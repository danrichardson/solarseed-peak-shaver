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

## State that does not survive an HA restart

Prediction snapshots, SOC checkpoints, hourly solar actuals, charge events, daily min, and
`_charging_active` are all in memory. A restart mid-day produces a partial or skewed
scorecard (or none), and a restart mid-charge means the stop event never fires from the
integration (the inverter stays in grid-charge mode until the next recalculation).
