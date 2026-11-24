"""Utility holidays and the one test for "is this a TOU day" (ROADMAP item 7).

Pure Python, no Home Assistant imports. A holiday is an off-peak day all day: no
pre-TOU night charge for it, no mid-peak or peak window on it, not graded, and its
load goes into the learner's "other days" history like a weekend.

Rules are data so a later version can let people type them (`01-01`, `11-thu-4`,
`05-mon-last`, `sat->fri, sun->mon`):

- a fixed date (month, day), moved by the preset's observed-day shift when it falls
  on a weekend;
- the nth weekday of a month (nth 1..5), or the last one (nth -1); these never fall
  on a weekend, so they are never shifted.

The shift can move a holiday into another year: 2028-01-01 is a Saturday, so it is
observed on Friday 2027-12-31.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

HOLIDAY_PRESET_NONE = "none"
HOLIDAY_PRESET_PGE = "pge"
HOLIDAY_PRESETS = (HOLIDAY_PRESET_NONE, HOLIDAY_PRESET_PGE)


@dataclass(frozen=True)
class HolidayRule:
    name: str
    month: int
    day: int | None = None          # fixed date
    weekday: int | None = None      # 0 = Monday ... 6 = Sunday
    nth: int | None = None          # 1..5, or -1 for the last one in the month

    def actual(self, year: int) -> date | None:
        """The date the holiday falls on in `year`, before any observed-day shift."""
        if self.day is not None:
            try:
                return date(year, self.month, self.day)
            except ValueError:
                return None
        if self.weekday is None or not self.nth:
            return None
        days = calendar.monthrange(year, self.month)[1]
        matches = [date(year, self.month, d) for d in range(1, days + 1)
                   if date(year, self.month, d).weekday() == self.weekday]
        if self.nth == -1:
            return matches[-1]
        return matches[self.nth - 1] if 0 < self.nth <= len(matches) else None


@dataclass(frozen=True)
class HolidayCalendar:
    rules: tuple[HolidayRule, ...]
    shift: tuple[tuple[int, int], ...] = ()   # (weekday, days to move), e.g. Saturday -1

    def observed(self, rule: HolidayRule, year: int) -> date | None:
        d = rule.actual(year)
        if d is None:
            return None
        if rule.day is not None:
            d += timedelta(days=dict(self.shift).get(d.weekday(), 0))
        return d


# Portland General Electric, Time of Day: six holidays are off-peak all day; Saturday
# moves to the Friday before, Sunday to the Monday after
# (portlandgeneral.com/about/info/pricing-plans/time-of-day).
PGE = HolidayCalendar(
    rules=(
        HolidayRule("New Year's Day", 1, day=1),
        HolidayRule("Memorial Day", 5, weekday=0, nth=-1),
        HolidayRule("Independence Day", 7, day=4),
        HolidayRule("Labor Day", 9, weekday=0, nth=1),
        HolidayRule("Thanksgiving", 11, weekday=3, nth=4),
        HolidayRule("Christmas Day", 12, day=25),
    ),
    shift=((5, -1), (6, +1)),
)

_CALENDARS: dict[str, HolidayCalendar] = {
    HOLIDAY_PRESET_NONE: HolidayCalendar(rules=()),
    HOLIDAY_PRESET_PGE: PGE,
}


def normalize_preset(preset: str | None) -> str:
    """A known preset name; anything unknown or empty means no holidays."""
    p = str(preset or "").strip().lower()
    return p if p in _CALENDARS else HOLIDAY_PRESET_NONE


@lru_cache(maxsize=32)
def holidays_in_year(year: int, preset: str) -> dict[date, str]:
    """Observed holiday dates that fall in `year`, with their names."""
    cal = _CALENDARS[normalize_preset(preset)]
    out: dict[date, str] = {}
    for y in (year - 1, year, year + 1):       # a shift can cross New Year
        for rule in cal.rules:
            d = cal.observed(rule, y)
            if d is not None and d.year == year:
                out[d] = rule.name
    return out


def holiday_name(d: date, preset: str | None) -> str | None:
    """The holiday observed on `d`, or None."""
    return holidays_in_year(d.year, normalize_preset(preset)).get(d)


def next_holiday(d: date, preset: str | None) -> tuple[date, str] | None:
    """The first observed holiday on or after `d`, or None when there are none."""
    p = normalize_preset(preset)
    for year in (d.year, d.year + 1):
        later = sorted((h, n) for h, n in holidays_in_year(year, p).items() if h >= d)
        if later:
            return later[0]
    return None


def is_tou_day(d: date, weekdays_only: bool, holiday_preset: str | None = HOLIDAY_PRESET_NONE) -> bool:
    """The one answer to "do the mid-peak and peak windows apply on this date?".

    Every planner, timer, scorecard and load-profile decision asks this; nothing else
    in the integration tests the day of the week.
    """
    if holiday_name(d, holiday_preset) is not None:
        return False
    return d.weekday() < 5 if weekdays_only else True


def is_last_tou_day_of_week(d: date, weekdays_only: bool, holiday_preset: str | None = HOLIDAY_PRESET_NONE) -> bool:
    """True on a TOU day followed by a non-TOU day, with no later TOU day in the same
    Monday-to-Sunday week. A mid-week holiday (Thanksgiving) is not the end of the week;
    a Friday holiday makes Thursday the last TOU day."""
    if not is_tou_day(d, weekdays_only, holiday_preset):
        return False
    if is_tou_day(d + timedelta(days=1), weekdays_only, holiday_preset):
        return False
    for i in range(2, 7 - d.weekday()):
        if is_tou_day(d + timedelta(days=i), weekdays_only, holiday_preset):
            return False
    return True


def holiday_attributes(today: date, preset: str | None) -> dict[str, object]:
    """For the Learned Plan sensor: is today / tomorrow a holiday, and the next one."""
    p = normalize_preset(preset)
    nxt = next_holiday(today, p)
    return {
        "holiday_preset": p,
        "holiday_today": holiday_name(today, p),
        "holiday_tomorrow": holiday_name(today + timedelta(days=1), p),
        "next_holiday": "%s %s" % (nxt[0].isoformat(), nxt[1]) if nxt else None,
    }
