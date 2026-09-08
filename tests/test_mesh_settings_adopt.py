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
which is exactly what the seam sees: a peer is its /version dict, nothing more. Synthetic host names, no
sockets, no live state.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
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

    def test_the_same_value_under_a_newer_stamp_writes_nothing(self):
        self.a.set("compact-suggest", True, 2_000)
        self.b.set("compact-suggest", True, 5_000)
        self.assertEqual(self.a.adopt("TESTHOST", self.b.version())[0], [], "the values agree: nothing to converge")
        self.assertEqual(self.a.read("compact-suggest"), (True, 2_000))

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
