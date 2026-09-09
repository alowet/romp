#!/usr/bin/env python3
"""The index tier's caption readers and the re-plan's cleared context read their files once per file state
(2026-09-09): captions/<sid>.jsonl is parsed once and captioned_ids, _live_natoms and session_turn_captions
derive from that parse; goals-archive/<sid>.json is loaded once for readers (load_goal_archive_shared) while
every archiver keeps the fresh loader.

Measured on the maintainer's box (py-spy, the judge tier thread): the three caption readers decoded the whole
file three times per session per index pass (19% of the thread), the archive loader decoded per call (11%).
Pins: parsed once then served; the derived readers equal the direct derivations; an append re-derives, including
one the file clock cannot see; a write landing during the read is served no further than that call; an absent
file is empty and never cached; a malformed line is skipped; the memos are bounded; the archive's writers get a
fresh object; the switched callers; a rebound root forgets; the counters.

Synthetic ids under a private synthetic sid; a temp state root."""
import json
import os
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
jd = SourceFileLoader("romp_judge_file_memos", os.path.join(BIN, "romp-judge")).load_module()

SID = "11111111-2222-3333-4444-666666666601"
T0 = 1781100000


class _Memo(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.saved_root = jd.STATE
        jd._rebind_state(Path(self.td.name))
        jd.CAPDIR.mkdir(parents=True, exist_ok=True)
        jd.GOALARCHDIR.mkdir(parents=True, exist_ok=True)
        self.cap = jd.CAPDIR / (SID + ".jsonl")
        self.arch = jd.GOALARCHDIR / (SID + ".json")
        self._reset()

    def tearDown(self):
        jd._rebind_state(self.saved_root)
        self._reset()
        self.td.cleanup()

    @staticmethod
    def _reset():
        jd._CAPTIONS_MEMO.clear(); jd._GOALARCH_MEMO.clear()
        for d in (jd._CAPTIONS_STATS, jd._GOALARCH_STATS):
            for k in d:
                d[k] = 0

    def append(self, *rows, mtime=None):
        with self.cap.open("a") as f:
            for r in rows:
                f.write((json.dumps(r) if isinstance(r, dict) else r) + "\n")
        if mtime is not None:
            os.utime(self.cap, (mtime, mtime))

    def direct(self):
        """The three answers computed the way the readers used to: three passes over the file."""
        rows = []
        for line in self.cap.read_text(errors="replace").splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
        done = {o["id"] for o in rows if o.get("id") and not o.get("live")}
        live = {}
        for o in rows:
            if o.get("live") and o.get("id"):
                live[o["id"]] = o.get("natoms", 0)
        caps = sorted((o.get("t", 0), o["caption"]) for o in rows if o.get("grain") == "turn" and o.get("caption"))
        return done, live, [c for _, c in caps]

    def counting(self):
        reads, real = [], Path.read_text

        def spy(p, *a, **k):
            if p in (self.cap, self.arch):
                reads.append(p.name)
            return real(p, *a, **k)
        patcher = patch.object(Path, "read_text", spy)
        patcher.start(); self.addCleanup(patcher.stop)
        return reads


class CaptionsMemo(_Memo):
    ROWS = [{"id": SID + ":s1", "grain": "work", "t": T0, "caption": "wired the banner"},
            {"id": SID + ":t1", "grain": "turn", "t": T0 + 5, "caption": "The banner reconnects."},
            {"id": SID + ":s2", "grain": "work", "t": T0 + 20, "caption": "checking the cap", "live": True, "natoms": 8},
            {"id": SID + ":t0", "grain": "turn", "t": T0 - 100, "caption": "An earlier turn."}]

    def test_parsed_once_and_the_three_readers_equal_the_direct_derivations(self):
        self.append(*self.ROWS)
        expected = self.direct()                          # three passes over the file, the way the readers used to
        reads = self.counting()
        got = (jd.captioned_ids(SID), jd._live_natoms(SID), jd.session_turn_captions(SID))
        self.assertEqual(got, expected)
        self.assertEqual(got[0], {SID + ":s1", SID + ":t1", SID + ":t0"}, "live rows are not done")
        self.assertEqual(got[1], {SID + ":s2": 8})
        self.assertEqual(got[2], ["An earlier turn.", "The banner reconnects."], "oldest first")
        self.assertEqual(reads, [SID + ".jsonl"], "one read of the file for three readers")
        self.assertEqual(jd._CAPTIONS_STATS, {"served": 2, "parsed": 1})

    def test_an_append_re_derives_even_when_the_file_clock_does_not_move(self):
        self.append(*self.ROWS[:2])
        self.assertEqual(jd.captioned_ids(SID), {SID + ":s1", SID + ":t1"})
        before = os.stat(self.cap)
        self.append({"id": SID + ":s2", "grain": "work", "t": T0 + 20, "caption": "checking the cap"}, mtime=before.st_mtime)
        self.assertEqual(os.stat(self.cap).st_mtime, before.st_mtime)
        self.assertIn(SID + ":s2", jd.captioned_ids(SID), "the size moved: parsed again")
        self.assertEqual(jd._CAPTIONS_STATS["parsed"], 2)

    def test_a_live_row_superseded_by_its_final_leaves_the_live_map(self):
        self.append({"id": SID + ":s2", "grain": "work", "t": T0, "caption": "working", "live": True, "natoms": 8})
        self.assertEqual((jd.captioned_ids(SID), jd._live_natoms(SID)), (set(), {SID + ":s2": 8}))
        jd.append_caption(SID, SID + ":s2", "work", T0 + 30, "checked the cap")      # the writer everyone uses
        self.assertEqual(jd.captioned_ids(SID), {SID + ":s2"}, "the final record is seen at once")
        self.assertEqual(jd._live_natoms(SID), {SID + ":s2": 8}, "the live row stays until the file says otherwise")

    def test_a_write_landing_during_the_read_is_served_no_further_than_that_call(self):
        # INTERLEAVED WRITE: a row appended while the file is being read. The key was taken before the read,
        # so whatever the first call saw is cached under a stat the file no longer has; the next call re-parses.
        self.append(*self.ROWS[:1])
        real = Path.read_text
        landed = []

        def read_then_write(p, *a, **k):
            data = real(p, *a, **k)
            if p == self.cap and not landed:
                landed.append(True)
                with p.open("a") as f:
                    f.write(json.dumps(self.ROWS[1]) + "\n")
            return data
        with patch.object(Path, "read_text", read_then_write):
            first = jd.captioned_ids(SID)
        self.assertEqual(first, {SID + ":s1"}, "what the read saw")
        self.assertTrue(landed)
        self.assertEqual(jd.captioned_ids(SID), {SID + ":s1", SID + ":t1"}, "the write moved the stat the second call took")
        self.assertEqual(jd._CAPTIONS_STATS, {"served": 0, "parsed": 2})

    def test_an_absent_file_is_empty_and_never_cached(self):
        self.assertEqual((jd.captioned_ids(SID), jd._live_natoms(SID), jd.session_turn_captions(SID)), (set(), {}, []))
        self.assertEqual(jd._CAPTIONS_STATS, {"served": 0, "parsed": 0})
        self.assertNotIn(SID, jd._CAPTIONS_MEMO)
        self.append(*self.ROWS[:1])
        self.assertEqual(jd.captioned_ids(SID), {SID + ":s1"}, "the first row is seen at once")

    def test_a_malformed_or_non_object_line_is_skipped(self):
        self.append(self.ROWS[0], "{not json", "[1, 2]", "42", self.ROWS[1])
        self.assertEqual(jd.captioned_ids(SID), {SID + ":s1", SID + ":t1"})

    def test_the_memo_is_bounded(self):
        saved = jd._FILE_MEMO_MAX
        jd._FILE_MEMO_MAX = 3
        try:
            for i in range(5):
                sid = "11111111-2222-3333-4444-6666666666%02d" % (10 + i)
                (jd.CAPDIR / (sid + ".jsonl")).write_text(json.dumps({"id": sid + ":s1", "grain": "work", "t": T0, "caption": "x"}) + "\n")
                jd.captioned_ids(sid)
            self.assertEqual(len(jd._CAPTIONS_MEMO), 3, "oldest-inserted out at the cap")
            self.assertNotIn("11111111-2222-3333-4444-666666666610", jd._CAPTIONS_MEMO)
        finally:
            jd._FILE_MEMO_MAX = saved


class GoalArchiveMemo(_Memo):
    def _write(self, nodes, mtime=None):
        self.arch.write_text(json.dumps({"rompUuid": SID, "nodes": nodes, "status": {k: "cleared" for k in nodes}}))
        if mtime is not None:
            os.utime(self.arch, (mtime, mtime))

    @staticmethod
    def _node(nid, text):
        return {"id": nid, "text": text, "parentId": None, "nodeComplete": False, "blocked": False,
                "cleared": True, "trail": [], "t": T0}

    def test_loaded_once_then_served_and_the_writers_get_a_fresh_object(self):
        self._write({SID + ":g1": self._node(SID + ":g1", "Ship the banner")})
        reads = self.counting()
        a = jd.load_goal_archive_shared(SID)
        b = jd.load_goal_archive_shared(SID)
        self.assertIs(a, b, "one object, served")
        self.assertEqual(reads, [SID + ".json"])
        self.assertEqual(set(a["nodes"]), {SID + ":g1"})
        self.assertEqual(jd._GOALARCH_STATS, {"served": 1, "loaded": 1})
        w1, w2 = jd.load_goal_archive(SID), jd.load_goal_archive(SID)
        self.assertIsNot(w1, w2); self.assertIsNot(w1, a)
        self.assertEqual(reads.count(SID + ".json"), 3, "an archiver's loader reads fresh every time, as before")

    def test_a_write_re_derives_even_when_the_file_clock_does_not_move(self):
        self._write({SID + ":g1": self._node(SID + ":g1", "Ship the banner")})
        jd.load_goal_archive_shared(SID)
        before = os.stat(self.arch)
        self._write({SID + ":g1": self._node(SID + ":g1", "Ship the banner"),
                     SID + ":g2": self._node(SID + ":g2", "Retire the cap")}, mtime=before.st_mtime)
        self.assertEqual(set(jd.load_goal_archive_shared(SID)["nodes"]), {SID + ":g1", SID + ":g2"})
        self.assertEqual(jd._GOALARCH_STATS["loaded"], 2)

    def test_a_write_landing_during_the_read_is_served_no_further_than_that_call(self):
        self._write({SID + ":g1": self._node(SID + ":g1", "Ship the banner")})
        real = Path.read_text
        landed = []

        def read_then_write(p, *a, **k):
            data = real(p, *a, **k)
            if p == self.arch and not landed:
                landed.append(True)
                self._write({SID + ":g1": self._node(SID + ":g1", "Ship the banner"),
                             SID + ":g2": self._node(SID + ":g2", "Retire the cap")})
            return data
        with patch.object(Path, "read_text", read_then_write):
            first = jd.load_goal_archive_shared(SID)
        self.assertEqual(set(first["nodes"]), {SID + ":g1"})
        self.assertTrue(landed)
        self.assertEqual(set(jd.load_goal_archive_shared(SID)["nodes"]), {SID + ":g1", SID + ":g2"})
        self.assertEqual(jd._GOALARCH_STATS, {"served": 0, "loaded": 2})

    def test_an_absent_archive_is_the_empty_shape_and_never_cached(self):
        a = jd.load_goal_archive_shared(SID)
        self.assertEqual((a["nodes"], a["status"]), ({}, {}))
        self.assertNotIn(SID, jd._GOALARCH_MEMO)
        self.assertEqual(jd._GOALARCH_STATS, {"served": 0, "loaded": 1})

    def test_the_readers_take_the_shared_loader_and_the_archivers_keep_the_fresh_one(self):
        src = open(os.path.join(BIN, "romp-judge")).read()
        self.assertIn('arch = load_goal_archive_shared(fsid).get("nodes", {})', src, "the re-plan's cleared context")
        self.assertIn('arch_nodes = (load_goal_archive_shared(fsid) or {}).get("nodes", {})', src, "the override replay's restore membership")
        self.assertIn('r_nodes = dict(load_goal_archive_shared(h["peer"]).get("nodes") or {})', src)
        self.assertIn('snodes = dict(load_goal_archive_shared(o["peer"]).get("nodes") or {})', src)
        self.assertIn('a = archives[sid] = load_goal_archive_shared(sid)', src, "the propagate pass's per-pass archive map reads")
        for writer in ('        arch = load_goal_archive(fsid)\n        a_nodes = arch.setdefault("nodes", {})',
                       '            arch = load_goal_archive(fsid)\n            for nid in back:'):
            self.assertIn(writer, src, "an archiver loads fresh")

    def test_a_rebound_root_forgets_both_memos(self):
        self.append({"id": SID + ":s1", "grain": "work", "t": T0, "caption": "x"})
        self._write({SID + ":g1": self._node(SID + ":g1", "Ship the banner")})
        jd.captioned_ids(SID); jd.load_goal_archive_shared(SID)
        self.assertTrue(jd._CAPTIONS_MEMO and jd._GOALARCH_MEMO)
        other = tempfile.TemporaryDirectory()
        try:
            jd._rebind_state(Path(other.name))
            self.assertEqual((jd._CAPTIONS_MEMO, jd._GOALARCH_MEMO), ({}, {}))
        finally:
            jd._rebind_state(Path(self.td.name))
            other.cleanup()

    def test_the_counters_are_copies(self):
        for fn in (jd.captions_memo_stats, jd.goal_archive_memo_stats):
            s = fn(); k = next(iter(s)); s[k] = 99
            self.assertNotEqual(fn()[k], 99)


if __name__ == "__main__":
    unittest.main()
