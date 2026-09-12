"""The structured channel: Claude Code's own JSONL transcript.

A limited turn is written as a record carrying `"error": "rate_limit"` and
`"apiErrorStatus": 429`. Keying on that field instead of on the rendered text
removes the entire "text about an error vs. a live error" ambiguity that the
screen-scraping design can only ever approximate.
"""
import json
import os
import shutil
import tempfile
import unittest

from helper import load

cr = load()


def record(text, error="rate_limit", status=429, api_error=True):
    return {
        "type": "assistant",
        "timestamp": "2026-07-19T19:22:08.730Z",
        "message": {"role": "assistant", "model": "<synthetic>",
                    "content": [{"type": "text", "text": text}]},
        "error": error,
        "isApiErrorMessage": api_error,
        "apiErrorStatus": status,
        "sessionId": "s1",
    }


ORDINARY = {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}}


def user_row(text):
    return {"type": "user", "timestamp": "2026-08-01T18:20:45.715Z",
            "message": {"role": "user", "content": text}, "sessionId": "s1"}


USER_ECHO = user_row("continue")

# Verbatim shape of a real limited turn, minus the fields we don't read.
REAL = record("You've hit your weekly limit · resets Jul 22 at 6am (Europe/Warsaw)")


class TestProjectDir(unittest.TestCase):
    def test_cwd_is_slugged_the_way_claude_code_does_it(self):
        got = cr.project_dir("/Users/a0s/a0s_github/node_editor", "/cfg")
        self.assertEqual(got, "/cfg/projects/-Users-a0s-a0s-github-node-editor")

    def test_dots_and_underscores_both_become_dashes(self):
        got = cr.project_dir("/Users/a0s/p/.claude/worktrees/x_y", "/cfg")
        self.assertEqual(got, "/cfg/projects/-Users-a0s-p--claude-worktrees-x-y")


class TestRecordParsing(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cr-tr-")
        self.path = os.path.join(self.dir, "session.jsonl")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def write(self, *records):
        with open(self.path, "a") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")

    def limits(self, found):
        return [r for r in found if r["kind"] == "limit"]

    def test_finds_the_limit_record(self):
        self.write(ORDINARY, REAL, ORDINARY)
        offset, found = cr.transcript_limit_records(self.path, 0)
        limits = self.limits(found)
        self.assertEqual(len(limits), 1)
        self.assertIn("resets Jul 22 at 6am", limits[0]["text"])
        self.assertEqual(offset, os.path.getsize(self.path))

    def test_offset_makes_reads_incremental(self):
        self.write(ORDINARY)
        offset, found = cr.transcript_limit_records(self.path, 0)
        self.assertEqual(self.limits(found), [])
        self.write(REAL)
        offset, found = cr.transcript_limit_records(self.path, offset)
        self.assertEqual(len(self.limits(found)), 1)
        # Reading again from the new offset must not re-report it.
        _, again = cr.transcript_limit_records(self.path, offset)
        self.assertEqual(again, [])

    def test_a_half_written_line_is_not_parsed_yet(self):
        # The transcript is appended to while we read it, so the last line can be
        # incomplete. Consuming it would drop the record permanently.
        with open(self.path, "w") as fh:
            fh.write(json.dumps(ORDINARY) + "\n")
            fh.write(json.dumps(REAL)[:60])
        offset, found = cr.transcript_limit_records(self.path, 0)
        self.assertEqual(self.limits(found), [])
        with open(self.path, "a") as fh:
            fh.write(json.dumps(REAL)[60:] + "\n")
        _, found = cr.transcript_limit_records(self.path, offset)
        self.assertEqual(len(self.limits(found)), 1)

    def test_non_limit_api_errors_are_ignored(self):
        self.write(record("API Error: 529 overloaded", error="overloaded", status=529))
        _, found = cr.transcript_limit_records(self.path, 0)
        self.assertEqual(found, [])

    def test_the_word_alone_is_not_enough(self):
        # A session that merely discusses rate limits writes ordinary assistant
        # records; only the structured error field makes one a limit.
        self.write({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "rate_limit and isApiErrorMessage are the fields to watch"}]}})
        _, found = cr.transcript_limit_records(self.path, 0)
        self.assertEqual([r["kind"] for r in found], ["alive"])

    def test_malformed_json_does_not_raise(self):
        with open(self.path, "w") as fh:
            fh.write("{not json at all\n")
            fh.write(json.dumps(REAL) + "\n")
        _, found = cr.transcript_limit_records(self.path, 0)
        self.assertEqual(len(self.limits(found)), 1)

    def test_an_answered_turn_is_reported_as_alive(self):
        # The account is serving requests again. It is what says so when a limit
        # ends early — a switched account, an upgraded plan — with no banner and
        # no reset to announce it.
        self.write(ORDINARY)
        _, found = cr.transcript_limit_records(self.path, 0)
        self.assertEqual([r["kind"] for r in found], ["alive"])

    def test_a_run_of_assistant_rows_collapses_into_one(self):
        # One answer is many rows (a thought, three tool calls, a summary). The
        # caller only needs "the session answered".
        self.write(ORDINARY, ORDINARY, ORDINARY)
        _, found = cr.transcript_limit_records(self.path, 0)
        self.assertEqual([r["kind"] for r in found], ["alive"])

    def test_alive_keeps_its_place_relative_to_a_limit(self):
        # Order is the whole meaning: alive-then-limit is a session that just
        # ran out, limit-then-alive is one that came back.
        self.write(ORDINARY, REAL, ORDINARY)
        _, found = cr.transcript_limit_records(self.path, 0)
        self.assertEqual([r["kind"] for r in found], ["alive", "limit", "alive"])

    def test_a_limit_record_is_not_also_alive(self):
        self.write(REAL)
        _, found = cr.transcript_limit_records(self.path, 0)
        self.assertEqual([r["kind"] for r in found], ["limit"])

    def test_a_user_row_quoting_the_type_field_is_not_alive(self):
        # Tool output lands in a user row verbatim; this file's own source has
        # been pasted into one more than once.
        self.write(user_row('grep found: "type":"assistant" in the parser'))
        _, found = cr.transcript_limit_records(self.path, 0)
        self.assertEqual(found, [])

    def test_missing_file(self):
        offset, found = cr.transcript_limit_records(os.path.join(self.dir, "nope.jsonl"), 0)
        self.assertEqual((offset, found), (0, []))


class TestWatcher(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cr-w-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.dir, name)

    def append(self, name, rec):
        with open(self.path(name), "a") as fh:
            fh.write(json.dumps(rec) + "\n")

    def test_preexisting_content_is_not_replayed(self):
        # `claude --continue` reopens a transcript that already contains
        # yesterday's banner. Replaying it would park a fresh session for hours.
        self.append("old.jsonl", REAL)
        w = cr.TranscriptWatcher(self.dir, poll=0)
        self.assertEqual(w.poll_now(), [])

    def test_new_records_in_an_existing_file_are_seen(self):
        self.append("old.jsonl", ORDINARY)
        w = cr.TranscriptWatcher(self.dir, poll=0)
        self.append("old.jsonl", REAL)
        found = w.poll_now()
        self.assertEqual(len(found), 1)

    def test_a_file_created_after_start_is_read_whole(self):
        w = cr.TranscriptWatcher(self.dir, poll=0)
        self.append("fresh.jsonl", REAL)
        self.assertEqual(len(w.poll_now()), 1)

    def test_growth_is_what_marks_the_transcript_channel_as_live(self):
        # `seen_any` is what turns the screen-scraping fallback off; it must only
        # flip once this project's transcript is actually being written.
        w = cr.TranscriptWatcher(self.dir, poll=0)
        self.assertFalse(w.seen_any)
        self.append("fresh.jsonl", ORDINARY)
        w.poll_now()
        self.assertTrue(w.seen_any)

    def test_poll_interval_is_respected(self):
        w = cr.TranscriptWatcher(self.dir, poll=100)
        w.poll_now(now=0)                                # first poll always runs
        self.append("fresh.jsonl", REAL)
        self.assertEqual(w.poll_now(now=1), [])          # still inside the interval
        self.assertEqual(len(w.poll_now(now=1e9)), 1)

    def test_our_retry_coming_back_is_reported_as_an_echo(self):
        # The proof a retry was submitted rather than left in the input box.
        # Watching the footer for it broke silently when Claude Code reworded it;
        # this row is written by claude itself.
        w = cr.TranscriptWatcher(self.dir, poll=0, echo="continue")
        self.append("s.jsonl", USER_ECHO)
        found = w.poll_now()
        self.assertEqual([r["kind"] for r in found], ["echo"])

    def test_a_different_prompt_is_not_our_echo(self):
        w = cr.TranscriptWatcher(self.dir, poll=0, echo="continue")
        self.append("s.jsonl", user_row("continue the refactor yourself"))
        self.assertEqual(w.poll_now(), [])

    def test_echoes_are_ignored_when_no_message_is_configured(self):
        w = cr.TranscriptWatcher(self.dir, poll=0)
        self.append("s.jsonl", USER_ECHO)
        self.assertEqual(w.poll_now(), [])

    def test_limit_records_are_still_labelled(self):
        w = cr.TranscriptWatcher(self.dir, poll=0, echo="continue")
        self.append("s.jsonl", REAL)
        self.assertEqual([r["kind"] for r in w.poll_now()], ["limit"])

    def test_truncation_is_handled(self):
        self.append("s.jsonl", ORDINARY)
        w = cr.TranscriptWatcher(self.dir, poll=0)
        with open(self.path("s.jsonl"), "w") as fh:      # rewritten from scratch
            fh.write(json.dumps(REAL) + "\n")
        self.assertEqual(len(w.poll_now()), 1)


class TestContextFigures(unittest.TestCase):
    """The context trigger does not count tokens; it reads the count Claude wrote.

    Every assistant row carries the API's own `usage`, and the three input
    counters in it are the prompt that was sent. Anything this layer gets wrong
    is a restart at the wrong moment — or, worse, never.
    """

    def test_the_three_input_counters_are_the_context(self):
        self.assertEqual(cr.usage_tokens(
            {"input_tokens": 2, "cache_creation_input_tokens": 1093,
             "cache_read_input_tokens": 611317, "output_tokens": 6858}), 612412)

    def test_output_tokens_are_not_context(self):
        # Not until the next turn quotes them back, and by then they are inside
        # cache_creation. Adding them here would count them twice.
        self.assertEqual(cr.usage_tokens({"input_tokens": 10, "output_tokens": 9999}), 10)

    def test_a_row_without_usage_says_nothing(self):
        self.assertIsNone(cr.usage_tokens(None))
        self.assertIsNone(cr.usage_tokens({}))
        self.assertIsNone(cr.usage_tokens("not a dict"))

    def test_missing_counters_do_not_zero_the_others(self):
        self.assertEqual(cr.usage_tokens({"cache_read_input_tokens": 500}), 500)


class TestModelWindows(unittest.TestCase):
    def test_the_slug_the_transcript_actually_writes(self):
        self.assertEqual(cr.model_window("claude-opus-5"), 1000000)
        self.assertEqual(cr.model_window("claude-haiku-4-5"), 200000)

    def test_a_dated_slug_resolves_to_the_family(self):
        self.assertEqual(cr.model_window("claude-haiku-4-5-20251001"), 200000)

    def test_a_bracketed_suffix_is_not_part_of_the_slug(self):
        self.assertEqual(cr.model_window("claude-opus-5[1m]"), 1000000)

    def test_an_unknown_slug_is_not_guessed(self):
        # The caller leaves the window unset and goes and looks it up; the rest
        # of that story is in test_models.py.
        self.assertIsNone(cr.model_window("claude-something-9"))
        self.assertIsNone(cr.model_window(None))

    def test_window_sizes_are_written_the_way_people_write_them(self):
        self.assertEqual(cr.parse_tokens("200k"), 200000)
        self.assertEqual(cr.parse_tokens("1M"), 1000000)
        self.assertEqual(cr.parse_tokens("1_000_000"), 1000000)
        self.assertEqual(cr.parse_tokens("450000"), 450000)

    def test_auto_is_not_a_size(self):
        for text in ("auto", "", None, "lots", "0"):
            self.assertIsNone(cr.parse_tokens(text), text)


def assistant(text="ok", tokens=None, model="claude-opus-5", stop="end_turn",
              sidechain=False):
    msg = {"role": "assistant", "model": model, "stop_reason": stop,
           "content": [{"type": "text", "text": text}]}
    if tokens is not None:
        msg["usage"] = {"input_tokens": 2, "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": tokens - 2, "output_tokens": 100}
    return {"type": "assistant", "isSidechain": sidechain, "message": msg}


class TestAssistantRows(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cr-ar-")
        self.path = os.path.join(self.dir, "s.jsonl")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def write(self, *records):
        with open(self.path, "a") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")

    def rows(self):
        return cr.transcript_limit_records(self.path, 0)[1]

    def test_an_alive_row_carries_the_figures(self):
        self.write(assistant(tokens=612412))
        row = self.rows()[0]
        self.assertEqual(row["tokens"], 612412)
        self.assertEqual(row["model"], "claude-opus-5")
        self.assertEqual(row["stop_reason"], "end_turn")
        self.assertFalse(row["sidechain"])

    def test_a_collapse_keeps_the_newest_figures(self):
        # One answer is many rows. Collapsing them to the FIRST would freeze the
        # context reading at whatever it was when the answer started, which for a
        # long answer is a threshold that arrives an answer late.
        self.write(assistant(tokens=100, stop="tool_use"),
                   assistant(tokens=200, stop="tool_use"),
                   assistant(tokens=300, stop="end_turn"))
        rows = self.rows()
        self.assertEqual([r["kind"] for r in rows], ["alive"])
        self.assertEqual(rows[0]["tokens"], 300)
        self.assertEqual(rows[0]["stop_reason"], "end_turn")

    def test_a_subagents_row_is_marked_as_one(self):
        # A subagent writes into the session's own transcript, and its usage is
        # its context, not the session's.
        self.write(assistant(tokens=40000, sidechain=True))
        self.assertTrue(self.rows()[0]["sidechain"])

    def test_a_row_with_no_usage_still_says_the_session_answered(self):
        self.write(assistant())
        row = self.rows()[0]
        self.assertEqual(row["kind"], "alive")
        self.assertIsNone(row["tokens"])


class TestWhichTranscriptIsOurs(unittest.TestCase):
    """A project directory holds more than one live transcript. For a limit that
    never mattered — a limit is the account's. For the context trigger it is the
    whole question: another session's usage read as ours is a restart at the
    wrong moment, or none at all."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cr-cur-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def append(self, name, rec, mtime=None):
        p = os.path.join(self.dir, name)
        with open(p, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    def test_every_record_says_which_file_it_came_from(self):
        w = cr.TranscriptWatcher(self.dir, poll=0)
        p = self.append("a.jsonl", assistant(tokens=5))
        self.assertEqual(w.poll_now()[0]["path"], p)

    def test_the_transcript_that_did_not_exist_before_us_is_ours(self):
        # `claude` writes its transcript within a second of starting; anything
        # else in the directory was there first.
        old = self.append("old.jsonl", assistant(tokens=1), mtime=1000)
        w = cr.TranscriptWatcher(self.dir, poll=0)
        self.append("old.jsonl", assistant(tokens=2), mtime=3000)
        mine = self.append("mine.jsonl", assistant(tokens=3), mtime=2000)
        w.poll_now()
        self.assertEqual(w.current, mine)
        self.assertEqual(sorted(w.grown), sorted([old, mine]))

    def test_it_stays_with_the_file_it_picked_while_that_file_grows(self):
        # Another session writing a burst in between must not steal the reading.
        w = cr.TranscriptWatcher(self.dir, poll=0)
        mine = self.append("mine.jsonl", assistant(tokens=1), mtime=1000)
        w.poll_now()
        self.assertEqual(w.current, mine)
        self.append("mine.jsonl", assistant(tokens=2), mtime=1000)
        self.append("other.jsonl", assistant(tokens=3), mtime=9000)
        w.poll_now()
        self.assertEqual(w.current, mine)

    def test_it_follows_the_session_into_a_new_file(self):
        # Which is what `/clear` looks like from here: the old transcript stops
        # and a new one appears.
        w = cr.TranscriptWatcher(self.dir, poll=0)
        self.append("before.jsonl", assistant(tokens=1), mtime=1000)
        w.poll_now()
        after = self.append("after.jsonl", assistant(tokens=2), mtime=2000)
        w.poll_now()
        self.assertEqual(w.current, after)

    def test_nothing_grew_means_nothing_grew(self):
        w = cr.TranscriptWatcher(self.dir, poll=0)
        self.append("a.jsonl", assistant(tokens=1))
        w.poll_now()
        w.poll_now()
        self.assertEqual(w.grown, [])


class TestSeveralEchoes(unittest.TestCase):
    """A restart types more than one thing, and each of them has to be
    recognisable coming back."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cr-ec-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def append(self, name, rec):
        with open(os.path.join(self.dir, name), "a") as fh:
            fh.write(json.dumps(rec) + "\n")

    def test_any_of_the_messages_we_type_is_an_echo(self):
        w = cr.TranscriptWatcher(self.dir, poll=0,
                                 echo=["continue", "Read `h.md` and continue from it."])
        self.append("s.jsonl", user_row("Read `h.md` and continue from it."))
        found = w.poll_now()
        self.assertEqual([r["kind"] for r in found], ["echo"])
        self.assertEqual(found[0]["text"], "Read `h.md` and continue from it.")

    def test_a_message_with_characters_json_escapes_still_matches(self):
        # The prefilter builds its needle with json.dumps for exactly this: a
        # quote or a backslash is written escaped in the row.
        msg = 'continue with "the plan" \\ now'
        w = cr.TranscriptWatcher(self.dir, poll=0, echo=[msg])
        self.append("s.jsonl", user_row(msg))
        self.assertEqual([r["kind"] for r in w.poll_now()], ["echo"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
