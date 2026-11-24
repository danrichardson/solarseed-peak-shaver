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

        # The tariff as the integration reads it (0.9.1)
        tariff = coordinator.tariff
        result["tariff"] = {
            **tariff.describe(coordinator._now().date()),
            "base_windows": tariff.windows.text(),
            "weekdays_only": tariff.weekdays_only,
            "seasons": [{"name": s.name, "months": list(s.months),
                         "windows": s.windows.text() if s.windows else None,
                         "prices": dict(s.prices)} for s in tariff.seasons],
            "holiday_preset": coordinator.holiday_preset,
            "holiday_rules": len(tariff.holidays.rules),
            "holiday_one_off_dates": len(tariff.holidays.dates),
        }

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

    runtime = getattr(coordinator, "learned", None) if coordinator else None
    if runtime is not None:
        result["learned"] = {
            "planner_in_control": coordinator.planner,
            "power_sensors_configured": runtime.sensors_configured,
            "decision": runtime.decision.as_dict() if runtime.decision else None,
            "bank_full": runtime.bank_full,
            "weekly_topup_pending": runtime.topup_pending,
            "battery_data_stale": runtime.data_stale,
            "stale_minutes_setting": coordinator.stale_minutes,
            "seconds_since_last_change": (
                None if runtime._last_change is None or runtime._last_tick is None
                else round((runtime._last_tick - runtime._last_change).total_seconds())
            ),
            "curves": runtime.curve_table(),
            "load_profile_tou_kw": {
                str(h): round(runtime.profile.mean(True, h), 3) for h in range(24)
            },
            "load_history_days": {
                "tou": runtime.profile.n_days(True),
                "other": runtime.profile.n_days(False),
            },
            "today": runtime.daily_summary(),
            "last_backfill": runtime.last_backfill,
        }
        tracker = runtime.pack_tracker()
        if tracker is not None:
            result["packs"] = {
                "current_entities": tracker.packs,
                "bus_voltage": runtime.bus_voltage(),
                "bus_voltage_entity": coordinator.bus_voltage_entity or None,
                "charge_estimate_pct": {p: tracker.estimate_pct(p) for p in tracker.packs},
                "tracker": tracker.to_dict(),
            }

    return result
