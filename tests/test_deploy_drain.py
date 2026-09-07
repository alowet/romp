#!/usr/bin/env python3
"""The deploy-drain hold (T121 part 1, 2026-08-27): while a quiet deploy restart is PARKED at the
manager, the kernel holds NEW turn starts so /busy falls to 0 on its own turn-end events — before
this, kernels kept starting queued turns and a busy box only ever "drained" via the manager's
backstop cut. The hold is a LEASE (refreshed by the parked poll, self-expiring when the holder
dies) and RUNTIME-ONLY (a fresh boot starts clear by construction — the manager-approved
stale-flag guard); arming is visible once per episode and a long hold escalates to the problems
ring. Mid-turn forwards keep flowing so the in-flight turn can finish; queued prompts persist —
that IS the checkpoint. Hermetic state; synthetic sids only."""
import os
import tempfile
import time
import unittest
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)
sb = SourceFileLoader("romp_sdk_backend_drainhold", os.path.join(BIN, "romp_sdk_backend.py")).load_module()


def _backend(d=None):
    return sb.SdkBackend(d or tempfile.mkdtemp(), "/bin/true", lambda *a, **k: None)


class DrainLease(unittest.TestCase):
    def test_a_fresh_backend_never_holds(self):
        # boot-clear BY CONSTRUCTION: the lease is runtime-only, so the restart it served can never
        # leave a standing flag behind — the manager-approved stale-drain guard
        self.assertFalse(_backend().drain_holding())

    def test_refresh_arms_and_expiry_releases(self):
        be = _backend()
        be.DRAIN_HOLD_TTL = 0.15
        be.refresh_drain_hold()
        self.assertTrue(be.drain_holding(), "the parked poll's refresh arms the hold")
        time.sleep(0.25)
        self.assertFalse(be.drain_holding(),
                         "the lease dies by itself when the holder stops refreshing — no off-switch to forget")

    def test_expiry_wakes_held_inputs(self):
        be = _backend()
        be.DRAIN_HOLD_TTL = 0.1
        woken = []
        be._wake_all_inputs = lambda: woken.append(1)
        be.refresh_drain_hold()
        time.sleep(0.9)   # the wake timer fires at TTL + 0.5s
        self.assertTrue(woken, "the lease-end timer nudges every input generator — a held fresh "
                               "turn starts without waiting for another event")

    def test_a_lapsed_lease_re_armed_moments_later_is_the_same_episode(self):
        # T240: the manager drops the hold during background-only stretches and re-arms it when a
        # turn starts — a flap, not a new park: the episode clock (the 5-minute ring) and the
        # "parked" line must not restart per flap
        be = _backend()
        be.DRAIN_HOLD_TTL = 0.2
        be.refresh_drain_hold()
        since0 = be._drain_hold_since
        time.sleep(0.3)                                    # lapsed
        be.refresh_drain_hold()                            # re-armed within 2×TTL of the lapse
        self.assertEqual(be._drain_hold_since, since0, "same episode")
        time.sleep(0.7)                                    # lapsed for > 2×TTL: genuinely a new park
        be.refresh_drain_hold()
        self.assertGreater(be._drain_hold_since, since0, "a new episode starts its own clock")

    def test_arming_is_visible_and_a_long_hold_rings(self):
        logs = []
        be = sb.SdkBackend(tempfile.mkdtemp(), "/bin/true", lambda *a, **k: None, log=logs.append)
        be.refresh_drain_hold()
        self.assertTrue(any("deploy restart parked" in str(l) for l in logs),
                        "arming says so once — a draining box never reads as a hung one")
        be._drain_hold_since = time.time() - be.DRAIN_LOUD_S - 1
        be.refresh_drain_hold()
        self.assertTrue(any("still parked" in str(l) for l in logs),
                        "a hold outliving the loud bound escalates rather than reading as idle sessions")

    def test_the_turn_start_gate_holds_fresh_starts_only(self):
        src = open(os.path.join(os.path.dirname(HERE), "kernel", "sdk_backend.py")).read()
        self.assertIn("blocked = blocked or (self.inflight == 0 and self.backend.drain_holding())", src,
                      "the inputs() gate holds NEW turn starts while draining; mid-turn forwards "
                      "(inflight > 0) keep flowing so the in-flight turn can finish")

    def test_the_kernel_route_and_the_deploy_paths_ride_the_gate(self):
        ksrc = open(os.path.join(os.path.dirname(HERE), "kernel", "kernel.py")).read()
        # T224 split the gate into branches so a REFUSED drain can be counted and said loudly; the
        # arm still sits under the explicit-token check and nowhere else
        self.assertIn('if q.get("drain", [""])[0] == "1":\n                        if self._write_token_ok(q):\n'
                      '                            be.refresh_drain_hold()', ksrc,
                      "/busy?drain=1 refreshes the lease in the same round-trip that reads the count — "
                      "but the arm is a WRITE, gated on an explicit token (the behavioral pins live "
                      "in tests/test_kernel_auth_hardening.py::BusyDrainWriteGate); the READ stays exempt")
        self.assertIn('json.dumps({"busy": n, "inflight": inflight, "background": background,', ksrc,
                      "the payload says when the box is draining — glanceable, never mysterious")
        self.assertIn("'http://127.0.0.1:%d/restart-all'", ksrc,
                      "the self-update deploy cuts IMMEDIATELY (T160, reversing the T121 quiet "
                      "default: parked windows cost minutes per push) — the quiet gate stays for "
                      "explicit `romp refresh --quiet`")
        self.assertNotIn("/restart-all?when=quiet'", ksrc,
                         "no kernel-side deploy path defaults to the quiet window any more")
        msrc = open(os.path.join(BIN, "romp-manager")).read()
        self.assertIn("fetchBusy(KERNEL_PORT, cb, holdTurns ? '/busy?drain=1' : '/busy')", msrc,
                      "the manager's PARKED poll is the lease's refresher")


if __name__ == "__main__":
    unittest.main()
