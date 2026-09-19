"""typing_plan (T16): the exact keystrokes schedule_injection turns into pty
writes for a given (agent, text). A pure function, so the T15 live-driving
table (docs/backlog/T15-codex-unfold-live-investigation.md) is pinned here
without a pty: only a leading "/" that names a real command opens anything
the composer resolves and accepts with Enter, on either agent. "$name"
(codex's own "invoke a skill" convention) and "@file" (both agents' file
mention) turned out, live, to have no popup at all -- they are delivered as
plain text exactly like anything else, as long as the whole phrase arrives in
one write() the way schedule_injection sends it.
"""
import unittest

from helper import load

cr = load()

CFG = dict(slash_gap=0.9, slash_enter=2, slash_enter_gap=0.6)


class TestTypingPlan(unittest.TestCase):
    def slash_plan(self, text):
        return [(0.0, text.encode()), (0.9, b"\r"), (1.5, b"\r")]

    def plain_plan(self, text):
        return [(0.0, text.encode()), (0.6, b"\r")]

    def test_a_real_command_gets_the_slash_treatment_on_both_agents(self):
        for agent in ("claude", "codex"):
            self.assertEqual(cr.typing_plan(agent, "/clear", CFG),
                             self.slash_plan("/clear"))
            self.assertEqual(cr.typing_plan(agent, "/skill arg", CFG),
                             self.slash_plan("/skill arg"))

    def test_dollar_skill_is_plain_text_on_both_agents(self):
        # T15: codex has no "$" popup at all -- $name is a model-level
        # convention, not a composer feature.
        text = "$supervisor continue scratchpad/RESUME.md"
        for agent in ("claude", "codex"):
            self.assertEqual(cr.typing_plan(agent, text, CFG), self.plain_plan(text))

    def test_at_file_mention_is_plain_text_on_both_agents(self):
        text = "@README.md summarize this file"
        for agent in ("claude", "codex"):
            self.assertEqual(cr.typing_plan(agent, text, CFG), self.plain_plan(text))

    def test_plain_text_on_both_agents(self):
        text = "continue from the handoff file"
        for agent in ("claude", "codex"):
            self.assertEqual(cr.typing_plan(agent, text, CFG), self.plain_plan(text))

    def test_russian_text_on_both_agents(self):
        text = "Прочти handoff.md и продолжай"
        for agent in ("claude", "codex"):
            self.assertEqual(cr.typing_plan(agent, text, CFG), self.plain_plan(text))

    def test_empty_text_does_not_crash_or_match_the_slash_prefix(self):
        # "" .startswith("/") is False; "" in "/" is True -- a bug this
        # guards against directly (text[:1] would be "", which IS "in" any
        # non-empty string in Python).
        for agent in ("claude", "codex"):
            self.assertEqual(cr.typing_plan(agent, "", CFG), self.plain_plan(""))

    def test_an_unknown_agent_falls_back_to_claudes_table(self):
        self.assertEqual(cr.typing_plan("some-future-agent", "/clear", CFG),
                         self.slash_plan("/clear"))


if __name__ == "__main__":
    unittest.main()
