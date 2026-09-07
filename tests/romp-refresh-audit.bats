#!/usr/bin/env bats
# `romp refresh --quiet` writes an audit row the kernel's drift check can read (T240d): when=quiet and
# the checkout sha. Without them the check saw the checkout ahead of the kernel, read a row that
# named no parked deploy, and posted an IMMEDIATE restart that pre-empted the quiet window this very
# flag asked for. The immediate refresh keeps its row as it was. Fake manager + postal stand-ins.

setup() {
    TEST_DIR="$(mktemp -d)"
    export ROMP_STATE_DIR="$TEST_DIR/state"
    mkdir -p "$TEST_DIR/bin"
    printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "%s/manager-calls"\n' "$TEST_DIR" > "$TEST_DIR/bin/romp-manager"
    printf '#!/usr/bin/env bash\nexit 0\n' > "$TEST_DIR/bin/romp-postal-service"
    chmod +x "$TEST_DIR/bin/romp-manager" "$TEST_DIR/bin/romp-postal-service"
    export ROMP_MANAGER_BIN="$TEST_DIR/bin/romp-manager"
    export ROMP_POSTAL_BIN="$TEST_DIR/bin/romp-postal-service"
    ROMP="$BATS_TEST_DIRNAME/../bin/romp"
}

teardown() { rm -rf "$TEST_DIR"; }

@test "romp refresh --quiet: the audit row says when=quiet and names the checkout sha" {
    run "$ROMP" refresh --quiet
    [ "$status" -eq 0 ]
    grep -qx 'restart-all --quiet' "$TEST_DIR/manager-calls"
    python3 - "$ROMP_STATE_DIR/restart-audit.jsonl" <<'EOF'
import json, re, sys
row = [json.loads(l) for l in open(sys.argv[1]) if l.strip()][-1]
assert row.get("when") == "quiet", row
assert re.fullmatch(r"[0-9a-f]{8}", row.get("sha") or ""), row
assert "action" not in row, row          # still the caller-attribution row, not a kernel action row
EOF
}

@test "romp refresh (immediate): the audit row carries neither when nor sha" {
    run "$ROMP" refresh
    [ "$status" -eq 0 ]
    grep -q '^restart-all' "$TEST_DIR/manager-calls"
    python3 - "$ROMP_STATE_DIR/restart-audit.jsonl" <<'EOF'
import json, sys
row = [json.loads(l) for l in open(sys.argv[1]) if l.strip()][-1]
assert "when" not in row and "sha" not in row, row
EOF
}
