#!/usr/bin/env python3
"""Peer kernel payloads are read through a shape, and the page never receives a remote's token (2026-09-08).

Two answers from a PEER kernel cross a tunnel into this kernel and on to the dashboard, and both used to
pass through as they came: tunnels_of relayed a peer's whole /tunnels JSON verbatim (no schema, no bound),
and _poll_remote_version stored whatever /version said as the row's sha and release name (then remotes.json
remembered it). Separately, _remote_public shipped each remote's reusable serve token to every /tunnels
reader and the page put it back into the relay URL — even though _remote_ws already injects that token
itself, so the page never needed it.

Now: tunnels_of returns only `tunnels`, each row re-read through _remote_payload_public_row (a host ssh
would accept, an enumerated status, sha/version shapes, exact booleans, bounded inert text, unknown keys
gone, the count capped); _remote_public publishes `hasToken`; _poll_remote_version drops a sha/version that
does not fit and says so once on stderr; _remote_ws discards the browser's token whether or not the row
has one. Synthetic only: hostname TESTHOST, invented tokens, a stubbed transport, a loopback fake /version.
"""
import contextlib
import io
import inspect
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")

os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "test-token-DO-NOT-USE")
km = SourceFileLoader("romp_kernel_peertext", os.path.join(BIN, "romp-kernel")).load_module()

SID = "11111111-2222-3333-4444-555555555555"
IMG = "<img src=x onerror=alert(1)>"
QUOTE = 'x" onmouseover="alert(1)'
SECRET = "peer-secret-DO-NOT-USE"

# One row of a peer's answer with a hostile or ill-shaped value in EVERY field the panel reads, plus keys
# it never asked for. The host itself is a real one so the row survives and its fields can be inspected.
HOSTILE_ROW = {
    "host": "peerbox", "kernelPort": "29855", "localPort": 70000, "busPort": True,
    "checkin": "yes", "checkinPeer": 1, "token": SECRET, "status": "<b>up</b>",
    "detail": ("d" + IMG) * 400, "sids": [SID, 42, IMG, "x" * 200], "trust": "<i>trusted</i>",
    "kernelSha": "abc" + QUOTE, "localSha": "ABC1234", "kernelVer": "v1" + IMG, "localVer": "v0.2.0+",
    "outOfDate": "true", "behindBy": "2", "aheadBy": 1.5, "kernelDate": "<b>2026-01-01</b>",
    "autoNudge": "false", "settings": {"a<b": 1, "ok": "v", "bad": IMG, "n": 3, "nested": {"x": 1}},
    "fastForward": "yes", "fastPull": None, "askPull": 1,
    "autoPush": {"phase": "<i>pushing</i>", "detail": "p" * 1000, "at": "now", "extra": 1},
    "fails": -3, "nextTry": 10 ** 20, "stale": 0, "lastOk": 1785272930,
    "evil": IMG, "__proto__": {"polluted": True},
}


class _Stubbed(unittest.TestCase):
    def setUp(self):
        self._rkc = km._remote_kernel_call
        self._rem = dict(km._remotes)
        km._remotes.clear()
        km._remotes["TESTHOST"] = {"host": "TESTHOST", "status": "up", "local_port": 1, "token": "t"}

    def tearDown(self):
        km._remote_kernel_call = self._rkc
        km._remotes.clear()
        km._remotes.update(self._rem)

    def _answer(self, body, status=200):
        # the stub's own `payload=` parameter mirrors _remote_kernel_call's signature, so the answer must
        # be bound under another name or the parameter shadows it
        km._remote_kernel_call = lambda r, m, p, payload=None, timeout=8: (status, body, None)


class TunnelsOfIsAWhitelist(_Stubbed):
    def test_every_field_is_read_through_its_shape_and_nothing_else_passes(self):
        self._answer({"tunnels": [HOSTILE_ROW], "known": [{"host": IMG}], "local": {"sha": "abc"},
                      "peerTiers": {"x": IMG}, "autoUpdate": True})
        d = km.tunnels_of("TESTHOST")
        self.assertTrue(d["ok"])
        self.assertEqual(d["of"], "TESTHOST")
        self.assertEqual(set(d), {"ok", "of", "tunnels"}, "only the rows are relayed — the peer's other sections stay behind")
        row = d["tunnels"][0]
        self.assertEqual(row["host"], "peerbox")
        self.assertNotIn("evil", row); self.assertNotIn("__proto__", row); self.assertNotIn("token", row)
        self.assertIs(row["hasToken"], True, "a peer's token collapses to the fact of one")
        self.assertEqual(row["status"], "", "a status word the panel does not know is not a status")
        self.assertEqual(row["trust"], "")
        self.assertEqual(row["kernelSha"], ""); self.assertEqual(row["kernelVer"], "")
        self.assertEqual(row["localSha"], "", "a sha is lowercase hex — the shape, not just the length")
        self.assertEqual(row["localVer"], "v0.2.0+")
        self.assertEqual((row["kernelPort"], row["localPort"], row["busPort"]), (0, 0, 0), "ints in range, or 0")
        for k in ("checkin", "checkinPeer", "outOfDate", "fastForward", "fastPull", "askPull", "stale"):
            self.assertIs(row[k], False, "%s: only True itself is True" % k)
        self.assertIsNone(row["behindBy"]); self.assertIsNone(row["aheadBy"])
        self.assertIsNone(row["autoNudge"])
        self.assertEqual(row["sids"], [SID], "session ids: id-shaped strings only")
        self.assertEqual(row["settings"], {"ok": "v", "n": 3}, "settings: plain keys, inert scalars")
        self.assertEqual(row["autoPush"], {"phase": "", "detail": "p" * 200, "at": 0})
        self.assertEqual((row["fails"], row["nextTry"], row["lastOk"]), (0, 0, 1785272930))
        self.assertLessEqual(len(row["detail"]), 200)
        self.assertEqual(row["kernelDate"], "b2026-01-01/b")
        # the contract the page relies on: no string anywhere in the answer can open a tag or an attribute
        flat = json.dumps(d)
        self.assertNotIn("<", flat); self.assertNotIn(">", flat); self.assertNotIn('\\"', flat)
        self.assertNotIn(SECRET, flat)

    def test_a_well_formed_row_survives_intact_so_the_expand_loses_nothing(self):
        good = {"host": "peerbox", "kernelPort": 29855, "localPort": 51000, "busPort": 51001,
                "checkin": False, "checkinPeer": True, "hasToken": True, "status": "up", "detail": "fine",
                "sids": [SID], "trust": "trusted", "kernelSha": "abc1234", "localSha": "def5678",
                "kernelVer": "v0.1.3", "localVer": "v0.2.0+", "outOfDate": True, "behindBy": 2, "aheadBy": 0,
                "kernelDate": "2026-08-11", "autoNudge": False, "settings": {"autoNudge": False, "theme": "dark"},
                "fastForward": True, "fastPull": False, "askPull": True,
                "autoPush": {"phase": "pushing", "detail": "sending", "at": 1785272930},
                "fails": 3, "nextTry": 1785272990, "stale": False, "lastOk": 1785272930}
        self._answer({"tunnels": [good]})
        self.assertEqual(km.tunnels_of("TESTHOST")["tunnels"], [good])

    def test_rows_without_a_usable_host_are_dropped_and_counted_and_the_count_is_capped(self):
        rows = [{"host": IMG, "status": "up"}, {"host": QUOTE}, {"host": "-oProxyCommand=x"}, "not a row", None]
        rows += [{"host": "h%d" % i, "status": "up"} for i in range(500)]
        self._answer({"tunnels": rows})
        km._peer_shape_said.clear()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            d = km.tunnels_of("TESTHOST")
            km.tunnels_of("TESTHOST")
        self.assertTrue(d["ok"])
        self.assertEqual(len(d["tunnels"]), km._PEER_TUNNELS_MAX)
        self.assertEqual(d["dropped"], 5, "rows with no host ssh would accept are counted for the panels' note")
        self.assertEqual(err.getvalue().count("\n"), 1, "…and said on stderr ONCE per host, not per read")
        self.assertIn("TESTHOST answered /tunnels with 5 rows without a usable host", err.getvalue())
        self.assertTrue(all(km._safe_ssh_host(r["host"]) for r in d["tunnels"]))
        self.assertEqual(d["tunnels"][0]["host"], "h0", "the drop does not eat the valid rows' places")
        km._peer_shape_said.clear()

    def test_a_dirty_worktree_sha_is_a_sha_in_a_peers_row_too(self):
        # _kernel_sha appends '-dirty' on an uncommitted worktree and the rest of this file reads through it
        # (_sha_base); a whitelist that refused it would blank a legitimately dirty peer's build (review find)
        self._answer({"tunnels": [{"host": "peerbox", "status": "up", "kernelSha": "abc1234-dirty",
                                   "localSha": "a" * 40 + "-dirty"}]})
        row = km.tunnels_of("TESTHOST")["tunnels"][0]
        self.assertEqual((row["kernelSha"], row["localSha"]), ("abc1234-dirty", "a" * 40 + "-dirty"))
        for bad in ("abc1234-DIRTY", "abc1234-dirty-dirty", "-dirty", "abc1234-clean", "abc1234 -dirty"):
            with self.subTest(sha=bad):
                self.assertEqual(km._peer_sha(bad), "", "only the one suffix _kernel_sha writes")

    def test_a_tunnels_that_is_not_a_list_is_a_loud_error(self):
        for bad in ({"tunnels": {"host": "x"}}, {"tunnels": "x"}, {"tunnels": None}, {}):
            with self.subTest(payload=bad):
                self._answer(bad)
                d = km.tunnels_of("TESTHOST")
                self.assertFalse(d["ok"])
                self.assertIn("without a list of tunnels", d["error"])
                self.assertIn("TESTHOST", d["error"])

    def test_a_peer_token_in_a_row_never_reaches_the_answer(self):
        self._answer({"tunnels": [{"host": "peerbox", "token": SECRET, "status": "up"}]})
        d = km.tunnels_of("TESTHOST")
        self.assertNotIn(SECRET, json.dumps(d))
        self.assertIs(d["tunnels"][0]["hasToken"], True)
        self._answer({"tunnels": [{"host": "peerbox", "token": "", "status": "up"}]})
        self.assertIs(km.tunnels_of("TESTHOST")["tunnels"][0]["hasToken"], False)


class TheRemotesPayloadCarriesNoToken(unittest.TestCase):
    def _row(self, token):
        return {"host": "TESTHOST", "kernel_port": 29855, "local_port": 51000, "bus_port": 51001,
                "token": token, "status": "up", "detail": "", "sids": [SID], "trust": "directed",
                "kernel_sha": "abc1234", "kernel_ver": "v0.1.3", "proc": None}

    def test_the_public_row_says_whether_a_token_exists_never_which(self):
        pub = km._remote_public(self._row(SECRET))
        self.assertNotIn("token", pub, "the page dials through the relay, which injects the credential itself")
        self.assertIs(pub["hasToken"], True)
        self.assertNotIn(SECRET, json.dumps(pub))
        self.assertIs(km._remote_public(self._row(""))["hasToken"], False)

    def test_the_tunnels_listing_never_serializes_a_token(self):
        saved = dict(km._remotes)
        km._remotes.clear()
        try:
            km._remotes["TESTHOST"] = self._row(SECRET)
            self.assertNotIn(SECRET, json.dumps(km.list_remotes()))
            self.assertEqual(km.list_remotes()[0]["hasToken"], True)
        finally:
            km._remotes.clear()
            km._remotes.update(saved)


class _FakeVersion(BaseHTTPRequestHandler):
    PAYLOAD = {}

    def do_GET(self):
        body = json.dumps(self.PAYLOAD).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class TheVersionPollReadsShapes(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeVersion)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        km._peer_shape_said.clear()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        km._peer_shape_said.clear()

    def _poll(self, payload, host="TESTHOST"):
        _FakeVersion.PAYLOAD = payload
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            got = km._poll_remote_version({"host": host, "local_port": self.port, "token": "tok"})
        return got, err.getvalue()

    def test_good_values_pass_unchanged_and_quietly(self):
        got, said = self._poll({"kernel_sha": "abc1234", "kernel_ver": "v0.5.0+", "autoNudge": False})
        self.assertEqual((got["sha"], got["ver"], got["autoNudge"]), ("abc1234", "v0.5.0+", False))
        self.assertEqual(said, "")
        got, said = self._poll({"kernel_sha": "a" * 40, "kernel_ver": "v12.0.3"})
        self.assertEqual((got["sha"], got["ver"]), ("a" * 40, "v12.0.3"))

    def test_a_sha_that_is_not_one_is_refused_and_said_once(self):
        for bad in ("abc" + QUOTE, IMG, "ABC1234", "abc12", "g" * 8, "a" * 41):
            with self.subTest(sha=bad):
                km._peer_shape_said.clear()
                got, said = self._poll({"kernel_sha": bad, "kernel_ver": "v0.5.0"})
                self.assertIsNone(got, "an unusable sha is no sha — the row keeps what it last knew")
                self.assertIn("TESTHOST reported a kernel_sha that is not one", said)
                self.assertIn(repr(bad[:60]), said, "the complaint quotes what came, so the offender is identifiable")
                got, said2 = self._poll({"kernel_sha": bad, "kernel_ver": "v0.5.0"})
                self.assertEqual(said2, "", "said ONCE per host and field, not once per poll")

    def test_a_version_that_is_not_one_is_blanked_and_said_once(self):
        for bad in ("v1" + IMG, "1.2.3", "v1.2", "v1.2.3-dirty", "v1.2.3++", QUOTE):
            with self.subTest(ver=bad):
                km._peer_shape_said.clear()
                got, said = self._poll({"kernel_sha": "abc1234", "kernel_ver": bad})
                self.assertEqual(got["sha"], "abc1234", "the sha still lands — the fields are judged apart")
                self.assertEqual(got["ver"], "", "the row falls back to the sha alone, as against an older kernel")
                self.assertIn("TESTHOST reported a kernel_ver that is not one", said)
                _, said2 = self._poll({"kernel_sha": "abc1234", "kernel_ver": bad})
                self.assertEqual(said2, "")

    def test_a_missing_version_is_not_a_complaint(self):
        got, said = self._poll({"kernel_sha": "abc1234"})
        self.assertEqual(got["ver"], "")
        self.assertEqual(said, "", "an older kernel that predates the field is not misbehaving")

    def test_a_peer_on_a_dirty_worktree_keeps_its_sha(self):
        # The suffix _kernel_sha appends on uncommitted edits is a sha to every reader here (_sha_base strips
        # it, _shas_agree ignores it); a shape that refused it froze that peer's row on its last clean poll
        # and the panel called it an unversioned copy (review find). Guard: passes on origin/main too.
        got, said = self._poll({"kernel_sha": "abc1234-dirty", "kernel_ver": "v0.5.0+"})
        self.assertEqual((got["sha"], got["ver"]), ("abc1234-dirty", "v0.5.0+"))
        self.assertEqual(said, "", "nothing to complain about")
        self.assertEqual(km._sha_base(got["sha"]), "abc1234", "the drift readers see the commit under it")
        self.assertIs(km._remote_out_of_date({"kernel_sha": got["sha"]}, head="abc1234"), False,
                      "same commit, dirty or not, is not out of date")
        self.assertIs(km._remote_out_of_date({"kernel_sha": got["sha"]}, head="def5678"), True)


class TheRelayDiscardsTheBrowsersToken(unittest.TestCase):
    def test_the_browser_query_token_is_dropped_before_the_remote_credential_is_set(self):
        # test_kernel_remote_ws_proxy drives the splice end to end for a row WITH a token; this pins the
        # order for the row without one: the browser's `token` is popped unconditionally, so nothing a page
        # sends can ever travel to the far kernel — the relay speaks for itself or not at all.
        src = inspect.getsource(km.Handler._remote_ws)
        drop, inject = src.index('q.pop("token", None)'), src.index('q["token"] = [rtok]')
        self.assertLess(drop, inject)
        self.assertLess(src.index("q = parse_qs(query"), drop)


class TheAttachRouteSpeaksInHasToken(unittest.TestCase):
    def test_no_kernel_source_publishes_the_token_key_on_a_public_row(self):
        src = inspect.getsource(km._remote_public)
        self.assertNotIn('"token": r.get("token")', src)
        self.assertIn('"hasToken": bool(r.get("token"))', src)


if __name__ == "__main__":
    unittest.main()
