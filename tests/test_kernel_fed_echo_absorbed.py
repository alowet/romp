#!/usr/bin/env python3
"""A send fed into a RUNNING turn is held by the CLI until its next tool boundary, then spliced in as a
queued_command attachment stamped with the ENQUEUE time — so its atom lands ABOVE the tool calls that
streamed while it waited. Until that splice the kernel's input echo is the message's only visible
record, and that must hold end to end: the echo of a FED, unlanded text outlives its sibling's landing —
no floor retires an SDK echo at all (sdk_backend.prune_live, 2026-09-06: the CLI's image-path extraction
is a composer paste-hook behaviour that stream-json input never reaches) — and retires exactly when the
absorbed atom's text lands: the kernel's _atom_user_texts reads the queued_command text off the parsed
absorbed atom, so the by-text prune fires on it and the message never renders twice.

The sdk_backend twin of the image-path predicate is pinned against the kernel's, and both against the
CLI paste hook's extension set (ImagePathPredicateTwins names the source). SYNTHETIC fixtures only (a
private synthetic sid, the notes-api demo domain)."""
import json
import os
import re
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
km = SourceFileLoader("romp_kernel_fed_echo", os.path.join(BIN, "romp-kernel")).load_module()
sb = SourceFileLoader("romp_sdk_backend_fed_echo", os.path.join(BIN, "romp_sdk_backend.py")).load_module()
em = km.em

SID = "1f3e5d7c-9b1a-4c2d-8e6f-0a1b2c3d4e5f"   # private synthetic sid (goal-store fixtures rule)
T0 = 1_800_000_000
NOW = T0 + 3600
FED = ("Replying to this highlighted code (/tmp/notes-api/notes/api.py:42):\n"
       "> def list_notes():\n\nrename this to fetch_notes")


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def uline(t, text, uuid, parent=None, ps="sdk"):
    return {"type": "user", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent,
            "promptSource": ps, "message": {"role": "user", "content": text}}


def aline(t, text, uuid, parent, tools=(), stop="end_turn"):
    content = [{"type": "text", "text": text}] if text else []
    for i, n in enumerate(tools):
        content.append({"type": "tool_use", "id": "tu_%s_%d" % (uuid, i), "name": n, "input": {"command": "true"}})
    return {"type": "assistant", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent,
            "message": {"role": "assistant", "content": content, "stop_reason": stop}}


def trline(t, tool_use_id, uuid, parent, content="ok"):
    return {"type": "user", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent,
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use_id,
                                                     "content": content}]}}


def attline(t, prompt, uuid, parent):
    return {"type": "attachment", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent,
            "isSidechain": False, "attachment": {"type": "queued_command", "prompt": prompt}}


def running_turn():
    """The first staged comment lands at T0+39 and opens a turn whose tool call is still running."""
    return [
        uline(T0, "tighten the notes-api search", "u1"),
        aline(T0 + 10, "Done.", "a1", "u1"),
        uline(T0 + 39, "the first comment: drop the unused import", "u2", "a1"),
        aline(T0 + 41, "Removing it.", "a2", "u2", tools=("Bash",), stop="tool_use"),
        trline(T0 + 50, "tu_a2_0", "tr1", "a2"),
    ]


def spliced_tail():
    """The CLI took the second comment at the T0+50 boundary: the attachment carries the send time."""
    return [
        attline(T0 + 38, FED, "att1", "tr1"),
        aline(T0 + 75, "Renamed it as well.", "a3", "att1"),
    ]


class _World:
    """A real SdkBackend bound as the kernel's backend, owning SID, with a thread-less SdkSession."""

    def __init__(self):
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        (root / "sdk").mkdir()
        self.cwd = root / "proj"; self.cwd.mkdir()
        os.environ["CLAUDE_CONFIG_DIR"] = str(root / "claude")
        self.tpath = Path(sb.transcript_path(str(self.cwd), SID))
        self.tpath.parent.mkdir(parents=True, exist_ok=True)
        self.tpath.write_text("")
        self.be = sb.SdkBackend(str(root), "/bin/true", lambda *a, **k: None)
        reg = {"sid": SID, "name": "web", "mode": "acceptEdits", "alive": True,
               "cwd": str(self.cwd), "lastSid": SID}
        sb.write_reg(self.be.state_dir, SID, reg)
        self.s = sb.SdkSession(self.be, dict(reg))
        self.be.sessions[SID] = self.s
        self.saved = km._sdk
        km._sdk = lambda: self.be

    def close(self):
        km._sdk = self.saved
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        self.td.cleanup()

    def write(self, recs):
        self.tpath.write_text("".join(json.dumps(r) + "\n" for r in recs))

    def parse(self):
        return em.parse_session(str(self.tpath), rompuuid=SID, candidate_files=[str(self.tpath)],
                                postal_log=[], now=NOW, sdk_human=True)

    def echo(self, text, t):
        key = "echo:fed"
        self.be._live[SID] = {key: {"type": "user", "uuid": key, "session_id": SID, "t": t,
                                     "parentUuid": None, "author": "human", "_echo_text": text,
                                     "message": {"role": "user", "content": [{"type": "text", "text": text}]}}}
        return key


class FedEchoSurvivesUntilTheSpliceLands(unittest.TestCase):
    def setUp(self):
        self.w = _World()
        self.assertTrue(self.w.be.owns(SID))
        self.assertIs(km.Sessions.backend_for(SID), self.w.be)

    def tearDown(self):
        self.w.close()

    def _texts(self, session):
        return [t for turn in session["turns"] for a in turn["atoms"] for t in km._atom_user_texts(a)]

    def test_the_fed_echo_outlives_the_siblings_landing(self):
        # the second comment was fed at second 38; the first landed at 39 and is the human floor.
        # Pre-change: the quote chip's path made the echo "path-bearing" and the floor retired it —
        # the store emptied with the message still in the CLI's queue.
        self.w.write(running_turn())
        key = self.w.echo(FED, T0 + 38)
        self.w.s.inflight = 1
        self.w.s._inflight_texts.append(FED)
        parsed = self.w.parse()
        self.assertEqual(km._human_turn_floor(parsed), T0 + 39, "the sibling's landing IS the floor")
        merged = km._merge_live_atoms(parsed, SID)
        self.assertIn(key, self.w.be._live.get(SID, {}), "the fed echo survives the floor")
        self.assertIn(FED, self._texts(merged), "…and the chat still shows the message, once")
        self.assertEqual(self._texts(merged).count(FED), 1)

    def test_the_landing_retires_it_by_text_through_the_queued_command_atom(self):
        self.w.write(running_turn() + spliced_tail())
        key = self.w.echo(FED, T0 + 38)
        self.w.s.inflight = 1
        self.w.s._inflight_texts.append(FED)          # still fed: the turn has not settled
        parsed = self.w.parse()
        absorbed = [a for t in parsed["turns"] for a in t["atoms"] if a.get("absorbed")]
        self.assertEqual([a["uuid"] for a in absorbed], ["att1"])
        self.assertIn(FED, km._atom_user_texts(absorbed[0]),
                      "the kernel's landing set covers the queued_command shape")
        merged = km._merge_live_atoms(parsed, SID)
        self.assertNotIn(SID, self.w.be._live, "the absorbed atom's text landed → the echo retires")
        self.assertEqual(self._texts(merged).count(FED), 1, "never twice: the atom, not the echo")

    def test_an_unfed_image_echo_survives_the_floor_too(self):
        # nobody holds it, nothing landed it: until 2026-09-06 the image-extraction floor retired this
        # echo the moment the sibling landed — but on this route the CLI never rewrites the path, so the
        # text WILL land verbatim, and the echo waits for that (or for the dropped marking)
        self.w.write(running_turn())
        key = self.w.echo("compare with /tmp/notes-api/docs/before.png", T0 + 38)
        merged = km._merge_live_atoms(self.w.parse(), SID)
        self.assertIn(key, self.w.be._live.get(SID, {}))
        self.assertEqual(self._texts(merged).count("compare with /tmp/notes-api/docs/before.png"), 1)


class ImagePathPredicateTwins(unittest.TestCase):
    """The extension set is the CLI's, not romp's. SOURCE OF TRUTH: the installed Claude Code bundle
    (2.1.261) carries exactly one image-path test, `/\\.(png|jpe?g|gif|webp)$/i`; its callers are the
    terminal composer's bracketed-paste handler — which reads a pasted path with one of those extensions
    and rewrites the token to "[Image #N]" (the "Failed to read pasted image file" path) — and two
    attachment uploaders' isImage. Nothing on the stream-json input path an SDK session uses reaches it,
    which is why sdk_backend.prune_live floors no echo; the kernel's tmux settle borrows the predicate
    for the route where the hook does run. When the CLI's set changes, change BOTH twins here: the kernel
    waits on the rewrite (_injected_img_paths), the backend exports the predicate — a drift between them
    or from the CLI makes an echo the CLI did rewrite persist forever, or one it did not rewrite get
    retired as an extraction."""

    CLI_SET = "png|jpe?g|gif|webp"

    def test_the_backend_regex_is_the_kernels(self):
        self.assertEqual(sb._IMG_PATH_RE.pattern, km._IMG_PATH_RE.pattern)
        self.assertEqual(sb._IMG_PATH_RE.flags, km._IMG_PATH_RE.flags)

    def test_the_set_is_the_cli_paste_hooks(self):
        for rx in (sb._IMG_PATH_RE, km._IMG_PATH_RE):
            m = re.search(r"\\\.\(\?:([a-z|?]+)\)", rx.pattern)
            self.assertIsNotNone(m, rx.pattern)
            self.assertEqual(m.group(1), self.CLI_SET, "the alternation is the CLI's, verbatim")
            self.assertTrue(rx.flags & re.IGNORECASE, "the CLI's test is case-insensitive (/i)")
        for ext in ("png", "PNG", "jpg", "JPEG", "jpeg", "gif", "webp", "WebP"):
            self.assertTrue(sb._path_bearing("see /tmp/notes-api/docs/shot.%s now" % ext), ext)
            self.assertEqual(km._injected_img_paths("see /tmp/notes-api/docs/shot.%s now" % ext),
                             ["/tmp/notes-api/docs/shot.%s" % ext])
        for ext in ("svg", "bmp", "ico", "avif", "heic", "tiff", "txt", "md"):
            self.assertFalse(sb._path_bearing("see /tmp/notes-api/docs/shot.%s now" % ext),
                             "%s: the CLI never rewrites it" % ext)
            self.assertEqual(km._injected_img_paths("see /tmp/notes-api/docs/shot.%s now" % ext), [])


if __name__ == "__main__":
    unittest.main()
