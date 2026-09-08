// The transcript's bottom moving UP under an at-bottom reader keeps them at the bottom, through the pane's own
// writer (T262f, the user 2026-09-08: the pane is unreadable near the bottom; their laptop's scroll breadcrumbs
// showed the view moving up by one fixed amount with no pane write between the rows). When an element at the
// END of #content loses height — the live-ask card cleared, a queued group emptying, the offline foot going —
// the browser clamps scrollTop to the new maximum: an UNWRITTEN move the journal could only file as a gesture,
// and one the follow-mode latch never saw. The rule is the same shape as the boxes-below one: the view's RECORDED
// follow mode (`stick`, the pre-change truth) decides; on, and the tail shrank, the reader is written to the new
// bottom through writeScroll (writer "tail-shrink") — the same place the clamp left them, so nothing visible moves
// twice, but the move is now the pane's, attributed in the journal, and the latch is re-read from a real scroll
// event; off, nothing (the clamp cannot reach a reader more than the shrink above the bottom, and the top line
// they read never moved). Pure rule executed here; render.ts wiring pinned.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { followTailShrink } from "./scroll-keep";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");

test("a follow-mode reader is written to the bottom when the tail shrinks; growth and a scrolled-up reader are left alone", () => {
  assert.equal(followTailShrink(true, -95), true, "the card went: the bottom moved up by 95 px");
  assert.equal(followTailShrink(true, -1), true, "any shrink");
  assert.equal(followTailShrink(true, 0), false);
  assert.equal(followTailShrink(true, 95), false, "growth is the append path's (append-stick) or the reveal's (liveask-reveal), not this rule's");
  assert.equal(followTailShrink(false, -95), false, "reading history: untouched");
});

test("render.ts observes every view's element and #live-ask, and writes the bottom through the scroll-write helper", () => {
  assert.match(RENDER, /import \{[^}]*\bfollowTailShrink\b[^}]*\} from "\.\/scroll-keep";/);
  // the per-view ResizeObserver (it already re-lands the rail) carries the rule
  const m = RENDER.match(/v\.ro = new ResizeObserver\(\(entries\) => \{([\s\S]*?)\n\s*\}\);/);
  assert.ok(m, "the view's ResizeObserver");
  assert.match(m![1], /followTailShrink\(view\.stick, h - lastH\)/, "the recorded follow mode decides, never a post-change atBottom read");
  assert.match(m![1], /writeScroll\(content, content\.scrollHeight, "tail-shrink", true\);/);
  assert.match(m![1], /activeId === id/, "only the ACTIVE view's element moves the reader");
  // the live-ask host sits inside #content after the threads: its shrink is the card leaving
  assert.match(RENDER, /const tailHost = document\.getElementById\("live-ask"\);/);
  assert.match(RENDER, /followTailShrink\(v\.stick, h - tailLastH\)/);
  assert.equal((RENDER.match(/"tail-shrink"/g) || []).length, 2, "two observers, one writer name");
});
