# How the Peak Shaver Actually Works (v0.6.0)

Reverse-engineered from the code on 2026-11-05. The README describes intent; this
describes behavior. Line refs are to `custom_components/solarseed_peak_shaver/coordinator.py`.

The sections up to "Learned planner (0.7.0)" describe the **classic planner, legacy from
0.9.3**: selectable, still computing beside the learned planner, no new features. A new
install with the house load and grid sensors starts on the learned planner ("0.9.3
additions").

## Rate model

Three hard-coded tiers, hour boundaries from config (defaults = PGE Time of Day):

| Period | Hours (weekdays) | README rate |
|---|---|---|
| Off-peak | 21:00 - 07:00, all weekend | $0.09 |
| Mid-peak | 07:00 - 17:00 | $0.18 |
| Peak | 17:00 - 21:00 | $0.44 |

Rates themselves are not in the integration; only `tools/analyze_performance.py` hard-codes
them (plus a 15% round-trip loss). Holidays are not handled. (Since 0.8.2 holidays are, and
since 0.9.1 the tariff with its prices is data; see "0.9.1 additions".)

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

## 0.8.2 additions

**Utility holidays.** `holidays.py` (pure Python) holds the one function that says whether
a date is a TOU day: `is_tou_day(date, weekdays_only, holiday_preset)`. The coordinator
wraps it as `coord.is_tou_day(date)`, and every caller goes through it: the classic
planner's timers (scheduled calculation, forecast update, off-peak hold, SOC
checkpoints, daily scoring) and the refresh at setup; the learned planner's today and
tomorrow, the price window it books grid energy under, the handover record and the load
profile (live and backfill). Nothing else in the integration looks at the day of the week.

A holiday is handled like a weekend day: the evening before it is not a pre-TOU night (no
charge for it), the day itself is off-peak all day (no mid-peak or peak window, grid
energy booked as off-peak), it is not scored, graded or messaged, and its load goes into
the learner's "other days" history. On the holiday evening the night rule plans the next
TOU day's charge as usual.

The option `holiday_preset` has two values. `pge` (the default, also when the key is
absent from an entry saved by an older version) is PGE Time of Day: New Year's Day,
Memorial Day (last Monday in May), Independence Day, Labor Day (first Monday in
September), Thanksgiving (fourth Thursday in November) and Christmas Day, with a
Saturday holiday observed on the Friday before and a Sunday one on the Monday after. The
rules are data (fixed date, nth or last weekday of a month, observed-day shift) and
computed for any year; the shift can cross New Year (2028-01-01 is observed on Friday
2027-12-31). `none` is the old behaviour. The preset applies whether or not weekdays-only
is on. The Learned Plan sensor shows `holiday_preset`, `holiday_today` and
`holiday_tomorrow` (the holiday's name, or null) and `next_holiday` ("2026-11-26
Thanksgiving").

**Weekly top-up.** It is owed from peak end on the last TOU day of a Monday-to-Sunday
week: a TOU day followed by a non-TOU day with no TOU day left in the week. Before 0.8.2
it was any TOU day followed by a non-TOU day, which with holidays would have charged to
full on the evening before a mid-week holiday as well as on Friday. A Friday holiday makes
Thursday the last TOU day.

**Hold at full is "cannot tell".** On 2026-11-23 a charge ended at 100 %, the planner
sent hold, and for about 30 minutes the AC500 carried the house from the battery (AC in
0 W, AC out 0.5 to 0.7 kW) until the gauge fell to 99 % and it passed the grid through.
The verification wanted grid near the load, called it "not in hold", resent the command
three times and logged an error. `mode_matches(hold)` now returns None (no resend, no
alert, no `commands_not_followed`) while the bank is full, the gauge is 99 % or more, or
the gauge is missing. `infer_mode`, used on the first tick after a restart when no
command was restored, had the same blind spot: at 99 % or more (or no gauge) with no grid
input it now says None instead of "discharge", so the first decision (hold at full) is
adopted rather than a discharge that would have run the battery down overnight.

## 0.9.0 additions

**Options as a menu.** `Configure` opens a menu of six sections: Battery and sensors,
Schedule, Learned planner, Third-party packs, Notifications, Classic planner (legacy). The
keys in each are listed in `options.py` (`SECTIONS`); every option key is in exactly one.
Saving a section stores the existing options with that section's fields replaced, so keys
of other sections, and keys no form shows, are kept (the 0.8.x form saved wholesale and
dropped anything it did not show). An optional sensor cleared in the form is stored as
empty rather than left out, because an absent option falls back to the setup data. The
battery SOC sensor and today's solar forecast, set only at setup before, are now in
Battery and sensors. The Schedule section checks that mid-peak start, peak start and peak
end are in order. No key was renamed; an entry saved by 0.8.x reads the same values.

**Settings on the device page.** Two selects and four numbers, each one stored option
(the config entry's options remain the only store): `Planner` (classic or learned),
`Utility holidays` (the holiday preset), `Peak margin`, `Load quantile`, `Solar
confidence` and `Gauge floor`, with the form's ranges. Changing one writes that option and
nothing else. They take effect without a restart: the coordinator reads options live and
the learned planner reads them on every minute, so a new value is used on the next minute.
Switching the planner follows the handover rules that already applied (to learned: the
first acting tick reads the inverter's mode and may only start a charge; to classic: a
charge or hold is returned to battery).

**When a save reloads.** There was no update listener before 0.9.0: anything read live
took effect at once and anything read at start waited for the next restart. Now a listener
compares the settings read once at start (`options.RELOAD_KEYS`: the battery SOC, forecast
and production sensors, the three hours, the calculation hours, the off-peak hold switch,
the pack sensors) with what the entry started with, in the integration's own reading (the
hours as a list and as text are the same). If one changed the entry is reloaded, which is
an integration restart with the usual restart rules; otherwise the entities are refreshed
and nothing restarts. The six device-page settings are never in that list, so they never
reload: the learned runtime, its first-tick restriction and its verification counters keep
running.

**Events after the 21:10 scoring.** The day is scored at 21:10 and the learned runtime's
day ends at midnight, so before 0.9.0 an ignored command or a frozen stretch between the
two fell in no graded day (the false alarm of 2026-11-23 was one). Now the scoring records
the day's counters (`command_retries`, `commands_not_followed`, `stale_minutes`, the
longest frozen stretch) as they stand, and at midnight whatever they gained since is kept
as a late event with its date and the scoring time. The next graded day's summary carries
the late events under a new key `late_events`; today's counters keep their meaning. The
health grade counts them like today's (an ignored command is Poor, a frozen stretch over
30 or 60 minutes Fair or Poor), with the date in the reason ("inverter ignored a command
late on 11-27"), and the health record lists them under `late_events`. They are cleared
once a scoring has graded a day with them, and kept if the next scoring has nothing to
grade. A day that was not scored (a weekend, a holiday) carries nothing: those days stay
ungraded. The record survives a restart, including one over midnight. At most 14 are kept.

## 0.9.1 additions

**The tariff is data.** `tariff.py` (pure Python) describes when electricity costs what:

- three named periods with a price per kWh: off-peak (cheap), mid-peak (middle), peak
  (dear). They are the planner's three windows, and every tariff is mapped onto them;
- the hours of a TOU day: mid-peak from `midpeak_start_hour` to `peak_start_hour`, peak
  from there to `peak_end_hour`, off-peak the rest. These are the three hour options of
  every earlier version, kept as the base hours. Mid-peak start equal to peak start means
  no mid-peak window: a two-price plan (off-peak and peak);
- day types: on a weekday the windows apply; on a weekend they apply only when
  weekdays-only is off, with the weekend's own hours and prices when a `weekend:` line
  gives them (else the weekday's); a holiday is off-peak all day (`holidays.day_type`);
- optional seasons: for some months, other hours, other prices, or both. A season never
  changes the planner's rules, only the hours and prices it works with;
- the holiday calendar.

With no tariff option stored, the tariff is PGE Time of Day exactly as 0.9.0 assumed it
(hours 7, 17, 21, weekdays only, the PGE holidays, mid-peak $0.1670 and peak $0.4313, and
off-peak unpriced); `tests/test_tariff.py` compares period and price for every hour of three
sample weeks (Thanksgiving 2026, 2027-07-05 observed, 2027-12-31 observed) with a frozen
copy of the 0.9.0 rules. An entry with only the three hour keys works unchanged.

**Options.** The Schedule section of the menu is now Tariff: the three hours, weekdays
only, the three prices (`offpeak_price` optional, `midpeak_price`, `peak_price`), seasons
(`tariff_seasons`), the holiday preset, the holiday rules (`holiday_rules`) and one-off
holidays (`holiday_dates`). Seasons are typed one per line, a name optional:
`Summer 06-09: mid-peak 7-15, peak 15-20 0.52, mid-peak 0.20`. Months are one month or a
range (`11-02` wraps the year); each item is a period with hours, a price, or both; hours
replace the day's windows (peak must be given, mid-peak must end where peak starts); a
season with prices only keeps the base hours. A line `weekend: peak 16-21 0.30` (the same
items, no months) gives weekend days their own hours and/or prices in every month, on top
of the season's; it needs weekdays-only off, and the form says so otherwise. Peak ends by
23:00: a peak ending at midnight would put the daily scoring and the peak-end checkpoint
at 00:xx on the next date, after the day's counters reset.

**Refused, not half-supported.** A tariff that does not fit the planner's cheap, middle,
dear day is refused in the form with the reason: two peak (or mid-peak) windows in a day, a
gap between mid-peak and peak or mid-peak after peak, a window across midnight, hours for
off-peak, a month in two seasons, and prices that do not rise from off-peak to mid-peak to
peak (the planner's rule that any predicted peak shortfall is worth a mid-peak top-up relies
on it; the mid-peak price does not count when there is no mid-peak window), a weekend line
with weekdays-only on, and a peak end of 24. A season that no longer parses in a hand-edited
entry is left out (its months use the base), never half-applied.

**Holidays as typed rules.** `holiday_preset` now has four values: `none`, `pge` (the
default, also when absent), `us_federal` (the eleven federal holidays) and `custom`. The
rules field shows the rules in force: one per line, `01-01 New Year's Day` (a fixed date),
`11-thu-4 Thanksgiving` (the nth weekday, 1 to 5), `05-mon-last Memorial Day` (the last
one), and `sat->fri, sun->mon` (move a fixed date that falls on a weekend). The name is
optional. Choosing a preset fills the field with its rules on save; editing the rules
under a preset makes it `custom`; a rule that is not understood is refused with the
reason. One-off holidays (`2026-12-24 Christmas Eve`) are a separate field, kept whatever
the preset, never shifted. The device-page select offers all four presets; choosing
`custom` there uses the stored rules (none stored: only the one-off dates). Holidays,
prices and season months are read live; only hours need a reload.

**Hours by season.** `coord.windows_on(date)` gives the hours of that date's season, and
`coord.period_at(when)` the period with the day type. The learned runtime asks for the
hours of the date it is planning or booking (the planner's inputs, the grid energy per
period, the handover record, the gauge checkpoints, the weekly top-up); the classic planner
and the sensors use today's. The timers (SOC checkpoints, solar sampling, off-peak hold,
daily scoring) are set for the hours of every season and act only on the day's own, so a
season change needs no restart; a saved change to a season's hours reloads the entry
(`tariff_seasons` is in `RELOAD_KEYS`, compared by hours only). After today's peak end the
night rule plans for tomorrow with tomorrow's hours (`PlanInputs.next_midpeak_start`,
`next_peak_end`): the night a season changes, and every Friday night when the weekend has
its own hours, the charge is sized for tomorrow's window and timed to end at tomorrow's
mid-peak start. Today's own rules (peak, mid-peak) keep today's hours. The classic planner
still uses today's hours for its overnight projection (legacy, PGE has one set).

**Dollars from the tariff.** The health record's `cost_usd` is the day's mid-peak and peak
grid energy at that day's prices (its season's), with the prices used in a new `prices`
field; the meaning of `cost_usd` is unchanged, and so is the daily message ("$0.86 at
mid-peak and peak prices"). The Learned Plan sensor adds `tariff` ("PGE Time of Day" or
"Custom"), `season`, `day_type`, `price_windows` ("07-17 mid-peak, 17-21 peak" or
"off-peak all day"), `prices`, `price_period` and `price_now`, and in dollars at the day's
peak price `handover_cost_usd` (what touching the floor costs) and `shortfall_cost_usd`
(the predicted peak shortfall, when there is one). Diagnostics show the tariff as read.
Prices are in dollars; another currency is not supported.

## 0.9.2 additions

**The dashboard.** `dashboards/solarseed.yaml` is a whole dashboard to paste into the raw
configuration editor of a new dashboard (instructions at the top of the file). Stock cards
only, in one sections view (Home Assistant 2024.10 or later): heading, markdown, tile,
gauge, history-graph, statistics-graph, conditional and vertical-stack; no custom cards, no
custom panel. The entity ids are written once, in a `solarseed_ids` block at the top, and
used everywhere else through YAML anchors; the markdown cards carry the block and read it
as `config.ids`. Two ids are the user's to set: the battery gauge (an AC500's by default)
and the third-party packs' "Ah Between" sensors. It answers, in this order:

1. **Now:** the Plan Summary sentence, the planner's reason for what it is doing, the
   price period and price now, the tariff, and a warning while battery data is frozen;
   tiles for the Learned Plan's mode (named "Inverter mode asked for" while the learned
   planner is in control, "Shadow plan (not in control)" under classic) and the planner
   select.
2. **The next peak:** a gauge of the Peak End Forecast (hidden while it is unknown; no
   colour bands, since the floor is an option and the card beside it says covered or not), and
   whether that peak is covered: the expected gauge at peak end and the kWh above the
   floor, or that the floor is expected first; the energy above the floor now; what
   running short would cost (`shortfall_cost_usd`, `handover_cost_usd`); or why there is
   no forecast.
3. **The last seven days:** the Health tile and a table of the last seven graded days from
   the Health sensor's `last_7_days`: grade, grid kWh in peak and `cost_usd` (dollars from
   the health records, never from a constant in a card; a missing figure is a dash, not
   0), the counts and the week's total, why each day that was not Good was not, and the
   review reasons.
4. **Predicted against what happened:** a 7-day history graph of the battery gauge with the
   running Peak End Forecast (it moves through the day and turns to tomorrow's peak after
   peak end), and a table of each graded day's prediction made at mid-peak start
   (`pred_gauge_peak_end`) against the gauge at peak end, with the error and its average.
5. **Pack capacity:** shown only while the first pack's capacity sensor exists and has a
   reading (the frontend reads a missing entity as `unknown`, so the condition excludes
   both `unknown` and `unavailable`): a statistics graph (weekly mean, 180 days) of each
   pack's Ah per clean run-down.

`docs/dashboard.png` shows it with invented numbers. It is drawn by a local script, not
photographed in Home Assistant: the card order, options and markdown templates are the
file's own, rendered with Jinja against the real sensor classes' attributes; the look of
the stock cards is imitated. `tests/test_dashboard.py` checks the file: ASCII, stock card
types only, every id written once and used by alias, every integration id one the
integration creates, every attribute a template reads one the sensor has, and every
markdown template rendered (with jinja2, strict about undefined names) for a fresh install,
a short afternoon with a week of grades, a weekend, a covered night, frozen data, and old
health records without dollars or predictions.

**Plan Summary** (`sensor.solarseed_peak_shaver_plan_summary`, new): the plan in one plain
sentence, ASCII, at most 255 characters, from the learned planner's last decision and the
inputs it was made with (`outlook.plan_sentence`). For example "Today: on battery through
peak 17:00-21:00; expected to end peak at 17 % (2.3 kWh to spare).", "Peak is over for
today. Tomorrow (Wednesday): holding; the charge to 69 % starts about 6.6 h before 07:00;
expected to end peak at 10 % (1.1 kWh to spare).", "No peak prices today (Thanksgiving):
solar first, then battery. Tomorrow's charge is planned from 21:00." A predicted shortfall
in mid-peak is named with its price at the day's peak rate; with the classic planner in
control the sentence starts "Shadow plan (classic planner in control):". Unknown before the
first decision. Text, no state class, so no long-term statistics.

**Peak End Forecast** (`sensor.solarseed_peak_shaver_peak_end_forecast`, new, %,
measurement): the gauge expected at the end of the next peak window the planner has planned
for (`outlook.peak_outlook`). Today's window while it is ahead or running; tomorrow's once
the night rule plans for it (after today's peak end, or the evening before a TOU day). It is
the prediction the health record grades (`predict_gauge`, mean load, solar discounted by
the solar confidence), so at mid-peak start it equals that day's `pred_gauge_peak_end`. It
starts from where the plan will put the battery: the night target before mid-peak (the gauge
reached, when the bank is already full), the top-up target while a mid-peak top-up runs,
else the gauge now. Covered means the expected gauge stays more than half a point above the
floor. Attributes: `for` (today or tomorrow), `for_date`, `peak_window`, `from_hour`,
`from_gauge`, `spare_kwh`, `covered`, `assumes_charge`, `floor`, and `why_none`. Unknown,
never a guess, with no battery reading, before the model is trained, or with no peak
planned (a weekend afternoon, a holiday, a Friday evening); `why_none` says which. The
forecast uses the average evening; the charge is sized for a busier one (the load quantile)
plus the margin, so a forecast that clears the floor can sit beside a planned top-up.

Both sensors only read the planner's decision (the runtime keeps the `PlanInputs` of its
last decision as `last_inputs`); neither changes it, acts, or notifies. A failure in either
is logged at debug level and gives an unknown state, never an error in the state write.

**A non-finite reading is a missing one.** The learned runtime read a state of `nan` or
`inf` as a number; a `nan` gauge then failed every mid-peak tick (`int(nan)` in the top-up
sizing) and would have reached the failsafe after ten minutes. `_float_state` now returns
None for a non-finite value, as the coordinator's readers already did.

## 0.9.3 additions

**The first-time flow has four screens.** Battery and solar forecast (as before, with the
classic planner's minimum marked legacy); **Learned planner sensors** (new: gauge, house
load, grid, PV, tomorrow's forecast, all optional, each checked to exist, tomorrow's
suggested when today's Solcast sensor has a `tomorrow` twin); **Tariff** (was "Rate
Schedule"); Notifications. With both the load and the grid sensor the new entry's data gets
`planner: learned`; with neither, `planner: classic`; one without the other is refused
(`learned_needs_both`), since the learned planner samples only when both read. The default
for an absent `planner` key stays classic, so every entry made before 0.9.3 keeps the
planner it had; nothing is migrated. Empty sensor fields are not stored (absent reads as
not set, as before).

The Tariff screen shows the hours, Weekdays only, the three prices (off-peak optional) and
the holiday preset (None, PGE, US federal; Custom needs rules, so it is in the options
only), plus the classic planner's calculation hours. It is checked by `options.check_tariff`,
the Tariff options section's own check: mid-peak start not after peak start, peak start
before peak end, peak end by 23 (the selector stops at 23; 24 was allowed here until now and
scheduled the scoring and the peak-end checkpoint at 00:xx on the next date, so the day
was never graded), prices rising, with the reason in `{prices_detail}`. Only the screen's own
keys are stored: no holiday rules text (the preset's own rules are used) and no off-peak
price when left empty. Seasons, weekend hours, custom rules and one-off dates are set in the
options afterwards.

Every field of every form (the four first-time screens and the six options sections) has
a label and a description in both string files; an optional field's says what empty does,
a required sensor's starts "Required." `tests/test_first_install.py` holds both files to
that from the forms the flow actually builds. The classic planner's fields are labelled
"(classic planner, legacy)" wherever they appear.

**Setup check** (`setup_check.py`, new). Every ten minutes, and only once Home Assistant's
state is `running` (automations attach their triggers at start; slow integrations add
their sensors late), `find_problems` looks for:

- `missing_sensors`: a configured sensor (battery energy, forecast today and tomorrow,
  gauge, load, grid, PV, solar production) for which `hass.states.get` returns nothing,
  named with its form label; and, with the learned planner in control, the load or grid
  sensor not set. A sensor that exists but is `unavailable` or `unknown` is not a setup
  problem (startup, night): the planners already treat its reading as missing.
- `forecast_without_detail`: a forecast sensor that has a state but none of the attributes
  `_get_hourly_solar` reads (`detailedHourly`, `detailedForecast`, `forecasts`,
  `forecast`). Not judged while it is unavailable.
- `no_automations`: an event the planner in control fires with no listener on the event
  bus (`hass.bus.async_listeners()`, which counts each enabled automation's event
  trigger). The learned planner needs all three; the classic planner needs start and stop,
  and `preserve_start` only with its off-peak hold on. The integration listens to none of
  its own events, so a count above zero is someone else's. When the counts cannot be read
  the check is skipped, not guessed.

Each problem is a Home Assistant repair issue (`issue_registry`, not fixable, warning,
issue id `<key>_<entry_id>`, text under `issues` in the string files, a link to the README)
and one WARNING log line `Setup problem (<key>): ...`. Nothing repeats while the problem is
unchanged; a changed list updates the issue and logs once more; a fixed problem deletes the
issue and logs one INFO line. The first run after a start also deletes issues no longer
true from before the restart; removing the entry deletes its issues. It never notifies, never
acts and never fails the setup (a check that raises is logged once and the planners carry
on). Diagnostics gain `setup_problems`.

**Blueprints.** `source_url` is each file's own GitHub URL (it was the repository root,
which Home Assistant's re-import would have fetched as the blueprint), `homeassistant:
min_version: 2024.8.0` (the `action:` key in their steps), and each description says when
the learned and classic planners fire its event and names the AC500 value as an example:
`STANDARD` (charge from grid), `PV_PRIORITY` (solar, then battery) and `TIME_CONTROL`
(hold: grid carries the house, battery kept; as seen on the unit this was built with, and
depending on the time-control windows set in the Bluetti app). `tests/test_blueprints.py`
checks the structure, every `!input`, the event names, the URLs against the README, and
ASCII. The three tracked `*:Zone.Identifier` download markers are gone.

**Install requirements.** `hacs.json` asks for Home Assistant 2024.12.0 (it said 2024.1.0).
`PeakShaverOptionsFlow` subclasses the plain `OptionsFlow` and reads `self.config_entry`;
in core 2024.11.0 only `OptionsFlowWithConfigEntry` has that property, and the plain class
gains it in 2024.12.0 (`homeassistant/config_entries.py` at those tags), so on 2024.11 the
settings menu would fail to open. The test mocks set `config_entry` by hand, which is why
the suite cannot see this; `tests/test_integration_structure.py` now holds the minimum.
The README's "What you need" says so, and that the forecast must be Solcast's, that a
two-price plan holds on grid all day before peak start (never yet watched on an inverter),
and that `tools/analyze_performance.py` prices with its own fixed rates.

## State that does not survive an HA restart

Prediction snapshots, SOC checkpoints, hourly solar actuals, charge events, daily min, and
`_charging_active` are all in memory. A restart mid-day produces a partial or skewed
scorecard (or none), and a restart mid-charge means the stop event never fires from the
integration (the inverter stays in grid-charge mode until the next recalculation).
