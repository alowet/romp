#!/usr/bin/env python3
"""The bars frame's wire shape (T278b): a bar carries the FIRST line of its prompt, capped, and none of the three
fields that duplicated another (tid = the lane key, uuid = promptId, workUuid = workId).

Why: on the devbox the {type:"bars"} frame reached 20.4 MB (8,562 bars in 25 lanes) and took 22 s to cross the
laptop tunnel on every connect. The prompt text was 8.2 MB of it, though the pane's only reader (reqText, the
prompt-dot tip) shows at most 90 characters of the first non-empty line and the full text is a click away in the
chat; the three duplicate uuid-shaped fields were another 1.2 MB. The encoder lives in the kernel (_wire_prompt and
the bar literal); the view derives the dropped fields. tests/fixtures/timeline-bars-wire.json pins the encoding of
a synthetic payload, and ui/timeline-bars-wire.test.ts feeds the same fixture to the view's helpers and checks the
rendered tip and anchors match what the old shape rendered: the round trip, each half in its own suite.

Synthetic only: invented prompts, placeholder ids."""
import json
import os
import tempfile
import unittest
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.realpath(__file__))
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()      # hermetic BEFORE the load: never live state
os.environ.pop("ROMP_STATE_DIR", None)
km = SourceFileLoader("kernel_bars_wire", os.path.join(os.path.dirname(HERE), "kernel", "kernel.py")).load_module()

FIXTURE = os.path.join(HERE, "fixtures", "timeline-bars-wire.json")
SID = "11111111-2222-3333-4444-555555555555"
DROPPED = ("tid", "uuid", "workUuid")


def wire_bar(old, sid=SID):
    """The wire shape of an old-shape bar: the encoder's rules, applied to a dict (the builder applies them at
    construction; this is the same transformation for a fixture)."""
    b = {k: v for k, v in old.items() if k not in DROPPED}
    b["prompt"] = km._wire_prompt(old.get("prompt"))
    return b


class WirePrompt(unittest.TestCase):
    def test_the_first_non_empty_line_rides_and_the_rest_does_not(self):
        self.assertEqual(km._wire_prompt("\n\n  Fix the parser  \nsecond line\nthird"), "Fix the parser")

    def test_romp_marks_and_a_leading_label_are_removed_before_the_line_is_picked(self):
        # an injected notice: the marks (or the label alone) would otherwise be the first line, or eat the cap;
        # the view removed both from the WHOLE text before picking its line, so the kernel does the same
        self.assertEqual(km._wire_prompt("<!-- romp-injected --><!-- romp-system -->[romp] The kernel restarted\nmore"),
                         "The kernel restarted")
        self.assertEqual(km._wire_prompt("<!-- romp-note: a\nmulti-line mark -->\nReal ask"), "Real ask")
        self.assertEqual(km._wire_prompt("[romp]\nPlease restart the build"), "Please restart the build",
                         "a label alone on line one must not become the line the tip strips to nothing")
        self.assertEqual(km._wire_prompt("  [ROMP]  \n\nAsk"), "Ask")
        self.assertEqual(km._wire_prompt("Ask mentions [romp] mid-line"), "Ask mentions [romp] mid-line", "only a LEADING label")

    def test_a_long_first_line_is_cut_with_an_ellipsis(self):
        long = " ".join("word%d" % i for i in range(200))      # varied words: a long ask, not a repeat storm
        out = km._wire_prompt(long)
        self.assertTrue(out.endswith("…"))
        self.assertLessEqual(len(out), km._WIRE_PROMPT_MAX + 1)
        self.assertEqual(out[:-1], long[:km._WIRE_PROMPT_MAX].rstrip())
        self.assertEqual(km._wire_prompt("x" * km._WIRE_PROMPT_MAX), "x" * km._WIRE_PROMPT_MAX, "exactly the cap: no marker")

    def test_a_repeat_storm_is_collapsed_over_the_whole_text_before_the_cut(self):
        self.assertEqual(km._wire_prompt(" ".join(["retry"] * 120)), "retry ×120", "the count is the storm's size, never truncated")
        self.assertEqual(km._wire_prompt("retry Retry RETRY"), "retry ×3")
        self.assertEqual(km._wire_prompt("retry now"), "retry now", "any variety is left alone")

    def test_empty_and_none_are_empty(self):
        self.assertEqual(km._wire_prompt(""), "")
        self.assertEqual(km._wire_prompt(None), "")
        self.assertEqual(km._wire_prompt("<!-- romp-only -->"), "")


class BarLiteral(unittest.TestCase):
    def setUp(self):
        self.src = open(os.path.join(os.path.dirname(HERE), "kernel", "kernel.py")).read()
        head, tail = '"id": seg["id"], "promptId": seg.get("trigger"), "workId": work_uuid,', '"replyUuid": reply_uuid})'
        self.assertIn(head, self.src, "the bar literal's first line moved or was reflowed: re-anchor this pin")
        i = self.src.index(head)
        self.assertIn(tail, self.src[i:], "the bar literal's last key moved: re-anchor this pin")
        self.literal = self.src[i:self.src.index(tail, i) + len(tail)]

    def test_the_bar_carries_the_wire_prompt_and_none_of_the_duplicates(self):
        self.assertIn('"prompt": _wire_prompt(full_prompt)', self.literal)
        self.assertIn('full_prompts[seg["id"]] = full_prompt = _seg_prompt(seg)', self.src, "the full text is kept beside the wire")
        self.assertIn("_bind_message_execs(messages, turns, full_prompts)", self.src, "…and handed to the message binder")
        for gone in ('"tid":', '"uuid":', '"workUuid":'):
            self.assertNotIn(gone, self.literal, gone + " is derived by the view from the lane key / promptId / workId")
        for kept in ('"id":', '"promptId":', '"workId":', '"replyUuid":', '"start":', '"end":', '"open":', '"cont":',
                     '"summary":', '"msgCaption":', '"src":', '"mids":', '"pending":', '"nudgeAuto":', '"romp":'):
            self.assertIn(kept, self.literal, kept + " is still read by the view")


def _old_bars(n_lanes=25, per_lane=320):
    """A synthetic old-shape payload of the devbox's size class: 25 lanes, 8,000 bars, prompts of a few lines."""
    turns = {}
    for li in range(n_lanes):
        sid = "%08d-2222-3333-4444-555555555555" % li
        bars = []
        for bi in range(per_lane):
            seg = "%08d-%04d-4000-8000-000000000000" % (li, bi)
            work = "%08d-%04d-4000-8000-000000000001" % (li, bi)
            reply = "%08d-%04d-4000-8000-000000000002" % (li, bi)
            prompt = ("Please look into item %d of lane %d and tell me what changed.\n" % (bi, li)
                      + "Context paragraph one, invented, about two hundred characters long so that the payload has the shape of a real ask. " * 2
                      + "\nContext paragraph two, also invented, with a few more details the tip never shows. " * 3)
            bars.append({"id": seg, "promptId": seg, "workId": work, "start": 1000 + 10 * bi, "end": 1005 + 10 * bi,
                         "open": False, "cont": False, "prompt": prompt, "summary": "invented work caption %d" % bi,
                         "msgCaption": "gist %d" % bi, "src": "typed", "mids": [], "pending": False, "tid": sid, "uuid": seg,
                         "nudgeAuto": False, "romp": False, "workUuid": work, "replyUuid": reply})
        turns[sid] = bars
    return turns


class MessageBinder(unittest.TestCase):
    """The postal connector's sender heuristic reads the FULL prompt, not the wire line: a delivery's first
    line is the postal header and the sender's name sits further down."""

    def _case(self, prompts):
        sid = SID
        full = "\U0001f4ec New message(s) from your romp peers:\n\nfrom web: could you look at the parser?\n"
        bar = {"id": "seg-1", "start": 1000, "end": 1050, "mids": [], "prompt": km._wire_prompt(full)}
        # fromOrig set as the postal reader sets it: an absent one is the empty string, which every prompt contains
        msgs = [{"id": "m-1", "toId": sid, "from": "web", "fromOrig": "web", "sent": 990, "exec": 990, "pending": True}]
        km._bind_message_execs(msgs, {sid: [bar]}, prompts({"seg-1": full}))
        return msgs[0]

    def test_with_the_builders_full_prompts_the_sender_is_found_past_the_first_line(self):
        m = self._case(lambda d: d)
        self.assertEqual((m["exec"], m["pending"]), (1000, False))

    def test_without_them_the_wire_line_alone_cannot_name_the_sender(self):
        m = self._case(lambda d: None)
        self.assertEqual((m["exec"], m["pending"]), (990, True), "a caller passing no prompts reads the wire line alone")


class MemoCarriesPrompts(unittest.TestCase):
    def test_the_dead_lane_memo_stores_the_lanes_full_prompts_and_a_hit_hands_them_to_the_binder(self):
        src = open(os.path.join(os.path.dirname(HERE), "kernel", "kernel.py")).read()
        self.assertIn('"prompts": {b["id"]: full_prompts[b["id"]] for b in bars if b["id"] in full_prompts}', src)
        self.assertIn('full_prompts.update(cached.get("prompts") or {})', src)


class FrameSize(unittest.TestCase):
    def test_the_wire_shape_is_well_under_two_thirds_of_the_old_on_a_devbox_sized_payload(self):
        old = _old_bars()
        new = {sid: [wire_bar(b, sid) for b in bars] for sid, bars in old.items()}
        n_old, n_new = len(json.dumps(old)), len(json.dumps(new))
        self.assertEqual(sum(len(v) for v in new.values()), 8000)
        self.assertLess(n_new / n_old, 0.65, "old %d B, new %d B: ratio %.2f" % (n_old, n_new, n_new / n_old))
        self.assertGreater(n_new / n_old, 0.3, "the fixture is not a strawman: the ids and captions still ride")


class Fixture(unittest.TestCase):
    """The committed fixture is the round trip's shared half: this pins encode(old) == wire; the node test pins
    that the view renders `wire` as it rendered `old`."""

    def test_the_fixture_is_the_encoders_output(self):
        fx = json.load(open(FIXTURE))
        self.assertEqual(fx["sid"], SID)
        self.assertEqual(len(fx["old"]), len(fx["wire"]))
        for old, wire in zip(fx["old"], fx["wire"]):
            self.assertEqual(wire_bar(old, fx["sid"]), wire, old["id"])
        self.assertTrue(any(len(o["prompt"]) > km._WIRE_PROMPT_MAX for o in fx["old"]), "the fixture covers a cut")
        self.assertTrue(any(o["prompt"].startswith("<!-- romp-") for o in fx["old"]), "…and an injected notice")
        self.assertTrue(any(o["prompt"].startswith("[romp]\n") for o in fx["old"]), "…and a label alone on line one")
