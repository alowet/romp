// T258 (the user 2026-09-08): render.ts applyTabOrder must not tear down a tab the kernel STILL affirms LIVE
// just because one tabOrder frame omits it — a transient transcript-read failure is not a close. The frame
// carries a `live` array (kernel _tab_order_frame; federation merges the per-host union); the omission
// teardown excludes it, retainLiveOmitted keeps it on the strip, and one clientDiag row names any id it saved.
// render.ts source pins + federation merge pin; red on the previous sources. Synthetic ids only.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const FED = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "federation.ts"), "utf8");

test("applyTabOrder takes the frame's live set and excludes it from the omission teardown", () => {
  assert.match(RENDER, /import \{ retainLiveOmitted \} from "\.\/tab-order";/);
  assert.match(RENDER, /function applyTabOrder\(o: any, tabs\?: any, report\?: OrderReport, live\?: any\) \{/);
  const m = RENDER.match(/^function applyTabOrder\([\s\S]*?\n\}/m);
  assert.ok(m, "applyTabOrder");
  const body = m![0];
  assert.match(body, /const liveSet = new Set<string>\(Array\.isArray\(live\) \? live\.filter\(\(x: any\) => typeof x === "string"\) : \[\]\);/);
  // the omission set now excludes a live id
  assert.match(body, /const omitted = new Set\(order\.filter\(\(id\) => kernelListed\.has\(id\) && !inKernel\.has\(id\) && !liveSet\.has\(id\)\)\);/);
  // and the retained order (live-but-omitted ids kept at their slot) feeds reconcile
  assert.match(body, /reconcileTabOrder\(retainLiveOmitted\(kernelOrder, order, liveSet\), order,/);
  // a saved id is named once, so a kernel that omits a live session is visible, never silent
  assert.match(body, /what: "live-omitted-kept", data: \{ ids: keptLive \}/);
});

test("the tabOrder message hands applyTabOrder the frame's live array", () => {
  assert.match(RENDER, /applyTabOrder\(m\.order, m\.tabs, \{ reemit:[\s\S]*?\}, m\.live\);/);
});

test("federation carries the live set through the per-host merge, prunes it on close, drops it on detach", () => {
  assert.match(FED, /const ARRAY_ID = \["order", "names", "working", "awaiting", "stateUnknown", "live", "skeleton"\];/);   // + skeleton: the reconnect strip's not-yet-loaded tabs ride the same pass
  assert.match(FED, /private perHostLive: Record<string, string\[\]> = \{\};/);
  assert.match(FED, /this\.perHostLive\[host\] = Array\.isArray\(m\.live\) \? m\.live\.filter\(\(x: any\) => typeof x === "string"\) : \[\];/);
  assert.match(FED, /if \(this\.perHostLive\[host\]\) this\.perHostLive\[host\] = this\.perHostLive\[host\]\.filter\(\(x\) => x !== gone\);/);
  assert.match(FED, /delete this\.perHostLive\[host\];/);
  assert.match(FED, /const live = this\.hostSeq\.flatMap\(\(h\) => this\.perHostLive\[h\] \|\| \[\]\);/);
  assert.match(FED, /const data: any = \{ type: "tabOrder", order, tabs, live, views:/);
});
