# Solarseed Peak Shaver — Verification Checklist

After updating to v0.6.0, use this checklist to confirm everything is working correctly.

---

## 1. Check the Integration Loaded

In HA, go to **Settings → Devices & Services → Solarseed Peak Shaver**. If it's there without errors, the code loaded cleanly. If it failed, you'd see a "Failed to set up" banner.

## 2. Confirm the 5 New Sensors Exist

Go to **Developer Tools → States** and filter for `sensor.solarseed_peak_shaver`. You should see these alongside the originals:

| Sensor | Purpose |
|--------|---------|
| `sensor.solarseed_peak_shaver_daily_grade` | Letter grade (A–F) for the day's performance |
| `sensor.solarseed_peak_shaver_solar_forecast_accuracy` | How close the solar forecast was to reality (%) |
| `sensor.solarseed_peak_shaver_effective_base_load` | Rolling 14-day average base load (kW) |
| `sensor.solarseed_peak_shaver_prediction_accuracy` | How close the predicted charge was to actual need (%) |
| `sensor.solarseed_peak_shaver_algorithm_score` | Numeric score (0–100) for the day |

> **Note:** These will show `unknown` initially — that's expected until the first peak window completes.

## 3. Confirm the New Services Exist

Go to **Developer Tools → Services** and search for `solarseed_peak_shaver`. You should see three services:

- `solarseed_peak_shaver.recalculate` — existed before
- `solarseed_peak_shaver.performance_report` — **new** (returns JSON scorecards)
- `solarseed_peak_shaver.export_history` — **new** (CSV export for analysis)

## 4. Watch for the First Daily Grade

After your next **complete peak window** (typically the evening peak), the integration will:

- Fire a `solarseed_peak_shaver_daily_score` event
- Send a persistent notification with the day's grade
- Populate the daily grade sensor

You can check for the event in **Developer Tools → Events** — listen for `solarseed_peak_shaver_daily_score`.

## 5. Verify Data Is Being Stored

After at least one peak cycle, call the `performance_report` service:

1. Go to **Developer Tools → Services**
2. Select `solarseed_peak_shaver.performance_report`
3. Click **Call Service**
4. The response should contain a JSON scorecard with the day's metrics

If it returns an empty list, scoring hasn't triggered yet (no peak window has completed since the update).

## 6. Optional: Configure Solar Actual Entity

If you haven't already, go to the integration's **Configure** options and set the **Solar Actual Entity** (your real-time solar production sensor). This enables the solar correction learning — without it, the algorithm can't compare forecast vs actual and won't improve its solar predictions over time.

---

## What "Working" Looks Like

- **After 1 day:** You should see a daily grade and score. The first few grades may be C or D as the algorithm has no history to learn from yet.
- **After 3–5 days:** Grades should stabilize. The solar correction factors and effective base load will start adjusting.
- **After 2 weeks:** The rolling averages are well-populated. You should see improvement trends if conditions are consistent.

> **Rule of thumb:** If everything is A+ from day one, something's probably not measuring correctly. The algorithm should have room to learn.
