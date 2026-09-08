#!/usr/bin/env python3
"""Every copy in the kernel's queued group carries an identity (T252c, the user via the manager 2026-09-08): the
chat's pending bubble placed itself by TEXT and ORDINAL because the group carried texts and nothing else, and text
cannot tell a press-time copy from a same-text copy another client queued later, nor pair two landings that arrive
in one frame after a reconnect. Under the authoritative-source rule the identity comes from the store that owns the
queue:

  SDK backend — send() mints the copy's id (the echo key it already minted for the optimistic echo) BEFORE the
  enqueue, so the queued copy, the echo atom and the landed atom share one id; the feed moves the id to a fed
  ledger, and the landed user record is paired with it FIFO per text, at or after the feed time (qid on the chat
  event). A queue restored from the registry after a kernel death carries no ids (legacy: the chat falls back to
  text), and so does a copy the backend itself queued (a death notice, the rename ping).
  Parked sends — a copy parked in the kernel's own FIFO (compaction, a usage-limit hold, a parked drive op) carries
  NO id until it reaches the backend: the park's op is the three-field record the on-disk mirror and a dozen
  readers pin, so the identity is minted where the copy enters the backend's queue. Stated as a gap.
  tmux — the CLI's queue-operation records carry timestamps but no ids: each copy carries its enqueue stamp and NO
  id (an id only the ledger copy wore would make the chat reject the tmux echo as another send's); nothing pairs the
  landed record (the kernel does not see the CLI take it), so the chat reads this route by text.

SYNTHETIC fixtures only: a private synthetic sid, the notes-api demo world, hostname-free.
"""
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)
km = SourceFileLoader("romp_kernel_qid", os.path.join(BIN, "romp-kernel")).load_module()
sb = SourceFileLoader("romp_sdk_backend_qid", os.path.join(BIN, "romp_sdk_backend.py")).load_module()

SID = "5a6b7c8d-1e2f-4a3b-9c4d-5e6f7a8b9c0d"   # private synthetic sid (goal-store fixtures rule)
T0 = 1_800_000_000


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class _World:
    """A real SdkBackend bound as the kernel's backend, owning SID, with a thread-less SdkSession, plus the
    discovery a build_session needs (names/ + projects/<cdir>/<SID>.jsonl under a hermetic state root)."""

    def __init__(self):
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        (root / "sdk").mkdir()
        self.cwd = root / "proj"; self.cwd.mkdir()
        os.environ["CLAUDE_CONFIG_DIR"] = str(root / "claude")
        self.tpath = Path(sb.transcript_path(str(self.cwd), SID))
        self.tpath.parent.mkdir(parents=True, exist_ok=True)
        self.tpath.write_text("")
        self.be = sb.SdkBackend(str(root), "/bin/true", lambda *a, **k: None)
        reg = {"sid": SID, "name": "web", "mode": "acceptEdits", "alive": True, "cwd": str(self.cwd), "lastSid": SID}
        sb.write_reg(self.be.state_dir, SID, reg)
        self.s = sb.SdkSession(self.be, dict(reg))
        # _ensure hands a send to THIS session only while its thread is alive (a dead one is respawned and
        # the spawn dies on the stand-in binary): park a daemon thread in its place for the test's life
        import threading
        self._park = threading.Event()
        self.s.thread = threading.Thread(target=self._park.wait, daemon=True)
        self.s.thread.start()
        self.be.sessions[SID] = self.s
        self.saved_sdk = km._sdk
        km._sdk = lambda: self.be
        proj = root / "projects"
        names = root / "names"; names.mkdir()
        (names / SID).write_text("web\t%s\t#abcdef\n" % str(self.cwd))
        self.saved = (km.jd.NAMES, km.jd.PROJECTS, km.jd.CAPDIR, km.jd.ARCHDIR, km.jd.GOALDIR, km.jd.STATE,
                      km.NAMES, km._tmux_sessions, km._GLOBAL_CLAUDE_MD)
        km.jd.NAMES, km.jd.PROJECTS = names, proj
        km.jd.CAPDIR, km.jd.ARCHDIR, km.jd.GOALDIR = root / "captions", root / "archive", root / "goals"
        km.jd.STATE = root
        km.NAMES = names
        km._GLOBAL_CLAUDE_MD = root / "no-global-claude.md"
        self.now = int(time.time())
        self.tm = {SID: {"state": "working", "since": self.now - 100, "model": "", "effort": "",
                         "context": None, "compactPct": None, "color": None}}
        km._tmux_sessions = lambda: self.tm
        km._chat_fold.clear(); km._parse_cache.clear()
        km._PATH_LINK_CACHE.clear(); km._SPACE_PATH_CACHE.clear()
        km._postal_index_memo[0] = None
        if isinstance(km.jd._discover_cache, dict):
            km.jd._discover_cache.clear()
        # the build_session transcript lives under the kernel's project dir for the cwd
        self.kpath = proj / km.jd._proj_dir(str(self.cwd)).name / (SID + ".jsonl")
        self.kpath.parent.mkdir(parents=True, exist_ok=True)

    def close(self):
        self._park.set()
        (km.jd.NAMES, km.jd.PROJECTS, km.jd.CAPDIR, km.jd.ARCHDIR, km.jd.GOALDIR, km.jd.STATE,
         km.NAMES, km._tmux_sessions, km._GLOBAL_CLAUDE_MD) = self.saved
        km._sdk = self.saved_sdk
        km._chat_fold.clear(); km._parse_cache.clear()
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        import shutil
        shutil.rmtree(self.td.name, ignore_errors=True)   # a backend writer (the echo mirror) may still be finishing

    def write(self, recs, shift=None):
        # discovery keys on the real clock: shift the fixture to "just now"; a landing that must pair with a
        # feed made during the test is written AT the clock (shift=now-T0), since the CLI's enqueue stamp is
        # never earlier than the feed that handed it the text
        shift = (self.now - 600) - T0 if shift is None else shift
        out = []
        for r in recs:
            r = dict(r)
            r["timestamp"] = iso(datetime.strptime(r["timestamp"], "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=timezone.utc).timestamp() + shift)
            out.append(r)
        self.kpath.write_text("".join(json.dumps(r) + "\n" for r in out))
        return shift

    def build(self):
        km._chat_fold.clear(); km._parse_cache.clear()
        return km.build_session(SID, self.now, self.tm)


def uline(t, text, uuid, parent=None):
    return {"type": "user", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent, "promptSource": "sdk",
            "sessionId": SID, "message": {"role": "user", "content": text}}


def aline(t, text, uuid, parent, tools=(), stop="end_turn"):
    content = [{"type": "text", "text": text}] if text else []
    for i, n in enumerate(tools):
        content.append({"type": "tool_use", "id": "tu_%s_%d" % (uuid, i), "name": n, "input": {"command": "true"}})
    return {"type": "assistant", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent, "sessionId": SID,
            "message": {"role": "assistant", "content": content, "stop_reason": stop}}


def trline(t, tool_use_id, uuid, parent):
    return {"type": "user", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent, "sessionId": SID,
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": "ok"}]}}


def attline(t, prompt, uuid, parent):
    return {"type": "attachment", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent, "isSidechain": False,
            "sessionId": SID, "attachment": {"type": "queued_command", "prompt": prompt}}


RUNNING = [uline(T0, "tighten the notes-api search", "u1"), aline(T0 + 10, "Done.", "a1", "u1"),
           uline(T0 + 39, "drop the unused import", "u2", "a1"),
           aline(T0 + 41, "Removing it.", "a2", "u2", tools=("Bash",), stop="tool_use"), trline(T0 + 50, "tu_a2_0", "tr1", "a2")]


class TheSdkQueueCarriesIds(unittest.TestCase):
    def setUp(self):
        self.w = _World()

    def tearDown(self):
        self.w.close()

    def test_send_mints_the_id_before_the_enqueue_and_the_echo_shares_it(self):
        self.assertTrue(self.w.be.send(SID, "first"))
        self.assertTrue(self.w.be.send(SID, "second"))
        meta = self.w.be.pending_queued_meta(SID)
        self.assertEqual(self.w.be.pending_queued(SID), ["first", "second"])
        self.assertEqual([m["md"] for m in meta], ["first", "second"])
        echoes = {a["uuid"] for a in self.w.be.live_atoms(SID) if a.get("_echo_text")}
        self.assertEqual({m["qid"] for m in meta}, echoes, "the copy's id IS its echo's uuid")
        self.assertTrue(all(isinstance(m["qts"], int) and m["qts"] > 1_700_000_000_000 for m in meta), "an epoch-ms enqueue stamp")

    def test_unqueue_keeps_the_ids_aligned(self):
        self.w.be.send(SID, "a"); self.w.be.send(SID, "b"); self.w.be.send(SID, "c")
        before = self.w.be.pending_queued_meta(SID)
        self.assertEqual(self.w.be.unqueue(SID, 1, expect="b"), "b")
        after = self.w.be.pending_queued_meta(SID)
        self.assertEqual([m["md"] for m in after], ["a", "c"])
        self.assertEqual([m["qid"] for m in after], [before[0]["qid"], before[2]["qid"]])

    def test_a_copy_the_backend_queued_itself_and_a_restored_queue_carry_no_id(self):
        self.w.be.send(SID, "typed")
        self.w.s.enqueue_if_empty("ping")           # the queue is not empty: refused, nothing changes
        self.w.s.enqueue("a backend-minted notice")  # no id: the chat falls back to text for it
        meta = self.w.be.pending_queued_meta(SID)
        self.assertEqual([m["md"] for m in meta], ["typed", "a backend-minted notice"])
        self.assertIsNotNone(meta[0]["qid"]); self.assertIsNone(meta[1]["qid"])
        # a queue restored from the registry after a kernel death: texts only
        del self.w.be.sessions[SID]
        self.assertEqual(self.w.be.pending_queued(SID), ["typed", "a backend-minted notice"], "the persisted mirror")
        self.assertIsNone(self.w.be.pending_queued_meta(SID), "…and it carries no ids (legacy)")

    def test_the_feed_moves_the_id_to_the_fed_ledger_and_the_landing_is_paired_fifo_per_text(self):
        self.w.be.send(SID, "ok"); self.w.be.send(SID, "other"); self.w.be.send(SID, "ok")
        ids = [m["qid"] for m in self.w.be.pending_queued_meta(SID)]
        with self.w.s._lock:
            fed = [self.w.s._pop_for_feed_locked() for _ in range(3)]
        self.assertEqual([f[0] for f in fed], ["ok", "other", "ok"])
        self.assertEqual(self.w.be.pending_queued(SID), [])
        now = int(time.time())
        self.assertEqual(self.w.be.qid_for_landing(SID, "uA", "ok", now + 1), ids[0], "the first landing of 'ok' is the first fed 'ok'")
        self.assertEqual(self.w.be.qid_for_landing(SID, "uA", "ok", now + 1), ids[0], "memoised per record")
        self.assertEqual(self.w.be.qid_for_landing(SID, "uB", "ok", now + 2), ids[2], "the second landing is the second fed 'ok'")
        self.assertIsNone(self.w.be.qid_for_landing(SID, "uC", "ok", now + 3), "no third fed copy: nothing to pair")
        self.assertIsNone(self.w.be.qid_for_landing(SID, "uOld", "other", now - 3600), "a record stamped long before the feed is not this copy's landing")
        self.assertEqual(self.w.be.qid_for_landing(SID, "uD", "other", now), ids[1])

    def test_the_kernels_own_echo_never_consumes_a_fed_entry(self):
        # the echo atom is a user atom too, stamped at the send; between the feed and the CLI's record it is the
        # visible copy — asked as a landing it took the fed entry and the real landing then carried no id (review)
        self.w.be.send(SID, "hello there")
        [qid] = [m["qid"] for m in self.w.be.pending_queued_meta(SID)]
        with self.w.s._lock:
            self.w.s._pop_for_feed_locked()
        now = int(time.time())
        self.assertIsNone(self.w.be.qid_for_landing(SID, qid, "hello there", now), "an echo uuid is refused")
        self.assertEqual(self.w.be.qid_for_landing(SID, "uReal", "hello there", now + 1), qid, "…so the record still pairs")

    def test_a_batched_record_pairs_every_block_and_a_dropped_copy_leaves_the_ledger(self):
        self.w.be.send(SID, "ok"); self.w.be.send(SID, "ok"); self.w.be.send(SID, "ok")
        ids = [m["qid"] for m in self.w.be.pending_queued_meta(SID)]
        with self.w.s._lock:
            for _ in range(3): self.w.s._pop_for_feed_locked()
        now = int(time.time())
        self.assertEqual(self.w.be.qids_for_landing(SID, "uJ", ["ok", "ok"], now), [ids[0], ids[1]], "two blocks, two copies, in order")
        self.assertEqual(self.w.be.qids_for_landing(SID, "uJ", ["ok", "ok"], now), [ids[0], ids[1]], "memoised per record")
        self.assertEqual(self.w.be.qid_for_landing(SID, "u3", "ok", now + 1), ids[2], "the third landing is the third copy's, not a stale first")
        # a copy fed and then dropped for good leaves the ledger, so a later same-text landing is not paired with it
        self.w.be.send(SID, "again"); self.w.be.send(SID, "again")
        [d1, d2] = [m["qid"] for m in self.w.be.pending_queued_meta(SID)]
        with self.w.s._lock:
            for _ in range(2): self.w.s._pop_for_feed_locked()
        self.w.be.forget_fed(SID, d1)          # what the never-delivered marking calls
        self.assertEqual(self.w.be.qid_for_landing(SID, "uAg", "again", now + 2), d2)


class TheChatCarriesTheIds(unittest.TestCase):
    def setUp(self):
        self.w = _World()

    def tearDown(self):
        self.w.close()
        km._pending_ops.pop(SID, None)

    def test_the_queued_group_and_the_landed_atom_share_the_copys_id(self):
        live = self.w.now - T0            # this test's records sit at the clock: the landing follows the feed in time
        self.w.write(RUNNING, shift=live)
        fed_text = "and also update the docstring"
        self.assertTrue(self.w.be.send(SID, fed_text))
        self.assertTrue(self.w.be.send(SID, "later one"))
        qid_fed, qid_later = [m["qid"] for m in self.w.be.pending_queued_meta(SID)]
        m = self.w.build()
        q = [e for e in m["events"] if e.get("kind") == "queued"]
        self.assertEqual(len(q), 1, [e.get("kind") for e in m["events"]])
        self.assertEqual([(t["md"], t.get("qid"), isinstance(t.get("qts"), int)) for t in q[0]["texts"]],
                         [(fed_text, qid_fed, True), ("later one", qid_later, True)])
        # the CLI takes the first copy at the boundary: the feed pops it, the splice record lands it
        with self.w.s._lock:
            self.w.s._pop_for_feed_locked()
        recs = RUNNING + [attline(T0 + 55, fed_text, "att1", "tr1"), aline(T0 + 75, "Updated.", "a3", "att1", tools=("Bash",), stop="tool_use")]
        self.w.write(recs, shift=live)
        m = self.w.build()
        landed = [e for e in m["events"] if e.get("kind") == "user" and e.get("md") == fed_text]
        self.assertEqual(len(landed), 1)
        self.assertTrue(landed[0].get("absorbed"))
        self.assertEqual(landed[0].get("qid"), qid_fed, "the landed atom carries the copy's id")
        q = [e for e in m["events"] if e.get("kind") == "queued"]
        self.assertEqual([t.get("qid") for t in q[0]["texts"]], [qid_later], "the queue now holds the other copy only")

    def test_an_intermediate_build_between_the_feed_and_the_landing_keeps_the_pairing(self):
        live = self.w.now - T0
        self.w.write(RUNNING, shift=live)
        fed_text = "and also update the docstring"
        self.w.be.send(SID, fed_text)
        [qid] = [m["qid"] for m in self.w.be.pending_queued_meta(SID)]
        with self.w.s._lock:
            self.w.s._pop_for_feed_locked()
        mid = self.w.build()                    # the echo is the visible copy now: a build here must not pair it
        echoes = [e for e in mid["events"] if e.get("kind") == "user" and str(e.get("uuid", "")).startswith("echo:")]
        self.assertEqual([e.get("qid") for e in echoes], [None] * len(echoes), "an echo event carries no landing id (its uuid IS the copy's id)")
        self.w.write(RUNNING + [attline(T0 + 55, fed_text, "att1", "tr1"), aline(T0 + 75, "Updated.", "a3", "att1", tools=("Bash",), stop="tool_use")], shift=live)
        m = self.w.build()
        landed = [e for e in m["events"] if e.get("kind") == "user" and e.get("md") == fed_text and not str(e.get("uuid", "")).startswith("echo:")]
        self.assertEqual([e.get("qid") for e in landed], [qid])

    def test_a_two_block_record_carries_both_copies_ids(self):
        live = self.w.now - T0
        self.w.write(RUNNING, shift=live)
        self.w.be.send(SID, "first of two"); self.w.be.send(SID, "second of two")
        [q1, q2] = [m["qid"] for m in self.w.be.pending_queued_meta(SID)]
        with self.w.s._lock:
            for _ in range(2): self.w.s._pop_for_feed_locked()
        batched = {"type": "user", "timestamp": iso(T0 + 90), "uuid": "u9", "parentUuid": "tr1", "promptSource": "sdk", "sessionId": SID,
                   "message": {"role": "user", "content": [{"type": "text", "text": "first of two"}, {"type": "text", "text": "second of two"}]}}
        self.w.write(RUNNING + [batched], shift=live)
        m = self.w.build()
        rec = [e for e in m["events"] if e.get("kind") == "user" and e.get("uuid") == "u9"]
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0].get("blocks"), ["first of two", "second of two"])
        self.assertEqual(rec[0].get("qids"), [q1, q2], "one id per block, in block order")
        self.assertIsNone(rec[0].get("qid"), "no single id claims the whole record")

    def test_ids_ride_only_when_each_one_sits_beside_its_own_text(self):
        # the queue can move between the two reads a build makes (a pop and an append keep the length): an id set
        # that does not match the texts one for one is not shipped, so no copy wears another copy's id
        self.w.write(RUNNING)
        self.w.be.send(SID, "A"); self.w.be.send(SID, "B")
        real = self.w.be.pending_queued_meta
        self.w.be.pending_queued_meta = lambda sid: [{"md": "B", "qid": "echo:b", "qts": 1}, {"md": "C", "qid": "echo:c", "qts": 2}]
        try:
            m = self.w.build()
        finally:
            self.w.be.pending_queued_meta = real
        q = [e for e in m["events"] if e.get("kind") == "queued"]
        self.assertEqual([(x["md"], x.get("qid")) for x in q[0]["texts"]], [("A", None), ("B", None)])

    def test_a_parked_copy_carries_no_id_until_it_reaches_the_backend(self):
        # the park's op is the three-field record the on-disk mirror and its readers pin: no identity rides it; the
        # copy is identified where it enters the backend's queue (send()), and the chat reads a parked copy by text
        self.w.write(RUNNING)
        km._park_op(SID, ("send", "parked words", None))
        m = self.w.build()
        q = [e for e in m["events"] if e.get("kind") == "queued"]
        self.assertEqual([(x["md"], x.get("qid"), x.get("qts")) for x in q[0]["texts"]], [("parked words", None, None)])
        km._deliver_send_batch(self.w.be, SID, [km._pending_ops[SID][0]])
        meta = self.w.be.pending_queued_meta(SID)
        self.assertEqual(meta[0]["md"], "parked words")
        self.assertTrue(meta[0]["qid"] and meta[0]["qid"].startswith("echo:"), "…and gains one the moment it enters the backend's queue")


class TheTmuxQueueCarriesStamps(unittest.TestCase):
    def test_each_copy_carries_its_enqueue_stamp_and_no_id_since_nothing_on_this_route_could_share_one(self):
        td = tempfile.TemporaryDirectory()
        p = Path(td.name) / "t.jsonl"
        recs = [{"type": "queue-operation", "operation": "enqueue", "content": "one", "timestamp": iso(T0 + 5)},
                {"type": "queue-operation", "operation": "enqueue", "content": "two", "timestamp": iso(T0 + 9)},
                {"type": "queue-operation", "operation": "dequeue", "timestamp": iso(T0 + 12)}]
        p.write_text("".join(json.dumps(r) + "\n" for r in recs))
        km._queued_parse_cache.clear()
        self.assertEqual(km._pending_queued(str(p)), ["two"])
        meta = km._pending_queued_meta(str(p))
        self.assertEqual([m["md"] for m in meta], ["two"])
        self.assertEqual(meta[0]["qts"], (T0 + 9) * 1000)
        # no id: the tmux echo is minted before the CLI writes its enqueue record and the landing carries nothing,
        # so an id only the ledger copy wore would make the chat reject the echo as another send's (review)
        self.assertIsNone(meta[0]["qid"])
        td.cleanup()


if __name__ == "__main__":
    unittest.main()
