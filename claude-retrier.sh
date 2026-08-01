#!/usr/bin/env bash
# claude-retrier — auto-resume Claude Code after a usage limit, without tmux.
#
# One file. Wraps `claude` in a PTY it owns, so it can BOTH see everything Claude
# prints AND type into the session — the two capabilities that forced the tmux
# design in claude-auto-retry (capture-pane + send-keys). Everything else (detached
# monitor, event markers, launchd/systemd reconcilers, shell-function installer)
# falls out as unnecessary.
#
# Usage:  claude-retrier.sh [claude args...]
#         claude-retrier.sh --cr-cmd <your-claude> [claude args...]
#         claude-retrier.sh --cr-dump-python      # print the embedded Python (used by tests)
#         claude-retrier.sh --cr-version
#
# `--cr-cmd` (or CR_CLAUDE_CMD) is whatever YOU type to start Claude: a binary, a
# script, a name on PATH, an alias or shell function from your ~/.zshrc, or a whole
# command line. Anything the wrapper cannot exec itself is run through your login
# shell, so rc-file aliases work exactly as they do when you type them.
#
# Set CR_DISABLE=1 to bypass the wrapper entirely.

set -u

CR_VERSION="1.0.0"

# =============================================================================
# SECTION 1 — DETECTION PATTERNS
# =============================================================================
# Every wording Claude Code has used (or plausibly will use) for "you are out of
# quota". These are Python regexes, matched case-insensitively, one per array
# entry. Order does not matter; any single match makes the line a LIMIT line.
#
# Detection requires a LIMIT line AND a RESET line near each other (or a
# structured `"error":"rate_limit"` transcript record, which needs no pattern at
# all). That pairing is what keeps prose about limits from triggering a retry.
#
# Add your own without touching anything else: append to the array.
# -----------------------------------------------------------------------------
CR_LIMIT_PATTERNS=(
  # --- "You've hit your <qualifier> limit" family (the current TUI wording) ---
  "you'?ve hit your (session|weekly|daily|monthly|hourly|opus|sonnet|usage|[0-9]+-hour|current)?\\s*limit"
  "you have hit your (session|weekly|daily|monthly|hourly|usage|[0-9]+-hour)?\\s*limit"
  "you'?ve hit the (session|weekly|daily|usage|rate)?\\s*limit"
  "hit your (session|weekly|daily|monthly|usage|rate|[0-9]+-hour)\\s+limit"
  # --- "reached" family ---
  "you'?ve reached your (session|weekly|daily|monthly|usage|rate|[0-9]+-hour)?\\s*limit"
  "you have reached your .{0,24}limit"
  "(claude|claude ai|claude code)?\\s*usage limit reached"
  "(session|weekly|daily|monthly|[0-9]+-hour) limit reached"
  "\\blimit reached\\b"
  "\\bquota (exceeded|reached)\\b"
  # --- "exceeded" family ---
  "you'?ve exceeded your .{0,24}limit"
  "you have exceeded your .{0,24}limit"
  "(rate|usage|request|token) limit exceeded"
  "exceeded (your|the) .{0,24}(quota|limit|allowance)"
  # --- generic noun phrases that only ever appear on a real limit render ---
  "\\busage limit\\b"
  "\\brate limit\\b"
  "\\brate_limit_error\\b"
  "\\brate_limit\\b"
  "\\bratelimit(ed)?\\b"
  "\\b[0-9]+-hour limit\\b"
  "out of (extra )?usage"
  "you'?re out of (usage|credits|messages)"
  "run out of (usage|credits|messages)"
  "no (remaining|more) (usage|credits|messages)"
  "insufficient (quota|credits)"
  "\\btoo many requests\\b"
  "http 429|status(:| code)? 429|\\berror 429\\b"
  # --- upsell / companion lines Claude prints right next to a live banner ---
  "/upgrade to increase your usage limit"
  "/usage-credits\\b"
  "upgrade your plan"
  "stop and wait for limit to reset"
  # --- localisations seen in the wild ---
  "límite de uso alcanzado"
  "limite d'utilisation atteinte"
  "nutzungslimit erreicht"
  "使用上限に達しました"
  "已达到使用上限"
)

# Lines that say WHEN the quota comes back. One of these must sit near a LIMIT
# line for the scraper path to fire, and the first one found is what gets parsed
# into a wall-clock wait.
CR_RESET_PATTERNS=(
  "resets?\\s+(at\\s+)?[0-9]{1,2}(:[0-9]{2})?\\s*(am|pm)?"          # resets 3pm / resets at 3:20am / resets 15:30
  "resets?\\s+(on\\s+)?[a-z]{3,9}\\.?\\s+[0-9]{1,2}"                # resets Jul 22 / resets on July 22
  "resets?\\s+(tomorrow|today|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
  "resets?\\s+in[:\\s]\\s*[0-9]"                                     # resets in 3 hours
  "reset(s|ting)?\\s+(at|on|in)\\b"
  "will reset (at|on|in)\\b"
  "available again (at|on|in)\\b"
  "try again (at|in|after)\\s+[0-9]"                                 # try again in 5 minutes
  "come back (at|in)\\s+[0-9]"
  "retry[- ]after[:\\s]+[0-9]+"
  "wait\\s+[0-9]+\\s*(seconds?|minutes?|hours?|secs?|mins?|hrs?)\\b"
  "[0-9]{4}-[0-9]{2}-[0-9]{2}t[0-9]{2}:[0-9]{2}"                     # ISO-8601 instant
)

# "Claude is mid-flight" markers. Seen anywhere in the recent output stream they
# mean the session is alive and must not be typed into. The streaming footer is
# repainted several times a second, so its absence for a few seconds is a solid
# idle signal — much stronger than the tmux design's foreground-process check.
CR_WORKING_PATTERNS=(
  "esc to interrupt"
  "\\besc\\b[^\\n]{0,24}\\binterrupt\\b"
  "ctrl\\+c to (stop|interrupt)"
  "retrying in [0-9]"
  "attempt [0-9]+/[0-9]+"
  "waiting for [0-9]+ background agents? to finish"
  "tokens?\\s*·\\s*esc"
)

# The interactive /rate-limit-options selector. If this is on screen a bare Enter
# confirms the highlighted default — historically "Upgrade your plan" (upstream
# issue #19) — so we dismiss it with Escape before typing anything.
CR_MENU_PATTERNS=(
  "what do you want to do\\?"
  "stop and wait for limit to reset"
  "1\\.\\s*upgrade your plan"
  "/rate-limit-options"
)

# Lines that LOOK like a limit but are not one. Checked first; a matching line is
# dropped before pairing. Keeps the API-429 "not your usage limit" render and
# this tool's own docs/logs from parking the session for hours.
CR_IGNORE_PATTERNS=(
  "not your usage limit"                       # "Server is temporarily limiting requests (not your usage limit)"
  "temporarily limiting requests"
  "approaching (your )?.{0,16}limit"           # the 90%-warning banner: not a stop
  "you are nearing"
  "claude-retrier|claude-auto-retry|CR_LIMIT_PATTERNS|CR_RESET_PATTERNS"
  "^\\s*[#>]\\s"                               # markdown quote / comment in a rendered doc
)

# =============================================================================
# SECTION 2 — configuration (all overridable from the environment)
# =============================================================================
: "${CR_MESSAGE:=continue}"            # what to type when the limit lifts
: "${CR_MARGIN_SEC:=45}"               # extra wait past the stated reset time
: "${CR_MAX_ATTEMPTS:=3}"              # sends per incident before giving up
: "${CR_FALLBACK_WAIT_SEC:=18000}"     # 5h, used when no reset time can be parsed
: "${CR_MAX_WAIT_SEC:=691200}"         # 8d hard cap on any single wait
: "${CR_USER_IDLE_SEC:=20}"            # don't type while the human is typing
: "${CR_BUSY_IDLE_SEC:=6}"             # no working-footer for this long => idle
: "${CR_VERIFY_SEC:=60}"               # how long to watch for the retry taking hold
: "${CR_SCRAPE:=auto}"                 # auto | always | never  (screen-scrape fallback)
: "${CR_LOG:=$HOME/.claude-retrier/log}"
: "${CR_NOTIFY:=1}"                    # print a one-line status note into the terminal
: "${CR_WAIT_SCALE:=1}"                # divide every wait by this (tests use 3600)
: "${CR_CLAUDE_BIN:=}"                 # override the claude binary (a file, nothing else)
: "${CR_CLAUDE_CMD:=}"                 # YOUR claude command: binary, PATH name, alias,
                                       # shell function, or a full command line
: "${CR_SHELL:=}"                      # shell that knows your aliases (default: $SHELL)
# Where to look when `claude` is not on PATH (colon-separated, in order).
: "${CR_CLAUDE_FALLBACKS:=$HOME/.claude/local/claude:$HOME/.local/bin/claude:/opt/homebrew/bin/claude:/usr/local/bin/claude}"
: "${CR_POLL_SEC:=2}"                  # transcript poll interval
: "${CR_SCRAPE_CONFIRM_SEC:=3}"        # a scraped banner must persist this long

# =============================================================================
# SECTION 3 — argument handling / degradation
# =============================================================================
case "${1:-}" in
  --cr-version) echo "claude-retrier $CR_VERSION"; exit 0 ;;
  --cr-help|-h|--help-retrier)
    sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
    exit 0 ;;
esac

# `--cr-cmd <command>` — the user's own way of starting Claude. Leading position
# only: everything after it belongs to claude, and claude takes a bare prompt as
# its first argument, so a positional guess would eat the prompt of anyone typing
# `claude-retrier.sh "fix the bug"`.
CR_CMD_SPEC="$CR_CLAUDE_CMD"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --cr-cmd)
      [ "$#" -ge 2 ] || { echo "claude-retrier: --cr-cmd needs a command" >&2; exit 2; }
      CR_CMD_SPEC="$2"; shift 2 ;;
    --cr-cmd=*) CR_CMD_SPEC="${1#--cr-cmd=}"; shift ;;
    *) break ;;
  esac
done

# A user command that resolves back to this script would fork-bomb the machine.
# Every exec below inherits this counter; two levels are legitimate (the wrapper
# degrading into plain claude), a third means the command points at us.
CR_DEPTH=$(( ${CR_DEPTH:-0} + 1 ))
export CR_DEPTH
if [ "$CR_DEPTH" -gt 3 ]; then
  echo "claude-retrier: refusing to recurse — does your claude command point back at claude-retrier?" >&2
  exit 1
fi

# Never let the wrapper be the reason `claude` stops working (upstream issue #65:
# an orphaned shell function bricked the command). Any doubt => plain claude.
cr_find_claude() {
  if [ -n "$CR_CLAUDE_BIN" ]; then
    # An explicit override that isn't runnable is a configuration mistake, not a
    # reason to silently fall back to some other claude.
    { [ -f "$CR_CLAUDE_BIN" ] && [ -x "$CR_CLAUDE_BIN" ]; } || return 1
    printf '%s' "$CR_CLAUDE_BIN"
    return 0
  fi
  local p
  # `type -P` searches PATH for an executable FILE only — a shell function or
  # alias named `claude` (Claude Code's own installer adds one, and so does
  # claude-auto-retry) is skipped, so the wrapper can never recurse into itself.
  p=$(type -P claude 2>/dev/null)
  if [ -n "$p" ] && [ -f "$p" ] && [ -x "$p" ]; then printf '%s' "$p"; return 0; fi
  local IFS=:
  for p in $CR_CLAUDE_FALLBACKS; do
    # -f as well as -x: a bare -x test also passes for a DIRECTORY (the execute
    # bit means "may traverse"), and exec'ing one fails with a baffling EACCES.
    if [ -f "$p" ] && [ -x "$p" ]; then printf '%s' "$p"; return 0; fi
  done
  return 1
}

# The shell that knows the user's aliases and functions. $SHELL is the one they
# actually configured; the fallbacks only matter in stripped environments (cron,
# containers) where no alias can be defined anyway.
cr_find_shell() {
  local s
  for s in ${CR_SHELL:-} ${SHELL:-} bash zsh sh; do
    [ -n "$s" ] || continue
    command -v "$s" >/dev/null 2>&1 && { printf '%s' "$s"; return 0; }
  done
  return 1
}

# A word we can hand to `exec` or `type -P` as-is: no whitespace, no character the
# shell would expand. Anything else is a command LINE and needs a shell to read it.
cr_is_bare_word() {
  case "$1" in
    "") return 1 ;;
    *[!A-Za-z0-9._/@%+:=-]*) return 1 ;;
    *) return 0 ;;
  esac
}

# The body of an alias, asked of the shell that defines it. Returning the body
# rather than running the alias through `sh -i` keeps the interactive shell out of
# the final exec: one less process between us and claude, and no "no job control
# in this shell" on stderr when we are running without a tty (`claude -p`).
# bash 3.2 (the /bin/bash macOS still ships) has no BASH_ALIASES and returns
# nothing here — the interactive path below covers it.
cr_alias_body() {   # $1 = shell, $2 = name
  local body
  body=$("$1" -ic 'if [ -n "${ZSH_VERSION:-}" ]; then print -r -- "${aliases[$1]:-}"
                   else printf "%s" "${BASH_ALIASES[$1]:-}"; fi' cr-probe "$2" 2>/dev/null) || return 1
  [ -n "$body" ] || return 1
  printf '%s' "$body"
}

# Turns "whatever the user types to start Claude" into an argv vector in CR_ARGV.
# Four shapes, tried in the order that keeps the common ones cheap and exact:
#
#   /opt/bin/claude-work   a path            -> exec it
#   claude-work            a name on PATH    -> exec the file
#   claude-work            an alias/function -> run it through an interactive shell
#   "claude --model opus"  a command line    -> ditto, shell reads the arguments
#
# The interactive shell is what makes rc-file aliases work: they exist nowhere
# else. It is only reached when the cheap paths miss, so the usual case pays
# nothing for it.
CR_ARGV=()
cr_resolve_cmd() {
  local spec="$1" p sh
  CR_ARGV=()

  if [ -z "$spec" ]; then
    p=$(cr_find_claude) || return 1
    CR_ARGV=("$p")
    return 0
  fi

  if cr_is_bare_word "$spec"; then
    case "$spec" in
      */*)
        # An explicit path that isn't runnable is a mistake worth reporting, not a
        # reason to go looking for some other claude.
        { [ -f "$spec" ] && [ -x "$spec" ]; } || return 1
        CR_ARGV=("$spec"); return 0 ;;
    esac
    p=$(type -P -- "$spec" 2>/dev/null)
    if [ -n "$p" ] && [ -f "$p" ] && [ -x "$p" ]; then CR_ARGV=("$p"); return 0; fi
  fi

  sh=$(cr_find_shell) || return 1
  if cr_is_bare_word "$spec"; then
    # Not a file, so it can only be an alias or a function — and only an
    # interactive shell has read the rc file that defines one.
    local body
    if body=$(cr_alias_body "$sh" "$spec"); then
      # An alias is just text: run its expansion, no interactive shell needed.
      # "$@" carries the claude arguments through untouched — no re-quoting, no
      # word-splitting of anything the user did not write themselves.
      CR_ARGV=("$sh" -c "$body \"\$@\"" "$spec")
      return 0
    fi
    # A function (or a bash 3.2 alias): only the interactive shell has it. Probe
    # first, so a typo fails here with a clear message instead of inside the pty
    # as an unreadable shell error.
    "$sh" -ic 'command -v -- "$1" >/dev/null 2>&1' cr-probe "$spec" >/dev/null 2>&1 || return 1
  fi
  CR_ARGV=("$sh" -ic "$spec \"\$@\"" "$spec")
  return 0
}

# Colon-separated interpreters to try, in order. Overridable so an unusual
# install (or a test) can point at a specific one.
: "${CR_PYTHON_CANDIDATES:=python3:/usr/bin/python3:/usr/local/bin/python3:/opt/homebrew/bin/python3}"

cr_find_python() {
  local p real IFS=:
  for p in ${CR_PYTHON:-} $CR_PYTHON_CANDIDATES; do
    [ -z "$p" ] && continue
    command -v "$p" >/dev/null 2>&1 || continue
    # Resolve to the actual interpreter. `python3` on PATH is frequently a
    # wrapper script (pyenv/asdf shims, conda stubs); running through one adds a
    # shell process between us and the supervisor that does not reliably pass the
    # child's exit status back, so `claude`'s exit code would be lost.
    real=$("$p" -c 'import sys; sys.stdout.write(sys.executable)' 2>/dev/null) || continue
    { [ -n "$real" ] && [ -f "$real" ] && [ -x "$real" ]; } || real="$p"
    if "$real" -c 'import pty,termios,select,json,re,zoneinfo' >/dev/null 2>&1; then
      printf '%s' "$real"
      return 0
    fi
  done
  return 1
}

# =============================================================================
# SECTION 4 — the wrapper itself
# =============================================================================
IFS= read -r -d '' CR_PY <<'CR_PYTHON_EOF' || true
"""claude-retrier PTY supervisor.

Runs claude on a pty we own, forwards bytes both ways untouched, and watches two
independent channels for "the session stopped because the quota ran out":

  1. the JSONL transcript  — structured, `"error":"rate_limit"`. Primary.
  2. the output stream     — pattern pairing. Fallback for when (1) is unavailable.

When a limit is seen it computes the wall-clock wait, sleeps, and types the retry
message into the pty — but only while the human is idle and claude is not busy.
"""
import errno
import fcntl
import glob
import json
import os
import pty
import re
import select
import signal
import struct
import sys
import termios
import time
import tty
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except Exception:          # pragma: no cover - stdlib since 3.9
    ZoneInfo = None


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def _env(name, default, cast=str):
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    try:
        return cast(v)
    except Exception:
        return default


CFG = dict(
    message=_env("CR_MESSAGE", "continue"),
    margin=_env("CR_MARGIN_SEC", 45, float),
    max_attempts=_env("CR_MAX_ATTEMPTS", 3, int),
    fallback_wait=_env("CR_FALLBACK_WAIT_SEC", 18000, float),
    max_wait=_env("CR_MAX_WAIT_SEC", 691200, float),
    user_idle=_env("CR_USER_IDLE_SEC", 20, float),
    busy_idle=_env("CR_BUSY_IDLE_SEC", 6, float),
    verify=_env("CR_VERIFY_SEC", 60, float),
    scrape=_env("CR_SCRAPE", "auto"),
    log=_env("CR_LOG", os.path.expanduser("~/.claude-retrier/log")),
    notify=_env("CR_NOTIFY", "1") == "1",
    wait_scale=max(1e-6, _env("CR_WAIT_SCALE", 1.0, float)),
    poll=_env("CR_POLL_SEC", 2.0, float),
    scrape_confirm=_env("CR_SCRAPE_CONFIRM_SEC", 3.0, float),
)


def _patterns(var):
    raw = os.environ.get(var, "")
    out = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(re.compile(line, re.I))
        except re.error:
            pass          # a bad user pattern must never take the wrapper down
    return out


PAT = {
    "limit": _patterns("CR_PAT_LIMIT"),
    "reset": _patterns("CR_PAT_RESET"),
    "working": _patterns("CR_PAT_WORKING"),
    "menu": _patterns("CR_PAT_MENU"),
    "ignore": _patterns("CR_PAT_IGNORE"),
}


# --------------------------------------------------------------------------- #
# terminal text handling
# --------------------------------------------------------------------------- #
_ANSI = re.compile(
    r"\x1b\][\s\S]*?(?:\x07|\x1b\\)"      # OSC
    r"|\x1bP[\s\S]*?(?:\x07|\x1b\\)"      # DCS
    r"|\x1b[_X^][\s\S]*?(?:\x07|\x1b\\)"  # APC/SOS/PM
    r"|\x1b\[[\x20-\x3f]*[\x40-\x7e]"     # CSI
    r"|\x1b[()][B0UK]"                    # charset select
    r"|\x1b[=><78MDEHc]"                  # misc single-char escapes
)


def strip_ansi(text):
    return _ANSI.sub("", text)


# A tool-call render quotes text ABOUT an error; it is never the live state.
# (upstream issue #63: a grep argument containing banner text parked a monitor
# for 22 hours.) Same discipline, far cheaper here because we also require the
# structured channel to be unavailable before scraping at all.
_TOOL_HEADER = re.compile(r"^\s*[●⏺∙]\s*\S+\(")
_TOOL_CHILD = re.compile(r"^\s*[⎿└↳]")


def tool_echo_mask(lines):
    mask = [False] * len(lines)
    in_block = False
    for i, line in enumerate(lines):
        if _TOOL_HEADER.search(line):
            in_block = True
            mask[i] = True
            continue
        if in_block and (_TOOL_CHILD.search(line) or (line[:1].isspace() and line.strip())):
            mask[i] = True
            continue
        in_block = False
    return mask


def _any(pats, s):
    return any(p.search(s) for p in pats)


def is_ignored(line):
    return _any(PAT["ignore"], line)


def is_limit_line(line):
    return (not is_ignored(line)) and _any(PAT["limit"], line)


def is_reset_line(line):
    return _any(PAT["reset"], line)


def is_working(text):
    return _any(PAT["working"], text)


def is_menu(text):
    return _any(PAT["menu"], strip_ansi(text))


WINDOW = 6          # how far apart a limit line and its reset line may sit


def find_limit(text):
    """Return the banner line if `text` contains a live limit render, else None.

    Requires a LIMIT line with a RESET line within WINDOW lines — the pairing is
    what separates a banner from prose that merely says the word "limit". Scans
    bottom-up so the freshest banner wins over a stale one further up.
    """
    lines = [l.rstrip() for l in strip_ansi(text).split("\n")]
    mask = tool_echo_mask(lines)
    for i in range(len(lines) - 1, -1, -1):
        if mask[i] or not is_limit_line(lines[i]):
            continue
        lo, hi = max(0, i - WINDOW), min(len(lines), i + WINDOW + 1)
        for j in range(lo, hi):
            if mask[j] or not is_reset_line(lines[j]):
                continue
            # Prefer whichever of the two carries the reset time: that is what
            # gets parsed. Joining keeps a two-line render ("⚠ limit" / "· resets
            # 3pm") intact for the parser.
            if i == j:
                return lines[i].strip()
            return (lines[i].strip() + " " + lines[j].strip()).strip()
    return None


# --------------------------------------------------------------------------- #
# reset-time parsing
# --------------------------------------------------------------------------- #
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_WEEKDAYS = {d: i for i, d in enumerate(
    ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])}

# "resets [on] [Jul 22] [at] 6[:30][am] [(Europe/Warsaw)]"
_ABS = re.compile(
    r"reset(?:s|ting)?\s+(?:on\s+)?"
    r"(?:(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+)?"
    r"(?:(?P<rel>tomorrow|today|tonight)\s+)?"
    r"(?:(?P<wd>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+)?"
    r"(?:at\s+)?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)?"
    r"(?:\s*\((?P<tz>[^)]{2,40})\))?",
    re.I)
# same, but the clock time comes before the date: "resets at 6am on Jul 22"
_ABS_TAIL_DATE = re.compile(
    r"\bon\s+(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?P<day>\d{1,2})",
    re.I)
_REL = re.compile(
    r"(?:try again|come back|resets?|available again|wait|retry[- ]after)"
    r"(?:\s+in|\s+after|:)?\s*(?P<n>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)\b",
    re.I)
# The HTTP header form carries no unit — it is seconds by definition.
_RETRY_AFTER = re.compile(r"retry[- ]after[:\s]+(?P<n>\d+)\b", re.I)
_ISO = re.compile(r"(?P<iso>\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}(?::\d{2})?)\s*(?P<z>z|[+-]\d{2}:?\d{2})?", re.I)


def _tz(name):
    if not name or ZoneInfo is None:
        return None
    name = name.strip()
    try:
        return ZoneInfo(name)
    except Exception:
        pass
    # Abbreviations ("UTC", "PST") are not IANA ids; only the unambiguous ones.
    fixed = {"utc": 0, "gmt": 0, "z": 0}
    if name.lower() in fixed:
        try:
            return ZoneInfo("UTC")
        except Exception:
            return None
    return None


def parse_reset(text, now=None):
    """Seconds to wait, or None when nothing parseable is present.

    `now` is injectable so the tests can pin a moment; it must be timezone-aware.
    """
    if not text:
        return None
    now = now or datetime.now().astimezone()

    m = _ISO.search(text)
    if m:
        raw = m.group("iso").replace(" ", "T")
        z = m.group("z")
        try:
            if z and z.lower() == "z":
                target = datetime.fromisoformat(raw + "+00:00")
            elif z:
                target = datetime.fromisoformat(raw + z)
            else:
                target = datetime.fromisoformat(raw).replace(tzinfo=now.tzinfo)
            return max(0.0, (target - now).total_seconds())
        except Exception:
            pass

    m = _REL.search(text)
    if m:
        n = float(m.group("n"))
        u = m.group("unit").lower()
        mult = 1 if u.startswith("s") else 60 if u.startswith("m") else 3600 if u.startswith("h") else 86400
        return n * mult

    m = _RETRY_AFTER.search(text)
    if m:
        return float(m.group("n"))

    m = _ABS.search(text)
    if not m:
        return None

    tz = _tz(m.group("tz")) or now.tzinfo
    local_now = now.astimezone(tz)

    hour = int(m.group("h"))
    minute = int(m.group("m") or 0)
    ap = (m.group("ap") or "").lower()
    if hour > 23 or minute > 59:
        return None
    ambiguous = not ap and 1 <= hour <= 12
    if ap == "pm" and hour != 12:
        hour += 12
    if ap == "am" and hour == 12:
        hour = 0

    def at(day_offset=0, h=None, y=None, mo=None, d=None):
        base = local_now + timedelta(days=day_offset)
        return base.replace(
            year=y or base.year, month=mo or base.month, day=d or base.day,
            hour=hour if h is None else h, minute=minute, second=0, microsecond=0)

    mon = m.group("mon")
    day = m.group("day")
    if not mon:
        tail = _ABS_TAIL_DATE.search(text)
        if tail:
            mon, day = tail.group("mon"), tail.group("day")

    candidates = []
    if mon and day:
        mo, d = _MONTHS[mon[:3].lower()], int(day)
        for year in (local_now.year, local_now.year + 1):
            try:
                candidates.append(at(y=year, mo=mo, d=d))
            except ValueError:
                pass
    elif m.group("wd"):
        want = _WEEKDAYS[m.group("wd").lower()]
        delta = (want - local_now.weekday()) % 7
        candidates.append(at(day_offset=delta))
        candidates.append(at(day_offset=delta + 7))
    else:
        rel = (m.group("rel") or "").lower()
        base_off = 1 if rel == "tomorrow" else 0
        for off in (base_off, base_off + 1):
            candidates.append(at(day_offset=off))
            if ambiguous:
                candidates.append(at(day_offset=off, h=(hour + 12) % 24))

    # Subtracting two datetimes that share a tzinfo is defined to compare WALL
    # CLOCK, silently ignoring the zone — so across a DST transition it is off by
    # an hour in whichever direction hurts (waking early with the banner still
    # live burns the attempt budget). Compare absolute instants instead.
    ref = local_now.timestamp()
    deltas = sorted(c.timestamp() - ref for c in candidates)

    # A reset stated in the recent past means it just happened — retry now rather
    # than rolling a full day forward (upstream: "resets 10am" seen at 10:03
    # parked the session for ~24h).
    future = [d for d in deltas if d > -3600]
    if not future:
        return None
    return max(0.0, future[0])


# --------------------------------------------------------------------------- #
# transcript watcher — the structured, non-scraping channel
# --------------------------------------------------------------------------- #
def project_dir(cwd=None, config_dir=None):
    cwd = cwd or os.getcwd()
    config_dir = config_dir or os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    slug = re.sub(r"[^A-Za-z0-9]", "-", cwd)
    return os.path.join(config_dir, "projects", slug)


def transcript_limit_records(path, offset=0):
    """Yield (new_offset, [records]) for rate-limit rows appended past `offset`."""
    out = []
    try:
        with open(path, "rb") as fh:
            if offset:
                # Our offset is only meaningful if it still lands on a record
                # boundary. If the file was rewritten rather than appended to,
                # it points into the middle of a line and everything after it
                # would decode as garbage — start over instead.
                fh.seek(offset - 1)
                if fh.read(1) != b"\n":
                    offset = 0
            fh.seek(offset)
            data = fh.read()
            new_offset = fh.tell()
    except OSError:
        return offset, out
    if not data:
        return new_offset, out
    tail_nl = data.rfind(b"\n")
    if tail_nl == -1:
        return offset, out                    # a partial line: re-read it next tick
    new_offset = offset + tail_nl + 1
    for raw in data[:tail_nl].split(b"\n"):
        if b"rate_limit" not in raw and b"isApiErrorMessage" not in raw:
            continue
        try:
            rec = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            continue
        if not rec.get("isApiErrorMessage"):
            continue
        err = str(rec.get("error") or "")
        status = rec.get("apiErrorStatus")
        if err != "rate_limit" and status != 429:
            continue
        out.append(dict(text=record_text(rec), ts=rec.get("timestamp"), error=err))
    return new_offset, out


def record_text(rec):
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, list):
        return " ".join(
            c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text").strip()
    if isinstance(content, str):
        return content.strip()
    return ""


class TranscriptWatcher:
    """Follows every transcript in this project that grows after we start.

    No session-id guessing: the file our claude writes is simply the one that
    starts growing. Files already present are seeded at their current size, so
    a `--continue` run never replays yesterday's banner.
    """

    def __init__(self, directory, poll=2.0, now=None):
        self.dir = directory
        self.poll = poll
        self.offsets = {}
        self.next_poll = 0.0
        self.seen_any = False
        self._seed(now or time.time())

    def _seed(self, _now):
        for p in glob.glob(os.path.join(self.dir, "*.jsonl")):
            try:
                self.offsets[p] = os.path.getsize(p)
            except OSError:
                self.offsets[p] = 0

    def poll_now(self, now=None):
        now = now if now is not None else time.time()
        if now < self.next_poll:
            return []
        self.next_poll = now + self.poll
        found = []
        for p in sorted(glob.glob(os.path.join(self.dir, "*.jsonl"))):
            start = self.offsets.get(p)
            if start is None:
                start = 0                       # created after we started: read it all
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            if size < start:                    # truncated/rotated
                start = 0
            if size > start:
                self.seen_any = True
            offset, recs = transcript_limit_records(p, start)
            self.offsets[p] = offset
            found.extend(recs)
        return found


# --------------------------------------------------------------------------- #
# controller — all decision-making, no I/O, so tests can drive it directly
# --------------------------------------------------------------------------- #
IDLE, WAITING, VERIFY, DONE = "idle", "waiting", "verify", "done"


class Controller:
    def __init__(self, cfg, log=lambda *_: None, now=None):
        self.cfg = cfg
        self.log = log
        self.state = IDLE
        self.wake_at = 0.0
        self.attempts = 0
        self.banner = None
        self.last_user_input = 0.0
        self.last_working = 0.0
        self.pending_input_chars = 0
        self.menu_open = False
        self.started = now if now is not None else time.time()
        self.banner_text = None
        self._carry = ""          # overlap so a marker split across two reads still matches

    # -- inputs ------------------------------------------------------------- #
    def on_user_bytes(self, data, now):
        """Track the human so we never type over a half-written prompt.

        Counts printable characters typed since the last submit/clear. Escape
        SEQUENCES (arrows, function keys, mouse reports) are consumed whole —
        naively counting their bytes made every cursor movement look like an
        unsent draft, which would defer the retry indefinitely.
        """
        self.last_user_input = now
        i, n = 0, len(data)
        while i < n:
            b = data[i]
            if b == 0x1b:
                if i + 1 >= n:
                    # A lone Escape at the end of a read is the human pressing
                    # Esc, which clears Claude Code's input box.
                    self.pending_input_chars = 0
                    i += 1
                    continue
                nxt = data[i + 1]
                if nxt in (0x5b, 0x4f):         # CSI "\x1b[" / SS3 "\x1bO"
                    j = i + 2
                    while j < n and 0x20 <= data[j] <= 0x3f:
                        j += 1
                    i = j + 1 if j < n else n   # skip the final byte too
                else:
                    i += 2                      # Alt+key
                continue
            if b in (0x0d, 0x0a):               # Enter: submitted, box is empty
                self.pending_input_chars = 0
                self.menu_open = False
            elif b in (0x03, 0x15, 0x17):       # ^C / ^U / ^W: cleared
                self.pending_input_chars = 0
            elif b in (0x7f, 0x08):
                self.pending_input_chars = max(0, self.pending_input_chars - 1)
            elif b >= 0x20:
                self.pending_input_chars += 1
            i += 1

    def on_output(self, text, now):
        # Claude's streaming footer can land split across two reads, so match on a
        # small overlap with the previous chunk rather than the chunk alone. It must
        # stay small: matching the whole rolling window would keep `last_working`
        # fresh long after the footer stopped repainting, and the idle gate would
        # never open.
        probe = self._carry + text
        self._carry = probe[-160:]
        if is_working(probe):
            self.last_working = now
        if is_menu(probe):
            self.menu_open = True

    def on_limit(self, banner, now, source):
        key = re.sub(r"\s+", " ", banner or "").strip().lower()
        if self.state in (WAITING, VERIFY) and key == self.banner:
            return False                        # same incident, already scheduled
        secs = parse_reset(banner)
        if secs is None:
            secs = self.cfg["fallback_wait"]
            self.log("limit detected (%s), no reset time parsed -> fallback %.0fs: %s"
                     % (source, secs, banner))
        else:
            self.log("limit detected (%s), resets in %.0fs: %s" % (source, secs, banner))
        secs = min(secs + self.cfg["margin"], self.cfg["max_wait"])
        self.banner = key
        self.banner_text = banner
        self.state = WAITING
        self.attempts = 0
        self.wake_at = now + secs / self.cfg["wait_scale"]
        return True

    # -- clock -------------------------------------------------------------- #
    def tick(self, now):
        """Return an action: None, or ('inject', text, dismiss_menu)."""
        if self.state == WAITING:
            if now < self.wake_at:
                return None
            if self.attempts >= self.cfg["max_attempts"]:
                self.log("giving up after %d attempts" % self.attempts)
                self.state = DONE
                return None
            blocked = self._blocked(now)
            if blocked:
                self.log("deferring retry: %s" % blocked)
                self.wake_at = now + 15
                return None
            self.attempts += 1
            self.state = VERIFY
            self.wake_at = now + self.cfg["verify"]
            dismiss = self.menu_open
            self.menu_open = False
            self.log("sending retry (attempt %d/%d)" % (self.attempts, self.cfg["max_attempts"]))
            return ("inject", self.cfg["message"], dismiss)

        if self.state == VERIFY:
            if now - self.last_working < self.cfg["busy_idle"]:
                self.log("session resumed")
                self.state = IDLE
                self.attempts = 0
                self.banner = None
                return None
            if now >= self.wake_at:
                self.log("retry did not take hold; re-arming")
                self.state = WAITING
                self.wake_at = now
                # Re-enter immediately: making the caller wait for the next tick
                # would silently drop an attempt, and at the give-up boundary
                # would leave the controller parked in WAITING forever.
                return self.tick(now)
            return None
        return None

    def _blocked(self, now):
        if now - self.last_working < self.cfg["busy_idle"]:
            return "claude is working"
        if now - self.last_user_input < self.cfg["user_idle"]:
            return "user is typing"
        if self.pending_input_chars > 0:
            return "unsent text in the prompt box"
        return None


# --------------------------------------------------------------------------- #
# pty plumbing
# --------------------------------------------------------------------------- #
def write_all(fd, data):
    """os.write is allowed to write less than asked; a short write on the pty
    would silently drop keystrokes, and on stdout would corrupt the render."""
    while data:
        try:
            n = os.write(fd, data)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EINTR):
                select.select([], [fd], [], 0.05)
                continue
            return False
        data = data[n:]
    return True


_ESC_TAIL = re.compile(r"\x1b[\x20-\x3f\[\]P_X^()=><]*$")


def split_escape_tail(text):
    """Return (complete, carry) so a control sequence cut in half by a read
    boundary is not decoded as literal text into the detection window."""
    m = _ESC_TAIL.search(text)
    if m and len(text) - m.start() < 64:
        return text[:m.start()], text[m.start():]
    return text, ""


def tcset(fd, attr):
    """Apply terminal attributes without ever blocking on it.

    TCSADRAIN waits for pending output to be consumed — if whatever is on the
    other end has stopped reading (a suspended terminal, a pane that went away),
    restoring the mode on exit hangs forever and the wrapper never returns.
    TCSANOW cannot block. SIGTTOU is masked for the call because a process that
    is no longer in the terminal's foreground group gets stopped by it instead of
    an error, which looks identical to a hang.
    """
    old = None
    try:
        old = signal.getsignal(signal.SIGTTOU)
        signal.signal(signal.SIGTTOU, signal.SIG_IGN)
    except Exception:
        pass
    try:
        termios.tcsetattr(fd, termios.TCSANOW, attr)
    except Exception:
        pass
    finally:
        if old is not None:
            try:
                signal.signal(signal.SIGTTOU, old)
            except Exception:
                pass


def fork_pty(rows, cols):
    """Like pty.fork(), but the window size is set BEFORE the child execs.

    pty.fork() hands the child an 0x0 terminal and leaves us to fix it after the
    fact; anything the TUI renders in that gap is laid out for the wrong width.
    """
    master, slave = pty.openpty()
    set_winsize(master, rows, cols)
    pid = os.fork()
    if pid == 0:
        os.close(master)
        os.setsid()
        try:
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
        except Exception:
            pass
        for target in (0, 1, 2):
            os.dup2(slave, target)
        if slave > 2:
            os.close(slave)
        return 0, -1
    os.close(slave)
    return pid, master


def set_winsize(fd, rows, cols):
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except Exception:
        pass


def get_winsize(fd):
    try:
        packed = fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8)
        rows, cols, _, _ = struct.unpack("HHHH", packed)
        if rows and cols:
            return rows, cols
    except Exception:
        pass
    return 24, 80


class Logger:
    def __init__(self, path):
        self.path = path
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.fh = open(path, "a", buffering=1)
        except Exception:
            self.fh = None

    def __call__(self, msg):
        line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
        if self.fh:
            try:
                self.fh.write(line + "\n")
            except Exception:
                pass


def launch_vector():
    """How to start Claude, as an argv prefix the shell layer already resolved.

    Usually one element (the binary). For an alias or a command line it is a
    shell invocation instead; either way we just exec it with the user's
    arguments appended, so nothing here needs to know which shape it got.
    """
    raw = os.environ.get("CR_CLAUDE_ARGV") or ""
    vec = raw.split("\x1f")
    if vec and vec[-1] == "":
        vec.pop()                      # trailing separator from printf
    return vec or [os.environ.get("CR_CLAUDE_RESOLVED") or "claude"]


def main(argv):
    launch = launch_vector()
    claude = launch[0]
    log = Logger(CFG["log"])
    log("start: %s %s" % (" ".join(launch), " ".join(argv)))

    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    interactive = os.isatty(stdin_fd) and os.isatty(stdout_fd)

    rows, cols = get_winsize(stdout_fd) if interactive else (24, 80)
    pid, master = fork_pty(rows, cols)
    if pid == 0:
        try:
            os.execvp(launch[0], launch + argv)
        except Exception as exc:
            sys.stderr.write("claude-retrier: cannot exec %s: %s\n" % (claude, exc))
            os._exit(127)

    old_attr = None
    if interactive:
        try:
            old_attr = termios.tcgetattr(stdin_fd)
            raw = termios.tcgetattr(stdin_fd)
            tty.cfmakeraw(raw)
            tcset(stdin_fd, raw)
        except Exception:
            old_attr = None

    resized = [False]

    def on_winch(_sig, _frm):
        resized[0] = True

    old_winch = signal.getsignal(signal.SIGWINCH)
    try:
        signal.signal(signal.SIGWINCH, on_winch)
    except Exception:
        pass

    # pty.fork() puts claude in its own session, so signals delivered to us (a
    # `kill` from outside, or ^C when stdin is a pipe rather than a raw tty) do
    # not reach it. Forward them instead of dying and orphaning the child.
    def forward(sig, _frm):
        try:
            os.kill(pid, sig)
        except OSError:
            pass

    old_sigs = {}
    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT):
        try:
            old_sigs[s] = signal.getsignal(s)
            signal.signal(s, forward)
        except Exception:
            pass

    ctl = Controller(CFG, log)
    watcher = TranscriptWatcher(project_dir(), CFG["poll"])
    scrape_allowed = CFG["scrape"] in ("auto", "always")
    window = ""            # rolling, ansi-stripped view of what claude just drew
    esc_carry = ""         # half-received control sequence from the previous read
    pending = []           # [(due_ts, bytes)] scheduled writes into the pty
    pending_scrape = None  # (banner, confirm_at) — a scraped banner awaiting confirmation
    watch_stdin = True
    exit_code = 0

    def notify(msg):
        """A single dim line, drawn where the human can see it.

        Claude's TUI repaints continuously, so this is transient by design — the
        durable record is the log file.
        """
        if not CFG["notify"] or not interactive:
            return
        try:
            os.write(stdout_fd, ("\r\x1b[2m[claude-retrier] %s\x1b[0m\r\n" % msg).encode())
        except Exception:
            pass

    def schedule_injection(text, dismiss_menu, now):
        """Type like a human, not like a paste.

        Claude Code treats a burst of text ending in CR as a paste and turns the
        CR into a newline, so the message piles up in the box unsent (upstream
        issues #7/#19). Text and Enter therefore go out as separate writes,
        several hundred ms apart, with an optional Escape first to dismiss the
        /rate-limit-options selector.
        """
        t = now
        if dismiss_menu:
            pending.append((t, b"\x1b"))
            t += 0.35
        pending.append((t, text.encode()))
        pending.append((t + 0.6, b"\r"))

    try:
        while True:
            if resized[0]:
                resized[0] = False
                set_winsize(master, *get_winsize(stdout_fd))

            now = time.time()
            timeout = 0.25
            for due, _ in pending:
                timeout = min(timeout, max(0.0, due - now))

            rlist = [master] + ([stdin_fd] if watch_stdin else [])
            try:
                ready, _, _ = select.select(rlist, [], [], timeout)
            except (OSError, select.error) as exc:
                if getattr(exc, "errno", None) == errno.EINTR:
                    continue
                break

            now = time.time()

            if master in ready:
                try:
                    data = os.read(master, 65536)
                except OSError as exc:
                    # EIO is how a pty reports "the child closed its end" on Linux.
                    data = b""
                if not data:
                    break
                write_all(stdout_fd, data)
                text, esc_carry = split_escape_tail(
                    esc_carry + data.decode("utf-8", "replace"))
                chunk = strip_ansi(text)
                window = (window + chunk)[-8192:]
                ctl.on_output(chunk, now)
                # The transcript is the trustworthy channel; scraping the render is
                # the fallback for when it is unavailable (no transcript directory,
                # a Claude Code build that stops writing the field). Running both
                # unconditionally would just re-import the false-positive class the
                # structured channel exists to avoid.
                if scrape_allowed and ctl.state == IDLE and pending_scrape is None:
                    if CFG["scrape"] == "always" or not watcher.seen_any:
                        banner = find_limit(window)
                        if banner:
                            pending_scrape = (banner, now + CFG["scrape_confirm"])

            if watch_stdin and stdin_fd in ready:
                try:
                    data = os.read(stdin_fd, 65536)
                except OSError:
                    data = b""
                if not data:
                    # Our stdin hit EOF. Stop selecting on it (a closed fd stays
                    # readable forever and would spin the loop), but leave claude
                    # running — piped input followed by an interactive session is
                    # a normal shape.
                    watch_stdin = False
                else:
                    ctl.on_user_bytes(data, now)
                    write_all(master, data)

            for rec in watcher.poll_now(now):
                text = rec["text"] or "usage limit"
                pending_scrape = None            # the structured channel wins
                if ctl.on_limit(text, now, "transcript"):
                    notify("usage limit detected; waiting for reset")

            # A scraped banner is acted on only after it has stood for a moment.
            # That covers two races at once: a frame captured mid-repaint, and a
            # transcript that had not yet announced itself when the banner was
            # first drawn (in which case the structured channel takes over and
            # this is dropped).
            if pending_scrape and now >= pending_scrape[1]:
                banner, _ = pending_scrape
                pending_scrape = None
                if CFG["scrape"] == "always" or not watcher.seen_any:
                    if ctl.on_limit(banner, now, "screen"):
                        window = ""
                        notify("usage limit detected; waiting for reset")

            action = ctl.tick(now)
            if action and action[0] == "inject":
                schedule_injection(action[1], action[2], now)
                notify("limit lifted; resuming session")

            if pending:
                stay = []
                for due, payload in pending:
                    if due <= now:
                        write_all(master, payload)
                    else:
                        stay.append((due, payload))
                pending = stay

            try:
                done, status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                done, status = pid, 0
            if done == pid:
                exit_code = os.waitstatus_to_exitcode(status) if status else 0
                # Drain whatever claude printed on its way out before we tear the
                # pty down, or the last frame (including its exit message) is lost.
                try:
                    while True:
                        r, _, _ = select.select([master], [], [], 0.05)
                        if not r:
                            break
                        data = os.read(master, 65536)
                        if not data:
                            break
                        write_all(stdout_fd, data)
                except OSError:
                    pass
                break
    finally:
        try:
            signal.signal(signal.SIGWINCH, old_winch)
        except Exception:
            pass
        for s, handler in old_sigs.items():
            try:
                signal.signal(s, handler)
            except Exception:
                pass
        if old_attr is not None:
            tcset(stdin_fd, old_attr)
        try:
            os.close(master)
        except Exception:
            pass
        # We may have left the loop because the pty reported EOF, which happens
        # before the child is reaped. Wait briefly so the real exit code is
        # reported instead of a default 0.
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                done, status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                break
            except Exception:
                break
            if done == pid:
                exit_code = os.waitstatus_to_exitcode(status) if status else 0
                break
            time.sleep(0.02)
    log("exit: %d" % exit_code)
    return exit_code


if __name__ == "__main__":
    code = main(sys.argv[1:])
    # waitstatus_to_exitcode reports a signal death as a negative number, which
    # sys.exit would turn into 255. Report it the way a shell does.
    sys.exit(128 - code if code < 0 else code)
CR_PYTHON_EOF

CR_PAT_LIMIT=$(printf '%s\n' "${CR_LIMIT_PATTERNS[@]}")
CR_PAT_RESET=$(printf '%s\n' "${CR_RESET_PATTERNS[@]}")
CR_PAT_WORKING=$(printf '%s\n' "${CR_WORKING_PATTERNS[@]}")
CR_PAT_MENU=$(printf '%s\n' "${CR_MENU_PATTERNS[@]}")
CR_PAT_IGNORE=$(printf '%s\n' "${CR_IGNORE_PATTERNS[@]}")
export CR_PAT_LIMIT CR_PAT_RESET CR_PAT_WORKING CR_PAT_MENU CR_PAT_IGNORE

case "${1:-}" in
  --cr-dump-python)
    printf '%s\n' "$CR_PY"
    exit 0 ;;
  --cr-dump-patterns)
    # The test suite reads the pattern arrays from here rather than re-declaring
    # them, so a pattern can never be tested in a form the wrapper doesn't use.
    for _n in LIMIT RESET WORKING MENU IGNORE; do
      eval "printf '### CR_PAT_%s\n%s\n' \"\$_n\" \"\$CR_PAT_$_n\""
    done
    exit 0 ;;
esac

# ---- degrade paths: any of these and we run claude untouched -----------------
cr_resolve_cmd "$CR_CMD_SPEC" || {
  if [ -n "$CR_CMD_SPEC" ]; then
    echo "claude-retrier: cannot run '$CR_CMD_SPEC' — not a runnable file, and your" >&2
    echo "shell does not know it as a command, alias or function" >&2
  else
    echo "claude-retrier: claude not found on PATH" >&2
  fi
  exit 127
}
CR_CLAUDE_RESOLVED="${CR_ARGV[0]}"

if [ "${CR_DISABLE:-0}" = "1" ] || [ "${CLAUDE_RETRIER_ACTIVE:-0}" = "1" ]; then
  exec "${CR_ARGV[@]}" "$@"
fi

CR_PYTHON_BIN=$(cr_find_python) || exec "${CR_ARGV[@]}" "$@"

# `claude -p` is a batch run: no TUI to type into, and the exit code already
# tells the caller what happened. Nothing to supervise.
for arg in "$@"; do
  case "$arg" in
    -p|--print) exec "${CR_ARGV[@]}" "$@" ;;
  esac
done

# \037 (unit separator) rather than a newline: it cannot occur in a path, a
# command name, or anything a shell would accept as one.
CR_CLAUDE_ARGV=$(printf '%s\037' "${CR_ARGV[@]}")
export CR_CLAUDE_RESOLVED CR_CLAUDE_ARGV CLAUDE_RETRIER_ACTIVE=1
export CR_MESSAGE CR_MARGIN_SEC CR_MAX_ATTEMPTS CR_FALLBACK_WAIT_SEC CR_MAX_WAIT_SEC
export CR_USER_IDLE_SEC CR_BUSY_IDLE_SEC CR_VERIFY_SEC CR_SCRAPE CR_LOG CR_NOTIFY
export CR_WAIT_SCALE CR_POLL_SEC CR_SCRAPE_CONFIRM_SEC

exec "$CR_PYTHON_BIN" -c "$CR_PY" "$@"
