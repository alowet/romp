#!/usr/bin/env bats

# scripts/docs-serve.sh — serve the docs so a browser refresh always shows the
# current tree. `mkdocs serve`'s own watcher catches your saves but sleeps
# through changes that arrive via git (a merge replaces files wholesale), which
# is the whole reason this wrapper exists: it watches git state and restarts.
# The real mkdocs is stubbed via ROMP_MKDOCS, so no test starts a web server.

ROMP_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"

load git-hermetic

setup() {
    git_hermetic
    TEST_DIR="$(mktemp -d)"
    REPO="$TEST_DIR/repo"
    mkdir -p "$REPO/scripts" "$REPO/docs"
    cp "$ROMP_DIR/scripts/docs-serve.sh" "$REPO/scripts/"
    chmod +x "$REPO/scripts/docs-serve.sh"
    git init -q "$REPO"
    git -C "$REPO" config user.email t@e.invalid
    git -C "$REPO" config user.name t
    echo "start" > "$REPO/docs/guide.md"
    printf 'site_name: t\n' > "$REPO/mkdocs.yml"
    git -C "$REPO" add -A
    git -C "$REPO" commit -qm init

    # A stub that logs one line per launch and then blocks, so a restart is
    # visible as a second line rather than inferred from a pid.
    STUB="$TEST_DIR/mkdocs"
    RUNS="$TEST_DIR/runs.log"
    cat > "$STUB" <<EOF
#!/usr/bin/env bash
echo "serve" >> "$RUNS"
while true; do sleep 0.2; done
EOF
    chmod +x "$STUB"
    export ROMP_MKDOCS="$STUB"
    export ROMP_DOCS_POLL=0.2
}

teardown() {
    [ -n "${LOOP_PID:-}" ] && kill "$LOOP_PID" 2>/dev/null
    pkill -f "$TEST_DIR/mkdocs" 2>/dev/null
    rm -rf "$TEST_DIR"
    return 0
}

runs() { [ -f "$RUNS" ] && wc -l < "$RUNS" | tr -d ' ' || echo 0; }

@test "it starts the server once and leaves it alone while the tree is still" {
    "$REPO/scripts/docs-serve.sh" 8099 >/dev/null 2>&1 &
    LOOP_PID=$!
    sleep 1.5
    [ "$(runs)" = "1" ]
}

@test "a commit restarts the server, which the mkdocs watcher would have missed" {
    "$REPO/scripts/docs-serve.sh" 8099 >/dev/null 2>&1 &
    LOOP_PID=$!
    sleep 1
    [ "$(runs)" = "1" ]

    # A merge/checkout looks like this to the tree: HEAD moves, files replaced.
    echo "edited" > "$REPO/docs/guide.md"
    git -C "$REPO" add -A
    git -C "$REPO" commit -qm second
    sleep 1.5

    [ "$(runs)" -ge 2 ]
}

@test "an uncommitted doc edit restarts it too" {
    "$REPO/scripts/docs-serve.sh" 8099 >/dev/null 2>&1 &
    LOOP_PID=$!
    sleep 1
    echo "dirty" > "$REPO/docs/new.md"
    sleep 1.5
    [ "$(runs)" -ge 2 ]
}

@test "the watcher polls git status without taking the index lock" {
    # A plain `git status` takes .git/index.lock on every run and, whenever a
    # tracked file's stat info is stale, rewrites the index under it. So each
    # poll raced any concurrent `git add`/`git commit` for the lock, and the
    # writer died with "Unable to create .git/index.lock: File exists" (status
    # itself just skips its refresh when it loses). That collision is a
    # scheduling race no test can force; the write behind it is not. Back-date
    # one tracked doc (content unchanged, stat stale): the old poll rewrote
    # .git/index on its very first pass, a read-only poll leaves it
    # byte-identical. (review find, 2026-09-08: behaviour, not a source grep)
    touch -t 200001010000 "$REPO/docs/guide.md"
    before="$(shasum "$REPO/.git/index" | cut -d' ' -f1)"
    LOG="$TEST_DIR/serve.log"
    "$REPO/scripts/docs-serve.sh" 8099 >"$LOG" 2>&1 &
    LOOP_PID=$!
    # The banner prints only after the startup tree_id() returned: wait on that
    # event, not a timer. The loop's later polls can only add a write to catch.
    for _ in $(seq 1 100); do grep -q 'docs on http' "$LOG" 2>/dev/null && break; sleep 0.1; done
    grep -q 'docs on http' "$LOG"
    [ "$(shasum "$REPO/.git/index" | cut -d' ' -f1)" = "$before" ]
    [ ! -e "$REPO/.git/index.lock" ]
}

@test "a git too old for --no-optional-locks refuses at startup instead of polling blind" {
    # git older than 2.15 rejects the flag ("unknown option", exit 129). Inside
    # tree_id the `|| true` would swallow that on every poll, so the watcher
    # would run on and never notice an uncommitted doc edit. A fake git first on
    # PATH plays that version and forwards everything else to the real one. The
    # script must exit before starting mkdocs and name the minimum git.
    # (review find, 2026-09-08)
    BIN="$TEST_DIR/bin"; mkdir -p "$BIN"
    REAL_GIT="$(command -v git)"
    cat > "$BIN/git" <<EOF
#!/usr/bin/env bash
[ "\$1" = "--version" ] && { echo "git version 2.14.0"; exit 0; }
[ "\$1" = "--no-optional-locks" ] && { echo "unknown option: --no-optional-locks" >&2; exit 129; }
exec "$REAL_GIT" "\$@"
EOF
    chmod +x "$BIN/git"
    LOG="$TEST_DIR/serve.log"
    PATH="$BIN:$PATH" "$REPO/scripts/docs-serve.sh" 8099 >"$LOG" 2>&1 &
    LOOP_PID=$!
    # Wait for the exit itself, bounded so a watcher that wrongly keeps polling
    # fails this test rather than hanging it.
    for _ in $(seq 1 50); do kill -0 "$LOOP_PID" 2>/dev/null || break; sleep 0.1; done
    run kill -0 "$LOOP_PID"
    [ "$status" -ne 0 ]
    rc=0; wait "$LOOP_PID" || rc=$?
    LOOP_PID=""
    [ "$rc" -ne 0 ]
    grep -q '2\.15' "$LOG"
    [ "$(runs)" = "0" ]
}

@test "a crashed mkdocs is brought back, never a dead port answering nothing" {
    "$REPO/scripts/docs-serve.sh" 8099 >/dev/null 2>&1 &
    LOOP_PID=$!
    sleep 1
    [ "$(runs)" = "1" ]
    pkill -f "$TEST_DIR/mkdocs"
    sleep 1.5
    [ "$(runs)" -ge 2 ]
}
