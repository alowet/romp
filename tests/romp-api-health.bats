#!/usr/bin/env bats

# `romp api-health` — the kernel's API-health signal for scripts: GET /api-health, printed verbatim.
# Same contract as `romp sessions`: the kernel owns the state, the token travels on stdin (never
# argv), a dead kernel fails LOUDLY rather than printing something a consumer could mistake for a
# healthy signal, and an unknown flag is refused.

ROMP_SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../bin" && pwd)/romp"

setup() {
    TEST_DIR="$(mktemp -d)"
    export XDG_STATE_HOME="$TEST_DIR/state"
    mkdir -p "$XDG_STATE_HOME/romp"
    printf 'TESTTOKEN123\n' > "$XDG_STATE_HOME/romp/serve-token"
    export ROMP_KERNEL_PORT=29855

    # Stub curl: records argv AND stdin (the auth header rides stdin as a curl config), replies
    # with a synthetic signal. Nothing touches a real kernel.
    MOCK="$TEST_DIR/mock"; mkdir -p "$MOCK"
    export CURL_LOG="$TEST_DIR/curl.log"
    export CURL_STDIN="$TEST_DIR/curl.stdin"
    export SIGNAL_JSON="$TEST_DIR/signal.json"
    cat > "$SIGNAL_JSON" <<'JSON'
{"schema": 1, "asOf": 1756800000.4, "bootId": "4242.1756790000", "rate429Basis": "attempts",
 "coverage": {"sidechainExcluded": true, "sdkSessionsLive": 2, "inTurn": 1, "retrying": 1, "tmuxSessionsUncovered": 0},
 "overall": {"state": "thrashing", "worstBucket": "key:0123456789ab|fable"},
 "buckets": {"key:0123456789ab|fable": {"state": "thrashing",
   "windows": {"300": {"requests": 20, "rateLimited": 8, "rate429": 0.4}}}}}
JSON
    cat > "$MOCK/curl" <<'MOCK'
#!/usr/bin/env bash
echo "$*" >> "$CURL_LOG"
cat >> "$CURL_STDIN" 2>/dev/null
[ -n "${CURL_FAIL:-}" ] && exit 22
cat "$SIGNAL_JSON"
MOCK
    chmod +x "$MOCK/curl"
    export PATH="$MOCK:$PATH"
}

teardown() { rm -rf "$TEST_DIR"; }

@test "romp api-health: prints the kernel's signal verbatim" {
    run "$ROMP_SCRIPT" api-health
    [ "$status" -eq 0 ]
    [[ "$output" == *'"thrashing"'* ]]
    echo "$output" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["overall"]["state"] == "thrashing"; assert d["coverage"]["sidechainExcluded"] is True'
}

@test "romp api-health: reads GET /api-health on the kernel, authorizing on stdin" {
    run "$ROMP_SCRIPT" api-health
    [ "$status" -eq 0 ]
    grep -q "127.0.0.1:29855/api-health" "$CURL_LOG"
    grep -q "X-Romp-Token: TESTTOKEN123" "$CURL_STDIN"
    # never in argv: /proc/<pid>/cmdline is world-readable
    run grep -q "TESTTOKEN123" "$CURL_LOG"
    [ "$status" -ne 0 ]
}

@test "romp api-health: a dead kernel fails LOUDLY, never a blank a consumer reads as healthy" {
    CURL_FAIL=1 run "$ROMP_SCRIPT" api-health
    [ "$status" -ne 0 ]
    [[ "$output" == *"kernel not reachable"* ]]
}

@test "romp api-health: an unknown flag is refused rather than silently ignored" {
    run "$ROMP_SCRIPT" api-health --nope
    [ "$status" -eq 2 ]
    [[ "$output" == *"usage: romp api-health"* ]]
}

@test "romp api-health: listed in help, under the scripting group" {
    run "$ROMP_SCRIPT" help
    [ "$status" -eq 0 ]
    [[ "$output" == *"romp api-health"* ]]
}
