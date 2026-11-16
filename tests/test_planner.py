"""Tests for the tariff-window planner (pure logic, no HA)."""
from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.solarseed_peak_shaver.learning import Learner, LoadProfile
from custom_components.solarseed_peak_shaver.planner import (
    MODE_CHARGE,
    MODE_DISCHARGE,
    MODE_HOLD,
    PlanInputs,
    decide,
    model_ready,
    predict_gauge,
    window_need,
)

# 2026-11-16 is a Monday, 2026-11-20 a Friday, 2026-11-21 a Saturday, 2026-11-22 a Sunday.
# 2026-03-16 is a Monday in a month that is not a full-charge month.


def trained(kwh_per_pt: float = 0.15, load_kw: float = 0.6, days: int = 8):
    """A learner and profile with enough data to be trusted."""
    ln = Learner(prior_per_pt=0.235)
    for _ in range(6):
        ln.discharge.observe(100, 0, kwh_per_pt * 100)
        ln.grid_charge.observe(0, 100, kwh_per_pt * 100, hours=10.0)     # 0.1 h per point
    lp = LoadProfile(default_kw=load_kw)
    for i in range(days):
        lp.observe_day(True, {h: load_kw + 0.02 * i for h in range(24)})
    assert model_ready(ln, lp)
    return ln, lp


def inputs(when: str, gauge, tou_today=True, tou_tomorrow=True, **kw) -> PlanInputs:
    return PlanInputs(now=datetime.fromisoformat(when), gauge=gauge, is_tou_today=tou_today,
                      is_tou_tomorrow=tou_tomorrow, **kw)


class TestWindowNeed:
    def test_flat_load_no_solar(self):
        lp = LoadProfile(default_kw=0.5)
        assert window_need(lp, {}, 7, 21, 0.8, 0.7, (7, 21)) == pytest.approx(7.0)

    def test_partial_first_hour(self):
        lp = LoadProfile(default_kw=1.0)
        assert window_need(lp, {}, 16.5, 21, 0.8, 0.7, (7, 21)) == pytest.approx(4.5)

    def test_solar_is_discounted_and_never_a_credit(self):
        lp = LoadProfile(default_kw=1.0)
        solar = {12: 1.0, 13: 5.0}
        # hour 12: 1.0 - 0.5 = 0.5; hour 13: surplus counts as zero
        assert window_need(lp, solar, 12, 14, 0.8, 0.5, (7, 21)) == pytest.approx(0.5)

    def test_quantile_scales_the_load_up(self):
        _, lp = trained()
        mean = window_need(lp, {}, 7, 21, 0.5, 0.7, (7, 21))
        high = window_need(lp, {}, 7, 21, 0.9, 0.7, (7, 21))
        assert high > mean


class TestPeakAndMidPeak:
    def test_never_charges_in_peak(self):
        ln, lp = trained()
        d = decide(inputs("2026-11-16T18:00", 3.0), ln, lp)
        assert d.mode == MODE_DISCHARGE and d.phase == "peak"

    def test_midpeak_with_plenty_stays_on_battery(self):
        ln, lp = trained()
        d = decide(inputs("2026-11-16T10:00", 95.0), ln, lp)
        assert d.mode == MODE_DISCHARGE and d.phase == "mid-peak"

    def test_midpeak_short_but_early_waits(self):
        ln, lp = trained()
        d = decide(inputs("2026-11-16T08:00", 30.0), ln, lp)
        assert d.mode == MODE_DISCHARGE
        assert "short" in d.reason

    def test_midpeak_short_and_late_charges_to_finish_by_peak(self):
        ln, lp = trained()
        d = decide(inputs("2026-11-16T16:00", 5.0), ln, lp)
        assert d.mode == MODE_CHARGE and d.phase == "mid-peak"
        assert d.target_gauge > 5.0

    def test_midpeak_charge_keeps_going_until_covered(self):
        ln, lp = trained()
        short_now = decide(inputs("2026-11-16T12:00", 20.0), ln, lp)
        assert short_now.mode == MODE_DISCHARGE          # too early to start
        going = decide(inputs("2026-11-16T12:00", 20.0, current_mode=MODE_CHARGE), ln, lp)
        assert going.mode == MODE_CHARGE                 # but a charge in progress continues

    def test_a_forecast_alone_never_starts_a_charge(self):
        ln, lp = trained()
        sunny = {h: 3.0 for h in range(8, 17)}
        cloudy = {h: 0.0 for h in range(24)}
        for solar in (sunny, cloudy):
            d = decide(inputs("2026-11-16T09:36", 90.0, solar_today=solar), ln, lp)
            assert d.mode == MODE_DISCHARGE

    def test_missing_gauge_in_midpeak_does_not_charge(self):
        ln, lp = trained()
        assert decide(inputs("2026-11-16T10:00", None), ln, lp).mode == MODE_DISCHARGE

    def test_weekend_daytime_is_plain_discharge(self):
        ln, lp = trained()
        d = decide(inputs("2026-11-21T12:00", 20.0, tou_today=False, tou_tomorrow=False), ln, lp)
        assert d.mode == MODE_DISCHARGE and d.phase == "off-peak"


class TestNightFullMonths:
    def test_charges_from_peak_end(self):
        ln, lp = trained()
        d = decide(inputs("2026-11-16T21:00", 20.0), ln, lp)
        assert d.mode == MODE_CHARGE and d.target_gauge == 100.0

    def test_holds_once_the_inverter_has_stopped(self):
        ln, lp = trained()
        d = decide(inputs("2026-11-17T04:00", 100.0, bank_full=True), ln, lp)
        assert d.mode == MODE_HOLD

    def test_at_99_it_keeps_charging(self):
        ln, lp = trained()
        d = decide(inputs("2026-11-17T04:00", 99.0, bank_full=False), ln, lp)
        assert d.mode == MODE_CHARGE

    def test_sunday_night_counts_as_the_night_before_a_tou_day(self):
        ln, lp = trained()
        d = decide(inputs("2026-11-22T21:30", 40.0, tou_today=False, tou_tomorrow=True), ln, lp)
        assert d.mode == MODE_CHARGE and d.phase == "night"

    def test_december_night_before_january_uses_january(self):
        ln, lp = trained()
        d = decide(inputs("2026-12-31T22:00", 50.0, full_months=(1,)), ln, lp)
        assert d.mode == MODE_CHARGE and d.target_gauge == 100.0


class TestNightSizedMonths:
    def test_holds_then_charges_to_end_at_midpeak_start(self):
        ln, lp = trained(kwh_per_pt=0.15, load_kw=0.6)
        early = decide(inputs("2026-03-16T21:30", 10.0), ln, lp)
        assert early.mode == MODE_HOLD and early.target_gauge < 100
        late = decide(inputs("2026-03-17T06:30", 10.0), ln, lp)
        assert late.mode == MODE_CHARGE
        assert late.target_gauge == pytest.approx(early.target_gauge, abs=0.01)

    def test_target_covers_the_need(self):
        ln, lp = trained(kwh_per_pt=0.15, load_kw=0.6)
        d = decide(inputs("2026-03-16T22:00", 10.0), ln, lp)
        assert ln.discharge.energy_between(3.0, d.target_gauge) >= d.need_kwh - 0.2

    def test_more_than_enough_keeps_discharging(self):
        ln, lp = trained()
        d = decide(inputs("2026-03-16T22:00", 99.0), ln, lp)
        assert d.mode == MODE_DISCHARGE and d.phase == "night"

    def test_holding_does_not_flip_back_to_discharge(self):
        ln, lp = trained()
        d = decide(inputs("2026-03-16T22:00", 99.0, current_mode=MODE_HOLD), ln, lp)
        assert d.mode == MODE_HOLD

    def test_holds_at_target(self):
        ln, lp = trained()
        t = decide(inputs("2026-03-16T22:00", 10.0), ln, lp).target_gauge
        d = decide(inputs("2026-03-17T05:00", round(t), current_mode=MODE_CHARGE), ln, lp)
        assert d.mode == MODE_HOLD

    def test_sunny_forecast_lowers_the_target(self):
        ln, lp = trained()
        cloudy = decide(inputs("2026-03-16T22:00", 10.0), ln, lp).target_gauge
        sunny = decide(inputs("2026-03-16T22:00", 10.0, solar_tomorrow={h: 2.0 for h in range(9, 16)}),
                       ln, lp).target_gauge
        assert sunny < cloudy

    def test_untrained_model_falls_back_to_full(self):
        d = decide(inputs("2026-03-16T22:00", 10.0), Learner(), LoadProfile())
        assert d.mode == MODE_CHARGE and d.target_gauge == 100.0 and not d.model_ready

    def test_missing_gauge_at_night_falls_back_to_full(self):
        ln, lp = trained()
        d = decide(inputs("2026-03-16T22:00", None), ln, lp)
        assert d.mode == MODE_CHARGE and d.target_gauge == 100.0


class TestWeeklyTopUp:
    def test_friday_night_tops_up_in_full_months(self):
        ln, lp = trained()
        d = decide(inputs("2026-11-20T21:30", 30.0, tou_tomorrow=False, topup_pending=True), ln, lp)
        assert d.mode == MODE_CHARGE and d.phase == "top-up"

    def test_top_up_continues_on_saturday_until_full(self):
        ln, lp = trained()
        going = decide(inputs("2026-11-21T10:00", 99.0, tou_today=False, tou_tomorrow=False,
                              topup_pending=True), ln, lp)
        assert going.mode == MODE_CHARGE
        done = decide(inputs("2026-11-21T10:00", 100.0, tou_today=False, tou_tomorrow=False,
                             topup_pending=True, bank_full=True), ln, lp)
        assert done.mode == MODE_DISCHARGE

    def test_no_top_up_outside_full_months(self):
        ln, lp = trained()
        d = decide(inputs("2026-03-20T21:30", 30.0, tou_tomorrow=False, topup_pending=True), ln, lp)
        assert d.mode == MODE_DISCHARGE

    def test_no_top_up_unless_pending(self):
        ln, lp = trained()
        d = decide(inputs("2026-11-20T21:30", 30.0, tou_tomorrow=False), ln, lp)
        assert d.mode == MODE_DISCHARGE


class TestPredictGauge:
    def test_falls_with_load_and_stops_at_floor(self):
        ln, lp = trained(kwh_per_pt=0.15, load_kw=0.6)
        g = predict_gauge(ln, lp, {}, 99.0, 7, 17, 3.0)
        used = sum(lp.mean(True, h) for h in range(7, 17))
        assert g == pytest.approx(ln.discharge.move(99.0, used, -1), abs=0.01)
        assert 50 < g < 60
        assert predict_gauge(ln, lp, {}, 10.0, 7, 21, 3.0) == 3.0

    def test_decision_serialises(self):
        ln, lp = trained()
        d = decide(inputs("2026-11-16T21:00", 20.0), ln, lp).as_dict()
        assert d["mode"] == MODE_CHARGE and isinstance(d["reason"], str)
