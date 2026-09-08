#!/usr/bin/env python3
"""The PR tier POLICY as a pure function — the maintainers' decisions of 2026-09-07 for romp-on/romp.

`evaluate(pr)` takes a PR record (the workflow's fetcher builds it from the GitHub API; tests build it by
hand) and returns the check-run verdict: {"conclusion", "title", "summary"}. No I/O here, ever — the
meaning of the gate lives in this file and in tests/test_tier_policy.py.

Record shape (every key the rules read):
  labels: [str]          author: login         head_sha: str
  files: [path]          (a renamed or copied file appears under BOTH its old and new path)
  files_truncated: bool  (the API lists at most 3000 files; True when the PR has more than it listed)
  reviews: [{user, state, commit_id, submitted_at, dismissed, dismissed_by}]   (state = the ORIGINAL state;
            for a dismissed review the fetcher recovers it, and the dismisser, from the review_dismissed event)
  permissions: {login: permission}
  first_check_at: epoch|None   (chain_start of THIS PR's hourly verdicts on this head, anchored at now)
  head_floor: epoch   now: epoch   body: str
  (the fetcher also records created_at; no rule reads it - head_floor already starts from it)
  issues: {number: {exists, is_pr, comments: [login]}}   (commenters; bots already filtered out by the fetcher)

Tiers: docs (documentation only) passes on green; fix passes on an approval OR seven days with the head
unchanged and no changes requested; feature passes on an approval; major-feature passes on an approval AND
a linked issue someone other than the author has COMMENTED on (the opener alone is not a discussion: the
maintainers' ruling of 2026-09-07 on the discussion issue). A PR touching .github/ or scripts/ci/ — the
gate's own workflow and code — needs an approval whatever its tier; so does a PR whose file listing the
API truncated (the unseen files are assumed guarded and not documentation). Zero or two tier labels fail.

An approval is a reviewer's STANDING — their latest APPROVED / CHANGES_REQUESTED / DISMISSED review; a
COMMENTED review (GitHub files one per inline comment) never changes standing — that is APPROVED, by a
non-author holding write/admin/maintain, on the CURRENT head. Dismissals are read fail-closed, in both
directions: a dismissed APPROVED never counts, whoever dismissed it (as the PR page shows it; a review
dismisses only once, so were a third party's dismissal ignored, the author could spend it first and lock
the peer's approval in with no way left for the peer to withdraw — the review's catch against the
symmetric rule); a dismissed CHANGES_REQUESTED is cleared only when the reviewer dismissed it THEMSELVES,
and a dismissal by anyone else leaves the objection standing, so the author (who holds write too) cannot
dismiss the peer's objection to reopen the seven-day path (the maintainers' ruling, 2026-09-07). A
reviewer whose objection someone else dismissed lifts it by approving.

The seven-day clock: since = the later of head_floor and first_check_at. first_check_at is the start of
the UNBROKEN chain of hourly "Tier policy" verdicts THIS PR received on this head (each verdict carries
the PR number as its external_id; the chain must reach to now, and a gap longer than VERDICT_GAP breaks
it): seven days means seven consecutive days with this head visible as this PR's head. So a sibling PR's
verdicts on the same sha lend nothing (the review's critical catch: fast-forwarding a second PR onto a
head the other maintainer vetoed inherited the first PR's clock while the objection stayed invisible),
and a sha pushed away and back starts over. head_floor is the server-stamped moment this head became THIS
PR's reviewable head — the PR's created_at, raised by every force-push, reopen, and draft-to-ready event
on its timeline — so a reopened PR or one converted from draft starts over too. A head with no verdict
yet has NOT started its clock: the run that evaluates it posts the first (created_at is never a fallback
— a stale PR's age would stand in for the gate's first look). Commit dates are never read: they are the
author's to set."""

TIERS = ("docs", "fix", "feature", "major-feature")
# TRANSITION (2026-09-07): `docs` is `tests-only` renamed; until the label itself is renamed on the
# upstream, PRs still carry the old name. It reads as `docs` here and in the label check, so nothing
# is stranded between this landing and the rename. Drop the alias once the label is renamed.
TIER_ALIASES = {"tests-only": "docs"}
MAINTAINER_PERMS = ("write", "admin", "maintain")
# the review states that set a reviewer's standing; COMMENTED (one per inline comment) and PENDING do not
STANDING_STATES = ("APPROVED", "CHANGES_REQUESTED", "DISMISSED")
TRUNCATED = "files beyond the API's 3000-entry listing"
SEVEN_DAYS = 7 * 86400
# paths whose change needs an approval regardless of tier: the gate's own workflow and code (a PR that
# rewrites the policy through the seven-day path would have graded itself)
GUARDED_PREFIXES = (".github/", "scripts/ci/")
import re
_ISSUE_REF = re.compile(r"(?:^|[^\w/])#(\d+)\b|github\.com/romp-on/romp/issues/(\d+)\b")


def _is_doc(path):
    if path.startswith(".github/") or path.startswith("scripts/"):
        return False
    return path.startswith("docs/") or path.endswith(".md")


def _standing(r):
    """The state a review contributes to its reviewer's standing, dismissals read fail-closed. Undismissed:
    its state. A dismissed APPROVED: DISMISSED, whoever dismissed it — an approval that the PR page shows
    struck out never counts (ignoring a third party's dismissal would let the author spend the review's
    one dismissal first and lock the approval in). A dismissed CHANGES_REQUESTED: DISMISSED only when the
    reviewer dismissed it themselves (their own word); dismissed by anyone else — the author holds write
    too — or by an unknown actor, the objection still stands."""
    if not r.get("dismissed") or r.get("state") == "APPROVED":
        return "DISMISSED" if r.get("dismissed") else r.get("state")
    return "DISMISSED" if r.get("dismissed_by") == r.get("user") else r.get("state")


def _latest_reviews(pr):
    """{reviewer: latest standing-bearing review} — the latest APPROVED / CHANGES_REQUESTED / dismissed
    review per reviewer; a COMMENTED or PENDING review is skipped, so one inline note after an approval
    (or an objection) leaves it standing. Read the review's effect through _standing."""
    latest = {}
    for r in sorted(pr.get("reviews") or [], key=lambda r: r.get("submitted_at") or 0):
        if r.get("state") in STANDING_STATES:            # `state` is the ORIGINAL state, dismissed or not
            latest[r["user"]] = r
    return latest


def _approved(pr):
    perms = pr.get("permissions") or {}
    seen_stale = False
    for user, r in _latest_reviews(pr).items():
        if user == pr.get("author") or perms.get(user) not in MAINTAINER_PERMS:
            continue
        if _standing(r) != "APPROVED":
            continue
        if r.get("commit_id") != pr.get("head_sha"):
            seen_stale = True
            continue
        return True, user
    if seen_stale:
        return False, "an approval exists but for an older head - a push after approval needs re-approval on the current head"
    return False, "no approval by a maintainer other than the author on the current head"


def _changes_requested(pr):
    perms = pr.get("permissions") or {}
    return [u for u, r in _latest_reviews(pr).items()
            if u != pr.get("author") and perms.get(u) in MAINTAINER_PERMS
            and _standing(r) == "CHANGES_REQUESTED"]


def _linked_issue_discussed(pr):
    """(True, n) when the body references an issue in romp-on/romp that exists, is not a PR, and carries a
    COMMENT by someone other than the author (bots filtered by the fetcher). The opener does not count on
    their own: an issue filed and never answered is not a discussion (the maintainers, 2026-09-07)."""
    refs = [int(a or b) for a, b in _ISSUE_REF.findall(pr.get("body") or "")]
    if not refs:
        return False, "the body links no issue (#N or a romp-on/romp issue URL)"
    issues = pr.get("issues") or {}
    for n in refs:
        info = issues.get(n) or issues.get(str(n))
        if not info or not info.get("exists") or info.get("is_pr"):
            continue
        if any(c != pr.get("author") for c in info.get("comments") or []):
            return True, n
    return False, "the linked issue(s) carry no comment by someone other than the author (or are PRs / missing)"


def chain_start(stamps, now, gap):
    """The start of the unbroken run of verdict stamps that ends within `gap` of now, or None when there
    is none or the latest is stale. The hourly sweep stamps a head every hour it is this PR's head, so a
    longer gap means it was not (force-pushed away and back; a sibling branch fast-forwarded onto it) or
    the gate was down - either way the clock restarts. Pure: the fetcher feeds it this PR's stamps."""
    s = sorted(x for x in stamps or [] if x)
    if not s or now - s[-1] > gap:
        return None
    start = s[-1]
    for prev in reversed(s[:-1]):
        if start - prev > gap:
            break
        start = prev
    return start


def _clock_since(pr):
    """When the seven-day clock started, or None when it has not: no verdict has stamped this head yet
    (the run evaluating it posts the first), or the record lacks head_floor (the fetcher always sets it,
    so fail closed on its absence)."""
    first, floor = pr.get("first_check_at"), pr.get("head_floor")
    if not first or not floor:
        return None
    return max(floor, first)


def evaluate(pr):
    labels = [TIER_ALIASES.get(l, l) for l in (pr.get("labels") or []) if TIER_ALIASES.get(l, l) in TIERS]
    if len(labels) != 1:
        return {"conclusion": "failure", "title": "Tier policy: %d tier labels" % len(labels),
                "summary": "Exactly one tier label is required (docs, fix, feature, major-feature); this PR carries %d."
                           % len(labels)}
    tier = labels[0]
    files = list(pr.get("files") or [])
    truncated = bool(pr.get("files_truncated"))
    guarded = [f for f in files if f.startswith(GUARDED_PREFIXES)] + ([TRUNCATED] if truncated else [])
    ok, who = _approved(pr)

    if tier == "docs":
        bad = [f for f in files if not _is_doc(f)] + ([TRUNCATED] if truncated else [])
        if bad:
            return {"conclusion": "failure", "title": "Tier policy: docs",
                    "summary": "The docs tier is documentation only (docs/** or *.md, never .github/** or "
                               "scripts/**); these files are not: %s. Pick another tier." % ", ".join(bad)}
        return {"conclusion": "success", "title": "Tier policy: docs",
                "summary": "Documentation only; merges on green."}

    if guarded and not ok:
        return {"conclusion": "failure", "title": "Tier policy: %s" % tier,
                "summary": "This PR touches the gate's own files (%s) and so needs an approval regardless of tier: %s."
                           % (", ".join(guarded), who)}

    if tier == "fix":
        if ok:
            return {"conclusion": "success", "title": "Tier policy: fix",
                    "summary": "Approved by %s on the current head." % who}
        objectors = _changes_requested(pr)
        if objectors:
            return {"conclusion": "failure", "title": "Tier policy: fix",
                    "summary": "Changes requested by %s; the seven-day path is closed until they say otherwise."
                               % ", ".join(objectors)}
        since = _clock_since(pr)
        if since is None:
            return {"conclusion": "failure", "title": "Tier policy: fix",
                    "summary": "%s; no Tier policy verdict has stamped this head yet, so the seven-day clock "
                               "starts with this run." % who}
        waited = (pr.get("now") or 0) - since
        if waited >= SEVEN_DAYS:
            return {"conclusion": "success", "title": "Tier policy: fix",
                    "summary": "Seven days with the head unchanged and no changes requested (clock: the later of "
                               "this head's arrival on the PR and its first Tier policy run)."}
        return {"conclusion": "failure", "title": "Tier policy: fix",
                "summary": "%s; or wait: %.1f of seven days elapsed since this head became the PR's head."
                           % (who, max(waited, 0) / 86400.0)}

    if tier == "feature":
        if ok:
            return {"conclusion": "success", "title": "Tier policy: feature",
                    "summary": "Approved by %s on the current head." % who}
        return {"conclusion": "failure", "title": "Tier policy: feature", "summary": who + "."}

    discussed, why = _linked_issue_discussed(pr)
    if ok and discussed:
        return {"conclusion": "success", "title": "Tier policy: major-feature",
                "summary": "Approved by %s on the current head, with the discussion in issue #%s." % (who, why)}
    missing = []
    if not ok:
        missing.append(who)
    if not discussed:
        missing.append("a discussed linked issue is required: " + why)
    return {"conclusion": "failure", "title": "Tier policy: major-feature", "summary": "; ".join(missing) + "."}


if __name__ == "__main__":
    import json, sys
    print(json.dumps(evaluate(json.load(sys.stdin))))
