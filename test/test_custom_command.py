"""Whatever the user types to start Claude, the wrapper has to accept it.

Nobody runs stock `claude` for long: people end up with `claude-work` and
`claude-personal`, sometimes a binary, more often an alias or a shell function in
~/.zshrc that pins a model or a settings file. The wrapper cannot know which, so
it has to handle all of them — and an alias in particular exists nowhere except
inside an interactive shell that has read the rc file.

Every shape is exercised twice where it matters: once through the fast degrade
path (`-p`, no supervisor), and once through the pty supervisor, because the two
reach exec by different routes.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_pty import PtyTestCase, FAKE          # noqa: E402  (pty harness, reused)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRAP = os.path.join(ROOT, "claude-retrier.sh")


def has(shell):
    return shutil.which(shell) is not None


class Rig:
    """A HOME with rc files defining an alias and a function for both shells."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="cr-cmd-")
        self.bin = os.path.join(self.dir, "bin")
        os.makedirs(self.bin)
        # The stand-in claude, reachable by path and by name on PATH.
        self.claude = os.path.join(self.bin, "my-claude")
        with open(self.claude, "w") as fh:
            fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n'
                     % (sys.executable, os.path.join(ROOT, "test", "fake_claude.py")))
        os.chmod(self.claude, 0o755)

        rc = ("alias claude-work='\"%s\" --model opus'\n"
              "claude-personal() { \"%s\" --fn \"$@\"; }\n" % (self.claude, self.claude))
        self.zdotdir = os.path.join(self.dir, "zdot")
        os.makedirs(self.zdotdir)
        for path in (os.path.join(self.dir, ".bashrc"),
                     os.path.join(self.zdotdir, ".zshrc")):
            with open(path, "w") as fh:
                fh.write(rc)

    def env(self, shell="bash", **over):
        e = {
            "HOME": self.dir,                   # bash -i reads $HOME/.bashrc
            "ZDOTDIR": self.zdotdir,            # zsh -i reads $ZDOTDIR/.zshrc
            "CR_SHELL": shell,
            "CR_CLAUDE_BIN": "",
            "CR_NOTIFY": "0",
            "PATH": self.bin + os.pathsep + os.environ.get("PATH", ""),
        }
        e.update(over)
        return e

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def run(args, env, timeout=30):
    full = dict(os.environ)
    full.update(env)
    return subprocess.run([WRAP, *args], env=full, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=timeout)


class CommandShapes(unittest.TestCase):
    """`-p` degrades to a direct exec, which is the cheapest way to see argv."""

    def setUp(self):
        self.rig = Rig()
        self.addCleanup(self.rig.cleanup)

    def argv_of(self, out):
        """What the stand-in claude saw, as one string."""
        for line in out.splitlines():
            if line.startswith("fake-claude ready argv="):
                return line.split("argv=", 1)[1].strip()
        self.fail("claude never started; output was:\n%s" % out)

    # --- the shapes ---------------------------------------------------------

    def test_an_absolute_path(self):
        r = run(["--cr-cmd", self.rig.claude, "-p", "hi"], self.rig.env())
        self.assertEqual(self.argv_of(r.stdout), "-p hi")

    def test_a_relative_path(self):
        rel = os.path.relpath(self.rig.claude, os.getcwd())
        r = run(["--cr-cmd", rel, "-p", "hi"], self.rig.env())
        self.assertEqual(self.argv_of(r.stdout), "-p hi")

    def test_a_name_on_path(self):
        r = run(["--cr-cmd", "my-claude", "-p", "hi"], self.rig.env())
        self.assertEqual(self.argv_of(r.stdout), "-p hi")

    def test_a_command_line_with_its_own_arguments(self):
        r = run(["--cr-cmd", '%s --model sonnet' % self.rig.claude, "-p", "hi"],
                self.rig.env())
        self.assertEqual(self.argv_of(r.stdout), "--model sonnet -p hi")

    @unittest.skipUnless(has("bash"), "no bash")
    def test_a_bash_alias(self):
        r = run(["--cr-cmd", "claude-work", "-p", "hi"], self.rig.env("bash"))
        self.assertEqual(self.argv_of(r.stdout), "--model opus -p hi")

    @unittest.skipUnless(has("zsh"), "no zsh")
    def test_a_zsh_alias(self):
        r = run(["--cr-cmd", "claude-work", "-p", "hi"], self.rig.env("zsh"))
        self.assertEqual(self.argv_of(r.stdout), "--model opus -p hi")

    @unittest.skipUnless(has("bash"), "no bash")
    def test_a_bash_function(self):
        r = run(["--cr-cmd", "claude-personal", "-p", "hi"], self.rig.env("bash"))
        self.assertEqual(self.argv_of(r.stdout), "--fn -p hi")

    @unittest.skipUnless(has("zsh"), "no zsh")
    def test_a_zsh_function(self):
        r = run(["--cr-cmd", "claude-personal", "-p", "hi"], self.rig.env("zsh"))
        self.assertEqual(self.argv_of(r.stdout), "--fn -p hi")

    @unittest.skipUnless(has("zsh"), "no zsh")
    def test_an_alias_resolves_without_an_interactive_shell_on_stderr(self):
        # Resolving the alias to its body keeps `sh -i` out of the final exec, so
        # a scripted `claude -p …` gets a clean stderr rather than job-control
        # chatter from a shell that has no terminal.
        r = run(["--cr-cmd", "claude-work", "-p", "hi"], self.rig.env("zsh"))
        self.assertEqual(r.stderr.strip(), "")

    # --- how it is spelled --------------------------------------------------

    def test_the_equals_form(self):
        r = run(["--cr-cmd=%s" % self.rig.claude, "-p", "hi"], self.rig.env())
        self.assertEqual(self.argv_of(r.stdout), "-p hi")

    def test_the_environment_variable(self):
        r = run(["-p", "hi"], self.rig.env(CR_CLAUDE_CMD=self.rig.claude))
        self.assertEqual(self.argv_of(r.stdout), "-p hi")

    def test_the_flag_wins_over_the_environment(self):
        env = self.rig.env(CR_CLAUDE_CMD="/nonexistent/claude")
        r = run(["--cr-cmd", self.rig.claude, "-p", "hi"], env)
        self.assertEqual(self.argv_of(r.stdout), "-p hi")

    # --- what must NOT happen ----------------------------------------------

    def test_a_prompt_is_not_mistaken_for_a_command(self):
        # `claude "fix the bug"` is a legitimate invocation: claude takes a bare
        # prompt as its first argument. Guessing the command positionally would
        # eat it, so only the explicit flag may set the command.
        r = run(["-p", "fix the bug"], self.rig.env(CR_CLAUDE_CMD=self.rig.claude))
        self.assertEqual(self.argv_of(r.stdout), "-p fix the bug")

    def test_claude_flags_are_not_consumed(self):
        r = run(["--cr-cmd", self.rig.claude, "-p", "--model", "opus", "x"],
                self.rig.env())
        self.assertEqual(self.argv_of(r.stdout), "-p --model opus x")

    def test_an_unknown_command_fails_loudly(self):
        # Not a silent fallback to some other claude: the user named a command,
        # and running a different one would be worse than not starting.
        r = run(["--cr-cmd", "no-such-claude-anywhere", "-p", "hi"], self.rig.env())
        self.assertEqual(r.returncode, 127)
        self.assertIn("no-such-claude-anywhere", r.stderr)

    def test_a_path_that_is_not_executable_fails_loudly(self):
        dud = os.path.join(self.rig.dir, "not-executable")
        open(dud, "w").close()
        r = run(["--cr-cmd", dud, "-p", "hi"], self.rig.env())
        self.assertEqual(r.returncode, 127)

    def test_the_flag_needs_an_argument(self):
        r = run(["--cr-cmd"], self.rig.env())
        self.assertEqual(r.returncode, 2)

    def test_a_command_pointing_back_at_the_wrapper_is_stopped(self):
        # The nightmare case: CR_CLAUDE_CMD naming the wrapper itself. Unlike the
        # flag, the variable is inherited by every exec, so each level would start
        # another wrapper — forever. The depth counter has to stop it, quickly.
        env = self.rig.env(CR_CLAUDE_CMD=WRAP, CR_CLAUDE_FALLBACKS="")
        r = run(["-p", "hi"], env, timeout=30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("recurse", r.stderr)

    @unittest.skipUnless(has("zsh"), "no zsh")
    def test_an_alias_pointing_back_at_the_wrapper_is_stopped(self):
        # The same loop by another route: `alias claude='claude-retrier.sh …'`,
        # which is exactly how someone would wire this into their rc file.
        with open(os.path.join(self.rig.zdotdir, ".zshrc"), "w") as fh:
            fh.write("alias claude='%s --cr-cmd claude'\n" % WRAP)
        # A PATH without a real `claude` on it, or the name would resolve to that
        # instead and the loop this test is about would never form.
        env = self.rig.env("zsh", CR_CLAUDE_FALLBACKS="",
                           PATH=os.pathsep.join([self.rig.bin, "/usr/bin", "/bin"]))
        r = run(["--cr-cmd", "claude", "-p", "hi"], env, timeout=30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("recurse", r.stderr)


class SupervisedCustomCommand(PtyTestCase):
    """The same shapes, but under the pty supervisor — the path that matters."""

    def setUp(self):
        self.rig = Rig()
        self.addCleanup(self.rig.cleanup)
        self.cfg = tempfile.mkdtemp(prefix="cr-cfg-")
        self.work = tempfile.mkdtemp(prefix="cr-work-")
        self.addCleanup(shutil.rmtree, self.cfg, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def env(self, shell="bash", **over):
        e = self.rig.env(shell)
        e.update({
            "CLAUDE_CONFIG_DIR": self.cfg,
            "CR_SCRAPE": "always",
            "CR_WAIT_SCALE": "3600",     # an hour of waiting becomes a second
            "CR_MARGIN_SEC": "0",
            "CR_USER_IDLE_SEC": "0",
            "CR_BUSY_IDLE_SEC": "0.2",
            "CR_LOG": os.path.join(self.rig.dir, "log"),
        })
        e.update(over)
        return e

    def test_a_binary_is_supervised(self):
        s = self.session(env=self.env(), args=["--cr-cmd", self.rig.claude],
                         cwd=self.work)
        self.assertTrue(s.read_until("fake-claude ready"))

    @unittest.skipUnless(has("zsh"), "no zsh")
    def test_an_alias_is_supervised_and_retried(self):
        # The whole point: a user whose claude is an alias still gets the retry.
        s = self.session(
            env=self.env("zsh", FAKE_BANNER="You've hit your session limit - resets in 1 hours"),
            args=["--cr-cmd", "claude-work"], cwd=self.work)
        self.assertTrue(s.read_until("GOT:continue", timeout=25))

    @unittest.skipUnless(has("zsh"), "no zsh")
    def test_a_function_is_supervised_and_retried(self):
        s = self.session(
            env=self.env("zsh", FAKE_BANNER="You've hit your session limit - resets in 1 hours"),
            args=["--cr-cmd", "claude-personal"], cwd=self.work)
        self.assertTrue(s.read_until("GOT:continue", timeout=25))

    @unittest.skipUnless(has("zsh"), "no zsh")
    def test_the_exit_code_survives_the_shell_in_between(self):
        # An alias runs through a shell, which is one more process to lose the
        # status in. `claude` exiting 3 must still be 3 to the caller.
        s = self.session(env=self.env("zsh", FAKE_EXIT="3"),
                         args=["--cr-cmd", "claude-work"], cwd=self.work)
        s.read_until("fake-claude ready")
        s.send("quit\n")
        self.assertEqual(s.wait(timeout=15), 3)

    def test_arguments_still_reach_claude(self):
        s = self.session(env=self.env(),
                         args=["--cr-cmd", self.rig.claude, "--verbose"], cwd=self.work)
        self.assertTrue(s.read_until("argv=--verbose"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
