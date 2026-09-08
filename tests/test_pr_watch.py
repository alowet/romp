#!/usr/bin/env python3
"""First-class PR-landing watches (the user 2026-08-24, both teams' surveys): a session registers
interest in a PR, the KERNEL polls gh for the terminal state — MERGED, CLOSED, or a FAILED check,
both ends of the standing watcher rule — and delivers ONE [romp] mail, surviving the kernel
restarts that killed every shell loop this replaces. Registrations persist and re-arm on boot (the
reconnect-intent idiom); a gh failure retires the watch LOUDLY after three consecutive errors.
Synthetic only — gh fully stubbed."""
import json
import os
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
SourceFileLoader("romp_event_model", os.path.join(BIN, "romp-event-model")).load_module()
SourceFileLoader("romp_judge", os.path.join(BIN, "romp-judge")).load_module()
km = SourceFileLoader("romp_kernel_prw", os.path.join(BIN, "romp-kernel")).load_module()
jd = km.jd

SID = "11111111-2222-3333-4444-555555555555"


class Verdict(unittest.TestCase):
    """The pure gh-payload reading, executed."""

    def test_merged_and_closed_are_terminal(self):
        self.assertEqual(km._pr_watch_verdict({"state": "MERGED"}), ("merged", ""))
        self.assertEqual(km._pr_watch_verdict({"state": "CLOSED"}), ("closed", ""))

    def test_a_failed_check_is_terminal_with_its_name(self):
        d = {"state": "OPEN", "statusCheckRollup": [
            {"name": "Python 3.12", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"name": "Shell (bats)", "status": "COMPLETED", "conclusion": "FAILURE"}]}
        self.assertEqual(km._pr_watch_verdict(d), ("failed", "Shell (bats)"))

    def test_in_flight_says_busy_for_the_cadence_hint(self):
        d = {"state": "OPEN", "statusCheckRollup": [
            {"name": "x", "status": "IN_PROGRESS", "conclusion": ""}]}
        self.assertEqual(km._pr_watch_verdict(d), (None, "busy"))
        self.assertEqual(km._pr_watch_verdict({"state": "OPEN", "statusCheckRollup": []}), (None, ""))


class Notice(unittest.TestCase):
    """The [romp] mechanics-notice voice, executed (the injected-voice rule: the notice is ABOUT
    romp — like the restart notice it names romp — and carries none of the board vocabulary)."""

    def test_each_terminal_reads_plainly_and_wears_the_machine_tag(self):
        for verdict, must in (("merged", "has MERGED"), ("closed", "CLOSED without merging"),
                              ("failed", "FAILED check"), ("error", "could not read")):
            n = km._pr_watch_notice(verdict, "TESTORG/testrepo", 7, "Shell (bats)")
            self.assertTrue(n.startswith("[romp] "), verdict)
            self.assertIn("TESTORG/testrepo#7", n)
            self.assertIn(must, n)
            self.assertIn("<!-- romp-tag: pr-watch -->", n, "machine-sent dress, never the user's words")
            # T130 (the user 2026-08-27): the chat classifies by MARKER — without romp-injected this
            # notice wore the generic tagged dress instead of the romp attribution the nudges wear
            self.assertIn("<!-- romp-injected --><!-- romp-system -->", n,
                          "the mechanics-notice family's markers, so the one machine-injected rendering applies")
            for word in ("card", "board", "goal", "column", "nudge"):
                self.assertNotIn(word, n.lower(), "no board vocabulary in an injected body")


class Persistence(unittest.TestCase):
    """Registration is intent: survives a restart, re-arms fresh (the reconnect-intent idiom)."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self._saved = (km.PR_WATCH_FILE, list(km._pr_watches))
        km.PR_WATCH_FILE = Path(self.td.name) / "pr-watches.json"
        km._pr_watches[:] = []

    def tearDown(self):
        km.PR_WATCH_FILE = self._saved[0]
        km._pr_watches[:] = self._saved[1]
        self.td.cleanup()

    def test_a_watch_survives_the_restart_and_rearms_fresh(self):
        km.add_pr_watch(7, "TESTORG/testrepo", SID, now=1000)
        km._pr_watches[0]["_fails"] = 2                      # runtime state must NOT persist
        km._pr_watches[0]["_next"] = 99999
        km._pr_watches[:] = []
        km._pr_watches_load()                                # the boot path
        self.assertEqual(len(km._pr_watches), 1)
        r = km._pr_watches[0]
        self.assertEqual((r["pr"], r["repo"], r["sid"], r["at"]), (7, "TESTORG/testrepo", SID, 1000))
        self.assertEqual((r["_next"], r["_fails"]), (0, 0), "re-armed fresh: polls immediately")

    def test_registration_is_idempotent(self):
        km.add_pr_watch(7, "TESTORG/testrepo", SID)
        km.add_pr_watch(7, "TESTORG/testrepo", SID)
        self.assertEqual(len(km._pr_watches), 1)


class SupervisorReachesTheTick(unittest.TestCase):
    """The sweep must run on a box with NO remotes (the 2026-08-25 audit's #664 specimen): `now` was
    bound only inside the supervisor's per-remote loop, so with remotes.json = [] every pass died on
    UnboundLocalError inside the catch-all before reaching _pr_watch_tick — the landing mail never
    sent, and a merged PR's awaiting stamp sat stale for hours with no retire path short of the
    dead-man. The binding is per-pass now; this pins the ORDER (bound before the loop)."""

    def test_now_is_bound_per_pass_before_the_tick(self):
        import inspect
        src = inspect.getsource(km._tunnel_supervisor)
        self.assertIn("now = time.time()               # bound per PASS", src,
                      "the unconditional per-pass binding exists (loop-local bindings do not count)")
        self.assertLess(src.index("now = time.time()               # bound per PASS"),
                        src.index("_pr_watch_tick(now)"),
                        "…and it precedes the tick, so zero remotes can never unbind it")


class Tick(unittest.TestCase):
    """The sweep: terminal delivers + retires; gh failure retires LOUDLY after three; in-flight
    backs off while checks run."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self._saved = (km.PR_WATCH_FILE, list(km._pr_watches), km._pr_watch_read, km._pr_watch_deliver)
        km.PR_WATCH_FILE = Path(self.td.name) / "pr-watches.json"
        km._pr_watches[:] = []
        self.mail = []
        km._pr_watch_deliver = lambda sid, text: self.mail.append((sid, text)) or True

    def tearDown(self):
        km.PR_WATCH_FILE, km._pr_watches[:], km._pr_watch_read, km._pr_watch_deliver = \
            self._saved[0], self._saved[1], self._saved[2], self._saved[3]
        self.td.cleanup()

    def test_merged_delivers_once_and_retires(self):
        km.add_pr_watch(7, "TESTORG/testrepo", SID, now=0)
        km._pr_watch_read = lambda pr, repo: ("merged", "")
        km._pr_watch_tick(100.0)
        self.assertEqual(len(self.mail), 1)
        self.assertIn("has MERGED", self.mail[0][1])
        self.assertEqual(self.mail[0][0], SID)
        self.assertEqual(km._pr_watches, [], "terminal → the watch retires")
        km._pr_watch_tick(200.0)
        self.assertEqual(len(self.mail), 1, "…and never mails twice")

    def test_a_failed_check_holds_mails_once_and_escalates_on_the_bound(self):
        # T143 (the ~6h invisible-ask specimen): a failed check MAILS THE OWNER ONCE and HOLDS —
        # never a silent retire the owner's death can orphan. Resolution is event-keyed; only the
        # no-event gap (nobody acted) takes the bounded escalation to the NAMED target.
        km.add_pr_watch(7, "TESTORG/testrepo", SID, now=0, escalate="mgr")
        km._sid_of_saved = getattr(km, "_sid_of")
        km._sid_of = lambda who: "22222222-2222-3333-4444-555555555555" if who == "mgr" else ""
        try:
            km._pr_watch_read = lambda pr, repo: ("failed", "Shell (bats)")
            km._pr_watch_tick(100.0)
            self.assertEqual(len(self.mail), 1, "the owner is mailed once")
            self.assertIn("FAILED check", self.mail[0][1])
            self.assertEqual(len(km._pr_watches), 1, "…and the watch HOLDS instead of retiring")
            km._pr_watch_tick(200.0)
            self.assertEqual(len(self.mail), 1, "no re-mail while held")
            # the bound passes with the failure still standing → ONE escalation to the named target
            km._pr_watch_tick(100.0 + km.PR_WATCH_ESCALATE_S + 61)
            self.assertEqual(len(self.mail), 2)
            self.assertEqual(self.mail[1][0], "22222222-2222-3333-4444-555555555555")
            self.assertIn("sat with a FAILED check", self.mail[1][1])
            km._pr_watch_tick(100.0 + km.PR_WATCH_ESCALATE_S + 200)
            self.assertEqual(len(self.mail), 2, "the escalation is ONE mail, ever")
            # the terminal event still ends the watch normally
            km._pr_watch_read = lambda pr, repo: ("merged", "")
            km._pr_watch_tick(100.0 + km.PR_WATCH_ESCALATE_S + 300)
            self.assertEqual(len(self.mail), 3)
            self.assertIn("has MERGED", self.mail[2][1])
            self.assertEqual(km._pr_watches, [])
        finally:
            km._sid_of = km._sid_of_saved

    def test_resolution_events_clear_the_held_failure_without_a_clock(self):
        km.add_pr_watch(9, "TESTORG/testrepo", SID, now=0, escalate="mgr")
        km._pr_watch_read = lambda pr, repo: ("failed", "x")
        km._pr_watch_tick(100.0)
        self.assertTrue(km._pr_watches[0].get("failedAt"))
        km._pr_watch_read = lambda pr, repo: (None, "busy")   # checks re-running — the EVENT
        km._pr_watch_tick(200.0)
        self.assertFalse(km._pr_watches[0].get("failedAt"),
                         "the held state clears on the resolution event, no bound involved")
        self.assertEqual(len(self.mail), 1, "clearing is silent — the watch just continues")

    def test_no_target_means_no_ping_ever(self):
        km.add_pr_watch(11, "TESTORG/testrepo", SID, now=0)   # no escalate; no box default in this temp state
        km._pr_watch_read = lambda pr, repo: ("failed", "x")
        km._pr_watch_tick(100.0)
        km._pr_watch_tick(100.0 + km.PR_WATCH_ESCALATE_S + 61)
        self.assertEqual(len(self.mail), 1, "the kernel never guesses a manager — unset = no ping")

    def test_failed_state_survives_the_save_load_cycle(self):
        # the specimen window held ~21 restarts — a clock that reset each boot would never fire
        km.add_pr_watch(13, "TESTORG/testrepo", SID, now=0, escalate="mgr")
        km._pr_watch_read = lambda pr, repo: ("failed", "x")
        km._pr_watch_tick(100.0)
        km._pr_watches_save()
        km._pr_watches[:] = []
        km._pr_watches_load()
        r = km._pr_watches[0]
        self.assertEqual((r.get("failedAt"), r.get("escalate")), (100, "mgr"),
                         "failedAt and the target persist across the restart")

    def test_gh_failure_retires_loudly_after_three_never_silently(self):
        km.add_pr_watch(9, "TESTORG/testrepo", SID, now=0)
        km._pr_watch_read = lambda pr, repo: ("error", "auth required")
        km._pr_watch_tick(100.0)
        km._pr_watch_tick(100.0 + km.PR_WATCH_EVERY)
        self.assertEqual(self.mail, [], "two failures → still trying, still quiet")
        km._pr_watch_tick(100.0 + 2 * km.PR_WATCH_EVERY)
        self.assertEqual(len(self.mail), 1, "the third delivers the loud retire")
        self.assertIn("could not read", self.mail[0][1])
        self.assertIn("auth required", self.mail[0][1])
        self.assertEqual(km._pr_watches, [])

    def test_in_flight_backs_off_while_checks_run(self):
        km.add_pr_watch(10, "TESTORG/testrepo", SID, now=0)
        km._pr_watch_read = lambda pr, repo: (None, "busy")
        km._pr_watch_tick(100.0)
        self.assertEqual(km._pr_watches[0]["_next"], 100.0 + km.PR_WATCH_BUSY_EVERY)
        km._pr_watch_read = lambda pr, repo: (None, "")
        km._pr_watch_tick(100.0 + km.PR_WATCH_BUSY_EVERY)
        self.assertEqual(km._pr_watches[0]["_next"],
                         100.0 + km.PR_WATCH_BUSY_EVERY + km.PR_WATCH_EVERY)
        self.assertEqual(self.mail, [])


class Route(unittest.TestCase):
    """POST /watch-pr over the real Handler: registration + refusals; token-gated."""

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
        self._saved = (km.PR_WATCH_FILE, list(km._pr_watches), km._sid_of)
        km.PR_WATCH_FILE = Path(self.td.name) / "pr-watches.json"
        km._pr_watches[:] = []
        km._sid_of = lambda who: SID if who in (SID, "web") else ""

    def tearDown(self):
        km.PR_WATCH_FILE, km._pr_watches[:], km._sid_of = self._saved
        self.td.cleanup()

    def _post(self, body, token=True):
        req = urllib.request.Request(
            "http://127.0.0.1:%d/watch-pr" % self.port, data=json.dumps(body).encode(),
            headers=dict({"Content-Type": "application/json"},
                         **({"X-Romp-Token": os.environ["ROMP_SERVE_TOKEN"]} if token else {})))
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, (e.read() or b"").decode()

    def test_registers_by_name_and_persists(self):
        st, r = self._post({"pr": 7, "repo": "TESTORG/testrepo", "name": "web"})
        self.assertEqual(st, 200)
        self.assertTrue(r["ok"])
        self.assertEqual(r["watch"]["sid"], SID)
        self.assertEqual(json.loads(km.PR_WATCH_FILE.read_text())[0]["pr"], 7)

    def test_refusals_are_loud_and_shaped(self):
        self.assertEqual(self._post({"repo": "TESTORG/testrepo", "name": "web"})[0], 400)
        self.assertEqual(self._post({"pr": 7, "repo": "not-a-repo", "name": "web"})[0], 400)
        st, r = self._post({"pr": 7, "repo": "TESTORG/testrepo", "name": "ghost"})
        self.assertFalse(r["ok"]); self.assertIn('no session answers to "ghost"', r["error"])
        self.assertEqual(self._post({"pr": 7, "repo": "TESTORG/testrepo", "name": "web"},
                                    token=False)[0], 403)



class VerdictJudgesEachCheckByItsNewestRun(unittest.TestCase):
    """T256: gh's statusCheckRollup keeps SUPERSEDED runs beside their re-runs — the label workflow
    left a failed run next to the passing one on every `gh pr create --label` PR, and any manual
    re-run does the same. The first FAILURE in list order was treated as terminal, so a stale red run
    mailed a false "FAILED check … will not land" (twice on 2026-09-07). The merge box's own rule:
    group by check name, judge each name by its NEWEST run (completion time), decide only then."""

    def _run(self, name, conclusion, completed, status="COMPLETED"):
        return {"name": name, "conclusion": conclusion, "status": status,
                "startedAt": completed.replace("Z", "") and "2026-09-07T05:00:00Z", "completedAt": completed}

    def test_a_stale_failure_beside_a_newer_success_of_the_same_name_is_not_failed(self):
        d = {"state": "OPEN", "statusCheckRollup": [
            self._run("label check", "FAILURE", "2026-09-07T05:40:00Z"),     # the superseded run, listed first
            self._run("Python 3.12", "SUCCESS", "2026-09-07T05:45:00Z"),
            self._run("label check", "SUCCESS", "2026-09-07T05:50:00Z"),     # the re-run that actually counts
        ]}
        self.assertEqual(km._pr_watch_verdict(d), (None, ""),
                         "every name's NEWEST run passed and the PR is open → keep watching, never 'failed'")

    def test_a_newer_failure_after_an_older_success_is_failed(self):
        d = {"state": "OPEN", "statusCheckRollup": [
            self._run("Shell (bats)", "SUCCESS", "2026-09-07T05:40:00Z"),
            self._run("Shell (bats)", "FAILURE", "2026-09-07T05:50:00Z"),
        ]}
        self.assertEqual(km._pr_watch_verdict(d), ("failed", "Shell (bats)"), "the newest run of that name is red")

    def test_a_running_rerun_of_a_failed_name_keeps_watching(self):
        d = {"state": "OPEN", "statusCheckRollup": [
            self._run("Shell (bats)", "FAILURE", "2026-09-07T05:40:00Z"),
            {"name": "Shell (bats)", "conclusion": "", "status": "IN_PROGRESS", "startedAt": "2026-09-07T05:55:00Z", "completedAt": None},
        ]}
        self.assertEqual(km._pr_watch_verdict(d), (None, "busy"), "its newest run is still in flight — the old red is superseded")


if __name__ == "__main__":
    unittest.main()
