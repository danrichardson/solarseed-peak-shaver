"""The tariff as data (0.9.1, ROADMAP item 8).

Pure Python, no Home Assistant imports. A tariff here is:

- three named periods with a price per kWh: off-peak (cheap), mid-peak (middle) and peak
  (dear). These are the planner's three windows; every tariff is mapped onto them;
- the hours of the mid-peak and peak windows on a TOU day. Mid-peak runs straight into
  peak; off-peak is every other hour. Mid-peak start equal to peak start means there is
  no mid-peak window (a two-price plan);
- day types: on a weekday the windows apply; on a weekend they apply only when the plan
  is not weekdays-only; a holiday is off-peak all day;
- optional seasons: by month, other hours and/or other prices. A season never changes the
  planner's rules, only the hours and the prices it works with;
- the holiday calendar (`holidays.py`).

A tariff that does not fit that shape (two peak windows in a day, a gap between mid-peak
and peak, mid-peak after peak, a window across midnight, prices that do not rise from
off-peak to peak) is refused with a plain message rather than half-supported.

The three legacy options `midpeak_start_hour`, `peak_start_hour` and `peak_end_hour` are
the base windows; with no other tariff option stored, the tariff is PGE Time of Day as
0.9.0 assumed it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from typing import Any

from .const import DEFAULT_MIDPEAK_PRICE, DEFAULT_PEAK_PRICE
from .holidays import PGE, HolidayCalendar, day_type, is_tou_day

PERIOD_OFFPEAK = "off-peak"
PERIOD_MIDPEAK = "mid-peak"
PERIOD_PEAK = "peak"
PERIODS = (PERIOD_OFFPEAK, PERIOD_MIDPEAK, PERIOD_PEAK)     # cheap, middle, dear

# PGE Time of Day, USD per kWh, as 0.8.1 to 0.9.0 had them in health.py (one source: the
# option defaults). Off-peak was never priced (the daily cost counts mid-peak and peak only),
# so the preset leaves it out.
PGE_MIDPEAK_PRICE = DEFAULT_MIDPEAK_PRICE
PGE_PEAK_PRICE = DEFAULT_PEAK_PRICE

TARIFF_CUSTOM = "Custom"


@dataclass(frozen=True)
class Windows:
    """The mid-peak and peak hours of a TOU day; off-peak is the rest."""
    midpeak_start: int
    peak_start: int
    peak_end: int

    def period(self, hour: int) -> str:
        if hour < self.midpeak_start or hour >= self.peak_end:
            return PERIOD_OFFPEAK
        if hour < self.peak_start:
            return PERIOD_MIDPEAK
        return PERIOD_PEAK

    @property
    def has_midpeak(self) -> bool:
        return self.midpeak_start < self.peak_start

    def text(self) -> str:
        """`07-17 mid-peak, 17-21 peak`."""
        parts = []
        if self.has_midpeak:
            parts.append("%02d-%02d mid-peak" % (self.midpeak_start, self.peak_start))
        parts.append("%02d-%02d peak" % (self.peak_start, self.peak_end))
        return ", ".join(parts)

    def problem(self) -> str | None:
        """Why these hours do not fit the planner's day, or None."""
        if not (0 <= self.midpeak_start <= self.peak_start < self.peak_end <= 24):
            return ("the hours must be in order inside one day: mid-peak start, then peak start, "
                    "then peak end (0 to 24); mid-peak start equal to peak start means no mid-peak")
        return None


@dataclass(frozen=True)
class Season:
    name: str
    months: tuple[int, ...]
    windows: Windows | None = None                      # None: the base hours
    prices: tuple[tuple[str, float], ...] = ()          # only the prices it changes


@dataclass(frozen=True)
class Tariff:
    name: str
    windows: Windows
    prices: tuple[tuple[str, float | None], ...]        # one per period; None = not given
    weekdays_only: bool = True
    seasons: tuple[Season, ...] = ()
    holidays: HolidayCalendar = PGE

    def season_on(self, d: date) -> Season | None:
        for s in self.seasons:
            if d.month in s.months:
                return s
        return None

    def windows_on(self, d: date) -> Windows:
        """The hours on `d`'s TOU days (its season's, else the base)."""
        s = self.season_on(d)
        return s.windows if s is not None and s.windows is not None else self.windows

    def prices_on(self, d: date) -> dict[str, float | None]:
        out = dict(self.prices)
        s = self.season_on(d)
        if s is not None:
            out.update(dict(s.prices))
        return {p: out.get(p) for p in PERIODS}

    def day_type(self, d: date) -> str:
        return day_type(d, self.holidays)

    def is_tou_day(self, d: date) -> bool:
        return is_tou_day(d, self.weekdays_only, self.holidays)

    def period_at(self, when: datetime) -> str:
        """The price period at `when`: off-peak all day on a day that is not a TOU day."""
        if not self.is_tou_day(when.date()):
            return PERIOD_OFFPEAK
        return self.windows_on(when.date()).period(when.hour)

    def price_at(self, when: datetime) -> float | None:
        return self.prices_on(when.date())[self.period_at(when)]

    def all_windows(self) -> tuple[Windows, ...]:
        """Every set of hours in use (the timers are set for all of them)."""
        out = [self.windows] + [s.windows for s in self.seasons if s.windows is not None]
        return tuple(sorted(set(out), key=lambda w: (w.midpeak_start, w.peak_start, w.peak_end)))

    def describe(self, d: date) -> dict[str, Any]:
        """What applies on `d`, for the plan sensor and diagnostics."""
        s = self.season_on(d)
        return {
            "tariff": self.name,
            "season": s.name if s is not None else None,
            "day_type": self.day_type(d),
            "price_windows": self.windows_on(d).text() if self.is_tou_day(d) else "off-peak all day",
            "prices": self.prices_on(d),
        }


PGE_TIME_OF_DAY = Tariff(
    name="PGE Time of Day",
    windows=Windows(7, 17, 21),
    prices=((PERIOD_OFFPEAK, None), (PERIOD_MIDPEAK, PGE_MIDPEAK_PRICE), (PERIOD_PEAK, PGE_PEAK_PRICE)),
    weekdays_only=True,
    seasons=(),
    holidays=PGE,
)

TARIFF_PRESETS: dict[str, Tariff] = {"pge_tod": PGE_TIME_OF_DAY}


# --- Checks -------------------------------------------------------------------------------


def price_problem(prices: dict[str, float | None], has_midpeak: bool = True) -> str | None:
    """Prices must rise from off-peak to mid-peak to peak (those given). The planner's rule
    that any predicted peak shortfall is worth a mid-peak top-up relies on it."""
    order = [p for p in PERIODS if p != PERIOD_MIDPEAK or has_midpeak]
    given = [(p, prices.get(p)) for p in order if prices.get(p) is not None]
    for p, v in given:
        if v < 0:
            return "the %s price cannot be negative" % p
    for (p1, v1), (p2, v2) in zip(given, given[1:]):
        if v1 > v2:
            return ("prices must rise from off-peak to mid-peak to peak (%s %.4f is above %s %.4f)"
                    % (p1, v1, p2, v2))
    return None


# --- Seasons as text ----------------------------------------------------------------------

_SEASON = re.compile(r"^(?:(?P<name>[A-Za-z][A-Za-z0-9 ]*?)\s+)?(?P<m1>\d{1,2})(?:\s*-\s*(?P<m2>\d{1,2}))?"
                     r"\s*:\s*(?P<items>.*)$")
_ITEM = re.compile(r"^(?P<period>off-peak|mid-peak|peak)"
                   r"(?:\s+(?P<h1>\d{1,2})\s*-\s*(?P<h2>\d{1,2}))?"
                   r"(?:\s+\$?(?P<price>\d+(?:\.\d+)?|\.\d+))?$", re.IGNORECASE)


def _months(m1: int, m2: int | None) -> tuple[int, ...]:
    if m2 is None:
        return (m1,)
    out, m = [m1], m1
    while m != m2:
        m = m % 12 + 1
        out.append(m)
    return tuple(out)


def parse_seasons(text: str | None, base_prices: dict[str, float | None] | None = None,
                  base_windows: Windows | None = None) -> tuple[tuple[Season, ...], list[str]]:
    """Seasons typed one per line (or separated by `;`):

        Summer 06-09: mid-peak 07-15, peak 15-20 0.52, mid-peak 0.20

    A name is optional; months are one month or a range (`11-02` wraps the year). Each item
    is a period with hours, a price, or both. Hours replace the day's windows: give peak,
    and mid-peak only if there is one; it must end where peak starts. A season with prices
    only keeps the base hours. Returns the seasons understood and a plain message for each
    problem; a season with a problem is left out, so a stored bad line keeps the base.
    """
    seasons: list[Season] = []
    errors: list[str] = []
    taken: dict[int, str] = {}
    base_prices = base_prices or {}
    for raw in re.split(r"[;\n]+", str(text or "")):
        line = raw.strip()
        if not line:
            continue
        m = _SEASON.match(line)
        if not m:
            errors.append("%s: start with the months and a colon, like 06-09: peak 15-20 0.50" % line)
            continue
        m1, m2 = int(m.group("m1")), None if m.group("m2") is None else int(m.group("m2"))
        label = m.group("m1") + ("-" + m.group("m2") if m2 is not None else "")
        name = (m.group("name") or "").strip() or label
        if not 1 <= m1 <= 12 or (m2 is not None and not 1 <= m2 <= 12):
            errors.append("%s: months are 01 to 12" % label)
            continue
        months = _months(m1, m2)
        clash = [mo for mo in months if mo in taken]
        if clash:
            errors.append("%s: month %02d is already in %s" % (name, clash[0], taken[clash[0]]))
            continue
        hours: dict[str, tuple[int, int]] = {}
        prices: dict[str, float] = {}
        bad = None
        for item in [i.strip() for i in m.group("items").split(",") if i.strip()]:
            im = _ITEM.match(item)
            if not im:
                bad = ("%s: '%s' is not understood; write a period (off-peak, mid-peak, peak) with "
                       "hours like 15-20, a price like 0.45, or both" % (name, item))
                break
            period = im.group("period").lower()
            if im.group("h1") is None and im.group("price") is None:
                bad = "%s: %s needs hours, a price or both" % (name, period)
                break
            if im.group("h1") is not None:
                if period == PERIOD_OFFPEAK:
                    bad = "%s: off-peak is every hour outside mid-peak and peak; give it a price only" % name
                    break
                if period in hours:
                    bad = ("%s: two %s windows in one day; the planner follows one mid-peak window "
                           "running straight into one peak window" % (name, period))
                    break
                h1, h2 = int(im.group("h1")), int(im.group("h2"))
                if not 0 <= h1 < h2 <= 24:
                    bad = ("%s: %s %d-%d must start before it ends, inside one day (0 to 24); "
                           "a window across midnight does not fit" % (name, period, h1, h2))
                    break
                hours[period] = (h1, h2)
            if im.group("price") is not None:
                if period in prices:
                    bad = "%s: two %s prices" % (name, period)
                    break
                prices[period] = float(im.group("price"))
        if bad is None and hours:
            peak = hours.get(PERIOD_PEAK)
            mid = hours.get(PERIOD_MIDPEAK)
            if peak is None:
                bad = "%s: hours for mid-peak need peak hours as well" % name
            elif mid is not None and mid[1] != peak[0]:
                bad = ("%s: mid-peak %d-%d must end when peak starts (%d); a gap, or mid-peak after "
                       "peak, does not fit the planner's cheap, middle, dear day" % (name, mid[0], mid[1], peak[0]))
        windows = None
        if bad is None and hours:
            peak = hours[PERIOD_PEAK]
            mid = hours.get(PERIOD_MIDPEAK)
            windows = Windows(mid[0] if mid else peak[0], peak[0], peak[1])
        if bad is None:
            effective = {**base_prices, **prices}
            w = windows or base_windows
            problem = price_problem(effective, w.has_midpeak if w is not None else True)
            if problem:
                bad = "%s: %s" % (name, problem)
        if bad is not None:
            errors.append(bad)
            continue
        for mo in months:
            taken[mo] = name
        seasons.append(Season(name, months, windows,
                              tuple((p, prices[p]) for p in PERIODS if p in prices)))
    return tuple(seasons), errors


# --- From the stored options --------------------------------------------------------------


@lru_cache(maxsize=32)
def build_tariff(midpeak_start: int, peak_start: int, peak_end: int, weekdays_only: bool,
                 offpeak_price: float | None, midpeak_price: float | None, peak_price: float | None,
                 seasons_text: str | None, holidays: HolidayCalendar) -> Tariff:
    """The tariff the stored options describe. Seasons that do not parse are left out (the
    form refuses them; this only matters for a hand-edited entry)."""
    windows = Windows(int(midpeak_start), int(peak_start), int(peak_end))
    prices = ((PERIOD_OFFPEAK, offpeak_price), (PERIOD_MIDPEAK, midpeak_price), (PERIOD_PEAK, peak_price))
    seasons, _ = parse_seasons(seasons_text, dict(prices), windows)
    t = Tariff(TARIFF_CUSTOM, windows, prices, bool(weekdays_only), seasons, holidays)
    for preset in TARIFF_PRESETS.values():
        if (t.windows, t.prices, t.weekdays_only, t.seasons, t.holidays) == (
                preset.windows, preset.prices, preset.weekdays_only, preset.seasons, preset.holidays):
            return preset
    return t


def cost_attributes(tariff: Tariff, when: datetime, handover_kwh: float | None,
                    shortfall_kwh: float | None) -> dict[str, Any]:
    """Dollars for the plan sensor, at the peak price of `when`'s date."""
    peak = tariff.prices_on(when.date())[PERIOD_PEAK]
    out = tariff.describe(when.date())
    out["price_period"] = tariff.period_at(when)
    out["price_now"] = tariff.price_at(when)
    out["handover_cost_usd"] = (None if peak is None or handover_kwh is None
                                else round(handover_kwh * peak, 2))
    out["shortfall_cost_usd"] = (None if peak is None or shortfall_kwh is None or shortfall_kwh <= 0
                                 else round(shortfall_kwh * peak, 2))
    return out
