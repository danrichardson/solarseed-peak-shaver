"""Tests for const.py — verify all required constants are defined and consistent."""
from __future__ import annotations

import json
from pathlib import Path

from custom_components.solarseed_peak_shaver.const import (
    DOMAIN,
    VERSION,
    # Config keys
    CONF_BATTERY_CAPACITY,
    CONF_BASE_LOAD,
    CONF_MIN_SAFE_SOC,
    CONF_BATTERY_SOC_ENTITY,
    CONF_SOLAR_FORECAST_ENTITY,
    CONF_SOLAR_ACTUAL_ENTITY,
    CONF_MIDPEAK_START,
    CONF_PEAK_START,
    CONF_PEAK_END,
    CONF_SCHEDULE_HOURS,
    CONF_WEEKDAYS_ONLY,
    CONF_NOTIFICATIONS_ENABLED,
    CONF_NOTIFY_ENTITY,
    CONF_CHARGE_THRESHOLD,
    CONF_SEASONAL_PRESERVATION,
    CONF_SEASONAL_MONTHS,
    CONF_VERBOSE_LOGGING,
    # Sensor keys
    SENSOR_TARGET_SOC,
    SENSOR_CHARGE_NEEDED,
    SENSOR_PROJECTED_MIN,
    SENSOR_BATTERY_AT_PEAK,
    SENSOR_CHARGE_BELOW,
    SENSOR_DAILY_GRADE,
    SENSOR_SOLAR_ACCURACY,
    SENSOR_EFFECTIVE_BASE_LOAD,
    SENSOR_PREDICTION_ACCURACY,
    SENSOR_ROLLING_SCORE,
    # Events
    EVENT_CHARGE_START,
    EVENT_CHARGE_STOP,
    EVENT_PRESERVE_START,
    # Services
    SERVICE_RECALCULATE,
    SERVICE_PERFORMANCE_REPORT,
    SERVICE_EXPORT_HISTORY,
)


class TestConstants:
    """Verify all constants are properly defined."""

    def test_domain_format(self):
        assert DOMAIN == "solarseed_peak_shaver"
        assert "_" in DOMAIN  # must be snake_case for HA

    def test_version_format(self):
        parts = VERSION.split(".")
        assert len(parts) == 3
        for p in parts:
            assert p.isdigit()

    def test_event_names_prefixed_with_domain(self):
        assert EVENT_CHARGE_START.startswith(DOMAIN)
        assert EVENT_CHARGE_STOP.startswith(DOMAIN)
        assert EVENT_PRESERVE_START.startswith(DOMAIN)

    def test_service_names_snake_case(self):
        for service in [SERVICE_RECALCULATE, SERVICE_PERFORMANCE_REPORT, SERVICE_EXPORT_HISTORY]:
            assert service == service.lower()
            assert " " not in service

    def test_config_keys_snake_case(self):
        config_keys = [
            CONF_BATTERY_CAPACITY, CONF_BASE_LOAD, CONF_MIN_SAFE_SOC,
            CONF_BATTERY_SOC_ENTITY, CONF_SOLAR_FORECAST_ENTITY,
            CONF_SOLAR_ACTUAL_ENTITY, CONF_MIDPEAK_START, CONF_PEAK_START,
            CONF_PEAK_END, CONF_SCHEDULE_HOURS, CONF_WEEKDAYS_ONLY,
            CONF_NOTIFICATIONS_ENABLED, CONF_NOTIFY_ENTITY,
            CONF_CHARGE_THRESHOLD, CONF_SEASONAL_PRESERVATION,
            CONF_SEASONAL_MONTHS, CONF_VERBOSE_LOGGING,
        ]
        for key in config_keys:
            assert key == key.lower()
            assert " " not in key


class TestManifest:
    """Verify manifest.json matches constants and HACS requirements."""

    def _load_manifest(self) -> dict:
        manifest_path = (
            Path(__file__).parent.parent
            / "custom_components"
            / "solarseed_peak_shaver"
            / "manifest.json"
        )
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def test_domain_matches(self):
        manifest = self._load_manifest()
        assert manifest["domain"] == DOMAIN

    def test_version_matches(self):
        manifest = self._load_manifest()
        assert manifest["version"] == VERSION

    def test_required_fields(self):
        manifest = self._load_manifest()
        required = ["domain", "name", "version", "codeowners", "documentation"]
        for field in required:
            assert field in manifest, f"Missing required field: {field}"

    def test_config_flow_enabled(self):
        manifest = self._load_manifest()
        assert manifest.get("config_flow") is True

    def test_no_requirements(self):
        """Integration should have no pip dependencies (HA stdlib only)."""
        manifest = self._load_manifest()
        assert manifest.get("requirements", []) == []

    def test_iot_class(self):
        manifest = self._load_manifest()
        assert manifest["iot_class"] in [
            "local_polling", "local_push", "cloud_polling", "cloud_push",
            "calculated",
        ]


class TestHACS:
    """Verify HACS configuration."""

    def _load_hacs(self) -> dict:
        hacs_path = Path(__file__).parent.parent / "hacs.json"
        return json.loads(hacs_path.read_text(encoding="utf-8"))

    def test_hacs_json_exists(self):
        hacs_path = Path(__file__).parent.parent / "hacs.json"
        assert hacs_path.exists()

    def test_hacs_name(self):
        hacs = self._load_hacs()
        assert "name" in hacs
        assert len(hacs["name"]) > 0

    def test_hacs_render_readme(self):
        hacs = self._load_hacs()
        assert hacs.get("render_readme") is True

    def test_hacs_homeassistant_version(self):
        hacs = self._load_hacs()
        assert "homeassistant" in hacs
        # Should be a valid semver-ish string
        parts = hacs["homeassistant"].split(".")
        assert len(parts) == 3


class TestServiceDefinitions:
    """Verify services.yaml matches registered services."""

    def _load_services(self) -> dict:
        import yaml
        services_path = (
            Path(__file__).parent.parent
            / "custom_components"
            / "solarseed_peak_shaver"
            / "services.yaml"
        )
        return yaml.safe_load(services_path.read_text(encoding="utf-8"))

    def test_all_services_defined(self):
        try:
            services = self._load_services()
        except ImportError:
            pytest.skip("PyYAML not installed")
        assert SERVICE_RECALCULATE in services
        assert SERVICE_PERFORMANCE_REPORT in services
        assert SERVICE_EXPORT_HISTORY in services

    def test_export_history_has_fields(self):
        try:
            services = self._load_services()
        except ImportError:
            pytest.skip("PyYAML not installed")
        export = services[SERVICE_EXPORT_HISTORY]
        assert "fields" in export
        assert "days" in export["fields"]
        assert "format" in export["fields"]


class TestStrings:
    """Verify strings.json and translations/en.json are in sync and complete."""

    def _load_json(self, name: str) -> dict:
        base = (
            Path(__file__).parent.parent
            / "custom_components"
            / "solarseed_peak_shaver"
        )
        if name == "strings":
            path = base / "strings.json"
        else:
            path = base / "translations" / "en.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_strings_valid_json(self):
        data = self._load_json("strings")
        assert "config" in data

    def test_translations_valid_json(self):
        data = self._load_json("en")
        assert "config" in data

    def test_strings_match_translations(self):
        strings = self._load_json("strings")
        en = self._load_json("en")
        # Top-level keys should match
        assert set(strings.keys()) == set(en.keys())

    def test_services_in_strings(self):
        data = self._load_json("strings")
        services = data.get("services", {})
        assert SERVICE_RECALCULATE in services
        assert SERVICE_PERFORMANCE_REPORT in services
        assert SERVICE_EXPORT_HISTORY in services

    def test_sensor_entities_in_strings(self):
        data = self._load_json("strings")
        entities = data.get("entity", {}).get("sensor", {})
        for key in [
            SENSOR_DAILY_GRADE,
            SENSOR_SOLAR_ACCURACY,
            SENSOR_EFFECTIVE_BASE_LOAD,
            SENSOR_PREDICTION_ACCURACY,
            SENSOR_ROLLING_SCORE,
        ]:
            assert key in entities, f"Sensor {key} missing from strings.json entity section"


class TestDirectoryStructure:
    """Verify the integration has the expected file structure for HACS."""

    def test_required_files_exist(self):
        base = (
            Path(__file__).parent.parent
            / "custom_components"
            / "solarseed_peak_shaver"
        )
        required = [
            "__init__.py",
            "manifest.json",
            "config_flow.py",
            "const.py",
            "coordinator.py",
            "sensor.py",
            "button.py",
            "store.py",
            "diagnostics.py",
            "services.yaml",
            "strings.json",
        ]
        for f in required:
            assert (base / f).exists(), f"Missing required file: {f}"

    def test_translations_exist(self):
        base = (
            Path(__file__).parent.parent
            / "custom_components"
            / "solarseed_peak_shaver"
            / "translations"
        )
        assert (base / "en.json").exists()

    def test_hacs_json_at_root(self):
        root = Path(__file__).parent.parent
        assert (root / "hacs.json").exists()

    def test_readme_at_root(self):
        root = Path(__file__).parent.parent
        assert (root / "README.md").exists()
