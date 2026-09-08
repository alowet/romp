#!/usr/bin/env python3
"""Web Push for the bell events (plans/ios-app.md proposal 2).

Covers the four layers separately, so a failure names its layer:

  * routes — /sw.js and /push/vapid-key are token-gated (they serve to the authed shell only);
    POST /push/subscribe validates, stores at 0600, and refuses loudly when the crypto
    dependency is missing; /push/unsubscribe prunes.
  * the worker — push + notificationclick ONLY. A fetch handler would fight the stale-bundle
    machinery (?v= cache-bust + the rstale banner), which assumes the network serves every load.
  * crypto — RFC 8291 aes128gcm round-trip: encrypt with the kernel's writer, decrypt with an
    independent receiver-side derivation from a browser keypair minted HERE, at run time (no
    credential-shaped literals in fixtures — repo rule). RFC 8292 VAPID: parse the header, verify
    the ES256 signature against the advertised key, check the claims.
  * the sink — _push_notify mirrors (title, body) to every subscription, sends the card gist and
    NOTHING more, prunes on the dead-subscription signal, and stands down silently when no
    device ever subscribed.

The cryptography package is required here (CI installs it; the kernel treats it as a soft
dependency and fails loudly without it — test_subscribe_without_crypto_is_a_loud_500).
"""
import io
import json
import os
import time
import threading
import unittest
from unittest import mock
from importlib.machinery import SourceFileLoader
import tempfile

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import serialization
    HAVE_CRYPTO = True
except ImportError:                                   # pragma: no cover — CI installs it
    HAVE_CRYPTO = False

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")

# Hermetic state BEFORE the loads — they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
SourceFileLoader("romp_event_model", os.path.join(BIN, "romp-event-model")).load_module()
jd = SourceFileLoader("romp_judge", os.path.join(BIN, "romp-judge")).load_module()
# Belt over conftest's suspenders. Under pytest, conftest.py rebinds XDG_STATE_HOME to a tempdir
# before any test module imports — but a RAW `python3 tests/test_kernel_webpush.py` skips conftest,
# and this file DELETES push state in _clear_push_state: on 2026-08-08 a raw run aimed that at the
# LIVE store, wiping the maintainer's phone subscription and rotating the real VAPID key (which
# orphans every subscription bound to it). Rebind the state root here, unconditionally, BEFORE the
# kernel module loads and captures jd.STATE into its path constants.
from pathlib import Path
_STATE_TD = tempfile.TemporaryDirectory()
jd.STATE = Path(_STATE_TD.name)
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "test-token-DO-NOT-USE")
km = SourceFileLoader("romp_kernel_webpush", os.path.join(BIN, "romp-kernel")).load_module()


def _b64u(b):
    import base64
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _mint_browser_keys():
    """What a real subscription carries, minted fresh per test run: a P-256 keypair (p256dh) and
    a 16-byte auth secret. Assembled at run time on purpose — a longhand fake key in a fixture
    would trip the very secret scanner that guards this repo."""
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key().public_bytes(serialization.Encoding.X962,
                                         serialization.PublicFormat.UncompressedPoint)
    return priv, _b64u(pub), _b64u(os.urandom(16))


def _serve_get(path, headers=None):
    """The real do_GET over a fake socket (the auth-hardening harness): (status, body_bytes)."""
    h = km.Handler.__new__(km.Handler)
    h.client_address = ("127.0.0.1", 0)
    h.headers = dict(headers or {})
    h.path = path
    h.command = "GET"
    h.request_version = "HTTP/1.1"
    h.wfile = io.BytesIO()
    h.rfile = io.BytesIO()
    h.close_connection = True
    captured = {}
    h.send_response = lambda code, *a: captured.__setitem__("status", code)
    h.send_header = lambda k, v: None
    h.end_headers = lambda: None
    h.log_message = lambda *a: None
    h.do_GET()
    return captured.get("status"), h.wfile.getvalue()


def _clear_push_state():
    for name in ("push-subscriptions.json", "push-vapid.json"):
        try:
            (jd.STATE / name).unlink()
        except OSError:
            pass


class ServiceWorkerRoute(unittest.TestCase):
    def test_sw_is_gated_and_push_only(self):
        status, _ = _serve_get("/sw.js")
        self.assertEqual(status, 403, "the worker serves to the authed shell only")
        status, body = _serve_get("/sw.js", headers={"X-Romp-Token": km.TOKEN})
        self.assertEqual(status, 200)
        js = body.decode()
        self.assertIn("addEventListener('push'", js)
        self.assertIn("addEventListener('notificationclick'", js)
        # NO fetch handler, ever: a caching worker would fight the stale-bundle detection,
        # which assumes the network serves every load (plans/ios-app.md)
        self.assertNotIn("'fetch'", js)
        self.assertNotIn("caches", js)
        # an UPDATED worker must take over immediately — this one owns no caches, so 'waiting'
        # only delays fixes (the sid-blind predecessor kept handling taps, the user 2026-08-08)
        self.assertIn("skipWaiting()", js)
        self.assertIn("clients.claim()", js)

    def test_sw_click_lands_on_the_session_that_fired(self):
        # the user 2026-08-08: the first real push opened the app on a DIFFERENT session. The
        # kernel's routing block rides the notification's data; a live window gets it over
        # postMessage, a cold start gets the kernel's deep link (ServiceWorkerExecutes runs it).
        _, body = _serve_get("/sw.js", headers={"X-Romp-Token": km.TOKEN})
        js = body.decode()
        self.assertIn("data:(d.data&&typeof d.data==='object')?d.data:{sid:d.sid||''}", js,
                      "the routing block verbatim; an older kernel's flat sid still lands")
        self.assertIn("opts.tag=d.tag;opts.renotify=!d.quiet", js, "one notification per session, still audible unless it is the quiet card push that yields the buzz")
        self.assertIn("if(d.quiet)opts.silent=true", js, "a quiet push carries the badge without re-alerting")
        self.assertIn("romp:'notificationClick'", js)
        self.assertIn("clients.openWindow(url)", js)
        self.assertIn("/?push-reveal=", js)              # the fallback deep link for a data block without one
        self.assertNotIn("setTimeout", js)                # event-based end to end — no timers in the worker
        # ...and the closed-app badge count comes from the payload
        self.assertIn("setAppBadge", js)


# The worker, EXECUTED (the test_error_center.py pattern): node runs _SW_JS against stubs of the
# ServiceWorker globals and the driver replays a push and four taps, logging every call in order.
# A source pin says the words are there; this says the sequence is right: close → matchAll →
# focus + postMessage, openWindow only when no window exists or focus() refused, all under waitUntil.
_SW_HARNESS = r"""
'use strict';
const H = {};            // event name -> the worker's handler
const LOG = [];          // every call the worker makes, in order
global.self = {
  addEventListener: (k, f) => { H[k] = f; },
  skipWaiting: () => {},
  registration: { showNotification: (title, opts) => { LOG.push(['show', title, opts]); return Promise.resolve(); },
                  update: () => { LOG.push(['update']); return Promise.resolve(); } },
  navigator: {},         // no setAppBadge here: the numeric-only badge rule has its own pin
};
global.clients = {
  claim: () => Promise.resolve(),
  matchAll: (q) => { LOG.push(['matchAll', q]); return Promise.resolve([]); },
  openWindow: (u) => { LOG.push(['openWindow', u]); return Promise.resolve({}); },
};
"""
_SW_DRIVER = r"""
function win(focusOk) {
  const w = { frameType: 'top-level',
              focus: () => { LOG.push(['focus']); return focusOk ? Promise.resolve(w) : Promise.reject(new Error('refused')); },
              postMessage: (m) => LOG.push(['post', m]) };
  return w;
}
// a TAGGED client, for the dashboard's shape: the shell (top-level) plus its same-origin pane iframes,
// which the browser lists as window clients too (frameType 'nested'), most-recently-focused first
function frame(tag, frameType) {
  const w = { frameType,
              focus: () => { LOG.push(['focus', tag]); return Promise.resolve(w); },
              postMessage: (m) => LOG.push(['post', tag, m]) };
  return w;
}
async function tap(data, windows) {
  LOG.length = 0;
  const waited = [];
  global.clients.matchAll = (q) => { LOG.push(['matchAll', q]); return Promise.resolve(windows); };
  H.notificationclick({ notification: { close: () => LOG.push(['close']), data }, waitUntil: (p) => waited.push(p) });
  for (const p of waited) await p;
  return { log: LOG.slice(), waited: waited.length };
}
(async () => {
  const out = {};
  const data = { sid: 'S1', host: '', kind: 'card', cardId: 'S1:g1', url: '/?push-reveal=S1&push-card=S1%3Ag1' };
  let pushWait = null;
  H.push({ data: { json: () => ({ title: 'romp: web', body: 'Needs you: x', sid: 'S1', tag: 'romp:S1', badge: 2, data }) },
           waitUntil: (p) => { out.pushWaited = true; pushWait = p; } });
  out.pushSync = LOG.slice();          // before the handler yields: the show, and nothing racing it
  await pushWait;                      // the whole push, as the browser waits for it
  out.push = LOG.slice();
  LOG.length = 0;
  H.push({ data: { json: () => ({ title: 't', body: 'b', sid: 'S9' }) }, waitUntil: (p) => { pushWait = p; } });   // an older kernel's flat payload
  out.pushLegacy = LOG.slice();
  await pushWait;                      // its update lands here, not inside the next tap's log
  out.live = await tap(data, [win(true)]);
  out.cold = await tap(data, []);
  out.refused = await tap(data, [win(false)]);
  out.test = await tap({ sid: '', host: '', kind: 'test', cardId: '', url: '/' }, []);
  const testSid = { sid: 'S5', host: '', kind: 'test', cardId: '', url: '/?push-reveal=S5' };   // a test addressed to the session in front (2026-09-06)
  out.testLive = await tap(testSid, [win(true)]);
  out.testCold = await tap(testSid, []);
  out.legacyTap = await tap({ sid: 'S7' }, []);            // a notification an older worker showed: flat sid, no url
  // the phone (2026-09-06): the user last tapped INSIDE the chat pane (the mobile session picker), so the
  // chat iframe is the most recently focused client — ahead of the shell that carries the reveal listener
  const fed = { sid: 'boxa:S8', host: 'boxa', kind: 'test', cardId: '', url: '/?push-reveal=boxa%3AS8' };
  out.nested = await tap(fed, [frame('chat', 'nested'), frame('feed', 'nested'), frame('shell', 'top-level')]);
  out.nestedOnly = await tap(fed, [frame('chat', 'nested')]);   // a pane with no shell above it: nothing to post to
  out.untyped = await tap(fed, [frame('old', undefined)]);       // a browser that reports no frameType is a window
  // the cold start's second road (2026-09-08): the window openWindow hands back is given the routing block too
  const opened = { postMessage: (m) => LOG.push(['post', 'opened', m]) };
  const openWindow0 = global.clients.openWindow;
  global.clients.openWindow = (u) => { LOG.push(['openWindow', u]); return Promise.resolve(opened); };
  out.coldHanded = await tap(data, []);
  out.testHanded = await tap({ sid: '', host: '', kind: 'test', cardId: '', url: '/' }, []);   // nothing to land on: nothing posted
  global.clients.openWindow = (u) => { LOG.push(['openWindow', u]); return Promise.resolve(null); };
  out.coldNull = await tap(data, []);                              // no client back: the link alone, no throw
  global.clients.openWindow = openWindow0;
  console.log(JSON.stringify(out));
})();
"""


class ServiceWorkerExecutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess, tempfile as _tf
        with _tf.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(_SW_HARNESS + km._SW_JS + _SW_DRIVER)
            path = f.name
        try:
            r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        finally:
            os.unlink(path)
        assert r.returncode == 0, "the worker threw: " + r.stderr[:800]
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    MATCH = ["matchAll", {"type": "window", "includeUncontrolled": True}]
    MSG = {"romp": "notificationClick", "sid": "S1", "host": "", "kind": "card", "cardId": "S1:g1"}
    URL = "/?push-reveal=S1&push-card=S1%3Ag1"

    def test_push_shows_the_gist_and_keeps_the_routing_block_verbatim(self):
        show = self.out["push"][0]
        self.assertEqual(show[:2], ["show", "romp: web"])
        opts = show[2]
        self.assertEqual(opts["body"], "Needs you: x")
        self.assertEqual(opts["data"], {"sid": "S1", "host": "", "kind": "card", "cardId": "S1:g1", "url": self.URL})
        self.assertEqual((opts["tag"], opts["renotify"]), ("romp:S1", True), "same session → replaces, still buzzes")
        self.assertTrue(self.out["pushWaited"])
        # an older kernel's flat payload still lands on its sid, and wears no tag it did not send
        legacy = self.out["pushLegacy"][0][2]
        self.assertEqual(legacy["data"], {"sid": "S9"})
        self.assertNotIn("tag", legacy)

    def test_the_push_refreshes_the_worker_once_the_notification_shows(self):
        # the phone (2026-09-08): an installed app left in the background checks for a new worker only on
        # a navigation, so every tap after a deploy ran the OLD handler. The push itself now asks for the
        # update — after the show, so the notification a push must produce is never raced by the takeover
        self.assertEqual([x[0] for x in self.out["pushSync"]], ["show"])
        self.assertEqual([x[0] for x in self.out["push"]], ["show", "update"])
        self.assertEqual([x[0] for x in self.out["pushLegacy"]], ["show"], "the legacy payload's push refreshes too, after its show")

    def test_a_cold_start_also_hands_the_opened_window_the_routing_block(self):
        # a message to a window whose page has no listener yet is held by the browser until the shell adds
        # one — the second road for a browser that opens the app on its start URL instead of the link
        self.assertEqual(self.out["coldHanded"]["log"], [["close"], self.MATCH, ["openWindow", self.URL], ["post", "opened", self.MSG]])
        self.assertEqual(self.out["coldNull"]["log"], [["close"], self.MATCH, ["openWindow", self.URL]])
        self.assertEqual(self.out["testHanded"]["log"], [["close"], self.MATCH, ["openWindow", "/"]])

    def test_a_live_window_is_focused_and_told_never_reopened(self):
        live = self.out["live"]
        self.assertEqual(live["waited"], 1, "the whole tap rides one waitUntil")
        self.assertEqual(live["log"], [["close"], self.MATCH, ["focus"], ["post", self.MSG]])

    def test_no_window_opens_the_deep_link(self):
        self.assertEqual(self.out["cold"]["log"], [["close"], self.MATCH, ["openWindow", self.URL]])
        self.assertEqual(self.out["cold"]["waited"], 1)

    def test_a_refused_focus_falls_through_to_open_window(self):
        # the installed-app case: focus() rejects — the tap must still land somewhere
        self.assertEqual(self.out["refused"]["log"], [["close"], self.MATCH, ["focus"], ["openWindow", self.URL]])

    def test_a_test_notification_just_opens_romp(self):
        # …when it carries no session: the button was pressed with no session in front
        self.assertEqual(self.out["test"]["log"], [["close"], self.MATCH, ["openWindow", "/"]])

    def test_a_test_addressed_to_a_session_lands_on_it_like_a_turn(self):
        # the user 2026-09-06: the test carries the session the button was pressed on. The worker
        # does not branch on kind — the same focus + routing block live, the same deep link cold
        msg = {"romp": "notificationClick", "sid": "S5", "host": "", "kind": "test", "cardId": ""}
        self.assertEqual(self.out["testLive"]["log"], [["close"], self.MATCH, ["focus"], ["post", msg]])
        self.assertEqual(self.out["testCold"]["log"], [["close"], self.MATCH, ["openWindow", "/?push-reveal=S5"]])

    def test_a_notification_from_the_previous_worker_still_lands(self):
        self.assertEqual(self.out["legacyTap"]["log"][-1], ["openWindow", "/?push-reveal=S7"])

    def test_the_tap_is_posted_to_the_shell_never_into_a_pane_iframe(self):
        # the user 2026-09-06, on the phone: the tap did nothing. matchAll lists the dashboard's
        # same-origin pane iframes as window clients too, most-recently-focused first — and the
        # chat pane the user had just switched sessions in was first. Only the top-level shell
        # listens for the worker's message; posting into the pane dropped the tap on the floor.
        msg = {"romp": "notificationClick", "sid": "boxa:S8", "host": "boxa", "kind": "test", "cardId": ""}
        self.assertEqual(self.out["nested"]["log"],
                         [["close"], self.MATCH, ["focus", "shell"], ["post", "shell", msg]])
        # no top-level client at all → the deep link, exactly as with no window
        self.assertEqual(self.out["nestedOnly"]["log"], [["close"], self.MATCH, ["openWindow", "/?push-reveal=boxa%3AS8"]])
        # a client that reports no frameType is treated as a window, never dropped
        self.assertEqual(self.out["untyped"]["log"][-1], ["post", "old", msg])


@unittest.skipUnless(HAVE_CRYPTO, "python 'cryptography' not installed")
class VapidKeys(unittest.TestCase):
    def setUp(self):
        _clear_push_state()

    def test_key_route_is_gated_and_stable(self):
        status, _ = _serve_get("/push/vapid-key")
        self.assertEqual(status, 403)
        status, body = _serve_get("/push/vapid-key", headers={"X-Romp-Token": km.TOKEN})
        self.assertEqual(status, 200)
        k1 = json.loads(body.decode())["key"]
        import base64
        raw = base64.urlsafe_b64decode(k1 + "=" * (-len(k1) % 4))
        self.assertEqual((len(raw), raw[0]), (65, 0x04), "uncompressed P-256 point")
        # stable across calls: a subscription is bound to the key it was minted with
        _, body2 = _serve_get("/push/vapid-key", headers={"X-Romp-Token": km.TOKEN})
        self.assertEqual(json.loads(body2.decode())["key"], k1)

    def test_private_key_is_0600(self):
        km._vapid_keys()
        mode = (jd.STATE / "push-vapid.json").stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)


@unittest.skipUnless(HAVE_CRYPTO, "python 'cryptography' not installed")
class Rfc8291Encryption(unittest.TestCase):
    def test_round_trip_against_an_independent_receiver(self):
        # decrypt with the RECEIVER's half of RFC 8291, derived here from first principles —
        # ua private key + auth secret → same IKM → cek/nonce → AESGCM open
        ua_priv, p256dh, auth_b64 = _mint_browser_keys()
        payload = json.dumps({"title": "romp: web", "body": "Needs you: pick a migration"}).encode()
        blob = km._webpush_encrypt(payload, p256dh, auth_b64)

        salt, rs, idlen = blob[:16], int.from_bytes(blob[16:20], "big"), blob[20]
        self.assertEqual((rs, idlen), (4096, 65), "RFC 8188 header: rs=4096, keyid=an EC point")
        as_pub_raw, ct = blob[21:21 + idlen], blob[21 + idlen:]
        as_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub_raw)
        ua_pub_raw = ua_priv.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)

        import base64
        auth = base64.urlsafe_b64decode(auth_b64 + "=" * (-len(auth_b64) % 4))
        hkdf = lambda s, ikm, info, n: HKDF(algorithm=hashes.SHA256(), length=n,
                                            salt=s, info=info).derive(ikm)
        ikm = hkdf(auth, ua_priv.exchange(ec.ECDH(), as_pub),
                   b"WebPush: info\x00" + ua_pub_raw + as_pub_raw, 32)
        cek = hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
        nonce = hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
        plain = AESGCM(cek).decrypt(nonce, ct, None)
        self.assertEqual(plain[-1:], b"\x02", "last-record delimiter")
        self.assertEqual(plain[:-1], payload)

    def test_seams_make_it_deterministic(self):
        # same salt + same ephemeral key → same bytes; fresh defaults → different bytes (real
        # sends never reuse a salt/key pair)
        _, p256dh, auth = _mint_browser_keys()
        eph = ec.generate_private_key(ec.SECP256R1())
        salt = os.urandom(16)
        a = km._webpush_encrypt(b"x", p256dh, auth, _salt=salt, _eph=eph)
        b = km._webpush_encrypt(b"x", p256dh, auth, _salt=salt, _eph=eph)
        c = km._webpush_encrypt(b"x", p256dh, auth)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


@unittest.skipUnless(HAVE_CRYPTO, "python 'cryptography' not installed")
class VapidAuth(unittest.TestCase):
    def setUp(self):
        _clear_push_state()

    def test_header_verifies_and_claims_the_push_origin(self):
        import base64
        hdr = km._vapid_auth("https://push.example.net/send/abc123")
        self.assertTrue(hdr.startswith("vapid t="))
        jwt, key = hdr[len("vapid t="):].split(", k=")
        h64, c64, s64 = jwt.split(".")
        dec = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
        self.assertEqual(json.loads(dec(h64)), {"alg": "ES256", "typ": "JWT"})
        claims = json.loads(dec(c64))
        # audience is the push SERVICE's origin (Apple's/Google's relay), never the full endpoint
        self.assertEqual(claims["aud"], "https://push.example.net")
        self.assertGreater(claims["exp"], time.time())
        self.assertTrue(claims["sub"].startswith("mailto:"))
        # signature verifies against the key the header itself advertises (k=)
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
        pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), dec(key))
        sig = dec(s64)
        der = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
        pub.verify(der, ("%s.%s" % (h64, c64)).encode(), ec.ECDSA(hashes.SHA256()))  # raises on mismatch


class SubscribeRoutes(unittest.TestCase):
    """POST /push/subscribe|unsubscribe over the real handler on loopback (the ServeSecurity
    pattern — a fake socket cannot exercise Content-Length body reads)."""

    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), km.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        _clear_push_state()

    def _post(self, path, body, token=True):
        import urllib.request, urllib.error
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Romp-Token"] = km.TOKEN
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path),
                                     method="POST", data=json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def _sub_body(self):
        if HAVE_CRYPTO:
            _, p256dh, auth = _mint_browser_keys()
        else:
            p256dh, auth = _b64u(b"\x04" + os.urandom(64)), _b64u(os.urandom(16))
        return {"endpoint": "https://push.example.net/send/dev-" + _b64u(os.urandom(6)),
                "keys": {"p256dh": p256dh, "auth": auth}}

    @unittest.skipUnless(HAVE_CRYPTO, "python 'cryptography' not installed")
    def test_subscribe_stores_at_0600_and_unsubscribe_prunes(self):
        sub = self._sub_body()
        code, _ = self._post("/push/subscribe", sub)
        self.assertEqual(code, 200)
        f = jd.STATE / "push-subscriptions.json"
        self.assertEqual(f.stat().st_mode & 0o777, 0o600,
                         "endpoints are capability URLs — the store gets the token treatment")
        self.assertIn(sub["endpoint"], km._push_subs())
        # same device re-subscribing overwrites, never duplicates
        code, _ = self._post("/push/subscribe", sub)
        self.assertEqual((code, len(km._push_subs())), (200, 1))
        code, _ = self._post("/push/unsubscribe", {"endpoint": sub["endpoint"]})
        self.assertEqual((code, km._push_subs()), (200, {}))

    def test_subscribe_requires_the_token(self):
        code, _ = self._post("/push/subscribe", self._sub_body(), token=False)
        self.assertEqual(code, 403)

    def test_garbage_is_a_400_not_a_stored_row(self):
        for bad in ({}, {"endpoint": "http://not-https", "keys": {"p256dh": "x", "auth": "y"}},
                    {"endpoint": "https://push.example.net/x", "keys": {}}):
            code, _ = self._post("/push/subscribe", bad)
            self.assertEqual(code, 400, bad)
        self.assertEqual(km._push_subs(), {})

    def test_subscribe_without_crypto_is_a_loud_500(self):
        # the fail-loudly rule: a subscription the kernel can never deliver to must be REFUSED
        # with the missing package named, not stored and silently starved
        with mock.patch.object(km, "_PUSH_CRYPTO", [False]):
            code, body = self._post("/push/subscribe", self._sub_body())
        self.assertEqual(code, 500)
        self.assertIn("cryptography", body)
        self.assertEqual(km._push_subs(), {})


class PushSink(unittest.TestCase):
    def setUp(self):
        _clear_push_state()

    def test_wired_beside_system_notify(self):
        # the sink hangs off the SAME loop as _system_notify — the armed-bell diff on fresh feed
        # builds — so it inherits the transition-event detection and the silent first-build
        # baseline by construction, rather than re-deriving either
        import inspect
        src = inspect.getsource(km._cached_feed)
        self.assertIn("_system_notify(_t, _b)", src)
        self.assertIn('_push_notify(_t, _b, _sid, _badge, kind="card", card_id=_iid)', src)
        self.assertIn("_badge_push(_badge)", src)

    def test_no_subscriptions_means_no_work(self):
        with mock.patch.object(km, "_push_send_one") as send:
            km._push_notify("romp: web", "Needs you")
        send.assert_not_called()

    def test_delivers_gist_only_and_prunes_dead_endpoints(self):
        km._save_push_subs({
            "https://push.example.net/send/live": {
                "endpoint": "https://push.example.net/send/live",
                "keys": {"p256dh": "k", "auth": "a"}},
            "https://push.example.net/send/dead": {
                "endpoint": "https://push.example.net/send/dead",
                "keys": {"p256dh": "k", "auth": "a"}},
        })
        seen = {}
        done = threading.Event()

        def fake_send(sub, payload):
            seen[sub["endpoint"]] = payload
            if len(seen) == 2:
                done.set()
            return not sub["endpoint"].endswith("/dead")

        with mock.patch.object(km, "_push_send_one", side_effect=fake_send), \
             mock.patch.object(km, "_push_crypto", return_value=True):
            km._push_notify("romp: web", "Needs you: pick a migration", "SID-web", 3)
            self.assertTrue(done.wait(5), "the send thread ran")
            # pruning happens after the sends; poll briefly for the store write
            for _ in range(100):
                if "https://push.example.net/send/dead" not in km._push_subs():
                    break
                time.sleep(0.05)
        self.assertEqual(set(km._push_subs()), {"https://push.example.net/send/live"},
                         "404/410 prunes; success stays")
        body = json.loads(list(seen.values())[0].decode())
        # the plan's privacy note, pinned: the payload is the card's gist (title + body) plus
        # ROUTING metadata — where the tap lands (sid, the data block), how it stacks (tag) and the
        # badge count — and nothing more (no brief, no transcript), even though the content is
        # E2E-encrypted. Every routing value is an id or a fixed word, never text.
        self.assertEqual(set(body), {"title", "body", "sid", "badge", "tag", "data"})
        self.assertEqual((body["title"], body["sid"], body["badge"]), ("romp: web", "SID-web", 3))
        self.assertEqual(set(body["data"]), {"sid", "host", "kind", "cardId", "url"})


class PushPayloadShape(unittest.TestCase):
    """_push_payload: the ONE builder every push kind goes through (the user 2026-09-06, who wants
    a tap to focus the romp already open and land on the session — and card — that buzzed)."""

    def test_a_card_push_carries_the_card_and_a_deep_link_the_shell_parses(self):
        d = km._push_payload("romp: web", "Needs you: pick one", "SID-web", 2, kind="card",
                             card_id="SID-web:g3")
        self.assertEqual(d["data"], {"sid": "SID-web", "host": "", "kind": "card", "cardId": "SID-web:g3",
                                     "url": "/?push-reveal=SID-web&push-card=SID-web%3Ag3"})
        self.assertEqual(d["tag"], "romp:SID-web", "one notification per session")
        self.assertEqual(d["sid"], "SID-web", "…and flat, for a worker of the previous build")
        self.assertEqual(d["badge"], 2)

    def test_a_turn_push_names_its_kind_and_carries_no_card(self):
        d = km._push_payload("web", "finished a turn", "SID-web", kind="turn")
        self.assertEqual((d["data"]["kind"], d["data"]["cardId"], d["data"]["url"]),
                         ("turn", "", "/?push-reveal=SID-web"))
        self.assertNotIn("badge", d, "None omits the key — the worker leaves the count alone")

    def test_a_test_push_has_no_session_and_lands_on_romp_itself(self):
        # the popover's probe (PR #937's _push_test builds its payload here once it lands): kind
        # "test", no sid, so the tap can only ever focus or open romp — and every test collapses
        # into one notification rather than stacking on the lock screen
        d = km._push_payload("romp", "Test notification", kind="test")
        self.assertEqual(d["data"], {"sid": "", "host": "", "kind": "test", "cardId": "", "url": "/"})
        self.assertEqual(d["tag"], "romp:test")

    def test_a_relayed_push_keeps_the_origin_in_sid_and_host(self):
        # a federated event's sid already wears its host prefix (the merged dashboard's own tab
        # address); host is the courtesy copy, from the relay's origin or read off the prefix
        d = km._push_payload("romp: boxa:web", "b", "boxa:11111111-2222", host="boxa", card_id="11111111-2222:g1")
        self.assertEqual((d["data"]["sid"], d["data"]["host"]), ("boxa:11111111-2222", "boxa"))
        self.assertEqual(d["data"]["url"], "/?push-reveal=boxa%3A11111111-2222&push-card=11111111-2222%3Ag1")
        self.assertEqual(km._push_payload("t", "b", "boxb:S")["data"]["host"], "boxb")

    def test_missing_crypto_with_subscriptions_says_so(self):
        km._save_push_subs({"https://push.example.net/send/x": {
            "endpoint": "https://push.example.net/send/x",
            "keys": {"p256dh": "k", "auth": "a"}}})
        with mock.patch.object(km, "_PUSH_CRYPTO", [False]), \
             mock.patch.object(km.sys, "stderr", new=io.StringIO()) as err, \
             mock.patch.object(km, "_push_send_one") as send:
            km._push_notify("romp: web", "Needs you")
        send.assert_not_called()
        self.assertIn("cryptography", err.getvalue(), "a starving phone is never silent")


def _fake_ws_client(app, wid):
    """Just enough of a _clients row for the reveal/badge paths: send() records the parsed JSON."""
    got = []
    return {"app": app, "wid": wid, "alive": True,
            "send": lambda s: got.append(json.loads(s))}, got


class RevealAiming(unittest.TestCase):
    """A push tap lands ON the session that fired (the user 2026-08-08). The cold-start half:
    POST /reveal parks the focus keyed by the asking window's wid, delivered on the exact event
    it waits for — that window's chat pane saying ready — and aimed at that pane alone."""

    def setUp(self):
        km._PENDING_REVEAL[0] = None
        self._added = []

    def tearDown(self):
        with km._clients_lock:
            for c in self._added:
                if c in km._clients:
                    km._clients.remove(c)
        km._PENDING_REVEAL[0] = None

    def _register(self, app, wid):
        c, got = _fake_ws_client(app, wid)
        with km._clients_lock:
            km._clients.append(c)
        self._added.append(c)
        return c, got

    def test_connected_pane_gets_it_now_dead_session_gets_revive(self):
        c, got = self._register("chat", "W1")
        with mock.patch.object(km, "_tmux_sessions", return_value={"SID-live": {}}):
            self.assertTrue(km._reveal_request("SID-live", "W1"))
        self.assertEqual(got, [{"type": "focus", "id": "SID-live", "live": True}])
        self.assertIsNone(km._PENDING_REVEAL[0], "delivered → nothing parked")
        # a DEAD session never silently reveals — the revive prompt instead (_reveal_or_confirm's split)
        got.clear()
        with mock.patch.object(km, "_tmux_sessions", return_value={}), \
             mock.patch.object(km, "_name_of", return_value="web"):
            km._reveal_request("SID-gone", "W1")
        self.assertEqual(got[0]["type"], "confirmRevive")

    def test_boot_race_parks_then_ready_consumes_aimed_by_wid(self):
        # the norm: the shell's fetch beats its chat iframe's WS, so nothing is connected yet
        with mock.patch.object(km, "_tmux_sessions", return_value={"SID-live": {}}):
            self.assertFalse(km._reveal_request("SID-live", "W-phone"))
            self.assertEqual(km._PENDING_REVEAL[0], {"sid": "SID-live", "wid": "W-phone"})
            # another dashboard's pane saying ready must NOT steal it (the 2026-07-29 rule)
            other, other_got = _fake_ws_client("chat", "W-desktop")
            km._consume_pending_reveal(other)
            self.assertEqual(other_got, [])
            self.assertIsNotNone(km._PENDING_REVEAL[0])
            # a non-chat pane of the RIGHT window doesn't take it either
            feed, feed_got = _fake_ws_client("feed", "W-phone")
            km._consume_pending_reveal(feed)
            self.assertEqual(feed_got, [])
            # the aimed pane arrives → delivered once, latch cleared
            mine, mine_got = _fake_ws_client("chat", "W-phone")
            km._consume_pending_reveal(mine)
            self.assertEqual(mine_got, [{"type": "focus", "id": "SID-live", "live": True}])
            self.assertIsNone(km._PENDING_REVEAL[0])
            km._consume_pending_reveal(mine)
            self.assertEqual(len(mine_got), 1, "consumed means consumed")

    def test_a_widless_park_matches_the_first_chat_pane(self):
        # sessionStorage blocked → the shell has no wid; better the first chat pane than a dropped tap
        with mock.patch.object(km, "_tmux_sessions", return_value={"S": {}}):
            km._reveal_request("S", "")
            c, got = _fake_ws_client("chat", "W-any")
            km._consume_pending_reveal(c)
        self.assertEqual(got[0]["id"], "S")

    def test_a_booting_page_parks_past_the_previous_pages_socket(self):
        # the deep-link arrival (2026-09-06, the phone): the page is BOOTING, so its own chat pane
        # cannot be connected yet — a same-wid chat socket the kernel still holds is the PREVIOUS
        # page's (sessionStorage keeps the wid across a reload; a suspended phone never sent its
        # close, and the ping timeout has up to WS_DEAD_S to notice). "Delivering" there parked
        # nothing, and the new pane's ready found nothing to consume.
        twin, twin_got = self._register("chat", "W-phone")
        with mock.patch.object(km, "_tmux_sessions", return_value={"S": {}}):
            self.assertFalse(km._reveal_request("S", "W-phone", boot=True))
            self.assertEqual(twin_got, [], "a booting page's tap is never aimed at a socket that predates it")
            self.assertEqual(km._PENDING_REVEAL[0], {"sid": "S", "wid": "W-phone"})
            fresh, fresh_got = _fake_ws_client("chat", "W-phone")
            km._consume_pending_reveal(fresh)
        self.assertEqual(fresh_got, [{"type": "focus", "id": "S", "live": True}])
        self.assertIsNone(km._PENDING_REVEAL[0])

    def test_a_live_tap_to_an_unproven_socket_keeps_a_copy_until_the_pong_or_the_redial(self):
        # the live half of the same hole: the pane's socket has a ping on the wire nobody has
        # answered yet (pingAt set — the peer is unproven since the last heartbeat). The focus goes
        # out as before, AND stays parked: the pong that proves the socket alive retires the copy
        # (the frame is ordered behind the ping it answers); a dead socket never pongs, the pane
        # redials, and its ready consumes the copy instead of finding nothing.
        c, got = self._register("chat", "W1")
        c["pingAt"] = 100.0
        with mock.patch.object(km, "_tmux_sessions", return_value={"S": {}}):
            self.assertTrue(km._reveal_request("S", "W1"))
        self.assertEqual(got, [{"type": "focus", "id": "S", "live": True}], "still delivered at once")
        self.assertEqual((km._PENDING_REVEAL[0] or {}).get("sid"), "S", "…and kept until the socket proves itself")
        # another window's pane pongs: not this tap's socket, the copy stays
        other, _ = self._register("chat", "W2")
        other["pingAt"] = 100.0
        km._note_ws_inbound(other, now=101.0)
        self.assertIsNotNone(km._PENDING_REVEAL[0])
        # the delivered-to socket pongs → proven → the copy is retired, and a later ready replays nothing
        km._note_ws_inbound(c, now=101.0)
        self.assertIsNone(km._PENDING_REVEAL[0])
        c["pingAt"] = None
        with mock.patch.object(km, "_tmux_sessions", return_value={"S": {}}):
            self.assertTrue(km._reveal_request("S", "W1"))
        self.assertIsNone(km._PENDING_REVEAL[0], "a socket with no ping outstanding is proven — nothing parked")
        # the dead case: never pongs; the pane's redial says ready and takes the copy
        c["pingAt"] = 100.0
        with mock.patch.object(km, "_tmux_sessions", return_value={"S": {}}):
            km._reveal_request("S", "W1")
            fresh, fresh_got = _fake_ws_client("chat", "W1")
            km._consume_pending_reveal(fresh)
        self.assertEqual(fresh_got, [{"type": "focus", "id": "S", "live": True}])
        self.assertIsNone(km._PENDING_REVEAL[0])


class RevealRoute(unittest.TestCase):
    """POST /reveal over the real handler (the ServeSecurity pattern)."""

    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), km.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        km._PENDING_REVEAL[0] = None

    def _post(self, path, body, token=True):
        import urllib.request, urllib.error
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Romp-Token"] = km.TOKEN
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path),
                                     method="POST", data=json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_parks_for_the_named_wid(self):
        code, body = self._post("/reveal", {"sid": "SID-x", "wid": "W-x"})
        self.assertEqual(code, 200)
        self.assertFalse(json.loads(body)["delivered"])
        self.assertEqual(km._PENDING_REVEAL[0], {"sid": "SID-x", "wid": "W-x"})

    def test_requires_token_and_sid(self):
        code, _ = self._post("/reveal", {"sid": "S"}, token=False)
        self.assertEqual(code, 403)
        code, _ = self._post("/reveal", {"wid": "W"})
        self.assertEqual(code, 400)
        self.assertIsNone(km._PENDING_REVEAL[0])

    def test_a_boot_flagged_reveal_parks_even_past_a_connected_same_wid_pane(self):
        # the deep-link arrival says it is booting; the kernel parks for the pane that is about to
        # connect and never counts the previous page's socket as delivery (RevealAiming has the why)
        twin, twin_got = _fake_ws_client("chat", "W-x")
        with km._clients_lock:
            km._clients.append(twin)
        try:
            code, body = self._post("/reveal", {"sid": "SID-x", "wid": "W-x", "boot": True})
        finally:
            with km._clients_lock:
                km._clients.remove(twin)
        self.assertEqual(code, 200)
        self.assertFalse(json.loads(body)["delivered"])
        self.assertEqual(twin_got, [])
        self.assertEqual(km._PENDING_REVEAL[0], {"sid": "SID-x", "wid": "W-x"})

    def test_every_tap_leaves_a_line_in_the_kernel_log(self):
        # 2026-09-08: a phone's tap "did nothing" and nothing recorded whether it had reached the kernel.
        # The route logs the road the shell names, the flags and the outcome; the park's end logs too.
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            code, _ = self._post("/reveal", {"sid": "SID-x", "wid": "W-x", "via": "link", "boot": True})
            pane, got = _fake_ws_client("chat", "W-x")
            km._consume_pending_reveal(pane)
        self.assertEqual(code, 200)
        lines = [l for l in buf.getvalue().splitlines() if l.startswith("[reveal]")]
        self.assertEqual(lines, ["[reveal] link sid=SID-x wid=W-x boot: parked",
                                 "[reveal] sid=SID-x wid=W-x: consumed — the pane's ready"])
        self.assertEqual(len(got), 1)


class Badge(unittest.TestCase):
    """Proposal 3: the app icon wears the needs-you count."""

    def setUp(self):
        km._BADGE_LAST[0] = None

    def test_counts_real_needs_input_cards_only(self):
        feed = {"asks": [
            {"itemId": "a", "column": "needs_input"},
            {"itemId": "b", "column": "needs_input", "provisional": True},   # placeholder churn
            {"itemId": "c", "column": "working"},
            {"itemId": "d", "column": "completed"},
        ]}
        self.assertEqual(km._needs_you_count(feed), 1)

    def test_pushes_to_shells_only_on_change(self):
        sent = []
        with mock.patch.object(km, "_send_to_app", side_effect=lambda app, m: sent.append((app, m))):
            km._badge_push(2)
            km._badge_push(2)          # same number again — a re-send would be a pointless wake
            km._badge_push(0)          # dropping to zero IS a change: the icon must clear
        self.assertEqual(sent, [("shell", {"type": "badge", "n": 2}),
                                ("shell", {"type": "badge", "n": 0})])


class LandingRevealPins(unittest.TestCase):
    def test_shell_carries_both_halves_of_the_tap(self):
        html = km._landing()
        self.assertIn("m.romp==='notificationClick'", html)   # live window: the SW's message
        self.assertIn("m.romp==='pushReveal'", html)          # …or the shape a worker of an older build posts (2026-09-08)
        self.assertIn("searchParams.get('push-reveal')", html)  # cold start: the deep link's params…
        self.assertIn("searchParams.get('push-card')", html)
        self.assertIn("searchParams['delete']('push-reveal')", html)   # …stripped once read
        self.assertIn("history.replaceState", html)
        self.assertIn("fetch('/reveal'", html)     # ONE activation path: the kernel aims the focus…
        self.assertIn("romp:wid", html)            # …at the shell's own per-window id
        self.assertIn("romp:'revealCard'", html)   # a card kind also scrolls the feed to the card…
        self.assertIn("m.romp==='ready'&&m.app==='feed'", html)   # …once the feed has its cards
        self.assertNotIn("type:'focus',id:sid", html, "no focus posted straight into the chat iframe any more")
        self.assertNotIn("setTimeout", km._LANDING_REVEAL_JS, "event-based: the feed's ready, never a timer")

    def test_shell_ws_trues_up_the_badge(self):
        html = km._landing()
        self.assertIn("{type:'ready'}", html)      # connect → the kernel answers with the current count
        self.assertIn("setAppBadge", html)
        self.assertIn("clearAppBadge", html)       # zero clears, never leaves a stale number


# The shell's reveal script, EXECUTED (the test_error_center.py pattern): node runs
# _LANDING_REVEAL_JS against stubs of the few browser globals it touches, booting on a deep link
# and then replaying the worker's messages. Pins the routing, not the words: /reveal is asked
# with the shell's wid, the URL is stripped, the card waits for the FEED's ready (not the
# timeline's), a turn kind reveals no card, a test addressed to a session reveals it the same way,
# a sid-less tap does nothing, a refused /reveal is loud.
_REVEAL_HARNESS = r"""
'use strict';
const FETCHES = [], POSTED = [], NOTES = [], REPLACED = [], WIN = [], SW = [];
let fetchOk = true;
const feedWin = { postMessage: (m) => POSTED.push(m) };
global.window = global;
global.document = { getElementById: (id) => (id === 'f-feed' ? { contentWindow: feedWin } : null) };
global.sessionStorage = { getItem: (k) => (k === 'romp:wid' ? 'W-test' : null) };
global.addEventListener = (k, f) => { if (k === 'message') WIN.push(f); };
Object.defineProperty(global, 'navigator', { configurable: true,   // a getter-only global in node 22
  value: { serviceWorker: { addEventListener: (k, f) => { if (k === 'message') SW.push(f); } } } });
global.history = { replaceState: (s, t, u) => REPLACED.push(u) };
global.location = { href: 'http://localhost:7777/?push-reveal=S1&push-card=S1%3Ag1&keep=1#frag' };
global.fetch = (path, init) => { FETCHES.push([path, JSON.parse(init.body)]);
  return Promise.resolve(fetchOk ? { ok: true } : { ok: false, status: 400, text: () => Promise.resolve('missing sid') }); };
global.__rompNotify = (kind, text) => NOTES.push([kind, text]);
"""
_REVEAL_DRIVER = r"""
const tick = () => new Promise((r) => setTimeout(r, 0));
const swMsg = (m) => SW.forEach((f) => f({ data: m }));
const winMsg = (m) => WIN.forEach((f) => f({ data: m }));
(async () => {
  const out = { boot: { fetches: FETCHES.slice(), replaced: REPLACED.slice(), postedBeforeReady: POSTED.length } };
  winMsg({ romp: 'ready' });                              // the timeline's ready: not the feed's
  out.boot.postedAfterTimelineReady = POSTED.length;
  winMsg({ romp: 'ready', app: 'feed' });
  out.boot.postedAfterFeedReady = POSTED.slice();
  FETCHES.length = 0; POSTED.length = 0;
  swMsg({ romp: 'notificationClick', sid: 'S2', host: '', kind: 'card', cardId: 'S2:g4' });
  out.live = { fetches: FETCHES.slice(), posted: POSTED.slice() };
  FETCHES.length = 0; POSTED.length = 0;
  swMsg({ romp: 'notificationClick', sid: 'S3', host: '', kind: 'turn', cardId: '' });
  out.turn = { fetches: FETCHES.slice(), posted: POSTED.slice() };
  FETCHES.length = 0; POSTED.length = 0;
  swMsg({ romp: 'notificationClick', sid: '', host: '', kind: 'test', cardId: '' });
  out.test = { fetches: FETCHES.slice(), posted: POSTED.slice() };
  FETCHES.length = 0; POSTED.length = 0;
  swMsg({ romp: 'notificationClick', sid: 'S5', host: '', kind: 'test', cardId: '' });   // a test addressed to the session in front (2026-09-06)
  out.testSid = { fetches: FETCHES.slice(), posted: POSTED.slice() };
  FETCHES.length = 0; POSTED.length = 0;
  swMsg({ romp: 'pushReveal', sid: 'S6' });                                             // the worker of builds before 2026-09-06, still installed on a phone
  out.legacy = { fetches: FETCHES.slice(), posted: POSTED.slice() };
  fetchOk = false; FETCHES.length = 0;
  swMsg({ romp: 'notificationClick', sid: 'S-bad', kind: 'turn' });
  await tick(); await tick();
  out.refused = { notes: NOTES.slice() };
  console.log(JSON.stringify(out));
})();
"""


class LandingRevealExecutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess, tempfile as _tf
        with _tf.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(_REVEAL_HARNESS + km._LANDING_REVEAL_JS + _REVEAL_DRIVER)
            path = f.name
        try:
            r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        finally:
            os.unlink(path)
        assert r.returncode == 0, "the reveal script threw: " + r.stderr[:800]
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_cold_start_asks_the_kernel_at_once_and_strips_the_link(self):
        b = self.out["boot"]
        # boot:true — this page is booting, so its own chat pane is not connected yet; the kernel
        # parks for it rather than aiming at a same-wid socket the previous page left behind
        self.assertEqual(b["fetches"], [["/reveal", {"sid": "S1", "wid": "W-test", "via": "link", "boot": True}]])
        self.assertEqual(b["replaced"], ["/?keep=1#frag"], "only OUR params go; a reload must not replay the jump")

    def test_the_card_waits_for_the_feeds_own_ready(self):
        b = self.out["boot"]
        self.assertEqual(b["postedBeforeReady"], 0, "no listener yet, nothing to scroll to")
        self.assertEqual(b["postedAfterTimelineReady"], 0, "another pane's ready is not the feed's")
        self.assertEqual(b["postedAfterFeedReady"], [{"romp": "revealCard", "itemId": "S1:g1", "sid": "S1"}])

    def test_a_live_tap_routes_the_same_way(self):
        live = self.out["live"]
        self.assertEqual(live["fetches"], [["/reveal", {"sid": "S2", "wid": "W-test", "via": "sw"}]])
        self.assertEqual(live["posted"], [{"romp": "revealCard", "itemId": "S2:g4", "sid": "S2"}])

    def test_a_turn_focuses_without_a_card_and_a_sidless_test_lands_nowhere(self):
        self.assertEqual(len(self.out["turn"]["fetches"]), 1)
        self.assertEqual(self.out["turn"]["posted"], [])
        self.assertEqual(self.out["test"], {"fetches": [], "posted": []})

    def test_a_test_addressed_to_a_session_reveals_it_like_a_turn(self):
        # the user 2026-09-06: ANY sid lands, whatever the kind; only a card adds the card scroll
        self.assertEqual(self.out["testSid"], {"fetches": [["/reveal", {"sid": "S5", "wid": "W-test", "via": "sw"}]], "posted": []})

    def test_a_stale_workers_tap_still_lands(self):
        # the worker of builds before 2026-09-06 posts {romp:'pushReveal', sid}; a phone keeps running it
        # until a navigation refreshes it (2026-09-08) — the shell reads that shape too, never a silent miss
        self.assertEqual(self.out["legacy"], {"fetches": [["/reveal", {"sid": "S6", "wid": "W-test", "via": "sw"}]], "posted": []})

    def test_a_refused_reveal_is_loud(self):
        self.assertEqual(self.out["refused"]["notes"],
                         [["error", "Could not open the session this notification was about: missing sid"]])



class RailBell(unittest.TestCase):
    """The desktop rail carries the same bell as the mobile tab bar (the user 2026-08-08). Since
    2026-09-05 the pair OPENS THE POPOVER (tests/test_kernel_notify_popover.py) whose rows are the
    switches: the kernel-wide master (the user 2026-08-09's model: on = every task notifies unless
    its own bell mutes it), labelled "Notifications", and nested under it this device's push
    subscription — pulled apart so a phone turning itself off no longer silences every device, and
    nested so the master reads as the master, not as a scope beside "This device" (the user
    2026-09-05)."""

    def test_shell_serves_both_bells_and_one_flow_drives_them(self):
        status, body = _serve_get("/", headers={"X-Romp-Token": km.TOKEN})
        self.assertEqual(status, 200)
        page = body.decode()
        self.assertIn("id=rail-bell hidden", page, "the bells ship hidden; the wiring reveals them at boot")
        self.assertIn("id=mbell hidden", page, "the mobile bell is unchanged")
        # ONE wiring drives the pair — reveal, paint and busy all iterate the same list — so the
        # two bells can never disagree about the master's state
        self.assertIn("querySelectorAll('#mbell,#rail-bell')", page)
        self.assertNotIn("getElementById('mbell')", page, "the single-bell wiring is gone")
        # the rail bell paints its states exactly like the mobile one
        self.assertIn(".rail-acts #rail-bell.on{color:var(--accent)}", page)
        self.assertIn(".rail-acts #rail-bell.busy{opacity:.45}", page)
        # the on-state must survive the light theme, whose .rail-act recolor outspecifies the bare
        # `.on` rule — with no light restatement on and off rendered pixel-identical there (the
        # user 2026-09-02)
        self.assertIn("body.theme-light .rail-act.on{color:var(--accent)}", page)
        # …and OFF reads as a slashed bell — the app's one bell-off idiom (feed card bell, timeline
        # lane bell) — never a color difference alone
        self.assertEqual(page.count("class='bell-slash'"), 2, "both bells carry the slash glyph")
        self.assertIn(".bell-slash{display:none}", page)
        self.assertIn("#rail-bell:not(.on) .bell-slash,#mbell:not(.on) .bell-slash{display:block}", page)

    def test_the_bell_opens_the_popover_whose_rows_are_the_switches(self):
        # (2026-09-05: was "the bell is the master switch, not a device toggle" — the tap now opens
        # the popover; the Notifications row is the master and This-device, nested under it, is the
        # subscription. The pin moved from "All devices" the same day: that label read as a scope
        # choice, not the switch the rest sit under)
        _, body = _serve_get("/", headers={"X-Romp-Token": km.TOKEN})
        page = body.decode()
        # kernel-authoritative paint of the master: GET /notify-all at boot and the shell WS push
        # on every toggle, so every dashboard's row agrees
        self.assertIn("fetch('/notify-all')", page)
        self.assertIn("window.__rompNotifyAllPaint", page)
        self.assertIn("m.type==='notifyAll'", page, "the shell WS repaints every open dashboard")
        self.assertIn("post('/notify-all',{on:want})", page)
        self.assertIn("id=rbell-pop", page)
        self.assertIn("data-act=all", page)
        self.assertIn("data-act=dev", page)
        # the bell shows everywhere — the master matters even where the Push API is missing (the
        # kernel box still gets osascript, other devices still buzz); only the device row gates
        self.assertNotIn("('Notification' in window))return", page,
                         "the old whole-bell capability bail is gone")
        self.assertIn("var canPush=", page)
        # the permission ask still runs in the tap's own stack (iOS voids the gesture across awaits)
        self.assertIn("Notification.requestPermission():null", page)
        # the glyph is THIS device's truth now: master AND subscribed (tests/test_kernel_notify_popover.py)
        self.assertIn("var lit=isOn&&(canPush?devOn:true)", page)


class MasterBellRoute(unittest.TestCase):
    """GET/POST /notify-all — the master bell's kernel half (the user 2026-08-09). Live server for
    the POST (the SubscribeRoutes pattern: a fake socket cannot exercise Content-Length reads)."""

    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), km.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        try:
            (jd.STATE / "notify-cards.json").unlink()
        except OSError:
            pass
        km._notify_cards_cache.clear()

    def _post(self, path, body, token=True, raw=None):
        import urllib.request, urllib.error
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Romp-Token"] = km.TOKEN
        data = raw if raw is not None else json.dumps(body).encode()
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path),
                                     method="POST", data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_get_is_gated_and_reads_the_store(self):
        status, _ = _serve_get("/notify-all")
        self.assertEqual(status, 403, "the master state is behind the serve token like every page")
        status, body = _serve_get("/notify-all", headers={"X-Romp-Token": km.TOKEN})
        self.assertEqual((status, json.loads(body)), (200, {"on": False}))

    def test_post_flips_and_broadcasts(self):
        sent = []
        with mock.patch.object(km, "_send_to_app", side_effect=lambda app, m: sent.append((app, m))):
            code, body = self._post("/notify-all", {"on": True})
        self.assertEqual((code, json.loads(body)), (200, {"ok": True, "on": True}))
        self.assertTrue(km._notify_all_on())
        self.assertIn(("shell", {"type": "notifyAll", "on": True}), sent,
                      "every open dashboard's bell repaints on the toggle, not just the clicker's")
        _, body = _serve_get("/notify-all", headers={"X-Romp-Token": km.TOKEN})
        self.assertEqual(json.loads(body), {"on": True})
        code, _ = self._post("/notify-all", {"on": False})
        self.assertEqual(code, 200)
        self.assertFalse(km._notify_all_on())

    def test_post_requires_token_and_refuses_garbage(self):
        code, _ = self._post("/notify-all", {"on": True}, token=False)
        self.assertEqual(code, 403)
        code, _ = self._post("/notify-all", None, raw=b"not json")
        self.assertEqual(code, 400)
        self.assertFalse(km._notify_all_on(), "a refused body must not flip the master")


if __name__ == "__main__":
    unittest.main()
