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
arms the model's own row in the [profile table](#the-context-window) instead —
`--cr-models` prints exactly what that resolves to for your environment — unless
`CR_CONTEXT_PCT` or `CR_CONTEXT_TOKENS` says otherwise. For the claude models
this project has always shipped 1M/200k windows for, that row's `restart_at` is
the same 51% (`DEFAULT_RESTART_PCT`) it has always used, just baked in per
model now instead of applied blind to whatever window a session happens to
report. Codex's row is not a percentage at all — its own hard cap and reserve
already give it a number of its own; see
[codex](codex.md#context-restart-on-codex) for what actually decides codex's
threshold under this flag.

Two more make it fit a project you actually work in:

```sh
export CR_CONTEXT_PCT=51
export CR_HANDOFF_FILE=scratchpad/RESUME.md      # relative to cwd, .gitignore it
export CR_RESUME_MSG='Read `{file}` and carry on from it.'
```

Put those three in your shell rc, or in a `direnv` file for one repo, and there
is nothing else to run. Write `{file}` rather than the literal path in both
phrases — it is substituted with whatever `CR_HANDOFF_FILE` actually resolves
to, which is not always the path you set (see below).

Add the handoff file to your `.gitignore`. It is a scratch note about one
session and it is rewritten from scratch every time.

Two sessions in the same project default to the same `CR_HANDOFF_FILE`, and
without either of the two things below, the second one to fold overwrites the
first one's file mid-write:

- Put `{id}` in the path — `CR_HANDOFF_FILE=scratchpad/RESUME-{id}.md` — and
  each session gets a short id of its own (`scratchpad/RESUME-3f9a1c2b.md`);
  no coordination needed, because the path can never collide.
- Leave it out and the wrapper coordinates for you: it registers the path it
  is about to use, and a session that finds another live one already holding
  it moves its own aside to `<stem>-<id><ext>` automatically, logging `handoff
  file is taken by pid N; using scratchpad/RESUME-3f9a1c2b.md`.
  `CR_HANDOFF_REGISTRY_DIR` (default `~/.claude-retrier/sessions`) is where
  that coordination lives.

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

And the unfold is owed after it. Once `/clear` has gone out, the session sitting
there has nothing in it — the one thing left to do is type the resume phrase,
and giving up part-way through would leave it empty forever. So `/clear` itself
is confirmed rather than trusted: the wrapper waits for the session's identity
to move on (a fresh transcript, the same signal a normal restart rebinds on) or
for the screen to go quiet for `CR_CLEAR_SETTLE_SEC`, and reprints `/clear` once
if neither shows up in time. Past that point there is no timeout that gives up
on its own — a person typing, or a foreign transcript still finishing a turn,
just holds the step, with a reminder every five minutes ("unfold is waiting
for: ..."), and the resume phrase goes out the moment the gate opens. If the
resume phrase itself keeps leaving no trace, it is retyped with a growing gap
between attempts (a minute, then two, then four, ...) up to `CR_RESUME_ATTEMPTS`
times before the wrapper stops trying — but even then it does not go quiet: the
badge turns red ("unfold failed"), a notice repeats until someone reads the
handoff file by hand, and the debt only clears once a key is pressed. What does
switch off for good, the same as before, is the *trigger* — nothing here starts
another restart on top of a session nobody has looked at yet.

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
export CR_RESUME_MSG='/my-skill continue from `{file}`'
```

If you write your own, keep three things in it. No new work, because the session
is about to end and anything started now is lost. "For a session that will not
remember this one", without which you get notes that only make sense to someone
who was there. And the marker as the last line of the file, written last: that
is the only thing standing between a half-written note and a cleared session.

Keep `{file}` in both, even in a phrase you are sure will only ever point at
one path: it is what lets the wrapper hand a session its own, possibly
suffixed, handoff path (see [Turning it on](#turning-it-on)) instead of a name
it made up itself. A phrase that drops `{file}` is flagged once at startup —
`CR_RESUME_MSG does not contain {file}; a per-session handoff path cannot be
passed to it` — precisely because it is easy to miss until two sessions in the
same project collide.

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

Putting all of the above together, the full order a threshold is resolved in,
top to bottom, is:

1. `CR_CLAUDE_TOKENS_<SLUG>` / `CR_CODEX_TOKENS_<SLUG>` — one exact model.
2. `CR_CONTEXT_TOKENS` / `CR_CODEX_CONTEXT_TOKENS` — an absolute number, never
   shared between agents (codex never inherits claude's).
3. `CR_CONTEXT_PCT` / `CR_CODEX_CONTEXT_PCT` × the window.
4. the model's own row in the [profile table](#the-context-window), armed by
   `CR_CONTEXT_RESTART=1`, and only when the window matches what that row was
   written for.
5. nothing — a model this build has never heard of, with no explicit number
   from you, stays disarmed rather than guessing.

Whatever (4) answers is always capped under that row's `compact_at` minus
`CR_CODEX_RESERVE_TOKENS` (0 for claude), read live rather than trusted frozen
into the table.

A threshold is a fraction of the window, but the session it protects never
starts at zero: the system prompt, `CLAUDE.md`, MCP tool definitions and the
handoff file it just read back all cost real tokens before a fresh session
writes a word of its own. Against a small window, that baseline alone can eat
most of the threshold's own headroom — a 200k window at the default 51%
restarts at 102k, and a session that comes back from the fold already sitting
at 57k has only 45k left to work with before it folds again, sometimes inside
30-40 minutes. So after every restart the wrapper checks the room actually
left: if `threshold − baseline` falls under `CR_CONTEXT_MIN_HEADROOM` (default
`80k`), it raises the threshold for the rest of the session — `baseline +
CR_CONTEXT_MIN_HEADROOM`, but never past the model's own `compact_at` minus
its reserve, the same ceiling stage (4) above is held to — and says so in the
log. Against a window at or under 200k, the check itself uses whichever is
smaller of `CR_CONTEXT_MIN_HEADROOM` and 30% of the window, so a window too
small to ever spare 80k is not nagged over headroom it never had; the raise
that follows still reaches for the full `CR_CONTEXT_MIN_HEADROOM` where the
model's `compact_at` leaves room for it. When there is nowhere to raise it to,
the wrapper says so out loud instead of guessing — widening `CR_CONTEXT_PCT`
or moving to a bigger window is then a decision for a person, not the wrapper.

A threshold that still cannot hold is a different problem: more than
`CR_CONTEXT_MAX_PER_HOUR` restarts (default `3`) inside a rolling hour means
the trigger is grinding the session rather than protecting it, and it is
switched off for the rest of the session — the same permanent-off state a
failed unfold leaves behind, visible the same way (badge, notify).

## The context window

Every model this build knows about is one row in a profile table — window,
where the wrapper restarts by default, and where the agent folds the context
on its own (`compact_at`, used only for the capping in stage 4 above).
`--cr-models` prints it resolved against your actual environment:

```
$ CR_CONTEXT_RESTART=1 claude-retrier.sh --cr-models
agent   model              window  restart_at  compact_at  source
------  -----------------  ------  ----------  ----------  ------------------
claude  claude-opus-5      1.0M    510k        967k        CR_CONTEXT_RESTART
claude  claude-haiku-4-5   200k    102k        190k        CR_CONTEXT_RESTART
...
codex   gpt-5.6-sol        258k    194k        258k        CR_CONTEXT_RESTART
```

| models | window | restart_at | compact_at |
|---|---|---|---|
| opus/sonnet/fable/mythos 5, opus 4-6/4-7/4-8, sonnet 4-6 | 1M | 510k (51%) | ~967k (Claude Code's own auto-compact point) |
| opus 4-1/4-5, sonnet 4-5, haiku 4-5 | 200k | 102k (51%) | ~190k |
| codex 5.6 (sol/terra/luna/astra) and 5.5 | 258.4k (effective) | 194.4k (cap − 64k reserve) | 258.4k (hard cap) |

`CR_CONTEXT_WINDOW=auto` reads the model slug out of the transcript and looks
it up. It narrows to 200k if `CLAUDE_CODE_DISABLE_1M_CONTEXT` or
`CLAUDE_CODE_MAX_CONTEXT_TOKENS` is set in the environment claude is started
with, and it widens if the session is ever seen past the window it assumed.
Name a number if your setup narrows the window some way the wrapper cannot see.
(On codex the window is read from the rollout, and `CR_CONTEXT_WINDOW` is not
needed — which is also why raising `model_context_window` in codex's
`config.toml` past what the profile table lists moves the window the wrapper
sees, and the table's row for that model stops applying; see stage 4 above.)

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
- `restart aborted at handoff_sent: ...` (or `handoff_ok`) means the fold
  produced nothing usable, and the message names which of the four checks
  failed. If the phrase never reached the session at all, that's it — the
  session is left alone. If it did (an echo was seen: the model was already
  told to wrap up and start nothing new), the next line is
  `restart cancelled; asking the session to carry on` — `CR_CANCEL_MSG` typed
  in to say the ask is off, so an unattended session does not sit on that
  instruction forever.
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
