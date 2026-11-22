"""Third-party packs: charge counted from the last full anchor, and capacity per run.

Pure Python: no Home Assistant imports.

Packs that the inverter does not manage keep their own percent counters, and on a bank
where charging stops before those packs reach their reset voltage (and discharging stops
long before their empty voltage) the counters drift apart and never resynchronise. Two
things are measured here instead, from each pack's current, the bus voltage and the
inverter's gauge:

  charge estimate   amp-hours out of each pack since the last full anchor (the inverter's
                    gauge reaching 100 %), as a percent of the pack's rated capacity.
  capacity trend    on each discharge that starts from a full anchor, the amp-hours each
                    pack delivers between two fixed bus voltages, and the battery's AC
                    energy over the same stretch. One point per run. A slow fall over
                    months is capacity loss; a sudden step is a pack or wiring problem.

Currents are signed positive into the pack (charging). The voltages are read under load,
so each point carries the run's mean power: compare runs of similar load.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

FULL_GAUGE = 100.0
CONFIRM_MIN = 3.0           # minutes a voltage must stay past a threshold to count as crossed
BRIDGE_MIN = 5.0            # a missing current is bridged with its last reading this long
RUN_GAP_ABORT_MIN = 10.0    # a run with a longer gap in any pack's current is discarded
CHARGE_AMPS = 0.5           # a pack current above this (into the pack) counts as charging
RUN_CHARGE_ABORT_AH = 2.0   # a run during which the packs took in more than this is discarded
RECHARGE_PTS = 2.0          # a gauge rise this big after the anchor ends a clean discharge
MAX_RUN_HOURS = 72.0
MAX_POINTS = 400

STATE_IDLE = "idle"             # waiting for a full anchor
STATE_ARMED = "armed"           # full; waiting for the bus to fall through the upper voltage
STATE_MEASURING = "measuring"   # between the two voltages


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


class PackTracker:
    """State for one bank of third-party packs, keyed by each pack's current sensor."""

    def __init__(self, packs: list[str], v_high: float = 53.0, v_low: float = 51.5,
                 capacity_ah: float = 100.0) -> None:
        self.packs = list(packs)
        self.v_high = float(v_high)
        self.v_low = float(v_low)
        self.capacity_ah = float(capacity_ah)
        # charge estimate
        self.anchor_at: str | None = None
        self.out_ah: dict[str, float] = {}
        self.gap_min: dict[str, float] = {}
        self._last_cur: dict[str, tuple[float, float]] = {}    # pack -> (amps, minutes old)
        self._prev_gauge: float | None = None
        self._last_at: datetime | None = None
        # capacity runs
        self.run_state = STATE_IDLE
        self._seen_high = False
        self._min_gauge: float | None = None
        self._run: dict[str, Any] | None = None
        self._confirm = 0.0
        self._end: dict[str, Any] | None = None
        self._end_confirm = 0.0
        self.points: list[dict[str, Any]] = []
        self.last_abort: str | None = None

    # -----------------------------------------------------------------
    # The minute tick
    # -----------------------------------------------------------------
    def tick(self, now: datetime, gauge: float | None, bus_v: float | None,
             currents: dict[str, float | None], battery_ac_kw: float | None) -> bool:
        """Feed one set of readings. Returns True when a capacity run was just recorded."""
        minutes = (now - self._last_at).total_seconds() / 60.0 if self._last_at else 0.0
        self._last_at = now
        if minutes < 0:
            minutes = 0.0
        hours = minutes / 60.0

        prev, self._prev_gauge = self._prev_gauge, (gauge if gauge is not None else self._prev_gauge)
        if gauge is not None and gauge >= FULL_GAUGE and (
                self.anchor_at is None or (prev is not None and prev < FULL_GAUGE)):
            self._anchor(now, gauge, bus_v)
            return False

        if minutes > BRIDGE_MIN:
            # A gap (a restart, a stalled timer): nothing is known about what flowed.
            for p in self.out_ah:
                self.gap_min[p] = self.gap_min.get(p, 0.0) + minutes
            self._last_cur.clear()
            if self.run_state != STATE_IDLE:
                self._abort(now, "no readings for %.0f minutes" % minutes)
            return False
        if minutes <= 0:
            return False

        amps = self._resolve(currents, minutes)
        if self.anchor_at is not None:
            for p in self.packs:
                if p not in self.out_ah:
                    continue                  # added after the anchor: unknown until the next one
                a = amps.get(p)
                if a is None:
                    self.gap_min[p] = self.gap_min.get(p, 0.0) + minutes
                else:
                    self.out_ah[p] = max(self.out_ah[p] - a * hours, 0.0)
        return self._run_tick(now, hours, gauge, bus_v, amps, battery_ac_kw)

    def _resolve(self, currents: dict[str, float | None], minutes: float) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        for p in self.packs:
            a = currents.get(p)
            if a is not None:
                self._last_cur[p] = (a, 0.0)
                out[p] = a
                continue
            last = self._last_cur.get(p)
            if last is not None and last[1] + minutes <= BRIDGE_MIN:
                self._last_cur[p] = (last[0], last[1] + minutes)
                out[p] = last[0]
            else:
                out[p] = None
        return out

    def _anchor(self, now: datetime, gauge: float, bus_v: float | None) -> None:
        self.anchor_at = _iso(now)
        self.out_ah = {p: 0.0 for p in self.packs}
        self.gap_min = {p: 0.0 for p in self.packs}
        self.run_state = STATE_ARMED
        self._seen_high = bus_v is not None and bus_v >= self.v_high
        self._min_gauge = gauge
        self._run, self._confirm, self._end, self._end_confirm = None, 0.0, None, 0.0

    # -----------------------------------------------------------------
    # Capacity runs
    # -----------------------------------------------------------------
    def _new_run(self, now: datetime) -> dict[str, Any]:
        return {"at": _iso(now), "ah": {p: 0.0 for p in self.packs}, "gap_min": {p: 0.0 for p in self.packs},
                "ac_kwh": 0.0, "hours": 0.0, "charged_ah": 0.0}

    def _accumulate(self, run: dict[str, Any], hours: float, amps: dict[str, float | None],
                    ac_kw: float | None) -> None:
        run["hours"] += hours
        if ac_kw is not None:
            run["ac_kwh"] += max(ac_kw, 0.0) * hours
        for p in self.packs:
            a = amps.get(p)
            if a is None:
                run["gap_min"][p] = run["gap_min"].get(p, 0.0) + hours * 60.0
                continue
            run["ah"][p] = run["ah"].get(p, 0.0) - a * hours
            if a > CHARGE_AMPS:
                run["charged_ah"] += a * hours

    def _run_tick(self, now: datetime, hours: float, gauge: float | None, bus_v: float | None,
                  amps: dict[str, float | None], ac_kw: float | None) -> bool:
        if self.run_state == STATE_IDLE:
            return False
        if gauge is not None:
            self._min_gauge = gauge if self._min_gauge is None else min(self._min_gauge, gauge)
            if gauge > self._min_gauge + RECHARGE_PTS:
                self._abort(now, "recharged before the bus reached %.1f V" % self.v_low)
                return False

        if self.run_state == STATE_ARMED:
            if bus_v is None:
                return False
            if bus_v >= self.v_high:
                self._seen_high, self._run, self._confirm = True, None, 0.0
                return False
            if not self._seen_high:
                return False                  # started below the upper voltage: not a whole run
            if self._run is None:
                self._run = self._new_run(now)    # counted from the first minute below
                return False
            self._accumulate(self._run, hours, amps, ac_kw)
            self._confirm += hours * 60.0
            if self._confirm >= CONFIRM_MIN:
                self.run_state = STATE_MEASURING
            return False

        run = self._run
        if run is None:                       # cannot happen; recover quietly
            self._abort(now, "lost run state")
            return False
        self._accumulate(run, hours, amps, ac_kw)
        if max(run["gap_min"].values(), default=0.0) > RUN_GAP_ABORT_MIN:
            self._abort(now, "pack current missing for more than %.0f minutes" % RUN_GAP_ABORT_MIN)
            return False
        if run["charged_ah"] > RUN_CHARGE_ABORT_AH:
            self._abort(now, "the packs were charged during the run")
            return False
        if run["hours"] > MAX_RUN_HOURS:
            self._abort(now, "run longer than %.0f hours" % MAX_RUN_HOURS)
            return False
        if bus_v is None:
            return False
        if bus_v < self.v_low:
            if self._end is None:
                self._end = copy.deepcopy(run)
                self._end["end"] = _iso(now)
            self._end_confirm += hours * 60.0
            if self._end_confirm >= CONFIRM_MIN:
                self._finish()
                return True
        else:
            self._end, self._end_confirm = None, 0.0
        return False

    def _finish(self) -> None:
        end = self._end or {}
        hrs = float(end.get("hours", 0.0))
        point = {
            "start": end.get("at"),
            "end": end.get("end"),
            "anchor": self.anchor_at,
            "v_high": self.v_high,
            "v_low": self.v_low,
            "hours": round(hrs, 2),
            "ah": {p: round(v, 2) for p, v in end.get("ah", {}).items()},
            "ac_kwh": round(float(end.get("ac_kwh", 0.0)), 3),
            "mean_kw": round(float(end.get("ac_kwh", 0.0)) / hrs, 3) if hrs > 0 else None,
            "gap_min": {p: round(v, 1) for p, v in end.get("gap_min", {}).items() if v > 0},
        }
        self.points = (self.points + [point])[-MAX_POINTS:]
        self._idle()

    def _abort(self, now: datetime, why: str) -> None:
        self.last_abort = "%s: %s" % (_iso(now), why)
        self._idle()

    def _idle(self) -> None:
        self.run_state = STATE_IDLE
        self._run, self._confirm, self._end, self._end_confirm = None, 0.0, None, 0.0
        self._seen_high = False

    # -----------------------------------------------------------------
    # Read-outs
    # -----------------------------------------------------------------
    def estimate_pct(self, pack: str) -> float | None:
        """Charge estimate in percent of rated capacity, or None before the first anchor."""
        if self.anchor_at is None or pack not in self.out_ah or self.capacity_ah <= 0:
            return None
        return min(max(100.0 * (1.0 - self.out_ah[pack] / self.capacity_ah), 0.0), 100.0)

    def history(self, pack: str, n: int = 30) -> list[dict[str, Any]]:
        """The last `n` runs for this pack at the current voltage pair."""
        out = [{"date": (pt.get("start") or "")[:10], "ah": pt["ah"][pack], "mean_kw": pt.get("mean_kw")}
               for pt in self.points
               if pack in pt.get("ah", {}) and pt.get("v_high") == self.v_high and pt.get("v_low") == self.v_low]
        return out[-n:]

    def latest_ah(self, pack: str) -> float | None:
        h = self.history(pack, 1)
        return h[-1]["ah"] if h else None

    def run_status(self) -> dict[str, Any]:
        run = self._run or {}
        return {
            "state": self.run_state,
            "started": run.get("at") if self.run_state == STATE_MEASURING else None,
            "ah_so_far": ({p: round(v, 1) for p, v in run.get("ah", {}).items()}
                          if self.run_state == STATE_MEASURING else None),
            "last_abort": self.last_abort,
            "runs_recorded": len(self.points),
        }

    # -----------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "v_high": self.v_high,
            "v_low": self.v_low,
            "anchor_at": self.anchor_at,
            "out_ah": {p: round(v, 4) for p, v in self.out_ah.items()},
            "gap_min": {p: round(v, 1) for p, v in self.gap_min.items()},
            "prev_gauge": self._prev_gauge,
            "last_at": _iso(self._last_at) if self._last_at else None,
            "run_state": self.run_state,
            "seen_high": self._seen_high,
            "min_gauge": self._min_gauge,
            "run": self._run,
            "confirm": self._confirm,
            "end": self._end,
            "end_confirm": self._end_confirm,
            "points": self.points,
            "last_abort": self.last_abort,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None, packs: list[str], v_high: float = 53.0,
                  v_low: float = 51.5, capacity_ah: float = 100.0) -> "PackTracker":
        """Rebuild from storage. Anything malformed starts that part empty."""
        t = cls(packs, v_high, v_low, capacity_ah)
        d = d if isinstance(d, dict) else {}
        try:
            pts = d.get("points") or []
            t.points = [p for p in pts if isinstance(p, dict) and isinstance(p.get("ah"), dict)][-MAX_POINTS:]
            t.last_abort = d.get("last_abort")
            t.anchor_at = d.get("anchor_at") or None
            t.out_ah = {p: float(v) for p, v in (d.get("out_ah") or {}).items() if p in t.packs}
            t.gap_min = {p: float(v) for p, v in (d.get("gap_min") or {}).items() if p in t.packs}
            pg = d.get("prev_gauge")
            t._prev_gauge = float(pg) if pg is not None else None
            if d.get("last_at"):
                t._last_at = datetime.fromisoformat(d["last_at"])
            same_volts = d.get("v_high") == t.v_high and d.get("v_low") == t.v_low
            if same_volts and d.get("run_state") in (STATE_ARMED, STATE_MEASURING):
                t.run_state = d["run_state"]
                t._seen_high = bool(d.get("seen_high"))
                mg = d.get("min_gauge")
                t._min_gauge = float(mg) if mg is not None else None
                t._run = d.get("run") if isinstance(d.get("run"), dict) else None
                t._confirm = float(d.get("confirm") or 0.0)
                t._end = d.get("end") if isinstance(d.get("end"), dict) else None
                t._end_confirm = float(d.get("end_confirm") or 0.0)
                if t.run_state == STATE_MEASURING and t._run is None:
                    t._idle()
                if t._run is not None and set(t._run.get("ah", {})) != set(t.packs):
                    t._idle()                 # the set of packs changed mid-run
        except (TypeError, ValueError, KeyError, AttributeError):
            return cls(packs, v_high, v_low, capacity_ah)
        return t
