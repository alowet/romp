"""Timeline ships in TWO messages so the lanes paint before the heavy bars (the user 2026-06-25, who found startup
still slow and wanted everything else loaded with the bars loaded after).

build_timeline(with_bars=False) builds only the LANES SKELETON (sessions/status, no turns/judging/messages/
nudges); _push sends it as {type:"data"} FIRST, then the cached full build's detail rides a {type:"bars"}
message. Profiling drove this: the timeline was 551ms/1940KB and ~95% of that is bars+judging, so the
skeleton is tiny and lands immediately. (The dead `tokens` field — nothing reads it — was dropped too.)
"""
import inspect
import json
import os
import unittest
from importlib.machinery import SourceFileLoader
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
# Hermetic state BEFORE the loads — they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
km = SourceFileLoader("romp_kernel", os.path.join(BIN, "romp-kernel")).load_module()


class BuildGating(unittest.TestCase):
    def test_build_timeline_gates_the_heavy_fields_on_with_bars(self):
        src = inspect.getsource(km.build_timeline)
        self.assertIn("with_bars=True", src, "the skeleton/bars switch")
        self.assertIn("if not with_bars:", src, "skeleton skips the per-segment bar dicts")
        self.assertIn("if with_bars:", src, "turns[sid] + judging + messages are gated")
        self.assertNotIn('"tokens"', src, "the dead token field is GONE from the payload (2026-07-07 audit)")
        self.assertNotIn('"nudges"', src, "…and so is the never-rendered nudges array")

    def test_the_host_shim_routes_a_bars_message_to_applyBars(self):
        boot = km._TIMELINE_BOOT
        self.assertIn('m.type==="bars"', boot)
        self.assertIn("panel.applyBars(m)", boot)

    def test_the_host_shim_wraps_its_listener_through_the_page_collector_when_there_is_one(self):
        # The page's performance collector (ui/webview/perf-telemetry.ts) is published on window.__rompPerf by
        # federation.js, which the timeline page loads before this boot (test_browser_owned_order pins the
        # order). Wrapped, the frames the boot dispatches are timed by type like every pane's, so the view's
        # hover/activeChat/revealEvent/models handling is not left inside federation's fed:<type> bracket
        # (2026-09-06); without a collector the plain listener is registered.
        boot = km._TIMELINE_BOOT
        self.assertIn("var onFrame=function(ev){var m=ev.data;if(!m||!panel)return;", boot)
        self.assertIn('window.addEventListener("message",(window.__rompPerf&&window.__rompPerf.wrapFrameHandler)'
                      "?window.__rompPerf.wrapFrameHandler(onFrame):onFrame);", boot)
        self.assertEqual(boot.count('addEventListener("message"'), 1, "one listener, the wrapped one")

    def test_the_lanes_skeleton_does_not_parse_any_transcript(self):
        # cold-start speed (the user 2026-06-26): a fresh kernel (the refresh button = POST /restart) re-parses
        # every transcript (~1.3s). The lanes don't need it — derive them from tmux + goals + the transcript
        # mtime. Only the {type:"bars"} build (with_bars=True) does the real parse.
        calls = {"parse": 0}
        o_ts, o_parse = km._timeline_sessions, km._parse
        km._timeline_sessions = lambda now, tmux, live_only=False: [{"sid": "S", "name": "n", "path": "/no/such/transcript"}]
        km._parse = lambda path, sid, now: (calls.__setitem__("parse", calls["parse"] + 1), {"turns": []})[1]
        try:
            km.build_timeline(0, {}, with_bars=False)
            self.assertEqual(calls["parse"], 0, "the lanes skeleton must NOT parse a transcript")
            km.build_timeline(0, {}, with_bars=True)
            self.assertGreater(calls["parse"], 0, "the bars build DOES parse")
        finally:
            km._timeline_sessions, km._parse = o_ts, o_parse


class TimelinePageLoader(unittest.TestCase):
    """The timeline pane no longer carries the full-pane _pane_spin("host") overlay (the user 2026-06-26): it
    hid the instant #host got its first child — the .romp-tl-wrap on TimelinePanel construction, BEFORE any
    bars — leaving an empty bar gap. The view owns the bars-area loader now (_drawBarsLoader, gated on
    _barsLoaded), so the spinner stays until the deferred {type:"bars"} payload renders."""

    def test_timeline_page_drops_the_full_pane_spin_but_keeps_the_host(self):
        page = km._timeline_page()
        self.assertIn("<div id=host>", page, "the timeline still mounts into #host")
        self.assertNotIn("id=pane-spin", page, "no full-pane _pane_spin overlay (it hid before the bars)")

    def test_other_panes_keep_their_pane_spin(self):
        # the chat/feed/fleet loaders are unaffected — only the timeline's was dropped
        self.assertIn("id=pane-spin", km._pane_spin("content"))


class PushSplit(unittest.TestCase):
    def test_push_ships_the_lanes_skeleton_before_the_bars(self):
        sent = []
        client = {"app": "timeline", "send": sent.append, "sent": {}, "alive": True}
        SKEL = {"type": "timeline", "sessions": [{"id": "S"}], "turns": {}, "judging": [],
                "messages": [], "now": 1, "usage": {}}
        FULL = {"type": "timeline", "sessions": [{"id": "S"}], "turns": {"S": [{"id": "b1"}]},
                "judging": [{"k": "planner"}], "messages": [{"m": 1}], "now": 1}
        o_bt, o_ct, o_tmux, o_sig = (km.build_timeline, km._cached_timeline,
                                     km._tmux_sessions, km._fleet_view_sig)
        km.build_timeline = lambda now, tmux, with_bars=True, live_only=False: (FULL if with_bars else SKEL)
        km._cached_timeline = lambda now, tmux, sig, connect=False: FULL
        km._tmux_sessions = lambda: {}
        km._fleet_view_sig = lambda now, tmux: ("sig",)
        try:
            km._push([client])
        finally:
            (km.build_timeline, km._cached_timeline,
             km._tmux_sessions, km._fleet_view_sig) = o_bt, o_ct, o_tmux, o_sig
        msgs = [json.loads(s) for s in sent]
        types = [m["type"] for m in msgs]
        self.assertIn("data", types)
        self.assertIn("bars", types)
        self.assertLess(types.index("data"), types.index("bars"), "lanes skeleton ships BEFORE the bars")
        skel = msgs[types.index("data")]["data"]
        self.assertEqual(skel["turns"], {}, "the {type:data} message is the lanes skeleton — no bars")
        bars = msgs[types.index("bars")]
        self.assertEqual(bars["turns"], {"S": [{"id": "b1"}]}, "the heavy bars ride the {type:bars} message")
        for k in ("judging", "messages"):
            self.assertIn(k, bars, "the whole time-plotted detail rides the bars message")


class DeadLaneWindow(unittest.TestCase):
    """Dead lanes default to a 12h window and the FIRST cold paint reads no dead session at all (the user
    2026-06-26: "rarely looking at 48h"; "get the main UI up with the live sessions first, dead in background")."""

    def test_dead_lanes_limited_to_12h_live_only_drops_them_all(self):
        now = 1_000_000
        o_alive, o_sessions, o_ordered = km._alive_sessions, km._sessions, km._ordered
        km._alive_sessions = lambda now, tmux: [{"sid": "LIVE", "name": "l", "path": "/l", "mtime": now}]
        km._sessions = lambda now: [
            {"sid": "LIVE", "name": "l", "path": "/l", "mtime": now},
            {"sid": "RECENT", "name": "r", "path": "/r", "mtime": now - 6 * 3600},    # dead, within 12h
            {"sid": "OLD", "name": "o", "path": "/o", "mtime": now - 30 * 3600},      # dead, beyond 12h
        ]
        km._ordered = lambda lst: lst
        try:
            lanes = {s["sid"] for s in km._timeline_sessions(now, {})}
            self.assertEqual(lanes, {"LIVE", "RECENT"}, "a dead lane >12h old is dropped")
            live = {s["sid"] for s in km._timeline_sessions(now, {}, live_only=True)}
            self.assertEqual(live, {"LIVE"}, "live_only drops every dead lane (cold-start first paint)")
        finally:
            km._alive_sessions, km._sessions, km._ordered = o_alive, o_sessions, o_ordered

    def test_cold_connect_builds_live_only_and_wakes_the_producer_for_the_rest(self):
        calls, sent = [], []
        client = {"app": "timeline", "send": sent.append, "sent": {}, "alive": True}
        SK = {"type": "timeline", "sessions": [], "turns": {}, "judging": [], "messages": [],
              "now": 1, "usage": {}}
        FB = {"type": "timeline", "sessions": [], "turns": {"S": []}, "judging": [],
              "messages": [], "now": 1}
        o_bt, o_tmux, o_sig = km.build_timeline, km._tmux_sessions, km._fleet_view_sig
        o_built = list(km._built_timeline)
        km.build_timeline = lambda now, tmux, with_bars=True, live_only=False: (
            calls.append(("bars" if with_bars else "skel", live_only)) or (FB if with_bars else SK))
        km._tmux_sessions = lambda: {}
        km._fleet_view_sig = lambda now, tmux: ("sig",)
        km._built_timeline[0], km._built_timeline[1], km._built_timeline[2] = None, None, 0.0   # cold cache
        km._producer_wake.clear()
        try:
            km._push([client], connect=True)
        finally:
            km.build_timeline, km._tmux_sessions, km._fleet_view_sig = o_bt, o_tmux, o_sig
            km._built_timeline[:] = o_built
        self.assertIn(("skel", True), calls, "cold connect: the lanes skeleton is built LIVE-ONLY")
        self.assertIn(("bars", True), calls, "cold connect: the bars are built LIVE-ONLY (no dead reads)")
        self.assertTrue(km._producer_wake.is_set(), "the full live+dead build is warmed in the background")


if __name__ == "__main__":
    unittest.main()
