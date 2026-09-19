# T17 — Per-agent command and skill syntax defaults

Priority: P1 · Epic: D · Depends on: T15, T16 · Size: S

## Problem

Per-agent overrides for `CR_CLAUDE_*`/`CR_CODEX_*` for `HANDOFF_MSG`,
`CLEAR_CMD`, and `RESUME_MSG` already exist (commit 1a5e9bc), but the
**defaults** are shared: `CR_CLEAR_CMD=/clear`, and the skill invocation syntax
is not parameterized anywhere. For claude, a skill is `/name`; for codex, it is
`$name`; the reset command is `/clear` for claude, and `/new` (historically) or
`/clear` (0.154: «clear the terminal and start a new chat») for codex. A user
who keeps a single `CR_RESUME_MSG` for both agents gets a non-working unfold on
one of them.

## What to do

1. Separate defaults in bash and `CONTEXT_DEFAULTS`:
   `CR_CLAUDE_CLEAR_CMD=/clear`, `CR_CODEX_CLEAR_CMD=` — based on the result of
   T15 (`/new` or `/clear`; choose the one that works on
   the oldest supported version of codex). `CR_CLEAR_CMD` remains a shared
   override.
2. The `{skill:NAME}` placeholder in
   `CR_HANDOFF_MSG`/`CR_RESUME_MSG`/`CR_CANCEL_MSG` expands to `/NAME` for claude
   and `$NAME` for codex. Example from the README:
   `CR_RESUME_MSG='{skill:supervisor} continue from `{file}`'`.
3. `--cr-help` prints defaults for both agents; `agent_cfg` (1901) applies
   `{skill:…}` after selecting the agent.
4. `docs/context-restart.md` («Writing your own phrases») and
   `docs/configuration.md`: a table of «what differs between agents».

## Acceptance criteria

- [x] `test_codex.py`: without variables, `clear_cmd` for codex equals the
      selected default, while for claude it equals `/clear`; `CR_CLEAR_CMD=/foo`
      overrides both; `CR_CODEX_CLEAR_CMD` affects codex only.
      → `test_codex_clear_cmd_default_matches_claudes` pins the first; the
      override rules were already covered by
      `test_handoff_msg_and_clear_cmd_follow_the_same_rule`.
- [x] `test_controller.py`/`test_codex.py`: `{skill:supervisor}` → `/supervisor`
      and `$supervisor`, respectively, in `resume_text` and `handoff_msg`.
      → `TestSkillPlaceholder` (5 tests) in `test_codex.py`, plus
      `test_a_skill_placeholder_reaches_codex_as_a_dollar_prefix` proving it
      end to end through bash + pty.
- [x] `--cr-help` contains both default lines.
- [x] `./test/run.sh` passes; `./test/codegraph-sync.sh` has been run.

## Decision on the codex default (item 1), after T15

**`CR_CODEX_CLEAR_CMD` keeps `/clear`, the same as claude — the defaults do
not diverge.** T15 drove both on live codex-cli 0.155.1 and found `/clear`
and `/new` byte-for-byte equivalent there: same single-Enter recipe, same
`Token usage: …` / `To continue this session, run codex resume …` banner,
same "no new rollout until the first message of the new chat". With nothing
to choose between them on behaviour, `/clear` wins on every other count — it
is what the shared `CR_CLEAR_CMD` already is, what claude uses, and what
codex's own hint text describes ("clear the terminal and start a new chat").

So no new bash default or `CONTEXT_DEFAULTS` entry was added: introducing a
second constant holding the identical string would configure nothing while
adding a knob to keep in sync. What the task actually needed — proof that
the shared default is safe on codex, and a regression test pinning it — is
in place. `CR_CLAUDE_CLEAR_CMD`/`CR_CODEX_CLEAR_CMD` already existed as
per-agent overrides (commit 1a5e9bc) and are unchanged, so the day codex
does diverge, the override is already there and only the default moves.

The genuinely per-agent part of this task is `{skill:NAME}`, which is
implemented: `/NAME` for claude, `$NAME` for codex. T15 made the direction
non-negotiable — codex silently drops an unrecognized `/NAME` (inline
"Unrecognized command", nothing sent, no rollout entry, which is exactly the
2026-09-15 incident's symptom), while `$NAME` is always delivered as text.

## Where in the code

`SKILL_PLACEHOLDER`/`expand_skill` (claude-retrier.sh 2439–2452),
`agent_cfg` (2455–2477, the `{skill:…}` loop at 2468–2470),
`--cr-help` header text (49–57), `test_codex.py`'s `TestSkillPlaceholder`.
