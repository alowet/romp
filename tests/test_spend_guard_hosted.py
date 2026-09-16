#!/usr/bin/env python3
"""plans/spend-guard-events.md, the read's carry-in: the guard keys "can spend" on the live row's working state and on the
backend's live subagent and background-task sets, so a host-attached session (per-session hosts are on by default) must
fill those sets the same way a direct SDK session does. The sets are fed by the SubagentStart/SubagentStop hooks and the
task lifecycle stream: the hooks ride the session's options, built by one function for both roads (pinned here, executed
with the hosts setting on and off), and the host relays hook callbacks as control requests (tests/test_session_host.py
pins the park and the neutral answers for every hook the kernel registers). Hermetic: a backend on a temp state dir, no
CLI, no SDK dependency."""
import os
import sys
import tempfile
import types
import unittest
from unittest import mock
from romp_load import load_source
HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
# Hermetic state BEFORE the load (the modules resolve their state root at import)
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)
sb = load_source("romp_sdk_backend_spend_hosted", os.path.join(BIN, "romp_sdk_backend.py"))
SID = "11111111-2222-3333-4444-00000000a351"


class HostedSessionsFillTheLiveSets(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self._fetch_before = sb._fetch_key_fast_org
        sb._fetch_key_fast_org = lambda key: None
        self._fake_sdk = "claude_agent_sdk" not in sys.modules and not sb.sdk_importable()
        if self._fake_sdk:
            fake = types.ModuleType("claude_agent_sdk")
            fake.HookMatcher = lambda **kw: types.SimpleNamespace(**kw)
            sys.modules["claude_agent_sdk"] = fake
        self.be = sb.SdkBackend(self.d, "/bin/true", lambda *a, **k: None, log=lambda *a, **k: None)

    def tearDown(self):
        sb._fetch_key_fast_org = self._fetch_before
        if self._fake_sdk:
            sys.modules.pop("claude_agent_sdk", None)

    def _hooks(self, hosts_on):
        sess = sb.SdkSession(self.be, {"sid": SID, "name": "web", "cwd": self.d, "mode": "acceptEdits"})
        with mock.patch.object(self.be, "session_hosts_on", lambda: hosts_on):
            kw = self.be._options(sess, dict)
        hooks = kw.get("hooks") or {}
        return {k: [getattr(h, "__name__", str(h)) for m in v for h in (getattr(m, "hooks", None) or [])] for k, v in hooks.items()}

    def test_the_subagent_hooks_ride_the_options_on_both_roads(self):
        on, off = self._hooks(True), self._hooks(False)
        for hooks, road in ((on, "host-attached"), (off, "direct")):
            self.assertEqual(hooks.get("SubagentStart"), ["_subagent_start_hook"], "%s: the live subagent set's start" % road)
            self.assertEqual(hooks.get("SubagentStop"), ["_subagent_stop_hook"], "%s: its stop" % road)
        self.assertEqual(sorted(on), sorted(off), "one hook set for both roads: the host relays what the direct road delivers")

    def test_the_snapshot_row_carries_both_sets_for_every_session(self):
        import inspect
        src = inspect.getsource(sb.SdkSession.snapshot)
        self.assertIn('"subagents": subs', src, "the live row's subagents come from the backend snapshot")
        self.assertIn('"bgTasks": self._live_bg_tasks()', src, "and its background tasks")
        self.assertNotIn("session_hosts_on", src, "the row's shape does not branch on the road")


if __name__ == "__main__":
    unittest.main()
