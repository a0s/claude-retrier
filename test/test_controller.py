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
           draft_grace=600, resume=15, typing_max=900)

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


class TestAScrapedWaitCanBeTalkedOutOfIt(unittest.TestCase):
    """A wait the screen scheduled stays open to the screen.

    A scraped banner is the one kind that can belong to somebody else — a card on
    the agent roster, a line of history behind one — and until now the wait it
    scheduled was unfixable: the screen channel closes the moment the controller
    leaves IDLE, and a roster has no transcript of its own to correct it from.
    A neighbour's "resets 2:10am" parked a terminal for 11h18m over a limit that
    lifted in seven minutes, and killing the process was the only way out.
    """

    def test_the_screen_may_still_be_read_during_a_scraped_wait(self):
        ctl = controller()
        ctl.on_limit("resets in 10 hours", now=0, source="screen")
        self.assertTrue(ctl.rescrapable())

    def test_a_transcript_wait_is_not_second_guessed(self):
        # The transcript reports this session's own limit; there is nothing on
        # screen worth weighing against it.
        ctl = controller()
        ctl.on_limit("resets in 10 hours", now=0, source="transcript")
        self.assertFalse(ctl.rescrapable())

    def test_a_stall_is_not_re_read_that_way(self):
        ctl = controller(stall_wait=60, stall_backoff=2, stall_max_wait=600,
                         stall_max_attempts=5)
        ctl.on_stall("Selected model is at capacity", now=0, source="screen")
        self.assertEqual(ctl.state, cr.WAITING)
        self.assertFalse(ctl.rescrapable())

    def test_an_earlier_reset_on_screen_shortens_the_wait(self):
        ctl = controller()
        ctl.on_limit("resets in 10 hours", now=0, source="screen")
        self.assertTrue(ctl.on_limit("resets in 1 hours", now=100, source="screen"))
        self.assertAlmostEqual(ctl.wake_at, 3700, delta=1)

    def test_a_later_one_cannot_extend_it(self):
        # The stale-banner direction: another card, read a moment later, must
        # not push the wake-up further out — that is how eleven hours happened.
        ctl = controller()
        ctl.on_limit("resets in 1 hours", now=0, source="screen")
        self.assertFalse(ctl.on_limit("resets in 10 hours", now=100, source="screen"))
        self.assertAlmostEqual(ctl.wake_at, 3600, delta=1)

    def test_a_banner_turned_down_once_is_not_re_read_forever(self):
        # The screen keeps the card on it, so the same text arrives every few
        # seconds for as long as the wait runs.
        ctl = controller()
        ctl.on_limit("resets in 1 hours", now=0, source="screen")
        ctl.on_limit("resets in 10 hours", now=100, source="screen")
        before = len(ctl.log_lines)
        for t in range(103, 130, 3):
            self.assertFalse(ctl.on_limit("resets in 10 hours", now=t, source="screen"))
        self.assertEqual(len(ctl.log_lines), before)

    def test_the_transcript_still_outranks_the_screen(self):
        # Whatever the screen said, a limit this session actually hit replaces it.
        ctl = controller()
        ctl.on_limit("resets in 1 hours", now=0, source="screen")
        self.assertTrue(ctl.on_limit("resets in 10 hours", now=100, source="transcript"))
        self.assertAlmostEqual(ctl.wake_at, 36100, delta=1)
        self.assertFalse(ctl.rescrapable())

    def test_the_slate_is_clean_after_the_wait_ends(self):
        ctl = controller()
        ctl.on_limit("resets in 1 hours", now=0, source="screen")
        ctl.on_limit("resets in 10 hours", now=10, source="screen")   # turned down
        ctl.on_output("esc to interrupt", 100)
        ctl.on_output("esc to interrupt", 120)
        self.assertTrue(ctl.on_alive(200, "output"))
        self.assertEqual(ctl.state, cr.IDLE)
        self.assertFalse(ctl.rescrapable())
        self.assertTrue(ctl.on_limit("resets in 10 hours", now=300, source="screen"))


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


class TestTheLimitCanEndWithoutTheReset(unittest.TestCase):
    """Field failure: a weekly limit was detected, the human logged into another
    account and worked for an hour — and the wrapper sat there counting down its
    48 hours, ready to type "continue" into the middle of that work.

    Nothing announces "your quota is back": not the transcript, not the render.
    The evidence is that claude is answering, which is exactly what the wait was
    waiting to find out.
    """
    def waiting(self, **over):
        ctl = controller(**over)
        ctl.on_limit("You've hit your weekly limit · resets in 48 hours", now=1000,
                     source="transcript")
        return ctl

    def working(self, ctl, start, seconds, step=2):
        for t in range(int(start), int(start + seconds) + 1, step):
            ctl.on_output("✻ Cogitating… (esc to interrupt)", now=t)
        return start + seconds

    def test_a_long_working_spell_cancels_the_wait(self):
        ctl = self.waiting()
        end = self.working(ctl, 1100, 20)
        self.assertEqual(ctl.tick(end), ("resume",))
        self.assertEqual(ctl.state, cr.IDLE)
        self.assertEqual(ctl.wake_at, 0.0)

    def test_a_flicker_of_footer_does_not(self):
        # A refused turn still paints a spinner for a second or two before the
        # banner lands. Acting on that would drop every wait the moment the human
        # tried again.
        ctl = self.waiting()
        end = self.working(ctl, 1100, 4)
        self.assertIsNone(ctl.tick(end))
        self.assertEqual(ctl.state, cr.WAITING)

    def test_a_spell_that_began_before_the_limit_does_not_count(self):
        # The footer was already running when the limit arrived — that spell is
        # the turn that got refused, not proof of a new one.
        ctl = controller()
        end = self.working(ctl, 1000, 30)
        ctl.on_limit("resets in 48 hours", now=end, source="screen")
        self.working(ctl, end, 4)
        self.assertIsNone(ctl.tick(end + 4))
        self.assertEqual(ctl.state, cr.WAITING)

    def test_a_spell_that_has_since_ended_does_not_count(self):
        ctl = self.waiting()
        end = self.working(ctl, 1100, 30)
        self.assertIsNone(ctl.tick(end + 60))       # quiet again for a minute
        self.assertEqual(ctl.state, cr.WAITING)

    def test_two_short_spells_do_not_add_up(self):
        ctl = self.waiting()
        end = self.working(ctl, 1100, 8)
        self.assertIsNone(ctl.tick(end))
        end = self.working(ctl, end + 30, 8)
        self.assertIsNone(ctl.tick(end))
        self.assertEqual(ctl.state, cr.WAITING)

    def test_an_answered_turn_in_the_transcript_cancels_the_wait(self):
        ctl = self.waiting()
        self.assertTrue(ctl.on_alive(now=1100, source="transcript"))
        self.assertEqual(ctl.state, cr.IDLE)
        self.assertIsNone(ctl.tick(1e9 + 1))        # and stays cancelled

    def test_rows_written_just_before_the_banner_are_not_evidence(self):
        # The transcript is polled, so the answer that ran out of quota can reach
        # us a moment after the limit row that followed it.
        ctl = self.waiting()
        self.assertFalse(ctl.on_alive(now=1001, source="transcript"))
        self.assertEqual(ctl.state, cr.WAITING)

    def test_an_idle_session_is_not_cancelled_by_anything(self):
        ctl = controller()
        self.assertFalse(ctl.on_alive(now=1000, source="transcript"))
        self.assertEqual(ctl.state, cr.IDLE)

    def test_a_cancelled_wait_can_be_scheduled_again(self):
        # The new quota runs out too. Nothing about the first incident may block
        # the second: same banner text, hours apart.
        ctl = self.waiting()
        ctl.on_alive(now=2000, source="transcript")
        self.assertTrue(ctl.on_limit("You've hit your weekly limit · resets in 48 hours",
                                     now=3000, source="transcript"))
        self.assertEqual(ctl.state, cr.WAITING)

    def test_a_verify_in_progress_is_cancelled_too(self):
        ctl = self.waiting()
        self.assertEqual(ctl.tick(1000 + 48 * 3600 + 1)[0], "inject")
        self.assertEqual(ctl.state, cr.VERIFY)
        self.assertTrue(ctl.on_alive(now=1000 + 48 * 3600 + 30, source="transcript"))
        self.assertEqual(ctl.state, cr.IDLE)
        self.assertEqual(ctl.attempts, 0)


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


class TestPresenceIsNotTraffic(unittest.TestCase):
    """The other half of the same field failure. Swallowing the terminal's
    replies kept them out of the draft counter, but every one of them still
    stamped `last_user_input`, and that gate wants twenty quiet seconds. A
    session that had waited out a four-hour limit then logged "user is typing"
    every 15s while its owner sat watching the screen: switching to another app
    and back, moving the mouse over the window, anything that makes a terminal
    speak. Presence has to mean a key, not a byte.
    """
    def present_after(self, data):
        ctl = controller()
        ctl.on_user_bytes(data, now=500)
        return ctl.last_user_input == 500

    def test_a_cursor_position_report_is_not_presence(self):
        self.assertFalse(self.present_after(b"\x1b[12;40R"))

    def test_a_device_attributes_reply_is_not_presence(self):
        self.assertFalse(self.present_after(b"\x1b[?1;2c"))

    def test_an_xtversion_reply_is_not_presence(self):
        self.assertFalse(self.present_after(b"\x1bP>|iTerm2 3.5.11\x1b\\"))

    def test_an_osc_colour_reply_is_not_presence(self):
        self.assertFalse(self.present_after(b"\x1b]11;rgb:1e1e/1e1e/1e1e\x07"))

    def test_focus_events_are_not_presence(self):
        # Switching to another window and back — which is what taking a
        # screenshot of the stuck session looks like from down here.
        self.assertFalse(self.present_after(b"\x1b[O"))
        self.assertFalse(self.present_after(b"\x1b[I"))

    def test_mouse_traffic_is_not_presence(self):
        self.assertFalse(self.present_after(b"\x1b[<35;36;12M"))
        self.assertFalse(self.present_after(b"\x1b[M\x20\x40\x30"))

    def test_a_window_size_report_is_not_presence(self):
        self.assertFalse(self.present_after(b"\x1b[8;40;120t"))

    def test_a_device_status_report_is_not_presence(self):
        self.assertFalse(self.present_after(b"\x1b[0n"))

    def test_a_kitty_keyboard_flags_report_is_not_presence(self):
        self.assertFalse(self.present_after(b"\x1b[?3u"))

    def test_a_key_is_presence_even_when_it_is_an_escape_sequence(self):
        for key in (b"\x1b[A", b"\x1b[1;5C", b"\x1bOP", b"\x1b[3~", b"\x1bb"):
            self.assertTrue(self.present_after(key), key)

    def test_a_lone_escape_is_presence(self):
        self.assertTrue(self.present_after(b"\x1b"))

    def test_ordinary_typing_is_presence(self):
        self.assertTrue(self.present_after(b"hello"))
        self.assertTrue(self.present_after(b"\r"))

    def test_a_reply_riding_along_with_a_keystroke_still_counts(self):
        self.assertTrue(self.present_after(b"\x1b[12;40Rx"))

    def test_the_retry_goes_out_over_a_chattering_terminal(self):
        # The failure end to end: the reset has passed and the only thing on
        # stdin is the terminal answering claude. Nothing may defer this.
        ctl = controller()
        ctl.on_limit(BANNER, now=0, source="transcript")
        for t in range(7100, 7220, 5):
            ctl.on_user_bytes(b"\x1b[24;80R\x1b[I", now=t)
        self.assertIsNotNone(ctl.tick(7220))
        self.assertFalse(any("deferring" in line for line in ctl.log_lines))


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

    def test_the_keyboard_gate_has_a_ceiling(self):
        # Nothing is behind this one: the box is empty (a draft has its own
        # grace period), so it defers to a pair of hands and no more. Whatever
        # keeps stamping presence next — a key that repeats, a report we failed
        # to recognise — the retry still has to happen.
        ctl = controller()
        ctl.on_limit(BANNER, now=0, source="transcript")
        for t in range(7201, 7201 + 900, 15):
            ctl.on_user_bytes(b"\r", now=t)              # empty box, present
            self.assertIsNone(ctl.tick(t))
            self.assertTrue(ctl.deferred)
        ctl.on_user_bytes(b"\r", now=7201 + 900)
        self.assertIsNotNone(ctl.tick(7201 + 900))
        self.assertTrue(any("ceiling" in line or "held for" in line
                            for line in ctl.log_lines))

    def test_the_ceiling_does_not_type_over_a_draft(self):
        # Someone typing has an empty box between thoughts and a full one during
        # them, and only the empty case is safe to overrule. A message being
        # written for half an hour still waits.
        ctl = controller()
        ctl.on_limit(BANNER, now=0, source="transcript")
        for t in range(7201, 7201 + 3000, 15):
            ctl.on_user_bytes(b"y", now=t)               # the draft keeps growing
            self.assertIsNone(ctl.tick(t))

    def test_deferring_is_visible_and_clears(self):
        ctl = controller()
        ctl.on_limit(BANNER, now=0, source="transcript")
        ctl.on_user_bytes(b"hi\r", now=7200)
        self.assertIsNone(ctl.tick(7201))
        self.assertTrue(ctl.deferred)
        self.assertIsNotNone(ctl.tick(7300))             # nobody there any more
        self.assertFalse(ctl.deferred)


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


# --------------------------------------------------------------------------- #
# the context restart
# --------------------------------------------------------------------------- #
# Settings for a controller with the feature on, small enough to drive by hand:
# a 1M window, a threshold at half of it, and a handoff of a couple of lines.
CTX = dict(
    context_pct=50, context_tokens=0, context_window="1M",
    context_env_max=0, context_no_1m=False,
    handoff_file="H.md", handoff_marker="HANDOFF", handoff_min_bytes=20,
    handoff_attempts=2,
    handoff_msg="Fold into `{file}` and end it with {marker}.",
    clear_cmd="/clear", resume_msg="Read `{file}` and continue from it.",
    root_idle=20, handoff_timeout=900, step_gap=3,
    context_cooldown=600, context_max_cycles=0,
)

MINE = "/proj/mine.jsonl"          # the transcript this terminal's session writes
FULL = 700000                      # past the 500k threshold
RESUME = "Read `H.md` and continue from it."


class Handoff:
    """The file the model was asked to write, as the controller can see it.

    The controller reads it through an injected probe precisely so that a test
    can hand it a file that was never written, one that stops halfway, or one
    still carrying the marker from a previous attempt.
    """

    def __init__(self):
        self.state = None

    def write(self, ctl, at, body=None, marker=True, size=None):
        text = body if body is not None else "everything you need to know\n" * 4
        if marker:
            text += ctl.nonce + "\n"
        self.state = dict(size=len(text.encode()) if size is None else size,
                          mtime=at, tail=text[-512:])

    def touch(self, at):
        self.state["mtime"] = at

    def __call__(self, _path):
        return self.state


def restart_controller(**over):
    cfg = dict(CFG)
    cfg.update(CTX)
    cfg.update(over)
    logs = []
    hand = Handoff()
    ctl = cr.Controller(cfg, logs.append, now=0, probe=hand)
    ctl.log_lines = logs
    ctl.handoff = hand
    return ctl


def usage(ctl, at, tokens, model="claude-opus-5", stop="end_turn", path=MINE,
          sidechain=False):
    """One assistant row, the way the watcher hands them over."""
    ctl.on_context(dict(kind="alive", path=path, tokens=tokens, model=model,
                        stop_reason=stop, sidechain=sidechain), at)


class RestartTestCase(unittest.TestCase):
    """Every action the controller returns is recorded, because half of what is
    being asserted here is what it did NOT do — and `/clear` is the one action
    that cannot be taken back."""

    def setUp(self):
        self.acts = []

    def tick(self, ctl, t):
        action = ctl.tick(t)
        if action:
            self.acts.append(action)
        return action

    def injected(self):
        return [a[1] for a in self.acts if a[0] == "inject"]

    def assertNeverCleared(self):
        self.assertNotIn("/clear", self.injected())

    # -- the machine, one step at a time ------------------------------------ #
    def fold(self, ctl, tokens=FULL, at=0, tick_at=30):
        """From "the context is full" to the folding phrase going out."""
        usage(ctl, at, tokens)
        return self.tick(ctl, tick_at)

    def folded(self, ctl, written_at=40):
        """...and the model writes the file and finishes its turn."""
        ctl.handoff.write(ctl, at=written_at)
        usage(ctl, written_at, FULL)

    def cleared(self, ctl):
        """...through the verification and out the other side of /clear."""
        self.fold(ctl)
        self.folded(ctl)
        self.tick(ctl, 65)
        return ctl

    def unfolding(self, ctl):
        """...and the resume phrase sent."""
        self.cleared(ctl)
        self.tick(ctl, 69)
        return ctl


class TestTheHappyPath(RestartTestCase):
    def test_full_context_becomes_a_fresh_session(self):
        ctl = restart_controller()
        action = self.fold(ctl)
        self.assertEqual(action[0], "inject")
        self.assertIn("H.md", action[1])
        self.assertIn(ctl.nonce, action[1])
        self.assertEqual(ctl.rstate, cr.HANDOFF_SENT)

        self.folded(ctl)
        self.assertIsNone(self.tick(ctl, 45))      # the transcript is still growing
        self.assertEqual(self.tick(ctl, 65), ("inject", "/clear", False))
        self.assertEqual(ctl.rstate, cr.CLEARED)

        self.assertIsNone(self.tick(ctl, 66))      # the gap between the two
        self.assertEqual(self.tick(ctl, 69), ("inject", RESUME, False))
        self.assertEqual(ctl.rstate, cr.RESUME_SENT)

        # The new session answers, and it answers small.
        usage(ctl, 72, 8000, path="/proj/after.jsonl")
        action = self.tick(ctl, 73)
        self.assertEqual(action[0], "notify")
        self.assertIn("restarted", action[1])
        self.assertIsNone(ctl.rstate)

    def test_the_marker_is_different_every_time(self):
        first = restart_controller()
        self.fold(first)
        second = restart_controller()
        self.fold(second)
        self.assertNotEqual(first.nonce, second.nonce)
        self.assertTrue(first.nonce.startswith("HANDOFF-"))

    def test_a_restart_is_followed_by_silence(self):
        ctl = restart_controller()
        self.unfolding(ctl)
        usage(ctl, 72, 8000, path="/proj/after.jsonl")
        self.tick(ctl, 73)
        usage(ctl, 100, FULL, path=MINE)           # full again straight away
        self.assertIsNone(self.tick(ctl, 200))     # inside the cooldown
        self.assertIsNotNone(self.tick(ctl, 700))

    def test_the_fuse_caps_how_many_a_session_gets(self):
        ctl = restart_controller(context_max_cycles=1, context_cooldown=0)
        self.fold(ctl)
        usage(ctl, 40, FULL)                       # no file: attempt 2
        self.tick(ctl, 65)
        usage(ctl, 70, FULL)
        self.tick(ctl, 95)                         # ...and the abort
        self.assertEqual(ctl.cycles, 1)
        usage(ctl, 100, FULL)
        self.assertIsNone(self.tick(ctl, 200))


class TestNothingIsClearedOnAPromise(RestartTestCase):
    """The dangerous failure in the whole design: the fold was asked for, the
    model did not manage it, and the context is cleared anyway — which loses the
    session's work with nothing written down. The model reporting success is not
    evidence; it says only that the model believes it finished."""

    def failing(self, **over):
        ctl = restart_controller(**over)
        self.fold(ctl)
        return ctl

    def second_attempt_then_abort(self, ctl):
        """Both attempts end the same way; the second one is the abort."""
        usage(ctl, 70, FULL)
        return self.tick(ctl, 95)

    def test_a_file_that_was_never_written(self):
        ctl = self.failing()
        usage(ctl, 40, FULL)
        action = self.tick(ctl, 65)
        self.assertEqual(action[0], "inject")      # attempt 2, not /clear
        self.assertEqual(ctl.handoff_tries, 2)
        action = self.second_attempt_then_abort(ctl)
        self.assertEqual(action[0], "notify")
        self.assertIn("never written", action[1])
        self.assertNeverCleared()
        self.assertIsNone(ctl.rstate)

    def test_a_file_too_short_to_be_a_handoff(self):
        ctl = self.failing()
        ctl.handoff.write(ctl, at=40, body="", size=8)
        usage(ctl, 40, FULL)
        self.tick(ctl, 65)
        ctl.handoff.write(ctl, at=70, body="", size=8)
        action = self.second_attempt_then_abort(ctl)
        self.assertIn("byte floor", action[1])
        self.assertNeverCleared()

    def test_a_file_that_stops_before_the_marker(self):
        # The one failure the marker exists for: a write that ran out partway,
        # which looks exactly like a complete file from every other angle.
        ctl = self.failing()
        ctl.handoff.write(ctl, at=40, marker=False)
        usage(ctl, 40, FULL)
        self.tick(ctl, 65)
        ctl.handoff.write(ctl, at=70, marker=False)
        action = self.second_attempt_then_abort(ctl)
        self.assertIn("does not end with", action[1])
        self.assertNeverCleared()

    def test_a_file_older_than_the_request_for_it(self):
        ctl = self.failing()
        ctl.handoff.write(ctl, at=5)               # left over from before
        usage(ctl, 40, FULL)
        self.tick(ctl, 65)
        action = self.second_attempt_then_abort(ctl)
        self.assertIn("older than the request", action[1])
        self.assertNeverCleared()

    def test_a_turn_cut_off_at_max_tokens(self):
        # A perfect-looking file whose turn the runtime says was truncated. The
        # marker cannot have been written by a finished answer, whatever the
        # bytes say.
        ctl = self.failing()
        ctl.handoff.write(ctl, at=40)
        usage(ctl, 40, FULL, stop="max_tokens")
        self.tick(ctl, 65)
        ctl.handoff.write(ctl, at=70)
        usage(ctl, 70, FULL, stop="max_tokens")
        action = self.tick(ctl, 95)
        self.assertEqual(action[0], "notify")
        self.assertIn("max_tokens", action[1])
        self.assertNeverCleared()

    def test_a_turn_that_was_refused(self):
        ctl = self.failing()
        ctl.handoff.write(ctl, at=40)
        usage(ctl, 40, FULL, stop="refusal")
        self.tick(ctl, 65)
        ctl.handoff.write(ctl, at=70)
        usage(ctl, 70, FULL, stop="refusal")
        self.assertIn("refusal", self.tick(ctl, 95)[1])
        self.assertNeverCleared()

    def test_a_session_that_kept_working_is_waited_for_not_cleared(self):
        # The file is complete and the model ignored "do not start new work".
        # Clearing now would take the new work with it.
        ctl = self.failing()
        ctl.handoff.write(ctl, at=40)
        usage(ctl, 40, FULL)
        for t in range(45, 400, 10):
            ctl.note_growth([MINE], now=t)         # still writing
            self.assertIsNone(self.tick(ctl, t))
        self.assertEqual(ctl.rstate, cr.HANDOFF_SENT)
        self.assertNeverCleared()

    def test_a_turn_still_in_flight_is_not_a_failed_one(self):
        # Quiet transcript, no file yet, and the last row is a tool call: the
        # answer has not landed. Failing it here would burn an attempt on a
        # session that is doing exactly as it was asked.
        ctl = self.failing()
        usage(ctl, 40, FULL, stop="tool_use")
        self.assertIsNone(self.tick(ctl, 65))
        self.assertEqual(ctl.handoff_tries, 1)

    def test_the_marker_from_the_last_attempt_is_not_this_attempts_proof(self):
        # Without a fresh nonce, the file left behind by a rejected attempt
        # satisfies the next one — which turns "the write finished" into "a
        # write finished once", and those are not the same claim.
        ctl = self.failing()
        ctl.handoff.write(ctl, at=40)
        usage(ctl, 40, FULL, stop="max_tokens")
        first = ctl.nonce
        action = self.tick(ctl, 65)
        self.assertEqual(action[0], "inject")
        self.assertNotEqual(ctl.nonce, first)
        ctl.handoff.touch(70)                      # same bytes, same old marker
        usage(ctl, 70, FULL)
        self.assertIn("does not end with", self.tick(ctl, 95)[1])
        self.assertNeverCleared()

    def test_the_fold_gives_up_rather_than_asking_forever(self):
        ctl = restart_controller(handoff_attempts=3)
        self.fold(ctl)
        for t in (40, 70, 100):
            usage(ctl, t, FULL)
            self.tick(ctl, t + 25)
        self.assertEqual(ctl.handoff_tries, 3)
        self.assertEqual(len([a for a in self.acts if a[0] == "notify"]), 1)
        self.assertNeverCleared()

    def test_a_fold_nobody_answers_times_out(self):
        ctl = restart_controller(handoff_timeout=60)
        self.fold(ctl)
        usage(ctl, 40, FULL, stop="tool_use")      # a turn that never ends
        action = self.tick(ctl, 200)
        self.assertEqual(action[0], "notify")
        self.assertIn("no usable handoff", action[1])
        self.assertNeverCleared()


class TestTheClearHasToHaveWorked(RestartTestCase):
    """The other half: `/clear` went out and the context did not move. Retrying
    that forever would type into a session that stays exactly as full as it was,
    for as long as it lives."""

    def test_a_clear_that_did_nothing_switches_the_feature_off(self):
        ctl = restart_controller()
        self.unfolding(ctl)
        ctl.on_resume_echo(70)                     # the phrase was accepted...
        usage(ctl, 80, FULL, path=MINE)            # ...and the context is untouched
        action = self.tick(ctl, 130)
        self.assertEqual(action[0], "notify")
        self.assertIn("did not fall", action[1])
        self.assertTrue(ctl.context_off)
        usage(ctl, 200, FULL)
        self.assertIsNone(self.tick(ctl, 1000))    # and never tries again

    def test_the_reading_it_is_judged_against_is_the_one_it_acted_on(self):
        # A project directory can hold more than one live transcript, and the
        # one that grew last is only usually ours. Taking the "before" figure at
        # /clear time rather than at the trigger would mean judging the restart
        # against whichever session happened to speak in between — and against a
        # small enough number, a real restart reads as a failure and switches the
        # feature off for good.
        ctl = restart_controller()
        self.fold(ctl)
        self.folded(ctl)
        usage(ctl, 66, 9000, path="/proj/somebody-else.jsonl")
        self.assertEqual(self.tick(ctl, 90), ("inject", "/clear", False))
        self.assertEqual(ctl.context_before, FULL)

    def test_a_resume_that_never_lands_says_that_and_not_something_else(self):
        # Two failures end in the same place and read completely differently in
        # a log: a clear that did nothing, and a phrase that never arrived.
        ctl = restart_controller(handoff_attempts=1)
        self.unfolding(ctl)
        usage(ctl, 80, FULL, path=MINE)
        self.assertEqual(self.tick(ctl, 130), ("inject", RESUME, False))
        action = self.tick(ctl, 200)
        self.assertEqual(action[0], "notify")
        self.assertIn("never reached the session", action[1])
        self.assertTrue(ctl.context_off)

    def test_a_resume_that_left_no_trace_is_sent_again(self):
        ctl = restart_controller()
        self.unfolding(ctl)
        usage(ctl, 80, FULL, path=MINE)
        action = self.tick(ctl, 130)
        self.assertEqual(action, ("inject", RESUME, False))
        self.assertEqual(ctl.resume_tries, 1)

    def test_a_context_that_only_dipped_is_not_a_restart(self):
        ctl = restart_controller()
        self.unfolding(ctl)
        ctl.on_resume_echo(70)
        usage(ctl, 80, 600000, path="/proj/after.jsonl")   # 700k -> 600k: no
        self.assertEqual(self.tick(ctl, 130)[0], "notify")
        self.assertTrue(ctl.context_off)


class TestTheLimitOutranksTheContext(RestartTestCase):
    """A session that is out of quota is stopped either way, so there is nothing
    to fold into a file and no point typing at it. A limit that arrives DURING a
    restart is a different thing: it suspends it, never cancels it."""

    def test_a_limit_holds_a_restart_back(self):
        ctl = restart_controller()
        usage(ctl, 0, FULL)
        ctl.on_limit(BANNER, now=10, source="transcript")
        self.assertIsNone(self.tick(ctl, 30))
        self.assertIsNone(ctl.rstate)
        self.assertEqual(self.tick(ctl, 7300), ("inject", "continue", False))

    def test_and_the_restart_happens_once_the_limit_is_gone(self):
        ctl = restart_controller()
        usage(ctl, 0, FULL)
        ctl.on_limit(BANNER, now=10, source="transcript")
        self.tick(ctl, 7300)
        ctl.on_echo(now=7302)                      # the retry was accepted
        action = self.tick(ctl, 7400)
        self.assertEqual(action[0], "inject")
        self.assertIn("H.md", action[1])

    def test_a_fold_interrupted_by_a_limit_is_re_sent_whole(self):
        # `continue` would be wrong here: the phrase rewrites the file from
        # scratch, so what a half-written handoff needs is the phrase again.
        ctl = restart_controller()
        self.fold(ctl)
        first = ctl.nonce
        ctl.on_limit("resets in 1 hours", now=40, source="transcript")
        self.assertIsNone(self.tick(ctl, 100))     # frozen for the duration
        action = self.tick(ctl, 40 + 3601)
        self.assertEqual(action[0], "inject")
        self.assertIn("H.md", action[1])
        self.assertNotEqual(ctl.nonce, first)
        self.assertEqual(ctl.rstate, cr.HANDOFF_SENT)
        self.assertEqual(ctl.state, cr.IDLE)

    def test_a_limit_does_not_spend_a_fold_attempt(self):
        # The attempt counter is for a model that will not fold, not for the
        # world getting in the way. Two limits in a row must not exhaust it.
        ctl = restart_controller()
        self.fold(ctl)
        for at in (40, 4000):
            ctl.on_limit("resets in 1 hours", now=at, source="transcript")
            self.tick(ctl, at + 3601)
        self.assertEqual(ctl.handoff_tries, 1)
        self.assertEqual(ctl.rstate, cr.HANDOFF_SENT)

    def test_the_fold_timeout_does_not_run_while_a_limit_does(self):
        # A weekly limit is days long; a fifteen-minute fold timeout inside one
        # would abort a restart that is going perfectly well.
        ctl = restart_controller(handoff_timeout=60)
        self.fold(ctl)
        ctl.on_limit("resets in 40 hours", now=35, source="transcript")
        for t in range(100, 40 * 3600, 1800):
            self.assertIsNone(self.tick(ctl, t))
        self.assertEqual(ctl.rstate, cr.HANDOFF_SENT)

    def test_a_verified_handoff_survives_a_limit_and_still_clears(self):
        ctl = restart_controller()
        self.fold(ctl)
        self.folded(ctl)
        ctl.on_user_bytes(b"typing", now=64)       # a draft holds the clear back
        self.assertIsNone(self.tick(ctl, 65))
        self.assertEqual(ctl.rstate, cr.HANDOFF_OK)
        ctl.on_limit("resets in 1 hours", now=66, source="transcript")
        self.assertEqual(self.tick(ctl, 66 + 3601), ("inject", "/clear", False))

    def test_a_limit_between_the_clear_and_the_resume_sends_the_resume(self):
        ctl = restart_controller()
        self.cleared(ctl)
        ctl.on_limit("resets in 1 hours", now=66, source="transcript")
        self.assertEqual(self.tick(ctl, 66 + 3601), ("inject", RESUME, False))
        self.assertEqual(ctl.rstate, cr.RESUME_SENT)

    def test_a_resume_that_never_landed_is_sent_again(self):
        ctl = restart_controller()
        self.unfolding(ctl)
        ctl.on_limit("resets in 1 hours", now=70, source="transcript")
        action = self.tick(ctl, 70 + 3601)
        self.assertEqual(action, ("inject", RESUME, False))

    def test_a_resume_that_had_landed_falls_back_to_continue(self):
        # The one position in the machine where "carry on with what you were
        # doing" is exactly the right instruction.
        ctl = restart_controller()
        self.unfolding(ctl)
        ctl.on_resume_echo(70)
        ctl.on_limit("resets in 1 hours", now=71, source="transcript")
        self.assertEqual(self.tick(ctl, 71 + 3601), ("inject", "continue", False))
        self.assertIsNone(ctl.rstate)

    def test_a_wait_that_ends_early_resumes_the_restart_too(self):
        # The quota can come back without the reset it announced, and the only
        # sign is the session answering. The restart still has to go on.
        ctl = restart_controller()
        self.cleared(ctl)
        ctl.on_limit("resets in 40 hours", now=66, source="transcript")
        self.assertTrue(ctl.on_alive(now=200, source="transcript"))
        self.assertEqual(self.tick(ctl, 201), ("inject", RESUME, False))


class TestWhoIsAllowedToBeInterrupted(RestartTestCase):
    def test_it_does_not_fold_over_someone_typing(self):
        ctl = restart_controller()
        usage(ctl, 0, FULL)
        ctl.on_user_bytes(b"mid-thought", now=25)
        self.assertIsNone(self.tick(ctl, 30))
        self.assertIsNone(ctl.rstate)
        ctl.on_user_bytes(b"\r", now=26)                   # they send it themselves
        self.assertIsNotNone(self.tick(ctl, 60))

    def test_it_does_not_fold_into_a_running_turn(self):
        ctl = restart_controller()
        usage(ctl, 0, FULL)
        ctl.note_growth([MINE], now=25)
        self.assertIsNone(self.tick(ctl, 30))
        self.assertIsNotNone(self.tick(ctl, 50))

    def test_another_sessions_transcript_holds_nothing_back(self):
        # Work running in the background under the same cwd writes its own
        # transcript. It is not this session's turn and must not gate it.
        ctl = restart_controller()
        usage(ctl, 0, FULL)
        ctl.note_growth(["/proj/somebody-else.jsonl"], now=29)
        self.assertIsNotNone(self.tick(ctl, 30))

    def test_a_busy_screen_holds_nothing_back(self):
        # In a session that keeps background work going, something is always
        # painting a footer. Waiting for the screen to go quiet would mean
        # waiting for ever, so the restart asks the transcript instead.
        ctl = restart_controller()
        usage(ctl, 0, FULL)
        for t in range(0, 31, 2):
            ctl.on_output("✻ Cogitating… 4m 12s · ↓ 8.1k tokens", now=t)
        self.assertIsNotNone(self.tick(ctl, 30))


class TestWhatCountsAsContext(RestartTestCase):
    def test_the_feature_is_off_unless_it_is_asked_for(self):
        ctl = restart_controller(context_pct=0, context_tokens=0)
        usage(ctl, 0, 999999)
        self.assertFalse(ctl.context_enabled)
        self.assertIsNone(self.tick(ctl, 100))

    def test_below_the_threshold_nothing_happens(self):
        ctl = restart_controller()
        usage(ctl, 0, 400000)
        self.assertIsNone(self.tick(ctl, 100))

    def test_a_subagents_context_is_not_the_sessions(self):
        # A subagent writes into the same transcript, and its usage is its own.
        ctl = restart_controller()
        usage(ctl, 0, 100000)
        usage(ctl, 5, 900000, sidechain=True)
        self.assertEqual(ctl.context_tokens, 100000)
        self.assertIsNone(self.tick(ctl, 60))

    def test_a_subagent_still_counts_as_the_session_working(self):
        ctl = restart_controller()
        usage(ctl, 0, FULL)
        usage(ctl, 25, 40000, sidechain=True)
        self.assertIsNone(self.tick(ctl, 30))      # the session is not idle
        self.assertIsNotNone(self.tick(ctl, 50))

    def test_the_model_decides_the_denominator(self):
        ctl = restart_controller(context_window="auto")
        usage(ctl, 0, 10, model="claude-opus-5")
        self.assertEqual(ctl.context_window, 1000000)
        self.assertEqual(ctl.context_limit, 500000)

    def test_a_short_window_model_triggers_sooner(self):
        ctl = restart_controller(context_window="auto")
        usage(ctl, 0, 10, model="claude-sonnet-4-5")
        self.assertEqual(ctl.context_limit, 100000)

    def test_an_unfamiliar_model_is_not_guessed_at(self):
        # Assuming the small window is what folded a 1M session at 12% full:
        # 118k of a 1M window read as 59% of a 200k one. An unfamiliar slug is
        # almost always a new — which is to say large — model, so nothing is
        # assumed and the percentage trigger simply does not arm.
        ctl = restart_controller(context_window="auto")
        usage(ctl, 0, 10, model="claude-something-9")
        self.assertIsNone(ctl.context_window)
        self.assertIsNone(ctl.context_limit)
        self.assertEqual(ctl.window_unknown, "claude-something-9")

    def test_a_point_release_is_its_familys_window(self):
        # The actual bug: claude-fable-5-1 is a 1M model, the table knew only
        # claude-fable-5, and the difference was a session cleared for nothing.
        ctl = restart_controller(context_window="auto")
        usage(ctl, 0, 10, model="claude-fable-5-1")
        self.assertEqual(ctl.context_window, 1000000)
        self.assertEqual(ctl.context_limit, 500000)
        self.assertIsNone(ctl.window_unknown)

    def test_an_unknown_window_never_folds_however_full_it_looks(self):
        ctl = restart_controller(context_window="auto")
        usage(ctl, 0, 900000, model="claude-something-9")
        self.assertIsNone(self.tick(ctl, 60))
        self.assertEqual(ctl.badge_warn(), "window?")

    def test_the_lookup_answer_arms_the_trigger(self):
        ctl = restart_controller(context_window="auto")
        usage(ctl, 0, 600000, model="claude-something-9")
        self.assertIsNone(self.tick(ctl, 60))
        self.assertTrue(ctl.on_window_learned("claude-something-9", 1000000,
                                              "the models docs"))
        self.assertEqual(ctl.context_limit, 500000)
        self.assertIsNone(ctl.window_unknown)
        self.assertIsNone(ctl.badge_warn())
        self.assertIsNotNone(self.tick(ctl, 120))      # 600k is past 500k

    def test_an_answer_about_another_model_is_kept_but_not_applied(self):
        # A lookup takes seconds and a session can change model inside them.
        ctl = restart_controller(context_window="auto")
        usage(ctl, 0, 10, model="claude-something-9")
        self.assertFalse(ctl.on_window_learned("claude-other-9", 300000, "docs"))
        self.assertIsNone(ctl.context_window)
        usage(ctl, 5, 10, model="claude-other-9")
        self.assertEqual(ctl.context_window, 300000)

    def test_an_absolute_threshold_needs_no_window_at_all(self):
        ctl = restart_controller(context_window="auto", context_pct=0,
                                 context_tokens=50000)
        usage(ctl, 0, 60000, model="claude-something-9")
        self.assertIsNone(ctl.window_unknown)
        self.assertIsNone(ctl.badge_warn())
        self.assertIsNotNone(self.tick(ctl, 60))

    def test_an_explicit_window_wins(self):
        ctl = restart_controller(context_window="300k")
        usage(ctl, 0, 10, model="claude-opus-5")
        self.assertEqual(ctl.context_window, 300000)

    def test_claude_codes_own_switch_narrows_it(self):
        ctl = restart_controller(context_window="auto", context_no_1m=True)
        usage(ctl, 0, 10, model="claude-opus-5")
        self.assertEqual(ctl.context_window, 200000)

    def test_claude_codes_own_ceiling_is_honoured(self):
        ctl = restart_controller(context_window="auto", context_env_max=150000)
        usage(ctl, 0, 10, model="claude-opus-5")
        self.assertEqual(ctl.context_window, 150000)

    def test_a_window_proved_too_small_is_raised(self):
        # The table can be right about the model and wrong about this session:
        # a 200k model served with a longer window still writes 200k's slug.
        ctl = restart_controller(context_window="auto")
        usage(ctl, 0, 10, model="claude-opus-4-5")
        self.assertEqual(ctl.context_window, 200000)
        usage(ctl, 5, 260000, model="claude-opus-4-5")
        self.assertEqual(ctl.context_window, 1000000)
        self.assertEqual(ctl.context_limit, 500000)

    def test_an_explicit_window_is_not_second_guessed(self):
        ctl = restart_controller(context_window="200k")
        usage(ctl, 0, 260000, model="claude-opus-5")
        self.assertEqual(ctl.context_window, 200000)

    def test_an_absolute_threshold_ignores_the_window_entirely(self):
        ctl = restart_controller(context_pct=0, context_tokens=123456)
        usage(ctl, 0, 10, model="claude-opus-5")
        self.assertTrue(ctl.context_enabled)
        self.assertEqual(ctl.context_limit, 123456)

    def test_the_session_moving_to_a_new_transcript_replaces_the_reading(self):
        ctl = restart_controller()
        usage(ctl, 0, FULL, path=MINE)
        usage(ctl, 1, 9000, path="/proj/after.jsonl")
        self.assertEqual(ctl.context_tokens, 9000)


class TestSettingsAsPeopleWriteThem(unittest.TestCase):
    """The thresholds are typed by hand into a shell, and a value that fails to
    parse falls back on the default — which for this feature is "off". Silently
    off is the one outcome nobody would ever notice."""

    def test_an_absolute_threshold_may_be_written_the_short_way(self):
        from helper import load as reload_impl
        for written, want in (("500k", 500000), ("1M", 1000000), ("450000", 450000)):
            mod = reload_impl(CR_CONTEXT_TOKENS=written)
            self.assertEqual(mod.CFG["context_tokens"], want, written)

    def test_nonsense_is_not_a_threshold(self):
        from helper import load as reload_impl
        self.assertEqual(reload_impl(CR_CONTEXT_TOKENS="lots").CFG["context_tokens"], 0)


class TestWhatTheCornerSays(RestartTestCase):
    def test_nothing_until_the_threshold_is_in_sight(self):
        ctl = restart_controller()
        usage(ctl, 0, 100000)
        self.assertIsNone(ctl.badge_context())

    def test_the_percentage_once_it_is(self):
        ctl = restart_controller()
        usage(ctl, 0, 450000)                      # 90% of the way to 500k
        self.assertAlmostEqual(ctl.badge_context(), 45.0, delta=0.1)

    def test_nothing_at_all_when_the_feature_is_off(self):
        ctl = restart_controller(context_pct=0, context_tokens=0)
        usage(ctl, 0, 999999)
        self.assertIsNone(ctl.badge_context())

    def test_the_restart_names_the_step_it_is_on(self):
        badge = cr.Badge(dict(badge=1, badge_pos="bottom-right", badge_label="cr"))
        text, _ = badge.frame(cr.IDLE, 0, 0, 3, now=0, restart=cr.HANDOFF_SENT)
        self.assertIn("folding", text)
        text, _ = badge.frame(cr.IDLE, 0, 0, 3, now=0, context=47.0)
        self.assertIn("47%", text)

    def test_a_wait_still_outranks_it_on_screen(self):
        badge = cr.Badge(dict(badge=1, badge_pos="bottom-right", badge_label="cr"))
        text, _ = badge.frame(cr.WAITING, 3600, 0, 3, now=0, restart=cr.HANDOFF_SENT)
        self.assertIn("1h00m", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
