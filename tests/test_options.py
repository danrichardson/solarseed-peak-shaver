"""0.9.0: the options menu's sections and merge rule, the settings entities on the device
page, and when a saved change reloads the entry (HA mocked; runs without voluptuous)."""
from __future__ import annotations

import asyncio
import math
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solarseed_peak_shaver import async_options_updated
from custom_components.solarseed_peak_shaver import const
from custom_components.solarseed_peak_shaver.const import (
    CONF_BATTERY_SOC_ENTITY,
    CONF_GAUGE_FLOOR,
    CONF_HOLIDAY_PRESET,
    CONF_LOAD_QUANTILE,
    CONF_NOTIFY_ENTITY,
    CONF_PACK_CURRENT_ENTITIES,
    CONF_PEAK_END,
    CONF_PEAK_MARGIN_KWH,
    CONF_PLANNER,
    CONF_SCHEDULE_HOURS,
    CONF_SOLAR_ACTUAL_ENTITY,
    CONF_SOLAR_CONFIDENCE,
    CONF_SOLAR_FORECAST_ENTITY,
    EVENT_CHARGE_START,
)
from custom_components.solarseed_peak_shaver.number import NUMBERS, OptionNumber
from custom_components.solarseed_peak_shaver.options import (
    CLEARED_VALUE,
    RELOAD_KEYS,
    SECTIONS,
    merge_section,
    write_option,
)
from custom_components.solarseed_peak_shaver.select import SELECTS, OptionSelect
from tests.test_learned_runtime import fired, make_runtime, run

# The options exactly as the 0.8.2 flat form stored them (it saved every field it showed).
OLD_FLAT_FORM_OPTIONS = {
    "battery_capacity": 23.5,
    "base_load_kw": 0.6,
    "min_safe_soc_kwh": 1.5,
    "midpeak_start_hour": 7.0,
    "peak_start_hour": 17.0,
    "peak_end_hour": 21.0,
    "weekdays_only": True,
    "holiday_preset": "pge",
    "notifications_enabled": True,
    "notify_entity": "notify.mobile_app_phone",
    "charge_threshold": 0.5,
    "seasonal_preservation": True,
    "seasonal_months": "11,12,1,2,3",
    "verbose_logging": False,
    "solar_actual_entity": "",
    "planner": "learned",
    "gauge_entity": "sensor.gauge",
    "load_power_entity": "sensor.load",
    "grid_power_entity": "sensor.grid",
    "pv_power_entity": "sensor.pv",
    "solar_forecast_tomorrow_entity": "sensor.solcast_tomorrow",
    "full_charge_months": "11,12,1",
    "load_quantile": 0.8,
    "solar_confidence": 0.7,
    "gauge_floor_pct": 3.0,
    "handover_recovery_pct": 10.0,
    "peak_margin_kwh": 0.5,
    "stale_minutes": 20.0,
    "pack_current_entities": ["sensor.pack_a_current", "sensor.pack_b_current"],
    "pack_current_charge_positive": True,
    "bus_voltage_entity": "",
    "pack_capacity_ah": 100.0,
    "capacity_v_high": 53.0,
    "capacity_v_low": 51.5,
}

TUNING_KEYS = (CONF_PLANNER, CONF_HOLIDAY_PRESET, CONF_PEAK_MARGIN_KWH, CONF_LOAD_QUANTILE,
               CONF_SOLAR_CONFIDENCE, CONF_GAUGE_FLOOR)


class FakeEntries:
    """hass.config_entries: updating an entry replaces its options, as HA does."""

    def __init__(self):
        self.updates = []
        self.async_reload = AsyncMock()

    def async_update_entry(self, entry, options):
        self.updates.append(dict(options))
        entry.options = dict(options)
        return True


def coordinator_with(options=None, **overrides):
    rt, coord, world = make_runtime(planner="classic", **overrides)
    coord.entry.options = dict(options or {})
    coord.hass.config_entries = FakeEntries()
    coord.hass.data = {const.DOMAIN: {coord.entry.entry_id: coord}}
    coord.started_with = coord.setup_signature()
    return rt, coord, world


# --- the sections ----------------------------------------------------------------------------


class TestSections:
    def test_every_option_key_is_in_exactly_one_section(self):
        keys = [k for keys in SECTIONS.values() for k in keys]
        assert len(keys) == len(set(keys))
        conf = {getattr(const, n) for n in dir(const) if n.startswith("CONF_")}
        assert set(keys) == conf

    def test_every_field_the_old_form_showed_is_in_a_section(self):
        keys = {k for keys in SECTIONS.values() for k in keys}
        assert set(OLD_FLAT_FORM_OPTIONS) <= keys

    def test_the_menu_order(self):
        # 0.9.1: the Schedule section became Tariff (the same hours, with prices and seasons)
        assert list(SECTIONS) == ["battery", "tariff", "learned", "packs", "notifications", "classic"]

    def test_only_optional_fields_can_be_cleared(self):
        for key, empty in CLEARED_VALUE.items():
            assert empty in ("", [])
            assert any(key in keys for keys in SECTIONS.values())


class TestMerge:
    @pytest.mark.parametrize("section", list(SECTIONS))
    def test_saving_a_section_keeps_the_others_and_unknown_keys(self, section):
        stored = {**OLD_FLAT_FORM_OPTIONS, "a_key_no_form_shows": [1, 2]}
        typed = {k: stored[k] for k in SECTIONS[section] if k in stored and stored[k] not in ("", [])}
        merged = merge_section(stored, typed, section)
        assert merged["a_key_no_form_shows"] == [1, 2]
        for key, value in stored.items():
            if key not in SECTIONS[section]:
                assert merged[key] == value, key

    def test_a_changed_field_is_stored(self):
        merged = merge_section(OLD_FLAT_FORM_OPTIONS, {CONF_LOAD_QUANTILE: 0.9}, "learned")
        assert merged == {**OLD_FLAT_FORM_OPTIONS, CONF_LOAD_QUANTILE: 0.9}

    def test_a_field_left_out_of_the_form_is_cleared_not_dropped(self):
        merged = merge_section({CONF_SOLAR_ACTUAL_ENTITY: "sensor.x", CONF_PACK_CURRENT_ENTITIES: ["a"]},
                               {CONF_BATTERY_SOC_ENTITY: "sensor.b"}, "battery")
        assert merged[CONF_SOLAR_ACTUAL_ENTITY] == ""
        assert merged[CONF_PACK_CURRENT_ENTITIES] == ["a"]            # another section's: kept
        merged = merge_section({CONF_NOTIFY_ENTITY: "notify.x"}, {}, "notifications")
        assert merged[CONF_NOTIFY_ENTITY] == ""

    def test_the_stored_dict_is_not_changed_in_place(self):
        stored = dict(OLD_FLAT_FORM_OPTIONS)
        merge_section(stored, {CONF_LOAD_QUANTILE: 0.9}, "learned")
        assert stored == OLD_FLAT_FORM_OPTIONS


class TestOldEntries:
    def test_an_entry_saved_by_0_8_reads_the_same(self):
        rt, coord, _ = make_runtime(planner="classic")
        coord.entry.options = dict(OLD_FLAT_FORM_OPTIONS)
        assert coord.planner == "learned"
        assert coord.load_quantile == 0.8 and coord.solar_confidence == 0.7
        assert coord.gauge_floor == 3.0 and coord.peak_margin_kwh == 0.5
        assert coord.holiday_preset == "pge"
        assert coord.full_charge_months == [11, 12, 1]
        assert coord.seasonal_months == [11, 12, 1, 2, 3]
        assert coord.schedule_hours == [3, 4, 5, 6]                    # from the setup data
        assert coord.pack_current_entities == ["sensor.pack_a_current", "sensor.pack_b_current"]

    def test_an_entry_with_no_options_at_all_still_reads_defaults(self):
        rt, coord, _ = make_runtime(planner="classic")
        coord.entry.options = {}
        assert coord.load_quantile == const.DEFAULT_LOAD_QUANTILE
        assert coord.holiday_preset == "pge"


# --- the settings entities -------------------------------------------------------------------


def make_select(coord, key):
    spec = next(s for s in SELECTS if s[0] == key)
    ent = OptionSelect(coord, coord.entry, *spec)
    ent.async_write_ha_state = MagicMock()
    return ent


def make_number(coord, key):
    spec = next(s for s in NUMBERS if s[0] == key)
    ent = OptionNumber(coord, coord.entry, *spec)
    ent.async_write_ha_state = MagicMock()
    return ent


class TestEntities:
    def test_the_six_settings_are_there(self):
        assert {s[0] for s in SELECTS} == {CONF_PLANNER, CONF_HOLIDAY_PRESET}
        assert {n[0] for n in NUMBERS} == {CONF_PEAK_MARGIN_KWH, CONF_LOAD_QUANTILE,
                                           CONF_SOLAR_CONFIDENCE, CONF_GAUGE_FLOOR}

    def test_unique_ids_are_new_and_distinct(self):
        rt, coord, _ = coordinator_with()
        ids = [make_select(coord, s[0])._attr_unique_id for s in SELECTS]
        ids += [make_number(coord, n[0])._attr_unique_id for n in NUMBERS]
        assert len(set(ids)) == 6
        assert all(i.startswith("test_entry_id_option_") for i in ids)
        assert make_select(coord, CONF_PLANNER)._attr_entity_category == "config"

    def test_the_planner_select_shows_and_writes_the_option(self):
        rt, coord, _ = coordinator_with(OLD_FLAT_FORM_OPTIONS)
        ent = make_select(coord, CONF_PLANNER)
        assert ent.current_option == "learned"
        assert ent._attr_options == ["classic", "learned"]
        asyncio.run(ent.async_select_option("classic"))
        assert coord.entry.options == {**OLD_FLAT_FORM_OPTIONS, CONF_PLANNER: "classic"}
        assert ent.current_option == "classic"
        ent.async_write_ha_state.assert_called_once()

    def test_an_absent_option_shows_its_default(self):
        rt, coord, _ = coordinator_with({})
        coord.entry.data.pop(CONF_PLANNER, None)
        assert make_select(coord, CONF_PLANNER).current_option == "classic"
        assert make_select(coord, CONF_HOLIDAY_PRESET).current_option == "pge"
        assert make_number(coord, CONF_LOAD_QUANTILE).native_value == const.DEFAULT_LOAD_QUANTILE

    def test_an_unknown_choice_is_refused(self):
        rt, coord, _ = coordinator_with()
        with pytest.raises(ValueError):
            asyncio.run(make_select(coord, CONF_HOLIDAY_PRESET).async_select_option("bogus"))
        assert coord.hass.config_entries.updates == []

    def test_a_number_writes_one_option_rounded(self):
        rt, coord, _ = coordinator_with(OLD_FLAT_FORM_OPTIONS)
        ent = make_number(coord, CONF_LOAD_QUANTILE)
        asyncio.run(ent.async_set_native_value(0.8500000001))
        assert coord.entry.options == {**OLD_FLAT_FORM_OPTIONS, CONF_LOAD_QUANTILE: 0.85}
        assert ent.native_value == 0.85

    @pytest.mark.parametrize("value", [0.2, 1.2, math.nan, None])
    def test_a_number_out_of_range_is_refused(self, value):
        rt, coord, _ = coordinator_with()
        with pytest.raises(ValueError):
            asyncio.run(make_number(coord, CONF_LOAD_QUANTILE).async_set_native_value(value))
        assert coord.hass.config_entries.updates == []

    def test_setting_the_same_value_writes_nothing(self):
        rt, coord, _ = coordinator_with({CONF_GAUGE_FLOOR: 3.0})
        asyncio.run(make_number(coord, CONF_GAUGE_FLOOR).async_set_native_value(3.0))
        assert coord.hass.config_entries.updates == []

    def test_write_option_keeps_everything_else(self):
        entry = SimpleNamespace(options={"x": 1, "planner": "classic"})
        hass = SimpleNamespace(config_entries=FakeEntries())
        assert write_option(hass, entry, "planner", "learned") is True
        assert entry.options == {"x": 1, "planner": "learned"}


# --- no reload for a tuning change; a reload for a setting read at start ----------------------


class TestUpdateListener:
    def test_the_signature_covers_exactly_the_reload_keys(self):
        rt, coord, _ = coordinator_with()
        assert set(coord.setup_signature()) == set(RELOAD_KEYS)

    @pytest.mark.parametrize("key", TUNING_KEYS)
    def test_a_settings_entity_never_reloads_the_entry(self, key):
        rt, coord, _ = coordinator_with(OLD_FLAT_FORM_OPTIONS)
        if key in (CONF_PLANNER, CONF_HOLIDAY_PRESET):
            ent = make_select(coord, key)
            choice = next(o for o in ent._attr_options if o != ent.current_option)
            asyncio.run(ent.async_select_option(choice))
        else:
            ent = make_number(coord, key)
            asyncio.run(ent.async_set_native_value(ent._attr_native_min_value))
        assert coord.hass.config_entries.updates                      # it was written
        asyncio.run(async_options_updated(coord.hass, coord.entry))   # what HA calls next
        coord.hass.config_entries.async_reload.assert_not_awaited()
        coord.async_update_listeners.assert_called()                  # the entities refresh

    @pytest.mark.parametrize("key", [k for keys in SECTIONS.values() for k in keys if k not in RELOAD_KEYS])
    def test_no_live_setting_reloads(self, key):
        rt, coord, _ = coordinator_with(OLD_FLAT_FORM_OPTIONS)
        coord.entry.options = {**coord.entry.options, key: "changed"}
        asyncio.run(async_options_updated(coord.hass, coord.entry))
        coord.hass.config_entries.async_reload.assert_not_awaited()

    @pytest.mark.parametrize("key,value", [
        (CONF_PEAK_END, 22.0), (CONF_SCHEDULE_HOURS, "2,3"), (CONF_BATTERY_SOC_ENTITY, "sensor.other"),
        (CONF_SOLAR_FORECAST_ENTITY, "sensor.other"), (CONF_PACK_CURRENT_ENTITIES, ["sensor.c_current"]),
    ])
    def test_a_setting_read_at_start_reloads(self, key, value):
        rt, coord, _ = coordinator_with(OLD_FLAT_FORM_OPTIONS)
        coord.entry.options = {**coord.entry.options, key: value}
        asyncio.run(async_options_updated(coord.hass, coord.entry))
        coord.hass.config_entries.async_reload.assert_awaited_once_with(coord.entry.entry_id)

    def test_the_same_value_in_another_form_does_not_reload(self):
        # the setup data has the hours as a list; the options form saves them as text
        rt, coord, _ = coordinator_with(OLD_FLAT_FORM_OPTIONS)
        coord.entry.options = {**coord.entry.options, CONF_SCHEDULE_HOURS: "3,4,5,6", CONF_PEAK_END: 21.0}
        asyncio.run(async_options_updated(coord.hass, coord.entry))
        coord.hass.config_entries.async_reload.assert_not_awaited()

    def test_an_unloaded_entry_is_ignored(self):
        rt, coord, _ = coordinator_with()
        coord.hass.data = {const.DOMAIN: {}}
        asyncio.run(async_options_updated(coord.hass, coord.entry))
        coord.hass.config_entries.async_reload.assert_not_awaited()

    def test_setup_registers_the_listener(self):
        from tests.test_startup_guards import TestSetupWithMissingBattery

        ok, hass, entry, _ = TestSetupWithMissingBattery._setup((20.0, "kWh"))
        assert ok is True
        entry.add_update_listener.assert_called_once_with(async_options_updated)
        entry.async_on_unload.assert_called_once_with(entry.add_update_listener.return_value)
        coord = hass.data[const.DOMAIN][entry.entry_id]
        assert coord.started_with == coord.setup_signature()

    def test_the_platforms_include_select_and_number(self):
        from custom_components.solarseed_peak_shaver import PLATFORMS

        assert set(PLATFORMS) == {"sensor", "button", "select", "number"}


# --- taking effect without a restart ----------------------------------------------------------


class TestLive:
    def test_the_planner_select_hands_control_to_learned_on_the_next_minute(self):
        rt, coord, world = coordinator_with({CONF_PLANNER: "classic"})
        run(rt, datetime(2026, 11, 16, 20, 55), 3)                  # classic: shadow only
        assert fired(coord) == []
        asyncio.run(make_select(coord, CONF_PLANNER).async_select_option("learned"))
        asyncio.run(async_options_updated(coord.hass, coord.entry))
        run(rt, datetime(2026, 11, 16, 21, 0), 2)                   # the same runtime, not a new one
        assert fired(coord) == [EVENT_CHARGE_START]
        coord.hass.config_entries.async_reload.assert_not_awaited()

    def test_a_tuning_number_reaches_the_planner_on_the_next_minute(self):
        rt, coord, _ = coordinator_with({CONF_PEAK_MARGIN_KWH: 0.5})
        now = datetime(2026, 11, 16, 12, 0)
        assert rt._inputs(now, 50.0).margin_kwh == 0.5
        asyncio.run(make_number(coord, CONF_PEAK_MARGIN_KWH).async_set_native_value(1.5))
        assert rt._inputs(now, 50.0).margin_kwh == 1.5
        asyncio.run(make_number(coord, CONF_SOLAR_CONFIDENCE).async_set_native_value(0.5))
        assert rt._inputs(now, 50.0).solar_confidence == 0.5
