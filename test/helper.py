"""Loads the implementation straight out of claude-retrier.sh.

Both the code and the pattern arrays come from the shell script itself, so a test
can never pass against a copy that has drifted from what actually ships.
"""
import fcntl
import importlib.util
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRAP = os.path.join(ROOT, "claude-retrier.sh")


def _dump(flag):
    return subprocess.run([WRAP, flag], capture_output=True, text=True, check=True).stdout


def pattern_env():
    """The CR_PAT_* environment exactly as claude-retrier.sh builds it."""
    env = {}
    name = None
    for line in _dump("--cr-dump-patterns").split("\n"):
        if line.startswith("### "):
            name = line[4:].strip()
            env[name] = []
        elif name and line.strip():
            env[name].append(line)
    return {k: "\n".join(v) for k, v in env.items()}


def load(**overrides):
    """Import the embedded Python as a module, with config from the environment.

    Inherited CR_* settings are dropped first: a suite run from inside a wrapped
    session would otherwise be testing the caller's tuning (and its
    CLAUDE_RETRIER_ACTIVE) rather than the defaults that ship.
    """
    for k in [k for k in os.environ if k.startswith("CR_")]:
        del os.environ[k]
    os.environ.pop("CLAUDE_RETRIER_ACTIVE", None)
    for k, v in pattern_env().items():
        os.environ[k] = v
    for k, v in overrides.items():
        os.environ[k] = str(v)
    os.environ.setdefault("CR_LOG", os.path.join(tempfile.gettempdir(), "claude-retrier-test.log"))

    src = _dump("--cr-dump-python")
    path = os.path.join(tempfile.mkdtemp(prefix="cr-"), "cr_impl.py")
    with open(path, "w") as fh:
        fh.write(src)
    spec = importlib.util.spec_from_file_location("cr_impl", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cr_impl"] = mod
    spec.loader.exec_module(mod)
    return mod


def _fake_bin(agent):
    """A single-exec launcher for fake_claude.py/fake_codex.py, named after the
    agent: claude-retrier's own auto-detection (`cr_looks_like_codex`) reads the
    resolved binary's path for a `codex` component, the same way it would for a
    real install, so the launcher has to be named exactly that.
    """
    script = "fake_claude.py" if agent == "claude" else "fake_codex.py"
    path = os.path.join(tempfile.mkdtemp(prefix="cr-fake-%s-" % agent), agent)
    with open(path, "w") as fh:
        fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n'
                 % (sys.executable, os.path.join(ROOT, "test", script)))
    os.chmod(path, 0o755)
    return path


def _descendant_pids(pid):
    """Every pid under `pid`, however many `setsid()` calls put distance
    between them — `pgrep -P` walks one generation at a time regardless."""
    try:
        out = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True)
    except OSError:
        return []
    children = [int(p) for p in out.stdout.split() if p.strip()]
    pids = list(children)
    for child in children:
        pids.extend(_descendant_pids(child))
    return pids


class WrapperSession:
    """One claude-retrier.sh instance on its own pty.

    Independent of test_pty.py's `Session`: this one has to run either agent,
    to be one of a pair sharing a project dir and a `CR_LOG`, and to guarantee
    its whole process group dies on close — a pty driver killed with a plain
    SIGTERM/`Popen.kill()` can leave its supervisor (and, in a live-codex run,
    codex itself) running as an orphan that keeps writing into that shared log
    (memory: live-codex-test-orphans). Built for `two_wrappers()`.
    """
    def __init__(self, cwd, log, env):
        env = dict(env or {})
        agent = env.pop("agent", "claude")
        self.agent = agent
        self.master, slave = pty.openpty()
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        full = {k: v for k, v in os.environ.items()
                if not k.startswith("CR_") and k not in ("CLAUDE_RETRIER_ACTIVE",)}
        full.update({
            "CR_CLAUDE_BIN": _fake_bin(agent),
            "CR_LOG": log,
            "CR_NOTIFY": "0",
            "CR_BADGE": "0",
            "PYTHONUNBUFFERED": "1",
        })
        full.update(env)
        self.log = log
        self.proc = subprocess.Popen(
            [WRAP], stdin=slave, stdout=slave, stderr=slave,
            env=full, cwd=cwd, close_fds=True, start_new_session=True)
        os.close(slave)
        self.buf = ""

    @property
    def pid(self):
        return self.proc.pid

    def agent_pid(self):
        """The pid of the fake claude/codex under us — what its own
        `sessions/<pid>.json` (T02) is named after, distinct from `.pid`."""
        children = _descendant_pids(self.proc.pid)
        return children[0] if children else None

    def _drain_once(self):
        r, _, _ = select.select([self.master], [], [], 0.1)
        if not r:
            return
        try:
            data = os.read(self.master, 65536)
        except OSError:
            return
        if data:
            self.buf += data.decode("utf-8", "replace")

    def read_until(self, needle, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if needle in self.buf:
                return True
            self._drain_once()
        return needle in self.buf

    def send(self, text):
        os.write(self.master, text.encode())

    def wait(self, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            rc = self.proc.poll()
            if rc is not None:
                return rc
            self._drain_once()
        self.close()
        raise subprocess.TimeoutExpired(self.proc.args, timeout)

    def log_lines(self):
        """This wrapper's own lines out of the shared `CR_LOG`, by its T01 pid tag."""
        tag = "[cr %d " % self.pid
        if not os.path.exists(self.log):
            return []
        with open(self.log) as fh:
            return [ln for ln in fh if tag in ln]

    def close(self):
        if self.proc.poll() is None:
            # The wrapper puts the agent it launches in its OWN session
            # (`os.setsid()`, claude-retrier.sh's forkpty-alike, so a signal
            # aimed at us never lands mid-keystroke on it) — which means
            # `killpg` on our pid alone leaves it running. Kill every pid in
            # the tree individually, group by group, each a leader of its own.
            for pid in [self.proc.pid] + _descendant_pids(self.proc.pid):
                try:
                    os.killpg(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            # A killed process holding the pty slave can sit "trying to exit"
            # until the master side is drained (unread output wedges teardown
            # on macOS) — plain `proc.wait()` alone can hang the full timeout.
            deadline = time.time() + 5
            while time.time() < deadline and self.proc.poll() is None:
                self._drain_once()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        try:
            os.close(self.master)
        except OSError:
            pass


def two_wrappers(project_dir, cfg_a, cfg_b):
    """Two claude-retrier.sh wrappers sharing one project dir and one `CR_LOG`.

    The bug class this exists for (T02/T04/T05: one session reading another's
    transcript) only reproduces with both wrappers alive over the same
    project-dir at once — a single `Session` (test_pty.py) can never show it.

    `cfg_a`/`cfg_b` are env overrides for each wrapper; `agent` in either
    (default `"claude"`) picks `fake_claude.py` or `fake_codex.py`. Returns
    `(a, b)`, each a `WrapperSession`. Callers should register both for
    cleanup (e.g. `self.addCleanup(a.close)`) so a failed test still cannot
    leave a supervisor running.
    """
    os.makedirs(project_dir, exist_ok=True)
    shared_dir = tempfile.mkdtemp(prefix="cr-two-")
    log = os.path.join(shared_dir, "shared.log")
    base = {
        "CLAUDE_CONFIG_DIR": os.path.join(shared_dir, "claude-config"),
        "CODEX_HOME": os.path.join(shared_dir, "codex-home"),
    }
    a_env = dict(base)
    a_env.update(cfg_a or {})
    b_env = dict(base)
    b_env.update(cfg_b or {})
    a = WrapperSession(cwd=project_dir, log=log, env=a_env)
    b = WrapperSession(cwd=project_dir, log=log, env=b_env)
    return a, b
