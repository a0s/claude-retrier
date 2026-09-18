"""Launch a real `claude` in a pty and log every byte it writes.

Follows test/helper.py's pattern: own pty, known winsize, whole process group
killed on the way out so nothing is left behind.
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
    "message. Use subagent_type Explore and model haiku for all three. "
    "Task 1: report the name of the first file in the cwd. "
    "Task 2: report the name of the second file in the cwd. "
    "Task 3: count the files in the cwd. "
    "Do nothing else, do not read anything yourself, just spawn them."
)


def main():
    workdir = os.path.join(HERE, "proj")
    os.makedirs(workdir, exist_ok=True)
    for n in ("alpha.txt", "beta.txt", "gamma.txt"):
        with open(os.path.join(workdir, n), "w") as fh:
            fh.write("hello %s\n" % n)

    raw_path = os.path.join(HERE, "raw.bin")
    raw = open(raw_path, "wb")

    master, slave = pty.openpty()
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))

    # Strip the parent session's own Claude Code wiring: a nested session that
    # inherits the messaging socket/session id does not start clean.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("CLAUDE_CODE_") and not k.startswith("CR_")
           and k != "CLAUDE_RETRIER_ACTIVE"}
    env["TERM"] = "xterm-256color"
    env["COLUMNS"] = str(COLS)
    env["LINES"] = str(ROWS)

    proc = subprocess.Popen(
        ["claude", "--model", "sonnet"],
        stdin=slave, stdout=slave, stderr=slave,
        env=env, cwd=workdir, close_fds=True, start_new_session=True)
    os.close(slave)

    buf = bytearray()

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
            raw.write(data)
            raw.flush()
            buf.extend(data)

    # Startup gates (trust-the-folder, bypass-permissions warning) each render a
    # two-item menu whose first item is "No, exit". Answer whichever appear.
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

    # the interesting window: the tree appears and updates here
    drain(int(sys.argv[1]) if len(sys.argv) > 1 else 100)

    raw.close()
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
    print("wrote %s (%d bytes)" % (raw_path, os.path.getsize(raw_path)))


if __name__ == "__main__":
    main()
