"""The corner badge: what it says, where it lands, and when it is allowed to draw.

The badge writes into the same terminal Claude Code is repainting, so the parts
worth pinning down are the ones that keep it from being seen at all: it must
never land in the last cell (which scrolls the screen), never draw while a
control sequence of Claude's is still half-received, and always leave the cursor
and colour exactly as it found them.
"""
import unittest

from helper import load

cr = load(CR_BADGE="1")
B = cr.Badge


def badge(**over):
    cfg = dict(cr.CFG)
    cfg.update({"badge": True, "badge_pos": "bottom-right", "badge_label": "cr"})
    cfg.update(over)
    return cr.Badge(cfg)


class TestText(unittest.TestCase):
    def test_idle_is_just_the_mark_and_the_label(self):
        text, sgr = badge().frame(cr.IDLE, 0, 0, 3, 0)
        self.assertEqual(text, "◆ cr")
        self.assertEqual(sgr, "2")                 # dim, no colour

    def test_waiting_shows_the_time_left(self):
        text, _ = badge().frame(cr.WAITING, 5000, 0, 3, 0)
        self.assertEqual(text, "◆ cr 1h23m")

    def test_verifying_shows_the_attempt(self):
        text, _ = badge().frame(cr.VERIFY, 0, 2, 3, 0)
        self.assertEqual(text, "◆ cr 2/3")

    def test_giving_up_says_so(self):
        text, sgr = badge().frame(cr.DONE, 0, 3, 3, 0)
        self.assertIn("stopped", text)
        self.assertIn("31", sgr)                   # red

    def test_the_label_is_configurable(self):
        text, _ = badge(badge_label="claude-retrier").frame(cr.IDLE, 0, 0, 3, 0)
        self.assertEqual(text, "◆ claude-retrier")

    def test_waiting_blinks_but_nothing_else_does(self):
        b = badge()
        marks = {b.frame(cr.WAITING, 60, 0, 3, t)[0][0] for t in (0, b.PULSE, 2 * b.PULSE)}
        self.assertEqual(marks, {b.MARK, b.MARK_ALT})
        idle = {b.frame(cr.IDLE, 0, 0, 3, t)[0][0] for t in (0, b.PULSE, 2 * b.PULSE)}
        self.assertEqual(idle, {b.MARK})

    def test_the_countdown_is_coarse(self):
        # Anything that ticks once a second in the corner of the eye is a
        # distraction, so minutes and hours are rounded, not counted down.
        self.assertEqual(cr.human_left(0), "0s")
        self.assertEqual(cr.human_left(45), "45s")
        self.assertEqual(cr.human_left(60), "1m")
        self.assertEqual(cr.human_left(3599), "59m")
        self.assertEqual(cr.human_left(3600), "1h00m")
        self.assertEqual(cr.human_left(18000), "5h00m")
        self.assertEqual(cr.human_left(-10), "0s")


class TestPlacement(unittest.TestCase):
    def test_the_last_column_is_left_empty(self):
        # A character written into the bottom-right cell wraps and scrolls the
        # whole screen by a line — the one way this feature could destroy the
        # session it is decorating.
        spot = badge().place(40, 120, 10)
        self.assertEqual(spot, (40, 110))          # occupies 110..119, col 120 free

    def test_each_corner_is_reachable(self):
        self.assertEqual(badge(badge_pos="bottom-left").place(40, 120, 10), (40, 1))
        self.assertEqual(badge(badge_pos="top-right").place(40, 120, 10), (1, 110))
        self.assertEqual(badge(badge_pos="top-left").place(40, 120, 10), (1, 1))

    def test_an_unknown_position_falls_back(self):
        self.assertEqual(badge(badge_pos="middle-of-nowhere").pos, "bottom-right")

    def test_a_tiny_terminal_gets_nothing(self):
        self.assertIsNone(badge().place(40, 11, 10))   # no room to keep a spare column
        self.assertIsNone(badge().place(1, 120, 10))


class TestSequence(unittest.TestCase):
    def test_cursor_and_colour_are_restored(self):
        seq = badge().sequence(40, 120, "◆ cr", "2").decode()
        self.assertTrue(seq.startswith("\x1b7"))       # DECSC: cursor + SGR saved
        self.assertTrue(seq.endswith("\x1b8"))         # DECRC: both restored
        self.assertIn("\x1b[40;116H", seq)
        self.assertIn("\x1b[2m◆ cr\x1b[0m", seq)

    def test_no_newline_is_ever_emitted(self):
        # A newline in the bottom row scrolls the screen; there must not be one.
        seq = badge().sequence(40, 120, "◆ cr 1h23m", "2;33").decode()
        self.assertNotIn("\n", seq)
        self.assertNotIn("\r", seq)

    def test_nothing_is_produced_when_it_does_not_fit(self):
        self.assertIsNone(badge().sequence(40, 4, "◆ cr", "2"))


class TestPaintTiming(unittest.TestCase):
    def setUp(self):
        self.b = badge()

    def due(self, now, text="◆ cr", blocked=False):
        return self.b.due(text, now, blocked)

    def test_it_waits_for_claude_to_finish_its_frame(self):
        self.b.note_output(100.0)
        self.assertFalse(self.due(100.0 + self.b.QUIET / 2))
        self.assertTrue(self.due(100.0 + self.b.QUIET + 0.01))

    def test_a_half_received_sequence_blocks_it(self):
        self.b.note_output(100.0)
        self.assertFalse(self.due(101.0, blocked=True))
        self.assertTrue(self.due(101.0))

    def test_an_unchanged_badge_is_not_redrawn_on_a_quiet_screen(self):
        self.b.note_output(100.0)
        self.assertTrue(self.due(101.0))
        self.b.last_paint, self.b.pending, self.b.painted = 101.0, False, "◆ cr"
        self.assertFalse(self.due(105.0))              # nothing drew, nothing changed
        self.assertTrue(self.due(105.0, text="◆ cr 5m"))

    def test_output_from_claude_makes_it_redraw(self):
        self.b.last_paint, self.b.pending, self.b.painted = 100.0, False, "◆ cr"
        self.assertFalse(self.due(101.0))
        self.b.note_output(101.0)                      # claude repainted over it
        self.assertTrue(self.due(101.0 + self.b.QUIET + 0.01))

    def test_the_repaint_rate_has_a_floor(self):
        self.b.last_paint = 100.0
        self.b.pending = True
        self.assertFalse(self.due(100.0 + self.b.MIN_INTERVAL / 2))
        self.assertTrue(self.due(100.0 + self.b.MIN_INTERVAL + 0.01))

    def test_disabled_means_silent(self):
        b = badge(badge=False)
        b.note_output(0.0)
        self.assertFalse(b.due("◆ cr", 100.0))


class TestPaintAndErase(unittest.TestCase):
    """paint()/erase() against a real fd, so the bytes are the ones that ship."""

    def fd(self):
        import os
        import tempfile
        path = tempfile.mktemp(prefix="cr-badge-")
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)

        def read():
            os.lseek(fd, 0, 0)
            return os.read(fd, 65536).decode()
        return fd, read

    def test_painting_writes_the_sequence_once(self):
        fd, read = self.fd()
        b = badge()
        self.assertTrue(b.paint(fd, 40, 120, cr.IDLE, 0, 0, 3, 100.0))
        self.assertIn("\x1b[40;116H", read())
        self.assertFalse(b.paint(fd, 40, 120, cr.IDLE, 0, 0, 3, 100.1))

    def test_erasing_covers_exactly_what_was_drawn(self):
        fd, read = self.fd()
        b = badge()
        b.paint(fd, 40, 120, cr.WAITING, 5000, 0, 3, 100.0)
        b.erase(fd, 40, 120)
        out = read()
        self.assertIn("\x1b[0m" + " " * len("◆ cr 1h23m"), out)
        self.assertIsNone(b.painted)

    def test_erasing_without_a_badge_writes_nothing(self):
        fd, read = self.fd()
        badge().erase(fd, 40, 120)
        self.assertEqual(read(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
