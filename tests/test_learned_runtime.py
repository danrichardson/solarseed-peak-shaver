"""Tests for the HA glue around the learned planner (HA mocked)."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
    STARTUP_CONFIRM_SECONDS,
)
from custom_components.solarseed_peak_shaver.learned_runtime import (
    LearnedRuntime,
    is_tou_day,
    mode_matches,
)
from custom_components.solarseed_peak_shaver.planner import MODE_CHARGE, MODE_DISCHARGE, MODE_HOLD

CALL_LATER = "custom_components.solarseed_peak_shaver.coordinator.async_call_later"

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
        self.tick = 0               # live data wobbles; a constant house load reads as frozen
        self.frozen = False

    def get(self, entity_id):
        if entity_id not in self.values:
            return None
        val, unit = self.values[entity_id]
        if entity_id == "sensor.load" and unit == "W" and not self.frozen and isinstance(val, (int, float)):
            val = val + self.tick % 2
        return SimpleNamespace(state=str(val), attributes={"unit_of_measurement": unit})


def make_runtime(planner="classic", **overrides):
    cfg = dict(ENTITIES)
    cfg[CONF_PLANNER] = planner
    cfg.update(overrides)
    coord = _make_coordinator(config_overrides=cfg)
    world = World()
    coord.hass.states.get = world.get
    coord.async_update_listeners = MagicMock()
    rt = LearnedRuntime(coord.hass, coord)
    rt._test_world = world
    coord.learned = rt
    return rt, coord, world


def fired(coord):
    return [c.args[0] for c in coord.hass.bus.async_fire.call_args_list]


def run(rt, start: datetime, minutes: int, step=None):
    t = start
    world = getattr(rt, "_test_world", None)
    for i in range(minutes):
        if step:
            step(i, t)
        if world is not None:
            world.tick += 1
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

    @pytest.mark.parametrize("bad", ["nan", "NaN", "inf", "-inf", "", "unknown"])
    def test_a_non_finite_reading_is_missing(self, bad):
        # 0.9.2: "nan" parsed as a float and crashed the mid-peak rule (int(nan)) every tick
        rt, coord, world = make_runtime(planner="learned")
        world.values["sensor.gauge"] = (bad, "%")
        world.values["sensor.grid"] = (bad, "W")
        assert rt.read_gauge() is None and rt._power_kw("sensor.grid") is None
        run(rt, datetime(2026, 11, 18, 12, 0), 20)          # mid-peak, past the start-up grace
        assert rt._tick_fails == 0
        assert rt.decision.reason == "Battery gauge unavailable: leaving the inverter on battery."


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
        run(rt, datetime(2026, 11, 16, 20, 58), 2)          # still peak, inverter seen on battery
        assert fired(coord) == []                           # already doing what is wanted
        world.values["sensor.grid"] = (2400, "W")
        run(rt, datetime(2026, 11, 16, 21, 0), 30)          # night before a TOU day, November
        assert fired(coord) == [EVENT_CHARGE_START]

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
        assert fired(coord) == [EVENT_CHARGE_STOP]          # the hold seen at 06:58 is kept, then released

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
        run(rt, datetime(2026, 11, 16, 20, 59), 1)
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
        run(rt, datetime(2026, 11, 20, 20, 58), 1)
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


WEEKDAY_NOON = datetime(2026, 11, 17, 12, 0)     # a Tuesday
SATURDAY_NOON = datetime(2026, 11, 21, 12, 0)


class TestClassicRestart:
    def _solar(self, coord, world, now=WEEKDAY_NOON):
        solar = MagicMock()
        solar.state = "5.0"
        solar.attributes = {"detailedHourly": [{"period_start": "2026-11-16T12:00:00", "pv_estimate": 1.0}]}
        base_get = world.get
        coord.hass.states.get = lambda e: solar if e == "sensor.solcast_today" else base_get(e)
        coord._now = lambda: now                    # the classic planner reads the clock

    def test_first_calculation_after_start_fires_nothing(self):
        import asyncio

        rt, coord, world = make_runtime(planner="classic")
        self._solar(coord, world)
        coord._events_armed = False                              # as after a restart
        world.values["sensor.battery_soc"] = (20.0, "kWh")       # classic would fire charge_stop
        assert asyncio.run(coord._async_update_data()) is not None
        assert fired(coord) == []                                # a restart leaves a hold alone
        asyncio.run(coord._async_update_data())
        assert fired(coord) == [EVENT_CHARGE_STOP]               # later calculations act as before


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
        run(rt, datetime(2026, 11, 16, 20, 59), 1)
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
        run(rt, datetime(2026, 11, 16, 20, 59), 1)
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


def _trained_runtime(planner="learned", **overrides):
    from tests.test_planner import trained

    rt, coord, world = make_runtime(planner=planner, **overrides)
    rt.learner, rt.profile = trained()
    return rt, coord, world


class TestStaleness:
    """ROADMAP item 4: readings that stop changing count as missing."""

    def _freeze_midday(self, planner="classic", **overrides):
        rt, coord, world = make_runtime(planner=planner, **overrides)
        coord._notify = MagicMock()

        def falling(i, t):
            world.values["sensor.gauge"] = (80 - i // 15, "%")

        run(rt, datetime(2026, 11, 16, 9, 0), 60, falling)
        world.frozen = True                                    # the data path stops, values stay put
        return rt, coord, world

    def test_frozen_readings_trip_after_the_limit_and_alert_once(self):
        rt, coord, world = self._freeze_midday()
        run(rt, datetime(2026, 11, 16, 10, 0), 19)
        assert not rt.data_stale
        run(rt, datetime(2026, 11, 16, 10, 19), 40)
        assert rt.data_stale
        titles = [c.args[0] for c in coord._notify.call_args_list]
        assert titles.count("Solarseed - battery data frozen") == 1
        assert "frozen" in rt.decision.reason

    def test_nothing_is_learned_from_frozen_readings(self):
        rt, coord, world = self._freeze_midday()
        run(rt, datetime(2026, 11, 16, 10, 0), 21)
        learned = sum(rt.learner.discharge.p)
        run(rt, datetime(2026, 11, 16, 10, 21), 60)
        assert sum(rt.learner.discharge.p) == pytest.approx(learned)

    def test_recovery_clears_and_says_so(self):
        rt, coord, world = self._freeze_midday()
        run(rt, datetime(2026, 11, 16, 10, 0), 30)
        assert rt.data_stale
        world.frozen = False
        run(rt, datetime(2026, 11, 16, 10, 30), 2)
        assert not rt.data_stale
        titles = [c.args[0] for c in coord._notify.call_args_list]
        assert "Solarseed - battery data back" in titles

    def test_a_still_gauge_alone_is_not_stale(self):
        rt, coord, world = make_runtime()
        world.values["sensor.gauge"] = (100, "%")              # overnight hold: gauge still for hours
        run(rt, datetime(2026, 11, 16, 22, 0), 180)
        assert not rt.data_stale

    # --- an idle system is not a frozen one (found on the owner's AC500, 2026-11-23) ---------

    def _idle_night(self, **overrides):
        """Full bank, nothing moving: every reading exactly still, as the real sensors sit."""
        rt, coord, world = make_runtime(**overrides)
        coord._notify = MagicMock()
        world.frozen = True                                    # no wobble: readings are exactly constant
        world.values["sensor.gauge"] = (100, "%")
        world.values["sensor.load"] = (0, "W")
        return rt, coord, world

    @staticmethod
    def _frozen_alerts(coord):
        return [c for c in coord._notify.call_args_list if c.args[0] == "Solarseed - battery data frozen"]

    def test_an_idle_full_bank_is_not_frozen_however_long(self):
        rt, coord, world = self._idle_night()
        run(rt, datetime(2026, 11, 23, 0, 5), 400)             # nearly seven hours of nothing moving
        assert not rt.data_stale
        assert self._frozen_alerts(coord) == []
        s = rt.daily_summary()
        assert s["stale_minutes"] == 0 and s["stale_longest_min"] == 0

    def test_an_idle_night_does_not_fall_back_to_charging(self):
        """The cost of the false alarm: frozen means night charges to full, idle or not."""
        rt, coord, world = _trained_runtime(planner="learned")
        world.values["sensor.gauge"] = (90, "%")               # March: sized night, plenty on board
        run(rt, datetime(2026, 3, 16, 22, 0), 3)
        assert rt.decision.mode in (MODE_DISCHARGE, MODE_HOLD)
        world.frozen = True                                    # exactly still...
        world.values["sensor.load"] = (0, "W")                 # ...and nothing moving
        run(rt, datetime(2026, 3, 16, 22, 3), 60)
        assert not rt.data_stale
        assert rt.decision.mode in (MODE_DISCHARGE, MODE_HOLD)
        assert EVENT_CHARGE_START not in fired(coord)

    @pytest.mark.parametrize("watts", [0, 5, 9])
    def test_a_few_watts_still_counts_as_idle(self, watts):
        rt, coord, world = self._idle_night()
        world.values["sensor.load"] = (watts, "W")
        run(rt, datetime(2026, 11, 23, 0, 5), 90)
        assert not rt.data_stale

    @pytest.mark.parametrize("watts", [50, 600])
    def test_power_that_is_flowing_but_never_changes_is_frozen(self, watts):
        rt, coord, world = self._idle_night()
        world.values["sensor.load"] = (watts, "W")
        run(rt, datetime(2026, 11, 23, 0, 5), 30)
        assert rt.data_stale
        assert len(self._frozen_alerts(coord)) == 1

    def test_idle_is_judged_in_kw_too(self):
        rt, coord, world = self._idle_night()
        world.values["sensor.load"] = (0.0, "kW")
        run(rt, datetime(2026, 11, 23, 0, 5), 90)
        assert not rt.data_stale
        world.values["sensor.load"] = (0.5, "kW")              # 500 W stuck
        run(rt, datetime(2026, 11, 23, 1, 35), 30)
        assert rt.data_stale

    def test_one_unreadable_power_sensor_is_not_idle(self):
        rt, coord, world = self._idle_night()
        world.values["sensor.grid"] = ("unavailable", "W")     # cannot say nothing is moving
        run(rt, datetime(2026, 11, 23, 0, 5), 40)
        assert rt.data_stale

    def test_a_feed_stuck_after_the_idle_stretch_is_caught_from_when_power_started(self):
        rt, coord, world = self._idle_night()
        t = run(rt, datetime(2026, 11, 23, 3, 0), 120)         # two idle hours: fine
        assert not rt.data_stale
        world.values["sensor.load"] = (600, "W")               # the house wakes up, the feed sticks
        t = run(rt, t, 15)
        assert not rt.data_stale
        run(rt, t, 10)
        assert rt.data_stale
        assert rt.daily_summary()["stale_longest_min"] < 35    # not counted from the idle hours before

    def test_going_idle_after_a_real_freeze_ends_it_for_good(self):
        rt, coord, world = self._freeze_midday()
        t = run(rt, datetime(2026, 11, 16, 10, 0), 30)
        assert rt.data_stale
        world.values["sensor.load"] = (0, "W")                 # everything stops: now just idle
        t = run(rt, t, 2)
        assert not rt.data_stale
        run(rt, t, 60)
        assert not rt.data_stale

    def test_zero_turns_the_check_off(self):
        from custom_components.solarseed_peak_shaver.const import CONF_STALE_MINUTES

        rt, coord, world = self._freeze_midday(**{CONF_STALE_MINUTES: 0})
        run(rt, datetime(2026, 11, 16, 10, 0), 120)
        assert not rt.data_stale

    def test_needs_a_power_sensor(self):
        rt, coord, world = make_runtime(**{CONF_LOAD_POWER_ENTITY: "", CONF_GRID_POWER_ENTITY: ""})
        world.frozen = True
        run(rt, datetime(2026, 11, 16, 22, 0), 60)
        assert not rt.data_stale

    def test_stale_minutes_go_into_the_daily_summary(self):
        rt, coord, world = self._freeze_midday()
        run(rt, datetime(2026, 11, 16, 10, 0), 50)
        assert rt.daily_summary()["stale_minutes"] == pytest.approx(31, abs=1)

    def test_frozen_gauge_is_not_bridged_and_night_falls_back_to_charging(self):
        rt, coord, world = _trained_runtime(planner="learned")
        world.values["sensor.gauge"] = (90, "%")               # March: sized night, plenty on board
        run(rt, datetime(2026, 3, 16, 22, 0), 3)
        assert rt.decision.mode in (MODE_DISCHARGE, MODE_HOLD)
        world.frozen = True
        run(rt, datetime(2026, 3, 16, 22, 3), 30)
        assert rt.data_stale
        assert rt.decision.mode == MODE_CHARGE and "frozen" in rt.decision.reason
        assert fired(coord)[-1] == EVENT_CHARGE_START

    def test_classic_never_stops_while_frozen(self):
        import asyncio

        rt, coord, world = make_runtime(planner="classic")
        TestClassicRestart()._solar(coord, world)
        rt.data_stale = True
        world.values["sensor.battery_soc"] = (20.0, "kWh")     # classic would fire charge_stop
        asyncio.run(coord._async_update_data())
        assert fired(coord) == []
        world.values["sensor.battery_soc"] = (1.0, "kWh")      # a charge may still start
        asyncio.run(coord._async_update_data())
        assert fired(coord) == [EVENT_CHARGE_START]


class TestFirstTickAfterStart:
    """ROADMAP item 5: a restart never releases a hold or stops a charge."""

    def test_classic_first_calculation_may_start_a_charge_after_a_second_look(self):
        import asyncio

        rt, coord, world = make_runtime(planner="classic")
        TestClassicRestart()._solar(coord, world)
        coord._events_armed = False
        coord.async_request_refresh = MagicMock()
        world.values["sensor.battery_soc"] = (1.0, "kWh")
        with patch(CALL_LATER) as later:
            asyncio.run(coord._async_update_data())
            assert fired(coord) == []                            # the first reading never acts
            assert later.call_args.args[1] == STARTUP_CONFIRM_SECONDS
            later.call_args.args[2](WEEKDAY_NOON)                # the timer fires
        asyncio.run(coord._async_update_data())                  # the refresh it asked for
        assert fired(coord) == [EVENT_CHARGE_START]

    def test_a_hold_seen_after_a_restart_is_kept(self):
        rt, coord, world = _trained_runtime()
        world.values["sensor.gauge"] = (90, "%")               # more than tomorrow needs,
        world.values["sensor.grid"] = (600, "W")               # but the inverter is holding
        run(rt, datetime(2026, 3, 16, 23, 0), 30)
        assert rt.decision.mode == MODE_HOLD
        assert fired(coord) == []

    def test_on_battery_after_a_restart_it_carries_on(self):
        rt, coord, world = _trained_runtime()
        world.values["sensor.gauge"] = (90, "%")
        world.values["sensor.grid"] = (0, "W")
        run(rt, datetime(2026, 3, 16, 23, 0), 30)
        assert rt.decision.mode == MODE_DISCHARGE
        assert fired(coord) == []

    def test_unreadable_mode_is_adopted_not_fired(self):
        rt, coord, world = _trained_runtime()
        world.values["sensor.gauge"] = (90, "%")
        world.values["sensor.load"] = (50, "W")                # too little load to tell the mode
        world.values["sensor.grid"] = (50, "W")
        run(rt, datetime(2026, 3, 16, 23, 0), 30)
        assert fired(coord) == []
        assert rt._commanded == MODE_DISCHARGE

    def test_a_charge_still_starts_on_the_first_tick(self):
        rt, coord, world = make_runtime(planner="learned")
        run(rt, datetime(2026, 11, 16, 21, 30), 1)             # full-charge month, inverter on battery
        assert fired(coord) == [EVENT_CHARGE_START]

    def test_a_restored_command_is_kept(self):
        rt, coord, world = _trained_runtime()
        now = datetime.now().replace(second=0, microsecond=0)
        rt._commanded, rt._commanded_phase, rt._commanded_at = MODE_HOLD, "night", now
        rt2, coord2, world2 = _trained_runtime()
        rt2.load_state(rt.dump_state())
        world2.values["sensor.gauge"] = (90, "%")
        world2.values["sensor.grid"] = (0, "W")                # readings alone would say discharge
        run(rt2, datetime(2026, 3, 16, 23, 0), 5)
        assert rt2._commanded == MODE_HOLD
        assert fired(coord2) == []

    def test_takeover_after_classic_starts_from_the_inverter_mode(self):
        rt, coord, world = make_runtime(planner="learned")
        run(rt, datetime(2026, 11, 16, 20, 59), 1)
        world.values["sensor.grid"] = (2400, "W")
        run(rt, datetime(2026, 11, 16, 21, 0), 3)
        coord.entry.data[CONF_PLANNER] = "classic"
        run(rt, datetime(2026, 11, 16, 21, 3), 2)              # releases (handover to classic)
        assert rt._first_act
        world.values["sensor.grid"] = (600, "W")
        world.values["sensor.gauge"] = (100, "%")
        coord.entry.data[CONF_PLANNER] = "learned"
        n = len(fired(coord))
        run(rt, datetime(2026, 11, 16, 23, 0), 5)              # inverter holding on a full bank
        assert fired(coord)[n:] == []

    def test_bank_full_survives_a_restart(self):
        rt, coord, world = make_runtime(planner="learned")
        world.values["sensor.gauge"] = (100, "%")
        run(rt, datetime(2026, 11, 16, 23, 0), 2)
        assert rt.bank_full
        rt2, _, _ = make_runtime(planner="learned")
        rt2.load_state(rt.dump_state())
        assert rt2.bank_full


class TestHandoverRecord:
    def test_the_first_touch_of_the_floor_in_peak_is_recorded(self):
        rt, coord, world = make_runtime()

        def falling(i, t):
            world.values["sensor.gauge"] = (max(3, 12 - i // 10), "%")

        run(rt, datetime(2026, 11, 16, 18, 0), 120, falling)
        s = rt.daily_summary()
        assert s["handover_at"] == "19:30" and s["handover_period"] == "peak"
        assert s["handover_cost_kwh"] > 0

    def test_not_on_a_weekend(self):
        rt, coord, world = make_runtime()
        world.values["sensor.gauge"] = (3, "%")
        run(rt, datetime(2026, 11, 21, 18, 0), 5)
        assert "handover_at" not in rt.daily_summary()


PACK_IDS = ["sensor.v1_current", "sensor.v2_current"]


def _pack_runtime(**overrides):
    from custom_components.solarseed_peak_shaver.const import CONF_PACK_CURRENT_ENTITIES

    cfg = {CONF_PACK_CURRENT_ENTITIES: list(PACK_IDS)}
    cfg.update(overrides)
    rt, coord, world = make_runtime(**cfg)
    world.values.update({
        "sensor.v1_current": (-20.0, "A"), "sensor.v2_current": (-22.0, "A"),
        "sensor.v1_voltage": (53.9, "V"), "sensor.v2_voltage": (54.1, "V"),
        "sensor.v1_battery": (61, "%"),
    })
    return rt, coord, world


def _anchor(rt, world, t):
    world.values["sensor.gauge"] = (99, "%")
    run(rt, t, 1)
    world.values["sensor.gauge"] = (100, "%")
    run(rt, t + timedelta(minutes=1), 1)


class TestPacksInRuntime:
    """ROADMAP items 1 and 2, through the minute tick."""

    def test_nothing_without_pack_sensors(self):
        rt, coord, world = make_runtime()
        run(rt, datetime(2026, 11, 21, 12, 0), 5)
        assert rt.pack_tracker() is None
        assert rt.dump_state()["packs"] == {}

    def test_counts_from_the_full_anchor(self):
        rt, coord, world = _pack_runtime()
        t = datetime(2026, 11, 21, 12, 0)
        _anchor(rt, world, t)
        world.values["sensor.gauge"] = (95, "%")
        run(rt, t + timedelta(minutes=2), 60)
        tr = rt.pack_tracker()
        assert tr.estimate_pct("sensor.v1_current") == pytest.approx(80.0, abs=0.5)
        assert tr.estimate_pct("sensor.v2_current") == pytest.approx(78.0, abs=0.5)

    def test_sign_option_for_packs_that_report_discharge_as_positive(self):
        from custom_components.solarseed_peak_shaver.const import CONF_PACK_CURRENT_CHARGE_POSITIVE

        rt, coord, world = _pack_runtime(**{CONF_PACK_CURRENT_CHARGE_POSITIVE: False})
        world.values["sensor.v1_current"] = (20.0, "A")
        assert rt.pack_current("sensor.v1_current") == -20.0

    def test_milliamps(self):
        rt, coord, world = _pack_runtime()
        world.values["sensor.v1_current"] = (-1500, "mA")
        assert rt.pack_current("sensor.v1_current") == pytest.approx(-1.5)

    def test_bus_voltage_from_the_packs_or_the_option(self):
        from custom_components.solarseed_peak_shaver.const import CONF_BUS_VOLTAGE_ENTITY

        rt, coord, world = _pack_runtime()
        assert rt.bus_voltage() == pytest.approx(54.0)
        rt2, coord2, world2 = _pack_runtime(**{CONF_BUS_VOLTAGE_ENTITY: "sensor.bus"})
        world2.values["sensor.bus"] = (52.2, "V")
        assert rt2.bus_voltage() == pytest.approx(52.2)

    def test_sibling_lookup(self):
        rt, coord, world = _pack_runtime()
        assert rt.sibling("sensor.v1_current", ("_battery", "_soc")) == "sensor.v1_battery"
        assert rt.sibling("sensor.v2_current", ("_battery", "_soc")) is None
        assert rt.sibling("sensor.odd_name", ("_voltage",)) is None

    def test_a_capacity_run_through_the_runtime(self):
        rt, coord, world = _pack_runtime()
        t = datetime(2026, 11, 21, 12, 0)
        _anchor(rt, world, t)
        v = [54.2]

        def falling(i, now):
            v[0] -= 0.01
            world.values["sensor.v1_voltage"] = (v[0], "V")
            world.values["sensor.v2_voltage"] = (v[0], "V")
            world.values["sensor.gauge"] = (max(4, 99 - i // 4), "%")
            world.values["sensor.load"] = (1500, "W")

        run(rt, t + timedelta(minutes=2), 400, falling)
        pts = rt.pack_tracker().points
        assert len(pts) == 1
        assert pts[0]["ah"]["sensor.v1_current"] == pytest.approx(50.0, abs=0.5)
        assert pts[0]["ac_kwh"] == pytest.approx(3.75, abs=0.1)        # 1.5 kW for 2.5 h

    def test_pack_state_survives_a_restart(self):
        rt, coord, world = _pack_runtime()
        t = datetime(2026, 11, 21, 12, 0)
        _anchor(rt, world, t)
        run(rt, t + timedelta(minutes=2), 30)
        rt2, coord2, world2 = _pack_runtime()
        rt2.load_state(rt.dump_state())
        assert rt2.pack_tracker().anchor_at == rt.pack_tracker().anchor_at
        assert rt2.pack_tracker().out_ah["sensor.v1_current"] == pytest.approx(10.0, abs=0.1)

    def test_a_pack_failure_never_stops_the_planner(self):
        rt, coord, world = _pack_runtime(planner="learned")
        rt.pack_tracker = MagicMock(side_effect=RuntimeError("boom"))
        run(rt, datetime(2026, 11, 16, 21, 0), 3)
        assert rt.decision is not None and rt._tick_fails == 0
        assert fired(coord)[-1] == EVENT_CHARGE_START


class TestPackSensors:
    def _sensors(self, rt, coord):
        from custom_components.solarseed_peak_shaver.sensor import PACK_CAPACITY, PACK_SOC, PackSensor

        entry = coord.entry
        return (PackSensor(coord, entry, "sensor.v1_current", PACK_SOC),
                PackSensor(coord, entry, "sensor.v1_current", PACK_CAPACITY))

    def test_names_ids_and_values(self):
        rt, coord, world = _pack_runtime()
        soc, cap = self._sensors(rt, coord)
        assert soc._attr_name == "V1 Charge Estimate"
        assert cap._attr_name == "V1 Ah Between 53.0 And 51.5 V"
        assert soc._attr_unique_id == "test_entry_id_pack_v1_current_charge_estimate"
        assert soc.native_value is None and cap.native_value is None      # no anchor, no run yet
        t = datetime(2026, 11, 21, 12, 0)
        _anchor(rt, world, t)
        world.values["sensor.gauge"] = (95, "%")
        run(rt, t + timedelta(minutes=2), 30)
        assert soc.native_value == pytest.approx(90.0, abs=0.5)
        attrs = soc.extra_state_attributes
        assert attrs["bms_percent"] == 61.0 and attrs["bms_entity"] == "sensor.v1_battery"
        assert attrs["ah_out_since_full"] == pytest.approx(10.0, abs=0.1)
        assert cap.extra_state_attributes["run"]["state"] == "armed"

    def test_setup_adds_two_sensors_per_pack(self):
        import asyncio

        from custom_components.solarseed_peak_shaver import sensor as sensor_mod
        from custom_components.solarseed_peak_shaver.const import DOMAIN

        rt, coord, world = _pack_runtime()
        coord.hass.data = {DOMAIN: {coord.entry.entry_id: coord}}
        added = []
        asyncio.run(sensor_mod.async_setup_entry(coord.hass, coord.entry, added.extend))
        packs = [e for e in added if isinstance(e, sensor_mod.PackSensor)]
        assert len(packs) == 4

    def test_friendly_name_is_used_for_the_label(self):
        from custom_components.solarseed_peak_shaver.sensor import pack_label

        rt, coord, world = _pack_runtime()
        coord.hass.states.get = lambda e: SimpleNamespace(state="1", attributes={"friendly_name": "Vatrer 3 Current"})
        assert pack_label(coord.hass, "sensor.whatever_current") == "Vatrer 3"
