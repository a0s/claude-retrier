# T20 — Claude: effective session window (`[1m]` vs 200k)

Priority: P1 · Epic: C · Depends on: T18, T19 · Size: L

## Problem

The transcript writes the slug without the suffix (`claude-sonnet-5`), while the
table says 1M. The actual session window depends on `/model sonnet[1m]`, the
plan (Max/Team/Enterprise vs Pro), `CLAUDE_CODE_DISABLE_1M_CONTEXT`, and
`CLAUDE_CODE_MAX_CONTEXT_TOKENS`. If the session is actually 200k, the 510k
threshold will never trigger, Claude Code will compact the context itself at
around ~190k, and the restart will not happen “invisibly” — the worst failure
mode.

## Evidence

Documentation report (2026-09-18): the statusline receives
`context_window.context_window_size` (200000 | 1000000), `model.id`,
`session_id`, `transcript_path`, and `exceeds_200k_tokens`; `--settings
<file-or-json>` exists; the merge order of `--settings` with user settings is
**not documented**. `~/.claude/sessions/<pid>.json` does not contain the
window.

## What to do

1. **Cheap signals** (without experiments): launch argument `--model X[1m]`,
   env `ANTHROPIC_MODEL`, `model` key in `settings.json`/`settings.local.json`
   (`…[1m]`) → the 1M window is confirmed; the absence of the suffix proves
   nothing.
2. **Statusline proxy** (the primary mechanism; requires live verification):
   the wrapper passes `--settings '{"statusLine":{"type":"command","command":
   "<path to agent-retrier.sh> --cr-statusline <sock-or-file>"}}'`. The proxy
   reads JSON from stdin, appends `model.id`, `context_window.*`,
   `session_id`, and `transcript_path` to `~/.agent-retrier/status/<pid>.json`
   (atomically), then **runs the user's original statusLine** (from their
   settings) with the same stdin and passes through its output — so the user's
   status line does not disappear. Verify: (a) whether `--settings` merges with
   or replaces user settings; (b) how often the statusline is invoked; (c) what
   to do when the user has no statusLine configured (do not show our own — empty
   output). Record everything in “Verified”.
3. The supervisor reads this file every `CR_POLL_SEC`: `context_window_size` →
   window (source “claude's status line”, highest priority after
   `CR_CONTEXT_WINDOW`), `model.id` → immediate model change (T21),
   `session_id` → another binding source (T02).
4. If the proxy cannot be enabled, fallback: T19 item 3 (`compact_boundary`)
   and `exceeds_200k_tokens` from the transcript, if present there.
5. `CR_STATUSLINE_PROXY=0` disables the mechanism.

## Acceptance criteria

- [ ] “Verified” is filled in: `--settings` behavior (merge/replace), invocation
      frequency, Claude Code version.
- [ ] Proxy unit test: stdin JSON → status file written atomically; the user's
      statusline script is called with the same stdin, and its stdout is
      returned.
- [ ] `test_controller.py`: `on_status(dict(context_window_size=200000,
      model_id="claude-sonnet-5"))` → 200k window, source “claude's status
      line”, 102k threshold, log.
- [ ] `test_pty.py`: fake_claude invokes the statusline command from
      `--settings` and writes 200k → the wrapper compacts at 102k rather than
      510k.
- [ ] The user's statusline is visible on screen (pty test with `screen.py`).
- [ ] `CR_STATUSLINE_PROXY=0` → `--settings` is not passed.
- [ ] `docs/context-restart.md` (“The context window”): section about `[1m]`.
- [ ] `./test/run.sh` passes; `./test/codegraph-sync.sh` has been run.

## Where in the code

`main()` — exec (3900) and `codex_launch_args` (1931) as examples of adding
arguments; `_resolve_window` (3156); `CFG` `context_env_max`/`context_no_1m`
(851–852); bash layer for the new `--cr-statusline` flag.

## Verified

Done 2026-09-19. No real Claude Code TUI session was available in this
environment, so nothing below claiming to be "verified" is a live
observation of the real binary — only what is documented, plus what this
build's own tests exercise against `fake_claude.py`.

**From documentation (not independently confirmed live):**
- The statusline command is invoked with a JSON payload on stdin including
  `model.id`, `context_window.context_window_size` (200000 | 1000000),
  `session_id`, `transcript_path`, `exceeds_200k_tokens`.
- `--settings <file-or-json>` exists and accepts a `statusLine` block shaped
  `{"type": "command", "command": "..."}`.

**Not verified, and explicitly left as an assumption in the code:**
- Whether a `--settings` value on the command line MERGES with the user's
  `settings.json`/`settings.local.json`, or REPLACES the settings entirely.
  Coded against **merge** — the fail-safe direction, since a proxy that
  silently discarded someone's other settings (permissions, hooks, etc.)
  would be a strictly worse failure than this feature simply not helping.
  If it turns out `--settings` REPLACES: the statusline itself would still
  work exactly as built (this project only ever puts one key, `statusLine`,
  into the object it passes), and this parenthetical is the only thing that
  would need updating — nothing else in `claude_launch_args` depends on
  `--settings` behaving one way or the other for keys it doesn't touch.
- How often the statusline command is actually invoked in a real session
  (every render? every N seconds? on state changes only?). The supervisor
  does not depend on any particular cadence: `StatusPoller` just re-reads the
  status file's mtime every `CR_POLL_SEC`, and treats "the file hasn't
  changed" as "nothing new to report" regardless of how often Claude Code
  calls the command underneath.
- The exact shape/precedence of `.claude/settings.json` vs
  `.claude/settings.local.json` vs `~/.claude/settings.json` for reading the
  USER's own `statusLine` back out — coded to match Claude Code's documented
  precedence (project-local overrides shared-project overrides user-global),
  not observed live.
- Whether the statusline payload actually includes a `workspace.current_dir`/
  `workspace.project_dir` field (used only as a hint for locating the user's
  own settings.json; falls back to `os.getcwd()` of the proxy process, which
  is correct in every case this project's own tests exercise since the proxy
  always runs with the same cwd as the wrapped claude).

**What this build does implement and test (test_statusline.py,
test_controller.py's `TestClaudesOwnStatusLine`, test_pty.py's
`TestClaudesStatusLineProxy`):**
- `--cr-statusline <path>` (bash flag, mirrors `--cr-models`'s dispatch):
  reads stdin, writes `model_id`/`context_window_size`/`session_id`/
  `transcript_path` to `<path>` atomically (temp file + `os.rename`, the same
  pattern `WindowLookup`/`UpdateCheck`/`HandoffRegistry` already use), then
  runs the user's own `statusLine` command (if any) with the same stdin and
  forwards its stdout/exit code untouched. No statusLine configured at all
  means no output from the proxy either.
- `claude_launch_args` adds `--settings` naming that proxy once a restart is
  armed (`CR_CONTEXT_PCT`/`CR_CONTEXT_TOKENS`/`CR_CONTEXT_RESTART`) and
  `CR_STATUSLINE_PROXY` is not `0`; never for codex; never if the user's own
  argv already names `--settings`.
- `StatusPoller` (in the supervisor) polls `~/.agent-retrier/status/<pid>.json`
  every `CR_POLL_SEC` and hands new content to `Controller.on_status`.
- `Controller.on_status`: `context_window_size` → `context_window_hint` (the
  same field codex's own rollout accounting already sets) with source label
  "claude's status line", then `_resolve_window()` — which already checks
  `context_window_hint` right after `CR_CONTEXT_WINDOW` and above the native
  model table, so no new priority tier was needed. `model.id` → an inline
  `context_model` update mirroring `on_context`'s own model-change branch (a
  placeholder for T21's `on_model()`, once merged — see that task's own
  notes). `session_id` → filed on `status_session_id` as a secondary,
  corroborating signal only; T02's `ClaudeSessionRegistry` binding is
  untouched by it.
- `CR_STATUSLINE_PROXY=0`: `--settings` is never added to the launch argv
  (`test_the_off_switch_stops_settings_being_added_at_all`).
- The user's own statusline output still reaches the screen, proxied through
  ours (`test_the_users_own_statusline_still_reaches_the_screen`, using
  `test/screen.py`).
