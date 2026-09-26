# T27 — Model and effort of each subagent overlaid on the on-screen tree

Priority: P0 · Epic: F · Depends on: — · Size: L

Investigated live on 2026-09-18 on Claude Code 2.1.273: a pty capture of a real
session with a subagent tree (305 frames over ~2 min) and analysis of 715
`subagents/agent-*.jsonl` files on the machine. All claims below come from
these two sources, not from the documentation.

Captures are stored in the repository: `test/fixtures/agent-tree-2.1.273.bin`,
`test/fixtures/agent-tree-2.1.273-collapsed.bin`, and the driver
`test/fixtures/capture-agent-tree.py` (see `test/fixtures/README.md`).

## Problem

An `harness-loop` session creates a subagent tree, and the user sees **no
numbers at all** about what powers them: the TUI shows no model in the agent
row, the tool call, or `/cost`. Upstream closed the request as “not planned”.
For a user paying for a run, a tree of a dozen agents is a black box: it is
unclear whether it is running cheap haiku or expensive opus.

The wrapper is the only component that can show this: it owns the pty and reads
the transcripts. The badge has already demonstrated that drawing over another TUI is safe.

## Evidence

### How the TUI renders the tree

1. **There is no alternate screen.** `ESC[?1049h` never occurs. Output goes
   into the normal buffer and into the real scrollback. An overlay is possible,
   but the tree scrolls with the screen.
2. **Frames are atomic:** every redraw is wrapped in
   `ESC[?2026h` … `ESC[?2026l` (synchronized output). This is a ready-made
   frame boundary, better than the `Badge.QUIET` (3623) quiet heuristic.
3. **Rendering is home-relative and differential:** a frame opens with
   `ESC[?25l ESC[H`, proceeds downward using *relative* movements (`ESC[22B`,
   `\r ESC[3C ESC[1B`), and parks the cursor at the end with absolute CUP
   (`ESC[50;1H`). Only changed cells are rewritten—one frame rewrote a single
   digit, `2`→`3`.
4. **Text is printed word by word via CHA:** words are separated by `ESC[<col>G`,
   so `b"trust this folder"` **does not exist** in the stream.
   **Byte grep will not find the tree—you need a grid renderer.**
5. **Geometry (frame 127, verbatim):**
   ```
   \r\x1b[2C\x1b[21BRunning \x1b[1m2\x1b[22m Explore agents…\x1b[29G\x1b[K
   \r\x1b[3C\x1b[1B├\x1b[6G\x1b[1mReport first file in cwd\x1b[22m · 0 tool uses
   \r\x1b[3C\x1b[1B│\x1b[6G⎿  Initializing…
   \r\x1b[3C\x1b[1B└\x1b[6G\x1b[1mReport second file in cwd\x1b[22m · 0 tool uses
   ```
   The glyph is in column 4 (`├` U+251C, `└` U+2514, `│` U+2502, child `⎿` U+23BF),
   and the label starts at column 6 (`ESC[6G`). Collapsed form:
   `⏺ 3 background agents launched (↓ to manage)`. Other forms:
   `⏺ Explore(Report first file in cwd)`,
   `⏺ Agent "Find first file in cwd" finished · 10s`.
6. **The row label is exactly the `description` from the Agent tool input.** It
   is neither the model nor the agent type. This is the key linking “screen row” ↔ “agent”.
7. **Rows end with `ESC[K`.** Anything we append on the right is erased on the
   next redraw of that row. This is the main mechanical constraint:
   **the annotation must be applied again on every frame.**
8. **There is room on the right, but it is volatile:** labels occupy ~25 of 120 columns.
9. **The TUI itself provides a placement precedent:** at the right edge (around
   column 103) it draws `● high · /effort`, and the banner reads
   `Sonnet 5 with high effort · Claude Max`. Right alignment is the native style.

### Where the model and effort come from

Subagents in 2.1.273 are **no longer sidechain rows**: `isSidechain` is `false`
on all 9,433 session rows. They have their own files:

```
~/.claude/projects/<proj>/<sessionId>/subagents/
    agent-<agentId>.jsonl        # transcript
    agent-<agentId>.meta.json    # spawn record
```

| Source | Model | Effort |
|---|---|---|
| `agent-<id>.meta.json` | no (`agentType`, `description`, `toolUseId`, `spawnDepth`, `requestShape`) | no |
| `agent-<id>.jsonl`, assistant rows | **yes — `.message.model`** (authoritative) | `perTurnEffort` exists, but is **always null** |
| Agent tool input in the parent | intent only | no |
| `~/.claude/settings.json` | session model only | no; a default key for subagents **does not exist** |

- Observed slugs: `claude-sonnet-5`, `claude-opus-5`,
  `claude-haiku-4-5-20251001`, `claude-fable-5-1`, `claude-opus-5[1m]`
  (the `[1m]` variant is encoded in the model string itself).
- **The tool input lies.** Two forks were spawned with `"model":"sonnet"`, but
  ran on `claude-opus-5`—forks silently ignore the override. Rendering from
  spawn input would display a lie.
- **Subagent effort is currently unreachable.** `perTurnEffort` is null on all
  9,520 subagent rows on the machine; it is non-null in exactly 159 rows of the
  main session on `claude-fable-5-1` (`"high"`). The `sonnet-5/xhigh` format is
  possible only if effort appears at all.
- **The tree can be reconstructed exactly:** `meta.json.toolUseId` matches the
  `tool_use` id in the *parent's* transcript (verified at `spawnDepth:2`: its
  `toolUseId` was found in another `agent-*.jsonl`, not the root).
- **Delay:** `meta.json` is written at spawn time, without the model; the model
  arrives with the first assistant row—**~3.1 s** for a fresh agent and **0 s**
  for a fork. The overlay must survive the “type known, model not yet known” window.

### What the wrapper lacks

`strip_ansi` (909) collapses cursor movements into newlines—it is a trailing
text buffer, not a cell grid, so it cannot tell which screen row currently holds
an agent. A full terminal emulator has already been written and tested, but
lives **only in tests** (`test/screen.py`: CUP, CUU/CUD/CUF/CUB, CHA, ED/EL,
SGR, DECSC/DECRC, deferred wrap, scroll counter). It is not in the supervisor.

## What to do

1. **Bring the screen emulator into the supervisor.** Move `test/screen.py` into
   the `CR_PY` heredoc as the `Screen` class; leave `test/screen.py` as a thin
   import via `--cr-dump-python`, so there is one source. Add what is missing and
   actually occurs: `ESC[?2026h/l` (frame boundaries), `ESC[?25l/h`,
   `IL`/`DL` (`ESC[L`/`ESC[M`), `ICH`/`DCH`, and the scroll region
   (`ESC[r` + `IND`/`RI`). Feed it the same `data` sent to
   `write_all(stdout_fd, data)` (4083), after `split_escape_tail` (3720).
   Disable it completely: without the overlay the emulator is not created and
   bytes are not processed.

2. **Recognize tree rows in the grid, not in bytes.** Add
   `CR_AGENT_ROW_PATTERNS` next to `CR_ROSTER_PATTERNS` (220) and the
   `"agent_row"` key in `PAT` (870), exported as `CR_PAT_AGENT_ROW` (4303–4309) —
   so an upstream rendering change can be fixed with an environment variable,
   without a release. `find_agent_rows(screen)` returns `[(row, label, col_label)]`:
   a `├`/`└`/`│`/`⎿` glyph in column 4 and a non-empty label from column 6. `⎿`
   rows (children) are not annotated—they have no agent of their own.

3. **Link a row to an agent by label.** `SubagentRegistry` reads
   `<sessionId>/subagents/agent-*.meta.json` for the attached session and builds
   `description → agentId`. The model comes from the last assistant row in
   `agent-<id>.jsonl` (`.message.model`)—**only from there**. Poll by mtime, like
   `TranscriptWatcher`, no more often than `CR_AGENTS_POLL_SEC` (default 1.0).
   A label collision (two agents with the same `description`) means both rows
   show `?`, not a guessed model.

4. **Label format.** `model_label(slug, effort)`:
   `claude-sonnet-5` → `sonnet-5`, `claude-haiku-4-5-20251001` → `haiku-4.5`,
   `claude-opus-5[1m]` → `opus-5[1m]`. Effort is the `/high` suffix when it was
   actually read, `/?` when the model is known but effort is not (today, always),
   and simply `…` when neither model is known (the first ~3 s of an agent's life).
   Lying is forbidden: `model` from tool input is not used as a value; at most it
   can serve as temporary `~sonnet`, with the tilde explicitly meaning “claimed,
   not confirmed”.

5. **Render.** `AgentOverlay.paint()` following `Badge.paint` (3664):
   `DECSC` → for each row `CUP(row, cols - width)` → `SGR` → text →
   `ESC[0m` → `DECRC`; never touch the last cell of a row (`Badge.place`, 3645:
   writing to it causes wrapping and scrolls the screen).
   Do not render an annotation when the row's own text reaches
   `cols - width - 1`. The redraw trigger is **frame closure `ESC[?2026l`**, not
   quietness: because of `ESC[K` (evidence 7), the label must return after every
   frame or it will blink. Keep a registry of “what was drawn where” so a moved
   row can be erased just as `Badge.painted_width` erases a shortened badge.

6. **Do not fight the badge.** The badge at `bottom-right` and the right
   annotation on the bottom row occupy the same cell. `AgentOverlay` yields: it
   does not annotate a row occupied by the badge.

7. **Configuration.** `CR_AGENTS_OVERLAY` (default `0`—interference with a
   another TUI is enabled deliberately), `CR_AGENTS_POS` (`right`|`label`, default
   `right`; `label` appends before the label and is provided in case the right
   edge is occupied), `CR_AGENTS_POLL_SEC`, and `CR_PAT_AGENT_ROW`. All appear
   in `--cr-help`.

8. **Test fake.** `test/fake_claude.py` has neither a tree nor subagents. Add a
   scenario reproducing evidence 5 verbatim (the same relative movements,
   `ESC[6G`, `ESC[K`, and `?2026h/l` wrapper) and writing the corresponding
   `subagents/agent-*.{jsonl,meta.json}`—without this, there is nothing with which
   to test the overlay in CI.

## Acceptance criteria

- [ ] `test_screen.py`: the supervisor emulator (via `--cr-dump-python`) runs
      `test/fixtures/agent-tree-2.1.273.bin` and produces a grid where
      tree rows appear where the user sees them; `?2026h/l`, `ESC[L`/`ESC[M`,
      and the scroll region are covered by separate cases.
- [ ] `test_screen.py`: `test/screen.py` and `Screen` in `agent-retrier.sh` are
      the same code (the test fails on divergence).
- [ ] `test_agents.py`: `find_agent_rows` on the grid from evidence 5 returns
      exactly two rows with labels `Report first file in cwd` and
      `Report second file in cwd`; the `⎿ Initializing…` row is not returned.
- [ ] `test_agents.py`: `model_label` returns `sonnet-5/?`, `haiku-4.5/?`,
      `opus-5[1m]/?`; with read effort — `fable-5.1/high`; before the first
      assistant row — `…`; on a label collision — `?`.
- [ ] `test_agents.py`: the model comes from `agent-<id>.jsonl`, not tool input—
      an agent spawned with `"model":"sonnet"` and running on `claude-opus-5`
      shows `opus-5`, not `sonnet-5` (a regression test for a real fork case).
- [ ] `test_pty.py`: through `Screen`, `sonnet-5/?` is visible at the right edge of the
      agent row; the last column is empty; `screen.scrolled == 0` throughout.
- [ ] `test_pty.py`: after a frame closed by `ESC[?2026l` erases the row
      through `ESC[K`, the label returns to its place within one frame.
- [ ] `test_pty.py`: `CR_AGENTS_OVERLAY=0` produces no extra bytes in stdout
      compared with a run without subagents.
- [ ] `test_badge.py`: with `badge_pos=bottom-right`, the badge row
      is not annotated.
- [ ] `./test/run.sh` is green; `./test/codegraph-sync.sh` has been run.

## Where in the code

`write_all(stdout_fd, data)` (4083) and the surrounding loop (4075–4089) — insertion point;
`split_escape_tail` (3720); `strip_ansi` (909); `PAT` (870) and
`CR_ROSTER_PATTERNS` (220) + export (4303–4309); `Badge` (3560) — example:
`due` (3623), `place` (3645), `sequence` (3655), `paint` (3664), `erase` (3688);
`get_winsize` (3789) and `SIGWINCH` handling (3927–3934); `TranscriptWatcher` —
an mtime-polling example; `test/screen.py`; `test/fake_claude.py`.

## Open questions (resolve during implementation)

- **Effort discrepancy.** Parsing `subagents/*.jsonl` gives `perTurnEffort` as
  always null; meanwhile, the parent transcript contains a top-level row key
  `effort` with value `'high'`. Check which key is live and for which rows.
  Until resolved, use `/?`; this does **not** block the task.
- **The agent panel opens with `←`, not `↓`** (footer:
  `⏵⏵ auto mode on … · ← for agents`), although the collapsed row says
  `(↓ to manage)`. The panel rendering itself is absent from the capture. A
  second capture is needed: what the expanded panel looks like and whether the
  same `find_agent_rows` applies to its rows.
- **Slug shortening in the label** overlaps with `display` in `MODEL_PROFILES`
  (T18). This task uses a local `model_label`; when T18 is implemented, merge
  it into the profile table instead of keeping two.

## Extension (candidate for a separate task, not part of AC)

The user's real question is “where am I spending money?”, while the model is
only an indirect signal. `agent-<id>.jsonl` contains usage rows, so accumulated
tokens (and estimated cost) for each agent can be obtained with the same read
already performed in item 3. A second label field (`sonnet-5/? · 12k`) would be
cheap, but is split out separately so T27 does not expand.
