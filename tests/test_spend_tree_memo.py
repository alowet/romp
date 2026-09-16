#!/usr/bin/env python3
"""T401 follow-up (2026-09-13): the spend guard listed every alive session's subagents tree WHOLE on the pusher thread in the
boot's first cycle (4.2 s on one boot: 60 trees, 16,752 agent transcripts in 1,542 directories, the largest 2,581 files). The
guard's job skips the boot's first cycle, and the tree memo is persisted (STATE/spend-tree/<sid>.json, written when dirty and at
exit) and loaded lazily when the session's guard first runs, so a boot stats directories and lists nothing until one moves; a
corrupt memo relists; the reads are counted under memos.spendTree. Round two: the load saves the listings, and the one stat per
file that remains (an append while the kernel was down moves no directory's mtime) is spread over the cycles that follow,
hot first, at most SPEND_GUARD_RESTAT_PER_CYCLE a cycle; a memo naming another root or a foreign path is not trusted; the
directory is swept of memos whose leaf is gone; the exit's write retries a dump under the pusher's mutation. Synthetic trees only."""
import json
import os
import threading
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
from test_spend_guard import km, jd   # noqa: E402  the hermetic kernel

SID = "11111111-2222-3333-4444-00000000b401"


def _stats():
    return dict(km._SPEND_TREE_STATS)


class SpendTreeMemo(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(); self.proj = os.path.join(self.td, "proj"); os.makedirs(self.proj)
        self.leaf = os.path.join(self.proj, SID + ".jsonl"); Path(self.leaf).write_text("{}\n")
        self.sub = os.path.join(self.proj, SID, "subagents"); os.makedirs(os.path.join(self.sub, "workflows", "wf_1"))
        self.files = []
        for i in range(6):
            p = os.path.join(self.sub, "agent-%d.jsonl" % i); Path(p).write_text("{}\n"); self.files.append(p)
        for i in range(4):
            p = os.path.join(self.sub, "workflows", "wf_1", "step-%d.jsonl" % i); Path(p).write_text("{}\n"); self.files.append(p)
        old = time.time() - 3600
        for p in self.files + [self.sub, os.path.join(self.sub, "workflows"), os.path.join(self.sub, "workflows", "wf_1")]:
            os.utime(p, (old, old))
        self.saved_state = jd.STATE; jd._rebind_state(Path(tempfile.mkdtemp()))
        km._SPEND_TREE_CACHE.clear()
        for k in km._SPEND_TREE_STATS:
            km._SPEND_TREE_STATS[k] = 0

    def tearDown(self):
        km._SPEND_TREE_CACHE.clear(); jd._rebind_state(self.saved_state)

    def _window(self, since):
        return km._spend_window_files(self.leaf, since, now=time.time())

    def test_a_moved_directory_whose_listing_fails_still_dirties_the_memo(self):
        """1589 low 1: the directory loop assigned the new mtime and left the dirtying to the listing, which marks dirty only when
        its scandir succeeds; a listing that fails left a memo whose recorded mtime moved unwritten (self-repairing, but the
        persisted copy lagged). The assignment dirties."""
        far = time.time() + 10 ** 6
        self._window(far); km._persist_spend_trees(force=True); km._SPEND_TREE_CACHE.clear()
        for _ in range(5):                                                 # the next process loads the memo and drains its re-stat
            self._window(far); km._persist_spend_trees(force=True)         #  list (each drain step dirties and is written): a clean,
        m = list(km._SPEND_TREE_CACHE.values())[0]                         #  drained memo is the starting point
        self.assertNotIn("restat", m); self.assertFalse(m.get("dirty"), "clean and drained before the directory moves")
        now = time.time(); os.utime(self.sub, (now, now))                  # the top directory's mtime moves
        with mock.patch("os.scandir", side_effect=OSError("EIO")):        # and its listing fails
            self._window(far)
        self.assertEqual(m["dirs"][self.sub], os.stat(self.sub).st_mtime, "the moved mtime is recorded")
        self.assertTrue(m.get("dirty"), "and the memo is dirty at the assignment")
        self.assertEqual(km._persist_spend_trees(), 1, "so the persist writes it without force")

    def test_the_persist_stages_under_a_per_writer_tmp_name(self):
        """1589 low 2: the tmp name was per process, so the exit's force write and the pusher's persist on one leaf shared a
        staged file and the unlink on a failed replace could remove the other writer's tmp: pid AND thread id now."""
        far = time.time() + 10 ** 6
        self._window(far)
        seen = []
        real = os.replace
        def capture(a, b): seen.append(str(a)); return real(a, b)
        with mock.patch("os.replace", side_effect=capture):
            self.assertEqual(km._persist_spend_trees(force=True), 1)
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].endswith(".tmp.%d.%x" % (os.getpid(), threading.get_ident())), seen[0])
        self.assertEqual(list(Path(km._spend_tree_path(self.leaf)).parent.glob("*.tmp.*")), [], "no tmp left behind")

    def test_a_boot_with_a_standing_memo_stats_directories_and_lists_no_file(self):
        """The first process lists the tree whole and persists the memo at exit; the next process loads it lazily at the
        session's first guard run and stats the three directories, no listing, no file stat for the cold files."""
        far = time.time() + 10 ** 6                               # a window in the future: every file is cold
        self._window(far)
        s1 = _stats(); self.assertEqual(s1["listings"], 3, "the first process listed the tree: %s" % s1)
        self.assertEqual(km._persist_spend_trees(force=True), 1)
        self.assertTrue(km._spend_tree_path(self.leaf).exists())
        km._SPEND_TREE_CACHE.clear()                              # the next process
        for k in km._SPEND_TREE_STATS:
            km._SPEND_TREE_STATS[k] = 0
        got = self._window(far)
        s2 = _stats()
        self.assertEqual(s2["loaded"], 1, s2)
        self.assertEqual(s2["listings"], 0, "a standing memo lists no file: %s" % s2)
        self.assertEqual(s2["dirStats"], 3, "one stat per directory: %s" % s2)
        self.assertEqual(s2["fileStats"], 10, "every file is statted once after the load (ten here, under the per-cycle bound): %s" % s2)
        self.assertEqual(s2["entryStats"], 0, "and no listing's per-entry stats: %s" % s2)
        self.assertEqual(got, [self.leaf])
        self.assertNotIn("restat", km._SPEND_TREE_CACHE[self.leaf], "the spread re-stat is done")

    def _second_boot(self):
        """The first process lists and persists; the cache is the next process's (empty). The memo carries no rescan epoch
        (the follow-up's low 7: the field on disk was dead and the test's ageing knob inert), so nothing to age."""
        far = time.time() + 10 ** 6
        self._window(far); km._persist_spend_trees(force=True); km._SPEND_TREE_CACHE.clear()
        self.assertNotIn("full", json.loads(km._spend_tree_path(self.leaf).read_text()), "no rescan epoch on disk")
        km._SPEND_TREE_EVICTED_FULL.clear()
        for k in km._SPEND_TREE_STATS:
            km._SPEND_TREE_STATS[k] = 0

    def test_the_re_stat_after_a_load_is_spread_and_finds_a_file_appended_while_the_kernel_was_down(self):
        """Round two, MEDIUM: the loaded memo's full epoch was the previous kernel's last pass, so the first guard cycle
        after a restart statted every file at once (16,752 over 60 trees, the base's count). The re-stat is needed (an
        append moves no directory's mtime) but spread: at most SPEND_GUARD_RESTAT_PER_CYCLE files a cycle, hot first, the
        tree whole within ceil(files / N) cycles, and a file appended during the gap is found by then."""
        coldest = time.time() - 7200                                   # the file to be appended is the COLDEST the memo knows, so
        os.utime(self.files[7], (coldest, coldest))                    #  hot-first puts it last in the spread: found in the third cycle
        self._second_boot()                                            #  (among equal stored mtimes the order is the listing's, which
        now = time.time(); os.utime(self.files[7], (now, now))        #  differs by filesystem: CI found it in the first cycle and then
        since = now - 100                                             #  statted it as hot in two more, 12 not 10; the count below is
        with mock.patch.object(km, "SPEND_GUARD_RESTAT_PER_CYCLE", 4):   #  exact only with the order pinned)
            got1 = km._spend_window_files(self.leaf, since, now=now)
            s1 = _stats()
            self.assertEqual(s1["fileStats"], 4, "the first cycle stats at most N files: %s" % s1)
            self.assertEqual(s1["listings"], 0, "and lists nothing: %s" % s1)
            self.assertEqual(len(km._SPEND_TREE_CACHE[self.leaf]["restat"]), 6, "six remain for the next cycles")
            self.assertEqual(km._SPEND_TREE_CACHE[self.leaf]["restat"][-1], self.files[7], "hot first: the coldest is last")
            self.assertNotIn(self.files[7], got1, "not found yet")
            for _ in range(2):                                        # ceil(10 / 4) = 3 cycles in all
                got = km._spend_window_files(self.leaf, since, now=now)
            s = _stats()
            self.assertEqual(s["fileStats"], 10, "every file statted once by the third cycle: %s" % s)
            self.assertNotIn("restat", km._SPEND_TREE_CACHE[self.leaf], "the spread is spent")
            self.assertIn(self.files[7], got, "the appended file is in the window by then")
            self.assertEqual(km._spend_window_files(self.leaf, since, now=now), got, "and a fourth cycle adds no stat beyond the hot one")
            self.assertEqual(_stats()["fileStats"], 11, "steady state: the one hot file (found, it is hot from then on): %s" % _stats())
        self.assertEqual(got1, [self.leaf])

    def test_a_memo_naming_another_root_is_a_failed_load_and_a_foreign_path_is_dropped(self):
        """Round two, lows 1 and 6: a shaped memo whose dirs do not name this session's root counted loaded and listed
        the tree whole, so the boot read could not tell a healthy load from a stale layout; and a shaped memo's paths were
        trusted wherever they pointed, so a corrupted memo keeping the root plus a foreign live path billed that file."""
        far = time.time() + 10 ** 6
        self._window(far); km._persist_spend_trees(force=True); km._SPEND_TREE_CACHE.clear()
        p = km._spend_tree_path(self.leaf); good = json.loads(p.read_text())
        for k in km._SPEND_TREE_STATS:
            km._SPEND_TREE_STATS[k] = 0
        p.write_text(json.dumps({"dirs": {os.path.join(self.td, "elsewhere", "subagents"): 1.0}, "files": {}, "full": time.time()}))
        self._window(far)
        s = _stats()
        self.assertEqual((s["loaded"], s["loadFailed"], s["listings"]), (0, 1, 3), "another root: a failed load, relisted whole: %s" % s)
        km._SPEND_TREE_CACHE.clear()
        for k in km._SPEND_TREE_STATS:
            km._SPEND_TREE_STATS[k] = 0
        foreign = os.path.join(self.td, "foreign.jsonl"); Path(foreign).write_text("{}\n")
        now = time.time(); os.utime(foreign, (now, now))
        bad = dict(good); bad["files"] = dict(good["files"]); bad["files"][foreign] = now
        bad["dirs"] = dict(good["dirs"]); bad["dirs"][os.path.dirname(foreign)] = now
        p.write_text(json.dumps(bad))
        got = km._spend_window_files(self.leaf, now - 100, now=now)
        s = _stats()
        self.assertEqual(s["loaded"], 1, "the root is named, so the memo loads: %s" % s)
        self.assertNotIn(foreign, got, "a path outside the root is never billed to the session")
        self.assertNotIn(foreign, km._SPEND_TREE_CACHE[self.leaf]["files"])
        self.assertNotIn(os.path.dirname(foreign), km._SPEND_TREE_CACHE[self.leaf]["dirs"])

    def test_an_evicted_memo_reloads_with_its_drain_and_its_rescan_clock(self):
        """Follow-up, low 1: under the byte bound the largest tree was evicted and reloaded every cycle, and both the re-stat
        list and the full epoch were per load, so that tree never drained its cold tail and never ran a full pass. The
        eviction writes the memo with its remaining re-stat list and keeps its rescan clock in memory for the kernel's life;
        the reload continues where it stopped."""
        self._second_boot()
        with mock.patch.object(km, "SPEND_GUARD_RESTAT_PER_CYCLE", 4):
            self._window(time.time() + 10 ** 6)                            # one cycle: four statted, six to go
            m = km._SPEND_TREE_CACHE[self.leaf]; remaining = list(m["restat"]); clock = m["full"]
            self.assertEqual(len(remaining), 6)
            with mock.patch.object(km, "SPEND_GUARD_TREE_MEMO_BYTES", 1):    # a bound one tree cannot fit
                km._spend_tree_memo_prune({self.leaf})
            self.assertNotIn(self.leaf, km._SPEND_TREE_CACHE, "evicted")
            s = _stats(); self.assertEqual(s["evicted"], 1, s)
            doc = json.loads(km._spend_tree_path(self.leaf).read_text())
            self.assertEqual(doc.get("restat"), remaining, "the drain list went to disk with the memo")
            self.assertEqual(km._SPEND_TREE_EVICTED_FULL.get(self.leaf), clock, "the rescan clock stays in memory")
            self._window(time.time() + 10 ** 6)                            # the reload: the next four of the six
            m = km._SPEND_TREE_CACHE[self.leaf]
            self.assertEqual(m["restat"], remaining[4:], "the drain continued where it stopped")
            self.assertEqual(m["full"], clock, "and the full pass keeps its clock")
            self.assertEqual(_stats()["fileStats"], 8, "four and four: %s" % _stats())
            self.assertEqual(km._SPEND_TREE_EVICTED_FULL, {}, "the clock is taken once")

    def test_the_sweep_runs_with_the_ceiling_off_and_the_clock_map_follows_the_file(self):
        """Round two, lows 1 and 2: with the ceiling disabled the guard returned before the sweep, so STATE/spend-tree was never
        swept for that kernel's life; and _SPEND_TREE_EVICTED_FULL had no reaper, so a leaf whose memo file was gone kept its
        clock entry for the life."""
        d = jd.STATE / km._SPEND_TREE_DIR; d.mkdir(parents=True, exist_ok=True)
        gone = os.path.join(self.proj, "22222222-2222-3333-4444-00000000b402.jsonl")
        (d / "22222222-2222-3333-4444-00000000b402.json").write_text(json.dumps({"leaf": gone, "dirs": {}, "files": {}}))
        km._SPEND_TREE_EVICTED_FULL[gone] = 123.0
        with mock.patch.object(km, "_SPEND_TREE_SWEPT", [False]), mock.patch.object(km, "_spend_ceiling", lambda: 0.0):
            km._spend_guard_tick(time.time(), {}, sessions=[], prices={})
        self.assertEqual(_stats()["swept"], 1, "swept with the guard off: %s" % _stats())
        self.assertNotIn(gone, km._SPEND_TREE_EVICTED_FULL, "the clock went with the file")
        km._SPEND_TREE_EVICTED_FULL[self.leaf] = 456.0
        self.assertIsNone(km._spend_tree_load(self.leaf), "no memo file yet")
        self.assertNotIn(self.leaf, km._SPEND_TREE_EVICTED_FULL, "a load that finds nothing drops the clock too")

    def test_a_write_that_raises_is_counted_and_said_once(self):
        """Round two, low 4: except OSError: continue on the memo write was counted nowhere and said nothing."""
        import io
        self._window(time.time() + 10 ** 6)
        p = km._spend_tree_path(self.leaf); p.parent.mkdir(parents=True, exist_ok=True)
        blocker = p.with_name(p.name + ".tmp.%d.%x" % (os.getpid(), threading.get_ident())); blocker.mkdir()   # the tmp path is a
        #                                                                                                   directory: write_text raises
        err = io.StringIO()
        try:
            with mock.patch.object(km, "_SPEND_TREE_WRITE_SAID", [False]), mock.patch.object(km.sys, "stderr", err):
                self.assertEqual(km._persist_spend_trees(force=True), 0)
                self.assertEqual(km._persist_spend_trees(force=True), 0)
        finally:
            blocker.rmdir()
        self.assertEqual(_stats()["writeFailed"], 2, _stats())
        self.assertEqual(err.getvalue().count("could not be written"), 1, "said once a life: %r" % err.getvalue())
        self.assertTrue(km._SPEND_TREE_CACHE[self.leaf].get("dirty"), "the memo stays dirty for the next cycle")

    def test_an_eviction_writes_only_a_dirty_memo(self):
        """Round two, low 5: the eviction wrote the whole memo every time, and on a binding bound it fires every cycle; a drain
        step marks the memo dirty, and an eviction of a memo whose file already holds its state writes nothing."""
        self._second_boot()
        with mock.patch.object(km, "SPEND_GUARD_RESTAT_PER_CYCLE", 100):
            self._window(time.time() + 10 ** 6)                            # the whole drain in one cycle: dirty (the list moved)
            self.assertTrue(km._SPEND_TREE_CACHE[self.leaf].get("dirty"))
            with mock.patch.object(km, "SPEND_GUARD_TREE_MEMO_BYTES", 1):
                km._spend_tree_memo_prune({self.leaf})
            w1 = _stats()["written"]; self.assertEqual(w1, 1, "the dirty memo was written on eviction: %s" % _stats())
            self._window(time.time() + 10 ** 6)                            # the reload: nothing to drain, nothing moved
            self.assertFalse(km._SPEND_TREE_CACHE[self.leaf].get("dirty"))
            with mock.patch.object(km, "SPEND_GUARD_TREE_MEMO_BYTES", 1):
                km._spend_tree_memo_prune({self.leaf})
            self.assertEqual(_stats()["written"], w1, "a clean memo is evicted without a write")
            self.assertEqual(_stats()["evicted"], 2)

    def test_a_file_that_grew_is_carried_to_disk_by_the_eviction_and_the_reload_keeps_it_in_the_window(self):
        """Round three, medium: the dirty-only eviction froze the persisted mtimes: the ordinary stat pass refreshed a grown
        file's mtime in memory without marking the memo dirty, the eviction wrote nothing, and a same-life reload read the old
        mtime, so a transcript that grew was in the window only on the 30 s full-pass cycles and the rate understated between
        them (a latch the full pass set could clear and re-fire). A stat that changes a stored mtime dirties the memo."""
        self._second_boot()
        now = time.time()
        with mock.patch.object(km, "SPEND_GUARD_RESTAT_PER_CYCLE", 100):
            km._spend_window_files(self.leaf, now - 100, now=now)          # the drain: every file statted once, all cold
            with mock.patch.object(km, "SPEND_GUARD_TREE_MEMO_BYTES", 1):
                km._spend_tree_memo_prune({self.leaf})                     # evicted and written (the drain dirtied it)
            w0 = _stats()["written"]
            km._spend_window_files(self.leaf, now - 100, now=now)          # the reload: clean
            self.assertFalse(km._SPEND_TREE_CACHE[self.leaf].get("dirty"))
            grown = self.files[3]; os.utime(grown, (now, now))            # an idle transcript grows
            km._SPEND_TREE_CACHE[self.leaf]["full"] = now - 3600           # the 30 s full pass is due
            got = km._spend_window_files(self.leaf, now - 100, now=now)
            self.assertIn(grown, got, "the full pass finds it in the window")
            self.assertTrue(km._SPEND_TREE_CACHE[self.leaf].get("dirty"), "the stat changed a stored mtime: dirty")
            with mock.patch.object(km, "SPEND_GUARD_TREE_MEMO_BYTES", 1):
                km._spend_tree_memo_prune({self.leaf})                     # the binding bound evicts it again
            self.assertEqual(_stats()["written"], w0 + 1, "the eviction wrote the grown mtime once")
            got = km._spend_window_files(self.leaf, now - 100, now=now)   # the same-life reload
            self.assertIn(grown, got, "the reload keeps the grown file in the window")
            km._spend_window_files(self.leaf, now - 100, now=now)
            self.assertTrue(km._SPEND_TREE_CACHE[self.leaf].get("dirty") is False or _stats()["written"] == w0 + 1,
                            "nothing grew since: nothing more to write")

    def test_a_departed_sessions_rescan_clock_leaves_with_its_memo(self):
        """Round three, low 1: a leaf evicted (its clock in the map) and then departed from the live set kept its clock for the
        life; the non-live prune pops the clock with the cache entry."""
        self._second_boot()
        self._window(time.time() + 10 ** 6)
        with mock.patch.object(km, "SPEND_GUARD_TREE_MEMO_BYTES", 1):
            km._spend_tree_memo_prune({self.leaf})
        self.assertIn(self.leaf, km._SPEND_TREE_EVICTED_FULL)
        km._spend_tree_memo_prune(set())                                   # the session left the live set
        self.assertNotIn(self.leaf, km._SPEND_TREE_EVICTED_FULL, "the clock went with the memo")

    def test_a_failed_replace_leaves_no_tmp_behind(self):
        """Round three, low 2: a failed os.replace left sid.json.tmp.pid until the next kernel's first-tick sweep while the retry
        each cycle rewrote it; the except unlinks the tmp."""
        self._window(time.time() + 10 ** 6)
        p = km._spend_tree_path(self.leaf)
        with mock.patch.object(km.os, "replace", side_effect=OSError("EACCES")):
            self.assertEqual(km._persist_spend_trees(force=True), 0)
        self.assertEqual([x.name for x in p.parent.glob("*.tmp.*")], [], "no tmp left behind")
        self.assertEqual(_stats()["writeFailed"], 1)

    def test_a_partly_foreign_memo_counts_the_paths_it_dropped(self):
        """Follow-up, low 6: paths dropped by the root filter went uncounted, so a partly foreign memo read as a healthy load."""
        far = time.time() + 10 ** 6
        self._window(far); km._persist_spend_trees(force=True); km._SPEND_TREE_CACHE.clear()
        p = km._spend_tree_path(self.leaf); d = json.loads(p.read_text())
        d["files"]["/elsewhere/agent.jsonl"] = 1.0; d["dirs"]["/elsewhere"] = 1.0; p.write_text(json.dumps(d))
        for k in km._SPEND_TREE_STATS:
            km._SPEND_TREE_STATS[k] = 0
        self._window(far)
        s = _stats(); self.assertEqual((s["loaded"], s["dropped"]), (1, 2), s)

    def test_the_exits_write_retries_a_dump_the_pusher_moved_under_it(self):
        """Round two, low 2: the exit's memo write runs from the SIGTERM handler while the pusher may mutate the dicts, so
        json.dumps can raise RuntimeError past the except OSError and skip every later memo; the dump is retried."""
        far = time.time() + 10 ** 6
        self._window(far)
        real = json.dumps; calls = []
        def flaky(obj, *a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("dictionary changed size during iteration")
            return real(obj, *a, **k)
        with mock.patch.object(km.json, "dumps", flaky):
            n = km._persist_spend_trees(force=True)
        self.assertEqual(n, 1, "the memo was written on the retry")
        self.assertEqual(len(calls), 2)
        self.assertEqual(json.loads(km._spend_tree_path(self.leaf).read_text())["leaf"], self.leaf, "the memo names its leaf")

    def test_three_lost_dumps_are_counted_and_said_once(self):
        """Follow-up, low 2: three failed json.dumps attempts were silent (no log, no counter)."""
        import io
        self._window(time.time() + 10 ** 6)
        def always(obj, *a, **k):
            raise RuntimeError("dictionary changed size during iteration")
        err = io.StringIO()
        with mock.patch.object(km.json, "dumps", always), mock.patch.object(km, "_SPEND_TREE_DUMP_SAID", [False]), \
             mock.patch.object(km.sys, "stderr", err):
            self.assertEqual(km._persist_spend_trees(force=True), 0)
            self.assertEqual(km._persist_spend_trees(force=True), 0)
        self.assertEqual(_stats()["dumpSkipped"], 2, _stats())
        self.assertEqual(err.getvalue().count("tree memo's write was skipped"), 1, "said once a life: %r" % err.getvalue())

    def test_the_first_persist_sweeps_memos_whose_leaf_is_gone(self):
        """Round two, low 3: STATE/spend-tree had no reaper, so a memo outlived its session forever (0.73 MB for the largest
        tree); the first persist of a kernel life removes the memos whose leaf no longer exists, the checkpoint sweep's shape."""
        d = jd.STATE / km._SPEND_TREE_DIR; d.mkdir(parents=True)
        gone = os.path.join(self.proj, "22222222-2222-3333-4444-00000000b402.jsonl")
        (d / "22222222-2222-3333-4444-00000000b402.json").write_text(json.dumps({"leaf": gone, "dirs": {}, "files": {}, "full": 0}))
        (d / "33333333-2222-3333-4444-00000000b403.json").write_text(json.dumps({"dirs": {}, "files": {}, "full": 0}))   # no leaf named
        (d / "44444444-2222-3333-4444-00000000b404.json").write_text("{not json")
        (d / (SID + ".json.tmp.4242")).write_text("{")                     # a tmp a kill left between write and replace (low 3)
        far = time.time() + 10 ** 6
        self._window(far)
        with mock.patch.object(km, "_SPEND_TREE_SWEPT", [False]):
            km._persist_spend_trees(force=True)
            self.assertEqual(_stats()["swept"], 0, "the persist job no longer sweeps (the sweep parses every memo): %s" % _stats())
            km._spend_guard_tick(time.time(), {}, sessions=[], prices={})   # the guard's first tick of the life sweeps
            self.assertEqual(_stats()["swept"], 4, "the gone, the unnamed, the corrupt and the tmp: %s" % _stats())
            self.assertEqual(sorted(x.name for x in d.iterdir()), [SID + ".json"], "the live session's memo stands, the tmp is gone")
            km._spend_guard_tick(time.time(), {}, sessions=[], prices={})
            self.assertEqual(_stats()["swept"], 4, "once per kernel life")

    def test_a_fresh_listing_counts_its_per_entry_stats(self):
        """Round two, low 5: a listing's per-entry stats (one per DirEntry) went uncounted, so a fresh listing reported
        listings 343, fileStats 0 while performing about 2,900 stats."""
        self._window(time.time() + 10 ** 6)
        s = _stats()
        self.assertEqual((s["listings"], s["entryStats"]), (3, 12), "ten files and two subdirectories: %s" % s)

    def test_a_directory_whose_mtime_moved_is_relisted_alone(self):
        far = time.time() + 10 ** 6
        self._window(far); km._persist_spend_trees(force=True); km._SPEND_TREE_CACHE.clear()
        for k in km._SPEND_TREE_STATS:
            km._SPEND_TREE_STATS[k] = 0
        Path(os.path.join(self.sub, "workflows", "wf_1", "step-9.jsonl")).write_text("{}\n")   # the deepest directory moves
        self._window(far)
        s = _stats()
        self.assertEqual(s["listings"], 1, "the moved directory alone was relisted: %s" % s)
        self.assertIn(os.path.join(self.sub, "workflows", "wf_1", "step-9.jsonl"), km._SPEND_TREE_CACHE[self.leaf]["files"])

    def test_a_corrupt_memo_relists_and_is_counted(self):
        far = time.time() + 10 ** 6
        self._window(far); km._persist_spend_trees(force=True); km._SPEND_TREE_CACHE.clear()
        for k in km._SPEND_TREE_STATS:
            km._SPEND_TREE_STATS[k] = 0
        km._spend_tree_path(self.leaf).write_text("{not json")
        self._window(far)
        s = _stats()
        self.assertEqual((s["loadFailed"], s["listings"]), (1, 3), "a corrupt memo is relisted whole, never raised: %s" % s)
        km._spend_tree_path(self.leaf).write_text(json.dumps({"dirs": {"x": "not a number"}, "files": {}}))
        km._SPEND_TREE_CACHE.clear(); self._window(far)
        self.assertEqual(_stats()["loadFailed"], 2, "a misshapen memo too")

    def test_the_perf_memos_carry_the_reads(self):
        rep = km._spend_tree_memo_report()
        self.assertEqual(set(rep), {"entries", "bytes", "bound", "served", "dirStats", "fileStats", "entryStats", "listings", "loaded", "loadFailed",
                                    "written", "swept", "dropped", "dumpSkipped", "evicted", "writeFailed"})


class FirstCycleGate(unittest.TestCase):
    """The guard's job and the boot's first cycle, driven through whole pusher cycles (no tree fixture: this class must
    collect and run at a base that has no tree memo at all, so its red is the gate's absence and nothing else)."""

    def test_the_boots_first_pass_carries_no_guard_listing(self):
        """Two whole passes of the jobs thread (the guard's home since the housekeeping split, 2026-09-13) with the pass
        counter floored at zero: the guard ran zero times after pass one and once after pass two (round two, low 4:
        behavioural, not a source pin)."""
        calls = []
        with mock.patch.object(km, "_spend_guard_tick", side_effect=lambda now, live_map: calls.append(now)), \
             mock.patch.dict(km._PERF_STATS.jobs, {"passes": 0}):
            km._jobs_cycle()
            self.assertEqual(len(calls), 0, "the boot's first pass runs no guard")
            self.assertEqual(km._PERF_STATS.jobs.get("passes"), 1, "the pass counted itself")
            km._jobs_cycle()
            self.assertEqual(len(calls), 1, "the second pass runs it")
        import inspect
        self.assertIn("_persist_spend_trees(force=True)", inspect.getsource(km._drain_and_exit), "the memo is written at exit too")


if __name__ == "__main__":
    unittest.main()
