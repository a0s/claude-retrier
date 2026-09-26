# T07 — Passthrough for non-session claude subcommands

Priority: P2 · Epic: A · Depends on: — · Size: S

## Problem

For codex, a list of non-session subcommands exists (agent-retrier.sh:4378),
while for claude there is only `-p/--print`. `claude stop <id>`, `claude mcp
list`, `claude update`, etc. are launched under the pty supervisor: they sleep
for `CR_UPDATE_NOTICE_SEC`, write `start:/exit:` to the log, and while this is
happening the watcher reads transcripts from other project sessions and may
print `continue` to the command output.

## Evidence

Log: `start: /opt/homebrew/bin/claude stop 8a2e968f (agent: claude)`,
`start: … claude attach 3556432e open in this terminal`.

## What to do

1. In the bash layer, next to the codex list, add `cr_looks_like_claude` and a
   list of subcommands to exec directly: `auth login logout setup-token update
   upgrade install doctor mcp plugin plugins project logs stop kill rm respawn
   gateway import ultrareview`, plus the `--version -v --help -h` flags. **Do
   not** include `agents` (TUI, already handled as a roster) or `attach` (this
   is a session).
2. The first positional word decides; account for a word after a flag with a
   value (`--model opus attach`) in the same way as in the codex branch
   (iterate over all arguments).
3. Add a test in `test/test_degrade.py` using `--cr-dump-argv`/a real launch
   with fake_claude.

## Acceptance criteria

- [ ] `agent-retrier.sh stop abc` and `agent-retrier.sh mcp list` do not
      create `start:` lines in the log (exec directly).
- [ ] `agent-retrier.sh attach abc` and `agent-retrier.sh agents` are still
      wrapped.
- [ ] `agent-retrier.sh "fix the stop command"` (prompt) is wrapped.
- [ ] `./test/run.sh` passes.

## Where in the code

bash section after `CR_PYTHON_BIN` (4348–4382).
