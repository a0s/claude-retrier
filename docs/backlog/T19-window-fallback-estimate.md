# T19 — Fallback window estimate for an unknown model

Priority: P1 · Epic: C · Depends on: T18 · Size: M

## Problem

Unknown slugs currently use a network lookup (claude only; codex — “the rollout
will say”) → otherwise the trigger is disabled and the badge is `window?`. An
early version guessed 200k and folded a 1M session at 12% — hence the caution.
But “disabled” is also a failure: a new model appears exactly when the table is
out of date, and a session without a restart dies from its own compaction. The
user is asking for an **estimate with self-correction**, not a refusal.

## Evidence

Log 2026-09-11/12: `claude-fable-5-1: a 200k context window (an unfamiliar model
slug), restarting at 102k` → folded at 118k (59%) in a 1M session.

## What to do

1. Window source order (a single `resolve_window()` function instead of branches
   in `_resolve_window`, 3156): `CR_CONTEXT_WINDOW` → reported by the agent
   (rollout `model_context_window`; claude statusline from T20) → claude env
   limits (`CLAUDE_CODE_MAX_CONTEXT_TOKENS`, `CLAUDE_CODE_DISABLE_1M_CONTEXT`) →
   profile (T18, including family: `claude-fable-5-1` → `claude-fable-5`) →
   cache/network (`WindowLookup`, as now) → **estimate**:
   - claude: an unknown version of a known family (`claude-opus-6`) → the
     window of the newest known model in the same family; an unknown family
     `claude-*` → the modal window of the newest generation in the table
     (currently 1M);
   - codex: `~/.codex/models_cache.json` (slug → `context_window ×
     effective_context_window_percent`), then the cache's modal window;
   - otherwise `SMALL_WINDOW` (200k) — but only as a **provisional** estimate.
   Each estimate carries an `estimated=True` flag and a source; log:
   `claude-opus-6: no published window; estimating 1.0M from claude-opus-5 (same
   family) — restarting at 510k until something says otherwise`; badge
   `~51%`/`~est` (T14).
2. Upward self-correction remains (`_window_bumped`, 3000): when `tokens >
   window` — not just “assuming 1.0M”, but the next step (200k → 1M →
   `max_context_window` codex 872k → +50%).
3. Downward self-correction: the agent compacted the context itself at N tokens
   (claude — a `type=system, subtype=compact_boundary` line with
   `compactMetadata.preTokens`; codex — `compacted`) → effective window ≤ N:
   `window = N / 0.92`, log `claude compacted at 190k: the effective window is
   ~200k, not the 1.0M assumed; restarting at 102k from now on`, threshold
   recalculated. This also fixes the case “the table says 1M, but the session
   has 200k” (T20), albeit after the fact.
4. An estimate confirmed by observation (the session passed 60% of the estimated
   window without compaction) loses its `~`.

## Acceptance criteria

- [ ] `test_models.py`: `claude-opus-6` → 1M, source “same family”;
      `claude-newfamily-1` → modal window; `gpt-7-nova` with codex cache → from
      cache; with nothing → 200k with `estimated=True`.
- [ ] `test_controller.py`: 200k estimate, usage 250k → window raised, log; usage
      1.1M → next step.
- [ ] `test_controller.py`: `compact_boundary` with `preTokens=190000` at an
      assumed 1M → window ≈ 206k, `context_limit` recalculated, log.
- [ ] `test_transcript.py`: `compact_boundary` line parses into a record
      `kind="alive", quiet=True, compacted=True, pre_tokens=N`.
- [ ] Badge shows `~` for an estimate (test in `test_badge.py`).
- [ ] `docs/context-restart.md` (“The context window”): new order and an
      explicit statement that “an estimate is an estimate, here is how it
      corrects itself”.
- [ ] `./test/run.sh` passes; `./test/codegraph-sync.sh` executed.

## Where in the code

`_resolve_window` (3156), `_needs_window` (3207), `on_window_learned` (3212),
`on_context` — bump (3000), `transcript_limit_records` (1254, add
`compact_boundary`), `codex_records` (`compacted`, 1415), `WindowLookup` (2094),
`badge_warn`/`badge_context` (3121–3143).
