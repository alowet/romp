#!/usr/bin/env python3
"""The suite-wide credential floor (tests/conftest.py, 2026-09-08): no test starts with a credential the
developer's shell configured. Every session shell under a romp-managed manager inherits the manager's
environment, so a test that constructs a backend or asks default_auth would otherwise read the developer's
own configuration: 73 tests across eight modules went red on a box running a key command while CI, which
exports none of these, stayed green. conftest pops the names at import and before every test.

The list is the code's own: kernel/credentials.py FLOOR_ENV_NAMES (the retired provider names the boot
check refuses, the login tokens the backend claims, the declaration, the 1Password CLI's names) and
FLOOR_ENV_PREFIXES, with sdk_backend.AUTH_ENV_NAMES inside it. Source pins plus the floor observed from
inside a test and from a subprocess whose shell is fully configured."""
import ast
import os
import subprocess
import sys
import tempfile
import unittest

# Hermetic state BEFORE any romp code loads (the credentials module below is romp code, and the meta-test
# tests/test_state_isolation_order.py holds every loading module to the same preamble).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)


def _assigned(path, name):
    """The literal tuple assigned to `name` at module level in `path`, read without importing the module."""
    tree = ast.parse(open(path).read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError("%s assigns no %s" % (path, name))


def _credentials():
    """kernel/credentials.py loaded by path: constants and functions, no state root, no network."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("romp_credentials_floor_pin", os.path.join(ROOT, "kernel", "credentials.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _floor_names():
    return _assigned(os.path.join(HERE, "conftest.py"), "KEY_SOURCE_ENV_NAMES")


class KeySourceFloor(unittest.TestCase):
    def test_the_list_is_the_codes_own(self):
        """Every name the code treats as a credential or a retired provider is on the list, and nothing else,
        so the floor never removes a variable the code does not read."""
        conftest = os.path.join(HERE, "conftest.py")
        names = set(_floor_names())
        prefixes = _assigned(conftest, "KEY_SOURCE_ENV_PREFIXES")
        cred = _credentials()
        auth_names = _assigned(os.path.join(ROOT, "kernel", "sdk_backend.py"), "AUTH_ENV_NAMES")
        self.assertEqual(names, set(cred.FLOOR_ENV_NAMES))
        self.assertTrue(set(auth_names) <= names, "the backend's credential names are floored too")
        self.assertTrue(set(cred.RETIRED_VARS) <= names, "the retired provider names the boot check refuses")
        self.assertEqual(tuple(prefixes), tuple(cred.FLOOR_ENV_PREFIXES))

    def test_conftest_scrubs_at_import_and_per_test(self):
        src = open(os.path.join(HERE, "conftest.py")).read()
        head, _, body = src.partition("@pytest.fixture(autouse=True)\ndef _no_real_service_env")
        self.assertTrue(body, "the fixture header moved: re-anchor this pin")
        self.assertIn("\n_scrub_key_source_env()\n", head, "the import-time floor, before any test module loads")
        self.assertIn("    _scrub_key_source_env()\n", body, "the per-test re-assert")

    def test_the_floor_holds_for_a_bare_run_under_a_configured_shell(self):
        """A subprocess whose environment carries a synthetic value under EVERY name on the list, plus an
        OP_SESSION_ name, runs only this module's behavioural check, which passes only if conftest's floor
        did. This is the developer's box: a manager exports its environment to every shell."""
        env = dict(os.environ)
        for name in _floor_names():
            env[name] = "synthetic-value-for-%s" % name.lower()
        env["ROMP_EXPECTED_AUTH"] = "login"
        env["OP_SESSION_testaccount"] = "synthetic-session"
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                            os.path.join(HERE, "test_key_source_floor.py") + "::KeySourceFloor::test_the_floor_holds_inside_a_test"],
                           env=env, capture_output=True, text=True, timeout=180, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout[-800:] + r.stderr[-400:])

    def test_the_floor_holds_inside_a_test(self):
        for name in _floor_names():
            self.assertNotIn(name, os.environ, "a configured shell's %s must not reach a test" % name)
        self.assertEqual([k for k in os.environ if k.startswith("OP_SESSION_")], [])


if __name__ == "__main__":
    unittest.main()
