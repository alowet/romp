#!/usr/bin/env python3
"""The courier skips a session whose inputs have not moved since a scan that found nothing to place, and
reads the ones it scans through the shared read-only view (2026-09-09).

Measured on the maintainer's box: run_courier loaded every session's goal store with the writer's loader on
every triage pass, 1172 goal loads a pass across 18 sessions, 83% of the judge tier thread's samples. The
skip key is every input the per-session scan reads, taken before the store read (the chain-memo rule): the
parse cache's key bound to the session object, the store file's key with its journal's and archive's, the
episode log's key and the transcript path. Pins: unchanged inputs skip after a scan that placed nothing; a
moved store, a fresh parse or an episode boundary un-skips that session alone; a write landing during the
scan is seen next pass; three sessions with one moved place exactly what the ungated pass places; a parse
the cache does not hold is never skipped; the scan asks the writer's loader for nothing; the counters.

Synthetic fixtures only: placeholder sids, invented text, hostname TESTHOST; a temp root per test."""
import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
jd = SourceFileLoader("romp_judge_courier_skip", os.path.join(BIN, "romp-judge")).load_module()

A = "11111111-2222-3333-4444-777777777701"
B = "11111111-2222-3333-4444-777777777702"
C = "11111111-2222-3333-4444-777777777703"
SENDER = "aaaaaaaa-bbbb-cccc-dddd-777777777700"
T0 = 1781100000
DELEGATING = '{"verdict": "delegating", "goal": 0, "text": "check the subnet layout"}'


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def uline(t, text, uuid, parent=None):
    return {"type": "user", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent,
            "message": {"role": "user", "content": text}, "promptSource": "typed"}


def aline(t, text, uuid, parent):
    return {"type": "assistant", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}],
                        "stop_reason": "end_turn"}}


class _World(unittest.TestCase):
    SIDS = (A, B, C)

    def setUp(self):
        self._rooted_saved = jd._delegate_user_rooted
        jd._delegate_user_rooted = lambda *a, **k: True       # chain-rooted minting is orthogonal here
        self.saved = (jd.NAMES, jd.PROJECTS, jd.GOALDIR, jd.CAPDIR, jd.ARCHDIR, jd.PCACHE,
                      jd.MESSAGES, jd.ERRORS, jd.courier_llm)
        jd.courier_llm = lambda *a, **k: DELEGATING
        self._make_world()

    def tearDown(self):
        self._drop_world()
        (jd.NAMES, jd.PROJECTS, jd.GOALDIR, jd.CAPDIR, jd.ARCHDIR, jd.PCACHE,
         jd.MESSAGES, jd.ERRORS, jd.courier_llm) = self.saved
        jd._delegate_user_rooted = self._rooted_saved

    def _make_world(self):
        self.td = tempfile.TemporaryDirectory()
        td = Path(self.td.name)
        cdir = td / "launchdir"; cdir.mkdir()
        proj = td / "projects"
        munged = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(str(cdir)))
        self.proj_dir = proj / munged
        self.proj_dir.mkdir(parents=True)
        names = td / "names"; names.mkdir()
        for i, sid in enumerate(self.SIDS):
            (names / sid).write_text("worker%d\t%s\t#abcdef\n" % (i, str(cdir)))
        tl = td / "timeline"; tl.mkdir()
        jd.NAMES, jd.PROJECTS = names, proj
        jd.GOALDIR = td / "goals"
        jd.CAPDIR, jd.ARCHDIR, jd.PCACHE = td / "captions", td / "archive", td / "pcache"
        jd.MESSAGES = tl / "messages.jsonl"
        jd.ERRORS = td / "judge-errors.jsonl"
        jd.MESSAGES.write_text("")
        self.recs = {sid: [] for sid in self.SIDS}
        self.mids = 0
        self._reset_memos()
        jd._COURIER_SEEN.clear()
        for k in jd._COURIER_STATS:
            jd._COURIER_STATS[k] = 0
        for sid in self.SIDS:
            self.deliver(sid, T0 + 10 * self.SIDS.index(sid))

    def _drop_world(self):
        for sid in self.SIDS:
            try:
                (jd.EPIDIR / (sid + ".jsonl")).unlink()
            except OSError:
                pass
            try:
                (jd._overrides_dir() / (sid + ".jsonl")).unlink()
            except OSError:
                pass
        jd._COURIER_SEEN.clear()
        self._reset_memos()
        self.td.cleanup()

    @staticmethod
    def _reset_memos():
        jd._PARSE_CACHE.clear(); jd._CHAIN_MEMO.clear()
        jd._episode_memo.clear()
        jd._shared_clear()

    def deliver(self, sid, t):
        """One peer message (a declared delegate) lands in `sid`'s transcript, with its postal row."""
        self.mids += 1
        mid = "%d.%05d_%05d.TESTHOST" % (T0, self.mids, self.mids)
        with jd.MESSAGES.open("a") as f:
            f.write(json.dumps({"t": t - 5, "ev": "sent", "id": mid, "from": "sender", "from_id": SENDER,
                                "to_id": sid, "kind": "delegate",
                                "body": "check the subnet layout for box %d" % self.mids}) + "\n")
        n = len(self.recs[sid]) // 2 + 1
        parent = self.recs[sid][-1]["uuid"] if self.recs[sid] else None
        self.recs[sid] += [uline(t, "check the subnet layout for box %d\n<!-- romp-msg-id: %s -->\n"
                                    "<!-- romp-msg-kind: delegate -->" % (self.mids, mid), "u%d" % n, parent),
                           aline(t + 30, "Looking at box %d now." % self.mids, "a%d" % n, "u%d" % n)]
        p = self.proj_dir / (sid + ".jsonl")
        p.write_text("\n".join(json.dumps(r) for r in self.recs[sid]) + "\n")
        os.utime(p, (t + 60, t + 60))                       # a distinct mtime per write: the parse key moves
        jd._discover_cache["fp"] = None
        jd._discover_cache["result"] = None
        return mid

    def run_pass(self, now=T0 + 200):
        """One courier pass; returns the gate counters' deltas (scanned, skipped, recorded)."""
        before = jd.courier_skip_stats()
        jd._discover_cache["fp"] = None
        jd._discover_cache["result"] = None
        jd._postal_from_memo["key"] = None
        jd.run_courier(now=now)
        after = jd.courier_skip_stats()
        return tuple(after[k] - before[k] for k in ("scanned", "skipped", "recorded"))

    def stores(self):
        return {sid: json.loads((jd.GOALDIR / (sid + ".json")).read_text()) for sid in self.SIDS}

    @staticmethod
    def shape(store):
        """The decisions a pass makes for a session: its placements and its planted peer nodes."""
        planted = sorted((nd.get("text"), (nd.get("origin") or {}).get("msgId"))
                         for nd in store["nodes"].values() if isinstance(nd.get("origin"), dict))
        return (store["placements"], planted)


class CourierSkip(_World):
    def test_unchanged_inputs_skip_after_a_scan_that_placed_nothing(self):
        self.assertEqual(self.run_pass(), (3, 0, 0), "first pass: every session scanned, rows to place, none recorded")
        placed = self.stores()
        self.assertTrue(all(any(isinstance(nd.get("origin"), dict) for nd in st["nodes"].values())
                            for st in placed.values()), "a recipient top planted in each session")
        self.assertEqual(self.run_pass(), (3, 0, 3), "second pass: scanned, nothing to place, all three recorded")
        self.assertEqual(self.run_pass(), (0, 3, 0), "third pass: nothing moved, all three skipped")
        self.assertEqual(self.run_pass(), (0, 3, 0))
        self.assertEqual(self.stores(), placed, "a skipped pass writes nothing")

    def _settled(self):
        self.run_pass(); self.run_pass()
        self.assertEqual(self.run_pass(), (0, 3, 0))

    def test_a_moved_store_un_skips_that_session_only(self):
        self._settled()
        p = jd.GOALDIR / (A + ".json")
        d = json.loads(p.read_text()); d["seq"] = d.get("seq", 0) + 1
        p.write_text(json.dumps(d))
        self.assertEqual(self.run_pass(), (1, 2, 1), "A's store moved: A scanned and re-recorded, B and C skipped")

    def test_a_journal_write_un_skips(self):
        self._settled()
        jd._overrides_dir().mkdir(parents=True, exist_ok=True)
        with (jd._overrides_dir() / (B + ".jsonl")).open("a") as f:
            f.write(json.dumps({"op": "resolve", "id": B + ":gX", "t": T0 + 150}) + "\n")
        self.assertEqual(self.run_pass(), (1, 2, 1), "B's override journal moved: B alone scanned")

    def test_a_fresh_parse_un_skips(self):
        self._settled()
        p = self.proj_dir / (C + ".jsonl")
        recs = self.recs[C] + [uline(T0 + 120, "and the gateway?", "u9", self.recs[C][-1]["uuid"]),
                               aline(T0 + 130, "10.0.0.1", "a9", "u9")]
        p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
        os.utime(p, (T0 + 190, T0 + 190))
        self.assertEqual(self.run_pass(), (1, 2, 1), "C's transcript grew: C alone scanned")

    def test_an_episode_boundary_un_skips(self):
        self._settled()
        jd.EPIDIR.mkdir(parents=True, exist_ok=True)
        (jd.EPIDIR / (A + ".jsonl")).write_text(json.dumps({"t": T0 - 100, "kind": "seed"}) + "\n"
                                                + json.dumps({"t": T0 + 150, "kind": "clear"}) + "\n")
        self.assertEqual(self.run_pass(), (1, 2, 1), "A's episode log moved: A alone scanned")

    def test_a_write_landing_during_the_scan_is_seen_next_pass(self):
        # INTERLEAVED WRITE: the key is taken before the store read. A row appended to A's journal while the
        # scan reads A's store leaves the recorded key behind the file, so the next pass scans A again.
        self.run_pass()                                   # places
        real = jd.load_goals_shared
        landed = []

        def read_then_write(fsid):
            store = real(fsid)
            if fsid == A and not landed:
                landed.append(True)
                jd._overrides_dir().mkdir(parents=True, exist_ok=True)
                with (jd._overrides_dir() / (A + ".jsonl")).open("a") as f:
                    f.write(json.dumps({"op": "resolve", "id": A + ":gX", "t": T0 + 160}) + "\n")
            return store
        jd.load_goals_shared = read_then_write
        try:
            self.assertEqual(self.run_pass(), (3, 0, 3), "the recording pass, with A's write landing mid-scan")
        finally:
            jd.load_goals_shared = real
        self.assertTrue(landed)
        self.assertEqual(self.run_pass(), (1, 2, 1), "A is scanned again: its recorded key predates the write")
        self.assertEqual(self.run_pass(), (0, 3, 0))

    def test_three_sessions_one_moved_place_exactly_what_the_ungated_pass_places(self):
        def scenario(gated):
            self.run_pass()                               # places the first three
            self.run_pass()                               # records all three
            self.deliver(B, T0 + 150)                     # B moves: a second message
            if not gated:
                jd._COURIER_SEEN.clear()                  # the ungated pass scans every session
            counts = self.run_pass(now=T0 + 300)
            return counts, {sid: self.shape(st) for sid, st in self.stores().items()}
        gated_counts, gated = scenario(True)
        self._drop_world(); self._make_world()
        ungated_counts, ungated = scenario(False)
        self.assertEqual(gated_counts, (1, 2, 0), "gated: B scanned with rows to place, A and C skipped")
        self.assertEqual(ungated_counts, (3, 0, 2), "ungated: all scanned, A and C recorded")
        self.assertEqual(gated, ungated, "the same placements and planted nodes either way")
        self.assertEqual(len(gated[B][1]), 2, "B's second delegate planted")

    def test_a_placed_delegate_without_its_link_keeps_the_session_scanned_until_the_repair_lands(self):
        # PLANNER-FIRST PLACEMENT: A's delegate segment sits under a plain top with no courier link, and no
        # sender tracks the message yet. The repair's other input is the SENDER's store (_handoff_backref),
        # outside A's key, so A is never recorded while the link is missing; once the sender's tracking node
        # exists, the next pass attaches the link through a writer load, and only then does A settle.
        path = self.proj_dir / (A + ".jsonl")
        mid_a = self.recs[A][0]["message"]["content"].split("romp-msg-id: ")[1].split(" ")[0]
        session = jd.parsed_session(A, [str(path)], T0 + 200)
        fresh = jd.load_goals(A)
        seg = next(sg for tn in session["turns"] for sg in jd._segs(tn, fresh) if (jd._seg_peer(sg) or ("",))[0])
        top = {"id": A + ":g1", "text": "Look after the subnet", "parentId": None, "nodeComplete": False,
               "blocked": False, "cleared": False, "trail": [], "t": T0}
        jd.GOALDIR.mkdir(parents=True, exist_ok=True)
        (jd.GOALDIR / (A + ".json")).write_text(json.dumps(
            {"rompUuid": A, "seq": 1, "lastNode": top["id"], "closedTurns": [], "nodes": {top["id"]: top},
             "placements": {seg["id"]: top["id"]}, "status": {top["id"]: "working"}}))
        self._reset_memos()
        self.run_pass()                                   # B and C place; A has nothing pending but an open repair
        self.assertEqual(self.run_pass(), (3, 0, 2), "B and C recorded; A stays scanned: its link is missing")
        self.assertEqual(self.run_pass(), (1, 2, 0), "A alone, every pass, while no sender tracks the message")
        self.assertNotIn("links", jd.load_goals(A)["nodes"][top["id"]])
        # the sender's tracking node appears (a names entry and a transcript make the sender discoverable, the way
        # _handoff_backref finds sender boards; its store carries the handoff)
        (jd.NAMES / SENDER).write_text("sender\t%s\t#abcdef\n" % str(Path(self.td.name) / "launchdir"))
        (self.proj_dir / (SENDER + ".jsonl")).write_text(json.dumps(uline(T0 - 100, "hand the subnet check to worker0", "s1"))
                                                         + "\n" + json.dumps(aline(T0 - 90, "Delegated.", "s2", "s1")) + "\n")
        snd = jd.load_goals(SENDER)
        snd["nodes"][SENDER + ":g1"] = {"id": SENDER + ":g1", "text": "delegated to worker0", "parentId": None,
                                        "nodeComplete": False, "blocked": False, "cleared": False, "trail": [],
                                        "t": T0, "handoff": {"peer": A, "msgId": mid_a}}
        snd["status"][SENDER + ":g1"] = "working"
        jd.save_goals(SENDER, snd)
        private, o_load = [], jd.load_goals
        jd.load_goals = lambda fsid: (private.append(fsid), o_load(fsid))[1]
        try:
            self.assertEqual(self.run_pass(), (2, 2, 1), "A and the now-discoverable sender scanned, B and C skipped; "
                                                         "the sender records, A does not yet (its store just moved)")
        finally:
            jd.load_goals = o_load
        self.assertIn(A, private, "the repair took a writer load for A")
        links = jd.load_goals(A)["nodes"][top["id"]].get("links") or []
        self.assertEqual([l.get("msgId") for l in links], [mid_a], "the link attached")
        self.assertEqual(self.run_pass(), (1, 3, 1), "A's store moved with the link: scanned once more and recorded; "
                                                     "B, C and the sender skipped")
        self.assertEqual(self.run_pass(), (0, 4, 0), "and now every session is settled")

    def test_a_parse_the_cache_does_not_hold_is_never_skipped(self):
        real = jd.parsed_session
        jd.parsed_session = lambda fsid, paths, now: dict(real(fsid, paths, now))   # a copy: not the cache's object
        try:
            self.run_pass(); self.run_pass()
            self.assertEqual(self.run_pass(), (3, 0, 0), "unkeyed: scanned every pass, never recorded")
        finally:
            jd.parsed_session = real

    def test_the_scan_asks_the_writers_loader_for_nothing(self):
        self.run_pass()                                   # places (writers, legitimately)
        private, o_load = [], jd.load_goals
        jd.load_goals = lambda fsid: (private.append(fsid), o_load(fsid))[1]
        try:
            self.assertEqual(self.run_pass(), (3, 0, 3))
        finally:
            jd.load_goals = o_load
        self.assertEqual(private, [], "a scan with nothing to place reads only the view")

    def test_the_counters(self):
        self.assertEqual(set(jd.courier_skip_stats()), {"skipped", "scanned", "recorded"})
        s = jd.courier_skip_stats(); s["skipped"] = 99
        self.assertNotEqual(jd.courier_skip_stats()["skipped"], 99, "a copy")

    def test_a_rebound_root_forgets_the_seen_keys(self):
        self._settled()
        self.assertTrue(jd._COURIER_SEEN)
        saved = jd.STATE
        other = tempfile.TemporaryDirectory()
        try:
            jd._rebind_state(Path(other.name))
            self.assertEqual(jd._COURIER_SEEN, {})
        finally:
            jd._rebind_state(saved)
            other.cleanup()


if __name__ == "__main__":
    unittest.main()
