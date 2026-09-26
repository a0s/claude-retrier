# The README's GIFs

`claude-restart.gif` (`codex-restart.gif` still pending, see below) is a real
session, not a mockup: a live agent under the wrapper, with the
context-restart threshold turned down far enough that the whole fold →
verify → `/clear` → unfold sequence happens in a couple of minutes instead of
a couple of hours.

Two scripts, both stdlib + PIL + ffmpeg, nothing else:

```sh
# 1. record a live session (this spends quota) -- use the default model
# (sonnet), not a small one: a cheap model has been observed answering the
# fold phrase in its own words ("Handoff written to `HANDOFF.md`.") instead
# of calling Write and echoing the phrase back verbatim, which the T06 echo
# check never accepts, so the recording hangs at "asking for a handoff"
# until the window closes.
python3 docs/demo/record.py claude docs/demo/claude-restart.cast
python3 docs/demo/record.py codex  docs/demo/codex-restart.cast

# 2. cut the waiting out and render
python3 docs/demo/cast2gif.py docs/demo/claude-restart.cast \
        docs/demo/claude-restart.gif --title 'agent-retrier: context restart' --trim 0:127.9
```

**codex-restart.gif is not recorded yet.** `record.py codex` was written
against an older codex-cli and needs a maintainer with time to follow up on
two version-compat breaks found while shipping 2.0: `--full-auto` is gone
(replaced with `--sandbox workspace-write --ask-for-approval never`, already
updated here) and the directory-trust prompt's wording/default changed (also
updated), but the recording still exits a few seconds after the fold is
armed, before ever asking for a handoff — not yet root-caused.

`record.py` drives `agent-retrier.sh` on its own 110x21 pty and writes
[asciicast v2](https://docs.asciinema.org/manual/asciicast/v2/) — a JSON
header plus one `[time, "o", bytes]` line per write, so no `asciinema` binary
is needed to make or to read one.

`cast2gif.py` replays that file through the project's **own** `Screen`
terminal emulator (the one inside `agent-retrier.sh`, reached the same way
`test/screen.py` reaches it), so a frame it paints cannot drift from what the
supervisor itself judges the user to be seeing. `--trim START:END` keeps only
the interesting spans, `--idle-cap` squeezes dead air, `--speed` does the
rest.

Things worth knowing if you re-record these:

- **Geometry: wide and short.** 110x21 (about 16:10 once rendered), not a terminal's default 120x50. A
  README renders a GIF at about 900px wide; at that width 120 columns need a
  font too small to read, and the extra rows only get letterboxed.
- **The demo project is a throwaway directory**, with a `CLAUDE.md`/`AGENTS.md`
  of its own — recording inside a real checkout puts that checkout's
  instructions into the GIF. That alone is not enough to pin the language,
  though: a personal global CLAUDE.md instruction has been observed winning
  over it on claude, which is why `record.py` also passes
  `--append-system-prompt` — outranks CLAUDE.md, though even that has lost to
  a strong enough account-level preference. If a recording comes out in the
  wrong language, that is why; there is no full fix here yet short of
  recording on an account with no such global instruction.
- **Not under `~/.claude`.** Claude Code treats its own config directory as
  special and asks permission to write inside it whatever `--permission-mode`
  says, which stops the fold dead.
- **One prompt, then hands off the keyboard.** A second prompt typed while the
  wrapper is trying to send the fold phrase collides with it, and the log says
  `the handoff phrase left no trace`.
- **Everything is killed on the way out**, process group by process group: a
  pty driver that dies without doing that leaves the supervisor behind,
  writing into the same log (project memory: `live-codex-test-orphans`).

The `.cast` files are kept next to the GIFs. They are the source: a re-render
with different trimming or a different font needs no new quota.
