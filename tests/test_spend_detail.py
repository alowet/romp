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
        self.assertEqual(d["hosts"], 1)
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
        self.assertIn("windows", d)
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
        self.assertEqual(by["api"]["usd"], 0.0, "a login-only session bills nothing to the key")
        self.assertEqual(d["unattributed"]["usd"], 0.0)
        # the TOTAL scope, same ledger: the split rides beside the totals where the hover would show it
        km._claude_account = lambda: ""
        d2 = km._spend_detail(now=NOW)
        self.assertEqual(d2["scope"], "total")
        by2 = {s["name"]: s for s in d2["sessions"]}
        self.assertAlmostEqual(by2["web"]["usd"], 6.0, places=3)
        self.assertEqual(by2["web"]["key"], {"usd": 2.0, "tok": 20000, "turns": 2})
        self.assertNotIn("key", by2["api"])

    def test_other_machines_are_counted_so_the_modal_can_say_this_machine_only(self):
        km._remotes["peer"] = {"host": "peer", "status": "up", "usage": {"apiKey": True}}
        km._remotes["down"] = {"host": "down", "status": "down", "usage": {"apiKey": True}}
        d = km._spend_detail(now=NOW)
        self.assertEqual(d["hosts"], 2, "one live peer joins the fleet totals; its bySid does not reach us")

    def test_an_empty_or_missing_ledger_answers_with_zeros_not_an_error(self):
        (km.jd.STATE / "spend.json").unlink()
        d = km._spend_detail(now=NOW)
        self.assertEqual(d["sessions"], [])
        self.assertEqual(d["days"]["stacks"], [])
        self.assertEqual(len(d["days"]["keys"]), 90)

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
        self.assertIn("this machine only", html)
        self.assertIn("recorded before per-session tracking", html, "unattributed spend is named, never folded")
        self.assertIn("fleetSpendHTML(LAST||[],true)", html, "the modal's window numbers are the hover's own renderer")
        self.assertIn("body.theme-light #rsp-panel{", html, "a light-theme step of its own")


if __name__ == "__main__":
    unittest.main()
