"""The options menu and the settings entities: which keys belong where, and how a save is
merged into the stored options (0.9.0).

Pure Python, no Home Assistant imports, so the merge rules are tested without HA.

Before 0.9.0 the options were one flat form that saved wholesale: whatever the form did not
show was dropped. Now each section of the menu, and each settings entity on the device
page, changes only its own keys and keeps every other stored option as it was, including
keys no form shows.
"""
from __future__ import annotations

from typing import Any

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
    CONF_HOLIDAY_PRESET,
    CONF_LOAD_POWER_ENTITY,
    CONF_LOAD_QUANTILE,
    CONF_MIDPEAK_START,
    CONF_MIN_SAFE_SOC,
    CONF_NOTIFICATIONS_ENABLED,
    CONF_NOTIFY_ENTITY,
    CONF_PACK_CAPACITY_AH,
    CONF_PACK_CURRENT_CHARGE_POSITIVE,
    CONF_PACK_CURRENT_ENTITIES,
    CONF_PEAK_END,
    CONF_PEAK_MARGIN_KWH,
    CONF_PEAK_START,
    CONF_PLANNER,
    CONF_PV_POWER_ENTITY,
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
)

SECTION_BATTERY = "battery"
SECTION_SCHEDULE = "schedule"
SECTION_LEARNED = "learned"
SECTION_PACKS = "packs"
SECTION_NOTIFICATIONS = "notifications"
SECTION_CLASSIC = "classic"

# The menu, in order, and the keys each section shows. Every option key is in exactly one.
SECTIONS: dict[str, tuple[str, ...]] = {
    SECTION_BATTERY: (
        CONF_BATTERY_SOC_ENTITY,
        CONF_GAUGE_ENTITY,
        CONF_LOAD_POWER_ENTITY,
        CONF_GRID_POWER_ENTITY,
        CONF_PV_POWER_ENTITY,
        CONF_SOLAR_FORECAST_ENTITY,
        CONF_SOLAR_FORECAST_TOMORROW_ENTITY,
        CONF_SOLAR_ACTUAL_ENTITY,
        CONF_BATTERY_CAPACITY,
        CONF_BASE_LOAD,
    ),
    SECTION_SCHEDULE: (
        CONF_MIDPEAK_START,
        CONF_PEAK_START,
        CONF_PEAK_END,
        CONF_WEEKDAYS_ONLY,
        CONF_HOLIDAY_PRESET,
    ),
    SECTION_LEARNED: (
        CONF_PLANNER,
        CONF_FULL_CHARGE_MONTHS,
        CONF_LOAD_QUANTILE,
        CONF_SOLAR_CONFIDENCE,
        CONF_GAUGE_FLOOR,
        CONF_PEAK_MARGIN_KWH,
        CONF_RECOVERY_PCT,
        CONF_STALE_MINUTES,
    ),
    SECTION_PACKS: (
        CONF_PACK_CURRENT_ENTITIES,
        CONF_PACK_CURRENT_CHARGE_POSITIVE,
        CONF_BUS_VOLTAGE_ENTITY,
        CONF_PACK_CAPACITY_AH,
        CONF_CAPACITY_V_HIGH,
        CONF_CAPACITY_V_LOW,
    ),
    SECTION_NOTIFICATIONS: (
        CONF_NOTIFICATIONS_ENABLED,
        CONF_NOTIFY_ENTITY,
        CONF_VERBOSE_LOGGING,
    ),
    SECTION_CLASSIC: (
        CONF_MIN_SAFE_SOC,
        CONF_CHARGE_THRESHOLD,
        CONF_SCHEDULE_HOURS,
        CONF_SEASONAL_PRESERVATION,
        CONF_SEASONAL_MONTHS,
    ),
}

# Optional fields: Home Assistant leaves a cleared one out of the submitted form. Stored as
# empty instead, because an absent option falls back to the setup data (the solar production
# sensor is there), and a cleared field must stay cleared.
CLEARED_VALUE: dict[str, Any] = {
    CONF_SOLAR_ACTUAL_ENTITY: "",
    CONF_GAUGE_ENTITY: "",
    CONF_LOAD_POWER_ENTITY: "",
    CONF_GRID_POWER_ENTITY: "",
    CONF_PV_POWER_ENTITY: "",
    CONF_SOLAR_FORECAST_TOMORROW_ENTITY: "",
    CONF_PACK_CURRENT_ENTITIES: [],
    CONF_BUS_VOLTAGE_ENTITY: "",
    CONF_NOTIFY_ENTITY: "",
}

# Settings that are read once, when the integration starts (timers, state listeners, the
# pack sensors). Saving a change to one of them reloads the entry, as a restart would.
# Everything else, including the six settings entities, is read live and needs no reload.
RELOAD_KEYS: tuple[str, ...] = (
    CONF_BATTERY_SOC_ENTITY,
    CONF_SOLAR_FORECAST_ENTITY,
    CONF_SOLAR_ACTUAL_ENTITY,
    CONF_MIDPEAK_START,
    CONF_PEAK_START,
    CONF_PEAK_END,
    CONF_SCHEDULE_HOURS,
    CONF_SEASONAL_PRESERVATION,
    CONF_PACK_CURRENT_ENTITIES,
)


def merge_section(stored: dict[str, Any], user_input: dict[str, Any], section: str) -> dict[str, Any]:
    """The options after saving one section: the stored options, with that section's
    fields replaced. Keys of other sections, and keys no form shows, are kept."""
    merged = dict(stored)
    for key in SECTIONS[section]:
        if key in CLEARED_VALUE and key not in user_input:
            merged[key] = CLEARED_VALUE[key]
    merged.update(user_input)
    return merged


def write_option(hass: Any, entry: Any, key: str, value: Any) -> bool:
    """Store one option, keeping every other one. Returns False when it was already set."""
    if key in entry.options and entry.options[key] == value:
        return False
    hass.config_entries.async_update_entry(entry, options={**entry.options, key: value})
    return True
