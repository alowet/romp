#!/usr/bin/env python3
"""The PR tier POLICY as a pure function over synthetic PR fixtures: scripts/ci/tier_policy.py, the
repository owner's rules of 2026-09-08, by tier and by the AUTHOR's role. The workflow only fetches data
and calls it; every rule here is pinned on fixtures so the gate's meaning lives in tests, not in a YAML step.

Roles are read from the author's collaborator permission in the record's permissions map: admin is the
repository owner, write or maintain a member, anyone else (including an author the map lacks, as a fork
PR's author is) a contributor. Members and contributors are gated alike; admin is the role that changes a
gate.

Tiers: docs and fix are ONE tier under two labels (tests-only is the pre-rename spelling of docs) and merge
on green for every author: the check requires no approval. feature merges on green when the author is an
admin (the owner's features merge straight away); by anyone else it needs an APPROVED review by an admin
other than the author on the current head (the owner looks first). major-feature needs, for every author,
a linked issue that someone other than the author has commented on (the opener alone does not count); a
non-admin author additionally needs that admin approval. Any PR touching .github/ or scripts/ci/, the
gate's own workflow and code, needs an admin's approval regardless of tier when the author is not an admin
(the base-branch check cannot stop a PR-branch job from posting a same-named success on pull_request
events, and nobody but the owner may rewrite the policy through a PR the check cannot see); an admin author
is exempt. A standing CHANGES_REQUESTED by a maintainer (write, maintain or admin) other than the author
holds a PR of any tier until that reviewer lifts it. No tier has a time-based path: the record carries no
time field and nothing in the policy reads one. Zero or two tier labels fail here too (belt and braces
with the label check). An approval is a reviewer's STANDING, their latest APPROVED / CHANGES_REQUESTED /
DISMISSED review (comment-only reviews never change standing; a dismissed approval never counts, whoever
dismissed it; a dismissed objection clears only when the reviewer dismissed it THEMSELVES, so the author
cannot dismiss the peer's objection away), by an admin other than the author, APPROVED, on the CURRENT
head. A renamed file counts under both paths; a file listing the API truncated makes the unseen files
guarded.

Synthetic only: invented logins, placeholder shas, TESTHOST-free."""
import importlib.util
import os
import re
import tempfile
import types
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
NOW = 1_800_000_000   # orders one reviewer's reviews (submitted_at); the policy has no clock to compare it to
DAY = 86400           # only for the stale clock keys NoTimePath feeds the policy, which must ignore them


def pr(**kw):
    """A synthetic PR fixture with sensible defaults; override per test. No time field: the fetcher
    records none (pinned in FetcherShapes) and the policy reads none (pinned in NoTimePath)."""
    base = {"number": 42, "author": "author-a", "labels": ["fix"], "head_sha": HEAD,
            "files": ["kernel/kernel.py"], "reviews": [], "permissions": {},
            "files_truncated": False, "body": "", "issues": {}}
    base.update(kw)
    return base


def review(user, state="APPROVED", sha=HEAD, submitted=NOW - 60, dismissed=False, dismissed_by=None):
    """`state` is the review's ORIGINAL state (the fetcher recovers it from the review_dismissed
    timeline event for a dismissed one); `dismissed_by` is the login that dismissed it."""
    return {"user": user, "state": state, "commit_id": sha, "submitted_at": submitted,
            "dismissed": dismissed, "dismissed_by": dismissed_by}


# Roles as the check reads them, from the collaborator permission the fetcher records: admin-c holds admin
# (the repository owner); maint-b holds write (a member). author-a, the default author, is absent from
# MAINTAINERS (a contributor, as a fork PR's author is); MEMBER_AUTHOR and ADMIN_AUTHOR are the same map
# with the default author given write or admin, so a test varies the author's role the way the check
# reads it, through the map, never through the login.
MAINTAINERS = {"maint-b": "write", "admin-c": "admin"}
MEMBER_AUTHOR = dict(MAINTAINERS, **{"author-a": "write"})
ADMIN_AUTHOR = dict(MAINTAINERS, **{"author-a": "admin"})
ROLES = (("a contributor", MAINTAINERS), ("a member", MEMBER_AUTHOR), ("an admin", ADMIN_AUTHOR))


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


class Roles(unittest.TestCase):
    """The author's role is the collaborator permission the fetcher recorded for them; a login the map
    lacks is not an admin (the stricter gate applies, fail closed)."""

    def test_admin_is_read_from_the_permissions_map(self):
        self.assertTrue(tp._is_admin(pr(permissions=ADMIN_AUTHOR)))
        self.assertFalse(tp._is_admin(pr(permissions=MEMBER_AUTHOR)), "write is a member, not an admin")
        self.assertFalse(tp._is_admin(pr(permissions=dict(MAINTAINERS, **{"author-a": "maintain"}))),
                         "maintain is a member too")
        self.assertFalse(tp._is_admin(pr(permissions=MAINTAINERS)), "absent from the map: a contributor")
        self.assertFalse(tp._is_admin(pr(permissions={})), "an empty map makes nobody an admin")
        self.assertTrue(tp._is_admin(pr(permissions=MAINTAINERS), "admin-c"))
        self.assertFalse(tp._is_admin(pr(permissions=MAINTAINERS), "maint-b"))

    def test_members_and_contributors_are_gated_alike(self):
        # the gates below differ by admin or not; a member and a contributor grade the same on every
        # tier and on the guard, with and without an admin's approval
        for kw in (dict(labels=["feature"]),
                   dict(labels=["feature"], reviews=[review("admin-c")]),
                   dict(labels=["major-feature"], body="#7", issues=MajorFeature.ISSUE_OK),
                   dict(labels=["major-feature"], body="#7", issues=MajorFeature.ISSUE_OK, reviews=[review("admin-c")]),
                   dict(labels=["fix"], files=[".github/workflows/ci.yml"]),
                   dict(labels=["fix"], files=[".github/workflows/ci.yml"], reviews=[review("admin-c")])):
            a = tp.evaluate(pr(permissions=MAINTAINERS, **kw))
            b = tp.evaluate(pr(permissions=MEMBER_AUTHOR, **kw))
            self.assertEqual(a["conclusion"], b["conclusion"], kw)


class OnGreen(unittest.TestCase):
    """docs and fix: one tier under two labels, merging on green for every author (the owner, 2026-09-08).
    The check requires no approval; a standing change request by a maintainer other than the author is the
    one hold, and only that reviewer's next word lifts it."""

    def test_a_fix_passes_on_green_with_no_reviews(self):
        v = tp.evaluate(pr(labels=["fix"]))
        self.assertEqual(v["conclusion"], "success")
        self.assertIn("merges on green", v["summary"])
        self.assertIn("no approval is required", v["summary"])

    def test_a_docs_pr_passes_the_same_way(self):
        v = tp.evaluate(pr(labels=["docs"], files=["docs/guide.md"]))
        self.assertEqual(v["conclusion"], "success")
        self.assertIn("merges on green", v["summary"])

    def test_every_author_role_merges_on_green(self):
        for role, perms in ROLES:
            for tier in ("docs", "fix"):
                v = tp.evaluate(pr(labels=[tier], permissions=perms))
                self.assertEqual(v["conclusion"], "success", "%s by %s" % (tier, role))
                self.assertIn("every author", v["summary"])

    def test_docs_and_fix_are_one_tier(self):
        # the label names the tier; it does not filter files. The 2026-09-07 text made docs
        # documentation-only because it alone merged on green; with fix merging on green too the two
        # labels are one tier to the check, and the same record grades the same under either
        for files in (["docs/guide.md", "README.md"], ["kernel/kernel.py"], ["VERSION"]):
            a = tp.evaluate(pr(labels=["docs"], files=files))
            b = tp.evaluate(pr(labels=["fix"], files=files))
            self.assertEqual((a["conclusion"], b["conclusion"]), ("success", "success"), files)

    def test_the_pre_rename_label_is_the_same_tier(self):
        v = tp.evaluate(pr(labels=["tests-only"], files=["docs/guide.md"]))
        self.assertEqual(v["conclusion"], "success")
        v = tp.evaluate(pr(labels=["tests-only", "docs"], files=["docs/guide.md"]))
        self.assertEqual(v["conclusion"], "failure", "both spellings at once are two tier labels")
        v = tp.evaluate(pr(labels=["docs", "fix"]))
        self.assertEqual(v["conclusion"], "failure", "one tier, still two labels: the count rule is unchanged")

    def test_an_approval_is_not_required_and_changes_nothing(self):
        for who in ("maint-b", "admin-c"):
            v = tp.evaluate(pr(labels=["fix"], reviews=[review(who)], permissions=MAINTAINERS))
            self.assertEqual(v["conclusion"], "success")
            self.assertIn("merges on green", v["summary"])

    def test_a_standing_change_request_by_another_maintainer_holds_a_fix(self):
        v = tp.evaluate(pr(labels=["fix"], permissions=MAINTAINERS,
                           reviews=[review("maint-b", state="CHANGES_REQUESTED")]))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("Changes requested by maint-b", v["summary"])
        self.assertIn("until they say otherwise", v["summary"])

    def test_the_same_objection_holds_a_docs_pr(self):
        v = tp.evaluate(pr(labels=["docs"], files=["docs/guide.md"], permissions=MAINTAINERS,
                           reviews=[review("maint-b", state="CHANGES_REQUESTED")]))
        self.assertEqual(v["conclusion"], "failure")

    def test_the_objection_holds_an_admin_authors_fix_too(self):
        # a standing objection by a maintainer other than the author blocks every tier for every author
        v = tp.evaluate(pr(labels=["fix"], permissions=ADMIN_AUTHOR,
                           reviews=[review("maint-b", state="CHANGES_REQUESTED")]))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("maint-b", v["summary"])

    def test_an_objection_on_an_older_head_still_holds(self):
        # an objection asks "did a maintainer object?"; a push does not answer it, that reviewer does
        v = tp.evaluate(pr(labels=["fix"], permissions=MAINTAINERS,
                           reviews=[review("maint-b", state="CHANGES_REQUESTED", sha=OLD)]))
        self.assertEqual(v["conclusion"], "failure")

    def test_another_maintainers_approval_does_not_lift_the_objection(self):
        # the check requires no approval, so an approval has no role in this tier: an objection is an
        # objection until its reviewer says otherwise, an admin's approval included
        v = tp.evaluate(pr(labels=["fix"], permissions=MAINTAINERS,
                           reviews=[review("maint-b", state="CHANGES_REQUESTED"), review("admin-c")]))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("maint-b", v["summary"])

    def test_the_objectors_own_approval_lifts_it(self):
        v = tp.evaluate(pr(labels=["fix"], permissions=MAINTAINERS,
                           reviews=[review("maint-b", state="CHANGES_REQUESTED", submitted=NOW - 600),
                                    review("maint-b", submitted=NOW - 60)]))
        self.assertEqual(v["conclusion"], "success")

    def test_an_objection_by_a_reviewer_without_write_does_not_hold(self):
        v = tp.evaluate(pr(labels=["fix"], permissions={"drive-by-d": "read"},
                           reviews=[review("drive-by-d", state="CHANGES_REQUESTED")]))
        self.assertEqual(v["conclusion"], "success", "the rule names a maintainer other than the author")

    def test_the_authors_own_change_request_is_not_an_objection(self):
        v = tp.evaluate(pr(labels=["fix"], permissions=MEMBER_AUTHOR,
                           reviews=[review("author-a", state="CHANGES_REQUESTED")]))
        self.assertEqual(v["conclusion"], "success", "the rule names a maintainer OTHER than the author")


class Feature(unittest.TestCase):
    """feature: by an admin author, merges on green (the owner's features merge straight away); by a member
    or a contributor, one approval by an admin other than the author on the current head (the owner looks
    first). No issue, no discussion, no waiting period."""

    def test_an_admin_authors_feature_passes_with_no_reviews(self):
        v = tp.evaluate(pr(labels=["feature"], permissions=ADMIN_AUTHOR))
        self.assertEqual(v["conclusion"], "success")
        self.assertIn("admin author merges on green", v["summary"])

    def test_an_admin_authors_feature_is_still_held_by_a_standing_objection(self):
        v = tp.evaluate(pr(labels=["feature"], permissions=ADMIN_AUTHOR,
                           reviews=[review("maint-b", state="CHANGES_REQUESTED")]))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("Changes requested by maint-b", v["summary"])

    def test_a_member_authors_feature_fails_without_an_admin_approval(self):
        v = tp.evaluate(pr(labels=["feature"], permissions=MEMBER_AUTHOR))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("no approval by an admin", v["summary"])

    def test_a_member_authors_feature_fails_with_a_write_holders_approval(self):
        v = tp.evaluate(pr(labels=["feature"], permissions=MEMBER_AUTHOR, reviews=[review("maint-b")]))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("maint-b approved but does not hold admin", v["summary"])

    def test_a_member_authors_feature_passes_with_an_admin_approval_on_the_current_head(self):
        v = tp.evaluate(pr(labels=["feature"], permissions=MEMBER_AUTHOR, reviews=[review("admin-c")]))
        self.assertEqual(v["conclusion"], "success")
        self.assertIn("Approved by admin-c", v["summary"])

    def test_a_member_authors_feature_fails_with_an_admin_approval_on_an_older_head(self):
        v = tp.evaluate(pr(labels=["feature"], permissions=MEMBER_AUTHOR, reviews=[review("admin-c", sha=OLD)]))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("older head", v["summary"])

    def test_a_contributors_feature_is_gated_like_a_members(self):
        v = tp.evaluate(pr(labels=["feature"], permissions=MAINTAINERS))
        self.assertEqual(v["conclusion"], "failure")
        v = tp.evaluate(pr(labels=["feature"], permissions=MAINTAINERS, reviews=[review("maint-b")]))
        self.assertEqual(v["conclusion"], "failure", "a write-holder's approval meets no gate")
        v = tp.evaluate(pr(labels=["feature"], permissions=MAINTAINERS, reviews=[review("admin-c")]))
        self.assertEqual(v["conclusion"], "success")

    def test_an_author_the_permissions_map_lacks_is_not_an_admin(self):
        # an older fetcher's record, or a hand-built one, without the author's permission: fail closed
        v = tp.evaluate(pr(labels=["feature"], permissions={}))
        self.assertEqual(v["conclusion"], "failure")

    def test_a_discussed_issue_is_not_asked_of_a_feature_and_does_not_stand_in_for_the_approval(self):
        v = tp.evaluate(pr(labels=["feature"], permissions=MEMBER_AUTHOR, body="#7", issues=MajorFeature.ISSUE_OK))
        self.assertEqual(v["conclusion"], "failure")
        v = tp.evaluate(pr(labels=["feature"], permissions=MEMBER_AUTHOR, reviews=[review("admin-c")]))
        self.assertEqual(v["conclusion"], "success", "no issue linked, and none needed")


class Approval(unittest.TestCase):
    """What counts as an approval, and how a reviewer's standing is read. Exercised on a member author's
    feature (which needs an admin's approval) and on fix (where only an objection matters)."""

    def test_an_admin_approval_on_the_current_head_counts(self):
        v = tp.evaluate(pr(labels=["feature"], permissions=MEMBER_AUTHOR, reviews=[review("admin-c")]))
        self.assertEqual(v["conclusion"], "success")

    def test_the_author_cannot_approve_their_own_pr(self):
        # no gate asks an admin author for an approval, so this is pinned on the helper: were one added,
        # the author's own word still would not meet it
        ok, why = tp._approved_by_admin(pr(author="admin-c", permissions=MAINTAINERS, reviews=[review("admin-c")]))
        self.assertFalse(ok)
        self.assertIn("no approval by an admin other than the author", why)

    def test_a_reviewer_without_write_does_not_count(self):
        v = tp.evaluate(pr(labels=["feature"], reviews=[review("drive-by-d")],
                           permissions={"drive-by-d": "read"}))
        self.assertEqual(v["conclusion"], "failure")
        self.assertNotIn("drive-by-d", v["summary"], "a read-only reviewer is not the nearest miss to name")

    def test_only_the_LATEST_review_per_reviewer_counts(self):
        # approved, then changes requested: the latest word stands
        v = tp.evaluate(pr(labels=["feature"], permissions=MEMBER_AUTHOR,
                           reviews=[review("admin-c", submitted=NOW - 600),
                                    review("admin-c", state="CHANGES_REQUESTED", submitted=NOW - 60)]))
        self.assertEqual(v["conclusion"], "failure")
        # changes requested, then approved: also the latest word
        v = tp.evaluate(pr(labels=["feature"], permissions=MEMBER_AUTHOR,
                           reviews=[review("admin-c", state="CHANGES_REQUESTED", submitted=NOW - 600),
                                    review("admin-c", submitted=NOW - 60)]))
        self.assertEqual(v["conclusion"], "success")

    def test_dismissing_a_later_objection_does_not_revive_an_earlier_approval(self):
        # a DISMISSED review is the reviewer's latest word (a non-approval), never an erasure: anyone
        # with write can dismiss - the review's catch
        v = tp.evaluate(pr(labels=["feature"], permissions=MEMBER_AUTHOR,
                           reviews=[review("admin-c", submitted=NOW - 600),
                                    review("admin-c", state="CHANGES_REQUESTED", submitted=NOW - 60, dismissed=True,
                                           dismissed_by="admin-c")]))
        self.assertEqual(v["conclusion"], "failure")

    # Dismissals read fail-closed in both directions. A dismissed APPROVED never counts, whoever dismissed
    # it: a review dismisses only once, so ignoring a third party's dismissal would let the author spend
    # it first and lock the approval in while the PR page shows it struck out (the review's catch
    # against the symmetric rule). A dismissed CHANGES_REQUESTED clears only when the reviewer dismissed it
    # themselves; an author with write access cannot dismiss the peer's objection to merge on green
    # (the maintainers' ruling of 2026-09-07, kept through the owner's rules of 2026-09-08).
    def test_a_reviewer_dismissing_their_own_objection_clears_it(self):
        v = tp.evaluate(pr(labels=["fix"], permissions=MAINTAINERS,
                           reviews=[review("maint-b", state="CHANGES_REQUESTED", dismissed=True, dismissed_by="maint-b")]))
        self.assertEqual(v["conclusion"], "success", "withdrawn by its author: not a standing objection")

    def test_the_author_cannot_dismiss_the_peers_objection_to_merge_on_green(self):
        for perms in (MEMBER_AUTHOR, ADMIN_AUTHOR):
            v = tp.evaluate(pr(labels=["fix"], permissions=perms,
                               reviews=[review("maint-b", state="CHANGES_REQUESTED", dismissed=True, dismissed_by="author-a")]))
            self.assertEqual(v["conclusion"], "failure")
            self.assertIn("Changes requested by maint-b", v["summary"])

    def test_a_reviewer_dismissing_their_own_approval_withdraws_it(self):
        v = tp.evaluate(pr(labels=["feature"], permissions=MEMBER_AUTHOR,
                           reviews=[review("admin-c", dismissed=True, dismissed_by="admin-c")]))
        self.assertEqual(v["conclusion"], "failure")

    def test_an_approval_dismissed_by_anyone_never_counts(self):
        for who in ("author-a", "maint-b"):          # the author; another maintainer
            v = tp.evaluate(pr(labels=["feature"], permissions=MEMBER_AUTHOR,
                               reviews=[review("admin-c", dismissed=True, dismissed_by=who)]))
            self.assertEqual(v["conclusion"], "failure", "dismissed by %s: the PR page shows it struck out" % who)

    def test_a_reviewer_whose_objection_was_dismissed_by_another_lifts_it_by_approving(self):
        v = tp.evaluate(pr(labels=["fix"], permissions=MAINTAINERS,
                           reviews=[review("maint-b", state="CHANGES_REQUESTED", submitted=NOW - 600, dismissed=True,
                                           dismissed_by="author-a"),
                                    review("maint-b", submitted=NOW - 60)]))
        self.assertEqual(v["conclusion"], "success")

    def test_a_dismissal_of_unknown_actor_fails_closed_both_ways(self):
        # the fetcher raises before it builds such a record; the policy still fails closed on it
        v = tp.evaluate(pr(labels=["feature"], permissions=MEMBER_AUTHOR, reviews=[review("admin-c", dismissed=True)]))
        self.assertEqual(v["conclusion"], "failure", "an approval dismissed by nobody-knows-who is no approval")
        v = tp.evaluate(pr(labels=["fix"], permissions=MAINTAINERS,
                           reviews=[review("maint-b", state="CHANGES_REQUESTED", dismissed=True)]))
        self.assertEqual(v["conclusion"], "failure", "...and an objection dismissed by nobody-knows-who still stands")

    def test_a_comment_review_is_not_an_approval(self):
        v = tp.evaluate(pr(labels=["feature"], permissions=MEMBER_AUTHOR, reviews=[review("admin-c", state="COMMENTED")]))
        self.assertEqual(v["conclusion"], "failure")

    def test_a_later_comment_review_does_not_erase_an_approval(self):
        # GitHub records every inline comment as a COMMENTED review; a reviewer's standing is their
        # latest APPROVED / CHANGES_REQUESTED / DISMISSED and comments never change it - the review's
        # catch: a maintainer who approved and then left one note read as "no approval"
        v = tp.evaluate(pr(labels=["feature"], permissions=MEMBER_AUTHOR,
                           reviews=[review("admin-c", submitted=NOW - 600),
                                    review("admin-c", state="COMMENTED", submitted=NOW - 60)]))
        self.assertEqual(v["conclusion"], "success")

    def test_a_later_comment_review_does_not_lift_a_change_request(self):
        v = tp.evaluate(pr(labels=["fix"], permissions=MAINTAINERS,
                           reviews=[review("maint-b", state="CHANGES_REQUESTED", submitted=NOW - 600),
                                    review("maint-b", state="COMMENTED", submitted=NOW - 60)]))
        self.assertEqual(v["conclusion"], "failure", "the objection stands; a comment is not saying otherwise")

    def test_a_pending_review_changes_nothing(self):
        v = tp.evaluate(pr(labels=["feature"], permissions=MEMBER_AUTHOR,
                           reviews=[review("admin-c", submitted=NOW - 600),
                                    review("admin-c", state="PENDING", submitted=NOW - 60)]))
        self.assertEqual(v["conclusion"], "success")


class MajorFeature(unittest.TestCase):
    """major-feature: for every author, a linked issue someone other than the author commented on (the
    write-up and its discussion); a member or a contributor additionally needs an admin's approval on the
    current head."""
    ISSUE_OK = {7: {"exists": True, "is_pr": False, "user": "author-a", "comments": ["maint-b"]}}

    def test_an_admin_authors_major_feature_passes_on_a_discussed_issue_alone(self):
        v = tp.evaluate(pr(labels=["major-feature"], permissions=ADMIN_AUTHOR,
                           body="Design discussion in #7.", issues=self.ISSUE_OK))
        self.assertEqual(v["conclusion"], "success")
        self.assertIn("issue #7", v["summary"])

    def test_an_admin_authors_major_feature_fails_without_the_discussion(self):
        v = tp.evaluate(pr(labels=["major-feature"], permissions=ADMIN_AUTHOR))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("discussed linked issue", v["summary"])
        v = tp.evaluate(pr(labels=["major-feature"], permissions=ADMIN_AUTHOR, reviews=[review("admin-c")]))
        self.assertEqual(v["conclusion"], "failure", "another admin's approval does not stand in for the write-up")
        v = tp.evaluate(pr(labels=["major-feature"], permissions=ADMIN_AUTHOR, body="#7",
                           issues={7: {"exists": True, "is_pr": False, "user": "author-a", "comments": ["author-a"]}}))
        self.assertEqual(v["conclusion"], "failure", "the author's own comments are not a discussion")

    def test_a_member_authors_major_feature_needs_both(self):
        discussed = dict(labels=["major-feature"], permissions=MEMBER_AUTHOR, body="#7", issues=self.ISSUE_OK)
        v = tp.evaluate(pr(**discussed))
        self.assertEqual(v["conclusion"], "failure", "discussed, unapproved")
        self.assertIn("needs an admin's approval", v["summary"])
        v = tp.evaluate(pr(**dict(discussed, reviews=[review("maint-b")])))
        self.assertEqual(v["conclusion"], "failure", "a write-holder's approval meets no gate")
        v = tp.evaluate(pr(labels=["major-feature"], permissions=MEMBER_AUTHOR, reviews=[review("admin-c")]))
        self.assertEqual(v["conclusion"], "failure", "approved, undiscussed")
        self.assertIn("discussed linked issue is required", v["summary"])
        v = tp.evaluate(pr(**dict(discussed, reviews=[review("admin-c")])))
        self.assertEqual(v["conclusion"], "success")
        self.assertIn("Approved by admin-c", v["summary"])
        self.assertIn("issue #7", v["summary"])

    def test_a_contributors_major_feature_needs_both_as_well(self):
        v = tp.evaluate(pr(labels=["major-feature"], permissions=MAINTAINERS, body="#7", issues=self.ISSUE_OK))
        self.assertEqual(v["conclusion"], "failure")
        v = tp.evaluate(pr(labels=["major-feature"], permissions=MAINTAINERS, body="#7", issues=self.ISSUE_OK,
                           reviews=[review("admin-c")]))
        self.assertEqual(v["conclusion"], "success")

    def test_an_issue_url_counts_too(self):
        v = tp.evaluate(pr(labels=["major-feature"], permissions=ADMIN_AUTHOR,
                           body="See https://github.com/romp-on/romp/issues/7 for the discussion.",
                           issues=self.ISSUE_OK))
        self.assertEqual(v["conclusion"], "success")

    def test_approval_without_a_linked_issue_fails(self):
        v = tp.evaluate(pr(labels=["major-feature"], permissions=MEMBER_AUTHOR, reviews=[review("admin-c")]))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("issue", v["summary"].lower())

    def test_a_linked_issue_with_only_the_authors_comments_is_not_a_discussion(self):
        v = tp.evaluate(pr(labels=["major-feature"], permissions=MEMBER_AUTHOR, reviews=[review("admin-c")],
                           body="#7", issues={7: {"exists": True, "is_pr": False, "user": "author-a",
                                                   "comments": ["author-a"]}}))
        self.assertEqual(v["conclusion"], "failure")

    def test_the_issue_opener_alone_is_not_a_discussion(self):
        # the maintainers' ruling (2026-09-07, the discussion issue's third point): discussion means a
        # COMMENT by someone other than the author; an issue a maintainer filed and the author answered
        # alone is not one, and the fetcher no longer records the opener
        v = tp.evaluate(pr(labels=["major-feature"], permissions=MEMBER_AUTHOR, reviews=[review("admin-c")],
                           body="#7", issues={7: {"exists": True, "is_pr": False, "user": "maint-b",
                                                   "comments": ["author-a"]}}))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("comment by someone other than the author", v["summary"])

    def test_a_linked_PR_number_is_not_an_issue(self):
        v = tp.evaluate(pr(labels=["major-feature"], permissions=ADMIN_AUTHOR,
                           body="#7", issues={7: {"exists": True, "is_pr": True, "user": "maint-b",
                                                   "comments": ["maint-b"]}}))
        self.assertEqual(v["conclusion"], "failure")

    def test_an_approval_on_an_older_head_fails_here_too(self):
        v = tp.evaluate(pr(labels=["major-feature"], permissions=MEMBER_AUTHOR, reviews=[review("admin-c", sha=OLD)],
                           body="#7", issues=self.ISSUE_OK))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("older head", v["summary"])

    def test_a_standing_objection_holds_a_discussed_and_approved_major_feature(self):
        for perms in (MEMBER_AUTHOR, ADMIN_AUTHOR):
            v = tp.evaluate(pr(labels=["major-feature"], permissions=perms, body="#7", issues=self.ISSUE_OK,
                               reviews=[review("admin-c"), review("maint-b", state="CHANGES_REQUESTED")]))
            self.assertEqual(v["conclusion"], "failure")
            self.assertIn("maint-b", v["summary"])


class NoTimePath(unittest.TestCase):
    """No tier has a time-based path (the owner, 2026-09-08). Mutation guard in both directions: the
    seven-day clock the 2026-09-07 text gave fix is gone from the module, and a record still carrying the
    old clock keys (an older fetcher, a hand-built fixture) changes no verdict."""

    def test_the_module_has_no_clock(self):
        for gone in ("SEVEN_DAYS", "chain_start", "_clock_since", "_is_doc"):
            self.assertFalse(hasattr(tp, gone), gone)
        consts = " ".join(str(c) for f in vars(tp).values() if isinstance(f, types.FunctionType)
                          for c in f.__code__.co_consts)
        for key in ("first_check_at", "head_floor", "created_at", "now", "seven", "days",
                    "committer", "author_date", "commit_date"):
            self.assertIsNone(re.search(r"\b%s\b" % key, consts), key)

    def test_stale_clock_keys_on_a_record_change_nothing(self):
        stale = {"first_check_at": NOW - 30 * DAY, "head_floor": NOW - 30 * DAY,
                 "created_at": NOW - 30 * DAY, "now": NOW}
        for perms in (MAINTAINERS, MEMBER_AUTHOR):
            v = tp.evaluate(pr(labels=["feature"], permissions=perms, **stale))
            self.assertEqual(v["conclusion"], "failure", "a month-old unapproved feature still waits for its approval")
            v = tp.evaluate(pr(labels=["major-feature"], permissions=perms, body="#7", issues=MajorFeature.ISSUE_OK, **stale))
            self.assertEqual(v["conclusion"], "failure", "...and a month-old discussed one too")
            v = tp.evaluate(pr(labels=["fix"], files=["scripts/ci/tier_policy.py"], permissions=perms, **stale))
            self.assertEqual(v["conclusion"], "failure", "nor is the guard on the gate's own code outwaited")
        v = tp.evaluate(pr(labels=["major-feature"], permissions=ADMIN_AUTHOR, **stale))
        self.assertEqual(v["conclusion"], "failure", "an admin author's month-old undiscussed major feature still waits")
        v = tp.evaluate(pr(labels=["fix"], permissions=MAINTAINERS,
                           reviews=[review("maint-b", state="CHANGES_REQUESTED")], **stale))
        self.assertEqual(v["conclusion"], "failure", "an objection is not outwaited")
        for label in ("fix", "feature", "major-feature"):
            self.assertNotIn("seven", tp.evaluate(pr(labels=[label], **stale))["summary"].lower())


class GithubDir(unittest.TestCase):
    """The gate's own files: a member or a contributor needs an admin's approval whatever the tier (merging
    on green never clears them, and a write-holder's approval meets no gate); an admin author, the owner,
    is exempt."""

    def test_a_file_listing_the_api_truncated_makes_the_unseen_files_guarded(self):
        # the files endpoint returns at most 3000 entries; when the PR's changed_files says there are
        # more, the unseen files are assumed guarded
        v = tp.evaluate(pr(labels=["docs"], files=["docs/a.md"], files_truncated=True))
        self.assertEqual(v["conclusion"], "failure", "docs merges on green, but not with unseen files")
        self.assertIn("3000", v["summary"])
        v = tp.evaluate(pr(labels=["fix"], files_truncated=True))
        self.assertEqual(v["conclusion"], "failure", "the same for fix")
        v = tp.evaluate(pr(labels=["fix"], files_truncated=True, reviews=[review("maint-b")], permissions=MAINTAINERS))
        self.assertEqual(v["conclusion"], "failure", "a write-holder's approval does not clear it")
        v = tp.evaluate(pr(labels=["fix"], files_truncated=True, reviews=[review("admin-c")], permissions=MAINTAINERS))
        self.assertEqual(v["conclusion"], "success", "an admin's approval clears it")
        v = tp.evaluate(pr(labels=["fix"], files_truncated=True, permissions=ADMIN_AUTHOR))
        self.assertEqual(v["conclusion"], "success", "an admin author is exempt: the unseen files are the owner's own")

    def test_the_gates_own_code_needs_an_admins_approval_from_a_non_admin_author(self):
        # the policy is checked out from main and run with checks:write, so a PR rewriting
        # scripts/ci/tier_policy.py and merging on green would have graded itself
        for perms in (MAINTAINERS, MEMBER_AUTHOR):
            for tier in ("docs", "fix"):
                v = tp.evaluate(pr(labels=[tier], files=["scripts/ci/tier_policy.py"], permissions=perms))
                self.assertEqual(v["conclusion"], "failure", tier)
                self.assertIn("scripts/ci/tier_policy.py", v["summary"])
                self.assertIn("admin's approval", v["summary"])
            v = tp.evaluate(pr(labels=["fix"], files=["scripts/ci/tier_policy.py"], reviews=[review("maint-b")],
                               permissions=perms))
            self.assertEqual(v["conclusion"], "failure", "a write-holder's approval does not meet the guard")
            v = tp.evaluate(pr(labels=["fix"], files=["scripts/ci/tier_policy.py"], reviews=[review("admin-c")],
                               permissions=perms))
            self.assertEqual(v["conclusion"], "success")

    def test_touching_github_requires_an_admins_approval_regardless_of_tier(self):
        v = tp.evaluate(pr(labels=["fix"], files=[".github/workflows/ci.yml"], permissions=MEMBER_AUTHOR))
        self.assertEqual(v["conclusion"], "failure", "merging on green never clears a .github change")
        self.assertIn(".github", v["summary"])
        v = tp.evaluate(pr(labels=["docs"], files=[".github/PULL_REQUEST_TEMPLATE.md"], permissions=MEMBER_AUTHOR))
        self.assertEqual(v["conclusion"], "failure", "markdown under .github is still .github")
        v = tp.evaluate(pr(labels=["fix"], files=[".github/workflows/ci.yml"], reviews=[review("admin-c")],
                           permissions=MEMBER_AUTHOR))
        self.assertEqual(v["conclusion"], "success")
        v = tp.evaluate(pr(labels=["feature"], files=[".github/workflows/ci.yml"], reviews=[review("admin-c")],
                           permissions=MEMBER_AUTHOR))
        self.assertEqual(v["conclusion"], "success", "one admin approval meets the guard and the feature gate")

    def test_an_admin_author_is_exempt_from_the_guard(self):
        # the owner may change the gate; the guard exists so that nobody else rewrites it unread
        for tier in ("docs", "fix", "feature"):
            v = tp.evaluate(pr(labels=[tier], permissions=ADMIN_AUTHOR,
                               files=[".github/workflows/tier-policy.yml", "scripts/ci/tier_policy.py"]))
            self.assertEqual(v["conclusion"], "success", tier)
        v = tp.evaluate(pr(labels=["major-feature"], permissions=ADMIN_AUTHOR, files=[".github/workflows/ci.yml"],
                           body="#7", issues=MajorFeature.ISSUE_OK))
        self.assertEqual(v["conclusion"], "success", "the tier's own gate still applies, the guard does not")

    def test_an_objection_holds_a_guarded_fix_even_when_an_admin_approved(self):
        # the approval meets the guard; the objection still holds the tier
        v = tp.evaluate(pr(labels=["fix"], files=[".github/workflows/ci.yml"], permissions=MAINTAINERS,
                           reviews=[review("admin-c"), review("maint-b", state="CHANGES_REQUESTED")]))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("maint-b", v["summary"])


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

    def test_the_header_states_the_rules_by_the_authors_role(self):
        head = self.wf[:self.wf.index("\non:")]
        for phrase in ("author's role", "admin", "merge on green for every author"):
            self.assertIn(phrase, head, phrase)

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

    def test_the_schedule_exists_for_approval_propagation_only(self):
        m = re.search(r'- cron: "[^"]+"\s*#\s*(.*)', self.wf)
        self.assertTrue(m, "the schedule line carries its reason")
        self.assertIn("approval propagation", m.group(1))
        self.assertNotIn("seven", self.wf.lower(), "no clock rides the schedule")

    def test_the_token_holds_what_the_verdict_and_the_label_need(self):
        # checks:write posts the verdict; pull-requests:write applies the body's declared tier as a label
        # (T273); actions:write re-runs the label counter on that head. Never contents:write: the job
        # checks out the base tree read-only and executes nothing from the PR
        for line in ("checks: write", "pull-requests: write", "actions: write", "issues: read", "contents: read"):
            self.assertIn(line, self.wf, line)
        self.assertNotIn("contents: write", self.wf)
        self.assertNotIn("issues: write", self.wf)

    def test_the_header_says_the_body_is_data_and_the_label_write_is_the_only_new_power(self):
        head = self.wf[:self.wf.index("\non:")]
        for phrase in ("body is data", "pull-requests: write", "Tier:"):
            self.assertIn(phrase, head, phrase)

    def test_the_job_never_runs_pr_code(self):
        # the only checkout is the base tree; no ref: pointing at the PR head, and the fetcher is
        # API reads plus one check-run POST
        self.assertNotIn("ref:", self.wf)
        self.assertNotIn("head.sha", self.wf)
        self.assertEqual(self.fetch.count('_req("POST"'), 3,
                         "exactly three writes: the verdict, the declared tier's label, the label counter's re-run")
        self.assertIn('"/repos/%s/check-runs"', self.fetch)
        self.assertIn('"/repos/%s/issues/%d/labels"', self.fetch)
        self.assertIn('/actions/runs/%d/rerun', self.fetch)

    def test_the_fetcher_reads_no_clock_input(self):
        # nothing in the policy is timed, so the fetcher lists no check-run history, no timeline and
        # never the commit itself (whose author/committer dates are the author's to set)
        for gone in ("/commits/", "/timeline", "chain_start", "first_check_at", "head_floor",
                     "RESET_EVENTS", "VERDICT_GAP", "import time", '["committer"]', '["author"]["date"]'):
            self.assertNotIn(gone, self.fetch, gone)
        self.assertNotIn("seven", self.fetch.lower())

    def test_the_job_name_is_NOT_the_check_name(self):
        # the job's own check run must not share the required check's name: two same-named runs per
        # head (the job's, frozen at push time, and the API-posted verdict the hourly sweep moves) leave
        # it undocumented which one the ruleset honors - so only the API-posted verdict carries the name
        jobs = self.wf[self.wf.index("\njobs:"):]
        self.assertIn("    name: Tier policy evaluation", jobs)
        self.assertNotRegex(jobs, r"name: Tier policy[ \t]*\n")

    def test_the_three_tier_label_lists_agree(self):
        wf = open(os.path.join(os.path.dirname(HERE), ".github", "workflows", "pr-tier.yml")).read()
        tmpl = open(os.path.join(os.path.dirname(HERE), ".github", "PULL_REQUEST_TEMPLATE.md")).read()
        in_jq = set(re.findall(r'\. == "([a-z-]+)"', wf))
        expected = set(tp.TIERS) | set(tp.TIER_ALIASES)
        self.assertEqual(in_jq, expected, "the label check and the policy name the same tiers")
        for t in tp.TIERS:
            self.assertIn("`%s`" % t, tmpl, "the PR template lists every tier")

    def test_the_standing_sentences_admit_the_label_write(self):
        # the trust-model sentences that said the fetcher "only fetches PR data and posts the verdict" and
        # "reads no check-run history" now name the label write and the counter re-run (the manager's review)
        doc = open(os.path.join(os.path.dirname(HERE), "docs", "pr-tiers.md")).read()
        self.assertNotIn("only fetches PR data and posts the verdict", doc)
        for text, name in ((doc, "docs"), (self.wf, "workflow"), (self.fetch, "fetcher")):
            self.assertIn("label", text, name)
            self.assertNotRegex(text, r"reads no check-run history, no timeline and no commit date, so there is no clock",
                                name + " still carries the pre-T273 sentence")

    def test_the_docs_describe_the_body_line(self):
        # docs/pr-tiers.md has the section; the repo CLAUDE.md's tier bullet names the line in a sentence
        doc = open(os.path.join(os.path.dirname(HERE), "docs", "pr-tiers.md")).read()
        self.assertIn("Declaring the tier", doc)
        for phrase in ("Tier: fix", "label", "wins"):
            self.assertIn(phrase, doc[doc.index("Declaring the tier"):], phrase)
        claude = open(os.path.join(os.path.dirname(HERE), "CLAUDE.md")).read()
        self.assertIn("`Tier: fix`", claude, "the CLAUDE.md tier bullet names the body line")


class FetcherShapes(unittest.TestCase):
    """build_record against the DOCUMENTED response shapes, with _req stubbed - no network. A request the
    stub does not know (a check-run listing, a timeline, the commit itself) is an AssertionError: the
    fetcher reads nothing the policy would time. Collaborator permissions are served per login (admin-c
    admin, maint-b and author-a write); an unknown login is the API's 404, a non-collaborator."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "tier_policy_check", os.path.join(os.path.dirname(HERE), "scripts", "ci", "tier_policy_check.py"))
        self.tc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tc)
        self.calls = []
        test = self

        def paged(pages, route, query):
            # pages are served BY URL (the review's catch: a stub serving by call count let a fetcher
            # that never follows the Link URL pass); a page asked for twice is a looping fetcher
            import urllib.parse as up
            n = int((up.parse_qs(query).get("page") or ["1"])[0])
            test.assertNotIn((route, n), test.served, "page requested twice: not following Link")
            test.served.add((route, n))
            more = n < len(pages)
            nxt = "%s/repos/romp-on/romp/pulls/42/%s?per_page=100&page=%d" % (test.tc.API, route, n + 1)
            last = "%s/repos/romp-on/romp/pulls/42/%s?per_page=100&page=%d" % (test.tc.API, route, len(pages))
            hdrs = {"Link": '<%s>; rel="next", <%s>; rel="last"' % (nxt, last)} if more else {}
            return pages[n - 1], hdrs

        def fake_req(method, path, token, body=None):
            test.calls.append((method, path))
            path, _, query = path.partition("?")       # _get_all appends per_page; match the route
            if method == "POST":
                test.posted.append((path, body))
            if path.endswith("/pulls/42"):
                return {"head": {"sha": HEAD, "ref": "topic", "repo": {"full_name": "fork-x/romp"}}, "user": {"login": test.author},
                        "labels": [{"name": l} for l in test.labels], "created_at": "2026-08-30T00:00:00Z", "body": test.body,
                        "changed_files": test.changed_files}, {}
            if path.endswith("/issues/42/labels"):
                test.labels = test.labels + list((body or {}).get("labels") or [])
                return [{"name": l} for l in test.labels], {}
            if "/actions/workflows/pr-tier.yml/runs" in path:
                test.assertIn("head_sha=" + HEAD, query, "the counter's runs are asked for on THIS head")
                test.assertIn("branch=topic", query, "...and on this PR's head branch")
                return {"total_count": len(test.counter_runs), "workflow_runs": test.counter_runs}, {}
            if "/actions/runs/" in path and path.endswith("/rerun"):
                if test.rerun_error:
                    raise urllib.error.HTTPError(path, test.rerun_error, "x", {}, None)
                return None, {}
            if path.endswith("/check-runs"):
                return {"id": 1}, {}
            if "/files" in path:
                if test.files_error:
                    raise urllib.error.HTTPError(path, test.files_error, "x", {}, None)
                return paged(test.files_pages, "files", query)
            if "/reviews" in path:
                return test.reviews, {}
            if "/collaborators/" in path:
                if test.perm_error:
                    raise urllib.error.HTTPError(path, test.perm_error, "x", {}, None)
                login = path.split("/collaborators/")[1].split("/")[0]
                if login not in test.perms:
                    raise urllib.error.HTTPError(path, 404, "x", {}, None)
                return {"permission": test.perms[login]}, {}
            if path.endswith("/events"):
                return test.events, {}
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
        self.files_error = None
        self.perms = {"author-a": "write", "maint-b": "write", "admin-c": "admin"}
        self.author = "author-a"
        self.labels = ["fix"]
        self.files_pages = [[{"filename": "kernel/kernel.py", "status": "modified"}]]
        self.served = set()
        self.changed_files = 1
        self.reviews = [{"id": 1, "user": {"login": "admin-c"}, "state": "APPROVED", "commit_id": HEAD,
                         "submitted_at": "2026-09-02T00:00:00Z"}]
        self.events = []
        self.issue_fetches = []
        self.body = "fixes #7"
        self.posted = []
        self.rerun_error = None
        self.counter_runs = [{"id": 9001, "status": "completed", "conclusion": "failure",
                              "head_repository": {"full_name": "fork-x/romp"}}]
        self.tc._req = fake_req

    def _labels_posted(self):
        return [b for p, b in self.posted if p.endswith("/issues/42/labels")]

    def _reruns_posted(self):
        return [p for p, b in self.posted if p.endswith("/rerun")]

    def test_a_declared_tier_on_an_unlabeled_pr_is_applied_before_the_verdict(self):
        # T273: a read-only contributor cannot label their PR, so the body's `Tier: fix` line becomes the
        # label through the workflow, and the same run grades the tier it just applied
        self.labels = []
        self.body = "fixes #7\n\nTier: fix\n"
        self.reviews = []
        v = self.tc.run_one("romp-on/romp", 42, "tok")
        self.assertEqual(self._labels_posted(), [{"labels": ["fix"]}], "one label write, the declared tier")
        self.assertEqual(v["conclusion"], "success", "graded as the fix it declared, in the same run")
        self.assertIn("applied", v["summary"])
        self.assertIn("fix", v["summary"])
        # a label added with the workflow's own token fires no `labeled` run, so the "Exactly one tier
        # label" run on this head still shows the count it read before: its newest completed run is re-run
        self.assertEqual(self._reruns_posted(), ["/repos/romp-on/romp/actions/runs/9001/rerun"])

    def test_an_existing_label_stands_and_a_disagreeing_body_is_only_mentioned(self):
        self.labels = ["feature"]
        self.body = "Tier: fix"
        self.perms["author-a"] = "admin"
        self.counter_runs = [{"id": 9006, "status": "completed", "conclusion": "success",
                              "head_repository": {"full_name": "fork-x/romp"}}]     # a green counter: nothing to refresh
        v = self.tc.run_one("romp-on/romp", 42, "tok")
        self.assertEqual(self._labels_posted(), [], "the label stands; maintainers re-tier by relabeling")
        self.assertEqual(self._reruns_posted(), [])
        self.assertEqual(v["title"], "Tier policy: feature", "graded as the label says")
        self.assertIn("fix", v["summary"])
        self.assertIn("relabel", v["summary"])

    def test_disagreeing_tier_lines_apply_nothing_and_the_verdict_says_so(self):
        self.labels = []
        self.body = "Tier: fix\n\nTier: feature\n"
        v = self.tc.run_one("romp-on/romp", 42, "tok")
        self.assertEqual(self._labels_posted(), [])
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("disagree", v["summary"])

    def test_the_untouched_template_applies_nothing_and_the_verdict_points_at_the_placeholder(self):
        self.labels = []
        self.body = open(os.path.join(os.path.dirname(HERE), ".github", "PULL_REQUEST_TEMPLATE.md")).read()
        v = self.tc.run_one("romp-on/romp", 42, "tok")
        self.assertEqual(self._labels_posted(), [])
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("names no tier", v["summary"])

    def test_a_counter_run_still_in_progress_is_not_rerun_and_the_verdict_says_so(self):
        self.labels = []
        self.body = "Tier: fix"
        self.counter_runs = [{"id": 9002, "status": "in_progress", "conclusion": None}]
        v = self.tc.run_one("romp-on/romp", 42, "tok")
        self.assertEqual(self._labels_posted(), [{"labels": ["fix"]}])
        self.assertEqual(self._reruns_posted(), [], "a run in progress cannot be re-run")
        self.assertIn("mid-count", v["summary"])

    def test_a_queued_counter_run_reads_the_label_itself(self):
        self.labels = []
        self.body = "Tier: fix"
        self.counter_runs = [{"id": 9003, "status": "queued", "conclusion": None}]
        v = self.tc.run_one("romp-on/romp", 42, "tok")
        self.assertEqual(self._reruns_posted(), [], "a queued run has not counted yet: nothing to refresh")
        self.assertEqual(v["conclusion"], "success")

    def test_no_counter_run_on_the_head_is_nothing_to_refresh(self):
        self.labels = []
        self.body = "Tier: fix"
        self.counter_runs = []
        v = self.tc.run_one("romp-on/romp", 42, "tok")
        self.assertEqual(self._labels_posted(), [{"labels": ["fix"]}])
        self.assertEqual(self._reruns_posted(), [])
        self.assertEqual(v["conclusion"], "success")

    def test_a_counter_run_awaiting_approval_is_not_rerun_and_the_verdict_says_so(self):
        # a first-time contributor's workflow runs wait for a maintainer's approval: the API reports that
        # run completed with conclusion action_required, though it has never counted anything. Re-running
        # it would be either refused or a bypass of the approval; say what it waits for instead
        self.labels = []
        self.body = "Tier: fix"
        self.counter_runs = [{"id": 9004, "status": "completed", "conclusion": "action_required",
                              "head_repository": {"full_name": "fork-x/romp"}}]
        v = self.tc.run_one("romp-on/romp", 42, "tok")
        self.assertEqual(self._labels_posted(), [{"labels": ["fix"]}])
        self.assertEqual(self._reruns_posted(), [], "an approval-gated run is never re-run from here")
        self.assertEqual(v["conclusion"], "success")
        self.assertIn("approval", v["summary"])

    def test_a_refused_rerun_after_the_label_landed_is_said_not_graded_as_a_failed_evaluation(self):
        # the label write succeeded, so the verdict is the real one; the counter's refresh is said to have
        # failed (loudly, in the summary) instead of posting "evaluation failed" on a correctly labeled PR
        self.labels = []
        self.body = "Tier: fix"
        self.rerun_error = 403
        v = self.tc.run_one("romp-on/romp", 42, "tok")
        self.assertEqual(self._labels_posted(), [{"labels": ["fix"]}])
        self.assertEqual(v["conclusion"], "success")
        self.assertIn("could not be re-run", v["summary"])
        self.assertIn("403", v["summary"])

    def test_a_non_http_failure_of_the_refresh_is_said_too(self):
        # a URLError (DNS, the 30 s timeout), a reset connection or a bad JSON body on the re-run path must
        # not surface as "evaluation failed" on a PR whose label just landed (the manager's review)
        for exc in (urllib.error.URLError("dns"), TimeoutError("30 s"), ConnectionResetError(), ValueError("bad json")):
            real = self.tc._req

            def failing(method, path, token, body=None, exc=exc):
                if "/actions/" in path:
                    raise exc
                return real(method, path, token, body)
            self.tc._req = failing
            self.labels = []
            self.body = "Tier: fix"
            self.posted = []
            self.served = set()
            v = self.tc.run_one("romp-on/romp", 42, "tok")
            self.tc._req = real
            self.assertEqual(self._labels_posted(), [{"labels": ["fix"]}], repr(exc))
            self.assertEqual(v["conclusion"], "success", repr(exc))
            self.assertIn("could not be re-run", v["summary"], repr(exc))
            self.assertIn(type(exc).__name__, v["summary"], repr(exc))

    def test_a_red_counter_beside_one_correct_label_is_rerun_on_any_later_pass(self):
        # the in-progress race (the counter read the labels a second before the write) and a refused
        # re-run both leave the counter red with the label on; the next event or hourly pass repairs it
        self.labels = ["fix"]
        self.body = ""
        v = self.tc.run_one("romp-on/romp", 42, "tok")
        self.assertEqual(self._labels_posted(), [], "nothing to apply")
        self.assertEqual(self._reruns_posted(), ["/repos/romp-on/romp/actions/runs/9001/rerun"])
        self.assertEqual(v["conclusion"], "success")
        self.assertIn("re-run", v["summary"])
        # a green counter is left alone: no write for nothing
        self.posted = []
        self.served = set()
        self.counter_runs = [{"id": 9005, "status": "completed", "conclusion": "success",
                              "head_repository": {"full_name": "fork-x/romp"}}]
        self.tc.run_one("romp-on/romp", 42, "tok")
        self.assertEqual(self._reruns_posted(), [])

    def test_another_repositorys_run_on_the_same_sha_is_not_the_one_rerun(self):
        # two PRs can share a head sha (a fork and a branch); the run re-run is this PR's own
        self.labels = []
        self.body = "Tier: fix"
        self.counter_runs = [{"id": 7, "status": "completed", "conclusion": "failure", "head_repository": {"full_name": "other-y/romp"}},
                             {"id": 9001, "status": "completed", "conclusion": "failure", "head_repository": {"full_name": "fork-x/romp"}}]
        self.tc.run_one("romp-on/romp", 42, "tok")
        self.assertEqual(self._reruns_posted(), ["/repos/romp-on/romp/actions/runs/9001/rerun"])

    def test_a_tier_label_removed_by_someone_other_than_the_author_ends_the_bodys_say(self):
        # a maintainer who removes the label has ruled (to re-tier, or to leave it unsorted for a talk);
        # re-applying the body's line on the `unlabeled` event or the hourly pass would undo that ruling,
        # and a remove-then-add re-tier would end with two labels. The removal is read from the issue
        # events the fetcher already fetches: an event, not a clock
        self.labels = []
        self.body = "Tier: fix"
        self.events = [{"event": "unlabeled", "label": {"name": "fix"}, "actor": {"login": "maint-b"}},
                       {"event": "unlabeled", "label": {"name": "wontfix"}, "actor": {"login": "maint-b"}},
                       {"event": "unlabeled", "label": {"name": "feature"}, "actor": {"login": "github-actions[bot]", "type": "Bot"}}]
        rec = self.tc.build_record("romp-on/romp", 42, "tok")
        self.assertEqual(rec["tier_unlabeled_by"], ["maint-b"], "tier labels only, humans only, once per login")
        self.served = set()
        v = self.tc.run_one("romp-on/romp", 42, "tok")
        self.assertEqual(self._labels_posted(), [], "the body's line is not re-applied after a maintainer's removal")
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("maint-b", v["summary"])
        self.assertIn("not re-applied", v["summary"])
        # the author's own removal is not a ruling: the line applies again
        self.events = [{"event": "unlabeled", "label": {"name": "fix"}, "actor": {"login": "author-a"}}]
        self.served = set()
        self.tc.run_one("romp-on/romp", 42, "tok")
        self.assertEqual(self._labels_posted(), [{"labels": ["fix"]}])

    def test_a_failed_label_write_fails_the_run_loudly(self):
        # a 403 (the token lacks pull-requests:write) must not grade the PR as unlabeled with a
        # normal-looking verdict: the run raises, and run_one posts "evaluation failed" naming the error
        real = self.tc._req

        def refusing(method, path, token, body=None):
            if method == "POST" and path.endswith("/issues/42/labels"):
                raise urllib.error.HTTPError(path, 403, "Resource not accessible by integration", {}, None)
            return real(method, path, token, body)
        self.tc._req = refusing
        self.labels = []
        self.body = "Tier: fix"
        with self.assertRaises(urllib.error.HTTPError):
            self.tc.run_one("romp-on/romp", 42, "tok")
        failed = [b for p, b in self.posted if p.endswith("/check-runs")]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["conclusion"], "failure")
        self.assertIn("evaluation failed", failed[0]["output"]["title"])

    def test_build_record_survives_the_documented_shapes_and_has_no_time_field(self):
        rec = self.tc.build_record("romp-on/romp", 42, "tok")
        self.assertEqual(set(rec), {"number", "author", "labels", "head_sha", "files", "files_truncated", "reviews",
                                    "permissions", "body", "issues", "tier_unlabeled_by"},
                         "the record has exactly the documented keys: no time field, no commit date")
        self.assertEqual(rec["tier_unlabeled_by"], [], "no tier label was ever removed from this PR")
        self.assertEqual(rec["permissions"], {"admin-c": "admin", "author-a": "write"},
                         "every reviewer AND the author: the policy reads the author's role from this map")
        self.assertEqual(rec["issues"], {7: {"exists": True, "is_pr": False, "comments": ["maint-b"]}},
                         "the bot commenter is filtered; the opener is not recorded (they do not count)")
        self.assertEqual(self.tc.evaluate(rec)["conclusion"], "success")
        self.assertFalse(any("/commits/" in p or p.endswith("/timeline") for _, p in self.calls),
                         "no check-run history, no timeline, no commit: nothing the policy would time")

    def test_an_unreviewed_fix_passes_through_the_fetcher_too(self):
        self.reviews = []
        rec = self.tc.build_record("romp-on/romp", 42, "tok")
        v = self.tc.evaluate(rec)
        self.assertEqual(v["conclusion"], "success")
        self.assertIn("merges on green", v["summary"])

    def test_the_authors_role_reaches_the_policy(self):
        # a member's feature waits for the admin's approval; the same PR by an admin merges on green
        self.labels = ["feature"]
        self.reviews = []
        rec = self.tc.build_record("romp-on/romp", 42, "tok")
        self.assertEqual(rec["permissions"], {"author-a": "write"}, "no reviewer: the author alone is looked up")
        self.assertEqual(self.tc.evaluate(rec)["conclusion"], "failure")
        self.perms["author-a"] = "admin"
        self.served = set()                  # a second, independent build: the page ledger starts over
        rec = self.tc.build_record("romp-on/romp", 42, "tok")
        self.assertEqual(rec["permissions"], {"author-a": "admin"})
        v = self.tc.evaluate(rec)
        self.assertEqual(v["conclusion"], "success")
        self.assertIn("admin author merges on green", v["summary"])

    def test_a_non_collaborator_author_reads_as_none(self):
        # a fork PR by an outside contributor: the permission endpoint 404s, recorded as "none"
        self.author = "outsider-x"
        self.labels = ["feature"]
        self.reviews = []
        rec = self.tc.build_record("romp-on/romp", 42, "tok")
        self.assertEqual(rec["permissions"], {"outsider-x": "none"})
        self.assertEqual(self.tc.evaluate(rec)["conclusion"], "failure", "a contributor's feature waits for the admin")
        rec["labels"] = ["fix"]
        self.assertEqual(self.tc.evaluate(rec)["conclusion"], "success", "a contributor's fix merges on green")

    def test_a_permission_lookup_error_other_than_404_raises(self):
        # a 403 or 5xx mapped to "none" would deny every approval (and read every author as a contributor)
        # while posting a normal-looking verdict; the fetcher fails loudly instead
        self.perm_error = 403
        with self.assertRaises(urllib.error.HTTPError):
            self.tc.build_record("romp-on/romp", 42, "tok")

    def test_a_push_during_evaluation_raises_instead_of_grading_a_mixed_record(self):
        real = self.tc._req
        heads = iter([HEAD, OLD])

        def moving(method, path, token, body=None):
            if path.split("?")[0].endswith("/pulls/42"):
                return {"head": {"sha": next(heads)}, "user": {"login": "author-a"}, "labels": [{"name": "fix"}],
                        "created_at": "2026-08-30T00:00:00Z", "body": "", "changed_files": 1}, {}
            return real(method, path, token, body)
        self.tc._req = moving
        with self.assertRaises(RuntimeError):
            self.tc.build_record("romp-on/romp", 42, "tok")

    def test_a_rename_out_of_github_carries_both_paths(self):
        # the review's HIGH: `git mv .github/workflows/tier-policy.yml docs/gate-notes.md` in a docs PR
        # read as documentation-only and would have merged on green, removing the gate from main
        self.files_pages = [[{"filename": "docs/gate-notes.md", "status": "renamed",
                              "previous_filename": ".github/workflows/tier-policy.yml"}]]
        rec = self.tc.build_record("romp-on/romp", 42, "tok")
        self.assertEqual(rec["files"], ["docs/gate-notes.md", ".github/workflows/tier-policy.yml"])
        self.assertFalse(rec["files_truncated"], "one entry, two paths: truncation counts entries, not paths")
        self.assertEqual(self.tc.evaluate(rec)["conclusion"], "success", "approved by an admin: the guard is met")
        rec["reviews"] = []
        for tier in ("docs", "fix"):
            rec["labels"] = [tier]
            self.assertEqual(self.tc.evaluate(rec)["conclusion"], "failure",
                             "a .github change wearing a docs destination does not merge on green as %s" % tier)

    def test_a_two_page_file_listing_is_read_whole(self):
        self.files_pages = [[{"filename": "a.py", "status": "modified"}], [{"filename": "b.py", "status": "added"}]]
        self.changed_files = 2
        rec = self.tc.build_record("romp-on/romp", 42, "tok")
        self.assertEqual(rec["files"], ["a.py", "b.py"])
        self.assertFalse(rec["files_truncated"])
        self.assertTrue(any("/files" in p and "page=2" in p for _, p in self.calls), "the Link URL was followed")

    def test_a_listing_shorter_than_changed_files_is_flagged_truncated(self):
        self.changed_files = 3001
        rec = self.tc.build_record("romp-on/romp", 42, "tok")
        self.assertTrue(rec["files_truncated"])
        self.assertEqual(self.tc.evaluate(rec)["conclusion"], "success", "an admin-approved fix still passes")
        rec["reviews"] = []
        self.assertEqual(self.tc.evaluate(rec)["conclusion"], "failure", "unapproved, the unseen files hold it")
        rec["labels"] = ["docs"]
        self.assertEqual(self.tc.evaluate(rec)["conclusion"], "failure", "docs cannot vouch for unseen files either")


class DeclaredTier(unittest.TestCase):
    """The body's tier line (T273, the owner 2026-09-08): outside contributors hold read permission and
    cannot label their own PRs, so the author writes `Tier: fix` in the PR body and the tier workflow
    applies the label. declared_tier(body) is the pure parser: the first word after "Tier:" is the tier,
    case-insensitive, one of the four (the tests-only alias reads as docs), prose after it allowed unless it
    names another tier (T273b); HTML comments and code are not read, so the template's explanation never
    parses; two lines naming different tiers declare nothing, and the reason says so.
    A label already on the PR always wins: the body is then only remarked on."""

    def test_each_tier_parses_from_its_own_line(self):
        for t in tp.TIERS:
            self.assertEqual(tp.declared_tier("one line about the change\n\nTier: %s\n\n## Tests\n" % t), (t, ""))

    def test_case_bold_backticks_and_a_list_marker_are_tolerated(self):
        for body in ("tier: FIX", "**Tier:** fix", "Tier: `fix`", "- Tier: fix", "  TIER :  Fix  ", "__Tier__: fix"):
            self.assertEqual(tp.declared_tier(body)[0], "fix", body)

    def test_the_alias_reads_as_docs(self):
        self.assertEqual(tp.declared_tier("Tier: tests-only")[0], "docs")

    def test_no_line_declares_nothing_and_says_nothing(self):
        self.assertEqual(tp.declared_tier(""), (None, ""))
        self.assertEqual(tp.declared_tier(None), (None, ""))
        self.assertEqual(tp.declared_tier("fixes #7\n\nthe tier is fix, really\n## Tier\n"), (None, ""))

    def test_the_first_word_is_the_tier_and_trailing_prose_is_allowed(self):
        # T273b (the manager, 2026-09-08): a contributor wrote the tier word and then a sentence on the same
        # line, and the line declared nothing until a maintainer labeled by hand. The FIRST word after
        # "Tier:" (markup stripped) is the declaration; prose after it is ignored unless it names another tier
        for body in ("Tier: `fix` — please label this one, I have no triage",
                     "Tier: fix (see the test below)",
                     "Tier: fix. This closes the parser gap.",
                     "Tier: **fix** since it comes with a failing test",
                     "Tier: fix and a bit more",
                     "Tier: fix - a fix for the parser"):
            self.assertEqual(tp.declared_tier(body), ("fix", ""), body)
        self.assertEqual(tp.declared_tier("Tier: major-feature: it changes the contract")[0], "major-feature")
        self.assertEqual(tp.declared_tier("Tier: tests-only, docs only")[0], "docs", "the alias as first word")

    def test_punctuation_glued_to_the_tier_word_still_reads_the_word(self):
        # an em dash or a parenthesis set without spaces, smart quotes from a phone keyboard, an ellipsis:
        # words split on punctuation as well as on whitespace, so the first WORD is still the tier
        for body in ("Tier: fix—closes the parser gap", "Tier: `fix`—please label", "Tier: fix(see below)",
                     "Tier: \u2018fix\u2019", "Tier: \u201cfix\u201d", "Tier: fix\u2026", "Tier:\u00a0fix", "Tier: <b>fix</b> please"):
            self.assertEqual(tp.declared_tier(body), ("fix", ""), repr(body))
        self.assertEqual(tp.declared_tier("Tier: major-feature—see #7")[0], "major-feature", "the inner hyphen survives")
        for body in ("Tier: fix/feature", "Tier: fix,feature", "Tier: fix—feature"):
            self.assertIsNone(tp.declared_tier(body)[0], body)
            self.assertIn("more than one tier", tp.declared_tier(body)[1], body)

    def test_an_ambiguous_line_counts_like_a_line_naming_no_tier(self):
        # consistent with the placeholder: a line that declares nothing never vetoes a clean line elsewhere;
        # alone, it is what the summary quotes
        self.assertEqual(tp.declared_tier("Tier: fix or feature\n\nTier: fix"), ("fix", ""))
        self.assertEqual(tp.declared_tier("Tier: <one of docs, fix, feature, major-feature>\n\nTier: fix"), ("fix", ""))
        tier, why = tp.declared_tier("Tier: fix or feature\n\nTier: bogus")
        self.assertIsNone(tier)
        self.assertIn("more than one tier", why)

    def test_a_line_naming_two_tiers_declares_nothing_and_says_so(self):
        for body in ("Tier: fix or feature", "Tier: fix (maybe feature?)", "Tier: docs — not a fix"):
            tier, why = tp.declared_tier(body)
            self.assertIsNone(tier, body)
            self.assertIn("more than one tier", why, body)
        tier, why = tp.declared_tier("Tier: fix or feature")
        for word in ("fix", "feature"):
            self.assertIn(word, why)

    def test_a_first_word_that_is_no_tier_declares_nothing_whatever_follows(self):
        for body in ("Tier: fixes the parser", "Tier: a fix", "Tier: the tier is fix"):
            tier, why = tp.declared_tier(body)
            self.assertIsNone(tier, body)
            self.assertIn("names no tier", why, body)
        self.assertIn("fixes the parser", tp.declared_tier("Tier: fixes the parser")[1])

    def test_a_value_that_is_not_a_tier_declares_nothing_and_names_itself(self):
        tier, why = tp.declared_tier("Tier: bugfix")
        self.assertIsNone(tier)
        self.assertIn("bugfix", why)
        self.assertIn("names no tier", why)
        tier, why = tp.declared_tier("Tier:")
        self.assertIsNone(tier)
        self.assertTrue(why, "an empty line is said, not skipped")

    def test_html_comments_are_not_read(self):
        self.assertEqual(tp.declared_tier("<!-- Tier: fix -->"), (None, ""))
        self.assertEqual(tp.declared_tier("<!--\nTier: fix\n-->\nTier: docs")[0], "docs")
        # an unclosed comment hides the rest of the body on GitHub too (a trimmed template that lost its
        # closing marker): what the reader cannot see declares nothing
        self.assertEqual(tp.declared_tier("Tier: docs\n<!-- explanation never closed\nTier: fix\n"), ("docs", ""))
        self.assertEqual(tp.declared_tier("<!-- never closed\nTier: fix\n"), (None, ""))

    def test_code_blocks_and_quotes_are_not_read(self):
        # a docs PR quoting the template line in a fence, a pasted snippet, a quoted reply
        self.assertEqual(tp.declared_tier("Tier: fix\n\n```\nTier: feature\n```\n")[0], "fix")
        self.assertEqual(tp.declared_tier("~~~md\nTier: feature\n~~~\nTier: fix")[0], "fix")
        self.assertEqual(tp.declared_tier("```\nTier: feature\n"), (None, ""), "an unclosed fence runs to the end")
        self.assertEqual(tp.declared_tier("    Tier: feature\nTier: fix")[0], "fix", "four spaces indent a code block")
        self.assertEqual(tp.declared_tier("> Tier: feature\nTier: fix")[0], "fix")

    def test_trailing_punctuation_and_crlf_are_tolerated(self):
        for body in ("Tier: fix.", "Tier: fix,\r\n", "Tier: `fix`.\r\nmore\r\n"):
            self.assertEqual(tp.declared_tier(body)[0], "fix", repr(body))

    def test_crlf_bodies_keep_the_declaration_behind_a_fenced_block(self):
        # GitHub's web editor writes CRLF; a fence's closing line then ends in \r, which a `$`-anchored
        # close could not match, so the fence read as unclosed and swallowed the declaration (the
        # manager's review, 2026-09-08). Line endings are normalised before any pattern runs
        self.assertEqual(tp.declared_tier("Summary\r\n\r\n```\r\ncode\r\n```\r\n\r\nTier: fix\r\n"), ("fix", ""))
        self.assertEqual(tp.declared_tier("<!-- note\r\n-->\r\nTier: docs\r\n"), ("docs", ""))
        self.assertEqual(tp.declared_tier("```\rcode\r```\rTier: feature\r"), ("feature", ""), "bare CR too")

    def test_the_odd_excerpt_cannot_render_as_markdown_in_the_check_summary(self):
        # the summary is rendered as Markdown in the Checks tab under the gate's own identity: a link, a
        # tracking image or text that reads like an approval must come back as literal text (a code span,
        # with any backtick of its own removed so the span cannot be broken out of)
        # (first words that are no tier: under T273b a tier word followed by prose is a declaration)
        for raw in ("<img src=https://x.example/p.png>", "[fix](https://x.example) approved", "notatier` **APPROVED** `"):
            tier, why = tp.declared_tier("Tier: " + raw)
            self.assertIsNone(tier)
            shown = raw.replace("`", "").strip()          # the excerpt drops the value's own backticks, then trims
            self.assertIn("`%s`" % shown, why, why)
            self.assertNotRegex(why, r"(?<!`)\[fix\]\(", "no bare link")
            self.assertNotRegex(why, r"(?<!`)<img", "no bare tag")
        self.assertIn("`(empty)`", tp.declared_tier("Tier:")[1])

    def test_the_odd_value_echoed_back_is_bounded(self):
        tier, why = tp.declared_tier("Tier: " + "x" * 65000)
        self.assertIsNone(tier)
        self.assertLess(len(why), 300, "the check summary quotes a bounded excerpt, never the whole line")
        tier, why = tp.declared_tier("\n".join("Tier: odd%d" % i for i in range(50)))
        self.assertIsNone(tier)
        self.assertLess(len(why), 300)
        self.assertIn("odd0", why)

    def test_two_lines_naming_different_tiers_declare_nothing_and_say_so(self):
        tier, why = tp.declared_tier("Tier: fix\n\nTier: feature")
        self.assertIsNone(tier)
        self.assertIn("disagree", why)
        for word in ("fix", "feature"):
            self.assertIn(word, why)

    def test_two_lines_naming_the_same_tier_agree(self):
        self.assertEqual(tp.declared_tier("Tier: fix\nTier: FIX")[0], "fix")

    def test_the_template_placeholder_never_parses(self):
        tmpl = open(os.path.join(os.path.dirname(HERE), ".github", "PULL_REQUEST_TEMPLATE.md")).read()
        self.assertRegex(tmpl, r"(?m)^Tier: ", "the template carries the fill-in line")
        tier, why = tp.declared_tier(tmpl)
        self.assertIsNone(tier, "the untouched template declares no tier")
        self.assertIn("names no tier", why, "...and the reason points at the placeholder")
        for t in tp.TIERS:
            self.assertEqual(tp.declared_tier(tmpl.replace(re.search(r"(?m)^Tier: .*$", tmpl).group(0), "Tier: " + t))[0], t,
                             "the placeholder replaced by a tier parses as that tier")

    # evaluate reads the same line: with no label it names the label the workflow applies; with a label
    # the label stands and a disagreeing body is only mentioned
    def test_no_label_and_a_declared_tier_fails_naming_the_label_the_workflow_applies(self):
        v = tp.evaluate(pr(labels=[], body="Tier: fix"))
        self.assertEqual(v["conclusion"], "failure", "pure: the label is not on the PR yet")
        self.assertIn("`fix`", v["summary"])
        self.assertIn("applies", v["summary"])

    def test_no_label_and_disagreeing_lines_say_so(self):
        v = tp.evaluate(pr(labels=[], body="Tier: fix\nTier: feature"))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("disagree", v["summary"])

    def test_no_label_and_no_line_points_at_the_body_line(self):
        v = tp.evaluate(pr(labels=[]))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("Tier:", v["summary"])

    def test_a_label_stands_over_a_disagreeing_body_and_the_verdict_mentions_it(self):
        v = tp.evaluate(pr(labels=["fix"], body="Tier: feature"))
        self.assertEqual(v["conclusion"], "success", "the fix label's own verdict")
        self.assertIn("`feature`", v["summary"])
        self.assertIn("relabel", v["summary"])
        v = tp.evaluate(pr(labels=["feature"], body="Tier: fix"))
        self.assertEqual(v["conclusion"], "failure", "a contributor's feature waits, whatever the body says")
        self.assertIn("relabel", v["summary"])

    def test_no_label_after_a_maintainers_removal_says_the_line_is_not_re_applied(self):
        v = tp.evaluate(pr(labels=[], body="Tier: fix", tier_unlabeled_by=["maint-b"]))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("maint-b", v["summary"])
        self.assertIn("not re-applied", v["summary"])
        self.assertNotIn("applies that label", v["summary"])

    def test_a_label_matching_the_body_is_not_remarked_on(self):
        v = tp.evaluate(pr(labels=["fix"], body="Tier: fix"))
        self.assertNotIn("body", v["summary"])
        self.assertNotIn("relabel", v["summary"])

    def test_two_labels_still_fail_whatever_the_body_says(self):
        v = tp.evaluate(pr(labels=["fix", "feature"], body="Tier: fix"))
        self.assertEqual(v["conclusion"], "failure")
        self.assertIn("2", v["title"])
