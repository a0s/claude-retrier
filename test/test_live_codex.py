"""live_codex.py's gates — the part of `./test/run.sh --live-codex` that must
be right *before* any money is spent, and the only part of it that can be
tested without spending any.

The scenarios themselves need real codex and real quota, so they are not run
here (that is the point of the separate flag); what is pinned here is that
the run cannot start without an explicit yes, cannot start against a codex
that is missing or logged out, and never treats a pipe as consent.
"""
import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("live_codex", os.path.join(ROOT, "live_codex.py"))
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


class Run(object):
    """A stand-in for subprocess.run: records the argv, returns a code."""
    def __init__(self, code=0, raises=None):
        self.code, self.raises, self.argv = code, raises, None

    def __call__(self, argv, **kw):
        self.argv = argv
        if self.raises:
            raise self.raises
        return type("Done", (), {"returncode": self.code})()


class TestResolveCodex(unittest.TestCase):
    def test_path_lookup_when_nothing_is_overridden(self):
        self.assertEqual(live.resolve_codex({}, which=lambda n: "/usr/bin/" + n),
                         "/usr/bin/codex")

    def test_missing_from_path_is_none_not_a_crash(self):
        self.assertIsNone(live.resolve_codex({}, which=lambda n: None))

    def test_a_file_that_exists_but_is_not_executable_is_not_a_codex(self):
        self.assertIsNone(live.resolve_codex({"CR_LIVE_CODEX_BIN": __file__},
                                             which=lambda n: "/usr/bin/codex"))

    def test_an_unrunnable_override_is_none_rather_than_a_silent_fallback(self):
        # A configuration mistake must not quietly drive some other codex.
        self.assertIsNone(live.resolve_codex({"CR_LIVE_CODEX_BIN": "/nope/codex"},
                                             which=lambda n: "/usr/bin/codex"))

    def test_a_runnable_override_is_used(self):
        self.assertEqual(live.resolve_codex({"CR_LIVE_CODEX_BIN": "/bin/sh"},
                                            which=lambda n: "/usr/bin/codex"),
                         "/bin/sh")


class TestLoginOk(unittest.TestCase):
    def test_zero_exit_means_logged_in(self):
        run = Run(0)
        self.assertTrue(live.login_ok("/bin/codex", run=run))
        self.assertEqual(run.argv, ["/bin/codex", "login", "status"])

    def test_nonzero_exit_means_logged_out(self):
        self.assertFalse(live.login_ok("/bin/codex", run=Run(1)))

    def test_a_binary_that_cannot_run_is_not_logged_in(self):
        self.assertFalse(live.login_ok("/bin/codex", run=Run(raises=OSError("boom"))))


class TestConfirmed(unittest.TestCase):
    def refuse(self):
        raise AssertionError("must not prompt")

    def test_the_env_hatch_starts_the_run_without_a_prompt(self):
        for value in ("1", "y", "YES", "true"):
            self.assertTrue(live.confirmed({"CR_LIVE_CONFIRM": value}, False, self.refuse), value)

    def test_a_pipe_with_no_hatch_is_refused_not_defaulted(self):
        self.assertFalse(live.confirmed({}, False, self.refuse))

    def test_a_tty_is_asked_and_yes_starts_the_run(self):
        self.assertTrue(live.confirmed({}, True, lambda: "y"))
        self.assertTrue(live.confirmed({}, True, lambda: " Yes \n"))

    def test_anything_that_is_not_yes_is_a_no(self):
        for answer in ("", "n", "no", "\n", "sure"):
            self.assertFalse(live.confirmed({}, True, lambda: answer), repr(answer))

    def test_an_empty_hatch_still_asks(self):
        self.assertFalse(live.confirmed({"CR_LIVE_CONFIRM": ""}, True, lambda: "n"))

    def test_the_prompt_says_what_it_will_spend(self):
        text = live.prompt_text("gpt-5.6-luna")
        self.assertIn("REAL codex-cli", text)
        self.assertIn("gpt-5.6-luna", text)
        self.assertIn("CR_LIVE_CONFIRM=1", text)
        self.assertTrue(text.rstrip().endswith("[y/N]"))


class TestRollouts(unittest.TestCase):
    def test_user_texts_reads_input_text_rows_only(self):
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(prefix="cr-live-"), "rollout-x.jsonl")
        with open(path, "w") as fh:
            for row in ({"payload": {"type": "message", "role": "user",
                                     "content": [{"type": "input_text", "text": "$skill go"}]}},
                        {"payload": {"type": "message", "role": "assistant",
                                     "content": [{"type": "output_text", "text": "ok"}]}},
                        {"payload": {"type": "event_msg"}}):
                fh.write(json.dumps(row) + "\n")
            fh.write("not json at all\n")     # a half-written line must not throw
        self.assertEqual(live.user_texts(path), ["$skill go"])

    def test_a_missing_rollout_is_empty_not_an_error(self):
        self.assertEqual(live.user_texts("/nope/rollout-x.jsonl"), [])


class TestCheckAccounting(unittest.TestCase):
    def test_a_failed_check_is_recorded_and_returns_false(self):
        import contextlib
        import io
        before = len(live.RESULTS)
        with contextlib.redirect_stdout(io.StringIO()):   # it prints as it goes
            self.assertFalse(live.check("a thing", False, "why"))
            self.assertTrue(live.check("another thing", True))
        self.assertEqual([r[0] for r in live.RESULTS[before:]], [False, True])


if __name__ == "__main__":
    unittest.main()
