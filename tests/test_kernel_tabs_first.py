"""TABS-FIRST (the user 2026-06-26): the tabOrder push carries name+color per tab so the client can paint the
WHOLE strip as placeholders up front (no one-by-one pop-in). Both emit sites — the periodic/connect _push and
the WS 'ready' handler — send a `tabs` list of {id, name, color} alongside the sid `order`.
"""
import inspect
import os
import unittest
from importlib.machinery import SourceFileLoader
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
KPATH = os.path.join(BIN, "romp-kernel")
# Hermetic state BEFORE the loads — they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
km = SourceFileLoader("romp_kernel", KPATH).load_module()


class TabsFirst(unittest.TestCase):
    def test_push_taborder_carries_name_and_color_per_tab(self):
        src = inspect.getsource(km._push)
        self.assertIn('tab_meta = [{"id": s["sid"], "name": s.get("name", ""), "color": _name_color(s["sid"])}', src,
                      "the periodic push builds a name+color list per tab")
        self.assertIn('_send_client(c, ("taborder",), _tab_order_frame(tab_order, tab_meta, tmux))', src,
                      "and ships it as the tabs field alongside the sid order, in the frame's one spelling")

    def test_every_tab_order_frame_names_this_kernels_own_host(self):
        # the chat reads a postal card's sender host against the viewing kernel's own name (its
        # postalSenderHost); the session frame carries the name, but only a LOCAL session's frame teaches
        # it, so a dashboard whose kernel runs no sessions of its own never learned it until the + picker
        # opened, and a remote card stamped with this kernel's name stayed plain text (review find,
        # 2026-09-06). The tabOrder frame is the one every chat receives, first of all on connect.
        sid = "11111111-2222-3333-4444-555555555555"
        frame = km._tab_order_frame([sid], [{"id": sid, "name": "web", "color": None}], [sid])
        self.assertEqual(frame["type"], "tabOrder")
        self.assertEqual(frame["selfHost"], km._self_host())
        self.assertEqual(sorted(frame), ["live", "order", "selfHost", "tabs", "type", "views"])
        # the four senders share the one spelling: the pusher's tabs-first send, the off-cycle session push,
        # the close confirmation and the WS 'ready' handler's connect-time frame — a fifth inline dict would
        # drop the field again
        text = open(KPATH).read()
        self.assertEqual(text.count('_send_client(c, ("taborder",), _tab_order_frame(tab_order, tab_meta, tmux))'), 2)
        self.assertEqual(text.count("frame = _tab_order_frame(tab_order, tab_meta, tmux)"), 1)
        self.assertEqual(text.count("_frame = _tab_order_frame(_o, _tabs, _tm)"), 1)
        self.assertEqual(text.count('{"type": "tabOrder"'), 1, "the literal lives in _tab_order_frame alone")
        self.assertIn("_tab_order_frame(tab_order, tab_meta, tmux)", inspect.getsource(km._push_session_now))
        self.assertIn("_tab_order_frame(tab_order, tab_meta, tmux)", inspect.getsource(km._confirm_close_now))

    def test_connect_ready_handler_also_sends_tabs(self):
        text = open(KPATH).read()
        self.assertIn('_frame = _tab_order_frame(_o, _tabs, _tm)', text,
                      "the WS 'ready' connect push also carries name+color tabs, in the frame's one spelling")
        self.assertIn('_tabs = [{"id": s["sid"], "name": s.get("name", ""), "color": _name_color(s["sid"])}', text)

    def test_name_color_shape_matches_the_client_color_type(self):
        # _name_color returns {bg,fg} or None — exactly the render.ts Color the placeholder applies.
        # A sid with no names entry → None (no color), which the client tolerates.
        self.assertIsNone(km._name_color("11111111-2222-3333-4444-555555555555"))


if __name__ == "__main__":
    unittest.main()
