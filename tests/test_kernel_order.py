#!/usr/bin/env python3
"""Session order (chat tabs + timeline lanes) is a PURE function of session-order.json — it must NEVER
auto-reshuffle on activity (mtime / status / death), only a user drag reorders (the user 2026-06-24:
"the only thing that should reorder them is the user clicking and dragging").

Pins bin/romp-kernel's _ordered / _ordered_alive / _chat_tab_sessions / _timeline_sessions and the
non-destructive _merge_session_order. Synthetic fleet only: placeholder UUIDs, no real session data.
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
# Hermetic state BEFORE the loads — they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
km = SourceFileLoader("romp_kernel_order", os.path.join(BIN, "romp-kernel")).load_module()

A = "aaaaaaaa-0000-0000-0000-000000000001"
B = "bbbbbbbb-0000-0000-0000-000000000002"
C = "cccccccc-0000-0000-0000-000000000003"
D = "dddddddd-0000-0000-0000-000000000004"


def sess(sid, mtime):
    return {"sid": sid, "name": sid[:8], "path": "/x/%s.jsonl" % sid, "mtime": mtime}


class SessionOrder(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        # redirect every state read/write (_session_order / _write_session_order) into a temp dir
        self._saved = {"STATE": km.jd.STATE, "_kept_open": km._kept_open,
                       "_alive_sessions": km._alive_sessions, "_sessions": km._sessions}
        km.jd.STATE = Path(self.td.name)
        km._kept_open = set()

    def tearDown(self):
        km.jd.STATE = self._saved["STATE"]
        km._kept_open = self._saved["_kept_open"]
        km._alive_sessions = self._saved["_alive_sessions"]
        km._sessions = self._saved["_sessions"]
        self.td.cleanup()

    def order_file(self):
        return json.loads((km.jd.STATE / "session-order.json").read_text())

    def sids(self, rows):
        return [s["sid"] for s in rows]

    # ── _ordered: pure positional, freeze-on-first-sight, ZERO activity input ──────────────────────
    def test_appends_newcomers_in_input_order_and_persists(self):
        out = self.sids(km._ordered([sess(A, 100), sess(B, 200), sess(C, 300)]))
        self.assertEqual(out, [A, B, C])
        self.assertEqual(self.order_file(), [A, B, C])     # frozen to disk

    def test_stable_across_mtime_changes_the_core_bug(self):
        km._ordered([sess(A, 100), sess(B, 200), sess(C, 300)])     # seed
        # B "works" hard (mtime spikes highest), C goes quiet (mtime lowest) — order must NOT move
        out = self.sids(km._ordered([sess(A, 100), sess(B, 99999), sess(C, 5)]))
        self.assertEqual(out, [A, B, C])

    def test_saved_order_wins_over_mtime(self):
        km._write_session_order([C, A, B])
        out = self.sids(km._ordered([sess(A, 999), sess(B, 1), sess(C, 500)]))
        self.assertEqual(out, [C, A, B])                   # disk order honored, mtime ignored

    def test_newcomer_lands_at_end_even_if_newest_by_activity(self):
        km._write_session_order([A, B])
        out = self.sids(km._ordered([sess(A, 1), sess(B, 2), sess(C, 99999)]))
        self.assertEqual(out, [A, B, C])                   # C is newest but appends at END, never jumps to top

    # ── _chat_tab_sessions / _timeline_sessions: stable through activity + death ───────────────────
    def test_chat_tabs_keep_order_when_a_session_dies(self):
        km._alive_sessions = lambda now, tmux: [sess(A, 100), sess(B, 200), sess(C, 300)]
        km._sessions = lambda now: [sess(A, 100), sess(B, 200), sess(C, 300)]
        self.assertEqual(self.sids(km._chat_tab_sessions(0, {})), [A, B, C])
        # B dies (leaves the alive set); not kept-open → its tab drops, A & C keep their relative order
        km._alive_sessions = lambda now, tmux: [sess(A, 100), sess(C, 300)]
        self.assertEqual(self.sids(km._chat_tab_sessions(0, {})), [A, C])

    def test_timeline_lanes_never_reshuffle_on_activity(self):
        km._alive_sessions = lambda now, tmux: [sess(A, 100), sess(B, 200)]
        km._sessions = lambda now: [sess(A, 100), sess(B, 200), sess(C, 50), sess(D, 60)]
        self.assertEqual(self.sids(km._timeline_sessions(0, {})), [A, B, C, D])
        # B works hard + dead lane C's transcript gets touched (both mtimes spike) — lanes must hold
        km._alive_sessions = lambda now, tmux: [sess(A, 100), sess(B, 99999)]
        km._sessions = lambda now: [sess(A, 100), sess(B, 99999), sess(C, 88888), sess(D, 60)]
        self.assertEqual(self.sids(km._timeline_sessions(0, {})), [A, B, C, D])

    # ── _merge_session_order: a drag moves ONLY what it touched ────────────────────────────────────
    def test_chat_drag_leaves_timeline_only_lanes_in_place(self):
        km._write_session_order([A, B, C, D])              # B, D are timeline-only dead lanes
        # chat shows A & C; user drags them to [C, A] — B and D must keep their slots
        self.assertEqual(km._merge_session_order([C, A]), [C, B, A, D])

    def test_merge_appends_brand_new_sids_at_end(self):
        km._write_session_order([A, B])
        self.assertEqual(km._merge_session_order([B, A, C]), [B, A, C])

    def test_merge_on_empty_existing_is_incoming(self):
        self.assertEqual(km._merge_session_order([A, B, C]), [A, B, C])

    def test_merge_dedupes_and_drops_non_strings(self):
        km._write_session_order([A, B])
        self.assertEqual(km._merge_session_order([B, A, A, 7, None]), [B, A])

    # ── _gc_session_order: self-clean GONE sids, keep everything still around ───────────────────────
    def test_gc_prunes_gone_sids_keeps_survivors_in_order(self):
        km._write_session_order([A, B, C, D])
        km._gc_session_order({A, C})                       # B, D are gone (not alive, no transcript)
        self.assertEqual(self.order_file(), [A, C])        # gone sids dropped; survivors keep their order

    def test_gc_is_a_noop_when_nothing_is_gone(self):
        km._write_session_order([A, B, C])
        km._gc_session_order({A, B, C, D})                 # all present (D just isn't in the order yet)
        self.assertEqual(self.order_file(), [A, B, C])     # unchanged

    def test_chat_push_prunes_a_truly_gone_session_from_the_file(self):
        km._write_session_order([A, B, C])
        km._alive_sessions = lambda now, tmux: [sess(A, 100), sess(C, 300)]    # B not alive
        km._sessions = lambda now: [sess(A, 100), sess(C, 300)]               # B's transcript gone → GONE
        km._chat_tab_sessions(0, {})
        self.assertEqual(self.order_file(), [A, C])        # B pruned on a chat push (self-cleaning)

    def test_chat_push_keeps_a_dead_but_in_window_session(self):
        km._write_session_order([A, B, C])
        km._alive_sessions = lambda now, tmux: [sess(A, 100), sess(C, 300)]    # B not alive...
        km._sessions = lambda now: [sess(A, 100), sess(B, 200), sess(C, 300)]  # ...but B is still in-window
        km._chat_tab_sessions(0, {})
        self.assertEqual(self.order_file(), [A, B, C])     # dead-but-in-window B keeps its slot

    # ── fork identity: a /clear/revive (new fsid, SAME anchor) keeps its slot, never jumps to the END ──────
    def test_a_fork_slots_after_its_anchor_not_at_the_end(self):
        km._write_session_order([A, B, C])
        A2 = "aaaaaaaa-0000-0000-0000-0000000000a2"        # A forks → new fsid, same anchor A
        def f(sid, anchor):
            return {"sid": sid, "name": sid[:8], "anchor": anchor, "path": "/x/%s.jsonl" % sid, "mtime": 1}
        out = self.sids(km._ordered([f(A, A), f(B, B), f(C, C), f(A2, A)]))
        self.assertEqual(self.order_file(), [A, A2, B, C])  # A2 inherits A's place, not the END
        self.assertEqual(out, [A, A2, B, C])

    def test_a_genuinely_new_session_still_appends_at_the_end(self):
        km._write_session_order([A, B])
        def f(sid, anchor):
            return {"sid": sid, "name": sid[:8], "anchor": anchor, "path": "/x/%s.jsonl" % sid, "mtime": 1}
        D2 = "dddddddd-0000-0000-0000-0000000000d2"
        self.sids(km._ordered([f(A, A), f(B, B), f(D2, D2)]))   # D2 is its own anchor → no sibling
        self.assertEqual(self.order_file(), [A, B, D2])

    # ── the silent-reorder bug: a SELF-anchored fork (discover's lexical scan anchored it to itself) must
    #    STILL inherit its session's slot by NAME, not jump to the END (the user 2026-06-29) ─────────────
    def test_a_self_anchored_fork_inherits_by_NAME_not_the_end(self):
        # A relaunch/clear of the session named "obsidian" mints a new fsid that — because it has its OWN
        # names entry, scanned first — discover SELF-anchors (anchor == its own sid). The OLD inheritance
        # keyed on that anchor, so it found no sibling and appended at the END (obsidian jumped). Keying on
        # the stable NAME, the fork lands right after its same-name sibling instead.
        km._write_session_order([A, B, C])
        OBS2 = "00000000-0000-0000-0000-00000000ob2"          # lexically-small fork → discover self-anchors it
        def f(sid, name, anchor):
            return {"sid": sid, "name": name, "anchor": anchor, "path": "/x/%s.jsonl" % sid, "mtime": 1}
        # A is the original "obsidian"; OBS2 is its relaunch fork, self-anchored, but SAME name "obsidian"
        out = self.sids(km._ordered([f(A, "obsidian", A), f(B, "bee", B), f(C, "see", C),
                                     f(OBS2, "obsidian", OBS2)]))
        self.assertEqual(self.order_file(), [A, OBS2, B, C], "the fork inherits obsidian's slot, not the END")
        self.assertEqual(out, [A, OBS2, B, C])

    def test_relaunch_transfers_the_slot_across_a_chat_push_gc(self):
        # End-to-end through _chat_tab_sessions: the OLD fsid is dead-but-in-window while the relaunch fork is
        # alive; ordering must run BEFORE the GC so the fork inherits the slot in the SAME build (a GC-first
        # order would drop the old fsid first, leaving the fork no sibling → it would jump to the END).
        km._write_session_order([A, B, C])                     # A = "obsidian" original, in slot 0
        OBS2 = "00000000-0000-0000-0000-00000000ob2"
        def f(sid, name):
            return {"sid": sid, "name": name, "path": "/x/%s.jsonl" % sid, "mtime": 1}
        # the dead original A is NOT in the live input, so _ordered resolves its NAME from the names registry
        # (in production its names entry persists across a relaunch — both fsids keep one). Stub that lookup.
        reg = {A: "obsidian", OBS2: "obsidian", B: "bee", C: "see"}
        saved_name_of = km._name_of
        km._name_of = lambda sid: reg.get(sid)
        self.addCleanup(lambda: setattr(km, "_name_of", saved_name_of))
        # A is no longer alive (relaunched) but its transcript is still in-window; OBS2 is the live fork
        km._alive_sessions = lambda now, tmux: [f(OBS2, "obsidian"), f(B, "bee"), f(C, "see")]
        km._sessions = lambda now: [f(A, "obsidian"), f(OBS2, "obsidian"), f(B, "bee"), f(C, "see")]
        out = self.sids(km._chat_tab_sessions(0, {}))
        # OBS2 inherited slot 1 (right after A); A is dead-but-in-window so it keeps its slot in the FILE
        self.assertEqual(self.order_file(), [A, OBS2, B, C])
        # the LIVE tabs are OBS2, B, C (dead A isn't rendered) — OBS2 sits FIRST in obsidian's slot, NOT at
        # the end behind B and C, which is where the self-anchored-fork bug pushed it.
        self.assertEqual(out, [OBS2, B, C], "the fork renders in obsidian's slot (first), not at the end")


class OrderStoreUnreadableRefuses(unittest.TestCase):
    """The state-readers audit (rank 8): _session_order used to fold ANY read fault to [], and both
    _merge_session_order (a drag) and _ordered (per push) persisted the result — so a transient EIO
    turned every session "new", overwriting the user's saved lane order with plain discovery order
    under no gesture. The mutation paths now read PROVED: a drag is refused loudly and _ordered
    renders last-known and persists nothing on a fault. Synthetic sids only."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        # _session_order_lkg is new on the fix; guard so this module still IMPORTS + runs on origin/main
        # (where the primary test must fail by SHOWING the erasure, not erroring in setUp)
        self._lkg = km._session_order_lkg[0] if hasattr(km, "_session_order_lkg") else None
        self._saved_state = km.jd.STATE
        km.jd.STATE = Path(self.td.name)
        if hasattr(km, "_session_order_lkg"):
            km._session_order_lkg[0] = None

    def tearDown(self):
        km.jd.STATE = self._saved_state
        if hasattr(km, "_session_order_lkg"):
            km._session_order_lkg[0] = self._lkg
        self.td.cleanup()

    def _path(self):
        return km.jd.STATE / "session-order.json"

    def _fault_reads_of(self, target):
        """Fail BOTH read_bytes (the fix's proved reader) and read_text (origin/main's reader) for one
        path — green on the fix, RED on main where the fold-to-[] overwrites the order with a drag's
        subset (or discovery order)."""
        import errno
        real_rb, real_rt = Path.read_bytes, Path.read_text
        tgt = str(target)
        def rb(self, *a, **k):
            if str(self) == tgt:
                raise OSError(errno.EIO, "injected EIO")
            return real_rb(self, *a, **k)
        def rt(self, *a, **k):
            if str(self) == tgt:
                raise OSError(errno.EIO, "injected EIO")
            return real_rt(self, *a, **k)
        Path.read_bytes, Path.read_text = rb, rt
        return (real_rb, real_rt)

    def test_a_drag_is_refused_and_the_order_untouched_when_the_store_cannot_be_read(self):
        km._write_session_order([A, B, C])                 # the user's saved lane order
        before = self._path().read_bytes()
        saved = self._fault_reads_of(self._path())
        raised = None
        try:
            # a chat-tab drag publishing only [C, B]: on origin/main _merge_session_order reads a
            # fabricated [] and returns [C, B], which _write_session_order then persists — DROPPING A's
            # slot. Here we persist the merge result exactly as the WS branch does, so the erasure shows.
            merged = km._merge_session_order([C, B])
            km._write_session_order(merged)
        except Exception as e:                             # noqa: BLE001 — on main it never raises
            raised = e
        finally:
            Path.read_bytes, Path.read_text = saved
        # THE erasure: on main the file is now [C, B] (A gone); the fix refuses before any write.
        self.assertEqual(self._path().read_bytes(), before,
                         "the order file must be unchanged when its file can't be read (main drops A here)")
        self.assertEqual(type(raised).__name__, "_StateUnreadable",
                         "the drag is refused LOUDLY, not spliced into a fabricated [] (got %r)" % raised)

    def test_ordered_renders_last_known_and_persists_nothing_on_a_fault(self):
        km._write_session_order([A, B, C])
        _ = km._session_order()                            # prime the last-known-good
        before = self._path().read_bytes()
        saved = self._fault_reads_of(self._path())
        try:
            out = [s["sid"] for s in km._ordered([sess(C, 300), sess(A, 100), sess(B, 200)])]
        finally:
            Path.read_bytes, Path.read_text = saved
        self.assertEqual(out, [A, B, C], "renders the last-known order, not discovery order")
        self.assertEqual(self._path().read_bytes(), before,
                         "a display fault persists NOTHING — the saved order is not overwritten")

    def test_a_torn_order_file_is_quarantined_aside_not_overwritten(self):
        torn = b'["aaaa", THIS IS NOT JSON'
        self._path().write_bytes(torn)
        self.assertEqual(km._session_order_proved(), [], "the store starts empty only after the bytes are saved")
        q = list(km.jd.STATE.glob("session-order.json.corrupt-*"))
        self.assertEqual(len(q), 1)
        self.assertEqual(q[0].read_bytes(), torn, "the quarantine holds the ORIGINAL bytes")
        self.assertFalse(self._path().exists())

    def test_enoent_order_still_reads_empty_with_no_quarantine(self):
        self.assertEqual(km._session_order(), [], "a missing store is legitimately empty")
        self.assertEqual(km._session_order_proved(), [])
        self.assertEqual(list(km.jd.STATE.glob("session-order.json.corrupt-*")), [])


import contextlib
import errno
import time
from unittest import mock


@contextlib.contextmanager
def _reads_fault(target):
    """Fail every byte read of ONE path with an EIO for the duration of the block."""
    real_rb, real_rt = Path.read_bytes, Path.read_text
    tgt = str(target)
    def rb(self, *a, **k):
        if str(self) == tgt:
            raise OSError(errno.EIO, "injected EIO")
        return real_rb(self, *a, **k)
    def rt(self, *a, **k):
        if str(self) == tgt:
            raise OSError(errno.EIO, "injected EIO")
        return real_rt(self, *a, **k)
    Path.read_bytes, Path.read_text = rb, rt
    try:
        yield
    finally:
        Path.read_bytes, Path.read_text = real_rb, real_rt


class OrderDisplayReaderServesUnproved(unittest.TestCase):
    """The DISPLAY reader of the lane order under a fault serves the last order this kernel read or
    wrote -- and never latches what the fault produced as the new known-good. A reader that latched
    [] would render discovery order on the second faulted build and hand the mutation path a
    fabricated 'last known' to fall back on."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self._saved_state, self._lkg = km.jd.STATE, km._session_order_lkg[0]
        km.jd.STATE = Path(self.td.name)
        km._session_order_lkg[0] = None
        km._state_fault_seen.clear()

    def tearDown(self):
        km.jd.STATE = self._saved_state
        km._session_order_lkg[0] = self._lkg
        km._state_fault_seen.clear()
        self.td.cleanup()

    def _path(self):
        return km.jd.STATE / "session-order.json"

    def test_a_fault_serves_the_last_known_order_on_every_faulted_read(self):
        km._write_session_order([A, B, C])
        self.assertEqual(km._session_order(), [A, B, C])                # primes the known-good
        with _reads_fault(self._path()):
            self.assertEqual(km._session_order(), [A, B, C])
            self.assertEqual(km._session_order(), [A, B, C], "the second faulted read serves the same -- nothing was latched")
            self.assertEqual(km._session_order_lkg[0], [A, B, C])
        self.assertEqual(km._session_order(), [A, B, C])

    def test_a_fault_with_no_known_good_serves_empty_and_latches_nothing(self):
        km._write_session_order([A, B, C])
        km._session_order_lkg[0] = None                                # a cold start: nothing read yet
        with _reads_fault(self._path()):
            self.assertEqual(km._session_order(), [], "no known-good: the empty default, unproved")
            self.assertIsNone(km._session_order_lkg[0], "the fault's [] is NOT latched as the known-good")
        self.assertEqual(km._session_order(), [A, B, C], "the real order reads once the fault clears")

    def test_the_display_read_returns_a_copy_so_a_caller_cannot_mutate_the_known_good(self):
        km._write_session_order([A, B])
        got = km._session_order(); got.append(C)
        self.assertEqual(km._session_order_lkg[0], [A, B])


class OrderWsRefusal(unittest.TestCase):
    """The reorderTabs / writeOrder WS arm under a store fault: the order file is untouched, the
    poster gets a `settingRefused` frame on its own socket, nothing escapes _dispatch_ws."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self._saved = (km.jd.STATE, km._mark_views_dirty, km._session_order_lkg[0])
        km.jd.STATE = Path(self.td.name)
        self.dirty = []
        km._mark_views_dirty = lambda: self.dirty.append(1)

    def tearDown(self):
        km.jd.STATE, km._mark_views_dirty, km._session_order_lkg[0] = self._saved
        self.td.cleanup()

    def test_a_refused_drag_answers_the_poster_and_leaves_the_order_alone(self):
        km._write_session_order([A, B, C])
        p = km.jd.STATE / "session-order.json"
        before = p.read_bytes()
        sent = []
        client = {"app": "chat", "wid": "w1", "alive": True, "send": lambda raw: sent.append(json.loads(raw))}
        with _reads_fault(p):
            km.Handler._dispatch_ws(None, {"type": "reorderTabs", "order": [C, B]}, client)
        self.assertEqual(p.read_bytes(), before, "the order file is byte-for-byte unchanged (a fold-to-[] would have dropped A)")
        self.assertEqual(len(sent), 1)
        self.assertEqual((sent[0]["type"], sent[0]["gesture"], sent[0]["value"]), ("settingRefused", "order", None))
        self.assertIn("couldn't save the new order", sent[0]["text"])
        self.assertIn("session-order.json could not be read", sent[0]["text"])
        self.assertEqual(self.dirty, [])

    def test_a_clean_drag_still_lands(self):
        km._write_session_order([A, B, C])
        sent = []
        client = {"app": "chat", "wid": "w1", "alive": True, "send": lambda raw: sent.append(json.loads(raw))}
        km.Handler._dispatch_ws(None, {"type": "reorderTabs", "order": [C, B]}, client)
        self.assertEqual(sent, [])
        self.assertEqual(km._session_order_proved(), [A, C, B], "the drag merged: the untouched lane keeps its slot, the dragged pair reorders in place")
        self.assertEqual(self.dirty, [1])


class StateQuarantineShape(unittest.TestCase):
    """The quarantine wears the shape the goal-store and ledger quarantines wear: `<file>.corrupt-<utc
    stamp>` with a `-n` suffix for a second collision, an os.replace, and a same-file re-check
    (inode, mtime, size) before the move -- so an atomic publish that landed between the read and
    the rename is never moved aside, and bytes that cannot be moved leave the store UNREADABLE (a
    writer refuses) rather than read as empty over evidence that was not preserved."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self._saved_state = km.jd.STATE
        km.jd.STATE = Path(self.td.name)

    def tearDown(self):
        km.jd.STATE = self._saved_state
        self.td.cleanup()

    def _path(self):
        return km.jd.STATE / "session-order.json"

    def test_a_second_corrupt_file_in_the_same_second_gets_a_numbered_suffix(self):
        fixed = time.gmtime(1_800_000_000)
        with mock.patch.object(km.time, "gmtime", return_value=fixed):
            stamp = time.strftime("%Y%m%dT%H%M%SZ", fixed)
            first = self._path().with_name("session-order.json.corrupt-" + stamp)
            first.write_bytes(b"earlier corrupt bytes")
            torn = b'["aaaa", NOT JSON'
            self._path().write_bytes(torn)
            self.assertIsNone(km._read_state_json(self._path()))
        self.assertEqual(first.read_bytes(), b"earlier corrupt bytes", "the earlier quarantine is never overwritten")
        second = self._path().with_name("session-order.json.corrupt-" + stamp + "-1")
        self.assertEqual(second.read_bytes(), torn, "the collision takes the -1 suffix")
        self.assertFalse(self._path().exists())

    def test_a_file_republished_between_the_read_and_the_rename_is_not_moved_aside(self):
        # the torn bytes are read, and BEFORE the quarantine's rename an atomic publish replaces the
        # file with a good one (a writer on another thread): the re-check sees a different inode /
        # mtime / size and leaves the new file exactly where it is -- the caller gets a transient
        # UNREADABLE (its next read is a fresh one), never a good file quarantined
        good = json.dumps([A, B]).encode()
        p = self._path()
        p.write_bytes(b'["aaaa", NOT JSON')
        real_rb = Path.read_bytes
        def rb(self_, *a, **k):
            raw = real_rb(self_, *a, **k)
            if str(self_) == str(p):
                km._atomic_write(p, good.decode())                 # the publish lands after our read
            return raw
        Path.read_bytes = rb
        try:
            with self.assertRaises(km._StateUnreadable) as cm:
                km._read_state_json(p)
        finally:
            Path.read_bytes = real_rb
        self.assertIn("replaced meanwhile", str(cm.exception))
        self.assertEqual(p.read_bytes(), good, "the republished good file is untouched")
        self.assertEqual(list(km.jd.STATE.glob("session-order.json.corrupt-*")), [], "nothing was moved aside")
        self.assertEqual(km._read_state_json(p), [A, B], "the next read is a fresh, clean one")

    def test_bytes_that_cannot_be_moved_aside_leave_the_store_unreadable_not_empty(self):
        p = self._path()
        torn = b'["aaaa", NOT JSON'
        p.write_bytes(torn)
        with mock.patch.object(km.os, "replace", side_effect=PermissionError(errno.EACCES, "Permission denied")):
            with self.assertRaises(km._StateUnreadable) as cm:
                km._read_state_json(p)
            self.assertIn("could not be moved aside: [Errno 13] Permission denied", str(cm.exception))
            self.assertEqual(p.read_bytes(), torn, "the evidence stays in place; the store is not read as empty over it")
            with self.assertRaises(km._StateUnreadable):
                km._session_order_proved()                             # so a writer refuses, exactly as for an EIO
        self.assertEqual(p.read_bytes(), torn)

    def test_the_move_is_an_os_replace_and_the_fault_text_carries_no_stamp_or_path(self):
        # the fault text feeds the once-per-fault-text registries: a path or a per-second stamp in it
        # would defeat the dedupe (the ledgers' lesson), so it is errno + strerror only
        e = km._StateUnreadable(self._path(), "read failed: %s" % km._errno_text(OSError(errno.EIO, "Input/output error", "/some/where")))
        self.assertEqual(e.fault, "read failed: [Errno 5] Input/output error")
        self.assertNotIn("/some/where", str(e))
        with mock.patch.object(km.os, "replace", wraps=os.replace) as rep:
            self._path().write_bytes(b"{ not json")
            self.assertIsNone(km._read_state_json(self._path()))
        self.assertEqual(rep.call_count, 1, "the quarantine moves with os.replace, like its siblings")


if __name__ == "__main__":
    unittest.main()
