#!/usr/bin/env python3
"""The mesh/origin-aware update notice (the user 2026-08-14): the release banner only watched TAGS, so
ordinary merges sat undeployed with every machine reading "in sync" — all equally stale. The kernel now
also compares origin/main vs the checkout vs the RUNNING build, fires the same banner (kind:"main"),
and converges on click or unattended per the update mode. Pure verdict unit-tested; the wiring pinned
by source (the rail-spend pattern). Synthetic only; hermetic state dir."""
import inspect
import os
import tempfile
import unittest
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
# Hermetic state BEFORE the loads — they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "test-token-DO-NOT-USE")
os.environ["ROMP_MANAGER_PORT"] = "1"   # dead port: an unstubbed converge dials nothing real
SourceFileLoader("romp_event_model", os.path.join(BIN, "romp-event-model")).load_module()
SourceFileLoader("romp_judge", os.path.join(BIN, "romp-judge")).load_module()
km = SourceFileLoader("romp_kernel_drift", os.path.join(BIN, "romp-kernel")).load_module()


class ReleaseRemote(unittest.TestCase):
    """_release_remote picks the remote the updater reads. The remote convention (the user
    2026-09-06) makes a maintainer's `origin` their FORK, whose main nobody advances: an updater
    still reading a literal `origin` would report the fork's stale main as the truth and, in auto
    mode, walk the checkout backwards onto it. A plain bootstrap install has only `origin`, which
    IS the canonical repo. Throwaway repos; no network."""

    def _repo_with_remotes(self, *names):
        import subprocess
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", d], check=True)
        for n in names:
            subprocess.run(["git", "-C", d, "remote", "add", n, "https://example.invalid/%s.git" % n], check=True)
        return d

    def _resolve_in(self, root):
        from pathlib import Path
        saved = km.ROOT
        km.ROOT = Path(root)
        try:
            return km._release_remote()
        finally:
            km.ROOT = saved

    def test_a_fork_layout_reads_upstream(self):
        self.assertEqual(self._resolve_in(self._repo_with_remotes("origin", "upstream")), "upstream")

    def test_a_plain_install_reads_origin(self):
        self.assertEqual(self._resolve_in(self._repo_with_remotes("origin")), "origin")

    def test_no_git_checkout_falls_back_to_origin(self):
        self.assertEqual(self._resolve_in(tempfile.mkdtemp()), "origin")

    def test_every_updater_probe_and_walk_goes_through_it(self):
        for fn in (km._latest_release_tag, km._origin_main_sha, km._run_main_update, km._run_update):
            self.assertIn("_release_remote()", inspect.getsource(fn), fn.__name__)
            self.assertNotIn('"origin"', inspect.getsource(fn), "%s still names a literal origin" % fn.__name__)


class DriftVerdict(unittest.TestCase):
    def test_origin_ahead_of_the_checkout_wants_a_pull(self):
        self.assertEqual(km._main_drift_verdict("aaaa1111", "bbbb2222", "bbbb2222"), ("pull", "aaaa1111"))

    def test_checkout_ahead_of_the_running_kernel_wants_a_restart(self):
        # the hand-advanced case: updated code sits on disk, nothing booted it
        self.assertEqual(km._main_drift_verdict("aaaa1111", "aaaa1111", "cccc3333"), ("restart", "aaaa1111"))

    def test_pull_outranks_restart_when_both_hold(self):
        # origin ahead AND the running build stale: one pull converges both in a single bounce
        self.assertEqual(km._main_drift_verdict("aaaa1111", "bbbb2222", "cccc3333")[0], "pull")

    def test_in_sync_is_quiet(self):
        self.assertEqual(km._main_drift_verdict("aaaa1111", "aaaa1111", "aaaa1111"), ("", ""))

    def test_unknown_shas_never_invent_a_notice(self):
        # offline ls-remote, unreadable checkout, missing running sha: unknown, not a disagreement
        self.assertEqual(km._main_drift_verdict("", "bbbb2222", "bbbb2222"), ("", ""))
        self.assertEqual(km._main_drift_verdict("aaaa1111", "", "bbbb2222"), ("", ""))
        self.assertEqual(km._main_drift_verdict("", "", ""), ("", ""))


class DriftWiring(unittest.TestCase):
    def test_off_mode_silences_the_watcher_and_auto_converges_unattended(self):
        src = inspect.getsource(km._main_drift_check)
        self.assertIn('if _update_mode() == "off":', src)
        self.assertIn('if _update_mode() == "auto":', src)
        self.assertIn("_run_main_update(kind)", src)
        self.assertIn('"kind": "main"', src, "ask mode fires the shared banner with the drift variant")

    def test_a_dirty_shared_tree_refuses_loudly_and_rearms(self):
        src = inspect.getsource(km._run_main_update)
        self.assertIn('"status", "--porcelain"', src)
        self.assertIn("uncommitted work", src, "the refusal names the real problem")
        self.assertIn('_MAIN_DRIFT[0] = ""', src, "the notice re-fires once the tree is clean")
        self.assertIn('"checkout", "--detach", "%s/main" % remote', src, "advance is the repo's own convention")
        self.assertIn("remote = _release_remote()", src,
                      "the walk targets the RELEASE remote, never a literal origin (a fork layout's stale mirror)")

    def test_every_converge_is_immediate_by_default_and_quiet_stays_expressible(self):
        # T160 (the user 2026-08-28): deploys cut in-flight turns NOW — auto converge included.
        # The quiet spelling survives as an explicit opt-in, so the drain machinery stays testable
        # and reachable, it just stopped being the default.
        sig = inspect.signature(km._run_main_update)
        self.assertIs(sig.parameters["immediate"].default, True,
                      "auto converge is a deploy: immediate by default")
        src = inspect.getsource(km._run_main_update)
        self.assertIn('"" if immediate else "?when=quiet"', src,
                      "immediate=False still rides the quiet window explicitly")
        self.assertIn('_audit_restart_request("main-converge"', src,
                      "the converge names itself in restart-audit.jsonl so the cut row joins to it")
        route = inspect.getsource(km)
        self.assertIn('threading.Thread(target=_run_main_update, args=(kind, True),', route,
                      "the banner click stays explicitly immediate")

    def test_auto_converges_batch_behind_the_cool_down(self):
        # the user 2026-08-15, after flipping auto: main took a merge every few minutes and auto mode
        # converged once per commit — 4+ restarts/hour, each cutting every in-flight turn. Behind the
        # cool-down, N merges inside the window become ONE restart to the LATEST sha.
        ran = []
        saved = (km._update_mode, km._origin_main_sha, km._checkout_sha, km._kernel_sha,
                 km._run_main_update, km._LAST_AUTO_CONVERGE[0], km._MAIN_DRIFT[0], km._MAIN_DRIFT[1])
        km._update_mode = lambda: "auto"
        km._checkout_sha = lambda: "aaa"
        km._kernel_sha = lambda: "aaa"
        km._run_main_update = lambda kind, immediate=False: ran.append(kind)
        try:
            km._MAIN_DRIFT[0] = km._MAIN_DRIFT[1] = ""
            km._LAST_AUTO_CONVERGE[0] = 0.0
            km._origin_main_sha = lambda: "bbb"
            km._main_drift_check()
            self.assertEqual(ran, ["pull"], "the first drift converges at once")
            km._origin_main_sha = lambda: "ccc"          # a new merge lands inside the window
            km._main_drift_check()
            self.assertEqual(ran, ["pull"], "inside the cool-down, no second restart")
            self.assertEqual(km._MAIN_DRIFT[0], "", "the deferred sha is NOT marked offered")
            km._LAST_AUTO_CONVERGE[0] = 0.0              # the window passes
            km._main_drift_check()
            self.assertEqual(ran, ["pull", "pull"], "past the window, one converge takes the LATEST sha")
        finally:
            (km._update_mode, km._origin_main_sha, km._checkout_sha, km._kernel_sha,
             km._run_main_update) = saved[:5]
            km._LAST_AUTO_CONVERGE[0] = saved[5]
            km._MAIN_DRIFT[0], km._MAIN_DRIFT[1] = saved[6], saved[7]

    def test_the_cool_down_holds_across_the_restart_it_spaces(self):
        # T240: the cool-down lived in module memory ("a restart resets it, which is fine — the
        # restart WAS the converge"). It was not fine: the converge's own restart boots a fresh
        # process with the cool-down at zero, so the next merge converged again at once — 05:19Z then
        # 05:24Z against a 1500 s window. The last DEPLOY restart is read from durable state (the
        # restart-cuts ledger's newest deploy row), so a fresh process still honours the window.
        import json, time
        ran = []
        saved = (km._update_mode, km._origin_main_sha, km._checkout_sha, km._kernel_sha,
                 km._run_main_update, km._LAST_AUTO_CONVERGE[0], km._MAIN_DRIFT[0], km._MAIN_DRIFT[1])
        km._update_mode = lambda: "auto"
        km._checkout_sha = lambda: "aaa"
        km._kernel_sha = lambda: "aaa"
        km._origin_main_sha = lambda: "bbb"
        km._run_main_update = lambda kind, immediate=False: ran.append(kind)
        try:
            km._MAIN_DRIFT[0] = km._MAIN_DRIFT[1] = ""
            km._LAST_AUTO_CONVERGE[0] = 0.0                       # a FRESH process: module memory is empty
            now = time.time()
            with open(km.RESTART_CUTS_FILE, "a") as f:            # …but the ledger says a deploy restart
                f.write(json.dumps({"t": int(now - 300), "reason": "main-converge", "cutTurns": []}) + "\n")
            km._main_drift_check()
            self.assertEqual(ran, [], "5 min after a landed deploy restart, the cool-down still holds")
            self.assertEqual(km._MAIN_DRIFT[0], "", "the deferred sha stays unoffered — the first pass past the window takes the LATEST")
            km.RESTART_CUTS_FILE.write_text(json.dumps({"t": int(now - 2000), "reason": "p2p-update: from X to Y",
                                                        "cutTurns": []}) + "\n")
            km._main_drift_check()
            self.assertEqual(ran, ["pull"], "past the window, the converge fires")
        finally:
            (km._update_mode, km._origin_main_sha, km._checkout_sha, km._kernel_sha,
             km._run_main_update) = saved[:5]
            km._LAST_AUTO_CONVERGE[0] = saved[5]
            km._MAIN_DRIFT[0], km._MAIN_DRIFT[1] = saved[6], saved[7]
            if km.RESTART_CUTS_FILE.exists():
                km.RESTART_CUTS_FILE.unlink()

    def test_the_audit_row_anchors_the_window_when_the_cut_row_was_lost(self):
        # review find, reproduced by simulation: a stale-manager converge can lose its cut row (the
        # parent-watch exited the kernel mid-drain). The deploy's AUDIT row is written before the
        # restart and survives — it anchors the window on its own.
        import json, time
        now = time.time()
        audit = km.jd.STATE / "restart-audit.jsonl"
        audit.write_text(json.dumps({"t": int(now - 300), "action": "main-converge", "when": "now", "tag": "pull"}) + "\n")
        started = km._STARTED
        km._STARTED = now - 3600      # this process booted long before every row below
        try:
            # the request LANDED: a boot row newer than it (the cut row itself was lost)
            km.RESTART_CUTS_FILE.write_text(json.dumps({"t": int(now - 296), "bootSettled": True, "pid": 1}) + "\n")
            self.assertAlmostEqual(km._last_deploy_restart_t(), now - 300, delta=2, msg="no cut row needed")
            # a request nothing has booted since — a self-update click whose script failed, a p2p
            # apply that restarted nothing — anchors NOTHING (event, not time)
            km.RESTART_CUTS_FILE.write_text(json.dumps({"t": int(now - 900), "bootSettled": True, "pid": 1}) + "\n")
            self.assertEqual(km._last_deploy_restart_t(), 0.0, "requested, never landed")
            # the RUNNING kernel is a boot too (review find): the new kernel's own boot row lands only
            # after its first serve and reconcile, and the drift loop's first pass runs before that —
            # a lost-row deploy must anchor on that very pass, not one boot row later
            km._STARTED = now - 10
            self.assertAlmostEqual(km._last_deploy_restart_t(), now - 300, delta=2,
                                   msg="a request older than this process has, by construction, been followed by a boot")
            km._STARTED = now - 3600
            # a cut row BETWEEN the request and the boot that the ledger did not join to it (review
            # find): the restart that booted was recorded and attributed elsewhere — an anonymous
            # manual restart ten minutes after a self-update click whose script failed — so the
            # click restarted nothing and anchors nothing, however many boots follow it
            km.RESTART_CUTS_FILE.write_text(json.dumps({"t": int(now - 94), "reason": "", "cutTurns": []}) + "\n"
                                            + json.dumps({"t": int(now - 90), "bootSettled": True, "pid": 1}) + "\n")
            self.assertEqual(km._last_deploy_restart_t(), 0.0, "a later unrelated restart does not land an earlier request")
            # …but a cut row the ledger DID join to the request (auditT) is the request landing
            km.RESTART_CUTS_FILE.write_text(json.dumps({"t": int(now - 294), "reason": "", "cutTurns": [],
                                                        "auditT": int(now - 300)}) + "\n"
                                            + json.dumps({"t": int(now - 290), "bootSettled": True, "pid": 1}) + "\n")
            self.assertAlmostEqual(km._last_deploy_restart_t(), now - 300, delta=2, msg="its own cut row is not a stranger's")
            km.RESTART_CUTS_FILE.write_text(json.dumps({"t": int(now - 296), "bootSettled": True, "pid": 1}) + "\n")
            audit.write_text(json.dumps({"t": int(now - 200), "action": "main-converge", "tag": "abc"}) + "\n")
            self.assertEqual(km._last_deploy_restart_t(), 0.0, "a clicked-Update request row without when=now "
                             "is not a landed deploy on its own")
            audit.write_text(json.dumps({"t": int(now - 100), "action": "p2p-update", "reason": "from X to Y",
                                         "when": "quiet"}) + "\n")
            self.assertEqual(km._last_deploy_restart_t(), 0.0, "a peer's apply that has not restarted us yet anchors nothing")
            km.RESTART_CUTS_FILE.write_text(json.dumps({"t": int(now - 90), "bootSettled": True, "pid": 1}) + "\n")
            self.assertAlmostEqual(km._last_deploy_restart_t(), now - 100, delta=2, msg="a peer's apply anchors once it landed")
        finally:
            km._STARTED = started
            audit.unlink()

    def test_a_parked_quiet_deploy_for_the_checkouts_sha_stands_the_converge_down(self):
        # T240d: a peer's p2p apply advanced the checkout and parked a QUIET restart at the manager;
        # the drift check then saw the checkout ahead of the kernel and posted an IMMEDIATE
        # restart-all — 16:23Z quiet park, 16:27Z converge/now, ten sessions cut — so the quiet
        # window the peer asked for never ran. The restart is already on its way: stand down, once,
        # keyed on the ledger row and its consumption (the row expires with the far manager's
        # backstop, the same bound a pending quiet request already has for cut attribution).
        import contextlib, io, json, time
        now = time.time()
        audit = km.jd.STATE / "restart-audit.jsonl"
        ran = []
        saved = (km._update_mode, km._origin_main_sha, km._checkout_sha, km._kernel_sha,
                 km._run_main_update, km._LAST_AUTO_CONVERGE[0], km._MAIN_DRIFT[0], km._MAIN_DRIFT[1],
                 km._kernel_code_changed, km._QUIET_PARKED_LOGGED[0], km._CONVERGE_COOLDOWN_S)
        km._update_mode = lambda: "auto"
        km._kernel_code_changed = lambda a, b: True
        km._CONVERGE_COOLDOWN_S = 0.0      # isolate the stand-down: the cool-down is T240's own gate
        km._run_main_update = lambda kind, immediate=False: ran.append(kind)
        km._checkout_sha = lambda: "f3dc387a" + "0" * 32
        km._origin_main_sha = km._checkout_sha
        km._kernel_sha = lambda: "aaaaaaaa" + "0" * 32

        def check():
            km._MAIN_DRIFT[0] = km._MAIN_DRIFT[1] = ""
            km._LAST_AUTO_CONVERGE[0] = 0.0
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                km._main_drift_check()
            return err.getvalue()

        try:
            km._QUIET_PARKED_LOGGED[0] = ""
            if km.RESTART_CUTS_FILE.exists():
                km.RESTART_CUTS_FILE.unlink()
            # the 16:23Z shape: checkout ahead of the kernel, a quiet p2p row for the checkout's sha
            audit.write_text(json.dumps({"t": int(now - 240), "action": "p2p-update",
                                         "reason": "from TESTHOST to f3dc387a", "when": "quiet"}) + "\n")
            out = check()
            self.assertEqual(ran, [], "a quiet deploy for this very code is parked: the converge stands down")
            self.assertIn("already parked as a quiet deploy", out, "one line says why nothing happened")
            self.assertEqual(km._MAIN_DRIFT[1], "", "the sha is not marked acted on — the next pass re-evaluates")
            self.assertNotIn("already parked", check(), "…but says it once per sha, not once per pass")
            self.assertEqual(ran, [])
            # the 08:42Z shape: origin reads ahead of the checkout too (a stale fetch, or a merge
            # that landed meanwhile) — the parked restart still delivers the code on disk first;
            # one restart, not two, and the pull follows on the next pass after it lands
            km._origin_main_sha = lambda: "bbbbbbbb" + "0" * 32
            check()
            self.assertEqual(ran, [], "a pull does not pre-empt the parked quiet deploy either")
            km._origin_main_sha = km._checkout_sha
            # CONSUMED: the cut row that landed the quiet deploy joined the row — nothing is parked
            km.RESTART_CUTS_FILE.write_text(json.dumps({"t": int(now - 30), "reason": "p2p-update: from TESTHOST to f3dc387a",
                                                        "cutTurns": [], "auditT": int(now - 240)}) + "\n")
            check()
            self.assertEqual(ran, ["restart"], "a consumed row parks nothing: the converge proceeds as today")
            km.RESTART_CUTS_FILE.unlink()
            # a quiet row for a DIFFERENT sha: not this code — proceeds
            ran.clear()
            audit.write_text(json.dumps({"t": int(now - 240), "action": "p2p-update",
                                         "reason": "from TESTHOST to 99999999", "when": "quiet"}) + "\n")
            check()
            self.assertEqual(ran, ["restart"], "a quiet deploy of other code is not this converge")
            # an IMMEDIATE p2p row (the no-owning-manager fallback): nothing is parked — proceeds
            ran.clear()
            audit.write_text(json.dumps({"t": int(now - 240), "action": "p2p-update",
                                         "reason": "from TESTHOST to f3dc387a (immediate: no owning manager)"}) + "\n")
            check()
            self.assertEqual(ran, ["restart"], "an immediate request parks nothing")
            # a quiet row older than the far manager's backstop bound: the park is gone (its manager
            # died with it) — the converge proceeds rather than waiting forever
            ran.clear()
            audit.write_text(json.dumps({"t": int(now - km.RESTART_EXPECT_MAX_S - 30), "action": "p2p-update",
                                         "reason": "from TESTHOST to f3dc387a", "when": "quiet"}) + "\n")
            check()
            self.assertEqual(ran, ["restart"], "past the backstop bound nothing can still be parked")
            # a QUIET converge row from the explicit immediate=False door carries the sha it deploys:
            # parked too (no production caller passes immediate=False today; the CLI door is below)
            ran.clear()
            km._QUIET_PARKED_LOGGED[0] = ""
            audit.write_text(json.dumps({"t": int(now - 60), "action": "main-converge", "tag": "restart",
                                         "when": "quiet", "sha": "f3dc387a" + "0" * 32}) + "\n")
            check()
            self.assertEqual(ran, [], "a quiet local converge for this sha is parked the same way")
            # …a legacy quiet converge row without a sha cannot be matched: proceeds (never guesses)
            audit.write_text(json.dumps({"t": int(now - 60), "action": "main-converge", "tag": "restart",
                                         "when": "quiet"}) + "\n")
            check()
            self.assertEqual(ran, ["restart"], "no sha on the row, no stand-down")
            # the CLI door (review find): `romp refresh --quiet` writes bin/romp's caller-attribution
            # row — no action — now with when=quiet and the checkout sha; it parks the same way
            ran.clear()
            km._QUIET_PARKED_LOGGED[0] = ""
            audit.write_text(json.dumps({"t": int(now - 60), "ppid": 4242, "parent": "bash", "sid": "", "name": "",
                                         "tty": "/dev/pts/0", "tmux": "", "when": "quiet", "sha": "f3dc387a"}) + "\n")
            check()
            self.assertEqual(ran, [], "a quiet CLI refresh for this sha is a parked deploy too")
            # a busy box (review find): fifty session self-closes write fifty end-on-idle rows after
            # the quiet row — the reader walks past them; the park is still live
            ran.clear()
            audit.write_text(json.dumps({"t": int(now - 240), "action": "p2p-update",
                                         "reason": "from TESTHOST to f3dc387a", "when": "quiet"}) + "\n"
                             + "".join(json.dumps({"t": int(now - 200 + i), "action": "end-on-idle", "sid": "s%d" % i}) + "\n"
                                       for i in range(50)))
            check()
            self.assertEqual(ran, [], "fifty no-restart rows do not hide a live park")
            # LANDED, cut row lost (review find): the kernel already runs the checkout, the row is still
            # unconsumed — nothing is owed, so a pull must not wait on it (and says nothing about a park)
            ran.clear()
            km._QUIET_PARKED_LOGGED[0] = ""
            audit.write_text(json.dumps({"t": int(now - 240), "action": "p2p-update",
                                         "reason": "from TESTHOST to f3dc387a", "when": "quiet"}) + "\n")
            km._kernel_sha = km._checkout_sha
            km._origin_main_sha = lambda: "bbbbbbbb" + "0" * 32
            out = check()
            self.assertEqual(ran, ["pull"], "the parked restart already delivered: the pull proceeds")
            self.assertNotIn("already parked", out)
            km._kernel_sha = lambda: "aaaaaaaa" + "0" * 32
            km._origin_main_sha = km._checkout_sha
            # a stand-down that ENDS without landing (the row expired: the park died with its manager)
            # says so once, then the converge proceeds on its own terms (review find: silent expiry)
            ran.clear()
            km._QUIET_PARKED_LOGGED[0] = ""
            check()
            self.assertEqual(ran, [], "parked again")
            audit.write_text(json.dumps({"t": int(now - km.RESTART_EXPECT_MAX_S - 30), "action": "p2p-update",
                                         "reason": "from TESTHOST to f3dc387a", "when": "quiet"}) + "\n")
            out = check()
            self.assertEqual(ran, ["restart"])
            self.assertIn("no longer pending", out, "the end of a stand-down is said, not silent")
            self.assertNotIn("no longer pending", check(), "…once")
        finally:
            (km._update_mode, km._origin_main_sha, km._checkout_sha, km._kernel_sha,
             km._run_main_update) = saved[:5]
            km._LAST_AUTO_CONVERGE[0] = saved[5]
            km._MAIN_DRIFT[0], km._MAIN_DRIFT[1] = saved[6], saved[7]
            km._kernel_code_changed, km._QUIET_PARKED_LOGGED[0] = saved[8], saved[9]
            km._CONVERGE_COOLDOWN_S = saved[10]
            audit.unlink()
            if km.RESTART_CUTS_FILE.exists():
                km.RESTART_CUTS_FILE.unlink()

    def test_the_quiet_deploy_rows_carry_what_the_stand_down_reads(self):
        # T240d pins on the writers: the p2p apply's quiet audit row lands right after the reset that
        # advances the checkout — BEFORE the owner check, whose manager status call is the window a
        # drift pass could hit between "checkout ahead" and "row on disk" — and the local converge's
        # row carries the sha it deploys, so a quiet `romp refresh` is matched, not guessed at
        ksrc = open(os.path.join(os.path.dirname(HERE), "kernel", "kernel.py")).read()
        reset = ksrc.index("reset --hard %s >/dev/null 2>&1 || {")
        row = ksrc.index("\\'action\\':\\'p2p-update\\',")     # the shell script's escaped spelling
        owned = ksrc.index("'OWNED=0; if command -v node")
        self.assertLess(reset, row, "the row says the checkout IS at the sha: it follows the reset")
        self.assertLess(row, owned, "and precedes the owner check, so the drift check sees it at once")
        self.assertIn('_audit_restart_request("main-converge", tag=kind, when=("now" if immediate else "quiet"),\n'
                      '                               sha=', ksrc,
                      "the converge row names the sha it deploys")
        # the CLI door: bin/romp's own caller-attribution row says when=quiet and names the checkout
        # sha under --quiet (behavior pinned in tests/romp-refresh-audit.bats; the spelling here)
        rsrc = open(os.path.join(os.path.dirname(HERE), "bin", "romp")).read()
        self.assertIn('RA_WHEN="${2:-}"', rsrc)
        self.assertIn('if os.environ.get("RA_WHEN") == "--quiet":\n    # a PARKED restart', rsrc)
        self.assertIn('row["when"] = "quiet"', rsrc)

    def test_the_parent_watch_stands_down_under_a_graceful_term(self):
        # behavioral (review find: the source-order pin executed nothing): the manager is gone —
        # with the graceful term running the watchdog returns; without it, it exits the kernel
        from unittest import mock
        exits = []
        saved = (km._pid_alive, os.environ.get("ROMP_MANAGER_PID"), km._TERMINATING[0])
        km._pid_alive = lambda pid: False
        os.environ["ROMP_MANAGER_PID"] = "424242"
        try:
            km._TERMINATING[0] = True
            with mock.patch.object(km.os, "_exit", lambda code: exits.append(code)):
                km._parent_watch()
            self.assertEqual(exits, [], "the graceful term owns the exit")
            km._TERMINATING[0] = False
            with mock.patch.object(km.os, "_exit", lambda code: exits.append(code)):
                km._parent_watch()
            self.assertEqual(exits, [0], "a dead manager with no drain running still exits the kernel")
        finally:
            km._pid_alive = saved[0]
            if saved[1] is None:
                os.environ.pop("ROMP_MANAGER_PID", None)
            else:
                os.environ["ROMP_MANAGER_PID"] = saved[1]
            km._TERMINATING[0] = saved[2]
        import inspect
        gt = inspect.getsource(km._graceful_term)
        self.assertLess(gt.index("_TERMINATING[0] = True"), gt.index("_broadcast_restarting()"),
                        "the flag is the FIRST thing the graceful term does")

    def test_only_deploy_restarts_count_toward_the_cool_down(self):
        # a rail-button restart, a self-close, an in-place skip: none of them is a converge, so none
        # of them spaces the next one
        import json, time
        now = time.time()
        km.RESTART_CUTS_FILE.write_text("".join(json.dumps(r) + "\n" for r in [
            {"t": int(now - 3000), "reason": "main-converge", "cutTurns": []},
            {"t": int(now - 100), "reason": "kernel-asks-manager-restart-all: rail button", "cutTurns": []},
            {"t": int(now - 50), "reason": "main-converge-skip", "cutTurns": []},
            {"t": int(now + 7200), "reason": "p2p-update: from X to Y", "cutTurns": []},   # a clock stepped back
        ]))
        try:
            self.assertAlmostEqual(km._last_deploy_restart_t(), now - 3000, delta=2)
            km.RESTART_CUTS_FILE.write_text(json.dumps(
                {"t": int(now - 200), "reason": "self-update: v0.15 -> v0.16", "cutTurns": []}) + "\n")
            self.assertAlmostEqual(km._last_deploy_restart_t(), now - 200, delta=2,
                                   msg="a release self-update is a deploy restart too")
        finally:
            km.RESTART_CUTS_FILE.unlink()

    def test_the_shell_banner_carries_the_drift_variants(self):
        src = inspect.getsource(km)
        self.assertIn("m.drift||''", src, "the shell relay forwards the drift kind")
        self.assertIn("new romp commits are on main", src)
        self.assertIn("is ready on disk", src)

    def test_the_route_acts_only_on_what_the_kernel_itself_found(self):
        src = inspect.getsource(km)
        self.assertIn('kind = "pull" if _MAIN_DRIFT[0] else ("restart" if _MAIN_DRIFT[1] else "")', src,
                      "no version or kind is ever taken from the client")


if __name__ == "__main__":
    unittest.main()


class UiOnlyConverge(unittest.TestCase):
    """A drift whose commits touch nothing the running process executes converges by rebuilding dist
    in place — kernel left up, zero cut turns (the user 2026-08-23: most changes are UI-only, and
    every restart cuts every in-flight turn). Kernel-code drift keeps the restart path unchanged."""

    def setUp(self):
        self._saved = {n: getattr(km, n) for n in
                       ("_main_drift_verdict", "_kernel_code_changed", "_rebuild_dist",
                        "_sync_notice", "_update_mode", "_send_to_app", "_kernel_sha",
                        "_main_tracking", "_converge_classes")}
        km._MAIN_DRIFT[0] = km._MAIN_DRIFT[1] = ""
        km._REBUILT_FOR[0] = ""
        km._INPLACE_TRIED[0] = ""
        km._converge_classes = lambda a, b: {"kernel": [], "bus": [],
                                             "skip": ["ui/webview/feed.ts"], "ast_equal": []}
        self.notices, self.banners, self.rebuilds = [], [], []
        km._sync_notice = lambda msg, ok=True: self.notices.append((msg, ok))
        km._send_to_app = lambda app, payload: self.banners.append(payload)
        km._update_mode = lambda: "ask"
        km._kernel_sha = lambda: "cur-sha"
        km._main_tracking = lambda: True   # these tests exercise POST-gate behavior; the gate has its own

    def tearDown(self):
        for n, f in self._saved.items():
            setattr(km, n, f)
        km._MAIN_DRIFT[0] = km._MAIN_DRIFT[1] = ""
        km._REBUILT_FOR[0] = ""
        km._INPLACE_TRIED[0] = ""

    def test_ui_only_restart_drift_rebuilds_in_place_and_latches(self):
        km._main_drift_verdict = lambda o, c, k: ("restart", "tgt-ui")
        km._kernel_code_changed = lambda a, b: False
        km._rebuild_dist = lambda: (self.rebuilds.append(1), (True, ""))[1]
        km._main_drift_check()
        self.assertEqual(len(self.rebuilds), 1)
        self.assertEqual(km._REBUILT_FOR[0], "tgt-ui", "the converge latches on the target sha")
        self.assertEqual(self.banners, [], "no restart banner for a rebuild that cuts nothing")
        self.assertTrue(any("no restart" in m for m, _ in self.notices))
        km._main_drift_check()   # same target again: already converged, no second build
        self.assertEqual(len(self.rebuilds), 1)

    def test_a_failed_build_falls_through_to_the_restart_path_loudly(self):
        km._main_drift_verdict = lambda o, c, k: ("restart", "tgt-ui")
        km._kernel_code_changed = lambda a, b: False
        km._rebuild_dist = lambda: (False, "esbuild boom")
        km._main_drift_check()
        self.assertEqual(km._REBUILT_FOR[0], "", "a failed build never latches")
        self.assertTrue(any(not ok and "esbuild boom" in m for m, ok in self.notices))
        self.assertEqual([b.get("drift") for b in self.banners], ["restart"],
                         "the normal restart offer still fires")

    def test_kernel_code_drift_keeps_the_restart_path(self):
        km._main_drift_verdict = lambda o, c, k: ("restart", "tgt-kern")
        km._kernel_code_changed = lambda a, b: True
        km._rebuild_dist = lambda: self.fail("a kernel-code drift must never rebuild in place")
        km._main_drift_check()
        self.assertEqual([b.get("drift") for b in self.banners], ["restart"])

    def test_the_classifier_reads_the_touched_paths(self):
        from unittest.mock import patch
        km._converge_classes = self._saved["_converge_classes"]   # the REAL classifier under test

        class R:
            def __init__(self, out, rc=0):
                self.stdout, self.returncode = out, rc

        def fake_run(names, show_rc=1):
            # git diff answers the NUL-separated name list; git show (the AST-equality probe)
            # answers show_rc — rc=1 means "blob unreadable", the not-provable arm that must
            # read as kernel code
            def run(argv, **kw):
                return R(names) if argv[:2] == ["git", "diff"] else R(b"", rc=show_rc)
            return run
        with patch.object(km.subprocess, "run", fake_run("ui/webview/feed.ts\0docs/a.md\0")):
            self.assertFalse(km._kernel_code_changed("a1", "b2"), "UI + docs only: rebuild in place")
        with patch.object(km.subprocess, "run", fake_run("ui/webview/feed.ts\0kernel/kernel.py\0")):
            self.assertTrue(km._kernel_code_changed("a1", "b2"),
                            "a kernel file whose blobs cannot be proven equal restarts")
        with patch.object(km.subprocess, "run", lambda argv, **kw: R("", rc=128)):
            self.assertTrue(km._kernel_code_changed("a1", "b2"), "git failure: the restart is the safe converge")
        self.assertTrue(km._kernel_code_changed("", "b2"), "unknown shas: the restart is the safe converge")

    def test_the_pull_path_carries_the_same_in_place_converge(self):
        src = inspect.getsource(km._run_main_update)
        self.assertIn("pulled = _checkout_sha()", src)
        self.assertIn("not _kernel_code_changed(_kernel_sha(), pulled) and _in_place_converge(pulled)",
                      src, "verdict input and converge target are the SAME read — never raced")
        conv = inspect.getsource(km._in_place_converge)
        self.assertIn("_rebuild_dist()", conv)
        self.assertIn("_REBUILT_FOR[0] = target", conv)


class ChannelGate(unittest.TestCase):
    """The audience gate (the user 2026-08-31, two independent "constant update notices" reports):
    dev commits must never notify a plain install — one notice per release TAG is their whole
    channel, owned by _update_check. The maintainer's mesh keeps the drift watcher through its own
    signals; everything else (bootstrap installs detached at a tag, and the installs an old banner
    walked onto a detached main sha) is the release channel and stays silent here."""

    def test_the_pure_verdict_truth_table(self):
        V = km._main_channel_verdict
        self.assertTrue(V("main", "ask", False), "a deliberate branch-main clone tracks main")
        self.assertTrue(V("", "auto", False), "auto mode = the unattended-converge machines")
        self.assertTrue(V("", "ask", True), "attached remotes = the federated mesh")
        self.assertFalse(V("", "ask", False),
                         "detached + ask + no remotes = a plain install: the bootstrap tag "
                         "checkout AND the old banner's walked-onto-main victims both land here")
        self.assertFalse(V("some-branch", "ask", False), "a feature-branch checkout is not main-tracking")

    def test_the_check_bails_for_a_plain_install_before_any_git_io(self):
        saved = (km._main_tracking, km._main_drift_verdict, km._send_to_app, km._update_mode)
        calls, banners = [], []
        try:
            km._update_mode = lambda: "ask"
            km._main_tracking = lambda: False
            km._main_drift_verdict = lambda *a: calls.append(a) or ("pull", "deadbeef")
            km._send_to_app = lambda app, payload: banners.append(payload)
            km._main_drift_check()
        finally:
            (km._main_tracking, km._main_drift_verdict, km._send_to_app, km._update_mode) = saved
        self.assertEqual(calls, [], "gated out BEFORE the verdict — no ls-remote, no banner")
        self.assertEqual(banners, [])

    def test_the_live_reader_consults_branch_mode_and_both_remote_stores(self):
        src = inspect.getsource(km._main_tracking)
        self.assertIn("bool(_remotes)", src, "live attached rows count (the Mac's dial-in included)")
        self.assertIn("KNOWN_FILE", src, "remembered hosts count — the mesh signal survives a detach")
        self.assertIn("_main_channel_verdict(_checkout_branch(), _update_mode(), attached)", src)


class PersistentDismissal(unittest.TestCase):
    """Not-now outlives the page and the kernel (the user 2026-08-31): a dismissed sha/tag stays
    dismissed until a NEW one — the per-page-load re-derive and the per-restart re-offer were the
    notice-spam compounders on the dev mesh too."""

    def setUp(self):
        try:
            (km.jd.STATE / km._DISMISSED_UPDATES_FILE_NAME).unlink()
        except OSError:
            pass

    tearDown = setUp

    def test_round_trip_and_restart_survival(self):
        km._dismiss_update("aaaa1111")
        km._dismiss_update("v0.14.0")
        self.assertEqual(km._dismissed_updates(), ["aaaa1111", "v0.14.0"],
                         "the store is a FILE — module state resets (a restart) cannot re-offer")
        km._dismiss_update("aaaa1111")
        self.assertEqual(km._dismissed_updates(), ["v0.14.0", "aaaa1111"], "re-dismissal dedupes")

    def test_a_dismissed_drift_sha_never_banners_but_a_new_one_does(self):
        saved = {n: getattr(km, n) for n in
                 ("_main_tracking", "_main_drift_verdict", "_send_to_app", "_update_mode",
                  "_kernel_sha", "_kernel_code_changed")}
        banners = []
        try:
            km._update_mode = lambda: "ask"
            km._main_tracking = lambda: True
            km._kernel_sha = lambda: "cur"
            km._kernel_code_changed = lambda a, b: True
            km._send_to_app = lambda app, payload: banners.append(payload)
            km._MAIN_DRIFT[0] = km._MAIN_DRIFT[1] = ""
            km._dismiss_update("deadbee1")
            km._main_drift_verdict = lambda *a: ("pull", "deadbee1")
            km._main_drift_check()
            self.assertEqual(banners, [], "the dismissed sha stays quiet across restarts")
            km._MAIN_DRIFT[0] = km._MAIN_DRIFT[1] = ""
            km._main_drift_verdict = lambda *a: ("pull", "feedf00d")
            km._main_drift_check()
            self.assertEqual([b.get("tag") for b in banners], ["feedf00d"],
                             "a NEW sha is new information and offers")
        finally:
            for n, f in saved.items():
                setattr(km, n, f)
            km._MAIN_DRIFT[0] = km._MAIN_DRIFT[1] = ""

    def test_the_banner_posts_the_dismissal_and_the_route_stores_it(self):
        src = inspect.getsource(km)
        self.assertIn("fetch('/update-dismiss'", src, "Not-now persists server-side, not just page-local")
        self.assertIn('u.path == "/update-dismiss"', src)
        self.assertIn("_dismiss_update((b or {}).get(\"tag\"))", src)

    def test_update_check_route_blanks_dismissed_offers(self):
        src = inspect.getsource(km)
        self.assertIn('"tag": ("" if _UPDATE_AVAIL[0] in dis else _UPDATE_AVAIL[0])', src,
                      "a page load can no longer re-derive a dismissed offer")


class PlainInstallCopy(unittest.TestCase):
    def test_the_drift_copy_drops_mesh_operator_language(self):
        src = inspect.getsource(km)
        self.assertNotIn("restarts every kernel", src)
        self.assertIn("Update pulls them and restarts romp.", src)
        self.assertIn("Update restarts romp onto it.", src)
