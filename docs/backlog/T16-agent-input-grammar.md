# T16 — Per-agent input grammar (`/`, `$`, `@`)

Priority: P0 · Epic: D · Depends on: T15 · Size: M

## Problem

`schedule_injection` (4006) distinguishes only “starts with `/`” (the
`CR_SLASH_GAP_SEC` pause, `CR_SLASH_ENTER` Enters) and “everything else” (Enter
after 0.6 s). Different characters open popups in codex and claude:

| character | claude | codex |
|---|---|---|
| `/` at the beginning | command list | command list |
| `$` at the beginning of a word | — | skill list |
| `@` at the beginning of a word | file mention | file mention |
| `#` at the beginning | memory | — |

In codex, a phrase starting with `$skill` is not sent (T15). The user should
not need to know this: the wrapper must be able to type any phrase that a
person could type by hand.

## What to do

1. Introduce `AGENT_INPUT = {"claude": dict(popup_prefixes="/@#", …), "codex":
   dict(popup_prefixes="/$@", …)}` and `typing_plan(agent, text)` — a pure
   function returning a list of `(delay, bytes)` according to the recipes from
   T15. Expected form (clarify against T15): for a popup token, type the token,
   pause for `CR_POPUP_GAP_SEC` (default 0.9), type the remainder (a space
   closes the popup), pause for 0.6, then Enter; for a pure command (`/clear`
   with no arguments), behave as now (two Enters).
2. `schedule_injection` uses `typing_plan`. `CR_SLASH_*` remain as aliases.
3. Echo verification (T06/T08) is a safety net: if the plan did not work, the
   phrase is retyped; after the second failure, the full input plan is written
   to the log.
4. `test/fake_codex.py`: emulate the popup for `$`: while the `$…` token is not
   closed with a space, Enter selects an item (appends a space) and does not
   send; `test/fake_claude.py`: do the same for `/` (already present?) and `@`.

## Acceptance criteria

- [x] Unit tests for `typing_plan`: `/clear`, `/skill arg`, `$skill arg`, `@file
      text`, `plain text`, `text in Russian` — for both agents, with the
      expected sequences fixed in the tests.
      → `test/test_input_grammar.py`, 7 tests.
- [x] `test_codex.py` (pty, ~~fake_codex with popup~~): the resume phrase
      `$supervisor continue {file}` is delivered on the first attempt; the
      rollout contains a user string with the exact text.
      → `test_a_skill_placeholder_reaches_codex_as_a_dollar_prefix`, which does
      it through the stronger T17 route: one *shared* `CR_RESUME_MSG` with
      `{skill:supervisor}` in it must arrive at codex as `$supervisor …`.
      The "with popup" half is dropped — see the deviation note below.
- [x] `test_pty.py`: `@README.md summarize` is delivered to fake_claude.
      → `test_an_at_file_mention_resume_phrase_is_delivered_whole`.
- [x] Live run according to the T15 recipe (three consecutive times) — record
      the result in this file. → done under T15 itself (3/3 for `$skill …`,
      `/clear`, and the post-`/clear` plain phrase); driver kept as
      `test/fixtures/capture-codex-input-grammar.py` for re-running when
      upstream changes.
- [x] `docs/context-restart.md` (“Slash commands and `CR_SLASH_ENTER`”) is
      rewritten as “Commands, skills and mentions”. `docs/codex.md`'s
      "Skills and file mentions in codex" was corrected too — it had recorded
      the pre-investigation guess (`$`/`@` open popups) as established fact.
- [x] `./test/run.sh` is green; `./test/codegraph-sync.sh` has been run.

## Deviation from "What to do", and why

Items 1 and 4 above were written before T15 ran, on the assumption that codex
opens a `$`-skill popup the way it opens a `/`-command list. **Live driving
of codex-cli 0.155.1 disproved that** (see T15's results): `$name` is a
model-level convention, not a composer feature, and `@file` is likewise plain
text once the whole phrase arrives in one `write()` — which is the only way
this wrapper ever sends it. So:

- `AGENT_INPUT` ships as `{"claude": {"popup_prefixes": "/"}, "codex":
  {"popup_prefixes": "/"}}`, not the guessed `"/@#"`/`"/$@"`. It stays a
  per-agent table (rather than collapsing to a constant) purely as the place
  a future release's popup behaviour would go.
- There is no `CR_POPUP_GAP_SEC`: with no popup to settle, a second knob
  would configure nothing. `CR_SLASH_*` keep their existing meaning for the
  one prefix that does open something.
- Item 4 (teach `fake_codex.py`/`fake_claude.py` to emulate a `$`/`@` popup)
  is **skipped deliberately**: a fake that swallows Enter for `$…` would
  assert behaviour the real binary does not have, and would then have to be
  un-taught. What is tested instead is the real property — the phrase is
  delivered whole, on the first attempt, with `$`/`@` intact.
- Item 3 (retype-on-failure as a safety net) needed no new code: T06's echo
  verification already retypes an unconfirmed phrase and T08 already escalates
  after `CR_RESUME_ATTEMPTS`, both independent of which plan produced the
  keystrokes.

The one real hazard T15 *did* find — codex silently drops an unrecognized
`/word`, never sending it even as text — is handled in T17 (`{skill:NAME}`
never expands to `/NAME` for codex) and documented in both
`docs/codex.md` and `docs/context-restart.md`.

## Where in the code

`AGENT_INPUT` (agent-retrier.sh 2410–2413), `typing_plan` (2416–2436),
`schedule_injection` (6536–6552), bash defaults `CR_SLASH_*` (505–507),
`test/test_input_grammar.py`.
