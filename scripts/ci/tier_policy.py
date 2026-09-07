#!/usr/bin/env python3
"""The PR tier POLICY as a pure function — the maintainers' decisions of 2026-09-07 for romp-on/romp.

`evaluate(pr)` takes a PR record (the workflow's fetcher builds it from the GitHub API; tests build it by
hand) and returns the check-run verdict: {"conclusion", "title", "summary"}. No I/O here, ever — the
meaning of the gate lives in this file and in tests/test_tier_policy.py.

Record shape (every key the rules read):
  labels: [str]          author: login         head_sha: str          files: [path]
  reviews: [{user, state, commit_id, submitted_at, dismissed}]      permissions: {login: permission}
  first_check_at: epoch|None   head_floor: epoch   created_at: epoch   now: epoch   body: str
  issues: {number: {exists, is_pr, user, comments: [login]}}   (bots already filtered out by the fetcher)

Tiers: docs (documentation only) passes on green; fix passes on an approval OR seven days with the head
unchanged and no changes requested; feature passes on an approval; major-feature passes on an approval AND
a linked issue someone other than the author took part in. A PR touching .github/ or scripts/ci/ — the
gate's own workflow and code — needs an approval whatever its tier. Zero or two tier labels fail.

An approval is the LATEST review per reviewer (a DISMISSED review stands as that reviewer's latest word
and never approves) that is APPROVED, by a non-author holding write/admin/maintain, on the CURRENT head.

The seven-day clock: since = the later of head_floor and the first "Tier policy" check run for the head.
head_floor is the server-stamped moment this head became THIS PR's reviewable head — the PR's created_at,
raised by every force-push, reopen, and draft-to-ready event on its timeline — so a sha seen briefly at
day 0 and force-pushed back on day 7, a reopened PR, a PR converted from draft, or a new PR reusing an old
head all start over. Commit dates are never read: they are the author's to set."""

TIERS = ("docs", "fix", "feature", "major-feature")
# TRANSITION (2026-09-07): `docs` is `tests-only` renamed; until the label itself is renamed on the
# upstream, PRs still carry the old name. It reads as `docs` here and in the label check, so nothing
# is stranded between this landing and the rename. Drop the alias once the label is renamed.
TIER_ALIASES = {"tests-only": "docs"}
MAINTAINER_PERMS = ("write", "admin", "maintain")
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


def _latest_reviews(pr):
    """{reviewer: latest review} — the latest word per reviewer stands, a DISMISSED one included (it
    is a non-approval, never an erasure that revives an earlier approval)."""
    latest = {}
    for r in sorted(pr.get("reviews") or [], key=lambda r: r.get("submitted_at") or 0):
        latest[r["user"]] = r
    return latest


def _approved(pr):
    perms = pr.get("permissions") or {}
    seen_stale = False
    for user, r in _latest_reviews(pr).items():
        if user == pr.get("author") or perms.get(user) not in MAINTAINER_PERMS:
            continue
        if r.get("dismissed") or r.get("state") != "APPROVED":
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
            and not r.get("dismissed") and r.get("state") == "CHANGES_REQUESTED"]


def _linked_issue_discussed(pr):
    """(True, n) when the body references an issue in romp-on/romp that exists, is not a PR, and has a
    participant (opener or commenter; bots filtered by the fetcher) other than the author."""
    refs = [int(a or b) for a, b in _ISSUE_REF.findall(pr.get("body") or "")]
    if not refs:
        return False, "the body links no issue (#N or a romp-on/romp issue URL)"
    issues = pr.get("issues") or {}
    for n in refs:
        info = issues.get(n) or issues.get(str(n))
        if not info or not info.get("exists") or info.get("is_pr"):
            continue
        participants = set(info.get("comments") or [])
        if info.get("user"):
            participants.add(info["user"])
        if any(p != pr.get("author") for p in participants):
            return True, n
    return False, "the linked issue(s) have no participant other than the author (or are PRs / missing)"


def _clock_since(pr):
    floor = pr.get("head_floor") or pr.get("created_at") or pr.get("now") or 0
    first = pr.get("first_check_at")
    return max(floor, first) if first else floor


def evaluate(pr):
    labels = [TIER_ALIASES.get(l, l) for l in (pr.get("labels") or []) if TIER_ALIASES.get(l, l) in TIERS]
    if len(labels) != 1:
        return {"conclusion": "failure", "title": "Tier policy: %d tier labels" % len(labels),
                "summary": "Exactly one tier label is required (docs, fix, feature, major-feature); this PR carries %d."
                           % len(labels)}
    tier = labels[0]
    files = list(pr.get("files") or [])
    guarded = [f for f in files if f.startswith(GUARDED_PREFIXES)]
    ok, who = _approved(pr)

    if tier == "docs":
        bad = [f for f in files if not _is_doc(f)]
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
        waited = (pr.get("now") or 0) - _clock_since(pr)
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
