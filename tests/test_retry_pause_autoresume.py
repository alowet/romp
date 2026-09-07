#!/usr/bin/env python3
"""The global retry-pause is an API-HEALTH flag, not a permanent switch. The user flips "stop all
auto-retries" to calm the auto-retry + judge storm during an API / usage-limit outage — but the judge
tier is gated on `not _retry_paused_on()`, so a pause that never clears silently kills EVERY judge for
hours (the user 2026-06-30, who noted none of the judges were running and called it an API problem that should
clear the second a successful non-API-error response arrives on any session). _auto_resume_retry
clears it event-based: the first live session that is NOT blocked on an API error AND wrote fresh output
since the pause began (mtime past the pause floor) proves the account can serve requests again.
"""
import json
import os
import tempfile
import time
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
# Hermetic state BEFORE the loads — they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
km = SourceFileLoader("romp_kernel_rp", os.path.join(BIN, "romp-kernel")).load_module()


class RetryPauseAutoResume(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.dir = Path(self.td.name)
        self._orig_state = km.jd.STATE
        km.jd.STATE = self.dir                          # retry-paused.json lives under jd.STATE
        self._orig_alive = km._alive_sessions
        self._orig_apierr = km._api_error
        self._orig_push = km._push_all
        km._push_all = lambda *a, **k: self.fail("a tick job built a push inline; it should wake the pusher")
        self._orig_rearm = km.jd.rearm_failed_summaries
        km.jd.rearm_failed_summaries = lambda now, **k: 0   # no given-up cards unless a test says so
        self._was_set = km._pusher_wake.is_set()
        km._pusher_wake.clear()

    def tearDown(self):
        km.jd.STATE = self._orig_state
        km._alive_sessions = self._orig_alive
        km._api_error = self._orig_apierr
        km._push_all = self._orig_push
        km.jd.rearm_failed_summaries = self._orig_rearm
        if self._was_set:
            km._pusher_wake.set()
        else:
            km._pusher_wake.clear()
        self.td.cleanup()

    def _transcript(self, name, mtime):
        p = self.dir / name
        p.write_text("{}\n")
        os.utime(p, (mtime, mtime))
        return str(p)

    # --- the flag records its pause instant ---
    def test_pause_records_a_floor_timestamp(self):
        km._set_retry_paused(True)
        self.assertTrue(km._retry_paused_on())
        self.assertGreater(km._retry_pause_ts(), 0, "a pause records WHEN it began (the auto-resume floor)")
        km._set_retry_paused(False)
        self.assertFalse(km._retry_paused_on())
        self.assertEqual(km._retry_pause_ts(), 0.0, "un-pausing drops the floor")

    # --- recovery clears it ---
    def test_fresh_healthy_session_clears_the_pause(self):
        km._set_retry_paused(True)
        floor = km._retry_pause_ts()
        path = self._transcript("healthy.jsonl", floor + 5)   # wrote output AFTER the pause
        km._alive_sessions = lambda now, tmux: [{"sid": "s1", "path": path}]
        km._api_error = lambda p: None                        # not blocked on an API error
        km._auto_resume_retry(int(time.time()), {})
        self.assertFalse(km._retry_paused_on(), "a served request after the pause proves recovery → resume")

    # --- an api-errored session is NOT proof of recovery ---
    def test_still_errored_session_keeps_the_pause(self):
        km._set_retry_paused(True)
        floor = km._retry_pause_ts()
        path = self._transcript("errored.jsonl", floor + 5)   # fresh mtime, but the last record is an API error
        km._alive_sessions = lambda now, tmux: [{"sid": "s1", "path": path}]
        km._api_error = lambda p: {"text": "overloaded", "status": 529}
        km._auto_resume_retry(int(time.time()), {})
        self.assertTrue(km._retry_paused_on(), "a session still blocked on an API error must not clear the pause")

    # --- a stale success (from before the outage) is NOT proof ---
    def test_stale_session_keeps_the_pause(self):
        km._set_retry_paused(True)
        floor = km._retry_pause_ts()
        path = self._transcript("stale.jsonl", floor - 60)    # last wrote BEFORE the pause
        km._alive_sessions = lambda now, tmux: [{"sid": "s1", "path": path}]
        km._api_error = lambda p: None
        km._auto_resume_retry(int(time.time()), {})
        self.assertTrue(km._retry_paused_on(), "no fresh output since the pause → no evidence the API recovered")

    # --- no-op when not paused ---
    def test_noop_when_not_paused(self):
        km._set_retry_paused(False)
        called = []
        km._alive_sessions = lambda now, tmux: called.append(1) or []
        km._auto_resume_retry(int(time.time()), {})
        self.assertEqual(called, [], "not paused → the resume check does no work")

    # --- delivery: the writer's wake and dirty mark, a second mark for the re-arm's write, no inline push ---
    def _recovered(self):
        km._set_retry_paused(True)
        km._pusher_wake.clear()                          # the pre-pause's own wake, not the clear's
        floor = km._retry_pause_ts()
        path = self._transcript("healthy.jsonl", floor + 5)
        km._alive_sessions = lambda now, tmux: [{"sid": "s1", "path": path}]
        km._api_error = lambda p: None

    def test_the_clear_wakes_the_pusher_and_marks_the_views_dirty(self):
        self._recovered()
        floor = km._views_dirty[0]
        km._auto_resume_retry(int(time.time()), {})
        self.assertFalse(km._retry_paused_on())
        self.assertTrue(km._pusher_wake.is_set(), "the clear wakes the pusher; globalRetryPaused rides its push")
        self.assertGreater(km._views_dirty[0], floor, "the writer's own mark: that cycle rebuilds past the sig")

    def test_a_re_arm_marks_the_views_dirty_after_its_write(self):
        # the store write on this path the cards show (a given-up card's summary sentinel goes back to
        # None) lands after the flag's own stamp, so the branch stamps again once the write is made
        self._recovered()
        seen = []

        def rearm(now, **k):
            seen.append(km._views_dirty[0])              # the clear's stamp, already placed
            return 2
        km.jd.rearm_failed_summaries = rearm
        km._auto_resume_retry(int(time.time()), {})
        self.assertEqual(len(seen), 1)
        self.assertGreater(km._views_dirty[0], seen[0], "a second mark, after the write")
        self.assertTrue(km._pusher_wake.is_set())

    def test_the_no_op_paths_neither_wake_nor_dirty(self):
        km._set_retry_paused(False)
        km._pusher_wake.clear()                          # the test's own write, not the tick's
        floor = km._views_dirty[0]
        km._auto_resume_retry(int(time.time()), {})
        self.assertFalse(km._pusher_wake.is_set(), "not paused: nothing to deliver")
        self.assertEqual(km._views_dirty[0], floor)
        km._set_retry_paused(True)
        km._pusher_wake.clear()
        pfloor = km._retry_pause_ts()
        path = self._transcript("stale.jsonl", pfloor - 60)
        km._alive_sessions = lambda now, tmux: [{"sid": "s1", "path": path}]
        km._api_error = lambda p: None
        floor = km._views_dirty[0]
        km._auto_resume_retry(int(time.time()), {})
        self.assertTrue(km._retry_paused_on())
        self.assertFalse(km._pusher_wake.is_set(), "still paused: nothing to deliver")
        self.assertEqual(km._views_dirty[0], floor)


if __name__ == "__main__":
    unittest.main()
