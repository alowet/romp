// A box BELOW the transcript growing must not drop an at-bottom reader out of follow mode (T262e, the user
// 2026-09-08 11:30 AM PT: when the awaiting/background-task box appears between the transcript and the composer
// and covers part of the text, a reader at the bottom must stay at the bottom — the pane scrolls by the box's
// height — and today it does not). A box below the scroller changes the scroller's clientHeight and nothing else:
// the browser keeps scrollTop, fires no scroll event, and the reader who was at the bottom is now the box's
// height above it with the last lines covered; the next append reads atBottom false and leaves them there — the
// pane has fallen into scrolled-up mode by itself. The composer auto-grows the same way while a message is typed.
// Fix: a ResizeObserver on #bg-tasks and #footer with the rule OPPOSITE to the boxes-above compensation: a reader
// whose recorded follow mode is on (the view's `stick`, untouched by the growth since no scroll event fired) is
// written to the new bottom (writer "box-below"); a scrolled-up reader is untouched (their top line never moved).
// Pure rule executed here; render.ts wiring pinned. Also pinned: #content opts out of the browser's own scroll
// anchoring, which was double-compensating the pane's own writers (see the comment beside the rule in styles.css).
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { followBoxBelow } from "./scroll-keep";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const CSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "styles.css"), "utf8");

test("a follow-mode reader follows the bottom when a box below grows or shrinks; a scrolled-up reader is untouched", () => {
  assert.equal(followBoxBelow(true, 64), true, "the awaiting box appeared: pin to the new bottom");
  assert.equal(followBoxBelow(true, -64), true, "it went away: the bottom is the bottom (the clamp already got there; the write is a no-op)");
  assert.equal(followBoxBelow(true, 0), false, "no height change, no write");
  assert.equal(followBoxBelow(false, 64), false, "reading history: the top line never moved, leave them");
  assert.equal(followBoxBelow(false, -64), false);
});

test("render.ts observes #bg-tasks and #footer and writes the new bottom through the scroll-write helper", () => {
  assert.match(RENDER, /import \{[^}]*\bfollowBoxBelow\b[^}]*\} from "\.\/scroll-keep";/);
  assert.match(RENDER, /for \(const boxId of \["bg-tasks", "footer"\]\) \{/);
  const m = RENDER.match(/for \(const boxId of \["bg-tasks", "footer"\]\) \{([\s\S]*?)\n\}/);
  assert.ok(m, "the boxes-below observer block");
  const body = m![1];
  assert.match(body, /new ResizeObserver\(/);
  assert.match(body, /followBoxBelow\(v\.stick, h - lastH\)/, "the recorded follow mode decides, never a post-growth atBottom read (the growth already moved the bottom away)");
  assert.match(body, /writeScroll\(content, content\.scrollHeight, "box-below", true\);/);
  assert.match(body, /v\.scrollTop = content\.scrollTop;/, "the per-view saved position follows");
  assert.match(body, /content\.clientHeight > 0/, "a hidden pane measures 0: nothing to do");
  // the boxes ABOVE keep their own (opposite) rule
  assert.match(RENDER, /for \(const boxId of \["tabbar", "ledger"\]\) \{/);
  assert.match(RENDER, /writeScroll\(content, content\.scrollTop \+ \(h - lastH\), "box-resize"\);/);
});

test("#content opts out of the browser's scroll anchoring: the pane is the one compensator", () => {
  assert.match(CSS, /#content \{[^}]*overflow-anchor: none;/);
});
