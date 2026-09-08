#!/usr/bin/env python3
"""The self-host safety net: neither the bus nor the kernel may ever declare a machine name that
fails _safe_id. Peers key the mail they hold FOR this machine by that name, as a path component —
so a kern.hostname stomped with junk (control bytes, 2026-08-11) used to HALF-break peering:
presence still crossed (PEER_STATE is a dict), but outbox_put on every peer refused the name, so
each reply parked "unreachable" forever with only a server-log line as trace — and _unique() baked
the junk into message ids, killing outbound the same way. self_host (bus) and _self_host (kernel)
now validate and fall back loudly: the platform's user-set machine name, else a minted id persisted
at the state root's self-host file, SHARED between the two daemons so the machine can never appear
under two names. peer_exchange_handle refuses an unkeyable declared name (guarding against
un-updated dialers) — but only AFTER _canon_peer_name, so the checked-in-alias fold keeps
self-healing.

The override tests (2026-09-08): the kernel's ROMP_HOST_NAME override and the bus's ROMP_POSTAL_HOST
override were each the one branch that dodged the rule — returned exactly as set, directly under the
docstring saying the name MUST clear _safe_id — so a mobile whose operator set one to an unusable name
declared that name to every hub (which now refuses it at its check-in door, checkin_apply) while its
own mail parked unreachable. An unusable override is now set aside aloud, once per process, and the
derived name is used — on both daemons (KernelSelfHost and BusSelfHost).

SafeIdTwins (review find, 2026-09-08): the rule itself is duplicated in the two daemons, and its regex
ended in `$`, which in Python also matches before ONE trailing newline, so "TESTHOST\n" cleared it, and
the override branches on both daemons returned that name verbatim while every hub stripped it, leaving
the machine believing in a name no peer keyed. Both copies now fullmatch, both must stay the same
function, and a trailing newline is the one whitespace shape the junk-override cases now include.

Synthetic only — invented hostnames (TESTHOST, a control-byte junk form), hermetic temp state dir,
no real machine data.
"""
import ast
import contextlib
import inspect
import io
import os
import socket as _socket
import tempfile
import textwrap
import unittest
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")

# Hermetic state dir BEFORE the loads: both daemons resolve their state root at import, and the
# minted-id file must land here — shared by the two module instances, never in real state.
# (ROMP_POSTAL_HOST / ROMP_HOST_NAME are deliberately NOT popped here: they are read at CALL time,
# other test modules set them at IMPORT time, and pytest imports every module before running any
# test — a module-level pop would erase theirs for the whole run. _HostnameSeams clears per test.)
STATE_HOME = os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
pm = SourceFileLoader("romp_postal_selfhost", os.path.join(BIN, "romp-postal-service")).load_module()
km = SourceFileLoader("romp_kernel_selfhost", os.path.join(BIN, "romp-kernel")).load_module()

JUNK = "TEST\x04HOST"          # a control byte mid-name, the 2026-08-11 shape — fails _safe_id


class _HostnameSeams(unittest.TestCase):
    """Shared seams: fake gethostname (the stdlib socket module is one object, shared by both
    loads), no platform name candidates unless a test supplies them, fallback caches reset — every
    test states its own hostname world and leaks nothing."""

    def setUp(self):
        self._env = {k: os.environ.pop(k, None) for k in ("ROMP_POSTAL_HOST", "ROMP_HOST_NAME")}
        self._gethostname = _socket.gethostname
        self._pc, self._kc = pm._host_name_candidates, km._host_name_candidates
        pm._host_name_candidates = km._host_name_candidates = lambda: []
        pm._self_host_fb = km._self_host_fb = None
        getattr(km, "_host_name_env_warned", set()).clear()   # the once-per-process override warnings, re-armed
        getattr(pm, "_postal_host_env_warned", set()).clear()

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _socket.gethostname = self._gethostname
        pm._host_name_candidates, km._host_name_candidates = self._pc, self._kc
        pm._self_host_fb = km._self_host_fb = None
        getattr(km, "_host_name_env_warned", set()).clear()
        getattr(pm, "_postal_host_env_warned", set()).clear()


class BusSelfHost(_HostnameSeams):
    def test_safe_hostname_passes_through_live(self):
        _socket.gethostname = lambda: "TESTHOST.local"
        self.assertEqual(pm.self_host(), "TESTHOST")
        _socket.gethostname = lambda: "TESTHOST2"
        self.assertEqual(pm.self_host(), "TESTHOST2", "a hostname fix lands with no restart")
        self.assertIsNone(pm._self_host_fb, "no fallback engages for a healthy name")

    def test_junk_falls_back_to_the_platform_machine_name(self):
        _socket.gethostname = lambda: JUNK
        pm._host_name_candidates = lambda: ["Test Person's Laptop!!"]
        self.assertEqual(pm.self_host(), "Test-Person-s-Laptop", "sanitized, never raw")
        self.assertTrue(pm._safe_id(pm.self_host()))

    def test_junk_mints_a_stable_persisted_id(self):
        _socket.gethostname = lambda: JUNK
        a = pm.self_host()
        self.assertTrue(pm._safe_id(a))
        self.assertEqual(a, pm.self_host(), "cached within the process")
        # A fresh load of the same bin (= a restarted bus) must resolve the SAME identity: peers
        # key our mailbox by this name, so a per-process id would strand mail on every restart.
        # Pin XDG to THIS module's state dir for the load — a later-imported test module may have
        # re-pointed the env at its own tempdir during collection (imports all run before tests).
        saved = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = STATE_HOME
        try:
            pm2 = SourceFileLoader("romp_postal_selfhost_reload",
                                   os.path.join(BIN, "romp-postal-service")).load_module()
        finally:
            os.environ["XDG_STATE_HOME"] = saved
        pm2._host_name_candidates = lambda: []
        pm2._self_host_fb = None
        self.assertEqual(pm2.self_host(), a, "the minted id is persisted, not per-process")

    def test_unique_mid_stays_path_safe(self):
        # Mids are path components at outbox_put on BOTH ends, so a junk hostname baked into them
        # killed outbound cross-host mail the same way the declared name killed inbound.
        _socket.gethostname = lambda: JUNK
        mid = pm._unique()
        self.assertTrue(pm._safe_id(mid), "the mid must survive the outbox path check")
        pm.outbox_put("TESTHOST", {"mid": mid, "body": "hi"})
        self.assertEqual((pm.outbox_get("TESTHOST", mid) or {}).get("body"), "hi")
        self.assertTrue(pm.outbox_del("TESTHOST", mid))

    def test_a_valid_override_of_any_real_shape_is_returned_verbatim(self):
        for name in ("TESTHOST", "build-box-01.example.com", "my_box", "host-1a2b3c4d"):
            os.environ["ROMP_POSTAL_HOST"] = name
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(pm.self_host(), name)
            self.assertEqual(err.getvalue(), "", "a usable override is taken quietly")

    def test_a_junk_override_is_set_aside_aloud_once_and_the_derived_name_is_used(self):
        # the bus's twin of the kernel gap: ROMP_POSTAL_HOST came back exactly as set, so a bus whose
        # operator set it to an unusable name declared that name in every peer exchange (2026-09-08)
        _socket.gethostname = lambda: "TESTHOST"
        for junk in ("my box", "user@host", "a" * 129, "TESTHOST2\n"):   # the trailing newline: review find, 2026-09-08
            os.environ["ROMP_POSTAL_HOST"] = junk
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                first, second = pm.self_host(), pm.self_host()
            self.assertEqual((first, second), ("TESTHOST", "TESTHOST"), repr(junk[:20]))
            self.assertTrue(pm._safe_id(first))
            lines = [l for l in err.getvalue().splitlines() if "ROMP_POSTAL_HOST" in l]
            self.assertEqual(len(lines), 1, "said once per process, not per call: %r" % err.getvalue())
            self.assertTrue(lines[0].startswith("[postal] self_host: "), "the bus's own log prefix")
            self.assertIn("not usable as a machine name", lines[0])
            self.assertIn("letters, digits, dots, hyphens or underscores", lines[0], "says what a name may look like")
            self.assertIn("declaring 'TESTHOST' to peers instead", lines[0], "names the name used instead")
            self.assertIn(repr(junk[:20])[:-1], lines[0], "and the name set aside (a long one is cut short)")

    def test_a_junk_override_with_a_junk_hostname_still_converges_with_the_kernel(self):
        os.environ["ROMP_POSTAL_HOST"] = "my box"
        _socket.gethostname = lambda: JUNK
        with contextlib.redirect_stderr(io.StringIO()):
            b = pm.self_host()
        self.assertTrue(pm._safe_id(b))
        self.assertNotIn(" ", b)
        self.assertEqual(b, km._self_host(), "bus and kernel still share the persisted identity")


class ExchangeUnkeyableHostGate(_HostnameSeams):
    """peer_exchange_handle refuses a declared name that fails _safe_id — an un-updated dialer
    could still declare one — but only AFTER _canon_peer_name, so the checked-in-alias fold (the
    existing self-heal for a bus we already peer with under a dialable name) keeps working."""

    def setUp(self):
        super().setUp()
        self._peers, self._pstate = dict(pm.PEERS), dict(pm.PEER_STATE)
        self._agents = pm.local_agents
        pm.local_agents = lambda: []          # presence enumeration is not under test; stay hermetic

    def tearDown(self):
        pm.local_agents = self._agents
        pm.PEERS.clear(); pm.PEERS.update(self._peers)
        pm.PEER_STATE.clear(); pm.PEER_STATE.update(self._pstate)
        super().tearDown()

    def test_unkeyable_declared_host_is_refused_400(self):
        payload, status = pm.peer_exchange_handle({"host": JUNK, "proto": pm.PEER_PROTO})
        self.assertEqual(status, 400, "refuse whole — half-working (presence without replies) is worse")
        self.assertIn("error", payload)
        self.assertNotIn(JUNK, pm.PEER_STATE, "no half-registered row for an unkeyable name")

    def test_canon_fold_to_checked_in_alias_still_accepted(self):
        pm.PEERS["safealias"] = {"port": 1}                       # dialable: the kernel notified this alias
        pm.PEER_STATE["safealias"] = {"busId": "bus-11111111"}    # same bus, seen before under the alias
        payload, status = pm.peer_exchange_handle(
            {"host": JUNK, "busId": "bus-11111111", "proto": pm.PEER_PROTO})
        self.assertEqual(status, 200, "the alias fold self-heals ahead of the gate")
        self.assertIn("safealias", pm.PEER_STATE)
        self.assertNotIn(JUNK, pm.PEER_STATE)


class KernelSelfHost(_HostnameSeams):
    def test_env_override_wins(self):
        os.environ["ROMP_HOST_NAME"] = "TESTHOST"
        try:
            self.assertEqual(km._self_host(), "TESTHOST")
        finally:
            os.environ.pop("ROMP_HOST_NAME", None)

    def test_safe_hostname_passes_through_live(self):
        _socket.gethostname = lambda: "TESTHOST"
        self.assertEqual(km._self_host(), "TESTHOST")
        self.assertIsNone(km._self_host_fb, "no fallback engages for a healthy name")

    def test_junk_is_never_declared_and_kernel_matches_bus(self):
        _socket.gethostname = lambda: JUNK
        k = km._self_host()
        self.assertTrue(km._safe_id(k))
        self.assertNotIn("\x04", k)
        self.assertEqual(k, pm.self_host(),
                         "kernel and bus share the persisted identity — one machine, one name")

    def test_a_valid_override_of_any_real_shape_is_returned_verbatim(self):
        # a dotted name with hyphens, an underscore, a minted-style id: what an operator might set
        for name in ("TESTHOST", "build-box-01.example.com", "my_box", "host-1a2b3c4d"):
            os.environ["ROMP_HOST_NAME"] = name
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(km._self_host(), name)
            self.assertEqual(err.getvalue(), "", "a usable override is taken quietly")

    def test_a_junk_override_is_set_aside_aloud_once_and_the_derived_name_is_used(self):
        # the one branch that dodged the rule: the override came back exactly as set, so a mobile whose
        # operator set ROMP_HOST_NAME to an unusable name declared it to every hub (2026-09-08)
        _socket.gethostname = lambda: "TESTHOST"
        for junk in ("my box", "user@host", "a" * 129, "TESTHOST2\n"):   # the trailing newline: review find, 2026-09-08
            os.environ["ROMP_HOST_NAME"] = junk
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                first, second = km._self_host(), km._self_host()
            self.assertEqual((first, second), ("TESTHOST", "TESTHOST"), repr(junk[:20]))
            self.assertTrue(km._safe_id(first))
            lines = [l for l in err.getvalue().splitlines() if "ROMP_HOST_NAME" in l]
            self.assertEqual(len(lines), 1, "said once per process, not per call: %r" % err.getvalue())
            self.assertIn("not usable as a machine name", lines[0])
            self.assertIn("letters, digits, dots, hyphens or underscores", lines[0], "says what a name may look like")
            self.assertIn("using 'TESTHOST' for peering instead", lines[0], "names the name used instead")
            self.assertIn(repr(junk[:20])[:-1], lines[0], "and the name set aside (a long one is cut short)")

    def test_a_junk_override_with_a_junk_hostname_still_converges_with_the_bus(self):
        os.environ["ROMP_HOST_NAME"] = "my box"
        _socket.gethostname = lambda: JUNK
        with contextlib.redirect_stderr(io.StringIO()):
            k = km._self_host()
        self.assertTrue(km._safe_id(k))
        self.assertNotIn(" ", k)
        self.assertEqual(k, pm.self_host(), "kernel and bus still share the persisted identity")


class SafeIdTwins(unittest.TestCase):
    """_safe_id lives in both daemons on purpose (each loads alone), so the two copies must stay ONE
    function; and a trailing newline is not a name on either (review find, 2026-09-08: `$` matched
    before it, and the override branches returned "TESTHOST\n" verbatim)."""

    @staticmethod
    def _body(fn):
        # the function minus its docstring: the two copies explain themselves differently, and may
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        f = tree.body[0]
        f.body = [n for n in f.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                                            and isinstance(n.value.value, str))]
        return ast.dump(f)

    def test_the_two_copies_are_the_same_function(self):
        self.assertEqual(km._SAFE_ID_RE.pattern, pm._SAFE_ID_RE.pattern, "one regex on both daemons")
        self.assertEqual(self._body(km._safe_id), self._body(pm._safe_id), "one rule on both daemons")

    def test_a_trailing_newline_is_not_a_name_on_either_daemon(self):
        for s in ("TESTHOST\n", "abc\n", "a\n", "TESTHOST\r\n", "TESTHOST\n\n"):
            self.assertFalse(km._safe_id(s), repr(s))
            self.assertFalse(pm._safe_id(s), repr(s))
        for s in ("TESTHOST", "a", "A.B-c_2", "11111111-2222-3333-4444-555555555555", "a" * 128):
            self.assertTrue(km._safe_id(s), repr(s))
            self.assertTrue(pm._safe_id(s), repr(s))

    def test_an_override_with_a_trailing_newline_is_set_aside_on_both_daemons(self):
        # the ONE whitespace shape the rule admitted: returned verbatim by both override branches, then
        # stripped by every hub, so the machine's own name and the name peers keyed it by differed by a
        # newline, and the bus baked it into every message id
        saved = {k: os.environ.pop(k, None) for k in ("ROMP_POSTAL_HOST", "ROMP_HOST_NAME")}
        seams = (_socket.gethostname, pm._host_name_candidates, km._host_name_candidates,
                 pm._self_host_fb, km._self_host_fb)
        _socket.gethostname = lambda: "TESTHOST"
        pm._host_name_candidates = km._host_name_candidates = lambda: []
        pm._self_host_fb = km._self_host_fb = None
        getattr(km, "_host_name_env_warned", set()).clear()
        getattr(pm, "_postal_host_env_warned", set()).clear()
        try:
            os.environ["ROMP_HOST_NAME"] = os.environ["ROMP_POSTAL_HOST"] = "TESTHOST2\n"
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                k, b, mid = km._self_host(), pm.self_host(), pm._unique()
            self.assertEqual((k, b), ("TESTHOST", "TESTHOST"), "the derived name, never the newline one")
            self.assertNotIn("\n", mid, "no message id carries a newline")
            self.assertTrue(pm._safe_id(mid))
            self.assertEqual(len([l for l in err.getvalue().splitlines() if "ROMP_HOST_NAME" in l]), 1)
            self.assertEqual(len([l for l in err.getvalue().splitlines() if "ROMP_POSTAL_HOST" in l]), 1)
        finally:
            for k_, v in saved.items():
                if v is None:
                    os.environ.pop(k_, None)
                else:
                    os.environ[k_] = v
            (_socket.gethostname, pm._host_name_candidates, km._host_name_candidates,
             pm._self_host_fb, km._self_host_fb) = seams
            getattr(km, "_host_name_env_warned", set()).clear()
            getattr(pm, "_postal_host_env_warned", set()).clear()


if __name__ == "__main__":
    unittest.main(verbosity=2)
