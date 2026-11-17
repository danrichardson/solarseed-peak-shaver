# Characterizing a mixed battery bank behind a consumer inverter

How we worked out what Dan's battery bank really does, why the planner was wrong about
it, and the design that follows. Written 2026-11-15. The system is bespoke, but the
method is not: it applies to any setup where the inverter's "percent" is the only gauge
and you have reason to distrust it.

Measured results live in `docs/winter-2026-findings.md` (sections 2f and 7). This file
is the approach and the reasoning.

## The situation

- Inverter: Bluetti AC500. It reports one number, battery percent, and makes its own
  decisions from it (stop discharging at the floor, throttle charging at the top).
- Bank: one Bluetti B300 (3.07 kWh) and four Vatrer 51.2 V 100 Ah packs (about 5.1 kWh
  each), 23.5 kWh nameplate. The Vatrers are third-party and invisible to the inverter.
- The planner multiplied the inverter's percent by 23.5 kWh and planned charging from
  that. It consistently ran short.

## Principles we ended up with

1. **The billing meter is the truth.** Everything is ultimately judged by what the
   whole-house meter (Emporia Vue) imports in each tariff window. Device sensors are
   evidence, not truth.
2. **Check that sensors close an energy balance before trusting any of them.** Over a
   year the AC500's AC output exceeded grid input plus PV by 3.5 %. That is impossible,
   so at least one sensor is biased. Efficiency derived from those sensors alone would
   be wrong. Work in consistent "sensor units" and calibrate against the meter.
3. **A percent is a gauge reading, not an amount of energy.** Find out what the gauge is
   attached to. Here it is attached to the smallest battery only (the B300's own
   counter matched the inverter's total to 0.03 points all year).
4. **Measure energy per gauge unit instead of assuming it.** Divide AC energy delivered
   during battery-only hours by the change in the gauge, by gauge band and by period.
   This showed 0.20-0.22 kWh per percent in 2025 and 0.13-0.15 in late 2026 against an
   assumed 0.235, and the step lined up with a hardware change (two B300s became one).
5. **Counters drift; anchors fix them.** Every charge counter (the B300's and each
   Vatrer's) integrates current and accumulates error until it sees a full charge. At
   one shared bus voltage the five counters read 18, 31, 11, 11 and 10 %. A known-full
   state is the only reliable anchor. Without one for three months, the relationship
   between the counters had moved about 30 points.
6. **Voltage is a good anchor and a poor ruler.** LFP voltage is nearly flat through the
   middle, and it shifts with current. It cannot tell 55 % from 80 %. It can tell you
   three things reliably: full (about 56-57 V with current tapering), nearly empty
   (below about 51 V), and which plateau you are on (about 53.1 V upper, about 52.5 V
   lower at light load, with the step near half charge). Use those as checkpoints for a
   counter, not as the counter.
7. **Run an experiment when history cannot answer.** History could not separate "lost
   capacity" from "gauge on the wrong battery" from "drift". A controlled full charge
   and discharge over a weekend, on cheap power, did.
8. **Prefer history when it can answer, and search all of it.** "What happens when the
   gauge reads 3 %?" was first answered from eleven recent episodes: the grid takes
   over. That answer was true for the current settings only. A search of the full
   18 months for the lowest voltages found one event (December 2025) where the inverter
   stayed on battery for 15 hours with the gauge parked at 1 %. Look for the extremes
   and the exceptions, not just the typical case, and say which configuration a
   conclusion belongs to.
9. **The owner's recollection is data.** Dan said the inverter keeps going at a very low
   percent. The recent record said otherwise, and the record was incomplete.

## What the bank actually does

- **Power is shared roughly equally per battery, not per kWh.** Over the test discharge
  each of the five batteries gave about 2 kWh while the B300 fell 62 points and the
  Vatrers about 40. The small battery's percent therefore moves about 1.7 times faster.
- **The split is not constant.** The B300 carries 10-23 % of the load depending on where
  it sits on its voltage curve; it slows down when it is below a plateau step relative
  to the Vatrers. So there is some self-correction, but not enough to keep the
  percentages together.
- **The inverter acts on the B300 alone.** With the current settings it hands the house
  to the grid at B300 3 %, whatever the Vatrers hold. In spring 2026 that left the
  Vatrers at 12-32 %.
- **That floor is a setting, not physics.** In December 2025 the B300 parked at 1 % for
  15 hours while the Vatrers carried the house down to a 48 V bus (findings section 7).
  What made the difference is not yet known.
- **At the top, 99 % and 100 % are different things.** At 99 % the B300's counter is
  full and the inverter keeps charging at about 40 % power. At about 55.0 V the B300
  flips to 100 % and charging stops completely. The Vatrers never see the 56-57 V that
  resets their own counters.
- **A full charge from everything-empty takes about 20 hours:** about 8.5 hours until
  the B300 reads 99 %, then a long throttled tail. From B300 23 % and Vatrers about
  40 % it took 7 h 52 min.
- **The inverter's AC sensors are self-consistent but not meter-accurate.** AC input
  reads about 5 % under the house meter while charging, and a closed charge-discharge
  cycle comes out above 100 %. Plan in sensor units; take money from the meter.

## The operating idea: keep the bank anchored at the top

Because the B300 empties first, usable energy per cycle is whatever the bank delivers
while the B300 goes from full to its floor. That is largest when the Vatrers start full
too: then they end the cycle with charge to spare (about 20-40 %) instead of hitting
their own bottom early and leaving the B300 to carry the load alone.

- From a full start, the first 62 points of B300 delivered about 0.175 kWh AC per point.
- In the drifted state before the test, with the Vatrers bottoming out alongside the
  B300, it was 0.13-0.15.

So the practical recipe is:

1. **Weekly long top-up on the weekend.** Charge until the B300 flips to 100 % and the
   inverter stops by itself, not just until it reads 99 %. That is as full as this
   inverter will make the Vatrers. It restores the band. It does not reset the Vatrer
   counters (corrected 2026-11-16).
2. **Weekday nights: charge to B300 full.** About 9 hours from empty at full rate.
3. **The bottom is an open question** (changed 2026-11-16). The Vatrer charge left when
   the B300 hits its floor was thought unreachable. The December 2025 event shows it
   can be reached under some setting. Find the setting, test it once on a weekend, then
   decide on a routine floor by bus voltage (around 50 V, not the 48 V extreme).

## Design for the planner (proposed, not yet built)

Replace "percent times nameplate capacity" and "one fixed base load" with quantities
the integration learns from its own sensors.

1. **Learned discharge curve.** During battery-only intervals, accumulate AC energy
   delivered (minus PV) per gauge bin. Remaining energy at gauge reading g is the sum of
   the bins below g. Keep it as a decaying average so it follows drift and hardware
   changes. Needs a load power sensor.
2. **Learned charge curve.** During grid charging, accumulate AC energy and elapsed time
   per gauge bin. This gives energy and hours to reach a target, including taper and
   throttling, so "be finished by 07:00" can be planned honestly. Needs a grid input
   power sensor.
3. **Learned load profile.** Mean load by hour of day and day type from the load power
   sensor, trailing two weeks.
4. **Anchors.** The top anchor is the gauge reaching 100 % with charge power falling to
   zero (here that is a voltage event on the B300). A timeout ends the weekend top-up
   otherwise. An optional voltage sensor gives the nearly-empty and plateau
   checkpoints. If the floor test works, the gauge below the B300's floor is bus
   voltage or the Vatrer counters, as a second stage of the learned curve.
5. **Band monitor.** Optional auxiliary pack sensors. If the auxiliary packs are low
   when the main gauge is high, a top-up is overdue; say so.
6. **Tariff windows drive the schedule** (Dan's rules): forecasts update the plan but do
   not start a charge; off-peak charging is planned to end at 07:00; mid-peak charging
   only to cover 17:00-21:00 and ending by 17:00; never in peak.

Nothing in 1-3 is specific to Bluetti or to this bank. Any installation with a gauge, a
load sensor and a grid sensor gets a planner calibrated to what its hardware delivers.
Items 4-5 are where the bespoke knowledge goes, as optional inputs.

## Choices we made and why

| Choice | Why |
|---|---|
| Read-only access through HA's API, with a temporary admin user | Scoped, auditable, revocable by deleting the user. No SSH into the production VM |
| Raw recorder statistics over the integration's own scorecards | The scorecards depend on the calculations under suspicion, and had bookkeeping holes |
| One temporary, date-guarded automation for the weekend test | Runs on the box whether or not an agent is awake; retries failed mode commands; inert afterwards |
| Test on a weekend | 58 hours of off-peak power, so nothing is interrupted and the cost is trivial |
| Kept the Sunday recharge instead of running to the floor | Monday starting full is a better test. The other reason given then, that history already answered the floor question, was wrong (principle 8) |
| No rewiring, no added resistance | The equal-sharing behavior is worked around in software; the hardware idea involves milliohms on a proprietary cable |
| Plan from the inverter's gauge with a learned curve, not from the Vatrer counters | The inverter stops on its own gauge, so that gauge decides how much energy is deliverable. The Vatrer counters check the band |

## Mistakes worth not repeating

- Assumed 10-12 hours to full from a partial historical charge. It is about 20 from
  everything-empty. The test's discharge step fired with the Vatrers at 80 %.
- Estimated savings before subtracting load that is not behind the inverter. $20/month
  became $10/month.
- Used fixed Pacific Standard Time for summer months in a first tariff table.
- Called a capacity figure "usable" before knowing what the gauge was attached to.
- Told Dan the B300 "does not float at 3-5 %" from recent episodes only. One older
  event showed it parking at 1 % for 15 hours.
- Proposed "all Vatrers at 99 % or bus at 56 V" as the full condition before checking
  that the inverter ever gets there. It stops at about 55 V.
