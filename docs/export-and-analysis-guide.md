# Solarseed Peak Shaver — Export & Analysis Guide

How to get your data out of the integration and analyze it to understand (and improve) how well the peak shaving algorithm is performing.

---

## Step 1: Wait for Data

The performance tracking system needs at least one complete peak window to produce its first scorecard. After that, more data = better analysis:

| Data Volume | What You Can Learn |
|---|---|
| 1–3 days | Basic sanity check — is it tracking? |
| 7 days | First meaningful trends |
| 14+ days | Rolling averages are reliable, SPC analysis becomes useful |
| 30+ days | Seasonal patterns, long-term drift, robust Cpk indices |

---

## Step 2: Export Your Data

### Option A: From the HA UI

1. Go to **Developer Tools → Services**
2. Select **`solarseed_peak_shaver.export_history`**
3. Set parameters:
   - **Days**: Number of days to export (leave blank for all available, max 90)
   - **Format**: `daily` (default) or `hourly_solar`
4. Click **Call Service**
5. The CSV data appears in the service response — copy it and save to a `.csv` file

### Option B: From an Automation or Script

```yaml
service: solarseed_peak_shaver.export_history
data:
  days: 30
  format: daily
response_variable: csv_result
```

### What Each Format Contains

**`daily` format** — one row per day with columns:
- `date`, `grade`, `score`
- `charge_amount_kwh`, `predicted_need_kwh`, `base_load_kw`
- `solar_forecast_kwh`, `solar_actual_kwh`, `solar_accuracy`
- `soc_start`, `soc_end_peak`, `soc_floor`
- `margin_above_floor_kwh`, `grid_draw_kwh`
- `effective_base_load_kw`, `solar_correction_factor`
- `prediction_error_kwh`, `overcharge_kwh`, `undercharge_kwh`
- `overcharge_cost`, `undercharge_cost`

**`hourly_solar` format** — one row per hour with columns:
- `date`, `hour`, `predicted_kwh`, `actual_kwh`, `ratio`, `error_kwh`

---

## Step 3: Quick Check via Performance Report

For a quick JSON summary without exporting CSV:

1. Go to **Developer Tools → Services**
2. Select **`solarseed_peak_shaver.performance_report`**
3. Set **Days** (default: 7)
4. Click **Call Service**
5. Review the JSON response with daily scorecards

This is useful for a quick glance but not as good for deep analysis.

---

## Step 4: Analyze the Data

You have three options, from simplest to most powerful:

### Option A: Eyeball the CSV

Open the CSV in a spreadsheet (Excel, Google Sheets). Look for:
- **Grades trending up over time** — the algorithm is learning
- **Grades stuck at C or below** — something may need tuning
- **`grid_draw_kwh` > 0 on multiple days** — algorithm is under-charging
- **`overcharge_kwh` consistently high** — algorithm is too conservative
- **`solar_accuracy` far from 1.0** — solar forecast needs correction (set up Solar Actual Entity if you haven't)

### Option B: Run the SPC Analysis Script

The repo includes a standalone analysis script that produces a full SPC report:

```bash
# Save your daily CSV to a file, then:
python tools/analyze_performance.py daily_history.csv

# With hourly solar data too:
python tools/analyze_performance.py daily_history.csv --hourly hourly_solar.csv

# Machine-readable JSON output:
python tools/analyze_performance.py daily_history.csv --json
```

The script requires only Python 3.10+ (no pip packages needed). It produces:
- **Control chart statistics** — mean, upper/lower control limits, out-of-control points
- **Process capability index (Cpk)** — measures how well the algorithm stays within acceptable bounds
- **Solar forecast error distribution** — bias, variance, per-hour breakdown
- **Base load stability analysis**
- **Asymmetric cost analysis** — dollar impact of over- vs under-charging
- **Trend/drift detection**
- **Actionable recommendations** with specific parameter suggestions

Optional: `pip install matplotlib` to also generate chart images.

### Option C: Feed to Claude for AI-Powered Analysis

The repo includes prompt templates designed for deep analysis. The file `tools/claude_analysis_prompt.md` has four ready-to-use prompts:

1. **Full Analysis** — comprehensive SPC review with recommendations
2. **Quick Check** — fast pass/fail assessment with one action item
3. **Solar Tuning** — focused analysis of solar forecast accuracy by hour
4. **Iterative Feedback Loop** — ongoing weekly check-in format

#### How to use:

1. Export both CSV formats from the `export_history` service
2. Open `tools/claude_analysis_prompt.md`
3. Copy the prompt template you want
4. Paste your CSV data where indicated
5. Send to Claude
6. Get back quantitative recommendations (e.g., "increase min_safe_soc by 0.5 kWh, expected to reduce peak draw cost by $2.10/month")

---

## Step 5: Act on the Results

Common adjustments based on analysis:

| Finding | Action |
|---|---|
| Frequent grid draws during peak | Increase `min_safe_soc` |
| Consistent overcharging > 2 kWh | Decrease `min_safe_soc` or reduce `charge_rate` |
| Solar accuracy < 80% | Configure Solar Actual Entity for correction learning |
| Base load estimate too low | Check for new appliances; algorithm will auto-correct over ~14 days |
| Grades improving week over week | The system is working — keep collecting data |

---

## Recommended Analysis Cadence

| Timeframe | What to Do |
|---|---|
| **Daily** | Glance at the daily grade notification |
| **Weekly** | Run `performance_report` for the last 7 days |
| **Monthly** | Export full CSV, run SPC script or Claude analysis |
| **Seasonally** | Full analysis with focus on solar pattern changes |
