#!/usr/bin/env python3
"""A whole assembly entry re-seats on the document written from it (the 2026-09-24 investigation of the kernel's whole
re-parses). An entry built by a whole parse (a boot with no document, a compaction, a demotion with none standing) kept
every record and atom for the life of the process: the settle and the converge pass wrote the leaf's assembly document FROM
it and left it whole, so every later fold re-ran the graph passes over every record and copied every atom, and every serve
segmented the whole history again (on synthetic transcripts of 150 MB, a fold an order of magnitude dearer than one over a
restored entry), and the chat's render floor stayed at turn 0. Pinned here, by the parse's own road counters and the
entry's size on a synthetic episode: once the document stands, the next parse takes the restore road from it, the tree is
the cold parse's, and the folds after it walk the tail alone. And the rules that keep the re-seat from costing more than it
saves, or from serving less than the whole entry did: the re-seated entry carries the churn bound (its cut still advances
once the tail reaches the share), also through a restore after a descent; an entry whose document's tail already meets
the share is not re-seated; a re-seat the restore refuses, or an entry whose leaf's document a restore just refused, stays
whole, and the writer's churn hold keeps its document as it is until the share; and an entry whose postal author still
waits on the log is not re-seated. Synthetic transcripts only: invented text in the notes-api demo world, private
placeholder ids."""
import gzip
import json
import os
import random
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from romp_load import load_source

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
# Hermetic state BEFORE the load: the event model resolves its state root at import time, and only pytest runs conftest's
# floor (a bare unittest or script run would otherwise write REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
em = load_source("romp_event_model", os.path.join(BIN, "romp-event-model"))

SID = "5ea70924-2222-4333-8444-00000000a5e1"          # this module's own placeholder session id
NOW = 1781200000
PEER = "5ea70924-2222-4333-8444-00000000a5e2"         # a peer session's placeholder id (the postal sender)
MSG = "1781200000.222_444.TESTHOST"                   # a synthetic postal message id
WORDS = ("notes", "search", "index", "query", "cursor", "page", "cache", "retry", "fixture", "route", "schema", "review")


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _words(rnd, n):
    return " ".join(rnd.choice(WORDS) for _ in range(n))


def episode(t0, turns=240, compact_every=80, tool_every=6, seed=24):
    """A long synthetic session: typed prompts and prose replies, a Bash call and its result every `tool_every` turns, and
    an automatic compaction (the boundary and its summary) every `compact_every` turns."""
    rnd = random.Random(seed)
    recs, parent, t = [], None, t0
    for k in range(turns):
        if k and k % compact_every == 0:
            b, s = "b%d" % k, "s%d" % k
            recs.append({"type": "system", "subtype": "compact_boundary", "uuid": b, "parentUuid": None, "logicalParentUuid": parent,
                         "timestamp": iso(t), "compactMetadata": {"trigger": "auto", "preTokens": 160000, "postTokens": 9000}})
            recs.append({"type": "user", "uuid": s, "parentUuid": b, "timestamp": iso(t + 1), "isCompactSummary": True,
                         "message": {"role": "user", "content": "summary so far: " + _words(rnd, 80)}})
            parent = s; t += 2
        u = "u%d" % k
        recs.append({"type": "user", "uuid": u, "parentUuid": parent, "timestamp": iso(t), "promptSource": "typed", "cwd": "/w/notes-api",
                     "message": {"role": "user", "content": "%s %d" % (_words(rnd, 24), k)}})
        parent = u
        if k % tool_every == 0:
            c, r = "c%d" % k, "r%d" % k
            recs.append({"type": "assistant", "uuid": c, "parentUuid": parent, "timestamp": iso(t + 5), "cwd": "/w/notes-api",
                         "message": {"id": "msg_c%d" % k, "role": "assistant", "stop_reason": "tool_use",
                                     "content": [{"type": "tool_use", "id": "toolu_%d" % k, "name": "Bash",
                                                  "input": {"command": "uv run pytest -q tests/test_search.py"}}]}})
            out = "%d passed\n%s" % (10 + k % 7, _words(rnd, 60))
            recs.append({"type": "user", "uuid": r, "parentUuid": c, "sourceToolAssistantUUID": c, "timestamp": iso(t + 9),
                         "toolUseResult": {"stdout": out, "stderr": "", "interrupted": False},
                         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_%d" % k, "content": out}]}})
            parent = r
        a = "a%d" % k
        recs.append({"type": "assistant", "uuid": a, "parentUuid": parent, "timestamp": iso(t + 20), "cwd": "/w/notes-api",
                     "message": {"id": "msg_a%d" % k, "role": "assistant", "stop_reason": "end_turn",
                                 "content": [{"type": "text", "text": _words(rnd, 90)}]}})
        parent = a; t += 60
    return recs


def tool_round(t, k, parent, width=400):
    """One call and its result inside a turn that stays open (the call's stop reason is tool_use, no reply follows yet)."""
    c, r = "oc%d" % k, "or%d" % k
    out = "%d passed\n%s" % (k, _words(random.Random(k), width))
    return [{"type": "assistant", "uuid": c, "parentUuid": parent, "timestamp": iso(t), "cwd": "/w/notes-api",
             "message": {"id": "msg_oc%d" % k, "role": "assistant", "stop_reason": "tool_use",
                         "content": [{"type": "tool_use", "id": "toolu_o%d" % k, "name": "Bash",
                                      "input": {"command": "uv run pytest -q tests/test_index_%d.py" % k}}]}},
            {"type": "user", "uuid": r, "parentUuid": c, "sourceToolAssistantUUID": c, "timestamp": iso(t + 4),
             "toolUseResult": {"stdout": out, "stderr": "", "interrupted": False},
             "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_o%d" % k, "content": out}]}}]


def spur(t, opener):
    """An api_error spur as the CLI writes one when a request fails: the error record parented at the turn's opener (where
    the request started), and the next prompt chained onto the error record. The new leaf does not chain back to the old
    one through the delta, and nothing in it hangs off a tool call, so the fold's gate demotes the entry for descent."""
    return [{"type": "system", "subtype": "api_error", "uuid": "de1", "parentUuid": opener, "level": "error", "timestamp": iso(t),
             "error": {"type": "overloaded_error"}},
            {"type": "user", "uuid": "du1", "parentUuid": "de1", "timestamp": iso(t + 10), "promptSource": "typed", "cwd": "/w/notes-api",
             "message": {"role": "user", "content": "and the export endpoint of the notes-api?"}}]


def rewind(t, before):
    """A rewound prompt: the last prompt asked again, parented at the record before it (`before`), so the last exchange
    leaves the active branch and the new leaf does not chain back to the old one (a descent)."""
    return [{"type": "user", "uuid": "du1", "parentUuid": before, "timestamp": iso(t), "promptSource": "typed", "cwd": "/w/notes-api",
             "message": {"role": "user", "content": "actually, page the search index by cursor instead"}}]


def turn(t, k, parent):
    """One more settled turn chained onto `parent`: a typed prompt and its reply."""
    u, a = "xu%d" % k, "xa%d" % k
    return [{"type": "user", "uuid": u, "parentUuid": parent, "timestamp": iso(t), "promptSource": "typed", "cwd": "/w/notes-api",
             "message": {"role": "user", "content": "follow-up %d on the notes-api search" % k}},
            {"type": "assistant", "uuid": a, "parentUuid": u, "timestamp": iso(t + 20), "cwd": "/w/notes-api",
             "message": {"id": "msg_x%d" % k, "role": "assistant", "stop_reason": "end_turn",
                         "content": [{"type": "text", "text": "follow-up %d is done: the cursor pages the index" % k}]}}]


def _strip(tree):
    """A tree as JSON compares it (the stage 4a harness's rule): a restored tree's pre-cut turns built into plain turns, the
    lazy markers dropped once hydrated, the cut turn left out (a restored tree's own fact)."""
    t = json.loads(json.dumps(em.plain_tree(tree), default=lambda o: "<unserializable>"))
    t.pop("cutTurn", None)
    for tr in t["turns"]:
        for a in tr["atoms"]:
            a.pop("lazy", None)
    return t


class Episode(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp()).resolve()      # the real path: the reader's key and the assembly cache's realpath key agree
        self.ck = self.td / "checkpoints"
        em.set_checkpoint_dir(lambda: self.ck)
        self.leaf = str(self.td / (SID + ".jsonl"))
        self.recs = episode(NOW - 86400)
        Path(self.leaf).write_text("".join(json.dumps(r) + "\n" for r in self.recs))
        self.k = 0
        self.postal = []                                   # the postal log's rows, as the parse reads them
        self.fresh()

    def tearDown(self):
        em.set_checkpoint_dir(None)
        self.fresh()
        shutil.rmtree(self.td, ignore_errors=True)

    def fresh(self):
        """A kernel restart's in-memory side: every reader entry, assembly entry, hydrated body and memoized document gone."""
        with em._JSONL_CACHE_LOCK:
            em._JSONL_CACHE.clear()
        with em._ASM_LOCK:
            em._ASM_CACHE.clear()
        em._TRAILING_CACHE.clear()
        with em._ASM_CKPT_LOCK:
            em._HYDRATED.clear(); em._HYDRATED_BYTES[0] = 0
            em._ASM_DOC_MEMO.clear(); em._ASM_DOC_MEMO_BYTES[0] = 0
        em._LAZY_FILES.clear()
        with em._READ_BYTES_LOCK:
            em._READ_BYTES.clear()

    def append(self, recs):
        self.recs += recs
        with open(self.leaf, "a") as f:
            f.write("".join(json.dumps(r) + "\n" for r in recs))

    def begin(self, recs):
        """Start the leaf over with `recs` (before any parse of it)."""
        self.recs = list(recs)
        Path(self.leaf).write_text("".join(json.dumps(r) + "\n" for r in self.recs))

    def last_uuid(self):
        return next(r["uuid"] for r in reversed(self.recs) if r.get("uuid"))

    def last_t(self):
        return max(em.parse_z(r["timestamp"]) for r in self.recs if r.get("timestamp"))

    def append_turn(self):
        """A settled turn on the leaf, stamped past every record so far (the fold's stamp gate holds)."""
        self.k += 1
        self.append(turn(self.last_t() + 60, self.k, self.last_uuid()))

    def doc_cut(self):
        """The leaf's cut offset in the standing document: where the pre-cut bytes end."""
        d = json.loads(gzip.decompress(em._asm_ckpt_file(self.leaf).read_bytes()))
        return int(d["files"][Path(self.leaf).stem]["cut"][0])

    def parse(self):
        mode = []
        out = em.parse_session(self.leaf, rompuuid=SID, name="web", dir="/w/notes-api", candidate_files=[self.leaf],
                               states=None, postal_log=list(self.postal), now=NOW, asm_mode_out=mode)
        return out, (mode[-1] if mode else None)

    def settle(self, tree):
        """The settle's write: the leaf's document from its assembly entry, with the tree the parse store holds."""
        return em.asm_checkpoint_write(self.leaf, SID, tree=tree)

    def doc_bytes(self):
        return em._asm_ckpt_file(self.leaf).read_bytes()

    def grow_to_the_share(self, base=1000):
        """Append settled turns until the tail past the standing document's cut reaches the churn bound's share; returns the
        cut it was measured from."""
        cut0 = self.doc_cut()
        grow = []
        for k in range(4000):                                   # loop-ok: bounded; the share is reached long before
            if (os.path.getsize(self.leaf) + sum(len(json.dumps(r)) + 1 for r in grow) - cut0) * em._ASM_TAIL_SHARE >= cut0:
                break
            grow += turn(self.last_t() + 60 * (len(grow) + 1), base + k, grow[-1]["uuid"] if grow else self.last_uuid())
        self.append(grow)
        return cut0

    @staticmethod
    def skipped():
        return dict(em.asm_checkpoint_stats()["skipped"])

    def entry(self):
        with em._ASM_LOCK:
            return em._ASM_CACHE.get((os.path.realpath(self.leaf), SID, False))

    def cold(self):
        """The reference: a whole parse from zero in a fresh process with no document, hydrated and stripped."""
        self.fresh()
        saved = em._CKPT_DIR_FN
        em._CKPT_DIR_FN = None
        try:
            out, _ = self.parse()
        finally:
            em._CKPT_DIR_FN = saved
        return _strip(out)

    def assertColdEqual(self, tree):
        em.hydrate(tree, SID)
        got = _strip(tree)
        want = self.cold()
        self.assertEqual(len(got["turns"]), len(want["turns"]), "as many turns as the cold parse")
        self.assertEqual([t["id"] for t in got["turns"]], [t["id"] for t in want["turns"]], "the cold parse's turn ids, in order")
        self.assertEqual(got, want, "and the cold parse's tree, atom for atom and body for body")

    @staticmethod
    def stats():
        return dict(em._ASM_STATS)

    @staticmethod
    def moved(a, b):
        return {k: b.get(k, 0) - a.get(k, 0) for k in set(a) | set(b) if b.get(k, 0) != a.get(k, 0)}


class WholeEntryReseats(Episode):
    """The defect itself: the settle writes the document from a whole entry, and the next parse still folds the whole entry."""

    def test_after_the_settle_writes_the_document_the_next_parse_restores_from_it(self):
        out, mode = self.parse()
        self.assertEqual(mode, "full", "no document yet: a whole parse")
        self.assertTrue(self.settle(out), "the settle wrote the document: %s" % em.asm_checkpoint_stats()["skipped"])
        self.append_turn()
        s0 = self.stats()
        out2, mode2 = self.parse()
        d = self.moved(s0, self.stats())
        self.assertEqual(mode2, "restore", "once its document stands the entry takes the restore road from it; on main the whole "
                         "entry keeps folding: road %s, cutTurn %r, %d turns, counters moved %s"
                         % (mode2, out2.get("cutTurn"), len(out2["turns"]), d))
        self.assertEqual((d.get("g:reseat"), d.get("restore:afterDemote"), d.get("full", 0)), (1, 1, 0), "counted as a re-seat: %s" % d)
        self.assertGreater(out2.get("cutTurn", 0), 0, "the render floor moved from turn 0 to the cut")
        self.assertColdEqual(out2)

    def test_the_folds_after_the_reseat_walk_the_tail_alone(self):
        out, _ = self.parse()
        whole = self.entry()
        n_recs, n_atoms = len(whole["ad"].by_uuid), len(whole["atoms"])
        self.assertTrue(self.settle(out))
        walked, modes = [], []
        for _k in range(3):
            self.append_turn()
            out, m = self.parse()
            modes.append(m)
            e = self.entry()
            walked.append((len(e["ad"].by_uuid), len(e["atoms"])))
        for i, (recs_n, atoms_n) in enumerate(walked):
            self.assertLess(recs_n * 10, n_recs, "parse %d after the write walked %d records and copied %d atoms of the whole "
                            "entry's %d and %d (roads %s): every fold re-derived the whole history" % (i + 1, recs_n, atoms_n, n_recs, n_atoms, modes))
            self.assertLess(atoms_n * 10, n_atoms, "parse %d copied %d atoms of %d" % (i + 1, atoms_n, n_atoms))
        self.assertEqual(modes, ["restore", "fold", "fold"], "one re-seat, then folds over the restored entry")
        self.assertColdEqual(out)


class ReseatKeepsTheChurnBound(Episode):
    """The whole entry carried the churn bound in the writer (a standing document is rewritten once the tail past its cut
    reaches an eighth of the pre-cut bytes); a re-seated entry carries it in the fold's gate, so its leaf's cut still
    advances, and an entry whose document's tail already meets the share is not re-seated at all."""

    def test_a_reseated_entry_whose_tail_reaches_the_share_is_parsed_whole_and_its_cut_advances(self):
        out, _ = self.parse()
        self.assertTrue(self.settle(out))
        cut0 = self.doc_cut()
        self.append_turn()
        _, m1 = self.parse()
        self.assertEqual(m1, "restore", "re-seated on the document")
        grow = []
        for k in range(4000):                                   # loop-ok: bounded; the share is reached long before
            if (os.path.getsize(self.leaf) + sum(len(json.dumps(r)) + 1 for r in grow) - cut0) * em._ASM_TAIL_SHARE >= cut0:
                break
            grow += turn(self.last_t() + 60 * (len(grow) + 1), 1000 + k, grow[-1]["uuid"] if grow else self.last_uuid())
        self.append(grow)
        s0 = self.stats()
        out, m2 = self.parse()
        d = self.moved(s0, self.stats())
        self.assertEqual((m2, d.get("g:tailShare")), ("full", 1), "the tail past the cut reached the share: the re-seated entry "
                         "is demoted to the whole parse, as the whole entry's writer rewrote at the share (%s)" % d)
        self.assertTrue(self.settle(out), "the settle after the whole parse writes: %s" % em.asm_checkpoint_stats()["skipped"])
        self.assertGreater(self.doc_cut(), cut0 + (os.path.getsize(self.leaf) - cut0) // 2, "the cut advanced past the grown tail")
        self.append_turn()
        out, m3 = self.parse()
        self.assertEqual(m3, "restore", "and the next parse re-seats on the new document")
        self.assertColdEqual(out)

    def test_a_document_whose_tail_already_meets_the_share_leaves_the_entry_whole(self):
        """A turn that stays open (a long run of tool calls) keeps the cut before the last settled turn while the tail grows;
        re-seated there, the restored entry would demote at its first fold and the whole parse would write the same cut again
        at every settle. The entry stays whole and folds, as before the re-seat."""
        recs = episode(NOW - 86400, turns=40, compact_every=1000)
        t = max(em.parse_z(r["timestamp"]) for r in recs) + 60
        opener = {"type": "user", "uuid": "ou", "parentUuid": recs[-1]["uuid"], "timestamp": iso(t), "promptSource": "typed",
                  "cwd": "/w/notes-api", "message": {"role": "user", "content": "run the whole index suite, file by file"}}
        recs.append(opener)
        for k in range(6):
            recs += tool_round(t + 10 * (k + 1), k, recs[-1]["uuid"])
        self.begin(recs)
        out, _ = self.parse()
        self.assertTrue(self.settle(out))
        self.assertGreaterEqual((os.path.getsize(self.leaf) - self.doc_cut()) * em._ASM_TAIL_SHARE, self.doc_cut(),
                                "the fixture's premise: the open turn's tail already meets the share")
        s0 = self.stats()
        modes = []
        for k in range(6, 10):
            self.append(tool_round(self.last_t() + 10, k, self.last_uuid()))
            out, m = self.parse()
            modes.append(m)
            self.settle(out)                                    # the settle writes at every states row of the open turn
        d = self.moved(s0, self.stats())
        self.assertEqual(modes, ["fold"] * 4, "no re-seat, no whole parse per call of the open turn: %s" % d)
        self.assertEqual((d.get("full", 0), d.get("g:reseat", 0)), (0, 0), "%s" % d)
        self.assertColdEqual(out)


def _refused_with_its_document(key, leaf_path, *a, **k):
    """A restore that refuses the leaf's document the way a document that does not verify is refused: counted, said once,
    and removed from disk."""
    em._asm_ckpt_note(leaf_path, "identity")
    return None


class ARefusedReseatStaysWhole(Episode):
    """A re-seat whose restore does not serve must not become a loop (a document written at every settle, refused at the next
    miss, and the history parsed whole again): the entry the whole parse builds after the refusal stays whole and folds.
    Such an entry is where the writer's churn hold still governs (a whole entry with a standing document rewrites it only
    once the tail past its cut reaches the share or a compaction lands past it), so both tests here pin the hold too: every
    settle after the entry's first write leaves the document as it is (`written`), where a rewrite would cost a whole
    document build per settled turn (review of 2026-09-24, medium 2)."""

    def test_a_reseat_the_restore_refuses_is_not_tried_again_for_that_entry(self):
        out, _ = self.parse()
        self.assertTrue(self.settle(out))
        with mock.patch.object(em, "_asm_restore", _refused_with_its_document):
            s0, k0 = self.stats(), self.skipped()
            modes, wrote, doc = [], [], None
            for _k in range(4):
                self.append_turn()
                out, m = self.parse()
                modes.append(m)
                wrote.append(self.settle(out))                  # the settle runs after every turn
                if doc is None:
                    doc = self.doc_bytes()
            d, k = self.moved(s0, self.stats()), self.moved(k0, self.skipped())
        self.assertEqual(modes, ["full", "fold", "fold", "fold"], "one refused re-seat, one whole parse, then folds: %s" % d)
        self.assertEqual(d.get("g:reseat"), 1, "the re-seat is tried once: %s" % d)
        self.assertEqual((wrote, k), ([True, False, False, False], {"written": 3}), "the whole parse's entry writes its document "
                         "once; the churn hold keeps it while the tail is under the share (settles %s, skipped %s)" % (wrote, k))
        self.assertEqual(self.doc_bytes(), doc, "the document is the one written after the whole parse")
        self.assertColdEqual(out)

    def test_after_a_restore_refused_a_standing_document_the_whole_entry_is_not_reseated(self):
        """A boot whose restore the tail's shape refuses (the chain proof; the document stands) parses whole and rewrites the
        document at once (the refusal's own write); the entry that parse built is not re-seated on it, since the same tail
        refuses it again."""
        out, _ = self.parse()
        self.assertTrue(self.settle(out))
        self.fresh()                                            # a restart: the next parse offers the document to the restore
        with mock.patch.object(em, "_tail_chains_onto_the_document", lambda *a, **k: False):
            s0 = self.stats()
            out, m0 = self.parse()
            doc, k0 = self.doc_bytes(), self.skipped()          # the refusal's own write, from the whole parse
            modes, wrote = [], []
            for _k in range(3):
                self.append_turn()
                out, m = self.parse()
                modes.append(m)
                wrote.append(self.settle(out))
            d, k = self.moved(s0, self.stats()), self.moved(k0, self.skipped())
        self.assertEqual((m0, d.get("restore:chainRefused")), ("full", 1), "the boot's restore refused, the whole parse served: %s" % d)
        self.assertEqual(modes, ["fold"] * 3, "the whole entry folds, never re-seated on a document its tail refuses: %s" % d)
        self.assertEqual(d.get("g:reseat", 0), 0, "%s" % d)
        self.assertEqual((wrote, k), ([False] * 3, {"written": 3}), "the churn hold keeps the standing document while the tail "
                         "is under the share (settles %s, skipped %s)" % (wrote, k))
        self.assertEqual(self.doc_bytes(), doc, "the document is the refusal's own write")
        self.assertColdEqual(out)


class ReseatSurvivesADescent(Episode):
    """An api_error spur off the last turn's opener with a prompt chained onto it, and a rewound prompt in the tail, each
    demote the entry for descent (the new leaf does not chain back to the old one through the delta), and a descent takes
    the restore road again. The churn bound has to ride that restore: a restore without it leaves a turns-section entry
    with no churn gate (`prefix` is empty), the writer skips it as restored, and its cut never moves again in the process
    (review of 2026-09-24, medium 1). Each shape in both places: after the re-seat, where the restored entry carries the
    re-seat's flag, and as the first delta after the write, which demotes the marked whole entry before any re-seat. Neither
    shape hangs off a tool call, so each stays a descent whatever the gate makes of a parallel tool batch's results."""

    def opener(self):
        """The last turn's typed prompt."""
        return next(r for r in reversed(self.recs) if r.get("type") == "user" and r.get("promptSource") == "typed")

    def descend(self, shape):
        """Append the descent of `shape` and parse (the premise: a descent demotion served by the restore), then the reply to
        the prompt it ends on, which folds."""
        t = self.last_t() + 60
        recs = spur(t, self.opener()["uuid"]) if shape == "spur" else rewind(t, self.opener()["parentUuid"])
        s0 = self.stats()
        self.append(recs)
        _, m = self.parse()
        d = self.moved(s0, self.stats())
        self.assertEqual((m, d.get("g:descent", 0), d.get("restore:afterDemote", 0)), ("restore", 1, 1), "the fixture's premise: "
                         "the %s demotes the entry for descent and the restore serves it (%s)" % (shape, d))
        self.append([{"type": "assistant", "uuid": "da1", "parentUuid": "du1", "timestamp": iso(self.last_t() + 20), "cwd": "/w/notes-api",
                      "message": {"id": "msg_da1", "role": "assistant", "stop_reason": "end_turn",
                                  "content": [{"type": "text", "text": "the export endpoint pages the notes by cursor"}]}}])
        _, m = self.parse()
        self.assertEqual(m, "fold", "the reply chains onto the new leaf")

    def grown_is_parsed_whole_and_the_cut_advances(self):
        cut0 = self.grow_to_the_share()
        s0 = self.stats()
        out, m = self.parse()
        d = self.moved(s0, self.stats())
        self.assertEqual((m, d.get("g:tailShare")), ("full", 1), "the tail past the cut reached the share after a restore for "
                         "descent: the entry is demoted to the whole parse (%s)" % d)
        self.assertTrue(self.settle(out), "the settle after the whole parse writes: %s" % self.skipped())
        self.assertGreater(self.doc_cut(), cut0 + (os.path.getsize(self.leaf) - cut0) // 2, "the cut advanced past the grown tail")
        self.append_turn()
        out, m = self.parse()
        self.assertEqual(m, "restore", "and the next parse re-seats on the new document")
        self.assertColdEqual(out)

    def after_the_reseat(self, shape):
        out, _ = self.parse()
        self.assertTrue(self.settle(out))
        self.append_turn()
        _, m = self.parse()
        self.assertEqual(m, "restore", "re-seated on the document")
        self.descend(shape)
        self.grown_is_parsed_whole_and_the_cut_advances()

    def as_the_first_delta_after_the_write(self, shape):
        """The settle writes from the whole entry and marks it; the descent demotes that marked entry at its next parse,
        before the gates could pass a delta and re-seat it, and the restore after the descent re-seats the entry."""
        out, m = self.parse()
        self.assertEqual(m, "full")
        self.assertTrue(self.settle(out), "the settle writes: %s" % self.skipped())
        self.descend(shape)
        self.grown_is_parsed_whole_and_the_cut_advances()

    def test_a_spur_after_the_reseat_keeps_the_churn_bound(self):
        self.after_the_reseat("spur")

    def test_a_rewind_after_the_reseat_keeps_the_churn_bound(self):
        self.after_the_reseat("rewind")

    def test_a_spur_as_the_first_delta_after_the_write_keeps_the_churn_bound(self):
        self.as_the_first_delta_after_the_write("spur")

    def test_a_rewind_as_the_first_delta_after_the_write_keeps_the_churn_bound(self):
        self.as_the_first_delta_after_the_write("rewind")


class AProvisionalPostalAuthorIsNotFrozen(Episode):
    """A peer's message whose postal id the log does not hold yet gets a provisional author, and the whole entry re-authors it
    when the log catches up (the assembly's heal). The document carries the provisional author and no heal state, so an
    entry re-seated on it would serve the provisional author for the rest of the process where a cold parse names the peer
    (review of 2026-09-24, low 1): the writer does not mark such an entry, and it stays whole and heals."""

    def test_an_entry_with_an_unresolved_postal_marker_stays_whole_and_heals(self):
        recs = episode(NOW - 86400)
        i = next(j for j, r in enumerate(recs) if r.get("uuid") == "u30")
        recs[i] = dict(recs[i], message={"role": "user", "content": "please raise the search page size to 50\n<!-- romp-msg-id: %s -->" % MSG})
        recs[i].pop("promptSource", None)
        sent = em.parse_z(recs[i]["timestamp"]) + 1
        self.begin(recs)
        out, _ = self.parse()
        self.assertIn("u30", self.entry()["st"]["postal_miss_rec"], "the fixture's premise: the marker waits on the log")
        self.assertTrue(self.settle(out))
        s0 = self.stats()
        self.append_turn()
        _, m = self.parse()
        self.assertEqual(m, "fold", "no re-seat while an author waits on the log: %s" % self.moved(s0, self.stats()))
        self.postal = [{"t": sent, "ev": "sent", "id": MSG, "from": "api", "from_id": PEER, "to_id": SID,
                        "body": "ASK: raise the search page size"}]
        self.append_turn()
        out, m = self.parse()
        self.assertEqual(m, "fold")
        self.assertEqual(self.moved(s0, self.stats()).get("g:reseat", 0), 0)
        self.assertColdEqual(out)


class TheConvergePassReseatsToo(Episode):
    """The converge pass writes an idle session's document through the same writer as the settle; the entry it wrote from is
    re-seated the same way (review of 2026-09-24, low 3)."""

    def test_a_document_the_converge_pass_writes_reseats_the_entry(self):
        out, _ = self.parse()
        why = []
        self.assertTrue(em.asm_checkpoint_write(self.leaf, SID, tree=out, reason_out=why, who="converge pass"), why)
        self.append_turn()
        s0 = self.stats()
        out, m = self.parse()
        d = self.moved(s0, self.stats())
        self.assertEqual((m, d.get("g:reseat"), d.get("restore:afterDemote")), ("restore", 1, 1), "re-seated on the converge "
                         "pass's document: %s" % d)
        self.assertColdEqual(out)


if __name__ == "__main__":
    unittest.main()
