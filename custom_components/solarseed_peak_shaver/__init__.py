"""Solarseed Peak Shaver - smart overnight charging for solar + battery systems."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse

from .const import DOMAIN, SERVICE_EXPORT_HISTORY, SERVICE_PERFORMANCE_REPORT, SERVICE_RECALCULATE
from .coordinator import PeakShaverCoordinator
from .store import PeakShaverStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Solarseed Peak Shaver from a config entry."""
    store = PeakShaverStore(hass)
    await store.async_load()

    coordinator = PeakShaverCoordinator(hass, entry, store)

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

    # Register performance report service
    if not hass.services.has_service(DOMAIN, SERVICE_PERFORMANCE_REPORT):

        async def handle_performance_report(call: ServiceCall) -> dict:
            """Return performance data for recent days."""
            days = int(call.data.get("days", 7))
            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, PeakShaverCoordinator):
                    recent = coord.store.days[-days:]
                    return {
                        "days": recent,
                        "rolling_solar_accuracy": round(
                            coord.store.rolling_solar_accuracy(14) * 100, 1
                        ),
                        "rolling_base_load": coord.store.rolling_base_load(14),
                        "rolling_score": coord.store.rolling_score(7),
                        "solar_correction_factor": round(
                            coord.solar_correction_factor, 3
                        ),
                    }
            return {"error": "No coordinator found"}

        hass.services.async_register(
            DOMAIN,
            SERVICE_PERFORMANCE_REPORT,
            handle_performance_report,
            supports_response=SupportsResponse.ONLY,
        )

    # Register export history service
    if not hass.services.has_service(DOMAIN, SERVICE_EXPORT_HISTORY):

        async def handle_export_history(call: ServiceCall) -> dict:
            """Export performance history as CSV."""
            days = call.data.get("days")
            if days is not None:
                days = int(days)
            export_format = call.data.get("format", "daily")

            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, PeakShaverCoordinator):
                    if export_format == "hourly_solar":
                        csv_data = coord.store.export_hourly_solar_csv(days)
                    else:
                        csv_data = coord.store.export_csv(days)

                    return {
                        "csv": csv_data,
                        "format": export_format,
                        "records": csv_data.count("\n") if csv_data else 0,
                    }
            return {"error": "No coordinator found"}

        hass.services.async_register(
            DOMAIN,
            SERVICE_EXPORT_HISTORY,
            handle_export_history,
            supports_response=SupportsResponse.ONLY,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: PeakShaverCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.remove_listeners()

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    # Remove services if no more entries
    if not hass.data.get(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_RECALCULATE)
        hass.services.async_remove(DOMAIN, SERVICE_PERFORMANCE_REPORT)
        hass.services.async_remove(DOMAIN, SERVICE_EXPORT_HISTORY)

    return unload_ok
