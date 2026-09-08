// Executable geometry for the drag-flap fix (2026-08-28): the slot the provisional tab lands in
// is computed against a VIRTUAL wrap layout of the non-dragged tabs — boundaries that cannot move
// in response to the insert they cause, so monotone pointer motion gives monotone slots and the
// oscillation in the user's recording is impossible by construction.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import { dragSlotIndex, type SlotBox } from "./dragslot";

const boxes = (...w: number[]): SlotBox[] => w.map((x, i) => ({ id: "t" + i, w: x }));

test("a smooth leftward sweep crosses each boundary once — slots are monotone, never oscillating", () => {
  // variable widths on a wrapping strip: 3 rows at 300px
  const b = boxes(120, 90, 140, 60, 110, 100, 80);
  let prev = Infinity;
  for (let x = 299; x >= 0; x -= 3) {
    const idx = dragSlotIndex(b, 300, 0, 30, x, 45);   // sweeping row 2 (y=45, rowH=30)
    assert.ok(idx <= prev, `monotone under monotone motion (x=${x}: ${idx} > ${prev})`);
    prev = idx;
  }
});

test("rows resolve by y band; within a row the midpoints decide", () => {
  const b = boxes(100, 100, 100, 100);   // 2 per 250px row
  assert.equal(dragSlotIndex(b, 250, 0, 30, 40, 10), 0, "row 1, left of t0's midpoint");
  assert.equal(dragSlotIndex(b, 250, 0, 30, 60, 10), 1, "row 1, past t0's midpoint");
  assert.equal(dragSlotIndex(b, 250, 0, 30, 40, 40), 2, "row 2 by y band");
  assert.equal(dragSlotIndex(b, 250, 0, 30, 160, 40), 4, "past row 2's last midpoint → the end");
});

test("past a row's tabs lands at the next row's head; beyond every row lands at the end", () => {
  const b = boxes(200, 200, 200);        // one per 250px row
  assert.equal(dragSlotIndex(b, 250, 0, 30, 240, 5), 1, "right of row 1's tab → row 2's head");
  assert.equal(dragSlotIndex(b, 250, 0, 30, 99, 900), 2, "y clamps to the last row");
  assert.equal(dragSlotIndex(b, 250, 0, 30, 240, 900), 3, "…and past its midline is the very end");
});

test("the gap participates in the layout (the Yatharth strip's 3px seam)", () => {
  const b = boxes(120, 120);             // 120+3+120 = 243 > 240 → wraps
  assert.equal(dragSlotIndex(b, 240, 3, 30, 10, 40), 1, "the second tab wrapped to row 2");
});

test("degenerate inputs stay sane", () => {
  assert.equal(dragSlotIndex([], 300, 0, 30, 50, 50), 0);
  assert.equal(dragSlotIndex(boxes(400), 300, 0, 30, 10, -20), 0, "negative y clamps to row 0");
});

test("a `br` box opens a row even when it would have fit — the line-per-group strip's headers (T264)", () => {
  // T264 (the user 2026-09-08): every tag group starts on its own line, so the real strip breaks
  // before each header whatever the remaining width; the simulation must wrap at the same places or
  // the pointer's slot would read against rows the strip does not have
  const boxes = [{ id: "a", w: 50 }, { id: "b", w: 50 }, { id: "\0head:api", w: 40, br: true }, { id: "c", w: 50 }];
  // row 0: a, b (100 of 400 used — b's row had room for the header, but the header opens row 1)
  assert.equal(dragSlotIndex(boxes, 400, 0, 20, 10, 5), 0, "row 0, left of a");
  assert.equal(dragSlotIndex(boxes, 400, 0, 20, 60, 5), 1, "row 0, between a and b");
  assert.equal(dragSlotIndex(boxes, 400, 0, 20, 300, 5), 2, "row 0, past b: the header's slot (the end of row 0)");
  assert.equal(dragSlotIndex(boxes, 400, 0, 20, 10, 25), 2, "row 1, left of the header: the same slot");
  assert.equal(dragSlotIndex(boxes, 400, 0, 20, 60, 25), 3, "row 1, between the header and c");
  assert.equal(dragSlotIndex(boxes, 400, 0, 20, 300, 25), 4, "row 1, past c: the end");
  // a zero-width br box (the untagged trail's break) is a row opener too: the slot past the previous
  // row's last tab and the slot before the trail's first tab stay two distinct slots
  const trail = [{ id: "a", w: 50 }, { id: "\0sep", w: 0, br: true }, { id: "c", w: 50 }];
  assert.equal(dragSlotIndex(trail, 400, 4, 20, 300, 5), 1, "past a: before the break (the end of a's row)");
  assert.equal(dragSlotIndex(trail, 400, 4, 20, 10, 25), 2, "row 1, left of c's middle: the head of the trail");
  // br on the FIRST box is a no-op (nothing to break from)
  assert.equal(dragSlotIndex([{ id: "\0head:web", w: 40, br: true }, { id: "a", w: 50 }], 400, 0, 20, 100, 5), 2);
});
