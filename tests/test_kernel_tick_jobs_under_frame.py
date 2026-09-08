#!/usr/bin/env python3
"""A pusher tick job that parses a session while a judge pass frame is open reads the frame's world, on a
cache HIT as on a miss (the hit-path pin, review 2026-09-06). The frame is a module global in the judge, so
the kernel's tick jobs (_clear_done_working_notes, _interrupt_block_tick, _closer_pending, ...) share it
with the pass: a warm session they touch mid-pass is the pass's frozen parse, not the live file, and a turn
that ends after the pass's first touch is judged whole in the next pass. Before the pin, a warm hit returned
unpinned and the job read the live transcript under an open frame (the two-worlds shape).
SYNTHETIC fixtures only."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
# Hermetic state BEFORE the loads — they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
km = SourceFileLoader("romp_kernel_tickframe", os.path.join(BIN, "romp-kernel")).load_module()
jd = km.jd

SID = "11111111-2222-3333-4444-555555555555"
T0 = 1781100000


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def uline(t, text, uuid, parent=None):
    return {"type": "user", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent,
            "promptSource": "typed", "message": {"role": "user", "content": text}}


def aline(t, text, uuid, parent=None, stop="end_turn"):
    return {"type": "assistant", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}],
                        "stop_reason": stop}}


class WarmTickJobUnderAFrame(unittest.TestCase):
    """_clear_done_working_notes lifts a session's working note once its last turn has ENDED with no open
    top goal; an open turn keeps it. That decision is the job's read of parsed_session, so it shows which
    world the job saw."""

    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        jd._rebind_state(self.td)
        self.path = self.td / (SID + ".jsonl")
        recs = [uline(T0, "start the work", "u1"),
                aline(T0 + 10, "Working on it now, first step underway.", "a1", "u1", stop="tool_use")]
        self.path.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
        jd.end_pass_frame(True)          # belt: never inherit a frame a crashed test left open
        jd._PARSE_CACHE.clear(); jd._CHAIN_MEMO.clear()   # the cache-hit premise must not ride an earlier test's entry
        self.lifted = []
        self._saved = (km._working_notes, km._alive_sessions, km._open_top_goal, km._set_working_note,
                       km._suspended_after)
        km._working_notes = lambda: {SID: "owns the api worktree"}
        km._alive_sessions = lambda now, tmux: [{"sid": SID, "path": str(self.path)}]
        km._open_top_goal = lambda sid: False
        km._set_working_note = lambda sid, text: self.lifted.append((sid, text))
        km._suspended_after = lambda t: False

    def tearDown(self):
        jd.end_pass_frame(True)
        (km._working_notes, km._alive_sessions, km._open_top_goal, km._set_working_note,
         km._suspended_after) = self._saved

    def _append(self, rec):
        with open(self.path, "a") as f:
            f.write(json.dumps(rec) + "\n")

    def test_a_warm_hit_holds_the_open_turn_for_the_whole_pass(self):
        warm = jd.parsed_session(SID, [str(self.path)], T0 + 100)     # frameless: fills the cache, turn open
        self.assertFalse(warm["turns"][-1]["ended"], "premise: the cached parse holds an open turn")
        self.assertTrue(jd.begin_pass_frame())
        km._clear_done_working_notes(T0 + 100, {})                      # the pass's first touch: a cache HIT
        self.assertEqual(self.lifted, [], "premise: an open turn keeps the note")
        self.assertIs(jd._frame["parses"].get(SID), warm, "the tick job's warm hit is pinned into the pass frame")
        self._append(aline(T0 + 60, "All done: shipped and verified.", "a2", "a1", stop="end_turn"))
        km._clear_done_working_notes(T0 + 100, {})
        self.assertEqual(self.lifted, [], "mid-pass the job reads the frame's world, where the turn is still open")
        self.assertFalse(jd._frame["parses"][SID]["turns"][-1]["ended"], "the mid-pass append stays out of this pass")
        jd.end_pass_frame(True)
        km._clear_done_working_notes(T0 + 100, {})
        self.assertEqual(self.lifted, [(SID, "")], "the next pass sees the ended turn, whole, and lifts the claim")


if __name__ == "__main__":
    unittest.main()
