#!/usr/bin/env python3
"""A peer's reply lifts the awaiting stamp again — for handoffs, not just questions (2026-08-18).

The 2026-08-15 change that stopped DELEGATES from making chip edges (ownership transferred is not a
dependency) also emptied last_ask of them — which silently removed _peer_answered_at's release, so a
delegated peer's reply no longer superseded a judge kind=peer stamp: the audit found a cross-host
handoff answered in 23 minutes still wearing Awaiting six hours later, with the 6h wake as the only
exit. The release reads every reply-REQUIRING outbound (question or delegate: last_await, 2026-09-08 —
it walked last_any first, until a coordinate the asker sent after the answer re-opened the pair),
restoring the designed exact ending event for questions and handoffs alike, while the chip edge stays
question-only exactly as intended.

Also pinned: an UNRESOLVABLE cross-host ask (the peer never sent a row, so the alias map cannot know
its sid) keys on the NAMED recipient — two asks to different sessions on one detached host used to
collapse onto the single (from, relay) pair, the later silently overwriting the earlier (a
29.6h-invisible ask found eaten this way). Synthetic rows only (placeholder ids, TESTHOST).

Since 2026-09-08 (mail keyed by the recipient's stable id): a relay row's own `to_sid` keys it exactly,
and the name→sid alias older rows fall back to is anchored at each row's SEND time (jd._alias_at), so a
name a NEW session reused no longer re-keys every OLD message to the new sid."""
import json
import os
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
km = SourceFileLoader("romp_kernel_awaitrel", os.path.join(BIN, "romp-kernel")).load_module()

A = "11111111-2222-3333-4444-000000000001"
B = "11111111-2222-3333-4444-000000000002"


class _AwaitBase(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self._saved = km.jd.MESSAGES
        km.jd.MESSAGES = Path(self.td.name) / "messages.jsonl"
        km._POSTAL_WAIT_CACHE[:] = [None, ({}, {}, {})]

    def tearDown(self):
        km.jd.MESSAGES = self._saved
        km._POSTAL_WAIT_CACHE[:] = [None, ({}, {}, {})]
        self.td.cleanup()

    def _write(self, rows):
        km.jd.MESSAGES.parent.mkdir(parents=True, exist_ok=True)
        km.jd.MESSAGES.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        km._POSTAL_WAIT_CACHE[:] = [None, ({}, {}, {})]


class AwaitRelease(_AwaitBase):
    def test_a_delegated_peers_reply_supersedes_the_stamp(self):
        self._write([
            {"from_id": A, "to_id": B, "t": 100, "kind": "delegate", "body": "own this now"},
            {"from_id": B, "to_id": A, "t": 200, "kind": "coordinate", "body": "done, shipped"},
        ])
        last_any, last_ask, last_await = km._postal_wait_maps()
        self.assertNotIn((A, B), last_ask, "a DELEGATE still makes no chip edge — ownership transferred")
        self.assertEqual(last_await.get((A, B)), 100, "…but it IS a reply-requiring send")
        self.assertEqual(km._peer_answered_at(A), 200, "…and the reply IS the stamp's ending event again")

    def test_a_reply_older_than_the_newest_reply_requiring_send_does_not_supersede(self):
        # the newest send that AWAITS something is unanswered → nothing supersedes (the rule this
        # test always pinned, now stated on the send that carries the wait)
        self._write([
            {"from_id": A, "to_id": B, "t": 100, "kind": "delegate", "body": "own this"},
            {"from_id": B, "to_id": A, "t": 150, "kind": "coordinate", "body": "ack"},
            {"from_id": A, "to_id": B, "t": 300, "kind": "question", "body": "and the port?"},
        ])
        self.assertEqual(km._peer_answered_at(A), 0, "the newest reply-requiring send is unanswered")

    def test_a_coordinate_after_the_answer_does_not_reopen_the_wait(self):
        # PIN MOVED 2026-09-08 (this fixture asserted 0 before): A's "one more thing" is a COORDINATE
        # — by declaration it requests nothing — so the handoff answered at 150 stays answered. Read
        # off last_any, the coordinate was "a newer outbound awaiting a reply" and the stamp the
        # answer had ended stood until the 6h backstop. main: 0.
        self._write([
            {"from_id": A, "to_id": B, "t": 100, "kind": "delegate", "body": "own this"},
            {"from_id": B, "to_id": A, "t": 150, "kind": "coordinate", "body": "ack"},
            {"from_id": A, "to_id": B, "t": 300, "kind": "coordinate", "body": "one more thing"},
        ])
        self.assertEqual(km._peer_answered_at(A), 150, "the delegate's answer is the clock; a heads-up is not a wait")

    def test_question_release_unchanged(self):
        self._write([
            {"from_id": A, "to_id": B, "t": 100, "kind": "question", "body": "which port?"},
            {"from_id": B, "to_id": A, "t": 180, "kind": "coordinate", "body": "8080"},
        ])
        last_any, last_ask, _aw = km._postal_wait_maps()
        self.assertIn((A, B), last_ask, "a QUESTION still makes the chip edge")
        self.assertEqual(km._peer_answered_at(A), 180)

    def test_unresolvable_relay_asks_key_per_named_recipient(self):
        self._write([
            {"from_id": A, "to_id": "peer:TESTHOST", "toName": "TESTHOST:web", "t": 100,
             "kind": "question", "body": "status of the web thing?"},
            {"from_id": A, "to_id": "peer:TESTHOST", "toName": "TESTHOST:api", "t": 120,
             "kind": "question", "body": "status of the api thing?"},
        ])
        _any, last_ask, _aw = km._postal_wait_maps()
        self.assertIn((A, "peer:TESTHOST:web"), last_ask, "the earlier ask survives")
        self.assertIn((A, "peer:TESTHOST:api"), last_ask, "…beside the later one — no overwrite")

    def test_the_alias_rekeys_everything_once_the_peer_speaks(self):
        W = "11111111-2222-3333-4444-000000000003"
        self._write([
            {"from_id": A, "to_id": "peer:TESTHOST", "toName": "TESTHOST:web", "t": 100,
             "kind": "question", "body": "status?"},
            {"from_id": W, "to_id": A, "t": 150, "kind": "coordinate", "body": "all good",
             "from_host": "TESTHOST", "from": "web"},
        ])
        _any, last_ask, _aw = km._postal_wait_maps()
        self.assertIn((A, W), last_ask, "the maps rebuild from the full log — the row re-keys to the real sid")
        self.assertNotIn((A, "peer:TESTHOST:web"), last_ask)
        self.assertEqual(km._peer_answered_at(A), 150, "and the reply releases the wait")


class AnswerClockIgnoresCoordinates(_AwaitBase):
    """The answered-supersede walks reply-REQUIRING sends (2026-09-08). On main it walked last_any, so a
    coordinate the asker sent after the answer landed made the answer read stale — and the card kept
    "Awaiting <peer>" although the peer had answered, until the 6h backstop."""

    def _stamp(self, written_at):
        # a closer stamp awaiting B, written at `written_at` (the write time is the supersede key)
        return {"awaitingAt": written_at, "awaitingKind": "peer", "awaitingPeers": [B],
                "awaitingWhy": "asked the api session which port", "log": [{"kind": "awaiting", "at": written_at}]}

    def test_thanks_after_the_answer_leaves_the_question_answered(self):
        self._write([
            {"from_id": A, "to_id": B, "t": 100, "kind": "question", "body": "which port?"},
            {"from_id": B, "to_id": A, "t": 200, "kind": "coordinate", "body": "8080"},
            {"from_id": A, "to_id": B, "t": 300, "kind": "coordinate", "body": "thanks, going with 8080"},
        ])
        self.assertEqual(km._peer_answered_at(A), 200, "main: 0 — the thanks re-opened the pair")
        self.assertEqual(km._peer_answered(A), (200, {B: 200}), "…pair-aware alike")
        self.assertTrue(km._peer_stamp_superseded(self._stamp(120), km._peer_answered(A)),
                        "a stamp written between the ask and its answer is ended by the answer (main: stands)")
        self.assertFalse(km._peer_stamp_superseded(self._stamp(250), km._peer_answered(A)),
                         "a stamp written AFTER the answer is fresher than it — it stands, as before")

    def test_a_later_question_does_reopen(self):
        # the boundary: a NEW reply-requiring send after the answer is a new wait
        self._write([
            {"from_id": A, "to_id": B, "t": 100, "kind": "question", "body": "which port?"},
            {"from_id": B, "to_id": A, "t": 200, "kind": "coordinate", "body": "8080"},
            {"from_id": A, "to_id": B, "t": 300, "kind": "question", "body": "and the host?"},
        ])
        self.assertEqual(km._peer_answered_at(A), 0)
        self.assertFalse(km._peer_stamp_superseded(self._stamp(120), km._peer_answered(A)))

    def test_a_kindless_legacy_row_counts_by_its_ask_prefix(self):
        # rows from before the schema `kind`: the QUESTION/ASK lead word is the ask tell (last_ask's
        # own rule); a kindless row without it requests nothing
        self._write([
            {"from_id": A, "to_id": B, "t": 100, "body": "QUESTION: which port?"},
            {"from_id": B, "to_id": A, "t": 200, "body": "8080"},
            {"from_id": A, "to_id": B, "t": 300, "body": "thanks"},
        ])
        _any, _ask, last_await = km._postal_wait_maps()
        self.assertEqual(last_await.get((A, B)), 100)
        self.assertEqual(km._peer_answered_at(A), 200)


class MailKeyedByStableId(_AwaitBase):
    """Cross-host rows key on the recipient's stable id (2026-09-08): the row's own `to_sid` when it has
    one; else the name alias AT the row's send time. Last-write-wins re-keyed every old message to
    whichever session most recently wore the name."""

    X = "11111111-2222-3333-4444-000000000003"   # the session that wore "api" on TESTHOST first
    Y = "11111111-2222-3333-4444-000000000004"   # a later session that reused the name
    C = "11111111-2222-3333-4444-000000000005"   # an unrelated local session Y mailed

    def _reused_name(self):
        # A asks "api" (an OLDER row: no to_sid); X — then wearing the name — answers; later a NEW
        # session Y wears "api" and mails someone else, which is how the alias learns Y
        return [
            {"from_id": A, "to_id": "peer:TESTHOST", "toName": "TESTHOST:api", "t": 100,
             "kind": "question", "body": "status of the api thing?"},
            {"from_id": self.X, "to_id": A, "t": 150, "kind": "coordinate", "body": "shipped",
             "from_host": "TESTHOST", "from": "api"},
            {"from_id": self.Y, "to_id": self.C, "t": 400, "kind": "coordinate", "body": "hello from the new api",
             "from_host": "TESTHOST", "from": "api"},
        ]

    def test_a_reused_name_leaves_the_old_ask_keyed_to_the_session_it_went_to(self):
        self._write(self._reused_name())
        _any, last_ask, _aw = km._postal_wait_maps()
        self.assertIn((A, self.X), last_ask, "keyed to X, who wore the name when the ask was sent (main: Y)")
        self.assertNotIn((A, self.Y), last_ask)
        self.assertEqual(km._peer_answered_at(A), 150, "X's reply answers it (main: 0 — the reply sits under X, the ask under Y)")
        self.assertEqual(km._peer_answered(A)[1], {self.X: 150})
        self.assertNotIn(A, km._wait_for_graph(1_000_000, {A, self.X, self.Y, self.C}),
                         "no edge: the ask was answered (main: A → Y, a stranger A never asked, forever)")

    def test_an_ask_sent_after_the_reuse_keys_to_the_new_wearer(self):
        # the ASSERTIONS hold on main too (last-write-wins also lands on Y); the test itself fails there
        # on the 3-tuple unpack. The anchor picks the most recent sighting at or before the send.
        self._write(self._reused_name() + [
            {"from_id": A, "to_id": "peer:TESTHOST", "toName": "TESTHOST:api", "t": 500,
             "kind": "question", "body": "new api: status?"}])
        _any, last_ask, _aw = km._postal_wait_maps()
        self.assertIn((A, self.Y), last_ask)
        self.assertIn((A, self.X), last_ask, "…while the old ask keeps its own key")

    def test_upgrade_time_a_legacy_ask_to_a_recreated_peer_stays_keyed_to_the_prior_wearer(self):
        # review find, 2026-09-08: the residual the PR body names, pinned so the boundary is visible:
        # an ask sent BEFORE the upgrade (no to_sid) to a name a recreated session now wears, where the
        # new wearer's FIRST sighting on this host is its own reply. The anchor can only pick the prior
        # wearer (the log records no wearer deaths, and nothing sighted the new one before the send), so
        # the ask reads open on both readers; main's last-write-wins happened to read it answered. The
        # same exchange on a post-upgrade row keys by to_sid and reads answered: new rows cannot recur.
        W1 = self.X                                   # wore "api" before the ask; never replied to it
        W2 = self.Y                                   # recreated under the name; its first row is the reply
        legacy = [
            {"from_id": W1, "to_id": self.C, "t": 50, "kind": "coordinate", "body": "hello from the first api",
             "from_host": "TESTHOST", "from": "api"},
            {"from_id": A, "to_id": "peer:TESTHOST", "toName": "TESTHOST:api", "t": 100,
             "kind": "question", "body": "status?"},
            {"from_id": W2, "to_id": A, "t": 150, "kind": "coordinate", "body": "shipped",
             "from_host": "TESTHOST", "from": "api"},
        ]
        self._write(legacy)
        km.jd._PEER_ASK_CACHE[:] = [None, ({}, {}, {})]
        _any, last_ask, _aw = km._postal_wait_maps()
        self.assertIn((A, W1), last_ask, "anchored at the send: the prior wearer (main: W2, the answerer)")
        self.assertEqual(km._peer_answered_at(A), 0, "the documented residual: open until the 6h wake (main: 150)")
        self.assertEqual(km.jd._open_ask_peers(A), [W1], "the judge's gate agrees with the wait maps")
        # the same exchange as a post-upgrade row: the relay wrote the recipient's id, no alias involved
        self._write([dict(legacy[1], to_sid=W2)] + [legacy[0], legacy[2]])
        km.jd._PEER_ASK_CACHE[:] = [None, ({}, {}, {})]
        self.assertEqual(km._peer_answered_at(A), 150, "to_sid keys the row to W2; W2's reply answers it")
        self.assertEqual(km.jd._open_ask_peers(A), [])

    def test_to_sid_keys_the_row_without_any_alias(self):
        # a relay row since 2026-09-08 carries the sid the send resolved: no peer row is needed to
        # place it, and a later name reuse cannot move it
        self._write([
            {"from_id": A, "to_id": "peer:TESTHOST", "toName": "TESTHOST:api", "to_sid": self.X, "t": 100,
             "kind": "question", "body": "status?"},
            {"from_id": self.Y, "to_id": self.C, "t": 400, "kind": "coordinate", "body": "hi",
             "from_host": "TESTHOST", "from": "api"},
        ])
        _any, last_ask, last_await = km._postal_wait_maps()
        self.assertIn((A, self.X), last_ask, "main: (A, Y) — the alias re-key won; to_sid was never read")
        self.assertNotIn((A, "peer:TESTHOST:api"), last_ask)
        self.assertNotIn((A, self.Y), last_ask)
        self.assertEqual(last_await.get((A, self.X)), 100)


if __name__ == "__main__":
    unittest.main()
