"""Number entities: the learned planner's tuning settings on the device page (0.9.0).

Each one changes one stored option and takes effect on the learned planner's next minute,
without a restart or a reload. The ranges are the options form's.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_GAUGE_FLOOR,
    CONF_LOAD_QUANTILE,
    CONF_PEAK_MARGIN_KWH,
    CONF_SOLAR_CONFIDENCE,
    DOMAIN,
    NAME,
    VERSION,
)
from .coordinator import PeakShaverCoordinator
from .options import write_option

_LOGGER = logging.getLogger(__name__)

# key, name, icon, min, max, step, unit, how the coordinator reads it
NUMBERS: tuple[tuple[str, str, str, float, float, float, str | None, Callable[[Any], float]], ...] = (
    (CONF_PEAK_MARGIN_KWH, "Peak margin", "mdi:battery-arrow-up-outline",
     0.0, 10.0, 0.1, "kWh", lambda c: c.peak_margin_kwh),
    (CONF_LOAD_QUANTILE, "Load quantile", "mdi:chart-bell-curve-cumulative",
     0.5, 0.99, 0.01, None, lambda c: c.load_quantile),
    (CONF_SOLAR_CONFIDENCE, "Solar confidence", "mdi:weather-partly-cloudy",
     0.0, 1.5, 0.05, None, lambda c: c.solar_confidence),
    (CONF_GAUGE_FLOOR, "Gauge floor", "mdi:battery-10",
     0.0, 50.0, 1.0, "%", lambda c: c.gauge_floor),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the tuning numbers."""
    coordinator: PeakShaverCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([OptionNumber(coordinator, entry, *spec) for spec in NUMBERS])


class OptionNumber(CoordinatorEntity[PeakShaverCoordinator], NumberEntity):
    """A number that is one stored option."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: PeakShaverCoordinator, entry: ConfigEntry, key: str, name: str,
                 icon: str, lo: float, hi: float, step: float, unit: str | None,
                 read: Callable[[Any], float]) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._key = key
        self._read = read
        self._attr_name = name
        self._attr_icon = icon
        self._attr_translation_key = key
        self._attr_native_min_value = lo
        self._attr_native_max_value = hi
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_unique_id = f"{entry.entry_id}_option_{key}"
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
        return self._read(self.coordinator)

    async def async_set_native_value(self, value: float) -> None:
        lo, hi = self._attr_native_min_value, self._attr_native_max_value
        if value is None or not lo <= float(value) <= hi:
            raise ValueError("%s must be between %s and %s" % (self._attr_name, lo, hi))
        stored = round(float(value), 3)
        if write_option(self.coordinator.hass, self._entry, self._key, stored):
            _LOGGER.info("Option %s set to %s from the device page", self._key, stored)
        self.async_write_ha_state()
