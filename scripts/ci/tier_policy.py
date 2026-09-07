#!/usr/bin/env python3
"""The PR tier POLICY as a pure function — the maintainers' decisions of 2026-09-07 for romp-on/romp.

`evaluate(pr)` takes a synthetic-shaped PR record (the workflow's fetcher builds the same shape from
the GitHub API; tests build it by hand) and returns the check-run verdict: {"conclusion", "title",
"summary"}. No I/O here, ever — the meaning of the gate lives in this file and in tests/test_tier_policy.py.

Record shape (every key the rules read):
  labels: [str]            author: login          head_sha: str          files: [path]
  reviews: [{user, state, commit_id, submitted_at, dismissed}]   permissions: {login: permission}
  first_check_at: epoch|None   created_at: epoch   now: epoch   body: str
  issues: {number: {exists, is_pr, comments: [login]}}

Tiers: docs (documentation only) passes on green; fix passes on an approval OR seven unchanged days with
no changes requested; feature passes on an approval; major-feature passes on an approval AND a linked
issue someone other than the author has commented on. A PR touching .github/ needs an approval whatever
its tier (the base-branch gate cannot stop a PR-branch job from posting a same-named success on
pull_request events, so a human must look). Zero or two tier labels fail (belt and braces with the label
check). An approval is the LATEST review per reviewer that is APPROVED, by a non-author holding
write/admin/maintain, on the CURRENT head; dismissed reviews never count. The seven-day clock reads the
server-stamped first "Tier policy" check run for the head (commit dates are free to forge), falling back
to the PR's created_at."""
import re

TIERS = ("docs", "fix", "feature", "major-feature")
MAINTAINER_PERMS = ("write", "admin", "maintain")
SEVEN_DAYS = 7 * 86400
_ISSUE_REF = re.compile(r"(?:^|[^\w/])#(\d+)\b|github\.com/romp-on/romp/issues/(\d+)\b")


def _is_doc(path):
    if path.startswith(".github/") or path.startswith("scripts/"):
        return False
    return path.startswith("docs/") or path.endswith(".md")


def _latest_reviews(pr):
    """{reviewer: latest non-dismissed review} — the latest word per reviewer stands."""
    latest = {}
    for r in sorted(pr.get("reviews") or [], key=lambda r: r.get("submitted_at") or 0):
        if r.get("dismissed"):
            continue
        latest[r["user"]] = r
    return latest


def _approved(pr):
    """(True, who) when an approval counts: a non-author with write/admin/maintain, APPROVED, on the
    current head. Otherwise (False, why)."""
    perms = pr.get("permissions") or {}
    seen_stale = False
    for user, r in _latest_reviews(pr).items():
        if user == pr.get("author"):
            continue
        if perms.get(user) not in MAINTAINER_PERMS:
            continue
        if r.get("state") != "APPROVED":
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
            if u != pr.get("author") and perms.get(u) in MAINTAINER_PERMS and r.get("state") == "CHANGES_REQUESTED"]


def _linked_issue_discussed(pr):
    """(True, n) when the body references an issue in romp-on/romp that exists, is not a PR, and has a
    comment by someone other than the author; else (False, why)."""
    body = pr.get("body") or ""
    refs = [int(a or b) for a, b in _ISSUE_REF.findall(body)]
    if not refs:
        return False, "the body links no issue (#N or a romp-on/romp issue URL)"
    issues = pr.get("issues") or {}
    for n in refs:
        info = issues.get(n) or issues.get(str(n))
        if not info or not info.get("exists") or info.get("is_pr"):
            continue
        if any(c != pr.get("author") for c in (info.get("comments") or [])):
            return True, n
    return False, "the linked issue(s) carry no comment by anyone other than the author (or are PRs / missing)"


def evaluate(pr):
    labels = [l for l in (pr.get("labels") or []) if l in TIERS]
    if len(labels) != 1:
        return {"conclusion": "failure", "title": "Tier policy: %d tier labels" % len(labels),
                "summary": "Exactly one tier label is required (docs, fix, feature, major-feature); this PR carries %d."
                           % len(labels)}
    tier = labels[0]
    files = list(pr.get("files") or [])
    touches_github = any(f.startswith(".github/") for f in files)
    ok, who = _approved(pr)
    reasons = []

    if tier == "docs":
        bad = [f for f in files if not _is_doc(f)]
        if bad:
            return {"conclusion": "failure", "title": "Tier policy: docs",
                    "summary": "The docs tier is documentation only (docs/** or *.md, never .github/** or "
                               "scripts/**); these files are not: %s. Pick another tier." % ", ".join(bad)}
        if touches_github:
            return {"conclusion": "failure", "title": "Tier policy: docs",
                    "summary": "A PR touching .github/ needs an approval regardless of tier."}
        return {"conclusion": "success", "title": "Tier policy: docs",
                "summary": "Documentation only; merges on green."}

    if touches_github and not ok:
        return {"conclusion": "failure", "title": "Tier policy: %s" % tier,
                "summary": "This PR touches .github/ and so needs an approval regardless of tier: %s." % who}

    if tier == "fix":
        if ok:
            return {"conclusion": "success", "title": "Tier policy: fix",
                    "summary": "Approved by %s on the current head." % who}
        objectors = _changes_requested(pr)
        if objectors:
            return {"conclusion": "failure", "title": "Tier policy: fix",
                    "summary": "Changes requested by %s; the seven-day path is closed until they say otherwise."
                               % ", ".join(objectors)}
        since = pr.get("first_check_at") or pr.get("created_at") or pr.get("now")
        waited = (pr.get("now") or 0) - since
        if waited >= SEVEN_DAYS:
            return {"conclusion": "success", "title": "Tier policy: fix",
                    "summary": "Seven days with the head unchanged and no changes requested (clock: the first "
                               "Tier policy run for this head, or the PR's creation)."}
        return {"conclusion": "failure", "title": "Tier policy: fix",
                "summary": "%s; or wait: %.1f of seven days elapsed since this head's first check run."
                           % (who, max(waited, 0) / 86400.0)}

    if tier == "feature":
        if ok:
            return {"conclusion": "success", "title": "Tier policy: feature",
                    "summary": "Approved by %s on the current head." % who}
        return {"conclusion": "failure", "title": "Tier policy: feature", "summary": who + "."}

    # major-feature
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
