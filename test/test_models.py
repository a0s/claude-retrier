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

from helper import load

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
        self.assertTrue(any("update claude-retrier" in line for line in self.logs))


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
