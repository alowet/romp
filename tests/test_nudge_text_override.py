#!/usr/bin/env python3
"""Per-session wording for the auto-nudge ask (the user 2026-08-10).

romp's follow-up ask is one shared sentence for every session. A person running several sessions in
different registers wanted one of them asked in their own words, without changing what the others get.
auto-nudge.json gains a "text" map:

    {"text": {"<session name or sid>": {"mode": "append"|"replace", "text": "..."}}}

APPEND (the default, and the shorthand a bare string takes) keeps romp's status ask and adds the line
after it. That matters beyond taste: the segment a nudge opens is goal-tagged, and the planner must
resolve that goal from the reply — done or block, never a plain step. An ask that requests no status
leaves it nothing to resolve with, and the card lands stalled. REPLACE drops the status ask and is the
user's call; this file pins that both modes reach both fire shapes, and that a malformed entry falls
back to the stock ask rather than wedging the nudge.

SYNTHETIC fixtures only (placeholder ids, invented session/goal names).
"""
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
km = SourceFileLoader("romp_kernel_nudgetext", os.path.join(BIN, "romp-kernel")).load_module()
jd = km.jd

SID = "11111111-2222-3333-4444-555555555555"
SID2 = "66666666-7777-8888-9999-000000000000"
G1, G2 = SID + ":g1", SID + ":g2"
NAME = "web"
NOW = 1781100000
T0 = NOW - 3600
MINE = "Keep it short and tell me the one thing you're stuck on."


def _node(nid, text, parent=None, **kw):
    d = {"id": nid, "text": text, "parentId": parent, "nodeComplete": False,
         "blocked": False, "cleared": False, "t": T0, "mt": T0, "log": []}
    d.update(kw)
    return d


def _store(nodes, status=None):
    return {"rompUuid": SID, "seq": len(nodes), "nodes": nodes, "placements": {},
            "status": status if status is not None else {n: "working" for n in nodes}}


class _StateBase(unittest.TestCase):
    """A temp romp state root with a names/ registry, so the NAME lookup runs for real."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        self.saved = (jd.STATE, km.NAMES)
        jd.STATE = root
        km.NAMES = root / "names"
        km.NAMES.mkdir()
        (km.NAMES / SID).write_text("%s\t/tmp/notes-api\t#1EA1EB\twhite\n" % NAME)
        km._autonudge_cache.clear()

    def tearDown(self):
        (jd.STATE, km.NAMES) = self.saved
        km._autonudge_cache.clear()
        self.td.cleanup()

    def _cfg(self, text):
        km._write_auto_nudge({"enabled": True, "nudged": {}, "text": text})
        km._autonudge_cache.clear()


class Override(_StateBase):
    """_nudge_override / _nudge_ask: what resolves, what wins, and what safely doesn't resolve."""

    def test_no_config_leaves_the_stock_ask_untouched(self):
        self.assertIsNone(km._nudge_override(SID))
        self.assertEqual(km._nudge_ask(SID, km.AUTO_NUDGE_TEXT), km.AUTO_NUDGE_TEXT)

    def test_append_by_name_keeps_the_status_ask_and_adds_the_line(self):
        self._cfg({NAME: {"mode": "append", "text": MINE}})
        out = km._nudge_ask(SID, km.AUTO_NUDGE_TEXT)
        self.assertTrue(out.startswith(km.AUTO_NUDGE_TEXT),
                        "append must not drop the ask the planner resolves the goal from")
        self.assertTrue(out.endswith("\n\n" + MINE))

    def test_replace_by_name_sends_only_the_custom_ask(self):
        self._cfg({NAME: {"mode": "replace", "text": MINE}})
        self.assertEqual(km._nudge_ask(SID, km.AUTO_NUDGE_TEXT), MINE)

    def test_a_bare_string_is_append_shorthand(self):
        self._cfg({NAME: MINE})
        self.assertEqual(km._nudge_override(SID), ("append", MINE))

    def test_the_name_key_is_case_insensitive(self):
        self._cfg({NAME.upper(): {"mode": "replace", "text": MINE}})
        self.assertEqual(km._nudge_ask(SID, km.AUTO_NUDGE_TEXT), MINE,
                         "the key should match what the tab shows, whatever its case")

    def test_a_sid_key_works_when_no_name_entry_matches(self):
        self._cfg({SID: {"mode": "replace", "text": MINE}})
        self.assertEqual(km._nudge_ask(SID, km.AUTO_NUDGE_TEXT), MINE)

    def test_the_name_entry_wins_over_a_sid_entry_for_the_same_session(self):
        self._cfg({SID: "by sid", NAME: "by name"})
        self.assertEqual(km._nudge_override(SID), ("append", "by name"))

    def test_another_session_is_unaffected(self):
        self._cfg({NAME: {"mode": "replace", "text": MINE}})
        self.assertIsNone(km._nudge_override(SID2))
        self.assertEqual(km._nudge_ask(SID2, km.AUTO_NUDGE_TEXT), km.AUTO_NUDGE_TEXT)

    def test_the_fork_ask_takes_the_override_too(self):
        self._cfg({NAME: {"mode": "append", "text": MINE}})
        out = km._nudge_ask(SID, km.AUTO_NUDGE_STALLED_TEXT)
        self.assertTrue(out.startswith(km.AUTO_NUDGE_STALLED_TEXT))
        self.assertIn(MINE, out)

    def test_malformed_entries_fall_back_to_the_stock_ask(self):
        for bad in ({NAME: {}}, {NAME: {"text": "   "}}, {NAME: {"text": ""}},
                    {NAME: None}, {NAME: 42}, {NAME: []}):
            self._cfg(bad)
            self.assertIsNone(km._nudge_override(SID), repr(bad))
            self.assertEqual(km._nudge_ask(SID, km.AUTO_NUDGE_TEXT), km.AUTO_NUDGE_TEXT, repr(bad))

    def test_a_config_that_is_not_a_map_is_ignored(self):
        for bad in ("nope", [NAME], 7, {}):
            self._cfg(bad)
            self.assertIsNone(km._nudge_override(SID), repr(bad))

    def test_an_unknown_mode_degrades_to_append_not_to_replace(self):
        self._cfg({NAME: {"mode": "clobber", "text": MINE}})
        out = km._nudge_ask(SID, km.AUTO_NUDGE_TEXT)
        self.assertEqual(km._nudge_override(SID), ("append", MINE))
        self.assertIn(km.AUTO_NUDGE_TEXT, out,
                      "a typo in the mode must not silently drop the status ask")

    def test_toggling_auto_nudge_off_and_on_preserves_the_config(self):
        # the gear checkbox rewrites auto-nudge.json; the wording must survive it
        self._cfg({NAME: {"mode": "replace", "text": MINE}})
        km._set_auto_nudge(False)
        km._set_auto_nudge(True)
        km._autonudge_cache.clear()
        self.assertEqual(km._nudge_ask(SID, km.AUTO_NUDGE_TEXT), MINE)
        self.assertIn("text", json.loads((jd.STATE / "auto-nudge.json").read_text()))


class BundleAsk(_StateBase):
    """The multi-goal bundle shares ONE ask, so it must take the same override as the single-goal fire."""

    def _nodes(self):
        return {G1: _node(G1, "Ship the auth refactor"), G2: _node(G2, "Write the migration guide")}

    def test_the_bundle_ask_is_overridden_and_the_quote_and_markers_survive(self):
        self._cfg({NAME: {"mode": "replace", "text": MINE}})
        out = km._nudge_bundle_body([G1, G2], self._nodes(), set())
        self.assertIn(MINE, out)
        self.assertNotIn("Where do these 2 stand?", out)
        self.assertIn("> 1. Ship the auth refactor", out)
        self.assertIn("<!-- romp-goal-id: %s -->" % G2, out, "the judge contract is untouched")

    def test_append_leaves_the_shared_status_ask_in_place(self):
        self._cfg({NAME: {"mode": "append", "text": MINE}})
        out = km._nudge_bundle_body([G1, G2], self._nodes(), set())
        self.assertIn("Where do these 2 stand?", out)
        self.assertIn(MINE, out)

    def test_an_unconfigured_session_gets_the_stock_bundle(self):
        out = km._nudge_bundle_body([G1, G2], self._nodes(), set())
        self.assertIn("Where do these 2 stand?", out)
        self.assertNotIn(MINE, out)


class EndToEnd(_StateBase):
    """Through _auto_nudge_session: the override reaches what is actually SENT, on both fire shapes."""

    def setUp(self):
        super().setUp()
        self._orig_km = {n: getattr(km, n) for n in (
            "_session_flag", "_compacting_now", "_api_error", "_session_working",
            "_interrupt_suppresses_nudge", "_backend_queued", "_backend_rewind_pending",
            "_last_state", "_session_awaiting", "_turn_romp_injected", "_closer_settled",
            "_revivers_pending", "_pending_ops")}
        self._orig_jd = {n: getattr(jd, n) for n in ("parsed_session", "load_goals", "_segs", "plan_units")}
        self._orig_backend = km.Sessions.backend_for
        km._session_flag = lambda sid, flag: False
        km._compacting_now = lambda sid: False
        km._api_error = lambda path: None
        km._session_working = lambda turns: False
        km._interrupt_suppresses_nudge = lambda turns: False
        km._backend_queued = lambda sid: False
        km._backend_rewind_pending = lambda sid: False
        km._last_state = lambda sid: ("", 0)
        km._session_awaiting = lambda *a: False
        km._turn_romp_injected = lambda tn: False
        km._closer_settled = lambda *a: True
        km._revivers_pending = lambda *a: None
        km._pending_ops = {}
        jd._segs = lambda tn, store: []
        jd.plan_units = lambda session, store: []
        jd.parsed_session = lambda sid, paths, now: {
            "turns": [{"id": "t1", "t": T0, "end": T0 + 10, "ended": True, "atoms": [{}, {}, {}]}]}
        self.sent = []
        test = self

        class FakeBackend:
            def send(self, sid, body):
                test.sent.append(body)
        km.Sessions.backend_for = staticmethod(lambda sid: FakeBackend())

    def tearDown(self):
        for n, v in self._orig_km.items():
            setattr(km, n, v)
        for n, v in self._orig_jd.items():
            setattr(jd, n, v)
        km.Sessions.backend_for = self._orig_backend
        super().tearDown()

    def _tick(self, nodes):
        jd.load_goals = lambda sid: _store(nodes)
        nudged = dict(km._auto_nudge_data().get("nudged", {}))
        km._auto_nudge_session({"sid": SID, "path": "/nonexistent.jsonl"}, NOW, {}, nudged, {})
        return self.sent

    def test_one_due_goal_sends_the_overridden_ask(self):
        self._cfg({NAME: {"mode": "replace", "text": MINE}})
        sent = self._tick({G1: _node(G1, "Ship the auth refactor")})
        self.assertEqual(len(sent), 1)
        self.assertIn(MINE, sent[0])
        self.assertNotIn(km.AUTO_NUDGE_TEXT, sent[0])
        self.assertIn("<!-- romp-goal-id: %s -->" % G1, sent[0])

    def test_two_due_goals_send_one_bundle_carrying_the_overridden_ask(self):
        self._cfg({NAME: {"mode": "append", "text": MINE}})
        sent = self._tick({G1: _node(G1, "Ship the auth refactor"),
                           G2: _node(G2, "Write the migration guide")})
        self.assertEqual(len(sent), 1, "same-tick fires still coalesce")
        self.assertIn("Where do these 2 stand?", sent[0])
        self.assertIn(MINE, sent[0])

    def test_an_unconfigured_session_still_sends_the_stock_ask(self):
        sent = self._tick({G1: _node(G1, "Ship the auth refactor")})
        self.assertEqual(len(sent), 1)
        self.assertIn(km.AUTO_NUDGE_TEXT, sent[0])


if __name__ == "__main__":
    unittest.main()
