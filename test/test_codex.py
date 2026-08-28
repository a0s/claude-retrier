"""codex: the second agent, and the second reason a session stops.

Two things are new here and both come from the same file. codex writes a rollout
JSONL that states outright what Claude Code's transcript only implies — the turn
boundaries, the size of the context window, and the reason a turn ended — so the
first half of this suite is about reading it, and about not reading the rollouts
that belong to other people's sessions.

The second half is the stall: a turn refused by the server rather than by the
account. Nothing about it says when to come back, which is exactly what makes it
a different machine from the limit — the wait is one we pick, and it doubles for
as long as the refusals keep coming.
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from helper import load
from test_pty import PtyTestCase, Session

cr = load()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAPACITY = "Selected model is at capacity. Please try a different model."
OUT_OF_QUOTA = ("You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage "
                "to purchase more credits or try again at Aug 20th, 2026 10:00 AM.")


def rollout(dirname, name="rollout-2026-08-28T10-00-00-abc.jsonl", cwd=None,
            subagent=False, rows=()):
    """Write a rollout file with a session_meta head and `rows` after it."""
    os.makedirs(dirname, exist_ok=True)
    path = os.path.join(dirname, name)
    meta = {"session_id": "abc", "cwd": cwd or os.getcwd(), "originator": "codex-tui",
            "cli_version": "0.150.1",
            "source": {"subagent": {"thread_spawn": {}}} if subagent else "vscode",
            "thread_source": "subagent" if subagent else "user"}
    with open(path, "w") as fh:
        fh.write(json.dumps({"timestamp": "2026-08-28T08:00:00.000Z", "ordinal": 0,
                             "type": "session_meta", "payload": meta}) + "\n")
        for i, (rtype, payload) in enumerate(rows):
            fh.write(json.dumps({"timestamp": "2026-08-28T08:00:0%d.000Z" % (i + 1),
                                 "ordinal": i + 1, "type": rtype,
                                 "payload": payload}) + "\n")
    return path


def task_complete(error=None, last="pong"):
    p = {"type": "task_complete", "turn_id": "t1", "last_agent_message": last,
         "started_at": 1, "completed_at": 2, "duration_ms": 1000}
    if error:
        p["error"] = error
    return ("event_msg", p)


def token_count(tokens, window=258400):
    usage = {"input_tokens": tokens, "cached_input_tokens": 0,
             "cache_write_input_tokens": 0, "output_tokens": 0,
             "reasoning_output_tokens": 0, "total_tokens": tokens}
    return ("event_msg", {"type": "token_count",
                          "info": {"total_token_usage": usage, "last_token_usage": usage,
                                   "model_context_window": window},
                          "rate_limits": {"limit_id": "codex"}})


def message(role, text):
    key = "input_text" if role == "user" else "output_text"
    return ("response_item", {"type": "message", "id": "msg_1", "role": role,
                              "content": [{"type": key, "text": text}]})


class TestReadingARollout(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cr-codex-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def read(self, rows, echo=None):
        path = rollout(self.dir, rows=rows)
        return cr.codex_records(path, 0, echo)[1]

    def test_a_refused_turn_is_a_stall(self):
        got = self.read([task_complete(
            error={"message": CAPACITY, "codex_error_info": "server_overloaded"}, last=None)])
        self.assertEqual([r["kind"] for r in got], ["stall"])
        self.assertEqual(got[0]["text"], CAPACITY)

    def test_a_turn_the_account_ran_out_on_is_a_limit(self):
        got = self.read([task_complete(
            error={"message": OUT_OF_QUOTA, "codex_error_info": "usage_limit_exceeded"},
            last=None)])
        self.assertEqual([r["kind"] for r in got], ["limit"])
        # And the wording carries a time, which is the whole point of preferring
        # the message over anything we could guess. Read from the day before the
        # one it names, since a reset that has already passed is no wait at all.
        before = datetime.datetime(2026, 8, 19, 12, 0).astimezone()
        self.assertAlmostEqual(cr.parse_reset(got[0]["text"], before), 22 * 3600, delta=60)

    def test_an_error_with_no_kind_is_read_from_its_wording(self):
        got = self.read([task_complete(error={"message": OUT_OF_QUOTA}, last=None)])
        self.assertEqual([r["kind"] for r in got], ["limit"])

    def test_an_unrecognised_error_is_a_stall_rather_than_a_limit(self):
        # Guessing "limit" would park the session for five hours over a hiccup.
        got = self.read([task_complete(
            error={"message": "the connection went away", "codex_error_info": "io"},
            last=None)])
        self.assertEqual([r["kind"] for r in got], ["stall"])

    def test_a_turn_that_finished_says_so(self):
        got = self.read([task_complete()])
        self.assertEqual(got[0]["kind"], "alive")
        self.assertTrue(got[0]["clean"])

    def test_token_count_carries_the_context_and_the_window(self):
        got = self.read([token_count(120000, window=258400)])
        self.assertEqual(got[0]["tokens"], 120000)
        self.assertEqual(got[0]["window"], 258400)

    def test_the_prompt_we_typed_comes_back_as_an_echo(self):
        got = self.read([message("user", "continue")], echo="continue")
        self.assertEqual([r["kind"] for r in got], ["echo"])
        self.assertEqual(got[0]["text"], "continue")

    def test_a_prompt_we_did_not_type_is_not_an_echo(self):
        self.assertEqual(self.read([message("user", "do the thing")], echo="continue"), [])

    def test_an_answer_says_the_session_is_alive(self):
        got = self.read([message("assistant", "pong")])
        self.assertEqual([r["kind"] for r in got], ["alive"])
        self.assertFalse(got[0].get("clean"))

    def test_the_model_is_named_but_proves_nothing(self):
        got = self.read([("event_msg", {"type": "thread_settings_applied",
                                        "thread_settings": {"model": "gpt-5.6-sol"}})])
        self.assertEqual(got[0]["model"], "gpt-5.6-sol")
        # `quiet`: a row that names the model is not the session answering, and a
        # wait that ended on one would end on the user opening /model.
        self.assertTrue(got[0]["quiet"])

    def test_rows_are_not_collapsed(self):
        # Each row is a different statement about the turn. Merging them the way
        # claude's assistant rows are merged would let the one without figures
        # blank out the one that had them.
        got = self.read([token_count(9000), message("assistant", "pong"), task_complete()])
        self.assertEqual([r["kind"] for r in got], ["alive", "alive", "alive"])
        self.assertEqual(got[0]["tokens"], 9000)

    def test_reading_resumes_where_it_stopped(self):
        path = rollout(self.dir, rows=[task_complete()])
        offset, first = cr.codex_records(path, 0)
        self.assertEqual(len(first), 1)
        _, again = cr.codex_records(path, offset)
        self.assertEqual(again, [])

    def test_a_half_written_row_is_left_for_the_next_poll(self):
        path = rollout(self.dir, rows=[])
        with open(path, "a") as fh:
            fh.write('{"type":"event_msg","payload":{"type":"task_comp')
        offset, got = cr.codex_records(path, 0)
        self.assertEqual(got, [])
        with open(path, "a") as fh:
            fh.write('lete","turn_id":"t"}}\n')
        _, got = cr.codex_records(path, offset)
        self.assertEqual([r["kind"] for r in got], ["alive"])


class TestWhichRolloutsAreOurs(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="cr-codex-home-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        t = time.localtime()
        self.today = os.path.join(self.home, "sessions", "%04d" % t.tm_year,
                                  "%02d" % t.tm_mon, "%02d" % t.tm_mday)

    def agent(self, cwd=None):
        return cr.CodexAgent(home=self.home, cwd=cwd or os.getcwd())

    def test_todays_rollouts_are_found(self):
        path = rollout(self.today, rows=[])
        self.assertIn(path, self.agent().paths())

    def test_a_rollout_from_another_day_is_not_scanned(self):
        old = os.path.join(self.home, "sessions", "2001", "01", "01")
        path = rollout(old, rows=[])
        self.assertNotIn(path, self.agent().paths())

    def test_our_own_rollout_is_kept(self):
        path = rollout(self.today, rows=[])
        self.assertTrue(self.agent().keep(path))

    def test_a_subagents_rollout_is_not_ours(self):
        # It is a different session with a context of its own, and a limit on it
        # is not this terminal's news.
        path = rollout(self.today, name="rollout-sub.jsonl", subagent=True, rows=[])
        self.assertFalse(self.agent().keep(path))

    def test_a_rollout_from_another_directory_is_not_ours(self):
        path = rollout(self.today, name="rollout-elsewhere.jsonl", cwd="/somewhere/else",
                       rows=[])
        self.assertFalse(self.agent().keep(path))

    def test_a_file_with_no_head_yet_is_read_anyway(self):
        # Better to read a stranger's rollout for one poll than to write our own
        # session off for the rest of its life.
        os.makedirs(self.today, exist_ok=True)
        path = os.path.join(self.today, "rollout-empty.jsonl")
        open(path, "w").close()
        a = self.agent()
        self.assertTrue(a.keep(path))
        # ...and the verdict is not cached, so the real answer still lands.
        with open(path, "w") as fh:
            fh.write(json.dumps({"type": "session_meta",
                                 "payload": {"thread_source": "subagent"}}) + "\n")
        self.assertFalse(a.keep(path))


class TestPickingTheAgent(unittest.TestCase):
    def test_a_codex_binary_is_recognised(self):
        self.assertEqual(cr.pick_agent("auto", ["/Users/x/.local/bin/codex"]), "codex")

    def test_a_codex_command_line_behind_a_shell_is_recognised(self):
        self.assertEqual(
            cr.pick_agent("auto", ["/bin/zsh", "-c", 'codex --model x "$@"', "codex"]),
            "codex")

    def test_claude_is_the_default(self):
        self.assertEqual(cr.pick_agent("auto", ["/usr/local/bin/claude"]), "claude")

    def test_a_name_that_merely_contains_codex_is_not_one(self):
        self.assertEqual(cr.pick_agent("auto", ["/usr/local/bin/my-codex-helper"]),
                         "claude")

    def test_a_prompt_that_says_codex_does_not_pick_codex(self):
        # `claude-retrier "fix the codex build"` starts claude. Reading the
        # sentence would send the watcher after a file nobody is writing.
        self.assertEqual(cr.pick_agent("auto", ["/usr/local/bin/claude"]), "claude")

    def test_an_explicit_choice_wins(self):
        self.assertEqual(cr.pick_agent("codex", ["/usr/local/bin/claude"]), "codex")
        self.assertEqual(cr.pick_agent("claude", ["/usr/local/bin/codex"]), "claude")

    def test_the_directory_codex_was_pointed_at_is_the_one_we_follow(self):
        self.assertEqual(cr.codex_cwd(["--cd", "/tmp/x"]), "/tmp/x")
        self.assertEqual(cr.codex_cwd(["--cd=/tmp/y"]), "/tmp/y")
        self.assertIsNone(cr.codex_cwd(["--model", "gpt"]))


CFG = dict(message="continue", margin=0, max_attempts=3, fallback_wait=18000,
           max_wait=691200, user_idle=20, busy_idle=6, verify=60, wait_scale=1,
           draft_grace=600, resume=15, typing_max=900,
           stall_wait=60, stall_backoff=2, stall_max_wait=600, stall_max_attempts=8)


def controller(**over):
    cfg = dict(CFG)
    cfg.update(over)
    logs = []
    ctl = cr.Controller(cfg, logs.append, now=0)
    ctl.log_lines = logs
    return ctl


class TestStalling(unittest.TestCase):
    def test_a_stall_schedules_a_nudge(self):
        ctl = controller()
        self.assertTrue(ctl.on_stall(CAPACITY, now=1000, source="transcript"))
        self.assertEqual(ctl.state, cr.WAITING)
        self.assertAlmostEqual(ctl.wake_at, 1060, delta=1)

    def test_no_margin_is_added(self):
        # The margin exists to clear a stated reset time by a little. A stall
        # states nothing, so there is nothing to clear.
        ctl = controller(margin=45)
        ctl.on_stall(CAPACITY, now=0, source="transcript")
        self.assertAlmostEqual(ctl.wake_at, 60, delta=1)

    def test_the_wait_doubles_while_the_refusals_keep_coming(self):
        ctl = controller()
        waits = []
        for i in range(4):
            now = i * 1000
            ctl.state = cr.IDLE
            ctl.on_stall(CAPACITY, now=now, source="transcript")
            waits.append(round(ctl.wake_at - now))
        self.assertEqual(waits, [60, 120, 240, 480])

    def test_the_wait_is_capped(self):
        ctl = controller(stall_max_wait=100)
        for i in range(4):
            ctl.state = cr.IDLE
            ctl.on_stall(CAPACITY, now=i * 1000, source="transcript")
        self.assertAlmostEqual(ctl.wake_at - 3000, 100, delta=1)

    def test_a_turn_that_finishes_ends_the_streak(self):
        ctl = controller()
        ctl.on_stall(CAPACITY, now=0, source="transcript")
        ctl.state = cr.IDLE
        ctl.on_turn_done(now=100)
        ctl.on_stall(CAPACITY, now=200, source="transcript")
        self.assertAlmostEqual(ctl.wake_at, 260, delta=1)

    def test_the_same_line_again_is_the_same_stall(self):
        # A TUI repaints the line for as long as it is on screen, and the
        # transcript reports it besides.
        ctl = controller()
        self.assertTrue(ctl.on_stall(CAPACITY, now=0, source="screen"))
        ctl.state = cr.IDLE
        self.assertFalse(ctl.on_stall(CAPACITY, now=5, source="screen"))

    def test_a_stall_during_a_wait_is_ignored(self):
        ctl = controller()
        ctl.on_limit("You've hit your weekly limit · resets in 2 hours", now=0,
                     source="transcript")
        self.assertFalse(ctl.on_stall(CAPACITY, now=10, source="transcript"))
        self.assertAlmostEqual(ctl.wake_at, 7200, delta=1)

    def test_a_limit_during_a_stall_wait_takes_over(self):
        # The account running out outranks the server being busy: it is the
        # longer wait and the one with a time attached.
        ctl = controller()
        ctl.on_stall(CAPACITY, now=0, source="transcript")
        self.assertTrue(ctl.on_limit("You've hit your weekly limit · resets in 2 hours",
                                     now=10, source="transcript"))
        self.assertAlmostEqual(ctl.wake_at, 7210, delta=1)

    def test_it_gives_up_after_enough_of_them(self):
        ctl = controller(stall_max_attempts=2)
        for i in range(2):
            ctl.state = cr.IDLE
            self.assertTrue(ctl.on_stall(CAPACITY, now=i * 1000, source="transcript"))
        ctl.state = cr.IDLE
        self.assertFalse(ctl.on_stall(CAPACITY, now=9000, source="transcript"))
        self.assertTrue(any("leaving it alone" in l for l in ctl.log_lines))

    def test_zero_switches_it_off(self):
        ctl = controller(stall_wait=0)
        self.assertFalse(ctl.on_stall(CAPACITY, now=0, source="transcript"))
        self.assertEqual(ctl.state, cr.IDLE)

    def test_the_nudge_goes_out_when_the_wait_ends(self):
        ctl = controller(user_idle=0)
        ctl.on_stall(CAPACITY, now=0, source="transcript")
        self.assertIsNone(ctl.tick(30))
        self.assertEqual(ctl.tick(61), ("inject", "continue", False))

    def test_the_notice_says_which_of_the_two_it_is(self):
        ctl = controller(user_idle=0)
        ctl.on_stall(CAPACITY, now=0, source="transcript")
        ctl.tick(61)
        self.assertEqual(ctl.inject_note(), "asking the session to carry on")
        ctl = controller(user_idle=0)
        ctl.on_limit("resets in 1 hours", now=0, source="transcript")
        ctl.tick(3601)
        self.assertEqual(ctl.inject_note(), "limit lifted; resuming session")

    def test_a_working_session_holds_the_nudge_back(self):
        ctl = controller(user_idle=0)
        ctl.on_stall(CAPACITY, now=0, source="transcript")
        ctl.on_output("✳ Cogitating… (esc to interrupt)", now=60)
        self.assertIsNone(ctl.tick(61))


class TestFindingAStallOnScreen(unittest.TestCase):
    def test_the_capacity_line_is_found(self):
        self.assertEqual(cr.find_stall("⚠ " + CAPACITY), "⚠ " + CAPACITY)

    def test_ordinary_output_is_not_a_stall(self):
        self.assertIsNone(cr.find_stall("• Ran 3 commands · ctrl + t to view transcript"))

    def test_a_tool_call_quoting_the_words_is_not_one(self):
        screen = "● Bash(grep -r 'model is at capacity' .)\n  ⎿  selected model is at capacity"
        self.assertIsNone(cr.find_stall(screen))

    def test_our_own_documentation_is_not_one(self):
        self.assertIsNone(cr.find_stall("  CR_STALL_PATTERNS  selected model is at capacity"))


def _fake_codex_launcher():
    """A single-exec launcher, named codex so the auto-detection has something
    to work from — which is the same thing it has in a real install."""
    path = os.path.join(tempfile.mkdtemp(prefix="cr-fake-codex-"), "codex")
    with open(path, "w") as fh:
        fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n'
                 % (sys.executable, os.path.join(ROOT, "test", "fake_codex.py")))
    os.chmod(path, 0o755)
    return path


FAKE_CODEX = _fake_codex_launcher()


class TestCodexSubcommands(unittest.TestCase):
    """Most of what `codex` can be asked to do is not a session at all, and a pty
    supervisor around one of those is a pty for nothing."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cr-codex-sub-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.log = os.path.join(self.dir, "log")

    def run_wrapper(self, args):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("CR_")
               and k not in ("CLAUDE_RETRIER_ACTIVE", "CLAUDE_CONFIG_DIR")}
        env.update({"CR_CLAUDE_BIN": FAKE_CODEX, "CR_LOG": self.log,
                    "CODEX_HOME": self.dir, "CR_NOTIFY": "0"})
        return subprocess.run([os.path.join(ROOT, "claude-retrier.sh"), *args],
                              env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=30)

    def supervised(self):
        """Did the pty supervisor run? It is the only thing that logs."""
        if not os.path.exists(self.log):
            return False
        with open(self.log) as fh:
            return "start:" in fh.read()

    def test_exec_runs_codex_directly(self):
        r = self.run_wrapper(["exec", "do the thing"])
        self.assertIn("fake-codex ready", r.stdout)
        self.assertFalse(self.supervised())

    def test_login_runs_codex_directly(self):
        self.run_wrapper(["login"])
        self.assertFalse(self.supervised())

    def test_a_flag_before_the_subcommand_is_stepped_over(self):
        self.run_wrapper(["--cd", self.dir, "exec"])
        self.assertFalse(self.supervised())

    def wrapped(self, args, timeout=15):
        """Start the wrapper and wait for the supervisor to announce itself.

        A wrapped session does not end on its own — it is sitting at a prompt on
        a pty, which is the whole point — so this asks the question and then
        stops it.
        """
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("CR_")
               and k not in ("CLAUDE_RETRIER_ACTIVE", "CLAUDE_CONFIG_DIR")}
        env.update({"CR_CLAUDE_BIN": FAKE_CODEX, "CR_LOG": self.log,
                    "CODEX_HOME": self.dir, "CR_NOTIFY": "0"})
        proc = subprocess.Popen([os.path.join(ROOT, "claude-retrier.sh"), *args],
                                env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        try:
            deadline = time.time() + timeout
            while time.time() < deadline and not self.supervised():
                time.sleep(0.1)
            return self.supervised()
        finally:
            proc.kill()
            proc.wait(timeout=5)

    def test_resume_is_a_session_and_is_wrapped(self):
        self.assertTrue(self.wrapped(["resume"]))

    def test_a_bare_prompt_is_a_session_and_is_wrapped(self):
        # And a prompt that happens to name a subcommand is still a prompt.
        self.assertTrue(self.wrapped(["exec the plan and report back"]))


class TestCodexEndToEnd(PtyTestCase):
    """The whole thing on a pty: a rollout file the wrapper follows, a turn that
    dies in it, and `continue` typed into the session that was left sitting."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="cr-codex-home-")
        self.work = tempfile.mkdtemp(prefix="cr-codex-work-")
        self.log = os.path.join(self.home, "log")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def env(self, **over):
        e = {"CR_CLAUDE_BIN": FAKE_CODEX,
             "CODEX_HOME": self.home,
             "CR_LOG": self.log,
             "CR_SCRAPE": "never",           # prove the rollout alone is enough
             "CR_WAIT_SCALE": "60",          # a minute of waiting becomes a second
             "CR_USER_IDLE_SEC": "0",
             "CR_POLL_SEC": "0.2"}
        e.update(over)
        return e

    def logged(self):
        try:
            with open(self.log) as fh:
                return fh.read()
        except OSError:
            return ""

    def wait_for_log(self, needle, session, timeout=20):
        """The log is the durable record; with the notice line off it is also the
        only place a detection shows up."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if needle in self.logged():
                return True
            session.drain(0.3)
        return False

    def test_a_capacity_error_is_answered_with_the_message(self):
        s = self.session(env=self.env(FAKE_STALL=CAPACITY), cwd=self.work)
        self.assertTrue(s.read_until("GOT:continue", timeout=25))

    def test_the_agent_is_worked_out_from_the_command(self):
        s = self.session(env=self.env(FAKE_STALL=CAPACITY), cwd=self.work)
        s.read_until("GOT:continue", timeout=25)
        self.assertIn("agent: codex", self.logged())

    def test_a_usage_limit_in_the_rollout_is_waited_out(self):
        s = self.session(
            env=self.env(FAKE_TRANSCRIPT="You've hit your usage limit. Try again at "
                                         "10:00 AM.",
                         CR_MARGIN_SEC="0"),
            cwd=self.work)
        self.assertTrue(self.wait_for_log("limit detected (transcript)", s))
        self.assertIn("resets in", self.logged())

    def test_a_subagents_rollout_is_left_alone(self):
        # Same error, written by a rollout that belongs to a subagent. Acting on
        # it would type into a session that never stopped.
        s = self.session(env=self.env(FAKE_STALL=CAPACITY, FAKE_SUBAGENT="1"),
                         cwd=self.work)
        s.read_until("ready", timeout=10)
        s.drain(4)
        self.assertNotIn("GOT:continue", s.buf)

    def test_an_ordinary_session_is_left_alone(self):
        s = self.session(env=self.env(), cwd=self.work)
        s.read_until("ready", timeout=10)
        s.send("hello there\r")
        self.assertTrue(s.read_until("GOT:hello there", timeout=10))
        s.drain(3)
        self.assertNotIn("GOT:continue", s.buf)

    def test_the_context_window_comes_from_the_rollout(self):
        s = self.session(
            env=self.env(CR_CONTEXT_PCT="50", FAKE_USAGE="1000", FAKE_WINDOW="400000"),
            cwd=self.work)
        s.read_until("ready", timeout=10)
        s.drain(4)
        self.assertIn("400k context window (the transcript)", self.logged())


if __name__ == "__main__":
    unittest.main(verbosity=2)
