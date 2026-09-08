// Tab rename must act on the CURRENT tab node, never one captured when the menu opened (the user
// 2026-08-08: "right-click → Rename does nothing; the second try works"). The context menu lives on
// document.body and survives kernel pushes, but the tab it was opened FROM does not: renderTabs()
// replaceChildren()s the strip on every push and nothing defers rebuilds while a menu is open. So by
// the time Rename was clicked, the closure's tab/label were usually detached — startTabRename hid the
// orphan's label, inserted an input nobody could see, and focus() was a silent no-op. Worse, the failed
// call still set renameActive = true, and the only code clearing it sits on that detached input's
// Enter/Esc/blur handlers, which can never fire — freezing the strip's re-renders, which is exactly why
// the SECOND attempt always worked (its captured node could no longer be destroyed) and the freeze then
// healed itself on commit. The fix is this codebase's standing click-safety rule: key the action off the
// id and resolve the node at action time.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const rename = RENDER.slice(RENDER.indexOf("function startTabRename"),
                            RENDER.indexOf("// Keyboard nav on a focused tab"));

test("the menu's Rename hands over the id alone — no captured nodes", () => {
  assert.match(RENDER, /dismissTabMenu\(\); startTabRename\(id, copy\); \}\);/,
               "the click resolves the tab itself; a node captured at menu-open time may be detached");
  assert.doesNotMatch(RENDER, /startTabRename\(tab, label, id\)/);
});

test("startTabRename resolves the live tab by data-id at call time", () => {
  assert.match(rename, /function startTabRename\(id: string, copy\?: string\)/, "the id, plus which copy of a multi-tag session to edit (T264b)");
  assert.match(rename, /dataset\.id === id/, "the strip is searched for the CURRENT node wearing this id");
  assert.match(rename, /querySelector<HTMLElement>\("\.tab-label"\)/, "…and its label is taken from that node");
});

test("a vanished tab bails out before renameActive is touched", () => {
  // the stuck-flag half of the bug: renameActive = true with no live input to ever clear it froze the
  // strip until an unrelated rename committed. The guard must run BEFORE the flag is set.
  const guard = rename.indexOf("if (!tab || !label");
  const flag = rename.indexOf("renameActive = true");
  assert.ok(guard > 0, "the resolve is guarded");
  assert.ok(flag > 0, "the defer flag is still set for the live edit");
  assert.ok(guard < flag, "the bail-out precedes the flag, so a dead tab can never freeze the strip");
});
