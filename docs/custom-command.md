# Your claude, not `claude`

How to make the wrapper run your own claude command: a renamed binary, a whole
command line, an alias or a shell function.

[← back to README](../README.md)

Most people do not run stock `claude` for long. There is a `claude-work` and a
`claude-personal`, or an alias in `~/.zshrc` that pins a model, or a function
that sets a settings file first. Name yours with `--cmd` and the wrapper runs
it:

```sh
claude-retrier --cmd claude-work                    # binary, or a name on PATH
claude-retrier --cmd ~/bin/claude-personal          # a path to anything runnable
claude-retrier --cmd 'claude --model opus'          # a whole command line
claude-retrier --cmd my-claude-alias                # an alias from your ~/.zshrc
claude-retrier --cmd my-claude-function             # a shell function, likewise
```

## Aliases and functions

An alias or a function exists nowhere except inside an interactive shell that
has read your rc file, so that is where the wrapper looks when the name is not a
file it can run directly (`CR_SHELL`, default `$SHELL`, is the shell it asks).
It looks once, at startup, and lifts the definition out so the session itself
runs from a plain shell. `claude-retrier --cmd X --cr-dump-argv` prints exactly
what will be executed.

Caveat: because the alias or function is read out of your rc file once, at
startup, and run from a plain non-interactive shell afterwards, one that calls
*another* alias defined in the same rc file will not find it. (bash 3.2, still
what macOS ships as `/bin/bash`, cannot be asked for an alias body at all and
falls back to running the alias through `bash -i`.)

## Setting it once

Set `CR_CLAUDE_CMD` instead of passing the flag every time:

```sh
alias claude='claude-retrier --cmd claude-work'     # in ~/.zshrc
export CR_CLAUDE_CMD=claude-work                    # or, once, in your env
```

## Arguments

Everything after the command belongs to claude. `claude-retrier --cmd
claude-work --resume` resumes, and a bare prompt stays a prompt. With no `--cmd`
at all the wrapper finds `claude` the way your shell would.

For codex the equivalent is `CR_CODEX_CMD` — see [codex](codex.md).

See also: [configuration](configuration.md#commands-and-agents),
[troubleshooting](troubleshooting.md).
