#!/usr/bin/env python3
"""The suite-wide KEY-SOURCE floor (tests/conftest.py, 2026-09-08): every session shell under a romp-managed
manager inherits the manager's credentials — the startup key, the runtime providers (ROMP_API_KEY_CMD,
ROMP_API_KEY_REF), the auth declaration, the competing token credentials and 1Password's own names — and a
test that constructs a backend, resolves a key or asks default_auth then reads the DEVELOPER'S configuration.
73 tests across eight modules went red on a box running the command key source while CI, which exports
none of these, stayed green. conftest pops every such name at import and before every test; a test that
wants a source sets a synthetic one itself. Source pins in the style of test_supervised_floor.py, the list
checked against the CODE'S constants (never a hand-kept copy), and the floor observed from a subprocess
whose environment carries synthetic values under every name.

Synthetic values only (`sk-ant-TEST-…`, an invented reference and command); nothing here reads a real one."""
import ast
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
# Hermetic state BEFORE any romp code loads (the repo-wide rule the state-isolation meta-test enforces):
# keysource itself touches no state root, but the rule is uniform on purpose.
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor


def _assigned(path, name):
    """The value a module's top-level `NAME = <literal>` assigns, read from its SOURCE through the ast (no
    import: sdk_backend is heavy, and a constant read as text cannot have been changed by anything a test
    process did). Literals only; a tuple built from other names is read through _keysource() instead."""
    tree = ast.parse(open(path).read(), path)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("%s not found in %s" % (name, path))


def _keysource():
    """kernel/keysource.py loaded by path: a pure module (constants and functions, no state root, no
    network), so importing it inside a test is safe; its SOURCE_VARS is a tuple of names, not literals."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("romp_keysource_floor_pin", os.path.join(ROOT, "kernel", "keysource.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # dataclasses resolve a class's module through sys.modules
    spec.loader.exec_module(mod)
    return mod


def _floor_names():
    return _assigned(os.path.join(HERE, "conftest.py"), "KEY_SOURCE_ENV_NAMES")


class KeySourceFloor(unittest.TestCase):
    def test_the_list_is_the_codes_own(self):
        """Every name keysource or sdk_backend consults for a key source or a credential is on the list —
        and nothing else, so the floor never removes a variable the code does not read."""
        conftest = os.path.join(HERE, "conftest.py")
        names = set(_floor_names())
        prefixes = _assigned(conftest, "KEY_SOURCE_ENV_PREFIXES")
        ks = _keysource()
        auth_names = _assigned(os.path.join(ROOT, "kernel", "sdk_backend.py"), "AUTH_ENV_NAMES")
        expected = set(ks.SOURCE_VARS) | set(ks.OP_ENV_NAMES) | set(auth_names) | {"ROMP_EXPECTED_AUTH"}
        self.assertEqual(names, expected)
        self.assertEqual(tuple(prefixes), (ks.OP_ENV_PREFIX,))
        self.assertTrue(all(ks.is_op_env_name(n) for n in ks.OP_ENV_NAMES), "the op names are the ones claim_op_env takes")

    def test_conftest_scrubs_at_import_and_per_test(self):
        src = open(os.path.join(HERE, "conftest.py")).read()
        head, _, body = src.partition("@pytest.fixture(autouse=True)\ndef _no_real_service_env")
        self.assertTrue(body, "the fixture header moved - re-anchor this pin")
        self.assertIn("\n_scrub_key_source_env()\n", head, "the import-time floor, before any test module loads")
        self.assertIn("    _scrub_key_source_env()\n", body, "the per-test re-assert")

    def test_the_floor_holds_for_a_bare_run_under_a_configured_shell(self):
        """A subprocess whose environment carries a synthetic value under EVERY name on the list, plus an
        OP_SESSION_ name, runs only this module's behavioural check, which passes only if conftest's floor
        did. This is the developer's box: a manager on ROMP_API_KEY_CMD exports it to every shell."""
        env = dict(os.environ)
        for name in _floor_names():
            env[name] = "synthetic-value-for-%s" % name.lower()
        env["ANTHROPIC_API_KEY"] = "sk-ant-TEST-0000"
        env["ROMP_API_KEY_CMD"] = "/opt/test/fetch-api-key"
        env["ROMP_API_KEY_REF"] = "op://test-vault/test-item/api-key"
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
