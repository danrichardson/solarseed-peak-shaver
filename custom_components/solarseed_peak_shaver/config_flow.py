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
    CONF_CHARGE_THRESHOLD,
    CONF_MIDPEAK_START,
    CONF_NOTIFICATIONS_ENABLED,
    CONF_NOTIFY_ENTITY,
    CONF_PEAK_END,
    CONF_PEAK_START,
    CONF_MIN_SAFE_SOC,
    CONF_SCHEDULE_HOURS,
    CONF_SEASONAL_MONTHS,
    CONF_SEASONAL_PRESERVATION,
    CONF_SOLAR_ACTUAL_ENTITY,
    CONF_SOLAR_FORECAST_ENTITY,
    CONF_VERBOSE_LOGGING,
    CONF_WEEKDAYS_ONLY,
    DEFAULT_BASE_LOAD,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_CHARGE_THRESHOLD,
    DEFAULT_MIDPEAK_START,
    DEFAULT_NOTIFICATIONS_ENABLED,
    DEFAULT_PEAK_END,
    DEFAULT_PEAK_START,
    DEFAULT_MIN_SAFE_SOC,
    DEFAULT_SCHEDULE_HOURS,
    DEFAULT_SEASONAL_MONTHS,
    DEFAULT_SEASONAL_PRESERVATION,
    DEFAULT_SOLAR_ACTUAL_ENTITY,
    DEFAULT_SOLAR_FORECAST_ENTITY,
    DEFAULT_VERBOSE_LOGGING,
    DEFAULT_WEEKDAYS_ONLY,
    DOMAIN,
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
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}

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
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)
