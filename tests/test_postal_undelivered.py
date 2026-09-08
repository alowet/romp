#!/usr/bin/env python3
"""Sender 'still undelivered' backstop (the user 2026-06-29): the orphan sweep only bounces mail to a DEAD
recipient. Mail can also strand UNREAD in a LIVE-but-idle recipient's box (the stale-bus bug). _warn_stuck_mail
warns the live SENDER once, after STUCK_GRACE, and LEAVES the message for eventual delivery — gated on the
recipient being idle/waiting so a mid-turn recipient never trips a false alarm.

Synthetic only — placeholder UUIDs, no real session data.
"""
import json
import os
import shutil
import tempfile
import time
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")

os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
pm = SourceFileLoader("romp_postal_undelivered", os.path.join(BIN, "romp-postal-service")).load_module()

SENDER = "11111111-1111-1111-1111-111111111111"
RECIP = "22222222-2222-2222-2222-222222222222"


class StuckMailWarning(unittest.TestCase):
    def setUp(self):
        self._seamfile = os.path.join(tempfile.mkdtemp(), "sessions.json")
        os.environ["ROMP_SESSIONS_FILE"] = self._seamfile      # local_agents() reads this instead of a live kernel
        for d in (pm.MAILROOT, pm.WARNED, pm.MAILPENDING):     # isolate each test
            shutil.rmtree(d, ignore_errors=True)

    def tearDown(self):
        os.environ.pop("ROMP_SESSIONS_FILE", None)

    def _set_recip_state(self, state):
        Path(self._seamfile).write_text(json.dumps(
            [{"id": SENDER, "name": "alice", "state": "idle"},
             {"id": RECIP, "name": "bob", "state": state}]))

    def _age_recip_mail(self, secs):
        old = time.time() - secs
        for f in (pm.MAILROOT / RECIP / "new").iterdir():
            os.utime(f, (old, old))

    def _sender_box(self):
        return pm.read_box(SENDER, consume=False)

    def test_idle_recipient_stuck_past_grace_warns_sender_once_and_keeps_the_mail(self):
        self._set_recip_state("idle")
        mid = pm.deliver(RECIP, "alice", SENDER, "please review my PR")
        self._age_recip_mail(pm.STUCK_GRACE + 60)
        pm._warn_stuck_mail()
        sb = self._sender_box()
        self.assertEqual(len(sb), 1, "the live sender is warned exactly once")
        self.assertIn("STILL UNDELIVERED", sb[0]["body"])
        self.assertIn("bob", sb[0]["body"], "the warning names the unreachable recipient")
        self.assertTrue((pm.MAILROOT / RECIP / "new" / mid).exists(),
                        "a live recipient's message is LEFT in new/ — it may still deliver (not bounced)")
        pm._warn_stuck_mail()
        self.assertEqual(len(self._sender_box()), 1, "the one-time marker prevents a duplicate warning")

    def test_working_recipient_is_not_warned(self):
        self._set_recip_state("working")
        pm.deliver(RECIP, "alice", SENDER, "ping while you work")
        self._age_recip_mail(pm.STUCK_GRACE + 60)
        pm._warn_stuck_mail()
        self.assertEqual(self._sender_box(), [],
                         "a mid-turn recipient legitimately waits for its next turn — no false alarm")

    def test_fresh_mail_within_grace_is_not_warned(self):
        self._set_recip_state("idle")
        pm.deliver(RECIP, "alice", SENDER, "just sent")     # mtime ~ now, within STUCK_GRACE
        pm._warn_stuck_mail()
        self.assertEqual(self._sender_box(), [], "within the grace the normal delivery path still owns it")

    def test_marker_is_pruned_once_the_message_delivers(self):
        self._set_recip_state("idle")
        mid = pm.deliver(RECIP, "alice", SENDER, "warn then deliver")
        self._age_recip_mail(pm.STUCK_GRACE + 60)
        pm._warn_stuck_mail()
        self.assertTrue((pm.WARNED / mid).exists(), "warned once → marker written")
        pm.read_box(RECIP, consume=True)                    # the recipient finally drains it (new/ -> cur/)
        pm._warn_stuck_mail()
        self.assertFalse((pm.WARNED / mid).exists(),
                         "the marker is pruned once the message left new/ so WARNED stays bounded")


class RefusedNotesKeepTheMail(unittest.TestCase):
    """deliver() can REFUSE now (2026-09-08: its sent row could not land). The orphan sweep and the
    stuck-mail warning used to catch every deliver error and carry on — destroy the orphan, touch the
    one-time marker — so a refused note lost the mail with no notice and no row, and the warning was
    never retried. A refusal keeps the file and the marker untouched, is said once per episode, and
    the next pass retries once the log writes again. Mutants killed: the generic `except Exception`
    arm swallowing the refusal (the orphan is destroyed / the marker touched); the sweep's destroy
    row written best-effort AFTER the unlink (the file goes with no row)."""

    def setUp(self):
        self._seamfile = os.path.join(tempfile.mkdtemp(), "sessions.json")
        os.environ["ROMP_SESSIONS_FILE"] = self._seamfile
        for d in (pm.MAILROOT, pm.WARNED, pm.MAILPENDING):
            shutil.rmtree(d, ignore_errors=True)
        self._tl, self._log = pm.TLDIR, pm._log
        self.logged = []
        pm._log = lambda m: self.logged.append(m)
        try:
            (pm.TLDIR / "messages.jsonl").unlink()
        except OSError:
            pass
        pm._TL_FAULT[0] = False
        pm._REFUSAL_SAID.clear()

    def tearDown(self):
        pm.TLDIR, pm._log = self._tl, self._log
        pm._TL_FAULT[0] = False
        pm._REFUSAL_SAID.clear()
        os.environ.pop("ROMP_SESSIONS_FILE", None)

    def _live(self, rows):
        Path(self._seamfile).write_text(json.dumps(rows))

    def _break_the_log(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        self.addCleanup(lambda: os.unlink(path))
        pm.TLDIR = Path(path) / "timeline"          # under a regular file: the REAL append fails (ENOTDIR)

    def _age(self, secs):
        old = time.time() - secs
        for f in (pm.MAILROOT / RECIP / "new").iterdir():
            os.utime(f, (old, old))

    def _rows(self):
        p = self._tl / "messages.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines() if l] if p.exists() else []

    def _said(self):
        return len([m for m in self.logged if "kept for the next pass" in m])

    def test_the_sweep_keeps_an_orphan_whose_bounce_note_was_refused(self):
        self._live([{"id": SENDER, "name": "alice", "state": "idle"}])          # bob is dead → an orphan
        mid = pm.deliver(RECIP, "alice", SENDER, "please review my PR")
        self._age(pm.ORPHAN_GRACE + 60)
        self._break_the_log()
        pm._sweep_orphans()
        self.assertTrue((pm.MAILROOT / RECIP / "new" / mid).exists(),
                        "a refused bounce note destroys nothing: the orphan waits for the next sweep")
        self.assertEqual(pm.read_box(SENDER, consume=False), [], "no note was published without its row")
        pm._sweep_orphans()
        self.assertTrue((pm.MAILROOT / RECIP / "new" / mid).exists())
        self.assertEqual(self._said(), 1, "said once per episode, not per pass")
        pm.TLDIR = self._tl                                                    # the log writes again
        pm._sweep_orphans()
        self.assertFalse((pm.MAILROOT / RECIP / "new" / mid).exists(), "the next pass completes the bounce")
        notes = pm.read_box(SENDER, consume=False)
        self.assertEqual(len(notes), 1)
        self.assertIn("UNDELIVERED", notes[0]["body"])
        self.assertEqual([r["ev"] for r in self._rows() if r.get("id") == mid], ["sent", "bounced"],
                         "the destroy landed on the ledger")

    def test_the_sweep_records_the_destroy_before_it_destroys(self):
        # no live sender to bounce to (the sweep still runs: someone is live) → straight to the destroy
        self._live([{"id": "33333333-4444-5555-6666-777777777777", "name": "carol", "state": "idle"}])
        mid = pm.deliver(RECIP, "alice", SENDER, "please review my PR")
        self._age(pm.ORPHAN_GRACE + 60)
        self._break_the_log()
        pm._sweep_orphans()
        self.assertTrue((pm.MAILROOT / RECIP / "new" / mid).exists(),
                        "a destroy that cannot be recorded does not happen")
        pm.TLDIR = self._tl
        pm._sweep_orphans()
        self.assertFalse((pm.MAILROOT / RECIP / "new" / mid).exists())
        self.assertEqual([r["ev"] for r in self._rows() if r.get("id") == mid], ["sent", "bounced"])

    def test_the_stuck_warning_is_retried_once_its_note_lands(self):
        self._live([{"id": SENDER, "name": "alice", "state": "idle"},
                    {"id": RECIP, "name": "bob", "state": "idle"}])
        mid = pm.deliver(RECIP, "alice", SENDER, "please review my PR")
        self._age(pm.STUCK_GRACE + 60)
        self._break_the_log()
        pm._warn_stuck_mail()
        self.assertFalse((pm.WARNED / mid).exists(), "a refused warning leaves the one-time marker untouched")
        self.assertEqual(pm.read_box(SENDER, consume=False), [])
        pm._warn_stuck_mail()
        self.assertFalse((pm.WARNED / mid).exists())
        self.assertEqual(self._said(), 1, "said once per episode")
        pm.TLDIR = self._tl
        pm._warn_stuck_mail()
        warns = pm.read_box(SENDER, consume=False)
        self.assertEqual(len(warns), 1, "the warning fires on the first pass whose note lands")
        self.assertIn("STILL UNDELIVERED", warns[0]["body"])
        self.assertTrue((pm.WARNED / mid).exists(), "…and only then is it marked one-time")
        pm._warn_stuck_mail()
        self.assertEqual(len(pm.read_box(SENDER, consume=False)), 1, "one-time still holds")
        self.assertTrue((pm.MAILROOT / RECIP / "new" / mid).exists(), "the stuck message itself is left for delivery")


if __name__ == "__main__":
    unittest.main()
