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
"""
import json
import os
import re
import sys
import time


def transcript_path():
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.getcwd())
    d = os.path.join(cfg, "projects", slug)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "fake-session.jsonl")


def write_transcript(text, limited=True):
    rec = {
        "type": "assistant",
        "timestamp": "2026-07-19T19:22:08.730Z",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }
    if limited:
        rec.update({"error": "rate_limit", "isApiErrorMessage": True, "apiErrorStatus": 429})
    with open(transcript_path(), "a") as fh:
        fh.write(json.dumps(rec) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


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
        out.write("GOT:%s\r\n" % line)
        out.flush()
    return int(os.environ.get("FAKE_EXIT", "0"))


if __name__ == "__main__":
    sys.exit(main())
