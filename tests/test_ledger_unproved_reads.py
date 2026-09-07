#!/usr/bin/env python3
"""The auto-nudge ledger is never rewritten from a fabricated default after a read fault (2026-09-07).

auto-nudge.json has one reader (_auto_nudge_data) and one writer (_write_auto_nudge) with some twenty
read-modify-write sites between them — `d = dict(_auto_nudge_data()); d[k] = v; _write_auto_nudge(d)`.
The reader used to answer ANY fault — a stat or read error, bytes that did not parse — with the
fresh-install default {"enabled": True, "nudged": {}} and cache it under the file's real stat key, so the
next writer persisted it: after one EIO every stalled goal in every session was nudged again (the dedupe
map read as empty) and an explicit auto-nudge OFF came back ON.

Now only a MISSING file reads as the default — that IS the fresh-install state. Every other fault yields a
snapshot tagged "_unproved" (a copy of the last one this process proved, else the default) that the writer
refuses, loud once per fault episode; nothing unproved is cached, so the file's next successful read ends
the episode. Bytes that do not parse are moved aside as auto-nudge.json.corrupt-<utc stamp> (evidence
kept) and the ledger then reads as absent. The nudge pass's stand-down rides the same tag and is pinned
where the firing fixture lives (tests/test_wake_deadman_toggle.py); the interrupt→blocked tick, which runs
outside that pass, is pinned here; the retry-suppress ledger takes the same shape in
tests/test_session_retry_suppress.py.

Synthetic fixtures only: a placeholder sid, invented goal ids, a temp state root."""
import contextlib
import errno
import io
import json
import os
import tempfile
import time
import unittest
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
km = SourceFileLoader("romp_kernel_ledger_unproved", os.path.join(BIN, "romp-kernel")).load_module()
jd = km.jd

SID = "11111111-2222-3333-4444-555555555555"
GID = SID + ":g1"
DEFAULT = {"enabled": True, "nudged": {}}
SEEDED = {"enabled": False, "nudged": {GID: {"count": 2, "lastTurnId": "t7"}}}   # an explicit OFF + a dedupe record
EIO = OSError(errno.EIO, "Input/output error")
# Spelled out, not km.UNPROVED: a kernel without the fix has no such name, and these tests must fail
# there on the DEFECT (a rewritten file, a fired message), never on an AttributeError in the fixture.
UNPROVED = "_unproved"
REGISTRIES = ("_ledger_fault_warned", "_ledger_refusal_warned")   # the once-per-episode registries


def _reset_ledger_state():
    km._autonudge_cache.clear()
    for reg in REGISTRIES:                       # absent on a kernel before the fix (see UNPROVED above)
        vars(km).get(reg, {}).clear()
    vars(km).get("_auto_nudge_paused", [None])[0] = None


def _fail_path(target, method, exc):
    """Path.<method> raises `exc` for `target` only; every other path behaves as before. Returns the undo."""
    real = getattr(Path, method)

    def failing(p, *a, **k):
        if str(p) == str(target):
            raise exc
        return real(p, *a, **k)
    setattr(Path, method, failing)
    return lambda: setattr(Path, method, real)


class _Ledger(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.saved_state = jd.STATE
        jd.STATE = Path(self.td.name)
        self.p = jd.STATE / "auto-nudge.json"
        self._undo = []
        _reset_ledger_state()

    def tearDown(self):
        self._heal()
        _reset_ledger_state()
        jd.STATE = self.saved_state
        self.td.cleanup()

    def _seed(self, d=SEEDED):
        self.p.write_text(json.dumps(d))
        km._autonudge_cache.clear()
        return self.p.read_bytes()

    def _fail(self, method, exc=EIO):
        self._undo.append(_fail_path(self.p, method, exc))

    def _heal(self):
        for undo in reversed(self._undo):
            undo()
        self._undo = []

    def _aside(self):
        return sorted(n for n in os.listdir(jd.STATE) if n.startswith("auto-nudge.json.corrupt-"))


class FreshInstall(_Ledger):
    def test_a_missing_file_reads_as_the_default_with_no_log_and_no_quarantine(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            d = km._auto_nudge_data()
        self.assertEqual(d, DEFAULT)
        self.assertNotIn(UNPROVED, d, "absent is the one fault that IS the default — a proved read")
        self.assertEqual(err.getvalue(), "", "a fresh install is not an incident")
        self.assertEqual(os.listdir(jd.STATE), [], "nothing moved aside, nothing created")
        self.assertEqual(km._autonudge_cache, {}, "absent is not cached — the old arm, byte for byte")
        km._mark_auto_nudged(GID, "t1", 1)
        self.assertEqual(json.loads(self.p.read_text())["nudged"][GID]["count"], 1,
                         "…and the first RMW writes the ledger, as it always did")


class ReadFault(_Ledger):
    def test_an_ordinary_rmw_after_a_read_fault_leaves_the_file_unchanged(self):
        # THE defect: the reader fabricated the default on EIO, cached it under the file's real stat key,
        # and the next writer persisted it — flipping the OFF to ON and erasing the dedupe record.
        before = self._seed()
        self._fail("read_text")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            applied = km._set_auto_nudge(True, gt=1_700_000_000_000)
            applied2 = km._set_compact_suggest(True, gt=1_700_000_000_000)
            km._mark_auto_nudged(GID + "x", "t9", 1)
        self._heal()
        self.assertEqual(self.p.read_bytes(), before, "the file on disk is byte for byte what it was")
        self.assertIsNone(applied, "a refused write reports not-applied, like a failed write")
        self.assertIsNone(applied2, "…the compaction-suggestion toggle too (the same blob, the same writer)")
        self.assertEqual(err.getvalue().count("refusing to write auto-nudge.json"), 1,
                         "one refusal line per fault episode — not one per write, not one per tick")
        self.assertIn("Input/output error", err.getvalue(), "the line names the fault")
        self.assertEqual(km._autonudge_cache, {}, "nothing unproved is cached")

    def test_a_stat_fault_is_unproved_too(self):
        # the old stat arm returned the default for ANY OSError; only ENOENT means absent
        before = self._seed()
        self._fail("stat")
        with contextlib.redirect_stderr(io.StringIO()):
            d = km._auto_nudge_data()
            km._mark_auto_nudged(GID + "x", "t9", 1)
        self._heal()
        self.assertEqual(self.p.read_bytes(), before)
        self.assertTrue(str(d.get(UNPROVED, "")).startswith("stat failed"))

    def test_the_snapshot_is_a_copy_of_the_last_proved_one_tagged_with_the_fault(self):
        self._seed()
        proved = km._auto_nudge_data()                     # a proved read fills the cache
        self.assertFalse(proved["enabled"])
        self.p.write_text(json.dumps(DEFAULT))             # the file moves on (a different size → a new key)…
        self._fail("read_text")                            # …and the new bytes cannot be read
        with contextlib.redirect_stderr(io.StringIO()):
            d = km._auto_nudge_data()
        self.assertFalse(d["enabled"], "the last snapshot this process proved — not the fabricated default")
        self.assertIn(GID, d["nudged"])
        self.assertTrue(str(d.get(UNPROVED, "")).startswith("read failed"))
        d["scratch"] = 1
        self.assertNotIn("scratch", proved, "a copy: no site can poison the proved snapshot through it")
        self.assertIs(km._autonudge_cache[str(self.p)][1], proved, "the cache still holds the proved one")
        self.assertFalse(km._write_auto_nudge(dict(d)), "the writer refuses a snapshot wearing the tag")
        km._autonudge_cache.clear()                        # no proved snapshot at all (a fault at boot):
        with contextlib.redirect_stderr(io.StringIO()):
            d2 = km._auto_nudge_data()
        self.assertEqual({k: v for k, v in d2.items() if k != UNPROVED}, DEFAULT,
                         "readers get the default to display — tagged, so no writer may persist it")
        self.assertIn(UNPROVED, d2)

    def test_the_reader_and_the_writer_shout_once_per_fault_episode(self):
        # keyed on the fault TEXT, reset by EVERY proved state — a write, a read, a cache hit, absence —
        # so a disk that stays broken says so once, and the SAME fault returning after a heal says so again
        self._seed()
        err = io.StringIO()

        def episode(n, method="read_text"):
            if method == "read_text":
                km._autonudge_cache.clear()                # the file must actually be read (no cache hit)
            self._fail(method)
            with contextlib.redirect_stderr(err):
                for _ in range(3):
                    km._auto_nudge_data()
                    km._mark_auto_nudged(GID + "y", "t1", 1)
            self._heal()
            self.assertEqual(err.getvalue().count("auto-nudge.json is unreadable"), n, "the reader: once per episode")
            self.assertEqual(err.getvalue().count("refusing to write"), n, "the writer: once per episode")
        episode(1)
        with contextlib.redirect_stderr(err):
            km._mark_auto_nudged(GID + "y", "t1", 1)       # healed: a proved RMW lands, quietly…
        self.assertIn(GID + "y", json.loads(self.p.read_text())["nudged"])
        episode(2)                                         # …and ended the episode: the same text shouts again
        with contextlib.redirect_stderr(err):
            km._auto_nudge_data()                          # healed: a proved READ alone, no write…
        episode(3)                                         # …ends the episode too (both registries, not just the reader's)
        with contextlib.redirect_stderr(err):
            km._auto_nudge_data()                          # a proved read: the cache now holds the file's key
        episode(4, "stat")                                 # a STAT fault: the cache is never consulted…
        with contextlib.redirect_stderr(err):
            self.assertNotIn(UNPROVED, km._auto_nudge_data(), "healed: stat OK, same key — a cache HIT")
        episode(5, "stat")                                 # …and the cache hit ended the episode (same text, shouts again)
        self.p.unlink()
        with contextlib.redirect_stderr(err):
            self.assertEqual(km._auto_nudge_data(), DEFAULT, "healed by absence: ENOENT is a proved state")
        self._seed()                                       # recreated…
        episode(6, "stat")                                 # …and faulting again with the same text: shouts again
        km._autonudge_cache.clear()
        self._fail("read_text", OSError(errno.EACCES, "Permission denied"))
        with contextlib.redirect_stderr(err):
            km._mark_auto_nudged(GID + "z", "t1", 1)
        self.assertEqual(err.getvalue().count("refusing to write"), 7, "a different fault text is its own episode")
        self.assertIn("Permission denied", err.getvalue())


class CorruptBytes(_Ledger):
    def _corrupt(self, text):
        self.p.write_text(text)
        km._autonudge_cache.clear()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            d = km._auto_nudge_data()
        return d, err.getvalue()

    def test_bytes_that_do_not_parse_are_moved_aside_then_read_as_the_default(self):
        d, err = self._corrupt('{"enabled": fals')        # a torn or hand-edited file
        self.assertEqual(d, DEFAULT)
        self.assertNotIn(UNPROVED, d, "absent after the move: a proved default, so writes proceed")
        self.assertFalse(self.p.exists(), "the corrupt file is out of the way")
        aside = self._aside()
        self.assertEqual(len(aside), 1, "evidence kept, never deleted")
        self.assertRegex(aside[0], r"^auto-nudge\.json\.corrupt-\d{8}T\d{6}Z$",
                         "the judge's goal-store quarantine shape: <name>.corrupt-<utc stamp>")
        self.assertEqual((jd.STATE / aside[0]).read_text(), '{"enabled": fals')
        self.assertEqual(err.count("moved aside"), 1, "one stderr line naming the move")
        self.assertIn("invalid JSON", err)
        km._mark_auto_nudged(GID, "t1", 1)
        self.assertEqual(json.loads(self.p.read_text())["nudged"][GID]["count"], 1,
                         "the next RMW writes a fresh ledger: absent is the fresh-install state")

    def test_a_json_value_that_is_not_an_object_is_corrupt_too(self):
        d, err = self._corrupt("[1, 2, 3]")
        self.assertEqual(d, DEFAULT)
        self.assertFalse(self.p.exists())
        self.assertEqual(len(self._aside()), 1)
        self.assertIn("top-level JSON value is list, not an object", err)

    def test_a_second_corrupt_file_in_the_same_second_takes_a_suffix(self):
        real = time.gmtime
        time.gmtime = lambda *a: real(0)                   # pin the stamp: both moves land in one second
        self.addCleanup(setattr, time, "gmtime", real)
        self._corrupt("{")
        self._corrupt("}")
        self.assertEqual(self._aside(), ["auto-nudge.json.corrupt-19700101T000000Z",
                                         "auto-nudge.json.corrupt-19700101T000000Z-1"],
                         "the second never overwrites the first: a -n suffix, the judge's convention")

    def test_a_file_replaced_under_a_corrupt_read_is_not_moved_aside(self):
        # the inode guard: the bytes that failed are the ones to move; a concurrent atomic publish between
        # our read and our rename has already replaced them, and the NEW file must not be quarantined
        self.p.write_text("{")
        km._autonudge_cache.clear()
        real, target = Path.read_text, str(self.p)

        def read_then_publish(p, *a, **k):
            raw = real(p, *a, **k)
            if str(p) == target:                           # a peer publishes a valid ledger under us
                tmp = p.with_name("auto-nudge.json.tmp.peer")
                tmp.write_text(json.dumps(SEEDED))
                os.replace(tmp, p)
            return raw
        Path.read_text = read_then_publish
        self._undo.append(lambda: setattr(Path, "read_text", real))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            d = km._auto_nudge_data()
        self._heal()
        self.assertEqual(self._aside(), [], "the replacement is not the file whose bytes failed")
        self.assertEqual(json.loads(self.p.read_text()), SEEDED, "…and it stands, untouched")
        self.assertIn("replaced meanwhile", str(d.get(UNPROVED, "")), "this read is unproved; the next one reads the new bytes")
        km._autonudge_cache.clear()
        self.assertEqual(km._auto_nudge_data()["nudged"], SEEDED["nudged"])

    def test_a_corrupt_file_that_cannot_be_moved_aside_is_said_once_not_once_per_read(self):
        # a read-only state dir: every read re-fails the parse and the move; build_feed reads this ledger
        # once per node per push, so a line per read floods the log — the move failure rides the fault
        # text, which the reader dedupes per episode. The text must be STAMP-FREE: str(OSError) from
        # os.replace names the destination, whose per-second stamp made the text — and so every dedupe:
        # the reader's line, the writer's, the pause latch, the error-center row — fire once a second.
        self.p.write_text("{")
        km._autonudge_cache.clear()
        real_replace, real_gmtime, clock = os.replace, time.gmtime, [1_000_000]

        def refuse_aside(src, dst, *a, **k):
            if ".corrupt-" in str(dst):
                raise OSError(errno.EROFS, "Read-only file system", str(src), None, str(dst))
            return real_replace(src, dst, *a, **k)

        def ticking(*a):                                   # every read lands in a NEW second
            clock[0] += 1
            return real_gmtime(clock[0])
        os.replace, time.gmtime = refuse_aside, ticking
        self._undo.append(lambda: setattr(os, "replace", real_replace))
        self._undo.append(lambda: setattr(time, "gmtime", real_gmtime))
        err, snaps, rows = io.StringIO(), [], len(km._SDK_BOOT_PROBLEMS)
        pause = vars(km).get("_auto_nudge_pause", lambda fault: None)   # absent before the fix (see UNPROVED)
        with contextlib.redirect_stderr(err):
            for _ in range(3):
                snaps.append(km._auto_nudge_data())
                pause(snaps[-1].get(UNPROVED, ""))         # what the ticks do with the text: latch on it
        self._heal()
        self.assertTrue(self.p.exists(), "nothing moved: the bytes stand for repair")
        texts = {str(d.get(UNPROVED, "")) for d in snaps}
        self.assertEqual(len(texts), 1, "ONE fault text across three seconds — no destination, no stamp")
        text = texts.pop()
        self.assertNotRegex(text, r"\d{8}T\d{6}Z", "the stamp never rides the fault text")
        self.assertIn("[Errno %d] Read-only file system" % errno.EROFS, text, "errno + strerror name the failure")
        lines = [l for l in err.getvalue().splitlines() if l.strip()]
        self.assertEqual(len(lines), 2, "two channels, one line each: the reader's, and the pause latch's:\n" + err.getvalue())
        self.assertEqual(sum("serving the default" in l for l in lines), 1, "the reader: once per fault episode, not per second")
        self.assertEqual(sum("paused, not defaulted on" in l for l in lines), 1, "the pause latch: once")
        self.assertTrue(all("could not be moved aside" in l for l in lines), "both carry the stamp-free reason")
        self.assertEqual(len(km._SDK_BOOT_PROBLEMS), rows + 1, "one error-center row")
        self.assertFalse(km._write_auto_nudge(dict(snaps[-1])), "and nothing is written over the corrupt file")

    def test_bytes_that_are_not_utf8_are_corrupt_too(self):
        self.p.write_bytes(b"\xff\xfe{")
        km._autonudge_cache.clear()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            d = km._auto_nudge_data()
        self.assertEqual(d, DEFAULT)
        self.assertFalse(self.p.exists())
        self.assertEqual(len(self._aside()), 1, "moved aside like any other unparseable bytes")
        self.assertEqual((jd.STATE / self._aside()[0]).read_bytes(), b"\xff\xfe{")
        self.assertIn("not UTF-8", err.getvalue())


class InterruptBlockTickUnderAFault(unittest.TestCase):
    """_interrupt_block_tick runs every push OUTSIDE the paused nudge pass. Under an unproved snapshot its
    block arm used to file the block in the goal store (a proved write) and then have the marker write
    refused — and the lift on re-engagement is gated on that marker, so a block placed during a fault
    episode stood until a judge happened to unblock it; and its lift arm, with the marker clear refused,
    set `changed` every cycle and pushed every cycle. Now the block arm files nothing under a fault (the
    stop is re-evaluated from the transcript every push, so the block lands on the first tick after the
    file reads again), the lift still runs (it is the user's own re-engagement), and `changed` follows the
    marker write. Control flow only: every collaborator is a recording stub."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.saved_state = jd.STATE
        jd.STATE = Path(self.td.name)
        self.p = jd.STATE / "auto-nudge.json"
        names = ("_alive_sessions", "_session_flag", "_compacting_now", "_api_error", "_interrupt_marks",
                 "_session_working", "_record_interrupt_block", "_lift_interrupt_block", "_intr_block_stands",
                 "_push_all")
        self.saved = {n: getattr(km, n) for n in names}
        self.saved_parsed = jd.parsed_session
        km._alive_sessions = lambda now, tmux: [{"sid": SID, "path": "/nonexistent.jsonl"}]
        km._session_flag = lambda sid, flag: False
        km._compacting_now = lambda sid: False
        km._api_error = lambda path: None
        jd.parsed_session = lambda sid, paths, now: {"turns": [{"id": "t1", "t": 1000, "atoms": []}]}
        km._session_working = lambda turns: False
        self.marks = (1200, 900)                           # the stop is newer than the last human message: a user stop
        km._interrupt_marks = lambda turns, sid="": self.marks
        self.recorded, self.lifted, self.pushes = [], [], []
        km._record_interrupt_block = lambda sid, ev: self.recorded.append((sid, ev)) or GID
        km._lift_interrupt_block = lambda sid, gid, ev: self.lifted.append((sid, gid, ev)) or True   # True: spent (the
        #                                                  #1019 contract; False keeps the marker for a goals-store fault)
        km._intr_block_stands = lambda sid, gid: True
        km._push_all = lambda *a, **k: self.pushes.append(1)
        self._undo = []
        _reset_ledger_state()

    def tearDown(self):
        for undo in reversed(self._undo):
            undo()
        for n, v in self.saved.items():
            setattr(km, n, v)
        jd.parsed_session = self.saved_parsed
        _reset_ledger_state()
        jd.STATE = self.saved_state
        self.td.cleanup()

    def _fail_read(self):
        self._undo.append(_fail_path(self.p, "read_text", EIO))

    def _heal(self):
        for undo in reversed(self._undo):
            undo()
        self._undo = []

    def _tick(self, n=1):
        for _ in range(n):
            km._interrupt_block_tick(2000, {SID: {"state": ""}})

    def test_a_stop_during_a_fault_files_no_block_until_the_ledger_reads_again(self):
        self.p.write_text(json.dumps(DEFAULT))
        km._autonudge_cache.clear()
        before = self.p.read_bytes()
        self._fail_read()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self._tick(5)
        self.assertEqual(self.recorded, [], "no block whose marker cannot be minted: unmarked, it could never be lifted")
        self.assertEqual(self.pushes, [], "…and nothing pushes")
        self.assertEqual(self.p.read_bytes(), before)
        self.assertEqual(err.getvalue().count("paused"), 1, "loud once per fault episode, on the pass's latch")
        self._heal()
        with contextlib.redirect_stderr(err):
            self._tick()
        self.assertEqual(len(self.recorded), 1, "the stop is re-evaluated every push: the block lands on the first tick after the file reads")
        self.assertEqual(json.loads(self.p.read_text())["intrBlocked"], {SID: GID}, "…with its once-per-episode marker")
        self.assertEqual(len(self.pushes), 1)

    def test_a_fault_landing_mid_tick_still_pushes_the_block_it_filed_and_then_stands_down(self):
        # the tag check at the arm's top proves; the fault lands before the marker write. The block IS in
        # the goal store — a proved write, a needs-you flip the feed must hear — so this tick pushes once
        # whatever the marker's fate; every later faulted tick stands down at the check: no storm
        self.p.write_text(json.dumps(DEFAULT))
        km._autonudge_cache.clear()
        real, calls, ledger, test = km._auto_nudge_data, [0], self.p, self

        def flaky():
            calls[0] += 1
            if calls[0] == 2:                              # the file moves on (a new key) and cannot be read
                ledger.write_text(json.dumps(DEFAULT, indent=1))
                test._fail_read()
            return real()
        km._auto_nudge_data = flaky
        self._undo.append(lambda: setattr(km, "_auto_nudge_data", real))
        with contextlib.redirect_stderr(io.StringIO()):
            self._tick(5)
        self.assertEqual(len(self.recorded), 1, "the block was filed once")
        self.assertEqual(self.pushes, [1], "…and pushed exactly once, marker or no marker")
        self.assertNotIn("intrBlocked", json.loads(self.p.read_bytes()), "the marker write was refused")

    def test_a_re_engagement_during_a_fault_lifts_our_block_and_pushes_once_the_marker_clears(self):
        marked = dict(DEFAULT, intrBlocked={SID: GID})
        self.p.write_text(json.dumps(marked))
        km._autonudge_cache.clear()
        km._auto_nudge_data()                              # a proved read: the marker is in the last proved snapshot
        self.p.write_text(json.dumps(marked, indent=1))    # the file moves on (a new stat key)…
        before = self.p.read_bytes()
        self._fail_read()                                  # …and cannot be read
        self.marks = (900, 1200)                           # the user spoke after the stop: re-engaged
        with contextlib.redirect_stderr(io.StringIO()):
            self._tick(5)
        self.assertGreaterEqual(len(self.lifted), 1, "the lift is the user's own re-engagement: it runs whatever the ledger's state")
        self.assertEqual(self.pushes, [], "the marker clear was refused: no push storm (one per cycle before)")
        self.assertEqual(self.p.read_bytes(), before)
        self._heal()
        self._tick()
        self.assertNotIn(SID, json.loads(self.p.read_text()).get("intrBlocked", {}), "the marker clears on the first tick after the file reads")
        self.assertEqual(len(self.pushes), 1, "…and that is the one push")


if __name__ == "__main__":
    unittest.main()
