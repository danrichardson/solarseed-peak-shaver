"""Home Assistant glue for the learned model and planner.

Runs once a minute. Every tick it:
  1. reads the gauge and the three power sensors and feeds the learner,
  2. asks the planner what the inverter should be doing,
  3. publishes that as sensors (always: this is "shadow mode"),
  4. and, only when the planner option is set to "learned", fires the integration's
     existing events so the blueprints switch the inverter, then checks from the power
     sensors that the inverter did what was asked.

Nothing in here may break the classic planner. Every entry point catches and logs.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change

from .const import (
    EVENT_CHARGE_START,
    EVENT_CHARGE_STOP,
    EVENT_PRESERVE_START,
    PLANNER_LEARNED,
)
from .learning import Learner, LoadProfile, build_from_samples, profile_from_hourly
from .planner import (
    MODE_CHARGE,
    MODE_DISCHARGE,
    MODE_HOLD,
    Decision,
    PlanInputs,
    decide,
    predict_gauge,
)

_LOGGER = logging.getLogger(__name__)

VERIFY_AFTER_MIN = 3        # minutes after a command before checking the inverter obeyed
VERIFY_RETRIES = 3
FULL_CONFIRM_MIN = 10       # minutes of "charging asked, nothing going in" that mean full
TOPUP_MAX_HOURS = 24        # a weekly top-up that has not finished by then is abandoned


def is_tou_day(d: date, weekdays_only: bool) -> bool:
    return d.weekday() < 5 if weekdays_only else True


def mode_matches(mode: str, gauge: float | None, grid_kw: float, load_kw: float, pv_kw: float,
                 floor: float, bank_full: bool) -> bool | None:
    """Does what the power sensors show agree with the commanded mode?

    Returns None when the readings cannot tell (for example on battery at the floor,
    where the grid legitimately carries the house).
    """
    if mode == MODE_CHARGE:
        if bank_full or (gauge is not None and gauge >= 99):
            return None
        return grid_kw > load_kw + 0.2
    if mode == MODE_DISCHARGE:
        if gauge is None or gauge <= floor + 2 or load_kw < 0.1:
            return None
        return grid_kw < 0.1
    if mode == MODE_HOLD:
        if load_kw < 0.15 or pv_kw > load_kw:
            return None
        return load_kw * 0.5 < grid_kw < load_kw + 0.3
    return None


class LearnedRuntime:
    """Owns the learner, the load profile and the planner state for one config entry."""

    def __init__(self, hass: HomeAssistant, coordinator: Any) -> None:
        self.hass = hass
        self.coord = coordinator
        self.learner = Learner()
        self.profile = LoadProfile(default_kw=coordinator.base_load_kw)
        self.decision: Decision | None = None
        self.bank_full = False
        self.topup_pending = False
        self._topup_day: str | None = None
        self.last_backfill: dict[str, Any] = {}
        self._unsub: list[CALLBACK_TYPE] = []
        self._last_tick: datetime | None = None
        self._day: date | None = None
        self._day_kwh: dict[int, float] = {}
        self._day_cover: dict[int, float] = {}
        self._commanded: str | None = None
        self._commanded_at: datetime | None = None
        self._retries = 0
        self._alerted = False
        self._idle_charge_min = 0
        self._shadow: dict[str, Any] = {}
        self._grid_kwh: dict[str, float] = {}
        self._dirty = False

    # -----------------------------------------------------------------
    # Setup, persistence
    # -----------------------------------------------------------------
    def setup(self) -> None:
        self.load_state(self.coord.store.learning)
        self._unsub.append(async_track_time_change(self.hass, self._on_minute, second=0))

    def remove(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()

    def load_state(self, blob: dict[str, Any]) -> None:
        try:
            self.learner = Learner.from_dict(blob.get("learner"))
            self.profile = LoadProfile.from_dict(blob.get("profile"), default_kw=self.coord.base_load_kw)
            self.topup_pending = bool(blob.get("topup_pending", False))
            self._topup_day = blob.get("topup_day") or None
            day = blob.get("day") or {}
            if day.get("date") == datetime.now().strftime("%Y-%m-%d"):
                self._day = datetime.now().date()
                self._day_kwh = {int(h): float(v) for h, v in (day.get("kwh") or {}).items()}
                self._day_cover = {int(h): float(v) for h, v in (day.get("cover") or {}).items()}
                self._shadow = dict(day.get("shadow") or {})
                self._grid_kwh = {str(k): float(v) for k, v in (day.get("grid_kwh") or {}).items()}
        except Exception:  # noqa: BLE001 - a bad blob must not stop the integration
            _LOGGER.exception("Could not restore learned model; starting empty")
            self.learner = Learner()
            self.profile = LoadProfile(default_kw=self.coord.base_load_kw)

    def dump_state(self) -> dict[str, Any]:
        return {
            "learner": self.learner.to_dict(),
            "profile": self.profile.to_dict(),
            "topup_pending": self.topup_pending,
            "topup_day": self._topup_day,
            "day": {
                "date": self._day.isoformat() if self._day else None,
                "kwh": {str(h): round(v, 4) for h, v in self._day_kwh.items()},
                "cover": {str(h): round(v, 3) for h, v in self._day_cover.items()},
                "shadow": self._shadow,
                "grid_kwh": {k: round(v, 3) for k, v in self._grid_kwh.items()},
            },
            "saved": datetime.now().isoformat(timespec="seconds"),
        }

    async def async_save(self) -> None:
        self.coord.store.learning = self.dump_state()
        await self.coord.store.async_save()
        self._dirty = False

    # -----------------------------------------------------------------
    # Reading sensors
    # -----------------------------------------------------------------
    def _float_state(self, entity_id: str) -> float | None:
        if not entity_id:
            return None
        st = self.hass.states.get(entity_id)
        if st is None:
            return None
        try:
            return float(str(st.state).strip())
        except (ValueError, TypeError):
            return None

    def _power_kw(self, entity_id: str) -> float | None:
        """A power sensor in kW, whatever unit it reports (W assumed if unlabeled)."""
        val = self._float_state(entity_id)
        if val is None:
            return None
        st = self.hass.states.get(entity_id)
        unit = str((getattr(st, "attributes", None) or {}).get("unit_of_measurement", "W")).strip().lower()
        if unit == "kw":
            return val
        if unit == "mw":
            return val * 1000.0
        return val / 1000.0

    def read_gauge(self) -> float | None:
        """Battery gauge in percent: the gauge entity if set, else SOC kWh over capacity."""
        c = self.coord
        if c.gauge_entity:
            return self._float_state(c.gauge_entity)
        soc = self._float_state(c.battery_soc_entity)
        if soc is None or c.battery_capacity <= 0:
            return None
        return soc / c.battery_capacity * 100.0

    @property
    def sensors_configured(self) -> bool:
        c = self.coord
        return bool(c.load_power_entity and c.grid_power_entity)

    # -----------------------------------------------------------------
    # The minute tick
    # -----------------------------------------------------------------
    @callback
    def _on_minute(self, now: datetime) -> None:
        try:
            self.tick(now.replace(tzinfo=None))
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Learned planner tick failed")

    def tick(self, now: datetime) -> None:
        c = self.coord
        hours = (now - self._last_tick).total_seconds() / 3600.0 if self._last_tick else 0.0
        self._last_tick = now

        gauge = self.read_gauge()
        grid = self._power_kw(c.grid_power_entity)
        load = self._power_kw(c.load_power_entity)
        pv = self._power_kw(c.pv_power_entity) or 0.0

        self._roll_day(now)

        if None not in (gauge, grid, load) and 0 < hours <= Learner.MAX_SAMPLE_HOURS:
            self.learner.sample(gauge, max(grid, 0.0), max(load, 0.0), max(pv, 0.0), hours)
            self._day_kwh[now.hour] = self._day_kwh.get(now.hour, 0.0) + max(load, 0.0) * hours
            self._day_cover[now.hour] = self._day_cover.get(now.hour, 0.0) + hours
            period = c._classify_period(now) if is_tou_day(now.date(), c.weekdays_only) else "off-peak"
            self._grid_kwh[period] = self._grid_kwh.get(period, 0.0) + max(grid, 0.0) * hours
            self._dirty = True
        elif hours > Learner.MAX_SAMPLE_HOURS or None in (gauge, grid, load):
            self.learner.sample(0.0, 0.0, 0.0, 0.0, 0.0)       # gap: drop the open stretch

        self._update_bank_full(gauge, grid, load)
        self._update_topup(now)

        self.decision = self._decide(now, gauge)
        self._record_shadow(now, gauge)

        if c.planner == PLANNER_LEARNED:
            self._act(now, gauge, grid, load, pv)
        else:
            self._commanded = None

        if now.minute == 0 and self._dirty:
            self.hass.async_create_task(self.async_save())
        if hasattr(c, "async_update_listeners"):
            c.async_update_listeners()

    def _roll_day(self, now: datetime) -> None:
        today = now.date()
        if self._day is None:
            self._day = today
            return
        if today == self._day:
            return
        c = self.coord
        # only hours that were actually observed for most of the hour count
        full = {h: v / self._day_cover[h] for h, v in self._day_kwh.items() if self._day_cover.get(h, 0) >= 0.75}
        self.profile.observe_day(is_tou_day(self._day, c.weekdays_only), full)
        self.learner.age(float(max((today - self._day).days, 1)))
        self._day = today
        self._day_kwh, self._day_cover, self._shadow, self._grid_kwh = {}, {}, {}, {}
        self.hass.async_create_task(self.async_save())

    def _update_bank_full(self, gauge: float | None, grid: float | None, load: float | None) -> None:
        if gauge is None:
            return
        if gauge >= 100:
            self.bank_full = True
            self._idle_charge_min = 0
            return
        if gauge < 98:
            self.bank_full = False
            self._idle_charge_min = 0
            return
        # 98-99 %: full if a charge was asked for and nothing is going in
        if self._commanded == MODE_CHARGE and None not in (grid, load) and grid - load < 0.15:
            self._idle_charge_min += 1
            if self._idle_charge_min >= FULL_CONFIRM_MIN:
                self.bank_full = True
        else:
            self._idle_charge_min = 0

    def _update_topup(self, now: datetime) -> None:
        c = self.coord
        today_tou = is_tou_day(now.date(), c.weekdays_only)
        tomorrow_tou = is_tou_day(now.date() + timedelta(days=1), c.weekdays_only)
        # Owed once, from peak end on the last TOU day of the week.
        if today_tou and not tomorrow_tou and now.hour >= c.peak_end and self._topup_day != now.date().isoformat():
            self._topup_day = now.date().isoformat()
            self.topup_pending = not self.bank_full
            self._dirty = True
            return
        if not self.topup_pending:
            return
        try:
            began = datetime.combine(date.fromisoformat(self._topup_day or ""), time(c.peak_end % 24))
        except ValueError:
            began = now - timedelta(hours=TOPUP_MAX_HOURS)
        expired = now >= began + timedelta(hours=TOPUP_MAX_HOURS)
        next_week = (tomorrow_tou and now.hour >= c.peak_end) or (today_tou and now.date() > began.date())
        if self.bank_full or expired or next_week:
            self.topup_pending = False
            self._dirty = True

    def _inputs(self, now: datetime, gauge: float | None) -> PlanInputs:
        c = self.coord
        return PlanInputs(
            now=now,
            gauge=gauge,
            is_tou_today=is_tou_day(now.date(), c.weekdays_only),
            is_tou_tomorrow=is_tou_day(now.date() + timedelta(days=1), c.weekdays_only),
            midpeak_start=c.midpeak_start,
            peak_start=c.peak_start,
            peak_end=c.peak_end,
            floor=c.gauge_floor,
            full_months=tuple(c.full_charge_months),
            load_quantile=c.load_quantile,
            solar_confidence=c.solar_confidence,
            solar_today=c._get_hourly_solar(quiet=True),
            solar_tomorrow=(c._get_hourly_solar(c.solar_forecast_tomorrow_entity_resolved, quiet=True)
                            or c._get_hourly_solar(quiet=True)),
            bank_full=self.bank_full,
            topup_pending=self.topup_pending,
            current_mode=self._commanded if c.planner == PLANNER_LEARNED else None,
        )

    def _decide(self, now: datetime, gauge: float | None) -> Decision:
        return decide(self._inputs(now, gauge), self.learner, self.profile)

    # -----------------------------------------------------------------
    # Shadow bookkeeping (what the learned planner thought, for the daily scorecard)
    # -----------------------------------------------------------------
    def _record_shadow(self, now: datetime, gauge: float | None) -> None:
        c, d, s = self.coord, self.decision, self._shadow
        if d is None:
            return
        if d.phase == "night" and d.target_gauge is not None and now.hour < c.midpeak_start:
            s["night_target_gauge"] = round(d.target_gauge, 1)
            if d.need_kwh is not None:
                s["night_need_kwh"] = round(d.need_kwh, 2)
        if d.mode == MODE_CHARGE and d.phase == "mid-peak":
            s["midpeak_charge_wanted"] = True
        if gauge is None or now.minute != 0:
            return
        if now.hour == c.midpeak_start:
            solar = c._get_hourly_solar(quiet=True)
            s["gauge_midpeak_start"] = round(gauge, 1)
            s["pred_gauge_peak_start"] = round(predict_gauge(
                self.learner, self.profile, solar, gauge, c.midpeak_start, c.peak_start, c.gauge_floor,
                c.solar_confidence), 1)
            s["pred_gauge_peak_end"] = round(predict_gauge(
                self.learner, self.profile, solar, gauge, c.midpeak_start, c.peak_end, c.gauge_floor,
                c.solar_confidence), 1)
            s["load_forecast_kwh"] = round(self.profile.window_mean(True, c.midpeak_start, c.peak_end), 2)
            s["energy_remaining_kwh"] = round(self.learner.discharge.energy_between(c.gauge_floor, gauge), 2)
        elif now.hour == c.peak_start:
            s["gauge_peak_start"] = round(gauge, 1)
        elif now.hour == c.peak_end % 24:
            s["gauge_peak_end"] = round(gauge, 1)

    def daily_summary(self) -> dict[str, Any]:
        """Fields added to the daily scorecard (new keys only)."""
        c = self.coord
        out = dict(self._shadow)
        out["planner"] = c.planner
        out["model_ready"] = bool(self.decision.model_ready) if self.decision else False
        out["load_actual_kwh"] = round(sum(
            v for h, v in self._day_kwh.items() if c.midpeak_start <= h < c.peak_end), 2)
        out["grid_kwh"] = {k: round(v, 2) for k, v in self._grid_kwh.items()}
        return out

    # -----------------------------------------------------------------
    # Acting (planner option = learned)
    # -----------------------------------------------------------------
    def _fire(self, mode: str, gauge: float | None) -> None:
        c, d = self.coord, self.decision
        soc = self._float_state(c.battery_soc_entity) or 0.0
        data = {
            "current_soc": round(soc, 2),
            "planner": PLANNER_LEARNED,
            "gauge": None if gauge is None else round(gauge, 1),
            "target_gauge": None if d is None or d.target_gauge is None else round(d.target_gauge, 1),
            "reason": d.reason if d else "",
        }
        event = {MODE_CHARGE: EVENT_CHARGE_START, MODE_DISCHARGE: EVENT_CHARGE_STOP,
                 MODE_HOLD: EVENT_PRESERVE_START}[mode]
        self.hass.bus.async_fire(event, data)

    def _act(self, now: datetime, gauge: float | None, grid: float | None, load: float | None,
             pv: float) -> None:
        d = self.decision
        if d is None:
            return
        if d.mode != self._commanded:
            _LOGGER.info("Learned planner: %s -> %s (%s)", self._commanded, d.mode, d.reason)
            self._fire(d.mode, gauge)
            if self._commanded is not None or d.mode != MODE_DISCHARGE:
                self.coord._notify("Solarseed - %s" % d.mode.capitalize(), d.reason)
            self._commanded, self._commanded_at = d.mode, now
            self._retries, self._alerted = 0, False
            return
        if self._commanded_at is None or None in (grid, load):
            return
        waited = (now - self._commanded_at).total_seconds() / 60.0
        if waited < VERIFY_AFTER_MIN * (self._retries + 1):
            return
        ok = mode_matches(d.mode, gauge, grid, load, pv, self.coord.gauge_floor, self.bank_full)
        if ok is False:
            if self._retries < VERIFY_RETRIES:
                self._retries += 1
                _LOGGER.warning("Inverter does not look like it is in %s mode; sending the command again (%d/%d)",
                                d.mode, self._retries, VERIFY_RETRIES)
                self._fire(d.mode, gauge)
                self._commanded_at = now
            elif not self._alerted:
                self._alerted = True
                _LOGGER.error("Inverter did not follow the %s command after %d attempts", d.mode, VERIFY_RETRIES)
                self.coord._notify(
                    "Solarseed - inverter not responding",
                    "Asked for %s mode %d times; the power readings do not match. Check the inverter."
                    % (d.mode, VERIFY_RETRIES + 1))
        elif ok:
            self._retries = 0

    # -----------------------------------------------------------------
    # Backfill from the recorder
    # -----------------------------------------------------------------
    async def async_backfill(self, days: int = 10, profile_days: int = 45) -> dict[str, Any]:
        """Rebuild the learned model from recorder statistics instead of starting cold."""
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import statistics_during_period
        from homeassistant.util import dt as dt_util

        c = self.coord
        gauge_id = c.gauge_entity or c.battery_soc_entity
        ids = [i for i in (gauge_id, c.grid_power_entity, c.load_power_entity, c.pv_power_entity) if i]
        if not (gauge_id and c.grid_power_entity and c.load_power_entity):
            return {"error": "Set the gauge, grid power and load power entities first."}
        end = dt_util.utcnow()
        rec = get_instance(self.hass)
        fine = await rec.async_add_executor_job(
            statistics_during_period, self.hass, end - timedelta(days=days), end, set(ids), "5minute", None, {"mean"})
        hourly = await rec.async_add_executor_job(
            statistics_during_period, self.hass, end - timedelta(days=profile_days), end,
            {c.load_power_entity}, "hour", None, {"mean"})

        def local(ts: Any) -> datetime:
            if isinstance(ts, datetime):
                return dt_util.as_local(ts).replace(tzinfo=None)
            sec = float(ts) / 1000.0 if float(ts) > 1e11 else float(ts)
            return dt_util.as_local(dt_util.utc_from_timestamp(sec)).replace(tzinfo=None)

        def series(rows: list | None, scale: float) -> dict[datetime, float]:
            return {local(r["start"]): r["mean"] * scale for r in (rows or []) if r.get("mean") is not None}

        def kw_scale(entity_id: str) -> float:
            st = self.hass.states.get(entity_id)
            unit = str((getattr(st, "attributes", None) or {}).get("unit_of_measurement", "W")).strip().lower()
            return 1.0 if unit == "kw" else 1000.0 if unit == "mw" else 0.001

        g_scale = 1.0 if c.gauge_entity else (100.0 / c.battery_capacity if c.battery_capacity > 0 else 1.0)
        g = series(fine.get(gauge_id), g_scale)
        grid = series(fine.get(c.grid_power_entity), kw_scale(c.grid_power_entity))
        load = series(fine.get(c.load_power_entity), kw_scale(c.load_power_entity))
        pv = series(fine.get(c.pv_power_entity), kw_scale(c.pv_power_entity)) if c.pv_power_entity else {}
        samples = [(t, g.get(t), grid.get(t), load.get(t), pv.get(t, 0.0), 5.0 / 60.0) for t in sorted(g)]
        load_h = series(hourly.get(c.load_power_entity), kw_scale(c.load_power_entity))
        today = dt_util.now().date()
        rows = [(t, v) for t, v in sorted(load_h.items()) if t.date() < today]

        self.learner = build_from_samples(samples)
        self.profile = profile_from_hourly(rows, lambda d: is_tou_day(d, c.weekdays_only),
                                           LoadProfile(default_kw=c.base_load_kw))
        await self.async_save()
        self.last_backfill = {
            "samples": len(samples),
            "discharge_points": round(sum(self.learner.discharge.p), 1),
            "grid_charge_points": round(sum(self.learner.grid_charge.p), 1),
            "solar_charge_points": round(sum(self.learner.solar_charge.p), 1),
            "tou_days": self.profile.n_days(True),
            "other_days": self.profile.n_days(False),
            "energy_floor_to_full_kwh": round(self.learner.discharge.energy_between(c.gauge_floor, 100.0), 2),
            "load_midpeak_to_peak_end_kwh": round(self.profile.window_mean(True, c.midpeak_start, c.peak_end), 2),
        }
        return self.last_backfill

    # -----------------------------------------------------------------
    # For sensors and diagnostics
    # -----------------------------------------------------------------
    def curve_table(self) -> list[dict[str, Any]]:
        ln = self.learner
        out = []
        for i in range(ln.discharge.n):
            out.append({
                "from": int(i * ln.discharge.bin_pts),
                "to": int(min(100, (i + 1) * ln.discharge.bin_pts)),
                "discharge_kwh_per_pct": round(ln.discharge.per_pt(i), 3),
                "discharge_weight": round(ln.discharge.weight(i), 1),
                "charge_kwh_per_pct": round(ln.grid_charge.per_pt(i), 3),
                "charge_hours_per_pct": round(ln.grid_charge.hours_per_pt(i), 3),
                "charge_weight": round(ln.grid_charge.weight(i), 1),
            })
        return out
