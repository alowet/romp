<!-- One line: what this changes and why. -->

## Tier

Apply exactly one of these labels to the PR. The "Exactly one tier label" check fails until it carries one, and fails again if it carries two; the "Tier policy" check then holds the PR until its tier's gate is met.

- [ ] `docs`: documentation only (files under `docs/` or `*.md`, never `.github/` or `scripts/`). Merges on green.
- [ ] `fix`: a bug fix, with a test that fails before it. Merges on the other maintainer's approval, or after seven days with no changes requested.
- [ ] `feature`: a self-contained new capability. Merges on the other maintainer's approval.
- [ ] `major-feature`: new functionality that changes what romp does or its contracts. Merges on the other maintainer's approval AND a discussion in a linked issue (`#N` in this body, with a comment by someone other than the author; the opener alone does not count).

Any PR that touches `.github/` or `scripts/ci/` needs an approval regardless of tier. "Approval" means a maintainer other than the author has a standing APPROVED review on the current head (comment-only reviews never change standing; a dismissed approval never counts, and a dismissed change request clears only when its reviewer dismissed it themselves).

## Tests

<!-- What you ran, and which test covers the change. -->
