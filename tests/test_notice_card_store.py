"""The notice card STORE (T370, plans/notice-cards.md, issue #1750): kernel-made feed cards a producer posts without the judges. The
store STATE/notices/<sid>.jsonl; post_notice(...) -> (row, error) behind its doors (in-process, the backend's hook, POST
/notice; `romp card` is tests/romp.bats'); the feed's card family under notice:<sid>:<key>:<rev>; the three moves (a
dismissal, a revision, an expiry); the actions allowlist executed by the kernel on the gesture; the attachment verdict by
the preview's confinement; retention to the archive; the memo bound. Hermetic: a temp state root, a synthetic session in
the notes-api demo world; nothing touches the live state root."""
import json
import os
import re
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from romp_load import load_source

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
_XDG = tempfile.mkdtemp()
os.environ["XDG_STATE_HOME"] = _XDG
os.environ.pop("ROMP_STATE_DIR", None)
os.makedirs(os.path.join(_XDG, "romp"), exist_ok=True)
open(os.path.join(_XDG, "romp", "session-hosts"), "w").write("off\n")
km = load_source("romp_kernel_notice_store", os.path.join(BIN, "romp-kernel"))
sb = load_source("romp_sdk_backend_notice_store", os.path.join(BIN, "romp_sdk_backend.py"))
KSRC = open(os.path.join(BIN, "romp-kernel")).read()

SID = "11111111-2222-3333-4444-555555555555"     # web, the notes-api demo world
SID2 = "11111111-2222-3333-4444-666666666666"    # api


class World:
    """A hermetic state root with two named sessions (web, api) whose folder is the temp cwd; the kernel rebound to it."""
    def __init__(self):
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        self.cwd = root / "notes-api"; self.cwd.mkdir()
        self.orig_state, self.orig_names = km.jd.STATE, km.NAMES   # the conftest guard: shared state goes back at close
        km.jd._rebind_state(root / "state")
        (km.jd.STATE / "session-hosts").parent.mkdir(parents=True, exist_ok=True)
        (km.jd.STATE / "session-hosts").write_text("off\n")
        km.jd.NAMES.mkdir(parents=True, exist_ok=True)
        (km.jd.NAMES / SID).write_text("web\t%s\t#1EA1EB\t#ffffff\n" % self.cwd)
        (km.jd.NAMES / SID2).write_text("api\t%s\t#B69513\tblack\n" % self.cwd)
        km.NAMES = km.jd.NAMES
        self.saved = (km._live_map, km._cwd_of, km._mark_views_dirty, km._push_soon, km._deliver_text, km.Sessions.live)
        km._live_map = lambda: {}
        km.Sessions.live = staticmethod(lambda: {})
        km._cwd_of = lambda sid: str(self.cwd) if sid in (SID, SID2) else None
        self.dirty, self.pushes, self.delivered = [], [], []
        km._mark_views_dirty = lambda: self.dirty.append(1)
        km._push_soon = lambda: self.pushes.append(1)
        km._deliver_text = lambda sid, text, plain=False: (self.delivered.append((sid, text)) or (True, "", False))
        km._NOTICE_MEMO.clear(); km._NOTICE_SWEPT.clear()
        for k in km._NOTICE_MEMO_STATS: km._NOTICE_MEMO_STATS[k] = 0
        km._CLEARED_MEMO["slot"] = None

    def close(self):
        (km._live_map, km._cwd_of, km._mark_views_dirty, km._push_soon, km._deliver_text, km.Sessions.live) = self.saved
        km.jd._rebind_state(self.orig_state); km.NAMES = self.orig_names
        km._NOTICE_MEMO.clear(); km._NOTICE_SWEPT.clear(); km._CLEARED_MEMO["slot"] = None
        self.td.cleanup()

    def png(self, name="figure.png"):
        p = self.cwd / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        return str(p)


_REAL_DELIVER = km._deliver_text   # the module's delivery door, before any test world stubs it


def _rows(sid):
    p = km._notice_path(sid)
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


class PostNotice(unittest.TestCase):
    def setUp(self): self.w = World()
    def tearDown(self): self.w.close()

    def test_a_post_appends_one_row_with_the_kernels_rev_and_stamp_and_wakes_the_pusher(self):
        row, err = km.post_notice(SID, "figure", "A new version of the accuracy figure is ready", "Regenerated after the sweep.",
                                  producer="figure", now=1757000000, t=1756999990)
        self.assertIsNone(err); self.assertEqual((row["rev"], row["at"], row["t"], row["op"]), (1, 1757000000, 1756999990, "post"))
        self.assertEqual(_rows(SID), [row], "the file holds exactly the returned row")
        self.assertEqual(row["needsYou"], False); self.assertEqual(row["actions"], []); self.assertIsNone(row["attachment"])
        self.assertEqual((len(self.w.dirty), len(self.w.pushes)), (1, 1), "the views are dirtied and the pusher woken once")

    def test_every_refusal_is_said_and_nothing_is_written(self):
        cases = [
            (dict(sid="", key="k", title="t"), "needs a session"),
            (dict(sid=SID, key="bad key!", title="t"), "the key must match"),
            (dict(sid=SID, key="a" * 65, title="t"), "the key must match"),
            (dict(sid=SID, key="k", title=""), "needs a title"),
            (dict(sid=SID, key="k", title="x" * 201), "title is too long"),
            (dict(sid=SID, key="k", title="t", body="b" * (64 * 1024 + 1)), "body is too long"),
            (dict(sid=SID, key="k", title="t", producer="not ok"), "producer label"),
            (dict(sid="99999999-2222-3333-4444-555555555555", key="k", title="t"), "no session answers"),
            (dict(sid=SID, key="k", title="t", expires_at="soon"), "expiresAt must be"),
            (dict(sid=SID, key="k", title="t", expires_at=1757000000 - 1), "already past"),
            (dict(sid=SID, key="k", title="t", actions="x"), "actions must be a list"),
            (dict(sid=SID, key="k", title="t", actions=[{"label": "a", "route": "/send", "body": {"text": "x"}}] * 5), "at most 4"),
            (dict(sid=SID, key="k", title="t", actions=[{"label": "a", "route": "/watch", "body": {}}]), "not allowed"),
            (dict(sid=SID, key="k", title="t", actions=[{"label": "", "route": "/send", "body": {"text": "x"}}]), "needs a label"),
            (dict(sid=SID, key="k", title="t", actions=[{"label": "a", "route": "/send", "body": {}}]), "needs text"),
            (dict(sid=SID, key="k", title="t", actions=[{"label": "a", "route": "/send", "body": {"id": SID2, "text": "x"}}]), "names no target"),
            (dict(sid=SID, key="k", title="t", actions=[{"label": "a", "route": "/send", "body": {"name": "api", "text": "x"}}]), "names no target"),
            (dict(sid=SID, key="k", title="t", actions=[{"label": "a", "route": "/send", "body": {"text": "  /model opus"}}]), "never a command"),
            (dict(sid=SID, key="k", title="t", attachment="/nowhere/figure.png"), "attachment refused: not a file"),
        ]
        for kw, why in cases:
            kw.setdefault("producer", "figure"); kw.setdefault("now", 1757000000)
            row, err = km.post_notice(kw.pop("sid"), kw.pop("key"), kw.pop("title"), kw.pop("body", ""), **kw)
            self.assertIsNone(row, why); self.assertIn(why, err or "", "refusal names the rule: %r" % err)
        self.assertEqual(_rows(SID), [], "a refused post writes nothing"); self.assertEqual(self.w.dirty, [])

    def test_the_rev_counts_per_key_per_session_and_the_item_id_carries_it(self):
        r1, _ = km.post_notice(SID, "figure", "first", producer="figure", now=100)
        r2, _ = km.post_notice(SID, "figure", "second", producer="figure", now=200)
        o1, _ = km.post_notice(SID, "other", "other", producer="figure", now=300)
        a1, _ = km.post_notice(SID2, "figure", "api's own", producer="figure", now=400)
        self.assertEqual([r1["rev"], r2["rev"], o1["rev"], a1["rev"]], [1, 2, 1, 1])
        self.assertEqual(km._notice_item_id(SID, "figure", 2), "notice:%s:figure:2" % SID)

    def test_the_attachment_verdict_rides_the_row_an_image_pinned_and_a_refusal_carries_its_why(self):
        fp = self.w.png()
        row, err = km.post_notice(SID, "figure", "the figure", producer="figure", attachment=fp, now=100)
        self.assertIsNone(err)
        att = row["attachment"]
        self.assertEqual((att["path"], att["kind"], att["allowed"], att["why"]), (fp, "image", True, ""))
        self.assertTrue(att["pin"] and att["pin"].endswith(".png"), "an image is pinned at post time: %r" % att["pin"])
        (self.w.cwd / ".env").write_text("SECRET=1\n")
        row, err = km.post_notice(SID, "leak", "a secret", producer="figure", attachment=str(self.w.cwd / ".env"), now=100)
        self.assertIsNone(row); self.assertIn("attachment refused: a secrets-shaped name", err)
        outside = tempfile.mkdtemp(); fo = os.path.join(outside, "far.png"); open(fo, "wb").write(b"\x89PNG\r\n\x1a\n")
        # the temp dir sits under the home only when the home holds /tmp; a path outside the session's folder and the
        # home is refused by the confinement, one inside is allowed
        row, err = km.post_notice(SID, "far", "far away", producer="figure", attachment=fo, now=100)
        if os.path.realpath(outside).startswith(os.path.realpath(os.path.expanduser("~")) + os.sep):
            self.assertIsNone(err, "under the home: allowed")
        else:
            self.assertIsNone(row); self.assertIn("outside the session's folder and your home", err)


class TheCardFamily(unittest.TestCase):
    def setUp(self): self.w = World()
    def tearDown(self): self.w.close()

    def _cards(self, now, cleared=None):
        return km._notice_cards(now, cleared or {})

    def test_the_newest_revision_per_key_is_the_card_and_every_field_but_the_age_colour_is_fixed(self):
        km.post_notice(SID, "figure", "first", "one", producer="figure", now=100, t=100)
        km.post_notice(SID, "figure", "second", "two", producer="figure", now=200, t=200)
        km.post_notice(SID, "note", "a note", producer="cli", now=150, t=150, needs_you=True)
        a = self._cards(1000); b = self._cards(2000)
        self.assertEqual([c["itemId"] for c in a], ["notice:%s:note:1" % SID, "notice:%s:figure:2" % SID], "post order, the superseded rev hidden")
        strip = lambda c: {k: v for k, v in c.items() if k != "trgb"}
        self.assertEqual([strip(c) for c in a], [strip(c) for c in b], "no field but trgb derives from the clock")
        fig = a[1]
        self.assertEqual((fig["text"], fig["column"], fig["name"], fig["sid"], fig["t"], fig["tree"], fig["live"], fig["blocked"]),
                         ("second", "completed", "web", SID, 200, [], False, None))
        self.assertEqual(fig["notice"], {"producer": "figure", "key": "figure", "rev": 2, "body": "two", "attachment": None,
                                         "actions": [], "expiresAt": None, "dismissOnAction": False, "acted": False})
        self.assertEqual(a[0]["column"], "needs_input", "needsYou files under Blocked")
        self.assertEqual(fig["color"], {"bg": "#1EA1EB", "fg": "#ffffff"})
        self.assertNotIn("_ageT", fig, "no private fold field rides the wire (round two, low b)")

    def test_the_cleared_ledger_applies_before_the_cap_so_a_dismissed_row_holds_no_slot(self):
        # round three, low a: fifty-one keys, the newest dismissed: all fifty undismissed show, the oldest among them
        for i in range(51):
            km.post_notice(SID, "k%03d" % i, "card %d" % i, producer="cli", now=1000 + i, t=1000 + i)
        newest = "notice:%s:k050:1" % SID
        cards = self._cards(5000, {newest: 4000})
        self.assertEqual(len(cards), 50); self.assertEqual(cards[0]["notice"]["key"], "k000", "the oldest undismissed card stands: the dismissed one held no slot")
        self.assertNotIn(newest, [c["itemId"] for c in cards])

    def test_a_session_shows_at_most_the_newest_fifty_keys_and_the_sweep_archives_the_rest(self):
        for i in range(60):
            km.post_notice(SID, "k%03d" % i, "card %d" % i, producer="cli", now=1000 + i, t=1000 + i)
        cards = self._cards(5000)
        self.assertEqual(len(cards), km.NOTICE_LIVE_KEYS_MAX, "the projection caps the live keys")
        self.assertEqual([c["notice"]["key"] for c in cards][:2], ["k010", "k011"], "the newest fifty by their post time stand; the oldest yield")
        moved = km._compact_notices(now=5000)
        self.assertEqual(moved, 10, "the ten oldest keys are superseded into the archive")
        self.assertEqual(sorted(r["key"] for r in _rows(SID))[:2], ["k010", "k011"]); self.assertEqual(len(_rows(SID)), 50)
        arch = [json.loads(l) for l in (km._notice_archive_dir() / (SID + ".jsonl")).read_text().splitlines()]
        self.assertEqual(sorted(r["key"] for r in arch), ["k%03d" % i for i in range(10)], "nothing deleted: the rows moved")

    def test_a_dismissal_hides_the_revision_and_a_new_revision_re_shows_after_it(self):
        km.post_notice(SID, "figure", "first", producer="figure", now=100, t=100)
        i1 = "notice:%s:figure:1" % SID
        self.assertEqual([c["itemId"] for c in self._cards(500, {i1: 400})], [], "cleared: hidden")
        km.post_notice(SID, "figure", "second", producer="figure", now=600, t=600)
        self.assertEqual([c["itemId"] for c in self._cards(700, {i1: 400})], ["notice:%s:figure:2" % SID], "new information re-shows under a new id")

    def test_an_expiry_leaves_at_the_next_build_and_an_expire_row_retires_early(self):
        km.post_notice(SID, "soon", "expires", producer="figure", now=100, t=100, expires_at=1000)
        self.assertEqual(len(self._cards(999)), 1); self.assertEqual(len(self._cards(1000)), 0, "expiresAt applies as a skip at build time")
        km.post_notice(SID, "keep", "stays", producer="figure", now=100, t=100)
        row, err = km.expire_notice(SID, "keep", now=200)
        self.assertIsNone(err); self.assertEqual((row["op"], row["rev"]), ("expire", 1))
        self.assertEqual([c["itemId"] for c in self._cards(300)], ["notice:%s:soon:1" % SID], "the retired key is gone; the one not yet expired stays")
        self.assertIn("no notice with key", km.expire_notice(SID, "never", now=200)[1])

    def test_the_family_keys_no_session_for_the_cleared_ledger(self):
        self.assertIn("notice:", km._CLEARED_NO_SESSION)
        self.assertEqual(km._cleared_foreign({"notice:%s:figure:1" % SID: 5, "%s:g1" % SID: 6}), ["%s:g1" % SID], "a notice id never rides as foreign")


class Actions(unittest.TestCase):
    def setUp(self): self.w = World()
    def tearDown(self): self.w.close()

    def test_a_stored_send_action_delivers_through_the_one_door_and_dismisses_when_asked(self):
        acts = [{"label": "Send again", "route": "/send", "body": {"text": "please retry the sweep"}}]
        row, err = km.post_notice(SID, "dropped-sends", "1 message you typed before the restart was not re-sent",
                                  producer="dropped-sends", actions=acts, needs_you=True, dismiss_on_action=True, now=100)
        self.assertIsNone(err)
        iid = "notice:%s:dropped-sends:1" % SID
        ok, e = km._notice_action(iid, "/send", {"text": "please retry the sweep"})
        self.assertEqual((ok, e), (True, "")); self.assertEqual(self.w.delivered, [(SID, "please retry the sweep")])
        self.assertIn(iid, km._cleared_ids(), "dismissOnAction: a success clears the card")
        # round four, high: the dismissal is the event; a repeat click after it must not deliver the words a second time
        self.assertEqual(km._notice_action(iid, "/send", {"text": "please retry the sweep"}), (False, "that card's action ran already"))
        self.assertEqual(self.w.delivered, [(SID, "please retry the sweep")], "one delivery")
        # round five: Undo reverses the cleared ledger and brings the card back; the one-shot mark is the store's own acted row,
        # so the card returns with its action SPENT and a click delivers nothing
        km._undo_clear()
        self.assertNotIn(iid, km._cleared_ids(), "Undo restored the card's visibility")
        cards = km._notice_cards(500, km._cleared_ids())
        back = next(c for c in cards if c["itemId"] == iid)
        self.assertEqual((back["notice"]["acted"], back["notice"]["actions"]), (True, []), "back with its action spent")
        self.assertEqual(km._notice_action(iid, "/send", {"text": "please retry the sweep"}), (False, "that card's action ran already"))
        self.assertEqual(self.w.delivered, [(SID, "please retry the sweep")], "still one delivery after Undo")
        rows = _rows(SID); self.assertEqual([r["op"] for r in rows], ["post", "acted"], "the acted row rides the store")
        # a card the user cleared before ever clicking: the plain reason, no claim that its action ran
        km.post_notice(SID, "k2", "t", producer="cli", actions=[{"label": "Send", "route": "/send", "body": {"text": "x"}}], dismiss_on_action=True, now=100)
        iid2 = "notice:%s:k2:1" % SID; km._clear_ask(iid2)
        self.assertEqual(km._notice_action(iid2, "/send", {"text": "x"}), (False, "that card was dismissed"))
        self.assertEqual(km._notice_action(iid, "/send", {"text": "something else"}), (False, "no such action on that card"))
        self.assertEqual(km._notice_action(iid, "/watch", {}), (False, "no such action on that card"))
        self.assertEqual(km._notice_action("notice:%s:gone:1" % SID, "/send", {}), (False, "that notice is gone"))
        self.assertEqual(km._notice_action("%s:g1" % SID, "/send", {}), (False, "not a notice card"))

    def test_the_target_is_the_notices_own_session_and_the_text_takes_the_plain_message_door(self):
        # the review of PR 1757, high: an older row whose body names another session (written before the check refused it)
        # still delivers to the notice's OWN session; and a stored text never reaches the typed-command router
        row, err = km.post_notice(SID, "k", "t", producer="cli", actions=[{"label": "Send", "route": "/send", "body": {"text": "hello"}}], now=100)
        self.assertIsNone(err)
        rows = _rows(SID); rows[0]["actions"][0]["body"] = {"id": SID2, "name": "api", "text": "hello"}   # a row from before the check
        km._notice_path(SID).write_text("".join(json.dumps(r) + "\n" for r in rows)); km._NOTICE_MEMO.clear()
        iid = "notice:%s:k:1" % SID
        self.assertEqual(km._notice_action(iid, "/send", {"id": SID2, "name": "api", "text": "hello"}), (True, ""))
        self.assertEqual(self.w.delivered, [(SID, "hello")], "the row's sid, never the body's")
        # the plain door: the module's own _deliver_text (saved before the world stubbed it) never consults the command router
        # under plain=True and does under the route's own call
        saved = (km._route_meta_command, km.Sessions.backend_for, km._send_or_park, km._host_for_sid, km._postal_shaped)
        routed, parked = [], []
        try:
            km._route_meta_command = lambda be, sid, text, client=None, floating=False, state=None: (routed.append(text) or False)
            km.Sessions.backend_for = staticmethod(lambda sid: object()); km._host_for_sid = lambda sid: None; km._postal_shaped = lambda t: False
            km._send_or_park = lambda be, sid, text, **kw: (parked.append((sid, text, kw.get("user"))) or True)
            self.assertEqual(_REAL_DELIVER(SID, "/model opus", plain=True), (True, "", True)); self.assertEqual(routed, [], "plain: the router is never consulted")
            self.assertEqual(parked[-1], (SID, "/model opus", True), "the text goes as a message, as the user's words")
            self.assertEqual(_REAL_DELIVER(SID, "/model opus"), (True, "", True)); self.assertEqual(routed, ["/model opus"], "POST /send's own arm consults the router")
        finally:
            (km._route_meta_command, km.Sessions.backend_for, km._send_or_park, km._host_for_sid, km._postal_shaped) = saved

    def test_a_second_click_while_the_first_delivery_is_in_flight_is_refused_not_delivered_twice(self):
        # round three, low c: the pane re-arms on every push and a push the delivery causes can land before the answer
        import threading
        km.post_notice(SID, "k", "t", producer="cli", actions=[{"label": "Send", "route": "/send", "body": {"text": "hello"}}], now=100)
        iid = "notice:%s:k:1" % SID
        hold, started = threading.Event(), threading.Event()
        def slow(sid, text, plain=False):
            started.set(); hold.wait(5); self.w.delivered.append((sid, text)); return True, "", False
        km._deliver_text = slow
        out = {}
        th = threading.Thread(target=lambda: out.setdefault("first", km._notice_action(iid, "/send", {"text": "hello"})), daemon=True); th.start()
        self.assertTrue(started.wait(5), "the first delivery is in flight")
        self.assertEqual(km._notice_action(iid, "/send", {"text": "hello"}), (False, "that action is already in flight"))
        hold.set(); th.join(5)
        self.assertEqual(out.get("first"), (True, "")); self.assertEqual(self.w.delivered, [(SID, "hello")], "one delivery")
        self.assertEqual(km._notice_action(iid, "/send", {"text": "hello"}), (True, ""), "after the answer the action runs again")

    def test_without_dismiss_on_action_the_card_stays(self):
        acts = [{"label": "Send", "route": "/send", "body": {"text": "hello"}}]
        km.post_notice(SID, "k", "t", producer="cli", actions=acts, now=100)
        iid = "notice:%s:k:1" % SID
        self.assertEqual(km._notice_action(iid, "/send", {"text": "hello"}), (True, ""))
        self.assertEqual(self.w.delivered, [(SID, "hello")], "a body without a target delivers to the card's own session")
        self.assertNotIn(iid, km._cleared_ids())
        self.assertEqual(km._notice_action(iid, "/send", {"text": "hello"}), (True, ""), "a card that stays is meant to run again")
        self.assertEqual(len(self.w.delivered), 2)


class Retention(unittest.TestCase):
    def setUp(self): self.w = World()
    def tearDown(self): self.w.close()

    def test_the_sweep_archives_dismissed_expired_and_superseded_rows_and_deletes_none(self):
        km.post_notice(SID, "figure", "first", producer="figure", now=100, t=100)
        km.post_notice(SID, "figure", "second", producer="figure", now=200, t=200)
        km.post_notice(SID, "soon", "expires", producer="figure", now=100, t=100, expires_at=500)
        km.post_notice(SID, "gone", "dismissed", producer="figure", now=100, t=100)
        km.post_notice(SID, "keep", "stays", producer="figure", now=100, t=100)
        km.expire_notice(SID, "keep", now=150)
        km.post_notice(SID, "keep", "stays again", producer="figure", now=160, t=160)
        km._clear_ask("notice:%s:gone:1" % SID)
        before = _rows(SID)
        moved = km._compact_notices(now=600)
        live, arch = _rows(SID), [json.loads(l) for l in (km._notice_archive_dir() / (SID + ".jsonl")).read_text().splitlines()]
        self.assertEqual(moved, len(arch)); self.assertEqual(len(live) + len(arch), len(before), "nothing deleted")
        self.assertEqual(sorted((r["key"], r["rev"], r["op"]) for r in live), [("figure", 2, "post"), ("keep", 2, "post")])
        self.assertEqual(sorted((r["key"], r["rev"], r["op"]) for r in arch),
                         [("figure", 1, "post"), ("gone", 1, "post"), ("keep", 1, "expire"), ("keep", 1, "post"), ("soon", 1, "post")])
        # an acted mark goes with its target's post and not before (Undo may still show the spent card until then)
        km.post_notice(SID, "act", "t", producer="cli", actions=[{"label": "Send", "route": "/send", "body": {"text": "x"}}], dismiss_on_action=True, now=700)
        km._notice_action("notice:%s:act:1" % SID, "/send", {"text": "x"}); km._undo_clear()
        self.assertEqual(km._compact_notices(now=800), 0, "the spent card, visible after Undo, keeps its post and its acted mark")
        km._clear_ask("notice:%s:act:1" % SID)
        self.assertEqual(km._compact_notices(now=900), 2, "dismissed again: the post and its acted mark go together")
        self.assertEqual(km._compact_notices(now=700), 0, "an unmoved file is skipped")
        self.assertEqual([c["itemId"] for c in km._notice_cards(700, km._cleared_ids())], ["notice:%s:keep:2" % SID, "notice:%s:figure:2" % SID], "post order by t")

    def test_undo_restores_a_dismissed_card_the_housekeeping_pass_had_archived(self):
        # round six, high: the archive pass runs inside the housekeeping pass, seconds after a Clear, so Undo must find the
        # card's rows in the archive and move them back (the reference: Clear; Undo restores it)
        km.post_notice(SID, "figure", "first", producer="figure", now=100, t=100)
        iid = "notice:%s:figure:1" % SID
        self.assertEqual(km._compact_notices(now=200), 0, "a live card stays")
        km._clear_ask(iid)
        self.assertEqual(km._compact_notices(now=300), 1, "the pass archives the dismissed row")
        self.assertEqual(_rows(SID), [], "gone from the live file")
        self.assertEqual(km._undo_clear(), {}, "no fault")
        self.assertNotIn(iid, km._cleared_ids())
        self.assertEqual([c["itemId"] for c in km._notice_cards(400, km._cleared_ids())], [iid], "post, pass, Clear, pass, Undo: the card is back")
        self.assertEqual([(r["key"], r["rev"], r["op"]) for r in _rows(SID)], [("figure", 1, "post")], "its row is live again")
        self.assertEqual((km._notice_archive_dir() / (SID + ".jsonl")).read_text(), "", "moved back, not copied")
        self.assertEqual(km._compact_notices(now=500), 0, "restored and undismissed: the pass keeps it")
        # the one-shot mark rides back with its post: a spent card returns spent, and a click delivers nothing
        acts = [{"label": "Send", "route": "/send", "body": {"text": "x"}}]
        km.post_notice(SID, "act", "t", producer="cli", actions=acts, dismiss_on_action=True, now=600, t=600)
        aid = "notice:%s:act:1" % SID
        self.assertEqual(km._notice_action(aid, "/send", {"text": "x"}), (True, ""))
        self.assertEqual(km._compact_notices(now=700), 2, "the post and its acted mark are archived together")
        km._undo_clear()
        back = next(c for c in km._notice_cards(800, km._cleared_ids()) if c["itemId"] == aid)
        self.assertEqual((back["notice"]["acted"], back["notice"]["actions"]), (True, []), "back spent")
        self.assertEqual(km._notice_action(aid, "/send", {"text": "x"}), (False, "that card's action ran already"))
        self.assertEqual(self.w.delivered, [(SID, "x")], "one delivery across click, Clear, pass, Undo, click")
        # Undo walks back one batch a press, so an older batch's rows must come back from the archive too, not the newest's alone
        km._clear_ask(iid); km._clear_ask(aid)
        self.assertEqual(km._compact_notices(now=900), 3)
        km._undo_clear()
        self.assertEqual([c["itemId"] for c in km._notice_cards(1000, km._cleared_ids())], [aid], "the newest batch first")
        km._undo_clear()
        self.assertEqual(sorted(c["itemId"] for c in km._notice_cards(1100, km._cleared_ids())), sorted([iid, aid]), "then the older")

    def test_a_repost_under_a_dismissed_key_takes_the_next_revision_once_the_pass_archived_the_first(self):
        # round six, medium: the revision counted the live file alone, so a repost after the pass took rev 1 again, an id the
        # cleared ledger still held: the projection dropped it while the producer was told the card was up
        km.post_notice(SID, "figure", "first", producer="figure", now=100, t=100)
        km._clear_ask("notice:%s:figure:1" % SID)
        self.assertEqual(km._compact_notices(now=200), 1)
        row, err = km.post_notice(SID, "figure", "second", producer="figure", now=300, t=300)
        self.assertEqual((err, row["rev"]), (None, 2), "post, dismiss, pass, repost: rev 2")
        self.assertEqual([c["itemId"] for c in km._notice_cards(400, km._cleared_ids())], ["notice:%s:figure:2" % SID], "the card shows")
        # the count follows the rows wherever they sit: Undo moves rev 1 back live (superseded by rev 2), a third post is rev 3
        km._undo_clear()
        self.assertEqual([c["itemId"] for c in km._notice_cards(500, km._cleared_ids())], ["notice:%s:figure:2" % SID], "rev 1 back but superseded")
        row, err = km.post_notice(SID, "figure", "third", producer="figure", now=600, t=600)
        self.assertEqual((err, row["rev"]), (None, 3))
        # an archive that cannot be read refuses the post with its reason, never a revision minted blind
        km._clear_ask("notice:%s:figure:3" % SID); self.assertEqual(km._compact_notices(now=700), 3)
        ap = km._notice_archive_dir() / (SID + ".jsonl"); ap.unlink(); ap.mkdir()
        row, err = km.post_notice(SID, "figure", "fourth", producer="figure", now=800)
        self.assertEqual(row, None); self.assertIn("the notice archive could not be read", err)
        ap.rmdir()

    def test_an_unreadable_archive_keeps_the_undo_owed_and_says_so(self):
        km.post_notice(SID, "figure", "first", producer="figure", now=100, t=100)
        iid = "notice:%s:figure:1" % SID
        km._clear_ask(iid); self.assertEqual(km._compact_notices(now=200), 1)
        ap = km._notice_archive_dir() / (SID + ".jsonl"); saved = ap.read_text(); ap.unlink(); ap.mkdir()
        faults = km._undo_clear()
        self.assertEqual(list(faults), ["notice:" + SID], "keyed apart from a goals-file fault"); self.assertIn("the notice archive could not be read", faults["notice:" + SID])
        self.assertIn(iid, km._cleared_ids(), "re-journaled: the batch stays owed for the next Undo")
        self.assertEqual(km._notice_cards(300, km._cleared_ids()), [], "nothing restored blind")
        # the refusal is worded per store (round six, low): the notice archive's fault says notice cards and names the session,
        # never that none of its cards came back; a goals-file fault keeps its own sentence
        sent = []; client = {"send": lambda m: sent.append(json.loads(m))}
        km._gesture_store_refusal(client, "undo", faults)
        self.assertEqual((sent[0]["type"], sent[0]["sid"]), ("err", SID))
        self.assertIn("notice cards were not restored", sent[0]["text"]); self.assertIn("notice archive", sent[0]["text"])
        self.assertNotIn("goals file", sent[0]["text"]); self.assertIn("Its other cards and the other sessions were not affected", sent[0]["text"])
        km._gesture_store_refusal(client, "undo", {SID: "a goals fault"})
        self.assertIn("goals file (a goals fault)", sent[1]["text"]); self.assertNotIn("notice", sent[1]["text"])
        ap.rmdir(); ap.write_text(saved)
        self.assertEqual(km._undo_clear(), {})
        self.assertEqual([c["itemId"] for c in km._notice_cards(400, km._cleared_ids())], [iid], "the next Undo restores it")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads through chmod 0; the permission fault needs a real one")
    def test_an_unreadable_archive_directory_refuses_the_post_rather_than_minting_a_revision_blind(self):
        # round six, low: the stat helper folds a FAILED stat into None, the absent-file answer, so with the archive directory
        # unreadable a repost minted rev 1 blind and reported success on an invisible card; the stat is explicit now
        km.post_notice(SID, "figure", "first", producer="figure", now=100, t=100)
        km._clear_ask("notice:%s:figure:1" % SID); self.assertEqual(km._compact_notices(now=200), 1)
        ad = km._notice_archive_dir(); ap = ad / (SID + ".jsonl")
        try:
            os.chmod(ad, 0)                                   # the directory: the file's stat fails, which is not an absent file
            row, err = km.post_notice(SID, "figure", "second", producer="figure", now=300)
            self.assertEqual(row, None); self.assertIn("the notice archive could not be read", err)
        finally:
            os.chmod(ad, 0o755)
        try:
            os.chmod(ap, 0)                                   # the file: its stat reads, its bytes do not
            row, err = km.post_notice(SID, "figure", "second", producer="figure", now=300)
            self.assertEqual(row, None); self.assertIn("the notice archive could not be read", err)
        finally:
            os.chmod(ap, 0o644)
        row, err = km.post_notice(SID, "figure", "second", producer="figure", now=300)
        self.assertEqual((err, row["rev"]), (None, 2), "readable again: the count resumes")

    def test_the_pass_reads_the_ledger_under_the_lock_so_an_undo_landing_during_it_is_not_archived_back_out(self):
        # round six, low: the pass snapshotted the cleared ledger once before its per-session loop, so an Undo that landed
        # while it walked an earlier session had its restored row archived back out under the stale snapshot, and no later
        # Undo could reach it; the ledger is read per session, under the lock, after the file's stat
        km.post_notice(SID, "figure", "first", producer="figure", now=100, t=100)
        iid = "notice:%s:figure:1" % SID
        km._clear_ask(iid); self.assertEqual(km._compact_notices(now=200), 1)
        real, fired = km._stat_key, []
        def stat_then_undo(path):
            if not fired and Path(path) == km._notice_path(SID):   # the pass reaches this session's file: the Undo lands first
                fired.append(1); km._undo_clear()
            return real(path)
        km._stat_key = stat_then_undo
        try:
            moved = km._compact_notices(now=300)
        finally:
            km._stat_key = real
        self.assertEqual(fired, [1]); self.assertEqual(moved, 0, "the restored row stays: the ledger was read after the Undo")
        self.assertEqual([c["itemId"] for c in km._notice_cards(400, km._cleared_ids())], [iid], "the card is on the board")
        self.assertEqual((km._notice_archive_dir() / (SID + ".jsonl")).read_text(), "", "and not in the archive")

    def test_the_memo_is_bounded_by_bytes_as_a_fraction_of_memory_with_the_environment_override(self):
        saved = km._mem_total_bytes
        try:
            km._mem_total_bytes = lambda: 8 * 1024 ** 3
            os.environ.pop("ROMP_NOTICE_MEMO_BYTES", None)
            self.assertEqual(km._notice_memo_bound(), 32 * 1024 * 1024)
            os.environ["ROMP_NOTICE_MEMO_BYTES"] = "4096"; self.assertEqual(km._notice_memo_bound(), 4096)
            os.environ["ROMP_NOTICE_MEMO_BYTES"] = "0"; self.assertEqual(km._notice_memo_bound(), 32 * 1024 * 1024, "zero is not a bound")
            os.environ["ROMP_NOTICE_MEMO_BYTES"] = "lots"; self.assertEqual(km._notice_memo_bound(), 32 * 1024 * 1024)
        finally:
            km._mem_total_bytes = saved; os.environ.pop("ROMP_NOTICE_MEMO_BYTES", None)
        km.post_notice(SID, "k", "t", producer="cli", now=100)
        km._notice_rows(SID); km._notice_rows(SID)
        rep = km._notice_memo_report()
        self.assertEqual(set(rep), {"entries", "bytes", "bound", "hit", "miss", "evicted"})
        self.assertEqual((rep["entries"], rep["bound"]), (1, km.NOTICE_MEMO_BYTES)); self.assertGreaterEqual(rep["hit"], 1)
        saved_bound = km.NOTICE_MEMO_BYTES
        try:
            km.NOTICE_MEMO_BYTES = 1                    # a bound smaller than one file: the entry is shed after the read, not kept
            km.post_notice(SID2, "k", "t", producer="cli", now=100)
            km._notice_rows(SID2)
            self.assertEqual(km._notice_memo_report()["entries"], 0, "over the bound the largest goes first")
        finally:
            km.NOTICE_MEMO_BYTES = saved_bound


class TheDoors(unittest.TestCase):
    """POST /notice in /watch's shape, the backend's hook, and the boot wiring pin."""
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), km.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self): self.w = World()
    def tearDown(self): self.w.close()

    def _post(self, body, token=True):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Romp-Token"] = os.environ["ROMP_SERVE_TOKEN"]
        req = urllib.request.Request("http://127.0.0.1:%d/notice" % self.port, data=body if isinstance(body, bytes) else json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            raw = e.read().decode() or "{}"
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"raw": raw}

    def test_the_route_answers_in_the_watch_shape(self):
        self.assertNotEqual(self._post({"id": SID, "key": "k", "title": "t"}, token=False)[0], 200, "no token: refused")
        st, r = self._post(b"[]"); self.assertEqual(st, 400)
        st, r = self._post({"id": SID, "title": "t"}); self.assertEqual(st, 400); self.assertIn("key, title and id|name", r["error"])
        st, r = self._post({"id": SID, "key": "bad key", "title": "t"}); self.assertEqual((st, r["ok"]), (200, False)); self.assertIn("the key must match", r["error"])
        st, r = self._post({"id": "99999999-2222-3333-4444-555555555555", "key": "k", "title": "t"}); self.assertEqual((st, r["ok"]), (200, False)); self.assertIn("no session answers", r["error"])
        st, r = self._post({"id": SID, "key": "k", "title": "t", "actions": [{"label": "x", "route": "/watch", "body": {}}]}); self.assertEqual(r["ok"], False); self.assertIn("not allowed", r["error"])
        st, r = self._post({"id": SID, "key": "k", "title": "t", "attachment": "/nowhere.png"}); self.assertEqual(r["ok"], False); self.assertIn("attachment refused", r["error"])
        st, r = self._post({"id": SID, "key": "figure", "title": "posted over http", "body": "the body", "producer": "http-test", "needsYou": True})
        self.assertEqual((st, r["ok"]), (200, True)); n = r["notice"]
        self.assertEqual((n["sid"], n["key"], n["rev"], n["needsYou"], n["producer"], n["title"]), (SID, "figure", 1, True, "http-test", "posted over http"))
        st, r = self._post({"id": SID, "key": "figure", "title": "again"}); self.assertEqual((r["ok"], r["notice"]["rev"], r["notice"]["producer"]), (True, 2, "http"))
        saved = (km.Sessions.live, km._live_names)
        try:                                            # a LIVE session's name resolves, as on every name-keyed route
            km.Sessions.live = staticmethod(lambda: {SID: {"state": "waiting"}}); km._live_names = lambda live: {"web": SID}
            st, r = self._post({"name": "web", "key": "byname", "title": "by name"}); self.assertEqual((r["ok"], r["notice"]["sid"]), (True, SID))
        finally:
            km.Sessions.live, km._live_names = saved
        st, r = self._post({"id": SID, "expire": "figure"}); self.assertEqual((st, r["ok"], r["notice"]["op"], r["notice"]["rev"]), (200, True, "expire", 2))
        st, r = self._post({"id": SID, "expire": "never"}); self.assertEqual(r["ok"], False)

    def test_the_backend_helper_resolves_the_hook_defensively_and_the_kernel_wires_it_at_boot(self):
        class Bare(sb.SdkBackend):                 # a stand-in class carrying no hook, as the backend's own tests bind
            def __init__(self): pass
        be = Bare()
        self.assertEqual(be.post_notice(SID, "k", "t", producer="dropped-sends"), (None, "no notice door is wired on this backend (the kernel wires on_notice at boot)"))
        calls = []
        Bare.on_notice = staticmethod(lambda sid, key, title, body="", **kw: (calls.append((sid, key, title, body, kw)) or ({"rev": 1}, None)))
        self.assertEqual(be.post_notice(SID, "k", "t", "b", producer="dropped-sends", needs_you=True), ({"rev": 1}, None))
        self.assertEqual(calls, [(SID, "k", "t", "b", {"producer": "dropped-sends", "needs_you": True})])
        Bare.on_notice = staticmethod(lambda *a, **k: 1 / 0)
        self.assertIn("could not be posted", be.post_notice(SID, "k", "t", producer="x")[1])
        self.assertIn("type(_sdk_backend).on_notice = staticmethod(post_notice)", KSRC, "the boot wiring, beside the model-fallback hook")
        self.assertIn('asks.extend(_notice_cards(now, cleared))', KSRC, "the feed attaches the family after the quarantine cards")
        self.assertIn('("notices", _notice_memo_report)', KSRC, "/perf reports the memo")
        self.assertIn('_nmoved = _compact_notices()', KSRC, "the retention pass runs beside the goal-store sweep")


if __name__ == "__main__":
    unittest.main()
