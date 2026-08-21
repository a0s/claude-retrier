# Changelog

Every released version, newest first. The section for a tag is what GitHub shows
as that release's notes — `.github/workflows/release.yml` reads it straight out
of this file, so a release cannot describe itself differently from here.

The version in `claude-retrier.sh` (`CR_VERSION`) must match the newest entry
below; the test suite checks it.

## [1.7.0] - 2026-08-21

A second trigger. The first one answers "the quota ran out"; this one answers
"the context window is filling up" — and it is off until you switch it on.

### Added
- **Context restart.** At `CR_CONTEXT_PCT` of the model's context window the
  wrapper asks Claude to fold the session into a file, checks that the file
  really was written, types `/clear`, and hands the file to the fresh session.
  It automates a ritual people were already doing by hand, several times a day,
  at whatever moment they happened to notice the window filling up.

  Nothing is counted on our side: every assistant row in the transcript carries
  the API's own `usage`, and `input + cache_creation + cache_read` is the prompt
  that was sent. The check rides on the row the watcher has already parsed, so
  it costs two comparisons and happens only when the file actually grew. The
  denominator comes from the model slug in the same row, narrowed by
  `CLAUDE_CODE_DISABLE_1M_CONTEXT` or `CLAUDE_CODE_MAX_CONTEXT_TOKENS` if either
  is set, and raised if the session is ever seen past it.

  `/clear` throws a session's history away, so it goes out only when four
  independent things agree: the handoff file ends with a one-time marker that
  was generated for this attempt (proof the write ran to the end, not that the
  model believes it did); the runtime recorded the turn as `end_turn` rather
  than `max_tokens` or `refusal`; the file is newer than the request and over a
  size floor; and the session's own transcript has stopped growing. Any of them
  missing and the fold is asked for again, then abandoned — with the session
  left exactly as it was, because falling back on Claude Code's own compaction
  is a far better outcome than a history cleared on a promise.

  A usage limit landing in the middle suspends the restart instead of cancelling
  it: every clock it runs on stops for the duration, its attempt budget is not
  spent on the world's problems, and when the quota returns the step that was
  interrupted is re-sent — `continue`, which is what the limit path types, is
  the wrong instruction at every step of a restart but the last.

  Off by default (`CR_CONTEXT_PCT=0`). Existing installs behave exactly as they
  did.

- `CR_HANDOFF_FILE`, `CR_HANDOFF_MSG`, `CR_RESUME_MSG`, `CR_CONTEXT_WINDOW`,
  `CR_CONTEXT_TOKENS`, `CR_HANDOFF_ATTEMPTS`, `CR_ROOT_IDLE_SEC`,
  `CR_CONTEXT_COOLDOWN_SEC`, `CR_CONTEXT_MAX_CYCLES` and the rest of the knobs,
  all listed in the README.

- The corner badge shows the context percentage once the threshold is in sight,
  and names the step while a restart is running. It is the only way to find out
  whether the threshold you picked is a sensible one.

### Changed
- A message beginning with `/` is typed as a command rather than as prose:
  a longer pause after the text, so Claude Code's command list can settle on the
  exact match, and two Enters. The second submits if the first only completed
  the highlighted entry, and lands in an empty input box if it did not — where
  Claude Code ignores it. `CR_SLASH_ENTER=1` for a build that does not need it.
- The transcript watcher says which file each row came from, and which of the
  growing files belongs to the session at this terminal. A limit is the
  account's and never cared; a context reading taken from another session's
  transcript would be a restart at the wrong moment, or none at all.
- A subagent's rows are marked as such. Its work is the session's work, so it
  holds a restart back — but its context is its own and is not read as the
  session's.

## [1.6.0] - 2026-08-06

What `claude agents` did to the scraper, found in a session that sat out a
five-hour wait for a limit that had lifted five minutes after it started.

### Fixed
- The roster (`claude agents`) painted another session's three-hour-old card —
  `You've hit your session limit · resets 9:30pm … 3h` — and the wrapper read it
  as its own live banner, parking the terminal until half past nine while the
  real reset (3:40pm) came and went. A roster is a list of OTHER sessions and
  has no input box worth typing `continue` into, so a screen showing one is no
  longer scraped at all. The transcript channel is untouched: a limit hit by
  this session's own claude still arrives structured.
- A full-screen TUI positions the cursor instead of printing rows, and the
  roster reached the scraper with not one `\n` in it. Stripping the escapes left
  the whole screen as a single line, where any limit wording pairs with any
  reset wording — that is how a card's clock time was attached to a different
  card's banner. Cursor motions and carriage returns are now line breaks, so the
  pairing rule sees the rows the eye sees.
- The badge froze. It waits for a gap in claude's output before painting over a
  finished frame, and the roster animates about ten times a second, so the gap
  never came and the corner kept whichever frame it drew first — a countdown
  that does not count, which reads as a dead wrapper. The wait for the gap is
  now bounded (2s), after which it paints into the traffic and lets the next
  repaint tidy up.

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
