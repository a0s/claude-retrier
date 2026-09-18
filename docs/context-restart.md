# Restarting a full context

Opt-in: at a threshold you pick, the wrapper asks the session for a handoff
file, verifies it, runs `/clear` and points the fresh session at the file.

[← back to README](../README.md)

- [Turning it on](#turning-it-on)
- [What you will see](#what-you-will-see)
- [The four steps](#the-four-steps)
- [Why `/clear` is the last thing it will do](#why-clear-is-the-last-thing-it-will-do)
- [Writing your own phrases](#writing-your-own-phrases)
- [Choosing a threshold](#choosing-a-threshold)
- [The context window](#the-context-window)
- [Slash commands and `CR_SLASH_ENTER`](#slash-commands-and-cr_slash_enter)
- [When nothing happens](#when-nothing-happens)
- [Caveats](#caveats)
- [Settings](#settings)

The other way a session stops is by filling up its context window, and then
there is a ritual: ask Claude to write down where it got to, `/clear`, hand the
note to the fresh session. People do that by hand, several times a day, at
whatever moment they happen to notice.

Set a threshold and the wrapper does it for you — on claude and on codex, each
with a threshold of its own ([codex details](codex.md#context-restart-on-codex)).

## Turning it on

The context restart is opt-in, because it clears a session's history and nobody
should get that by accident. One variable. It is off until you set it, and
nothing below happens without it:

```sh
CR_CONTEXT_PCT=51 claude-retrier          # restart at 51% of the context window
```

`CR_CONTEXT_RESTART=1` is the same thing without having to pick a number: it
turns the restart on at 51% (`DEFAULT_RESTART_PCT`, half the window and this
project's own long-standing recommendation) for claude, unless `CR_CONTEXT_PCT`
or `CR_CONTEXT_TOKENS` says otherwise. Codex does **not** inherit that 51% —
its own hard cap and reserve already give it a number of its own, tuned for
that cap rather than borrowed from claude's window; see
[codex](codex.md#context-restart-on-codex) for what actually decides codex's
threshold under this flag.

Two more make it fit a project you actually work in:

```sh
export CR_CONTEXT_PCT=51
export CR_HANDOFF_FILE=scratchpad/RESUME.md      # relative to cwd, .gitignore it
export CR_RESUME_MSG='Read `scratchpad/RESUME.md` and carry on from it.'
```

Put those three in your shell rc, or in a `direnv` file for one repo, and there
is nothing else to run.

Add the handoff file to your `.gitignore`. It is a scratch note about one
session and it is rewritten from scratch every time.

## What you will see

Nothing at all, until the session gets near the threshold. Then the badge in the
corner starts showing the percentage, `◆ cr 47%`, so you can tell whether the
number you picked is a sensible one before it ever fires.

When it does fire, four things are typed into your session, and the wrapper
prints a dim line before each of them so you are never left wondering what just
happened:

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

The whole thing takes a minute or two, nearly all of it spent waiting for Claude
to finish writing the file and for the transcript to fall quiet afterwards.

## The four steps

1. **Fold.** `CR_HANDOFF_MSG` asks Claude to stop, start nothing new, write a
   complete handoff into `CR_HANDOFF_FILE`, and finish that file with a one-time
   marker.
2. **Check.** The next section, which is the whole design.
3. **`/clear`.** Claude Code's own command. The process, the pty, the MCP
   connections and the warm prompt cache all stay; only the history goes.
4. **Unfold.** `CR_RESUME_MSG` points the fresh session at the file.

Nothing is counted on this side. Every assistant row in the transcript carries
the API's own `usage`, and `input + cache_creation + cache_read` is the prompt
that was sent. The check rides on a row the wrapper had already parsed, so it
costs two comparisons and happens only when the transcript actually grew. The
denominator comes from the model slug in the same row.

## Why `/clear` is the last thing it will do

Clearing a session that was not folded up loses the work with nothing written
down, so `/clear` goes out only when four independent things agree:

- the handoff file **ends with the marker generated for this attempt**, which is
  proof the write ran to the end. "Done" in the chat would only be proof that
  the model believes it did. The marker is different every time, so one left
  behind by a previous attempt cannot be mistaken for this one's;
- the runtime recorded the turn as `end_turn`, not `max_tokens` (cut off by
  length) or `refusal`;
- the file is newer than the request for it and over `CR_HANDOFF_MIN_BYTES`;
- the session's own transcript has stopped growing for `CR_ROOT_IDLE_SEC`. That
  is how "the turn is over" is asked here, because in a session that keeps
  background work running the screen never goes quiet.

(On codex, "the turn finished" and "mid-turn" are read off the rollout's own
turn rows instead — see [codex](codex.md#how-it-differs-from-claude-underneath).)

If any of them is missing the wrapper asks for the fold again, and then gives
up. Giving up leaves the session untouched: it can still fall back on Claude Code's own
compaction, which is a far better outcome than a history thrown away on a
promise. If `/clear` did go out and the context did not actually fall, the
feature switches itself off for the rest of the session rather than typing into
a full one for ever.

A usage limit landing in the middle suspends the restart rather than cancelling
it. Every clock it runs on stops for the duration, because a weekly limit is
days long and would otherwise expire a fifteen-minute fold timeout from the
inside. Its attempt budget is not spent on the world's problems either, and when
the quota comes back the step that was interrupted is re-sent. `continue` is the
wrong instruction at every step of a restart but the last one.

Background agents keep running across a restart, which is what you want and why
nothing here waits for them. Idle is measured on the session's own transcript,
and work started elsewhere writes its own.

## Writing your own phrases

The two phrases are yours. `{file}` is substituted in both and `{marker}` in the
folding one, and each must be a single line, because a newline submits it.

```sh
export CR_HANDOFF_MSG='Stop here, start nothing new, and write everything the next session needs into `{file}` because it will not remember this one. Last line of that file: {marker}, alone, written after the rest.'
export CR_RESUME_MSG='/my-skill continue from `scratchpad/RESUME.md`'
```

If you write your own, keep three things in it. No new work, because the session
is about to end and anything started now is lost. "For a session that will not
remember this one", without which you get notes that only make sense to someone
who was there. And the marker as the last line of the file, written last: that
is the only thing standing between a half-written note and a cleared session.

A slash command works as a resume phrase. It goes out with the extra care
described under [`CR_SLASH_ENTER`](#slash-commands-and-cr_slash_enter) below.

A command is not portable between agents, though — `/my-skill` above is a
Claude Code skill, and codex has never heard of it. Running both agents in the
same project with `CR_HANDOFF_FILE` shared (it can be — it is just a path) and
a command in `CR_HANDOFF_MSG` or `CR_RESUME_MSG` needs
`CR_CLAUDE_HANDOFF_MSG`/`CR_CODEX_HANDOFF_MSG` and
`CR_CLAUDE_RESUME_MSG`/`CR_CODEX_RESUME_MSG` instead: set for one agent only,
each overrides the shared phrase for that agent alone, and the other keeps
using it unchanged. `CR_CLAUDE_CLEAR_CMD`/`CR_CODEX_CLEAR_CMD` exist for the
same reason, though `/clear` itself works on both.

## Choosing a threshold

Half the window is a good place to start for a threshold. It leaves the folding
turn plenty of room to think and to read files, which is exactly the
turn you do not want cramped. Much above 80% and the fold itself starts
struggling for space; much below 30% and you restart more often than you get
work done. Watch the badge for a day and move it.

`CR_CONTEXT_TOKENS` sets an absolute threshold instead (`500k` is fine), and it
beats the percentage.

One model behaving differently from the rest of its own fleet does not need a
whole new threshold for everyone: `CR_CLAUDE_TOKENS_<SLUG>` and
`CR_CODEX_TOKENS_<SLUG>` set an absolute threshold for one model by name —
`<SLUG>` is that model's slug, uppercased, with anything that is not a letter
or digit turned into `_` (`claude-opus-5` → `CLAUDE_OPUS_5`, `gpt-5.6-sol` →
`GPT_5_6_SOL`). It outranks the percentage and `CR_CONTEXT_TOKENS` both, but
only for that one model — every other model still reads off whichever of those
two is set.

```sh
export CR_CLAUDE_TOKENS_CLAUDE_HAIKU_4_5=90000   # this one model folds sooner
```

## The context window

`CR_CONTEXT_WINDOW=auto` reads the model slug out of the transcript and looks
it up. It narrows to 200k if `CLAUDE_CODE_DISABLE_1M_CONTEXT` or
`CLAUDE_CODE_MAX_CONTEXT_TOKENS` is set in the environment claude is started
with, and it widens if the session is ever seen past the window it assumed.
Name a number if your setup narrows the window some way the wrapper cannot see.
(On codex the window is read from the rollout, and `CR_CONTEXT_WINDOW` is not
needed.)

A model the built-in table does not list is not guessed at. A point release
resolves to its family (`claude-fable-5-1` is whatever `claude-fable-5` is), and
anything left over is looked up: the Models API when `ANTHROPIC_API_KEY` is set
— a Claude subscription is not an API key, so most sessions skip this — and the
published models table otherwise. That happens in a worker thread, so nothing
waits on it, and the answer is cached in `CR_MODEL_CACHE` for a week. Until it
arrives the percentage trigger is disarmed and the corner says `cr window?`;
`CR_MODEL_LOOKUP=0` keeps the wrapper entirely offline, and then an unknown
model needs `CR_CONTEXT_WINDOW` or `CR_CONTEXT_TOKENS` from you.

This is the one thing in the wrapper that talks to the network, and only ever
about a model name: it sends a slug and reads back a number. Guessing instead is
what this replaced — assuming 200k for a slug that turned out to be a 1M model
folded a session that was 12% full.

## Slash commands and `CR_SLASH_ENTER`

`CR_SLASH_ENTER` exists because typing a `/` opens Claude Code's command list, and in a TUI
that is a real hazard: Enter into an open list can pick the highlighted entry
instead of submitting what was typed. Measured against Claude Code 2.1.222, one
Enter runs `/clear` and there is no confirmation step. So a slash command gets a
longer pause, letting the list settle on the exact match, and then two Enters,
the second purely as insurance for a build that behaves differently. That second
one costs nothing, because an Enter into an empty input box submits nothing,
which is also measured. `CR_SLASH_ENTER=1` turns it off.

## When nothing happens

Look in `~/.claude-retrier/log`. In order of likelihood:

- No `context restart armed` line at all: `CR_CONTEXT_PCT` never reached the
  wrapper. Check that it is exported, and that your `--cmd` wrapper is not
  starting claude in a scrubbed environment.
- `restart step held: ...` is working as intended. It will not type over you
  mid-sentence, and it will not interrupt a turn that is still running. On
  codex, `a turn is still running` can last as long as the turn does, however
  quiet it is — that is a root waiting on its agents.
- `a 200k context window` for a model you expected to have 1M: the line says
  where the figure came from — most likely `CLAUDE_CODE_DISABLE_1M_CONTEXT`.
  Name the window yourself with `CR_CONTEXT_WINDOW=1M`.
- `the window is unknown ... stays disarmed`, and `cr window?` in the corner:
  this build has never heard of the model and could not look it up either. It
  will not guess — a guessed window is how a session gets folded at 12% full —
  so either `CR_CONTEXT_WINDOW=1M`, or set `CR_CONTEXT_TOKENS`, which needs no
  window at all.
- `restart aborted at handoff_sent: ...` means the fold produced nothing usable,
  and the message names which of the four checks failed. The session was left
  alone.
- The percentage in the badge never moves: the wrapper reads the figures off
  assistant rows, so it has nothing to show until the session answers something.
  A transcript that already existed when the wrapper started is seeded rather
  than replayed, so a `--continue` session reports its size from its next turn.

## Caveats

- The context restart reads its figures from one transcript at a time, the one
  this terminal's session writes. On Claude Code >= 2.1.273 that transcript is
  identified explicitly, through `~/.claude/sessions/<pid>.json`
  (`ClaudeSessionRegistry`) — never by guessing which file grew last, so
  another live session under the same working directory has no effect on it,
  even while it is briefly the busier of the two.
- Without that file (an older Claude Code, or the registry never resolving one
  unambiguously), the watcher falls back to its previous heuristic: stay with
  the transcript already being followed while it grows, and otherwise prefer
  whichever one did not exist when the session started. That fallback carries
  the same limitation as before — another live session under the same working
  directory can, briefly, be the file that grew last — and a
  `no session registry for pid …` line in the log says when it is in effect.

## Settings

Every context-restart setting — `CR_CONTEXT_PCT`, `CR_CONTEXT_TOKENS`,
`CR_CONTEXT_WINDOW`, the codex thresholds, the model lookup, the handoff file
and phrases, the timeouts and `CR_SLASH_ENTER` — is in
[configuration.md](configuration.md#context-restart), and all of them do nothing
until `CR_CONTEXT_PCT` is set.

See also: [codex](codex.md), [usage limits](usage-limits.md),
[troubleshooting](troubleshooting.md).
