# Fixtures

## `agent-tree-2.1.273.bin`, `agent-tree-2.1.273-collapsed.bin`

Raw bytes from the master end of the pty of a real `claude` 2.1.273 session,
captured on 2026-09-18 while investigating T27. The session was run in a
120×50 terminal and spawned two or three trivial Explore agents ("name the
first file in cwd").

This is the sole source of truth for how the TUI renders the subagent tree:
the rendering is differential and word-by-word (words are separated by
`ESC[<col>G`), so grep finds nothing in the bytes — the file must be run
through a screen emulator. See the "Evidence" section in
`docs/backlog/T27-subagent-model-overlay.md`.

Checked for credentials before committing.

`capture-agent-tree.py` — the driver used to capture them; it is also used to
make a new capture when upstream changes the rendering.

## `agents-panel-2.1.273.bin`

Raw bytes from the same real `claude` 2.1.273 session (120×50), captured on
2026-09-18 while investigating T29, but from a different screen: the
persistent subagent control panel, which opens with the `/tasks` command while
at least one agent is still running and does not close by itself (it closes
with `Esc`) — unlike the fleeting inline tree in
`agent-tree-2.1.273.bin`.

Live investigation established that the footer hint `← for agents` (in both
the normal and `manual` permission modes) opens a COMPLETELY DIFFERENT screen
— an inter-session roster (a list of other, unrelated sessions on the
machine) — the very one that `CR_ROSTER_PATTERNS` in `claude-retrier.sh`
deliberately never scrapes. The first capture attempt did briefly show other
people's content (emails, insurance, etc.); those bytes were never saved to
disk or committed. `/tasks` is the confirmed safe way to reach the panel for
the current session specifically.

Checked for credentials and other people's content before committing.

`capture-agents-panel.py` — the driver used to capture it (buffers output in
memory and never writes to disk until it confirms that the roster did not
appear); it is also used to make a new capture when upstream changes the
rendering.
