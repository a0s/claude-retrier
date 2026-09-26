"""Learning the context window of a model this build has never heard of.

The table shipped in the script goes stale the day a new model ships, which is
exactly the day it is most likely to be pointed at one. Two things keep that from
turning into a session cleared for nothing: a point release resolves to its
family offline, and a slug nothing local can size is looked up rather than
guessed at — the real failure was `claude-fable-5-1` read as unknown, assumed to
be 200k, and folded at 118k when the window was 1M.
"""
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from helper import load
from test_codex import codex_controller, feed
from test_controller import restart_controller, usage

cr = load()

# The rows that matter, verbatim from the published page: one column per model,
# the API id, the alias (which differs only where the id carries a date), and the
# window. The header link in the first cell is markup, not a value.
DOC = """
Some prose above the table.

| Model page | [Claude Fable 5.1](https://x/fable) | [Claude Opus 5](https://x/opus) | [Claude Haiku 4.5](https://x/haiku) |
| --- | --- | --- | --- |
| Claude API ID | `claude-fable-5-1` | `claude-opus-5` | `claude-haiku-4-5-20251001` |
| [Context window](https://x/context-windows) | 1M tokens | 1M tokens | 200K tokens |
| Claude API alias | `claude-fable-5-1` | `claude-opus-5` | `claude-haiku-4-5` |
| Input price | $10.00 | $5.00 | $1.00 |
"""


class TestTheSlugTable(unittest.TestCase):
    def test_a_point_release_falls_back_to_its_family(self):
        self.assertEqual(cr.model_window("claude-fable-5-1"), 1000000)
        self.assertEqual(cr.model_window("claude-opus-5-1"), 1000000)
        self.assertEqual(cr.model_window("claude-haiku-4-5-1"), 200000)

    def test_the_fallback_stops_before_it_starts_inventing(self):
        # claude-opus-4-5 is 200k and claude-opus-4-8 is 1M, so "some opus 4"
        # is not an answer — dropping back to `claude-opus-4` must find nothing.
        self.assertIsNone(cr.model_window("claude-opus-4-9"))
        self.assertIsNone(cr.model_window("claude-nothing-7"))
        self.assertIsNone(cr.model_window("gpt-5"))

    def test_a_slug_is_read_the_way_the_transcript_writes_it(self):
        self.assertEqual(cr.model_slug(" Claude-Opus-5[1m] "), "claude-opus-5")
        self.assertEqual(cr.model_slug("claude-haiku-4-5-20251001"), "claude-haiku-4-5")
        self.assertEqual(cr.model_slug(None), "")


class TestReadingThePublishedTable(unittest.TestCase):
    def test_every_column_pairs_its_id_with_its_window(self):
        self.assertEqual(cr.parse_models_doc(DOC), {
            "claude-fable-5-1": 1000000,
            "claude-opus-5": 1000000,
            "claude-haiku-4-5": 200000,
        })

    def test_a_page_without_the_rows_says_nothing(self):
        self.assertEqual(cr.parse_models_doc("# Models\n\nnothing tabular here"), {})
        self.assertEqual(cr.parse_models_doc(""), {})

    def test_the_models_api_answers_outright(self):
        self.assertEqual(cr.parse_models_api(json.dumps(
            {"id": "claude-opus-5", "max_input_tokens": 1000000})), 1000000)

    def test_an_api_response_that_does_not_say_is_not_invented(self):
        self.assertIsNone(cr.parse_models_api(json.dumps({"id": "claude-opus-5"})))
        self.assertIsNone(cr.parse_models_api('{"max_input_tokens": 0}'))
        self.assertIsNone(cr.parse_models_api("not json at all"))


class LookupTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cr-win-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.calls = []
        self.logs = []
        self.now = 1000.0
        self.cfg = dict(
            model_lookup=True, model_lookup_timeout=1.0,
            model_cache=os.path.join(self.dir, "windows.json"),
            model_cache_ttl=100.0,
            models_doc_url="https://docs.example/models.md",
            models_api_url="https://api.example/v1/models",
        )
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def fetch(self, url, timeout, headers=None):
        self.calls.append((url, headers or {}))
        if url.startswith("https://docs.example"):
            return DOC
        if url.endswith("/claude-fable-5-1"):
            return json.dumps({"max_input_tokens": 999999})
        raise IOError("404")

    def lookup(self, **over):
        cfg = dict(self.cfg, **over)
        return cr.WindowLookup(cfg, self.logs.append, fetch=self.fetch,
                               clock=lambda: self.now)


class TestWhereTheAnswerComesFrom(LookupTestCase):
    def test_the_published_table_answers_without_credentials(self):
        look = self.lookup()
        look._work("claude-fable-5-1")
        self.assertEqual(look.take(),
                         [("claude-fable-5-1", 1000000, "the models docs")])
        self.assertEqual([u for u, _ in self.calls], ["https://docs.example/models.md"])

    def test_the_api_is_preferred_when_there_is_a_key_for_it(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        self.addCleanup(os.environ.pop, "ANTHROPIC_API_KEY", None)
        look = self.lookup()
        look._work("claude-fable-5-1")
        self.assertEqual(look.take(),
                         [("claude-fable-5-1", 999999, "the models API")])
        url, headers = self.calls[0]
        self.assertEqual(url, "https://api.example/v1/models/claude-fable-5-1")
        self.assertEqual(headers["x-api-key"], "sk-test")

    def test_an_api_that_will_not_answer_falls_through_to_the_docs(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        self.addCleanup(os.environ.pop, "ANTHROPIC_API_KEY", None)
        look = self.lookup()
        look._work("claude-opus-5")          # the fake API 404s for this one
        self.assertEqual(look.take(), [("claude-opus-5", 1000000, "the models docs")])

    def test_a_model_nothing_publishes_leaves_the_trigger_disarmed(self):
        look = self.lookup()
        look._work("claude-secret-9")
        self.assertEqual(look.take(), [])
        self.assertTrue(any("stays disarmed" in line for line in self.logs))

    def test_a_network_that_is_not_there_is_not_a_crash(self):
        look = self.lookup(models_doc_url="https://nowhere.example/models.md")
        look._work("claude-fable-5-1")       # the fake fetch raises for this url
        self.assertEqual(look.take(), [])
        self.assertTrue(self.logs)

    def test_the_log_says_the_build_is_the_thing_that_is_out_of_date(self):
        look = self.lookup()
        look._work("claude-fable-5-1")
        self.assertTrue(any("update agent-retrier" in line for line in self.logs))


class TestAskingOnlyOnce(LookupTestCase):
    def test_a_slug_is_asked_about_once_per_session(self):
        look = self.lookup()
        self.assertTrue(look.want("claude-fable-5-1"))
        self.assertFalse(look.want("claude-fable-5-1[1m]"))   # the same model

    def test_the_answer_is_taken_exactly_once(self):
        look = self.lookup()
        look._work("claude-fable-5-1")
        self.assertEqual(len(look.take()), 1)
        self.assertEqual(look.take(), [])

    def test_a_thread_really_does_the_work(self):
        look = self.lookup()
        look.want("claude-fable-5-1")
        for _ in range(200):
            got = look.take()
            if got:
                break
            time.sleep(0.01)
        self.assertEqual(got, [("claude-fable-5-1", 1000000, "the models docs")])

    def test_a_name_that_is_not_a_model_name_is_not_asked_about(self):
        # It goes into a URL, and it came out of a JSON file.
        look = self.lookup()
        for junk in ("claude-x/../../etc", "claude x", "claude-x?y=1", "<synthetic>"):
            self.assertFalse(look.want(junk), junk)
        self.assertEqual(self.calls, [])

    def test_with_the_lookup_off_nothing_leaves_the_machine(self):
        look = self.lookup(model_lookup=False)
        self.assertFalse(look.want("claude-fable-5-1"))
        self.assertEqual(self.calls, [])
        self.assertTrue(any("CR_MODEL_LOOKUP" in line for line in self.logs))


class TestTheCache(LookupTestCase):
    def test_what_was_learned_is_read_back_without_the_network(self):
        self.lookup()._work("claude-fable-5-1")
        self.calls = []
        look = self.lookup()
        self.assertTrue(look.want("claude-fable-5-1"))
        self.assertEqual(look.take(),
                         [("claude-fable-5-1", 1000000, "the models docs, cached")])
        self.assertEqual(self.calls, [])

    def test_the_whole_page_is_kept_not_just_the_model_asked_about(self):
        self.lookup()._work("claude-fable-5-1")
        rows = json.load(open(self.cfg["model_cache"]))
        self.assertEqual(rows["claude-haiku-4-5"]["window"], 200000)

    def test_an_entry_past_its_ttl_is_not_an_entry(self):
        self.lookup()._work("claude-fable-5-1")
        self.calls = []
        self.now += 1000.0
        look = self.lookup()
        look.want("claude-fable-5-1")
        for _ in range(200):
            if look.take():
                break
            time.sleep(0.01)
        self.assertEqual([u for u, _ in self.calls], ["https://docs.example/models.md"])

    def test_a_corrupt_cache_is_simply_not_a_cache(self):
        with open(self.cfg["model_cache"], "w") as fh:
            fh.write("{not json")
        look = self.lookup()
        self.assertIsNone(look._cached("claude-fable-5-1"))
        look._work("claude-fable-5-1")        # and writing over it still works
        self.assertEqual(json.load(open(self.cfg["model_cache"]))
                         ["claude-fable-5-1"]["window"], 1000000)

    def test_an_unwritable_cache_does_not_stop_the_answer(self):
        look = self.lookup(model_cache="/proc/nope/windows.json")
        look._work("claude-fable-5-1")
        self.assertEqual(look.take(),
                         [("claude-fable-5-1", 1000000, "the models docs")])


class TestTheModelProfileTable(unittest.TestCase):
    """MODEL_PROFILES (T18) is the one place stating, per model, what its
    window is, where the agent folds it on its own, and where the wrapper
    should restart. Self-consistency here is what stops a typo in one of
    those three numbers from shipping unnoticed."""

    def test_every_entry_leaves_room_between_restart_and_compaction(self):
        for agent, models in cr.MODEL_PROFILES.items():
            for slug, prof in models.items():
                with self.subTest(agent=agent, slug=slug):
                    self.assertLess(prof.restart_at, prof.compact_at)
                    self.assertLessEqual(prof.compact_at, prof.window)
                    self.assertGreaterEqual(prof.restart_at, 0.3 * prof.window)

    def test_the_two_names_cr_models_is_checked_against_are_in_the_table(self):
        # test_degrade.py checks --cr-models' output for exactly these two.
        self.assertIn("claude-opus-5", cr.MODEL_PROFILES["claude"])
        self.assertIn("gpt-5.6-sol", cr.MODEL_PROFILES["codex"])

    def test_model_window_reads_the_profile_table_now(self):
        # CONTEXT_WINDOWS used to be kept apart from the profiles; now it is
        # derived from them, and model_window's own behavior must not move.
        for slug, prof in cr.MODEL_PROFILES["claude"].items():
            self.assertEqual(cr.model_window(slug), prof.window, slug)

    def test_cr_models_output_has_no_percentage_and_nothing_disarmed(self):
        # 2.0: every row in the table has a profile, so CR_CONTEXT_RESTART=1
        # alone is enough to arm every one of them — none should print
        # "disarmed", and the removed percentage vocabulary should not appear
        # anywhere in the table at all.
        import io
        mod = load(CR_CONTEXT_RESTART="1")
        out = io.StringIO()
        mod.print_models_table(out=out)
        text = out.getvalue()
        self.assertNotIn("disarmed", text)
        self.assertNotIn("PCT", text)


class TestTheWindowEstimate(unittest.TestCase):
    """T19: a slug neither the profile table, the cache, nor a live lookup has
    ever sized still gets a number, not a disarmed trigger — an unfamiliar
    slug is almost always a NEW (large) model, and a session with nothing
    armed at all dies of its own context instead."""

    def test_an_unfamiliar_version_of_a_known_family_gets_its_newest_window(self):
        self.assertEqual(cr.estimate_window("claude", "claude-opus-6"),
                         (1000000, "same family"))

    def test_a_brand_new_family_gets_the_tables_modal_window(self):
        self.assertEqual(cr.estimate_window("claude", "claude-newfamily-1"),
                         (1000000, "modal window"))

    def test_nothing_claude_shaped_falls_back_to_the_small_window(self):
        self.assertEqual(cr.estimate_window("claude", "not-even-claude-shaped"),
                         (200000, "nothing published"))

    def test_a_codex_slug_is_read_from_its_own_cache(self):
        home = tempfile.mkdtemp(prefix="cr-codex-cache-")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        with open(os.path.join(home, "models_cache.json"), "w") as fh:
            json.dump({"gpt-7-nova": {"context_window": 300000,
                                      "effective_context_window_percent": 90}}, fh)
        with mock.patch.dict(os.environ, {"CODEX_HOME": home}):
            self.assertEqual(cr.estimate_window("codex", "gpt-7-nova"),
                             (270000, "the codex model cache"))

    def test_a_codex_slug_absent_from_the_cache_gets_its_modal_window(self):
        home = tempfile.mkdtemp(prefix="cr-codex-cache-")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        with open(os.path.join(home, "models_cache.json"), "w") as fh:
            json.dump({"gpt-a": {"context_window": 300000,
                                  "effective_context_window_percent": 100},
                       "gpt-b": {"context_window": 300000,
                                 "effective_context_window_percent": 100},
                       "gpt-c": {"context_window": 100000,
                                 "effective_context_window_percent": 100}}, fh)
        with mock.patch.dict(os.environ, {"CODEX_HOME": home}):
            self.assertEqual(cr.estimate_window("codex", "gpt-unknown"),
                             (300000, "the codex cache's modal window"))

    def test_with_nothing_published_at_all_it_is_the_provisional_small_window(self):
        with mock.patch.dict(os.environ, {"CODEX_HOME": "/nonexistent-cr-test-home"}):
            self.assertEqual(cr.estimate_window("codex", "gpt-anything"),
                             (200000, "nothing published, no codex model cache either"))


class TestTheThresholdResolutionOrder(unittest.TestCase):
    """`_recompute_limit`'s whole order, one stage at a time — the same order
    documented on `model_restart_at`, which is only the last of the four."""

    def test_stage_1_the_per_model_override_wins_over_everything(self):
        env = "CR_CLAUDE_TOKENS_CLAUDE_OPUS_5"
        os.environ[env] = "300000"
        self.addCleanup(os.environ.pop, env, None)
        ctl = restart_controller(context_restart_on=True)
        usage(ctl, 0, 10, model="claude-opus-5")
        self.assertEqual(ctl.context_limit, 300000)

    def test_stage_2_an_absolute_threshold_wins_over_the_profile(self):
        ctl = restart_controller(context_tokens=400000, context_restart_on=True)
        usage(ctl, 0, 10, model="claude-opus-5")
        self.assertEqual(ctl.context_limit, 400000)

    def test_stage_3_the_bare_flag_arms_the_models_own_profile(self):
        ctl = restart_controller(context_tokens=0, context_restart_on=True)
        usage(ctl, 0, 10, model="claude-opus-5")
        self.assertEqual(ctl.context_limit, 510000)

    def test_stage_4_an_unmatched_model_falls_back_to_the_default_rule(self):
        # A window no profile row describes — either a model this build has
        # never heard of, or one whose window was raised past what its row
        # was written for — falls to DEFAULT_RESTART_PCT of the ACTUAL window
        # instead of staying disarmed.
        ctl = restart_controller(context_tokens=0, context_restart_on=True,
                                 context_window="1M")
        usage(ctl, 0, 10, model="claude-something-new")   # not in MODEL_PROFILES at all
        self.assertEqual(ctl.context_limit, 510000)        # 51% of the forced 1M window

        codex = codex_controller(context_tokens=0, context_restart_on=True)
        feed(codex, 1, model="gpt-5.6-sol", window=872000)  # past that row's own window
        self.assertEqual(codex.context_limit, 872000 - 64000)  # window - the default reserve

    def test_stage_4_uses_the_estimated_window(self):
        # A slug nothing in the table (or the network) has ever heard of still
        # gets a window from T19's estimate machinery, and stage 4 applies
        # DEFAULT_RESTART_PCT to THAT rather than leaving nothing armed.
        ctl = restart_controller(context_tokens=0, context_restart_on=True,
                                 context_window="auto")
        usage(ctl, 0, 10, model="claude-something-9")
        self.assertTrue(ctl.context_estimated)
        self.assertEqual(ctl.context_window, 1000000)      # the table's modal window
        self.assertEqual(ctl.context_limit, 510000)         # 51% of the estimate

    def test_stage_5_no_window_at_all_stays_disarmed(self):
        # codex before its first turn: nothing has stated a window yet, so
        # there is nothing for even the estimate fallback to work from.
        ctl = codex_controller(context_tokens=0, context_restart_on=True)
        self.assertIsNone(ctl.context_limit)

    def test_the_profile_is_reclamped_under_compact_minus_the_live_reserve(self):
        # The profile's own restart_at (194,400) already bakes in the DEFAULT
        # 64k reserve; raising CR_CODEX_RESERVE_TOKENS has to move the real
        # number even though the frozen one in the table does not change.
        os.environ["CR_CODEX_RESERVE_TOKENS"] = "200000"
        self.addCleanup(os.environ.pop, "CR_CODEX_RESERVE_TOKENS", None)
        ctl = codex_controller(context_tokens=0, context_restart_on=True)
        feed(ctl, 1, model="gpt-5.6-sol", window=258400)
        self.assertEqual(ctl.context_limit, 58400)   # 258400 - 200000, not the baked 194400


if __name__ == "__main__":
    unittest.main(verbosity=2)
