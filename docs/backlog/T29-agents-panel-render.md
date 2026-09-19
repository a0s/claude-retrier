# T29 — Overlay on the expanded agent panel (`← for agents` / `/tasks`), not only on the live tree

Priority: P0 · Epic: F · Depends on: T27 · Size: M

## Problem

T27 recognizes and labels only ONE render form — the inline tree with
`├`/`└`/`│` glyphs (`⏺ Running N ... agents…`), which lives on screen for
seconds while agents are running, then collapses into
`⏺ N background agents launched (↓ to manage)` and moves into the scrollback. This was
deliberately recorded as an open question in
`docs/backlog/T27-subagent-model-overlay.md` ("The expanded panel... is absent
from the capture"), but in practice this turned out not to be a secondary detail,
but precisely the tree the user actually keeps in front of them: a live
screenshot (2026-09-18, Claude Code 2.1.273) shows a persistent bottom
panel —

```
⏵⏵ manual mode on · /tasks to see subagents · ← for agents

● main
○ Explore  Report the name of the second file in cwd    4s · ↓ 13.6k tokens
○ Explore  Count the files in cwd                       3s · ↓ 10.2k tokens
```

— opened with the `←` arrow, which does **not** collapse by itself and remains
on screen until closed. A run with `CR_AGENTS_OVERLAY=1` was confirmed (the `◆ cr`
badge is visible on the same line, overlapping `tokens`), but there is no model
label: `find_agent_rows` does not find a single row here — the `○ Explore  label`
format does not match `CR_AGENT_ROW_PATTERNS` (`^ {3}([├└│])\\s(.+)$`), which was
designed only for a glyph in column 4.

## What to do

1. **Live recapture** (T27 method, with `test/fixtures/capture-agent-tree.py`
   as the basis): extend the driver — after spawning agents, wait until at
   least one finishes (so the tree has time either to collapse or for the panel
   to open), send `←` (or whatever actually opens the panel — verify whether
   this is truly the left-arrow key code; the footer says `←`, but the first
   T27 pass noted that "the collapsed row says `(↓ to manage)`" — the discrepancy
   between what the hint says and what actually works must be resolved live,
   rather than by relying on the hint text). Save the raw bytes as a new fixture
   (`test/fixtures/agents-panel-2.1.273.bin` or the next Claude Code version,
   if the currently installed one is newer).
2. Run the capture through `Screen` (already in the supervisor) and see how
   `○ Explore  label` rows actually sit in the grid — the glyph column is `○`,
   the label start column, and whether there is a tail like `· N tokens` that
   should be stripped in the same way as `· N tool uses` in the current
   `find_agent_rows`.
3. Add recognition for this form — either a second pattern in
   `CR_AGENT_ROW_PATTERNS`/`PAT["agent_row"]`` (if the geometry is similar
   enough: a fixed glyph in a fixed column + label), or a separate function
   `find_panel_agent_rows(screen)` if the form is sufficiently different that
   a unified pattern would be unreadable — decide based on what the capture
   shows, not by guessing in advance.
4. Check the connection with `SubagentRegistry`/`model_label`: panel labels
   are the same `description` values from `agent-*.meta.json` as in the tree,
   so the "label → model" association should work unchanged if the label text
   matches (including the case where the panel truncates a long label
   differently from the inline tree — test with a long task).
5. Check for collision with `AgentOverlay`'s `avoid`/`badge_row`: the panel has
   its own geometry (several consecutive rows at the bottom of the screen,
   rather than scattered through the scrollback) — the risk of colliding with
   the badge and with Claude Code's own status line (`[Haiku 4.5] main | ... 19% | $...`,
   `⏵⏵ manual mode on...`) is higher than with the fleeting inline tree.

## Results of the live investigation (2026-09-18, Claude Code 2.1.273)

The live recapture (`test/fixtures/capture-agents-panel.py`, a real `claude`
session, user authentication, ~5 live runs) produced an answer different from
the original hypothesis, and one incident along the way:

- **`←` is not about Task-tool subagents at all.** Verified both in default and
  `--permission-mode manual` (the footer says `← for agents` in both cases):
  pressing it collapses the ENTIRE session into the background and opens an
  **inter-session roster** — a list of OTHER, unrelated sessions on the machine,
  with their real names and summaries (emails, insurance, PDFs, etc.). This is
  exactly the screen that `CR_ROSTER_PATTERNS` already deliberately never
  scrapes. The first capture attempt (auto mode, after the agents had already
  finished) actually showed someone else's content for a second; those bytes
  were never written to disk or committed — the incident was noticed
  immediately, and the driver was rewritten to
  buffer-in-memory-until-safe (see `capture-agents-panel.py`). The premise that
  underpinned the entire task — "`←` opens subagents" — was removed from the
  code: this is not true under any tested conditions.
- **`↓` on the collapsed `(↓ to manage)` row does not open anything either.**
  Pressing it in auto mode produced no visible effect — the agents simply
  finished and wrote ordinary inline completion messages. The T27 open question
  is closed: the `(↓ to manage)` hint does not match the observed behavior in
  2.1.273.
- **`/tasks` (entered as a command) is the confirmed working method.** While at
  least one subagent is running, `/tasks` opens a persistent panel
  `Background → N active agents → Local agents (N)`, which does not collapse
  by itself and closes with `Esc` — exactly the property for which this task
  was created. The real capture is saved as
  `test/fixtures/agents-panel-2.1.273.bin`.
- **The row format is NOT `○ Explore  label · Ns · ↓ N tokens` from the
  screenshot.** The actual format (both while running and afterward) is
  `<5 spaces><label> (running|done) · <Model>` for an ordinary row, and
  `   ❯ <label> (state) · <Model>` for the row selected by the cursor — a
  selector glyph in column 4, with the label always starting in column 6.
  The section heading `Local agents (N)` starts in THE SAME column 6 and differs
  from a real row only by lacking `(state)` — that is how they are distinguished.
  **The model is already displayed as plain text by Claude Code itself** in this
  panel — the overlay is not required here to solve the original "which model
  is unclear" problem, but it still labels these rows (through the same path as
  the inline tree) for consistency and in case upstream removes `· Model` from
  the render.
  The screen capture with `○ Explore label ... tokens` that initiated the task
  was never reproduced in 5 live attempts (different timings, both permission
  modes, both candidate keys) — either it belongs to another Claude Code build/
  version, or requires another condition not discovered live. The task is closed
  based on the real, reproducible capture, rather than an unreachable screenshot
  (see the top-level instruction: "decide based on what the capture shows, not by
  guessing in advance").

Implementation: `find_panel_agent_rows(screen)` (claude-retrier.sh) — a separate
function, not a second pattern inside `find_agent_rows`, because the capture
groups (label / state) do not have the same semantics as the old pattern
(glyph / label). The `CR_AGENTS_PANEL_ROW_PATTERNS` → `CR_PAT_AGENTS_PANEL_ROW`
pattern is not anchored to the end of the line (it matches as a prefix), just as
`CR_AGENT_ROW_PATTERNS` does — trailing junk after `(state)` does not break
recognition. `AgentOverlay.paint` calls both row-finding functions line by line;
their row sets cannot overlap by construction (different glyph sets), so
concatenation without deduplication is safe.

## Acceptance criteria

- [x] A new fixture with raw bytes from the real expanded-panel render is
      saved in `test/fixtures/` (`agents-panel-2.1.273.bin`), with the same
      source README description as `agent-tree-2.1.273.bin`.
- [x] `test_screen.py`/`test_agents.py`: the panel capture is run through
      `Screen`, `find_panel_agent_rows` finds every row with the correct label;
      the panel's service row (the `Local agents (N)` heading) is not accepted
      as an agent (`TestRealCaptureAgentsPanel`, `TestFindPanelAgentRows`).
- [x] `test_pty.py`: with `CR_AGENTS_OVERLAY=1`, the model label for every agent
      row is visible in the panel opened by the `/tasks` command;
      `screen.scrolled == 0`; the last column is untouched
      (`TestAgentsPanelOverlay`).
- [x] The T27 open question "does `find_agent_rows` apply to panel rows?" is
      closed: no — the geometry and semantics of the groups differ enough to
      require a separate `find_panel_agent_rows` function; this conclusion is
      based on the capture (see "Results" above), not an assumption.
- [x] `./test/run.sh` is green; `./test/codegraph-sync.sh` has been run.

## Where in the code

`find_agent_rows`, `find_panel_agent_rows` (claude-retrier.sh, adjacent);
`CR_AGENT_ROW_PATTERNS`, `CR_AGENTS_PANEL_ROW_PATTERNS` (bash arrays alongside
`CR_ROSTER_PATTERNS`); `AgentOverlay.paint`/`_paint_row` (unchanged — accepts
the combined list of rows from both row-finding functions);
`test/fixtures/capture-agents-panel.py` — capture driver;
`test/fake_claude.py` (`FAKE_AGENTS_PANEL`, `draw_agents_panel`, `repaint-panel`)
— fake for `test_pty.py`.

## Open questions

Closed (see "Results" above). Nothing remains open for this task.
