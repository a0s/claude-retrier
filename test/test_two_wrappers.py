"""The T26 test infrastructure itself: two claude-retrier.sh wrappers alive
over one project dir at once — the shape every "wrong session's numbers" bug
(T02, T04, T05) needs to reproduce, and that no single-`Session` pty test
(test_pty.py) can show.
"""
import json
import os
import tempfile
import time
import unittest

import helper


def _read_sessions(sessions_dir):
    entries = {}
    for name in os.listdir(sessions_dir):
        with open(os.path.join(sessions_dir, name)) as fh:
            entries[int(name[:-5])] = json.load(fh)
    return entries


class TwoWrappersTestCase(unittest.TestCase):
    def two(self, cfg_a=None, cfg_b=None):
        d = tempfile.mkdtemp(prefix="cr-two-test-")
        a, b = helper.two_wrappers(d, cfg_a or {"agent": "claude"}, cfg_b or {"agent": "claude"})
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        return a, b


class TestTwoWrappers(TwoWrappersTestCase):
    def test_logs_stay_untangled_by_pid(self):
        a, b = self.two()
        self.assertTrue(a.read_until("ready"))
        self.assertTrue(b.read_until("ready"))
        a.send("quit\r")
        b.send("quit\r")
        a.wait()
        b.wait()
        a_lines, b_lines = a.log_lines(), b.log_lines()
        self.assertTrue(a_lines)
        self.assertTrue(b_lines)
        other_tag = "[cr %d " % b.pid
        self.assertFalse(any(other_tag in line for line in a_lines))
        own_tag = "[cr %d " % a.pid
        self.assertFalse(any(own_tag in line for line in b_lines))

    def test_each_wrapper_gets_its_own_session_registry_entry(self):
        a, b = self.two()
        self.assertTrue(a.read_until("ready"))
        self.assertTrue(b.read_until("ready"))
        time.sleep(0.3)  # both fakes have written sessions/<pid>.json by now
        a_pid, b_pid = a.agent_pid(), b.agent_pid()
        self.assertIsNotNone(a_pid)
        self.assertIsNotNone(b_pid)
        self.assertNotEqual(a_pid, b_pid)
        sessions_dir = os.path.join(os.path.dirname(a.log), "claude-config", "sessions")
        entries = _read_sessions(sessions_dir)
        self.assertIn(a_pid, entries)
        self.assertIn(b_pid, entries)
        self.assertNotEqual(entries[a_pid]["sessionId"], "")
        self.assertNotEqual(entries[a_pid]["sessionId"], entries[b_pid]["sessionId"])
        a.send("quit\r")
        b.send("quit\r")
        a.wait()
        b.wait()
        # gone on exit: a stale entry would tell a later wrapper a dead pid is live
        self.assertEqual(os.listdir(sessions_dir), [])

    def test_ten_runs_do_not_flap_and_finish_quickly(self):
        start = time.time()
        for _ in range(10):
            d = tempfile.mkdtemp(prefix="cr-two-flap-")
            a, b = helper.two_wrappers(d, {"agent": "claude"}, {"agent": "claude"})
            try:
                self.assertTrue(a.read_until("ready", timeout=10))
                self.assertTrue(b.read_until("ready", timeout=10))
                a.send("quit\r")
                b.send("quit\r")
                self.assertEqual(a.wait(timeout=10), 0)
                self.assertEqual(b.wait(timeout=10), 0)
            finally:
                a.close()
                b.close()
        self.assertLess(time.time() - start, 60)

    def test_close_kills_the_whole_process_group(self):
        # FAKE_WORKING never exits on its own — proof close() does not depend
        # on the fake cooperating (the live-codex-test-orphans case: a killed
        # pty driver leaving its supervisor behind).
        a, b = self.two({"agent": "claude", "FAKE_WORKING": "1"}, {"agent": "claude"})
        self.assertTrue(a.read_until("ready"))
        self.assertTrue(b.read_until("ready"))
        wrapper_pid, agent_pid = a.pid, a.agent_pid()
        self.assertIsNotNone(agent_pid)
        a.close()
        time.sleep(0.2)
        with self.assertRaises(ProcessLookupError):
            os.kill(wrapper_pid, 0)
        with self.assertRaises(ProcessLookupError):
            os.kill(agent_pid, 0)   # setsid()'d out of our process group — the
                                    # orphan `close()` has to hunt down explicitly

    def test_a_session_growing_never_leaks_into_the_others_context(self):
        # The concrete bug class: one session's transcript keeps growing while
        # the other sits idle. Their sessions/<pid>.json entries — what T02's
        # identity binding reads — must stay distinguishable throughout.
        a, b = self.two({"agent": "claude", "FAKE_SCRIPT": "grow=50000:0.2"},
                        {"agent": "claude"})
        self.assertTrue(a.read_until("ready"))
        self.assertTrue(b.read_until("ready"))
        time.sleep(0.6)
        a_pid, b_pid = a.agent_pid(), b.agent_pid()
        sessions_dir = os.path.join(os.path.dirname(a.log), "claude-config", "sessions")
        entries = _read_sessions(sessions_dir)
        self.assertEqual(entries[a_pid]["cwd"], entries[b_pid]["cwd"])
        self.assertNotEqual(entries[a_pid]["sessionId"], entries[b_pid]["sessionId"])


if __name__ == "__main__":
    unittest.main()
