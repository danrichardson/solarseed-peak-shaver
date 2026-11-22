"""Config flow for Solarseed Peak Shaver."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

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
    CONF_LOAD_POWER_ENTITY,
    CONF_LOAD_QUANTILE,
    CONF_MIDPEAK_START,
    CONF_NOTIFICATIONS_ENABLED,
    CONF_NOTIFY_ENTITY,
    CONF_PACK_CAPACITY_AH,
    CONF_PACK_CURRENT_CHARGE_POSITIVE,
    CONF_PACK_CURRENT_ENTITIES,
    CONF_PEAK_END,
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
    CONF_VERBOSE_LOGGING,
    CONF_WEEKDAYS_ONLY,
    DEFAULT_BASE_LOAD,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_CAPACITY_V_HIGH,
    DEFAULT_CAPACITY_V_LOW,
    DEFAULT_CHARGE_THRESHOLD,
    DEFAULT_FULL_CHARGE_MONTHS,
    DEFAULT_GAUGE_FLOOR,
    DEFAULT_LOAD_QUANTILE,
    DEFAULT_MIDPEAK_START,
    DEFAULT_NOTIFICATIONS_ENABLED,
    DEFAULT_PACK_CAPACITY_AH,
    DEFAULT_PACK_CURRENT_CHARGE_POSITIVE,
    DEFAULT_PEAK_END,
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
                return await self.async_step_schedule()

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

    async def async_step_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: peak hours and calculation schedule."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mid = user_input[CONF_MIDPEAK_START]
            peak = user_input[CONF_PEAK_START]
            end = user_input[CONF_PEAK_END]

            if mid >= peak:
                errors[CONF_PEAK_START] = "invalid_time_range"
            if peak >= end:
                errors[CONF_PEAK_END] = "invalid_time_range"

            if not errors:
                self._collected.update(user_input)
                return await self.async_step_notifications()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_MIDPEAK_START,
                    default=DEFAULT_MIDPEAK_START,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=23, step=1, unit_of_measurement="hour",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_PEAK_START,
                    default=DEFAULT_PEAK_START,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=23, step=1, unit_of_measurement="hour",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_PEAK_END,
                    default=DEFAULT_PEAK_END,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=24, step=1, unit_of_measurement="hour",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_WEEKDAYS_ONLY,
                    default=DEFAULT_WEEKDAYS_ONLY,
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_SCHEDULE_HOURS,
                    default=",".join(str(h) for h in DEFAULT_SCHEDULE_HOURS),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.TEXT,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="schedule",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 3: notifications and seasonal settings."""
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
    """Handle options for Solarseed Peak Shaver."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            v_high = user_input.get(CONF_CAPACITY_V_HIGH, DEFAULT_CAPACITY_V_HIGH)
            v_low = user_input.get(CONF_CAPACITY_V_LOW, DEFAULT_CAPACITY_V_LOW)
            if float(v_low) >= float(v_high):
                errors[CONF_CAPACITY_V_LOW] = "invalid_voltage_range"
            else:
                return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options, **(user_input or {})}

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_BATTERY_CAPACITY,
                    default=current.get(CONF_BATTERY_CAPACITY, DEFAULT_BATTERY_CAPACITY),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5, max=200.0, step=0.5, unit_of_measurement="kWh",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_BASE_LOAD,
                    default=current.get(CONF_BASE_LOAD, DEFAULT_BASE_LOAD),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0, max=10.0, step=0.1, unit_of_measurement="kW",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_MIN_SAFE_SOC,
                    default=current.get(CONF_MIN_SAFE_SOC, DEFAULT_MIN_SAFE_SOC),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0, max=100.0, step=0.1, unit_of_measurement="kWh",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_MIDPEAK_START,
                    default=current.get(CONF_MIDPEAK_START, DEFAULT_MIDPEAK_START),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=23, step=1, unit_of_measurement="hour",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_PEAK_START,
                    default=current.get(CONF_PEAK_START, DEFAULT_PEAK_START),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=23, step=1, unit_of_measurement="hour",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_PEAK_END,
                    default=current.get(CONF_PEAK_END, DEFAULT_PEAK_END),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=24, step=1, unit_of_measurement="hour",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_WEEKDAYS_ONLY,
                    default=current.get(CONF_WEEKDAYS_ONLY, DEFAULT_WEEKDAYS_ONLY),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_NOTIFICATIONS_ENABLED,
                    default=current.get(CONF_NOTIFICATIONS_ENABLED, DEFAULT_NOTIFICATIONS_ENABLED),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_NOTIFY_ENTITY,
                    default=current.get(CONF_NOTIFY_ENTITY, ""),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.TEXT,
                    )
                ),
                vol.Required(
                    CONF_CHARGE_THRESHOLD,
                    default=current.get(CONF_CHARGE_THRESHOLD, DEFAULT_CHARGE_THRESHOLD),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0, max=5.0, step=0.1, unit_of_measurement="kWh",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_SEASONAL_PRESERVATION,
                    default=current.get(CONF_SEASONAL_PRESERVATION, DEFAULT_SEASONAL_PRESERVATION),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_SEASONAL_MONTHS,
                    default=current.get(
                        CONF_SEASONAL_MONTHS,
                        ",".join(str(m) for m in DEFAULT_SEASONAL_MONTHS),
                    ),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.TEXT,
                    )
                ),
                vol.Required(
                    CONF_VERBOSE_LOGGING,
                    default=current.get(CONF_VERBOSE_LOGGING, DEFAULT_VERBOSE_LOGGING),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_SOLAR_ACTUAL_ENTITY,
                    description={"suggested_value": current.get(CONF_SOLAR_ACTUAL_ENTITY, "")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                # --- Learned planner (all optional) ---
                vol.Required(
                    CONF_PLANNER,
                    default=current.get(CONF_PLANNER, DEFAULT_PLANNER),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[PLANNER_CLASSIC, PLANNER_LEARNED],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_GAUGE_ENTITY,
                    description={"suggested_value": current.get(CONF_GAUGE_ENTITY, "")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_LOAD_POWER_ENTITY,
                    description={"suggested_value": current.get(CONF_LOAD_POWER_ENTITY, "")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_GRID_POWER_ENTITY,
                    description={"suggested_value": current.get(CONF_GRID_POWER_ENTITY, "")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_PV_POWER_ENTITY,
                    description={"suggested_value": current.get(CONF_PV_POWER_ENTITY, "")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_SOLAR_FORECAST_TOMORROW_ENTITY,
                    description={
                        "suggested_value": current.get(CONF_SOLAR_FORECAST_TOMORROW_ENTITY, "")
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(
                    CONF_FULL_CHARGE_MONTHS,
                    default=_as_csv(
                        current.get(CONF_FULL_CHARGE_MONTHS, DEFAULT_FULL_CHARGE_MONTHS)
                    ),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.TEXT,
                    )
                ),
                vol.Required(
                    CONF_LOAD_QUANTILE,
                    default=current.get(CONF_LOAD_QUANTILE, DEFAULT_LOAD_QUANTILE),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5, max=0.99, step=0.01,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_SOLAR_CONFIDENCE,
                    default=current.get(CONF_SOLAR_CONFIDENCE, DEFAULT_SOLAR_CONFIDENCE),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0, max=1.5, step=0.05,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_GAUGE_FLOOR,
                    default=current.get(CONF_GAUGE_FLOOR, DEFAULT_GAUGE_FLOOR),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=50, step=1, unit_of_measurement="%",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_RECOVERY_PCT,
                    default=current.get(CONF_RECOVERY_PCT, DEFAULT_RECOVERY_PCT),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=100, step=1, unit_of_measurement="%",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_PEAK_MARGIN_KWH,
                    default=current.get(CONF_PEAK_MARGIN_KWH, DEFAULT_PEAK_MARGIN_KWH),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0, max=10.0, step=0.1, unit_of_measurement="kWh",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_STALE_MINUTES,
                    default=current.get(CONF_STALE_MINUTES, DEFAULT_STALE_MINUTES),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=240, step=1, unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                # --- Third-party packs (all optional) ---
                vol.Optional(
                    CONF_PACK_CURRENT_ENTITIES,
                    description={"suggested_value": current.get(CONF_PACK_CURRENT_ENTITIES, [])},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", multiple=True)
                ),
                vol.Required(
                    CONF_PACK_CURRENT_CHARGE_POSITIVE,
                    default=current.get(
                        CONF_PACK_CURRENT_CHARGE_POSITIVE, DEFAULT_PACK_CURRENT_CHARGE_POSITIVE
                    ),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_BUS_VOLTAGE_ENTITY,
                    description={"suggested_value": current.get(CONF_BUS_VOLTAGE_ENTITY, "")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(
                    CONF_PACK_CAPACITY_AH,
                    default=current.get(CONF_PACK_CAPACITY_AH, DEFAULT_PACK_CAPACITY_AH),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=2000, step=1, unit_of_measurement="Ah",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_CAPACITY_V_HIGH,
                    default=current.get(CONF_CAPACITY_V_HIGH, DEFAULT_CAPACITY_V_HIGH),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=1000, step=0.1, unit_of_measurement="V",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_CAPACITY_V_LOW,
                    default=current.get(CONF_CAPACITY_V_LOW, DEFAULT_CAPACITY_V_LOW),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=1000, step=0.1, unit_of_measurement="V",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema, errors=errors)


def _as_csv(value: Any) -> str:
    """Render a list setting as the comma-separated text the form edits."""
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value)
    return str(value)
