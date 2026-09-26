"""Telling the user a newer release exists, and how to get it.

Two rules hold the whole thing up. A session never waits on the network: the
notice is read out of a cache the previous run wrote, and the fetch that
refreshes it happens after claude is already up. And the command printed is the
command that updates THIS copy — `brew upgrade` shown to someone running a git
clone is advice that does nothing when followed.
"""
import json
import os
import shutil
import tempfile
import time
import unittest

from helper import load

cr = load()

FEED = json.dumps({"tag_name": "v1.11.0",
                   "html_url": "https://github.com/a0s/agent-retrier/releases/tag/v1.11.0"})


class TestVersions(unittest.TestCase):
    def test_a_release_tag_is_read_with_or_without_its_v(self):
        self.assertEqual(cr.parse_version("v1.10.0"), (1, 10, 0))
        self.assertEqual(cr.parse_version(" 1.9.0 "), (1, 9, 0))

    def test_anything_that_is_not_a_release_is_not_a_version(self):
        for junk in ("v1.10", "1.10.0-rc1", "main", "", None, "latest"):
            self.assertIsNone(cr.parse_version(junk), junk)

    def test_ordering_is_numeric_not_alphabetical(self):
        # The bug this is here for: "1.9.0" > "1.10.0" as strings.
        self.assertLess(cr.parse_version("1.9.0"), cr.parse_version("1.10.0"))


class UpdateTestCase(unittest.TestCase):
    def setUp(self):
        # realpath: on macOS the temp dir is reached through /var -> /private/var,
        # and the command printed names the path the way the wrapper resolves it.
        self.dir = os.path.realpath(tempfile.mkdtemp(prefix="cr-up-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.calls = []
        self.logs = []
        self.now = 5000.0
        self.cfg = dict(
            update_check=True, update_repo="a0s/agent-retrier", update_url="",
            update_formula="a0s/agent-retrier/agent-retrier",
            update_cache=os.path.join(self.dir, "update.json"),
            update_ttl=86400.0, update_timeout=1.0, update_notice=0.0,
        )
        os.environ.pop("CR_SELF", None)

    def fetch(self, url, timeout, headers=None):
        self.calls.append(url)
        if "nowhere" in url:
            raise IOError("no route to host")
        if "garbage" in url:
            return "<html>not json</html>"
        return FEED

    def checker(self, **over):
        return cr.UpdateCheck(dict(self.cfg, **over), self.logs.append,
                              fetch=self.fetch, clock=lambda: self.now)

    def cached(self, version, at=None):
        with open(self.cfg["update_cache"], "w") as fh:
            json.dump({"version": version,
                       "at": self.now if at is None else at}, fh)


class TestWhatIsSaid(UpdateTestCase):
    def test_a_newer_release_is_announced_with_both_numbers(self):
        self.cached("v1.11.0")
        headline, _ = self.checker().notice("1.10.0")
        self.assertIn("1.10.0", headline)
        self.assertIn("1.11.0", headline)

    def test_the_version_in_hand_is_not_news(self):
        self.cached("v1.10.0")
        self.assertIsNone(self.checker().notice("1.10.0"))

    def test_a_build_ahead_of_the_release_is_not_told_to_downgrade(self):
        # Running from a clone between releases is the normal way to hit this.
        self.cached("v1.10.0")
        self.assertIsNone(self.checker().notice("1.11.0"))

    def test_nothing_is_said_before_anything_has_been_checked(self):
        self.assertIsNone(self.checker().notice("1.10.0"))

    def test_the_switch_turns_the_whole_thing_off(self):
        self.cached("v1.11.0")
        look = self.checker(update_check=False)
        self.assertIsNone(look.notice("1.10.0"))
        self.assertFalse(look.refresh(background=False))
        self.assertEqual(self.calls, [])


class TestHowToUpgrade(UpdateTestCase):
    def test_a_cellar_copy_is_a_brew_upgrade(self):
        path = os.path.join(self.dir, "Cellar", "agent-retrier", "1.9.0", "bin", "cr")
        os.makedirs(os.path.dirname(path))
        open(path, "w").close()
        self.assertEqual(self.checker().upgrade_command(path),
                         "brew upgrade a0s/agent-retrier/agent-retrier")

    def test_a_clone_is_a_git_pull_of_that_clone(self):
        os.makedirs(os.path.join(self.dir, ".git"))
        path = os.path.join(self.dir, "agent-retrier.sh")
        open(path, "w").close()
        self.assertEqual(self.checker().upgrade_command(path),
                         "git -C %s pull" % self.dir)

    def test_anything_else_gets_the_releases_page(self):
        path = os.path.join(self.dir, "agent-retrier.sh")
        open(path, "w").close()
        self.assertEqual(self.checker().upgrade_command(path),
                         "https://github.com/a0s/agent-retrier/releases/latest")

    def test_the_running_copy_is_found_without_being_handed_over(self):
        os.makedirs(os.path.join(self.dir, ".git"))
        os.environ["CR_SELF"] = os.path.join(self.dir, "agent-retrier.sh")
        self.addCleanup(os.environ.pop, "CR_SELF", None)
        self.assertEqual(self.checker().upgrade_command(),
                         "git -C %s pull" % self.dir)


class TestTheCheckItself(UpdateTestCase):
    def test_the_feed_becomes_the_cache(self):
        self.assertTrue(self.checker().refresh(background=False))
        self.assertEqual(json.load(open(self.cfg["update_cache"]))["version"], "v1.11.0")
        self.assertEqual(
            self.calls,
            ["https://api.github.com/repos/a0s/agent-retrier/releases/latest"])

    def test_it_is_asked_once_a_day_not_once_a_session(self):
        self.cached("v1.11.0")
        self.assertFalse(self.checker().refresh(background=False))
        self.assertEqual(self.calls, [])
        self.now += 90000.0
        self.assertTrue(self.checker().refresh(background=False))

    def test_a_check_that_failed_still_counts_as_recent(self):
        # Otherwise a machine with no network asks GitHub on every single launch.
        self.checker(update_url="https://nowhere.example/latest").refresh(background=False)
        self.assertTrue(self.logs)
        self.now += 60.0
        self.calls = []
        self.checker(update_url="https://nowhere.example/latest").refresh(background=False)
        self.assertEqual(self.calls, [])

    def test_a_feed_that_answers_nonsense_changes_nothing(self):
        self.cached("v1.11.0", at=0)
        self.checker(update_url="https://garbage.example/latest").refresh(background=False)
        self.assertEqual(json.load(open(self.cfg["update_cache"]))["version"], "v1.11.0")

    def test_the_background_check_really_runs(self):
        look = self.checker()
        look.refresh()
        for _ in range(200):
            if os.path.exists(self.cfg["update_cache"]):
                break
            time.sleep(0.01)
        self.assertEqual(json.load(open(self.cfg["update_cache"]))["version"], "v1.11.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
