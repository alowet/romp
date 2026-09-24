#!/usr/bin/env bats

# scripts/release.sh — the release gate. What it exists to enforce:
#   * VERSION is the ONE source of truth and the tag is DERIVED from it, so the two can
#     never disagree — the script takes no tag argument at all (2026-07-29);
#   * the tag is therefore always v-prefixed (bootstrap.sh's `git tag -l 'v*'` selector
#     matches nothing otherwise, and the installer silently falls back to main);
#   * the macOS CI run — dispatch-only, since macOS is billed even on public repos — must
#     be GREEN before a version is tagged.
# The GitHub CLI is stubbed via ROMP_GH so none of this touches real CI, and most tests run
# with --skip-tests: the fixture repo has no suites of its own.

ROMP_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"

load git-hermetic

setup() {
    git_hermetic
    TEST_DIR="$(mktemp -d)"
    REPO="$TEST_DIR/repo"
    mkdir -p "$REPO/scripts"
    cp "$ROMP_DIR/scripts/release.sh" "$REPO/scripts/"
    git init -q "$REPO"
    # `git init -b main` needs git 2.28+; setting HEAD before the first commit works on every
    # version, which matters because this suite also runs on the CI's older shells.
    git -C "$REPO" symbolic-ref HEAD refs/heads/main
    git -C "$REPO" config user.email t@e.invalid
    git -C "$REPO" config user.name t
    echo "0.1.0" > "$REPO/VERSION"
    git -C "$REPO" add -A
    git -C "$REPO" commit -qm init
    # A real origin, because the script now pushes the tag and (on a bump) the branch. A
    # bare repo is enough and keeps every test on the same footing as a real clone.
    git init -q --bare "$TEST_DIR/origin.git"
    git -C "$REPO" remote add origin "$TEST_DIR/origin.git"
    git -C "$REPO" push -q origin main
    export REPO_FOR_STUB="$REPO"
    export ROMP_RELEASE_POLL=0          # no sleeping in tests
    export GH_LOG="$TEST_DIR/gh.log"
}
teardown() { rm -rf "$TEST_DIR"; }

# STUB_CONCLUSION = what the stubbed `gh run view` reports (default success).
# STUB_FLAKY_VIEWS = report nothing for the first N `run view` calls, as a transient API
# error looks to the poll loop, then the real conclusion.
# STUB_PR_STATE = what `gh pr view` reports (default MERGED).
# STUB_MERGE_REMOTE = the remote the simulated merge lands on (default origin; a fork layout
# names its canonical remote `upstream`).
_stub_gh() {
    cat > "$TEST_DIR/gh" <<STUB
#!/usr/bin/env bash
TEST_DIR="$TEST_DIR"
echo "\$@" >> "$GH_LOG"
case "\$1 \$2" in
  # a NEW run id appears only after a dispatch, as the real API behaves
  "run list")   if [ -f "$TEST_DIR/dispatched" ]; then echo 1000; else echo 999; fi ;;
  "workflow run") touch "$TEST_DIR/dispatched"; exit 0 ;;
  "run view")
      n=\$(( \$(cat "$TEST_DIR/views" 2>/dev/null || echo 0) + 1 )); echo "\$n" > "$TEST_DIR/views"
      if [ "\$n" -le "\${STUB_FLAKY_VIEWS:-0}" ]; then exit 1; fi
      echo "\${STUB_CONCLUSION:-success}" ;;
  # Auto-merge really lands the branch on origin/main, so the script's post-merge
  # fast-forward has something to pull and VERSION genuinely changes on main. Simulating
  # the merge as a no-op would let the bump path "pass" while proving nothing.
  # \`gh pr create\` prints the PR URL; the script reads the NUMBER off its tail and addresses
  # every later call by that number (a fork-headed branch is unresolvable by name — see below).
  # STUB_RELEASE_422 = refuse the first N \`release create\` calls the way GitHub refuses a body over
  # its ceiling (HTTP 422 "body is too long"), then accept; the script's short-body fallback rides it.
  "release create")
      n=\$(( \$(cat "$TEST_DIR/creates" 2>/dev/null || echo 0) + 1 )); echo "\$n" > "$TEST_DIR/creates"
      if [ "\$n" -le "\${STUB_RELEASE_422:-0}" ]; then
          echo "HTTP 422: Validation Failed (https://api.github.com/repos/romp-on/romp/releases)" >&2
          echo "body is too long (maximum is 125000 characters)" >&2
          exit 1
      fi ;;
  "pr create")  echo "https://github.com/romp-on/romp/pull/4242" ;;
  "pr merge")   if [ "\${STUB_PR_STATE:-MERGED}" = "MERGED" ]; then
                    git -C "$REPO" push -q "\${STUB_MERGE_REMOTE:-origin}" HEAD:main
                fi ;;
  "pr view")    echo "\${STUB_PR_STATE:-MERGED}" ;;
esac
exit 0
STUB
    chmod +x "$TEST_DIR/gh"
    export ROMP_GH="$TEST_DIR/gh"
}

# ── the source-of-truth contract ──────────────────────────────────────

@test "release: with no argument it releases whatever VERSION says" {
    _stub_gh
    run "$REPO/scripts/release.sh" --skip-tests
    [ "$status" -eq 0 ]
    run git -C "$REPO" tag -l
    [ "$output" = "v0.1.0" ]
}

@test "release: refuses a v-prefixed argument and names the version to pass instead" {
    # the tag is derived, so accepting one would re-open the mismatch this design closed
    _stub_gh
    run "$REPO/scripts/release.sh" v0.1.0
    [ "$status" -ne 0 ]
    [[ "$output" == *"WITHOUT the leading v"* ]]
    [[ "$output" == *"'0.1.0'"* ]]
    [ ! -s "$GH_LOG" ]
}

@test "release: the derived tag is always v-prefixed" {
    _stub_gh
    echo "1.2.3" > "$REPO/VERSION"
    git -C "$REPO" commit -qam ver
    run "$REPO/scripts/release.sh" --skip-tests
    [ "$status" -eq 0 ]
    run git -C "$REPO" tag -l
    [ "$output" = "v1.2.3" ]
}

@test "release: a bump level computes the next version and PRs it" {
    _stub_gh
    run "$REPO/scripts/release.sh" minor --skip-tests
    [ "$status" -eq 0 ]
    [[ "$output" == *"0.1.0 → 0.2.0"* ]]
    grep -q "pr create" "$GH_LOG"
    grep -q "pr merge" "$GH_LOG"
    # The version PR carries its tier label at creation: a required upstream check holds an
    # unlabeled PR red. The label is `docs`, tier 0 as the repository names it (docs and fix are one
    # tier that merges on green; the pre-rename spelling `tests-only` exists only as a body alias, and
    # `gh` resolves the label name on the server, so naming a label the repository lacks fails the
    # cut one step after the version branch is pushed, as v0.16.0's first cut did on 2026-09-16).
    grep -q "pr create .*--label docs" "$GH_LOG"
    # And the body says the tier too, the road a contributor who cannot label uses, so the tier
    # workflow can re-apply the label should its name move again.
    grep -q "Tier: docs" "$GH_LOG"
    # BY NUMBER, never by branch name (the user 2026-08-01): every PR here is fork-headed, because
    # rulesets block branch pushes upstream — and `gh pr merge <branch> --repo <upstream>` cannot
    # resolve a branch that lives on the fork. It failed with "no pull requests found for branch
    # release-0.3.0" one step after opening the PR, leaving VERSION merged but UNTAGGED: the exact
    # half-finished release this script exists to prevent.
    grep -q "pr merge 4242 " "$GH_LOG"
    grep -q "pr view 4242 " "$GH_LOG"
    # `run` + status, NOT a bare `! grep`: `!` is exempt from set -e, so mid-test it asserts nothing.
    run grep -qE "pr (merge|view) release-" "$GH_LOG"
    [ "$status" -ne 0 ]
    run git -C "$REPO" tag -l
    [ "$output" = "v0.2.0" ]
}

@test "release: patch and major bump the right component" {
    _stub_gh
    echo "1.4.7" > "$REPO/VERSION"
    git -C "$REPO" commit -qam ver
    run "$REPO/scripts/release.sh" patch --skip-tests --dry-run
    [[ "$output" == *"1.4.7 → 1.4.8"* ]]
    run "$REPO/scripts/release.sh" major --skip-tests --dry-run
    [[ "$output" == *"1.4.7 → 2.0.0"* ]]
}

@test "release: an explicit number is taken as the target" {
    _stub_gh
    run "$REPO/scripts/release.sh" 3.0.0 --skip-tests --dry-run
    [ "$status" -eq 0 ]
    [[ "$output" == *"releasing v3.0.0"* ]]
}

@test "release: refuses a target that is not semver" {
    _stub_gh
    run "$REPO/scripts/release.sh" not-a-version --skip-tests
    [ "$status" -ne 0 ]
    [[ "$output" == *"is not semver"* ]]
}

@test "release: VERSION already at the target needs no bump PR" {
    # the resumable case: a bump PR landed earlier, so only the tagging half remains
    _stub_gh
    run "$REPO/scripts/release.sh" 0.1.0 --skip-tests
    [ "$status" -eq 0 ]
    [[ "$output" == *"no bump PR needed"* ]]
    run grep -q "pr create" "$GH_LOG"
    [ "$status" -ne 0 ]
    run git -C "$REPO" tag -l
    [ "$output" = "v0.1.0" ]
}

@test "release: a version PR that never merges does NOT tag" {
    _stub_gh
    STUB_PR_STATE=OPEN run "$REPO/scripts/release.sh" minor --skip-tests
    [ "$status" -ne 0 ]
    [[ "$output" == *"did not merge"* ]]
    # it dies on the release branch, so it says how to converge: local main is behind the merge
    [[ "$output" == *"switch to main and pull"* ]]
    run git -C "$REPO" tag -l
    [ -z "$output" ]
}

@test "release: a version PR closed unmerged does NOT tag" {
    _stub_gh
    STUB_PR_STATE=CLOSED run "$REPO/scripts/release.sh" minor --skip-tests
    [ "$status" -ne 0 ]
    [[ "$output" == *"closed without merging"* ]]
    run git -C "$REPO" tag -l
    [ -z "$output" ]
}

@test "release: a re-run while the version PR is still open refuses — it never tags the release branch" {
    # A bump run whose PR has not landed when the wait runs out dies still checked out on the
    # release branch, where VERSION already reads the target. The script advertises re-running to
    # resume; unchecked, that re-run saw VERSION at the target, skipped the bump, and tagged HEAD —
    # the release branch — then pushed the tag, so bootstrap.sh installed a commit that is not on
    # main while main's VERSION lagged. The re-run must refuse, by name, and before spending CI.
    _stub_gh
    STUB_PR_STATE=OPEN run "$REPO/scripts/release.sh" minor --skip-tests
    [ "$status" -ne 0 ]
    [ "$(git -C "$REPO" rev-parse --abbrev-ref HEAD)" = "release-0.2.0" ]
    run "$REPO/scripts/release.sh" --skip-tests
    [ "$status" -ne 0 ]
    [[ "$output" == *"on branch release-0.2.0, not main"* ]]
    [[ "$output" == *"switch to main and pull"* ]]     # the same way forward as the run that left it here
    run git -C "$REPO" tag -l
    [ -z "$output" ]
    run git -C "$TEST_DIR/origin.git" tag -l
    [ -z "$output" ]
    run grep -q "workflow run" "$GH_LOG"      # refused before any CI was dispatched
    [ "$status" -ne 0 ]
}

@test "release: a release branch that already exists refuses before VERSION is touched — main stays clean" {
    # The bump used to write VERSION first and branch second, so a branch that already existed
    # died with a modified VERSION sitting on main, which then failed the next run's dirty-tree
    # check for no reason the user had caused.
    _stub_gh
    git -C "$REPO" branch release-0.2.0
    run "$REPO/scripts/release.sh" minor --skip-tests
    [ "$status" -ne 0 ]
    [[ "$output" == *"could not create branch release-0.2.0"* ]]
    [ "$(git -C "$REPO" rev-parse --abbrev-ref HEAD)" = "main" ]
    [ -z "$(git -C "$REPO" status --porcelain)" ]
    [ "$(cat "$REPO/VERSION")" = "0.1.0" ]
}

@test "release: a detached HEAD refuses by that name — there is no branch to blame" {
    # `git rev-parse --abbrev-ref HEAD` prints the word HEAD when detached, which would have made the
    # refusal name a branch that cannot exist and offer the open-PR diagnosis that does not fit.
    _stub_gh
    git -C "$REPO" switch -q --detach main
    run "$REPO/scripts/release.sh" --skip-tests
    [ "$status" -ne 0 ]
    [[ "$output" == *"detached HEAD, not on main"* ]]
    run git -C "$REPO" tag -l
    [ -z "$output" ]
}

# ── the macOS gate ────────────────────────────────────────────────────

@test "release: refuses when the macOS run fails, and does NOT tag" {
    _stub_gh
    STUB_CONCLUSION=failure run "$REPO/scripts/release.sh" --skip-tests
    [ "$status" -ne 0 ]
    [[ "$output" == *"macOS run did not pass"* ]]
    run git -C "$REPO" tag -l
    [ -z "$output" ]
}

@test "release: a transient API error while watching does not fail the gate" {
    # `gh run watch` treated a dropped connection as a failed RUN and refused a green
    # release twice (2026-07-27); the poll must ride out empty answers.
    _stub_gh
    ROMP_RELEASE_POLL=0.01 STUB_FLAKY_VIEWS=3 run "$REPO/scripts/release.sh" --skip-tests
    [ "$status" -eq 0 ]
    [[ "$output" == *"macOS run green"* ]]
    run git -C "$REPO" tag -l
    [ "$output" = "v0.1.0" ]
}

@test "release: tags when the macOS run is green" {
    _stub_gh
    run "$REPO/scripts/release.sh" --skip-tests
    [ "$status" -eq 0 ]
    [[ "$output" == *"macOS run green"* ]]
    run git -C "$REPO" tag -l
    [ "$output" = "v0.1.0" ]
    grep -q "workflow run CI" "$GH_LOG"      # it really did dispatch
}

@test "release: --skip-macos tags without CI, but says so loudly" {
    _stub_gh
    run "$REPO/scripts/release.sh" --skip-macos --skip-tests
    [ "$status" -eq 0 ]
    [[ "$output" == *"SKIPPING the macOS check"* ]]
    run grep -q "workflow run CI" "$GH_LOG"   # no CI was dispatched
    [ "$status" -ne 0 ]
    run git -C "$REPO" tag -l
    [ "$output" = "v0.1.0" ]
}

# ── publishing ────────────────────────────────────────────────────────

@test "release: a generated-notes body GitHub refuses falls back to a short body, never a tag without a release" {
    # v0.16.0 (2026-09-16): about nine hundred pull requests in the range, GitHub's generated notes
    # ran past its 125000-character ceiling (HTTP 422), the tag was pushed and the release was not created.
    git -C "$REPO" tag v0.0.9                          # a previous release, so the notes have a range
    _stub_gh
    STUB_RELEASE_422=1 run "$REPO/scripts/release.sh" --skip-macos --skip-tests
    [ "$status" -eq 0 ]
    [[ "$output" == *"generated notes were refused"* ]]
    [[ "$output" == *"published."* ]]
    [ "$(grep -c "release create v0.1.0" "$GH_LOG")" -eq 2 ]
    grep -q -- "release create v0.1.0 .*--generate-notes --notes-start-tag v0.0.9" "$GH_LOG"
    grep -q -- "release create v0.1.0 .*--notes romp v0.1.0" "$GH_LOG"
    grep -q -- "pull requests merged since v0.0.9. The full list: https://github.com/romp-on/romp/compare/v0.0.9...v0.1.0" "$GH_LOG"
    run git -C "$TEST_DIR/origin.git" tag -l
    [ "$output" = "v0.1.0" ]
}

@test "release: a range with more merged pull requests than the ceiling allows skips the generated notes" {
    git -C "$REPO" tag v0.0.9
    # two merged pull requests since the previous tag, simulated as first-parent merge commits
    for i in 1 2; do
        git -C "$REPO" switch -q -c "pr-$i"
        echo "$i" > "$REPO/pr-$i.txt"; git -C "$REPO" add -A; git -C "$REPO" commit -qm "pr $i"
        git -C "$REPO" switch -q main
        git -C "$REPO" merge -q --no-ff -m "Merge pull request #$i" "pr-$i"
    done
    git -C "$REPO" push -q origin main
    _stub_gh
    ROMP_RELEASE_NOTES_MAX_PRS=1 run "$REPO/scripts/release.sh" --skip-macos --skip-tests
    [ "$status" -eq 0 ]
    [[ "$output" == *"2 pull requests since v0.0.9, more than 1"* ]]
    [ "$(grep -c "release create v0.1.0" "$GH_LOG")" -eq 1 ]
    run grep -q -- "--generate-notes" "$GH_LOG"
    [ "$status" -ne 0 ]
    grep -q -- "2 pull requests merged since v0.0.9" "$GH_LOG"
}

@test "release: pushes the tag and publishes the release" {
    _stub_gh
    run "$REPO/scripts/release.sh" --skip-tests
    [ "$status" -eq 0 ]
    grep -q "release create v0.1.0" "$GH_LOG"
    # the tag really reached the remote — a local-only tag installs for nobody
    run git -C "$TEST_DIR/origin.git" tag -l
    [ "$output" = "v0.1.0" ]
}

@test "release: a fork layout pushes the branch to origin, and reads main + pushes the tag at upstream" {
    # The remote convention (the user 2026-09-06): `origin` is the fork, `upstream` the canonical
    # repo. The version PR merges on the canonical repo, so the post-merge fast-forward must read
    # upstream/main: origin/main is the fork's stale main, and fast-forwarding onto it silently
    # tags a commit that never got the bump. And the tag must land where installs look for it.
    _stub_gh
    git init -q --bare "$TEST_DIR/upstream.git"
    git -C "$REPO" remote add upstream "$TEST_DIR/upstream.git"
    git -C "$REPO" push -q upstream main
    export STUB_MERGE_REMOTE=upstream
    run "$REPO/scripts/release.sh" minor --skip-tests
    [ "$status" -eq 0 ]
    # the version branch went to the fork (origin: no pushDefault set here)
    run git -C "$TEST_DIR/origin.git" branch --list release-0.2.0
    [[ "$output" == *"release-0.2.0"* ]]
    # local main was fast-forwarded from the canonical repo, so the tagged tree carries the bump
    [ "$(cat "$REPO/VERSION")" = "0.2.0" ]
    # the tag reached the canonical repo, and never the fork
    [ "$(git -C "$TEST_DIR/upstream.git" tag -l)" = "v0.2.0" ]
    [ -z "$(git -C "$TEST_DIR/origin.git" tag -l)" ]
}

@test "release: notes start at the PREVIOUS tag, never at the one being cut" {
    _stub_gh
    git -C "$REPO" tag v0.0.9
    run "$REPO/scripts/release.sh" --skip-tests
    [ "$status" -eq 0 ]
    grep -q -- "--notes-start-tag v0.0.9" "$GH_LOG"
}

# ── the ordinary guards ───────────────────────────────────────────────

@test "release: refuses a dirty tree" {
    _stub_gh
    echo dirty > "$REPO/junk.txt"
    git -C "$REPO" add junk.txt
    run "$REPO/scripts/release.sh" --skip-tests
    [ "$status" -ne 0 ]
    [[ "$output" == *"dirty"* ]]
}

@test "release: refuses a tag that already exists" {
    _stub_gh
    git -C "$REPO" tag v0.1.0
    run "$REPO/scripts/release.sh" --skip-tests
    [ "$status" -ne 0 ]
    [[ "$output" == *"already exists"* ]]
    [ ! -s "$GH_LOG" ]                        # bailed before spending any CI
}

@test "release: refuses when VERSION is missing" {
    _stub_gh
    rm "$REPO/VERSION"
    git -C "$REPO" commit -qam rmver
    run "$REPO/scripts/release.sh" --skip-tests
    [ "$status" -ne 0 ]
    [[ "$output" == *"source of truth"* ]]
}

@test "release: refuses a VERSION that is not X.Y.Z" {
    _stub_gh
    echo "nightly" > "$REPO/VERSION"
    git -C "$REPO" commit -qam ver
    run "$REPO/scripts/release.sh" --skip-tests
    [ "$status" -ne 0 ]
    [[ "$output" == *"is not X.Y.Z"* ]]
}

@test "release: a prerelease version tags as-is" {
    _stub_gh
    echo "0.2.0-rc.1" > "$REPO/VERSION"
    git -C "$REPO" commit -qam ver
    run "$REPO/scripts/release.sh" --skip-tests
    [ "$status" -eq 0 ]
    run git -C "$REPO" tag -l
    [ "$output" = "v0.2.0-rc.1" ]
}

@test "release: a prerelease bumps from its release number" {
    _stub_gh
    echo "0.2.0-rc.1" > "$REPO/VERSION"
    git -C "$REPO" commit -qam ver
    run "$REPO/scripts/release.sh" minor --skip-tests --dry-run
    [[ "$output" == *"0.2.0-rc.1 → 0.3.0"* ]]
}

@test "release: --dry-run changes nothing at all" {
    _stub_gh
    run "$REPO/scripts/release.sh" minor --skip-tests --dry-run
    [ "$status" -eq 0 ]
    run git -C "$REPO" tag -l
    [ -z "$output" ]
    run cat "$REPO/VERSION"
    [ "$output" = "0.1.0" ]
}

@test "release: a failing suite stops the release before any tag — and never reroutes" {
    # The runner is PRESENT (the probe is presence-only: --version answers) and the SUITE fails —
    # the safety semantics the resolver must never soften: this stops the release with the suite
    # message, and it must NOT fall through to uv (a failing suite is not a missing runner). The
    # old shape ran the real ambient python3 against a failing fixture conftest, which proved the
    # same gate only on machines that HAPPENED to have pytest — on a pytest-less shell the die
    # fired with the resolver's missing-runner wording instead and the message assertion broke
    # (CI, 2026-08-31). Stubbed present-but-failing, the case is hermetic on every shell.
    _stub_gh; _stub_python3 suite-fails; _stub_uvx
    run env PATH="$(_env_path)" "$REPO/scripts/release.sh"
    [ "$status" -ne 0 ]
    [[ "$output" == *"Python suite failed"* ]]
    [ ! -s "$UVX_LOG" ]                 # present ambient + failing suite → never rerouted to uv
    run git -C "$REPO" tag -l
    [ -z "$output" ]
}

# ── the suite-environment resolver (the v0.13.0 lesson) ───────────────
# release.sh died mid-release on a bare ModuleNotFoundError on a box with only a repo venv.
# It now resolves its own suite runner: a WORKING ambient `python3 -m pytest` first, else uv's
# throwaway env with CI's exact dep set, else a LOUD failure naming both remedies — before any
# release state is at stake. PATH is narrowed per test so the resolver sees exactly the world
# each case describes; the stubbed runners record their argv so the invocation shape is pinned.

_stub_python3() {                       # $1 = "with-pytest" | "no-pytest" | "suite-fails"
    cat > "$TEST_DIR/python3" <<PYSTUB
#!/bin/sh
echo "python3 \$*" >> "$TEST_DIR/py.log"
if [ "\$1" = "-m" ] && [ "\$2" = "pytest" ]; then
    case "$1" in
        with-pytest) exit 0 ;;                          # present, and every run succeeds
        suite-fails) [ "\$3" = "--version" ] && exit 0; exit 1 ;;   # PRESENT (probe ok), the suite run fails
        *) exit 1 ;;                                    # no pytest at all — probe and runs alike
    esac
fi
exit 0
PYSTUB
    chmod +x "$TEST_DIR/python3"
}

_stub_uvx() {
    cat > "$TEST_DIR/uvx" <<'UVSTUB'
#!/bin/sh
echo "uvx $*" >> "$UVX_LOG"
exit 0
UVSTUB
    chmod +x "$TEST_DIR/uvx"
    export UVX_LOG="$TEST_DIR/uvx.log"
}

_env_path() {                           # a narrowed PATH: the stubs + the bare essentials
    echo "$TEST_DIR:/usr/bin:/bin"
}

@test "release: a working ambient pytest is preferred — no provisioning" {
    _stub_gh; _stub_python3 with-pytest; _stub_uvx
    run env PATH="$(_env_path)" "$REPO/scripts/release.sh"
    [ "$status" -eq 0 ]
    grep -q "python3 -m pytest tests/ -q" "$TEST_DIR/py.log"
    [ ! -s "$UVX_LOG" ]
}

@test "release: no ambient pytest + uv present → the suite runs through uv's throwaway env" {
    _stub_gh; _stub_python3 no-pytest; _stub_uvx
    run env PATH="$(_env_path)" "$REPO/scripts/release.sh"
    [ "$status" -eq 0 ]
    [[ "$output" == *"throwaway env"* ]]
    grep -q -- "uvx --with pytest --with cryptography pytest tests/ -q" "$UVX_LOG"
}

@test "release: neither pytest nor uv → a LOUD refusal naming both remedies, before any release work" {
    _stub_gh; _stub_python3 no-pytest
    rm -f "$TEST_DIR/uvx"
    run env PATH="$(_env_path)" "$REPO/scripts/release.sh"
    [ "$status" -ne 0 ]
    [[ "$output" == *"no way to run the Python suite"* ]]
    [[ "$output" == *"astral.sh/uv/install.sh"* ]]
    [[ "$output" == *"pip install --upgrade pytest cryptography"* ]]
    run git -C "$REPO" tag -l
    [ -z "$output" ]                    # nothing was tagged — the refusal came first
}

@test "release: ROMP_RELEASE_PYTEST overrides the resolver entirely (the test seam)" {
    _stub_gh; _stub_python3 no-pytest
    cat > "$TEST_DIR/myrunner" <<RSTUB
#!/bin/sh
echo "myrunner \$*" >> "$TEST_DIR/my.log"
exit 0
RSTUB
    chmod +x "$TEST_DIR/myrunner"
    run env PATH="$(_env_path)" ROMP_RELEASE_PYTEST="$TEST_DIR/myrunner" "$REPO/scripts/release.sh"
    [ "$status" -eq 0 ]
    grep -q "myrunner tests/ -q" "$TEST_DIR/my.log"
}

# ── the suites' order and environment (2026-09-24) ─────────────────────────────────────────
# The script orders the suites as CI's extension job does (the webview typecheck, suite and build,
# then the Python suite against that build: the labs that serve the checkout's dist as it stands
# get the tip's bundle, and a broken build stops the release before the suite instead of inside a
# lab an hour in), scrubs the live kernel's exports a romp session's shell carries for the Python
# run, and requires the served labs where playwright's chromium is installed, declaring the
# engines CI declares. Parity with CI: at the v0.17.0 cut two federation labs were red in the
# local run on a box running a live romp and green in CI on the same tip, and they stay red
# there under this order and scrub; on such a box the gate is CI green on the tip through
# --skip-tests. Every call below lands in one sequence log, so the ORDER is what these pin.

_stub_npm() {                           # $1 = "ok" | "typecheck-fails" | "test-fails" | "build-fails"
    cat > "$TEST_DIR/npm" <<NPMSTUB
#!/bin/sh
echo "npm \$*" >> "$TEST_DIR/seq.log"
if [ "\$1 \$2" = "run typecheck" ] && [ "$1" = "typecheck-fails" ]; then exit 1; fi
if [ "\$1" = "test" ] && [ "$1" = "test-fails" ]; then exit 1; fi
if [ "\$1 \$2" = "run build" ] && [ "$1" = "build-fails" ]; then exit 1; fi
exit 0
NPMSTUB
    chmod +x "$TEST_DIR/npm"
}

_stub_python3_recording() {            # a present pytest whose suite run records its argv, its environment's NAMES, and the served knobs' values
    cat > "$TEST_DIR/python3" <<PYSTUB
#!/bin/sh
echo "python3 \$*" >> "$TEST_DIR/seq.log"
if [ "\$1" = "-m" ] && [ "\$2" = "pytest" ] && [ "\$3" = "tests/" ]; then
    env | cut -d= -f1 | sort > "$TEST_DIR/suite-env.txt"
    env | grep '^ROMP_SERVED_TESTS_' | sort > "$TEST_DIR/suite-served.txt" || true
fi
exit 0
PYSTUB
    chmod +x "$TEST_DIR/python3"
}

_stub_node() {                          # $1 = "both" | "full-only" | "shell-only" | "none" | "shell-no-location": which of playwright's two
    #                                         Chromium downloads are complete; the last is both complete but the listing lost the
    #                                         shell section's Install location line (the next section's directory must not be read)
    mkdir -p "$TEST_DIR/pw/chromium-1" "$TEST_DIR/pw/chromium_headless_shell-1" "$TEST_DIR/pw/ffmpeg-1"
    : > "$TEST_DIR/pw/ffmpeg-1/INSTALLATION_COMPLETE"
    case "$1" in both|full-only|shell-no-location) : > "$TEST_DIR/pw/chromium-1/INSTALLATION_COMPLETE" ;; esac
    case "$1" in both|shell-only|shell-no-location) : > "$TEST_DIR/pw/chromium_headless_shell-1/INSTALLATION_COMPLETE" ;; esac
    local shell_loc="  Install location:    $TEST_DIR/pw/chromium_headless_shell-1"
    [ "$1" = "shell-no-location" ] && shell_loc="  Download url:        https://example.test/chrome-headless-shell-linux64.zip"
    # the resolve call (node -e ...) answers the cli's path; the listing call answers the sections, the shell's LAST so a grab
    # that ran past a missing line would land on the download after it (ffmpeg, complete here)
    cat > "$TEST_DIR/node" <<NODESTUB
#!/bin/sh
echo "node \$*" >> "$TEST_DIR/seq.log"
if [ "\$1" = "-e" ]; then printf '%s' "$TEST_DIR/pw-cli.js"; exit 0; fi
cat <<LISTING
Chrome for Testing 1.0 (playwright chromium v1)
  Install location:    $TEST_DIR/pw/chromium-1
  Download url:        https://example.test/chrome-linux64.zip
Chrome Headless Shell 1.0 (playwright chromium-headless-shell v1)
$shell_loc
FFmpeg (playwright ffmpeg v1)
  Install location:    $TEST_DIR/pw/ffmpeg-1
LISTING
NODESTUB
    chmod +x "$TEST_DIR/node"
}

_with_extension_deps() { mkdir -p "$REPO/vscode-extension/node_modules"; }

@test "release: with the extension deps present, the webview typecheck, suite and BUILD run before the Python suite, in that order" {
    _stub_gh; _stub_npm ok; _stub_node both; _stub_python3_recording; _with_extension_deps
    run env PATH="$(_env_path)" "$REPO/scripts/release.sh"
    [ "$status" -eq 0 ]
    [ "$(grep -c '^npm run build$' "$TEST_DIR/seq.log")" -eq 1 ]
    c="$(grep -n '^npm run typecheck$' "$TEST_DIR/seq.log" | cut -d: -f1)"
    t="$(grep -n '^npm test$' "$TEST_DIR/seq.log" | cut -d: -f1)"
    b="$(grep -n '^npm run build$' "$TEST_DIR/seq.log" | cut -d: -f1)"
    p="$(grep -n '^python3 -m pytest tests/ -q$' "$TEST_DIR/seq.log" | cut -d: -f1)"
    [ -n "$c" ]; [ -n "$t" ]; [ -n "$b" ]; [ -n "$p" ]
    [ "$c" -lt "$t" ]
    [ "$t" -lt "$b" ]
    [ "$b" -lt "$p" ]
}

@test "release: a failing webview typecheck stops the release BEFORE the Python suite, and nothing is tagged" {
    _stub_gh; _stub_npm typecheck-fails; _stub_node both; _stub_python3_recording; _with_extension_deps
    run env PATH="$(_env_path)" "$REPO/scripts/release.sh"
    [ "$status" -ne 0 ]
    [[ "$output" == *"webview typecheck failed"* ]]
    [ "$(grep -c '^python3 -m pytest tests/' "$TEST_DIR/seq.log")" -eq 0 ]
    run git -C "$REPO" tag -l
    [ -z "$output" ]
}

@test "release: a failing webview suite stops the release BEFORE the Python suite, and nothing is tagged" {
    _stub_gh; _stub_npm test-fails; _stub_node both; _stub_python3_recording; _with_extension_deps
    run env PATH="$(_env_path)" "$REPO/scripts/release.sh"
    [ "$status" -ne 0 ]
    [[ "$output" == *"webview suite failed"* ]]
    [ "$(grep -c '^python3 -m pytest tests/' "$TEST_DIR/seq.log")" -eq 0 ]
    run git -C "$REPO" tag -l
    [ -z "$output" ]
}

@test "release: a failing webview build stops the release BEFORE the Python suite, and nothing is tagged" {
    _stub_gh; _stub_npm build-fails; _stub_node both; _stub_python3_recording; _with_extension_deps
    run env PATH="$(_env_path)" "$REPO/scripts/release.sh"
    [ "$status" -ne 0 ]
    [[ "$output" == *"webview build failed"* ]]
    [ "$(grep -c '^python3 -m pytest tests/' "$TEST_DIR/seq.log")" -eq 0 ]
    run git -C "$REPO" tag -l
    [ -z "$output" ]
}

@test "release: the Python suite runs without any ROMP_ name the shell carries except the suite's own knobs, and with the served labs required and chromium declared when both Chromium parts are installed" {
    _stub_gh; _stub_npm ok; _stub_node both; _stub_python3_recording; _with_extension_deps
    # six names the live kernel exports, one no list would think of (ROMP_STATE_TAG: the rule is every ROMP_ name), and
    # one of the suite's own knobs, which must pass through
    run env PATH="$(_env_path)" ROMP_MANAGER_PID=4242 ROMP_SERVE_HOST=0.0.0.0 \
        ROMP_SID=cccccccc-1111-2222-3333-444444444444 ROMP_SESSION_NAME=web ROMP_KERNEL_PORT=7433 ROMP_POSTAL_PORT=25302 \
        ROMP_STATE_TAG=tag-of-the-live-box ROMP_TESTS_SYSTEM_TMPDIR="$TEST_DIR/systmp" \
        "$REPO/scripts/release.sh"
    [ "$status" -eq 0 ]
    [ -s "$TEST_DIR/suite-env.txt" ]
    [ "$(grep -c -E '^(ROMP_MANAGER_PID|ROMP_SERVE_HOST|ROMP_SID|ROMP_SESSION_NAME|ROMP_KERNEL_PORT|ROMP_POSTAL_PORT|ROMP_STATE_TAG)$' "$TEST_DIR/suite-env.txt")" -eq 0 ]
    [ "$(grep -c '^ROMP_TESTS_SYSTEM_TMPDIR$' "$TEST_DIR/suite-env.txt")" -eq 1 ]
    [ "$(grep -c '^ROMP_SERVED_TESTS_REQUIRE=1$' "$TEST_DIR/suite-served.txt")" -eq 1 ]
    [ "$(grep -c '^ROMP_SERVED_TESTS_ENGINES=chromium$' "$TEST_DIR/suite-served.txt")" -eq 1 ]
    grep -q '^python3 -m pytest tests/ -q$' "$TEST_DIR/seq.log"
}

@test "release: an engines list the shell declares reaches the served labs as it stands, beside the require flag" {
    _stub_gh; _stub_npm ok; _stub_node both; _stub_python3_recording; _with_extension_deps
    run env PATH="$(_env_path)" ROMP_SERVED_TESTS_ENGINES=chromium,firefox "$REPO/scripts/release.sh"
    [ "$status" -eq 0 ]
    [ "$(grep -c '^ROMP_SERVED_TESTS_REQUIRE=1$' "$TEST_DIR/suite-served.txt")" -eq 1 ]
    [ "$(grep -c '^ROMP_SERVED_TESTS_ENGINES=chromium,firefox$' "$TEST_DIR/suite-served.txt")" -eq 1 ]
}

@test "release: node deps present but no browser: the served labs are not required, and the line says their gate is CI and the remedy runs from the extension directory" {
    _stub_gh; _stub_npm ok; _stub_node none; _stub_python3_recording; _with_extension_deps
    run env PATH="$(_env_path)" "$REPO/scripts/release.sh"
    [ "$status" -eq 0 ]
    [[ "$output" == *"node deps present, no browser"* ]]
    [[ "$output" == *"cd vscode-extension && npx playwright install chromium"* ]]
    [[ "$output" == *"their gate is CI's extension job on the tip"* ]]
    [ -s "$TEST_DIR/suite-env.txt" ]
    [ "$(grep -c '^ROMP_SERVED_TESTS_REQUIRE$' "$TEST_DIR/suite-env.txt")" -eq 0 ]
    [ "$(grep -c '^python3 -m pytest tests/ -q$' "$TEST_DIR/seq.log")" -eq 1 ]
}

@test "release: the full Chromium alone is a partial install: the labs are not required, and the line names the missing headless shell" {
    _stub_gh; _stub_npm ok; _stub_node full-only; _stub_python3_recording; _with_extension_deps
    run env PATH="$(_env_path)" "$REPO/scripts/release.sh"
    [ "$status" -eq 0 ]
    [[ "$output" == *"partial browser install"* ]]
    [[ "$output" == *"the headless shell the labs launch is not"* ]]
    [ "$(grep -c '^ROMP_SERVED_TESTS_REQUIRE$' "$TEST_DIR/suite-env.txt")" -eq 0 ]
    [ "$(grep -c '^python3 -m pytest tests/ -q$' "$TEST_DIR/seq.log")" -eq 1 ]
}

@test "release: the headless shell alone is a partial install: the labs are not required, and the line names the missing full Chromium" {
    _stub_gh; _stub_npm ok; _stub_node shell-only; _stub_python3_recording; _with_extension_deps
    run env PATH="$(_env_path)" "$REPO/scripts/release.sh"
    [ "$status" -eq 0 ]
    [[ "$output" == *"partial browser install"* ]]
    [[ "$output" == *"the full Chromium is not"* ]]
    [ "$(grep -c '^ROMP_SERVED_TESTS_REQUIRE$' "$TEST_DIR/suite-env.txt")" -eq 0 ]
    [ "$(grep -c '^python3 -m pytest tests/ -q$' "$TEST_DIR/seq.log")" -eq 1 ]
}

@test "release: a listing whose shell section lost its Install location line reads the shell as absent, never the next download's directory" {
    _stub_gh; _stub_npm ok; _stub_node shell-no-location; _stub_python3_recording; _with_extension_deps
    run env PATH="$(_env_path)" "$REPO/scripts/release.sh"
    [ "$status" -eq 0 ]
    [[ "$output" == *"partial browser install"* ]]
    [[ "$output" == *"the headless shell the labs launch is not"* ]]
    [ "$(grep -c '^ROMP_SERVED_TESTS_REQUIRE$' "$TEST_DIR/suite-env.txt")" -eq 0 ]
    grep -q "^node $TEST_DIR/pw-cli.js install --dry-run chromium$" "$TEST_DIR/seq.log"
}

@test "release: writing the gh stub runs no gh of its own (the heredoc's backticks are escaped)" {
    # the stub is written by an UNQUOTED heredoc, so an unescaped backtick pair in its comments runs as a command while
    # the file is written: a spy gh first on PATH records any such run
    mkdir -p "$TEST_DIR/spy"
    printf '#!/bin/sh\necho "spy gh $*" >> "%s/spy.log"\nexit 0\n' "$TEST_DIR" > "$TEST_DIR/spy/gh"
    chmod +x "$TEST_DIR/spy/gh"
    PATH="$TEST_DIR/spy:$PATH" _stub_gh
    [ "$(cat "$TEST_DIR/spy.log" 2>/dev/null | wc -l)" -eq 0 ]
    [ -x "$TEST_DIR/gh" ]
}

@test "release: without the extension deps the script says the served labs are not proven here, and does not require them" {
    _stub_gh; _stub_python3_recording
    run env PATH="$(_env_path)" "$REPO/scripts/release.sh"
    [ "$status" -eq 0 ]
    [[ "$output" == *"served labs skip here"* ]]
    [[ "$output" == *"CI's extension job on the tip"* ]]
    [ -s "$TEST_DIR/suite-env.txt" ]
    [ "$(grep -c '^ROMP_SERVED_TESTS_REQUIRE$' "$TEST_DIR/suite-env.txt")" -eq 0 ]
}

@test "release: --skip-tests names CI green on the tip as the gate, with the tip's sha" {
    _stub_gh
    run "$REPO/scripts/release.sh" --skip-tests
    [ "$status" -eq 0 ]
    tip="$(git -C "$REPO" rev-parse --short HEAD)"
    [[ "$output" == *"CI green on the tip being tagged ($tip)"* ]]
}
