# T28 — Move the badge (`◆ cr`) to the rendering mechanism shared with the overlay

Priority: P0 · Epic: F · Depends on: T27 · Size: M

## Problem

T27 added a second, independent way to paint over someone else's TUI
(`AgentOverlay._paint_row`, agent-retrier.sh:4269), almost verbatim
duplicating what `Badge` (class, agent-retrier.sh:3588) has done since 2023:
`DECSC → CUP → SGR → text → SGR reset → DECRC`, never touching the last
column, and padding with spaces to the old (wider) width so that shrinking
text erases the tail of the previous text. The two places with the same
arithmetic already diverged once while T27 was being written — in the first
implementation of `AgentOverlay._paint_row`, the write column was calculated
from the NEW (narrower) text width, while space padding went to the OLD
(wider) width, allowing a shrinking label to reach past the protected last
column and scroll the screen; `Badge.paint`/`Badge.sequence` did not contain
this error because they calculate space padding BEFORE calculating the column.
The bug was caught by an independent review, not a test — so the duplication
is demonstrably dangerous, not merely hypothetical.

In addition to duplicating the arithmetic, the two paths are coordinated only
manually: `AgentOverlay.paint()` receives `badge_row` as a parameter
(agent-retrier.sh:4608-4609) and manually excludes that row, while `Badge`
knows nothing about the subagent tree and checks nothing — it merely happened
to be the only one before T27. Centralization removes both the duplicated
arithmetic and the manual coordination where “one side knows the other by
name.”

## What to do

1. Extract the shared rendering primitive — `DECSC → CUP → SGR → text → reset →
   DECRC`, calculating the column from the FINAL (already padded) width, and
   preventing writes to the last column — into one function/class (for example,
   `paint_annotation(fd, row, col, text, sgr, prev_width)` or a shared
   `RowPainter`) used by both `Badge` and `AgentOverlay`.
2. Use a shared per-frame occupied-row registry: instead of passing
   `badge_row` as a separate parameter, both painters register with/query one
   object to determine which row is already occupied in the current frame — so
   adding a third participant (if one appears) will not require another manual
   check.
3. Explicitly decide and document (see “Open questions” below) whether
   `Badge` continues drawing on its current `due()` timer (output quiescence)
   independently of `Screen`, or also switches to a trigger on frame closure
   (`ESC[?2026l`) — this determines whether `Screen` is created by default
   (`CR_BADGE=1` is enabled out of the box, while `CR_AGENTS_OVERLAY=0` is
   not).
4. Do not change the badge's observable behavior (text, colors, redraw
   timing, behavior with `CR_BADGE=0`) — this is a refactoring of a shared
   primitive, not a new badge feature.

## Acceptance criteria

- [ ] `test_badge.py`: the entire existing suite (30 tests as of T27) passes
      without changes to expected bytes/columns.
- [ ] `test_agents.py`: the entire existing suite (25 tests, including the
      shrinking-label regression) passes through the shared primitive.
- [ ] A new test for the shared primitive itself: the same function, called
      from both `Badge` and `AgentOverlay`, produces the same column offset when
      text shrinks — arithmetic duplication is mathematically impossible, not
      merely “happens to match right now.”
- [ ] `test_pty.py::TestBadge` and `test_pty.py::TestAgentOverlay`: both pass
      without `badge_row` being manually passed by name — coordination occurs
      through the shared row registry, covered by a test for a collision
      between the badge and a tree row.
- [ ] `--cr-help`/environment variables remain unchanged (this is an internal
      refactoring).
- [ ] `./test/run.sh` passes; `./test/codegraph-sync.sh` has been run.

## Where in the code

`Badge` (3588): `due` (3651), `place` (3673), `sequence` (3683), `paint`
(3692), `erase` (3716) — an example of the correct order (padding before the
call to `place`). `AgentOverlay` (4242): `paint` (4248), `_paint_row` (4269) —
the location of the bug with the wrong order, already fixed, but still a
separate copy of the arithmetic. Call sites in `main()`: `badge.paint` (4749),
`badge.erase` (4780), `agents.paint` with `badge_row=` (4608-4609).

## Open questions (resolve during implementation)

- **Is `Screen` created by default?** T27 deliberately made `Screen` optional
  (`CR_AGENTS_OVERLAY=0` means zero extra bytes and no emulator is created at
  all), while `Badge` is enabled out of the box (`CR_BADGE=1`). If `Badge`
  switches to the same “redraw after frame closure” trigger, this either
  requires keeping `Screen` active at all times (when the badge is enabled —
  that is, almost always), or `Badge` continues using its independent
  `due()` timer (output quiescence), sharing only the RENDERING primitive with
  `AgentOverlay`, not the REDRAW trigger. The latter is lower risk and appears
  to be the right default choice, but the decision and its cost (in
  performance/complexity) must be explicitly recorded rather than selected by
  the implementation by default.
- **Is `AgentOverlay.erase()` needed on exit**, analogous to `Badge.erase()`
  (4780)? T27 deliberately left this outside the AC (there is no alternate
  screen, and the labels remain in the real scrollback without harming the
  session), but with primitive centralization, erase will become shared for
  free — decide whether to call it for the agent tree as well instead of
  leaving the asymmetry unexplained.
