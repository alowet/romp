#!/usr/bin/env python3
"""The timeline's DEAD-LANE memo (2026-09-08): a lane whose session is dead is re-derived only when an input moves.

The full timeline build ran every pusher cycle (the fleet signature's 5 s bucket turns over faster than a 6 s
cycle) and re-parsed every lane's transcript and goals each time, dead lanes included. Now a dead lane's
parse-derived parts (bars, compactions, the work end, its judging marks) are served from a memo keyed on
every file they read and the host's recorded suspensions, its parse is dropped from _parse_cache once cached
(the resident-memory lever), and the served frame is byte-identical to a rebuilt one: the judging marks are
derived once at horizon zero, stamped with the value the horizon test compares, and filtered per build on
exactly that. The bars encoder reuses the strings of entry objects it already encoded.

Synthetic transcript, states and captions under a temp root; a placeholder sid; the lane is dead because the
liveness snapshot is empty."""
import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
km = SourceFileLoader("romp_kernel_lane_memo", os.path.join(BIN, "romp-kernel")).load_module()

SID = "11111111-2222-3333-4444-555555555555"
NOW = 1_800_000_000
T0 = NOW - 3600


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _rec(kind, t, uuid, parent, text):
    if kind == "user":
        return {"type": "user", "timestamp": _iso(t), "uuid": uuid, "parentUuid": parent, "promptSource": "typed",
                "message": {"role": "user", "content": text}}
    return {"type": "assistant", "timestamp": _iso(t), "uuid": uuid, "parentUuid": parent,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}}


def move_ctime(path):
    """Move a file's ctime and nothing else: flip its mode between 0o600 and 0o644, checking the stat after
    each chmod, until the ctime differs (a coarse filesystem clock can hand two chmods one timestamp). mtime,
    size and inode stand. Bounded at 5 s: a filesystem that never ticks ctime under chmod fails the test
    loudly rather than passing it."""
    before = cur = os.stat(path)
    deadline = time.monotonic() + 5
    while cur.st_ctime_ns == before.st_ctime_ns:
        if time.monotonic() > deadline:
            raise AssertionError("ctime did not move under chmod within 5 s")
        os.chmod(path, 0o644 if (cur.st_mode & 0o777) == 0o600 else 0o600)
        cur = os.stat(path)
    return cur


class DeadLaneMemo(unittest.TestCase):
    def setUp(self):
        km._downtime[:] = []
        self.td = tempfile.TemporaryDirectory()
        td = Path(self.td.name)
        cdir = td / "launchdir"; cdir.mkdir()
        proj = td / "projects"
        pdir = proj / km.jd.re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(str(cdir)))
        pdir.mkdir(parents=True)
        self.recs = [_rec("user", T0, "u1", None, "run the long benchmark"),
                     _rec("assistant", T0 + 10, "a1", "u1", "Launched it.")]
        self.tpath = pdir / (SID + ".jsonl")
        self._write(self.recs)
        names = td / "names"; names.mkdir()
        (names / SID).write_text("testsess\t%s\t#abcdef\n" % str(cdir))
        self.saved = (km.jd.NAMES, km.jd.PROJECTS, km.jd.GOALDIR, km.jd.CAPDIR, km.jd.STATE, km.NAMES, km._tmux_sessions)
        km.jd.NAMES, km.jd.PROJECTS, km.jd.GOALDIR, km.jd.CAPDIR = names, proj, td / "goals", td / "captions"
        km.jd.STATE = td
        km.NAMES = names
        km._tmux_sessions = lambda: {}                 # NOBODY is live: the lane is a dead one within the window
        (td / "states").mkdir(); (td / "captions").mkdir(); (td / "goals").mkdir()
        (td / "goals" / (SID + ".json")).write_text(json.dumps({"nodes": {}, "status": {}}))   # the judging marks need a store
        self.caps = td / "captions" / (SID + ".jsonl")
        km._parse_cache.pop(str(self.tpath), None)
        km._dead_lane_memo.clear()
        km._delta_entry_memo.clear()

    def tearDown(self):
        (km.jd.NAMES, km.jd.PROJECTS, km.jd.GOALDIR, km.jd.CAPDIR, km.jd.STATE, km.NAMES, km._tmux_sessions) = self.saved
        km._dead_lane_memo.clear()
        km._downtime[:] = []
        self.td.cleanup()

    def _write(self, recs):
        self.tpath.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
        os.utime(self.tpath, (NOW - 30, NOW - 30))    # recently touched: a lane within the 12 h window

    def _build(self, now=NOW):
        return km.build_timeline(now, {}, with_bars=True)

    def _lane(self, tl):
        return next(s for s in tl["sessions"] if s["id"] == SID)

    def test_the_second_build_serves_the_lane_without_a_parse_and_drops_the_parse(self):
        parses = []
        real = km._parse
        km._parse = lambda path, sid, now: (parses.append(path), real(path, sid, now))[1]
        try:
            tl1 = self._build()
            self.assertEqual(parses, [str(self.tpath)], "the first build parses the dead lane once")
            self.assertNotIn(str(self.tpath), km._parse_cache, "and drops the parse once the lane is cached")
            self.assertIn(SID, km._dead_lane_memo)
            tl2 = self._build()
            self.assertEqual(len(parses), 1, "the second build serves the lane: no parse")
            self.assertEqual(tl1["turns"][SID], tl2["turns"][SID])
            self.assertEqual(self._lane(tl1), self._lane(tl2), "a served lane is the rebuilt lane, byte for byte")
            self.assertEqual([m for m in tl1["judging"] if m["sid"] == SID], [m for m in tl2["judging"] if m["sid"] == SID])
            self.assertFalse(any("_h" in m for m in tl2["judging"]), "the horizon stamp never reaches the wire")
        finally:
            km._parse = real

    def test_a_moved_transcript_re_derives_the_lane(self):
        self._build()
        recs = self.recs + [_rec("user", T0 + 600, "u2", "a1", "and the cap?"),
                            _rec("assistant", T0 + 610, "a2", "u2", "Two minutes.")]
        self._write(recs)
        os.utime(self.tpath, (NOW - 20, NOW - 20))
        tl = self._build()
        self.assertEqual(len(tl["turns"][SID]), 2, "the new turn is drawn")
        self.assertEqual(km._dead_lane_memo[SID][1]["bars"], tl["turns"][SID])

    def test_the_memo_keeps_stamped_marks_and_the_wire_never_sees_the_stamp(self):
        cap_t = NOW - km.TL_HORIZON + 30
        self.caps.write_text(json.dumps({"id": "u1", "t": cap_t, "caption": "launched the benchmark",
                                         "grain": "segment"}) + "\n")
        tl = self._build(NOW)
        marks = km._dead_lane_memo[SID][1]["marks"]
        self.assertEqual([(m["judge"], m["_h"]) for m in marks], [("captioner", cap_t)], "derived once, stamped")
        self.assertFalse(any("_h" in m for m in tl["judging"]), "the stamp never reaches the wire")

    def test_every_keyed_input_re_derives_the_lane_when_it_moves(self):
        """The key is every file the parse-derived parts read, not the transcript alone (the review of the
        first batch found a key pinned on one component): touching each one changes the memo's key and the
        lane is derived again."""
        td = Path(self.td.name)
        self._build()
        key0 = km._dead_lane_memo[SID][0]
        inputs = [td / "states" / (SID + ".jsonl"), td / "goals" / (SID + ".json"),
                  td / "overrides" / (SID + ".jsonl"), td / "captions" / (SID + ".jsonl"),
                  td / "archive" / (SID + ".json"), td / "session-flags.json"]
        seen = {key0}
        for i, p in enumerate(inputs):
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.name == SID + ".json" and p.parent.name == "goals":
                p.write_text(json.dumps({"nodes": {}, "status": {}, "touched": i}))
            elif p.suffix == ".json":
                p.write_text(json.dumps({"touched": i}))
            else:
                p.write_text("")
            os.utime(p, (NOW - 10 + i, NOW - 10 + i))
            self._build()
            key = km._dead_lane_memo[SID][0]
            self.assertNotIn(key, seen, "%s moved but the key did not" % p.name)
            seen.add(key)
        self._build()
        self.assertEqual(km._dead_lane_memo[SID][0], key, "nothing moved: the key stands")

    def test_a_lane_whose_goals_store_cannot_be_read_is_never_cached(self):
        """A goals FAULT is a store that cannot be read (an OSError; malformed bytes are healed by the loader):
        the lane renders without goal-derived data, complains, and is derived again on every build rather
        than served from a memo that would silence the fault."""
        store = Path(self.td.name) / "goals" / (SID + ".json")
        store.chmod(0)
        try:
            self._build()
            self.assertNotIn(SID, km._dead_lane_memo, "a faulted store stays loud on every build, never served stale")
        finally:
            store.chmod(0o600)
        self._build()
        self.assertIn(SID, km._dead_lane_memo, "readable again: cached like any other dead lane")

    def test_a_live_lane_is_not_memoized(self):
        km._tmux_sessions = lambda: {SID: {"state": "waiting", "since": NOW - 100, "model": "", "effort": "",
                                           "context": None, "compactPct": None, "color": None, "mode": ""}}
        km.build_timeline(NOW, km._tmux_sessions(), with_bars=True)
        self.assertNotIn(SID, km._dead_lane_memo)

    def test_a_chmod_alone_moves_the_transcripts_stat_key(self):
        """A chmod, chown or rename moves a file's ctime while its mtime, size and inode stand, so the stat
        key carries st_ctime_ns as its fourth member: the repair of a read the memo cached as the empty lane is
        visible to the key."""
        p = str(self.tpath)
        k0 = km._stat_key(p)
        move_ctime(p)
        k1 = km._stat_key(p)
        self.assertNotEqual(k0, k1, "ctime is in the key: a chmod or a rename moves it")
        self.assertEqual(k0[:3], k1[:3], "mtime, size and inode stood")
        self.assertIsNone(km._stat_key(p + ".absent"))

    def test_a_failed_parse_is_served_once_cached_and_re_attempted_when_the_transcripts_stat_moves(self):
        """A transcript that cannot be read parses as the empty lane (the read layer returns no records on an
        OSError, silently) and a parse that raises leaves the same empty lane plus one stderr line; either is
        cached like any other lane (a dead transcript has no writer, so the result would repeat). The lane is
        derived again only when a keyed file moves, and a chmod or chown that repairs the read moves neither
        mtime, size nor inode: the ctime in the key is what makes the repair visible. The vehicle here is a
        raising stub, the path with an observable complaint; the chmod only moves the ctime."""
        parses, failing = [], [True]
        real = km._parse

        def parse(path, sid, now):
            parses.append(path)
            if failing[0]:
                raise OSError("unreadable")
            return real(path, sid, now)
        km._parse = parse
        km._BARS_COMPLAINED.pop((SID, "parse"), None)   # the complaint latch: one line per distinct cause
        err = io.StringIO()
        try:
            with redirect_stderr(err):
                tl1 = self._build()
                tl2 = self._build()
            self.assertEqual(len(parses), 1, "parsed once: the failed parse is cached as the empty lane")
            self.assertEqual(tl1["turns"][SID], [])
            self.assertEqual(tl2["turns"][SID], [], "served as the empty lane it drew")
            self.assertEqual(err.getvalue().count("timeline bars:"), 1, "one stderr line, none when served")
            self.assertIn(SID, km._dead_lane_memo)
            failing[0] = False
            move_ctime(self.tpath)
            tl3 = self._build()
            self.assertEqual(len(parses), 2, "the transcript's stat moved: the parse is attempted again")
            self.assertEqual(len(tl3["turns"][SID]), 1, "readable again: the bar is drawn")
            self._build()
            self.assertEqual(len(parses), 2, "and the repaired lane is served like any other")
        finally:
            km._parse = real

    def test_a_suspension_recorded_after_the_lane_was_cached_re_derives_it(self):
        """_awake_spans excises every recorded suspension from each segment's span, reading the in-memory list
        (its jsonl mirror is appended best-effort, so the list, not the file, is the input), and the list
        grows at run time when the producer's tick detects a sleep, on a thread other than the build's. The
        key carries the list: a nap inside a cached segment splits its bar on the very next build; a
        different nap of the same count is a different key; a nap outside every segment re-derives to equal
        bars; the same list rebound is served."""
        parses = []
        real = km._parse
        km._parse = lambda path, sid, now: (parses.append(path), real(path, sid, now))[1]
        try:
            self._build()
            key0 = km._dead_lane_memo[SID][0]
            self.assertEqual(len(parses), 1)
            km._downtime[:] = [(T0 + 3, T0 + 7)]            # a nap inside the one segment, an atom on each side
            tl = self._build()
            self.assertEqual(len(tl["turns"][SID]), 2, "the bar is cut at the nap on the very next build")
            self.assertEqual(len(parses), 2, "derived again, not served")
            key1 = km._dead_lane_memo[SID][0]
            self.assertNotEqual(key1, key0, "the suspensions are in the key")
            km._downtime[:] = [(T0 + 2, T0 + 8)]            # a different nap, the same count
            tl2 = self._build()
            self.assertNotEqual(tl2["turns"][SID], tl["turns"][SID], "a different nap cuts the bar elsewhere")
            key2 = km._dead_lane_memo[SID][0]
            self.assertNotEqual(key2, key1, "a nap of the same count is a different key")
            km._downtime.append((NOW - 20000, NOW - 19000))  # a sleep outside every segment: equal bars, a new key
            tl3 = self._build()
            key3 = km._dead_lane_memo[SID][0]
            self.assertNotEqual(key3, key2)
            self.assertEqual(tl3["turns"][SID], tl2["turns"][SID], "a nap outside every segment: the same bars")
            self.assertEqual(len(parses), 4)
            km._downtime[:] = list(km._downtime)            # the same content, rebound
            self._build()
            self.assertEqual(km._dead_lane_memo[SID][0], key3, "the same suspensions: the same key")
            self.assertEqual(len(parses), 4, "served")
        finally:
            km._parse = real


class HorizonFilterIsExact(unittest.TestCase):
    """The cached marks filtered on their stamped compare value are the marks a fresh derivation at that
    horizon would append, mark for mark: the diary and distiller marks are compared on their EVIDENCE time
    but emitted at the segment's work END, so a filter on the emitted time would admit a mark the fresh
    derivation drops (evidence before the horizon, work end after it). Pure functions, synthetic inputs."""

    def _inputs(self):
        h = 1_700_000_000
        caps = {"c%d" % i: {"id": "c%d" % i, "t": h - 100 + i * 50, "caption": "cap %d" % i, "grain": "segment"} for i in range(6)}
        goals = {"nodes": {
            "g1": {"t": h - 40, "mt": h + 10, "text": "old mint, done after the horizon",
                   "log": [{"src": "closer", "kind": "done", "ev_t": h - 5, "why": "evidence just before the horizon"}]},
            "g2": {"t": h + 20, "mt": h + 30, "text": "new mint", "distilledMt": h - 20, "briefedMt": h + 40},
        }}
        seg_ends = {h - 5: h + 300, h - 20: h + 400}      # completion marks land at the work END, after the horizon
        return h, caps, goals, seg_ends

    def test_filtered_stamped_marks_equal_a_fresh_derivation(self):
        h, caps, goals, seg_ends = self._inputs()
        for t0 in (h - 1000, h - 10, h, h + 15, h + 35, h + 1000):
            fresh = []
            km._derive_judging("s", caps, goals, t0, fresh, seg_ends)
            stamped = []
            km._derive_judging("s", caps, goals, 0, stamped, seg_ends, stamp=True)
            self.assertEqual(km._dead_lane_marks(stamped, t0), fresh, "horizon %+d" % (t0 - h))
        fresh = []
        km._derive_judging("s", caps, goals, h, fresh, seg_ends)
        self.assertFalse(any(m["judge"] == "closer" for m in fresh), "evidence before the horizon: dropped")
        self.assertTrue(any(m["judge"] == "distiller" and m["kind"] == "brief" for m in fresh))

    def test_the_stamp_is_private(self):
        h, caps, goals, seg_ends = self._inputs()
        stamped = []
        km._derive_judging("s", caps, goals, 0, stamped, seg_ends, stamp=True)
        self.assertTrue(stamped and all("_h" in m for m in stamped))
        self.assertFalse(any("_h" in m for m in km._dead_lane_marks(stamped, 0)))


class EntryEncodeMemo(unittest.TestCase):
    def test_an_entry_object_seen_last_split_is_not_encoded_again(self):
        km._delta_entry_memo.clear()
        sep = km._DELTA_SEP
        b1, b2 = {"id": "b1", "start": 1, "end": 2}, {"id": "b2", "start": 3, "end": 4}
        ents1, _ = km._delta_split("dictlist:id", {"S": [b1, b2]}, memo_key=("bars", "turns"))
        b3 = {"id": "b3", "start": 5, "end": 6}
        ents2, _ = km._delta_split("dictlist:id", {"S": [b1, b3]}, memo_key=("bars", "turns"))
        self.assertIs(ents2["S" + sep + "b1"][1], ents1["S" + sep + "b1"][1], "the same object: the same string, not re-encoded")
        self.assertEqual(json.loads(ents2["S" + sep + "b3"][1]), b3)
        self.assertNotIn(id(b2), km._delta_entry_memo[("bars", "turns")], "the memo is rebuilt from THIS split: no growth")
        b1b = dict(b1)                                   # equal content, a NEW object: encoded afresh (identity, never equality)
        ents3, _ = km._delta_split("dictlist:id", {"S": [b1b]}, memo_key=("bars", "turns"))
        self.assertEqual(ents3["S" + sep + "b1"][1], ents1["S" + sep + "b1"][1])
        self.assertIsNot(ents3["S" + sep + "b1"][1], ents1["S" + sep + "b1"][1])

    def test_the_wire_fill_hands_the_collection_key_down(self):
        import inspect
        self.assertIn("_delta_split(kind, value, memo_key=(ftype, name))", inspect.getsource(km._delta_parts))


if __name__ == "__main__":
    unittest.main()
