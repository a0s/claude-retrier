# claude-retrier Plans.md

Created on 2026-09-18 from `docs/backlog/` (T01–T26, 1.11.0 audit + 4
unreleased commits; T27 was added the same day after a separate investigation
of subagent-tree rendering). Task numbering equals backlog IDs (`T01`…`T27`);
full Problem/Evidence/What to do/AC/Where in code are in the corresponding
`docs/backlog/T##-*.md`; the DoD here is a compact, verifiable version. Spec:
`docs/spec/00-project-spec.md`.

Spec delta:
- path: docs/spec/00-project-spec.md
- change: created a root spec with 4 invariant blocks (identity / model profile / restart machine G1–G8 / limits); previously this model existed only in `docs/backlog/README.md` as an informal audit.
- why: 22 of 26 tasks change user-visible behavior (session ownership, restart timing, badge contents), and without a fixed contract implementation could diverge from the audit model.

Team validation: `team_validation_mode: manual-pass` (the Task agent is available but was not run: the original audit already provides log evidence for each task; repeating discovery review with five personas would be redundant). The perspectives below are a one-pass self-check, not parallel agents.

- **Product**: addresses user-visible bugs (folding with another session's numbers, dead session after abort, restarts every 30–40 minutes) — high Product Fit.
- **Architecture**: introduces one transcript-switch point (`bind_transcript`) and one model-profile structure, reducing the state surface; T02→T04→T06 is the correct order (identity, path-bound signals, then echo verification).
- **Security**: reads no secrets; T24 requires external sending (git push, gh release, homebrew tap), covered by the confirmation event below.
- **QA**: each T-task carries AC with unit/pty tests; `test/run.sh` is the floor; T26 (two-session test infrastructure) intentionally runs in parallel with Phase 1 (see Depends).
- **Skeptic**: T15 and T20 contain behavior not tested live (codex `$skill` popup, `--settings` merge/replace); both are `unknown` in the spec and should not block Phase 1/2.

formatter_baseline: missing
formatter_baseline_evidence: no `.shellcheckrc`/`pyproject.toml`/lint step in `.github/workflows/test.yml`; only `./test/run.sh`.
formatter_baseline_action: skip_with_reason — bash+Python-heredoc in one file; backlog tasks do not change code style, and lint infrastructure was not requested.

## Event requiring confirmation (pre-approval, T24)

- event: `external-send` — `git push --tags`, `gh release create`, updating the formula in adjacent `homebrew-claude-retrier` (new tarball URL + sha256)
  reason: release procedure requires publishing a tag/release and synchronized formula (a tag without a formula is not a release)
  scope: Phase 8 / T24

---

## Phase 0: Subagent observability (Epic F)

Purpose: a `harness-loop` session spends quota on a subagent tree that the TUI does not report by model, effort, or cost (upstream marked the request “not planned”). The wrapper is the only observer able to show this. It was placed first at the user's request and does not technically depend on Phase 1.

| Task | Content | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T29 | `[lane:gate]` `[tdd:required]` Overlay on the expanded agent panel; live recapture (T27 method) and row recognition. Investigation disproved the original hypothesis: `←` opens the cross-session roster, not subagents; the reproducible method is `/tasks`, rows `<label> (running\|done) · <Model>` | All AC green: new `agents-panel-2.1.273.bin`; `find_panel_agent_rows` finds every row without `Local agents (N)`; `CR_AGENTS_OVERLAY=1` labels the model through `test_pty.py`; `screen.scrolled == 0`; T27/T29 `←`/`↓` questions closed; `./test/run.sh` green | T27 | cc:完了 [ccee293] |
| T28 | `[lane:gate]` `[tdd:required]` Move `Badge` to the primitive shared with `AgentOverlay` (`DECSC→CUP→SGR→text→DECRC`) and use one per-frame occupied-row registry | All AC green; expected bytes unchanged; shared primitive and registry proven by tests; `Screen` default behavior resolved; `./test/run.sh` green | T27 | cc:done [b83d0d1] |
| T27 | `[lane:gate]` `[tdd:required]` `Screen` emulator from `test/screen.py`, grid `find_agent_rows`, `SubagentRegistry` (`subagents/agent-*.{jsonl,meta.json}`), and `AgentOverlay` drawing `sonnet-5/?` at the row edge after each `ESC[?2026l` frame | Model only from `agent-<id>.jsonl`; final column untouched; no scroll; overlay-off adds no bytes; fake scenario reproduces geometry; `--cr-help` includes four variables; tests green | - | cc:done [2ee1e58] |

## Phase 1: Session identity and signal integrity (Epic A, part B)

Purpose: remove the root cause of folding with another session's numbers and losing unfold.

| Task | Content | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T01 | `[lane:gate]` `[tdd:required]` `[cr <pid> <agent>]` on every `Logger` line; `start:`/`exit:` include cwd and duration | AC format and two-wrapper pty test pass; `./test/run.sh` green | - | cc:完了 [fe4df9d] |
| T26 | `[lane:gate]` `[tdd:required]` Two sessions in one project-dir (`fake_claude`/`fake_codex`, `helper.two_wrappers`, orphan check) | Used in 3+ tests; 10 runs under 60s; orphan produces `FAILURES`; tests green | T01 | cc:完了 [d3ea768] |
| T02 | `[lane:gate]` `[tdd:required]` Claude transcript binding via `~/.claude/sessions/<pid>.json` (`ClaudeSessionRegistry`, `TranscriptWatcher.bind`) | Unit/pty AC, live verification, and updated Caveats pass | T01, T26 | cc:完了 [5e3010d] |
| T04 | `[lane:gate]` `[tdd:required]` `bind_transcript` is the sole switch point; callbacks filter on `path == watcher.current` | Foreign signals have no effect; state resets; tests green | T01, T02 | cc:done [84ef121] |
| T05 | `[lane:gate]` `[tdd:required]` Unique handoff file per session (`{id}` or session registry with suffix) | Collision, dead-pid, and one-warning tests pass | T01 | cc:done [13e4720] |
| T10 | `[lane:gate]` `[tdd:required]` Ignore `<synthetic>`/zero-usage rows in context helpers | Synthetic gives `tokens=None,model=None`; positive context required | - | cc:done [08c9680] |
| T11 | `[lane:gate]` `[tdd:required]` Assistant-row collapsing preserves `end_turn` and separates sidechains | AC tests pass (`[end_turn, None]` and root+sidechain) | - | cc:done [277a446] |
| T06 | `[lane:gate]` `[tdd:required]` Echo verification (`watcher.expect/forget`, `on_handoff_echo`) is the sole binding confirmation and `/clear` prerequisite | Retry/abort, foreign-path rebind, and guarded `/clear` tests pass | T02, T04 | cc:done [7bb1656] |

## Phase 2: Restart-machine guarantees (Epic B)

Purpose: guarantee recovery from `CLEARED`, `RESUME_SENT` without unfold, and dead sessions after abort (G4/G5).

| Task | Content | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T08 | `[lane:gate]` `[tdd:required]` Unfold mandatory after `/clear`; `CLEAR_SENT`, safe timeout, and `CR_RESUME_ATTEMPTS` to `UNFOLD_FAILED` | Claude/Codex AC and docs pass | T04, T06 | cc:done [8e8adba] |
| T09 | `[lane:gate]` `[tdd:required]` `CR_CANCEL_MSG` after aborted delivered fold enters `CANCEL_PENDING` | Guarded injection, help text, and tests pass | T06 | cc:done [df16021] |
| T12 | `[lane:gate]` `[tdd:required]` Handoff latch `handoff_verified_at` uses file plus `end_turn`, not transcript silence | Background tools preserve latch; missing marker returns to `HANDOFF_SENT` | T06, T11 | cc:done [91f94c9] |

## Phase 3: Codex — input and agent grammar (Epic D)

Purpose: determine why Codex unfold never worked, then encode observed TUI behavior.

| Task | Content | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T15 | `[lane:gate]` `[tdd:skip:live-investigation]` Live Codex 0.154 recipes for `/clear`, `/new`, `$skill …`, `@file`, and Cyrillic | Eight results with version/date and reproducible 3× recipes; `CR_CLEAR_SETTLE_SEC` decision | T01 | cc:TODO |
| T16 | `[lane:gate]` `[tdd:required]` Per-agent `AGENT_INPUT`/`typing_plan(agent, text)` replaces binary slash logic | Unit/pty and live recipe tests pass | T15 | cc:TODO |
| T17 | `[lane:gate]` `[tdd:required]` Per-agent clear-command defaults and `{skill:NAME}` → `/NAME`/`$NAME` | AC and `--cr-help` defaults pass | T15, T16 | cc:TODO |

## Phase 4: Codex — session identity (Epic A, continuation)

Purpose: close the Codex equivalent of T02 using echo and path-bound filtering.

| Task | Content | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T03 | `[lane:gate]` `[tdd:required]` Bind Codex rollout using lock/lsof/heuristic plus echo nonce; expose old `codex resume` sessions in `paths()` | Verified section, rollout/subagent tests, docs, and test suite pass | T01, T04, T06 | cc:done [16a92e4] |

## Phase 5: Model profiles and windows (Epic C)

Purpose: one source-of-truth table for T13 headroom and T21 real-time model changes.

| Task | Content | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T18 | `[lane:gate]` `[tdd:required]` `MODEL_PROFILES` (window/restart_at/compact_at), `model_restart_at()`, `--cr-models` | Profile consistency, threshold precedence, and table tests pass | T01 | cc:done [0f90975] |
| T19 | `[lane:gate]` `[tdd:required]` Unknown-slug window fallback with correction (`resolve_window()`, `estimated=True`) | Family/modal fallback, boundary correction, and `~` badge tests pass | T18 | cc:done [76e3d05] |
| T21 | `[lane:gate]` `[tdd:required]` Real-time model changes via `Controller.on_model()` and `local-command-stdout` hint | Round-trip, shrinking-window, override, and `codex_cap` tests pass | T04, T18, T19 | cc:done [f19c35c] |
| T20 | `[lane:gate]` `[tdd:required]` Claude effective window through `--cr-statusline` proxy; cheap signals first | Settings behavior, call frequency, pty statusline, and disable switch tests pass | T18, T19 | cc:done [454193e] (`--settings` merge-vs-replace and invocation frequency remain unverified live — coded against the fail-safe assumption, see docs/backlog/T20-claude-effective-window.md "Verified") |

## Phase 6: Restart stability and failure visibility (Epic B, remainder)

Purpose: model profiles are required to calculate headroom/compaction_line correctly.

| Task | Content | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T13 | `[lane:gate]` `[tdd:required]` Raise `headroom` after restart; frequency guard `CR_CONTEXT_MAX_PER_HOUR` | 200k/1M scenarios and fourth-restart guard pass | T18 | cc:done [14f5378] |
| T14 | `[lane:gate]` `[tdd:required]` Badge failure priority via `badge_warn()`; repeat `notify` every `CR_NOTIFY_REPEAT_SEC` | Badge frames, persistent `restart off`, and keystroke reset pass | T08 | cc:done [6a7693d] |

## Phase 7: Tail work (Epic C/A remainder)

Purpose: non-blocking simplifications and passthrough dependent on model profiles.

| Task | Content | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T22 | `[lane:gate]` `[tdd:required]` Codex profile threshold `min(…, compact_at − reserve)`, fold cost log, optional reserve increase | Constant removal, cost/recommendation/adaptation, interrupt timeout, docs, and tests pass | T18 | cc:in-progress (`task/t22-codex-threshold-semantics`; the "constant removal" AC item was already done by T18 before this task started) |
| T07 | `[lane:gate]` `[tdd:required]` Direct passthrough for non-session Claude subcommands (`auth`, `mcp`, `update`, `stop`, …) | `stop`/`mcp list` avoid `start:`; wrapped commands remain wrapped | - | cc:done [bbbb81f] |

## Phase 8: Operations and release (Epic E)

Purpose: close technical debt (unrotated log, 4 unreleased commits) and update documentation after Epics A/B.

| Task | Content | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T23 | `[lane:gate]` `[tdd:required]` Concurrent-safe log rotation (`CR_LOG_MAX_BYTES`/`CR_LOG_KEEP`) | Startup rotation and below-limit tests pass | - | cc:done [2b5201c] |
| T25 | `[lane:fast]` `[tdd:skip:docs-only]` Update four docs without stale Caveats | Grep is empty; links and anchors valid | T02, T04, T05, T08, T09 | cc:done [4ed1c1d] |
| T24 | `[lane:release]` `[tdd:skip:release-prep]` CHANGELOG, `CR_VERSION`, tag, GitHub release, and Homebrew formula | Every commit/task recorded; version tests, tag, release, and formula pass (no user-machine brew install/upgrade) | completed P0 tasks | cc:done [72a3c3b, v1.12.0] |
| T26-live | `[lane:fast]` `[tdd:skip:optional-manual]` Optional `test/run.sh --live-codex` checklist with confirmation and orphan cleanup | Explicit confirmation required; quota deliberate; process groups killed afterward | T15, T26 | cc:TODO |

---

## Next step

All of Phases 1, 2, 4, 5, 6, 7, and 8 are now complete except T26-live:
T01-T14, T18-T25, T27, T28 are all merged and released as v1.12.0. Only T15
(Phase 3, blocked on a live manual investigation) and its dependents T16/T17,
plus the optional T26-live, remain — see the 2026-09-19 entries below.

Still open:
- **T15** (Phase 3) is still blocked on a live, manual codex 0.155 TUI
  investigation (`[tdd:skip:live-investigation]`) — needs a human-in-the-loop
  session. T16/T17 depend on it and stay blocked until it's done.
- **T26-live** needs explicit user confirmation before running — it
  deliberately burns quota on a live codex session.

2026-09-19 (T24, release): CHANGELOG entry for every merged task plus the
four pre-session commits (5668357, 1a5e9bc, f53921f, 78ffa2c), `CR_VERSION`
bumped to 1.12.0, `docs/how-it-works.md`'s test count corrected to the actual
760 (`Ran N tests` summed across all 17 files, not the looser "500+"). Tag
`v1.12.0` pushed after the user's explicit go-ahead for the external-send
event (git push, gh release, homebrew formula) — but its first CI run
(35439903275) **failed** `./test/run.sh` on `ubuntu-latest`
(`test_fake_agents.py`/`test_two_wrappers.py`), green locally on macOS both
times. Reproduced under `./test/run-docker.sh` (after first fixing a second,
independent bug it uncovered: `test/Dockerfile`'s Debian slim never installed
`procps`, so `pgrep` didn't exist and `test/helper.py`'s `_descendant_pids`
silently swallowed the resulting `OSError` and returned `[]` — every
pid-dependent assertion saw `None`). With `pgrep` actually present, `ps
--forest` showed the real cause: `claude-retrier.sh`'s own hand-off to python
(`exec ... 3< <(printf ...)`) forks a bash to feed that process substitution,
which becomes a direct, unreaped `<defunct>` child of the supervisor the
moment it exits — a lower pid than the real agent (it forked first), and
`_descendant_pids`'s `children[0]` picked it over the live `fake_claude.py`
underneath. Fixed by filtering zombies (`ps -o stat=`) out of the descendant
walk; confirmed 3x clean under Docker, then the whole Linux suite (764 tests,
`ALL PASS`) and again natively on macOS. Also picked up, in parallel while waiting on CI: the small T20/T21
consolidation polish (`on_status`'s inline model-id handling now routes
through `Controller.on_model()`, per the note left when T20/T21 landed
concurrently — 0650ce1). Tag moved to the fixed commit (72a3c3b) — the original v1.12.0 push had never
actually published a release (the Publish step is skipped on a red suite),
so nothing public pointed at the broken commit; moving a *pushed* tag is
normally treated as destructive and needed a second explicit confirmation.
Second run (35441371397) green; release published, Homebrew formula updated
to the new tarball/sha256 (57c109b in the tap) without any `brew
install`/`upgrade` on this machine.

Still open after this batch lands:
- **T15** (Phase 3) is still blocked on a live, manual codex 0.154 TUI
  investigation (`[tdd:skip:live-investigation]`) — not something to hand to
  an unsupervised coding subagent; needs a human-in-the-loop session. T16/T17
  depend on it and stay blocked until it's done.
- **T24** (release) and **T26-live** both need explicit user confirmation
  before running — T24 for the external-send event listed above (git push,
  gh release, homebrew formula), T26-live because it deliberately burns quota
  on a live codex session. Neither was started in this batch.

New session: `claude`
First input: `/harness-work T14`

2026-09-19: user asked for the next 5 ready backlog tasks, each in its own
subagent, with an explicit parallel-vs-sequential check first. Status check
via `git log` found T13, T14, T18, T19, T26 already merged to `main` from a
prior session whose work never got recorded here — this file's status column
was stale for all five; corrected above with their actual commit hashes
(T13 14f5378, T14 6a7693d, T19 00b99cc, T26 already had d3ea768 recorded
correctly). Real next-ready set was therefore T07, T20, T21, T22, T23 (T24/
T25/T26-live/T15 excluded per the "Still open" reasons above and below).

CodeGraph code-region check (current line numbers, not the backlog docs')
found T20 and T21 are NOT actually independent despite Plans.md listing no
cross-dependency between them: `_resolve_window`'s own docstring says
"T20 will have claude's own statusline do the same" as codex's window hint,
and T20's spec explicitly routes a claude-statusline model-id change through
`Controller.on_model()` — the exact entry point T21 introduces. T07
(bash-tail passthrough dispatch), T22 (`interrupt_line`/`trigger_limit`/
`_maybe_restart`, codex-only), and T23 (`Logger`, log rotation) were confirmed
disjoint from T21 and from each other. So T07, T21, T22, T23 were started
first, concurrently, in git worktrees under `claude-retrier-worktrees/`
(`task/t07-claude-passthrough`, `task/t21-model-switch-realtime`,
`task/t22-codex-threshold-semantics`, `task/t23-log-rotation`; the usual
untracked `CLAUDE.md`/`docs/backlog/`/`docs/spec/`/`codegraph.json`/
`test/codegraph-sync.sh` seeded into each). T22's own backlog doc turned out
partially stale too — its "remove `DEFAULT_CODEX_RESTART_PCT`" item was
already done by T18; the T22 agent was told to skip straight to the
remaining scope (interrupt-after-seconds, fold-cost logging/reserve-adapt).

T23 and T07 finished first and were merged into `main` as 2b5201c (T23,
fast-forward) then a merge commit (T07, `git merge` auto-resolved the one
overlapping hunk in `claude-retrier.sh`); `./test/run.sh` green after each.
While T21/T22 were still running, the user asked for 2 more tasks from the
queue to keep 4 agents busy: **T25** (docs-only, depends only on already-
merged T02/T04/T05/T08/T09, told to steer clear of the exact threshold
paragraph in `docs/codex.md` that T22 is concurrently rewriting) and **T20**
— started now rather than waiting for T21 to merge, since T20's own
acceptance criteria don't actually require `on_model()` to exist yet; its
agent was told explicitly not to reference T21's (not-yet-merged, not-in-its-
worktree) `on_model()` and instead do the minimal inline equivalent (set
`context_model` + call `_resolve_window()`, matching what `on_context`
already does), with a comment flagging it as a candidate for later
consolidation once T21 lands. Both launched in `task/t25-docs-after-binding`
and `task/t20-claude-effective-window`, branched from post-T23 `main`.

T22 merged next as a merge commit (`git merge` auto-resolved the one
overlapping hunk in `claude-retrier.sh`); `./test/run.sh` green (`test_pty.py`
alone took ~238s under contention from the T20/T21/T25 worktrees still
running their own suites, `test_codex.py` re-run in isolation afterward to
confirm — 147 tests OK). T21 merged next: a real conflict this time, both
branches had inserted a new `unittest.TestCase` class at the same point in
`test/test_codex.py` (T22's `TestFoldCostAndReserve` and T21's
`TestModelSwitchResetsTheCodexCap`) — trivial to resolve, kept both classes
back to back, no logic conflict. T25 merged last and hit an unrelated
conflict: `docs/bugs/codex-self-compaction-orphans-handoff.md` had a
pre-existing *uncommitted* Russian→English translation sitting in `main`'s
working tree (not part of this batch, already there before this session
started) that T25's branch — checked out before that translation existed —
also touched (a small 3-link paragraph added near the top, in Russian, to the
still-untranslated file). Resolved by stashing the translation, merging T25
cleanly, then popping the stash and manually re-translating T25's added
paragraph into English to match the surrounding file rather than discarding
either side; the rest of the pre-existing uncommitted translation (this file
plus `.gitignore`, `docs/backlog/T29-agents-panel-render.md`,
`test/fixtures/README.md`) was deliberately left uncommitted and unstaged
exactly as found — it is not part of this batch and not this session's to
commit. `./test/run.sh` green after both merges.

Of the 6 tasks in this batch (T07, T20, T21, T22, T23, T25), 5 are merged;
**T20** is the only one still running as of this note, deliberately started
in parallel with T21 rather than sequenced after it (see above) — once it
reports, its inline model-id handling may be worth consolidating with T21's
now-merged `Controller.on_model()` (source labels: `"local command"`,
`"assistant line"`, `"codex log"`; signature `on_model(self, model, source,
now)`, returns `True` iff the slug actually changed), though that is a
polish item, not a correctness requirement for either task's own AC.

2026-09-18/09-19 (Phase 2, T08/T09/T12, then T03/T18): code-region check via
CodeGraph on the current (post-T01–T28) line numbers — not the stale ones in
the backlog docs — found T08 and T09 both edit the same small
`_abort_restart`/`_tick_restart` dispatcher and the state tuple/
`RESTART_LABELS`, while T12 only touches `_check_handoff`/`_handoff_fault`/
`on_context`'s `last_stop_reason` handling, disjoint from both. So T08 and
T12 ran concurrently in worktrees `task/t08-unfold-owed` and
`task/t12-handoff-latch` (untracked `CLAUDE.md`/`docs/backlog/`/`docs/spec/`/
`test/codegraph-sync.sh`/`.codegraph*` seeded into each, same reason as the
T10/T11/T06 batch). Merged into `main` as 91f94c9 (T12, no conflicts) then
8e8adba (T08, `git merge` auto-resolved overlapping edits in
`claude-retrier.sh`/`test_controller.py`); `./test/run.sh` green on the
merged tree (one `test_the_restart_flag_reaches_codex_through_bash_too`
failure seen under full-suite CPU load, confirmed as a pre-existing
`test_pty.py`-style flake by 3/3 clean isolated reruns at the time, not a
regression from T08/T12). T09 was then branched as
`task/t09-cancel-after-abort` from the post-T08+T12 `main` (so its edits to
the now-larger `_abort_restart` land on top of T08's version instead of
racing it) and merged as df16021; `./test/run.sh` green again.

The user then asked for the next two ready backlog tasks in parallel too:
T03 (Phase 4, `CodexAgent` rollout binding) and T18 (Phase 5, model profile
table) — both depend only on already-merged tasks and touch disjoint code
(T03: `CodexAgent.paths`/`keep`, `TranscriptWatcher`, new
`Controller.on_candidates`/`context_ambiguous`; T18: `MODEL_PROFILES`,
`model_restart_at`, `_recompute_limit`, `--cr-models`), so both ran
concurrently in `task/t03-codex-session-binding` and
`task/t18-model-profiles-table`, branched from post-T09 `main`. T15 (next in
Phase 3 by table order) was again skipped for this batch — live manual
investigation, not delegable. Merged as 16a92e4 (T03) then 0f90975 (T18);
`git merge` auto-resolved every overlapping hunk (`claude-retrier.sh`,
`docs/codex.md`, `docs/configuration.md`, `docs/context-restart.md`,
`test_codex.py`, `test_controller.py`) with no manual conflict resolution.
Notably, T18's own work surfaced and fixed a real (pre-existing, not
T18-caused) gap: `test/fake_codex.py`'s `FAKE_USAGE` path never wrote
`turn_context`, so no model name was ever on record for that test path —
harmless under the old flat-percentage threshold, but it meant
`model_restart_at`'s new model-keyed profile lookup couldn't resolve, and
separately `codex_launch_args()` failed to hold codex's own compaction back
when only the bare `CR_CONTEXT_RESTART=1` flag was set (codex would still
self-compact at its 90% soft cap, undermining the point of arming the
restart). Both fixed as part of T18's commit. `./test/run.sh` was green
after each merge and on the final tree (`ALL PASS`, all 17 files, including
the previously-flaky-looking codex end-to-end test, which passed reliably
every time post-fix).

2026-09-18: T04, T05, and T28 implemented in parallel git worktrees (T04/T05
share no code with T28, so all three ran concurrently; T10 was deliberately
left out of this batch because it touches `on_context` the same way T04 does,
and merging two independent rewrites of the same function was judged riskier
than sequencing them). Merged into `main` as 326ab72 (T04), b7b664f (T05),
b0fe1c6 (T28); `./test/run.sh` green after each merge and on the final tree.

2026-09-18 (later): T10, T11, and T06 implemented in parallel, each in its own
`git worktree` (branched from local `HEAD`, not `origin/main`, which was 16
commits behind — a `test/codegraph-sync.sh` copy was seeded into each
worktree since it was untracked). Code-region check confirmed no overlap:
T10 touches `assistant_row`/`usage_tokens`/`on_context`/`_context_fell`; T11
touches only the collapse branch of `transcript_limit_records`; T06 touches
`TranscriptWatcher.expect/forget`, `on_handoff_echo`, and the
`_send_handoff`/`_check_handoff`/`_send_clear` trio plus `main()`'s wiring —
so all three ran concurrently rather than sequentially. Merged into `main`
one at a time as 08c9680 (T10), 277a446 (T11), 7bb1656 (T06); `git merge`
auto-resolved every touched file (including `test_controller.py`, which all
three branches extended) with no manual conflict resolution needed, and
`./test/run.sh` was green after each merge and on the final tree (one
`test_pty.py` timeout seen once, reproduced as a pre-existing ~25-30% flake
unrelated to these changes via repeated reruns on both the unmodified and
modified tree).

2026-09-18 (Phase 2, T08/T09/T12): code-region check via CodeGraph on the
current (post-T01–T28) line numbers — not the stale ones in the backlog docs
— found T08 and T09 both edit the same small `_abort_restart`/`_tick_restart`
dispatcher and the state tuple/`RESTART_LABELS`, while T12 only touches
`_check_handoff`/`_handoff_fault`/`on_context`'s `last_stop_reason` handling,
disjoint from both. So T08 and T12 ran concurrently in worktrees
`task/t08-unfold-owed` and `task/t12-handoff-latch` (untracked
`CLAUDE.md`/`docs/backlog/`/`docs/spec/`/`test/codegraph-sync.sh`/`.codegraph*`
seeded into each, same reason as the T10/T11/T06 batch). Merged into `main`
as 91f94c9 (T12, no conflicts) then 8e8adba (T08, `git merge` auto-resolved
overlapping edits in `claude-retrier.sh`/`test_controller.py`); `./test/run.sh`
green on the merged tree (one `test_the_restart_flag_reaches_codex_through_bash_too`
failure seen under full-suite CPU load, confirmed as the pre-existing
`test_pty.py`-style flake by 3/3 clean isolated reruns, not a regression).
T09 was then branched as `task/t09-cancel-after-abort` from the post-T08+T12
`main` (so its edits to the now-larger `_abort_restart` land on top of T08's
version instead of racing it) and is still running. T03 and T18 were started
in parallel with it in `task/t03-codex-session-binding` and
`task/t18-model-profiles-table`, since both depend only on already-merged
tasks and touch code neither T09 nor each other touch (T03: `CodexAgent`
binding/`paths()`; T18: `MODEL_PROFILES`/`model_window`/`--cr-models`). T15
(next in Phase 3 by table order) was intentionally skipped over for this
batch — it is a live, manual Codex-TUI investigation
(`[tdd:skip:live-investigation]`), not a fire-and-forget coding task for an
unsupervised subagent.
