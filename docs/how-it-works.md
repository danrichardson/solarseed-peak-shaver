# How the Peak Shaver Actually Works (v0.6.0)

Reverse-engineered from the code on 2026-11-05. The README describes intent; this
describes behavior. Line refs are to `custom_components/solarseed_peak_shaver/coordinator.py`.

## Rate model

Three hard-coded tiers, hour boundaries from config (defaults = PGE Time of Day):

| Period | Hours (weekdays) | README rate |
|---|---|---|
| Off-peak | 21:00 - 07:00, all weekend | $0.09 |
| Mid-peak | 07:00 - 17:00 | $0.18 |
| Peak | 17:00 - 21:00 | $0.44 |

Rates themselves are not in the integration; only `tools/analyze_performance.py` hard-codes
them (plus a 15% round-trip loss). Holidays are not handled.

## Daily timeline (weekday, default config)

| Time | What fires | Effect |
|---|---|---|
| 03:00, 04:00, 05:00, 06:00 | `_on_scheduled_time` -> full recalculation | Fires `charge_start` OR `charge_stop` every run |
| Any Solcast state change between 03:00 and 17:00 | `_on_forecast_update` -> recalculation | Same - can start a charge during mid-peak |
| Every battery SOC change | `_on_battery_update` | If charging and SOC >= target + 0.1 -> `charge_stop`; tracks daily min |
| 07:00:00 .. 21:00:15 hourly | `_on_solar_actual_sample` (only if solar actual entity configured) | Diffs a cumulative solar kWh sensor into per-hour actuals |
| 07:00:30, 17:00:30, 21:00:30 | `_on_soc_checkpoint` | Records SOC at midpeak start / peak start / peak end; daily-min window is 07:00-21:00 |
| 21:05 (months 11,12,1,2,3) | `_on_preservation_time` | Fires `preserve_start` -> blueprint puts inverter in hold mode |
| 21:10 | `_on_daily_scoring_time` | Builds scorecard, saves to store, sends daily report notification |

Weekends: everything is skipped except solar sampling and the SOC listener. The Friday
21:05 hold therefore stays in effect until Monday 03:00.

## The calculation (`_async_update_data`, ~L889)

1. `current_soc` = state of the battery kWh sensor.
2. `hourly_solar` = Solcast `detailedHourly` (kWh/h), else `detailedForecast` (kW per 30 min x 0.5), using **`pv_estimate` (P50)** only.
3. `load_kw` = `effective_base_load` (see feedback loop below) - a **single flat kW** for every hour of the day and night.
4. Project battery at 07:00: `current_soc - hours_until_7 * load_kw` (assumes the battery, not the grid, carries the house until 07:00).
5. Simulate each hour 07..20: `battery += solar[h] * correction[h] - load_kw`, track the minimum. No upper clamp at capacity, no charge/discharge efficiency, no inverter limits.
6. If `min < min_safe_soc`: `target = current_soc + (min_safe - min)`, capped at capacity. Else `target = current_soc`.
7. `charge_needed = target - current_soc`. If `> charge_threshold` (0.5) -> `charge_start` event, `_charging_active = True`. Otherwise -> `charge_stop` event.
8. `charge_below = current_soc - (min - min_safe)` - the SOC at which this run would have started charging.

Charging stops when SOC crosses `target + 0.1`, or when a later recalculation decides no
more charge is needed (that path fires `charge_stop` but does not record a charge event).

## Blueprints (inverter side)

- `charge_start` -> set mode to the "grid charge" value (Dan: `STANDARD`).
- `charge_stop` -> set mode to the "solar priority" value (Dan: `PV_PRIORITY`). Fires on *every* no-charge recalculation, including the 03:00 run.
- `preserve_start` -> set mode to the "hold" value (e.g. `TIME_CONTROL`/`PASSTHROUGH`).

Consequence: in hold months, the 21:05 hold is ended at 03:00 by whichever event the first
recalculation fires. After a no-charge verdict (or after a charge finishes before 07:00),
the inverter is in PV_PRIORITY and the battery carries house load during cheap off-peak
hours until 07:00.

## Feedback loop (learning)

All learning comes from the stored daily scorecards (`store.py`, last 90 days):

- **Effective base load** (`effective_base_load`, L583): once >= 3 scorecards exist, replaces the configured base load with the 14-day mean of per-day `effective_base_load_kw`. Per-day value (L661) =
  `(solar_actual_7_to_21 + (soc_at_07 - soc_at_21) - total_charged_today) / 14 h`, floored at 0.
- **Solar correction**: global factor = mean(actual/predicted) over 14 days, clamped 0.5-1.2 (>= 3 days); per-hour factors = sum(actual)/sum(predicted) per hour over 14 days, clamped 0.5-1.5 (>= 7 days). Both need `solar_actual_entity` configured; without it there is no solar learning and per-day base load is never computed.

## Scoring (21:10)

Start at 100: -30 floor breached, -25 any charge started in mid-peak/peak, up to -15 for
solar forecast error > 20%, up to -15 for min-SOC prediction error > 2 kWh, up to -15 for
"unnecessary" charge (> 2 kWh charged beyond the 03:00 run's `charge_needed`). Grade A-F.
The primary prediction scored is the *first* snapshot of the day (normally 03:00).
Since 0.8.1 this grade is stored and shown (the `Daily Grade` sensor) but no longer
notified when the learned planner's power sensors are configured: the day is graded from
the meters instead, see "0.8.1 additions".

## Learned planner (0.7.0)

A second planner lives beside the one described above. Code: `learning.py` (what it
learns), `planner.py` (the rules), `learned_runtime.py` (the Home Assistant glue). Both
planners always compute; the `planner` option decides which one fires events.

- `classic` (default): everything above is unchanged. The learned planner only reports,
  through the `Learned Plan` and `Learned Energy Remaining` sensors and a `learned` block
  in each daily scorecard. This is shadow mode.
- `learned`: the learned planner fires the same three events and the classic planner
  fires nothing (it still updates its sensors for comparison).

**What it learns**, once a minute, from the gauge and three optional power sensors
(house load, grid input, solar):

- Discharge curve: AC kWh delivered per gauge percent, in 5-point bands.
- Grid-charge curve: net AC kWh absorbed per percent, and hours per percent at full rate.
- Solar-charge curve: PV kWh per percent.
- Load profile: kWh per hour of day over the trailing 14 TOU days (and 14 other days).

Curves forget with a 30-day half-life, so they follow drift and hardware changes. State
is saved hourly in the same storage file under `learning` and survives a restart. The
`backfill_learning` service rebuilds all of it from recorder statistics.

**The rules**, in order (see the docstring of `planner.py`):

1. Peak window: on battery. Never charge.
2. Mid-peak: on battery. Charge only if the battery will not cover the peak window with
   the peak margin to spare, as late as will still finish by peak start. Since 0.8.0
   any predicted shortfall starts a top-up and a running top-up goes 0.2 kWh past the
   need (see "Handover as a cost" below).
3. Night before a TOU day: in the "full" months charge from peak end until the inverter
   ends the charge, then hold until mid-peak start. In other months size the charge from
   the learned load (a high percentile) and discounted forecast solar, time it to finish
   at mid-peak start, and hold before and after.
4. Weekly top-up to full after the last TOU day of the week, in the "full" months, for
   at most 24 hours.
5. Otherwise on battery.

A forecast update changes numbers inside these rules and never starts a charge. If the
model is untrained or the gauge is unreadable, the night rule charges to full.

**Checking the inverter obeyed.** Three minutes after a command the runtime compares the
power sensors with the mode it asked for (charging means grid input well above house
load, and so on). If they disagree it sends the event again, up to three times, then
notifies.

**Events map to modes** exactly as before: `charge_start` = charge, `charge_stop` = on
battery, `preserve_start` = hold. Event data from the learned planner carries `planner`,
`gauge`, `target_gauge` and `reason`.

## 0.8.0 additions

**Handover as a cost** (options `handover_recovery_pct`, default 10, and
`peak_margin_kwh`, default 0.5). When the gauge reaches the floor the inverter hands the
house to the grid, grid-charges its own battery back to the recovery level and stays on
grid. Running out in peak therefore costs the shortfall plus that recharge, all at peak
price. The planner prices the recharge from the learned grid-charge curve (floor to
recovery level) and shows it as `handover_kwh` on the `Learned Plan` sensor and in the
reason text. Because a mid-peak top-up is never dearer than running out, the old
0.3 kWh tolerance is gone: any shortfall below the peak margin starts a top-up (still
timed to finish at peak start), and a running top-up continues until it is 0.2 kWh past
the need. The daily scorecard records `handover_at`, `handover_period` and
`handover_cost_kwh` when the gauge first touches the floor inside the rate window.
Nothing changes at night or in peak.

**Staleness check** (option `stale_minutes`, default 20, 0 = off). The runtime notes
when the gauge (or SOC sensor) and each power sensor last changed value. If none has
changed for `stale_minutes`, the readings count as missing: nothing is learned, the last
gauge reading is not bridged, inverter verification pauses, and the planner uses its
no-gauge rules (night: charge to full; mid-peak: stay on battery, but finish a top-up
already running; peak: never charge). One notification when it starts and one when the
readings move again; `stale_minutes` is added to the daily scorecard and
`battery_data_stale` to the `Learned Plan` sensor. The classic planner, while the
readings are frozen, may start a charge but never stops one or releases a hold. Needs
the load or grid power sensor; a hold can keep the gauge still for hours, so the gauge
alone is not used.

*An idle system is not frozen (0.8.1).* When every configured power sensor reads 10 W or
less, nothing is moving through the inverter and the readings sit exactly still, so
the timer restarts instead of running. The first version assumed the AC500 readings
change every few seconds; on 2026-11-23 the minute log showed otherwise: a full bank
overnight, and again in mid-peak, read 0 W on every power sensor for stretches of 36 to
173 min while the pack voltages kept moving, and the check called all of it frozen
(alerts, no learning, night falling back to charging, and a Poor health grade). A feed stuck
on a non-zero value is still caught. A feed that freezes while the system is idle is not:
nothing is moving for the planner to miss, and the inverter's own SOC Low is the
backstop if something starts.

**After a restart.** The classic planner's first calculation may start a charge but
never stops one or releases a hold (0.7.1 fired nothing at all, which skipped a needed
top-up after a mid-peak restart). The learned runtime, when no command younger than 90
minutes was restored, reads the inverter's current mode from the power sensors (grid
well above load: charging; grid about equal to load: hold; no grid: on battery) and
continues from there, so its hysteresis keeps a hold. Its first acting tick fires only a
charge; anything else waits a tick, and a mode it cannot read is adopted without an
event (verification then checks it). `bank_full` is saved with the rest of the state.
Handing control back to classic and later to learned starts the same way.

**Third-party packs** (optional; options `pack_current_entities`,
`pack_current_charge_positive`, `bus_voltage_entity`, `pack_capacity_ah`,
`capacity_v_high`, `capacity_v_low`). Code: `packs.py`. For packs the inverter does not
manage, give one current sensor per pack. After a restart two sensors per pack appear:

- `<pack> Charge Estimate` (%): amp-hours out of the pack since the last full anchor
  (the inverter's gauge reaching 100 %), against the rated capacity. Attributes show
  the amp-hours, the anchor time, minutes of missing current data and the pack's own
  BMS percent for comparison. Unknown until the first anchor. Charging back after the
  anchor counts, up to full.
- `<pack> Ah Between 53.0 And 51.5 V` (Ah): on each discharge that starts from a full
  anchor, the amp-hours the pack delivered while the bus fell from the upper to the
  lower voltage, plus the AC energy and mean load over the same stretch. One point per
  anchor; a crossing must hold for 3 minutes. A recharge, more than 2 Ah of charging, a
  gap of more than 10 minutes in any pack's current, or a restart longer than 5 minutes
  discards the run. The attribute `history` lists the last 30 points; long-term
  statistics give the chart over months. A slow fall is capacity loss; a step is a
  pack or wiring problem. The voltages are under load, so compare runs of similar
  `mean_kw`.

The bus voltage is the configured sensor, else the mean of the packs' own `..._voltage`
sensors; the BMS percent is found the same way (`..._battery`, `..._soc`). Currents are
taken as positive into the pack (bms_ble's convention); turn the option off for packs
that report discharge as positive. State is saved with the learned model, so a short
restart keeps the count.

Replayed on the 2026-11-21 run-down (recorder history, offline): anchor at the gauge's
flip to 100 %, one run of 10.3 h between 53.0 and 51.5 V with 74-79 Ah per pack and
16.5 kWh AC at 1.6 kW; at the handover the estimates read 16-21 % while the BMS
counters read 3-24 %.

## 0.8.1 additions

**Startup guards (the classic planner).** On 2026-11-22 the first 0.8.0 restart started a
grid charge for a few seconds. The AC500 gauge went unknown for about 3 s while HA
loaded, and `sensor.available_battery_kwh` (a template helper that defaulted to 0)
showed a numeric 0.0 for that window. The first calculation read an empty battery and
wanted a 4.1 kWh charge, `charge_start` went out, and when the sensor loaded the
target-reached listener sent `charge_stop`. The calculation had also run on a Sunday
although weekdays-only is on. Two fixes sit on either side of the integration. On the
box (2026-11-22) the helper now has the availability template
`{{ is_number(states('sensor.ac500_total_battery_percent')) }}`, so an unknown gauge makes
it unavailable instead of 0. In the code, three rules apply:

- A battery reading that is unavailable, unknown, empty or not a finite number (or an
  entity that does not exist yet) is missing, not 0 kWh. The classic calculation is then
  skipped and nothing fires; the sensors keep their last values (unknown before the
  first calculation), and one warning is logged per gap. Setup does not fail over it:
  the learned planner is the one in control and does not use this sensor, so a failed
  first refresh would have kept it from starting. An empty solar forecast is treated the
  same way. When a battery reading comes back, the listener asks for a recalculation
  (still the restricted first one after a start) instead of waiting for the next
  scheduled run. The battery and checkpoint listeners ignore missing readings too, so
  they can no longer "reach the target" or pull the day's minimum to 0, and a charge
  target that was never calculated is never "reached". A numeric 0.0 is still a reading,
  which is why the next rule exists.
- The first calculation after a start that wants a charge does not act on it. It
  schedules a second calculation `STARTUP_CONFIRM_SECONDS` (60) later and records no
  prediction snapshot. That second look may start the charge, but, like the first, never
  stops one or releases a hold; later calculations act as before. The learned planner is
  not delayed (it reads the inverter's own gauge).
- Weekdays only is honoured by every refresh, not just the scheduled ones: on a weekend
  the setup refresh, the Recalculate button and the service update the sensors and fire
  nothing, record nothing and score nothing. A weekend start still counts as the first
  calculation, so Monday's 03:00 run is not restricted.

**Daily health check** (`health.py`; pure functions). The old daily grade scores the
classic planner's own predictions, so under the learned planner it grades a plan nobody
follows. The day is now graded from what the meters saw, using the learned runtime's
daily summary (so it needs the grid and load power sensors; without them the old grade
notification is kept). First thresholds, constants in `health.py`; where a reading sits
exactly on a boundary the worse grade wins:

| | Good | Fair | Poor |
|---|---|---|---|
| Grid kWh in peak | under 0.2 | exactly 0.2 | over 0.2 |
| Grid kWh in mid-peak | under 0.5 | 0.5 or more | - |
| Handover (gauge hit the floor in the rate window) | none | any | - |
| Longest frozen-data stretch (an idle system is not frozen) | 30 min or less | over 30 | over 60 |
| Inverter commands | all followed | - | one ignored after retries |
| Gauge at peak end vs predicted | within 10 points | off by more | - |

The grade is the worst row. "Grid kWh" is energy through the inverter's AC input in that
price window, so a handover and a mid-peak top-up both show up; dollars are those two
figures at the PGE Time of Day prices (constants: 16.70 and 43.13 cents). The scorecard
gets a new `health` field (date, grade, reasons, grid kWh, dollars, gauge at peak end,
predicted gauge, signed error `predicted - actual`, longest frozen stretch, commands not
followed); the old grade fields stay and the store schema is unchanged. The learned
summary gained `stale_longest_min`, `command_retries` and `commands_not_followed` to feed
it. Weekends are not graded (the scoring timer skips them); holidays follow with
ROADMAP item 7. A day with no grid readings and no frozen data is not graded and sends
nothing.

**Health sensor** (`Solarseed Peak Shaver Health`): `good`, `watch` or `review` over the
last 7 graded days, unknown until the first. Review when any of the 7 was Poor, or the
last 3 were all not Good, or the peak-end prediction was off the same way by more than
8 points on average (needs 5 days with a prediction). Watch when there is a Fair day but
no reason to review. Attributes: days graded, counts, the average bias, the reasons for a
review and the 7 `health` records.

**Notifications.** The daily message replaces the grade, one or two lines, ASCII, only on
graded days: `Solarseed Daily Report - Good`, then for example "peak on battery, ended at
12 % (predicted 9 %), $0.00 at mid-peak and peak prices." and "Last 7 weekdays: 6 good,
1 fair." A day that went wrong names what happened ("peak bought 0.4 kWh, handover at
16:10, ..."). A second message, `Solarseed - review needed`, goes out once when health
changes to review, sent with the phone app's high-priority options (`ttl: 0`,
`priority: high`, time-sensitive); a notify service that rejects those keys gets the
plain message. A review session then follows the routine in `docs/tuning-log.md`.

## State that does not survive an HA restart

Prediction snapshots, SOC checkpoints, hourly solar actuals, charge events, daily min, and
`_charging_active` are all in memory. A restart mid-day produces a partial or skewed
scorecard (or none), and a restart mid-charge means the stop event never fires from the
integration (the inverter stays in grid-charge mode until the next recalculation).
