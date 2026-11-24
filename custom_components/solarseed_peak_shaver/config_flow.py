"""Config flow for Solarseed Peak Shaver."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .holidays import HOLIDAY_PRESET_CUSTOM, HOLIDAY_PRESETS, normalize_preset, preset_rules_text
from .options import (
    SECTION_BATTERY,
    SECTION_CLASSIC,
    SECTION_LEARNED,
    SECTION_NOTIFICATIONS,
    SECTION_PACKS,
    SECTION_TARIFF,
    SECTIONS,
    check_tariff,
    merge_section,
)
from .const import (
    CONF_BASE_LOAD,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_BUS_VOLTAGE_ENTITY,
    CONF_CAPACITY_V_HIGH,
    CONF_CAPACITY_V_LOW,
    CONF_CHARGE_THRESHOLD,
    CONF_FULL_CHARGE_MONTHS,
    CONF_GAUGE_ENTITY,
    CONF_GAUGE_FLOOR,
    CONF_GRID_POWER_ENTITY,
    CONF_HOLIDAY_DATES,
    CONF_HOLIDAY_PRESET,
    CONF_HOLIDAY_RULES,
    CONF_LOAD_POWER_ENTITY,
    CONF_LOAD_QUANTILE,
    CONF_MIDPEAK_PRICE,
    CONF_MIDPEAK_START,
    CONF_NOTIFICATIONS_ENABLED,
    CONF_NOTIFY_ENTITY,
    CONF_OFFPEAK_PRICE,
    CONF_PACK_CAPACITY_AH,
    CONF_PACK_CURRENT_CHARGE_POSITIVE,
    CONF_PACK_CURRENT_ENTITIES,
    CONF_PEAK_END,
    CONF_PEAK_PRICE,
    CONF_PEAK_START,
    CONF_PLANNER,
    CONF_PV_POWER_ENTITY,
    CONF_MIN_SAFE_SOC,
    CONF_PEAK_MARGIN_KWH,
    CONF_RECOVERY_PCT,
    CONF_SCHEDULE_HOURS,
    CONF_SEASONAL_MONTHS,
    CONF_SEASONAL_PRESERVATION,
    CONF_SOLAR_ACTUAL_ENTITY,
    CONF_SOLAR_CONFIDENCE,
    CONF_SOLAR_FORECAST_ENTITY,
    CONF_SOLAR_FORECAST_TOMORROW_ENTITY,
    CONF_STALE_MINUTES,
    CONF_TARIFF_SEASONS,
    CONF_VERBOSE_LOGGING,
    CONF_WEEKDAYS_ONLY,
    DEFAULT_BASE_LOAD,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_CAPACITY_V_HIGH,
    DEFAULT_CAPACITY_V_LOW,
    DEFAULT_CHARGE_THRESHOLD,
    DEFAULT_FULL_CHARGE_MONTHS,
    DEFAULT_GAUGE_FLOOR,
    DEFAULT_HOLIDAY_PRESET,
    DEFAULT_LOAD_QUANTILE,
    DEFAULT_MIDPEAK_PRICE,
    DEFAULT_MIDPEAK_START,
    DEFAULT_NOTIFICATIONS_ENABLED,
    DEFAULT_PACK_CAPACITY_AH,
    DEFAULT_PACK_CURRENT_CHARGE_POSITIVE,
    DEFAULT_PEAK_END,
    DEFAULT_PEAK_PRICE,
    DEFAULT_PEAK_START,
    DEFAULT_PLANNER,
    DEFAULT_MIN_SAFE_SOC,
    DEFAULT_PEAK_MARGIN_KWH,
    DEFAULT_RECOVERY_PCT,
    DEFAULT_SCHEDULE_HOURS,
    DEFAULT_SEASONAL_MONTHS,
    DEFAULT_SEASONAL_PRESERVATION,
    DEFAULT_SOLAR_ACTUAL_ENTITY,
    DEFAULT_SOLAR_CONFIDENCE,
    DEFAULT_SOLAR_FORECAST_ENTITY,
    DEFAULT_STALE_MINUTES,
    DEFAULT_VERBOSE_LOGGING,
    DEFAULT_WEEKDAYS_ONLY,
    DOMAIN,
    PLANNER_CLASSIC,
    PLANNER_LEARNED,
)

_LOGGER = logging.getLogger(__name__)


class PeakShaverConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Solarseed Peak Shaver."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow."""
        self._collected: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: battery system and entity selection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            battery_entity = user_input[CONF_BATTERY_SOC_ENTITY]
            solar_entity = user_input[CONF_SOLAR_FORECAST_ENTITY]

            if self.hass.states.get(battery_entity) is None:
                errors[CONF_BATTERY_SOC_ENTITY] = "entity_not_found"
            if self.hass.states.get(solar_entity) is None:
                errors[CONF_SOLAR_FORECAST_ENTITY] = "entity_not_found"

            if not errors:
                self._collected.update(user_input)
                return await self.async_step_learned()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_BATTERY_SOC_ENTITY
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(
                    CONF_SOLAR_FORECAST_ENTITY,
                    default=DEFAULT_SOLAR_FORECAST_ENTITY,
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(
                    CONF_BATTERY_CAPACITY,
                    default=DEFAULT_BATTERY_CAPACITY,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5, max=200.0, step=0.5, unit_of_measurement="kWh",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_BASE_LOAD,
                    default=DEFAULT_BASE_LOAD,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0, max=10.0, step=0.1, unit_of_measurement="kW",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_MIN_SAFE_SOC,
                    default=DEFAULT_MIN_SAFE_SOC,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0, max=100.0, step=0.1, unit_of_measurement="kWh",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_SOLAR_ACTUAL_ENTITY,
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_learned(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2 (0.9.3): the learned planner's sensors. With the house load and grid
        sensors the new entry starts with the learned planner in control; without them the
        classic planner (legacy) is. Every field is optional and checked to exist."""
        errors: dict[str, str] = {}
        if user_input is not None:
            picked = {k: str(v).strip() for k, v in user_input.items()
                      if k in LEARNED_SENSOR_KEYS and str(v or "").strip()}
            for key, entity_id in picked.items():
                if self.hass.states.get(entity_id) is None:
                    errors[key] = "entity_not_found"
            has_load, has_grid = CONF_LOAD_POWER_ENTITY in picked, CONF_GRID_POWER_ENTITY in picked
            if has_load != has_grid:
                errors[CONF_GRID_POWER_ENTITY if has_load else CONF_LOAD_POWER_ENTITY] = "learned_needs_both"
            if not errors:
                self._collected.update(picked)
                self._collected[CONF_PLANNER] = first_planner(picked)
                return await self.async_step_schedule()

        shown = user_input or {CONF_SOLAR_FORECAST_TOMORROW_ENTITY: self._guess_tomorrow()}
        data_schema = vol.Schema({
            vol.Optional(key, description={"suggested_value": shown.get(key) or ""}): _sensor()
            for key in LEARNED_SENSOR_KEYS
        })
        return self.async_show_form(step_id="learned", data_schema=data_schema, errors=errors)

    def _guess_tomorrow(self) -> str:
        """Tomorrow's forecast sensor, when today's is Solcast-named and the twin exists."""
        today = str(self._collected.get(CONF_SOLAR_FORECAST_ENTITY) or "")
        if "today" not in today:
            return ""
        guess = today.replace("today", "tomorrow")
        return guess if self.hass.states.get(guess) is not None else ""

    async def async_step_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 3: the tariff - hours, prices, holidays - checked as the Tariff options
        section checks them (0.9.3; before, only mid-peak <= peak < end, and peak end 24
        was allowed, which scored on the next date). Seasons and custom holiday rules are
        in the options afterwards."""
        errors: dict[str, str] = {}
        placeholders = {"seasons_detail": "", "prices_detail": "", "rules_detail": "", "dates_detail": ""}

        if user_input is not None:
            preset = normalize_preset(user_input.get(CONF_HOLIDAY_PRESET, DEFAULT_HOLIDAY_PRESET))
            if preset == HOLIDAY_PRESET_CUSTOM:
                preset = DEFAULT_HOLIDAY_PRESET
            user_input = {**user_input, CONF_HOLIDAY_PRESET: preset}
            _, errors, placeholders = check_tariff(
                {}, {**user_input, CONF_HOLIDAY_RULES: preset_rules_text(preset) or ""})
            if not errors:
                self._collected.update(user_input)
                return await self.async_step_notifications()

        current = user_input or {}
        fields: dict[Any, Any] = {}
        for key in FIRST_TARIFF_KEYS:
            if key == CONF_HOLIDAY_PRESET:
                presets = [p for p in HOLIDAY_PRESETS if p != HOLIDAY_PRESET_CUSTOM]
                fields[vol.Required(key, default=normalize_preset(current.get(key, DEFAULT_HOLIDAY_PRESET)))] = (
                    _choice(presets, CONF_HOLIDAY_PRESET))
            else:
                marker, make = _field(key, current)
                fields[marker] = make
        return self.async_show_form(
            step_id="schedule",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 4: notifications, and the classic planner's (legacy) hold settings."""
        if user_input is not None:
            self._collected.update(user_input)
            return self.async_create_entry(
                title="Solarseed Peak Shaver",
                data=self._collected,
            )

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_NOTIFICATIONS_ENABLED,
                    default=DEFAULT_NOTIFICATIONS_ENABLED,
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_NOTIFY_ENTITY,
                    default="",
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.TEXT,
                    )
                ),
                vol.Required(
                    CONF_CHARGE_THRESHOLD,
                    default=DEFAULT_CHARGE_THRESHOLD,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0, max=5.0, step=0.1, unit_of_measurement="kWh",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_SEASONAL_PRESERVATION,
                    default=DEFAULT_SEASONAL_PRESERVATION,
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_SEASONAL_MONTHS,
                    default=",".join(str(m) for m in DEFAULT_SEASONAL_MONTHS),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.TEXT,
                    )
                ),
                vol.Required(
                    CONF_VERBOSE_LOGGING,
                    default=DEFAULT_VERBOSE_LOGGING,
                ): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="notifications",
            data_schema=data_schema,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> PeakShaverOptionsFlow:
        """Get the options flow handler."""
        return PeakShaverOptionsFlow()


class PeakShaverOptionsFlow(config_entries.OptionsFlow):
    """Options, as a menu of sections (0.9.0). Each section saves only its own fields."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """The menu."""
        return self.async_show_menu(step_id="init", menu_options=list(SECTIONS))

    async def async_step_battery(self, user_input: dict[str, Any] | None = None):
        """Battery and sensors."""
        return self._section(SECTION_BATTERY, user_input)

    async def async_step_tariff(self, user_input: dict[str, Any] | None = None):
        """Tariff: price windows, prices, seasons, weekdays and holidays (0.9.1)."""
        errors: dict[str, str] = {}
        placeholders = {"seasons_detail": "", "prices_detail": "", "rules_detail": "", "dates_detail": ""}
        if user_input is not None:
            user_input, errors, placeholders = check_tariff(self._current(), user_input)
        return self._section(SECTION_TARIFF, user_input, errors, placeholders)

    async def async_step_learned(self, user_input: dict[str, Any] | None = None):
        """Learned planner."""
        return self._section(SECTION_LEARNED, user_input)

    async def async_step_packs(self, user_input: dict[str, Any] | None = None):
        """Third-party packs."""
        errors: dict[str, str] = {}
        if user_input is not None:
            current = self._current(user_input)
            v_high = current.get(CONF_CAPACITY_V_HIGH, DEFAULT_CAPACITY_V_HIGH)
            v_low = current.get(CONF_CAPACITY_V_LOW, DEFAULT_CAPACITY_V_LOW)
            if float(v_low) >= float(v_high):
                errors[CONF_CAPACITY_V_LOW] = "invalid_voltage_range"
        return self._section(SECTION_PACKS, user_input, errors)

    async def async_step_notifications(self, user_input: dict[str, Any] | None = None):
        """Notifications and logging."""
        return self._section(SECTION_NOTIFICATIONS, user_input)

    async def async_step_classic(self, user_input: dict[str, Any] | None = None):
        """Classic planner (legacy)."""
        return self._section(SECTION_CLASSIC, user_input)

    # -----------------------------------------------------------------

    def _current(self, user_input: dict[str, Any] | None = None) -> dict[str, Any]:
        """What the form shows: setup data, then stored options, then what was just typed."""
        return {**self.config_entry.data, **self.config_entry.options, **(user_input or {})}

    def _section(self, section: str, user_input: dict[str, Any] | None,
                 errors: dict[str, str] | None = None, placeholders: dict[str, str] | None = None):
        errors = errors or {}
        if user_input is not None and not errors:
            return self.async_create_entry(
                title="", data=merge_section(dict(self.config_entry.options), user_input, section)
            )
        current = self._current(user_input)
        schema = vol.Schema(dict(_field(key, current) for key in SECTIONS[section]))
        if placeholders is not None:
            return self.async_show_form(step_id=section, data_schema=schema, errors=errors,
                                        description_placeholders=placeholders)
        return self.async_show_form(step_id=section, data_schema=schema, errors=errors)


# --- The options form fields -------------------------------------------------------------


def _number(lo: float, hi: float, step: float, unit: str | None = None) -> Any:
    cfg: dict[str, Any] = {"min": lo, "max": hi, "step": step, "mode": selector.NumberSelectorMode.BOX}
    if unit:
        cfg["unit_of_measurement"] = unit
    return selector.NumberSelector(selector.NumberSelectorConfig(**cfg))


def _sensor(multiple: bool = False) -> Any:
    if multiple:
        return selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", multiple=True))
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))


def _text(multiline: bool = False) -> Any:
    if multiline:
        return selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT,
                                                                 multiline=True))
    return selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT))


def _price() -> Any:
    return _number(0.0, 10.0, 0.0001, "$/kWh")


def _choice(options: list[str], translation_key: str | None = None) -> Any:
    cfg: dict[str, Any] = {"options": options, "mode": selector.SelectSelectorMode.DROPDOWN}
    if translation_key:
        cfg["translation_key"] = translation_key
    return selector.SelectSelector(selector.SelectSelectorConfig(**cfg))


# key: (default when unset, selector factory). Optional sensors have no default and are
# shown with their current value as a suggestion, so they can be cleared.
_FIELDS: dict[str, tuple[Any, Any]] = {
    CONF_BATTERY_SOC_ENTITY: ("", lambda: _sensor()),
    CONF_SOLAR_FORECAST_ENTITY: (DEFAULT_SOLAR_FORECAST_ENTITY, lambda: _sensor()),
    CONF_BATTERY_CAPACITY: (DEFAULT_BATTERY_CAPACITY, lambda: _number(0.5, 200.0, 0.5, "kWh")),
    CONF_BASE_LOAD: (DEFAULT_BASE_LOAD, lambda: _number(0.0, 10.0, 0.1, "kW")),
    CONF_MIN_SAFE_SOC: (DEFAULT_MIN_SAFE_SOC, lambda: _number(0.0, 100.0, 0.1, "kWh")),
    CONF_MIDPEAK_START: (DEFAULT_MIDPEAK_START, lambda: _number(0, 23, 1, "hour")),
    CONF_PEAK_START: (DEFAULT_PEAK_START, lambda: _number(0, 23, 1, "hour")),
    CONF_PEAK_END: (DEFAULT_PEAK_END, lambda: _number(1, 23, 1, "hour")),   # 24 would score on the next date
    CONF_WEEKDAYS_ONLY: (DEFAULT_WEEKDAYS_ONLY, lambda: selector.BooleanSelector()),
    CONF_OFFPEAK_PRICE: (None, lambda: _price()),
    CONF_MIDPEAK_PRICE: (DEFAULT_MIDPEAK_PRICE, lambda: _price()),
    CONF_PEAK_PRICE: (DEFAULT_PEAK_PRICE, lambda: _price()),
    CONF_TARIFF_SEASONS: (None, lambda: _text(multiline=True)),
    CONF_HOLIDAY_PRESET: (DEFAULT_HOLIDAY_PRESET, lambda: _choice(list(HOLIDAY_PRESETS), CONF_HOLIDAY_PRESET)),
    CONF_HOLIDAY_RULES: (None, lambda: _text(multiline=True)),
    CONF_HOLIDAY_DATES: (None, lambda: _text(multiline=True)),
    CONF_NOTIFICATIONS_ENABLED: (DEFAULT_NOTIFICATIONS_ENABLED, lambda: selector.BooleanSelector()),
    CONF_NOTIFY_ENTITY: (None, lambda: _text()),
    CONF_CHARGE_THRESHOLD: (DEFAULT_CHARGE_THRESHOLD, lambda: _number(0.0, 5.0, 0.1, "kWh")),
    CONF_SCHEDULE_HOURS: (DEFAULT_SCHEDULE_HOURS, lambda: _text()),
    CONF_SEASONAL_PRESERVATION: (DEFAULT_SEASONAL_PRESERVATION, lambda: selector.BooleanSelector()),
    CONF_SEASONAL_MONTHS: (DEFAULT_SEASONAL_MONTHS, lambda: _text()),
    CONF_VERBOSE_LOGGING: (DEFAULT_VERBOSE_LOGGING, lambda: selector.BooleanSelector()),
    CONF_SOLAR_ACTUAL_ENTITY: (None, lambda: _sensor()),
    CONF_PLANNER: (DEFAULT_PLANNER, lambda: _choice([PLANNER_CLASSIC, PLANNER_LEARNED], CONF_PLANNER)),
    CONF_GAUGE_ENTITY: (None, lambda: _sensor()),
    CONF_LOAD_POWER_ENTITY: (None, lambda: _sensor()),
    CONF_GRID_POWER_ENTITY: (None, lambda: _sensor()),
    CONF_PV_POWER_ENTITY: (None, lambda: _sensor()),
    CONF_SOLAR_FORECAST_TOMORROW_ENTITY: (None, lambda: _sensor()),
    CONF_FULL_CHARGE_MONTHS: (DEFAULT_FULL_CHARGE_MONTHS, lambda: _text()),
    CONF_LOAD_QUANTILE: (DEFAULT_LOAD_QUANTILE, lambda: _number(0.5, 0.99, 0.01)),
    CONF_SOLAR_CONFIDENCE: (DEFAULT_SOLAR_CONFIDENCE, lambda: _number(0.0, 1.5, 0.05)),
    CONF_GAUGE_FLOOR: (DEFAULT_GAUGE_FLOOR, lambda: _number(0, 50, 1, "%")),
    CONF_RECOVERY_PCT: (DEFAULT_RECOVERY_PCT, lambda: _number(0, 100, 1, "%")),
    CONF_PEAK_MARGIN_KWH: (DEFAULT_PEAK_MARGIN_KWH, lambda: _number(0.0, 10.0, 0.1, "kWh")),
    CONF_STALE_MINUTES: (DEFAULT_STALE_MINUTES, lambda: _number(0, 240, 1, "min")),
    CONF_PACK_CURRENT_ENTITIES: (None, lambda: _sensor(multiple=True)),
    CONF_PACK_CURRENT_CHARGE_POSITIVE: (DEFAULT_PACK_CURRENT_CHARGE_POSITIVE, lambda: selector.BooleanSelector()),
    CONF_BUS_VOLTAGE_ENTITY: (None, lambda: _sensor()),
    CONF_PACK_CAPACITY_AH: (DEFAULT_PACK_CAPACITY_AH, lambda: _number(1, 2000, 1, "Ah")),
    CONF_CAPACITY_V_HIGH: (DEFAULT_CAPACITY_V_HIGH, lambda: _number(0, 1000, 0.1, "V")),
    CONF_CAPACITY_V_LOW: (DEFAULT_CAPACITY_V_LOW, lambda: _number(0, 1000, 0.1, "V")),
}

# Lists the form edits as comma-separated text.
_CSV_KEYS = (CONF_SCHEDULE_HOURS, CONF_SEASONAL_MONTHS, CONF_FULL_CHARGE_MONTHS)

# The first-time flow (0.9.3). The learned planner's sensors, all optional:
LEARNED_SENSOR_KEYS: tuple[str, ...] = (
    CONF_GAUGE_ENTITY,
    CONF_LOAD_POWER_ENTITY,
    CONF_GRID_POWER_ENTITY,
    CONF_PV_POWER_ENTITY,
    CONF_SOLAR_FORECAST_TOMORROW_ENTITY,
)

# The first-time Tariff screen; the classic planner's calculation hours stay on it, last.
FIRST_TARIFF_KEYS: tuple[str, ...] = (
    CONF_MIDPEAK_START,
    CONF_PEAK_START,
    CONF_PEAK_END,
    CONF_WEEKDAYS_ONLY,
    CONF_OFFPEAK_PRICE,
    CONF_MIDPEAK_PRICE,
    CONF_PEAK_PRICE,
    CONF_HOLIDAY_PRESET,
    CONF_SCHEDULE_HOURS,
)


def first_planner(picked: dict[str, Any]) -> str:
    """The planner a new entry starts with: learned when it has the house load and grid
    sensors it learns from, else classic. An entry made before 0.9.3 has no planner key
    and stays classic (the absent-key default); only a new install is written here."""
    if picked.get(CONF_LOAD_POWER_ENTITY) and picked.get(CONF_GRID_POWER_ENTITY):
        return PLANNER_LEARNED
    return PLANNER_CLASSIC


def _field(key: str, current: dict[str, Any]) -> tuple[Any, Any]:
    """The schema marker and selector for one option, pre-filled from `current`."""
    default, make = _FIELDS[key]
    if default is None:
        empty: Any = [] if key == CONF_PACK_CURRENT_ENTITIES else ""
        value = current.get(key)
        if key == CONF_HOLIDAY_RULES:
            # the rules in force: a preset's own, or the typed ones for custom
            preset = normalize_preset(current.get(CONF_HOLIDAY_PRESET, DEFAULT_HOLIDAY_PRESET))
            if preset != HOLIDAY_PRESET_CUSTOM:
                value = preset_rules_text(preset)
        if value is None or value == "" or (isinstance(value, list) and not value):
            value = empty
        return vol.Optional(key, description={"suggested_value": value}), make()
    value = current.get(key, default)
    if key in _CSV_KEYS:
        value = _as_csv(value)
    elif key == CONF_HOLIDAY_PRESET:
        value = normalize_preset(value)
    elif key == CONF_PLANNER:
        value = PLANNER_LEARNED if str(value or "").strip().lower() == PLANNER_LEARNED else PLANNER_CLASSIC
    return vol.Required(key, default=value), make()


def _as_csv(value: Any) -> str:
    """Render a list setting as the comma-separated text the form edits."""
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value)
    return str(value)
