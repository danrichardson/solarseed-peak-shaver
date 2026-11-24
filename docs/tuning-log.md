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

## 2026-11-23 - 0.8.1: the frozen-data check ignores an idle system

**What we saw.** The first Monday check on the learned planner (07:10) showed
`battery_data_stale` true and `stale_minutes` 261 for the day on a healthy, full bank. The
minute log from 22:22 to 07:10 has seven stretches of 36 to 173 min (longest 02:56 to 05:49)
where the gauge and the AC input, AC output and DC input power all read the same value (the
gauge 98 to 100, power 0 W) while pack and cell voltages kept changing. The same 0 W
continued after 07:00, in mid-peak, so a rule limited to the mid-peak and peak windows would
not have fixed it. Under the 0.8.1 grading each of those stretches was over 60 min, so an
ordinary full-bank night would have graded Poor and sent a review notice.

**What changed (0.8.1, not installed).** A system whose configured power sensors all read
10 W or less is idle, and the unchanged-timer restarts while it is. A feed stuck on a
non-zero value is still caught after 20 min. The "battery data frozen" notification now says
"while power was flowing". Constant `IDLE_POWER_KW` in `learned_runtime.py`. The thresholds
in the 2026-11-22 entry are unchanged.

**Cost on the box until 0.8.1 is installed.** The 0.8.0 check keeps flagging idle stretches:
expect the "battery data frozen" / "battery data back" notifications and a stale flag in
the daily scorecard. In the full-charge months a stale night only means charging a bank
that is already full; outside them it would charge unnecessarily.

**Next review.** After the first week on 0.8.1, check `stale_minutes` and
`stale_longest_min` in the scorecards: they should be near zero on ordinary days. A real
freeze while idle is invisible by design; if one shows up in the raw history, revisit.

## 2026-11-23 - idle baseline: battery drain with almost nothing on the inverter (not a clean one)

**What we saw.** For about 26 hours from the morning of 2026-11-22 almost nothing was
fed by the inverter: AC output read 5 W or less in all but 35 of 1,484 minutes (maximum
76 W), against 500 to 700 W on every hour of the weeks before. The owner confirms one small
circuit was still on the inverter with next to no load. The gauge still fell about 1% every
46 to 56 minutes between 99% and 92% (six steps in the minute log, with AC input, DC input
and AC output all under 10 W). At the configured 23.5 kWh per 100% that is 0.25 to
0.3 kW, or 6 to 7 kWh a day. The 100% to 99% step is slower (173 min once) and was left out.

**Why it is not a clean baseline.**
- One night and one day. The gauge moves in whole percent, and 23.5 kWh per 100% is the
  configured capacity, not a measured one, so allow roughly 15% either way.
- A resistive load of about 150 W (the owner's estimate, to be corrected) ran all day on
  the main panel, not on the AC500, which the AC output sensor agrees with. It does not
  explain the drain. What does is open: the system's own overhead, or the capacity figure.
  The pack current in the `bluetti` bucket would settle it, as would a second run with the
  load confirmed.

**Whole-house baseline (to do).** The same days also give an idle baseline for the whole
house on the Emporia Vue mains sensor (see `docs/analysis-plan.md`), after taking out the
150 W load above (24 h of it is 3.6 kWh a day; use the owner's corrected figure when there
is one). It needs the mains sensor's history for the same window, which has not been
pulled: the local hourly statistics end on 11-19. Add the figure here once it is.

**Data note.** The load profile for 2026-11-22 and 2026-11-23 is idle-day data. Both days
went into the learned 14-day history (about 7% off the weekday mean until they age out,
and only felt outside the full-charge months). Leave both out of load-profile analysis and
the first review; their scorecards are not comparable with the other days. No code change
was made for this.
