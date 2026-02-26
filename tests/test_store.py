"""Tests for PeakShaverStore — persistence, rolling averages, and CSV export."""
from __future__ import annotations

import pytest
from tests.conftest import _make_store, make_scorecard


# ───────────────────────────────────────────────────────────────────
# Basic storage operations
# ───────────────────────────────────────────────────────────────────

class TestStoreBasics:
    """Core store CRUD operations."""

    def test_empty_store(self):
        store = _make_store()
        assert store.days == []

    def test_add_scorecard(self):
        store = _make_store()
        sc = make_scorecard(date="2026-02-20")
        store.add_scorecard(sc)
        assert len(store.days) == 1
        assert store.days[0]["date"] == "2026-02-20"

    def test_add_scorecard_replaces_same_date(self):
        store = _make_store()
        sc1 = make_scorecard(date="2026-02-20", score=80)
        sc2 = make_scorecard(date="2026-02-20", score=95)
        store.add_scorecard(sc1)
        store.add_scorecard(sc2)
        assert len(store.days) == 1
        assert store.days[0]["score"] == 95

    def test_add_multiple_dates(self):
        store = _make_store()
        for i in range(5):
            store.add_scorecard(make_scorecard(date=f"2026-02-{20+i:02d}"))
        assert len(store.days) == 5

    def test_preloaded_days(self):
        days = [make_scorecard(date=f"2026-02-{i:02d}") for i in range(1, 4)]
        store = _make_store(days=days)
        assert len(store.days) == 3


# ───────────────────────────────────────────────────────────────────
# Rolling averages
# ───────────────────────────────────────────────────────────────────

class TestRollingAverages:
    """Test rolling average computations."""

    def _make_store_with_days(self, n: int = 14, **overrides):
        days = []
        for i in range(n):
            sc = make_scorecard(date=f"2026-02-{i+1:02d}", **overrides)
            days.append(sc)
        return _make_store(days=days)

    def test_rolling_solar_accuracy_perfect(self):
        store = self._make_store_with_days(
            10, solar_predicted_kwh=10.0, solar_actual_kwh=10.0,
        )
        assert abs(store.rolling_solar_accuracy(10) - 1.0) < 0.01

    def test_rolling_solar_accuracy_80pct(self):
        store = self._make_store_with_days(
            10, solar_predicted_kwh=10.0, solar_actual_kwh=8.0,
        )
        assert abs(store.rolling_solar_accuracy(10) - 0.8) < 0.01

    def test_rolling_solar_accuracy_no_actual(self):
        store = self._make_store_with_days(5, solar_actual_kwh=None)
        # Falls back to 1.0 when no actual data
        assert store.rolling_solar_accuracy(5) == 1.0

    def test_rolling_base_load(self):
        store = self._make_store_with_days(10, effective_base_load_kw=0.65)
        result = store.rolling_base_load(10)
        assert result is not None
        assert abs(result - 0.65) < 0.01

    def test_rolling_base_load_none(self):
        store = self._make_store_with_days(5, effective_base_load_kw=None)
        assert store.rolling_base_load(5) is None

    def test_rolling_prediction_error(self):
        store = self._make_store_with_days(7, min_prediction_error_kwh=0.3)
        result = store.rolling_prediction_error(7)
        assert result is not None
        assert abs(result - 0.3) < 0.01

    def test_rolling_score(self):
        store = self._make_store_with_days(7, score=85)
        result = store.rolling_score(7)
        assert result is not None
        assert abs(result - 85.0) < 0.1

    def test_rolling_margin(self):
        store = self._make_store_with_days(
            7, battery_min_actual=3.5, min_safe_soc=1.5,
        )
        result = store.rolling_margin(7)
        assert result is not None
        assert abs(result - 2.0) < 0.01

    def test_rolling_margin_floor_breached(self):
        store = self._make_store_with_days(
            7, battery_min_actual=1.0, min_safe_soc=1.5,
        )
        result = store.rolling_margin(7)
        assert result is not None
        assert result < 0  # negative margin = breach

    def test_recent_grades(self):
        days = [
            make_scorecard(date=f"2026-02-{i+1:02d}", grade=g)
            for i, g in enumerate(["A", "B", "A", "C", "A"])
        ]
        store = _make_store(days=days)
        grades = store.recent_grades(5)
        assert grades == ["A", "B", "A", "C", "A"]

    def test_recent_grades_limited(self):
        days = [
            make_scorecard(date=f"2026-02-{i+1:02d}", grade="A")
            for i in range(10)
        ]
        store = _make_store(days=days)
        grades = store.recent_grades(3)
        assert len(grades) == 3


# ───────────────────────────────────────────────────────────────────
# Hourly solar ratios
# ───────────────────────────────────────────────────────────────────

class TestHourlySolarRatios:
    """Test per-hour solar correction factor calculation."""

    def test_perfect_forecast(self):
        solar = {str(h): 1.0 for h in range(7, 19)}
        days = [
            make_scorecard(
                date=f"2026-02-{i+1:02d}",
                hourly_solar_predicted=solar,
                hourly_solar_actual=solar,
            )
            for i in range(10)
        ]
        store = _make_store(days=days)
        ratios = store.hourly_solar_ratios(10)
        for h, r in ratios.items():
            assert abs(r - 1.0) < 0.01

    def test_optimistic_forecast(self):
        predicted = {str(h): 2.0 for h in range(7, 19)}
        actual = {str(h): 1.0 for h in range(7, 19)}
        days = [
            make_scorecard(
                date=f"2026-02-{i+1:02d}",
                hourly_solar_predicted=predicted,
                hourly_solar_actual=actual,
            )
            for i in range(10)
        ]
        store = _make_store(days=days)
        ratios = store.hourly_solar_ratios(10)
        for h, r in ratios.items():
            assert abs(r - 0.5) < 0.01

    def test_ignores_near_zero_predictions(self):
        """Hours with < 0.05 kWh predicted should be excluded."""
        predicted = {"8": 0.03, "12": 2.0}
        actual = {"8": 0.5, "12": 1.8}
        days = [
            make_scorecard(
                date=f"2026-02-{i+1:02d}",
                hourly_solar_predicted=predicted,
                hourly_solar_actual=actual,
            )
            for i in range(10)
        ]
        store = _make_store(days=days)
        ratios = store.hourly_solar_ratios(10)
        assert 8 not in ratios  # excluded
        assert 12 in ratios


# ───────────────────────────────────────────────────────────────────
# CSV export
# ───────────────────────────────────────────────────────────────────

class TestCSVExport:
    """Test CSV export functionality."""

    def test_export_csv_empty(self):
        store = _make_store()
        assert store.export_csv() == ""

    def test_export_csv_has_header(self):
        store = _make_store(days=[make_scorecard()])
        csv = store.export_csv()
        header = csv.split("\n")[0]
        assert "date" in header
        assert "grade" in header
        assert "charge_surplus_kwh" in header
        assert "margin_above_floor_kwh" in header

    def test_export_csv_row_count(self):
        days = [make_scorecard(date=f"2026-02-{i+1:02d}") for i in range(5)]
        store = _make_store(days=days)
        csv = store.export_csv()
        lines = csv.strip().split("\n")
        assert len(lines) == 6  # 1 header + 5 data

    def test_export_csv_days_filter(self):
        days = [make_scorecard(date=f"2026-02-{i+1:02d}") for i in range(10)]
        store = _make_store(days=days)
        csv = store.export_csv(days=3)
        lines = csv.strip().split("\n")
        assert len(lines) == 4  # 1 header + 3 data

    def test_export_csv_derived_columns(self):
        """margin_above_floor and charge_surplus should be computed."""
        sc = make_scorecard(
            battery_min_actual=4.0,
            battery_min_predicted=3.0,
            min_safe_soc=1.5,
        )
        store = _make_store(days=[sc])
        csv = store.export_csv()
        lines = csv.strip().split("\n")
        header = lines[0].split(",")
        row = lines[1].split(",")
        data = dict(zip(header, row))
        # margin = actual_min - min_safe = 4.0 - 1.5 = 2.5
        assert float(data["margin_above_floor_kwh"]) == 2.5
        # surplus = actual_min - predicted_min = 4.0 - 3.0 = 1.0
        assert float(data["charge_surplus_kwh"]) == 1.0

    def test_export_csv_column_count(self):
        store = _make_store(days=[make_scorecard()])
        csv = store.export_csv()
        lines = csv.strip().split("\n")
        header_cols = lines[0].split(",")
        data_cols = lines[1].split(",")
        assert len(header_cols) == 21
        assert len(data_cols) == 21

    def test_export_hourly_solar_csv_empty(self):
        store = _make_store()
        assert store.export_hourly_solar_csv() == ""

    def test_export_hourly_solar_csv_structure(self):
        sc = make_scorecard(
            hourly_solar_predicted={"10": 2.0, "11": 2.5},
            hourly_solar_actual={"10": 1.8, "11": 2.3},
        )
        store = _make_store(days=[sc])
        csv = store.export_hourly_solar_csv()
        lines = csv.strip().split("\n")
        assert lines[0] == "date,hour,solar_predicted_kwh,solar_actual_kwh,error_kwh,ratio"
        assert len(lines) == 3  # header + 2 hours

    def test_export_hourly_solar_csv_error_calc(self):
        sc = make_scorecard(
            hourly_solar_predicted={"12": 3.0},
            hourly_solar_actual={"12": 2.5},
        )
        store = _make_store(days=[sc])
        csv = store.export_hourly_solar_csv()
        lines = csv.strip().split("\n")
        row = lines[1].split(",")
        # error = actual - predicted = 2.5 - 3.0 = -0.5
        assert float(row[4]) == -0.5
        # ratio = actual / predicted = 2.5 / 3.0 ≈ 0.833
        assert abs(float(row[5]) - 0.833) < 0.01
