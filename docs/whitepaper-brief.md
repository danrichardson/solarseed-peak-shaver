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
  failed validation and was replaced by a measured one. A short "what we got wrong and
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
8. **Voltage: a good anchor, a poor ruler.**
9. **The design** - learn the discharge curve, the charge curve and the load profile;
   plan against the tariff windows; the rules in plain words.
10. **Does it work?** - prediction accuracy against the old model and against a fixed
    corrected constant; the validated battery model; the cost replay by month; the
    first weekday on a full bank. **Pending:** a week with the new planner in control.
11. **Pending: the low-end test** (weekend of 2026-11-21).
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
| The low end is worth twice as much after a full charge (11-17) | Pending: energy counted from the full anchor, voltage floor | Weekend test 11-21 | proposed |
| The battery data path froze for up to 4 days (2025-2026) | Pending: staleness check; inverter SOC Low kept as backstop | Reliability record | proposed |
| A parked gauge would credit hours of energy to one point | 0.7.1: cap one point at 2 h / 1 kWh | Guard on learning | pending |

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
