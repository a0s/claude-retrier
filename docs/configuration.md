# Configuration

Every setting in one place, grouped by feature. All optional, all environment
variables.

[← back to README](../README.md)

- [Commands and agents](#commands-and-agents)
- [Usage limits and typing](#usage-limits-and-typing)
- [Stalls](#stalls)
- [Context restart](#context-restart)
- [Codex](#codex)
- [The badge](#the-badge)
- [Updates](#updates)
- [Logging and switching it off](#logging-and-switching-it-off)
- [Detection patterns](#detection-patterns)

Wrapper flags: `--cmd` (same as `CR_CLAUDE_CMD`), `--agent` / `--cr-agent`
(same as `CR_AGENT`), `--cr-dump-argv` (print what will be executed),
`--cr-help` (includes the default `CR_HANDOFF_MSG`). Every other argument goes
to claude or codex.

## Commands and agents

More in [custom-command.md](custom-command.md) and [codex.md](codex.md).

| variable | default | |
|---|---|---|
| `CR_CLAUDE_CMD` | | your claude command (same as `--cmd`) |
| `CR_AGENT` | `auto` | `auto` \| `claude` \| `codex` — which one you are running (same as `--agent`) |
| `CR_CODEX_CMD` | `codex` | the command `codex-retrier` runs |
| `CR_SHELL` | `$SHELL` | shell that knows your aliases |

## Usage limits and typing

More in [usage-limits.md](usage-limits.md).

| variable | default | |
|---|---|---|
| `CR_MESSAGE` | `continue` | what to type when the limit lifts |
| `CR_MARGIN_SEC` | `45` | extra wait past the stated reset time |
| `CR_MAX_ATTEMPTS` | `3` | sends per incident before giving up |
| `CR_USER_IDLE_SEC` | `20` | don't type while you are typing |
| `CR_TYPING_MAX_SEC` | `900` | but not past this, with an empty input box |
| `CR_RESUME_SEC` | `15` | claude working this long during a wait ends it |
| `CR_DRAFT_GRACE_SEC` | `600` | an untouched draft this old stops blocking |
| `CR_SCRAPE` | `auto` | `auto` \| `always` \| `never` |

## Stalls

More in [stalls.md](stalls.md).

| variable | default | |
|---|---|---|
| `CR_STALL_WAIT_SEC` | `60` | first wait after a stall; `0` switches stalls off |
| `CR_STALL_BACKOFF` | `2` | multiply the wait by this for each repeat |
| `CR_STALL_MAX_WAIT_SEC` | `600` | the longest a stall wait gets |
| `CR_STALL_MAX_ATTEMPTS` | `8` | consecutive stalls before it stops nudging |

## Context restart

More in [context-restart.md](context-restart.md). All of these do nothing until
`CR_CONTEXT_PCT` is set.

| variable | default | |
|---|---|---|
| `CR_CONTEXT_PCT` | `0` | restart at this % of the window; `0` is off |
| `CR_CONTEXT_TOKENS` | `0` | absolute threshold (`500k` is fine); beats the % |
| `CR_CONTEXT_WINDOW` | `auto` | `auto` \| `200k` \| `1M` \| a number |
| `CR_MODEL_LOOKUP` | `1` | look an unfamiliar model up; `0` never touches the network |
| `CR_MODEL_CACHE` | `~/.claude-retrier/windows.json` | what the lookup learned |
| `CR_MODEL_CACHE_TTL_SEC` | `604800` | a week |
| `CR_HANDOFF_FILE` | `.claude-retrier/handoff.md` | where the fold is written |
| `CR_HANDOFF_MSG` | (see `--cr-help`) | the folding phrase; `{file}`, `{marker}` |
| `CR_RESUME_MSG` | ``Read `{file}` and continue from it.`` | the unfolding phrase |
| `CR_CLEAR_CMD` | `/clear` | |
| `CR_HANDOFF_MARKER` | `HANDOFF` | prefix; a nonce is appended to it |
| `CR_HANDOFF_MIN_BYTES` | `200` | a shorter file is not a handoff |
| `CR_HANDOFF_ATTEMPTS` | `2` | folds attempted before giving up |
| `CR_ROOT_IDLE_SEC` | `20` | transcript quiet this long means the turn is over |
| `CR_HANDOFF_TIMEOUT_SEC` | `900` | per step, and frozen while a limit runs |
| `CR_STEP_GAP_SEC` | `3` | between `/clear` and the resume phrase |
| `CR_CONTEXT_COOLDOWN_SEC` | `600` | silence after any restart |
| `CR_CONTEXT_MAX_CYCLES` | `0` | `0` = no cap; a fuse against a loop |
| `CR_SLASH_ENTER` | `2` | Enters sent for a `/command` |

## Codex

More in [codex.md](codex.md#context-restart-on-codex). The rest of the
context-restart settings above apply to codex too.

| variable | default | |
|---|---|---|
| `CR_CODEX_CONTEXT_PCT` | `CR_CONTEXT_PCT` | the same, for codex, as its status line counts it |
| `CR_CODEX_CONTEXT_TOKENS` | `0` | absolute threshold for codex; never taken from claude |
| `CR_CODEX_HOLD_COMPACT` | `1` | start codex with its own compaction threshold moved out of the restart's way; `0` leaves it alone |
| `CR_CODEX_RESERVE_TOKENS` | `32k` | room kept under codex's compaction cap for the fold; the threshold never goes past it |
| `CR_CODEX_INTERRUPT` | `1` | press Esc on a running turn that crosses that line; `0` = only restart between turns |
| `CR_CODEX_LOGS_DB` | newest `$CODEX_HOME/logs_*.sqlite` | where codex logs the count its compaction is decided on |

The last four only matter while the context restart is on for codex — see
[staying ahead of codex's own compaction](codex.md#staying-ahead-of-codexs-own-compaction).

`CR_CODEX_CMD` is under [Commands and agents](#commands-and-agents).

## The badge

More in [how-it-works.md](how-it-works.md#a-sign-of-life).

| variable | default | |
|---|---|---|
| `CR_BADGE` | `1` | `0` hides the corner mark |
| `CR_BADGE_POS` | `bottom-right` | also `bottom-left`, `top-right`, `top-left` |
| `CR_BADGE_LABEL` | `cr` | the word next to the mark |

## Updates

More in [how-it-works.md](how-it-works.md#updates).

| variable | default | |
|---|---|---|
| `CR_UPDATE_CHECK` | `1` | `0` never checks for a newer release and never mentions it |
| `CR_UPDATE_NOTICE_SEC` | `2` | how long the notice stays before claude starts |
| `CR_UPDATE_TTL_SEC` | `86400` | between checks |
| `CR_UPDATE_CACHE` | `~/.claude-retrier/update.json` | |
| `CR_UPDATE_REPO` | `a0s/claude-retrier` | whose releases to read |
| `CR_UPDATE_BREW_FORMULA` | `a0s/claude-retrier/claude-retrier` | named in the brew command |

## Logging and switching it off

| variable | default | |
|---|---|---|
| `CR_LOG` | `~/.claude-retrier/log` | |
| `CR_DISABLE` | | `1` runs plain claude |

## Detection patterns

Detection patterns live in one array at the top of `claude-retrier.sh`. Add a
wording and nothing else changes. Patterns for a refused turn live in
`CR_STALL_PATTERNS`, next to the other pattern arrays — see
[stalls.md](stalls.md#detection-patterns).
