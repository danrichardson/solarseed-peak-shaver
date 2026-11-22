# Roadmap

Feature ideas that came out of the winter 2026 work, roughly in order. Each links to the
finding behind it. Nothing here is committed to a release yet. Current state and
operating notes: `docs/HANDOFF.md`.

## Next (0.8.x)

1. **Capacity trend from every clean run-down.** On each discharge that starts from a
   full anchor (the small battery's flip to 100 %), integrate each third-party pack's
   current and the inverter's AC output between two fixed bus voltages (for example
   53.0 V and 51.5 V; pick two that most deep evenings reach). Store one point per run and
   expose a sensor per pack: "Ah between 53.0 and 51.5 V". A falling trend is capacity
   loss; a sudden step is a pack or wiring problem. Show it on the dashboard as a chart
   over months. Basis: the 2026-11-21 run-down, where each pack delivered 85-89 Ah and
   the counters implied about 104-107 Ah each (findings; white paper section 11a).
   Needs the per-pack current sensors to be configured (optional, like the power
   sensors today).
2. **Our own third-party pack state of charge.** The packs' percent counters drift apart
   (19/4/0/2 % at one voltage) and never reset in this charge regime. Count each pack's
   amp-hours from the last full anchor instead and expose that as the pack's charge
   estimate; show the BMS percent beside it for comparison.
3. **Treat the handover as a cost.** Running out in peak costs the shortfall plus the
   inverter's own recharge to its 10 % recovery level at peak price. The planner should
   keep margin above the 3 % handover during peak and count that cost when deciding a
   top-up (findings section 11).
4. **Staleness check.** A battery reading that has not changed for some minutes counts
   as missing, not just an unavailable one; the planner falls back to safe behaviour and
   alerts (findings section 11, reliability table).
5. **First calculation after a restart:** allow a charge to start, never release a hold
   or stop a charge (HANDOFF, step 5).
6. **Dashboard:** the voltage curve of the latest run-down, energy per gauge band, the
   capacity trend, and the planner's prediction against what happened.

## Later

7. **Top-off charging for the third-party packs** (optional hardware; see below). An
   occasional full charge to their reset voltage would resynchronise their counters and
   top-balance their cells. Only worth doing if cell imbalance appears or if the
   counters are wanted for display; the planner does not need them.
8. **Outage mode.** A switch that tells the integration the grid is down: a higher floor
   (keep the small battery from shutting down), generator start and stop reminders by
   phone, and load-shedding hints. Depends on the private outage analysis and on knowing
   what the inverter does below 3 % with no AC input.
9. **Learn the handover rule.** Whether the 3 % handover is a firmware floor or a per-mode
   reserve (findings, low-end test). A run with the reserve at 6 % would tell.

## Top-off charging options for the third-party packs (notes for item 7)

Why they never reach 100 %: the inverter stops charging when its own battery flips to
100 % at about 55.4 V (about 3.46 V per cell). The third-party packs reset their counters
to 100 % only at a higher voltage with a small tail current (about 3.55-3.65 V per cell,
roughly 56.8-58.4 V; check the Vatrer manual). That stop point is gentle on lithium iron
phosphate cells and probably deliberate on Bluetti's part. Physically the packs are
nearly full anyway; only the counters and cell balancing are affected.

Options, cheapest first:
- **Do nothing in hardware** (recommended first): items 1 and 2 above make the counters
  irrelevant. Watch each pack's highest-minus-lowest cell voltage at the top of charge;
  act only if it grows.
- **Set the counters from the pack app**, if Vatrer's app allows a SOC calibration.
- **A dedicated LiFePO4 charger for the third-party packs**, switched by Home Assistant
  through a smart relay, run monthly after a full night charge. Caution: all five
  batteries share one DC bus with the inverter, and pushing the bus to 57-58 V may be
  outside the small battery's or the inverter's limits. A safe version isolates the
  third-party packs first (a DC breaker or switch), charges them on their own, then lets
  them settle before reconnecting, because closing packs at different voltages onto one
  bus drives a large current between them. This is rewiring, which is off the table for
  now (owner, 2026-11-15); revisit only if needed.
- **Charge through the inverter's solar input**: does not help, because the inverter
  stops on the same 100 % flip.
