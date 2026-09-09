// Timeline work-bar click regression (2026-06-12): the bar's click handler
// passed a NULL anchor (a bare lane-open with preserveFocus), so clicking any
// work period visibly did nothing — while prompt-dot clicks, which carry the
// prompt-line uuid, worked. workAnchorOf is now the single anchor chain for
// WORK-intent landings (focus handler + bar click); these tests pin the chain
// and, since the SVG draw path has no DOM harness here, pin the bar/focus
// wiring at the source level so the click can't silently revert to null.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { createRequire } from "node:module";

const viewPath = path.resolve(process.cwd(), "..", "ui", "romp-timeline-view.js");
const { workAnchorOf, idleGaps, dotLit, barLit, interpNow, barEndT, dragAxis } = createRequire(__filename)(viewPath);

// idleGaps(merged, gapCT, now): which idle stretches collapse on the broken axis. GAP_MIN = 20*60 = 1200s.
// merged = sorted non-overlapping activity intervals [[a,b],…]. A gap collapses when it's ≥ GAP_MIN AND
// wider than the collapsed width gapCT. Tests use gapCT = 300 so GAP_MIN is the binding threshold.

test("idleGaps: a long gap BETWEEN activity collapses (trailing:false)", () => {
  const g = idleGaps([[0, 100], [2000, 2100]], 300, null);
  assert.deepEqual(g, [{ ra: 100, rb: 2000, trailing: false }]);
});

test("idleGaps: a short gap between activity does NOT collapse", () => {
  assert.deepEqual(idleGaps([[0, 100], [900, 1000]], 300, null), []); // 800s < GAP_MIN
});

test("idleGaps: the TRAILING gap from last activity to now collapses, flagged trailing", () => {
  const g = idleGaps([[0, 100]], 300, 2000);
  assert.deepEqual(g, [{ ra: 100, rb: 2000, trailing: true }]);
});

test("idleGaps: no trailing gap when now is close to the last activity", () => {
  assert.deepEqual(idleGaps([[0, 100]], 300, 1000), []); // 900s idle < GAP_MIN
});

test("idleGaps: now=null yields inter-gaps only (no trailing)", () => {
  const g = idleGaps([[0, 100], [2000, 2100]], 300, null);
  assert.equal(g.length, 1);
  assert.equal(g[0].trailing, false);
});

test("idleGaps: a gap not WIDER than the collapsed width is left alone", () => {
  // 1900s ≥ GAP_MIN but ≤ gapCT(2500): collapsing wouldn't shrink it, so skip
  assert.deepEqual(idleGaps([[0, 100], [2000, 2100]], 2500, null), []);
});

test("idleGaps: inter-gap then trailing — ascending, trailing last and flagged", () => {
  const g = idleGaps([[0, 100], [2000, 2100]], 300, 5000);
  assert.deepEqual(g, [
    { ra: 100, rb: 2000, trailing: false },
    { ra: 2100, rb: 5000, trailing: true },
  ]);
});

test("work anchor prefers the readable reply line", () => {
  assert.equal(workAnchorOf({ promptId: "p1", workId: "w1", replyUuid: "r1" }), "r1");
});

test("work anchor falls back to the first reply line when no readable reply", () => {
  assert.equal(workAnchorOf({ promptId: "p1", workId: "w1", replyUuid: null }), "w1");
});

test("interrupted period (no reply lines) anchors on the boundary line", () => {
  assert.equal(workAnchorOf({ promptId: "p1", workId: null, replyUuid: null }), "p1");
});

test("no event / no uuids yields null (openChat then uses anchorT / bottom)", () => {
  assert.equal(workAnchorOf(null), null);
  assert.equal(workAnchorOf({ promptId: null, workId: null, replyUuid: null }), null);
});

test("bar click and focus handler both route through workAnchorOf", () => {
  const src = fs.readFileSync(viewPath, "utf8");
  // the work-bar click must carry the work anchor + the period start as anchorT
  assert.match(src, /openChat\(s\.id, workAnchorOf\(t\), false, false, t\.start\)/);   // T278b: the lane key is the bar's session
  // the feed-focus landing uses the same chain, so the two can't drift apart
  assert.match(src, /workAnchorOf\(byId\)/);
});

// Granular hover (2026-06-12): a turn's two glyphs are addressed by the ATOM ids romp-events mints
// (t.promptId → the start dot, t.workId → the work bar). dotLit/barLit gate each glyph on its own
// atom so a chat 'message' hover (emitting promptId) rings ONLY the dot and an 'action' hover
// (emitting workId) ONLY the bar — no out-of-band part flag, no shared highlight. The whole-turn id
// (a DAG journey / a coarse card hover) still lights both. `hit` = membership in the highlight set.
const hitOf = (...ids: string[]) => { const s = new Set(ids); return (id: string) => !!id && s.has(id); };
const TURN = { id: "S:100:ab", promptId: "S:100:ab#p", workId: "S:100:ab#w" };

test("prompt-atom hover lights ONLY the dot (not the bar)", () => {
  const hit = hitOf(TURN.promptId);
  assert.equal(dotLit(TURN, hit), true);
  assert.equal(barLit(TURN, hit), false);
});

test("work-atom hover lights ONLY the bar (not the dot)", () => {
  const hit = hitOf(TURN.workId);
  assert.equal(barLit(TURN, hit), true);
  assert.equal(dotLit(TURN, hit), false);
});

test("whole-turn id (DAG journey / coarse card hover) lights BOTH glyphs", () => {
  const hit = hitOf(TURN.id);
  assert.equal(dotLit(TURN, hit), true);
  assert.equal(barLit(TURN, hit), true);
});

test("an unrelated id lights neither glyph", () => {
  const hit = hitOf("S:999:zz#w");
  assert.equal(dotLit(TURN, hit), false);
  assert.equal(barLit(TURN, hit), false);
});

test("the bar uses barLit and the start dot uses dotLit (not a shared check)", () => {
  const src = fs.readFileSync(viewPath, "utf8");
  // membership helper is `dagOrHover`, NOT `hit` — the bar/connector loops have a local `const hit`
  // rect, so a `const hit` here would TDZ-crash draw() on the first in-window bar (2026-06-12 regression).
  // (2026-07-17: lit no longer draws a white ring — the bar is drawn grown, the dot passes lit into dot().)
  assert.match(src, /const lit = barLit\(t, dagOrHover\);/);
  assert.match(src, /, null, dotLit\(t, dagOrHover\)\);/);
  assert.doesNotMatch(src, /const hit = \(id\) =>/, "membership helper must not be named `hit` (collides with the local hit-target rect)");
});

// --- smooth live-edge advance: interpNow(baseSec, baseMs, nowMs, live, maxAheadSec) ---
// The effective `now` the timeline renders its right edge at. While live-following it = data.now plus
// the wall-clock elapsed since that poll (so the edge GLIDES between polls); otherwise it's exactly
// data.now (a held/frozen view must not creep). The advance is clamped to [0, maxAheadSec].
test("interpNow: not live-following → returns the raw base (held/frozen views never creep)", () => {
  assert.equal(interpNow(1000, 0, 5000, false, 30), 1000);   // 5s elapsed but not live → unchanged
});

test("interpNow: no baseline ms yet → returns the raw base", () => {
  assert.equal(interpNow(1000, null, 5000, true, 30), 1000);
});

test("interpNow: live-following advances base by wall-clock seconds elapsed", () => {
  assert.equal(interpNow(1000, 2000, 4500, true, 30), 1002.5);   // (4500-2000)ms = 2.5s
});

test("interpNow: never runs backward when the monotonic clock hiccups (clamped at 0)", () => {
  assert.equal(interpNow(1000, 5000, 4000, true, 30), 1000);     // negative elapsed → +0
});

test("interpNow: clamps the advance to maxAheadSec (a backgrounded tab can't fling the edge ahead)", () => {
  assert.equal(interpNow(1000, 0, 120000, true, 30), 1030);      // 120s elapsed, cap 30 → +30
});

// --- open work bar rides the interpolated edge: barEndT(t, nowS, dataNow) ---
// The right edge a bar is DRAWN to. An OPEN bar (end baked to emit-now, or t.open) must follow the
// gliding nowS so it advances WITH the axis instead of snapping each re-emit; a CLOSED bar keeps its
// real end regardless of nowS. When not live-following (nowS === dataNow) an open bar just ends at now.
test("barEndT: an open bar (end >= dataNow) is drawn to the interpolated nowS", () => {
  assert.equal(barEndT({ start: 100, end: 200 }, 250, 200), 250);   // glides past the baked end (200) to 250
});

test("barEndT: an open bar flagged t.open rides nowS too", () => {
  assert.equal(barEndT({ start: 100, end: 200, open: true }, 250, 200), 250);
});

test("barEndT: a closed bar (end < dataNow) keeps its real end, unaffected by nowS", () => {
  assert.equal(barEndT({ start: 100, end: 150 }, 250, 200), 150);
});

test("barEndT: with no interpolation (nowS === dataNow) an open bar just ends at now", () => {
  assert.equal(barEndT({ start: 100, end: 200 }, 200, 200), 200);
});

test("barEndT: never draws an open bar to before its own start", () => {
  assert.equal(barEndT({ start: 300, end: 300 }, 250, 300), 300);   // max(nowS, start) guards backward draw
});

// Min zoom window = 1 minute (the user 2026-06-13). NICE already includes 60 so 1-min ticks render.
test("MIN_W allows a 1-minute zoom window", () => {
  const src = fs.readFileSync(viewPath, "utf8");
  assert.match(src, /const MIN_W = 60\b/);
});

// Drag axis disambiguation (the user 2026-06-13 mouse model): horizontal-dominant drag pans, vertical
// reorders; below threshold = undecided (a plain click still selects).
test("dragAxis: below threshold → null (plain click still selects)", () => {
  assert.equal(dragAxis(2, 2, 4), null);
});
test("dragAxis: horizontal-dominant → pan", () => {
  assert.equal(dragAxis(20, 5, 4), "pan");
});
test("dragAxis: vertical-dominant → row reorder", () => {
  assert.equal(dragAxis(5, 20, 4), "row");
});

test("a postal connector click jumps to the message's OWN card BY ID (mm.id → data-mid), not nearest-time (the user 2026-06-20)", () => {
  const src = fs.readFileSync(viewPath, "utf8");
  // msgNav passes the postal message id as the chat anchor; the chat (scrollToAnchor) matches it to the
  // card's data-mid. nearestTurnAnchor stays only as a uuid fallback (the tab is the lane, mm.toId; bars carry
  // no tid since T278b) — the old time-nearest anchor (whatever turn was closest to the exec time) is gone.
  assert.match(src, /this\.openChat\(mm\.toId, mm\.id \|\| \(an && \(an\.promptId \|\| an\.replyUuid\)\)/);
});
