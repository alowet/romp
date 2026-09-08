#!/usr/bin/env python3
"""The "Exactly one tier label" check (.github/workflows/pr-tier.yml) judges the PR's CURRENT labels, read
from the API, and its runs for one PR are serialized, never cancelled.

The race this pins closed (pull 1039, 2026-09-08): `gh pr create --label` fires `opened` with an empty
label snapshot and `labeled` a second later; the opened run judged the snapshot and failed, and when its
job finished two seconds AFTER the labeled run's, the newest same-named check run was that stale failure
and the PR read blocked with auto-merge armed. Two things make ordering irrelevant now: every run reads
the labels the PR carries at the moment it looks (the API, with the job's read-only token), and a
concurrency group keyed on the PR number queues the runs so the newest check run is the last event's.
Cancel-in-progress would be WRONG here: a cancelled run's check run concludes "cancelled", and when
that run started later than the survivor it is the newest, and a cancelled required check blocks.

The step's script is run for real, with `gh` replaced by a shim on PATH that prints a canned label list
(or fails), so the zero / one / two / alias / unreadable cases are behaviour, not a grep. Source pins
cover what the script cannot show: the trigger types, the token, the concurrency stanza and the check's
name, which the ruleset requires by name and app and so must never change.

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
    m = re.search(r"^( +)run: \|\n((?:\1  .*\n|\n)+)", src, re.M)
    if not m:
        raise AssertionError("no `run: |` block found")
    indent = len(m.group(1)) + 2
    return "".join(line[indent:] if line.strip() else line for line in m.group(2).splitlines(True))


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

    def test_runs_for_one_pr_are_serialized_never_cancelled(self):
        self.assertIn("concurrency:\n  group: pr-tier-${{ github.event.pull_request.number }}\n"
                      "  cancel-in-progress: false\n", self.src)

    def test_the_token_is_read_only_and_passed_to_gh(self):
        self.assertIn("permissions:\n  pull-requests: read\n", self.src)
        self.assertNotIn("write", self.src.split("jobs:")[0].split("permissions:")[1].split("\n\n")[0])
        self.assertIn("GH_TOKEN: ${{ github.token }}", self.src)
        self.assertNotIn("actions/checkout", self.src, "no checkout: nothing from the PR's tree runs")
        self.assertNotIn("uses:", self.src, "no third-party action")


if __name__ == "__main__":
    unittest.main()
