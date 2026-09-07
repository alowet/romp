#!/usr/bin/env python3
"""The pusher cycle takes ONE liveness snapshot (the 2026-08-10 CPU fix).

Every _tmux_sessions() read forks `tmux list-sessions` and sweeps the whole SDK reg registry.
The pusher's cycle used to take NINE of them — one inside _push plus one per tick job — at its
0.5s cadence, which profiling attributed as the kernel's single hottest thread (~50-90% of one
core sustained, three quarters of total process CPU). The jobs all take the map as a parameter
by design, so the fix is purely structural: one snapshot at cycle start, handed to everything.

SYNTHETIC fixtures only: placeholder UUIDs, invented names.
"""
import json
import os
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
# Hermetic state BEFORE the loads — they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
SourceFileLoader("romp_event_model", os.path.join(BIN, "romp-event-model")).load_module()
SourceFileLoader("romp_judge", os.path.join(BIN, "romp-judge")).load_module()
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
km = SourceFileLoader("romp_kernel_pushsnap", os.path.join(BIN, "romp-kernel")).load_module()
jd = km.jd

NOW = 1781100000
SID = "11111111-2222-3333-4444-555555555555"


class OneSnapshotPerCycle(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        td = Path(self.td.name)
        self.saved = (jd.NAMES, jd.PROJECTS, jd.CAPDIR, jd.ARCHDIR, jd.GOALDIR, jd.STATE,
                      km.NAMES, km.Sessions.live, km._sdk,
                      km._auto_nudge_tick, km._clear_done_working_notes)
        names = td / "names"; names.mkdir()
        proj = td / "projects"; proj.mkdir()
        jd.NAMES, jd.PROJECTS = names, proj
        jd.CAPDIR, jd.ARCHDIR, jd.GOALDIR = td / "captions", td / "archive", td / "goals"
        for d in (jd.CAPDIR, jd.ARCHDIR, jd.GOALDIR):
            d.mkdir()
        jd.STATE = td
        km.NAMES = names
        km._sdk = lambda: None
        # a real session on disk, so the push leg builds it and the DEEP helpers (the awaiting/bg-task
        # sources, the feed's per-session gates) actually run — the reads this fix removes hide there
        cdir = td / "work"; cdir.mkdir()
        pdir = proj / jd.re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(str(cdir)))
        pdir.mkdir(parents=True)
        rec = {"type": "user", "timestamp": "2026-06-11T00:00:00.000Z", "uuid": "u1",
               "parentUuid": None, "promptSource": "typed",
               "message": {"role": "user", "content": "hello there"}}
        (pdir / (SID + ".jsonl")).write_text(json.dumps(rec) + "\n")
        (names / SID).write_text("web\t%s\t#abcdef\n" % str(cdir))
        self.row = {SID: {"state": "waiting", "since": NOW - 5, "model": "", "effort": "",
                          "context": None, "compactPct": None, "color": None, "mode": "",
                          "backend": "tmux"}}
        self.saved_clients = list(km._clients)

    def tearDown(self):
        (jd.NAMES, jd.PROJECTS, jd.CAPDIR, jd.ARCHDIR, jd.GOALDIR, jd.STATE,
         km.NAMES, km.Sessions.live, km._sdk,
         km._auto_nudge_tick, km._clear_done_working_notes) = self.saved
        with km._clients_lock:
            km._clients[:] = self.saved_clients
        km._live_scope.snapshot = None
        self.td.cleanup()

    def test_one_cycle_reads_liveness_once_however_deep_the_call(self):
        # count REAL liveness reads (Sessions.live — the tmux fork + reg sweep), not the delegator:
        # inside the cycle's scope every _tmux_sessions() call, at any depth of the build stack,
        # must be served the cycle's one snapshot instead of taking a fresh read
        reads = []
        row = self.row
        km.Sessions.live = lambda: (reads.append(1), dict(row))[1]
        got = {}
        # bracket the job list: the FIRST and the LAST tick job must both receive the cycle's one map
        km._auto_nudge_tick = lambda now, tmux: got.setdefault("first", tmux)
        km._clear_done_working_notes = lambda now, tmux: got.setdefault("last", tmux)
        sent = []
        with km._clients_lock:   # a connected chat client, so the _push leg builds for real
            km._clients[:] = [{"app": "chat", "alive": True, "wid": "", "qbytes": 0,
                               "send": sent.append}]
        km._pusher_cycle()
        self.assertEqual(len(reads), 1, "one fork + one reg sweep per cycle — that IS the fix")
        self.assertIn(SID, got.get("first") or {}, "the jobs got the cycle's snapshot")
        self.assertIs(got.get("first"), got.get("last"))
        self.assertTrue(any('"type": "session"' in s or '"type":"session"' in s.replace(" ", "")
                            for s in sent), "the push leg really built the session")
        self.assertIsNone(km._live_scope.snapshot, "the scope ends with the cycle")
        # OUTSIDE a cycle the delegator reads fresh — a WS handler must never see a stale snapshot
        n = len(reads)
        km._tmux_sessions()
        self.assertEqual(len(reads), n + 1)

    def test_build_session_reuses_the_callers_snapshot(self):
        # build_session used to take a FRESH liveness read per session build (the bgTasks line) — on
        # the pusher's hottest path that was a tmux fork + reg sweep per tab per push
        reads = []
        row = self.row
        km.Sessions.live = lambda: (reads.append(1), dict(row))[1]
        m = km.build_session(SID, NOW, dict(self.row))
        self.assertIsNotNone(m)
        self.assertEqual(reads, [], "a provided snapshot is enough — no fresh liveness reads")


class LazyChatSerialization(unittest.TestCase):
    """The chat payload's full serialization is LAZY (round two of the 2026-08-10 CPU fix): steady
    state sends only chatTail suffixes, so eagerly json.dumps-ing the whole multi-MB active-tab
    payload every cycle — profiled as ~half the pusher's remaining busy samples — bought nothing.
    _send_chat materializes it only on the untrimmed full-send branch and hands it back for reuse."""

    def _client(self, caught_up_from=None, sid="s1", head_uuid="e0"):
        sent = []
        c = {"app": "chat", "alive": True, "send": lambda s: sent.append(s), "sent": {}}
        if caught_up_from is not None:
            c["echat"] = {sid: (head_uuid, caught_up_from)}
        return c, sent

    def _payload(self, sid="s1", n=5):
        return {"type": "session", "id": sid, "status": {"state": "working"},
                "events": [{"uuid": "e%d" % i, "kind": "user", "text": "m%d" % i} for i in range(n)]}

    def test_a_caught_up_client_gets_a_tail_and_no_full_serialization_happens(self):
        m = self._payload()
        c, sent = self._client(caught_up_from=0)
        out = km._send_chat(c, m, None, 3, False)
        self.assertIsNone(out, "no full send → the lazy serialization was never materialized")
        self.assertEqual(len(sent), 1)
        got = json.loads(sent[0])
        self.assertEqual((got["type"], got["from"]), ("chatTail", 3))

    def test_a_fresh_client_materializes_it_once_and_hands_it_back(self):
        m = self._payload()
        c, sent = self._client()                     # no echat state → the full-send branch
        out = km._send_chat(c, m, None, 3, False)
        self.assertIsInstance(out, str, "the full send materialized the serialization")
        self.assertEqual(json.loads(out)["id"], "s1")
        self.assertEqual(sent, [out], "the exact materialized bytes went to the client")
        # a second full-send client REUSES the returned serialization verbatim
        c2, sent2 = self._client()
        out2 = km._send_chat(c2, m, out, 3, False)
        self.assertIs(out2, out)

    def test_unchanged_feed_and_bars_reuse_their_wire_form_across_cycles(self):
        # Round three: with nothing changed, a cycle must not re-serialize the shared payloads at all —
        # measured on a quiet fleet, the per-cycle dumps were ~357KB (feed) + ~1.65MB (bars), ~4MB/s of
        # json.dumps discarded by the dedup. The wire caches key on the cached build's identity (+ a
        # deep-eq on the ledgers attach), so an unchanged second cycle serves the SAME tuple.
        base = OneSnapshotPerCycle("test_one_cycle_reads_liveness_once_however_deep_the_call")
        base.setUp()
        try:
            km.Sessions.live = lambda: dict(base.row)
            frames = []
            with km._clients_lock:
                km._clients[:] = [
                    {"app": "chat", "alive": True, "wid": "", "qbytes": 0, "send": lambda s: None},
                    {"app": "feed", "alive": True, "wid": "", "qbytes": 0, "send": frames.append},
                    {"app": "timeline", "alive": True, "wid": "", "qbytes": 0, "send": lambda s: None},
                ]
            km._feed_wire = km._bars_wire = None
            km._built_feed[:] = [None, None, 0.0, 0.0]
            km._built_timeline[:] = [None, None, 0.0, 0.0]
            km._pusher_cycle()
            w_feed, w_bars = km._feed_wire, km._bars_wire
            self.assertIsNotNone(w_feed, "the first cycle made the feed's wire form once")
            # the body is a lazy cell: this feed client announces no delta, so its whole frame went and the cell
            # holds the one whole encode of the build; the signature is the split's tuple
            self.assertIsInstance(w_feed[3], km._LazyWire)
            self.assertTrue(w_feed[3].materialized(), "a legacy client took the whole frame: serialized once")
            self.assertEqual(w_feed[4], km._parts_sig(w_feed[5]))
            n = len(frames)
            km._pusher_cycle()
            self.assertIs(km._feed_wire, w_feed, "unchanged feed → the SAME wire tuple, no re-dump")
            if w_bars is not None:   # bars need a warmed timeline build; when present, same contract
                self.assertIs(km._bars_wire, w_bars, "unchanged bars → the SAME wire tuple, no re-dump")
            self.assertEqual(len(frames), n, "…and the deduped client got nothing new")
        finally:
            base.tearDown()
            km._feed_wire = km._bars_wire = None
            km._built_feed[:] = [None, None, 0.0, 0.0]
            km._built_timeline[:] = [None, None, 0.0, 0.0]

    def test_send_client_honors_a_precomputed_dedup_sig(self):
        # feed/bars carry volatile keys, so _dedup_sig re-dumps the FILTERED payload per call — the
        # pusher now computes it once per cycle and passes it down. Prove the parameter is authoritative:
        # two payloads differing in a NON-volatile field but sharing a passed sig must dedup.
        sent = []
        c = {"app": "feed", "alive": True, "send": lambda s: sent.append(s)}
        m1 = {"type": "bars", "now": 1, "x": "a"}
        m2 = {"type": "bars", "now": 2, "x": "b"}    # x differs → a recomputed sig would NOT dedup
        km._send_client(c, ("t",), m1, pre=json.dumps(m1), sig="same")
        km._send_client(c, ("t",), m2, pre=json.dumps(m2), sig="same")
        self.assertEqual(len(sent), 1, "the passed sig, not a recomputation, drives the dedup")


if __name__ == "__main__":
    unittest.main()
