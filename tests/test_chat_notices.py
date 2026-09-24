#!/usr/bin/env python3
"""The chat page's NEEDS YOU BOX, kernel side (plans/needs-you.md, phase three; the approval box of plans/notice-cards.md,
"Action kinds and the held-mail card", 2026-09-19, before it): the session frame's status carries `notices`, this session's
Needs you items that are not hard stops, each with a way to act. Goal rows first (kind "goal": the card's text, its decision
brief, whether Continue is offered), from the rows the last feed build filed (_needs_you_rows over the frame: a placeholder,
a notice card and a hard stop, a card floored with a live-block object, stay out); then the standing needs-you notices from
the same projection the feed card reads with the cleared ledger applied (kind "notice": the stored actions each with its
kind; a notice without actions offers Clear). An informational notice is not the user's and stays off the box. A decision
(the expire row) or a Clear drops the row. The chat signature carries the rows' ids and faces so the box and the ring move
in one frame. Synthetic: a placeholder sid, invented names and text."""
import inspect
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from romp_load import load_source
from tests.needs_row_fixture import populated_ask   # noqa: E402  the shared fixture, a package module (romp_load put the checkout root on the path for a direct run)

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")

os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "test-token-DO-NOT-USE")
load_source("romp_event_model", os.path.join(BIN, "romp-event-model"))
load_source("romp_judge", os.path.join(BIN, "romp-judge"))
km = load_source("romp_kernel", os.path.join(BIN, "romp-kernel"))

SID = "11111111-2222-3333-4444-000000000902"   # a PRIVATE synthetic sid: the suite shares one state root across modules, and a names
#                                                entry left under the shared placeholder poisons a later module's route test (2026-09-19)
KSRC = open(os.path.join(os.path.dirname(HERE), "kernel", "kernel.py")).read()


def _held(mid):
    return [{"label": "Approve", "kind": "quarantine", "body": {"mid": mid, "verdict": "approve"}},
            {"label": "Deny", "kind": "quarantine", "body": {"mid": mid, "verdict": "deny"}}]


class ChatNotices(unittest.TestCase):
    # the suite runs every module in one process over one state root: these tests restore the SHARED files they append to (the
    # owner-less home, its archive and index, the cleared ledger) and unlink only their own sid's files (the review of PR 1890,
    # low c, the 1885 round-two rule)
    @staticmethod
    def _shared():
        out = {}
        f = km.jd.STATE / "cleared.jsonl"
        out["cleared.jsonl"] = f.read_bytes() if f.exists() else None
        for d in ("notices", "notices-archive"):
            dd = km.jd.STATE / d
            if dd.exists():
                for f in dd.iterdir():
                    if f.name.startswith("notes"):
                        out[d + "/" + f.name] = f.read_bytes()
        return out

    def setUp(self):
        self._before = self._shared()
        km.jd.NAMES.mkdir(parents=True, exist_ok=True)
        (km.jd.NAMES / SID).write_text("web\t%s\t#1EA1EB\t#ffffff\n" % (km.jd.STATE / "notes-api"))
        km.NAMES = km.jd.NAMES
        km._live_scope.names = None
        km._NOTICE_MEMO.clear(); km._CLEARED_MEMO["slot"] = None
        self._needs = km._feed_needs_input[0]
        km._feed_needs_input[0] = frozenset()             # a feed build happened: the slice answers (the gate is its own test)
        self._rows = getattr(km, "_feed_needs_rows", [None])[0]   # getattr: absent at the base before the box's goal rows
        getattr(km, "_feed_needs_rows", [None])[0] = {}

    def tearDown(self):
        km._feed_needs_input[0] = self._needs
        getattr(km, "_feed_needs_rows", [None])[0] = self._rows
        for f in (km.jd.NAMES / SID, km.jd.STATE / "notices" / (SID + ".jsonl"), km.jd.STATE / "notices-archive" / (SID + ".jsonl"),
                  km.jd.STATE / "notices-archive" / (SID + ".revs.json")):
            if f.exists():
                f.unlink()
        after = self._shared()
        for rel in set(after) | set(self._before):
            f = km.jd.STATE / rel
            before = self._before.get(rel)
            if before is None:
                if f.exists():
                    f.unlink()
            elif after.get(rel) != before:
                f.parent.mkdir(parents=True, exist_ok=True); f.write_bytes(before)
        km._NOTICE_MEMO.clear(); km._CLEARED_MEMO["slot"] = None

    def test_the_slice_is_absent_before_the_first_feed_build_as_needs_you_is(self):
        # the review of PR 1890, low d: the box must never show before the ring; both read the first feed build since start
        km._feed_needs_input[0] = None
        km.post_notice(SID, "m1", "t", producer="postal", actions=_held("m1"), needs_you=True, dismiss_on_action=True, now=100, t=100)
        self.assertIsNone(km._chat_notices(SID), "None, as needsYou is None then")
        km._feed_needs_input[0] = frozenset()
        self.assertEqual(len(km._chat_notices(SID)), 1, "the first build lets the slice answer")
        self.assertIn('for n in (_chat_notices(sid) or ())))', KSRC, "the signature reads the absent slice as empty")

    def test_the_row_carries_the_attachment_the_feed_card_shows(self):
        # the review of PR 1890, low e: one face for both surfaces; the row copies the stored attachment verdict as the card does
        att = {"path": str(km.jd.STATE / "notes-api" / "accuracy.png"), "kind": "image", "allowed": True, "why": "", "pin": "abc.png"}
        with km._notice_lock:
            km._notice_append(SID, {"op": "post", "t": 100, "key": "fig", "rev": 1, "sid": SID, "title": "A figure", "body": "", "producer": "figure", "needsYou": True,
                                    "attachment": att, "actions": [{"label": "Send again", "kind": "send", "body": {"text": "please regenerate"}}]})
        rows = km._chat_notices(SID)
        self.assertEqual(rows[0]["attachment"], att)
        km.post_notice(SID, "m1", "t", producer="postal", actions=_held("m1"), needs_you=True, dismiss_on_action=True, now=100, t=100)
        self.assertIsNone([r for r in km._chat_notices(SID) if r["key"] == "m1"][0]["attachment"], "a held message carries none")

    def test_the_box_lists_every_needs_you_notice_with_its_actions_by_kind_or_clear_when_it_has_none(self):
        # getattr: at the base before the box the helper is absent, and the test reds on its behaviour
        rows = getattr(km, "_chat_notices", lambda sid: None)(SID)
        self.assertEqual(rows, [], "a session with no notice file has an empty box")
        km.post_notice(SID, "m1", "New message from api", "from TESTHOST:api to web, held because peer TESTHOST is DIRECTED\n\nhello",
                       producer="postal", actions=_held("m1"), needs_you=True, dismiss_on_action=True, now=100, t=100)
        km.post_notice(SID, "fig", "A new figure is ready", producer="figure", now=101, t=101)                       # informational: no decision
        km.post_notice(SID, "dropped", "1 message was not re-sent", producer="dropped-sends", needs_you=True, now=102, t=102)   # needs you, no action to take here
        with km._notice_lock:                                                          # an OLDER row, written before the kinds: its action carries a route
            km._notice_append(SID, {"op": "post", "t": 103, "key": "again", "rev": 1, "sid": SID, "title": "Send it again?", "body": "", "producer": "cli",
                                    "needsYou": True, "actions": [{"label": "Send again", "route": "/send", "body": {"text": "please retry"}}]})
        rows = km._chat_notices(SID)
        self.assertEqual([r["itemId"] for r in rows], ["notice:%s:m1:1" % SID, "notice:%s:dropped:1" % SID, "notice:%s:again:1" % SID],
                         "every needs-you notice in post order; the informational figure stays off (phase three: a notice with no action offers Clear)")
        self.assertEqual([r["kind"] for r in rows], ["notice", "notice", "notice"], "each row says its kind")
        self.assertEqual(rows[1]["actions"], [], "the dropped-sends notice has no stored action: the client offers Clear")
        r = rows[0]
        self.assertEqual((r["key"], r["rev"], r["title"], r["producer"]), ("m1", 1, "New message from api", "postal"))
        self.assertEqual(r["body"], "from TESTHOST:api to web, held because peer TESTHOST is DIRECTED\n\nhello", "the message text is the body")
        self.assertEqual(r["actions"], _held("m1"), "the stored actions with their kind")
        self.assertEqual(rows[2]["actions"], [{"label": "Send again", "kind": "send", "route": "/send", "body": {"text": "please retry"}}], "an older row's route reads as its kind beside it")

    def test_goal_rows_come_first_as_the_feed_build_filed_them_then_the_notices(self):
        # the box's goal rows are the last feed build's (_feed_needs_rows), read without a second build; a notice follows them
        rows_fn = getattr(km, "_needs_you_rows", None)
        self.assertIsNotNone(rows_fn, "the kernel projects the box's goal rows from a feed frame")
        g1, g2, g3, g4, g5 = (SID + ":g%d" % i for i in range(1, 6))
        frame = {"asks": [
            {"itemId": g1, "sid": SID, "text": "which database does the suite target?", "blockSummary": "Postgres or SQLite: the fixtures differ",
             "background": "the suite has two databases and the fixtures load into one", "origin": {"peer": "api", "peerSid": "22222222-2222-3333-4444-000000000902", "live": True},
             "warns": [{"kind": "brief-failed", "t": 99, "msg": "the brief could not be written", "detail": "the model returned nothing"}],   # a section's and a badge's field: the row must carry them (a mutant dropping one passed a fixture without them)
             "live": True, "t": 100, "board": "feed", "category": "needs_input", "column": "needs_input", "blocked": None},
            {"itemId": g2, "sid": SID, "text": "keep going on the parser", "live": True, "t": 101, "board": "feed", "category": "working", "column": "working", "blocked": None},
            {"itemId": g3, "sid": SID, "text": "the suite's fixtures directory", "live": True, "t": 102, "board": "feed", "category": "needs_input", "column": "needs_input",
             "blocked": {"state": "permission", "what": "this session is stopped awaiting your approval"}},
            {"itemId": "blocked:" + SID, "sid": SID, "text": "Awaiting your approval", "live": True, "t": 103, "board": "feed", "category": "needs_input", "column": "needs_input",
             "provisional": True, "blocked": {"state": "permission", "what": "stopped"}},
            {"itemId": "notice:%s:m1:1" % SID, "sid": SID, "text": "New message from api", "live": True, "t": 104, "board": "feed", "category": "needs_input", "column": "needs_input",
             "notice": {"producer": "postal", "key": "m1", "rev": 1}, "blocked": None},
            {"itemId": g4, "sid": SID, "text": "a dead session's question", "blockSummary": None, "live": False, "t": 105, "board": "feed", "category": "needs_input", "column": "needs_input", "blocked": None},
            {"itemId": "22222222-2222-3333-4444-000000000902:g1", "sid": "22222222-2222-3333-4444-000000000902", "text": "another session's question", "live": True, "t": 106,
             "board": "feed", "category": "needs_input", "column": "needs_input", "blocked": None},
            {"itemId": g5, "sid": SID, "text": "the judges cannot read this session", "live": True, "t": 107, "board": "feed", "category": "needs_input", "column": "needs_input",
             "blocked": {"state": "judgeAuth", "mode": "key", "login": "", "what": "romp can't analyze this session: the API key its judges bill is being refused"}},
            populated_ask(SID),   # every card field DISTINCT and non-None but blocked (tests/needs_row_fixture.py): a contributor's post-merge note on PR 2124 ran seven
                                  # single-edit mutants of the row builder past a fixture populating five fields
        ]}
        rows = rows_fn(frame)
        self.assertEqual(sorted(rows), sorted([SID, "22222222-2222-3333-4444-000000000902"]), "rows per session, only sessions with one")
        # the card's own fields ride the plain row (the row carries what the card carries, plans/needs-you.md): the list is written out here so a
        # kernel without them reds on the rows themselves, and the kernel's own list is held to it below
        CARD_FIELDS = ("summary", "blockSummary", "briefParts", "summaryParts", "distillState", "summaryStale", "relayNote", "background",
               "stalled", "tree", "awaiting", "recheck", "rejudging", "nudgeFailed", "nudged", "interrupting", "interrupted", "waitingOn", "origin", "handoffTo",
               "warns", "failLog", "summaryAnchorUuid", "summaryAnchorQuote", "summaryAnchorsPara", "doneConfirming", "blocked", "column", "judging", "working", "sessState", "delegTracked")
        TREE_FIELDS = ("id", "kind", "text", "status", "children", "parked", "cleared", "reviewedEarlier", "auth", "qderived", "t",
               "anchorUuid", "summary", "blockSummary", "summaryAnchorUuid", "summaryAnchorQuote")   # the tree node fields the builder reads: the row carries that projection, never the tint (round three of the box content PR)
        tree_of = lambda tr: None if tr is None else [{k: r[k] for k in TREE_FIELDS if k in r} for r in tr]
        card_fields = lambda a: {f: (tree_of(a.get("tree")) if f == "tree" else a.get(f)) for f in CARD_FIELDS}
        self.assertEqual(rows[SID], [
            {"itemId": g1, "kind": "goal", "title": "which database does the suite target?", "body": "Postgres or SQLite: the fixtures differ", "cont": True, "t": 100, **card_fields(frame["asks"][0])},
            {"itemId": g4, "kind": "goal", "title": "a dead session's question", "body": "", "cont": False, "t": 105, **card_fields(frame["asks"][5])},
            {"itemId": g5, "kind": "goal", "title": "the judges cannot read this session", "body": "romp can't analyze this session: the API key its judges bill is being refused", "cont": False, "fix": "credential", "t": 107},
            {"itemId": SID + ":g6", "kind": "goal", "title": "which port do the fixtures own?", "body": frame["asks"][8]["blockSummary"], "cont": True, "t": 108, **card_fields(frame["asks"][8])}],
            "the judge's questions in the frame's order: a working card, a live-block card, the placeholder and the notice card stay out; "
            "no brief yet reads as an empty line; Continue only on a live session; the judges' credential refusal is a row whose action is the fix")
        full = rows[SID][3]   # the populated ask's row, field by field: a field set to None, or read from the wrong key, names itself here
        for f in CARD_FIELDS:
            want = tree_of(frame["asks"][8]["tree"]) if f == "tree" else frame["asks"][8][f]
            self.assertEqual(full[f], want, "the row's %s is the card's (the tree through the projection, its tint and modal fields dropped)" % f)
            if f != "blocked":
                self.assertIsNotNone(full[f], "premise: the fixture populates %s" % f)
        self.assertIsNone(full["blocked"], "a plain row's live block is None by construction (the credential floor builds the fix row; every other live block is a hard stop and takes no row)")
        self.assertEqual(len({repr(frame["asks"][8][f]) for f in CARD_FIELDS if f != "blocked" and not isinstance(frame["asks"][8][f], bool)}), len([f for f in CARD_FIELDS if f != "blocked" and not isinstance(frame["asks"][8][f], bool)]),
                         "premise: every non-boolean value is distinct, so a read from the wrong key shows")
        self.assertEqual(km._NEEDS_ROW_CARD_FIELDS, CARD_FIELDS, "the kernel's list of the card's fields on the row, the one the chat signature keys")
        self.assertEqual(km._NEEDS_ROW_TREE_FIELDS, TREE_FIELDS, "the kernel's projection of a tree node onto the builder's fields")
        self.assertTrue(km._hard_stop_card(frame["asks"][2]) and not km._hard_stop_card(frame["asks"][0]), "a hard stop is a card with a live-block object")
        self.assertFalse(km._hard_stop_card(frame["asks"][7]), "the judges' credential refusal is NOT a hard stop (plans/needs-you.md, the sixth floor): the session runs")
        km._feed_needs_rows[0] = rows
        km.post_notice(SID, "m1", "New message from api", "hello", producer="postal", actions=_held("m1"), needs_you=True, dismiss_on_action=True, now=100, t=100)
        box = km._chat_notices(SID)
        self.assertEqual([(r["itemId"], r["kind"]) for r in box], [(g1, "goal"), (g4, "goal"), (g5, "goal"), (SID + ":g6", "goal"), ("notice:%s:m1:1" % SID, "notice")], "goal rows first, then the notices")
        for r in box[:4]:
            self.assertNotIn("t", r, "the unkeyed time never rides the wire (the third review of PR 1967): %r" % sorted(r))
            self.assertEqual(set(r) - {"fix"} - set(CARD_FIELDS), {"itemId", "kind", "title", "body", "cont"}, "the row's face, the card's fields it carries since the row carries what the card carries (plans/needs-you.md), and nothing else")
        self.assertEqual(box[0]["title"], "which database does the suite target?"); self.assertEqual(box[4]["actions"], _held("m1"))
        self.assertEqual((box[2]["fix"], box[2]["cont"]), ("credential", False), "the credential row: the fix as its action, no Continue")
        km._feed_needs_rows[0] = {}
        self.assertEqual([r["kind"] for r in km._chat_notices(SID)], ["notice"], "a frame that re-filed the goals drops their rows")
        self.assertIn('sig.append(tuple((n["itemId"], n.get("kind") or "notice", n.get("title") or "", n.get("body") or "", bool(n.get("cont")), n.get("fix") or "",', KSRC,
                      "the chat signature carries the rows' ids and faces in its one value: a brief landing or a Continue offered repaints the box")
        self.assertIn("    _rows_now = _needs_you_rows(feed)", KSRC, "the feed build files the rows beside the needs-you set")

        self.assertIn("    if _needs_rows_face(_rows_now) != _needs_rows_face(_feed_needs_rows[0]):\n        _pusher_wake.set()", KSRC, "a row change wakes the pusher, as a set change does")

    def test_a_rows_face_moving_with_the_set_unchanged_wakes_the_pusher(self):
        """The second contributor's post-merge review of PR 1967 (2026-09-22): the row-face wake at the feed build's end was pinned by source
        text alone. Three builds over one blocked goal, the bells and pushes stubbed: the first files the row (and wakes, as the set moved
        too); the second, over an unchanged store, leaves the cleared wake unset; the third, after the brief changed on disk with the set
        unchanged, finds it set. With the compare gated off the third finds it unset."""
        brief = km.jd.STATE / "brief-on-disk.txt"; brief.write_text("which database does the suite target?")
        gid = SID + ":g1"

        card = {"background": None}   # a card field beside the brief: the fourth build moves it alone (round three of the box content PR)

        def feed(now, live_map):
            return {"type": "feed", "asks": [{"itemId": gid, "sid": SID, "name": "web", "text": "pick the suite's database", "column": "needs_input",
                                             "category": "needs_input", "blockSummary": brief.read_text(), "blocked": None, "live": True, "background": card["background"],
                                             "tree": [{"id": gid, "kind": "ask", "text": "pick the suite's database", "status": "open", "children": []}]}],
                    "items": [], "working": [], "awaiting": [], "stateUnknown": [], "sessions": [{"sid": SID, "name": "web"}]}
        saved = list(km._built_feed)
        try:
            with mock.patch.object(km, "build_feed", feed), mock.patch.object(km, "_task_tracking_on", lambda: True), \
                 mock.patch.object(km, "_feed_notifications", lambda f: []), mock.patch.object(km, "_badge_push", lambda n: None):
                km._pusher_wake.clear(); km._build_feed_locked(100, {}, "s1")
                self.assertEqual([r["itemId"] for r in km._feed_needs_rows[0].get(SID, [])], [gid], "the first build files the row")
                self.assertTrue(km._pusher_wake.is_set(), "and wakes: the set and the rows moved from nothing")
                km._pusher_wake.clear(); km._build_feed_locked(101, {}, "s2")
                self.assertFalse(km._pusher_wake.is_set(), "an unchanged store: the set and the rows' face stand, no wake")
                brief.write_text("which database does the suite target, and which loader?")   # the brief changed on disk; the set unchanged
                km._pusher_wake.clear(); km._build_feed_locked(102, {}, "s3")
                self.assertTrue(km._pusher_wake.is_set(), "a row's line moved with the set unchanged: the pusher wakes, so the box follows the card by one build (before, pinned by source text alone)")
                self.assertEqual(km._feed_needs_rows[0][SID][0]["body"], "which database does the suite target, and which loader?")
                card["background"] = "the suite has two databases"   # one card field alone, the brief and the set unchanged
                km._pusher_wake.clear(); km._build_feed_locked(103, {}, "s4")
                self.assertTrue(km._pusher_wake.is_set(), "a card field the row carries moved alone: the face reads it, the pusher wakes (a face cut to the six old fields passes the third build and fails here)")
        finally:
            km._built_feed[:] = saved; km._pusher_wake.clear()
            brief.unlink(missing_ok=True)

    def test_a_decision_a_clear_and_an_expiry_drop_the_row(self):
        km.post_notice(SID, "m1", "t", producer="postal", actions=_held("m1"), needs_you=True, dismiss_on_action=True, now=100, t=100)
        km.post_notice(SID, "m2", "t", producer="postal", actions=_held("m2"), needs_you=True, dismiss_on_action=True, now=100, t=100)
        soon = int(km.time.time()) + 3600
        km.post_notice(SID, "m3", "t", producer="postal", actions=_held("m3"), needs_you=True, dismiss_on_action=True, now=100, t=100, expires_at=soon)
        self.assertEqual(len(km._chat_notices(SID)), 3)
        with km._notice_lock:                                                          # the runner's retirement on a decision
            km._notice_append(SID, {"op": "expire", "t": 200, "key": "m1", "rev": 1, "sid": SID})
        km._clear_ask("notice:%s:m2:1" % SID)                                           # the user's Clear on the feed card
        self.assertEqual([r["key"] for r in km._chat_notices(SID)], ["m3"], "the decided and the dismissed rows are off the box")
        saved = km.time.time
        try:
            km.time.time = lambda: soon + 1                                                # past m3's expiry
            self.assertEqual(km._chat_notices(SID), [], "an expired notice is off the box at the next read")
        finally:
            km.time.time = saved

    def test_the_owner_less_run_and_a_fault_give_an_empty_box(self):
        km.post_notice("", "k", "Remember the standup moved", producer="cli", needs_you=True, now=100, t=100)
        self.assertEqual(km._chat_notices(km.NOTICE_OWNERLESS_SID), [], "the owner-less home is not a session: no chat page, no box")
        saved = km._notice_projection
        try:
            def boom(*a, **k): raise OSError("unreadable")
            km._notice_projection = boom
            self.assertEqual(km._chat_notices(SID), [], "best-effort: a fault is an empty box, never a dead frame")
        finally:
            km._notice_projection = saved

    def test_the_session_frame_carries_the_rows_on_its_status_and_the_signature_carries_their_ids(self):
        src = inspect.getsource(km.build_session)
        self.assertIn('"needsYou": needs_you,', src)
        self.assertIn('"notices": _chat_notices(sid),', src, "beside needsYou on the STATUS, so a status-only delta carries a decision")
        self.assertIn("sig.append((_feed_needs_input_of(sid) is True, _feed_needs_input_count_of(sid) or 0))\n", KSRC)
        self.assertIn('sig.append(tuple((n["itemId"], n.get("kind") or "notice", n.get("title") or "", n.get("body") or "", bool(n.get("cont")), n.get("fix") or "",', KSRC, "the chat signature: a hold posted or a decision taken brings a frame forward")
        labels = km._CHAT_SIG_LABELS
        self.assertEqual(labels[labels.index("needs") + 1], "notices", "one label per signature position, the new one right after needs (the builder appends them in that order)")

    def test_the_chat_page_places_the_box_between_the_transcript_and_the_background_box(self):
        body = km._chat_body()
        self.assertIn('<div id="notices" style="display:none"></div>', body)
        self.assertLess(body.index('id="content"'), body.index('id="notices"'), "after the transcript")
        self.assertLess(body.index('id="notices"'), body.index('id="bg-tasks"'), "above the background box (the user: a decision sits nearest the composer's eye line, above the agents)")
        self.assertLess(body.index('id="bg-tasks"'), body.index('id="composer"'))


if __name__ == "__main__":
    unittest.main()
