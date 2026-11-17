# Winter 2026 Analysis Brief

Started 2026-11-05, expanded 2026-11-13. This is a self-contained handoff: a fresh agent
should be able to run the whole analysis from this file plus `AGENTS.md` and
`docs/how-it-works.md`. Read those two first.

## 1. The questions Dan wants answered

1. **Plan choice (the headline question):** for winter, should Dan stay on PGE's Time of
   Day plan (3 tiers) or go back to a flat-rate plan? Answer in dollars per month, both
   with today's algorithm and with a fixed/better one. "It depends" is fine if the
   dependency is stated as a number (e.g. "TOU wins as long as peak-hour import stays
   under X kWh/day").
2. **Why is the house pulling grid power during the day?** The screenshots (section 3) show
   repeated ~2.7 kW grid draws during mid-peak and an hour of grid draw during peak.
   Precharging is supposed to prevent that. Is precharge too small, is the solar forecast
   wrong, is the base load wrong, or is something else switching the inverter?
3. **Is the solar forecast accurate?** Compare historic Solcast predictions with actual
   generation. If there is a stable bias, fit a correction (regression or quantile
   calibration) the algorithm can apply.
4. **Should we just precharge a lot more and keep a bigger reserve?** Quantify what extra
   reserve actually costs in winter (see H10 - likely close to nothing).
5. **Oven.** Find when the oven ran on 2026-11-12, how many kWh a bake session uses, and
   what baking 17:00-21:00 costs compared with baking before 17:00 or after 21:00, under
   both plans. Recommend how the algorithm should handle a planned bake.

Out of scope until Dan approves: changing anything on the live HA box (config, automations,
inverter modes). Analysis is read-only. Code changes go in this repo, tested, not deployed.

## 2. System facts

- **Battery/inverter:** Bluetti AC500, configured usable capacity 23.5 kWh. Mode entity
  `select.ac500_ups_mode` (STANDARD = grid charge/passthrough, PV_PRIORITY = run from
  battery+solar, a hold mode such as TIME_CONTROL). Grid charge rate seen in the
  screenshots: ~2.6-3.3 kW AC input (includes passthrough load), so roughly 2 kW net into
  the battery. AC500 output limit is ~5 kW, so check whether oven plus house load can
  exceed it.
- **Battery sensor:** `sensor.available_battery_kwh` (kWh).
- **Power sensors (from the old dashboard templates):** `sensor.ac500_dc_input_power`
  (solar/PV in), `sensor.ac500_ac_output_power` (house load served by the AC500). An AC
  input / grid input sensor also exists - the light-blue line in the "Energy Balance -
  AC & Solar" card. Find its entity id on the box.
- **Whole-house grid meter:** Emporia Vue, device "Vuetonia". The mains entity is the
  "Power Minute Average" sensor, e.g. `sensor.vuetonia_123_1min`. Vue usually exposes
  per-circuit channels too; check whether the oven/range has its own channel.
- **Solar forecast:** Solcast (BJReplay `ha-solcast-solar`),
  `sensor.solcast_pv_forecast_forecast_today`. Attributes `detailedHourly` /
  `detailedForecast` carry `pv_estimate` (P50), `pv_estimate10`, `pv_estimate90`. The
  integration also keeps a forecast cache file in `/config` (look for `solcast*.json`),
  which may contain past days' forecasts - the best source for forecast-vs-actual.
- **Utility:** PGE Oregon. Time of Day periods: weekdays off-peak 21:00-07:00, mid-peak
  07:00-17:00, peak 17:00-21:00, all weekend off-peak. The README rates ($0.09 / $0.18 /
  $0.44) are from early 2026 and probably energy charge only. **Re-fetch the current
  tariffs** (TOD schedule and the standard/flat residential Schedule 7, all per-kWh
  riders and adders, monthly basic charge, any plan-switching rules) from
  portlandgeneral.com before computing dollars. Holidays may count as off-peak; check.
- **Integration settings on the box:** unknown. Pull `core.config_entries` and record the
  actual base load, min safe SOC, charge threshold, schedule hours, hold months, and
  whether `solar_actual_entity` is set.
- **HA host:** HAOS VM 240 on Proxmox node pve3 (LAN .83). **Access method not yet
  established** - ask Dan (he will walk through it), then record it in `AGENTS.md` under
  "Live system access".

## 3. What the 2026-11-12/13 screenshots show

Files: `analysis/evidence/2026-11-13_vue-grid-power.png` (Vue mains, Nov 12 00:00 -
Nov 13 ~17:00) and `analysis/evidence/2026-11-13_energy-balance-ac-solar.png` (AC500:
light blue = AC/grid input, green = AC output/house load, orange = PV). Times were read off
the chart pixels and are about +/-10 min. Confirm all of them against recorder data.

| When | Grid draw | Reading |
|---|---|---|
| Nov 12 00:00-02:00 | ~650 W | Hold mode, house on grid passthrough (expected) |
| Nov 12 03:00-05:00 | ~2.7 kW | 03:00 scheduled precharge, about 2 h, so roughly 4 kWh into the battery |
| Nov 12 05:00-07:10 | ~100 W | Charge hit target, mode went to PV_PRIORITY, battery carries the house during off-peak (H6) |
| Nov 12 07:13-07:44 | 2.7-3.7 kW | **Mid-peak grid charge** |
| Nov 12 12:00-12:18 | ~2.1 kW | **Mid-peak grid charge** |
| Nov 12 14:23-14:50 | ~2.6 kW | **Mid-peak grid charge** |
| Nov 12 ~16:00-17:10 | 3.0-4.9 kW, oscillating | **Oven candidate A.** Green (house load) rises to ~2.6 kW with cycling spikes; grid peaks at 4.9 kW, so the AC500 is also charging at the same time. Runs about 10 min into peak |
| Nov 12 20:05-21:07 | 2.7-2.9 kW flat | **Peak-hour grid draw, about 2.8 kWh at $0.44.** Both AC input and output appear raised, which reads as a house load (**oven candidate B**) being passed through from the grid rather than served by the battery. Either the battery hit its floor/cutoff or the mode was not PV_PRIORITY. Must verify |
| Nov 12 21:07-21:40 | ~850 W | After-peak hold begins |
| Nov 13 03:00-04:37 | 2.6-3.3 kW | Precharge, shorter than the night before |
| Nov 13 04:37-06:40 | ~80 W | Battery carries the house off-peak again (H6) |
| Nov 13 07:12-07:44 | 2.6-3.0 kW | **Mid-peak grid charge** at the same time as Nov 12 |
| Nov 13 09:36-10:00 | ~2.8 kW | **Mid-peak grid charge** |
| Nov 13 11:59-12:23 | ~2.6 kW | **Mid-peak grid charge** at the same time as Nov 12 |
| Nov 13 14:24-14:42 | ~2.7 kW | **Mid-peak grid charge** at the same time as Nov 12 |

Takeaways to verify:

- **The daytime top-ups land at the same clock times on both days (~07:12, ~12:00, ~14:23).** That
  is what a schedule does, not a battery state. The likely mechanism: Solcast's API
  refreshes run on a fixed daily schedule; each refresh changes the forecast entity; the
  integration's `_on_forecast_update` recalculates (its window runs until 17:00); the
  battery is below plan, so it fires `charge_start`, charges about 0.5-1.3 kWh to the new
  target, and stops. See H9. Confirm by lining up Solcast `last_updated` / API-poll
  timestamps and the `solarseed_peak_shaver_charge_start` events in the logbook with
  these blocks.
- **Repeated top-ups mean the overnight charge was too small, not too conservative.**
  About 4 kWh at night was followed by several kWh of mid-peak top-ups at about twice the
  price, plus peak draw. That fits H1 (learned base load biased low).
- About 80-150 W of grid draw remains while the battery is carrying the house: either loads
  not behind the AC500 or AC500 self-consumption. Measure it, because no battery
  dispatch can remove it and it belongs in the plan-choice math.

## 4. Hypotheses (confirm or kill each with data)

**H1 - Learned base load is biased low on every day it precharges (code bug).**
`coordinator.py` ~L661: `effective_base_load_kw = (solar + (soc_07 - soc_21) -
total_charged) / 14`. `soc_07` is read *after* the overnight charge, yet `total_charged`
includes that overnight charge, so it is subtracted twice. Example: 4 kWh charged at
03:00 makes that day's load read 0.29 kW too low; a 10 kWh charge often floors it to 0.
After 3 days in the store, the 14-day mean of these values replaces the configured base
load. Check: in the scorecard history, regress `effective_base_load_kw` on
`total_charged_kwh` (expect a slope near -1/14), and compare it with true 07-21 load from
the Vue/AC output data.

**H2 - Grid-served load is invisible to the learned base load.** Load served by passthrough
(STANDARD mode while charging, hold, battery at cutoff) never shows up in the SOC delta,
so it is missing from the estimate as well. It biases low again, and worst on the bad days.
Fix: learn load from the AC500 output sensor (plus any non-AC500 circuits from Vue), not
from SOC accounting.

**H3 - One flat kW is the wrong load model.** The same kW is used overnight and for every
daytime hour, and Dan's daytime use has gone up. Build an hourly load profile (hour of day x
weekday/weekend x month, perhaps with outdoor temperature) and check how much forecast
error each model leaves.

**H4 - No tier-aware dispatch.** When 07-21 demand minus solar is more than capacity, the
current plan drains from 07:00 and runs dry in peak. In that case, holding the battery
through mid-peak and spending it in peak is worth about $0.35/kWh vs about $0.08/kWh in
mid-peak. Check whether this case even happens in winter. 23.5 kWh may cover all of
07-21 (see section 5).

**H5 - Using P50 solar when errors cost different amounts each way.** The code reads only `pv_estimate`.
Calibrate P10/P50/P90 against actuals (how often actual < P10 should be ~10%) and pick a
planning quantile from the cost ratio, which H10 changes a lot.

**H6 - Hold is cancelled at 03:00 and the battery drains off-peak.** Every recalculation
fires `charge_start` or `charge_stop`, and `charge_stop` puts the inverter into
PV_PRIORITY, so the battery runs the house from ~05:00 to 07:00 at off-peak prices (seen
in the screenshots). Cost: round-trip loss and cycling. Fix: stay in hold/passthrough until
07:00.

**H7 - Charge start time ignores charge rate.** Charging starts no earlier than 03:00. At
~2 kW net, a 10+ kWh winter charge cannot finish by 07:00. Schedule the start from
required kWh / charge rate, anywhere in 21:00-07:00.

**H8 - Bookkeeping holes in the scorecard history.** Charges ended by a "no charge needed"
recalculation are not recorded. A re-triggered charge resets the start SOC. All daily
tracking is in memory, so HA restarts skew or drop days. `run_type` is always
"scheduled". "Unnecessary charge" is not a counterfactual. Treat scorecard fields as
suspect and rebuild the metrics from raw recorder data.

**H9 - Solcast refreshes trigger mid-peak charging (new, from screenshots).** Forecast-update
recalculations from 07:00 to 17:00 can fire `charge_start` at mid-peak rates. With an
undersized overnight charge, every refresh finds a new small deficit. Even with a correct
overnight charge this path is questionable in winter. Check how many charge events
started 07:00-17:00 and how many kWh they added.

**H10 - In winter, extra reserve costs almost nothing (new, important).** `tools/analyze_performance.py`
prices overcharge at off-peak plus round-trip loss (~$0.10/kWh), as if that energy were
wasted. In winter, solar cannot fill the battery, and the after-peak hold keeps leftover
charge overnight. So a kWh not used today means one fewer kWh to charge tonight. Net grid
energy is the same; the cost is standby loss and some extra cycling. Undercharging costs
$0.18 (mid-peak top-up) or about $0.44 (peak). If true, the best winter policy is close to
"charge toward full every weekday night" and Dan's instinct to keep more reserve is right.
Verify with the backtest. Summer differs: excess charge displaces free solar.

## 5. Analysis phases

### Phase 0 - Access and inventory (blocked on Dan)

1. Get the access method from Dan and record it in `AGENTS.md`.
2. Find out where the recorder lives (SQLite `/config/home-assistant_v2.db` vs MariaDB
   add-on), the `purge_keep_days` setting, and the earliest row in `statistics`.
3. List every entity in section 2 and confirm its unit and `state_class`. Only entities
   with `state_class` have long-term hourly statistics.
4. Copy everything read-only into `analysis/data/` (gitignored). Never modify the live
   DB; copy it first (`sqlite3 ... ".backup"` or copy while HA is idle) and query the copy.

Extraction recipes:

```sql
-- hourly long-term stats (kept forever): mean/min/max for power, state/sum for energy
SELECT m.statistic_id, datetime(s.start_ts,'unixepoch','localtime') AS hour,
       s.mean, s.min, s.max, s.state, s.sum
FROM statistics s JOIN statistics_meta m ON s.metadata_id = m.id
WHERE m.statistic_id IN ('sensor.available_battery_kwh','sensor.ac500_ac_output_power',
      'sensor.ac500_dc_input_power','sensor.vuetonia_123_1min' /* + AC input, Vue circuits */)
ORDER BY m.statistic_id, s.start_ts;
-- 5-minute stats for roughly the last 10 days: same query on statistics_short_term
-- full-resolution states (purge window only): inverter mode changes
SELECT datetime(st.last_updated_ts,'unixepoch','localtime'), st.state
FROM states st JOIN states_meta sm ON st.metadata_id = sm.metadata_id
WHERE sm.entity_id = 'select.ac500_ups_mode' ORDER BY st.last_updated_ts;
-- integration events (if recorded): events + event_types where event_type LIKE 'solarseed_peak_shaver_%'
```

Also pull `/config/.storage/solarseed_peak_shaver_history`, `/config/.storage/core.config_entries`
(the solarseed entry only), `/config/automations.yaml`, `/config/home-assistant.log*`, and the
Solcast cache files.

### Phase 1 - Ground truth per day (weekdays, as far back as data goes)

Build one table per day and hour: grid import (Vue), house load (AC output + non-AC500
loads), PV actual, battery kWh, inverter mode, tier. From it derive per-day kWh imported
in each tier, kWh charged overnight vs in mid-peak/peak, min SOC and when it happened,
whether the floor/cutoff was hit, and true 07-21 and 17-21 load.

### Phase 2 - Diagnose (answers question 2)

Test H1, H2, H6, H8, H9 directly. Show learned base load vs true load over time.
Attribute every mid-peak/peak grid kWh to a cause: forecast-refresh top-up, floor hit,
passthrough load, non-AC500 load, or other.

### Phase 3 - Solar forecast vs actual (answers question 3)

Per hour and per day: actual vs P50/P10/P90 (from the Solcast cache, or from scorecard
`hourly_solar_predicted`, which is the 03:00 snapshot P50 only). Report bias by month and
hour of day, MAPE, and quantile coverage. Fit `actual ~ a + b*P50` (or a per-hour ratio)
on prior data and test it on later data. In Nov-Feb solar is small; quantify how much it even
matters vs load error before spending effort here.

### Phase 4 - Load model (H3)

Hourly profile by hour x day type x month, with optional temperature regression. Measure
the forecast error of the 07-21 and 17-21 totals for each model. Identify big discrete
loads (oven, dryer, EV, space heaters) by signature, since they drive the error.

### Phase 5 - Oven (answers question 5)

Find oven sessions on 2026-11-12 (candidates A ~16:00-17:10 and B ~20:05-21:07 in section
3; a dedicated Vue circuit makes this trivial). Over the last few months, measure kWh per
session (preheat plus cycling) and power draw, and check whether the oven is behind the
AC500 at all. If it is on a grid-only 240 V circuit, the battery can never cover it and
the only lever is timing. Price a typical session in each tier and under the flat plan,
both from the grid and from the battery (battery = precharge at off-peak / round-trip
efficiency). Recommend handling, e.g. a `input_boolean.bake_tonight` (or a calendar
entry) that adds N kWh to the 17-21 load in the plan, plus an oven-on alert during peak
like the existing "Power Spiking During Peak" automation in `../homeassistant_stuff`.

### Phase 6 - Backtest policies and the plan choice (answers questions 1 and 4)

Simulator: replay the actual hourly load and PV with battery constraints (capacity,
measured charge rate, measured round-trip efficiency, AC500 output limit, floor), apply a
dispatch policy, and price grid import under each tariff. Policies:

| ID | Policy |
|---|---|
| P0 | What actually happened (sanity check vs real bills, if Dan can share them) |
| P1 | Current algorithm with H1/H2 fixed and no daytime top-ups |
| P2 | Winter fixed target: charge to X kWh every weekday night (sweep X from 10 to 23.5), hold until 07:00, no daytime charging |
| P3 | Forecast-based: target = forecast(07-21 load) - quantile solar + floor + oven allowance, tier-aware (save battery for peak when short) |
| P4 | Flat-rate plan, battery for backup/solar self-consumption only, no grid arbitrage |
| P5 | Hindsight optimum (perfect knowledge), the upper bound on savings |

Report $/month for each, for winter months and annualized, plus peak-hour kWh imported.
State the plan-choice answer as a break-even: TOU beats flat when
`E_off*(flat - r_off) > E_mid*(r_mid - flat) + E_peak*(r_peak - flat) + loss_kWh*r_off`
(plus any basic-charge difference), using the import mix each policy produces.
Back-of-envelope expectation to test: winter weekday load is about 0.6-0.9 kW, so 07-21 needs
about 9-13 kWh plus the oven, less than 23.5 kWh. A decent policy can then push nearly all
weekday import to off-peak, which would make TOU clearly cheaper than flat. If the data
says otherwise, say why.

### Phase 7 - Recommendations

1. Plan choice with dollar figures and the conditions it depends on.
2. Immediate settings tweaks Dan can make today without code (e.g. raise min safe SOC or
   the configured base load, narrow the forecast-recalc window), with expected effect.
3. Algorithm changes for the next version, ranked by $ impact, each mapped to the
   hypotheses above. Expected candidates: fix H1/H2, hourly load profile, no daytime top-ups
   in winter (H9), hold until 07:00 (H6), rate-aware charge start (H7), season-aware
   reserve (H10), a bake-allowance input, and moving daily tracking state into the store
   so restarts do not lose it.

## 6. Deliverables and ground rules

- Write findings to `docs/winter-2026-findings.md` with tables, and charts as PNGs in
  `analysis/` or embedded data. Keep raw household data in `analysis/` (gitignored).
- Append decisions to the log below.
- Do not change the live HA box, push to `main`, or deploy without Dan's explicit OK.
- ASCII only in written files (see `~/src/AGENTS.md`).
- When a phase that takes a long time finishes, or you are blocked on Dan, notify via `~/src/notify.sh`.

## Decisions log

- 2026-11-13: Analysis brief written. Screenshots saved to `analysis/evidence/`. Data access to HA still pending.
- 2026-11-13: Access established (temporary HA admin user, REST + WebSocket API; see `AGENTS.md`). Phase 0 done and a first pass of Phases 1, 2, 5 and the tariff lookup. Results in `docs/winter-2026-findings.md`. Corrections to this brief:
  - Section 2: integration settings are now known (base load 0.6 kW, min safe 1.5 kWh, `solar_actual_entity` unset). Grid input entity is `sensor.ac500_ac_input_power`. There is no `home-assistant.log` on current HA; use the Supervisor log API. The AC500 power sensors keep only 1 day of raw states (a purge automation), so use 5-minute and hourly statistics.
  - Section 3: "oven candidate B" (Nov 12 20:05-21:07) was a manual switch to STANDARD from Dan's own account, not an oven. Candidate A is a load that is not behind the AC500, about 16:25-17:15.
  - H1/H2 are not active on the live box because `solar_actual_entity` is unset. H6, H8, H9 confirmed.
  - New top finding: a percent of SOC now delivers about 0.13-0.15 kWh, not the assumed 0.235. Cause open.
  - Phase 6 must model the battery with measured kWh per percent, not the configured 23.5 kWh.
- 2026-11-13: Design decisions from Dan for the rework:
  - Keep pulling Solcast, but a forecast update must not by itself start a charge. Charging is planned against the tariff windows.
  - Off-peak precharge is planned to finish at 07:00. If more is needed to get through 17:00-21:00, the mid-peak charge is planned to finish by 17:00. No charging in peak.
  - Add a periodic full (100 %) calibration charge on the weekend, starting Friday 21:00, when there is 58 hours of off-peak and nothing can interrupt it.
  - Base load must be adaptive or periodically refreshed from measured load (Dan's gaming PC raised it recently). Learn it from the AC500 output sensor, not from SOC accounting.
  - The Nov 12 20:07 manual switch to STANDARD was Dan, worried about load. The 16:25-17:15 load was the oven.
  - Bank is one B300 plus four Vatrer packs; the Bluetti percent tracks the B300 only (findings 2f). Plan with a bank energy sensor built from the Vatrer BMS data plus the B300.
- 2026-11-13 16:59 PST: LIVE BOX CHANGE, approved by Dan in chat. Added one temporary automation, id `temp_claude_calibration_20261113`, alias "TEMP Claude - battery calibration weekend 2026-11-13". It sets `select.ac500_ups_mode` (with up to 5 retries) and sends a phone notification after each step: Fri 11-13 21:10 STANDARD (full charge); Sat 11-14 12:00 PV_PRIORITY (measured discharge); Sun 11-15 STANDARD when the Bluetti percent is under 3.5 for 5 minutes or at 15:00, whichever is first (recharge before Monday 07:00). Date-guarded, so it does nothing after 11-15. Delete it Monday (Settings > Automations). A copy of its config and of all 19 pre-existing automation configs is in `analysis/data/`. Nothing else on the box was changed.
  - Purpose: measure true usable capacity (AC kWh out from full to cutover), charge rate and taper, round-trip efficiency, and reset the five charge counters. Monday then starts from a full battery, which is a free test of H10.
- 2026-11-16 00:45 PST: LIVE BOX CHANGE, cleanup. Deleted the temporary automation `temp_claude_calibration_20261113` (deletion on Monday was part of Dan's approval on 2026-11-13). Checked afterwards: 19 automations, none unavailable. All three steps had fired as scheduled (Fri 21:10, Sat 12:00, Sun 15:00); the low-percent trigger never fired. Nothing else on the box was changed. The box is back to its pre-test configuration.
- 2026-11-16: Dan confirmed the learned-curve planner design (`docs/battery-bank-methodology.md`) as the next step, and wants the improvement measured against the current behavior. He also wants a low-end test on the weekend of 2026-11-21. Test results and two corrections (charging stops at B300 100 %; the B300 parked at 1 % for 15 hours in December 2025) are in findings section 7.
- 2026-11-16: Decisions and facts from Dan:
  - Approved: in winter, charge every TOU night until the inverter stops by itself. The replay (findings 8d) supports this for November to January and a sized charge for February and March.
  - The 2025-12-27/28 run-down was deliberate. Dan has a photo from 12-28 11:27 with the four Vatrers stacked and showing ?, 5, 13 and 12 % and the AC500 at 0 %, which matches the recorded data. He had just swapped the second Bluetti pack (a B300 or possibly a B300K, 2.7 kWh) for the fourth Vatrer, bought 2025-12-19. He does not remember what setting kept the inverter on battery below 3 %.
  - Open: which Bluetti pack remains in Portland (B300, 3.07 kWh, or B300K, 2.76 kWh). Low stakes; the learned model does not use the nameplate.
- 2026-11-16 21:15 PST: RELEASE. Fast-forwarded `main` to the rework branch and pushed; created GitHub release v0.7.0 (HACS installs from releases). Tests pass on GitHub for Python 3.12 and 3.13 and hassfest passes; the HACS Action job still fails on repository metadata only (no description, topics or brand assets), as it did before.
  - Mistake to know about: local `main` was three commits ahead of GitHub before this work (ec8f01e "wip: pre-migration snapshot", 4b005cb "pre-work for winter 2026 analysis...", fd49d50 merge). The push published those too. Checked afterwards: they add `AGENTS.md`, `CLAUDE.md`, `.gitignore`, the original `docs/analysis-plan.md`, `docs/how-it-works.md` and three `Zone.Identifier` files; no credentials, tokens or full IP addresses. Dan told 2026-11-16.
- 2026-11-16 21:20 PST: DEPLOY BLOCKED, nothing changed on the box. `update.install` for v0.7.0 was refused by HACS with "Open the Marketplace and read the warning first, installing and updating work once it is accepted". That acknowledgement is Dan's to give in the UI; not worked around. The box still runs 0.6.0, inverter in TIME_CONTROL (hold) since 21:05 as usual.
- 2026-11-16 21:41 PST: DEPLOYED 0.7.0 in shadow mode. Dan accepted the HACS warning and installed v0.7.0 himself (the HACS panel is no longer a separate item in his UI; he found the update elsewhere) and Home Assistant restarted. Verified over the API: config entry `loaded`, version v0.7.0, all previous sensors present, two new sensors present, no integration errors in the log.
  - LIVE BOX CHANGE (covered by Dan's "free to deploy"): saved the integration's options through the options flow with every existing value unchanged plus `gauge_entity` = `sensor.ac500_total_battery_percent`, `load_power_entity` = `sensor.ac500_ac_output_power`, `grid_power_entity` = `sensor.ac500_ac_input_power`, `pv_power_entity` = `sensor.ac500_dc_input_power`, `planner` = `classic`. Before this the entry had no options (everything was in `data`).
  - Ran `backfill_learning` (10 days): 2879 samples, 319 discharge points, 278 grid-charge points, 14 TOU days and 14 other days of load; floor to full 16.9 kWh; 07:00-21:00 load 9.1 kWh.
  - Side effect of the restart, existing behavior: the integration's first calculation after a restart fired `charge_stop`, which released the 21:05 hold (inverter back to PV_PRIORITY at 21:41). The battery therefore carries the house overnight until the 03:00 run. Cost-neutral (all off-peak). Worth fixing: a restart should not change the inverter's mode.
- 2026-11-16: Dan: the house drawing a few hundred watts from the grid in mid-peak and peak is by design; the inverter was never meant to carry the whole house. So the measure of success is grid energy through the inverter in mid-peak and peak, not the house meter. He also asked for the analysis docs to be committed (done, with one account name removed), the HACS repository checks fixed, and a brief for turning the methodology into a white paper (`docs/whitepaper-brief.md`).

