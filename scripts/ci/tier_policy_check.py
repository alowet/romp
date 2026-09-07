#!/usr/bin/env python3
"""The Tier policy check's FETCHER: reads a PR (or every open PR) through the GitHub REST API with the
workflow's GITHUB_TOKEN, builds the record scripts/ci/tier_policy.py evaluates, and posts the verdict as a
check run named "Tier policy" on the PR's head sha. API reads only - it never checks out or runs PR code.

Trust model, stated once: the workflow that runs this is the BASE branch's copy (pull_request_target), so
a PR cannot rewrite its own gate; the token holds checks:write (to post the verdict), pull-requests:read,
issues:read, contents:read and nothing else. The seven-day clock is bound to THIS PR's head: head_floor is
the later of the PR's created_at and every server-stamped force-push / reopen / ready-for-review event on
its timeline, and first_check_at is the earliest "Tier policy" check run for the head (listed with
filter=all - the default `latest` collapses the hourly runs to the newest). Commit dates are never read.
GITHUB_TOKEN is the GitHub Actions app's installation token, which is what the Checks API's "GitHub Apps
only" write rule admits; the ruleset requiring this check must select the run posted by the GitHub Actions
app (a bare context match would accept any write-holder's commit status of the same name).
Usage: tier_policy_check.py --pr N | --all-open (env GITHUB_TOKEN, GITHUB_REPOSITORY)."""
import json
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
from tier_policy import evaluate  # noqa: E402

API = "https://api.github.com"
CHECK_NAME = "Tier policy"
MAX_ISSUE_REFS = 5                 # a body can be 64 KiB of "#1 " - bound the work (and the token budget)
RESET_EVENTS = ("head_ref_force_pushed", "reopened", "ready_for_review")


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
    check-runs endpoint returns {"total_count", "check_runs": [...]}."""
    out, url = [], path if path.startswith("http") else API + path
    sep = "&" if "?" in url else "?"
    url += sep + "per_page=100"
    while url:
        page, hdrs = _req("GET", url, token)
        out.extend(page[key] if key else page)
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


def build_record(repo, number, token, now=None):
    pr, _ = _req("GET", "/repos/%s/pulls/%d" % (repo, number), token)
    head = pr["head"]["sha"]
    author = pr["user"]["login"]
    files = [f["filename"] for f in _get_all("/repos/%s/pulls/%d/files" % (repo, number), token)]
    reviews = [{"user": r["user"]["login"], "state": r["state"], "commit_id": r.get("commit_id"),
                "submitted_at": _iso(r.get("submitted_at")), "dismissed": r["state"] == "DISMISSED"}
               for r in _get_all("/repos/%s/pulls/%d/reviews" % (repo, number), token) if r.get("user")]
    perms = {u: _permission(repo, u, token) for u in {r["user"] for r in reviews}}
    runs = _get_all("/repos/%s/commits/%s/check-runs?check_name=%s&filter=all"
                    % (repo, head, urllib.parse.quote(CHECK_NAME)), token, key="check_runs")
    starts = [_iso(r.get("started_at")) for r in runs if r.get("started_at")]
    first_check_at = min(starts) if starts else None
    created_at = _iso(pr["created_at"])
    resets = [_iso(e.get("created_at")) for e in _get_all("/repos/%s/issues/%d/timeline" % (repo, number), token)
              if e.get("event") in RESET_EVENTS and e.get("created_at")]
    head_floor = max([created_at] + resets)
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
            opener = None if _is_bot(it.get("user")) else it["user"]["login"]
            issues[n] = {"exists": True, "is_pr": "pull_request" in it, "user": opener, "comments": comments}
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            issues[n] = {"exists": False, "is_pr": False, "user": None, "comments": []}
    return {"number": number, "author": author, "labels": [l["name"] for l in pr.get("labels") or []],
            "head_sha": head, "files": files, "reviews": reviews, "permissions": perms,
            "first_check_at": first_check_at, "head_floor": head_floor, "created_at": created_at,
            "now": int(now or time.time()), "body": pr.get("body") or "", "issues": issues}


def post_check(repo, head, verdict, token):
    body = {"name": CHECK_NAME, "head_sha": head, "status": "completed", "conclusion": verdict["conclusion"],
            "output": {"title": verdict["title"], "summary": verdict["summary"]}}
    _req("POST", "/repos/%s/check-runs" % repo, token, body)


def run_one(repo, n, token):
    """Evaluate one PR and post its verdict. A failure while BUILDING the record posts a failing verdict
    naming the error when the head is known (never a silent gap on a required check), and re-raises so
    the job reads red; in --all-open the caller isolates it so one PR cannot starve the others."""
    head = None
    try:
        pr, _ = _req("GET", "/repos/%s/pulls/%d" % (repo, n), token)
        head = pr["head"]["sha"]
        rec = build_record(repo, n, token)
        v = evaluate(rec)
    except Exception as e:
        if head:
            post_check(repo, head, {"conclusion": "failure", "title": "Tier policy: evaluation failed",
                                    "summary": "The policy could not be evaluated for this head: %r. A maintainer "
                                               "can re-run the workflow; the verdict is not a ruling on the tier." % (e,)},
                       token)
        raise
    post_check(repo, head, v, token)
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
