// The outline pane rebuilds only when it can be seen (2026-09-04). The dashboard shell keeps it in a
// display:none iframe by default, yet every feed push rebuilt its whole list on the main thread the chat
// pane's clicks share. The first content still paints through while hidden, so revealing the pane shows
// the list at once instead of the pane loader fading over nothing. Pinned at the source, like the other
// pane-wiring tests.
//
// 2026-09-07 (the user, whose dashboard froze on the return to its browser tab): the observer-only gate
// kept rebuilding an ON-SCREEN pane in a HIDDEN tab — the observer sees the pane, not the tab — and its
// callback never fires on the return (nothing intersected differently), so nothing released. The gate
// now reads both measures through the shared pure decision (paint-gate.ts), and visibilitychange releases
// alongside the observer.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { paintHeld } from "./paint-gate";

const SRC = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "fleet.ts"), "utf8");
const body = (name: string) => new RegExp("^function " + name + "\\([\\s\\S]*?\\n\\}", "m").exec(SRC)![0];

test("render() defers while the list is off screen, lets the first content through, and paints once when shown", () => {
  assert.match(SRC, /import \{ paintHeld, paintReleased \} from "\.\/paint-gate";/);
  assert.match(SRC, /function render\(\) \{[\s\S]*?if \(!paneWatching\) \{ paneWatching = true; watchPaneVisibility\(list\); \}/);
  assert.match(SRC, /if \(paintHeld\(document\.hidden, paneVisible, list\.childElementCount > 0\)\) \{ paneDirty = true; return; \}/);
  assert.match(SRC, /if \(typeof IntersectionObserver === "undefined"\) return;/, "no observer → the tab's visibility alone gates");
  assert.match(SRC, /let paneVisible = true;/, "visible until told otherwise: the first paint is never withheld");
});

test("the gate includes the TAB's visibility: an on-screen pane in a hidden tab holds (the observer-only gate did not)", () => {
  // the pure decision fleet.ts now calls, with the pane on screen by the observer's measure
  assert.equal(paintHeld(true, true, true), true, "hidden tab → held");
  assert.equal(!true && true, false, "the old gate (`!paneVisible && content`) let this case through");
  assert.equal(paintHeld(true, true, false), false, "…but the first content still paints through");
  assert.equal(paintHeld(false, true, true), false);
});

test("BOTH release events run the same synchronous release: the observer's callback and visibilitychange→visible", () => {
  assert.match(body("watchPaneVisibility"), /new IntersectionObserver\(\(entries\) => \{\n\s*paneVisible = entries\.some\(\(e\) => e\.isIntersecting\);\n\s*releasePaint\(\);\n\s*\}\)\.observe\(list\);/);
  const rel = body("releasePaint");
  assert.match(rel, /if \(!paintReleased\(paneDirty, document\.hidden, paneVisible\)\) return;\n\s*paneDirty = false;\n\s*render\(\);/);
  assert.doesNotMatch(rel, /requestAnimationFrame|setTimeout|queueMicrotask/, "synchronous: the earliest fresh frame after the compositor's cached one");
  assert.match(SRC, /document\.addEventListener\("visibilitychange", \(\) => \{ if \(!document\.hidden\) releasePaint\(\); \}\);/);
});

test("the payload is applied whatever the visibility — only the rebuild waits", () => {
  // the message handler swaps the model before render() decides whether to paint; no visibility check on the way
  // (the listener is installed through perf-telemetry's per-frame timing wrapper; the handler body is unchanged)
  const handler = /window\.addEventListener\("message", perfFrameHandler\("fleet", \(m\) => vscodeApi\?\.postMessage\(m\), \(e: MessageEvent\) => \{[\s\S]*?\n\}\)\);/.exec(SRC)![0];
  assert.match(handler, /loaded = true;\n\s*sessions = m\.ledgers as FleetSession\[\];/);
  assert.doesNotMatch(handler, /document\.hidden|paneVisible|paneDirty|paintHeld/);
});
