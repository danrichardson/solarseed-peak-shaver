#!/usr/bin/env python3
"""
Solarseed Peak Shaver — SPC / Statistical Process Control Analysis

Reads CSV data exported from the export_history service and produces
a statistical quality report inspired by manufacturing SPC methodology.

Usage:
    # Copy CSV from the service response, save to a file, then:
    python analyze_performance.py daily_history.csv
    python analyze_performance.py daily_history.csv --hourly hourly_solar.csv
    python analyze_performance.py daily_history.csv --json   # machine-readable output

Metrics produced:
    - Control chart statistics (mean, UCL, LCL, out-of-control points)
    - Process capability indices (Cpk for margin-above-floor)
    - Solar forecast error distribution (bias, variance, per-hour)
    - Base load stability
    - Asymmetric cost-of-error analysis (PGE TOU rates)
    - Trend / drift detection
    - Actionable recommendations

Requires: Python 3.10+, no external dependencies (stdlib only).
Optional: pip install matplotlib   (for chart generation)
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

# ---------------------------------------------------------------------------
# TOU rate constants (PGE E-TOU-D as reference)
# ---------------------------------------------------------------------------
RATE_OFFPEAK = 0.09   # $/kWh
RATE_MIDPEAK = 0.18
RATE_PEAK = 0.44
ROUND_TRIP_LOSS = 0.15  # 15% inverter round-trip loss

# Cost per kWh of error in each direction
COST_UNDERCHARGE_PER_KWH = RATE_PEAK                                   # 0.44
COST_OVERCHARGE_PER_KWH = RATE_OFFPEAK + RATE_OFFPEAK * ROUND_TRIP_LOSS  # ~0.1035


# ---------------------------------------------------------------------------
# Helper math (stdlib-only, no numpy/scipy needed)
# ---------------------------------------------------------------------------
def _mean(vals: Sequence[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _stdev(vals: Sequence[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = _mean(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


def _median(vals: Sequence[float]) -> float:
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return 0.0
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def _percentile(vals: Sequence[float], pct: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * pct / 100.0
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def _skewness(vals: Sequence[float]) -> float:
    """Fisher-Pearson coefficient of skewness."""
    n = len(vals)
    if n < 3:
        return 0.0
    m = _mean(vals)
    s = _stdev(vals)
    if s == 0:
        return 0.0
    return (n / ((n - 1) * (n - 2))) * sum(((v - m) / s) ** 3 for v in vals)


def _moving_range_stdev(vals: Sequence[float]) -> float:
    """Estimate process sigma from moving range (d2=1.128 for n=2)."""
    if len(vals) < 2:
        return 0.0
    mr = [abs(vals[i] - vals[i - 1]) for i in range(1, len(vals))]
    return _mean(mr) / 1.128


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class DailyRecord:
    date: str = ""
    grade: str = ""
    score: float | None = None
    solar_predicted_kwh: float | None = None
    solar_actual_kwh: float | None = None
    solar_accuracy_pct: float | None = None
    battery_at_midpeak_predicted: float | None = None
    battery_at_midpeak_actual: float | None = None
    midpeak_prediction_error_kwh: float | None = None
    battery_min_predicted: float | None = None
    battery_min_actual: float | None = None
    min_prediction_error_kwh: float | None = None
    min_safe_soc: float | None = None
    floor_breached: bool = False
    midpeak_charge_triggered: bool = False
    total_charged_kwh: float | None = None
    unnecessary_charge_kwh: float | None = None
    effective_base_load_kw: float | None = None
    solar_correction_factor: float | None = None
    charge_surplus_kwh: float | None = None
    margin_above_floor_kwh: float | None = None


@dataclass
class HourlySolar:
    date: str = ""
    hour: int = 0
    predicted: float = 0.0
    actual: float = 0.0
    error: float = 0.0
    ratio: float | None = None


@dataclass
class ControlChart:
    """Individuals (I) control chart statistics."""
    metric_name: str = ""
    mean: float = 0.0
    sigma: float = 0.0
    ucl: float = 0.0
    lcl: float = 0.0
    n_points: int = 0
    n_out_of_control: int = 0
    out_of_control_dates: list[str] = field(default_factory=list)
    trend_detected: bool = False
    trend_direction: str = ""  # "improving" or "deteriorating"


@dataclass
class CpkResult:
    """Process capability index."""
    metric_name: str = ""
    cpk: float = 0.0
    cpu: float = 0.0  # upper capability
    cpl: float = 0.0  # lower capability
    ppm_defective: float = 0.0  # estimated parts-per-million outside spec
    interpretation: str = ""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def _safe_float(val: str) -> float | None:
    if val.strip() == "":
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _safe_bool(val: str) -> bool:
    return val.strip().lower() in ("true", "1", "yes")


def parse_daily_csv(text: str) -> list[DailyRecord]:
    """Parse daily scorecard CSV text into records."""
    reader = csv.DictReader(io.StringIO(text))
    records: list[DailyRecord] = []
    for row in reader:
        records.append(DailyRecord(
            date=row.get("date", ""),
            grade=row.get("grade", ""),
            score=_safe_float(row.get("score", "")),
            solar_predicted_kwh=_safe_float(row.get("solar_predicted_kwh", "")),
            solar_actual_kwh=_safe_float(row.get("solar_actual_kwh", "")),
            solar_accuracy_pct=_safe_float(row.get("solar_accuracy_pct", "")),
            battery_at_midpeak_predicted=_safe_float(
                row.get("battery_at_midpeak_predicted", "")
            ),
            battery_at_midpeak_actual=_safe_float(
                row.get("battery_at_midpeak_actual", "")
            ),
            midpeak_prediction_error_kwh=_safe_float(
                row.get("midpeak_prediction_error_kwh", "")
            ),
            battery_min_predicted=_safe_float(
                row.get("battery_min_predicted", "")
            ),
            battery_min_actual=_safe_float(row.get("battery_min_actual", "")),
            min_prediction_error_kwh=_safe_float(
                row.get("min_prediction_error_kwh", "")
            ),
            min_safe_soc=_safe_float(row.get("min_safe_soc", "")),
            floor_breached=_safe_bool(row.get("floor_breached", "")),
            midpeak_charge_triggered=_safe_bool(
                row.get("midpeak_charge_triggered", "")
            ),
            total_charged_kwh=_safe_float(row.get("total_charged_kwh", "")),
            unnecessary_charge_kwh=_safe_float(
                row.get("unnecessary_charge_kwh", "")
            ),
            effective_base_load_kw=_safe_float(
                row.get("effective_base_load_kw", "")
            ),
            solar_correction_factor=_safe_float(
                row.get("solar_correction_factor", "")
            ),
            charge_surplus_kwh=_safe_float(row.get("charge_surplus_kwh", "")),
            margin_above_floor_kwh=_safe_float(
                row.get("margin_above_floor_kwh", "")
            ),
        ))
    return records


def parse_hourly_solar_csv(text: str) -> list[HourlySolar]:
    """Parse hourly solar CSV text into records."""
    reader = csv.DictReader(io.StringIO(text))
    records: list[HourlySolar] = []
    for row in reader:
        r = _safe_float(row.get("ratio", ""))
        records.append(HourlySolar(
            date=row.get("date", ""),
            hour=int(row.get("hour", 0)),
            predicted=float(row.get("solar_predicted_kwh", 0)),
            actual=float(row.get("solar_actual_kwh", 0)),
            error=float(row.get("error_kwh", 0)),
            ratio=r,
        ))
    return records


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------
def control_chart(
    metric_name: str,
    values: list[float],
    dates: list[str],
) -> ControlChart:
    """Build an Individuals (I) control chart."""
    if len(values) < 3:
        return ControlChart(metric_name=metric_name, n_points=len(values))

    mean = _mean(values)
    # Use moving-range estimate for sigma (more robust than plain stdev)
    sigma = _moving_range_stdev(values)
    ucl = mean + 3 * sigma
    lcl = mean - 3 * sigma

    ooc_dates = []
    for v, d in zip(values, dates):
        if v > ucl or v < lcl:
            ooc_dates.append(d)

    # Simple trend detection: 7+ consecutive points on same side of mean
    trend = False
    trend_dir = ""
    run_above = 0
    run_below = 0
    max_run_above = 0
    max_run_below = 0
    for v in values:
        if v > mean:
            run_above += 1
            run_below = 0
        elif v < mean:
            run_below += 1
            run_above = 0
        else:
            run_above = 0
            run_below = 0
        max_run_above = max(max_run_above, run_above)
        max_run_below = max(max_run_below, run_below)

    if max_run_above >= 7 or max_run_below >= 7:
        trend = True
        # Check last 7 values to determine current trend
        last_7 = values[-7:]
        above = sum(1 for v in last_7 if v > mean)
        trend_dir = "improving" if above >= 5 else "deteriorating"

    return ControlChart(
        metric_name=metric_name,
        mean=round(mean, 3),
        sigma=round(sigma, 3),
        ucl=round(ucl, 3),
        lcl=round(lcl, 3),
        n_points=len(values),
        n_out_of_control=len(ooc_dates),
        out_of_control_dates=ooc_dates,
        trend_detected=trend,
        trend_direction=trend_dir,
    )


def process_capability(
    metric_name: str,
    values: list[float],
    lsl: float | None = None,       # lower spec limit
    usl: float | None = None,       # upper spec limit
    target: float | None = None,
) -> CpkResult:
    """Calculate Cpk (process capability index).

    For margin_above_floor: LSL=0 (never breach floor), USL=maybe 5 kWh (waste).
    For solar_accuracy_pct: target=100, LSL=70, USL=130.
    """
    if len(values) < 5:
        return CpkResult(metric_name=metric_name, interpretation="Insufficient data")

    mean = _mean(values)
    sigma = _stdev(values)
    if sigma == 0:
        return CpkResult(
            metric_name=metric_name, cpk=999.0,
            interpretation="No variation — perfect process (or no data)",
        )

    cpu = (usl - mean) / (3 * sigma) if usl is not None else 999.0
    cpl = (mean - lsl) / (3 * sigma) if lsl is not None else 999.0
    cpk = min(cpu, cpl)

    # Approximate PPM outside spec (assumes normal)
    # Using Cpk -> Z-score approximation
    z = cpk * 3
    # Simple approximation of tail probability
    # P(Z > z) ≈ 1 - Φ(z), using Abramowitz & Stegun approximation
    ppm = _normal_tail_ppm(z)

    if cpk >= 1.33:
        interp = "CAPABLE — process is well-centered within spec limits"
    elif cpk >= 1.0:
        interp = "MARGINAL — process is barely capable, watch for drift"
    elif cpk >= 0.67:
        interp = "POOR — significant fraction of outcomes outside spec"
    else:
        interp = "INCAPABLE — process cannot reliably meet spec limits"

    return CpkResult(
        metric_name=metric_name,
        cpk=round(cpk, 3),
        cpu=round(cpu, 3),
        cpl=round(cpl, 3),
        ppm_defective=round(ppm, 0),
        interpretation=interp,
    )


def _normal_tail_ppm(z: float) -> float:
    """Approximate one-tail PPM for standard normal."""
    if z < 0:
        return 500_000.0  # more than half outside
    if z > 6:
        return 0.001
    # Abramowitz & Stegun 26.2.17 approximation
    p = 0.2316419
    b1, b2, b3, b4, b5 = 0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429
    t = 1.0 / (1.0 + p * z)
    phi = (1.0 / math.sqrt(2 * math.pi)) * math.exp(-z * z / 2)
    tail = phi * (b1 * t + b2 * t**2 + b3 * t**3 + b4 * t**4 + b5 * t**5)
    return max(tail * 1_000_000, 0.001)


def asymmetric_cost_analysis(records: list[DailyRecord]) -> dict:
    """Calculate expected cost of errors using asymmetric loss function.

    Under-charging is ~4x more expensive per kWh than over-charging:
      - Under-charge: draw from grid at $0.44/kWh peak
      - Over-charge:  bought at $0.09 off-peak + 15% round-trip loss ≈ $0.1035/kWh wasted
    """
    total_cost = 0.0
    total_overcharge_kwh = 0.0
    total_undercharge_kwh = 0.0
    total_overcharge_cost = 0.0
    total_undercharge_cost = 0.0
    n_days = 0

    for r in records:
        margin = r.margin_above_floor_kwh
        if margin is None:
            continue
        n_days += 1

        if margin < 0:
            # Floor breached — undercharged
            cost = abs(margin) * COST_UNDERCHARGE_PER_KWH
            total_undercharge_kwh += abs(margin)
            total_undercharge_cost += cost
        else:
            # Extra headroom — overcharged
            # Not all margin is wasted (some is safety buffer), but the
            # charge_surplus_kwh is the true excess vs prediction
            surplus = r.charge_surplus_kwh
            if surplus is not None and surplus > 0:
                cost = surplus * COST_OVERCHARGE_PER_KWH
                total_overcharge_kwh += surplus
                total_overcharge_cost += cost
            else:
                cost = 0.0

        total_cost += cost

    daily_avg_cost = total_cost / n_days if n_days else 0.0
    monthly_est = daily_avg_cost * 30

    # Optimal bias: should we shift the mean charge decision?
    # With 4:1 cost ratio, optimal decision point is shifted toward overcharging.
    # Kelly-criterion-like: optimal_bias = (p_under * c_under - p_over * c_over)
    # / (c_under + c_over) where p is probability of each outcome.
    n_under = sum(1 for r in records if r.floor_breached)
    n_over = sum(
        1 for r in records
        if r.margin_above_floor_kwh is not None
        and r.margin_above_floor_kwh > 2.0
    )
    p_under = n_under / n_days if n_days else 0
    p_over = n_over / n_days if n_days else 0

    return {
        "n_days": n_days,
        "total_undercharge_kwh": round(total_undercharge_kwh, 2),
        "total_overcharge_kwh": round(total_overcharge_kwh, 2),
        "total_undercharge_cost": round(total_undercharge_cost, 2),
        "total_overcharge_cost": round(total_overcharge_cost, 2),
        "total_error_cost": round(total_cost, 2),
        "daily_avg_cost": round(daily_avg_cost, 3),
        "monthly_estimated_cost": round(monthly_est, 2),
        "cost_ratio_under_vs_over": round(
            COST_UNDERCHARGE_PER_KWH / COST_OVERCHARGE_PER_KWH, 1
        ),
        "pct_days_floor_breached": round(p_under * 100, 1),
        "pct_days_overconservative": round(p_over * 100, 1),
        "recommendation": (
            "Increase min_safe_soc or conservative bias — too many floor breaches"
            if p_under > 0.10
            else "Reduce conservative bias — too much overcharging"
            if p_over > 0.50
            else "Balance is reasonable — continue monitoring"
        ),
    }


def solar_forecast_analysis(
    records: list[DailyRecord],
    hourly: list[HourlySolar] | None = None,
) -> dict:
    """Analyze solar forecast accuracy at daily and hourly granularity."""
    # Daily accuracy
    daily_errors = [
        r.solar_actual_kwh - r.solar_predicted_kwh
        for r in records
        if r.solar_actual_kwh is not None and r.solar_predicted_kwh is not None
        and r.solar_predicted_kwh > 0
    ]

    daily_ratios = [
        r.solar_actual_kwh / r.solar_predicted_kwh
        for r in records
        if r.solar_actual_kwh is not None and r.solar_predicted_kwh is not None
        and r.solar_predicted_kwh > 0
    ]

    result: dict = {
        "daily": {
            "n_days": len(daily_errors),
            "mean_error_kwh": round(_mean(daily_errors), 2) if daily_errors else None,
            "stdev_error_kwh": round(_stdev(daily_errors), 2) if daily_errors else None,
            "median_error_kwh": round(_median(daily_errors), 2) if daily_errors else None,
            "skewness": round(_skewness(daily_errors), 3) if daily_errors else None,
            "mean_ratio": round(_mean(daily_ratios), 3) if daily_ratios else None,
            "p10_ratio": round(_percentile(daily_ratios, 10), 3) if daily_ratios else None,
            "p90_ratio": round(_percentile(daily_ratios, 90), 3) if daily_ratios else None,
            "bias": (
                "optimistic (forecast > actual)"
                if daily_errors and _mean(daily_errors) < -0.5
                else "pessimistic (forecast < actual)"
                if daily_errors and _mean(daily_errors) > 0.5
                else "well-calibrated"
            ),
        },
    }

    # Per-hour analysis
    if hourly:
        hour_errors: dict[int, list[float]] = defaultdict(list)
        hour_ratios: dict[int, list[float]] = defaultdict(list)
        for h in hourly:
            hour_errors[h.hour].append(h.error)
            if h.ratio is not None:
                hour_ratios[h.hour].append(h.ratio)

        per_hour = {}
        for hr in sorted(hour_errors.keys()):
            errs = hour_errors[hr]
            rats = hour_ratios.get(hr, [])
            per_hour[hr] = {
                "n_samples": len(errs),
                "mean_error_kwh": round(_mean(errs), 3),
                "stdev_error_kwh": round(_stdev(errs), 3),
                "mean_ratio": round(_mean(rats), 3) if rats else None,
                "recommended_correction": (
                    round(_mean(rats), 3) if rats and len(rats) >= 5 else None
                ),
            }
        result["per_hour"] = per_hour

        # Identify worst hours
        worst = sorted(
            ((hr, abs(_mean(hour_errors[hr]))) for hr in hour_errors if len(hour_errors[hr]) >= 3),
            key=lambda x: x[1],
            reverse=True,
        )[:3]
        result["worst_hours"] = [
            {"hour": h, "avg_abs_error_kwh": round(e, 3)} for h, e in worst
        ]

    return result


def base_load_analysis(records: list[DailyRecord]) -> dict:
    """Analyze base load stability."""
    loads = [
        r.effective_base_load_kw
        for r in records
        if r.effective_base_load_kw is not None
    ]
    if not loads:
        return {"n_days": 0, "message": "No base load data"}

    return {
        "n_days": len(loads),
        "mean_kw": round(_mean(loads), 3),
        "stdev_kw": round(_stdev(loads), 3),
        "min_kw": round(min(loads), 3),
        "max_kw": round(max(loads), 3),
        "cv_pct": round(_stdev(loads) / _mean(loads) * 100, 1) if _mean(loads) > 0 else 0,
        "stable": _stdev(loads) / _mean(loads) < 0.15 if _mean(loads) > 0 else True,
    }


def grade_distribution(records: list[DailyRecord]) -> dict:
    """Count grade distribution and trends."""
    grades = [r.grade for r in records if r.grade]
    dist: dict[str, int] = {}
    for g in grades:
        dist[g] = dist.get(g, 0) + 1

    # Recent trend (last 14 vs first 14 if enough data)
    scores = [r.score for r in records if r.score is not None]
    trend = ""
    if len(scores) >= 14:
        first_half = _mean(scores[: len(scores) // 2])
        second_half = _mean(scores[len(scores) // 2 :])
        diff = second_half - first_half
        if diff > 5:
            trend = f"IMPROVING (+{diff:.1f} points)"
        elif diff < -5:
            trend = f"DECLINING ({diff:.1f} points)"
        else:
            trend = "STABLE"

    return {
        "total_days": len(grades),
        "distribution": dist,
        "mean_score": round(_mean(scores), 1) if scores else None,
        "median_score": round(_median(scores), 1) if scores else None,
        "trend": trend,
    }


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------
def generate_report(
    records: list[DailyRecord],
    hourly: list[HourlySolar] | None = None,
) -> dict:
    """Generate the full SPC analysis report."""
    report: dict = {
        "summary": {
            "data_range": f"{records[0].date} — {records[-1].date}" if records else "N/A",
            "n_records": len(records),
        },
    }

    # 1. Grade distribution
    report["grades"] = grade_distribution(records)

    # 2. Control charts
    margin_vals = [
        r.margin_above_floor_kwh for r in records
        if r.margin_above_floor_kwh is not None
    ]
    margin_dates = [
        r.date for r in records
        if r.margin_above_floor_kwh is not None
    ]

    score_vals = [r.score for r in records if r.score is not None]
    score_dates = [r.date for r in records if r.score is not None]

    pred_err_vals = [
        r.min_prediction_error_kwh for r in records
        if r.min_prediction_error_kwh is not None
    ]
    pred_err_dates = [
        r.date for r in records
        if r.min_prediction_error_kwh is not None
    ]

    report["control_charts"] = {
        "margin_above_floor": vars(
            control_chart("margin_above_floor_kwh", margin_vals, margin_dates)
        ),
        "algorithm_score": vars(
            control_chart("algorithm_score", score_vals, score_dates)
        ),
        "prediction_error": vars(
            control_chart("min_prediction_error_kwh", pred_err_vals, pred_err_dates)
        ),
    }

    # 3. Process capability
    report["process_capability"] = {
        "margin_above_floor": vars(process_capability(
            "margin_above_floor_kwh",
            margin_vals,
            lsl=0.0,      # never breach floor
            usl=5.0,      # > 5 kWh headroom is wasteful overcharging
        )),
        "algorithm_score": vars(process_capability(
            "algorithm_score",
            score_vals,
            lsl=60.0,     # below 60 is a failing grade
            usl=None,     # no upper limit on score
        )),
    }

    # 4. Asymmetric cost analysis
    report["cost_analysis"] = asymmetric_cost_analysis(records)

    # 5. Solar forecast analysis
    report["solar_forecast"] = solar_forecast_analysis(records, hourly)

    # 6. Base load analysis
    report["base_load"] = base_load_analysis(records)

    # 7. Recommendations
    report["recommendations"] = _generate_recommendations(report, records)

    return report


def _generate_recommendations(report: dict, records: list[DailyRecord]) -> list[str]:
    """Generate actionable recommendations from the analysis."""
    recs: list[str] = []

    # Cost analysis
    cost = report.get("cost_analysis", {})
    if cost.get("pct_days_floor_breached", 0) > 10:
        recs.append(
            f"CRITICAL: Floor breached on {cost['pct_days_floor_breached']}% of days. "
            f"Increase min_safe_soc by 1-2 kWh or increase conservative bias."
        )
    if cost.get("pct_days_overconservative", 0) > 50:
        recs.append(
            f"OPTIMIZATION: Over-conservative on {cost['pct_days_overconservative']}% of days. "
            f"Margin > 2 kWh is wasteful. Consider reducing min_safe_soc by 0.5-1 kWh."
        )

    # Solar forecast
    solar = report.get("solar_forecast", {}).get("daily", {})
    if solar.get("mean_ratio") is not None:
        ratio = solar["mean_ratio"]
        if ratio < 0.80:
            recs.append(
                f"Solar forecast is significantly optimistic (ratio={ratio:.2f}). "
                f"Check Solcast configuration or consider switching providers."
            )
        elif ratio > 1.20:
            recs.append(
                f"Solar forecast is significantly pessimistic (ratio={ratio:.2f}). "
                f"The correction factor should adjust automatically, but verify sensor setup."
            )

    # Base load
    bl = report.get("base_load", {})
    if not bl.get("stable", True):
        recs.append(
            f"Base load is unstable (CV={bl.get('cv_pct', 0)}%). "
            f"Consider investigating what is causing load variance."
        )

    # Control charts
    for name, chart in report.get("control_charts", {}).items():
        if chart.get("n_out_of_control", 0) > 0:
            recs.append(
                f"Control chart '{name}' has {chart['n_out_of_control']} out-of-control "
                f"point(s) on: {', '.join(chart.get('out_of_control_dates', []))}. "
                f"Investigate these dates for unusual conditions."
            )
        if chart.get("trend_detected"):
            recs.append(
                f"Trend detected in '{name}': {chart.get('trend_direction', 'unknown')}. "
                f"If deteriorating, investigate recent changes."
            )

    # Process capability
    for name, cpk_data in report.get("process_capability", {}).items():
        if cpk_data.get("cpk", 999) < 1.0:
            recs.append(
                f"Process capability for '{name}' is low (Cpk={cpk_data['cpk']:.2f}). "
                f"{cpk_data.get('interpretation', '')}"
            )

    if not recs:
        recs.append("All metrics look healthy. Continue monitoring.")

    return recs


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------
def format_text_report(report: dict) -> str:
    """Format report as human-readable text."""
    lines: list[str] = []
    divider = "=" * 72

    lines.append(divider)
    lines.append("  SOLARSEED PEAK SHAVER — SPC ANALYSIS REPORT")
    lines.append(divider)
    lines.append(f"  Data range: {report['summary']['data_range']}")
    lines.append(f"  Records:    {report['summary']['n_records']}")
    lines.append("")

    # Grades
    g = report.get("grades", {})
    lines.append("─── GRADE DISTRIBUTION ───────────────────────────────────")
    if g.get("distribution"):
        for grade, count in sorted(g["distribution"].items()):
            bar = "█" * count
            lines.append(f"  {grade}: {bar} ({count})")
    lines.append(f"  Mean score: {g.get('mean_score', 'N/A')}")
    lines.append(f"  Trend:      {g.get('trend', 'N/A')}")
    lines.append("")

    # Control charts
    lines.append("─── CONTROL CHARTS ──────────────────────────────────────")
    for name, chart in report.get("control_charts", {}).items():
        lines.append(f"  {name}:")
        lines.append(f"    Mean={chart['mean']:.3f}  σ={chart['sigma']:.3f}  "
                      f"UCL={chart['ucl']:.3f}  LCL={chart['lcl']:.3f}")
        lines.append(f"    Points: {chart['n_points']}  "
                      f"Out-of-control: {chart['n_out_of_control']}")
        if chart.get("trend_detected"):
            lines.append(f"    ⚠ TREND: {chart['trend_direction']}")
        lines.append("")

    # Process capability
    lines.append("─── PROCESS CAPABILITY (Cpk) ────────────────────────────")
    for name, cpk_data in report.get("process_capability", {}).items():
        lines.append(f"  {name}:")
        lines.append(f"    Cpk={cpk_data['cpk']:.3f}  "
                      f"(CPU={cpk_data['cpu']:.3f}, CPL={cpk_data['cpl']:.3f})")
        lines.append(f"    Est. PPM defective: {cpk_data['ppm_defective']:.0f}")
        lines.append(f"    → {cpk_data['interpretation']}")
        lines.append("")

    # Cost analysis
    lines.append("─── ASYMMETRIC COST ANALYSIS ────────────────────────────")
    cost = report.get("cost_analysis", {})
    lines.append(f"  Cost ratio (under:over): {cost.get('cost_ratio_under_vs_over', 'N/A')}:1")
    lines.append(f"  Under-charge: {cost.get('total_undercharge_kwh', 0):.1f} kWh "
                  f"(${cost.get('total_undercharge_cost', 0):.2f})")
    lines.append(f"  Over-charge:  {cost.get('total_overcharge_kwh', 0):.1f} kWh "
                  f"(${cost.get('total_overcharge_cost', 0):.2f})")
    lines.append(f"  Daily avg error cost: ${cost.get('daily_avg_cost', 0):.3f}")
    lines.append(f"  Monthly estimate:     ${cost.get('monthly_estimated_cost', 0):.2f}")
    lines.append(f"  Floor breached: {cost.get('pct_days_floor_breached', 0):.1f}% of days")
    lines.append(f"  Over-conservative (>2kWh margin): "
                  f"{cost.get('pct_days_overconservative', 0):.1f}% of days")
    lines.append("")

    # Solar forecast
    lines.append("─── SOLAR FORECAST ACCURACY ─────────────────────────────")
    solar = report.get("solar_forecast", {}).get("daily", {})
    lines.append(f"  Mean error: {solar.get('mean_error_kwh', 'N/A')} kWh  "
                  f"(stdev: {solar.get('stdev_error_kwh', 'N/A')})")
    lines.append(f"  Mean ratio: {solar.get('mean_ratio', 'N/A')}  "
                  f"(P10={solar.get('p10_ratio', 'N/A')}, P90={solar.get('p90_ratio', 'N/A')})")
    lines.append(f"  Skewness:   {solar.get('skewness', 'N/A')}")
    lines.append(f"  Bias:       {solar.get('bias', 'N/A')}")

    worst = report.get("solar_forecast", {}).get("worst_hours", [])
    if worst:
        lines.append(f"  Worst hours: {', '.join(f'H{w['hour']}({w['avg_abs_error_kwh']}kWh)' for w in worst)}")
    lines.append("")

    # Base load
    lines.append("─── BASE LOAD STABILITY ─────────────────────────────────")
    bl = report.get("base_load", {})
    lines.append(f"  Mean: {bl.get('mean_kw', 'N/A')} kW  "
                  f"(σ={bl.get('stdev_kw', 'N/A')}, range={bl.get('min_kw', 'N/A')}-{bl.get('max_kw', 'N/A')})")
    lines.append(f"  CV: {bl.get('cv_pct', 'N/A')}%  "
                  f"Stable: {'✓' if bl.get('stable', True) else '✗'}")
    lines.append("")

    # Recommendations
    lines.append("─── RECOMMENDATIONS ─────────────────────────────────────")
    for i, rec in enumerate(report.get("recommendations", []), 1):
        lines.append(f"  {i}. {rec}")
    lines.append("")
    lines.append(divider)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Optional: matplotlib charts
# ---------------------------------------------------------------------------
def try_generate_charts(
    report: dict,
    records: list[DailyRecord],
    output_dir: Path,
) -> list[str]:
    """Generate PNG charts if matplotlib is available. Returns list of file paths."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime
    except ImportError:
        return []

    charts: list[str] = []
    dates = [datetime.strptime(r.date, "%Y-%m-%d") for r in records if r.date]

    # 1. Margin above floor control chart
    margins = [
        (datetime.strptime(r.date, "%Y-%m-%d"), r.margin_above_floor_kwh)
        for r in records
        if r.margin_above_floor_kwh is not None and r.date
    ]
    if margins:
        fig, ax = plt.subplots(figsize=(12, 5))
        chart_data = report["control_charts"]["margin_above_floor"]
        d, v = zip(*margins)
        ax.plot(d, v, "b.-", label="Margin (kWh)", linewidth=1)
        ax.axhline(chart_data["mean"], color="green", linestyle="-", label=f"Mean ({chart_data['mean']:.2f})")
        ax.axhline(chart_data["ucl"], color="red", linestyle="--", label=f"UCL ({chart_data['ucl']:.2f})")
        ax.axhline(chart_data["lcl"], color="red", linestyle="--", label=f"LCL ({chart_data['lcl']:.2f})")
        ax.axhline(0, color="black", linestyle=":", alpha=0.5, label="Floor")
        ax.set_title("Margin Above Floor — I-Chart (SPC)")
        ax.set_ylabel("kWh above floor")
        ax.legend(fontsize=8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        fig.autofmt_xdate()
        fig.tight_layout()
        path = output_dir / "control_chart_margin.png"
        fig.savefig(path, dpi=100)
        plt.close(fig)
        charts.append(str(path))

    # 2. Score over time
    scores = [
        (datetime.strptime(r.date, "%Y-%m-%d"), r.score)
        for r in records
        if r.score is not None and r.date
    ]
    if scores:
        fig, ax = plt.subplots(figsize=(12, 5))
        d, v = zip(*scores)
        ax.bar(d, v, color=["green" if s >= 80 else "orange" if s >= 60 else "red" for s in v], alpha=0.7)
        chart_data = report["control_charts"]["algorithm_score"]
        ax.axhline(chart_data["mean"], color="blue", linestyle="-", label=f"Mean ({chart_data['mean']:.1f})")
        ax.set_title("Algorithm Score Over Time")
        ax.set_ylabel("Score (0-100)")
        ax.set_ylim(0, 105)
        ax.legend()
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        fig.autofmt_xdate()
        fig.tight_layout()
        path = output_dir / "score_over_time.png"
        fig.savefig(path, dpi=100)
        plt.close(fig)
        charts.append(str(path))

    # 3. Cost breakdown
    cost = report.get("cost_analysis", {})
    if cost.get("total_undercharge_cost", 0) + cost.get("total_overcharge_cost", 0) > 0:
        fig, ax = plt.subplots(figsize=(8, 5))
        labels = ["Under-charge\n(peak draw)", "Over-charge\n(wasted charge)"]
        values = [cost["total_undercharge_cost"], cost["total_overcharge_cost"]]
        colors = ["#e74c3c", "#f39c12"]
        ax.bar(labels, values, color=colors)
        ax.set_title("Cumulative Cost of Errors")
        ax.set_ylabel("Cost ($)")
        for i, v in enumerate(values):
            ax.text(i, v + 0.01, f"${v:.2f}", ha="center", fontsize=10)
        fig.tight_layout()
        path = output_dir / "cost_breakdown.png"
        fig.savefig(path, dpi=100)
        plt.close(fig)
        charts.append(str(path))

    return charts


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Solarseed Peak Shaver — SPC Performance Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python analyze_performance.py daily.csv\n"
            "  python analyze_performance.py daily.csv --hourly hourly_solar.csv\n"
            "  python analyze_performance.py daily.csv --json\n"
            "  python analyze_performance.py daily.csv --charts output_dir/\n"
        ),
    )
    parser.add_argument("daily_csv", help="Path to daily scorecard CSV file")
    parser.add_argument("--hourly", help="Path to hourly solar CSV file", default=None)
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--charts", help="Directory to save PNG charts (requires matplotlib)", default=None)

    args = parser.parse_args()

    # Read daily data
    daily_text = Path(args.daily_csv).read_text(encoding="utf-8")
    records = parse_daily_csv(daily_text)
    if not records:
        print("ERROR: No records found in CSV file.", file=sys.stderr)
        sys.exit(1)

    # Read hourly data (optional)
    hourly = None
    if args.hourly:
        hourly_text = Path(args.hourly).read_text(encoding="utf-8")
        hourly = parse_hourly_solar_csv(hourly_text)

    # Generate report
    report = generate_report(records, hourly)

    # Generate charts (optional)
    if args.charts:
        chart_dir = Path(args.charts)
        chart_dir.mkdir(parents=True, exist_ok=True)
        chart_files = try_generate_charts(report, records, chart_dir)
        if chart_files:
            report["chart_files"] = chart_files

    # Output
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_text_report(report))


if __name__ == "__main__":
    main()
