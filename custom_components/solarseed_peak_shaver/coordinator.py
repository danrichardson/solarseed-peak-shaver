"""DataUpdateCoordinator for Solarseed Peak Shaver."""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, Event, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_BASE_LOAD,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_BUS_VOLTAGE_ENTITY,
    CONF_CAPACITY_V_HIGH,
    CONF_CAPACITY_V_LOW,
    CONF_CHARGE_THRESHOLD,
    CONF_FULL_CHARGE_MONTHS,
    CONF_GAUGE_ENTITY,
    CONF_GAUGE_FLOOR,
    CONF_GRID_POWER_ENTITY,
    CONF_HOLIDAY_DATES,
    CONF_HOLIDAY_PRESET,
    CONF_HOLIDAY_RULES,
    CONF_LOAD_POWER_ENTITY,
    CONF_LOAD_QUANTILE,
    CONF_MIDPEAK_PRICE,
    CONF_MIDPEAK_START,
    CONF_NOTIFICATIONS_ENABLED,
    CONF_OFFPEAK_PRICE,
    CONF_NOTIFY_ENTITY,
    CONF_PACK_CAPACITY_AH,
    CONF_PACK_CURRENT_CHARGE_POSITIVE,
    CONF_PACK_CURRENT_ENTITIES,
    CONF_PEAK_END,
    CONF_PEAK_MARGIN_KWH,
    CONF_PEAK_PRICE,
    CONF_PEAK_START,
    CONF_PLANNER,
    CONF_PV_POWER_ENTITY,
    CONF_MIN_SAFE_SOC,
    CONF_RECOVERY_PCT,
    CONF_SCHEDULE_HOURS,
    CONF_SEASONAL_MONTHS,
    CONF_SEASONAL_PRESERVATION,
    CONF_SOLAR_ACTUAL_ENTITY,
    CONF_SOLAR_CONFIDENCE,
    CONF_SOLAR_FORECAST_ENTITY,
    CONF_SOLAR_FORECAST_TOMORROW_ENTITY,
    CONF_STALE_MINUTES,
    CONF_TARIFF_SEASONS,
    CONF_VERBOSE_LOGGING,
    CONF_WEEKDAYS_ONLY,
    DEFAULT_BASE_LOAD,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_CAPACITY_V_HIGH,
    DEFAULT_CAPACITY_V_LOW,
    DEFAULT_CHARGE_THRESHOLD,
    DEFAULT_FULL_CHARGE_MONTHS,
    DEFAULT_GAUGE_FLOOR,
    DEFAULT_HOLIDAY_DATES,
    DEFAULT_HOLIDAY_PRESET,
    DEFAULT_LOAD_QUANTILE,
    DEFAULT_MIDPEAK_PRICE,
    DEFAULT_MIDPEAK_START,
    DEFAULT_NOTIFICATIONS_ENABLED,
    DEFAULT_NOTIFY_ENTITY,
    DEFAULT_OFFPEAK_PRICE,
    DEFAULT_PACK_CAPACITY_AH,
    DEFAULT_PACK_CURRENT_CHARGE_POSITIVE,
    DEFAULT_PEAK_END,
    DEFAULT_PEAK_MARGIN_KWH,
    DEFAULT_PEAK_PRICE,
    DEFAULT_PEAK_START,
    DEFAULT_PLANNER,
    DEFAULT_MIN_SAFE_SOC,
    DEFAULT_RECOVERY_PCT,
    DEFAULT_SCHEDULE_HOURS,
    DEFAULT_SEASONAL_MONTHS,
    DEFAULT_SEASONAL_PRESERVATION,
    DEFAULT_SOLAR_ACTUAL_ENTITY,
    DEFAULT_SOLAR_CONFIDENCE,
    DEFAULT_STALE_MINUTES,
    DEFAULT_TARIFF_SEASONS,
    DEFAULT_VERBOSE_LOGGING,
    DEFAULT_WEEKDAYS_ONLY,
    DOMAIN,
    EVENT_CHARGE_START,
    EVENT_CHARGE_STOP,
    EVENT_PRESERVE_START,
    PLANNER_CLASSIC,
    PLANNER_LEARNED,
    STARTUP_CONFIRM_SECONDS,
    SENSOR_BATTERY_AT_PEAK,
    SENSOR_CHARGE_BELOW,
    SENSOR_CHARGE_NEEDED,
    SENSOR_PROJECTED_MIN,
    SENSOR_TARGET_SOC,
)
from .holidays import HolidayCalendar, build_calendar, is_tou_day, normalize_preset
from .health import HEALTH_REVIEW, daily_message, grade_day, review_message
from .health import status as health_status
from .store import PeakShaverStore
from .tariff import Tariff, Windows, build_tariff

_LOGGER = logging.getLogger(__name__)


class PeakShaverCoordinator(DataUpdateCoordinator[dict[str, float]]):
    """Coordinator that calculates optimal battery charge targets for peak shaving."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, store: PeakShaverStore
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
        )
        self.entry = entry
        self.store = store
        self._unsub_listeners: list[CALLBACK_TYPE] = []
        self._charging_active: bool = False
        # The first calculation after a (re)start never stops a charge or releases a hold
        # (0.7.0 released a hold that way), and a charge it wants is only started after a
        # second look STARTUP_CONFIRM_SECONDS later (0.8.0 started one on a bogus 0.0 kWh).
        self._events_armed: bool = False
        self._startup_recheck_unsub: CALLBACK_TYPE | None = None
        self._recheck_restricted: bool = False
        self._skipped_for: str | None = None    # "battery" or "forecast" while a calculation is skipped
        self.last_simulation_csv: str = ""
        self.last_simulation_summary: str = ""

        # --- Performance tracking (daily, reset by _reset_daily_tracking) ---
        self._tracking_date: str | None = None
        self.prediction_snapshots: list[dict] = []
        self.actual_soc_checkpoints: dict[str, float] = {}
        self.actual_solar_hourly: dict[int, float] = {}
        self._last_solar_actual_reading: float | None = None
        self.charge_events_today: list[dict] = []
        self._charge_start_time: datetime | None = None
        self._charge_start_soc: float = 0.0
        self._daily_min_soc: float = float("inf")
        self._daily_min_tracking: bool = False
        self.last_daily_scorecard: dict = {}

        # Learned model + planner (0.7.0). Created in async_setup_entry; None in old tests.
        self.learned: Any = None
        # setup_signature() when this entry started; a saved change to it reloads (0.9.0)
        self.started_with: dict[str, Any] = {}

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

    # --- The tariff (0.9.1). The three hour options are the base windows; a season can
    # change them by month, so the hours below are the ones in force today. ---
    @property
    def midpeak_start(self) -> int:
        return self.windows_on(self._now().date()).midpeak_start

    @property
    def peak_start(self) -> int:
        return self.windows_on(self._now().date()).peak_start

    @property
    def peak_end(self) -> int:
        return self.windows_on(self._now().date()).peak_end

    @property
    def weekdays_only(self) -> bool:
        return bool(self._cfg(CONF_WEEKDAYS_ONLY, DEFAULT_WEEKDAYS_ONLY))

    @property
    def holiday_preset(self) -> str:
        """Utility holidays that are off-peak all day; absent key = PGE, unknown = none."""
        return normalize_preset(self._cfg(CONF_HOLIDAY_PRESET, DEFAULT_HOLIDAY_PRESET))

    @property
    def holiday_calendar(self) -> HolidayCalendar:
        """The preset's rules (the typed ones when it is custom) plus one-off dates."""
        return build_calendar(self.holiday_preset, self._text_cfg(CONF_HOLIDAY_RULES),
                              self._text_cfg(CONF_HOLIDAY_DATES, DEFAULT_HOLIDAY_DATES))

    def _text_cfg(self, key: str, default: str = "") -> str:
        val = self._cfg(key, default)
        return "" if val is None else str(val)

    def _price_cfg(self, key: str, default: float | None) -> float | None:
        """A price per kWh; empty means not given, anything unreadable the default."""
        raw = self._cfg(key, default)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return None
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return default
        return val if math.isfinite(val) and val >= 0 else default

    def _hour_cfg(self, key: str, default: int) -> int:
        try:
            return int(float(self._cfg(key, default)))
        except (TypeError, ValueError):
            return default

    @property
    def tariff(self) -> Tariff:
        """Periods, prices, seasons and holidays, from the options (PGE Time of Day when
        none is stored). Built once per distinct set of options."""
        return build_tariff(
            self._hour_cfg(CONF_MIDPEAK_START, DEFAULT_MIDPEAK_START),
            self._hour_cfg(CONF_PEAK_START, DEFAULT_PEAK_START),
            self._hour_cfg(CONF_PEAK_END, DEFAULT_PEAK_END),
            self.weekdays_only,
            self._price_cfg(CONF_OFFPEAK_PRICE, DEFAULT_OFFPEAK_PRICE),
            self._price_cfg(CONF_MIDPEAK_PRICE, DEFAULT_MIDPEAK_PRICE),
            self._price_cfg(CONF_PEAK_PRICE, DEFAULT_PEAK_PRICE),
            self._text_cfg(CONF_TARIFF_SEASONS, DEFAULT_TARIFF_SEASONS),
            self.holiday_calendar,
        )

    def windows_on(self, d: date) -> Windows:
        """The mid-peak and peak hours that apply on `d`'s season."""
        return self.tariff.windows_on(d)

    def period_at(self, when: datetime) -> str:
        """off-peak, mid-peak or peak at `when`, with the day type (off-peak all day on a
        day that is not a TOU day)."""
        return self.tariff.period_at(when)

    def is_tou_day(self, d: date) -> bool:
        """Do the mid-peak and peak windows apply on `d`? (weekday rule and holidays)"""
        return is_tou_day(d, self.weekdays_only, self.holiday_calendar)

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
    def verbose_logging(self) -> bool:
        return bool(self._cfg(CONF_VERBOSE_LOGGING, DEFAULT_VERBOSE_LOGGING))

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

    @property
    def solar_actual_entity(self) -> str:
        return str(self._cfg(CONF_SOLAR_ACTUAL_ENTITY, DEFAULT_SOLAR_ACTUAL_ENTITY))

    # --- Learned planner settings (all optional) ---
    @property
    def planner(self) -> str:
        """Which planner controls the inverter: "classic" or "learned"."""
        val = str(self._cfg(CONF_PLANNER, DEFAULT_PLANNER) or DEFAULT_PLANNER).strip().lower()
        return PLANNER_LEARNED if val == PLANNER_LEARNED else PLANNER_CLASSIC

    def _entity_cfg(self, key: str) -> str:
        return str(self._cfg(key, "") or "").strip()

    @property
    def gauge_entity(self) -> str:
        return self._entity_cfg(CONF_GAUGE_ENTITY)

    @property
    def load_power_entity(self) -> str:
        return self._entity_cfg(CONF_LOAD_POWER_ENTITY)

    @property
    def grid_power_entity(self) -> str:
        return self._entity_cfg(CONF_GRID_POWER_ENTITY)

    @property
    def pv_power_entity(self) -> str:
        return self._entity_cfg(CONF_PV_POWER_ENTITY)

    @property
    def solar_forecast_tomorrow_entity_resolved(self) -> str:
        """Tomorrow's forecast entity: the configured one, else guessed from today's."""
        explicit = self._entity_cfg(CONF_SOLAR_FORECAST_TOMORROW_ENTITY)
        if explicit:
            return explicit
        today = self.solar_forecast_entity
        if "today" in today:
            guess = today.replace("today", "tomorrow")
            if self.hass.states.get(guess) is not None:
                return guess
        return ""

    @property
    def full_charge_months(self) -> list[int]:
        raw = self._cfg(CONF_FULL_CHARGE_MONTHS, DEFAULT_FULL_CHARGE_MONTHS)
        if isinstance(raw, list):
            return [int(m) for m in raw]
        if isinstance(raw, str):
            try:
                return [int(m.strip()) for m in raw.split(",") if m.strip()]
            except ValueError:
                return list(DEFAULT_FULL_CHARGE_MONTHS)
        return list(DEFAULT_FULL_CHARGE_MONTHS)

    def _num_cfg(self, key: str, default: float, lo: float, hi: float) -> float:
        try:
            return min(max(float(self._cfg(key, default)), lo), hi)
        except (TypeError, ValueError):
            return default

    @property
    def load_quantile(self) -> float:
        return self._num_cfg(CONF_LOAD_QUANTILE, DEFAULT_LOAD_QUANTILE, 0.0, 1.0)

    @property
    def solar_confidence(self) -> float:
        return self._num_cfg(CONF_SOLAR_CONFIDENCE, DEFAULT_SOLAR_CONFIDENCE, 0.0, 1.5)

    @property
    def gauge_floor(self) -> float:
        return self._num_cfg(CONF_GAUGE_FLOOR, DEFAULT_GAUGE_FLOOR, 0.0, 50.0)

    @property
    def recovery_pct(self) -> float:
        """Gauge the inverter grid-charges back to after a handover at the floor."""
        return self._num_cfg(CONF_RECOVERY_PCT, DEFAULT_RECOVERY_PCT, 0.0, 100.0)

    @property
    def peak_margin_kwh(self) -> float:
        """Reserve the learned planner keeps above the floor at peak end."""
        return self._num_cfg(CONF_PEAK_MARGIN_KWH, DEFAULT_PEAK_MARGIN_KWH, 0.0, 20.0)

    @property
    def stale_minutes(self) -> float:
        """Minutes without any change in the battery readings that count as frozen. 0 = off."""
        return self._num_cfg(CONF_STALE_MINUTES, DEFAULT_STALE_MINUTES, 0.0, 1440.0)

    # --- Third-party packs (all optional) ---
    @property
    def pack_current_entities(self) -> list[str]:
        raw = self._cfg(CONF_PACK_CURRENT_ENTITIES, []) or []
        if isinstance(raw, str):
            raw = raw.split(",")
        out: list[str] = []
        for e in raw:
            e = str(e).strip()
            if e and e not in out:
                out.append(e)
        return out

    @property
    def pack_current_charge_positive(self) -> bool:
        return bool(self._cfg(CONF_PACK_CURRENT_CHARGE_POSITIVE, DEFAULT_PACK_CURRENT_CHARGE_POSITIVE))

    @property
    def bus_voltage_entity(self) -> str:
        return self._entity_cfg(CONF_BUS_VOLTAGE_ENTITY)

    @property
    def pack_capacity_ah(self) -> float:
        return self._num_cfg(CONF_PACK_CAPACITY_AH, DEFAULT_PACK_CAPACITY_AH, 1.0, 10000.0)

    @property
    def capacity_v_high(self) -> float:
        return self._num_cfg(CONF_CAPACITY_V_HIGH, DEFAULT_CAPACITY_V_HIGH, 0.0, 1000.0)

    @property
    def capacity_v_low(self) -> float:
        return self._num_cfg(CONF_CAPACITY_V_LOW, DEFAULT_CAPACITY_V_LOW, 0.0, 1000.0)

    def setup_signature(self) -> dict[str, Any]:
        """The settings read once at start (timers, state listeners, pack sensors), as the
        integration understands them. A saved change to any of these reloads the entry
        (`options.RELOAD_KEYS`); everything else is read live. The timers are set for the
        hours of every season, so only a season's hours count, not its months or prices."""
        tariff = self.tariff
        return {
            CONF_BATTERY_SOC_ENTITY: self.battery_soc_entity.strip(),
            CONF_SOLAR_FORECAST_ENTITY: self.solar_forecast_entity.strip(),
            CONF_SOLAR_ACTUAL_ENTITY: self.solar_actual_entity.strip(),
            CONF_MIDPEAK_START: tariff.windows.midpeak_start,
            CONF_PEAK_START: tariff.windows.peak_start,
            CONF_PEAK_END: tariff.windows.peak_end,
            CONF_TARIFF_SEASONS: tuple((w.midpeak_start, w.peak_start, w.peak_end)
                                       for w in tariff.all_windows()),
            CONF_SCHEDULE_HOURS: tuple(self.schedule_hours),
            CONF_SEASONAL_PRESERVATION: self.seasonal_preservation,
            CONF_PACK_CURRENT_ENTITIES: tuple(self.pack_current_entities),
        }

    @property
    def battery_data_stale(self) -> bool:
        """True while the learned runtime sees the battery readings frozen."""
        runtime = getattr(self, "learned", None)
        return bool(runtime is not None and getattr(runtime, "data_stale", False))

    # -----------------------------------------------------------------
    # Notifications
    # -----------------------------------------------------------------
    def _notify(self, title: str, message: str, urgent: bool = False) -> None:
        """Send a notification if enabled and configured.

        `urgent` asks the phone app for an immediate, high-priority delivery (mobile_app
        data keys); a notify service that rejects them gets the plain message instead.
        """
        if not self.notifications_enabled or not self.notify_entity:
            return

        service_target = self.notify_entity
        if "." in service_target:
            domain, service = service_target.split(".", 1)
        else:
            domain = "notify"
            service = service_target

        payload = {"title": title, "message": message}
        if urgent:
            self.hass.async_create_task(self._async_notify_urgent(domain, service, payload))
            return
        self.hass.async_create_task(
            self.hass.services.async_call(domain, service, payload)
        )

    async def _async_notify_urgent(self, domain: str, service: str, payload: dict[str, Any]) -> None:
        try:
            await self.hass.services.async_call(
                domain, service,
                {**payload, "data": {"ttl": 0, "priority": "high",
                                     "push": {"interruption-level": "time-sensitive"}}},
            )
        except Exception:  # noqa: BLE001 - not every notify service takes these keys
            _LOGGER.warning("Notify service %s.%s rejected the priority options; sending plainly",
                            domain, service)
            await self.hass.services.async_call(domain, service, payload)

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
            self._unsub_listeners.append(unsub)

        # Recalculate when solar forecast updates
        if self.solar_forecast_entity:
            unsub = async_track_state_change_event(
                self.hass,
                [self.solar_forecast_entity],
                self._on_forecast_update,
            )
            self._unsub_listeners.append(unsub)

        # Monitor battery SOC for target-reached detection
        if self.battery_soc_entity:
            unsub = async_track_state_change_event(
                self.hass,
                [self.battery_soc_entity],
                self._on_battery_update,
            )
            self._unsub_listeners.append(unsub)

        # The tariff's hours: one set, or one per season (0.9.1). Each timer is set for every
        # season's hour and acts only when the hour is that day's own.
        windows = self.tariff.all_windows()
        end_hours = sorted({w.peak_end % 24 for w in windows})

        # Seasonal preservation trigger at peak_end + 5 minutes
        if self.seasonal_preservation:
            for end_hour in end_hours:
                unsub = async_track_time_change(
                    self.hass,
                    self._on_preservation_time,
                    hour=end_hour,
                    minute=5,
                    second=0,
                )
                self._unsub_listeners.append(unsub)

        # --- Performance tracking listeners ---

        # SOC checkpoints at midpeak_start, peak_start, peak_end
        ckpt_hours = sorted({h % 24 for w in windows for h in (w.midpeak_start, w.peak_start, w.peak_end)})
        for ckpt_hour in ckpt_hours:
            unsub = async_track_time_change(
                self.hass,
                self._on_soc_checkpoint,
                hour=ckpt_hour,
                minute=0,
                second=30,
            )
            self._unsub_listeners.append(unsub)

        # Hourly solar actual sampling during rate window
        if self.solar_actual_entity:
            sample_hours = sorted({h % 24 for w in windows for h in range(w.midpeak_start, w.peak_end + 1)})
            for sample_hour in sample_hours:
                unsub = async_track_time_change(
                    self.hass,
                    self._on_solar_actual_sample,
                    hour=sample_hour,
                    minute=0,
                    second=15,
                )
                self._unsub_listeners.append(unsub)

        # Daily scoring at peak_end + 10 minutes
        for end_hour in end_hours:
            unsub = async_track_time_change(
                self.hass,
                self._on_daily_scoring_time,
                hour=end_hour,
                minute=10,
                second=0,
            )
            self._unsub_listeners.append(unsub)

    def remove_listeners(self) -> None:
        """Remove all registered listeners."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()
        if self._startup_recheck_unsub is not None:
            self._startup_recheck_unsub()
            self._startup_recheck_unsub = None

    @callback
    def _on_scheduled_time(self, now: datetime) -> None:
        """Handle scheduled recalculation."""
        if not self.is_tou_day(now.date()):
            _LOGGER.debug("Skipped calculation (not a TOU day)")
            return
        self.hass.async_create_task(self.async_request_refresh())

    def _schedule_startup_recheck(self) -> None:
        """Arrange the second look at a charge the first calculation after a start wanted."""
        if self._startup_recheck_unsub is not None:
            return
        self._startup_recheck_unsub = async_call_later(
            self.hass, STARTUP_CONFIRM_SECONDS, self._on_startup_recheck
        )

    @callback
    def _on_startup_recheck(self, _now: datetime) -> None:
        """The second look: recalculate. It may start a charge but never stop one."""
        self._startup_recheck_unsub = None
        self._recheck_restricted = True
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _on_forecast_update(self, event: Event) -> None:
        """Handle solar forecast state change.

        Recalculate from overnight through mid-peak, but not once peak
        has started - by then the only lever is mid-peak charging, which
        should already be in play.
        """
        now = datetime.now()

        if not self.is_tou_day(now.date()):
            _LOGGER.debug("Forecast update ignored (not a TOU day)")
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
        """Monitor battery SOC for target-reached and daily minimum tracking."""
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        current_soc = self._read_float(new_state.state)
        if current_soc is None:
            return  # unavailable or unknown is a gap, not an empty battery

        # The last calculation was skipped for want of this reading: it is back, so calculate
        # now instead of waiting for the next scheduled run (the first calculation after a
        # start is still the restricted one).
        if self._skipped_for == "battery":
            self.hass.async_create_task(self.async_request_refresh())

        # Track daily minimum during rate window
        if self._daily_min_tracking:
            self._daily_min_soc = min(self._daily_min_soc, current_soc)

        # Check for charge target reached
        if not self._charging_active or self.planner == PLANNER_LEARNED:
            return

        if not self.data:
            return

        target_soc = self.data.get(SENSOR_TARGET_SOC)
        if target_soc is None:
            return  # no calculation yet, so no target to reach

        if current_soc >= target_soc + 0.1:
            self._charging_active = False
            _LOGGER.info(
                "Battery reached target: %.2f kWh >= %.2f kWh",
                current_soc,
                target_soc,
            )

            # Record charge event
            if self._charge_start_time:
                now = datetime.now()
                energy = current_soc - self._charge_start_soc
                period = self._classify_period(self._charge_start_time)
                self.charge_events_today.append({
                    "charge_start_time": self._charge_start_time.isoformat(),
                    "charge_stop_time": now.isoformat(),
                    "soc_at_start": round(self._charge_start_soc, 2),
                    "soc_at_stop": round(current_soc, 2),
                    "energy_charged_kwh": round(max(energy, 0), 2),
                    "period": period,
                })
                self._charge_start_time = None

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
        """Fire hold event during low-solar months.

        When solar won't refill the battery, hold what you have after peak
        and draw from the grid for household needs. The next morning's
        scheduled calculation takes over from there.
        """
        if now.month not in self.seasonal_months:
            return

        if not self.is_tou_day(now.date()):
            return

        if now.hour != self.windows_on(now.date()).peak_end % 24:
            return  # another season's peak end

        if self.planner == PLANNER_LEARNED:
            return  # the learned planner decides when to hold

        _LOGGER.info(
            "Off-peak battery hold triggered (month %d, %d:%02d)",
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
            "Solarseed - Off-Peak Hold",
            f"Holding battery at {current_soc:.1f} kWh - drawing from grid "
            "until next scheduled charge calculation.",
        )

    @callback
    def _on_soc_checkpoint(self, now: datetime) -> None:
        """Record battery SOC at key rate window timestamps."""
        if not self.is_tou_day(now.date()):
            return
        soc_state = self.hass.states.get(self.battery_soc_entity)
        if soc_state is None:
            return
        current_soc = self._read_float(soc_state.state)
        if current_soc is None:
            return  # no checkpoint beats a checkpoint of 0 kWh
        hour = now.hour
        w = self.windows_on(now.date())

        if hour == w.midpeak_start:
            self.actual_soc_checkpoints["midpeak_start"] = round(current_soc, 2)
            self._daily_min_soc = current_soc
            self._daily_min_tracking = True
            if w.peak_start == w.midpeak_start:     # no mid-peak window: peak starts now too
                self.actual_soc_checkpoints["peak_start"] = round(current_soc, 2)
        elif hour == w.peak_start:
            self.actual_soc_checkpoints["peak_start"] = round(current_soc, 2)
        elif hour == w.peak_end % 24:
            self.actual_soc_checkpoints["peak_end"] = round(current_soc, 2)
            # After a restart inside the window, tracking never started and the day's
            # minimum is unknown (it was infinity, which crashed scoring on 2026-11-19).
            if self._daily_min_tracking and math.isfinite(self._daily_min_soc):
                self.actual_soc_checkpoints["daily_min"] = round(
                    min(self._daily_min_soc, current_soc), 2
                )
            self._daily_min_tracking = False

        _LOGGER.debug("SOC checkpoint at %d:00 = %.2f kWh", hour, current_soc)

    @callback
    def _on_solar_actual_sample(self, now: datetime) -> None:
        """Sample cumulative solar production to derive hourly actuals."""
        entity_id = self.solar_actual_entity
        if not entity_id:
            return
        w = self.windows_on(now.date())
        if now.hour not in {h % 24 for h in range(w.midpeak_start, w.peak_end + 1)}:
            return  # another season's hour
        state = self.hass.states.get(entity_id)
        if state is None:
            return
        current_reading = self._safe_float(state.state)
        hour = now.hour

        if self._last_solar_actual_reading is not None:
            prev_hour = (hour - 1) % 24
            delta = max(current_reading - self._last_solar_actual_reading, 0.0)
            self.actual_solar_hourly[prev_hour] = round(delta, 3)
            _LOGGER.debug(
                "Solar actual: hour %d = %.3f kWh (cumulative: %.3f)",
                prev_hour, delta, current_reading,
            )
        self._last_solar_actual_reading = current_reading

    @callback
    def _on_daily_scoring_time(self, now: datetime) -> None:
        """Run daily performance scoring after peak ends."""
        if not self.is_tou_day(now.date()):
            return
        if now.hour != self.windows_on(now.date()).peak_end % 24:
            return  # another season's peak end
        self.hass.async_create_task(self._async_score_daily_performance())

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

    @staticmethod
    def _read_float(value: Any) -> float | None:
        """A sensor reading as a float, or None when there is no usable reading.

        "unavailable", "unknown", an empty or non-numeric string, NaN and infinity are
        all missing. Use this for the battery: `_safe_float` turns a missing reading
        into 0.0, which the planner takes for an empty battery.
        """
        if value is None:
            return None
        try:
            number = float(str(value).strip())
        except ValueError:
            return None
        return number if math.isfinite(number) else None

    def _now(self) -> datetime:
        """Local time; one place to override in tests."""
        return datetime.now()

    def _classify_period(self, dt: datetime) -> str:
        """Classify a datetime into off-peak, mid-peak, or peak by the hour alone (the
        hours of its date's season); `period_at` also knows weekends and holidays."""
        return self.windows_on(dt.date()).period(dt.hour)

    def _reset_daily_tracking(self) -> None:
        """Reset all daily performance tracking data if the date changed."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self._tracking_date == today:
            return

        _LOGGER.debug("Resetting daily tracking for %s", today)
        self._tracking_date = today
        self.prediction_snapshots = []
        self.actual_soc_checkpoints = {}
        self.actual_solar_hourly = {}
        self._last_solar_actual_reading = None
        self.charge_events_today = []
        self._charge_start_time = None
        self._charge_start_soc = 0.0
        self._daily_min_soc = float("inf")
        self._daily_min_tracking = False

    def _record_prediction_snapshot(
        self,
        run_type: str,
        current_soc: float,
        battery_at_peak: float,
        min_battery: float,
        target_soc: float,
        charge_needed: float,
        charge_below: float,
        hourly_solar: dict[int, float],
        charging_triggered: bool,
    ) -> None:
        """Store a timestamped prediction snapshot."""
        self.prediction_snapshots.append({
            "timestamp": datetime.now().isoformat(),
            "run_type": run_type,
            "current_soc_kwh": round(current_soc, 2),
            "predicted_battery_at_midpeak": round(battery_at_peak, 2),
            "predicted_minimum_kwh": round(min_battery, 2),
            "target_soc_kwh": round(target_soc, 2),
            "charge_needed_kwh": round(charge_needed, 2),
            "charge_below_kwh": round(charge_below, 2),
            "hourly_solar_forecast": {
                str(h): round(v, 3) for h, v in hourly_solar.items()
            },
            "base_load_used": round(self.effective_base_load, 2),
            "solar_correction_factor": round(self.solar_correction_factor, 3),
            "charging_triggered": charging_triggered,
        })

    # -----------------------------------------------------------------
    # Feedback loop: correction factors from historical data
    # -----------------------------------------------------------------
    @property
    def solar_correction_factor(self) -> float:
        """Global solar correction factor from rolling history."""
        if not self.store or len(self.store.days) < 3:
            return 1.0
        factor = self.store.rolling_solar_accuracy(days=14)
        return max(0.5, min(1.2, factor))

    def _get_solar_correction(self, hour: int) -> float:
        """Per-hour solar correction, falling back to global factor."""
        if not self.store or len(self.store.days) < 7:
            return 1.0

        hourly = self.store.hourly_solar_ratios(days=14)
        if hour in hourly:
            return max(0.5, min(1.5, hourly[hour]))
        return self.solar_correction_factor

    @property
    def effective_base_load(self) -> float:
        """Dynamic base load from rolling history, or configured value."""
        if not self.store or len(self.store.days) < 3:
            return self.base_load_kw
        rolling = self.store.rolling_base_load(days=14)
        if rolling is None:
            return self.base_load_kw
        return rolling

    # -----------------------------------------------------------------
    # Daily performance scoring
    # -----------------------------------------------------------------
    async def _async_score_daily_performance(self) -> None:
        """Score today's performance and persist the result."""
        today = datetime.now().strftime("%Y-%m-%d")

        if not self.prediction_snapshots:
            _LOGGER.debug("No prediction snapshots for scoring on %s", today)
            await self._async_score_health_only(today)
            return

        # Use the earliest snapshot as the primary prediction
        primary = self.prediction_snapshots[0]

        predicted_solar: dict[str, float] = primary.get(
            "hourly_solar_forecast", {}
        )
        predicted_min = primary.get("predicted_minimum_kwh", 0)
        predicted_at_midpeak = primary.get("predicted_battery_at_midpeak", 0)

        actual_min = self.actual_soc_checkpoints.get("daily_min")
        if actual_min is not None and not math.isfinite(actual_min):
            actual_min = None
        actual_at_midpeak = self.actual_soc_checkpoints.get("midpeak_start")

        # Solar accuracy
        predicted_solar_total = sum(predicted_solar.values())
        actual_solar_total = (
            sum(self.actual_solar_hourly.values())
            if self.actual_solar_hourly
            else None
        )

        solar_accuracy_pct = None
        if actual_solar_total is not None and predicted_solar_total > 0:
            solar_accuracy_pct = round(
                (actual_solar_total / predicted_solar_total) * 100, 1
            )

        # Prediction errors
        midpeak_error = None
        if actual_at_midpeak is not None and predicted_at_midpeak:
            midpeak_error = round(predicted_at_midpeak - actual_at_midpeak, 2)

        min_error = None
        if actual_min is not None and predicted_min:
            min_error = round(predicted_min - actual_min, 2)

        # Outcomes
        floor_breached = (
            actual_min is not None and actual_min < self.min_safe_soc
        )

        midpeak_charge = any(
            e.get("period") in ("mid-peak", "peak")
            for e in self.charge_events_today
        )

        total_charged = sum(
            e.get("energy_charged_kwh", 0) for e in self.charge_events_today
        )

        # Unnecessary charge = charged more than the deficit
        first_charge_needed = primary.get("charge_needed_kwh", 0)
        unnecessary = (
            max(total_charged - first_charge_needed, 0)
            if total_charged > 0
            else 0
        )

        # Effective base load derivation
        effective_base_load = None
        if (
            actual_solar_total is not None
            and actual_at_midpeak is not None
            and self.actual_soc_checkpoints.get("peak_end") is not None
        ):
            soc_start = actual_at_midpeak
            soc_end = self.actual_soc_checkpoints["peak_end"]
            hours = self.peak_end - self.midpeak_start
            if hours > 0:
                total_consumption = (
                    actual_solar_total + (soc_start - soc_end) - total_charged
                )
                effective_base_load = round(
                    max(total_consumption / hours, 0), 2
                )

        # --- Scoring ---
        score = 100

        if floor_breached:
            score -= 30

        if midpeak_charge:
            score -= 25

        if solar_accuracy_pct is not None:
            solar_error = abs(100 - solar_accuracy_pct)
            if solar_error > 20:
                score -= min(int(solar_error - 20), 15)

        if min_error is not None:
            abs_error = abs(min_error)
            if abs_error > 2:
                score -= min(int((abs_error - 2) / 0.5), 15)

        if unnecessary > 2:
            score -= min(int(unnecessary - 2), 15)

        score = max(score, 0)

        if score >= 90:
            grade = "A"
        elif score >= 80:
            grade = "B"
        elif score >= 70:
            grade = "C"
        elif score >= 60:
            grade = "D"
        else:
            grade = "F"

        scorecard: dict[str, Any] = {
            "date": today,
            "grade": grade,
            "score": score,
            "solar_predicted_kwh": round(predicted_solar_total, 2),
            "solar_actual_kwh": (
                round(actual_solar_total, 2)
                if actual_solar_total is not None
                else None
            ),
            "solar_accuracy_pct": solar_accuracy_pct,
            "battery_at_midpeak_predicted": round(predicted_at_midpeak, 2),
            "battery_at_midpeak_actual": (
                round(actual_at_midpeak, 2)
                if actual_at_midpeak is not None
                else None
            ),
            "midpeak_prediction_error_kwh": midpeak_error,
            "battery_min_predicted": round(predicted_min, 2),
            "battery_min_actual": (
                round(actual_min, 2) if actual_min is not None else None
            ),
            "min_prediction_error_kwh": min_error,
            "min_safe_soc": self.min_safe_soc,
            "floor_breached": floor_breached,
            "midpeak_charge_triggered": midpeak_charge,
            "total_charged_kwh": round(total_charged, 2),
            "unnecessary_charge_kwh": round(unnecessary, 2),
            "charge_events": self.charge_events_today.copy(),
            "effective_base_load_kw": effective_base_load,
            "hourly_solar_predicted": {
                str(h): v for h, v in predicted_solar.items()
            },
            "hourly_solar_actual": {
                str(h): v for h, v in self.actual_solar_hourly.items()
            },
            "solar_correction_factor": round(self.solar_correction_factor, 3),
            "prediction_snapshots_count": len(self.prediction_snapshots),
        }

        # What the learned planner thought and saw today (new keys only).
        if getattr(self, "learned", None) is not None:
            try:
                scorecard["learned"] = self.learned.daily_summary()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Could not add learned-planner summary to the scorecard")

        # How the day actually went, from the meters (new key; the grade fields stay).
        day_health = self._grade_health(today, scorecard.get("learned"))
        if day_health is not None:
            scorecard["health"] = day_health

        self.last_daily_scorecard = scorecard
        self._mark_scored(today, day_health is not None)

        # Persist
        self.store.add_scorecard(scorecard)
        await self.store.async_save()

        _LOGGER.info(
            "Daily scorecard: %s (%d/100) | Solar: %s | Min: %s | "
            "Floor breach: %s | Mid-peak charge: %s",
            grade,
            score,
            f"{solar_accuracy_pct:.0f}%" if solar_accuracy_pct else "N/A",
            f"{actual_min:.1f}" if actual_min is not None else "N/A",
            floor_breached,
            midpeak_charge,
        )

        # Conservative bias advisory
        rolling_margin = self.store.rolling_margin(days=14)
        if rolling_margin is not None and rolling_margin > 2.0:
            _LOGGER.warning(
                "Algorithm is conservative by %.1f kWh on average over 14 days. "
                "Consider reducing min_safe_soc or base_load.",
                rolling_margin,
            )

        # Trigger sensor update so grade/rolling sensors reflect new data
        if self.data is not None:
            self.async_set_updated_data(self.data)

        # Daily notification: the health message when the meters could grade the day,
        # else the old grade message (installs without the learned planner's sensors).
        self._send_daily_notifications(scorecard)

    # -----------------------------------------------------------------
    # Health (0.8.1): the day graded from what the meters saw
    # -----------------------------------------------------------------
    def _health_enabled(self) -> bool:
        runtime = getattr(self, "learned", None)
        return bool(runtime is not None and runtime.sensors_configured)

    def _grade_health(self, today: str, learned_summary: dict[str, Any] | None) -> dict[str, Any] | None:
        """The `health` record for today, or None when it cannot be graded."""
        if not self._health_enabled():
            return None
        try:
            if learned_summary is None:
                learned_summary = self.learned.daily_summary()
            # the day's own prices (its season's), from the tariff (0.9.1)
            return grade_day(learned_summary, today, self.tariff.prices_on(date.fromisoformat(today)))
        except Exception:  # noqa: BLE001 - grading must never break the daily scoring
            _LOGGER.exception("Could not grade the day's health")
            return None

    def health_records(self, exclude_date: str | None = None) -> list[dict[str, Any]]:
        """Stored `health` records, oldest first."""
        out: list[dict[str, Any]] = []
        for card in (self.store.days if self.store else []):
            record = card.get("health")
            if isinstance(record, dict) and record.get("grade") and card.get("date") != exclude_date:
                out.append(record)
        return out

    def health_summary(self) -> dict[str, Any]:
        """Good, watch or review over the last 7 graded days (state None before the first)."""
        return health_status(self.health_records())

    async def _async_score_health_only(self, today: str) -> None:
        """A day with no classic prediction snapshots can still be graded from the meters."""
        runtime = getattr(self, "learned", None)
        if not self._health_enabled():
            return
        try:
            summary = runtime.daily_summary()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Could not read the learned-planner summary")
            return
        day_health = self._grade_health(today, summary)
        self._mark_scored(today, day_health is not None)
        if day_health is None:
            return
        scorecard = {"date": today, "learned": summary, "health": day_health}
        self.store.add_scorecard(scorecard)
        await self.store.async_save()
        if self.data is not None:
            self.async_set_updated_data(self.data)
        self._send_daily_notifications(scorecard)

    def _mark_scored(self, today: str, graded: bool) -> None:
        """Tell the learned runtime the day has been scored, so what happens between now
        and midnight is carried into the next graded day instead of falling in none."""
        runtime = getattr(self, "learned", None)
        if runtime is None or not hasattr(runtime, "mark_scored"):
            return
        try:
            runtime.mark_scored(today, self._now(), graded)
        except Exception:  # noqa: BLE001 - bookkeeping must never break the daily scoring
            _LOGGER.exception("Could not mark the day as scored")

    def _send_daily_notifications(self, scorecard: dict) -> None:
        day_health = scorecard.get("health")
        if day_health is None:
            if not self._health_enabled() and "grade" in scorecard:
                self._send_daily_summary(scorecard)
            return
        summary = self.health_summary()
        _LOGGER.info(
            "Daily health: %s | grid kWh mid-peak %.2f, peak %.2f | health %s",
            day_health.get("grade"), day_health.get("grid_midpeak_kwh", 0.0),
            day_health.get("grid_peak_kwh", 0.0), summary.get("state"),
        )
        title, body = daily_message(day_health, summary, "weekday" if self.weekdays_only else "day")
        self._notify(title, body)
        before = health_status(self.health_records(exclude_date=day_health.get("date")))
        if summary.get("state") == HEALTH_REVIEW and before.get("state") != HEALTH_REVIEW:
            title, body = review_message(summary)
            self._notify(title, body, urgent=True)

    def _send_daily_summary(self, scorecard: dict) -> None:
        """Send a daily summary notification."""
        grade = scorecard.get("grade", "?")
        score = scorecard.get("score", 0)
        solar_pct = scorecard.get("solar_accuracy_pct")
        actual_min = scorecard.get("battery_min_actual")
        predicted_min = scorecard.get("battery_min_predicted", 0)
        total_charged = scorecard.get("total_charged_kwh", 0)
        correction = scorecard.get("solar_correction_factor", 1.0)

        lines = [f"Grade: {grade} ({score}/100)"]

        if solar_pct is not None:
            solar_actual = scorecard.get("solar_actual_kwh", 0)
            solar_predicted = scorecard.get("solar_predicted_kwh", 0)
            lines.append(
                f"Solar: {solar_actual:.1f} kWh actual vs "
                f"{solar_predicted:.1f} kWh predicted ({solar_pct:.0f}%)"
            )

        if actual_min is not None:
            lines.append(
                f"Battery min: {actual_min:.1f} kWh "
                f"(predicted {predicted_min:.1f}, "
                f"floor {self.min_safe_soc:.1f})"
            )

        if total_charged > 0:
            lines.append(f"Total charged: {total_charged:.1f} kWh")
        else:
            lines.append("No charging triggered today.")

        if abs(correction - 1.0) > 0.05:
            lines.append(f"Solar correction factor: {correction:.2f}")

        self._notify(
            f"Solarseed Daily Report - {grade} ({score}/100)",
            "\n".join(lines),
        )

    def _get_hourly_solar(self, entity_id: str | None = None, quiet: bool = False) -> dict[int, float]:
        """Parse hourly solar forecast into {hour: kWh}.

        Reads the configured forecast entity, or `entity_id` if given (for example
        tomorrow's forecast). An empty `entity_id` returns {}.

        Supports Solcast (detailedHourly / detailedForecast attributes) and
        Forecast.Solar (compatible forecast format).

        detailedHourly values are kWh per hour (use directly).
        detailedForecast values are kW at 30-min intervals (multiply by 0.5).
        """
        if entity_id is None:
            entity_id = self.solar_forecast_entity
        if not entity_id:
            return {}
        state = self.hass.states.get(entity_id)
        if state is None:
            (_LOGGER.debug if quiet else _LOGGER.warning)(
                "Solar forecast entity %s not found", entity_id
            )
            return {}

        # Prefer pre-aggregated hourly data (values are kWh)
        forecast_data = state.attributes.get("detailedHourly")
        period_hours = 1.0

        if not forecast_data:
            # Fall back to half-hourly data (values are kW, 30-min periods)
            forecast_data = state.attributes.get("detailedForecast")
            period_hours = 0.5

        if not forecast_data:
            # Generic forecast attributes (assume hourly kWh)
            forecast_data = (
                state.attributes.get("forecasts")
                or state.attributes.get("forecast")
                or []
            )
            period_hours = 1.0

        if not forecast_data:
            _LOGGER.debug(
                "No forecast attributes found on %s. Available attributes: %s",
                entity_id,
                list(state.attributes.keys()),
            )

        hourly: dict[int, float] = {}
        for entry in forecast_data:
            if not isinstance(entry, dict):
                continue
            period_start = entry.get("period_start", "")
            pv_estimate = self._safe_float(entry.get("pv_estimate", 0))
            energy_kwh = pv_estimate * period_hours

            if isinstance(period_start, datetime):
                hourly[period_start.hour] = hourly.get(period_start.hour, 0.0) + energy_kwh
            elif isinstance(period_start, str):
                try:
                    dt = datetime.fromisoformat(period_start)
                    hourly[dt.hour] = hourly.get(dt.hour, 0.0) + energy_kwh
                except (ValueError, AttributeError):
                    continue

        return hourly

    # -----------------------------------------------------------------
    # Core peak shaving calculation
    # -----------------------------------------------------------------
    def _skip_calculation(self, kind: str, reason: str) -> dict[str, float]:
        """No usable input: no classic calculation, no event, and setup does not fail.

        Returns the last calculation (or nothing yet), so the sensors keep their last
        values or show unknown. Logged once per kind of gap. A returning battery reading
        asks for a recalculation (`_on_battery_update`); a returning forecast does too
        (`_on_forecast_update`, within its window).
        """
        if self._skipped_for != kind:
            _LOGGER.warning("Classic calculation skipped: %s. Nothing is fired until it is back.", reason)
        self._skipped_for = kind
        return dict(self.data) if self.data else {}

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
        self._reset_daily_tracking()

        capacity = self.battery_capacity
        load_kw = self.effective_base_load
        min_safe = self.min_safe_soc
        midpeak_start = self.midpeak_start
        peak_start = self.peak_start
        peak_end = self.peak_end
        log = _LOGGER.warning if self.verbose_logging else _LOGGER.debug

        # --- Current battery level ---
        # A missing battery is not 0 kWh: 0.8.0 read it as an empty battery after a restart
        # and started a charge. With no usable reading the classic calculation is skipped
        # and nothing fires. Setup must not fail over it either: the learned planner is
        # the one in control and does not use this sensor.
        soc_state = self.hass.states.get(self.battery_soc_entity)
        current_soc = self._read_float(soc_state.state) if soc_state is not None else None
        if current_soc is None:
            return self._skip_calculation(
                "battery",
                f"battery SOC entity {self.battery_soc_entity} has no reading "
                f"(state {soc_state.state if soc_state is not None else None!r})",
            )

        # --- Solar forecast ---
        hourly_solar = self._get_hourly_solar()
        if not hourly_solar:
            return self._skip_calculation(
                "forecast", f"solar forecast entity {self.solar_forecast_entity} has no data"
            )
        self._skipped_for = None

        now = self._now()
        current_hour = now.hour

        # --- Project battery level at mid-peak start ---
        battery_at_peak: float = current_soc
        sim_start: int = midpeak_start
        pre_sim_note: str = ""

        if current_hour < midpeak_start:
            hours_to_rates = midpeak_start - current_hour
            drain = hours_to_rates * load_kw
            battery_at_peak = current_soc - drain
            pre_sim_note = (
                f"Pre-rate drain: {hours_to_rates}h x {load_kw:.1f} kW = "
                f"{drain:.2f} kWh, battery at mid-peak: {battery_at_peak:.2f}"
            )
        elif current_hour >= peak_end:
            hours_to_midnight = 24 - current_hour
            hours_after_midnight = midpeak_start
            hours_to_rates = hours_to_midnight + hours_after_midnight
            drain = hours_to_rates * load_kw
            battery_at_peak = current_soc - drain
            pre_sim_note = (
                f"Overnight drain: {hours_to_rates}h x {load_kw:.1f} kW = "
                f"{drain:.2f} kWh, battery at mid-peak: {battery_at_peak:.2f}"
            )
        else:
            battery_at_peak = current_soc
            sim_start = current_hour
            pre_sim_note = f"In rate window, simulating from hour {current_hour}"

        # --- Simulate through mid-peak + peak period ---
        battery_level = battery_at_peak
        min_battery = battery_level
        csv_lines = ["hour,period,solar_kwh,load_kwh,net_kwh,battery_kwh"]
        table_lines: list[str] = []

        for hour in range(sim_start, peak_end):
            raw_solar = hourly_solar.get(hour, 0.0)
            solar_kwh = raw_solar * self._get_solar_correction(hour)
            net = solar_kwh - load_kw
            battery_level += net
            min_battery = min(min_battery, battery_level)

            period = "MID" if hour < peak_start else "PEAK"

            csv_lines.append(
                f"{hour:02d}:00,{period},{solar_kwh:.3f},{load_kw:.3f},"
                f"{net:+.3f},{battery_level:.2f}"
            )
            table_lines.append(
                f"{hour:02d}:00 [{period:4s}] | "
                f"Solar: {solar_kwh:.3f} | Load: {load_kw:.3f} | "
                f"Net: {net:+.3f} | Battery: {battery_level:.2f}"
            )

        # Store for sensor attributes
        self.last_simulation_csv = "\n".join(csv_lines)

        # --- Calculate target ---
        if min_battery < min_safe:
            deficit = min_safe - min_battery
            target_soc = current_soc + deficit
            verdict = (
                f"CHARGE NEEDED:\n"
                f"Projected min: {min_battery:.2f} kWh < floor {min_safe:.2f} kWh\n"
                f"Deficit: {deficit:.2f} kWh"
            )
        else:
            target_soc = current_soc
            verdict = (
                f"NO CHARGE NEEDED:\n"
                f"Projected min: {min_battery:.2f} kWh >= floor {min_safe:.2f} kWh"
            )

        target_soc = min(target_soc, capacity)
        charge_needed = max(target_soc - current_soc, 0.0)

        # Break-even SOC: below this current level, charging would trigger
        headroom = min_battery - min_safe
        charge_below = max(current_soc - headroom, 0.0)

        # --- Diagnostics: full formatted summary ---
        self.last_simulation_summary = (
            f"Peak Shaver Calculation @ {now.strftime('%H:%M')}\n"
            f"\n"
            f"Battery:     {current_soc:>6.2f} kWh\n"
            f"Capacity:    {capacity:>6.2f} kWh\n"
            f"Min safe:    {min_safe:>6.2f} kWh\n"
            f"Base load:   {load_kw:>5.1f} kW\n"
            f"\n"
            f"{pre_sim_note}\n"
            f"\n"
            + "\n".join(table_lines) + "\n"
            f"\n"
            f"{verdict}\n"
            f"\n"
            f"Target:        {target_soc:>6.2f} kWh\n"
            f"Charge needed: {charge_needed:>6.2f} kWh\n"
            f"Charge below:  {charge_below:>6.2f} kWh"
        )

        # --- Log: compact summary for HA log dialog ---
        total_solar = sum(hourly_solar.get(h, 0.0) for h in range(sim_start, peak_end))
        total_load = load_kw * (peak_end - sim_start)
        charge_verdict = (
            f"CHARGE {charge_needed:.1f} kWh"
            if charge_needed > self.charge_threshold
            else "NO CHARGE"
        )
        log(
            f"[{charge_verdict}] "
            f"Battery: {current_soc:.1f} kWh | "
            f"Projected min: {min_battery:.1f} kWh | "
            f"Target: {target_soc:.1f} kWh | "
            f"Solar: {total_solar:.1f} kWh | "
            f"Load: {total_load:.1f} kWh | "
            f"Charge below: {charge_below:.1f} kWh"
        )

        result = {
            SENSOR_TARGET_SOC: round(target_soc, 2),
            SENSOR_CHARGE_NEEDED: round(charge_needed, 2),
            SENSOR_PROJECTED_MIN: round(min_battery, 2),
            SENSOR_BATTERY_AT_PEAK: round(battery_at_peak, 2),
            SENSOR_CHARGE_BELOW: round(charge_below, 2),
        }

        wants_charge = charge_needed > self.charge_threshold

        # Not a TOU day (weekend or holiday): the listeners already skip it, but the refresh at setup,
        # the Recalculate button and the service do not. They still update the sensors;
        # nothing is fired, scored or recorded (0.8.0 ran a full calculation on a Sunday).
        if not self.is_tou_day(now.date()):
            _LOGGER.debug("Not a TOU day (weekend or holiday): sensors updated, no events")
            if self.planner != PLANNER_LEARNED:
                self._events_armed = True  # a weekend start must not restrict Monday's 03:00
            return result

        # First calculation after a (re)start that wants a charge: do not act on it. A
        # sensor can read wrongly for a moment while HA loads, and the reading would also
        # become the day's primary prediction. Look again shortly; only that second
        # calculation may start the charge.
        first_calc = self.planner != PLANNER_LEARNED and not self._events_armed
        recheck = self._recheck_restricted
        self._recheck_restricted = False
        if first_calc and wants_charge:
            self._events_armed = True
            self._schedule_startup_recheck()
            _LOGGER.info(
                "First calculation since start wants a %.1f kWh charge (battery %.1f kWh): "
                "checking again in %d s before starting it",
                charge_needed, current_soc, STARTUP_CONFIRM_SECONDS,
            )
            return result

        # Record prediction snapshot for performance tracking
        charging_triggered = wants_charge
        self._record_prediction_snapshot(
            run_type="scheduled",
            current_soc=current_soc,
            battery_at_peak=battery_at_peak,
            min_battery=min_battery,
            target_soc=target_soc,
            charge_needed=charge_needed,
            charge_below=charge_below,
            hourly_solar=hourly_solar,
            charging_triggered=charging_triggered,
        )

        _LOGGER.info(
            "Peak shaver: target=%.2f kWh, charge_needed=%.2f kWh, "
            "projected_min=%.2f kWh",
            target_soc,
            charge_needed,
            min_battery,
        )

        # --- Fire events and notify ---
        if self.planner == PLANNER_LEARNED:
            # The learned planner drives the inverter. Keep computing the classic
            # numbers for comparison, but fire nothing.
            self._charging_active = False
            return result

        # First calculation after a (re)start, the second look that follows it, or battery
        # readings frozen: a charge may start, but a hold is never released and a charge
        # never stopped. Releasing from an unverified state cost a night's hold in 0.7.0;
        # firing nothing (0.7.1) skipped a needed top-up after a mid-peak restart.
        self._events_armed = True
        if (first_calc or recheck or self.battery_data_stale) and not wants_charge:
            _LOGGER.info(
                "%s: no charge needed, leaving the inverter mode as it is",
                "First calculation since start" if first_calc
                else "Second look after start" if recheck
                else "Battery data frozen",
            )
            return result

        solar_forecast_state = self.hass.states.get(self.solar_forecast_entity)
        solar_forecast_val = (
            self._safe_float(solar_forecast_state.state)
            if solar_forecast_state
            else 0.0
        )

        if wants_charge:
            self._charging_active = True
            self._charge_start_time = now
            self._charge_start_soc = current_soc

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
