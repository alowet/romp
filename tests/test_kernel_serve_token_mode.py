#!/usr/bin/env python3
"""The serve-token file is the same-user gate on the whole kernel, and every client holds a COPY of
it (bin/romp and the hooks read the file, the bus and each session's MCP process load it at start,
peers fetch it at attach). So `_load_token` has two jobs beyond returning a string: the file must be
0600 from its first byte, and an EXISTING token must never be replaced behind those clients' backs.

The old loader failed the second job in three ways, each pinned here by a case that fails on it:
  - ANY read fault fell through to the mint (`except OSError: pass`), so an EACCES or EIO rotated
    the token: the kernel came up with a credential nobody else held. UnreadableIsNotRotated.
  - Two starters (kernel and bus boot together) each minted their own, last writer winning while
    the loser served a token the file no longer held. ServeTokenFlock.
  - The mint opened the LIVE path with O_TRUNC, so a concurrent reader saw an empty file and
    minted its own. TokenBirth pins the temp-then-rename shape and that the live path is never
    opened for writing at all.
TightenMode (a loose existing file is chmod'd, its value kept), EmptyFileMints (a 0-byte or
whitespace file is a torn earlier mint and is minted over, aloud), LockFailureIsFailClosed (no
lock: a good 0600 token is returned, anything else is a refusal) and StaleTempsAreSwept (a crashed
attempt's temp, any pid's, is removed before the mint) pin the rest of the contract, and
ServeTokenLoadersMatch pins the bus's copy of the routine to the kernel's, since the bus imports
nothing from kernel/ and carries its own: AST identity with the docstring stripped (any divergence
is red), plus the named invariants as a readable second layer.

ServeTokenFileMode is the original mode case. It INTERPOSES on os.chmod because the old shape's
trailing chmod repaired the mode before anything could observe it; the shape now needs no chmod on
a fresh mint at all, and that is what the case asserts.

Synthetic only: hermetic temp STATE, placeholder tokens.
"""
import ast
import contextlib
import io
import os
import re
import stat
import tempfile
import threading
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")

os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "test-token-DO-NOT-USE")
SourceFileLoader("romp_event_model", os.path.join(BIN, "romp-event-model")).load_module()
SourceFileLoader("romp_judge", os.path.join(BIN, "romp-judge")).load_module()
km = SourceFileLoader("romp_kernel", os.path.join(BIN, "romp-kernel")).load_module()


def _mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


class _TokenFile(unittest.TestCase):
    """Every case starts and ends with no token, no lock and no temp under the test's own STATE.
    ROMP_SERVE_TOKEN is moved out of the way (with it set the loader returns it verbatim and never
    touches the file), and the umask is 0 so only the loader's own modes protect what it writes."""

    def setUp(self):
        self.f = km.jd.STATE / "serve-token"
        self.lock = self.f.with_name("serve-token.lock")
        km.jd.STATE.mkdir(parents=True, exist_ok=True)
        self._env = self._umask = None
        self.addCleanup(self._restore)      # registered FIRST: a failing _clear() must not leak a zeroed umask
        self._env = os.environ.pop("ROMP_SERVE_TOKEN", None)
        self._umask = os.umask(0)
        self._clear()

    def _clear(self):
        for p in [self.f, self.lock] + list(km.jd.STATE.glob("serve-token.*.tmp")):
            if p.is_dir():
                p.rmdir()                    # LockFailureIsFailClosed plants a directory at the lock path
            elif p.exists():
                p.unlink()

    def _restore(self):
        self._clear()
        if self._umask is not None:
            os.umask(self._umask)
        if self._env is not None:
            os.environ["ROMP_SERVE_TOKEN"] = self._env

    def _temps(self):
        return sorted(p.name for p in km.jd.STATE.glob("serve-token.*.tmp"))


class ServeTokenFileMode(_TokenFile):
    def test_minted_0600_before_any_chmod_can_repair_it(self):
        chmods = []
        real_chmod = os.chmod

        def _no_chmod(path, mode, *a, **k):
            """Record the repair and DON'T perform it: the mode the file was created with is the
            whole question, and a chmod one line later hides the answer."""
            chmods.append((str(path), mode))

        os.chmod = _no_chmod
        try:
            tok = km._load_token()
        finally:
            os.chmod = real_chmod

        self.assertTrue(self.f.exists(), "the mint path never ran — this test proves nothing")
        self.assertEqual(self.f.read_text().strip(), tok, "the file must hold the token it returned")
        self.assertEqual(_mode(self.f), 0o600,
                         "the serve token must be 0600 from the open() that created it: writing it "
                         "first and chmod'ing after leaves the credential at the umask's mercy for "
                         "the gap between the two calls")
        self.assertEqual(chmods, [],
                         "a fresh mint needs no chmod at all: the temp is opened 0600 and renamed into "
                         "place, so there is no pre-existing inode to tighten (TightenMode covers the "
                         "one case where there is)")

    def test_a_pre_existing_loose_file_is_still_tightened(self):
        # An empty serve-token left at 0644 (a torn earlier mint, or one written before this change)
        # is minted over: the rename swaps in a NEW inode born 0600, so the loose mode goes with the
        # old one.
        self.f.write_text("")                # empty → a torn earlier mint → falls through to the mint
        os.chmod(self.f, 0o644)
        with contextlib.redirect_stderr(io.StringIO()):
            tok = km._load_token()
        self.assertEqual(self.f.read_text().strip(), tok)
        self.assertEqual(_mode(self.f), 0o600,
                         "a token file that already existed at 0644 must not keep that mode")

    def test_the_env_override_never_writes_the_file(self):
        # Guards this test file's own premise: with ROMP_SERVE_TOKEN set there is nothing on disk to
        # have a mode, so the cases above would be vacuous if the pop in setUp ever stopped working.
        os.environ["ROMP_SERVE_TOKEN"] = "env-token-DO-NOT-USE"
        try:
            self.assertEqual(km._load_token(), "env-token-DO-NOT-USE")
        finally:
            os.environ.pop("ROMP_SERVE_TOKEN", None)
        self.assertFalse(self.f.exists(), "the env override must not mint or persist anything")
        self.assertFalse(self.lock.exists(), "nor take the lock: there is nothing on disk to guard")


class ServeTokenFlock(_TokenFile):
    def test_racing_starters_read_one_token_and_the_lock_file_is_0600(self):
        """N starters with no token on disk. Without the lock each one reads 'absent' and mints its
        own, so N distinct tokens come back and N-1 callers hold one the file no longer has. The
        barrier inside os.urandom widens that window deterministically: on the unlocked shape every
        racer reaches the mint before any of them writes. Under the lock only the FIRST racer ever
        gets there (the rest block on flock and then read its token), so it waits out the barrier
        alone and moves on. Expected first error on the old loader: 6 != 1 at the one-token check."""
        n = 6
        gate = threading.Barrier(n)
        real_urandom = os.urandom
        mints = []

        def _urandom(k):
            mints.append(threading.get_ident())
            try:
                gate.wait(timeout=1.0)
            except threading.BrokenBarrierError:
                pass                          # under the lock the first racer is here alone: move on
            return real_urandom(k)

        out, errs = [], []

        def run():
            try:
                out.append(km._load_token())
            except BaseException as e:        # surfaced by the assertion below, never swallowed
                errs.append(repr(e))

        os.urandom = _urandom
        try:
            ts = [threading.Thread(target=run) for _ in range(n)]
            for t in ts:
                t.start()
            for t in ts:
                t.join(15)
        finally:
            os.urandom = real_urandom

        self.assertEqual(errs, [], "no racer may fail: a fresh mint is the ordinary first boot")
        self.assertEqual(len(out), n)
        self.assertEqual(len(set(out)), 1,
                         "every starter must come away holding the SAME token: %d distinct ones means "
                         "the losers now hold credentials the daemon will refuse" % len(set(out)))
        self.assertEqual(self.f.read_text().strip(), out[0])
        self.assertEqual(len(mints), 1, "exactly one starter minted; the rest read its token under the lock")
        self.assertTrue(self.lock.exists(), "the lock is a sibling file, serve-token.lock")
        self.assertEqual(_mode(self.lock), 0o600)
        self.assertEqual(self._temps(), [], "no temp survives a finished mint")


class TokenBirth(_TokenFile):
    def test_token_is_0600_from_its_first_byte_and_the_live_path_is_never_opened_for_writing(self):
        """Under a stock 022 umask. The mint must land by renaming a FINISHED temp onto the path:
        os.replace is interposed to stat and read the temp at the instant of the swap, and os.open is
        interposed to record every open of the live path (there must be none: O_TRUNC on it is the
        torn window a concurrent reader fell into). Expected first error on the old loader: the
        rename count is 0, because it wrote the live file in place."""
        os.umask(0o022)
        swaps, opens = [], []
        real_replace, real_open = os.replace, os.open

        def _replace(src, dst, *a, **k):
            swaps.append((str(src), str(dst), _mode(src), Path(src).read_text()))
            return real_replace(src, dst, *a, **k)

        def _open(path, flags, *a, **k):
            opens.append((str(path), flags))
            return real_open(path, flags, *a, **k)

        os.replace, os.open = _replace, _open
        try:
            tok = km._load_token()
        finally:
            os.replace, os.open = real_replace, real_open

        self.assertEqual(len(swaps), 1, "the mint must land by one rename of a finished temp file")
        src, dst, mode, body = swaps[0]
        self.assertEqual(dst, str(self.f))
        self.assertEqual(mode, 0o600, "the temp is born 0600 under a 022 umask: the open mode, not the umask, decides")
        self.assertEqual(body, tok, "the temp already holds the whole token when it is swapped in")
        self.assertTrue(Path(src).name.startswith("serve-token.") and src.endswith(".tmp"), src)
        self.assertEqual(Path(src).parent, self.f.parent, "same directory, so the rename is atomic")
        self.assertFalse(Path(src).exists(), "the temp is gone after the swap")
        live = [flags for path, flags in opens if path == str(self.f)]
        self.assertEqual(live, [], "the live token path is never opened for writing at all")
        self.assertEqual(_mode(self.f), 0o600)
        self.assertEqual(self.f.read_text(), tok)


class UnreadableIsNotRotated(_TokenFile):
    @unittest.skipIf(os.geteuid() == 0, "root reads through mode 0, so the fault cannot be staged")
    def test_an_unreadable_existing_token_is_a_fault_not_a_rotation(self):
        """An existing token the loader cannot read is the one case that must NOT mint: every
        client still holds the old value, and a fresh one would strand them all. Expected first
        error on the old loader: RuntimeError not raised (it returned a new random token while the
        file kept the old one, which is exactly the strand)."""
        self.f.write_text("old-token-DO-NOT-USE\n")
        os.chmod(self.f, 0)
        with self.assertRaises(RuntimeError) as cm:
            km._load_token()
        msg = str(cm.exception)
        self.assertIn(str(self.f), msg, "the refusal names the file to fix")
        self.assertIn("EACCES", msg, "and the errno, by name")
        self.assertIn("NOT replace", msg, "and says the token every client holds is still the token")
        os.chmod(self.f, 0o600)
        self.assertEqual(self.f.read_text(), "old-token-DO-NOT-USE\n", "the file is untouched, byte for byte")
        self.assertEqual(self._temps(), [], "no temp left behind by a mint that must not have started")

    def test_a_token_that_is_not_utf8_text_is_a_fault_not_a_rotation(self):
        """A read fault that is not an OSError: bytes that do not decode. It must reach the same
        refusal, naming the path, with the file untouched. Old loader: UnicodeDecodeError escaped
        its `except OSError` and the loader raised THAT (the case errors rather than fails on it)."""
        raw = b"\xff\xfe\x00tok"
        self.f.write_bytes(raw)
        os.chmod(self.f, 0o600)
        with self.assertRaises(RuntimeError) as cm:
            km._load_token()
        self.assertIn(str(self.f), str(cm.exception), "the refusal names the file to fix")
        self.assertIn("UnicodeDecodeError", str(cm.exception), "and what was wrong with it")
        self.assertEqual(self.f.read_bytes(), raw, "the file is untouched, byte for byte")
        self.assertEqual(self._temps(), [])


class StaleTempsAreSwept(_TokenFile):
    def test_another_pids_crashed_temp_is_removed_by_the_next_mint(self):
        """A `serve-token.<pid>.tmp` left by a starter that died between open and rename is swept
        before the next mint writes its own: the lock is held, so any temp beside the token is a
        crashed attempt, whichever pid named it. Old loader: no temps at all, so the planted file
        simply stays (assertFalse on its existence fails)."""
        stale = self.f.with_name("serve-token.99999.tmp")
        stale.write_text("half-written-DO-NOT-USE")
        tok = km._load_token()
        self.assertFalse(stale.exists(), "the stale temp is gone")
        self.assertEqual(self.f.read_text(), tok, "and the token was minted")
        self.assertEqual(_mode(self.f), 0o600)
        self.assertEqual(self._temps(), [])


class TightenMode(_TokenFile):
    def test_a_loose_existing_token_is_tightened_and_returned_unchanged(self):
        """A readable token at 0644 (written by hand, or by a loader older than the 0600 open) is
        the gate with the door open. Its VALUE is fine, so it is kept and the mode is repaired, and
        the repair is said once on stderr. Expected first error on the old loader: 0o644 != 0o600,
        since it only chmod'd on the mint path and a readable file never reached it."""
        self.f.write_text("keep-me-DO-NOT-USE\n")
        os.chmod(self.f, 0o644)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            tok = km._load_token()
        self.assertEqual(tok, "keep-me-DO-NOT-USE")
        self.assertEqual(_mode(self.f), 0o600)
        self.assertEqual(self.f.read_text(), "keep-me-DO-NOT-USE\n", "tightening the mode rewrites nothing")
        self.assertIn("644", err.getvalue())
        self.assertIn("0600", err.getvalue())
        self.assertEqual(self._temps(), [], "no mint happened")

    def test_a_good_0600_token_is_returned_silently(self):
        self.f.write_text("fine-DO-NOT-USE\n")
        os.chmod(self.f, 0o600)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(km._load_token(), "fine-DO-NOT-USE")
        self.assertEqual(err.getvalue(), "", "the ordinary boot says nothing")
        self.assertEqual(_mode(self.f), 0o600)


class EmptyFileMints(_TokenFile):
    def test_an_empty_or_whitespace_file_is_a_torn_mint_and_is_minted_over_aloud(self):
        """A 0-byte (or whitespace-only) token file is treated as ABSENT, not as a fault: no client
        can be holding a token that was never written, so nothing is stranded by minting over it,
        and the old in-place shape could leave exactly this behind. It is said on stderr because
        the file's existence is evidence of an earlier interrupted start. Expected first error on
        the old loader: 'empty' not found in '' (it minted, but silently)."""
        for body in ("", "  \n"):
            self._clear()
            self.f.write_text(body)
            os.chmod(self.f, 0o644)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                tok = km._load_token()
            self.assertTrue(tok, "a token was minted")
            self.assertEqual(self.f.read_text(), tok)
            self.assertEqual(_mode(self.f), 0o600, "the swapped-in inode is born 0600; the loose mode left with the old one")
            self.assertIn("empty", err.getvalue(), "the torn earlier mint is said on stderr")
            self.assertEqual(self._temps(), [])


class LockFailureIsFailClosed(_TokenFile):
    def test_no_lock_tolerates_only_a_good_0600_token(self):
        """A directory planted at the lock path makes os.open(O_RDWR|O_CREAT) fail with EISDIR, the
        same way an unwritable state dir or a foreign file there would. Without the lock the loader
        may return an existing, non-empty, 0600 token (nothing to mint, nothing to tighten) and must
        refuse everything else: minting or chmod'ing unlocked is the race again. Expected first
        error on the old loader: RuntimeError not raised at (b), since it had no lock to fail."""
        self.lock.mkdir()
        # (a) a good token: returned as is, and the missing lock is said on stderr
        self.f.write_text("good-DO-NOT-USE")
        os.chmod(self.f, 0o600)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(km._load_token(), "good-DO-NOT-USE")
        self.assertIn(str(self.lock), err.getvalue())
        # (b) a loose token: cannot be tightened without the lock, so it is a refusal, and no chmod happens
        os.chmod(self.f, 0o644)
        with self.assertRaises(RuntimeError) as cm:
            km._load_token()
        self.assertIn(str(self.lock), str(cm.exception), "the refusal names the lock path")
        self.assertIn("EISDIR", str(cm.exception))
        self.assertEqual(_mode(self.f), 0o644, "no unlocked write of any kind, not even a chmod")
        # (c) no token: cannot be minted without the lock, so it is a refusal, and nothing appears
        self.f.unlink()
        with self.assertRaises(RuntimeError):
            km._load_token()
        self.assertFalse(self.f.exists(), "nothing minted unlocked")
        self.assertEqual(self._temps(), [])


class ServeTokenLoadersMatch(unittest.TestCase):
    """The bus imports nothing from kernel/ (by design: it is one self-contained file, and the two
    daemons boot together), so postal_service.py carries its OWN copy of _serve_token_read_or_mint.
    Two layers pin the copies together. The AST identity (docstring stripped) is the gate: ANY
    divergence is red, so a fix to one copy that forgets the other cannot land. The named invariants
    are the readable layer that says WHAT a divergence broke. The gate exists because three
    postal-only mutants got past the invariants alone in review: the tighten removed, the
    lock-failure arm returning any non-empty token regardless of mode, and the empty file raising
    instead of minting; each is also killed by its own postal case in tests/test_postal_token.py."""
    KERNEL = Path(HERE).parent / "kernel" / "kernel.py"
    POSTAL = Path(HERE).parent / "postal" / "postal_service.py"

    @staticmethod
    def _body(src, name):
        m = re.search(r"^def %s\(.*?(?=^\S)" % re.escape(name), src, re.S | re.M)
        assert m, "no top-level def %s" % name
        return m.group(0)

    @staticmethod
    def _func(path, name):
        """The top-level def as an AST, with a leading docstring removed (the kernel's copy carries
        the reasoning; the bus's copy points at it)."""
        for node in ast.parse(path.read_text(), filename=str(path)).body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                first = node.body[0] if node.body else None
                if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    node.body = node.body[1:]
                return node
        raise AssertionError("no top-level def %s in %s" % (name, path.name))

    def test_both_copies_are_one_function_once_the_docstring_is_stripped(self):
        k = self._func(self.KERNEL, "_serve_token_read_or_mint")
        p = self._func(self.POSTAL, "_serve_token_read_or_mint")
        # unparse first for a readable line diff; ast.dump is the strict gate (it sees what unparse normalizes)
        self.assertEqual(ast.unparse(k).splitlines(), ast.unparse(p).splitlines(),
                         "the bus's copy has drifted from the kernel's")
        self.assertEqual(ast.dump(k), ast.dump(p))

    def test_both_copies_keep_the_invariants(self):
        for path in (self.KERNEL, self.POSTAL):
            body = self._body(path.read_text(), "_serve_token_read_or_mint")
            with self.subTest(file=path.name):
                self.assertIn("fcntl.flock(", body, "the read-or-mint runs under an flock")
                self.assertIn("fcntl.LOCK_EX", body)
                self.assertIn('".lock"', body, "the lock is the sibling serve-token.lock")
                self.assertIn("except FileNotFoundError", body, "absence is the ONLY mint trigger")
                self.assertIn("RuntimeError", body, "any other fault is a refusal, never a rotation")
                self.assertIn("os.O_EXCL", body, "the temp is created exclusively")
                self.assertIn("0o600", body)
                self.assertIn("n != len(data)", body, "the short-write check")
                self.assertIn("os.fsync(", body)
                self.assertIn("os.replace(", body, "the mint lands by rename")
                self.assertNotIn("O_TRUNC", body, "the live path is never truncated")
                self.assertNotIn("write_text(", body, "no umask-mode write of the token")

    def test_both_loaders_route_through_the_shared_shape(self):
        k = self._body(self.KERNEL.read_text(), "_load_token")
        p = self._body(self.POSTAL.read_text(), "_load_serve_token")
        self.assertIn("_serve_token_read_or_mint(", k)
        self.assertIn("_serve_token_read_or_mint(", p)
        for body in (k, p):
            self.assertNotIn("read_text(", body, "the loader itself touches no file; the helper does, under the lock")


if __name__ == "__main__":
    unittest.main(verbosity=2)
