"""The decision layer: when it is safe to type into someone else's session.

Every guard here exists because the tmux design got it wrong at least once:
 - #7/#19  the retry landed in the input box but was never submitted
 - #19     a bare Enter confirmed "Upgrade your plan" in the limit menu
 - #21     a cleared banner at reset time was misread as "the user resumed"
 - #39     a second limit arriving during a wait was never noticed
and the "don't type over a half-written prompt" case, which the tmux design
listed as unsolvable by scraping (DESIGN-NOTES §6) but is trivial here: we are
the terminal, so we see the keystrokes.
"""
import unittest

from helper import load

cr = load()

CFG = dict(message="continue", margin=0, max_attempts=3, fallback_wait=18000,
           max_wait=691200, user_idle=20, busy_idle=6, verify=60, wait_scale=1,
           draft_grace=600)

BANNER = "You've hit your session limit · resets in 2 hours"


def controller(**over):
    cfg = dict(CFG)
    cfg.update(over)
    logs = []
    ctl = cr.Controller(cfg, logs.append, now=0)
    ctl.log_lines = logs
    return ctl


class TestScheduling(unittest.TestCase):
    def test_a_limit_schedules_a_wake_up_at_the_reset(self):
        ctl = controller()
        self.assertTrue(ctl.on_limit(BANNER, now=1000, source="transcript"))
        self.assertEqual(ctl.state, cr.WAITING)
        self.assertAlmostEqual(ctl.wake_at, 1000 + 7200, delta=1)

    def test_margin_is_added(self):
        ctl = controller(margin=45)
        ctl.on_limit(BANNER, now=0, source="transcript")
        self.assertAlmostEqual(ctl.wake_at, 7245, delta=1)

    def test_unparseable_banner_uses_the_fallback_wait(self):
        ctl = controller()
        ctl.on_limit("You've hit your session limit", now=0, source="transcript")
        self.assertAlmostEqual(ctl.wake_at, 18000, delta=1)

    def test_wait_is_capped(self):
        ctl = controller(max_wait=100)
        ctl.on_limit("resets in 40 days", now=0, source="transcript")
        self.assertAlmostEqual(ctl.wake_at, 100, delta=1)

    def test_the_same_banner_does_not_reschedule(self):
        # The banner is repainted continuously and the transcript may report it
        # too; only the first sighting sets the timer.
        ctl = controller()
        self.assertTrue(ctl.on_limit(BANNER, now=0, source="screen"))
        self.assertFalse(ctl.on_limit(BANNER, now=5, source="transcript"))
        self.assertFalse(ctl.on_limit("  YOU'VE HIT YOUR SESSION LIMIT · resets in 2 hours ",
                                      now=6, source="screen"))
        self.assertAlmostEqual(ctl.wake_at, 7200, delta=1)

    def test_a_new_limit_during_a_wait_supersedes_the_old_one(self):
        # Upstream #39: a monitor parked on a stale timer never re-evaluated, so
        # a second, genuine limit was ignored for hours.
        ctl = controller()
        ctl.on_limit("resets in 10 hours", now=0, source="transcript")
        self.assertAlmostEqual(ctl.wake_at, 36000, delta=1)
        ctl.on_limit("resets in 1 hours", now=100, source="transcript")
        self.assertAlmostEqual(ctl.wake_at, 3700, delta=1)


class TestInjection(unittest.TestCase):
    def test_nothing_happens_before_the_reset(self):
        ctl = controller()
        ctl.on_limit(BANNER, now=0, source="transcript")
        self.assertIsNone(ctl.tick(7100))

    def test_the_retry_fires_at_the_reset(self):
        ctl = controller()
        ctl.on_limit(BANNER, now=0, source="transcript")
        action = ctl.tick(7201)
        self.assertEqual(action, ("inject", "continue", False))
        self.assertEqual(ctl.state, cr.VERIFY)

    def test_the_menu_is_dismissed_first(self):
        # Upstream #19: Enter into /rate-limit-options confirmed "Upgrade your plan".
        ctl = controller()
        ctl.on_output("What do you want to do?\n 2. Stop and wait for limit to reset", now=0)
        ctl.on_limit(BANNER, now=0, source="screen")
        action = ctl.tick(7201)
        self.assertEqual(action, ("inject", "continue", True))

    def test_a_cleared_banner_still_gets_a_retry(self):
        # Upstream #21: Claude clears the banner exactly when the limit lifts, and
        # the monitor read that as "the user must have continued" — then sent
        # nothing, leaving the session idle. Nothing here consults the banner at
        # wake-up time; only "is the session busy" gates the send.
        ctl = controller()
        ctl.on_limit(BANNER, now=0, source="transcript")
        self.assertIsNotNone(ctl.tick(7201))


class TestSafetyGates(unittest.TestCase):
    def setUp(self):
        self.ctl = controller()
        self.ctl.on_limit(BANNER, now=0, source="transcript")

    def test_not_while_claude_is_working(self):
        self.ctl.on_output("✻ Cogitating… (esc to interrupt)", now=7200)
        self.assertIsNone(self.ctl.tick(7201))
        self.assertEqual(self.ctl.state, cr.WAITING)

    def test_retries_once_the_session_goes_quiet(self):
        self.ctl.on_output("✻ Cogitating… (esc to interrupt)", now=7200)
        self.ctl.tick(7201)
        self.assertIsNotNone(self.ctl.tick(7300))

    def test_not_while_the_user_is_typing(self):
        self.ctl.on_user_bytes(b"hel", now=7195)
        self.assertIsNone(self.ctl.tick(7201))

    def test_not_over_unsent_text_in_the_prompt_box(self):
        # DESIGN-NOTES §6 calls this unsolvable by scraping. Owning the pty makes
        # it a byte count: characters typed since the last Enter.
        self.ctl.on_user_bytes(b"half a thought", now=7100)
        self.assertIsNone(self.ctl.tick(7201))
        self.ctl.on_user_bytes(b"\r", now=7202)          # user submits it
        self.assertIsNotNone(self.ctl.tick(7300))

    def test_backspacing_the_draft_away_clears_the_gate(self):
        self.ctl.on_user_bytes(b"ab", now=0)
        self.ctl.on_user_bytes(b"\x7f\x7f", now=1)
        self.assertIsNotNone(self.ctl.tick(7201))

    def test_ctrl_u_clears_the_gate(self):
        self.ctl.on_user_bytes(b"draft", now=0)
        self.ctl.on_user_bytes(b"\x15", now=1)
        self.assertIsNotNone(self.ctl.tick(7201))

    def test_arrow_keys_do_not_count_as_a_draft(self):
        self.ctl.on_user_bytes(b"\x1b[A", now=0)         # up arrow: an escape seq
        self.assertIsNotNone(self.ctl.tick(7201))


class TestTheTerminalTalksBackToo(unittest.TestCase):
    """Field failure: a session waited out its reset and then deferred the retry
    every 15s for three hours, logging "unsent text in the prompt box" while
    nobody had touched the keyboard. claude sends "\\x1b[>q" at startup and the
    terminal's XTVERSION reply came back on our stdin, where 15 of its bytes were
    counted as typing. Nothing but Enter clears that counter, so the gate stayed
    shut for the rest of the session.

    Everything the terminal can answer with belongs here, not just what a human
    can press.
    """
    def draft_after(self, data):
        ctl = controller()
        ctl.on_user_bytes(data, now=0)
        return ctl.pending_input_chars

    def test_xtversion_reply_is_not_typing(self):
        self.assertEqual(self.draft_after(b"\x1bP>|iTerm2 3.5.11\x1b\\"), 0)

    def test_xtversion_reply_through_tmux_is_not_typing(self):
        self.assertEqual(self.draft_after(b"\x1bP>|tmux 3.5a\x1b\\"), 0)

    def test_a_dcs_reply_terminated_by_bel_is_not_typing(self):
        self.assertEqual(self.draft_after(b"\x1bP1$r0m\x07"), 0)

    def test_an_osc_colour_reply_is_not_typing(self):
        self.assertEqual(
            self.draft_after(b"\x1b]11;rgb:1e1e/1e1e/1e1e\x1b\\"), 0)

    def test_an_osc_reply_terminated_by_bel_is_not_typing(self):
        self.assertEqual(self.draft_after(b"\x1b]10;rgb:c0c0/c0c0/c0c0\x07"), 0)

    def test_a_cursor_position_report_is_not_typing(self):
        self.assertEqual(self.draft_after(b"\x1b[12;40R"), 0)

    def test_a_device_attributes_reply_is_not_typing(self):
        self.assertEqual(self.draft_after(b"\x1b[?1;2c"), 0)

    def test_x10_mouse_coordinates_are_not_typing(self):
        # "\x1b[M" then three raw bytes; claude enables ?1000h, so a terminal
        # without SGR reporting sends these for every click and drag.
        self.assertEqual(self.draft_after(b"\x1b[M\x20\x40\x30"), 0)

    def test_sgr_mouse_reports_are_not_typing(self):
        self.assertEqual(self.draft_after(b"\x1b[<0;36;12M\x1b[<0;36;12m"), 0)

    def test_a_reply_split_across_two_reads_is_not_typing(self):
        ctl = controller()
        ctl.on_user_bytes(b"\x1bP>|iTer", now=0)
        ctl.on_user_bytes(b"m2 3.5.11\x1b\\", now=1)
        self.assertEqual(ctl.pending_input_chars, 0)

    def test_a_reply_arriving_mid_draft_leaves_the_draft_alone(self):
        ctl = controller()
        ctl.on_user_bytes(b"hi", now=0)
        ctl.on_user_bytes(b"\x1bP>|iTerm2 3.5.11\x1b\\", now=1)
        self.assertEqual(ctl.pending_input_chars, 2)

    def test_pasted_text_still_counts(self):
        # Bracketed paste is real content in the box; only the markers are ours
        # to swallow.
        self.assertEqual(self.draft_after(b"\x1b[200~hello\x1b[201~"), 5)


class TestTheGateCannotJam(unittest.TestCase):
    """Whatever desyncs the counter next, the wait must still end. The gate is a
    courtesy to the human; the retry is the product."""
    def test_a_draft_nobody_touches_stops_blocking(self):
        ctl = controller()
        ctl.on_limit(BANNER, now=0, source="transcript")
        ctl.on_user_bytes(b"stray", now=7100)
        self.assertIsNone(ctl.tick(7201))                # inside the grace period
        self.assertIsNotNone(ctl.tick(7100 + 601))
        self.assertTrue(any("stale" in line for line in ctl.log_lines))

    def test_a_draft_being_edited_keeps_blocking(self):
        ctl = controller()
        ctl.on_limit(BANNER, now=0, source="transcript")
        ctl.on_user_bytes(b"a real", now=0)
        for t in range(7201, 7201 + 3000, 300):          # still typing at it
            ctl.on_user_bytes(b"x", now=t - 60)
            self.assertIsNone(ctl.tick(t))


class TestVerifyAndGiveUp(unittest.TestCase):
    def test_a_resumed_session_ends_the_incident(self):
        ctl = controller()
        ctl.on_limit(BANNER, now=0, source="transcript")
        ctl.tick(7201)
        ctl.on_output("✻ Thinking… (esc to interrupt)", now=7210)
        ctl.tick(7211)
        self.assertEqual(ctl.state, cr.IDLE)
        self.assertEqual(ctl.attempts, 0)

    def test_a_retry_that_did_not_take_hold_is_repeated(self):
        ctl = controller()
        ctl.on_limit(BANNER, now=0, source="transcript")
        self.assertIsNotNone(ctl.tick(7201))            # attempt 1
        self.assertIsNotNone(ctl.tick(7201 + 61))       # verify window elapsed
        self.assertEqual(ctl.attempts, 2)

    def test_it_gives_up_rather_than_typing_forever(self):
        ctl = controller(max_attempts=2)
        ctl.on_limit(BANNER, now=0, source="transcript")
        t = 7201
        for _ in range(2):
            self.assertIsNotNone(ctl.tick(t))
            t += 61
        self.assertIsNone(ctl.tick(t))
        self.assertEqual(ctl.state, cr.DONE)

    def test_a_new_limit_reactivates_a_given_up_controller(self):
        ctl = controller(max_attempts=1)
        ctl.on_limit(BANNER, now=0, source="transcript")
        ctl.tick(7201)
        ctl.tick(7300)
        self.assertEqual(ctl.state, cr.DONE)
        ctl.on_limit("resets in 3 hours", now=8000, source="transcript")
        self.assertEqual(ctl.state, cr.WAITING)
        self.assertIsNotNone(ctl.tick(8000 + 10801))


class TestARetryThatWorkedIsNotRepeated(unittest.TestCase):
    """Field failure: the reset came, `continue` went out and claude resumed —
    and the wrapper typed it twice more and then painted "cr stopped", because
    the only thing it watched for was a footer wording that no longer exists.
    The transcript says it plainly, so ask the transcript."""
    def test_the_transcript_echo_ends_the_incident(self):
        ctl = controller()
        ctl.on_limit(BANNER, now=0, source="transcript")
        self.assertIsNotNone(ctl.tick(7201))            # `continue` goes out
        self.assertTrue(ctl.on_echo(now=7203))          # claude logged it
        self.assertEqual(ctl.state, cr.IDLE)
        self.assertEqual(ctl.attempts, 0)
        self.assertIsNone(ctl.tick(7203 + 3600))        # and never types again

    def test_an_echo_outside_an_incident_changes_nothing(self):
        ctl = controller()
        self.assertFalse(ctl.on_echo(now=10))
        self.assertEqual(ctl.state, cr.IDLE)

    def test_the_new_footer_alone_also_ends_it(self):
        # Belt and braces: with no transcript (scrape mode) the screen has to do.
        ctl = controller()
        ctl.on_limit(BANNER, now=0, source="screen")
        ctl.tick(7201)
        ctl.on_output("✻ Cogitating… 1m 3s · ↓ 812 tokens", now=7210)
        ctl.tick(7211)
        self.assertEqual(ctl.state, cr.IDLE)


class TestWaitScale(unittest.TestCase):
    def test_scale_divides_the_wait(self):
        ctl = controller(wait_scale=3600)
        ctl.on_limit("resets in 2 hours", now=0, source="transcript")
        self.assertAlmostEqual(ctl.wake_at, 2.0, delta=0.01)


if __name__ == "__main__":
    unittest.main(verbosity=2)
