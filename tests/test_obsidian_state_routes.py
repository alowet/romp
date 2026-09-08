#!/usr/bin/env python3
"""POST /flag, /views and /order (2026-09-08): the Obsidian timeline panel's three state writes as
kernel routes. The panel runs in Obsidian's Electron with Node's fs and the state dir and has no
socket to the kernel, so it used to write session-flags.json, timeline-views.json and
session-order.json itself -- a second writer beside the kernel, bypassing the views judge and its
stale-writer guard, the flags setter's lock, and the order merge. Each route lands through the SAME
setter its socket op calls (setSessionFlag / setTimelineViews / reorderTabs in _dispatch_ws), with
that op's validation, and refuses the way it refuses; the tests here drive the REAL Handler over
HTTP (the test_tag_route.py pattern) and, where a refusal is claimed to match the socket op's, drive
the socket op too and compare. Synthetic only."""
import contextlib
import errno
import inspect
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
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")

# Hermetic state BEFORE the loads -- they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
SourceFileLoader("romp_event_model", os.path.join(BIN, "romp-event-model")).load_module()
SourceFileLoader("romp_judge", os.path.join(BIN, "romp-judge")).load_module()
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "test-token-DO-NOT-USE")
km = SourceFileLoader("romp_kernel_osr", os.path.join(BIN, "romp-kernel")).load_module()

SID = "11111111-2222-3333-4444-555555555555"
SID2 = "22222222-3333-4444-5555-666666666666"
OTHER = "99999999-8888-7777-6666-555555555555"
A, B, C, D = ("aaaaaaaa-1111-2222-3333-444444444444", "bbbbbbbb-1111-2222-3333-444444444444",
              "cccccccc-1111-2222-3333-444444444444", "dddddddd-1111-2222-3333-444444444444")


@contextlib.contextmanager
def _reads_fault(target):
    """Fail every byte read of ONE path with an EIO for the duration of the block (the
    tests/test_kernel_session_flags.py injector); everything else reads normally."""
    real_rb, real_rt = Path.read_bytes, Path.read_text
    tgt = str(target)

    def rb(self, *a, **k):
        if str(self) == tgt:
            raise OSError(errno.EIO, "injected EIO")
        return real_rb(self, *a, **k)

    def rt(self, *a, **k):
        if str(self) == tgt:
            raise OSError(errno.EIO, "injected EIO")
        return real_rt(self, *a, **k)
    Path.read_bytes, Path.read_text = rb, rt
    try:
        yield
    finally:
        Path.read_bytes, Path.read_text = real_rb, real_rt


class _Routes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), km.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self._state = km.jd.STATE
        km.jd.STATE = Path(self.td.name)
        km._flags_cache.clear()
        self._saved = (km._mark_views_dirty, km._sync_notice)
        self.dirty, self.notices = [], []
        km._mark_views_dirty = lambda: self.dirty.append(1)
        km._sync_notice = lambda text, ok=True, **kw: self.notices.append((text, ok))

    def tearDown(self):
        km._mark_views_dirty, km._sync_notice = self._saved
        km.jd.STATE = self._state
        km._flags_cache.clear()
        self.td.cleanup()

    def _post(self, path, body=None, raw=None, token=os.environ["ROMP_SERVE_TOKEN"]):
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-Romp-Token"] = token
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path),
                                     data=(raw if raw is not None else json.dumps(body).encode()),
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            text = e.read().decode()
            try:
                return e.code, json.loads(text)
            except ValueError:
                return e.code, text

    def _ws(self, msg):
        """The socket op, through the real dispatcher; the frames it answered on the poster's socket."""
        sent = []
        client = {"app": "timeline", "wid": "w-obs", "alive": True,
                  "send": lambda raw: sent.append(json.loads(raw))}
        km.Handler._dispatch_ws(object.__new__(km.Handler), msg, client)
        return sent


class FlagRoute(_Routes):

    def _flags_file(self):
        p = km.jd.STATE / "session-flags.json"
        return json.loads(p.read_text()) if p.exists() else None

    def test_a_toggle_lands_through_the_setter_and_unsets_the_way_it_does(self):
        st, r = self._post("/flag", {"id": SID, "flag": "hideFromFeed", "value": True})
        self.assertEqual((st, r), (200, {"ok": True, "id": SID, "flag": "hideFromFeed", "value": True}))
        self.assertEqual(self._flags_file(), {SID: {"hideFromFeed": True}}, "the store the kernel reads holds it")
        self.assertTrue(km._session_flag(SID, "hideFromFeed"))
        self.assertEqual(self.dirty, [1], "the views push is poked, as after the socket op")
        st, r = self._post("/flag", {"id": SID, "flag": "hideFromFeed", "value": False})
        self.assertEqual((st, r["ok"]), (200, True))
        self.assertEqual(self._flags_file(), {}, "off drops the entry -- _set_session_flag's pop, not a stored false")

    def test_the_bell_rides_its_own_tri_state_setter(self):
        st, r = self._post("/flag", {"id": SID, "flag": "notify", "value": True})
        self.assertEqual((st, r["ok"]), (200, True))
        self.assertIs(km._session_flag_raw(SID, "notify"), True, "an override on the (off) master is stored")
        st, r = self._post("/flag", {"id": SID, "flag": "notify", "value": False})
        self.assertEqual((st, r["ok"]), (200, True))
        self.assertIsNone(km._session_flag_raw(SID, "notify"), "back to the master's value: the override is dropped, not stored as false")

    def test_a_non_boolean_or_missing_value_is_a_400_that_writes_nothing(self):
        for value, needle in (("false", "'value' must be true or false"), (0, "'value' must be true or false"),
                              (None, "value (true or false) required")):
            body = {"id": SID, "flag": "hideFromFeed"}
            if value is not None:
                body["value"] = value
            st, r = self._post("/flag", body)
            self.assertEqual(st, 400, (value, r))
            self.assertFalse(r["ok"])
            self.assertIn(needle, r["error"])
        st, r = self._post("/flag", {"id": SID, "flag": "hideFromFeed", "value": None})
        self.assertEqual((st, r["error"]), (400, "value (true or false) required"), "an explicit null is not a value either")
        self.assertIsNone(self._flags_file(), "bool('false') must never UNDO a mute -- nothing was written")
        self.assertEqual(self.dirty, [])

    def test_an_unknown_flag_key_or_a_missing_id_is_a_400_naming_it(self):
        st, r = self._post("/flag", {"id": SID, "flag": "autoNudgeOff", "value": True})
        self.assertEqual(st, 400)
        self.assertEqual(r["error"], 'flag must be one of hideFromFeed, postalServiceOff, notify, got "autoNudgeOff"')
        st, r = self._post("/flag", {"id": SID, "flag": "hideFromFeed", "value": True, "target": "web"})
        self.assertEqual(st, 400)
        self.assertEqual(r["error"], "unknown key(s) 'target' — this route reads only 'id', 'flag', 'value'")
        st, r = self._post("/flag", {"flag": "hideFromFeed", "value": True})
        self.assertEqual((st, r["error"]), (400, "id (the session's id) required"))
        self.assertIsNone(self._flags_file())

    def test_a_store_fault_answers_the_socket_ops_refusal_and_leaves_the_file_alone(self):
        km._set_session_flag(OTHER, "postalServiceOff", True)     # a populated store: a safety boundary
        km._flags_cache.clear()
        p = km.jd.STATE / "session-flags.json"
        before = p.read_bytes()
        with _reads_fault(p):
            st, r = self._post("/flag", {"id": SID, "flag": "hideFromFeed", "value": True})
            ws = self._ws({"type": "setSessionFlag", "id": SID, "flag": "hideFromFeed", "value": True})
        self.assertEqual(st, 200, "the kernel's own refusal is a 200 with ok:false, like every route's")
        self.assertFalse(r["ok"])
        self.assertIn("couldn't save that setting", r["error"])
        self.assertIn("session-flags.json could not be read", r["error"])
        self.assertIs(r["value"], False, "the value the display path still paints rides along (the settingRefused field)")
        self.assertEqual(len(ws), 1)
        self.assertEqual(ws[0]["type"], "settingRefused")
        self.assertEqual(ws[0]["text"], r["error"], "word for word the socket op's refusal")
        self.assertEqual(ws[0]["value"], r["value"])
        self.assertEqual(p.read_bytes(), before, "the flags file is byte-for-byte unchanged")
        self.assertEqual(self.dirty, [], "a refused write marks nothing dirty")


class ViewsRoute(_Routes):

    def setUp(self):
        super().setUp()
        try:
            km._views_path().unlink()
        except OSError:
            pass

    def _seed(self):
        t, err = km._edit_tag("web", add=[SID])
        self.assertIsNone(err)
        self.dirty.clear()
        return km._views_client()

    def test_a_clean_write_lands_through_the_judge_and_answers_the_viewsack_document(self):
        served = self._seed()
        nv = json.loads(json.dumps(served))
        nv["actives"] = {"timeline": {"tags": ["web"]}}                # a lens edit, built from the echo
        st, r = self._post("/views", {"views": nv, "edited": [], "writeId": "w1"})
        self.assertEqual(st, 200)
        self.assertEqual((r["type"], r["writeId"], r["ok"], r["refused"]), ("viewsAck", "w1", True, []))
        self.assertEqual(r["views"]["actives"]["timeline"], {"tags": ["web"]})
        self.assertIsInstance(r["seq"], int)
        self.assertNotIn("error", r)
        stored = json.loads(km._views_path().read_text())
        self.assertEqual(stored["seq"], r["seq"], "the store carries the judge's stamp -- the write went through the one door")
        self.assertEqual(stored["actives"]["timeline"], {"tags": ["web"]})
        self.assertEqual(self.dirty, [1])
        self.assertEqual(self.notices, [])

    def test_a_stale_copy_is_refused_exactly_as_the_socket_op_refuses_it(self):
        served = self._seed()
        tid = served["tags"][0]["id"]
        stale = json.loads(json.dumps(served))                           # this panel's copy...
        time.sleep(1.1)                                                  # int-second stamps: land in a later second
        t, err = km._edit_tag("web", add=[SID2])                         # ...then another writer adds a member
        self.assertIsNone(err)
        stale["actives"] = {"timeline": {"tags": ["web"]}}               # the stale panel changes its lens...
        stale["tags"][0]["members"] = []                                 # ...and its copy of web has no members
        st, r = self._post("/views", {"views": stale, "edited": [tid], "writeId": "w2"})
        self.assertEqual((st, r["type"], r["writeId"], r["ok"]), (200, "viewsAck", "w2", False))
        self.assertEqual([x["name"] for x in r["refused"]], ["web"])
        self.assertIn("predates", r["refused"][0]["reason"])
        self.assertIn('"web"', r["error"], "one plain sentence the dialog shows as-is")
        v = r["views"]
        self.assertEqual(sorted(next(x for x in v["tags"] if x["id"] == tid)["members"]), sorted([SID, SID2]),
                         "the store's newer members stand -- the guard judged this write")
        self.assertEqual(v["actives"]["timeline"], {"tags": ["web"]}, "the rest of the write (the lens) landed")
        # the SAME stale copy through the socket op: the same verdict, the same words, the same document
        ws = self._ws({"type": "setTimelineViews", "writeId": "w3", "views": stale, "edited": [tid]})
        self.assertEqual(len(ws), 1)
        a = ws[0]
        self.assertEqual((a["type"], a["ok"]), ("viewsAck", False))
        self.assertEqual(a["error"], r["error"])
        self.assertEqual([x["name"] for x in a["refused"]], [x["name"] for x in r["refused"]])
        self.assertEqual(set(a) - {"writeId"}, set(r) - {"writeId"}, "one document, whichever door it came through")

    def test_a_setter_exception_is_the_socket_arms_refusal_word_for_word(self):
        self._seed()
        real = km._set_timeline_views

        def boom(blob, **kw):
            raise RuntimeError("disk on fire")
        km._set_timeline_views = boom
        try:
            st, r = self._post("/views", {"views": {"active": "all", "tags": []}, "writeId": "w1"})
            ws = self._ws({"type": "setTimelineViews", "writeId": "w1", "views": {"active": "all", "tags": []}})
        finally:
            km._set_timeline_views = real
        self.assertEqual((st, r["ok"], r["refused"]), (200, False, []))
        self.assertEqual(r["error"], "the write failed on the kernel: disk on fire")
        self.assertEqual(ws[0]["error"], r["error"])
        self.assertIsInstance(r["views"], dict, "the store's blob rides the refusal, for the panel to revert to")

    def test_a_non_object_views_field_or_an_unknown_key_is_a_400(self):
        st, r = self._post("/views", {"views": "not-a-dict"})
        self.assertEqual((st, r["error"]), (400, 'views (an object) required, got "not-a-dict"'))
        st, r = self._post("/views", {"views": {"active": "all", "tags": []}, "target": "x"})
        self.assertEqual(st, 400)
        self.assertEqual(r["error"], "unknown key(s) 'target' — this route reads only 'views', 'edited', 'writeId'")
        self.assertFalse(km._views_path().exists(), "nothing was written")
        self.assertEqual(self.dirty, [])


class OrderRoute(_Routes):

    def _order_file(self):
        return json.loads((km.jd.STATE / "session-order.json").read_text())

    def test_the_merge_keeps_the_slots_of_lanes_the_drag_did_not_carry(self):
        km._write_session_order([A, B, C])
        st, r = self._post("/order", {"order": [C, A]})
        self.assertEqual((st, r), (200, {"ok": True, "order": [C, B, A]}))
        self.assertEqual(self._order_file(), [C, B, A], "B kept its slot -- the merge, never the whole-file overwrite")
        self.assertEqual(self.dirty, [1])

    def test_a_sid_the_store_does_not_know_lands_where_the_merge_puts_it(self):
        km._write_session_order([A, B, C])
        st, r = self._post("/order", {"order": [D, A]})
        self.assertEqual((st, r["order"]), (200, [D, B, C, A]))
        self.assertEqual(self._order_file(), [D, B, C, A], "the new sid takes the dragged slot; the displaced one appends")

    def test_a_non_list_a_non_string_entry_or_an_unknown_key_is_a_400(self):
        km._write_session_order([A, B, C])
        self.dirty.clear()
        st, r = self._post("/order", {"order": "abc"})
        self.assertEqual((st, r["error"]), (400, 'order (a list of session ids) required, got "abc"'))
        st, r = self._post("/order", {"order": [A, 7]})
        self.assertEqual(st, 400)
        self.assertIn("order (a list of session ids) required", r["error"])
        st, r = self._post("/order", {"order": [A], "surface": "lanes"})
        self.assertEqual((st, r["error"]), (400, "unknown key(s) 'surface' — this route reads only 'order'"))
        self.assertEqual(self._order_file(), [A, B, C], "nothing was written")
        self.assertEqual(self.dirty, [])

    def test_a_store_fault_answers_the_socket_ops_refusal_and_leaves_the_file_alone(self):
        km._write_session_order([A, B, C])
        p = km.jd.STATE / "session-order.json"
        before = p.read_bytes()
        self.dirty.clear()
        with _reads_fault(p):
            st, r = self._post("/order", {"order": [C, A]})
            ws = self._ws({"type": "reorderTabs", "order": [C, A]})
        self.assertEqual((st, r["ok"]), (200, False))
        self.assertIn("couldn't save the new order", r["error"])
        self.assertIn("session-order.json could not be read", r["error"])
        self.assertEqual(ws[0]["type"], "settingRefused")
        self.assertEqual(ws[0]["text"], r["error"], "word for word the socket op's refusal")
        self.assertEqual(p.read_bytes(), before, "never spliced against a fabricated [] and persisted")
        self.assertEqual(self.dirty, [])


class BodiesAndAuth(_Routes):

    def test_a_non_object_body_is_the_typed_400_on_every_route(self):
        for path in ("/flag", "/views", "/order"):
            st, r = self._post(path, raw=b"[1]")
            self.assertEqual((st, r), (400, {"ok": False, "error": "body must be a JSON object, got [1]"}), path)
            st, r = self._post(path, raw=b"nope")
            self.assertEqual((st, r), (400, {"ok": False, "error": "body is not JSON"}), path)

    def test_a_missing_or_wrong_token_is_refused_before_the_body_is_read(self):
        for path, body in (("/flag", {"id": SID, "flag": "hideFromFeed", "value": True}),
                           ("/views", {"views": {"active": "all", "tags": []}}),
                           ("/order", {"order": [A]})):
            for tok in (None, "not-the-token"):
                st, r = self._post(path, body, token=tok)
                self.assertEqual(st, 403, (path, tok, r))
                self.assertIn("forbidden", r)
        self.assertFalse((km.jd.STATE / "session-flags.json").exists())
        self.assertFalse(km._views_path().exists())
        self.assertFalse((km.jd.STATE / "session-order.json").exists())


class PortRecord(unittest.TestCase):
    """The panel learns the kernel's port from the kernel's OWN record, written once the socket is
    bound -- never from a guess (an Electron app launched from the dock sees no shell's
    ROMP_KERNEL_PORT) -- and beside the serve-token file it already reads."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self._state = km.jd.STATE
        km.jd.STATE = Path(self.td.name)

    def tearDown(self):
        km.jd.STATE = self._state
        self.td.cleanup()

    def test_the_record_is_the_bound_port_one_line(self):
        km._persist_serve_port(12345)
        self.assertEqual((km.jd.STATE / "serve-port").read_text(), "12345\n")
        km._persist_serve_port(29855)
        self.assertEqual((km.jd.STATE / "serve-port").read_text(), "29855\n", "a restart on another port rewrites it")

    def test_main_writes_it_right_after_the_bind_succeeds(self):
        src = inspect.getsource(km.main)
        bind = src.index("srv = ThreadingHTTPServer((BIND, PORT), Handler)")
        rec = src.index("_persist_serve_port(srv.server_address[1])")
        self.assertLess(bind, rec, "the record follows the bind")
        between = src[bind:rec].split("\n")[1:]
        self.assertTrue(all(not ln.strip() or ln.strip().startswith("#") for ln in between),
                        "...immediately: a failed bind leaves no record that lies")


if __name__ == "__main__":
    unittest.main(verbosity=2)
