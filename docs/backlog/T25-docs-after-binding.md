# T25 — Documentation after A/B epics

Priority: P2 · Epic: E · Depends on: T02, T04, T05, T08, T09 · Size: S

## Problem

The documentation currently describes the bug as a “caveat”: `docs/context-restart.md`
(“Caveats”: “Another live session under the same working directory can,
briefly, be the file that grew last”) and states guarantees that do not exist
(“Giving up leaves the session untouched” — this is not true after a fold has
been delivered). `docs/codex.md` describes three-level threshold arithmetic that
T18/T22 simplify. `docs/bugs/codex-self-compaction-orphans-handoff.md` is a valuable
chronicle, but its “Not verified” section is partially addressed by this backlog item.

## What to do

1. `docs/context-restart.md`: add a “Which session is mine” section (binding via
   `sessions/<pid>.json`, echo nonce, and per-session handoff file `{id}`); remove
   the “Caveats” note about a neighboring session; supplement “Why `/clear` is the
   last thing it will do” with “and the unfold is owed after it” and the cancel phrase.
2. `docs/codex.md`: rollout binding, `codex resume` for old sessions, the new
   threshold order, and `$skill` input grammar.
3. `docs/how-it-works.md`: badge-word table (T14) and log tag (T01).
4. `docs/troubleshooting.md`: “two sessions in one project”, “unfold failed —
   what to do”, and “how to read the log by pid”.
5. `docs/bugs/…`: add a link at the top to the backlog tasks that close each
   finding (T08, T09, T22).
6. README: add one sentence about multi-session support if it has become a
   noticeable capability.

## Acceptance criteria

- [ ] All listed files are updated; no remaining phrase describes behavior from
      before T02/T04/T05/T08/T09 (check `grep -n "grew last\|left
      untouched\|Caveats" docs/`).
- [ ] Links between documents and anchors work (check with `grep` for
      `](…#…)` and verify that the headings exist).
- [ ] `--cr-help` (lines 2–50 of the script) is consistent with the documentation.
