// A tab's width must not change with its state (T262g, the user 2026-09-08: the chat view slid up and down by one
// tab row at times). renderTabs appended the working dot (.tab-dot, 7 px plus the 4 px gap) only while a session was
// working or awaiting, so a tab grew and shrank with its state; with the strip filled to a wrap boundary, a dot
// appearing or vanishing added or removed a ROW, and every row change moves #content's box under the reader: a
// bottom reader's text slides by the row height (Chrome keeps the scroller at its maximum; on a wrap the pane's
// box-resize compensation writes the same). Measured in a lab: wrap -31 px / un-wrap +31 px per flip, no browser
// fault. Fix: every tab carries the dot's slot in every state — laid out, hidden when the state has no dot — so the
// strip's row count changes only when tabs are added, removed or renamed. The compacting bar keeps its own wider
// slot (a rare, deliberate state). Pure rule executed here; render.ts and the CSS pinned.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { tabDotClass } from "./tab-state";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const CSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "styles.css"), "utf8");

test("every state maps to a dot class; the ones without a visible dot get the hidden slot; compacting gets no dot (its bar)", () => {
  assert.equal(tabDotClass("working"), "tab-dot");
  assert.equal(tabDotClass("awaitingBg"), "tab-dot await");
  assert.equal(tabDotClass(undefined), "tab-dot unknown");
  assert.equal(tabDotClass(""), "tab-dot unknown");
  assert.equal(tabDotClass("opening"), "tab-dot opening");
  assert.equal(tabDotClass("compacting"), null);
  for (const st of ["waiting", "idle", "blocked", "closed", "dead", "needsYou"]) assert.equal(tabDotClass(st), "tab-dot none", st);
});

test("render.ts appends the slot from the one rule; the compacting bar branch stays", () => {
  assert.match(RENDER, /import \{[^}]*\btabDotClass\b[^}]*\} from "\.\/tab-state";/);
  assert.match(RENDER, /const dotCls = tabDotClass\(st\);\s*\n\s*if \(dotCls\) tab\.appendChild\(el\("span", dotCls\)\);/);
  assert.doesNotMatch(RENDER, /if \(st === "working"\) tab\.appendChild\(el\("span", "tab-dot"\)\);/, "the per-state appends are gone");
  assert.match(RENDER, /const ci = el\("span", "tab-compacting-bar"\);/);
});

test("the hidden slot is laid out (visibility, never display:none), same box as the dot", () => {
  assert.match(CSS, /\.tab-dot\.none \{ visibility: hidden; \}/);
});
