"""The setup check (0.9.3): missing sensors, a forecast without hourly detail and events no
automation listens to become repair issues and one log line, never silence, never spam,
never a failed setup."""
from __future__ import annotations

import asyncio
import logging
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solarseed_peak_shaver.const import (
    CONF_GAUGE_ENTITY,
    CONF_GRID_POWER_ENTITY,
    CONF_LOAD_POWER_ENTITY,
    CONF_PLANNER,
    CONF_PV_POWER_ENTITY,
    CONF_SEASONAL_PRESERVATION,
    CONF_SOLAR_FORECAST_TOMORROW_ENTITY,
    EVENT_CHARGE_START,
    EVENT_CHARGE_STOP,
    EVENT_PRESERVE_START,
)
from custom_components.solarseed_peak_shaver.setup_check import (
    ISSUE_FORECAST_SHAPE,
    ISSUE_MISSING_SENSORS,
    ISSUE_NO_AUTOMATIONS,
    ISSUES,
    SetupCheck,
    events_needed,
    find_problems,
)
from tests.test_coordinator import _make_coordinator

ALL_EVENTS = {EVENT_CHARGE_START: 1, EVENT_CHARGE_STOP: 1, EVENT_PRESERVE_START: 1}
SOLCAST = {"detailedHourly": [{"period_start": "2026-11-24T12:00:00", "pv_estimate": 1.0}]}
LEARNED = {CONF_PLANNER: "learned", CONF_GAUGE_ENTITY: "sensor.gauge",
           CONF_LOAD_POWER_ENTITY: "sensor.load", CONF_GRID_POWER_ENTITY: "sensor.grid"}


def states(**overrides):
    """A healthy install's states; a value of None removes the entity."""
    s = {
        "sensor.battery_soc": SimpleNamespace(state="11.7", attributes={}),
        "sensor.solcast_today": SimpleNamespace(state="12.3", attributes=dict(SOLCAST)),
        "sensor.gauge": SimpleNamespace(state="50", attributes={}),
        "sensor.load": SimpleNamespace(state="600", attributes={}),
        "sensor.grid": SimpleNamespace(state="0", attributes={}),
        "sensor.pv": SimpleNamespace(state="0", attributes={}),
    }
    for key, value in overrides.items():
        entity = "sensor." + key
        if value is None:
            s.pop(entity, None)
        else:
            s[entity] = value
    return s.get


def coord(**cfg):
    return _make_coordinator(config_overrides=cfg)


# --- find_problems ---------------------------------------------------------------------


def test_a_healthy_learned_install_has_no_problems():
    assert find_problems(coord(**LEARNED), states(), ALL_EVENTS) == {}


def test_a_healthy_classic_install_without_learned_sensors_has_none_either():
    # an entry from before 0.9.3: classic, no power sensors; nothing to report
    assert find_problems(coord(), states(), ALL_EVENTS) == {}


def test_a_sensor_that_does_not_exist_is_named_with_its_role():
    found = find_problems(coord(**LEARNED), states(load=None), ALL_EVENTS)
    assert list(found) == [ISSUE_MISSING_SENSORS]
    assert "House load power: sensor.load does not exist" in found[ISSUE_MISSING_SENSORS]["sensors"]


@pytest.mark.parametrize("state", ["unavailable", "unknown", ""])
def test_a_sensor_that_exists_without_a_reading_is_not_a_setup_problem(state):
    # startup, night, a flaky link: the planners treat it as missing already
    reading = SimpleNamespace(state=state, attributes={})
    assert find_problems(coord(**LEARNED), states(load=reading, solcast_today=reading,
                                                  battery_soc=reading), ALL_EVENTS) == {}


def test_learned_in_control_without_load_and_grid_says_so():
    found = find_problems(coord(**{CONF_PLANNER: "learned"}), states(), ALL_EVENTS)
    text = found[ISSUE_MISSING_SENSORS]["sensors"]
    assert "House load power: not set" in text and "Grid power into the inverter: not set" in text


def test_an_optional_sensor_left_empty_is_not_missing():
    assert find_problems(coord(**{**LEARNED, CONF_PV_POWER_ENTITY: ""}), states(pv=None), ALL_EVENTS) == {}


def test_a_typed_tomorrow_forecast_that_does_not_exist_is_missing():
    found = find_problems(coord(**{CONF_SOLAR_FORECAST_TOMORROW_ENTITY: "sensor.solcast_tomorow"}),
                          states(), ALL_EVENTS)
    assert "sensor.solcast_tomorow does not exist" in found[ISSUE_MISSING_SENSORS]["sensors"]


def test_a_forecast_without_hourly_detail_is_reported():
    plain = SimpleNamespace(state="12.3", attributes={"unit_of_measurement": "kWh"})   # Forecast.Solar-like
    found = find_problems(coord(), states(solcast_today=plain), ALL_EVENTS)
    assert found == {ISSUE_FORECAST_SHAPE: {"entities": "sensor.solcast_today"}}


def test_a_forecast_that_is_unavailable_is_not_judged_by_its_attributes():
    found = find_problems(coord(), states(solcast_today=SimpleNamespace(state="unavailable", attributes={})),
                          ALL_EVENTS)
    assert found == {}


def test_events_nobody_listens_to_are_listed():
    found = find_problems(coord(**LEARNED), states(), {EVENT_CHARGE_START: 1})
    assert found == {ISSUE_NO_AUTOMATIONS: {"events": f"- {EVENT_CHARGE_STOP}\n- {EVENT_PRESERVE_START}"}}


def test_no_listener_counts_means_no_guess():
    assert find_problems(coord(**LEARNED), states(), None) == {}


def test_a_listen_to_everything_subscriber_is_not_an_automation_for_these_events():
    # The bus counts a match-all listener (the recorder, the logbook, an "all events"
    # websocket subscription) under "*", never under the event; a count there says nothing
    # about whether the inverter will move, so the events still go unheard.
    found = find_problems(coord(**LEARNED), states(), {"*": 4, EVENT_CHARGE_START: 1})
    assert found == {ISSUE_NO_AUTOMATIONS: {"events": f"- {EVENT_CHARGE_STOP}\n- {EVENT_PRESERVE_START}"}}
    # and the count is the number of listeners, so a disabled automation (0) is unheard too
    assert find_problems(coord(**LEARNED), states(), {**ALL_EVENTS, EVENT_CHARGE_STOP: 0}) == {
        ISSUE_NO_AUTOMATIONS: {"events": f"- {EVENT_CHARGE_STOP}"}}


def test_classic_without_its_hold_needs_only_start_and_stop():
    assert events_needed(coord(**{CONF_SEASONAL_PRESERVATION: False})) == (EVENT_CHARGE_START, EVENT_CHARGE_STOP)
    assert len(events_needed(coord(**{**LEARNED, CONF_SEASONAL_PRESERVATION: False}))) == 3
    found = find_problems(coord(**{CONF_SEASONAL_PRESERVATION: False}), states(),
                          {EVENT_CHARGE_START: 2, EVENT_CHARGE_STOP: 1})
    assert found == {}


# --- SetupCheck: issues and log lines --------------------------------------------------


def make_check(cfg=None, get=None, listeners=None, state="running"):
    c = coord(**(cfg or LEARNED))
    hass = MagicMock()
    hass.state = state
    hass.states.get = get or states()
    hass.bus.async_listeners = MagicMock(return_value=dict(ALL_EVENTS if listeners is None else listeners))
    c.hass = hass
    return SetupCheck(hass, c, "entry1"), hass


@pytest.fixture
def ir():
    reg = sys.modules["homeassistant.helpers.issue_registry"]
    reg.async_create_issue.reset_mock()
    reg.async_delete_issue.reset_mock()
    return reg


def test_nothing_is_judged_before_home_assistant_has_started(ir):
    check, hass = make_check(get=states(load=None), listeners={}, state="starting")
    assert check.run() == {}
    ir.async_create_issue.assert_not_called()
    ir.async_delete_issue.assert_not_called()


def test_a_problem_is_one_issue_and_one_log_line_until_it_changes(ir, caplog):
    check, hass = make_check(get=states(load=None))
    with caplog.at_level(logging.WARNING):
        for _ in range(6):                                  # an hour of checks
            check._on_interval()
    assert ir.async_create_issue.call_count == 1
    args, kwargs = ir.async_create_issue.call_args
    assert args[2] == "missing_sensors_entry1"
    assert kwargs["translation_key"] == ISSUE_MISSING_SENSORS and kwargs["is_fixable"] is False
    assert "sensor.load" in kwargs["translation_placeholders"]["sensors"]
    assert [r for r in caplog.records if "Setup problem" in r.message][0].levelno == logging.WARNING
    assert len([r for r in caplog.records if "Setup problem" in r.message]) == 1
    # the first run cleared the issues that are not problems (left from before a restart)
    deleted = {c.args[2] for c in ir.async_delete_issue.call_args_list}
    assert deleted == {"forecast_without_detail_entry1", "no_automations_entry1"}


def test_a_fixed_problem_clears_its_issue_with_one_info_line(ir, caplog):
    check, hass = make_check(get=states(load=None))
    check.run()
    ir.async_delete_issue.reset_mock()
    hass.states.get = states()
    with caplog.at_level(logging.INFO):
        check.run()
        check.run()
    ir.async_delete_issue.assert_called_once()
    assert ir.async_delete_issue.call_args.args[2] == "missing_sensors_entry1"
    assert len([r for r in caplog.records if "resolved" in r.message]) == 1


def test_a_changed_problem_updates_the_issue(ir):
    check, hass = make_check(get=states(load=None))
    check.run()
    hass.states.get = states(load=None, grid=None)
    check.run()
    assert ir.async_create_issue.call_count == 2
    assert "sensor.grid" in ir.async_create_issue.call_args.kwargs["translation_placeholders"]["sensors"]


def test_missing_automations_are_an_issue(ir):
    check, hass = make_check(listeners={EVENT_CHARGE_START: 1, EVENT_CHARGE_STOP: 1})
    assert list(check.run()) == [ISSUE_NO_AUTOMATIONS]
    assert ir.async_create_issue.call_args.kwargs["translation_placeholders"] == {
        "events": f"- {EVENT_PRESERVE_START}"}


def test_a_failing_check_is_logged_once_and_never_raises(ir, caplog):
    check, hass = make_check()
    hass.states.get = MagicMock(side_effect=RuntimeError("boom"))
    with caplog.at_level(logging.ERROR):
        for _ in range(3):
            check._on_interval()
    assert len([r for r in caplog.records if "Setup check failed" in r.message]) == 1


def test_every_issue_has_its_text_in_both_string_files():
    import json
    from pathlib import Path

    base = Path(__file__).parent.parent / "custom_components" / "solarseed_peak_shaver"
    placeholders = {ISSUE_MISSING_SENSORS: "{sensors}", ISSUE_FORECAST_SHAPE: "{entities}",
                    ISSUE_NO_AUTOMATIONS: "{events}"}
    for name in ("strings.json", "translations/en.json"):
        issues = json.loads((base / name).read_text(encoding="utf-8"))["issues"]
        assert set(issues) == set(ISSUES)
        for key in ISSUES:
            assert issues[key]["title"] and placeholders[key] in issues[key]["description"], (name, key)


# --- the real setup -------------------------------------------------------------------------


def _setup(data, get):
    from custom_components.solarseed_peak_shaver import async_setup_entry
    from tests.conftest import _make_config_entry, _make_store

    entry = _make_config_entry(data=data)
    store = _make_store()
    store.async_load = AsyncMock()
    hass = MagicMock()
    hass.data = {}
    hass.state = "running"
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.states.get = get
    hass.bus.async_listeners = MagicMock(return_value={})
    with patch("custom_components.solarseed_peak_shaver.PeakShaverStore", return_value=store):
        ok = asyncio.run(async_setup_entry(hass, entry))
    return ok, hass, entry


def test_setup_succeeds_with_every_sensor_missing_and_starts_the_check(ir):
    from custom_components.solarseed_peak_shaver.const import DOMAIN

    event = sys.modules["homeassistant.helpers.event"]
    event.async_track_time_interval.reset_mock()
    ok, hass, entry = _setup(LEARNED, lambda e: None)
    assert ok is True
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.learned is not None and coordinator.setup_check is not None
    event.async_track_time_interval.assert_called_once()
    assert ir.async_create_issue.call_count == 0              # not at setup: ten minutes later
    found = coordinator.setup_check.run()
    assert set(found) == {ISSUE_MISSING_SENSORS, ISSUE_NO_AUTOMATIONS}
    assert all(e in found[ISSUE_MISSING_SENSORS]["sensors"]
               for e in ("sensor.battery_soc", "sensor.solcast_today", "sensor.gauge", "sensor.load", "sensor.grid"))


def test_setup_survives_a_check_that_cannot_start(ir):
    from custom_components.solarseed_peak_shaver.const import DOMAIN

    event = sys.modules["homeassistant.helpers.event"]
    with patch.object(event, "async_track_time_interval", side_effect=RuntimeError("no timers")):
        ok, hass, entry = _setup(LEARNED, states())
    assert ok is True
    assert hass.data[DOMAIN][entry.entry_id].setup_check is None


def test_unload_stops_the_check_and_removal_deletes_its_issues(ir):
    from custom_components.solarseed_peak_shaver import async_remove_entry, async_unload_entry

    unsub = MagicMock()
    event = sys.modules["homeassistant.helpers.event"]
    with patch.object(event, "async_track_time_interval", return_value=unsub):
        ok, hass, entry = _setup(LEARNED, states())
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    asyncio.run(async_unload_entry(hass, entry))
    unsub.assert_called_once()
    asyncio.run(async_remove_entry(hass, entry))
    assert {c.args[2] for c in ir.async_delete_issue.call_args_list} >= {f"{k}_{entry.entry_id}" for k in ISSUES}
