"""0.9.2: the dashboard and the two sensors it needed.

- The peak-end forecast and the plan sentence (`outlook.py`) through the real runtime.
- The Plan Summary and Peak End Forecast sensors: unknown, never a guess, when the planner
  cannot tell; never an exception into the state write.
- `dashboards/solarseed.yaml`: stock cards only, the entity ids in one place at the top,
  every id one the integration creates, and every markdown template rendered against the
  real sensors' attributes (jinja2 needed for that part; skipped without it).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from custom_components.solarseed_peak_shaver.const import (
    CONF_TARIFF_SEASONS,
    SENSOR_HEALTH,
    SENSOR_LEARNED_ENERGY,
    SENSOR_LEARNED_PLAN,
    SENSOR_PEAK_END_FORECAST,
    SENSOR_PLAN_SUMMARY,
)
from custom_components.solarseed_peak_shaver.health import grade_day
from custom_components.solarseed_peak_shaver.outlook import MAX_STATE_LEN, plan_sentence
from custom_components.solarseed_peak_shaver.planner import MODE_CHARGE, MODE_HOLD
from custom_components.solarseed_peak_shaver.tariff import Windows
from tests.test_learned_runtime import make_runtime, run
from tests.test_planner import trained

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboards" / "solarseed.yaml"

TUESDAY = datetime(2027, 2, 16)          # a February weekday: the charge is sized, not full
FRIDAY = datetime(2027, 2, 19)
SATURDAY = datetime(2027, 2, 20)
SUNDAY = datetime(2027, 2, 21)


def at(day: datetime, hour: int, minute: int = 0) -> datetime:
    return day.replace(hour=hour, minute=minute)


def planner_at(when: datetime, gauge, planner="learned", train=True, **overrides):
    rt, coord, world = make_runtime(planner=planner, **overrides)
    if train:
        rt.learner, rt.profile = trained()
    world.values["sensor.gauge"] = (gauge, "%")
    run(rt, when, 2)
    return rt, coord, world


def sensor(coord, key):
    from custom_components.solarseed_peak_shaver.sensor import SENSOR_DESCRIPTIONS, PeakShaverSensor

    return PeakShaverSensor(coord, coord.entry, key, SENSOR_DESCRIPTIONS[key])


# --- the forecast ------------------------------------------------------------------------------


class TestPeakOutlook:
    def test_mid_peak_predicts_from_the_gauge_now(self):
        rt, _, _ = planner_at(at(TUESDAY, 10), 70)
        o = rt.outlook()
        assert o.day == "today" and o.for_date == TUESDAY.date()
        assert o.start_hour == pytest.approx(10 + 1 / 60) and o.start_gauge == 70
        assert o.covered and o.spare_kwh > 0 and not o.assumes_charge
        assert (o.windows.peak_start, o.windows.peak_end) == (17, 21)

    def test_it_is_the_prediction_the_health_record_grades(self):
        # At mid-peak start the forecast and the scorecard's pred_gauge_peak_end are one number.
        rt, _, _ = planner_at(at(TUESDAY, 6, 59), 70)
        run(rt, at(TUESDAY, 7, 0), 1)
        assert rt.daily_summary()["pred_gauge_peak_end"] == round(rt.outlook().gauge_end, 1)

    def test_before_mid_peak_it_starts_from_the_night_target(self):
        rt, _, _ = planner_at(at(TUESDAY, 5, 30), 30)
        d = rt.decision
        assert d.mode == MODE_CHARGE and d.phase == "night"
        o = rt.outlook()
        assert o.day == "today" and o.start_hour == 7 and o.start_gauge == pytest.approx(d.target_gauge)
        assert o.assumes_charge

    def test_after_peak_end_it_is_tomorrows_window(self):
        rt, _, _ = planner_at(at(TUESDAY, 22), 15)
        assert rt.decision.phase == "night"
        o = rt.outlook()
        assert o.day == "tomorrow" and o.for_date == (TUESDAY + timedelta(days=1)).date()
        assert o.start_gauge == pytest.approx(rt.decision.target_gauge) and o.assumes_charge

    def test_a_low_battery_in_mid_peak_is_not_covered(self):
        rt, _, _ = planner_at(at(TUESDAY, 14), 25)
        o = rt.outlook()
        assert not o.covered and o.spare_kwh == 0.0
        assert rt.decision.shortfall_kwh > 0

    def test_hold_at_full_starts_from_the_gauge_reached(self):
        rt, _, world = planner_at(at(datetime(2026, 11, 17), 23), 98)
        rt.bank_full = True
        run(rt, at(datetime(2026, 11, 17), 23, 2), 1)
        assert rt.decision.mode == MODE_HOLD
        o = rt.outlook()
        assert o.start_gauge == pytest.approx(98) and not o.assumes_charge

    @pytest.mark.parametrize("when", [at(SATURDAY, 12), at(SUNDAY, 15), at(FRIDAY, 22),
                                      at(datetime(2026, 11, 26), 12)])        # Thanksgiving
    def test_no_peak_planned_is_no_forecast(self, when):
        rt, _, _ = planner_at(when, 50)
        assert rt.outlook() is None

    def test_cannot_tell_without_a_gauge_or_a_trained_model(self):
        rt, _, _ = planner_at(at(TUESDAY, 10), "unavailable")
        assert rt.outlook() is None
        rt, _, _ = planner_at(at(TUESDAY, 10), 70, train=False)
        assert rt.outlook() is None

    def test_a_season_gives_tomorrow_its_own_window(self):
        rt, _, _ = planner_at(at(datetime(2026, 9, 30), 21, 30), 20,
                              **{CONF_TARIFF_SEASONS: "06-09: mid-peak 9-15, peak 15-20"})
        o = rt.outlook()
        assert o.day == "tomorrow" and (o.windows.midpeak_start, o.windows.peak_end) == (7, 21)


# --- the sentence ------------------------------------------------------------------------------


class TestPlanSentence:
    def say(self, when, gauge, **kw):
        rt, coord, _ = planner_at(when, gauge, **kw)
        text = rt.plan_sentence()
        text.encode("ascii")
        assert 0 < len(text) <= MAX_STATE_LEN
        return text, rt

    def test_a_weekday_in_mid_peak(self):
        text, rt = self.say(at(TUESDAY, 10), 70)
        assert text.startswith("Today: on battery through peak 17:00-21:00; expected to end peak at ")
        assert "%d %%" % round(rt.outlook().gauge_end) in text and "kWh to spare" in text

    def test_a_short_peak_names_the_top_up_and_its_price(self):
        text, rt = self.say(at(TUESDAY, 14), 25)
        short = rt.decision.shortfall_kwh
        assert "looks short by %.1f kWh (about $%.2f at peak price)" % (short, short * 0.4313) in text
        assert "a top-up starts before 17:00" in text
        assert text.endswith("expected to reach the floor before 21:00.")

    def test_the_night_before(self):
        text, rt = self.say(at(TUESDAY, 22), 15)
        assert text.startswith("Peak is over for today. Tomorrow (Wednesday): holding; the charge to ")
        assert "%d %%" % round(rt.decision.target_gauge) in text

    def test_before_mid_peak_on_the_day(self):
        text, rt = self.say(at(TUESDAY, 5, 30), 30)
        assert text.startswith("Today: charging to %d %% by 07:00, then on battery through peak 17:00-21:00"
                               % round(rt.decision.target_gauge))

    def test_in_peak(self):
        text, _ = self.say(at(TUESDAY, 18), 40)
        assert text.startswith("Peak until 21:00: on battery, never charging; expected to end it at ")

    def test_a_full_charge_month(self):
        text, _ = self.say(at(datetime(2026, 11, 17), 23), 40)
        assert "Tomorrow (Wednesday): charging until the inverter stops, then holding until 07:00" in text

    def test_weekend_friday_and_sunday(self):
        assert self.say(at(SATURDAY, 12), 50)[0] == "No peak prices today (Saturday): solar first, then battery."
        assert self.say(at(FRIDAY, 22), 15)[0] == "Peak is over for today. No peak prices tomorrow (Saturday)."
        text, _ = self.say(at(SUNDAY, 15), 50)
        assert text.endswith("Tomorrow's charge is planned from 21:00.")
        assert self.say(at(SUNDAY, 22), 50)[0].startswith("Tomorrow (Monday): ")

    def test_thanksgiving_by_name(self):
        text, _ = self.say(at(datetime(2026, 11, 25), 22), 40)
        assert text == "Peak is over for today. No peak prices tomorrow (Thanksgiving)."
        text, _ = self.say(at(datetime(2026, 11, 26), 12), 40)
        assert text.startswith("No peak prices today (Thanksgiving)")

    def test_cannot_tell_is_said_plainly(self):
        text, _ = self.say(at(TUESDAY, 22), 15, train=False)
        assert text.endswith("no forecast until the model has learned enough.")
        text, _ = self.say(at(TUESDAY, 22), "unavailable")
        assert text.endswith("no forecast without a battery reading.")
        text, rt = self.say(at(TUESDAY, 10), "unavailable")
        assert text == rt.decision.reason

    def test_classic_in_control_is_marked_as_a_shadow(self):
        text, _ = self.say(at(TUESDAY, 10), 70, planner="classic")
        assert text.startswith("Shadow plan (classic planner in control): Today: ")

    def test_a_weekly_top_up_is_named(self):
        rt, coord, _ = planner_at(at(datetime(2026, 11, 21), 10), 60)     # a November Saturday
        rt.topup_pending, rt._topup_day = True, "2026-11-20"           # owed from Friday's peak end
        run(rt, at(datetime(2026, 11, 21), 10, 2), 1)
        assert rt.decision.phase == "top-up"
        assert rt.plan_sentence().endswith("Weekly top-up: charging until the inverter stops.")

    def test_never_over_the_state_limit(self):
        rt, _, _ = planner_at(at(SATURDAY, 12), 50)
        w = Windows(7, 17, 21)
        text = plan_sentence(rt.last_inputs, rt.decision, None, w, w, holiday_today="x" * 400)
        assert len(text) == MAX_STATE_LEN and text.endswith("...")

    def test_none_before_the_first_decision(self):
        rt, _, _ = make_runtime(planner="learned")
        assert rt.plan_sentence() is None and rt.outlook() is None


# --- the sensors -------------------------------------------------------------------------------


class TestDashboardSensors:
    def test_registered_with_names_units_and_state_classes(self):
        from custom_components.solarseed_peak_shaver.sensor import SENSOR_DESCRIPTIONS

        assert SENSOR_DESCRIPTIONS[SENSOR_PLAN_SUMMARY]["name"] == "Plan Summary"
        assert SENSOR_DESCRIPTIONS[SENSOR_PLAN_SUMMARY]["unit"] is None
        assert SENSOR_DESCRIPTIONS[SENSOR_PLAN_SUMMARY]["state_class"] is None      # text, no statistics
        assert SENSOR_DESCRIPTIONS[SENSOR_PEAK_END_FORECAST]["name"] == "Peak End Forecast"
        assert SENSOR_DESCRIPTIONS[SENSOR_PEAK_END_FORECAST]["unit"] == "%"
        assert SENSOR_DESCRIPTIONS[SENSOR_PEAK_END_FORECAST]["state_class"] == "measurement"

    def test_values_and_attributes(self):
        rt, coord, _ = planner_at(at(TUESDAY, 10), 70)
        summary, forecast = sensor(coord, SENSOR_PLAN_SUMMARY), sensor(coord, SENSOR_PEAK_END_FORECAST)
        assert summary.native_value == rt.plan_sentence()
        assert forecast.native_value == round(rt.outlook().gauge_end)
        attrs = forecast.extra_state_attributes
        assert attrs["for"] == "today" and attrs["peak_window"] == "17:00-21:00"
        assert attrs["covered"] is True and attrs["why_none"] is None and attrs["floor"] == coord.gauge_floor
        assert summary.extra_state_attributes is None

    @pytest.mark.parametrize("gauge,train,when,why", [
        ("unavailable", True, at(TUESDAY, 10), "no battery reading"),
        ("unknown", True, at(TUESDAY, 10), "no battery reading"),
        ("", True, at(TUESDAY, 10), "no battery reading"),
        ("nan", True, at(TUESDAY, 10), "no battery reading"),
        (70, False, at(TUESDAY, 10), "the model is still learning"),
        (70, True, at(SATURDAY, 12), "no peak window planned yet"),
    ])
    def test_unknown_when_it_cannot_tell(self, gauge, train, when, why):
        rt, coord, _ = planner_at(when, gauge, train=train)
        forecast = sensor(coord, SENSOR_PEAK_END_FORECAST)
        assert forecast.native_value is None
        assert forecast.extra_state_attributes["why_none"] == why

    def test_before_the_planner_has_run(self):
        rt, coord, _ = make_runtime(planner="learned")
        assert sensor(coord, SENSOR_PLAN_SUMMARY).native_value is None
        forecast = sensor(coord, SENSOR_PEAK_END_FORECAST)
        assert forecast.native_value is None
        assert forecast.extra_state_attributes["why_none"] == "the planner has not run yet"

    def test_a_failure_never_reaches_the_state_write(self):
        rt, coord, _ = planner_at(at(TUESDAY, 10), 70)
        rt.outlook = MagicMock(side_effect=RuntimeError("boom"))
        rt.plan_sentence = MagicMock(side_effect=RuntimeError("boom"))
        assert sensor(coord, SENSOR_PEAK_END_FORECAST).native_value is None
        assert sensor(coord, SENSOR_PLAN_SUMMARY).native_value is None
        assert sensor(coord, SENSOR_PEAK_END_FORECAST).extra_state_attributes["floor"] == coord.gauge_floor

    def test_without_a_learned_runtime(self):
        rt, coord, _ = planner_at(at(TUESDAY, 10), 70)
        coord.learned = None
        assert sensor(coord, SENSOR_PLAN_SUMMARY).native_value is None
        assert sensor(coord, SENSOR_PEAK_END_FORECAST).native_value is None

    def test_the_planner_decides_exactly_as_before(self):
        # The dashboard reads the decision; it must not change it.
        from custom_components.solarseed_peak_shaver.planner import decide

        rt, coord, _ = planner_at(at(TUESDAY, 14), 25)
        again = decide(rt.last_inputs, rt.learner, rt.profile)
        assert again == rt.decision


# --- the dashboard file ------------------------------------------------------------------------

STOCK_CARDS = {"heading", "markdown", "tile", "gauge", "history-graph", "statistics-graph",
               "conditional", "vertical-stack", "horizontal-stack", "entities", "grid"}


def load_dashboard():
    return yaml.safe_load(DASHBOARD.read_text(encoding="utf-8"))


def cards(node):
    """Every card in the dashboard, nested ones included."""
    if isinstance(node, dict):
        if "type" in node and ("entity" in node or "content" in node or "cards" in node
                               or "card" in node or "entities" in node or "heading" in node):
            yield node
        for key in ("views", "sections", "cards"):
            for child in node.get(key) or []:
                yield from cards(child)
        if isinstance(node.get("card"), dict):
            yield from cards(node["card"])
    elif isinstance(node, list):
        for child in node:
            yield from cards(child)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def integration_entity_ids(coord) -> set[str]:
    """The entity ids Home Assistant gives this integration's entities on a fresh install."""
    from custom_components.solarseed_peak_shaver.const import NAME
    from custom_components.solarseed_peak_shaver.select import SELECTS
    from custom_components.solarseed_peak_shaver.sensor import SENSOR_DESCRIPTIONS

    device = slug(NAME)
    ids = {"sensor.%s_%s" % (device, slug(d["name"])) for d in SENSOR_DESCRIPTIONS.values()}
    ids |= {"select.%s_%s" % (device, slug(spec[1])) for spec in SELECTS}
    # one pack named "Pack 1" (its current sensor sensor.pack_1_current), default voltages
    ids.add("sensor.%s_%s" % (device, slug("Pack 1 Ah Between %.1f And %.1f V"
                                            % (coord.capacity_v_high, coord.capacity_v_low))))
    return ids


class TestDashboardFile:
    def test_ascii_and_loads(self):
        DASHBOARD.read_bytes().decode("ascii")
        assert load_dashboard()["views"][0]["type"] == "sections"

    def test_stock_cards_only(self):
        found = {c["type"] for c in cards(load_dashboard())}
        assert found <= STOCK_CARDS, found - STOCK_CARDS
        assert not any(t.startswith("custom:") for t in found)
        assert {"markdown", "tile", "gauge", "history-graph", "statistics-graph"} <= found

    def test_the_ids_are_in_one_place_at_the_top(self):
        text = DASHBOARD.read_text(encoding="utf-8")
        first_key = next(line for line in text.splitlines() if line and not line.startswith("#"))
        assert first_key.startswith("solarseed_ids: &ids")
        ids = load_dashboard()["solarseed_ids"]
        flat = [v for v in ids.values() if isinstance(v, str)] + list(ids["packs"])
        for entity_id in flat:
            assert text.count(entity_id) == 1, entity_id                # written once, used by alias
        # every entity a card names comes from the list
        for card in cards(load_dashboard()):
            for e in [card.get("entity")] + [x.get("entity") if isinstance(x, dict) else x
                                             for x in card.get("entities") or []]:
                assert e is None or e in flat, e

    def test_every_integration_id_exists(self):
        _, coord, _ = make_runtime()
        ids = load_dashboard()["solarseed_ids"]
        made = integration_entity_ids(coord)
        ours = [v for k, v in ids.items() if k not in ("gauge", "packs")] + list(ids["packs"])
        for entity_id in ours:
            assert entity_id in made, entity_id

    def test_markdown_cards_carry_the_ids_and_use_only_known_keys(self):
        board = load_dashboard()
        ids = board["solarseed_ids"]
        markdowns = [c for c in cards(board) if c["type"] == "markdown"]
        assert len(markdowns) == 4
        for card in markdowns:
            assert card["ids"] == ids
            for key in re.findall(r"config\.ids\.(\w+)", card["content"]):
                assert key in ids, key
            assert "sensor." not in card["content"] and "select." not in card["content"]

    def test_attributes_the_templates_read_exist(self):
        board = load_dashboard()
        text = "\n".join(c["content"] for c in cards(board) if c["type"] == "markdown")
        wanted = set(re.findall(r"state_attr\(ids\.(\w+), '(\w+)'\)", text))
        attrs = {key: set(a) for key, a in real_attributes().items()}
        for key, attr in sorted(wanted):
            assert attr in attrs[key], (key, attr)
        # and the health records' fields the tables read
        record = grade_day({"grid_kwh": {"peak": 0.0}, "gauge_peak_end": 12.0, "pred_gauge_peak_end": 9.0}, "2027-02-16")
        for field in set(re.findall(r"r\.get\('(\w+)'\)", text)) | {"gauge_peak_end"}:
            assert field in record, field

    def test_question_order(self):
        sections = load_dashboard()["views"][0]["sections"]
        headings = []
        for s in sections:
            for c in cards(s):
                if c["type"] == "heading":
                    headings.append(c["heading"])
        assert headings == ["Now", "The next peak", "The last seven days",
                            "Predicted against what happened", "Pack capacity"]


def real_attributes() -> dict[str, dict]:
    """Attributes of the sensors the dashboard reads, from the real sensor classes."""
    rt, coord, _ = planner_at(at(TUESDAY, 14), 25)
    coord._now = lambda: at(TUESDAY, 14, 2)
    coord.store._data["days"] = invented_days(coord)
    return {
        "plan": sensor(coord, SENSOR_LEARNED_PLAN).extra_state_attributes,
        "forecast": sensor(coord, SENSOR_PEAK_END_FORECAST).extra_state_attributes,
        "health": sensor(coord, SENSOR_HEALTH).extra_state_attributes,
        "energy": sensor(coord, SENSOR_LEARNED_ENERGY).extra_state_attributes,
        "summary": {},
    }


def invented_days(coord, n=7, reasons=True):
    """Scorecards for n invented weekdays, graded by the real health code."""
    out = []
    day = TUESDAY - timedelta(days=1)
    while len(out) < n:
        if coord.is_tou_day(day.date()):
            i = len(out)
            peak = 0.4 if (reasons and i == 2) else 0.0
            summary = {"grid_kwh": {"mid-peak": 0.1 * (i % 3), "peak": peak},
                       "gauge_peak_end": 8.0 + i, "pred_gauge_peak_end": 10.0 + (i % 4)}
            if reasons and i == 4:
                summary["handover_at"] = "20:40"
            d = day.date().isoformat()
            out.insert(0, {"date": d, "health": grade_day(summary, d, coord.tariff.prices_on(day.date()))})
        day -= timedelta(days=1)
    return out


# --- the templates, rendered -------------------------------------------------------------------


def ha_env():
    """A Jinja environment close enough to Home Assistant's for these templates: sandboxed,
    strict about undefined names, with the HA functions and filters they use."""
    jinja2 = pytest.importorskip("jinja2")
    from jinja2.sandbox import ImmutableSandboxedEnvironment

    def is_number(value):
        try:
            f = float(value)
        except (TypeError, ValueError):
            return False
        return f == f and f not in (float("inf"), float("-inf"))

    env = ImmutableSandboxedEnvironment(undefined=jinja2.StrictUndefined)
    env.filters["is_number"] = is_number
    env.globals["strptime"] = lambda s, fmt: datetime.strptime(s, fmt)
    return env


def render_all(world: dict[str, tuple[str, dict | None]]) -> list[str]:
    """Render every markdown card with these states (entity id -> (state, attributes))."""
    env = ha_env()

    def states(entity_id):
        return world.get(entity_id, ("unknown", None))[0]

    def state_attr(entity_id, name):
        attrs = world.get(entity_id, ("unknown", None))[1] or {}
        return attrs.get(name)

    env.globals.update(states=states, state_attr=state_attr)
    board = load_dashboard()
    out = []
    for card in cards(board):
        if card["type"] == "markdown":
            out.append(env.from_string(card["content"]).render(config=card, user="test"))
    return out


def ha_world(coord) -> dict[str, tuple[str, dict | None]]:
    """The states Home Assistant would hold for the dashboard's sensors."""
    ids = load_dashboard()["solarseed_ids"]
    keys = {"plan": SENSOR_LEARNED_PLAN, "summary": SENSOR_PLAN_SUMMARY, "forecast": SENSOR_PEAK_END_FORECAST,
            "energy": SENSOR_LEARNED_ENERGY, "health": SENSOR_HEALTH}
    world = {}
    for name, key in keys.items():
        s = sensor(coord, key)
        value = s.native_value
        world[ids[name]] = ("unknown" if value is None else str(value), s.extra_state_attributes)
    return world


def check_text(text: str) -> None:
    text.encode("ascii")
    assert "None" not in text and "Undefined" not in text, text


class TestTemplatesRender:
    def test_a_fresh_install_with_nothing_yet(self):
        out = render_all({})
        for text in out:
            check_text(text)
        assert out[0].startswith("The learned planner has not decided anything yet.")
        assert out[1].startswith("**No peak forecast:** not available.")
        assert out[2] == "No day graded yet. Each TOU day is graded ten minutes after peak end from the grid meter."
        assert out[3].startswith("No peak end recorded yet.")

    def test_a_short_afternoon_with_a_week_of_grades(self):
        rt, coord, _ = planner_at(at(TUESDAY, 14), 25)
        coord._now = lambda: at(TUESDAY, 14, 2)
        coord.store._data["days"] = invented_days(coord)
        now, nxt, week, pred = render_all(ha_world(coord))
        for text in (now, nxt, week, pred):
            check_text(text)
        assert now.startswith("**Today: on battery; peak 17:00-21:00 looks short by ")
        assert "Right now: Peak window looks short by" in now
        assert "Price now: mid-peak at $0.1670/kWh, PGE Time of Day. In control: the learned planner." in now
        assert nxt.startswith("**Today, peak 17:00-21:00: not covered.** The battery is expected to reach the 3 % floor")
        assert "Running short would cost about $" in nxt
        rows = [line for line in week.splitlines() if line.startswith("| ") and "Day" not in line]
        assert len(rows) == 7 and rows[0].startswith("| Mon 02-15 |")
        assert "**7 graded days:** 5 good, 1 fair, 1 poor;" in week
        assert "Review needed:" in week
        assert "Why not Good:" in week and "handover at 20:40" in week
        assert "peak bought 0.4 kWh" in week
        rows = [line for line in pred.splitlines() if line.startswith("| ") and "Day" not in line]
        assert len(rows) == 7 and "pts |" in rows[0]

    def test_a_weekend_has_no_forecast_and_says_why(self):
        rt, coord, _ = planner_at(at(SATURDAY, 12), 50)
        coord._now = lambda: at(SATURDAY, 12, 2)
        now, nxt, _, _ = render_all(ha_world(coord))
        assert now.startswith("**No peak prices today (Saturday): solar first, then battery.**")
        assert nxt.startswith("**No peak forecast:** no peak window planned yet.")
        assert "Running short" not in nxt

    def test_a_covered_night_names_the_planned_charge(self):
        rt, coord, _ = planner_at(at(TUESDAY, 22), 15)
        coord._now = lambda: at(TUESDAY, 22, 2)
        _, nxt, _, _ = render_all(ha_world(coord))
        assert nxt.startswith("**Tomorrow, peak 17:00-21:00: covered.** Expected to end at ")
        assert "after the planned charge to %d %%." % round(rt.decision.target_gauge) in nxt

    def test_frozen_data_is_said(self):
        rt, coord, _ = planner_at(at(TUESDAY, 10), 70)
        coord._now = lambda: at(TUESDAY, 10, 2)
        rt.data_stale = True
        now = render_all(ha_world(coord))[0]
        assert "Battery readings are frozen" in now

    def test_old_records_without_dollars_or_predictions(self):
        rt, coord, _ = planner_at(at(TUESDAY, 10), 70)
        coord.store._data["days"] = [{"date": "2026-11-18", "health": {"date": "2026-11-18", "grade": "good",
                                                                       "reasons": [], "gauge_peak_end": 11.0}}]
        _, _, week, pred = render_all(ha_world(coord))
        check_text(week)
        check_text(pred)
        # a missing figure is a dash, never a 0 that reads as "nothing bought"
        assert "| Wed 11-18 | Good | - | - |" in week
        assert "$0.00 of grid energy" in week                       # the total counts only the days that have one
        assert "| Wed 11-18 | - | 11 % | - |" in pred

    def test_a_graded_day_shows_its_figures(self):
        rt, coord, _ = planner_at(at(TUESDAY, 10), 70)
        coord.store._data["days"] = invented_days(coord, n=1, reasons=False)
        _, _, week, _ = render_all(ha_world(coord))
        assert "| Mon 02-15 | Good | 0.0 kWh | $0.00 |" in week


# --- the conditional cards, with the frontend's rules ----------------------------------------
#
# home-assistant/frontend, src/panels/lovelace/common/validate-condition.ts, checkStateCondition:
# an entity that does not exist reads as "unknown"; `state` / `state_not` are a string or a list.


def condition_ok(cond: dict, world: dict) -> bool:
    state = world[cond["entity"]][0] if cond["entity"] in world else "unknown"
    if "state" in cond:
        want = cond["state"]
        return state in want if isinstance(want, list) else state == want
    if "state_not" in cond:
        avoid = cond["state_not"]
        return state not in avoid if isinstance(avoid, list) else state != avoid
    return True


def shown(card: dict, world: dict) -> bool:
    return all(condition_ok(c, world) for c in card["conditions"])


def conditionals() -> dict[str, dict]:
    """The conditional cards by what they wrap: heading text, tile name or card type."""
    out = {}
    for c in cards(load_dashboard()):
        if c["type"] != "conditional":
            continue
        inner = c["card"]
        key = inner.get("name") or inner["type"]
        if inner["type"] == "vertical-stack":
            key = inner["cards"][0]["heading"]
        out[key] = c
    return out


class TestConditions:
    def test_the_dashboard_promises_no_fixed_hour(self):
        text = DASHBOARD.read_text(encoding="utf-8")
        assert "21:10" not in text and "severity" not in text

    def test_pack_section_hides_without_a_pack(self):
        pack = conditionals()["Pack capacity"]
        entity = pack["conditions"][0]["entity"]
        assert not shown(pack, {})                                   # no packs configured: entity absent
        assert not shown(pack, {entity: ("unknown", None)})          # configured, no clean run-down yet
        assert not shown(pack, {entity: ("unavailable", None)})
        assert shown(pack, {entity: ("86.3", None)})

    def test_forecast_gauge_hides_while_unknown(self):
        gauge = conditionals()["Expected at peak end"]
        entity = gauge["conditions"][0]["entity"]
        for state in ("unknown", "unavailable"):
            assert not shown(gauge, {entity: (state, None)})
        assert not shown(gauge, {})
        assert shown(gauge, {entity: ("17", None)})

    def test_the_mode_tile_says_shadow_under_classic(self):
        c = conditionals()
        asked, shadow = c["Inverter mode asked for"], c["Shadow plan (not in control)"]
        planner = asked["conditions"][0]["entity"]
        assert planner.startswith("select.") and asked["card"]["entity"] == shadow["card"]["entity"]
        assert shown(asked, {planner: ("learned", None)}) and not shown(shadow, {planner: ("learned", None)})
        assert shown(shadow, {planner: ("classic", None)}) and not shown(asked, {planner: ("classic", None)})
        assert not shown(asked, {})                                  # select missing: never claim control
