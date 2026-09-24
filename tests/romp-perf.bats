#!/usr/bin/env bats

# `romp perf [--interval <s>] [--json]` and `romp perf log on|off` — the kernel's performance counters
# for a terminal: two GET /perf snapshots printed as rates, one raw snapshot, or the POST that flips the
# romp-perf stderr log without a restart.
#
# Same contract as `romp sessions`: the token travels on stdin (never argv), a dead kernel fails
# LOUDLY rather than printing something a reader could mistake for a quiet kernel, and an unknown
# flag is refused. Two more refusals are this verb's own: two snapshots from different kernel
# processes (a restart inside the window) are not subtracted into negative rates, and a refused
# token is named as such rather than reported as a dead kernel. Nothing here touches a real kernel:
# curl is a stub that serves synthetic snapshots in turn and emits the status trailer the real one
# is asked for (-w).

ROMP_SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../bin" && pwd)/romp"

setup() {
    # bin/romp resolves the state directory as ${ROMP_STATE_DIR:-$XDG_STATE_HOME/romp} and the token as
    # ${ROMP_SERVE_TOKEN:-<state>/serve-token}: a live kernel's exports outrank the redirection below
    unset ROMP_STATE_DIR ROMP_SERVE_TOKEN
    TEST_DIR="$(mktemp -d)"
    export XDG_STATE_HOME="$TEST_DIR/state"
    mkdir -p "$XDG_STATE_HOME/romp"
    printf 'TESTTOKEN123\n' > "$XDG_STATE_HOME/romp/serve-token"
    export ROMP_KERNEL_PORT=29855

    MOCK="$TEST_DIR/mock"; mkdir -p "$MOCK"
    export CURL_LOG="$TEST_DIR/curl.log"
    export CURL_STDIN="$TEST_DIR/curl.stdin"
    export CURL_CALLS="$TEST_DIR/curl.calls"
    export SNAP_A="$TEST_DIR/a.json"
    export SNAP_B="$TEST_DIR/b.json"
    export SNAP_C="$TEST_DIR/c.json"
    export SNAP_S="$TEST_DIR/s.json"
    export SNAP_OLD="$TEST_DIR/old.json"
    # A and B: the same kernel process ten seconds apart. Over the window: 20 cycles, 60 wakes, 6 s of
    # cycle time (4 s of it in push, 3 s of that in the chat block), 300 ms of pusher CPU and 50 ms of
    # judge CPU inside 500 ms of process CPU, 2 chat rebuilds (one of the watched tab, one of a background
    # tab whose store component moved) against 18 cache hits, 3 builds not cached because an input moved
    # while they ran, 1 MB sent as chat
    # full frames, one GET /feed.json build (150 ms) against 4 of its cache hits, 100 goal loads, 2 judge
    # passes totalling 2400 ms, 5 /tick requests and 3 WebSocket connects. B's lifetime figures (cycle_ms_max 900, ms_mean 1012.5) differ from the window's
    # (ring max 700, mean 1200) so a line printing the wrong one is caught. The kernel's parse store: 6 misses (5 folds and
    # 1 whole parse of a 20 MB leaf), 8 hits, and 2 misses by the judges.
    cat > "$SNAP_A" <<'JSON'
{"now": 1000.0, "since": 900.0, "uptime_s": 100.0, "log": false,
 "process": {"rss_kb": 409600, "threads": 40, "cpu_s": 60.0, "pid": 4242},
 "pusher": {"cycles": 100, "wakes": 300, "wakes_event": 250, "wakes_backstop": 50, "cycle_ms_sum": 30000.0,
            "cycle_ms_max": 900.0, "cycle_ms_last": 200.0, "cycle_cpu_ms_sum": 10000.0,
            "cycle_ms_p50": 180.0, "cycle_ms_p90": 400.0, "cycle_ms_ring_max": 900.0, "ring_n": 100},
 "stages_ms": {"jobs": 5000.0, "push": 20000.0, "push.chat": 15000.0, "push.feed": 3000.0, "push.timeline": 1000.0, "push.send": 500.0},
 "builds": {"chat": {"cached": 80, "built": 20, "ms": 800.0, "active_built": 12, "bg_built": 8, "moved": 0, "bg_miss": {"transcript": 5, "states": 2, "store": 1, "tasks": 0, "cut": 0, "row": 0, "cold": 1, "nosig": 0}}, "feed": {"cached": 90, "built": 10, "ms": 5000.0}, "timeline": {"cached": 95, "built": 5, "ms": 4000.0}, "feedJson": {"cached": 5, "built": 1, "ms": 300.0}},
 "sends": {"full": {"chat": {"count": 10, "bytes": 1000000}}, "delta": {"chat": {"count": 100, "bytes": 50000}}, "deduped": {"feed": {"count": 90, "bytes": 9000000}}},
 "goals": {"loads": 1000, "saves": 200, "writes": 50},
 "judge": {"passes": 30, "ms_sum": 30000.0, "ms_last": 1000.0, "ms_mean": 1000.0, "cpu_ms_sum": 2000.0, "cpu_ms_workers": 1500.0},
 "parses": {"kernel": 10, "hits": 50, "wholeBytes": 2097152, "byRoad": {"serve": 2, "fold": 5, "restore": 1, "full": 2, "bypass": 0, "fallback": 0},
            "bySid": {}, "total": 14, "judge": 4, "sharedHits": 60},
 "http": {"GET /tick": {"count": 50, "ms": 25.0}, "GET /sessions": {"count": 5, "ms": 10.0}}}
JSON
    cat > "$SNAP_B" <<'JSON'
{"now": 1010.0, "since": 900.0, "uptime_s": 110.0, "log": false,
 "process": {"rss_kb": 419840, "threads": 41, "cpu_s": 60.5, "pid": 4242},
 "pusher": {"cycles": 120, "wakes": 360, "wakes_event": 300, "wakes_backstop": 60, "cycle_ms_sum": 36000.0,
            "cycle_ms_max": 900.0, "cycle_ms_last": 250.0, "cycle_cpu_ms_sum": 10300.0,
            "cycle_ms_p50": 190.0, "cycle_ms_p90": 420.0, "cycle_ms_ring_max": 700.0, "ring_n": 120},
 "stages_ms": {"jobs": 6000.0, "push": 24000.0, "push.chat": 18000.0, "push.feed": 3600.0, "push.timeline": 1200.0, "push.send": 600.0},
 "builds": {"chat": {"cached": 98, "built": 22, "ms": 880.0, "active_built": 13, "bg_built": 9, "moved": 3, "bg_miss": {"transcript": 5, "states": 2, "store": 2, "tasks": 0, "cut": 0, "row": 0, "cold": 1, "nosig": 0}}, "feed": {"cached": 108, "built": 12, "ms": 6000.0}, "timeline": {"cached": 114, "built": 6, "ms": 4800.0}, "feedJson": {"cached": 9, "built": 2, "ms": 450.0}},
 "sends": {"full": {"chat": {"count": 12, "bytes": 2048576}}, "delta": {"chat": {"count": 120, "bytes": 60000}}, "deduped": {"feed": {"count": 108, "bytes": 10800000}}},
 "goals": {"loads": 1100, "saves": 220, "writes": 55},
 "judge": {"passes": 32, "ms_sum": 32400.0, "ms_last": 1200.0, "ms_mean": 1012.5, "cpu_ms_sum": 2050.0, "cpu_ms_workers": 1540.0},
 "parses": {"kernel": 16, "hits": 58, "wholeBytes": 23068672, "byRoad": {"serve": 2, "fold": 10, "restore": 1, "full": 3, "bypass": 0, "fallback": 0},
            "bySid": {}, "total": 22, "judge": 6, "sharedHits": 70},
 "http": {"GET /tick": {"count": 55, "ms": 27.5}, "GET /sessions": {"count": 5, "ms": 10.0}, "GET /ws": {"count": 3, "ms": 0.0}}}
JSON
    # C: a kernel that restarted five seconds into the window — new pid, new `since`, counters reset
    sed -e 's/"since": 900.0/"since": 1005.0/' -e 's/"uptime_s": 110.0/"uptime_s": 5.0/' \
        -e 's/"pid": 4242/"pid": 4343/' -e 's/"cycles": 120/"cycles": 4/' "$SNAP_B" > "$SNAP_C"
    # Stub curl: records argv AND stdin (the auth header rides stdin as a curl config) and emits the
    # body followed by the -w status trailer the script asks for. A POST answers the toggle's ack; a
    # GET serves snapshot A first, then B (or C under CURL_RESTART), so two reads see counters move.
    # S: a snapshot with the thread-stack sample (GET /perf?stacks=1): the pusher inside the nudge job waiting on a
    # lock, a handler thread answering, a producer idle; frames innermost last
    cat > "$SNAP_S" <<'JSON'
{"now": 1000.0, "since": 900.0, "uptime_s": 100.0, "log": false,
 "process": {"rss_kb": 409600, "threads": 3, "cpu_s": 60.0, "pid": 4242},
 "stacks": {
  "11 pusher": {"self": false, "stage": "jobs.autoNudge",
   "frames": ["_pusher (kernel.py:100)", "_job_stage (kernel.py:200)", "_auto_nudge_session (kernel.py:300)", "parse_session (event_model.py:400)", "__enter__ (threading.py:500)"]},
  "12 producer": {"self": false, "stage": null, "frames": ["_producer (kernel.py:600)", "wait (threading.py:700)"]},
  "13 handler": {"self": true, "stage": null, "frames": ["do_GET (kernel.py:800)", "_thread_stacks (kernel.py:900)"]}}}
JSON
    # OLD: the switch's shape before the sample (T358): ident and name to a list of format_stack lines; well-formed JSON, so
    # the dict guard alone does not refuse it and the per-row frames check must
    cat > "$SNAP_OLD" <<'JSON'
{"now": 1000.0, "process": {"pid": 4242},
 "stacks": {"11 pusher": ["  File \"kernel.py\", line 100, in _pusher\n    _pusher_cycle()", "  File \"kernel.py\", line 200, in _pusher_cycle"]}}
JSON
    cat > "$MOCK/curl" <<'MOCK'
#!/usr/bin/env bash
echo "$*" >> "$CURL_LOG"
cat >> "$CURL_STDIN" 2>/dev/null
[ -n "${CURL_FAIL:-}" ] && exit 7
if [ -n "${CURL_403:-}" ]; then printf 'forbidden: token required\n403'; exit 0; fi
if [[ "$*" == *"-X POST"* ]]; then
    printf '{"ok": true, "log": %s}\n200' "$([[ "$*" == *'"log": true'* ]] && echo true || echo false)"
    exit 0
fi
if [[ "$*" == *"stacks=1"* ]]; then
    if [ -n "${CURL_OLD_KERNEL:-}" ]; then cat "$SNAP_A"
    elif [ -n "${CURL_OLD_SHAPE:-}" ]; then cat "$SNAP_OLD"
    else cat "$SNAP_S"; fi
    printf '\n200'; exit 0
fi
n=0; [ -f "$CURL_CALLS" ] && n="$(cat "$CURL_CALLS")"
echo $((n + 1)) > "$CURL_CALLS"
if [ "$n" -eq 0 ]; then cat "$SNAP_A"; elif [ -n "${CURL_RESTART:-}" ]; then cat "$SNAP_C"; else cat "$SNAP_B"; fi
printf '\n200'
MOCK
    chmod +x "$MOCK/curl"
    export PATH="$MOCK:$PATH"
}

teardown() { rm -rf "$TEST_DIR"; }

@test "romp perf: prints rates computed from two snapshots" {
    run "$ROMP_SCRIPT" perf --interval 0
    [ "$status" -eq 0 ]
    [[ "$output" == *"10.0 s window"* ]]                 # the window is the snapshots' own clocks, not the sleep
    [[ "$output" == *"2.00 cycles/s"* ]]                 # 20 cycles over 10 s
    [[ "$output" == *"6.00 wakes/s (event 50, backstop 10)"* ]]
    [[ "$output" == *"busy 60% of wall"* ]]              # 6 s of cycle time in a 10 s window
    [[ "$output" == *"rss 410 MB"* ]]
    [[ "$output" == *"pid 4242"* ]]
}

@test "romp perf: the process line splits the window's CPU between the pusher, the judge and the rest" {
    run "$ROMP_SCRIPT" perf --interval 0
    [ "$status" -eq 0 ]
    # 0.5 s of process CPU in 10 s; 300 ms of it on the pusher thread, 50 ms in the judge threads
    [[ "$output" == *"cpu 5.0% of one core (pusher 3.0%, judge 0.5%, other 1.5%)"* ]]
}

@test "romp perf: the cycle line's max is the ring's, and the parenthetical names the ring" {
    run "$ROMP_SCRIPT" perf --interval 0
    [ "$status" -eq 0 ]
    [[ "$output" == *"p50 190   p90 420   max 700 (over the last 120 cycles)   last 250"* ]]
    [[ "$output" != *"max 900"* ]]                       # the lifetime max is not printed as a window figure
}

@test "romp perf: the stage line shows each stage's share of cycle time" {
    run "$ROMP_SCRIPT" perf --interval 0
    [ "$status" -eq 0 ]
    # 1 s of jobs, 4 s of push (3 s chat, 0.6 s feed, 0.2 s timeline, 0.1 s send) out of 6 s of cycles
    [[ "$output" == *"jobs  17%"* ]]
    [[ "$output" == *"push  67%"* ]]
    [[ "$output" == *"chat  50%"* ]]
    [[ "$output" == *"feed  10%"* ]]
}

@test "romp perf: builds, sends, goals, judge and http lines carry the window's deltas" {
    run "$ROMP_SCRIPT" perf --interval 0
    [ "$status" -eq 0 ]
    # the chat line's split: the watched tab's rebuild against the background one's, per signature component
    # the background rebuilds it caused (only the non-zero causes; the store moved once in the window), and the
    # builds not cached because an input moved while they ran (three in the window; printed only when non-zero)
    [[ "$output" == *"chat 2 built / 18 cached (40 ms avg; 1 watched, 1 background: store 1; 3 moved)"* ]]
    # GET /feed.json's own reads print beside the pusher's feed, never folded into it (review find, 2026-09-08)
    [[ "$output" == *"feedJson 1 built / 4 cached (150 ms avg)"* ]]
    [[ "$output" == *"full 102 KB/s (chat 2 frames 102 KB/s)"* ]]        # 1048576 bytes over 10 s, bytes beside the count
    [[ "$output" == *"deduped 176 KB/s (feed 18 frames 176 KB/s)"* ]]
    [[ "$output" == *"10.0 loads/s   2.0 saves/s   0.5 writes/s"* ]]
    [[ "$output" == *"2 passes (0.20/s)   last 1200 ms   mean 1200 ms"* ]]   # the WINDOW mean: 2400 ms over 2 passes
    [[ "$output" != *"1012"* ]]                          # not the lifetime ms_mean
    [[ "$output" == *"GET /tick 5 (0.5 ms avg)"* ]]
    [[ "$output" == *"GET /ws 3"* ]]                     # a WebSocket row: count only …
    [[ "$output" != *"GET /ws 3 ("* ]]                   # … never a fabricated 0.0 ms avg
    [[ "$output" != *"/sessions"* ]]                     # no requests in the window: not listed
}

@test "romp perf: the parses line splits the kernel's misses by road and prints only the whole parses' bytes" {
    run "$ROMP_SCRIPT" perf --interval 0
    [ "$status" -eq 0 ]
    # 6 misses in the window, 5 folds and 1 whole parse, whose 20 MB leaf is the only parse cost (2.0 MB/s over 10 s);
    # the roads that did not move in the window are not listed (2026-09-24)
    [[ "$output" == *"parses    kernel 6 misses (fold 5, full 1)   parsed whole 2.0 MB/s   judge 2 misses   8 hits"* ]]
}

@test "romp perf: a kernel from before the split by road prints its misses and says so, never its per-miss bytes" {
    # the older shape: no byRoad, and `bytes` booked the leaf's size at every miss (here nine times the whole parses')
    for s in A B; do
        src="SNAP_$s"
        python3 -c 'import json, sys
d = json.load(open(sys.argv[1])); p = d["parses"]
p["bytes"] = 9 * p.pop("wholeBytes"); p.pop("byRoad")
json.dump(d, open(sys.argv[2], "w"))' "${!src}" "$TEST_DIR/old-$s.json"
    done
    SNAP_A="$TEST_DIR/old-A.json" SNAP_B="$TEST_DIR/old-B.json" run "$ROMP_SCRIPT" perf --interval 0
    [ "$status" -eq 0 ]
    [[ "$output" == *"parses    kernel 6 misses (no split by road: the kernel predates it)   judge 2 misses   8 hits"* ]]
    [[ "$output" != *"parsed whole"* ]]
    [[ "$output" != *"18.0 MB/s"* ]]                     # the old per-miss figure is not printed as a parse cost
}

@test "romp perf: a restart inside the window is said, not subtracted into negative rates" {
    CURL_RESTART=1 run "$ROMP_SCRIPT" perf --interval 0
    [ "$status" -eq 1 ]
    [[ "$output" == *"the kernel restarted during the window (pid 4242 -> 4343)"* ]]
    [[ "$output" != *"cycles/s"* ]]
}

@test "romp perf --json: prints one raw snapshot verbatim and reads the kernel once" {
    run "$ROMP_SCRIPT" perf --json
    [ "$status" -eq 0 ]
    echo "$output" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["pusher"]["cycles"] == 100; assert d["process"]["pid"] == 4242'
    [ "$(cat "$CURL_CALLS")" -eq 1 ]
}

@test "romp perf stacks: reads GET /perf?stacks=1 once and prints one block per thread, its stage and its frames innermost last" {
    run "$ROMP_SCRIPT" perf stacks
    [ "$status" -eq 0 ]
    [ "$(grep -c "127.0.0.1:29855/perf?stacks=1" "$CURL_LOG")" -eq 1 ]
    grep -q "X-Romp-Token: TESTTOKEN123" "$CURL_STDIN"
    echo "$output" | grep -q "^3 threads at 1000.000 (pid 4242)"
    echo "$output" | grep -q "^pusher (ident 11)  stage jobs.autoNudge$"
    echo "$output" | grep -q "^producer (ident 12)$"
    echo "$output" | grep -q "^handler (ident 13) \[answering this request\]$"
    # the pusher's frames in order, innermost last
    echo "$output" | python3 -c '
import sys
lines = [l for l in sys.stdin.read().splitlines()]
i = lines.index("pusher (ident 11)  stage jobs.autoNudge")
assert lines[i + 1:i + 6] == ["    _pusher (kernel.py:100)", "    _job_stage (kernel.py:200)", "    _auto_nudge_session (kernel.py:300)",
                              "    parse_session (event_model.py:400)", "    __enter__ (threading.py:500)"], lines[i:i + 6]'
}

@test "romp perf stacks --json: prints the raw stacks list" {
    run "$ROMP_SCRIPT" perf stacks --json
    [ "$status" -eq 0 ]
    echo "$output" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert sorted(d) == ["11 pusher", "12 producer", "13 handler"], sorted(d); assert d["11 pusher"]["stage"] == "jobs.autoNudge"'
}

@test "romp perf stacks: a kernel from before the sample is named as such and the exit is 1, never 0 threads" {
    CURL_OLD_KERNEL=1 run "$ROMP_SCRIPT" perf stacks
    [ "$status" -eq 1 ]
    echo "$output" | grep -q "does not answer stacks"
    run bash -c "CURL_OLD_KERNEL=1 '$ROMP_SCRIPT' perf stacks 2>/dev/null | grep -c threads"
    [ "$output" = "0" ]
}

@test "romp perf stacks: the OLD switch shape (a list of lines per thread) is refused like no stacks, in both forms" {
    CURL_OLD_SHAPE=1 run "$ROMP_SCRIPT" perf stacks
    [ "$status" -eq 1 ]
    echo "$output" | grep -q "does not answer stacks"
    CURL_OLD_SHAPE=1 run "$ROMP_SCRIPT" perf stacks --json
    [ "$status" -eq 1 ]
}

@test "romp perf stacks: an unknown flag is refused with the usage" {
    run "$ROMP_SCRIPT" perf stacks --bogus
    [ "$status" -eq 2 ]
    echo "$output" | grep -q "usage: romp perf"
}

@test "romp perf: reads GET /perf on the kernel, authorizing on stdin, twice" {
    run "$ROMP_SCRIPT" perf --interval 0
    [ "$status" -eq 0 ]
    [ "$(grep -c "127.0.0.1:29855/perf" "$CURL_LOG")" -eq 2 ]
    grep -q "X-Romp-Token: TESTTOKEN123" "$CURL_STDIN"
    # never in argv: /proc/<pid>/cmdline is world-readable
    run grep -q "TESTTOKEN123" "$CURL_LOG"
    [ "$status" -ne 0 ]
}

@test "romp perf log on|off: POSTs the toggle to /perf and names the journal on systemd" {
    run "$ROMP_SCRIPT" perf log on
    [ "$status" -eq 0 ]
    [[ "$output" == *"log on"* ]]
    [[ "$output" == *"journalctl --user -u romp-manager"* ]]
    grep -q -- "-X POST http://127.0.0.1:29855/perf" "$CURL_LOG"
    grep -q '"log": true' "$CURL_LOG"
    grep -q "X-Romp-Token: TESTTOKEN123" "$CURL_STDIN"
    run "$ROMP_SCRIPT" perf log off
    [ "$status" -eq 0 ]
    [[ "$output" == *"log off"* ]]
    grep -q '"log": false' "$CURL_LOG"
}

@test "romp perf log on: under launchd the hint names the manager.log file, not journalctl" {
    printf '#!/usr/bin/env bash\necho Darwin\n' > "$MOCK/uname"; chmod +x "$MOCK/uname"
    run "$ROMP_SCRIPT" perf log on
    [ "$status" -eq 0 ]
    [[ "$output" == *"tail -f $XDG_STATE_HOME/romp/manager.log"* ]]
    [[ "$output" != *"journalctl"* ]]
}

@test "romp perf log: anything but on|off is refused" {
    run "$ROMP_SCRIPT" perf log maybe
    [ "$status" -eq 2 ]
    [[ "$output" == *"usage: romp perf"* ]]
    run "$ROMP_SCRIPT" perf log
    [ "$status" -eq 2 ]
    [ ! -f "$CURL_LOG" ]                                 # nothing reached the kernel
}

@test "romp perf: a dead kernel fails LOUDLY" {
    CURL_FAIL=1 run "$ROMP_SCRIPT" perf --interval 0
    [ "$status" -ne 0 ]
    [[ "$output" == *"kernel not reachable"* ]]
    CURL_FAIL=1 run "$ROMP_SCRIPT" perf log on
    [ "$status" -ne 0 ]
    [[ "$output" == *"kernel not reachable"* ]]
}

@test "romp perf: a refused token is named as such, not reported as a dead kernel" {
    CURL_403=1 run "$ROMP_SCRIPT" perf --interval 0
    [ "$status" -eq 1 ]
    [[ "$output" == *"refused the serve token (HTTP 403)"* ]]
    [[ "$output" != *"not reachable"* ]]
    CURL_403=1 run "$ROMP_SCRIPT" perf log on
    [ "$status" -eq 1 ]
    [[ "$output" == *"refused the serve token (HTTP 403)"* ]]
}

@test "romp perf: an unknown flag or a bad interval is refused rather than silently ignored" {
    run "$ROMP_SCRIPT" perf --nope
    [ "$status" -eq 2 ]
    [[ "$output" == *"usage: romp perf"* ]]
    run "$ROMP_SCRIPT" perf --interval soon
    [ "$status" -eq 2 ]
    run "$ROMP_SCRIPT" perf --interval
    [ "$status" -eq 2 ]
}

@test "romp perf: listed in help, under the scripting group" {
    run "$ROMP_SCRIPT" help
    [ "$status" -eq 0 ]
    [[ "$output" == *"romp perf"* ]]
}
