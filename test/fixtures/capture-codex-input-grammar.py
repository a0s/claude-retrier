"""Live driver for T15: what real codex-cli does with `/clear`, `/new`,
`$skill ...`, `@file`, `/prompts:`, and Cyrillic input, and whether an
ordinary phrase gets through right after `/clear`.

Basis: capture-agents-panel.py (T29) -- same pty-driver shape, but this one
talks to real codex-cli (not claude) and inspects the resulting rollout file
under ~/.codex/sessions instead of the screen render, because the thing T15
needs to know is whether a MESSAGE WAS SENT, not how a panel is drawn.

Run one scenario per process (`--scenario N`), each in its own fresh codex
session -- state never carries between scenarios, so a single scenario can be
rerun (e.g. 3x for T16's AC) without the others' history in the way. Uses the
cheapest available model (gpt-5.6-luna) with low reasoning effort and a
"reply in <=3 words" system nudge, since this is testing keystrokes, not
answers.

Safety: `--dangerously-bypass-approvals-and-sandbox` skips the folder-trust
and command-approval prompts this throwaway project dir would otherwise
trigger; the model is told to run no commands so the flag is never exercised.
Always kills the whole process group on exit (a killed pty driver otherwise
leaves the supervisor behind, still writing to the same rollout --
`live-codex-test-orphans` memory).
"""
import fcntl
import glob
import json
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import time

ROWS, COLS = 50, 120
MODEL = "gpt-5.6-luna"
PROJ = os.environ.get("CR_T15_PROJ") or "/tmp/codex-t15-proj"
SYSTEM_NUDGE = ("For this whole session, reply to every message in 3 words "
                "or fewer and never run a shell command or tool call.")


def spawn(cwd, extra_args=()):
    master, slave = pty.openpty()
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
    env = {k: v for k, v in os.environ.items() if not k.startswith("CR_")}
    env["TERM"] = "xterm-256color"
    env["COLUMNS"], env["LINES"] = str(COLS), str(ROWS)
    argv = ["codex", "-m", MODEL, "-c", "model_reasoning_effort=\"low\"",
            "-a", "never", "-s", "read-only"] + list(extra_args)
    proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave,
                             env=env, cwd=cwd, close_fds=True, start_new_session=True)
    os.close(slave)
    return proc, master


def cleanup(proc, master):
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        time.sleep(0.4)
        if proc.poll() is not None:
            break
    try:
        os.close(master)
    except OSError:
        pass


class Session(object):
    def __init__(self, cwd):
        self.cwd = cwd
        self.proc, self.master = spawn(cwd)
        self.buf = bytearray()
        self._accept_trust_prompt()

    def _accept_trust_prompt(self):
        """A scratch project dir outside the trusted-projects list gets a
        one-time 'Do you trust the contents of this directory?' gate before
        the composer appears. Option 1 ('Yes, continue') is already
        highlighted, so plain Enter accepts it."""
        for _ in range(3):
            self.drain(2)
            tail = bytes(self.buf[-4000:])
            if b"trust the contents" in tail:
                self.write(b"\r")
                self.drain(1)
                del self.buf[:]
            else:
                break

    def drain(self, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            r, _, _ = select.select([self.master], [], [], 0.15)
            if not r:
                continue
            try:
                data = os.read(self.master, 65536)
            except OSError:
                return
            if not data:
                return
            self.buf.extend(data)

    def write(self, data):
        os.write(self.master, data if isinstance(data, bytes) else data.encode())

    def screen_text(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        from helper import load
        Screen = load().Screen
        scr = Screen(ROWS, COLS)
        scr.feed(bytes(self.buf).decode("utf-8", "replace"))
        return scr.text()

    def close(self):
        cleanup(self.proc, self.master)


def rollouts_snapshot():
    return set(glob.glob(os.path.expanduser("~/.codex/sessions/*/*/*/rollout-*.jsonl")))


def new_rollouts(before):
    return sorted(rollouts_snapshot() - before,
                  key=lambda p: os.path.getmtime(p))


def rollout_user_texts(path):
    out = []
    try:
        with open(path) as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                payload = row.get("payload") or {}
                if payload.get("type") == "message" and payload.get("role") == "user":
                    for part in payload.get("content") or []:
                        if part.get("type") == "input_text":
                            out.append(part.get("text"))
    except OSError:
        pass
    return out


def report(label, sess, before_rollouts, extra=None):
    print("=" * 20, label, "=" * 20)
    news = new_rollouts(before_rollouts)
    print("new rollout files: %d" % len(news))
    for p in news:
        texts = rollout_user_texts(p)
        print("  %s -> user texts: %r" % (os.path.basename(p), texts))
    if extra:
        print("note:", extra)
    print("---- final screen (non-blank, up to 20 lines) ----")
    lines = [ln for ln in sess.screen_text().splitlines() if ln.strip()]
    for ln in lines[-20:]:
        print(" |%s" % ln)
    print()


def scenario_1_clear():
    sess = Session(PROJ)
    before = rollouts_snapshot()
    sess.drain(3)
    sess.write(SYSTEM_NUDGE + " Say ready.")
    sess.drain(0.6)
    sess.write(b"\r")
    sess.drain(6)
    t0 = time.time()
    sess.write("/clear")
    sess.drain(0.6)
    sess.write(b"\r")
    sess.drain(0.6)
    sess.write(b"\r")
    sess.drain(3)
    accepted_at = time.time() - t0
    report("1 /clear", sess, before, extra="elapsed since /clear typed: %.1fs" % accepted_at)
    sess.close()


def scenario_2_new():
    sess = Session(PROJ)
    before = rollouts_snapshot()
    sess.drain(3)
    sess.write(SYSTEM_NUDGE + " Say ready.")
    sess.drain(0.6)
    sess.write(b"\r")
    sess.drain(6)
    sess.write("/new")
    sess.drain(0.6)
    sess.write(b"\r")
    sess.drain(0.6)
    sess.write(b"\r")
    sess.drain(3)
    report("2 /new", sess, before)
    sess.close()


def scenario_3_skill_06():
    sess = Session(PROJ)
    before = rollouts_snapshot()
    sess.drain(3)
    sess.write("$supervisor continue scratchpad/RESUME.md")
    sess.drain(0.6)
    sess.write(b"\r")
    sess.drain(4)
    report("3 $skill + Enter@0.6s", sess, before)
    sess.close()


def scenario_4_skill_09_two_enter():
    sess = Session(PROJ)
    before = rollouts_snapshot()
    sess.drain(3)
    sess.write("$supervisor continue scratchpad/RESUME.md")
    sess.drain(0.9)
    sess.write(b"\r")
    sess.drain(0.6)
    sess.write(b"\r")
    sess.drain(4)
    report("4 $skill + 0.9s + 2xEnter", sess, before)
    sess.close()


def scenario_5_skill_separate_space():
    sess = Session(PROJ)
    before = rollouts_snapshot()
    sess.drain(3)
    sess.write("$supervisor")
    sess.drain(0.3)
    sess.write(" continue scratchpad/RESUME.md")
    sess.drain(0.6)
    sess.write(b"\r")
    sess.drain(4)
    report("5 $skill + separate space@0.3s", sess, before)
    sess.close()


def scenario_6_at_and_prompts():
    sess = Session(PROJ)
    before = rollouts_snapshot()
    sess.drain(3)
    sess.write("@README.md summarize this file in 3 words")
    sess.drain(0.9)
    sess.write(b"\r")
    sess.drain(4)
    report("6a @file mention", sess, before)
    sess.close()

    sess = Session(PROJ)
    before = rollouts_snapshot()
    sess.drain(3)
    sess.write("/prompts:list")
    sess.drain(0.9)
    sess.write(b"\r")
    sess.drain(4)
    report("6b /prompts:", sess, before)
    sess.close()


def scenario_7_cyrillic():
    sess = Session(PROJ)
    before = rollouts_snapshot()
    sess.drain(3)
    sess.write(SYSTEM_NUDGE + " ")
    sess.write("Ответь одним словом — привет!")
    sess.drain(0.6)
    sess.write(b"\r")
    sess.drain(4)
    report("7 cyrillic", sess, before)
    sess.close()


def scenario_8_after_clear_plain():
    sess = Session(PROJ)
    before = rollouts_snapshot()
    sess.drain(3)
    sess.write(SYSTEM_NUDGE + " Say ready.")
    sess.drain(0.6)
    sess.write(b"\r")
    sess.drain(6)
    sess.write("/clear")
    sess.drain(0.6)
    sess.write(b"\r")
    sess.drain(0.6)
    sess.write(b"\r")
    sess.drain(3)
    sess.write("Say hello in one word.")
    sess.drain(0.6)
    sess.write(b"\r")
    sess.drain(4)
    report("8 plain phrase 3s after /clear", sess, before)
    sess.close()


SCENARIOS = {
    "1": scenario_1_clear,
    "2": scenario_2_new,
    "3": scenario_3_skill_06,
    "4": scenario_4_skill_09_two_enter,
    "5": scenario_5_skill_separate_space,
    "6": scenario_6_at_and_prompts,
    "7": scenario_7_cyrillic,
    "8": scenario_8_after_clear_plain,
}


def main():
    os.makedirs(os.path.join(PROJ, "scratchpad"), exist_ok=True)
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    names = SCENARIOS.keys() if which == "all" else [which]
    for n in sorted(names, key=lambda x: int(x)):
        SCENARIOS[n]()


if __name__ == "__main__":
    main()
