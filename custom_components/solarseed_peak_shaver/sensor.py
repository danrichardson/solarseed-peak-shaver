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
    SENSOR_CHARGE_NEEDED,
    SENSOR_PROJECTED_MIN,
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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="Johnny Solarseed",
            model="Peak Shaver",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._sensor_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return simulation CSV on the Target SOC sensor."""
        if self._sensor_key != SENSOR_TARGET_SOC:
            return None
        csv = self.coordinator.last_simulation_csv
        if not csv:
            return None
        return {"last_simulation_csv": csv}
