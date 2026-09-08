// The reader's place across a rebuild that RE-WINDOWED the view (T262l, 2026-09-08, from a lab run). A settings
// change re-renders every view from scratch; the fresh tail window of a long transcript rarely holds the anchor turn
// of a reader scrolled up, so the direct restore (restoreScrollAnchor: query the uuid in the DOM, write its kept
// offset) found nothing, the land put the reader on the raw saved scrollTop in a layout whose spacer estimate had
// moved by thousands of pixels, and the anchor turn drifted about 200 px on screen (measured: -0.1 px → +198 px over
// two re-renders, spacer rows dTop -10348 / dBot +4378). When the direct restore misses, the deep-link land takes over
// with the kept offset: it renders a window AROUND the anchor's unit (or fetches older history and re-lands on
// arrival) and writes "keep-offset", the anchor's exact on-screen position. Measured after: -0.14 px → -0.14 px, no
// moves. render.ts wiring pinned (the machinery it reuses has its own executed tests).
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");

test("keepPlaceAcrossWindow: the direct restore first; on a miss, the deep-link land with the kept offset", () => {
  const m = RENDER.match(/^function keepPlaceAcrossWindow\(content: HTMLElement, v: View, keep: \{ uuid: string; y: number \}\): boolean \{([\s\S]*?)\n\}/m);
  assert.ok(m, "the helper");
  const body = m![1];
  assert.match(body, /if \(restoreScrollAnchor\(content, v, keep\)\) return true;/, "the cheap path when the turn is rendered");
  assert.match(body, /pendingAnchor = keep\.uuid; pendingAnchorKeepY = keep\.y;/, "armed with the kept offset, so the land writes keep-offset, not a flashed top-of-viewport jump");
  assert.match(body, /const landed = scrollToAnchor\(keep\.uuid\);/, "the window-around-unit land");
  assert.match(body, /if \(!anchorPendingOlder\) \{ pendingAnchor = null; pendingAnchorKeepY = null; \}/, "disarmed unless an older-history fetch will re-land on arrival");
});

test("showActive keeps the place through the window-aware helper on both build paths", () => {
  assert.match(RENDER, /syncView\(activeId!\); landActive\(content, v\);\n\s*if \(keepAnchor\) keepPlaceAcrossWindow\(content, v, keepAnchor\);/);
  assert.match(RENDER, /landActive\(cc, vv\);\n\s*if \(keepAnchor && cc\) keepPlaceAcrossWindow\(cc, vv, keepAnchor\);/);
  assert.equal((RENDER.match(/keepPlaceAcrossWindow\(/g) || []).length, 3, "two call sites and the definition");
});
