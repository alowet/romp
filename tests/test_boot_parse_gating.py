#!/usr/bin/env python3
"""T323 stage 1 (the user 2026-09-10): a kernel boot must not read every live transcript whole for nobody. The boot
warm parses nothing (it warms discover() only), the feed-only warm parses only sessions that moved since this boot or
are working now, the judges' passes go newest-first and yield between sessions, the two event-keyed tick jobs skip a
session whose transcript and state log are unchanged since their last look (the boot being the first baseline), and
/perf counts every cold parse so the effect is measurable. Hermetic: synthetic files under a temp root, the kernel and
judge loaded against a temp state directory, threads joined explicitly."""
import inspect
import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from romp_load import load_source

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
load_source("romp_event_model", os.path.join(BIN, "romp-event-model"))
jd = load_source("romp_judge", os.path.join(BIN, "romp-judge"))
km = load_source("romp_kernel_t323s1", os.path.join(BIN, "romp-kernel"))

SID_OLD = "11111111-2222-4333-8444-000000000001"
SID_NEW = "22222222-2222-4333-8444-000000000002"
SID_WORK = "33333333-2222-4333-8444-000000000003"
SID_T3 = "44444444-2222-4333-8444-0000000000b3"        # the interrupt key test's own sids (T401 (3))
SID_GONE = "66666666-2222-4333-8444-000000000006"      # the warm loop's leaf gate: a working row, no transcript on disk
SID_T3_OTHER = "55555555-2222-4333-8444-0000000000b4"


def _threads():
    return set(threading.enumerate())


def _join_new(before, timeout=10):
    for t in _threads() - before:
        t.join(timeout)


def _row(d, sid, old):
    """A session row whose transcript (and state log) predate or postdate this kernel's start."""
    p = Path(d) / (sid + ".jsonl")
    p.write_text(json.dumps({"type": "user", "uuid": sid[:8], "timestamp": "2026-09-10T00:00:00Z", "message": {"role": "user", "content": "x"}}) + "\n")
    t = km._STARTED - 600 if old else time.time() + 1
    os.utime(p, (t, t))
    return {"sid": sid, "path": str(p), "name": sid[:8], "mtime": t}


class BootWarmParsesNothing(unittest.TestCase):
    def test_discover_only(self):
        calls = {"discover": 0, "parse": 0}
        before = _threads()
        with mock.patch.object(km.jd, "discover", side_effect=lambda now, **k: calls.__setitem__("discover", calls["discover"] + 1) or []), \
             mock.patch.object(km, "_parse", side_effect=lambda *a, **k: calls.__setitem__("parse", calls["parse"] + 1)), \
             mock.patch.object(km, "_alive_sessions", side_effect=lambda now, live_map: [{"sid": SID_OLD, "path": "/nonexistent", "name": "web"}]):
            km._boot_warm()
            _join_new(before)
        self.assertEqual(calls["discover"], 1, "the shared discover cache is still warmed")
        self.assertEqual(calls["parse"], 0, "no transcript is parsed for nobody (the redial road parses the active tab itself)")
        src = inspect.getsource(km._boot_warm)
        self.assertNotIn("_parse(", src, "the warm's body calls no parse")
        self.assertIn("PARSES NOTHING", src)


class FeedWarmParsesOnlyWhatMoved(unittest.TestCase):
    def test_a_warm_that_parses_nothing_wakes_nobody(self):
        """Review find: with a feed-only window and an idle unmoved session, the warm used to invalidate the feed
        and wake the pusher every cycle though it parsed nothing (a whole-feed rebuild per cycle for ever)."""
        d = tempfile.mkdtemp()
        rows = [_row(d, SID_OLD, old=True)]
        pokes = []
        before = _threads()
        km._warming[0] = False
        saved = list(km._clients)
        with km._clients_lock:
            km._clients[:] = [{"app": "feed", "send": lambda s: None, "sent": {}, "alive": True}]
        self.addCleanup(lambda: km._clients.__setitem__(slice(None), saved))
        km._built_feed[1] = "a built payload"
        with mock.patch.object(km, "_alive_sessions", side_effect=lambda now, live_map: rows), \
             mock.patch.object(km, "_live_map", side_effect=lambda: {}), \
             mock.patch.object(km, "_has_parsing_client", side_effect=lambda: False), \
             mock.patch.object(km, "_parse", side_effect=lambda path, sid, now: None), \
             mock.patch.object(km, "_push_soon", side_effect=lambda: pokes.append(1)):
            km._warm_fleet_bg(int(time.time()))
            _join_new(before)
        self.assertEqual(km._built_feed[1], "a built payload", "the feed cache is left alone")
        self.assertEqual(pokes, [], "and the pusher is not woken")
        src = inspect.getsource(km._feed_session_entry)
        self.assertIn("if _warm_wanted(s, tm):", src, "build_feed asks for a warm only for a session the gate would parse")
        self.assertFalse(km._warm_wanted(rows[0], None), "an unmoved idle session is cold by design")
        self.assertTrue(km._warm_wanted(rows[0], {"state": "working"}))

    def test_a_warm_that_skipped_a_leaf_it_cannot_stat_drops_nothing_and_wakes_nobody(self):
        """The loop's leaf gate sits AHEAD of the parsed-anything flag (the post-merge review of the leaf_ok gate,
        2026-09-21). A working live row whose transcript is not on disk is warm-wanted on the state leg (a missing
        file's stat is zeros, so the moved-since-boot leg cannot hold for it), and the warm must skip it without a
        parse and then, having parsed nothing, leave the feed cache and the pusher alone. Two mutants this pins: the
        gate absent (the missing path is parsed, the cache drops, the pusher wakes) and the gate moved below the flag
        (no parse, but the cache still drops and the pusher still wakes)."""
        d = tempfile.mkdtemp()
        gone = {"sid": SID_GONE, "path": str(Path(d) / (SID_GONE + ".jsonl")), "name": SID_GONE[:8], "mtime": 0}
        self.assertFalse(os.path.exists(gone["path"]), "the transcript was never written")
        self.assertTrue(km._warm_wanted(gone, {"state": "working"}), "a working row is warm-wanted on the state leg")
        parsed, pokes = [], []
        before = _threads()
        km._warming[0] = False
        saved, saved_feed = list(km._clients), list(km._built_feed)
        with km._clients_lock:
            km._clients[:] = [{"app": "feed", "send": lambda s: None, "sent": {}, "alive": True}]
        self.addCleanup(lambda: km._clients.__setitem__(slice(None), saved))
        self.addCleanup(lambda: km._built_feed.__setitem__(slice(None), saved_feed))
        km._built_feed[1] = "a built payload"
        with mock.patch.object(km, "_alive_sessions", side_effect=lambda now, live_map: [gone]), \
             mock.patch.object(km, "_live_map", side_effect=lambda: {SID_GONE: {"state": "working"}}), \
             mock.patch.object(km, "_has_parsing_client", side_effect=lambda: False), \
             mock.patch.object(km, "_parse", side_effect=lambda path, sid, now: parsed.append(path)), \
             mock.patch.object(km, "_push_soon", side_effect=lambda: pokes.append(1)):
            km._warm_fleet_bg(int(time.time()))
            _join_new(before)
        self.assertEqual(parsed, [], "a leaf the warm thread cannot stat is never handed to _parse")
        self.assertEqual(km._built_feed[1], "a built payload", "a warm that skipped everything leaves the cache alone")
        self.assertEqual(pokes, [], "and wakes nobody")

    def test_moved_or_working_only(self):
        d = tempfile.mkdtemp()
        rows = [_row(d, SID_OLD, old=True), _row(d, SID_NEW, old=False), _row(d, SID_WORK, old=True)]
        parsed = []
        before = _threads()
        km._warming[0] = False
        saved = list(km._clients)
        with km._clients_lock:                                   # the warm is a no-op with nobody connected: a feed-only window
            km._clients[:] = [{"app": "feed", "send": lambda s: None, "sent": {}, "alive": True}]
        self.addCleanup(lambda: km._clients.__setitem__(slice(None), saved))
        with mock.patch.object(km, "_alive_sessions", side_effect=lambda now, live_map: rows), \
             mock.patch.object(km, "_live_map", side_effect=lambda: {SID_WORK: {"state": "working"}}), \
             mock.patch.object(km, "_has_parsing_client", side_effect=lambda: False), \
             mock.patch.object(km, "_parse", side_effect=lambda path, sid, now: parsed.append(sid)):
            km._warm_fleet_bg(int(time.time()))
            _join_new(before)
        self.assertEqual(sorted(parsed), sorted([SID_NEW, SID_WORK]),
                         "the session that moved since boot and the one working now; the untouched one waits for a client")

    def test_moved_since_boot_reads_either_file(self):
        d = tempfile.mkdtemp()
        r = _row(d, SID_OLD, old=True)
        self.assertFalse(km._session_moved_since_boot(r))
        states = km.jd.STATE / "states"
        states.mkdir(parents=True, exist_ok=True)
        (states / (SID_OLD + ".jsonl")).write_text(json.dumps({"t": int(time.time()), "state": "waiting"}) + "\n")
        self.assertTrue(km._session_moved_since_boot(r), "a state-log append after the boot counts as movement")
        (states / (SID_OLD + ".jsonl")).unlink()


class TickJobsKeyOnAChange(unittest.TestCase):
    """The event-keyed tick jobs' memo: a session is evaluated once when no kernel on record has looked at it,
    skipped while its keyed files (the transcript, the state log, the store and its journal and archive, the four logs) match the last COMPLETED look, and evaluated again on
    any change; the memo persists across kernels, so a stop that landed in the gap between the previous kernel's
    last tick and this boot is evaluated (review find, 2026-09-10), while a session settled before the restart
    and untouched since is not parsed again."""

    def setUp(self):
        km._TICK_SEEN.clear()
        km._TICK_SEEN_DIRTY[0] = False
        p = km._tick_seen_path()
        if p.exists():
            p.unlink()

    def test_first_look_evaluates_then_a_completed_look_skips_until_a_change(self):
        d = tempfile.mkdtemp()
        r = _row(d, SID_OLD, old=True)                    # mtime BEFORE this kernel's start: no longer a reason to skip
        skip, st = km._tick_job_check("interrupt-block", r)
        self.assertFalse(skip, "no kernel on record has looked at it: evaluate once, whatever the mtime")
        self.assertFalse(km._tick_job_skips("interrupt-block", r), "not yet marked done (a fault mid-tick): the next tick evaluates again")
        km._tick_job_done("interrupt-block", r, st)
        self.assertTrue(km._tick_job_skips("interrupt-block", r), "once the evaluation completed, the same files skip")
        with open(r["path"], "a") as f:
            f.write(json.dumps({"type": "assistant", "uuid": "a1"}) + "\n")
        os.utime(r["path"], None)
        skip, st = km._tick_job_check("interrupt-block", r)
        self.assertFalse(skip, "an appended record is the event: evaluate")
        km._tick_job_done("interrupt-block", r, st)
        self.assertTrue(km._tick_job_skips("interrupt-block", r))

    def test_a_failed_persist_leaves_no_tmp_re_arms_the_dirty_flag_and_says_it_once(self):
        """1603 low 1: the tick-seen persist took only the tmp NAME from the marks persist; on a failed replace it left the tmp
        on disk, left the memo clean (never written again until something else dirtied it) and said nothing. The three
        things the precedent does: unlink the tmp, re-arm dirty, say it once."""
        d = tempfile.mkdtemp()
        r = _row(d, SID_OLD, old=True)
        skip, st = km._tick_job_check("interrupt-block", r); km._tick_job_done("interrupt-block", r, st)
        p = km._tick_seen_path(); p.parent.mkdir(parents=True, exist_ok=True)
        err = io.StringIO()
        def broken_replace(a, b):                                          # the fault on the REPLACE (1610 round three, medium 3):
            raise OSError("EIO: replace refused")                          #  the tmp was written, so the unlink leg has power
        with mock.patch.object(km, "_TICK_SEEN_WRITE_SAID", [False]), mock.patch.object(km.sys, "stderr", err), \
             mock.patch("os.replace", side_effect=broken_replace):
            self.assertFalse(km._persist_tick_seen(), "the replace failed")
            with km._TICK_SEEN_LOCK:
                self.assertTrue(km._TICK_SEEN_DIRTY[0], "the memo is dirty again: the next persist retries")
            self.assertEqual(list(p.parent.glob(p.name + ".tmp.*")), [], "the written tmp was unlinked")
            self.assertFalse(km._persist_tick_seen(), "still failing")
            self.assertEqual(list(p.parent.glob(p.name + ".tmp.*")), [], "and unlinked again")
        self.assertEqual(err.getvalue().count("tick-seen memo: not written"), 1, "said once: %r" % err.getvalue())
        self.assertTrue(km._persist_tick_seen(), "the fault gone: the retried persist writes")

    def test_an_unserializable_entry_raises_with_the_flag_still_dirty_and_is_said_once(self):
        """1610 round two, medium 3: json.dumps sat after the flag cleared, so an unserializable entry raised with the memo left
        clean and no later persist retried. The dumps runs before the clear; the failure is said once; the memo stays dirty."""
        d = tempfile.mkdtemp()
        r = _row(d, SID_OLD, old=True)
        skip, st = km._tick_job_check("interrupt-block", r); km._tick_job_done("interrupt-block", r, st)
        key = ("interrupt-block", "99999999-2222-4333-8444-0000000000b9")
        err = io.StringIO()
        with km._TICK_SEEN_LOCK:
            km._TICK_SEEN[key] = [{1, 2}]                                   # a set inside the entry: not JSON
        try:
            with mock.patch.object(km, "_TICK_SEEN_WRITE_SAID", [False]), mock.patch.object(km.sys, "stderr", err):
                with self.assertRaises(TypeError):
                    km._persist_tick_seen()
                with km._TICK_SEEN_LOCK:
                    self.assertTrue(km._TICK_SEEN_DIRTY[0], "the flag is still dirty: the next persist retries")
                with self.assertRaises(TypeError):
                    km._persist_tick_seen()
                self.assertEqual(err.getvalue().count("tick-seen memo: not serialized"), 1, "said once: %r" % err.getvalue())
        finally:
            with km._TICK_SEEN_LOCK:
                km._TICK_SEEN.pop(key, None)
        self.assertTrue(km._persist_tick_seen(), "the entry gone: the retried persist writes")

    def test_the_say_once_latch_re_arms_on_a_clean_write(self):
        """1610 round two, low 8: the latch never re-armed, so a second fault episode hours later was silent."""
        d = tempfile.mkdtemp()
        r = _row(d, SID_OLD, old=True)
        p = km._tick_seen_path(); p.parent.mkdir(parents=True, exist_ok=True)
        blocker = p.with_name(p.name + ".tmp.%d.%x" % (os.getpid(), threading.get_ident()))
        err = io.StringIO()
        with mock.patch.object(km, "_TICK_SEEN_WRITE_SAID", [False]), mock.patch.object(km.sys, "stderr", err):
            skip, st = km._tick_job_check("interrupt-block", r); km._tick_job_done("interrupt-block", r, st)
            blocker.mkdir(); self.assertFalse(km._persist_tick_seen()); blocker.rmdir()      # episode one
            self.assertTrue(km._persist_tick_seen(), "a clean write")
            km._tick_job_done("interrupt-block", r, st)
            blocker.mkdir(); self.assertFalse(km._persist_tick_seen()); blocker.rmdir()      # episode two, hours later
        self.assertEqual(err.getvalue().count("tick-seen memo: not written"), 2, "each episode said once: %r" % err.getvalue())

    def test_the_jobs_pass_persists_each_memo_on_its_own(self):
        """1610 low 2: the per-cycle persist road on the jobs thread had no pin; the exit drain's has one. Each persist stage
        in its own try, the failure written under its own name."""
        import inspect
        src = inspect.getsource(km._jobs_pass)
        for stage, name in (("persistTickSeen", "tick-seen"), ("persistIntrMarks", "interrupt-marks"), ("persistSpendTrees", "spend-tree")):
            i = src.index("_job_stage('%s'" % stage)
            tail = src[i:i + 400]
            self.assertIn('sys.stderr.write("%s: %%s\\n" %% traceback.format_exc())' % name, tail, "%s is logged under its own name" % stage)
        a, b, c = (src.index("_job_stage('%s'" % s_) for s_ in ("persistTickSeen", "persistIntrMarks", "persistSpendTrees"))
        self.assertIn("except Exception", src[a:b], "tick-seen's try closes before the marks persist")
        self.assertIn("except Exception", src[b:c], "the marks persist's try closes before the spend-tree persist")

    def test_the_exit_drain_persists_each_memo_on_its_own(self):
        """1610 round two, medium 3: the exit drain wrapped the three persists in one bare except, so one memo's raise silently
        cost the other two. A source pin: each persist in its own try, the failure logged by name."""
        import inspect
        src = inspect.getsource(km._drain_and_exit)
        for name in ("tick-seen", "interrupt-marks", "spend-tree", "planner-seen"):
            self.assertIn('_exit_log("romp-kernel: the %s memo was not persisted at exit' % name, src, name)
        self.assertEqual(src.count('    except Exception as _e:\n        _exit_log("romp-kernel: the '), 4, "each persist in its own try")
        self.assertNotIn("        _persist_tick_seen(force=True)\n        _persist_intr_marks(force=True)", src, "no shared try")

    def test_the_memo_persists_and_the_next_kernel_starts_from_it(self):
        d = tempfile.mkdtemp()
        settled = _row(d, SID_OLD, old=True)             # settled by the previous kernel, untouched since
        moved = _row(d, SID_NEW, old=True)               # settled, then moved in the gap before this boot
        skip, st = km._tick_job_check("interrupt-block", settled); km._tick_job_done("interrupt-block", settled, st)
        skip, st = km._tick_job_check("interrupt-block", moved); km._tick_job_done("interrupt-block", moved, st)
        seen = []; real = os.replace
        def capture(a, b): seen.append(str(a)); return real(a, b)
        with mock.patch("os.replace", side_effect=capture):
            self.assertTrue(km._persist_tick_seen(), "dirty → written")
        self.assertTrue(seen and seen[0].endswith(".tmp.%d.%x" % (os.getpid(), threading.get_ident())),
                        "staged under a per-WRITER tmp (pid and thread id): the exit's force write runs beside the pusher's (1589 low 2): %r" % seen)
        self.assertFalse(km._persist_tick_seen(), "clean → nothing to write")
        # the gap: a stop lands in `moved` after the previous kernel's last tick, before this boot (mtime still < _STARTED)
        with open(moved["path"], "a") as f:
            f.write(json.dumps({"type": "user", "uuid": "u9", "message": {"role": "user", "content": "[Request interrupted by user]"}}) + "\n")
        os.utime(moved["path"], (km._STARTED - 60, km._STARTED - 60))
        # the next kernel: an empty memo, then the persisted one
        km._TICK_SEEN.clear()
        self.assertEqual(km._load_tick_seen(), 2)
        self.assertTrue(km._tick_job_skips("interrupt-block", settled), "unchanged since the previous kernel's look: the store's verdict stands, no parse")
        self.assertFalse(km._tick_job_skips("interrupt-block", moved), "moved in the gap before the boot: evaluated, whatever _STARTED says")

    def test_a_goal_store_write_is_an_event_too(self):
        """A judge can clear or complete the goal a marker points at without a transcript change; the interrupt
        tick must re-evaluate on that alone (its stale-marker rule)."""
        d = tempfile.mkdtemp()
        r = _row(d, SID_OLD, old=True)
        skip, st = km._tick_job_check("interrupt-block", r); km._tick_job_done("interrupt-block", r, st)
        self.assertTrue(km._tick_job_skips("interrupt-block", r))
        km.jd.GOALDIR.mkdir(parents=True, exist_ok=True)
        (km.jd.GOALDIR / (SID_OLD + ".json")).write_text("{}")
        try:
            skip, st = km._tick_job_check("interrupt-block", r)
            self.assertFalse(skip, "the store moved: evaluate")
            km._tick_job_done("interrupt-block", r, st)
            self.assertTrue(km._tick_job_skips("interrupt-block", r))
        finally:
            (km.jd.GOALDIR / (SID_OLD + ".json")).unlink()

    def test_a_missing_transcript_is_unknown_never_unchanged(self):
        r = {"sid": SID_OLD, "path": "/nonexistent-t323.jsonl", "name": "web"}
        skip, st = km._tick_job_check("interrupt-block", r)
        self.assertFalse(skip, "a row whose transcript cannot be read is evaluated (the fault-boundary tests build such rows)")
        km._tick_job_done("interrupt-block", r, st)
        self.assertFalse(km._tick_job_skips("interrupt-block", r), "and stays evaluated every tick until a file exists")

    def test_the_memo_counts_why_it_re_evaluated_by_key_position(self):
        """The boot follow-up (2026-09-13): the measurement boot re-parsed every session in the interrupt tick (38 s) and the key
        position that had moved could not be named after the fact. Every check counts under memos.tickSeen: hits, misses,
        neverSeen, noTranscript, and missBy[job][file] for each position that differed on a miss, in _session_files_stat's
        order (the ten files, then askerRow, then shape for a key of another length)."""
        d = tempfile.mkdtemp()
        r = _row(d, SID_OLD, old=True)
        def snap(job="interrupt-block"):
            rep = km._tick_seen_report().get("byJob", {}).get(job) or {"hits": 0, "misses": 0, "neverSeen": 0, "noTranscript": 0, "clockParse": 0, "missBy": {}}
            return {k: rep[k] for k in ("hits", "misses", "neverSeen", "noTranscript", "clockParse")}, {"interrupt-block": rep["missBy"]}
        def delta(by0, by1, job="interrupt-block"):                     # the counters are cumulative for the module: deltas
            a, b = by0.get(job, {}), by1.get(job, {})
            return {k: b.get(k, 0) - a.get(k, 0) for k in set(a) | set(b) if b.get(k, 0) != a.get(k, 0)}
        c0, by0 = snap()
        skip, st = km._tick_job_check("interrupt-block", r)
        c1, _ = snap(); self.assertEqual(c1["neverSeen"] - c0["neverSeen"], 1, "a session no kernel had looked at")
        km._tick_job_done("interrupt-block", r, st)
        self.assertTrue(km._tick_job_skips("interrupt-block", r))
        c2, _ = snap(); self.assertEqual(c2["hits"] - c1["hits"], 1)
        led = km.jd.STATE / "auto-nudge.json"; led.parent.mkdir(parents=True, exist_ok=True)
        led.write_text(json.dumps({"enabled": True, "nudged": {}, "walkGates": {}, "t": time.time()}))   # the ledger moved: position ten
        os.utime(led, (time.time() + 5, time.time() + 5))
        skip, st = km._tick_job_check("interrupt-block", r)
        self.assertFalse(skip)
        c3, by3 = snap(); self.assertEqual(c3["misses"] - c2["misses"], 1)
        self.assertEqual(delta(by0, by3), {"ledger": 1}, "the ledger is the one position that moved: %r" % delta(by0, by3))
        km._tick_job_done("interrupt-block", r, st)
        with open(r["path"], "a") as f:
            f.write(json.dumps({"type": "assistant", "uuid": "a2"}) + "\n")
        os.utime(r["path"], (time.time() + 9, time.time() + 9))
        km._tick_job_check("interrupt-block", r)
        _, by4 = snap(); self.assertEqual(delta(by3, by4), {"transcript": 1}, delta(by3, by4))
        self.assertEqual(list(km._TICK_KEY_FILES), ["transcript", "states", "store", "overrides", "archive", "episode", "cleared",
                                                    "messages", "downtime", "ledger"], "the order the reference names")
        bad = {"sid": SID_NEW, "path": "/nonexistent-t401.jsonl", "name": "web"}
        km._tick_job_check("interrupt-block", bad)
        c4, _ = snap(); self.assertEqual(c4["noTranscript"] - c3["noTranscript"], 1)
        self.assertIn("entries", km._tick_seen_report())

    def test_the_walks_key_counts_beside_the_tick_jobs(self):
        """The nudge walk's look memo shares the tick memo; its checks count under the same report, job auto-nudge, and a
        differing asker row past the ten files counts as askerRow."""
        d = tempfile.mkdtemp()
        r = _row(d, SID_OLD, old=True)
        st = km._session_files_stat(r) + (5.0, 7)                    # ten files plus one asker row
        km._nudge_look_done(r, st, [], "working")
        def job():
            return dict(km._tick_seen_report()["byJob"].get("auto-nudge") or {"hits": 0, "misses": 0, "neverSeen": 0, "noTranscript": 0, "clockParse": 0, "missBy": {}})
        rep0 = job()
        km._NUDGE_LOOK_STATS[SID_OLD] = st
        try:
            self.assertTrue(km._nudge_look_check(r, time.time())[0])
            self.assertEqual(job()["hits"] - rep0["hits"], 1, "the skipping return counts a hit")
            km._NUDGE_LOOK_STATS[SID_OLD] = km._session_files_stat(r) + (6.0, 7)   # the asker's row moved
            self.assertFalse(km._nudge_look_check(r, time.time())[0])
            self.assertEqual(job()["missBy"].get("askerRow", 0) - rep0["missBy"].get("askerRow", 0), 1, job()["missBy"])
            km._NUDGE_LOOK_STATS[SID_OLD] = km._session_files_stat(r)                  # a key of another length: shape
            self.assertFalse(km._nudge_look_check(r, time.time())[0])
            self.assertEqual(job()["missBy"].get("shape", 0) - rep0["missBy"].get("shape", 0), 1, job()["missBy"])
            # round two, MEDIUM: a matched key that a clock leg refuses to serve is a parse, never a hit
            km._NUDGE_LOOK_STATS[SID_OLD] = st
            km._nudge_look_done(r, st, [None], "awaiting-dispatch")                    # a None flip: unbounded
            h0, c0 = job()["hits"], job()["clockParse"]
            self.assertFalse(km._nudge_look_check(r, time.time())[0])
            self.assertEqual((job()["hits"] - h0, job()["clockParse"] - c0), (0, 1), "flip None: hits 0, clockParse 1")
            km._nudge_look_done(r, st, [time.time() - 5], "working")                  # a flip already due
            self.assertFalse(km._nudge_look_check(r, time.time())[0])
            self.assertEqual((job()["hits"] - h0, job()["clockParse"] - c0), (0, 2))
            # round two, low 1: the walk's no-transcript parse counts too
            n0 = job()["noTranscript"]
            km._NUDGE_LOOK_STATS[SID_OLD] = (0.0, 0) + st[2:]
            self.assertFalse(km._nudge_look_check(r, time.time())[0])
            self.assertEqual(job()["noTranscript"] - n0, 1)
            # round two, low 2: a previous entry that is not a sequence counts under shape, never raises
            with km._TICK_SEEN_LOCK:
                km._TICK_SEEN[("auto-nudge", SID_OLD)] = 17
            km._NUDGE_LOOK_STATS[SID_OLD] = st
            self.assertFalse(km._nudge_look_check(r, time.time())[0])
            self.assertEqual(job()["missBy"].get("shape", 0) - rep0["missBy"].get("shape", 0), 2)
            with km._TICK_SEEN_LOCK:
                km._TICK_SEEN[("interrupt-block", SID_OLD)] = "bad"
            self.assertFalse(km._tick_job_check("interrupt-block", r)[0])
            j = job
            ib = km._tick_seen_report()["byJob"]["interrupt-block"]
            self.assertGreaterEqual(ib["missBy"].get("shape", 0), 1, ib)
            # per job, the checks reconcile: hits + misses + neverSeen + noTranscript + clockParse
            a = job(); self.assertEqual(a["hits"] + a["misses"] + a["neverSeen"] + a["noTranscript"] + a["clockParse"],
                                        sum(rep0[k] for k in ("hits", "misses", "neverSeen", "noTranscript", "clockParse")) + 7,
                                        "the seven auto-nudge checks above, one counter each")
        finally:
            km._NUDGE_LOOK_STATS.clear()
            with km._TICK_SEEN_LOCK:
                km._TICK_SEEN.pop(("interrupt-block", SID_OLD), None); km._TICK_SEEN.pop(("auto-nudge", SID_OLD), None)

    def test_a_matched_key_a_clock_leg_refuses_to_serve_is_a_parse_not_a_hit(self):
        """Round two, MEDIUM: hits was incremented before the walk's three clock branches, so a parse forced by a None flip, a
        due flip or the closer toggle counted as a skip and a boot read over-reported the memo's skip rate; hits counts on the
        one return that skips, and those parses count under clockParse for the walk's job."""
        d = tempfile.mkdtemp()
        r = _row(d, SID_OLD, old=True)
        st = km._session_files_stat(r)
        def counters():                                             # shape-tolerant: per job (the head) or aggregate (the base)
            rep = km._tick_seen_report()
            j = (rep.get("byJob") or {}).get("auto-nudge") if "byJob" in rep else rep
            j = j or {}
            return j.get("hits", 0), j.get("clockParse", 0)
        km._nudge_look_done(r, st, [None], "awaiting-dispatch")     # a matched key whose look declined on a None flip
        km._NUDGE_LOOK_STATS[SID_OLD] = st
        try:
            h0, c0 = counters()
            skip, _st, verdict = km._nudge_look_check(r, time.time())
            self.assertFalse(skip, "a None flip: the look parses")
            h1, c1 = counters()
            self.assertEqual((h1 - h0, c1 - c0), (0, 1), "hits 0, clockParse 1 for auto-nudge")
        finally:
            km._NUDGE_LOOK_STATS.clear()
            with km._TICK_SEEN_LOCK:
                km._TICK_SEEN.pop(("auto-nudge", SID_OLD), None)

    def test_the_interrupt_ticks_key_is_its_own_ledger_row_not_the_ledgers_stat(self):
        """T401 (3), 1b's ledger branch (DRAFT): the interrupt tick reads one thing from the nudge ledger, its intrBlocked row for
        this session, while the ledger is one file for the box that every walk write moves; keyed on the file's stat, one
        ledger write re-evaluated every alive session's interrupt block, and at boot the walk's first pass wrote it before
        the tick read it. The key carries this session's own row instead: another session's row rewritten keeps the skip,
        this session's row rewritten busts it, and an unproved ledger yields no key."""
        d = tempfile.mkdtemp()
        me, other = SID_T3, SID_T3_OTHER                                   # private synthetic sids: this test's rows never land under the
        r = _row(d, me, old=True)                                           #  module's shared placeholders (the goal-store fixture rule)
        shared = [km.jd.STATE / "timeline" / "messages.jsonl", km.jd.STATE / "cleared.jsonl", km.jd.STATE / "auto-nudge.json",
                  km.jd.STATE / "states" / (me + ".jsonl"), km.jd.EPIDIR / (me + ".jsonl"), km._tick_seen_path()]
        sizes = {p: (p.read_bytes() if p.exists() else None) for p in shared}
        def restore():                                                      # every appended or written row undone, byte for byte
            for p, b in sizes.items():
                if b is None:
                    p.unlink(missing_ok=True)
                else:
                    p.write_bytes(b)
            with km._TICK_SEEN_LOCK:
                km._TICK_SEEN.pop(("interrupt-block", me), None)
        self.addCleanup(restore)
        led = km.jd.STATE / "auto-nudge.json"; led.parent.mkdir(parents=True, exist_ok=True)
        km._autonudge_cache.clear() if isinstance(getattr(km, "_autonudge_cache", None), dict) else None
        led.write_text(json.dumps({"enabled": True, "nudged": {}, "intrBlocked": {}}))
        key = km._interrupt_block_key(r); self.assertIsNotNone(key); self.assertEqual(len(key), 20)
        skip, st = km._tick_job_check("interrupt-block", r, key); km._tick_job_done("interrupt-block", r, st)
        self.assertTrue(km._tick_job_check("interrupt-block", r, km._interrupt_block_key(r))[0], "unchanged: skip")
        km._set_intr_blocked(other, other + ":g1")                     # ANOTHER session's row: the ledger's stat moves
        self.assertTrue(km._tick_job_check("interrupt-block", r, km._interrupt_block_key(r))[0],
                        "another session's row moved the ledger, not this session's key: the skip stands")
        log = km.jd.STATE / "timeline" / "messages.jsonl"; log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:                        # a postal message lands (position 8)
            f.write(json.dumps({"kind": "coordinate", "from_id": other, "to_sid": me, "t": time.time()}) + "\n")
        os.utime(log, (time.time() + 3, time.time() + 3))
        self.assertTrue(km._tick_job_check("interrupt-block", r, km._interrupt_block_key(r))[0],
                        "the tick reads no postal log: a message keeps the skip")
        cl = km.jd.STATE / "cleared.jsonl"
        with open(cl, "a", encoding="utf-8") as f:                         # a clear lands (position 7): an INPUT, by design (round two,
            f.write(json.dumps({"gid": other + ":g1", "t": time.time()}) + "\n")   # medium 2: the store readers' override replay
        os.utime(cl, (time.time() + 3, time.time() + 3))                   #  gates a journalled move on the clears log)
        self.assertFalse(km._tick_job_check("interrupt-block", r, km._interrupt_block_key(r))[0], "a clear busts the key")
        skip, st = km._tick_job_check("interrupt-block", r, km._interrupt_block_key(r)); km._tick_job_done("interrupt-block", r, st)
        ep = km.jd.EPIDIR / (me + ".jsonl"); ep.parent.mkdir(parents=True, exist_ok=True)
        with open(ep, "a", encoding="utf-8") as f:                         # an episode row lands (position 6)
            f.write(json.dumps({"t": time.time(), "kind": "x"}) + "\n")
        os.utime(ep, (time.time() + 3, time.time() + 3))
        self.assertTrue(km._tick_job_check("interrupt-block", r, km._interrupt_block_key(r))[0],
                        "the tick reads no episode log: an episode row keeps the skip")
        stl = km.jd.STATE / "states" / (me + ".jsonl"); stl.parent.mkdir(parents=True, exist_ok=True)
        with open(stl, "a", encoding="utf-8") as f:                        # a states-log row (position 2): an input (machineCut, working)
            f.write(json.dumps({"state": "idle", "t": time.time()}) + "\n")
        os.utime(stl, (time.time() + 3, time.time() + 3))
        self.assertFalse(km._tick_job_check("interrupt-block", r, km._interrupt_block_key(r))[0], "a states-log row busts the key")
        skip, st = km._tick_job_check("interrupt-block", r, km._interrupt_block_key(r)); km._tick_job_done("interrupt-block", r, st)
        km.jd.GOALDIR.mkdir(parents=True, exist_ok=True)
        (km.jd.GOALDIR / (me + ".json")).write_text("{}")             # the goal store (position 3): an input (the marker's card)
        try:
            self.assertFalse(km._tick_job_check("interrupt-block", r, km._interrupt_block_key(r))[0], "a store write busts the key")
            skip, st = km._tick_job_check("interrupt-block", r, km._interrupt_block_key(r)); km._tick_job_done("interrupt-block", r, st)
        finally:
            (km.jd.GOALDIR / (me + ".json")).unlink()
        skip, st = km._tick_job_check("interrupt-block", r, km._interrupt_block_key(r)); km._tick_job_done("interrupt-block", r, st)
        km._set_intr_blocked(me, me + ":g7")                     # THIS session's row
        self.assertFalse(km._tick_job_check("interrupt-block", r, km._interrupt_block_key(r))[0], "this session's row busts the key")
        by = km._tick_seen_report()["byJob"]["interrupt-block"]["missBy"]
        self.assertGreaterEqual(by.get("ledger", 0), 1, "the miss is counted under the ledger position: %r" % by)
        self.assertEqual(len(km._interrupt_block_key(r)), 20, "the ten-file shape stands, so missBy decodes")
        key = km._interrupt_block_key(r)
        for i in km._INTERRUPT_BLOCK_UNREAD:
            self.assertEqual(tuple(key[2 * i:2 * i + 2]), km._TICK_KEY_UNREAD, "a constant no stat can produce at position %d" % (i + 1))
        self.assertTrue(all(x < 0 for x in km._TICK_KEY_UNREAD))
        # a boot with the previous kernel's persisted entries skips a quiet session
        skip, st = km._tick_job_check("interrupt-block", r, km._interrupt_block_key(r)); km._tick_job_done("interrupt-block", r, st)
        self.assertTrue(km._persist_tick_seen(force=True))
        km._TICK_SEEN.clear(); self.assertGreaterEqual(km._load_tick_seen(), 1)
        km._set_intr_blocked(other, None)                                # the walk's ledger write at the next boot's first pass
        self.assertTrue(km._tick_job_check("interrupt-block", r, km._interrupt_block_key(r))[0], "the next kernel skips the quiet session")
        with mock.patch.object(km, "_auto_nudge_data", lambda: {km.UNPROVED: "EIO"}):
            self.assertIsNone(km._interrupt_block_key(r), "an unproved ledger: no key, the tick evaluates")
        self.assertEqual(km._NUDGE_FILE_KEYED_ROADS["interrupt-block"],
                         ("_interrupt_block_key", "_session_working", "_suspended_after", "_interrupt_marks", "_last_machine_cut",
                          "_interrupt_marks_atoms", "_machine_cut_cause", "_intr_blocked", "_record_interrupt_block",
                          "_interrupt_focus_top", "_intr_block_stands", "_lift_interrupt_block"),
                         "the road's exact members: the key builder, the verdict's readers and the arms' store readers (round two)")
        self.assertEqual(km._INTERRUPT_BLOCK_UNREAD, (5, 7), "the constant positions: the episode log and the postal log; the clears log is real")
        with km._TICK_SEEN_LOCK:
            km._TICK_SEEN.pop(("interrupt-block", me), None); km._TICK_SEEN_DIRTY[0] = False
        km._tick_job_done("interrupt-block", r, None)                       # the REAL key with no stat: nothing recorded (1595 low 1)
        with km._TICK_SEEN_LOCK:
            self.assertNotIn(("interrupt-block", me), km._TICK_SEEN, "a None key records nothing for this session")
            self.assertFalse(km._TICK_SEEN_DIRTY[0], "and dirties nothing")
        with km._TICK_SEEN_LOCK:                                           # the mutation the guard prevents: a None entry makes the
            km._TICK_SEEN[("interrupt-block", me)] = None; km._TICK_SEEN_DIRTY[0] = True   #  persist's json.dumps raise (list(None))
        try:
            with self.assertRaises(TypeError, msg="a None entry makes the persist RAISE under its lock (a raise per cycle, caught only by the "
                                                  "pusher's guard): what the `if st is None: return` keeps out"):
                km._persist_tick_seen()
        finally:
            with km._TICK_SEEN_LOCK:
                km._TICK_SEEN.pop(("interrupt-block", me), None); km._TICK_SEEN_DIRTY[0] = False

    def test_jobs_keep_separate_memos(self):
        d = tempfile.mkdtemp()
        r = _row(d, SID_NEW, old=False)
        skip, st = km._tick_job_check("interrupt-block", r); km._tick_job_done("interrupt-block", r, st)
        self.assertFalse(km._tick_job_skips("working-notes", r), "another job's first look is its own")

    def test_a_stand_down_with_nothing_to_block_records_the_evaluation_and_replaces_a_legacy_entry(self):
        """T401 (3), condition 4: five legacy six-element entries in the live memo (two for alive sessions) missed as shape every
        cycle and never got a twenty-element record. Cause: _record_interrupt_block returned None both for a store fault and
        for a stand-down (no focus top, the diary outranks), and the tick recorded nothing on None, so a session the user
        stopped with nothing to block was re-evaluated every cycle for good. A stand-down is a pure function of the files
        and records the evaluation; a store fault (False) still leaves the session to the next tick."""
        d = tempfile.mkdtemp()
        r = _row(d, SID_OLD, old=True)
        stopped = [{"id": "t1", "t": 1000, "atoms": [{"t": 1000, "type": "user"}]}]
        common = dict(_alive_sessions=lambda now, live_map: [r], _session_flag=lambda sid, flag: False,
                      _compacting_now=lambda *a, **k: False, _api_error=lambda path: False,
                      _interrupt_marks=lambda turns, sid, family="judge", path=None: (1000, 900), _session_working=lambda turns: False,
                      _auto_nudge_pause=lambda why: None, _auto_nudge_resume=lambda: None, _auto_nudge_data=lambda: {},
                      _intr_blocked=lambda sid=None, data=None: None)
        with km._TICK_SEEN_LOCK:
            km._TICK_SEEN[("interrupt-block", SID_OLD)] = (1.0, 2, 3.0, 4, 5.0, 6)      # the previous era's three-file key
        try:
            with mock.patch.multiple(km, **common), \
                 mock.patch.object(km.jd, "parsed_session", side_effect=lambda sid, paths, now: {"turns": stopped}):
                km._interrupt_block_tick(int(time.time()), {})                          # an empty store: nothing to block
            ent = km._TICK_SEEN.get(("interrupt-block", SID_OLD))
            self.assertEqual(len(ent or ()), 20, "the stand-down recorded the evaluation under the full key: %r" % (ent,))
            self.assertTrue(km._tick_job_check("interrupt-block", r, km._interrupt_block_key(r))[0], "and the next tick skips")
            with km._TICK_SEEN_LOCK:
                km._TICK_SEEN[("interrupt-block", SID_OLD)] = (1.0, 2, 3.0, 4, 5.0, 6)
            with mock.patch.multiple(km, **common), \
                 mock.patch.object(km.jd, "parsed_session", side_effect=lambda sid, paths, now: {"turns": stopped}), \
                 mock.patch.object(km.jd, "load_goals_or_fault", side_effect=lambda sid: (None, OSError("EIO"))):
                km._interrupt_block_tick(int(time.time()), {})                          # a store fault: not evaluated
            self.assertEqual(len(km._TICK_SEEN.get(("interrupt-block", SID_OLD)) or ()), 6, "a store fault records nothing")
            self.assertIs(km._record_interrupt_block(SID_OLD, 1000), None, "no focus top: a stand-down, None")
            with mock.patch.object(km.jd, "load_goals_or_fault", side_effect=lambda sid: (None, OSError("EIO"))):
                self.assertIs(km._record_interrupt_block(SID_OLD, 1000), False, "a store fault: False")
        finally:
            with km._TICK_SEEN_LOCK:
                km._TICK_SEEN.pop(("interrupt-block", SID_OLD), None)

    def test_a_bail_out_leaves_the_session_unmarked(self):
        """Review find: an unproved ledger read, a parse failure or an exception mid-tick must leave the session
        for the next tick; only a landed outcome marks it done."""
        d = tempfile.mkdtemp()
        r = _row(d, SID_OLD, old=True)
        stopped = [{"id": "t1", "t": 1000, "atoms": [{"t": 1000, "type": "user"}]}]
        common = dict(_alive_sessions=lambda now, live_map: [r], _session_flag=lambda sid, flag: False,
                      _compacting_now=lambda *a, **k: False, _api_error=lambda path: False,
                      _interrupt_marks=lambda turns, sid, family="judge", path=None: (1000, 900), _session_working=lambda turns: False,
                      _auto_nudge_pause=lambda why: None, _auto_nudge_resume=lambda: None)
        with mock.patch.multiple(km, **common), \
             mock.patch.object(km.jd, "parsed_session", side_effect=lambda sid, paths, now: {"turns": stopped}), \
             mock.patch.object(km, "_auto_nudge_data", side_effect=lambda: {km.UNPROVED: {"t": 1}}):
            km._interrupt_block_tick(int(time.time()), {})
        self.assertNotIn(("interrupt-block", SID_OLD), km._TICK_SEEN, "an unproved ledger read bails out unmarked")
        with mock.patch.multiple(km, **common), \
             mock.patch.object(km.jd, "parsed_session", side_effect=RuntimeError("parse failed")):
            km._interrupt_block_tick(int(time.time()), {})
        self.assertNotIn(("interrupt-block", SID_OLD), km._TICK_SEEN, "a parse failure bails out unmarked")

    def test_a_faulting_store_read_on_the_standing_path_leaves_the_session_unmarked(self):
        """Review find: _intr_block_stands keeps the marker on an unreadable store by design; that is not evidence
        the block still holds its card, so the tick must not mark the session evaluated (the persisted memo would
        carry the skip across a restart while the new focus top sat in Working)."""
        d = tempfile.mkdtemp()
        r = _row(d, SID_OLD, old=True)
        stopped = [{"id": "t1", "t": 1000, "atoms": [{"t": 1000, "type": "user"}]}]
        common = dict(_alive_sessions=lambda now, live_map: [r], _session_flag=lambda sid, flag: False,
                      _compacting_now=lambda *a, **k: False, _api_error=lambda path: False,
                      _interrupt_marks=lambda turns, sid, family="judge", path=None: (1000, 900), _session_working=lambda turns: False,
                      _auto_nudge_resume=lambda: None, _auto_nudge_data=lambda: {}, _intr_blocked=lambda sid=None, data=None: "g1")
        with mock.patch.multiple(km, **common), \
             mock.patch.object(km.jd, "parsed_session", side_effect=lambda sid, paths, now: {"turns": stopped}), \
             mock.patch.object(km.jd, "load_goals_shared_or_fault", side_effect=lambda sid: (None, OSError("transient"))):
            km._interrupt_block_tick(int(time.time()), {})
        self.assertNotIn(("interrupt-block", SID_OLD), km._TICK_SEEN, "a faulted store read is not a standing block: unmarked")
        with mock.patch.multiple(km, **common), \
             mock.patch.object(km.jd, "parsed_session", side_effect=lambda sid, paths, now: {"turns": stopped}), \
             mock.patch.object(km.jd, "load_goals_shared_or_fault", side_effect=lambda sid: ({"nodes": {"g1": {"blocked": True}}}, None)):
            km._interrupt_block_tick(int(time.time()), {})
        self.assertIn(("interrupt-block", SID_OLD), km._TICK_SEEN, "a readable store whose block still holds its card: evaluated")

    def test_a_refused_marker_write_leaves_the_session_unmarked(self):
        """Review find: _set_intr_blocked returns False when its own ledger read is unproved; marking the session
        done on that would leave the block on the card with no marker ever minted."""
        d = tempfile.mkdtemp()
        r = _row(d, SID_OLD, old=True)
        stopped = [{"id": "t1", "t": 1000, "atoms": [{"t": 1000, "type": "user"}]}]
        common = dict(_alive_sessions=lambda now, live_map: [r], _session_flag=lambda sid, flag: False,
                      _compacting_now=lambda *a, **k: False, _api_error=lambda path: False,
                      _interrupt_marks=lambda turns, sid, family="judge", path=None: (1000, 900), _session_working=lambda turns: False,
                      _auto_nudge_resume=lambda: None, _auto_nudge_data=lambda: {}, _intr_blocked=lambda sid=None, data=None: None,
                      _record_interrupt_block=lambda sid, ev: "g1")
        for refused, marked in ((False, False), (True, True)):
            km._TICK_SEEN.clear()
            with mock.patch.multiple(km, **common), \
                 mock.patch.object(km, "_set_intr_blocked", side_effect=lambda sid, gid: refused), \
                 mock.patch.object(km.jd, "parsed_session", side_effect=lambda sid, paths, now: {"turns": stopped}):
                km._interrupt_block_tick(int(time.time()), {})
            self.assertEqual(("interrupt-block", SID_OLD) in km._TICK_SEEN, marked,
                             "marker write returned %r → marked %r" % (refused, marked))

    def test_the_two_event_keyed_ticks_gate_before_their_parse_and_the_nudge_does_not(self):
        for fn, job in ((km._interrupt_block_tick, "interrupt-block"), (km._clear_done_working_notes, "working-notes")):
            src = inspect.getsource(fn)
            gate = src.index('_tick_job_check("%s", s, _key)' % job if job == "interrupt-block" else '_tick_job_check("%s", s)' % job)
            parse = src.index("jd.parsed_session(sid, [s[\"path\"]], now)")   # the interrupt tick hands its own key (T401 (3))
            self.assertLess(gate, parse, "%s: the gate sits before the parse" % job)
            self.assertIn('_tick_job_done("%s", s, files_st)' % job, src, "%s: a completed evaluation is marked done" % job)
        self.assertEqual(inspect.getsource(km._interrupt_block_tick).count('_tick_job_done("interrupt-block", s, files_st)'), 5,
                         "done on the five landed outcomes (filed, standing, lifted, nothing to lift, a stand-down with nothing to block); "
                         "never on a refused write, an unproved ledger or a store fault")
        walk = inspect.getsource(km._auto_nudge_session)               # T401 (2): the nudge's gate is its own (the memo plus the
        self.assertNotIn("_tick_job_check", walk + inspect.getsource(km._nudge_look_gated),   # earliest clock flip), never the
                         "the nudge has wall-clock legs: never the plain memo check (documented in _tick_job_check)")   # plain check
        self.assertTrue(walk.startswith("@_nudge_look_gated"), "the look is wrapped by its parse gate")
        self.assertTrue(hasattr(km._auto_nudge_session, "__wrapped__"))
        cyc = inspect.getsource(km._jobs_pass)                          # the jobs thread's list (the housekeeping split, 2026-09-13)
        self.assertLess(cyc.index("_job_stage('interruptBlock', lambda: _interrupt_block_tick(now, live_map))"),
                        cyc.index("_job_stage('persistTickSeen', lambda: _persist_tick_seen())"), "the memo is written after the tick jobs")
        self.assertIn("_persist_tick_seen(force=True)", inspect.getsource(km._drain_and_exit), "and at exit")


class PerfCountsColdParses(unittest.TestCase):
    def test_counter_and_snapshot(self):
        km._PERF_STATS.reset()
        km._PERF_STATS.parse(SID_OLD, 1234)
        km._PERF_STATS.parse(SID_OLD, 10)
        km._PERF_STATS.parse(SID_NEW, 5)
        snap = km._PERF_STATS.snapshot()
        # bytes is wholeBytes since 2026-09-24 (only a whole parse books the leaf); these three ride the default road, full
        self.assertEqual((snap["parses"]["kernel"], snap["parses"]["wholeBytes"]), (3, 1249), "the kernel's own asks (stage 2 splits the counters)")
        self.assertIsInstance(snap["parses"]["total"], int)
        self.assertEqual(snap["parses"]["bySid"], {SID_OLD[:8]: 2, SID_NEW[:8]: 1})
        self.assertIsInstance(snap["parses"]["judge"], int)

    def test_kernel_parse_counts_a_miss_not_a_hit(self):
        d = tempfile.mkdtemp()
        r = _row(d, SID_NEW, old=False)
        km._PERF_STATS.reset()
        km._parse_cache.pop(r["path"], None)
        now = int(time.time())
        km._parse(r["path"], SID_NEW, now)
        km._parse(r["path"], SID_NEW, now)
        snap = km._PERF_STATS.snapshot()["parses"]
        self.assertEqual((snap["kernel"], snap["hits"]), (1, 1), "the second call is served from the shared store")

    def test_judge_parse_misses(self):
        d = tempfile.mkdtemp()
        r = _row(d, SID_WORK, old=False)
        before = jd.parse_misses()
        jd._PARSE_CACHE.pop(SID_WORK, None)
        now = int(time.time())
        jd.parsed_session(SID_WORK, [r["path"]], now)
        jd.parsed_session(SID_WORK, [r["path"]], now)
        self.assertEqual(jd.parse_misses() - before, 1)


class JudgesGoNewestFirst(unittest.TestCase):
    def test_by_recency_orders_by_transcript_mtime(self):
        d = tempfile.mkdtemp()
        rows = []
        for i, sid in enumerate((SID_OLD, SID_NEW, SID_WORK)):
            p = Path(d) / (sid + ".jsonl"); p.write_text("{}\n")
            os.utime(p, (1000 + i * 100, 1000 + i * 100))
            rows.append((sid, str(p), sid, sid[:8]))
        rows.append(("missing", str(Path(d) / "missing.jsonl"), "missing", "m"))
        out = jd.by_recency(rows)
        self.assertEqual([r[0] for r in out], [SID_WORK, SID_NEW, SID_OLD, "missing"], "newest first, a stat failure last")
        self.assertEqual([r[0] for r in rows][0], SID_OLD, "the input is not reordered in place")

    def test_passes_walk_by_recency_and_yield(self):
        src = inspect.getsource(jd._run_index)
        self.assertIn("fleet = by_recency(discover(now))", src)
        self.assertIn("yield_between_sessions()", src)
        self.assertEqual(inspect.getsource(jd).count("by_recency(discover(now))"), 1,
                         "the FIRST pass (the index) orders by recency; the courier and the capped passes keep discover()'s order, which their tests pin")


if __name__ == "__main__":
    unittest.main()
