#!/usr/bin/env python3
"""The Tier policy check's FETCHER: reads a PR (or every open PR) through the GitHub REST API with the
workflow's GITHUB_TOKEN, builds the record scripts/ci/tier_policy.py evaluates, and posts the verdict as a
check run named "Tier policy" on the PR's head sha. API reads only - it never checks out or runs PR code.

Trust model, stated once: the workflow that runs this is the BASE branch's copy (pull_request_target), so
a PR cannot rewrite its own gate; the token holds checks:write (to post the verdict), pull-requests:read,
issues:read, contents:read and nothing else; the seven-day clock is the server-stamped time of the FIRST
"Tier policy" check run for the current head (commit dates are the author's to forge, check runs are
not), falling back to the PR's created_at when no run exists for that head yet. GITHUB_TOKEN is the
GitHub Actions app's installation token, which is what the Checks API's "GitHub Apps only" write rule
admits; the ruleset that requires this check must therefore select the run posted by the GitHub Actions
app. Usage: tier_policy_check.py --pr N | --all-open (env GITHUB_TOKEN, GITHUB_REPOSITORY)."""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
from tier_policy import evaluate  # noqa: E402

API = "https://api.github.com"
CHECK_NAME = "Tier policy"


def _iso(s):
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()) if s else None


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


def _get_all(path, token, key=None):
    """Every page of a list endpoint. `key` names the list inside an OBJECT-shaped response - the
    check-runs endpoint returns {"total_count", "check_runs": [...]} (the review's catch: extending
    with the dict itself produced its two key strings and crashed every run before a verdict)."""
    out, url = [], path if path.startswith("http") else API + path
    sep = "&" if "?" in url else "?"
    url += sep + "per_page=100"
    while url:
        page, hdrs = _req("GET", url, token)
        out.extend(page[key] if key else page)
        m = re.search(r'<([^>]+)>;\s*rel="next"', hdrs.get("Link", "") or "")
        url = m.group(1) if m else None
    return out


def build_record(repo, number, token, now=None):
    pr, _ = _req("GET", "/repos/%s/pulls/%d" % (repo, number), token)
    head = pr["head"]["sha"]
    author = pr["user"]["login"]
    files = [f["filename"] for f in _get_all("/repos/%s/pulls/%d/files" % (repo, number), token)]
    reviews = [{"user": r["user"]["login"], "state": r["state"], "commit_id": r.get("commit_id"),
                "submitted_at": _iso(r.get("submitted_at")), "dismissed": r["state"] == "DISMISSED"}
               for r in _get_all("/repos/%s/pulls/%d/reviews" % (repo, number), token) if r.get("user")]
    perms = {}
    for u in {r["user"] for r in reviews}:
        try:
            p, _ = _req("GET", "/repos/%s/collaborators/%s/permission" % (repo, u), token)
            perms[u] = p.get("permission")
        except urllib.error.HTTPError:
            perms[u] = "none"                     # not a collaborator: never an approver
    runs = _get_all("/repos/%s/commits/%s/check-runs?check_name=%s"
                    % (repo, head, urllib.parse.quote(CHECK_NAME)), token, key="check_runs")
    starts = [_iso(r.get("started_at")) for r in runs if r.get("started_at")]
    first_check_at = min(starts) if starts else None
    issues = {}
    for a, b in re.findall(r"(?:^|[^\w/])#(\d+)\b|github\.com/%s/issues/(\d+)\b" % re.escape(repo), pr.get("body") or ""):
        n = int(a or b)
        try:
            it, _ = _req("GET", "/repos/%s/issues/%d" % (repo, n), token)
            comments = [c["user"]["login"] for c in _get_all("/repos/%s/issues/%d/comments" % (repo, n), token)
                        if c.get("user")]
            issues[n] = {"exists": True, "is_pr": "pull_request" in it, "comments": comments}
        except urllib.error.HTTPError:
            issues[n] = {"exists": False, "is_pr": False, "comments": []}
    return {"number": number, "author": author, "labels": [l["name"] for l in pr.get("labels") or []],
            "head_sha": head, "files": files, "reviews": reviews, "permissions": perms,
            "first_check_at": first_check_at, "created_at": _iso(pr["created_at"]),
            "now": int(now or time.time()), "body": pr.get("body") or "", "issues": issues}


def post_check(repo, head, verdict, token):
    body = {"name": CHECK_NAME, "head_sha": head, "status": "completed", "conclusion": verdict["conclusion"],
            "output": {"title": verdict["title"], "summary": verdict["summary"]}}
    _req("POST", "/repos/%s/check-runs" % repo, token, body)


def main(argv):
    token = os.environ.get("GITHUB_TOKEN") or ""
    repo = os.environ.get("GITHUB_REPOSITORY") or "romp-on/romp"
    if not token:
        sys.exit("GITHUB_TOKEN is required")
    if "--all-open" in argv:
        numbers = [p["number"] for p in _get_all("/repos/%s/pulls?state=open" % repo, token)]
    else:
        numbers = [int(argv[argv.index("--pr") + 1])]
    failed = 0
    for n in numbers:
        rec = build_record(repo, n, token)
        v = evaluate(rec)
        post_check(repo, rec["head_sha"], v, token)
        print("PR #%d (%s): %s - %s" % (n, rec["head_sha"][:8], v["conclusion"], v["title"]))
        failed += v["conclusion"] != "success"
    # the job itself is green whenever it managed to POST a verdict for every PR; the verdict lives on
    # the check run "Tier policy", which is what the ruleset requires. A single-PR run exits non-zero
    # on a failing verdict so the pull_request_target run also reads red at a glance.
    return 1 if (failed and "--pr" in argv) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
