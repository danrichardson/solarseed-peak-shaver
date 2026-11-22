# Weekend low-end test, Fri 2026-11-20 21:00 to Mon 2026-11-23 07:00

Tick the boxes as you go (`[ ]` -> `[x]`). Owner of each step in brackets:
**[Dan]**, **[Claude]**, or **[box]** (a temporary automation on Home Assistant).
Every change on the box is listed here and still gets a notify before it happens.

## What we want to learn

1. Measure the energy delivered from full to the B300's indicated 3%, and from
   there to the observed handover or abort.
2. Find the indicated B300 percentage and pack voltage where voltage starts
   falling faster under steady load. Record each Vatrer voltage separately.
3. With reserve set to 1%, observe when grid input picks up the heater load
   and whether the AC500 output stays on. The critical circuits will be on utility
   power for this part.
4. Measure the recharge from the observed endpoint to the inverter stopping.

From these: whether to keep SOC Low at 1, and where the integration's own voltage floor
goes (expected about 50 V). We are **not** looking for the shutdown voltage, and
**Deep Discharge stays OFF** the whole weekend.

## Settings that matter (findings section 11)

| What | Entity | Normal | Weekend |
|---|---|---|---|
| Mode | `select.ac500_ups_mode` | integration drives it | STANDARD = charge, PV_PRIORITY = run on battery, TIME_CONTROL = hold |
| Battery SOC Low / PV reserve | `number.ac500_battery_range_start` | 2 | **1** from the run-down start |
| Grid charge | `switch.ac500_grid_charge_on` | on | on (unchanged) |
| Deep Discharge | unit screen only | OFF | OFF |
| Planner option | integration options | classic | classic until Sunday evening |

Safe state at any moment: **STANDARD** (house on grid, battery charging). Anyone can
set it at the unit or in Home Assistant, and it ends the test safely.

## Abort rules (any one: set STANDARD, then notify / tell Dan)

- Lowest Vatrer voltage at or below **47.5 V** and the grid has not taken over
  (AC input near 0 W).
- Any error code or alarm on the AC500 or B300 screen.
- The house circuits on the AC500 blink or drop.
- Battery data in Home Assistant stops changing for more than 10 minutes while the
  B300 is below 5 % (the data path can freeze; then Home Assistant cannot act, so
  switch at the unit).
- Dan is uneasy for any reason. Science can wait a weekend.

A Vatrer cutting out on its own BMS is **not** an abort: it is safe and recovers
(Dan). Note the time and voltage and carry on.

## Before Friday

- [x] **[Claude] Thu:** fix the learner so a parked gauge cannot corrupt the curve
  (cap one gauge point at 2 hours / 1 kWh; discard longer stretches). Tests pass.
  Done Wed night, commit 76c2620; on the last 10 days of real data it discards nothing.
- [x] **[Claude] Thu:** same release: a Home Assistant restart must not change the
  inverter mode (the 0.7.0 restart released a hold). Done, same commit; 219 tests pass.
- [x] **[Dan] Thu:** approve release 0.7.1 and the update + restart (approved; v0.7.1 released Wed night; HACS refused the agent's install Thu 12:41, so Dan installs it) (midday, while the
  inverter is on battery anyway, so a restart is harmless). Accept in HACS if asked.
- [x] **[Dan]:** install v0.7.1 in HACS and restart (any time before Fri 21:00).
  Done Thu 2026-11-19 late afternoon.
- [x] **[Claude]:** verify 0.7.1 is loaded, no errors, mode unchanged by the restart.
  Update entity shows v0.7.1 installed. Mode was PV_PRIORITY before, briefly unknown
  during the restart, PV_PRIORITY after; nothing fired. The first calculation wanted a
  0.7 kWh mid-peak top-up and, as designed, did not act on it. No errors; the only
  warning is a startup race (Solcast entity not loaded yet), which cleared by itself.
- [x] **[Claude] Thu:** write the temporary automation (below) and the monitor script;
  send both to Dan to read. Done Wed night: `analysis/data/live_changes/lowend_automation_2026-11-20.yaml`
  (templates checked against live values with HA's template renderer, nothing installed)
  and `analysis/scripts/lowend_monitor.py` (read-only; dry run logged two rows, sent
  nothing). Both are local only (analysis/ is not in git).
- [x] **[Dan]:** approve the temporary automation `temp_claude_lowend_test_20261120`.
  Approved and installed Wed 2026-11-18 late evening; entity
  `automation.temp_claude_low_end_test_weekend_2026_11_20`, on, inert until Fri 21:00.
  No errors in the log; 20 automations now.
- [ ] **[Dan] 07:15 Saturday reminder.** Plug the 1500 W heater into its AC500-backed
  wall outlet and leave it off. Run it only while attended.
- [x] **[Dan]:** install v0.7.2 in HACS and restart (released Thu night; HACS refused
  the agent's install again). Done Thu night.
- [x] **[Claude]:** verify 0.7.2 is loaded and no errors. v0.7.2 installed; mode
  TIME_CONTROL before and after the restart (the first calculation wanted a 5.4 kWh
  charge and, as designed, fired nothing); SOC Low 2; weekend automation on; no errors
  from the integration (only the known Solcast startup race).
- [ ] **[Claude] Fri 20:00:** snapshot states, diagnostics and the integration's
  stored learning (rollback point). Missed. A later states and diagnostics snapshot
  is saved locally under `analysis/data/live_changes/*_after_charge_start_2026-11-20.json`.

## The temporary automation (date-guarded, inert after Mon 2026-11-23 08:00)

Runs on the box whether or not Claude is awake. Each action notifies Dan's phone.

| Trigger | Action |
|---|---|
| Fri 2026-11-20 21:10 | mode STANDARD (start the full charge; after the integration's 21:05 hold has fired) |
| B300 at 100 % and AC input below 100 W for 10 min, Sat before 12:00 | notify "bank full" (no mode change; Dan or Claude starts the run-down) |
| Lowest Vatrer voltage at or below 47.5 V for 2 min and AC input below 100 W | mode STANDARD + urgent notify (automatic abort) |
| Mode not what was last set, 3 min after setting | set it again (up to 3 times) + notify |

## Friday 2026-11-20

- [ ] **21:00** [Claude] notify: "starting the weekend test in 10 min, reply stop to cancel".
  The workstation missed this reminder window.
- [x] **21:05** [box] the logbook shows TIME_CONTROL at 21:05:04.
- [x] **21:10** [box] the temporary automation fired at 21:10:00. The AC500 reported
  STANDARD at 21:10:04. Recorder shows B300 9%, pack voltage 52.1 V and Vatrers
  21/7/3/5% at the transition.
- [x] **21:20** [Claude] checked late at 22:26. Recorder shows B300 12% at 21:20
  with 2.55 kW AC input and 0.86 kW output. At the live check B300 was 25%,
  with 2.41 kW input and 0.68 kW output.
- The early-morning estimate is for B300 99%. On the previous run charging
  continued for hours at 99%. Use measured charge completion for the start time.

## Saturday 2026-11-21: run-down

Charge completion confirmed. The minute log first showed B300 99% at 05:42.
HA reported 100% at 12:33:46 PST. The 12:34 sample showed B300 55.4 V and
Vatrers 100/90/81/82% at 55.21/55.11/55.25/55.23 V. By 12:47 the AC500
was passing grid power through to the load, with all four Vatrer currents
between -1.03 and 0 A. Mode STANDARD, reserve 2%. Bank-full phone alert sent
for the start chat. Dan confirmed receipt and chose the 20% transfer cue.

- [ ] Verify charge completion from fresh readings: B300 100%, charge currents near
  zero, and grid input accounting for the house load. Record time, AC input and Vue
  energy, B300 voltage and each Vatrer's voltage and percentage. The "bank full"
  alert can miss this if house load exceeds 100 W or completion is after noon.
- [x] Start approved, monitor logging, phone delivery confirmed. Use the B300 20%
  alert to transfer the critical circuits and the 3% alert to return to chat.
- [x] PV_PRIORITY with heater and critical circuits on battery. AC input was zero
  and output about 1.9 kW after the transfer.
- [ ] **Dan** sets reserve to **1%** at the unit. Verify the readback. HA reported
  5% immediately after the mode change (2% during the overnight charge).
- [ ] At the agreed alert Dan transfers the critical circuits to utility, leaving
  only the heater on the AC500. Dan confirms the transfer. Record the time and AC
  output before and after so the load step can be identified in the voltage trace.
- [ ] At the B300 3% alert Dan returns to chat. Follow B300 pack voltage, gauge,
  each Vatrer voltage, AC input/output and PV together. Record any steepening
  under steady load, the first sustained grid draw, and whether the heater lost
  power. Near 1% discuss the readings together. This run is authorized at 1%
  reserve; a displayed 0% is a possible observation. The voltage abort stays active.
- [ ] [Claude] monitor runs every minute and notifies at: B300 20 %, 10 %, 5 %, 3 %,
  1 % (parked), each Vatrer 10 % and 5 %, bus 50.5 / 50.0 / 49.5 / 49.0 / 48.5 V,
  handover, abort threshold, data stale.
- [x] **Sag check 1** recorded at the 52.5 V cue, plus an earlier comparison near
  96% B300. Local analysis notes with before/off/after windows and all five
  voltages: `analysis/data/live_changes/sag_checks_2026-11-21.md`.
- [ ] **Sag check 2**, when the B300 parks at 1 %: heater off 10 min, then on.
- [ ] **Sag check 3**, bus about 50 V: heater off 10 min, then on.
- [ ] **Sag check 4**, bus about 49 V: heater off 10 min, then on.
- [x] Grid pickup occurred at 00:57:03 PST Sunday with reserve confirmed at 1%.
  The AC500 total gauge briefly read 3% and returned to 4% five seconds later.
  The separate B300 pack gauge held at 4%. The one-minute monitor missed the
  3% reading. Neither gauge reached 1% on this run.
- [ ] Any Vatrer BMS cut-out: time, voltage, which pack.
- [x] **Handover**: B300 pack 50.6 V; Vatrers 50.74/50.76/50.77/50.75 V at
  19/4/0/2%. All four last reported discharge current, including pack 3 at 0%.
  AC input rose from zero to 1.17 kW then 3.40 kW while still in PV_PRIORITY.
  Output stayed above 1.4 kW at the recorded samples; a sub-sample blink is
  unverified. Recorder extract: `analysis/data/live_changes/handover_history_2026-11-22.json`.
- [x] [Dan] approve the automation's handover trigger fix (v2: PV_PRIORITY, gauge
  5 % or less, AC input over 300 W for 2 min). Approved and installed Thu night; the
  automation now sets STANDARD at the handover. v1 kept as
  `lowend_automation_v1_as_installed.json`.
- [ ] [Dan] heater OFF once the grid has taken over.

## Saturday evening to Sunday: recharge

- [x] Mode **STANDARD** reported at 00:59:09 after the grid pickup. Recharging,
  with SOC Low still at 1%.
- [ ] [Claude] record: time and kWh to B300 99 %, to 100 %, to the inverter stopping.
  Expect up to about 20 hours from everything-empty, so done Sunday afternoon.
- [ ] If charging is still running Sunday 18:00: fine, it is all off-peak; let it finish.

## Sunday 2026-11-22: decide and hand back

- [ ] [Claude] first numbers to Dan: energy full -> 3 %, 3 % -> park, park -> handover;
  voltages; sag in volts per kW; recharge time.
- [ ] **[Dan] decide SOC Low**: keep **1** if the handover was clean; otherwise back to 2.
- [ ] [Claude] check the learned curve was not distorted by the parked hours (0.7.1 caps).
- [ ] **[Dan] decide the planner**: switch to `learned` about 20:00 (preferred: it
  charges to full, holds until 07:00 Monday, then runs on battery). If not, fallback:
  [Claude] sets PV_PRIORITY at Monday 07:00.
- [ ] [Claude] delete `temp_claude_lowend_test_20261120` (it is inert by then anyway).
- [ ] [Claude] confirm the box is back to normal: mode, SOC Low as decided, planner as
  decided, the 19 normal automations as before (18 on, `power_alerts` off).

## Monday 2026-11-23

- [ ] **07:00** mode PV_PRIORITY (planner or fallback). **21:00** first weekday result.
- [ ] [Claude] write up in `docs/winter-2026-findings.md` (new section), update
  `docs/battery-bank-methodology.md`, and propose the voltage floor value.
- [ ] Evaluate whether a voltage-based switch to STANDARD before automatic bypass
  could reduce the grid energy bought during recovery. This run records the
  discharge curve. Early return to battery below the recovery level is unverified.

## After the weekend: what the results feed

- Energy counted down from full becomes the ruler (needs: total full -> floor energy).
- Voltage floor for the integration (needs: handover voltage, sag per kW).
- White paper section "Pending: the low-end test".
