#!/usr/bin/env python3
"""A safeguards downgrade is picked back at the session's next idle (the user 2026-08-13).

The CLI's safeguards can flag a prompt and retry the turn on a fallback model. The swap is
session-scoped, so every later turn stays on the fallback until somebody picks the model back — which
on an unattended session nobody does, for hours. romp now undoes it itself: the swap record the parse
already carries (system/model_refusal_fallback) arms a restore, and the restore fires when the session
goes quiet, ONE per flagged turn, never into a live turn and never over a model the user chose.

SYNTHETIC only: placeholder uuids, invented notes-api prompts, temp dirs.
"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
em = SourceFileLoader("romp_em_mrestore", os.path.join(BIN, "romp-event-model")).load_module()
km = SourceFileLoader("romp_kernel_mrestore", os.path.join(BIN, "romp-kernel")).load_module()

# The account gate is a separate axis (tests/test_kernel_limit_queue.py owns it). Left live, these
# tests would read the real machine's usage.json and park the restore for a reason none of them is
# about, the moment that account hit a limit. Pin it off so they stay hermetic.
km._limit_hold = lambda sid: None

SID = "11111111-2222-3333-4444-555555555555"
NOW = 1781100000
T0 = NOW - 3600

NOTICE = ("The model's safeguards flagged this message. Switched to a fallback model. "
          "Send feedback with /feedback.")


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def flagged_turn(n, at, frm="claude-fable-5", to="claude-opus-4-8"):
    """One turn whose prompt was flagged: the refused call leaves an assistant record carrying only a
    {"type":"fallback"} block, the fallback model then replies, and the system record — stamped with
    the retry start — carries the swap facts. The shape the CLI actually writes."""
    u, afb, a1, sfb = "u%d" % n, "afb%d" % n, "a%d" % n, "sfb%d" % n
    return [
        {"type": "user", "timestamp": iso(at), "uuid": u, "parentUuid": None,
         "promptSource": "typed",
         "message": {"role": "user", "content": "audit the notes-api auth middleware"}},
        {"type": "assistant", "timestamp": iso(at + 5), "uuid": afb, "parentUuid": u,
         "message": {"role": "assistant", "stop_reason": "end_turn",
                     "content": [{"type": "fallback", "from": {"model": frm}, "to": {"model": to}}]}},
        {"type": "assistant", "timestamp": iso(at + 45), "uuid": a1, "parentUuid": afb,
         "message": {"role": "assistant", "stop_reason": "end_turn",
                     "content": [{"type": "text", "text": "The middleware validates the bearer token."}]}},
        {"type": "system", "subtype": "model_refusal_fallback", "timestamp": iso(at + 5),
         "uuid": sfb, "parentUuid": a1, "direction": "retry", "trigger": "refusal", "scope": "session",
         "level": "warning", "content": NOTICE, "originalModel": frm, "fallbackModel": to},
    ]


def clean_turn(n, at):
    u, a1 = "u%d" % n, "a%d" % n
    return [
        {"type": "user", "timestamp": iso(at), "uuid": u, "parentUuid": None,
         "promptSource": "typed",
         "message": {"role": "user", "content": "now list the notes-api routes"}},
        {"type": "assistant", "timestamp": iso(at + 20), "uuid": a1, "parentUuid": u,
         "message": {"role": "assistant", "stop_reason": "end_turn",
                     "content": [{"type": "text", "text": "GET /notes, POST /notes."}]}},
    ]


def write(records, path=None):
    """Write a synthetic transcript and parse it, as (path, parsed). A fresh temp dir per call unless
    a path is handed back in — reusing one is how the transcript-grew case is exercised."""
    if path is None:
        path = Path(tempfile.mkdtemp()) / (SID + ".jsonl")
    Path(path).write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return str(path), em.parse_session(str(path), rompuuid=SID, now=NOW)


class WhichDowngradeIsStillInForce(unittest.TestCase):
    """_downgrade_in_force reads the swap off the parse and decides whether it still stands."""

    def setUp(self):
        km._newest_swap_cache.clear()

    tearDown = setUp

    def test_a_swap_the_session_is_still_sitting_on_arms_the_restore(self):
        hit = km._downgrade_in_force(*write(flagged_turn(1, T0)), "Opus 4.8")
        self.assertIsNotNone(hit, "the session is still on the model the swap moved it to")
        self.assertEqual(hit[1], "fable", "it goes back to the family the swap took it off")

    def test_a_session_already_back_on_its_own_model_has_nothing_to_undo(self):
        self.assertIsNone(km._downgrade_in_force(*write(flagged_turn(1, T0)), "Fable 5"),
                          "picked back by hand → the swap is spent, do not touch it again")

    def test_a_model_the_user_moved_to_since_is_left_alone(self):
        self.assertIsNone(km._downgrade_in_force(*write(flagged_turn(1, T0)), "Sonnet 5"),
                          "a live human decision outranks an old swap — never yank them off it")

    def test_only_the_newest_swap_counts(self):
        # flagged, then flagged again onto a DIFFERENT fallback: the session sits on the newest one
        recs = flagged_turn(1, T0) + flagged_turn(2, T0 + 300, to="claude-sonnet-5")
        self.assertIsNone(km._downgrade_in_force(*write(recs), "Opus 4.8"),
                          "the older swap is history; the session is not on that model any more")
        km._newest_swap_cache.clear()
        hit = km._downgrade_in_force(*write(recs), "Sonnet 5")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[1], "fable")

    def test_a_transcript_with_no_swap_arms_nothing(self):
        self.assertIsNone(km._downgrade_in_force(*write(clean_turn(1, T0)), "Fable 5"))

    def test_an_unrecognised_pairing_is_never_handed_to_set_model(self):
        recs = flagged_turn(1, T0, frm="some-other-vendor-model", to="claude-opus-4-8")
        self.assertIsNone(km._downgrade_in_force(*write(recs), "Opus 4.8"),
                          "no known family to go back to → leave the session alone, don't invent one")

    def test_an_unrecognised_newest_swap_does_not_resurrect_the_one_before_it(self):
        recs = (flagged_turn(1, T0)
                + flagged_turn(2, T0 + 300, frm="some-other-vendor-model", to="claude-opus-4-8"))
        self.assertIsNone(km._downgrade_in_force(*write(recs), "Opus 4.8"),
                          "the newest swap decides; a superseded one is not an excuse to act")

    def test_the_scan_memo_notices_the_transcript_growing(self):
        # the memo is keyed on (mtime,size) — a swap that lands after a clean scan must still be seen,
        # or the restore would be silently disabled for the life of the session
        path, _ = write(clean_turn(1, T0))
        self.assertIsNone(km._downgrade_in_force(path, em.parse_session(path, rompuuid=SID, now=NOW),
                                                 "Fable 5"))
        os.utime(path, (T0, T0))                      # pin an old mtime so the rewrite's differs for sure
        path, parsed = write(clean_turn(1, T0) + flagged_turn(2, T0 + 300), path=path)
        hit = km._downgrade_in_force(path, parsed, "Opus 4.8")
        self.assertIsNotNone(hit, "the transcript changed → the memo must re-scan, not serve the old answer")
        self.assertEqual(hit[1], "fable")


class _FakeBackend:
    def __init__(self):
        self.calls = []

    def set_model(self, sid, value):
        self.calls.append((sid, value))
        return True

    def busy(self, sid):
        return None


class TheRestoreFiresAtIdleOncePerTurn(unittest.TestCase):
    def setUp(self):
        self.be = _FakeBackend()
        self._saved = (km._alive_sessions, km._parse_cached, km._working_now, km._compacting_now,
                       km._clearing_now, km._model_pending_now, km.Sessions.backend_for,
                       km._push_soon, km._push_all, km._mark_views_dirty)
        self.path = str(Path(tempfile.mkdtemp()) / (SID + ".jsonl"))
        km._alive_sessions = lambda now, tmux: [{"sid": SID, "path": self.path}]
        km._working_now = lambda sid: False
        km._compacting_now = lambda sid: False
        km._clearing_now = lambda sid: False
        km._model_pending_now = lambda sid, tm: False
        km.Sessions.backend_for = lambda sid: self.be
        km._push_soon = lambda: None
        km._push_all = lambda: None
        km._mark_views_dirty = lambda: None
        km._model_restored.clear()
        km._pending_ops.clear()
        km._model_switch_pending.clear()
        km._newest_swap_cache.clear()

    def tearDown(self):
        (km._alive_sessions, km._parse_cached, km._working_now, km._compacting_now,
         km._clearing_now, km._model_pending_now, km.Sessions.backend_for,
         km._push_soon, km._push_all, km._mark_views_dirty) = self._saved
        km._model_restored.clear()
        km._pending_ops.clear()
        km._model_switch_pending.clear()
        km._newest_swap_cache.clear()

    def _arm(self, records, live_model):
        """Lay down the transcript this session is running on and say which model it is live on now."""
        _, session = write(records, path=self.path)
        km._parse_cached = lambda path: session
        return {SID: {"state": "idle", "since": NOW - 100, "model": live_model, "effort": "",
                      "context": None, "compactPct": None, "color": None}}

    def test_an_idle_downgraded_session_is_put_back(self):
        tmux = self._arm(flagged_turn(1, T0), "Opus 4.8")
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [(SID, "fable")], "the swap is undone at idle")

    def test_it_does_not_fire_twice_for_the_same_flagged_turn(self):
        tmux = self._arm(flagged_turn(1, T0), "Opus 4.8")
        km._auto_restore_model_tick(NOW, tmux)
        km._auto_restore_model_tick(NOW, tmux)      # the switch has not landed yet — model still reads Opus
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [(SID, "fable")],
                         "one restore per flagged turn — a re-flagged turn is answered once, not per flag")

    def test_a_turn_flagged_twice_still_earns_only_one_restore(self):
        # the CLI can write the swap record more than once inside a single turn (a retry ladder)
        recs = flagged_turn(1, T0)
        recs.append(dict(recs[-1], uuid="sfb1b", timestamp=iso(T0 + 9)))
        tmux = self._arm(recs, "Opus 4.8")
        km._auto_restore_model_tick(NOW, tmux)
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [(SID, "fable")])

    def test_a_fresh_downgrade_on_a_later_turn_gets_its_own_restore(self):
        tmux = self._arm(flagged_turn(1, T0), "Opus 4.8")
        km._auto_restore_model_tick(NOW, tmux)
        # the switch lands, the session runs a clean turn on its own model, then gets flagged again
        tmux = self._arm(flagged_turn(1, T0) + clean_turn(2, T0 + 200) + flagged_turn(3, T0 + 400),
                         "Opus 4.8")
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [(SID, "fable"), (SID, "fable")],
                         "it never gives up across turns — a new flag is a new turn and earns a new restore")

    def test_it_never_fires_into_a_live_turn(self):
        tmux = self._arm(flagged_turn(1, T0), "Opus 4.8")
        km._working_now = lambda sid: True
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [], "mid-turn the pick waits — it does not land in an open turn")
        km._working_now = lambda sid: False
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [(SID, "fable")], "…and lands the moment the session settles")

    def test_a_compaction_parks_it_instead_of_dropping_it(self):
        tmux = self._arm(flagged_turn(1, T0), "Opus 4.8")
        km._compacting_now = lambda sid: True
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [], "a compaction is not idle")
        km._compacting_now = lambda sid: False
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [(SID, "fable")])

    def test_a_switch_already_in_flight_is_left_to_resolve(self):
        tmux = self._arm(flagged_turn(1, T0), "Opus 4.8")
        km._model_pending_now = lambda sid, tm: True
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [], "a pick is already on its way — don't stack another on top")

    def test_a_session_the_user_moved_elsewhere_is_not_yanked_back(self):
        tmux = self._arm(flagged_turn(1, T0), "Sonnet 5")
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [], "the user picked this model after the swap — leave it")

    def test_an_unparsed_session_is_skipped_not_guessed_at(self):
        km._parse_cached = lambda path: None
        km._auto_restore_model_tick(NOW, {SID: {"model": "Opus 4.8"}})
        self.assertEqual(self.be.calls, [], "no cached parse yet → wait for one, never act on a guess")


if __name__ == "__main__":
    unittest.main()
