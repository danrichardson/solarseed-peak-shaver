"""0.8.1: the daily health check, graded from what the meters saw (pure functions)."""
from __future__ import annotations

import pytest

from custom_components.solarseed_peak_shaver.health import (
    FAIR,
    GOOD,
    HEALTH_GOOD,
    HEALTH_REVIEW,
    HEALTH_WATCH,
    POOR,
    daily_message,
    grade_day,
    review_message,
    status,
)


def summary(**over):
    """A learned-runtime daily summary of a clean day."""
    base = {
        "grid_kwh": {"off-peak": 14.2, "mid-peak": 0.0, "peak": 0.0},
        "gauge_peak_end": 12.0,
        "pred_gauge_peak_end": 9.0,
        "stale_minutes": 0,
        "stale_longest_min": 0,
        "commands_not_followed": 0,
    }
    base.update(over)
    return base


def grid(mid=0.0, peak=0.0):
    return {"off-peak": 14.2, "mid-peak": mid, "peak": peak}


def rec(grade, date="2026-11-17", err=None):
    return {"date": date, "grade": grade, "peak_end_error_pts": err}


class TestGradeDay:
    def test_a_clean_day_is_good(self):
        day = grade_day(summary(), "2026-11-17")
        assert day["grade"] == GOOD
        assert day["reasons"] == []
        assert day["peak_covered"] is True
        assert day["cost_usd"] == 0.0
        assert day["peak_end_error_pts"] == pytest.approx(-3.0)      # predicted 9, actual 12

    def test_error_is_predicted_minus_actual(self):
        day = grade_day(summary(gauge_peak_end=5.0, pred_gauge_peak_end=12.0), "d")
        assert day["peak_end_error_pts"] == pytest.approx(7.0)         # optimistic: positive

    @pytest.mark.parametrize("peak", [0.21, 0.5, 3.0])
    def test_more_than_0_2_kwh_in_peak_is_poor(self, peak):
        day = grade_day(summary(grid_kwh=grid(peak=peak)), "d")
        assert day["grade"] == POOR
        assert day["peak_covered"] is False

    def test_exactly_0_2_kwh_in_peak_is_fair_not_good(self):
        day = grade_day(summary(grid_kwh=grid(peak=0.2)), "d")
        assert day["grade"] == FAIR and day["peak_covered"] is False

    def test_just_under_0_2_kwh_in_peak_is_still_good(self):
        assert grade_day(summary(grid_kwh=grid(peak=0.19)), "d")["grade"] == GOOD

    @pytest.mark.parametrize("mid,grade", [(0.49, GOOD), (0.5, FAIR), (2.4, FAIR)])
    def test_midpeak_grid_charging(self, mid, grade):
        assert grade_day(summary(grid_kwh=grid(mid=mid)), "d")["grade"] == grade

    def test_a_handover_is_fair_when_peak_was_covered(self):
        day = grade_day(summary(handover_at="15:20", handover_period="mid-peak"), "d")
        assert day["grade"] == FAIR
        assert "handover at 15:20" in day["reasons"]

    @pytest.mark.parametrize("pred,grade", [(22.0, GOOD), (22.1, FAIR), (1.9, FAIR), (2.0, GOOD)])
    def test_peak_end_prediction_off_by_more_than_10_points(self, pred, grade):
        assert grade_day(summary(gauge_peak_end=12.0, pred_gauge_peak_end=pred), "d")["grade"] == grade

    def test_missing_prediction_does_not_downgrade(self):
        day = grade_day(summary(gauge_peak_end=None, pred_gauge_peak_end=None), "d")
        assert day["grade"] == GOOD and day["peak_end_error_pts"] is None

    @pytest.mark.parametrize("longest,grade", [(30, GOOD), (31, FAIR), (60, FAIR), (61, POOR)])
    def test_frozen_data(self, longest, grade):
        assert grade_day(summary(stale_longest_min=longest, stale_minutes=longest), "d")["grade"] == grade

    def test_the_longest_stretch_counts_not_the_total(self):
        day = grade_day(summary(stale_minutes=70, stale_longest_min=25), "d")
        assert day["grade"] == GOOD

    def test_without_a_longest_stretch_the_total_is_used(self):
        s = summary(stale_minutes=45)
        del s["stale_longest_min"]
        assert grade_day(s, "d")["grade"] == FAIR

    def test_a_command_the_inverter_ignored_is_poor(self):
        day = grade_day(summary(commands_not_followed=1), "d")
        assert day["grade"] == POOR
        assert "inverter ignored a command" in day["reasons"]

    def test_a_day_with_no_data_is_not_graded(self):
        assert grade_day({}, "d") is None
        assert grade_day(None, "d") is None
        assert grade_day({"grid_kwh": {}, "stale_longest_min": 10}, "d") is None

    def test_a_day_frozen_throughout_is_poor_even_without_grid_readings(self):
        day = grade_day({"grid_kwh": {}, "stale_longest_min": 600}, "d")
        assert day["grade"] == POOR

    def test_dollars_use_the_time_of_day_prices(self):
        day = grade_day(summary(grid_kwh=grid(mid=1.0, peak=0.5)), "d")
        assert day["cost_usd"] == pytest.approx(0.1670 + 0.5 * 0.4313, abs=0.005)

    def test_worst_reason_wins_and_all_are_listed(self):
        day = grade_day(summary(grid_kwh=grid(mid=1.0, peak=1.0), handover_at="16:00"), "d")
        assert day["grade"] == POOR
        assert day["reasons"] == ["handover at 16:00", "mid-peak grid 1.0 kWh"]


class TestStatus:
    def test_no_days_no_state(self):
        assert status([])["state"] is None

    def test_seven_good_days(self):
        s = status([rec(GOOD, "2026-11-%02d" % d) for d in range(10, 17)])
        assert s["state"] == HEALTH_GOOD
        assert s["counts"] == {GOOD: 7, FAIR: 0, POOR: 0}

    def test_one_fair_day_is_watch(self):
        days = [rec(GOOD)] * 3 + [rec(FAIR)] + [rec(GOOD)] * 3
        assert status(days)["state"] == HEALTH_WATCH

    def test_a_poor_day_in_the_window_is_review(self):
        days = [rec(POOR)] + [rec(GOOD)] * 6
        s = status(days)
        assert s["state"] == HEALTH_REVIEW
        assert "1 Poor day in the last 7" in s["review_reasons"][0]

    def test_a_poor_day_older_than_the_window_does_not_count(self):
        days = [rec(POOR)] + [rec(GOOD)] * 7
        assert status(days)["state"] == HEALTH_GOOD

    def test_three_not_good_in_a_row_is_review(self):
        s = status([rec(GOOD), rec(FAIR), rec(FAIR), rec(FAIR)])
        assert s["state"] == HEALTH_REVIEW
        assert "3 days in a row" in s["review_reasons"][0]

    def test_two_not_good_in_a_row_is_only_watch(self):
        assert status([rec(GOOD), rec(FAIR), rec(FAIR)])["state"] == HEALTH_WATCH

    def test_a_good_day_breaks_the_run(self):
        assert status([rec(FAIR), rec(FAIR), rec(GOOD), rec(FAIR)])["state"] == HEALTH_WATCH

    def test_bias_over_8_points_the_same_way_is_review(self):
        s = status([rec(GOOD, err=9.0)] * 7)
        assert s["state"] == HEALTH_REVIEW
        assert s["bias_pts"] == 9.0
        assert "9 points too high" in s["review_reasons"][0]

    def test_bias_the_other_way(self):
        s = status([rec(GOOD, err=-8.5)] * 7)
        assert s["state"] == HEALTH_REVIEW and "too low" in s["review_reasons"][0]

    def test_errors_that_cancel_out_are_not_a_bias(self):
        days = [rec(GOOD, err=9.0), rec(GOOD, err=-9.0)] * 3 + [rec(GOOD, err=0.0)]
        assert status(days)["state"] == HEALTH_GOOD

    def test_exactly_8_is_not_over_8(self):
        assert status([rec(GOOD, err=8.0)] * 7)["state"] == HEALTH_GOOD

    def test_a_short_history_is_not_enough_for_a_bias(self):
        assert status([rec(GOOD, err=15.0)] * 4)["state"] == HEALTH_GOOD
        assert status([rec(GOOD, err=15.0)] * 5)["state"] == HEALTH_REVIEW

    def test_days_without_a_prediction_do_not_count_toward_the_bias(self):
        days = [rec(GOOD, err=15.0)] * 4 + [rec(GOOD, err=None)] * 3
        assert status(days)["state"] == HEALTH_GOOD


class TestMessages:
    def good_day(self, **over):
        day = grade_day(summary(), "2026-11-17")
        day.update(over)
        return day

    def test_the_agreed_example(self):
        counts = {GOOD: 6, FAIR: 1, POOR: 0}
        title, body = daily_message(self.good_day(), {"days": 7, "counts": counts})
        assert title == "Solarseed Daily Report - Good"
        assert body.split("\n") == [
            "peak on battery, ended at 12 % (predicted 9 %), $0.00 at mid-peak and peak prices.",
            "Last 7 weekdays: 6 good, 1 fair.",
        ]

    def test_a_bad_day_says_what_went_wrong(self):
        day = grade_day(summary(grid_kwh=grid(mid=0.8, peak=0.4), handover_at="16:10"), "d")
        title, body = daily_message(day, {"days": 3, "counts": {GOOD: 1, FAIR: 0, POOR: 2}})
        assert title.endswith("Poor")
        first = body.split("\n")[0]
        assert first.startswith("peak bought 0.4 kWh, handover at 16:10, mid-peak grid 0.8 kWh")
        assert "$0.31 at mid-peak and peak prices" in first      # 0.8 x 16.70 c + 0.4 x 43.13 c
        assert body.split("\n")[1] == "Last 3 weekdays: 1 good, 2 poor."

    def test_without_a_gauge_reading_the_end_clause_is_left_out(self):
        day = grade_day(summary(gauge_peak_end=None), "d")
        _, body = daily_message(day, {"days": 1, "counts": {GOOD: 1}})
        assert "ended at" not in body
        assert body.endswith("Last 1 weekday: 1 good.")

    def test_every_day_wording_when_weekdays_only_is_off(self):
        _, body = daily_message(self.good_day(), {"days": 2, "counts": {GOOD: 2}}, "day")
        assert body.endswith("Last 2 days: 2 good.")

    def test_messages_are_ascii(self):
        s = status([rec(POOR), rec(FAIR, err=12.0), rec(FAIR, err=12.0)])
        for text in (*daily_message(self.good_day(), s), *review_message(s)):
            text.encode("ascii")

    def test_review_message(self):
        s = status([rec(POOR)] + [rec(GOOD)] * 2)
        title, body = review_message(s)
        assert title == "Solarseed - review needed"
        assert body == "1 Poor day in the last 3. Time for a review session."
