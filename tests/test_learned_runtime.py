"""Tests for the HA glue around the learned planner (HA mocked)."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from tests.test_coordinator import _make_coordinator

from custom_components.solarseed_peak_shaver.const import (
    CONF_FULL_CHARGE_MONTHS,
    CONF_GAUGE_ENTITY,
    CONF_GRID_POWER_ENTITY,
    CONF_LOAD_POWER_ENTITY,
    CONF_PLANNER,
    CONF_PV_POWER_ENTITY,
    EVENT_CHARGE_START,
    EVENT_CHARGE_STOP,
    EVENT_PRESERVE_START,
)
from custom_components.solarseed_peak_shaver.learned_runtime import (
    LearnedRuntime,
    is_tou_day,
    mode_matches,
)
from custom_components.solarseed_peak_shaver.planner import MODE_CHARGE, MODE_DISCHARGE, MODE_HOLD

ENTITIES = {
    CONF_GAUGE_ENTITY: "sensor.gauge",
    CONF_LOAD_POWER_ENTITY: "sensor.load",
    CONF_GRID_POWER_ENTITY: "sensor.grid",
    CONF_PV_POWER_ENTITY: "sensor.pv",
}


class World:
    """A fake hass.states whose values the test changes between ticks."""

    def __init__(self):
        self.values = {"sensor.gauge": (50, "%"), "sensor.load": (600, "W"), "sensor.grid": (0, "W"),
                       "sensor.pv": (0, "W"), "sensor.battery_soc": (11.75, "kWh")}

    def get(self, entity_id):
        if entity_id not in self.values:
            return None
        val, unit = self.values[entity_id]
        st = MagicMock()
        st.state = str(val)
        st.attributes = {"unit_of_measurement": unit}
        return st


def make_runtime(planner="classic", **overrides):
    cfg = dict(ENTITIES)
    cfg[CONF_PLANNER] = planner
    cfg.update(overrides)
    coord = _make_coordinator(config_overrides=cfg)
    world = World()
    coord.hass.states.get = world.get
    coord.async_update_listeners = MagicMock()
    rt = LearnedRuntime(coord.hass, coord)
    coord.learned = rt
    return rt, coord, world


def fired(coord):
    return [c.args[0] for c in coord.hass.bus.async_fire.call_args_list]


def run(rt, start: datetime, minutes: int, step=None):
    t = start
    for i in range(minutes):
        if step:
            step(i, t)
        rt.tick(t)
        t += timedelta(minutes=1)
    return t


class TestHelpers:
    def test_is_tou_day(self):
        assert is_tou_day(datetime(2026, 11, 16).date(), True)
        assert not is_tou_day(datetime(2026, 11, 21).date(), True)
        assert is_tou_day(datetime(2026, 11, 21).date(), False)

    def test_mode_matches(self):
        assert mode_matches(MODE_CHARGE, 50, 2.4, 0.6, 0, 3, False) is True
        assert mode_matches(MODE_CHARGE, 50, 0.6, 0.6, 0, 3, False) is False
        assert mode_matches(MODE_CHARGE, 99, 0.6, 0.6, 0, 3, False) is None      # nearly full: cannot tell
        assert mode_matches(MODE_DISCHARGE, 50, 0.0, 0.6, 0, 3, False) is True
        assert mode_matches(MODE_DISCHARGE, 50, 0.6, 0.6, 0, 3, False) is False
        assert mode_matches(MODE_DISCHARGE, 3, 0.6, 0.6, 0, 3, False) is None    # at the floor grid is normal
        assert mode_matches(MODE_HOLD, 50, 0.6, 0.6, 0, 3, False) is True
        assert mode_matches(MODE_HOLD, 50, 0.0, 0.6, 0, 3, False) is False


class TestReading:
    def test_units(self):
        rt, coord, world = make_runtime()
        assert rt._power_kw("sensor.load") == pytest.approx(0.6)
        world.values["sensor.load"] = (0.6, "kW")
        assert rt._power_kw("sensor.load") == pytest.approx(0.6)
        assert rt._power_kw("sensor.missing") is None

    def test_gauge_falls_back_to_soc_over_capacity(self):
        rt, coord, world = make_runtime(**{CONF_GAUGE_ENTITY: ""})
        assert rt.read_gauge() == pytest.approx(50.0)

    def test_unavailable_gauge(self):
        rt, coord, world = make_runtime()
        world.values["sensor.gauge"] = ("unavailable", "%")
        assert rt.read_gauge() is None


class TestShadowMode:
    def test_classic_planner_never_fires_events(self):
        rt, coord, world = make_runtime(planner="classic")
        run(rt, datetime(2026, 11, 16, 20, 55), 20)        # across peak end into the night
        assert rt.decision.mode == MODE_CHARGE              # it knows what it would do
        assert fired(coord) == []                           # and does nothing

    def test_learns_while_shadowing(self):
        rt, coord, world = make_runtime()

        def step(i, t):
            world.values["sensor.gauge"] = (80 - i // 15, "%")

        run(rt, datetime(2026, 11, 16, 8, 0), 300, step)
        assert sum(rt.learner.discharge.p) > 10
        d = rt.learner.discharge
        assert d.e[14] / d.p[14] == pytest.approx(0.15, abs=0.01)     # 0.6 kW, 15 min per point

    def test_missing_power_sensor_just_skips_learning(self):
        rt, coord, world = make_runtime(**{CONF_LOAD_POWER_ENTITY: ""})
        run(rt, datetime(2026, 11, 16, 8, 0), 30)
        assert sum(rt.learner.discharge.p) == 0
        assert rt.decision is not None


class TestLearnedInControl:
    def test_fires_once_per_mode_change(self):
        rt, coord, world = make_runtime(planner="learned")
        run(rt, datetime(2026, 11, 16, 20, 58), 2)          # still peak
        assert fired(coord) == [EVENT_CHARGE_STOP]
        world.values["sensor.grid"] = (2400, "W")
        run(rt, datetime(2026, 11, 16, 21, 0), 30)          # night before a TOU day, November
        assert fired(coord) == [EVENT_CHARGE_STOP, EVENT_CHARGE_START]

    def test_holds_when_the_inverter_reports_full(self):
        rt, coord, world = make_runtime(planner="learned")
        world.values["sensor.grid"] = (2400, "W")
        run(rt, datetime(2026, 11, 16, 21, 0), 3)
        world.values["sensor.gauge"] = (100, "%")
        world.values["sensor.grid"] = (600, "W")
        run(rt, datetime(2026, 11, 16, 23, 0), 3)
        assert fired(coord)[-1] == EVENT_PRESERVE_START
        assert rt.bank_full

    def test_releases_at_midpeak_start(self):
        rt, coord, world = make_runtime(planner="learned")
        world.values["sensor.gauge"] = (100, "%")
        world.values["sensor.grid"] = (600, "W")
        run(rt, datetime(2026, 11, 17, 6, 58), 4)
        assert fired(coord) == [EVENT_PRESERVE_START, EVENT_CHARGE_STOP]

    def test_resends_a_command_the_inverter_ignored_then_alerts(self):
        rt, coord, world = make_runtime(planner="learned")
        coord._notify = MagicMock()
        # night charge commanded, but grid input never rises above the house load
        world.values["sensor.grid"] = (600, "W")
        run(rt, datetime(2026, 11, 16, 21, 0), 60)
        assert fired(coord).count(EVENT_CHARGE_START) == 4      # first + 3 retries
        titles = [c.args[0] for c in coord._notify.call_args_list]
        assert any("not responding" in t for t in titles)

    def test_no_resend_when_the_inverter_obeys(self):
        rt, coord, world = make_runtime(planner="learned")
        world.values["sensor.grid"] = (2400, "W")
        run(rt, datetime(2026, 11, 16, 21, 0), 60)
        assert fired(coord).count(EVENT_CHARGE_START) == 1

    def test_full_detected_from_power_when_gauge_sticks_at_99(self):
        rt, coord, world = make_runtime(planner="learned")
        world.values["sensor.gauge"] = (99, "%")
        world.values["sensor.grid"] = (600, "W")               # charging asked, nothing going in
        run(rt, datetime(2026, 11, 16, 22, 0), 15)
        assert rt.bank_full
        assert fired(coord)[-1] == EVENT_PRESERVE_START

    def test_weekly_topup_is_requested_after_the_last_tou_day(self):
        rt, coord, world = make_runtime(planner="learned")
        world.values["sensor.grid"] = (2400, "W")
        run(rt, datetime(2026, 11, 20, 20, 59), 5)              # Friday across 21:00
        assert rt.topup_pending
        assert fired(coord)[-1] == EVENT_CHARGE_START
        world.values["sensor.gauge"] = (100, "%")
        run(rt, datetime(2026, 11, 21, 9, 0), 2)
        assert not rt.topup_pending
        assert fired(coord)[-1] == EVENT_CHARGE_STOP

    def test_tick_never_raises(self):
        rt, coord, world = make_runtime(planner="learned")
        coord.hass.states.get = MagicMock(side_effect=RuntimeError("boom"))
        rt._on_minute(datetime(2026, 11, 16, 21, 0))            # logged, not raised


class TestClassicStandsDown:
    def test_classic_fires_nothing_when_learned_is_in_control(self):
        import asyncio

        rt, coord, world = make_runtime(planner="learned")
        solar = MagicMock()
        solar.state = "5.0"
        solar.attributes = {"detailedHourly": [{"period_start": "2026-11-16T12:00:00", "pv_estimate": 1.0}]}
        base_get = world.get
        coord.hass.states.get = lambda e: solar if e == "sensor.solcast_today" else base_get(e)
        world.values["sensor.battery_soc"] = (1.0, "kWh")       # classic would want to charge
        result = asyncio.run(coord._async_update_data())
        assert result is not None
        assert fired(coord) == []
        assert coord._charging_active is False


class TestPersistence:
    def test_state_round_trip(self):
        rt, coord, world = make_runtime()

        def step(i, t):
            world.values["sensor.gauge"] = (80 - i // 15, "%")

        run(rt, datetime.now().replace(hour=8, minute=0, second=0, microsecond=0), 200, step)
        rt.topup_pending = True
        blob = rt.dump_state()
        rt2, _, _ = make_runtime()
        rt2.load_state(blob)
        assert rt2.topup_pending
        assert rt2.learner.discharge.energy_between(3, 100) == pytest.approx(
            rt.learner.discharge.energy_between(3, 100), rel=1e-3)
        assert rt2._day_kwh.get(8) == pytest.approx(rt._day_kwh.get(8), rel=1e-3)

    def test_bad_blob_starts_empty(self):
        rt, coord, world = make_runtime()
        rt.load_state({"learner": "junk", "profile": 7, "day": "x"})
        assert rt.learner.discharge.energy_between(0, 100) == pytest.approx(23.5)

    def test_day_rollover_feeds_the_profile(self):
        rt, coord, world = make_runtime()
        run(rt, datetime(2026, 11, 16, 0, 0), 24 * 60 + 2)
        assert rt.profile.n_days(True) == 1
        assert rt.profile.mean(True, 12) == pytest.approx(0.6, abs=0.02)

    def test_daily_summary_has_the_comparison_fields(self):
        rt, coord, world = make_runtime()
        run(rt, datetime(2026, 11, 16, 6, 55), 15 * 60)
        s = rt.daily_summary()
        for key in ("gauge_midpeak_start", "pred_gauge_peak_start", "pred_gauge_peak_end",
                    "gauge_peak_start", "gauge_peak_end", "load_actual_kwh", "grid_kwh", "planner"):
            assert key in s, key
        assert s["load_actual_kwh"] == pytest.approx(0.6 * 14, abs=0.1)


class TestTopUpLifecycle:
    def test_abandoned_after_a_day_if_the_inverter_never_reports_full(self):
        rt, coord, world = make_runtime(planner="learned")
        world.values["sensor.gauge"] = (99, "%")
        world.values["sensor.grid"] = (1400, "W")               # still trickling in, never flips to 100
        run(rt, datetime(2026, 11, 20, 21, 0), 2)
        assert rt.topup_pending
        run(rt, datetime(2026, 11, 21, 20, 58), 5)              # Saturday, 24 h later
        assert not rt.topup_pending
        assert rt.decision.mode == MODE_DISCHARGE

    def test_picked_up_after_a_restart_later_that_evening(self):
        rt, coord, world = make_runtime(planner="learned")
        run(rt, datetime(2026, 11, 20, 22, 17), 2)              # first tick is well after 21:00
        assert rt.topup_pending

    def test_not_owed_again_once_done(self):
        rt, coord, world = make_runtime(planner="learned")
        run(rt, datetime(2026, 11, 20, 21, 0), 2)
        world.values["sensor.gauge"] = (100, "%")
        run(rt, datetime(2026, 11, 20, 23, 0), 2)
        assert not rt.topup_pending
        world.values["sensor.gauge"] = (90, "%")
        run(rt, datetime(2026, 11, 20, 23, 30), 2)
        assert not rt.topup_pending

    def test_survives_a_restart(self):
        rt, coord, world = make_runtime(planner="learned")
        run(rt, datetime(2026, 11, 20, 21, 0), 2)
        rt2, _, _ = make_runtime(planner="learned")
        rt2.load_state(rt.dump_state())
        assert rt2.topup_pending and rt2._topup_day == "2026-11-20"


class TestRobustness:
    def test_short_gauge_dropout_does_not_change_the_plan(self):
        rt, coord, world = make_runtime(planner="learned", **{CONF_FULL_CHARGE_MONTHS: "1"})
        world.values["sensor.gauge"] = (60, "%")
        world.values["sensor.grid"] = (2400, "W")                # untrained model: it is charging
        run(rt, datetime(2026, 11, 16, 22, 0), 3)
        before = list(fired(coord))
        world.values["sensor.gauge"] = ("unavailable", "%")
        run(rt, datetime(2026, 11, 16, 22, 3), 5)                # five minutes without a gauge
        assert fired(coord) == before

    def test_long_gauge_outage_at_night_falls_back_to_charging(self):
        rt, coord, world = make_runtime(planner="learned", **{CONF_FULL_CHARGE_MONTHS: "1"})
        world.values["sensor.gauge"] = (60, "%")
        run(rt, datetime(2026, 11, 16, 22, 0), 3)
        world.values["sensor.gauge"] = ("unavailable", "%")
        world.values["sensor.grid"] = (2400, "W")
        run(rt, datetime(2026, 11, 16, 22, 3), 30)
        assert fired(coord)[-1] == EVENT_CHARGE_START

    def test_no_command_while_sensors_are_still_coming_up(self):
        rt, coord, world = make_runtime(planner="learned")
        world.values["sensor.gauge"] = ("unavailable", "%")
        run(rt, datetime(2026, 11, 16, 22, 0), 5)                # just restarted, nothing readable yet
        assert fired(coord) == []

    def test_persistent_failure_returns_the_inverter_to_battery_once(self):
        rt, coord, world = make_runtime(planner="learned")
        coord._notify = MagicMock()
        world.values["sensor.grid"] = (2400, "W")
        run(rt, datetime(2026, 11, 16, 21, 0), 3)
        assert fired(coord)[-1] == EVENT_CHARGE_START
        coord.hass.states.get = MagicMock(side_effect=RuntimeError("boom"))
        t = datetime(2026, 11, 16, 21, 3)
        for i in range(30):
            rt._on_minute(t + timedelta(minutes=i))
        assert fired(coord).count(EVENT_CHARGE_STOP) == 1
        assert fired(coord)[-1] == EVENT_CHARGE_STOP

    def test_handing_back_to_classic_releases_a_charge(self):
        rt, coord, world = make_runtime(planner="learned")
        world.values["sensor.grid"] = (2400, "W")
        run(rt, datetime(2026, 11, 16, 21, 0), 3)
        assert fired(coord)[-1] == EVENT_CHARGE_START
        coord.entry.data[CONF_PLANNER] = "classic"
        run(rt, datetime(2026, 11, 16, 21, 3), 3)
        assert fired(coord)[-1] == EVENT_CHARGE_STOP
        assert fired(coord).count(EVENT_CHARGE_STOP) == 1
        assert rt._commanded is None

    def test_commanded_mode_survives_a_restart(self):
        rt, coord, world = make_runtime(planner="learned")
        now = datetime.now().replace(second=0, microsecond=0)
        rt._commanded, rt._commanded_phase, rt._commanded_at = MODE_HOLD, "night", now
        rt2, _, _ = make_runtime(planner="learned")
        rt2.load_state(rt.dump_state())
        assert rt2._commanded == MODE_HOLD and rt2._commanded_phase == "night"

    def test_marginal_readings_cannot_resend_forever(self):
        rt, coord, world = make_runtime(planner="learned")
        coord._notify = MagicMock()
        world.values["sensor.gauge"] = (50, "%")

        def step(i, t):                                       # alternates obeying and not obeying
            world.values["sensor.grid"] = (2400 if (i // 4) % 2 else 600, "W")

        run(rt, datetime(2026, 11, 16, 21, 0), 600, step)
        assert fired(coord).count(EVENT_CHARGE_START) <= 4

    def test_sensors_are_not_republished_every_minute(self):
        rt, coord, world = make_runtime(planner="classic")
        run(rt, datetime(2026, 11, 16, 10, 1), 30)
        assert coord.async_update_listeners.call_count <= 8
