"""0.9.0: an event between the 21:10 scoring and midnight lands in a graded day.

Before, the day was scored at 21:10 and its counters were reset at midnight, so an ignored
command at 23:00 (the 2026-11-23 false alarm was one) fell in no graded day. Now what the
counters gain after the scoring is carried into the next graded day's summary, marked with
its date, and graded there. Today's own counters keep their meaning.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import MagicMock

from custom_components.solarseed_peak_shaver.health import FAIR, GOOD, POOR, daily_message, grade_day, status
from custom_components.solarseed_peak_shaver.learned_runtime import LearnedRuntime
from tests.test_health import summary
from tests.test_health_integration import score, scoring_setup
from tests.test_learned_runtime import fired, make_runtime, run

FRIDAY = "2026-11-27"           # the day after Thanksgiving: a TOU day


def friday_night_with_an_ignored_command_at_23():
    """Learned in control. The weekly top-up starts at 21:00 and the inverter charges; the
    day is scored at 21:10; at 23:00 the inverter stops following the charge command."""
    rt, coord, world = make_runtime(planner="learned")
    coord._notify = MagicMock()
    run(rt, datetime(2026, 11, 27, 20, 58), 2)
    world.values["sensor.grid"] = (2400, "W")
    run(rt, datetime(2026, 11, 27, 21, 0), 10)
    assert fired(coord)[-1:] == ["solarseed_peak_shaver_charge_start"]
    assert rt.daily_summary()["commands_not_followed"] == 0
    rt.mark_scored(FRIDAY, datetime(2026, 11, 27, 21, 10), True)      # the 21:10 scoring
    run(rt, datetime(2026, 11, 27, 21, 10), 110)
    world.values["sensor.grid"] = (600, "W")                         # grid only carries the house
    run(rt, datetime(2026, 11, 27, 23, 0), 65)                        # into Saturday 00:05
    return rt, coord, world


class TestCarry:
    def test_the_23_00_event_is_carried_with_its_date(self):
        rt, coord, world = friday_night_with_an_ignored_command_at_23()
        assert rt._late == [{"date": FRIDAY, "after": "21:10", "command_retries": 3,
                             "commands_not_followed": 1}]
        s = rt.daily_summary()                                        # Saturday's
        assert s["late_events"] == rt._late
        assert s["commands_not_followed"] == 0                        # today's own, unchanged

    def test_it_lands_in_mondays_grade_and_message(self):
        rt, coord, world = friday_night_with_an_ignored_command_at_23()
        world.values["sensor.grid"] = (0, "W")
        run(rt, datetime(2026, 11, 30, 20, 0), 5)                     # the weekend is not scored
        late = rt.daily_summary()["late_events"]
        assert [e["date"] for e in late] == [FRIDAY]
        day = grade_day({**summary(), "late_events": late}, "2026-11-30")
        assert day["grade"] == POOR
        assert "inverter ignored a command late on 11-27" in day["reasons"]
        assert day["commands_not_followed"] == 0                      # Monday's own count
        assert day["late_events"] == [{"date": FRIDAY, "after": "21:10", "commands_not_followed": 1,
                                       "frozen_longest_min": 0.0}]
        title, body = daily_message(day, status([day]))
        assert title == "Solarseed Daily Report - Poor"
        assert "inverter ignored a command late on 11-27" in body
        (title + body).encode("ascii")
        rt.mark_scored("2026-11-30", datetime(2026, 11, 30, 21, 10), True)
        assert rt._late == []                                         # graded once, not again

    def test_a_day_that_was_not_scored_carries_nothing(self):
        rt, coord, world = make_runtime(planner="learned")
        coord._notify = MagicMock()
        world.values["sensor.grid"] = (600, "W")
        run(rt, datetime(2026, 11, 16, 21, 0), 60)                    # not followed, no scoring
        assert rt.daily_summary()["commands_not_followed"] == 1
        run(rt, datetime(2026, 11, 16, 23, 58), 4)
        assert rt._late == []

    def test_nothing_after_the_scoring_carries_nothing(self):
        rt, coord, world = make_runtime(planner="learned")
        world.values["sensor.grid"] = (2400, "W")
        run(rt, datetime(2026, 11, 27, 21, 0), 10)
        rt.mark_scored(FRIDAY, datetime(2026, 11, 27, 21, 10), True)
        run(rt, datetime(2026, 11, 27, 21, 10), 180)
        assert rt._late == []
        assert "late_events" not in rt.daily_summary()

    def test_a_scoring_that_graded_nothing_keeps_them_for_the_next(self):
        rt, coord, world = friday_night_with_an_ignored_command_at_23()
        rt.mark_scored("2026-11-30", datetime(2026, 11, 30, 21, 10), False)
        assert len(rt._late) == 1

    def test_frozen_minutes_after_the_scoring(self):
        rt, coord, world = make_runtime()
        rt._late = []
        rt._carry_late(FRIDAY, {"stale_minutes": 50, "stale_longest_min": 80},
                       {"date": FRIDAY, "at": "21:10", "stale_minutes": 10, "stale_longest_min": 30})
        assert rt._late == [{"date": FRIDAY, "after": "21:10", "stale_minutes": 40.0, "stale_longest_min": 40.0}]

    def test_a_snapshot_of_another_day_is_ignored(self):
        rt, coord, world = make_runtime()
        rt._carry_late(FRIDAY, {"commands_not_followed": 1}, {"date": "2026-11-26", "commands_not_followed": 0})
        assert rt._late == []

    def test_at_most_two_weeks_are_kept(self):
        rt, coord, world = make_runtime()
        for n in range(20):
            rt._carry_late("2026-10-%02d" % (n + 1), {"command_retries": 1},
                           {"date": "2026-10-%02d" % (n + 1), "command_retries": 0})
        assert len(rt._late) == 14 and rt._late[-1]["date"] == "2026-10-20"


class TestRestart:
    def test_late_events_and_the_snapshot_are_saved(self):
        rt, coord, world = friday_night_with_an_ignored_command_at_23()
        blob = rt.dump_state()
        assert blob["late_events"] == rt._late
        assert "scored" in blob["day"]
        rt2 = LearnedRuntime(coord.hass, coord)
        rt2.load_state(blob)
        assert rt2._late == rt._late

    def test_down_over_midnight_after_a_scored_evening(self):
        # saved at 23:30 on a past Friday, loaded the next day: the evening still counts
        rt, coord, world = make_runtime(planner="learned")
        rt._day = datetime(2026, 11, 20).date()
        rt._shadow = {"command_retries": 3, "commands_not_followed": 1}
        rt._scored = {"date": "2026-11-20", "at": "21:10", "command_retries": 0, "commands_not_followed": 0}
        blob = rt.dump_state()
        rt2 = LearnedRuntime(coord.hass, coord)
        rt2.load_state(blob)
        assert rt2._late == [{"date": "2026-11-20", "after": "21:10", "command_retries": 3,
                              "commands_not_followed": 1}]
        assert rt2._scored is None

    def test_a_restart_the_same_evening_keeps_the_snapshot(self):
        rt, coord, world = make_runtime()
        today = datetime.now().strftime("%Y-%m-%d")
        scored = {"date": today, "at": "21:10", "command_retries": 0, "commands_not_followed": 0}
        rt.load_state({"day": {"date": today, "shadow": {}, "scored": scored}})
        assert rt._scored == scored

    def test_a_blob_from_0_8_loads(self):
        rt, coord, world = make_runtime()
        rt.load_state({"day": {"date": "2026-11-20", "shadow": {"commands_not_followed": 1}}})
        assert rt._late == [] and rt._scored is None


class TestScoringHandOff:
    def test_the_scoring_grades_late_events_and_marks_the_day(self):
        late = [{"date": FRIDAY, "after": "21:10", "commands_not_followed": 1}]
        rt, coord, _ = scoring_setup({**summary(), "late_events": late}, snapshots=False)
        rt._late = list(late)
        score(coord)
        card = coord.store.days[-1]
        assert card["health"]["grade"] == POOR
        assert card["health"]["late_events"][0]["date"] == FRIDAY
        assert "late on 11-27" in coord._notify.call_args_list[0].args[1]
        assert rt._late == []
        assert rt._scored is not None and rt._scored["date"] == card["date"]

    def test_the_classic_scoring_path_marks_the_day_too(self):
        rt, coord, _ = scoring_setup(summary(), snapshots=True)
        score(coord)
        assert rt._scored is not None

    def test_a_day_with_nothing_to_grade_keeps_the_late_events(self):
        late = [{"date": FRIDAY, "commands_not_followed": 1}]
        rt, coord, _ = scoring_setup({"grid_kwh": {}, "late_events": late}, snapshots=False)
        rt._late = list(late)
        score(coord)
        assert rt._late == late
        coord._notify.assert_not_called()

    def test_a_failing_runtime_never_breaks_the_scoring(self):
        rt, coord, _ = scoring_setup(summary())
        rt.mark_scored = MagicMock(side_effect=RuntimeError("boom"))
        score(coord)
        assert coord.store.days[-1]["health"]["grade"] == GOOD


class TestGrade:
    def test_late_frozen_data_is_graded_like_todays(self):
        fair = grade_day(summary(late_events=[{"date": FRIDAY, "stale_longest_min": 45}]), "2026-11-30")
        assert fair["grade"] == FAIR and "data frozen 45 min late on 11-27" in fair["reasons"]
        poor = grade_day(summary(late_events=[{"date": FRIDAY, "stale_longest_min": 70}]), "2026-11-30")
        assert poor["grade"] == POOR

    def test_retries_alone_do_not_change_the_grade(self):
        day = grade_day(summary(late_events=[{"date": FRIDAY, "command_retries": 2}]), "2026-11-30")
        assert day["grade"] == GOOD and day["reasons"] == []
        assert day["late_events"][0]["date"] == FRIDAY

    def test_a_day_without_late_events_has_the_same_record_as_before(self):
        assert "late_events" not in grade_day(summary(), "2026-11-30")

    def test_junk_is_ignored(self):
        day = grade_day(summary(late_events=["x", None, {"date": FRIDAY, "commands_not_followed": "bad"}]),
                        "2026-11-30")
        assert day["grade"] == GOOD

    def test_the_scoring_runs_asynchronously_as_before(self):
        rt, coord, _ = scoring_setup(summary())
        asyncio.run(coord._async_score_daily_performance())
        assert coord.store.days
