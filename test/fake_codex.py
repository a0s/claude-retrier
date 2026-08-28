#!/usr/bin/env python3
"""A stand-in for the codex binary, driven entirely by the environment.

Behaves like a line-oriented TUI on a pty: prints a greeting, echoes what it
is told, and appends JSONL "rollout" records the way real codex does, so the
wrapper can be exercised end to end without burning real quota.

  FAKE_BANNER      text printed once at startup (the on-screen channel)
  FAKE_TRANSCRIPT  written as a usage-limit task_complete error (the structured one)
  FAKE_STALL       written as a transient task_complete error (a server hiccup,
                   not a usage limit)
  FAKE_STALL_INFO  the codex_error_info string for FAKE_STALL (default
                   "server_overloaded")
  FAKE_DELAY       seconds to wait before writing any of the above
  FAKE_EXIT        exit code to use when told to quit
  FAKE_WORKING     print codex's own streaming footer forever (session looks busy)

Typing `answer` writes an ordinary (non-error) task_complete: a turn that was
served, which is how a session says its quota came back.

It also plays the other half of a context restart, which needs a session that
answers with numbers rather than words:

  FAKE_USAGE        context the startup token_count records claim
                     (last_token_usage.total_tokens)
  FAKE_USAGE_DELAY   seconds to wait first, and between the two copies of it
  FAKE_WINDOW        model_context_window on every record (default 258400)
  FAKE_SUBAGENT      when set, session_meta claims thread_source "subagent"
                     (used to prove the wrapper ignores other agents' rollouts)
  FAKE_CWD           the cwd written into session_meta (default os.getcwd())
  FAKE_HANDOFF       what to do when asked to fold up: ok | short | nomarker | none
  FAKE_HANDOFF_STOP  kept for symmetry with fake_claude.py; codex has no
                     stop_reason, so this is ignored
  FAKE_USAGE_AFTER   context the record written after the resume phrase claims

`/clear` (or FAKE_CLEAR_CMD) moves the fake to a whole new rollout file, which
is what a new chat does and what the wrapper's "did the context actually
fall" check reads.
"""
import json
import os
import re
import sys
import time
import uuid

# The phrase the wrapper types is configurable, so the fake recognises it by the
# two things any wording of it must carry: where to write, and what to end with.
_MARKER = re.compile(r"must be exactly (\S+) and nothing else")
_TARGET = re.compile(r"handoff to `([^`]+)`")

SESSION = [None]   # [current rollout file path]
ORDINAL = [0]      # resets to 0 whenever a new rollout file is started


def codex_home():
    return os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"


def window():
    return int(os.environ.get("FAKE_WINDOW", "258400"))


def write_record(rtype, payload, ts=None):
    rec = {"timestamp": ts or now_iso(), "ordinal": ORDINAL[0], "type": rtype, "payload": payload}
    ORDINAL[0] += 1
    with open(SESSION[0], "a") as fh:
        fh.write(json.dumps(rec) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def new_rollout():
    """Start a brand new rollout file, the way a fresh codex session does.

    The date directories come from the session start time, UTC.
    """
    now = time.gmtime()
    d = os.path.join(codex_home(), "sessions",
                      time.strftime("%Y", now), time.strftime("%m", now), time.strftime("%d", now))
    os.makedirs(d, exist_ok=True)
    sid = str(uuid.uuid4())
    name = "rollout-%s-%s.jsonl" % (time.strftime("%Y-%m-%dT%H-%M-%S", now), sid)
    SESSION[0] = os.path.join(d, name)
    ORDINAL[0] = 0

    ts = now_iso()
    subagent = os.environ.get("FAKE_SUBAGENT")
    payload = {
        "session_id": sid,
        "id": sid,
        "timestamp": ts,
        "cwd": os.environ.get("FAKE_CWD") or os.getcwd(),
        "originator": "codex-tui",
        "cli_version": "0.150.1",
        "source": {"subagent": {"thread_spawn": {}}} if subagent else "vscode",
        "thread_source": "subagent" if subagent else "user",
        "model_provider": "openai",
    }
    write_record("session_meta", payload, ts=ts)


def write_user_message(text):
    """The echo record: proof a typed line was really submitted."""
    write_record("response_item", {
        "type": "message",
        "id": "msg_%s" % uuid.uuid4(),
        "role": "user",
        "content": [{"type": "input_text", "text": text}],
    })


def write_assistant_message(text):
    write_record("response_item", {
        "type": "message",
        "id": "msg_%s" % uuid.uuid4(),
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
        "phase": "final_answer",
    })


def write_token_count(tokens):
    tokens = int(tokens)
    usage = {
        "input_tokens": tokens,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": tokens,
    }
    write_record("event_msg", {
        "type": "token_count",
        "info": {
            "total_token_usage": usage,
            "last_token_usage": usage,
            "model_context_window": window(),
        },
        "rate_limits": {
            "limit_id": "codex",
            "primary": {"used_percent": 4.0, "window_minutes": 10080,
                        "resets_at": int(time.time()) + 604800},
            "secondary": None,
            "rate_limit_reached_type": None,
        },
    })


def write_task_complete(last_agent_message, error=None):
    now = int(time.time())
    payload = {
        "type": "task_complete",
        "turn_id": str(uuid.uuid4()),
        "last_agent_message": last_agent_message,
        "started_at": now,
        "completed_at": now,
        "duration_ms": 1,
    }
    if error is not None:
        payload["error"] = error
    write_record("event_msg", payload)


def fold_up(line):
    """Write (or fail to write) the handoff the wrapper just asked for.

    Mirrors fake_claude.py's fold_up: only the handoff-file part. The rollout
    records for the turn are written by the caller, since codex's turn shape
    differs from claude's.
    """
    mode = os.environ.get("FAKE_HANDOFF", "ok")
    m, t = _MARKER.search(line), _TARGET.search(line)
    marker = m.group(1) if m else "HANDOFF"
    target = t.group(1) if t else ".claude-retrier/handoff.md"
    body = "".join("state: step %d is done\n" % i for i in range(20))
    text = {"ok": body + marker + "\n",
            "short": marker + "\n",           # under the byte floor
            "nomarker": body,                 # complete-looking, no proof it is
            "none": None}.get(mode, body + marker + "\n")
    if text is not None:
        d = os.path.dirname(target)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(target, "w") as fh:
            fh.write(text)


def main():
    out = sys.stdout
    out.write("fake-codex ready argv=%s\r\n" % " ".join(sys.argv[1:]))
    try:
        cols, rows = os.get_terminal_size()   # os.terminal_size is (columns, lines)
        out.write("winsize %dx%d\r\n" % (cols, rows))
    except OSError:
        out.write("winsize unknown\r\n")
    out.flush()

    new_rollout()

    time.sleep(float(os.environ.get("FAKE_DELAY", "0")))

    if os.environ.get("FAKE_TRANSCRIPT"):
        write_task_complete(None, error={
            "message": os.environ["FAKE_TRANSCRIPT"],
            "codex_error_info": "usage_limit_exceeded",
        })
    if os.environ.get("FAKE_STALL"):
        write_task_complete(None, error={
            "message": os.environ["FAKE_STALL"],
            "codex_error_info": os.environ.get("FAKE_STALL_INFO", "server_overloaded"),
        })
    if os.environ.get("FAKE_USAGE"):
        # Twice, after a pause. The wrapper seeds its watcher at the size every
        # rollout file already has, so a resumed session never replays
        # yesterday's numbers — which means a record written before the
        # watcher gets there is invisible. Real codex takes seconds to answer
        # anything and never runs into that; a fake that writes on its first
        # line does, and did.
        gap = float(os.environ.get("FAKE_USAGE_DELAY", "0.6"))
        for _ in range(2):
            time.sleep(gap)
            write_token_count(os.environ["FAKE_USAGE"])
    if os.environ.get("FAKE_BANNER"):
        out.write(os.environ["FAKE_BANNER"] + "\r\n")
        out.flush()

    if os.environ.get("FAKE_WORKING"):
        start = time.time()
        while True:
            out.write("\r• Working (%ds • esc to interrupt)" % int(time.time() - start))
            out.flush()
            time.sleep(0.2)

    # readline(), not `for line in sys.stdin`: iterating a TextIOWrapper reads
    # ahead in blocks, so on a tty it sits on a complete line until the buffer
    # fills. A real TUI is character-driven and never has this problem.
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue                          # an empty box: codex ignores it too
        write_user_message(line)
        if line.startswith("quit"):
            break
        if line == "answer":
            write_assistant_message("an ordinary answer")
            write_token_count(100)
            write_task_complete("an ordinary answer")
            out.write("GOT:answer\r\n")
            out.flush()
            continue
        if line == "winsize":
            try:
                cols, rows = os.get_terminal_size()   # os.terminal_size is (columns, lines)
                out.write("winsize %dx%d\r\n" % (cols, rows))
            except OSError:
                out.write("winsize unknown\r\n")
            out.flush()
            continue
        if _MARKER.search(line) or "Write a complete handoff" in line:
            fold_up(line)
            write_assistant_message("handoff written")
            if os.environ.get("FAKE_USAGE"):
                # Folding up does not shrink the context — it is still the same
                # full session, which is what the wrapper compares against once
                # the new chat has started.
                write_token_count(os.environ["FAKE_USAGE"])
            write_task_complete("handoff written")
            out.write("GOT:handoff\r\n")
            out.flush()
            continue
        if line == os.environ.get("FAKE_CLEAR_CMD", "/clear"):
            # codex starts a new session in place, and a new session means a
            # new rollout file. Nothing is written into it until someone speaks.
            new_rollout()
            out.write("GOT:/clear\r\n")
            out.flush()
            continue
        if os.environ.get("FAKE_RESUME_MATCH", "continue from it") in line:
            write_assistant_message("picked the handoff up")
            write_token_count(os.environ.get("FAKE_USAGE_AFTER", "5000"))
            write_task_complete("picked the handoff up")
            out.write("GOT:resume\r\n")
            out.flush()
            continue
        out.write("GOT:%s\r\n" % line)
        out.flush()
    return int(os.environ.get("FAKE_EXIT", "0"))


if __name__ == "__main__":
    sys.exit(main())
