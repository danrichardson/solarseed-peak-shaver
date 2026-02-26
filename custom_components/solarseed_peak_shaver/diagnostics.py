"""Diagnostics support for Solarseed Peak Shaver."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

TO_REDACT = {"notify_entity"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data[DOMAIN].get(entry.entry_id)

    result: dict[str, Any] = {
        "config_entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "last_calculation": coordinator.data if coordinator else None,
    }

    if coordinator:
        battery_entity = entry.data.get("battery_soc_entity", "")
        solar_entity = entry.data.get("solar_forecast_entity", "")

        battery_state = hass.states.get(battery_entity)
        solar_state = hass.states.get(solar_entity)

        result["entity_states"] = {
            "battery_soc": {
                "entity_id": battery_entity,
                "state": battery_state.state if battery_state else None,
            },
            "solar_forecast": {
                "entity_id": solar_entity,
                "state": solar_state.state if solar_state else None,
                "has_detailedHourly": bool(
                    solar_state
                    and solar_state.attributes.get("detailedHourly")
                ),
                "has_detailedForecast": bool(
                    solar_state
                    and solar_state.attributes.get("detailedForecast")
                ),
            },
        }

        result["charging_active"] = coordinator._charging_active
        result["last_simulation"] = coordinator.last_simulation_summary

        # Performance tracking data
        result["performance"] = {
            "last_daily_scorecard": coordinator.last_daily_scorecard,
            "solar_correction_factor": round(
                coordinator.solar_correction_factor, 3
            ),
            "effective_base_load": round(coordinator.effective_base_load, 2),
            "prediction_snapshots_today": len(
                coordinator.prediction_snapshots
            ),
            "charge_events_today": coordinator.charge_events_today,
            "actual_soc_checkpoints": coordinator.actual_soc_checkpoints,
            "actual_solar_hourly": coordinator.actual_solar_hourly,
            "recent_grades": (
                coordinator.store.recent_grades(7)
                if coordinator.store
                else []
            ),
            "rolling_score_7d": (
                coordinator.store.rolling_score(7)
                if coordinator.store
                else None
            ),
            "rolling_margin_14d": (
                coordinator.store.rolling_margin(14)
                if coordinator.store
                else None
            ),
            "history_days_stored": (
                len(coordinator.store.days)
                if coordinator.store
                else 0
            ),
        }

    return result
