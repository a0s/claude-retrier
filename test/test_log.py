"""Log rotation (T23).

`~/.claude-retrier/log` (or wherever CR_LOG points) is shared by every wrapper
process on the machine (T01's per-line `[cr <pid> <agent>]` tags exist exactly
because of this), so it has no natural owner to truncate it. Left alone it
grows forever. Rotation happens only at Logger construction (wrapper startup)
so it can never yank the file out from under a neighboring process mid-incident.
"""
import os
import shutil
import tempfile
import unittest

from helper import load


class LogConfigTestCase(unittest.TestCase):
    def test_defaults(self):
        cr = load()
        self.assertEqual(cr.CFG["log_max_bytes"], 5_000_000)
        self.assertEqual(cr.CFG["log_keep"], 2)

    def test_env_overrides_are_parsed_with_parse_tokens(self):
        cr = load(CR_LOG_MAX_BYTES="500k", CR_LOG_KEEP="5")
        self.assertEqual(cr.CFG["log_max_bytes"], 500_000)
        self.assertEqual(cr.CFG["log_keep"], 5)


class LogRotationTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cr-log-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "log")
        self.cr = load()

    def test_oversized_log_is_rotated_to_dot_1(self):
        with open(self.path, "w") as fh:
            fh.write("old\n" * 1000)
        log = self.cr.Logger(self.path, max_bytes=10, keep=2)
        log("new line")
        log.fh.close()

        self.assertTrue(os.path.exists(self.path + ".1"))
        with open(self.path + ".1") as fh:
            self.assertIn("old", fh.read())
        with open(self.path) as fh:
            content = fh.read()
        self.assertNotIn("old", content)
        self.assertIn("new line", content)

    def test_keep_chain_shifts_and_spills_the_oldest(self):
        with open(self.path, "w") as fh:
            fh.write("current\n" * 1000)
        with open(self.path + ".1", "w") as fh:
            fh.write("gen1")
        with open(self.path + ".2", "w") as fh:
            fh.write("gen2-should-be-deleted")

        self.cr.Logger(self.path, max_bytes=10, keep=2)

        with open(self.path + ".2") as fh:
            self.assertEqual(fh.read(), "gen1")
        with open(self.path + ".1") as fh:
            self.assertIn("current", fh.read())
        self.assertFalse(os.path.exists(self.path + ".3"))

    def test_small_log_is_left_alone(self):
        with open(self.path, "w") as fh:
            fh.write("hello\n")
        before = os.stat(self.path)

        self.cr.Logger(self.path, max_bytes=1_000_000, keep=2)

        after = os.stat(self.path)
        self.assertEqual(before.st_ino, after.st_ino)
        self.assertFalse(os.path.exists(self.path + ".1"))
        with open(self.path) as fh:
            self.assertEqual(fh.read(), "hello\n")

    def test_missing_log_is_not_an_error(self):
        # Nothing to rotate yet — first run on this machine.
        log = self.cr.Logger(self.path, max_bytes=10, keep=2)
        self.assertIsNotNone(log.fh)


if __name__ == "__main__":
    unittest.main()
