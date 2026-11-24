"""What the dashboard says about the plan (0.9.2). Pure Python: no Home Assistant imports.

Two answers, both read from the learned planner's last decision and the inputs it was
made with, so they never disagree with what the planner is doing:

- `peak_outlook`: the gauge expected at the end of the next peak window the planner has
  planned for. Today's window while it is still ahead or running; tomorrow's once the night
  rule is planning for it (from today's peak end, or the evening before a TOU day). The
  same prediction the health record grades (`predict_gauge`, mean load, solar discounted by
  the solar confidence), started from where the plan will put the battery: the night
  target before mid-peak, the top-up target while a top-up runs, else the gauge now.
  None when it cannot tell: no gauge, the model not trained yet, or no peak planned (a
  weekend afternoon, a holiday).
- `plan_sentence`: the day's plan in one plain sentence, ASCII, at most 255 characters
  (a Home Assistant state).

Neither acts on anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .holidays import day_name
from .learning import Learner, LoadProfile
from .planner import MODE_CHARGE, MODE_DISCHARGE, MODE_HOLD, Decision, PlanInputs, predict_gauge
from .tariff import Windows

#: a Home Assistant state is at most this long
MAX_STATE_LEN = 255
#: the expected peak-end gauge has to clear the floor by this much to count as covered
COVERED_MARGIN_PTS = 0.5


@dataclass(frozen=True)
class Outlook:
    day: str                    # "today" or "tomorrow"
    for_date: date
    windows: Windows
    start_hour: float           # the prediction runs from this hour ...
    start_gauge: float          # ... starting at this gauge
    gauge_end: float            # expected gauge at peak end
    spare_kwh: float            # energy above the floor at peak end
    covered: bool               # the floor is not reached before peak end
    assumes_charge: bool        # the start gauge is a charge target, not today's reading

    def as_dict(self) -> dict[str, Any]:
        return {
            "for": self.day,
            "for_date": self.for_date.isoformat(),
            "peak_window": "%s-%s" % (_hh(self.windows.peak_start), _hh(self.windows.peak_end)),
            "from_hour": round(self.start_hour, 2),
            "from_gauge": round(self.start_gauge, 1),
            "spare_kwh": round(self.spare_kwh, 2),
            "covered": self.covered,
            "assumes_charge": self.assumes_charge,
        }


def _hh(hour: int) -> str:
    return "%02d:00" % (hour % 24)


def _night_start(inp: PlanInputs, d: Decision) -> tuple[float, bool]:
    """The gauge the night rule will leave at mid-peak start, and whether that is a target."""
    gauge = float(inp.gauge)
    target = d.target_gauge
    if target is None:
        return gauge, False
    if d.mode == MODE_CHARGE:
        return max(gauge, target), target > gauge
    if d.mode == MODE_HOLD:
        if inp.bank_full:                   # the charge is over; the gauge is what it reached
            return gauge, False
        return max(gauge, target), target > gauge
    # discharge: more on board than needed, running down to the target before holding
    return min(gauge, target), False


def peak_outlook(inp: PlanInputs | None, d: Decision | None, learner: Learner, profile: LoadProfile,
                 today: Windows, tomorrow: Windows) -> Outlook | None:
    """The gauge expected at the end of the next planned peak window, or None (see above)."""
    if inp is None or d is None or inp.gauge is None or not d.model_ready:
        return None
    now = inp.now
    h = now.hour + now.minute / 60.0
    assumes = False
    if inp.is_tou_today and h < today.peak_end:
        w, day, when, solar = today, "today", now.date(), inp.solar_today
        if h < w.midpeak_start:
            start_h = float(w.midpeak_start)
            start_g, assumes = _night_start(inp, d)
        elif (h < w.peak_start and d.mode == MODE_CHARGE and d.phase == "mid-peak"
              and d.target_gauge is not None):
            # a top-up is running: the grid carries the house until it ends by peak start
            start_h, start_g, assumes = float(w.peak_start), max(float(inp.gauge), d.target_gauge), True
        else:
            start_h, start_g = h, float(inp.gauge)
    elif d.phase == "night" and inp.is_tou_tomorrow:
        w, day, when, solar = tomorrow, "tomorrow", now.date() + timedelta(days=1), inp.solar_tomorrow
        start_h = float(w.midpeak_start)
        start_g, assumes = _night_start(inp, d)
    else:
        return None
    end = predict_gauge(learner, profile, solar, start_g, start_h, w.peak_end, inp.floor,
                        inp.solar_confidence)
    spare = learner.discharge.energy_between(inp.floor, end) if end > inp.floor else 0.0
    return Outlook(day=day, for_date=when, windows=w, start_hour=start_h, start_gauge=start_g,
                   gauge_end=end, spare_kwh=spare, covered=end > inp.floor + COVERED_MARGIN_PTS,
                   assumes_charge=assumes)


# --- The sentence -------------------------------------------------------------------------


def _pct(value: float) -> str:
    return "%d %%" % round(value)


def _night_part(inp: PlanInputs, d: Decision, mid_start: int) -> str:
    """What the night rule is doing, as a clause."""
    by = _hh(mid_start)
    target = d.target_gauge
    if d.mode == MODE_CHARGE:
        if target is None or target >= 99.5:
            return "charging until the inverter stops, then holding until %s" % by
        return "charging to %s by %s" % (_pct(target), by)
    if d.mode == MODE_HOLD:
        if target is not None and inp.gauge is not None and target > inp.gauge + 0.5 and not inp.bank_full:
            lead = " about %.1f h before %s" % (d.lead_hours, by) if d.lead_hours is not None else ""
            return "holding; the charge to %s starts%s" % (_pct(target), lead)
        if inp.gauge is not None:
            return "holding at %s until %s" % (_pct(inp.gauge), by)
        return "holding until %s" % by
    if target is not None:
        return "on battery overnight down to %s, then holding until %s" % (_pct(target), by)
    return "on battery"


def _tail(inp: PlanInputs, d: Decision, outlook: Outlook | None, peak_word: str = "peak") -> str:
    """The forecast clause: where the battery is expected to end the peak window."""
    if outlook is None:
        if inp.gauge is None:
            return "no forecast without a battery reading"
        if not d.model_ready:
            return "no forecast until the model has learned enough"
        return ""
    if not outlook.covered:
        return "expected to reach the floor before %s" % _hh(outlook.windows.peak_end)
    return "expected to end %s at %s (%.1f kWh to spare)" % (peak_word, _pct(outlook.gauge_end),
                                                           outlook.spare_kwh)


def _join(*parts: str) -> str:
    return "; ".join(p for p in parts if p)


def _clip(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= MAX_STATE_LEN:
        return text
    return text[: MAX_STATE_LEN - 3].rstrip() + "..."


def plan_sentence(inp: PlanInputs | None, d: Decision | None, outlook: Outlook | None,
                  today: Windows, tomorrow: Windows, holiday_today: str | None = None,
                  holiday_tomorrow: str | None = None, in_control: bool = True,
                  peak_price: float | None = None) -> str | None:
    """The plan in one plain sentence (None before the first decision)."""
    if inp is None or d is None:
        return None
    now = inp.now
    h = now.hour + now.minute / 60.0
    peak = "peak %s-%s" % (_hh(today.peak_start), _hh(today.peak_end))

    if inp.is_tou_today and h < today.peak_end:
        if d.phase == "peak" or h >= today.peak_start:
            text = "Peak until %s: on battery, never charging; %s." % (
                _hh(today.peak_end), _tail(inp, d, outlook, "it") or "no forecast")
        elif d.phase == "night" or h < today.midpeak_start:
            text = "Today: %s, then on battery through %s; %s." % (
                _night_part(inp, d, today.midpeak_start), peak, _tail(inp, d, outlook) or "no forecast")
        elif d.mode == MODE_CHARGE:
            text = "Today: topping up from the grid to finish by %s, then on battery through %s; %s." % (
                _hh(today.peak_start), peak, _tail(inp, d, outlook) or "no forecast")
        elif d.shortfall_kwh is not None and d.shortfall_kwh > 0:
            cost = " (about $%.2f at peak price)" % (d.shortfall_kwh * peak_price) if peak_price else ""
            text = ("Today: on battery; %s looks short by %.1f kWh%s, so a top-up starts before %s "
                    "if that holds; %s." % (peak, d.shortfall_kwh, cost, _hh(today.peak_start),
                                            _tail(inp, d, outlook) or "no forecast"))
        elif inp.gauge is None:
            text = d.reason
        else:
            text = "Today: on battery through %s; %s." % (peak, _tail(inp, d, outlook) or "no forecast")
    elif d.phase == "night" and inp.is_tou_tomorrow:
        nxt = now.date() + timedelta(days=1)
        lead = "Peak is over for today. " if inp.is_tou_today else ""
        text = "%sTomorrow (%s): %s." % (lead, day_name(nxt), _join(
            _night_part(inp, d, tomorrow.midpeak_start), _tail(inp, d, outlook) or "no forecast"))
    else:
        if inp.is_tou_today:
            nxt = now.date() + timedelta(days=1)
            text = "Peak is over for today. No peak prices tomorrow (%s)." % (holiday_tomorrow or day_name(nxt))
        else:
            text = "No peak prices today (%s): solar first, then battery." % (holiday_today or day_name(now.date()))
            if inp.is_tou_tomorrow:
                text += " Tomorrow's charge is planned from %s." % _hh(inp.peak_end)
        if d.phase == "top-up":
            text += " " + d.reason
        elif d.mode != MODE_DISCHARGE:
            text += " " + d.reason
    if not in_control:
        text = "Shadow plan (classic planner in control): " + text
    return _clip(text)
