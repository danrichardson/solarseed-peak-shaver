# Performance Tracking & Feedback Plan

## Goal

Quantify how well the peak shaver algorithm predicts when to charge (and when not to). Build a data collection layer, a daily scoring system, and a dynamic feedback loop that tunes the algorithm based on observed reality.

## Success / Failure Definitions

**Intentional off-peak window** (acceptable grid draw):
- Weekdays: 9 PM – 7 AM
- Weekends: all day

**Failures:**
1. **Mid-peak charge event** — the algorithm triggered grid charging during mid-peak (7 AM – 9 PM weekday) because it underestimated what was needed overnight
2. **Unnecessary off-peak charge** — the algorithm charged overnight but solar would have covered the day; we paid for grid power we didn't need
3. **Floor breach** — battery hit `min_safe_soc` during the rate window, meaning we were forced to draw peak-rate grid power
4. **Excess grid draw while battery has headroom** — grid power drawn when battery SOC is above the low threshold (inverter pulled grid instead of discharging)

**Exception:** Intentional 100% SOC calibration charges (flagged, not scored as failure).

---

## Phase 1: Data Capture Layer

**What:** Record predictions and actuals so we can compare them after each day.

### Task 1.1 — Add a prediction snapshot store

At each calculation run, persist a timestamped snapshot of the prediction:

```
{
  "timestamp": "2026-02-25T04:00:00",
  "run_type": "scheduled|forecast_update|manual",
  "current_soc_kwh": 12.5,
  "predicted_battery_at_midpeak": 10.1,
  "predicted_minimum_kwh": 3.8,
  "target_soc_kwh": 12.5,
  "charge_needed_kwh": 0.0,
  "charge_below_kwh": 8.7,
  "hourly_solar_forecast": {7: 0.1, 8: 0.5, ...},  // predicted kWh per hour
  "base_load_used": 0.6,
  "charging_triggered": false
}
```

**Implementation:**
- New field on `PeakShaverCoordinator`: `prediction_snapshots: list[dict]` (keep today's runs)
- Populate at end of `_async_update_data()`, before returning `result`
- Expose latest snapshot as extra attributes on the Target SOC sensor

**Files:** `coordinator.py`, `sensor.py`

### Task 1.2 — Track actual solar production per hour

We need to compare predicted solar to actual solar. Two approaches (implement whichever is available):

**Option A — Solcast "actual" entity:** If the user has `sensor.solcast_pv_forecast_forecast_today` with `detailedHourly`, Solcast also typically provides an energy sensor or past actual data. Check for `sensor.solcast_pv_actual_*` or the `past` attribute.

**Option B — Derive from battery + grid:** If a grid power sensor is configured (new config option), actual solar = battery_delta + load_consumed - grid_draw. This is more complex but inverter-agnostic.

**Option C — Hourly solar energy sensor:** Many solar setups have a `sensor.solar_energy_today` or similar that reports cumulative production. Sample it hourly, diff to get hourly actuals.

For the MVP, track whichever is available. Add a new optional config field: `solar_actual_entity` (sensor reporting cumulative solar production in kWh). Sample it on the hour from `midpeak_start` through `peak_end` and store deltas.

**Implementation:**
- New config key: `CONF_SOLAR_ACTUAL_ENTITY` (optional)
- New hourly sampler in coordinator: `_track_hourly_solar_actual()`
- Register `async_track_time_change` for each hour in the rate window
- Store in `actual_solar_hourly: dict[int, float]` on coordinator

**Files:** `const.py`, `config_flow.py`, `coordinator.py`, `strings.json`, `translations/en.json`

### Task 1.3 — Track actual battery SOC at key moments

Record battery SOC at these timestamps daily:
- **Last calculation run** (already captured as `current_soc`)
- **Mid-peak start** (7 AM) — compare to `predicted_battery_at_midpeak`
- **Peak start** (5 PM)
- **Peak end** (9 PM)
- **Daily battery minimum** during mid-peak+peak window — compare to `predicted_minimum`

**Implementation:**
- New dict on coordinator: `actual_soc_checkpoints: dict[str, float]`
- Register time listeners at `midpeak_start`, `peak_start`, `peak_end` to sample battery SOC
- Track running minimum during rate window (update on every battery state change between `midpeak_start` and `peak_end`)

**Files:** `coordinator.py`

### Task 1.4 — Track grid charging events and timing

Record every charge_start and charge_stop event with timestamps and classify them:

```
{
  "charge_start_time": "2026-02-25T04:15:00",
  "charge_stop_time": "2026-02-25T05:42:00",
  "soc_at_start": 8.2,
  "soc_at_stop": 14.1,
  "energy_charged_kwh": 5.9,
  "period": "off-peak",          // off-peak | mid-peak | peak
  "was_necessary": null           // filled in by daily scoring
}
```

**Implementation:**
- New list on coordinator: `charge_events_today: list[dict]`
- Populate timestamps when `EVENT_CHARGE_START` / `EVENT_CHARGE_STOP` fire
- Classify period based on time of event vs rate schedule

**Files:** `coordinator.py`

---

## Phase 2: Daily Scorecard

**What:** At the end of each peak window (9 PM + 10 min), evaluate the day and produce a score.

### Task 2.1 — Create the daily scoring function

Run at `peak_end + 10 minutes` daily. Produce a scorecard:

```
{
  "date": "2026-02-25",
  "grade": "A",                    // A/B/C/D/F
  "score": 92,                     // 0-100

  // Prediction accuracy
  "solar_predicted_kwh": 18.5,
  "solar_actual_kwh": 16.2,
  "solar_accuracy_pct": 87.6,      // actual/predicted * 100

  "battery_at_midpeak_predicted": 10.1,
  "battery_at_midpeak_actual": 9.8,
  "midpeak_prediction_error_kwh": 0.3,

  "battery_min_predicted": 3.8,
  "battery_min_actual": 4.5,
  "min_prediction_error_kwh": -0.7,  // negative = conservative (good)

  // Outcomes
  "floor_breached": false,
  "midpeak_charge_triggered": false,
  "unnecessary_charge_kwh": 0.0,    // energy charged that wasn't needed
  "charge_events": [...],

  // Base load
  "effective_base_load_kwh": 0.55,  // derived from actual consumption
}
```

**Scoring rubric:**
| Criterion | Points | Deduction |
|-----------|--------|-----------|
| No floor breach | 30 | -30 if breached |
| No mid-peak charging | 25 | -25 if triggered |
| Solar forecast within 20% | 15 | -1 per % over 20% |
| Battery min prediction within 2 kWh | 15 | -1 per 0.5 kWh over |
| No unnecessary charging (>2 kWh excess) | 15 | -1 per kWh over 2 |

Grades: A (90-100), B (80-89), C (70-79), D (60-69), F (<60)

**Implementation:**
- New method: `_score_daily_performance()` on coordinator
- New time listener at `peak_end + 10 min`
- Store result as `last_daily_scorecard: dict` on coordinator

**Files:** `coordinator.py`

### Task 2.2 — Daily scorecard sensor

Expose the scorecard as a sensor with attributes:

- **Primary value:** letter grade (A/B/C/D/F)
- **Attributes:** all scorecard fields
- **New sensor key:** `SENSOR_DAILY_GRADE`

**Files:** `const.py`, `sensor.py`

### Task 2.3 — Persist daily history

Store the last N days of scorecards (default 30) in a JSON file: `.storage/solarseed_peak_shaver_history.json`

Use HA's `Store` helper for atomic writes. Structure:

```json
{
  "version": 1,
  "days": [
    {"date": "2026-02-25", "grade": "A", "score": 92, ...},
    {"date": "2026-02-24", "grade": "B", "score": 84, ...}
  ],
  "rolling_solar_accuracy": 0.91,
  "rolling_base_load": 0.58
}
```

**Implementation:**
- New file: `store.py` — wrapper around `homeassistant.helpers.storage.Store`
- Load on coordinator init, save after each daily scoring
- Expose rolling averages as coordinator properties

**Files:** `store.py` (new), `coordinator.py`

---

## Phase 3: Accuracy Tracking Sensors

**What:** Dedicated sensors that show how well the algorithm is doing over time.

### Task 3.1 — Solar forecast accuracy sensor

- **Value:** rolling 7-day solar accuracy percentage (actual / predicted × 100)
- **Attributes:** today's accuracy, 7-day, 30-day, per-hour breakdown
- **Key:** `SENSOR_SOLAR_ACCURACY`

### Task 3.2 — Base load accuracy sensor

- **Value:** rolling 7-day effective base load (kW)
- **Attributes:** configured base load, actual, delta, trend
- **Key:** `SENSOR_EFFECTIVE_BASE_LOAD`

### Task 3.3 — Prediction accuracy sensor

- **Value:** rolling 7-day battery minimum prediction error (kWh)
- **Attributes:** mean error, std dev, bias direction (optimistic vs conservative)
- **Key:** `SENSOR_PREDICTION_ACCURACY`

### Task 3.4 — Algorithm score sensor

- **Value:** rolling 7-day average score (0-100)
- **Attributes:** last 7 grades, streak info, worst recent day
- **Key:** `SENSOR_ROLLING_SCORE`

**Files:** `const.py`, `sensor.py`

---

## Phase 4: Feedback Loop

**What:** Use captured data to dynamically adjust the algorithm's inputs.

### Task 4.1 — Solar correction factor

The most impactful feedback. If solar consistently comes in at 85% of forecast, apply a 0.85 multiplier.

**Implementation:**
- New coordinator property: `solar_correction_factor` — rolling 14-day ratio of actual/predicted solar
- Apply in `_async_update_data()` when reading hourly solar:
  ```python
  solar_kwh = hourly_solar.get(hour, 0.0) * self.solar_correction_factor
  ```
- Clamp between 0.5 and 1.2 (don't over-correct)
- Log when correction factor deviates significantly from 1.0
- Expose as sensor attribute on Solar Accuracy sensor

**Files:** `coordinator.py`, `store.py`

### Task 4.2 — Dynamic base load

If the actual effective base load is consistently different from configured, use the rolling average instead.

**Implementation:**
- New coordinator property: `effective_base_load` — rolling 14-day average
- Falls back to configured `base_load_kw` if insufficient data (<3 days)
- Used in simulation instead of raw config value
- Log when effective differs from configured by >20%

**Files:** `coordinator.py`, `store.py`

### Task 4.3 — Conservative bias adjustment

The notes say the algorithm triggers mid-peak charging too often. Track the "margin" — how far above the floor the actual minimum was. If we're consistently 3+ kWh above floor, the algorithm is too conservative.

**Implementation:**
- Track `margin = actual_min - min_safe_soc` in daily scorecard
- Rolling average of margin over 14 days
- If rolling_margin > 2.0 kWh for 7+ days: log advisory "Algorithm is conservative by {margin} kWh on average"
- Future: auto-adjust `min_safe_soc` downward within safe bounds (config option to enable/disable auto-tuning)

**Files:** `coordinator.py`, `store.py`

### Task 4.4 — Per-hour solar accuracy tracking

Solar forecasts are often wrong at specific hours (mornings underestimated due to panel angle, afternoons overestimated due to clouds). Track accuracy per hour.

**Implementation:**
- In the history store, maintain `hourly_solar_accuracy: dict[int, float]` — rolling ratio per hour
- Apply per-hour correction factors instead of a single global factor
- Requires >7 days of per-hour data before activating

**Files:** `coordinator.py`, `store.py`

---

## Phase 5: Reporting & Observability

### Task 5.1 — Diagnostics enhancement

Add to the existing diagnostics output:
- Last 7 daily scorecards
- Rolling correction factors
- Prediction vs actual comparison for today

**Files:** `diagnostics.py`

### Task 5.2 — Daily summary notification

If notifications are enabled, send a daily summary at `peak_end + 15 min`:

> **Solarseed Daily Report — Grade: A (92/100)**
> Solar: 16.2 kWh actual vs 18.5 kWh predicted (88%)
> Battery min: 4.5 kWh (predicted 3.8, floor 1.5)
> No charging triggered today.
> Solar correction factor: 0.91

**Files:** `coordinator.py`

### Task 5.3 — Service: get performance report

New service: `solarseed_peak_shaver.performance_report` — returns the last N days of scorecards as a formatted response. Useful for debugging and dashboard text cards.

**Files:** `services.yaml`, `coordinator.py`, `__init__.py`, `strings.json`

---

## Implementation Order

The tasks are designed as independent, digestible chunks. Here's the recommended order, grouped into sprints:

### Sprint 1: Foundation (capture data)
1. **Task 1.1** — Prediction snapshot store
2. **Task 1.3** — Actual SOC checkpoints
3. **Task 1.4** — Charge event tracking
4. **Task 1.2** — Actual solar tracking (new config option)

### Sprint 2: Scoring (evaluate performance)
5. **Task 2.1** — Daily scoring function
6. **Task 2.3** — Persistent history store
7. **Task 2.2** — Daily grade sensor

### Sprint 3: Visibility (show the data)
8. **Task 3.1** — Solar accuracy sensor
9. **Task 3.2** — Base load accuracy sensor
10. **Task 3.3** — Prediction accuracy sensor
11. **Task 3.4** — Rolling score sensor

### Sprint 4: Feedback (close the loop)
12. **Task 4.1** — Solar correction factor
13. **Task 4.2** — Dynamic base load
14. **Task 4.3** — Conservative bias adjustment
15. **Task 4.4** — Per-hour solar accuracy

### Sprint 5: Polish (reporting)
16. **Task 5.1** — Enhanced diagnostics
17. **Task 5.2** — Daily summary notification
18. **Task 5.3** — Performance report service

---

## Data Flow Diagram

```
                    ┌─────────────────────┐
                    │   Solar Forecast     │
                    │   (Solcast / FS)     │
                    └────────┬────────────┘
                             │
                    ┌────────▼────────────┐
                    │  _async_update_data  │ ◄── Scheduled / forecast update
                    │  (core algorithm)    │
                    └────────┬────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
    ┌─────────▼──────┐ ┌────▼─────┐ ┌──────▼──────┐
    │  Prediction    │ │  Events  │ │  Sensors    │
    │  Snapshot      │ │  fired   │ │  updated    │
    │  (Task 1.1)    │ │          │ │             │
    └─────────┬──────┘ └────┬─────┘ └─────────────┘
              │              │
              │    ┌─────────▼──────────┐
              │    │  Charge Event Log  │
              │    │  (Task 1.4)        │
              │    └─────────┬──────────┘
              │              │
    ┌─────────▼──────────────▼──────────┐
    │                                    │
    │  Throughout the day:               │
    │  - SOC checkpoints (Task 1.3)     │
    │  - Actual solar samples (Task 1.2)│
    │                                    │
    └─────────────────┬──────────────────┘
                      │
             9:10 PM  │
                      │
            ┌─────────▼──────────┐
            │  Daily Scoring     │
            │  (Task 2.1)        │
            │                    │
            │  Compare predicted │
            │  vs actual         │
            └─────────┬──────────┘
                      │
         ┌────────────┼────────────┐
         │            │            │
   ┌─────▼────┐ ┌────▼─────┐ ┌───▼──────────┐
   │ Grade    │ │ History  │ │ Notification │
   │ Sensor   │ │ Store    │ │ (Task 5.2)   │
   │(Task 2.2)│ │(Task 2.3)│ │              │
   └──────────┘ └────┬─────┘ └──────────────┘
                     │
            ┌────────▼────────────┐
            │  Rolling Averages   │
            │  - Solar accuracy   │
            │  - Base load        │
            │  - Margin bias      │
            └────────┬────────────┘
                     │
            ┌────────▼────────────┐
            │  Correction Factors │
            │  (Phase 4)          │
            │                     │
            │  Fed back into      │
            │  _async_update_data │
            └─────────────────────┘
```

---

## Notes & Constraints

- **No external dependencies.** Everything uses HA's built-in helpers (Store, event bus, state machine).
- **Graceful degradation.** If `solar_actual_entity` isn't configured, skip solar accuracy tracking but still score on outcomes (floor breach, mid-peak charging).
- **SOC calibration charges.** Add a boolean `input_boolean` or button to flag "this is a calibration charge — don't score it." Unlikely with hacked batteries but keeps scoring fair.
- **Storage limits.** Keep 90 days max. Prune on daily write.
- **Performance.** All sampling is event-driven or time-triggered — no polling loops. The daily scoring function runs once at 9:10 PM.
- **Backward compatible.** All new config fields are optional with sensible defaults. Existing installs get scoring based on outcomes only until they configure `solar_actual_entity`.

---

## Phase 6: Long-Term Statistical Analysis (SPC)

**Added post-implementation.** This phase provides tooling for offline analysis
using Statistical Process Control methodology — treating the charge decision as
a manufacturing process where "defects" are floor breaches (under-charge) or
wasted energy (over-charge).

### Asymmetric Cost Model

The core insight: under-charging and over-charging are **not equally bad**.

| Error direction | Cost per kWh | Why |
|---|---|---|
| Under-charge (floor breach → peak grid draw) | $0.44 | Full peak rate |
| Over-charge (wasted round-trip loss) | ~$0.10 | Off-peak rate × (1 + 15% loss) |

**Cost ratio: 4.25:1** — under-charging is 4.25× more expensive per kWh.
The optimal strategy is therefore slightly conservative (overcharge by a small margin).

### 6.1 — CSV Export Service

**Service:** `solarseed_peak_shaver.export_history`

Two export formats:

1. **daily** — One row per day, 21 columns including derived SPC columns
   (`charge_surplus_kwh`, `margin_above_floor_kwh`)
2. **hourly_solar** — One row per day per hour (predicted vs actual with error and ratio)

Usage in Developer Tools → Services:

```yaml
service: solarseed_peak_shaver.export_history
data:
  format: daily
  days: 30  # optional, omit for all data
```

**Files:** `const.py`, `store.py`, `__init__.py`, `services.yaml`

### 6.2 — SPC Analysis Script

**File:** `tools/analyze_performance.py`

Standalone Python script (stdlib only, no pip dependencies required) that reads
exported CSV and produces:

- **Control charts** (Individuals I-chart) for margin, score, and prediction error
  with UCL/LCL/mean and out-of-control point detection
- **Process capability (Cpk)** for margin-above-floor (LSL=0, USL=5) and
  algorithm score (LSL=60)
- **Asymmetric cost analysis** — total undercharge cost, overcharge cost,
  daily average, monthly projection, and optimal bias recommendation
- **Solar forecast analysis** — daily bias/variance/skewness, per-hour error
  distribution, worst hours, recommended correction factors
- **Base load stability** — mean, variance, coefficient of variation
- **Trend detection** — run tests for improving/deteriorating drift
- **Actionable recommendations** — quantitative parameter change suggestions

Optional matplotlib support for generating PNG charts (control chart, score
timeline, cost breakdown).

```bash
python tools/analyze_performance.py daily.csv
python tools/analyze_performance.py daily.csv --hourly hourly_solar.csv
python tools/analyze_performance.py daily.csv --json
python tools/analyze_performance.py daily.csv --charts output/
```

### 6.3 — Claude Analysis Prompt Template

**File:** `tools/claude_analysis_prompt.md`

Four structured prompt templates for feeding CSV data to Claude:

1. **Full Analysis** — comprehensive SPC review with control charts, Cpk,
   cost analysis, per-hour solar corrections, and parameter recommendations
2. **Quick Check** — focused margin optimization prompt
3. **Solar Forecast Tuning** — per-hour correction factor analysis
4. **Iterative Feedback** — before/after comparison when tracking improvements

### Workflow

```
HA Integration                     Offline Analysis
─────────────                     ────────────────
Daily scorecards     ──export──►  daily.csv
Hourly solar data    ──export──►  hourly_solar.csv
                                       │
                                       ├──► analyze_performance.py
                                       │    (local SPC report)
                                       │
                                       └──► Claude prompt template
                                            (AI-assisted analysis)
                                                    │
                                                    ▼
                                         Parameter recommendations
                                           (min_safe_soc, base_load,
                                            correction factors)
                                                    │
                                                    ▼
                                         Update HA config / options
```

