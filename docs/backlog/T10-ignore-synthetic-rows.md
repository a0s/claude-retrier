# T10 — Ignore `<synthetic>` and zero-usage rows

Priority: P0 · Epic: B · Depends on: — · Size: S

## Problem

Claude Code writes assistant rows with `"model": "<synthetic>"` and usage
`{0,0,0}` (for example, “No response requested” or an interrupted request). `usage_tokens`
(1940) returns `0` for them (not `None`), and `on_context`:

- sets `context_tokens = 0` → the badge and threshold are reset;
- sets `context_model = "<synthetic>"` → `_resolve_window` → “unfamiliar
  model slug” → the window is `None`, and the trigger is cleared until the next real row;
- in the `RESUME_SENT` state, `_context_fell()` (3443) sees `0 <= before*0.5` →
  a false `context restarted: 550k down to 0`; the restart completes without a real
  `/clear` verification effect.

## Evidence

`~/.claude/projects/-Users-a0s-a0s-github-voxik/4a2c66dc….jsonl` and
`b5d84050….jsonl`: one row each with `model=<synthetic> sidechain=False
stop_reason=stop_sequence`, with zero usage.

## What to do

1. `assistant_row` (1194): if `model` starts with `<` (`<synthetic>`) —
   `tokens=None`, `model=None`, `stop_reason=None` (the row is “live”, but says nothing).
2. `usage_tokens`: a sum of `0` when all three counters are `0` → `None`.
3. `on_context`: a `model` starting with `<` does not count as a model change.
4. `_context_fell`: require `context_tokens > 0`.

## Acceptance criteria

- [ ] `test_transcript.py`: a `<synthetic>` row with zero usage yields
      `tokens=None`, `model=None`.
- [ ] `test_controller.py`: in `RESUME_SENT`, a row with `tokens=0` does not complete
      the restart; the next real row with 55k completes it.
- [ ] `test_controller.py`: `<synthetic>` between two `claude-opus-5` rows does not
      call `_resolve_window` or write a window-related line to the log.
- [ ] `./test/run.sh` is green; `./test/codegraph-sync.sh` has been run.

## Where in the code

`assistant_row` (1194), `usage_tokens` (1940), `Controller.on_context` (2946),
`_context_fell` (3443).
