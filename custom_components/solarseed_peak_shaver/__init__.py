"""Solarseed Peak Shaver - smart overnight charging for solar + battery systems."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN, SERVICE_RECALCULATE
from .coordinator import PeakShaverCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Solarseed Peak Shaver from a config entry."""
    coordinator = PeakShaverCoordinator(hass, entry)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Set up scheduled recalculations and state listeners
    coordinator.setup_listeners()

    # Register recalculate service (once, for any number of config entries)
    if not hass.services.has_service(DOMAIN, SERVICE_RECALCULATE):

        async def handle_recalculate(call: ServiceCall) -> None:
            """Handle the recalculate service call."""
            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, PeakShaverCoordinator):
                    await coord.async_request_refresh()

        hass.services.async_register(DOMAIN, SERVICE_RECALCULATE, handle_recalculate)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: PeakShaverCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.remove_listeners()

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    # Remove service if no more entries
    if not hass.data.get(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_RECALCULATE)

    return unload_ok
