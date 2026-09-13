// The partition's pure rules, EXECUTED (the chat split, the user 2026-09-11): which column a page is from its
// own search string, and whether a column holds a session under the shell's sets. render.ts's tabInView is the
// one caller; tab-strip-skip.test.ts pins that call at the source. Synthetic ids only.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import { colFromSearch, columnHolds, ownerOf, parseChatLayout, tileHeaderShown, type ColSets } from "./chat-columns";

const WEB = "11111111-2222-3333-4444-555555555501";
const API = "11111111-2222-3333-4444-555555555502";
const TESTS = "11111111-2222-3333-4444-555555555503";
const REMOTE = "TESTHOST:11111111-2222-3333-4444-555555555504";   // a remote host's session rides its host prefix, as `order` carries it

test("colFromSearch: the shim's rule — the first column is the empty string, ?col=1 folds to it, a later column is its number", () => {
  assert.equal(colFromSearch(""), "", "no search: the first column (a standalone page, the VS Code webview)");
  assert.equal(colFromSearch("?col=1"), "", "?col=1 IS the first column: its state blob keeps the unsuffixed key");
  assert.equal(colFromSearch("?col=2"), "2");
  assert.equal(colFromSearch("?col=3&skeleton=1"), "3", "the skeleton flag rides beside it");
  assert.equal(colFromSearch("?skeleton=1"), "", "no col: the first column");
  assert.equal(colFromSearch("garbage"), "", "an unparseable search is the first column, never a throw");
});

test("columnHolds with null sets: no partition, everything is held, whatever the column", () => {
  for (const col of ["", "2", "9"]) for (const id of [WEB, API, REMOTE]) assert.equal(columnHolds(null, col, id), true, col + " holds " + id);
});

test("columnHolds: a later column holds the ids its entry lists, and only those", () => {
  const sets: ColSets = { "2": [API], "3": [TESTS, REMOTE] };
  assert.equal(columnHolds(sets, "2", API), true);
  assert.equal(columnHolds(sets, "2", TESTS), false, "listed by another column");
  assert.equal(columnHolds(sets, "2", WEB), false, "listed by no column: the first column's");
  assert.equal(columnHolds(sets, "3", TESTS), true);
  assert.equal(columnHolds(sets, "3", REMOTE), true, "a host-prefixed id is matched as a whole string");
  assert.equal(columnHolds(sets, "4", API), false, "a column with no entry holds nothing (a stale page whose entry closed)");
});

test("columnHolds: the first column derives — every id no entry lists, and none an entry does", () => {
  const sets: ColSets = { "2": [API], "3": [TESTS] };
  assert.equal(columnHolds(sets, "", WEB), true, "unlisted: the first column's");
  assert.equal(columnHolds(sets, "", REMOTE), true, "a remote host's session that arrived with no gesture lands in the first column");
  assert.equal(columnHolds(sets, "", API), false);
  assert.equal(columnHolds(sets, "", TESTS), false);
  assert.equal(columnHolds({}, "", WEB), true, "no later columns: the first column holds everything");
  assert.equal(columnHolds({}, "2", WEB), false);
});

test("a doubly listed id belongs to ONE column, the first key holding it, never to both", () => {
  // the shell's writes never produce a double and its sets() resolves one by row order; a store another
  // dashboard wrote before this shell reconciled it can still carry one, and two columns must not both show it
  const sets: ColSets = { "2": [API], "3": [API, TESTS] };
  assert.equal(ownerOf(sets, API), "2");
  assert.equal(columnHolds(sets, "2", API), true);
  assert.equal(columnHolds(sets, "3", API), false);
  assert.equal(columnHolds(sets, "", API), false, "…and the first column does not derive it either");
  assert.equal([2, 3, ""].filter((c) => columnHolds(sets, String(c), API)).length, 1, "exactly one holder");
});

test("ownerOf: the empty string for an id no entry lists, and a junk entry is skipped, never a throw", () => {
  assert.equal(ownerOf({ "2": [API] }, WEB), "");
  assert.equal(ownerOf({ "2": null as unknown as string[], "3": [WEB] }, WEB), "3", "a corrupt entry is passed over");
});

// ── the layout and the tile header rule (tiles, the user 2026-09-13) ──────────────────────────────────────────────
test("parseChatLayout: a grid needs integer rows and cols of at least 1; anything else reads as the row; a non-object is no layout", () => {
  assert.deepEqual(parseChatLayout({ layout: "grid", rows: 2, cols: 3 }), { layout: "grid", rows: 2, cols: 3 });
  assert.deepEqual(parseChatLayout({ layout: "grid", rows: "2", cols: "2" }), { layout: "grid", rows: 2, cols: 2 }, "numeric strings are numbers");
  assert.deepEqual(parseChatLayout({ layout: "row", rows: 1, cols: 3 }), { layout: "row", rows: 1, cols: 3 });
  assert.deepEqual(parseChatLayout({ layout: "grid", rows: 0, cols: 2 }), { layout: "row", rows: 1, cols: 2 }, "a grid with no rows is the row");
  assert.deepEqual(parseChatLayout({ layout: "grid", rows: 2.5, cols: 2 }), { layout: "row", rows: 1, cols: 2 }, "…and so is a fractional one");
  assert.deepEqual(parseChatLayout({ layout: "grid" }), { layout: "row", rows: 1, cols: 1 }, "no shape: the row, one column");
  assert.deepEqual(parseChatLayout({}), { layout: "row", rows: 1, cols: 1 });
  assert.equal(parseChatLayout(null), null, "no shell answer");
  assert.equal(parseChatLayout(undefined), null);
  assert.equal(parseChatLayout("grid"), null, "a bare string is not an answer");
});

test("tileHeaderShown: a grid AND exactly one session shown here; the row never; an empty tile and an overflow tile keep the strip", () => {
  const grid = { layout: "grid" as const, rows: 2, cols: 3 };
  const row = { layout: "row" as const, rows: 1, cols: 2 };
  assert.equal(tileHeaderShown(grid, 1), true, "one session in a tile: the header");
  assert.equal(tileHeaderShown(grid, 0), false, "an empty tile: the strip (its + and the pick)");
  assert.equal(tileHeaderShown(grid, 2), false, "two or more: the strip — the first tile is the overflow, never a dead end");
  assert.equal(tileHeaderShown(grid, 5), false);
  assert.equal(tileHeaderShown(row, 1), false, "the row wears the strip whatever it holds");
  assert.equal(tileHeaderShown(null, 1), false, "no shell (standalone, VS Code): the strip, as ever");
});
