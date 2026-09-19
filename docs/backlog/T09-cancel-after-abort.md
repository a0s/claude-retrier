# T09 — Cancel phrase after abort of a delivered fold

Priority: P0 · Epic: B · Depends on: T06 · Size: S

## Problem

`_abort_restart` (3511) “leaves the session exactly as it is”. But if the
fold phrase was delivered, the session is already **not** “as it was”: the model
has been told “Wrap up now. Do not start new work”. After such an abort, an
autonomous session (an orchestrator with agents) sits with empty input until a
human arrives—the very thing the wrapper exists for has been lost.

Scenarios for an abort after a delivered fold: the file was not completed before
the timeout; `stop_reason=max_tokens`; codex compacted the context itself, but
the handoff did not go through; `handoff_attempts` were exhausted.

## What to do

1. New setting `CR_CANCEL_MSG` (and per-agent `CR_CLAUDE_CANCEL_MSG` /
   `CR_CODEX_CANCEL_MSG`), default: `The context restart was cancelled — the
   handoff is not needed now. Continue with what you were doing before it was
   requested.` Substitution of `{file}` is allowed.
2. When `_abort_restart` sees `at in (HANDOFF_SENT, HANDOFF_OK)` and
   `handoff_echoed=True` (T06), it returns `("inject", cancel_text, dismiss)`
   instead of `("notify", …)`—through the same gates
   (`_blocked_by_human`, `_session_busy`), that is, through the new short-lived
   `CANCEL_PENDING` state, from which `_tick_restart` sends the phrase and
   completes the restart. `inject_note()` → `restart cancelled; asking the
   session to carry on`.
3. Cooldown after such an abort is the same as after any abort
   (`CR_CONTEXT_COOLDOWN_SEC`).
4. Documentation: `docs/context-restart.md` (“When nothing happens” /
   “restart aborted at handoff_sent”) and `docs/configuration.md`.

## Acceptance criteria

- [ ] `test_controller.py`: fold delivered (echo), file did not appear before
      the timeout → after the abort, the next tick yields `inject` with the
      cancel text; the log contains `restart aborted at handoff_sent` and
      `asking the session to carry on`.
- [ ] `test_controller.py`: fold **not** delivered (no echo, T06) → cancel is
      not sent.
- [ ] `test_controller.py`: abort in `CLEARED`/`RESUME_SENT` does not send
      cancel (T08 applies there).
- [ ] `test_codex.py`: codex compacted the context itself, the handoff is
      invalid → abort + cancel phrase.
- [ ] `--cr-help` shows the `CR_CANCEL_MSG` default.
- [ ] `./test/run.sh` passes; `./test/codegraph-sync.sh` has been run.

## Where in the code

`_abort_restart` (3511), `_lost_the_race` (3050), `_check_handoff` (3382),
`inject_note` (3145), `AGENT_MESSAGE_KEYS` (1896), bash defaults (358–372),
variable exports (4405–4408).
