# T14 — Failures visible in the badge

Priority: P1 · Epic: B · Depends on: T08 · Size: S

## Problem

`notify()` (3980) prints one dim line, which the TUI immediately redraws
(“transient by design”). Persistent failures — `restart aborted`, `switched off
for this session`, `unfold failed` — go unseen, and the user discovers an empty
session hours later. The badge only knows `window?`.

## What to do

1. `Controller.badge_warn()` (3136) returns, in priority order:
   `unfold failed` (T08, red, until the first keystroke), `unfold?` (unfold
   has been waiting for the gate > 60 s), `restart off` (`context_off=True`, until
   the end of the session, dim red), `window?` (as now), `~est` — estimated window
   (T19).
2. For the `unfold failed` and `restart off` states, repeat `notify` every
   `CR_NOTIFY_REPEAT_SEC` (new, default 300) until the user presses a key.
3. `docs/how-it-works.md` (“A sign of life”): a table of all badge words.

## Acceptance criteria

- [ ] `test_badge.py`: frames for each state from item 1 with the expected text and
      SGR.
- [ ] `test_controller.py`: after a permanent abort, `badge_warn() == "restart off"`
      through the end of the session; after `UNFOLD_FAILED` — `"unfold failed"`,
      reset by `on_user_bytes`.
- [ ] `test_pty.py`: the screen emulator shows `◆ cr restart off` after
      the abort.
- [ ] `./test/run.sh` passes; `./test/codegraph-sync.sh` has been run.

## Where in the code

`badge_warn` (3136), `Badge.frame` (3580), `main()` — `notify` and `badge.paint`
(3980, 4215).
