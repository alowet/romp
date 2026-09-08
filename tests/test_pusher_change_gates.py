#!/usr/bin/env python3
"""Change gates on the pusher's idle path (2026-09-08): waiting must not cost CPU.

A profile of an idle devbox kernel (py-spy plus the kernel's own /perf) put most of a core into work whose
inputs had not changed: every comment thread's chat rebuilt per cycle (tests/test_comment_threads.py pins
that gate), the fold prefixes of those threads evicted just before they were rebuilt, the comments stores
re-decoded per cycle, the tasks root re-scanned per build for a session whose store never joins (a negative
memo declared and read but never written), the dormant regs' state tails re-read on every liveness read,
and the working notes re-read on every GET /sessions (polled about once a second by every session's postal
service). Each gate is stat-keyed: an unchanged input costs a stat; a moved input misses exactly.
Synthetic sids and paths; hermetic state."""
import json
import os
import tempfile
import time
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ["ROMP_SERVE_TOKEN"] = "testtok"
jd = SourceFileLoader("romp_judge_gates", os.path.join(BIN, "romp-judge")).load_module()
km = SourceFileLoader("romp_kernel_gates", os.path.join(BIN, "romp-kernel")).load_module()
sb = SourceFileLoader("romp_sdk_backend_gates", os.path.join(BIN, "romp_sdk_backend.py")).load_module()

SID = "11111111-2222-3333-4444-555555555555"


class CommentsStoreMemo(unittest.TestCase):
    def setUp(self):
        km._comments_memo.clear()
        (jd.STATE / "comments").mkdir(parents=True, exist_ok=True)

    def test_decoded_once_per_file_version_and_never_shared(self):
        km._save_comments(SID, {"threads": [{"tid": "t1", "sid": "s1", "status": "open"}]})
        real = km._load_comments
        calls = []
        km._load_comments = lambda sid: (calls.append(sid), real(sid))[1]
        try:
            a = km._load_comments_cached(SID)
            b = km._load_comments_cached(SID)
            self.assertEqual(calls, [SID], "one decode for two reads of the same file version")
            self.assertEqual(a, b)
            a["threads"].append({"tid": "junk"})
            self.assertEqual(len(km._load_comments_cached(SID)["threads"]), 1, "a reader's copy leaks nowhere")
            km._save_comments(SID, {"threads": []})          # a rewrite (a rename) moves the key
            self.assertEqual(km._load_comments_cached(SID)["threads"], [])
            self.assertEqual(len(calls), 2)
        finally:
            km._load_comments = real

    def test_a_missing_store_reads_empty_and_drops_the_memo(self):
        km._save_comments(SID, {"threads": [{"tid": "t1"}]})
        km._load_comments_cached(SID)
        os.unlink(km._comments_path(SID))
        self.assertEqual(km._load_comments_cached(SID), {"threads": []})
        self.assertNotIn(SID, km._comments_memo)

    def test_the_read_only_callers_use_the_memo_and_the_writers_do_not(self):
        import inspect
        self.assertIn("_load_comments_cached(sid)", inspect.getsource(km._comments_frame))
        self.assertIn("_load_comments_cached(sid)", inspect.getsource(km._comment_markers))
        self.assertNotIn("_load_comments_cached", inspect.getsource(km._comment_thread), "writers read fresh")


class TaskJoinMiss(unittest.TestCase):
    """The negative memo _task_store_resolve reads was never written: same fold pairs, the whole tasks root
    re-read on every call. The tasks root sits under the CLAUDE_CONFIG_DIR floor here."""

    def setUp(self):
        km._task_join_miss.clear(); km._task_dir_hint.clear()
        self.root = km._task_store_dir("x").parent
        self.root.mkdir(parents=True, exist_ok=True)
        for name, tasks in (("session-aaaaaaaa", [(1, "alpha")]), ("session-bbbbbbbb", [(2, "beta")])):
            d = self.root / name; d.mkdir(exist_ok=True)
            for i, subj in tasks:
                (d / ("%d.json" % i)).write_text(json.dumps({"id": str(i), "subject": subj}))

    def _root_scans(self, scans):
        return len([s for s in scans if s == str(self.root)])

    def test_a_failed_join_is_remembered_until_the_fold_changes(self):
        fold = [{"id": "7", "subject": "gamma"}]            # in no store: the join fails
        scans = []
        real = os.scandir
        with mock.patch.object(km.os, "scandir", side_effect=lambda p: (scans.append(str(p)), real(p))[1]):
            self.assertIsNone(km._task_store_resolve(SID, fold))
            self.assertEqual(self._root_scans(scans), 1, "the first miss scans the root once")
            self.assertIsNone(km._task_store_resolve(SID, fold))
            self.assertEqual(self._root_scans(scans), 1, "the same fold does not rescan")
            fold2 = [{"id": "7", "subject": "gamma"}, {"id": "8", "subject": "delta"}]
            self.assertIsNone(km._task_store_resolve(SID, fold2))
            self.assertEqual(self._root_scans(scans), 2, "a changed fold rescans")

    def test_a_successful_join_clears_the_miss_memo(self):
        fold = [{"id": "1", "subject": "alpha"}]
        km._task_join_miss[SID] = {("9", "nothing")}
        d = km._task_store_resolve(SID, fold)
        self.assertEqual(d.name, "session-aaaaaaaa")
        self.assertNotIn(SID, km._task_join_miss)


class LastStateMemo(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        (Path(self.td) / "states").mkdir()
        self.p = Path(self.td) / "states" / (SID + ".jsonl")
        sb._LAST_STATE_MEMO.clear()

    def test_the_tail_is_read_once_per_file_version(self):
        self.p.write_text('{"state": "working", "t": 1}\n{"state": "waiting", "t": 2}\n')
        reads = []
        real = sb._lines_from_end
        sb._lines_from_end = lambda p, block=65536: (reads.append(str(p)), real(p, block))[1]
        try:
            a = sb.last_state(Path(self.td), SID)
            b = sb.last_state(Path(self.td), SID)
            self.assertEqual(a, {"state": "waiting", "t": 2}); self.assertEqual(a, b)
            self.assertEqual(len(reads), 1, "the second read is a stat")
            a["state"] = "mutated"
            self.assertEqual(sb.last_state(Path(self.td), SID)["state"], "waiting", "callers get copies")
            with open(self.p, "a") as fh:
                fh.write('{"state": "working", "t": 3}\n')
            self.assertEqual(sb.last_state(Path(self.td), SID)["t"], 3, "an appended record is read")
            self.assertEqual(len(reads), 2)
        finally:
            sb._lines_from_end = real

    def test_a_missing_file_reads_empty_and_forgets(self):
        self.p.write_text('{"state": "waiting", "t": 2}\n')
        sb.last_state(Path(self.td), SID)
        self.p.unlink()
        self.assertEqual(sb.last_state(Path(self.td), SID), {})
        self.assertNotIn(str(self.p), sb._LAST_STATE_MEMO)


class WorkingNotesMemo(unittest.TestCase):
    def setUp(self):
        km._working_notes_memo[0] = None
        km.WORKING_DIR.mkdir(parents=True, exist_ok=True)
        for f in km.WORKING_DIR.iterdir():
            f.unlink()

    def test_read_once_per_directory_version(self):
        (km.WORKING_DIR / SID).write_text("editing the notes API\n")
        real = Path.read_text
        reads = []
        with mock.patch.object(Path, "read_text", lambda self, *a, **k: (reads.append(str(self)), real(self, *a, **k))[1]):
            a = km._working_notes(); b = km._working_notes()
            self.assertEqual(a, {SID: "editing the notes API"}); self.assertEqual(a, b)
            self.assertEqual(len(reads), 1)
            (km.WORKING_DIR / SID).write_text("done, idle\n")
            st = os.stat(km.WORKING_DIR / SID); os.utime(km.WORKING_DIR / SID, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
            self.assertEqual(km._working_notes()[SID], "done, idle")
            (km.WORKING_DIR / SID).unlink()
            self.assertEqual(km._working_notes(), {}, "a removed note is gone at once")


class FoldEvictionKeepsThreads(unittest.TestCase):
    def test_push_keeps_the_fold_prefixes_of_last_cycles_threads(self):
        import inspect
        src = inspect.getsource(km._push)
        self.assertIn("keep = shown_sids | _thread_fold_keep[0]", src)
        self.assertIn("_thread_fold_keep[0], _thread_fold_keep[1] = _thread_fold_keep[1], set()", src)
        self.assertIn("_thread_fold_keep[1].add(tsid)", inspect.getsource(km._thread_events))


if __name__ == "__main__":
    unittest.main()
