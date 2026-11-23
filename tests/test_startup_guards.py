"""0.8.1: the false charge at the 0.8.0 restart (2026-11-22).

The battery sensor read a numeric 0.0 kWh for about 2 s while HA loaded, the first
calculation wanted a 4.1 kWh charge, and charge_start went out; the sensor then loaded
and the target-reached listener sent charge_stop. These tests cover the three guards:
a missing reading is not 0, a restart's first reading cannot start a charge on its own,
and weekdays-only is honoured by every refresh.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solarseed_peak_shaver.const import (
    EVENT_CHARGE_START,
    EVENT_CHARGE_STOP,
    STARTUP_CONFIRM_SECONDS,
)
from tests.test_learned_runtime import (
    CALL_LATER,
    SATURDAY_NOON,
    WEEKDAY_NOON,
    TestClassicRestart,
    fired,
    make_runtime,
)


def _classic(now=WEEKDAY_NOON, armed=False, battery=(1.0, "kWh"), **overrides):
    rt, coord, world = make_runtime(planner="classic", **overrides)
    TestClassicRestart()._solar(coord, world, now)
    coord._events_armed = armed
    coord.async_request_refresh = MagicMock()      # the timer's refresh is run by the test
    world.values["sensor.battery_soc"] = battery
    return rt, coord, world


def _calc(coord):
    return asyncio.run(coord._async_update_data())


def _battery_event(state):
    return SimpleNamespace(data={"new_state": SimpleNamespace(state=state)})


# --- an unavailable or unknown battery is missing, not 0 ----------------------------------


class TestMissingBattery:
    @pytest.mark.parametrize("armed", [False, True])
    @pytest.mark.parametrize("state", ["unavailable", "unknown", "", "nan", "none"])
    def test_no_calculation_and_no_event(self, state, armed):
        rt, coord, world = _classic(armed=armed, battery=(state, "kWh"))
        with patch(CALL_LATER) as later:
            with pytest.raises(Exception):               # UpdateFailed
                _calc(coord)
        assert fired(coord) == []
        assert coord.prediction_snapshots == []
        assert not later.called
        assert coord._charging_active is False

    def test_a_real_zero_is_still_a_reading(self):
        # an empty battery is a legitimate value; only the first look at it is deferred
        rt, coord, world = _classic(armed=True, battery=(0.0, "kWh"))
        _calc(coord)
        assert fired(coord) == [EVENT_CHARGE_START]

    def test_listeners_ignore_a_missing_reading(self):
        rt, coord, world = _classic(armed=True)
        coord._charging_active = True
        coord._daily_min_tracking = True
        coord._daily_min_soc = 6.0
        coord._on_battery_update(_battery_event("unavailable"))
        assert fired(coord) == []                        # no "target reached" off a 0
        assert coord._charging_active is True
        assert coord._daily_min_soc == 6.0               # not dragged to 0
        world.values["sensor.battery_soc"] = ("unknown", "kWh")
        coord._on_soc_checkpoint(datetime(2026, 11, 17, 17, 0))
        assert "peak_start" not in coord.actual_soc_checkpoints


# --- the restart rule: a charge needs a second look ---------------------------------------


class TestRestartRule:
    def test_first_calculation_that_wants_a_charge_only_schedules_a_second_look(self):
        rt, coord, world = _classic(battery=(1.0, "kWh"))
        with patch(CALL_LATER) as later:
            result = _calc(coord)
        assert result is not None and result["charge_needed_kwh"] > 0.5   # sensors still update
        assert fired(coord) == []
        assert coord._charging_active is False
        assert coord.prediction_snapshots == []          # the first reading is not the day's prediction
        later.assert_called_once()
        assert later.call_args.args[1] == STARTUP_CONFIRM_SECONDS
        assert later.call_args.args[2] == coord._on_startup_recheck

    def test_the_2026_11_22_incident_starts_nothing(self):
        # 0.0 kWh at the first calculation, 20 kWh two seconds later
        rt, coord, world = _classic(battery=(0.0, "kWh"))
        with patch(CALL_LATER) as later:
            _calc(coord)
            world.values["sensor.battery_soc"] = (20.0, "kWh")    # the sensor has loaded
            coord._on_battery_update(_battery_event("20.0"))
            later.call_args.args[2](WEEKDAY_NOON)                # the second look, a minute on
        _calc(coord)
        assert fired(coord) == []                        # no charge_start and no charge_stop
        assert coord._charging_active is False

    def test_the_second_look_starts_the_charge_if_it_is_still_needed(self):
        rt, coord, world = _classic(battery=(1.0, "kWh"))
        with patch(CALL_LATER) as later:
            _calc(coord)
            later.call_args.args[2](WEEKDAY_NOON)
        coord.async_request_refresh.assert_called_once()
        _calc(coord)
        assert fired(coord) == [EVENT_CHARGE_START]
        assert coord._charging_active is True
        assert len(coord.prediction_snapshots) == 1

    def test_the_second_look_never_releases_a_hold_but_later_calculations_do(self):
        rt, coord, world = _classic(battery=(1.0, "kWh"))
        with patch(CALL_LATER) as later:
            _calc(coord)
            world.values["sensor.battery_soc"] = (20.0, "kWh")
            later.call_args.args[2](WEEKDAY_NOON)
        _calc(coord)
        assert fired(coord) == []
        _calc(coord)
        assert fired(coord) == [EVENT_CHARGE_STOP]       # normal operation resumes

    def test_a_first_calculation_that_wants_nothing_schedules_nothing(self):
        rt, coord, world = _classic(battery=(20.0, "kWh"))
        with patch(CALL_LATER) as later:
            _calc(coord)
        assert not later.called
        assert fired(coord) == []

    def test_the_learned_planner_does_not_wait(self):
        rt, coord, world = make_runtime(planner="learned")
        TestClassicRestart()._solar(coord, world)
        coord._events_armed = False
        world.values["sensor.battery_soc"] = (1.0, "kWh")
        with patch(CALL_LATER) as later:
            _calc(coord)
        assert not later.called
        assert fired(coord) == []
        assert coord._events_armed is False              # a rollback to classic starts cautious

    def test_unloading_cancels_the_second_look(self):
        rt, coord, world = _classic(battery=(1.0, "kWh"))
        with patch(CALL_LATER) as later:
            _calc(coord)
        coord.remove_listeners()
        later.return_value.assert_called_once()
        assert coord._startup_recheck_unsub is None


# --- weekends -----------------------------------------------------------------------------


class TestWeekdaysOnly:
    def test_weekend_start_updates_the_sensors_and_fires_nothing(self):
        rt, coord, world = _classic(now=SATURDAY_NOON, battery=(1.0, "kWh"))
        with patch(CALL_LATER) as later:
            result = _calc(coord)
        assert result["charge_needed_kwh"] > 0.5          # computed for the sensors
        assert fired(coord) == []
        assert not later.called
        assert coord._charging_active is False
        assert coord.prediction_snapshots == []

    def test_weekend_recalculation_never_stops_a_charge_or_hold(self):
        rt, coord, world = _classic(now=SATURDAY_NOON, armed=True, battery=(20.0, "kWh"))
        _calc(coord)                                     # the Recalculate button on a Saturday
        assert fired(coord) == []

    def test_weekend_start_does_not_restrict_monday(self):
        rt, coord, world = _classic(now=SATURDAY_NOON, battery=(20.0, "kWh"))
        _calc(coord)
        coord._now = lambda: WEEKDAY_NOON
        _calc(coord)
        assert fired(coord) == [EVENT_CHARGE_STOP]        # not a "first calculation" any more

    def test_every_day_counts_when_weekdays_only_is_off(self):
        rt, coord, world = _classic(now=SATURDAY_NOON, battery=(1.0, "kWh"), weekdays_only=False)
        with patch(CALL_LATER) as later:
            _calc(coord)
        later.assert_called_once()
