#!/usr/bin/env python3
"""The PR tier POLICY (the maintainers' decisions of 2026-09-07), as a pure function over synthetic PR
fixtures — scripts/ci/tier_policy.py. The workflow only fetches data and calls it; every rule here is
pinned on fixtures so the gate's meaning lives in tests, not in a YAML step.

Tiers: docs (documentation only) merges on green; fix needs an approval OR seven unchanged days with no
changes requested; feature needs an approval; major-feature needs an approval AND a linked issue that
someone other than the author has commented on. Any PR touching .github/ needs an approval regardless
(the base-branch check cannot stop a PR-branch job from posting a same-named success on pull_request
events, so a human must look). Zero or two tier labels fail here too (belt and braces with the label
check). An approval is the LATEST review by a reviewer who is not the author, holds write/admin/maintain,
is APPROVED, and reviewed the CURRENT head; dismissed reviews never count. The seven-day clock is the
server-stamped first "Tier policy" check run for the current head (never a commit date, which is free
to forge), falling back to the PR's created_at.

Synthetic only: invented logins, placeholder shas, TESTHOST-free."""
import importlib.util
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
# Hermetic state BEFORE any romp code loads (the repo-wide rule the state-isolation meta-test
# enforces): the policy module itself touches no state, but the rule is uniform on purpose.
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
SPEC = importlib.util.spec_from_file_location(
    "tier_policy", os.path.join(os.path.dirname(HERE), "scripts", "ci", "tier_policy.py"))
tp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tp)

HEAD = "1111111111111111111111111111111111111111"
OLD = "2222222222222222222222222222222222222222"
NOW = 1_800_000_000
DAY = 86400


def pr(**kw):
    """A synthetic PR fixture with sensible defaults; override per test."""
    base = {"number": 42, "author": "author-a", "labels": ["fix"], "head_sha": HEAD,
            "files": ["kernel/kernel.py"], "reviews": [], "permissions": {},
            "first_check_at": None, "created_at": NOW - DAY, "now": NOW, "body": "",
            "issues": {}}
    base.update(kw)
    return base


def review(user, state="APPROVED", sha=HEAD, submitted=NOW - 60, dismissed=False):
    return {"user": user, "state": state, "commit_id": sha, "submitted_at": submitted,
            "dismissed": dismissed}


MAINTAINERS = {"maint-b": "write", "admin-c": "admin"}


class Labels(unittest.TestCase):
    def test_zero_tier_labels_fail(self):
        v = tp.evaluate(pr(labels=[]))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("exactly one", v["summary"].lower())

    def test_two_tier_labels_fail(self):
        v = tp.evaluate(pr(labels=["fix", "feature"]))
        self.assertEqual(v["conclusion"], "failure")

    def test_non_tier_labels_are_ignored(self):
        v = tp.evaluate(pr(labels=["docs", "good-first-issue"], files=["docs/guide.md"]))
        self.assertEqual(v["conclusion"], "success")


class Docs(unittest.TestCase):
    def test_docs_dir_and_markdown_anywhere_pass_on_green(self):
        v = tp.evaluate(pr(labels=["docs"], files=["docs/guide.md", "README.md", "kernel/README.md"]))
        self.assertEqual(v["conclusion"], "success")

    def test_a_non_doc_file_breaks_the_docs_tier(self):
        v = tp.evaluate(pr(labels=["docs"], files=["docs/guide.md", "kernel/kernel.py"]))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("kernel/kernel.py", v["summary"])

    def test_markdown_under_github_or_scripts_is_never_docs(self):
        for f in (".github/PULL_REQUEST_TEMPLATE.md", "scripts/ci/README.md"):
            v = tp.evaluate(pr(labels=["docs"], files=[f]))
            self.assertEqual(v["conclusion"], "failure", f)

    def test_VERSION_is_not_docs(self):
        # the release script's PR touches exactly this file — the open question for the maintainers
        v = tp.evaluate(pr(labels=["docs"], files=["VERSION"]))
        self.assertEqual(v["conclusion"], "failure")


class Approval(unittest.TestCase):
    def test_a_maintainer_approval_on_the_current_head_counts(self):
        v = tp.evaluate(pr(labels=["feature"], reviews=[review("maint-b")], permissions=MAINTAINERS))
        self.assertEqual(v["conclusion"], "success")

    def test_the_author_cannot_approve_their_own_pr(self):
        v = tp.evaluate(pr(labels=["feature"], author="maint-b", reviews=[review("maint-b")],
                           permissions=MAINTAINERS))
        self.assertEqual(v["conclusion"], "failure")

    def test_a_reviewer_without_write_does_not_count(self):
        v = tp.evaluate(pr(labels=["feature"], reviews=[review("drive-by-d")],
                           permissions={"drive-by-d": "read"}))
        self.assertEqual(v["conclusion"], "failure")

    def test_an_approval_on_an_older_head_needs_re_approval(self):
        v = tp.evaluate(pr(labels=["feature"], reviews=[review("maint-b", sha=OLD)], permissions=MAINTAINERS))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("head", v["summary"].lower())

    def test_only_the_LATEST_review_per_reviewer_counts(self):
        # approved, then changes requested: the latest word stands
        v = tp.evaluate(pr(labels=["feature"], permissions=MAINTAINERS,
                           reviews=[review("maint-b", submitted=NOW - 600),
                                    review("maint-b", state="CHANGES_REQUESTED", submitted=NOW - 60)]))
        self.assertEqual(v["conclusion"], "failure")
        # changes requested, then approved: also the latest word
        v = tp.evaluate(pr(labels=["feature"], permissions=MAINTAINERS,
                           reviews=[review("maint-b", state="CHANGES_REQUESTED", submitted=NOW - 600),
                                    review("maint-b", submitted=NOW - 60)]))
        self.assertEqual(v["conclusion"], "success")

    def test_a_dismissed_approval_does_not_count(self):
        v = tp.evaluate(pr(labels=["feature"], reviews=[review("maint-b", dismissed=True)],
                           permissions=MAINTAINERS))
        self.assertEqual(v["conclusion"], "failure")

    def test_a_comment_review_is_not_an_approval(self):
        v = tp.evaluate(pr(labels=["feature"], reviews=[review("maint-b", state="COMMENTED")],
                           permissions=MAINTAINERS))
        self.assertEqual(v["conclusion"], "failure")


class Fix(unittest.TestCase):
    def test_a_fix_with_approval_passes(self):
        v = tp.evaluate(pr(labels=["fix"], reviews=[review("maint-b")], permissions=MAINTAINERS))
        self.assertEqual(v["conclusion"], "success")

    def test_a_fix_passes_after_seven_unchanged_days_from_the_first_check_run(self):
        v = tp.evaluate(pr(labels=["fix"], first_check_at=NOW - 7 * DAY - 1))
        self.assertEqual(v["conclusion"], "success")
        self.assertIn("seven", v["summary"].lower())

    def test_a_fix_under_seven_days_waits(self):
        v = tp.evaluate(pr(labels=["fix"], first_check_at=NOW - 7 * DAY + 3600))
        self.assertEqual(v["conclusion"], "failure")

    def test_the_clock_falls_back_to_created_at_when_no_run_exists(self):
        v = tp.evaluate(pr(labels=["fix"], first_check_at=None, created_at=NOW - 8 * DAY))
        self.assertEqual(v["conclusion"], "success")

    def test_the_clock_never_reads_a_commit_date(self):
        # a forged old commit date on the head must not shorten the wait: the fixture carries one
        # and the policy must ignore it
        v = tp.evaluate(pr(labels=["fix"], first_check_at=NOW - DAY, head_commit_date=NOW - 30 * DAY))
        self.assertEqual(v["conclusion"], "failure")

    def test_changes_requested_blocks_the_seven_day_path(self):
        v = tp.evaluate(pr(labels=["fix"], first_check_at=NOW - 8 * DAY, permissions=MAINTAINERS,
                           reviews=[review("maint-b", state="CHANGES_REQUESTED")]))
        self.assertEqual(v["conclusion"], "failure")

    def test_changes_requested_on_an_OLD_head_still_blocks_the_clock(self):
        # the seven-day path asks "did any reviewer object?" — an objection on an older head is
        # still an objection until that reviewer says otherwise
        v = tp.evaluate(pr(labels=["fix"], first_check_at=NOW - 8 * DAY, permissions=MAINTAINERS,
                           reviews=[review("maint-b", state="CHANGES_REQUESTED", sha=OLD)]))
        self.assertEqual(v["conclusion"], "failure")


class MajorFeature(unittest.TestCase):
    ISSUE_OK = {7: {"exists": True, "is_pr": False, "comments": ["maint-b"]}}

    def test_approval_plus_a_discussed_linked_issue_passes(self):
        v = tp.evaluate(pr(labels=["major-feature"], reviews=[review("maint-b")], permissions=MAINTAINERS,
                           body="Design discussion in #7.", issues=self.ISSUE_OK))
        self.assertEqual(v["conclusion"], "success")

    def test_an_issue_url_counts_too(self):
        v = tp.evaluate(pr(labels=["major-feature"], reviews=[review("maint-b")], permissions=MAINTAINERS,
                           body="See https://github.com/romp-on/romp/issues/7 for the discussion.",
                           issues=self.ISSUE_OK))
        self.assertEqual(v["conclusion"], "success")

    def test_approval_without_a_linked_issue_fails(self):
        v = tp.evaluate(pr(labels=["major-feature"], reviews=[review("maint-b")], permissions=MAINTAINERS))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("issue", v["summary"].lower())

    def test_a_linked_issue_with_only_the_authors_comments_is_not_a_discussion(self):
        v = tp.evaluate(pr(labels=["major-feature"], reviews=[review("maint-b")], permissions=MAINTAINERS,
                           body="#7", issues={7: {"exists": True, "is_pr": False, "comments": ["author-a"]}}))
        self.assertEqual(v["conclusion"], "failure")

    def test_a_linked_PR_number_is_not_an_issue(self):
        v = tp.evaluate(pr(labels=["major-feature"], reviews=[review("maint-b")], permissions=MAINTAINERS,
                           body="#7", issues={7: {"exists": True, "is_pr": True, "comments": ["maint-b"]}}))
        self.assertEqual(v["conclusion"], "failure")

    def test_a_discussed_issue_without_approval_fails(self):
        v = tp.evaluate(pr(labels=["major-feature"], body="#7", issues=self.ISSUE_OK))
        self.assertEqual(v["conclusion"], "failure")


class GithubDir(unittest.TestCase):
    def test_touching_github_requires_approval_regardless_of_tier(self):
        v = tp.evaluate(pr(labels=["fix"], files=[".github/workflows/ci.yml"], first_check_at=NOW - 30 * DAY))
        self.assertEqual(v["conclusion"], "failure", "the seven-day path never clears a .github change")
        self.assertIn(".github", v["summary"])
        v = tp.evaluate(pr(labels=["fix"], files=[".github/workflows/ci.yml"], reviews=[review("maint-b")],
                           permissions=MAINTAINERS))
        self.assertEqual(v["conclusion"], "success")

    def test_docs_label_on_a_github_file_fails_twice_over(self):
        v = tp.evaluate(pr(labels=["docs"], files=[".github/workflows/ci.yml"]))
        self.assertEqual(v["conclusion"], "failure")


class Verdict(unittest.TestCase):
    def test_the_verdict_names_the_tier_and_says_why(self):
        v = tp.evaluate(pr(labels=["feature"]))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("feature", v["title"])
        self.assertTrue(v["summary"], "a failing verdict always says what would clear it")


class WorkflowPins(unittest.TestCase):
    """The workflow is the policy's only door; its trust-model facts are source-pinned."""

    def setUp(self):
        self.wf = open(os.path.join(os.path.dirname(HERE), ".github", "workflows", "tier-policy.yml")).read()
        self.fetch = open(os.path.join(os.path.dirname(HERE), "scripts", "ci", "tier_policy_check.py")).read()

    def test_the_check_run_is_named_tier_policy(self):
        self.assertIn("name: Tier policy", self.wf)
        self.assertIn('CHECK_NAME = "Tier policy"', self.fetch)

    def _triggers(self):
        # the trigger MAPPING, not a grep of the file: the comments deliberately name the events they
        # exclude, and a grep would trip on its own explanation
        on = [l for l in self.wf.split("\n") if l and not l.startswith("#")]
        block, inside = [], False
        for l in on:
            if l.startswith("on:"):
                inside = True; continue
            if inside and l and not l.startswith(" "):
                break
            if inside and l.startswith("  ") and not l.startswith("   ") and l.strip().endswith(":"):
                block.append(l.strip().rstrip(":"))
        return block

    def test_the_gate_runs_from_the_base_branch_never_the_pr(self):
        trig = self._triggers()
        self.assertIn("pull_request_target", trig)
        self.assertNotIn("pull_request", trig, "a pull_request trigger would run the PR's copy")
        self.assertNotIn("pull_request_review", trig,
                         "the review event runs in the PR's merge-commit context - approvals ride the schedule")
        self.assertIn("schedule", trig)
        self.assertIn("workflow_dispatch", trig)

    def test_the_token_holds_only_what_the_verdict_needs(self):
        self.assertIn("checks: write", self.wf)
        for line in ("pull-requests: read", "issues: read", "contents: read"):
            self.assertIn(line, self.wf)
        self.assertNotIn("contents: write", self.wf)
        self.assertNotIn("pull-requests: write", self.wf)

    def test_the_job_never_runs_pr_code(self):
        # the only checkout is the base tree; no ref: pointing at the PR head, and the fetcher is
        # API reads plus one check-run POST
        self.assertNotIn("ref:", self.wf)
        self.assertNotIn("head.sha", self.wf)
        self.assertEqual(self.fetch.count('_req("POST"'), 1, "exactly one write: the verdict")
        self.assertIn('"/repos/%s/check-runs"', self.fetch)

    def test_the_clock_reads_check_runs_not_commit_dates(self):
        self.assertIn("check-runs?check_name=", self.fetch)
        self.assertNotIn("commit.committer", self.fetch)
        self.assertNotIn("commit.author", self.fetch)


if __name__ == "__main__":
    unittest.main()
