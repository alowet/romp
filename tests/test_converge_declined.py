#!/usr/bin/env python3
"""A converge that finds this kernel already leaving asks no restart (2026-09-15): the running kernel decided a main
converge, a peer's push restarted it a second later, and the dying kernel's converge request killed its two-second-old
successor (two sigterms three seconds apart in the restart-audit ledger). Now `_run_main_update` returns before the pull
and again before the request when `_TERMINATING` is set (the exit path holds the lock), writes one `main-converge-declined`
row and counts it under memos.convergeDeclined. Hermetic: a temp git remote and checkout, a stand-in manager counting
the requests, the kernel loaded over a temp state root."""
import http.server
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from romp_load import load_source
HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
from git_fixture import init_repo, git as fixture_git, forbid_background   # noqa: E402
BIN = os.path.join(os.path.dirname(HERE), "bin")
_STATE_TD = tempfile.TemporaryDirectory()
_PREV_STATE_DIR = os.environ.get("ROMP_STATE_DIR")
os.environ["ROMP_STATE_DIR"] = _STATE_TD.name
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "test-token-DO-NOT-USE")
os.environ["ROMP_MANAGER_PORT"] = "1"
load_source("romp_event_model", os.path.join(BIN, "romp-event-model"))
jd = load_source("romp_judge", os.path.join(BIN, "romp-judge"))
km = load_source("romp_kernel_converge_declined", os.path.join(BIN, "romp-kernel"))
if _PREV_STATE_DIR is None:
    os.environ.pop("ROMP_STATE_DIR", None)
else:
    os.environ["ROMP_STATE_DIR"] = _PREV_STATE_DIR


def git(cwd, *args):
    r = fixture_git(cwd, *args, timeout=30, check=False)
    if r.returncode != 0:
        raise AssertionError("git %s failed: %s%s" % (" ".join(args), r.stdout, r.stderr))
    return r.stdout.strip()


def commit(cwd, name):
    Path(cwd, name).write_text(name + "\n")
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", "add " + name)
    return git(cwd, "rev-parse", "--short=8", "HEAD")


class _Manager(http.server.BaseHTTPRequestHandler):
    posts = []

    def do_POST(self):
        _Manager.posts.append(self.path)
        self.send_response(200); self.end_headers(); self.wfile.write(b"{}")

    def log_message(self, *a):
        pass


class ConvergeWhileLeaving(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        self.remote = root / "remote.git"
        seed = root / "seed"; seed.mkdir()
        init_repo(seed, "-q", "-b", "main")
        commit(seed, "one")
        self.remote.mkdir()
        init_repo(self.remote, "-q", "--bare", "-b", "main")
        git(seed, "push", "-q", str(self.remote), "main")
        self.checkout = root / "checkout"
        git(root, "clone", "-q", str(self.remote), str(self.checkout))
        forbid_background(self.checkout)
        other = root / "other"
        git(root, "clone", "-q", str(self.remote), str(other))
        self.target = commit(other, "two")
        git(other, "push", "-q", "origin", "main")
        self.saved_state = jd.STATE
        jd.STATE = root / "state"; jd.STATE.mkdir()
        _Manager.posts = []
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), _Manager)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.saved_term = km._TERMINATING[0]
        with km._SYNC_LOCK:
            del km._SYNC_NOTICES[:]

    def tearDown(self):
        km._TERMINATING[0] = self.saved_term
        self.srv.shutdown(); self.srv.server_close()
        jd.STATE = self.saved_state
        self.td.cleanup()

    def _converge(self):
        with mock.patch.object(km, "ROOT", self.checkout), \
             mock.patch.object(km, "_release_remote", return_value="origin"), \
             mock.patch.object(km, "_kernel_code_changed", return_value=True), \
             mock.patch.object(km, "_rebuild_dist", return_value=(True, "")):
            return km._run_main_update("pull", target=self.target, manager_port=self.srv.server_address[1])

    def _rows(self):
        p = jd.STATE / "restart-audit.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []

    def test_a_converge_on_a_kernel_that_is_leaving_asks_no_restart_and_says_so(self):
        km._TERMINATING[0] = True                          # the manager's SIGTERM landed: the exit path holds the lock
        n0 = (getattr(km, "_CONVERGE_DECLINED", None) or [0])[0]
        self._converge()
        self.assertEqual(_Manager.posts, [], "no restart asked of the manager: the successor boots on the disk as it stands")
        acts = [r.get("action") for r in self._rows()]
        self.assertEqual(acts, ["main-converge-declined"], "one declined row, no main-converge request row: %r" % acts)
        row = self._rows()[0]
        self.assertEqual((row.get("why"), row.get("phase")), ("shutting-down", "before-pull"), "declined before the pull: %r" % row)
        self.assertEqual(row.get("sha"), self.target, "the row names the target it did not pull")
        self.assertNotEqual(git(self.checkout, "rev-parse", "--short=8", "HEAD"), self.target, "and the checkout was left alone")
        self.assertEqual((getattr(km, "_CONVERGE_DECLINED", None) or [0])[0] - n0, 1, "counted for /perf")
        self.assertIn("main-converge-declined", getattr(km, "_NO_RESTART_ACTIONS", set()), "the audit walk skips the row")

    def test_the_sigterm_landing_during_the_pull_declines_the_request_too(self):
        """The 2026-09-15 shape: the decision was taken with the kernel running, the SIGTERM landed while git pulled."""
        real = km.subprocess.run
        def run(cmd, *a, **kw):
            if isinstance(cmd, (list, tuple)) and "fetch" in cmd:
                km._TERMINATING[0] = True                  # the signal lands mid-pull
            return real(cmd, *a, **kw)
        with mock.patch.object(km.subprocess, "run", side_effect=run):
            self._converge()
        self.assertEqual(_Manager.posts, [], "the request after the pull is declined")
        self.assertEqual([r.get("action") for r in self._rows()], ["main-converge-declined"])
        row = self._rows()[0]
        self.assertEqual(row.get("phase"), "after-pull", "declined after the pull: %r" % row)
        self.assertEqual(row.get("sha"), self.target, "the row names the checkout it moved")
        self.assertEqual(git(self.checkout, "rev-parse", "--short=8", "HEAD"), self.target, "the checkout moved; the successor boots on it")

    def test_a_running_kernel_still_asks_its_restart(self):
        km._TERMINATING[0] = False
        self._converge()
        self.assertEqual(_Manager.posts, ["/restart-all"], "the road that stays: one restart-all")
        self.assertEqual([r.get("action") for r in self._rows()], ["main-converge"])


if __name__ == "__main__":
    unittest.main()
