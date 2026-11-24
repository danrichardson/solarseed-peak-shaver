"""Utility holidays (0.8.2, ROADMAP item 7) and the hold-at-full false alarm."""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.test_learned_runtime import fired, make_runtime, run

from custom_components.solarseed_peak_shaver.const import (
    CONF_HOLIDAY_PRESET,
    EVENT_CHARGE_START,
    EVENT_PRESERVE_START,
)
from custom_components.solarseed_peak_shaver.holidays import (
    holiday_attributes,
    holiday_name,
    holidays_in_year,
    is_last_tou_day_of_week,
    is_tou_day,
    next_holiday,
    normalize_preset,
)
from custom_components.solarseed_peak_shaver.learned_runtime import infer_mode, mode_matches
from custom_components.solarseed_peak_shaver.planner import MODE_CHARGE, MODE_DISCHARGE, MODE_HOLD

WED_EVE = datetime(2026, 11, 25, 21, 30)        # the evening before Thanksgiving 2026
THANKSGIVING = date(2026, 11, 26)


class TestPgeRules:
    def test_2026(self):
        assert sorted(holidays_in_year(2026, "pge")) == [
            date(2026, 1, 1), date(2026, 5, 25), date(2026, 7, 3), date(2026, 9, 7),
            date(2026, 11, 26), date(2026, 12, 25)]

    @pytest.mark.parametrize("d,name", [
        (date(2026, 7, 3), "Independence Day"),       # Jul 4 is a Saturday: the Friday before
        (date(2027, 7, 5), "Independence Day"),       # Jul 4 is a Sunday: the Monday after
        (date(2027, 12, 24), "Christmas Day"),        # Dec 25 is a Saturday
        (date(2027, 12, 31), "New Year's Day"),       # 2028-01-01 is a Saturday: the year before
        (date(2026, 11, 26), "Thanksgiving"),         # fourth Thursday
        (date(2027, 5, 31), "Memorial Day"),          # last Monday in May
        (date(2027, 9, 6), "Labor Day"),              # first Monday in September
    ])
    def test_observed_days(self, d, name):
        assert holiday_name(d, "pge") == name

    @pytest.mark.parametrize("d", [date(2026, 7, 4), date(2027, 7, 4), date(2027, 12, 25),
                                   date(2028, 1, 1), date(2026, 11, 27), date(2026, 11, 19)])
    def test_not_observed(self, d):
        assert holiday_name(d, "pge") is None

    def test_2028_has_no_new_years_day_of_its_own(self):
        assert date(2027, 12, 31) in holidays_in_year(2027, "pge")
        assert not any(d.month == 1 for d in holidays_in_year(2028, "pge"))

    def test_every_year_has_six(self):
        for year in range(2020, 2040):
            days = holidays_in_year(year, "pge")
            # a year loses New Year's Day to the year before, and may gain the next one
            assert 5 <= len(days) <= 7, year
            assert all(d.weekday() < 5 for d in days), year

    def test_none_and_unknown_presets_have_no_holidays(self):
        assert holidays_in_year(2026, "none") == {}
        assert normalize_preset("bogus") == "none"
        assert normalize_preset(None) == "none"
        assert normalize_preset(" PGE ") == "pge"
        assert holiday_name(THANKSGIVING, "bogus") is None

    def test_next_holiday_crosses_the_year(self):
        assert next_holiday(date(2026, 11, 24), "pge") == (THANKSGIVING, "Thanksgiving")
        assert next_holiday(date(2026, 12, 26), "pge") == (date(2027, 1, 1), "New Year's Day")
        assert next_holiday(date(2026, 12, 26), "none") is None

    def test_attributes(self):
        a = holiday_attributes(date(2026, 11, 25), "pge")
        assert a == {"holiday_preset": "pge", "holiday_today": None, "holiday_tomorrow": "Thanksgiving",
                     "next_holiday": "2026-11-26 Thanksgiving"}


class TestTouDay:
    def test_holiday_is_not_a_tou_day(self):
        assert not is_tou_day(THANKSGIVING, True, "pge")
        assert is_tou_day(THANKSGIVING, True, "none")
        assert is_tou_day(THANKSGIVING, True)                 # no preset given: no holidays
        assert not is_tou_day(THANKSGIVING, False, "pge")      # holidays apply on every-day plans too
        assert not is_tou_day(date(2026, 11, 28), True, "pge")  # Saturday
        assert is_tou_day(date(2026, 11, 27), True, "pge")

    def test_last_tou_day_of_the_week(self):
        assert not is_last_tou_day_of_week(date(2026, 11, 25), True, "pge")   # Friday still comes
        assert is_last_tou_day_of_week(date(2026, 11, 27), True, "pge")
        assert is_last_tou_day_of_week(date(2026, 7, 2), True, "pge")         # Friday Jul 3 is off
        assert is_last_tou_day_of_week(date(2026, 11, 20), True, "none")
        assert not is_last_tou_day_of_week(date(2026, 11, 26), True, "pge")   # not a TOU day itself
        # every day TOU, no holidays: never (as before 0.8.2)
        for day in range(16, 23):
            assert not is_last_tou_day_of_week(date(2026, 11, day), False, "none")

    def test_one_function_answers_the_day_type(self):
        """Nothing outside holidays.py tests the day of the week."""
        root = Path(__file__).resolve().parents[1] / "custom_components" / "solarseed_peak_shaver"
        hits = [f"{p.name}:{n}" for p in root.glob("*.py") if p.name != "holidays.py"
                for n, line in enumerate(p.read_text().splitlines(), 1)
                if re.search(r"\.weekday\(\)", line)]
        assert hits == []


class TestThanksgivingWeek:
    """Absent `holiday_preset` key (an entry saved by 0.8.1): PGE holidays apply."""

    def test_option_absent_means_pge(self):
        rt, coord, world = make_runtime(planner="learned")
        assert coord.holiday_preset == "pge"
        assert not coord.is_tou_day(THANKSGIVING)

    def test_no_night_charge_before_the_holiday(self):
        rt, coord, world = make_runtime(planner="learned")
        world.values["sensor.gauge"] = (30, "%")
        run(rt, datetime(2026, 11, 25, 20, 50), 60)           # Wednesday across 21:00 to 21:50
        assert rt.decision.mode == MODE_DISCHARGE
        assert rt.decision.phase == "off-peak"
        assert not rt.topup_pending                           # not the last TOU day of the week
        assert EVENT_CHARGE_START not in fired(coord)

    def test_the_holiday_is_off_peak_all_day_and_not_scored(self):
        rt, coord, world = make_runtime(planner="learned")
        world.values["sensor.gauge"] = (60, "%")
        world.values["sensor.grid"] = (300, "W")
        run(rt, datetime(2026, 11, 26, 0, 0), 20 * 60)        # midnight to 20:00
        assert rt.decision.phase == "off-peak"
        assert EVENT_CHARGE_START not in fired(coord)
        assert set(rt.daily_summary()["grid_kwh"]) == {"off-peak"}
        coord.hass.async_create_task = MagicMock()
        coord._on_daily_scoring_time(datetime(2026, 11, 26, 21, 10))
        coord.hass.async_create_task.assert_not_called()      # no scorecard, no daily message
        coord._on_scheduled_time(datetime(2026, 11, 26, 4, 0))
        coord.hass.async_create_task.assert_not_called()      # classic does not run either

    def test_friday_charge_is_planned_on_the_holiday_evening(self):
        rt, coord, world = make_runtime(planner="learned")
        world.values["sensor.gauge"] = (30, "%")
        run(rt, datetime(2026, 11, 26, 20, 58), 5)
        assert rt.decision.phase == "night"
        assert rt.decision.mode == MODE_CHARGE                # November: charge to full for Friday
        assert fired(coord)[-1] == EVENT_CHARGE_START

    def test_weekly_topup_moves_to_friday(self):
        rt, coord, world = make_runtime(planner="learned")
        run(rt, datetime(2026, 11, 27, 20, 58), 5)
        assert rt.topup_pending

    def test_the_holiday_goes_into_the_other_days_profile(self):
        rt, coord, world = make_runtime()
        run(rt, datetime(2026, 11, 26, 0, 0), 24 * 60 + 2)
        assert rt.profile.n_days(False) == 1
        assert rt.profile.n_days(True) == 0

    def test_preset_none_keeps_the_old_behaviour(self):
        rt, coord, world = make_runtime(planner="learned", **{CONF_HOLIDAY_PRESET: "none"})
        world.values["sensor.gauge"] = (30, "%")
        run(rt, datetime(2026, 11, 25, 20, 58), 5)
        assert rt.decision.phase == "night"                   # Thursday is a weekday
        assert coord.is_tou_day(THANKSGIVING)

    def test_plan_sensor_attributes(self):
        from custom_components.solarseed_peak_shaver.const import SENSOR_LEARNED_PLAN
        from custom_components.solarseed_peak_shaver.sensor import PeakShaverSensor

        rt, coord, world = make_runtime(planner="learned")
        run(rt, WED_EVE, 2)
        coord.data = {}
        sensor = PeakShaverSensor.__new__(PeakShaverSensor)
        sensor.coordinator = coord
        sensor._sensor_key = SENSOR_LEARNED_PLAN
        attrs = sensor.extra_state_attributes
        for key in ("holiday_preset", "holiday_today", "holiday_tomorrow", "next_holiday"):
            assert key in attrs


class TestHoldAtFull:
    """2026-11-23 evening: charge ended at 100 %, hold sent, the inverter carried the
    house from the battery (AC in 0 W, AC out about 0.6 kW) until the gauge fell to 99."""

    def test_mode_matches_cannot_tell(self):
        assert mode_matches(MODE_HOLD, 100, 0.0, 0.6, 0, 3, True) is None
        assert mode_matches(MODE_HOLD, 100, 0.0, 0.6, 0, 3, False) is None
        assert mode_matches(MODE_HOLD, 99, 0.0, 0.6, 0, 3, False) is None
        assert mode_matches(MODE_HOLD, 99.4, 0.0, 0.68, 0, 3, True) is None
        assert mode_matches(MODE_HOLD, None, 0.0, 0.6, 0, 3, False) is None
        assert mode_matches(MODE_HOLD, 98, 0.0, 0.6, 0, 3, False) is False   # below full: still caught
        assert mode_matches(MODE_HOLD, 98, 0.6, 0.6, 0, 3, False) is True

    def test_infer_mode_after_a_restart_at_full(self):
        assert infer_mode(100, 0.0, 0.6, 0, 3) is None
        assert infer_mode(99, 0.0, 0.6, 0, 3) is None
        assert infer_mode(None, 0.0, 0.6, 0, 3) is None
        assert infer_mode(50, 0.0, 0.6, 0, 3) == MODE_DISCHARGE

    def test_no_resend_and_no_alarm(self):
        rt, coord, world = make_runtime(planner="learned")
        coord._notify = MagicMock()
        world.values["sensor.gauge"] = (30, "%")
        run(rt, datetime(2026, 11, 23, 21, 0), 1)             # Monday night charge for Tuesday
        assert fired(coord)[-1] == EVENT_CHARGE_START
        world.values["sensor.grid"] = (3000, "W")
        run(rt, datetime(2026, 11, 23, 21, 1), 2)
        world.values["sensor.gauge"] = (100, "%")
        world.values["sensor.grid"] = (0, "W")
        world.values["sensor.load"] = (600, "W")
        run(rt, datetime(2026, 11, 23, 21, 3), 40)            # full: hold, battery carries the house
        assert rt.decision.mode == MODE_HOLD
        assert fired(coord).count(EVENT_PRESERVE_START) == 1
        s = rt.daily_summary()
        assert s["command_retries"] == 0
        assert s["commands_not_followed"] == 0
        titles = [c.args[0] for c in coord._notify.call_args_list]
        assert not any("not responding" in t for t in titles)

    def test_restart_at_full_adopts_the_plan_not_discharge(self):
        rt, coord, world = make_runtime(planner="learned")
        world.values["sensor.gauge"] = (100, "%")
        world.values["sensor.grid"] = (0, "W")
        run(rt, datetime(2026, 11, 23, 22, 0), 5)
        assert rt._commanded == MODE_HOLD
        assert EVENT_PRESERVE_START not in fired(coord)       # first tick adopts, does not act
