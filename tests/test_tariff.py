"""The tariff as data (0.9.1, ROADMAP item 8): PGE Time of Day reproduced exactly, the
three legacy hour keys, seasons, typed holiday rules, the shape refusal, and dollars from
the tariff (HA mocked; runs without voluptuous)."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solarseed_peak_shaver import async_options_updated
from custom_components.solarseed_peak_shaver.const import (
    CONF_HOLIDAY_DATES,
    CONF_HOLIDAY_PRESET,
    CONF_HOLIDAY_RULES,
    CONF_MIDPEAK_PRICE,
    CONF_MIDPEAK_START,
    CONF_OFFPEAK_PRICE,
    CONF_PEAK_END,
    CONF_PEAK_PRICE,
    CONF_PEAK_START,
    CONF_TARIFF_SEASONS,
    CONF_WEEKDAYS_ONLY,
    EVENT_CHARGE_START,
    SENSOR_LEARNED_PLAN,
)
from custom_components.solarseed_peak_shaver.health import daily_message, grade_day
from custom_components.solarseed_peak_shaver.holidays import (
    PGE,
    US_FEDERAL,
    format_rules,
    holidays_in_year,
    is_tou_day,
    parse_dates,
    parse_rules,
    preset_rules_text,
)
from custom_components.solarseed_peak_shaver.options import check_tariff
from custom_components.solarseed_peak_shaver.planner import MODE_CHARGE
from custom_components.solarseed_peak_shaver.tariff import (
    PGE_TIME_OF_DAY,
    TARIFF_CUSTOM,
    Windows,
    build_tariff,
    parse_seasons,
    price_problem,
)
from tests.test_learned_runtime import fired, make_runtime, run
from tests.test_options import OLD_FLAT_FORM_OPTIONS, coordinator_with, make_select
from tests.test_planner import trained

# --- 0.9.0, frozen: what the code did before the tariff was data -----------------------------
# learned_runtime.tick: `c._classify_period(now) if c.is_tou_day(now.date()) else "off-peak"`
# with the hours 7 / 17 / 21, weekdays only, the PGE holidays; health.py priced mid-peak at
# 0.1670 and peak at 0.4313 and never priced off-peak.
PGE_090_HOLIDAYS = {date(2026, 11, 26), date(2027, 7, 5), date(2027, 12, 31)}
PRICE_090 = {"mid-peak": 0.1670, "peak": 0.4313}


def period_090(when: datetime) -> str:
    d = when.date()
    if d.weekday() >= 5 or d in PGE_090_HOLIDAYS:
        return "off-peak"
    if when.hour < 7 or when.hour >= 21:
        return "off-peak"
    return "mid-peak" if when.hour < 17 else "peak"


SAMPLE_WEEKS = [date(2026, 11, 23), date(2027, 7, 4), date(2027, 12, 27)]   # Thanksgiving, Jul 5, Dec 31


def every_hour():
    for start in SAMPLE_WEEKS:
        t = datetime.combine(start, datetime.min.time())
        for _ in range(7 * 24):
            yield t
            t += timedelta(hours=1)


class TestPgeIsExactly090:
    @pytest.mark.parametrize("source", ["preset", "absent keys", "0.8 flat form", "three hour keys only"])
    def test_period_and_price_for_every_hour_of_three_weeks(self, source):
        if source == "preset":
            tariff = PGE_TIME_OF_DAY
        else:
            rt, coord, _ = make_runtime(planner="classic")
            if source == "0.8 flat form":
                coord.entry.options = dict(OLD_FLAT_FORM_OPTIONS)
            elif source == "three hour keys only":
                coord.entry.data = {CONF_MIDPEAK_START: 7, CONF_PEAK_START: 17, CONF_PEAK_END: 21}
            tariff = coord.tariff
            assert tariff is PGE_TIME_OF_DAY
        hours = 0
        for when in every_hour():
            old = period_090(when)
            assert tariff.period_at(when) == old, when
            assert tariff.price_at(when) == PRICE_090.get(old), when
            hours += 1
        assert hours == 3 * 7 * 24

    def test_the_coordinator_reads_the_same_hours_and_periods(self):
        rt, coord, _ = make_runtime(planner="classic")
        for when in every_hour():
            assert coord.period_at(when) == period_090(when)
            assert coord.is_tou_day(when.date()) == (period_090(when.replace(hour=12)) != "off-peak")
        assert (coord.midpeak_start, coord.peak_start, coord.peak_end) == (7, 17, 21)

    def test_the_daily_dollars_are_the_same(self):
        rt, coord, _ = make_runtime(planner="classic")
        summary = {"grid_kwh": {"off-peak": 3.9, "mid-peak": 1.98, "peak": 0.63}, "gauge_peak_end": 12,
                   "pred_gauge_peak_end": 9}
        old = grade_day(summary, "2026-11-24")                         # the 0.9.0 call
        new = grade_day(summary, "2026-11-24", coord.tariff.prices_on(date(2026, 11, 24)))
        assert new["cost_usd"] == old["cost_usd"] == round(1.98 * 0.1670 + 0.63 * 0.4313, 2)
        assert daily_message(new, {}) == daily_message(old, {})
        assert new["prices"] == {"mid-peak": 0.1670, "peak": 0.4313}

    def test_the_preset_is_named(self):
        rt, coord, _ = make_runtime(planner="classic")
        assert coord.tariff.name == "PGE Time of Day"
        coord.entry.options = {CONF_PEAK_PRICE: 0.45}
        assert coord.tariff.name == TARIFF_CUSTOM


class TestLegacyHourKeys:
    def test_other_hours_in_the_three_keys_still_rule(self):
        rt, coord, _ = make_runtime(planner="classic", **{CONF_MIDPEAK_START: 8, CONF_PEAK_START: 16,
                                                          CONF_PEAK_END: 20})
        t = coord.tariff
        assert t.windows == Windows(8, 16, 20)
        assert t.prices_on(date(2026, 11, 24))["peak"] == 0.4313
        assert coord.period_at(datetime(2026, 11, 24, 7, 30)) == "off-peak"
        assert coord.period_at(datetime(2026, 11, 24, 16, 0)) == "peak"
        assert coord.period_at(datetime(2026, 11, 24, 20, 0)) == "off-peak"
        assert rt._inputs(datetime(2026, 11, 24, 12, 0), 50.0).peak_start == 16

    def test_the_timers_use_the_three_keys(self):
        rt, coord, _ = make_runtime(planner="classic", **{CONF_PEAK_END: 22})
        with patch("custom_components.solarseed_peak_shaver.coordinator.async_track_time_change") as track:
            coord.setup_listeners()
        scoring = [c.kwargs["hour"] for c in track.call_args_list if c.args[1] == coord._on_daily_scoring_time]
        assert scoring == [22]


# --- seasons ----------------------------------------------------------------------------------

SUMMER = "Summer 06-09: mid-peak 7-15, peak 15-20 0.52, mid-peak 0.20"


class TestSeasons:
    def test_a_season_changes_hours_and_prices_in_its_months(self):
        t = build_tariff(7, 17, 21, True, None, 0.167, 0.4313, SUMMER, PGE)
        assert t.windows_on(date(2026, 7, 15)) == Windows(7, 15, 20)
        assert t.windows_on(date(2026, 11, 24)) == Windows(7, 17, 21)
        assert t.prices_on(date(2026, 7, 15)) == {"off-peak": None, "mid-peak": 0.20, "peak": 0.52}
        assert t.period_at(datetime(2026, 7, 15, 15, 30)) == "peak"
        assert t.period_at(datetime(2026, 11, 24, 15, 30)) == "mid-peak"
        assert t.season_on(date(2026, 7, 15)).name == "Summer"
        assert t.all_windows() == (Windows(7, 15, 20), Windows(7, 17, 21))

    def test_prices_only_keeps_the_hours_and_months_wrap_the_year(self):
        seasons, errors = parse_seasons("11-02: peak 0.50; 06: off-peak 0.05")
        assert errors == []
        assert seasons[0].months == (11, 12, 1, 2) and seasons[0].windows is None
        assert seasons[1].months == (6,)
        t = build_tariff(7, 17, 21, True, None, 0.167, 0.4313, "11-02: peak 0.50", PGE)
        assert t.windows_on(date(2027, 1, 5)) == Windows(7, 17, 21)
        assert t.prices_on(date(2027, 1, 5))["peak"] == 0.50

    @pytest.mark.parametrize("text,words", [
        ("06-09: peak 7-11, peak 17-21", "two peak windows"),
        ("06-09: mid-peak 7-12, peak 17-21", "must end when peak starts"),
        ("06-09: peak 7-12, mid-peak 12-17", "must end when peak starts"),
        ("06-09: peak 22-2", "across midnight"),
        ("06-09: off-peak 0-7", "off-peak is every hour"),
        ("06-09: mid-peak 7-15", "need peak hours"),
        ("06-09: peak 0.10", "prices must rise"),
        ("06-09 peak 15-20", "start with the months"),
        ("13: peak 15-20", "months are 01 to 12"),
        ("06-09: peak 15-20; 09-10: peak 16-21", "already in"),
        ("06-09: shoulder 15-20", "not understood"),
    ])
    def test_a_tariff_that_does_not_fit_is_refused_plainly(self, text, words):
        seasons, errors = parse_seasons(text, {"off-peak": None, "mid-peak": 0.167, "peak": 0.4313},
                                        Windows(7, 17, 21))
        assert errors and words in errors[0], errors
        if "already in" not in words:
            assert seasons == ()

    def test_a_bad_stored_season_falls_back_to_the_base(self):
        t = build_tariff(7, 17, 21, True, None, 0.167, 0.4313, "06-09: peak 7-11, peak 17-21", PGE)
        assert t.seasons == () and t.windows_on(date(2026, 7, 1)) == Windows(7, 17, 21)

    def test_through_the_runtime_in_july_and_november(self):
        rt, coord, world = make_runtime(planner="learned", **{CONF_TARIFF_SEASONS: SUMMER})
        world.values["sensor.gauge"] = (60, "%")
        world.values["sensor.grid"] = (300, "W")
        run(rt, datetime(2026, 7, 15, 15, 30), 20)                  # Wednesday, summer peak
        assert rt.decision.phase == "peak"
        assert rt.daily_summary()["grid_kwh"]["peak"] > 0
        run(rt, datetime(2026, 11, 18, 15, 30), 20)                 # Wednesday, base hours
        assert rt.decision.phase == "mid-peak"
        # the July day is graded at July's prices
        record = coord._grade_health("2026-07-15", {"grid_kwh": {"peak": 1.0, "mid-peak": 1.0}})
        assert record["cost_usd"] == round(0.20 + 0.52, 2)

    def test_the_timers_cover_every_season_and_act_on_the_days_own(self):
        rt, coord, _ = make_runtime(planner="classic", **{CONF_TARIFF_SEASONS: SUMMER})
        with patch("custom_components.solarseed_peak_shaver.coordinator.async_track_time_change") as track:
            coord.setup_listeners()
        scoring = sorted(c.kwargs["hour"] for c in track.call_args_list
                         if c.args[1] == coord._on_daily_scoring_time)
        assert scoring == [20, 21]
        coord.hass.async_create_task = MagicMock()
        coord._on_daily_scoring_time(datetime(2026, 7, 15, 21, 10))     # not July's peak end
        coord.hass.async_create_task.assert_not_called()
        coord._on_daily_scoring_time(datetime(2026, 7, 15, 20, 10))
        coord.hass.async_create_task.assert_called_once()
        coord.hass.async_create_task.reset_mock()
        coord._on_daily_scoring_time(datetime(2026, 11, 18, 20, 10))    # not November's
        coord.hass.async_create_task.assert_not_called()
        coord._on_daily_scoring_time(datetime(2026, 11, 18, 21, 10))
        coord.hass.async_create_task.assert_called_once()

    def test_a_season_hour_change_reloads_a_price_change_does_not(self):
        rt, coord, _ = coordinator_with({CONF_TARIFF_SEASONS: SUMMER})
        coord.entry.options = {CONF_TARIFF_SEASONS: SUMMER.replace("0.52", "0.60"), CONF_PEAK_PRICE: 0.5,
                               CONF_HOLIDAY_PRESET: "us_federal"}
        asyncio.run(async_options_updated(coord.hass, coord.entry))
        coord.hass.config_entries.async_reload.assert_not_awaited()
        coord.entry.options = {CONF_TARIFF_SEASONS: SUMMER.replace("15-20", "16-21").replace("7-15", "7-16")}
        asyncio.run(async_options_updated(coord.hass, coord.entry))
        coord.hass.config_entries.async_reload.assert_awaited_once()


class TestPrices:
    def test_rising_prices_pass(self):
        assert price_problem({"off-peak": 0.09, "mid-peak": 0.17, "peak": 0.43}) is None
        assert price_problem({"off-peak": None, "mid-peak": 0.17, "peak": 0.17}) is None

    def test_mid_above_peak_is_refused(self):
        assert "prices must rise" in price_problem({"mid-peak": 0.5, "peak": 0.43})

    def test_mid_does_not_count_without_a_midpeak_window(self):
        assert price_problem({"off-peak": 0.1, "mid-peak": 0.5, "peak": 0.43}, has_midpeak=False) is None


class TestTwoPricePlan:
    """Mid-peak start = peak start: a plan with only off-peak and peak (16-21 every day)."""

    def test_no_midpeak_phase_and_the_night_charge_ends_at_peak_start(self):
        rt, coord, world = make_runtime(planner="learned", **{CONF_MIDPEAK_START: 16, CONF_PEAK_START: 16,
                                                              CONF_PEAK_END: 21, CONF_WEEKDAYS_ONLY: False,
                                                              CONF_HOLIDAY_PRESET: "none"})
        world.values["sensor.gauge"] = (30, "%")
        run(rt, datetime(2026, 11, 21, 21, 30), 2)                   # Saturday night: TOU every day
        assert rt.decision.phase == "night" and "16:00" in rt.decision.reason
        assert fired(coord)[-1] == EVENT_CHARGE_START
        phases = set()
        run(rt, datetime(2026, 11, 22, 12, 0), 8 * 60, step=lambda i, t: phases.add(rt.decision.phase if rt.decision else None))
        assert "mid-peak" not in phases
        assert rt.decision.phase == "peak"
        assert rt.daily_summary().get("gauge_peak_start") is not None


# --- holidays as typed rules ------------------------------------------------------------------


class TestHolidayRules:
    def test_the_presets_round_trip_through_their_text(self):
        for cal in (PGE, US_FEDERAL):
            parsed, errors = parse_rules(format_rules(cal))
            assert errors == []
            assert parsed == cal

    def test_the_example_rules(self):
        cal, errors = parse_rules("01-01, 11-thu-4, 05-mon-last, sat->fri, sun->mon")
        assert errors == []
        assert sorted(holidays_in_year(2026, cal)) == [date(2026, 1, 1), date(2026, 5, 25), date(2026, 11, 26)]
        assert sorted(holidays_in_year(2027, cal))[-1] == date(2027, 12, 31)   # 2028-01-01 is a Saturday

    def test_us_federal_2026(self):
        assert sorted(holidays_in_year(2026, "us_federal")) == [
            date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 5, 25), date(2026, 6, 19),
            date(2026, 7, 3), date(2026, 9, 7), date(2026, 10, 12), date(2026, 11, 11), date(2026, 11, 26),
            date(2026, 12, 25)]

    @pytest.mark.parametrize("text,words", [
        ("13-01", "no such month"), ("02-30", "no such month"), ("11-xyz-4", "the day must be"),
        ("11-thu-6", "1 to 5 or last"), ("2026-12-24", "one-off holidays field"), ("christmas", "not a holiday rule"),
        ("sat->sun", "a shift moves"),
    ])
    def test_bad_rules_say_why_and_keep_the_good_ones(self, text, words):
        cal, errors = parse_rules("12-25 Christmas, " + text)
        assert len(errors) == 1 and words in errors[0], errors
        assert [r.name for r in cal.rules] == ["Christmas"]

    def test_one_off_dates(self):
        dates, errors = parse_dates("2026-12-24 Christmas Eve, 2027-01-02")
        assert errors == [] and dates == ((date(2026, 12, 24), "Christmas Eve"), (date(2027, 1, 2), "Holiday"))
        assert parse_dates("12-24")[1]
        assert parse_dates("2026-02-30")[1]

    def test_the_coordinator_reads_custom_rules_and_one_off_dates(self):
        rt, coord, _ = make_runtime(planner="classic", **{CONF_HOLIDAY_PRESET: "custom",
                                                          CONF_HOLIDAY_RULES: "11-fri-4 Day after Thanksgiving",
                                                          CONF_HOLIDAY_DATES: "2026-12-24 Christmas Eve"})
        assert not coord.is_tou_day(date(2026, 11, 27))
        assert coord.is_tou_day(date(2026, 11, 26))                  # custom: Thanksgiving not listed
        assert not coord.is_tou_day(date(2026, 12, 24))
        coord.entry.options = {CONF_HOLIDAY_PRESET: "pge", CONF_HOLIDAY_DATES: "2026-12-24"}
        assert not coord.is_tou_day(date(2026, 11, 26)) and not coord.is_tou_day(date(2026, 12, 24))
        assert coord.is_tou_day(date(2026, 11, 27))

    def test_custom_with_no_rules_has_only_the_dates(self):
        rt, coord, _ = make_runtime(planner="classic", **{CONF_HOLIDAY_PRESET: "custom"})
        assert coord.is_tou_day(date(2026, 11, 26))

    def test_the_device_page_select_offers_the_new_presets(self):
        rt, coord, _ = coordinator_with(OLD_FLAT_FORM_OPTIONS)
        ent = make_select(coord, CONF_HOLIDAY_PRESET)
        assert ent._attr_options == ["none", "pge", "us_federal", "custom"]
        asyncio.run(ent.async_select_option("us_federal"))
        assert coord.entry.options == {**OLD_FLAT_FORM_OPTIONS, CONF_HOLIDAY_PRESET: "us_federal"}
        assert not coord.is_tou_day(date(2026, 11, 11))              # Veterans Day
        asyncio.run(async_options_updated(coord.hass, coord.entry))
        coord.hass.config_entries.async_reload.assert_not_awaited()


# --- the Tariff form (the pure half; test_config_flow.py drives the real form) ---------------

PREVIOUS = {CONF_MIDPEAK_START: 7, CONF_PEAK_START: 17, CONF_PEAK_END: 21, CONF_HOLIDAY_PRESET: "pge"}


def submit(**typed):
    form = {CONF_MIDPEAK_START: 7, CONF_PEAK_START: 17, CONF_PEAK_END: 21, CONF_WEEKDAYS_ONLY: True,
            CONF_MIDPEAK_PRICE: 0.167, CONF_PEAK_PRICE: 0.4313, CONF_HOLIDAY_PRESET: "pge",
            CONF_HOLIDAY_RULES: preset_rules_text("pge")}
    form.update(typed)
    return check_tariff(PREVIOUS, form)


class TestTariffForm:
    def test_the_shown_values_save_unchanged(self):
        data, errors, _ = submit()
        assert errors == {}
        assert data[CONF_HOLIDAY_PRESET] == "pge"

    def test_choosing_a_preset_fills_the_rules(self):
        data, errors, _ = submit(**{CONF_HOLIDAY_PRESET: "us_federal"})
        assert errors == {}
        assert data[CONF_HOLIDAY_RULES] == preset_rules_text("us_federal")
        assert "11-11 Veterans Day" in data[CONF_HOLIDAY_RULES]
        data, _, _ = submit(**{CONF_HOLIDAY_PRESET: "none"})
        assert data[CONF_HOLIDAY_RULES] == ""

    def test_editing_the_rules_makes_it_custom(self):
        data, errors, _ = submit(**{CONF_HOLIDAY_RULES: preset_rules_text("pge") + "\n11-fri-4 Day after"})
        assert errors == {}
        assert data[CONF_HOLIDAY_PRESET] == "custom"
        assert "11-fri-4 Day after" in data[CONF_HOLIDAY_RULES]

    def test_bad_custom_rules_are_refused_with_the_reason(self):
        data, errors, detail = submit(**{CONF_HOLIDAY_PRESET: "custom", CONF_HOLIDAY_RULES: "11-thu-9"})
        assert errors == {CONF_HOLIDAY_RULES: "invalid_holiday_rules"}
        assert "1 to 5 or last" in detail["rules_detail"]

    def test_two_peak_windows_are_refused_with_the_reason(self):
        data, errors, detail = submit(**{CONF_TARIFF_SEASONS: "06-09: peak 7-11, peak 17-21"})
        assert errors == {CONF_TARIFF_SEASONS: "invalid_seasons"}
        assert "two peak windows" in detail["seasons_detail"]

    def test_prices_that_do_not_rise_are_refused(self):
        data, errors, detail = submit(**{CONF_MIDPEAK_PRICE: 0.5, CONF_PEAK_PRICE: 0.4})
        assert errors == {CONF_PEAK_PRICE: "invalid_prices"}
        assert "rise" in detail["prices_detail"]
        data, errors, _ = submit(**{CONF_OFFPEAK_PRICE: 0.2, CONF_MIDPEAK_PRICE: 0.1})
        assert errors == {CONF_PEAK_PRICE: "invalid_prices"}

    def test_hours_out_of_order_and_a_two_price_plan(self):
        _, errors, _ = submit(**{CONF_MIDPEAK_START: 18})
        assert errors == {CONF_PEAK_START: "invalid_time_range"}
        _, errors, _ = submit(**{CONF_PEAK_END: 17})
        assert errors == {CONF_PEAK_END: "invalid_time_range"}
        _, errors, _ = submit(**{CONF_MIDPEAK_START: 16, CONF_PEAK_START: 16, CONF_MIDPEAK_PRICE: 0.9})
        assert errors == {}                                          # no mid-peak: its price does not count

    def test_bad_one_off_dates_are_refused(self):
        _, errors, detail = submit(**{CONF_HOLIDAY_DATES: "12/24"})
        assert errors == {CONF_HOLIDAY_DATES: "invalid_holiday_dates"}
        assert "not a date" in detail["dates_detail"]


# --- the plan sensor --------------------------------------------------------------------------


class TestPlanSensorDollars:
    def test_tariff_and_dollars_on_the_plan_sensor(self):
        from custom_components.solarseed_peak_shaver.sensor import PeakShaverSensor

        rt, coord, world = make_runtime(planner="learned")
        world.values["sensor.gauge"] = (20, "%")
        run(rt, datetime(2026, 11, 18, 12, 0), 2)
        coord.data = {}
        coord._now = lambda: datetime(2026, 11, 18, 12, 1)
        sensor = PeakShaverSensor.__new__(PeakShaverSensor)
        sensor.coordinator = coord
        sensor._sensor_key = SENSOR_LEARNED_PLAN
        attrs = sensor.extra_state_attributes
        assert attrs["tariff"] == "PGE Time of Day"
        assert attrs["price_period"] == "mid-peak" and attrs["price_now"] == 0.1670
        assert attrs["prices"] == {"off-peak": None, "mid-peak": 0.1670, "peak": 0.4313}
        assert attrs["price_windows"] == "07-17 mid-peak, 17-21 peak"
        d = rt.decision
        assert attrs["handover_cost_usd"] == round(d.handover_kwh * 0.4313, 2)
        if d.shortfall_kwh is not None and d.shortfall_kwh > 0:
            assert attrs["shortfall_cost_usd"] == round(d.shortfall_kwh * 0.4313, 2)
        assert attrs["holiday_preset"] == "pge"

    def test_the_dollars_follow_a_changed_peak_price(self):
        from custom_components.solarseed_peak_shaver.tariff import cost_attributes

        t = build_tariff(7, 17, 21, True, 0.09, 0.2, 0.5, "", PGE)
        out = cost_attributes(t, datetime(2026, 11, 21, 12, 0), 1.0, 2.0)   # a Saturday
        assert out["price_period"] == "off-peak" and out["price_now"] == 0.09
        assert out["handover_cost_usd"] == 0.5 and out["shortfall_cost_usd"] == 1.0
        assert out["price_windows"] == "off-peak all day"
        assert cost_attributes(t, datetime(2026, 11, 20, 12, 0), 1.0, -1.0)["shortfall_cost_usd"] is None


def test_holiday_tou_rule_is_unchanged_for_old_callers():
    # holidays.is_tou_day with a preset name, as 0.8.2 and the replay script call it
    assert not is_tou_day(date(2026, 11, 26), True, "pge")
    assert is_tou_day(date(2026, 11, 26), True)
    assert MODE_CHARGE == "charge"


# --- review: the night after peak end plans for tomorrow with tomorrow's hours ----------------

LATE_SUMMER = "06-09: mid-peak 9-15, peak 15-20"        # other mid-peak start than the base 7


class TestSeasonBoundaryNight:
    def test_the_last_summer_evening_plans_for_the_first_base_day(self):
        rt, coord, world = make_runtime(planner="learned", **{CONF_TARIFF_SEASONS: LATE_SUMMER})
        rt.learner, rt.profile = trained()
        world.values["sensor.gauge"] = (20, "%")
        # Tuesday 2026-09-29 evening: tomorrow is still summer, mid-peak from 09:00
        run(rt, datetime(2026, 9, 29, 20, 30), 2)
        assert rt.decision.phase == "night" and "09:00" in rt.decision.reason
        need_summer = rt.decision.need_kwh
        # Wednesday 2026-09-30 evening: tomorrow is October, mid-peak from 07:00, 07-21
        run(rt, datetime(2026, 9, 30, 20, 30), 2)
        assert rt.decision.phase == "night" and "07:00" in rt.decision.reason
        assert rt.decision.need_kwh > need_summer                    # a longer window needs more
        # the planner inputs say so too
        inp = rt._inputs(datetime(2026, 9, 30, 20, 30), 20.0)
        assert (inp.midpeak_start, inp.peak_end) == (9, 20)          # today's, for today's rules
        assert (inp.next_midpeak_start, inp.next_peak_end) == (7, 21)
        # before mid-peak start on the day itself, today's hours rule as before
        run(rt, datetime(2026, 10, 1, 5, 0), 2)
        assert rt.decision.phase == "night" and "07:00" in rt.decision.reason

    def test_the_full_month_hold_names_tomorrows_hour(self):
        rt, coord, world = make_runtime(planner="learned", **{CONF_TARIFF_SEASONS: "10: mid-peak 9-15, peak 15-20",
                                                              CONF_WEEKDAYS_ONLY: False,
                                                              CONF_HOLIDAY_PRESET: "none"})
        world.values["sensor.gauge"] = (100, "%")
        world.values["sensor.grid"] = (600, "W")
        run(rt, datetime(2026, 10, 31, 21, 0), 3)                   # Saturday; tomorrow November
        assert rt.decision.phase == "night" and "until 07:00" in rt.decision.reason

    def test_pge_is_untouched(self):
        rt, coord, _ = make_runtime(planner="learned")
        inp = rt._inputs(datetime(2026, 11, 24, 22, 0), 50.0)
        assert (inp.next_midpeak_start, inp.next_peak_end) == (7, 21) == (inp.midpeak_start, inp.peak_end)


# --- review: the weekend's own hours and prices (day types weekday, weekend, holiday) ----------

WEEKEND_LINE = "weekend: peak 16-21 0.30"


class TestWeekendOwnHoursAndPrices:
    def test_parsed_as_a_season_with_no_months(self):
        seasons, errors = parse_seasons(WEEKEND_LINE, {"off-peak": None, "mid-peak": 0.167, "peak": 0.4313},
                                        Windows(7, 17, 21))
        assert errors == []
        assert seasons[0].name == "weekend" and seasons[0].months == ()
        assert seasons[0].windows == Windows(16, 16, 21) and seasons[0].prices == (("peak", 0.30),)

    def test_weekend_days_use_their_own_when_the_windows_apply_every_day(self):
        t = build_tariff(7, 17, 21, False, None, 0.167, 0.4313, WEEKEND_LINE, PGE)
        sat, fri = date(2026, 11, 21), date(2026, 11, 20)
        assert t.windows_on(sat) == Windows(16, 16, 21) and t.windows_on(fri) == Windows(7, 17, 21)
        assert t.prices_on(sat)["peak"] == 0.30 and t.prices_on(fri)["peak"] == 0.4313
        assert t.prices_on(sat)["mid-peak"] == 0.167                 # not given: the weekday's
        assert t.period_at(datetime(2026, 11, 21, 12, 0)) == "off-peak"
        assert t.period_at(datetime(2026, 11, 21, 17, 0)) == "peak"
        assert t.period_at(datetime(2026, 11, 20, 12, 0)) == "mid-peak"
        assert t.all_windows() == (Windows(7, 17, 21), Windows(16, 16, 21))
        assert t.describe(sat)["season"] == "weekend" and t.describe(fri)["season"] is None
        assert t.describe(sat)["price_windows"] == "16-21 peak"
        assert not t.is_tou_day(date(2026, 11, 26))                 # a holiday is still off-peak all day

    def test_weekdays_only_leaves_the_weekend_off_peak(self):
        t = build_tariff(7, 17, 21, True, None, 0.167, 0.4313, WEEKEND_LINE, PGE)
        assert t.windows_on(date(2026, 11, 21)) == Windows(7, 17, 21)
        assert t.period_at(datetime(2026, 11, 21, 17, 0)) == "off-peak"
        assert t.describe(date(2026, 11, 21))["season"] is None

    def test_with_a_season_the_weekend_prices_sit_on_top(self):
        t = build_tariff(7, 17, 21, False, None, 0.167, 0.4313, SUMMER + "\nweekend: peak 0.30", PGE)
        sat_july = date(2026, 7, 18)
        assert t.windows_on(sat_july) == Windows(7, 15, 20)        # the season's hours
        assert t.prices_on(sat_july) == {"off-peak": None, "mid-peak": 0.20, "peak": 0.30}
        assert t.describe(sat_july)["season"] == "Summer, weekend"

    @pytest.mark.parametrize("text,words", [
        ("weekend: peak 16-21; weekend: peak 0.3", "given twice"),
        ("weekend:", "hours, a price or both"),
        ("weekend: peak 0.10", "prices must rise"),
    ])
    def test_bad_weekend_lines_say_why(self, text, words):
        _, errors = parse_seasons(text, {"off-peak": None, "mid-peak": 0.167, "peak": 0.4313}, Windows(7, 17, 21))
        assert errors and words in errors[-1], errors

    def test_the_form_wants_weekdays_only_off(self):
        _, errors, detail = submit(**{CONF_TARIFF_SEASONS: WEEKEND_LINE, CONF_WEEKDAYS_ONLY: True})
        assert errors == {CONF_TARIFF_SEASONS: "invalid_seasons"}
        assert "Weekdays only" in detail["seasons_detail"]
        data, errors, _ = submit(**{CONF_TARIFF_SEASONS: WEEKEND_LINE, CONF_WEEKDAYS_ONLY: False})
        assert errors == {} and data[CONF_TARIFF_SEASONS] == WEEKEND_LINE

    def test_through_the_runtime_friday_night_plans_for_saturdays_hours(self):
        rt, coord, world = make_runtime(planner="learned", **{CONF_TARIFF_SEASONS: WEEKEND_LINE,
                                                              CONF_WEEKDAYS_ONLY: False,
                                                              CONF_HOLIDAY_PRESET: "none"})
        world.values["sensor.gauge"] = (30, "%")
        run(rt, datetime(2026, 11, 20, 21, 30), 2)                  # Friday night, November
        assert rt.decision.phase == "night" and "until 16:00" in rt.decision.reason
        assert fired(coord)[-1] == EVENT_CHARGE_START
        world.values["sensor.grid"] = (300, "W")
        run(rt, datetime(2026, 11, 21, 17, 0), 5)                   # Saturday, the weekend's peak
        assert rt.decision.phase == "peak"
        assert rt.daily_summary()["grid_kwh"].get("peak", 0) > 0
        assert "mid-peak" not in rt.daily_summary()["grid_kwh"]
        record = coord._grade_health("2026-11-21", {"grid_kwh": {"peak": 1.0}})
        assert record["cost_usd"] == 0.30                           # Saturday's peak price
        with patch("custom_components.solarseed_peak_shaver.coordinator.async_track_time_change") as track:
            coord.setup_listeners()
        ckpt = sorted(c.kwargs["hour"] for c in track.call_args_list if c.args[1] == coord._on_soc_checkpoint)
        assert ckpt == [7, 16, 17, 21]


class TestPeakEndByEleven:
    def test_peak_end_24_is_refused_in_the_form(self):
        # 24 would put the scoring and the peak-end checkpoint at 00:xx on the next date
        _, errors, _ = submit(**{CONF_PEAK_END: 24})
        assert errors == {CONF_PEAK_END: "invalid_time_range"}
        _, errors, _ = submit(**{CONF_PEAK_END: 23})
        assert errors == {}
