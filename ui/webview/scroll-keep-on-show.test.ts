// T249 (the user 2026-09-07, a screen recording): on a session served through the relay from an attached
// kernel, the chat pane snapped the reader's scroll back to an earlier position ~3 s after they scrolled to
// the bottom — the exact spot the tab had been left at, a blue bubble at the top of the viewport.
//
// The writer: landActive's closing rule, `if (!v.shown || v.stick) bottom else v.scrollTop`, fed by a saved
// spot nothing updated while the reader scrolled (only a tab switch's leaving-tab save, the jump button,
// the resize compensation and the nav trail wrote it). Any full show of an already-shown tab — a
// fork/first-build frame, a settings rerender, a revive failure, a dismissal's fallback — landed the reader
// on that stale spot. Fix: (1) the #content scroll listener keeps the active view's saved spot and
// follow-mode current; (2) a show of a view already on screen anchors the reader's place across its rebuild
// like the live append does, and the big-view re-collapse-to-tail is a switch-only rule. Executed rules +
// render.ts wiring pins, red on main's render.ts. Synthetic values only.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { followReader, landSpot, keepPlaceAcrossShow, type KeepView } from "./scroll-keep";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");

test("the recording: a tab left scrolled up, the reader scrolls to the bottom, a full show lands at the bottom — not the stale spot", () => {
  const v: KeepView = { scrollTop: 1180, stick: false, shown: true };   // saved when the tab was last LEFT: a bubble at the top
  assert.equal(landSpot(v), 1180, "before any gesture a re-show lands on the saved spot (unchanged rule)");
  followReader(v, 9400, true);                                          // the user's smooth scroll to the bottom
  assert.equal(landSpot(v), "bottom", "a full show now follows the reader to the bottom");
  followReader(v, 3020, false);                                         // they scroll back up to read
  assert.equal(landSpot(v), 3020, "…and lands exactly where they are reading");
});

test("followReader touches only a shown view, and a missing view is a no-op", () => {
  const fresh: KeepView = { scrollTop: 0, stick: true, shown: false };
  followReader(fresh, 500, false);
  assert.deepEqual(fresh, { scrollTop: 0, stick: true, shown: false }, "an unshown view's first land still goes to the bottom");
  assert.doesNotThrow(() => followReader(null, 1, true));
  assert.doesNotThrow(() => followReader(undefined, 1, true));
});

test("keepPlaceAcrossShow: only a displayed, visible, already-shown view with no navigation pending", () => {
  const v: KeepView = { scrollTop: 300, stick: false, shown: true };
  assert.equal(keepPlaceAcrossShow(v, true, true, false), true, "a re-show of the view on screen");
  assert.equal(keepPlaceAcrossShow(v, false, true, false), false, "a tab SWITCH: the entering view is not displayed yet — its explicit spot semantics stand");
  assert.equal(keepPlaceAcrossShow(v, true, false, false), false, "a hidden pane has nothing to keep");
  assert.equal(keepPlaceAcrossShow(v, true, true, true), false, "a deep link / moment lands where it says");
  assert.equal(keepPlaceAcrossShow({ ...v, shown: false }, true, true, false), false, "a first show lands at the bottom");
});

test("render.ts: the #content scroll listener keeps the active view's saved spot current (passive, no timer)", () => {
  assert.match(RENDER, /import \{ followReader, keepPlaceAcrossShow \} from "\.\/scroll-keep";/);
  assert.match(RENDER, /c\.addEventListener\("scroll", \(\) => \{\n\s*if \(c\.clientHeight <= 0\) return;\n\s*followReader\(activeId \? views\.get\(activeId\) : null, c\.scrollTop, nearBottom\(c\)\);\n\s*\}, \{ passive: true \}\);/);
  // landActive's landing rule itself is unchanged — its INPUT is what the fix repairs
  assert.match(RENDER, /if \(!v\.shown \|\| v\.stick\) content\.scrollTop = content\.scrollHeight;\n\s*else content\.scrollTop = v\.scrollTop;/);
});

test("render.ts: showActive keeps the reader's place across a re-show of the view already on screen, on both build paths", () => {
  const m = RENDER.match(/^function showActive\(\) \{([\s\S]*?)\n\}/m);
  assert.ok(m, "showActive");
  const body = m![1];
  assert.match(body, /const reshow = keepPlaceAcrossShow\(v, v\.el\.style\.display !== "none", content\.clientHeight > 0, !!pendingAnchor \|\| pendingAnchorT != null\);/);
  assert.match(body, /const keepAnchor = reshow && !nearBottom\(content\) \? captureScrollAnchor\(content, v\) : null;/, "captured BEFORE the rebuild, like appendActive");
  const restores = body.match(/if \(keepAnchor(?: && cc)?\) restoreScrollAnchor\(/g) || [];
  assert.equal(restores.length, 2, "restored after landActive on the light path AND inside the deferred heavy build");
  // the big-view re-collapse to the tail is a SWITCH rule: a re-show of the view on screen must not snap it to the bottom
  assert.match(body, /if \(!reshow && !pendingAnchor && pendingAnchorT == null\n\s*&& v\.el\.querySelectorAll\("\.turn"\)\.length > WINDOW_CAP\)/);
});
