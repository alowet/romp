#!/usr/bin/env python3
"""The suite-wide CLAUDE_CONFIG_DIR floor (tests/conftest.py, 2026-09-08): no test resolves the REAL
~/.claude. The judge module and the event model compute their projects root at IMPORT from
CLAUDE_CONFIG_DIR (default ~/.claude), so a test that touched a per-session project dir without
patching jd.PROJECTS wrote synthetic-sid directories under the developer's real ~/.claude/projects
(thirty of them, one night). conftest now points CLAUDE_CONFIG_DIR at a fresh directory inside the
run's private temp root before any test module loads, and re-asserts it before every test, so a
module-level pop or write in one test file cannot erase the floor for the rest of the run; a test
that needs its own Claude root sets the variable in setUp, which runs after the fixture, as before.

Source pins in the style of test_supervised_floor.py, the floor observed from inside a test, from a
module loaded under it, and from a subprocess whose shell exports a value of its own."""
import os
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
# Hermetic state BEFORE any romp code loads (the repo-wide rule the state-isolation meta-test enforces).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"


def _under_the_run_root(path):
    root = os.path.realpath(os.environ["TMPDIR"])
    return os.path.realpath(str(path)).startswith(root + os.sep)


class ClaudeConfigFloor(unittest.TestCase):
    def test_conftest_sets_the_variable_at_import_and_per_test(self):
        src = open(os.path.join(HERE, "conftest.py")).read()
        head, _, body = src.partition("@pytest.fixture(autouse=True)\ndef _no_real_claude_config")
        self.assertTrue(body, "the fixture header moved - re-anchor this pin")
        self.assertIn('os.environ["CLAUDE_CONFIG_DIR"] = _CLAUDE_CONFIG', head, "the import-time floor")
        self.assertIn('os.environ["CLAUDE_CONFIG_DIR"] = _CLAUDE_CONFIG', body, "the per-test re-assert")
        self.assertIn('tempfile.mkdtemp(prefix="romp-tests-claude-")', head, "a fresh dir inside the run root")

    def test_the_floor_holds_inside_a_test(self):
        cfg = os.environ.get("CLAUDE_CONFIG_DIR")
        self.assertTrue(cfg, "CLAUDE_CONFIG_DIR is set for every test")
        self.assertTrue(_under_the_run_root(cfg), "…to a directory inside the run's private temp root")
        self.assertFalse(os.path.realpath(cfg).startswith(os.path.realpath(str(Path.home() / ".claude"))),
                         "never the real ~/.claude")

    def test_a_module_loaded_under_the_floor_resolves_its_projects_root_inside_it(self):
        # the judge computes PROJECTS at import: a test that imports it and writes a project dir lands
        # inside the floor, never under the real ~/.claude/projects (the incident's shape)
        jd = SourceFileLoader("romp_judge_claude_cfg_floor", os.path.join(ROOT, "bin", "romp-judge")).load_module()
        self.assertEqual(Path(jd.PROJECTS), Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects")
        self.assertTrue(_under_the_run_root(jd.PROJECTS), str(jd.PROJECTS))
        d = jd._proj_dir("/TESTDIR/notes-api")
        self.assertTrue(_under_the_run_root(d), str(d))

    def test_the_floor_overrides_a_value_the_shell_exports(self):
        """A subprocess whose environment carries its own CLAUDE_CONFIG_DIR (a developer pointing their
        Claude at a custom root) runs only this module's behavioural checks, which pass only if
        conftest's floor replaced that value rather than defaulting to it."""
        env = dict(os.environ, CLAUDE_CONFIG_DIR=os.path.join(tempfile.gettempdir(), "synthetic-claude-root-not-a-floor"))
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                            os.path.join(HERE, "test_claude_config_floor.py") + "::ClaudeConfigFloor::test_the_floor_holds_inside_a_test",
                            os.path.join(HERE, "test_claude_config_floor.py") + "::ClaudeConfigFloor::test_a_module_loaded_under_the_floor_resolves_its_projects_root_inside_it"],
                           env=env, capture_output=True, text=True, timeout=180, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout[-800:] + r.stderr[-400:])
        self.assertNotIn("synthetic-claude-root-not-a-floor", r.stdout)


if __name__ == "__main__":
    unittest.main()
