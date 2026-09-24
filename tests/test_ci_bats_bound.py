#!/usr/bin/env python3
"""The bats step of CI carries a per-test bound from bats itself (.github/workflows/ci.yml, 2026-09-16).

The macOS bats leg (a manual dispatch) was cancelled at the job's 35-minute ceiling on every run, nameless:
the job annotation says only that the maximum execution time was exceeded, and the TAP stream stops at the
last test that finished. BATS_TEST_TIMEOUT is bats-core's own bound (since 1.8, in the pinned 1.11.1 and in
Homebrew's 1.14.0 alike): a background sleep, then pkill or ps on the test's children, and the test's TAP
line ends "# timeout after Ns", so a hung test fails in minutes and is named. No coreutils timeout, which the
macOS image lacks. Source pins, as tests/test_ci_workflow_concurrency.py: no YAML library in the test deps."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
WF = os.path.join(os.path.dirname(HERE), ".github", "workflows", "ci.yml")


class BatsStepBound(unittest.TestCase):
    def setUp(self):
        src = open(WF).read()
        m = re.search(r"^      - name: Run bats\n((?:        .*\n)*?)        run: (bats .*)\n", src, re.M)   # zero lines between: the step without an env
        self.assertTrue(m, "the Run bats step moved or was renamed: re-anchor this pin")
        self.head, self.cmd = m.group(1), m.group(2)

    def test_the_step_sets_bats_own_per_test_timeout(self):
        m = re.search(r'^          BATS_TEST_TIMEOUT: "?(\d+)"?$', self.head, re.M)
        self.assertTrue(m, "no BATS_TEST_TIMEOUT in the step's env: a hung test would eat the job's whole budget, nameless")
        secs = int(m.group(1))
        self.assertGreaterEqual(secs, 120, "below two minutes the slowest legitimate macOS test (the 60 s romp-serve probes) is at risk")
        self.assertLessEqual(secs, 600, "above ten minutes a hang still eats most of the 35-minute job")

    def test_the_step_still_runs_every_bats_file(self):
        self.assertIn("tests/*.bats", self.cmd)
        self.assertIn("--print-output-on-failure", self.cmd)


class PythonJobCeiling(unittest.TestCase):
    """The python job's ceiling is per cell (2026-09-16): the macOS cells run the same suite on the image's slower
    runners, and the 3.10 cell was cancelled at the job's 25-minute ceiling after 25 min 27 s on one dispatch having
    completed in 24 min 43 s on the one before, so the release's combined proof could die on a minute's margin. Forty
    minutes then; sixty since 2026-09-24, when the release dispatch (run 35976250043) had the 3.13 macOS cell green in
    38 min 52 s and the 3.10 macOS cell cancelled at 40 min 20 s with no failure in its log, the same cells having taken
    33 to 35 minutes on the dispatch five hours before. The 3.10 cell reached 90 percent 36 min 40 s into its pytest
    step, and its own tail from there to the pytest step's end ran 6 min 56 s and 9 min 46 s on runs 35952964334 and
    35623182872 (the 3.13 cell's 5 min 38 s and 4 min 51 s are the wrong term: the three StateIsolationOrder tests
    take 193 s and 279 s on 3.10), so the cut cell's suite sits near 43.5 to 46.5 minutes; the rule (the suite plus
    the 600 s per-test timeout plus setup) gives 54.5 to 57, the floor is 57 and the ceiling 60, so a revert to 40 or
    to the first cut's 55 goes red, and the next growth step is splitting or sharding the 3.10 cell, not a higher cap.
    Linux 25 to 35 the same day by the same rule: the 3.10
    Linux cell took 19 min 34 s on the dispatch of 2026-09-24 03:48 UTC (run 35952964334), under six minutes short of
    the cap where about 20 plus 10 plus setup is about 31; its floor is 30 and its ceiling 45."""
    def setUp(self):
        src = open(WF).read()
        m = re.search(r"^  python:\n((?:    .*\n|\n)+?)    strategy:\n", src, re.M)
        self.assertTrue(m, "the python job's head moved: re-anchor this pin")
        self.head = m.group(1)

    def test_macos_cells_get_sixty_minutes_and_linux_thirty_five_and_neither_reverts_below_its_floor(self):
        m = re.search(r"^    timeout-minutes: \$\{\{ matrix\.os == 'macos-latest' && (\d+) \|\| (\d+) \}\}$", self.head, re.M)
        self.assertTrue(m, "the python job's timeout-minutes is not the per-cell expression (macos-latest && N || M)")
        macos, linux = int(m.group(1)), int(m.group(2))
        self.assertGreaterEqual(macos, 57, "the macOS cells need the margin: on run 35976250043 (2026-09-24) the 3.13 cell was green at "
                                "38 min 52 s and the 3.10 cell cancelled at 40 min 20 s by the 40-minute cap, at 90 percent 36 min 40 s "
                                "into its pytest step with its own tail from there 6 min 56 s to 9 min 46 s on runs 35952964334 and "
                                "35623182872, so its suite sits near 43.5 to 46.5 minutes; that plus the 600 s per-test timeout plus "
                                "setup is 54.5 to 57, so a cap below 57 cuts a green run (the next step is sharding the cell, not a raise)")
        self.assertLessEqual(macos, 60, "past an hour a hung macOS cell eats the dispatch")
        self.assertGreaterEqual(linux, 30, "the Linux cells need the margin: the 3.10 Linux cell took 19 min 34 s on run 35952964334 "
                                "(2026-09-24) under a 25-minute cap; about 20 minutes of suite plus the 600 s per-test timeout plus "
                                "setup is about 31, so a cap below 30 cuts a green run")
        self.assertLessEqual(linux, 45, "a hung Linux cell past 45 minutes holds every PR's required check for nothing")


class ExtensionJobCeiling(unittest.TestCase):
    """The vscode-extension job runs the served labs, which grow with every lab added: PR 1790's run was cancelled at the
    job's 25-minute ceiling after 25 min 04 s mid lab (2026-09-16), and under the 40-minute cap that followed, PR 2061's red
    run 35821212036 (attempt 1) was cut at 40 min 15 s. Sixty minutes (2026-09-23): the rule is a served step of up to 38 min
    plus the 600 s per-test timeout plus about 2 min of earlier steps, about 50. After the raise the served step took 31.62
    to 39.15 min over the sixty green main runs from 2026-09-23 06:37 UTC to 2026-09-24 10:44 UTC (35.97 to 37.77 over the
    sixteen consecutive runs from f824eb06 to f2108d89, and 37.92 on 23c2a9960 shortly before them), the closest call the
    run on b598eae9 ending its served step 41 min 19 s after the job started; with a step of up to 39 min the rule's figure
    is about 51, the floor, and the ceiling stays 60, so the pin keeps the file's range style and a revert to 40 or 50
    goes red on it."""
    def test_the_extension_job_gets_sixty_minutes_and_never_reverts_below_the_rules_figure(self):
        src = open(WF).read()
        m = re.search(r"^  vscode-extension:\n((?:    .*\n|\n)+?)    defaults:\n", src, re.M)
        self.assertTrue(m, "the extension job's head moved: re-anchor this pin")
        t = re.search(r"^    timeout-minutes: (\d+)$", m.group(1), re.M)
        self.assertTrue(t, "the extension job has no plain timeout-minutes line")
        self.assertGreaterEqual(int(t.group(1)), 51, "the served step ran 31.62 to 39.15 min over the sixty green main runs after the raise (2026-09-23 to "
                                                     "2026-09-24; 41 min 19 s to its end at the closest call, b598eae9): up to 39 min plus the 600 s per-test "
                                                     "timeout plus about 2 min of earlier steps is about 51, so a cap below it cuts a green run")
        self.assertLessEqual(int(t.group(1)), 60, "past an hour a hung lab eats the run")


if __name__ == "__main__":
    unittest.main()
