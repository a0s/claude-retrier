# T12 — Handoff verification latch

Priority: P1 · Epic: B · Depends on: T06, T11 · Size: S

## Problem

`_check_handoff` (3382) currently requires **all at once**: the file is valid,
`last_stop_reason == "end_turn"`, and the transcript has been quiet for
`CR_ROOT_IDLE_SEC` (20 s). In a session with background activity (agent
notifications wake the model, `notify_idle`, hooks), a new turn may begin after
the fold turn's `end_turn`: `last_stop_reason` becomes `tool_use`, the transcript
grows — and the valid handoff is never accepted: after 900 s, abort with «no
usable handoff».

## What to do

1. Latch: when both “the file is valid” and “an `end_turn` line arrived on the
   attached transcript after `handoff_sent_at`” are true, record
   `handoff_verified_at = now` and transition to `HANDOFF_OK`, **without** waiting
   for quiet. Quiet/the “session busy” gate remains a condition for sending
   `/clear` (`_send_clear` → `_held`), as it is now.
2. If the file changes after the latch (mtime/size), verify it again; if the
   marker is gone, return to `HANDOFF_SENT` with a log entry.
3. `last_stop_reason`: store not only the latest value, but also
   `end_turn_seen_at` (the time of the `end_turn` line on the attached transcript
   after `handoff_sent_at`), so subsequent `tool_use` events do not erase the
   fact.

## Acceptance criteria

- [ ] `test_controller.py`: the file is valid, `end_turn` occurs, then
      `tool_use` lines and transcript growth continue for 5 minutes → state is
      `HANDOFF_OK` (log `handoff accepted`), and `/clear` is sent as soon as the
      transcript becomes quiet.
- [ ] `test_controller.py`: after the latch, the file is rewritten without the
      marker → return to `HANDOFF_SENT`, with log `the handoff file changed after
      it was accepted`.
- [ ] Existing `TestHandoffChecks`/similar tests remain green.
- [ ] `./test/run.sh` is green; `./test/codegraph-sync.sh` has been run.

## Where in the code

`_check_handoff` (3382), `_handoff_fault` (3417), `on_context` — assignment of
`last_stop_reason` (2978), `_send_clear` (3361).
