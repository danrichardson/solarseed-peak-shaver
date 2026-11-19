# Winter 2026 Findings

Working record for the analysis in `docs/analysis-plan.md`. Numbers come from raw Home
Assistant recorder data (states, 5-minute and hourly statistics, logbook) and the
integration's diagnostics download, pulled read-only on 2026-11-13. Raw data and the
scripts that produced these tables are in `analysis/` (gitignored). Nothing on the live
box was changed.

Status: first pass. Items marked OPEN are not settled.

## 1. What the box is actually configured to do

Integration v0.6.0, HA 2026.11.1. Config entry (no options overrides):

| Setting | Value |
|---|---|
| base_load_kw | 0.6 |
| battery_capacity | 23.5 |
| min_safe_soc_kwh | 1.5 |
| charge_threshold | 0.5 |
| schedule_hours | 3,4,5,6 |
| seasonal_preservation / months | on / 11,12,1,2,3 |
| weekdays_only | true |
| solar_actual_entity | not set |

- `solar_actual_entity` is not set, so `effective_base_load_kw` is always null and the
  integration uses the configured 0.6 kW. **H1 and H2 (learned base load bias) are real
  code bugs but are not active on this box.**
- `sensor.available_battery_kwh` moves in 0.235 kWh steps: it is SOC percent x 23.5 / 100.
- AC500 limits on the box: `number.ac500_battery_range_start` = 2 %, `..._end` = 100 %.
- No AppDaemon add-on is installed (the `appdaemon` folder is a leftover). The only
  automations that write `select.ac500_ups_mode` are the three Solarseed blueprints.
- An automation purges the three AC500 power sensors from recorder states after 1 day.
  Their 5-minute statistics cover about 10 days and hourly statistics go back to
  2025-05-31 (Vue mains: 2024-03).
- HA was restarted 2026-11-11 09:44 PST, which reset the integration's in-memory day.

## 2. Why the house pulls grid power during the day

### 2a. Every daytime top-up is a Solcast poll (H9 confirmed)

Solcast is polled 10 times a day at fixed 144-minute spacing from local midnight
(02:24, 04:48, 07:12, 09:36, 12:00, 14:24, 16:48, 19:12, 21:36). Each poll changes the
forecast entity, the integration recalculates, finds a deficit, and fires `charge_start`.
On Nov 12 and 13 every mid-peak charge started within one second of a poll:

| Day | Charge start (PST) | Stop | Tier |
|---|---|---|---|
| Nov 12 | 03:00:00 | 05:00:00 | off-peak |
| Nov 12 | 07:12:01 | 07:41:29 | mid-peak |
| Nov 12 | 12:00:02 | 12:16:14 | mid-peak |
| Nov 12 | 14:24:01 | 14:47:02 | mid-peak |
| Nov 12 | 16:48:01 | 17:09:24 | mid-peak, ran 9 min into peak |
| Nov 13 | 03:00:00 | 04:36:27 | off-peak |
| Nov 13 | 07:12:01 | 07:45:57 | mid-peak |
| Nov 13 | 09:36:01 | 10:01:44 | mid-peak |
| Nov 13 | 12:00:02 | 12:28:57 | mid-peak |
| Nov 13 | 14:24:01 | 14:43:49 | mid-peak |

### 2b. The plan is too small because a percent of battery is worth far less than assumed

The integration assumes 1 % SOC = 0.235 kWh. Measured AC energy delivered per 1 % during
battery-only discharge hours (ratio of sums over all such hours, hourly statistics):

| Period | 0-20 % | 20-40 % | 40-60 % | 60-80 % | 80-100 % | Days reaching 99 % |
|---|---|---|---|---|---|---|
| 2025 H2 | 0.219 | 0.199 | 0.225 | 0.194 | 0.232 | 59 of 184 |
| 2026 H1 | 0.264 | 0.161 | 0.171 | 0.139 | 0.160 | 45 of 180 |
| 2026 H2 | 0.229 | 0.130 | 0.147 | 0.132 | 0.151 | 8 of 136 |

In 2025 a percent delivered about 0.20-0.22 kWh (consistent with 23.5 kWh less inverter
loss). In late 2026 it delivers about 0.13-0.15 kWh, i.e. roughly 13-15 kWh usable AC for
a full battery. The integration therefore believes it has about 1.6x the energy it has.

Cause (2026-11-13, with Dan's description of the bank): see section 2f. The Bluetti
percent is the state of charge of one 3 kWh B300 only, so it is not a measure of the
23.5 kWh bank at all.

### 2f. The battery bank and what the Bluetti percent means

Bank: one Bluetti B300 (3.07 kWh) plus four Vatrer 51.2 V 100 Ah packs (about 5.1 kWh
each), 23.5 kWh nameplate. Until December 2025 it was two B300s; one was moved out and
a Vatrer added (Vatrer 2 first reports 2025-12-24, Vatrer 4 on 2026-01-20). The Vatrer
packs report over Bluetooth (`sensor.vatrer_N_battery`, `_voltage`, `_current`,
`_power`, `_stored_energy`), hourly statistics since 2025-06 to 2026-01 depending on pack.

- `sensor.ac500_total_battery_percent` equals `sensor.ac500_pack_percent3` (the B300) to
  within 0.03 points over all of 2026. The Vatrer packs do not enter it. Confirmed.
- B300 pack voltage and Vatrer voltage have the same monthly extremes (57.1 vs 57.0 V
  max, 50.3 vs 50.4 V min). They sit on one bus and are the same 16-cell LFP chemistry.
  No evidence of different voltage curves.
- What differs is the charge counters, and they drift against each other:

| Bluetti % | Vatrer SOC, Feb-Jun 2026 | Vatrer SOC, Jul-Nov 2026 |
|---|---|---|
| 3-10 | 24 | 8 (packs 2-4 read 3-5, pack 1 reads 22) |
| 20-30 | 54 | 22 |
| 40-50 | 66 | 37 |
| 70-80 | 82 | 64 |
| 99.5-100 | 99 | 97 |

  In spring the B300 read empty while the Vatrers still reported about 5 kWh. By autumn
  the relationship had moved about 30 points. Right now (2026-11-13 16:28) at one bus
  voltage of 52.05 V the five counters read 18 (B300), 31, 11, 11 and 10 %.
- Last full charge: August 2026. No day in September, October or November reached
  55.2 V or 99 % on any counter. In October a Vatrer counter read 1 % or less on 27 of 31
  days while the bus never went below 50.4 V.
- During battery-only hours the Vatrers supply 0.865 kWh DC per kWh of reported AC
  output. Whether the B300 does more than its 13 % share of the work depends on inverter
  loss, which is not measured (section 6 shows the AC500 sensors do not close an energy
  balance). NOT ESTABLISHED; the calibration test compares the counters directly.
- The step down in kWh per Bluetti percent (0.176 in Dec 2025, 0.153 in Jan 2026) lines
  up with the December swap: the percent went from describing 28 % of the bank to 13 %.

Consequences: true usable capacity is not known from existing data; a measured full
charge and discharge is needed. The planner should take bank energy from the Vatrer
packs plus the B300, not from the Bluetti percent. A periodic full charge is needed to
keep all five counters honest.

### 2c. Other contributors

- Real AC500 load is about 0.67-0.70 kW averaged over the day (15.7-18.1 kWh/day on
  full days Nov 4-12) against the configured 0.6 kW, before inverter losses.
- H6 confirmed: after the overnight charge the inverter goes to PV_PRIORITY and the
  battery carries the house from about 05:00 to 07:00 at off-peak prices (Nov 12:
  32.9 % at 05:00, 22.9 % at 07:00), so the day starts about 10 points down.
- The battery lives at the bottom of its range: daily low 3-6 % on most weekdays, daily
  high 24-47 %. It has not been above 47 % in the 10 days of data.
- H8 confirmed: the Nov 12 scorecard lists no overnight charge at all (the 03:00-05:00
  charge ended on a "no charge needed" recalculation and was not recorded), and the
  04:00 recalculation overwrote the 03:00 start on Nov 13.
- About 85 W of load is not behind the AC500 and is always served from the grid.

### 2d. The Nov 12 peak-hour draw was a manual mode change

At 20:07:48 PST `select.ac500_ups_mode` was set to STANDARD by a `select.select_option`
service call from Dan's own user account (not an automation). SOC was about 9 %.
The inverter then grid-charged at about 2.5 kW until the 21:05 hold, taking SOC to 21 %.
That is roughly 2.2 kWh of peak-rate import, about 1.5 kWh of it into the battery. It was
not an oven and not the algorithm.

### 2e. Weekday import by tier, Nov 4-12 (7 full weekdays, Vue mains)

| | Off-peak | Mid-peak | Peak |
|---|---|---|---|
| Grid import, kWh/day | 8.8 | 4.7 | 2.1 |
| Of which battery grid-charge, kWh/day | 3.2 | 1.8 | 0.6 |

## 3. Oven on 2026-11-12

A load that is not behind the AC500 (Vue mains minus AC500 grid input) ran from about
16:25 to 17:15 PST: 2.7-2.95 kW for the first 10 minutes, then 0.6-1.5 kW cycling. Total
about 1.1 kWh, of which about 0.3 kWh fell after 17:00. The AC500 is not in split-phase
mode (120 V only), so a 240 V oven cannot be on it. Dan confirmed 2026-11-13 that this
was the oven. The battery can never cover it and timing is the only lever. Vue has no
dedicated oven channel (only channels 11 and 16 show any load).

## 4. Plan choice, first cut

Tariff (PUC Oregon E-19, Advice 26-06, effective 2026-04-01; base plus Schedule 125
adjustment). Basic charge is $13 on both plans.

| | cents/kWh |
|---|---|
| Default (flat) | 11.411 + 5.685 = 17.10 |
| TOD off-peak | 8.93 (PGE web page, current) |
| TOD mid-peak | 16.70 |
| TOD on-peak | 43.13 |

Mid-peak is about the same price as flat. So the comparison is nearly two-term:
**TOD wins while peak-hour import is below about 31 % of off-peak import**
(8.17 c saved per off-peak kWh against 26.03 c lost per peak kWh).

Applied to what the whole-house meter actually recorded, with the algorithm as it is:

| Month | Off kWh | Mid kWh | Peak kWh | Peak / off | TOD cheaper than flat by |
|---|---|---|---|---|---|
| 2025-11 | 298 | 49 | 11 | 4 % | $22 |
| 2025-12 | 337 | 67 | 17 | 5 % | $23 |
| 2026-01 | 363 | 46 | 18 | 5 % | $25 |
| 2026-02 | 214 | 29 | 13 | 6 % | $14 |
| 2026-10 | 237 | 75 | 24 | 10 % | $13 |
| 2026-11 (13 days) | 143 | 36 | 17 | 12 % | $8 so far |

Caveats: this prices the same import pattern on both plans. On the flat plan the battery
would not grid-charge, which saves the round-trip loss (order of $5/month), so the true
TOD advantage is somewhat smaller. The 2026-10-15 PGE price change and Schedule 100
adjustments are not yet folded in. A proper backtest (Phase 6) is still to do.

(October and November rows use daylight-saving-correct local time and PGE holidays; an
earlier version of this table used fixed PST for every month.)

An earlier estimate here said fixing the algorithm was worth about $20/month. The
backtest in section 6 puts it at about $10/month: part of the mid-peak and peak import
is load that is not behind the AC500 and cannot be shifted.

## 5. Hypothesis status

| ID | Status |
|---|---|
| H1, H2 | Code bugs, not active on this box (no `solar_actual_entity`). H1 is also wrong in sign for daytime charges: they should be added, not subtracted |
| H3 | Not tested yet |
| H4 | Not tested yet |
| H5 | Not tested yet. Solar is 1-4 kWh/day in November, so it is second-order next to 2b |
| H6 | Confirmed |
| H7 | Open. Observed charge rate about 1.9 kW net; a full charge from 5 % would not fit in 03:00-07:00 |
| H8 | Confirmed |
| H9 | Confirmed |
| H10 | Not tested yet. Battery never above 47 %, so there is ample headroom to try it |
| New: kWh per percent | Section 2b. Largest single error found so far |

## 6. Backtest, first cut (2026-11-13)

`analysis/scripts/backtest.py` replays measured hourly AC500 load, PV and non-AC500 load
through a simple battery model and prices the resulting grid import. Winter policies hold
the battery overnight and on weekends, charge off-peak to finish by 07:00, discharge
07:00-21:00 on TOU days, and never charge in peak.

| Policy | Meaning |
|---|---|
| actual | What the whole-house meter recorded |
| selfuse @ flat | No grid charging, battery only stores solar, flat price |
| night_full | Charge to 100 % before every TOU day |
| forecast | Charge to expected 07-21 need (14-day load profile, 70 % of recent solar) plus 10 % margin |
| tier | forecast, plus hold or top up in mid-peak if the peak window is not covered |
| hindsight | Charge exactly what the next day needed (upper bound) |

Energy cost in $ per month, 15 kWh usable, 92 % grid-charge efficiency:

| Month | actual @ TOD | actual @ flat | selfuse @ flat | night_full | forecast | tier | hindsight |
|---|---|---|---|---|---|---|---|
| 2025-11 | 39.29 | 61.27 | 63.21 | 40.26 | 39.09 | 39.12 | 39.00 |
| 2025-12 | 47.00 | 72.13 | 75.49 | 46.75 | 46.74 | 46.78 | 46.63 |
| 2026-01 | 47.23 | 72.97 | 74.05 | 47.63 | 47.79 | 47.45 | 47.24 |
| 2026-02 | 29.66 | 43.77 | 48.78 | 35.54 | 32.71 | 32.71 | 32.38 |
| 2026-03 | 32.59 | 48.21 | 53.63 | 42.30 | 38.31 | 38.12 | 37.32 |
| 2026-11 (13 days) | 25.97 | 33.49 | 34.36 | 21.49 | 22.50 | 21.83 | 21.53 |

What it shows:

- **Plan choice is not close.** TOD beats flat by about $22-28/month in November to
  January and $14-16 in February and March, under every policy and every capacity and
  efficiency tried (12-18 kWh, 85-100 %).
- **Last winter the system was already within about $1/month of the hindsight optimum**
  in November to January. The problem is recent: November 2026 is running about $4.50
  over optimum in 13 days, roughly $10/month.
- **In deep winter, charging to full every weekday night is as good as perfect
  foresight** (H10 confirmed for November to January). In February, March and October it
  costs $3-5/month because a full battery wastes solar, so the shoulder months need the
  forecast-based target.
- **Capacity between 12 and 18 kWh barely changes the answer in winter.** A full charge
  covers 07:00-21:00 either way.
- **Unshiftable floor:** load not behind the AC500 is about 16 kWh mid-peak and 7 kWh
  peak in the 13 November days, against 36 and 17 actually imported.

Limits of this cut:

- The AC500's own power sensors do not close an energy balance: over the year AC output
  exceeds grid input plus PV by 3.5 %. The model therefore works in sensor units with a
  single charge-efficiency number. The weekend calibration test will measure real
  round-trip efficiency against the whole-house meter.
- February, March and October rows understate what a good policy can do: this cut holds
  the battery all weekend, which wastes solar in sunnier months. Actual beat every
  modelled policy in those months for that reason.
- Hourly resolution; no inverter output limit; no modelling of the B300 hitting its own
  floor before the Vatrers are empty.

## 7. Calibration test, partial results (as of Sat 2026-11-14 21:05 PST)

Charge ran Fri 21:10 to Sat 12:00, discharge from Sat 12:00 and still running. Hourly
means from 5-minute statistics (`analysis/data/raw/test_5min_partial.json`).

| Phase | Net AC into bank | B300 | Each Vatrer |
|---|---|---|---|
| Charge, full rate (Fri 22:00 - Sat 03:00) | 1.85 kW | +12.5 %/h, about 0.38 kW | +7 %/h, about 0.40 kW by its power sensor |
| Charge, after B300 reached 98-99 % (Sat 05:00 - 12:00) | 0.70-0.80 kW | flat at 99 % | +3.3 %/h, about 0.19 kW |
| Discharge (Sat 13:00 - 21:00), house load about 0.65 kW | - | -4.5 to -5 %/h, about 0.14 kW | -2 to -3 %/h, about 0.11-0.15 kW |

- **The five batteries share power about equally per battery, not per kWh.** The B300 is
  3.07 kWh and each Vatrer about 5.1 kWh, so the B300's percent moves about 1.7 times as
  fast as a Vatrer's, charging and discharging. This establishes what section 2f left open.
- **The inverter throttles to about 40 % power once the B300 reads full,** but keeps
  charging. From an all-empty start that leaves the Vatrers near 60 % when the B300 is
  full, and a slow tail of about 12 more hours.
- **A full charge from empty is about 20 hours, not 10-12.** B300 6 % to 99 % took 8.5
  hours; Vatrers 2-4 went from about 3 % to about 80 % in 15 hours and were still rising
  when the discharge step started at noon. The noon step was scheduled on the wrong
  assumption; the Vatrers were not full.
- **The charge counters did not reset.** Bus voltage peaked at 54.1 V (past full
  charges reached 57 V). Vatrer 1 still reads 15-20 points above its siblings at the
  same voltage and current.
- Net AC in during the charge was about 19.5 kWh.
- Projection: the B300 reaches the 3.5 % trigger around 10:00 Sunday with Vatrers 2-4
  near 40 %. Usable AC from this start would then be about 14 kWh. Confirm from the data.

### The operating band that follows from equal sharing

With equal power per battery, a full B300 swing (3.07 kWh) moves each Vatrer by 3.07 kWh,
which is 60 % of a Vatrer. So the bank stays in step when the Vatrers cycle between about
40 % and 100 % while the B300 cycles between its floor and 100 %:

- Starting from B300 at floor and Vatrers at 40 %, everything reaches full together in
  about 9 hours at full rate. No throttled tail.
- Starting from everything at the bottom (the state before this test) gives the long tail.
- The bottom 40 % of the Vatrers, about 8 kWh, cannot be reached by daily cycling,
  because the inverter stops when the B300 reads empty. Usable is about 15 kWh at the
  batteries, about 14 kWh AC. Spring 2026 data (section 2f) had the Vatrers near 24 %
  when the B300 was empty, so some rebalancing may occur near the bottom; check Sunday.
- The band drifts (it moved about 30 points between spring and autumn 2026). A long
  weekend top-up, continuing after the B300 is full until the Vatrers are full, puts it
  back and is the only thing that resets the counters.

Consequence for the planner: the Bluetti percent is the right gauge for "energy until
the inverter stops", with the wrong scale. Use about 0.14 kWh AC per percent (to be
confirmed Sunday), not 0.235. Use the Vatrer counters to check the band and to decide
when a top-up is due, not as the planning quantity. This replaces the earlier suggestion
to plan from a Vatrer-based bank energy sensor.

### Update, Sun 2026-11-15 13:30 PST

Discharge Sat 12:00 to Sun 07:00 (19 hours, almost no PV): AC out 11.49 kWh, PV 0.62 kWh.
B300 99 % to 37 %. Vatrer counters fell 38-41 points each (1.93-2.10 kWh each); their
power sensors say 2.06-2.28 kWh each.

- **Equal energy per battery holds over the whole discharge:** about 1.9 kWh from the
  B300 and about 2 kWh from each Vatrer.
- **From a (nearly) full start the bank delivered about 0.175 kWh AC per B300 percent,**
  against 0.13-0.15 in the drifted state before the test. Extrapolated to the 3 % floor
  that is about 17 kWh AC. The earlier "about 14 kWh" in this section applies to the
  drifted state only.
- **The split is not constant.** Overnight the B300 almost stopped falling (53 % to 46 %
  in five hours) while Vatrers 2 and 3 carried more, as the bus crossed the plateau step
  from 53.1 V to 52.6 V. Historical battery-only hours give a B300 share of 10-23 %
  depending on its band, lowest at 12-20 %.
- The B300 will not reach the 3.5 % trigger before 15:00 (29 % at 13:30, sun on the
  panels), so the recharge starts at 15:00 from B300 about 30 % and Vatrers about 40 %.

### What happens at the floor (from history, no extra test needed)

- Whenever the B300 touched 3 % in PV_PRIORITY the inverter handed the house to the
  grid. Spring 2026: 6 of 6 such hours had grid carrying the load, with the Vatrers
  still at 12-32 %. November 2026: 5 episodes, 30-70 minutes on battery below 6 %, then
  grid. The handover is seamless, so the house does not notice.
- The B300 does not hold at 3-5 % while the Vatrers carry on. At 5-12 % it still falls
  2.4-3.5 points per hour.
- So the Vatrer charge left at that moment is not delivered in that cycle. From a full
  start that is roughly 20-40 % of the Vatrers.

**Corrected 2026-11-16:** the three bullets above describe the present setup only, and
the second one is wrong as a general statement. See "The B300 can park" below.

### Update, Mon 2026-11-16 00:30 PST: recharge result and corrections

Data pulled 2026-11-16 08:27 UTC. The 2026-11-13 files are kept in
`analysis/data/raw/snap_2026-11-13/`. The temporary automation was deleted at 00:45 PST
(19 automations remain, none unavailable).

**Recharge, Sun 15:00 to 22:52.**

| | |
|---|---|
| Start | B300 23 %, Vatrers 55 / 36 / 38 / 35 % |
| End | B300 100 %, Vatrers 100 / 86 / 81 / 80 % |
| Duration | 7 h 52 min |
| Inverter AC in / AC out / PV | 17.11 / 5.23 / 0.04 kWh, so 11.9 kWh net into the bank |
| House meter (Vue mains) | 18.95 kWh |
| Rate | about 1.8 kW net until B300 90 % (19:30), then about 0.9-1.2 kW |
| Bus voltage | peaked at 54.8 V (B300 pack 55.0 V) |

- **Charging stops completely when the B300 flips from 99 to 100 %.** At 22:52 net
  charge power went to zero and has stayed there (AC in equals AC out, Vatrer currents
  0). On Saturday the B300 sat at 99 % for six hours with the bus at 54.1 V and charging
  continued, throttled. So 99 % is "counter full, still charging" and 100 % is a
  voltage event at about 55.0 V on the B300 that ends the charge.
- **The inverter will not take the Vatrers to their own full voltage.** The bus never
  passed 54.8 V; the Vatrer counters reset at about 56-57 V. Three Vatrer counters still
  read 80-86 %. "Charge until all Vatrers read 99 % or the bus reaches 56 V" is
  therefore not reachable with the inverter's own charger.
- **The Vatrer counters probably read low rather than the packs being under-filled.**
  All four sit on the same bus at the same voltage; Vatrer 1 reached 100 by counting,
  not by a reset; at 54.8 V with only 3-8 A per pack an LFP pack is close to full.
  Not proven. A bottom anchor (below) would settle it.
- **The counters count consistently.** Discharge Sat 12:05 to Sun 15:00 took 2.46,
  2.64, 2.43, 2.51 kWh DC from the four Vatrers for 44-47 points each; the recharge put
  back 2.62, 2.82, 2.46, 2.59 kWh for 43-50 points. About 5.5 kWh per 100 points both
  ways, and about 96 % DC round trip.
- **Whole discharge, Sat 12:05 to Sun 15:00:** AC out 15.97 kWh, PV 2.81 kWh, so
  13.16 kWh from the bank for B300 99 to 23 %, 0.173 kWh per percent.

**The inverter's AC sensors do not give the true cost of a charge.**

- In bypass (Sun 23:30 to Mon 00:20) Vue mains, AC in and AC out agree: 0.50, 0.49,
  0.48 kWh. Load outside the AC500 was about 10 W then.
- While charging overnight Friday, Vue mains read 110-175 W more than AC in every hour
  (2.3-2.6 kW charging). Most of that is not other load, so AC in under-reads by
  roughly 5 % while charging.
- The closed cycle "delivered 13.16 kWh, took 11.9 kWh to refill" is over 100 % and
  therefore not real. Vatrer DC out plus the B300 is about 12.4 kWh, less than the AC
  the inverter claims to have delivered from it. AC out probably over-reads in inverter
  mode (it cannot be checked against the meter there), or PV under-reads.
- Load outside the AC500 is not small on weekends: 10.5 kWh over the 27-hour discharge
  (389 W average; dryer and oven class loads). The "40-50 W at night, 100 W by day"
  figure holds for quiet hours only.
- Consequence: learn curves in the inverter's sensor units (they are self-consistent
  for planning), and take cost and savings from the Vue.

### The B300 can park: 27-28 December 2025

One past event contradicts "the inverter hands over at 3 % whatever the Vatrers hold".
Hourly statistics, 2025-12-27 18:00 to 2025-12-28 12:00 PST:

| Time | B300 % (min) | Bus V (min) | Vatrer 1 / 2 / 3 % | AC in W | AC out W |
|---|---|---|---|---|---|
| 12-27 18:00 | 4 | 52.2 | 41 / 37 / 38 | 0 | 594 |
| 12-27 20:00 | 1 | 51.9 | 37 / 33 / 32 | 0 | 772 |
| 12-28 00:00 | 1 | 51.8 | 32 / 26 / 25 | 0 | 396 |
| 12-28 05:00 | 1 | 51.2 | 24 / 17 / 17 | 0 | 413 |
| 12-28 08:00 | 1 | 50.3 | 17 / 11 / 9 | 3 | 608 |
| 12-28 10:00 | 1 | 49.9 | 14 / 7 / 6 | 0 | 618 |
| 12-28 11:00 | 0 | 48.2 | 13 / 6 / 5 | 647 | 438 |
| 12-28 12:00 | 6 | 52.0 | 21 / 13 / 14 | 1385 | 133 |

- The B300 read 1 % for 15 hours while the inverter stayed on battery and delivered
  about 7.4 kWh AC (sensor units). The Vatrers carried the house from about 35 % down
  to about 5-13 %. Vue mains showed 50-110 W the whole time, so the grid was present
  and the AC500 was not using it.
- It ended when the bus reached 48.2 V and the B300 read 0 %; grid input appeared in
  the same hour and charging followed. Whether the inverter did that or Dan did is not
  known.
- Bus voltage fell slowly, 51.9 to 49.9 V over about 7 kWh, then 1.7 V in the last hour.
- A second deep event, 2025-07-19 (two B300s then): B300 fell steadily to 0 % and the
  bus to 48.3 V under 1.2-1.7 kW, with the one monitored Vatrer at 5 %. Everything was
  empty together, so nothing parked.
- This is the only parked event in 18 months. Since January 2026 the B300 has touched
  3 % in 65 hours and never gone lower; grid input took over each time.
- So the 3 % handover is a property of the current mode or settings, not of the
  batteries. What differed in December 2025 is not known (Dan to say). Candidates:
  `number.ac500_battery_range_start` (2 now), a different UPS mode, or grid charging
  switched off. The hardware change (two B300s to one, fourth Vatrer added) happened in
  the same month.
- Recent data agrees in direction: in the last ten days the 4-6 % band delivered
  0.40 kWh per B300 point against 0.13-0.23 elsewhere, and the Vatrer share of the load
  rose from about 77 % to about 85 % below 12 %. Only 2.4 hours of data.
- If the floor can be moved, the Vatrer charge now left behind (about 5-7 kWh) becomes
  usable, the bus voltage becomes the gauge below the B300's floor, and the bottom
  becomes a reachable anchor for the Vatrer counters (all near 5 % at 48 V).

Method and design consequences: `docs/battery-bank-methodology.md`.


## 8. Offline replay of the learned model (2026-11-16)

Scripts: `analysis/scripts/learned.py` (the learner, pure Python), `replay_learned.py`
(prediction accuracy), `replay_cost.py` (dollars; not yet trustworthy, see below).
Walk-forward: every prediction uses only data from before the day being predicted.
Hourly statistics, 2026-01-15 to 2026-11-15, 210 TOU days.

### 8a. Gauge tracking

Start from the measured gauge at 07:00, feed the measured hourly load, PV and grid
input, predict the gauge at 17:00 and 21:00. Error in gauge points.

| Model | 17:00 bias | 17:00 mean abs error | 21:00 bias | 21:00 mean abs error |
|---|---|---|---|---|
| Current (percent x 0.235 kWh) | -10.7 | 13.2 | -6.7 | 10.3 |
| Fixed corrected scale, 0.16 (best constant is 0.14-0.16, chosen with hindsight) | -4.5 | 6.5 | -3.8 | 6.3 |
| Learned curves (5-point bins, 30-day half-life) | -0.2 | 4.7 | 0.0 | 5.4 |
| Learned curves plus a second input (Vatrers in or out of band) | -0.7 | 4.5 | -0.5 | 4.8 |

- The learned model halves the current model's error and removes its bias, with no
  constant to tune. Against a well-chosen fixed constant it is about 10-25 % better.
- Results barely move with half-life 14, 30 or 90 days or bins of 2, 5 or 10 points.
- A second input helps by about 10 %. Not worth the complexity in the first version.
- Solar charging needs its own curve (PV is measured on the DC side). Without it the
  learned model lost to the fixed constant in summer.
- About 5 points of error remain. Part of that is the hourly data (the gauge at an hour
  boundary is estimated from hourly min and max). The integration will sample
  per minute.

### 8b. Load forecast, 07:00-21:00 on TOU days

| Model | Bias kWh | Mean abs error kWh | Days short by more than 0.5 kWh (of 210) |
|---|---|---|---|
| Current, 0.6 kW flat (8.4 kWh) | -0.5 | 1.3 | 80 |
| Learned profile, trailing 14 TOU days, mean | 0.0 | 1.1 | 55 |
| Learned profile, 80th percentile of the window | +0.6 | 1.4 | 31 |

Day-to-day load varies by more than a kWh whatever the model, so the planner should
plan to a high percentile, not the mean.

### 8c. A gauge point is not worth the same going in and coming out

Clean 5-minute intervals, last ten days, inverter sensor units:

| B300 band | Charge, kWh per point | Discharge, kWh per point |
|---|---|---|
| 0-10 | 0.113 | 0.186 |
| 10-20 | 0.126 | 0.215 |
| 20-40 | 0.13-0.14 | 0.128 |
| 40-60 | 0.153 | 0.211 |
| 60-95 | 0.14-0.15 | 0.14-0.15 |
| 95-100 | 0.60 (B300 at 99 %, Vatrers still filling) | 0.17 |

- Over a full swing the two curves agree (about 15.3 kWh each way from floor to 100).
  Over a shallow cycle at the low end they do not: charging 3 to 20 % takes about
  2 kWh, discharging 20 to 3 % gives about 3.4 kWh. The Vatrers supply about 82 % of
  the energy in both directions, so the difference comes out of the Vatrers.
- Inference, not proven: shallow top-ups at the low end, which is what the system did
  all autumn, lower the Vatrers relative to the B300 a little each cycle. That would
  explain the 30-point drift of the band and the fall to 0.13-0.15 kWh per point.
- The gauge saturates at the top: at 99 % a "point" absorbs four times the energy.
- So a one-gauge curve is reliable for a discharge that starts from a full charge and
  unreliable for shallow cycling at the bottom. Charging until the inverter stops
  every TOU night in winter keeps the bank in the regime where the curve holds.

### 8d. Dollar replay (corrected 2026-11-16, replaces an earlier version of this section)

The first version simulated policies on the learned curves themselves and failed its
energy check (policies used 14-21 % less grid energy than reality, because of 8c). Its
conclusion that "the money is mostly in the scheduling rules" was wrong and is
withdrawn.

`replay_cost.py` now runs on `bank_model.py`, a two-store model (B300 and Vatrers) in
which each store conserves energy and the B300 takes a measured share of the power by
band and direction.

- Validation: fed the measured power over the calibration weekend (50 hours, a full
  charge, discharge and recharge), it follows the B300 gauge to 3.5 points and the
  Vatrer counters to 1.7 points mean error.
- A first attempt that treated the batteries as plain voltage sources in parallel
  failed that validation (gauge error 11 points): it makes the B300 follow the Vatrers'
  state of charge. The real bank shares power about equally per battery, so the B300
  is evidently behind its own converter.
- Energy check: simulated totals are within 5-8 % of the measured grid energy in
  January, October and November. In February, March and September the model needs
  10-20 % more than reality did, and far more in April. So only compare simulated
  policies with "actual" in January, October and November; elsewhere compare simulated
  policies with each other.
- The planners see only the gauge. The learned planner learns its curves and load
  profile from the simulated system day by day, as the integration would.

Cost of grid energy into the AC500, dollars per month at Time of Day prices:

| Month | Actual | New rules, old model | New rules, learned model | New rules, charge to full |
|---|---|---|---|---|
| 2026-01 (from the 15th) | 15.75 | 17.09 | 14.97 | 14.14 |
| 2026-02 | (17.20) | 19.99 | 19.20 | 20.70 |
| 2026-03 | (17.51) | 21.80 | 20.57 | 22.97 |
| 2026-10 | 21.43 | 19.16 | 18.04 | 21.25 |
| 2026-11 (1st to 15th) | 24.30 | 21.93 | 18.60 | 17.29 |

"New rules": a forecast never starts a charge; the overnight charge is timed to end at
07:00 and the battery is held until 07:00; mid-peak charging only when the peak window
would be short, finished by 17:00; never in peak; a top-up to full after the last TOU
day of the week in winter. "Old model" is percent x 0.235 kWh and 0.6 kW; "learned" is
section 8a/8b with the 80th percentile of load (50th to 95th changes a month by under
$1).

- **November as run cost $24.30 for half a month; the new rules with a full charge
  every TOU night cost $17.29.** About $7 per half month, $12-14 a month in these
  conditions. October: about $3.40 with the learned model.
- **The rules alone are not enough.** With the old battery model the new rules still
  left 23 kWh of mid-peak and 8 kWh of peak import in half of November. The learned
  model is worth about $2-3 a month over the old model under the same rules in winter.
- **November to January: charge to full.** It cost no mid-peak or peak import at all
  and beat the learned sizing by about $1 a month.
- **February and March: size the charge.** Charging to full cost $1.50-2.40 a month
  more than the learned sizing there (solar is wasted). In April to September a nightly
  full charge is far worse, as expected.
- The "hindsight" column of the script is not a valid lower bound yet (it still shows
  peak imports) and is not quoted.

## 9. Monday 2026-11-16: a weekday on a full bank

The bank started the day full (B300 100 %, Vatrers 99 / 88 / 82 / 81 %) and the
integration was unchanged. Data pulled 21:06 PST.

| Window | AC500 grid in kWh | AC500 out kWh | PV kWh | Vue mains kWh | B300 % |
|---|---|---|---|---|---|
| Off-peak 03:00-07:00 (on battery) | 0.00 | 2.10 | 0.00 | 0.33 | 100 to 87 |
| Mid-peak 07:00-17:00 | 0.00 | 6.57 | 3.51 | 1.27 | 86 to 65 |
| Peak 17:00-21:00 | 0.00 | 3.14 | 0.00 | 0.70 | 65 to 47 |

- **No grid energy went through the inverter from 03:00 to 21:00.** No mid-peak or
  peak charge. The 2.0 kWh the house meter saw in mid-peak and peak is load outside
  the AC500.
- The day ended peak with the B300 at 47 % and the Vatrers at 54-73 %: about half the
  bank unused, on a sunny day (3.5 kWh PV).
- 8.3 kWh delivered by the bank for 53 gauge points: 0.157 kWh per point.
- The battery still carried the house from 03:00 to 07:00 at off-peak prices (2.1 kWh,
  13 gauge points). The new planner holds until 07:00 instead.
- For comparison, the six weekdays before the test averaged 4.7 kWh mid-peak and
  1.9 kWh peak import through the house meter, of which 1.8 and 0.6 kWh were battery
  charging.

## 10. Shadow log (0.7.0, classic planner in control)

One row per TOU day while the learned planner only observes. Gauge is the B300 percent.

| Day | Classic overnight | Gauge 07:00 | Learned would have | Learned prediction 17:00 / 21:00 | Actual 17:00 / 21:00 | Inverter grid kWh mid / peak |
|---|---|---|---|---|---|---|
| Tue 11-17 | No charge at 03:00-06:00 ("projected minimum 2.97 kWh, above the 1.5 floor") | 22 | Charged to full from 21:00, held to 07:00 | 14.6 / 3.0 (floor) | 18 / 11.8 | 0.0 / 0.0 |
| Wed 11-18 | Charged 03:00-04:48 to 38 %, then released to PV_PRIORITY (no hold); 26 % at 07:00 | 26 | Charged to full from 21:00 Tue, held to 07:00 | 3.0 / 3.0 (floor by 17:00) | 17 / 8 (after 4 mid-peak top-ups) | 4.02 / 0.0 |

Notes, Tue 11-17:

- First night on a real Home Assistant: the minute tick ran, the shadow record filled
  in, no errors in the log.
- The two planners disagree in the expected direction. Classic reads 22 % as 5.2 kWh
  and sees no need to charge. The learned curve reads it as 3.8 kWh and expects the
  battery to reach its floor before 21:00, short by about 2.2 kWh for the peak window.
- Part of the low start is from the deploy: the 21:41 restart released Monday's hold
  and the battery carried the house overnight (47 % at 21:00 to 22 % at 07:00). With
  the hold intact classic would have started near 47 %, still without charging.

Tue 11-17 evening result:

- Classic made the right call: no charge at all, zero grid energy through the inverter
  in mid-peak and peak, battery at 11.8 % at 21:00. The house drew 1.1 kWh mid-peak and
  0.5 kWh peak from the grid outside the inverter (by design).
- Learned load forecast was good: 9.13 kWh forecast, 8.86 kWh actual for 07:00-21:00.
- Learned gauge prediction: 17:00 off by 3.4 points (inside the 5-point target),
  21:00 off by 8.8 points (outside it), both on the pessimistic side. Had the learned
  planner been in control it would have started a mid-peak top-up it did not need
  (`midpeak_charge_wanted` stayed true).
- Cause: the low end of the discharge curve. The curve says about 0.20 kWh per point
  below 22 %. Measured today, 17:00-21:00 (no solar, no grid): 2.61 kWh AC for
  6.2 points, about 0.42 kWh per point. Between 12:00 and 17:00 the gauge rose from
  16 % to 20 % while the bank as a whole was a net source (load 2.94 kWh, solar 2.11 kWh
  DC). Both fit the idea that at low charge the third-party packs carry more of the load
  and may even top the B300 back up, so the gauge falls more slowly the lower it gets.
  The calibration weekend saw the low end after a long discharge with the third-party
  packs also low; today they started from a full charge on Monday. One gauge cannot see
  that difference.
- Consequence for winter: small, because in full-charge months the learned planner
  charges every TOU night and rarely reaches the low end. It matters for the shoulder
  months and for the mid-peak top-up rule. Watch Wed-Fri before changing anything; the
  Saturday low-end test is the place to measure it.

Wed 11-18 (dark day, 1.1 kWh solar):

- Classic charged 03:00-04:48 and then switched to PV_PRIORITY instead of holding, so
  the battery spent about 12 gauge points on the house at off-peak prices before 07:00.
- It then made four mid-peak top-ups at 07:12, 09:36, 12:00 and 14:24, exactly
  144 minutes apart: the Solcast refresh cadence (section 2, H9), live on the box.
  Integration count 6.34 kWh in its own units; 4.02 kWh through the inverter in
  mid-peak. Nothing in peak. Its own scorecard graded the day D (64).
- The learned prediction cannot be scored directly because classic's charges are not
  in it. As a rough check, the top-ups added about 27 points by classic's own count;
  without them the gauge would have reached its floor before 17:00, which is what the
  learned planner predicted at 07:00.
- Learned load forecast again close: 9.19 kWh forecast, 9.26 actual.
- Cost of the difference, roughly: 4.0 kWh bought at mid-peak instead of off-peak is
  about $0.31 for the day.

## 11. AC500 low-end settings and link reliability (2026-11-17)

Dan photographed the AC500's settings screens; the photo timestamps match changes in
Home Assistant's history to the second, which ties each screen to an entity.

- **Battery SOC Low / "Reserved capacity for PV charging" is one value**, exposed in
  Home Assistant as `number.ac500_battery_range_start` (currently 2). Dan set it to 0 and
  back to 2 while browsing (2 -> 0 -> 2 ten seconds apart in history); the PV Priority
  screen showed 0 at the same second and the Time Control SOC screen showed 2 later.
  The unit's own help text: below this value the load is powered by the grid in bypass,
  and "setting it at 0 may cause the failure of bypass function". With 2 the observed
  handover is at gauge 3 % (65 hours at 3 % since January 2026, grid took over each time).
- **Deep Discharge** (off) is not the low-end setting. Its help text: only available when
  SOC is 0 %, damages the pack, emergency use only. Leave it off.
- Likely explanation of December 2025 (inferred, not proven): the value was 1 or 0. The
  B300 parked at 1 % while the Vatrers carried the house, and the grid took over in the
  hour the B300 reached 0 % (bus 48.2 V), which is what this setting does.
- Forum reports from other AC500 owners include bypass not engaging at SOC Low; on this
  unit at 2 it has engaged every time. Whether it does at 1 is what Saturday tests.

- **A 2-minute charge every night at about 23:16** (seen 2026-11-18: 2.5 kW from
  23:16:26 to 23:18:26 in TIME_CONTROL; the same burst is in the 23:15 bucket on every
  night with a hold since at least 11-08). Cause: the AC500's own Time Control schedule
  has "Period 1: Charge 00:00-00:01" (photo), and the AC500's clock runs about 44 minutes
  fast. Harmless (about 0.08 kWh off-peak), but anyone using the AC500's own schedule
  should correct its clock first.

Link reliability, from 18 months of hourly statistics (2025-05-31 to 2026-11-17).
Missing rows are easy to see; frozen values (a house load reported to the watt for
hours) are the worse failure because they look healthy.

| Start (PST) | AC500 data | Vatrer data |
|---|---|---|
| 2025-10-28 00:00 | frozen 7 h | frozen 7 h |
| 2025-11-30 06:00 | frozen 16 h | frozen 16 h |
| 2026-02-16 00:00 | frozen 11 h | frozen 11 h |
| 2026-04-20 18:00 | frozen 20 h, then missing 54 h | normal |
| 2026-05-02 13:00 | frozen 93 h | frozen 93 h |
| 2026-05-07 08:00 | output power missing 4 h | normal |
| 2026-09-14 17:00 | normal | missing 5 h |

- Home Assistant itself was up: the only hours missing for everything are three single
  hours. The failures are in the battery data path, about 210 hours in all (1.6 % of the
  time), five long episodes, none on the AC500 side since May 2026.
- Four of the five long episodes froze the AC500 and the Vatrer readings together, so a
  voltage guard on the Vatrer sensors fails at the same moments as the gauge. Commands
  to the inverter probably travel the same path (not verified).
- Design consequence: Home Assistant can be the first line at the bottom, not the only
  one. The inverter's own SOC Low must stay set to a value where bypass works, and the
  integration needs a staleness check (a reading that has not changed for some minutes
  counts as missing), not just an unavailable check.

