// The live AskUserQuestion picker renders INLINE in the chat transcript (the user 2026-06-27): it's the last
// child of #content and scrolls WITH the chat history, instead of a fixed mini-window below it — so a tall
// picker never buries the context above it. Keyboard control is unchanged (the card still owns keydown). And
// "Chat about this" is a real selectable answer again, not filtered-out TUI chrome. Source pins (fleet/render
// run as modules, no jsdom).
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const SRC = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const CSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "styles.css"), "utf8");
const SKEL = fs.readFileSync(path.resolve(process.cwd(), "src", "page-skeleton.ts"), "utf8");
const KERNEL = fs.readFileSync(path.resolve(process.cwd(), "..", "bin", "romp-kernel"), "utf8");

test("#live-ask lives INSIDE #content in the skeleton (both the VS Code body and the kernel's ported copy)", () => {
  assert.match(SKEL, /<div id="content"><div id="live-ask" style="display:none"><\/div><\/div>/);
  assert.match(KERNEL, /<div id="content"><div id="live-ask" style="display:none"><\/div><\/div>/);
});

test("new threads insert BEFORE the picker so it stays the last child of #content", () => {
  assert.match(SRC, /content\?\.insertBefore\(elv, document\.getElementById\("live-ask"\)\)/);
});

test("renderLiveAsk keeps the picker last and reveals it when the user is parked at the bottom", () => {
  // re-append to the end of #content if a thread landed after it
  assert.match(SRC, /if \(content && host\.parentNode === content && host !== content\.lastChild\) content\.appendChild\(host\)/);
  // scroll the transcript to the bottom to reveal the picker — only when stuck to the bottom (never yank a
  // user scrolled up reading context)
  assert.match(SRC, /const v = activeId \? views\.get\(activeId\) : undefined;\s*\n\s*if \(content && \(!v \|\| v\.stick\)\) writeScroll\(content, content\.scrollHeight, "liveask-reveal", true\);/);
});

test("#live-ask is no longer a fixed 42vh mini-region — it flows in the scroll", () => {
  assert.doesNotMatch(CSS, /#live-ask \{[^}]*max-height: 42vh/);
  assert.match(CSS, /#live-ask \{ padding-bottom: 6px; \}/);
});

test("'Chat about this' is a selectable answer again (only Type-something / Submit are filtered)", () => {
  assert.match(SRC, /function isMetaOption\(label: string\): boolean \{ return \/\^\\s\*\(type something\|submit\$\)\/i\.test\(label\.trim\(\)\); \}/);
  // and it is NOT excluded any longer
  assert.doesNotMatch(SRC, /type something\|chat about\|submit/);
});

test("the picker card still owns the keyboard (focus + keydown), so inline-ness doesn't lose keyboard control", () => {
  assert.match(SRC, /card\.addEventListener\("keydown", onSingleKey\);/);
  assert.match(SRC, /card\.addEventListener\("keydown", onMultiKey\);/);
  assert.match(SRC, /querySelector\("#live-ask \.ask-card"\)/);   // Enter from a tab still focuses the card
});
