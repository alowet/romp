#!/usr/bin/env python3
"""Per-session view flags (the user 2026-06-19): a persisted {sid: {flag: true}} dict under STATE, set
from the timeline lane gear. The only flag today is hideFromFeed — a session whose prompts shouldn't mint
feed cards (it stays on the timeline). These pin the storage helpers + the web boot hook. Synthetic only."""
import os
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin")
# Hermetic state BEFORE the loads — they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
SourceFileLoader("romp_event_model", os.path.join(BIN, "romp-event-model")).load_module()
SourceFileLoader("romp_judge", os.path.join(BIN, "romp-judge")).load_module()
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
km = SourceFileLoader("romp_kernel_sf", os.path.join(BIN, "romp-kernel")).load_module()
# the kernel's helpers read/write jd.STATE; sandbox THAT module's STATE (the one the kernel actually uses)
jd = km.jd


class SessionFlags(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.saved = jd.STATE
        jd.STATE = Path(self.td.name)
        km._flags_cache.clear()

    def tearDown(self):
        jd.STATE = self.saved
        self.td.cleanup()

    def test_default_is_empty(self):
        self.assertEqual(km._session_flags(), {})
        self.assertFalse(km._session_flag("sid1", "hideFromFeed"))

    def test_set_get_then_unset_drops_the_entry(self):
        km._set_session_flag("sid1", "hideFromFeed", True)
        self.assertTrue(km._session_flag("sid1", "hideFromFeed"))
        self.assertEqual(km._session_flags(), {"sid1": {"hideFromFeed": True}})
        km._set_session_flag("sid1", "hideFromFeed", False)
        self.assertFalse(km._session_flag("sid1", "hideFromFeed"))
        self.assertEqual(km._session_flags(), {}, "removing the last flag drops the whole session entry")

    def test_sessions_are_independent(self):
        km._set_session_flag("a", "hideFromFeed", True)
        km._set_session_flag("b", "hideFromFeed", False)
        self.assertTrue(km._session_flag("a", "hideFromFeed"))
        self.assertFalse(km._session_flag("b", "hideFromFeed"))
        self.assertNotIn("b", km._session_flags(), "a never-set / cleared flag isn't persisted")

    def test_cache_invalidates_on_write(self):
        self.assertEqual(km._session_flags(), {})           # primes the (empty) read path
        km._set_session_flag("a", "hideFromFeed", True)     # changes the file
        self.assertTrue(km._session_flag("a", "hideFromFeed"), "the (mtime_ns,size) cache key sees the write")

    def test_unknown_flag_value_is_false(self):
        km._set_session_flag("a", "hideFromFeed", True)
        self.assertFalse(km._session_flag("a", "someFutureFlag"), "an unset flag reads False")

    def test_web_boot_exposes_the_set_flag_hook(self):
        # the timeline web page posts setSessionFlag via this host hook (kernel _TIMELINE_BOOT)
        self.assertIn("__rompTimelineSetFlag", km._TIMELINE_BOOT)
        self.assertIn("setSessionFlag", km._TIMELINE_BOOT)


class AutoNudgeWiring(unittest.TestCase):
    """The Auto Nudge toggle is a SERVER-SIDE behavior, so the feed gear posts setAutoNudge to the kernel
    and the checkbox reflects the kernel's state via /version (not localStorage) — the user 2026-06-19."""

    def test_gear_has_the_autonudge_toggle_posting_to_the_kernel(self):
        self.assertIn("rs-autonudge", _gear_src(), "the gear panel has an Auto Nudge checkbox")
        self.assertIn("Auto Nudge", _gear_src())
        self.assertIn("setAutoNudge", _gear_src(), "toggling posts the server-side message")

    def test_version_reports_autonudge_state_for_the_checkbox(self):
        saved = jd.STATE
        td = tempfile.TemporaryDirectory()
        jd.STATE = Path(td.name)
        km._autonudge_cache.clear()
        try:
            self.assertTrue(km._version_info()["autoNudge"], "on by default (no state file)")
            km._set_auto_nudge(False)
            self.assertFalse(km._version_info()["autoNudge"], "an explicit off is respected")
            km._set_auto_nudge(True)
            self.assertTrue(km._version_info()["autoNudge"], "the gear reads the kernel's authoritative state")
        finally:
            jd.STATE = saved
            td.cleanup()

    def test_default_on_even_when_state_file_lacks_the_key(self):
        saved = jd.STATE
        td = tempfile.TemporaryDirectory()
        jd.STATE = Path(td.name)
        km._autonudge_cache.clear()
        try:
            (Path(td.name) / "auto-nudge.json").write_text('{"nudged": {}}')  # present, no "enabled" key
            self.assertTrue(km._auto_nudge_on(), "a state file missing the enabled key still defaults on")
        finally:
            jd.STATE = saved
            td.cleanup()


class FlagsStoreUnreadableRefuses(unittest.TestCase):
    """The state-readers audit (rank 5): the session-flags reader used to fold ANY read fault to {}
    and CACHE it, so _set_session_flag copied that empty, applied one edit, and atomically wrote it
    back — erasing every session's flags (including the postalServiceOff isolation boundaries) under
    a silent success. The setters now read PROVED: a read fault refuses the write loudly and the
    file is left exactly as it was. Synthetic sids only."""
    SID = "11111111-2222-3333-4444-555555555555"
    OTHER = "99999999-8888-7777-6666-555555555555"

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.saved = jd.STATE
        jd.STATE = Path(self.td.name)
        km._flags_cache.clear()

    def tearDown(self):
        jd.STATE = self.saved
        km._flags_cache.clear()
        self.td.cleanup()

    def _path(self):
        return jd.STATE / "session-flags.json"

    def _fault_reads_of(self, target):
        """Fail BOTH read_bytes (the fix's proved reader) and read_text (origin/main's reader) for one
        path, so the same test injects the fault on either tree — green on the fix, RED on main where
        the fold-to-{} erases the flags."""
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

    def test_a_flag_toggle_is_refused_when_the_flags_store_cannot_be_read(self):
        # a populated store: the OTHER session is isolated from the postal bus — a safety boundary
        km._set_session_flag(self.OTHER, "postalServiceOff", True)
        km._flags_cache.clear()
        before = self._path().read_bytes()
        saved = self._fault_reads_of(self._path())
        raised = None
        try:
            km._set_session_flag(self.SID, "hideFromFeed", True)   # a fresh edit on another sid
        except Exception as e:                                     # noqa: BLE001 — on main it never raises
            raised = e
        finally:
            Path.read_bytes, Path.read_text = saved
        km._flags_cache.clear()
        # THE erasure the audit is about: on origin/main the read folds to {}, the setter writes
        # {SID:{hideFromFeed}} and the OTHER session's isolation boundary is GONE — this assertion is
        # what turns RED there. The fix refuses the write, so the file is byte-for-byte unchanged.
        self.assertEqual(self._path().read_bytes(), before,
                         "the flags file must be unchanged when its file can't be read (main erases it here)")
        self.assertTrue(km._session_flag(self.OTHER, "postalServiceOff"),
                        "the pre-existing isolation flag survives the refused toggle")
        self.assertEqual(type(raised).__name__, "_StateUnreadable",
                         "the write is refused LOUDLY, not folded to a fabricated empty (got %r)" % raised)

    def test_a_torn_flags_file_is_quarantined_aside_not_overwritten(self):
        torn = b'{"sid": {"hideFromFeed": true'
        self._path().write_bytes(torn)
        km._flags_cache.clear()
        self.assertEqual(km._session_flags_proved(), {}, "the store starts empty only after the bytes are saved")
        q = list(jd.STATE.glob("session-flags.json.corrupt-*"))
        self.assertEqual(len(q), 1)
        self.assertEqual(q[0].read_bytes(), torn, "the quarantine holds the ORIGINAL bytes")
        self.assertFalse(self._path().exists())

    def test_enoent_flags_still_reads_empty_with_no_quarantine(self):
        self.assertEqual(km._session_flags(), {}, "a missing store is legitimately empty")
        self.assertEqual(km._session_flags_proved(), {})
        self.assertEqual(list(jd.STATE.glob("session-flags.json.corrupt-*")), [])


import contextlib
import errno
import json
import shutil
import subprocess
from unittest import mock


@contextlib.contextmanager
def _stat_fault(target):
    """Fail every stat of ONE path with an EACCES for the duration of the block -- the arm the read-fault
    injector never reaches (review find, 2026-09-08): every reader stats BEFORE it reads (the display
    readers key their cache on it), and a state dir that cannot be searched faults exactly there.
    Everything else stats normally."""
    real_stat = Path.stat
    tgt = str(target)
    def st(self, *a, **k):
        if str(self) == tgt:
            raise OSError(errno.EACCES, "injected EACCES")
        return real_stat(self, *a, **k)
    Path.stat = st
    try:
        yield
    finally:
        Path.stat = real_stat


@contextlib.contextmanager
def _reads_fault(target):
    """Fail every byte read of ONE path with an EIO (the proved reader's read_bytes and the pre-fix
    reader's read_text alike) for the duration of the block; everything else reads normally."""
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


@contextlib.contextmanager
def _writes_fault(target):
    """Fail the PUBLISH of ONE state file with an ENOSPC for the duration of the block: _atomic_write
    writes `<name>.tmp.<pid>.<tid>.<n>` beside the file and renames it over, so failing every write_text
    of that shape is the disk refusing this file's publish while every other path, and every read, behaves."""
    real = Path.write_text
    prefix = Path(target).name + ".tmp."

    def wt(self, *a, **k):
        if self.name.startswith(prefix):
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(self, *a, **k)
    Path.write_text = wt
    try:
        yield
    finally:
        Path.write_text = real


class StateUnreadableIsAPlainException(unittest.TestCase):
    """The WS receive loop re-raises (BrokenPipeError, ConnectionResetError, OSError) as a genuine
    socket failure and tears the connection down; every other exception falls to its logging arm
    and the next message still processes. A store-read fault must be the second kind: one handler
    branch that forgets to catch it costs a logged line, never the dashboard's socket."""

    def test_it_is_an_exception_but_never_an_oserror(self):
        self.assertTrue(issubclass(km._StateUnreadable, Exception))
        self.assertFalse(issubclass(km._StateUnreadable, OSError),
                         "as an OSError the WS loop would classify a read fault as a socket failure")

    def test_it_names_the_file_and_the_fault_in_plain_words(self):
        e = km._StateUnreadable(Path("/tmp/x/session-flags.json"), "read failed: [Errno 5] Input/output error")
        self.assertEqual(str(e), "session-flags.json could not be read (read failed: [Errno 5] Input/output error)")
        self.assertEqual((e.path.name, e.fault), ("session-flags.json", "read failed: [Errno 5] Input/output error"))


class FlagsDisplayReaderServesUnproved(unittest.TestCase):
    """The DISPLAY reader under a fault: the last value this kernel read if it holds one, else {}
    -- and NEITHER is cached under the file's stat key. A reader that cached what a fault produced
    would keep serving it after the disk recovered (same key, a cache HIT never reads), which is how
    the pre-fix reader turned a transient EIO into a permanent empty."""
    SID = "11111111-2222-3333-4444-555555555555"
    OTHER = "99999999-8888-7777-6666-555555555555"

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.saved = jd.STATE
        jd.STATE = Path(self.td.name)
        km._flags_cache.clear()
        km._state_fault_seen.clear()
        self.notices = []
        self._notice = km._sync_notice
        km._sync_notice = lambda text, ok=True, kind="sync": self.notices.append((text, ok, kind))

    def tearDown(self):
        km._sync_notice = self._notice
        jd.STATE = self.saved
        km._flags_cache.clear()
        km._state_fault_seen.clear()
        self.td.cleanup()

    def _path(self):
        return jd.STATE / "session-flags.json"

    def test_a_stat_fault_serves_the_last_read_value_and_refuses_the_writers(self):
        # the STAT arm (review find, 2026-09-08: every injector faulted the read, so the reader's stat
        # arm and the proved reader's were unpinned -- reverting either to a silent `return {}` passed)
        km._set_session_flag(self.OTHER, "postalServiceOff", True)
        km._flags_cache.clear()
        self.assertEqual(km._session_flags(), {self.OTHER: {"postalServiceOff": True}})   # primes the cache
        key1 = km._flags_cache[str(self._path())][0]
        before = self._path().read_bytes()
        with _stat_fault(self._path()):
            self.assertEqual(km._session_flags(), {self.OTHER: {"postalServiceOff": True}},
                             "the stat arm serves the LAST value read, not {}")
            self.assertEqual(km._flags_cache[str(self._path())], (key1, {self.OTHER: {"postalServiceOff": True}}),
                             "and caches nothing new")
            with self.assertRaises(km._StateUnreadable) as cm:
                km._session_flags_proved()                              # the proved reader raises on the stat
            self.assertIn("stat failed: [Errno 13]", str(cm.exception))
            with self.assertRaises(km._StateUnreadable):
                km._set_session_flag(self.SID, "hideFromFeed", True)     # so a writer refuses
        self.assertEqual(self._path().read_bytes(), before, "the refused write left the file alone")
        bad = [t for t, ok, _k in self.notices if not ok]
        self.assertEqual(len(bad), 1, "one notice for the episode, from the display reader's stat arm")
        self.assertIn("stat failed: [Errno 13]", bad[0])
        km._flags_cache.clear()
        with _stat_fault(self._path()):
            self.assertEqual(km._session_flags(), {}, "a cold cache serves the empty default under a stat fault")
            self.assertNotIn(str(self._path()), km._flags_cache, "…uncached")

    def test_the_fault_notice_is_filed_under_the_refused_kind_not_sync(self):
        # review find, 2026-09-08: filed under the ring's default (sync) kind, the notice wore the
        # machine-sync label and a mute on that log silenced every disk-fault notice with it
        km._set_session_flag(self.OTHER, "postalServiceOff", True)
        km._flags_cache.clear()
        with _reads_fault(self._path()):
            km._session_flags()
        self.assertEqual([(ok, k) for _t, ok, k in self.notices], [(False, "refused")])

    def test_a_quarantine_tells_the_dashboard_once_under_the_refused_kind(self):
        # review find, 2026-09-08: a quarantine reset the store to empty with only a stderr line, so
        # from the dashboard every flag (postal isolation included) simply reset itself
        torn = b'{"' + self.OTHER.encode() + b'": {"postalServiceOff": tr'
        self._path().write_bytes(torn)
        self.assertEqual(km._session_flags_proved(), {})
        self.assertEqual(len(self.notices), 1, "one notice for the move")
        text, ok, kind = self.notices[0]
        self.assertEqual((ok, kind), (False, "refused"))
        self.assertIn("session-flags.json could not be parsed and was moved aside to session-flags.json.corrupt-", text)
        self.assertIn("start over empty", text)
        aside = list(jd.STATE.glob("session-flags.json.corrupt-*"))
        self.assertEqual(len(aside), 1)
        self.assertIn(aside[0].name, text, "the notice names the sidecar, so the bytes can be found")
        self.assertEqual(km._session_flags_proved(), {})                # the next read is an ENOENT …
        self.assertEqual(len(self.notices), 1, "… and files nothing more: a corrupt file speaks exactly once")

    def test_valid_json_of_the_wrong_shape_is_quarantined_not_read_as_empty(self):
        # review find, 2026-09-08: a LIST where the flags dict belongs read as a proved empty store and
        # was overwritten by the next writer -- a file none of our writers produce, gone without a trace
        wrong = b'["' + self.OTHER.encode() + b'"]'
        self._path().write_bytes(wrong)
        self.assertEqual(km._session_flags_proved(), {}, "empty only AFTER the bytes are moved aside")
        aside = list(jd.STATE.glob("session-flags.json.corrupt-*"))
        self.assertEqual(len(aside), 1, "quarantined like torn bytes")
        self.assertEqual(aside[0].read_bytes(), wrong)
        self.assertFalse(self._path().exists())
        self.assertEqual([k for _t, _ok, k in self.notices], ["refused"])
        self._path().write_bytes(wrong)
        km._flags_cache.clear()
        self.assertEqual(km._session_flags(), {}, "the display reader quarantines it the same way")
        self.assertEqual(len(list(jd.STATE.glob("session-flags.json.corrupt-*"))), 2)

    def test_a_fault_serves_the_last_read_value_and_caches_nothing_new(self):
        km._set_session_flag(self.OTHER, "postalServiceOff", True)
        km._flags_cache.clear()
        first = km._session_flags()                                    # a clean read primes the cache
        key1 = km._flags_cache[str(self._path())][0]
        self.assertEqual(first, {self.OTHER: {"postalServiceOff": True}})
        # the file moves on (a second session's flag lands), so the stat key changes and the next
        # read is a MISS -- a primed cache under the same key would be a hit and never read at all
        km._set_session_flag(self.SID, "hideFromFeed", True)
        key2 = self._path().stat(); key2 = (key2.st_mtime_ns, key2.st_size)
        self.assertNotEqual(key1, key2, "the write must move the stat key, or this test reads nothing")
        with _reads_fault(self._path()):
            served = km._session_flags()
            self.assertEqual(served, {self.OTHER: {"postalServiceOff": True}},
                             "the fault serves the LAST value this kernel read, not the unread file and not {}")
            self.assertEqual(km._flags_cache[str(self._path())][0], key1,
                             "nothing is cached under the NEW key -- the fault produced no value worth keeping")
        # the disk recovers: the reader reads the real, newer file (a reader that had cached the
        # fault's value under key2 would serve the stale copy here forever)
        self.assertEqual(km._session_flags(), {self.OTHER: {"postalServiceOff": True}, self.SID: {"hideFromFeed": True}})

    def test_a_fault_on_a_cold_cache_serves_the_empty_default_uncached(self):
        km._set_session_flag(self.OTHER, "postalServiceOff", True)
        km._flags_cache.clear()
        with _reads_fault(self._path()):
            self.assertEqual(km._session_flags(), {}, "no known-good yet: the empty default, unproved")
            self.assertNotIn(str(self._path()), km._flags_cache, "…and it is NOT cached")
        self.assertEqual(km._session_flags(), {self.OTHER: {"postalServiceOff": True}},
                         "the real flags read once the fault clears -- the empty was never latched")

    def test_the_fault_is_loud_once_per_episode_and_a_clean_read_rearms_it(self):
        km._set_session_flag(self.OTHER, "postalServiceOff", True)
        km._flags_cache.clear()
        with _reads_fault(self._path()):
            km._session_flags(); km._session_flags(); km._session_flags()
        bad = [t for t, ok, _k in self.notices if not ok]
        self.assertEqual(len(bad), 1, "one notice per fault episode, however many builds read the store")
        self.assertIn("session-flags.json could not be read", bad[0])
        self.assertIn("[Errno 5]", bad[0])
        km._session_flags()                                            # the clean read ends the episode
        self.assertNotIn(str(self._path()), km._state_fault_seen)
        with _reads_fault(self._path()):
            km._flags_cache.clear()
            km._session_flags()
        self.assertEqual(len([t for t, ok, _k in self.notices if not ok]), 2, "a fresh episode speaks again")


class FlagsWsRefusal(unittest.TestCase):
    """The setSessionFlag WS arm under a store fault: the file is untouched, the poster gets a
    `settingRefused` frame addressed to its toggle (sid + flag) on its OWN socket, and nothing
    escapes _dispatch_ws. A `warn` frame did not reach the timeline page (no handler) so the lane
    gear kept showing the refused state until a reload."""
    SID = "11111111-2222-3333-4444-555555555555"
    OTHER = "99999999-8888-7777-6666-555555555555"

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.saved = (jd.STATE, km._mark_views_dirty)
        jd.STATE = Path(self.td.name)
        km._flags_cache.clear()
        self.dirty = []
        km._mark_views_dirty = lambda: self.dirty.append(1)

    def tearDown(self):
        jd.STATE, km._mark_views_dirty = self.saved
        km._flags_cache.clear()
        self.td.cleanup()

    def _client(self):
        sent = []
        return {"app": "timeline", "wid": "w1", "alive": True,
                "send": lambda raw: sent.append(json.loads(raw))}, sent

    def test_a_refused_toggle_answers_the_poster_and_leaves_the_file_alone(self):
        km._set_session_flag(self.OTHER, "postalServiceOff", True)
        km._flags_cache.clear()
        p = jd.STATE / "session-flags.json"
        before = p.read_bytes()
        for flag in ("hideFromFeed", "notify"):                       # both arms of the branch: the plain setter and the tri-state bell
            client, sent = self._client()
            with _reads_fault(p):
                km.Handler._dispatch_ws(None, {"type": "setSessionFlag", "id": self.SID, "flag": flag, "value": True}, client)
            self.assertEqual(p.read_bytes(), before, "%s: the flags file is byte-for-byte unchanged" % flag)
            self.assertEqual(len(sent), 1, "%s: exactly one frame, on the delivering socket" % flag)
            fr = sent[0]
            self.assertEqual((fr["type"], fr["sid"], fr["flag"], fr["itemId"]), ("settingRefused", self.SID, flag, ""))
            self.assertEqual(fr["gesture"], "flag", "the frame names its gesture; no pane infers it from empty fields")
            self.assertIs(fr["value"], False, "the value the kernel still paints for this flag rides along (here: unset -> off)")
            self.assertIn("couldn't save that setting", fr["text"])
            self.assertIn("session-flags.json could not be read", fr["text"])
            self.assertNotIn("warn", fr["type"])
        self.assertEqual(self.dirty, [], "a refused write marks nothing dirty -- there is nothing new to push")

    def test_a_clean_toggle_still_lands_and_sends_no_refusal(self):
        client, sent = self._client()
        km.Handler._dispatch_ws(None, {"type": "setSessionFlag", "id": self.SID, "flag": "hideFromFeed", "value": True}, client)
        self.assertEqual(sent, [], "no frame on success -- the next push carries the value")
        self.assertTrue(km._session_flag(self.SID, "hideFromFeed"))
        self.assertEqual(self.dirty, [1])

    def test_a_refusal_carries_the_painted_value_when_it_is_on(self):
        # `value` is what the display path still PAINTS, so the pane repaints a refused toggle to it. Every
        # other case here paints off (review find, 2026-09-08: a constant False survived), so this one
        # paints ON for both arms: the flag is set, and the master is on (the bell's default with no
        # override). The file then moves on (a new stat key) so the faulted read is a real miss served
        # from the primed cache, not a cache hit
        km._set_session_flag(self.SID, "hideFromFeed", True)
        km._set_notify_all(True)
        km._flags_cache.clear(); km._notify_cards_cache.clear()
        km._session_flags(); km._notify_cards()                         # prime the display caches
        km._set_session_flag(self.OTHER, "postalServiceOff", True)       # bump the flags file's stat key
        p = jd.STATE / "session-flags.json"
        before = p.read_bytes()
        for flag in ("hideFromFeed", "notify"):
            client, sent = self._client()
            with _reads_fault(p):
                km.Handler._dispatch_ws(None, {"type": "setSessionFlag", "id": self.SID, "flag": flag, "value": False}, client)
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0]["gesture"], "flag")
            self.assertIs(sent[0]["value"], True, "%s: the kernel still paints ON, and the frame says so" % flag)
        self.assertEqual(p.read_bytes(), before)


class SessionBellJudgedAgainstAProvedMaster(unittest.TestCase):
    """_set_notify_session judges the click against the MASTER bell, which lives in the OTHER store
    (notify-cards.json). Read through the display reader, a fault there folded the master to off, so a
    click matching that fabricated master popped the session's stored override and rewrote
    session-flags.json without it -- the user's mute erased under the success path. The master is read
    PROVED now: a fault on the bells file refuses the flags write exactly like a fault on the flags file."""
    SID = "11111111-2222-3333-4444-555555555555"

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.saved = (jd.STATE, km._mark_views_dirty)
        jd.STATE = Path(self.td.name)
        km._flags_cache.clear(); km._notify_cards_cache.clear()
        self.dirty = []
        km._mark_views_dirty = lambda: self.dirty.append(1)

    def tearDown(self):
        jd.STATE, km._mark_views_dirty = self.saved
        km._flags_cache.clear(); km._notify_cards_cache.clear()
        self.td.cleanup()

    def test_a_session_bell_click_is_refused_when_the_bells_store_cannot_be_read(self):
        km._set_notify_all(True)                                   # the master is ON …
        km._set_notify_session(self.SID, False)                    # … and this session is MUTED (a stored override)
        km._flags_cache.clear(); km._notify_cards_cache.clear()
        flags_p, cards_p = jd.STATE / "session-flags.json", jd.STATE / "notify-cards.json"
        self.assertEqual(json.loads(flags_p.read_text()), {self.SID: {"notify": False}})
        before = flags_p.read_bytes()
        raised = None
        with _reads_fault(cards_p):                                # the OTHER store faults
            try:
                km._set_notify_session(self.SID, False)            # the user clicks mute again (or the pane re-sends it)
            except Exception as e:                                 # noqa: BLE001 -- before the fix it never raises
                raised = e
        # before the fix: the master folded to off, False == off, the override was POPPED and the flags file
        # rewritten as {} -- the mute gone. Now the write is refused and the file is byte-for-byte unchanged.
        self.assertEqual(flags_p.read_bytes(), before, "the flags file must be unchanged when the bells file can't be read")
        self.assertEqual(type(raised).__name__, "_StateUnreadable", "refused loudly (got %r)" % raised)
        self.assertIn("notify-cards.json", str(raised), "the refusal names the store that faulted")

    def test_the_ws_arm_refuses_a_session_bell_on_the_other_store_s_fault(self):
        km._set_notify_all(True); km._set_notify_session(self.SID, False)
        km._flags_cache.clear(); km._notify_cards_cache.clear()
        flags_p, cards_p = jd.STATE / "session-flags.json", jd.STATE / "notify-cards.json"
        before = flags_p.read_bytes()
        sent = []
        client = {"app": "timeline", "wid": "w1", "alive": True, "send": lambda raw: sent.append(json.loads(raw))}
        with _reads_fault(cards_p):
            km.Handler._dispatch_ws(None, {"type": "setSessionFlag", "id": self.SID, "flag": "notify", "value": False}, client)
        self.assertEqual(flags_p.read_bytes(), before)
        self.assertEqual(len(sent), 1)
        self.assertEqual((sent[0]["type"], sent[0]["gesture"], sent[0]["flag"]), ("settingRefused", "flag", "notify"))
        self.assertIn("notify-cards.json could not be read", sent[0]["text"])
        self.assertEqual(self.dirty, [])


class FlagsWsWriteFailure(unittest.TestCase):
    """The setSessionFlag WS arm when the store READS but its PUBLISH fails (ENOSPC, EROFS, EACCES): the
    maintainer's fold on PR #1019 -- a user gesture's WRITE step is a fault boundary too. Before, the arm
    caught only _StateUnreadable, so the OSError out of _atomic_write escaped _dispatch_ws to the receive
    loop, which re-raises any OSError as a socket failure: the dashboard was DROPPED without a word. Now
    the publish raises _StateUnwritable, the arm answers the same settingRefused frame ("could not be
    written"), the file is untouched, the fault is filed once per episode on the path's registry, and a
    landed write ends the episode."""
    SID = "11111111-2222-3333-4444-555555555555"
    OTHER = "99999999-8888-7777-6666-555555555555"

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.saved = (jd.STATE, km._mark_views_dirty, km._sync_notice)
        jd.STATE = Path(self.td.name)
        km._flags_cache.clear(); km._notify_cards_cache.clear(); km._state_fault_seen.clear()
        vars(km).get("_state_write_fault_seen", {}).clear()
        self.dirty, self.notices = [], []
        km._mark_views_dirty = lambda: self.dirty.append(1)
        km._sync_notice = lambda text, ok=True, kind="sync": self.notices.append((text, ok))

    def tearDown(self):
        jd.STATE, km._mark_views_dirty, km._sync_notice = self.saved
        km._flags_cache.clear(); km._notify_cards_cache.clear(); km._state_fault_seen.clear()
        vars(km).get("_state_write_fault_seen", {}).clear()
        self.td.cleanup()

    def _client(self):
        sent = []
        return {"app": "timeline", "wid": "w1", "alive": True, "send": lambda raw: sent.append(json.loads(raw))}, sent

    def test_a_failed_publish_answers_the_poster_instead_of_dropping_the_socket(self):
        km._set_session_flag(self.OTHER, "postalServiceOff", True)
        km._flags_cache.clear()
        p = jd.STATE / "session-flags.json"
        before = p.read_bytes()
        with _writes_fault(p):
            for flag in ("hideFromFeed", "notify"):                   # the plain setter and the tri-state bell
                client, sent = self._client()
                try:
                    km.Handler._dispatch_ws(None, {"type": "setSessionFlag", "id": self.SID, "flag": flag, "value": True}, client)
                except OSError:
                    self.fail("%s: the OSError escaped _dispatch_ws -- the receive loop re-raises it and drops the client" % flag)
                self.assertTrue(client["alive"])
                self.assertEqual(p.read_bytes(), before, "%s: the flags file is byte-for-byte unchanged" % flag)
                self.assertEqual(len(sent), 1, "%s: exactly one frame, on the delivering socket" % flag)
                fr = sent[0]
                self.assertEqual((fr["type"], fr["gesture"], fr["sid"], fr["flag"]), ("settingRefused", "flag", self.SID, flag))
                self.assertIn("couldn't save that setting", fr["text"])
                self.assertIn("session-flags.json could not be written", fr["text"])
                self.assertIn("No space left on device", fr["text"])
                self.assertNotIn(".tmp.", fr["text"], "errno + strerror only, never the temp path")
                self.assertIs(fr["value"], False, "the value the kernel still paints rides along")
        self.assertEqual(self.dirty, [], "a refused write marks nothing dirty")
        self.assertEqual(len([t for t, ok in self.notices if not ok]), 1, "the fault is filed ONCE per episode, not per click")
        self.assertIn("could not be written", self.notices[0][0])
        self.assertIn("not saved", self.notices[0][0])
        # the disk heals: the next click lands, ends the episode, and a fresh fault speaks again
        client, sent = self._client()
        km.Handler._dispatch_ws(None, {"type": "setSessionFlag", "id": self.SID, "flag": "hideFromFeed", "value": True}, client)
        self.assertEqual(sent, [])
        self.assertTrue(km._session_flag(self.SID, "hideFromFeed"))
        self.assertNotIn(str(p), km._state_write_fault_seen, "a landed write ends the episode")
        with _writes_fault(p):
            client, sent = self._client()
            km.Handler._dispatch_ws(None, {"type": "setSessionFlag", "id": self.SID, "flag": "hideFromFeed", "value": False}, client)
        self.assertEqual([m["type"] for m in sent], ["settingRefused"])
        self.assertEqual(len([t for t, ok in self.notices if not ok]), 2, "a new episode is filed again")
        self.assertTrue(km._session_flag(self.SID, "hideFromFeed"), "nothing applied: the store keeps the value")

    def test_a_failed_rename_refuses_the_same_way_and_leaves_no_temp_behind(self):
        # the publish's OTHER fault point (review find, 2026-09-08): the temp WROTE, and the rename over
        # the live file failed (EACCES on the directory, EROFS). The same refusal on the socket, and
        # _atomic_write's unlink means the failed publish leaves no `<name>.tmp.*` beside the store
        km._set_session_flag(self.OTHER, "postalServiceOff", True)
        km._flags_cache.clear()
        p = jd.STATE / "session-flags.json"
        before = p.read_bytes()
        client, sent = self._client()
        with mock.patch.object(km.os, "replace", side_effect=PermissionError(errno.EACCES, "Permission denied")):
            km.Handler._dispatch_ws(None, {"type": "setSessionFlag", "id": self.SID, "flag": "hideFromFeed", "value": True}, client)
        self.assertTrue(client["alive"])
        self.assertEqual(p.read_bytes(), before)
        self.assertEqual([m["type"] for m in sent], ["settingRefused"])
        self.assertIn("session-flags.json could not be written (write failed: [Errno 13] Permission denied)", sent[0]["text"])
        self.assertEqual(list(jd.STATE.glob("session-flags.json.tmp.*")), [], "the failed publish left no temp behind")

    def test_the_setter_raises_the_plain_exception_never_the_os_error(self):
        p = jd.STATE / "session-flags.json"
        with _writes_fault(p):
            with self.assertRaises(km._StateUnwritable) as cm:
                km._set_session_flag(self.SID, "hideFromFeed", True)
        self.assertNotIsInstance(cm.exception, OSError, "an OSError is what the receive loop reads as a dead socket")
        self.assertEqual(str(cm.exception), "session-flags.json could not be written (write failed: [Errno 28] No space left on device)")
        self.assertEqual((cm.exception.path.name, cm.exception.fault), ("session-flags.json", "write failed: [Errno 28] No space left on device"))
        self.assertFalse(p.exists(), "nothing was published")


class SyncNoticeRowsCarryAKind(unittest.TestCase):
    """The ring the shell's bell mirrors carries each row's KIND (review find, 2026-09-08): "sync" by
    default (a machine sync, the ring's original tenant), "refused" for a state-file fault or a
    quarantine, so the shell files the two apart and a mute on one never hides the other."""

    def setUp(self):
        self._ring, self._seq = list(km._SYNC_NOTICES), km._SYNC_SEQ

    def tearDown(self):
        km._SYNC_NOTICES[:] = self._ring
        km._SYNC_SEQ = self._seq

    def test_the_default_is_sync_and_a_fault_files_refused(self):
        km._sync_notice("pushed this machine's build to TESTHOST")
        self.assertEqual(km._sync_notice_rows()[-1]["kind"], "sync")
        km._sync_notice("a fault", ok=False, kind="refused")
        row = km._sync_notice_rows()[-1]
        self.assertEqual((row["kind"], row["ok"]), ("refused", False))
        km._state_fault_seen.clear(); km._state_write_fault_seen.clear()
        km._note_state_fault(km._StateUnreadable(Path("/x/session-flags.json"), "read failed: [Errno 5] Input/output error"))
        row = km._sync_notice_rows()[-1]
        self.assertEqual(row["kind"], "refused", "the display-read fault reaches the bell under its own kind")
        self.assertIn("session-flags.json could not be read", row["text"])
        km._note_state_fault(km._StateUnwritable(Path("/x/session-flags.json"), "write failed: [Errno 28] No space left on device"))
        km._state_fault_seen.clear(); km._state_write_fault_seen.clear()
        row = km._sync_notice_rows()[-1]
        self.assertEqual(row["kind"], "refused", "and so does a write fault")
        self.assertIn("session-flags.json could not be written", row["text"])


NODE = shutil.which("node")
VIEW_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "ui", "romp-timeline-view.js")

# The timeline's Obsidian-desktop fallback writer of session-flags.json, executed in node with a stubbed
# fs (the tests/test_timeline_touch.py harness shape). Synthetic sids; ROMP_STATE_DIR is a temp dir and fs
# is stubbed besides, so no real file is ever touched.
_WRITER_HARNESS = r"""
const { TimelinePanel } = require(process.argv[1]);
const fs = require('fs'), path = require('path');
process.env.ROMP_STATE_DIR = process.argv[2];
const fp = path.join(process.argv[2], 'session-flags.json');
const SID = '11111111-2222-3333-4444-555555555555', OTHER = '99999999-8888-7777-6666-555555555555';
const real = { readFileSync: fs.readFileSync, writeFileSync: fs.writeFileSync, renameSync: fs.renameSync, mkdirSync: fs.mkdirSync };
function run(readImpl) {
  const writes = [], renames = [];
  fs.readFileSync = function (p) { if (String(p) === fp) return readImpl(); return real.readFileSync.apply(fs, arguments); };
  fs.writeFileSync = function (p, data) { writes.push([String(p), String(data)]); };
  fs.renameSync = function (a, b) { renames.push([String(a), String(b)]); };
  fs.mkdirSync = function () {};
  try {
    const v = Object.create(TimelinePanel.prototype);
    v._setSessionFlag({ id: SID }, 'hideFromFeed', true);
  } finally { Object.assign(fs, real); }
  return { writes, renames };
}
const err = (code) => Object.assign(new Error(code), { code });
const r = {};
process.versions.electron = '1.0.0-test';                   // the Electron guard: the writer runs at all
r.eio = run(() => { throw err('EIO'); });                   // a read fault
r.torn = run(() => '{"' + OTHER + '": {"postalServiceOff": tr');   // torn bytes
r.list = run(() => '["' + OTHER + '"]');                   // valid JSON of the wrong shape
r.enoent = run(() => { throw err('ENOENT'); });             // a legitimately missing store
r.clean = run(() => JSON.stringify({ [OTHER]: { postalServiceOff: true } }));
delete process.versions.electron;
r.noElectron = run(() => { throw err('ENOENT'); });         // a bare-node run: nothing at all
process.stdout.write(JSON.stringify({ fp, ...r }));
"""


@unittest.skipUnless(NODE, "node not available")
class TimelineFallbackFlagWriter(unittest.TestCase):
    """The timeline's Obsidian-desktop fallback writer of session-flags.json (review find, 2026-09-08)
    had the exact shape the kernel dropped: any read fault or torn bytes became {} and was written over
    EVERY session's flags, in place -- so the kernel's strict reader could observe 0 bytes mid-write
    and quarantine the very file being written. It now refuses on anything but a missing file, and
    publishes tmp + rename, like _persistOrder."""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        out = subprocess.run([NODE, "-e", _WRITER_HARNESS, VIEW_JS, cls.td.name],
                             capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise RuntimeError(out.stderr)
        cls.r = json.loads(out.stdout)

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_a_read_fault_torn_bytes_or_the_wrong_shape_write_nothing(self):
        for case in ("eio", "torn", "list"):
            self.assertEqual(self.r[case]["writes"], [], "%s: never written over a store that could not be read" % case)
            self.assertEqual(self.r[case]["renames"], [], case)

    def test_a_missing_store_is_written_atomically(self):
        fp = self.r["fp"]
        writes, renames = self.r["enoent"]["writes"], self.r["enoent"]["renames"]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][0], fp + ".tmp", "the bytes go to the temp, never the live file")
        self.assertEqual(json.loads(writes[0][1]), {"11111111-2222-3333-4444-555555555555": {"hideFromFeed": True}})
        self.assertEqual(renames, [[fp + ".tmp", fp]], "one atomic publish")

    def test_a_clean_read_keeps_the_other_sessions_flags(self):
        writes = self.r["clean"]["writes"]
        self.assertEqual(json.loads(writes[0][1]), {"99999999-8888-7777-6666-555555555555": {"postalServiceOff": True},
                                                    "11111111-2222-3333-4444-555555555555": {"hideFromFeed": True}})

    def test_without_electron_nothing_is_touched(self):
        self.assertEqual((self.r["noElectron"]["writes"], self.r["noElectron"]["renames"]), ([], []))


if __name__ == "__main__":
    unittest.main()


# The gear moved from kernel-inline strings into the shared feed bundle
# (2026-07-13): ui/webview/gear.js is the single source both hosts render, so
# the gear pins read THAT file (and feed.css for its styling).
def _gear_src():
    import pathlib
    return (pathlib.Path(__file__).resolve().parent.parent / "ui" / "webview" / "gear.js").read_text()


def _gear_css_src():
    import pathlib
    return (pathlib.Path(__file__).resolve().parent.parent / "ui" / "webview" / "gear.css").read_text()
