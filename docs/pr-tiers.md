# PR tiers

Every pull request to romp-on/romp carries exactly one tier label, and a required status check named **Tier policy** holds the PR until its tier's gate is met. The gate was decided by the maintainers on 2026-09-07; the rules are a pure function in `scripts/ci/tier_policy.py`, pinned by `tests/test_tier_policy.py`, and the workflow in `.github/workflows/tier-policy.yml` only fetches PR data and posts the verdict.

| Tier | What it is | Merges when |
|---|---|---|
| `docs` | Documentation only: files under `docs/` or `*.md` anywhere, never `.github/` or `scripts/` | CI is green |
| `fix` | A bug fix with a test that fails before it | The other maintainer approves, **or** seven days pass with the head unchanged and no changes requested |
| `feature` | A self-contained new capability inside romp's existing model | The other maintainer approves |
| `major-feature` | New functionality that changes what romp does or its contracts | The other maintainer approves **and** the PR body links an issue (`#N`) that someone other than the author has commented on |

**Approval** means the latest review by a maintainer other than the PR author (write, maintain, or admin permission), on the **current** head, is APPROVED. A push after an approval needs a fresh approval; dismissed reviews never count. Only two accounts can merge, and GitHub forbids approving your own PR, so in practice "approval" means the other maintainer.

**The seven-day clock** starts at the server-stamped time of the first Tier policy run for the current head (the run that fires when the head is pushed), falling back to the PR's creation time when no run exists yet. Commit dates are never read: they are the author's to set.

**Any PR that touches `.github/`** needs an approval regardless of its tier. The check runs from the base branch's copy of the workflow, so a PR cannot rewrite its own gate; but a PR that edits `.github/` could add a job that posts a same-named success from its own copy on `pull_request` events, and no automation can stop that. The rule closes the gap with a human look.

Approvals reach the check through an hourly schedule (or a manual re-run of the workflow), because the review event runs in the PR's own context and is not trusted to drive the gate.
