# Changelog

Every released version, newest first. The section for a tag is what GitHub shows
as that release's notes — `.github/workflows/release.yml` reads it straight out
of this file, so a release cannot describe itself differently from here.

The version in `claude-retrier.sh` (`CR_VERSION`) must match the newest entry
below; the test suite checks it.

## [1.2.0] - 2026-08-01

### Added
- A dim badge in a corner of the terminal: `◆ cr` while the session is being
  watched, a countdown while a limit is being waited out, and the attempt number
  while a retry is being confirmed. It is painted over Claude's finished frame in
  the gaps between repaints — nothing is reserved from the TUI, the cursor and
  colour are restored around every write, and the last column is left empty so it
  can never wrap the screen. `CR_BADGE=0` turns it off; `CR_BADGE_POS` picks the
  corner and `CR_BADGE_LABEL` the word.
- `docs/badge-shot.py`, which regenerates the README picture by running the real
  wrapper and rendering what it actually wrote to the terminal.

### Fixed
- The suite no longer measures the caller's session: `CR_*` and
  `CLAUDE_RETRIER_ACTIVE` are stripped from the environment before each wrapper
  under test is started. Running `./test/run.sh` from inside a wrapped session
  used to make every wrapper degrade to a plain exec and the tests pass or fail
  for the wrong reason.

### Internal
- `test/screen.py`: a small terminal emulator, so end-to-end tests can assert on
  the screen a user would see rather than on the byte stream.

## [1.1.0] - 2026-08-01

### Added
- `--cmd` (and `CR_CLAUDE_CMD`): run *your* claude — a binary, a path, a name on
  PATH, an rc-file alias, a shell function, or a whole command line.
- `--cr-dump-argv`, which prints exactly what will be executed.

### Fixed
- An interactive shell is no longer left inside the pty: the alias or function is
  lifted out once, at startup, and the session runs from a plain shell.
- A shell whose rc file asks a question can no longer hang the wrapper forever;
  the probe times out and says what to do about it.

## [1.0.0] - 2026-08-01

### Added
- Single-file, tmux-free auto-resume for Claude Code: the wrapper runs claude on
  a pty it owns, detects a usage limit through the transcript (primary) or the
  screen (fallback), waits out the stated reset, and types `continue` once the
  session is idle and the human is not mid-sentence.

[1.2.0]: https://github.com/a0s/claude-retrier/releases/tag/v1.2.0
[1.1.0]: https://github.com/a0s/claude-retrier/releases/tag/v1.1.0
[1.0.0]: https://github.com/a0s/claude-retrier/releases/tag/v1.0.0
