#!/usr/bin/env python3
"""T276 (the user 2026-09-08, from the devbox CPU hunt): when a kernel restart cuts a session's turn, that
turn's Bash-tool processes must die with it. The boot reaper used to SIGTERM the orphaned CLI pid alone, so
a tool shell's setsid children (a stress harness's 32 busy loops, a benchmark's 11) survived, re-parented
to the user manager once their shells died, and burned cores for over an hour.

Now the reaper ends the WHOLE tree before the resumed CLI launches:
  * the session's transient scope unit when the CLI runs in one (bin/romp-cli-scope's
    `romp-session-<sid8>-<pid>-<t>.scope`): systemd ends every process in the cgroup, setsid children and
    re-parented leftovers included — read from the CLI's own /proc/<pid>/cgroup;
  * always, the process tree the `ps` listing still shows under the CLI: each descendant's process group
    where it leads one (a setsid child), else the process; children before the CLI, SIGTERM then SIGKILL;
  * a sweep of OUR sessions' scopes whose CLI is not a live child of this kernel — a scope outlives its
    CLI when the tool's children keep running, which is exactly the loops the pid-only reap left behind.
Nothing outside the CLI's scope or tree is ever signaled: the walk is by ppid from the CLI, this kernel's
own group is never a target, and the scope sweep is filtered to our sids and skips this kernel's live
children.

Deterministic where it can be (pure helpers; scripted `run`/`kill`/`cgroup` seams), plus REAL processes on
Linux: a fake "CLI" whose child spawns a setsid'd sleep loop, and a bystander sleep outside the tree. The
loops here sleep — no synthetic load — and every process this file starts is killed by it. Synthetic
fixtures only.
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()   # hermetic BEFORE the load
os.environ.pop("ROMP_STATE_DIR", None)
os.environ["ROMP_CLI_SCOPE"] = "0"
sb = SourceFileLoader("romp_sdk_backend_treekill", os.path.join(BIN, "romp_sdk_backend.py")).load_module()

SID = "11111111-aaaa-0000-0000-00000000c276"
OTHER = "22222222-bbbb-0000-0000-00000000c276"
LINUX = sys.platform.startswith("linux") and shutil.which("ps") is not None and os.path.isdir("/proc")


def _backend(d=None):
    return sb.SdkBackend(d or tempfile.mkdtemp(), "/bin/true", lambda *a, **k: None)


def _reg(d, sid, **extra):
    r = {"sid": sid, "name": "s-" + sid[:4], "cwd": "/tmp", "alive": True, "lastSid": sid}
    r.update(extra)
    sb.write_reg(Path(d), sid, r)
    return r


class PureRules(unittest.TestCase):
    def test_scope_unit_of_reads_the_session_scope_from_a_cgroup_listing(self):
        v2 = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/romp-session-11111111-4242-1757374800.scope\n"
        self.assertEqual(sb.scope_unit_of(v2), "romp-session-11111111-4242-1757374800.scope")
        legacy = ("12:memory:/user.slice/romp-session-11111111-4242-1757374800.scope\n"
                  "1:name=systemd:/user.slice/romp-session-11111111-4242-1757374800.scope\n")
        self.assertEqual(sb.scope_unit_of(legacy), "romp-session-11111111-4242-1757374800.scope")
        self.assertIsNone(sb.scope_unit_of("0::/user.slice/user-1000.slice/user@1000.service/romp-manager.service\n"),
                          "the service cgroup is not a session scope — a CLI there has no unit of its own to stop")
        self.assertIsNone(sb.scope_unit_of(""))

    def test_scope_pid_and_our_sessions_units(self):
        self.assertEqual(sb.scope_pid("romp-session-11111111-4242-1757374800.scope"), 4242)
        self.assertIsNone(sb.scope_pid("romp-manager.service"))
        self.assertIsNone(sb.scope_pid("romp-session-garbage.scope"))
        listing = ("romp-session-11111111-4242-1757374800.scope loaded active running /x/claude\n"
                   "romp-session-22222222-4343-1757374801.scope loaded active running /x/claude\n"
                   "romp-session-11111111-4444-1757374802.scope loaded inactive dead /x/claude\n"
                   "run-r9b2.scope loaded active running something else\n")
        self.assertEqual(sb.session_scope_units(listing.splitlines(), [SID]),
                         ["romp-session-11111111-4242-1757374800.scope", "romp-session-11111111-4444-1757374802.scope"],
                         "our sid's units only, in listing order — another session's scope is never ours to stop")
        self.assertEqual(sb.session_scope_units(listing.splitlines(), [OTHER]), ["romp-session-22222222-4343-1757374801.scope"])
        self.assertEqual(sb.session_scope_units(listing.splitlines(), []), [])

    def test_descendants_walk_the_ppid_chain_and_nothing_else(self):
        ps = ("  100 1 /usr/lib/systemd/systemd --user\n"
              "  200 100 /x/claude --input-format stream-json --resume %s\n"
              "  201 200 bash -c tool\n"
              "  202 201 bash -c 'while :; do sleep 1; done' loop\n"     # setsid'd: still a child by ppid
              "  300 100 sleep 300\n"                                      # a bystander under the same manager
              "  400 1 python3 unrelated\n") % SID
        self.assertEqual(sorted(sb.descendants(ps.splitlines(), 200)), [201, 202])
        self.assertEqual(sb.descendants(ps.splitlines(), 300), [])
        self.assertEqual(sb.descendants(ps.splitlines(), 999), [], "an unknown root has no tree")
        # a leftover whose shell died has re-parented (ppid 100) and is NOT in the CLI's tree — the scope covers it
        ps2 = ps + "  203 100 bash -c 'while :; do sleep 1; done' orphaned-loop\n"
        self.assertNotIn(203, sb.descendants(ps2.splitlines(), 200))


class ScopePath(unittest.TestCase):
    def test_a_cli_in_a_session_scope_has_its_unit_stopped_and_only_its_own_pid_signaled(self):
        be = _backend()
        runs, killed = [], []
        def run(argv, **kw):
            runs.append(list(argv)); return mock.Mock(stdout="", returncode=0)
        cg = lambda pid: "0::/user.slice/user-1000.slice/user@1000.service/app.slice/romp-session-11111111-4242-1757374800.scope\n"
        ps = ("  4242 901 /x/claude --input-format stream-json --resume %s\n"
              "  4300 901 sleep 300\n") % SID
        out = be._end_cli_tree(4242, ps.splitlines(), kill=lambda p, s: killed.append((p, s)), run=run, cgroup=cg)
        self.assertEqual(runs, [["systemctl", "--user", "stop", "romp-session-11111111-4242-1757374800.scope"]],
                         "the scope is stopped — systemd ends the cgroup, re-parented leftovers included")
        self.assertEqual(killed, [(4242, signal.SIGTERM)], "the tree walk still signals the CLI (belt and braces), nothing else")
        self.assertEqual(out["scope"], "romp-session-11111111-4242-1757374800.scope")
        self.assertEqual(out["tree"], 0)

    def test_a_cli_with_no_scope_falls_back_to_the_tree_children_first(self):
        be = _backend()
        runs, killed = [], []
        ps = ("  4242 901 /x/claude --input-format stream-json --resume %s\n"
              "  4250 4242 bash -c tool\n"
              "  4260 4250 sleep 300\n"
              "  4300 901 sleep 300\n") % SID
        out = be._end_cli_tree(4242, ps.splitlines(), kill=lambda p, s: killed.append((p, s)),
                               run=lambda *a, **k: runs.append(a), cgroup=lambda pid: "0::/user.slice/user-1000.slice/user@1000.service/romp-manager.service\n")
        self.assertEqual(runs, [], "no scope → no systemctl")
        self.assertEqual([p for p, _ in killed], [4250, 4260, 4242], "descendants (parents first) then the CLI; the bystander 4300 untouched")
        self.assertTrue(all(s == signal.SIGTERM for _, s in killed), "fake pids are gone at once, so no SIGKILL escalation")
        self.assertIsNone(out["scope"])
        self.assertEqual(out["tree"], 2)

    def test_the_leftover_scope_sweep_stops_our_dead_sessions_scopes_only(self):
        be = _backend()
        # a real child of THIS process stands in for "this kernel's live session": its unit is skipped
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(child.wait, timeout=10); self.addCleanup(child.kill)
        listing = ("romp-session-11111111-424242-1757374800.scope loaded active running claude\n"     # our sid, CLI gone → stop
                   "romp-session-11111111-%d-1757374801.scope loaded active running claude\n"           # our sid, our live child → keep
                   "romp-session-22222222-424243-1757374802.scope loaded active running claude\n"      # another session → never ours
                   ) % child.pid
        runs = []
        def run(argv, **kw):
            runs.append(list(argv)); return mock.Mock(stdout=listing if argv == sb.SCOPE_LIST_ARGV else "", returncode=0)
        n = be._stop_leftover_scopes([SID], run=run)
        self.assertEqual(n, 1)
        self.assertEqual(runs, [sb.SCOPE_LIST_ARGV, ["systemctl", "--user", "stop", "romp-session-11111111-424242-1757374800.scope"]])

    def test_no_systemctl_means_nothing_to_sweep(self):
        be = _backend()
        def run(argv, **kw): raise FileNotFoundError("systemctl")
        self.assertEqual(be._stop_leftover_scopes([SID], run=run), 0)


class BootReconcileEndsTheTree(unittest.TestCase):
    def test_the_reap_signals_the_orphans_tree_and_sweeps_scopes_after_the_ps_read(self):
        d = tempfile.mkdtemp(); be = _backend(d)
        _reg(d, SID)
        sb.append_state(Path(d), SID, "working")
        ps = ("  555 1 /x/claude --output-format stream-json --resume %s --input-format stream-json\n"
              "  560 555 bash -c tool\n"
              "  561 560 sleep 300\n"
              "  556 1 claude --resume %s --name termsess\n"
              "  90210 1 /usr/bin/python3 /x/romp/bin/romp-kernel\n"
              "  557 90210 /x/claude --output-format stream-json --resume %s --input-format stream-json\n") % (SID, SID, SID)
        listing = "romp-session-11111111-555-1757374800.scope loaded active running claude\n"
        killed, runs = [], []
        def run(argv, **kw):
            runs.append(list(argv)); return mock.Mock(stdout=ps if argv == sb.PS_ARGV else (listing if argv == sb.SCOPE_LIST_ARGV else ""), returncode=0)
        with mock.patch.object(sb.subprocess, "run", side_effect=run), \
             mock.patch.object(sb.os, "kill", side_effect=lambda p, s: killed.append((p, s))):
            be._boot_reconcile([sb.read_reg(Path(d), SID)])
        self.assertEqual([p for p, _ in killed], [560, 561, 555], "the orphan's tree, children first, then the CLI; the tmux CLI and the live CLI untouched")
        self.assertEqual(runs[0], sb.PS_ARGV, "the listing is read first, with PS_ARGV")
        self.assertIn(sb.SCOPE_LIST_ARGV, runs, "…then our sessions' scopes are listed")
        self.assertIn(["systemctl", "--user", "stop", "romp-session-11111111-555-1757374800.scope"], runs,
                      "the dead CLI's scope is stopped: its children live on in the cgroup even after the CLI is gone")


@unittest.skipUnless(LINUX, "real processes on Linux with procfs")
class RealProcessTree(unittest.TestCase):
    """The fixture the dispatch asked for: a 'session' (a fake CLI shell) whose child spawns a DETACHED sleep loop;
    after the simulated cut — the reaper ending the orphaned CLI's tree — the loop is gone, and a bystander outside
    the tree is untouched. No scope here (ROMP_CLI_SCOPE=0), so this is the process-group fallback."""

    def _tree(self):
        marker = "romp-t276-loop-" + uuid.uuid4().hex
        # the "CLI": a shell that starts a setsid'd loop (its own session + process group, like a tool's nohup child)
        # and then sits like a CLI mid-turn; the loop sleeps — no load
        cli = subprocess.Popen(["bash", "-c", 'setsid bash -c "while :; do sleep 0.2; done" "$0" & wait', marker],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.addCleanup(self._kill_marker, marker)
        self.addCleanup(lambda: (cli.poll() is None) and os.killpg(cli.pid, signal.SIGKILL))
        # a bystander outside the tree
        by = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(by.wait, timeout=10); self.addCleanup(by.kill)
        deadline = time.time() + 5
        while time.time() < deadline and not self._marker_pids(marker):
            time.sleep(0.05)
        self.assertTrue(self._marker_pids(marker), "the detached loop is running before the cut")
        return cli, by, marker

    @staticmethod
    def _marker_pids(marker):
        out = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True).stdout.split()
        return [int(x) for x in out if x.isdigit() and int(x) != os.getpid()]

    def _kill_marker(self, marker):
        for p in self._marker_pids(marker):
            try: os.kill(p, signal.SIGKILL)
            except ProcessLookupError: pass

    def test_ending_the_cut_clis_tree_kills_the_detached_loop_and_spares_the_bystander(self):
        cli, by, marker = self._tree()
        be = _backend()
        ps = subprocess.run(sb.PS_ARGV, capture_output=True, text=True, timeout=10).stdout.splitlines()
        loop_pids = [p for p in self._marker_pids(marker) if p != cli.pid]   # the fake CLI's own argv carries the marker too
        self.assertTrue(loop_pids and all(p in sb.descendants(ps, cli.pid) for p in loop_pids),
                        "the setsid'd loop is still the CLI's descendant by ppid: %r vs %r" % (loop_pids, sb.descendants(ps, cli.pid)))
        out = be._end_cli_tree(cli.pid, ps)
        deadline = time.time() + 5
        while time.time() < deadline and (self._marker_pids(marker) or cli.poll() is None):
            time.sleep(0.05)
        self.assertEqual(self._marker_pids(marker), [], "the detached loop died with the cut turn")
        self.assertIsNotNone(cli.poll(), "the CLI is gone")
        self.assertIsNone(by.poll(), "the bystander outside the tree was never signaled")
        self.assertGreaterEqual(out["tree"], 1)


if __name__ == "__main__":
    unittest.main()
