# T01 — Wrapper Identifier in Every Log Line

Priority: P0 · Epic: A · Depends on: — · Size: S

## Problem

All wrappers on the machine write to the same `~/.claude-retrier/log`, and a line
does not say which one wrote it. When two sessions live in one project, the log
is unreadable: `folding up` / `handoff accepted` / `exit: 0` from different
processes are mixed together, making it impossible to reconstruct the chronology
of a single restart.

## Evidence

`~/.claude-retrier/log`, 2026-09-17 22:45–22:51: two `folding up` entries with
different nonce values, then `handoff accepted … HANDOFF-8b21b153`, `handoff attempt 1/2
failed … HANDOFF-081d06b8`, `exit: 0`, `start:`, `handoff accepted …
HANDOFF-b11a5bfc` — three processes, none labeled.

## What to do

1. In `Logger.__call__` (claude-retrier.sh:3809), add a tag after the timestamp:
   `[2026-09-17 22:45:36] [cr 48213 claude] …`, where `48213` is the supervisor's
   pid (`os.getpid()`), and `claude`/`codex` is the agent name. Set the tag once
   (`Logger(path, tag=...)` or `log.tag = ...` immediately after `pick_agent`).
2. The `start:` line additionally prints `cwd` and, when known, the associated
   transcript (after T02 — `session <sessionId>`).
3. The `exit:` line prints the same tag (automatically by then) and the session
   duration (`after 2h13m`, via `human_left`).
4. `docs/troubleshooting.md`: add one paragraph explaining how to filter the log
   by pid (`grep 'cr 48213'`).

## Acceptance criteria

- [ ] Every line written through `Logger` has the form
      `[YYYY-MM-DD HH:MM:SS] [cr <pid> <agent>] <msg>`; the tests
      `test_controller.py`/`test_pty.py` that parse the log are updated and green.
- [ ] New test in `test/test_pty.py`: two simultaneous wrapper launches
      (fake_claude) in one `CR_LOG` → the `start:` lines of the two processes are
      distinguishable by pid, and `grep` for one pid gives a coherent
      `start → … → exit` sequence.
- [ ] `start:` contains `cwd=<path>`.
- [ ] `exit:` contains the duration.
- [ ] `./test/run.sh` is green; `./test/codegraph-sync.sh` has been run.

## Where in the code

`Logger` (claude-retrier.sh:3800), `main()` — `start:` (3870) and
`exit:` (4280), `pick_agent` (1728).
