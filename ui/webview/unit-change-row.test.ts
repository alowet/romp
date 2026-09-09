// A unit above the tail names itself when it changes height (T262n, the user's 2026-09-08 laptop capture). The merged
// audit reader found one unwritten move in eleven minutes of real use: the transcript shrank 24 px with the reader at
// the bottom and the browser carried them down, still at the bottom, and no row said what shrank. The view rail's row
// names the TAIL whenever the view's height changes, so a unit above the tail changing height in place is a row that
// names the wrong element. This instrument observes every unit in the rendered window and files, for a NON-tail unit's
// height change, the unit's class, its distance above the tail, the recorded follow mode and the measured bottom. A
// row only: nothing is written or decided from it. The tail unit's own change stays the rail's tailchange row.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { unitChangeRow, unitChanges, tailChangeRow, tailLabel, boxChanges, boxLabel, BOX_FROM_TAIL } from "./scroll-write";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const SID = "11111111-2222-4333-8444-000000000262";

type U = { className: string; unit?: number };
const unitOf = (u: U) => u.unit;   // the pane's data-unit: a day divider carries the unit it opens
function window() {
  const top: U = { className: "tx-spacer tx-spacer-top" };
  const a: U = { className: "turn turn-user", unit: 5 };
  const b: U = { className: "turn turn-assistant", unit: 6 };
  const c: U = { className: "turn turn-tool", unit: 7 };            // the tail: the last child that is not a spacer
  const bot: U = { className: "tx-spacer tx-spacer-bot" };
  const children = [top, a, b, c, bot];
  const heights = new Map<U, number>();
  // observe() reports once on attach: the first observation of every unit is its baseline, never a row
  assert.deepEqual(unitChanges(children.map((u, i) => ({ target: u, height: [20, 100, 200, 300, 40][i] })), children, heights, unitOf), []);
  return { top, a, b, c, bot, children, heights };
}

test("a non-tail unit growing by N files exactly one row with dh N, naming the unit and its distance above the tail", () => {
  const w = window();
  const changes = unitChanges([{ target: w.b, height: 237 }], w.children, w.heights, unitOf);
  assert.equal(changes.length, 1, "one change, one row");
  assert.deepEqual({ dh: changes[0].dh, cls: changes[0].cls, fromTail: changes[0].fromTail }, { dh: 37, cls: "turn turn-assistant", fromTail: 1 });
  assert.deepEqual(unitChangeRow(SID, changes[0].dh, changes[0].cls, changes[0].fromTail, true, true, 23690, 869),
                   { sid: SID, dh: 37, cls: "turn turn-assistant", fromTail: 1, stick: true, atBottom: true, sh: 23690, ch: 869 });
  // the same height again is no change; a shrink reads negative; a unit two above the tail says so
  assert.deepEqual(unitChanges([{ target: w.b, height: 237 }], w.children, w.heights, unitOf), []);
  const two = unitChanges([{ target: w.a, height: 76 }], w.children, w.heights, unitOf);
  assert.deepEqual(two.map((x) => [x.dh, x.fromTail]), [[-24, 2]]);
  assert.equal(unitChangeRow(SID, 1, "x".repeat(200), 1, false, false).cls.length, 60, "the class list is bounded like the rail's label");
});

test("fromTail counts units, not children: a day divider between the unit and the tail is not a turn", () => {
  const w = window();
  const divider: U = { className: "day-divider", unit: 7 };   // opens the tail's day: a child of its own, the tail's unit
  const children = [w.top, w.a, w.b, divider, w.c, w.bot];
  w.heights.set(divider, 18);
  const byUnit = unitChanges([{ target: w.b, height: 260 }], children, w.heights, unitOf);
  assert.deepEqual(byUnit.map((x) => [x.dh, x.fromTail]), [[60, 1]], "one turn above the tail, whatever sits between");
  const byChild = unitChanges([{ target: w.b, height: 290 }], children, w.heights);
  assert.deepEqual(byChild.map((x) => [x.dh, x.fromTail]), [[30, 2]], "with no unit index the child distance is all there is");
  const dividerGrew = unitChanges([{ target: divider, height: 40 }], children, w.heights, unitOf);
  assert.deepEqual(dividerGrew.map((x) => [x.cls, x.dh, x.fromTail]), [["day-divider", 22, 0]], "the divider itself is named, at the tail's own unit");
});

test("the tail unit's own change files the existing tailchange row and not this one", () => {
  const w = window();
  assert.deepEqual(unitChanges([{ target: w.c, height: 350 }], w.children, w.heights, unitOf), [], "the tail is the rail's");
  // …and the rail's row is what it always was: the view grew by the same 50 px, named by the tail's class
  assert.deepEqual(tailChangeRow(SID, 350 - 300, tailLabel(w.children), true, 23740, 869),
                   { sid: SID, dh: 50, last: "turn turn-tool", stick: true, sh: 23740, ch: 869 });
  // a batch mixing the tail and a unit above it files the unit alone
  const mixed = unitChanges([{ target: w.c, height: 360 }, { target: w.b, height: 210 }], w.children, w.heights, unitOf);
  assert.deepEqual(mixed.map((x) => [x.cls, x.dh, x.fromTail]), [["turn turn-assistant", 10, 1]]);
});

test("spacers, units that left the window and a window with no tail file nothing", () => {
  const w = window();
  assert.deepEqual(unitChanges([{ target: w.top, height: 4483 }], w.children, w.heights), [], "a spacer re-estimate has its own spacer row");
  const gone: U = { className: "turn turn-user" };
  w.heights.set(gone, 90);
  assert.deepEqual(unitChanges([{ target: gone, height: 120 }], w.children, w.heights), [], "a unit the window slide removed files nothing");
  const spacersOnly = [w.top, w.bot];
  const h2 = new Map<U, number>([[w.top, 10], [w.bot, 10]]);
  assert.deepEqual(unitChanges([{ target: w.top, height: 30 }], spacersOnly, h2), []);
});

test("a box of the scroller outside the thread files the same row, named by id else class, with fromTail -1", () => {
  // the laptop capture's one unwritten move had NO tailchange row: the 24 px came from outside the thread element,
  // on a remote-host tab, where the one such box is the host-offline foot (T262n follow-up)
  assert.equal(BOX_FROM_TAIL, -1, "units sit 1 or more above the tail; a box has no place in the thread");
  assert.equal(boxLabel({ id: "host-offline-foot", className: "tx-hostoff" }), "#host-offline-foot");
  assert.equal(boxLabel({ className: "tx-loading" }), "tx-loading");
  const foot = { id: "host-offline-foot", className: "tx-hostoff" }, sub = { id: "sub-head", className: "sub-head" };
  const heights = new Map<object, number>();
  assert.deepEqual(boxChanges([{ target: foot, height: 58 }, { target: sub, height: 26 }], heights), [], "first observations are baselines");
  assert.deepEqual(boxChanges([{ target: foot, height: 58 }], heights), [], "unchanged files nothing");
  assert.deepEqual(boxChanges([{ target: sub, height: 50 }], heights).map((b) => [b.cls, b.dh]), [["#sub-head", 24]]);
  assert.deepEqual(unitChangeRow(SID, -58, "#host-offline-foot", BOX_FROM_TAIL, true, true, 23666, 869),
                   { sid: SID, dh: -58, cls: "#host-offline-foot", fromTail: -1, stick: true, atBottom: true, sh: 23666, ch: 869 });
});

test("render.ts watches #content's non-thread boxes: appear, change in place and leave all file; nothing is written", () => {
  const blk = RENDER.split("// …and the scroller's boxes OUTSIDE the thread")[1].split("\n}\n")[0];
  assert.match(blk, /const isBox = \(n: Node\): n is HTMLElement => n instanceof HTMLElement && !n\.classList\.contains\("thread"\) && n\.id !== "live-ask";/,
    "threads have their own observers, the live-ask host its own rows");
  assert.match(blk, /scrollDiagRow\("unitchange", unitChangeRow\(activeId \|\| "", dh, cls, BOX_FROM_TAIL, v\.stick, atBottom\(c\), c\.scrollHeight, c\.clientHeight\)\)/);
  assert.match(blk, /for \(const n of Array\.from\(c\.children\)\) if \(isBox\(n\)\) watchBox\(n\);/, "what is there at load is the baseline");
  assert.match(blk, /rec\.removedNodes\.forEach\(\(n\) => \{ if \(isBox\(n\)\) \{ const h = boxHeights\.get\(n\) \|\| 0; boxRo\.unobserve\(n\); boxHeights\.delete\(n\); fileBox\(-h, boxLabel\(n\)\); \} \}\);/,
    "a box leaving files the height it had, negative: the clamp's size");
  assert.match(blk, /rec\.addedNodes\.forEach\(\(n\) => \{ if \(isBox\(n\)\) fileBox\(watchBox\(n\), boxLabel\(n\)\); \}\);/, "a box appearing files its height");
  assert.match(blk, /\.observe\(c, \{ childList: true \}\);/);
  assert.match(blk, /height: \(e\.target as HTMLElement\)\.offsetHeight/, "one measure at the baseline and in the observer: no false first row");
  assert.match(blk, /if \(c\.clientHeight <= 0\) \{ for \(const e of entries\) boxHeights\.delete\(e\.target\); return; \}/, "the whole pane hidden forgets the box baselines, like the unit observer's hide");
  assert.doesNotMatch(blk, /writeScroll|scrollTop =/, "attribution only");
});

test("render.ts wires one observer per view over every unit, through the mutation observer, into the capped diag path", () => {
  const ev = RENDER.split("function ensureView(id: string): View {")[1].split("\n}")[0];
  assert.match(RENDER, /import \{[^}]*\bunitChangeRow\b[^}]*\bunitChanges\b[^}]*\} from "\.\/scroll-write";/);
  assert.match(RENDER, /function scrollDiagRow\(kind: "scrollwrite" \| "scrollgesture" \| "tailchange" \| "spacer" \| "tailmut" \| "unitchange", data: any\): void \{/);
  assert.match(RENDER, /uo\?: ResizeObserver; uh\?: WeakMap<Element, number>; ro\?: ResizeObserver; mo\?: MutationObserver; \}/, "the View carries the unit observer and its heights");
  // a hidden view's units measure 0x0 on hide and their full height on re-show: neither is a change (the review's
  // find: one switch back would have filed a row per unit and burnt the minute's cap). The hide forgets baselines
  // and files nothing; a width change (every unit reflows) refreshes them and files nothing; then the fold, BEFORE
  // the active gate, so an inactive view's baselines stay current
  const uo = ev.split("v.uo = new ResizeObserver((entries) => {")[1].split("\n      });")[0];
  assert.match(uo, /^[\s\S]*?if \(view3\.el\.style\.display === "none"\) \{ for \(const e of entries\) unitHeights\.delete\(e\.target\); return; \}/, "the hide guard is the first statement");
  assert.match(uo, /const w = view3\.el\.clientWidth;\s*\n\s*if \(w !== unitW\) \{ unitW = w; for \(const e of entries\) unitHeights\.set\(e\.target, e\.contentRect\?\.height \?\? 0\); return; \}/, "a reflow refreshes baselines and files nothing");
  assert.ok(uo.indexOf('display === "none"') < uo.indexOf("w !== unitW") && uo.indexOf("w !== unitW") < uo.indexOf("const changes = unitChanges("), "hide, then reflow, then the fold");
  assert.match(uo, /const changes = unitChanges\(entries\.map\(\(e\) => \(\{ target: e\.target, height: e\.contentRect\?\.height \?\? 0 \}\)\), view3\.el\.children, unitHeights, unitOf\);\s*\n\s*const content = document\.getElementById\("content"\);\s*\n\s*if \(!content \|\| activeId !== id \|\| !view3\.shown\) return;/,
    "the fold runs BEFORE the active/shown gate, so an inactive view's baselines stay current");
  assert.match(ev, /const unitOf = \(n: Element\) => \{ const u = \(n as HTMLElement\)\.dataset\?\.unit; return u != null && u !== "" \? Number\(u\) : undefined; \};/, "fromTail counts the pane's data-unit");
  assert.match(ev, /scrollDiagRow\("unitchange", unitChangeRow\(id, c\.dh, c\.cls, c\.fromTail, view3\.stick, atBottom\(content\), content\.scrollHeight, content\.clientHeight\)\)/);
  assert.match(ev, /rec\.addedNodes\.forEach\(\(n\) => \{ if \(n instanceof Element\) view2\.uo\?\.observe\(n\); \}\);/, "units entering the window are observed");
  assert.match(ev, /rec\.removedNodes\.forEach\(\(n\) => \{ if \(n instanceof Element\) \{ view2\.uo\?\.unobserve\(n\); unitHeights\.delete\(n\); \} \}\);/, "units leaving are dropped");
  // the rail's own filing is untouched: the tail's change still files tailchange from the view observer
  assert.match(ev, /if \(content && lastH >= 0 && activeId === id && view\.shown && h !== lastH\)\s*\n\s*scrollDiagRow\("tailchange", tailChangeRow\(id, h - lastH, tailLabel\(view\.el\.children\)/);
  assert.equal((RENDER.match(/v\.uo\?\.disconnect\(\); v\.ro\?\.disconnect\(\); v\.mo\?\.disconnect\(\); v\.el\.remove\(\);/g) || []).length, 2, "both view-removal sites disconnect it");
  assert.equal((RENDER.match(/"unitchange"/g) || []).length, 3, "the kind in the router's union, the unit filing and the box filing");
  assert.doesNotMatch(ev.split("v.uo = new ResizeObserver")[1].split("v.mo = new MutationObserver")[0], /writeScroll|scrollTop =/, "a row only: the unit observer never writes");
});
