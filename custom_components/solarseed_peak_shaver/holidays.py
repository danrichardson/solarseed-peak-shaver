"""Utility holidays and the one test for "is this a TOU day" (ROADMAP item 7).

Pure Python, no Home Assistant imports. A holiday is an off-peak day all day: no
pre-TOU night charge for it, no mid-peak or peak window on it, not graded, and its
load goes into the learner's "other days" history like a weekend.

Rules are data, and since 0.9.1 they can be typed (one per line or comma-separated):

- `01-01 New Year's Day`: a fixed date (month-day), moved by the observed-day shift when
  it falls on a weekend;
- `11-thu-4 Thanksgiving`, `05-mon-last Memorial Day`: the nth weekday of a month (1..5)
  or the last one; these are never shifted;
- `sat->fri, sun->mon`: the observed-day shift for fixed dates.

The name after a date rule is optional. One-off dates (`2026-12-24 Christmas Eve`) are a
separate list, never shifted. Presets (PGE, US federal) are the same rules as data, and
fill the rules field when chosen.

The shift can move a holiday into another year: 2028-01-01 is a Saturday, so it is
observed on Friday 2027-12-31.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, replace
from datetime import date, timedelta
from functools import lru_cache

HOLIDAY_PRESET_NONE = "none"
HOLIDAY_PRESET_PGE = "pge"
HOLIDAY_PRESET_US_FEDERAL = "us_federal"
HOLIDAY_PRESET_CUSTOM = "custom"
HOLIDAY_PRESETS = (HOLIDAY_PRESET_NONE, HOLIDAY_PRESET_PGE, HOLIDAY_PRESET_US_FEDERAL, HOLIDAY_PRESET_CUSTOM)

# Day types a tariff prices separately.
DAY_WEEKDAY = "weekday"
DAY_WEEKEND = "weekend"
DAY_HOLIDAY = "holiday"

_WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_WORDS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


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

    def token(self) -> str:
        """The rule as it is typed: `01-01`, `11-thu-4`, `05-mon-last`."""
        if self.day is not None:
            return "%02d-%02d" % (self.month, self.day)
        return "%02d-%s-%s" % (self.month, _WEEKDAY_NAMES[self.weekday or 0],
                               "last" if self.nth == -1 else self.nth)


@dataclass(frozen=True)
class HolidayCalendar:
    rules: tuple[HolidayRule, ...]
    shift: tuple[tuple[int, int], ...] = ()   # (weekday, days to move), e.g. Saturday -1
    dates: tuple[tuple[date, str], ...] = ()  # one-off dates, never shifted

    def observed(self, rule: HolidayRule, year: int) -> date | None:
        d = rule.actual(year)
        if d is None:
            return None
        if rule.day is not None:
            d += timedelta(days=dict(self.shift).get(d.weekday(), 0))
        return d


_WEEKEND_SHIFT = ((5, -1), (6, +1))

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
    shift=_WEEKEND_SHIFT,
)

# The eleven US federal holidays (5 U.S.C. 6103), with the same weekend shift.
US_FEDERAL = HolidayCalendar(
    rules=(
        HolidayRule("New Year's Day", 1, day=1),
        HolidayRule("Martin Luther King Jr. Day", 1, weekday=0, nth=3),
        HolidayRule("Washington's Birthday", 2, weekday=0, nth=3),
        HolidayRule("Memorial Day", 5, weekday=0, nth=-1),
        HolidayRule("Juneteenth", 6, day=19),
        HolidayRule("Independence Day", 7, day=4),
        HolidayRule("Labor Day", 9, weekday=0, nth=1),
        HolidayRule("Columbus Day", 10, weekday=0, nth=2),
        HolidayRule("Veterans Day", 11, day=11),
        HolidayRule("Thanksgiving", 11, weekday=3, nth=4),
        HolidayRule("Christmas Day", 12, day=25),
    ),
    shift=_WEEKEND_SHIFT,
)

NO_HOLIDAYS = HolidayCalendar(rules=())

_CALENDARS: dict[str, HolidayCalendar] = {
    HOLIDAY_PRESET_NONE: NO_HOLIDAYS,
    HOLIDAY_PRESET_PGE: PGE,
    HOLIDAY_PRESET_US_FEDERAL: US_FEDERAL,
}


def normalize_preset(preset: str | None) -> str:
    """A known preset name; anything unknown or empty means no holidays."""
    p = str(preset or "").strip().lower()
    return p if p in HOLIDAY_PRESETS else HOLIDAY_PRESET_NONE


def _resolve(holidays: HolidayCalendar | str | None) -> HolidayCalendar:
    """A calendar from a calendar or a preset name ("custom" alone has no rules)."""
    if isinstance(holidays, HolidayCalendar):
        return holidays
    return _CALENDARS.get(normalize_preset(holidays), NO_HOLIDAYS)


# --- Typed rules --------------------------------------------------------------------------

_SPLIT = re.compile(r"[,;\n]+")
_FIXED = re.compile(r"^(\d{1,2})-(\d{1,2})(?:\s+(.*))?$")
_NTH = re.compile(r"^(\d{1,2})-([a-z]{3})-(\w+)(?:\s+(.*))?$", re.IGNORECASE)
_SHIFT = re.compile(r"^([a-z]{3})\s*->\s*([a-z]{3})$", re.IGNORECASE)
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+(.*))?$")


def _items(text: str | None) -> list[str]:
    return [i.strip() for i in _SPLIT.split(str(text or "")) if i.strip()]


def parse_rules(text: str | None) -> tuple[HolidayCalendar, list[str]]:
    """Typed holiday rules as a calendar, and a plain message for each item not understood.

    The calendar keeps every item that was understood, so a bad line in a stored option
    costs that one holiday (the day is then planned as a TOU day: a wasted charge, no harm),
    never the others. The form refuses any text with a message.
    """
    rules: list[HolidayRule] = []
    shift: dict[int, int] = {}
    errors: list[str] = []
    for item in _items(text):
        if _ISO.match(item):
            errors.append("%s is a one-off date; put it in the one-off holidays field" % item)
            continue
        m = _SHIFT.match(item)
        if m:
            src, dst = m.group(1).lower(), m.group(2).lower()
            if src not in ("sat", "sun") or dst not in _WEEKDAY_NAMES[:5]:
                errors.append("%s: a shift moves sat or sun to a weekday, like sat->fri or sun->mon" % item)
                continue
            s, t = _WEEKDAY_NAMES.index(src), _WEEKDAY_NAMES.index(dst)
            delta = (t - s) % 7
            shift[s] = delta - 7 if delta > 3 else delta
            continue
        m = _FIXED.match(item)
        if m:
            month, day, name = int(m.group(1)), int(m.group(2)), (m.group(3) or "").strip()
            try:
                date(2000, month, day)              # a leap year, so 02-29 is allowed
            except ValueError:
                errors.append("%s: no such month and day" % item.split()[0])
                continue
            rules.append(HolidayRule(name or "%02d-%02d" % (month, day), month, day=day))
            continue
        m = _NTH.match(item)
        if m:
            month, wd, nth_s, name = int(m.group(1)), m.group(2).lower(), m.group(3).lower(), (m.group(4) or "").strip()
            token = item.split()[0]
            if not 1 <= month <= 12:
                errors.append("%s: the month must be 01 to 12" % token)
                continue
            if wd not in _WEEKDAY_NAMES:
                errors.append("%s: the day must be one of %s" % (token, ", ".join(_WEEKDAY_NAMES)))
                continue
            if nth_s == "last":
                nth = -1
            elif nth_s.isdigit() and 1 <= int(nth_s) <= 5:
                nth = int(nth_s)
            else:
                errors.append("%s: the count must be 1 to 5 or last" % token)
                continue
            rule = HolidayRule(name, month, weekday=_WEEKDAY_NAMES.index(wd), nth=nth)
            rules.append(rule if name else replace(rule, name=rule.token()))
            continue
        errors.append("%s is not a holiday rule (examples: 01-01, 11-thu-4, 05-mon-last, sat->fri)" % item)
    return HolidayCalendar(rules=tuple(rules), shift=tuple(sorted(shift.items()))), errors


def parse_dates(text: str | None) -> tuple[tuple[tuple[date, str], ...], list[str]]:
    """One-off holidays (`2026-12-24 Christmas Eve`), and a message for each item not understood."""
    out: list[tuple[date, str]] = []
    errors: list[str] = []
    for item in _items(text):
        m = _ISO.match(item)
        if not m:
            errors.append("%s is not a date like 2026-12-24" % item)
            continue
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            errors.append("%s: no such date" % item.split()[0])
            continue
        out.append((d, (m.group(4) or "").strip() or "Holiday"))
    return tuple(sorted(set(out))), errors


def format_rules(cal: HolidayCalendar) -> str:
    """The calendar's rules as they are typed, one per line, the shift last."""
    lines = ["%s %s" % (r.token(), r.name) if r.name != r.token() else r.token() for r in cal.rules]
    if cal.shift:
        lines.append(", ".join("%s->%s" % (_WEEKDAY_NAMES[wd], _WEEKDAY_NAMES[(wd + delta) % 7])
                               for wd, delta in cal.shift))
    return "\n".join(lines)


def preset_rules_text(preset: str | None) -> str | None:
    """The rules text a preset fills in; None for custom (the typed text is kept)."""
    p = normalize_preset(preset)
    if p == HOLIDAY_PRESET_CUSTOM:
        return None
    return format_rules(_CALENDARS[p])


def same_rules(a: str | None, b: str | None) -> bool:
    """Two rule texts that say the same thing (spacing, order of lines and case aside)."""
    canon = lambda t: sorted(" ".join(i.lower().split()) for i in _items(t))
    return canon(a) == canon(b)


@lru_cache(maxsize=32)
def build_calendar(preset: str | None, rules_text: str | None, dates_text: str | None) -> HolidayCalendar:
    """The holidays in force: a preset's rules (or the typed ones for custom), plus one-off dates."""
    p = normalize_preset(preset)
    cal = parse_rules(rules_text)[0] if p == HOLIDAY_PRESET_CUSTOM else _CALENDARS[p]
    dates = parse_dates(dates_text)[0]
    return replace(cal, dates=dates) if dates else cal


def describe_shift(cal: HolidayCalendar) -> str:
    """`Saturday to Friday, Sunday to Monday`, for the log and the sensor."""
    return ", ".join("%s to %s" % (_DAY_WORDS[wd], _DAY_WORDS[(wd + d) % 7]) for wd, d in cal.shift)


# --- Questions ----------------------------------------------------------------------------


@lru_cache(maxsize=64)
def _in_year(year: int, cal: HolidayCalendar) -> dict[date, str]:
    out: dict[date, str] = {}
    for y in (year - 1, year, year + 1):       # a shift can cross New Year
        for rule in cal.rules:
            d = cal.observed(rule, y)
            if d is not None and d.year == year:
                out.setdefault(d, rule.name)
    for d, name in cal.dates:
        if d.year == year:
            out.setdefault(d, name)
    return out


def holidays_in_year(year: int, holidays: HolidayCalendar | str | None) -> dict[date, str]:
    """Observed holiday dates that fall in `year`, with their names."""
    return dict(_in_year(year, _resolve(holidays)))


def holiday_name(d: date, holidays: HolidayCalendar | str | None) -> str | None:
    """The holiday observed on `d`, or None."""
    return _in_year(d.year, _resolve(holidays)).get(d)


def next_holiday(d: date, holidays: HolidayCalendar | str | None) -> tuple[date, str] | None:
    """The first observed holiday on or after `d`, or None when there are none."""
    cal = _resolve(holidays)
    for year in (d.year, d.year + 1):
        later = sorted((h, n) for h, n in _in_year(year, cal).items() if h >= d)
        if later:
            return later[0]
    return None


def day_type(d: date, holidays: HolidayCalendar | str | None = HOLIDAY_PRESET_NONE) -> str:
    """weekday, weekend or holiday: the day types a tariff prices separately."""
    if holiday_name(d, holidays) is not None:
        return DAY_HOLIDAY
    return DAY_WEEKEND if d.weekday() >= 5 else DAY_WEEKDAY


def is_tou_day(d: date, weekdays_only: bool, holidays: HolidayCalendar | str | None = HOLIDAY_PRESET_NONE) -> bool:
    """The one answer to "do the mid-peak and peak windows apply on this date?".

    Every planner, timer, scorecard and load-profile decision asks this; nothing else
    in the integration tests the day of the week. A holiday is off-peak all day; a weekend
    day is too unless the windows apply every day.
    """
    kind = day_type(d, holidays)
    if kind == DAY_HOLIDAY:
        return False
    return kind == DAY_WEEKDAY or not weekdays_only


def is_last_tou_day_of_week(d: date, weekdays_only: bool,
                            holidays: HolidayCalendar | str | None = HOLIDAY_PRESET_NONE) -> bool:
    """True on a TOU day followed by a non-TOU day, with no later TOU day in the same
    Monday-to-Sunday week. A mid-week holiday (Thanksgiving) is not the end of the week;
    a Friday holiday makes Thursday the last TOU day."""
    if not is_tou_day(d, weekdays_only, holidays):
        return False
    if is_tou_day(d + timedelta(days=1), weekdays_only, holidays):
        return False
    for i in range(2, 7 - d.weekday()):
        if is_tou_day(d + timedelta(days=i), weekdays_only, holidays):
            return False
    return True


def day_name(d: date) -> str:
    """`Monday` ... `Sunday`, in English whatever the locale (for the plan sentence)."""
    return _DAY_WORDS[d.weekday()]


def holiday_attributes(today: date, holidays: HolidayCalendar | str | None,
                       preset: str | None = None) -> dict[str, object]:
    """For the Learned Plan sensor: is today / tomorrow a holiday, and the next one."""
    if preset is None:
        preset = holidays if isinstance(holidays, str) or holidays is None else HOLIDAY_PRESET_CUSTOM
    cal = _resolve(holidays)
    nxt = next_holiday(today, cal)
    return {
        "holiday_preset": normalize_preset(preset),
        "holiday_today": holiday_name(today, cal),
        "holiday_tomorrow": holiday_name(today + timedelta(days=1), cal),
        "next_holiday": "%s %s" % (nxt[0].isoformat(), nxt[1]) if nxt else None,
    }
