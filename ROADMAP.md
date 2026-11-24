# Solarseed Peak Shaver roadmap: one chunk at a time, to 1.0

**Next, paste this** (review session, the strongest model):

```
review the last chunk per REVIEW.md
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
| P3 | Tariff as data | 0.9.1 | care | yes | |
| P4 | The dashboard | 0.9.2 | taste | yes | |
| P5 | A stranger can install it | 0.9.3 | care, taste | yes | |
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
tariff key the timers read at start belongs in `RELOAD_KEYS` and `setup_signature`.

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
sensors and their attributes); `docs/ROADMAP.md` item 6.

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
`diagnostics.py` for what is redacted.

**Defaults:** solar forecast stays Solcast-shaped (`detailedHourly` / `detailedForecast`);
say so plainly in the form instead of building a second forecast adapter.

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
