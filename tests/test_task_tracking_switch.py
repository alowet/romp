#!/usr/bin/env python3
"""The Task tracking master switch (T404 PR 2, the user 2026-09-13): default on; off, the task tracking system stands down
entirely. Executed on the kernel module with a hermetic state root: the store's reads (absent, malformed, false, true), the
setter's gesture rules (echo, stale, applied stamp), the socket arm (writes and wakes the producer), the producer's tier
gate (a function of its inputs: off starts nothing with a live session and retries not paused; on starts both), the feed's
off frame in place of a build (the builder stubbed to raise: a call would be the bug), the two panes' notice (hidden while
on, shown while off), the nudge pass walking wake-only while off (the goal nudges wait; the compaction suggestion and the
debt ladder keep the nudge toggle), and the CENSUS: every model-call site in kernel/judge.py names a judge that
judge.py MODEL_CALLERS declares, and the entry point refuses an undeclared judge and stands a tracking judge down while the
switch is off. Round two (the read at 7a105ade): the judge-side gate is installed at kernel import; a refused write is
told on the socket with the kept value, and an applied flip is echoed to it (the gear dresses on the echo, never the
click); the switch is a mesh-adopted setting with its stamp in every table; the debt reminders ride the nudge toggle alone
and go out while tracking is off; the census resolves a judge name bound in the function and flags one it cannot, and the
entry point refuses an undeclared judge; the push attaches no ledgers while off and the chat's dots are derived outside
the feed build; the clear-all op builds no feed while off. Synthetic everything: hermetic XDG state, no network, no browser.
"""
import ast
import json
import os
import shutil
import tempfile
import time
import types
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
import sys
sys.path.insert(0, HERE)
from romp_load import load_source   # noqa: E402
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)   # a live kernel's export outranks the XDG floor
os.environ.setdefault("ROMP_KERNEL_PORT", "0")   # never the live kernel's port

km = load_source("romp_kernel_tasktrack", os.path.join(BIN, "romp-kernel"))
JUDGE_SRC = Path(ROOT, "kernel", "judge.py").read_text()


class _Base(unittest.TestCase):
    """A fresh state root per test; the judge module's hook restored after."""
    maxDiff = None

    def setUp(self):
        self._td = tempfile.mkdtemp()
        self._saved_state = km.jd.STATE
        km.jd.STATE = Path(self._td)
        km.jd._state_cache.clear()
        Path(self._td, "session-hosts").write_text("off")
        self._saved_hook = km.jd.TASK_TRACKING_ON   # installed by the kernel's own load (TheJudgeHook); tests that stub it restore it
        km._stale_seen.last = None
        km._stale_seen.refused = None
        self.replies = []                            # every frame a socket op answered on its delivering socket
        self._saved_reply = km._reply
        km._reply = lambda client, m: self.replies.append(m)

    def tearDown(self):
        km._reply = self._saved_reply
        km.jd.TASK_TRACKING_ON = self._saved_hook
        km.jd.STATE = self._saved_state
        km.jd._state_cache.clear()
        shutil.rmtree(self._td, ignore_errors=True)

    def _file(self):
        return Path(self._td) / km.TASK_TRACKING_FILE


class TheStore(_Base):
    def test_absent_unreadable_or_malformed_reads_on(self):
        self.assertTrue(km._task_tracking_on(), "no file: on")
        self._file().write_text("{not json")
        self.assertTrue(km._task_tracking_on(), "malformed: on")
        self._file().write_text(json.dumps({"gt": 5}))
        self.assertTrue(km._task_tracking_on(), "no field: on")
        self._file().write_text(json.dumps({"enabled": "no"}))
        self.assertTrue(km._task_tracking_on(), "only the literal false turns it off")

    def test_false_reads_off_and_true_on(self):
        self._file().write_text(json.dumps({"enabled": False, "gt": 1}))
        self.assertFalse(km._task_tracking_on())
        self._file().write_text(json.dumps({"enabled": True, "gt": 2}))
        self.assertTrue(km._task_tracking_on())

    def test_a_present_file_that_cannot_be_read_reads_on_and_is_said_once_per_episode_while_absence_is_quiet(self):
        # round three, low 3: the siblings' unproved default withholds a capability; this one resumes spending, so it is said
        said = []
        saved = km._sync_notice
        km._sync_notice = lambda text, ok=True, kind="sync": said.append((text, ok, kind))
        try:
            self.assertTrue(km._task_tracking_on()); self.assertEqual(said, [], "absent: the quiet default")
            self._file().write_text("{not json")
            self.assertTrue(km._task_tracking_on(), "malformed reads on")
            self.assertTrue(km._task_tracking_on())
            self.assertEqual(len(said), 1, "…and is said ONCE for the episode: %r" % said)
            self.assertIn("task tracking switch file could not be read", said[0][0]); self.assertIn("tracking is running", said[0][0])
            self.assertEqual((said[0][1], said[0][2]), (False, "refused"), "the bell's refused kind")
            self._file().write_text(json.dumps({"enabled": False, "gt": 3}))
            self.assertFalse(km._task_tracking_on(), "a clean read ends the episode")
            self._file().write_text("[]")
            self.assertTrue(km._task_tracking_on(), "the wrong shape reads on")
            self.assertEqual(len(said), 2, "…and opens a new episode")
            for i, bad in enumerate(('{"enabled": null}', '{"enabled": 0}', '{"enabled": "false"}')):   # round four, low 1
                self._file().write_text(json.dumps({"enabled": True}))
                self.assertTrue(km._task_tracking_on()); n0 = len(said)
                self._file().write_text(bad)
                self.assertTrue(km._task_tracking_on(), bad + ": not true or false reads on")
                self.assertTrue(km._task_tracking_on())
                self.assertEqual(len(said), n0 + 1, bad + ": said once for its episode: %r" % said[-1:])
                self.assertIn("not true or false", said[-1][0])
            self._file().write_text(json.dumps({"gt": 5}))
            self.assertTrue(km._task_tracking_on(), "no enabled key: the default, on"); self.assertEqual(len(said), n0 + 1, "…and quiet: the intent is the default, readable")
            self._file().write_text(json.dumps({"enabled": False}))
            self.assertFalse(km._task_tracking_on(), "the literal false is the only off"); n1 = len(said)
            self._file().write_text(json.dumps({"enabled": True}))
            self.assertTrue(km._task_tracking_on()); self.assertEqual(len(said), n1, "a proved read says nothing")
            n2 = len(said)
            self._file().unlink(); self._file().mkdir()
            self.assertTrue(km._task_tracking_on(), "a directory in the file's place reads on")
            self.assertEqual(len(said), n2 + 1, "…said once")
            self.assertTrue(km._task_tracking_on()); self.assertEqual(len(said), n2 + 1)
            self._file().rmdir()
            self.assertTrue(km._task_tracking_on()); self.assertEqual(len(said), n2 + 1, "absence again is quiet and ends the episode")
        finally:
            km._sync_notice = saved

    def test_the_three_readers_of_the_stored_value_are_one_reader_and_agree_on_every_shape(self):
        # round five, low 3: the display read, the setter's echo check and the mesh snapshot resolved the value with two rules
        shapes = ['{"enabled": false, "gt": 1}', '{"enabled": true, "gt": 2}', '{"enabled": null}', '{"enabled": 0}', '{"enabled": "false"}',
                  '{"enabled": 1}', '{"gt": 5}', '[]', '"junk"', '{not json']
        saved = km._sync_notice; km._sync_notice = lambda *a, **k: None
        try:
            for raw in shapes:
                self._file().write_text(raw)
                try:
                    d = json.loads(raw)
                except ValueError:
                    d = None
                one = km._tracking_value(d)[0]
                self.assertEqual(km._task_tracking_on(), one, raw + ": the display read is the one reader")
                self.assertEqual(km._mesh_settings_snapshot()[0]["taskTracking"], one, raw + ": the mesh snapshot too")
        finally:
            km._sync_notice = saved
        self.assertEqual([km._tracking_value(x) for x in ({"enabled": False}, {"enabled": True}, {"gt": 5}, {"enabled": None}, {"enabled": 0}, {"enabled": "false"}, [], None)],
                         [(False, True), (True, True), (True, True), (True, False), (True, False), (True, False), (True, False), (True, False)],
                         "proved only for a real boolean or an absent key; everything else on and unproved")
        ksrc = Path(ROOT, "kernel", "kernel.py").read_text()
        self.assertIn("prev_on = _tracking_value(prev)[0]", ksrc, "the setter's echo check reads through the one reader")
        self.assertIn('"taskTracking": _tracking_value(tt)[0]}', ksrc, "the mesh snapshot too")
        self.assertIn("on, proved = _tracking_value(d)", ksrc, "and the display read")
        self.assertNotIn('is not False', ksrc[ksrc.index("def _tracking_value("):ksrc.index("def _tracking_value(") + 6000], "no second rule near the reader")

    def test_reading_never_creates_the_file(self):
        km._task_tracking_on()
        self.assertFalse(self._file().exists())


class TheSetter(_Base):
    def test_a_stamped_flip_applies_and_is_read_back(self):
        self.assertEqual(km._set_task_tracking(False, gt=1000), 1000)
        self.assertEqual(json.loads(self._file().read_text()), {"enabled": False, "gt": 1000})
        self.assertFalse(km._task_tracking_on())
        self.assertEqual(km._set_task_tracking(True, gt=1001), 1001)
        self.assertTrue(km._task_tracking_on())

    def test_the_same_value_with_the_same_stamp_is_a_silent_echo_and_an_older_stamp_stands_down(self):
        km._set_task_tracking(False, gt=1000)
        self.assertIsNone(km._set_task_tracking(False, gt=1000), "the gesture's own echo: nothing to apply")
        self.assertIsNone(km._stale_seen.last, "an echo is quiet")
        self.assertIsNone(km._set_task_tracking(True, gt=900), "an older stamp stands down")
        self.assertEqual(km._stale_seen.last["setting"], "task-tracking")
        self.assertFalse(km._task_tracking_on(), "the stored value held")

    def test_a_refused_write_applies_nothing_and_is_told_with_the_kept_value(self):
        # a directory where the file goes: the read falls to on (malformed reads on) and the atomic write's replace refuses
        self._file().mkdir()
        self.assertIsNone(km._set_task_tracking(False, gt=5000))
        self.assertTrue(km._task_tracking_on(), "nothing applied: the store still reads on")
        rf = km._stale_seen.refused
        self.assertIsNotNone(rf, "the refusal is recorded for the delivering socket (its siblings' road)")
        self.assertEqual((rf["setting"], rf["refused"], rf["write"], rf["known"]), ("task-tracking", "off", True, True), rf)
        self.assertTrue(rf["why"].startswith("write failed"), rf["why"])

    def test_an_unstamped_flip_applies_with_the_clock(self):
        stamp = km._set_task_tracking(False)
        self.assertIsInstance(stamp, int)
        self.assertGreater(stamp, 0)
        self.assertFalse(km._task_tracking_on())


class TheSocketArm(_Base):
    def test_set_task_tracking_writes_and_wakes_the_producer(self):
        km._producer_wake.clear()
        t0 = time.time()
        km._PURE_FEED = ("stale", 0, 0, None)
        km.Handler._dispatch_ws(types.SimpleNamespace(), {"type": "setTaskTracking", "enabled": False, "gt": 2000}, {})
        self.assertFalse(km._task_tracking_on(), "the arm wrote the store")
        self.assertTrue(km._producer_wake.is_set(), "…and woke the producer, so the tiers stop at the next pass")
        self.assertGreaterEqual(km._views_dirty[0], t0, "…and marked the views dirty, so the feed cache rebuilds into the off frame instead of serving its warmed build")
        self.assertIsNone(km._PURE_FEED, "…and dropped the GET copy")
        km._producer_wake.clear()
        km.Handler._dispatch_ws(types.SimpleNamespace(), {"type": "setTaskTracking", "enabled": True, "gt": 1999}, {})
        self.assertFalse(km._task_tracking_on(), "a stale stamp stood down")
        self.assertFalse(km._producer_wake.is_set(), "a stood-down gesture is not new information: no wake")

    def test_an_applied_flip_is_echoed_to_the_delivering_socket_and_a_refusal_is_told_with_why_and_the_kept_value(self):
        km.Handler._dispatch_ws(types.SimpleNamespace(), {"type": "setTaskTracking", "enabled": False, "gt": 2000}, {})
        self.assertEqual(self.replies, [{"type": "taskTracking", "on": False, "gt": 2000}],
                         "the kernel's echo: the gear dresses its dependents and tells the shell on this frame, never on the click")
        self.replies.clear()
        km.Handler._dispatch_ws(types.SimpleNamespace(), {"type": "setTaskTracking", "enabled": True, "gt": 1500}, {})
        self.assertEqual(len(self.replies), 1, self.replies)
        st = self.replies[0]
        self.assertEqual((st["type"], st["setting"], st["storedGt"], st["gt"], st["kept"]), ("settingStale", "task-tracking", 2000, 1500, False),
                         "a stale stand-down names the kept value (off), so the toast's Keeping clause reads: %r" % st)
        self.assertEqual(st["gesture"], {"type": "setTaskTracking", "enabled": True})
        self.replies.clear()
        self._file().unlink()
        self._file().mkdir()                         # the refused write: nothing applied, the socket hears why and what is kept
        km.Handler._dispatch_ws(types.SimpleNamespace(), {"type": "setTaskTracking", "enabled": False, "gt": 3000}, {})
        self.assertEqual(len(self.replies), 1, self.replies)
        rf = self.replies[0]
        self.assertEqual((rf["type"], rf["setting"], rf["kept"], rf["gt"]), ("settingStale", "task-tracking", True, 3000), rf)
        self.assertTrue(rf["why"].startswith("write failed"), rf)
        self.assertTrue(km._task_tracking_on(), "the kernel keeps tracking on: the shell and the gear follow it, not the click")


class TheProducerGate(_Base):
    def setUp(self):
        super().setUp()
        self._saved = (km._live_map, km._retry_paused_on)
        km._live_map = lambda: {"11111111-2222-3333-4444-555555555555": object()}
        km._retry_paused_on = lambda: False

    def tearDown(self):
        km._live_map, km._retry_paused_on = self._saved
        super().tearDown()

    def test_off_starts_no_tier_with_a_live_session_and_retries_not_paused(self):
        self.assertFalse(km._tiers_may_start(False))
        km._set_task_tracking(False, gt=1)
        self.assertFalse(km._tiers_may_start(), "the default reads the store")

    def test_on_starts_the_tiers(self):
        self.assertTrue(km._tiers_may_start(True))
        self.assertTrue(km._tiers_may_start(), "the default reads the store: absent is on")

    def test_no_live_session_or_a_paused_retry_starts_none_even_when_on(self):
        km._live_map = lambda: {}
        self.assertFalse(km._tiers_may_start(True))
        km._live_map = lambda: {"x": 1}
        km._retry_paused_on = lambda: True
        self.assertFalse(km._tiers_may_start(True))

    def test_the_producer_keeps_its_two_literal_tier_threads_behind_the_predicate(self):
        import inspect, re
        body = inspect.getsource(km._producer)
        self.assertIn("res = jd.run_pass(_tiers_may_start(tracking), before_tier=_tier_started)", body, "the predicate's answer gates the shared pass body")
        self.assertIn("def _tier_started(name):", inspect.getsource(km._tier_started), "each tier counts at its start")
        before = km._PERF_STATS.snapshot()["judge"]["tierStarts"]; km._tier_started("index")
        self.assertEqual(km._PERF_STATS.snapshot()["judge"]["tierStarts"], before + 1, "the hook counts one tier as it starts (round three: a read mid-pass sees the running tiers)")
        self.assertNotIn('judge_tiers(res["tierStarts"])', body, "and not again after the barrier")
        guard = re.search(r"    if may_start:\n(.*?)\n    frame = begin_pass_frame\(\)", inspect.getsource(km.jd.run_pass), re.S)
        self.assertTrue(guard, "one guard for both tiers, in the shared body")
        self.assertIn('"index", acc, before_tier), name="index"', guard.group(1))
        self.assertIn('"triage", acc, before_tier), name="triage"', guard.group(1))
        res = km.jd.run_pass(False)
        self.assertEqual((res["tierStarts"], res["failures"]), (0, []), "may_start False starts nothing, whatever the store says")

    def test_the_perf_counter_counts_tier_starts(self):
        before = km._PERF_STATS.snapshot()["judge"]["tierStarts"]
        km._PERF_STATS.judge_tiers(2)
        self.assertEqual(km._PERF_STATS.snapshot()["judge"]["tierStarts"], before + 2)


class TheFeedOffFrame(_Base):
    def test_the_switch_is_an_input_of_the_view_signature(self):
        # the feed cache serves its warmed build while the signature stands: the switch's file is one of its inputs, so a flip
        # busts the cache the way every other file input does (the dirty mark in the socket arm is the belt)
        km._live_map = getattr(km, "_live_map")
        s1 = json.dumps(km._fleet_view_sig(int(time.time()), {}), sort_keys=True, default=str)
        km._set_task_tracking(False, gt=1)
        s2 = json.dumps(km._fleet_view_sig(int(time.time()), {}), sort_keys=True, default=str)
        self.assertNotEqual(s1, s2, "the signature moved with the switch's file")
        self.assertIn("__tracking__", s2)

    def test_the_frame_carries_the_flag_and_the_empty_lists_its_readers_iterate(self):
        f = km._feed_off_frame(123)
        self.assertEqual((f["type"], f["off"], f["now"], f["asks"], f["ledgers"]), ("feed", True, 123, [], []))
        for key in ("items", "asks", "working", "awaiting", "stateUnknown", "order", "sessions", "ledgers", "hosts", "pendingHosts", "pendingDead"):
            self.assertEqual(f[key], [], key + ": every list the push, the chat and the merge read is present and empty (a missing one raised inside the push)")
        self.assertIn('feed["working"]', Path(ROOT, "kernel", "kernel.py").read_text(), "the push does read the working list")
        self.assertEqual(km._needs_input_sids(f), set() if isinstance(km._needs_input_sids(f), set) else km._needs_input_sids(f))
        self.assertEqual(km._needs_you_count(f), 0)

    def test_the_off_frame_never_runs_the_bell_diff_so_a_mute_survives_the_switch(self):
        # round three, the medium: the diff's prune reads the frame's cards as the live set, and the off frame has none, so one off
        # frame deleted every per-card mute from notify-cards.json (the cards had not gone; they were in the store, and returned)
        bells = Path(self._td) / "notify-cards.json"
        bells.write_text(json.dumps({"*": True, "g-needsyou-1": False, "g-working-1": False}, sort_keys=True))
        before = bells.read_text()
        km._set_task_tracking(False, gt=1)
        # the FIRST-BOOT road, where the prune lives (round four, medium 1): no remembered snapshot in memory and none on disk (a
        # fresh state root), so the diff seeds from the frame's cards, and the off frame has none: every non-reserved id is gone
        saved = (list(km._built_feed), km._NOTIFY_PREV[0], km._NOTIFY_PREV_DISK[0])
        km._NOTIFY_PREV[0] = None; km._NOTIFY_PREV_DISK[0] = None
        self.assertFalse(any(p.name.startswith("notify-prev") for p in Path(self._td).iterdir()), "no snapshot file in the fresh root")
        km._built_feed[:] = [None, None, 0, 0]
        try:
            f = km._cached_feed(int(time.time()), {}, "sig-off")
        finally:
            km._built_feed[:] = saved[0]; km._NOTIFY_PREV[0] = saved[1]; km._NOTIFY_PREV_DISK[0] = saved[2]
        self.assertTrue(f.get("off"), "the post-build work ran on the off frame")
        self.assertEqual(bells.read_text(), before, "notify-cards.json is unchanged: the stand-in frame fed no writer that prunes by absence")
        km._set_task_tracking(True, gt=2)
        cards = km._notify_cards()
        self.assertIs(km._notify_card_effective(cards, "g-working-1", "11111111-2222-3333-4444-555555555555"), False, "back on, the Working card's mute still holds")
        self.assertIs(km._notify_card_effective(cards, "g-needsyou-1", "11111111-2222-3333-4444-555555555555"), False)
        self.assertIn('_fired = _feed_notifications(feed) if not feed.get("off") else []', Path(ROOT, "kernel", "kernel.py").read_text(), "the one-line gate its two siblings have")

    def test_the_off_frame_carries_the_notice_rings_and_the_bells_bits_so_the_error_center_carries_on(self):
        # round four, the ruling: the error center is not task tracking; a refused write or a failed sync is told while off
        km._sync_notice("TESTHOST: the machine sync failed (a stub)", ok=False, kind="sync")
        km._sync_notice("session-flags.json — the change was not saved (a stub)", ok=False, kind="refused")
        km._sdk_problem("a session that cannot start (a stub)")
        f = km._feed_off_frame(int(time.time()), {})
        self.assertTrue(f["off"])
        self.assertEqual(km._FEED_FRAME_RINGS, ("clearNotices", "sdkNotices", "syncNotices"))
        for key in km._FEED_FRAME_RINGS:
            self.assertIsInstance(f[key], list, key)
        texts = [r["text"] for r in f["syncNotices"]]
        self.assertTrue(any("machine sync failed" in t for t in texts) and any("was not saved" in t for t in texts), "the sync ring's rows ride the off frame: %r" % texts)
        self.assertEqual([r["kind"] for r in f["syncNotices"] if "was not saved" in r["text"]], ["refused"], "with their kinds")
        self.assertTrue(any("cannot start" in r.get("text", "") for r in f["sdkNotices"]), "the SDK ring's rows too: %r" % f["sdkNotices"])
        # round nine, low 1: the clear ring's ROWS ride too (it was pinned as a list alone, so dropping its rows survived the module)
        saved_bcn = km._boundary_clear_notices
        row = {"sig": "c|11111111-2222-3333-4444-555555555555|7", "sid": "11111111-2222-3333-4444-555555555555", "t": 7,
               "text": "web: a /clear dropped two open cards (a stub)"}
        km._boundary_clear_notices = lambda alive: [dict(row)]
        try:
            f2 = km._feed_off_frame(int(time.time()), {})
        finally:
            km._boundary_clear_notices = saved_bcn
        self.assertEqual(f2["clearNotices"], [row], "the clear ring's rows ride the off frame, verbatim")
        self.assertEqual((f["dismissedCount"], f["showDismissed"], f["canUndoClear"]), (0, False, False), "the bell's bits, from the cleared set")
        self.assertIn('mirrorBadges([], Array.isArray(m.clearNotices) ? m.clearNotices : [], Array.isArray(m.sdkNotices) ? m.sdkNotices : [], Array.isArray(m.syncNotices) ? m.syncNotices : [], { cardsUnknown: true });',
                      Path(ROOT, "ui", "webview", "feed.ts").read_text(), "the feed's off branch mirrors the rings to the shell's bell before it returns, the cards unknown (round five)")

    def test_the_pure_feed_builds_nothing_while_off(self):
        km._set_task_tracking(False, gt=1)
        saved = km.build_feed
        def boom(*a, **k):
            raise AssertionError("build_feed called while task tracking is off")
        km.build_feed = boom
        try:
            km._PURE_FEED = None if hasattr(km, "_PURE_FEED") else None
            f = km._pure_feed(int(time.time()), {})
        finally:
            km.build_feed = saved
        self.assertTrue(f.get("off"), json.dumps(f)[:200])


class ThePanesNotice(_Base):
    def test_the_notice_is_in_both_pages_hidden_while_on_and_shown_while_off(self):
        for page in (km._feed_page(), km._fleet_page()):
            self.assertIn("<div id=tt-off class=tt-off hidden", page, "on: the notice is in the page, hidden")
            self.assertIn("Task tracking is off, so there is no ", page)
            self.assertIn("<button id=tt-off-btn type=button class=notice-act>Open Task tracking settings</button>", page)
        km._set_task_tracking(False, gt=1)
        feed, fleet = km._feed_page(), km._fleet_page()
        self.assertIn("<div id=tt-off class=tt-off style=", feed, "off: the notice shows")
        self.assertIn("there is no feed to show", feed)
        self.assertIn("there is no outline to show", fleet)
        self.assertNotIn("class=tt-off hidden", feed)
        self.assertNotIn("class=tt-off hidden", fleet)

    def test_the_version_report_carries_the_switch_top_level_and_in_settings(self):
        v = km._version_info()
        self.assertTrue(v["taskTracking"])
        self.assertTrue(v["settings"]["taskTracking"])
        km._set_task_tracking(False, gt=1)
        v = km._version_info()
        self.assertFalse(v["taskTracking"])
        self.assertFalse(v["settings"]["taskTracking"])


def _consts(node):
    """The constants an expression can evaluate to: a constant itself, or either arm of a conditional (nested too)."""
    if isinstance(node, ast.Constant):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _consts(node.body) | _consts(node.orelse)
    return set()


def _census(src=None):
    """Every function in judge.py that calls _judge_run, and every judge name those calls carry: a constant `judge=`,
    the function's own default for a `judge` parameter, every constant a caller passes for that parameter, and every
    constant the function binds to that name itself (`which = "planner"`, a conditional between constants). A name that
    resolves to no constant at all is flagged `<unnamed:function:name>` so the census FAILS on it rather than passing
    over a caller it cannot read (round two, low 3: a local passed as the judge was silently skipped)."""
    tree = ast.parse(JUDGE_SRC if src is None else src)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    def defaults(fn):
        a = fn.args; d = {}
        for arg, dv in zip(a.args[len(a.args) - len(a.defaults):], a.defaults):
            d[arg.arg] = dv
        for arg, dv in zip(a.kwonlyargs, a.kw_defaults):
            d[arg.arg] = dv
        return d
    callers, names = set(), set()
    for fname, fn in fns.items():
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_judge_run":
                callers.add(fname)
                jv = {k.arg: k.value for k in node.keywords}.get("judge")
                if isinstance(jv, ast.Constant):
                    names.add(jv.value)
                elif isinstance(jv, ast.Name):
                    found = set()
                    dv = defaults(fn).get(jv.id)
                    if isinstance(dv, ast.Constant):
                        found.add(dv.value)
                    for n2 in ast.walk(tree):
                        if isinstance(n2, ast.Call) and getattr(n2.func, "id", None) == fname:
                            for k in n2.keywords:
                                if k.arg == jv.id and isinstance(k.value, ast.Constant):
                                    found.add(k.value.value)
                    for n3 in ast.walk(fn):                       # the function's own bindings of the name
                        if isinstance(n3, ast.Assign) and any(isinstance(t, ast.Name) and t.id == jv.id for t in n3.targets):
                            found |= _consts(n3.value)
                    names |= found if found else {"<unnamed:%s:%s>" % (fname, jv.id)}
                else:
                    names.add("<unnamed:%s>" % fname)
    return callers, names


class TheCensus(_Base):
    def test_every_model_call_site_names_a_judge_the_table_declares_and_the_table_names_nothing_else(self):
        callers, names = _census()
        self.assertGreaterEqual(len(callers), 15, "the model-call functions of judge.py: %r" % sorted(callers))
        self.assertFalse([n for n in names if str(n).startswith("<unnamed")], "every call names its judge: %r" % sorted(map(str, names)))
        self.assertEqual(names, set(km.jd.MODEL_CALLERS), "the census and the table agree: a new caller declares itself")
        self.assertTrue(all(v in ("tracking", "user") for v in km.jd.MODEL_CALLERS.values()), km.jd.MODEL_CALLERS)
        self.assertEqual({v for v in km.jd.MODEL_CALLERS.values()}, {"tracking"}, "today every kernel-initiated judge stands down with the switch")

    def test_the_census_resolves_a_name_bound_in_the_function_and_flags_one_it_cannot(self):
        snippet = (
            "def a():\n    which = 'alpha'\n    return _judge_run('m', 's', 'u', judge=which)\n"
            "def b(mode):\n    which = 'beta' if mode else 'gamma'\n    return _judge_run('m', 's', 'u', judge=which)\n"
            "def c(name):\n    return _judge_run('m', 's', 'u', judge=name)\n"
            "def d():\n    which = pick()\n    return _judge_run('m', 's', 'u', judge=which)\n"
            "def e(judge='epsilon'):\n    return _judge_run('m', 's', 'u', judge=judge)\n"
            "def f():\n    return e(judge='zeta')\n")
        callers, names = _census(snippet)
        self.assertEqual(callers, {"a", "b", "c", "d", "e"})
        self.assertEqual({n for n in names if not str(n).startswith("<")}, {"alpha", "beta", "gamma", "epsilon", "zeta"},
                         "a local constant, both arms of a conditional, a default and a caller's constant all count")
        self.assertIn("<unnamed:c:name>", names, "a parameter no caller fills and no default names is flagged")
        self.assertIn("<unnamed:d:which>", names, "a local bound to a call cannot be read: flagged, never silently skipped")

    def test_the_entry_point_stands_a_tracking_judge_down_while_off_and_refuses_an_undeclared_name_while_an_unnamed_call_passes(self):
        class Reached(Exception):
            pass
        saved_engine = km.jd._judge_engine
        def boom():
            raise Reached("the model engine was reached")
        km.jd._judge_engine = boom
        errs = Path(km.jd.ERRORS)   # the module binds its error log at import (the state root alone does not move it)
        before = errs.read_text() if errs.exists() else ""
        try:
            km.jd.TASK_TRACKING_ON = lambda: False
            self.assertEqual(km.jd._judge_run("m", "sys", "user", judge="planner"), "", "off: no call, an empty reply")
            self.assertTrue(km.jd._judge_ctx.paused, "a stand-down, never a failure to count")
            with self.assertRaises(Reached, msg="an unnamed call (a harness, a probe) is not gated: it reaches the engine"):
                km.jd._judge_run("m", "sys", "user")
            km.jd.TASK_TRACKING_ON = lambda: True
            with self.assertRaises(Reached, msg="on: a declared judge reaches the engine"):
                km.jd._judge_run("m", "sys", "user", judge="planner")
            self.assertEqual(km.jd._judge_run("m", "sys", "user", judge="not-a-judge"), "", "an undeclared NAME is refused (round two, low 3)…")
            self.assertTrue(km.jd._judge_ctx.paused, "…as a stand-down, never a failure to count")
            after = errs.read_text() if errs.exists() else ""
            self.assertIn("unregistered-caller", after[len(before):], "…and says so in judge-errors.jsonl")
        finally:
            km.jd._judge_engine = saved_engine

    def test_the_kernel_installs_its_store_as_the_judge_modules_hook_at_import(self):
        # a fresh load of the kernel module, no backend built (round two, low 7: the install sat in the SDK backend's constructor)
        import re
        saved = km.jd.TASK_TRACKING_ON
        km.jd.TASK_TRACKING_ON = lambda: True
        try:
            fresh = load_source("romp_kernel_tasktrack_fresh", os.path.join(BIN, "romp-kernel"))
            self.assertIs(fresh.jd.TASK_TRACKING_ON, fresh._task_tracking_on, "installed by the module's own load, beside the reader")
        finally:
            km.jd.TASK_TRACKING_ON = saved
        ksrc = Path(ROOT, "kernel", "kernel.py").read_text()
        self.assertEqual(len(re.findall(r"^jd\.TASK_TRACKING_ON = _task_tracking_on$", ksrc, re.M)), 1, "one install, at module level")
        self.assertEqual(ksrc.count("jd.TASK_TRACKING_ON = _task_tracking_on"), 1, "…and no second copy in a constructor")
        self.assertIn("TASK_TRACKING_ON = lambda: True", JUDGE_SRC, "the module's default: a hand-run judge pass is the user's")


class TheMeshRoad(_Base):
    """A kernel attached after the flip kept tracking on with its default while the gear showed off with the mixed mark
    (round two, medium 5): the switch rides the adoption road its siblings take, with its stamp in every table."""
    def test_the_switch_is_a_mesh_adopted_setting_with_its_stamp_in_every_table(self):
        self.assertIn(("taskTracking", "task-tracking", km._set_task_tracking), km._MESH_ADOPTED_SETTINGS)
        self.assertIn("task-tracking", km._GT_STORES, "the gear's clock pre-learns the stamp from /version's settingsGt (low 2)")
        self.assertEqual(km._setting_stored_gt("task-tracking"), 0, "no file: nothing to outrank")
        self.assertIs(km._setting_kept_value("task-tracking"), True, "no file: on is what a stood-down gesture keeps")
        km._set_task_tracking(False, gt=4000)
        values, stamps = km._mesh_settings_snapshot()
        self.assertEqual((values["taskTracking"], stamps["task-tracking"]), (False, 4000))
        self.assertEqual(km._setting_stored_gt("task-tracking"), 4000)
        self.assertIs(km._setting_kept_value("task-tracking"), False)
        v = km._version_info()
        self.assertEqual((v["taskTracking"], v["settings"]["taskTracking"], v["settingsGt"]["task-tracking"]), (False, False, 4000),
                         "/version reports the value twice and the stamp once, all from the one snapshot")

    def test_a_stamp_too_large_for_an_int_orders_as_zero_instead_of_raising_out_of_the_report(self):
        # round three, low 1: json parses 1e400 to infinity, and int(inf) raised OverflowError out of the snapshot and /version
        self.assertEqual(km._gt_int(float("inf")), 0); self.assertEqual(km._gt_int(1e400), 0); self.assertEqual(km._gt_int(-1e400), 0)
        self._file().write_text('{"enabled": false, "gt": 1e400}')
        values, stamps = km._mesh_settings_snapshot()
        self.assertEqual((values["taskTracking"], stamps["task-tracking"]), (False, 0))
        v = km._version_info()
        self.assertEqual((v["taskTracking"], v["settingsGt"]["task-tracking"]), (False, 0), "the report survives the stamp")
        self.assertEqual(km._setting_stored_gt("task-tracking"), 0)

    def test_a_kernel_attached_after_the_flip_adopts_the_peers_newer_off_and_an_older_stamp_teaches_nothing(self):
        self.assertTrue(km._task_tracking_on())
        out = km._adopt_peer_settings("TESTHOST", {"settings": {"taskTracking": False}, "settingsGt": {"task-tracking": 7000}})
        self.assertIn("task-tracking", out)
        self.assertFalse(km._task_tracking_on(), "adopted: this kernel's judges stand down too")
        self.assertEqual(km._setting_stored_gt("task-tracking"), 7000, "…under the peer's stamp")
        out = km._adopt_peer_settings("TESTHOST", {"settings": {"taskTracking": True}, "settingsGt": {"task-tracking": 6000}})
        self.assertEqual(out, [], "an older stamp teaches nothing")
        self.assertFalse(km._task_tracking_on())


class ThePushWhileOff(_Base):
    """The off frame carried the outline's real ledgers and ran the archived-tops walk on every push, and its empty
    working and awaiting lists blanked the chat's dots (round two, lows 4 and 9)."""
    def test_the_ledgers_attach_and_the_archived_tops_are_gated_and_the_chat_dots_are_derived_outside_the_build(self):
        ksrc = Path(ROOT, "kernel", "kernel.py").read_text()
        self.assertIn('if (chat_sessions or want_fleet) and not feed.get("off"):', ksrc)
        self.assertIn("_dots_w, _dots_a = _chat_dots_off(now, live_map)", ksrc)
        self.assertIn('_send_client(c, ("working",), {"type": "working", "names": _dots_w, "awaiting": _dots_a})', ksrc)
        self.assertNotIn('"names": feed["working"]', ksrc, "the chat's dots no longer read the frame's list directly")

    def test_the_chat_dots_read_the_sessions_turns_and_waits_without_the_feed_build(self):
        saved = {k: getattr(km, k) for k in ("_alive_sessions", "_parse_cached", "_merge_live_atoms", "_session_working", "_session_awaiting", "build_feed")}
        try:
            km._alive_sessions = lambda now, live_map: [{"sid": "s1", "name": "web", "path": "/p1"}, {"sid": "s2", "name": "api", "path": "/p2"},
                                                         {"sid": "s3", "name": "tests", "path": "/p3"}, {"sid": "s4", "name": "docs", "path": None}]
            km._parse_cached = lambda path: None if path == "/p3" else {"turns": [path]}
            km._merge_live_atoms = lambda ps, sid, shown_texts=(): ps
            km._session_working = lambda turns: turns == ["/p1"]
            km._session_awaiting = lambda sid, path, idle, stamp=False: {"why": "a delegate"} if sid == "s2" else None
            def boom(*a, **k):
                raise AssertionError("build_feed called")
            km.build_feed = boom
            self.assertEqual(km._chat_dots_off(0, {}), (["web"], ["api"]),
                             "web works, api awaits; a cold parse (tests) and a pathless row (docs) show no dot; nothing built")
        finally:
            for k, v in saved.items():
                setattr(km, k, v)


class TheClearAllOp(_Base):
    def test_clear_all_builds_no_feed_while_off_and_clears_nothing(self):
        # round two, low 8: the op called build_feed bare, outside the two gated seams
        km._set_task_tracking(False, gt=1)
        saved = (km.build_feed, km._clear_all, km._gesture_store_refusal, km._send_to_app, km._mark_views_dirty)
        calls = []
        def boom(*a, **k):
            raise AssertionError("build_feed called while task tracking is off")
        km.build_feed = boom
        km._clear_all = lambda ids: calls.append(("clear", list(ids))) or {"ok": True}
        km._gesture_store_refusal = lambda client, what, res: calls.append(("refusal", what))
        km._send_to_app = lambda app, m: calls.append(("app", m.get("type")))
        km._mark_views_dirty = lambda: calls.append(("dirty",))
        try:
            km.Handler._dispatch_ws(types.SimpleNamespace(), {"type": "clearAll"}, {})
        finally:
            km.build_feed, km._clear_all, km._gesture_store_refusal, km._send_to_app, km._mark_views_dirty = saved
        self.assertIn(("clear", []), calls, calls)


class TheNudgePass(_Base):
    """The goal nudges wait while tracking is off: the walk runs wake-only, as it does with the nudge toggle off; the
    compaction suggestion and the debt ladder keep the nudge toggle alone."""
    def setUp(self):
        super().setUp()
        self._saved = {k: getattr(km, k) for k in ("_alive_sessions", "_nudge_asks_by_target", "_nudge_look_stat", "_auto_nudge_data",
                                                     "_auto_nudge_session", "_compact_suggest_tick", "_debt_backstop_tick", "_dead_wait_sweep",
                                                     "_auto_nudge_on", "_cleared_ids", "_push_soon")}
        self.calls = []
        km._alive_sessions = lambda now, live_map: [{"sid": "11111111-2222-3333-4444-555555555555", "path": os.path.join(self._td, "t.jsonl"), "name": "web"}]
        km._nudge_asks_by_target = lambda: {}
        km._nudge_look_stat = lambda s, asks, pstat: (("k",), False, False)
        km._auto_nudge_data = lambda: {"enabled": True, "nudged": {}}
        km._auto_nudge_session = lambda s, now, live_map, nudged, waitfor, alive_ids, wake_only=False, cleared=None, reminders=None: self.calls.append(("session", wake_only, reminders))
        km._compact_suggest_tick = lambda sid, s, now: self.calls.append(("compact", None))
        km._debt_backstop_tick = lambda now: self.calls.append(("debt", None))
        km._dead_wait_sweep = lambda alive_ids, nudged, now: self.calls.append(("sweep", None))
        km._auto_nudge_on = lambda: True
        km._cleared_ids = lambda: set()
        km._push_soon = lambda: None

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(km, k, v)
        super().tearDown()

    def test_off_walks_wake_only_with_the_reminders_on_and_keeps_the_compaction_suggestion_and_the_debt_ladder(self):
        km._set_task_tracking(False, gt=1)
        km._auto_nudge_pass(int(time.time()), {}, True)
        kinds = [c[0] for c in self.calls]
        self.assertIn(("session", True, True), self.calls, "the goal walk ran wake-only, the debt reminders handed the toggle (on): %r" % self.calls)
        self.assertIn("compact", kinds, "the compaction suggestion keeps the nudge toggle")
        self.assertIn("debt", kinds, "the debt ladder keeps the nudge toggle")

    def test_the_nudge_toggle_off_hands_the_reminders_off_whatever_the_switch(self):
        km._auto_nudge_on = lambda: False
        km._auto_nudge_pass(int(time.time()), {}, True)
        self.assertIn(("session", True, False), self.calls, self.calls)

    def test_on_walks_the_goals(self):
        km._auto_nudge_pass(int(time.time()), {}, True)
        self.assertIn(("session", False, True), self.calls, self.calls)


class TheDebtLeg(_Base):
    """The reminders about unanswered messages from other sessions need no judge, so the Task tracking switch off does not
    drop them (round two, medium 3: the Auto Nudge row's note said only they still go out, and none did)."""
    def test_the_reminders_ride_the_nudge_toggle_alone(self):
        self.assertTrue(km._debt_leg_open(False, True, True), "tracking off made the walk wake-only; the toggle is on: the reminder goes out")
        self.assertFalse(km._debt_leg_open(False, True, False), "the toggle off: no reminder")
        self.assertFalse(km._debt_leg_open(False, False, False), "…whatever the walk")
        self.assertTrue(km._debt_leg_open(False, False, True))
        self.assertFalse(km._debt_leg_open(True, False, True), "a goal nudge fired this tick: the reminder yields, as before")
        self.assertFalse(km._debt_leg_open(False, True), "no toggle handed down (an older harness): the leg follows the walk")
        self.assertTrue(km._debt_leg_open(False, False))

    def test_the_session_walk_reaches_the_debt_leg_through_it_and_the_pass_hands_the_toggle_down(self):
        ksrc = Path(ROOT, "kernel", "kernel.py").read_text()
        body = ksrc[ksrc.index("def _auto_nudge_session("):]
        body = body[:body.index("\ndef ", 1)]
        self.assertIn("if _debt_leg_open(fired, wake_only, reminders):", body)
        self.assertLess(body.index("if _debt_leg_open(fired, wake_only, reminders):"), body.index("_debt_reminder_outcomes(sid, lt, now)"))
        self.assertIn("fired = _fire_debt_reminder(sid, now, alive_ids)", body)
        self.assertNotIn("if not fired and not wake_only:", body, "the old gate is gone")
        passsrc = ksrc[ksrc.index("def _auto_nudge_pass("):]
        passsrc = passsrc[:passsrc.index("\ndef ", 1)]
        self.assertIn("wake_only=not on or not tracking, cleared=cleared,", passsrc)
        self.assertIn("reminders=on)", passsrc, "the pass hands the toggle down beside the walk's own gate")
        self.assertIn("r = fn(s, now, live_map, nudged, waitfor, alive_ids, wake_only, cleared, reminders)", ksrc, "the look decorator forwards it")


if __name__ == "__main__":
    unittest.main()
