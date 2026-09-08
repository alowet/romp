#!/usr/bin/env python3
"""A check-in handshake must not undo the trust you set (the user 2026-07-29).

Symptom: a remote was set to trusted, over and over, and kept coming back as directed — its mail
quarantining again minutes later. The setting was not being forgotten by the store; it was being
OVERWRITTEN. checkin_apply rebuilt the peer's row from scratch on every handshake with a hardcoded
"trust": "directed", and the handshake repeats once per tunnel INCARNATION: every reconnect, tunnel
respawn and kernel restart on the checking-in machine.

The mismatch is invisible from the sending end, which is why it read as a store that forgets: the level
a peer DECLARES comes from its own row, so the sender kept displaying "they hold yours: trusted" while
the receiver was quarantining. A re-check-in is the same relationship reconnecting, not a new one.

CheckinHostChecked / CheckinRoute (2026-09-08): the same handshake took the peer's DECLARED name as it
came — any length, any characters — and that string went on to key the registry, remotes.json, the
remembered-hosts file, the bus's peer table (and the mail it holds for that peer, a path component
there), the /remote/<host>/ routes and every row action's body lookup. Every name a romp mobile
declares clears _safe_id — _self_host()'s derived names always did, and its ROMP_HOST_NAME override
now does or is set aside aloud (test_postal_self_host.py) — so the hub refuses anything else at the
door with a 400 that says what a name may look like, recording, saving, popping and waking nothing,
and turns away only names no romp mobile produces.

Synthetic only — placeholder hosts/ports/tokens, hermetic temp STATE, no ssh.
"""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
km = SourceFileLoader("romp_kernel_citrust", os.path.join(BIN, "romp-kernel")).load_module()

BODY = {"host": "TESTHOST", "kernelPort": 29855, "busPort": 25302, "token": "peertok"}


class CheckinTrust(unittest.TestCase):
    def setUp(self):
        km._remotes.clear()
        with km._known_lock:
            km._known.clear()

    def tearDown(self):
        km._remotes.clear()
        with km._known_lock:
            km._known.clear()

    def test_a_first_checkin_is_directed_the_safe_default(self):
        payload, status = km.checkin_apply(dict(BODY))
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(km._remotes["TESTHOST"]["trust"], "directed")

    def test_a_LEVEL_YOU_SET_survives_the_next_handshake(self):
        # this is the bug: the mobile reconnects (or its kernel restarts) and hands in the same details
        km.checkin_apply(dict(BODY))
        km.set_trust("TESTHOST", "trusted")
        self.assertEqual(km._remotes["TESTHOST"]["trust"], "trusted")
        km.checkin_apply(dict(BODY))
        self.assertEqual(km._remotes["TESTHOST"]["trust"], "trusted",
                         "a reconnect must not silently re-gate a host you trusted")

    def test_isolated_survives_too_the_refusal_is_a_boundary(self):
        # an isolation refusal is the user's boundary; a reconnect re-opening it would be worse than
        # the directed case, since isolation means no postal contact at all
        km.checkin_apply(dict(BODY))
        km.set_trust("TESTHOST", "isolated")
        km.checkin_apply(dict(BODY))
        self.assertEqual(km._remotes["TESTHOST"]["trust"], "isolated")

    def test_the_level_is_remembered_so_it_survives_a_kernel_restart_too(self):
        km.checkin_apply(dict(BODY))
        km.set_trust("TESTHOST", "trusted")
        self.assertEqual(km.known_trust("TESTHOST"), "trusted", "the remembered entry tracks the choice")
        # a restart loses _remotes' live rows; the next handshake rebuilds from what was remembered
        km._remotes.clear()
        km.checkin_apply(dict(BODY))
        self.assertEqual(km._remotes["TESTHOST"]["trust"], "trusted")

    def test_a_checkin_under_a_NEW_name_carries_nothing_over(self):
        # the same mobile re-checking in as another name is a different key: it must not inherit a level
        # chosen for the old one, since trust is judged by origin name at the gate
        km.checkin_apply(dict(BODY))
        km.set_trust("TESTHOST", "trusted")
        km.checkin_apply(dict(BODY, host="OTHERHOST"))
        self.assertEqual(km._remotes["OTHERHOST"]["trust"], "directed")

    def test_an_ssh_attached_row_of_the_same_name_is_still_refused(self):
        km._remotes["TESTHOST"] = {"host": "TESTHOST", "trust": "trusted", "checkin_peer": False}
        payload, status = km.checkin_apply(dict(BODY))
        self.assertEqual(status, 409)
        self.assertFalse(payload["ok"])
        self.assertEqual(km._remotes["TESTHOST"]["trust"], "trusted", "the ssh row is untouched")


# What the door must say when it refuses a name — the person's words, naming the shape a host may take.
RULE = ("host must be a machine name: letters, digits, dots, hyphens or underscores, starting with a "
        "letter or digit, at most 128 characters")

# Names every consumer downstream would choke on, or silently mis-key. Each is a path/URL/JSON hazard a
# hostile or merely broken peer could declare; none is anything _self_host() can produce.
BAD_HOSTS = {
    "a slash": "mobile/hub", "a slash with dot-dot": "mobile/../hub",
    "whitespace inside": "my host", "a tab": "host\tname", "a newline": "host\nname",
    "a NUL": "host\x00name", "a control char": "host\x1bname",
    "just over the limit": "a" * 129, "ten kilobytes": "b" * 10_000,
    "a leading dot": ".hidden", "dot-dot": "..", "a lone dot": ".",
    "a leading hyphen": "-oProxyCommand=x", "a quote": 'host"name', "a backslash": "host\\name",
    "a colon": "host:22", "an at-sign": "user@host", "a percent": "host%2Fname", "a query": "host?x=1",
}

# Names machines really declare, and every fixture name the other check-in tests use. A dotted FQDN
# with hyphens, an underscore (an ssh alias or a ROMP_HOST_NAME override may carry one), a minted
# last-resort id, and single-character or digit-led labels all pass.
GOOD_HOSTS = ("TESTHOST", "OTHERHOST", "mobile1", "hub", "laptop", "build-box-01.example.com",
              "my_box", "host-1a2b3c4d", "a", "9box", "a" * 128)


class CheckinHostChecked(unittest.TestCase):
    """A check-in is refused when the declared host is not a hostname, and nothing is recorded."""

    def setUp(self):
        km._remotes.clear()
        with km._known_lock:
            km._known.clear()
        self.saves, self.notes = [], []
        self._saved = (km._remotes_save, km._known_note)
        km._remotes_save = lambda: self.saves.append(1)
        km._known_note = lambda *a, **k: self.notes.append((a, k))
        km._tunnel_wake.clear()
        self.disk = self._disk()

    def tearDown(self):
        km._remotes_save, km._known_note = self._saved
        km._remotes.clear()
        with km._known_lock:
            km._known.clear()

    @staticmethod
    def _disk():
        # the two persisted registries, as bytes (None = absent), so "nothing saved" is checked on disk too
        out = []
        for f in (km.REMOTES_FILE, km.KNOWN_FILE):
            try:
                out.append(f.read_bytes())
            except OSError:
                out.append(None)
        return out

    def _refused(self, why, host):
        payload, status = km.checkin_apply(dict(BODY, host=host))
        self.assertEqual(status, 400, why)
        self.assertIs(payload["ok"], False, why)
        self.assertEqual(payload["error"], RULE, why)
        if len(host) > 3:
            self.assertNotIn(host, payload["error"], "the refused string is not echoed back (%s)" % why)
        self.assertEqual(km._remotes, {}, "nothing filed in the registry (%s)" % why)
        with km._known_lock:
            self.assertEqual(km._known, {}, "nothing remembered (%s)" % why)
        self.assertEqual(self.saves, [], "remotes.json not written (%s)" % why)
        self.assertEqual(self.notes, [], "no remembered-hosts entry (%s)" % why)
        self.assertEqual(self._disk(), self.disk, "neither state file changed (%s)" % why)
        self.assertFalse(km._tunnel_wake.is_set(), "the supervisor is not woken for nothing (%s)" % why)

    def test_a_slash_is_refused_and_nothing_is_recorded(self):
        for why in ("a slash", "a slash with dot-dot"):
            self._refused(why, BAD_HOSTS[why])

    def test_whitespace_inside_is_refused(self):
        for why in ("whitespace inside", "a tab", "a newline"):
            self._refused(why, BAD_HOSTS[why])

    def test_a_control_char_or_nul_is_refused(self):
        for why in ("a NUL", "a control char"):
            self._refused(why, BAD_HOSTS[why])

    def test_an_over_long_name_is_refused(self):
        for why in ("just over the limit", "ten kilobytes"):
            self._refused(why, BAD_HOSTS[why])

    def test_a_leading_dot_or_dot_dot_is_refused(self):
        for why in ("a leading dot", "dot-dot", "a lone dot"):
            self._refused(why, BAD_HOSTS[why])

    def test_every_other_hazard_is_refused_too(self):
        for why, host in BAD_HOSTS.items():
            self._refused(why, host)

    def test_a_non_string_host_is_refused(self):
        # str() used to coerce these into names — a JSON 1.5 became the host "1.5" and was filed
        for host in (["mobile"], {"host": "mobile"}, 1.5, 5, True, None):
            payload, status = km.checkin_apply(dict(BODY, host=host))
            self.assertEqual(status, 400, repr(host))
            self.assertIs(payload["ok"], False, repr(host))
            self.assertEqual(payload["error"], "host, kernelPort, busPort required", repr(host))
        self.assertEqual((km._remotes, self.saves, self.notes), ({}, [], []))
        self.assertFalse(km._tunnel_wake.is_set())

    def test_a_junk_name_with_a_known_token_pops_nothing(self):
        # the same-token sweep ("this mobile re-checked in under a new name") ran BEFORE anything looked
        # at the name, so a junk re-check-in would have dropped the mobile's good row on its way in
        km.checkin_apply(dict(BODY))
        self.assertEqual(set(km._remotes), {"TESTHOST"})
        self.saves.clear(), self.notes.clear()
        km._tunnel_wake.clear()
        payload, status = km.checkin_apply(dict(BODY, host=BAD_HOSTS["a slash with dot-dot"]))
        self.assertEqual((status, payload["ok"], payload["error"]), (400, False, RULE))
        self.assertEqual(set(km._remotes), {"TESTHOST"}, "the good row is untouched")
        self.assertEqual(km._remotes["TESTHOST"]["token"], "peertok")
        self.assertEqual((self.saves, self.notes), ([], []))
        self.assertFalse(km._tunnel_wake.is_set())

    def test_the_names_machines_declare_still_land(self):
        for h in GOOD_HOSTS:
            payload, status = km.checkin_apply(dict(BODY, host=h, token="tok-" + h))
            self.assertEqual(status, 200, h)
            self.assertIs(payload["ok"], True, h)
            self.assertEqual(payload["host"], h)
            self.assertTrue(km._remotes[h]["checkin_peer"], h)
            self.assertEqual(km._remotes[h]["host"], h)
        self.assertEqual(len(self.saves), len(GOOD_HOSTS), "each landing is persisted, as before")
        self.assertEqual([a[0] for a, k in self.notes], list(GOOD_HOSTS), "…and remembered, as before")
        self.assertTrue(km._tunnel_wake.is_set())

    def test_this_machines_own_declared_name_clears_the_rule(self):
        # what a real mobile sends IS _self_host(); every shape it can produce must land. Read live, with
        # the override out of the way, so this checks the box's real short hostname — never a literal.
        saved = os.environ.pop("ROMP_HOST_NAME", None)
        try:
            me = km._self_host()
        finally:
            if saved is not None:
                os.environ["ROMP_HOST_NAME"] = saved
        self.assertTrue(km._safe_id(me), "the rule IS the promise _self_host makes")
        payload, status = km.checkin_apply(dict(BODY, host=me))
        self.assertEqual(status, 200, "a real machine's own name must never be refused")
        self.assertIn(me, km._remotes)
        # …and the two fallbacks _self_host reaches for when the kernel hostname fails path-safety
        for h in (km._sanitize_host_name("Some Body's Mac (2)"), "host-%08x" % 0xDEADBEEF):
            self.assertTrue(h and km._safe_id(h), h)
            self.assertEqual(km.checkin_apply(dict(BODY, host=h, token="t-" + h))[1], 200, h)


class CheckinRoute(unittest.TestCase):
    """The same refusal through the door the mobile actually knocks on: POST /checkin on the real Handler
    (the test_tag_route.py harness pattern)."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), km.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        km._remotes.clear()
        with km._known_lock:
            km._known.clear()
        self.saves, self.notes = [], []
        self._saved = (km._remotes_save, km._known_note)
        km._remotes_save = lambda: self.saves.append(1)
        km._known_note = lambda *a, **k: self.notes.append((a, k))

    def tearDown(self):
        km._remotes_save, km._known_note = self._saved
        km._remotes.clear()
        with km._known_lock:
            km._known.clear()

    def _post(self, body):
        req = urllib.request.Request(
            "http://127.0.0.1:%d/checkin" % self.port, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "X-Romp-Token": os.environ["ROMP_SERVE_TOKEN"]})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def test_over_http_a_junk_name_is_a_400_and_a_real_one_lands(self):
        for why in ("a slash with dot-dot", "whitespace inside", "a NUL", "ten kilobytes", "a leading dot"):
            st, r = self._post(dict(BODY, host=BAD_HOSTS[why]))
            self.assertEqual(st, 400, why)
            self.assertEqual((r.get("ok"), r.get("error")), (False, RULE), why)
        self.assertEqual((km._remotes, self.saves, self.notes), ({}, [], []), "nothing recorded over HTTP either")
        st, r = self._post(dict(BODY, host="build-box-01.example.com"))
        self.assertEqual(st, 200)
        self.assertEqual((r["ok"], r["host"]), (True, "build-box-01.example.com"))
        self.assertTrue(km._remotes["build-box-01.example.com"]["checkin_peer"])
        self.assertEqual((len(self.saves), len(self.notes)), (1, 1))


if __name__ == "__main__":
    unittest.main()
