#!/usr/bin/env python3
"""build_feed's per-session card memo (T368): a rebuild re-derives only the sessions whose inputs moved.

The pusher keeps the whole feed payload while nothing on the board changes, but any change anywhere rebuilt it
whole, and the rebuild walked every living session's goal tree and per-session derivations (the loop body of
build_feed, now _feed_session_entry) whether or not that session had moved: a cost that scaled with sessions
times goals, not with what changed. The memo (_feed_memo) holds each session's derived entry under a key of every
input the derivation reads (_feed_session_key), invalidated by those inputs alone and never by the clock.

This module drives the REAL build_feed over a hermetic three-session board (the notes-api demo world: web, api
and tests, each with a transcript, a names entry, a live row and a goal store holding one top-level goal) and
pins, per build, how many sessions were derived (/perf builds.feed.memo `derived`) and which component the miss
was attributed to, beside the card the moved input changes:
  * cold: three derivations; unchanged: none; a memoized build equals a from-scratch build byte for byte;
  * one input at a time, each re-deriving ITS session only: a judge verdict (the store file), a user gesture
    (the override journal), a clear (the session's slice of cleared.jsonl), a live-row change, a transcript
    append, a states append, a names rewrite, the hideFromFeed flag;
  * a peer's verdict re-derives the session whose card reads that peer's store (the peers dependency);
  * nudge facts re-derive only cards that read the changed node, including foreign node ids; unrelated
    bookkeeping and undisplayed history do not invalidate, and concurrent writes wait for the next snapshot;
  * a deferral record (the ledger's `deferred` map: the Stalled section, the Blocked filing) minted or retired
    for a node re-derives the card that read that exact node id, a foreign-owned id included, and no other;
  * the clock: two builds ten minutes apart derive nothing and differ in `now`, `buildId` and the cards' age
    tint alone (the fold stamps trgb per build; the memo holds nothing clock-derived);
  * the byte bound (FEED_MEMO_BYTES): entries leave oldest first, counted, and the payload stays complete;
  * a departed session's entry leaves with it; GET /perf reports the memo's counters.

Harness: tests/test_payload_dedup_invariant.py's world (a hermetic state root the kernel's judge is rebound to,
names/ entries and projects/<launch dir>/<sid>.jsonl transcripts discover finds, a fixed live map, a warm first
build so the session-order adoption sits behind the compared builds), extended to three sessions with goal
stores minted the way tests/test_kernel_goal_cache_wiring.py mints them (jd.apply_plan, jd.rollup_status,
jd.save_goals). The parses stay cold, as the feed reads them (cache-only), so a card here is the store's card.
Synthetic fixtures only: private synthetic sids (the goal-store fixture rule: load_goals replays the per-sid
override journal, so a shared placeholder sid would be re-flagged by other modules' rows), invented text.
"""
import json
import os
import re
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from romp_load import load_source

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "test-token-DO-NOT-USE")
# Hermetic state BEFORE the load: the kernel resolves its state root at import time, and only pytest runs
# conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
km = load_source("romp_kernel_feed_session_memo", os.path.join(BIN, "romp-kernel"))
jd = km.jd                              # the kernel's judge: the one object build_feed reads stores through

# This module's PRIVATE synthetic sids (never the shared 11111111-2222-... placeholder: see the docstring).
# (a tuple, unpacked below: a session named after the demo's api service assigned a high-entropy string on its
# own line reads as a credential to the secret scanner the pre-push hook runs)
SIDS = ("5f3e2d1c-0b9a-4876-9543-210fedcba001", "5f3e2d1c-0b9a-4876-9543-210fedcba002",
        "5f3e2d1c-0b9a-4876-9543-210fedcba003")
WEB, API, TESTS = SIDS
NAME_OF = {WEB: "web", API: "api", TESTS: "tests"}
COLOR_OF = {WEB: "#1EA1EB", API: "#E67E22", TESTS: "#2ECC71"}
GOAL_OF = {WEB: "wire the notes-api web client", API: "add the notes-api list endpoint",
           TESTS: "cover the notes-api list endpoint"}
NOW = 1781100000
T0 = NOW - 3600                         # the goals' mint time: a one-hour age sits inside the tint's fade window


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def uline(t, text, uuid, parent=None):
    return {"type": "user", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent,
            "promptSource": "typed", "message": {"role": "user", "content": text}}


def aline(t, text, uuid, parent=None, stop="end_turn"):
    return {"type": "assistant", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}],
                        "stop_reason": stop}}


def _dump(feed):
    """The payload's serialization with the declared clock fields stripped: the dedup's comparison."""
    return json.dumps({k: v for k, v in feed.items() if k not in km._DEDUP_VOLATILE}, sort_keys=True, default=str)


def _without_tints(feed):
    """The stripped payload with every card's and tree row's age tint removed, for the clock comparison."""
    f = json.loads(_dump(feed))
    for c in f["asks"]:
        c.pop("trgb", None)
        for r in c.get("tree") or []:
            r.pop("trgb", None)
    return json.dumps(f, sort_keys=True)


def _reset_memo():
    """The memo empty and its counters at zero: every test starts cold. A kernel without the memo (the base commit
    this change's red-first run pins against) has nothing to reset: the walked-sessions pin below then runs red on
    its own assertion rather than erroring here."""
    if not hasattr(km, "_feed_memo"):
        return
    with km._feed_memo_lock:
        km._feed_memo.clear()
        st = km._FEED_MEMO_STATS
        for k in ("hit", "miss", "evict", "derived", "entries", "bytes"):
            st[k] = 0
        for k in st["miss_by"]:
            st["miss_by"][k] = 0


def _memo_snapshot():
    """(the entries, the counters) as they stand, so a test can hand the process back what it found."""
    if not hasattr(km, "_feed_memo"):
        return None
    with km._feed_memo_lock:
        return dict(km._feed_memo), json.loads(json.dumps(km._FEED_MEMO_STATS))


def _memo_restore(snap):
    if snap is None:
        return
    entries, stats = snap
    with km._feed_memo_lock:
        km._feed_memo.clear()
        km._feed_memo.update(entries)
        km._FEED_MEMO_STATS.clear()
        km._FEED_MEMO_STATS.update(stats)


class _Board(unittest.TestCase):
    """The three-session world; every test builds the REAL build_feed over it."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        td = Path(self.td.name)
        proj = td / "projects"
        names = td / "names"
        names.mkdir()
        self.tpath, self.cdir = {}, {}
        for sid in SIDS:
            cdir = td / ("launch-" + NAME_OF[sid])
            cdir.mkdir()
            pdir = proj / re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(str(cdir)))
            pdir.mkdir(parents=True)
            tp = pdir / (sid + ".jsonl")
            tp.write_text("\n".join(json.dumps(r) for r in [
                uline(T0, "start on: " + GOAL_OF[sid], "u1"),
                aline(T0 + 40, "On it.", "a1", "u1"),
            ]) + "\n")
            (names / sid).write_text("%s\t%s\t%s\n" % (NAME_OF[sid], cdir, COLOR_OF[sid]))
            self.tpath[sid], self.cdir[sid] = tp, cdir
        self.saved = (jd.STATE, jd.PROJECTS, km.NAMES, km._GLOBAL_CLAUDE_MD)
        self.saved_memo = _memo_snapshot()        # the memo and its counters, restored in tearDown
        # The kernel's judge is ONE module object for every test module in the process, so its STATE (goals,
        # override journals, cleared.jsonl, session-order.json) is a directory the whole run shares. This board
        # builds over ITS root and nothing else: _rebind_state moves GOALDIR and every derived dir with it.
        jd._rebind_state(td)
        jd.PROJECTS = proj
        km.NAMES = jd.NAMES
        km._GLOBAL_CLAUDE_MD = td / "no-global-claude.md"
        km._live_scope.names = None               # no cycle snapshot: the names registry is read from the files
        km._live_scope.snapshot = None
        for sid in SIDS:
            self._mint(sid, GOAL_OF[sid])
        # Fixed rows, so the stub itself contributes nothing clock-derived (the dedup invariant's idiom).
        self.live = {sid: self._row() for sid in SIDS}
        # A session's FIRST build adopts it into the persisted session order (feed `order` reads that file
        # before _ordered appends the newcomer), so the first sight is a genuine change; warm once so every
        # compared build is post-adoption, then start the memo cold.
        jd._discover_cache.clear()
        km.build_feed(NOW - 1, self.live)
        _reset_memo()

    def tearDown(self):
        _memo_restore(self.saved_memo)
        jd._rebind_state(self.saved[0])
        jd.PROJECTS, km.NAMES, km._GLOBAL_CLAUDE_MD = self.saved[1:]
        km._live_scope.names = None
        km._live_scope.snapshot = None
        jd._discover_cache.clear()
        self.td.cleanup()

    # ── the world's writers ──
    @staticmethod
    def _row():
        return {"state": "idle", "since": NOW - 100, "model": "", "effort": "", "context": None,
                "compactPct": None, "color": None}

    @staticmethod
    def _mint(sid, text):
        """One top-level goal, minted the way the planner mints (apply_plan), rolled up and saved: the store
        the kernel's judge loads (tests/test_kernel_goal_cache_wiring.py's idiom)."""
        s = {"rompUuid": sid, "seq": 0, "placementsV": jd.PLACEMENTS_V, "nodes": {}, "placements": {},
             "status": {}}
        jd.apply_plan(s, "s1", T0, [{"do": "mint", "why": "the request that opened the session", "text": text}], [])
        jd.rollup_status(s, session_closed=False)
        jd.save_goals(sid, s)

    @staticmethod
    def _complete(sid, t=NOW - 30):
        """A JUDGE VERDICT: the closer records the goal done and rolls the store up with the session's turn
        closed, which settles the top (rollup_status records the settle verdict itself) so the card enters
        Completed; the publish moves the store file."""
        s = jd.load_goals(sid)
        nd = s["nodes"][sid + ":g1"]
        assert jd.record_verdict(s, nd, "romp", "done", t, why="Shipped."), "the done verdict passed the gate"
        jd.rollup_status(s, session_closed=True, now=t)
        jd.save_goals(sid, s)

    @staticmethod
    def _publish_raw(sid, text, **node):
        """A store republished whole in the judge's file shape (the fault-boundary tests' fixture), for a node
        shape apply_plan does not mint here (a goal carrying a sender's origin)."""
        gid = sid + ":g1"
        nd = {"id": gid, "parentId": None, "t": T0, "mt": T0, "text": text, "nodeComplete": False,
              "blocked": False, "cleared": False, "trail": ["s1"], "log": []}
        nd.update(node)
        store = {"rompUuid": sid, "seq": 1, "rev": 7, "placementsV": jd.PLACEMENTS_V, "placements": {},
                 "nodes": {gid: nd}, "status": {gid: "working"}, "lastNode": gid}
        p = jd.GOALDIR / (sid + ".json")
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(store))
        os.replace(tmp, p)                    # the atomic publish every store writer uses

    # ── the reads ──
    def _build(self, now=NOW):
        return km.build_feed(now, self.live)

    def _delta(self, fn):
        """(the memo counters' movement over fn(), fn's result): hit / miss / derived / evict and the non-zero
        miss attributions."""
        b = km._feed_memo_report()
        bm = b["miss_by"]
        out = fn()
        a = km._feed_memo_report()
        d = {k: a[k] - b[k] for k in ("hit", "miss", "derived", "evict")}
        d["miss_by"] = {k: v - bm.get(k, 0) for k, v in a["miss_by"].items() if v - bm.get(k, 0)}
        return d, out

    @staticmethod
    def _cards(feed):
        return {a["itemId"]: a for a in feed["asks"]}


class ColdWarmAndFromScratch(_Board):
    def test_a_cold_build_derives_every_session_and_an_unchanged_rebuild_derives_none(self):
        d, f1 = self._delta(self._build)
        self.assertEqual((d["derived"], d["hit"]), (3, 0), d)
        self.assertEqual(d["miss"], d["derived"], "miss and derived count the same event: one per derivation")
        self.assertEqual(d["miss_by"], {"cold": 3}, "a session with no entry misses under `cold`")
        self.assertEqual(sorted(self._cards(f1)), sorted(sid + ":g1" for sid in SIDS), "one card per goal")
        self.assertEqual({a["column"] for a in f1["asks"]}, {"working"})
        d, f2 = self._delta(self._build)
        self.assertEqual((d["derived"], d["hit"]), (0, 3), d)
        self.assertEqual(_dump(f1), _dump(f2), "a served build is the derived build, byte for byte")
        rep = km._feed_memo_report()
        self.assertEqual(rep["entries"], 3)
        self.assertEqual(rep["bytes"], sum(e[2] for e in km._feed_memo.values()))
        self.assertGreater(rep["bytes"], 0)

    def test_one_sessions_store_publish_re_derives_that_session_alone_and_equals_a_from_scratch_build(self):
        before = self._cards(self._build())
        self.assertIsNone(before[API + ":g1"]["doneConfirming"])
        self._complete(API)                   # the closer's verdict lands in api's store
        d, memoized = self._delta(self._build)
        self.assertEqual((d["derived"], d["hit"]), (1, 2), d)
        self.assertEqual(d["miss_by"], {"store": 1}, "the store file moved and nothing else")
        cards = self._cards(memoized)
        self.assertEqual(cards[API + ":g1"]["column"], "completed", "the verdict reached the card")
        self.assertEqual(cards[API + ":g1"]["distillState"], "completed")
        self.assertEqual(cards[WEB + ":g1"]["column"], "working")
        self.assertEqual(cards[TESTS + ":g1"]["column"], "working")
        _reset_memo()                         # the same clock, nothing memoized: every session derived afresh
        d, scratch = self._delta(self._build)
        self.assertEqual(d["derived"], 3, d)
        self.assertEqual(_dump(memoized), _dump(scratch),
                         "two served entries beside one derivation must equal three derivations, byte for byte")


class HostRegistryProgress(_Board):
    """Host journal bookkeeping does not change cards; registry content still does."""

    @staticmethod
    def _publish_registry(sid, record):
        path = jd.STATE / "sdk" / (sid + ".json")
        path.parent.mkdir(exist_ok=True)
        pending = path.with_suffix(".tmp")
        pending.write_text(json.dumps(record))
        os.replace(pending, path)
        return path

    def test_host_progress_replacements_keep_all_sessions_cached_and_match_a_fresh_build(self):
        record = {"sid": WEB, "name": "web", "spawnedAt": T0}
        self._publish_registry(WEB, record)
        before = self._build()
        for progress in ({"hostAck": {"host": "1:2", "offset": 10}},
                         {"hostAck": {"host": "1:2", "offset": 20}, "hostLogPos": {"pos": 3}},
                         {}):
            with self.subTest(progress=progress):
                self._publish_registry(WEB, dict(record, **progress))
                delta, cached = self._delta(self._build)
                self.assertEqual((delta["derived"], delta["hit"]), (0, 3), delta)
                self.assertEqual(delta["miss_by"], {})
                self.assertEqual(_dump(cached), _dump(before))
                _reset_memo()
                self.assertEqual(_dump(cached), _dump(self._build()),
                                 "skipping host bookkeeping must preserve the real feed payload")

    def test_other_registry_content_invalidates_only_its_session(self):
        record = {"sid": API, "name": "api", "spawnedAt": T0}
        self._publish_registry(API, record)
        self._build()
        for fields in ({"spawnedAt": T0 + 10}, {"bgLedger": {"worker": {"state": "running"}}},
                       {"futureDisplayField": "changed"}):
            with self.subTest(fields=fields):
                record.update(fields)
                self._publish_registry(API, record)
                delta, cached = self._delta(self._build)
                self.assertEqual((delta["derived"], delta["hit"]), (1, 2), delta)
                self.assertEqual(delta["miss_by"], {"reg": 1})
                _reset_memo()
                self.assertEqual(_dump(cached), _dump(self._build()))

    def test_missing_empty_object_and_unreadable_registry_remain_distinct(self):
        self._build()
        path = self._publish_registry(WEB, {})
        delta, _ = self._delta(self._build)
        self.assertEqual((delta["derived"], delta["hit"]), (1, 2), delta)
        self.assertEqual(delta["miss_by"], {"reg": 1})
        path.write_text("")
        delta, _ = self._delta(self._build)
        self.assertEqual((delta["derived"], delta["hit"]), (1, 2), delta)
        self.assertEqual(delta["miss_by"], {"reg": 1})
        path.write_text("not json")
        delta, _ = self._delta(self._build)
        self.assertEqual((delta["derived"], delta["hit"]), (0, 3), delta)
        self.assertEqual(delta["miss_by"], {}, "both invalid forms have the same unreadable state")
        path.unlink()
        delta, _ = self._delta(self._build)
        self.assertEqual((delta["derived"], delta["hit"]), (1, 2), delta)
        self.assertEqual(delta["miss_by"], {"reg": 1})


class EveryInputMovesItsSessionOnly(_Board):
    """Each writer below is one of the events the key covers; each re-derives exactly the session it touched,
    under exactly its label, and the card shows the change."""

    def test_a_user_gesture_journaled_as_an_override_row(self):
        self._build()
        # the user resolves web's card: _resolve_node journals the gesture BEFORE its store save (the journal
        # is the durable truth load_goals replays); here the journal row alone, the store file untouched
        jd.append_override(WEB, WEB + ":g1", "resolve", NOW - 20)
        d, f = self._delta(self._build)
        self.assertEqual((d["derived"], d["hit"]), (1, 2), d)
        self.assertEqual(d["miss_by"], {"store": 1}, "the override journal is part of the store identity")
        card = self._cards(f)[WEB + ":g1"]
        # the replayed resolve is a done verdict on a top the session still holds as its focus: the settle gate
        # keeps the column Working and the card wears the "done, confirming" cue (rollup's confirming export)
        self.assertTrue(card["doneConfirming"], "the replayed resolve reached the card")
        self.assertEqual(card["column"], "working")
        d, _ = self._delta(self._build)
        self.assertEqual(d["derived"], 0, "the replay is idempotent and the journal stands: a hit")

    def test_a_clear_row_for_one_card(self):
        self._build()
        with (jd.STATE / "cleared.jsonl").open("a") as fh:      # the ledger row the clear handler appends
            fh.write(json.dumps({"id": TESTS + ":g1", "t": NOW - 10, "op": "clear"}) + "\n")
        d, f = self._delta(self._build)
        self.assertEqual((d["derived"], d["hit"]), (1, 2), d)
        self.assertEqual(d["miss_by"], {"cleared": 1}, "the ledger is keyed by the session's own slice")
        self.assertNotIn(TESTS + ":g1", self._cards(f), "the cleared card is gone")
        self.assertEqual(sorted(self._cards(f)), sorted([WEB + ":g1", API + ":g1"]))
        self.assertEqual(f["dismissedCount"], 1)

    def test_a_live_row_change(self):
        self._build()
        self.live[API] = dict(self._row(), model="opus")        # the row's model badge changes
        d, f = self._delta(self._build)
        self.assertEqual((d["derived"], d["hit"]), (1, 2), d)
        self.assertEqual(d["miss_by"], {"row": 1})
        self.assertEqual(len(f["asks"]), 3)

    def test_a_transcript_append(self):
        self._build()
        with self.tpath[WEB].open("a") as fh:
            fh.write(json.dumps(uline(NOW - 5, "and the pagination", "u2", "a1")) + "\n")
        d, f = self._delta(self._build)
        self.assertEqual((d["derived"], d["hit"]), (1, 2), d)
        self.assertIn("transcript", d["miss_by"])
        self.assertTrue(set(d["miss_by"]) <= {"transcript", "parse"},
                        "an append moves the transcript identity (and the parse bit when a parse was cached): %r"
                        % d["miss_by"])
        self.assertEqual(len(f["asks"]), 3)

    def test_a_states_append(self):
        self._build()
        jd.STATESDIR.mkdir(parents=True, exist_ok=True)
        with (jd.STATESDIR / (API + ".jsonl")).open("a") as fh:   # a producer's state row
            fh.write(json.dumps({"t": NOW - 5, "state": "idle"}) + "\n")
        d, f = self._delta(self._build)
        self.assertEqual((d["derived"], d["hit"]), (1, 2), d)
        self.assertEqual(d["miss_by"], {"states": 1})
        self.assertEqual(len(f["asks"]), 3)

    def test_a_names_rewrite(self):
        self._build()
        (jd.NAMES / TESTS).write_text("tests\t%s\t#123456\n" % self.cdir[TESTS])   # the session recolored
        d, f = self._delta(self._build)
        self.assertEqual((d["derived"], d["hit"]), (1, 2), d)
        self.assertEqual(d["miss_by"], {"names": 1})
        self.assertEqual(self._cards(f)[TESTS + ":g1"]["color"], {"bg": "#123456", "fg": "#ffffff"})
        self.assertEqual(self._cards(f)[WEB + ":g1"]["color"], {"bg": COLOR_OF[WEB], "fg": "#ffffff"})

    def test_the_hide_from_feed_flag(self):
        self._build()
        flags = jd.STATE / "session-flags.json"
        flags.write_text(json.dumps({API: {"hideFromFeed": True}}))
        d, f = self._delta(self._build)
        self.assertEqual((d["derived"], d["hit"]), (1, 2), d)
        self.assertEqual(d["miss_by"], {"hide": 1})
        self.assertNotIn(API, {a["sid"] for a in f["asks"]}, "a muted session's cards vanish")
        self.assertEqual(sorted(self._cards(f)), sorted([WEB + ":g1", TESTS + ":g1"]))
        d, _ = self._delta(self._build)
        self.assertEqual((d["derived"], d["hit"]), (0, 3), "the muted session's (empty) entry serves too")
        flags.write_text(json.dumps({}))
        d, f = self._delta(self._build)
        self.assertEqual((d["derived"], d["miss_by"]), (1, {"hide": 1}), d)
        self.assertIn(API + ":g1", self._cards(f), "unmuted: the card is back")

    def test_a_peers_verdict_re_derives_the_card_that_reads_its_store(self):
        """api's goal was delegated from web (its origin names web's goal): the card's origin badge reads WEB's
        store, so a verdict in web's store must re-derive api's card too, or a hit would serve a badge a judge
        has moved. The key's `peers` component re-evaluates the peers the previous derivation recorded."""
        self._build()
        self._publish_raw(API, GOAL_OF[API], origin={"peer": WEB, "goalId": WEB + ":g1"})
        d, f = self._delta(self._build)
        self.assertEqual((d["derived"], d["miss_by"]), (1, {"store": 1}), d)
        card = self._cards(f)[API + ":g1"]
        self.assertTrue(card["origin"]["live"], "web's goal is open: the badge reads live")
        # That derivation read web for the FIRST time, so web's facts were not taken before the read (a publish
        # landing mid-read could pair a new key with old content): the stored key is unsettled, and the next build
        # re-derives api once more with web's facts taken before the read, then hits.
        peers_at = km._FEED_MEMO_LABELS.index("peers")
        self.assertEqual(km._feed_memo_get(API)[0][peers_at], km._FEED_PEERS_UNSETTLED,
                         "a peer first read by this derivation leaves the key unsettled")
        d, _ = self._delta(self._build)
        self.assertEqual((d["derived"], d["miss_by"]), (1, {"peers": 1}), "the settling derivation: %r" % d)
        self.assertEqual(km._feed_memo_get(API)[0][peers_at][0][0], WEB,
                         "api's key names web, with facts taken before the read")
        d, _ = self._delta(self._build)
        self.assertEqual(d["derived"], 0, "the peer's facts stand: a hit")
        self._complete(WEB)                   # the verdict lands in WEB's store, not api's
        d, f = self._delta(self._build)
        self.assertEqual(d["derived"], 2, "web (its store) and api (its peer's store): %r" % d)
        self.assertEqual(d["miss_by"], {"store": 1, "peers": 1})
        self.assertEqual(self._cards(f)[WEB + ":g1"]["column"], "completed")
        self.assertFalse(self._cards(f)[API + ":g1"]["origin"]["live"], "the badge dimmed with the sender's goal")
        self.assertEqual(self._cards(f)[TESTS + ":g1"]["column"], "working")


class TheClockIsNotAnInput(_Board):
    def test_two_builds_ten_minutes_apart_derive_nothing_and_differ_only_in_the_clock_fields_and_the_tints(self):
        d, a = self._delta(self._build)
        self.assertEqual(d["derived"], 3)
        d, b = self._delta(lambda: self._build(NOW + 600))
        self.assertEqual((d["derived"], d["hit"]), (0, 3), "time passing moves no key component: %r" % d)
        top = sorted(k for k in set(list(a) + list(b))
                     if json.dumps(a.get(k), sort_keys=True, default=str) != json.dumps(b.get(k), sort_keys=True, default=str))
        self.assertEqual(top, ["asks", "now"], "only the clock and the cards (their tints) differ: %r" % top)
        self.assertEqual(_without_tints(a), _without_tints(b), "with the tints removed the two builds are one")
        tints_a = [c["trgb"] for c in a["asks"]]
        tints_b = [c["trgb"] for c in b["asks"]]
        self.assertNotEqual(tints_a, tints_b, "the fold re-stamped the age tint for the later clock")
        self.assertTrue(all(len(t) == 3 for t in tints_a + tints_b))
        for c in a["asks"] + b["asks"]:
            self.assertNotIn("_ageT", c, "the tint's epoch is the entry's; the folded card carries trgb")
            for r in c.get("tree") or []:
                self.assertNotIn("_ageT", r)
        self.assertIn("now", km._DEDUP_VOLATILE, "the one clock field the builder emits is a declared volatile")


class TheBoundAndTheDepartures(_Board):
    def test_the_byte_bound_sheds_the_oldest_entries_and_the_payload_stays_complete(self):
        self._build()
        one = max(e[2] for e in km._feed_memo.values())     # the largest entry: alone at the bound it still serves
        with mock.patch.object(km, "FEED_MEMO_BYTES", one):
            _reset_memo()
            d, f = self._delta(self._build)
            self.assertEqual(d["derived"], 3)
            rep = km._feed_memo_report()
            self.assertEqual(rep["bound"], one)
            self.assertGreaterEqual(rep["evict"], 2, "the second and third puts each shed the oldest: %r" % rep)
            self.assertLessEqual(rep["bytes"], one)
            self.assertEqual(rep["entries"], 1)
            self.assertEqual(rep["bytes"], sum(e[2] for e in km._feed_memo.values()))
            self.assertEqual(sorted(self._cards(f)), sorted(sid + ":g1" for sid in SIDS),
                             "the payload is complete whatever the bound")
            self.assertEqual(km._PERF_STATS.snapshot()["builds"]["feed"]["memo"], rep,
                             "GET /perf reports the memo's counters under builds.feed.memo")

    def test_the_bound_is_a_fraction_of_the_machines_memory_unless_the_environment_names_bytes(self):
        with mock.patch.dict(os.environ, {"ROMP_FEED_MEMO_BYTES": "4096"}):
            self.assertEqual(km._feed_memo_bound(), 4096)
        with mock.patch.dict(os.environ, {"ROMP_FEED_MEMO_BYTES": "lots"}):
            self.assertEqual(km._feed_memo_bound(), km._mem_total_bytes() // 64, "an unparseable value falls to the default")
        with mock.patch.dict(os.environ, {"ROMP_FEED_MEMO_BYTES": "0"}):
            self.assertEqual(km._feed_memo_bound(), km._mem_total_bytes() // 64, "zero is not a bound")
        env = {k: v for k, v in os.environ.items() if k != "ROMP_FEED_MEMO_BYTES"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(km._feed_memo_bound(), km._mem_total_bytes() // 64)
        self.assertGreater(km.FEED_MEMO_BYTES, 0)

    def test_a_departed_sessions_entry_leaves_with_it(self):
        self._build()
        self.assertEqual(km._feed_memo_report()["entries"], 3)
        self.live.pop(TESTS)                  # the session is gone from the backend's live map ...
        (jd.NAMES / TESTS).unlink()           # ... and from the names registry
        jd._discover_cache.clear()
        d, f = self._delta(self._build)
        self.assertEqual((d["derived"], d["hit"]), (0, 2), d)
        self.assertEqual(d["evict"], 1, "the departed entry is counted as an eviction")
        rep = km._feed_memo_report()
        self.assertEqual(rep["entries"], 2)
        self.assertEqual(set(km._feed_memo), {WEB, API})
        self.assertEqual(rep["bytes"], sum(e[2] for e in km._feed_memo.values()))
        self.assertNotIn(TESTS + ":g1", self._cards(f))
        self.assertEqual(set(km._SUBAGENT_DIRS_MEMO) & set(SIDS), {WEB, API},
                         "the key's subagent-walk memo drops the departed session with its entry (round two, low 1)")

    def test_the_perf_snapshot_carries_the_memo_beside_the_feed_builds_counters(self):
        self._build()
        feed = km._PERF_STATS.snapshot()["builds"]["feed"]
        self.assertEqual(set(feed), {"cached", "built", "ms", "memo"})
        self.assertEqual(feed["memo"], km._feed_memo_report())
        self.assertEqual(set(feed["memo"]), {"hit", "miss", "evict", "entries", "bytes", "bound", "derived", "miss_by"})
        self.assertEqual(set(feed["memo"]["miss_by"]), set(km._FEED_MEMO_LABELS) | {"cold"})
        self.assertEqual(feed["memo"]["derived"], 3)
        self.assertEqual(feed["memo"]["bound"], km.FEED_MEMO_BYTES)
        json.dumps(feed)                      # serializes as-is


class TheRebuildWalksOnlyWhatMoved(_Board):
    """The pin this change is filed under (it fails on the kernel before the memo): a rebuild of an unchanged board
    walks NO session's goal tree. _heal_session_tops runs once per session per derivation (the read-side nesting of
    machine-rooted tops over the session's nodes and status), so its call count is the number of sessions whose
    trees the build walked. Before the memo it was three on every rebuild, whatever had changed; with it, three on
    the cold build and none on the unchanged rebuild, then exactly the one session whose store moved."""

    def _walked(self, fn):
        calls = []
        real = km._heal_session_tops
        with mock.patch.object(km, "_heal_session_tops", side_effect=lambda *a, **k: (calls.append(1), real(*a, **k))[1]):
            out = fn()
        return len(calls), out

    def test_an_unchanged_rebuild_walks_no_sessions_tree_and_a_moved_store_walks_that_session_alone(self):
        n_cold, _ = self._walked(self._build)
        self.assertEqual(n_cold, 3, "the cold build derives every session: one walk each")
        n_same, feed = self._walked(self._build)
        self.assertEqual(n_same, 0, "an unchanged board is served from the memo: no session's tree is walked")
        self.assertEqual(len(feed["asks"]), 3, "and the board is whole")
        self._complete(API)
        n_moved, feed = self._walked(self._build)
        self.assertEqual(n_moved, 1, "one store moved: that session's tree alone is walked again")
        self.assertEqual(self._cards(feed)[API + ":g1"]["column"], "completed", "and its card wears the verdict")


class TheClearedIndexMatchesTheFilter(unittest.TestCase):
    """The per-build clear index (_cleared_by_sid) must hand each session exactly what the per-session filter
    `i.startswith(sid + ":")` returned, for every id shape the ledger can hold: a node id <sid>:gN, a composite
    session key with its own colon (host:name:gN, a peer wait key), an id with no colon, and an id of another kind
    (parked:<msgId>). Round two, low 3: an index on the FIRST colon gave a composite session nothing. The sessions
    asked are the shapes a session id takes (a uuid, a host:name key, none, an unknown one); a session id is never
    the bare host half of a composite key, the one prefix the filter would have matched and the index does not."""

    def test_every_shape_indexes_where_the_filter_found_it(self):
        ids = {WEB + ":g1", WEB + ":g2", API + ":g1", "TESTHOST:api:g3", "TESTHOST:api:g1", "parked:m-1789", "bare-id"}
        by = km._cleared_by_sid(ids)
        for sid in (WEB, API, TESTS, "TESTHOST:api", "parked", "bare-id", "", "nobody"):
            want = tuple(sorted(i for i in ids if i.startswith(sid + ":")))
            self.assertEqual(by.get(sid, ()), want, "session %r" % sid)


class TheClockDecidedBooleansAreComponents(_Board):
    """The one read in the derivation's closure that consults its own clock is the billing-switch offer
    (_cap_switch_offer: a login-account usage window at its cap with resets_at still ahead). The reset passing ends the
    offer on the base's next build; a memo hit would keep offering a switch past the reset, so the crossing is the
    `offer` component, a boolean the key computes from usage.json against the build's clock (the verifier's shape,
    T368 review). Red on the memo without the component: the second build serves the offer with derived 0."""

    def _cap_death(self, sid, resets_at):
        """web dead on a plain retryable API error, billing the login, a key on hand, the five-hour window at its cap:
        every leg of the offer."""
        with open(self.tpath[sid], "a") as fh:
            fh.write(json.dumps({"type": "assistant", "timestamp": iso(T0 + 80), "uuid": "a2", "parentUuid": "a1",
                                 "isApiErrorMessage": True, "apiErrorStatus": 529, "error": "overloaded_error",
                                 "message": {"role": "assistant", "stop_reason": "stop_sequence",   # the failed turn ENDS on the record
                                             "content": [{"type": "text", "text": "API Error: 529 overloaded"}]}}) + "\n")
        km._parse(str(self.tpath[sid]), sid, NOW)          # the feed reads the parse cache-only: warm it (the error tail rides the parse)
        self.live[sid] = dict(self._row(), authLive="login")
        (jd.STATE / "usage.json").write_text(json.dumps({"five_hour": {"pct": 100, "resets_at": resets_at}}))

    def test_the_offer_leaves_the_card_when_its_reset_passes_on_a_served_entry(self):
        # The reset sits ahead of BOTH clocks the offer has been read against (the build's, and the wall clock the
        # memo's first head still minted from), so the served-stale case shows on that head as it did on the
        # verifier's kernel: the window passes, the entry hits, the card keeps offering.
        resets_at = max(NOW, int(time.time())) + 600
        self._cap_death(WEB, resets_at)
        with mock.patch.object(km, "_auth_key_present", lambda: True), \
                mock.patch.object(km, "_live_map", lambda: self.live):   # the offer reads the cycle's live snapshot
            d, f = self._delta(self._build)
            self.assertEqual(d["derived"], 3)
            offer = {"resetsAt": resets_at, "window": "five_hour"}
            blocked = self._cards(f)[WEB + ":g1"]["blocked"]     # the api-error block carries the offer
            self.assertEqual(blocked.get("capOffer"), offer,
                             "the offer rides the card while the window is capped with its reset ahead: %r" % blocked)
            d, f = self._delta(self._build)
            self.assertEqual(d["derived"], 0, "nothing moved: a hit, the offer still current")
            self.assertEqual(self._cards(f)[WEB + ":g1"]["blocked"].get("capOffer"), offer)
            d, f = self._delta(lambda: self._build(resets_at + 1))
            self.assertEqual((d["derived"], d["miss_by"]), (1, {"offer": 1}),
                             "the reset passed: the crossing moved web's key and web alone re-derived: %r" % d)
            blocked = self._cards(f)[WEB + ":g1"]["blocked"]
            self.assertEqual(blocked.get("state"), "apiError", "the error block stays: %r" % blocked)
            self.assertNotIn("capOffer", blocked, "a rebuilt card drops the offer; a served one must too")
            d, f = self._delta(lambda: self._build(resets_at + 2))
            self.assertEqual(d["derived"], 0, "closed stays closed: a hit")
            self.assertNotIn("capOffer", self._cards(f)[WEB + ":g1"]["blocked"])

    def test_two_capped_windows_the_earlier_reset_passing_moves_the_offer_to_the_later_window(self):
        """Round two's shape: both windows at their cap, the five-hour one resetting first. The five-hour reset
        passing leaves a login window capped (the seven-day one), so a boolean would stand and a served card would
        keep naming a reset already in the past; the component is the payload the card renders, so the crossing
        moves the key and the rebuilt card names the seven-day window and its reset."""
        base = max(NOW, int(time.time()))
        r5, r7 = base + 600, base + 4000
        self._cap_death(WEB, r5)
        (jd.STATE / "usage.json").write_text(json.dumps({"five_hour": {"pct": 100, "resets_at": r5},
                                                         "seven_day": {"pct": 100, "resets_at": r7}}))
        with mock.patch.object(km, "_auth_key_present", lambda: True), \
                mock.patch.object(km, "_live_map", lambda: self.live):
            d, f = self._delta(self._build)
            self.assertEqual(self._cards(f)[WEB + ":g1"]["blocked"].get("capOffer"), {"resetsAt": r5, "window": "five_hour"})
            d, f = self._delta(lambda: self._build(r5 + 1))
            self.assertEqual((d["derived"], d["miss_by"]), (1, {"offer": 1}),
                             "the five-hour reset passed with the seven-day window still capped: web re-derives: %r" % d)
            self.assertEqual(self._cards(f)[WEB + ":g1"]["blocked"].get("capOffer"), {"resetsAt": r7, "window": "seven_day"},
                             "the rebuilt card names the window still capped and ITS reset, never the passed one")
            d, f = self._delta(lambda: self._build(r5 + 2))
            self.assertEqual(d["derived"], 0, "and holds: a hit")
            d, f = self._delta(lambda: self._build(r7 + 1))
            self.assertEqual((d["derived"], d["miss_by"]), (1, {"offer": 1}), "the seven-day reset passing closes it: %r" % d)
            self.assertNotIn("capOffer", self._cards(f)[WEB + ":g1"]["blocked"])

    def test_the_offer_is_keyed_only_for_the_session_that_read_usage(self):
        # one clock read: the cap and the assertion below must name the same second, and two reads of time.time()
        # straddled a boundary on a CI job (1789348898 in the key against 1789348899 expected)
        reset = max(NOW, int(time.time())) + 600
        self._cap_death(WEB, reset)
        with mock.patch.object(km, "_auth_key_present", lambda: True), \
                mock.patch.object(km, "_live_map", lambda: self.live):
            self._build()
            k_web = km._feed_memo_get(WEB)[0]
            k_api = km._feed_memo_get(API)[0]
            at = km._FEED_MEMO_LABELS.index("offer")
            self.assertEqual(k_web[at], ("five_hour", reset),
                             "web read usage.json: its key carries the open window and its reset")
            self.assertIsNone(k_api[at], "api did not: the crossing is no input of its card")


class ThePostalLogIsKeyedPerSession(_Board):
    """The postal log is one file every session's derivation reads, but a session's cards read only the rows it is
    a party to (its own asks, the replies to them, its peers' names), so the key holds that slice by value, not
    the whole log's identity: a row between two other sessions moves no key of this one (T368 review: the
    whole-log identity re-derived the board on every row)."""

    def _mail(self, frm, to, kind, t, body):
        p = jd.MESSAGES
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as fh:
            fh.write(json.dumps({"id": "m-%d" % t, "from_id": frm, "to_id": to, "from": NAME_OF[frm], "to": NAME_OF[to],
                                 "kind": kind, "t": t, "body": body}) + "\n")

    def test_a_row_between_two_other_sessions_leaves_a_sessions_key_where_it_was(self):
        self._build()
        self._mail(WEB, API, "question", NOW - 50, "Is the list endpoint paginated?")
        d, _ = self._delta(self._build)
        self.assertEqual(d["derived"], 2, "the two parties re-derive, the third does not: %r" % d)
        self.assertEqual(d["miss_by"], {"postal": 2, "wait": 1}, "the question also opens the asker's wait edge")
        self.assertEqual(km._feed_memo_get(TESTS)[0][km._FEED_MEMO_LABELS.index("postal")], ((), ()),
                         "tests is party to no row: its slice is empty and its key stood")
        d, _ = self._delta(self._build)
        self.assertEqual(d["derived"], 0)
        self._mail(API, WEB, "coordinate", NOW - 40, "Yes, by cursor.")
        d, _ = self._delta(self._build)
        self.assertEqual((d["derived"], d["miss_by"]), (2, {"postal": 2, "wait": 1}), "the reply moves the pair's rows and closes the edge: %r" % d)
        self.assertEqual(km._feed_memo_get(TESTS)[0][km._FEED_MEMO_LABELS.index("postal")], ((), ()))
        self._mail(TESTS, WEB, "coordinate", NOW - 30, "Covering the cursor case.")
        d, _ = self._delta(self._build)
        self.assertEqual((d["derived"], d["miss_by"]), (2, {"postal": 2}), "tests and web, never api: %r" % d)
        self.assertEqual(km._feed_memo_get(API)[0][km._FEED_MEMO_LABELS.index("postal")][0][0][0], (WEB, API),
                         "api's slice still holds its own pair alone")


class PerCardNudgeInputs(_Board):
    @staticmethod
    def _nudge_data(nudged, **metadata):
        path = jd.STATE / "auto-nudge.json"
        pending = path.with_suffix(".tmp")
        pending.write_text(json.dumps(dict(enabled=True, nudged=nudged, **metadata)))
        os.replace(pending, path)
        # The ledger reader is covered separately. Force this fixture publish visible even when a
        # filesystem rounds two same-size writes to the same mtime; this test exercises the feed key.
        km._autonudge_cache.pop(str(path), None)

    @staticmethod
    def _nudge_event(gid, stamp):
        with (jd.STATE / "nudge-events.jsonl").open("a") as out:
            out.write(json.dumps({"gid": gid, "t": stamp}) + "\n")

    def test_count_and_history_changes_rebuild_only_the_card_owner(self):
        self._build()
        gid = API + ":g1"
        self._nudge_data({gid: {"count": 1}})
        self._nudge_event(gid, NOW - 30)
        delta, frame = self._delta(self._build)
        self.assertEqual((delta["derived"], delta["hit"]), (1, 2), delta)
        self.assertEqual(delta["miss_by"], {"nudge": 1})
        self.assertEqual(self._cards(frame)[gid]["nudged"], {"count": 1, "times": [NOW - 30]})
        self._nudge_event(gid, NOW - 10)
        delta, frame = self._delta(self._build)
        self.assertEqual((delta["derived"], delta["hit"]), (1, 2), delta)
        self.assertEqual(self._cards(frame)[gid]["nudged"]["times"], [NOW - 30, NOW - 10])
        _reset_memo()
        self.assertEqual(_dump(frame), _dump(self._build()))

    def test_unrelated_ledger_writes_and_unread_history_keep_entries_cached(self):
        self._nudge_data({API + ":g1": {"count": 1, "lastTurnId": "s1"}})
        before = self._build()
        self._nudge_data({API + ":g1": {"count": 1, "lastTurnId": "s2"}}, pollSeq=2)
        self._nudge_event(WEB + ":g1", NOW - 10)  # no count: the card does not read this history
        delta, frame = self._delta(self._build)
        self.assertEqual((delta["derived"], delta["hit"]), (0, 3), delta)
        self.assertEqual(_dump(frame), _dump(before))
        _reset_memo()
        self.assertEqual(_dump(frame), _dump(self._build()))

    def test_failure_state_changes_rebuild_its_card_without_changing_the_count(self):
        gid = WEB + ":g1"
        self._nudge_data({gid: {"count": 1}})
        before = self._build()
        self.assertFalse(self._cards(before)[gid]["nudgeFailed"])
        self._nudge_data({gid: {"count": 1, "failed": True, "failedAt": NOW - 20}})
        delta, frame = self._delta(self._build)
        self.assertEqual((delta["derived"], delta["hit"]), (1, 2), delta)
        self.assertTrue(self._cards(frame)[gid]["nudgeFailed"])
        self._nudge_data({gid: {"count": 1, "failed": True, "failedAt": T0 - 1}})
        delta, _ = self._delta(self._build)
        self.assertEqual((delta["derived"], delta["hit"]), (1, 2), delta)

    def test_history_outside_the_displayed_tail_does_not_invalidate_and_count_removal_does(self):
        gid = API + ":g1"
        self._nudge_data({gid: {"count": 12}})
        stamps = list(range(NOW - 100, NOW - 88))
        for stamp in stamps:
            self._nudge_event(gid, stamp)
        before = self._build()
        self.assertEqual(self._cards(before)[gid]["nudged"]["times"], stamps[-8:])
        path = jd.STATE / "nudge-events.jsonl"
        path.write_text("".join(json.dumps({"gid": gid, "t": stamp}) + "\n"
                                for stamp in [NOW - 300, *stamps[1:]]))
        delta, frame = self._delta(self._build)
        self.assertEqual((delta["derived"], delta["hit"]), (0, 3), delta)
        self.assertEqual(_dump(frame), _dump(before))
        self._nudge_data({})
        delta, frame = self._delta(self._build)
        self.assertEqual((delta["derived"], delta["hit"]), (1, 2), delta)
        self.assertIsNone(self._cards(frame)[gid]["nudged"])

    def test_a_card_with_a_foreign_node_id_tracks_that_exact_id(self):
        old, foreign = WEB + ":g1", API + ":g9"
        store = jd.load_goals(WEB)
        node = store["nodes"].pop(old)
        node["id"] = foreign
        store["nodes"][foreign] = node
        store["status"][foreign] = store["status"].pop(old)
        jd.save_goals(WEB, store)
        frame = self._build()
        self.assertEqual(self._cards(frame)[foreign]["sid"], WEB)
        self._nudge_data({foreign: {"count": 1}})
        delta, frame = self._delta(self._build)
        self.assertEqual((delta["derived"], delta["hit"]), (1, 2), delta)
        self.assertEqual(self._cards(frame)[foreign]["nudged"]["count"], 1)
        _reset_memo()
        self.assertEqual(_dump(frame), _dump(self._build()))

    def test_a_deferral_record_for_a_foreign_node_id_re_derives_the_card_that_read_it(self):
        """The key's `stalls` component follows the exact node ids the entry read, like `nudge`: a deferral
        record (auto-nudge.json's `deferred` map, what _stalled_goals reads) minted or retired for a node whose id
        prefix is another session's re-derives the session holding that card, once; a record for a node no entry
        read re-derives nothing. Red on a session-prefix slice: with the nudge component scoped to its read ids,
        no board-wide identity covered the ledger any more, and the holding session's entry was served with a
        frozen or missing Stalled section."""
        old, foreign = WEB + ":g1", API + ":g9"
        store = jd.load_goals(WEB)
        node = store["nodes"].pop(old)
        node["id"] = foreign
        store["nodes"][foreign] = node
        store["status"][foreign] = store["status"].pop(old)
        jd.save_goals(WEB, store)
        frame = self._build()
        self.assertEqual(self._cards(frame)[foreign]["sid"], WEB)
        self.assertIsNone(self._cards(frame)[foreign]["stalled"])
        hold = {"why": "waiting on the notes-api list endpoint to land", "at": NOW - 60}
        self._nudge_data({}, deferred={foreign: hold})          # minted AFTER the entry was memoized
        delta, frame = self._delta(self._build)
        self.assertEqual((delta["derived"], delta["hit"]), (1, 2), delta)
        self.assertEqual(delta["miss_by"], {"stalls": 1}, delta)
        stalled = self._cards(frame)[foreign]["stalled"]
        self.assertEqual((stalled["why"], stalled["since"]), (hold["why"], hold["at"]))
        delta, _ = self._delta(self._build)
        self.assertEqual((delta["derived"], delta["hit"]), (0, 3), "the record stands: a hit: %r" % delta)
        unread = TESTS + ":g7"                                    # a node id no entry read
        self._nudge_data({}, deferred={foreign: hold, unread: dict(hold, at=NOW - 50)})
        delta, _ = self._delta(self._build)
        self.assertEqual((delta["derived"], delta["hit"]), (0, 3), "an unread node's record moves no key: %r" % delta)
        self._nudge_data({}, deferred={unread: dict(hold, at=NOW - 50)})   # the foreign node's record retired
        delta, frame = self._delta(self._build)
        self.assertEqual((delta["derived"], delta["hit"]), (1, 2), delta)
        self.assertEqual(delta["miss_by"], {"stalls": 1}, delta)
        self.assertIsNone(self._cards(frame)[foreign]["stalled"])
        _reset_memo()
        self.assertEqual(_dump(frame), _dump(self._build()))

    def test_publish_during_derivation_uses_one_snapshot_then_heals_on_next_build(self):
        gid = API + ":g1"
        self._nudge_data({gid: {"count": 1}})
        self._build()
        _reset_memo()
        derive = km._feed_session_entry

        def publish_then_derive(session, ctx):
            if session["sid"] == API:
                self._nudge_data({gid: {"count": 2}})
            return derive(session, ctx)

        with mock.patch.object(km, "_feed_session_entry", side_effect=publish_then_derive):
            frame = self._build()
        self.assertEqual(self._cards(frame)[gid]["nudged"]["count"], 1)
        delta, frame = self._delta(self._build)
        self.assertEqual((delta["derived"], delta["hit"]), (1, 2), delta)
        self.assertEqual(self._cards(frame)[gid]["nudged"]["count"], 2)
        _reset_memo()
        self.assertEqual(_dump(frame), _dump(self._build()))


if __name__ == "__main__":
    unittest.main()
