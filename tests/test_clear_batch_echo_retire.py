#!/usr/bin/env python3
"""A /clear's optimistic echo must RETIRE by the IDENTITY of the /clear the CLI TOOK, even when a message
rode the same batch, and must NEVER retire a /clear that was only queued or fed-but-not-yet-taken.

The user's report (chat page): sending a `/clear` and a text message TOGETHER in one batch left the
transcript stuck, a dashed "sending…" /clear chip that never retired, beside the delivered message and
its answer, after the clear had run and the status read Ready. The cause is in the SDK backend's echo
lifecycle: a /clear resets the transcript and writes NO user record for itself, so its optimistic input
echo can never LAND (prune_live's by-text match never fires); and sent in the SAME whole second as the
batched message it is never OVERTAKEN either (settle_echoes' floor is strictly-later-in-whole-seconds).

The fix retires it on the exact event that proves THIS /clear ran, keyed on the copy the CLI has TAKEN
(round two keyed on the FEED, which stranded a /clear fed mid-turn: the message's result drained the
tracking before the CLI ever took the /clear). A fed copy sits in SdkSession._untaken until _untaken_taken
fires; only then is its echo qid recorded in _taken_clear_qids. It retires at the lastSid flip that follows
(the fresh conversation), or, for a /clear taken as its own fresh turn that found nothing to clear, its own
turn's ResultMessage settle. A /clear still QUEUED or fed-but-UNTAKEN reaches no boundary of its own and
keeps its echo, so an unplanned CLI death still flags/re-delivers it; a mid-turn SWALLOWED /clear keeps its
echo for settle_echoes to flag as a loss.

SYNTHETIC fixtures only (invented text, placeholder UUIDs, hostname TESTHOST)."""
import asyncio
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
from romp_load import load_source   # noqa: E402  the loader import comes FIRST: it brings in the tests package's
#   mkdtemp hook and TMPDIR redirect, so the state root minted below lands inside the run's temp root, never loose
#   (tests/test_state_isolation_order.py pins this order).
BIN = os.path.join(os.path.dirname(HERE), "bin")
# Hermetic state BEFORE the sdk_backend load, which resolves its state root at import time, and only pytest
# runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
_XDG = tempfile.mkdtemp()
os.environ["XDG_STATE_HOME"] = _XDG
os.environ.pop("ROMP_STATE_DIR", None)   # a live kernel's export outranks the XDG floor
# This module mints its own state roots, outside conftest's session-hosts floor, so it writes `off` itself
# (the 2026-09-11 rule): none of these tests connects a session, but the belt is armed the moment a backend
# is built over a root with no session-hosts file. The xdg DEFAULT root is <XDG_STATE_HOME>/romp
# (event_model.py), so the floor goes there, matching tests/conftest.py; the per-backend self.d floor below
# is the real protection for these tests (they hand SdkBackend an explicit self.d, not the xdg default).
os.makedirs(os.path.join(_XDG, "romp"), exist_ok=True)
open(os.path.join(_XDG, "romp", "session-hosts"), "w").write("off")

sb = load_source("romp_sdk_backend_clearbatch", os.path.join(os.path.dirname(HERE), "kernel", "sdk_backend.py"))

SID = "aaaaaaaa-1111-2222-3333-444444444444"   # a SHARED synthetic placeholder sid (~48 modules use it): never a real
#   session id, and safe here only because this module MINTS NO GOALS, so the cross-module override-journal collision the
#   goal-store fixtures guard against cannot reach it (the CLAUDE.md rule: rewording is enough when no goals are minted)
FRESH_FSID = "bbbbbbbb-5555-6666-7777-888888888888"
FRESH_FSID2 = "cccccccc-9999-aaaa-bbbb-cccccccccccc"
MSG = "please rebuild the notes-api search index"


class _Sys:
    """Stand-in for the CLI's SystemMessage (isinstance + subtype + data), the idiom of test_sdk_backend.py."""
    def __init__(self, data):
        self.subtype = "init"
        self.data = data


class _AM:
    pass


class _RM:
    """The CLI's ResultMessage double: an instance drives the settle path (isinstance uses the class ARG)."""
    uuid = "r1"


_RM.__name__ = "ResultMessage"


class ClearBatchEchoRetires(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        open(os.path.join(self.d, "session-hosts"), "w").write("off")   # this backend's root: hosts off (module note)
        self.be = sb.SdkBackend(self.d, "/bin/true", lambda *a, **k: None)
        # _untaken_taken's mid-turn branch reads the transcript; floor it False so a take is proven only by the
        # deterministic events these tests drive (a fresh copy, or a settled hold), never a stray transcript scan.
        self.be._text_landed = lambda *a, **k: False
        sb.write_reg(self.d, SID, {"sid": SID, "name": "web", "cwd": "/tmp/notes-api",
                                   "alive": True, "lastSid": SID})
        self.s = sb.SdkSession(self.be, {"sid": SID, "name": "web", "cwd": "/tmp/notes-api", "lastSid": SID})
        self.s.thread = type("T", (), {"is_alive": lambda self: True})()   # _ensure returns the live session
        self.s._input_wake = asyncio.Event()                              # inputs() owns this; stub it so settle can set it
        self.be.sessions[SID] = self.s

        async def _noop():
            pass
        self.s._do_refresh_context = _noop

    # --- helpers ---------------------------------------------------------------------------------------
    def _echo_texts(self):
        return [a.get("_echo_text") for a in self.be.live_atoms(SID)]

    def _echo_uuids(self):
        return [a.get("uuid") for a in self.be.live_atoms(SID)]

    def _echo_atom(self, qid):
        return {a.get("uuid"): a for a in self.be.live_atoms(SID)}.get(qid)

    def _feed(self):
        """Model the input generator handing the head copy to the CLI: pop for feed, then arm self._untaken
        (carrying the copy's qid + its `fresh` flag) and raise inflight, as inputs() does. The TAKE is a
        separate event (driven below); the qid is recorded only when the CLI takes it (_untaken_taken)."""
        with self.s._lock:
            fresh = self.s.inflight == 0
            text, meta = self.s._pop_for_feed_locked(0)
            self.s.inflight += 1
            self.s._inflight_texts.append(text)
            self.s._untaken = {"text": text, "item": text, "fresh": fresh, "settled": False,
                               "qid": (meta or {}).get("qid"), "t": int(time.time()), "off": None, "fsid": None}
        self.s._persist_queue()   # the fed turn leaves the persisted queue mirror, as inputs() does after the pop
        return text, (meta or {}).get("qid"), fresh

    def _om(self, msg):
        async def run():
            self.s._on_message(msg, _AM, _RM, _Sys)
            await asyncio.sleep(0)   # let the ensure_future'd refresh run, as the fast-mode tests do
        asyncio.run(run())

    def _take_and_flip(self, fsid=FRESH_FSID):
        """The CLI's init whose session_id flips lastSid to a fresh episode: one frame both TAKES the fed
        /clear (records its qid) and, since the fsid is new, ends the clearing bracket (retires the echo)."""
        self._om(_Sys({"session_id": fsid}))

    def _take_no_flip(self):
        """A turn frame that TAKES the fed copy but flips nothing (the init carries the SAME fsid)."""
        self._om(_Sys({"session_id": self.s.resume_sid}))

    def _settle(self):
        """The turn's ResultMessage: the backstop end (SdkSession._on_message ResultMessage finally)."""
        self._om(_RM())

    # --- the HIGH: retire keys on the IDENTITY of the /clear the CLI TOOK ------------------------------
    def test_a_taken_clear_that_ran_retires_exactly_its_own_echo_batched_with_a_message(self):
        # the same-second batch: /clear then the message, both delivered before the CLI can run either
        self.be.send(SID, "/clear", qid="echo:clear1", user=True)
        self.be.send(SID, MSG, qid="echo:msg1", user=True)
        self.assertTrue(self.s._clearing, "delivering /clear lights the clearing bracket")
        self.assertEqual(sorted(self._echo_texts()), sorted(["/clear", MSG]),
                         "both sends have an optimistic echo before either lands")

        # the /clear is fed (its own fresh turn); its qid is NOT recorded until the CLI takes it
        text, qid, fresh = self._feed()
        self.assertEqual((text, qid, fresh), ("/clear", "echo:clear1", True))
        self.assertEqual(self.s._taken_clear_qids, [], "fed, not yet taken: nothing recorded")

        # the batched message lands in the fresh conversation (its own user record); /clear never lands
        self.be.prune_live(SID, set(), {sb.echo_text_key(MSG): 9999999999}, 0)
        self.assertEqual(self._echo_texts(), ["/clear"],
                         "the message echo retires on its record; only the never-landing /clear remains")

        # the clear runs: the init TAKES the /clear (records its qid), then flips lastSid (retires it)
        self._take_and_flip()
        self.assertFalse(self.s._clearing, "the bracket ends on the flip (unchanged)")
        self.assertEqual(self.s.resume_sid, FRESH_FSID, "the fresh conversation exists (unchanged)")
        self.assertEqual(self._echo_texts(), [],
                         "the /clear echo retires at the clear boundary, no stuck dashed 'sending…' chip")
        self.assertEqual(self.s._taken_clear_qids, [], "the taken-clear ledger is spent")
        self.assertIsNone(self.s._own_turn_clear_qid, "the flip consumed the own-turn arm")

    def test_a_solo_taken_clear_retires_at_the_flip(self):
        self.be.send(SID, "/clear", qid="echo:clear-solo", user=True)
        self._feed()
        self._take_and_flip()
        self.assertEqual(self._echo_texts(), [], "a solo /clear's echo retires on its flip")

    def test_a_clear_only_QUEUED_keeps_its_echo_through_another_turns_result(self):
        # a turn is already running; a /clear is queued BEHIND it and never fed. Its echo must survive that
        # running turn's ResultMessage (round-one's backstop over-fired: it retired on ANY settle while lit).
        self.s.inflight = 1
        self.be.send(SID, "/clear", qid="echo:clear-q", user=True)
        self.assertTrue(self.s._clearing, "enqueue lights the bracket even for a queued /clear")
        self.assertEqual(self.s._taken_clear_qids, [], "nothing taken → nothing owed a boundary retire")
        self._settle()
        self.assertEqual(self._echo_texts(), ["/clear"],
                         "a /clear only QUEUED keeps its echo through another turn's settle")

    def test_a_clear_only_QUEUED_keeps_its_echo_through_an_unrelated_flip(self):
        # a fork/reconnect flips lastSid while a /clear is only queued (boot-restored bracket): the flip is
        # NOT this /clear's, so its echo must stay (round-one's init retire over-fired on ANY flipping init).
        self.be.send(SID, "/clear", qid="echo:clear-q2", user=True)
        self.assertEqual(self.s._taken_clear_qids, [], "not taken → the flip below is not its boundary")
        self._om(_Sys({"session_id": FRESH_FSID}))
        self.assertEqual(self._echo_texts(), ["/clear"],
                         "an unrelated flip does not retire a /clear the CLI never took")

    def test_a_clear_fed_but_UNTAKEN_survives_the_running_turns_result_and_retires_when_it_runs(self):
        # THE decision-1 case: a message is running; a /clear is fed MID-turn and becomes _untaken (the CLI is
        # busy, so it has NOT taken it). The message's ResultMessage must NOT retire the /clear (round two
        # drained the feed-time list here and stranded it); the /clear's echo survives and retires when the
        # CLI actually runs it.
        self.s.inflight = 1                                   # the message's turn is running
        self.be.send(SID, "/clear", qid="echo:clear-mid", user=True)
        text, qid, fresh = self._feed()                       # fed MID-turn (inflight was 1) → NOT fresh, NOT yet taken
        self.assertEqual((text, fresh), ("/clear", False))
        self.assertEqual(self.s._taken_clear_qids, [], "fed but untaken: nothing recorded")

        self._settle()                                        # the MESSAGE's result: it must not take/retire the /clear
        self.assertEqual(self._echo_texts(), ["/clear"], "the fed-but-untaken /clear survives the running turn's result")
        self.assertEqual(self.s._taken_clear_qids, [], "still nothing taken")
        self.assertTrue(self.s._untaken and self.s._untaken.get("settled"), "the hold is marked settled for the drain")

        # now the CLI takes the /clear as its own turn and flips: it retires ONCE, when it runs
        self._take_and_flip()
        self.assertEqual(self._echo_texts(), [], "the /clear echo retires when it actually runs, not before")

    def test_a_taken_clear_the_cli_swallowed_is_shown_as_a_loss(self):
        # the swallow: a /clear the CLI TOOK but folded into a running turn (not its own turn) and never
        # flipped. It reaches no boundary of its own, so its echo STAYS and settle_echoes flags it dropped;
        # its stale ledger entry is drained at the settle so it never poisons a later flip.
        self.s.inflight = 1
        old_t = int(time.time()) - 10
        self.be.send(SID, "/clear", qid="echo:clear-swallow", user=True)
        self._echo_atom("echo:clear-swallow")["t"] = old_t   # age it so a later floor overtakes it
        self._feed()                                          # fed MID-turn (leaves _pending: settle_echoes no longer sees it queued)
        # DRIVE the take: the CLI folds the /clear into the running turn (a mid-turn landing), so _untaken_taken
        # fires and the take is RECORDED through the REAL path, EXERCISING the `fresh` gate (it must NOT arm
        # _own_turn_clear_qid, fresh=False). Hand-setting the arm before skipped the gate, so the `if True:`
        # mutant (always arm) stayed invisible; driving it makes that mutant red (the loss below goes missing).
        self.be._text_landed = lambda *a, **k: True           # the fold: the /clear's text "landed" mid-turn (the CLI took it)
        self._take_no_flip()                                  # a turn frame → _untaken_taken (via the landing) records the take
        self.be._text_landed = lambda *a, **k: False          # restore for the settle / settle_echoes below
        self.assertEqual(self.s._taken_clear_qids, ["echo:clear-swallow"], "the take was recorded through the real path")
        self.assertIsNone(self.s._own_turn_clear_qid, "the `fresh` gate did NOT arm the backstop (mid-turn take, fresh=False)")

        self._settle()                                        # the running turn ends with no flip
        self.assertEqual(self._echo_texts(), ["/clear"], "the swallowed /clear's echo is NOT retired at settle")
        self.assertEqual(self.s._taken_clear_qids, [], "its stale ledger entry is drained (no future flip poisons)")

        self.be.settle_echoes(SID, human_floor=int(time.time()) + 5)
        self.assertTrue(self._echo_atom("echo:clear-swallow").get("dropped"),
                        "the swallowed /clear is shown as a loss, not silently retired")

    def test_two_queued_clears_retire_one_at_a_time(self):
        self.be.send(SID, "/clear", qid="echo:clear-a", user=True)
        self.be.send(SID, "/clear", qid="echo:clear-b", user=True)
        self.assertEqual(self._echo_texts(), ["/clear", "/clear"], "two /clear echoes pending")

        self._feed()                                         # take+flip the first /clear
        self._take_and_flip(FRESH_FSID)
        self.assertEqual(self._echo_uuids(), ["echo:clear-b"],
                         "the first /clear's echo retired at its flip; the second is untouched")
        self._settle()                                       # the first turn ends

        self._feed()                                         # take+flip the second /clear (a DIFFERENT fsid: a real flip)
        self._take_and_flip(FRESH_FSID2)
        self.assertEqual(self._echo_texts(), [], "the second /clear's echo retires at ITS own flip")

    def test_the_backstop_retires_a_taken_clear_with_nothing_to_clear(self):
        # EXECUTED backstop (round one pinned it by a regex only): a solo /clear the CLI TOOK as its own turn
        # but that minted no fresh fsid (nothing to clear → no flip) is retired at ITS turn's settle. The
        # retire runs in the settle's failed-step loop, so a raise in it cannot stop the settle (its own test below).
        self.be.send(SID, "/clear", qid="echo:clear-noflip", user=True)
        self._feed()                                         # fresh
        self._take_no_flip()                                 # taken as its own turn, no fresh fsid
        self.assertEqual(self.s._own_turn_clear_qid, "echo:clear-noflip", "armed for the backstop")
        self._settle()
        self.assertEqual(self._echo_texts(), [], "the backstop retires a no-flip /clear at its own turn's settle")
        self.assertIsNone(self.s._own_turn_clear_qid, "the arm is spent")

    def test_the_settle_completes_even_if_the_clear_retire_raises(self):
        # decision 3: the backstop retire runs as a step in the failed-step loop, so a raise in it is caught
        # and the settle still marks waiting / releases the queue (shaped like test_sdk_stream_survives_handler_errors).
        self.be.send(SID, "/clear", qid="echo:clear-raise", user=True)
        self._feed()
        self._take_no_flip()                                 # arms _own_turn_clear_qid
        self.be.retire_clear_echoes = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        self._settle()                                       # the retire raises INSIDE the loop, contained
        self.assertEqual(self.s.inflight, 0, "the settle still ran to idle despite the retire raising")
        self.assertTrue(self.s._input_wake.is_set(), "the queue was still released")

    def test_a_clear_sent_but_never_taken_keeps_its_echo(self):
        # loss preserved: with NO take and NO boundary, the echo stays so a genuine loss can still be flagged
        self.be.send(SID, "/clear", qid="echo:clear-lost", user=True)
        self.assertEqual(self._echo_texts(), ["/clear"], "never taken → the echo stays, a loss settle can flag it")

    def test_retire_clear_echoes_is_by_qid_never_by_text(self):
        # a message that happens to read like a second /clear copy must not be swept: the retire pops the ONE
        # atom keyed by the supplied qid, not every /clear-texted echo.
        self.be.send(SID, "/clear", qid="echo:c1", user=True)
        self.be.send(SID, "/clear extra note", qid="echo:c2", user=True)   # a second, different /clear copy
        self.be.retire_clear_echoes(SID, "echo:c1")
        self.assertEqual(self._echo_uuids(), ["echo:c2"],
                         "only the qid named is popped; the other /clear echo stays")

    def test_flip_first_keeps_the_message_echo_and_the_mirror_lists_it(self):
        # flip-first (the real live order): the /clear's flip lands BEFORE the batched message's record, so at
        # the flip the message echo is still pending. The /clear echo goes; the message echo STAYS; the echo
        # mirror (reg['echoes']) still lists the message (a restart would re-seed it).
        self.be.send(SID, "/clear", qid="echo:cf", user=True)
        self.be.send(SID, MSG, qid="echo:mf", user=True)
        self._feed()                                         # feed + take + flip the /clear, message not landed yet
        self._take_and_flip()
        self.assertEqual(self._echo_texts(), [MSG], "the /clear echo retired at its flip; the message echo stays")
        reg = sb.read_reg(self.d, SID) or {}
        self.assertEqual([e.get("text") for e in (reg.get("echoes") or [])], [MSG],
                         "the echo mirror still lists the message (the /clear's retire persisted only its own removal)")

    def test_a_restart_after_a_solo_clear_retire_reseeds_nothing_stale(self):
        # decision 6: retire_clear_echoes persists the emptied mirror, so a restart right after a solo /clear's
        # retire (by flip OR by backstop) re-seeds no stale /clear echo, and the take ledger is not restored.
        for boundary in ("flip", "backstop"):   # loop-ok: two boundary shapes, bounded
            self.setUp()
            self.be.send(SID, "/clear", qid="echo:cr-" + boundary, user=True)
            self._feed()
            if boundary == "flip":
                self._take_and_flip()
            else:
                self._take_no_flip()
                self._settle()
            self.assertEqual(self._echo_texts(), [], "the /clear echo retired (%s)" % boundary)
            reg = sb.read_reg(self.d, SID) or {}
            self.assertEqual(reg.get("echoes") or [], [], "the mirror is empty: a restart re-seeds no stale /clear (%s)" % boundary)
            self.assertEqual(reg.get("clearingTaken") or [], [], "and the take ledger is spent in the mirror (%s)" % boundary)
            # a REAL restart: a fresh backend + session over the same state root. The reseeded live tail and the
            # restored _pending queue must carry no /clear (decision 6's other two checks, unverified before).
            be2 = sb.SdkBackend(self.d, "/bin/true", lambda *a, **k: None)
            be2._text_landed = lambda *a, **k: False
            be2._reseed_echoes([reg])
            self.assertEqual([a.get("_echo_text") for a in be2.live_atoms(SID)], [],
                             "the reseeded live tail carries no /clear after the retire (%s)" % boundary)
            s2 = sb.SdkSession(be2, sb.read_reg(self.d, SID))
            self.assertNotIn("/clear", s2._pending, "the restored queue carries no /clear (%s)" % boundary)

    def test_a_restart_between_take_and_flip_restores_the_take_only_when_the_lease_survives(self):
        # decision 5: a kernel restart in the window between a /clear's TAKE and its flip, on a CLI its host
        # KEPT alive, restores the take-tracking from reg['clearingTaken'] (relit bracket), so the surviving
        # CLI's flip retires the echo instead of it being flagged never-delivered. A CLI the restart did not
        # survive restores nothing (the /clear never runs → a genuine loss).
        self.be.send(SID, "/clear", qid="echo:cr2", user=True)
        self._feed()
        self._take_no_flip()                                 # TAKEN, awaiting its flip; the take is mirrored
        reg = sb.read_reg(self.d, SID) or {}
        self.assertEqual(reg.get("clearingTaken") or [], ["echo:cr2"], "the take is mirrored beside the echo")
        # The OWN-TURN arm round-trips through the mirror too (the /clear was taken as its own fresh turn),
        # so a restored no-flip /clear retires at its settle instead of being flagged lost. The reg KEY, by name:
        self.assertEqual(reg.get("clearingOwnTurn"), "echo:cr2", "the own-turn arm is persisted under clearingOwnTurn")

        # restart with the lease SURVIVING: a fresh backend + session over the same reg restore the take
        be2 = sb.SdkBackend(self.d, "/bin/true", lambda *a, **k: None)
        be2._text_landed = lambda *a, **k: False
        be2._lease_survives = lambda sid: True
        s2 = sb.SdkSession(be2, sb.read_reg(self.d, SID))
        self.assertEqual(s2._taken_clear_qids, ["echo:cr2"], "lease survives → the take is restored")
        self.assertEqual(s2._own_turn_clear_qid, "echo:cr2", "…and the own-turn arm round-trips back from clearingOwnTurn")
        self.assertTrue(s2._clearing, "…and the clearing bracket is relit")

        # restart with the lease GONE: the take is not restored (the /clear never ran → its echo is a loss)
        be3 = sb.SdkBackend(self.d, "/bin/true", lambda *a, **k: None)
        be3._text_landed = lambda *a, **k: False
        be3._lease_survives = lambda sid: False
        s3 = sb.SdkSession(be3, sb.read_reg(self.d, SID))
        self.assertEqual(s3._taken_clear_qids, [], "lease gone → nothing restored; the echo is a genuine loss")
        self.assertIsNone(s3._own_turn_clear_qid, "…and the own-turn arm is not restored either")
        reg3 = sb.read_reg(self.d, SID) or {}
        self.assertNotIn("clearingTaken", reg3, "lease gone: the stale take mirror is DROPPED, so a later host-kept restart cannot relight the bracket from it")
        self.assertNotIn("clearingOwnTurn", reg3, "…and the own-turn mirror is dropped too")

    def test_a_taken_clears_retire_forgets_its_fed_ledger_entry(self):
        # A /clear echo retired by the flip must also leave the FED ledger (_fed_meta): its landing will never
        # come (it wrote no record of its own), and a stale fed entry would be paired against a later record.
        # retire_clear_echoes calls forget_fed for exactly this. (Red-first: with forget_fed removed the qid
        # lingers in _fed_meta.)
        self.be.send(SID, "/clear", qid="echo:fedclear", user=True)
        self._feed()
        self.assertIn("echo:fedclear", [f.get("qid") for f in self.s._fed_meta],
                      "premise: the fed /clear copy is in the fed ledger")
        self._take_and_flip()
        self.assertEqual(self._echo_texts(), [], "the /clear echo retired at the flip")
        self.assertNotIn("echo:fedclear", [f.get("qid") for f in self.s._fed_meta],
                         "the retire also FORGETS the fed ledger entry (its landing will never come)")

    def test_a_no_op_flip_retire_still_drains_the_reg_mirror(self):
        # retire_clear_echoes persists the mirror only when it REMOVES an echo. When the flip's retire is a
        # NO-OP (the echo already gone), the pop of _taken_clear_qids must still be mirrored, or
        # reg['clearingTaken'] keeps the spent qid and a later host-kept restart relights the bracket.
        # (Red-first: without the persist after the pop, the reg mirror keeps the qid.)
        self.be.send(SID, "/clear", qid="echo:noop", user=True)
        self._feed()
        self._take_no_flip()                                  # taken + mirrored (clearingTaken=[echo:noop])
        self.assertEqual((sb.read_reg(self.d, SID) or {}).get("clearingTaken") or [], ["echo:noop"])
        # the echo is already gone by the time the flip runs, so the flip's retire finds nothing (a NO-OP)
        with self.be._live_lock:
            (self.be._live.get(SID) or {}).pop("echo:noop", None)
        self.assertEqual(self._echo_texts(), [], "premise: the /clear echo is already gone before the flip")
        self._take_and_flip()                                 # the flip pops the take; its retire removes no echo
        self.assertEqual((sb.read_reg(self.d, SID) or {}).get("clearingTaken") or [], [],
                         "the flip mirrors the emptied take list even though the retire removed no echo")

    def test_reconcile_stranded_drops_the_take_tracking_and_its_mirror(self):
        # A /clear a reconnect-abandoned client had TAKEN can never flip: _reconcile_stranded must drop its
        # take-tracking (not only the bracket) AND re-persist. Otherwise the next unrelated turn's settle would
        # retire its echo (hiding the loss), and a later host-kept restart would relight the bracket from the
        # stale mirror. (Red-first: without the reset the fields and the reg keys survive the reconcile.)
        self.be.send(SID, "/clear", qid="echo:strand", user=True)
        self._feed()
        self._take_no_flip()                                  # TAKEN, awaiting its flip; the take is recorded + mirrored
        self.assertEqual(self.s._taken_clear_qids, ["echo:strand"], "premise: the take is recorded")
        self.assertEqual(self.s._own_turn_clear_qid, "echo:strand", "premise: the own-turn arm is set")
        self.assertEqual((sb.read_reg(self.d, SID) or {}).get("clearingTaken") or [], ["echo:strand"], "premise: the take is mirrored")
        self.s._reconcile_stranded()
        self.assertEqual(self.s._taken_clear_qids, [], "the reconcile drops the take ledger")
        self.assertIsNone(self.s._own_turn_clear_qid, "the reconcile drops the own-turn arm")
        reg2 = sb.read_reg(self.d, SID) or {}
        self.assertEqual(reg2.get("clearingTaken") or [], [], "and the reg mirror is dropped too")
        self.assertIsNone(reg2.get("clearingOwnTurn"), "…including the own-turn arm in the mirror")


if __name__ == "__main__":
    unittest.main()
