#!/usr/bin/env python3
"""Kernel-side settings converge across attached machines WITHOUT a click (T248b, the user 2026-09-08: the
Suggest /compact setting must be consistent always; a machine attached after the click keeping its own copy
until the next click, with a mixed mark to show it, does not meet that).

The seam is the tunnel supervisor's poll: it already lifts each up peer's /version "settings" dict onto the
peer's /tunnels row. It now lifts "settingsGt" beside it and hands both to _adopt_peer_settings: when a
peer's stamp for a setting is NEWER than the local store's last-applied stamp and the values differ, the
peer's value is applied through the setting's own gt-gated setter with the PEER's stamp. The poll observing
a newer stamp is the event; gesture-time ordering makes it latest-wins on both sides with no ping-pong (an
adopter's stamp equals the peer's afterwards, and an equal stamp is never adopted). Generalized to the three
boolean kernel settings that ride the browser broadcast and nothing else: compactSuggest, autoNudge and
fileEditing — the same three lines each, one table row apiece.

Two hermetic "kernels" here are two state roots served by one loaded module (jd.STATE swapped per call),
which is exactly what the seam sees: a peer is its /version dict, nothing more — and one class drives that
dict through the REAL poll (_poll_remote_version against a loopback stand-in for the peer's /version), the
gap the first cut's review caught: the poll copied four fixed keys and dropped settingsGt, so nothing ever
converged in production while the hand-built dicts here passed. A same value under a NEWER peer stamp lifts
the local stamp too (review, second finding): the dashboard mints its next gesture above the LOCAL kernel's
stamps only, so a lagging stamp let a later local click apply locally, stand down on the peer, and then be
adopted away again — the gear-says-off, kernel-holds-on state this exists to end. Synthetic host names,
loopback only, no live state.
"""
import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
km = SourceFileLoader("romp_kernel_mesh_adopt", os.path.join(BIN, "romp-kernel")).load_module()
jd = km.jd

KERNEL_SRC = open(os.path.join(BIN, "romp-kernel")).read()
SETTERS = {"compact-suggest": km._set_compact_suggest, "auto-nudge": km._set_auto_nudge, "file-editing": km._set_file_editing}
READERS = {"compact-suggest": km._compact_suggest_on, "auto-nudge": km._auto_nudge_on, "file-editing": km._file_editing_on}
KEYS = {"compact-suggest": "compactSuggest", "auto-nudge": "autoNudge", "file-editing": "fileEditing"}


class _Kernel:
    """One hermetic state root; `with k:` makes the loaded module act as that kernel."""

    def __init__(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)

    def __enter__(self):
        self._saved = jd.STATE
        jd.STATE = self.root
        km._autonudge_cache.clear()
        return self

    def __exit__(self, *a):
        km._autonudge_cache.clear()
        jd.STATE = self._saved

    def version(self):
        """What this kernel's /version says to a polling peer: the settings dict + every store's stamp."""
        with self:
            return {"settings": {KEYS[n]: READERS[n]() for n in KEYS}, "settingsGt": km._settings_gt()}

    def set(self, store, value, gt):
        with self:
            return SETTERS[store](value, gt=gt)

    def read(self, store):
        with self:
            return READERS[store](), km._setting_stored_gt(store)

    def adopt(self, host, rver):
        with self:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                out = km._adopt_peer_settings(host, rver)
            return out, err.getvalue()

    def close(self):
        self.td.cleanup()


class AdoptPeerSettings(unittest.TestCase):
    def setUp(self):
        self.a, self.b = _Kernel(), _Kernel()

    def tearDown(self):
        self.a.close(); self.b.close()

    def test_a_newer_peer_pick_is_applied_with_the_peers_stamp(self):
        self.b.set("compact-suggest", True, 2_000)
        adopted, err = self.a.adopt("TESTHOST", self.b.version())
        self.assertEqual(adopted, ["compact-suggest"])
        self.assertEqual(self.a.read("compact-suggest"), (True, 2_000), "the peer's value, under the peer's stamp")
        self.assertIn("TESTHOST", err, "the adoption is said, and names the machine it came from")

    def test_an_older_peer_pick_stands_down_and_leaves_no_stale_verdict_behind(self):
        self.a.set("compact-suggest", True, 3_000)
        self.b.set("compact-suggest", False, 2_000)
        adopted, _ = self.a.adopt("TESTHOST", self.b.version())
        self.assertEqual(adopted, [])
        self.assertEqual(self.a.read("compact-suggest"), (True, 3_000), "the newer local pick keeps")
        with self.a:
            self.assertIsNone(km._pop_stale_notice(), "no delivering socket here: a stand-down verdict must not leak to the next WS gesture")

    def test_an_equal_stamp_is_never_adopted_whatever_the_value(self):
        self.a.set("compact-suggest", True, 2_000)
        self.b.set("compact-suggest", True, 2_000)
        self.assertEqual(self.a.adopt("TESTHOST", self.b.version())[0], [], "same news again: no write")
        self.b.set("compact-suggest", False, 2_000)     # an echo: same stamp → refused by b's own setter
        self.assertEqual(self.b.read("compact-suggest"), (True, 2_000))
        # a hand-built peer dict with an equal stamp and a different value: not newer → not adopted (determinism)
        rver = {"settings": {"compactSuggest": False}, "settingsGt": {"compact-suggest": 2_000}}
        self.assertEqual(self.a.adopt("TESTHOST", rver)[0], [])
        self.assertEqual(self.a.read("compact-suggest"), (True, 2_000))

    def test_the_same_value_under_a_newer_stamp_lifts_the_local_stamp(self):
        # the value already agrees, but the STAMP is newer: adopt it, or the local dashboard — which mints its
        # next gesture above the local kernel's stamps only — clicks below the peer's stamp, applies locally,
        # stands down on the peer, and is adopted away again one pass later (review of the first cut)
        self.a.set("compact-suggest", True, 5_000)
        self.b.set("compact-suggest", True, 7_000)          # a device whose clock runs ahead clicked ON on b
        self.assertEqual(self.a.adopt("TESTHOST", self.b.version())[0], ["compact-suggest"])
        self.assertEqual(self.a.read("compact-suggest"), (True, 7_000), "same value, the peer's stamp")
        # a's dashboard now learns 7_000 from a's own /version and mints the OFF click above it: it wins everywhere
        self.a.set("compact-suggest", False, 7_001)
        self.assertEqual(self.a.read("compact-suggest"), (False, 7_001))
        self.assertEqual(self.a.adopt("TESTHOST", self.b.version())[0], [], "b's older pick teaches a nothing")
        self.assertEqual(self.b.adopt("TESTHOST2", self.a.version())[0], ["compact-suggest"])
        self.assertEqual(self.b.read("compact-suggest"), (False, 7_001), "the click held on both machines")

    def test_a_non_finite_stamp_skips_only_its_own_setting(self):
        # json can carry NaN/Infinity; int() of either raises, and an exception mid-loop would skip the peer's
        # remaining settings every pass (second review, nit)
        self.b.set("file-editing", True, 2_000)
        rver = {"settings": {"compactSuggest": True, "fileEditing": True},
                "settingsGt": {"compact-suggest": float("nan"), "file-editing": 2_000}}
        self.assertEqual(self.a.adopt("TESTHOST", rver)[0], ["file-editing"])
        rver["settingsGt"]["compact-suggest"] = float("inf")
        self.assertEqual(self.a.adopt("TESTHOST", rver)[0], [], "…and inf is not a stamp either")

    def test_an_older_kernel_or_a_junk_dict_adopts_nothing(self):
        self.a.set("compact-suggest", False, 1_000)
        for rver in (None, {}, {"settings": {"compactSuggest": True}},                       # no settingsGt: older kernel
                     {"settings": {"compactSuggest": True}, "settingsGt": {}},
                     {"settings": {"compactSuggest": "yes"}, "settingsGt": {"compact-suggest": 9_000}},   # not a bool
                     {"settings": {"compactSuggest": True}, "settingsGt": {"compact-suggest": "9000"}},   # not a stamp
                     {"settings": "x", "settingsGt": {"compact-suggest": 9_000}}):
            self.assertEqual(self.a.adopt("TESTHOST", rver)[0], [], repr(rver))
        self.assertEqual(self.a.read("compact-suggest"), (False, 1_000))

    def test_no_ping_pong_between_two_kernels(self):
        self.a.set("compact-suggest", False, 1_000)
        self.b.set("compact-suggest", True, 2_000)
        self.assertEqual(self.a.adopt("TESTHOST", self.b.version())[0], ["compact-suggest"])   # a polls b: adopts
        self.assertEqual(self.b.adopt("TESTHOST2", self.a.version())[0], [], "b polls a: equal stamps, nothing")
        self.assertEqual(self.a.adopt("TESTHOST", self.b.version())[0], [], "a polls b again: nothing")
        self.assertEqual(self.a.read("compact-suggest"), self.b.read("compact-suggest"), "one value, one stamp")

    def test_the_newest_click_wins_on_both_sides(self):
        # clicked on a at 4_000 (off) and on b at 3_000 (on) while apart; when they see each other, 4_000 wins everywhere
        self.a.set("compact-suggest", False, 4_000)
        self.b.set("compact-suggest", True, 3_000)
        self.assertEqual(self.a.adopt("TESTHOST", self.b.version())[0], [], "a holds the newer pick")
        self.assertEqual(self.b.adopt("TESTHOST2", self.a.version())[0], ["compact-suggest"])
        self.assertEqual(self.b.read("compact-suggest"), (False, 4_000))

    def test_auto_nudge_and_file_editing_converge_the_same_way(self):
        # each store's fresh-install default differs (Auto Nudge ships on, file editing off): the peer's pick
        # is the OTHER value, since a pick equal to what we hold has nothing to converge
        for store in ("auto-nudge", "file-editing"):
            default = self.a.read(store)[0]
            self.b.set(store, not default, 2_000)
            adopted, _ = self.a.adopt("TESTHOST", self.b.version())
            self.assertIn(store, adopted, store)
            self.assertEqual(self.a.read(store), (not default, 2_000), store)
            self.a.set(store, default, 3_000)
            self.assertEqual(self.b.adopt("TESTHOST2", self.a.version())[0], [store], store + ": the newer pick flows back")
            self.assertEqual(self.b.read(store), (default, 3_000), store)


class _FakePeer(BaseHTTPRequestHandler):
    """A stand-in peer kernel: /version answers with whatever PAYLOAD holds (the loopback shape
    tests/test_auto_nudge_every_kernel.py uses)."""
    PAYLOAD = {}

    def do_GET(self):
        body = json.dumps(self.PAYLOAD).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class ThroughTheRealPoll(unittest.TestCase):
    """The dict the supervisor hands to _adopt_peer_settings is _poll_remote_version's return, not the
    peer's /version JSON: the poll must carry the stamps across, or nothing ever converges."""

    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakePeer)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.a = _Kernel()

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close(); self.a.close()

    def _poll(self, payload):
        _FakePeer.PAYLOAD = payload
        return km._poll_remote_version({"local_port": self.port, "token": "tok"})

    def test_the_poll_carries_the_peers_stamps_beside_its_settings(self):
        got = self._poll({"kernel_sha": "abc1234", "settings": {"compactSuggest": True},
                          "settingsGt": {"compact-suggest": 2_000, "auto-nudge": 0}})
        self.assertEqual(got["settings"], {"compactSuggest": True})
        self.assertEqual(got["settingsGt"], {"compact-suggest": 2_000, "auto-nudge": 0})

    def test_an_older_kernel_or_junk_stamps_poll_as_none(self):
        self.assertIsNone(self._poll({"kernel_sha": "abc1234", "settings": {"compactSuggest": True}})["settingsGt"])
        self.assertIsNone(self._poll({"kernel_sha": "abc1234", "settingsGt": "2000"})["settingsGt"])

    def test_a_polled_peer_is_adopted_end_to_end(self):
        rver = self._poll({"kernel_sha": "abc1234", "settings": {"compactSuggest": True, "autoNudge": True, "fileEditing": True},
                           "settingsGt": {"compact-suggest": 2_000, "file-editing": 2_000}})
        self.assertEqual(sorted(self.a.adopt("TESTHOST", rver)[0]), ["compact-suggest", "file-editing"])
        self.assertEqual(self.a.read("compact-suggest"), (True, 2_000))
        self.assertEqual(self.a.read("file-editing"), (True, 2_000))
        self.assertEqual(self.a.read("auto-nudge")[1], 0, "no stamp for it in the peer's dict: untouched")


class TheEmitterIsOneSnapshotPerStore(unittest.TestCase):
    """The consumer takes a peer's (value, stamp) as one snapshot, so the peer's /version must read each
    store's value and stamp from ONE read: two reads with a click landing between them yield (old value,
    new stamp), which the adopter persists and the equal-stamp rule then freezes on both machines (the
    second review of this change)."""

    def setUp(self):
        self.k = _Kernel()

    def tearDown(self):
        self.k.close()

    def test_version_reports_a_value_and_stamp_from_the_same_read(self):
        # the blob reader is wrapped so that the settings sub-dict's VALUE readers see the pre-click blob while
        # the stamp reader sees the post-click one — exactly a click landing between two separate reads
        import inspect
        with self.k:
            km._set_compact_suggest(False, gt=5_000)
            old = dict(km._auto_nudge_data())
            km._set_compact_suggest(True, gt=9_000)
            new = dict(km._auto_nudge_data())
            real = km._auto_nudge_data
            def torn():
                caller = inspect.stack()[1].function
                return dict(old) if caller in ("_compact_suggest_on", "_auto_nudge_on") else dict(new)
            km._auto_nudge_data = torn
            try:
                v = km._version_info()
            finally:
                km._auto_nudge_data = real
        pair = (v["settings"]["compactSuggest"], v["settingsGt"]["compact-suggest"])
        self.assertIn(pair, [(False, 5_000), (True, 9_000)], "value and stamp come from one snapshot: %r" % (pair,))
        self.assertEqual(v["compactSuggest"], v["settings"]["compactSuggest"], "the top-level field rides the same snapshot")

    def test_version_builds_the_three_adopted_settings_from_the_snapshot_helper(self):
        src = KERNEL_SRC.split("def _version_info():")[1].split("\ndef ")[0]
        self.assertIn("_mesh_settings_snapshot()", src)
        with self.k:
            km._set_file_editing(True, gt=4_000)
            values, stamps = km._mesh_settings_snapshot()
        self.assertEqual(values["fileEditing"], True)
        self.assertEqual(stamps["file-editing"], 4_000)
        self.assertEqual(set(values), {"autoNudge", "compactSuggest", "fileEditing"})
        self.assertEqual(set(stamps), {"auto-nudge", "compact-suggest", "file-editing"})


class ThePollSeam(unittest.TestCase):
    def test_the_supervisor_lifts_the_stamps_and_adopts_outside_the_lock(self):
        sup = KERNEL_SRC.split("def _tunnel_supervisor():")[1].split("\ndef ")[0]
        self.assertIn('r["settings"] = (rver or {}).get("settings")', sup)
        self.assertIn('r["settingsGt"] = (rver or {}).get("settingsGt")', sup, "the stamps ride the row beside the values")
        self.assertIn("_adopt_peer_settings(r.get(\"host\") or \"?\", rver)", sup)
        # the setters take their own locks and write files: they run in the OUTSIDE-the-lock block, like the auto update
        before_lock_exit = sup.split("if auto_check:")[0]
        self.assertNotIn("_adopt_peer_settings(", before_lock_exit, "never under _remotes_lock")

    def test_the_table_names_exactly_the_three_broadcast_booleans(self):
        self.assertEqual([row[0] for row in km._MESH_ADOPTED_SETTINGS], ["compactSuggest", "autoNudge", "fileEditing"])
        self.assertEqual([row[1] for row in km._MESH_ADOPTED_SETTINGS], ["compact-suggest", "auto-nudge", "file-editing"])


if __name__ == "__main__":
    unittest.main()
