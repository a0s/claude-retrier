# T05 — Unique handoff file per session

Priority: P0 · Epic: A · Depends on: T01 · Size: M

## Problem

`CR_HANDOFF_FILE` is one path per project. Two sessions in the same `cwd` write to the same
`scratchpad/RESUME.md`: the second overwrites the first, the marker does not match, the fold
fails, and if it succeeds, the session resumes from another session's handoff.

## Evidence

Log 2026-09-17 22:45:36/38: two `asking for a handoff into scratchpad/RESUME.md`
entries with nonces `8b21b153` and `081d06b8`; 22:49:17 — `the handoff file does not end
with HANDOFF-081d06b8`.

## What to do

1. `CR_HANDOFF_FILE` supports the `{id}` placeholder — a short session id (8 hex,
   `os.urandom(4).hex()` at wrapper startup, the same one as in the log tag after T01,
   if it is decided to include it there). Example: `scratchpad/RESUME-{id}.md`.
2. Without `{id}` in the path: the wrapper registers itself in
   `~/.claude-retrier/sessions/<pid>.json` (`cwd`, `handoff_path`, `agent`,
   `started`). At startup it reads other entries; if a live process (live pid)
   with the same `handoff_path` already exists, its own path is automatically changed to
   `<stem>-<id><ext>` (`scratchpad/RESUME-3f9a1c2b.md`), and the log records
   `handoff file is taken by pid N; using scratchpad/RESUME-3f9a1c2b.md`. Dead
   pid entries are ignored and removed. The entry is removed on exit.
3. `{file}` in `CR_HANDOFF_MSG`/`CR_RESUME_MSG` is replaced with the **actual** path.
   A user phrase without `{file}` (for example `$supervisor continue
   scratchpad/RESUME.md`) produces this startup log warning: `CR_RESUME_MSG
   does not contain {file}; a per-session handoff path cannot be passed to it`.
4. Documentation: `docs/context-restart.md` ("Turning it on") — recommend writing
   `{file}` in both phrases; `docs/configuration.md` — `{id}`.

## Acceptance criteria

- [ ] Unit test: `CR_HANDOFF_FILE=scratchpad/RESUME-{id}.md` → `handoff_path`
      contains 8 hex characters, and `resume_text` contains the same path.
- [ ] Unit test: two controllers/wrappers with the same `CR_HANDOFF_FILE` and
      the same `cwd` → the second gets a suffix, and the log contains `is taken by pid`.
- [ ] Unit test: an entry with a dead pid is not considered occupied and is removed.
- [ ] Pty test: two wrappers both reach the fold → two different files, both
      `handoff accepted`, both `context restarted`.
- [ ] The warning about the absence of `{file}` is printed exactly once at startup.
- [ ] `./test/run.sh` is green; `./test/codegraph-sync.sh` has been run.

## Where in the code

`Controller.__init__` (2449–2450: `handoff_path`, `resume_text`), `_send_handoff`
(3337), `main()` (3955–3967: handoff directory creation), bash default
`CR_HANDOFF_FILE` (349).
