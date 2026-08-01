"""The shell layer, and every path where the wrapper must get out of the way.

Upstream's sharpest failure was not a missed retry: it was issue #65, where an
uninstalled wrapper left `claude` unable to start at all. A wrapper is only
acceptable if every failure mode degrades to plain claude.
"""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRAP = os.path.join(ROOT, "claude-retrier.sh")
FAKE_SRC = os.path.join(ROOT, "test", "fake_claude.py")


def launcher(dirpath, body=None):
    path = os.path.join(dirpath, "claude")
    with open(path, "w") as fh:
        fh.write(body or '#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, FAKE_SRC))
    os.chmod(path, 0o755)
    return path


def run(args=(), env=None, stdin=subprocess.DEVNULL, timeout=30):
    full = dict(os.environ)
    full.setdefault("CR_NOTIFY", "0")
    full.update(env or {})
    return subprocess.run([WRAP, *args], env=full, stdin=stdin,
                          capture_output=True, text=True, timeout=timeout)


class TestCli(unittest.TestCase):
    def test_version(self):
        self.assertIn("claude-retrier", run(["--cr-version"]).stdout)

    def test_dump_python_is_valid_python(self):
        src = run(["--cr-dump-python"]).stdout
        compile(src, "embedded", "exec")

    def test_dump_patterns_lists_every_array(self):
        out = run(["--cr-dump-patterns"]).stdout
        for name in ("LIMIT", "RESET", "WORKING", "MENU", "IGNORE"):
            self.assertIn("### CR_PAT_%s" % name, out)
        self.assertIn("hit your", out)

    def test_shell_syntax_is_valid_under_bash(self):
        self.assertEqual(subprocess.run(["bash", "-n", WRAP]).returncode, 0)


class TestDegradation(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cr-deg-")
        self.claude = launcher(self.dir)
        self.log = os.path.join(self.dir, "log")

    def env(self, **over):
        e = {"CR_CLAUDE_BIN": self.claude, "CR_LOG": self.log}
        e.update(over)
        return e

    def supervised(self):
        """Did the pty supervisor actually run? It is the only thing that logs."""
        return os.path.exists(self.log) and "start:" in open(self.log).read()

    def test_print_mode_runs_claude_directly(self):
        # `claude -p` is a batch run with no TUI to type into; supervising it
        # would add a pty for nothing and break piping.
        r = run(["-p", "hello"], env=self.env(), timeout=20)
        self.assertIn("fake-claude ready", r.stdout)
        self.assertFalse(self.supervised())

    def test_long_form_print_flag_too(self):
        run(["--print"], env=self.env(), timeout=20)
        self.assertFalse(self.supervised())

    def test_disable_flag_runs_claude_directly(self):
        r = run(env=self.env(CR_DISABLE="1"), timeout=20)
        self.assertIn("fake-claude ready", r.stdout)
        self.assertFalse(self.supervised())

    def test_recursion_is_refused(self):
        # If a wrapped session somehow invokes `claude` again, the inner call
        # must not stack a second pty supervisor on top of the first.
        r = run(env=self.env(CLAUDE_RETRIER_ACTIVE="1"), timeout=20)
        self.assertIn("fake-claude ready", r.stdout)
        self.assertFalse(self.supervised())

    def test_missing_claude_reports_clearly(self):
        empty = tempfile.mkdtemp(prefix="cr-empty-")
        r = run(env={"PATH": "%s:/usr/bin:/bin" % empty, "HOME": empty,
                     "CR_CLAUDE_BIN": "", "CR_CLAUDE_FALLBACKS": empty})
        self.assertEqual(r.returncode, 127)
        self.assertIn("not found", r.stderr)

    def test_an_unrunnable_override_is_reported_not_ignored(self):
        r = run(env=self.env(CR_CLAUDE_BIN=os.path.join(self.dir, "nope")))
        self.assertEqual(r.returncode, 127)

    def test_unusable_python_still_runs_claude(self):
        # No interpreter with the modules we need => the session must still start,
        # unsupervised. This is the single most important degradation path: a
        # missing dependency of the WRAPPER must never cost the user their claude.
        r = run(env=self.env(CR_PYTHON="", CR_PYTHON_CANDIDATES="/nonexistent/python"),
                timeout=20)
        self.assertIn("fake-claude ready", r.stdout)
        self.assertFalse(self.supervised())

    def test_a_claude_that_fails_still_reports_its_status(self):
        broken = launcher(self.dir, '#!/bin/sh\necho "boom" >&2\nexit 3\n')
        r = run(env=self.env(CR_CLAUDE_BIN=broken), timeout=20)
        self.assertEqual(r.returncode, 3)
        self.assertIn("boom", r.stdout + r.stderr)

    def test_it_works_without_a_tty_at_all(self):
        # Piped stdin/stdout: the supervisor still runs, just with no raw mode.
        r = subprocess.run([WRAP], env={**os.environ, **self.env(), "CR_NOTIFY": "0"},
                           input="quit\n", capture_output=True, text=True, timeout=25)
        self.assertIn("fake-claude ready", r.stdout)
        self.assertTrue(self.supervised())


class TestPatternRobustness(unittest.TestCase):
    def test_a_broken_user_pattern_is_skipped_not_fatal(self):
        from helper import load
        mod = load(CR_PAT_LIMIT="you've hit your session limit\n[unclosed(")
        self.assertEqual(len(mod.PAT["limit"]), 1)
        self.assertTrue(mod.is_limit_line("You've hit your session limit"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
