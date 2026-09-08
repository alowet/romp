// The chat's tail path re-renders exactly what changed. The kernel's chatTail names the first changed event;
// the client used to re-render from min(that, len - 25) "in case an earlier event mutated in place" — a
// trailing window that was most of a tail's render and stood in for two signals the client can give itself:
// a reconcile pass that touched a prefix event (the editable set, the rewind dim) marks the view stale, and a
// full session frame for a held session rebuilds the window. The one render that depends on later events, the
// "worked …" footer, is patched by unit (worked-footer.ts, its own executed tests). chatTail and
// patchWorkedFooters are lifted and RUN by chat-exact-tail-exec.test.ts (review find, 2026-09-08); the pins
// here cover what no harness lifts: syncViewInner's wiring, reconcileRewind's delegation, the frame paths.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");

test("the tail path starts at the exact first changed event; the trailing re-check window is gone", () => {
  assert.doesNotMatch(RENDER, /const TAIL_RECHECK = \d+;/);
  assert.doesNotMatch(RENDER, /len - TAIL_RECHECK/);
  const sync = RENDER.slice(RENDER.indexOf("function syncViewInner("), RENDER.indexOf("function patchWorkedFooters("));
  assert.match(sync, /const from = Math\.max\(v\.rendered, v\.winStart \?\? 0\);/);
  assert.match(sync, /patchWorkedFooters\(v, s, from, working\);\s*\n\s*v\.winEnd = total;/, "the footers are reconciled after the exact re-render, before the bookkeeping");
});

test("reconcileRewind delegates to the pure pass and marks the view stale on its signal, on every path", () => {
  // the pass and the stale signal are rewind-reconcile.ts, executed by rewind-reconcile.test.ts (a compaction at
  // `from`, a TTL expiry on a full or partial tail, a plain prompt append); render.ts keeps the session's set,
  // the pending entry and the view mark
  const fn = RENDER.slice(RENDER.indexOf("function reconcileRewind("), RENDER.indexOf("// Tab name+color from the kernel's tabOrder push"));
  assert.match(fn, /const r = reconcileRewindPass\(s\.events as RewindEvent\[\], \(s as any\)\._editable, pendingRewind\.get\(s\.id\),\s*\n\s*\{ sdk: s\.status\?\.backend === "sdk", now: Date\.now\(\), ttlMs: REWIND_TTL_MS, optPrefix: OPT_PREFIX, bound \}\);/);
  assert.match(fn, /\(s as any\)\._editable = r\.editable;/);
  assert.match(fn, /if \(!r\.pending\) pendingRewind\.delete\(s\.id\);/);
  assert.match(fn, /if \(v && r\.stale\) v\.stale = true;/);
  assert.doesNotMatch(fn, /\n\s*return;\s*\n/, "no early return skips the mark");
  assert.doesNotMatch(RENDER, /function rewindSig\(/, "one signature, in the module");
});

test("a full frame for a held session and a wholesale events replacement rebuild the window (the tail path trusts v.rendered)", () => {
  const up = RENDER.slice(RENDER.indexOf("function upsert(msg: any) {"), RENDER.indexOf("function update(msg: any) {"));
  // `!kept`: a frame that carried no events for a session with content keeps the resident events (T249b,
  // frame-merge.ts) — nothing was replaced, so a status-shaped frame leaves the view as it is
  assert.match(up, /\} else if \(existed && !kept\) \{[\s\S]{0,900}?const v = views\.get\(msg\.id\);\s*\n\s*if \(v\) v\.stale = true;\s*\n\s*\}/);
  assert.ok(up.indexOf("const kept = keepResidentEvents(") < up.indexOf("} else if (existed && !kept) {"), "the keep decision precedes the stale mark");
  const upd = RENDER.slice(RENDER.indexOf("function update(msg: any) {"), RENDER.indexOf("function update(msg: any) {") + 1200);
  assert.match(upd, /if \(msg\.events\) \{ const v0 = views\.get\(msg\.id\); if \(v0\) v0\.stale = true; \}/);
});

test("the render and the footer patch share one elapsed rule", () => {
  // the patch itself (add, remove, the fork spot's re-homing, the day-divider skip, compact-mode units) runs in
  // chat-exact-tail-exec.test.ts; this pins that the render's per-turn footer reads the same module rule
  assert.match(RENDER, /function turnWorkedSecs\(events: ChatEvent\[\], i: number, working: boolean\): number \| null \{\s*\n\s*return workedSecsOf\(events, i, working, eventEpoch\);/, "one rule for the render and the patch");
  const fn = RENDER.slice(RENDER.indexOf("function patchWorkedFooters("), RENDER.indexOf("function patchWorkedFooters(") + 1500);
  assert.match(fn, /workedFooterPlan\(s\.events, from, winEv, working, eventEpoch\)/, "the patch takes its plan from the module");
});

test("a status-only tail reaches the footer: the view remembers the working state, and a flip patches from the fast path with from = len", () => {
  // chatTail with an empty suffix leaves v.rendered === len, so syncViewInner's no-op fast path is the only
  // code that runs for it; the footer's one non-event input is the session's working state
  assert.match(RENDER, /^interface View \{[^\n]*working\?: boolean;/m);
  const sync = RENDER.slice(RENDER.indexOf("function syncViewInner("), RENDER.indexOf("function patchWorkedFooters("));
  assert.match(sync, /const workFlip = v\.working != null && v\.working !== working;\s*\n\s*v\.working = working;/);
  assert.match(sync, /if \(workFlip && v\.rendered === len && !v\.stale && v\.el\.childNodes\.length > 0\) \{\s*\n\s*patchWorkedFooters\(v, s, len, working, settings\.compact \? items : null\);\s*\n\s*\}\s*\n\s*if \(v\.rendered === len && !v\.stale && v\.el\.childNodes\.length > 0\) return v;/,
    "the flip patches just ahead of the fast path under its predicate, and the fast path (its line pinned by other tests) still returns; a patch that could not address the unit marks stale, so the window path re-renders");
});

test("a plain human-prompt append does not set stale: the signature reads the prefix below the tail's re-render start", () => {
  // a landing prompt is a new editable bubble, so an unbounded editable set differed on every prompt and
  // rebuilt the whole window; the tail renders everything at or past `from` itself (executed:
  // rewind-reconcile.test.ts; here, that chatTail hands its `from` over as the bound)
  assert.match(RENDER, /function reconcileRewind\(s: Session, bound\?: number\): void \{/);
  // (that chatTail hands its `from` over as the bound, lowers v.rendered to it, and still rebuilds the window on a
  // shrunken tail or a change inside a scrolled-away window, runs in chat-exact-tail-exec.test.ts)
});
