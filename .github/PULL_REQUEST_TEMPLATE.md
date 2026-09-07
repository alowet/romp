<!-- One line: what this changes and why. -->

## Tier

Apply exactly one of these labels to the PR. The "PR tier" check fails until it carries one, and fails again if it carries two; the "Tier policy" check then holds the PR until its tier's gate is met.

- [ ] `docs`: documentation only (files under `docs/` or `*.md`, never `.github/` or `scripts/`). Merges on green.
- [ ] `fix`: a bug fix, with a test that fails before it. Merges on the other maintainer's approval, or after seven days with no changes requested.
- [ ] `feature`: a self-contained new capability. Merges on the other maintainer's approval.
- [ ] `major-feature`: new functionality that changes what romp does or its contracts. Merges on the other maintainer's approval AND a discussion in a linked issue (`#N` in this body, with a comment by someone other than the author).

Any PR that touches `.github/` needs an approval regardless of tier. "Approval" means the latest review by a maintainer other than the author, on the current head, is APPROVED.

## Tests

<!-- What you ran, and which test covers the change. -->
