"""Tests for the coordinator's pure-logic methods (no HA runtime needed)."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from tests.conftest import _make_config_entry, _make_store, make_scorecard


def _make_coordinator(config_overrides=None, days=None):
    """Build a PeakShaverCoordinator with mocked HA dependencies."""
    from custom_components.solarseed_peak_shaver.coordinator import (
        PeakShaverCoordinator,
    )

    entry = _make_config_entry(data=config_overrides)
    store = _make_store(days=days)

    hass = MagicMock()
    hass.data = {}
    hass.states = MagicMock()
    hass.bus = MagicMock()
    hass.services = MagicMock()
    hass.async_create_task = MagicMock()

    # Patch the parent __init__ to prevent HA-specific setup
    with patch.object(
        PeakShaverCoordinator,
        "__init__",
        lambda self, *a, **k: None,
    ):
        coord = PeakShaverCoordinator.__new__(PeakShaverCoordinator)

    # Manually set instance attributes (mirroring __init__)
    coord.hass = hass
    coord.entry = entry
    coord.store = store
    coord._unsub_listeners = []
    coord._charging_active = False
    coord.last_simulation_csv = ""
    coord.last_simulation_summary = ""
    coord._tracking_date = None
    coord.prediction_snapshots = []
    coord.actual_soc_checkpoints = {}
    coord.actual_solar_hourly = {}
    coord._last_solar_actual_reading = None
    coord.charge_events_today = []
    coord._charge_start_time = None
    coord._charge_start_soc = 0.0
    coord._daily_min_soc = float("inf")
    coord._daily_min_tracking = False
    coord.last_daily_scorecard = {}
    coord.data = {}
    coord.name = "solarseed_peak_shaver"
    coord.logger = MagicMock()

    return coord


# ───────────────────────────────────────────────────────────────────
# Config access
# ───────────────────────────────────────────────────────────────────

class TestConfigAccess:
    """Verify config property accessors."""

    def test_defaults(self):
        coord = _make_coordinator()
        assert coord.battery_capacity == 23.5
        assert coord.base_load_kw == 0.6
        assert coord.min_safe_soc == 1.5
        assert coord.midpeak_start == 7
        assert coord.peak_start == 17
        assert coord.peak_end == 21

    def test_options_override_data(self):
        coord = _make_coordinator(config_overrides={"battery_capacity": 23.5})
        coord.entry.options = {"battery_capacity": 30.0}
        assert coord.battery_capacity == 30.0

    def test_schedule_hours_from_string(self):
        coord = _make_coordinator(config_overrides={"schedule_hours": "3,4,5,6"})
        assert coord.schedule_hours == [3, 4, 5, 6]

    def test_schedule_hours_from_list(self):
        coord = _make_coordinator(config_overrides={"schedule_hours": [2, 3, 4]})
        assert coord.schedule_hours == [2, 3, 4]

    def test_seasonal_months_from_string(self):
        coord = _make_coordinator(config_overrides={"seasonal_months": "11,12,1,2"})
        assert coord.seasonal_months == [11, 12, 1, 2]


# ───────────────────────────────────────────────────────────────────
# Static helpers
# ───────────────────────────────────────────────────────────────────

class TestStaticHelpers:
    """Test static/pure helper methods."""

    def test_safe_float_from_float(self):
        from custom_components.solarseed_peak_shaver.coordinator import (
            PeakShaverCoordinator,
        )
        assert PeakShaverCoordinator._safe_float(3.14) == 3.14

    def test_safe_float_from_string(self):
        from custom_components.solarseed_peak_shaver.coordinator import (
            PeakShaverCoordinator,
        )
        assert PeakShaverCoordinator._safe_float("12.5") == 12.5

    def test_safe_float_from_bad_string(self):
        from custom_components.solarseed_peak_shaver.coordinator import (
            PeakShaverCoordinator,
        )
        assert PeakShaverCoordinator._safe_float("unavailable", 0.0) == 0.0

    def test_safe_float_from_none(self):
        from custom_components.solarseed_peak_shaver.coordinator import (
            PeakShaverCoordinator,
        )
        assert PeakShaverCoordinator._safe_float(None, 5.0) == 5.0


# ───────────────────────────────────────────────────────────────────
# Period classification
# ───────────────────────────────────────────────────────────────────

class TestPeriodClassification:
    def test_off_peak_night(self):
        coord = _make_coordinator()
        dt = datetime(2026, 2, 20, 3, 0)  # 3 AM
        assert coord._classify_period(dt) == "off-peak"

    def test_off_peak_late(self):
        coord = _make_coordinator()
        dt = datetime(2026, 2, 20, 22, 0)  # 10 PM
        assert coord._classify_period(dt) == "off-peak"

    def test_mid_peak(self):
        coord = _make_coordinator()
        dt = datetime(2026, 2, 20, 10, 0)  # 10 AM
        assert coord._classify_period(dt) == "mid-peak"

    def test_peak(self):
        coord = _make_coordinator()
        dt = datetime(2026, 2, 20, 18, 0)  # 6 PM
        assert coord._classify_period(dt) == "peak"

    def test_boundary_midpeak_start(self):
        coord = _make_coordinator()
        dt = datetime(2026, 2, 20, 7, 0)  # 7 AM = midpeak start
        assert coord._classify_period(dt) == "mid-peak"

    def test_boundary_peak_start(self):
        coord = _make_coordinator()
        dt = datetime(2026, 2, 20, 17, 0)  # 5 PM = peak start
        assert coord._classify_period(dt) == "peak"

    def test_boundary_peak_end(self):
        coord = _make_coordinator()
        dt = datetime(2026, 2, 20, 21, 0)  # 9 PM = peak end → off-peak
        assert coord._classify_period(dt) == "off-peak"


# ───────────────────────────────────────────────────────────────────
# Solar correction factors
# ───────────────────────────────────────────────────────────────────

class TestSolarCorrectionFactors:
    def test_no_history(self):
        coord = _make_coordinator()
        assert coord.solar_correction_factor == 1.0

    def test_with_history_perfect(self):
        days = [
            make_scorecard(
                date=f"2026-02-{i+1:02d}",
                solar_predicted_kwh=10.0,
                solar_actual_kwh=10.0,
            )
            for i in range(10)
        ]
        coord = _make_coordinator(days=days)
        assert abs(coord.solar_correction_factor - 1.0) < 0.01

    def test_with_history_pessimistic(self):
        days = [
            make_scorecard(
                date=f"2026-02-{i+1:02d}",
                solar_predicted_kwh=10.0,
                solar_actual_kwh=8.0,
            )
            for i in range(10)
        ]
        coord = _make_coordinator(days=days)
        assert coord.solar_correction_factor < 1.0

    def test_correction_factor_clamped_low(self):
        days = [
            make_scorecard(
                date=f"2026-02-{i+1:02d}",
                solar_predicted_kwh=10.0,
                solar_actual_kwh=1.0,  # 10% ratio, should clamp at 0.5
            )
            for i in range(10)
        ]
        coord = _make_coordinator(days=days)
        assert coord.solar_correction_factor == 0.5

    def test_correction_factor_clamped_high(self):
        days = [
            make_scorecard(
                date=f"2026-02-{i+1:02d}",
                solar_predicted_kwh=10.0,
                solar_actual_kwh=20.0,  # 200% ratio, should clamp at 1.2
            )
            for i in range(10)
        ]
        coord = _make_coordinator(days=days)
        assert coord.solar_correction_factor == 1.2


# ───────────────────────────────────────────────────────────────────
# Effective base load
# ───────────────────────────────────────────────────────────────────

class TestEffectiveBaseLoad:
    def test_no_history_uses_config(self):
        coord = _make_coordinator(config_overrides={"base_load_kw": 0.7})
        assert coord.effective_base_load == 0.7

    def test_with_history(self):
        days = [
            make_scorecard(
                date=f"2026-02-{i+1:02d}",
                effective_base_load_kw=0.55,
            )
            for i in range(10)
        ]
        coord = _make_coordinator(days=days)
        assert abs(coord.effective_base_load - 0.55) < 0.01


# ───────────────────────────────────────────────────────────────────
# Daily tracking reset
# ───────────────────────────────────────────────────────────────────

class TestDailyReset:
    def test_reset_on_new_date(self):
        coord = _make_coordinator()
        coord._tracking_date = "2026-02-19"
        coord.prediction_snapshots = [{"test": 1}]
        coord.charge_events_today = [{"test": 1}]
        coord._reset_daily_tracking()
        assert coord.prediction_snapshots == []
        assert coord.charge_events_today == []
        assert coord._tracking_date == datetime.now().strftime("%Y-%m-%d")

    def test_no_reset_same_date(self):
        coord = _make_coordinator()
        today = datetime.now().strftime("%Y-%m-%d")
        coord._tracking_date = today
        coord.prediction_snapshots = [{"test": 1}]
        coord._reset_daily_tracking()
        # Should NOT reset
        assert len(coord.prediction_snapshots) == 1


# ───────────────────────────────────────────────────────────────────
# Prediction snapshot recording
# ───────────────────────────────────────────────────────────────────

class TestPredictionSnapshots:
    def test_record_snapshot(self):
        coord = _make_coordinator()
        coord._record_prediction_snapshot(
            run_type="scheduled",
            current_soc=12.0,
            battery_at_peak=10.0,
            min_battery=3.0,
            target_soc=12.0,
            charge_needed=0.0,
            charge_below=8.0,
            hourly_solar={10: 2.5, 11: 3.0},
            charging_triggered=False,
        )
        assert len(coord.prediction_snapshots) == 1
        snap = coord.prediction_snapshots[0]
        assert snap["run_type"] == "scheduled"
        assert snap["current_soc_kwh"] == 12.0
        assert snap["charging_triggered"] is False

    def test_multiple_snapshots(self):
        coord = _make_coordinator()
        for i in range(3):
            coord._record_prediction_snapshot(
                run_type="scheduled",
                current_soc=10.0 + i,
                battery_at_peak=8.0,
                min_battery=3.0,
                target_soc=10.0 + i,
                charge_needed=0.0,
                charge_below=7.0,
                hourly_solar={},
                charging_triggered=False,
            )
        assert len(coord.prediction_snapshots) == 3
