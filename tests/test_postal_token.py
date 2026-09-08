#!/usr/bin/env python3
"""The postal bus is token-gated (Jupyter's model, shared with the kernel): every route
except the /ping liveness probe requires the machine's serve token — loopback included,
since loopback is reachable by every local user and the bus can wake sessions and inject
mail into their prompts. Accepted forms: X-Romp-Token (same-machine clients, read from
the 0600 file) and ?token= (a peer bus dialing through the ssh forward with the DIALED
machine's token). Also pins the peer-token plumbing: /peer notifies carry the peer's
token, a token-less down notify keeps the last known one, and the dialer sends ?token=.

Synthetic only — hermetic temp state dir, placeholder names, no real session data.
"""
import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")

# Hermetic state dir; the sessions-file seam signals "no live kernel" to the bus.
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
_SESS = os.path.join(os.environ["XDG_STATE_HOME"], "sessions.json")
Path(_SESS).write_text("[]")
os.environ["ROMP_SESSIONS_FILE"] = _SESS
ps = SourceFileLoader("romp_postal_token", os.path.join(BIN, "romp-postal-service")).load_module()

TOK = ps.SERVE_TOKEN


def _code(port, path, headers=None, method="GET", data=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path),
                                 headers=dict(headers or {}), method=method, data=data)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


class BusTokenGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), ps.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_ping_is_exempt(self):
        self.assertEqual(_code(self.port, "/ping"), 200)

    def test_tokenless_requests_denied(self):
        self.assertEqual(_code(self.port, "/agents"), 403)
        self.assertEqual(_code(self.port, "/peers"), 403)
        self.assertEqual(_code(self.port, "/inbox?id=x"), 403)
        self.assertEqual(_code(self.port, "/send", method="POST", data=b"{}"), 403)
        self.assertEqual(_code(self.port, "/peer", method="POST", data=b"{}"), 403)

    def test_header_token_authorizes(self):
        self.assertEqual(_code(self.port, "/peers", headers={"X-Romp-Token": TOK}), 200)

    def test_query_token_authorizes_the_peer_dial_form(self):
        # A peer bus dials /peer-exchange through the ssh forward with ?token= — same
        # acceptance on any route (here /peers, which needs no exchange payload).
        self.assertEqual(_code(self.port, "/peers?token=" + TOK), 200)

    def test_wrong_token_denied(self):
        self.assertEqual(_code(self.port, "/peers", headers={"X-Romp-Token": "wrong"}), 403)
        self.assertEqual(_code(self.port, "/peers?token=wrong"), 403)


class PeerTokenPlumbing(unittest.TestCase):
    def test_peer_update_stores_token_and_down_notify_keeps_it(self):
        ps.peer_update({"host": "TESTHOST", "port": 45001, "up": True, "token": "peer-tok"})
        self.assertEqual(ps.PEERS["TESTHOST"]["token"], "peer-tok")
        ps.peer_update({"host": "TESTHOST", "port": 45001, "up": False})   # down carries no token
        self.assertEqual(ps.PEERS["TESTHOST"]["token"], "peer-tok",
                         "a token-less transition must keep the last known peer token")
        ps.PEERS.pop("TESTHOST", None)

    def test_peer_http_sends_the_peer_token_as_query(self):
        seen = {}

        class Capture(BaseHTTPRequestHandler):
            def do_POST(self):
                seen["path"] = self.path
                body = json.dumps({}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Capture)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            ps._peer_http(srv.server_address[1], {"host": "TESTHOST"}, token="peer-tok")
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(seen.get("path"), "/peer-exchange?token=peer-tok")


class _BusServer(unittest.TestCase):
    """A live bus for the request-body classes below (no tests of its own): one server per class."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), ps.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def _post(self, path, raw):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=raw, method="POST",
                                     headers={"X-Romp-Token": TOK, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception as e:                        # the handler raised and the socket closed under us
            return None, {"error": repr(e)}

    def _raw(self, path, headers, body=b"", half_close=True):
        """One hand-built POST over a real socket -> (status, JSON body, response head): a header can be
        sent twice, and `half_close` ends the sending side after `body` so a short body reads as EOF."""
        lines = ["POST %s HTTP/1.1" % path, "Host: 127.0.0.1", "Connection: close",
                 "X-Romp-Token: " + TOK] + ["%s: %s" % kv for kv in headers]
        req = ("\r\n".join(lines) + "\r\n\r\n").encode() + body
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        try:
            s.sendall(req)
            if half_close:
                s.shutdown(socket.SHUT_WR)
            data = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
        finally:
            s.close()
        head, _, payload = data.partition(b"\r\n\r\n")
        return int(head.split(b" ", 2)[1]), json.loads(payload.decode() or "{}"), head.decode()


class BusBodiesAreObjects(_BusServer):
    """Every bus route takes a JSON OBJECT. _body() used to hand back whatever json.loads produced, so
    an array, string, number or null body reached `data.get(...)` and raised AttributeError out of the
    handler: the connection dropped with a traceback on the bus's stderr. Now: the bus's own JSON 400,
    naming what arrived; undecodable JSON keeps its refusal."""

    def test_a_non_object_body_is_a_400_naming_what_arrived(self):
        for raw, echo in ((b"[]", "[]"), (b'"x"', '"x"'), (b"1", "1"), (b"null", "null")):
            for path in ("/send", "/peer", "/peer-exchange"):
                st, r = self._post(path, raw)
                self.assertEqual(st, 400, (path, raw, r))
                self.assertEqual(r.get("error"), "body must be a JSON object, got " + echo, (path, raw))
        st, r = self._post("/send", b"{nope")
        self.assertEqual((st, r.get("error")), (400, "bad json"), "undecodable JSON keeps its refusal")

    def test_a_long_string_body_echoes_clipped_inside_its_quotes(self):
        st, r = self._post("/send", json.dumps("x" * 100_000).encode())
        self.assertEqual(st, 400, r)
        self.assertEqual(r["error"], 'body must be a JSON object, got "' + "x" * 60 + '\u2026"')
        self.assertLess(len(r["error"]), 100)


class BusBodyGate(_BusServer):
    """The bus reads a body only within bounds -- the kernel's gate, mirrored. _body() used to trust the
    first of two Content-Length headers, cap nothing, and pass whatever bytes arrived as the body."""

    def test_two_content_length_headers_are_400_and_close(self):
        st, r, head = self._raw("/send", [("Content-Length", "2"), ("Content-Length", "4")], body=b"{}{}")
        self.assertEqual((st, r.get("error")), (400, "body could not be read: more than one Content-Length header"))
        self.assertIn("Connection: close", head)

    def test_a_non_decimal_content_length_is_400(self):
        st, r, head = self._raw("/send", [("Content-Length", "12abc")], body=b"{}")
        self.assertEqual(st, 400, r)
        self.assertIn("invalid literal for a byte count", r.get("error", ""))

    def test_an_oversize_announcement_is_413_before_any_read(self):
        # announced past the cap, nothing sent: refused on the declared length before any read (the old
        # bus read to EOF, got b"", and answered "bad json")
        st, r, head = self._raw("/send", [("Content-Length", str(ps._POST_MAX_BYTES + 1))])
        self.assertEqual(st, 413, r)
        self.assertIn(str(ps._POST_MAX_BYTES), r.get("error", ""))
        self.assertIn("Connection: close", head)

    def test_a_body_shorter_than_announced_is_400_naming_the_shortfall(self):
        st, r, head = self._raw("/send", [("Content-Length", "100")], body=b'{"to": "ap')
        self.assertEqual((st, r.get("error")), (400, "body could not be read: read 10 of the 100 bytes Content-Length announced"))
        self.assertIn("Connection: close", head)

    def test_transfer_encoding_is_411(self):
        st, r, head = self._raw("/send", [("Transfer-Encoding", "chunked")], body=b"2\r\n{}\r\n0\r\n\r\n")
        self.assertEqual(st, 411, r)
        self.assertIn("Transfer-Encoding", r.get("error", ""))


class TrackedIsABoolean(_BusServer):
    """`tracked` arms a report-back delegation. Both doors coerced it with bool(), so the STRING "false"
    tracked a send. Now a non-boolean is refused -- HTTP /send with a 400 naming the field, the MCP tool
    in its error return -- before any recipient is resolved or the bus dialed. The MCP schema declares
    the field boolean and `romp mail send --tracked` sends True, so real callers are unchanged."""
    SID = "11111111-2222-3333-4444-555555555555"

    def test_http_send_refuses_a_string_tracked_before_resolving_anyone(self):
        for bad in ("false", "true", 1, "yes"):
            st, r = self._post("/send", json.dumps({"to": "api", "from": "web", "from_id": self.SID,
                                                    "body": "hello", "kind": "delegate", "tracked": bad}).encode())
            self.assertEqual(st, 400, (bad, r))
            self.assertEqual(r.get("error"), "'tracked' must be true or false, got %s" % json.dumps(bad))

    def test_the_mcp_tool_refuses_a_string_tracked_before_dialing_the_bus(self):
        dialed = []

        def http(*a, **k):
            dialed.append(a)
            raise ps.BusError("stubbed: the bus is not dialed here")
        saved = (ps._http, ps.my_name, ps.my_id, ps._heartbeat)
        ps._http, ps.my_name, ps.my_id, ps._heartbeat = http, (lambda: "web"), (lambda: self.SID), (lambda mid, me: None)
        try:
            for bad in ("false", "true", 1):
                text, is_err = ps._mcp_call("send_message", {"to": "api", "body": "hello", "kind": "delegate", "tracked": bad})
                self.assertTrue(is_err, (bad, text))
                self.assertIn("'tracked' must be true or false, got %s" % json.dumps(bad), text)
            self.assertEqual(dialed, [], "the bus is never dialed with a malformed flag")
            ps._mcp_call("send_message", {"to": "api", "body": "hello", "kind": "delegate", "tracked": True})
            self.assertEqual(dialed[0][:2], ("POST", "/send"))
            self.assertIs(dialed[0][2]["tracked"], True, "a real true rides the wire as itself")
        finally:
            ps._http, ps.my_name, ps.my_id, ps._heartbeat = saved


if __name__ == "__main__":
    unittest.main(verbosity=2)
