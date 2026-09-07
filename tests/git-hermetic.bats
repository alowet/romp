#!/usr/bin/env bats

# tests/git-hermetic.bash: after git_hermetic, git reads no global or system config and every
# commit has an identity, whatever the box is configured with.
#
# Skips on git < 2.32 with the same message as tests/test_tempdir_hygiene.GitFloor: GIT_CONFIG_GLOBAL
# and GIT_CONFIG_SYSTEM arrived in 2.32, so on an older git the config half of the floor is inert
# (the identity half still holds) and both proofs say so the same way instead of one going red.

load git-hermetic

git_at_least_2_32() {
    local v
    v="$(git --version | awk '{print $3}')"
    local major="${v%%.*}" rest="${v#*.}"
    local minor="${rest%%.*}"
    [ "$major" -gt 2 ] 2>/dev/null || { [ "$major" -eq 2 ] && [ "$minor" -ge 32 ]; } 2>/dev/null
}

setup() {
    git_at_least_2_32 || skip "GIT_CONFIG_GLOBAL needs git >= 2.32"
    TEST_DIR="$(mktemp -d)"
    # A stand-in for the developer's global config: a hooks directory whose pre-commit refuses
    # every commit and leaves a marker, wired in through core.hooksPath.
    export HOME="$TEST_DIR/home"
    mkdir -p "$HOME" "$TEST_DIR/hooks"
    printf '#!/bin/sh\necho ran > "%s/hook-ran"\nexit 1\n' "$TEST_DIR" > "$TEST_DIR/hooks/pre-commit"
    chmod +x "$TEST_DIR/hooks/pre-commit"
    printf '[core]\n\thooksPath = %s\n[user]\n\tname = Global Person\n\temail = global@example.invalid\n' \
        "$TEST_DIR/hooks" > "$HOME/.gitconfig"
    unset GIT_CONFIG_GLOBAL GIT_CONFIG_NOSYSTEM XDG_CONFIG_HOME
    unset GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL
    REPO="$TEST_DIR/repo"
    git init -q "$REPO"
    echo a > "$REPO/a.txt"
    git -C "$REPO" add a.txt
}

teardown() { rm -rf "${TEST_DIR:-}"; }

@test "the probe is live: without git_hermetic the global hooksPath blocks the commit" {
    run git -C "$REPO" commit -qm seed
    [ "$status" -ne 0 ]
    [ -f "$TEST_DIR/hook-ran" ]
}

@test "with git_hermetic the global hook never runs and the commit lands" {
    git_hermetic
    run git -C "$REPO" commit -qm seed
    [ "$status" -eq 0 ]
    [ ! -e "$TEST_DIR/hook-ran" ]
    [ "$(git -C "$REPO" config --global --get core.hooksPath || true)" = "" ]
}

@test "with git_hermetic a system-config hooksPath never runs either" {
    # The system half of the floor: GIT_CONFIG_SYSTEM (git >= 2.32) is a root-free stand-in for
    # /etc/gitconfig, and GIT_CONFIG_NOSYSTEM=1 is what hides it; the global probe above says
    # nothing about it. The file carries an identity because git resolves the author before it
    # runs pre-commit, and the live arm has none from the environment or a global config (the
    # global file is hidden there so the system file is the ONLY source of the hook).
    printf '[core]\n\thooksPath = %s\n[user]\n\tname = System Person\n\temail = system@example.invalid\n' \
        "$TEST_DIR/hooks" > "$TEST_DIR/sysconfig"
    export GIT_CONFIG_SYSTEM="$TEST_DIR/sysconfig"
    run env GIT_CONFIG_GLOBAL=/dev/null git -C "$REPO" commit -qm seed
    [ "$status" -ne 0 ]
    [ -f "$TEST_DIR/hook-ran" ]
    rm "$TEST_DIR/hook-ran"
    git_hermetic
    run git -C "$REPO" commit -qm seed
    [ "$status" -eq 0 ]
    [ ! -e "$TEST_DIR/hook-ran" ]
}

@test "the identity is the synthetic one, not the global config's" {
    git_hermetic
    git -C "$REPO" commit -qm seed
    [ "$(git -C "$REPO" log -1 --format='%an <%ae>')" = "romp tests <tests@example.invalid>" ]
    [ "$(git -C "$REPO" log -1 --format='%cn <%ce>')" = "romp tests <tests@example.invalid>" ]
}

@test "a test's own identity exports after git_hermetic still win" {
    git_hermetic
    # The env identity outranks `git config user.*` and `-c user.*`, so a test that must pin a
    # particular author exports its own GIT_AUTHOR_* / GIT_COMMITTER_* after git_hermetic.
    GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@e.invalid git -C "$REPO" commit -qm seed
    [ "$(git -C "$REPO" log -1 --format='%an <%ae>')" = "t <t@e.invalid>" ]
}
