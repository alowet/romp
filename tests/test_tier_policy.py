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
import urllib.error

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
            "first_check_at": None, "head_floor": None, "created_at": NOW - DAY, "now": NOW, "body": "",
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

    def test_dismissing_a_later_objection_does_not_revive_an_earlier_approval(self):
        # a DISMISSED review is the reviewer's latest word (a non-approval), never an erasure: anyone
        # with write can dismiss, and both maintainers hold write - the review's catch
        v = tp.evaluate(pr(labels=["feature"], permissions=MAINTAINERS,
                           reviews=[review("maint-b", submitted=NOW - 600),
                                    review("maint-b", state="CHANGES_REQUESTED", submitted=NOW - 60, dismissed=True)]))
        self.assertEqual(v["conclusion"], "failure")

    def test_a_dismissed_objection_does_not_close_the_seven_day_path(self):
        v = tp.evaluate(pr(labels=["fix"], first_check_at=NOW - 8 * DAY, created_at=NOW - 9 * DAY,
                           permissions=MAINTAINERS,
                           reviews=[review("maint-b", state="CHANGES_REQUESTED", dismissed=True)]))
        self.assertEqual(v["conclusion"], "success", "a dismissed objection is not a standing objection")

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
        v = tp.evaluate(pr(labels=["fix"], first_check_at=NOW - 7 * DAY - 1, created_at=NOW - 8 * DAY))
        self.assertEqual(v["conclusion"], "success")
        self.assertIn("seven", v["summary"].lower())

    def test_a_fix_under_seven_days_waits(self):
        v = tp.evaluate(pr(labels=["fix"], first_check_at=NOW - 7 * DAY + 3600))
        self.assertEqual(v["conclusion"], "failure")

    def test_the_clock_falls_back_to_created_at_when_no_run_exists(self):
        v = tp.evaluate(pr(labels=["fix"], first_check_at=None, created_at=NOW - 8 * DAY))
        self.assertEqual(v["conclusion"], "success")

    def test_a_force_push_back_to_an_old_head_restarts_the_clock(self):
        # the review's critical catch: check runs are keyed by sha, so a sha seen for a minute on
        # day 0 and force-pushed back on day 7 read as seven days old. head_floor is the later of
        # created_at and every force-push / reopen / ready-for-review event - the clock is bound to
        # the head's time as THIS PR's reviewable head, not the sha's age
        v = tp.evaluate(pr(labels=["fix"], first_check_at=NOW - 8 * DAY, head_floor=NOW - 3600))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("became the PR's head", v["summary"])

    def test_a_new_pr_reusing_an_old_head_starts_its_own_clock(self):
        # PR B opened from PR A's branch: A's old check runs must not spend B's seven days
        v = tp.evaluate(pr(labels=["fix"], first_check_at=NOW - 30 * DAY, created_at=NOW - DAY,
                           head_floor=NOW - DAY))
        self.assertEqual(v["conclusion"], "failure")

    def test_the_clock_is_the_later_of_head_arrival_and_first_run(self):
        v = tp.evaluate(pr(labels=["fix"], first_check_at=NOW - 8 * DAY, head_floor=NOW - 9 * DAY))
        self.assertEqual(v["conclusion"], "success", "both bounds are older than seven days")

    def test_the_record_carries_no_commit_date_for_the_clock_to_read(self):
        # the clock's only inputs are first_check_at, head_floor and created_at - the fetcher's record
        # has no commit-date field at all (pinned in FetcherShapes below), so a forged commit date has
        # no way into the policy
        import types
        consts = " ".join(str(c) for f in vars(tp).values() if isinstance(f, types.FunctionType)
                          for c in f.__code__.co_consts)
        self.assertIn("first_check_at", consts)
        self.assertIn("head_floor", consts)
        for forged in ("committer", "author_date", "commit_date"):
            self.assertNotIn(forged, consts)

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
    ISSUE_OK = {7: {"exists": True, "is_pr": False, "user": "author-a", "comments": ["maint-b"]}}

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
                           body="#7", issues={7: {"exists": True, "is_pr": False, "user": "author-a",
                                                   "comments": ["author-a"]}}))
        self.assertEqual(v["conclusion"], "failure")

    def test_the_issue_opener_is_a_participant(self):
        # the ordinary flow - a maintainer files the issue, the author replies and implements
        v = tp.evaluate(pr(labels=["major-feature"], reviews=[review("maint-b")], permissions=MAINTAINERS,
                           body="#7", issues={7: {"exists": True, "is_pr": False, "user": "maint-b",
                                                   "comments": ["author-a"]}}))
        self.assertEqual(v["conclusion"], "success")

    def test_a_linked_PR_number_is_not_an_issue(self):
        v = tp.evaluate(pr(labels=["major-feature"], reviews=[review("maint-b")], permissions=MAINTAINERS,
                           body="#7", issues={7: {"exists": True, "is_pr": True, "user": "maint-b",
                                                   "comments": ["maint-b"]}}))
        self.assertEqual(v["conclusion"], "failure")

    def test_a_discussed_issue_without_approval_fails(self):
        v = tp.evaluate(pr(labels=["major-feature"], body="#7", issues=self.ISSUE_OK))
        self.assertEqual(v["conclusion"], "failure")


class GithubDir(unittest.TestCase):
    def test_the_gates_own_code_needs_an_approval_regardless_of_tier(self):
        # the review's catch: the policy is checked out from main and run with checks:write, so a
        # fix-tier PR rewriting scripts/ci/tier_policy.py through the seven-day path would grade itself
        v = tp.evaluate(pr(labels=["fix"], files=["scripts/ci/tier_policy.py"], first_check_at=NOW - 30 * DAY,
                           head_floor=NOW - 30 * DAY))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("scripts/ci/tier_policy.py", v["summary"])
        v = tp.evaluate(pr(labels=["fix"], files=["scripts/ci/tier_policy.py"], reviews=[review("maint-b")],
                           permissions=MAINTAINERS))
        self.assertEqual(v["conclusion"], "success")

    def test_touching_github_requires_approval_regardless_of_tier(self):
        v = tp.evaluate(pr(labels=["fix"], files=[".github/workflows/ci.yml"], first_check_at=NOW - 30 * DAY,
                           head_floor=NOW - 30 * DAY))
        self.assertEqual(v["conclusion"], "failure", "the seven-day path never clears a .github change")
        self.assertIn(".github", v["summary"])
        v = tp.evaluate(pr(labels=["fix"], files=[".github/workflows/ci.yml"], reviews=[review("maint-b")],
                           permissions=MAINTAINERS))
        self.assertEqual(v["conclusion"], "success")

    def test_docs_label_on_a_github_file_fails_as_not_documentation(self):
        v = tp.evaluate(pr(labels=["docs"], files=[".github/workflows/ci.yml"]))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn(".github/workflows/ci.yml", v["summary"], "named as not-documentation")

    def test_the_pre_rename_label_reads_as_docs_during_the_transition(self):
        v = tp.evaluate(pr(labels=["tests-only"], files=["docs/guide.md"]))
        self.assertEqual(v["conclusion"], "success")
        v = tp.evaluate(pr(labels=["tests-only", "docs"], files=["docs/guide.md"]))
        self.assertEqual(v["conclusion"], "failure", "both spellings at once are two tier labels")


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
        self.assertIn('key="check_runs"', self.fetch, "the check-runs endpoint is an object; read its list")
        self.assertIn("filter=all", self.fetch, "the default `latest` collapses the hourly runs to the newest")
        # the ONLY /commits/ request is the check-runs listing - no GET of the commit itself, whose
        # author/committer dates are the author's to set
        import re
        commits = re.findall(r'/commits/%s([^"]*)"', self.fetch)
        self.assertEqual(commits, ["/check-runs?check_name=%s&filter=all"], commits)
        self.assertIn('RESET_EVENTS = ("head_ref_force_pushed", "reopened", "ready_for_review")', self.fetch,
                      "the head's arrival is bounded by the server-stamped timeline events")

    def test_the_job_name_is_the_check_name(self):
        # the pull_request_target job's own check run is what stamps a head's arrival; the JOB (not
        # just the workflow) must carry the check name - pinned at the jobs level explicitly
        jobs = self.wf[self.wf.index("\njobs:"):]
        self.assertIn("    name: Tier policy", jobs)
        self.assertNotIn('["committer"]', self.fetch)
        self.assertNotIn('["author"]["date"]', self.fetch)

    def test_the_three_tier_label_lists_agree(self):
        wf = open(os.path.join(os.path.dirname(HERE), ".github", "workflows", "pr-tier.yml")).read()
        tmpl = open(os.path.join(os.path.dirname(HERE), ".github", "PULL_REQUEST_TEMPLATE.md")).read()
        import re
        in_jq = set(re.findall(r'\. == "([a-z-]+)"', wf))
        expected = set(tp.TIERS) | set(tp.TIER_ALIASES)
        self.assertEqual(in_jq, expected, "the label check and the policy name the same tiers")
        for t in tp.TIERS:
            self.assertIn("`%s`" % t, tmpl, "the PR template lists every tier")


class FetcherShapes(unittest.TestCase):
    """build_record against the DOCUMENTED response shapes, with _req stubbed - no network. The
    review's critical catch lived here: the check-runs endpoint is an object, not a list."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "tier_policy_check", os.path.join(os.path.dirname(HERE), "scripts", "ci", "tier_policy_check.py"))
        self.tc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tc)
        self.calls = []
        test = self

        def fake_req(method, path, token, body=None):
            test.calls.append((method, path))
            path = path.split("?")[0]                  # _get_all appends per_page; match the route
            if "/check-runs" in path:
                return {"total_count": 1, "check_runs": [{"started_at": "2026-09-01T00:00:00Z"}]}, {}
            if path.endswith("/pulls/42"):
                return {"head": {"sha": HEAD}, "user": {"login": "author-a"}, "labels": [{"name": "fix"}],
                        "created_at": "2026-08-30T00:00:00Z", "body": "fixes #7"}, {}
            if "/files" in path:
                return [{"filename": "kernel/kernel.py"}], {}
            if "/reviews" in path:
                return [{"user": {"login": "maint-b"}, "state": "APPROVED", "commit_id": HEAD,
                         "submitted_at": "2026-09-02T00:00:00Z"}], {}
            if "/collaborators/" in path:
                if test.perm_error:
                    raise urllib.error.HTTPError(path, test.perm_error, "x", {}, None)
                return {"permission": "write"}, {}
            if path.endswith("/timeline"):
                return test.timeline, {}
            if path.endswith("/issues/7/comments"):
                return [{"user": {"login": "maint-b"}}, {"user": {"login": "stale[bot]", "type": "Bot"}}], {}
            if path.endswith("/issues/7"):
                return {"number": 7, "user": {"login": "author-a"}}, {}
            if "/issues/" in path and path.endswith("/comments"):
                return [], {}
            if "/issues/" in path:
                test.issue_fetches.append(path)
                return {"number": 0, "user": {"login": "author-a"}}, {}
            raise AssertionError("unexpected request " + path)
        self.perm_error = None
        self.timeline = []
        self.issue_fetches = []
        self.tc._req = fake_req

    def test_build_record_survives_the_documented_shapes_and_has_no_commit_date(self):
        rec = self.tc.build_record("romp-on/romp", 42, "tok", now=NOW)
        self.assertEqual(rec["first_check_at"], self.tc._iso("2026-09-01T00:00:00Z"),
                         "the clock is the server-stamped first check run for this head")
        self.assertEqual(set(rec), {"number", "author", "labels", "head_sha", "files", "reviews", "permissions",
                                    "first_check_at", "head_floor", "created_at", "now", "body", "issues"},
                         "the record has exactly the documented keys - no commit date can reach the policy")
        self.assertEqual(rec["permissions"], {"maint-b": "write"})
        self.assertEqual(rec["issues"], {7: {"exists": True, "is_pr": False, "user": "author-a",
                                             "comments": ["maint-b"]}}, "the bot commenter is filtered")
        self.assertEqual(rec["head_floor"], rec["created_at"], "no reset events → the floor is created_at")
        self.assertEqual(self.tc.evaluate(rec)["conclusion"], "success")
        self.assertFalse(any("/commits/%s\"" % HEAD in p or p.endswith("/commits/" + HEAD) for _, p in self.calls),
                         "the commit itself is never fetched")

    def test_a_force_push_on_the_timeline_raises_the_head_floor(self):
        self.timeline = [{"event": "head_ref_force_pushed", "created_at": "2026-09-02T12:00:00Z"},
                         {"event": "labeled", "created_at": "2026-09-03T12:00:00Z"}]
        rec = self.tc.build_record("romp-on/romp", 42, "tok", now=NOW)
        self.assertEqual(rec["head_floor"], self.tc._iso("2026-09-02T12:00:00Z"),
                         "the latest reset event, not a label change, bounds the clock")

    def test_issue_refs_are_deduped_and_capped(self):
        # a 64 KiB body of "#1 #1 #1 ..." must not become tens of thousands of requests
        pr_body = " ".join("#%d" % n for n in ([1] * 50 + list(range(2, 40))))
        real = self.tc._req

        def with_body(method, path, token, body=None):
            if path.split("?")[0].endswith("/pulls/42"):
                return {"head": {"sha": HEAD}, "user": {"login": "author-a"}, "labels": [{"name": "fix"}],
                        "created_at": "2026-08-30T00:00:00Z", "body": pr_body}, {}
            return real(method, path, token, body)
        self.tc._req = with_body
        self.tc.build_record("romp-on/romp", 42, "tok", now=NOW)
        fetched = {p.split("/issues/")[1].split("/")[0] for p in self.issue_fetches}
        self.assertLessEqual(len(fetched), self.tc.MAX_ISSUE_REFS)
        self.assertEqual(len([p for p in self.issue_fetches if p.endswith("/issues/1")]), 1, "deduped")

    def test_a_non_404_permission_error_is_loud_not_a_silent_denial(self):
        self.perm_error = 403
        with self.assertRaises(urllib.error.HTTPError):
            self.tc.build_record("romp-on/romp", 42, "tok", now=NOW)

    def test_a_404_permission_means_not_a_collaborator(self):
        self.perm_error = 404
        rec = self.tc.build_record("romp-on/romp", 42, "tok", now=NOW)
        self.assertEqual(rec["permissions"], {"maint-b": "none"})
        self.assertFalse(tp._approved(rec)[0], "a non-collaborator never approves")

    def test_all_open_isolates_one_prs_failure_from_the_rest(self):
        posted = []
        real = self.tc._req

        def isolating(method, path, token, body=None):
            p = path.split("?")[0]
            if method == "POST":
                posted.append(body["head_sha"][:4] + ":" + body["conclusion"])
                return {}, {}
            if p.endswith("/pulls"):
                return [{"number": 41}, {"number": 42}], {}
            if p.endswith("/pulls/41"):
                return {"head": {"sha": "4" * 40}, "user": {"login": "author-a"}, "labels": [{"name": "fix"}],
                        "created_at": "2026-08-30T00:00:00Z", "body": ""}, {}
            if "/pulls/41/" in p:
                raise urllib.error.HTTPError(path, 500, "boom", {}, None)
            return real(method, path, token, body)
        self.tc._req = isolating
        os.environ["GITHUB_TOKEN"] = "tok"
        try:
            rc = self.tc.main(["--all-open"])
        finally:
            os.environ.pop("GITHUB_TOKEN", None)
        self.assertEqual(rc, 1, "the run reads red because one PR could not be evaluated")
        self.assertIn("4444:failure", posted, "…and that PR got a LOUD failing verdict, not silence")
        self.assertIn(HEAD[:4] + ":success", posted, "…while the other PR still got its verdict")


if __name__ == "__main__":
    unittest.main()
