#!/usr/bin/env python3
"""The compaction sweep's unowned ruling is the judge pass's skip list (review find, 2026-09-15).

The pass's pre-pass snapshot (_begin_goals_pass) lists every goals/<sid>.json and decodes each one whose
(ino, mtime_ns, size) key is not in the stat-keyed memo; the compaction sweep after the pass drops the memo
entries of stores no discovered session owns (_goals_memo_evict_unowned). The directory keeps the stores of
sessions gone past the discover window and of old transcript episodes, so the two fought forever: every
pass decoded the orphans as misses and every sweep evicted them again (one kernel: 49 files, 22 owned, 27
orphans of 7 MB; GET /perf memos.pass read hit 202, miss 582, evict 390; 109 store opens and 68 MB read per
5 s with no mtime moving), for stores nothing rendered or judged reads. Now the sweep keeps its ruling in
_goals_memo_unowned and the pass steps over those files before the stat and the open; a consumer that asks
for such a sid gets the live store, as for any sid absent from the snapshot. The owner list the sweep rules
by is the discovered sessions AND the live ones: the feed renders a live session whatever its transcript's
age, so a live session idle past the discover window is not ruled out while liveness reads (the first cut
ruled by discover alone, and would have read such a session live on every build of every pass).

Drives the pass, the eviction and the feed's read directly, over two synthetic stores in a private state
root: an owned session O and an orphan X. The eviction takes its owner list as an argument, exactly as the
sweep hands it, so discover is never walked here. Synthetic fixtures only: placeholder sids private to this
module, invented goal text, no transcripts."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from romp_load import load_source
from unittest import mock

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")

# Hermetic state BEFORE the loads — they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
load_source("romp_event_model", os.path.join(BIN, "romp-event-model"))
load_source("romp_judge", os.path.join(BIN, "romp-judge"))
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "test-token-DO-NOT-USE")
km = load_source("romp_kernel", os.path.join(BIN, "romp-kernel"))
jd = km.jd

# Private synthetic sids (CLAUDE.md, Testing): load_goals replays the per-sid override journal, and node
# ids collide across modules, so a store minted under the shared placeholder sid can be re-flagged by a
# gesture another module journaled against it.
OWNED = "11111111-2222-3333-4444-5555555555a1"      # O: a store a discovered session owns
ORPHAN = "11111111-2222-3333-4444-5555555555a2"     # X: a store no discovered session owns
T0 = 1_750_000_000


def _hosts_off(root):
    """A test that mints its own state root says so (per-session hosts are on by default, T348): no test
    here connects a session, and none may start a host by omission."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "session-hosts").write_text("off\n")


_hosts_off(Path(os.environ["XDG_STATE_HOME"]) / "romp")


class SweepRulingSkipsThePass(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.saved_state = jd.STATE
        jd._rebind_state(Path(self.td.name))           # a private goals directory (and journal) per test
        _hosts_off(Path(self.td.name))
        km._end_goals_pass()                           # never inherit a stuck snapshot…
        km._goals_memo[0] = {}                         # …nor another test's memo entries or ruling
        km._goals_memo_unowned = set()
        for i, sid in enumerate((OWNED, ORPHAN)):
            s = {"rompUuid": sid, "seq": 0, "placementsV": jd.PLACEMENTS_V, "nodes": {},
                 "placements": {}, "status": {}}
            jd.apply_plan(s, "s1", T0, [{"do": "mint", "why": "x", "text": "Goal %d" % i}], [])
            jd.rollup_status(s, session_closed=False)
            jd.save_goals(sid, s)
        # Count decodes at the memo's own hook, not json.loads: the feed's live read and the punch parse too.
        self.real_decode, self.decodes = km._goals_memo_decode, []
        km._goals_memo_decode = lambda data: (self.decodes.append(1), self.real_decode(data))[1]

    def tearDown(self):
        km._goals_memo_decode = self.real_decode
        km._end_goals_pass()
        km._goals_memo[0] = {}
        km._goals_memo_unowned = set()
        jd._rebind_state(self.saved_state)
        self.td.cleanup()

    def _pass(self):
        """Take one pass's snapshot and answer how many stores it decoded. The caller ends the pass."""
        del self.decodes[:]
        km._begin_goals_pass()
        return len(self.decodes)

    def test_the_sweeps_ruling_is_the_next_passs_skip_list(self):
        stats0 = dict(km._goals_memo_stats)
        # (a) a cold pass decodes both stores and the snapshot holds both
        self.assertEqual(self._pass(), 2, "a cold memo decodes both stores")
        self.assertEqual(set(km._goals_snap[0]), {OWNED, ORPHAN})
        km._end_goals_pass()
        # (b) the sweep: only O is owned, so X's entry goes and X is ruled unowned
        self.assertEqual(km._goals_memo_evict_unowned({OWNED}), 1)
        self.assertEqual(km._goals_memo_unowned, {ORPHAN}, "the sweep keeps its ruling")
        self.assertEqual(km._goals_memo_report()["unowned"], 1)
        # (c) the next pass decodes nothing: O is a memo hit and X is stepped over before its stat
        self.assertEqual(self._pass(), 0, "O is a hit and X is stepped over: no decode at all")
        try:
            self.assertEqual(set(km._goals_snap[0]), {OWNED}, "no snapshot entry for the store ruled unowned")
            self.assertNotIn(str(jd.GOALDIR / (ORPHAN + ".json")), km._goals_memo[0], "…and no memo entry")
            self.assertEqual(km._goals_memo_stats["skip"] - stats0["skip"], 1, "…counted as one skip")
            # …and a consumer that asks for X mid-pass gets its store live: nothing is lost
            served = km._feed_goals(ORPHAN)
            self.assertEqual(served["rompUuid"], ORPHAN)
            self.assertEqual([n["text"] for n in served["nodes"].values()], ["Goal 1"])
        finally:
            km._end_goals_pass()
        # (d) a second sweep with the same owner list has nothing left to evict: the churn is gone
        evict0 = km._goals_memo_stats["evict"]
        self.assertEqual(km._goals_memo_evict_unowned({OWNED}), 0)
        self.assertEqual(km._goals_memo_stats["evict"], evict0, "the evict counter did not move")
        self.assertEqual(km._goals_memo_unowned, {ORPHAN}, "…and the ruling stands")
        # (e) X discovered again: that sweep lifts the ruling, and the next pass decodes X, exactly once
        self.assertEqual(km._goals_memo_evict_unowned({OWNED, ORPHAN}), 0)
        self.assertEqual(km._goals_memo_unowned, set(), "a store owned again is no longer ruled out")
        self.assertEqual(self._pass(), 1, "the store owned again is decoded; the other is still a hit")
        try:
            self.assertEqual(set(km._goals_snap[0]), {OWNED, ORPHAN})
        finally:
            km._end_goals_pass()

    def test_the_ruling_is_bounded_by_the_files_present(self):
        # (f) The set never grows past the stores in the directory: a ruled sid whose file is gone leaves at
        # the next sweep, so the process's history of sids is not what bounds it.
        self._pass()
        km._end_goals_pass()
        km._goals_memo_evict_unowned({OWNED})
        self.assertEqual(km._goals_memo_unowned, {ORPHAN})
        (jd.GOALDIR / (ORPHAN + ".json")).unlink()
        self.assertEqual(km._goals_memo_evict_unowned({OWNED}), 0)
        self.assertEqual(km._goals_memo_unowned, set(), "no file, no ruling")
        skip0 = km._goals_memo_stats["skip"]
        self.assertEqual(self._pass(), 0, "O is a hit; there is nothing to step over")
        try:
            self.assertEqual(km._goals_memo_stats["skip"], skip0)
            self.assertEqual(set(km._goals_snap[0]), {OWNED})
        finally:
            km._end_goals_pass()

    def test_the_report_carries_the_skips_and_the_ruling(self):
        # (g) GET /perf memos.pass says how many files a pass stepped over and how many stores stand ruled out.
        report = km._goals_memo_report()
        self.assertIn("skip", report)
        self.assertEqual(report["unowned"], 0)
        self._pass()
        km._end_goals_pass()
        km._goals_memo_evict_unowned({OWNED})
        skip0 = km._goals_memo_report()["skip"]
        self._pass()
        km._end_goals_pass()
        report = km._goals_memo_report()
        self.assertEqual((report["skip"] - skip0, report["unowned"], report["entries"]), (1, 1, 1))

    def test_a_live_session_outside_the_discover_window_is_not_ruled_unowned(self):
        # The sweep as _compact_goal_stores runs it: discover lists nothing (both transcripts idle past the
        # 48 h window), but O is LIVE, so the feed renders it; its store keeps its memo entry and only X is
        # ruled out. Red on the first cut, which ruled by the discover set alone (O evicted and ruled too).
        self._pass()
        km._end_goals_pass()
        with mock.patch.object(jd, "discover", lambda now, window=None, forks=True: []), \
                mock.patch.object(km, "_live_map", lambda: {OWNED: {"state": "idle", "backend": "sdk"}}):
            km._compact_goal_stores()
        self.assertEqual(km._goals_memo_unowned, {ORPHAN}, "a live session is an owner, discovered or not")
        self.assertIn(str(jd.GOALDIR / (OWNED + ".json")), km._goals_memo[0], "…and its store keeps its memo entry")
        self.assertEqual(self._pass(), 0, "O is a hit and X is stepped over")
        try:
            self.assertEqual(set(km._goals_snap[0]), {OWNED})
        finally:
            km._end_goals_pass()
        # a liveness read that raises leaves the discover set as the owner list, said on stderr, never a crash
        err = io.StringIO()
        with mock.patch.object(jd, "discover", lambda now, window=None, forks=True: [(OWNED, "/dev/null", None, "web")]), \
                mock.patch.object(km, "_live_map", side_effect=RuntimeError("registry unreadable")), \
                contextlib.redirect_stderr(err):
            km._compact_goal_stores()
        self.assertEqual(km._goals_memo_unowned, {ORPHAN}, "the discover set alone owns when liveness cannot be read")
        self.assertIn("live map unreadable", err.getvalue())

    def test_the_pass_never_asks_discover(self):
        # The sweep holds the owner list; the pass reads the ruling and stays independent of the walk.
        with mock.patch.object(jd, "discover", side_effect=AssertionError("the pass walked discover")):
            self.assertEqual(self._pass(), 2)
            km._end_goals_pass()
            km._goals_memo_evict_unowned({OWNED})
            self.assertEqual(self._pass(), 0)
            km._end_goals_pass()


if __name__ == "__main__":
    unittest.main()
