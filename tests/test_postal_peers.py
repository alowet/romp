#!/usr/bin/env python3
"""Peer-bus mode stage 1 (plans/postal-peer-buses.md): every machine runs its OWN bus — the
client-only special case is retired under the flag — and the kernel feeds the bus a peer table
over POST /peer on tunnel transitions. Synthetic only."""
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
pm = SourceFileLoader("romp_postal_peers", os.path.join(BIN, "romp-postal-service")).load_module()


class PeerMode(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("ROMP_POSTAL_PEERS", None)
        pm.PEERS.clear()

    def test_flag_retires_client_only(self):
        os.environ["ROMP_POSTAL_PEERS"] = "1"
        os.environ["ROMP_POSTAL_CLIENT_ONLY"] = "1"
        try:
            self.assertFalse(pm.is_client_only(),
                             "peer mode: every machine runs its own bus — client-only is retired")
        finally:
            os.environ.pop("ROMP_POSTAL_CLIENT_ONLY", None)

    def test_flag_off_client_only_unchanged(self):
        os.environ["ROMP_POSTAL_PEERS"] = "0"          # peer mode is the DEFAULT now; 0 = legacy scheme
        os.environ["ROMP_POSTAL_CLIENT_ONLY"] = "1"
        try:
            self.assertTrue(pm.is_client_only(), "legacy mode: the singleton scheme is untouched")
        finally:
            os.environ.pop("ROMP_POSTAL_CLIENT_ONLY", None)

    def test_peers_on_is_the_default(self):
        os.environ.pop("ROMP_POSTAL_PEERS", None)
        self.assertTrue(pm.peers_on(), "peer-bus mode is the default (the user's activation, 2026-07-20)")
        os.environ["ROMP_POSTAL_PEERS"] = "0"
        self.assertFalse(pm.peers_on(), "explicit 0 selects the legacy scheme")

    def test_peer_update_and_snapshot(self):
        payload, status = pm.peer_update({"host": "TESTHOST", "port": 50002, "up": True})
        self.assertEqual(status, 200)
        self.assertEqual(payload["up"], 1)
        snap = pm.peers_snapshot()["peers"]["TESTHOST"]
        self.assertEqual((snap["port"], snap["up"]), (50002, True))
        payload, status = pm.peer_update({"host": "TESTHOST", "port": 50002, "up": False})
        self.assertEqual(pm.peers_snapshot()["peers"]["TESTHOST"]["up"], False,
                         "a down transition keeps the row for introspection, marked down")
        self.assertEqual(payload["up"], 0)

    def test_peer_update_refuses_a_non_boolean_up_and_records_nothing(self):
        # `up` used to be coerced with bool(), so a notify carrying the STRING "false" marked the peer UP
        for bad in ("false", "true", 1, 0, "up"):
            payload, status = pm.peer_update({"host": "TESTHOST", "port": 50002, "up": bad})
            self.assertEqual(status, 400, (bad, payload))
            self.assertEqual(payload["error"], "'up' must be true or false, got %s" % json.dumps(bad))
        self.assertEqual(pm.PEERS, {}, "a refused notify records no row")
        payload, status = pm.peer_update({"host": "TESTHOST", "port": 50002, "up": False})
        self.assertEqual((status, pm.PEERS["TESTHOST"]["up"]), (200, False), "a real false rides through as itself")

    def test_peer_update_reads_an_explicit_null_up_as_absent(self):
        # the rule _as_bool states (review find, 2026-09-08): null is the absent case spelled out, so it
        # takes the field's default (down), where a string or a number is refused
        payload, status = pm.peer_update({"host": "TESTHOST", "port": 50002, "up": None})
        self.assertEqual(status, 200, payload)
        self.assertEqual(pm.PEERS["TESTHOST"]["up"], False)

    def test_peer_update_validates(self):
        for bad in ({}, {"host": "", "port": 1}, {"host": "h"}, {"host": "h", "port": "x"},
                    {"host": "h", "port": 0}, {"host": "h", "port": True}):
            payload, status = pm.peer_update(bad)
            self.assertEqual(status, 400, "rejected: %r" % (bad,))
        self.assertEqual(pm.PEERS, {}, "nothing recorded from rejected notifies")

    def test_origin_only_row_stores_trust_without_a_port(self):
        # Trust-by-origin (the user 2026-07-25): a tier for a host with no tunnel here. Portless,
        # no dialer, judged at delivery by true origin.
        payload, status = pm.peer_update({"host": "FARBOX", "trust": "trusted", "originOnly": True})
        self.assertEqual(status, 200)
        self.assertTrue(payload["originOnly"])
        row = pm.peers_snapshot()["peers"]["FARBOX"]
        self.assertEqual((row["port"], row["up"], row["trust"], row.get("originOnly")),
                         (None, False, "trusted", True))
        # applied to a CONNECTED row it touches only the trust — port/up/token survive
        pm.peer_update({"host": "HUB", "port": 50007, "up": True, "token": "tk", "trust": "trusted"})
        pm.peer_update({"host": "HUB", "trust": "directed", "originOnly": True})
        row = pm.peers_snapshot()["peers"]["HUB"]
        self.assertEqual((row["port"], row["up"], row["token"], row["trust"], row.get("originOnly")),
                         (50007, True, "tk", "directed", None))

    def test_origin_only_validates(self):
        for bad in ({"originOnly": True}, {"host": "h", "originOnly": True},
                    {"host": "h", "trust": "bogus", "originOnly": True}):
            payload, status = pm.peer_update(bad)
            self.assertEqual(status, 400, "rejected: %r" % (bad,))

    def test_via_reach_summarizes_far_spokes(self):
        pm.PEER_STATE.clear()
        try:
            import time as _t
            pm.PEER_STATE["hub"] = {"presence": [
                {"name": "a", "id": "1"},                       # the hub's own session — not via
                {"name": "b", "id": "2", "via": "FARBOX"},
                {"name": "c", "id": "3", "via": "FARBOX"},
                {"name": "d", "id": "4", "via": "PEERED"},      # directly peered here → excluded
            ], "seenAt": int(_t.time())}
            pm.peer_update({"host": "PEERED", "port": 50008, "up": True})
            pm.peer_update({"host": "FARBOX", "trust": "isolated", "originOnly": True})
            rows = pm.via_reach()
            self.assertEqual(len(rows), 1)
            r = rows[0]
            self.assertEqual((r["host"], r["via"], r["agents"], r["trust"]),
                             ("FARBOX", "hub", 2, "isolated"))
            self.assertEqual(pm.peers_snapshot()["viaReach"], rows,
                             "the snapshot carries the summary for the kernel's popover proxy")
        finally:
            pm.PEER_STATE.clear()

    def test_routes_are_wired(self):
        import inspect
        src = inspect.getsource(pm)
        self.assertIn('if u.path == "/peer":', src)
        self.assertIn('if u.path == "/peers":', src)


if __name__ == "__main__":
    unittest.main()


_B_STATE = tempfile.mkdtemp()
os.environ["XDG_STATE_HOME"] = _B_STATE
pmb = SourceFileLoader("romp_postal_peers_b", os.path.join(BIN, "romp-postal-service")).load_module()


class _TwoBusHarness(unittest.TestCase):
    """The two-bus harness (plans/postal-peer-buses.md): A and B are two module instances with
    separate state dirs; the "tunnel" is a direct call — A builds a request, B handles it, A applies
    the response. No tests of its own: TwoBusExchange and ExchangeRelaysAreBudgeted run on it."""

    def setUp(self):
        os.environ["ROMP_POSTAL_PEERS"] = "1"
        self._saved = (pm.self_host, pmb.self_host, pm.local_agents, pmb.local_agents,
                       pm.local_agents_checked, pmb.local_agents_checked)
        pm.self_host = lambda: "hosta"
        pmb.self_host = lambda: "hostb"
        pm.local_agents = lambda threads=False: [{"name": "alpha", "id": "sid-a", "dir": ""}]
        pmb.local_agents = lambda threads=False: [{"name": "beta", "id": "sid-b", "dir": ""}]
        # _relay_in and fleet_presence rule from the CHECKED seam now (2026-08-31): same stub
        # rows, answered=True — the harness's world is authoritative
        pm.local_agents_checked = lambda threads=False: (pm.local_agents(), True)
        pmb.local_agents_checked = lambda threads=False: (pmb.local_agents(), True)
        for m in (pm, pmb):
            m.PEER_STATE.clear()
            m.PEERS.clear()
            m._peer_pending.clear()
            m._seen_ids = None
        import shutil
        for m in (pm, pmb):
            shutil.rmtree(m.OUTBOX, ignore_errors=True)
            shutil.rmtree(m.MAILROOT, ignore_errors=True)
            try:
                m.PEER_SEEN.unlink()
            except Exception:
                pass
            m.MAILROOT.mkdir(parents=True, exist_ok=True)
        # In production the kernel's /peer notify (peer_update) populates PEERS with each host's trust,
        # and the inbound gate HOLDS a directed peer's mail. These tests exercise the exchange/relay
        # MECHANICS, so mark the exchanged peers trusted (the gate keys on the relay's origin host: B sees
        # A's self_host "hosta"; A's dialer-apply uses the "srv" alias). Trust itself is covered in
        # test_postal_quarantine.py.
        pmb.PEERS["hosta"] = {"port": 1, "up": True, "trust": "trusted"}
        pm.PEERS["srv"] = {"port": 1, "up": True, "trust": "trusted"}

    def tearDown(self):
        os.environ.pop("ROMP_POSTAL_PEERS", None)
        (pm.self_host, pmb.self_host, pm.local_agents, pmb.local_agents,
         pm.local_agents_checked, pmb.local_agents_checked) = self._saved

    def _exchange(self):
        req = pm.build_exchange_request("srv", wait=False)
        resp, status = pmb.peer_exchange_handle(req)
        self.assertEqual(status, 200)
        pm.peer_exchange_apply("srv", req, resp)
        return resp


class TwoBusExchange(_TwoBusHarness):
    """Covers mail both directions, end-to-end acks, dedupe on a resent relay, bounce to the sender on a
    dead recipient, presence gossip, and the version handshake."""

    def test_quarantine_holds_cross_the_exchange_both_ways(self):
        # Slice 4 of the federation UI (the user 2026-07-25): each side's exchange payload carries a
        # summary of ITS held mail, so a hold is visible from the peer instead of only on the
        # holding machine's own dashboard.
        import shutil
        for m in (pm, pmb):
            shutil.rmtree(m.QUARANTINE, ignore_errors=True)
        try:
            pmb.QUARANTINE.mkdir(parents=True, exist_ok=True)
            (pmb.QUARANTINE / "h1.json").write_text(json.dumps(
                {"mid": "h1", "to": "beta", "frm": "api", "origin": "TESTHOST",
                 "body": "please review the parser fix before it merges", "at": 1000}))
            pm.QUARANTINE.mkdir(parents=True, exist_ok=True)
            (pm.QUARANTINE / "h2.json").write_text(json.dumps(
                {"mid": "h2", "to": "alpha", "frm": "web", "origin": "", "body": "ping", "at": 1001}))
            self._exchange()
            got = pm.PEER_STATE["srv"]["holds"]
            self.assertEqual([(h["mid"], h["frm"], h["to"], h["origin"]) for h in got],
                             [("h1", "api", "beta", "TESTHOST")], "B's hold arrived at A")
            self.assertIn("please review the parser fix", got[0]["gist"])
            self.assertEqual(pm.remote_holds()[0]["atHost"], "srv",
                             "stamped with the machine HOLDING it")
            got_b = pmb.PEER_STATE["hosta"]["holds"]
            self.assertEqual([h["mid"] for h in got_b], ["h2"], "A's hold rode the request to B")
        finally:
            for m in (pm, pmb):
                shutil.rmtree(m.QUARANTINE, ignore_errors=True)

    def test_mail_crosses_and_acks_clear_the_outbox(self):
        pm.outbox_put("srv", {"mid": "m1", "to": "beta", "frm": "alpha", "frm_id": "sid-a",
                              "body": "hello over the wire", "kind": "question", "t": 1})
        self._exchange()
        box = pmb.read_box("sid-b", consume=True)
        self.assertEqual(len(box), 1, "the relay delivered on B")
        self.assertIn("hello over the wire", box[0]["body"])
        self.assertEqual(box[0]["kind"], "question", "the declared kind rides the relay")
        self.assertEqual(pm.outbox_list("srv"), [], "B's ack cleared A's outbox")
        self.assertEqual(pmb.PEER_STATE["hosta"]["presence"][0]["name"], "alpha", "presence gossiped A to B")
        self.assertEqual(pm.PEER_STATE["srv"]["presence"][0]["name"], "beta", "presence gossiped B to A")

    def test_resent_relay_delivers_exactly_once(self):
        pm.outbox_put("srv", {"mid": "m2", "to": "beta", "frm": "alpha", "frm_id": "sid-a",
                              "body": "once", "kind": "", "t": 1})
        req = pm.build_exchange_request("srv", wait=False)
        r1, _ = pmb.peer_exchange_handle(req)
        r2, _ = pmb.peer_exchange_handle(req)          # the link flapped before the ack → A resent
        self.assertIn("m2", r1["acks"])
        self.assertIn("m2", r2["acks"], "the duplicate is re-acked, never re-delivered")
        self.assertEqual(len(pmb.read_box("sid-b", consume=True)), 1, "exactly one delivery")

    def test_dead_recipient_bounces_to_the_sender(self):
        pm.outbox_put("srv", {"mid": "m3", "to": "ghost", "frm": "alpha", "frm_id": "sid-a",
                              "body": "boo", "kind": "", "t": 1})
        self._exchange()
        self.assertEqual(pm.outbox_list("srv"), [], "a definitive refusal never stays parked")
        back = pm.read_box("sid-a", consume=True)
        self.assertEqual(len(back), 1, "the sender got the bounce note")
        self.assertIn("undeliverable to 'ghost'", back[0]["body"])
        self.assertEqual(back[0]["from"], "romp-postal", "bus-authored, clearly not a peer message")

    def test_return_mail_rides_the_response_and_acks_the_next_request(self):
        pmb.outbox_put("hosta", {"mid": "m4", "to": "alpha", "frm": "beta", "frm_id": "sid-b",
                                 "body": "reply", "kind": "", "t": 1})
        self._exchange()
        self.assertEqual(len(pm.read_box("sid-a", consume=True)), 1, "B-to-A mail rode the response")
        self.assertEqual(len(pmb.outbox_list("hosta")), 1, "B holds it until the end-to-end ack")
        self._exchange()
        self.assertEqual(pmb.outbox_list("hosta"), [], "the next request's ack cleared B's outbox")

    def test_version_drift_refuses_politely(self):
        req = pm.build_exchange_request("srv", wait=False)
        req["proto"] = 999
        resp, status = pmb.peer_exchange_handle(req)
        self.assertEqual(status, 409)
        self.assertIn("drift", resp["error"])

    def test_peer_route_resolves_and_disambiguates(self):
        pm.PEER_STATE["srv"] = {"presence": [{"name": "beta", "id": "sid-b"}], "seenAt": 1}
        pm.PEER_STATE["other"] = {"presence": [{"name": "beta", "id": "sid-c"}], "seenAt": 1}
        host, hits = pm.peer_route("beta")
        self.assertIsNone(host, "two hosts own 'beta' → ambiguous")
        self.assertEqual(len(hits), 2)
        host, hit = pm.peer_route("srv:beta")
        self.assertEqual(host, "srv", "host:name breaks the tie")
        self.assertEqual(hit["id"], "sid-b")


_C_STATE = tempfile.mkdtemp()
os.environ["XDG_STATE_HOME"] = _C_STATE
pmc = SourceFileLoader("romp_postal_peers_c", os.path.join(BIN, "romp-postal-service")).load_module()


class ThreeBusRelay(unittest.TestCase):
    """Spoke-to-spoke through a shared hub (plans/postal-peer-buses.md 3b): A and C each exchange only
    with hub B. Presence gossips one hop with a `via` label; a relay for a far spoke forwards ONE hop
    with end-to-end acks relayed backward, so the origin keeps mail parked until the FAR side delivers."""

    def setUp(self):
        os.environ["ROMP_POSTAL_PEERS"] = "1"
        self._saved = (pm.self_host, pmb.self_host, pmc.self_host,
                       pm.local_agents, pmb.local_agents, pmc.local_agents,
                       pm.local_agents_checked, pmb.local_agents_checked, pmc.local_agents_checked)
        pm.self_host = lambda: "hosta"
        pmb.self_host = lambda: "hostb"
        pmc.self_host = lambda: "hostc"
        pm.local_agents = lambda threads=False: [{"name": "alpha", "id": "sid-a", "dir": ""}]
        pmb.local_agents = lambda threads=False: [{"name": "beta", "id": "sid-b", "dir": ""}]
        pmc.local_agents = lambda threads=False: [{"name": "carol", "id": "sid-c", "dir": ""}]
        # _relay_in and fleet_presence rule from the CHECKED seam now (2026-08-31)
        pm.local_agents_checked = lambda threads=False: (pm.local_agents(), True)
        pmb.local_agents_checked = lambda threads=False: (pmb.local_agents(), True)
        pmc.local_agents_checked = lambda threads=False: (pmc.local_agents(), True)
        import shutil
        for m in (pm, pmb, pmc):
            m.PEER_STATE.clear()
            m.PEERS.clear()
            m._peer_pending.clear()
            m._seen_ids = None
            shutil.rmtree(m.OUTBOX, ignore_errors=True)
            shutil.rmtree(m.MAILROOT, ignore_errors=True)
            try:
                m.PEER_SEEN.unlink()
            except Exception:
                pass
            m.MAILROOT.mkdir(parents=True, exist_ok=True)
        # Mechanics test → mark the origin trusted so the inbound gate delivers (see TwoBusExchange.setUp).
        # The gate keys on the relay's ORIGIN host: B delivers to beta and C delivers a forwarded message
        # whose origin is "hosta" (B stamps origin when it forwards). Trust itself: test_postal_quarantine.
        pmb.PEERS["hosta"] = {"port": 1, "up": True, "trust": "trusted"}
        pmc.PEERS["hosta"] = {"port": 1, "up": True, "trust": "trusted"}
        # A forwarded message is ALSO capped at the forwarder's own tier (2026-08-05: a relay must
        # not out-rank itself by stamping an origin — test_postal_quarantine owns that rule), so the
        # hub C actually exchanges with needs a tier of its own. A real deployment always has one:
        # the kernel notifies a row for every host you dial. Without it the hub reads as an unknown
        # host, i.e. directed, and the relayed mail is HELD — correct, but the trust tests' business,
        # not this one's, which is about relay mechanics and end-to-end acks.
        pmc.PEERS["hub"] = {"port": 1, "up": True, "trust": "trusted"}

    def tearDown(self):
        os.environ.pop("ROMP_POSTAL_PEERS", None)
        (pm.self_host, pmb.self_host, pmc.self_host,
         pm.local_agents, pmb.local_agents, pmc.local_agents,
         pm.local_agents_checked, pmb.local_agents_checked, pmc.local_agents_checked) = self._saved

    def _xchg(self, dialer, dialed, alias):
        req = dialer.build_exchange_request(alias, wait=False)
        resp, status = dialed.peer_exchange_handle(req)
        self.assertEqual(status, 200)
        dialer.peer_exchange_apply(alias, req, resp)

    def test_far_spoke_gossips_via_the_hub(self):
        self._xchg(pmc, pmb, "hub")                  # B learns carol
        self._xchg(pm, pmb, "hub")                   # A learns beta directly and carol via the hub
        names = {(a.get("name"), a.get("via")) for a in pm.PEER_STATE["hub"]["presence"]}
        self.assertIn(("beta", None), names)
        self.assertIn(("carol", "hostc"), names, "the far spoke arrives labeled via, one hop only")

    def test_far_holds_gossip_via_the_hub_one_hop_only(self):
        # A hold TWO machines away (on C) reaches A labeled via the hub — and never re-gossips
        # further (the same one-hop rule as presence).
        import shutil
        for m in (pm, pmb, pmc):
            shutil.rmtree(m.QUARANTINE, ignore_errors=True)
        try:
            pmc.QUARANTINE.mkdir(parents=True, exist_ok=True)
            (pmc.QUARANTINE / "h9.json").write_text(json.dumps(
                {"mid": "h9", "to": "carol", "frm": "ops", "origin": "RENTBOX",
                 "body": "held on the far spoke", "at": 1002}))
            self._xchg(pmc, pmb, "hub")              # B learns C's hold (direct, no via)
            self._xchg(pm, pmb, "hub")               # A learns it via the hub
            got = [h for h in pm.PEER_STATE["hub"]["holds"] if h["mid"] == "h9"]
            self.assertEqual(len(got), 1)
            self.assertEqual(got[0].get("via"), "hostc", "labeled with the machine holding it")
            self.assertEqual([r["atHost"] for r in pm.remote_holds() if r["mid"] == "h9"],
                             ["hostc"])
            self.assertNotIn("via", [k for h in pmb.PEER_STATE["hostc"]["holds"] for k in h
                                     if k == "via"], "the direct hop carries no via label")
            # A never re-gossips the via-labeled hold onward (one hop, like presence)
            self.assertEqual([h for h in pm.holds_payload("elsewhere") if h["mid"] == "h9"], [])
        finally:
            for m in (pm, pmb, pmc):
                shutil.rmtree(m.QUARANTINE, ignore_errors=True)

    def test_relay_hops_once_with_end_to_end_acks(self):
        self._xchg(pmc, pmb, "hub")
        self._xchg(pm, pmb, "hub")
        host, hit = pm.peer_route("carol")
        self.assertEqual(host, "hub", "A reaches carol through the peer it can dial")
        pm.outbox_put("hub", {"mid": "r1", "to": "carol", "frm": "alpha", "frm_id": "sid-a",
                              "body": "over the hub", "kind": "delegate", "t": 1})
        self._xchg(pm, pmb, "hub")                   # A→B: B forwards, does NOT ack yet
        self.assertEqual(len(pm.outbox_list("hub")), 1,
                         "the origin keeps it parked until the FAR side's ack (end-to-end)")
        self.assertEqual(len(pmb.outbox_list("hostc")), 1, "the hub holds it forwarded for C")
        self._xchg(pmc, pmb, "hub")                  # C→B: the response carries the relay → C delivers
        box = pmc.read_box("sid-c", consume=True)
        self.assertEqual(len(box), 1, "delivered on the far spoke")
        self.assertIn("over the hub", box[0]["body"])
        self._xchg(pmc, pmb, "hub")                  # C's next request acks → B routes it backward
        self.assertEqual(pmb.outbox_list("hostc"), [], "C's ack cleared the hub's forward")
        self._xchg(pm, pmb, "hub")                   # A's next exchange picks the relayed ack up
        self.assertEqual(pm.outbox_list("hub"), [], "the end-to-end ack finally clears the origin")

    def test_far_bounce_relays_backward_to_the_sender(self):
        self._xchg(pmc, pmb, "hub")
        self._xchg(pm, pmb, "hub")
        pm.outbox_put("hub", {"mid": "r2", "to": "carol", "frm": "alpha", "frm_id": "sid-a",
                              "body": "too late", "kind": "", "t": 1})
        self._xchg(pm, pmb, "hub")                   # forwarded
        pmc.local_agents = lambda threads=False: []                # carol died before delivery
        self._xchg(pmc, pmb, "hub")                  # C receives the relay → bounces it
        self._xchg(pmc, pmb, "hub")                  # C's bounce rides its next request → B routes backward
        self._xchg(pm, pmb, "hub")                   # A picks the bounce up → sender gets the note
        back = pm.read_box("sid-a", consume=True)
        self.assertEqual(len(back), 1, "the far refusal came all the way back")
        self.assertIn("undeliverable to 'carol'", back[0]["body"])
        self.assertEqual(pm.outbox_list("hub"), [], "nothing left parked after a definitive refusal")

    def test_a_hopped_message_never_hops_again(self):
        m = {"mid": "r3", "to": "nobody-anywhere", "frm": "alpha", "frm_id": "sid-a",
             "body": "x", "kind": "", "t": 1, "origin": "hosta"}
        pmb.PEER_STATE["hostc"] = {"presence": [{"name": "nobody-anywhere", "id": "sid-x"}], "seenAt": 1}
        verdict, bounce = pmb._relay_in("hosta", m)
        self.assertEqual(verdict, "bounce", "one hop max: an already-hopped message bounces, never re-forwards")
        self.assertIn("no live session", bounce["why"])


class ExchangeRelaysAreBudgeted(_TwoBusHarness):
    """One exchange carries the outbox's oldest-first prefix under _RELAY_BUDGET_BYTES (half the dialed
    bus's 1 MiB body cap); the rest ride the next round. The request used to carry the WHOLE outbox
    (review find, 2026-09-08): a backlog past the cap was 413'd by the dialed bus's _body gate and the
    dialer re-sent the identical request on every backoff, forever, so every message to that peer parked
    on a healthy link. A single relay over the budget is bounced to its sender instead of retried."""

    def _park(self, n, size, prefix="big"):
        for i in range(n):
            pm.outbox_put("srv", {"mid": "%s%02d" % (prefix, i), "to": "beta", "frm": "alpha", "frm_id": "sid-a",
                                  "body": "R" * size, "kind": "coordinate", "t": i})

    def test_a_backlog_past_the_cap_drains_over_successive_exchanges(self):
        self._park(12, 100_000)
        self.assertGreater(len(json.dumps({"relays": pm.outbox_list("srv")}).encode()), pm._POST_MAX_BYTES,
                           "the whole outbox would not fit one request")
        rounds = 0
        while pm.outbox_list("srv") and rounds < 10:
            req = pm.build_exchange_request("srv", wait=False)
            self.assertLessEqual(len(json.dumps(req).encode("utf-8")), pm._POST_MAX_BYTES,
                                 "every request fits the dialed bus's cap")
            self.assertTrue(req["relays"], "progress every round")
            resp, status = pmb.peer_exchange_handle(req)
            self.assertEqual(status, 200)
            pm.peer_exchange_apply("srv", req, resp)
            rounds += 1
        self.assertEqual(pm.outbox_list("srv"), [], "the backlog drained")
        self.assertGreaterEqual(rounds, 2, "over more than one exchange")
        box = pmb.read_box("sid-b", consume=True)
        self.assertEqual(len(box), 12, "every message arrived exactly once")
        self.assertEqual(sorted(len(m["body"]) for m in box), [100_000] * 12)

    def test_a_name_collision_on_the_dialed_side_loses_no_message(self):
        """The drain test above failed once on CI with 11 of 12 (2026-09-08, on a PR that touched no postal
        code) and passed on either side of it. The dialed side names every message it lands by
        _unique() — the second, the pid and five random digits, 100k names per second per process — and
        deliver() published with rename(), which silently REPLACES a standing new/<name>. Two relays
        landing in one second with the same draw became one file: the first sender's message gone, both
        relays acked, both ledgers reading delivered (a drain of twelve loses one about once in 1500).
        Drives that collision exactly, through the mint the drain reads: the second mint returns the
        first's name. The standing message stays, the collided relay is refused rather than acked
        (silence on the wire, so the sender's outbox keeps it), and it rides the next exchange under a
        fresh name."""
        for i in range(12):
            pm.outbox_put("srv", {"mid": "big%02d" % i, "to": "beta", "frm": "alpha", "frm_id": "sid-a",
                                  "body": ("%02d" % i).ljust(100_000, "R"), "kind": "coordinate", "t": i})
        real, minted = pmb._unique, []

        def collide_once():
            name = real()
            minted.append(name)
            return minted[0] if len(minted) == 2 else name    # the drain's second mint repeats its first

        pmb._unique = collide_once
        acked = []
        try:
            rounds = 0
            while pm.outbox_list("srv") and rounds < 10:
                req = pm.build_exchange_request("srv", wait=False)
                resp, status = pmb.peer_exchange_handle(req)
                self.assertEqual(status, 200)
                acked.append(resp["acks"])
                pm.peer_exchange_apply("srv", req, resp)
                rounds += 1
        finally:
            pmb._unique = real
        self.assertEqual(pm.outbox_list("srv"), [], "the backlog drained")
        box = pmb.read_box("sid-b", consume=True)
        self.assertEqual(len(box), 12, "every message arrived exactly once")
        self.assertEqual(sorted(m["body"][:2] for m in box), ["%02d" % i for i in range(12)],
                         "the collided message included, under its own name")
        self.assertEqual(len({m["id"] for m in box}), 12, "under twelve distinct names")
        self.assertNotIn("big01", acked[0], "the relay that hit the collision was not acked")
        self.assertIn("big01", acked[1], "it rode the next exchange and landed")
        self.assertEqual(len(minted), 13, "one extra mint: the refused relay was named afresh on its next ride")

    def test_a_refused_collision_leaves_the_standing_message_s_ledger_alone(self):
        """The first cut of the collision refusal wrote the row before the publish, and under this same
        forced collision it filed the refused message's `sent` row and then the refusal's `bounced` row
        under the colliding name — the STANDING message's id — so the dialed side's ledger (its timeline,
        its receipts, every reader that takes a bounced row on a sent id as terminal) showed a delivered
        message as bounced. The publish is the claim on the name now and the row follows it: the refusal
        writes nothing, the standing message keeps its one `sent` row, and the retry lands under a fresh
        id with a row of its own."""
        for i in range(3):
            pm.outbox_put("srv", {"mid": "m%d" % i, "to": "beta", "frm": "alpha", "frm_id": "sid-a",
                                  "body": "note %d" % i, "kind": "coordinate", "t": i})
        ledger = pmb.TLDIR / "messages.jsonl"

        def rows():
            return [json.loads(l) for l in ledger.read_text().splitlines() if l] if ledger.exists() else []

        before = len(rows())
        real, minted = pmb._unique, []

        def collide_once():
            name = real()
            minted.append(name)
            return minted[0] if len(minted) == 2 else name    # the drain's second mint repeats its first

        pmb._unique = collide_once
        try:
            rounds = 0
            while pm.outbox_list("srv") and rounds < 10:
                self._exchange()
                rounds += 1
        finally:
            pmb._unique = real
        self.assertEqual(pm.outbox_list("srv"), [], "the backlog drained")
        self.assertEqual(len(minted), 4, "three lands, plus the refused relay's fresh name on its next ride")
        standing, fresh = minted[0], minted[-1]
        self.assertNotEqual(fresh, standing)
        added = rows()[before:]
        self.assertEqual([r["ev"] for r in added if r["id"] == standing], ["sent"],
                         "the standing message has exactly one sent row and no bounced row")
        self.assertEqual([r["ev"] for r in added], ["sent"] * 3, "three messages, three sent rows, nothing bounced")
        by_id = {r["id"]: r for r in added}
        self.assertEqual(len(by_id), 3, "three distinct ids: the refusal wrote no row under the standing id")
        self.assertEqual(by_id[standing]["originMid"], "m0", "the standing message's one row is its own")
        self.assertEqual(by_id[fresh]["originMid"], "m1", "the refused relay landed under a fresh id with its own row")
        # the receipts reader on the dialed side: nothing about the standing message reads bounced
        recs = {r["id"]: r for r in pmb._sent_receipts("sid-a")}
        self.assertIsNone(recs[standing]["bounced"], "the standing message's receipt is not bounced")
        self.assertIsNone(recs[fresh]["bounced"])
        self.assertEqual(recs[standing]["to"], "beta")

    def test_the_budget_holds_through_the_dialed_bus_s_own_body_gate(self):
        # the HTTP layer in the path: the dialed bus's _body reads a request only up to _POST_MAX_BYTES,
        # and a 413 would raise out of _peer_http here
        self._park(12, 100_000)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), pmb.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            rounds = 0
            while pm.outbox_list("srv") and rounds < 10:
                req = pm.build_exchange_request("srv", wait=False)
                resp = pm._peer_http(srv.server_address[1], req, token=pmb.SERVE_TOKEN)
                pm.peer_exchange_apply("srv", req, resp)
                rounds += 1
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(pm.outbox_list("srv"), [])
        self.assertEqual(len(pmb.read_box("sid-b", consume=True)), 12)

    def test_a_single_relay_over_the_budget_is_bounced_to_its_sender_naming_the_size(self):
        logged, saved = [], pm._log
        pm._log = lambda msg: logged.append(msg)
        try:
            pm.outbox_put("srv", {"mid": "huge", "to": "beta", "frm": "alpha", "frm_id": "sid-a",
                                  "body": "Z" * (pm._RELAY_BUDGET_BYTES + 1000), "kind": "coordinate", "t": 1})
            pm.outbox_put("srv", {"mid": "small", "to": "beta", "frm": "alpha", "frm_id": "sid-a",
                                  "body": "hi", "kind": "", "t": 2})
            req = pm.build_exchange_request("srv", wait=False)
        finally:
            pm._log = saved
        self.assertEqual([m["mid"] for m in req["relays"]], ["small"], "the oversize relay never rides")
        self.assertEqual([m["mid"] for m in pm.outbox_list("srv")], ["small"], "and left the outbox")
        back = pm.read_box("sid-a", consume=True)
        self.assertEqual(len(back), 1, "the sender got the bounce note")
        self.assertIn("undeliverable to 'beta' on srv", back[0]["body"])
        self.assertIn("exceeds the %d-byte relay limit" % pm._RELAY_BUDGET_BYTES, back[0]["body"])
        self.assertNotIn("ZZZZ", back[0]["body"], "the note names the size instead of repeating the body")
        self.assertEqual(back[0]["from"], "romp-postal")
        self.assertTrue(any("relay huge is" in l and "bounced to its sender" in l for l in logged), logged)

    def test_a_forwarded_relay_over_the_budget_bounces_backward_to_its_origin(self):
        pm.outbox_put("srv", {"mid": "fwd", "to": "beta", "frm": "gamma", "frm_id": "sid-c", "origin": "hostc",
                              "body": "Z" * (pm._RELAY_BUDGET_BYTES + 1000), "kind": "", "t": 1})
        req = pm.build_exchange_request("srv", wait=False)
        self.assertEqual(req["relays"], [])
        self.assertEqual(pm.outbox_list("srv"), [])
        b = pm._pending("hostc")["bounces"]
        self.assertEqual(len(b), 1, "the bounce rides back to the origin on its next exchange")
        self.assertEqual(b[0]["mid"], "fwd")
        self.assertIn("relay limit", b[0]["why"])
        self.assertTrue(b[0]["omitBody"])
        self.assertEqual(pm.read_box("sid-c", consume=True), [], "nothing lands locally for mail we only forwarded")

    def test_the_dialed_side_budgets_its_response_relays_too(self):
        for i in range(12):
            pmb.outbox_put("hosta", {"mid": "back%02d" % i, "to": "alpha", "frm": "beta", "frm_id": "sid-b",
                                     "body": "Q" * 100_000, "kind": "", "t": i})
        resp = self._exchange()
        self.assertLess(len(resp["relays"]), 12)
        self.assertLessEqual(len(json.dumps(resp["relays"]).encode()), pm._RELAY_BUDGET_BYTES)
        rounds = 1
        while pmb.outbox_list("hosta") and rounds < 10:   # each request acks the last response's relays
            self._exchange()
            rounds += 1
        self.assertEqual(pmb.outbox_list("hosta"), [])
        self.assertEqual(len(pm.read_box("sid-a", consume=True)), 12)


class RecallAndReceipts(unittest.TestCase):
    def setUp(self):
        os.environ["ROMP_POSTAL_PEERS"] = "1"
        import shutil
        shutil.rmtree(pm.OUTBOX, ignore_errors=True)
        try:
            (pm.TLDIR / "messages.jsonl").unlink()
        except Exception:
            pass

    def tearDown(self):
        os.environ.pop("ROMP_POSTAL_PEERS", None)

    def test_recall_reaches_the_outbox(self):
        pm.outbox_put("srv", {"mid": "q1", "to": "beta", "frm": "alpha", "frm_id": "sid-a",
                              "body": "changed my mind", "kind": "", "t": 1})
        removed = pm._recall("sid-a", "", "q1")
        self.assertEqual([r["id"] for r in removed], ["q1"], "a recall that beats the truck wins")
        self.assertEqual(pm.outbox_list("srv"), [], "the parked message is gone")

    def test_recall_never_touches_forwarded_mail(self):
        pm.outbox_put("srv", {"mid": "q2", "to": "beta", "frm": "alpha", "frm_id": "sid-a",
                              "body": "not mine to recall here", "kind": "", "t": 1, "origin": "hostz"})
        self.assertEqual(pm._recall("sid-a", "", "q2"), [], "forwarded mail belongs to the origin's sender")
        self.assertEqual(len(pm.outbox_list("srv")), 1)

    def test_receipts_show_parked_then_relayed(self):
        pm.outbox_put("srv", {"mid": "q3", "to": "beta", "frm": "alpha", "frm_id": "sid-a",
                              "body": "hi", "kind": "", "t": 1})
        pm._tl_append("messages.jsonl", {"t": 10, "ev": "sent", "id": "q3", "from": "alpha",
                                         "from_id": "sid-a", "to_id": "peer:srv",
                                         "toName": "srv:beta", "body": "hi", "kind": ""})
        row = pm._sent_receipts("sid-a")[-1]
        self.assertEqual((row["to"], row["parked"]), ("srv:beta", "srv"), "parked shows, honestly")
        pm._ack_arrived("srv", "q3")                 # the end-to-end ack lands
        row = pm._sent_receipts("sid-a")[-1]
        self.assertEqual(row["parked"], None)
        self.assertTrue(row["relayed"], "delivery confirmation replaces parked")

    def test_a_parked_receipt_carries_the_link_state(self):
        # outbox residency alone is not unreachability (the user 2026-08-24): the receipt row now
        # rides the authoritative dial state the send path already branches on, so the client can
        # say "queued for relay" on a healthy link and "unreachable" only on a real dial failure
        self.addCleanup(lambda: pm.PEERS.pop("srv", None))   # a mid-test failure must not leak link state
        pm.outbox_put("srv", {"mid": "q9", "to": "beta", "frm": "alpha", "frm_id": "sid-a",
                              "body": "hi", "kind": "", "t": 1})
        pm._tl_append("messages.jsonl", {"t": 10, "ev": "sent", "id": "q9", "from": "alpha",
                                         "from_id": "sid-a", "to_id": "peer:srv",
                                         "toName": "srv:beta", "body": "hi", "kind": ""})
        pm.PEERS["srv"] = {"up": True}
        self.assertTrue(pm._sent_receipts("sid-a")[-1]["parkedUp"], "healthy link -> queued, not lost")
        pm.PEERS["srv"] = {"up": False}
        self.assertFalse(pm._sent_receipts("sid-a")[-1]["parkedUp"], "down link -> honestly unreachable")
        pm.PEERS.pop("srv", None)
        self.assertFalse(pm._sent_receipts("sid-a")[-1]["parkedUp"],
                         "no tunnel record at all reads down, matching the send path's branch")
        row = pm._sent_receipts("sid-a")[-1]
        self.assertEqual(row["parked"], "srv", "the parked key keeps its host-string shape")


_SND = "11111111-2222-3333-4444-555555555555"
_RCP = "22222222-3333-4444-5555-666666666666"


class LedgerBeforeTheDelete(unittest.TestCase):
    """The accounting rows are the ONE record anyone reads (the sender's receipts, the timeline, the
    kernel's courier), so they land before the irreversible step, never after it (2026-09-08):
    deliver() writes the sent row and only then publishes — a row that cannot land refuses the send
    with nothing in new/ — and _bounce_apply / _ack_arrived write the terminal row and only then
    delete the outbox record. On origin/main the publish and the delete came first and the row was
    best-effort after them: mail with no row anywhere, and records gone before their receipt existed."""

    def setUp(self):
        os.environ["ROMP_POSTAL_PEERS"] = "1"
        import shutil
        shutil.rmtree(pm.OUTBOX, ignore_errors=True)
        shutil.rmtree(pm.MAILROOT, ignore_errors=True)
        shutil.rmtree(pm.MAILPENDING, ignore_errors=True)
        self._tl, self._log = pm.TLDIR, pm._log
        self.logged = []
        pm._log = lambda m: self.logged.append(m)
        try:
            (pm.TLDIR / "messages.jsonl").unlink()
        except OSError:
            pass
        if hasattr(pm, "_TL_FAULT"):
            pm._TL_FAULT[0] = False

    def tearDown(self):
        pm.TLDIR, pm._log = self._tl, self._log
        if hasattr(pm, "_TL_FAULT"):
            pm._TL_FAULT[0] = False
        os.environ.pop("ROMP_POSTAL_PEERS", None)

    def _break_the_log(self):
        # TLDIR under a regular FILE: mkdir raises (ENOTDIR), so the REAL _tl_append fails the way a
        # full or read-only disk fails it — no stub stands in for the function under test
        fd, path = tempfile.mkstemp()
        os.close(fd)
        self.addCleanup(lambda: os.unlink(path))
        pm.TLDIR = type(pm.TLDIR)(path) / "timeline"

    def test_tl_append_reports_whether_the_row_landed(self):
        self.assertTrue(pm._tl_append("messages.jsonl", {"t": 1, "ev": "sent", "id": "r1"}))
        self._break_the_log()
        self.assertFalse(pm._tl_append("messages.jsonl", {"t": 1, "ev": "sent", "id": "r2"}))
        self.assertFalse(pm._tl_append("messages.jsonl", {"t": 1, "ev": "sent", "id": "r3"}))
        self.assertEqual(len([m for m in self.logged if "append failed" in m]), 1,
                         "one line per fault episode, not per call")

    def test_a_send_whose_row_cannot_land_is_refused_with_nothing_in_new(self):
        self._break_the_log()
        with self.assertRaises(pm.DeliveryNotRecorded) as cm:
            pm.deliver(_RCP, "web", _SND, "please review the schema", kind="question")
        self.assertIn("not delivered", str(cm.exception))
        self.assertIn("retry", str(cm.exception))
        newd, tmpd = pm.MAILROOT / _RCP / "new", pm.MAILROOT / _RCP / "tmp"
        self.assertEqual([p.name for p in newd.iterdir()] if newd.is_dir() else [], [],
                         "no mail is published without its row")
        self.assertEqual([p.name for p in tmpd.iterdir()] if tmpd.is_dir() else [], [], "the temp is removed")
        self.assertFalse((pm.MAILPENDING / _RCP).exists(), "no pending marker for mail that never landed")

    def test_the_sent_row_follows_the_publish_it_names(self):
        # the order pin, executed: a recording _tl_append sees the mail ALREADY in new/ under the very
        # name the row carries. The publish is the claim on the name (link() refuses a standing one),
        # so a row is never written for a name that is not this message's — the first cut wrote the
        # row first and, under a collision, filed it under the standing message's id (the ledger pin
        # is in ExchangeRelaysAreBudgeted). A row that then fails takes the mail back (pinned above).
        seen = []
        saved = pm._tl_append
        newd = pm.MAILROOT / _RCP / "new"
        pm._tl_append = lambda f, o: seen.append(
            (o["ev"], o["id"], sorted(p.name for p in newd.iterdir()) if newd.is_dir() else [])) or True
        try:
            mid = pm.deliver(_RCP, "web", _SND, "hello")
        finally:
            pm._tl_append = saved
        self.assertEqual(seen, [("sent", mid, [mid])],
                         "the row is written once the mail stands in new/, under the name the row carries")

    def test_a_row_that_fails_after_a_reader_claimed_the_mail_answers_the_id(self):
        # the one interleaving the take-back cannot undo: read_box moved the file into cur/ in the
        # instant between the publish and the row. The message is in the recipient's hands, so the
        # answer is the id, not a refusal that would have the sender deliver it twice — and the gap
        # in the ledger is said out loud, by name.
        claimed = []
        saved = pm._tl_append

        def claim_then_fail(f, o):
            if o["ev"] == "sent":
                claimed.extend(m["id"] for m in pm.read_box(_RCP, consume=True))   # the reader beat the row
            return False

        pm._tl_append = claim_then_fail
        try:
            mid = pm.deliver(_RCP, "web", _SND, "hello")
        finally:
            pm._tl_append = saved
        self.assertEqual(claimed, [mid], "the reader took the message")
        self.assertTrue((pm.MAILROOT / _RCP / "cur" / mid).is_file(), "…and holds it")
        self.assertTrue(any(mid in m and "no record" in m for m in self.logged), "the missing row is said, by id")

    def test_bounce_apply_writes_the_terminal_row_and_the_note_before_the_delete(self):
        pm.outbox_put("srv", {"mid": "b1", "to": "beta", "frm": "alpha", "frm_id": _SND,
                              "body": "ship it", "kind": "", "t": 1})
        calls = []
        saved = (pm._tl_append, pm.outbox_del, pm.deliver)
        pm._tl_append = lambda f, o: calls.append("row:" + o["ev"]) or True
        pm.outbox_del = lambda h, m: calls.append("del:" + m) or saved[1](h, m)
        pm.deliver = lambda *a, **k: calls.append("note") or "m-note"
        try:
            pm._bounce_apply("srv", {"mid": "b1", "why": "no live session named 'beta'"})
        finally:
            pm._tl_append, pm.outbox_del, pm.deliver = saved
        self.assertEqual(calls, ["row:bounced", "note", "del:b1"],
                         "terminal row, then the return note, then — only then — the delete")
        self.assertIsNone(pm.outbox_get("srv", "b1"), "the record does leave the outbox once accounted")

    def test_bounce_apply_keeps_the_record_when_the_row_cannot_land(self):
        pm.outbox_put("srv", {"mid": "b2", "to": "beta", "frm": "alpha", "frm_id": _SND,
                              "body": "ship it", "kind": "", "t": 1})
        self._break_the_log()
        pm._bounce_apply("srv", {"mid": "b2", "why": "no live session named 'beta'"})
        self.assertIsNotNone(pm.outbox_get("srv", "b2"),
                             "an unaccounted refusal keeps the record — the next exchange re-relays it")
        self.assertTrue(any("stays parked" in m for m in self.logged), "…and says so")
        newd = pm.MAILROOT / _SND / "new"
        self.assertFalse(newd.is_dir() and any(newd.iterdir()),
                         "no return note either: nothing is published without its row")

    def test_ack_arrived_writes_the_receipt_before_the_delete(self):
        pm.outbox_put("srv", {"mid": "a1", "to": "beta", "frm": "alpha", "frm_id": _SND,
                              "body": "hi", "kind": "", "t": 1})
        calls = []
        saved = (pm._tl_append, pm.outbox_del)
        pm._tl_append = lambda f, o: calls.append("row:" + o["ev"]) or True
        pm.outbox_del = lambda h, m: calls.append("del:" + m) or saved[1](h, m)
        try:
            pm._ack_arrived("srv", "a1")
        finally:
            pm._tl_append, pm.outbox_del = saved
        self.assertEqual(calls, ["row:relayed", "del:a1"], "the delivered receipt, then the delete")
        self._break_the_log()
        pm.outbox_put("srv", {"mid": "a2", "to": "beta", "frm": "alpha", "frm_id": _SND,
                              "body": "hi", "kind": "", "t": 1})
        pm._ack_arrived("srv", "a2")
        self.assertIsNotNone(pm.outbox_get("srv", "a2"), "a receipt that did not land keeps the record")


class StoresPublishAtomicallyAndQuarantineTornRecords(unittest.TestCase):
    """outbox_put / readbox_put publish through a same-directory temp + os.replace, so a reader never
    sees a half-written record; a record that still cannot be parsed is moved aside ONCE to
    `<name>.corrupt-<utc stamp>` with one log line, and the rest of the store is listed. On
    origin/main the put was a plain write_text and the list skipped an unparseable file silently on
    every pass, forever."""

    def setUp(self):
        import shutil
        shutil.rmtree(pm.OUTBOX, ignore_errors=True)
        shutil.rmtree(pm.READBOX, ignore_errors=True)
        self._log = pm._log
        self.logged = []
        pm._log = lambda m: self.logged.append(m)

    def tearDown(self):
        pm._log = self._log

    def test_puts_go_through_os_replace_and_leave_no_temp(self):
        replaced = []
        saved = os.replace
        os.replace = lambda a, b, *r, **k: replaced.append((str(a), str(b))) or saved(a, b, *r, **k)
        try:
            self.assertTrue(pm.outbox_put("srv", {"mid": "p1", "to": "beta", "body": "hi"}))
            self.assertTrue(pm.readbox_put("srv", {"mid": "p2", "t": 1}))
        finally:
            os.replace = saved
        self.assertEqual([os.path.basename(b) for _a, b in replaced], ["p1.json", "p2.json"],
                         "each record is published by an atomic replace of a finished temp")
        for a, b in replaced:
            self.assertEqual(os.path.dirname(a), os.path.dirname(b), "the temp lives in the store's own directory")
            self.assertFalse(a.endswith(".json"), "…under a name the *.json listing can never see")
        self.assertEqual([p.name for p in (pm.OUTBOX / "srv").iterdir()], ["p1.json"], "no temp left behind")
        self.assertEqual([p.name for p in (pm.READBOX / "srv").iterdir()], ["p2.json"])
        self.assertEqual([r["mid"] for r in pm.outbox_list("srv")], ["p1"])
        self.assertEqual([r["mid"] for r in pm.readbox_list("srv")], ["p2"])

    def test_a_torn_record_is_moved_aside_once_and_the_rest_is_listed(self):
        pm.outbox_put("srv", {"mid": "good", "to": "beta", "body": "hi"})
        (pm.OUTBOX / "srv" / "torn.json").write_text('{"mid": "torn", "to": "be')     # a half-written record
        self.assertEqual([r["mid"] for r in pm.outbox_list("srv")], ["good"], "the rest of the store is served")
        aside = sorted(p.name for p in (pm.OUTBOX / "srv").iterdir() if p.name.startswith("torn.json.corrupt-"))
        self.assertEqual(len(aside), 1, "the torn record is moved aside, kept as evidence")
        self.assertFalse((pm.OUTBOX / "srv" / "torn.json").exists())
        said = [m for m in self.logged if "torn.json" in m]
        self.assertEqual(len(said), 1, "one log line names it")
        self.assertIn(aside[0], said[0], "…and where it went")
        self.assertEqual([r["mid"] for r in pm.outbox_list("srv")], ["good"])
        self.assertEqual(sorted(p.name for p in (pm.OUTBOX / "srv").iterdir() if "corrupt" in p.name), aside,
                         "the second pass moves nothing again")
        self.assertEqual(len([m for m in self.logged if "torn.json" in m]), 1, "…and says nothing again")

    def test_readbox_shares_the_quarantine(self):
        pm.readbox_put("srv", {"mid": "good", "t": 1})
        (pm.READBOX / "srv" / "torn.json").write_text("[1, 2")
        self.assertEqual([r["mid"] for r in pm.readbox_list("srv")], ["good"])
        self.assertTrue(any(p.name.startswith("torn.json.corrupt-") for p in (pm.READBOX / "srv").iterdir()))

    def test_a_record_rewritten_under_the_read_is_left_for_the_next_pass(self):
        # the fingerprint guard: the parse fails because a writer REPLACED the file between the stat
        # and the read — a torn READ of a healthy record, never a torn record — and it must not be
        # moved aside. Pins the new mechanism against moving a live record; main had no move to guard.
        pm.outbox_put("srv", {"mid": "live", "to": "beta", "body": "v1"})
        target = pm.OUTBOX / "srv" / "live.json"
        real_json = pm.json

        class _Shim:
            dumps = staticmethod(real_json.dumps)
            fired = [False]

            @staticmethod
            def loads(text, *a, **k):
                if not _Shim.fired[0]:
                    _Shim.fired[0] = True
                    pm._atomic_json_put(target, {"mid": "live", "to": "beta", "body": "v2"})   # a concurrent rewrite
                    raise ValueError("torn read")
                return real_json.loads(text, *a, **k)

        pm.json = _Shim
        try:
            first = pm.outbox_list("srv")
        finally:
            pm.json = real_json
        self.assertEqual(first, [], "this pass skips the record it could not read whole")
        self.assertTrue(target.exists(), "…and leaves it in place")
        self.assertEqual([p.name for p in (pm.OUTBOX / "srv").iterdir() if "corrupt" in p.name], [],
                         "a rewritten record is never moved aside")
        self.assertEqual([r["body"] for r in pm.outbox_list("srv")], ["v2"], "the next pass lists the new bytes")
        self.assertEqual(self.logged, [], "nothing to say: no fault happened")


class RefusalArms(unittest.TestCase):
    """The arms the review found claimed but untested (2026-09-08), each named with the mutant it kills."""

    def setUp(self):
        os.environ["ROMP_POSTAL_PEERS"] = "1"
        import shutil
        for d in (pm.OUTBOX, pm.READBOX, pm.MAILROOT):
            shutil.rmtree(d, ignore_errors=True)
        self._tl, self._log = pm.TLDIR, pm._log
        self.logged = []
        pm._log = lambda m: self.logged.append(m)
        try:
            (pm.TLDIR / "messages.jsonl").unlink()
        except OSError:
            pass
        pm._TL_FAULT[0] = False
        pm._peer_pending.clear()

    def tearDown(self):
        pm.TLDIR, pm._log = self._tl, self._log
        pm._TL_FAULT[0] = False
        pm._peer_pending.clear()
        os.environ.pop("ROMP_POSTAL_PEERS", None)

    def _break_the_log(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        self.addCleanup(lambda: os.unlink(path))
        pm.TLDIR = type(pm.TLDIR)(path) / "timeline"

    def _rows(self):
        p = self._tl / "messages.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines() if l] if p.exists() else []

    def test_tl_append_says_once_when_the_log_writes_again(self):
        # mutant: the three recovery lines deleted → no "writes again" line and _TL_FAULT stays set
        self._break_the_log()
        self.assertFalse(pm._tl_append("messages.jsonl", {"t": 1, "ev": "sent", "id": "r1"}))
        self.assertTrue(pm._TL_FAULT[0])
        pm.TLDIR = self._tl
        self.assertTrue(pm._tl_append("messages.jsonl", {"t": 1, "ev": "sent", "id": "r2"}))
        self.assertTrue(pm._tl_append("messages.jsonl", {"t": 1, "ev": "sent", "id": "r3"}))
        self.assertEqual(len([m for m in self.logged if m == "timeline log messages.jsonl writes again"]), 1,
                         "exactly one recovery line (the fault line also ends in the phrase; pin the whole line)")
        self.assertFalse(pm._TL_FAULT[0], "the fault flag clears with it")

    def test_relay_in_answers_retry_when_the_local_delivery_is_refused(self):
        # mutant: no except → falls through to peer_seen_add + "ack": the mail is acked, marked seen, gone
        saved = (pm.local_agents_checked, pm._postal_off, dict(pm.PEERS), pm._seen_ids)
        pm.local_agents_checked = lambda threads=False: ([{"id": _RCP, "name": "api", "remote": False}], True)
        pm._postal_off = lambda sid: False
        pm.PEERS["TESTHOST"] = {"trust": "trusted", "up": True}
        pm._seen_ids = set()
        self._break_the_log()
        mid = "px-1700000000.1_" + "ab" * 16 + ".TESTHOST"
        try:
            verdict, bounce = pm._relay_in("TESTHOST", {"mid": mid, "to": "api", "frm": "web", "frm_id": _SND,
                                                        "body": "ship it", "kind": "coordinate"})
            seen = pm.peer_seen_check(mid)
        finally:
            pm.local_agents_checked, pm._postal_off, peers, pm._seen_ids = saved
            pm.PEERS.clear()
            pm.PEERS.update(peers)
        self.assertEqual((verdict, bounce), ("retry", None), "silence on the wire: the sender re-relays")
        self.assertFalse(seen, "not marked seen, so the re-relay is processed in full")
        newd = pm.MAILROOT / _RCP / "new"
        self.assertEqual([p.name for p in newd.iterdir()] if newd.is_dir() else [], [], "nothing landed")

    def test_bounce_arrived_queues_the_backward_bounce_before_the_delete(self):
        # mutant: delete first (main's order) → at the delete the backward queue is still empty
        pm.outbox_put("hub", {"mid": "f1", "to": "carol", "frm": "alpha", "frm_id": _SND,
                              "body": "hi", "kind": "", "t": 1, "origin": "originhost"})
        at_delete = []
        saved = pm.outbox_del
        pm.outbox_del = lambda h, m: at_delete.append(list(pm._pending("originhost")["bounces"])) or saved(h, m)
        b = {"mid": "f1", "why": "no live session named 'carol'"}
        try:
            pm._bounce_arrived("hub", b)
        finally:
            pm.outbox_del = saved
        self.assertEqual(at_delete, [[b]], "the backward bounce is already queued at the moment of the delete")
        self.assertIsNone(pm.outbox_get("hub", "f1"), "…and the forward does leave the outbox")

    def test_no_readable_record_means_no_delete(self):
        # mutant: main's get → del → check: the unparseable record is destroyed, evidence gone
        d = pm.OUTBOX / "srv"
        d.mkdir(parents=True, exist_ok=True)
        (d / "torn.json").write_text('{"mid": "torn", "to": "be')
        pm._bounce_apply("srv", {"mid": "torn", "why": "refused"})
        self.assertTrue((d / "torn.json").exists(), "a bounce for a record we cannot read deletes nothing")
        pm._ack_arrived("srv", "torn")
        self.assertTrue((d / "torn.json").exists(), "…nor does an ack")
        pm.outbox_list("srv")                                # the listing is what moves it aside
        self.assertTrue(any(p.name.startswith("torn.json.corrupt-") for p in d.iterdir()), "evidence kept")

    def test_a_torn_outbox_record_closes_its_ledger_and_the_receipt_says_refused(self):
        # mutant: no terminal row → check_sent reads "pending (not read yet)" forever
        pm._tl_append("messages.jsonl", {"t": 10, "ev": "sent", "id": "px-torn", "from": "alpha",
                                         "from_id": "sid-a", "to_id": "peer:srv",
                                         "toName": "srv:beta", "body": "hi", "kind": ""})
        d = pm.OUTBOX / "srv"
        d.mkdir(parents=True, exist_ok=True)
        (d / "px-torn.json").write_text("{torn")
        self.assertEqual(pm.outbox_list("srv"), [])
        term = [r for r in self._rows() if r.get("ev") == "bounced" and r.get("id") == "px-torn"]
        self.assertEqual(len(term), 1, "one terminal row for the mid the filename names")
        self.assertEqual((term[0]["host"], term[0]["why"]), ("srv", pm.WHY_OUTBOX_UNREADABLE))
        row = pm._sent_receipts("sid-a")[-1]
        self.assertTrue(row["bounced"])
        self.assertEqual(row["bouncedWhy"], pm.WHY_OUTBOX_UNREADABLE)
        txt = pm.format_receipts([row])
        self.assertIn("refused — " + pm.WHY_OUTBOX_UNREADABLE, txt)
        self.assertNotIn("returned to you", txt, "no return note exists for a refusal")
        pm.outbox_list("srv")
        self.assertEqual(len([r for r in self._rows() if r.get("ev") == "bounced"]), 1, "the second pass adds nothing")

    def test_a_torn_readbox_record_closes_no_ledger(self):
        pm.readbox_put("srv", {"mid": "good", "t": 1})
        (pm.READBOX / "srv" / "torn.json").write_text("[1, 2")
        self.assertEqual([r["mid"] for r in pm.readbox_list("srv")], ["good"])
        self.assertEqual([r for r in self._rows() if r.get("ev") == "bounced"], [], "a receipt is not a message")

    def test_a_refused_oversize_bounce_puts_the_claimed_message_back(self):
        # the rebase onto the oversize-bounce change (PR #1038) created this arm: _bounce_oversize drops a
        # claimed message and mails its local sender a note; with the note REFUSED the message must not
        # sit in cur/ with no note and no row. Mutant: no except → the refusal escapes into _push's
        # catch-all and the message is stranded.
        saved_name = pm._name_for_id
        pm._name_for_id = lambda sid: "api"
        try:
            mid = pm.deliver(_RCP, "web", _SND, "x" * 64, kind="coordinate")
            m = pm.read_box(_RCP, consume=True)[0]                # the drain claims it (new/ → cur/)
            self.assertEqual(m["id"], mid)
            self._break_the_log()
            pm._bounce_oversize(_RCP, m)                          # must not raise
            self.assertTrue((pm.MAILROOT / _RCP / "new" / mid).exists(), "put back for the next pass")
            self.assertEqual(pm.read_box(_SND, consume=False), [], "no note was published without its row")
            self.assertEqual(len([x for x in self.logged if "kept for the next pass" in x]), 1)
            pm.TLDIR = self._tl                                    # the log writes again: the next pass
            m = pm.read_box(_RCP, consume=True)[0]
            pm._bounce_oversize(_RCP, m)
            self.assertFalse((pm.MAILROOT / _RCP / "new" / mid).exists(), "…and the bounce completes")
            notes = pm.read_box(_SND, consume=False)
            self.assertEqual(len(notes), 1)
            self.assertIn("undeliverable to 'api'", notes[0]["body"])
            evs = [r["ev"] for r in self._rows() if r.get("id") == mid]
            self.assertEqual((evs[-1], evs.count("bounced")), ("bounced", 1),
                             "one terminal row, written only once the note had landed (the roll-back's unexec "
                             "could not land while the log was down — that window is what restore() is for)")
        finally:
            pm._name_for_id = saved_name


class _LoudBus(unittest.TestCase):
    """Fixture for the review fixes of 2026-09-08: clean stores, the log captured, the kernel leg of
    _refused_notice captured (`told`), the once-per-episode registries reset. No tests of its own."""

    def setUp(self):
        os.environ["ROMP_POSTAL_PEERS"] = "1"
        import shutil
        for d in (pm.OUTBOX, pm.READBOX, pm.MAILROOT, pm.MAILPENDING):
            shutil.rmtree(d, ignore_errors=True)
        self._saved = (pm.TLDIR, pm._log, pm._kernel_post, pm.local_agents, pm.local_agents_checked)
        self.logged, self.told = [], []
        pm._log = lambda m: self.logged.append(m)
        pm._kernel_post = lambda path, body, timeout=2: self.told.append((path, body)) or {"ok": True}
        pm.local_agents = lambda threads=False: []
        pm.local_agents_checked = lambda threads=False: ([], True)
        try:
            (pm.TLDIR / "messages.jsonl").unlink()
        except OSError:
            pass
        pm._TL_FAULT[0] = False
        pm._DASHBOARD_MISSED[0] = False
        pm._NOTE_FAILED_SAID.clear()
        pm._UNREADABLE_SAID.clear()
        pm._peer_pending.clear()

    def tearDown(self):
        pm.TLDIR, pm._log, pm._kernel_post, pm.local_agents, pm.local_agents_checked = self._saved
        pm._TL_FAULT[0] = False
        pm._DASHBOARD_MISSED[0] = False
        pm._NOTE_FAILED_SAID.clear()
        pm._peer_pending.clear()
        os.environ.pop("ROMP_POSTAL_PEERS", None)

    def _rows(self):
        p = pm.TLDIR / "messages.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines() if l] if p.exists() else []

    def _notices(self):
        return [b["text"] for p, b in self.told if p == "/postal-notice"]


class OneBadRelayNeverAbortsTheExchange(_LoudBus):
    """_bounce_apply bounds the return note's failure (review find, 2026-09-08). With the record kept
    until it is accounted, a deliver() exception other than a refusal escaped the handler and aborted
    the WHOLE exchange; the peer re-bounced the still-parked record next exchange, so the abort
    recurred forever and every other relay, ack and receipt in those exchanges was lost with it.
    Mutant: the generic except removed (RuntimeError escapes peer_exchange_handle)."""

    def _exchange(self):
        return pm.peer_exchange_handle({"host": "srv", "proto": pm.PEER_PROTO, "epoch": 1, "busId": "b" * 32,
                                        "presence": [], "holds": [], "relays": [], "acks": ["n2"],
                                        "bounces": [{"mid": "n1", "why": "no live session named 'beta'"}],
                                        "reads": [], "readAcks": []})

    def test_a_note_that_raises_keeps_the_record_says_once_and_the_exchange_completes(self):
        for mid in ("n1", "n2"):
            pm.outbox_put("srv", {"mid": mid, "to": "beta", "frm": "alpha", "frm_id": _SND,
                                  "body": "ship it", "kind": "", "t": 1})
        saved = pm.deliver
        pm.deliver = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("mailbox on fire"))
        try:
            payload, status = self._exchange()                         # must not raise
            self.assertEqual(status, 200, "the exchange completes")
            self.assertIsNotNone(pm.outbox_get("srv", "n1"), "the bounced record stays parked for the next exchange")
            self.assertIsNone(pm.outbox_get("srv", "n2"), "the ack in the same exchange was processed")
            evs = {(r["ev"], r["id"]) for r in self._rows()}
            self.assertIn(("bounced", "n1"), evs, "the terminal row landed before the note was tried")
            self.assertIn(("relayed", "n2"), evs)
            said = [m for m in self.logged if "n1" in m and "could not be delivered" in m]
            self.assertEqual(len(said), 1)
            self.assertIn("RuntimeError: mailbox on fire", said[0], "the line names the fault")
            self.assertEqual(len(self._notices()), 1, "one bell row for a fault that would recur every exchange")
            self._exchange()                                           # the peer re-bounces it
            self.assertEqual((len([m for m in self.logged if "could not be delivered" in m]), len(self._notices())),
                             (1, 1), "said once per message, not per exchange")
        finally:
            pm.deliver = saved
        self._exchange()                                               # the note lands
        self.assertIsNone(pm.outbox_get("srv", "n1"), "and the record leaves once the note is delivered")
        self.assertEqual(len(pm.read_box(_SND, consume=False)), 1)


class NewFalseReturnsAreHonoured(_LoudBus):
    """The False the stores learned to return is read everywhere it was ignored (review find,
    2026-09-08). Mutants: outbox_put's False ignored at the relay forward ('hold' with nothing
    parked); the forwarded-ack order reverted (delete before the backward queue)."""

    def test_relay_in_answers_retry_when_the_forward_cannot_be_parked(self):
        saved = (pm.peer_route, pm.outbox_put)
        pm.peer_route = lambda to: ("farhost", {"name": "carol", "id": ""})
        pm.outbox_put = lambda h, m: False
        m = {"mid": "px-fwd", "to": "carol", "frm": "alpha", "frm_id": _SND, "body": "hi", "kind": ""}
        try:
            verdict = pm._relay_in("srv", m)
        finally:
            pm.peer_route, pm.outbox_put = saved
        self.assertEqual(verdict, ("retry", None), "silence on the wire: the sender re-relays")
        self.assertIsNone(pm.outbox_get("farhost", "px-fwd"))
        pm.peer_route = lambda to: ("farhost", {"name": "carol", "id": ""})
        try:
            self.assertEqual(pm._relay_in("srv", m), ("hold", None), "and a park that lands forwards as before")
        finally:
            pm.peer_route = saved[0]
        self.assertEqual(pm.outbox_get("farhost", "px-fwd")["origin"], "srv")

    def test_ack_arrived_queues_the_backward_ack_before_the_delete(self):
        pm.outbox_put("hub", {"mid": "fa1", "to": "carol", "frm": "alpha", "frm_id": _SND,
                              "body": "hi", "kind": "", "t": 1, "origin": "originhost"})
        at_delete = []
        saved = pm.outbox_del
        pm.outbox_del = lambda h, m: at_delete.append(list(pm._pending("originhost")["acks"])) or saved(h, m)
        try:
            pm._ack_arrived("hub", "fa1")
        finally:
            pm.outbox_del = saved
        self.assertEqual(at_delete, [["fa1"]], "the backward ack is already queued at the moment of the delete")
        self.assertIsNone(pm.outbox_get("hub", "fa1"), "and the forward does leave the outbox")


class StoreFaultsAreLoud(_LoudBus):
    """_atomic_json_put's failure path and _list_json_records' unreadable arm (review find,
    2026-09-08). An unreadable record is moved aside like a torn one, once, with its ledger closed
    and a bell row; the first cut skipped it in place on every exchange."""

    def test_a_failed_replace_raises_and_leaves_no_temp(self):
        import errno
        d = pm.OUTBOX / "srv"
        saved = os.replace
        os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError(errno.ENOSPC, "staged by the test"))
        try:
            with self.assertRaises(OSError):
                pm._atomic_json_put(d / "x.json", {"mid": "x"})
            self.assertEqual([p.name for p in d.iterdir()], [], "no temp and no record")
            self.assertFalse(pm.outbox_put("srv", {"mid": "x", "to": "beta", "body": "hi"}), "the put reports it")
        finally:
            os.replace = saved
        self.assertTrue(any("could not be written" in m for m in self.logged), "and says it")
        self.assertEqual([p.name for p in d.iterdir()], [])

    @unittest.skipIf(os.geteuid() == 0, "root reads a mode-0 file; the fault cannot be staged")
    def test_an_unreadable_record_is_moved_aside_once_and_closes_its_ledger(self):
        pm._tl_append("messages.jsonl", {"t": 10, "ev": "sent", "id": "px-locked", "from": "alpha",
                                         "from_id": _SND, "to_id": "peer:srv", "toName": "srv:beta",
                                         "body": "hi", "kind": "question"})
        pm.outbox_put("srv", {"mid": "px-locked", "to": "beta", "frm": "alpha", "frm_id": _SND, "body": "hi"})
        pm.outbox_put("srv", {"mid": "good", "to": "beta", "frm": "alpha", "frm_id": _SND, "body": "hi"})
        os.chmod(pm.OUTBOX / "srv" / "px-locked.json", 0)
        self.assertEqual([r["mid"] for r in pm.outbox_list("srv")], ["good"], "the rest of the store is served")
        self.assertFalse((pm.OUTBOX / "srv" / "px-locked.json").exists())
        aside = [p.name for p in (pm.OUTBOX / "srv").iterdir() if p.name.startswith("px-locked.json.corrupt-")]
        self.assertEqual(len(aside), 1, "moved aside, kept as evidence")
        term = [r for r in self._rows() if r.get("ev") == "bounced" and r.get("id") == "px-locked"]
        self.assertEqual([(r["host"], r["why"]) for r in term], [("srv", pm.WHY_OUTBOX_UNREADABLE)])
        self.assertEqual(len([m for m in self.logged if "px-locked.json" in m]), 1)
        self.assertEqual(len(self._notices()), 1, "one bell row")
        self.assertIn("could not be read", self._notices()[0])
        self.assertEqual([r["mid"] for r in pm.outbox_list("srv")], ["good"])
        self.assertEqual((len([m for m in self.logged if "px-locked.json" in m]), len(self._notices())), (1, 1),
                         "the second pass moves nothing and says nothing")
        self.assertIn("refused", pm.format_receipts([pm._sent_receipts(_SND)[-1]]))


class BusStartSweepsUnfinishedWrites(_LoudBus):
    """A crash between the sent row and the publish (or the park) left a phantom: a row that says
    "sent" and a temp nothing listed, nothing removed, nothing reported (review find, 2026-09-08).
    At bus start every temp is a write that never finished: removed, its ledger closed once when a
    sent row stands open, said once per file and once as a bell row. Sidecars are evidence and stay."""

    def test_temps_are_removed_ledgers_closed_and_said_once_and_sidecars_kept(self):
        for mid, to in (("m-tmp", _RCP), ("m-done", _RCP), ("px-tmp", "peer:srv")):
            pm._tl_append("messages.jsonl", {"t": 10, "ev": "sent", "id": mid, "from": "alpha", "from_id": _SND,
                                             "to_id": to, "body": "hi", "kind": "question"})
        pm._tl_append("messages.jsonl", {"t": 11, "ev": "bounced", "id": "m-done", "why": "already closed"})
        tmpd = pm.MAILROOT / _RCP / "tmp"
        tmpd.mkdir(parents=True)
        (tmpd / "m-tmp").write_text("From: alpha\n\nhalf")
        (tmpd / "m-done").write_text("From: alpha\n\nhalf")
        pm.outbox_put("srv", {"mid": "good", "to": "beta", "frm": "alpha", "frm_id": _SND, "body": "hi"})
        (pm.OUTBOX / "srv" / "px-tmp.json.tmp-1-abcd").write_text('{"mid": "px-t')
        (pm.OUTBOX / "srv" / "old.json.corrupt-20260101T000000Z").write_text("{torn")
        (pm.READBOX / "srv").mkdir(parents=True)
        (pm.READBOX / "srv" / "r1.json.tmp-2-beef").write_text("{")
        pm._sweep_unfinished_writes()
        self.assertEqual([p.name for p in tmpd.iterdir()], [], "the maildir temps are gone")
        self.assertEqual(sorted(p.name for p in (pm.OUTBOX / "srv").iterdir()),
                         ["good.json", "old.json.corrupt-20260101T000000Z"], "the store temp is gone; the record and the sidecar stay")
        self.assertEqual([p.name for p in (pm.READBOX / "srv").iterdir()], [])
        term = {r["id"]: r for r in self._rows() if r.get("ev") == "bounced"}
        self.assertEqual(term["m-tmp"]["why"], pm.WHY_STOPPED_BEFORE_PUBLISH)
        self.assertEqual(term["m-tmp"]["to_id"], _RCP)
        self.assertEqual((term["px-tmp"]["host"], term["px-tmp"]["why"]), ("srv", pm.WHY_STOPPED_BEFORE_PARK))
        self.assertEqual(len([r for r in self._rows() if r.get("ev") == "bounced" and r.get("id") == "m-done"]), 1,
                         "an id already closed is not closed again")
        self.assertEqual(len([m for m in self.logged if "removed at start" in m]), 4, "one line per file")
        self.assertEqual(len(self._notices()), 1, "one bell row for the sweep")
        self.assertIn("4 unfinished mail write(s)", self._notices()[0])
        self.assertIn("2 sender receipt(s) now read refused", self._notices()[0])
        recs = {r["id"]: r for r in pm._sent_receipts(_SND)}
        for mid in ("m-tmp", "px-tmp"):
            self.assertIn("refused", pm.format_receipts([recs[mid]]), mid)
        pm._sweep_unfinished_writes()
        self.assertEqual((len([m for m in self.logged if "removed at start" in m]), len(self._notices())), (4, 1),
                         "a second start with nothing to sweep says nothing")

    def test_serve_runs_the_sweep_before_it_binds(self):
        import inspect
        src = inspect.getsource(pm.serve)
        self.assertIn("_sweep_unfinished_writes()", src)
        self.assertLess(src.index("_sweep_unfinished_writes()"), src.index("ThreadingHTTPServer("),
                        "the sweep runs at start, before any writer of ours can run")
