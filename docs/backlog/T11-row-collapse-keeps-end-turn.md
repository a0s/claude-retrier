# T11 — Collapsing assistant rows does not lose `end_turn` or sidechain

Priority: P0 · Epic: B · Depends on: — · Size: S

## Problem

`transcript_limit_records` (1254) collapses consecutive assistant rows from a
single poll: `out[-1].update(row)` (1295). `row` always contains the
`stop_reason` and `sidechain` keys, therefore:

1. A root row with `stop_reason="end_turn"` (the end of the fold turn), followed
   in the same 2-second poll by a row with `stop_reason=None` (a streaming
   fragment of the next turn) or a sidechain row, loses `end_turn`.
   `last_stop_reason` remains `tool_use`, `_handoff_fault` → “the turn ended
   with stop_reason=tool_use”, the fold fails, aborts, and there is no unfold.
2. A root row (tokens=500k, sidechain=False) + the next sidechain row
   (tokens=20k, sidechain=True) → the merged row is marked as sidechain →
   `on_context` exits at `if rec.get("sidechain"): return` — the observation for
   this poll is lost (the next poll may not bring the root row either).

In Claude Code 2.1.273, subagent transcripts are located in
`<project>/<sessionId>/subagents/*.jsonl` (not scanned), but inline
`isSidechain` rows from older versions and streaming `stop_reason=None` rows
(observed: `cbdd7422…` contains a row with `stop_reason=None`) remain.

## What to do

1. Collapse only rows with the same `sidechain`; do not collapse sidechain rows
   with root rows.
2. When collapsing `stop_reason`: the new row overrides the old one only when
   its `stop_reason` is not `None`; `tokens`/`model` remain as they are now (the
   newest non-`None` values).
3. Tests for both orders (`end_turn` then `None`; `None` then `end_turn`).

## Acceptance criteria

- [ ] `test_transcript.py`: `[end_turn, None]` in one poll → one record with
      `stop_reason="end_turn"`.
- [ ] `test_transcript.py`: `[root 500k, sidechain 20k]` → two records; the first
      has `tokens=500000, sidechain=False`.
- [ ] `test_controller.py`: the fold turn is closed with `end_turn`, followed in
      the same batch by a streaming row without `stop_reason` — `handoff accepted`.
- [ ] `./test/run.sh` passes; `./test/codegraph-sync.sh` has been run.

## Where in the code

`transcript_limit_records` (1254–1305), `assistant_row` (1194).
