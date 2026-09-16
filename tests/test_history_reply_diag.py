#!/usr/bin/env python3
"""The history-reply diagnostic row (2026-09-15): the kernel files one client-diag row per history reply
(loadTurns/loadOlder/loadAround/loadNewer, proto-2 or the legacy loadOlder arm) it serves to ANY client, so a
scroll-back that stalls can be read from the SERVING kernel: did the ask arrive, over what span, was it answered
(events, bytes) or refused, was the client a local page or a relay, and did the reply actually leave over the wire.
This drives the real WS dispatch (_dispatch_ws) for a page client and a relay client, whose kind is what the real
_dial_kind assigns from a dial's headers and query (not a hand-set literal), and reads the rows. No behaviour
change: the reply the client is sent is unchanged; only a diagnostic row is added.

Synthetic only: a placeholder uuid, hostname TESTHOST. Hermetic: the state root is rebound to a temp dir, so the
client-diag.jsonl written is the test's own."""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

from romp_load import load_source

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
km = load_source("romp_kernel_histdiag", os.path.join(BIN, "romp-kernel"))
jd = km.jd

SID = "11111111-2222-4333-8444-000000000905"
HOST = "TESTHOST"

# The dial shapes _dial_kind reads (headers, parse_qs query: name -> [values]); the kind is derived, never hand-set.
PAGE_DIAL = ({"Origin": "https://" + HOST}, {})   # a browser upgrade carries an Origin -> page
RELAY_DIAL = ({}, {"relay": ["1"]})               # the federation splice writes relay=1 -> relay


class HistoryReplyDiag(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.saved_state = jd.STATE
        jd._rebind_state(self.td / "state")
        for d in ("names", "sdk", "states", "checkpoints"):
            (jd.STATE / d).mkdir(parents=True, exist_ok=True)
        # isolate the history branches: _drive returns False for these msgs (not a drive op) anyway; stub it so the
        # test never depends on drive-op wiring, and stub the reply/build so the row's fields are deterministic.
        self._saved_reply, self._saved_drive, self._saved_build = km._chat_history_reply, km._drive, km.build_session
        km._drive = lambda *a, **k: False

    def tearDown(self):
        km._chat_history_reply, km._drive, km.build_session = self._saved_reply, self._saved_drive, self._saved_build
        jd._rebind_state(self.saved_state)

    def _rows(self):
        fp = jd.STATE / "client-diag.jsonl"
        return [json.loads(l) for l in fp.read_text().splitlines() if l.strip()] if fp.exists() else []

    def _dispatch(self, client, msg):
        # _dispatch_ws's history branches use no `self`; a bare stub is enough to drive the real dispatch
        km.Handler._dispatch_ws(types.SimpleNamespace(), msg, client)

    def _client(self, dial, cid, **extra):
        """A client whose kind is what the real _dial_kind assigns from the dial's (headers, query), not a literal
        the test writes: this pins the row's `kind` to the dial classifier's own verdict."""
        headers, q = dial
        kind = km._dial_kind(headers, q)
        sent = []
        c = {"app": "chat", "kind": kind, "cid": cid, "wid": "w-" + kind, "proto": 2, "echat": {},
             "send": (lambda s: sent.append(s))}
        c.update(extra)
        return c, sent

    def test_a_served_reply_files_a_row_for_a_page_and_a_relay_client(self):
        km._chat_history_reply = lambda sid, msg, now, base=None: {
            "type": "chatTurns", "id": sid, "span": [msg.get("lo"), msg.get("hi")],
            "events": [{"k": i} for i in range(33)], "head": msg.get("lo") == 0}
        page, psent = self._client(PAGE_DIAL, "cidpage")
        relay, rsent = self._client(RELAY_DIAL, "cidrelay")
        self.assertEqual((page["kind"], relay["kind"]), ("page", "relay"), "the dial classifier assigned the kinds")
        self._dispatch(page, {"type": "loadTurns", "id": SID, "lo": 0, "hi": 16})
        self._dispatch(relay, {"type": "loadTurns", "id": SID, "lo": 0, "hi": 16})
        self.assertTrue(psent and rsent, "both clients were still sent the reply (no behaviour change)")
        rows = [r for r in self._rows() if r.get("what") == "historyReply"]
        self.assertEqual(len(rows), 2, "one diag row per history reply: %r" % rows)
        byk = {r["data"]["kind"]: r["data"] for r in rows}
        self.assertEqual(set(byk), {"page", "relay"}, "a row for each client kind: %r" % rows)
        for kind, cid in (("page", "cidpage"), ("relay", "cidrelay")):
            d = byk[kind]
            self.assertEqual(d["cid"], cid, "%s row names its cid" % kind)
            self.assertEqual(d["sid"], SID)
            self.assertEqual(d["type"], "loadTurns")
            self.assertEqual(d["span"], [0, 16], "the reply's turn span")
            self.assertEqual(d["events"], 33, "the events served")
            self.assertGreater(d["bytes"], 0, "the wire bytes")
            self.assertIs(d["head"], True, "the head page")
            self.assertIs(d["refused"], False)
            self.assertIs(d["sent"], True, "the reply left over the wire")
        self.assertNotIn("host", byk["relay"], "the dead host field is gone from the row")

    def test_a_fault_reply_files_a_refused_row_with_the_reason(self):
        km._chat_history_reply = lambda sid, msg, now, base=None: None   # no build -> the dispatch answers a fault
        relay, sent = self._client(RELAY_DIAL, "cidrelay")
        self._dispatch(relay, {"type": "loadTurns", "id": SID, "lo": 0, "hi": 16})
        self.assertTrue(sent, "the fault reply is still sent")
        rows = [r for r in self._rows() if r.get("what") == "historyReply"]
        self.assertEqual(len(rows), 1, "the fault reply is one row too: %r" % rows)
        d = rows[0]["data"]
        self.assertIs(d["refused"], True, "a fault reads as refused: %r" % d)
        self.assertTrue(d.get("reason"), "the row carries the fault reason: %r" % d)
        self.assertEqual(d["events"], 0, "a fault served no events")
        self.assertIs(d["sent"], True, "the fault still left over the wire")

    def test_the_legacy_loadOlder_arm_files_a_row(self):
        # A loadOlder with an INTEGER `before` misses the proto-2 gate (not isinstance(before, int)) and falls to the
        # legacy scroll-back arm, which builds a chatHead from the session's events. Stub build_session so it answers.
        km.build_session = lambda sid, now: {"events": [{"i": i} for i in range(50)]}
        page, psent = self._client(PAGE_DIAL, "cidlegacy")
        self._dispatch(page, {"type": "loadOlder", "id": SID, "before": 40})
        self.assertTrue(psent, "the legacy arm still sends the chatHead (no behaviour change)")
        rows = [r for r in self._rows() if r.get("what") == "historyReply"]
        self.assertEqual(len(rows), 1, "the legacy arm files one row too: %r" % rows)
        d = rows[0]["data"]
        self.assertEqual(d["type"], "loadOlder")
        self.assertEqual(d["kind"], "page")
        self.assertGreater(d["events"], 0, "the older events it shipped")
        self.assertIs(d["refused"], False)
        self.assertIs(d["sent"], True)

    def test_a_send_that_raises_files_a_row_with_sent_false(self):
        # An ask that arrived and whose reply was built but FAILED to leave over the wire is told from one that never
        # arrived: the row is still filed, with sent=False, on the send-exception path.
        km._chat_history_reply = lambda sid, msg, now, base=None: {
            "type": "chatTurns", "id": sid, "span": [msg.get("lo"), msg.get("hi")], "events": [], "head": True}

        def _boom(_s):
            raise RuntimeError("wire closed")

        relay, _ = self._client(RELAY_DIAL, "cidgone", send=_boom)
        self._dispatch(relay, {"type": "loadTurns", "id": SID, "lo": 0, "hi": 16})   # the send raises; the dispatch swallows it
        rows = [r for r in self._rows() if r.get("what") == "historyReply"]
        self.assertEqual(len(rows), 1, "a send that raised still files a row: %r" % rows)
        d = rows[0]["data"]
        self.assertIs(d["sent"], False, "the reply did not leave over the wire: %r" % d)
        self.assertEqual(d["type"], "loadTurns")


if __name__ == "__main__":
    unittest.main()
