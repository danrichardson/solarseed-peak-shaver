"""DataUpdateCoordinator for Solarseed Peak Shaver."""
from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, Event, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_BASE_LOAD,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_CHARGE_THRESHOLD,
    CONF_MIDPEAK_START,
    CONF_NOTIFICATIONS_ENABLED,
    CONF_NOTIFY_ENTITY,
    CONF_PEAK_END,
    CONF_PEAK_START,
    CONF_MIN_SAFE_SOC,
    CONF_SCHEDULE_HOURS,
    CONF_SEASONAL_MONTHS,
    CONF_SEASONAL_PRESERVATION,
    CONF_SOLAR_FORECAST_ENTITY,
    CONF_WEEKDAYS_ONLY,
    DEFAULT_BASE_LOAD,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_CHARGE_THRESHOLD,
    DEFAULT_MIDPEAK_START,
    DEFAULT_NOTIFICATIONS_ENABLED,
    DEFAULT_NOTIFY_ENTITY,
    DEFAULT_PEAK_END,
    DEFAULT_PEAK_START,
    DEFAULT_MIN_SAFE_SOC,
    DEFAULT_SCHEDULE_HOURS,
    DEFAULT_SEASONAL_MONTHS,
    DEFAULT_SEASONAL_PRESERVATION,
    DEFAULT_WEEKDAYS_ONLY,
    DOMAIN,
    EVENT_CHARGE_START,
    EVENT_CHARGE_STOP,
    EVENT_PRESERVE_START,
    SENSOR_BATTERY_AT_PEAK,
    SENSOR_CHARGE_NEEDED,
    SENSOR_PROJECTED_MIN,
    SENSOR_TARGET_SOC,
)

_LOGGER = logging.getLogger(__name__)


class PeakShaverCoordinator(DataUpdateCoordinator[dict[str, float]]):
    """Coordinator that calculates optimal battery charge targets for peak shaving."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
        )
        self.entry = entry
        # self._listeners: list[CALLBACK_TYPE] = []
        self._charging_active: bool = False

    # -----------------------------------------------------------------
    # Config accessors
    # -----------------------------------------------------------------
    def _cfg(self, key: str, default: Any = None) -> Any:
        """Get a config value, checking options first, then data."""
        if key in self.entry.options:
            return self.entry.options[key]
        return self.entry.data.get(key, default)

    @property
    def battery_capacity(self) -> float:
        return float(self._cfg(CONF_BATTERY_CAPACITY, DEFAULT_BATTERY_CAPACITY))

    @property
    def base_load_kw(self) -> float:
        return float(self._cfg(CONF_BASE_LOAD, DEFAULT_BASE_LOAD))

    @property
    def min_safe_soc(self) -> float:
        return float(self._cfg(CONF_MIN_SAFE_SOC, DEFAULT_MIN_SAFE_SOC))

    @property
    def midpeak_start(self) -> int:
        return int(self._cfg(CONF_MIDPEAK_START, DEFAULT_MIDPEAK_START))

    @property
    def peak_start(self) -> int:
        return int(self._cfg(CONF_PEAK_START, DEFAULT_PEAK_START))

    @property
    def peak_end(self) -> int:
        return int(self._cfg(CONF_PEAK_END, DEFAULT_PEAK_END))

    @property
    def weekdays_only(self) -> bool:
        return bool(self._cfg(CONF_WEEKDAYS_ONLY, DEFAULT_WEEKDAYS_ONLY))

    @property
    def battery_soc_entity(self) -> str:
        return str(self._cfg(CONF_BATTERY_SOC_ENTITY, ""))

    @property
    def solar_forecast_entity(self) -> str:
        return str(self._cfg(CONF_SOLAR_FORECAST_ENTITY, ""))

    @property
    def schedule_hours(self) -> list[int]:
        raw = self._cfg(
            CONF_SCHEDULE_HOURS,
            ",".join(str(h) for h in DEFAULT_SCHEDULE_HOURS),
        )
        if isinstance(raw, list):
            return [int(h) for h in raw]
        if isinstance(raw, str):
            try:
                return [int(h.strip()) for h in raw.split(",") if h.strip()]
            except ValueError:
                return list(DEFAULT_SCHEDULE_HOURS)
        return list(DEFAULT_SCHEDULE_HOURS)

    @property
    def notifications_enabled(self) -> bool:
        return bool(self._cfg(CONF_NOTIFICATIONS_ENABLED, DEFAULT_NOTIFICATIONS_ENABLED))

    @property
    def notify_entity(self) -> str:
        return str(self._cfg(CONF_NOTIFY_ENTITY, DEFAULT_NOTIFY_ENTITY))

    @property
    def charge_threshold(self) -> float:
        return float(self._cfg(CONF_CHARGE_THRESHOLD, DEFAULT_CHARGE_THRESHOLD))

    @property
    def seasonal_preservation(self) -> bool:
        return bool(self._cfg(CONF_SEASONAL_PRESERVATION, DEFAULT_SEASONAL_PRESERVATION))

    @property
    def seasonal_months(self) -> list[int]:
        raw = self._cfg(CONF_SEASONAL_MONTHS, DEFAULT_SEASONAL_MONTHS)
        if isinstance(raw, list):
            return [int(m) for m in raw]
        if isinstance(raw, str):
            try:
                return [int(m.strip()) for m in raw.split(",") if m.strip()]
            except ValueError:
                return list(DEFAULT_SEASONAL_MONTHS)
        return list(DEFAULT_SEASONAL_MONTHS)

    # -----------------------------------------------------------------
    # Notifications
    # -----------------------------------------------------------------
    def _notify(self, title: str, message: str) -> None:
        """Send a notification if enabled and configured."""
        if not self.notifications_enabled or not self.notify_entity:
            return

        service_target = self.notify_entity
        if "." in service_target:
            domain, service = service_target.split(".", 1)
        else:
            domain = "notify"
            service = service_target

        self.hass.async_create_task(
            self.hass.services.async_call(
                domain,
                service,
                {"title": title, "message": message},
            )
        )

    # -----------------------------------------------------------------
    # Listeners
    # -----------------------------------------------------------------
    def setup_listeners(self) -> None:
        """Register scheduled and event-based triggers."""
        # Scheduled hourly calculation runs
        for hour in self.schedule_hours:
            unsub = async_track_time_change(
                self.hass,
                self._on_scheduled_time,
                hour=hour,
                minute=0,
                second=0,
            )
            self._listeners.append(unsub)

        # Recalculate when solar forecast updates
        if self.solar_forecast_entity:
            unsub = async_track_state_change_event(
                self.hass,
                [self.solar_forecast_entity],
                self._on_forecast_update,
            )
            self._listeners.append(unsub)

        # Monitor battery SOC for target-reached detection
        if self.battery_soc_entity:
            unsub = async_track_state_change_event(
                self.hass,
                [self.battery_soc_entity],
                self._on_battery_update,
            )
            self._listeners.append(unsub)

        # Seasonal preservation trigger at peak_end + 5 minutes
        if self.seasonal_preservation:
            unsub = async_track_time_change(
                self.hass,
                self._on_preservation_time,
                hour=self.peak_end,
                minute=5,
                second=0,
            )
            self._listeners.append(unsub)

    def remove_listeners(self) -> None:
        """Remove all registered listeners."""
        for unsub in self._listeners:
            unsub()
        self._listeners.clear()

    @callback
    def _on_scheduled_time(self, now: datetime) -> None:
        """Handle scheduled recalculation."""
        if self.weekdays_only and now.weekday() >= 5:
            _LOGGER.debug("Skipped calculation (weekend)")
            return
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _on_forecast_update(self, event: Event) -> None:
        """Handle solar forecast state change.

        Recalculate from overnight through mid-peak, but not once peak
        has started - by then the only lever is mid-peak charging, which
        should already be in play.
        """
        now = datetime.now()

        if self.weekdays_only and now.weekday() >= 5:
            _LOGGER.debug("Forecast update ignored (weekend)")
            return

        earliest = self.schedule_hours[0] if self.schedule_hours else 3
        start = time(earliest, 0)
        end = time(self.peak_start, 0)

        if not (start <= now.time() <= end):
            _LOGGER.debug(
                "Forecast update ignored (outside %d:00-%d:00 window)",
                earliest,
                self.peak_start,
            )
            return

        _LOGGER.debug("Solar forecast updated - recalculating target")
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _on_battery_update(self, event: Event) -> None:
        """Monitor battery SOC and fire charge_stop when target is reached."""
        if not self._charging_active:
            return

        if self.data is None:
            return

        new_state = event.data.get("new_state")
        if new_state is None:
            return

        current_soc = self._safe_float(new_state.state)
        target_soc = self.data.get(SENSOR_TARGET_SOC, 0.0)

        if current_soc >= target_soc + 0.1:
            self._charging_active = False
            _LOGGER.info(
                "Battery reached target: %.2f kWh >= %.2f kWh",
                current_soc,
                target_soc,
            )

            self.hass.bus.async_fire(
                EVENT_CHARGE_STOP,
                {
                    "current_soc": round(current_soc, 2),
                    "target_soc": round(target_soc, 2),
                },
            )

            self._notify(
                "Solarseed - Charging Complete",
                f"Battery reached target: {current_soc:.1f} kWh "
                f"(target was {target_soc:.1f} kWh). "
                "Switching to solar priority.",
            )

    @callback
    def _on_preservation_time(self, now: datetime) -> None:
        """Fire preservation event during seasonal months.

        In low-solar months, preserve battery at end of peak instead of
        letting it drain overnight. Better to hold what you have and
        charge from cheap off-peak grid power in the early morning.
        """
        if now.month not in self.seasonal_months:
            return

        if self.weekdays_only and now.weekday() >= 5:
            return

        _LOGGER.info(
            "Seasonal preservation triggered (month %d, %d:%02d)",
            now.month,
            now.hour,
            now.minute,
        )

        soc_state = self.hass.states.get(self.battery_soc_entity)
        current_soc = self._safe_float(soc_state.state) if soc_state else 0.0

        self.hass.bus.async_fire(
            EVENT_PRESERVE_START,
            {
                "current_soc": round(current_soc, 2),
                "month": now.month,
            },
        )

        self._notify(
            "Solarseed - Preservation Mode",
            f"Preserving battery for overnight ({current_soc:.1f} kWh). "
            "Will recalculate at next scheduled run.",
        )

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------
    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        """Convert a value to float safely."""
        try:
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                return float(value.strip())
        except (ValueError, TypeError):
            pass
        return float(default)

    def _get_hourly_solar(self) -> dict[int, float]:
        """Parse hourly solar forecast into {hour: kWh}.

        Supports Solcast (detailedHourly / forecasts attributes) and
        Forecast.Solar (compatible forecast format).
        """
        state = self.hass.states.get(self.solar_forecast_entity)
        if state is None:
            _LOGGER.warning(
                "Solar forecast entity %s not found", self.solar_forecast_entity
            )
            return {}

        forecast_data = (
            state.attributes.get("detailedHourly")
            or state.attributes.get("forecasts")
            or state.attributes.get("forecast")
            or []
        )

        hourly: dict[int, float] = {}
        for entry in forecast_data:
            if not isinstance(entry, dict):
                continue
            period_start = entry.get("period_start", "")
            pv_estimate = self._safe_float(entry.get("pv_estimate", 0))

            if isinstance(period_start, str):
                try:
                    dt = datetime.fromisoformat(period_start)
                    hourly[dt.hour] = pv_estimate
                except (ValueError, AttributeError):
                    continue

        return hourly

    # -----------------------------------------------------------------
    # Core peak shaving calculation
    # -----------------------------------------------------------------
    async def _async_update_data(self) -> dict[str, float]:
        """Calculate the optimal battery charge target for peak shaving.

        Strategy:
        1. Figure out where the battery will be when rates start
        2. Simulate hour-by-hour through mid-peak + peak:
           solar production minus base load
        3. Find the minimum battery level during that simulation
        4. If it drops below the safety floor, calculate the deficit
        5. Target SOC = current SOC + deficit
        6. Fire events and notify based on result
        """
        capacity = self.battery_capacity
        load_kw = self.base_load_kw
        min_safe = self.min_safe_soc
        midpeak_start = self.midpeak_start
        peak_start = self.peak_start
        peak_end = self.peak_end

        # --- Current battery level ---
        soc_state = self.hass.states.get(self.battery_soc_entity)
        if soc_state is None:
            _LOGGER.error(
                "Battery SOC entity %s not found", self.battery_soc_entity
            )
            return self.data or {}

        current_soc = self._safe_float(soc_state.state)

        # --- Solar forecast ---
        hourly_solar = self._get_hourly_solar()
        if not hourly_solar:
            _LOGGER.warning(
                "No solar forecast data - using current SOC as target"
            )
            return {
                SENSOR_TARGET_SOC: current_soc,
                SENSOR_CHARGE_NEEDED: 0.0,
                SENSOR_PROJECTED_MIN: current_soc,
                SENSOR_BATTERY_AT_PEAK: current_soc,
            }

        now = datetime.now()
        current_hour = now.hour

        # --- Project battery level at mid-peak start ---
        battery_at_peak: float = current_soc
        sim_start: int = midpeak_start

        if current_hour < midpeak_start:
            hours_to_rates = midpeak_start - current_hour
            drain = hours_to_rates * load_kw
            battery_at_peak = current_soc - drain
            _LOGGER.debug(
                "Pre-rate: %dh drain of %.2f kWh, battery at mid-peak: %.2f",
                hours_to_rates,
                drain,
                battery_at_peak,
            )
        elif current_hour >= peak_end:
            hours_to_midnight = 24 - current_hour
            hours_after_midnight = midpeak_start
            hours_to_rates = hours_to_midnight + hours_after_midnight
            drain = hours_to_rates * load_kw
            battery_at_peak = current_soc - drain
            _LOGGER.debug(
                "Post-peak: %dh overnight drain of %.2f kWh, battery at mid-peak: %.2f",
                hours_to_rates,
                drain,
                battery_at_peak,
            )
        else:
            battery_at_peak = current_soc
            sim_start = current_hour
            _LOGGER.debug("In rate window: simulating from hour %d", current_hour)

        # --- Simulate through mid-peak + peak period ---
        battery_level = battery_at_peak
        min_battery = battery_level

        for hour in range(sim_start, peak_end):
            solar_kwh = hourly_solar.get(hour, 0.0)
            net = solar_kwh - load_kw
            battery_level += net
            min_battery = min(min_battery, battery_level)

            period = "MID" if hour < peak_start else "PEAK"

            _LOGGER.debug(
                "  %02d:00 [%s] | Solar: %.3f | Load: %.3f | Net: %+.3f | Battery: %.2f",
                hour,
                period,
                solar_kwh,
                load_kw,
                net,
                battery_level,
            )

        # --- Calculate target ---
        if min_battery < min_safe:
            deficit = min_safe - min_battery
            target_soc = current_soc + deficit
            _LOGGER.info(
                "Peak shaving deficit: need %.2f kWh additional charge", deficit
            )
        else:
            target_soc = current_soc
            _LOGGER.info("Battery survives peak period - no grid charge needed")

        target_soc = min(target_soc, capacity)
        charge_needed = max(target_soc - current_soc, 0.0)

        result = {
            SENSOR_TARGET_SOC: round(target_soc, 2),
            SENSOR_CHARGE_NEEDED: round(charge_needed, 2),
            SENSOR_PROJECTED_MIN: round(min_battery, 2),
            SENSOR_BATTERY_AT_PEAK: round(battery_at_peak, 2),
        }

        _LOGGER.info(
            "Peak shaver: target=%.2f kWh, charge_needed=%.2f kWh, "
            "projected_min=%.2f kWh",
            target_soc,
            charge_needed,
            min_battery,
        )

        # --- Fire events and notify ---
        solar_forecast_state = self.hass.states.get(self.solar_forecast_entity)
        solar_forecast_val = (
            self._safe_float(solar_forecast_state.state)
            if solar_forecast_state
            else 0.0
        )

        if charge_needed > self.charge_threshold:
            self._charging_active = True

            self.hass.bus.async_fire(
                EVENT_CHARGE_START,
                {
                    "current_soc": round(current_soc, 2),
                    "target_soc": round(target_soc, 2),
                    "charge_needed": round(charge_needed, 2),
                    "solar_forecast": round(solar_forecast_val, 2),
                },
            )

            self._notify(
                "Solarseed - Charging Required",
                f"Current: {current_soc:.1f} kWh | "
                f"Target: {target_soc:.1f} kWh | "
                f"Need: {charge_needed:.1f} kWh | "
                f"Solar forecast: {solar_forecast_val:.1f} kWh",
            )
        else:
            self._charging_active = False

            self.hass.bus.async_fire(
                EVENT_CHARGE_STOP,
                {
                    "current_soc": round(current_soc, 2),
                    "target_soc": round(target_soc, 2),
                },
            )

            self._notify(
                "Solarseed - Battery OK",
                f"No charging needed. "
                f"Current: {current_soc:.1f} kWh | "
                f"Target: {target_soc:.1f} kWh | "
                f"Solar forecast: {solar_forecast_val:.1f} kWh",
            )

        return result
