"""The chat tab's right-click menu gained the timeline lane's per-session toggles (the user 2026-06-26): mute
from the feed (hideFromFeed) and isolate from the postal service (postalServiceOff). For the menu to show the
right state + action, build_session now carries both flags (mirroring build_timeline, legacy postalOff
fallback included), and the kernel handles a chat-side setSessionFlag the same way as the timeline's."""
import inspect
import os
import unittest
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
KPATH = os.path.join(BIN, "romp-kernel")
km = SourceFileLoader("romp_kernel", KPATH).load_module()


class TabFlags(unittest.TestCase):
    def test_build_session_carries_the_feed_and_postal_flags(self):
        src = inspect.getsource(km.build_session)
        self.assertIn('"hideFromFeed": _session_flag(sid, "hideFromFeed")', src)
        self.assertIn('"postalServiceOff": _session_flag(sid, "postalServiceOff") or _session_flag(sid, "postalOff")', src,
                      "canonical postalServiceOff with the legacy postalOff fallback, like build_timeline")

    def test_kernel_handles_a_chat_side_setSessionFlag(self):
        text = open(KPATH).read()
        self.assertIn('msg.get("type") == "setSessionFlag"', text)
        self.assertIn('_flag, _val = str(msg["flag"]), bool(msg.get("value"))', text)
        self.assertIn('_set_session_flag(str(msg["id"]), _flag, _val)', text)

    def test_the_notify_bell_is_stored_inverted(self):
        # the bell is ON by default (the user 2026-08-09), and the flags file cannot hold a false — so
        # what persists is "notifyOff". Clients still send the positive `notify`; the flip lives in the
        # handler, the one place that writes it.
        text = open(KPATH).read()
        self.assertIn('_flag, _val = "notifyOff", not _val', text)

    def test_set_session_flag_round_trips(self):
        sid = "11111111-2222-3333-4444-555555555555"
        try:
            km._set_session_flag(sid, "postalServiceOff", True)
            self.assertTrue(km._session_flag(sid, "postalServiceOff"))
            km._set_session_flag(sid, "postalServiceOff", False)
            self.assertFalse(km._session_flag(sid, "postalServiceOff"))
        finally:
            km._set_session_flag(sid, "postalServiceOff", False)


if __name__ == "__main__":
    unittest.main()
