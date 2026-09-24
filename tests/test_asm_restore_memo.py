#!/usr/bin/env python3
"""The restore road serves the assembly document's decode from the per-process memo (the reparse investigation of
2026-09-24). A restore after a descent, rewrite or nonleaf demotion read, gunzipped and JSON-decoded the leaf's whole
document again although the document had not changed: `_asm_restore_inner` loaded it with the memo off, and then wrote
None into the decoded rows once the lazy index had copied them, so a memoized decode could not have served a second
restore anyway (the load refuses a document without rows, and the next parse is the whole parse). On synthetic
transcripts in a lab kernel the load was 61 percent of the restore time at 120 MB, about 192 ms per restore.

Pinned here on a synthetic compacting episode whose document stands: two rewinds in the tail each demote the entry at
the descent gate and restore from the document, reading none of it (counted `restore:asmDocMemo`, never under the
seeded walk's key), each restore building the lazy index over the same turns, the memoized decode equal to a fresh decode
of its file in every field (the review of 2026-09-24: a pin on the rows alone let a write into another field of the
shared document through), and the tree equal to a cold whole parse; a memoized decode still gets every file check the
load runs (a leaf rewritten under the cut refuses it, the document and its memo entry removed); and every refusal the
restore makes after the load (its tree identity, its coverage, an exception in the restore, and a row the index cannot
decode at its first build) drops the memo entry with the document (the same review: a note that dropped the entry on
the identity refusal alone passed every earlier pin). Synthetic only: invented text, a private placeholder session id,
the notes-api demo world."""
import gzip
import json
import os
import random
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from romp_load import load_source

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
# Hermetic state BEFORE the loads — they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
em = load_source("romp_event_model", os.path.join(BIN, "romp-event-model"))

SID = "5a5a5a5a-2222-4333-8444-000000000924"   # this module's own placeholder session id
NOW = 1781100000
WORDS = ("fixture", "suite", "backoff", "jitter", "cap", "retry", "review", "branch", "merge", "green", "README", "wire")


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def prompt(t, uuid, parent, text):
    return {"type": "user", "uuid": uuid, "parentUuid": parent, "timestamp": iso(t), "promptSource": "typed", "cwd": "/w/notes-api",
            "message": {"role": "user", "content": text}}


def reply(t, uuid, parent, text):
    return {"type": "assistant", "uuid": uuid, "parentUuid": parent, "timestamp": iso(t), "cwd": "/w/notes-api",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}}


def episode(t0, turns=240, compact_every=80):
    """A compacting episode in the CLI's shape: typed prompts and end_turn replies chained record to record, and every
    `compact_every` turns a compaction (the boundary anchored on the last record, its summary child)."""
    rnd = random.Random(924)
    recs, parent, t = [], None, t0
    for k in range(turns):
        if k and k % compact_every == 0:
            b, s = "b%d" % k, "s%d" % k
            recs.append({"type": "system", "subtype": "compact_boundary", "uuid": b, "parentUuid": None, "logicalParentUuid": parent,
                         "timestamp": iso(t), "compactMetadata": {"trigger": "auto", "preTokens": 160000, "postTokens": 9000}})
            recs.append({"type": "user", "uuid": s, "parentUuid": b, "timestamp": iso(t + 1), "isCompactSummary": True,
                         "message": {"role": "user", "content": "summary so far: " + " ".join(rnd.choice(WORDS) for _ in range(60))}})
            parent = s
            t += 2
        u, a = "u%d" % k, "a%d" % k
        recs.append(prompt(t, u, parent, " ".join(rnd.choice(WORDS) for _ in range(20)) + " %d" % k))
        recs.append(reply(t + 20, a, u, " ".join(rnd.choice(WORDS) for _ in range(80))))
        parent = a
        t += 60
    return recs


class _Documented(unittest.TestCase):
    """An episode written to a leaf of its own, parsed whole, its document written from the whole entry with the tree
    (so the document carries its turns section and the restore builds the lazy index), then a restart's in-memory side. A
    membership check on the memo reads its keys (list(...)): a failure then names paths, never the whole decoded documents
    the memo's values are."""

    def setUp(self):
        self.td = Path(tempfile.mkdtemp()).resolve()
        em.set_checkpoint_dir(lambda: self.td / "checkpoints")
        self.leaf = str(self.td / (SID + ".jsonl"))
        self.recs = episode(NOW - 86400)
        with open(self.leaf, "w") as f:
            f.write("".join(json.dumps(r) + "\n" for r in self.recs))
        self.restart()
        tree, mode = self.parse()
        self.assertEqual(mode, "full")
        self.assertTrue(em.asm_checkpoint_write(self.leaf, SID, tree=tree), em.asm_checkpoint_stats())
        self.cp = str(em._asm_ckpt_file(self.leaf))
        self.assertTrue(os.path.exists(self.cp))
        self.restart()

    def tearDown(self):
        em.set_checkpoint_dir(None)
        shutil.rmtree(self.td, ignore_errors=True)

    def restart(self):
        """A kernel restart's in-memory side: every reader entry, assembly entry, hydrated body, memoized document and read
        count gone."""
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

    def parse(self):
        modes = []
        tree = em.parse_session(self.leaf, rompuuid=SID, name="web", dir="/w/notes-api", candidate_files=[self.leaf],
                                states=None, postal_log=[], now=NOW, asm_mode_out=modes)
        return tree, (modes[-1] if modes else None)

    def append(self, recs):
        self.recs += recs
        with open(self.leaf, "a") as f:
            f.write("".join(json.dumps(r) + "\n" for r in recs))

    def last_t(self):
        return max(em.parse_z(r["timestamp"]) for r in self.recs if r.get("timestamp"))

    def doc_read(self):
        with em._READ_BYTES_LOCK:
            return em._READ_BYTES.get(self.cp, 0)

    def read_doc(self):
        """The document as its file holds it, decoded fresh (never through the memo)."""
        return json.loads(gzip.decompress(Path(self.cp).read_bytes()).decode("utf-8"))

    def write_doc(self, doc):
        Path(self.cp).write_bytes(gzip.compress(json.dumps(doc).encode("utf-8")))

    @staticmethod
    def restored_turns():
        return em.asm_index_stats()["restoredTurns"]

    @staticmethod
    def counters():
        st = em.asm_checkpoint_stats()
        return dict(st["parse"]), dict(st["fallbacks"])

    @staticmethod
    def moved(a, b):
        return {k: b.get(k, 0) - a.get(k, 0) for k in set(a) | set(b) if b.get(k, 0) != a.get(k, 0)}

    @staticmethod
    def plain(tree):
        """A tree as JSON compares it, its bodies hydrated and a restored tree's pre-cut turns built (em.plain_tree); the lazy
        scalars and the cut, a restored tree's own facts, left out."""
        em.hydrate(tree, SID)
        t = json.loads(json.dumps(em.plain_tree(tree), default=lambda o: "<unserializable>"))
        t.pop("cutTurn", None)
        for turn in t["turns"]:
            for a in turn["atoms"]:
                a.pop("lazy", None)
        return t

    def cold(self):
        """The reference: the same bytes parsed whole from zero with no document (a restart first, the directory off)."""
        self.restart()
        em.set_checkpoint_dir(None)
        try:
            tree, mode = self.parse()
        finally:
            em.set_checkpoint_dir(lambda: self.td / "checkpoints")
        self.assertEqual(mode, "full")
        return self.plain(tree)

    def assertSameConversation(self, got, cold):
        """The two trees' turn counts first, then the first turn that differs, then everything outside the turns: a short
        message on a mismatch where the whole trees would print hundreds of turns."""
        self.assertEqual(len(got["turns"]), len(cold["turns"]), "turn count against the cold parse")
        first = next((i for i, (a, b) in enumerate(zip(got["turns"], cold["turns"])) if a != b), None)
        self.assertIsNone(first, "turn %r differs from the cold parse's: %r against %r"
                          % (first, None if first is None else [a.get("uuid") for a in got["turns"][first]["atoms"]],
                             None if first is None else [a.get("uuid") for a in cold["turns"][first]["atoms"]]))
        self.assertEqual({k: v for k, v in got.items() if k != "turns"}, {k: v for k, v in cold.items() if k != "turns"})


class RestoreServesTheDocumentFromMemory(_Documented):
    def test_each_restore_after_a_rewind_in_the_tail_reads_none_of_the_unchanged_document(self):
        """Two rewinds onto a tail record: each new leaf does not chain back to the old one through the delta, so the entry
        demotes at the descent gate and falls to the restore road over the same document. The boot's restore decodes it; the
        two after the rewinds must not read a byte of it."""
        size = os.path.getsize(self.cp)
        p0, _ = self.counters()
        roads, reads, restored = [], [], []
        r0, n0 = self.doc_read(), self.restored_turns()
        tree, mode = self.parse()                                # the boot: the entry restored from the document
        roads.append(mode); reads.append(self.doc_read() - r0); restored.append(self.restored_turns() - n0)
        tip = [r["uuid"] for r in self.recs if r.get("type") == "assistant"][-2]   # the settled turn past the cut: a tail record
        for k in (1, 2):
            t = self.last_t() + 60
            self.append([prompt(t, "rw%d" % k, tip, "back up: redo the notes-api search index, take %d" % k),
                         reply(t + 20, "rwa%d" % k, "rw%d" % k, "rebuilt the index, take %d" % k)])
            r0, n0 = self.doc_read(), self.restored_turns()
            tree, mode = self.parse()
            roads.append(mode); reads.append(self.doc_read() - r0); restored.append(self.restored_turns() - n0)
        p1, _ = self.counters()
        d = self.moved(p0, p1)
        self.assertEqual(roads, ["restore"] * 3, "the boot and both rewinds take the restore road: %s (counters moved %s)" % (roads, d))
        self.assertEqual((d.get("g:descent", 0), d.get("restore:afterDemote", 0)), (2, 2),
                         "each rewind demoted the entry at the descent gate and restored: %s" % d)
        self.assertEqual(reads[0], size, "the boot's restore decodes the %d byte document once: %s" % (size, reads))
        self.assertEqual(reads[1:], [0, 0], "a restore over the unchanged document reads none of it: document bytes read per "
                         "parse %s of a %d byte document (the base decoded it at every restore)" % (reads, size))
        self.assertEqual((d.get("restore:asmDocMemo", 0), d.get("seeded:asmDocMemo", 0)), (2, 0),
                         "both decodes served from the memo, counted under the restore's own key: %s" % d)
        self.assertTrue(restored[0] > 0 and restored == [restored[0]] * 3,
                        "each restore builds the lazy index over the document's turns section, the same %d turns each time (a "
                        "restore that fell to the atoms-only form restores none): turns restored per parse %s" % (restored[0], restored))
        with em._ASM_CKPT_LOCK:
            ent = em._ASM_DOC_MEMO.get(self.cp)
        self.assertIsNotNone(ent, "the verified document is memoized")
        held, fresh = json.loads(json.dumps(ent[1], default=repr)), self.read_doc()
        self.assertEqual(sorted(k for k in set(held) | set(fresh) if k not in held or k not in fresh or held[k] != fresh[k]), [],
                         "the memoized decode equals a fresh decode of its file in every field (these are the fields that differ): "
                         "the restore drops the rows from its own copy and writes into nothing the memo serves the next reader")
        got = self.plain(tree)
        self.assertSameConversation(got, self.cold())


class AMemoizedDocumentIsStillVerified(_Documented):
    def test_a_leaf_rewritten_under_the_cut_refuses_the_memoized_document(self):
        """The memo serves the decode alone: the load's checks run on a memoized document as on a fresh one. A byte of a
        pre-cut prompt rewritten in place (the size the same, the mtime later) demotes the restored entry at the rewrite
        gate; the restore that follows is served the decode from the memo and its file check refuses it as `rewrite`: the
        note removes the document and drops the memo entry, and the parse is the whole parse over the rewritten bytes."""
        _, mode = self.parse()
        self.assertEqual(mode, "restore")
        with em._ASM_CKPT_LOCK:
            self.assertIn(self.cp, list(em._ASM_DOC_MEMO), "the boot's restore memoized its document")
        st0 = os.stat(self.leaf)
        data = Path(self.leaf).read_bytes()
        at = data.index(b'"content": "') + len(b'"content": "')    # the first prompt's text, well before the cut
        flipped = b"X" if data[at:at + 1] != b"X" else b"Y"
        Path(self.leaf).write_bytes(data[:at] + flipped + data[at + 1:])
        os.utime(self.leaf, ns=(st0.st_atime_ns, st0.st_mtime_ns + 2_000_000_000))
        self.assertEqual(os.path.getsize(self.leaf), st0.st_size)
        p0, f0 = self.counters()
        tree, mode = self.parse()
        p1, f1 = self.counters()
        d, fd = self.moved(p0, p1), self.moved(f0, f1)
        self.assertEqual(d.get("restore:asmDocMemo", 0), 1, "the restore after the rewrite was served the decode from memory: %s" % d)
        self.assertEqual(fd, {"rewrite": 1}, "and the load's file check refused it, as it refuses a fresh decode: %s" % fd)
        self.assertEqual(mode, "full", "the whole parse over the rewritten bytes: %s" % d)
        self.assertFalse(os.path.exists(self.cp), "the note removed the document")
        with em._ASM_CKPT_LOCK:
            self.assertNotIn(self.cp, list(em._ASM_DOC_MEMO), "and dropped its memoized decode")
            self.assertEqual(em._ASM_DOC_MEMO_BYTES[0], 0)
        got = self.plain(tree)
        self.assertSameConversation(got, self.cold())


class ARestoreRefusalDropsTheMemo(_Documented):
    """A document that passes the load and fails a proof the restore makes after it is noted: the note removes the document,
    and with it the decode the load memoized, which no reader could use again. One test per refusal the restore itself
    notes, since a drop placed in one branch alone (the identity refusal) passed an earlier version of this class."""

    def _refused_after_the_load(self, spoil, reason):
        doc = self.read_doc()
        spoil(doc)
        self.write_doc(doc)
        _, f0 = self.counters()
        tree, mode = self.parse()
        _, f1 = self.counters()
        self.assertEqual(self.moved(f0, f1), {reason: 1}, "the restore's own refusal, after the load memoized the document")
        self.assertEqual(mode, "full")
        self.assertFalse(os.path.exists(self.cp), "the note removed the document")
        with em._ASM_CKPT_LOCK:
            self.assertNotIn(self.cp, list(em._ASM_DOC_MEMO), "no memoized decode outlives the document the note removed")
            self.assertEqual(em._ASM_DOC_MEMO_BYTES[0], 0)
        got = self.plain(tree)
        self.assertSameConversation(got, self.cold())

    def test_a_turns_section_whose_identity_does_not_match_leaves_no_memo_entry(self):
        """The turns section's identity."""
        self._refused_after_the_load(lambda doc: doc.update(treeIdentity="0" * 40), "identity")

    def test_a_turns_section_that_does_not_cover_the_rows_leaves_no_memo_entry(self):
        """The section's coverage: one row left out of the last turn, the section's identity recomputed over what is left so
        the identity proof passes and the coverage proof is the one that refuses."""
        def spoil(doc):
            doc["turns"][-1]["atoms"] = doc["turns"][-1]["atoms"][:-1]
            doc["treeIdentity"] = em._tree_identity_of_doc(doc["turns"], doc.get("identity"))
        self._refused_after_the_load(spoil, "coverage")

    def test_a_document_the_restore_raises_on_leaves_no_memo_entry(self):
        """A document the restore's code cannot use (an emit carry with none of its fields) is the counted `restore` fallback."""
        self._refused_after_the_load(lambda doc: doc.update(carry={}), "restore")

    def test_a_row_the_index_cannot_decode_drops_the_memo_entry_at_its_first_build(self):
        """A row shaped as an object whose inside is not JSON passes the load's shape check, so the restore serves and the load
        memoizes the document; the row's first build notes it `rows`, and the note drops the memo entry with the document."""
        doc = self.read_doc()
        k = len(doc["atoms"]) // 2
        self.assertGreater(k, 0, "a row past the first, which the load decodes itself")
        doc["atoms"][k] = "{not json inside}"
        self.write_doc(doc)
        _, f0 = self.counters()
        tree, mode = self.parse()
        self.assertEqual(mode, "restore", "the shape check passes: the restore serves")
        with em._ASM_CKPT_LOCK:
            self.assertIn(self.cp, list(em._ASM_DOC_MEMO), "and the load memoized the document")
        la = next(t["atoms"] for t in tree["turns"] if isinstance(t.get("atoms"), em.LazyAtoms) and k in t["atoms"]._rows)
        with self.assertRaises(em.LazyIndexError):
            la[la._rows.index(k)]
        _, f1 = self.counters()
        self.assertEqual(self.moved(f0, f1), {"rows": 1}, "the build's belt noted the document")
        self.assertFalse(os.path.exists(self.cp), "the note removed the document")
        with em._ASM_CKPT_LOCK:
            self.assertNotIn(self.cp, list(em._ASM_DOC_MEMO), "no memoized decode outlives the document the note removed")
            self.assertEqual(em._ASM_DOC_MEMO_BYTES[0], 0)
        tree, mode = self.parse()
        self.assertEqual(mode, "full", "the entry was dropped: the next parse is whole")
        self.assertSameConversation(self.plain(tree), self.cold())


if __name__ == "__main__":
    unittest.main()
