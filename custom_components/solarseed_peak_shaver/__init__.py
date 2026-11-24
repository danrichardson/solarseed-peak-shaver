"""Solarseed Peak Shaver - smart overnight charging for solar + battery systems."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse

from .const import (
    DOMAIN,
    SERVICE_BACKFILL_LEARNING,
    SERVICE_EXPORT_HISTORY,
    SERVICE_PERFORMANCE_REPORT,
    SERVICE_RECALCULATE,
)
from .coordinator import PeakShaverCoordinator
from .learned_runtime import LearnedRuntime
from .setup_check import SetupCheck, remove_issues
from .store import PeakShaverStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON, Platform.SELECT, Platform.NUMBER]


async def async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Stored options changed (an options section was saved, or a settings entity set).

    Most settings are read live, so nothing needs restarting: the entities are refreshed
    and the learned planner uses the new value on its next minute. Only a change to a
    setting read once at start (sensors with listeners, hours with timers, the packs)
    reloads the entry, which is a restart of the integration with the usual restart rules.
    The six settings entities never reload it.
    """
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        return
    try:
        now = coordinator.setup_signature()
        changed = sorted(k for k, v in now.items() if coordinator.started_with.get(k) != v)
    except Exception:  # noqa: BLE001 - an odd stored value is not a reason to restart
        _LOGGER.exception("Could not compare the settings read at start")
        changed = []
    if changed:
        _LOGGER.info("Settings read at start changed (%s); reloading", ", ".join(changed))
        await hass.config_entries.async_reload(entry.entry_id)
        return
    if hasattr(coordinator, "async_update_listeners"):
        coordinator.async_update_listeners()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Solarseed Peak Shaver from a config entry."""
    store = PeakShaverStore(hass)
    await store.async_load()

    coordinator = PeakShaverCoordinator(hass, entry, store)
    coordinator.started_with = coordinator.setup_signature()

    await coordinator.async_config_entry_first_refresh()

    # Learned model and planner. It only observes unless the planner option is set to
    # "learned", and a failure here must never stop the classic planner. The object is
    # created now so the sensors can read it; its timer starts after the platforms load.
    try:
        coordinator.learned = LearnedRuntime(hass, coordinator)
        coordinator.learned.load_state(store.learning)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Learned planner could not start; continuing with the classic planner only")
        coordinator.learned = None

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Set up scheduled recalculations and state listeners
    coordinator.setup_listeners()
    if coordinator.learned is not None:
        try:
            coordinator.learned.setup()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Learned planner timer could not start; continuing with the classic planner only")
            coordinator.learned = None

    # Options saved from the menu or the settings entities (0.9.0). There was no listener
    # before: a change to a setting read at start waited for the next restart.
    entry.async_on_unload(entry.add_update_listener(async_options_updated))

    # Missing sensors, a forecast without hourly detail, events nobody acts on: a repair
    # issue and one log line each, checked every ten minutes once HA runs (0.9.3).
    try:
        coordinator.setup_check = SetupCheck(hass, coordinator, entry.entry_id)
        coordinator.setup_check.start()
    except Exception:  # noqa: BLE001 - a check must never stop the planners
        _LOGGER.exception("Setup check could not start")
        coordinator.setup_check = None

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

    # Register the learned-model backfill service
    if not hass.services.has_service(DOMAIN, SERVICE_BACKFILL_LEARNING):

        async def handle_backfill(call: ServiceCall) -> dict:
            """Rebuild the learned model from recorder statistics."""
            days = int(call.data.get("days", 10))
            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, PeakShaverCoordinator) and coord.learned is not None:
                    try:
                        return await coord.learned.async_backfill(days=days)
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.exception("Backfill failed")
                        return {"error": str(err)}
            return {"error": "Learned planner is not running"}

        hass.services.async_register(
            DOMAIN,
            SERVICE_BACKFILL_LEARNING,
            handle_backfill,
            supports_response=SupportsResponse.ONLY,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: PeakShaverCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.remove_listeners()
    check = getattr(coordinator, "setup_check", None)
    if check is not None:
        check.stop()
    if coordinator.learned is not None:
        try:
            coordinator.learned.remove()
            await coordinator.learned.async_save()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Could not save the learned model on unload")

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    # Remove services if no more entries
    if not hass.data.get(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_RECALCULATE)
        hass.services.async_remove(DOMAIN, SERVICE_PERFORMANCE_REPORT)
        hass.services.async_remove(DOMAIN, SERVICE_EXPORT_HISTORY)
        hass.services.async_remove(DOMAIN, SERVICE_BACKFILL_LEARNING)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """The entry is deleted: its repair issues go with it."""
    try:
        remove_issues(hass, entry.entry_id)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Could not remove the setup issues")
