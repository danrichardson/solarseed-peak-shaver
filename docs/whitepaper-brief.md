# Brief: turn the winter 2026 work into a white paper

This is a prompt for an agent. Hand it over as written, in a session opened at the root
of this repo on the workstation that holds `analysis/` (the data is not in git).

---

## What to produce

A white paper, as a PDF with its HTML source, that a solar-and-battery owner or a home
automation engineer could read cold and learn from. Working title:

> **What is a percent worth? Peak shaving with a mixed battery bank behind a consumer inverter**

Author on the title page: **Daniel Richardson**. Also on the title page: date,
revision number, and one sentence saying what the paper is. Page 2: a revision history
table and a table of contents. Start at revision 0.9 (draft); 1.0 is reserved for when
the two pending sections below have real data.

Length: 12 to 20 pages. Figures and tables numbered and captioned. Page numbers.

**Status (2026-11-22).** A reproducible revision 0.9 already exists: build package in
`analysis/whitepaper/` (one command, `python analysis/whitepaper/build.py`), output in
`docs/whitepaper/`, written before the low-end test. Update that package; do not start
over. The low-end test (weekend of 2026-11-21) is done, so section 11 now has real data:
make the next revision 0.95. Revision 1.0 still waits for one pending item, a week with
the learned planner in control (section 10, figure 15).

**Out of scope:** grid-outage resilience and generator planning. That is a separate,
private planning document for the owner (household loads and habits do not belong in a
paper with a real name). This paper may mention, in one sentence under open questions,
that the same measured bank model supports an outage analysis.

## Who reads it

People who own or build systems like this one: Home Assistant users, off-grid and
hybrid-inverter owners, engineers curious about the method. They know what a kWh and a
time-of-use tariff are. They do not know this house, this repo, or any of our working
labels. Define every term on first use, and never refer to "H9", "section 2f", script
names or agent sessions in the body text.

The reader should come away with three things: the story (a planner that looked fine
and quietly cost money), the method (how to find out what your own battery gauge
means), and the design that follows (a planner that measures instead of assuming).

## Sources, in the order to read them

1. `docs/battery-bank-methodology.md` - the method, the principles, the mistakes.
2. `docs/winter-2026-findings.md` - every measurement, with corrections marked.
3. `docs/analysis-plan.md`, "Decisions log" at the bottom - what was decided, when, why.
4. `docs/how-it-works.md` - how the integration and both planners work.
5. `analysis/scripts/` - the code behind every number. `analysis/data/raw/` - the data.
6. `README.md` - what the integration is, for the introduction.
7. The low-end test: `docs/weekend-test-2026-11-20.md` (what was done, minute by minute)
   and its data, all local:
   - `analysis/data/raw/lowend_2026-11-21.csv` - one row a minute, Fri 22:26 to Sun:
     gauge, mode, reserve, AC in/out, solar, B300 pack voltage, four Vatrer voltages and
     percents.
   - `analysis/data/raw/history_lowend_wk1.json`, `_wk2.json`, `_wk3.json` - recorder
     history at full resolution (about 5 s) for Tue 11-17 to Sun 11-22, including
     per-pack Vatrer current. Home Assistant deletes this after about 10 days; these
     files are the only copy.
   - `analysis/data/live_changes/handover_history_2026-11-22.json` (seconds around the
     handover) and `sag_checks_2026-11-21.md` (load-step windows).

## Rules that matter more than polish

- **Regenerate, do not transcribe.** Every number and every chart in the paper comes
  from a script you save under `analysis/whitepaper/`, reading `analysis/data/raw/`.
  Where your number differs from the docs by more than rounding, stop and list it in
  your report; do not silently pick one.
- **Keep the corrections in.** This work changed its mind several times and the paper
  is more useful for saying so: a savings estimate that halved; a "usable capacity"
  quoted before anyone knew what the gauge was attached to; a claim that the small
  battery never parks at low charge, overturned by one event found in older data; a
  first cost simulation that created energy from nothing; a physical battery model that
  failed validation and was replaced by a measured one; a low-end test planned around "the inverter will run to 1 % once the reserve is 1 %", which it did not; and a voltage floor that was designed before the test showed voltage was nowhere near a cliff. A short "what we got wrong and
  how we noticed" section is required.
- **Say what is not established.** One house, one winter, one inverter model. The
  sensors do not close an energy balance. The cost replay matches reality to 5-8 % in
  some months and 10-20 % in others. Say which claims are measured, which are replayed
  and which are inferred.
- **Privacy.** The paper carries a real name. No IP addresses, host names, account
  names, credentials, or anything about when the house is occupied or empty. Entity
  names of sensors are fine where they help. Tariff figures are public.
- **Do not touch the live system.** Work from the data already pulled. If something you
  need is missing or stale, say so in your report.
- Source files you write are ASCII (use HTML entities for symbols).

## Suggested shape

1. **Summary** - one page: the problem, the three findings, the result in dollars.
2. **The system and the tariff** - one diagram: grid, inverter, one first-party battery
   the inverter can see, four third-party packs it cannot, solar, house. The three
   price windows and why charging at the wrong hour matters.
3. **The symptom** - daytime grid charging that should not happen.
4. **Finding 1: the forecast was pulling the trigger.** Every daytime top-up lines up
   with a solar-forecast refresh.
5. **Finding 2: a percent is not what you think.** The gauge follows the smallest
   battery; energy per percent is 55-75 % of what was assumed and moves over time.
6. **The experiment** - a weekend full charge and discharge on cheap power: what was
   controlled, what it settled.
7. **How the bank really behaves** - equal power per battery, not per kWh; the slow
   tail at the top; charging ends on a voltage event; a percent costs less going in
   than it gives coming out at the low end; the small battery can park at 1 % while
   the others carry the house.
8. **Voltage: a good anchor, a poor ruler.** Show it with the run-down: from full to
   the handover the bus fell only from about 53 to 50.6 V under load, smooth, no knee,
   while the gauge went from 100 to 4 %. Load sag was about 0.25-0.4 V per kW. Voltage
   marks the ends (the full flip at about 55.4 V; the handover region) and cannot
   measure the middle. Include the load-step sag measurement.
9. **The design** - learn the discharge curve, the charge curve and the load profile;
   plan against the tariff windows; the rules in plain words.
10. **Does it work?** - prediction accuracy against the old model and against a fixed
    corrected constant; the validated battery model; the cost replay by month; the
    first weekday on a full bank. **Pending:** a week with the new planner in control.
11. **The low-end test** (weekend of 2026-11-21; numbers below are first-pass, from
    the minute log and the recorder history; regenerate them):
    - Full charge Friday night; the B300 read 99 % from early Saturday and flipped to
      100 % only around midday, with the third-party packs at 100/90/81/82 %.
    - Run-down on house load plus a heater: 18.7 kWh AC from 100 % to the handover in
      12 hours. 100 to 21 %: 10.6 kWh (about 0.13 kWh per point). 20 % to the handover:
      8.1 kWh (about 0.5 per point). The last fifth of the gauge held 43 % of the energy.
    - The handover happened when the inverter's total gauge first read 3 %, in the same
      5-second sample as the grid input step, with the reserve set to 1 %. With the
      reserve at 2 % it has always happened at 3 % too. So lowering the reserve did not
      move the transfer point; the mechanism (a firmware floor, or a per-mode reserve) is
      not established. Present this as measured fact plus open question.
    - No blink in the 5-second data (output stayed at 1.44-1.47 kW). At the handover the
      inverter grid-charges the small battery to its 10 % recovery level and stays on
      grid until then (also seen on three weekday evenings); cost implication in peak.
    - Nothing was physically empty at the handover: 50.6-50.7 V under 1.5 kW, one
      third-party pack still reading 19 %.
    - Recharge from the handover: time and energy to full (fill in from the data; it
      was still running Sunday morning).
11a. **Battery health and the third-party counters.** Integrating each third-party
    pack's current over the run-down: 84.5, 89.3, 85.3 and 84.6 Ah delivered, nearly
    equal, as parallel packs at one voltage should be. Their own percent counters moved
    80-86 points for that, implying about 104-107 Ah each against 100 Ah nameplate: no
    sign of capacity loss after about 18 months (inferred, one run, counter-based). But
    the counters ended at 19/4/0/2 % with the packs at the same voltage: the counters
    are offset from each other by up to about 19 points and do not converge, because
    charging stops (small battery flips to 100 % at about 55.4 V) before the packs reach
    the voltage where their BMS resets to 100 %, and discharge stops (3 % handover) long
    before the low-voltage point where it would reset to 0 %. Lesson for readers: a
    third-party pack's percent is a coulomb counter with no recent reference point;
    trust its current and voltage, not its percent.
12. **What we got wrong and how we noticed.**
13. **A method you can reuse** - the principles as a checklist for any system where the
    inverter's percent is the only gauge.
14. **Limits and open questions.**

## Figures to build (each from data, each with a caption that states the takeaway)

| # | Shows | Data |
|---|---|---|
| 1 | System diagram | drawn |
| 2 | One early-November weekday: grid input, battery percent, forecast refresh times marked | 5-minute statistics |
| 3 | Energy per gauge percent: assumed against measured, by period | hourly statistics |
| 4 | The calibration weekend: small-battery percent, mean third-party percent, charge power | 5-minute statistics |
| 5 | Energy delivered per battery over the test discharge (equal bars, unequal capacities) | 5-minute statistics |
| 6 | Charge against discharge energy per percent, by gauge band | 5-minute statistics |
| 7 | The December 2025 run-down: gauge parked at 1 % for 15 hours while bus voltage and the other packs fall | hourly statistics |
| 8 | Bus voltage against state of charge through the test, with the three usable checkpoints marked | 5-minute statistics |
| 9 | The learned discharge curve and the learned hourly load profile | `learned.py` on the data |
| 10 | Prediction error at 17:00 and 21:00: old model, fixed constant, learned | `replay_learned.py` |
| 11 | Battery model against measurement over the weekend | `bank_validate.py` |
| 12 | Monthly cost: as run, new rules with old model, new rules with learned model, charge to full | `replay_cost.py` |
| 13 | A day under the new rules, as a timeline of modes against the price windows | drawn |
| 14 | Monday 2026-11-16 on a full bank, by price window | 5-minute statistics |
| 15 | Before and after, per weekday: mid-peak and peak energy through the inverter | **pending** |
| 16 | **Voltage curves of the run-down:** B300 pack voltage and the four third-party pack voltages against energy delivered since full (x axis kWh, not time), with the gauge on a second axis and the 100/20/10/5/3 % points marked | minute CSV, recorder history |
| 17 | **Voltage against gauge, charge and discharge overlaid** (Friday-Saturday charge, Saturday run-down): the hysteresis between charging and discharging voltage at the same percent | minute CSV |
| 18 | **Load-step sag:** voltage during the heater on/off windows, at about 96 %, 52.5 V and lower; volts per kW | `sag_checks_2026-11-21.md` windows, minute CSV |
| 19 | **Energy per gauge point by band** from the clean full run-down (bars for 100-80, 80-60, ... 20-10, 10-handover), against the assumed 0.235 | minute CSV |
| 20 | **The handover, seconds:** gauge, AC input, AC output, bus voltage from one minute before to five minutes after | `handover_history_2026-11-22.json` |
| 21 | **Third-party packs: Ah delivered against what their counters say** (equal bars of Ah; counters ending 19/4/0/2 %) | recorder history (per-pack current) |
| 22 | **The full charge:** charge power and the five voltages against time, showing the 99 % plateau and the 100 % flip where charging ends | minute CSV, recorder history |

One accent color for "what we assumed" and one for "what we measured", used the same
way in every chart. Units on every axis, local time, color-blind-safe. Tables for
exact values, charts for shape.

## Findings and the features they produced

Dan wants the paper to point from each thing we learned to the part of the algorithm
that answers it, and to show how that part learns. Use this table as the backbone of
section 9 (the design) and check each row against the code before quoting it.

| Finding | Feature | How it learns or decides | Code |
|---|---|---|---|
| Daytime charges lined up with forecast refreshes | A forecast update never starts a charge; charging is decided by tariff window | Rules, not learned | `planner.decide` rules 1-2 |
| A gauge percent is worth 0.13-0.20 kWh, not 0.235, and drifts | Learned discharge curve | AC energy per gauge point in 5-point bins, 30-day half-life, prior 0.235 with weight 3 points | `learning.Curve`, `Learner.sample` |
| Charging slows at the top; full takes 8-20 h | Learned grid-charge curve with time | Energy and hours per point, timed only at full rate | `Curve.hours_per_pt`, night timing in `planner.decide` |
| Fixed 0.6 kW base load under-forecast by 0.5 kWh/day | Learned load profile | Hourly mean per day type over 14 days, sized at the 80th percentile | `learning.LoadProfile` |
| Charging stops when the B300 flips to 100 % | "Bank full" detection | Gauge 100, or 97-99 with charge commanded and stalled 10 min | `learned_runtime._update_bank_full` |
| The bank drifts out of its band | Weekly top-up after the last TOU day | Rule, months configurable | `planner.decide` rule 4 |
| Releasing the hold spends off-peak battery that is then bought back in mid-peak (11-18) | Hold until 07:00 after the night charge | Rule | `planner.decide` rule 3 |
| Mode commands can be lost | Verify from power sensors, resend 3 times, then alert | Measured | `learned_runtime._act` |
| In deep winter a full charge every night beats sizing | Full-charge months | Replay on a validated bank model | `full_charge_months` option |
| The low end is worth more than twice as much after a full charge (11-17; 11-21: 0.5 vs 0.13 kWh per point) | Learned discharge curve learns from full-anchored run-downs; pending: energy counted from the full anchor | Weekend test 11-21 | `learning.Curve` (exists); counter proposed |
| Lowering the inverter's reserve from 2 to 1 % did not move the handover; it is at gauge 3 % (11-21) | The planner's floor stays at gauge 3 %; the voltage floor is dropped (voltage was nowhere near a cliff at the handover) | Measured | `gauge_floor` option (exists) |
| Third-party pack percents drift apart and never reset in this charge regime (11-21) | The planner never uses third-party percents; only the inverter's gauge, power and voltage | Design rule | n/a |
| The battery data path froze for up to 4 days (2025-2026) | Pending: staleness check; inverter SOC Low kept as backstop | Reliability record | proposed |
| A parked gauge would credit hours of energy to one point | 0.7.1: cap one point at 2 h / 1 kWh | Guard on learning | `Learner.sample` (0.7.1, live since 11-19) |
| A restart released the evening hold (11-16) | 0.7.1: the first calculation after a start changes nothing | Rule | `coordinator._events_armed` |
| Running out in peak triggers the AC500's own grid charge, about 7 points at peak price (11-19) | Pending: treat the handover as a cost, not a floor; keep margin above it in peak | Shadow log 11-19, history 11-11 and 11-13 | proposed |

## How to build it

Your choice of tools, with these constraints: charts as vector graphics; one HTML file
with a print stylesheet (title page, running page numbers, figures that do not split
across pages); a PDF made from it with a headless browser; a single command that
rebuilds everything from the data. Put it all in `analysis/whitepaper/` and copy the
finished PDF and HTML to `docs/whitepaper/`.

## Before you hand it back

- Rebuild from scratch with the one command and open the PDF: title page, contents,
  every figure present and legible in grayscale, no figure split across pages.
- Check every number in the text against the table or chart it refers to.
- Read it once as the intended reader, and remove anything that only makes sense to
  someone who was in the room.

Report back: the paths, the rebuild command, every number that differed from the docs,
anything you could not source, and what the two pending sections will need.
