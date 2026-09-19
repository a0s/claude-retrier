# T15 — Codex: live investigation of `/clear` + `$skill`

Priority: P0 · Epic: D · Depends on: T01 · Size: M (mostly manual work)

## Problem

Codex unfold has **never** worked for the user (log: 0 `context
restarted` events for codex, 2 folds — 2 failures), although CHANGELOG 1.11.0
claims testing on live codex 0.154. The difference is the user's resume phrase:
`$supervisor continue scratchpad/RESUME.md`. In codex, `$` opens a skill
selection popup (like `/` opens the command list), while `schedule_injection`
(4006) knows only about `/`.

Incident 2026-09-15 05:23: `/clear` at 05:23:07, resume at 05:23:10, two
retries after 60 and 120 s — none created user lines; there is no new
user-rollout in `~/.codex/sessions` at all. In other words, Enter was
“swallowed” all three times, not only during the first seconds after `/clear`.

## What to do

Run this on live codex-cli 0.154 (use a cheap model/prompt; account for the
`live-codex-test-orphans` memory: after kill, the pty driver leaves the
supervisor running — kill the entire process group) and **record the results in
this file**:

1. Enter `/clear` + Enter (+ a second Enter after 0.6 s): does it execute;
   what does the screen look like afterward; how long until the TUI accepts
   input; is a new rollout created immediately or only on the first message?
2. The same for `/new`.
3. Enter the text `$supervisor continue scratchpad/RESUME.md` in one
   `write()`, then Enter after 0.6 s: does the popup open; what does Enter do
   (select an item / send / insert a newline); is the message sent; what is
   recorded in the rollout (`$supervisor` + an `<skill>` line?).
4. The same with a 0.9 s pause and two Enters (as for `/`).
5. The same when a space after `$supervisor` is entered by a separate
   `write()` after 0.3 s (does the space close the popup?).
6. Enter text beginning with `@` (file mention) and with `/prompts:`.
7. Cyrillic in the phrase: does it break codex's paste-burst detection?
8. Immediately after `/clear` (after 3 s), enter an ordinary phrase without
   `$`: does it get through?

The result should be a table “input → what happened → reliable recipe”. It is
needed for T16/T17.

## Acceptance criteria

- [ ] The “Results” section is completed for all 8 items, with the codex
      version and date.
- [ ] For each blank below, provide an input recipe that **three times in a
      row** resulted in a message being sent: an ordinary phrase after
      `/clear`; `$skill …`; `/command`.
- [ ] State whether `CR_CLEAR_SETTLE_SEC` is needed and what its default
      should be (T08).
- [ ] If a bug is found in the wrapper itself and is not covered by T16, file
      a task.

## Results

Performed 2026-09-19 against **codex-cli 0.155.1** (installed via
`~/.local/bin/codex`; the backlog's 0.154 is no longer installed anywhere on
this machine). Driver: `test/fixtures/capture-codex-input-grammar.py`, model
`gpt-5.6-luna` (cheapest available slug) at `model_reasoning_effort=low`,
`-a never -s read-only`, one fresh session per scenario in a throwaway
project dir. Screens read back through the shared `Screen` emulator
(`test/screen.py`); rollouts checked under `~/.codex/sessions`.

**Headline finding: none of the incident's failure modes reproduce on
0.155.1.** `$name` does **not** open a popup at all — it is a *model-level*
convention (`AGENTS.md`/system prompt: "if the user names a skill with
`$SkillName` or plain text, use it"), not a TUI feature the composer
special-cases. The only character the composer itself treats specially is a
leading `/` that resolves to exactly one known command (shown as a
description hint under the input, e.g. `/clear  clear the terminal and start
a new chat`); one `Enter` accepts it immediately. Everything else — `$name`,
`@file`, plain text, Cyrillic — is delivered as plain text with a single
`Enter` ~0.6s later, **as long as it arrives in one `write()`** (a real
human typing character-by-character might trigger a live `@file`
autocomplete list that a burst write never triggers — not tested here, out
of scope: the wrapper never types character-by-character). This means the
2026-09-15 incident's true cause was almost certainly **not** an input-popup
problem at all — it predates T02–T06 (session/transcript binding), which is
the far more likely explanation and is already fixed.

One genuine, reproducible hazard *was* found and is new information for
T16/T17: **an unrecognized `/word` is silently dropped.** Codex prints
`Unrecognized command '/word'. Type "/" for a list of supported commands.`
inline, leaves the text sitting in the composer, and never sends it as a
message — confirmed for both `/prompts:list` and a literal `/supervisor
continue scratchpad/RESUME.md` (0 new rollout files both times). This is
exactly the incident's symptom ("none created user lines"). It means a
custom phrase must **never** rely on a bare `/name` unless `name` is one of
codex's own commands — which is precisely why T17's `{skill:NAME}` must
expand to `$NAME` for codex, never `/NAME`: `$NAME` is always delivered as
text (proven below); `/NAME` is dropped outright unless codex itself defines
that command.

| Input | What happened | Recipe |
|---|---|---|
| `/clear` | Executes on a single `Enter` — verified directly, by a run that sent exactly one and nothing after it: the `Token usage: …` / `To continue this session, run codex resume, then select <title> (<thread-id>)` banner was already on screen, with an empty, ready composer. The composer shows the `/clear` description hint the instant the full token is typed, so there is nothing to navigate. **No new rollout file is created** until the first message of the new chat — the old one becomes resumable via `codex resume`. A second `Enter` afterwards lands on the now-empty box and sends nothing (same as claude), so the existing two-Enter default is harmless. 3/3 clean runs. | type `/clear`, wait ≥0.6s, `Enter` once (a second `Enter` is harmless, which is what keeps the existing `CR_SLASH_ENTER=2` default safe) |
| `/new` | The same rendered outcome as `/clear`: same `Token usage: …` / `To continue this session, run codex resume …` banner, same emptied composer, same "no new rollout until the next message". Compared on the decoded screen and the rollout set, not byte-for-byte on the raw stream. No functional difference found between the two on 0.155.1. | same as `/clear` |
| `$skill …` + `Enter` after 0.6s | No popup. Delivered as plain text, the exact string `$supervisor continue scratchpad/RESUME.md` present in the rollout's `input_text`; the turn starts at once ("I'll inspect the repository's resume notes…"). 3/3 clean runs. | type the full phrase in one `write()`, wait 0.6s, `Enter` once |
| `$skill …` + 0.9s + 2×`Enter` | Same as above. The rollout holds exactly **one** user message and no empty one, so the second `Enter` submitted nothing — no difference from the 0.6s/1×Enter recipe. | not needed; the plain-text recipe above already works |
| `$skill` + separate space (0.3s later) | Same as above — splitting the write across two `os.write()` calls made no observable difference; still no popup, still delivered whole, still one user message in the rollout. | not needed |
| `@file …` | No popup. `@README.md summarize this file in 3 words` is in the rollout verbatim, `@` included, and the model opens the turn by saying it will read `README.md` (the run was cut short at that point — the mention was clearly received; the finished answer was not waited for, and is not what this scenario tests). | type the full phrase in one `write()`, wait 0.9s, `Enter` once |
| `/prompts:list` (a real family, unknown member) | Rejected inline: `Unrecognized command '/prompts:list'. Type "/" for a list of supported commands.` Composer keeps the literal text; **0 new rollout files** — never sent as a message either. | n/a — this is the hazard to avoid, not a recipe |
| bare `/name` that is not a codex command (tested with `/supervisor continue scratchpad/RESUME.md`) | Same rejection as above: `Unrecognized command '/supervisor'…`, 0 new rollout files. This is the exact shape of the 2026-09-15 incident's symptom. | n/a — never use a bare `/name` for a custom phrase on codex |
| Cyrillic (`Ответь одним словом — привет!`) | No paste-burst/encoding issue of any kind; exact UTF-8 text round-trips through the rollout, model replies in kind (`Привет!`). | same plain-text recipe as any other phrase |
| plain phrase 3s after `/clear` | Delivered and answered normally — **a second, brand-new rollout file appears** at this point (the first message of the new chat), confirming `/clear` itself never created one. 3/3 clean runs. | wait ≥3s after `/clear`'s `Enter`s settle, then send normally |

### Acceptance criteria

- `CR_CLEAR_SETTLE_SEC` is **not needed** for codex on 0.155.1: `/clear` takes
  effect on the same `Enter` that types it (no multi-second settle window
  observed before the composer is ready again), matching claude's own
  behavior that the existing `clear_settle` default (5.0s, used for `/clear`
  → handoff-file-exists polling, not per-keystroke) already assumes.
- No new bug filed against the wrapper itself: the one real hazard found
  (unrecognized `/word` is dropped) is fully covered by T17's
  `{skill:NAME}` → `$NAME` design for codex — see T17.
- Recipes reproduced 3/3 for: `/clear` (table above), `$skill …` (table
  above), and the post-`/clear` plain phrase (table above).
