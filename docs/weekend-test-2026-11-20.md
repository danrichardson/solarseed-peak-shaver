# Weekend low-end test, Fri 2026-11-20 21:00 to Mon 2026-11-23 07:00

Tick the boxes as you go (`[ ]` -> `[x]`). Owner of each step in brackets:
**[Dan]**, **[Claude]**, or **[box]** (a temporary automation on Home Assistant).
Every change on the box is listed here and still gets a notify before it happens.

## What we want to learn

1. How much energy the bank gives from full down to the B300's 3 % (today's handover),
   then with the B300 parked at 1 %, down to the inverter's own handover at 0 %.
2. The bus voltage at each of those points, and how much it sags under load.
3. Whether the AC500 hands the house to the grid cleanly at 0 % with Battery SOC Low
   set to **1** (no blink, no dark house), and recharges afterwards.
4. Time and energy to recharge from truly empty to full.

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
- [ ] **[Dan] Thu:** approve release 0.7.1 and the update + restart (midday, while the
  inverter is on battery anyway, so a restart is harmless). Accept in HACS if asked.
- [ ] **[Claude] Thu:** write the temporary automation (below) and the monitor script;
  send both to Dan to read.
- [ ] **[Dan]:** approve the temporary automation `temp_claude_lowend_test_20261120`.
- [ ] **[Dan]:** confirm the 1500 W heater is on an AC500-backed outlet and safe to
  run unattended for about 12 hours.
- [ ] **[Claude] Fri 20:00:** snapshot states, diagnostics and the integration's
  stored learning (rollback point).

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
- [ ] **21:05** [box] the integration's normal hold fires (TIME_CONTROL). Expected.
- [ ] **21:10** [box] mode STANDARD. Charging starts.
- [ ] **21:20** [Claude] check: AC input about 1.5-1.9 kW, gauge rising. Record start
  gauge, bus voltage, each Vatrer percent.
- Expect full around 05:00-07:00 Saturday (about 8.5 h to 99 %, then a slower tail;
  charging stops completely when the B300 flips to 100 %, about 55 V).

## Saturday 2026-11-21: run-down

- [ ] **~07:00** [box/Claude] "bank full" notify. Record: time, kWh in (AC input and
  Vue), bus voltage, each Vatrer percent.
- [ ] **~08:00** [Dan] approve the run-down start (reply to the notify).
- [ ] **08:00** [Claude] `number.ac500_battery_range_start` 2 -> **1**.
- [ ] **08:00** [Claude] mode **PV_PRIORITY** (battery carries the house).
- [ ] **08:00** [Dan] heater ON (house plus heater about 2.1 kW; solar adds a little).
  Target: the handover in the evening, roughly 18:00-22:00. If it is running fast or
  slow, turn the heater off or on; Claude will say which.
- [ ] [Claude] monitor runs every minute and notifies at: B300 20 %, 10 %, 5 %, 3 %,
  1 % (parked), each Vatrer 10 % and 5 %, bus 50.5 / 50.0 / 49.5 / 49.0 / 48.5 V,
  handover, abort threshold, data stale.
- [ ] **Sag check 1**, bus about 52.5 V: [Dan] heater off 10 min, then on.
- [ ] **Sag check 2**, when the B300 parks at 1 %: heater off 10 min, then on.
- [ ] **Sag check 3**, bus about 50 V: heater off 10 min, then on.
- [ ] **Sag check 4**, bus about 49 V: heater off 10 min, then on.
- [ ] Old handover point: does the inverter carry on past B300 3 % now? (expected yes)
- [ ] B300 parks at 1 %: time, bus voltage, Vatrer percents.
- [ ] Any Vatrer BMS cut-out: time, voltage, which pack.
- [ ] **Handover**: time, bus voltage, B300 0 %, each Vatrer percent. Did the house
  blink? Does AC input carry the load?
- [ ] [Dan] heater OFF once the grid has taken over.

## Saturday evening to Sunday: recharge

- [ ] [Claude] mode **STANDARD** right after the handover (charge from empty). Leave
  SOC Low at 1 for now.
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
  decided, all 19 normal automations on.

## Monday 2026-11-23

- [ ] **07:00** mode PV_PRIORITY (planner or fallback). **21:00** first weekday result.
- [ ] [Claude] write up in `docs/winter-2026-findings.md` (new section), update
  `docs/battery-bank-methodology.md`, and propose the voltage floor value.

## After the weekend: what the results feed

- Energy counted down from full becomes the ruler (needs: total full -> floor energy).
- Voltage floor for the integration (needs: handover voltage, sag per kW).
- White paper section "Pending: the low-end test".
