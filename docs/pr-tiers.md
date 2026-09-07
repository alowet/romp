# PR tiers

Every pull request to romp-on/romp carries exactly one tier label, and a required status check named **Tier policy** holds the PR until its tier's gate is met. The gate was decided by the maintainers on 2026-09-07; the rules are a pure function in `scripts/ci/tier_policy.py`, pinned by `tests/test_tier_policy.py`, and the workflow in `.github/workflows/tier-policy.yml` only fetches PR data and posts the verdict.

| Tier | What it is | Merges when |
|---|---|---|
| `docs` | Documentation only: files under `docs/` or `*.md` anywhere, never `.github/` or `scripts/` | CI is green |
| `fix` | A bug fix with a test that fails before it | The other maintainer approves, **or** seven days pass with the head unchanged and no changes requested |
| `feature` | A self-contained new capability inside romp's existing model | The other maintainer approves |
| `major-feature` | New functionality that changes what romp does or its contracts | The other maintainer approves **and** the PR body links an issue (`#N`) that someone other than the author took part in (opened, or commented on) |

**Approval** means a maintainer other than the PR author (write, maintain, or admin permission) has a standing approval on the **current** head. A reviewer's standing is their latest approval, change request, or dismissal: comment-only reviews (GitHub files one for every inline comment) never change it, and a dismissed review stands as a non-approval rather than reviving an earlier one. A push after an approval needs a fresh approval. Only two accounts can merge, and GitHub forbids approving your own PR, so in practice "approval" means the other maintainer.

**The seven-day clock** counts seven *consecutive* days with the current head visible as *this PR's* head. Every Tier policy verdict is posted hourly and bound to its PR, and the clock starts at the first verdict of the unbroken chain this PR has received on the current head (a gap longer than six hours, or no verdict yet, restarts it), or at the PR's creation raised by every force-push, reopen, and draft-to-ready event on its timeline, whichever is later. So a commit shown briefly and pushed back a week later, a reopened PR, a PR converted from draft, a new PR reusing an old head, or a second PR fast-forwarded onto a head the other maintainer had vetoed all start over. Commit dates are never read: they are the author's to set.

**Renamed and copied files** count under both their old and new path, so moving a file out of `.github/` into `docs/` is still a `.github/` change. The API lists at most 3000 files per PR; when a PR has more, the unseen files are treated as guarded and not documentation, so it needs an approval and cannot be `docs`.

**Any PR that touches `.github/` or `scripts/ci/`** — the gate's own workflow and code — needs an approval regardless of its tier. The check runs from the base branch's copy of the workflow, so a PR cannot rewrite its own gate; but a PR that edits `.github/` could add a job that posts a same-named success from its own copy on `pull_request` events, and no automation can stop that. The rule closes the gap with a human look.

Approvals reach the check through an hourly schedule (or a manual re-run of the workflow), because the review event runs in the PR's own context and is not trusted to drive the gate.

**For the maintainers configuring the ruleset**: require the `Tier policy` check **with the GitHub Actions app selected as its source**, not "any source" — a bare name match would accept a same-named commit status set by anyone with write permission. The `.github/` and `scripts/ci/` approval rule lives inside the check itself; the stronger backstop is a `CODEOWNERS` entry for those paths with code-owner review required in the ruleset, which needs the maintainers' handles and is therefore theirs to add.
