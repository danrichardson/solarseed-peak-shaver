# Reviewing work on Solarseed Peak Shaver

**To run it, say:** `review the last chunk per REVIEW.md` (or name it: `review P2 per
REVIEW.md`). It is for the strongest model in a fresh session, and it is the other half of
[ROADMAP.md](ROADMAP.md): a builder does a chunk, a reviewer checks it, Dan says next.

Keep this file under 200 lines. It holds what a reviewer cannot get from the code. Status
does not belong here.

## 1. What a review is

A builder's report is a claim. This integration runs a house battery with nobody watching,
and its bugs so far have all been true-at-the-desk and wrong on the box: the code did what
the builder thought the sensors would do. Your job is to look where the builder did not,
with the readings the box really produces, fix what is small, and correct what comes next.

It is not a second build, a redesign or a critique document. One short session.

## 2. Procedure

1. **Read** `AGENTS.md`, the "RESUME HERE" section of `docs/HANDOFF.md`, this file, then
   the chunk in ROADMAP.md and its Log entry. Treat each sentence of the report as a claim.
2. **Form your own read first** from primary sources: `git log main..chunk-<id>`,
   `git diff main..chunk-<id> --stat`, then the files that matter, whole. Compare with the
   report afterwards.
3. **Run the checks** in section 6 that apply. Always run `python -m pytest -q` yourself,
   and `git show --stat` on every commit of the branch.
4. **Try the thing that must not work:** a sensor unavailable at setup, a key absent from
   the options, a restart in the middle of a hold, the day before and after a holiday, an
   idle system, a full bank. Write the missing test if it is small.
5. **Ask what happens if nobody looks for a month.** Which notification repeats daily?
   Which state can stick?
6. **Judge** against section 3 with section 4 as the ruler.
7. **Decide:** go; go after a small fix (make it, section 7); or send back.
8. **Push it forward.** Edit the chunks still to come with what you learned.
9. **Record:** a `Review:` line in the chunk's Log entry (verdict, what you checked, what
   you changed). One line in section 9 if it will still be true next month.
10. **Notify Dan once,** verdict first (`~/src/notify.sh --event=ready-for-review`). End
    with the sentence to paste next, alone in a code block: `ship <version>` when a release
    is ready, else the build sentence. Rewrite the line at the top of ROADMAP.md. Stop.

## 3. The standard: what Dan wants, in his words

Add his reactions here verbatim, with the date. Dictated text is quoted as it arrived.

**Pace and scope** (2026-11-23):
> "It's Monday. You agents think everything takes so freaking long. ... We could totally
> have that done by two hours from now."

> "I'd like to get this thing done and feature complete if we can"

> "Let's make this a public release."

> "if we have to iterate on brainstorms for what some of the details are, let's do it"

A review that sends work back over something a default would have settled is a failure by
this standard. Fix it or note it; send back only what is unsafe or wrong.

**Settings** (2026-11-23): "do we need to put any kind of GUI or editor on the parameters"

**From the record, not verbatim** (dates as logged in `docs/HANDOFF.md`):

- 2026-11-16: success is grid energy through the inverter in mid-peak and peak, and what it
  costs. Load outside the inverter is by design and not counted.
- 2026-11-16: a forecast update refreshes the plan and never starts a charge by itself.
  Never charge in peak. A night charge is planned to finish at mid-peak start; a mid-peak
  top-up to finish by peak start.
- 2026-11-22: he had stopped reading the old daily grade because it graded a plan nobody
  followed. A message he cannot trust is worse than none.
- 2026-11-15: rewiring is off the table.
- Standing: the box is production. Read-only without his word. He clicks install in HACS.

## 4. Anchors: what good and bad look like here

**Good**

- The daily message as specified: "Good - peak on battery, ended at 12 % (predicted 9 %),
  $0.00 at peak prices. Last 7 weekdays: 6 good, 1 fair." One or two lines, ASCII, the
  outcome first, a number he can check against the meter.
- 0.8.1 at restart: the log says `Classic calculation skipped: solar forecast entity ...
  has no data`, the inverter mode does not move, setup succeeds. A missing reading produced
  one plain line and no action.
- The learned planner calling the shortfall on each of three shadow days before it was
  given control. Shadow first, then switch.

**Bad**

- 0.8.0 at restart: "[CHARGE 4.1 kWh] Battery: 0.0 kWh", `charge_start` fired, stopped two
  seconds later. A 0 that meant "unknown" was believed.
- A healthy full bank overnight reported as `battery_data_stale` for 261 minutes. It would
  have graded the night Poor and sent a review notice.
- `Inverter did not follow the hold command after 3 attempts` on 2026-11-23, when the
  inverter was doing exactly what a full battery does. An ERROR and a Poor grade for
  nothing.
- A fix first proposed for the idle bug that was limited to the mid-peak and peak windows.
  The recorded readings showed the same 0 W in mid-peak; it would not have worked.

The pattern: bad output here is nearly always a confident statement about a state the
sensors could not actually tell apart. "Cannot tell" (None, skip, no message) is a good
answer.

## 5. Where the truth is

- **Tests:** `python -m pytest -q` from the repo root. 402 passed, 1 skipped on 2026-11-23.
  Home Assistant is mocked in `tests/ha_mocks.py`; a test that passes only because the mock
  is kinder than the box proves nothing, so read the mock when a test touches states.
- **The diff:** `git diff main..chunk-<id>`; `git log origin/main..main` before any ship.
- **Replay:** `analysis/scripts/shadow_replay.py` runs the real runtime over pulled data;
  `replay_cost.py` prices a policy. Local and gitignored; on a machine without `analysis/`
  say so instead of skipping silently.
- **The box, read-only,** when `analysis/.ha_token.json` exists (else ask Dan for a
  temporary login; never store the password). In Git Bash set `MSYS_NO_PATHCONV=1`:
  - `python analysis/scripts/ha.py rest /api/states/sensor.solarseed_peak_shaver_health`
  - `python analysis/scripts/ha.py rest /api/states/sensor.solarseed_peak_shaver_learned_plan`
  - `python analysis/scripts/ha.py rest /api/states/select.ac500_ups_mode`
  - `python analysis/scripts/ha.py rest /api/diagnostics/config_entry/<entry_id>`
  - `update.solarseed_peak_shaver_update` for the installed version; `system_log/list`
    over the WebSocket for errors; the logbook for what the inverter mode really did.
- **Release state:** `gh release list`, `gh run list --limit 3`.
- **What the owner sees:** the notification text. Build one from `health.daily_message`
  with real-looking numbers and read it as a lock-screen line.

## 6. How work here goes wrong, and the check that catches it

| What happened | Check |
|---|---|
| A sensor read 0 for "unknown" for 2 s at startup and a charge started | Every new reading goes through the missing-is-not-zero path; a test feeds unavailable, unknown, empty and non-finite |
| Setup failed on a missing sensor, which would have kept the planner in control from starting | A test runs the real `async_setup_entry` with that entity unavailable |
| "Readings change every few seconds" was assumed; an idle system sat exactly still for hours | For any rule about sensor behaviour, find the recorded stretch that shows it; if there is none, the Log must say it is an assumption |
| A fix was scoped to the wrong window | Replay the fix against the readings that produced the bug, written into the test |
| Verification called a full battery in hold "not followed" | Walk the boundary states for any threshold: full, floor, idle, PV above load, gauge missing |
| The setup refresh skipped the weekday test that the timers had | One function for one question; `grep -n "weekday()" custom_components/` |
| A restart flipped the inverter mode | After a start the first tick may start a charge and nothing else; test a restart in hold, in charge and on battery |
| New options are absent from stored options until the form is submitted; options save wholesale | Read every new key with a default; test with the key absent; saving one section must not drop the others |
| Events after the 21:10 scoring fell in no graded day | For anything counted per day, ask where an event at 23:00 goes |
| A day that was not comparable (circuits off the inverter, a holiday) was graded and learned from | Ask what a strange day does to the 14-day load history and the 7-day health window |
| `git add docs` staged the owner's untracked files | `git show --stat` on every commit; files staged by name |
| A non-ASCII dash in a notification title | `git diff main..HEAD \| grep -nP "[^\x00-\x7F]"` must print nothing |
| Version bumped in one file | `const.py` and `manifest.json` agree (`tests/test_integration_structure.py` checks) |
| Household detail in a public repo | Read the diff of every doc for times of the owner's actions, IPs, names, addresses |

## 7. What the reviewer may do

- **Yes:** a missing test; a wrong threshold or boundary; a string; a doc correction; an
  absent default; a commit on the chunk's branch for any of these, prefixed `P<n> review:`.
- **No:** a second design; new features; refactors the chunk did not need; merging,
  pushing, releasing or touching the box (Dan's word, as for the builder).
- If the fix is more than about an hour or changes the approach, send back: put the reason
  and the default you would take into the chunk text, mark the row "Back", stop.

## 8. The reviewer's own traps

- Agreeing with the report because the tests are green. The tests were written by the same
  mind that wrote the bug.
- Reviewing the code and not the behaviour over a whole day. Walk one weekday, one Friday
  night, one holiday and one restart through the change by hand.
- Wanting it more general. This is one house and, at 1.0, a few strangers. The recoverable
  waste is about $10 a month.
- Sending back for taste on a plumbing chunk, or passing a taste chunk without quoting Dan.
- Re-deriving what the findings already settled (`docs/HANDOFF.md`, "Facts learned this
  week - do not re-derive").
- Holding the pace up. Dan's standard for a chunk is hours, not days.

## 9. Lessons

One line per review, newest last.

- 2026-11-24 (P2): a "skipped" in the pytest line is a question. `test_config_flow.py` had
  skipped in CI since 0.8.1 for a missing package; the chunk that rewrote the options flow
  would have shipped with its form tests never run there. Run the suite with the extra
  package (`analysis/p2_pydeps`) and read the skip count, not just the pass count.
- 2026-11-24 (P3): read the chunk's "Done when" against the Log's Skipped and Unsure lines
  one by one. Two honest "unsure" notes (old hours until midnight on a season night; weekend
  hours cannot be typed) were a boundary bug and a missed criterion, each under an hour to
  fix. Writing a limitation down does not make it a decision; and any "today's" default
  that runs after peak end is planning tomorrow, so walk it with tomorrow's hours.
