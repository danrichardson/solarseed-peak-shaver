"""Tariff-window planner on top of the learned model. Pure Python: no Home Assistant imports.

One function, `decide`, answers "what should the inverter be doing right now?" with one
of three modes:

  discharge  solar first, then battery, then grid (the normal daytime mode)
  hold       grid carries the house, the battery is kept as it is
  charge     grid carries the house and charges the battery

The rules, in order:

  1. Peak window on a TOU day: discharge. Never charge.
  2. Mid-peak on a TOU day: discharge. Charge only if the battery will not cover the
     peak window with the margin to spare, and then as late as will still finish by
     peak start. Running out in peak is never cheap: the inverter hands the house to
     the grid at the floor and then grid-charges its battery back to a recovery level
     at peak price, so any predicted shortfall starts a top-up (no tolerance), and a
     running top-up goes a little past the need.
  3. The night before a TOU day (after peak end, or before mid-peak start on the day):
       - "full" months: charge until the inverter ends the charge, then hold.
       - other months: work out the energy the day needs, turn it into a gauge target
         with the learned discharge curve, start the charge as late as will still
         finish by mid-peak start, and hold before and after it.
     If there is already more than enough on board, keep discharging down to the target.
  4. A weekly top-up to full after the last TOU day of the week, in "full" months.
  5. Otherwise: discharge.

A forecast only changes numbers inside these rules. It never starts a charge by itself.
When the model is not trained yet, or the gauge cannot be read (missing, or frozen:
see the staleness check in learned_runtime), the night rule falls back to a full
charge: more charge than needed costs cents, too little costs dollars. Without a gauge
in mid-peak the inverter stays on battery, except that a top-up already running is
finished (the inverter stops it when full; the peak rule stops it at peak start).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .learning import Learner, LoadProfile

MODE_DISCHARGE = "discharge"
MODE_HOLD = "hold"
MODE_CHARGE = "charge"

#: gauge points of discharge data before the learned curve is trusted for sizing
MIN_CURVE_POINTS = 150.0
#: TOU days of load history before the learned profile is trusted for sizing
MIN_PROFILE_DAYS = 5
#: a mid-peak top-up keeps going until the peak window is covered with this much extra (kWh)
TOPUP_OVERSHOOT_KWH = 0.2


@dataclass
class PlanInputs:
    now: datetime                       # local time
    gauge: float | None                 # percent, None if it cannot be read
    is_tou_today: bool
    is_tou_tomorrow: bool
    midpeak_start: int = 7
    peak_start: int = 17
    peak_end: int = 21
    floor: float = 3.0                  # gauge at which the inverter hands over to grid
    full_months: tuple[int, ...] = (11, 12, 1)
    load_quantile: float = 0.8
    solar_confidence: float = 0.7
    margin_kwh: float = 0.5             # reserve to keep above the floor at peak end
    recovery_pct: float = 10.0          # gauge the inverter grid-charges back to after a handover
    solar_today: dict[int, float] = field(default_factory=dict)       # kWh by hour
    solar_tomorrow: dict[int, float] = field(default_factory=dict)
    bank_full: bool = False             # the inverter has ended the charge
    topup_pending: bool = False         # weekly top-up owed and not yet finished
    current_mode: str | None = None     # what was last commanded, for hysteresis
    current_phase: str | None = None    # the phase that command was issued in
    fallback_charge_kw: float = 1.5     # net charge rate assumed before one is learned
    data_stale: bool = False            # the gauge is None because the readings froze
    # Tomorrow's hours, for the night rule after today's peak end (a season or the weekend
    # can give tomorrow other hours). None: the same as today's.
    next_midpeak_start: int | None = None
    next_peak_end: int | None = None


@dataclass
class Decision:
    mode: str
    phase: str
    reason: str
    target_gauge: float | None = None
    need_kwh: float | None = None
    energy_remaining_kwh: float | None = None
    lead_hours: float | None = None
    model_ready: bool = False
    handover_kwh: float | None = None   # what one handover costs on top of the shortfall
    shortfall_kwh: float | None = None  # predicted short of the peak window plus margin

    def as_dict(self) -> dict[str, Any]:
        r = lambda v, n=2: None if v is None else round(v, n)
        return {
            "mode": self.mode,
            "phase": self.phase,
            "reason": self.reason,
            "target_gauge": r(self.target_gauge, 1),
            "need_kwh": r(self.need_kwh),
            "energy_remaining_kwh": r(self.energy_remaining_kwh),
            "lead_hours": r(self.lead_hours),
            "model_ready": self.model_ready,
            "handover_kwh": r(self.handover_kwh),
            "shortfall_kwh": r(self.shortfall_kwh),
        }


def model_ready(learner: Learner, profile: LoadProfile) -> bool:
    """True once there is enough data to size a charge from the learned model."""
    return sum(learner.discharge.p) >= MIN_CURVE_POINTS and profile.n_days(True) >= MIN_PROFILE_DAYS


def window_need(
    profile: LoadProfile,
    solar: dict[int, float],
    t0: float,
    t1: float,
    quantile: float,
    solar_confidence: float,
    window: tuple[int, int],
) -> float:
    """Battery energy (kWh) needed to carry the house from hour t0 to hour t1.

    Load is the learned TOU-day profile scaled up to the given quantile of whole-window
    energy; forecast solar is discounted by `solar_confidence`; an hour with more solar
    than load counts as zero, not as a credit.
    """
    if t1 <= t0:
        return 0.0
    mean = profile.window_mean(True, window[0], window[1])
    scale = profile.window_quantile(True, window[0], window[1], quantile) / mean if mean > 0 else 1.0
    need = 0.0
    hour = int(t0)
    while hour < t1:
        frac = min(hour + 1, t1) - max(hour, t0)
        if frac > 0:
            load = profile.mean(True, hour % 24) * scale
            pv = float(solar.get(hour % 24, 0.0)) * solar_confidence
            need += max(load - pv, 0.0) * frac
        hour += 1
    return need


def handover_kwh(learner: Learner, floor: float, recovery_pct: float) -> float:
    """kWh the inverter buys to recharge its battery from the floor to the recovery level.

    That is the price of touching the floor, on top of the load the grid then carries:
    the inverter stays on grid until its battery is back at the recovery level (and
    with this inverter, until the mode changes). Learned from the grid-charge curve.
    """
    if recovery_pct <= floor:
        return 0.0
    return learner.grid_charge.energy_between(floor, recovery_pct)


def _hours_until(now_h: float, hour: int) -> float:
    return (hour - now_h) % 24 or 24.0


def decide(inp: PlanInputs, learner: Learner, profile: LoadProfile) -> Decision:
    """What the inverter should be doing at inp.now."""
    now = inp.now
    h = now.hour + now.minute / 60.0
    ready = model_ready(learner, profile)
    window = (inp.midpeak_start, inp.peak_end)
    gauge = inp.gauge
    remaining = None
    if gauge is not None:
        remaining = learner.discharge.energy_between(inp.floor, gauge) if gauge > inp.floor else 0.0

    handover = handover_kwh(learner, inp.floor, inp.recovery_pct)
    no_gauge = "Battery data frozen" if inp.data_stale else "Battery gauge unavailable"

    def make(mode: str, phase: str, reason: str, **kw: Any) -> Decision:
        return Decision(mode=mode, phase=phase, reason=reason, energy_remaining_kwh=remaining,
                        model_ready=ready, handover_kwh=handover, **kw)

    in_rates = inp.is_tou_today and inp.midpeak_start <= h < inp.peak_end
    pre_tou_night = (h >= inp.peak_end and inp.is_tou_tomorrow) or (h < inp.midpeak_start and inp.is_tou_today)

    # 1. Peak: never charge.
    if in_rates and h >= inp.peak_start:
        return make(MODE_DISCHARGE, "peak", "Peak window: running on battery, never charging.")

    # 2. Mid-peak: charge only to cover the peak window, finished by peak start.
    if in_rates:
        charging = inp.current_mode == MODE_CHARGE and inp.current_phase == "mid-peak"
        if gauge is None:
            if charging:
                return make(MODE_CHARGE, "mid-peak",
                            "%s during a top-up: finishing it; it ends when the inverter is full or at %02d:00."
                            % (no_gauge, inp.peak_start))
            return make(MODE_DISCHARGE, "mid-peak", "%s: leaving the inverter on battery." % no_gauge)
        to_peak = window_need(profile, inp.solar_today, h, inp.peak_start, inp.load_quantile,
                              inp.solar_confidence, window)
        peak = window_need(profile, inp.solar_today, inp.peak_start, inp.peak_end, inp.load_quantile,
                           inp.solar_confidence, window)
        short = peak + inp.margin_kwh - (remaining - to_peak)
        # Handover as a cost: not topping up risks the shortfall plus `handover` kWh, all at
        # peak price; a top-up costs the shortfall at mid-peak price. Peak price is never
        # lower, so any shortfall is worth covering, and a running top-up overshoots a bit.
        if short > (-TOPUP_OVERSHOOT_KWH if charging else 0.0):
            i = min(learner.grid_charge.n - 1, int(gauge // learner.grid_charge.bin_pts))
            hpp = learner.grid_charge.hours_per_pt(i)
            rate = learner.grid_charge.per_pt(i) / hpp if hpp > 0 else inp.fallback_charge_kw
            rate = min(max(rate, 0.3), 10.0)
            lead = short / rate + 0.25
            left = inp.peak_start - h
            cost = ("running out would cost about %.1f kWh at peak price (%.1f short plus %.1f to "
                    "recharge to %.0f%%)" % (max(short, 0.0) + handover, max(short, 0.0), handover,
                                             inp.recovery_pct))
            if charging or left <= lead:
                target = learner.discharge.move(gauge, max(short, 0.0) + TOPUP_OVERSHOOT_KWH, +1)
                return make(MODE_CHARGE, "mid-peak",
                            "Peak window would be short by %.1f kWh: charging now to finish by %02d:00; %s."
                            % (max(short, 0.0), inp.peak_start, cost),
                            target_gauge=target, need_kwh=peak + to_peak, lead_hours=lead,
                            shortfall_kwh=short)
            return make(MODE_DISCHARGE, "mid-peak",
                        "Peak window looks short by %.1f kWh; a top-up will start about %.1f h before %02d:00 "
                        "if that is still true; %s." % (short, lead, inp.peak_start, cost),
                        need_kwh=peak + to_peak, lead_hours=lead, shortfall_kwh=short)
        return make(MODE_DISCHARGE, "mid-peak",
                    "On battery. Expected to reach %02d:00 with %.1f kWh against %.1f kWh needed for peak."
                    % (inp.peak_start, max(remaining - to_peak, 0.0), peak),
                    need_kwh=peak + to_peak, shortfall_kwh=short)

    # 3. The night before a TOU day. After today's peak end the day planned for is tomorrow,
    #    so its hours are tomorrow's (a season boundary or the weekend can change them).
    if pre_tou_night:
        for_tomorrow = h >= inp.peak_end
        tou_day_month = _next_day_month(now) if for_tomorrow else now.month
        solar = inp.solar_tomorrow if for_tomorrow else inp.solar_today
        mid_start = inp.midpeak_start
        end = inp.peak_end
        if for_tomorrow:
            mid_start = inp.midpeak_start if inp.next_midpeak_start is None else inp.next_midpeak_start
            end = inp.peak_end if inp.next_peak_end is None else inp.next_peak_end
        hours_left = _hours_until(h, mid_start)
        full_month = tou_day_month in inp.full_months
        if full_month or not ready or gauge is None:
            why = ("Full-charge month" if full_month else
                   "Model not trained yet" if not ready else no_gauge)
            if inp.bank_full:
                return make(MODE_HOLD, "night", "%s: battery is full, holding until %02d:00."
                            % (why, mid_start), target_gauge=100.0)
            return make(MODE_CHARGE, "night", "%s: charging until the inverter stops, then holding until %02d:00."
                        % (why, mid_start), target_gauge=100.0)
        need = window_need(profile, solar, mid_start, end, inp.load_quantile,
                           inp.solar_confidence, (mid_start, end)) + inp.margin_kwh
        target = learner.discharge.gauge_for_energy(inp.floor, need)
        if gauge > target + 1.0 and not inp.current_mode == MODE_HOLD:
            return make(MODE_DISCHARGE, "night",
                        "More on board than tomorrow needs (%.0f%% against a target of %.0f%%): still on battery."
                        % (gauge, target), target_gauge=target, need_kwh=need)
        if gauge >= target - 0.5 or inp.bank_full:
            return make(MODE_HOLD, "night", "At target (%.0f%% for %.1f kWh): holding until %02d:00."
                        % (target, need, mid_start), target_gauge=target, need_kwh=need)
        lead = learner.grid_charge.hours_between(gauge, target) * 1.15 + 0.25
        if inp.current_mode == MODE_CHARGE or hours_left <= lead:
            return make(MODE_CHARGE, "night", "Charging to %.0f%% (%.1f kWh for tomorrow), timed to end at %02d:00."
                        % (target, need, mid_start), target_gauge=target, need_kwh=need, lead_hours=lead)
        return make(MODE_HOLD, "night", "Holding. Charge to %.0f%% starts about %.1f h before %02d:00."
                    % (target, lead, mid_start), target_gauge=target, need_kwh=need, lead_hours=lead)

    # 4. Weekly top-up after the last TOU day of the week.
    if inp.topup_pending and now.month in inp.full_months:
        if not inp.bank_full:
            return make(MODE_CHARGE, "top-up", "Weekly top-up: charging until the inverter stops.",
                        target_gauge=100.0)
        return make(MODE_DISCHARGE, "top-up", "Weekly top-up finished.")

    # 5. Everything else.
    return make(MODE_DISCHARGE, "off-peak", "Off-peak: solar first, then battery.")


def _next_day_month(now: datetime) -> int:
    from datetime import timedelta

    return (now + timedelta(days=1)).month


def predict_gauge(
    learner: Learner,
    profile: LoadProfile,
    solar: dict[int, float],
    gauge: float,
    t0: float,
    t1: float,
    floor: float,
    solar_confidence: float = 1.0,
) -> float:
    """Expected gauge at hour t1 starting from `gauge` at hour t0, on battery (mean load)."""
    g = gauge
    hour = int(t0)
    while hour < t1:
        frac = min(hour + 1, t1) - max(hour, t0)
        if frac > 0:
            net = float(solar.get(hour % 24, 0.0)) * solar_confidence - profile.mean(True, hour % 24)
            if net < 0:
                g = learner.discharge.move(g, -net * frac, -1, lo=floor)
            else:
                g = learner.solar_charge.move(g, net * frac, +1)
        hour += 1
    return g
