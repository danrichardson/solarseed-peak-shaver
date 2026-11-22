"""Options form checks (HA mocked). Skipped where voluptuous is not installed (CI)."""
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
    CONF_PACK_CURRENT_ENTITIES,
    CONF_RECOVERY_PCT,
    CONF_STALE_MINUTES,
)

STRINGS = Path(__file__).parent.parent / "custom_components" / "solarseed_peak_shaver" / "strings.json"


def make_flow(options=None):
    flow = PeakShaverOptionsFlow()
    flow.config_entry = SimpleNamespace(data={}, options=dict(options or {}))
    flow.async_create_entry = MagicMock(return_value="created")
    flow.async_show_form = MagicMock(return_value="form")
    return flow


def test_every_option_has_a_label():
    flow = make_flow()
    asyncio.run(flow.async_step_init(None))
    schema = flow.async_show_form.call_args.kwargs["data_schema"]
    labels = json.loads(STRINGS.read_text(encoding="utf-8"))["options"]["step"]["init"]["data"]
    keys = {str(k) for k in schema.schema}
    for key in (CONF_RECOVERY_PCT, CONF_STALE_MINUTES, CONF_PACK_CURRENT_ENTITIES, CONF_CAPACITY_V_HIGH):
        assert key in keys
    missing = keys - set(labels)
    assert not missing, missing


def test_lower_voltage_must_be_below_the_upper():
    flow = make_flow()
    out = asyncio.run(flow.async_step_init({CONF_CAPACITY_V_HIGH: 51.0, CONF_CAPACITY_V_LOW: 52.0}))
    assert out == "form"
    assert flow.async_show_form.call_args.kwargs["errors"] == {CONF_CAPACITY_V_LOW: "invalid_voltage_range"}
    flow.async_create_entry.assert_not_called()


def test_valid_input_is_saved():
    flow = make_flow()
    data = {CONF_CAPACITY_V_HIGH: 53.0, CONF_CAPACITY_V_LOW: 51.5, CONF_STALE_MINUTES: 20}
    assert asyncio.run(flow.async_step_init(data)) == "created"
    assert flow.async_create_entry.call_args.kwargs["data"] == data
