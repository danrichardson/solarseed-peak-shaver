"""Persistent storage for Solarseed Peak Shaver performance data."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = f"{DOMAIN}_history"
STORAGE_VERSION = 1
MAX_DAYS = 90


class PeakShaverStore:
    """Manage persistent storage of daily performance scorecards."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the store."""
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, Any] = {
            "version": STORAGE_VERSION,
            "days": [],
        }

    async def async_load(self) -> None:
        """Load data from disk."""
        data = await self._store.async_load()
        if data and isinstance(data, dict):
            self._data = data

    async def async_save(self) -> None:
        """Save data to disk, pruning to MAX_DAYS."""
        self._data["days"] = self._data["days"][-MAX_DAYS:]
        await self._store.async_save(self._data)

    @property
    def days(self) -> list[dict]:
        """Return all stored daily scorecards."""
        return self._data.get("days", [])

    def add_scorecard(self, scorecard: dict) -> None:
        """Add or replace a daily scorecard."""
        date = scorecard.get("date")
        self._data["days"] = [
            d for d in self._data.get("days", []) if d.get("date") != date
        ]
        self._data["days"].append(scorecard)

    # -----------------------------------------------------------------
    # Rolling averages
    # -----------------------------------------------------------------
    def rolling_solar_accuracy(self, days: int = 14) -> float:
        """Return rolling ratio of actual/predicted solar (1.0 = perfect)."""
        recent = self.days[-days:]
        ratios: list[float] = []
        for d in recent:
            predicted = d.get("solar_predicted_kwh", 0)
            actual = d.get("solar_actual_kwh")
            if actual is not None and predicted > 0:
                ratios.append(actual / predicted)
        return sum(ratios) / len(ratios) if ratios else 1.0

    def rolling_base_load(self, days: int = 14) -> float | None:
        """Return rolling average effective base load in kW."""
        recent = self.days[-days:]
        loads = [
            d["effective_base_load_kw"]
            for d in recent
            if d.get("effective_base_load_kw") is not None
        ]
        return round(sum(loads) / len(loads), 2) if loads else None

    def rolling_prediction_error(self, days: int = 7) -> float | None:
        """Return rolling average battery minimum prediction error (kWh).

        Positive = predicted higher than actual (optimistic).
        Negative = predicted lower than actual (conservative).
        """
        recent = self.days[-days:]
        errors = [
            d["min_prediction_error_kwh"]
            for d in recent
            if d.get("min_prediction_error_kwh") is not None
        ]
        return round(sum(errors) / len(errors), 2) if errors else None

    def rolling_score(self, days: int = 7) -> float | None:
        """Return rolling average performance score (0-100)."""
        recent = self.days[-days:]
        scores = [d["score"] for d in recent if d.get("score") is not None]
        return round(sum(scores) / len(scores), 1) if scores else None

    def rolling_margin(self, days: int = 14) -> float | None:
        """Return rolling average headroom above floor (kWh).

        High positive = algorithm is conservative (battery never gets close to floor).
        Near zero or negative = floor was nearly breached or breached.
        """
        recent = self.days[-days:]
        margins: list[float] = []
        for d in recent:
            actual_min = d.get("battery_min_actual")
            min_safe = d.get("min_safe_soc")
            if actual_min is not None and min_safe is not None:
                margins.append(actual_min - min_safe)
        return round(sum(margins) / len(margins), 2) if margins else None

    def hourly_solar_ratios(self, days: int = 14) -> dict[int, float]:
        """Return per-hour actual/predicted solar ratios for correction."""
        hour_actuals: dict[int, list[float]] = {}
        hour_predictions: dict[int, list[float]] = {}

        recent = self.days[-days:]
        for d in recent:
            hourly_actual = d.get("hourly_solar_actual", {})
            hourly_predicted = d.get("hourly_solar_predicted", {})
            for h_str, actual in hourly_actual.items():
                h = int(h_str)
                predicted = hourly_predicted.get(h_str, 0)
                if predicted > 0.05:  # ignore near-zero predictions
                    hour_actuals.setdefault(h, []).append(actual)
                    hour_predictions.setdefault(h, []).append(predicted)

        ratios: dict[int, float] = {}
        for h in hour_actuals:
            total_actual = sum(hour_actuals[h])
            total_predicted = sum(hour_predictions[h])
            if total_predicted > 0:
                ratios[h] = total_actual / total_predicted
        return ratios

    def recent_grades(self, days: int = 7) -> list[str]:
        """Return recent letter grades."""
        recent = self.days[-days:]
        return [d.get("grade", "?") for d in recent]

    # -----------------------------------------------------------------
    # Export
    # -----------------------------------------------------------------
    def export_csv(self, days: int | None = None) -> str:
        """Export scorecard history as CSV.

        Flat columns suitable for pandas / SPC analysis / Claude ingestion.
        """
        records = self.days[-days:] if days else self.days
        if not records:
            return ""

        columns = [
            "date",
            "grade",
            "score",
            "solar_predicted_kwh",
            "solar_actual_kwh",
            "solar_accuracy_pct",
            "battery_at_midpeak_predicted",
            "battery_at_midpeak_actual",
            "midpeak_prediction_error_kwh",
            "battery_min_predicted",
            "battery_min_actual",
            "min_prediction_error_kwh",
            "min_safe_soc",
            "floor_breached",
            "midpeak_charge_triggered",
            "total_charged_kwh",
            "unnecessary_charge_kwh",
            "effective_base_load_kw",
            "solar_correction_factor",
            "charge_surplus_kwh",
            "margin_above_floor_kwh",
        ]

        lines = [",".join(columns)]
        for d in records:
            # Derived columns for SPC
            actual_min = d.get("battery_min_actual")
            min_safe = d.get("min_safe_soc")
            margin = (
                round(actual_min - min_safe, 2)
                if actual_min is not None and min_safe is not None
                else ""
            )
            # charge_surplus = how much actual minimum exceeded predicted
            predicted_min = d.get("battery_min_predicted")
            surplus = (
                round(actual_min - predicted_min, 2)
                if actual_min is not None and predicted_min is not None
                else ""
            )

            row = [
                str(d.get("date", "")),
                str(d.get("grade", "")),
                str(d.get("score", "")),
                str(d.get("solar_predicted_kwh", "")),
                str(d.get("solar_actual_kwh", "") or ""),
                str(d.get("solar_accuracy_pct", "") or ""),
                str(d.get("battery_at_midpeak_predicted", "")),
                str(d.get("battery_at_midpeak_actual", "") or ""),
                str(d.get("midpeak_prediction_error_kwh", "") or ""),
                str(d.get("battery_min_predicted", "")),
                str(d.get("battery_min_actual", "") or ""),
                str(d.get("min_prediction_error_kwh", "") or ""),
                str(d.get("min_safe_soc", "")),
                str(d.get("floor_breached", "")),
                str(d.get("midpeak_charge_triggered", "")),
                str(d.get("total_charged_kwh", "")),
                str(d.get("unnecessary_charge_kwh", "")),
                str(d.get("effective_base_load_kw", "") or ""),
                str(d.get("solar_correction_factor", "")),
                str(surplus),
                str(margin),
            ]
            lines.append(",".join(row))

        return "\n".join(lines)

    def export_hourly_solar_csv(self, days: int | None = None) -> str:
        """Export per-hour solar predicted vs actual as CSV.

        One row per day per hour. This is the data you need for
        per-hour forecast error analysis.
        """
        records = self.days[-days:] if days else self.days
        if not records:
            return ""

        lines = ["date,hour,solar_predicted_kwh,solar_actual_kwh,error_kwh,ratio"]
        for d in records:
            predicted = d.get("hourly_solar_predicted", {})
            actual = d.get("hourly_solar_actual", {})
            all_hours = sorted(
                set(int(h) for h in list(predicted.keys()) + list(actual.keys()))
            )
            for h in all_hours:
                p = predicted.get(str(h), 0)
                a = actual.get(str(h))
                if a is None:
                    continue
                error = round(a - p, 3)
                ratio = round(a / p, 3) if p > 0.05 else ""
                lines.append(
                    f"{d.get('date', '')},{h},{p},{a},{error},{ratio}"
                )

        return "\n".join(lines)
