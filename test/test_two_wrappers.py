"""The T26 test infrastructure itself: two claude-retrier.sh wrappers alive
over one project dir at once — the shape every "wrong session's numbers" bug
(T02, T04, T05) needs to reproduce, and that no single-`Session` pty test
(test_pty.py) can show.
"""
import json
import os
import shutil
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

    def test_a_neighbours_answer_does_not_cancel_our_wait(self):
        # T04: `on_alive("transcript")` used to fire for ANY growing file in the
        # project dir, not just the one this wrapper owns — so b answering
        # cleared a's wait, which was waiting out a's own limit.
        base = {"agent": "claude", "CR_SCRAPE": "never", "CR_WAIT_SCALE": "3600",
                "CR_MARGIN_SEC": "0", "CR_USER_IDLE_SEC": "0", "CR_POLL_SEC": "0.2",
                "CR_NOTIFY": "1"}
        a, b = self.two(dict(base, FAKE_TRANSCRIPT="You've hit your weekly limit - resets in 40 hours"),
                        dict(base))
        self.assertTrue(a.read_until("ready"))
        self.assertTrue(b.read_until("ready"))
        self.assertTrue(a.read_until("usage limit detected", timeout=15))
        b.send("answer\r")
        self.assertTrue(b.read_until("GOT:answer", timeout=15))
        self.assertFalse(a.read_until("wait cancelled", timeout=2))
        self.assertNotIn("session is answering again", "".join(a.log_lines()))

    def test_only_the_session_above_the_threshold_is_folded(self):
        # The bug T02 removes: without registry-based identity, a's watcher
        # could pick up b's growth and read b's numbers as its own (or vice
        # versa), folding the wrong session or both.
        base = {
            "agent": "claude",
            "CR_SCRAPE": "never",
            "CR_CONTEXT_PCT": "51",
            "CR_HANDOFF_FILE": "handoff.md",
            "CR_ROOT_IDLE_SEC": "1",
            "CR_HANDOFF_TIMEOUT_SEC": "45",
            "CR_STEP_GAP_SEC": "0.5",
            "CR_VERIFY_SEC": "8",
            "CR_USER_IDLE_SEC": "0",
            "CR_POLL_SEC": "0.2",
            "CR_SLASH_GAP_SEC": "0.2",
            "CR_SLASH_ENTER_GAP_SEC": "0.2",
            "FAKE_MODEL": "claude-opus-5",
            "FAKE_USAGE_DELAY": "0.3",
        }
        a, b = self.two(dict(base, FAKE_USAGE="700000"), dict(base, FAKE_USAGE="50000"))
        self.assertTrue(a.read_until("ready"))
        self.assertTrue(b.read_until("ready"))
        self.assertTrue(a.read_until("GOT:handoff", timeout=20), a.buf[-500:])
        # b gets every chance it would need to (wrongly) fold too.
        self.assertFalse(b.read_until("GOT:handoff", timeout=3))
        self.assertIn("folding up", "".join(a.log_lines()))
        self.assertNotIn("folding up", "".join(b.log_lines()))

    def test_two_sessions_sharing_a_handoff_file_get_two_different_ones(self):
        # T05: without this, the second wrapper to reach the fold overwrites
        # the first one's handoff.md mid-write, and the fold that reads it
        # back (or the one that never gets written at all) is a coin flip.
        #
        # Started one after the other's "ready" (its registry claim is made
        # before that point, well before the pty is even forked) rather than
        # via `two_wrappers()`'s simultaneous start: the registry has no lock,
        # by design (same "two sessions can race" tradeoff the model cache
        # makes), so two claims within the same instant can both see no
        # conflict — exactly the gap the evidence itself was not testing (its
        # two nonces landed two seconds apart, not the same millisecond).
        d = tempfile.mkdtemp(prefix="cr-two-handoff-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        shared = tempfile.mkdtemp(prefix="cr-two-handoff-cfg-")
        self.addCleanup(shutil.rmtree, shared, ignore_errors=True)
        log = os.path.join(shared, "shared.log")
        base = {
            "CLAUDE_CONFIG_DIR": os.path.join(shared, "claude-config"),
            "CODEX_HOME": os.path.join(shared, "codex-home"),
            "agent": "claude",
            "CR_SCRAPE": "never",
            "CR_CONTEXT_PCT": "51",
            "CR_HANDOFF_FILE": "handoff.md",
            "CR_HANDOFF_REGISTRY_DIR": os.path.join(shared, "handoff-registry"),
            "CR_ROOT_IDLE_SEC": "1",
            "CR_HANDOFF_TIMEOUT_SEC": "45",
            "CR_STEP_GAP_SEC": "0.5",
            "CR_VERIFY_SEC": "8",
            "CR_USER_IDLE_SEC": "0",
            "CR_POLL_SEC": "0.2",
            "CR_SLASH_GAP_SEC": "0.2",
            "CR_SLASH_ENTER_GAP_SEC": "0.2",
            "FAKE_MODEL": "claude-opus-5",
            "FAKE_USAGE": "700000",
            "FAKE_USAGE_DELAY": "0.3",
        }
        a = helper.WrapperSession(cwd=d, log=log, env=dict(base))
        self.addCleanup(a.close)
        self.assertTrue(a.read_until("ready"))

        b = helper.WrapperSession(cwd=d, log=log, env=dict(base))
        self.addCleanup(b.close)
        self.assertTrue(b.read_until("ready"))

        self.assertTrue(a.read_until("GOT:handoff", timeout=20), a.buf[-500:])
        self.assertTrue(b.read_until("GOT:handoff", timeout=20), b.buf[-500:])

        files = sorted(f for f in os.listdir(d) if f.startswith("handoff") and f.endswith(".md"))
        self.assertEqual(len(files), 2, files)
        self.assertIn("handoff.md", files)

        combined = "".join(a.log_lines()) + "".join(b.log_lines())
        self.assertIn("is taken by pid", combined)


if __name__ == "__main__":
    unittest.main()
