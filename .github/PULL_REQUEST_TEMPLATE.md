<!-- One line: what this changes and why. -->

## Tier

Tier: <one of docs, fix, feature, major-feature>

<!-- Replace the placeholder above with ONE tier word and leave the line on its own. The "Tier policy"
workflow turns it into the PR's label (labeling needs triage permission, which outside contributors do
not hold); `gh pr create --label <tier>` still works for those who can. A label already on the PR wins:
maintainers re-tier by relabeling, and once a maintainer has removed a tier label the line is not applied
again. Two lines naming different tiers declare nothing. The tiers:
  `docs`           documentation. To the check it is the same tier as `fix`: merges on green for every author.
  `fix`            a bug fix, with a test that fails before it. Merges on green for every author.
  `feature`        a self-contained new capability. By the repository owner (an admin): merges on green. By a
                   member (write access) or a contributor: merges on the owner's approval on the current head.
  `major-feature`  new functionality that changes what romp does or its contracts. For every author: a
                   discussion in a linked issue (`#N` in this body, with a comment by someone other than the
                   author; the opener alone does not count). A member's or a contributor's additionally needs
                   the owner's approval on the current head.
The "Exactly one tier label" check fails until the PR carries one tier label, and fails again if it carries
two; the "Tier policy" check then holds the PR until its tier's gate is met. -->

A standing change request by a maintainer other than the author holds a PR of any tier until that reviewer lifts it. Any PR that touches `.github/` or `scripts/ci/` needs the owner's approval regardless of tier unless the author is an admin. "Approval" means an admin other than the author has a standing APPROVED review on the current head (comment-only reviews never change standing; a dismissed approval never counts, and a dismissed change request clears only when its reviewer dismissed it themselves).

## Tests

<!-- What you ran, and which test covers the change. -->
