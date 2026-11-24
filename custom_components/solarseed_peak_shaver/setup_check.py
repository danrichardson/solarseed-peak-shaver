"""Is the integration set up so it can work? (0.9.3)

A stranger's install fails quietly in three ways: a sensor it was given does not exist (a
typo in the options, or the inverter integration renamed or removed it), the forecast is
not Solcast-shaped (no hourly detail, so both planners see no sun), or no automation acts
on the events (the blueprints were never imported, or their automations are disabled), so
the planner decides and nothing happens.

`find_problems` answers that from the states and the event bus's listener counts; it has
no Home Assistant dependency and is tested on its own. `SetupCheck` runs it every ten minutes once Home
Assistant is running, and turns each problem into a Home Assistant repair issue and one
log line. It logs only when a problem appears, changes or clears, never on every run; it
sends no notification and never acts. A missing reading that does exist (unavailable,
unknown) is not a setup problem: sensors go unavailable at startup and at night, and the
planners already treat it as missing.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Callable

from homeassistant.core import callback

from .const import (
    CONF_BATTERY_SOC_ENTITY,
    CONF_GAUGE_ENTITY,
    CONF_GRID_POWER_ENTITY,
    CONF_LOAD_POWER_ENTITY,
    CONF_PV_POWER_ENTITY,
    CONF_SOLAR_ACTUAL_ENTITY,
    CONF_SOLAR_FORECAST_ENTITY,
    CONF_SOLAR_FORECAST_TOMORROW_ENTITY,
    DOMAIN,
    EVENT_CHARGE_START,
    EVENT_CHARGE_STOP,
    EVENT_PRESERVE_START,
    PLANNER_LEARNED,
)

_LOGGER = logging.getLogger(__name__)

# Issue keys; each is also the translation key under "issues" in the string files.
ISSUE_MISSING_SENSORS = "missing_sensors"
ISSUE_FORECAST_SHAPE = "forecast_without_detail"
ISSUE_NO_AUTOMATIONS = "no_automations"
ISSUES = (ISSUE_MISSING_SENSORS, ISSUE_FORECAST_SHAPE, ISSUE_NO_AUTOMATIONS)

CHECK_EVERY = timedelta(minutes=10)
LEARN_MORE_URL = "https://github.com/danrichardson/solarseed-peak-shaver#installation"

# The forecast attributes `coordinator._get_hourly_solar` reads.
FORECAST_ATTRIBUTES = ("detailedHourly", "detailedForecast", "forecasts", "forecast")

# What each configured sensor is, in the words of the Battery and sensors form.
_SENSOR_LABELS: tuple[tuple[str, str], ...] = (
    (CONF_BATTERY_SOC_ENTITY, "Battery energy sensor (kWh)"),
    (CONF_SOLAR_FORECAST_ENTITY, "Solar forecast sensor (today)"),
    (CONF_SOLAR_FORECAST_TOMORROW_ENTITY, "Solar forecast sensor (tomorrow)"),
    (CONF_GAUGE_ENTITY, "Battery gauge (percent)"),
    (CONF_LOAD_POWER_ENTITY, "House load power"),
    (CONF_GRID_POWER_ENTITY, "Grid power into the inverter"),
    (CONF_PV_POWER_ENTITY, "Solar power"),
    (CONF_SOLAR_ACTUAL_ENTITY, "Solar production today"),
)


def configured_sensors(coord: Any) -> dict[str, str]:
    """{key: entity id} of every sensor the entry names (empty ones left out)."""
    ids = {
        CONF_BATTERY_SOC_ENTITY: coord.battery_soc_entity,
        CONF_SOLAR_FORECAST_ENTITY: coord.solar_forecast_entity,
        CONF_SOLAR_FORECAST_TOMORROW_ENTITY: coord._entity_cfg(CONF_SOLAR_FORECAST_TOMORROW_ENTITY),
        CONF_GAUGE_ENTITY: coord.gauge_entity,
        CONF_LOAD_POWER_ENTITY: coord.load_power_entity,
        CONF_GRID_POWER_ENTITY: coord.grid_power_entity,
        CONF_PV_POWER_ENTITY: coord.pv_power_entity,
        CONF_SOLAR_ACTUAL_ENTITY: coord.solar_actual_entity,
    }
    return {k: str(v or "").strip() for k, v in ids.items() if str(v or "").strip()}


def events_needed(coord: Any) -> tuple[str, ...]:
    """The events the planner in control fires. The learned planner uses all three (hold
    is `preserve_start`); the classic planner (legacy) fires the hold only with its
    off-peak hold switched on."""
    if coord.planner == PLANNER_LEARNED or coord.seasonal_preservation:
        return (EVENT_CHARGE_START, EVENT_CHARGE_STOP, EVENT_PRESERVE_START)
    return (EVENT_CHARGE_START, EVENT_CHARGE_STOP)


def find_problems(coord: Any, state_of: Callable[[str], Any],
                  listeners: dict[str, int] | None) -> dict[str, dict[str, str]]:
    """{issue key: translation placeholders} for each problem found; {} when all is well.

    `state_of` is `hass.states.get`; `listeners` is `hass.bus.async_listeners()`, or None
    when it cannot be read (then the automation check is skipped, never guessed).
    """
    problems: dict[str, dict[str, str]] = {}
    labels = dict(_SENSOR_LABELS)
    sensors = configured_sensors(coord)

    lines = [f"- {labels[k]}: {e} does not exist" for k, e in sensors.items() if state_of(e) is None]
    if coord.planner == PLANNER_LEARNED:
        for key in (CONF_LOAD_POWER_ENTITY, CONF_GRID_POWER_ENTITY):
            if key not in sensors:
                lines.append(f"- {labels[key]}: not set; the learned planner is in control and "
                             "cannot learn without it")
    if lines:
        problems[ISSUE_MISSING_SENSORS] = {"sensors": "\n".join(lines)}

    shapeless = []
    for key in (CONF_SOLAR_FORECAST_ENTITY, CONF_SOLAR_FORECAST_TOMORROW_ENTITY):
        state = state_of(sensors[key]) if key in sensors else None
        if state is None or str(getattr(state, "state", "")).strip().lower() in ("unavailable", "unknown", ""):
            continue                                    # missing is the issue above; unavailable is not judged
        attrs = getattr(state, "attributes", None) or {}
        if not any(a in attrs for a in FORECAST_ATTRIBUTES):
            shapeless.append(sensors[key])
    if shapeless:
        problems[ISSUE_FORECAST_SHAPE] = {"entities": ", ".join(shapeless)}

    if listeners is not None:
        silent = [e for e in events_needed(coord) if int(listeners.get(e, 0) or 0) <= 0]
        if silent:
            problems[ISSUE_NO_AUTOMATIONS] = {"events": "\n".join(f"- {e}" for e in silent)}
    return problems


class SetupCheck:
    """Runs `find_problems` every CHECK_EVERY once Home Assistant is running, and keeps
    one repair issue per problem. Started by `async_setup_entry`, stopped on unload."""

    def __init__(self, hass: Any, coord: Any, entry_id: str) -> None:
        self.hass = hass
        self.coord = coord
        self.entry_id = entry_id
        self.problems: dict[str, dict[str, str]] = {}
        self._first = True              # the first judged run also clears issues left from before
        self._failed_logged = False
        self._unsub: Callable[[], None] | None = None

    def issue_id(self, key: str) -> str:
        return f"{key}_{self.entry_id}"

    def start(self) -> None:
        from homeassistant.helpers.event import async_track_time_interval

        self._unsub = async_track_time_interval(self.hass, self._on_interval, CHECK_EVERY)

    def stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    @callback        # on the event loop: the issue registry and the bus are loop-only
    def _on_interval(self, _now: Any = None) -> None:
        try:
            self.run()
        except Exception:  # noqa: BLE001 - a check must never disturb the planners
            if not self._failed_logged:
                _LOGGER.exception("Setup check failed")
            self._failed_logged = True

    def _running(self) -> bool:
        from homeassistant.core import CoreState

        return getattr(self.hass, "state", None) == CoreState.running

    def _listeners(self) -> dict[str, int] | None:
        try:
            return dict(self.hass.bus.async_listeners())
        except Exception:  # noqa: BLE001 - not available: skip that check, do not guess
            return None

    def run(self) -> dict[str, dict[str, str]]:
        """One check. Before Home Assistant has started, nothing is judged (automations
        attach their triggers at start, and slow integrations add their sensors late)."""
        if not self._running():
            return self.problems
        from homeassistant.helpers import issue_registry as ir

        found = find_problems(self.coord, self.hass.states.get, self._listeners())
        for key in ISSUES:
            now, before = found.get(key), self.problems.get(key)
            if now is not None:
                if now != before:
                    ir.async_create_issue(
                        self.hass, DOMAIN, self.issue_id(key), is_fixable=False, is_persistent=False,
                        severity=ir.IssueSeverity.WARNING, translation_key=key,
                        translation_placeholders=now, learn_more_url=LEARN_MORE_URL)
                    _LOGGER.warning("Setup problem (%s): %s", key, "; ".join(
                        " ".join(v.split()) for v in now.values()))
            elif before is not None or self._first:
                ir.async_delete_issue(self.hass, DOMAIN, self.issue_id(key))   # also clears one left from before a restart
                if before is not None:
                    _LOGGER.info("Setup problem resolved (%s)", key)
        self.problems = found
        self._first = False
        return found


def remove_issues(hass: Any, entry_id: str) -> None:
    """Delete this entry's issues (the entry is being removed)."""
    from homeassistant.helpers import issue_registry as ir

    for key in ISSUES:
        ir.async_delete_issue(hass, DOMAIN, f"{key}_{entry_id}")
