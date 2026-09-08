#!/usr/bin/env python3
"""main's CI never cancels itself (.github/workflows/ci.yml, 2026-09-08).

The concurrency group was `ci-<event>-<ref>` with cancel-in-progress for every event, so two merges to
main in quick succession cancelled the first merge's run, and a red main (2e9d4492) went unseen until a
later run happened to fail. Now: pull-request runs still cancel their superseded predecessor (the new
head makes the old verdict moot); pushes to main are keyed on the commit sha, one group per merge
commit, so every merge gets its own completed run (a queue would not do: a group holds at most one
pending run, so a third merge would replace the second's); a dispatch queues rather than cancels. The
event name stays in the key so a release dispatch (the macOS gate) is never cancelled by a push to the
same ref (2026-07-27). Source pins: no YAML library in the test deps, and the stanza is three lines."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
WF = os.path.join(os.path.dirname(HERE), ".github", "workflows", "ci.yml")


class CiConcurrency(unittest.TestCase):
    def setUp(self):
        self.src = open(WF).read()
        m = re.search(r"^concurrency:\n((?:  .*\n)+)", self.src, re.M)
        self.assertTrue(m, "the concurrency stanza moved - re-anchor this pin")
        self.stanza = m.group(1)

    def test_the_event_name_keys_the_group(self):
        # a release dispatch shares main's ref with every push; the event in the key keeps them apart
        self.assertIn("group: ci-${{ github.event_name }}-", self.stanza)

    def test_pushes_to_main_are_keyed_on_the_commit_sha(self):
        # one group per merge commit: never cancelled, never replaced as a pending run
        self.assertIn("${{ github.event_name == 'push' && github.sha || github.ref }}", self.stanza)

    def test_only_pull_request_runs_cancel_their_predecessor(self):
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", self.stanza)
        self.assertNotIn("cancel-in-progress: true", self.stanza, "an unconditional cancel would cancel main's own run")

    def test_the_workflow_still_runs_on_push_to_main_and_on_pull_requests(self):
        self.assertTrue(re.search(r"^on:\n  push:\n    branches: \[main\]\n  pull_request:\n", self.src, re.M),
                        "the push-to-main and pull_request triggers are the two the group tells apart")


if __name__ == "__main__":
    unittest.main()
