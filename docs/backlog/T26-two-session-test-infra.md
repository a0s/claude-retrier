# T26 — Test infrastructure: two sessions in one project

Priority: P1 · Epic: E · Depends on: T01 · Size: M

## Problem

No test runs two wrappers over the same project-dir, so the class of
“foreign session” bugs (T02, T04, T05) slipped past 429 green tests.
`test_transcript.py::test_it_stays_with_the_file_it_picked_while_that_file_grows`
only checks the case where both files grow during one poll. Live codex runs
leave orphans (project memory `live-codex-test-orphans`).

## What to do

1. `test/fake_claude.py`: (a) writes `$CLAUDE_CONFIG_DIR/sessions/<pid>.json` with
   `sessionId`, `cwd`, `status`; updates `status` at turn boundaries and
   `sessionId` after `/clear`; removes it on exit; (b) scenario mode
   (`FAKE_SCRIPT=…`): “grow by N tokens every M seconds”, “lose the first
   fold phrase”, “accept `/clear` after K seconds”, “write a `<synthetic>`
   line”; (c) streaming lines with `stop_reason=null`.
2. `test/fake_codex.py`: popup for `$` and `/` (T16), lazy creation of a rollout after
   `/clear`/`/new`, subagent rollouts on the same day, a rollout on an old day for
   `resume`.
3. `test/helper.py`: `two_wrappers(project_dir, cfg_a, cfg_b)` — starts two
   wrappers in one directory and returns both logs, filtered by pid
   (T01), and both transcripts; timeouts and guaranteed process-group
   termination (`os.killpg`) in `addCleanup`.
4. `test/run.sh --live-codex` (optional): the T15 checklist as a script, with
   explicit confirmation before starting (uses quota) and orphan cleanup.
5. Orphan check at the end of `run.sh`: if processes with `CR_CLAUDE_ARGV` in
   their environment are still alive after the run — `FAILURES` with their list.

## Acceptance criteria

- [x] `two_wrappers` is used in at least three tests (T02, T04, T05) and
      reliably (10 consecutive runs without flaking) completes in < 60 s.
- [x] fake_claude covers all scenarios from item 1; each has a test consumer.
- [x] After `./test/run.sh` there are no orphan processes; with an artificially
      orphaned process, `run.sh` prints `FAILURES` and its pid.
- [x] `docs/how-it-works.md` (“Tests”) is updated.
- [x] `./test/run.sh` is green; `./test/codegraph-sync.sh` has been run.

## Where in the code

`test/fake_claude.py`, `test/fake_codex.py`, `test/helper.py`, `test/run.sh`,
`test/live_codex.py`, `test/test_live_codex.py`, `test/test_pty.py`,
`test/test_codex.py`.

## Results

Item 4 ended up as `test/live_codex.py`, reached through `./test/run.sh
--live-codex` (`run.sh` only execs it; it is never in the default file list).

It is the T15 table turned into eleven assertions rather than a printed
transcript — that transcript was already produced once by
`test/fixtures/capture-codex-input-grammar.py`, and re-reading it by eye
every release is not a test. Two live sessions, a handful of three-word
turns on the cheapest model (`CR_LIVE_MODEL`, default `gpt-5.6-luna`):
`/clear` accepted by the shipped Enters and creating no rollout of its own,
the plain phrase after it getting through and being what finally opens the
new rollout, `$skill …`/`@file …`/Cyrillic delivered verbatim into the
rollout, and an unrecognized `/name` rejected inline and never sent.

Two choices worth recording. First, codex runs **under the wrapper**
(`claude-retrier.sh --agent codex`, `CR_CLAUDE_BIN` pointed at the real
binary), not bare as in the T15 capture: what needs re-verifying each release
is that the supervisor's pty relay leaves those recipes intact, and the run
also asserts its own `[cr <pid> …] start: … (agent: codex)` line (T01).
Second, the keystrokes come from the shipped `typing_plan()` itself, so the
script cannot pass against a recipe the wrapper no longer sends —
`test/test_input_grammar.py` pins the same function without a pty, and this
is the live half of that pair.

Gates, since this one costs money: preflight resolves `codex`
(`CR_LIVE_CODEX_BIN` or `PATH`) and runs `codex login status` — missing is a
skip (exit 0, the documented no-codex case), logged out is exit 3 — then
confirmation, an interactive `y/N` naming the spend or `CR_LIVE_CONFIRM=1`
for CI, and a refusal (exit 2) when there is neither, a pipe never counting
as consent. Cleanup is not optional: every session is registered before it
starts and killed process-group by process-group from a `finally` and from
`SIGINT`/`SIGTERM` (the wrapper `setsid()`s the agent, so `killpg` on the
wrapper's own pid alone would leave codex running — memory
`live-codex-test-orphans`), and the run finishes by calling
`check-orphans.py` whatever else happened.

The gates, the rollout parsing and the check accounting are unit-tested in
`test/test_live_codex.py`, which does run in the default suite.
