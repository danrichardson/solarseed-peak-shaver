"""Learned battery and load model. Pure Python: no Home Assistant imports.

The planner used to assume that one percent of battery is worth capacity / 100 kWh and
that the house draws one fixed base load. Both were wrong on the system this was built
for, and both drift. This module measures them instead, from three power sensors and
the battery gauge:

  discharge curve     AC kWh delivered per gauge point, by gauge band
  grid charge curve   net AC kWh absorbed per gauge point, and hours per point
  solar charge curve  PV kWh absorbed per gauge point
  load profile        kWh per hour of day, for TOU days and for other days

"Gauge" is whatever percent the inverter reports. Nothing here knows about a brand of
inverter, a battery chemistry or a tariff. Units are the sensors' own; they only need
to be self-consistent.

A curve is reliable for a discharge that starts from a full charge. Shallow cycling at
the bottom of the gauge can be worth different amounts going in and coming out when
part of the bank is invisible to the inverter (see docs/battery-bank-methodology.md).
"""
from __future__ import annotations

import math
from typing import Any

REGIME_DISCHARGE = "discharge"
REGIME_GRID_CHARGE = "grid_charge"
REGIME_SOLAR_CHARGE = "solar_charge"
REGIME_NONE = "none"


class Curve:
    """Energy (and optionally time) per gauge point, in bins, with exponential forgetting.

    Each bin keeps decayed sums of energy, points and hours. A prior of `prior_per_pt`
    with the weight of `prior_pts` points keeps empty bins sane and fades as data
    arrives.
    """

    def __init__(
        self,
        bin_pts: float = 5.0,
        prior_per_pt: float = 0.235,
        prior_pts: float = 3.0,
        half_life_days: float = 30.0,
        prior_hours_per_pt: float | None = None,
    ) -> None:
        self.bin_pts = float(bin_pts)
        self.n = int(math.ceil(100.0 / self.bin_pts))
        self.prior_per_pt = prior_per_pt
        self.prior_pts = prior_pts
        self.prior_hours_per_pt = prior_hours_per_pt
        self.half_life_days = half_life_days
        self.e = [0.0] * self.n
        self.p = [0.0] * self.n
        self.h = [0.0] * self.n
        self.pt = [0.0] * self.n     # points seen in observations that carried a duration

    # -- learning ---------------------------------------------------------

    def age(self, days: float = 1.0) -> None:
        """Forget: scale every sum by 0.5 ** (days / half_life_days)."""
        f = 0.5 ** (days / self.half_life_days)
        for i in range(self.n):
            self.e[i] *= f
            self.p[i] *= f
            self.h[i] *= f
            self.pt[i] *= f

    def _overlaps(self, a: float, b: float):
        """Yield (bin index, gauge points of [a, b] inside that bin)."""
        lo, hi = max(0.0, min(a, b)), min(100.0, max(a, b))
        i = int(lo // self.bin_pts)
        while i < self.n and i * self.bin_pts < hi:
            x0, x1 = max(lo, i * self.bin_pts), min(hi, (i + 1) * self.bin_pts)
            if x1 > x0:
                yield i, x1 - x0
            i += 1

    def observe(self, g_from: float, g_to: float, energy_kwh: float, hours: float = 0.0) -> None:
        """Record that the gauge moved g_from -> g_to while `energy_kwh` flowed."""
        span = abs(g_from - g_to)
        if span < 0.5 or energy_kwh <= 0:
            return
        for i, pts in self._overlaps(g_from, g_to):
            share = pts / span
            self.e[i] += energy_kwh * share
            self.p[i] += pts
            if hours > 0:
                self.h[i] += hours * share
                self.pt[i] += pts

    # -- reading ----------------------------------------------------------

    def weight(self, i: int) -> float:
        """Decayed gauge points seen in bin i (0 means only the prior speaks)."""
        return self.p[i]

    def per_pt(self, i: int) -> float:
        return (self.e[i] + self.prior_per_pt * self.prior_pts) / (self.p[i] + self.prior_pts)

    def hours_per_pt(self, i: int) -> float:
        prior = self.prior_hours_per_pt or 0.0
        return (self.h[i] + prior * self.prior_pts) / (self.pt[i] + self.prior_pts)

    def energy_between(self, g_lo: float, g_hi: float) -> float:
        """kWh between two gauge readings."""
        return sum(self.per_pt(i) * pts for i, pts in self._overlaps(g_lo, g_hi))

    def hours_between(self, g_lo: float, g_hi: float) -> float:
        return sum(self.hours_per_pt(i) * pts for i, pts in self._overlaps(g_lo, g_hi))

    def gauge_for_energy(self, floor: float, energy_kwh: float) -> float:
        """Lowest gauge reading with at least `energy_kwh` between it and `floor`."""
        return self.move(floor, energy_kwh, +1)

    def move(self, g: float, energy_kwh: float, direction: int, lo: float = 0.0, hi: float = 100.0) -> float:
        """Gauge after `energy_kwh` flows. direction -1 = discharge, +1 = charge."""
        e = energy_kwh
        while e > 1e-9:
            if direction < 0:
                if g <= lo + 1e-9:
                    return lo
                i = min(self.n - 1, int(math.ceil(g / self.bin_pts)) - 1)
                edge = max(lo, i * self.bin_pts)
                room = (g - edge) * self.per_pt(i)
                if e >= room:
                    e -= room
                    g = edge
                else:
                    return g - e / self.per_pt(i)
            else:
                if g >= hi - 1e-9:
                    return hi
                i = min(self.n - 1, int(g // self.bin_pts))
                edge = min(hi, (i + 1) * self.bin_pts)
                room = (edge - g) * self.per_pt(i)
                if e >= room:
                    e -= room
                    g = edge
                else:
                    return g + e / self.per_pt(i)
        return g

    # -- persistence ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "bin_pts": self.bin_pts,
            "prior_per_pt": self.prior_per_pt,
            "prior_pts": self.prior_pts,
            "prior_hours_per_pt": self.prior_hours_per_pt,
            "half_life_days": self.half_life_days,
            "e": [round(x, 5) for x in self.e],
            "p": [round(x, 4) for x in self.p],
            "h": [round(x, 5) for x in self.h],
            "pt": [round(x, 4) for x in self.pt],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None, **defaults: Any) -> "Curve":
        """Rebuild a curve. Anything missing or malformed falls back to an empty curve."""
        d = d or {}
        c = cls(
            bin_pts=d.get("bin_pts", defaults.get("bin_pts", 5.0)),
            prior_per_pt=d.get("prior_per_pt", defaults.get("prior_per_pt", 0.235)),
            prior_pts=d.get("prior_pts", defaults.get("prior_pts", 3.0)),
            half_life_days=d.get("half_life_days", defaults.get("half_life_days", 30.0)),
            prior_hours_per_pt=d.get("prior_hours_per_pt", defaults.get("prior_hours_per_pt")),
        )
        try:
            loaded = {}
            for name in ("e", "p", "h", "pt"):
                vals = d.get(name)
                if isinstance(vals, list) and len(vals) == c.n:
                    loaded[name] = [float(x) for x in vals]
            if "e" in loaded and "p" in loaded:
                c.e, c.p = loaded["e"], loaded["p"]
                if "h" in loaded and "pt" in loaded:
                    c.h, c.pt = loaded["h"], loaded["pt"]
        except (TypeError, ValueError):
            return cls(bin_pts=c.bin_pts, prior_per_pt=c.prior_per_pt, prior_pts=c.prior_pts,
                       half_life_days=c.half_life_days, prior_hours_per_pt=c.prior_hours_per_pt)
        return c


class LoadProfile:
    """Load by hour of day for two day types, from the trailing `days` days of each."""

    def __init__(self, days: int = 14, default_kw: float = 0.6) -> None:
        self.days = days
        self.default_kw = default_kw
        self.hist: dict[bool, list[dict[int, float]]] = {True: [], False: []}

    def observe_day(self, is_tou: bool, by_hour: dict[int, float]) -> None:
        """Add one finished day ({hour: kWh}). Days with fewer than 20 hours are skipped."""
        if len(by_hour) >= 20:
            self.hist[is_tou] = (self.hist[is_tou] + [dict(by_hour)])[-self.days :]

    def n_days(self, is_tou: bool) -> int:
        return len(self.hist[is_tou])

    def mean(self, is_tou: bool, hour: int) -> float:
        v = [d[hour] for d in self.hist[is_tou] if hour in d]
        return sum(v) / len(v) if v else self.default_kw

    def window_samples(self, is_tou: bool, h0: int, h1: int) -> list[float]:
        """Total kWh over [h0, h1) for each remembered day that has every hour."""
        out = []
        for d in self.hist[is_tou]:
            if all(h in d for h in range(h0, h1)):
                out.append(sum(d[h] for h in range(h0, h1)))
        return sorted(out)

    def window_mean(self, is_tou: bool, h0: int, h1: int) -> float:
        s = self.window_samples(is_tou, h0, h1)
        return sum(s) / len(s) if s else self.default_kw * (h1 - h0)

    def window_quantile(self, is_tou: bool, h0: int, h1: int, q: float) -> float:
        """Quantile of whole-window energy.

        Taken over whole days, not hour by hour, so a day that runs heavy all day counts
        as heavy. Falls back to the mean with fewer than 5 days.
        """
        s = self.window_samples(is_tou, h0, h1)
        if len(s) < 5:
            return self.window_mean(is_tou, h0, h1)
        x = min(max(q, 0.0), 1.0) * (len(s) - 1)
        i = int(x)
        return s[i] + (s[min(i + 1, len(s) - 1)] - s[i]) * (x - i)

    def to_dict(self) -> dict[str, Any]:
        return {
            "days": self.days,
            "default_kw": self.default_kw,
            "tou": [{str(h): round(v, 4) for h, v in d.items()} for d in self.hist[True]],
            "other": [{str(h): round(v, 4) for h, v in d.items()} for d in self.hist[False]],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None, **defaults: Any) -> "LoadProfile":
        d = d or {}
        lp = cls(days=d.get("days", defaults.get("days", 14)),
                 default_kw=d.get("default_kw", defaults.get("default_kw", 0.6)))
        for key, is_tou in (("tou", True), ("other", False)):
            for day in d.get(key) or []:
                try:
                    lp.hist[is_tou].append({int(h): float(v) for h, v in day.items()})
                except (TypeError, ValueError, AttributeError):
                    continue
            lp.hist[is_tou] = lp.hist[is_tou][-lp.days :]
        return lp


def classify(grid_kw: float, load_kw: float, pv_kw: float) -> str:
    """Which curve, if any, a sample belongs to.

    grid_kw is AC power into the inverter from the grid, load_kw is AC power out to the
    house, pv_kw is solar power in. Net into the battery is grid + pv - load.
    """
    net = grid_kw + pv_kw - load_kw
    if grid_kw < 0.03:
        if net < -0.05:
            return REGIME_DISCHARGE
        if net > 0.05:
            return REGIME_SOLAR_CHARGE
        return REGIME_NONE
    if grid_kw > 0.2 and net > 0.1 and pv_kw < 0.05:
        return REGIME_GRID_CHARGE
    return REGIME_NONE


class Learner:
    """Turns a stream of samples into the three curves.

    The gauge is usually an integer that ticks once every several minutes. Energy is
    accumulated between ticks and credited to the gauge points actually crossed. A
    stretch is thrown away when the regime changes inside it (for example a charge that
    starts mid-point), and the first, partial point of every stretch is skipped.
    """

    #: a sample longer than this is not trusted (restart, sensor dropout)
    MAX_SAMPLE_HOURS = 0.25
    #: grid input above this counts as a full-rate charge for the timing curve
    FULL_RATE_KW = 1.2
    #: a discharge stretch that takes longer than this, or delivers more than this, without
    #: the gauge moving is not a measurement of one point: the small battery is parked
    #: (seen at 1 % for 15 hours) while the others carry the load. Thrown away.
    MAX_DISCHARGE_POINT_HOURS = 2.0
    MAX_DISCHARGE_POINT_KWH = 1.0

    def __init__(self, prior_per_pt: float = 0.235, half_life_days: float = 30.0, bin_pts: float = 5.0) -> None:
        kw = dict(bin_pts=bin_pts, prior_per_pt=prior_per_pt, half_life_days=half_life_days)
        self.discharge = Curve(**kw)
        self.grid_charge = Curve(prior_hours_per_pt=prior_per_pt / 1.9, **kw)
        self.solar_charge = Curve(**kw)
        self._reset_segment(REGIME_NONE, None)

    def _reset_segment(self, regime: str, gauge: float | None) -> None:
        self._regime = regime
        self._g0 = gauge
        self._energy = 0.0
        self._hours = 0.0
        self._full_rate = True
        self._aligned = False

    def age(self, days: float = 1.0) -> None:
        for c in (self.discharge, self.grid_charge, self.solar_charge):
            c.age(days)

    def sample(self, gauge: float, grid_kw: float, load_kw: float, pv_kw: float, hours: float) -> None:
        """Feed one sample covering the last `hours` hours."""
        if hours <= 0 or hours > self.MAX_SAMPLE_HOURS:
            self._reset_segment(REGIME_NONE, None)
            return
        regime = classify(grid_kw, load_kw, pv_kw)
        if regime != self._regime or self._g0 is None:
            self._reset_segment(regime, gauge)
            return
        if regime == REGIME_NONE:
            return
        net = grid_kw + pv_kw - load_kw
        self._energy += abs(net) * hours
        self._hours += hours
        if grid_kw < self.FULL_RATE_KW:
            self._full_rate = False
        moved = gauge - self._g0
        want = -1 if regime == REGIME_DISCHARGE else 1
        if regime == REGIME_DISCHARGE and (
            self._hours > self.MAX_DISCHARGE_POINT_HOURS or self._energy > self.MAX_DISCHARGE_POINT_KWH
        ):
            # parked gauge: drop the stretch, and start again unaligned (the next
            # point is partial)
            self._reset_segment(regime, gauge)
            return
        if moved * want >= 1.0:
            if self._aligned:
                curve = {REGIME_DISCHARGE: self.discharge, REGIME_GRID_CHARGE: self.grid_charge,
                         REGIME_SOLAR_CHARGE: self.solar_charge}[regime]
                timed = regime == REGIME_GRID_CHARGE and self._full_rate
                curve.observe(self._g0, gauge, self._energy, hours=self._hours if timed else 0.0)
            self._g0, self._energy, self._hours, self._full_rate, self._aligned = gauge, 0.0, 0.0, True, True
        elif moved * want <= -1.0:
            self._reset_segment(regime, gauge)

    def to_dict(self) -> dict[str, Any]:
        return {
            "discharge": self.discharge.to_dict(),
            "grid_charge": self.grid_charge.to_dict(),
            "solar_charge": self.solar_charge.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None, **kw: Any) -> "Learner":
        d = d or {}
        ln = cls(**kw)
        base = dict(bin_pts=ln.discharge.bin_pts, prior_per_pt=ln.discharge.prior_per_pt,
                    half_life_days=ln.discharge.half_life_days)
        ln.discharge = Curve.from_dict(d.get("discharge"), **base)
        ln.grid_charge = Curve.from_dict(d.get("grid_charge"), prior_hours_per_pt=ln.grid_charge.prior_hours_per_pt, **base)
        ln.solar_charge = Curve.from_dict(d.get("solar_charge"), **base)
        return ln


def build_from_samples(samples, learner: Learner | None = None) -> Learner:
    """Train a Learner from historical samples (used by the recorder backfill).

    `samples` is an iterable of (local datetime, gauge, grid_kw, load_kw, pv_kw, hours),
    oldest first. The curves age by one day at each change of date, as they would live.
    """
    ln = learner or Learner()
    last_date = None
    last_when = None
    for when, gauge, grid_kw, load_kw, pv_kw, hours in samples:
        gap = last_when is not None and (when - last_when).total_seconds() > 1.5 * hours * 3600.0
        last_when = when
        if gap or None in (gauge, grid_kw, load_kw):
            ln.sample(0.0, 0.0, 0.0, 0.0, 0.0)          # gap: drop the open stretch
            if None in (gauge, grid_kw, load_kw):
                continue
        d = when.date()
        if last_date is not None and d != last_date:
            ln.age(float((d - last_date).days))
        last_date = d
        ln.sample(float(gauge), float(grid_kw), float(load_kw), float(pv_kw or 0.0), float(hours))
    return ln


def profile_from_hourly(rows, is_tou, profile: LoadProfile | None = None) -> LoadProfile:
    """Build a LoadProfile from (local datetime at the start of the hour, load_kw) rows."""
    lp = profile or LoadProfile()
    days: dict[Any, dict[int, float]] = {}
    for when, load_kw in rows:
        if load_kw is None:
            continue
        days.setdefault(when.date(), {})[when.hour] = max(float(load_kw), 0.0)
    for d in sorted(days):
        lp.observe_day(bool(is_tou(d)), days[d])
    return lp
