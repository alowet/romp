#!/usr/bin/env python3
"""The read-only observability GETs (both teams' surveys, 2026-08-24): GET /feed.json — exactly what
build_feed ships to the board — and GET /classify?id=<sid> — one session's live classification as
the kernel derives it, a JOIN over reads that already exist (never a second predicate
implementation). Both serve-token-gated, read-only, no side effects. Drives the REAL Handler over
HTTP (the test_tag_route idiom). Synthetic only.

/feed.json answers through _pure_feed, never _cached_feed (2026-09-08): the pusher's door diffs the
bells on its cold branch (_feed_notifications advances _NOTIFY_PREV and prunes notify-cards.json),
pushes the app badge and fills the pusher's cache — so on a headless kernel, where nothing ever
warms _built_feed, a monitoring script's GET did all four. The pure path serves the pusher's copy
while the pusher has an audience, else its own build, gated on the pusher's REBUILD_MIN_S and
_views_dirty; it never fills _built_feed (a 1 Hz poller would otherwise keep the pusher on its
serve branch and mute every bell)."""
import inspect
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
SourceFileLoader("romp_event_model", os.path.join(BIN, "romp-event-model")).load_module()
SourceFileLoader("romp_judge", os.path.join(BIN, "romp-judge")).load_module()
km = SourceFileLoader("romp_kernel_obs", os.path.join(BIN, "romp-kernel")).load_module()
jd = km.jd

SID = "11111111-2222-3333-4444-555555555555"


def _client(app):
    """A fake WS client of `app` whose frames land in the returned list (the test_close_confirm shape)."""
    frames = []
    return {"app": app, "alive": True, "send": lambda s: frames.append(json.loads(s))}, frames


def _state_snapshot(root):
    """Every file under STATE with its (mtime_ns, size) — the read-only-ness witness."""
    out = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            st = p.stat()
            out[str(p)] = (st.st_mtime_ns, st.st_size)
    return out


class ObservabilityRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), km.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self._state = jd.STATE
        jd.STATE = Path(self.td.name)
        km._flags_cache.clear()
        self._saved = (km._tmux_sessions, km.build_feed, km._NOTIFY_PREV[0], km._BADGE_LAST[0],
                       getattr(km, "_PURE_FEED", None), km._views_dirty[0], list(km._clients))
        km._tmux_sessions = lambda: {}
        km._built_feed[:] = [None, None, 0, 0]     # a cold pusher cache: headless, nothing warmed it
        km._PURE_FEED = None                        # …and no earlier GET's build either
        km._views_dirty[0] = 0.0
        del km._clients[:]

    def tearDown(self):
        (km._tmux_sessions, km.build_feed, km._NOTIFY_PREV[0], km._BADGE_LAST[0],
         km._PURE_FEED, km._views_dirty[0], clients) = self._saved
        del km._clients[:]
        km._clients.extend(clients)
        jd.STATE = self._state
        km._flags_cache.clear()
        km._built_feed[:] = [None, None, 0, 0]
        self.td.cleanup()

    def _get(self, path, token=True):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        req = urllib.request.Request(url, headers=(
            {"X-Romp-Token": os.environ["ROMP_SERVE_TOKEN"]} if token else {}))
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            return e.code, (e.read() or b"").decode()

    def test_both_routes_are_token_gated(self):
        self.assertEqual(self._get("/feed.json", token=False)[0], 403)
        self.assertEqual(self._get("/classify?id=" + SID, token=False)[0], 403)

    def test_feed_json_is_exactly_the_boards_payload_and_read_only(self):
        (jd.STATE / "goals").mkdir(parents=True, exist_ok=True)
        before = _state_snapshot(self.td.name)
        st, d = self._get("/feed.json")
        self.assertEqual(st, 200)
        self.assertEqual(d.get("type"), "feed", "the exact build_feed shape, not a re-derivation")
        self.assertIn("asks", d)
        self.assertIn("now", d)
        # the top-level keys a reader of this route can lean on: build_feed's, plus the build id
        # every served payload carries (the pure path claims one like the pusher's builds do)
        for key in ("type", "asks", "working", "awaiting", "now", "buildId", "order", "sessions", "selfHost"):
            self.assertIn(key, d, "the answer shape is build_feed's own")
        self.assertEqual(_state_snapshot(self.td.name), before, "a GET writes nothing")

    def test_feed_json_on_a_cold_kernel_moves_nothing(self):
        """The defect (2026-09-08): a headless kernel never warms _built_feed, so every GET took
        _cached_feed's cold branch — which is the PUSHER's transition event: it pruned the bell's
        per-card overrides on disk, advanced the notification baseline past changes nobody had been
        told about, pushed a badge frame to the shells, and filled the pusher's cache. A read does
        none of that."""
        armed = json.dumps({"*": True, SID + ":g1": True}, sort_keys=True)   # a master bell + one armed
        (jd.STATE / "notify-cards.json").write_text(armed)                    # card no feed lists any more
        sentinel = {SID + ":g0": "working"}          # the baseline the next PUSHER build must diff against
        km._NOTIFY_PREV[0] = sentinel
        km._BADGE_LAST[0] = None                     # nothing sent since boot: a push here would be a first
        shell, frames = _client("shell")
        km._clients.append(shell)
        st, d = self._get("/feed.json")
        self.assertEqual(st, 200)
        self.assertEqual(d.get("type"), "feed")
        self.assertEqual((jd.STATE / "notify-cards.json").read_text(), armed,
                         "the armed card survives: pruning is the pusher's event, not a read's")
        self.assertIs(km._NOTIFY_PREV[0], sentinel, "the notification baseline did not advance")
        self.assertEqual(frames, [], "no badge frame reached the shell")
        self.assertIsNone(km._BADGE_LAST[0])
        self.assertIsNone(km._built_feed[1], "the pusher's cache is not filled by a read")

    def test_feed_json_reuses_its_build_inside_the_rebuild_window_and_rebuilds_on_dirty(self):
        """A poller hitting the route every second must not pay a build per hit: the pure path keeps
        its own copy, gated on the pusher's existing REBUILD_MIN_S and _views_dirty — a mutation the
        sig cannot see rebuilds at once, and an aged copy rebuilds; nothing else does."""
        calls = []

        def counting_build(now, tmux):
            calls.append(now)
            return {"type": "feed", "asks": [], "working": [], "awaiting": [], "now": now}

        km.build_feed = counting_build
        self.assertEqual(self._get("/feed.json")[0], 200)
        self.assertEqual(self._get("/feed.json")[0], 200)
        self.assertEqual(len(calls), 1, "two GETs inside REBUILD_MIN_S: one build")
        km._views_dirty[0] = time.time()             # an optimistic kernel-side mutation postdates the build
        self.assertEqual(self._get("/feed.json")[0], 200)
        self.assertEqual(len(calls), 2, "a dirty mark rebuilds")
        payload, built_at, started = km._PURE_FEED
        km._PURE_FEED = (payload, built_at - km.REBUILD_MIN_S - 1, started)   # age the copy past the window
        self.assertEqual(self._get("/feed.json")[0], 200)
        self.assertEqual(len(calls), 3, "past REBUILD_MIN_S the copy is stale and rebuilds")
        self.assertIsNone(km._built_feed[1], "none of those builds reached the pusher's slot")

    def test_the_routes_audience_predicate_is_the_pushers(self):
        # the route serves the pusher's copy only while the pusher would build one: the two must ask
        # the same question, or the route serves a frozen board (or builds needlessly) the day _push's
        # want_feed changes. Pinned as text: one tuple, two sites.
        src = inspect.getsource(km)
        want = 'any(c["app"] in ("feed", "fleet", "chat") for c in targets)'
        ours = 'any(c["app"] in ("feed", "fleet", "chat") for c in _clients)'
        self.assertIn(want, src, "_push's want_feed predicate")
        self.assertIn(ours, src, "_pusher_has_feed_audience's predicate")
        self.assertEqual(want.replace("targets", ""), ours.replace("_clients", ""),
                         "the route's audience question is _push's, over the same app ids")

    def test_feed_json_serves_the_pushers_copy_only_while_the_pusher_has_an_audience(self):
        """With a client riding the feed payload the pusher maintains _built_feed, and the route
        serves exactly that — what the panes see, no build. When the audience leaves the pusher stops
        rebuilding and the slot freezes at the last disconnect, so it is no longer the answer: the
        route builds its own copy and leaves the pusher's slot as it found it."""
        calls = []

        def counting_build(now, tmux):
            calls.append(now)
            return {"type": "feed", "asks": [], "working": [], "awaiting": [], "now": now, "fresh": True}

        km.build_feed = counting_build
        warm = {"type": "feed", "asks": [], "working": [], "awaiting": [], "now": 1, "buildId": 7, "warm": True}
        km._built_feed[:] = [("SIG",), warm, time.time(), time.time()]
        feed_client, _ = _client("feed")
        km._clients.append(feed_client)
        st, d = self._get("/feed.json")
        self.assertEqual(st, 200)
        self.assertEqual(d, warm, "the pusher's copy, exactly")
        self.assertEqual(calls, [], "no build while the pusher maintains the slot")
        km._clients.remove(feed_client)              # the last pane closes: the pusher stops rebuilding
        st, d = self._get("/feed.json")
        self.assertEqual(st, 200)
        self.assertEqual(len(calls), 1, "a frozen copy is not served: the route builds its own")
        self.assertTrue(d.get("fresh"))
        self.assertIs(km._built_feed[1], warm, "…and the pusher's slot is untouched")

    def test_classify_requires_an_id(self):
        st, _ = self._get("/classify")
        self.assertEqual(st, 400)

    def test_classify_joins_the_existing_reads_and_is_read_only(self):
        # seed the stores the joined reads consume: a progressing state transition, and a nudge
        # ledger holding this session's goal record (deadWait flag) + a walk-gate journal entry
        (jd.STATE / "states").mkdir(parents=True, exist_ok=True)
        (jd.STATE / "states" / (SID + ".jsonl")).write_text(
            json.dumps({"state": "working", "t": 1000}) + "\n")
        (jd.STATE / "auto-nudge.json").write_text(json.dumps({
            "enabled": True,
            "nudged": {SID + ":g1": {"deadWait": True, "anchor": 5, "at": 6},
                       "someone-else:g9": {"at": 7}},
            "walkGates": {SID: {"gate": "compacting", "at": 8},
                          "someone-else": {"gate": "open-turn", "at": 9}}}))
        km._autonudge_cache.clear()
        before = _state_snapshot(self.td.name)
        st, d = self._get("/classify?id=" + SID)
        self.assertEqual(st, 200)
        self.assertEqual(d["id"], SID)
        self.assertFalse(d["live"], "no live snapshot in this world")
        self.assertEqual(d["state"], {"value": "working", "t": 1000}, "_last_state verbatim")
        self.assertFalse(d["idle"], "the nudge gate's own idle rule: working is progressing")
        self.assertIn("_PROGRESSING_STATES", d["idleRule"], "the input's provenance rides the payload")
        self.assertIsNone(d["awaiting"])
        self.assertIsNone(d["waitingOn"])
        self.assertEqual(d["owesAsks"], [])
        self.assertEqual(d["nudge"]["records"], {SID + ":g1": {"deadWait": True, "anchor": 5, "at": 6}},
                         "only THIS session's ledger rows — deadWait flags ride verbatim")
        self.assertEqual(d["nudge"]["walkGates"], {SID: {"gate": "compacting", "at": 8}},
                         "…and its walk-gate journal entries")
        self.assertTrue(d["nudge"]["enabled"])
        self.assertEqual(_state_snapshot(self.td.name), before, "a GET writes nothing")

    def test_classify_idle_when_the_state_says_stopped(self):
        (jd.STATE / "states").mkdir(parents=True, exist_ok=True)
        (jd.STATE / "states" / (SID + ".jsonl")).write_text(
            json.dumps({"state": "waiting", "t": 2000}) + "\n")
        st, d = self._get("/classify?id=" + SID)
        self.assertTrue(d["idle"])


if __name__ == "__main__":
    unittest.main()
