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
    CONF_HOLIDAY_DATES,
    CONF_HOLIDAY_PRESET,
    CONF_HOLIDAY_RULES,
    CONF_LOAD_POWER_ENTITY,
    CONF_LOAD_QUANTILE,
    CONF_MIDPEAK_PRICE,
    CONF_MIDPEAK_START,
    CONF_MIN_SAFE_SOC,
    CONF_NOTIFICATIONS_ENABLED,
    CONF_NOTIFY_ENTITY,
    CONF_OFFPEAK_PRICE,
    CONF_PACK_CAPACITY_AH,
    CONF_PACK_CURRENT_CHARGE_POSITIVE,
    CONF_PACK_CURRENT_ENTITIES,
    CONF_PEAK_END,
    CONF_PEAK_MARGIN_KWH,
    CONF_PEAK_PRICE,
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
    CONF_TARIFF_SEASONS,
    CONF_VERBOSE_LOGGING,
    CONF_WEEKDAYS_ONLY,
    DEFAULT_HOLIDAY_PRESET,
    DEFAULT_MIDPEAK_START,
    DEFAULT_PEAK_END,
    DEFAULT_PEAK_START,
)
from .holidays import (
    HOLIDAY_PRESET_CUSTOM,
    normalize_preset,
    parse_dates,
    parse_rules,
    preset_rules_text,
    same_rules,
)
from .tariff import PERIOD_MIDPEAK, PERIOD_OFFPEAK, PERIOD_PEAK, Windows, parse_seasons, price_problem

SECTION_BATTERY = "battery"
SECTION_TARIFF = "tariff"           # was "schedule" in 0.9.0: the hours, now with prices and seasons
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
    SECTION_TARIFF: (
        CONF_MIDPEAK_START,
        CONF_PEAK_START,
        CONF_PEAK_END,
        CONF_WEEKDAYS_ONLY,
        CONF_OFFPEAK_PRICE,
        CONF_MIDPEAK_PRICE,
        CONF_PEAK_PRICE,
        CONF_TARIFF_SEASONS,
        CONF_HOLIDAY_PRESET,
        CONF_HOLIDAY_RULES,
        CONF_HOLIDAY_DATES,
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
    CONF_OFFPEAK_PRICE: "",
    CONF_TARIFF_SEASONS: "",
    CONF_HOLIDAY_RULES: "",
    CONF_HOLIDAY_DATES: "",
}

# Settings that are read once, when the integration starts (timers, state listeners, the
# pack sensors). Saving a change to one of them reloads the entry, as a restart would.
# Everything else, including the six settings entities, the prices and the holidays, is read
# live and needs no reload. The seasons are here for their hours (the timers); a change to a
# season's months or prices alone does not reload (`setup_signature` compares hours).
RELOAD_KEYS: tuple[str, ...] = (
    CONF_BATTERY_SOC_ENTITY,
    CONF_SOLAR_FORECAST_ENTITY,
    CONF_SOLAR_ACTUAL_ENTITY,
    CONF_MIDPEAK_START,
    CONF_PEAK_START,
    CONF_PEAK_END,
    CONF_TARIFF_SEASONS,
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


def _float_or_none(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def check_tariff(previous: dict[str, Any], user_input: dict[str, Any]
                 ) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    """The Tariff section as submitted: what to save, the errors, and the plain messages
    the errors show (description placeholders).

    `previous` is what the form showed (setup data and stored options). A holiday preset
    that was just chosen fills the rules field with its rules; rules edited under a preset
    make it custom. A tariff that does not fit the planner's cheap, middle, dear day is
    refused with the reason.
    """
    data = dict(user_input)
    current = {**previous, **data}
    errors: dict[str, str] = {}
    detail = {"seasons_detail": "", "prices_detail": "", "rules_detail": "", "dates_detail": ""}

    def hour(key: str, default: int) -> int:
        try:
            return int(float(current.get(key, default)))
        except (TypeError, ValueError):
            return default

    mid, peak, end = (hour(CONF_MIDPEAK_START, DEFAULT_MIDPEAK_START), hour(CONF_PEAK_START, DEFAULT_PEAK_START),
                      hour(CONF_PEAK_END, DEFAULT_PEAK_END))
    if mid > peak:
        errors[CONF_PEAK_START] = "invalid_time_range"
    if peak >= end:
        errors[CONF_PEAK_END] = "invalid_time_range"
    windows = Windows(mid, peak, end)

    prices = {PERIOD_OFFPEAK: _float_or_none(current.get(CONF_OFFPEAK_PRICE)),
              PERIOD_MIDPEAK: _float_or_none(current.get(CONF_MIDPEAK_PRICE)),
              PERIOD_PEAK: _float_or_none(current.get(CONF_PEAK_PRICE))}
    problem = price_problem(prices, windows.has_midpeak)
    if problem:
        errors[CONF_PEAK_PRICE] = "invalid_prices"
        detail["prices_detail"] = problem

    _, season_errors = parse_seasons(data.get(CONF_TARIFF_SEASONS, ""), prices, windows)
    if season_errors:
        errors[CONF_TARIFF_SEASONS] = "invalid_seasons"
        detail["seasons_detail"] = "; ".join(season_errors[:2])

    before = normalize_preset(previous.get(CONF_HOLIDAY_PRESET, DEFAULT_HOLIDAY_PRESET))
    chosen = normalize_preset(data.get(CONF_HOLIDAY_PRESET, before))
    typed = str(data.get(CONF_HOLIDAY_RULES, "") or "")
    if chosen != HOLIDAY_PRESET_CUSTOM:
        preset_text = preset_rules_text(chosen) or ""
        if chosen != before or same_rules(typed, preset_text):
            typed = preset_text                     # the preset fills the field
        else:
            chosen = HOLIDAY_PRESET_CUSTOM          # its rules were edited
    data[CONF_HOLIDAY_PRESET] = chosen
    data[CONF_HOLIDAY_RULES] = typed
    if chosen == HOLIDAY_PRESET_CUSTOM:
        rule_errors = parse_rules(typed)[1]
        if rule_errors:
            errors[CONF_HOLIDAY_RULES] = "invalid_holiday_rules"
            detail["rules_detail"] = "; ".join(rule_errors[:2])

    date_errors = parse_dates(data.get(CONF_HOLIDAY_DATES, ""))[1]
    if date_errors:
        errors[CONF_HOLIDAY_DATES] = "invalid_holiday_dates"
        detail["dates_detail"] = "; ".join(date_errors[:2])
    return data, errors, detail


def write_option(hass: Any, entry: Any, key: str, value: Any) -> bool:
    """Store one option, keeping every other one. Returns False when it was already set."""
    if key in entry.options and entry.options[key] == value:
        return False
    hass.config_entries.async_update_entry(entry, options={**entry.options, key: value})
    return True
