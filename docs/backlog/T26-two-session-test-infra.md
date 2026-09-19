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

- [ ] `two_wrappers` is used in at least three tests (T02, T04, T05) and
      reliably (10 consecutive runs without flaking) completes in < 60 s.
- [ ] fake_claude covers all scenarios from item 1; each has a test consumer.
- [ ] After `./test/run.sh` there are no orphan processes; with an artificially
      orphaned process, `run.sh` prints `FAILURES` and its pid.
- [ ] `docs/how-it-works.md` (“Tests”) is updated.
- [ ] `./test/run.sh` is green; `./test/codegraph-sync.sh` has been run.

## Where in the code

`test/fake_claude.py`, `test/fake_codex.py`, `test/helper.py`, `test/run.sh`,
`test/test_pty.py`, `test/test_codex.py`.
