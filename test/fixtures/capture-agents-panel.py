"""Launch a real `claude`, spawn subagents, and type /tasks to open the
persistent subagent-management panel WHILE they are still running -- then log
the raw bytes. This is the driver behind agents-panel-2.1.273.bin (T29); run
it again whenever upstream changes that panel's render.

Basis: capture-agent-tree.py (T27). The footer prints two DIFFERENT hints
side by side: "/tasks to see subagents" and "<- for agents". Live
investigation on 2.1.273 established these are NOT two ways to the same
place -- the left arrow (plain and application-cursor-key encodings, in both
the default and "manual" permission mode) backgrounds the whole conversation
and opens the CROSS-SESSION roster (other, unrelated sessions' titles and
summaries), exactly the screen CR_ROSTER_PATTERNS in agent-retrier.sh exists
to never scrape. /tasks is the confirmed, safe way to this session's OWN
subagent panel, which is what this driver uses.

Because that first (wrong) attempt genuinely surfaced another session's
content, this driver never writes a byte to disk until the run is judged
safe: output is buffered in memory, and any sign of the roster (the same
substrings CR_ROSTER_PATTERNS matches) truncates the buffer back to the last
known-safe point and sends Escape ("esc returns to it") before anything else
is tried. Nothing from another session ever reaches disk.
"""
import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROWS, COLS = 50, 120

PROMPT = (
    "Use the Task tool to spawn 3 subagents in parallel RIGHT NOW in a single "
    "message. Use subagent_type Explore and model haiku for all three. Each "
    "task is a recursive file COUNT ONLY under a system directory (nothing "
    "user-specific, nothing to read or quote, just a number at the end) -- "
    "make them slow enough to still be running for a while by picking large "
    "trees. Task 1: recursively count every file under /usr, report only the "
    "count. Task 2: recursively count every file under /System/Library, "
    "report only the count. Task 3: recursively count every file under "
    "/Applications, report only the count. "
    "Do nothing else yourself, do not read anything yourself, just spawn them."
)

# Substrings that mean "this is the cross-session roster / background view,
# not this session's own subagent panel" -- the same shape CR_ROSTER_PATTERNS
# in agent-retrier.sh refuses to scrape.
ROSTER_SIGNS = (
    b"awaiting input", b"describe a task for a new session",
    b"moved to the background", b"ctrl+x to delete",
)


def is_roster(data):
    return any(sign in data for sign in ROSTER_SIGNS)


def main():
    workdir = os.path.join(HERE, "proj2")
    os.makedirs(workdir, exist_ok=True)
    for n in ("alpha.txt", "beta.txt", "gamma.txt"):
        with open(os.path.join(workdir, n), "w") as fh:
            fh.write("hello %s\n" % n)

    raw_path = os.path.join(HERE, "raw-agents-panel.bin")
    master, slave = pty.openpty()
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))

    env = {k: v for k, v in os.environ.items()
           if not k.startswith("CLAUDE_CODE_") and not k.startswith("CR_")
           and k != "AGENT_RETRIER_ACTIVE"}
    env["TERM"] = "xterm-256color"
    env["COLUMNS"] = str(COLS)
    env["LINES"] = str(ROWS)

    proc = subprocess.Popen(
        ["claude", "--model", "sonnet"],
        stdin=slave, stdout=slave, stderr=slave,
        env=env, cwd=workdir, close_fds=True, start_new_session=True)
    os.close(slave)

    buf = bytearray()
    safe_mark = 0     # everything before this offset is known clean

    def drain(seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            r, _, _ = select.select([master], [], [], 0.2)
            if not r:
                continue
            try:
                data = os.read(master, 65536)
            except OSError:
                return
            if not data:
                return
            buf.extend(data)

    def bail_and_write(reason):
        print("!! %s -- writing only the known-safe prefix and stopping"
              % reason, file=sys.stderr)
        os.write(master, b"\x1b")     # "esc returns to it"
        drain(2)
        with open(raw_path, "wb") as fh:
            fh.write(bytes(buf[:safe_mark]))
        print("wrote %s (%d bytes, stopped early)" % (raw_path, safe_mark))
        _cleanup(proc, master)

    # Startup gates (trust-the-folder, bypass-permissions warning) each render
    # a two-item menu whose first item is "No, exit". Answer whichever appear.
    for _ in range(4):
        drain(6)
        tail = bytes(buf[-4000:])
        if b"exit" in tail and "❯".encode() in tail:
            os.write(master, b"\x1b[B")     # Down -> the "Yes" item
            drain(1)
            os.write(master, b"\r")
            del buf[:]
        else:
            break

    os.write(master, PROMPT.encode())
    drain(2)
    os.write(master, b"\r")

    # Wait for the tree to actually be running -- polled tight (0.3s) because
    # these trivial-looking tasks can finish within a couple of seconds. Must
    # check for the tree's own glyphs, not words like "Running" or "Explore":
    # PROMPT itself contains "subagent_type Explore" and gets echoed to the
    # screen within the first poll, which used to trip this early and send
    # /tasks before any agent had actually been spawned ("No tasks currently
    # running" was the tell).
    deadline = time.time() + 20
    while time.time() < deadline:
        drain(0.3)
        if is_roster(bytes(buf[safe_mark:])):
            return bail_and_write("the roster surfaced before /tasks was even sent")
        tail = bytes(buf[-3000:])
        if "├".encode() in tail or "└".encode() in tail or b"background agent" in tail:
            break

    safe_mark = len(buf)   # the tree is up and running, nothing borrowed yet

    os.write(master, b"/tasks\r")
    drain(3)
    if is_roster(bytes(buf[safe_mark:])):
        return bail_and_write("/tasks opened the roster, not the panel")

    drain(4)
    if is_roster(bytes(buf[safe_mark:])):
        return bail_and_write("roster surfaced during the settle drain")

    with open(raw_path, "wb") as fh:
        fh.write(bytes(buf))
    print("wrote %s (%d bytes)" % (raw_path, len(buf)))

    _cleanup(proc, master)


def _cleanup(proc, master):
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        time.sleep(0.5)
        if proc.poll() is not None:
            break
    try:
        os.close(master)
    except OSError:
        pass


if __name__ == "__main__":
    main()
