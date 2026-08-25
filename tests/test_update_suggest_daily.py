#!/usr/bin/env python3
"""Ask-mode update banners fire at most once per day (the user 2026-08-25): main takes merges in
bursts, and every kernel restart resets the in-memory discovered/offered latches, so the banner
re-offered an update several times a day. The stamp persists under STATE (update-suggested.json)
so a restart cannot re-nag; a held offer leaves its latch clear, so the first pass past the window
offers the NEWEST sha/release; auto mode never consults the stamp (its restart rate is the converge
cool-down's job). Synthetic only; hermetic state dir."""
import json
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
km = SourceFileLoader("romp_kernel_suggest", os.path.join(BIN, "romp-kernel")).load_module()


class AskBannerDaily(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.saved = (km._update_mode, km._origin_main_sha, km._checkout_sha, km._kernel_sha,
                      km._send_to_app, km._MAIN_DRIFT[0], km._MAIN_DRIFT[1], km._UPDATE_AVAIL[0])
        km._update_mode = lambda: "ask"
        km._checkout_sha = lambda: "aaa"
        km._kernel_sha = lambda: "aaa"
        km._send_to_app = lambda app, msg: self.sent.append(msg)
        km._MAIN_DRIFT[0] = km._MAIN_DRIFT[1] = ""
        km._UPDATE_AVAIL[0] = ""
        self.stamp = km.jd.STATE / "update-suggested.json"
        if self.stamp.exists():
            self.stamp.unlink()

    def tearDown(self):
        (km._update_mode, km._origin_main_sha, km._checkout_sha, km._kernel_sha,
         km._send_to_app) = self.saved[:5]
        km._MAIN_DRIFT[0], km._MAIN_DRIFT[1] = self.saved[5], self.saved[6]
        km._UPDATE_AVAIL[0] = self.saved[7]

    def test_a_second_drift_inside_the_day_is_held_and_the_latest_sha_offers_past_it(self):
        km._origin_main_sha = lambda: "bbb"
        km._main_drift_check()
        self.assertEqual([m["tag"] for m in self.sent], ["bbb"], "the first drift offers at once")
        km._origin_main_sha = lambda: "ccc"          # a new merge lands inside the window
        km._main_drift_check()
        self.assertEqual(len(self.sent), 1, "inside the day, no second banner")
        self.assertEqual(km._MAIN_DRIFT[0], "", "the held sha is NOT marked offered")
        self.stamp.write_text(json.dumps({"t": 0}))  # the day passes
        km._main_drift_check()
        self.assertEqual([m["tag"] for m in self.sent], ["bbb", "ccc"],
                         "past the window, one banner offers the LATEST sha")

    def test_a_kernel_restart_does_not_reset_the_day(self):
        km._origin_main_sha = lambda: "bbb"
        km._main_drift_check()
        km._MAIN_DRIFT[0] = km._MAIN_DRIFT[1] = ""   # what a restart does to the in-memory latches
        km._main_drift_check()
        self.assertEqual(len(self.sent), 1, "the persisted stamp holds across restarts")

    def test_the_release_banner_shares_the_daily_stamp(self):
        saved = (km._latest_release_tag, km._kernel_ver)
        km._kernel_ver = lambda: "v0.1.0"
        km._latest_release_tag = lambda: "v0.2.0"
        try:
            km._origin_main_sha = lambda: "bbb"
            km._main_drift_check()                   # today's one suggestion
            km._update_check()
            self.assertEqual(len(self.sent), 1, "the release banner waits out the same day")
            self.assertEqual(km._UPDATE_AVAIL[0], "", "a held release is not latched as acted on")
            self.stamp.write_text(json.dumps({"t": 0}))
            km._update_check()
            self.assertEqual(self.sent[-1]["tag"], "v0.2.0",
                             "past the window, the release offers and latches")
            self.assertEqual(km._UPDATE_AVAIL[0], "v0.2.0")
        finally:
            km._latest_release_tag, km._kernel_ver = saved

    def test_auto_mode_never_waits_on_the_stamp(self):
        ran = []
        saved = (km._run_main_update, km._LAST_AUTO_CONVERGE[0])
        km._update_mode = lambda: "auto"
        km._run_main_update = lambda kind, immediate=False: ran.append(kind)
        try:
            km._LAST_AUTO_CONVERGE[0] = 0.0
            km._mark_suggested()                     # a banner fired earlier today
            km._origin_main_sha = lambda: "bbb"
            km._main_drift_check()
            self.assertEqual(ran, ["pull"], "auto converges regardless — its rate is the cool-down's job")
        finally:
            km._run_main_update = saved[0]
            km._LAST_AUTO_CONVERGE[0] = saved[1]


if __name__ == "__main__":
    unittest.main()
