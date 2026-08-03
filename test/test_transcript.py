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


if __name__ == "__main__":
    unittest.main(verbosity=2)
