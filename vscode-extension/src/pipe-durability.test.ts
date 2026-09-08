// KernelPipe durability pins (the user 2026-07-21, roof): a card reply sent while
// the extension's kernel socket was down vanished — the pipe queued it silently,
// then the reconnect branch wiped the queue. These pins hold the fix's three
// pieces in place: (1) queued ops are tagged intent/chatter and intent FLUSHES on
// every reconnect (before the webview reload), (2) the chat + feed panels feed
// pipe state into their webviews, (3) both webviews render the down-banner with
// the held-message count. No ws/jsdom harness for the pipe class, so pin at source.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const SRC = fs.readFileSync(path.join(process.cwd(), "src", "extension.ts"), "utf8");
const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const FEED = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "feed.ts"), "utf8");
const STYLES = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "styles.css"), "utf8");
const FEEDCSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "feed.css"), "utf8");

test("a send into a down pipe is tagged by intentOp and reported, never silently swallowed", () => {
  assert.match(SRC, /this\.queue\.push\(\{ s, intent: intentOp\(m\?\.type\) \}\);/);
  assert.match(SRC, /this\.onState\?\.\(false, this\.queuedIntents\(\)\);/);
});

test("reconnect flushes intent ops before the webview reload instead of wiping the queue", () => {
  const open = SRC.slice(SRC.indexOf("if (this.everConnected) {"), SRC.indexOf("this.onReconnect();"));
  assert.match(open, /const keep = this\.queue\.filter\(\(q\) => q\.intent\);/);
  assert.match(open, /for \(const q of keep\) ws\.send\(q\.s\);/);
  // the wipe assigns [] only AFTER keep is captured — a bare wipe with no keep is the old bug
  assert.ok(open.indexOf("const keep") < open.indexOf("this.queue = [];"), "keep must be captured before the wipe");
});

test("the first-ever connect still flushes everything queued before the pipe was up", () => {
  assert.match(SRC, /this\.everConnected = true;\s*\n\s*for \(const q of this\.queue\) ws\.send\(q\.s\);/);
});

test("chat and feed panels both post pipeState into their webviews", () => {
  const hits = SRC.match(/postMessage\(\{ type: "pipeState", up, queued: queued \?\? 0 \}\)/g) || [];
  assert.equal(hits.length, 2, "chat + feed panels must both wire onState");
});

test("both webviews render the pipe-down banner with the held count", () => {
  for (const [name, src] of [["render.ts", RENDER], ["feed.ts", FEED]] as const) {
    // the chat's handler also marks unconfirmed sends "not confirmed" on the down edge (render.ts
    // markPendingLost); the feed has no sends, so the group is optional and the feed's bare form still matches
    assert.match(src, /if \(m\.type === "pipeState"\) \{ (?:if \(!m\.up\) markPendingLost\("connection"\); )?pipeBanner\(!!m\.up, Number\(m\.queued\) \|\| 0\); return; \}/,
      `${name} must handle pipeState`);
    assert.ok(src.includes("held, sending when it's back"), `${name} must count held messages`);
  }
});

test("the #rpipe banner is styled in both sheets (feed page loads only feed.css)", () => {
  assert.ok(STYLES.includes("#rpipe {"), "styles.css must style #rpipe");
  assert.ok(FEEDCSS.includes("#rpipe {"), "feed.css must style #rpipe");
});
