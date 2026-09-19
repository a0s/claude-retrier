# T22 — Codex: threshold semantics, reserve, and its measurement

Priority: P2 · Epic: C · Depends on: T18 · Size: M

## Problem

1. Three numbers compete for the codex threshold: `CR_CODEX_CONTEXT_PCT` (or Claude's 51%),
   `DEFAULT_CODEX_RESTART_PCT=90` (only under `CR_CONTEXT_RESTART=1`), and
   `cap − CR_CODEX_RESERVE_TOKENS` via `min()` in `trigger_limit` (3030).
   The documentation explains this over half a page—a sign that the model is
   more complex than necessary. After T18, the threshold is one number from the
   profile/settings, with `min` against `compact_at − reserve` as the only rule.
2. The threshold between turns is almost irrelevant: a codex orchestrator turn
   lasts hours, and the restart occurs only at the interrupt line (`cap − reserve`).
   Log: threshold 137k, fold at 228k and 231k. This should be documented honestly,
   and a setting should be provided to interrupt a turn if it runs longer than
   `CR_CODEX_INTERRUPT_AFTER_SEC` after crossing the threshold (default 0 = only
   at the cap − reserve line).
3. The 64k reserve was chosen based on one incident. The wrapper knows the actual
   cost of a fold turn: `tokens at handoff accepted − tokens at folding up`. It
   should log and accumulate this (`~/.claude-retrier/folds.json`: agent, cwd,
   cost, date); if the observed cost exceeds 80% of the reserve, log a
   recommendation and (optionally, `CR_CODEX_RESERVE_ADAPT=1`) automatically raise
   the reserve to `1.25 × maximum observed`.
4. `CODEX_BASELINE_TOKENS=12000` was measured on 0.154; verify it on the current
   version at execution time and leave a comment with the version.

## Acceptance criteria

- [ ] `DEFAULT_CODEX_RESTART_PCT` removed; `test_codex.py` covers: without
      settings, threshold = `profile.restart_at`; with `CR_CODEX_CONTEXT_PCT=60`,
      60% according to the status-line formula, but not above `cap − reserve`.
- [ ] Log after every codex fold: `the fold cost 31k tokens (reserve 64k)`.
- [ ] `test_codex.py`: cost of 55k with a 64k reserve → recommendation line; with
      `CR_CODEX_RESERVE_ADAPT=1` → reserve 69k in the next calculation.
- [ ] `test_codex.py`: `CR_CODEX_INTERRUPT_AFTER_SEC=600`, turn runs for 700 s after
      crossing the threshold → `interrupt`.
- [ ] `docs/codex.md` (“Context restart on codex”) shortened to the new rule.
- [ ] `./test/run.sh` green; `./test/codegraph-sync.sh` executed.

## Where in the code

`DEFAULT_CODEX_RESTART_PCT` (754), `CFG codex_*` (804–813), `agent_cfg` (1901),
`interrupt_line`/`trigger_limit`/`_note_cap` (3018–3048), `_maybe_interrupt`
(3080), `_maybe_restart` (3308), `_check_handoff` (3382), `CODEX_BASELINE_TOKENS`
(1890).
