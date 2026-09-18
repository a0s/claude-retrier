"""The subagent tree overlay (T27): which rows on screen are agents, what each
one is labelled, and which model it is really running on.
"""
import json
import os
import re
import shutil
import tempfile
import unittest

from helper import load
from screen import Screen

cr = load()
find_agent_rows = cr.find_agent_rows
model_label = cr.model_label
SubagentRegistry = cr.SubagentRegistry
AgentOverlay = cr.AgentOverlay

# The exact frame from T27's evidence #5: two Explore agents, the second row
# being the first agent's own child status line ("⎿  Initializing…"), not an
# agent of its own.
EVIDENCE_5 = (
    "\r\x1b[2C\x1b[21BRunning \x1b[1m2\x1b[22m Explore agents…\x1b[29G\x1b[K"
    "\r\x1b[3C\x1b[1B├\x1b[6G\x1b[1mReport first file in cwd\x1b[22m · 0 tool uses"
    "\r\x1b[3C\x1b[1B│\x1b[6G⎿  Initializing…"
    "\r\x1b[3C\x1b[1B└\x1b[6G\x1b[1mReport second file in cwd\x1b[22m · 0 tool uses"
)


def grid(rows=40, cols=120):
    s = Screen(rows, cols)
    s.feed(EVIDENCE_5)
    return s


class TestFindAgentRows(unittest.TestCase):
    def test_it_finds_exactly_the_two_agent_rows(self):
        found = find_agent_rows(grid())
        labels = [label for _, label, _ in found]
        self.assertEqual(len(found), 2)
        self.assertIn("Report first file in cwd", labels)
        self.assertIn("Report second file in cwd", labels)

    def test_the_child_status_line_is_not_one_of_them(self):
        found = find_agent_rows(grid())
        labels = [label for _, label, _ in found]
        self.assertFalse(any("Initializing" in label for label in labels))

    def test_labels_are_ordinary_rows_with_nothing_special(self):
        found = find_agent_rows(Screen(40, 120))
        self.assertEqual(found, [])

    def test_the_label_column_reported_is_the_real_one_not_a_constant(self):
        s = Screen(5, 120)
        s.feed("\x1b[3;4H├\x1b[30GReport first file in cwd")
        found = find_agent_rows(s)
        self.assertEqual(found, [(3, "Report first file in cwd", 30)])


class TestModelLabel(unittest.TestCase):
    def test_known_slugs(self):
        self.assertEqual(model_label("claude-sonnet-5"), "sonnet-5/?")
        self.assertEqual(model_label("claude-haiku-4-5-20251001"), "haiku-4.5/?")
        self.assertEqual(model_label("claude-opus-5[1m]"), "opus-5[1m]/?")

    def test_effort_is_shown_when_it_was_actually_read(self):
        self.assertEqual(model_label("claude-fable-5-1", "high"), "fable-5.1/high")

    def test_before_the_first_assistant_line_the_model_is_unknown(self):
        self.assertEqual(model_label(None), "…")

    def test_a_label_collision_shows_a_bare_question_mark(self):
        self.assertEqual(model_label("?"), "?")

    def test_an_unfamiliar_slug_is_shown_verbatim_rather_than_guessed_at(self):
        self.assertEqual(model_label("claude-something-new"), "claude-something-new/?")


class TestSubagentRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cr-agents-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.session = os.path.join(self.tmp, "sess-1.jsonl")
        with open(self.session, "w"):
            pass
        self.subdir = os.path.join(self.tmp, "sess-1", "subagents")
        os.makedirs(self.subdir)

    def write_meta(self, agent_id, description, spawn_model=None):
        meta = {"agentType": "general-purpose", "description": description,
                "toolUseId": "toolu_%s" % agent_id, "spawnDepth": 1}
        if spawn_model:
            # T27 evidence: forks have been seen to IGNORE this and run on a
            # different model entirely — it must never be read as truth.
            meta["requestedModel"] = spawn_model
        path = os.path.join(self.subdir, "agent-%s.meta.json" % agent_id)
        with open(path, "w") as fh:
            json.dump(meta, fh)

    def write_turn(self, agent_id, model, effort=None, sidechain=False):
        rec = {"type": "assistant", "isSidechain": sidechain,
               "message": {"model": model, "content": []}}
        if effort:
            rec["effort"] = effort
        path = os.path.join(self.subdir, "agent-%s.jsonl" % agent_id)
        with open(path, "a") as fh:
            fh.write(json.dumps(rec) + "\n")

    def registry(self):
        return SubagentRegistry(poll=0.0)

    def test_a_poll_landing_mid_write_does_not_permanently_lose_the_record(self):
        # A poll can land while the agent's jsonl is only partway through
        # being flushed. The half-written line must be left for the next
        # poll rather than parsed (and its offset consumed) half-written —
        # otherwise the rest of it, once it does land, starts mid-record and
        # can never be parsed at all.
        self.write_meta("a1", "Report first file in cwd")
        rec = json.dumps({"type": "assistant", "isSidechain": False,
                          "message": {"model": "claude-sonnet-5", "content": []}}) + "\n"
        path = os.path.join(self.subdir, "agent-a1.jsonl")
        cut = len(rec) // 2
        with open(path, "w") as fh:
            fh.write(rec[:cut])          # no trailing newline: a partial line
        reg = self.registry()
        reg.poll_now(self.session, now=0.0)
        self.assertIsNone(reg.model_for("Report first file in cwd"))
        with open(path, "a") as fh:
            fh.write(rec[cut:])          # the rest lands, completing the line
        reg.poll_now(self.session, now=0.0)
        self.assertEqual(reg.model_for("Report first file in cwd"), ("claude-sonnet-5", None))

    def test_the_model_comes_from_the_agent_s_own_transcript(self):
        # Regression on the exact real case T27 caught: spawned as "sonnet",
        # actually ran on opus.
        self.write_meta("a1", "Report first file in cwd", spawn_model="sonnet")
        self.write_turn("a1", "claude-opus-5")
        reg = self.registry()
        reg.poll_now(self.session, now=0.0)
        self.assertEqual(reg.model_for("Report first file in cwd"), ("claude-opus-5", None))

    def test_unknown_before_any_turn_has_run(self):
        self.write_meta("a1", "Report first file in cwd")
        reg = self.registry()
        reg.poll_now(self.session, now=0.0)
        self.assertIsNone(reg.model_for("Report first file in cwd"))

    def test_effort_is_read_when_present(self):
        self.write_meta("a1", "Plan the refactor")
        self.write_turn("a1", "claude-fable-5-1", effort="high")
        reg = self.registry()
        reg.poll_now(self.session, now=0.0)
        self.assertEqual(reg.model_for("Plan the refactor"), ("claude-fable-5-1", "high"))

    def test_two_agents_sharing_a_label_collide_to_a_question_mark(self):
        self.write_meta("a1", "Explore the repo")
        self.write_meta("a2", "Explore the repo")
        self.write_turn("a1", "claude-sonnet-5")
        self.write_turn("a2", "claude-haiku-4-5-20251001")
        reg = self.registry()
        reg.poll_now(self.session, now=0.0)
        self.assertEqual(reg.model_for("Explore the repo"), ("?", None))

    def test_a_sidechain_row_is_not_read_as_the_agent_s_own_model(self):
        self.write_meta("a1", "Report first file in cwd")
        self.write_turn("a1", "claude-haiku-4-5-20251001", sidechain=True)
        reg = self.registry()
        reg.poll_now(self.session, now=0.0)
        self.assertIsNone(reg.model_for("Report first file in cwd"))

    def test_switching_sessions_forgets_the_old_one(self):
        self.write_meta("a1", "Report first file in cwd")
        self.write_turn("a1", "claude-sonnet-5")
        reg = self.registry()
        reg.poll_now(self.session, now=0.0)
        self.assertIsNotNone(reg.model_for("Report first file in cwd"))
        other = os.path.join(self.tmp, "sess-2.jsonl")
        with open(other, "w"):
            pass
        os.makedirs(os.path.join(self.tmp, "sess-2", "subagents"))
        reg.poll_now(other, now=0.0)
        self.assertIsNone(reg.model_for("Report first file in cwd"))

    def test_a_second_poll_within_the_interval_does_no_work(self):
        self.write_meta("a1", "Report first file in cwd")
        self.write_turn("a1", "claude-sonnet-5")
        reg = SubagentRegistry(poll=100.0)
        reg.poll_now(self.session, now=0.0)
        self.write_meta("a2", "Report second file in cwd")
        self.write_turn("a2", "claude-haiku-4-5-20251001")
        reg.poll_now(self.session, now=1.0)     # still inside the 100s window
        self.assertIsNone(reg.model_for("Report second file in cwd"))
        reg.poll_now(self.session, now=100.0)
        self.assertIsNotNone(reg.model_for("Report second file in cwd"))


def _fd(cls):
    path = tempfile.mktemp(prefix="cr-agents-fd-")
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    cls.addCleanup(os.close, fd)

    def read():
        os.lseek(fd, 0, 0)
        return os.read(fd, 65536).decode()
    return fd, read


class TestAgentOverlay(unittest.TestCase):
    def cfg(self, **over):
        c = dict(agents_overlay=True, agents_pos="right")
        c.update(over)
        return c

    class FakeRegistry:
        def __init__(self, models):
            self.models = models

        def model_for(self, label):
            return self.models.get(label)

    def test_off_by_default_writes_nothing(self):
        overlay = AgentOverlay(self.cfg(agents_overlay=False))
        fd, read = _fd(self)
        wrote = overlay.paint(fd, 40, 120, grid(), self.FakeRegistry({}))
        self.assertFalse(wrote)
        self.assertEqual(read(), "")

    def test_a_shrinking_annotation_does_not_overrun_the_row(self):
        # Field-shape regression: an effort suffix that stops being read
        # ("fable-5.1/high" -> "fable-5.1/?") or two agents colliding down to
        # a bare "?" both shrink the text on a row already painted wider. The
        # column has to move with the OLD (wider) footprint, not the new
        # text's own — placing it at the new width while still padding out to
        # the old one would write past where it was placed.
        s = Screen(5, 120)
        s.feed("\x1b[3;4H└\x1b[6GReport second file in cwd")
        overlay = AgentOverlay(self.cfg())
        fd, read = _fd(self)
        wide = self.FakeRegistry({"Report second file in cwd": ("claude-fable-5-1", "high")})
        self.assertTrue(overlay.paint(fd, 5, 120, s, wide))
        narrow = self.FakeRegistry({"Report second file in cwd": ("claude-fable-5-1", None)})
        self.assertTrue(overlay.paint(fd, 5, 120, s, narrow))
        last = read().split("\x1b7")[-1]
        self.assertIn("fable-5.1/?", last)
        m = re.search(r"\x1b\[3;(\d+)H\x1b\[2m(.*?)\x1b\[0m", last)
        self.assertIsNotNone(m)
        col, drawn = int(m.group(1)), m.group(2)
        # never touches column 120 (1-based, the last one) or beyond
        self.assertLessEqual(col + len(drawn) - 1, 119)

    def test_annotation_lands_at_the_right_edge_with_the_last_column_free(self):
        overlay = AgentOverlay(self.cfg())
        fd, read = _fd(self)
        registry = self.FakeRegistry({"Report first file in cwd": ("claude-sonnet-5", None),
                                      "Report second file in cwd": ("claude-haiku-4-5-20251001", None)})
        self.assertTrue(overlay.paint(fd, 40, 120, grid(), registry))
        out = read()
        self.assertIn("sonnet-5/?", out)
        self.assertIn("haiku-4.5/?", out)
        # placed at column 120 - len("sonnet-5/?") = 110, never touching 120
        self.assertIn("\x1b[23;110H", out)
        self.assertNotIn(";120H", out)

    def test_it_never_contests_the_badge_s_own_row(self):
        overlay = AgentOverlay(self.cfg())
        s = Screen(23, 120)     # the agent row lands on the last row (23)
        s.feed(EVIDENCE_5)
        fd, read = _fd(self)
        registry = self.FakeRegistry({"Report second file in cwd": ("claude-sonnet-5", None)})
        overlay.paint(fd, 23, 120, s, registry)
        self.assertEqual(read(), "")

    def test_it_does_not_paint_over_claude_s_own_text(self):
        # A row whose own content already reaches near the right edge leaves no
        # clean gap to annotate into.
        s = Screen(5, 40)
        s.feed("\x1b[3;1H   ├\x1b[6G" + "x" * 32)   # runs to col 38 of 40
        overlay = AgentOverlay(self.cfg())
        fd, read = _fd(self)
        registry = self.FakeRegistry({"x" * 32: ("claude-sonnet-5", None)})
        wrote = overlay.paint(fd, 5, 40, s, registry)
        self.assertFalse(wrote)
        self.assertEqual(read(), "")

    def test_an_agent_with_no_model_yet_shows_the_unknown_mark(self):
        overlay = AgentOverlay(self.cfg())
        fd, read = _fd(self)
        overlay.paint(fd, 40, 120, grid(), self.FakeRegistry({}))
        self.assertIn("…", read())     # "…"

    def test_agents_pos_label_lands_just_before_the_label_instead(self):
        # A row with room to its left: glyph at column 4, label starting at
        # column 30 rather than the usual 6 — find_agent_rows reports the
        # label's REAL column, not a fixed constant.
        s = Screen(5, 120)
        s.feed("\x1b[3;4H├\x1b[30GReport first file in cwd")
        overlay = AgentOverlay(self.cfg(agents_pos="label"))
        fd, read = _fd(self)
        registry = self.FakeRegistry({"Report first file in cwd": ("claude-sonnet-5", None)})
        self.assertTrue(overlay.paint(fd, 5, 120, s, registry))
        out = read()
        self.assertIn("sonnet-5/?", out)
        self.assertIn("\x1b[3;19H", out)     # column 30 - len("sonnet-5/?") - 1

    def test_agents_pos_label_is_skipped_when_there_is_no_room_before_it(self):
        # A label starting at column 6 (evidence #5's own position) leaves no
        # room for a 10-cell annotation to sit to its left without going
        # negative — a single-row screen isolates this from the OTHER agent
        # row evidence #5 also carries, whose model is unknown and would fit.
        s = Screen(5, 120)
        s.feed("\x1b[3;4H└\x1b[6GReport second file in cwd")
        overlay = AgentOverlay(self.cfg(agents_pos="label"))
        fd, read = _fd(self)
        registry = self.FakeRegistry({"Report second file in cwd": ("claude-haiku-4-5-20251001", None)})
        wrote = overlay.paint(fd, 5, 120, s, registry)
        self.assertFalse(wrote)
        self.assertEqual(read(), "")


if __name__ == "__main__":
    unittest.main()
