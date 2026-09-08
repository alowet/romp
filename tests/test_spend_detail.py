#!/usr/bin/env python3
"""T247 (the user 2026-09-07): clicking the dashboard's usage readout opens a modal with a per-session
spend breakdown and a stacked histogram of spend over time colored by session. The data is GET
/spend/detail: the ledger's bySid maps (T100's per-session attribution) with names and identity colors
resolved kernel-side, two ranges at the ledger's own granularity (192 hours, 90 days), the top-N sessions
as stacks plus ONE "other" and ONE "unattributed" stack — spend recorded before attribution existed, or
the part of a bucket no sid accounts for, is shown as such, never dropped (fail loudly). Hermetic state
root, synthetic ledger, the notes-api demo sessions (web/api/tests), placeholder uuids, TESTHOST."""
import inspect
import json
import os
import tempfile
import time
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)
km = SourceFileLoader("romp_kernel_spenddetail", os.path.join(BIN, "romp-kernel")).load_module()

WEB, API, TESTS = ("11111111-2222-3333-4444-000000000001", "11111111-2222-3333-4444-000000000002",
                   "11111111-2222-3333-4444-000000000003")
NOW = time.mktime((2026, 9, 7, 15, 30, 0, 0, 0, -1))   # a fixed afternoon; keys built the recorder's way


def _hour(n):
    return time.strftime("%Y-%m-%dT%H", time.localtime(NOW - n * 3600))


def _day(n):
    return time.strftime("%Y-%m-%d", time.localtime(NOW - n * 86400))


def _bucket(usd, tok, turns, by=None, key=None):
    e = {"usd": usd, "turns": turns, "tokIn": tok // 4, "tokOut": tok // 4, "tokCacheR": tok // 4,
         "tokCacheW": tok - 3 * (tok // 4)}
    if key is not None:
        e["key"] = key
    if by is not None:
        e["bySid"] = by
    return e


def write_ledger(state, extra_sids=0):
    hours = {}
    for n in range(0, 60):
        # web spends every hour, api every other, tests rarely
        by = {WEB: {"usd": 1.0, "turns": 2, "tok": 20000}}
        if n % 2 == 0:
            by[API] = {"usd": 0.5, "turns": 1, "tok": 8000}
        if n % 10 == 0:
            by[TESTS] = {"usd": 0.25, "turns": 1, "tok": 3000}
        tot_usd = sum(v["usd"] for v in by.values())
        tot_tok = sum(v["tok"] for v in by.values())
        tot_turns = sum(v["turns"] for v in by.values())
        hours[_hour(n)] = _bucket(tot_usd, tot_tok, tot_turns, by)
    # an hour that predates per-session attribution: no bySid at all → unattributed, never dropped
    hours[_hour(70)] = _bucket(3.0, 30000, 4)
    days = {}
    for n in range(0, 40):
        by = {WEB: {"usd": 24.0, "turns": 48, "tok": 480000}, API: {"usd": 6.0, "turns": 12, "tok": 96000}}
        if n % 5 == 0:
            by[TESTS] = {"usd": 0.6, "turns": 2, "tok": 7200}
        for i in range(extra_sids):   # many small sessions, to overflow the top-N into "other"
            by["11111111-2222-3333-4444-0000000001%02d" % i] = {"usd": 0.1, "turns": 1, "tok": 1000}
        days[_day(n)] = _bucket(sum(v["usd"] for v in by.values()), sum(v["tok"] for v in by.values()),
                                sum(v["turns"] for v in by.values()), by)
    # a PARTIAL day: the bucket total exceeds what its sids account for (a turn recorded sid-less)
    days[_day(2)]["usd"] += 5.0
    days[_day(2)]["tokIn"] += 50000
    days[_day(2)]["turns"] += 1
    # two days before attribution existed: whole-bucket unattributed
    days[_day(50)] = _bucket(40.0, 400000, 30)
    days[_day(51)] = _bucket(41.0, 410000, 31)
    (state / "spend.json").write_text(json.dumps({"days": days, "hours": hours}))


class SpendDetail(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        state = Path(self.td.name)
        self._saved = (km.jd.STATE, km.NAMES, km._live_names, km._tmux_sessions, km._self_host,
                       km._claude_account, km._auth_key_present, dict(km._remotes))
        km.jd.STATE = state
        km.NAMES = state / "names"
        km.NAMES.mkdir()
        (km.NAMES / WEB).write_text("web\t/tmp/notes-api\t#1EA1EB\t#ffffff\n")
        (km.NAMES / API).write_text("api\t/tmp/notes-api\t#54B204\t#ffffff\n")
        (km.NAMES / TESTS).write_text("tests\t/tmp/notes-api\n")          # no identity color
        km._live_names = lambda tm: {"web": WEB, "api": API}                # tests is no longer running
        km._tmux_sessions = lambda: []
        km._self_host = lambda: "TESTHOST"
        km._claude_account = lambda: ""                                     # a key-only machine: total scope
        km._auth_key_present = lambda: True
        km._remotes.clear()
        (state / "usage.json").write_text(json.dumps({"apiKey": True}))
        write_ledger(state)

    def tearDown(self):
        (km.jd.STATE, km.NAMES, km._live_names, km._tmux_sessions, km._self_host,
         km._claude_account, km._auth_key_present, saved_remotes) = self._saved
        km._remotes.clear()
        km._remotes.update(saved_remotes)
        self.td.cleanup()

    def test_sessions_are_named_colored_sorted_and_flagged_live(self):
        d = km._spend_detail(now=NOW)
        self.assertEqual(d["host"], "TESTHOST")
        self.assertEqual([(h["host"], h["status"]) for h in d["hosts"]], [("TESTHOST", "ok")])
        self.assertEqual(d["scope"], "total")
        names = [s["name"] for s in d["sessions"]]
        self.assertEqual(names, ["web", "api", "tests"], "sorted by dollars, largest first")
        web, api, tests = d["sessions"]
        self.assertEqual((web["bg"], web["fg"]), ("#1EA1EB", "#ffffff"), "identity color from the registry")
        self.assertEqual(tests["bg"], "", "a session without an identity color says so (the client draws neutral)")
        self.assertTrue(web["live"] and api["live"] and not tests["live"], "a dead session keeps its name, flagged")
        self.assertAlmostEqual(web["usd"], 24.0 * 40, places=3)
        self.assertEqual(web["turns"], 48 * 40)
        self.assertEqual(api["tok"], 96000 * 40)
        self.assertEqual(d["topN"], km._DETAIL_TOP_N)
        self.assertNotIn("windows", d, "the modal's window rows are the hover's own (no second parse, no dead payload)")
        self.assertEqual(d["tzOffsetMin"], int((time.localtime(NOW).tm_gmtoff or 0) // 60))

    def test_unattributed_spend_is_shown_never_dropped(self):
        d = km._spend_detail(now=NOW)
        un = d["unattributed"]
        # two pre-attribution days + the partial day's remainder
        self.assertAlmostEqual(un["usd"], 40.0 + 41.0 + 5.0, places=3)
        self.assertEqual(un["turns"], 30 + 31 + 1)
        self.assertEqual(un["tok"], 400000 + 410000 + 50000)
        kinds = [s["kind"] for s in d["days"]["stacks"]]
        self.assertEqual(kinds, ["sid", "sid", "sid", "unattributed"], "one stack per session, then the unattributed stack")
        una = d["days"]["stacks"][-1]
        keys = d["days"]["keys"]
        self.assertEqual(len(keys), 90)
        self.assertEqual(keys[-1], _day(0), "dense, oldest first, today last")
        self.assertAlmostEqual(una["usd"][keys.index(_day(50))], 40.0, places=3)
        self.assertAlmostEqual(una["usd"][keys.index(_day(2))], 5.0, places=3, msg="the partial day's remainder")
        self.assertEqual(una["tok"][keys.index(_day(2))], 50000)
        hk = d["hours"]["keys"]
        self.assertEqual(len(hk), km._SERIES_HOURS)
        self.assertEqual(hk[-1], _hour(0))
        hun = [s for s in d["hours"]["stacks"] if s["kind"] == "unattributed"][0]
        self.assertAlmostEqual(hun["usd"][hk.index(_hour(70))], 3.0, places=3, msg="a pre-attribution hour, whole")
        web = [s for s in d["hours"]["stacks"] if s.get("name") == "web"][0]
        self.assertAlmostEqual(web["usd"][hk.index(_hour(5))], 1.0, places=3)
        self.assertEqual(web["tok"][hk.index(_hour(5))], 20000)
        self.assertFalse(web["usd"][hk.index(_hour(100))], "an hour with nothing recorded is a true zero")

    def test_beyond_the_top_n_sessions_fold_into_one_other_stack(self):
        write_ledger(km.jd.STATE, extra_sids=12)
        d = km._spend_detail(now=NOW)
        self.assertEqual(len(d["sessions"]), 15, "the table lists EVERY session")
        kinds = [s["kind"] for s in d["days"]["stacks"]]
        self.assertEqual(kinds.count("sid"), km._DETAIL_TOP_N)
        self.assertEqual(kinds[-2:], ["other", "unattributed"])
        other = d["days"]["stacks"][-2]
        self.assertEqual(other["count"], 15 - km._DETAIL_TOP_N)
        keys = d["days"]["keys"]
        self.assertAlmostEqual(other["usd"][keys.index(_day(1))], 0.1 * (15 - km._DETAIL_TOP_N), places=3)
        self.assertEqual(d["hours"]["stacks"][0]["name"], "web", "stack order is the table's: top by dollars")

    def test_the_keyed_scope_reads_each_sids_key_split_like_the_rail(self):
        # a login's windows beside the key's spend: the rail sums ONLY key-billed turns, so does the modal
        km._claude_account = lambda: "acct-digest"
        (km.jd.STATE / "usage.json").write_text(json.dumps({"five_hour": {"pct": 10}}))
        state = km.jd.STATE
        days = {_day(0): _bucket(10.0, 100000, 10, {WEB: {"usd": 6.0, "turns": 6, "tok": 60000,
                                                           "key": {"usd": 2.0, "turns": 2, "tok": 20000}},
                                                     API: {"usd": 4.0, "turns": 4, "tok": 40000}},
                                  key={"usd": 2.0, "turns": 2, "tok": 20000})}
        (state / "spend.json").write_text(json.dumps({"days": days, "hours": {}}))
        d = km._spend_detail(now=NOW)
        self.assertEqual(d["scope"], "keyed")
        by = {s["name"]: s for s in d["sessions"]}
        self.assertAlmostEqual(by["web"]["usd"], 2.0, places=3, msg="the key-billed dollars only")
        self.assertNotIn("api", by, "a login-only session bills nothing to the key: not a row, not a stack")
        self.assertEqual([s["name"] for s in d["days"]["stacks"]], ["web"])
        self.assertEqual(d["unattributed"]["usd"], 0.0)
        # the TOTAL scope, same ledger: the split rides beside the totals where the hover would show it
        km._claude_account = lambda: ""
        d2 = km._spend_detail(now=NOW)
        self.assertEqual(d2["scope"], "total")
        by2 = {s["name"]: s for s in d2["sessions"]}
        self.assertAlmostEqual(by2["web"]["usd"], 6.0, places=3)
        self.assertEqual(by2["web"]["key"], {"usd": 2.0, "tok": 20000, "turns": 2})
        self.assertNotIn("key", by2["api"])

    def test_the_hosts_asked_are_the_hovers_spend_hosts(self):
        # the hover's predicate exactly: a remote joins when it reports SPEND windows (a login-only
        # remote contributes bars, not spend, and is not asked); a down one is reported, never omitted
        km._remotes["peer"] = {"host": "peer", "status": "up", "local_port": 1, "token": "t",
                               "usage": {"apiKey": True, "spend": {"day": {"usd": 1}}}}
        km._remotes["bars"] = {"host": "bars", "status": "up", "usage": {"fiveHour": {"pct": 5}}}
        km._remotes["down"] = {"host": "down", "status": "down", "usage": {"apiKey": True, "spend": {"day": {"usd": 1}}}}
        saved = km._PEER_SPEND_TIMEOUT_S
        km._PEER_SPEND_TIMEOUT_S = 0.5
        try:
            d = km._spend_detail(now=NOW)
        finally:
            km._PEER_SPEND_TIMEOUT_S = saved
        self.assertEqual([h["host"] for h in d["hosts"]], ["TESTHOST", "peer", "down"], "bars has no spend: not asked, not listed")
        self.assertEqual(d["hosts"][1]["status"], "unreachable", "nothing answers on port 1")
        self.assertEqual(d["hosts"][2]["status"], "unreachable")

    def test_a_login_without_a_key_is_the_computed_scope(self):
        # the rail's THIRD arm: windows present, no key → the rail shows no spend at all; the modal must
        # not dress computed costs up as API spend (review find)
        km._claude_account = lambda: "acct-digest"
        km._auth_key_present = lambda: False
        (km.jd.STATE / "usage.json").write_text(json.dumps({"five_hour": {"pct": 10}}))
        d = km._spend_detail(now=NOW)
        self.assertEqual(d["scope"], "computed")
        self.assertEqual(d["sessions"][0]["name"], "web", "the computed costs are still per session")
        html = km._landing()
        self.assertIn("computed cost, not billed", html)
        self.assertIn("Spend (computed)", html)

    def test_totals_cover_the_days_the_chart_draws_not_every_bucket_kept(self):
        # the recorder keeps the 90 most RECENT spend days, which can reach past 90 calendar days; the
        # header says "last 90 days", so a bucket older than the chart's window counts nowhere (review find)
        d0 = km._spend_detail(now=NOW)
        led = json.loads((km.jd.STATE / "spend.json").read_text())
        led["days"][_day(120)] = _bucket(999.0, 9990000, 99, {TESTS: {"usd": 999.0, "turns": 99, "tok": 9990000}})
        (km.jd.STATE / "spend.json").write_text(json.dumps(led))
        d = km._spend_detail(now=NOW)
        self.assertEqual([s["name"] for s in d["sessions"]], [s["name"] for s in d0["sessions"]], "the ranking is unmoved")
        self.assertEqual(d["sessions"][2]["usd"], d0["sessions"][2]["usd"], "tests' total is the chart's window, not the ledger's reach")
        self.assertEqual(d["unattributed"], d0["unattributed"])

    def test_a_fall_back_transition_writes_one_slot_per_local_hour(self):
        # TZ-pinned: 192 epoch hours across a fall-back hold 191 distinct local keys; the recorder merges
        # both 01:00s into one key, so the series holds one slot for it, not a labeled empty twin
        import os as _os
        saved = _os.environ.get("TZ")
        _os.environ["TZ"] = "America/Los_Angeles"
        time.tzset()
        try:
            fall = time.mktime((2026, 11, 1, 12, 0, 0, 0, 0, -1))
            d = km._spend_detail(now=fall)
            hk = d["hours"]["keys"]
            self.assertEqual(len(hk), len(set(hk)), "no duplicate hour key")
            self.assertEqual(len(hk), km._SERIES_HOURS - 1)
        finally:
            if saved is None:
                _os.environ.pop("TZ", None)
            else:
                _os.environ["TZ"] = saved
            time.tzset()

    def test_an_empty_or_missing_ledger_answers_with_zeros_not_an_error(self):
        (km.jd.STATE / "spend.json").unlink()
        d = km._spend_detail(now=NOW)
        self.assertEqual(d["sessions"], [])
        self.assertEqual(d["days"]["stacks"], [])
        self.assertEqual(len(d["days"]["keys"]), 90)

    def test_float_residue_never_conjures_an_unattributed_stack_or_row(self):
        # T247b review find: the recorder rounds the bucket sum and each sid's sum independently (6
        # places), so a fully attributed bucket can carry a +1e-6..+6e-6 dollar residue with zero token
        # residue — 28 of 113 live hour buckets did — and the presence test on the unrounded residues
        # hung a hatched "unattributed" chip with no bars on the 8-day view. Below the rounding grain
        # a residue is zero: no stack, no row.
        hours, days = {}, {}
        for n in range(0, 40):
            by = {WEB: {"usd": 0.333333, "turns": 1, "tok": 1000}, API: {"usd": 0.666667, "turns": 1, "tok": 2000}}
            hours[_hour(n)] = _bucket(1.000001, 3000, 2, by)          # sum of sids: 1.000000 → +1e-6 residue
        for n in range(0, 30):
            by = {WEB: {"usd": 2.1, "turns": 3, "tok": 5000}, API: {"usd": 3.9, "turns": 4, "tok": 7000}}
            days[_day(n)] = _bucket(6.000004, 12000, 7, by)           # +4e-6 residue, every day
        (km.jd.STATE / "spend.json").write_text(json.dumps({"days": days, "hours": hours}))
        d = km._spend_detail(now=NOW)
        self.assertEqual([s["kind"] for s in d["hours"]["stacks"]], ["sid", "sid"], "no unattributed stack from residue")
        self.assertEqual([s["kind"] for s in d["days"]["stacks"]], ["sid", "sid"])
        self.assertEqual(d["unattributed"], {"usd": 0.0, "tok": 0, "turns": 0}, "30 days of residue sum to nothing, not $0.0001")
        # …and a REAL remainder still shows: a sid-less turn's cost is far above the grain
        days[_day(1)]["usd"] += 0.05
        (km.jd.STATE / "spend.json").write_text(json.dumps({"days": days, "hours": hours}))
        d = km._spend_detail(now=NOW)
        self.assertEqual(d["days"]["stacks"][-1]["kind"], "unattributed")
        self.assertAlmostEqual(d["unattributed"]["usd"], 0.05, places=4)

    def test_the_keyed_scopes_other_stack_counts_only_sessions_that_billed_the_key(self):
        # T247b review find: in the keyed scope a login-only session contributed (0,0,0) yet was counted
        # into "other (N sessions)", while the table dropped it — the legend said 17, the fold said 2
        km._claude_account = lambda: "acct-digest"
        (km.jd.STATE / "usage.json").write_text(json.dumps({"five_hour": {"pct": 10}}))
        by = {}
        for i in range(12):   # twelve key-billed sessions, two beyond the top ten
            by["11111111-2222-3333-4444-0000000002%02d" % i] = {"usd": 1.0 + i, "turns": 1, "tok": 1000,
                                                                "key": {"usd": 1.0 + i, "turns": 1, "tok": 1000}}
        for i in range(5):    # five login-only sessions: no key sub-map
            by["11111111-2222-3333-4444-0000000003%02d" % i] = {"usd": 9.0, "turns": 9, "tok": 9000}
        days = {_day(0): _bucket(sum(v["usd"] for v in by.values()), 17000, 26, by,
                                 key={"usd": sum(1.0 + i for i in range(12)), "turns": 12, "tok": 12000})}
        (km.jd.STATE / "spend.json").write_text(json.dumps({"days": days, "hours": {}}))
        d = km._spend_detail(now=NOW)
        self.assertEqual(d["scope"], "keyed")
        self.assertEqual(len(d["sessions"]), 12, "the table lists the key-billed sessions only")
        other = [s for s in d["days"]["stacks"] if s["kind"] == "other"][0]
        self.assertEqual(other["count"], 2, "the legend's count is the table's fold: sessions that contributed")
        self.assertEqual(d["unattributed"]["usd"], 0.0, "every key dollar is a session's: nothing unattributed")
        self.assertEqual([s["kind"] for s in d["days"]["stacks"]][-1], "other")

    # ── T247c: every attached kernel's sessions, merged kernel-side ──────────────────────────────
    def _peer_server(self, payload=None, status=200, token="peer-tok", hang=False):
        """A stand-in peer kernel: /spend/detail behind the peer's own serve token (the transport
        mirror_trust uses), answering `payload` — or 404 for an older build, or never (hang)."""
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        body = json.dumps(payload or {}).encode()

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.headers.get("X-Romp-Token") != token:
                    self.send_response(401); self.end_headers(); return
                if hang:
                    time.sleep(5); return
                if self.path.split("?")[0] != "/spend/detail":
                    self.send_response(404); self.end_headers(); return
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return srv.server_address[1]

    def _attach(self, host, port, token="peer-tok", status="up"):
        km._remotes[host] = {"host": host, "status": status, "local_port": port, "token": token,
                             "usage": {"apiKey": True, "spend": {"day": {"usd": 1}}}}

    def _peer_payload(self, off_min, epochs=True):
        """A peer's own /spend/detail, three hours east of us: the same absolute hours, LOCAL keys that
        read three hours later, and one session of its own (plus a pre-attribution hour)."""
        local = km._spend_detail_local(now=NOW)
        keys, eps = local["hours"]["keys"], local["hours"]["epochs"]
        pk = [time.strftime("%Y-%m-%dT%H", time.gmtime(e * 3600 + off_min * 60)) for e in eps]
        n = len(keys)
        usd = [0.0] * n; tok = [0] * n
        i5 = n - 1 - 5
        usd[i5] = 7.0; tok[i5] = 70000
        una = [0.0] * n; una[n - 1 - 9] = 2.0
        pd = {"host": "PEERHOST", "scope": "total", "tz": "PEER", "tzOffsetMin": off_min, "topN": 10,
              "sessions": [{"sid": "22222222-3333-4444-5555-000000000001", "name": "worker", "bg": "#C2410C", "fg": "#fff",
                            "live": True, "usd": 300.0, "tok": 3000000, "turns": 30}],
              "unattributed": {"usd": 2.0, "tok": 0, "turns": 1},
              "hours": {"keys": pk, "stacks": [
                  {"kind": "sid", "sid": "22222222-3333-4444-5555-000000000001", "name": "worker", "bg": "#C2410C", "live": True, "usd": usd, "tok": tok},
                  {"kind": "unattributed", "name": "unattributed", "usd": una, "tok": [0] * n}]},
              "days": {"keys": local["days"]["keys"], "stacks": [
                  {"kind": "sid", "sid": "22222222-3333-4444-5555-000000000001", "name": "worker", "bg": "#C2410C", "live": True,
                   "usd": [0.0] * 89 + [300.0], "tok": [0] * 89 + [3000000]}]}}
        if epochs:
            pd["hours"]["epochs"] = eps
        return pd

    def test_a_peers_sessions_merge_in_with_their_host_and_hours_align_by_absolute_time(self):
        off = int((time.localtime(NOW).tm_gmtoff or 0) // 60) + 180
        self._attach("PEERHOST", self._peer_server(self._peer_payload(off)))
        d = km._spend_detail(now=NOW)
        self.assertEqual([h["host"] for h in d["hosts"]], ["TESTHOST", "PEERHOST"])
        self.assertEqual([h["status"] for h in d["hosts"]], ["ok", "ok"])
        names = [(s["host"], s["name"]) for s in d["sessions"]]
        self.assertEqual(names[0], ("TESTHOST", "web"))
        self.assertIn(("PEERHOST", "worker"), names, "the peer's session is a row, tagged with its host")
        self.assertEqual(names[1], ("PEERHOST", "worker"), "sorted by dollars across hosts: 300 sits between web's 960 and api's 240")
        hk = d["hours"]["keys"]
        worker = [s for s in d["hours"]["stacks"] if s.get("name") == "worker"][0]
        self.assertEqual(worker["host"], "PEERHOST")
        self.assertAlmostEqual(worker["usd"][len(hk) - 1 - 5], 7.0, places=3,
                               msg="the peer's hour lands on the same ABSOLUTE hour, though its local key reads three hours later")
        self.assertEqual(sum(1 for v in worker["usd"] if v), 1)
        una = [s for s in d["hours"]["stacks"] if s["kind"] == "unattributed"][0]
        self.assertAlmostEqual(una["usd"][len(hk) - 1 - 9], 2.0, places=3, msg="the peer's pre-attribution hour joins the one unattributed stack")
        self.assertAlmostEqual(una["hosts"]["PEERHOST"]["usd"][len(hk) - 1 - 9], 2.0, places=3, msg="…with its host named for the tooltip")
        self.assertAlmostEqual(d["unattributed"]["byHost"]["PEERHOST"]["usd"], 2.0, places=3)
        self.assertAlmostEqual(d["unattributed"]["usd"], 86.0 + 2.0, places=3)
        dk = d["days"]["keys"]
        wd = [s for s in d["days"]["stacks"] if s.get("name") == "worker"][0]
        self.assertAlmostEqual(wd["usd"][len(dk) - 1], 300.0, places=3, msg="daily buckets align by each machine's own date")

    def test_an_older_peer_without_epochs_still_aligns_through_its_offset(self):
        off = int((time.localtime(NOW).tm_gmtoff or 0) // 60) + 180
        self._attach("PEERHOST", self._peer_server(self._peer_payload(off, epochs=False)))
        d = km._spend_detail(now=NOW)
        hk = d["hours"]["keys"]
        worker = [s for s in d["hours"]["stacks"] if s.get("name") == "worker"][0]
        self.assertAlmostEqual(worker["usd"][len(hk) - 1 - 5], 7.0, places=3, msg="local keys converted with the peer's offset, never string-equal")

    def test_a_down_an_older_and_a_hanging_peer_are_reported_by_name_never_omitted(self):
        self._attach("DOWNHOST", 1, status="down")
        self._attach("OLDHOST", self._peer_server(status=404))
        self._attach("SLOWHOST", self._peer_server(hang=True))
        self._attach("PEERHOST", self._peer_server(self._peer_payload(int((time.localtime(NOW).tm_gmtoff or 0) // 60))))
        saved = km._PEER_SPEND_TIMEOUT_S
        km._PEER_SPEND_TIMEOUT_S = 0.6
        try:
            t0 = time.time()
            d = km._spend_detail(now=NOW)
            took = time.time() - t0
        finally:
            km._PEER_SPEND_TIMEOUT_S = saved
        by = {h["host"]: h for h in d["hosts"]}
        self.assertEqual(by["DOWNHOST"]["status"], "unreachable")
        self.assertEqual(by["OLDHOST"]["status"], "older", "no /spend/detail route: an older build, said so by name")
        self.assertEqual(by["SLOWHOST"]["status"], "unreachable", "past the bounded timeout: reported, and the rest renders")
        self.assertIn("timed out", by["SLOWHOST"]["detail"])
        self.assertEqual(by["PEERHOST"]["status"], "ok", "a slow host holds nobody hostage")
        self.assertIn(("PEERHOST", "worker"), [(s["host"], s["name"]) for s in d["sessions"]])
        self.assertLess(took, 3.0, "the peer calls run in parallel under one bounded timeout")

    def test_a_peer_that_rejects_our_token_is_unreachable_by_name(self):
        self._attach("PEERHOST", self._peer_server(self._peer_payload(0)), token="wrong")
        d = km._spend_detail(now=NOW)
        by = {h["host"]: h for h in d["hosts"]}
        self.assertEqual(by["PEERHOST"]["status"], "unreachable")

    def test_the_route_and_the_shell_are_wired(self):
        ksrc = inspect.getsource(km.Handler.do_GET) if hasattr(km.Handler, "do_GET") else open(os.path.join(os.path.dirname(HERE), "kernel", "kernel.py")).read()
        self.assertIn('if p == "/spend/detail":', ksrc, "the kernel route exists")
        self.assertIn("json.dumps(_spend_detail())", ksrc)
        html = km._landing()
        self.assertIn("id=rsp-back hidden", html, "the modal's shell-native backdrop, hidden until the click")
        self.assertIn("fetch('/spend/detail'", html, "the shell fetches the route on open, never scrapes the hover")
        self.assertIn("el.addEventListener('click',function(){pull(true);openSpend();});", html,
                      "the click on the readout opens the modal (and still kicks the hover's refresh)")
        self.assertIn("if(sp&&!sp.hidden&&window.__rompCloseSpend){window.__rompCloseSpend();closed=true;}", html,
                      "Escape closes it through the shell's one Escape chain")
        self.assertIn("#rsp-back{position:fixed;inset:0;z-index:205;display:flex;align-items:center;justify-content:center;"
                      "background:rgba(0,0,0,0.55)}", html, "the panel rule: a centered card over rgba(0,0,0,0.55)")
        self.assertNotIn("__ROMP_LOADER__", html.split("_LANDING_JS")[0] if "_LANDING_JS" in html else html,
                         "the loader markup is spliced, not left as a placeholder")
        self.assertIn("rl-word", html)
        self.assertNotIn("this machine only", html, "T247c: every attached kernel's sessions are in — no such note")
        self.assertIn("not reachable", html)
        self.assertIn("older build", html)
        self.assertIn("aligned by clock time across machines", html)
        self.assertIn("recorded before per-session tracking", html, "unattributed spend is named, never folded")
        self.assertIn("var rows=spendRowsHTML(LAST||[]);", html, "the modal's window numbers are the hover's own renderer")
        self.assertIn("function fleetSpendHTML(sets){", html, "…whose signature the other suites pin, untouched")
        self.assertIn("body.theme-light #rsp-panel{", html, "a light-theme step of its own")
        # T247b: the pressed toggle's light rule is written explicitly — a state rule must win the cascade
        # (body.theme-light .rsp-btn at (0,2,1) beat .rsp-btn.on at (0,2,0) and painted dark text on the clay)
        self.assertIn("body.theme-light .rsp-btn.on{background:var(--accent,#C2410C);color:var(--accent-fg,#FFF8F2);border-color:transparent}", html)
        # T247b: the loader has a backstop — an AbortController with a generous timeout lands on the
        # existing error + retry path, so a hung socket can never trap the modal
        self.assertIn("var spAbort=new AbortController()", html)
        self.assertIn("setTimeout(function(){spAbort.abort();}", html)
        self.assertIn("signal:spAbort.signal", html)
        # T247b: dimmed rows dim ONCE — the annotation inside a dimmed row stays at the row's level, and
        # the fold row's "show all" is a control, never dimmed
        self.assertIn(".rsp-dead td{opacity:.55}", html)
        self.assertIn(".rsp-dead .ru-tip-reset{opacity:1}", html)
        self.assertNotIn("<tr class=rsp-dead><td><i class=rsp-sw style=\"background:'+SP_OTHER+'\"></i></td><td class=rsp-name>'+rest.length+' more session", html,
                         "the fold row is not a dead row")
        self.assertIn("<tr class=rsp-fold>", html)
        # T247b: the phone's door is its own row at the hover's button size, full opacity — not an
        # annotation inside .ru-tip-age (10px, .55)
        self.assertIn("<div class=ru-tip-more><button class=rsp-btn id=ru-bysession>", html)
        self.assertNotIn("<div class=ru-tip-age><button class=rsp-btn id=ru-bysession>", html)
        self.assertIn(".ru-tip-more{", html)


if __name__ == "__main__":
    unittest.main()
