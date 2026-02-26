"""
Mock stubs for homeassistant packages so tests can run without
installing the full Home Assistant package (which requires Python <3.14).

This module is imported by conftest.py before any custom_components code.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Build a mock hierarchy for every homeassistant.* import the integration uses
# ---------------------------------------------------------------------------

_HA_MODULES = [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.event",
    "homeassistant.helpers.storage",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.selector",
    "homeassistant.helpers.entity_platform",
    "homeassistant.components",
    "homeassistant.components.button",
    "homeassistant.components.sensor",
]


def install_ha_mocks() -> None:
    """Inject mock modules into sys.modules for HA imports."""
    for mod_name in _HA_MODULES:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = MagicMock()

    # --- Constants the integration actually references at import time ---
    ha_const = sys.modules["homeassistant.const"]
    ha_const.Platform = MagicMock()
    ha_const.Platform.SENSOR = "sensor"
    ha_const.Platform.BUTTON = "button"
    ha_const.UnitOfEnergy = MagicMock()
    ha_const.UnitOfEnergy.KILO_WATT_HOUR = "kWh"
    ha_const.UnitOfPower = MagicMock()
    ha_const.UnitOfPower.KILO_WATT = "kW"

    ha_core = sys.modules["homeassistant.core"]
    ha_core.HomeAssistant = MagicMock
    ha_core.ServiceCall = MagicMock
    ha_core.Event = MagicMock
    ha_core.callback = lambda f: f  # just passthrough
    ha_core.CALLBACK_TYPE = object
    ha_core.SupportsResponse = MagicMock()
    ha_core.SupportsResponse.ONLY = "only"

    ha_config_entries = sys.modules["homeassistant.config_entries"]
    ha_config_entries.ConfigEntry = MagicMock
    ha_config_entries.ConfigFlow = MagicMock
    ha_config_entries.OptionsFlow = MagicMock

    ha_helpers_event = sys.modules["homeassistant.helpers.event"]
    ha_helpers_event.async_track_state_change_event = MagicMock()
    ha_helpers_event.async_track_time_change = MagicMock()

    ha_helpers_storage = sys.modules["homeassistant.helpers.storage"]
    ha_helpers_storage.Store = MagicMock

    ha_update_coordinator = sys.modules["homeassistant.helpers.update_coordinator"]
    # DataUpdateCoordinator needs to be a real class so our coordinator can inherit
    class _FakeDataUpdateCoordinator:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__(**kwargs)

        def __class_getitem__(cls, item):
            return cls

        def __init__(self, hass, logger, *, name=None, update_interval=None):
            self.hass = hass
            self.logger = logger
            self.name = name
            self.data = {}

        async def async_request_refresh(self):
            pass

        def async_set_updated_data(self, data):
            self.data = data

    ha_update_coordinator.DataUpdateCoordinator = _FakeDataUpdateCoordinator
    ha_update_coordinator.UpdateFailed = Exception

    # Sensor / Button entity bases
    ha_sensor = sys.modules["homeassistant.components.sensor"]
    ha_sensor.SensorEntity = MagicMock
    ha_sensor.SensorDeviceClass = MagicMock()
    ha_sensor.SensorDeviceClass.ENERGY = "energy"
    ha_sensor.SensorDeviceClass.POWER = "power"
    ha_sensor.SensorStateClass = MagicMock()
    ha_sensor.SensorStateClass.MEASUREMENT = "measurement"

    ha_button = sys.modules["homeassistant.components.button"]
    ha_button.ButtonEntity = MagicMock

    # CoordinatorEntity
    ha_helpers = sys.modules["homeassistant.helpers"]
    ha_helpers.entity_platform = sys.modules["homeassistant.helpers.entity_platform"]

    # Add update_coordinator.CoordinatorEntity (used by sensor.py and button.py)
    class _FakeCoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator

    ha_update_coordinator.CoordinatorEntity = _FakeCoordinatorEntity


# Run on import
install_ha_mocks()
