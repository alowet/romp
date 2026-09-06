// A notification tap lands on the session AND the card that buzzed (the user 2026-09-06). The feed's
// half of that, pinned from both sides of the iframe boundary: the feed announces its first content
// so the shell knows when a {romp:'revealCard'} has something to land on, and the reveal itself never
// dead-ends on a folded thread. Source pins against feed.ts + kernel.py (the render path has no jsdom
// harness), like card-notify's; the shell script itself is EXECUTED by tests/test_kernel_webpush.py.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const SRC = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "feed.ts"), "utf8");
const KERNEL = fs.readFileSync(path.resolve(process.cwd(), "..", "kernel", "kernel.py"), "utf8");

test("the feed announces its FIRST payload's render to the shell, once, the way the timeline does", () => {
  assert.match(SRC, /let feedAnnounced = false;/);
  // after render() inside applyFeedPayload — the cards are in the DOM when this leaves the frame
  assert.match(SRC, /render\(\);\n  if \(!feedAnnounced\) \{\n    feedAnnounced = true;/);
  assert.match(SRC, /window\.parent\.postMessage\(\{ romp: "ready", app: "feed" \}, "\*"\)/);
  assert.equal(SRC.match(/romp: "ready", app: "feed"/g)?.length, 1, "one announcement, one place");
});

test("the shell's reveal script waits for exactly that message, never another pane's ready", () => {
  // the two sides of the contract share the words: app:'feed' is what the shell keys on
  assert.match(KERNEL, /m\.romp==='ready'&&m\.app==='feed'/);
  assert.match(KERNEL, /pendingCard=\{itemId:itemId,sid:sid\};return;/, "a tap before the feed is up is held, not dropped");
  assert.doesNotMatch(KERNEL.slice(KERNEL.indexOf("_LANDING_REVEAL_JS = "), KERNEL.indexOf("_LANDING_REVEAL_JS = ") + 2600),
    /setTimeout/, "event-based: the feed's own ready, no timer");
});

test("revealCard unfolds a collapsed thread before looking for the card (no silent miss on a fold)", () => {
  assert.match(SRC, /function unfoldThreadsFor\(keys: Set<string>\): void \{/);
  // both "take me to this card" entries share it: the bell-entry/notification jump and the chat-dot jump
  assert.match(SRC, /unfoldThreadsFor\(new Set\(\["a:" \+ String\(m\.itemId \|\| ""\)\]\)\);\n    const target = document\.querySelector/);
  assert.match(SRC, /function revealCards\(keys: Set<string>\) \{\n  unfoldThreadsFor\(keys\);/);
  // and the existing fallback stands: a card gone from the feed still opens its session
  assert.match(SRC, /\} else if \(m\.sid\) \{\n      vscodeApi\?\.postMessage\(\{ type: "openSession", id: String\(m\.sid\) \}\);/);
});
