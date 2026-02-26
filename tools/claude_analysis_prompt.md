# Solarseed Peak Shaver — Claude Analysis Prompt Template

Use this prompt when feeding exported CSV data to Claude for analysis. Copy the
appropriate sections and paste your CSV data where indicated.

---

## Full Analysis Prompt

```
You are an expert in Statistical Process Control (SPC) and residential battery
energy management. I have a Home Assistant integration called "Solarseed Peak
Shaver" that decides how much to charge a home battery overnight so that the
battery lasts through the peak TOU rate window without importing from the grid,
but without overcharging and wasting the 15% round-trip efficiency loss.

**Rate structure (PGE E-TOU-D):**
- Off-peak: $0.09/kWh
- Mid-peak: $0.18/kWh  
- Peak: $0.44/kWh
- Round-trip battery loss: ~15%

**The asymmetric cost problem:**
- Under-charging costs $0.44/kWh (grid draw during peak)
- Over-charging costs ~$0.10/kWh (off-peak cost + lost efficiency)
- Ratio: under-charging is ~4.25x more costly per kWh than over-charging
- Optimal strategy is slightly conservative (overcharge by a small margin)

**Key algorithmic decisions:**
- `charge_amount_kwh`: How much to charge overnight (main output)
- `solar_correction_factor`: Per-hour multiplier applied to solar forecast
- `effective_base_load_kw`: Dynamic base load estimate (rolling average)

**What I need you to analyze:**

1. **Process Stability**: Are charge decisions statistically in-control, or 
   are there special-cause variations? Look for runs, trends, and outliers.

2. **Bias Detection**: Is the algorithm systematically over- or under-charging?
   What is the optimal bias given the 4.25:1 cost asymmetry?

3. **Solar Forecast Quality**: How accurate is the solar forecast? Are there
   specific hours that are consistently off? What correction factors would you
   recommend per-hour?

4. **Base Load Stability**: Is the base load estimate stable, or are there
   periodic patterns (weekday/weekend, seasonal)?

5. **min_safe_soc Optimization**: Given the data, what is the optimal 
   min_safe_soc setting? Currently set to [FILL IN YOUR VALUE] kWh.

6. **Actionable Recommendations**: Specific parameter changes with expected
   impact. Be quantitative — "increase X by Y, expected to reduce Z cost by $W/month."

**DAILY SCORECARD CSV:**
```csv
[PASTE daily CSV from export_history service here]
```

**HOURLY SOLAR CSV (optional but recommended):**
```csv
[PASTE hourly_solar CSV from export_history service here]
```

Please provide your analysis in the following format:
1. Executive Summary (3-5 bullet points)
2. Control Chart Analysis (with specific out-of-control dates)
3. Cost Analysis (total, daily average, monthly projection)
4. Solar Forecast Assessment (daily bias, per-hour corrections)
5. Specific Parameter Recommendations (with confidence levels)
6. Risk Assessment (what could go wrong with your recommendations)
```

---

## Quick Check Prompt

For a faster, focused analysis:

```
I have daily performance data from my battery peak-shaving algorithm.
The key metric is "margin_above_floor_kwh" — how much battery headroom
remained above the configured minimum at the worst point during peak hours.

- Positive = good (battery never hit floor)
- Negative = bad (floor was breached, grid power was drawn during peak)
- Too positive (>3 kWh) = wasteful (overcharged)

Given PGE TOU rates ($0.44 peak, $0.09 off-peak, 15% round-trip loss),
what is the optimal target margin and what parameter changes do you recommend?

CSV data:
```csv
[PASTE daily CSV here]
```
```

---

## Solar Forecast Tuning Prompt

For focused solar forecast correction:

```
I need per-hour solar forecast correction factors for my peak-shaving algorithm.
The data below shows predicted vs actual solar production per hour per day.

A ratio of 1.0 means the forecast was perfect.
Below 1.0 means the forecast was optimistic (predicted more than actual).
Above 1.0 means the forecast was pessimistic (predicted less than actual).

Please calculate:
1. Per-hour mean ratio and recommended correction factor
2. Per-hour variance (some hours may be inherently less predictable)
3. Hours that should use a wider safety margin
4. Any time-of-year trends if dates span multiple months

```csv
[PASTE hourly_solar CSV here]
```
```

---

## Iterative Feedback Prompt

After implementing recommendations, use this to track improvement:

```
I previously analyzed my peak-shaving algorithm and made these changes:
[LIST CHANGES MADE]

Here is the new data since those changes. Please compare:
1. Did the changes improve the margin distribution?
2. Is the algorithm now closer to optimal?
3. Are there new issues that emerged?
4. What is the next recommended adjustment?

**BEFORE (previous data):**
```csv
[PASTE old CSV]
```

**AFTER (new data since changes):**
```csv
[PASTE new CSV]
```
```

---

## How to Get the CSV Data

In Home Assistant Developer Tools > Services:

```yaml
service: solarseed_peak_shaver.export_history
data:
  format: daily
```

```yaml
service: solarseed_peak_shaver.export_history
data:
  format: hourly_solar
```

Copy the `csv` field from the service response and paste it into the prompts above.

## Using with the SPC Script

For automated analysis before feeding to Claude:

```bash
# Export CSVs from HA, save to files, then:
python tools/analyze_performance.py daily.csv --hourly hourly_solar.csv

# Or get JSON for programmatic use:
python tools/analyze_performance.py daily.csv --hourly hourly_solar.csv --json

# Generate charts:
python tools/analyze_performance.py daily.csv --charts output/
```

The script produces control charts, Cpk calculations, and cost analysis using
only the Python standard library. For charts, install matplotlib:

```bash
pip install matplotlib
```
