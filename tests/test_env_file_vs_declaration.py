#!/usr/bin/env python3
"""The env file's API key source against ROMP_EXPECTED_AUTH, checked once at kernel start.

A `service.env` that selects a key source — an `ANTHROPIC_API_KEY=` line with a value, or a
`ROMP_API_KEY_REF=` line — while `ROMP_EXPECTED_AUTH=login` is in force sends every session without
an explicit Billing pick to the key (effective_auth and default_auth answer "key" whenever a source is
configured). Before this check the first sign was _note_auth_source's per-init line, after a launch had
billed the wrong account. What these tests pin (sdk_backend._check_env_file_vs_declaration):

  * =login over a key line, or over a reference line, is one problem-ring line naming the file and the
    variable — never a value — said once per process (a re-constructed backend says nothing new);
  * =key is never a contradiction: a key source in the file lands the sessions keyed, as declared;
  * undeclared is quiet, as is a declaration over a file that selects no source, whatever else the
    file carries (another service's token beside a reference is the documented shape);
  * a remembered gear Billing pick makes the declaration inert here too (_declared_auth);
  * the sentence describes what the code does: default_auth answers "key" under the flagged shape.

Synthetic keys (`sk-ant-TEST-…`), a synthetic reference, temp paths. The env-file path is pointed at
a temp dir before the loads so nothing here can read the machine's real one.
"""
import os
import tempfile
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
os.environ["ROMP_SERVICE_ENV_FILE"] = os.path.join(os.environ["XDG_STATE_HOME"], "no-such-service.env")
os.environ["ROMP_SERVICE_ENV"] = os.environ["ROMP_SERVICE_ENV_FILE"]

sb = SourceFileLoader("romp_sdk_backend_env_file_vs_declaration",
                      os.path.join(BIN, "romp_sdk_backend.py")).load_module()
ks = sb._keysrc

KEY = "sk-ant-TEST-0000"
REF = "op://test-vault/test-item/api-key"


class _Env(unittest.TestCase):
    """A temp env file at the path every reader resolves, the declaration cleared, the one-shot reset."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "service.env")
        self._before = {v: os.environ.get(v) for v in ("ROMP_SERVICE_ENV_FILE", "ROMP_SERVICE_ENV",
                                                       "ROMP_EXPECTED_AUTH", "ANTHROPIC_API_KEY",
                                                       "ROMP_API_KEY_REF")}
        os.environ["ROMP_SERVICE_ENV_FILE"] = self.path
        os.environ["ROMP_SERVICE_ENV"] = self.path
        for v in ("ROMP_EXPECTED_AUTH", "ANTHROPIC_API_KEY", "ROMP_API_KEY_REF"):
            os.environ.pop(v, None)
        self._checked = sb._ENV_FILE_AUTH_CHECKED
        sb._ENV_FILE_AUTH_CHECKED = False
        ks._CACHE = ((), "")          # the stat-identity cache is module-global

    def tearDown(self):
        for v, was in self._before.items():
            if was is None:
                os.environ.pop(v, None)
            else:
                os.environ[v] = was
        sb._ENV_FILE_AUTH_CHECKED = self._checked
        ks._CACHE = ((), "")
        ks._AUTHORITATIVE_PATHS.pop(self.path, None)

    def write_env(self, body, path=None):
        p = path or self.path
        with open(p, "w") as fh:
            fh.write(body)
        os.chmod(p, 0o600)
        ks._CACHE = ((), "")          # a same-second rewrite in a test can reuse the stat identity
        return p


class _Backend(_Env):
    """A backend on a manager whose environment carried no key at startup, so the env file is the only
    place a key source can come from. The startup stash is module-global; each test re-arms it."""

    def setUp(self):
        super().setUp()
        self.state = tempfile.mkdtemp()
        self._stash = sb._WORK_KEY
        self._file_checked = sb._KEY_FILE_CHECKED
        self._seen_fp = sb._FILE_KEY_SEEN_FP
        sb._WORK_KEY = ""                     # the startup claim, already made, found nothing
        sb._KEY_FILE_CHECKED = True           # the startup-vs-file line is asserted in tests/test_keyswap.py
        sb._FILE_KEY_SEEN_FP = ""
        self._fetch = sb._fetch_key_fast_org
        sb._fetch_key_fast_org = lambda key: None      # never a real HTTPS GET from a test
        sb._FAST_ORG_VERDICTS.clear()
        self.logged = []

    def tearDown(self):
        sb._WORK_KEY = self._stash
        sb._KEY_FILE_CHECKED = self._file_checked
        sb._FILE_KEY_SEEN_FP = self._seen_fp
        sb._fetch_key_fast_org = self._fetch
        sb._FAST_ORG_VERDICTS.clear()
        super().tearDown()

    def construct(self):
        # `log=` is a keyword: the third positional is `notify`. A line reaches self.logged only through
        # the log wire, which is what the no-value assertions read.
        return sb.SdkBackend(self.state, "/bin/true", lambda *a, **k: None,
                             log=lambda m: self.logged.append(str(m)))

    @staticmethod
    def flagged(be):
        return [p["text"] for p in be.problems() if "while ROMP_EXPECTED_AUTH=" in p["text"]]


class EnvFileVsDeclaration(_Backend):
    def test_login_declared_over_a_key_line_is_one_line_naming_the_file_and_the_variable(self):
        self.write_env("ROMP_PERF=1\n%s=%s\n" % (ks.KEY_VAR, KEY))
        os.environ["ROMP_EXPECTED_AUTH"] = "login"
        be = self.construct()
        lines = self.flagged(be)
        self.assertEqual(len(lines), 1, be.problems())
        self.assertIn(self.path, lines[0])
        self.assertIn(ks.KEY_VAR, lines[0])
        self.assertIn("ROMP_EXPECTED_AUTH=login", lines[0])
        self.assertIn("Billing pick", lines[0], "the line says what happens to billing and why")
        self.assertFalse(any(KEY in m for m in self.logged), "no log line carries the value")
        self.assertTrue(sb._ENV_FILE_AUTH_CHECKED)
        # once per process: a re-constructed backend (the WS handler's lazy build, tests) says nothing new
        self.assertEqual(self.flagged(self.construct()), [])
        self.assertEqual(sb._check_env_file_vs_declaration(be._log, self.state), "")

    def test_login_declared_over_a_reference_line_names_the_reference_variable(self):
        self.write_env("ROMP_PERF=1\n%s=%s\n" % (ks.REF_VAR, REF))
        os.environ["ROMP_EXPECTED_AUTH"] = "login"
        be = self.construct()
        lines = self.flagged(be)
        self.assertEqual(len(lines), 1, be.problems())
        self.assertIn(ks.REF_VAR, lines[0])
        self.assertNotIn(ks.KEY_VAR, lines[0])
        self.assertFalse(any(REF in m for m in self.logged), "names, never values: the reference included")

    def test_the_direct_call_returns_the_variable_it_named_and_files_a_problem(self):
        self.write_env("%s=%s\n" % (ks.REF_VAR, REF))
        os.environ["ROMP_EXPECTED_AUTH"] = "login"
        said = []
        log = lambda m, problem=None: said.append((str(m), problem))
        self.assertEqual(sb._check_env_file_vs_declaration(log, self.state), ks.REF_VAR)
        self.assertEqual([p for _, p in said], [True], "a problem-ring line, not a plain log line")
        self.assertEqual(sb._check_env_file_vs_declaration(log, self.state), "")
        self.assertEqual(len(said), 1)

    def test_the_sentence_describes_what_the_code_does(self):
        self.write_env("%s=%s\n" % (ks.KEY_VAR, KEY))
        os.environ["ROMP_EXPECTED_AUTH"] = "login"
        be = self.construct()
        self.assertEqual(len(self.flagged(be)), 1)
        self.assertEqual(be.default_auth({}), "key", "a session without an explicit pick launches keyed")

    def test_key_declared_over_a_key_source_is_quiet(self):
        for body in ("%s=%s\n" % (ks.KEY_VAR, KEY), "%s=%s\n" % (ks.REF_VAR, REF)):
            self.write_env(body)
            os.environ["ROMP_EXPECTED_AUTH"] = "key"
            be = self.construct()
            self.assertEqual(self.flagged(be), [], "the sessions land keyed, as declared: %r" % body)
            self.assertFalse(sb._ENV_FILE_AUTH_CHECKED, "a quiet pass does not spend the one shot")

    def test_undeclared_is_quiet(self):
        self.write_env("%s=%s\n" % (ks.KEY_VAR, KEY))
        be = self.construct()
        self.assertEqual(self.flagged(be), [])
        self.assertEqual(sb._check_env_file_vs_declaration(be._log, self.state), "")
        self.assertFalse(sb._ENV_FILE_AUTH_CHECKED)

    def test_login_declared_over_a_file_that_selects_no_source_is_quiet(self):
        # Other services' credentials are the installer's invited shape for this file, and the 1Password
        # service-account token beside a reference is the documented one; none of them is what a launch
        # injects as the sessions' key, so none contradicts the declaration. An EMPTY key line selects
        # nothing either (keysource: a file source with no value is not configured).
        self.write_env("ROMP_PERF=1\nROMP_DIR=/nonexistent/x\nHF_TOKEN=x\nOP_SERVICE_ACCOUNT_TOKEN=x\n"
                       "FOO_API_KEY=x\n%s=\n" % ks.KEY_VAR)
        os.environ["ROMP_EXPECTED_AUTH"] = "login"
        be = self.construct()
        self.assertEqual(self.flagged(be), [], be.problems())
        self.assertFalse(sb._ENV_FILE_AUTH_CHECKED)

    def test_a_missing_file_is_quiet(self):
        os.environ["ROMP_EXPECTED_AUTH"] = "login"
        be = self.construct()                 # no file was ever written at self.path
        self.assertEqual(self.flagged(be), [])
        self.assertFalse(sb._ENV_FILE_AUTH_CHECKED)

    def test_a_remembered_billing_pick_makes_the_declaration_inert_here_too(self):
        # Q3: set_auth's durable trace (the remembered auth default) is the pick event; from then on the
        # env declaration is stale doctrine and _note_auth_source judges against the pick. Under a login
        # pick every spawn is seeded auth=login, so the file's key wins for nobody: nothing to say.
        for pick in ("login", "key"):
            self.write_env("%s=%s\n" % (ks.KEY_VAR, KEY))
            os.environ["ROMP_EXPECTED_AUTH"] = "login"
            sb.write_sdk_default(Path(self.state), auth=pick)
            be = self.construct()
            self.assertEqual(self.flagged(be), [], "pick=%s: %r" % (pick, be.problems()))
            self.assertFalse(sb._ENV_FILE_AUTH_CHECKED)
            self.assertEqual(sb._declared_auth(Path(self.state)), (pick, "pick"))

    def test_the_check_reads_the_installers_path_variable(self):
        other = self.write_env("%s=%s\n" % (ks.KEY_VAR, KEY), path=os.path.join(self.d, "elsewhere.env"))
        os.environ["ROMP_SERVICE_ENV_FILE"] = other
        os.environ["ROMP_EXPECTED_AUTH"] = "login"
        be = self.construct()
        lines = self.flagged(be)
        self.assertEqual(len(lines), 1, be.problems())
        self.assertIn(other, lines[0])


if __name__ == "__main__":
    unittest.main()
