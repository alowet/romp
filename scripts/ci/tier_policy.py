#!/usr/bin/env python3
"""The PR tier POLICY as a pure function for romp-on/romp: the repository owner's rules of 2026-09-08, by
tier and by the AUTHOR's role (replacing the maintainers' text of 2026-09-07 and its seven-day clock).

`evaluate(pr)` takes a PR record (the workflow's fetcher builds it from the GitHub API; tests build it by
hand) and returns the check-run verdict: {"conclusion", "title", "summary"}. No I/O here, ever: the
meaning of the gate lives in this file and in tests/test_tier_policy.py.

Record shape (every key the rules read):
  labels: [str]          author: login         head_sha: str
  files: [path]          (a renamed or copied file appears under BOTH its old and new path)
  files_truncated: bool  (the API lists at most 3000 files; True when the PR has more than it listed)
  reviews: [{user, state, commit_id, submitted_at, dismissed, dismissed_by}]   (state = the ORIGINAL state;
            for a dismissed review the fetcher recovers it, and the dismisser, from the review_dismissed event)
  permissions: {login: permission}   (every reviewer AND the author; the author's role is read from here)
  body: str              (the `Tier: <tier>` line is read here, T273; see declared_tier)
  tier_unlabeled_by: [login]   (everyone other than the author who ever REMOVED a tier label, from the issue
                          events; bots filtered. Non-empty: the body's line is not re-applied, a maintainer set the tier)
  issues: {number: {exists, is_pr, comments: [login]}}   (commenters; bots already filtered out by the fetcher)
  There is no time field: nothing in the policy is timed, so the fetcher records no clock, no check-run
  history and no commit date (submitted_at orders one reviewer's reviews and is never compared to now).

Roles, read from the author's collaborator permission in that map: an ADMIN author is the repository
owner; a write or maintain author is a member; anyone else (read, none, or absent from the map) is a
contributor. The check treats members and contributors alike, so the one role that changes a gate is
admin, and an author whose permission the map lacks is read as a contributor: the stricter gate applies.

Tiers (the owner, 2026-09-08):
  docs / fix     ONE tier under two labels (tests-only is the pre-rename spelling of docs). Merges on
                 green for every author: the check requires no approval; whichever maintainer merges it is
                 the whole requirement.
  feature        By an admin author: merges on green (the owner's features merge straight away). By anyone
                 else: one APPROVED review by an admin other than the author on the current head (the
                 owner looks at a member's or a contributor's feature before it merges). No issue, no
                 waiting period.
  major-feature  For EVERY author, a linked issue that someone other than the author has COMMENTED on
                 (the write-up and its discussion; the opener alone is not a discussion, the maintainers'
                 ruling of 2026-09-07 kept). A non-admin author additionally needs an admin's approval on
                 the current head.
  the guard      A PR touching .github/ or scripts/ci/, the gate's own workflow and code, or whose file
                 listing the API truncated (the unseen files are assumed guarded): a non-admin author
                 needs an admin's approval whatever the tier. An admin author is exempt: the owner may
                 change the gate; the guard exists so that nobody else rewrites it through a PR the check
                 cannot see.
  every tier     A standing CHANGES_REQUESTED by a maintainer (write, maintain or admin) other than the
                 author holds the PR until that reviewer lifts it: an objection is an objection, an
                 approval by someone else does not lift it, only that reviewer's own next word does. No
                 tier has a time-based path. Zero or two tier labels fail.

An approval is a reviewer's STANDING (their latest APPROVED / CHANGES_REQUESTED / DISMISSED review; a
COMMENTED review, which GitHub files one per inline comment, never changes standing) that is APPROVED, by
an admin other than the author, on the CURRENT head. Dismissals are read fail-closed, in both directions:
a dismissed APPROVED never counts, whoever dismissed it (as the PR page shows it; a review dismisses only
once, so were a third party's dismissal ignored, the author could spend it first and lock the approval in
with no way left for the reviewer to withdraw); a dismissed CHANGES_REQUESTED is cleared only when the
reviewer dismissed it THEMSELVES, and a dismissal by anyone else leaves the objection standing, so an
author holding write cannot dismiss a peer's objection to merge on green (the maintainers' ruling of
2026-09-07, kept). A reviewer whose objection someone else dismissed lifts it by approving."""

TIERS = ("docs", "fix", "feature", "major-feature")
# TRANSITION (2026-09-07): `docs` is `tests-only` renamed; until the label itself is renamed on the
# upstream, PRs still carry the old name. It reads as `docs` here and in the label check, so nothing
# is stranded between this landing and the rename. Drop the alias once the label is renamed.
TIER_ALIASES = {"tests-only": "docs"}
# the labels that merge on green for every author: one tier under two names (the owner, 2026-09-08). Two
# of them on one PR are still two tier labels: the label check counts labels, and so does evaluate.
ON_GREEN = ("docs", "fix")
# the collaborator permissions that make a reviewer a maintainer: their standing objection holds any tier
MAINTAINER_PERMS = ("write", "admin", "maintain")
# the permission that makes an author the repository owner, and a reviewer the approver every gate asks for
ADMIN = "admin"
# the review states that set a reviewer's standing; COMMENTED (one per inline comment) and PENDING do not
STANDING_STATES = ("APPROVED", "CHANGES_REQUESTED", "DISMISSED")
TRUNCATED = "files beyond the API's 3000-entry listing"
# paths whose change needs an admin's approval regardless of tier when the author is not an admin: the
# gate's own workflow and code (a PR that rewrote the policy and merged on green would have graded itself)
GUARDED_PREFIXES = (".github/", "scripts/ci/")
import re
_ISSUE_REF = re.compile(r"(?:^|[^\w/])#(\d+)\b|github\.com/romp-on/romp/issues/(\d+)\b")
# the body's tier line (T273, the owner 2026-09-08): `Tier: fix` on a line of its own, read case-insensitively
# with bold, backticks or a list marker tolerated; HTML comments are cut out first, so the PR template's
# explanation of the tiers never parses. A read-only contributor cannot label their own PR (labeling needs
# triage), so this line is how they sort it: the workflow applies the matching label from it.
# HTML comments and fenced code are cut out first, each running to its close or to the end of the body (an
# unclosed comment or fence hides the rest on GitHub too, so what the reader cannot see declares nothing);
# a line indented four spaces is a code block and a `>` line a quote, neither a declaration
_HTML_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.S)
_CODE_FENCE = re.compile(r"^(```|~~~)[^\n]*\n.*?(?:^\1[ \t]*$|\Z)", re.S | re.M)
_TIER_LINE = re.compile(r"^ {0,3}(?:[-*]\s+)?[*_`]*tier[*_`]*\s*:[*_`]*\s*(.*?)\s*$", re.I)
_ODD_MAX, _ODD_LEN = 3, 40    # the check summary quotes a bounded excerpt of a line that names no tier
# markup and punctuation that separate the words of a tier line's value, whitespace aside: an em dash or a
# parenthesis set without spaces, smart quotes from a phone keyboard, an ellipsis, a slash. The ASCII hyphen
# is NOT a separator (major-feature is one word) and is trimmed only at a word's ends
_WORD_SPLIT = re.compile("[\\s`*_.,;:!?()\\[\\]{}<>\"'\u2018\u2019\u201c\u201d\u00ab\u00bb\u2026\u2014\u2013/]+")


_HTML_TAG = re.compile(r"<[^<>\n]*>")   # inline HTML around the word (<b>fix</b>) renders as the word alone


def _tier_words(raw):
    """The words of a tier line's value, each read as a tier or None: inline HTML tags removed, then split on
    whitespace, markup and punctuation (the alias mapped, lower-cased, an inner hyphen kept: major-feature; a
    hyphen at a word's ends dropped). Empty words are dropped. Pure. The template's placeholder is one tag
    and so reads as no words; the summary still quotes it, from the raw value."""
    out = []
    for w in _WORD_SPLIT.split(_HTML_TAG.sub(" ", raw or "")):
        w = w.strip("-").lower()
        if w:
            out.append(TIER_ALIASES.get(w, w) if TIER_ALIASES.get(w, w) in TIERS else None)
    return out


def _excerpt(raw):
    """A line's value quoted back into the check summary, which the Checks tab renders as Markdown under
    the gate's own identity: a code span, with the value's own backticks removed so it cannot break out of
    the span, so a link, an image tag or text that reads like an approval comes back as literal text."""
    shown = (raw or "").replace("`", "").strip() or "(empty)"
    if len(shown) > _ODD_LEN:
        shown = shown[:_ODD_LEN] + "…"
    return "`%s`" % shown


def declared_tier(body):
    """The tier the PR body declares on a `Tier: <tier>` line, as (tier, why): (tier, "") when exactly one
    tier is named (the same tier on two lines still agrees; the tests-only alias reads as docs); (None, "")
    when no line declares anything; (None, why) when a line exists but declares nothing, and why says so
    for the check's summary: lines naming different tiers disagree, a line naming more than one tier is
    ambiguous, a value whose first word is no tier (the template's untouched placeholder, a typo, an empty
    line) is quoted back. The FIRST word after "Tier:" is the declaration and prose after it is allowed
    (T273b: a contributor wrote the tier word and then a sentence, and the line declared nothing until a
    maintainer labeled by hand), unless that prose names another tier. Pure over the body text; HTML comments
    and fenced code are not read."""
    found, odd, ambiguous = [], [], []
    # line endings first: GitHub's web editor writes CRLF, and a fence's closing line ending in \r would
    # miss a `$`-anchored close, reading as unclosed and swallowing the declaration (the manager's review)
    text = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _CODE_FENCE.sub("", _HTML_COMMENT.sub("", text))
    for line in text.splitlines():
        m = _TIER_LINE.match(line)
        if not m:
            continue
        raw = m.group(1).strip()
        words = _tier_words(raw)
        first = words[0] if words else None
        if first is None:
            if len(odd) < _ODD_MAX:
                odd.append(_excerpt(raw))
            continue
        others = [w for w in words[1:] if w and w != first]
        if others:
            # a line naming two tiers declares nothing, like a line whose first word is no tier: it never
            # vetoes a clean line elsewhere, and alone it is what the summary explains
            ambiguous.append(", ".join(dict.fromkeys([first] + others)))
            continue
        found.append(first)
    distinct = list(dict.fromkeys(found))
    if len(distinct) > 1:
        return None, "the body's tier lines disagree (%s): one line, one tier" % ", ".join(distinct)
    if distinct:
        return distinct[0], ""
    if ambiguous:
        return None, "the body's tier line names more than one tier (%s): one tier" % "; ".join(ambiguous[:_ODD_MAX])
    if odd:
        return None, "the body's tier line names no tier (%s): one of %s" % ("; ".join(odd), ", ".join(TIERS))
    return None, ""


def _is_admin(pr, login=None):
    """Whether `login` (the author when omitted) holds admin on the repository: the owner's role, read from
    the permissions map the fetcher fills for the author and every reviewer. A login the map lacks is not
    an admin, so the stricter gate applies (fail closed)."""
    perms = pr.get("permissions") or {}
    return perms.get(pr.get("author") if login is None else login) == ADMIN


def _standing(r):
    """The state a review contributes to its reviewer's standing, dismissals read fail-closed. Undismissed:
    its state. A dismissed APPROVED: DISMISSED, whoever dismissed it (an approval that the PR page shows
    struck out never counts; ignoring a third party's dismissal would let the author spend the review's
    one dismissal first and lock the approval in). A dismissed CHANGES_REQUESTED: DISMISSED only when the
    reviewer dismissed it themselves (their own word); dismissed by anyone else (an author with write
    access) or by an unknown actor, the objection still stands."""
    if not r.get("dismissed") or r.get("state") == "APPROVED":
        return "DISMISSED" if r.get("dismissed") else r.get("state")
    return "DISMISSED" if r.get("dismissed_by") == r.get("user") else r.get("state")


def _latest_reviews(pr):
    """{reviewer: latest standing-bearing review}: the latest APPROVED / CHANGES_REQUESTED / dismissed
    review per reviewer; a COMMENTED or PENDING review is skipped, so one inline note after an approval
    (or an objection) leaves it standing. Read the review's effect through _standing."""
    latest = {}
    for r in sorted(pr.get("reviews") or [], key=lambda r: r.get("submitted_at") or 0):
        if r.get("state") in STANDING_STATES:            # `state` is the ORIGINAL state, dismissed or not
            latest[r["user"]] = r
    return latest


def _approved_by_admin(pr):
    """(True, reviewer) when an admin other than the author has a standing APPROVED review on the CURRENT
    head: the one approval any gate here asks for (the owner's look). Else (False, why), naming the nearest
    miss: an admin's approval on an older head, or an approval by a maintainer without admin, which meets
    no gate."""
    perms = pr.get("permissions") or {}
    stale = non_admin = None
    for user, r in _latest_reviews(pr).items():
        if user == pr.get("author") or _standing(r) != "APPROVED":
            continue
        if perms.get(user) != ADMIN:
            if perms.get(user) in MAINTAINER_PERMS:
                non_admin = user
            continue
        if r.get("commit_id") != pr.get("head_sha"):
            stale = user
            continue
        return True, user
    if stale:
        return False, ("%s's approval is for an older head - a push after approval needs re-approval by an admin "
                       "on the current head" % stale)
    if non_admin:
        return False, ("no approval by an admin other than the author on the current head (%s approved but does "
                       "not hold admin, and only an admin's approval meets this gate)" % non_admin)
    return False, "no approval by an admin other than the author on the current head"


def _changes_requested(pr):
    """Maintainers (write, maintain or admin) other than the author whose standing is CHANGES_REQUESTED,
    on any head: an objection holds until that reviewer says otherwise (a push does not answer it)."""
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


def evaluate(pr):
    labels = [TIER_ALIASES.get(l, l) for l in (pr.get("labels") or []) if TIER_ALIASES.get(l, l) in TIERS]
    declared, why = declared_tier(pr.get("body"))
    if len(labels) != 1:
        hint = ""
        if not labels:
            # no label yet: the body's line is how a read-only contributor sorts the PR (T273). The workflow
            # applies that label and re-grades in the same run; here, purely, the PR is still unlabeled.
            # A tier label REMOVED by someone other than the author is a ruling (a maintainer re-tiering, or
            # un-sorting it for a talk): the line is not re-applied over it, and a maintainer sets the tier
            removed = list(pr.get("tier_unlabeled_by") or [])
            if removed:
                hint = (" %s removed a tier label, so the body's line is not re-applied: a maintainer sets the tier."
                        % ", ".join(removed))
            elif declared:
                hint = " The body declares `%s`: the tier workflow applies that label and grades it." % declared
            elif why:
                hint = " " + why[0].upper() + why[1:] + "."
            else:
                hint = " Add the label, or declare the tier in the body on a line of its own: `Tier: fix`."
        return {"conclusion": "failure", "title": "Tier policy: %d tier labels" % len(labels),
                "summary": "Exactly one tier label is required (docs, fix, feature, major-feature); this PR carries %d.%s"
                           % (len(labels), hint)}
    tier = labels[0]
    v = _verdict_for(pr, tier)
    if declared and declared != tier:
        # the LABEL stands (maintainers re-tier by relabeling); a body that disagrees is said, never applied
        v["summary"] += " The body declares `%s`, but the `%s` label stands: maintainers re-tier by relabeling." % (declared, tier)
    return v


def _verdict_for(pr, tier):
    """The verdict for a PR wearing exactly one tier label: the gate by tier and by the author's role."""
    admin_author = _is_admin(pr)

    # every tier, every author: a standing objection by a maintainer other than the author holds the PR
    # until that reviewer lifts it, and an approval by someone else does not (the owner, 2026-09-08)
    objectors = _changes_requested(pr)
    if objectors:
        return {"conclusion": "failure", "title": "Tier policy: %s" % tier,
                "summary": "Changes requested by %s; a standing objection by a maintainer other than the author holds "
                           "a PR of any tier until they say otherwise." % ", ".join(objectors)}

    # the guard: a non-admin author touching the gate's own files (or whose file listing the API truncated)
    # needs an admin's approval whatever the tier, so that nobody but the owner rewrites the gate through a
    # PR the check cannot see; an admin author is exempt, the owner may change the gate
    files = list(pr.get("files") or [])
    truncated = bool(pr.get("files_truncated"))
    guarded = [f for f in files if f.startswith(GUARDED_PREFIXES)] + ([TRUNCATED] if truncated else [])
    if guarded and not admin_author:
        ok, who = _approved_by_admin(pr)
        if not ok:
            return {"conclusion": "failure", "title": "Tier policy: %s" % tier,
                    "summary": "This PR touches the gate's own files (%s), which needs an admin's approval regardless "
                               "of tier when the author is not an admin: %s." % (", ".join(guarded), who)}

    if tier in ON_GREEN:
        # docs and fix merge on green for every author: no approval is required by this check, and the one
        # hold, a standing objection, was ruled out above (the owner, 2026-09-08)
        return {"conclusion": "success", "title": "Tier policy: %s" % tier,
                "summary": "The %s tier merges on green for every author: no approval is required by this check, and "
                           "no maintainer has requested changes." % tier}

    if tier == "feature":
        # an admin author's feature merges on green (the owner's features merge straight away); anyone else's
        # needs an admin's approval on the current head (the owner looks first). No issue, no waiting period
        if admin_author:
            return {"conclusion": "success", "title": "Tier policy: feature",
                    "summary": "A feature by an admin author merges on green: no approval is required by this check, "
                               "and no maintainer has requested changes."}
        ok, who = _approved_by_admin(pr)
        if ok:
            return {"conclusion": "success", "title": "Tier policy: feature",
                    "summary": "Approved by %s, an admin, on the current head." % who}
        return {"conclusion": "failure", "title": "Tier policy: feature",
                "summary": "A feature by a non-admin author needs an admin's approval: %s." % who}

    # major-feature: for every author, a linked issue that someone other than the author has commented on
    # (the write-up and its discussion); a non-admin author additionally needs an admin's approval on the
    # current head
    discussed, why = _linked_issue_discussed(pr)
    if admin_author:
        if discussed:
            return {"conclusion": "success", "title": "Tier policy: major-feature",
                    "summary": "A major feature by an admin author merges once its linked issue is discussed: issue #%s "
                               "carries a comment by someone other than the author." % why}
        return {"conclusion": "failure", "title": "Tier policy: major-feature",
                "summary": "A major feature needs a discussed linked issue, whoever the author: %s." % why}
    ok, who = _approved_by_admin(pr)
    if ok and discussed:
        return {"conclusion": "success", "title": "Tier policy: major-feature",
                "summary": "Approved by %s, an admin, on the current head, with the discussion in issue #%s." % (who, why)}
    missing = []
    if not ok:
        missing.append("a major feature by a non-admin author needs an admin's approval: " + who)
    if not discussed:
        missing.append("a discussed linked issue is required: " + why)
    return {"conclusion": "failure", "title": "Tier policy: major-feature", "summary": "; ".join(missing) + "."}


if __name__ == "__main__":
    import json, sys
    print(json.dumps(evaluate(json.load(sys.stdin))))
