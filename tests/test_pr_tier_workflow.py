#!/usr/bin/env python3
"""The "Exactly one tier label" check (.github/workflows/pr-tier.yml) judges the PR's CURRENT labels, read
from the API, and runs one job at a time per PR without cancelling the one in progress.

The race this pins closed (pull 1039, 2026-09-08): `gh pr create --label` fires `opened` with an empty
label snapshot and `labeled` a second later; the opened run judged the snapshot and failed, and when its
job COMPLETED two seconds after the labeled run's, the merge box (which follows the newest same-named
check run by time) took that stale failure and the PR read blocked with auto-merge armed. Two things make
ordering irrelevant now: every run reads the labels the PR carries at the moment it looks (the API, with
the job's read-only token), and a concurrency group keyed on the PR number runs one job at a time, which
makes completion times monotonic in execution order, so the run that executes last is the newest. GitHub's
default queue replaces a superseded PENDING run with the newer one (whose check run completes later
still), so the last executed run has always read the world after the last event. Cancel-in-progress is
deliberately off: cancelling the in-progress run risks its "cancelled" check run completing after the
survivor's, and a cancelled required check blocks.

The step's script is run for real, with `gh` replaced by a shim on PATH that prints a canned label list
(or fails), so the zero / one / two / alias / unreadable cases are behaviour, not a grep. Source pins
cover what the script cannot show: the trigger types, the read-only token (the workflow's one
permissions block, no job-level override), the concurrency stanza and the check's name, which the
ruleset requires by name and app and so must never change. The accepted label SET is read back from the
workflow, not pinned here: tests/test_tier_policy.py (the tier-policy change) pins it against the policy.

Synthetic only: an invented repository name and PR number, no network."""
import os
import re
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
WF = os.path.join(os.path.dirname(HERE), ".github", "workflows", "pr-tier.yml")


def _run_block(src):
    """The text of the step's `run: |` block, de-indented (no YAML library in the test deps; the
    workflow is small and its shape is pinned here)."""
    m = re.search(r"^( +)run: \|\n((?:\1  .*(?:\n|\Z)|\n)+)", src, re.M)
    if not m:
        raise AssertionError("no `run: |` block found")
    indent = len(m.group(1)) + 2
    script = "".join(line[indent:] if line.strip() else line for line in m.group(2).splitlines(True))
    # a file saved without its final newline used to drop `exit 1` and fail two tests as `0 != 1`,
    # pointing nowhere near the extractor (review find): the block's last line is pinned instead
    if script.rstrip().splitlines()[-1].strip() != "exit 1":
        raise AssertionError("the extracted script does not end in `exit 1`; the extractor lost a line")
    return script


def _accepted_labels(src):
    return set(re.findall(r'\. == "([a-z-]+)"', src))


class LabelCountBehaviour(unittest.TestCase):
    """The script against a shimmed `gh`."""

    def setUp(self):
        self.src = open(WF).read()
        self.script = _run_block(self.src)
        self.bin = tempfile.mkdtemp()
        self.accepted = sorted(_accepted_labels(self.src))
        self.assertTrue(self.accepted, "the jq filter names the tier labels")

    def _gh(self, body, fail=False):
        p = os.path.join(self.bin, "gh")
        with open(p, "w") as fh:
            fh.write("#!/bin/sh\n" + ("exit 1\n" if fail else "printf '%s' '" + body + "'\n"))
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)

    def _run(self):
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ.get("PATH", ""),
                   GITHUB_REPOSITORY="example/repo", PR_NUMBER="7", GH_TOKEN="synthetic")
        return subprocess.run(["bash", "-e", "-c", self.script], env=env, capture_output=True, text=True, timeout=60)

    def test_exactly_one_tier_label_passes(self):
        self._gh('["%s"]' % self.accepted[0])
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_non_tier_label_beside_the_tier_label_is_ignored(self):
        self._gh('["good-first-issue", "%s"]' % self.accepted[0])
        self.assertEqual(self._run().returncode, 0)

    def test_zero_tier_labels_fail(self):
        # the opened event's world, as the API reports it BEFORE the label call lands
        self._gh('[]')
        r = self._run()
        self.assertEqual(r.returncode, 1)
        self.assertIn("0 tier labels", r.stdout)

    def test_two_tier_labels_fail(self):
        self._gh('["%s", "%s"]' % (self.accepted[0], self.accepted[1]))
        r = self._run()
        self.assertEqual(r.returncode, 1)
        self.assertIn("2 tier labels", r.stdout)

    def test_an_unreadable_api_is_a_failed_check_not_a_guess(self):
        self._gh("", fail=True)
        r = self._run()
        self.assertEqual(r.returncode, 1)
        self.assertIn("Could not read", r.stdout)

    def test_the_script_reads_the_pulls_endpoint_not_the_payload(self):
        self.assertIn('gh api "repos/$GITHUB_REPOSITORY/pulls/$PR_NUMBER"', self.script)
        self.assertNotIn("github.event.pull_request.labels", self.src, "the payload snapshot is never consulted")


class WorkflowPins(unittest.TestCase):
    def setUp(self):
        self.src = open(WF).read()

    def test_the_check_name_is_unchanged(self):
        # the ruleset requires the check by this name and the Actions app; renaming it would silently
        # un-require it
        self.assertIn("    name: Exactly one tier label\n", self.src)

    def test_every_label_changing_event_reruns_it(self):
        m = re.search(r"pull_request:\n\s+types: \[([^\]]+)\]", self.src)
        types = {t.strip() for t in m.group(1).split(",")}
        self.assertTrue({"opened", "reopened", "labeled", "unlabeled", "synchronize"} <= types, types)

    def test_runs_for_one_pr_never_cancel_the_one_in_progress(self):
        self.assertIn("concurrency:\n  group: pr-tier-${{ github.event.pull_request.number }}\n"
                      "  cancel-in-progress: false\n", self.src)

    def test_the_token_is_read_only_and_passed_to_gh(self):
        self.assertIn("permissions:\n  pull-requests: read\n", self.src)
        # ONE permissions block, the workflow's: a job-level `permissions:` replaces the workflow's grant
        # for that job, so a write there would hand gh a write token past a pin that read only the top
        # (review find); and no non-comment line grants a write anywhere
        self.assertEqual(self.src.count("permissions:"), 1)
        code = "\n".join(l for l in self.src.splitlines() if not l.lstrip().startswith("#"))
        self.assertNotIn("write", code)
        self.assertIn("GH_TOKEN: ${{ github.token }}", self.src)
        self.assertNotIn("actions/checkout", self.src, "no checkout: nothing from the PR's tree runs")
        self.assertNotIn("uses:", self.src, "no third-party action")


if __name__ == "__main__":
    unittest.main()
