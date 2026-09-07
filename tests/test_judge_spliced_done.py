#!/usr/bin/env python3
"""A prompt QUEUED into a running turn must never complete off that turn's unrelated work (the user 2026-07-29).

The incident: the user queued a question while the session was mid-turn on other work; the CLI
spliced it in (a queued_command attachment, stamped with its ENQUEUE time), and the process died
before any reply. The splice's segment absorbed the running turn's CONTINUING atoms — real assistant
work, none of it a reply to the spliced ask — so the no-work guard from the API-error fix
(_has_asst_work, the user 2026-07-25) passed, plan_units emitted a full work unit framed
"USER ASKED: … ASSISTANT SAID: [other work]", and a capable planner answered the question from its
own knowledge and filed done with a confabulated summary — 30 seconds after the ask was typed,
before the assistant's first post-splice token. Now the event model marks the synthesized splice
atom `absorbed`, and planner DONE ops filed off a spliced-trigger segment are stripped
(_strip_unevidenced_dones, spliced leg): work in such a segment is never proof the spliced ask — or any listed goal —
was answered. Mint/sub still apply (the ask gets its card, the tail work files), the goal stays
open — the truth — and the turn-level closer keeps done authority. SYNTHETIC fixtures only."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader
from pathlib import Path
import os

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
# Hermetic state BEFORE the loads — they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
jd = SourceFileLoader("romp_judge_spliced_done", os.path.join(BIN, "romp-judge")).load_module()

NOW = 1781100000
SID = "11111111-2222-3333-4444-555555555555"
T0 = NOW - 3600
ASK = "Can the notes-api search endpoint run without a separate key, or does that need its own token?"


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def uline(t, text, uuid, parent=None):
    return {"type": "user", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent,
            "promptSource": "typed", "message": {"role": "user", "content": text}}


def aline(t, text, uuid, parent=None, stop="end_turn"):
    return {"type": "assistant", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}],
                        "stop_reason": stop}}


def qline(t, text, uuid, parent):
    """The CLI's mid-turn splice witness: a queued_command attachment, uuid-bearing, parent-chained,
    stamped with the ENQUEUE time (earlier than its neighbours in file order — the real shape)."""
    return {"type": "attachment", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent,
            "attachment": {"type": "queued_command", "prompt": text}}


DONE_HAPPY = ('{"ops":[{"why":"asked about the search endpoint","do":"mint","text":"Answer the search endpoint question"},'
              '{"why":"explained the same token covers it","do":"done","ref":1}]}')
SKIP = '{"ops":[{"why":"nothing to file","do":"skip"}]}'


def spliced_records():
    """An in-flight labeling turn; the ask spliced into it at enqueue time; the turn's work
    CONTINUES (chained through the attachment, as the CLI writes it) and never answers the ask;
    a later unrelated turn ends things."""
    return [
        uline(T0, "Label the notes-api fixture batch", "u1"),
        aline(T0 + 10, "Working through the batch now.", "a1", "u1"),
        qline(T0 + 30, ASK, "q1", "a1"),
        aline(T0 + 60, "Sheet seven labeled; two to go.", "a2", "q1"),
        uline(T0 + 400, "unrelated: also bump the version", "u2", "a2"),
        aline(T0 + 410, "Bumped.", "a3", "u2"),
    ]


class SplicedDone(unittest.TestCase):
    def _run(self, records, reply_for_ask, reply_default=SKIP):
        calls = []
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            tpath = td / (SID + ".jsonl")
            tpath.write_text("\n".join(json.dumps(r) for r in records) + "\n")
            saved = (jd.GOALDIR, jd.PCACHE, jd.plan_llm, jd.opener_llm, jd._group_store)
            jd.GOALDIR, jd.PCACHE = td / "goals", td / "pcache"
            def fake(text, *a, **k):
                calls.append(text)
                return reply_for_ask if ASK[:40] in text else reply_default
            jd.plan_llm = jd.opener_llm = fake
            jd._group_store = lambda *a, **k: None
            try:
                jd._PARSE_CACHE.clear(); jd._CHAIN_MEMO.clear()
                jd._plan_session(SID, str(tpath), NOW)
                store = jd.load_goals(SID)
            finally:
                (jd.GOALDIR, jd.PCACHE, jd.plan_llm, jd.opener_llm, jd._group_store) = saved
            return calls, store

    def test_spliced_ask_places_but_cannot_complete(self):
        calls, store = self._run(spliced_records(), DONE_HAPPY)
        # the planner DID see the ambiguous frame (the unit still runs — the guard is at op level)
        self.assertTrue(any(ASK[:40] in c for c in calls),
                        "the spliced segment still gets its work unit — the tail work must still file")
        asked = [nd for nd in store["nodes"].values()
                 if "search endpoint" in (nd.get("text") or "").lower()]
        self.assertTrue(asked, "the spliced ask still gets a card — it is real")
        self.assertFalse(asked[0].get("nodeComplete"),
                         "a done-happy planner reply must not complete a goal off a spliced segment "
                         "whose work belongs to the interrupted turn's own ask")

    def test_spliced_done_cannot_complete_other_cards_either(self):
        # a done aimed at a PRE-EXISTING card (the in-flight work's own card, coerce-placed by the
        # earlier segment) is confabulation off the same unreliable frame — stripped too, and the
        # ask itself still lands via the never-vanish floor
        done_only = '{"ops":[{"why":"the batch is finished","do":"done","goal":1}]}'
        calls, store = self._run(spliced_records(), done_only)
        self.assertTrue(store["nodes"], "the earlier segment's ask was placed")
        self.assertFalse(any(nd.get("nodeComplete") for nd in store["nodes"].values()),
                         "no goal may complete off a spliced-trigger segment")
        placed_texts = " | ".join((nd.get("quote") or nd.get("text") or "") for nd in store["nodes"].values())
        self.assertIn(ASK[:30], placed_texts,
                      "a stripped-to-empty reply still hard-places the spliced ask (never vanish)")

    def test_typed_ask_with_real_answer_still_completes(self):
        # guard precision: an ordinary typed ask whose turn really answers it still dones
        records = [
            uline(T0, ASK, "u1"),
            aline(T0 + 10, "No separate key: the search endpoint rides the session token.", "a1", "u1"),
            uline(T0 + 400, "unrelated: also bump the version", "u2", "a1"),
            aline(T0 + 410, "Bumped.", "a3", "u2"),
        ]
        calls, store = self._run(records, DONE_HAPPY)
        asked = [nd for nd in store["nodes"].values()
                 if "search endpoint" in (nd.get("text") or "").lower()]
        self.assertTrue(asked and asked[0].get("nodeComplete"),
                        "a genuinely delivered answer still completes")

    def test_absorbed_trigger_is_marked_and_detected(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            tpath = td / (SID + ".jsonl")
            tpath.write_text("\n".join(json.dumps(r) for r in spliced_records()) + "\n")
            jd._PARSE_CACHE.clear(); jd._CHAIN_MEMO.clear()
            session = jd.parsed_session(SID, [str(tpath)], NOW)
        segs = [seg for turn in session["turns"] for seg in jd.em.segments(turn)]
        by_trig = {seg.get("trigger"): seg for seg in segs}
        self.assertIn("q1", by_trig, "the splice opens its own segment")
        spliced = by_trig["q1"]
        self.assertTrue(any(a.get("uuid") == "q1" and a.get("absorbed") for a in spliced["atoms"]),
                        "the synthesized splice atom carries the absorbed marker")
        self.assertTrue(jd._seg_spliced(spliced))
        self.assertFalse(jd._seg_spliced(by_trig["u1"]),
                         "an ordinary typed trigger is not spliced")
        # and the running turn's continuation really does land inside the splice's segment —
        # the ambiguity this whole guard exists for
        self.assertIn("a2", [a.get("uuid") for a in spliced["atoms"]])


if __name__ == "__main__":
    unittest.main()
