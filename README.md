# claude-wrap

Auto-resume Claude Code after a usage limit. One shell script, no tmux, no daemon.

```sh
./wrap.sh                 # instead of: claude
alias claude='~/path/to/wrap.sh'
```

When the session stops on `You've hit your session limit · resets 3pm`, the wrapper
waits until the reset and types `continue` for you. Everything else passes straight
through — keys, colours, resizes, exit codes.

## How it works

`wrap.sh` runs `claude` on a pty it owns, so it can both read the output and write
input. That single fact removes the need for tmux (`capture-pane` + `send-keys`), a
detached monitor process, event marker files, and a launchd/systemd reconciler.

It detects a limit on two channels:

1. **The transcript** — Claude Code writes `{"error":"rate_limit","isApiErrorMessage":true}`
   into `~/.claude/projects/<project>/<session>.jsonl`. Structured, unambiguous, primary.
2. **The screen** — pattern matching, used only when the transcript is unavailable.

Before typing anything it checks that Claude is not mid-turn and that you are not
typing yourself — it can see your keystrokes, so an unsent draft in the prompt box
is never overwritten.

## Configuration

All optional, all environment variables:

| variable | default | |
|---|---|---|
| `CW_MESSAGE` | `continue` | what to type when the limit lifts |
| `CW_MARGIN_SEC` | `45` | extra wait past the stated reset time |
| `CW_MAX_ATTEMPTS` | `3` | sends per incident before giving up |
| `CW_USER_IDLE_SEC` | `20` | don't type while you are typing |
| `CW_SCRAPE` | `auto` | `auto` \| `always` \| `never` |
| `CW_LOG` | `~/.claude-wrap/log` | |
| `CW_DISABLE` | | `1` runs plain `claude` |

Detection patterns live in one array at the top of `wrap.sh`; add a wording and
nothing else changes.

## Requirements

`bash` and `python3` (3.9+, standard library only). If either is missing, or
`claude` is invoked with `-p`, the wrapper execs `claude` unchanged — it never
becomes the reason your session won't start.

## Tests

```sh
./test/run.sh     # 100 tests: patterns, time parsing, transcript, state machine,
                  # degradation, and end-to-end runs on a real pty
```

## Limitations

- The screen-scraping fallback cannot tell a live banner from a session that is
  discussing one. It is off whenever the transcript is being written, which is
  the normal case.
- A weekly limit stated as a bare `resets Jul 22` with no year is assumed to be
  the next occurrence.
- Windows is not supported (no pty).

Prior art: [claude-auto-retry](https://github.com/cheapestinference/claude-auto-retry),
whose issue tracker supplied most of the edge cases tested here.

MIT.
