"""Select entities: settings on the device page (0.9.0).

Each one changes one stored option (the config entry's options are the only store) and
takes effect without a restart: the coordinator reads options live, and the learned
planner uses the new value on its next minute. Switching the planner follows the rules
for a handover that already apply when the option is changed any other way.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_HOLIDAY_PRESET,
    CONF_PLANNER,
    DOMAIN,
    NAME,
    PLANNER_CLASSIC,
    PLANNER_LEARNED,
    VERSION,
)
from .coordinator import PeakShaverCoordinator
from .holidays import HOLIDAY_PRESETS
from .options import write_option

_LOGGER = logging.getLogger(__name__)

# key, name, icon, choices, how the coordinator reads it
SELECTS: tuple[tuple[str, str, str, tuple[str, ...], Callable[[Any], str]], ...] = (
    (CONF_PLANNER, "Planner", "mdi:swap-horizontal-bold",
     (PLANNER_CLASSIC, PLANNER_LEARNED), lambda c: c.planner),
    (CONF_HOLIDAY_PRESET, "Utility holidays", "mdi:calendar-star",
     tuple(HOLIDAY_PRESETS), lambda c: c.holiday_preset),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the settings selects."""
    coordinator: PeakShaverCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([OptionSelect(coordinator, entry, *spec) for spec in SELECTS])


class OptionSelect(CoordinatorEntity[PeakShaverCoordinator], SelectEntity):
    """A select that is one stored option."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: PeakShaverCoordinator, entry: ConfigEntry, key: str, name: str,
                 icon: str, choices: tuple[str, ...], read: Callable[[Any], str]) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._key = key
        self._read = read
        self._attr_name = name
        self._attr_icon = icon
        self._attr_translation_key = key
        self._attr_options = list(choices)
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
    def current_option(self) -> str | None:
        return self._read(self.coordinator)

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            raise ValueError("%s is not one of %s" % (option, ", ".join(self._attr_options)))
        if write_option(self.coordinator.hass, self._entry, self._key, option):
            _LOGGER.info("Option %s set to %s from the device page", self._key, option)
        self.async_write_ha_state()
