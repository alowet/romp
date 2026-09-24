#!/usr/bin/env python3
"""/perf's kernel parse counter names the road each parse took (the reparse investigation of 2026-09-24).

`parses.kernel` counts every parse-store miss the kernel's _parse asked for, and `parses.bytes` added the leaf's WHOLE
size at every one of them, whichever road em.parse_session then took. A fold reads only the appended records and a
serve or a restore reads none of the transcript before its cut, so a session that took one whole parse and then folded
five appends was booked as six whole parses and six times its size. On a synthetic lab kernel 69 kernel misses read as
7.18 GB while 6 of the 84 misses in all were whole parses; the counter was read as "every miss re-parses the whole
transcript", which is what started the investigation. Pinned here: every miss is counted under the road it took
(`parses.byRoad`: serve, fold, restore, full, bypass, fallback), the roads sum to `kernel`, a store hit moves no road,
the road is the last one _assemble named (a serve or a whole parse that raises names "fallback" after itself), and
`wholeBytes` adds the leaf's size only for the roads that walk the transcript from its first record (full, bypass,
fallback). Synthetic transcripts only: invented notes-api text, a private placeholder sid."""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from romp_load import load_source

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
# Hermetic state BEFORE the loads — they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
Path(os.environ["XDG_STATE_HOME"], "romp").mkdir(parents=True, exist_ok=True)
Path(os.environ["XDG_STATE_HOME"], "romp", "session-hosts").write_text("off\n")   # this root is the module's own: no host spawns
load_source("romp_event_model", os.path.join(BIN, "romp-event-model"))
load_source("romp_judge", os.path.join(BIN, "romp-judge"))
km = load_source("romp_kernel_parse_roads", os.path.join(BIN, "romp-kernel"))
jd, em = km.jd, km.em

SID = "c0ffee00-0924-4aaa-8bbb-000000000524"   # a private synthetic sid (CLAUDE.md, goal-store fixtures)
NOW = 1790000000
ROADS = ("serve", "fold", "restore", "full", "bypass", "fallback")
WORDS = ("search", "index", "fixture", "retry", "budget", "cap", "cursor", "page", "token", "schema", "route", "green")


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def transcript(t0, turns=240, compact_every=80):
    """A notes-api session: typed prompts, text replies, a compaction every `compact_every` turns (so a document has a cut)."""
    recs, parent, t = [], None, t0
    for k in range(turns):
        if k and k % compact_every == 0:
            b, s = "pr-b%d" % k, "pr-s%d" % k
            recs.append({"type": "system", "subtype": "compact_boundary", "uuid": b, "parentUuid": None, "logicalParentUuid": parent,
                         "timestamp": iso(t), "compactMetadata": {"trigger": "auto", "preTokens": 160000, "postTokens": 9000}})
            recs.append({"type": "user", "uuid": s, "parentUuid": b, "timestamp": iso(t + 1), "isCompactSummary": True,
                         "message": {"role": "user", "content": "summary so far: the notes-api search is wired through step %d" % k}})
            parent, t = s, t + 2
        u, a = "pr-u%d" % k, "pr-a%d" % k
        words = " ".join(WORDS[(k + i) % len(WORDS)] for i in range(40))
        recs.append({"type": "user", "uuid": u, "parentUuid": parent, "timestamp": iso(t), "promptSource": "typed", "cwd": "/w/notes-api",
                     "message": {"role": "user", "content": "step %d of the notes-api search: %s" % (k, words)}})
        recs.append({"type": "assistant", "uuid": a, "parentUuid": u, "timestamp": iso(t + 20), "cwd": "/w/notes-api",
                     "message": {"id": "msg_pr%d" % k, "role": "assistant", "stop_reason": "end_turn",
                                 "content": [{"type": "text", "text": "done with step %d: %s" % (k, words * 3)}]}})
        parent, t = a, t + 60
    return recs


def turn(t, k, parent):
    u, a = "pr-xu%d" % k, "pr-xa%d" % k
    return [{"type": "user", "uuid": u, "parentUuid": parent, "timestamp": iso(t), "promptSource": "typed", "cwd": "/w/notes-api",
             "message": {"role": "user", "content": "follow-up %d on the notes-api search" % k}},
            {"type": "assistant", "uuid": a, "parentUuid": u, "timestamp": iso(t + 20), "cwd": "/w/notes-api",
             "message": {"id": "msg_prx%d" % k, "role": "assistant", "content": [{"type": "text", "text": "done with %d" % k}],
                         "stop_reason": "end_turn"}}]


class _Roads(unittest.TestCase):
    """A synthetic leaf under a per-test state root, parsed through the kernel's own _parse (the store, the mode, /perf)."""

    @classmethod
    def setUpClass(cls):
        km._display_sdk_human(SID)          # builds the backend once: its setter installs the owner hook and clears the
        #                                      store, which must never happen between a test's parses (tests/test_shared_parse.py)

    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, True)
        self.saved_state, self.saved_ckpt = jd.STATE, em._CKPT_DIR_FN
        jd._rebind_state(self.td / "state")
        for d in ("states", "checkpoints"):
            (jd.STATE / d).mkdir(parents=True, exist_ok=True)
        (jd.STATE / "session-hosts").write_text("off\n")                  # this state root is the test's own: no host spawns
        em.set_checkpoint_dir(lambda: jd.STATE / "checkpoints")
        (self.td / "proj").mkdir()
        self.leaf = str(self.td / "proj" / (SID + ".jsonl"))
        self.recs = transcript(NOW - 86400)
        with open(self.leaf, "w") as f:
            f.write("".join(json.dumps(r) + "\n" for r in self.recs))
        self.fresh()

    def tearDown(self):
        self.fresh()
        em.set_checkpoint_dir(self.saved_ckpt)
        jd._rebind_state(self.saved_state)

    def fresh(self):
        """A kernel restart's in-memory side: no assembly entry, no stored parse, no read memo."""
        with em._JSONL_CACHE_LOCK:
            em._JSONL_CACHE.clear()
        with em._ASM_LOCK:
            em._ASM_CACHE.clear()
        em._TRAILING_CACHE.clear()
        with em._ASM_CKPT_LOCK:
            em._HYDRATED.clear(); em._HYDRATED_BYTES[0] = 0
        em._LAZY_FILES.clear()
        with em._MAT_LOCK:
            em._MAT_LRU.clear()
        jd.parse_cache_clear()
        km._parse_mode.clear()

    def append(self, recs):
        self.recs += recs
        with open(self.leaf, "a") as f:
            f.write("".join(json.dumps(r) + "\n" for r in recs))

    def append_turn(self, k):
        last = next(r["uuid"] for r in reversed(self.recs) if r.get("uuid"))
        t = max(em.parse_z(r["timestamp"]) for r in self.recs if r.get("timestamp"))
        self.append(turn(t + 60, k, last))

    def parse(self):
        """The kernel's own ask, and the road it took (the mode _parse records for the chat fold)."""
        km._parse(self.leaf, SID, NOW)
        return km._parse_mode[self.leaf]

    @staticmethod
    def counters():
        """/perf's parses block as the route serves it."""
        p = km._PERF_STATS.snapshot()["parses"]
        return {"kernel": p["kernel"], "hits": p["hits"], "wholeBytes": p.get("wholeBytes"), "bytes": p.get("bytes"),
                "byRoad": dict(p.get("byRoad") or {})}

    @staticmethod
    def asm():
        """The event model's own road counters, kept inside _assemble apart from /perf (the premise of a raising road)."""
        with em._ASM_CKPT_LOCK:
            return dict(em._ASM_STATS)

    @staticmethod
    def moved(a, b):
        roads = set(a["byRoad"]) | set(b["byRoad"])
        return {"kernel": b["kernel"] - a["kernel"], "hits": b["hits"] - a["hits"],
                "wholeBytes": None if b["wholeBytes"] is None else b["wholeBytes"] - (a["wholeBytes"] or 0),
                "bytes": None if b["bytes"] is None else b["bytes"] - (a["bytes"] or 0),
                "byRoad": {r: b["byRoad"].get(r, 0) - a["byRoad"].get(r, 0) for r in roads
                           if b["byRoad"].get(r, 0) != a["byRoad"].get(r, 0)}}


class ParseCounterNamesItsRoad(_Roads):
    """The investigation's red: one whole parse and five folds through the kernel's _parse. On main the six misses carry no
    road and `bytes` moved by the leaf's whole size at each, six times the leaf."""

    def test_folds_are_not_counted_as_whole_parses(self):
        c0 = self.counters()
        modes = [self.parse()]                                            # the kernel's own ask: a whole parse
        size0 = os.path.getsize(self.leaf)
        for k in range(5):
            self.append_turn(10 + k)
            modes.append(self.parse())
        self.parse()                                                      # nothing moved: served from the store
        d = self.moved(c0, self.counters())
        self.assertEqual(modes, ["full"] + ["fold"] * 5, "the premise: one whole parse, then five folds")
        self.assertEqual((d["kernel"], d["hits"]), (6, 1), "kernel still counts every miss, and the hit is a hit")
        self.assertEqual(d["byRoad"], {"full": 1, "fold": 5},
                         "each miss under the road it took: %r (bytes moved %r for a %d-byte leaf)" % (d["byRoad"], d["bytes"], size0))
        self.assertEqual(d["wholeBytes"], size0, "bytes count the whole parse's leaf once, at its size then, and no fold's")
        self.assertEqual(sum(self.counters()["byRoad"].values()), self.counters()["kernel"], "the roads sum to the misses")


class EveryRoadIsNamed(_Roads):
    """Each road _assemble reports lands under its own name; only the three that walk the transcript from its first record
    book the leaf's size."""

    def test_a_states_row_is_a_serve_and_books_no_bytes(self):
        self.parse()
        c0 = self.counters()
        (jd.STATE / "states" / (SID + ".jsonl")).write_text(json.dumps({"t": NOW - 30, "state": "idle"}) + "\n")
        mode = self.parse()                                               # the key moved (the states file), the transcript did not
        d = self.moved(c0, self.counters())
        self.assertEqual(mode, "serve", "the premise: a live-status change serves the entry")
        self.assertEqual((d["kernel"], d["byRoad"], d["wholeBytes"]), (1, {"serve": 1}, 0), d)

    def test_a_restart_over_a_document_is_a_restore_and_books_no_bytes(self):
        self.parse()
        self.assertTrue(em.asm_checkpoint_write(self.leaf, SID, tree=km._parse(self.leaf, SID, NOW)), em.asm_checkpoint_stats())
        self.fresh()                                                      # a restart: the next parse reads the document
        c0 = self.counters()
        mode = self.parse()
        d = self.moved(c0, self.counters())
        self.assertEqual(mode, "restore", "the premise: the document stands and the tail is read from its cut")
        self.assertEqual((d["kernel"], d["byRoad"], d["wholeBytes"]), (1, {"restore": 1}, 0), d)

    def test_a_pending_cut_is_a_bypass_and_books_the_leaf(self):
        self.parse()
        c0 = self.counters()
        saved = jd._PENDING_CUT_FN
        jd.set_pending_cut_provider(lambda fsid: "pr-a200" if fsid == SID else "")   # a bare rollback armed at an old reply
        try:
            mode = self.parse()
        finally:
            jd.set_pending_cut_provider(saved)
        d = self.moved(c0, self.counters())
        self.assertEqual(mode, "bypass", "the premise: a cut parse is a plain whole parse, never cached")
        self.assertEqual((d["kernel"], d["byRoad"], d["wholeBytes"]), (1, {"bypass": 1}, os.path.getsize(self.leaf)), d)

    def test_a_fold_that_raises_is_a_fallback_and_books_the_leaf(self):
        self.parse()
        self.append_turn(1)
        c0 = self.counters()
        with mock.patch.object(em, "_asm_fold", side_effect=RuntimeError("a synthetic fold fault")), \
                contextlib.redirect_stderr(io.StringIO()):
            mode = self.parse()
        d = self.moved(c0, self.counters())
        self.assertEqual(mode, "fallback", "the premise: the fold raised and the parse fell back to a plain whole walk")
        self.assertEqual((d["kernel"], d["byRoad"], d["wholeBytes"]), (1, {"fallback": 1}, os.path.getsize(self.leaf)), d)

    def test_a_serve_that_raises_is_a_fallback_and_books_the_leaf(self):
        """_assemble names a serve before it runs it and appends "fallback" when it raises, so the road is the LAST mode it
        appended: the plain walk that ran. Taking the first booked a serve and no bytes for a parse that walked the whole
        transcript, and handed the chat fold a serve (the review of 2026-09-24; a fold that raises names nothing first)."""
        self.parse()
        (jd.STATE / "states" / (SID + ".jsonl")).write_text(json.dumps({"t": NOW - 30, "state": "idle"}) + "\n")
        c0, a0 = self.counters(), self.asm()
        with mock.patch.object(em, "_asm_serve", side_effect=RuntimeError("a synthetic serve fault")), \
                contextlib.redirect_stderr(io.StringIO()):
            mode = self.parse()
        d, a = self.moved(c0, self.counters()), self.asm()
        self.assertEqual((a["serve"] - a0["serve"], a["fallback"] - a0["fallback"]), (1, 1),
                         "the premise: the event model named the serve, it raised, and the plain walk ran")
        self.assertEqual(mode, "fallback", "the road the chat fold reads is the walk that ran, not the serve that raised")
        self.assertEqual((d["kernel"], d["byRoad"], d["wholeBytes"]), (1, {"fallback": 1}, os.path.getsize(self.leaf)), d)

    def test_a_whole_parse_that_raises_is_a_fallback(self):
        c0, a0 = self.counters(), self.asm()
        with mock.patch.object(em, "_asm_full", side_effect=RuntimeError("a synthetic whole-parse fault")), \
                contextlib.redirect_stderr(io.StringIO()):
            mode = self.parse()                                           # no entry and no document: the whole road, raising
        d, a = self.moved(c0, self.counters()), self.asm()
        self.assertEqual((a.get("full:noDocument", 0) - a0.get("full:noDocument", 0), a["fallback"] - a0["fallback"]), (1, 1),
                         "the premise: the event model named the whole parse, it raised, and the plain walk ran")
        self.assertEqual(mode, "fallback")
        self.assertEqual((d["kernel"], d["byRoad"], d["wholeBytes"]), (1, {"fallback": 1}, os.path.getsize(self.leaf)), d)

    def test_a_cleared_cut_is_a_serve_and_books_no_bytes(self):
        """The reference's serve covers more than a states row: clearing a pending cut moves the key, not the transcript,
        and the held tree is served again."""
        self.parse()
        saved = jd._PENDING_CUT_FN
        jd.set_pending_cut_provider(lambda fsid: "pr-a200" if fsid == SID else "")
        try:
            self.assertEqual(self.parse(), "bypass")
        finally:
            jd.set_pending_cut_provider(saved)
        c0 = self.counters()
        mode = self.parse()                                               # the cut cleared: the cut-free key again
        d = self.moved(c0, self.counters())
        self.assertEqual(mode, "serve", "the premise: the transcript did not move and the held tree was served")
        self.assertEqual((d["kernel"], d["byRoad"], d["wholeBytes"]), (1, {"serve": 1}, 0), d)

    def test_a_dropped_stored_parse_is_a_serve_and_books_no_bytes(self):
        self.parse()
        jd.parse_cache_clear()                                            # the store drops its tree; the event model keeps its own
        c0 = self.counters()
        mode = self.parse()
        d = self.moved(c0, self.counters())
        self.assertEqual(mode, "serve", "the premise: a miss over an unmoved transcript the event model still holds")
        self.assertEqual((d["kernel"], d["byRoad"], d["wholeBytes"]), (1, {"serve": 1}, 0), d)


class TheCollector(unittest.TestCase):
    """_PerfStats.parse and the snapshot on their own: every road is named from the start, the whole roads alone book
    bytes, and the snapshot hands out copies."""

    def test_a_fresh_collector_names_every_road_at_zero(self):
        p = km._PerfStats().snapshot()["parses"]
        self.assertEqual(p.get("byRoad"), dict.fromkeys(ROADS, 0))
        self.assertEqual(p.get("wholeBytes"), 0)
        self.assertNotIn("bytes", p, "retired: it added the leaf's size at every miss, a fold's and a serve's included")

    def test_only_the_whole_roads_book_bytes(self):
        st = km._PerfStats()
        for road, n in (("full", 1000), ("bypass", 200), ("fallback", 30), ("fold", 7000), ("serve", 7000), ("restore", 7000)):
            st.parse(SID, n, road=road)
        p = st.snapshot()["parses"]
        self.assertEqual((p["kernel"], p.get("byRoad"), p.get("wholeBytes")), (6, dict.fromkeys(ROADS, 1), 1230), p)
        p["byRoad"]["full"] = 99
        self.assertEqual(st.snapshot()["parses"]["byRoad"]["full"], 1, "the snapshot's split is a copy")

    def test_the_reference_names_every_road_and_the_whole_bytes(self):
        """docs/reference.md's `parses` passage names each road the collector counts, so a road added to one is added to
        the other (the precedent: the chatFullWhy and builds.feed.memo passages in tests/test_perf_stats.py)."""
        doc = Path(HERE).parent.joinpath("docs", "reference.md").read_text()
        passage = doc[doc.index("- `parses`: the cold event-model parses"):]
        passage = passage[:passage.index("\n- ")]
        self.assertEqual(km._PerfStats.PARSE_ROADS, ROADS)
        for name in ROADS + ("byRoad", "wholeBytes"):
            self.assertIn("`%s`" % name, passage, name)
        self.assertTrue(set(km._PerfStats.WHOLE_ROADS) < set(ROADS))


if __name__ == "__main__":
    unittest.main()
