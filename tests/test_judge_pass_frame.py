#!/usr/bin/env python3
"""The PASS FRAME (the user 2026-07-21): one frozen view of the evidence per judge pass, so every stage
judges the same world. Without it each stage read the live transcript at its own moment — a turn ending
mid-pass was invisible to the planner (stage 1) yet visible to the closer (stage 2), which swept the
freshly-ended turn against a tree the planner had not yet ruled on (the ui g139 stranded top). The frame
pins parsed_session from first touch to pass end (first touch wins across worker threads), pins the
caption memo's fileset key so a mid-pass write can't stamp stale tasks under a fresh key, and only
freezes EVIDENCE — goal/caption stores keep flowing (the closer must see this pass's planner verdicts).
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
jd = SourceFileLoader("romp_judge_passframe", os.path.join(BIN, "romp-judge")).load_module()

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


class PassFrame(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        jd._rebind_state(self.td)
        (self.td / "judge-units-cache").mkdir(parents=True, exist_ok=True)
        self.path = self.td / (SID + ".jsonl")
        recs = [uline(T0, "start the work", "u1"),
                aline(T0 + 10, "Working on it now, first step underway.", "a1", "u1", stop="tool_use")]
        self.path.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
        jd.end_pass_frame(True)          # belt: never inherit a frame a crashed test left open

    def tearDown(self):
        jd.end_pass_frame(True)

    def _append(self, rec):
        with open(self.path, "a") as f:
            f.write(json.dumps(rec) + "\n")

    def test_frame_pins_the_parse_across_a_mid_pass_write(self):
        self.assertTrue(jd.begin_pass_frame())
        first = jd.parsed_session(SID, [str(self.path)], T0 + 100)
        self.assertFalse(first["turns"][-1]["ended"], "the frame captured the turn still open")
        self._append(aline(T0 + 60, "All done: shipped and verified.", "a2", "a1", stop="end_turn"))
        again = jd.parsed_session(SID, [str(self.path)], T0 + 100)
        self.assertIs(again, first, "every later look in the pass returns the SAME frozen parse")
        jd.end_pass_frame(True)
        fresh = jd.parsed_session(SID, [str(self.path)], T0 + 100)
        self.assertIsNot(fresh, first)
        self.assertTrue(fresh["turns"][-1]["ended"], "the next pass sees the ended turn, whole")

    def test_without_a_frame_the_live_world_shows_through(self):
        first = jd.parsed_session(SID, [str(self.path)], T0 + 100)
        self._append(aline(T0 + 60, "All done: shipped and verified.", "a2", "a1", stop="end_turn"))
        fresh = jd.parsed_session(SID, [str(self.path)], T0 + 100)
        self.assertIsNot(fresh, first, "no frame → each look re-reads reality (the pre-frame behavior)")

    def test_a_warm_first_touch_pins_the_cached_parse(self):
        # The cache-HIT path returned without pinning (found in review 2026-09-06): a session whose parse
        # was already in _PARSE_CACHE froze nothing under the frame, so a turn ending mid-pass was visible
        # to a later stage and invisible to an earlier one - the same two-worlds shape the frame exists
        # to prevent, for every warm session (idle sessions are warm nearly always).
        warm = jd.parsed_session(SID, [str(self.path)], T0 + 100)     # frameless: fills the cache
        self.assertTrue(jd.begin_pass_frame())
        first = jd.parsed_session(SID, [str(self.path)], T0 + 100)
        self.assertIs(first, warm, "premise: the pass's first touch is a cache hit")
        self._append(aline(T0 + 60, "All done: shipped and verified.", "a2", "a1", stop="end_turn"))
        again = jd.parsed_session(SID, [str(self.path)], T0 + 100)
        self.assertIs(again, first, "the hit was pinned: a later stage sees the SAME frozen parse")
        self.assertFalse(again["turns"][-1]["ended"], "the mid-pass append stays out of this pass")
        jd.end_pass_frame(True)
        fresh = jd.parsed_session(SID, [str(self.path)], T0 + 100)
        self.assertIsNot(fresh, first)
        self.assertTrue(fresh["turns"][-1]["ended"], "the next pass sees the ended turn, whole")

    def test_a_warm_cache_without_a_frame_still_reads_live(self):
        # the no-frame path is unchanged: an unchanged file hits the cache, a grown one re-parses at once
        warm = jd.parsed_session(SID, [str(self.path)], T0 + 100)
        self.assertIs(jd.parsed_session(SID, [str(self.path)], T0 + 100), warm,
                      "an unchanged file is served from the cache")
        self._append(aline(T0 + 60, "All done: shipped and verified.", "a2", "a1", stop="end_turn"))
        fresh = jd.parsed_session(SID, [str(self.path)], T0 + 100)
        self.assertIsNot(fresh, warm)
        self.assertTrue(fresh["turns"][-1]["ended"], "no frame: the appended turn shows on the next look")

    def test_a_warm_hit_yields_to_a_concurrent_first_toucher(self):
        # first touch wins on the HIT path too: the pin is a setdefault, never an overwrite. A worker thread
        # that pinned the session between this caller's cache read and its lock take keeps its pin, and this
        # caller is handed the peer's parse, so no two stages of the pass ever hold different objects
        jd.parsed_session(SID, [str(self.path)], T0 + 100)             # frameless: fills the cache
        self.assertTrue(jd.begin_pass_frame())
        peer = {"turns": [], "peer": True}

        class RacedCache(dict):
            # parsed_session reads the cache BEFORE it takes _frame_lock, so a peer pinning here is the
            # concurrent first toucher, and the lock is free to take
            def get(self, k, default=None):
                with jd._frame_lock:
                    jd._frame["parses"].setdefault(SID, peer)
                return dict.get(self, k, default)
        real = jd._PARSE_CACHE
        jd._PARSE_CACHE = RacedCache(real)
        try:
            got = jd.parsed_session(SID, [str(self.path)], T0 + 100)
        finally:
            jd._PARSE_CACHE = real
        self.assertIs(got, peer, "first touch wins: the hit path yields to the peer's pin")
        self.assertIs(jd._frame["parses"][SID], peer, "and the peer's pin stands")

    def test_frame_ownership_nests(self):
        self.assertTrue(jd.begin_pass_frame(), "first opener owns the frame")
        pinned = jd.parsed_session(SID, [str(self.path)], T0 + 100)
        self.assertFalse(jd.begin_pass_frame(), "a tier under the producer's frame joins, not owns")
        jd.end_pass_frame(False)          # the joiner's end is a no-op
        self._append(aline(T0 + 60, "All done: shipped and verified.", "a2", "a1", stop="end_turn"))
        self.assertIs(jd.parsed_session(SID, [str(self.path)], T0 + 100), pinned,
                      "the frame survives a joiner's end — the mid-pass write stays invisible")
        jd.end_pass_frame(True)
        self.assertTrue(jd.parsed_session(SID, [str(self.path)], T0 + 100)["turns"][-1]["ended"],
                        "the owner's end unfreezes the world — the write shows on the next look")

    def test_caption_memo_key_rides_the_frame(self):
        # a transcript growing MID-PASS must not stamp the pass's (older) task list under the file's
        # NEW key — the next pass would cache-hit that key and never caption the growth
        self._append(aline(T0 + 20, "Finished the first stretch of work here.", "a2", "a1",
                           stop="end_turn"))
        self.assertTrue(jd.begin_pass_frame())
        v1 = jd.tasks_for(SID, str(self.path), [str(self.path)], T0 + 100)
        self.assertTrue(v1, "the ended turn yields caption tasks")
        self._append(uline(T0 + 200, "now do a second thing", "u2", "a2"))
        self._append(aline(T0 + 210, "Second thing finished and checked in.", "a3", "u2",
                           stop="end_turn"))
        self.assertEqual(jd.tasks_for(SID, str(self.path), [str(self.path)], T0 + 300), v1,
                         "inside the pass the frozen task list holds")
        jd.end_pass_frame(True)
        v2 = jd.tasks_for(SID, str(self.path), [str(self.path)], T0 + 300)
        ids = {w["id"] for t in v2 for w in t["writes"]}
        self.assertGreater(len(ids), len({w["id"] for t in v1 for w in t["writes"]}),
                           "the next pass captions the growth — the memo never went stale")

    def test_tier_entries_and_producer_are_frame_wrapped(self):
        jsrc = open(jd.__file__).read()
        for fn in ("def run_triage", "def run_index"):
            body = jsrc.split(fn, 1)[1]
            self.assertLess(body.find("begin_pass_frame()"), body.find("def ", 10),
                            "%s opens (or joins) a pass frame before any stage runs" % fn)
        ksrc = open(os.path.join(os.path.dirname(BIN), "kernel", "kernel.py")).read()
        self.assertIn("_own_frame = jd.begin_pass_frame()", ksrc,
                      "the kernel producer pins ONE frame for both tiers")
        self.assertIn("jd.end_pass_frame(_own_frame)", ksrc,
                      "and ends it (join path plus the finally safety net)")
        self.assertEqual(ksrc.count("jd.end_pass_frame(_own_frame)"), 2,
                         "normal-path end after the join AND the leak-proof finally")


if __name__ == "__main__":
    unittest.main()
