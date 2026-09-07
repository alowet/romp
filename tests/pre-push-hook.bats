#!/usr/bin/env bats

# .githooks/pre-push — the identifier scan, driven by hand against real commits.
#
# The hook refuses to publish a commit carrying a string from the machine's
# private-strings denylist. Every identifier below is SYNTHETIC (the repo may go
# public, and a real one written here would be the very leak the hook exists to
# stop): the denylist, the paths and the hostnames are all invented per test.
#
# Two rules, both about what a push changes on the remote: the TIP tree of each
# pushed ref must be clean (that is what a push exposes), and each commit the
# remote does not already have must ADD no banned line — a commit that only
# inherits an older leak in its tree is not refused, a commit that introduced
# one is, even if a later commit removed it again. install-sh.bats exercises the
# hook through a real `git push`; this file feeds it ref lines directly, so it
# can model a remote and its remote-tracking refs the way a clone has them.

ROMP_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
HOOK="$ROMP_DIR/.githooks/pre-push"

setup() {
    TEST_DIR="$(mktemp -d)"
    REPO="$TEST_DIR/repo"
    mkdir -p "$REPO"
    git -C "$REPO" init -q
    git -C "$REPO" symbolic-ref HEAD refs/heads/main     # whatever init.defaultBranch says
    git -C "$REPO" config user.email t@example.invalid
    git -C "$REPO" config user.name  Tester
    # The hook under test is run BY HAND below; the fixture's own git operations
    # (commits, pushes to the bare remote) must not run this machine's hooks.
    mkdir -p "$TEST_DIR/no-hooks"
    git -C "$REPO" config core.hooksPath "$TEST_DIR/no-hooks"

    # the denylist: invented identifiers, nothing that exists on any real box
    STRINGS="$TEST_DIR/private-strings.txt"
    printf '# synthetic\nzzsynthuser\nTESTHOST\n' > "$STRINGS"

    export ROMP_PRIVATE_STRINGS="$STRINGS"
}

teardown() { rm -rf "${TEST_DIR:-}"; }

ZERO=0000000000000000000000000000000000000000

# Run the hook from inside the repo, the way git does. bats' `run` executes the
# command in a subshell, so the cd here does not leak into the test. (A cd
# helper rather than `env -C`, which BSD env lacks.)
_hook_in() { cd "$1" && shift && bash "$@"; }

# Feed the hook a ref line the way git does: <local_ref> <sha> <remote_ref> <remote_sha>.
# The default remote sha of zero means a new branch, i.e. every commit here is
# being published; pass the sha the remote holds to model updating a branch it has.
run_hook() {
    local sha remote_sha="${1:-$ZERO}"
    sha="$(git -C "$REPO" rev-parse HEAD)"
    run _hook_in "$REPO" "$HOOK" origin git@example.invalid:x/y.git <<< \
        "refs/heads/main $sha refs/heads/main $remote_sha"
}

commit_file() {   # <path> <content> <message>
    printf '%s\n' "$2" > "$REPO/$1"
    git -C "$REPO" add "$1"
    git -C "$REPO" commit -qm "$3"
}

# A bare remote named origin, so refs/remotes/origin/* exist the way they do in a
# real clone: the hook decides what is "already on the remote" from those refs.
add_remote() {
    git init -q --bare "$TEST_DIR/remote.git"
    git -C "$REPO" remote add origin "$TEST_DIR/remote.git"
}

remove_file() {   # <path> <message>
    git -C "$REPO" rm -q "$1"
    git -C "$REPO" commit -qm "$2"
}

# main publishes an identifier (LEAK_SHA, pushed, so the remote has it); a branch
# is cut from there and commits work of its own, whose tree INHERITS the leak
# although its diff is clean. Leaves HEAD on the branch; main has not yet redacted.
branch_inheriting_mains_leak() {
    add_remote
    commit_file base.txt "notes-api" "base"
    commit_file leak.txt "home is /home/zzsynthuser/code" "leak"
    LEAK_SHA="$(git -C "$REPO" rev-parse HEAD)"
    git -C "$REPO" push -q origin main
    git -C "$REPO" checkout -q -b feature
    commit_file web.txt "the web session's work" "branch work"
}

# ...and main redacts the leak (pushed), and the branch merges main: its own
# earlier commit still has the leaky tree, but its tip is clean.
main_redacts_and_branch_merges() {
    git -C "$REPO" checkout -q main
    remove_file leak.txt "redact"
    git -C "$REPO" push -q origin main
    git -C "$REPO" checkout -q feature
    git -C "$REPO" merge -q -m "merge main" main
}

@test "a clean commit passes" {
    commit_file file.txt "nothing to see" "clean"
    run_hook
    [ "$status" -eq 0 ]
}

@test "an identifier in a regular file is blocked" {
    commit_file file.txt "home is /home/zzsynthuser/code" "leak"
    run_hook
    [ "$status" -ne 0 ]
    [[ "$output" == *"personal identifier"* ]]
}

@test "an identifier in an INTERMEDIATE commit is caught, not just the tip" {
    commit_file bad.txt "home is /home/zzsynthuser/x" "leak"
    leak_sha="$(git -C "$REPO" rev-parse HEAD)"
    remove_file bad.txt "remove it"               # tip is clean; history is not
    run_hook
    [ "$status" -ne 0 ]
    [[ "$output" == *"commit ${leak_sha:0:10} ADDS a personal identifier"* ]]
    [[ "$output" == *"  bad.txt"* ]]
}

@test "an added line shaped like a diff header is content, not a new path" {
    # In a patch, content `++ b/decoy.txt` renders as `+++ b/decoy.txt`, the same
    # text as a file header. Only a header names the path the next hit belongs to.
    printf '%s\n' '++ b/decoy.txt' 'home is /home/zzsynthuser/x' > "$REPO/real.txt"
    git -C "$REPO" add real.txt
    git -C "$REPO" commit -qm "leak"
    leak_sha="$(git -C "$REPO" rev-parse HEAD)"
    remove_file real.txt "remove it"              # tip is clean, so the added-lines pass decides
    run_hook
    [ "$status" -ne 0 ]
    [[ "$output" == *"commit ${leak_sha:0:10} ADDS a personal identifier"* ]]
    [[ "$output" == *"  real.txt"* ]]
    [[ "$output" != *"decoy.txt"* ]]
}

@test "no denylist file means no identifier scan (a fresh clone is unaffected)" {
    export ROMP_PRIVATE_STRINGS="$TEST_DIR/does-not-exist.txt"
    commit_file bad.txt "home is /home/zzsynthuser/x" "leak"
    run_hook
    [ "$status" -eq 0 ]
}

# ── which commits a push publishes ────────────────────────────────────────
# A leak already on the remote is fixed forward on main, not by refusing every
# branch cut since: the tip tree must be clean, and only commits the remote lacks
# are read, for the lines they ADD.

@test "a branch that only INHERITED main's leak in its tree passes once its tip merged the redaction" {
    branch_inheriting_mains_leak
    main_redacts_and_branch_merges
    run_hook                                    # new ref: range = the branch commit + the merge
    [ "$status" -eq 0 ]
}

@test "the same branch is refused while its TIP still carries the inherited leak" {
    branch_inheriting_mains_leak
    run_hook
    [ "$status" -ne 0 ]
    [[ "$output" == *"the tip of refs/heads/main"* ]]   # named as the tip, not as an introduction
    [[ "$output" == *"leak.txt"* ]]
    [[ "$output" != *"ADDS"* ]]
    [[ "$output" == *"merge main"* ]]                   # the remedy is spelled out
}

@test "a leak ADDED by a branch commit and removed by a later one is refused, naming the commit" {
    commit_file base.txt "notes-api" "base"
    commit_file leak.txt "home is /home/zzsynthuser/code" "leak"
    leak_sha="$(git -C "$REPO" rev-parse HEAD)"
    remove_file leak.txt "redact"
    run_hook
    [ "$status" -ne 0 ]
    [[ "$output" == *"commit ${leak_sha:0:10} ADDS a personal identifier"* ]]
    [[ "$output" == *"leak.txt"* ]]
}

@test "an identifier in the branch's OWN new commit is still refused after merging main" {
    branch_inheriting_mains_leak
    main_redacts_and_branch_merges
    commit_file api.txt "home is /home/zzsynthuser/api" "branch leak"
    run_hook
    [ "$status" -ne 0 ]
    [[ "$output" == *"ADDS a personal identifier"* ]]
    [[ "$output" == *"api.txt"* ]]
    [[ "$output" != *"leak.txt"* ]]       # main's commits were skipped, not re-flagged
}

@test "a commit only ANOTHER remote has is still new to this one" {
    # --not --remotes (every remote) would have excused this; the exclusion is per remote
    commit_file leak.txt "home is /home/zzsynthuser/code" "leak"
    leak_sha="$(git -C "$REPO" rev-parse HEAD)"
    remove_file leak.txt "redact"                # tip is clean
    git -C "$REPO" update-ref refs/remotes/elsewhere/main HEAD
    run_hook
    [ "$status" -ne 0 ]
    [[ "$output" == *"commit ${leak_sha:0:10} ADDS"* ]]
}

@test "with no remote-tracking refs, the same rule covers everything the remote ref lacks (the fallback)" {
    commit_file base.txt "notes-api" "base"
    remote_sha="$(git -C "$REPO" rev-parse HEAD)"
    commit_file leak.txt "home is /home/zzsynthuser/code" "leak"
    leak_sha="$(git -C "$REPO" rev-parse HEAD)"
    remove_file leak.txt "redact"
    commit_file web.txt "the web session's work" "more work"   # tip is clean; the range is not
    run_hook "$remote_sha"
    [ "$status" -ne 0 ]
    [[ "$output" == *"commit ${leak_sha:0:10} ADDS"* ]]
}
