"""Sensor platform for Solarseed Peak Shaver."""
from __future__ import annotations

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

from .const import (
    DOMAIN,
    NAME,
    SENSOR_BATTERY_AT_PEAK,
    SENSOR_CHARGE_BELOW,
    SENSOR_CHARGE_NEEDED,
    SENSOR_DAILY_GRADE,
    SENSOR_EFFECTIVE_BASE_LOAD,
    SENSOR_PREDICTION_ACCURACY,
    SENSOR_PROJECTED_MIN,
    SENSOR_ROLLING_SCORE,
    SENSOR_SOLAR_ACCURACY,
    SENSOR_TARGET_SOC,
    VERSION,
)
from .coordinator import PeakShaverCoordinator

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
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from a config entry."""
    coordinator: PeakShaverCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        PeakShaverSensor(coordinator, entry, sensor_key, desc)
        for sensor_key, desc in SENSOR_DESCRIPTIONS.items()
    ]
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

        return None
