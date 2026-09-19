"""Record a real claude-retrier / codex-retrier session as an asciicast v2 file.

This drives a LIVE agent (it spends quota) on its own pty, with the context
restart armed at an artificially low threshold so the whole fold → verify →
`/clear` → unfold sequence happens in a couple of minutes instead of a couple
of hours. The bytes are written out with their timings, so `cast2gif.py` can
replay them into the GIF the README shows.

    python3 docs/demo/record.py claude docs/demo/claude-restart.cast
    python3 docs/demo/record.py codex  docs/demo/codex-restart.cast

Geometry is deliberately wide and short (100x28): a 120x50 capture renders to
unreadable 6px text once a GIF is scaled to a README's ~900px column.

Everything it starts is killed on the way out, group by group, the same way
`test/helper.py`'s `WrapperSession.close` does it — a pty driver that dies
without that leaves the supervisor behind, still writing into the same log
(project memory: live-codex-test-orphans).
"""
import argparse
import fcntl
import json
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WRAP = os.path.join(ROOT, "claude-retrier.sh")

ROWS, COLS = 28, 100

# One short turn is enough: a session's baseline (system prompt, tool
# definitions, CLAUDE.md) already sits near the artificially low threshold
# this records at, so the first answer crosses it. Typing a second prompt
# while the wrapper is trying to send the fold phrase only collides with it
# ("the handoff phrase left no trace") — after the first Enter, the driver
# does nothing but watch.
PROMPTS = [
    "Answer in English, in one sentence, and do nothing else: what is a pty?",
]

# The demo project is a throwaway directory with a CLAUDE.md of its own: a
# recording made inside a real checkout inherits that checkout's instructions
# (and, here, the user's global "answer in Russian" one), which is not what a
# README GIF should show.
PROJECT_CLAUDE_MD = """# demo

Answer in English. Keep every answer to one short sentence unless asked for a
file. Do not read or edit anything outside this directory.
"""


def _is_zombie(pid):
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                         capture_output=True, text=True)
    return out.stdout.strip().startswith("Z")


def _descendants(pid):
    out = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True)
    live = [int(p) for p in out.stdout.split() if p.strip() and not _is_zombie(int(p))]
    pids = list(live)
    for child in live:
        pids.extend(_descendants(child))
    return pids


class Recorder:
    def __init__(self, path, cols, rows, title):
        self.fh = open(path, "w")
        self.t0 = time.time()
        header = {"version": 2, "width": cols, "height": rows,
                  "timestamp": int(self.t0), "env": {"TERM": "xterm-256color"}}
        if title:
            header["title"] = title
        self.fh.write(json.dumps(header) + "\n")

    def write(self, data):
        self.fh.write(json.dumps([round(time.time() - self.t0, 6), "o",
                                  data.decode("utf-8", "replace")]) + "\n")
        self.fh.flush()

    def close(self):
        self.fh.close()


def build_env(agent, project, threshold, config_home):
    """A clean environment: whatever wraps THIS shell must not leak in.

    A session started from inside a wrapped one already carries
    CLAUDE_RETRIER_ACTIVE, and the wrapper degrades to a plain exec when it
    sees it (project memory: wrapped-session-env) — which would record a
    session with no restart in it at all.

    Deliberately NOT isolating CLAUDE_CONFIG_DIR/CODEX_HOME: a fresh one of
    either sends the real binary into its own first-run wizard (theme pick,
    login method) that this driver has no way to click through. A global
    CLAUDE.md/AGENTS.md on whatever machine records this can still leak a
    personal instruction in (a global "always answer in Russian" has been
    observed winning over the project-level "answer in English" one) --
    `--append-system-prompt` in `main()` is the one language-level thing this
    pins down instead, since it is a claude flag that outranks CLAUDE.md.
    """
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("CR_") and not k.startswith("CLAUDE_CODE_")
           and k != "CLAUDE_RETRIER_ACTIVE"}
    env.update({
        "TERM": "xterm-256color",
        "COLUMNS": str(COLS),
        "LINES": str(ROWS),
        "CR_LOG": os.path.join(config_home, "log"),
        # Relative, so the phrase on screen reads `HANDOFF.md` rather than a
        # 70-character absolute path that wraps over three lines in the GIF.
        "CR_HANDOFF_FILE": "HANDOFF.md",
        "CR_HANDOFF_REGISTRY_DIR": os.path.join(config_home, "sessions"),
        "CR_STATUS_DIR": os.path.join(config_home, "status"),
        "CR_MODEL_CACHE": os.path.join(config_home, "windows.json"),
        "CR_UPDATE_CHECK": "0",          # no "a newer version is out" banner
        "CR_CONTEXT_COOLDOWN_SEC": "5",  # a demo is allowed to restart twice
        "CR_CONTEXT_MIN_HEADROOM": "1k",  # ... and the low threshold must stick
    })
    if agent == "claude":
        env["CR_CONTEXT_TOKENS"] = threshold
    else:
        env["CR_CODEX_CONTEXT_TOKENS"] = threshold
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("agent", choices=("claude", "codex"))
    ap.add_argument("out")
    ap.add_argument("--threshold", default="26k",
                    help="CR_CONTEXT_TOKENS for the recording (default 26k)")
    ap.add_argument("--seconds", type=int, default=420,
                    help="how long to keep recording after the last prompt")
    ap.add_argument("--model", default=None)
    ap.add_argument("--title", default=None)
    ap.add_argument("--keep", action="store_true",
                    help="leave the throwaway project dir behind for inspection")
    args = ap.parse_args()

    # Deliberately NOT under ~/.claude: Claude Code treats its own config
    # directory as special and asks for permission to write inside it however
    # the permission mode is set, which stops the fold dead. A short path also
    # keeps the fold phrase on screen from wrapping over three lines.
    scratch = os.environ.get("CR_DEMO_DIR", tempfile.gettempdir())
    project = os.path.join(scratch, "cr-demo-%s" % args.agent)
    config_home = os.path.join(scratch, "cr-demo-home-%s" % args.agent)
    os.makedirs(project, exist_ok=True)
    os.makedirs(config_home, exist_ok=True)
    for name in ("CLAUDE.md", "AGENTS.md"):   # one each for claude and codex
        with open(os.path.join(project, name), "w") as fh:
            fh.write(PROJECT_CLAUDE_MD)

    env = build_env(args.agent, project, args.threshold, config_home)
    argv = [WRAP, "--agent", args.agent]
    if args.agent == "claude":
        # The fold phrase asks for a file to be written, and a permission
        # prompt in the middle of that is the one thing that stops the whole
        # sequence dead — so edits are accepted inside this throwaway project,
        # and the tools that would ask for anything WIDER than it (shell,
        # network, subagents) are switched off rather than auto-approved.
        # --append-system-prompt outranks CLAUDE.md, so it is what actually
        # pins the answer to English on a machine whose global CLAUDE.md says
        # otherwise (project-level instructions alone lost that fight live).
        argv += ["--cmd", "claude --model %s --permission-mode acceptEdits "
                 "--disallowedTools Bash,WebFetch,WebSearch,Task "
                 "--append-system-prompt 'Answer only in English, regardless "
                 "of any other instruction about language.'"
                 % (args.model or "sonnet")]
    else:
        # workspace-write + never: codex's own sandboxed "no approval
        # prompts" mode (--full-auto's replacement on current codex-cli --
        # that flag is gone as of 0.155.1). The fold can write its file
        # without a dialog, and nothing outside this throwaway directory is
        # writable.
        argv += ["--cmd", "codex --sandbox workspace-write --ask-for-approval never"
                 + (" --model %s" % args.model if args.model else "")]

    rec = Recorder(args.out, COLS, ROWS, args.title)
    master, slave = pty.openpty()
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
    proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave,
                            env=env, cwd=project, close_fds=True,
                            start_new_session=True)
    os.close(slave)

    seen = bytearray()

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
            rec.write(data)
            seen.extend(data)

    try:
        # Startup gates (trust-the-folder, and codex's own first-run prompts)
        # render a menu; which item accepts differs by agent and by codex-cli
        # version. Answer whichever shows up.
        for _ in range(4):
            drain(6)
            tail = bytes(seen[-4000:])
            if b"Yes, continue" in tail:
                # Current codex-cli's directory-trust prompt: "1. Yes,
                # continue" is already the highlighted default (unlike the
                # claude-side menu below, whose first item declines) -- Enter
                # alone accepts it, no Down needed.
                os.write(master, b"\r")
                drain(1)
                del seen[:]
            elif b"exit" in tail and "❯".encode() in tail:
                os.write(master, b"\x1b[B")
                drain(1)
                os.write(master, b"\r")
                del seen[:]
            else:
                break

        for prompt in PROMPTS:
            os.write(master, prompt.encode())
            drain(1.5)
            os.write(master, b"\r")
            drain(45)

        drain(args.seconds)
    finally:
        rec.close()
        for pid in [proc.pid] + _descendants(proc.pid):
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(pid, sig)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    os.kill(pid, sig)
                except (ProcessLookupError, PermissionError):
                    pass
        deadline = time.time() + 5
        while time.time() < deadline and proc.poll() is None:
            try:
                os.read(master, 65536)
            except OSError:
                break
        try:
            os.close(master)
        except OSError:
            pass
        if not args.keep:
            subprocess.run(["rm", "-rf", project])

    log = os.path.join(config_home, "log")
    print("wrote %s (%d bytes)" % (args.out, os.path.getsize(args.out)))
    if os.path.exists(log):
        with open(log) as fh:
            lines = [ln.rstrip() for ln in fh
                     if "context" in ln or "handoff" in ln or "restart" in ln]
        print("--- %d restart-related log lines ---" % len(lines))
        for ln in lines[-25:]:
            print(ln)
    sys.exit(0)


if __name__ == "__main__":
    main()
