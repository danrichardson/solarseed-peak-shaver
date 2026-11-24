"""Home Assistant glue for the learned model and planner.

Runs once a minute. Every tick it:
  1. reads the gauge and the three power sensors and feeds the learner,
  2. asks the planner what the inverter should be doing,
  3. publishes that as sensors (always: this is "shadow mode"),
  4. and, only when the planner option is set to "learned", fires the integration's
     existing events so the blueprints switch the inverter, then checks from the power
     sensors that the inverter did what was asked.

Battery readings that stop changing count as missing (the data path has frozen for
hours with healthy-looking values): no learning, the planner's no-gauge fallbacks, one
alert per episode. The first acting tick after a start never releases a hold or stops
a charge; if no command was restored it reads the inverter's mode from the power
sensors so the planner's hysteresis carries on where it was.

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
from .holidays import is_last_tou_day_of_week, is_tou_day  # noqa: F401 - is_tou_day re-exported
from .learning import Learner, LoadProfile, build_from_samples, profile_from_hourly
from .packs import PackTracker
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
VERIFY_RETRIES = 3          # per commanded mode; not replenished until the mode changes
VERIFY_MISMATCH_MIN = 2     # consecutive minutes of disagreement before sending again
GAUGE_GRACE_MIN = 15        # minutes a missing gauge is bridged with its last reading
TICK_FAILS_FAILSAFE = 10    # consecutive failed ticks before returning the inverter to battery
IDLE_POWER_KW = 0.01        # every power sensor at or under this (10 W) means nothing is moving
PUBLISH_EVERY_MIN = 5       # sensors are refreshed on a change, and at least this often
FULL_CONFIRM_MIN = 10       # minutes of "charging asked, nothing going in" that mean full
FULL_GAUGE_PCT = 99.0       # at or above this a hold and a discharge look the same
TOPUP_MAX_HOURS = 24        # a weekly top-up that has not finished by then is abandoned

# Sibling sensors of a pack's current sensor ("..._current"), found by name.
PACK_VOLTAGE_SUFFIXES = ("_voltage",)
PACK_SOC_SUFFIXES = ("_battery", "_soc", "_state_of_charge", "_battery_level")


def infer_mode(gauge: float | None, grid_kw: float | None, load_kw: float | None, pv_kw: float,
               floor: float) -> str | None:
    """Which mode the power sensors say the inverter is in, or None if they cannot tell."""
    if grid_kw is None or load_kw is None:
        return None
    if grid_kw > load_kw + 0.2:
        return MODE_CHARGE
    if load_kw < 0.15 or pv_kw > load_kw:
        return None
    if grid_kw < 0.1:
        # A full bank in hold carries the house from the battery until the gauge drops
        # off 100 (about 30 min on the AC500, 2026-11-23): it looks exactly like discharge.
        if gauge is None or gauge >= FULL_GAUGE_PCT:
            return None
        return MODE_DISCHARGE
    if gauge is not None and gauge <= floor + 2:
        return None                     # at the floor the grid carries the house in any mode
    if load_kw * 0.5 < grid_kw < load_kw + 0.3:
        return MODE_HOLD
    return None


def mode_matches(mode: str, gauge: float | None, grid_kw: float, load_kw: float, pv_kw: float,
                 floor: float, bank_full: bool) -> bool | None:
    """Does what the power sensors show agree with the commanded mode?

    Returns None when the readings cannot tell (for example on battery at the floor,
    where the grid legitimately carries the house).
    """
    if mode == MODE_CHARGE:
        # near the top the charger tapers and may legitimately take almost nothing
        if bank_full or gauge is None or gauge >= 95:
            return None
        return grid_kw > load_kw + 0.2
    if mode == MODE_DISCHARGE:
        if gauge is None or gauge <= floor + 2 or load_kw < 0.1:
            return None
        return grid_kw < 0.1
    if mode == MODE_HOLD:
        if load_kw < 0.15 or pv_kw > load_kw:
            return None
        # Full: the inverter runs the house from the battery before it passes the grid
        # through (2026-11-23: AC in 0 W for about 30 min after a charge ended at 100 %).
        if bank_full or gauge is None or gauge >= FULL_GAUGE_PCT:
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
        self._commanded_phase: str | None = None
        self._retries = 0
        self._mismatch_min = 0
        self._alerted = False
        self._idle_charge_min = 0
        self._full_at: float | None = None
        self._last_gauge: float | None = None
        self._last_gauge_at: datetime | None = None
        self._first_tick: datetime | None = None
        self._tick_fails = 0
        self._failsafe_sent = False
        self._first_act = True          # the first acting tick never releases a hold or stops a charge
        self._seen: dict[str, float] = {}
        self._last_change: datetime | None = None
        self.data_stale = False
        self._stale_since: datetime | None = None
        self._stale_alerted = False
        self._published_key: Any = None
        self.packs: PackTracker | None = None
        self._packs_blob: dict[str, Any] = {}
        self._packs_cfg: Any = None
        self._packs_fails = 0
        self._shadow: dict[str, Any] = {}
        self._grid_kwh: dict[str, float] = {}
        self._dirty = False

    # -----------------------------------------------------------------
    # Setup, persistence
    # -----------------------------------------------------------------
    def setup(self) -> None:
        """Start the minute timer. Call load_state() first."""
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
            packs = blob.get("packs")
            self._packs_blob = packs if isinstance(packs, dict) else {}
            self.packs, self._packs_cfg = None, None
            if blob.get("bank_full"):
                self.bank_full = True
                self._full_at = float(blob.get("full_at") or 100.0)
            self._topup_day = blob.get("topup_day") or None
            cmd = blob.get("commanded") or {}
            try:
                age = (datetime.now() - datetime.fromisoformat(cmd.get("at", ""))).total_seconds()
            except (TypeError, ValueError):
                age = None
            if cmd.get("mode") in (MODE_CHARGE, MODE_DISCHARGE, MODE_HOLD) and age is not None and 0 <= age < 5400:
                self._commanded, self._commanded_phase = cmd["mode"], cmd.get("phase")
                self._commanded_at = datetime.fromisoformat(cmd["at"])
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
            "bank_full": self.bank_full,
            "full_at": self._full_at,
            "commanded": {
                "mode": self._commanded,
                "phase": self._commanded_phase,
                "at": self._commanded_at.isoformat(timespec="seconds") if self._commanded_at else None,
            },
            "day": {
                "date": self._day.isoformat() if self._day else None,
                "kwh": {str(h): round(v, 4) for h, v in self._day_kwh.items()},
                "cover": {str(h): round(v, 3) for h, v in self._day_cover.items()},
                "shadow": self._shadow,
                "grid_kwh": {k: round(v, 3) for k, v in self._grid_kwh.items()},
            },
            "packs": self.packs.to_dict() if self.packs is not None else self._packs_blob,
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
            self._tick_fails = 0
            self._failsafe_sent = False
        except Exception:  # noqa: BLE001
            self._tick_fails += 1
            if self._tick_fails == 1 or self._tick_fails % 60 == 0:
                _LOGGER.exception("Learned planner tick failed (%d in a row)", self._tick_fails)
            self._failsafe()

    def _failsafe(self) -> None:
        """If the planner keeps failing while in control, put the inverter back on battery once."""
        try:
            if (self._tick_fails < TICK_FAILS_FAILSAFE or self._failsafe_sent
                    or self.coord.planner != PLANNER_LEARNED):
                return
            self._failsafe_sent = True
            self._commanded = None
            _LOGGER.error("Learned planner failed %d times in a row; returning the inverter to battery mode",
                          self._tick_fails)
            self.hass.bus.async_fire(EVENT_CHARGE_STOP, {"planner": PLANNER_LEARNED, "reason": "planner failure"})
            self.coord._notify("Solarseed - planner error",
                               "The learned planner keeps failing. Inverter returned to battery mode. Check the log.")
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Learned planner failsafe failed")

    def tick(self, now: datetime) -> None:
        c = self.coord
        hours = (now - self._last_tick).total_seconds() / 3600.0 if self._last_tick else 0.0
        self._last_tick = now

        if self._first_tick is None:
            self._first_tick = now
        gauge = self.read_gauge()
        grid = self._power_kw(c.grid_power_entity)
        load = self._power_kw(c.load_power_entity)
        pv = self._power_kw(c.pv_power_entity)
        pv_ok = pv is not None or not c.pv_power_entity     # a configured but unreadable PV sensor is a gap

        self._roll_day(now)
        self._update_staleness(now, hours)
        if self.data_stale:                                 # frozen readings count as missing
            gauge = grid = load = pv = None
            pv_ok = not c.pv_power_entity
        pv = pv or 0.0

        if None not in (gauge, grid, load) and pv_ok and 0 < hours <= Learner.MAX_SAMPLE_HOURS:
            self.learner.sample(gauge, max(grid, 0.0), max(load, 0.0), max(pv, 0.0), hours)
            self._day_kwh[now.hour] = self._day_kwh.get(now.hour, 0.0) + max(load, 0.0) * hours
            self._day_cover[now.hour] = self._day_cover.get(now.hour, 0.0) + hours
            period = c._classify_period(now) if c.is_tou_day(now.date()) else "off-peak"
            self._grid_kwh[period] = self._grid_kwh.get(period, 0.0) + max(grid, 0.0) * hours
            self._dirty = True
        elif hours > Learner.MAX_SAMPLE_HOURS or None in (gauge, grid, load) or not pv_ok:
            self.learner.sample(0.0, 0.0, 0.0, 0.0, 0.0)       # gap: drop the open stretch

        self._update_bank_full(gauge, grid, load)
        self._update_topup(now)

        # Planning bridges a short gauge dropout with the last reading (learning never does).
        # A frozen gauge is not bridged: its last reading is exactly what is in doubt.
        if gauge is not None:
            self._last_gauge, self._last_gauge_at = gauge, now
        plan_gauge = gauge
        if plan_gauge is None and self._last_gauge_at is not None and not self.data_stale:
            if (now - self._last_gauge_at).total_seconds() <= GAUGE_GRACE_MIN * 60:
                plan_gauge = self._last_gauge

        in_control = c.planner == PLANNER_LEARNED
        # right after a restart sensors can take a while
        starting_blind = (plan_gauge is None
                          and (now - self._first_tick).total_seconds() < GAUGE_GRACE_MIN * 60)
        if in_control and not starting_blind and self._first_act and self._commanded is None:
            self._adopt_inverter_mode(now, plan_gauge, grid, load, pv)

        self.decision = self._decide(now, plan_gauge)
        self._record_shadow(now, gauge)
        self._tick_packs(now, gauge, grid, load, pv)

        if in_control:
            if not starting_blind:
                self._act(now, plan_gauge, grid, load, pv)
        elif self._commanded is not None:
            # Control was just handed back to the classic planner. Do not leave the
            # inverter charging or holding until classic's next scheduled run.
            if self._commanded in (MODE_CHARGE, MODE_HOLD):
                _LOGGER.info("Planner switched to classic while in %s mode; returning to battery", self._commanded)
                self.hass.bus.async_fire(EVENT_CHARGE_STOP, {"planner": PLANNER_LEARNED, "reason": "handover to classic"})
            self._commanded, self._commanded_phase, self._commanded_at = None, None, None
            self._first_act = True          # a later takeover starts from the inverter's actual mode
            self._dirty = True

        if now.minute == 0 and self._dirty:
            self.hass.async_create_task(self.async_save())
        d = self.decision
        key = (d.mode, d.phase, None if d.target_gauge is None else round(d.target_gauge),
               None if plan_gauge is None else round(plan_gauge), self.bank_full, self.topup_pending, c.planner)
        if hasattr(c, "async_update_listeners") and (key != self._published_key or now.minute % PUBLISH_EVERY_MIN == 0):
            self._published_key = key
            c.async_update_listeners()

    # -----------------------------------------------------------------
    # Third-party packs (ROADMAP items 1 and 2; optional)
    # -----------------------------------------------------------------
    def pack_tracker(self) -> PackTracker | None:
        """The pack tracker for the configured packs, or None when none are configured."""
        c = self.coord
        ids = c.pack_current_entities
        if not ids:
            return None
        cfg = (tuple(ids), c.capacity_v_high, c.capacity_v_low, c.pack_capacity_ah)
        if self.packs is None or self._packs_cfg != cfg:
            blob = self.packs.to_dict() if self.packs is not None else self._packs_blob
            self.packs = PackTracker.from_dict(blob, ids, c.capacity_v_high, c.capacity_v_low,
                                               c.pack_capacity_ah)
            self._packs_cfg = cfg
        return self.packs

    def sibling(self, current_id: str, suffixes: tuple[str, ...]) -> str | None:
        """A sensor of the same pack, by name: sensor.x_current -> sensor.x_voltage."""
        if not current_id.endswith("_current"):
            return None
        base = current_id[: -len("_current")]
        for suffix in suffixes:
            if self.hass.states.get(base + suffix) is not None:
                return base + suffix
        return None

    def bus_voltage(self) -> float | None:
        """The configured bus voltage sensor, else the mean of the packs' own voltages."""
        c = self.coord
        if c.bus_voltage_entity:
            return self._float_state(c.bus_voltage_entity)
        vals = []
        for p in c.pack_current_entities:
            e = self.sibling(p, PACK_VOLTAGE_SUFFIXES)
            v = self._float_state(e) if e else None
            if v is not None:
                vals.append(v)
        return sum(vals) / len(vals) if vals else None

    def pack_current(self, entity_id: str) -> float | None:
        """A pack's current in amps, positive into the pack."""
        val = self._float_state(entity_id)
        if val is None:
            return None
        st = self.hass.states.get(entity_id)
        unit = str((getattr(st, "attributes", None) or {}).get("unit_of_measurement", "A")).strip().lower()
        if unit == "ma":
            val /= 1000.0
        return val if self.coord.pack_current_charge_positive else -val

    def _tick_packs(self, now: datetime, gauge: float | None, grid: float | None,
                    load: float | None, pv: float) -> None:
        try:
            tracker = self.pack_tracker()
            if tracker is None:
                return
            currents = {p: self.pack_current(p) for p in tracker.packs}
            battery_ac = None if None in (grid, load) else load - grid - (pv or 0.0)
            if tracker.tick(now, gauge, self.bus_voltage(), currents, battery_ac):
                pt = tracker.points[-1]
                _LOGGER.info("Pack capacity run recorded (%.1f-%.1f V, %.1f h, %.2f kWh AC): %s",
                             pt["v_high"], pt["v_low"], pt["hours"], pt["ac_kwh"],
                             ", ".join("%s %.1f Ah" % (k, v) for k, v in pt["ah"].items()))
                self.hass.async_create_task(self.async_save())
            self._dirty = True
            self._packs_fails = 0
        except Exception:  # noqa: BLE001 - pack tracking must never disturb the planner
            self._packs_fails += 1
            if self._packs_fails == 1 or self._packs_fails % 60 == 0:
                _LOGGER.exception("Pack tracking failed (%d in a row)", self._packs_fails)

    # -----------------------------------------------------------------
    # Staleness (ROADMAP item 4)
    # -----------------------------------------------------------------
    def _update_staleness(self, now: datetime, hours: float) -> None:
        """Frozen if no battery reading has changed for `stale_minutes`.

        Watches the gauge (or the SOC sensor) and the power sensors together: the house
        load moves every minute on live data, while a hold can keep the gauge still for
        hours. Needs at least one power sensor; 0 minutes turns the check off.

        An idle system is not frozen. When every power sensor reads (about) zero nothing is
        moving through the inverter, a full bank has nothing to report, and live readings sit
        exactly still for hours (seen on the owner's AC500, 2026-11-23: seven stretches of
        36-173 min overnight with the pack voltages still moving). A frozen feed cannot be told
        from that, and nothing the planner needs is hidden by it, so while the system is idle
        the unchanged-timer restarts. A feed stuck on a non-zero value is still caught.
        """
        c = self.coord
        limit = c.stale_minutes
        ids = [e for e in (c.gauge_entity or c.battery_soc_entity, c.load_power_entity,
                           c.grid_power_entity, c.pv_power_entity) if e]
        if limit <= 0 or not (c.load_power_entity or c.grid_power_entity):
            self._set_stale(False, now)
            return
        for entity_id in ids:
            val = self._float_state(entity_id)
            if val is None:
                continue
            if self._seen.get(entity_id) != val:
                self._seen[entity_id] = val
                self._last_change = now
        if self._last_change is None or self._is_idle():
            self._last_change = now
        frozen = (now - self._last_change).total_seconds() >= limit * 60
        self._set_stale(frozen, now)
        if frozen and 0 < hours <= 1:
            self._shadow["stale_minutes"] = round(self._shadow.get("stale_minutes", 0) + hours * 60, 1)
        if frozen and self._stale_since is not None:
            # the longest single stretch of the day, for the health grade
            episode = (now - self._stale_since).total_seconds() / 60.0
            if episode > self._shadow.get("stale_longest_min", 0):
                self._shadow["stale_longest_min"] = round(episode, 1)

    def _is_idle(self) -> bool:
        """True when every configured power sensor is readable and at (about) zero.

        One unreadable sensor means we cannot say the system is idle, so it is not.
        """
        c = self.coord
        ids = [e for e in (c.load_power_entity, c.grid_power_entity, c.pv_power_entity) if e]
        if not ids:
            return False
        for entity_id in ids:
            kw = self._power_kw(entity_id)
            if kw is None or abs(kw) > IDLE_POWER_KW:
                return False
        return True

    def _set_stale(self, frozen: bool, now: datetime) -> None:
        if frozen == self.data_stale:
            return
        c = self.coord
        self.data_stale = frozen
        self._dirty = True
        if frozen:
            self._stale_since = self._last_change or now
            _LOGGER.warning("Battery readings have not changed for %.0f minutes; treating them as missing",
                            c.stale_minutes)
            if not self._stale_alerted:
                self._stale_alerted = True
                c._notify(
                    "Solarseed - battery data frozen",
                    "No change in the battery gauge or the power readings for %.0f minutes while "
                    "power was flowing. "
                    "The planner treats the battery as unreadable: no learning, night falls back to "
                    "charging, mid-peak stays on battery, peak never charges. The inverter's own "
                    "SOC Low is the backstop." % c.stale_minutes)
            return
        since = self._stale_since
        mins = (now - since).total_seconds() / 60.0 if since else 0.0
        _LOGGER.info("Battery readings are changing again after %.0f minutes", mins)
        if self._stale_alerted:
            self._stale_alerted = False
            c._notify("Solarseed - battery data back",
                      "Battery readings are changing again after %.0f minutes." % mins)
        self._stale_since = None

    # -----------------------------------------------------------------
    # First tick after a start (ROADMAP item 5)
    # -----------------------------------------------------------------
    def _adopt_inverter_mode(self, now: datetime, gauge: float | None, grid: float | None,
                             load: float | None, pv: float) -> None:
        """No command survived the restart: take the inverter's current mode from the power
        readings, so the planner continues (and keeps its hysteresis) instead of starting over."""
        mode = infer_mode(gauge, grid, load, pv, self.coord.gauge_floor)
        if mode is None:
            return
        phase = self._decide(now, gauge).phase
        _LOGGER.info("After start the inverter looks to be in %s mode (%s); continuing from there", mode, phase)
        self._commanded, self._commanded_phase, self._commanded_at = mode, phase, now

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
        self.profile.observe_day(c.is_tou_day(self._day), full)
        self.learner.age(float(max((today - self._day).days, 1)))
        self._day = today
        self._day_kwh, self._day_cover, self._shadow, self._grid_kwh = {}, {}, {}, {}
        self.hass.async_create_task(self.async_save())

    def _update_bank_full(self, gauge: float | None, grid: float | None, load: float | None) -> None:
        if gauge is None:
            return
        if gauge >= 100:
            self.bank_full, self._full_at = True, 100.0
            self._idle_charge_min = 0
            return
        if self.bank_full:
            if gauge < min(98.0, (self._full_at or 100.0) - 2.0):
                self.bank_full, self._full_at = False, None
            return
        # 97-99 %: full if a charge was asked for and nothing has gone in for a while
        if (gauge >= 97 and self._commanded == MODE_CHARGE and None not in (grid, load)
                and grid - load < 0.15):
            self._idle_charge_min += 1
            if self._idle_charge_min >= FULL_CONFIRM_MIN:
                self.bank_full, self._full_at = True, gauge
        else:
            self._idle_charge_min = 0

    def _update_topup(self, now: datetime) -> None:
        c = self.coord
        today_tou = c.is_tou_day(now.date())
        tomorrow_tou = c.is_tou_day(now.date() + timedelta(days=1))
        # Owed once, from peak end on the last TOU day of the week. The evening before a
        # mid-week holiday is not that (Friday still comes); a Friday holiday makes it Thursday.
        last_of_week = is_last_tou_day_of_week(now.date(), c.weekdays_only, c.holiday_preset)
        if last_of_week and now.hour >= c.peak_end and self._topup_day != now.date().isoformat():
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
            is_tou_today=c.is_tou_day(now.date()),
            is_tou_tomorrow=c.is_tou_day(now.date() + timedelta(days=1)),
            midpeak_start=c.midpeak_start,
            peak_start=c.peak_start,
            peak_end=c.peak_end,
            floor=c.gauge_floor,
            full_months=tuple(c.full_charge_months),
            margin_kwh=c.peak_margin_kwh,
            recovery_pct=c.recovery_pct,
            load_quantile=c.load_quantile,
            solar_confidence=c.solar_confidence,
            solar_today=c._get_hourly_solar(quiet=True),
            solar_tomorrow=(c._get_hourly_solar(c.solar_forecast_tomorrow_entity_resolved, quiet=True)
                            or c._get_hourly_solar(quiet=True)),
            bank_full=self.bank_full,
            topup_pending=self.topup_pending,
            current_mode=self._commanded if c.planner == PLANNER_LEARNED else None,
            current_phase=self._commanded_phase if c.planner == PLANNER_LEARNED else None,
            data_stale=self.data_stale,
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
        # The handover: the gauge reaching the floor inside the rate window (it bounces up
        # to the recovery level straight after, so only the first touch is recorded).
        if (gauge is not None and "handover_at" not in s and gauge <= c.gauge_floor + 0.5
                and c.is_tou_day(now.date()) and c.midpeak_start <= now.hour < c.peak_end):
            s["handover_at"] = now.strftime("%H:%M")
            s["handover_period"] = c._classify_period(now)
            if d.handover_kwh is not None:
                s["handover_cost_kwh"] = round(d.handover_kwh, 2)
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
        out.setdefault("stale_minutes", 0)
        out.setdefault("stale_longest_min", 0)
        out.setdefault("command_retries", 0)
        out.setdefault("commands_not_followed", 0)
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
        first, self._first_act = self._first_act, False
        if first and d.mode != self._commanded and d.mode != MODE_CHARGE:
            # A restart is no reason to release a hold or stop a charge; the next tick decides
            # again with the restored or observed mode. Unknown mode: adopt, verification checks.
            _LOGGER.info("First decision since start is %s (%s); not acting on it yet", d.mode, d.reason)
            if self._commanded is None:
                self._commanded, self._commanded_phase, self._commanded_at = d.mode, d.phase, now
            return
        if d.mode != self._commanded:
            _LOGGER.info("Learned planner: %s -> %s (%s)", self._commanded, d.mode, d.reason)
            self._fire(d.mode, gauge)
            if self._commanded is not None or d.mode != MODE_DISCHARGE:
                self.coord._notify("Solarseed - %s" % d.mode.capitalize(), d.reason)
            self._commanded, self._commanded_phase, self._commanded_at = d.mode, d.phase, now
            self._retries, self._mismatch_min, self._alerted = 0, 0, False
            self._dirty = True
            self.hass.async_create_task(self.async_save())
            return
        if self._commanded_at is None or None in (grid, load):
            return
        waited = (now - self._commanded_at).total_seconds() / 60.0
        if waited < VERIFY_AFTER_MIN:
            return
        ok = mode_matches(d.mode, gauge, grid, load, pv, self.coord.gauge_floor, self.bank_full)
        if ok is not False:
            self._mismatch_min = 0
            return
        self._mismatch_min += 1
        if self._mismatch_min < VERIFY_MISMATCH_MIN:
            return
        self._mismatch_min = 0
        if self._retries < VERIFY_RETRIES:
            self._retries += 1
            _LOGGER.warning("Inverter does not look like it is in %s mode; sending the command again (%d/%d)",
                            d.mode, self._retries, VERIFY_RETRIES)
            self._shadow["command_retries"] = self._shadow.get("command_retries", 0) + 1
            self._fire(d.mode, gauge)
            self._commanded_at = now
        elif not self._alerted:
            self._alerted = True
            self._shadow["commands_not_followed"] = self._shadow.get("commands_not_followed", 0) + 1
            _LOGGER.error("Inverter did not follow the %s command after %d attempts", d.mode, VERIFY_RETRIES)
            self.coord._notify(
                "Solarseed - inverter not responding",
                "Asked for %s mode %d times; the power readings do not match. Check the inverter."
                % (d.mode, VERIFY_RETRIES + 1))

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

        learner = build_from_samples(samples)
        profile = profile_from_hourly(rows, c.is_tou_day,
                                      LoadProfile(default_kw=c.base_load_kw))
        learned_pts = sum(learner.discharge.p) + sum(learner.grid_charge.p)
        if not samples or learned_pts <= 0:
            return {"error": "No usable 5-minute statistics for the gauge and power sensors; "
                             "the existing model was kept.", "samples": len(samples)}
        self.learner = learner
        if profile.n_days(True) or profile.n_days(False):
            self.profile = profile
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
