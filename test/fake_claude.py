#!/usr/bin/env python3
"""A stand-in for the claude binary, driven entirely by the environment.

Behaves like a line-oriented TUI on a pty: prints a greeting, echoes what it is
told, and can print a usage-limit banner and/or write one into a JSONL
transcript, so the wrapper can be exercised end to end without burning real
quota.

  FAKE_BANNER      text printed once at startup (the on-screen channel)
  FAKE_TRANSCRIPT  banner text written as a rate_limit record (the structured one)
  FAKE_DELAY       seconds to wait before doing either
  FAKE_EXIT        exit code to use when told to quit
  FAKE_WORKING     print a streaming footer forever (session looks busy)

Typing `answer` writes an ordinary (non-limit) assistant record: a turn that was
served, which is how a session says its quota came back.

It also plays the other half of a context restart, which needs a session that
answers with numbers rather than words:

  FAKE_USAGE       context the startup record claims to have been sent with
  FAKE_USAGE_DELAY seconds to wait first, and between the two copies of it
  FAKE_MODEL       model slug on every record (default claude-opus-5)
  FAKE_HANDOFF     what to do when asked to fold up: ok | short | nomarker | none
  FAKE_HANDOFF_STOP  stop_reason for the folding turn (default end_turn)
  FAKE_USAGE_AFTER context the record written after the resume phrase claims

`/clear` moves the fake to a fresh transcript file, which is what Claude Code
does and what the wrapper's "did the context actually fall" check reads.
"""
import json
import os
import re
import sys
import time

# The phrase the wrapper types is configurable, so the fake recognises it by the
# two things any wording of it must carry: where to write, and what to end with.
_MARKER = re.compile(r"must be exactly (\S+) and nothing else")
_TARGET = re.compile(r"handoff to `([^`]+)`")

SESSION = ["fake-session"]


def project_dir():
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.getcwd())
    d = os.path.join(cfg, "projects", slug)
    os.makedirs(d, exist_ok=True)
    return d


def transcript_path():
    return os.path.join(project_dir(), SESSION[0] + ".jsonl")


def write_transcript(text, limited=True, tokens=None, stop_reason=None):
    msg = {"role": "assistant", "content": [{"type": "text", "text": text}]}
    if os.environ.get("FAKE_MODEL", "claude-opus-5"):
        msg["model"] = os.environ.get("FAKE_MODEL", "claude-opus-5")
    if stop_reason:
        msg["stop_reason"] = stop_reason
    if tokens is not None:
        # Split across the three counters the wrapper adds up, so the test
        # exercises the sum rather than a single field.
        msg["usage"] = {"input_tokens": 2,
                        "cache_creation_input_tokens": 1000,
                        "cache_read_input_tokens": max(0, int(tokens) - 1002),
                        "output_tokens": 4000}
    rec = {"type": "assistant", "timestamp": "2026-07-19T19:22:08.730Z",
           "isSidechain": False, "message": msg}
    if limited:
        rec.update({"error": "rate_limit", "isApiErrorMessage": True, "apiErrorStatus": 429})
    with open(transcript_path(), "a") as fh:
        fh.write(json.dumps(rec) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def fold_up(line):
    """Write (or fail to write) the handoff the wrapper just asked for."""
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
    write_transcript("handoff written", limited=False,
                     tokens=int(os.environ.get("FAKE_USAGE", "0") or 0) or None,
                     stop_reason=os.environ.get("FAKE_HANDOFF_STOP", "end_turn"))


def main():
    out = sys.stdout
    out.write("fake-claude ready argv=%s\r\n" % " ".join(sys.argv[1:]))
    try:
        cols, rows = os.get_terminal_size()   # os.terminal_size is (columns, lines)
        out.write("winsize %dx%d\r\n" % (cols, rows))
    except OSError:
        out.write("winsize unknown\r\n")
    out.flush()

    time.sleep(float(os.environ.get("FAKE_DELAY", "0")))

    if os.environ.get("FAKE_TRANSCRIPT"):
        write_transcript(os.environ["FAKE_TRANSCRIPT"])
    if os.environ.get("FAKE_TRANSCRIPT_PLAIN"):
        write_transcript(os.environ["FAKE_TRANSCRIPT_PLAIN"], limited=False)
    if os.environ.get("FAKE_USAGE"):
        # Twice, after a pause. The wrapper seeds its watcher at the size every
        # transcript already has, so that `claude --continue` never replays
        # yesterday's banner — which means a record written before it gets there
        # is invisible. Real claude takes seconds to answer anything and never
        # runs into that; a fake that writes on its first line does, and did.
        gap = float(os.environ.get("FAKE_USAGE_DELAY", "0.6"))
        for _ in range(2):
            time.sleep(gap)
            write_transcript("a full-looking turn", limited=False,
                             tokens=int(os.environ["FAKE_USAGE"]), stop_reason="end_turn")
    if os.environ.get("FAKE_BANNER"):
        out.write(os.environ["FAKE_BANNER"] + "\r\n")
        out.flush()

    if os.environ.get("FAKE_WORKING"):
        while True:
            out.write("\r* Cogitating... (esc to interrupt)")
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
            continue                          # an empty box: Claude Code ignores it too
        if line.startswith("quit"):
            break
        if line == "answer":
            write_transcript("an ordinary answer", limited=False)
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
            out.write("GOT:handoff\r\n")
            out.flush()
            continue
        if line == os.environ.get("FAKE_CLEAR_CMD", "/clear"):
            # Claude Code starts a new session in place, and a new session means
            # a new transcript. Nothing is written into it until someone speaks.
            SESSION[0] = "fake-session-%d" % (int(time.time() * 1000) % 100000)
            out.write("GOT:/clear\r\n")
            out.flush()
            continue
        if os.environ.get("FAKE_RESUME_MATCH", "continue from it") in line:
            write_transcript("picked the handoff up", limited=False,
                             tokens=int(os.environ.get("FAKE_USAGE_AFTER", "5000")),
                             stop_reason="end_turn")
            out.write("GOT:resume\r\n")
            out.flush()
            continue
        out.write("GOT:%s\r\n" % line)
        out.flush()
    return int(os.environ.get("FAKE_EXIT", "0"))


if __name__ == "__main__":
    sys.exit(main())
