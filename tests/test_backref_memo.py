#!/usr/bin/env python3
"""The sender-board walk behind the courier's link repair (_handoff_backref) is built once per state of its
inputs and served while they stand (2026-09-09).

Every call walked every discovered session's goal store with the writer's loader, and the courier asked it
for each placed delegate whose link was missing, on every triage pass. The map now answers every message id
from one walk over the read-only view, keyed on the discover order and each sender store's file key with
its journal's and archive's, taken before the reads. Pins: built once then served; a sender store write
re-derives, including one the file clock cannot see; a journal row re-derives; a fleet change re-derives;
a write landing during the build is seen next call; the first sender in discover order wins; a completed
handoff is no backref; a store that raises leaves nothing cached; a rebound root forgets; the counters.

Synthetic sids and stores under a temp root; discover is a stub, so no transcripts are needed."""
import json
import os
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
jd = SourceFileLoader("romp_judge_backref_memo", os.path.join(BIN, "romp-judge")).load_module()

S1 = "11111111-2222-3333-4444-999999999901"
S2 = "11111111-2222-3333-4444-999999999902"
S3 = "11111111-2222-3333-4444-999999999903"
M1, M2, M3 = "1781100000.00001_00001.TESTHOST", "1781100000.00002_00002.TESTHOST", "1781100000.00003_00003.TESTHOST"
T0 = 1781100000


def _node(nid, text, mid=None, complete=False):
    nd = {"id": nid, "text": text, "parentId": None, "nodeComplete": complete, "blocked": False, "cleared": False,
          "trail": [], "t": T0}
    if mid:
        nd["handoff"] = {"peer": "peer", "msgId": mid}
    return nd


class _Memo(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.saved_root, self.saved_discover = jd.STATE, jd.discover
        jd._rebind_state(Path(self.td.name))
        jd.GOALDIR.mkdir(parents=True, exist_ok=True)
        self.fleet = [(S1, "/nonexistent/s1.jsonl", None, "s1"), (S2, "/nonexistent/s2.jsonl", None, "s2")]
        jd.discover = lambda now: list(self.fleet)
        self.write(S1, {S1 + ":g1": _node(S1 + ":g1", "delegated to worker0", M1)})
        self.write(S2, {S2 + ":g1": _node(S2 + ":g1", "delegated to worker1", M2)})
        self._reset()

    def tearDown(self):
        jd.discover = self.saved_discover
        jd._rebind_state(self.saved_root)
        self._reset()
        self.td.cleanup()

    @staticmethod
    def _reset():
        jd._BACKREF_MEMO["slot"] = None
        for k in jd._BACKREF_STATS:
            jd._BACKREF_STATS[k] = 0
        jd._shared_clear()

    def write(self, sid, nodes, mtime=None):
        p = jd.GOALDIR / (sid + ".json")
        p.write_text(json.dumps({"rompUuid": sid, "seq": 1, "lastNode": None, "closedTurns": [], "nodes": nodes,
                                 "placements": {}, "status": {k: "working" for k in nodes}}))
        if mtime is not None:
            os.utime(p, (mtime, mtime))

    def counting(self):
        """Wrap the view's loader; returns the list of sids read."""
        reads, real = [], jd.load_goals_shared
        jd.load_goals_shared = lambda fsid: (reads.append(fsid), real(fsid))[1]
        self.addCleanup(lambda: setattr(jd, "load_goals_shared", real))
        return reads


class BackrefMemo(_Memo):
    def test_built_once_then_served_while_the_inputs_stand(self):
        reads = self.counting()
        self.assertEqual(jd._handoff_backref(M1), (S1, S1 + ":g1"))
        self.assertEqual(jd._handoff_backref(M2), (S2, S2 + ":g1"))
        self.assertEqual(jd._handoff_backref("1781100000.00009_00009.TESTHOST"), ("", ""), "an untracked message")
        self.assertEqual(sorted(reads), sorted([S1, S2]), "one walk: each sender store read once")
        self.assertEqual(jd._BACKREF_STATS, {"served": 2, "built": 1})

    def test_a_sender_store_write_re_derives_even_when_the_file_clock_does_not_move(self):
        jd._handoff_backref(M1)
        before = os.stat(jd.GOALDIR / (S2 + ".json"))
        self.write(S2, {S2 + ":g1": _node(S2 + ":g1", "delegated to worker1", M2),
                        S2 + ":g2": _node(S2 + ":g2", "delegated to worker2", M3)}, mtime=before.st_mtime)
        self.assertEqual(os.stat(jd.GOALDIR / (S2 + ".json")).st_mtime, before.st_mtime)
        self.assertEqual(jd._handoff_backref(M3), (S2, S2 + ":g2"), "the size moved: built again, the new handoff seen")
        self.assertEqual(jd._BACKREF_STATS["built"], 2)

    def test_a_journal_row_re_derives(self):
        jd._handoff_backref(M1)
        jd._overrides_dir().mkdir(parents=True, exist_ok=True)
        with (jd._overrides_dir() / (S1 + ".jsonl")).open("a") as f:
            f.write(json.dumps({"op": "resolve", "id": S1 + ":g1", "t": T0 + 10}) + "\n")
        jd._shared_clear()
        jd._handoff_backref(M1)
        self.assertEqual(jd._BACKREF_STATS["built"], 2, "the journal is a keyed input")

    def test_a_fleet_change_re_derives(self):
        jd._handoff_backref(M1)
        self.write(S3, {S3 + ":g1": _node(S3 + ":g1", "delegated to worker3", M3)})
        self.fleet.append((S3, "/nonexistent/s3.jsonl", None, "s3"))
        self.assertEqual(jd._handoff_backref(M3), (S3, S3 + ":g1"))
        self.assertEqual(jd._BACKREF_STATS["built"], 2)

    def test_a_write_landing_during_the_build_is_seen_next_call(self):
        # INTERLEAVED WRITE: the key is taken before the reads. S2 gains a handoff while the walk reads S1, so
        # the map the first call builds is cached under a key the store no longer has; the next call rebuilds.
        real = jd.load_goals_shared
        landed = []

        def read_then_write(fsid):
            st = real(fsid)
            if fsid == S1 and not landed:
                landed.append(True)
                self.write(S2, {S2 + ":g1": _node(S2 + ":g1", "delegated to worker1", M2),
                                S2 + ":g2": _node(S2 + ":g2", "delegated to worker2", M3)})
            return st
        jd.load_goals_shared = read_then_write
        try:
            first = jd._handoff_backref(M3)
        finally:
            jd.load_goals_shared = real
        self.assertTrue(landed)
        self.assertEqual(jd._BACKREF_STATS["built"], 1)
        second = jd._handoff_backref(M3)
        self.assertEqual(jd._BACKREF_STATS, {"served": 0, "built": 2}, "the write moved the key the second call took")
        self.assertEqual(second, (S2, S2 + ":g2"))
        self.assertIn(first, ((S2, S2 + ":g2"), ("", "")), "what the first walk saw, depending on the read order")

    def test_the_first_sender_in_discover_order_wins(self):
        self.write(S2, {S2 + ":g1": _node(S2 + ":g1", "delegated to worker1", M1)})   # both track M1
        self.assertEqual(jd._handoff_backref(M1), (S1, S1 + ":g1"))
        self.fleet.reverse()
        self.assertEqual(jd._handoff_backref(M1), (S2, S2 + ":g1"), "the order is part of the key and the answer")

    def test_a_completed_handoff_is_no_backref(self):
        self.write(S1, {S1 + ":g1": _node(S1 + ":g1", "delegated to worker0", M1, complete=True)})
        self.assertEqual(jd._handoff_backref(M1), ("", ""))

    def test_a_store_that_raises_leaves_nothing_cached(self):
        real = jd.load_goals_shared

        def faulting(fsid):
            if fsid == S2:
                raise OSError(5, "Input/output error")
            return real(fsid)
        jd.load_goals_shared = faulting
        try:
            with self.assertRaises(OSError):
                jd._handoff_backref(M1)
        finally:
            jd.load_goals_shared = real
        self.assertIsNone(jd._BACKREF_MEMO["slot"])
        self.assertEqual(jd._BACKREF_STATS, {"served": 0, "built": 0})
        self.assertEqual(jd._handoff_backref(M1), (S1, S1 + ":g1"), "healed: built")

    def test_a_rebound_root_forgets_the_map(self):
        jd._handoff_backref(M1)
        self.assertIsNotNone(jd._BACKREF_MEMO["slot"])
        other = tempfile.TemporaryDirectory()
        try:
            jd._rebind_state(Path(other.name))
            self.assertIsNone(jd._BACKREF_MEMO["slot"])
        finally:
            jd._rebind_state(Path(self.td.name))
            other.cleanup()

    def test_the_counters_are_a_copy(self):
        s = jd.backref_memo_stats()
        self.assertEqual(set(s), {"served", "built"})
        s["built"] = 99
        self.assertNotEqual(jd.backref_memo_stats()["built"], 99)


if __name__ == "__main__":
    unittest.main()
