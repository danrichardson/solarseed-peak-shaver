"""Tests for the third-party pack tracker (pure logic, no HA). ROADMAP items 1 and 2."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.solarseed_peak_shaver.packs import (
    BRIDGE_MIN,
    MAX_POINTS,
    STATE_ARMED,
    STATE_IDLE,
    STATE_MEASURING,
    PackTracker,
)

PACKS = ["sensor.p1_current", "sensor.p2_current"]
T0 = datetime(2026, 11, 21, 12, 0)


class Bank:
    """A bank that discharges at a fixed current per pack while the bus falls linearly."""

    def __init__(self, tracker: PackTracker, amps=(-20.0, -22.0), v0=54.0, dv_per_min=0.01):
        self.t = tracker
        self.amps = list(amps)
        self.v = v0
        self.dv = dv_per_min
        self.gauge = 99.0
        self.now = T0
        self.recorded = 0

    def step(self, minutes=1, currents=None, gauge=None, v=None, ac_kw=1.2):
        for _ in range(minutes):
            self.now += timedelta(minutes=1)
            if v is None:
                self.v -= self.dv
            cur = currents if currents is not None else dict(zip(PACKS, self.amps))
            g = self.gauge if gauge is None else gauge
            if self.t.tick(self.now, g, self.v if v is None else v, cur, ac_kw):
                self.recorded += 1

    def anchor(self):
        self.step(1, currents={p: 0.0 for p in PACKS}, gauge=99.0, v=55.0)
        self.step(1, currents={p: 0.0 for p in PACKS}, gauge=100.0, v=55.0)
        self.gauge = 100.0


def make(**kw) -> tuple[PackTracker, Bank]:
    t = PackTracker(PACKS, **kw)
    return t, Bank(t)


class TestChargeEstimate:
    def test_unknown_before_the_first_anchor(self):
        t, bank = make()
        bank.step(30)
        assert t.estimate_pct(PACKS[0]) is None

    def test_counts_amp_hours_out_since_full(self):
        t, bank = make(capacity_ah=100.0)
        bank.anchor()
        assert t.estimate_pct(PACKS[0]) == pytest.approx(100.0)
        bank.step(90)                                     # 1.5 h at 20 A and 22 A
        assert t.out_ah[PACKS[0]] == pytest.approx(30.0)
        assert t.estimate_pct(PACKS[0]) == pytest.approx(70.0)
        assert t.estimate_pct(PACKS[1]) == pytest.approx(67.0)

    def test_charging_puts_it_back_but_never_past_full(self):
        t, bank = make()
        bank.anchor()
        bank.step(60)
        bank.step(30, currents={p: 30.0 for p in PACKS}, v=53.5)
        assert t.out_ah[PACKS[0]] == pytest.approx(5.0)
        bank.step(60, currents={p: 30.0 for p in PACKS}, v=54.0)
        assert t.out_ah[PACKS[0]] == 0.0
        assert t.estimate_pct(PACKS[0]) == 100.0

    def test_a_new_flip_to_full_resets_the_count(self):
        t, bank = make()
        bank.anchor()
        bank.step(60)
        bank.step(1, gauge=97.0, v=54.5, currents={p: 30.0 for p in PACKS})
        bank.step(1, gauge=100.0, v=55.2, currents={p: 0.0 for p in PACKS})
        assert t.out_ah[PACKS[0]] == 0.0

    def test_staying_at_full_is_not_a_new_anchor(self):
        t, bank = make()
        bank.anchor()
        first = t.anchor_at
        bank.step(30, gauge=100.0)                        # gauge still reads 100 early in a discharge
        assert t.anchor_at == first
        assert t.out_ah[PACKS[0]] == pytest.approx(10.0)

    def test_a_short_dropout_is_bridged(self):
        t, bank = make()
        bank.anchor()
        bank.step(1)
        bank.step(int(BRIDGE_MIN), currents={PACKS[0]: None, PACKS[1]: -22.0})
        assert t.gap_min[PACKS[0]] == 0.0
        assert t.out_ah[PACKS[0]] == pytest.approx(20.0 * (BRIDGE_MIN + 1) / 60)

    def test_a_long_dropout_is_counted_as_a_gap(self):
        t, bank = make()
        bank.anchor()
        bank.step(1)
        bank.step(20, currents={PACKS[0]: None, PACKS[1]: -22.0})
        assert t.gap_min[PACKS[0]] == pytest.approx(20 - BRIDGE_MIN)

    def test_a_pack_added_after_the_anchor_is_unknown_until_the_next(self):
        t, bank = make()
        bank.anchor()
        t2 = PackTracker.from_dict(t.to_dict(), PACKS + ["sensor.p3_current"])
        assert t2.estimate_pct("sensor.p3_current") is None
        assert t2.estimate_pct(PACKS[0]) == 100.0


class TestCapacityRun:
    def test_records_amp_hours_between_the_two_voltages(self):
        t, bank = make(v_high=53.0, v_low=51.5)
        bank.anchor()
        bank.v = 54.0
        bank.step(400)                                    # 54.0 V falling 0.01 V a minute
        assert bank.recorded == 1
        pt = t.points[-1]
        assert pt["hours"] == pytest.approx(2.5, abs=0.05)       # 150 minutes from 53.0 to 51.5
        assert pt["ah"][PACKS[0]] == pytest.approx(50.0, abs=0.5)
        assert pt["ah"][PACKS[1]] == pytest.approx(55.0, abs=0.5)
        assert pt["ac_kwh"] == pytest.approx(3.0, abs=0.05)
        assert pt["mean_kw"] == pytest.approx(1.2, abs=0.01)
        assert t.latest_ah(PACKS[0]) == pt["ah"][PACKS[0]]
        assert t.run_state == STATE_IDLE                  # one point per anchor

    def test_one_point_per_full_charge(self):
        t, bank = make()
        bank.anchor()
        bank.v = 54.0
        bank.step(400)
        bank.v = 53.6
        bank.step(200)
        assert bank.recorded == 1

    def test_a_brief_dip_does_not_start_the_run(self):
        t, bank = make()
        bank.anchor()
        bank.step(5, v=53.5)
        bank.step(2, v=52.8)                              # a kettle: two minutes below 53.0
        bank.step(5, v=53.3)
        assert t.run_state == STATE_ARMED
        bank.v = 53.3
        bank.step(400)
        assert bank.recorded == 1
        pt = t.points[-1]
        assert pt["hours"] == pytest.approx(2.5, abs=0.05)                # 53.0 -> 51.5, not from the dip
        assert pt["start"] > (T0 + timedelta(minutes=40)).isoformat()

    def test_a_brief_dip_below_the_low_voltage_does_not_end_it(self):
        t, bank = make()
        bank.anchor()
        bank.v = 54.0
        bank.step(130)                                    # bus 52.7, measuring
        assert t.run_state == STATE_MEASURING
        bank.step(2, v=51.3)
        bank.step(2, v=52.6)
        assert t.run_state == STATE_MEASURING
        bank.v = 52.6
        bank.step(200)
        assert bank.recorded == 1

    def test_a_run_must_start_above_the_upper_voltage(self):
        t, bank = make()
        bank.step(1, gauge=99.0, v=52.9, currents={p: 0.0 for p in PACKS})
        bank.step(1, gauge=100.0, v=52.9, currents={p: 0.0 for p in PACKS})    # full, but the bus is low
        assert t.run_state == STATE_ARMED
        bank.gauge, bank.v = 100.0, 52.9
        bank.step(300)
        assert bank.recorded == 0

    def test_a_recharge_discards_the_run(self):
        t, bank = make()
        bank.anchor()
        bank.v = 54.0
        bank.gauge = 60.0
        bank.step(150)
        bank.step(10, gauge=70.0, currents={p: 30.0 for p in PACKS}, v=52.5)
        assert t.run_state == STATE_IDLE and bank.recorded == 0
        assert "recharged" in t.last_abort or "charged" in t.last_abort

    def test_charging_current_alone_discards_the_run(self):
        t, bank = make()
        bank.anchor()
        bank.v = 54.0
        bank.step(150)
        bank.step(5, currents={p: 15.0 for p in PACKS}, v=52.4)
        assert t.run_state == STATE_IDLE
        assert "charged" in t.last_abort

    def test_a_long_current_gap_discards_the_run(self):
        t, bank = make()
        bank.anchor()
        bank.v = 54.0
        bank.step(150)
        bank.step(20, currents={PACKS[0]: None, PACKS[1]: -22.0})
        assert t.run_state == STATE_IDLE
        assert "missing" in t.last_abort

    def test_a_restart_gap_discards_the_run(self):
        t, bank = make()
        bank.anchor()
        bank.v = 54.0
        bank.step(150)
        bank.now += timedelta(minutes=30)                 # HA was down
        bank.step(1)
        assert t.run_state == STATE_IDLE
        assert "no readings" in t.last_abort
        assert t.gap_min[PACKS[0]] == pytest.approx(31)

    def test_survives_a_quick_restart_mid_run(self):
        t, bank = make()
        bank.anchor()
        bank.v = 54.0
        bank.step(150)
        t2 = PackTracker.from_dict(t.to_dict(), PACKS)
        bank.t = t2
        bank.step(250)
        assert bank.recorded == 1
        assert t2.points[-1]["ah"][PACKS[0]] == pytest.approx(50.0, abs=0.5)

    def test_history_only_shows_runs_at_the_current_voltages(self):
        t, bank = make()
        bank.anchor()
        bank.v = 54.0
        bank.step(400)
        assert len(t.history(PACKS[0])) == 1
        t2 = PackTracker.from_dict(t.to_dict(), PACKS, v_high=52.5, v_low=51.0)
        assert t2.history(PACKS[0]) == [] and len(t2.points) == 1

    def test_changing_the_voltages_mid_run_drops_the_run(self):
        t, bank = make()
        bank.anchor()
        bank.v = 54.0
        bank.step(150)
        t2 = PackTracker.from_dict(t.to_dict(), PACKS, v_high=52.5, v_low=51.0)
        assert t2.run_state == STATE_IDLE

    def test_points_are_capped(self):
        t, _ = make()
        t.points = [{"start": "x", "ah": {PACKS[0]: 1.0}}] * (MAX_POINTS + 5)
        t2 = PackTracker.from_dict(t.to_dict(), PACKS)
        assert len(t2.points) == MAX_POINTS

    def test_bad_blob_starts_empty(self):
        t = PackTracker.from_dict({"points": "junk", "out_ah": 7, "last_at": "nope"}, PACKS)
        assert t.points == [] and t.anchor_at is None

    def test_run_status_reports_progress(self):
        t, bank = make()
        bank.anchor()
        assert t.run_status()["state"] == STATE_ARMED
        bank.v = 54.0
        bank.step(150)
        st = t.run_status()
        assert st["state"] == STATE_MEASURING and st["ah_so_far"][PACKS[0]] > 10
