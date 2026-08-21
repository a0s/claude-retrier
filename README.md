<p align="center">
  <img src="docs/banner.webp" width="900"
       alt="A laptop at night showing 'limit reached - resets 3pm', and below it the wrapper typing 'continue'">
</p>

# claude-retrier

[![test](https://github.com/a0s/claude-retrier/actions/workflows/test.yml/badge.svg)](https://github.com/a0s/claude-retrier/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Auto-resume Claude Code after a usage limit. One shell script, no tmux, no daemon.

```sh
brew install a0s/claude-retrier/claude-retrier
claude-retrier                       # instead of: claude
```

When the session stops on `You've hit your session limit · resets 3pm`, the wrapper
waits until the reset and types `continue` for you. Everything else passes straight
through — keys, colours, resizes, exit codes.

It can also restart a session that is filling up its context window — fold it into
a file, `/clear`, unfold — but only if you ask it to; see
[Restarting a full context](#restarting-a-full-context).

## Install

**Homebrew** (macOS and Linux):

```sh
brew install a0s/claude-retrier/claude-retrier
```

**Or just take the file** — it is one self-contained script with no build step:

```sh
curl -fsSLO https://raw.githubusercontent.com/a0s/claude-retrier/main/claude-retrier.sh
chmod +x claude-retrier.sh
```

Every version is also attached to a
[release](https://github.com/a0s/claude-retrier/releases), with the notes for it
in [CHANGELOG.md](CHANGELOG.md).

Uninstall is `brew uninstall claude-retrier`, or deleting the file. Nothing else
was touched: no shell rc edits, no launch agents, no background process.

## Your claude, not `claude`

Most people do not run stock `claude` for long. There is a `claude-work` and a
`claude-personal`, or an alias in `~/.zshrc` that pins a model, or a function that
sets a settings file first. Name yours with `--cmd` and the wrapper runs it:

```sh
claude-retrier --cmd claude-work                    # binary, or a name on PATH
claude-retrier --cmd ~/bin/claude-personal          # a path to anything runnable
claude-retrier --cmd 'claude --model opus'          # a whole command line
claude-retrier --cmd my-claude-alias                # an alias from your ~/.zshrc
claude-retrier --cmd my-claude-function             # a shell function, likewise
```

An alias or a function exists nowhere except inside an interactive shell that has
read your rc file, so that is where the wrapper looks when the name is not a file
it can run directly — once, at startup, lifting out the definition so that the
session itself runs from a plain shell. `claude-retrier --cmd X --cr-dump-argv`
prints exactly what will be executed. Set `CR_CLAUDE_CMD` instead of passing the
flag every time:

```sh
alias claude='claude-retrier --cmd claude-work'     # in ~/.zshrc
export CR_CLAUDE_CMD=claude-work                    # or, once, in your env
```

Everything after the command is claude's own — `claude-retrier --cmd claude-work
--resume` resumes, and a bare prompt stays a prompt. With no `--cmd` at all the
wrapper finds `claude` the way your shell would.

## Resuming a session

Claude's own flags pass straight through, so whatever you would type after
`claude` you type after `claude-retrier` instead:

```sh
claude-retrier --resume deb786e8-3006-4edf-b5e6-2ca73e25620e   # claude --resume <id>
claude-retrier --continue                                      # the last session here
claude-retrier --cmd claude-work --resume deb786e8-3006-4edf-b5e6-2ca73e25620e
```

A resumed session is watched exactly like a fresh one: the wrapper follows the
transcript claude is already appending to, so a limit hit an hour into the
resumed conversation is picked up the same way.

## How it works

`claude-retrier.sh` runs your claude on a pty it owns, so it can both read the output
and write input. That single fact removes the need for tmux (`capture-pane` +
`send-keys`), a detached monitor process, event marker files, and a launchd/systemd
reconciler.

It detects a limit on two channels:

1. **The transcript** — Claude Code writes `{"error":"rate_limit","isApiErrorMessage":true}`
   into `~/.claude/projects/<project>/<session>.jsonl`. Structured, unambiguous, primary.
2. **The screen** — pattern matching, used only when the transcript is unavailable.
   One screen is never read this way: the `claude agents` roster, where every card
   is a different session's last line and a limit shown there is somebody else's,
   usually hours old.

Before typing anything it checks that Claude is not mid-turn and that you are not
typing yourself — it can see your keystrokes, so an unsent draft in the prompt box
is never overwritten.

A wait also ends when the limit does. Switch accounts with `/login`, upgrade the
plan, or simply get your quota back early: nothing announces any of that, so the
wrapper takes the session answering again as the answer, drops the countdown and
goes back to watching.

Nothing is installed into your shell, no background process is left behind, and the
only thing written under your home directory is the log.

## Restarting a full context

A session does not only stop because the quota ran out. It also fills up, and
then there is a ritual: ask Claude to write down where it got to, `/clear`, hand
the note to the fresh session. People do that by hand, several times a day, at
whatever moment they happen to notice the window filling up.

Set a threshold and the wrapper does it for you.

### Turning it on

One variable. It is off until you set it, and nothing below happens without it:

```sh
CR_CONTEXT_PCT=51 claude-retrier          # restart at 51% of the context window
```

Two more make it fit a project you actually work in:

```sh
export CR_CONTEXT_PCT=51
export CR_HANDOFF_FILE=scratchpad/RESUME.md      # relative to cwd — .gitignore it
export CR_RESUME_MSG='Read `scratchpad/RESUME.md` and carry on from it.'
```

Put those three in your shell rc, or in a `direnv` file for one repo, and there
is nothing else to run.

### What you will see

Nothing at all, until the session gets near the threshold. Then the badge in the
corner starts showing the percentage — `◆ cr 47%` — so you can tell whether the
number you picked is a sensible one before it ever fires.

When it does fire, four things are typed into your session, and the wrapper
prints a dim line before each so you are never wondering what just happened:

```
[claude-retrier] context is filling up; asking for a handoff
[claude-retrier] handoff verified; clearing the context
[claude-retrier] context cleared; unfolding the handoff
[claude-retrier] context restarted: 700k down to 5k
```

Behind those, `~/.claude-retrier/log` has the whole story with numbers:

```
claude-opus-5: a 1.0M context window (the model), restarting at 510k
context is 700k of a 1.0M window (70%, threshold 510k); folding up
asking for a handoff into scratchpad/RESUME.md (attempt 1/2, marker HANDOFF-4acfe679)
handoff accepted: 3417 bytes ending in HANDOFF-4acfe679, turn closed with end_turn
handoff verified; clearing the context with /clear
unfolding from scratchpad/RESUME.md
context restarted: 700k down to 5k
```

A minute or two of wall clock, nearly all of it spent waiting for Claude to
finish writing the file and for the transcript to fall quiet afterwards.

### The four steps

1. **Fold.** `CR_HANDOFF_MSG` asks Claude to stop, start nothing new, write a
   complete handoff into `CR_HANDOFF_FILE`, and finish that file with a one-time
   marker.
2. **Check.** The next section — it is the whole design.
3. **`/clear`.** Claude Code's own command. The process, the pty, the MCP
   connections and the warm prompt cache all stay; only the history goes.
4. **Unfold.** `CR_RESUME_MSG` points the fresh session at the file.

Nothing is counted on this side. Every assistant row in the transcript carries
the API's own `usage`, and `input + cache_creation + cache_read` is the prompt
that was sent — the check rides on a row the wrapper had already parsed, so it
costs two comparisons and happens only when the transcript actually grew. The
denominator comes from the model slug in the same row.

### Why `/clear` is the last thing it will do

Clearing a session that was not folded up loses the work with nothing written
down, so `/clear` goes out only when four independent things agree:

- the handoff file **ends with the marker generated for this attempt** — proof
  the write ran to the end, where "done" in the chat would only be proof that
  the model believes it did. The marker is different every time, so one left
  behind by a previous attempt cannot be mistaken for this one's;
- the runtime recorded the turn as `end_turn`, not `max_tokens` (cut off by
  length) or `refusal`;
- the file is newer than the request for it and over `CR_HANDOFF_MIN_BYTES`;
- the session's own transcript has stopped growing for `CR_ROOT_IDLE_SEC` —
  which is how "the turn is over" is asked here, because in a session that keeps
  background work running the screen never goes quiet.

Any of them missing and the fold is asked for again, then given up on. Giving up
leaves the session untouched: it can still fall back on Claude Code's own
compaction, which is a far better outcome than a history thrown away on a
promise. If `/clear` did go out and the context did not actually fall, the
feature switches itself off for the rest of the session rather than typing into
a full one for ever.

A usage limit landing in the middle **suspends** the restart rather than
cancelling it. Every clock it runs on stops for the duration — a weekly limit is
days long and would otherwise expire a fifteen-minute fold timeout from the
inside — its attempt budget is not spent on the world's problems, and when the
quota comes back the step that was interrupted is re-sent. `continue` is the
wrong instruction at every step of a restart but the last one.

Background agents keep running across a restart, which is what you want and why
nothing here waits for them: idle is measured on the session's own transcript,
and work started elsewhere writes its own.

### Writing your own phrases

The two phrases are yours. `{file}` is substituted in both and `{marker}` in the
folding one, and each must be a single line, because a newline submits it.

```sh
export CR_HANDOFF_MSG='Stop here, start nothing new, and write everything the next session needs into `{file}` — it will not remember this one. Last line of that file: {marker}, alone, written after the rest.'
export CR_RESUME_MSG='/my-skill continue from `scratchpad/RESUME.md`'
```

If you write your own, keep three things in it. **No new work** — the session is
about to end and anything started now is lost. **"for a session that will not
remember this one"** — without it you get notes that only make sense to someone
who was there. And **the marker as the last line of the file**, written last:
that is the only thing standing between a half-written note and a cleared
session.

A slash command works as a resume phrase; it goes out with the extra care
described under `CR_SLASH_ENTER` below.

### When nothing happens

Look in `~/.claude-retrier/log`. In order of likelihood:

- **no `context restart armed` line at all** — `CR_CONTEXT_PCT` did not reach
  the wrapper. Check it is exported, and that your `--cmd` wrapper is not
  starting claude in a scrubbed environment.
- **`restart step held: …`** — working as intended. It will not type over you
  mid-sentence, and it will not interrupt a turn that is still running.
- **`a 200k context window` for a model you expected to have 1M** — the line
  says where the figure came from: an unfamiliar model slug, or
  `CLAUDE_CODE_DISABLE_1M_CONTEXT`. Name the window yourself with
  `CR_CONTEXT_WINDOW=1M`.
- **`restart aborted at handoff_sent: …`** — the fold did not produce a usable
  file, and the message names which of the four checks failed. The session was
  not touched.
- **the percentage in the badge never moves** — the wrapper reads the figures
  off assistant rows, so it has nothing to show until the session answers
  something. A transcript that already existed when the wrapper started is
  seeded, not replayed, so a `--continue` session reports its size from its next
  turn rather than immediately.

### Settings

| variable | default | |
|---|---|---|
| `CR_CONTEXT_PCT` | `0` | restart at this % of the window; `0` is off |
| `CR_CONTEXT_TOKENS` | `0` | absolute threshold (`500k` is fine); beats the % |
| `CR_CONTEXT_WINDOW` | `auto` | `auto` \| `200k` \| `1M` \| a number |
| `CR_HANDOFF_FILE` | `.claude-retrier/handoff.md` | where the fold is written |
| `CR_HANDOFF_MSG` | (see `--cr-help`) | the folding phrase; `{file}`, `{marker}` |
| `CR_RESUME_MSG` | ``Read `{file}` and continue from it.`` | the unfolding phrase |
| `CR_CLEAR_CMD` | `/clear` | |
| `CR_HANDOFF_MARKER` | `HANDOFF` | prefix; a nonce is appended to it |
| `CR_HANDOFF_MIN_BYTES` | `200` | a shorter file is not a handoff |
| `CR_HANDOFF_ATTEMPTS` | `2` | folds attempted before giving up |
| `CR_ROOT_IDLE_SEC` | `20` | transcript quiet this long ⇒ the turn is over |
| `CR_HANDOFF_TIMEOUT_SEC` | `900` | per step, and frozen while a limit runs |
| `CR_STEP_GAP_SEC` | `3` | between `/clear` and the resume phrase |
| `CR_CONTEXT_COOLDOWN_SEC` | `600` | silence after any restart |
| `CR_CONTEXT_MAX_CYCLES` | `0` | `0` = no cap; a fuse against a loop |
| `CR_SLASH_ENTER` | `2` | Enters sent for a `/command` |

**Picking a threshold.** Half the window is a good place to start: it leaves the
folding turn plenty of room to think and to read files, which is exactly the
turn you do not want cramped. Much above 80% and the fold itself starts
struggling for space; much below 30% and you restart more often than you get
work done. Watch the badge for a day and move it.

**`CR_CONTEXT_WINDOW=auto`** reads the model slug out of the transcript and looks
it up. It narrows to 200k if `CLAUDE_CODE_DISABLE_1M_CONTEXT` or
`CLAUDE_CODE_MAX_CONTEXT_TOKENS` is set in the environment claude is started
with, and widens if the session is ever seen past the window it assumed —
guessing small only restarts a little early, guessing large never restarts at
all. Name a number if your setup narrows the window some way the wrapper cannot
see.

**`CR_SLASH_ENTER`.** Typing a `/` opens Claude Code's command list, and in a TUI
that is a real hazard: Enter into an open list can pick the highlighted entry
instead of submitting what was typed. Measured against Claude Code 2.1.222, one
Enter runs `/clear` and there is no confirmation step — so a slash command gets a
longer pause (for the list to settle on the exact match) and then two Enters, the
second purely as insurance for a build that behaves differently. It costs
nothing: an Enter into an empty input box submits nothing, which is also
measured. `CR_SLASH_ENTER=1` turns it off.

Add the handoff file to your `.gitignore` — it is a scratch note about one
session, and it is rewritten from scratch every time.

## A sign of life

A wrapper you cannot see is indistinguishable from a wrapper that died an hour
ago. So there is one mark, dim, in a corner of the screen: `◆ cr` while it is
watching, the time left while it is waiting out a limit, and `◆ cr held` when the
reset has passed but you are still at the keyboard.

<p align="center">
  <img src="docs/badge.svg" width="620"
       alt="Two terminal frames: an idle session with a dim '◆ cr' in the bottom-right corner, and the same session after a limit, showing '◆ cr 1h59m'">
</p>

Nothing is reserved from Claude: the badge is painted over the finished frame in
the gaps between repaints, cursor saved and restored around it, and the last
column is left empty so it can never wrap the screen. Claude paints over it, it
comes back a moment later — about forty bytes, a few times a second at most, and
never a byte into the session itself.

```sh
CR_BADGE=0 claude-retrier                  # off
CR_BADGE_POS=top-right claude-retrier      # any of the four corners
CR_BADGE_LABEL=retrier claude-retrier      # your own word next to the mark
```

The picture above is not a mockup: `python3 docs/badge-shot.py` runs the real
wrapper over a stand-in that prints one Claude-shaped frame, replays what the
wrapper wrote through the terminal emulator the tests use, and renders the
screen that came out.

## Configuration

All optional, all environment variables:

| variable | default | |
|---|---|---|
| `CR_CLAUDE_CMD` | | your claude command (same as `--cmd`) |
| `CR_MESSAGE` | `continue` | what to type when the limit lifts |
| `CR_MARGIN_SEC` | `45` | extra wait past the stated reset time |
| `CR_MAX_ATTEMPTS` | `3` | sends per incident before giving up |
| `CR_USER_IDLE_SEC` | `20` | don't type while you are typing |
| `CR_TYPING_MAX_SEC` | `900` | …but not past this, with an empty input box |
| `CR_RESUME_SEC` | `15` | claude working this long during a wait ends it |
| `CR_DRAFT_GRACE_SEC` | `600` | an untouched draft this old stops blocking |
| `CR_SCRAPE` | `auto` | `auto` \| `always` \| `never` |
| `CR_BADGE` | `1` | `0` hides the corner mark |
| `CR_BADGE_POS` | `bottom-right` | also `bottom-left`, `top-right`, `top-left` |
| `CR_BADGE_LABEL` | `cr` | the word next to the mark |
| `CR_SHELL` | `$SHELL` | shell that knows your aliases |
| `CR_LOG` | `~/.claude-retrier/log` | |
| `CR_DISABLE` | | `1` runs plain claude |

The context-restart settings are a table of their own,
[above](#restarting-a-full-context). All of them do nothing until
`CR_CONTEXT_PCT` is set.

Detection patterns live in one array at the top of `claude-retrier.sh`; add a wording
and nothing else changes.

## Requirements

`bash` and `python3` (3.9+, standard library only). If either is missing, or claude
is invoked with `-p`, the wrapper execs claude unchanged — it never becomes the
reason your session won't start.

## Tests

```sh
./test/run.sh              # 310 tests: patterns, time parsing, transcript, state
                           # machine, the badge, custom commands, degradation, and
                           # end-to-end runs on a real pty (rendered through a
                           # terminal emulator, so "what the user sees" is asserted)
./test/run.sh --docker     # the same suite on Linux, from anywhere with docker
./test/run.sh test_time.py # just one file
```

## Limitations

- The screen-scraping fallback cannot tell a live banner from a session that is
  discussing one. It is off whenever the transcript is being written, which is
  the normal case.
- A weekly limit stated as a bare `resets Jul 22` with no year is assumed to be
  the next occurrence.
- An alias or function is read out of your rc file once, at startup, and run from
  a plain non-interactive shell afterwards. One that calls *another* alias defined
  in the same rc file will not find it. (bash 3.2, still what macOS ships as
  `/bin/bash`, cannot be asked for an alias body at all and falls back to running
  the alias through `bash -i`.)
- The context restart reads its figures from one transcript at a time — the one
  this terminal's session writes. Another live session under the same working
  directory can, briefly, be the file that grew last.
- Windows is not supported (no pty).

Prior art: [claude-auto-retry](https://github.com/cheapestinference/claude-auto-retry),
whose issue tracker supplied most of the edge cases tested here.

MIT.
