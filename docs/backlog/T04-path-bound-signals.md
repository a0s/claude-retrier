# T04 — Controller: all signals only from the bound transcript

Priority: P0 · Epic: A · Depends on: T01, T02 · Size: M

## Problem

Currently, only `on_context`/`on_turn` are filtered by path (main, 4128, 4143).
The other signals come from **any** project file:

- `on_echo` / `on_resume_echo` (4118–4121): a foreign session whose wrapper
  printed `continue` or the same resume phrase “confirms” our submission.
- `on_alive(now, "transcript")` (4140): a foreign assistant line clears our
  limit wait. With two sessions, this is a real scenario: the Opus limit is
  weekly, a neighboring Sonnet session responds → our wait is reset, while the
  limit line has already been read and will not repeat → session A remains dead.
- `note_growth` (3100) and `_session_busy` (3299) read `context_grew_at` using
  `context_path`, which was unstable before T02.
- When `path` changes, `on_context` (2955) zeros `context_tokens`, `turn_open`,
  and `codex_cap`, but **not** `context_model`, `context_window_hint`,
  `counted_by_log`, `last_stop_reason`, or `_window_bumped`.

## What to do

1. Introduce a single transcript-switching point in `Controller`:
   `bind_transcript(path, why, now)`. It resets **all** per-transcript state
   (`context_tokens`, `context_model`? — no: the model remains until the next
   assistant line, but `context_window_hint`, `turn_open`, `codex_cap`,
   `counted_by_log`, `last_stop_reason`, `context_grew_at`, and `_window_bumped`
   are reset) and logs one line. `on_context` no longer changes `context_path`
   itself: a line with a foreign `path` is ignored.
2. In `main()`, `on_echo`, `on_resume_echo`, `on_alive("transcript")`, and
   `on_turn_done` are called only when `rec["path"] == watcher.current`.
   Exception: `kind == "limit"` is an account limit and is read from any file
   (as now), but a wait assigned by a foreign file is marked
   `limit_source="neighbour"` and is cleared only by “our” alive lines or by
   the screen.
3. Clearing the wait in `on_alive` requires `path == context_path`; in the
   “foreign session responds” test, the wait remains.
4. Remove the “newest among those that grew” rule from
   `TranscriptWatcher._pick_current` when binding (T02/T03) is available; keep
   it as a fallback with a log on every switch (`transcript switched: a → b
   (fallback heuristic)`) so that such switches are visible.

## Acceptance criteria

- [ ] `test_controller.py`: a foreign `continue` echo does not transition
      `VERIFY → IDLE`; our own does.
- [ ] `test_controller.py`: a foreign assistant line during `WAITING` does not
      clear the wait; our own does (after `ALIVE_GRACE`).
- [ ] `test_controller.py`: an `alive` line with a foreign `path` does not
      change `context_tokens`/`context_model`/`last_stop_reason`.
- [ ] `test_controller.py`: `bind_transcript` resets the listed fields; after
      binding, the first usage line from the new file produces the correct
      `context_pct()`.
- [ ] Log: exactly one line per binding/rebinding; no
      `… context window …, restarting at …` line without an actual model or
      window change (currently they are printed on every flip-flop).
- [ ] `./test/run.sh` is green; `./test/codegraph-sync.sh` has been run.

## Where in the code

`Controller.on_context` (2946), `on_echo` (2631), `on_resume_echo` (3112),
`on_alive` (2649), `note_growth` (3100), `_session_busy` (3299),
`TranscriptWatcher._pick_current` (1816), `main()` record loop (4117–4157).
