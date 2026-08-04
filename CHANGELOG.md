# Changelog

Every released version, newest first. The section for a tag is what GitHub shows
as that release's notes — `.github/workflows/release.yml` reads it straight out
of this file, so a release cannot describe itself differently from here.

The version in `claude-retrier.sh` (`CR_VERSION`) must match the newest entry
below; the test suite checks it.

## [1.5.0] - 2026-08-04

The other half of the 1.3.0 fix, found the same way: a session that had waited
out a four-hour limit, reached the reset, and then never typed anything.

### Fixed
- `deferring retry: user is typing` once every 15 seconds while nobody was
  touching the keyboard. 1.3.0 taught the wrapper that the terminal's replies to
  claude are not a draft, but every one of them still stamped "the human is
  here", and that gate wants twenty quiet seconds. A cursor-position report, a
  focus event from switching windows, a mouse move over the terminal — any of
  them, arriving oftener than that, held the retry for as long as the session
  lived. Presence now means a key: replies are told from keystrokes by shape
  (the string replies, `CSI…R`, a private `CSI ?…`, `CSI…c`, `CSI…t`, focus and
  mouse reports, the paste brackets), and everything unrecognised stays human,
  because mistaking a key for a report is the expensive direction.
- The keyboard gate now has a ceiling (`CR_TYPING_MAX_SEC`, 15 minutes). With an
  empty input box there is no half-written thought behind it, only the courtesy
  of not typing while someone is — and whatever stamps presence next, the retry
  still has to happen. A draft is untouched by this and keeps its own, longer
  grace.

### Changed
- The badge says `◆ cr held` while a retry is being deferred. Each deferral
  re-arms the clock by 15 seconds, so what the corner used to show was a
  countdown restarting from 15s forever — indistinguishable from waiting out a
  quota, which is the one thing it no longer meant.
- A narrower badge frame now covers the wider one it replaces. `◇ cr 1m` giving
  way to `◆ cr` left `◇ c◆ cr` in the corner until claude next repainted that
  row.

## [1.4.0] - 2026-08-03

### Fixed
- A weekly limit was detected, the account was switched with `/login`, and the
  session went back to work — while the wrapper kept counting down its 48 hours
  over it, ready to type `continue` into the middle of that work. Nothing
  announces "your quota is back": not the transcript, not the render. What says
  it is that claude is answering again, so a wait now ends on either of two
  sightings — an ordinary assistant record in the transcript, or the working
  footer running for `CR_RESUME_SEC` (15s) without a break. A refused turn still
  paints a second or two of footer before the banner lands, which is why a
  flicker is not enough, and rows written within eight seconds of the banner are
  taken as belonging to it.
- Cancelling a wait clears the rolling screen window with it. The banner is
  still in there, and it would otherwise be re-detected the moment the
  controller went idle and park the session all over again.

## [1.3.0] - 2026-08-02

Two field failures from the same evening, both of them the wrapper reading the
terminal too literally.

### Fixed
- A session waited out its reset and then deferred the retry every 15 seconds
  for three hours, logging `unsent text in the prompt box` while nobody had
  touched the keyboard. Not everything arriving on our stdin was typed: claude
  sends `\x1b[>q` at startup and the terminal's XTVERSION reply comes back the
  same way, where 15 of its bytes were counted as a draft. Only CSI and SS3 end
  at their first final byte — DCS, OSC, APC, PM and SOS run to a String
  Terminator, and an X10 mouse report carries three raw coordinate bytes after
  its `M`. All of them are now consumed whole, including when a read boundary
  cuts one in half.
- A draft nobody has touched for `CR_DRAFT_GRACE_SEC` (10 minutes) no longer
  blocks a retry. Whatever desyncs that counter next, the wait has to end.
- The retry landed, claude resumed — and the wrapper typed `continue` twice more
  and painted `cr stopped`. It was watching the footer for `esc to interrupt`,
  which Claude Code 2.1 no longer prints: the footer is now `✶ Nebulizing… `
  growing into `✻ Cogitating… 20m 57s · ↓ 6.8k tokens`. Every live session
  therefore looked idle.

### Added
- The transcript now confirms a retry as well as reporting a limit. claude
  writes our message back as a `user` row the moment it accepts it, which is
  direct proof the retry was submitted rather than left sitting in the input
  box — the question the verify step was trying to answer by reading pixels.
- `CR_DRAFT_GRACE_SEC`.

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
