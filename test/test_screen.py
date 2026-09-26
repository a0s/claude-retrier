"""The terminal emulator (T27): the grid agent-retrier.sh renders its own
subagent-tree overlay against, exercised the way the real supervisor drives
it — fed with raw pty bytes, not hand-picked escape sequences.
"""
import os
import unittest

from helper import load
from screen import Screen

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "agent-tree-2.1.273.bin")
FIXTURE_PANEL = os.path.join(HERE, "fixtures", "agents-panel-2.1.273.bin")


class TestOneSource(unittest.TestCase):
    def test_screen_py_has_no_implementation_of_its_own(self):
        # test/screen.py re-exports agent-retrier.sh's own Screen rather than
        # keeping a second copy, so the two can never quietly drift apart the
        # way a hand-maintained duplicate eventually does.
        with open(os.path.join(HERE, "screen.py")) as fh:
            src = fh.read()
        self.assertNotIn("class Screen", src)
        self.assertIn("from helper import load", src)


class TestRealCapture(unittest.TestCase):
    """Byte-for-byte pty output from a real Claude Code 2.1.273 session
    spawning subagents (test/fixtures/README.md). The render is differential
    and word-split — grep finds nothing in it — so the only way to check the
    tree lands where a human would see it is to render it."""

    def setUp(self):
        with open(FIXTURE, "rb") as fh:
            data = fh.read()
        self.screen = Screen(50, 120)
        self.screen.feed(data.decode("utf-8", "replace"))

    def test_it_never_scrolled(self):
        self.assertEqual(self.screen.scrolled, 0)

    def test_the_tree_rows_land_where_a_human_sees_them(self):
        cr = load()
        labels = [label for _, label, _ in cr.find_agent_rows(self.screen)]
        self.assertIn("Find second file in cwd", labels)
        self.assertIn("Find first file in cwd", labels)
        self.assertIn("Count files in cwd", labels)
        # the child's own status line is never mistaken for an agent's row
        self.assertNotIn("Initializing…", " ".join(labels))


class TestRealCaptureAgentsPanel(unittest.TestCase):
    """T29: the OTHER subagent view, opened by typing /tasks while at least
    one is still running -- a real Claude Code 2.1.273 capture
    (test/fixtures/README.md), not the transient inline tree TestRealCapture
    above already covers. Live investigation established the footer's own
    "<- for agents" hint does NOT open this in either permission mode -- it
    backgrounds the conversation into the cross-session roster instead, which
    is why nothing in this file ever sends that key.
    """

    def setUp(self):
        with open(FIXTURE_PANEL, "rb") as fh:
            data = fh.read()
        self.screen = Screen(50, 120)
        self.screen.feed(data.decode("utf-8", "replace"))

    def test_it_never_scrolled(self):
        self.assertEqual(self.screen.scrolled, 0)

    def test_the_panel_rows_land_where_a_human_sees_them(self):
        cr = load()
        found = cr.find_panel_agent_rows(self.screen)
        labels = [label for _, label, _ in found]
        self.assertEqual(len(found), 3)
        self.assertIn("Count files under /usr", labels)
        self.assertIn("Count files under /System/Library", labels)
        self.assertIn("Count files under /Applications", labels)
        # the section header ("Local agents (3)") is never one of them
        self.assertFalse(any("Local agents" in label for label in labels))


class TestScrollRegion(unittest.TestCase):
    def rows(self, s):
        return [s.line(n) for n in range(1, s.rows + 1)]

    def test_a_newline_at_the_bottom_margin_scrolls_only_the_region(self):
        s = Screen(10, 20)
        for i in range(1, 11):
            s.feed("\x1b[%d;1Hrow%d" % (i, i))
        s.feed("\x1b[3;6r")            # DECSTBM: rows 3..6 only
        s.feed("\x1b[6;1H\n")          # at the region's bottom margin
        self.assertEqual(self.rows(s)[:2], ["row1", "row2"])
        self.assertEqual(self.rows(s)[2:6], ["row4", "row5", "row6", ""])
        self.assertEqual(self.rows(s)[6:], ["row7", "row8", "row9", "row10"])

    def test_a_region_scroll_never_counts_against_the_whole_screen(self):
        # `scrolled` is what a badge/overlay test uses to prove it never moved
        # claude's own history — a scroll confined to a mid-screen region must
        # not trip that alarm.
        s = Screen(10, 20)
        s.feed("\x1b[3;6r\x1b[6;1H\n")
        self.assertEqual(s.scrolled, 0)

    def test_ri_reverse_scrolls_at_the_top_margin(self):
        s = Screen(10, 20)
        for i in range(1, 11):
            s.feed("\x1b[%d;1Hrow%d" % (i, i))
        s.feed("\x1b[3;6r\x1b[3;1H\x1bM")      # RI at the region's top margin
        self.assertEqual(self.rows(s)[2:6], ["", "row3", "row4", "row5"])


class TestInsertDeleteLine(unittest.TestCase):
    def test_il_pushes_the_rest_of_the_screen_down(self):
        s = Screen(6, 10)
        for i in range(1, 7):
            s.feed("\x1b[%d;1Hr%d" % (i, i))
        s.feed("\x1b[3;1H\x1b[L")
        self.assertEqual([s.line(n) for n in range(1, 7)],
                         ["r1", "r2", "", "r3", "r4", "r5"])
        self.assertEqual(s.scrolled, 0)

    def test_dl_pulls_the_rest_of_the_screen_up(self):
        s = Screen(6, 10)
        for i in range(1, 7):
            s.feed("\x1b[%d;1Hr%d" % (i, i))
        s.feed("\x1b[3;1H\x1b[M")
        self.assertEqual([s.line(n) for n in range(1, 7)],
                         ["r1", "r2", "r4", "r5", "r6", ""])

    def test_il_below_a_narrowed_region_s_margin_is_a_no_op(self):
        # A scroll region confines IL/DL to rows top..bottom; issuing one with
        # the cursor BELOW that margin must not touch the grid at all — a bare
        # slice-assign with top > bottom would insert rather than replace,
        # silently growing the grid past `rows`.
        s = Screen(6, 10)
        for i in range(1, 7):
            s.feed("\x1b[%d;1Hr%d" % (i, i))
        s.feed("\x1b[2;4r")          # region rows 2..4
        s.feed("\x1b[6;1H\x1b[L")    # IL with the cursor on row 6, below the region
        self.assertEqual([s.line(n) for n in range(1, 7)],
                         ["r1", "r2", "r3", "r4", "r5", "r6"])
        self.assertEqual(len(s.cells), 6)


class TestInsertDeleteChar(unittest.TestCase):
    def test_ich_shifts_the_row_right(self):
        s = Screen(3, 10)
        s.feed("\x1b[1;1Habcdef\x1b[1;2H\x1b[2@")
        self.assertEqual(s.line(1), "a  bcdef".rstrip())

    def test_dch_shifts_the_row_left(self):
        s = Screen(3, 10)
        s.feed("\x1b[1;1Habcdef\x1b[1;2H\x1b[2P")
        self.assertEqual(s.line(1), "adef")


class TestSyncFrameAndPrivateModes(unittest.TestCase):
    def test_a_frame_wrapped_in_sync_markers_renders_normally(self):
        s = Screen(3, 10)
        s.feed("\x1b[?2026h\x1b[1;1Hhello\x1b[?2026l")
        self.assertEqual(s.line(1), "hello")
        self.assertEqual(s.cursor(), (1, 6))

    def test_cursor_visibility_toggles_are_pure_no_ops(self):
        s = Screen(3, 10)
        s.feed("\x1b[1;1Hx")
        before = s.text()
        s.feed("\x1b[?25l\x1b[?25h")
        self.assertEqual(s.text(), before)


if __name__ == "__main__":
    unittest.main()
