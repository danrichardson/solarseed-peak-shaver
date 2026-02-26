"""Tests for the SPC analysis script (tools/analyze_performance.py)."""
from __future__ import annotations

import json
import pytest
import sys
from pathlib import Path

# Allow imports from the tools directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from analyze_performance import (
    DailyRecord,
    HourlySolar,
    ControlChart,
    CpkResult,
    _mean,
    _stdev,
    _median,
    _percentile,
    _skewness,
    _moving_range_stdev,
    control_chart,
    process_capability,
    asymmetric_cost_analysis,
    solar_forecast_analysis,
    base_load_analysis,
    grade_distribution,
    generate_report,
    format_text_report,
    parse_daily_csv,
    parse_hourly_solar_csv,
)


# ───────────────────────────────────────────────────────────────────
# Math helpers
# ───────────────────────────────────────────────────────────────────

class TestMathHelpers:
    def test_mean(self):
        assert _mean([1, 2, 3, 4, 5]) == 3.0

    def test_mean_empty(self):
        assert _mean([]) == 0.0

    def test_stdev(self):
        s = _stdev([2, 4, 4, 4, 5, 5, 7, 9])
        assert abs(s - 2.138) < 0.01  # sample stdev

    def test_stdev_single(self):
        assert _stdev([5]) == 0.0

    def test_median_odd(self):
        assert _median([1, 3, 5]) == 3.0

    def test_median_even(self):
        assert _median([1, 2, 3, 4]) == 2.5

    def test_percentile_50(self):
        vals = list(range(1, 101))
        assert abs(_percentile(vals, 50) - 50.5) < 1.0

    def test_percentile_extremes(self):
        vals = list(range(1, 11))
        assert _percentile(vals, 0) == 1
        assert _percentile(vals, 100) == 10

    def test_skewness_symmetric(self):
        vals = [1, 2, 3, 4, 5]
        assert abs(_skewness(vals)) < 0.1

    def test_moving_range_stdev(self):
        vals = [10.0, 10.5, 9.8, 10.2, 10.1]
        s = _moving_range_stdev(vals)
        assert s > 0
        assert s < 1.0  # should be small for this data


# ───────────────────────────────────────────────────────────────────
# CSV parsing
# ───────────────────────────────────────────────────────────────────

class TestCSVParsing:
    DAILY_CSV = (
        "date,grade,score,solar_predicted_kwh,solar_actual_kwh,solar_accuracy_pct,"
        "battery_at_midpeak_predicted,battery_at_midpeak_actual,"
        "midpeak_prediction_error_kwh,battery_min_predicted,battery_min_actual,"
        "min_prediction_error_kwh,min_safe_soc,floor_breached,"
        "midpeak_charge_triggered,total_charged_kwh,unnecessary_charge_kwh,"
        "effective_base_load_kw,solar_correction_factor,"
        "charge_surplus_kwh,margin_above_floor_kwh\n"
        "2026-02-20,A,95,15.0,14.0,93.3,12.0,11.5,0.5,3.0,3.5,-0.5,"
        "1.5,False,False,0.0,0.0,0.58,1.0,0.5,2.0\n"
        "2026-02-21,B,82,12.0,10.0,83.3,11.0,10.0,1.0,2.0,1.8,0.2,"
        "1.5,False,True,3.0,1.0,0.62,0.95,0.0,0.3\n"
    )

    HOURLY_CSV = (
        "date,hour,solar_predicted_kwh,solar_actual_kwh,error_kwh,ratio\n"
        "2026-02-20,10,2.0,1.8,-0.2,0.9\n"
        "2026-02-20,11,2.5,2.3,-0.2,0.92\n"
        "2026-02-20,12,3.0,2.8,-0.2,0.933\n"
    )

    def test_parse_daily_csv(self):
        records = parse_daily_csv(self.DAILY_CSV)
        assert len(records) == 2
        assert records[0].date == "2026-02-20"
        assert records[0].grade == "A"
        assert records[0].score == 95.0
        assert records[0].floor_breached is False

    def test_parse_daily_csv_types(self):
        records = parse_daily_csv(self.DAILY_CSV)
        r = records[0]
        assert isinstance(r.solar_predicted_kwh, float)
        assert isinstance(r.margin_above_floor_kwh, float)
        assert isinstance(r.floor_breached, bool)

    def test_parse_hourly_csv(self):
        records = parse_hourly_solar_csv(self.HOURLY_CSV)
        assert len(records) == 3
        assert records[0].hour == 10
        assert records[0].predicted == 2.0
        assert records[0].actual == 1.8
        assert abs(records[0].error - (-0.2)) < 0.001

    def test_parse_empty_csv(self):
        assert parse_daily_csv("") == []
        assert parse_hourly_solar_csv("") == []


# ───────────────────────────────────────────────────────────────────
# Control charts
# ───────────────────────────────────────────────────────────────────

class TestControlCharts:
    def test_basic_control_chart(self):
        vals = [10.0, 10.5, 9.8, 10.2, 10.1, 9.9, 10.3, 10.0, 9.7, 10.4]
        dates = [f"2026-02-{i+1:02d}" for i in range(len(vals))]
        chart = control_chart("test_metric", vals, dates)
        assert chart.metric_name == "test_metric"
        assert chart.n_points == 10
        assert chart.ucl > chart.mean
        assert chart.lcl < chart.mean

    def test_out_of_control_detection(self):
        vals = [10.0] * 9 + [20.0]  # last point is outlier
        dates = [f"2026-02-{i+1:02d}" for i in range(len(vals))]
        chart = control_chart("test", vals, dates)
        assert chart.n_out_of_control >= 1
        assert "2026-02-10" in chart.out_of_control_dates

    def test_insufficient_data(self):
        chart = control_chart("test", [1.0, 2.0], ["a", "b"])
        assert chart.n_points == 2
        assert chart.ucl == 0  # not enough data

    def test_trend_detection(self):
        # 8 consecutive points above mean
        vals = [5.0, 5.0, 5.0, 5.0, 5.0,  # below mean
                15.0, 15.0, 15.0, 15.0, 15.0,
                15.0, 15.0, 15.0]  # 8 above mean
        dates = [f"2026-02-{i+1:02d}" for i in range(len(vals))]
        chart = control_chart("test", vals, dates)
        assert chart.trend_detected is True


# ───────────────────────────────────────────────────────────────────
# Process capability (Cpk)
# ───────────────────────────────────────────────────────────────────

class TestProcessCapability:
    def test_capable_process(self):
        # Tight distribution well within spec
        vals = [2.0, 2.1, 1.9, 2.0, 2.1, 1.9, 2.0, 2.05, 1.95, 2.0]
        result = process_capability("test", vals, lsl=0.0, usl=5.0)
        assert result.cpk > 1.33
        assert "CAPABLE" in result.interpretation

    def test_incapable_process(self):
        # Wide distribution that exceeds spec limits
        vals = [-1.0, 6.0, -0.5, 5.5, 0.5, 4.5, -0.8, 5.8, 0.2, 4.8]
        result = process_capability("test", vals, lsl=0.0, usl=5.0)
        assert result.cpk < 1.0

    def test_insufficient_data(self):
        result = process_capability("test", [1.0, 2.0], lsl=0, usl=5)
        assert "Insufficient" in result.interpretation

    def test_no_variation(self):
        result = process_capability("test", [2.0] * 10, lsl=0, usl=5)
        assert result.cpk == 999.0


# ───────────────────────────────────────────────────────────────────
# Asymmetric cost analysis
# ───────────────────────────────────────────────────────────────────

class TestAsymmetricCostAnalysis:
    def _make_records(self, margins, surpluses=None):
        records = []
        for i, m in enumerate(margins):
            r = DailyRecord(
                date=f"2026-02-{i+1:02d}",
                margin_above_floor_kwh=m,
                charge_surplus_kwh=surpluses[i] if surpluses else max(m, 0),
                floor_breached=m < 0 if m is not None else False,
            )
            records.append(r)
        return records

    def test_perfect_operation(self):
        records = self._make_records([0.5, 0.3, 0.8, 0.4, 0.6], surpluses=[0]*5)
        result = asymmetric_cost_analysis(records)
        assert result["total_undercharge_kwh"] == 0
        assert result["total_overcharge_kwh"] == 0
        assert result["pct_days_floor_breached"] == 0

    def test_floor_breach_cost(self):
        records = self._make_records([-2.0])
        result = asymmetric_cost_analysis(records)
        assert result["total_undercharge_kwh"] == 2.0
        assert result["total_undercharge_cost"] == pytest.approx(2.0 * 0.44, abs=0.01)

    def test_overcharge_cost(self):
        records = self._make_records([3.0], surpluses=[3.0])
        result = asymmetric_cost_analysis(records)
        assert result["total_overcharge_kwh"] == 3.0
        assert result["total_overcharge_cost"] > 0

    def test_cost_ratio(self):
        result = asymmetric_cost_analysis(self._make_records([1.0]))
        assert result["cost_ratio_under_vs_over"] == pytest.approx(4.2, abs=0.5)

    def test_recommendation_floor_breach(self):
        # > 10% floor breach rate
        records = self._make_records([-1.0, -0.5, 1.0, 1.0, 1.0,
                                       1.0, 1.0, 1.0, 1.0, 1.0])
        result = asymmetric_cost_analysis(records)
        assert "floor breach" in result["recommendation"].lower()


# ───────────────────────────────────────────────────────────────────
# Solar forecast analysis
# ───────────────────────────────────────────────────────────────────

class TestSolarForecastAnalysis:
    def test_well_calibrated(self):
        records = [
            DailyRecord(
                solar_predicted_kwh=10.0,
                solar_actual_kwh=10.2,
            )
            for _ in range(10)
        ]
        result = solar_forecast_analysis(records)
        assert result["daily"]["bias"] == "well-calibrated"

    def test_optimistic_forecast(self):
        records = [
            DailyRecord(
                solar_predicted_kwh=15.0,
                solar_actual_kwh=10.0,
            )
            for _ in range(10)
        ]
        result = solar_forecast_analysis(records)
        assert "optimistic" in result["daily"]["bias"]
        assert result["daily"]["mean_error_kwh"] < 0

    def test_per_hour_analysis(self):
        hourly = [
            HourlySolar(date="2026-02-20", hour=10, predicted=2.0, actual=1.8, error=-0.2, ratio=0.9),
            HourlySolar(date="2026-02-20", hour=11, predicted=2.5, actual=2.3, error=-0.2, ratio=0.92),
        ]
        result = solar_forecast_analysis([], hourly=hourly)
        assert "per_hour" in result
        assert 10 in result["per_hour"]


# ───────────────────────────────────────────────────────────────────
# Base load analysis
# ───────────────────────────────────────────────────────────────────

class TestBaseLoadAnalysis:
    def test_stable_load(self):
        records = [DailyRecord(effective_base_load_kw=0.6) for _ in range(10)]
        result = base_load_analysis(records)
        assert result["stable"] is True
        assert abs(result["mean_kw"] - 0.6) < 0.01

    def test_no_data(self):
        records = [DailyRecord(effective_base_load_kw=None) for _ in range(5)]
        result = base_load_analysis(records)
        assert result["n_days"] == 0


# ───────────────────────────────────────────────────────────────────
# Grade distribution
# ───────────────────────────────────────────────────────────────────

class TestGradeDistribution:
    def test_distribution(self):
        records = [
            DailyRecord(grade="A", score=95),
            DailyRecord(grade="A", score=92),
            DailyRecord(grade="B", score=85),
            DailyRecord(grade="C", score=72),
        ]
        result = grade_distribution(records)
        assert result["distribution"]["A"] == 2
        assert result["distribution"]["B"] == 1
        assert result["total_days"] == 4

    def test_trend_detection(self):
        records = (
            [DailyRecord(grade="D", score=60)] * 10 +
            [DailyRecord(grade="A", score=95)] * 10
        )
        result = grade_distribution(records)
        assert "IMPROVING" in result["trend"]


# ───────────────────────────────────────────────────────────────────
# Full report
# ───────────────────────────────────────────────────────────────────

class TestFullReport:
    def _make_records(self, n: int = 20):
        records = []
        for i in range(n):
            records.append(DailyRecord(
                date=f"2026-02-{i+1:02d}",
                grade="A" if i % 2 == 0 else "B",
                score=90 + (i % 10),
                solar_predicted_kwh=15.0,
                solar_actual_kwh=14.0,
                solar_accuracy_pct=93.3,
                battery_min_predicted=3.0,
                battery_min_actual=3.5,
                min_prediction_error_kwh=-0.5,
                min_safe_soc=1.5,
                floor_breached=False,
                midpeak_charge_triggered=False,
                total_charged_kwh=0.0,
                unnecessary_charge_kwh=0.0,
                effective_base_load_kw=0.6,
                solar_correction_factor=1.0,
                charge_surplus_kwh=0.5,
                margin_above_floor_kwh=2.0,
            ))
        return records

    def test_report_structure(self):
        records = self._make_records()
        report = generate_report(records)
        assert "summary" in report
        assert "grades" in report
        assert "control_charts" in report
        assert "process_capability" in report
        assert "cost_analysis" in report
        assert "solar_forecast" in report
        assert "base_load" in report
        assert "recommendations" in report

    def test_report_json_serializable(self):
        records = self._make_records()
        report = generate_report(records)
        # Should not raise
        json_str = json.dumps(report, default=str)
        assert len(json_str) > 100

    def test_text_report_output(self):
        records = self._make_records()
        report = generate_report(records)
        text = format_text_report(report)
        assert "SPC ANALYSIS REPORT" in text
        assert "GRADE DISTRIBUTION" in text
        assert "CONTROL CHARTS" in text
        assert "PROCESS CAPABILITY" in text
        assert "RECOMMENDATIONS" in text
