#!/usr/bin/env python3
"""A safeguards downgrade is picked back at the session's next idle (the user 2026-08-13).

The CLI's safeguards can flag a prompt and retry the turn on a fallback model. The swap is
session-scoped, so every later turn stays on the fallback until somebody picks the model back — which
on an unattended session nobody does, for hours. romp now undoes it itself: the swap record the parse
already carries (system/model_refusal_fallback) arms a restore, and the restore fires when the session
goes quiet, ONE per flagged turn, never into a live turn and never over a model the user chose.

Budgeted, though (the user 2026-08-15): a session flagged over and over is fed straight back into the
safeguards by an unconditional restore, so after _MODEL_RESTORE_BUDGET of them romp stands down, says
so once, and waits for a human pick before it will try again.

And it puts the session on the CLI's "Default" rather than the model it was flagged off (the user
2026-08-18) — restoring Fable handed the safeguards the model that had just tripped them, and the loop
that produced burned the whole budget in two minutes. Which means the swap's two models can now be one
FAMILY apart and no more (Opus 5 restored, Opus 4.8 the fallback), so everything here is version-exact.

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
# Hermetic state BEFORE the loads — they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
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
        self.assertEqual(hit[1], "Fable 5", "it reports the model the swap took it off, for the messages")

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
        self.assertEqual(hit[1], "Fable 5")

    def test_a_transcript_with_no_swap_arms_nothing(self):
        self.assertIsNone(km._downgrade_in_force(*write(clean_turn(1, T0)), "Fable 5"))

    def test_a_swap_off_a_model_romp_cannot_name_is_left_alone(self):
        recs = flagged_turn(1, T0, frm="some-other-vendor-model", to="claude-opus-4-8")
        self.assertIsNone(km._downgrade_in_force(*write(recs), "Opus 4.8"),
                          "a routed/unknown model is a choice romp can't read — don't move it to the default")

    def test_a_restore_that_landed_is_not_read_as_still_on_the_fallback(self):
        # the whole point of the version-exact test: the restore lands the session on Opus 5, and the
        # fallback is Opus 4.8. A family test would call that "still downgraded" forever.
        self.assertIsNone(km._downgrade_in_force(*write(flagged_turn(1, T0)), "Opus 5"),
                          "Opus 5 is not Opus 4.8 — the swap is undone, re-arm for the next one")

    def test_a_swap_within_one_family_still_counts(self):
        # …and the other half: once restores land on Opus 5, a re-flag is Opus 5 → Opus 4.8. Dismissing
        # that as "same family, no swap" would park the session on the fallback with nobody told.
        hit = km._downgrade_in_force(*write(flagged_turn(1, T0, frm="claude-opus-5")), "Opus 4.8")
        self.assertIsNotNone(hit, "same family, different model — it is still a downgrade")
        self.assertEqual(hit[1], "Opus 5")

    def test_a_bare_versionless_badge_is_waited_out_not_guessed_at(self):
        self.assertIsNone(km._downgrade_in_force(*write(flagged_turn(1, T0)), "Opus"),
                          "which Opus that is decides everything — wait for a badge that says")

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
        self.assertEqual(hit[1], "Fable 5")


class _FakeBackend:
    def __init__(self):
        self.calls = []

    def set_model(self, sid, value, seed=True):
        self.calls.append((sid, value, seed))
        return True

    def busy(self, sid):
        return None


class _RestoreTickHarness(unittest.TestCase):
    """One idle session running off a synthetic transcript, with every surface the tick touches
    stubbed — including the notifier, so a test run can never fire a real desktop/phone alert."""

    def setUp(self):
        self.be = _FakeBackend()
        self.notified = []
        self._saved = (km._alive_sessions, km._parse_cached, km._working_now, km._compacting_now,
                       km._clearing_now, km._model_pending_now, km.Sessions.backend_for,
                       km._push_soon, km._push_all, km._mark_views_dirty,
                       km._system_notify, km._push_notify,
                       km._notify_session_effective, km._path_of)
        km._system_notify = lambda title, body: self.notified.append((title, body))
        km._push_notify = lambda title, body, sid="", badge=None: None
        km._notify_session_effective = lambda sid: True   # bell on: the stand-down is not muted
        self.path = str(Path(tempfile.mkdtemp()) / (SID + ".jsonl"))
        km._alive_sessions = lambda now, tmux: [{"sid": SID, "path": self.path}]
        km._path_of = lambda sid: self.path
        km._working_now = lambda sid: False
        km._compacting_now = lambda sid: False
        km._clearing_now = lambda sid: False
        km._model_pending_now = lambda sid, tm: False
        km.Sessions.backend_for = lambda sid: self.be
        km._push_soon = lambda: None
        km._push_all = lambda: None
        km._mark_views_dirty = lambda: None
        km._model_restored.clear()
        km._model_restore_spent.clear()
        km._model_stood_down.clear()
        km._model_restore_inflight.clear()
        km._model_hand_picked.clear()
        km._pending_ops.clear()
        km._model_switch_pending.clear()
        km._newest_swap_cache.clear()

    def tearDown(self):
        (km._alive_sessions, km._parse_cached, km._working_now, km._compacting_now,
         km._clearing_now, km._model_pending_now, km.Sessions.backend_for,
         km._push_soon, km._push_all, km._mark_views_dirty,
         km._system_notify, km._push_notify,
         km._notify_session_effective, km._path_of) = self._saved
        km._model_restored.clear()
        km._model_restore_spent.clear()
        km._model_stood_down.clear()
        km._model_restore_inflight.clear()
        km._model_hand_picked.clear()
        km._pending_ops.clear()
        km._model_switch_pending.clear()
        km._newest_swap_cache.clear()

    def _arm(self, records, live_model):
        """Lay down the transcript this session is running on and say which model it is live on now."""
        _, session = write(records, path=self.path)
        km._parse_cached = lambda path: session
        return {SID: {"state": "idle", "since": NOW - 100, "model": live_model, "effort": "",
                      "context": None, "compactPct": None, "color": None}}


class TheRestoreFiresAtIdleOncePerTurn(_RestoreTickHarness):
    def test_an_idle_downgraded_session_is_put_back(self):
        tmux = self._arm(flagged_turn(1, T0), "Opus 4.8")
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [(SID, "default", False)],
                         "the swap is undone at idle — onto the CLI default, and not as a new-session seed")

    def test_it_does_not_fire_twice_for_the_same_flagged_turn(self):
        tmux = self._arm(flagged_turn(1, T0), "Opus 4.8")
        km._auto_restore_model_tick(NOW, tmux)
        km._auto_restore_model_tick(NOW, tmux)      # the switch has not landed yet — model still reads Opus
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [(SID, "default", False)],
                         "one restore per flagged turn — a re-flagged turn is answered once, not per flag")

    def test_a_turn_flagged_twice_still_earns_only_one_restore(self):
        # the CLI can write the swap record more than once inside a single turn (a retry ladder)
        recs = flagged_turn(1, T0)
        recs.append(dict(recs[-1], uuid="sfb1b", timestamp=iso(T0 + 9)))
        tmux = self._arm(recs, "Opus 4.8")
        km._auto_restore_model_tick(NOW, tmux)
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [(SID, "default", False)])

    def test_a_fresh_downgrade_on_a_later_turn_gets_its_own_restore(self):
        tmux = self._arm(flagged_turn(1, T0), "Opus 4.8")
        km._auto_restore_model_tick(NOW, tmux)
        # the switch lands, the session runs a clean turn on its own model, then gets flagged again
        tmux = self._arm(flagged_turn(1, T0) + clean_turn(2, T0 + 200) + flagged_turn(3, T0 + 400),
                         "Opus 4.8")
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [(SID, "default", False), (SID, "default", False)],
                         "across turns a new flag is a new turn and earns its own restore (up to the budget)")

    def test_it_never_fires_into_a_live_turn(self):
        tmux = self._arm(flagged_turn(1, T0), "Opus 4.8")
        km._working_now = lambda sid: True
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [], "mid-turn the pick waits — it does not land in an open turn")
        km._working_now = lambda sid: False
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [(SID, "default", False)],
                         "…and lands the moment the session settles")

    def test_a_compaction_parks_it_instead_of_dropping_it(self):
        tmux = self._arm(flagged_turn(1, T0), "Opus 4.8")
        km._compacting_now = lambda sid: True
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [], "a compaction is not idle")
        km._compacting_now = lambda sid: False
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [(SID, "default", False)])

    def test_a_switch_already_in_flight_is_left_to_resolve(self):
        tmux = self._arm(flagged_turn(1, T0), "Opus 4.8")
        km._model_pending_now = lambda sid, tm: True
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [], "a pick is already on its way — don't stack another on top")

    def test_a_session_the_user_moved_elsewhere_is_not_yanked_back(self):
        tmux = self._arm(flagged_turn(1, T0), "Sonnet 5")
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [], "the user picked this model after the swap — leave it")

    def test_a_human_picking_the_fallback_model_itself_is_not_overruled(self):
        """The one case the live-model test can never see. romp's picker offers "Opus", which resolves to
        Opus 4.8 here — the very model the safeguards move sessions onto — so a user who deliberately
        picks it leaves a badge indistinguishable from an untouched downgrade. The pick itself is the
        signal (_human_picked_model), and it retires the swap that was standing when they made it."""
        tmux = self._arm(flagged_turn(1, T0), "Opus 4.8")
        km._compacting_now = lambda sid: False
        km._set_model_or_park(self.be, SID, "opus")     # their own pick, onto the fallback model
        self.be.calls.pop()                             # (not one of romp's restores)
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [], "they chose this model seconds ago — do not move them off it")

        tmux = self._arm(flagged_turn(1, T0) + flagged_turn(2, T0 + 300), "Opus 4.8")
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(self.be.calls, [(SID, "default", False)],
                         "a flag AFTER their pick is a new event their pick was not a verdict on")

    def test_a_backend_that_refuses_the_pick_spends_nothing(self):
        # SdkBackend.set_model returns False outright for a sid with no registry entry (a session
        # mid-teardown). Counting that as a restore would let a session be stood down — and announced as
        # "put back 5 times" — having never once actually been put back.
        class _Refuses(_FakeBackend):
            def set_model(self, sid, value, seed=True):
                _FakeBackend.set_model(self, sid, value, seed)
                return False
        self.be = _Refuses()
        tmux = self._arm(flagged_turn(1, T0), "Opus 4.8")
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(km._model_restore_spent.get(SID, 0), 0, "nothing landed, so nothing was spent")
        km._auto_restore_model_tick(NOW, tmux)
        self.assertEqual(len(self.be.calls), 2, "…and the turn is not marked answered — it tries again")

    def test_an_unparsed_session_is_skipped_not_guessed_at(self):
        km._parse_cached = lambda path: None
        km._auto_restore_model_tick(NOW, {SID: {"model": "Opus 4.8"}})
        self.assertEqual(self.be.calls, [], "no cached parse yet → wait for one, never act on a guess")


class TheRestoreBudgetStopsItLoopingForever(_RestoreTickHarness):
    """A session that keeps getting flagged is not helped by being put straight back on the model that
    keeps getting flagged — that just feeds the next flag, unattended, indefinitely, which is the shape
    that risks an account-level lockout (the user 2026-08-15). So the restores are budgeted, romp stands
    down when the budget runs out, and it says so rather than leaving the session quietly parked."""

    def setUp(self):
        super().setUp()
        self.recs = []

    def _flag_again(self, n, frm="claude-fable-5", live="Opus 4.8"):
        """Append one more flagged turn to the transcript this session is running on, and push once."""
        self.recs += flagged_turn(n, T0 + 100 * n, frm=frm)
        km._auto_restore_model_tick(NOW, self._arm(list(self.recs), live))

    def _budget(self):
        return km._MODEL_RESTORE_BUDGET

    def test_it_stops_after_the_budget_and_says_so_exactly_once(self):
        for n in range(1, self._budget() + 1):
            self._flag_again(n)
        self.assertEqual(len(self.be.calls), self._budget(), "every restore inside the budget lands")
        self.assertEqual(self.notified, [], "nothing is stuck yet — it has been put back every time")

        self._flag_again(self._budget() + 1)
        self.assertEqual(len(self.be.calls), self._budget(),
                         "the budget is spent — this flag is left standing rather than fed again")
        self.assertEqual(len(self.notified), 1,
                         "…and it is announced, because the session is now parked where nobody put it")

        for n in range(self._budget() + 2, self._budget() + 5):
            self._flag_again(n)
            km._auto_restore_model_tick(NOW, self._arm(list(self.recs), "Opus 4.8"))   # and idle pushes
        self.assertEqual(len(self.be.calls), self._budget(), "stood down stays stood down")
        self.assertEqual(len(self.notified), 1, "one stand-down notice, not one per flag or per push")

    def test_a_restore_that_lands_is_not_mistaken_for_a_hand_pick(self):
        for n in range(1, self._budget() + 1):
            self._flag_again(n)
            # the pick lands — the session sits on the default (Opus 5 here) until the next flag
            km._auto_restore_model_tick(NOW, self._arm(list(self.recs), "Opus 5"))
        self._flag_again(self._budget() + 1)
        self.assertEqual(len(self.be.calls), self._budget(),
                         "leaving the fallback because the restore WORKED must not refill the budget")

    def test_clean_turns_in_between_do_not_refill_the_budget(self):
        for n in range(1, self._budget() + 1):
            self._flag_again(n)
            self.recs += clean_turn(50 + n, T0 + 100 * n + 50)
            km._auto_restore_model_tick(NOW, self._arm(list(self.recs), "Opus 5"))
        self._flag_again(self._budget() + 1)
        self.assertEqual(len(self.be.calls), self._budget(),
                         "work going well in between is not a reason to start the count over")

    def test_the_last_restore_landing_after_the_stand_down_does_not_refill_it(self):
        """The loop this whole budget exists to stop, in the shape the journal caught it (2026-08-17,
        19:19:27 stand-down → 19:19:37 restore 1/5). A pick is SENT at one push and the live model reads
        back several pushes later, so the budget can run out and stand down while the last restore is
        still in flight. When it lands the session leaves the fallback — which looks exactly like a hand
        pick unless romp remembers that the move was its own."""
        for n in range(1, self._budget() + 2):        # …+1 flag past the budget → stood down, announced
            self._flag_again(n)
        self.assertEqual(len(self.notified), 1)
        spent = len(self.be.calls)

        km._auto_restore_model_tick(NOW, self._arm(list(self.recs), "Opus 5"))   # the last pick lands, late
        self._flag_again(self._budget() + 2, frm="claude-opus-5")
        self.assertEqual(len(self.be.calls), spent,
                         "romp's own restore landing is not a human at the wheel — no fresh budget")
        self.assertEqual(len(self.notified), 1, "and no second stand-down notice either")

    def test_an_out_of_band_pick_after_the_restore_landed_still_refills_it(self):
        for n in range(1, self._budget() + 2):
            self._flag_again(n)
        spent = len(self.be.calls)
        km._auto_restore_model_tick(NOW, self._arm(list(self.recs), "Opus 5"))   # romp's restore, consumed
        km._auto_restore_model_tick(NOW, self._arm(list(self.recs), "Sonnet 5"))  # and NOW a human picks
        self._flag_again(self._budget() + 2, frm="claude-sonnet-5")
        self.assertEqual(len(self.be.calls), spent + 1,
                         "the move romp cannot account for is the human's, and it earns a fresh set")

    def test_a_swap_romp_cannot_read_does_not_hand_back_the_budget(self):
        """The refill infers a human from the session leaving the fallback. A swap whose models romp
        can't name also makes the swap unreadable — but the session has not moved anywhere, nobody has
        touched it, and reading that as a hand pick would quietly undo the cap that exists to keep an
        unattended session from cycling restores into the safeguards all night."""
        for n in range(1, self._budget() + 2):
            self._flag_again(n)
        spent = len(self.be.calls)
        self.assertEqual(len(self.notified), 1, "stood down")

        # a newest swap romp can't read lands, with the session still sitting on the fallback
        self.recs += flagged_turn(90, T0 + 9000, frm="some-other-vendor-model")
        km._auto_restore_model_tick(NOW, self._arm(list(self.recs), "Opus 4.8"))
        self._flag_again(self._budget() + 2)
        self.assertEqual(len(self.be.calls), spent, "still stood down — nothing about this was a human")

    def test_a_hand_pick_while_stood_down_hands_it_a_fresh_budget(self):
        for n in range(1, self._budget() + 2):
            self._flag_again(n)
        self.assertEqual(len(self.notified), 1, "stood down, and the user has been told")

        # the user picks a model themselves, through a surface — the pick romp can SEE being made, so
        # the refill needs no inference at all (and none of romp's own picks are seeded this way)
        km._compacting_now = lambda sid: False
        km._set_model_or_park(self.be, SID, "sonnet")
        self.be.calls.pop()                             # their pick is not one of romp's restores
        self._flag_again(self._budget() + 2, frm="claude-sonnet-5")
        self.assertEqual(len(self.be.calls), self._budget() + 1,
                         "a human back at the wheel earns the session a fresh set of restores")
        self.assertEqual(self.be.calls[-1], (SID, "default", False),
                         "the restore target does not follow what they picked — it is always the default")


if __name__ == "__main__":
    unittest.main()
