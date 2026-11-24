"""The three blueprints (0.9.3): they import from their GitHub URL (the README's links, which
Home Assistant's importer turns into raw file URLs), their `source_url` is that same URL so a
re-import finds them, every `!input` is declared, each listens to the event the integration
fires, and each says what the mode is for, with the AC500 value as the example.

Checked against Home Assistant's blueprint schema as remembered from the core source
(`homeassistant/components/blueprint/schemas.py`); not imported into a live Home Assistant.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from custom_components.solarseed_peak_shaver.const import (  # noqa: E402
    EVENT_CHARGE_START,
    EVENT_CHARGE_STOP,
    EVENT_PRESERVE_START,
)

ROOT = Path(__file__).parent.parent
FOLDER = ROOT / "blueprints" / "automation" / "solarseed_peak_shaver"
REPO = "https://github.com/danrichardson/solarseed-peak-shaver"

# file: (event, the value input, the AC500 value)
BLUEPRINTS = {
    "charge_start.yaml": (EVENT_CHARGE_START, "charge_mode_value", "STANDARD"),
    "charge_stop.yaml": (EVENT_CHARGE_STOP, "solar_mode_value", "PV_PRIORITY"),
    "preserve_start.yaml": (EVENT_PRESERVE_START, "preserve_mode_value", "TIME_CONTROL"),
}

# The keys HA's BLUEPRINT_SCHEMA allows under `blueprint:`
ALLOWED_META = {"name", "description", "domain", "source_url", "author", "homeassistant", "input"}


class _Input(str):
    pass


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!input", lambda loader, node: _Input(loader.construct_scalar(node)))


def load(name: str) -> dict:
    return yaml.load((FOLDER / name).read_text(encoding="utf-8"), Loader=_Loader)


def inputs_used(node) -> set[str]:
    if isinstance(node, _Input):
        return {str(node)}
    if isinstance(node, dict):
        return set().union(*(inputs_used(v) for v in node.values())) if node else set()
    if isinstance(node, list):
        return set().union(*(inputs_used(v) for v in node)) if node else set()
    return set()


def url_of(name: str) -> str:
    return f"{REPO}/blob/main/blueprints/automation/solarseed_peak_shaver/{name}"


def test_there_are_exactly_three_and_no_download_markers():
    assert sorted(p.name for p in FOLDER.iterdir()) == sorted(BLUEPRINTS)


@pytest.mark.parametrize("name", list(BLUEPRINTS))
def test_the_blueprint_is_well_formed(name):
    text = (FOLDER / name).read_text(encoding="utf-8")
    assert text.isascii()
    bp = load(name)
    meta = bp["blueprint"]
    assert set(meta) <= ALLOWED_META
    assert meta["domain"] == "automation" and meta["name"].startswith("Solarseed - ")
    assert re.fullmatch(r"\d{4}\.\d{1,2}\.\d+", meta["homeassistant"]["min_version"])
    for key, spec in meta["input"].items():
        assert spec["name"] and spec["description"] and "selector" in spec, key
    assert inputs_used({k: v for k, v in bp.items() if k != "blueprint"}) == set(meta["input"])
    assert bp["mode"] == "single"


@pytest.mark.parametrize("name", list(BLUEPRINTS))
def test_source_url_is_the_file_itself_and_the_readme_links_it(name):
    meta = load(name)["blueprint"]
    assert meta["source_url"] == url_of(name)
    # HA's importer: https://github.com/<repo>/blob/<path> -> raw.githubusercontent.com/<repo>/<path>
    m = re.fullmatch(r"https://github\.com/(?P<repository>.+)/blob/(?P<path>.+)", meta["source_url"])
    assert m and m["path"] == f"main/blueprints/automation/solarseed_peak_shaver/{name}"
    assert url_of(name) in (ROOT / "README.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", list(BLUEPRINTS))
def test_it_listens_to_the_event_the_integration_fires(name):
    event, _, _ = BLUEPRINTS[name]
    triggers = load(name)["trigger"]
    assert triggers == [{"platform": "event", "event_type": event}]


@pytest.mark.parametrize("name", list(BLUEPRINTS))
def test_it_names_the_ac500_mode_and_what_the_mode_is_for(name):
    _, value_input, ac500 = BLUEPRINTS[name]
    meta = load(name)["blueprint"]
    assert "AC500" in meta["description"] and f"`{ac500}`" in meta["description"]
    assert "select.ac500_ups_mode" in meta["description"]
    assert f"AC500: {ac500}" in meta["input"][value_input]["description"]
    assert "learned planner" in meta["description"] and "classic planner (legacy)" in meta["description"]
