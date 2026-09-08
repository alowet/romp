#!/usr/bin/env python3
"""A session cwd whose `.git` POINTER FILE holds non-UTF-8 bytes no longer wedges the whole dashboard.

A worktree carries `.git` as a one-line FILE (`gitdir: <private-dir>`) instead of a directory.
`_git_head_file` opened that file in text mode inside a try whose only handler was `except OSError:`,
so one undecodable byte in it raised UnicodeDecodeError — through `_git_branch` and build_session's
gitBranch derivation — into `_push`'s single outer try, which logged 'push build:' and returned before
sending ANY session to ANY client. Every cycle, for every session, until someone fixed that one file
by hand. `_git_branch` and `_repo_file_index` closed their own reads with the same OSError-only clause.

Now all three treat an undecodable file the way an unreadable one is treated (no branch, no file
index), and the resolver names the bad file on stderr ONCE per fault episode: a registry keyed on the
path, cleared when the file reads again, so the operator learns which file to fix instead of staring
at a silent blank.

Synthetic only: throwaway git repos with fixture identities, placeholder sids, hostname TESTHOST."""
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
# Hermetic state BEFORE the loads — they resolve their state root at import time.
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
km = SourceFileLoader("romp_kernel_gitfile_bytes", os.path.join(BIN, "romp-kernel")).load_module()
jd = km.jd

TORN = b"gitdir: /x/y\xff\xfe"                      # a pointer file with two undecodable bytes in it
A = "11111111-2222-3333-4444-555555555555"      # the session whose cwd carries the torn pointer file
B = "11111111-2222-3333-4444-555555555556"      # a healthy peer on a real repo
NOW = 1781300000


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _uline(t, text, uuid, parent=None):
    return {"type": "user", "timestamp": _iso(t), "uuid": uuid, "parentUuid": parent,
            "promptSource": "typed", "message": {"role": "user", "content": text}}


def _aline(t, text, uuid, parent):
    return {"type": "assistant", "timestamp": _iso(t), "uuid": uuid, "parentUuid": parent,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}],
                        "stop_reason": "end_turn"}}


def _tm():
    """One live tmux entry, every key the chat builder reads."""
    return {"state": "ready", "color": "#888888", "since": NOW - 60, "model": "", "effort": "",
            "context": None, "compactPct": None, "backend": "tmux"}


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.email=t@TESTHOST", "-c", "user.name=t", *args],
                   cwd=cwd, capture_output=True, text=True, timeout=10, check=True)


def _mk_repo(td, name="repo"):
    repo = Path(td) / name
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    (repo / "a.txt").write_text("a\n")
    _git("add", "a.txt", cwd=repo)
    _git("commit", "-q", "-m", "seed", cwd=repo)
    return repo


def _torn_cwd(td, name="work"):
    cwd = Path(td) / name
    cwd.mkdir()
    (cwd / ".git").write_bytes(TORN)
    return cwd


def _reset_caches():
    for c in (km._branch_cache, km._head_path_cache, km._tree_cache, km._repo_index_cache):
        c.clear()
    faults = getattr(km, "_git_file_faults", None)      # absent on the pre-fix kernel: the raise is the finding
    if faults is not None:
        faults.clear()


@contextlib.contextmanager
def _stderr():
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        yield buf


class Resolver(unittest.TestCase):
    """_git_head_file / _git_branch — the derivation build_session runs for every session on every push."""

    def setUp(self):
        _reset_caches()

    def test_a_torn_pointer_file_reads_as_no_branch_and_is_named_once(self):
        with tempfile.TemporaryDirectory() as td:
            cwd = _torn_cwd(td)
            dotgit = str(cwd / ".git")
            with _stderr() as err:
                self.assertEqual(km._git_head_file(str(cwd)), "", "undecodable → no HEAD file, like unreadable")
                self.assertEqual(km._git_branch(str(cwd)), "", "…and no branch — never a raise")
            lines = err.getvalue().splitlines()
            self.assertEqual(len(lines), 1, "exactly one stderr line for the fault: %r" % lines)
            self.assertIn(dotgit, lines[0], "the line names the file the operator has to fix")
            # a second derivation adds nothing: the episode is already on record
            with _stderr() as err2:
                self.assertEqual(km._git_branch(str(cwd)), "")
                self.assertEqual(km._git_head_file(str(cwd)), "")
            self.assertEqual(err2.getvalue(), "", "one fault episode is reported once")
            # the repair — a pointer file that reads — ends the episode without a kernel restart
            repo = _mk_repo(td)
            (cwd / ".git").write_text("gitdir: %s\n" % (repo / ".git"))
            with _stderr() as err3:
                self.assertEqual(km._git_branch(str(cwd)), "main", "a repaired pointer file resolves again")
            self.assertEqual(err3.getvalue(), "", "a clean read is not news")
            self.assertNotIn(dotgit, km._git_file_faults, "a clean read ends the fault episode")
            # ...so the same file going bad again is a NEW episode, reported anew. The resolved path is
            # cached on purpose (a live worktree's pointer never moves), so the re-read a restart would
            # do is what surfaces the new fault.
            (cwd / ".git").write_bytes(TORN)
            km._head_path_cache.clear()
            km._branch_cache.clear()
            with _stderr() as err4:
                self.assertEqual(km._git_branch(str(cwd)), "")
            self.assertEqual(len(err4.getvalue().splitlines()), 1, "a new episode → one new line")
            self.assertIn(dotgit, err4.getvalue())

    @unittest.skipIf(os.geteuid() == 0, "root reads through chmod 0; the EACCES step needs a real permission fault")
    def test_a_different_fault_on_the_same_file_is_a_new_episode(self):
        # a presence-keyed registry would keep the FIRST fault on record: a pointer file that goes EACCES,
        # then (chmod) readable but still undecodable, would log the PermissionError once and never the
        # decode fault until a clean read. The episode is the fault TEXT, as the judge's store-fault
        # boundary defines it — so the operator sees the fault that is CURRENTLY in the way.
        with tempfile.TemporaryDirectory() as td:
            cwd = _torn_cwd(td)
            dotgit = cwd / ".git"
            dotgit.chmod(0)
            try:
                with _stderr() as err:
                    self.assertEqual(km._git_branch(str(cwd)), "")
                    self.assertEqual(km._git_branch(str(cwd)), "")
                lines = err.getvalue().splitlines()
                self.assertEqual(len(lines), 1, "the permission fault, once: %r" % lines)
                self.assertIn("PermissionError", lines[0])
            finally:
                dotgit.chmod(0o644)
            with _stderr() as err2:
                self.assertEqual(km._git_branch(str(cwd)), "")
                self.assertEqual(km._git_branch(str(cwd)), "")
            lines2 = err2.getvalue().splitlines()
            self.assertEqual(len(lines2), 1, "readable but undecodable is a NEW episode, once: %r" % lines2)
            self.assertIn("UnicodeDecodeError", lines2[0])
            self.assertIn(str(dotgit), lines2[0])

    def test_the_callers_backstop_a_raise_from_the_resolver(self):
        # _git_branch and _repo_file_index close their own reads with the same widened clause: even if the
        # resolver let a decode error through, the derivation yields the no-branch / uncached-listing path
        # it takes for an unreadable HEAD, never a raise into the push cycle
        with tempfile.TemporaryDirectory() as td:
            repo = _mk_repo(td)

            def boom(cwd):
                raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
            with mock.patch.object(km, "_git_head_file", boom):
                self.assertEqual(km._git_branch(str(repo)), "main", "the fork fallback still answers")
                idx = km._repo_file_index(str(repo))
            self.assertIsNotNone(idx, "the listing is still built — uncached, not abandoned")
            self.assertIn("a.txt", idx)


class FileIndex(unittest.TestCase):
    """_repo_file_index resolves the same pointer file to find the git index beside HEAD."""

    def setUp(self):
        _reset_caches()

    def test_a_torn_pointer_file_yields_no_index_not_a_raise(self):
        with tempfile.TemporaryDirectory() as td:
            cwd = _torn_cwd(td)
            with _stderr() as err:
                self.assertIsNone(km._repo_file_index(str(cwd)), "no listing to be had → None, the stand-down value")
            lines = err.getvalue().splitlines()
            self.assertEqual(len(lines), 1, "the one fault line: %r" % lines)
            self.assertIn(str(cwd / ".git"), lines[0])


class PushCycle(unittest.TestCase):
    """Two registered sessions, one whose cwd carries the torn pointer file: the push still reaches the
    client with EVERY session — the faulting one showing no branch, its healthy peer its real one."""

    def setUp(self):
        _reset_caches()
        self._saved = (jd.STATE, km.NAMES, km._GLOBAL_CLAUDE_MD)
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        jd._rebind_state(root / "state")
        jd.NAMES.mkdir(parents=True)
        km.NAMES = jd.NAMES                                   # the kernel binds NAMES at import; follow the rebind
        km._GLOBAL_CLAUDE_MD = root / "no-global-claude.md"   # hermetic: no machine-local instructions in the payload
        self.torn = _torn_cwd(root, "work-web")
        self.repo = _mk_repo(root, "work-api")
        (jd.NAMES / A).write_text("web\t%s\t#abcdef\t#ffffff\n" % self.torn)
        (jd.NAMES / B).write_text("api\t%s\t#abcdef\t#ffffff\n" % self.repo)
        self.paths = {A: self._transcript(A, "a"), B: self._transcript(B, "b")}
        self._clear_build_state()

    def tearDown(self):
        self._clear_build_state()
        jd._rebind_state(self._saved[0])
        km.NAMES, km._GLOBAL_CLAUDE_MD = self._saved[1], self._saved[2]
        self.td.cleanup()

    def _clear_build_state(self):
        km._parse_cache.clear()
        jd._PARSE_CACHE.clear()
        km._built_chat.clear()
        km._prev_chat_events.clear()
        km._prev_chat_ledger.clear()

    def _transcript(self, sid, tag):
        p = Path(self.td.name) / (sid + ".jsonl")
        recs = [_uline(NOW - 500, "tighten the notes-api search", "u1-" + tag),
                _aline(NOW - 480, "Done.", "a1-" + tag, "u1-" + tag)]
        p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
        return str(p)

    def _push_once(self, seen=None):
        """One push to one chat client; `seen` (a list) collects every cwd the pointer-file resolver
        was asked about, so a test can prove a branch was re-derived rather than served from a cache."""
        sessions = [{"sid": A, "name": "web", "path": self.paths[A], "anchor": 0, "mtime": NOW},
                    {"sid": B, "name": "api", "path": self.paths[B], "anchor": 0, "mtime": NOW}]
        tmux = {A: _tm(), B: _tm()}
        sent = []
        real_head = km._git_head_file

        def head(cwd):
            if seen is not None:
                seen.append(cwd)
            return real_head(cwd)
        with mock.patch.object(km, "_git_head_file", head), \
                mock.patch.object(km, "_sessions", lambda now, window=None, forks=True: list(sessions)), \
                mock.patch.object(km, "_tmux_sessions", lambda: dict(tmux)), \
                mock.patch.object(km, "_chat_tab_sessions", lambda now, tm: list(sessions)), \
                mock.patch.object(km, "build_feed", lambda *a, **k: {"working": [], "asks": []}), \
                mock.patch.object(km, "build_timeline", lambda *a, **k: None), \
                mock.patch.object(km, "_send_client",
                                  lambda c, key, msg, pre=None, sig=None: sent.append((key, msg))), \
                _stderr() as err:
            km._push([{"app": "chat", "alive": True}], tmux=tmux)
        return sent, err.getvalue()

    @staticmethod
    def _branch(msg):
        body = msg if isinstance(msg, dict) else json.loads(msg)
        return body.get("gitBranch")

    def test_one_torn_pointer_file_does_not_stop_the_push(self):
        sent, err = self._push_once()
        chats = {key[1]: msg for key, msg in sent if key[0] == "chat"}
        self.assertEqual(set(chats), {A, B},
                         "every session reaches the client; keys sent: %r" % sorted({k[0] for k, _ in sent}))
        self.assertEqual(self._branch(chats[B]), "main", "the healthy peer shows its branch")
        self.assertEqual(self._branch(chats[A]), "", "the session with the torn pointer file shows none")
        self.assertNotIn("push build:", err, "the cycle was not abandoned: %r" % err)
        named = [l for l in err.splitlines() if str(self.torn / ".git") in l]
        self.assertEqual(len(named), 1, "exactly one stderr line names the bad file: %r" % err.splitlines())
        # the next cycle has nothing new to say about a fault already on record. An UNCHANGED push serves
        # the chat from _built_chat / the parse cache and never re-derives the branch, which would keep
        # this quiet with no registry at all — so those caches are cleared and the resolver is watched:
        # what this pins is the DEDUPE (the branch IS re-derived, the file re-read, and still no new line).
        self._clear_build_state()
        seen = []
        _, err2 = self._push_once(seen)
        self.assertIn(str(self.torn), seen, "premise: the second push re-derived the torn session's branch")
        self.assertEqual([l for l in err2.splitlines() if str(self.torn / ".git") in l], [],
                         "a second push logs nothing new: %r" % err2.splitlines())


if __name__ == "__main__":
    unittest.main()
