"""Reset-time parsing.

Wall-clock arithmetic is where upstream lost the most user time: a timezone
mis-read added 24h (issue #6), a just-passed reset added another 24h, and the
weekly banner's `resets Jul 22 at 6am` form is not parsed by upstream at all —
it falls through to a flat 5-hour guess.
"""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from helper import load

cw = load()

WARSAW = ZoneInfo("Europe/Warsaw")
TOKYO = ZoneInfo("Asia/Tokyo")
NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

HOUR = 3600.0


def hours(seconds):
    return round(seconds / HOUR, 3)


class TestAbsoluteTimes(unittest.TestCase):
    def test_same_day_reset(self):
        now = datetime(2026, 7, 16, 8, 49, tzinfo=WARSAW)
        got = cw.parse_reset("You've hit your session limit · resets 1:30pm (Europe/Warsaw)", now)
        self.assertAlmostEqual(hours(got), 4.683, places=2)

    def test_reset_after_midnight_rolls_to_tomorrow(self):
        now = datetime(2026, 7, 14, 21, 59, tzinfo=WARSAW)
        got = cw.parse_reset("You've hit your session limit · resets 3:20am (Europe/Warsaw)", now)
        self.assertAlmostEqual(hours(got), 5.35, places=2)

    def test_banner_timezone_wins_over_host_timezone(self):
        # Issue #6: host in one zone, banner stating another. Reading the banner
        # time as host-local is what produced the ~25h wait.
        now = datetime(2026, 4, 15, 9, 43, tzinfo=TOKYO)
        got = cw.parse_reset("You've hit your limit · resets 8pm (Asia/Tokyo)", now)
        self.assertAlmostEqual(hours(got), 10.283, places=2)

        # Same instant, but the host sits in New York. The answer must not move.
        got_ny = cw.parse_reset("You've hit your limit · resets 8pm (Asia/Tokyo)",
                                now.astimezone(NY))
        self.assertAlmostEqual(hours(got_ny), 10.283, places=2)

    def test_unknown_timezone_falls_back_to_host_local(self):
        now = datetime(2026, 7, 16, 8, 0, tzinfo=WARSAW)
        got = cw.parse_reset("resets 10am (Middle/Earth)", now)
        self.assertAlmostEqual(hours(got), 2.0, places=2)

    def test_24_hour_clock(self):
        now = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
        self.assertAlmostEqual(hours(cw.parse_reset("resets 15:30 (UTC)", now)), 7.5, places=2)

    def test_am_pm_ambiguity_picks_the_nearest_future(self):
        # "resets 3" with no am/pm at 08:00 must mean 15:00, not 03:00 tomorrow.
        now = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
        self.assertAlmostEqual(hours(cw.parse_reset("resets 3 (UTC)", now)), 7.0, places=2)


class TestDatedResets(unittest.TestCase):
    def test_weekly_limit_with_a_date(self):
        # Verbatim from a real transcript. Upstream returns None here and waits 5h.
        now = datetime(2026, 7, 19, 19, 22, tzinfo=WARSAW)
        got = cw.parse_reset("You've hit your weekly limit · resets Jul 22 at 6am (Europe/Warsaw)", now)
        self.assertAlmostEqual(hours(got), 58.633, places=2)

    def test_date_after_the_time(self):
        now = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
        got = cw.parse_reset("resets at 6am on Jul 22 (UTC)", now)
        self.assertAlmostEqual(hours(got), 66.0, places=2)

    def test_date_that_already_passed_this_year_rolls_to_next(self):
        now = datetime(2026, 12, 30, 12, 0, tzinfo=UTC)
        got = cw.parse_reset("resets Jan 2 at 6am (UTC)", now)
        self.assertAlmostEqual(hours(got), 66.0, places=2)

    def test_tomorrow(self):
        now = datetime(2026, 7, 16, 20, 0, tzinfo=UTC)
        self.assertAlmostEqual(hours(cw.parse_reset("resets tomorrow at 9am (UTC)", now)), 13.0, places=2)

    def test_weekday(self):
        now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)   # a Thursday
        self.assertAlmostEqual(hours(cw.parse_reset("resets Saturday at 6am (UTC)", now)), 42.0, places=2)


class TestRelativeTimes(unittest.TestCase):
    def test_variants(self):
        cases = {
            "try again in 5 hours": 5.0,
            "try again in 30 minutes": 0.5,
            "resets in 3 hours": 3.0,
            "Retry-After: 3600": 1.0,
            "come back in 2 days": 48.0,
            "wait 90 seconds": 0.025,
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertAlmostEqual(hours(cw.parse_reset(text)), want, places=3)


class TestIso(unittest.TestCase):
    def test_iso_instant(self):
        now = datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
        got = cw.parse_reset("resets at 2026-07-22T06:00:00Z", now)
        self.assertAlmostEqual(hours(got), 6.0, places=2)


class TestBoundaries(unittest.TestCase):
    def test_just_passed_reset_retries_immediately(self):
        # Observed upstream: "resets 10am" settled on at 10:03 parked for ~24h.
        now = datetime(2026, 7, 16, 10, 3, tzinfo=UTC)
        self.assertEqual(cw.parse_reset("resets 10am (UTC)", now), 0.0)

    def test_long_past_reset_rolls_forward(self):
        now = datetime(2026, 7, 16, 20, 0, tzinfo=UTC)
        got = cw.parse_reset("resets 10am (UTC)", now)
        self.assertAlmostEqual(hours(got), 14.0, places=2)

    def test_nothing_parseable(self):
        self.assertIsNone(cw.parse_reset("You've hit your session limit"))
        self.assertIsNone(cw.parse_reset(""))
        self.assertIsNone(cw.parse_reset(None))

    def test_impossible_clock_is_rejected(self):
        self.assertIsNone(cw.parse_reset("resets 99:99"))

    def test_dst_spring_forward(self):
        # 2026-03-29, Europe/Warsaw jumps 02:00 -> 03:00. A reset stated as 4am
        # is 3h away in wall-clock terms but only 2h in real time.
        now = datetime(2026, 3, 29, 1, 0, tzinfo=WARSAW)
        got = cw.parse_reset("resets 4am (Europe/Warsaw)", now)
        self.assertAlmostEqual(hours(got), 2.0, places=2)

    def test_dst_fall_back(self):
        # 2026-10-25, Europe/Warsaw repeats 02:00-03:00, so midnight to 4am is
        # FIVE real hours. Naive wall-clock subtraction says 4 and wakes an hour
        # early, with the banner still live.
        now = datetime(2026, 10, 25, 0, 0, tzinfo=WARSAW)
        got = cw.parse_reset("resets 4am (Europe/Warsaw)", now)
        self.assertAlmostEqual(hours(got), 5.0, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
