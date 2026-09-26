# T18 — Model profile table (window + threshold) for both agents

Priority: P1 · Epic: C · Depends on: T01 · Size: M

## Problem

Model knowledge is currently scattered: `CONTEXT_WINDOWS` (1864) contains only
windows and only for claude; the threshold is one global percentage
(`DEFAULT_RESTART_PCT=51`, `DEFAULT_CODEX_RESTART_PCT=90` + `min()` with a
reserve); the agent's own compaction point is in comments (`244.8k`, `258.4k`)
and in `codex_cap` from sqlite. There is no single place stating for each model:
what its window is, where the agent will compact the context itself, and where
the wrapper should restart. There is no command to inspect this.

## What to do

1. One structure `MODEL_PROFILES = {"claude": {...}, "codex": {...}}`, with each
   entry being `Profile(window, restart_at, compact_at=None, since="2026-09-18",
   note="")`, all in tokens. Initial contents (update with current data at the
   time of implementation):

   claude (window / restart_at / compact_at ≈ 0.95·window if not known more precisely):
   - `claude-opus-5`, `claude-sonnet-5`, `claude-fable-5`, `claude-mythos-5`,
     `claude-opus-4-8`, `claude-opus-4-7`, `claude-opus-4-6`,
     `claude-sonnet-4-6`: 1 000 000 / 510 000 / ~967 000 (Claude Code
     documentation: auto-compact Sonnet 5 "~967K").
   - `claude-opus-4-5`, `claude-opus-4-1`, `claude-sonnet-4-5`,
     `claude-haiku-4-5`: 200 000 / 102 000 / ~190 000.

   codex (from `~/.codex/models_cache.json`, codex 0.154; window is effective,
   `context_window × effective_context_window_percent`):
   - `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.5`:
     258 400 / 194 400 (= cap − 64k) / 258 400 (hard cap; soft 244 800 with
     `CR_CODEX_HOLD_COMPACT=0`); `max_context_window` 872 000 for sol/terra/
     luna/astra — if the user raises `model_context_window` in
     `config.toml`, the rollout will report it, and the profile is only a fallback.
2. `model_window()` reads from the profiles; the new `model_restart_at(agent, slug,
   window)` provides the threshold. Threshold resolution order (document in code):
   `CR_<AGENT>_TOKENS_<SLUG>` → `CR_CONTEXT_TOKENS`/`CR_CODEX_CONTEXT_TOKENS` →
   `CR_CONTEXT_PCT`/`CR_CODEX_CONTEXT_PCT` × window → the profile's `restart_at`
   (when restart is enabled through `CR_CONTEXT_RESTART=1`) → T19 fallback. Always
   use `min(…, compact_at − reserve)`.
3. `--cr-models` in bash: print a table (agent, slug, window, restart_at,
   compact_at, source) taking environment variables into account, so a person
   can check what the wrapper thinks about their model without starting a session.
4. Test that "each profile is self-consistent": `restart_at < compact_at ≤ window`,
   `restart_at ≥ 0.3·window`.
5. `docs/context-restart.md` ("The context window", "Choosing a threshold"):
   profile table and resolution order.

## Acceptance criteria

- [ ] `test_models.py`: self-consistency is checked for every `MODEL_PROFILES`
      entry (item 4).
- [ ] `test_models.py`: threshold resolution order has one test for each
      stage, including `min(…, compact_at − reserve)`.
- [ ] `test_codex.py`: with no variables and `CR_CONTEXT_RESTART=1`, the rollout
      reports 258 400 → threshold 194 400; with `model_context_window=872000` in
      the rollout → the profile threshold is not applied, but
      `CR_CODEX_CONTEXT_PCT`/reserve is (describe the expected number in the test).
- [ ] `./agent-retrier.sh --cr-models` prints a table; a test in
      `test_degrade.py` checks for `claude-opus-5` and `gpt-5.6-sol`.
- [ ] All existing `test_models.py` tests are green (`model_window` behavior
      for point releases is preserved).
- [ ] `./test/run.sh` is green; `./test/codegraph-sync.sh` has been run.

## Where in the code

`CONTEXT_WINDOWS`/`SMALL_WINDOW`/`BIG_WINDOW` (1864–1881), `DEFAULT_RESTART_PCT`
(744), `DEFAULT_CODEX_RESTART_PCT` (754), `model_window` (1967),
`_recompute_limit` (3244), `trigger_limit` (3030), bash `case` for `--cr-*`
(391, 4301).
