"""The first-time config flow (0.9.3): a new install picks the learned planner's sensors and
starts on `learned`; the tariff is checked as the Tariff options section checks it; every
field of every form says what to pick and what empty does. Needs voluptuous (CI has it)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

vol = pytest.importorskip("voluptuous")

from custom_components.solarseed_peak_shaver.config_flow import (  # noqa: E402
    FIRST_TARIFF_KEYS,
    LEARNED_SENSOR_KEYS,
    PeakShaverConfigFlow,
    PeakShaverOptionsFlow,
)
from custom_components.solarseed_peak_shaver.const import (  # noqa: E402
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_BASE_LOAD,
    CONF_GAUGE_ENTITY,
    CONF_GRID_POWER_ENTITY,
    CONF_HOLIDAY_PRESET,
    CONF_HOLIDAY_RULES,
    CONF_LOAD_POWER_ENTITY,
    CONF_MIDPEAK_PRICE,
    CONF_MIDPEAK_START,
    CONF_MIN_SAFE_SOC,
    CONF_OFFPEAK_PRICE,
    CONF_PEAK_END,
    CONF_PEAK_PRICE,
    CONF_PEAK_START,
    CONF_PLANNER,
    CONF_PV_POWER_ENTITY,
    CONF_SCHEDULE_HOURS,
    CONF_SOLAR_FORECAST_ENTITY,
    CONF_SOLAR_FORECAST_TOMORROW_ENTITY,
    CONF_WEEKDAYS_ONLY,
    PLANNER_CLASSIC,
    PLANNER_LEARNED,
)
from custom_components.solarseed_peak_shaver.options import SECTIONS  # noqa: E402

BASE = Path(__file__).parent.parent / "custom_components" / "solarseed_peak_shaver"
STRING_FILES = ("strings.json", "translations/en.json")

EXISTING = {"sensor.battery_kwh", "sensor.solcast_pv_forecast_forecast_today",
            "sensor.solcast_pv_forecast_forecast_tomorrow", "sensor.inverter_gauge",
            "sensor.inverter_ac_out", "sensor.inverter_ac_in", "sensor.inverter_pv"}

STEP1 = {CONF_BATTERY_SOC_ENTITY: "sensor.battery_kwh",
         CONF_SOLAR_FORECAST_ENTITY: "sensor.solcast_pv_forecast_forecast_today",
         CONF_BATTERY_CAPACITY: 10.0, CONF_BASE_LOAD: 0.5, CONF_MIN_SAFE_SOC: 1.5}
SENSORS = {CONF_GAUGE_ENTITY: "sensor.inverter_gauge", CONF_LOAD_POWER_ENTITY: "sensor.inverter_ac_out",
           CONF_GRID_POWER_ENTITY: "sensor.inverter_ac_in", CONF_PV_POWER_ENTITY: "sensor.inverter_pv"}
TARIFF = {CONF_MIDPEAK_START: 15, CONF_PEAK_START: 17, CONF_PEAK_END: 20, CONF_WEEKDAYS_ONLY: True,
          CONF_MIDPEAK_PRICE: 0.2, CONF_PEAK_PRICE: 0.5, CONF_HOLIDAY_PRESET: "us_federal",
          CONF_SCHEDULE_HOURS: "3,4,5,6"}
NOTIFY = {"notifications_enabled": True, "notify_entity": "", "charge_threshold": 0.5,
          "seasonal_preservation": True, "seasonal_months": "11,12,1,2,3", "verbose_logging": False}


def make_flow():
    flow = PeakShaverConfigFlow()
    flow.hass = MagicMock()
    flow.hass.states.get = lambda e: SimpleNamespace(state="1", attributes={}) if e in EXISTING else None
    flow.async_show_form = MagicMock(return_value="form")
    flow.async_create_entry = MagicMock(return_value="created")
    return flow


def run(flow, step, user_input=None):
    return asyncio.run(getattr(flow, "async_step_" + step)(user_input))


def form(flow):
    return flow.async_show_form.call_args.kwargs


def fields(flow) -> dict[str, tuple[bool, object]]:
    """{key: (required, default or suggested value)} of the form last shown."""
    out = {}
    for marker in form(flow)["data_schema"].schema:
        if marker.description and "suggested_value" in marker.description:
            value = marker.description["suggested_value"]
        else:
            value = marker.default() if callable(marker.default) else None
        out[str(marker)] = (isinstance(marker, vol.Required), value)
    return out


def walk(sensors=None, tariff=None):
    flow = make_flow()
    assert run(flow, "user", dict(STEP1)) == "form"
    assert form(flow)["step_id"] == "learned"
    assert run(flow, "learned", dict(SENSORS if sensors is None else sensors)) == "form"
    assert form(flow)["step_id"] == "schedule", form(flow).get("errors")
    assert run(flow, "schedule", dict(TARIFF if tariff is None else tariff)) == "form"
    assert form(flow)["step_id"] == "notifications", form(flow).get("errors")
    assert run(flow, "notifications", dict(NOTIFY)) == "created"
    return flow.async_create_entry.call_args.kwargs["data"]


# --- the learned planner's sensors ------------------------------------------------------------


def test_a_new_install_with_load_and_grid_starts_on_learned():
    data = walk()
    assert data[CONF_PLANNER] == PLANNER_LEARNED
    for key, entity in SENSORS.items():
        assert data[key] == entity


def test_a_new_install_without_them_starts_on_classic_and_stores_no_empty_sensors():
    data = walk(sensors={})
    assert data[CONF_PLANNER] == PLANNER_CLASSIC
    assert not any(k in data for k in LEARNED_SENSOR_KEYS)


def test_one_of_load_and_grid_is_refused():
    flow = make_flow()
    run(flow, "user", dict(STEP1))
    run(flow, "learned", {CONF_LOAD_POWER_ENTITY: "sensor.inverter_ac_out"})
    assert form(flow)["step_id"] == "learned"
    assert form(flow)["errors"] == {CONF_GRID_POWER_ENTITY: "learned_needs_both"}
    assert fields(flow)[CONF_LOAD_POWER_ENTITY][1] == "sensor.inverter_ac_out"     # kept to fix


def test_a_sensor_that_does_not_exist_is_refused():
    flow = make_flow()
    run(flow, "user", dict(STEP1))
    run(flow, "learned", {**SENSORS, CONF_PV_POWER_ENTITY: "sensor.typo"})
    assert form(flow)["errors"] == {CONF_PV_POWER_ENTITY: "entity_not_found"}


def test_the_learned_screen_is_all_optional_and_guesses_tomorrow():
    flow = make_flow()
    run(flow, "user", dict(STEP1))
    shown = fields(flow)
    assert list(shown) == list(LEARNED_SENSOR_KEYS)
    assert not any(required for required, _ in shown.values())
    assert shown[CONF_SOLAR_FORECAST_TOMORROW_ENTITY][1] == "sensor.solcast_pv_forecast_forecast_tomorrow"
    assert shown[CONF_LOAD_POWER_ENTITY][1] == ""


def test_an_entry_from_before_0_9_3_stays_classic():
    from tests.test_coordinator import _make_coordinator

    coordinator = _make_coordinator(config_overrides={**SENSORS})   # sensors, but no planner key
    assert CONF_PLANNER not in coordinator.entry.data and CONF_PLANNER not in coordinator.entry.options
    assert coordinator.planner == PLANNER_CLASSIC


# --- the tariff screen --------------------------------------------------------------------------


def test_the_tariff_is_stored_as_typed_and_nothing_more():
    data = walk()
    for key, value in TARIFF.items():
        assert data[key] == value, key
    assert CONF_OFFPEAK_PRICE not in data                    # left empty: absent, as before
    assert CONF_HOLIDAY_RULES not in data                    # the preset's own rules are used


def test_the_tariff_screen_shows_the_pge_defaults_and_no_custom_preset():
    flow = make_flow()
    run(flow, "user", dict(STEP1))
    with patch("custom_components.solarseed_peak_shaver.config_flow._choice",
               side_effect=lambda options, key=None: ("choice", tuple(options))):
        run(flow, "learned", {})
    shown = fields(flow)
    assert list(shown) == list(FIRST_TARIFF_KEYS)
    assert shown[CONF_PEAK_END] == (True, 21) and shown[CONF_PEAK_PRICE] == (True, 0.4313)
    assert shown[CONF_OFFPEAK_PRICE] == (False, "")
    assert shown[CONF_HOLIDAY_PRESET] == (True, "pge")
    marker = next(m for m in form(flow)["data_schema"].schema if str(m) == CONF_HOLIDAY_PRESET)
    assert form(flow)["data_schema"].schema[marker] == ("choice", ("none", "pge", "us_federal"))
    assert form(flow)["description_placeholders"]["prices_detail"] == ""


@pytest.mark.parametrize("hours,field", [
    ((7, 17, 24), CONF_PEAK_END),           # scored on the next date; fixed in the Tariff section in 0.9.1
    ((7, 17, 17), CONF_PEAK_END),
    ((18, 17, 21), CONF_PEAK_START),
])
def test_hours_are_checked_as_the_tariff_section_checks_them(hours, field):
    flow = make_flow()
    run(flow, "user", dict(STEP1))
    run(flow, "learned", {})
    mid, peak, end = hours
    run(flow, "schedule", {**TARIFF, CONF_MIDPEAK_START: mid, CONF_PEAK_START: peak, CONF_PEAK_END: end})
    assert form(flow)["step_id"] == "schedule"
    assert form(flow)["errors"][field] == "invalid_time_range"
    flow.async_create_entry.assert_not_called()


def test_prices_that_fall_into_peak_are_refused_with_the_reason():
    flow = make_flow()
    run(flow, "user", dict(STEP1))
    run(flow, "learned", {})
    run(flow, "schedule", {**TARIFF, CONF_MIDPEAK_PRICE: 0.5, CONF_PEAK_PRICE: 0.2})
    assert form(flow)["errors"] == {CONF_PEAK_PRICE: "invalid_prices"}
    assert form(flow)["description_placeholders"]["prices_detail"]


def test_a_two_price_plan_is_accepted():
    data = walk(tariff={**TARIFF, CONF_MIDPEAK_START: 16, CONF_PEAK_START: 16, CONF_PEAK_END: 21})
    assert data[CONF_MIDPEAK_START] == data[CONF_PEAK_START] == 16


def test_pge_holidays_stay_pge():
    data = walk(tariff={**TARIFF, CONF_HOLIDAY_PRESET: "pge"})
    assert data[CONF_HOLIDAY_PRESET] == "pge"


# --- every field says what to pick and what empty does ----------------------------------------


def _config_forms():
    """{step id: fields} of each first-time screen, as the flow builds them."""
    flow = make_flow()
    out = {}
    run(flow, "user")
    out["user"] = fields(flow)
    run(flow, "user", dict(STEP1))
    out["learned"] = fields(flow)
    run(flow, "learned", {})
    out["schedule"] = fields(flow)
    run(flow, "schedule", dict(TARIFF))
    out["notifications"] = fields(flow)
    return out


def _options_forms():
    out = {}
    for section in SECTIONS:
        flow = PeakShaverOptionsFlow()
        flow.config_entry = SimpleNamespace(data={}, options={})
        flow.async_show_form = MagicMock(return_value="form")
        asyncio.run(getattr(flow, "async_step_" + section)(None))
        out[section] = fields(flow)
    return out


@pytest.mark.parametrize("name", STRING_FILES)
@pytest.mark.parametrize("where", ["config", "options"])
def test_every_field_has_a_label_and_a_description_that_says_what_empty_does(name, where):
    steps = json.loads((BASE / name).read_text(encoding="utf-8"))[where]["step"]
    forms = _config_forms() if where == "config" else _options_forms()
    entity_keys = {k for k in (*LEARNED_SENSOR_KEYS, CONF_BATTERY_SOC_ENTITY, CONF_SOLAR_FORECAST_ENTITY)}
    for step_id, shown in forms.items():
        assert steps[step_id]["title"] and steps[step_id]["description"], (step_id,)
        assert set(steps[step_id]["data"]) == set(shown), (step_id,)
        assert set(steps[step_id]["data_description"]) == set(shown), (step_id,)
        for key, (required, _) in shown.items():
            text = steps[step_id]["data_description"][key]
            assert len(text) > 20, (step_id, key)
            if not required:
                assert "empty" in text.lower(), (step_id, key, "optional: say what empty does")
            elif key in entity_keys:
                assert text.startswith("Required."), (step_id, key)


@pytest.mark.parametrize("name", STRING_FILES)
def test_the_first_time_errors_have_their_text(name):
    errors = json.loads((BASE / name).read_text(encoding="utf-8"))["config"]["error"]
    assert {"entity_not_found", "invalid_time_range", "invalid_prices", "learned_needs_both"} <= set(errors)
    assert "{prices_detail}" in errors["invalid_prices"]
    assert "23:00" in errors["invalid_time_range"]


@pytest.mark.parametrize("name", STRING_FILES)
def test_the_classic_planner_is_marked_legacy_wherever_its_settings_are(name):
    strings = json.loads((BASE / name).read_text(encoding="utf-8"))
    config = strings["config"]["step"]
    for step_id, key in (("user", CONF_MIN_SAFE_SOC), ("schedule", CONF_SCHEDULE_HOURS),
                         ("notifications", "charge_threshold"), ("notifications", "seasonal_preservation"),
                         ("notifications", "seasonal_months")):
        assert "legacy" in config[step_id]["data"][key], (step_id, key)
    assert "legacy" in strings["options"]["step"]["init"]["menu_options"]["classic"]
    assert "legacy" in strings["options"]["step"]["classic"]["title"]
    assert "legacy" in strings["selector"]["planner"]["options"]["classic"]
    assert "legacy" in strings["entity"]["select"]["planner"]["state"]["classic"]
