# Handoff - winter 2026 analysis and rework

## RESUME HERE - Monday 2026-11-23 night: 0.8.1 is released and running; what is left

**State (checked read-only on the evening of 11-23).**
- **Released.** `v0.8.1` is commit `c351c84` on `main`. It was merged, tagged and published as a
  pre-release with empty notes outside the session that built it; that session then wrote the
  release notes and made it the Latest release. CI is green. Later commits on `main` are docs
  only (tuning log, this handoff). The remote branch `release-0.8.1` and the worktree
  `../solarseed-peak-shaver-0.8.1` are merged and can be deleted.
- **Installed.** HACS shows installed and latest both `v0.8.1`; HA was restarted; the config
  entry is `loaded`. The restart changed nothing on the inverter: the AC500 mode read `unknown`
  for 4 s and went straight back, and no event fired. The log shows the new skip working at
  startup (`Classic calculation skipped: solar forecast entity ... has no data`); on 0.8.0 that
  moment was a failed setup attempt.
- **Live.** Planner `learned`, in control; `sensor.solarseed_peak_shaver_health` exists;
  `battery_data_stale` false; the night hold is in place. The 21:00 switch to `learned` ran on
  Sunday 11-22 and all three timers (switch, Monday check, minute logger) have finished, so
  nothing is watching the box automatically.
- **Access.** Ask the owner for a fresh temporary HA admin before pulling anything
  (`analysis/scripts/ha.py login`, token cached in the gitignored `analysis/.ha_token.json`,
  delete it when done; never write the password anywhere). Read-only unless approved.
- Untracked and not ours, leave alone: `docs/ac500-ui-screens.zip`, `docs/whitepaper/`.

**Data caveat.** Most circuits were not on the inverter from the morning of 11-22 to the
evening of 11-23, so AC output was about 0 W (`docs/tuning-log.md`, 2026-11-23). Both days went
into the learner's 14-day load history (a small effect, and only outside the full-charge
months), their scorecards are not comparable, and the Health sensor's one graded day (11-23,
`good`, 0 kWh from the grid) means nothing. Leave 11-22 and 11-23 out of the first review.

**What is left to develop** (roughly by value; `docs/ROADMAP.md` has the rest):
1. **0.8.2 candidate: a false "hold not followed" after a full charge.** On the evening of 11-23
   the charge ended at 100 %, the planner sent hold (`TIME_CONTROL`), and for about 30 min the
   inverter carried the house from the battery (AC in 0 W, AC out 540-680 W) until the gauge fell
   to 99 %, then passed the grid through (AC in about equal to AC out). `mode_matches(MODE_HOLD)`
   wants grid between half the load and load + 0.3 kW, so it said "not in hold", resent the
   command three times and logged `Inverter did not follow the hold command after 3 attempts`
   (an ERROR, a notification, and a `commands_not_followed` that grades a day Poor). Proposed
   fix: return None (cannot tell) for `MODE_HOLD` while the gauge is at 100 / `bank_full`, as
   `MODE_CHARGE` already does near the top; add a test with those readings. Related: the daily
   scoring runs at 21:10 and the summary resets at the day roll, so events between 21:10 and
   midnight are in no graded day (this one included); consider scoring the next morning or
   carrying them over.
2. **PGE holidays (ROADMAP 7).** First live case: Thursday 2026-11-26 (Thanksgiving). Until it is
   built a holiday is planned, run on battery through "mid-peak" and "peak", and scored like a
   weekday. No harm, but a wasted cycle and a polluted weekday profile.
3. **The first review session**, about a week after install (from 11-30), following "How a
   review session works" in `docs/tuning-log.md`. Leave out 11-22, 11-23 and 11-26. First check
   that the health thresholds sort days the way a human would.
4. **Tariff as data** (ROADMAP 8; before any public release), the **dashboard** (ROADMAP 6),
   and the later items 9 to 11.
5. **Open analysis questions.** The AC500 loses 0.25 to 0.3 kW with almost nothing on it (6 to
   7 kWh a day): overhead, or is 23.5 kWh per 100 % too high? Pack current from the `bluetti`
   bucket on the metrics container would settle it. The whole-house idle baseline is in the
   tuning log. A feed that freezes while the system is idle is invisible by design. A
   load-profile guard that ignores hours under about 20 W was proposed and not wanted.
6. **White paper 0.95** (separate session).

**Rules of the road** (unchanged). `python -m pytest -q` before every commit (402 tests); a
version bump touches both `const.py` and `manifest.json`; a deploy is push `main`, tag, release,
the owner clicks install in HACS, restart HA, the agent verifies; nothing on the live box beyond
read-only without approval each time; this repo is public (no household detail, credentials,
IPs, or exact times of the owner's own actions).

## 0.8.1 build notes (Sunday evening to Monday morning)

What 0.8.1 does: `docs/how-it-works.md`, "0.8.1 additions". The first threshold set and the
review routine: `docs/tuning-log.md`.

**Box change, 2026-11-22 (approved by Dan).** The Available Battery kWh template helper
(`sensor.available_battery_kwh`) now has the availability template
`{{ is_number(states('sensor.ac500_total_battery_percent')) }}`, so an unknown gauge makes
it unavailable instead of 0. Rollback copy of the helper as it was:
`analysis/data/live_changes/template_available_battery_kwh_before_2026-11-22.json` (on the
original workstation, not on the timer machine). Also in `docs/tuning-log.md`.

**Step 3a, as it turned out.** At the 0.8.0 restart the AC500 gauge went unknown for
about 3 s and `sensor.available_battery_kwh` showed a numeric `0.0` for that window (the
recorder has it at `0.0` from 21:19:22.9 to 21:19:24.8 UTC, then 23.27), probably a
template defaulting to 0. So treating unavailable/unknown as missing would not have
stopped it, and 0.8.1 also makes the first calculation after a start that wants a charge
wait 60 s and look again before it may start one. The `charge_stop` 1.8 s later was
almost certainly the battery listener's "target reached" check (`_on_battery_update`,
23.27 >= 4.1 + 0.1), not a recalculation; confirmed from the code and timing, not from
the HA log (not reachable through `ha.py` today). Weekend start: confirmed, the setup
refresh had no weekday check.

**Monday check, 07:10, and the idle fix (0.8.1).** The learned planner is in control and the
AC500 went to PV_PRIORITY at 07:00 on a full bank. The check also printed
`battery_data_stale` true with `stale_minutes` 261 for the day. Cause: the staleness check
calls the feed frozen when the gauge and the load, grid and PV sensors all sit exactly
still for 20 min. On a full bank they do: the minute log has seven such stretches of 36 to
173 min between 22:22 and 07:10 (gauge 98 to 100, every power sensor 0 W, pack and cell
voltages still moving, so the feed was alive), and the 0 W continued in mid-peak after
07:00. A fix limited to the mid-peak and peak windows, which I first proposed, would not
have worked. Fixed instead: a system whose power sensors all read 10 W or less is idle,
and the unchanged-timer restarts; a feed stuck on a non-zero value is still caught. A feed
that freezes while idle is not (nothing is moving; SOC Low is the backstop). Without the
fix an ordinary night graded Poor and would have sent a review notice. On the 0.8.0 box
the false flag keeps happening until 0.8.1 is installed (alerts, stale flag in the daily
scorecard); see `docs/tuning-log.md`, 2026-11-23. It only matters outside the
full-charge months, when a stale night charges.

**Setup no longer fails on a missing battery (changed before release).** The first draft
raised `UpdateFailed` for an unavailable battery sensor. That fails the first refresh, so
HA retries the setup and the learned planner, which is in control and does not use that
sensor, would not start until the sensor had a number. Now the classic calculation is
skipped, nothing fires, setup succeeds, and a returning reading triggers a recalculation.
The same goes for a missing or empty solar forecast (decided in the same change; revert
that part if a hard failure is preferred when Solcast is misconfigured). A test runs the
real `async_setup_entry` with the battery unavailable and checks the learned runtime
starts and still asks for the night charge.


## Earlier, Sunday 2026-11-22 afternoon: 0.8.0 installed, timers to restart (done)

**State.** v0.8.0 is released (tag `v0.8.0`, GitHub release) and Dan installed it through
HACS on Sunday afternoon, then restarted HA. Not yet verified by an agent. The planner
option is still `classic`; the switch to `learned` runs at 21:00 Sunday (approved).
What 0.8.0 adds: `docs/how-it-works.md`, "0.8.0 additions". The previous session's
background timers died when its VS Code window closed.

**Step 1 - restart the timers** (each with Bash `run_in_background`, from the repo root).
First check none is still running: `ps -ef | grep -E "sunday_switch|monday_check|lowend_monitor"`.

1. `bash analysis/scripts/sunday_switch.sh` - waits for 21:00, notifies, switches the
   planner to `learned`, deletes the weekend test automation, notifies the result.
   Restartable (markers in `analysis/data/live_changes/.sunday_switch_done/`); does
   nothing after Mon 06:00. If that window passed without the `planner` marker, the
   planner is still classic: notify Dan and ask (fallback: PV_PRIORITY at Mon 07:00).
2. `cd analysis && python scripts/monday_check.py` - waits until Mon 07:10, then prints
   the planner, the learned decision, the AC500 mode/gauge history since Sunday and any
   solarseed log lines (read-only). Read the output: the planner must be `learned` and in
   control, the AC500 should have charged overnight and held until 07:00. Notify Dan
   (`--event=needs-input`) if not; otherwise one short `task-complete` summary.
3. `lowend_monitor.py` was started from a console on 11-20 and may have survived. If it
   is not running and it is before Mon 08:00: check `analysis/data/` for fresh minute-log
   rows, then `cd analysis && python scripts/lowend_monitor.py 2026-11-23T08:00`.

**Step 2 - verify 0.8.0 on the box** (read-only, before 21:00):
- `update.solarseed_peak_shaver_update` reports `installed_version` v0.8.0.
- Diagnostics (`analysis/scripts/ha.py rest /api/diagnostics/config_entry/<entry>`):
  `learned.battery_data_stale` false, `seconds_since_last_change` small, no
  `solarseed` errors in `system_log/list`.
- `cd analysis && python scripts/switch_planner.py learned --dry-run` must print
  "new option saved at its default" for the eight 0.8.0 options and "other differences:
  none". (`switch_planner.py` was updated for 0.8.0 today: its new options are absent
  from the saved options until the form is submitted once. If the dry run reports
  differences, fix it before 21:00 or the switch fails and notifies.)

Step 2 was done on Sunday right after the restart: v0.8.0 installed, data not stale,
dry run clean (all eight new options at their defaults, no other differences). It also
found the bug in step 3a.

**Step 3a - fix first in 0.8.1: false charge at startup.** At the 0.8.0 restart the
classic planner's first calculation ran before `sensor.available_battery_kwh` had
loaded, read the battery as 0.0 kWh, logged "[CHARGE 4.1 kWh] Battery: 0.0 kWh" and,
because 0.8.0's restart rule lets a first calculation start a charge, fired
`charge_start`. The AC500 went to grid charge; about 2 s later the battery sensor loaded,
a recalculation fired `charge_stop`, and the mode was back to PV_PRIORITY within 5 s.
Harmless on a Sunday; on a weekday it flips the inverter twice, and if the battery sensor
stayed unavailable it could charge at mid-peak price. It also ran on a Sunday although
`weekdays_only` is on (the startup refresh seems to skip the weekday check; confirm).
Fix: an unavailable or unknown battery reading is missing, not 0 - no calculation and no
event (log once); and the restart rule only allows a charge on a real reading. Add a test
for each, plus one for the weekend check at startup. Evidence: HA logbook and system log
for 2026-11-22 21:19 UTC.

**Step 3b - this week, a fresh session: 0.8.1 health check and daily message.** Dan
installs it on an evening after 21:00 when ready (after 3a, a weekday restart is safe).
Spec agreed with Dan on 2026-11-22:
- Why: the daily "Grade" notification scores the classic planner's own predictions
  (battery kWh minimum, solar forecast accuracy, minus 25 for any mid-peak charge), so
  under the learned planner it grades a plan nobody follows and Dan ignores it.
- Grade each TOU weekday from the learned runtime's daily summary (grid kWh per price
  window, predicted vs actual gauge at peak start/end, `handover_at`, `stale_minutes`,
  inverter command verification). Deterministic first thresholds, as constants:
  - Good: under 0.2 kWh grid in peak, no handover before 21:00, under 0.5 kWh grid
    charging in mid-peak, data never frozen over 30 min, every command followed.
  - Fair: peak covered, but a mid-peak top-up over 0.5 kWh or the predicted gauge at peak
    end off by more than 10 points.
  - Poor: over 0.2 kWh grid in peak, data frozen over 60 min, or a command not followed.
  - Not graded: weekends (and holidays once roadmap item 7 exists).
- Review needed when: any Poor day in the last 7 TOU days, or 3 non-Good in a row, or
  the peak-end prediction biased the same way by more than 8 points on average over 7
  TOU days.
- Daily notification replaces the grade, one or two lines, ASCII only (the current title
  has a non-ASCII dash), no message on non-TOU days. Example: "Good - peak on battery,
  ended at 12 % (predicted 9 %), $0.00 at peak prices. Last 7 weekdays: 6 good, 1 fair."
  Dollars at PGE Time of Day prices (constants for now: 8.93 / 16.70 / 43.13 cents).
- A `Solarseed Health` sensor (good / watch / review) with the last 7 days as attributes,
  and a separate, higher-priority notification only when it changes to review.
- Store: add a new `health` field to the scorecard; keep the old grade fields (readers use
  `.get`, no schema bump). Tests with `python -m pytest -q`; branch in a worktree; Dan
  approves push and release.
- Then add the review-session section below to the tuning log's first entry.

**Also open.**
- White paper revision 0.95 (section 11 now has real data): separate session, hand over
  `docs/whitepaper-brief.md` as written. Revision 1.0 waits for 2-3 weeks with the
  learned planner in control; section 9 should describe 0.8.0.
- The week of 11-23 is a poor before/after week: the household's weekday schedule
  changes from 11-23, and Thu 11-26 is a PGE holiday (off-peak all day) that the
  integration does not know about yet (roadmap item 7). Evaluate with `replay_cost.py`,
  prediction error and the per-day targets; leave 11-26 out.

### Standing: review sessions (from 2026-11-22)

The integration cannot tune itself beyond what the learned planner learns, so Dan
starts a review session when the Health sensor says "review" (after 0.8.1), and one week
after any algorithm change. In a review session:
1. Pull the data (diagnostics and `export_history` CSV; raw history if needed) into
   `analysis/` (local only).
2. Build the weekly table from the validation plan below: mid-peak and peak grid kWh and
   dollars per TOU day, prediction error, top-ups, handovers, frozen minutes.
3. Decide tweaks with Dan; implement on a branch with tests.
4. Add a dated entry to `docs/tuning-log.md` (create it on first use): what we saw (weekly
   totals only), what changed and in which version, and next week's result for the
   previous entry. Weekly totals only; no household detail.
5. Rebuild the white paper only at milestones (a new algorithm version on the box, or
   revision 1.0), not weekly.

## Earlier: low-end test weekend (written Fri 2026-11-20, early morning)

**Sunday 2026-11-22 update.** The test is over; results are in the weekend checklist and
the white paper brief (section 11). The handover stayed at gauge 3 % with the reserve at
1 %. Scheduled on the workstation for 21:00 Sunday (Dan approved):
`analysis/scripts/sunday_switch.sh` switches the planner to `learned` (via
`analysis/scripts/switch_planner.py`, which changes nothing else) and deletes the
temporary automation, with notifies. If the workstation was off at 21:00, run it by hand
before Monday 06:00, or fall back to PV_PRIORITY at Monday 07:00. Still open for Dan:
reserve 1 or 2. Feature ideas from all this: `docs/ROADMAP.md`. A private brief for an
outage and generator analysis is in `analysis/outage/BRIEF.md` (local only).

Friday night update: both workstation jobs were started. Check for an existing
logger and fresh CSV rows before restarting. The 20:00 snapshot and 21:00 heads-up
were missed. HA switched to STANDARD at 21:10 and the late check confirmed charging.

**1. Revive the timers on this workstation** (they die with a reboot or a closed session).
Run each as a background job (Bash `run_in_background`), from the repo root:

```bash
bash analysis/scripts/weekend_jobs.sh
```

It is restartable: each step runs once (markers in `analysis/data/live_changes/.weekend_jobs_done/`)
and is skipped if its window has passed. Steps: Fri 20:00 rollback snapshot (states +
integration diagnostics into `analysis/data/live_changes/*_before_weekend_2026-11-20.json`),
Fri 21:00 heads-up notify, Fri 21:20 check notify, Sat 07:15 "plug the heater in, leave it
off" notify. Then, from Fri 21:10 at the latest (any time after the snapshot is fine):

```bash
cd analysis && python scripts/lowend_monitor.py 2026-11-23T08:00
```

Read-only; one CSV row a minute to `analysis/data/raw/lowend_2026-11-21.csv` (appends, so a
restart is safe; it re-sends milestone notifies it already sent). Check access first with
`MSYS_NO_PATHCONV=1 python analysis/scripts/ha.py rest /api/states/select.ac500_ups_mode`.
The token (with refresh token) is cached in `analysis/.ha_token.json`; if it fails, ask Dan
for the temporary HA login and run `ha.py login USER PASSWORD` (never store credentials).

**2. What does NOT depend on this workstation.** The safety and charge actions live on the
box in the temporary automation `temp_claude_lowend_test_20261120` (entity
`automation.temp_claude_low_end_test_weekend_2026_11_20`, v2 installed Thu night with
Dan's OK; source `analysis/data/live_changes/lowend_automation_2026-11-20.yaml`, v1 backup
`lowend_automation_v1_as_installed.json`). It is date-guarded (Fri 21:00 to Mon 08:00) and
does: Fri 21:10 STANDARD (full charge); keeps STANDARD until Sat 07:00; "bank full" notify
Sat morning; handover (PV_PRIORITY, gauge <= 5, AC in > 300 W for 2 min) -> STANDARD;
lowest Vatrer <= 47.5 V with no grid -> STANDARD + critical notify; stale data notify.

**3. State of the box at handoff (verified Thu 23:30):** integration v0.7.2 (a restart
no longer changes the mode; scoring survives a mid-day restart), planner `classic`, mode
TIME_CONTROL (normal evening hold), SOC Low (`number.ac500_battery_range_start`) 2, grid
charge on, Time Control on, 20 automations (19 normal: 18 on, `power_alerts` off as
always, plus the temporary one).

**4. The weekend, step by step** - the checklist is `docs/weekend-test-2026-11-20.md`;
tick it as you go. Every box change gets a notify first (`~/src/notify.sh
--event=lowend-test`), and the Saturday changes need Dan's OK at the time. Ready payloads in
`analysis/data/live_changes/`, posted with
`MSYS_NO_PATHCONV=1 python analysis/scripts/ha.py post /api/services/<domain>/<service> <file>`:

| When | Action | Service | Payload |
|---|---|---|---|
| Sat, after charge completion and the start chat | Dan sets SOC Low 2 -> 1; verify readback | - | - |
| same | run on battery | `select/select_option` | `act_mode_pv_priority.json` |
| then | tell Dan to switch the heater on; sag checks per checklist | - | - |
| abort, any time | safe state | `select/select_option` | `act_mode_standard.json` |
| Sunday, if Dan decides | SOC Low back to 2 | `number/set_value` | `act_soc_low_2.json` |

At the start chat confirm B300 100% and fresh Vatrer currents near zero. The full
alert can miss completion. Agree which B300 phone alert tells Dan to transfer the
critical circuits to utility (20% proposed, 10% also available). Start with the
critical circuits plus the heater. Dan confirms the transfer and leaves just the
heater on the AC500, with grid input still connected. At the 3% alert Dan returns
to chat to watch B300 pack voltage, the four Vatrer voltages and AC power. Discuss
the readings near 1%. The reserve for this run is 1%. Record the load change and
look for sustained voltage decline under steady load. Early release from grid
after a voltage-based mode change is an open question.

Sunday: first numbers to Dan; Dan decides SOC Low (1 or 2) and the planner (`learned`
about 20:00, or fallback PV_PRIORITY Monday 07:00); delete the temporary automation
(`DELETE /api/config/automation/config/temp_claude_lowend_test_20261120`, after a notify);
confirm the box is back to normal. Monday onward: write-up (findings, methodology,
voltage-floor proposal).

**5. Facts learned this week - do not re-derive** (details in `docs/winter-2026-findings.md`
sections 10 and 11):

- When the AC500 goes to grid (gauge hits SOC Low + 1, i.e. 3 % today) it stays on grid
  until the battery is back to its recovery level, 10 %, and grid-charges it there at
  about 2.2 kW (Dan: anti-oscillation; cannot be avoided). So at Saturday's handover the
  gauge bounces to about 10 %; the handover signal is grid input while in PV_PRIORITY.
- Running out in peak costs the shortfall plus about 0.6 kWh bought at peak price.
- Do not touch the AC500 Time Control "Period 1: Charge 00:00-00:01" (deliberate, open
  question). Deep Discharge stays OFF. Never set SOC Low to 0.
- HACS refuses installs from the agent login; Dan clicks install, the agent verifies.
- Shadow days so far: Tue classic right; Wed classic bought 4 kWh mid-peak; Thu classic
  ran out at 19:47 in peak. The learned planner called the shortfall each time.
- The data path (MQTT/BLE) has frozen for hours several times (findings section 11):
  frozen values look healthy. The inverter's own SOC Low is the backstop.

**6. Repo and git.** Four local doc commits (including this section) are not pushed (`git log origin/main..main`);
push only when Dan says. Stage files by name: `git add docs` once picked up Dan's untracked
`docs/ac500-ui-screens.zip` and `docs/whitepaper/` (removed before pushing; they stay
untracked on disk). Public repo: no exact times of Dan's own actions, no IPs or names.
Analysis data and scripts in `analysis/` are gitignored and stay local.

**7. Open questions after the weekend:** Period 1's purpose; whether SOC Low 1 bypasses
cleanly; voltage floor, staleness check and energy-since-full design; first-calculation
rule refinement (allow a charge start, never release a hold); planner treating the
handover as a cost.

---

Written 2026-11-13 21:30 PST for the agent who picks this up after the weekend. You are
starting cold. Read in this order, then come back here:

1. `AGENTS.md` (repo rules, live-box rules, access method)
2. `docs/winter-2026-findings.md` (everything measured so far)
   and `docs/battery-bank-methodology.md` (how the bank behaves, the planner design
   that follows, choices and mistakes)
3. `docs/analysis-plan.md` (original brief; its Decisions log at the bottom holds Dan's
   design rules and the record of the one live-box change)
4. `docs/how-it-works.md` (current runtime behavior of the integration)

## Where things stand

- The analysis has answered Dan's headline question: stay on PGE Time of Day. It beats
  flat by about $22-28/month in November to January.
- The daytime grid draws are explained (findings section 2). The recoverable waste is
  about $10/month, so keep the rework proportionate.
- A battery calibration test is running on the live box this weekend (below).
- No integration code has been changed. Nothing is committed. Uncommitted in the working
  tree: `AGENTS.md`, `docs/analysis-plan.md`, `docs/winter-2026-findings.md`,
  `docs/HANDOFF.md`. Do not commit or push unless Dan asks.
- Raw data and scripts are in `analysis/` (gitignored, this workstation only).

## Who does what, when

| When | Who | What |
|---|---|---|
| Fri 11-13 21:10 | HA automation | Inverter to STANDARD, charge to full. Confirmed started (2.6 kW grid input at 21:14, Bluetti 10 %) |
| Sat 11-14 12:00 | HA automation | Inverter to PV_PRIORITY, discharge on house load |
| Sun 11-15, when Bluetti < 3.5 % for 5 min, or 15:00 | HA automation | Inverter to STANDARD, recharge to full |
| Sat 11-14 21:05 | Checked | Discharge running since 12:00, B300 63 %, Vatrers 60-79 %. Partial results in findings section 7 |
| Sun 11-15 13:30 | Checked | B300 29 %, Vatrers 37-58 %, will not reach the floor; recharge will start at 15:00. Floor behavior answered from history (findings section 7) |
| Mon 11-16 03:00 onward | Existing integration, unchanged | Sees a full battery, switches to PV_PRIORITY, runs its normal weekday logic |
| Mon 11-16 or later | You | Steps 1-5 below |
| After that | You | The rework, on a branch |

Dan gets a phone notification after each automation step. He does not need to do anything
over the weekend.

## Status, Mon 2026-11-16 00:45 PST (read this first)

- The test is over and the temporary automation is **deleted** (19 automations remain).
  The box is back to its pre-test configuration. The section below is history.
- Step 1 is done: data pulled 2026-11-16 08:27 UTC; the 2026-11-13 files are in
  `analysis/data/raw/snap_2026-11-13/`. Pull again after Monday 21:00 for the
  ride-through (Step 2 question 6), and before 2026-11-22 in any case.
- Step 2 questions 1-5 are answered in findings section 7 ("Update, Mon 2026-11-16").
  Question 6 (Monday) is open.
- Dan confirmed the learned-curve design as the next step and wants the improvement
  measured. Agreed order of work is in "Step 4a" below.
- Offline replay is done (findings section 8). Prediction: learned curves halve the
  gauge-tracking error of the current model; the learned load profile removes a
  0.5 kWh/day under-forecast. Dollars, on a validated two-store bank model
  (`analysis/scripts/bank_model.py`, `replay_cost.py`): November as run $24.30 per half
  month against $17.29 with the new rules and a full charge every TOU night.
- Dan approved 2026-11-16: in winter, charge every TOU night until the inverter stops.
  The replay says November to January full, February and March a sized charge.
- Monday 2026-11-16 ride-through: a background job pulls the data at 21:06 that day. If
  it did not run, pull again (Step 1) and run `python -I scripts/tiers.py`.
- The 2025-12-27/28 run-down was deliberate (Dan), method not remembered. For the
  2026-11-21 test try, grid connected and one at a time: `number.ac500_battery_range_start`
  to 0, then `switch.ac500_grid_charge_on` off; only then the input breaker. Each is a
  live-box change needing Dan's approval.
- **Dan's standing instruction, 2026-11-16:** keep going until finished; free to deploy
  to Home Assistant; notify him (`~/src/notify.sh --event=needs-input`) only for
  critical questions. Changes on the box for the Saturday low-end test still get a
  notify before each one.
- Code: 0.7.0 is committed on branch `winter-2026-rework` (commit 5554ba0 plus any
  review fixes): `learning.py`, `planner.py`, `learned_runtime.py`, new optional
  settings, two sensors, `backfill_learning` service; 201 tests. `docs/how-it-works.md`
  has a "Learned planner" section. Analysis docs (`HANDOFF`, findings, methodology,
  `analysis-plan`, `AGENTS.md` edits) are deliberately NOT committed: the repo is public
  and they describe the household. Ask Dan before committing them.
- `analysis/scripts/shadow_replay.py` runs the real integration runtime (HA mocked) over
  the pulled data; use it after any change to the runtime.

- **Deploy status, Mon 2026-11-16 21:50 PST:** v0.7.0 is on the box in shadow mode
  (planner `classic`), options set, backfill done (Decisions log has the details).
  Docs are committed. Next check: Tuesday morning, compare the `learned` block of the
  scorecard and the `Learned Plan` sensor with what classic did (validation plan below).
- Monday rode through on the full bank with no grid input through the inverter
  (findings section 9).

### Plan to done (agreed with Dan 2026-11-16)

1. Mon 11-16 after 21:00: report Monday's ride-through; deploy 0.7.0 in shadow mode
   (runbook below).
2. Tue-Fri: each morning compare the `learned` block of the scorecard and the
   `Learned Plan` sensor with what classic did; fix anything off.
3. Sat 11-21: low-end test, grid connected, one setting at a time, notify before each.
4. Sun 11-22: set the planner option to `learned` if the shadow days look right; notify.
5. Following week: compare mid-peak and peak import and dollars with the weeks before;
   final write-up; Dan deletes the temporary `claude` HA login.

### Validation and measurement plan

Success measure (Dan, 2026-11-16): grid energy through the inverter in mid-peak and
peak, and what it costs. Load outside the inverter is by design and is not counted.

- Per TOU day, from `sensor.ac500_ac_input_power` by tariff window: kWh in mid-peak and
  peak, kWh of that which was battery charging (input minus output), and dollars at
  Time of Day prices. `analysis/scripts/tiers.py` prints the first two; the scorecard's
  `learned.grid_kwh` records the same inside the integration.
- Baseline: the six weekdays before the test (2026-11-04 to 11-13) averaged 1.8 kWh
  mid-peak and 0.6 kWh peak of battery charging per day. Monday 11-16 on a full bank: 0.
- Shadow week (11-17 to 11-20, classic in control): each day record what classic did,
  what the learned planner would have done (`night_target_gauge`, `midpeak_charge_wanted`)
  and how good its prediction was (`pred_gauge_peak_start` and `pred_gauge_peak_end`
  against `gauge_peak_start` and `gauge_peak_end`). Target: prediction within about
  5 gauge points.
- Learned week (from 11-23): the same table with the learned planner in control.
  Target: zero mid-peak and peak charging on normal days, the battery never at its floor
  before 21:00, and the hold until 07:00 visible in the data.
- Weather differs week to week, so also rerun `replay_cost.py` over both weeks: it
  prices what each policy would have cost on the same measured load and solar.
- Report: one table per week in `docs/winter-2026-findings.md`, and the before/after
  chart for the white paper.

### Deploy runbook (HACS tracks GitHub releases; v0.7.0 deployed 2026-11-16)

1. `python -m pytest -q`; merge the branch to `main` (fast-forward); push; tag `v0.7.0`;
   `gh release create v0.7.0`.
2. On the box (API, `analysis/scripts/ha.py`): call `update.install` on
   `update.solarseed_peak_shaver_update` with `version: v0.7.0`, then
   `homeassistant.restart`. Do it outside the peak window and not while a charge is
   running. HACS websocket commands were not reachable from `ha.py` on 2026-11-16.
3. After restart: config entry state `loaded`, no errors from
   `custom_components.solarseed_peak_shaver` in the log, old sensors still updating,
   `sensor.solarseed_peak_shaver_learned_plan` present.
4. Set options through the options flow (`/api/config/config_entries/options/flow`):
   read the form defaults first and send them all back (options replace wholesale, and
   the diagnostics redact `notify_entity`). New values: `gauge_entity`
   `sensor.ac500_total_battery_percent`, `load_power_entity`
   `sensor.ac500_ac_output_power`, `grid_power_entity` `sensor.ac500_ac_input_power`,
   `pv_power_entity` `sensor.ac500_dc_input_power`, `planner` `classic`.
5. Call `solarseed_peak_shaver.backfill_learning` (`?return_response`) and check the
   summary is sane (floor to full about 15-18 kWh, 07-21 load about 9 kWh).
6. Rollback: `update.install` with `version: v0.6.0` and restart. The stored `learning`
   key is ignored by 0.6.0.
- Two corrections that change Step 4: charging stops completely when the B300 flips to
  100 % at about 55 V, so item 6b's "until the Vatrers read 99 % or 56 V" cannot
  happen; and the 3 % floor is a setting, not physics (December 2025 event).
- Dan wants a low-end test on the weekend of 2026-11-21. Any change on the box for
  that test needs his approval for that specific change.
- 2026-11-17, Dan: the December 2025 run-down was probably done with the AC500's
  setting that lets it run below its low-battery protection until it shuts down
  (instead of switching to grid). Goal of the Saturday test, as revised: find the bus
  voltage at which the AC500 shuts down (and how it recovers), so the integration can
  stop discharging at a voltage with a margin above it and use the Vatrer charge now
  left behind (about 5-7 kWh by the December 2025 numbers). Log the bus voltage
  (`sensor.vatrer_N_voltage`), each Vatrer percent, B300 percent, AC in and out at
  1-minute resolution. Note the voltage when the B300 reaches 3 %, when it parks, when
  any Vatrer BMS cuts out, and at shutdown; then whether the AC500 passes grid through
  and restarts by itself.
- Revised 2026-11-17 late (findings section 11): Deep Discharge is a below-0 % emergency
  mode, not the setting; the setting is `number.ac500_battery_range_start` (SOC Low, now
  2, handover seen at gauge 3). Saturday no longer hunts the shutdown voltage: set it to
  1, let the B300 park, record the bus voltage and Vatrer charge when the inverter
  bypasses to grid at gauge 0 (December 2025: 48.2 V), with an abort if the bus reaches
  about 47.5 V without a handover (switch to grid by hand or by mode). Never 0: the
  unit warns bypass may fail. Keep 1 afterwards only if the handover worked.
- Proposed design after the test (not built): optional bus-voltage sensor and a voltage
  floor; discharge stops (hold) when the loaded bus voltage falls below it, and an
  unavailable voltage sensor counts as below; energy counted down from the nightly full
  anchor becomes the ruler, the learned curve the fallback. The B300 percent stays for
  the top anchor and as a check.

## Live-box changes for the low-end weekend (open)

- 2026-11-18, approved by Dan: temporary automation `temp_claude_lowend_test_20261120`
  (entity `automation.temp_claude_low_end_test_weekend_2026_11_20`). Source:
  `analysis/data/live_changes/lowend_automation_2026-11-20.yaml`; states before:
  `states_before_lowend_automation.json`. Date-guarded, inert outside
  2026-11-20 21:00 .. 2026-11-23 08:00. Delete it Sunday 2026-11-22 (checklist).
- Planned, each needing Dan's OK at the time: SOC Low 2 -> 1 and PV_PRIORITY Saturday
  morning.
- Done: v0.7.1 installed by Dan and HA restarted Thu 2026-11-19 late afternoon; verified
  (mode unchanged, no errors).
- Do not touch the AC500's Time Control "Period 1: Charge 00:00-00:01": Dan set it on
  purpose (findings section 11, open question).

## The live-box change (cleaned up 2026-11-16)

One temporary automation, added 2026-11-13 16:59 PST with Dan's approval:

- id `temp_claude_calibration_20261113`
- entity `automation.temp_claude_battery_calibration_weekend_2026_11_13`
- config copy: `analysis/data/live_changes/calibration_automation_2026-11-13.json`
- backup of the 19 automations that existed before: `analysis/data/raw/automation_configs.json`

It is date-guarded and does nothing after 2026-11-15. Dan approved deleting it on Monday.
Tell him before you do it, then:

```bash
cd analysis && export MSYS_NO_PATHCONV=1
python scripts/ha.py delete /api/config/automation/config/temp_claude_calibration_20261113
python scripts/ha.py rest /api/states   # confirm 19 automations remain, none unavailable
```

Record the deletion in the Decisions log of `docs/analysis-plan.md`. If it has already
been deleted in the UI, just record that.

Every other change to the box (automations, config entries, helpers, inverter modes)
needs Dan's explicit approval for that specific change. Reading is always fine.

## Access

Dan created a temporary HA administrator user for this work and will delete it when the
work is done. Ask him whether it still exists and for the credentials; they are not
stored anywhere in the repo. Then:

```bash
cd analysis && export MSYS_NO_PATHCONV=1
python scripts/ha.py login <user> <password>     # caches a token in analysis/.ha_token.json
python scripts/ha.py rest /api/config            # smoke test
```

A cached token from 2026-11-13 may still work without logging in again. Scripts need
Python with `aiohttp` (already on this workstation); everything else is stdlib. Run
analysis scripts with `python -I`.

## Step 1 - pull the weekend data (do this by 2026-11-22)

The AC500 power sensors keep raw states for 1 day only and 5-minute statistics for about
10 days. After that only hourly means remain, which is too coarse for the charge taper.

```bash
cd analysis && export MSYS_NO_PATHCONV=1
python scripts/pull_history.py stats   2024-01-01T08:00:00Z <now UTC>
python scripts/pull_history.py states  2026-11-13T08:00:00Z <now UTC>
python scripts/pull_history.py logbook 2026-11-13T08:00:00Z <now UTC>
```

This overwrites `analysis/data/raw/stats_*.json`. Copy the old files aside first if you
want to keep the 2026-11-13 snapshot.

## Step 2 - analyze the calibration test

Check the logbook first for what really happened and when: each automation step, and
any failed mode command (one in eight silently failed in early November).

Questions to answer, with the sensors to use:

1. **Charge: how long, how much, what shape.** Net AC into the battery per 5 minutes is
   `sensor.ac500_ac_input_power - sensor.ac500_ac_output_power`. Find when it tapers
   and when it reaches zero. Expect roughly 1.9 kW net and 10-12 hours from empty.
   This sets how early an overnight charge must start. A full charge from empty may not
   fit in the 21:00-07:00 off-peak window at all; that is a real design constraint.
2. **Did all five counters reset?** `sensor.ac500_total_battery_percent` (the B300) and
   `sensor.vatrer_N_battery` should all read 99-100 with pack voltage near 57 V. Before
   the test they read 18, 31, 11, 11 and 10 at one shared voltage.
3. **Usable capacity.** From Sat 12:00 until the grid takes over (AC input rises from 0),
   sum `sensor.ac500_ac_output_power`. Also sum `-sensor.vatrer_N_power` for the DC
   energy the Vatrers gave. This replaces the unknown in findings section 2f.
4. **Does the B300 track the Vatrers?** Tabulate B300 percent against mean Vatrer percent
   through the discharge. If the B300 reaches its floor while the Vatrers still hold
   energy, that energy is stranded and the planner must know how much. The earlier claim
   that the B300 is "worked harder than its share" rested on an assumed inverter loss and
   is not established; this test settles it.
5. **Round-trip efficiency against the real meter.** Compare grid energy for the Sunday
   recharge with AC energy delivered during the discharge. Use the Vue mains sensor
   `sensor.vuetonia_123_1min` as the billing truth. The AC500's own sensors do not close
   an energy balance (output exceeds input by 3.5 % over a year), so do not derive
   efficiency from them alone. Load not behind the AC500 is about 40-50 W at night and
   about 100 W by day; subtract it.
6. **Monday as a free test.** Monday starts full. Did the house get through 07:00-21:00
   with no mid-peak or peak charging? `python -I scripts/tiers.py` prints import by tier
   per day; `python -I scripts/timeline.py 2026-11-16T00:00 2026-11-17T00:00` prints the
   event timeline.

Write the results into `docs/winter-2026-findings.md` (new section 7), and correct
sections 2b, 2f and 6 where the measurements replace estimates. Then rerun
`python -I scripts/backtest.py` with the measured capacity and efficiency.

## Step 3 - things to tell Dan after the test

- Measured usable kWh, hours to full, round-trip efficiency.
- Whether the B300 strands Vatrer energy, and how much.
- Whether Monday rode through on one full charge.
- An interim setting he can change by hand if the rework will take a while (for example
  a higher base load or floor). Work it out against the measured numbers before
  proposing it; a bigger overnight target that cannot finish by 07:00 would spill into
  mid-peak under the current code.

## Step 4 - the rework

Branch first (`git checkout -b winter-2026-rework`). Dan's rules, from the Decisions log:

1. Solcast updates refresh the plan but never start a charge by themselves.
2. Off-peak precharge is planned to **finish at 07:00**. Start time comes from energy
   needed divided by measured charge rate, anywhere in 21:00-07:00.
3. Mid-peak charging happens only if the 17:00-21:00 window would otherwise not be
   covered, and is planned to **finish by 17:00**. Never charge in peak.
4. A periodic full calibration charge on the weekend, starting Friday 21:00.
5. Base load adapts to measured load (Dan's gaming PC raised it). Learn it from
   `sensor.ac500_ac_output_power`, as an hour-of-day profile, not from SOC accounting.

What the analysis adds:

6. **Plan from the Bluetti percent with the right scale, and keep the bank in its band.**
   Superseded 2026-11-14 by the test (findings section 7): the batteries share power
   equally per battery, so the inverter stops when the 3 kWh B300 is empty. The Bluetti
   percent is therefore the right gauge for energy until cutoff; only its scale is
   wrong, and the scale moves (0.175 kWh AC per percent from a full start, 0.13-0.15 in
   the drifted state, against 0.235 assumed). Preferred design, proposed to Dan
   2026-11-15 and not yet confirmed by him: the integration learns the discharge curve, the charge curve and the
   load profile from its own sensors (see `docs/battery-bank-methodology.md`, "Design
   for the planner"). A fixed scale is the stopgap. Use the
   Vatrer counters to check the band (Vatrers about 40 % when the B300 is at its floor,
   100 % together) and to decide when a top-up is due.
6a. **Weekday charge target is B300 100 %** in deep winter: about 9 hours from empty at
   1.85 kW net, so it fits 21:00-07:00 only if it starts by about 22:00.
6b. **Weekend top-up continues after the B300 reads 99 %** until it flips to 100 % and
   charge power falls to zero (the inverter ends the charge itself at about 55 V; the
   Vatrers never reach the 56 V that resets their counters). The inverter throttles to
   about 0.75-1 kW in that phase; allow up to 12 hours. Dan wants to avoid the graph
   where the B300 is full hours before the Vatrers, and this band is how.
7. **Winter target is simply "full".** In November to January, charging to 100 % before
   every TOU day matched perfect foresight in the backtest. February, March and October
   need a forecast-based target because a full battery wastes solar.
8. **Hold until 07:00.** Today the inverter goes to PV_PRIORITY when the charge ends and
   the battery carries the house from about 05:00 at off-peak prices. Use the existing
   `preserve_start` event for the hold and fire `charge_stop` at 07:00.
9. **Stop on the window edge.** A charge still running at 07:00 or 17:00 must be
   stopped by the integration, not left to finish.
10. Fix or remove the learned-base-load formula in `coordinator.py` (search for
    `total_consumption =`): it subtracts every charge, where the overnight charge should
    be absent and daytime charges added. It is inactive on Dan's box only because
    `solar_actual_entity` is unset.
11. Scorecard bookkeeping: charges ended by a "no charge needed" recalculation are not
    recorded, a re-triggered charge overwrites the start, and daily tracking is lost on
    restart.

### Step 4a - order of work proposed to Dan 2026-11-16

1. **Offline first, no deploy.** Prototype the three learned tables in
   `analysis/scripts/` from the pulled statistics and replay history: at each 07:00,
   predict the gauge at 17:00 and 21:00 with the current model (percent x 0.235,
   0.6 kW) and with the learned one. Report prediction error and, from `backtest.py`,
   daily regret against hindsight in dollars (Vue-based). That is the baseline and the
   expected gain.
2. **Code on branch `winter-2026-rework`.** A pure module (no HA imports) for the
   learner and planner so it is unit-testable and the replay can import it. New
   optional config keys with defaults (load power, grid input power, grid meter). A
   planner option `classic | learned`, default classic, so the switch and the rollback
   are one options-flow change, not a deploy.
3. **Shadow mode.** Deployed with the option on classic, the learner runs, publishes
   its own "energy remaining" and "plan" as sensors, and records both predictions in
   the daily scorecard (new fields only). A backfill service seeds the tables from
   recorder statistics so it does not start cold.
4. **Switch to learned** after about a week of shadow predictions look right. Dan's
   scheduling rules 1-3, 8 and 9 ship with the learned planner.
5. Additions proposed for 2.0 (not yet confirmed by Dan): verify mode commands took effect and retry or alert;
   stale or unavailable gauge falls back to classic; daily regret and a plain-language
   plan explanation as sensors; plan to a high percentile of learned load, not the
   mean (a shortfall costs 43 c/kWh, an overcharge about 9 c). Later, not in 2.0:
   tariff windows and prices as configuration, Solcast 10th-percentile for margin,
   two-stage gauge below the B300 floor (depends on the floor test).

Deploying (push to main, HACS update, restart) needs Dan's explicit instruction each time.

Repo constraints (details in `AGENTS.md`): config keys and event names are persisted
contracts, so add keys with defaults and do not rename; new config fields need
`strings.json` and `translations/en.json`; version bump touches `const.py` and
`manifest.json`; `python -m pytest -q` before every commit; pushing to `main` is a
deploy and needs Dan's explicit instruction.

The oven is on a 240 V circuit that is not behind the AC500, so the battery cannot cover
it. No bake allowance is needed in the planner; the existing "Power Alerts" automation
already warns about peak-hour spikes.

## Step 5 - open items

- Usable capacity, charge rate, efficiency: from the test.
- Rewiring: the test shows equal power per battery, so the B300 does 20 % of the work
  with 13 % of the capacity. Shifting share to the Vatrers would need hardware changes
  (resistance in the B300 branch, or a different port arrangement). Not verified against
  Bluetti's port ratings; do not advise rewiring from the data alone. The operating band
  in findings section 7 gets the practical result without it.
- The AC500's limits (charge and output power) appear to depend on how many Bluetti
  packs it recognizes. Dan reports the single B300 caps them. Not verified here.
- PGE: an "October 15, 2026 price change" appeared in one search summary and could not
  be confirmed. Tariff numbers in use are in `analysis/scripts/backtest.py` (Advice
  26-06 sheets, effective 2026-04-01, plus PGE's Time of Day web page).
- The backtest's weekend handling wastes solar in sunnier months; fix before quoting
  February, March or October numbers.
- 0.7.1 trade-off: the first calculation after a restart fires nothing, in either
  direction. That fixed the released hold, but a restart in mid-peak also skips a
  needed top-up until the next calculation (seen 2026-11-19: classic wanted 0.7 kWh
  late in mid-peak, did nothing, and peak started soon after). A finer rule:
  on the first calculation, still allow a charge start but never release a hold or
  stop a charge. Not urgent; restarts are rare.

## Scripts in `analysis/scripts/`

| Script | Purpose |
|---|---|
| `ha.py` | Login, REST, WebSocket, Supervisor API; `post` and `delete` change the box |
| `pull_history.py` | Pull states, statistics (including Vatrer and B300), logbook |
| `timeline.py` | Event timeline: mode changes, automation triggers, Solcast polls, targets |
| `table.py` | Binned power table from 5-minute statistics |
| `tiers.py` | Daily grid import and battery grid-charge by tariff tier |
| `capacity.py`, `capacity2.py` | Energy per Bluetti percent by month and by SOC band |
| `soc_compare.py` | Bluetti percent against the four Vatrer counters |
| `backtest.py` | Policy backtest and plan comparison |
| `check_at.py` | Wait until a clock time, then print inverter and battery state |

Timestamps: `timeline.py`, `table.py`, `tiers.py` and the capacity scripts use fixed PST,
which is correct from November 1 to March 8 only. `backtest.py` handles daylight saving
and PGE holidays.
