# T21 — Switching the model within a session in real time

Priority: P1 · Epic: C · Depends on: T04, T18, T19 · Size: M

## Problem

The mechanism partially exists: `on_context` (2983), when it encounters a new
`model` in an assistant line, calls `_resolve_window` → `_recompute_limit`; codex
writes `turn_context` with the model on every turn. What is missing:

- the signal arrives only **after** the first response from the new model; in claude,
  the `<command-name>/model</command-name>` and
  `<local-command-stdout>Set model to …</local-command-stdout>` lines appear in
  the transcript earlier and are currently ignored;
- there is no separate log line saying “model switched” — only a repeat of
  `…: a 1.0M context window …, restarting at 510k`, indistinguishable from
  flip-flop noise (T02);
- `_window_bumped`, `learned`, and the per-model override have not been tested
  for the “switched there and back” scenario;
- when switching to a model with a smaller window while the context is already
  above the new threshold, the fold must be sent immediately — this is not covered
  by a test;
- codex: `codex_cap` from sqlite remains from the previous model until the next
  `post sampling token usage` line; `interrupt_line()` is incorrect at that point.

## What to do

1. `Controller.on_model(model, source, now)` — a single entry point: compare the
   slugs; on a change, log `model switched: claude-opus-5 (1.0M, restart at 510k) →
   claude-haiku-4-5 (200k, restart at 102k) [source]`, call `_resolve_window`,
   reset `_window_bumped`, set `codex_cap=None` (until the next codex log line),
   and immediately check `_maybe_restart` on the next tick.
2. Sources: the assistant line (`message.model`), codex `turn_context` /
   `thread_settings_applied`, the claude statusline `model.id` (T20), and the claude
   `Set model to <display name>` line — through a display-name → slug table in
   profiles (T18: `display="Opus 5"`), only as an “early hint” with source
   `local command`, confirmed by the next assistant line.
3. The badge shows the percentage for the new window immediately after the switch.
4. Tests for “there and back”, “downward switch with an immediate fold”, “the
   per-model override applied after the switch”, and “codex: cap reset and
   restored”.

## Acceptance criteria

- [ ] `test_controller.py`: opus-5 (300k) → haiku-4-5 → `context_limit=102000`,
      the next tick emits `inject` fold phrases, with a `model switched` log.
- [ ] `test_controller.py`: haiku → back to opus-5 → `context_limit=510000`,
      `_window_bumped=False`, and `learned` is preserved.
- [ ] `test_controller.py`: `CR_CLAUDE_TOKENS_CLAUDE_HAIKU_4_5=90000` in the env →
      after switching to haiku, the threshold is 90,000.
- [ ] `test_controller.py`: `Set model to Haiku 4.5` line → `model switched …
      [local command]` log, 200k window; the next assistant line is opus
      (the user changed their mind) → switch back, with no fold.
- [ ] `test_codex.py`: `turn_context` with a new model → `codex_cap=None`,
      `interrupt_line() is None` until a new usage line, then restored.
- [ ] `./test/run.sh` is green; `./test/codegraph-sync.sh` has been run.

## Where in the code

`on_context` (2946–3011), `_resolve_window` (3156), `_model_tokens_override`
(3229), `codex_records` (`turn_context`, 1409; `thread_settings_applied`,
1462), `transcript_limit_records` (add parsing for `local-command-stdout`).
