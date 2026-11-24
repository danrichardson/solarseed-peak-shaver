"""Sensor platform for Solarseed Peak Shaver."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .holidays import holiday_attributes
from .const import (
    DOMAIN,
    NAME,
    SENSOR_BATTERY_AT_PEAK,
    SENSOR_CHARGE_BELOW,
    SENSOR_CHARGE_NEEDED,
    SENSOR_DAILY_GRADE,
    SENSOR_EFFECTIVE_BASE_LOAD,
    SENSOR_HEALTH,
    SENSOR_LEARNED_ENERGY,
    SENSOR_LEARNED_PLAN,
    SENSOR_PREDICTION_ACCURACY,
    SENSOR_PROJECTED_MIN,
    SENSOR_ROLLING_SCORE,
    SENSOR_SOLAR_ACCURACY,
    SENSOR_TARGET_SOC,
    VERSION,
)
from .coordinator import PeakShaverCoordinator
from .learned_runtime import PACK_SOC_SUFFIXES

SENSOR_DESCRIPTIONS: dict[str, dict] = {
    SENSOR_TARGET_SOC: {
        "name": "Target SOC",
        "icon": "mdi:battery-charging-high",
    },
    SENSOR_CHARGE_NEEDED: {
        "name": "Charge Needed",
        "icon": "mdi:battery-plus-variant",
    },
    SENSOR_PROJECTED_MIN: {
        "name": "Projected Minimum Battery",
        "icon": "mdi:battery-alert-variant-outline",
    },
    SENSOR_BATTERY_AT_PEAK: {
        "name": "Battery at Peak Start",
        "icon": "mdi:battery-clock-outline",
    },
    SENSOR_CHARGE_BELOW: {
        "name": "Charge Below",
        "icon": "mdi:battery-arrow-down",
    },
    # --- Performance tracking sensors ---
    SENSOR_DAILY_GRADE: {
        "name": "Daily Grade",
        "icon": "mdi:school-outline",
        "device_class": None,
        "state_class": None,
        "unit": None,
    },
    SENSOR_SOLAR_ACCURACY: {
        "name": "Solar Forecast Accuracy",
        "icon": "mdi:weather-sunny-alert",
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
        "unit": "%",
    },
    SENSOR_EFFECTIVE_BASE_LOAD: {
        "name": "Effective Base Load",
        "icon": "mdi:flash",
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
        "unit": "kW",
    },
    SENSOR_PREDICTION_ACCURACY: {
        "name": "Prediction Accuracy",
        "icon": "mdi:target",
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
    },
    SENSOR_ROLLING_SCORE: {
        "name": "Algorithm Score",
        "icon": "mdi:chart-line",
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
        "unit": None,
    },
    # --- Health (0.8.1): how the last 7 weekdays went, from the meters ---
    SENSOR_HEALTH: {
        "name": "Health",
        "icon": "mdi:heart-pulse",
        "device_class": None,
        "state_class": None,
        "unit": None,
    },
    # --- Learned planner sensors ---
    SENSOR_LEARNED_ENERGY: {
        "name": "Learned Energy Remaining",
        "icon": "mdi:battery-heart-variant",
    },
    SENSOR_LEARNED_PLAN: {
        "name": "Learned Plan",
        "icon": "mdi:head-cog-outline",
        "device_class": None,
        "state_class": None,
        "unit": None,
    },
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from a config entry."""
    coordinator: PeakShaverCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list = [
        PeakShaverSensor(coordinator, entry, sensor_key, desc)
        for sensor_key, desc in SENSOR_DESCRIPTIONS.items()
    ]
    # Optional third-party pack sensors (ROADMAP items 1 and 2), one pair per pack.
    # A pack added or removed in the options reloads the entry, which recreates these.
    for current_id in coordinator.pack_current_entities:
        entities.append(PackSensor(coordinator, entry, current_id, PACK_SOC))
        entities.append(PackSensor(coordinator, entry, current_id, PACK_CAPACITY))
    async_add_entities(entities)


class PeakShaverSensor(CoordinatorEntity[PeakShaverCoordinator], SensorEntity):
    """A sensor reporting a value from the peak shaving calculation."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENERGY_STORAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(
        self,
        coordinator: PeakShaverCoordinator,
        entry: ConfigEntry,
        sensor_key: str,
        description: dict,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor_key = sensor_key
        self._attr_name = description["name"]
        self._attr_icon = description.get("icon")
        self._attr_unique_id = f"{entry.entry_id}_{sensor_key}"

        # Override defaults for non-kWh sensors
        if "device_class" in description:
            self._attr_device_class = description["device_class"]
        if "unit" in description:
            self._attr_native_unit_of_measurement = description["unit"]
        if "state_class" in description:
            self._attr_state_class = description["state_class"]

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="Johnny Solarseed",
            model="Peak Shaver",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> float | str | None:
        """Return the current value."""
        coord = self.coordinator

        # Performance tracking sensors read from coordinator properties
        if self._sensor_key == SENSOR_DAILY_GRADE:
            sc = coord.last_daily_scorecard
            return sc.get("grade") if sc else None

        if self._sensor_key == SENSOR_SOLAR_ACCURACY:
            if coord.store and coord.store.days:
                return round(coord.store.rolling_solar_accuracy(days=7) * 100, 1)
            return None

        if self._sensor_key == SENSOR_EFFECTIVE_BASE_LOAD:
            if coord.store and len(coord.store.days) >= 3:
                val = coord.store.rolling_base_load(days=7)
                return round(val, 2) if val else None
            return None

        if self._sensor_key == SENSOR_PREDICTION_ACCURACY:
            if coord.store and coord.store.days:
                val = coord.store.rolling_prediction_error(days=7)
                return round(val, 2) if val else None
            return None

        if self._sensor_key == SENSOR_ROLLING_SCORE:
            if coord.store and coord.store.days:
                return coord.store.rolling_score(days=7)
            return None

        if self._sensor_key == SENSOR_HEALTH:
            return coord.health_summary()["state"]

        if self._sensor_key in (SENSOR_LEARNED_ENERGY, SENSOR_LEARNED_PLAN):
            decision = getattr(getattr(coord, "learned", None), "decision", None)
            if decision is None:
                return None
            if self._sensor_key == SENSOR_LEARNED_PLAN:
                return decision.mode
            val = decision.energy_remaining_kwh
            return round(val, 2) if val is not None else None

        # Standard sensors from coordinator data dict
        if coord.data is None:
            return None
        return coord.data.get(self._sensor_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes for dashboard and diagnostics."""
        coord = self.coordinator

        if self._sensor_key == SENSOR_TARGET_SOC:
            csv = coord.last_simulation_csv
            if not csv:
                return None
            return {"last_simulation_csv": csv}

        if self._sensor_key == SENSOR_DAILY_GRADE:
            sc = coord.last_daily_scorecard
            if not sc:
                return None
            return {
                "score": sc.get("score"),
                "date": sc.get("date"),
                "solar_accuracy_pct": sc.get("solar_accuracy_pct"),
                "floor_breached": sc.get("floor_breached"),
                "midpeak_charge_triggered": sc.get("midpeak_charge_triggered"),
                "unnecessary_charge_kwh": sc.get("unnecessary_charge_kwh"),
                "recent_grades": (
                    coord.store.recent_grades(7) if coord.store else []
                ),
            }

        if self._sensor_key == SENSOR_SOLAR_ACCURACY:
            if not coord.store:
                return None
            return {
                "correction_factor": round(coord.solar_correction_factor, 3),
                "7_day_accuracy": round(
                    coord.store.rolling_solar_accuracy(7) * 100, 1
                ),
                "14_day_accuracy": round(
                    coord.store.rolling_solar_accuracy(14) * 100, 1
                ),
                "30_day_accuracy": round(
                    coord.store.rolling_solar_accuracy(30) * 100, 1
                ),
            }

        if self._sensor_key == SENSOR_EFFECTIVE_BASE_LOAD:
            if not coord.store:
                return None
            return {
                "configured_base_load": coord.base_load_kw,
                "7_day_average": coord.store.rolling_base_load(7),
                "14_day_average": coord.store.rolling_base_load(14),
            }

        if self._sensor_key == SENSOR_PREDICTION_ACCURACY:
            if not coord.store:
                return None
            margin = coord.store.rolling_margin(14)
            return {
                "7_day_error": coord.store.rolling_prediction_error(7),
                "14_day_margin": (
                    round(margin, 2) if margin is not None else None
                ),
                "bias": (
                    "conservative"
                    if margin and margin > 0.5
                    else "optimistic"
                    if margin and margin < -0.5
                    else "balanced"
                ),
            }

        if self._sensor_key == SENSOR_ROLLING_SCORE:
            if not coord.store:
                return None
            return {
                "recent_grades": coord.store.recent_grades(7),
                "7_day_score": coord.store.rolling_score(7),
                "30_day_score": coord.store.rolling_score(30),
            }

        if self._sensor_key == SENSOR_HEALTH:
            summary = coord.health_summary()
            return {
                "days_graded": summary["days"],
                "counts": summary["counts"],
                "peak_end_bias_points": summary["bias_pts"],
                "review_reasons": summary["review_reasons"],
                "last_7_days": coord.health_records()[-7:],
            }

        runtime = getattr(coord, "learned", None)
        if runtime is not None and self._sensor_key == SENSOR_LEARNED_PLAN:
            decision = runtime.decision
            if decision is None:
                return None
            attrs = decision.as_dict()
            attrs.pop("mode", None)
            attrs.pop("energy_remaining_kwh", None)
            attrs["planner_in_control"] = coord.planner
            attrs["bank_full"] = runtime.bank_full
            attrs["weekly_topup_pending"] = runtime.topup_pending
            attrs["power_sensors_configured"] = runtime.sensors_configured
            attrs["battery_data_stale"] = runtime.data_stale
            attrs.update(holiday_attributes(datetime.now().date(), coord.holiday_preset))
            return attrs

        if runtime is not None and self._sensor_key == SENSOR_LEARNED_ENERGY:
            ln, floor = runtime.learner, coord.gauge_floor
            return {
                "floor_to_full_kwh": round(ln.discharge.energy_between(floor, 100.0), 1),
                "kwh_per_percent_by_band": {
                    "%d-%d" % (lo, lo + 20): round(ln.discharge.energy_between(lo, lo + 20) / 20.0, 2)
                    for lo in range(0, 100, 20)
                },
                "discharge_points_learned": round(sum(ln.discharge.p)),
                "charge_points_learned": round(sum(ln.grid_charge.p)),
                "tou_days_of_load_history": runtime.profile.n_days(True),
                "expected_load_rate_window_kwh": round(
                    runtime.profile.window_mean(True, coord.midpeak_start, coord.peak_end), 1
                ),
            }

        return None


PACK_SOC = "charge_estimate"
PACK_CAPACITY = "capacity_ah"


def pack_label(hass: HomeAssistant, current_id: str) -> str:
    """A pack's name from its current sensor: its friendly name without "Current"."""
    st = hass.states.get(current_id) if hass is not None else None
    name = str((getattr(st, "attributes", None) or {}).get("friendly_name", "") or "").strip()
    if name.lower().endswith(" current"):
        name = name[: -len(" current")].strip()
    if not name:
        obj = current_id.split(".", 1)[-1]
        if obj.endswith("_current"):
            obj = obj[: -len("_current")]
        name = obj.replace("_", " ").strip().title()
    return name


class PackSensor(CoordinatorEntity[PeakShaverCoordinator], SensorEntity):
    """Charge estimate or capacity trend for one third-party pack."""

    _attr_has_entity_name = True
    _attr_device_class = None

    def __init__(self, coordinator: PeakShaverCoordinator, entry: ConfigEntry, current_id: str,
                 kind: str) -> None:
        super().__init__(coordinator)
        self._current_id = current_id
        self._kind = kind
        label = pack_label(coordinator.hass, current_id)
        obj = current_id.split(".", 1)[-1]
        self._attr_unique_id = f"{entry.entry_id}_pack_{obj}_{kind}"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        if kind == PACK_SOC:
            self._attr_name = f"{label} Charge Estimate"
            self._attr_icon = "mdi:battery-sync-outline"
            self._attr_native_unit_of_measurement = "%"
        else:
            self._attr_name = "%s Ah Between %.1f And %.1f V" % (
                label, coordinator.capacity_v_high, coordinator.capacity_v_low)
            self._attr_icon = "mdi:battery-heart-outline"
            self._attr_native_unit_of_measurement = "Ah"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="Johnny Solarseed",
            model="Peak Shaver",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    def _tracker(self):
        runtime = getattr(self.coordinator, "learned", None)
        if runtime is None:
            return None, None
        try:
            return runtime, runtime.pack_tracker()
        except Exception:  # noqa: BLE001
            return runtime, None

    @property
    def native_value(self) -> float | None:
        _, tracker = self._tracker()
        if tracker is None:
            return None
        if self._kind == PACK_SOC:
            val = tracker.estimate_pct(self._current_id)
            return round(val, 1) if val is not None else None
        val = tracker.latest_ah(self._current_id)
        return round(val, 1) if val is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        runtime, tracker = self._tracker()
        if tracker is None:
            return None
        p = self._current_id
        if self._kind == PACK_SOC:
            bms_id = runtime.sibling(p, PACK_SOC_SUFFIXES)
            bms = runtime._float_state(bms_id) if bms_id else None
            return {
                "ah_out_since_full": (round(tracker.out_ah[p], 2) if p in tracker.out_ah else None),
                "capacity_ah": tracker.capacity_ah,
                "full_anchor_at": tracker.anchor_at,
                "gap_minutes_since_full": round(tracker.gap_min.get(p, 0.0), 1),
                "bms_percent": bms,
                "bms_entity": bms_id,
                "current_entity": p,
            }
        hist = tracker.history(p)
        last = next((pt for pt in reversed(tracker.points)
                     if p in pt.get("ah", {}) and pt.get("v_high") == tracker.v_high
                     and pt.get("v_low") == tracker.v_low), None)
        attrs: dict[str, Any] = {
            "v_high": tracker.v_high,
            "v_low": tracker.v_low,
            "history": hist,
            "run": tracker.run_status(),
            "current_entity": p,
        }
        if last is not None:
            attrs.update({
                "last_run_start": last.get("start"),
                "last_run_end": last.get("end"),
                "last_run_hours": last.get("hours"),
                "last_run_ac_kwh": last.get("ac_kwh"),
                "last_run_mean_kw": last.get("mean_kw"),
            })
        return attrs
