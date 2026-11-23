# Solarseed Peak Shaver - Agent Instructions

Canonical instructions for any agent (Claude Code, Copilot, etc.) working in this repo.
`CLAUDE.md` only imports this file. Global conventions in `~/src/AGENTS.md` still apply
(ASCII only, no Claude branding in commits, notify via `~/src/notify.sh`, etc.).

## What this is

A Home Assistant custom integration (HACS, domain `solarseed_peak_shaver`) that decides
how much to grid-charge a home battery overnight so the house rides through the
weekday TOU mid-peak/peak window on solar + battery. It does NOT talk to the inverter
directly - it fires HA events, and three automation blueprints translate those events
into inverter mode changes.

Owner's live system: Bluetti AC500 (mode entity `select.ac500_ups_mode`), battery kWh
sensor `sensor.available_battery_kwh`, Solcast forecast, PGE (Oregon) Time of Day plan.
Battery capacity configured 23.5 kWh. See `docs/how-it-works.md` for the full runtime
behavior and `docs/analysis-plan.md` for the current overhaul effort.

**Picking up the winter 2026 work? Start with `docs/HANDOFF.md`.** It has the current
state, the one temporary change on the live box, and the next steps.

## Repo layout

| Path | What |
|---|---|
| `custom_components/solarseed_peak_shaver/coordinator.py` | All logic: scheduling, simulation, events, perf tracking, scoring, feedback loop |
| `.../store.py` | Persistent scorecard history (`.storage/solarseed_peak_shaver_history` on HA, 90 days max) + rolling averages + CSV export |
| `.../__init__.py` | Setup + services `recalculate`, `performance_report`, `export_history` |
| `.../sensor.py`, `button.py`, `diagnostics.py` | Entities and HA diagnostics download |
| `.../config_flow.py`, `strings.json`, `translations/en.json` | 3-screen config + options flow |
| `blueprints/automation/solarseed_peak_shaver/` | charge_start / charge_stop / preserve_start blueprints |
| `tools/analyze_performance.py` | Stdlib-only SPC analysis of `export_history` CSVs |
| `tools/claude_analysis_prompt.md` | Prompt templates for LLM analysis of exports |
| `peak_shaver_original.py` | The pre-integration AppDaemon script (historical reference) |
| `docs/` | how-it-works, analysis plan, perf-tracking design, verification + export guides |
| `tests/` | pytest suite with HA mocked (`tests/ha_mocks.py`) - no HA install needed |

Sibling repo `../homeassistant_stuff` holds older exported HA YAML (pre-integration
automations, dashboard, template helpers). It is a snapshot, not the live config.

## Working rules

- **Tests:** `python -m pytest -q` from repo root (about 400 tests, a few seconds, needs `pytest pytest-asyncio pyyaml`). Run before every commit. CI (`.github/workflows/ci.yml`) also validates JSON files and runs on py3.12/3.13.
- **Version bumps** must touch both `const.py` `VERSION` and `manifest.json` `version`.
- **Config keys are persisted** in users' config entries. Renaming/removing a `CONF_*` key or changing an event name is a breaking change - add migration or keep the old key.
- **Store schema:** `store.py` `STORAGE_VERSION = 1`. Adding fields to scorecards is fine (readers use `.get`). Changing meaning of an existing field needs a version bump and a migration, or historical analysis silently mixes semantics.
- **Strings:** any new config field needs entries in both `strings.json` and `translations/en.json`.
- **Deploy path:** HA installs from GitHub via HACS custom repo `danrichardson/solarseed-peak-shaver`. HACS tracks GitHub **releases** (tags `vX.Y.Z`), so a deploy is: push `main`, create the release, update in HACS, restart HA. A push to `main` alone does not reach the box. Before pushing, run `git log origin/main..main` so you know exactly what will be published. Do not push to main, create a release or touch the live HA box without explicit instruction from Dan. HACS installs and updates must be accepted by Dan in the Home Assistant UI; the API refuses them until he has. The acceptance does not carry over to the temporary agent login (refused again for v0.7.1 on 2026-11-19), so in practice Dan clicks install; the agent verifies afterwards.
- **Live HA box is production** (it runs the house battery). Read-only by default: pulling logs/storage/history is fine once access is set up; changing config entries, automations, or inverter modes requires explicit approval each time.
- Delete-worthy junk: `*:Zone.Identifier` files got committed in the pre-migration snapshot (Windows download markers). Safe to `git rm` when convenient.

## Live system access

HAOS 18.x runs as VM 240 (`haos-12.0`) on Proxmox node pve3 (LAN IP ends in .83; see
`~/src/Tools/torrentbox-lx/AGENTS.md`).

Access method (established 2026-11-13): Dan creates a temporary HA administrator user
and deletes it when the work is done; ask him for current credentials, never store them
in this repo. Everything needed so far comes over HA's own HTTP API on port 8123:

- Log in with the `/auth/login_flow` + `/auth/token` flow, then use the bearer token.
- REST: `/api/states`, `/api/history/period/...`, `/api/logbook/...`,
  `/api/diagnostics/config_entry/<entry_id>` (the integration's live config and state).
- WebSocket `/api/websocket`: `recorder/statistics_during_period` (hourly statistics back
  to 2025-05, 5-minute for about 10 days), `automation/config`, `config_entries/get`,
  `supervisor/api` (add-on list, logs).
- Helper scripts live in `analysis/scripts/` (gitignored): `ha.py`, `pull_history.py`.
  In Git Bash set `MSYS_NO_PATHCONV=1` or `/api/...` arguments get rewritten.
- Not needed so far: SSH, `qm guest exec`, copying the recorder DB, InfluxDB (raw Bluetti
  data also lands in the `bluetti` bucket on the metrics container, CT 400 on pve5).

Key files on the HA config volume (reachable through the File editor add-on if needed):

- `/config/.storage/solarseed_peak_shaver_history` - scorecard history (JSON)
- `/config/.storage/core.config_entries` - the integration's live config/options
- `/config/home-assistant_v2.db` (unless recorder is external) - states (~10 days default) + long-term hourly `statistics` table (kept forever for `state_class: measurement` / `total` sensors)
- `/config/home-assistant.log` - INFO/WARNING lines from `custom_components.solarseed_peak_shaver`
- `/config/automations.yaml` - which blueprint automations exist and their mode values

## Analysis workflow

1. Pull raw data off the box into a gitignored/scratch location (never commit household energy data unless Dan asks).
2. Prefer raw HA history/statistics over the integration's own scorecards - the scorecards depend on the very calculations under suspicion (see `docs/analysis-plan.md`).
3. `tools/analyze_performance.py` works on `export_history` CSVs; ad-hoc analysis can use pandas in a scratch venv.
4. Record findings and decisions in `docs/analysis-plan.md` (or a dated doc in `docs/`).
