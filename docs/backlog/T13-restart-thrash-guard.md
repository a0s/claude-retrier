# T13 — Restart Thrash Guard

Priority: P1 · Epic: B · Depends on: T18 · Size: M

## Problem

The threshold is a fraction of the window; the baseline context of a fresh session
(system prompt, CLAUDE.md, MCP tools, reading RESUME.md) is an absolute value. With
a 200k window and a 51% threshold (102k), the session is already at 57k after a
restart: only 45k remains usable, and the restart repeats every 30–40 minutes,
with the handoff fully reprinted and details lost. The only safeguards are
`CR_CONTEXT_MAX_CYCLES=0` (disabled) and a 600 s cooldown.

## Evidence

Log 2026-09-04: 16:22 fold (106k) → 16:26 `down to 57k` → 16:36 fold (113k)
→ 16:39 `57k` → 17:19 fold → 18:06 fold.

## What to do

1. After each successful restart, calculate `baseline = context_tokens` from the
   first line of the new session and `headroom = limit − baseline`. If `headroom <
   CR_CONTEXT_MIN_HEADROOM` (new setting, default `80k`; for a window ≤ 200k —
   `min(80k, 30% of window)`), then log `after the restart the context already sits
   at 57k of a 102k threshold; raising the threshold to 137k for this session` and
   set `context_limit = min(baseline + headroom_min, compaction_line − reserve)`,
   where `compaction_line` is the agent's own compaction point from the profile
   (T18). If there is nowhere to raise it, notify «threshold leaves 45k of working
   room; consider a larger CR_CONTEXT_PCT or a bigger window».
2. Frequency safeguard: more than `CR_CONTEXT_MAX_PER_HOUR` (new setting, default
   3) restarts in a rolling hour → disable the trigger for the rest of the session
   with a notify and badge (T14).
3. `docs/context-restart.md` («Choosing a threshold»): add a paragraph about
   baseline and headroom.

## Acceptance criteria

- [ ] `test_controller.py`: 200k window, 102k threshold, 57k after restart → log
      `raising the threshold`, new `context_limit ≥ 137k`, but no higher than
      `compaction_line − reserve`.
- [ ] `test_controller.py`: 1M window, 510k threshold, 55k after restart →
      threshold unchanged, no message.
- [ ] `test_controller.py`: 4th restart in an hour → `context_enabled=False`,
      notify, badge.
- [ ] `./test/run.sh` passes; `./test/codegraph-sync.sh` completed.

## Where in the code

`_check_resume` (3449), `_end_restart` (3500), `_recompute_limit` (3244),
`_maybe_restart` (3308), `CONTEXT_DEFAULTS` (2400), bash defaults (373–377).
