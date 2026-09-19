# T06 — Fold phrase echo verification and binding confirmation

Priority: P0 · Epic: A · Depends on: T02, T04 · Size: M

## Problem

The resume phrase is checked by its echo in the transcript (`on_resume_echo`) and
retyped when absent; the fold phrase is not. If the handoff phrase does not arrive
(popup, TUI busy, keystroke lost), the wrapper silently waits for
`CR_HANDOFF_TIMEOUT_SEC` (15 minutes) and aborts with “the handoff file was never
written”. The fold phrase echo is also the **only 100% proof** of which transcript
is ours: the nonce `HANDOFF-xxxxxxxx` occurs in exactly one file on the machine.

## What to do

1. `TranscriptWatcher.echo` becomes mutable: `watcher.expect(text)` /
   `watcher.forget(text)`. `_send_handoff` registers the complete fold phrase
   text (with the nonce substituted) as an expected echo. Note that Claude Code
   writes the user line as-is, while codex writes it as `response_item/message
   role=user` with `input_text`; in both cases the comparison is exact
   (`text in echoes`), as it is now.
2. `Controller.on_handoff_echo(path, now)`: sets `handoff_echoed=True`.
   If `path != context_path`, this proves that the binding is incorrect:
   `bind_transcript(path, "our handoff phrase was echoed there")` and a line in
   the log at the “important” level.
3. `_check_handoff`: if there is no echo through `CR_VERIFY_SEC` (60 s) after
   sending and the file has not appeared, retype the phrase (without consuming
   `handoff_tries`, at most 2 retries), logging `the handoff phrase left no trace;
   sending it again (1/2)`. Once exhausted, abort with reason `the handoff phrase
   never reached the session` (T09 does not apply here: the phrase did not arrive,
   so the model did not stop anything).
4. `/clear` (`_send_clear`) is not sent until `handoff_echoed` is True — even if
   the file is valid (it may have been written by a neighboring session).

## Acceptance criteria

- [ ] `test_controller.py`: fold sent, no echo for 60 s → resend,
      log `left no trace`; after 2 retries — abort with the specified reason.
- [ ] `test_controller.py`: fold phrase echo came from another `path` →
      `context_path` switched, log contains `was echoed there`.
- [ ] `test_controller.py`: valid file + `end_turn`, but `handoff_echoed=False`
      → `/clear` is not sent; after the echo — it is sent.
- [ ] `test_pty.py`: fake_claude, for which the first fold phrase is “lost”
      (does not write the user line) → the second is delivered, restart completes.
- [ ] `./test/run.sh` passes; `./test/codegraph-sync.sh` executed.

## Where in the code

`TranscriptWatcher.__init__` (`echo`, 1764), `transcript_limit_records` (1254),
`codex_records` (1375), `Controller._send_handoff` (3337), `_check_handoff`
(3382), `_send_clear` (3361), `main()` (4118).
