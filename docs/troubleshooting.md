# Troubleshooting

Where to look when the wrapper does not do what you expected, and the known
limitations.

[← back to README](../README.md)

## Start with the log

`~/.claude-retrier/log` (or `CR_LOG`) has the whole story with numbers. It is
the only file the wrapper writes under your home directory.

Two sessions in the same project write into the same log, so every line
carries `[cr <pid> <agent>]` right after the timestamp — the pid is the
supervisor process, printed on `start:`. `grep 'cr 48213'` isolates one
session's own `start: … → … → exit:` sequence out of the interleaved file.

## Common checks

- **The context restart never fires.** See
  [When nothing happens](context-restart.md#when-nothing-happens) — the log
  lines listed there, in order of likelihood.
- **The wrong command runs, or an alias is not found.**
  `claude-retrier --cmd X --cr-dump-argv` prints exactly what will be executed.
  See [custom-command.md](custom-command.md).
- **codex is not being wrapped.** `codex exec`, `codex login`, `codex mcp` and
  the rest run untouched on purpose; only sessions (plain `codex`,
  `codex resume`, `codex fork`) are wrapped. See [codex.md](codex.md#subcommands).
- **codex compacted before the restart.** The log says `codex compacted the
  thread on its own before the restart could`. Give the fold more room with
  `CR_CODEX_RESERVE_TOKENS` or a lower `CR_CODEX_CONTEXT_PCT`; see
  [codex](codex.md#staying-ahead-of-codexs-own-compaction).
- **The wrapper seems to do nothing at all.** Without `python3`, with `claude
  -p`, or with `CR_DISABLE=1`, it execs plain claude unchanged. See
  [requirements](how-it-works.md#requirements).
- **Is it still running?** Look for the dim `◆ cr` mark in a corner
  ([a sign of life](how-it-works.md#a-sign-of-life)); `CR_BADGE=0` hides it.
- **You want it out of the way for one run.** `CR_DISABLE=1` runs plain claude.

## Limitations

- The screen-scraping fallback cannot tell a live banner from a session that is
  discussing one. It is off whenever the transcript is being written, which is
  the normal case.
- A weekly limit stated as a bare `resets Jul 22` with no year is assumed to be
  the next occurrence.
- An alias or function is read out of your rc file once, at startup, and run
  from a plain non-interactive shell afterwards. One that calls *another* alias
  defined in the same rc file will not find it. (bash 3.2, still what macOS
  ships as `/bin/bash`, cannot be asked for an alias body at all and falls back
  to running the alias through `bash -i`.)
- The context restart reads its figures from one transcript at a time, the one
  this terminal's session writes. Another live session under the same working
  directory can, briefly, be the file that grew last.
- Windows is not supported (no pty).
