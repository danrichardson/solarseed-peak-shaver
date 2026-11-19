"""Tests for the learned battery and load model (pure logic, no HA)."""
from __future__ import annotations

import json

import pytest

from custom_components.solarseed_peak_shaver.learning import (
    REGIME_DISCHARGE,
    REGIME_GRID_CHARGE,
    REGIME_NONE,
    REGIME_SOLAR_CHARGE,
    Curve,
    Learner,
    LoadProfile,
    classify,
)


class TestCurve:
    def test_empty_curve_is_the_prior(self):
        c = Curve(prior_per_pt=0.2)
        assert c.energy_between(0, 100) == pytest.approx(20.0)
        assert c.per_pt(3) == pytest.approx(0.2)

    def test_observation_spreads_over_the_bins_crossed(self):
        c = Curve(bin_pts=5, prior_per_pt=0.2, prior_pts=0.001)
        c.observe(20, 10, 1.5)           # 10 points, 0.15 kWh per point, bins 10-15 and 15-20
        assert c.per_pt(2) == pytest.approx(0.15, abs=1e-3)
        assert c.per_pt(3) == pytest.approx(0.15, abs=1e-3)
        assert c.per_pt(4) == pytest.approx(0.2, abs=1e-3)      # untouched bin keeps the prior
        assert c.weight(2) == pytest.approx(5.0)

    def test_direction_of_the_observation_does_not_matter(self):
        a, b = Curve(), Curve()
        a.observe(30, 40, 2.0)
        b.observe(40, 30, 2.0)
        assert a.e == b.e and a.p == b.p

    def test_tiny_or_empty_observations_are_ignored(self):
        c = Curve()
        c.observe(50, 50.2, 1.0)
        c.observe(50, 40, 0.0)
        assert sum(c.p) == 0

    def test_prior_fades_as_data_arrives(self):
        c = Curve(prior_per_pt=0.235, prior_pts=3.0)
        for _ in range(40):
            c.observe(55, 50, 0.75)      # 0.15 per point
        assert c.per_pt(10) == pytest.approx(0.15, abs=0.005)

    def test_aging_lets_new_data_win(self):
        c = Curve(prior_pts=0.001, half_life_days=30)
        c.observe(55, 50, 1.0)           # 0.20 per point
        c.age(300)
        c.observe(55, 50, 0.5)           # 0.10 per point
        assert c.per_pt(10) == pytest.approx(0.10, abs=0.005)

    def test_move_and_energy_between_agree(self):
        c = Curve(prior_pts=0.001)
        c.observe(100, 50, 10.0)         # 0.20 above 50
        c.observe(50, 0, 5.0)            # 0.10 below 50
        e = c.energy_between(20, 80)
        assert e == pytest.approx(3.0 + 6.0, rel=1e-3)
        assert c.move(80, e, -1) == pytest.approx(20, abs=0.01)
        assert c.move(20, e, +1) == pytest.approx(80, abs=0.01)

    def test_move_stops_at_the_limits(self):
        c = Curve(prior_per_pt=0.2)
        assert c.move(10, 99.0, -1, lo=3.0) == 3.0
        assert c.move(90, 99.0, +1) == 100.0

    def test_gauge_for_energy(self):
        c = Curve(prior_per_pt=0.2)
        assert c.gauge_for_energy(3.0, 4.0) == pytest.approx(23.0)
        assert c.gauge_for_energy(3.0, 500.0) == 100.0

    def test_hours_between(self):
        c = Curve(prior_pts=0.001, prior_hours_per_pt=0.1)
        c.observe(10, 20, 1.5, hours=1.0)        # 0.1 h per point
        assert c.hours_between(10, 20) == pytest.approx(1.0, rel=1e-2)

    def test_round_trip_through_json(self):
        c = Curve(bin_pts=5, prior_hours_per_pt=0.12)
        c.observe(80, 20, 9.0, hours=4.0)
        d = json.loads(json.dumps(c.to_dict()))
        c2 = Curve.from_dict(d)
        assert c2.energy_between(3, 100) == pytest.approx(c.energy_between(3, 100), rel=1e-4)
        assert c2.hours_between(20, 80) == pytest.approx(c.hours_between(20, 80), rel=1e-4)

    def test_from_dict_survives_garbage(self):
        assert Curve.from_dict(None).energy_between(0, 100) == pytest.approx(23.5)
        assert Curve.from_dict({"e": [1, 2], "p": "x"}).energy_between(0, 100) == pytest.approx(23.5)


class TestLoadProfile:
    def _day(self, kw):
        return {h: kw for h in range(24)}

    def test_default_until_there_is_data(self):
        lp = LoadProfile(default_kw=0.6)
        assert lp.mean(True, 10) == 0.6
        assert lp.window_mean(True, 7, 21) == pytest.approx(8.4)
        assert lp.window_quantile(True, 7, 21, 0.8) == pytest.approx(8.4)

    def test_day_types_are_kept_apart(self):
        lp = LoadProfile()
        lp.observe_day(True, self._day(1.0))
        lp.observe_day(False, self._day(0.3))
        assert lp.mean(True, 12) == 1.0
        assert lp.mean(False, 12) == 0.3

    def test_incomplete_days_are_skipped(self):
        lp = LoadProfile()
        lp.observe_day(True, {h: 1.0 for h in range(10)})
        assert lp.n_days(True) == 0

    def test_only_the_trailing_days_count(self):
        lp = LoadProfile(days=3)
        for kw in (5.0, 1.0, 1.0, 1.0):
            lp.observe_day(True, self._day(kw))
        assert lp.mean(True, 8) == 1.0

    def test_quantile_is_over_whole_days(self):
        lp = LoadProfile()
        for kw in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
            lp.observe_day(True, self._day(kw))
        assert lp.window_quantile(True, 7, 21, 0.0) == pytest.approx(0.5 * 14)
        assert lp.window_quantile(True, 7, 21, 1.0) == pytest.approx(1.0 * 14)
        assert lp.window_quantile(True, 7, 21, 0.8) == pytest.approx(0.9 * 14)
        assert lp.window_quantile(True, 7, 21, 0.8) > lp.window_mean(True, 7, 21)

    def test_round_trip_through_json(self):
        lp = LoadProfile()
        for kw in (0.5, 0.7):
            lp.observe_day(True, self._day(kw))
        lp.observe_day(False, self._day(0.2))
        lp2 = LoadProfile.from_dict(json.loads(json.dumps(lp.to_dict())))
        assert lp2.mean(True, 3) == pytest.approx(0.6)
        assert lp2.mean(False, 3) == pytest.approx(0.2)
        assert LoadProfile.from_dict({"tou": ["junk", None]}).n_days(True) == 0


class TestClassify:
    def test_regimes(self):
        assert classify(0.0, 0.6, 0.0) == REGIME_DISCHARGE
        assert classify(0.0, 0.6, 0.3) == REGIME_DISCHARGE
        assert classify(0.0, 0.5, 1.5) == REGIME_SOLAR_CHARGE
        assert classify(2.4, 0.6, 0.0) == REGIME_GRID_CHARGE
        assert classify(0.6, 0.6, 0.0) == REGIME_NONE          # bypass: grid carries the load
        assert classify(2.4, 0.6, 0.5) == REGIME_NONE          # grid and solar together: ambiguous
        assert classify(0.0, 0.5, 0.5) == REGIME_NONE


class TestLearner:
    MIN = 1.0 / 60

    def _run(self, ln, gauge_seq, grid, load, pv, minutes_per_point):
        for g in gauge_seq:
            for _ in range(minutes_per_point):
                ln.sample(g, grid, load, pv, self.MIN)

    def test_learns_discharge_energy_per_point(self):
        ln = Learner(prior_per_pt=0.235)
        # 0.6 kW for 15 minutes per point = 0.15 kWh per point
        for _ in range(6):
            self._run(ln, range(80, 39, -1), 0.0, 0.6, 0.0, 15)
        assert ln.discharge.per_pt(10) == pytest.approx(0.15, abs=0.01)
        assert sum(ln.grid_charge.p) == 0

    def test_learns_charge_energy_and_time(self):
        ln = Learner()
        # net 1.8 kW, 5 minutes per point = 0.15 kWh and 1/12 h per point
        for _ in range(6):
            self._run(ln, range(10, 61), 2.4, 0.6, 0.0, 5)
        assert ln.grid_charge.per_pt(6) == pytest.approx(0.15, abs=0.01)
        assert ln.grid_charge.hours_per_pt(6) == pytest.approx(1 / 12, abs=0.01)

    def test_slow_charge_teaches_energy_but_not_time(self):
        ln = Learner()
        prior_h = ln.grid_charge.hours_per_pt(6)
        for _ in range(6):
            self._run(ln, range(10, 61), 1.0, 0.6, 0.0, 20)       # throttled, below FULL_RATE_KW
        assert ln.grid_charge.per_pt(6) == pytest.approx(0.4 * 20 / 60, abs=0.01)
        assert ln.grid_charge.hours_per_pt(6) == pytest.approx(prior_h)   # timing untouched by a slow charge

    def test_slow_charges_do_not_dilute_learned_timing(self):
        ln = Learner()
        for _ in range(4):
            self._run(ln, range(10, 61), 2.4, 0.6, 0.0, 5)        # full rate: 1/12 h per point
        fast = ln.grid_charge.hours_per_pt(6)
        for _ in range(20):
            self._run(ln, range(10, 61), 1.0, 0.6, 0.0, 20)       # many throttled charges
        assert ln.grid_charge.hours_per_pt(6) == pytest.approx(fast, rel=0.02)

    def test_solar_charge_has_its_own_curve(self):
        ln = Learner()
        self._run(ln, range(30, 50), 0.0, 0.5, 1.5, 6)
        assert sum(ln.solar_charge.p) > 0
        assert sum(ln.grid_charge.p) == 0 and sum(ln.discharge.p) == 0

    def test_first_partial_point_of_a_stretch_is_skipped(self):
        ln = Learner()
        self._run(ln, [50, 49], 0.0, 0.6, 0.0, 10)
        assert sum(ln.discharge.p) == 0          # only one tick seen: not aligned yet
        self._run(ln, [48], 0.0, 0.6, 0.0, 10)
        assert sum(ln.discharge.p) == pytest.approx(1.0)

    def test_regime_change_discards_the_open_stretch(self):
        ln = Learner()
        self._run(ln, [50, 49, 48], 0.0, 0.6, 0.0, 10)
        seen = sum(ln.discharge.p)
        self._run(ln, [48], 2.4, 0.6, 0.0, 10)   # charge starts mid-point
        self._run(ln, [48, 47], 0.0, 0.6, 0.0, 10)
        assert sum(ln.discharge.p) == seen       # the point that straddled the charge is not credited

    def test_long_gap_resets(self):
        ln = Learner()
        self._run(ln, [50, 49], 0.0, 0.6, 0.0, 10)
        ln.sample(40, 0.0, 0.6, 0.0, 3.0)        # three hours with no samples
        self._run(ln, [40], 0.0, 0.6, 0.0, 5)
        assert sum(ln.discharge.p) == 0

    def test_parked_gauge_is_not_learned(self):
        ln = Learner()
        self._run(ln, [6, 5, 4, 3, 2], 0.0, 0.6, 0.0, 15)
        self._run(ln, [1], 0.0, 0.6, 0.0, 1)                     # the real 2 -> 1 point closes here
        seen_p, seen_e = sum(ln.discharge.p), sum(ln.discharge.e)
        self._run(ln, [1], 0.0, 0.6, 0.0, 15 * 60)              # parked at 1 % for 15 h, 9 kWh
        self._run(ln, [0], 0.0, 0.6, 0.0, 15)
        assert sum(ln.discharge.p) == seen_p
        assert sum(ln.discharge.e) == pytest.approx(seen_e)
        assert ln.discharge.per_pt(0) < 0.3

    def test_slow_but_real_points_are_still_learned(self):
        ln = Learner()
        # a quiet night: 0.35 kW and 0.42 kWh per point = 72 minutes per point
        self._run(ln, range(20, 9, -1), 0.0, 0.35, 0.0, 72)
        assert sum(ln.discharge.p) == pytest.approx(9.0)
        assert ln.discharge.per_pt(2) > 0.3

    def test_charging_tail_is_not_capped(self):
        ln = Learner()
        # throttled tail at the top: 3 hours on one point is real and must be learned
        self._run(ln, [97, 98, 99, 100], 0.9, 0.2, 0.0, 180)
        assert sum(ln.grid_charge.p) == pytest.approx(2.0)

    def test_round_trip_through_json(self):
        ln = Learner()
        for _ in range(3):
            self._run(ln, range(80, 39, -1), 0.0, 0.6, 0.0, 15)
            self._run(ln, range(40, 81), 2.4, 0.6, 0.0, 5)
        ln2 = Learner.from_dict(json.loads(json.dumps(ln.to_dict())))
        assert ln2.discharge.energy_between(40, 80) == pytest.approx(ln.discharge.energy_between(40, 80), rel=1e-3)
        assert ln2.grid_charge.hours_between(40, 80) == pytest.approx(ln.grid_charge.hours_between(40, 80), rel=1e-3)
        assert Learner.from_dict(None).discharge.energy_between(0, 100) == pytest.approx(23.5)


class TestBackfillBuilders:
    def _rows(self, start, gauges, minutes=5, grid=0.0, load=0.6):
        from datetime import timedelta
        return [(start + timedelta(minutes=minutes * i), g, grid, load, 0.0, minutes / 60.0)
                for i, g in enumerate(gauges)]

    def test_builds_a_discharge_curve(self):
        from datetime import datetime
        from custom_components.solarseed_peak_shaver.learning import build_from_samples

        # 0.6 kW, one point every 15 minutes = 0.15 kWh per point
        gauges = [80 - i / 3.0 for i in range(120)]
        ln = build_from_samples(self._rows(datetime(2026, 11, 10, 8, 0), gauges))
        assert ln.discharge.e[12] / ln.discharge.p[12] == pytest.approx(0.15, abs=0.01)

    def test_a_gap_in_the_rows_is_not_credited(self):
        from datetime import datetime, timedelta
        from custom_components.solarseed_peak_shaver.learning import build_from_samples

        gauges = [80 - i / 3.0 for i in range(60)]
        rows = self._rows(datetime(2026, 11, 10, 8, 0), gauges)
        # two hours missing, during which the gauge fell 20 points that were never measured
        later = [(w + timedelta(hours=2), g - 20, a, b, c, h) for (w, g, a, b, c, h) in rows[30:]]
        ln = build_from_samples(rows[:30] + later)
        for i in range(ln.discharge.n):
            if ln.discharge.p[i] > 0:
                assert ln.discharge.e[i] / ln.discharge.p[i] == pytest.approx(0.15, abs=0.02)

    def test_profile_from_hourly(self):
        from datetime import datetime, timedelta
        from custom_components.solarseed_peak_shaver.learning import profile_from_hourly

        start = datetime(2026, 11, 9, 0, 0)          # a Monday
        rows = [(start + timedelta(hours=i), 0.5 if (start + timedelta(hours=i)).weekday() < 5 else 0.2)
                for i in range(24 * 7)]
        lp = profile_from_hourly(rows, lambda d: d.weekday() < 5)
        assert lp.n_days(True) == 5 and lp.n_days(False) == 2
        assert lp.mean(True, 10) == pytest.approx(0.5) and lp.mean(False, 10) == pytest.approx(0.2)
