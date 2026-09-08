#!/usr/bin/env python3
"""The Tier policy check's FETCHER: reads a PR (or every open PR) through the GitHub REST API with the
workflow's GITHUB_TOKEN, builds the record scripts/ci/tier_policy.py evaluates, and posts the verdict as a
check run named "Tier policy" on the PR's head sha. API reads only - it never checks out or runs PR code.

Trust model, stated once: the workflow that runs this is the BASE branch's copy (pull_request_target), so
a PR cannot rewrite its own gate; the token holds checks:write (to post the verdict), pull-requests:write
(to apply the tier the body declares as a label, T273), actions:write (to re-run the label counter on
that head), issues:read, contents:read and nothing else. The PR body is DATA read through the API, never
executed. Nothing in the policy is timed (the owner's rules of
2026-09-08: the gate depends on the tier and on the author's role, and no tier has a time-based path), so
this fetcher reads no check-run history, no timeline and no commit date; the record it builds carries no
time field at all. The collaborator permission is fetched for the AUTHOR as well as for every reviewer: the
policy reads the author's role from the same map (admin is the repository owner; a non-collaborator's 404
reads as "none", a contributor).
A dismissed review's original state and its dismisser come from the issue events API's review_dismissed
event (actor + dismissed_review.{review_id,state}; the reviews API itself only says DISMISSED); a dismissed
review with no such event raises.
The workflow's own job carries a DIFFERENT name so exactly one family of same-named runs exists. A renamed
or copied file is recorded under both its paths, and a listing the API truncated (3000-file cap, checked
against the PR's changed_files) is flagged; the head is re-read at the end so a push during evaluation
raises instead of grading a mixed record. Commit dates are never read.
GITHUB_TOKEN is the GitHub Actions app's installation token, which is what the Checks API's "GitHub Apps
only" write rule admits; the ruleset requiring this check must select the run posted by the GitHub Actions
app (a bare context match would accept any write-holder's commit status of the same name).
The body's tier line (T273, the owner 2026-09-08): outside contributors hold read permission and cannot
label their own PRs, so `Tier: fix` in the body is how they sort one. When a PR carries NO tier label and
its body declares one, the label is applied through the API before the verdict, and the same run grades
the tier it applied; a label already on the PR always stands (maintainers re-tier by relabeling), and a
body that disagrees is only mentioned in the summary. A label added with the workflow's own token starts
no workflow run (GitHub: events the GITHUB_TOKEN causes create none, save dispatches), so the "Exactly one
tier label" run on the head would keep the count it read before the label: its newest completed run is
re-run through the Actions API. The hourly --all-open pass does the same for every open PR, so a PR whose
author adds the line reaches both green checks without a further push.
Usage: tier_policy_check.py --pr N | --all-open (env GITHUB_TOKEN, GITHUB_REPOSITORY)."""
import json
import os
import re
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
from tier_policy import evaluate, declared_tier, TIERS, TIER_ALIASES  # noqa: E402

API = "https://api.github.com"
CHECK_NAME = "Tier policy"
LABEL_COUNTER_WORKFLOW = "pr-tier.yml"   # the read-only "Exactly one tier label" check, re-run after a label write
MAX_ISSUE_REFS = 5                 # a body can be 64 KiB of "#1 " - bound the work (and the token budget)


def _iso(s):
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()) if s else None


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _req(method, path, token, body=None):
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "romp-tier-policy"})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read().decode()
        return (json.loads(txt) if txt else None), r.headers


def _get_all(path, token):
    """Every page of a list endpoint, following the Link header."""
    out, url = [], path if path.startswith("http") else API + path
    sep = "&" if "?" in url else "?"
    url += sep + "per_page=100"
    while url:
        page, hdrs = _req("GET", url, token)
        out.extend(page)
        m = re.search(r'<([^>]+)>;\s*rel="next"', hdrs.get("Link", "") or "")
        url = m.group(1) if m else None
    return out


def _is_bot(user):
    return not user or user.get("type") == "Bot" or str(user.get("login", "")).endswith("[bot]")


def _permission(repo, login, token):
    """The collaborator permission, "none" for a NON-collaborator (404). Any other error raises: a 403,
    429 or 5xx silently mapped to "none" would deny every approval while posting a normal-looking verdict
    (the review's catch) - fail loudly instead, leaving no verdict for this run."""
    try:
        p, _ = _req("GET", "/repos/%s/collaborators/%s/permission" % (repo, urllib.parse.quote(login)), token)
        return p.get("permission")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "none"
        raise


def build_record(repo, number, token):
    pr, _ = _req("GET", "/repos/%s/pulls/%d" % (repo, number), token)
    head = pr["head"]["sha"]
    author = pr["user"]["login"]
    entries = _get_all("/repos/%s/pulls/%d/files" % (repo, number), token)
    files = []
    for f in entries:
        for p in (f.get("filename"), f.get("previous_filename")):     # renamed/copied: judge the source too
            if p and p not in files:
                files.append(p)
    changed = pr.get("changed_files")
    files_truncated = changed is not None and changed != len(entries)
    dismissals = {}                    # review id -> (who dismissed it, the review's ORIGINAL state)
    for e in _get_all("/repos/%s/issues/%d/events" % (repo, number), token):
        if e.get("event") == "review_dismissed":
            d = e.get("dismissed_review") or {}
            dismissals[d.get("review_id")] = ((e.get("actor") or {}).get("login"), str(d.get("state") or "").upper())
    reviews = []
    for r in _get_all("/repos/%s/pulls/%d/reviews" % (repo, number), token):
        if not r.get("user"):
            continue
        rec = {"user": r["user"]["login"], "state": r["state"], "commit_id": r.get("commit_id"),
               "submitted_at": _iso(r.get("submitted_at")), "dismissed": r["state"] == "DISMISSED", "dismissed_by": None}
        if rec["dismissed"]:
            if r.get("id") not in dismissals:
                raise RuntimeError("review %s by %s is DISMISSED but no review_dismissed event says who dismissed it"
                                   % (r.get("id"), rec["user"]))
            rec["dismissed_by"], rec["state"] = dismissals[r["id"]]
        reviews.append(rec)
    # every reviewer AND the author: the policy reads the author's role (admin = the owner) from this map
    perms = {u: _permission(repo, u, token) for u in {r["user"] for r in reviews} | {author}}
    issues = {}
    seen = []
    for a, b in re.findall(r"(?:^|[^\w/])#(\d+)\b|github\.com/%s/issues/(\d+)\b" % re.escape(repo), pr.get("body") or ""):
        n = int(a or b)
        if n in seen:
            continue
        seen.append(n)
        if len(seen) > MAX_ISSUE_REFS:
            break
        try:
            it, _ = _req("GET", "/repos/%s/issues/%d" % (repo, n), token)
            comments = [c["user"]["login"] for c in _get_all("/repos/%s/issues/%d/comments" % (repo, n), token)
                        if not _is_bot(c.get("user"))]
            issues[n] = {"exists": True, "is_pr": "pull_request" in it, "comments": comments}
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            issues[n] = {"exists": False, "is_pr": False, "comments": []}
    again, _ = _req("GET", "/repos/%s/pulls/%d" % (repo, number), token)
    if again["head"]["sha"] != head:
        raise RuntimeError("the PR's head moved during evaluation (%s -> %s); the push's own run grades the new head"
                           % (head[:8], again["head"]["sha"][:8]))
    return {"number": number, "author": author, "labels": [l["name"] for l in pr.get("labels") or []],
            "head_sha": head, "files": files, "files_truncated": files_truncated, "reviews": reviews,
            "permissions": perms, "body": pr.get("body") or "", "issues": issues}


def post_check(repo, head, verdict, token, number):
    body = {"name": CHECK_NAME, "head_sha": head, "status": "completed", "conclusion": verdict["conclusion"],
            "external_id": str(number),    # names the PR this verdict is for (one sha can head several PRs)
            "started_at": _utc_now(),      # completed_at is left for the server to stamp
            "output": {"title": verdict["title"], "summary": verdict["summary"]}}
    _req("POST", "/repos/%s/check-runs" % repo, token, body)


def apply_declared_tier(repo, number, rec, token):
    """The body's declared tier becomes the label when the PR carries NO tier label (T273): one label write
    through the API, the record learns it, and the note returned rides the verdict's summary. A tier label
    already present stands whatever the body says (evaluate mentions the disagreement); a body declaring
    nothing, or two tiers, applies nothing (evaluate says why). A refused write raises: grading the PR as
    unlabeled with a normal-looking verdict would hide the missing permission (the T121 rule, fail loudly)."""
    if any(TIER_ALIASES.get(l, l) in TIERS for l in rec.get("labels") or []):
        return ""
    tier, _ = declared_tier(rec.get("body"))
    if not tier:
        return ""
    _req("POST", "/repos/%s/issues/%d/labels" % (repo, number), token, {"labels": [tier]})
    rec["labels"] = list(rec.get("labels") or []) + [tier]
    return "The `%s` label was applied from the body's tier line.%s" % (tier, _refresh_label_counter(repo, rec["head_sha"], token))


def _refresh_label_counter(repo, head, token):
    """A label added with the workflow's own token starts no workflow run, so the "Exactly one tier label"
    run on this head still shows the count it read before the label. Re-run its newest run on the head when
    that run is completed; a queued run has not counted yet and reads the label itself; one in progress may
    have counted already and cannot be re-run, so the summary says so instead of guessing; no run on the
    head (the counter never fired for it) is nothing to refresh. Returns the sentence for the summary."""
    runs, _ = _req("GET", "/repos/%s/actions/workflows/%s/runs?head_sha=%s&per_page=5"
                   % (repo, LABEL_COUNTER_WORKFLOW, urllib.parse.quote(head)), token)
    runs = (runs or {}).get("workflow_runs") or []
    if not runs:
        return ""
    run = runs[0]                       # the API lists runs newest first
    if run.get("status") == "completed":
        _req("POST", "/repos/%s/actions/runs/%d/rerun" % (repo, int(run["id"])), token)
        return ' The "Exactly one tier label" run on this head was re-run to count it.'
    if run.get("status") == "in_progress":
        return ' The "Exactly one tier label" run on this head was mid-count; if it stays red, push or edit once more.'
    return ""                           # queued: it reads the labels when it starts


def run_one(repo, n, token):
    """Evaluate one PR and post its verdict. A failure while BUILDING the record (or applying the body's
    declared tier) posts a failing verdict naming the error when the head is known (never a silent gap on
    a required check), and re-raises so the job reads red; in --all-open the caller isolates it so one PR
    cannot starve the others."""
    head = None
    try:
        pr, _ = _req("GET", "/repos/%s/pulls/%d" % (repo, n), token)
        head = pr["head"]["sha"]
        rec = build_record(repo, n, token)
        note = apply_declared_tier(repo, n, rec, token)
        v = evaluate(rec)
        if note:
            v["summary"] += " " + note
    except Exception as e:
        if head:
            post_check(repo, head, {"conclusion": "failure", "title": "Tier policy: evaluation failed",
                                    "summary": "The policy could not be evaluated for this head: %r. A maintainer "
                                               "can re-run the workflow; the verdict is not a ruling on the tier." % (e,)},
                       token, n)
        raise
    post_check(repo, head, v, token, n)
    print("PR #%d (%s): %s - %s" % (n, head[:8], v["conclusion"], v["title"]))
    return v


def main(argv):
    token = os.environ.get("GITHUB_TOKEN") or ""
    repo = os.environ.get("GITHUB_REPOSITORY") or "romp-on/romp"
    if not token:
        sys.exit("GITHUB_TOKEN is required")
    if "--all-open" in argv:
        rc = 0
        for p in _get_all("/repos/%s/pulls?state=open" % repo, token):
            try:
                run_one(repo, p["number"], token)
            except Exception:
                sys.stderr.write("PR #%s: %s\n" % (p["number"], traceback.format_exc().strip().splitlines()[-1]))
                rc = 1
        return rc
    v = run_one(repo, int(argv[argv.index("--pr") + 1]), token)
    return 1 if v["conclusion"] != "success" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
