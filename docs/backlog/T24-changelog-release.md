# T24 — CHANGELOG for unreleased commits and release

Priority: P2 · Epic: E · Depends on: completed P0 tasks · Size: S

## Problem

After `v1.11.0`, `main` contains four commits with no entry in `CHANGELOG.md`:
`5668357` (restoring handoff after codex self-compaction), `1a5e9bc`
(per-agent phrases, 64k reserve), `f53921f` (`CR_CONTEXT_RESTART=1`, per-model
override), `78ffa2c` (custom codex default behind a flag). `release.yml` reads notes
from CHANGELOG, and a test checks that `CR_VERSION` matches the top entry.
The release includes updating the formula in `homebrew-agent-retrier` (see the
project memory: a tag without a formula is not a release).

## What to do

1. Record these four changes in the `## [1.12.0]` section (or a higher version if
   tasks from epics A/B are included by release time — in that case this is a
   major fix and deserves a separate introductory paragraph about “two sessions
   in one project”).
2. Bump `CR_VERSION`, and update `docs/how-it-works.md` (the test count in
   “Tests”).
3. The tag, GitHub release, and brew formula should follow the procedure used for
   previous releases (see the formula's `git log` in the neighboring repository).

## Acceptance criteria

- [ ] `CHANGELOG.md` contains an entry for each of the four commits and for
      all completed backlog tasks included in the release.
- [ ] `test_update.py`/version check passes (`CR_VERSION` = top entry).
- [ ] The tag is pushed, the release is created, and the formula in the tap is
      updated to the new tarball and sha256; do **not** run `brew install`/`upgrade`
      on the user's machine (project memory).
- [ ] `./test/run.sh` passes.

## Where in the code

`CHANGELOG.md`, `CR_VERSION` (54), `.github/workflows/release.yml`,
`docs/how-it-works.md`.
