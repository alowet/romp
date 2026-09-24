#!/usr/bin/env bash
# scripts/release.sh [major|minor|patch|X.Y.Z] [flags] — cut a romp release, end to end.
#
# ONE SOURCE OF TRUTH: the VERSION file. The tag is DERIVED from it, always as
# "v$(cat VERSION)", and this script does not accept a tag argument at all. That is
# deliberate: the old interface took the tag and then checked it against VERSION, so the
# two could disagree and the only thing standing between you and a mismatched release was
# a comparison you had to remember to trust. Removing the second input removes the whole
# class of error — there is now exactly one place a human types the number, and everything
# downstream is computed (the user 2026-07-29, who wanted one script that does everything
# and keeps the version in sync with the tags).
#
# It runs the whole sequence, because the steps between "bump the number" and "users can
# install it" were a chain of by-hand commands that were easy to half-finish. Leaving
# VERSION merged but untagged is the worst of those states: main claims a version that
# bootstrap.sh will not install, since bootstrap picks the newest v* TAG.
#
#   1. resolve the target version (a bump level, an explicit number, or whatever VERSION
#      already says) and refuse it if that tag already exists
#   2. if VERSION needs to change: branch, commit, push, open a PR, auto-merge it, and wait
#      for it to land on main  (skipped entirely when VERSION is already correct)
#   3. run the test suites in CI's order: the webview typecheck, suite and BUILD, then the
#      Python suite (the served labs serve the bundle the build just wrote) with every ROMP_
#      name the environment carries removed except the suite's own knobs, and the served labs
#      required rather than skippable where BOTH of playwright's Chromium downloads (the full
#      browser and the headless shell) are complete (see the note on a box running a live romp)
#   4. the macOS gate (see below)
#   5. tag, push the tag, and publish the GitHub release
#
# Two rules it has always existed to enforce, both easy to get wrong by hand and expensive
# to get wrong in public:
#
#   * The tag MUST be v-prefixed. bootstrap.sh picks the release with
#     `git tag -l 'v*' --sort=-v:refname | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -n1`.
#     A tag like "0.1.0" matches NOTHING, so the one-line installer silently falls back to
#     main instead of installing the release — no error, just the wrong thing. Deriving the
#     tag guarantees the prefix.
#   * macOS CI does not run on pushes (it is billed even on public repos, ~10x, so it is
#     workflow_dispatch-only). A macOS-only breakage can therefore sit undetected until a
#     user hits it. Releasing is exactly when that matters, so this triggers the macOS run
#     and REFUSES to tag unless it goes green.
#
# --skip-macos exists for the case where you must ship anyway; it is deliberately an
# explicit flag (never an env default) and it says so loudly.
set -euo pipefail

GH="${ROMP_GH:-gh}"                       # overridable so tests can stub the GitHub CLI
PYTEST="${ROMP_RELEASE_PYTEST:-}"         # overridable suite runner (tests); empty → resolve below
POLL="${ROMP_RELEASE_POLL:-5}"            # seconds between checks while the run starts
REF="${ROMP_RELEASE_REF:-main}"
UPSTREAM="${ROMP_RELEASE_UPSTREAM:-romp-on/romp}"

# Which git remote is the canonical repo, and which one takes the branch push. The convention
# (the user 2026-09-06): in a clone with a fork, `origin` is the fork and `upstream` is the
# canonical repo; a plain clone has only `origin`, which is then both. So the canonical remote
# is `upstream` when the clone has one, else `origin`; the branch push goes to
# `remote.pushDefault` when set, else `origin`.
canonical_remote() {
    if git remote get-url upstream >/dev/null 2>&1; then echo upstream; else echo origin; fi
}
publish_remote() {
    local p
    p="$(git config --get remote.pushDefault || true)"
    printf '%s\n' "${p:-origin}"
}
skip_macos=0
skip_tests=0
dry_run=0
bump=""

usage() {
    cat >&2 <<'USAGE'
usage: scripts/release.sh [major|minor|patch|X.Y.Z] [flags]

  (no argument)       release the version VERSION already carries
  major|minor|patch   bump VERSION by that much first, via a PR
  X.Y.Z               set VERSION to exactly this, via a PR

flags:
  --skip-macos    tag without waiting for the dispatch-only macOS run (loud, discouraged)
  --skip-tests    do not run the local suites before releasing; acceptable only when CI is
                  green on the very tip being tagged (that run is then the gate: name it in
                  the notes)
  --dry-run       print what would happen; change nothing
USAGE
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --skip-macos) skip_macos=1 ;;
        --skip-tests) skip_tests=1 ;;
        --dry-run)    dry_run=1 ;;
        -h|--help)    usage ;;
        -*)           echo "release: unknown flag $1" >&2; usage ;;
        v[0-9]*)      echo "release: pass the version WITHOUT the leading v ('${1#v}', not '$1')." >&2
                      echo "  The tag is derived from VERSION, so the two cannot disagree." >&2
                      exit 2 ;;
        *)            [ -z "$bump" ] || usage; bump="$1" ;;
    esac
    shift
done

die() { echo "release: $*" >&2; exit 1; }
say() { echo "release: $*"; }
step() { if [ "$dry_run" -eq 1 ]; then echo "release: [dry-run] $*"; else "$@"; fi; }

# Resolve the repo from THIS SCRIPT's location, never the caller's cwd. With
# `git rev-parse --show-toplevel` the script would inspect — and tag — whatever repo you
# happened to be standing in, reading that tree's cleanliness and VERSION instead of the one
# being released.
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

[ -f VERSION ] || die "no VERSION file at the repo root — it is the source of truth and must exist."
current="$(tr -d '[:space:]' < VERSION)"

# ── 1. resolve the target version ─────────────────────────────────────
# The bump arithmetic works on the X.Y.Z core, so a prerelease suffix ("0.2.0-rc.1") bumps
# from its release number rather than tripping the parser.
core="${current%%-*}"
if [[ ! "$core" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    die "VERSION ('$current') is not X.Y.Z — cannot compute a bump from it."
fi
IFS=. read -r cur_major cur_minor cur_patch <<EOF
$core
EOF

case "$bump" in
    "")      target="$current" ;;
    major)   target="$((cur_major + 1)).0.0" ;;
    minor)   target="$cur_major.$((cur_minor + 1)).0" ;;
    patch)   target="$cur_major.$cur_minor.$((cur_patch + 1))" ;;
    *)       target="$bump" ;;
esac

if [[ ! "$target" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]]; then
    die "'$target' is not semver (X.Y.Z, optionally with a prerelease suffix)."
fi
tag="v$target"

if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
    die "tag $tag already exists."
fi

say "releasing $tag (VERSION currently reads $current)."

# ── 2. the tree must be releasable ────────────────────────────────────
[ -z "$(git status --porcelain)" ] || die "working tree is dirty — commit or stash first."
# And checked out on $REF: the tag goes on whatever HEAD is, bootstrap.sh installs the newest
# v* tag, so a tag cut anywhere else ships a commit that is not on $REF. The way to be here
# off $REF is a bump run that died with its version PR unmerged — the PR could not be opened,
# or the wait for it ran out — still on release-X.Y.Z, where VERSION already reads the target,
# so the advertised re-run would skip the bump and tag that branch. Checked once, here: the
# bump path below either ends back on $REF or dies, so it still holds at the tag step, and
# refusing now spends no suite run and no macOS wait on a release that cannot be cut. A detached
# HEAD is named as such: `symbolic-ref` prints nothing for it (and exits 1, hence `|| true`
# under set -e), where `rev-parse --abbrev-ref` would have blamed a branch called HEAD.
on_branch="$(git symbolic-ref -q --short HEAD || true)"
[ -n "$on_branch" ] || die "detached HEAD, not on $REF — a release is cut from $REF only; switch to it and pull first."
[ "$on_branch" = "$REF" ] || die "on branch $on_branch, not $REF — the version PR may still be open; switch to $REF and pull once it lands."

# ── 3. land the version bump, if there is one ─────────────────────────
# Skipped entirely when VERSION already carries the target, which is the normal case when a
# bump PR landed earlier. That makes a half-finished release resumable: re-running picks up
# where it stopped instead of insisting on starting over.
if [ "$current" != "$target" ]; then
    # Branch pushes to the upstream are blocked by rulesets, so publishing is always
    # push-to-a-fork then PR. remote.pushDefault is the configured answer when there is one.
    publish="$(publish_remote)"
    branch="release-$target"
    say "VERSION $current → $target, via a PR on $branch (pushing to '$publish')."
    if [ "$dry_run" -eq 1 ]; then
        say "[dry-run] would branch, commit VERSION=$target, open a PR, and auto-merge it."
    else
        # Branch FIRST, then write: a branch that already exists dies here, and main is left as it
        # was rather than holding a modified VERSION nobody asked for.
        git switch -c "$branch" >/dev/null 2>&1 || die "could not create branch $branch."
        printf '%s\n' "$target" > VERSION
        git add VERSION
        git commit -qm "VERSION $target" || die "nothing to commit for the version bump."
        git push -q -u "$publish" "$branch" || die "could not push $branch to $publish."
        # Address the PR by NUMBER, taken from the URL `gh pr create` prints (the user 2026-08-01).
        # `gh pr merge <branch>` resolves the branch WITHIN --repo, and the branch lives on the FORK
        # (rulesets block branch pushes upstream, so every PR here is fork-headed) — so it answered
        # "no pull requests found for branch release-0.3.0" and the release died one step after
        # opening the PR, leaving VERSION merged-but-untagged, exactly the half-finished state this
        # script exists to prevent. A number is unambiguous in any repo.
        # Every PR on the upstream carries exactly one tier label (docs / fix / feature /
        # major-feature), and a required check holds an unlabeled PR red, so auto-merge would
        # never fire and the release would stall one step after opening it. A version bump is
        # repo plumbing with no behavior change, so it wears tier 0, `docs`: the tier policy treats
        # docs and fix as ONE tier that merges on green for every author, with no rule on which
        # files a docs PR may touch (scripts/ci/tier_policy.py, ON_GREEN). The label is resolved on
        # the server by `gh pr create --label`, so it must be a label the repository HAS: the
        # pre-rename spelling `tests-only` is now only a body alias, and naming it here failed the
        # cut of v0.16.0 one step after the version branch was pushed (2026-09-16). The body carries
        # the same tier as a `Tier:` line, the road a contributor who cannot label uses, so the tier
        # workflow can apply the label itself should the label name move again.
        pr_url="$("$GH" pr create --repo "$UPSTREAM" --title "VERSION $target" \
            --label docs \
            --body "Version bump for \`$tag\`, opened by scripts/release.sh.

Tier: docs")" \
            || die "could not open the version PR."
        pr="${pr_url##*/}"
        case "$pr" in
            ''|*[!0-9]*) die "could not read the PR number from '$pr_url'." ;;
        esac
        say "opened PR #$pr."
        "$GH" pr merge "$pr" --repo "$UPSTREAM" --auto --merge \
            || die "could not arm auto-merge on PR #$pr."
        say "waiting for the version PR to land on $REF (its CI is the first gate)..."
        state=""
        for _ in $(seq 1 120); do
            state="$("$GH" pr view "$pr" --repo "$UPSTREAM" --json state -q .state 2>/dev/null || true)"
            if [ "$state" = "MERGED" ]; then break; fi
            if [ "$state" = "CLOSED" ]; then die "the version PR was closed without merging."; fi
            if [ "$POLL" = "0" ]; then break; fi
            sleep "$POLL"
        done
        # Still on the release branch here, so the way forward is spelled out: local $REF is behind
        # the merge until it is pulled, and a re-run on this branch is refused (step 2).
        [ "$state" = "MERGED" ] || die "the version PR did not merge — check $UPSTREAM; once it lands, switch to $REF and pull, then re-run."
        git switch "$REF" >/dev/null 2>&1 || die "could not switch back to $REF."
        # The merge landed on the CANONICAL repo. With a fork layout that is `upstream`, not
        # `origin`: reading `origin/main` there would fast-forward onto the fork's stale main
        # (a no-op) and then tag a commit that never got the bump.
        canonical="$(canonical_remote)"
        git fetch -q "$canonical"
        git merge --ff-only "$canonical/$REF" >/dev/null || die "could not fast-forward $REF after the merge."
        say "version PR merged; $REF now carries $target."
    fi
else
    say "VERSION already reads $target — no bump PR needed."
fi

# Re-read rather than trust the arithmetic: after the merge, the file on disk is the truth.
if [ "$dry_run" -eq 0 ]; then
    have="$(tr -d '[:space:]' < VERSION)"
    [ "$have" = "$target" ] || die "VERSION says '$have' but we are releasing '$tag' — refusing to tag a mismatch."
fi

# ── 4. the tests ──────────────────────────────────────────────────────
# A romp session's shell carries the live kernel's exports (the manager pid, the serve host, the
# session's sid and name, the ports, the state tag, the shutdown grace, and whatever a later kernel
# adds). The suite's conftest floors the state root and the ports and every lab kernel is built from
# a list of names, but a run from such a shell still hands the rest to the labs' node drivers and to
# every test that copies its environment. The rule, not a list: EVERY ROMP_ name the environment
# carries is removed for the Python run, except the suite's own knobs (ROMP_SERVED_TESTS_*, which
# this script sets below, ROMP_TESTS_*, and ROMP_UI_BENCH_REQUIRE, the ones tests/conftest.py
# documents), so the suite sees the machine the way CI's runner does: parity with CI, so that what
# the local run says is comparable with CI's, not a diagnosis of anything.
#
# The served labs on a box that runs a live romp: at the v0.17.0 cut (2026-09-24) two federation labs
# (the task-tracking federation lab and the send-bubble remote lab) were red in the local run on the
# shared box and green in CI on the same tip, and they stay red there with the tip's bundle built and
# these names removed; the cause is open. On such a box the gate for the tag is CI green on the tip,
# through --skip-tests, the documented road.
SUITE_KNOB_PATTERN='^(ROMP_SERVED_TESTS_|ROMP_TESTS_|ROMP_UI_BENCH_REQUIRE$)'
scrubbed() {
    local unset_args="" name
    for name in $(env | sed -n 's/^\(ROMP_[A-Za-z0-9_]*\)=.*/\1/p' | sort -u); do
        if printf '%s' "$name" | grep -Eq "$SUITE_KNOB_PATTERN"; then continue; fi
        unset_args="$unset_args -u $name"
    done
    # shellcheck disable=SC2086
    env $unset_args "$@"
}
if [ "$skip_tests" -eq 1 ]; then
    echo "release: !! skipping the local suites at your explicit request (--skip-tests)."
    echo "release: !! the gate is then CI green on the tip being tagged ($(git rev-parse --short HEAD)): read it before this tags, and name the run in the notes."
else
    served_env=()
    if [ -d vscode-extension/node_modules ]; then
        # CI's extension job order: the typecheck, the webview suite, the build, then the served labs
        # against the dist the build just wrote. Neither esbuild road checks types, so the typecheck is
        # its own step. Most served labs rebuild the shared dist themselves in setUpClass; the ones that
        # serve the checkout's dist as it stands get the tip's build from this step, and a build that
        # fails stops the release HERE, before the suite, instead of as a skip inside a lab (a lab whose
        # esbuild fails skips with the reason, and under the require flag below that skip is a failure an
        # hour into the run).
        say "typechecking the webview..."
        step sh -c 'cd vscode-extension && npm run typecheck' || die "the webview typecheck failed: NOT releasing."
        say "running the webview suite..."
        step sh -c 'cd vscode-extension && npm test' || die "the webview suite failed: NOT releasing."
        say "building the webview (the served labs serve this build)..."
        step sh -c 'cd vscode-extension && npm run build' || die "the webview build failed: NOT releasing."
        # The served labs run as CI runs them only where a browser can run them. Playwright's pinned
        # Chromium is TWO downloads: the full Chromium (the pane bench prefers it) and the headless shell
        # (what the labs' headless launch runs), so both must be here to require the labs: with the full
        # binary alone every lab is required and fails at launch after the whole Python run; with the
        # shell alone the labs run unrequired. Playwright's own listing says where each lives (its
        # install --dry-run, no network), and each directory carries INSTALLATION_COMPLETE once its
        # download finished. With both, a skip in a served lab (an absent dep, a kernel that never
        # served) is a failure carrying its reason, never a silent pass of this gate, and the engines
        # declared are the ones CI declares (chromium alone, unless the calling shell's
        # ROMP_SERVED_TESTS_ENGINES names others), so a leg
        # for an engine this box does not carry stays an optional skip instead of turning into a
        # failure. Without both the labs skip here and the line names what is missing; the remedy runs
        # from the extension directory, where npx resolves the PINNED playwright (in the repo root it
        # resolves whatever playwright is newest and installs a revision the pinned one never finds).
        # the pinned package's own cli, resolved by NAME from the extension directory (a nested node_modules layout
        # would make a fixed path read as "no browser"); its listing is one section per download, each headed
        # "(playwright <name> v<rev>)" with an Install location line under it
        pw_cli="$(cd vscode-extension && node -e "const p = require('path'); process.stdout.write(p.join(p.dirname(require.resolve('playwright-core/package.json')), 'cli.js'))" 2>/dev/null || true)"
        listing=""
        if [ -n "$pw_cli" ]; then listing="$(cd vscode-extension && node "$pw_cli" install --dry-run chromium 2>/dev/null || true)"; fi
        # the section's own Install location line, or nothing: the grab stops at the NEXT section header, so a section
        # that lost its line reads absent (the safe side) instead of returning the next download's directory
        pw_dir() { printf '%s\n' "$listing" | awk -v key="(playwright $1 v" 'grab && index($0, "(playwright ") { exit } index($0, key) { grab = 1; next } grab && /Install location:/ { sub(/.*Install location:[ \t]*/, ""); print; exit }'; }
        full_dir="$(pw_dir chromium)"; shell_dir="$(pw_dir chromium-headless-shell)"
        have_full=0; have_shell=0
        if [ -n "$full_dir" ] && [ -f "$full_dir/INSTALLATION_COMPLETE" ]; then have_full=1; fi
        if [ -n "$shell_dir" ] && [ -f "$shell_dir/INSTALLATION_COMPLETE" ]; then have_shell=1; fi
        remedy="cd vscode-extension && npx playwright install chromium"
        if [ "$have_full" -eq 1 ] && [ "$have_shell" -eq 1 ]; then
            served_env=(ROMP_SERVED_TESTS_REQUIRE=1 "ROMP_SERVED_TESTS_ENGINES=${ROMP_SERVED_TESTS_ENGINES:-chromium}")
        elif [ "$have_full" -eq 1 ]; then
            say "node deps present, a partial browser install (the full Chromium is here, the headless shell the labs launch is not; $remedy completes it): the served labs skip here; their gate is CI's extension job on the tip."
        elif [ "$have_shell" -eq 1 ]; then
            say "node deps present, a partial browser install (the headless shell is here, the full Chromium is not; $remedy completes it): the served labs skip here; their gate is CI's extension job on the tip."
        else
            say "node deps present, no browser ($remedy adds it): the served labs skip here; their gate is CI's extension job on the tip."
        fi
    else
        say "vscode-extension/node_modules is absent: skipping the webview suite and build (npm ci to include them);"
        say "the served labs skip here too, so their gate for this tag is CI's extension job on the tip."
    fi
    say "running the Python suite..."
    # Resolve a suite environment instead of assuming a system-wide pytest (the v0.13.0 run died
    # on a bare ModuleNotFoundError mid-release on a box with only a repo venv). Prefer a WORKING
    # ambient `python3 -m pytest`; else run through uv's throwaway env with CI's exact dep set
    # (pytest + cryptography — .github/workflows/ci.yml's install step: cryptography is the Web
    # Push soft dependency, without it the webpush tests silently skip); neither → die LOUDLY
    # naming both remedies BEFORE any release state is at stake.
    if [ -z "$PYTEST" ]; then
        if python3 -m pytest --version >/dev/null 2>&1; then
            PYTEST="python3 -m pytest"
        elif command -v uvx >/dev/null 2>&1; then
            say "no ambient pytest — running the suite through uv's throwaway env (pytest + cryptography, CI's dep set)"
            PYTEST="uvx --with pytest --with cryptography pytest"
        else
            die "no way to run the Python suite: python3 has no pytest and uv is not installed.
  Either:  curl -LsSf https://astral.sh/uv/install.sh | sh     (then re-run — the script provisions itself)
      or:  python3 -m pip install --upgrade pytest cryptography"
        fi
    fi
    # shellcheck disable=SC2086
    step scrubbed env ${served_env[@]+"${served_env[@]}"} $PYTEST tests/ -q || die "the Python suite failed: NOT releasing."
fi

# ── 5. the macOS gate ─────────────────────────────────────────────────
if [ "$skip_macos" -eq 1 ]; then
    echo "release: !! SKIPPING the macOS check at your explicit request (--skip-macos)."
    echo "release: !! a macOS-only breakage in $tag would reach users undetected."
elif [ "$dry_run" -eq 1 ]; then
    say "[dry-run] would dispatch the macOS CI run and wait for it."
else
    say "triggering the macOS CI run on $REF (it is dispatch-only, so this is the check)..."
    before="$("$GH" run list --workflow CI --event workflow_dispatch -L 1 --json databaseId -q '.[0].databaseId // ""' 2>/dev/null || true)"
    "$GH" workflow run CI --ref "$REF" || die "could not dispatch the CI workflow."

    # Identify OUR run by waiting for the newest dispatch run to differ from the one that was
    # newest before we dispatched — `gh workflow run` prints no run id, and taking the newest
    # unconditionally would happily watch a PREVIOUS run and pass the gate on a stale green.
    #
    # Each guard is a full `if`: under `set -e`, a bare `[ x ] && y` whose test is false makes
    # the whole list non-zero and kills the script.
    run_id=""
    for _ in $(seq 1 60); do
        if [ "$POLL" != "0" ]; then sleep "$POLL"; fi
        cur="$("$GH" run list --workflow CI --event workflow_dispatch -L 1 --json databaseId -q '.[0].databaseId // ""' 2>/dev/null || true)"
        if [ -n "$cur" ] && [ "$cur" != "$before" ]; then run_id="$cur"; break; fi
        if [ "$POLL" = "0" ]; then break; fi     # test mode: never spin
    done
    if [ -z "$run_id" ]; then
        die "the dispatched CI run never appeared — check the Actions tab."
    fi

    say "watching run $run_id (macOS bats is ~16 min; this is the wait you are paying for)..."
    # Poll `run view`, never `gh run watch`: watch holds one long connection and treats ANY
    # hiccup — a GitHub 502, a local socket error — as run failure. Twice (2026-07-27) it
    # declared a still-running, ultimately GREEN gate "did not pass". Here a transient API
    # error just yields an empty conclusion and we poll again; only the run's own verdict
    # ends the wait.
    conclusion=""
    while :; do
        conclusion="$("$GH" run view "$run_id" --json conclusion -q .conclusion 2>/dev/null || true)"
        if [ -n "$conclusion" ]; then break; fi
        if [ "$POLL" = "0" ]; then break; fi     # test mode: never spin
        sleep "$POLL"
    done
    if [ "$conclusion" != "success" ]; then
        die "the macOS run did not pass (conclusion: ${conclusion:-none}) — NOT tagging $tag.
  Fix it, or re-run with --skip-macos if you have decided to ship anyway."
    fi
    say "macOS run green."
fi

# ── 6. tag, push, publish ─────────────────────────────────────────────
# The previous release, for the notes range — computed BEFORE the new tag exists so it can
# never pick itself.
prev="$(git tag -l 'v*' --sort=-v:refname | head -n1 || true)"

step git tag -a "$tag" -m "romp $tag"
say "created tag $tag."

# The tag goes to the CANONICAL repo (`upstream` in a fork layout, else `origin`): rulesets
# block branch pushes there, but a tag is how a release is published, and a tag that lands
# only on the fork, or only locally, installs for nobody.
canonical="$(canonical_remote)"
step git push -q "$canonical" "$tag" || die "could not push $tag to $canonical."
say "pushed $tag."

# GitHub's generated notes list every merged pull request in the range, and its release body has a
# ceiling of 125000 characters: the v0.16.0 cut (2026-09-16) held about nine hundred pull requests,
# the API answered HTTP 422 "body is too long", and the tag was pushed with no release behind it.
# A cut never ends half-finished now: a range with more merged pull requests than
# ROMP_RELEASE_NOTES_MAX_PRS (500, well under the ceiling at GitHub's line lengths) goes straight to
# a short body, and a generated-notes attempt that fails for any reason falls back to the same
# short body: the range, the count and the compare view, where the full list lives.
notes_max="${ROMP_RELEASE_NOTES_MAX_PRS:-500}"
publish_short() {
    # $1 = the previous tag ('' when none); the short body names the range and the count
    local body
    if [ -n "$1" ]; then
        local n
        n="$(git rev-list --merges --first-parent --count "$1..$tag" 2>/dev/null || echo 0)"
        body="romp $tag

$n pull requests merged since $1. The full list: https://github.com/$UPSTREAM/compare/$1...$tag"
    else
        body="romp $tag

The first tagged release: https://github.com/$UPSTREAM/commits/$tag"
    fi
    step "$GH" release create "$tag" --repo "$UPSTREAM" --title "romp $tag" --notes "$body" \
        || die "$tag is pushed, but publishing the release failed — finish with:
  gh release create $tag --repo $UPSTREAM --title 'romp $tag' --notes '<a short body>'"
}
if [ -n "$prev" ]; then
    n_prs="$(git rev-list --merges --first-parent --count "$prev..$tag" 2>/dev/null || echo 0)"
    if [ "$n_prs" -gt "$notes_max" ]; then
        say "$n_prs pull requests since $prev, more than $notes_max: publishing with a short body (GitHub's generated notes would exceed its ceiling)."
        publish_short "$prev"
    elif ! step "$GH" release create "$tag" --repo "$UPSTREAM" --title "romp $tag" \
            --generate-notes --notes-start-tag "$prev"; then
        say "the generated notes were refused (a body over GitHub's ceiling, or a transient error): publishing with a short body instead."
        publish_short "$prev"
    fi
else
    if ! step "$GH" release create "$tag" --repo "$UPSTREAM" --title "romp $tag" --generate-notes; then
        say "the generated notes were refused: publishing with a short body instead."
        publish_short ""
    fi
fi
say "published. $tag is live — bootstrap.sh will install it."
