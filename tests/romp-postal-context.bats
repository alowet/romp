#!/usr/bin/env bats

# romp-postal-context.sh is a SessionStart hook: in a romp session (the @romp tmux
# flag) it emits a COMPACT pointer to the postal capability as additionalContext.
# The full norms live in the romp-postal skill (loaded on demand) + the postal MCP
# tools' own descriptions, so this pointer stays small and re-cheap every turn. It
# must be silent outside a romp session, and must never fail the turn.

setup() {
    TEST_DIR="$(mktemp -d)"
    export HOME="$TEST_DIR/home"; mkdir -p "$HOME"
    MOCK="$TEST_DIR/mock"; mkdir -p "$MOCK"
    # mock tmux: `tmux show -v @romp` prints $FAKE_ROMP
    cat > "$MOCK/tmux" <<'MOCK'
#!/usr/bin/env bash
[ "$1" = show ] && echo "${FAKE_ROMP:-}"
exit 0
MOCK
    chmod +x "$MOCK/tmux"
    export PATH="$MOCK:$PATH"
    HOOK="$(cd "$(dirname "$BATS_TEST_FILENAME")/../hooks" && pwd)/romp-postal-context.sh"
}

teardown() { rm -rf "$TEST_DIR"; }

@test "in a romp session it emits a compact postal pointer as additionalContext" {
    FAKE_ROMP=1 run bash -c 'echo "{}" | "'"$HOOK"'"'
    [ "$status" -eq 0 ]
    [[ "$output" == *'"additionalContext"'* ]]
    [[ "$output" == *'"hookEventName": "SessionStart"'* ]]
    [[ "$output" == *'postal MCP tools'* ]]
    # the declare-your-intent norm is present up front — as send_message's REQUIRED `kind` parameter, never
    # the retired DELEGATE:/COORDINATE:/QUESTION: body prefix the hook used to teach beside it (two
    # instructions for one fact). The negative pin is deliberate: the prefix must not come back.
    [[ "$output" == *'set `kind` to delegate, coordinate, or question'* ]]
    [[ "$output" != *'DELEGATE'* ]]
    [[ "$output" == *'list_agents'* ]]     # the coordinate-before-editing norm is present up front
    [[ "$output" == *'romp-postal skill'* ]]   # points to the full guide, not inlined
}

@test "outside a romp session it is silent" {
    FAKE_ROMP="" run bash -c 'echo "{}" | "'"$HOOK"'"'
    [ "$status" -eq 0 ]
    [ -z "$output" ]
}

@test "the pointer is self-contained (no dependence on the skill file) and never fails" {
    # the hook no longer reads SKILL.md; it emits the same pointer regardless, so a
    # missing skill file can't blank it or fail the turn.
    FAKE_ROMP=1 run bash -c 'echo "{}" | "'"$HOOK"'"'
    [ "$status" -eq 0 ]
    [[ "$output" == *'"additionalContext"'* ]]
}
