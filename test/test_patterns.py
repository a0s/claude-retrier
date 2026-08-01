"""Detection: which renders are a live usage limit, and which only look like one.

The positive cases include every banner wording recovered from real transcripts
on this machine; the negative cases are the false positives that upstream
claude-auto-retry shipped and then had to fix (issues #63, #15, #38, #19).
"""
import unittest

from helper import load

cw = load()


LIVE_BANNERS = [
    # --- verbatim from ~/.claude/projects transcripts ---
    "You've hit your session limit · resets 3:20am (Europe/Warsaw)",
    "You've hit your session limit · resets 1:30pm (Europe/Warsaw)",
    "You've hit your session limit · resets 9pm (Europe/Warsaw)",
    "You've hit your weekly limit · resets 4pm (Europe/Warsaw)",
    "You've hit your weekly limit · resets Jul 22 at 6am (Europe/Warsaw)",
    # --- wordings reported in upstream issues ---
    "You've hit your limit · resets 4am (America/Buenos_Aires)",
    "You've hit your session limit · resets 4:50pm (Asia/Shanghai)",
    "⎿  You've hit your limit · resets 4am (America/Buenos_Aires)",
    "Claude usage limit reached. Resets at 2pm",
    "5-hour limit reached · resets 3pm (UTC)",
    # --- plausible variants the pattern table is meant to absorb ---
    "You have reached your daily limit. Try again in 3 hours.",
    "Usage limit reached — available again at 18:00 (UTC)",
    "Rate limit exceeded. Retry-After: 3600",
    "You've exceeded your monthly limit, resets on Aug 1",
    "Too many requests. try again in 15 minutes",
    "quota exceeded · resets tomorrow at 9am",
]

# A two-line render: the banner and its reset time arrive on separate rows.
MULTILINE = """\
⚠ You've hit your session limit
· resets 3pm (UTC)
"""

# The banner pushed far up the pane by a task widget — upstream #38, where a
# fixed 12-line tail window scrolled right past it.
BURIED = "You've hit your session limit · resets 4:40pm (UTC)\n" + "\n".join(
    "  ☐ task item %d" % i for i in range(90))

NOT_LIMITS = [
    # #63: banner text quoted inside a tool call is text ABOUT a limit.
    '● Bash(grep -c "5-hour limit reached - resets 3pm (UTC)" ~/logs/x.log)\n  ⎿  3',
    '⏺ Read(notes.md)\n  ⎿  You\'ve hit your session limit · resets 3pm (UTC)',
    # The API-429 render, which explicitly is NOT a usage limit.
    "API Error: Server is temporarily limiting requests (not your usage limit) · Rate limited",
    # The soft warning, which does not stop the session.
    "Approaching your session limit · resets 3pm (UTC)",
    # A limit line with no reset time: prose, not a banner.
    "You've hit your session limit before, so I added a retry.",
    "Let me explain how the usage limit works in Claude Code.",
    # A reset time with no limit line.
    "The cache resets at 3pm every day.",
    # This tool's own source and docs.
    "CW_LIMIT_PATTERNS=( \"you've hit your session limit\" ) # resets 3pm",
]


class TestBannerDetection(unittest.TestCase):
    def test_live_banners_detected(self):
        for text in LIVE_BANNERS:
            with self.subTest(text=text):
                self.assertIsNotNone(cw.find_limit(text))

    def test_multiline_render(self):
        found = cw.find_limit(MULTILINE)
        self.assertIsNotNone(found)
        self.assertIn("resets 3pm", found)

    def test_banner_buried_under_a_tall_widget(self):
        # No fixed tail window here: the whole rolling buffer is searched, so the
        # distance between the banner and the bottom of the screen is irrelevant.
        self.assertIsNotNone(cw.find_limit(BURIED))

    def test_non_limits_rejected(self):
        for text in NOT_LIMITS:
            with self.subTest(text=text):
                self.assertIsNone(cw.find_limit(text))

    def test_freshest_banner_wins(self):
        pane = ("You've hit your session limit · resets 11:30am (UTC)\n"
                "...work...\n"
                "You've hit your session limit · resets 4:30pm (UTC)\n")
        self.assertIn("4:30pm", cw.find_limit(pane))

    def test_ansi_is_stripped_before_matching(self):
        colored = "\x1b[1m\x1b[31mYou've hit your session limit\x1b[0m \x1b[2m· resets 3pm (UTC)\x1b[0m"
        self.assertIsNotNone(cw.find_limit(colored))

    def test_osc_hyperlink_does_not_break_matching(self):
        text = "You've hit your session limit \x1b]8;;https://claude.ai/upgrade\x1b\\· resets 3pm\x1b]8;;\x1b\\"
        self.assertIsNotNone(cw.find_limit(text))


class TestWorkingDetection(unittest.TestCase):
    def test_streaming_footer_is_working(self):
        for text in ["✻ Cogitating… (esc to interrupt)",
                     "· Retrying in 5s · attempt 3/10",
                     "Waiting for 2 background agents to finish"]:
            with self.subTest(text=text):
                self.assertTrue(cw.is_working(text))

    def test_idle_prompt_is_not_working(self):
        for text in ["╭────╮\n│ >  │\n╰────╯", "⏵⏵ auto mode on", ""]:
            with self.subTest(text=text):
                self.assertFalse(cw.is_working(text))


class TestMenuDetection(unittest.TestCase):
    def test_rate_limit_options_menu(self):
        menu = ("What do you want to do?\n"
                "❯ 1. Upgrade your plan\n"
                "  2. Stop and wait for limit to reset\n")
        self.assertTrue(cw.is_menu(menu))

    def test_ordinary_prompt_is_not_a_menu(self):
        self.assertFalse(cw.is_menu("│ > what do you think? │"))


class TestToolEchoMask(unittest.TestCase):
    def test_children_of_a_tool_header_are_masked(self):
        lines = ['● Bash(grep "limit")', '  ⎿  You\'ve hit your limit · resets 3pm', 'back to content']
        mask = cw.tool_echo_mask(lines)
        self.assertEqual(mask, [True, True, False])

    def test_a_plain_bullet_is_not_a_tool_call(self):
        # "● API Error: …" is a real error render, not a Name(...) tool header.
        lines = ["● API Error: 529 overloaded"]
        self.assertEqual(cw.tool_echo_mask(lines), [False])


if __name__ == "__main__":
    unittest.main(verbosity=2)
