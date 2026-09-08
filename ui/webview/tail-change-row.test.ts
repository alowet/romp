// The transcript's tail names itself when it changes height (T262f, the user 2026-09-08). Chrome keeps a bottom reader
// at the bottom by itself when ANY element is appended at the end of #content and clamps them back when it is removed
// (measured: a plain 95 px div, scrollTop +95/-95 with no pane write), so a tail element that toggles under a bottom
// reader flaps the text by its height with no scrollwrite row at all — the shape of the user's laptop rows. The
// scroll rows cannot say WHICH element flapped; this breadcrumb, filed by the active view's ResizeObserver and by
// the live-ask host's, names it (class list or "live-ask") with the height delta and the recorded follow mode.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { tailChangeRow, tailLabel } from "./scroll-write";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const SID = "11111111-2222-4333-8444-000000000201";

test("the row names the tail element, the delta and the follow mode; the label is bounded", () => {
  assert.deepEqual(tailChangeRow(SID, -95, "turn turn-thinking", true, 5000, 600),
                   { sid: SID, dh: -95, last: "turn turn-thinking", stick: true, sh: 5000, ch: 600 });
  assert.equal(tailChangeRow(SID, 12, "x".repeat(200), false).last.length, 60);
  assert.deepEqual(tailChangeRow(SID, 3, "live-ask", false), { sid: SID, dh: 3, last: "live-ask", stick: false, sh: 0, ch: 0 });
});

test("the tail label is the last child that is not a virtualization spacer", () => {
  assert.equal(tailLabel([{ className: "turn turn-user" }, { className: "turn turn-assistant" }, { className: "tx-spacer tx-spacer-bot" }]), "turn turn-assistant");
  assert.equal(tailLabel([{ className: "tx-spacer tx-spacer-top" }]), "");
  assert.equal(tailLabel([]), "");
});

test("render.ts files the row from both tail observers, beside the tail-shrink rule, through the capped diag path", () => {
  assert.match(RENDER, /import \{ ScrollDiagBudget, classifyScroll, scrollWriteRow, tailChangeRow, tailLabel, spacerRow, readScrollDiagCap, summarizeTailMutations, tailMutRow \} from "\.\/scroll-write";/);   // + spacerRow, readScrollDiagCap (T262j)
  assert.match(RENDER, /function scrollDiagRow\(kind: "scrollwrite" \| "scrollgesture" \| "tailchange" \| "spacer" \| "tailmut", data: any\): void \{/);   // + spacer (T262j)
  assert.match(RENDER, /if \(content && lastH >= 0 && activeId === id && view\.shown && h !== lastH\)\s*\n\s*scrollDiagRow\("tailchange", tailChangeRow\(id, h - lastH, tailLabel\(view\.el\.children\), view\.stick, content\.scrollHeight, content\.clientHeight\)\);/);
  assert.match(RENDER, /if \(content && tailLastH >= 0 && v && v\.shown && h !== tailLastH\)\s*\n\s*scrollDiagRow\("tailchange", tailChangeRow\(activeId \|\| "", h - tailLastH, "live-ask", v\.stick, content\.scrollHeight, content\.clientHeight\)\);/);
  assert.equal((RENDER.match(/"tailchange"/g) || []).length, 3, "the kind in the router's union and the two filings");
});
