"""Daily health check of the system as it actually ran (0.8.1).

The old daily "Grade" scored the classic planner's own predictions. Under the learned
planner that grades a plan nobody follows. This module grades the day from what the
meters saw: grid energy through the inverter per price window, whether the battery
reached the end of peak as predicted, handovers, frozen data and unanswered commands.

Pure functions, no Home Assistant imports. The thresholds below are the first,
deterministic ones agreed on 2026-11-22. Tune them in a review session and record the
change in docs/tuning-log.md. Where a reading sits exactly on a boundary the worse
grade wins (exactly 0.20 kWh in peak is Fair, exactly 0.50 kWh in mid-peak is Fair).
"""
from __future__ import annotations

from typing import Any

GOOD = "good"
FAIR = "fair"
POOR = "poor"

HEALTH_GOOD = "good"
HEALTH_WATCH = "watch"
HEALTH_REVIEW = "review"

# --- Day grade ---------------------------------------------------------------------------
PEAK_GRID_KWH = 0.2            # grid kWh in peak: under is Good, over is Poor
MIDPEAK_GRID_KWH = 0.5         # grid kWh in mid-peak: under is Good, at or over is Fair
FROZEN_FAIR_MIN = 30           # longest frozen stretch: over is not Good
FROZEN_POOR_MIN = 60           # longest frozen stretch: over is Poor
PEAK_END_ERROR_PTS = 10.0      # predicted vs actual gauge at peak end: over is not Good

# --- Health over the recent days ---------------------------------------------------------
WINDOW_DAYS = 7                # TOU days looked at
REVIEW_NOT_GOOD_RUN = 3        # this many non-Good days in a row call for a review
REVIEW_BIAS_PTS = 8.0          # mean signed peak-end error, over the window, calls for a review
MIN_BIAS_DAYS = 5              # days with a prediction needed before the bias counts

# PGE Time of Day prices, USD per kWh. Constants for now; ROADMAP item 8 makes them data.
PRICE_MIDPEAK = 0.1670
PRICE_PEAK = 0.4313


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _opt(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def grade_day(learned: dict[str, Any] | None, date: str) -> dict[str, Any] | None:
    """Grade one TOU day from the learned runtime's daily summary.

    Returns the `health` record for the scorecard, or None when there is nothing to
    grade (no grid readings all day and no frozen data either).
    """
    summary = learned or {}
    grid = summary.get("grid_kwh") or {}
    frozen = _num(summary.get("stale_longest_min", summary.get("stale_minutes")))
    if not grid and frozen <= FROZEN_POOR_MIN:
        return None

    midpeak = _num(grid.get("mid-peak"))
    peak = _num(grid.get("peak"))
    unanswered = int(_num(summary.get("commands_not_followed")))
    handover = summary.get("handover_at") or None
    actual = _opt(summary.get("gauge_peak_end"))
    predicted = _opt(summary.get("pred_gauge_peak_end"))
    error = round(predicted - actual, 1) if actual is not None and predicted is not None else None

    poor: list[str] = []
    fair: list[str] = []
    peak_covered = peak < PEAK_GRID_KWH
    if peak > PEAK_GRID_KWH:
        poor.append("peak bought %.1f kWh" % peak)
    elif peak >= PEAK_GRID_KWH:
        fair.append("peak bought %.1f kWh" % peak)
    if frozen > FROZEN_POOR_MIN:
        poor.append("data frozen %d min" % round(frozen))
    elif frozen > FROZEN_FAIR_MIN:
        fair.append("data frozen %d min" % round(frozen))
    if unanswered > 0:
        poor.append("inverter ignored a command")
    if handover:
        fair.append("handover at %s" % handover)
    if midpeak >= MIDPEAK_GRID_KWH:
        fair.append("mid-peak grid %.1f kWh" % midpeak)
    if error is not None and abs(error) > PEAK_END_ERROR_PTS:
        fair.append("peak-end gauge off by %d points" % round(abs(error)))

    # Events after an earlier day's scoring (21:10 to midnight), carried here so they land
    # in a graded day. Graded like today's, named with their date (0.9.0).
    late = [e for e in (summary.get("late_events") or []) if isinstance(e, dict)]
    late_record: list[dict[str, Any]] = []
    for event in late:
        when = "late on %s" % str(event.get("date", "?"))[5:]
        ignored = int(_num(event.get("commands_not_followed")))
        stale = _num(event.get("stale_longest_min"))
        if ignored > 0:
            poor.append("inverter ignored a command %s" % when)
        if stale > FROZEN_POOR_MIN:
            poor.append("data frozen %d min %s" % (round(stale), when))
        elif stale > FROZEN_FAIR_MIN:
            fair.append("data frozen %d min %s" % (round(stale), when))
        late_record.append({"date": event.get("date"), "after": event.get("after"),
                            "commands_not_followed": ignored, "frozen_longest_min": round(stale, 1)})

    grade = POOR if poor else FAIR if fair else GOOD
    # The peak line is carried by peak_covered and grid_peak_kwh; reasons are the rest.
    reasons = [r for r in poor + fair if not r.startswith("peak bought")]
    record = {
        "date": date,
        "grade": grade,
        "reasons": reasons,
        "peak_covered": peak_covered,
        "grid_midpeak_kwh": round(midpeak, 2),
        "grid_peak_kwh": round(peak, 2),
        "cost_usd": round(midpeak * PRICE_MIDPEAK + peak * PRICE_PEAK, 2),
        "gauge_peak_end": actual,
        "pred_gauge_peak_end": predicted,
        "peak_end_error_pts": error,
        "handover_at": handover,
        "frozen_longest_min": round(frozen, 1),
        "commands_not_followed": unanswered,
    }
    if late_record:
        record["late_events"] = late_record
    return record


def status(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Health over the last WINDOW_DAYS graded days: good, watch or review.

    `records` are `health` records, oldest first. Review when any day was Poor, the
    last REVIEW_NOT_GOOD_RUN days were all not Good, or the peak-end prediction has
    been off the same way by more than REVIEW_BIAS_PTS on average. Watch when there is
    a Fair day but no reason to review. State is None until a day has been graded.
    """
    recent = [r for r in records if r.get("grade")][-WINDOW_DAYS:]
    counts = {GOOD: 0, FAIR: 0, POOR: 0}
    for r in recent:
        counts[r["grade"]] = counts.get(r["grade"], 0) + 1
    errors = [r["peak_end_error_pts"] for r in recent if r.get("peak_end_error_pts") is not None]
    bias = round(sum(errors) / len(errors), 1) if errors else None

    run = 0
    for r in reversed(recent):
        if r["grade"] == GOOD:
            break
        run += 1

    why: list[str] = []
    if counts[POOR]:
        why.append("%d Poor day%s in the last %d" % (counts[POOR], "" if counts[POOR] == 1 else "s", len(recent)))
    if run >= REVIEW_NOT_GOOD_RUN:
        why.append("%d days in a row were not Good" % run)
    if bias is not None and len(errors) >= MIN_BIAS_DAYS and abs(bias) > REVIEW_BIAS_PTS:
        why.append("peak-end gauge predicted %.0f points too %s on average" % (abs(bias), "high" if bias > 0 else "low"))

    if not recent:
        state = None
    elif why:
        state = HEALTH_REVIEW
    elif counts[FAIR]:
        state = HEALTH_WATCH
    else:
        state = HEALTH_GOOD
    return {"state": state, "days": len(recent), "counts": counts, "bias_pts": bias, "review_reasons": why}


def daily_message(day: dict[str, Any], summary: dict[str, Any], day_word: str = "weekday") -> tuple[str, str]:
    """The daily notification: a title and one or two lines, ASCII only."""
    grade = str(day.get("grade", "?"))
    pieces = ["peak on battery" if day.get("peak_covered") else "peak bought %.1f kWh" % _num(day.get("grid_peak_kwh"))]
    pieces += list(day.get("reasons") or [])
    actual, predicted = day.get("gauge_peak_end"), day.get("pred_gauge_peak_end")
    if actual is not None:
        ended = "ended at %d %%" % round(actual)
        if predicted is not None:
            ended += " (predicted %d %%)" % round(predicted)
        pieces.append(ended)
    pieces.append("$%.2f at mid-peak and peak prices" % _num(day.get("cost_usd")))
    lines = [", ".join(pieces) + "."]

    n = int(summary.get("days") or 0)
    counts = summary.get("counts") or {}
    parts = ["%d %s" % (counts[g], g) for g in (GOOD, FAIR, POOR) if counts.get(g)]
    if n and parts:
        lines.append("Last %d %s%s: %s." % (n, day_word, "" if n == 1 else "s", ", ".join(parts)))
    return "Solarseed Daily Report - %s" % grade.capitalize(), "\n".join(lines)


def review_message(summary: dict[str, Any]) -> tuple[str, str]:
    """The notification sent once, when health changes to review."""
    why = "; ".join(summary.get("review_reasons") or ["see the Health sensor"])
    return "Solarseed - review needed", "%s. Time for a review session." % why
