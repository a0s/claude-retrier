<p align="center">
  <img src="docs/banner.webp" width="900"
       alt="A laptop at night showing 'limit reached - resets 3pm', and below it the wrapper typing 'continue'">
</p>

# claude-retrier

[![test](https://github.com/a0s/claude-retrier/actions/workflows/test.yml/badge.svg)](https://github.com/a0s/claude-retrier/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Keep a **Claude Code** or **codex** session going when it stops — for a usage
limit, or for a server that refused the turn — and restart it before it runs out
of context. `claude-retrier` wraps claude, `codex-retrier` wraps codex. One shell
script, with no tmux and no daemon behind it.

```sh
brew install a0s/claude-retrier/claude-retrier
claude-retrier                       # instead of: claude
codex-retrier                        # instead of: codex
```

## Install

Homebrew, on macOS and Linux:

```sh
brew install a0s/claude-retrier/claude-retrier
```

Or take the file. It is self contained and there is no build step:

```sh
curl -fsSLO https://raw.githubusercontent.com/a0s/claude-retrier/main/claude-retrier.sh
chmod +x claude-retrier.sh
ln -s claude-retrier.sh codex-retrier            # optional: the codex name
```

Both names are installed whichever agents you have. `codex-retrier` is the same
file with codex as its default, and on a machine without codex all it does is
say so — which also means installing codex later needs nothing reinstalled.

Every version is also attached to a
[release](https://github.com/a0s/claude-retrier/releases), with the notes for it
in [CHANGELOG.md](CHANGELOG.md).

Uninstall is `brew uninstall claude-retrier`, or deleting the file. Nothing else
was touched: no shell rc edits, no launch agents, no background process.

Needs `bash` and `python3` 3.9+ ([details](docs/how-it-works.md#requirements)).

## Quick start

Run it wherever you would have run `claude` or `codex`:

```sh
claude-retrier                                   # instead of: claude
claude-retrier --resume 5e7a1c02-1a4b-4d99-b2f7  # any claude flag works
claude-retrier --cmd 'claude --model opus'       # or your own claude command
codex-retrier                                    # instead of: codex
CR_CONTEXT_PCT=51 claude-retrier                 # also restart at 51% of the context window
```

That is the whole setup for the usage-limit half. Start a session and forget
about it: the next time you look, the limit will have passed and the session
will have carried on.

The context restart is opt-in, because it clears a session's history and nobody
should get that by accident. `CR_CONTEXT_PCT` turns it on — see
[context-restart.md](docs/context-restart.md).

## What it does

- **Waits out a usage limit.** On `You've hit your session limit · resets 3pm`
  it sleeps until the reset and types `continue`. → [usage limits](docs/usage-limits.md)
- **Notices when a limit lifts early** — another account, an upgraded plan — and
  goes back to watching. → [usage limits](docs/usage-limits.md#when-a-limit-lifts-early)
- **Nudges a turn the server refused** (`Selected model is at capacity`), with a
  wait that doubles on each repeat. → [stalls](docs/stalls.md)
- **Restarts a session that is filling its context window**: handoff file,
  verified, `/clear`, fresh session reads it. Off until you switch it on.
  → [context restart](docs/context-restart.md)
- **Wraps codex as well as Claude Code**, with its own command and its own
  context threshold. → [codex](docs/codex.md)
- **Keeps two sessions in one project apart**: each gets its own identity, its
  own handoff file, and its own tagged log lines, so neither one's restart can
  read or clear the other's. → [troubleshooting](docs/troubleshooting.md#two-sessions-in-one-project)
- **Runs your claude, not `claude`**: a binary, a command line, an alias or a
  function. → [custom command](docs/custom-command.md)
- **Never types over you.** An unsent draft or an unfinished turn makes it wait.
  → [how it works](docs/how-it-works.md#typing-safely)
- **Passes everything else through** — keys, colours, resizes, exit codes, flags —
  and keeps one dim mark in a corner. → [a sign of life](docs/how-it-works.md#a-sign-of-life)
- **Gets out of the way.** No python3, `claude -p`, or `CR_DISABLE=1`, and it
  execs plain claude. → [how it works](docs/how-it-works.md#getting-out-of-the-way)

## Documentation

| page | what is in it |
|---|---|
| [Usage limits](docs/usage-limits.md) | waiting out a limit, early lifts, how a limit is detected, resuming a session |
| [Stalls](docs/stalls.md) | refused turns and the capacity nudge |
| [Context restart](docs/context-restart.md) | turning it on, what you see, the design, custom phrases, when nothing happens |
| [codex](docs/codex.md) | `codex-retrier`, rollouts, subcommands, codex context thresholds |
| [Custom command](docs/custom-command.md) | `--cmd`, `CR_CLAUDE_CMD`, aliases and functions |
| [Configuration](docs/configuration.md) | every setting, grouped by feature |
| [How it works](docs/how-it-works.md) | the pty, transcripts, the badge, update checks, requirements, tests |
| [Troubleshooting](docs/troubleshooting.md) | where to look, and known limitations |

## Troubleshooting

Start with `~/.claude-retrier/log`, then see
[troubleshooting.md](docs/troubleshooting.md).

## License

MIT.
