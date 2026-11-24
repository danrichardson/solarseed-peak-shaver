"""Options menu checks (HA mocked). Skipped where voluptuous is not installed (CI).

The merge rules themselves are in `options.py` and tested in test_options.py, which runs
everywhere; this file checks the flow's forms and that each step saves through them.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("voluptuous")

from custom_components.solarseed_peak_shaver.config_flow import PeakShaverOptionsFlow  # noqa: E402
from custom_components.solarseed_peak_shaver.const import (  # noqa: E402
    CONF_CAPACITY_V_HIGH,
    CONF_CAPACITY_V_LOW,
    CONF_GAUGE_ENTITY,
    CONF_HOLIDAY_PRESET,
    CONF_LOAD_QUANTILE,
    CONF_MIDPEAK_START,
    CONF_PEAK_END,
    CONF_PEAK_START,
    CONF_PLANNER,
    CONF_SCHEDULE_HOURS,
    CONF_SOLAR_ACTUAL_ENTITY,
    CONF_STALE_MINUTES,
)
from custom_components.solarseed_peak_shaver.options import SECTIONS  # noqa: E402
from tests.test_options import OLD_FLAT_FORM_OPTIONS  # noqa: E402

BASE = Path(__file__).parent.parent / "custom_components" / "solarseed_peak_shaver"


def make_flow(options=None, data=None):
    flow = PeakShaverOptionsFlow()
    flow.config_entry = SimpleNamespace(data=dict(data or {}), options=dict(options or {}))
    flow.async_create_entry = MagicMock(return_value="created")
    flow.async_show_form = MagicMock(return_value="form")
    flow.async_show_menu = MagicMock(return_value="menu")
    return flow


def step(flow, section, user_input=None):
    return asyncio.run(getattr(flow, "async_step_" + section)(user_input))


def shown(flow):
    """The form's fields: {key: default or suggested value}."""
    schema = flow.async_show_form.call_args.kwargs["data_schema"]
    out = {}
    for marker in schema.schema:
        if marker.description and "suggested_value" in marker.description:
            out[str(marker)] = marker.description["suggested_value"]
        else:
            out[str(marker)] = marker.default()
    return out


def test_the_options_open_on_the_menu():
    flow = make_flow()
    assert asyncio.run(flow.async_step_init(None)) == "menu"
    kwargs = flow.async_show_menu.call_args.kwargs
    assert kwargs["step_id"] == "init"
    assert kwargs["menu_options"] == ["battery", "schedule", "learned", "packs", "notifications", "classic"]


@pytest.mark.parametrize("section", list(SECTIONS))
def test_each_section_shows_its_fields_with_labels_in_both_string_files(section):
    flow = make_flow()
    assert step(flow, section) == "form"
    assert flow.async_show_form.call_args.kwargs["step_id"] == section
    assert list(shown(flow)) == list(SECTIONS[section])
    for name in ("strings.json", "translations/en.json"):
        steps = json.loads((BASE / name).read_text(encoding="utf-8"))["options"]["step"]
        assert steps[section]["title"]
        missing = set(SECTIONS[section]) - set(steps[section]["data"])
        assert not missing, (name, missing)
        assert steps["init"]["menu_options"][section]


@pytest.mark.parametrize("section", list(SECTIONS))
def test_an_entry_saved_by_0_8_shows_its_own_values(section):
    flow = make_flow(options=OLD_FLAT_FORM_OPTIONS, data={"battery_soc_entity": "sensor.battery_soc"})
    step(flow, section)
    for key, value in shown(flow).items():
        if key not in OLD_FLAT_FORM_OPTIONS and key not in flow.config_entry.data:
            continue                                     # never stored: the form's default
        stored = OLD_FLAT_FORM_OPTIONS.get(key, flow.config_entry.data.get(key))
        if isinstance(stored, list) and isinstance(value, str):
            stored = ",".join(str(v) for v in stored)
        assert value == stored, key


@pytest.mark.parametrize("section", list(SECTIONS))
def test_saving_one_section_keeps_every_other_stored_option(section):
    stored = {**OLD_FLAT_FORM_OPTIONS, "a_key_no_form_shows": 42}
    flow = make_flow(options=stored)
    step(flow, section)
    submitted = {k: v for k, v in shown(flow).items() if v not in ("", [])}   # as typed back
    assert step(flow, section, submitted) == "created"
    saved = flow.async_create_entry.call_args.kwargs["data"]
    assert saved["a_key_no_form_shows"] == 42
    for key, value in stored.items():
        if key not in SECTIONS[section]:
            assert saved[key] == value, key


def test_a_tuning_change_in_the_learned_section_changes_only_that():
    flow = make_flow(options=OLD_FLAT_FORM_OPTIONS)
    step(flow, "learned")
    submitted = {**shown(flow), CONF_LOAD_QUANTILE: 0.9}
    step(flow, "learned", submitted)
    saved = flow.async_create_entry.call_args.kwargs["data"]
    assert saved == {**OLD_FLAT_FORM_OPTIONS, CONF_LOAD_QUANTILE: 0.9}


def test_a_cleared_sensor_stays_cleared():
    # the setup data has a production sensor; clearing it in the options must win over it
    flow = make_flow(options={CONF_GAUGE_ENTITY: "sensor.gauge"},
                     data={CONF_SOLAR_ACTUAL_ENTITY: "sensor.pv_today", "battery_soc_entity": "sensor.b"})
    step(flow, "battery")
    assert shown(flow)[CONF_SOLAR_ACTUAL_ENTITY] == "sensor.pv_today"
    step(flow, "battery", {"battery_soc_entity": "sensor.b", "solar_forecast_entity": "sensor.f",
                           "battery_capacity": 23.5, "base_load_kw": 0.6})
    saved = flow.async_create_entry.call_args.kwargs["data"]
    assert saved[CONF_SOLAR_ACTUAL_ENTITY] == ""
    assert saved[CONF_GAUGE_ENTITY] == ""


def test_the_price_windows_must_be_in_order():
    flow = make_flow()
    out = step(flow, "schedule", {CONF_MIDPEAK_START: 17, CONF_PEAK_START: 17, CONF_PEAK_END: 16,
                                  "weekdays_only": True, CONF_HOLIDAY_PRESET: "pge"})
    assert out == "form"
    assert flow.async_show_form.call_args.kwargs["errors"] == {
        CONF_PEAK_START: "invalid_time_range", CONF_PEAK_END: "invalid_time_range"}
    flow.async_create_entry.assert_not_called()


def test_lower_voltage_must_be_below_the_upper():
    flow = make_flow()
    out = step(flow, "packs", {CONF_CAPACITY_V_HIGH: 51.0, CONF_CAPACITY_V_LOW: 52.0})
    assert out == "form"
    assert flow.async_show_form.call_args.kwargs["errors"] == {CONF_CAPACITY_V_LOW: "invalid_voltage_range"}
    flow.async_create_entry.assert_not_called()


def test_valid_input_is_saved_over_the_stored_options():
    flow = make_flow(options={CONF_PLANNER: "learned"})
    data = {CONF_CAPACITY_V_HIGH: 53.0, CONF_CAPACITY_V_LOW: 51.5}
    assert step(flow, "packs", data) == "created"
    saved = flow.async_create_entry.call_args.kwargs["data"]
    assert saved[CONF_PLANNER] == "learned"
    assert saved[CONF_CAPACITY_V_HIGH] == 53.0
    assert saved["pack_current_entities"] == [] and saved["bus_voltage_entity"] == ""


def test_lists_are_edited_as_text():
    flow = make_flow(data={CONF_SCHEDULE_HOURS: [3, 4, 5, 6]})
    step(flow, "classic")
    assert shown(flow)[CONF_SCHEDULE_HOURS] == "3,4,5,6"


def test_the_stale_minutes_field_is_in_the_learned_section():
    assert CONF_STALE_MINUTES in SECTIONS["learned"]
