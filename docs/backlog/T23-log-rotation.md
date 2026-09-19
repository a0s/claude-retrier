# T23 — Log rotation

Priority: P2 · Epic: E · Depends on: — · Size: S

## Problem

`~/.claude-retrier/log` grows without limit (`Logger`, 3800: `open(path,
"a")`). After T01 and more detailed log lines, growth will accelerate. With
several wrappers on the machine, the file is open for writing concurrently, so
rotation must be safe for concurrent writers.

## What to do

1. `CR_LOG_MAX_BYTES` (default `5M`, parsed using a `parse_tokens`-like parser for
   `5M`/`500k`), `CR_LOG_KEEP` (default 2).
2. At wrapper startup (only at startup, so that rotation does not happen under
   a neighboring process in the middle of an incident): if the size exceeds the
   limit — `log.2 → delete, log.1 → log.2, log → log.1` via `os.rename`; writers
   that already have the file open continue writing to `log.1` — this is
   acceptable and documented in a comment.
3. `docs/configuration.md` (“Logging”).

## Acceptance criteria

- [ ] `test_update.py` or a new `test_log.py`: log larger than the limit → after
      creating `Logger`, `log` (empty/new) and `log.1` with the old contents
      exist; with `CR_LOG_KEEP=2`, the third file is deleted.
- [ ] Log smaller than the limit — no rotation, same inode.
- [ ] `./test/run.sh` passes; `./test/codegraph-sync.sh` has been run.

## Where in the code

`Logger` (3800), `CFG` (777), bash defaults (244), and export (4389).
