"""End-to-end runs of claude-retrier.sh against a real pty.

Two things are being proven here. First, that the wrapper is invisible during
ordinary use — keystrokes, exit codes, terminal size and window resizes all pass
through — because a wrapper that degrades the everyday session is worse than no
wrapper. Second, that a limit really does get detected and answered, through
each of the two channels, without tmux anywhere in the picture.
"""
import os
import pty
import re
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

from screen import Screen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRAP = os.path.join(ROOT, "claude-retrier.sh")


def _fake_launcher():
    """A single-exec launcher for the fake claude.

    Running fake_claude.py via its `#!/usr/bin/env python3` shebang would pick up
    whatever `python3` resolves to — often a pyenv/asdf shim, i.e. a shell script
    that becomes an extra process in the chain. `exec` here keeps the process
    tree flat so the exit-status assertions below measure the wrapper, not the
    shim.
    """
    path = os.path.join(tempfile.mkdtemp(prefix="cr-fake-"), "claude")
    with open(path, "w") as fh:
        fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n'
                 % (sys.executable, os.path.join(ROOT, "test", "fake_claude.py")))
    os.chmod(path, 0o755)
    return path


FAKE = _fake_launcher()


class Session:
    """Runs claude-retrier.sh on a pty we control, the way a terminal emulator would."""

    def __init__(self, env=None, args=(), rows=40, cols=120, cwd=None):
        self.master, slave = pty.openpty()
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        # A test run started from inside a wrapped session would inherit
        # CLAUDE_RETRIER_ACTIVE=1 (and the caller's tuning), and every wrapper
        # under test would dutifully degrade into a plain exec. Start clean.
        full = {k: v for k, v in os.environ.items()
                if not k.startswith("CR_")
                and k not in ("CLAUDE_RETRIER_ACTIVE", "CLAUDE_CONFIG_DIR")}
        full.update({
            "CR_CLAUDE_BIN": FAKE,
            "CR_LOG": os.path.join(tempfile.gettempdir(), "cr-pty-test.log"),
            "CR_NOTIFY": "0",
            "CR_BADGE": "0",             # off unless a test is about the badge
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
        s = self.session(env={"CR_DISABLE": "1"})
        self.assertTrue(s.read_until("ready"))
        s.send("quit\r")
        s.wait()


class TestScrapeChannel(PtyTestCase):
    """The fallback channel: the banner is only ever seen on screen."""

    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix="cr-cfg-")
        self.work = tempfile.mkdtemp(prefix="cr-work-")
        self.addCleanup(shutil.rmtree, self.cfg, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def env(self, **over):
        e = {
            "CLAUDE_CONFIG_DIR": self.cfg,
            "CR_SCRAPE": "always",
            "CR_WAIT_SCALE": "3600",     # an hour of waiting becomes a second
            "CR_MARGIN_SEC": "0",
            "CR_USER_IDLE_SEC": "0",
            "CR_BUSY_IDLE_SEC": "0.2",
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
                         CR_MESSAGE="please resume"),
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
                         FAKE_WORKING="1", CR_BUSY_IDLE_SEC="30"),
            cwd=self.work)
        s.read_until("Cogitating")
        s.drain(4)
        self.assertNotIn("GOT:continue", s.buf)

    def test_an_unsent_draft_defers_the_retry(self):
        s = self.session(
            env=self.env(FAKE_BANNER="You've hit your session limit - resets in 1 hours",
                         CR_USER_IDLE_SEC="0"),
            cwd=self.work)
        s.read_until("session limit")
        s.send("half a thought")            # typed, never submitted
        s.drain(4)
        self.assertNotIn("GOT:continue", s.buf)
        s.send("\r")                        # the human submits it themselves
        self.assertTrue(s.read_until("GOT:continue", timeout=20))


class TestBadge(PtyTestCase):
    """The corner badge, judged the way a user judges it: by what is on screen.

    Every assertion here goes through a terminal emulator rather than the byte
    stream, because the whole risk of painting into someone else's TUI is about
    *where* the bytes land — a badge that greps fine but scrolls the screen or
    strands the cursor is a regression, not a feature.
    """

    ROWS, COLS = 40, 120

    def screen(self, session, rows=None, cols=None):
        s = Screen(rows or self.ROWS, cols or self.COLS)
        s.feed(session.buf)
        return s

    def running(self, **env):
        e = {"CR_BADGE": "1"}
        e.update(env)
        s = self.session(env=e, rows=self.ROWS, cols=self.COLS)
        self.assertTrue(s.read_until("winsize"))
        s.drain(1.0)                      # let the badge settle after the frame
        return s

    def test_it_is_painted_in_the_bottom_right_corner(self):
        sc = self.screen(self.running())
        self.assertEqual(sc.line(self.ROWS).strip(), "◆ cr")
        self.assertTrue(sc.line(self.ROWS).startswith(" " * 115))   # right-aligned
        self.assertEqual(sc.cells[self.ROWS - 1][self.COLS - 1], " ")   # spare column

    def test_it_never_scrolls_the_screen(self):
        # The bottom-right cell is the one place a printed character makes the
        # whole screen jump. If that ever happens, claude's output walks upward
        # a line at a time for the rest of the session.
        s = self.running()
        for _ in range(3):
            s.send("tick\r")
            s.drain(0.5)
        sc = self.screen(s)
        self.assertEqual(sc.scrolled, 0)
        self.assertTrue(sc.line(1).startswith("fake-claude ready"))

    def test_it_does_not_move_the_cursor_claude_is_using(self):
        # Claude keeps drawing where it left off; the badge saves and restores.
        s = self.running()
        s.send("hello\r")
        self.assertTrue(s.read_until("GOT:hello"))
        s.drain(0.5)
        sc = self.screen(s)
        # The reply lands at the start of its own line, where claude's cursor was
        # — not in the corner the badge jumped to.
        rows = [n for n in range(1, self.ROWS + 1) if sc.line(n) == "GOT:hello"]
        self.assertEqual(len(rows), 1, sc.text())
        self.assertLess(rows[0], self.ROWS)
        self.assertEqual(sc.line(self.ROWS).strip(), "◆ cr")

    def test_it_does_not_colour_what_claude_draws_next(self):
        s = self.running()
        s.send("plain\r")
        self.assertTrue(s.read_until("GOT:plain"))
        s.drain(0.5)
        sc = self.screen(s)
        self.assertEqual(sc.attr_at(3, 1), "")        # no dim leaking out of DECSC
        self.assertEqual(sc.attr_at(self.ROWS, 116), "2")

    def test_it_is_off_when_asked(self):
        s = self.session(env={"CR_BADGE": "0"}, rows=self.ROWS, cols=self.COLS)
        s.read_until("winsize")
        s.drain(1.0)
        self.assertNotIn("◆", s.buf)

    def test_the_corner_is_configurable(self):
        sc = self.screen(self.running(CR_BADGE_POS="top-left"))
        self.assertTrue(sc.line(1).startswith("◆ cr"))
        self.assertNotIn("◆", sc.line(self.ROWS))

    def test_the_label_is_configurable(self):
        sc = self.screen(self.running(CR_BADGE_LABEL="watching"))
        self.assertEqual(sc.line(self.ROWS).strip(), "◆ watching")

    def test_a_resize_moves_it(self):
        s = self.running()
        s.resize(24, 60)
        s.drain(1.0)
        sc = self.screen(s, rows=24, cols=60)
        self.assertIn("◆ cr", sc.line(24))
        self.assertEqual(sc.cells[23][59], " ")

    def test_it_shows_the_time_left_while_waiting(self):
        # A limit that "resets in 5 hours", compressed 60x, is a five-minute wait
        # — long enough to read the countdown off the screen.
        s = self.running(
            CLAUDE_CONFIG_DIR=tempfile.mkdtemp(prefix="cr-cfg-"),
            CR_SCRAPE="always", CR_WAIT_SCALE="60", CR_MARGIN_SEC="0",
            FAKE_BANNER="You've hit your session limit - resets in 5 hours")
        self.assertTrue(s.read_until("session limit"))
        countdown = re.compile(r"◆ cr ([1-5])m$")
        deadline = time.time() + 10
        while time.time() < deadline:
            s.drain(0.5)
            sc = self.screen(s)
            if countdown.search(sc.line(self.ROWS)):
                break
        sc = self.screen(s)
        self.assertRegex(sc.line(self.ROWS), countdown)
        self.assertEqual(sc.attr_at(self.ROWS, sc.line(self.ROWS).index("◆") + 1), "2;33")

    def test_it_is_taken_off_the_screen_on_exit(self):
        s = self.running()
        s.send("quit\r")
        self.assertEqual(s.wait(), 0)
        self.assertNotIn("◆", self.screen(s).text())


class TestTranscriptChannel(PtyTestCase):
    """The primary channel: nothing is scraped, the JSONL record drives it."""

    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix="cr-cfg-")
        self.work = tempfile.mkdtemp(prefix="cr-work-")
        self.addCleanup(shutil.rmtree, self.cfg, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def test_a_rate_limit_record_triggers_a_retry(self):
        s = self.session(env={
            "CLAUDE_CONFIG_DIR": self.cfg,
            "CR_SCRAPE": "never",            # prove the transcript alone is enough
            "CR_WAIT_SCALE": "3600",
            "CR_MARGIN_SEC": "0",
            "CR_USER_IDLE_SEC": "0",
            "CR_POLL_SEC": "0.2",
            "FAKE_TRANSCRIPT": "You've hit your weekly limit - resets in 2 hours",
        }, cwd=self.work)
        self.assertTrue(s.read_until("GOT:continue", timeout=25))

    def test_an_answered_turn_ends_the_wait(self):
        # The account was switched mid-wait (or the plan upgraded, or the quota
        # came back early): nothing announces it, the session simply starts
        # answering. Left alone, the wrapper would count down its 40 hours over
        # a working session and eventually type into it.
        s = self.session(env={
            "CLAUDE_CONFIG_DIR": self.cfg,
            "CR_SCRAPE": "never",
            "CR_NOTIFY": "1",
            "CR_WAIT_SCALE": "3600",
            "CR_MARGIN_SEC": "0",
            "CR_POLL_SEC": "0.2",
            "FAKE_TRANSCRIPT": "You've hit your weekly limit - resets in 40 hours",
        }, cwd=self.work)
        self.assertTrue(s.read_until("usage limit detected", timeout=15))
        s.send("answer\r")
        self.assertTrue(s.read_until("wait cancelled", timeout=15))
        s.drain(2)
        self.assertNotIn("GOT:continue", s.buf)

    def test_a_live_transcript_turns_the_scraper_off(self):
        # Both channels active: the transcript is being written (so `seen_any`
        # is true), and the screen shows text that WOULD match the scraper. The
        # scraper must stand down rather than double-fire on the render.
        s = self.session(env={
            "CLAUDE_CONFIG_DIR": self.cfg,
            "CR_SCRAPE": "auto",
            "CR_WAIT_SCALE": "3600",
            "CR_MARGIN_SEC": "0",
            "CR_USER_IDLE_SEC": "0",
            "CR_POLL_SEC": "0.2",
            "FAKE_TRANSCRIPT_PLAIN": "ordinary turn",   # a non-limit record: just growth
            "FAKE_BANNER": "You've hit your session limit - resets in 1 hours",
        }, cwd=self.work)
        s.read_until("session limit")
        s.drain(4)
        self.assertNotIn("GOT:continue", s.buf)


if __name__ == "__main__":
    unittest.main(verbosity=2)
