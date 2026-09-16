#!/usr/bin/env python3
"""The producer loop's scheduling policy (the user 2026-06-19): the TRIAGE tier runs ALWAYS for any live
session — no browser-connected gate — exactly like the INDEX tier, and the backstop between event-pokes is
short (3s). Source-level pins: the loop is an infinite thread that drives the real fleet, so its policy is
asserted against the source rather than executed. (Behaviour: each judge still only makes an LLM call when
it has real new work, so an idle pass is filesystem stats, not model calls.)
"""
import os
import inspect
import re
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
SRC = Path(os.path.join(os.path.dirname(HERE), "bin", "romp-kernel")).read_text()


class ProducerPolicy(unittest.TestCase):
    def _producer_body(self):
        # the body of def _producer() up to the next top-level def
        m = re.search(r"\ndef _producer\(\):\n(.*?)\ndef ", SRC, re.S)
        self.assertTrue(m, "found the _producer loop")
        return m.group(1)

    def test_triage_runs_always_for_a_live_session_not_browser_gated(self):
        body = self._producer_body()
        # both tiers start together inside the ONE shared pass body (judge.py run_pass), which the producer calls with the gate
        self.assertIn("res = jd.run_pass(_tiers_may_start(tracking), before_tier=_tier_started)", body)
        jsrc = Path(os.path.join(os.path.dirname(HERE), "kernel", "judge.py")).read_text()
        self.assertIn('lambda: run_index(now=now), "index", acc, before_tier), name="index"', jsrc)
        self.assertIn('lambda: run_triage(now=now), "triage", acc, before_tier), name="triage"', jsrc)
        # the OLD browser+sig gate is gone — triage is no longer conditional on a connected browser
        self.assertNotIn("if browser and sig", body)
        self.assertNotIn("bool(_clients)", body, "the loop no longer branches on whether a browser is connected")

    def test_both_tiers_share_the_same_live_session_guard(self):
        body = self._producer_body()
        # index + triage appends sit inside ONE guard: _tiers_may_start (a live session, retries not paused, the Task
        # tracking switch on; T404), a predicate executed in tests/test_task_tracking_switch.py
        self.assertIn("jd.run_pass(_tiers_may_start(tracking), before_tier=_tier_started)", body, "the predicate's answer is what the shared pass body gets")
        self.assertIn("def _tiers_may_start(tracking=None):", SRC)
        self.assertIn("return bool(tracking) and bool(_live_map()) and not _retry_paused_on()", SRC, "the predicate's three inputs")
        jsrc = Path(os.path.join(os.path.dirname(HERE), "kernel", "judge.py")).read_text()
        guard = re.search(r"    if may_start:\n(.*?)\n    frame = begin_pass_frame\(\)", jsrc, re.S)
        self.assertTrue(guard, "in the shared body the two tiers sit under the one may_start guard")
        block = guard.group(1)
        self.assertIn('name="index"', block)
        self.assertIn('name="triage"', block)
        self.assertNotIn("def _run_tier(", SRC, "the kernel keeps no copy of the tier runner")

    def test_backstop_is_short(self):
        body = self._producer_body()
        self.assertIn("_producer_wake.wait(3)", body, "the event-poke backstop is 3s")
        self.assertNotIn("_producer_wake.wait(20)", body, "the old 20s backstop is gone")


if __name__ == "__main__":
    unittest.main()
