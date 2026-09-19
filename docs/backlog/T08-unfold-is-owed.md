# T08 — Unfold is mandatory after `/clear`

Priority: P0 · Epic: B · Depends on: T04, T06 · Size: M

## Problem

After `/clear`, the context has already been destroyed, and the only meaningful
action is to type the resume phrase. Currently, in the `CLEARED` and
`RESUME_SENT` states, three silent outcomes are possible without unfold:

1. `CLEARED`: `_held()` holds the step (a foreign transcript is “still writing”,
   see T04; or a person is typing) longer than `CR_HANDOFF_TIMEOUT_SEC` →
   `_tick_restart` (3271) aborts with “cleared took longer than 900s”. The
   session remains empty forever.
2. `RESUME_SENT`: two reprints without echo → `_abort_restart(permanent=True)`
   (3474) — the feature is disabled, and the session remains empty.
3. `_send_resume` runs after `CR_STEP_GAP_SEC` = 3 s following `/clear`, without
   waiting for confirmation that `/clear` has executed and the TUI is ready to
   accept input; this was observed on codex.

## Evidence

Log: 2026-09-15 05:23:07 `/clear` → 05:23:10 `unfolding` → 05:24:10, 05:25:10
`left no trace` → 05:26:10 `restart aborted at resume_sent … not attempting
another this session`. In `~/.codex/sessions`, there is no new user-rollout
after 03:23Z: the phrase was never sent.

## What to do

1. **Confirmation of `/clear`.** Add a new `CLEAR_SENT` state between
   `HANDOFF_OK` and `CLEARED`. Transition to `CLEARED` on a positive signal:
   claude — rebind to a new `sessionId`/file (T02), or a new file with the user
   line `<command-name>/clear</command-name>`; codex — a new rollout (when it
   appears) **or** the screen: output has remained quiet for ≥
   `CR_CLEAR_SETTLE_SEC` (new setting, default 5 s) after `/clear`. If there is
   no confirmation within `CR_VERIFY_SEC`, reprint `/clear` once (a second
   `/clear` in an empty session is harmless), logging `the clear command left no
   trace; sending it again`.
2. **The timeout must not abort in `CLEARED`.** Instead of `_abort_restart`,
   continue waiting for human gates (`_blocked_by_human`), but **not** the “session
   busy” gate from the old transcript (after rebinding, it is no longer ours
   anyway). Every 5 minutes, call
   `notify("context cleared; unfold is waiting for: <why>")`; badge
   `◆ cr unfold?` (T14).
3. **In `RESUME_SENT` without echo**, reprint not 2 but up to
   `CR_RESUME_ATTEMPTS` (new setting, default 5) times with increasing intervals
   (60 s, 120, 240…), and after exhausting them use state `UNFOLD_FAILED`, not
   `permanent`: show the red badge `◆ cr unfold failed`, notify every 5 minutes
   “read `<file>` yourself: the resume phrase never reached the session”, and
   log it. The restart trigger is disabled (`context_off`), but the unfold debt
   remains visible until human input (any keystroke clears it).
4. `_context_fell()` remains the success criterion; with T10 it cannot produce
   a false success.

## Acceptance criteria

- [ ] `test_controller.py`: after `/clear` without confirmation for 60 s → a
      second `/clear`; with confirmation (a new `path` via `bind_transcript`) →
      `CLEARED` → resume.
- [ ] `test_controller.py`: `CLEARED` remains for 1000 s (a person is typing) —
      no abort occurs, notify repeats, and resume is sent as soon as the gate
      opens.
- [ ] `test_controller.py`: 5 reprints without echo → `UNFOLD_FAILED`,
      `unfold failed` badge, `context_enabled=False`, `notify` action repeats at
      an interval; `on_user_bytes` resets the state to `None`.
- [ ] `test_codex.py`: on codex after `/clear`, resume is not sent before
      `CR_CLEAR_SETTLE_SEC` of silence on the screen.
- [ ] `test_pty.py`: fake_claude accepts `/clear` only 4 s after Enter — the
      restart still finishes as `context restarted`.
- [ ] `docs/context-restart.md`: «Why `/clear` is the last thing it will do»
      supplemented with the paragraph “and the unfold is owed after it”.
- [ ] `./test/run.sh` passes; `./test/codegraph-sync.sh` has been run.

## Where in the code

`_tick_restart` (3258), `_send_clear` (3361), `_send_resume` (3373),
`_check_resume` (3449), `_abort_restart` (3511), `RESTART_LABELS` (2394),
`Badge.frame` (3580), `main()` handling of `notify` (4203).
