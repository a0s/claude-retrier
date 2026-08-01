"""End-to-end runs of wrap.sh against a real pty.

Two things are being proven here. First, that the wrapper is invisible during
ordinary use — keystrokes, exit codes, terminal size and window resizes all pass
through — because a wrapper that degrades the everyday session is worse than no
wrapper. Second, that a limit really does get detected and answered, through
each of the two channels, without tmux anywhere in the picture.
"""
import os
import pty
import select
import shutil
import signal
import struct
import subprocess
import fcntl
import sys
import termios
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRAP = os.path.join(ROOT, "wrap.sh")


def _fake_launcher():
    """A single-exec launcher for the fake claude.

    Running fake_claude.py via its `#!/usr/bin/env python3` shebang would pick up
    whatever `python3` resolves to — often a pyenv/asdf shim, i.e. a shell script
    that becomes an extra process in the chain. `exec` here keeps the process
    tree flat so the exit-status assertions below measure the wrapper, not the
    shim.
    """
    path = os.path.join(tempfile.mkdtemp(prefix="cw-fake-"), "claude")
    with open(path, "w") as fh:
        fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n'
                 % (sys.executable, os.path.join(ROOT, "test", "fake_claude.py")))
    os.chmod(path, 0o755)
    return path


FAKE = _fake_launcher()


class Session:
    """Runs wrap.sh on a pty we control, the way a terminal emulator would."""

    def __init__(self, env=None, args=(), rows=40, cols=120, cwd=None):
        self.master, slave = pty.openpty()
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        full = dict(os.environ)
        full.update({
            "CW_CLAUDE_BIN": FAKE,
            "CW_LOG": os.path.join(tempfile.gettempdir(), "cw-pty-test.log"),
            "CW_NOTIFY": "0",
            "PYTHONUNBUFFERED": "1",
        })
        full.update(env or {})
        self.proc = subprocess.Popen(
            [WRAP, *args], stdin=slave, stdout=slave, stderr=slave,
            env=full, cwd=cwd, close_fds=True, start_new_session=True)
        os.close(slave)
        self.buf = ""

    def read_until(self, needle, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if needle in self.buf:
                return True
            r, _, _ = select.select([self.master], [], [], 0.1)
            if not r:
                continue
            try:
                data = os.read(self.master, 65536)
            except OSError:
                break
            if not data:
                break
            self.buf += data.decode("utf-8", "replace")
        return needle in self.buf

    def drain(self, seconds=1.0):
        deadline = time.time() + seconds
        while time.time() < deadline:
            r, _, _ = select.select([self.master], [], [], 0.05)
            if not r:
                continue
            try:
                data = os.read(self.master, 65536)
            except OSError:
                break
            if not data:
                break
            self.buf += data.decode("utf-8", "replace")

    def send(self, text):
        os.write(self.master, text.encode())

    def resize(self, rows, cols):
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def wait(self, timeout=10):
        """Wait while still draining the pty.

        A session leader exiting with an unread output buffer is held in the
        kernel until that buffer is consumed, so a harness that stops reading
        would stall the process it is waiting on. Real terminals always read.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            rc = self.proc.poll()
            if rc is not None:
                self.drain(0.2)
                return rc
            self.drain(0.1)
        self.proc.kill()
        raise subprocess.TimeoutExpired(self.proc.args, timeout)

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=5)
        try:
            os.close(self.master)
        except OSError:
            pass


class PtyTestCase(unittest.TestCase):
    def session(self, **kw):
        s = Session(**kw)
        self.addCleanup(s.close)
        return s


class TestTransparency(PtyTestCase):
    def test_arguments_reach_claude(self):
        s = self.session(args=["--model", "opus", "--verbose"])
        self.assertTrue(s.read_until("argv=--model opus --verbose"))

    def test_terminal_size_is_propagated(self):
        s = self.session(rows=40, cols=120)
        self.assertTrue(s.read_until("winsize 120x40"))

    def test_keystrokes_pass_through(self):
        s = self.session()
        s.read_until("ready")
        s.send("hello world\r")
        self.assertTrue(s.read_until("GOT:hello world"))

    def test_control_characters_pass_through_unmangled(self):
        # Shift-Enter and friends are just escape sequences; upstream broke them
        # by routing input through `tmux send-keys` (issue #59). Here nothing
        # rewrites the byte stream, so an arbitrary sequence survives intact.
        s = self.session()
        s.read_until("ready")
        s.send("a\x1b[200~b\x1b[201~c\r")
        self.assertTrue(s.read_until("GOT:a\x1b[200~b\x1b[201~c"))

    def test_exit_code_is_preserved(self):
        s = self.session(env={"FAKE_EXIT": "42"})
        s.read_until("ready")
        s.send("quit\r")
        self.assertEqual(s.wait(), 42)

    def test_zero_exit_is_preserved(self):
        s = self.session(env={"FAKE_EXIT": "0"})
        s.read_until("ready")
        s.send("quit\r")
        self.assertEqual(s.wait(), 0)

    def test_resize_reaches_the_child(self):
        # A pane resize has to be forwarded onto the inner pty, or Claude keeps
        # rendering at the old width for the rest of the session.
        s = self.session(rows=24, cols=80)
        self.assertTrue(s.read_until("winsize 80x24"))
        s.resize(50, 100)
        time.sleep(0.3)
        s.send("winsize\r")
        self.assertTrue(s.read_until("winsize 100x50"))

    def test_signals_reach_the_child(self):
        # pty.fork puts claude in its own session, so a SIGTERM aimed at the
        # wrapper would otherwise leave the child running as an orphan.
        s = self.session()
        s.read_until("ready")
        s.proc.send_signal(signal.SIGTERM)
        self.assertEqual(s.wait(timeout=10), 128 + signal.SIGTERM)

    def test_wrapper_is_bypassed_when_disabled(self):
        s = self.session(env={"CW_DISABLE": "1"})
        self.assertTrue(s.read_until("ready"))
        s.send("quit\r")
        s.wait()


class TestScrapeChannel(PtyTestCase):
    """The fallback channel: the banner is only ever seen on screen."""

    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix="cw-cfg-")
        self.work = tempfile.mkdtemp(prefix="cw-work-")
        self.addCleanup(shutil.rmtree, self.cfg, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def env(self, **over):
        e = {
            "CLAUDE_CONFIG_DIR": self.cfg,
            "CW_SCRAPE": "always",
            "CW_WAIT_SCALE": "3600",     # an hour of waiting becomes a second
            "CW_MARGIN_SEC": "0",
            "CW_USER_IDLE_SEC": "0",
            "CW_BUSY_IDLE_SEC": "0.2",
        }
        e.update(over)
        return e

    def test_a_banner_on_screen_triggers_a_retry(self):
        s = self.session(
            env=self.env(FAKE_BANNER="You've hit your session limit - resets in 1 hours"),
            cwd=self.work)
        self.assertTrue(s.read_until("GOT:continue", timeout=20))

    def test_the_message_is_configurable(self):
        s = self.session(
            env=self.env(FAKE_BANNER="You've hit your session limit - resets in 1 hours",
                         CW_MESSAGE="please resume"),
            cwd=self.work)
        self.assertTrue(s.read_until("GOT:please resume", timeout=20))

    def test_ordinary_output_triggers_nothing(self):
        s = self.session(
            env=self.env(FAKE_BANNER="all done, no limits here"), cwd=self.work)
        s.read_until("all done")
        s.drain(3)
        self.assertNotIn("GOT:continue", s.buf)

    def test_text_about_a_limit_triggers_nothing(self):
        # A tool render quoting banner text: upstream #63, a 22-hour bogus wait.
        s = self.session(
            env=self.env(FAKE_BANNER='* Bash(grep "hit your session limit - resets 3pm (UTC)" log)'),
            cwd=self.work)
        s.read_until("Bash(grep")
        s.drain(3)
        self.assertNotIn("GOT:continue", s.buf)

    def test_a_busy_session_is_not_typed_into(self):
        s = self.session(
            env=self.env(FAKE_BANNER="You've hit your session limit - resets in 1 hours",
                         FAKE_WORKING="1", CW_BUSY_IDLE_SEC="30"),
            cwd=self.work)
        s.read_until("Cogitating")
        s.drain(4)
        self.assertNotIn("GOT:continue", s.buf)

    def test_an_unsent_draft_defers_the_retry(self):
        s = self.session(
            env=self.env(FAKE_BANNER="You've hit your session limit - resets in 1 hours",
                         CW_USER_IDLE_SEC="0"),
            cwd=self.work)
        s.read_until("session limit")
        s.send("half a thought")            # typed, never submitted
        s.drain(4)
        self.assertNotIn("GOT:continue", s.buf)
        s.send("\r")                        # the human submits it themselves
        self.assertTrue(s.read_until("GOT:continue", timeout=20))


class TestTranscriptChannel(PtyTestCase):
    """The primary channel: nothing is scraped, the JSONL record drives it."""

    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix="cw-cfg-")
        self.work = tempfile.mkdtemp(prefix="cw-work-")
        self.addCleanup(shutil.rmtree, self.cfg, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def test_a_rate_limit_record_triggers_a_retry(self):
        s = self.session(env={
            "CLAUDE_CONFIG_DIR": self.cfg,
            "CW_SCRAPE": "never",            # prove the transcript alone is enough
            "CW_WAIT_SCALE": "3600",
            "CW_MARGIN_SEC": "0",
            "CW_USER_IDLE_SEC": "0",
            "CW_POLL_SEC": "0.2",
            "FAKE_TRANSCRIPT": "You've hit your weekly limit - resets in 2 hours",
        }, cwd=self.work)
        self.assertTrue(s.read_until("GOT:continue", timeout=25))

    def test_a_live_transcript_turns_the_scraper_off(self):
        # Both channels active: the transcript is being written (so `seen_any`
        # is true), and the screen shows text that WOULD match the scraper. The
        # scraper must stand down rather than double-fire on the render.
        s = self.session(env={
            "CLAUDE_CONFIG_DIR": self.cfg,
            "CW_SCRAPE": "auto",
            "CW_WAIT_SCALE": "3600",
            "CW_MARGIN_SEC": "0",
            "CW_USER_IDLE_SEC": "0",
            "CW_POLL_SEC": "0.2",
            "FAKE_TRANSCRIPT_PLAIN": "ordinary turn",   # a non-limit record: just growth
            "FAKE_BANNER": "You've hit your session limit - resets in 1 hours",
        }, cwd=self.work)
        s.read_until("session limit")
        s.drain(4)
        self.assertNotIn("GOT:continue", s.buf)


if __name__ == "__main__":
    unittest.main(verbosity=2)
