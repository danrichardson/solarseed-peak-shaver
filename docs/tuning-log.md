# Tuning log

One dated entry per review session, newest last. Weekly totals only, no household
detail (this repo is public). Each entry says what we saw, what changed and in which
version, and, one week later, how the previous change did.

## How a review session works

The integration cannot tune itself beyond what the learned planner learns. Start a review
session when the `Health` sensor says `review` (it also sends a high-priority
notification once when it changes to review), and one week after any algorithm change.

1. Pull the data (diagnostics and the `export_history` CSV; raw history if needed) into
   `analysis/` (local only).
2. Build the weekly table: mid-peak and peak grid kWh and dollars per TOU day, prediction
   error, top-ups, handovers, frozen minutes. The `health` field of each scorecard has
   most of it; the diagnostics download has the rest.
3. Decide tweaks with the owner; implement on a branch with tests.
4. Add a dated entry below: what we saw (weekly totals only), what changed and in which
   version, and next week's result for the previous entry.
5. Rebuild the white paper only at milestones (a new algorithm version on the box, or
   revision 1.0), not weekly.

Success measure (from 2026-11-16): grid energy through the inverter in mid-peak and
peak, and what it costs. Load outside the inverter is by design and is not counted.

## 2026-11-22 - 0.8.1: health check thresholds (first set)

**Why.** The daily "Grade" scored the classic planner's own predictions (battery kWh
minimum, solar forecast accuracy, minus 25 for any mid-peak charge). With the learned
planner in control it grades a plan nobody follows, and the owner had stopped reading it.

**What changed.** From 0.8.1 each TOU weekday is graded from the meters (see
`docs/how-it-works.md`, "0.8.1 additions"). The first thresholds, all constants in
`health.py`:

- Good: under 0.2 kWh grid in peak, no handover, under 0.5 kWh grid in mid-peak, no frozen
  stretch over 30 min, every command followed, gauge at peak end within 10 points of
  the prediction.
- Fair: peak covered but a mid-peak top-up of 0.5 kWh or more, a handover, a frozen
  stretch of 31-60 min, or the peak-end gauge off by more than 10 points.
- Poor: over 0.2 kWh grid in peak, a frozen stretch over 60 min, or a command ignored.
- Review when any of the last 7 TOU days was Poor, or the last 3 were all not Good, or
  the peak-end prediction was off the same way by more than 8 points on average (5 or
  more days with a prediction). Watch when there is a Fair day and no reason to review.

**What we saw.** Nothing yet: 0.8.1 is not installed. Baseline for comparison, from the
validation plan in `docs/HANDOFF.md`: the six weekdays before the low-end test
(2026-11-04 to 11-13) averaged 1.8 kWh mid-peak and 0.6 kWh peak of battery charging per
day on the classic planner; a Monday on a full bank (2026-11-16) had none. The week of
2026-11-23 is a poor before/after week (the household's weekday schedule changes and
Thursday 11-26 is a PGE holiday the integration does not know yet, ROADMAP item 7);
leave 11-26 out and judge it by the per-day targets and `replay_cost.py`.

**Next review.** One week after 0.8.1 is installed. Check first whether the thresholds
sort the days the way a human would (a Good day should not need a second look), and
whether the 7-day window and the bias limit of 8 points are too tight or too loose.

## 2026-11-22 - box: availability template on the Available Battery kWh helper

**Why.** At the 0.8.0 restart the AC500 gauge went unknown for about 3 s and
`sensor.available_battery_kwh` showed 0.0 for that window (a template defaulting to 0), so
the classic planner read an empty battery and briefly started a charge (see 0.8.1 in
`docs/how-it-works.md`). The code now guards against it (a missing reading is skipped, and
the first calculation after a start waits 60 s before it may start a charge), but the
sensor should not report 0 for "I do not know" in the first place.

**What changed (box, not code; approved by the owner).** The Available Battery kWh
template helper now has the availability template
`{{ is_number(states('sensor.ac500_total_battery_percent')) }}`, so an unknown gauge makes
it unavailable instead of 0. Applies from 2026-11-22, independent of the integration
version. Rollback: the helper as it was is saved as
`analysis/data/live_changes/template_available_battery_kwh_before_2026-11-22.json` (local
only, on the original workstation).

**What to watch.** After the next HA restart or gauge dropout the helper should go
unavailable, not 0.0, and the integration should log one "Classic calculation skipped"
warning (0.8.1 and later) instead of firing an event. The learned planner reads the
gauge directly and is not affected. Anything else that reads this helper (dashboards,
automations) will now see "unavailable" in those moments rather than 0; check the
recorder for gaps instead of zeros when the next review pulls the data.
