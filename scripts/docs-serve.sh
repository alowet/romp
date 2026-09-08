#!/usr/bin/env bash
# Serve the docs site so a browser refresh ALWAYS shows the current tree.
#
# `mkdocs serve` watches the filesystem, and that watcher reliably catches your
# own saves but misses changes that arrive through git: a merge, a checkout, a
# rebase replaces files wholesale and the rebuild never fires, so the page you
# refresh is whatever was true when the server started. That has fooled us into
# re-reporting fixed text as broken more than once.
#
# So: run mkdocs serve, and watch the one thing its watcher misses. Whenever
# HEAD or the working tree moves, restart it. Event-based on git state, not a
# rebuild timer (CLAUDE.md's design rule).
#
#   scripts/docs-serve.sh [port]        # default 8000
set -euo pipefail

PORT="${1:-8000}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

# HEAD plus the hash of every tracked+untracked doc input: catches merges,
# checkouts, and stashes, which are exactly what the mkdocs watcher sleeps through.
# --no-optional-locks: a plain `git status` refreshes the index as a side effect,
# under .git/index.lock, and this runs every poll — so it raced any concurrent
# `git add`/`git commit` for the lock ("Unable to create .git/index.lock: File
# exists"). A watcher only reads; it must never hold the lock a writer needs.
tree_id() {
  {
    git rev-parse HEAD 2>/dev/null || true
    git --no-optional-locks status --porcelain -- docs mkdocs.yml overrides 2>/dev/null || true
  } | shasum | cut -d' ' -f1
}

# A git older than 2.15 has no --no-optional-locks: every poll would fail, the
# `|| true` above would swallow it, and the watcher would run on without ever
# seeing an uncommitted doc edit. Probe the exact poll once and refuse loudly
# instead. (review find, 2026-09-08)
if ! err="$(git --no-optional-locks status --porcelain -- docs mkdocs.yml overrides 2>&1 >/dev/null)"; then
  echo "docs-serve: the read-only poll failed: $err" >&2
  echo "docs-serve: needs git 2.15 or newer for --no-optional-locks; found: $(git --version 2>&1)" >&2
  exit 1
fi

MKDOCS="${ROMP_MKDOCS:-mkdocs}"     # stubbable, so the test never runs a real server
POLL="${ROMP_DOCS_POLL:-2}"

SERVER=""
start() {
  "$MKDOCS" serve -a "127.0.0.1:$PORT" &
  SERVER=$!
}
stop() { [ -n "$SERVER" ] && kill "$SERVER" 2>/dev/null || true; }
trap 'stop; exit 0' INT TERM

start
LAST="$(tree_id)"
echo "docs on http://127.0.0.1:$PORT/romp/ — restarting on any git change"

while true; do
  sleep "$POLL"
  NOW="$(tree_id)"
  if [ "$NOW" != "$LAST" ]; then
    echo "[docs-serve] tree moved; restarting mkdocs"
    LAST="$NOW"
    stop
    wait "$SERVER" 2>/dev/null || true
    start
  fi
  # A crashed mkdocs (a bad config, a port grab) must not leave a dead port
  # answering nothing: bring it back rather than looping over a corpse.
  if ! kill -0 "$SERVER" 2>/dev/null; then
    echo "[docs-serve] mkdocs exited; restarting"
    start
  fi
done
