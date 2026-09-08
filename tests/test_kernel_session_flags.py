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
        km._sync_notice = lambda text, ok=True: self.notices.append((text, ok))

    def tearDown(self):
        km._sync_notice = self._notice
        jd.STATE = self.saved
        km._flags_cache.clear()
        km._state_fault_seen.clear()
        self.td.cleanup()

    def _path(self):
        return jd.STATE / "session-flags.json"

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
        bad = [t for t, ok in self.notices if not ok]
        self.assertEqual(len(bad), 1, "one notice per fault episode, however many builds read the store")
        self.assertIn("session-flags.json could not be read", bad[0])
        self.assertIn("[Errno 5]", bad[0])
        km._session_flags()                                            # the clean read ends the episode
        self.assertNotIn(str(self._path()), km._state_fault_seen)
        with _reads_fault(self._path()):
            km._flags_cache.clear()
            km._session_flags()
        self.assertEqual(len([t for t, ok in self.notices if not ok]), 2, "a fresh episode speaks again")


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
        km._sync_notice = lambda text, ok=True: self.notices.append((text, ok))

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

    def test_the_setter_raises_the_plain_exception_never_the_os_error(self):
        p = jd.STATE / "session-flags.json"
        with _writes_fault(p):
            with self.assertRaises(km._StateUnwritable) as cm:
                km._set_session_flag(self.SID, "hideFromFeed", True)
        self.assertNotIsInstance(cm.exception, OSError, "an OSError is what the receive loop reads as a dead socket")
        self.assertEqual(str(cm.exception), "session-flags.json could not be written (write failed: [Errno 28] No space left on device)")
        self.assertEqual((cm.exception.path.name, cm.exception.fault), ("session-flags.json", "write failed: [Errno 28] No space left on device"))
        self.assertFalse(p.exists(), "nothing was published")


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
