// A thin blue notch on the chat's right scroll edge for every USER message (the user 2026-08-17) —
// the conversation's shape at a glance, overview-ruler style. Proportional positions (scroll-
// invariant), painted by the rail-sticky scheduler with a signature skip so pure scrolls do no DOM
// work; passive fixed chrome that never blocks the native scrollbar; gestures (command rows, the
// Continue row) draw no notch — those are doings, not words. Source pins.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const CSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "styles.css"), "utf8");

test("one notch per real user message across the WHOLE loaded conversation", () => {
  // the user 2026-08-17: the chat virtualizes (a rendered window between two estimated-height
  // spacers), and window-only notches "forgot" the newer messages when scrolled back. Notches
  // come from the full resident events array, placed by the one virtual frame (pinned below).
  assert.match(RENDER, /for \(let i = 0; i < s\.events\.length; i\+\+\) \{/);
  // the filter reads the ONE senderKind verdict (2026-08-18): user → blue, romp/tagged → the gray
  // machine notch, harness noise → none — the same classifier the bubble and rail dot wear
  assert.match(RENDER, /const kind = senderKind\(ev\);\s*\n\s*if \(kind === "injected"\) continue;/);
  assert.match(RENDER, /ev\.canned === "continue" \|\| SLASH_CMD_RE\.test\(md\)/,
    "a /command or Continue gesture is a doing, not words — no notch");
});

test("the frame is VIRTUAL: one cached-height prefix over ALL units, independent of scroll and window", () => {
  // T129 (the user 2026-08-27, filming marks moving RELATIVE TO EACH OTHER while scrolling —
  // geometrically impossible for a linear map): the old frame was piecewise — live rect offsets
  // inside the render window, cache sums normalized to each spacer's height outside — so pure
  // scrolling changed the map every frame the window slid. The frame now depends on NOTHING the
  // scroll moves: a mark's position changes only when information arrives (a height measured, an
  // event appended). Lab proof: tools/romp-lab/rail-drift.mjs — learned-regime drift is 0.0px
  // across a full scroll round trip (was 5.7px, endlessly, before).
  assert.match(RENDER, /const unitHeights = new Map<string, Map<number, number>>\(\);/);
  assert.match(RENDER, /if \(Number\.isFinite\(u\) && h > 0\) uh\.set\(u, h\);/, "every rendered unit's height is remembered");
  assert.match(RENDER, /for \(let u = 0; u < unitTotal; u\+\+\) \{ t \+= uh\.get\(u\) \?\? avg; pre\.push\(t\); \}/,
    "ONE prefix-sum over every unit — cached truth where seen, the renderer's average else");
  assert.match(RENDER, /\(i >= 0 && i < unitTotal\) \? pre\[i\] \+ \(pre\[i \+ 1\] - pre\[i\]\) \/ 2 : null/,
    "every unit slots at its virtual middle — uniform semantics, no per-basis seams");
  const frameBody = RENDER.slice(RENDER.indexOf("function contentOffsetFrame("), RENDER.indexOf("function ensureScrollMarks("));
  // the VIRTUAL branch never reads the scroll position or the window (T129); the fully-rendered EXACT branch
  // above it converts client rects into scroll space, which is scroll-invariant (T245)
  const virtualBody = frameBody.split("const avg = v.avgTurnH ?? 60;")[1] || frameBody;
  assert.ok(!/scrollTop|tx-spacer|winStart|slotIn/.test(virtualBody),
    "nothing scroll-coupled inside the frame — no live offsets, no spacer reads, no window bounds");
});

test("a history load rescales the map smoothly — moved notches are carried, never teleported", () => {
  // the user 2026-08-17: scrolling back streams older history in; the scroller's world grows and
  // every proportional position compresses (the native thumb does the same). Rebuilt nodes can't
  // transition, so same-count updates move the EXISTING nodes and CSS carries them.
  assert.match(RENDER, /if \(kids\.length === ys\.length\) \{\s*\n\s*ys\.forEach\(\(o, i\) => \{ kids\[i\]\.style\.top = o\.y \+ "px"; kids\[i\]\.className = "scroll-mark" \+ \(o\.m \? " " \+ o\.m : ""\); \}\);/,
    "…and the kind class updates in place too (a machine notch stays gray through a rescale)");
  assert.match(CSS, /transition: top 180ms ease;/);
  assert.match(CSS, /prefers-reduced-motion: reduce\) \{ \.scroll-marks \.scroll-mark \{ transition: none; \} \}/);
});

test("positions are proportional and pure scrolls do no DOM work", () => {
  assert.match(RENDER, /if \(sig !== scrollMarksSig\) \{/, "signature skip: rebuild only on real change");
  assert.match(RENDER, /paintRailSticky\(\); paintScrollMarks\(\);/, "rides the existing rAF scheduler");
});

test("passive chrome in the user's own blue", () => {
  assert.match(CSS, /\.scroll-marks \{ position: fixed; z-index: 3; pointer-events: none; width: 12px; \}/);
  assert.match(CSS, /background: var\(--you\); opacity: 0\.65;/, "the outgoing-bubble blue, never the romp accent");
});

test("marks translate EVENT indices to DISPLAY UNITS before asking the frame", () => {
  // the user 2026-08-18: "some notches are displayed, others aren't — maybe the ones where I
  // replied". Unit === event only in normal mode; compact mode folds tool runs into toolgroup
  // units, so event indices passed straight to the unit-keyed frame found no node (or the wrong
  // one) and the mark silently vanished — worst exactly beside big tool runs, where replies to a
  // working session land. Both painters now translate through eventUnitIndex.
  assert.match(RENDER, /function eventUnitIndex\(s: Session\): Int32Array/);
  assert.match(RENDER, /if \(it\.kind === "toolgroup" \|\| it\.kind === "retrygroup"\) \{ for \(const i of it\.indices\) map\[i\] = u; \}/);
  assert.match(RENDER, /const evUnit = eventUnitIndex\(s\);/);
  assert.match(RENDER, /const u = evUnit\[i\];/);
  assert.match(RENDER, /const off = frame\.offsetOf\(u\);/, "notches ask the frame in unit space");
  assert.match(RENDER, /const off = frame\.offsetOf\(evUnit\[idx\]\);/, "comment ticks too — one translation, both overlays");
});

// ── T245 (the user 2026-09-07): a notch sat below the thumb while its message was on screen ───────────────
test("a rendered unit changing height re-runs the shared paint — the event the frame was missing (T245)", () => {
  const ev = RENDER.split("function ensureView(id: string): View {")[1].split("\n}")[0];
  assert.match(ev, /v\.ro = new ResizeObserver\(\(\) => scheduleRailSticky\(\)\);\s*\n\s*v\.ro\.observe\(elv\);/,
    "one observer per view element: a lazy figure sizing in or a fold toggling repaints notches AND rail ticks");
  assert.match(RENDER, /ro\?: ResizeObserver; \}/, "the View carries its observer");
  assert.equal((RENDER.match(/v\.ro\?\.disconnect\(\); v\.el\.remove\(\);/g) || []).length, 2, "both view-removal sites disconnect it");
  assert.doesNotMatch(ev, /setTimeout|setInterval/, "no timer stands in for the event");
});

test("with every unit rendered the frame is the scrollbar's own truth: real middles over content.scrollHeight (T245)", () => {
  const frameBody = RENDER.split("function contentOffsetFrame(")[1].split("\nfunction ")[0];
  assert.match(frameBody, /const nodes = Array\.from\(v\.el\.querySelectorAll<HTMLElement>\("\.turn\[data-unit\]"\)\);/);
  assert.match(frameBody, /exact\.set\(u, content\.scrollTop \+ \(r\.top - cRect\.top\) \+ r\.height \/ 2\);/, "scroll-space middle, invariant under scrolling");
  // one unit may own several .turn nodes (an expanded tool group's children — appendItem tags them
  // all with the unit): the unit's FIRST node is its root, and the gate counts UNITS against a spacer-free view,
  // never nodes — the first cut's node count dropped the frame back to the sum whenever a group stood open
  assert.match(frameBody, /if \(Number\.isFinite\(u\) && !exact\.has\(u\)\) \{/, "first node per unit");
  assert.doesNotMatch(frameBody, /nodes\.length === unitTotal/, "no node-count gate");
  assert.match(frameBody, /if \(exact\.size > 0 && exact\.size === unitTotal && !v\.el\.querySelector\("\.tx-spacer"\) && content\.scrollHeight > 0\) \{\s*\n\s*const shx = content\.scrollHeight;\s*\n\s*return \{ sh: shx, offsetOf: \(i: number\): number \| null => exact\.get\(i\) \?\? null \};/);
  // the virtual prefix-sum stays the fallback while spacers hide units
  assert.match(frameBody, /for \(let u = 0; u < unitTotal; u\+\+\) \{ t \+= uh\.get\(u\) \?\? avg; pre\.push\(t\); \}/);
});
