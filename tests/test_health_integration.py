"""0.8.1: health in the daily scoring, the notifications, the sensor and the runtime counters."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solarseed_peak_shaver.const import (
    CONF_LOAD_POWER_ENTITY,
    EVENT_CHARGE_START,
    SENSOR_HEALTH,
)
from custom_components.solarseed_peak_shaver.health import FAIR, GOOD, POOR
from tests.test_learned_runtime import fired, make_runtime, run
from tests.test_health import grid, summary

TODAY = datetime.now().strftime("%Y-%m-%d")


def day_record(grade, days_ago, err=None):
    date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    return {"date": date, "learned": {}, "health": {"date": date, "grade": grade, "reasons": [],
                                                      "peak_end_error_pts": err}}


def scoring_setup(learned_summary, history=(), snapshots=True, **overrides):
    rt, coord, world = make_runtime(planner="learned", **overrides)
    rt.daily_summary = lambda: dict(learned_summary)
    coord.store._data["days"] = list(history)
    coord.store.async_save = AsyncMock()
    coord.async_set_updated_data = MagicMock()
    coord._notify = MagicMock()
    coord.prediction_snapshots = [{"predicted_minimum_kwh": 2.0}] if snapshots else []
    coord.actual_soc_checkpoints = {"peak_end": 2.1}
    return rt, coord, world


def score(coord):
    asyncio.run(coord._async_score_daily_performance())


class TestScoring:
    def test_the_scorecard_gets_a_health_field_and_keeps_the_grade_fields(self):
        rt, coord, _ = scoring_setup(summary())
        score(coord)
        card = coord.last_daily_scorecard
        assert card["health"]["grade"] == GOOD
        assert card["health"]["date"] == TODAY
        assert "grade" in card and "score" in card and "learned" in card
        assert coord.store.days[-1] is card

    def test_the_daily_message_replaces_the_grade_message(self):
        rt, coord, _ = scoring_setup(summary())
        coord._send_daily_summary = MagicMock()
        score(coord)
        coord._send_daily_summary.assert_not_called()
        coord._notify.assert_called_once()
        title, body = coord._notify.call_args.args
        assert title == "Solarseed Daily Report - Good"
        assert body.startswith("peak on battery, ended at 12 % (predicted 9 %)")
        assert "Last 1 weekday: 1 good." in body
        title.encode("ascii")
        body.encode("ascii")

    def test_the_message_counts_the_last_seven_days(self):
        history = [day_record(GOOD, n) for n in range(6, 1, -1)] + [day_record(FAIR, 1)]
        rt, coord, _ = scoring_setup(summary(), history)
        score(coord)
        assert "Last 7 weekdays: 6 good, 1 fair." in coord._notify.call_args.args[1]

    def test_a_third_bad_day_in_a_row_sends_one_urgent_review_notice(self):
        history = [day_record(GOOD, 3), day_record(FAIR, 2), day_record(FAIR, 1)]
        rt, coord, _ = scoring_setup(summary(grid_kwh=grid(mid=1.0)), history)
        score(coord)
        assert coord._notify.call_count == 2
        assert coord._notify.call_args_list[0].kwargs.get("urgent") is None
        review = coord._notify.call_args_list[1]
        assert review.args[0] == "Solarseed - review needed"
        assert review.kwargs == {"urgent": True}
        assert coord.health_summary()["state"] == "review"

    def test_review_is_announced_only_when_it_starts(self):
        history = [day_record(POOR, 2), day_record(GOOD, 1)]           # already in review
        rt, coord, _ = scoring_setup(summary(), history)
        score(coord)
        assert coord._notify.call_count == 1
        assert coord.health_summary()["state"] == "review"

    def test_a_day_without_snapshots_is_still_graded_from_the_meters(self):
        rt, coord, _ = scoring_setup(summary(), snapshots=False)
        score(coord)
        card = coord.store.days[-1]
        assert card["health"]["grade"] == GOOD
        assert "grade" not in card                                    # no classic grade that day
        coord._notify.assert_called_once()

    def test_a_day_with_nothing_to_grade_sends_nothing(self):
        rt, coord, _ = scoring_setup({"grid_kwh": {}, "stale_longest_min": 5})
        score(coord)
        assert "health" not in coord.last_daily_scorecard
        coord._notify.assert_not_called()

    def test_without_the_power_sensors_the_old_grade_message_is_kept(self):
        rt, coord, _ = scoring_setup(summary(), **{CONF_LOAD_POWER_ENTITY: ""})
        coord._send_daily_summary = MagicMock()
        score(coord)
        assert "health" not in coord.last_daily_scorecard
        coord._send_daily_summary.assert_called_once()

    def test_the_old_grade_title_is_ascii(self):
        rt, coord, _ = scoring_setup(summary(), **{CONF_LOAD_POWER_ENTITY: ""})
        score(coord)
        coord._notify.call_args.args[0].encode("ascii")

    def test_a_grading_failure_never_breaks_the_scoring(self):
        rt, coord, _ = scoring_setup(summary())
        rt.daily_summary = MagicMock(side_effect=RuntimeError("boom"))
        score(coord)
        assert coord.last_daily_scorecard["grade"]
        assert "health" not in coord.last_daily_scorecard

    def test_weekends_are_not_scored(self):
        rt, coord, _ = scoring_setup(summary())
        coord.hass.async_create_task = MagicMock()
        coord._on_daily_scoring_time(datetime(2026, 11, 21, 21, 10))      # a Saturday
        coord.hass.async_create_task.assert_not_called()


class TestUrgentNotify:
    def coord(self):
        rt, coord, _ = make_runtime(notifications_enabled=True, notify_entity="notify.mobile_app_phone")
        return coord

    def test_urgent_asks_for_high_priority(self):
        coord = self.coord()
        coord.hass.services.async_call = AsyncMock()
        asyncio.run(coord._async_notify_urgent("notify", "mobile_app_phone", {"title": "t", "message": "m"}))
        domain, service, payload = coord.hass.services.async_call.call_args.args
        assert (domain, service) == ("notify", "mobile_app_phone")
        assert payload["data"]["priority"] == "high" and payload["data"]["ttl"] == 0

    def test_a_service_that_rejects_the_options_gets_the_plain_message(self):
        coord = self.coord()
        coord.hass.services.async_call = AsyncMock(side_effect=[ValueError("extra keys"), None])
        asyncio.run(coord._async_notify_urgent("notify", "x", {"title": "t", "message": "m"}))
        assert coord.hass.services.async_call.call_count == 2
        assert coord.hass.services.async_call.call_args.args[2] == {"title": "t", "message": "m"}

    def test_notify_routes_urgent_to_the_priority_path(self):
        coord = self.coord()
        coord.hass.async_create_task = MagicMock(side_effect=lambda c: c.close())
        coord.hass.services.async_call = MagicMock()
        coord._notify("t", "m", urgent=True)
        coord.hass.async_create_task.assert_called_once()
        coord.hass.services.async_call.assert_not_called()           # the priority path makes its own call


class TestHealthSensor:
    def sensor(self, coord):
        from custom_components.solarseed_peak_shaver.sensor import SENSOR_DESCRIPTIONS, PeakShaverSensor

        return PeakShaverSensor(coord, coord.entry, SENSOR_HEALTH, SENSOR_DESCRIPTIONS[SENSOR_HEALTH])

    def test_unknown_until_a_day_is_graded(self):
        rt, coord, _ = make_runtime()
        s = self.sensor(coord)
        assert s.native_value is None
        assert s.extra_state_attributes["days_graded"] == 0

    def test_state_and_the_last_seven_days_as_attributes(self):
        rt, coord, _ = make_runtime()
        coord.store._data["days"] = [day_record(GOOD, n) for n in range(9, 1, -1)] + [day_record(FAIR, 1)]
        s = self.sensor(coord)
        assert s.native_value == "watch"
        attrs = s.extra_state_attributes
        assert attrs["days_graded"] == 7
        assert attrs["counts"] == {GOOD: 6, FAIR: 1, POOR: 0}
        assert len(attrs["last_7_days"]) == 7
        assert attrs["last_7_days"][-1]["grade"] == FAIR
        assert attrs["review_reasons"] == []

    def test_it_is_registered_with_a_name(self):
        from custom_components.solarseed_peak_shaver.sensor import SENSOR_DESCRIPTIONS

        assert SENSOR_DESCRIPTIONS[SENSOR_HEALTH]["name"] == "Health"
        assert SENSOR_DESCRIPTIONS[SENSOR_HEALTH]["unit"] is None


class TestRuntimeCounters:
    """What the health grade needs from the minute loop."""

    def test_an_ignored_command_is_counted_in_the_daily_summary(self):
        rt, coord, world = make_runtime(planner="learned")
        coord._notify = MagicMock()
        world.values["sensor.grid"] = (600, "W")           # charge asked, nothing goes in
        run(rt, datetime(2026, 11, 16, 21, 0), 60)
        s = rt.daily_summary()
        assert s["commands_not_followed"] == 1
        assert s["command_retries"] == 3

    def test_an_obeyed_command_leaves_the_counters_at_zero(self):
        rt, coord, world = make_runtime(planner="learned")
        run(rt, datetime(2026, 11, 16, 20, 59), 1)
        world.values["sensor.grid"] = (2400, "W")
        run(rt, datetime(2026, 11, 16, 21, 0), 30)
        s = rt.daily_summary()
        assert s["commands_not_followed"] == 0 and s["command_retries"] == 0
        assert fired(coord).count(EVENT_CHARGE_START) == 1

    def test_the_longest_frozen_stretch_is_recorded(self):
        rt, coord, world = make_runtime(planner="classic")
        t = run(rt, datetime(2026, 11, 16, 10, 0), 5)
        world.frozen = True
        t = run(rt, t, 40)                                  # frozen from about 10:04; trips after 20 min
        world.frozen = False
        run(rt, t, 10)
        s = rt.daily_summary()
        assert 35 <= s["stale_longest_min"] <= 45           # counted from the last change, not from the trip
        assert s["stale_minutes"] > 0
