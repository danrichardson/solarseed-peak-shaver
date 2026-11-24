# Solarseed Peak Shaver roadmap: one chunk at a time, to 1.0

**Next, paste this** (P5 reviewed 2026-11-24, go, on `chunk-P5` at its `P5 review:` commit;
0.9.1 to 0.9.3 ship together as 0.9.3 when Dan says so, and that one install also puts the
holidays on the box before Wednesday 11-25 evening for Thanksgiving. P6 waits for Dan's
word and a data review on 0.9.x; the live checks it owes are listed under P6):

```
ship 0.9.3
```

That sentence and this path are all an agent gets. The other half is [REVIEW.md](REVIEW.md).
Method: `~/src/AGENTS-plan-and-review.md`. Set up 2026-11-23.

## 1. How to run this file

You are an implementing agent. Do exactly one chunk, then stop.

1. **Read:** `AGENTS.md`, the "RESUME HERE" section of `docs/HANDOFF.md`, then this file top
   to bottom. Section 3 (Dan's steer) outranks everything below it. For a chunk marked taste
   or care also read sections 3, 4 and 6 of `REVIEW.md`.
2. **Look around:** `git status`, `git log -5`, `git log origin/main..main`. Untracked and
   not ours, never stage: `docs/ac500-ui-screens.zip`, `docs/whitepaper/`. If someone else's
   uncommitted work is in the tree, do nothing, notify Dan and stop.
3. **Take the pulse before building.** `python -m pytest -q` must be green before you touch
   anything (402 passed, 1 skipped on 2026-11-23). If `analysis/.ha_token.json` exists, look
   at the box read-only (REVIEW.md section 5): config entry `loaded`, the Health sensor, the
   system log for `solarseed` errors. No token: say so in the Log and carry on; do not ask
   for credentials just for the pulse. If the tests are red or the box is sick, the repair is
   this session's chunk: fix it, log it as a Repair, notify, stop.
4. **Pick:** the first row in Progress that is not Done, or the one Dan named.
5. **Check the chunk's facts, then say your plan.** A chunk is intent, not a specification,
   and its pointers go stale. Check them against the code first. Write the plan as the
   opening lines of a new Log entry (what you will build, what you will leave out, how it
   will be seen working) and say the same in chat. Do not wait for an answer.
6. **Build it** on a branch `chunk-<id>` cut from `main`: code, tests, both string files,
   `docs/how-it-works.md` brought up to date, the version bump if the chunk names a release.
   `python -m pytest -q` before every commit. If you changed the learned runtime or planner
   and `analysis/scripts/shadow_replay.py` and its data are on this machine, run it and
   compare with the run before your change.
7. **Leave it safe.** Every new behaviour inside the rails (section 5). A new option reads
   with a default when the key is absent, so an upgrade with no form submitted behaves
   sensibly.
8. **Record:** mark the row "Built <date>" with the branch and commit. Finish the Log entry:
   what was built, what you skipped, what you were unsure of, and the Look-at list.
9. **Notify once:** `~/src/notify.sh --event=ready-for-review --priority=3` with the
   Look-at list, short enough for a lock screen.
10. **Stop,** and end your last message with the sentence to paste next, alone in a code
    block: the review sentence if the chunk says review, else the build sentence. Rewrite
    the line at the top of this file to match.

- **Blocked** on something only Dan can answer: `--event=needs-input` with the question in
  the body; carry on with whatever does not depend on it; if nothing does, stop.
- **Too big:** build the first useful half, mark the row Part, add a row for the rest.
- **Review:** you do not review your own chunk.

**Already authorized:** commits on `chunk-<id>` branches, messages prefixed `P<n>:`;
read-only calls to the box when a token is already cached; running anything under
`analysis/scripts/` that only reads.

**Not authorized, each needs Dan's word at the time:** merging to `main`, pushing, tagging,
creating a release; any write to the Home Assistant box (options, automations, helpers,
inverter modes); asking HACS to install. Dan ships with one sentence, `ship <version>`,
after a review says go. A ship is: fast-forward `main`, `git log origin/main..main`, push,
tag `vX.Y.Z`, `gh release create` with notes, notify Dan to click install in HACS and
restart HA (after 21:00 or with no charge running), then verify read-only. Mark the row
Done only when the version is verified on the box.

**Keep the repo tidy.** This file is the only plan. `docs/HANDOFF.md` is the state record
and the history; `docs/tuning-log.md` is the record of review sessions on the data;
`docs/ROADMAP.md` holds the detailed notes behind the chunks (its item numbers are referred
to from code comments, so do not renumber it). Write no other planning or analysis
documents. Stage files by name, never `git add docs` or `git add -A`. Scratch goes under
`analysis/` (gitignored). When the Log passes twelve entries, cut the oldest to one line
each.

## 2. Progress

| # | Chunk | Release | Needs | Review | Status |
|---|---|---|---|---|---|
| P1 | Thanksgiving: holidays, and the false alarm at full | 0.8.2 | care | yes | Built 2026-11-23, `chunk-P1` 745c6b2 |
| P2 | Settings you can find | 0.9.0 | plumbing, care | yes | Built 2026-11-24, `chunk-P2` 95761f0 |
| P3 | Tariff as data | 0.9.1 | care | yes | Built 2026-11-24, `chunk-P3` eb18a74 |
| P4 | The dashboard | 0.9.2 | taste | yes | Built 2026-11-24, `chunk-P4` f443a46 |
| P5 | A stranger can install it | 0.9.3 | care, taste | yes | Built 2026-11-24, `chunk-P5` 2851170 |
| P6 | Ready to be seen | 1.0.0 | taste, Dan's word first | yes | |
| P7 | Refill | | | | |

Every chunk here ends up running a house battery unattended and in a public repository, so
every chunk is reviewed. Chunks that share a release may be shipped together.

**Not a build chunk: the first data review.** From 2026-11-30, in its own session with a
fresh temporary HA login, following "How a review session works" in `docs/tuning-log.md`.
Leave out 11-22, 11-23 and 11-26. Whatever it decides goes into section 3 or the next chunk.

## 3. Dan's steer

Dan writes here, or tells an agent to. Read it first and obey it over any chunk text. When
you have acted on a note, quote it in your Log entry and remove it from here.

(empty)

## 4. Where this is going

Dan, 2026-11-23 (dictated):

> "I'd like to get this thing done and feature complete if we can"

> "do we need to put any kind of GUI or editor on the parameters"

> "Let's make this a public release."

> "It's Monday. You agents think everything takes so freaking long. ... We could totally
> have that done by two hours from now. So, yes, thanksgiving is cool. ... I want it in
> there. Let's go for it"

> "if we have to iterate on brainstorms for what some of the details are, let's do it"

So: version 1.0 is a public release that somebody with a different utility and a different
inverter can install from HACS, set up from the forms, and watch on a dashboard. Chunks are
small and fast. Where a detail is open the chunk gives a default; build the default and
list the open point in the Look-at list instead of stopping.

What has been learned so far (details in `docs/HANDOFF.md` and
`docs/winter-2026-findings.md`; do not re-derive):

- The measure of success (Dan, 2026-11-16) is grid energy through the inverter in mid-peak
  and peak, and what it costs. The recoverable waste is about $10 a month, so keep every
  feature proportionate.
- The learned planner is in control on the owner's box since 2026-11-22. The classic
  planner still computes beside it. From 1.0 classic is legacy: selectable, no new features
  (a default taken on 2026-11-23; Dan has not ruled on it).
- The integration never talks to the inverter. It fires three events; blueprints act. Event
  names and `CONF_*` keys are contracts.
- Sensors lie at the edges: 0 for unknown at startup, exact stillness when idle, the
  battery carrying the house for half an hour after a full charge. Every one of the last
  three releases fixed a case of this.

## 5. The rails

**Never**

- Push, tag, release, or write to the box without Dan's word at the time.
- Rename or remove a `CONF_*` key, an event name, a service, or an entity's unique id.
- Change the meaning of an existing scorecard field without a `STORAGE_VERSION` bump and a
  migration. Adding fields is fine.
- Commit household data, credentials, IP addresses, names, or the times of the owner's own
  actions. `analysis/` stays local.
- Write non-ASCII characters in code, strings, docs or commits. No Claude branding or
  co-author lines in commits.
- Let a missing, unknown or frozen reading count as a number.

**Anything that acts by itself** (starts a charge, releases a hold, sends a message):

- Fenced: it has an option that turns it off, and the off state is the old behaviour.
- Safe when blind: with a reading missing it does nothing, or does what the night rule
  already does (charge to full in the full months). It never charges in peak.
- Quiet after a restart: the first tick may start a charge and nothing else.
- Visible: the decision and its reason are on a sensor attribute and in the log.
- Rationed: at most one notification per event, none on days that are not graded.
- Tested with Home Assistant mocked (`tests/ha_mocks.py`), including the absent-key case
  and an unavailable sensor at setup.

**What runs by itself today**

| What | How often | Where it is limited |
|---|---|---|
| Daily health message | once per graded day, 21:10 | `health.py`, `coordinator._send_daily_notifications` |
| "Review needed" message | once per change to review | Health sensor |
| "Battery data frozen / back" | once per freeze | `stale_minutes` option, 0 = off |
| Command resend | 3 per commanded mode, then one alert | `VERIFY_RETRIES` in `learned_runtime.py` |
| Setup check: repair issue + log line (no notification, no action) | every 10 min once HA runs; logs only on change | `setup_check.py`, `CHECK_EVERY` |

Add a row when a chunk adds something.

## 6. The chunks

### P1. Thanksgiving: holidays, and the false alarm at full (0.8.2)

**Dan:** "thanksgiving is cool ... I want it in there." Thursday 2026-11-26 is the first live
holiday. It has to be installed by Wednesday evening, because the night rule looks at
tomorrow from 21:00.

**Done when**

- On 2026-11-25 at 21:30 the learned planner does not plan a pre-TOU night charge, on
  2026-11-26 it treats the day as off-peak all day and nothing is graded or notified, and
  on the evening of 2026-11-26 it plans Friday's charge as usual. Tests show all three.
- The six PGE holidays and the Saturday-to-Friday, Sunday-to-Monday shift are computed, not
  listed by year. Tests: Fri 2026-07-03, Mon 2027-07-05, Fri 2027-12-24, and Fri 2027-12-31
  (the observed day for 2028-01-01, in the year before).
- There is exactly one function that says whether a date is a TOU day, and every caller uses
  it: `grep -n "weekday()" custom_components/` shows no other day-type test.
- With the readings of 2026-11-23 evening (hold commanded, gauge 100, grid 0 W, load about
  0.6 kW) `mode_matches` returns None: no resend, no error, no `commands_not_followed`.
- 0.8.2 in `const.py` and `manifest.json`; `docs/how-it-works.md` has "0.8.2 additions".

**Where to start** (checked 2026-11-23)

- `learned_runtime.py`: `is_tou_day(d, weekdays_only)` at the top, eight call sites, and
  `mode_matches` / `infer_mode` beside it. `MODE_CHARGE` already returns None when
  `bank_full` or the gauge is 95 or more; `MODE_HOLD` has no such case.
- `coordinator.py`: six inline `self.weekdays_only and now.weekday() >= 5` tests
  (scheduled time, forecast update, preservation, SOC checkpoint, daily scoring, and the
  refresh). `_classify_period` is what names the price window.
- The weekly top-up in `learned_runtime.py` ("Owed once, from peak end on the last TOU day
  of the week") uses today-TOU and tomorrow-not-TOU. With holidays that also fires on the
  evening before a mid-week holiday. Decide what is right and test it.
- `planner.py` takes `is_tou_today` and `is_tou_tomorrow` as inputs and needs no change.
- Rules and test dates: `docs/ROADMAP.md` item 7. The false alarm: `docs/HANDOFF.md`,
  "What is left to develop", item 1.

**Defaults for the open points**

- A new pure module `holidays.py` (no Home Assistant imports), rules as data: fixed date,
  nth or last weekday of a month, observed-day shift.
- New option `holiday_preset`, values `none` and `pge`, default `pge` when the key is
  absent (every other default in this integration is already PGE, and it makes Thursday
  work without anyone submitting the options form). P3 adds custom rules beside it.
- A holiday is a non-TOU day everywhere: planning, scoring, grading, and the load profile
  (it goes in the "other days" history).
- `holiday_today`, `holiday_tomorrow` and `next_holiday` attributes on the Learned Plan
  sensor.
- Hold at full: None while `bank_full` or the gauge is 99 or more. Look at whether
  `infer_mode` (the read after a restart) makes the same mistake.

**Leave out:** the gap between 21:10 scoring and midnight (P2), custom holiday rules (P3).

**Dan should look at:** the Learned Plan sensor on Wednesday night (it should say holiday
tomorrow and not be charging for it), and that no daily message arrives on Thursday.

### P2. Settings you can find (0.9.0)

**Dan:** "do we need to put any kind of GUI or editor on the parameters". Today the options
are one flat form of 33 fields that saves wholesale; flipping the planner needed a script.

**Done when**

- The options flow opens on a menu: Battery and sensors, Schedule, Learned planner,
  Third-party packs, Notifications, Classic planner (legacy). Saving one section leaves
  every other stored option as it was (test it with keys the form never showed).
- The settings that get tuned are entities on the device page, each changing one stored
  option and taking effect without a restart: a select for the planner; numbers for peak
  margin, load quantile, solar confidence and gauge floor; a select for the holiday preset.
- An event between the 21:10 scoring and midnight lands in a graded day.
- No key renamed; an entry saved by 0.8.x loads unchanged.

**Where to start**

- `config_flow.py`: `PeakShaverOptionsFlow.async_step_init` builds the single schema. Home
  Assistant's `async_show_menu` gives the menu; each step merges into
  `{**entry.options, **user_input}`.
- `__init__.py`: `PLATFORMS` is sensor and button; add select and number. Look at how an
  options change reaches the coordinator today (`_cfg` in `coordinator.py` reads options
  over data) and whether an update listener reloads the entry. A reload on every number
  change restarts the learned runtime; avoid that or prove it is harmless (the first tick
  after a start is restricted).
- Scoring gap: `_on_daily_scoring_time` in `coordinator.py` and `_roll_day` /
  `daily_summary` in `learned_runtime.py`.

**Defaults:** entity changes write the config entry options (one source of truth, no
second store). Health thresholds stay constants until the data review says they are right.
For the scoring gap, carry late events into the next graded day's summary, marked with
their date, in preference to moving the 21:10 message.

**Dan should look at:** the options menu in the HA UI, and the planner select on the
device page.

### P3. Tariff as data (0.9.1)

**Why:** a public release cannot assume PGE. Prices are constants in `health.py`; the
hours are three options; seasons do not exist.

**Done when**

- A tariff is data: named periods by day type (weekday, weekend, holiday) with prices,
  optional seasons, and holiday rules. PGE Time of Day is a preset that reproduces today's
  behaviour exactly (a test compares period and price for every hour of a sample week
  against the 0.9.0 code).
- An existing entry with only `midpeak_start_hour`, `peak_start_hour`, `peak_end_hour`
  works unchanged; those three keys stay.
- Holiday rules can be typed (`01-01`, `11-thu-4`, `05-mon-last`, `sat->fri, sun->mon`) and
  one-off dates added; presets PGE and US federal fill the field.
- Dollars come from the tariff in the health record, the daily message and the plan sensor.

**Where to start:** `docs/ROADMAP.md` items 7 and 8; `health.py` `PRICE_*`;
`coordinator._classify_period`; the planner's three-window model in `planner.py`. Since
0.9.0 the options are a menu: a tariff section is a new entry in `options.SECTIONS`, and any
tariff key the timers read at start belongs in `RELOAD_KEYS` and `setup_signature`. A new
`CONF_*` key needs, in this order or the tests say so: a section in `options.SECTIONS`, a
field in `config_flow._FIELDS`, a label in both string files under `options.step.<section>`,
and `CLEARED_VALUE` if it is optional. A new holiday preset appears in the device-page select
by itself (`select.SELECTS` reads `HOLIDAY_PRESETS`) but needs its name under both
`entity.select.holiday_preset.state` and `selector.holiday_preset.options` in the strings.
Prices and periods are read on every tick (`_classify_period`, `health.py`), so only the
timers' hours need a reload; test a changed tariff with `async_options_updated` as
`tests/test_options.py` does.

**Defaults:** keep the planner's shape of three windows (cheap, middle, dear) and map a
tariff onto it; a tariff that does not fit that shape (two dear windows a day, say) is
refused in the form with a plain message, not half-supported. A season changes hours and
prices, never the planner's rules.

**Dan should look at:** the tariff section of the options, and that his own daily message
shows the same dollars as before.

### P4. The dashboard (0.9.2)

**Why:** the owner should see it working without a review session, and a stranger should
see what the thing does before trusting it with a battery.

**Done when**

- `dashboards/solarseed.yaml` in the repo, built from stock Home Assistant cards only,
  pasteable as a new dashboard, with the entity ids in one place at the top.
- It answers, in this order: what is it doing now and why; will tonight's peak be covered;
  how did the last seven days go, in grades and dollars; what did it predict against what
  happened; pack capacity trend if packs are configured.
- Any sensor it needed and did not exist is added (prediction against actual as a sensor
  with history, today's plan as one plain sentence).
- A screenshot in `docs/` made from invented data, not the owner's.

**Where to start:** `sensor.py` (Learned Plan, Learned Energy Remaining, Health, pack
sensors and their attributes); `docs/ROADMAP.md` item 6. Since 0.9.1 the Learned Plan
sensor carries the tariff (`tariff`, `season`, `day_type`, `price_windows`, `prices`,
`price_period`, `price_now`) and dollars (`handover_cost_usd`, `shortfall_cost_usd`), and
each health record carries `cost_usd` with the `prices` it used; take dollars from there,
never from a constant in a card. Build the dashboard on `chunk-P3` (0.9.1 is reviewed and
not yet shipped); 0.9.1 and 0.9.2 can go out as one release.

**Defaults:** no custom cards and no custom panel. If one chart cannot be done with stock
cards, offer an optional second file that uses `apexcharts-card` and say so.

**Dan should look at:** the dashboard on his own box, first card first. Taste: he reacts,
the reaction goes verbatim into REVIEW.md section 3.

### P5. A stranger can install it (0.9.3)

**Done when**

- The first-time config flow offers the learned planner's sensors (gauge, load, grid, PV,
  tomorrow's forecast) and a new install with them starts on `learned`; an existing entry
  is untouched.
- Each form field has a description that says what to pick and what happens if it is left
  empty, in `strings.json` and `translations/en.json`.
- A missing required sensor, or blueprints that are not installed, show up as a Home
  Assistant repair issue or a plain log line, not as silence.
- The three blueprints import cleanly from the GitHub URL and their descriptions name the
  inverter modes for at least the AC500 as an example.
- The classic planner is marked legacy in the form and the docs.
- The three committed `*:Zone.Identifier` files are removed with `git rm`.

**Where to start:** `config_flow.py` steps `user`, `schedule`, `notifications`;
`blueprints/automation/solarseed_peak_shaver/`; `README.md` installation section;
`diagnostics.py` for what is redacted. The first-time `schedule` step still checks only
`mid > peak` and allows peak end 24: route it through `options.check_tariff` (the Tariff
section's checks, 0.9.1) or at least the same hour rules, and offer the prices there. Look
at the Tariff form in a real HA: the optional off-peak price is a number selector with an
empty suggested value, and the error texts rely on `description_placeholders`; neither has
been seen in a browser. Say plainly in the form or docs that a two-price plan (no mid-peak)
holds the battery on grid all day before peak start, which no inverter has been watched
doing, and that `tools/analyze_performance.py` prices with its own constants.

**Defaults:** solar forecast stays Solcast-shaped (`detailedHourly` / `detailedForecast`);
say so plainly in the form instead of building a second forecast adapter.

**From the P4 review:** a new install should start on `learned` (this chunk's first line),
so the dashboard's "Shadow plan (not in control)" tile is the exception, not the first
thing a stranger sees. The dashboard has still never been pasted into a real Home
Assistant; if P5 gets a browser on a box, paste `dashboards/solarseed.yaml` and check, in
this order: the markdown cards render (`config.ids`), the top-level `solarseed_ids` key
survives a save, no card shows "Entity not available", the pack section is hidden with no
packs (outside edit mode; conditional cards always show while editing), and the heading
cards exist (HA 2024.10+). Say in the README which HA version the dashboard needs.

**Dan should look at:** a walk through "add integration" on a scratch entry, if he is
willing to remove it afterwards; otherwise the reviewer reads every form string.

### P6. Ready to be seen (1.0.0) - Dan's word first

Do not start until Dan says so; it follows at least one data review on 0.9.x.

**Done when:** the README describes the integration as it is now (the learned planner
first, what it needs, what it will and will not do, the dashboard screenshot, honest
limits: one inverter family tested, Solcast, three price windows); `docs/how-it-works.md`
is rewritten in present tense from the code, not as layers of additions; `HACS.md`,
`hacs.json` and the manifest meet the HACS default-repository checks; the changelog covers
0.7 to 1.0; no household detail anywhere in the tracked tree (search for it); version 1.0.0.

**From the P5 review** (nothing in 0.9.3 has been seen in a Home Assistant UI; these are
owed, read-only unless Dan says otherwise, before or with 1.0): on the box, `/api/events`
lists the three `solarseed_peak_shaver_*` events with a listener count of at least 1 and
Settings, System, Repairs is empty ten minutes after the 0.9.3 restart; the four first-time
screens seen once on a scratch entry (the optional off-peak price box, a refused tariff with
its `{prices_detail}` text, load without grid refused), then the entry deleted; one blueprint
imported from its README URL; a repair issue's text with its `- ` lines rendered (make one by
typing a wrong sensor in Battery and sensors, then put it back); the P4 dashboard paste
list. HACS and hassfest: the `issues` and `config.step.learned` strings pass hassfest only in
CI so far; check the default-repository rules against `hacs.json` (2024.11.0) and the
README. History: the three removed download markers were one blob naming a Windows user
folder in a download path, and it stays in the public history; "no household detail
anywhere" is a decision from Dan on a rewrite, not a search of the tree. The README still
opens with the classic planner's "How it works"; the learned planner goes first.

**Dan should look at:** the README top to bottom as a stranger would.

### P7. Refill

When the rows above are Done: read the idea shelf, the Log and the latest tuning-log entry,
propose three chunks to Dan in a notification, and stop.

## 7. Idea shelf

Not in 1.0. Notes are in `docs/ROADMAP.md` under the item numbers given.

- Outage mode (10); top-off charging for third-party packs (9); learn the handover rule
  with the reserve at 6 % (11).
- Is 23.5 kWh per 100 % too high, or is 0.25 to 0.3 kW idle overhead real? Pack current
  from the metrics container would settle it (`docs/tuning-log.md`, 2026-11-23).
- Health thresholds as options, once a review shows which ones people would change.
- A second forecast source; a second inverter family's blueprints.
- White paper 0.95 and 1.0: a separate session with `docs/whitepaper-brief.md`.

## 8. Log

Newest last. One entry per session: plan, what was built, what was skipped, Look-at list,
then the reviewer's `Review:` line.

- 2026-11-23, setup. Wrote this file and REVIEW.md from the code, git history and
  `docs/`. Not verified: the box (no token on this machine; state taken from the handoff of
  the same evening). Open with Dan: the classic planner as legacy, and what "e and uing"
  meant in his first message (not assumed to authorize pushes).
- 2026-11-23, P1 build. Plan: a pure `holidays.py` with the one `is_tou_day` and the PGE
  rules as data; every day-type test in the coordinator and the runtime through it; option
  `holiday_preset` (default `pge` when absent); holiday attributes on the Learned Plan
  sensor; hold at full and the restart read made "cannot tell"; 0.8.2. Leave out the
  21:10-to-midnight gap (P2) and custom rules (P3). Seen working by tests on the
  Thanksgiving week and by the shadow replay. Pulse: tests green (402 + 1 skipped); no
  token on this machine, box not checked.
  Built: as planned, on `chunk-P1` (745c6b2). 436 passed, 1 skipped. `grep -n "weekday()"`
  finds only `holidays.py` (a test enforces it). Decided: the weekly top-up is owed on the
  last TOU day of a Monday-to-Sunday week (TOU today, not tomorrow, no TOU day left in the
  week), so Wednesday 11-25 owes none and Friday 11-27 does; a Friday holiday moves it to
  Thursday; an every-day plan with no holidays still never owes one. `infer_mode` had the
  same blind spot: at 99 % or more with no grid input it said "discharge", which in a
  non-full month would have let the battery run down overnight after a restart; now None,
  so the first decision is adopted. `mode_matches(hold)` and `infer_mode` also return None
  with no gauge (was: judged anyway). Shadow replay with learned in control, before and
  after: the only difference is the three resends and the "did not follow the hold
  command" error gone (86 to 83 events).
  Skipped: `analysis/scripts/backtest.py` keeps its own hard-coded holiday list (local,
  untracked). Unsure: the preset applies even with weekdays-only off (an every-day plan
  still gets PGE holidays unless set to `none`); `holiday_today`/`holiday_tomorrow` are
  the holiday's name or null, not booleans; the options form gained one field in the old
  flat form (P2 reorganizes it).
  Look at: Wednesday 11-25 evening, the Learned Plan sensor shows `holiday_tomorrow:
  Thanksgiving`, phase off-peak, no charge; no daily message on Thursday; a night charge
  Thursday evening for Friday; the next full-charge evening has no "not responding" error.
  Ship by Wednesday evening (the night rule looks at tomorrow from 21:00).
- 2026-11-24, P2 build. Plan: the options flow opens on a six-item menu, each section saves
  `{**entry.options, **user_input}` (a cleared optional sensor is stored as empty so it does
  not fall back to the setup data); new `select` and `number` platforms with the planner,
  holiday preset, peak margin, load quantile, solar confidence and gauge floor, each writing
  one option; an update listener that reloads only when a setting read at setup changed
  (sensors, hours, schedule, packs), never for the six tuning entities (they are read live
  every tick); events after the 21:10 scoring carried into the next graded day's summary,
  marked with their date; 0.9.0. Leave out health thresholds as options and the first-time
  flow (P5). Seen working by tests (form sections with keys the form never shows, entity
  writes without a reload, a Friday 23:00 ignored command in Monday's grade) and the shadow
  replay. Pulse: tests green (436 + 1 skipped); no token on this machine, box not checked.
  Built: as planned, on `chunk-P2` (95761f0), stacked on P1 because main has not shipped.
  530 passed, 1 skipped; with voluptuous on the path (a gitignored scratch copy; CI and this
  machine lack it, so `test_config_flow.py` is skipped there) 556 passed. Menu: Battery and
  sensors, Schedule, Learned planner, Third-party packs, Notifications, Classic planner
  (legacy); `options.py` holds the sections (every `CONF_*` key in exactly one, a test checks)
  and the merge. The battery SOC sensor and today's forecast are now editable there (they
  were setup-only). Schedule checks mid-peak < peak < end, as setup did. The update listener
  is new (there was none: settings read at start waited for a restart); it compares the
  integration's own reading of nine settings read at start (`RELOAD_KEYS`) and reloads only
  when one differs, so the hours as a list or as text do not trigger it. Late events: the
  scoring snapshots `command_retries`, `commands_not_followed`, `stale_minutes` and the
  longest frozen stretch; at midnight the gain is kept with its date under a new
  `late_events` key, graded on the next graded day ("inverter ignored a command late on
  11-27"), cleared once graded, kept while the next scoring has nothing to grade, carried
  over a restart across midnight. Existing scorecard and health fields keep their meaning
  (no storage bump). Shadow replay with learned in control, P1 base against P2: identical
  (decisions, 83 events, summary). A scratch variant that also does the 21:10 scoring shows
  the carry on recorded evenings (11-12, 11-16, 11-17, 11-18 each carried one ignored command
  into the next weekday and cleared after it); those are the replay's usual artifacts (the
  recorded days ran classic, so learned commands were never followed), not box faults.
  Skipped: health thresholds as options; the first-time flow (P5). Unsure: events on a day
  that is not scored (weekend, holiday) are still not carried, by design (those days stay
  ungraded), so a Saturday ignored command shows only in its own alert; carried retries
  alone do not change a grade; `hacs.json` says HA 2024.1.0 but the options flow already
  relied on HA setting `OptionsFlow.config_entry` (2024.11+), unchanged here (P5/P6).
  Look at: the options menu (six sections, labels, a save in one section leaves the others);
  the Planner select and four numbers on the device page under Configuration; switching
  Planner there should log "Option planner set to ... from the device page" and no reload;
  the first daily messages after install, since any real evening "not followed" now shows
  in the next weekday's grade.
  Review (2026-11-24, go): checked 95761f0 and 1d30455 against e8330c2. Read the diff whole,
  `options.py`, `select.py`, `number.py`, `config_flow.py`, the runtime's late-event code and
  the three new test files. 530 passed, 1 skipped; 556 with voluptuous on the path; diff is
  ASCII; `const.py` and `manifest.json` agree; strings.json equals en.json; `weekday()` only
  in `holidays.py`; shadow replay (learned in control) gives the same 83 events and decisions
  as P1. Walked: every setting the timers and state listeners capture at start is in
  `RELOAD_KEYS` (hours, calculation hours, hold switch, battery/forecast/production sensors,
  packs); the six device-page settings and the power sensors are read each tick; an 0.8.x
  flat-form options dict reads unchanged; a Friday 23:00 ignored command is carried to
  Monday, graded Poor once, then cleared; a weekend or holiday carries nothing because the
  scoring does not run; a scoring that grades nothing keeps the list; a restart over midnight
  keeps it. Changed: CI now installs voluptuous, so `test_config_flow.py` runs there instead
  of skipping (it had skipped silently since 0.8.1), and compiles the three new modules
  (5847319). Not verified: the HA UI (menu, device page) and hassfest on the new `entity`
  strings; no box token. Noted, not blockers: the Battery section does not check that a
  typed sensor exists (setup does); a late frozen stretch is capped at the minutes since the
  scoring, so a stretch spanning 21:10 is under-reported, never over.
- 2026-11-24, P3 build. Plan: a pure `tariff.py`: three named periods (off-peak, mid-peak,
  peak) with prices; weekday windows from the three legacy hour keys (kept); the weekend from
  `weekdays_only`; holidays off-peak all day; optional seasons that change hours and prices by
  month; the holiday calendar. PGE Time of Day is the preset and the default, so an entry with
  only the three hour keys reads the same. Holiday rules typed as text in `holidays.py`
  (`01-01`, `11-thu-4`, `05-mon-last`, `sat->fri, sun->mon`) plus one-off dates; presets none,
  PGE, US federal and custom, a preset filling the rules field on save. The Schedule section
  becomes Tariff (hours, weekdays, prices, seasons, holidays); a tariff that does not fit the
  planner's cheap/middle/dear shape is refused with a plain message. Dollars in the health
  record, the daily message and the plan sensor from the tariff of that date. Timers for every
  season's hours, acting only on the day's own. 0.9.1. Leave out: weekend hours unlike the
  weekday's (refused), more than three periods, a currency other than dollars, the first-time
  flow (P5). Seen working by: every hour of two sample weeks against a frozen copy of the
  0.9.0 rules, form tests with voluptuous, a summer season through the runtime, the shadow
  replay before and after. Pulse: tests green (530 + 1 skipped; 556 with voluptuous); no
  token on this machine, box not checked.
  Built: as planned, on `chunk-P3` (eb18a74), on P2 with its review (e06ac3b). 590 passed,
  1 skipped; with voluptuous on the path 621 passed, none skipped. The coordinator builds the
  tariff from the options (cached); `windows_on(date)` and `period_at(when)` replace the three
  fixed hours wherever a date is known (the learned runtime's planner inputs, grid booking,
  handover record, gauge checkpoints, weekly top-up); the classic planner and the sensors use
  today's. Exactness: every hour of three sample weeks (Thanksgiving 2026, 2027-07-05 and
  2027-12-31 observed) matches a frozen copy of the 0.9.0 rules in period and price, from the
  preset, absent keys, a 0.8 flat-form entry and an entry with only the three hour keys; the
  health cost and daily message are identical. Shadow replay with learned in control, before
  and after: identical (83 events, the same decisions and summary). The Schedule section is
  now Tariff (eleven fields). Refused with the reason: two peak or mid-peak windows, a gap or
  mid-peak after peak, a window across midnight, off-peak hours, a month in two seasons,
  prices not rising (the mid-peak price ignored when there is no mid-peak window), bad rules
  or dates. Mid-peak start equal to peak start is accepted as a two-price plan (refused
  before, here and in the first-time flow). Holiday presets none, pge, us_federal (11) and
  custom; the rules field shows the rules in force, a chosen preset fills it on save, edited
  rules make it custom; the device-page select lists all four. A season's hours reload the
  entry; its months, prices and the holidays do not. Health record gains `prices`; Learned
  Plan gains `tariff`, `season`, `day_type`, `price_windows`, `prices`, `price_period`,
  `price_now`, `handover_cost_usd`, `shortfall_cost_usd`. No key renamed, no storage change.
  Skipped: weekend hours unlike the weekday's (cannot be typed); a currency other than
  dollars; a tariff-preset selector (PGE Time of Day is the default and only preset, named on
  the sensor); `tools/analyze_performance.py` keeps its own approximate rates (an offline tool
  on classic CSVs that cannot import the integration package); the planner's reason text
  stays in kWh (the dollars are attributes).
  Unsure: the night after peak end is planned with today's hours, so on the one night a
  season starts the first plan uses the old mid-peak start until midnight; with no mid-peak
  window the whole day before peak start is "the night before" for the learned planner
  (charge timed to end at peak start, then hold), right by price but never seen on a box
  (does the inverter's hold still take PV?); that the HA frontend fills an error's detail
  from `description_placeholders` (believed, not seen); after the first save of the Tariff
  section the preset's rules are stored as text too (harmless: a preset's own rules are used
  unless custom); peak end 24 still schedules at 00:xx, as before.
  Look at: Configure, Tariff (eleven fields, the PGE rules in Holiday rules, prices 0.1670 and
  0.4313); save it unchanged and nothing changes; type a season with two peak windows to see
  the refusal; the Learned Plan sensor's new attributes (`tariff: PGE Time of Day`,
  `price_now`, `handover_cost_usd`); the next daily message shows the same dollars as before;
  the holiday select lists US federal and Custom.
  Review (2026-11-24, go after small fixes, made): checked eb18a74 and 9cd0a81 against
  e06ac3b. Read `tariff.py`, `holidays.py` and `test_tariff.py` whole, the diffs of the
  coordinator, runtime, planner, health, options, config flow, sensor and both string files.
  590 passed, 1 skipped; 621 with voluptuous; strings.json equals en.json; `const.py` and
  `manifest.json` agree; the diff is ASCII; shadow replay (learned in control) gives the
  same 83 events and decisions as 0.9.0, before and after the fixes; PGE prices are the
  0.9.0 constants and the default entry is the preset object itself. Walked: a Thanksgiving
  week, a two-price day, a July season day, a stored season that no longer parses, absent
  and unreadable price keys. Fixed (914e341): after today's peak end the night rule planned
  tomorrow with today's hours, so the night a season changes sized the charge for the wrong
  window and timed it to the old mid-peak start (`PlanInputs.next_midpeak_start`,
  `next_peak_end`; the runtime passes tomorrow's); the Done-when's day types gained the
  weekend's own hours and prices as a `weekend:` line in the seasons text (a season with
  no months; needs weekdays-only off, refused otherwise); the Tariff form refuses peak end
  24, which scheduled the scoring and the peak-end checkpoint at 00:xx on the next date
  after the counters reset (never graded; so since 0.8). 603 passed, 1 skipped; 634 with
  voluptuous. Not verified: the HA form (number selector with an empty suggested value for
  the optional off-peak price, `description_placeholders` in error text); no box token.
  Noted, not blockers: `tools/analyze_performance.py` keeps its own 0.09/0.18/0.44 (P6
  honest limits, or take prices from the export); the first-time flow still allows peak end
  24 and `mid > peak` only (P5 owns it); a two-price plan holds all day before peak start
  (right by price, never seen on an inverter); the classic planner projects the night with
  today's hours (legacy). Nothing in 0.9.1 needs to reach the box before P4.
- 2026-11-24, P4 build. Plan: `dashboards/solarseed.yaml`, one sections view of stock cards,
  the entity ids once at the top as YAML anchors, answering in the chunk's order: now and
  why; the next peak; the last seven graded days in grades and dollars (from the health
  records); predicted against what happened; pack capacity when packs exist. Two sensors it
  needs: Plan Summary (the plan as one sentence) and Peak End Forecast (the gauge expected
  at the next planned peak end, with history), both read-only views of the learned
  planner's last decision in a pure `outlook.py`. Tests for the sensors and the file, the
  templates rendered against the real sensors' attributes. A picture in `docs/` from
  invented data. 0.9.2. Leave out: custom cards (no chart needed one, so no apexcharts
  file), the run-down voltage curve and energy per gauge band from item 6, the first-time
  flow (P5). Seen working by the template renders, the picture and the shadow replay.
  Pulse: tests green (603 passed, 1 skipped; 634 with voluptuous); no token on this machine
  (no `analysis/.ha_token.json`), box not checked.
  Built: as planned, on `chunk-P4` (f443a46), on P3 with its review (930954d). 653 passed,
  7 skipped (the six template renders need jinja2, plus the config-flow file); on the
  flow-enabled path (`analysis/p2_pydeps`, now with jinja2) 690 passed, none skipped. CI
  installs jinja2 and parses the dashboard. The file: heading, markdown, tile, gauge,
  history-graph, statistics-graph, conditional and vertical-stack; HA 2024.10 or later
  (heading card, sections view). The markdown cards carry the id block and read it as
  `config.ids` (the markdown card's documented `config` template variable); HA expands the
  anchors on save, so the ids are edited in the file before pasting. Two ids are the user's:
  the battery gauge (an AC500's by default) and the packs' "Ah Between" sensors (a
  placeholder "Pack 1"; the pack section hides while that entity does not exist). Dollars
  come only from `cost_usd`, `shortfall_cost_usd` and `handover_cost_usd`. The forecast is
  the health record's own prediction (`predict_gauge`, mean load), so at mid-peak start it
  equals `pred_gauge_peak_end` (a test), started from the night target before mid-peak, the
  top-up target during a top-up, else the gauge now; unknown with no gauge, an untrained
  model, or no peak planned, `why_none` says which. The sentence covers night, mid-peak
  (covered, short with the dollar figure, topping up), peak, the night before, Friday,
  weekend, holiday by name, weekly top-up, no gauge, untrained, and "Shadow plan" under
  classic; ASCII, clipped at 255. Found by the new tests and fixed: the learned runtime
  read a `nan` or `inf` state as a number, and a `nan` gauge raised in the mid-peak top-up
  sizing (`int(nan)`) on every tick, toward the failsafe; `_float_state` now treats a
  non-finite value as missing, as the coordinator already did (not seen on the box; a test
  feeds nan, inf, -inf, empty, unknown). Shadow replay, learned in control, P3 baseline
  against P4: stdout identical (45 lines, 83 events, same decisions and summary; diffed by
  `analysis/scripts/p4_replay_compare.py`). Picture: `docs/dashboard.png`, 1440x1200,
  invented February week (a trained-looking model from the test helpers, seven invented
  graded days, invented gauge and pack histories), drawn with Pillow by
  `analysis/scripts/p4_draw_dashboard.py`: the card order, options and markdown templates are
  the file's own, rendered with Jinja against the real sensor classes; the look of the
  stock cards is imitated, and a note on the image says it is not a Home Assistant
  screenshot. Headless Edge (the first choice, via `p4_render_dashboard.py`'s HTML page)
  could not be launched in this session's permissions, and no HA runs on this machine.
  Skipped: an apexcharts file (not needed); item 6's voltage curve and energy per band
  (noted in `docs/ROADMAP.md` item 6); a translation of the mode state on the tile (it shows
  `discharge`, `hold`, `charge` raw; the Now card's reason says it in words).
  Unsure: the dashboard has never been pasted into a real Home Assistant: the `config`
  variable in markdown templates, `strptime`/`selectattr` in HA's sandbox, the conditional
  card hiding a gauge on `unknown` and a missing pack entity, and the heading card are from
  memory of the HA docs and frontend, checked here only with plain Jinja; a top-level
  `solarseed_ids` key in a dashboard is believed harmless (the raw editor keeps unknown
  keys). The forecast uses mean load and the plan the load quantile plus margin, so "covered,
  2 % above the floor" can sit beside "looks short, a top-up starts before 17:00"; the
  Next-peak card says so in small print. Plan Summary is a text sensor that changes with
  the numbers in it (a recorder row every few minutes, as the Learned Plan already does).
  Look at: paste the file into a new dashboard on the box (edit nothing if the gauge is the
  AC500's; the pack section stays hidden unless a pack is named "Pack 1"); the first card
  first: does the sentence say what the inverter is doing; the Next-peak gauge on a weekday
  evening and its absence on Saturday; the 7-day table against the daily messages; the
  history graph after a few days; that no card shows "Entity not available" or a template
  error. Taste: Dan's reaction verbatim into REVIEW.md section 3.
  Review (2026-11-24, go after small fixes, made): checked f443a46 and 7b48ec8 against
  930954d. Read `outlook.py`, the dashboard file, `test_dashboard.py` and the runtime,
  sensor, health and docs diffs whole; viewed `docs/dashboard.png`. 653 passed, 7 skipped;
  690 with voluptuous and jinja2; strings.json equals en.json; `const.py` and
  `manifest.json` agree; the diff is ASCII; `p4_replay_compare.py` gives identical stdout
  (45 lines, 83 events) P3 against P4; the non-finite fix matches the coordinator's
  `isfinite` readers and the test feeds nan, inf, -inf, empty and unknown through the
  real tick. Walked: a mid-peak shortfall (the "tops up before peak" line shows only in
  mid-peak, since `shortfall_kwh` is set there alone), a weekend, Thanksgiving, classic in
  control, a graded day with no grid readings but frozen data (graded Poor with 0.0 kWh and
  $0.00, as the daily message already says it; a health question for the data review, not
  the card's). Fixed (one commit, `P4 review:`): the pack section's condition had only
  `state_not: unavailable`, and the frontend's `checkStateCondition` reads a missing entity
  as `unknown`, so an install with no packs showed an empty chart; now both states are
  excluded (also hides a configured pack before its first run-down). The mode tile said
  "Inverter mode asked for" under classic, when the Learned Plan is a shadow; it is now a
  conditional pair on the planner select. The gauge's fixed green at 15 contradicted "not
  covered" with a floor above 15 (the option runs to 50); the colour bands and needle are
  gone, the card beside says covered or not. "Graded at 21:10" became "ten minutes after
  peak end" (the scoring is tariff-derived). A record without `cost_usd` or
  `grid_peak_kwh` showed "$0.00" and "0.0 kWh"; now a dash, and the total counts only days
  that have one. The history graph is titled the running forecast and the small print says
  the table holds the mid-peak-start value. Tests for each with the frontend's condition
  rules; the drawing script follows the file (missing entity reads unknown, no needle or
  bands) and the picture is redrawn. 657 passed, 8 skipped; 695 fully enabled. Not
  verified: any card in a real Home Assistant frontend (no HA on this machine, no browser
  in this session; the picture is a Pillow imitation and says so). Believed from the
  frontend source, not seen: `config.ids` in markdown templates, unknown top-level and
  card keys kept on save (the markdown card's visual editor may fall back to YAML for the
  `ids` key, cosmetic), `<small>` and tables in the markdown card, `strptime` and
  `selectattr(..., 'number')` in HA's sandbox. Owner taste inspection pending. Nothing in
  0.9.2 needs to reach the box before P5.
- 2026-11-24, P5 build. Plan: the first-time flow gains a "Learned planner sensors" screen
  (gauge, load, grid, PV, tomorrow's forecast, each optional and checked to exist); load and
  grid together write `planner: learned` into the new entry, one without the other is
  refused, neither writes `classic`; an absent key still reads classic, so existing entries
  are untouched. The first-time schedule screen becomes Tariff: hours (peak end by 23),
  weekdays, the three prices and the holiday preset, checked by `options.check_tariff`.
  Every field of every form gets a description saying what to pick and what empty does, a
  test holds both string files to it. A setup check (`setup_check.py`) every 10 minutes
  once HA is running: configured sensors that do not exist, the learned planner in control
  without load or grid, a forecast without Solcast's hourly detail, and events the planner
  fires that no automation listens to (`hass.bus.async_listeners()`); each is a Home
  Assistant repair issue plus one log line when it appears or changes, cleared when fixed;
  no notifications. Blueprints: `source_url` to each file, `min_version`, descriptions
  that say which planner state each event means and the AC500 values. Classic marked legacy
  in the forms, README and how-it-works; README installation for a stranger (HA 2024.11+,
  Solcast only, two-price caveat, the analysis tool's own prices); `hacs.json` to
  2024.11.0. `git rm` the three tracked Zone.Identifier files. 0.9.3. Leave out: a second
  forecast adapter, making the battery kWh sensor optional, an "unavailable for long"
  check (false alarms at night), P6's README rewrite. Seen working by tests with HA mocked
  (flow, setup check, setup with sensors missing), YAML checks of the blueprints against
  HA's blueprint schema as read from the core source, and the replay (runtime untouched,
  expected identical). Pulse: 657 passed, 8 skipped; 695 with voluptuous and jinja2; no
  token on this machine (no `analysis/.ha_token.json`), box not checked.
  Built: as planned, on `chunk-P5` (2851170), on P4 with its review (2e1eaa8). 694 passed,
  9 skipped (the new flow file needs voluptuous, like the old one); 754 passed, none skipped,
  with `analysis/p2_pydeps`. Replay (`p4_replay_compare.py`, learned in control, P3 baseline,
  which the P4 review found identical to P4): IDENTICAL, 45 lines, 83 events; the runtime
  and planner are untouched. strings.json equals en.json; the diff adds no non-ASCII line.
  First-time flow: four screens (Battery and solar forecast; Learned planner sensors;
  Tariff; Notifications). `first_planner` writes `learned` with load and grid, `classic`
  otherwise, into the new entry's data; no migration, absent key still classic (a test).
  Tariff screen: hours, Weekdays only, three prices, holiday preset (Custom left to the
  options: it needs rules), calculation hours; `check_tariff` with the preset's own rules
  so a preset is not turned Custom; stores only the screen's keys (no rules text, no empty
  off-peak price); peak end 24, 17-17 and mid after peak refused, falling prices refused with
  `{prices_detail}`, a two-price plan accepted. Strings: every field of all ten forms has a
  label and description in both files; optional ones say what empty does, required sensors
  start "Required." (`test_first_install.py` builds each form and checks both files). Classic
  fields say "(classic planner, legacy)" in the first-time flow; the planner select and
  options already did. Setup check: three issues (`missing_sensors`,
  `forecast_without_detail`, `no_automations`), each a repair issue `<key>_<entry_id>` plus
  one WARNING line, updated on change, deleted with one INFO line when fixed, stale ones
  cleared on the first run after start, deleted with the entry; judged only when
  `hass.state` is running; `@callback` so it runs on the loop; a raise is logged once and
  never reaches setup (tests run the real `async_setup_entry` with every sensor missing and
  with the timer failing). Blueprints: `source_url` was the repository root, so a re-import
  would have fetched the README page; now each file's URL, matching the README links (a
  test). Found while writing them: the learned planner also holds before its night charge
  starts, not only after; the hold blueprint says so. README: what you need (HA 2024.11,
  Solcast only, three windows, two-price caveat, one inverter family), the four screens,
  repairs, the blueprints with the AC500 values and what each mode is for, classic as legacy,
  the analysis tool's own prices. `hacs.json` 2024.11.0. Three Zone.Identifier files removed
  (all one blob: a Windows download marker carrying a local download path).
  Skipped: the battery kWh sensor stays required even for a learned-only install (the
  classic shadow and the gauge fallback read it; a template of percent times capacity is
  the README's advice); a sensor that exists but stays unavailable for hours is not a setup
  issue (false alarms on idle nights; the staleness check and the planners' missing-reading
  paths cover it); a second forecast adapter (the form says Solcast plainly); the dashboard
  paste check (no browser, no box).
  Unsure: none of this has been seen in a Home Assistant UI. From memory of the core source,
  not re-read this session (downloading the `homeassistant` wheel to read it was refused by
  this session's permissions): the event trigger registers through `hass.bus.async_listen`,
  so `hass.bus.async_listeners()` counts enabled automations per event type (the REST
  `/api/events` view reads the same counts, so the reviewer can check this read-only on the
  box); the blueprint importer turns `github.com/.../blob/...` into the raw URL and the
  schema allows `homeassistant: min_version`; `ir.async_create_issue` keywords; the frontend
  rendering a placeholder's "- " lines as a list in the repair dialog; an optional number
  selector with an empty suggested value; `description_placeholders` in config-flow error
  text (as in the Tariff section since 0.9.1). hassfest on the new `issues` and
  `config.step.learned` strings runs only in CI.
  Look at: (1) on the box, read-only, `/api/events` lists `solarseed_peak_shaver_charge_start`,
  `_charge_stop` and `_preserve_start` with a listener count of at least 1 each, so 0.9.3 will
  raise no `no_automations` issue there; and Settings, System, Repairs is empty ten minutes
  after the install. (2) If Dan is willing, "add integration" on a scratch entry: four
  screens, the tomorrow forecast pre-filled, load without grid refused, peak end 24 refused,
  the entry's planner `learned`, then delete it (its issues go with it). (3) Import one
  blueprint from its README URL on a scratch HA, or at least read the three descriptions.
  (4) The README's "What you need" and setup sections as a stranger would.
  Review (2026-11-24, go after a small fix, made): checked 2851170 and 28f38d7 against
  2e1eaa8. Read `setup_check.py`, `config_flow.py`, the three blueprints, both string files
  and the three new test files whole, and the diffs of `__init__.py`, the coordinator,
  diagnostics, the README and how-it-works. 694 passed, 9 skipped; 754 with
  `analysis/p2_pydeps`, none skipped; strings.json equals en.json byte for byte; `const.py`
  and `manifest.json` say 0.9.3; the diff adds no non-ASCII line (the three deleted
  filenames carry one private-use character from before); `p4_replay_compare.py` identical,
  45 lines, 83 events, and no runtime or planner file is in the diff. Checked against the
  core source the coordinator fetched (2024.11.0 and dev), not memory: `async_create_issue`
  takes exactly the keywords used, deleting an absent issue is no error, both run under
  `verify_event_loop_thread` (the check is a `@callback` on an interval timer, so on the
  loop), a non-persistent issue is loaded inactive after a restart and the first run
  re-creates or deletes it; the blueprint schema allows exactly `homeassistant: min_version`
  as `major.minor.patch` under `blueprint:`, and the importer turns
  `github.com/<repo>/blob/<path>` into the raw URL and rejects anything else, so the file
  URLs import and the old repository-root `source_url` would not have. The forecast
  attributes the check wants are the four `_get_hourly_solar` reads. Walked: an entry with
  no planner key reads classic; load without grid refused; an all-empty second screen
  writes classic and no sensor keys; peak end 24, 17-17 and mid after peak refused, two
  prices accepted; every optional field's "empty" text against the code (notify entity
  empty sends nothing whatever the switch says; calculation hours empty is an empty list;
  PV empty counts 0 and flags no gap; gauge empty derives from kWh over capacity; tomorrow
  empty guesses, then today's). A fresh learned install lands on the untrained path the
  planner already had: the night rule charges to full and the first tick never releases a
  hold or stops a charge. A registered entity whose integration failed to load has a
  restored `unavailable` state, so only a typo or a renamed entity reads "does not exist".
  Changed (one commit, `P5 review:`): a test that a match-all bus listener and a zero count
  leave the events unheard (the module already did this); roadmap and lesson. Not verified:
  anything in a Home Assistant UI (the four screens, the optional number field, error
  placeholders, the repair dialog's markdown, a real blueprint import, the dashboard
  paste); hassfest on the new strings (CI only); the owner's listener counts (no token);
  that the automation event trigger registers one `async_listen` per event type (from
  memory of core, not re-read here). Noted, not blockers: when the bus counts cannot be
  read an open `no_automations` issue is dropped as resolved (the call is a dict
  comprehension and does not fail in practice); an integration reload that removes its
  entities for a moment can raise a missing-sensor issue for ten minutes and then clear it,
  one WARNING and one INFO; the removed download markers named a Windows user folder and
  stay in the public history (P6). 0.9.3 can ship with 0.9.1 and 0.9.2 as one release when
  Dan says; nothing in it moves the inverter differently, and the only new thing that runs
  by itself writes a repair issue and a log line.
