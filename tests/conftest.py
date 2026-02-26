"""Shared test fixtures for Solarseed Peak Shaver tests."""
from __future__ import annotations

# Install HA mocks BEFORE any custom_components imports
import tests.ha_mocks  # noqa: F401

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Minimal stubs that let us import the integration modules without a running
# Home Assistant instance.  Tests that need a real HA loop should use
# homeassistant-core's pytest plugin, but these stubs let us run *fast*
# unit tests against pure logic.
# ---------------------------------------------------------------------------


def _make_config_entry(data: dict | None = None, options: dict | None = None):
    """Build a fake ConfigEntry with reasonable defaults."""
    from custom_components.solarseed_peak_shaver.const import (
        CONF_BATTERY_CAPACITY,
        CONF_BATTERY_SOC_ENTITY,
        CONF_BASE_LOAD,
        CONF_CHARGE_THRESHOLD,
        CONF_MIDPEAK_START,
        CONF_MIN_SAFE_SOC,
        CONF_NOTIFICATIONS_ENABLED,
        CONF_NOTIFY_ENTITY,
        CONF_PEAK_END,
        CONF_PEAK_START,
        CONF_SCHEDULE_HOURS,
        CONF_SEASONAL_MONTHS,
        CONF_SEASONAL_PRESERVATION,
        CONF_SOLAR_ACTUAL_ENTITY,
        CONF_SOLAR_FORECAST_ENTITY,
        CONF_VERBOSE_LOGGING,
        CONF_WEEKDAYS_ONLY,
    )

    defaults = {
        CONF_BATTERY_SOC_ENTITY: "sensor.battery_soc",
        CONF_SOLAR_FORECAST_ENTITY: "sensor.solcast_today",
        CONF_BATTERY_CAPACITY: 23.5,
        CONF_BASE_LOAD: 0.6,
        CONF_MIN_SAFE_SOC: 1.5,
        CONF_MIDPEAK_START: 7,
        CONF_PEAK_START: 17,
        CONF_PEAK_END: 21,
        CONF_WEEKDAYS_ONLY: True,
        CONF_SCHEDULE_HOURS: [3, 4, 5, 6],
        CONF_NOTIFICATIONS_ENABLED: False,
        CONF_NOTIFY_ENTITY: "",
        CONF_CHARGE_THRESHOLD: 0.5,
        CONF_SEASONAL_PRESERVATION: True,
        CONF_SEASONAL_MONTHS: [11, 12, 1, 2, 3],
        CONF_VERBOSE_LOGGING: False,
        CONF_SOLAR_ACTUAL_ENTITY: "",
    }
    if data:
        defaults.update(data)

    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = defaults
    entry.options = options or {}
    return entry


def _make_store(days: list[dict] | None = None):
    """Build a PeakShaverStore with optional pre-loaded days."""
    from custom_components.solarseed_peak_shaver.store import PeakShaverStore

    hass = MagicMock()
    store = PeakShaverStore.__new__(PeakShaverStore)
    store._store = MagicMock()
    store._data = {"version": 1, "days": list(days or [])}
    return store


@pytest.fixture
def config_entry():
    """Return a default config entry."""
    return _make_config_entry()


@pytest.fixture
def store():
    """Return an empty PeakShaverStore."""
    return _make_store()


def make_scorecard(
    date: str = "2026-02-20",
    grade: str = "A",
    score: int = 95,
    solar_predicted_kwh: float = 15.0,
    solar_actual_kwh: float | None = 14.0,
    solar_accuracy_pct: float | None = 93.3,
    battery_min_predicted: float = 3.0,
    battery_min_actual: float | None = 3.5,
    min_prediction_error_kwh: float | None = -0.5,
    min_safe_soc: float = 1.5,
    floor_breached: bool = False,
    midpeak_charge_triggered: bool = False,
    total_charged_kwh: float = 0.0,
    unnecessary_charge_kwh: float = 0.0,
    effective_base_load_kw: float | None = 0.58,
    solar_correction_factor: float = 1.0,
    battery_at_midpeak_predicted: float = 12.0,
    battery_at_midpeak_actual: float | None = 11.5,
    midpeak_prediction_error_kwh: float | None = 0.5,
    hourly_solar_predicted: dict | None = None,
    hourly_solar_actual: dict | None = None,
) -> dict:
    """Build a scorecard dict for testing."""
    return {
        "date": date,
        "grade": grade,
        "score": score,
        "solar_predicted_kwh": solar_predicted_kwh,
        "solar_actual_kwh": solar_actual_kwh,
        "solar_accuracy_pct": solar_accuracy_pct,
        "battery_at_midpeak_predicted": battery_at_midpeak_predicted,
        "battery_at_midpeak_actual": battery_at_midpeak_actual,
        "midpeak_prediction_error_kwh": midpeak_prediction_error_kwh,
        "battery_min_predicted": battery_min_predicted,
        "battery_min_actual": battery_min_actual,
        "min_prediction_error_kwh": min_prediction_error_kwh,
        "min_safe_soc": min_safe_soc,
        "floor_breached": floor_breached,
        "midpeak_charge_triggered": midpeak_charge_triggered,
        "total_charged_kwh": total_charged_kwh,
        "unnecessary_charge_kwh": unnecessary_charge_kwh,
        "effective_base_load_kw": effective_base_load_kw,
        "solar_correction_factor": solar_correction_factor,
        "hourly_solar_predicted": hourly_solar_predicted or {
            "7": 0.1, "8": 0.5, "9": 1.2, "10": 2.0,
            "11": 2.5, "12": 2.8, "13": 2.5, "14": 2.0,
            "15": 1.5, "16": 0.8, "17": 0.3, "18": 0.1,
        },
        "hourly_solar_actual": hourly_solar_actual or {
            "7": 0.08, "8": 0.45, "9": 1.1, "10": 1.9,
            "11": 2.3, "12": 2.6, "13": 2.3, "14": 1.8,
            "15": 1.3, "16": 0.7, "17": 0.25, "18": 0.05,
        },
        "charge_events": [],
        "prediction_snapshots_count": 1,
    }
