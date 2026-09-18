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

It also writes `$CLAUDE_CONFIG_DIR/sessions/<pid>.json`, the way Claude Code
>=2.1.273 does, so identity-binding code (T02) has something real to read:

  FAKE_SCRIPT      comma-separated scenario directives (see `run_script`)

For T27 (the subagent tree overlay) it can also draw two rows of Claude Code's
own subagent tree and back them with real `subagents/agent-*.{meta.json,jsonl}`
files, reproducing the geometry T27's evidence #5 captured (glyph in column 4,
label from column 6, a frame closed by ESC[?2026l):

  FAKE_AGENT_TREE  1 = draw the tree once at startup
                    the frame is redrawn (with an ESC[K that wipes whatever the
                    wrapper painted over it, the way claude's own repaint does)
                    whenever the line `repaint-tree` is typed
"""
import json
import os
import re
import sys
import threading
import time

# The phrase the wrapper types is configurable, so the fake recognises it by the
# two things any wording of it must carry: where to write, and what to end with.
_MARKER = re.compile(r"must be exactly (\S+) and nothing else")
_TARGET = re.compile(r"handoff to `([^`]+)`")

SESSION = ["fake-session"]
STARTED_AT = [None]
DROP_NEXT_FOLD = [False]


def project_dir():
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.getcwd())
    d = os.path.join(cfg, "projects", slug)
    os.makedirs(d, exist_ok=True)
    return d


def transcript_path():
    return os.path.join(project_dir(), SESSION[0] + ".jsonl")


def sessions_dir():
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    d = os.path.join(cfg, "sessions")
    os.makedirs(d, exist_ok=True)
    return d


def pid_file_path():
    return os.path.join(sessions_dir(), "%d.json" % os.getpid())


def write_pid_file(status):
    """The identity record TranscriptWatcher (T02) binds on: pid -> sessionId."""
    rec = {"pid": os.getpid(), "sessionId": SESSION[0], "cwd": os.getcwd(),
           "startedAt": STARTED_AT[0], "version": "1.0.0-fake",
           "kind": "interactive", "status": status,
           "statusUpdatedAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())}
    tmp = pid_file_path() + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(rec, fh)
    os.replace(tmp, pid_file_path())


def remove_pid_file():
    try:
        os.unlink(pid_file_path())
    except OSError:
        pass


def write_transcript(text, limited=True, tokens=None, stop_reason=None, model=None, synthetic=False):
    msg = {"role": "assistant", "content": [{"type": "text", "text": text}]}
    msg_model = "<synthetic>" if synthetic else (model or os.environ.get("FAKE_MODEL", "claude-opus-5"))
    if msg_model:
        msg["model"] = msg_model
    if stop_reason:
        msg["stop_reason"] = stop_reason
    if synthetic:
        msg["usage"] = {"input_tokens": 0, "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0, "output_tokens": 0}
    elif tokens is not None:
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


def write_streaming_turn(tokens, final_stop_reason="end_turn"):
    """A turn as it looks mid-stream: a delta row with no stop_reason yet,
    then the row that closes it (T11 row-collapse)."""
    write_transcript("partial", limited=False, tokens=tokens, stop_reason=None)
    write_transcript("partial and final", limited=False, tokens=tokens,
                     stop_reason=final_stop_reason)


def _grow_loop(step, period):
    total = int(step)
    while True:
        time.sleep(period)
        write_transcript("growing", limited=False, tokens=total, stop_reason="end_turn")
        total += int(step)


def run_script(spec):
    """Apply `FAKE_SCRIPT` directives, comma-separated `name` or `name=value`.

      grow=N:M          append a full-looking turn worth N tokens every M
                         seconds, forever (a session that keeps climbing)
      dropfirstfold      swallow the first handoff request entirely: no file,
                         no transcript row, no GOT reply (the lost-message case)
      synthetic          write a `<synthetic>`, all-zero-usage row at startup
      delayclear=K       stall K seconds before acking FAKE_CLEAR_CMD/`/clear`
      stream=N           write a streaming turn at startup: a delta row with
                         no stop_reason, then the row that closes it at N tokens
    """
    if not spec:
        return
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        name, _, value = part.partition("=")
        if name == "grow":
            step, _, period = value.partition(":")
            t = threading.Thread(target=_grow_loop, args=(step or "1000", float(period or "1")), daemon=True)
            t.start()
        elif name == "dropfirstfold":
            DROP_NEXT_FOLD[0] = True
        elif name == "synthetic":
            write_transcript("<synthetic>", limited=False, synthetic=True, stop_reason="stop_sequence")
        elif name == "delayclear":
            os.environ["FAKE_CLEAR_DELAY"] = value or "1"
        elif name == "stream":
            write_streaming_turn(int(value or "10000"))


AGENT_TREE_ROW1 = 10   # rows chosen well clear of both the badge (bottom row)
AGENT_TREE_ROW2 = 11   # and the terminal top, on any size test_pty.py uses.
AGENT_TREE_ROW3 = 12
AGENT_A, AGENT_B = "aaa111", "bbb222"
AGENT_A_LABEL, AGENT_B_LABEL = "Report first file in cwd", "Report second file in cwd"
AGENT_A_MODEL, AGENT_B_MODEL = "claude-sonnet-5", "claude-haiku-4-5-20251001"


def subagents_dir():
    d = os.path.join(project_dir(), SESSION[0], "subagents")
    os.makedirs(d, exist_ok=True)
    return d


def write_subagent(agent_id, description, model):
    d = subagents_dir()
    meta = {"agentType": "general-purpose", "description": description,
            "toolUseId": "toolu_fake_%s" % agent_id, "spawnDepth": 1,
            # T27 evidence: a fork spawned with this field has been seen to run
            # on a different model entirely — writing one here is deliberate,
            # so a test can catch the overlay if it ever starts trusting it.
            "requestedModel": "sonnet"}
    with open(os.path.join(d, "agent-%s.meta.json" % agent_id), "w") as fh:
        json.dump(meta, fh)
    rec = {"type": "assistant", "isSidechain": False, "message": {"model": model, "content": []}}
    with open(os.path.join(d, "agent-%s.jsonl" % agent_id), "w") as fh:
        fh.write(json.dumps(rec) + "\n")


def draw_agent_tree(out, suffix="0 tool uses"):
    frame = (
        "\x1b[?2026h"
        "\x1b[%d;4H├\x1b[%d;6GReport first file in cwd · %s\x1b[K"
        "\x1b[%d;4H│\x1b[%d;6G⎿  Initializing…\x1b[K"
        "\x1b[%d;4H└\x1b[%d;6GReport second file in cwd · %s\x1b[K"
        "\x1b[?2026l"
    ) % (AGENT_TREE_ROW1, AGENT_TREE_ROW1, suffix,
         AGENT_TREE_ROW2, AGENT_TREE_ROW2,
         AGENT_TREE_ROW3, AGENT_TREE_ROW3, suffix)
    out.write(frame)
    out.flush()


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
    STARTED_AT[0] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    SESSION[0] = "fake-session-%d" % os.getpid()  # distinct per process, like a real sessionId
    out.write("fake-claude ready argv=%s\r\n" % " ".join(sys.argv[1:]))
    try:
        cols, rows = os.get_terminal_size()   # os.terminal_size is (columns, lines)
        out.write("winsize %dx%d\r\n" % (cols, rows))
    except OSError:
        out.write("winsize unknown\r\n")
    out.flush()

    write_pid_file("idle")
    run_script(os.environ.get("FAKE_SCRIPT"))

    if os.environ.get("FAKE_AGENT_TREE"):
        # A pause first: the wrapper seeds its transcript watcher at whatever
        # size the file already has (so `--continue` never replays yesterday's
        # banner) — writing before that seed happens would be invisible to it,
        # same reasoning as FAKE_USAGE_DELAY below. Then a second pause after
        # the transcript starts growing, before the tree is drawn: the overlay
        # can only resolve a row's model once the wrapper's watcher has bound
        # to THIS session's transcript (T27's subagents live next to it), and
        # a real session's transcript is always growing well before it spawns
        # subagents.
        time.sleep(float(os.environ.get("FAKE_AGENT_TREE_DELAY", "0.3")))
        write_transcript("agent tree started", limited=False)
        time.sleep(float(os.environ.get("FAKE_AGENT_TREE_SETTLE_SEC", "0.5")))
        write_subagent(AGENT_A, AGENT_A_LABEL, AGENT_A_MODEL)
        write_subagent(AGENT_B, AGENT_B_LABEL, AGENT_B_MODEL)
        draw_agent_tree(out)

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
    try:
        while True:
            write_pid_file("idle")             # waiting for input
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue                      # an empty box: Claude Code ignores it too
            write_pid_file("busy")
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
            if line == "repaint-tree":
                # A repaint the way claude's own TUI does one: new content,
                # ESC[K wiping the row from wherever the label's cursor ends up
                # — which wipes any overlay annotation that was sitting to the
                # right of it, the exact flicker T27's per-frame repaint exists
                # to fix.
                draw_agent_tree(out, suffix="1 tool use")
                out.write("GOT:repaint-tree\r\n")
                out.flush()
                continue
            if _MARKER.search(line) or "Write a complete handoff" in line:
                if DROP_NEXT_FOLD[0]:
                    # The lost-message case: the fold request is swallowed as if
                    # it never reached the session at all.
                    DROP_NEXT_FOLD[0] = False
                    continue
                fold_up(line)
                out.write("GOT:handoff\r\n")
                out.flush()
                continue
            if line == os.environ.get("FAKE_CLEAR_CMD", "/clear"):
                # Claude Code starts a new session in place, and a new session means
                # a new transcript. Nothing is written into it until someone speaks.
                time.sleep(float(os.environ.get("FAKE_CLEAR_DELAY", "0")))
                SESSION[0] = "fake-session-%d" % (int(time.time() * 1000) % 100000)
                write_pid_file("busy")         # sessionId changed under the same pid
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
    finally:
        remove_pid_file()


if __name__ == "__main__":
    sys.exit(main())
