# codex: session hangs empty after codex compacts context itself during fold

Backlog tasks that close findings from this investigation:
[T08 — unfold is mandatory after `/clear`](../backlog/T08-unfold-is-owed.md),
[T09 — cancel phrase after abort of an already-delivered fold](../backlog/T09-cancel-after-abort.md),
[T22 — codex threshold and reserve semantics](../backlog/T22-codex-threshold-semantics.md).

Status: the leading fix candidate (Finding 1) has been implemented in branch
`fix/handoff-race-recovery` — see “What was done” at the end of this file.
Findings 2 and 3 (reserve/repeated interruptions during fold), and the items
under “Not checked”, have not been addressed yet.

## What the user observed

The `agent-retrier-codex` session in project `openhopper.app` (worktree
`feat/moldshell-extractor-phase-r1`). Screenshots are in the conversation from
2026-09-15 ~03:2x (the incident itself occurred earlier; see the log below).

Sequence on screen:
1. A `CR_HANDOFF_MSG` arrives (“Wrap up now. Do not start new work. Write a
   complete handoff to `scratchpad/RESUME.md` ... HANDOFF-4b5a6d39”).
2. The model wraps up: checks merge-lock/agent-state, stops the supervisor,
   writes `scratchpad/RESUME.md` (392 lines), ends it with marker
   `HANDOFF-4b5a6d39`, and checks `test -f`, `wc -l`, and the last line; all
   checks pass.
3. The transcript shows `Context compacted · 29s`.
4. The model reports: “Full context handoff written... Work and the
   controlling agent stopped... Worked for 4m 02s”.
5. Then silence. The input line is empty and context is `3% used`. The resume
   phrase (`CR_RESUME_MSG`) was never printed. Without the user noticing, the
   session would have remained empty and hung.

## Investigation

The `~/.agent-retrier/log` log for that night (project `openhopper.app`)
contains exactly what is needed:

```
[2026-09-15 00:26:45] context is 231k of a 258k window (89%, threshold 137k); folding up
[2026-09-15 00:30:40] codex compacted the thread on its own before the restart could (1 this session) — the count stood at 261k of a 258k cap
[2026-09-15 00:30:40] restart aborted at handoff_sent: codex compacted the thread itself during handoff_sent
[2026-09-15 03:24:00] start: /opt/homebrew/bin/claude  (agent: claude)
```

This confirms what the screenshots show and explains the cause.

### Finding 1 (main): race between the fold turn and codex’s own compaction

`Controller._lost_the_race()` (agent-retrier.sh): as soon as codex compacts the
thread while `rstate` (`HANDOFF_SENT` here) is unfinished, the controller calls
`_abort_restart(...)`. The abort does not check the result afterward:
`context_tokens` is reset, `rstate` is reset, and — crucially — **the resume
phrase (unfold, `CR_RESUME_MSG`) is never sent**, even if the fold has already
written the file successfully (as here: `HANDOFF-4b5a6d39` is the final line,
and the model verified the file). `_abort_restart` deliberately does nothing
(“Nothing is cleared, nothing is retyped, no state is unwound”); it assumes the
session will fall through Claude Code/codex’s own compaction and continue. But:

- `Context compacted` is compaction by **codex itself**, not the wrapper’s
  `/clear`. The wrapper does not treat it as a successful clear and does not
  start unfold.
- The handoff is valid and usable, but nobody prints `CR_RESUME_MSG` because
  the restart is already marked aborted.

Thus the context reset as expected, and the handoff was correctly written, but
the linking step (“read the file and continue”) was skipped entirely — exactly
what the user saw.

This also explains why the log contains no context-clear command. The wrapper’s
`/clear` is logged only when sent —
`"handoff verified; clearing the context with %s" % clear_cmd`
(agent-retrier.sh:3252) — and only on transition to `CLEARED`, after handoff
verification. Here the restart aborted in `handoff_sent`, before verification,
so that line was never reached. `Context compacted` in the codex transcript is
not a wrapper command: agent-retrier sends nothing to compact codex; it only
detects the already completed event by reading the `"compacted"` record from
the rollout file (see `if rec.get("type") == "compacted"` in
agent-retrier.sh). The log line `codex compacted the thread on its own before
the restart could` is only a post-factum record, not an outgoing action.

### Finding 2: the threshold did not trigger in time, leaving almost no headroom before codex’s cap

`CR_CONTEXT_PCT` (or the default 51%) should trigger a fold at 137k tokens
(238k window * ~53%, according to the log: `threshold 137k`). In reality fold
started at **231k / 89%**, almost at codex’s `258k` cap (see `docs/codex.md`
for “90% of the raw window — 244,800 tokens” with a raw window of 258.4k;
the cap here is recorded as 258k). The ~94k-token difference apparently arrived
in one jump between checks: the log counts only when the transcript grows,
through `note_growth`/line reading, rather than fixed-interval polling. One
codex turn, perhaps with large tool output from a file or log, likely added tens
of thousands of tokens, skipping the 137k threshold and jumping to 231k.

By the time the wrapper learned it should fold, only ~27k tokens remained before
the `258k` cap where codex compacts itself. The fold turn (reading
merge-lock/agent-state, stopping the supervisor, writing the 392-line RESUME.md,
and self-checking) consumed that reserve over ~4 minutes, so codex compacted first.

### Finding 3: interruption triggered in time, but the reserve was barely insufficient

The complete log from that evening shows that Finding 2’s interpretation is
inaccurate: interruption worked exactly as designed:

```
[2026-09-14 21:24:43] codex compacts this thread at 258k by its own count; restarting at 137k, interrupting a running turn past 226k
[2026-09-15 00:26:23] context is 231k, within 32k of codex compacting at 258k; interrupting the running turn to fold it up
[2026-09-15 00:26:25] restart step held: the session is still writing to its transcript
[2026-09-15 00:26:45] context is 231k of a 258k window (89%, threshold 137k); folding up
[2026-09-15 00:26:45] asking for a handoff into scratchpad/RESUME.md (attempt 1/2, marker HANDOFF-4b5a6d39)
[2026-09-15 00:30:40] codex compacted the thread on its own ... the count stood at 261k of a 258k cap
```

The running turn was interrupted (Esc) at `cap - CR_CODEX_RESERVE_TOKENS` =
`258k - 32k` = `226k`, as stated in the `CR_CODEX_INTERRUPT` comment. The fold
turn is not interrupted afterward because it must finish the handoff. It used
another **~30k tokens** in 4 minutes (reading `agent-merge-lock`/`agent-state`,
stopping the supervisor, writing 392-line `RESUME.md`, and shell self-checking),
crossing the hard cap (`261k > 258k`) a few thousand tokens before the marker
was written and verified.

Conclusion: `CR_CODEX_RESERVE_TOKENS=32k` is a reserve **for the entire fold
turn**, not merely “up to the cap”. Heavy folds with several shell commands and
self-checking consume a comparable amount. The default is systematically too
thin for this heavy `CR_HANDOFF_MSG`, which also requests merge-lock/agent-state
checks and therefore adds tool calls.

### On “disabling codex auto-compaction entirely”

We discussed simply disabling this uncontrollable behavior and relying on the
wrapper restart. The code indicates this is **not fully achievable through
configuration**. The `CR_CODEX_HOLD_COMPACT` comment describes two thresholds:
a “soft” 90% raw-window threshold that *can* move via
`model_auto_compact_token_limit_scope`/`model_auto_compact_token_limit` (which
`CR_CODEX_HOLD_COMPACT=1`, enabled by default, does), and a “hard” 95% threshold
(258.4k of 272k) — “a cap nothing can move”. Thus `CR_CODEX_HOLD_COMPACT` is
already “disable auto-compaction as far as possible”, and was enabled here. The
compaction occurred on reaching the immovable hard cap, not the soft threshold.

**Decision (2026-09-15):** do not pursue removing the hard cap until it is known
to be possible. Make the wrapper fit reliably within its reserve instead. The
user accepts that a larger reserve starts folds earlier, causing somewhat more
restarts (and history rewrites after `/clear`) and slightly higher token use;
this is preferable to the bug described here.

(Clarification: Reddit complaints that “token usage became faster” concern
people who enabled an 800k+ context instead of the default ~270k. Larger
windows make every request heavier/more expensive and exhaust the weekly quota
faster. This is unrelated to auto-compaction, `CR_CODEX_RESERVE_TOKENS`, or
this bug. The discussion here concerns the default ~270k window.)

Specifically:
- raise `CR_CODEX_RESERVE_TOKENS` from 32k to a value covering the heaviest
  realistic fold turn, or make it adaptive based on actual fold consumption;
- investigate whether a new codex-cli flag, environment variable, or
  `config.toml` patch can raise/remove the hard cap;
- if the cap cannot be removed, consider repeated interruptions during fold
  when it approaches the cap, rather than relying on one reserve for the whole fold.

### Not checked / investigate further

- Inspect the transcript to learn why 137k → 231k happened in one jump and
  which tool call caused it; a large-file read may make a larger reserve predictable.
- `_maybe_interrupt()` interrupts a turn before fold. Check whether the same
  Esc logic should apply during fold as it approaches the cap.
- Main fix candidate: in `_lost_the_race()` / `_abort_restart()`, read the
  handoff again before giving up. If its marker exists, as here, skip abort,
  transition to `RESUME_SENT`, and print `CR_RESUME_MSG` (codex already cleared
  context, so only unfold is needed). At minimum make `notify()` more visible
  than a transient line when the log says “restart aborted”.
- Check `notify()` in agent-retrier.sh: “restart aborted at handoff_sent: ...”
  is transient by design and immediately redrawn by the codex TUI. This likely
  explains the missing screenshot warning; consider a persistent badge or log.

## Where to look in the code

- `agent-retrier.sh`: `Controller._lost_the_race`, `Controller._abort_restart`,
  `Controller._maybe_interrupt`, `Controller.note_growth`, `notify()` (pty launch block).
- `docs/context-restart.md` — standard four-step flow (fold → check → `/clear`
  → unfold) and “Caveats”.
- `docs/codex.md` — “Staying ahead of codex's own compaction”, describing the
  cap (258k / 90% of the raw window) reached here.

## How to reproduce (hypothesis, not checked)

1. Start agent-retrier-codex with `CR_CONTEXT_PCT` around 50% on a long session.
2. Trigger very large tool output (for example, reading a huge file or log) so
   the counter jumps from below threshold into the final ~10% before codex’s
   `CR_CODEX_HOLD_COMPACT` cap.
3. Let the fold turn write the handoff for several minutes. If codex compacts
   first, there should be a valid handoff, “Context compacted” in the transcript,
   but no subsequent unfold.

## What was done (branch `fix/handoff-race-recovery`)

The main Finding 1 fix was implemented. Before `_lost_the_race()` calls
`_abort_restart()`, it now retries `self.probe(self.handoff_path)` and passes it
through `_handoff_fault()`, the same check used by `_check_handoff()`. If all
four layers (file exists, is not older than the request, meets the minimum
length, ends with the correct marker, and the turn closed with `end_turn`) have
passed — as in this incident — the restart is not aborted. `rstate` moves
directly to `CLEARED` (no second `/clear`; codex already performed it), and the
next `_tick_restart()` waits until the session is no longer busy and sends
`CR_RESUME_MSG` through `_send_resume()`. This applies only to
`HANDOFF_SENT`/`HANDOFF_OK`; `CLEARED`/`RESUME_SENT` still abort on a race because
there is then nothing to restore.

If verification fails (incomplete file, wrong marker, turn did not end through
`end_turn`, etc.), behavior is unchanged: `_abort_restart()` is called and the
session falls through its own Claude Code/codex compaction without printing anything.

Tests: `test/test_codex.py`, class `TestStayingAheadOfCodex` —
`test_codex_getting_there_first_does_not_lose_a_landed_handoff` (valid handoff
survives the race and unfold is sent) and
`test_codex_getting_there_first_with_no_handoff_still_aborts` (invalid handoff
retains old behavior; existing `test_codex_getting_there_first_is_said_and_ends_the_restart`
also remains green unchanged). Full `./test/run.sh`, including `test_pty.py`,
was run successfully; no orphaned processes remained.

Not done in this pass:
- Findings 2/3 (`CR_CODEX_RESERVE_TOKENS` and repeated interruptions during
  fold) — the fix does not reduce the race itself, only its lost-unfold result.
- The “Not checked” items: the 137k → 231k jump and `notify()` robustness for
  permanent aborts.
- No live run on real codex was performed, only `Controller` unit tests. The
  race was simulated with `Handoff.write()` + `compacted=True`; real codex/pty
  was not tested.
