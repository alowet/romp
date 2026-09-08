// Rapid tab switching stays snappy (the user 2026-06-17): a switch updates the tab/ledger instantly, but
// the only expensive part — a first-visited (or changed-compact) view's O(events) transcript BUILD — is
// deferred to the next frame and CANCELLED if you switch away first, so you never wait on a tab you're
// leaving. An already-built view still renders synchronously (instant). Source-level pin (no jsdom).
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");

test("showActive renders a built view synchronously, defers an unbuilt/changed one", () => {
  // the heavy gate is also fronted by `s.events.length > 0` so a zero-event session never defers / never
  // shows the "Loading transcript…" hint — it renders the empty placeholder synchronously (the user 2026-06-19)
  assert.match(RENDER, /const heavy = s\.events\.length > 0 && \(v\.el\.childNodes\.length === 0 \|\| \(settings\.compact && \(v\.rendered !== s\.events\.length \|\| v\.stale\)\)\);/);
  // cached/incremental → instant; since T249 the light path also restores the re-show anchor after the land
  assert.match(RENDER, /if \(!heavy\) \{\s*\n\s*syncView\(activeId!\); landActive\(content, v\);\n\s*if \(keepAnchor\) restoreScrollAnchor\(content, v, keepAnchor\);[^\n]*\n\s*return;\n\s*\}/);
});

test("the heavy build is deferred via rAF, replacing any in-flight one, and skipped if we switched away", () => {
  assert.match(RENDER, /if \(pendingBuildRaf != null\) cancelAnimationFrame\(pendingBuildRaf\);/);
  assert.match(RENDER, /pendingBuildRaf = requestAnimationFrame\(\(\) => \{/);
  assert.match(RENDER, /if \(activeId !== target\) return;/);   // switched away before the build → don't build the tab we left
  assert.match(RENDER, /syncView\(target\);/);
});

test("the landing (scroll/anchor/diagnostics) is factored so sync + deferred paths land identically", () => {
  assert.match(RENDER, /function landActive\(content: HTMLElement \| null, v: View\): void/);
  // called after the deferred build, on the #content read once for the land and the T249 re-show anchor restore
  assert.match(RENDER, /const cc = document\.getElementById\("content"\);\n\s*syncView\(target\);[^\n]*\n\s*landActive\(cc, vv\);\n\s*if \(keepAnchor && cc\) restoreScrollAnchor\(cc, vv, keepAnchor\);/);
});
