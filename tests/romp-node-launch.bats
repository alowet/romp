#!/usr/bin/env bats

# romp-node-launch execs romp-manager under a romp-OWNED copy of node ("romp-node")
# so macOS Full Disk Access is scoped to romp alone, not the shared "node" every
# script inherits (see the script's header for the TCC rationale). These exercise
# the copy/refresh behavior and the exec target with fake node + manager stand-ins.

setup() {
    TEST_DIR="$(mktemp -d)"
    LAUNCH="$(cd "$(dirname "$BATS_TEST_FILENAME")/../bin" && pwd)/romp-node-launch"
    export HOME="$TEST_DIR/home"
    export XDG_STATE_HOME="$HOME/.local/state"
    # The launcher honors both; a developer shell exporting them would point every
    # case here at a real service.env or state dir.
    unset ROMP_SERVICE_ENV_FILE ROMP_STATE_DIR
    BIN="$TEST_DIR/bin"
    mkdir -p "$HOME" "$BIN"
    # Fake manager: just a marker file. It is never run directly — the fake node
    # (below) is what "runs" it, and it echoes the argv it was handed so the test
    # can see the manager path + args the launcher exec'd the copy with.
    MANAGER="$TEST_DIR/romp-manager"
    printf 'placeholder manager\n' > "$MANAGER"
    # Fake `node` (v1) first on PATH, so the launcher copies THIS, not the real
    # system node. Echoes a version marker + its args.
    printf '#!/bin/sh\necho "NODE_V1 ran: $*"\n' > "$BIN/node"
    chmod +x "$BIN/node"
    export PATH="$BIN:$PATH"
    RN="$XDG_STATE_HOME/romp/romp-node"
}

teardown() { rm -rf "$TEST_DIR"; }

@test "creates a romp-node copy of the system node and execs the manager under it" {
    run "$LAUNCH" "$MANAGER" up
    [ "$status" -eq 0 ]
    # The copy exists and is a byte-for-byte copy of the system node.
    [ -x "$RN" ]
    cmp -s "$BIN/node" "$RN"
    # It was the COPY (romp-node) that ran the manager, with our args.
    [[ "$output" == *"NODE_V1 ran: $MANAGER up"* ]]
}

@test "refreshes the copy when the system node changes (a node upgrade)" {
    "$LAUNCH" "$MANAGER" up >/dev/null
    cmp -s "$BIN/node" "$RN"
    # Simulate a node upgrade: different bytes at the same PATH entry.
    printf '#!/bin/sh\necho "NODE_V2 ran: $*"\n' > "$BIN/node"
    chmod +x "$BIN/node"
    run "$LAUNCH" "$MANAGER" up
    [ "$status" -eq 0 ]
    cmp -s "$BIN/node" "$RN"                       # copy now matches the NEW node
    [[ "$output" == *"NODE_V2 ran: $MANAGER up"* ]]
}

@test "a failed refresh never blocks startup — falls back to the existing copy" {
    if [ "$(id -u)" -eq 0 ]; then skip "unwritable-dir check needs a non-root user"; fi
    "$LAUNCH" "$MANAGER" up >/dev/null              # seed the copy (v1)
    [ -x "$RN" ]
    chmod 555 "$XDG_STATE_HOME/romp"               # block the refresh write
    printf '#!/bin/sh\necho "NODE_V2 ran: $*"\n' > "$BIN/node"   # node changed → refresh WOULD fire
    chmod +x "$BIN/node"
    run "$LAUNCH" "$MANAGER" up
    chmod 755 "$XDG_STATE_HOME/romp"               # restore for teardown
    [ "$status" -eq 0 ]
    [[ "$output" == *"NODE_V1 ran: $MANAGER up"* ]] # ran via the kept v1 copy, not aborted
}

@test "service.env: KEY=VALUE lines reach the manager; comments and junk skipped" {
    # Parity with the systemd unit's EnvironmentFile=- : the launcher parses
    # (never sources) ~/.config/romp/service.env before exec'ing the manager.
    export XDG_CONFIG_HOME="$HOME/.config"
    mkdir -p "$XDG_CONFIG_HOME/romp"
    {
        echo '# comment'
        echo 'ROMP_TEST_SECRET=hunter2'
        echo ''
        echo 'not a valid line'
    } > "$XDG_CONFIG_HOME/romp/service.env"
    # Fake node prints the env var the launcher should have exported.
    printf '#!/bin/sh\necho "SECRET=[$ROMP_TEST_SECRET] ran: $*"\n' > "$BIN/node"
    chmod +x "$BIN/node"
    run "$LAUNCH" "$MANAGER" up
    [ "$status" -eq 0 ]
    [[ "$output" == *"SECRET=[hunter2] ran: $MANAGER up"* ]]
}

@test "service.env: one layer of matching quotes comes off the value and whitespace around it is dropped; edge cases follow the kernel's reader" {
    # Every reader of this file strips one layer of matching quotes and discards
    # whitespace around the value (a trailing space after the closing quote, a CRLF
    # line ending): systemd's EnvironmentFile=, the kernel's own reader
    # (kernel/keysource.py _assignments) and this launcher. Without that a quoted
    # value means one thing on Linux and another on macOS. The edge cases follow
    # the kernel's reader, not systemd, which parses a value like a shell (pieces
    # concatenate, an unbalanced quote runs on to the next line): an unbalanced
    # quote is left as written; quotes inside a value are part of the value; an
    # empty quoted value is empty; exactly one layer comes off, so a nested pair
    # keeps its inner quotes; the pair must match, so "abc' is left as written; a
    # value holding the other quote character keeps it.
    export XDG_CONFIG_HOME="$HOME/.config"
    mkdir -p "$XDG_CONFIG_HOME/romp"
    {
        echo 'ROMP_TEST_DQ="two words"'
        echo "ROMP_TEST_SQ='x y'"
        echo 'ROMP_TEST_ONE="abc'
        echo 'ROMP_TEST_EMPTY=""'
        echo 'ROMP_TEST_INNER=a"b"c'
        echo "ROMP_TEST_NESTED=\"'q'\""
        echo 'ROMP_TEST_TWO=""a""'
        echo "ROMP_TEST_MIX=\"abc'"
        echo "ROMP_TEST_APOS=\"it's\""
        printf 'ROMP_TEST_TSP="a b" \n'          # trailing space after the closing quote
        printf 'ROMP_TEST_CRLF="c d"\r\n'        # a CRLF line ending on a quoted value
        printf 'ROMP_TEST_BARECR=plain\r\n'      # and on an unquoted one
    } > "$XDG_CONFIG_HOME/romp/service.env"
    printf '#!/bin/sh\necho "DQ=[$ROMP_TEST_DQ] SQ=[$ROMP_TEST_SQ] ONE=[$ROMP_TEST_ONE] EMPTY=[${ROMP_TEST_EMPTY-unset}] INNER=[$ROMP_TEST_INNER] NESTED=[$ROMP_TEST_NESTED] TWO=[$ROMP_TEST_TWO] MIX=[$ROMP_TEST_MIX] APOS=[$ROMP_TEST_APOS] TSP=[$ROMP_TEST_TSP] CRLF=[$ROMP_TEST_CRLF] BARECR=[$ROMP_TEST_BARECR]"\n' > "$BIN/node"
    chmod +x "$BIN/node"
    run "$LAUNCH" "$MANAGER" up
    [ "$status" -eq 0 ]
    want="DQ=[two words] SQ=[x y] ONE=[\"abc] EMPTY=[] INNER=[a\"b\"c] NESTED=['q'] TWO=[\"a\"] MIX=[\"abc'] APOS=[it's] TSP=[a b] CRLF=[c d] BARECR=[plain]"
    [[ "$output" == *"$want"* ]]
}
