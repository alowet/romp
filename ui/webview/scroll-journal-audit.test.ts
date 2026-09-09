// The scroll journal's reader recognizes the snap (T262k, the user 2026-09-08): a single scroll event, after the reader
// had stopped, landing on one fixed value per tab tens of pixels above the bottom, with no write, no tail change and
// scrollHeight unchanged — and does NOT cry wolf at the reader's own bursts, a write's echo, a tail shrink's clamp or a
// spacer re-size's anchoring. The rows are built with the pane's own row builders (scroll-write.ts), so a change to a
// row's shape breaks this file before it breaks the reading. Synthetic values throughout.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import { unwrittenMoves, repeatedLandings, journalRowFromDiagLine, type JournalRow } from "./scroll-journal-audit";
import { scrollWriteRow, tailChangeRow, spacerRow } from "./scroll-write";

const SID = "11111111-2222-4333-8444-000000000301";
const SID2 = "devbox:11111111-2222-4333-8444-000000000302";
const SH = 9000, CH = 900, BOTTOM = SH - CH;           // 8100

const gesture = (t: number, top: number, sh = SH, ch = CH, sid = SID): JournalRow => ({ t, what: "scrollgesture", data: { sid, top, gesture: true, sh, ch } });
const write = (t: number, writer: string, before: number, after: number, stick = false, sh = SH, ch = CH, sid = SID): JournalRow =>
  ({ t, what: "scrollwrite", data: scrollWriteRow(sid, writer, before, after, stick, sh, ch) });
const tail = (t: number, dh: number, last: string, stick: boolean, sh = SH, ch = CH, sid = SID): JournalRow =>
  ({ t, what: "tailchange", data: tailChangeRow(sid, dh, last, stick, sh, ch) });
const spacer = (t: number, topBefore: number, topAfter: number, botBefore: number, botAfter: number, sh = SH, ch = CH, sid = SID): JournalRow =>
  ({ t, what: "spacer", data: spacerRow(sid, topBefore, topAfter, botBefore, botAfter, sh, ch) });

/** A reader's trackpad burst: samples ~16 ms apart, accelerating then easing, from `from` to `to`. */
function burst(t0: number, from: number, to: number, n = 12): JournalRow[] {
  const rows: JournalRow[] = [];
  for (let i = 1; i <= n; i++) {
    const k = i / n, ease = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    rows.push(gesture(t0 + i * 16, Math.round((from + (to - from) * ease) * 10) / 10));
  }
  return rows;
}

test("the snap: one event after a pause, tens of pixels up, nothing wrote it — reported, with its distance above the bottom", () => {
  const rows = [
    write(1000, "land-bottom", 0, BOTTOM, true),
    ...burst(1600, BOTTOM - 300, BOTTOM),                 // the reader scrolls down to the bottom
    gesture(4400, BOTTOM - 64),                           // 2.6 s later: one event, 64 px up, sh unchanged
    ...burst(9000, BOTTOM - 64, BOTTOM),                  // the reader scrolls back down
    gesture(11900, BOTTOM - 64),                          // and it happens again
  ];
  const moves = unwrittenMoves(rows);
  assert.equal(moves.length, 2, JSON.stringify(moves));
  assert.deepEqual(moves.map((m) => [m.t, m.from, m.to, m.delta, m.distAfter, m.explained]),
    [[4400, BOTTOM, BOTTOM - 64, -64, 64, "none"], [11900, BOTTOM, BOTTOM - 64, -64, 64, "none"]]);
  assert.ok(moves[0].idleMs >= 2500, "the pause before it is on the record: " + moves[0].idleMs);
  assert.deepEqual(repeatedLandings(moves), [{ to: BOTTOM - 64, count: 2, distAfter: 64 }], "one fixed landing, twice");
});

test("the snap right after a land: the write's after is the bottom, the next event 90 ms later already reads 128 px up", () => {
  const rows = [
    write(1000, "land-bottom", 3800, 13640.8, true, 14208, 567),
    gesture(1093, 13512.9, 14208, 567),
    ...burst(1700, 13514.6, 13640.8),
  ];
  // the write is the last recorded position; a 128 px move 93 ms later is not a burst sample (idle is measured from the write)
  const moves = unwrittenMoves(rows, { idleMs: 80 });
  assert.equal(moves.length, 1);
  assert.equal(moves[0].from, 13640.8);
  assert.equal(Math.round(moves[0].to * 10) / 10, 13512.9);
  assert.equal(Math.round(moves[0].distAfter * 10) / 10, 128.1);
  assert.equal(moves[0].explained, "none");
  // at the default idle floor the same rows say nothing: the caller chooses how close to a write a move may sit
  assert.equal(unwrittenMoves(rows).length, 0);
});

test("the reader's own bursts are not moves: samples 16 ms apart, small first steps, a continuing stream", () => {
  const rows = [
    write(1000, "land-bottom", 0, BOTTOM, true),
    ...burst(1600, BOTTOM, BOTTOM - 420),                 // up
    ...burst(4000, BOTTOM - 420, BOTTOM - 40),            // down, after a 2.4 s pause: the first step is small
    ...burst(7000, BOTTOM - 40, BOTTOM),                  // to the bottom
  ];
  assert.deepEqual(unwrittenMoves(rows), []);
});

test("a fast flick after a pause is one big first step but a stream follows: not a move", () => {
  const rows = [
    write(1000, "land-bottom", 0, BOTTOM, true),
    gesture(4000, BOTTOM - 90), gesture(4016, BOTTOM - 210), gesture(4033, BOTTOM - 300), gesture(4050, BOTTOM - 340),
  ];
  assert.deepEqual(unwrittenMoves(rows), []);
  // …unless the settle window is set to zero, in which case the caller asked for every first step
  assert.equal(unwrittenMoves(rows, { settleMs: 0 }).length, 1);
});

test("a write's echo and a write's own landing are not moves", () => {
  const rows = [
    ...burst(1000, BOTTOM - 500, BOTTOM - 300),
    write(3000, "anchor-restore", BOTTOM - 300, 2438.3, false),
    gesture(3020, 2438.3),                                // the echo (within a pixel)
    write(6000, "box-resize", 2438.3, 2534.2, false, SH, CH - 96),
    gesture(6016, 2534.5),                                // the echo, off by half a pixel
  ];
  assert.deepEqual(unwrittenMoves(rows), []);
});

test("a tail shrink under a bottom reader clamps them up by the shrink: reported, explained by the tailchange row", () => {
  const rows = [
    write(1000, "land-bottom", 0, BOTTOM, true),
    tail(3000, -72, "turn turn-tool", true, SH - 72, CH),
    gesture(3010, BOTTOM - 72, SH - 72, CH),
  ];
  const moves = unwrittenMoves(rows);
  assert.equal(moves.length, 1);
  assert.equal(moves[0].explained, "tail-change");
  assert.equal(moves[0].by.dh, -72);
  assert.equal(moves[0].distAfter, 0, "the reader is still at the (new) bottom");
});

test("a top spacer re-size under anchoring moves the reader by the opposite amount: reported, explained by the spacer row", () => {
  const rows = [
    write(1000, "land-saved", 0, 5000, false),
    spacer(3000, 1000, 1064, 200, 136),                   // top grew 64, bottom shrank 64: scrollHeight unchanged
    gesture(3010, 5064),                                  // anchoring carried the reader down with the content
  ];
  const moves = unwrittenMoves(rows);
  assert.equal(moves.length, 1);
  assert.equal(moves[0].explained, "spacer");
  assert.deepEqual(moves[0].by.top, [1000, 1064]);
});

test("a tail change or spacer row of the WRONG size does not explain the move", () => {
  const rows = [
    write(1000, "land-bottom", 0, BOTTOM, true),
    tail(2000, 30.8, "turn turn-tool", true, SH + 31, CH),   // the tail grew a little; unrelated
    gesture(4400, BOTTOM - 64, SH, CH),
  ];
  const moves = unwrittenMoves(rows);
  assert.equal(moves.length, 1);
  assert.equal(moves[0].explained, "none");
  assert.equal(moves[0].by, undefined);
});

test("a read while the view has nothing to scroll (emptied for a rebuild, clamped to 0) is neither a move nor a position", () => {
  const rows = [
    write(1000, "land-bottom", 0, BOTTOM, true),
    gesture(40000, 0, 800, 800),                          // the view is empty: scrollHeight == clientHeight, top clamps to 0
    write(40100, "land-bottom", 0, BOTTOM, true),         // the rebuild lands
    gesture(40200, BOTTOM),                               // its echo
  ];
  assert.deepEqual(unwrittenMoves(rows), []);
  // …and it does not seed the next comparison either: a real snap after it is measured from the land, not from 0
  const withSnap = [...rows, gesture(43000, BOTTOM - 64)];
  const moves = unwrittenMoves(withSnap);
  assert.equal(moves.length, 1);
  assert.equal(moves[0].from, BOTTOM);
});

test("rows of several tabs are audited per tab; `sid` picks one", () => {
  const rows = [
    write(1000, "land-bottom", 0, BOTTOM, true),
    write(1000, "land-bottom", 0, 12000, true, 12900, 900, SID2),
    gesture(4400, BOTTOM - 64),                           // tab 1 snaps
    gesture(4500, 11936, 12900, 900, SID2),               // tab 2 snaps too
    ...burst(5000, BOTTOM - 64, BOTTOM),
  ];
  const all = unwrittenMoves(rows);
  assert.deepEqual(all.map((m) => [m.t, m.to]), [[4400, BOTTOM - 64], [4500, 11936]]);
  assert.deepEqual(unwrittenMoves(rows, { sid: SID2 }).map((m) => m.to), [11936]);
  // the positions of one tab never explain or seed the other's: tab 2's move is measured from ITS write
  assert.equal(all[1].from, 12000);
});

test("repeatedLandings: the fixed value is the signature; a value seen once is not one", () => {
  const moves = unwrittenMoves([
    write(1000, "land-bottom", 0, BOTTOM, true),
    gesture(4000, BOTTOM - 64), ...burst(5000, BOTTOM - 64, BOTTOM),
    gesture(8000, BOTTOM - 64), ...burst(9000, BOTTOM - 64, BOTTOM),
    gesture(12000, BOTTOM - 64), ...burst(13000, BOTTOM - 64, BOTTOM),
    gesture(16000, BOTTOM - 233),                         // a lone flick
  ]);
  assert.equal(moves.length, 4);
  assert.deepEqual(repeatedLandings(moves), [{ to: BOTTOM - 64, count: 3, distAfter: 64 }]);
});

test("client-diag lines: chat scroll rows parse with a millisecond clock (the arrival stamp when present), the rest are null", () => {
  const base = { wid: "22222222-3333-4444-8555-000000000001", surface: "chat" };
  const g = journalRowFromDiagLine(JSON.stringify({ ...base, t: 1700000000, what: "scrollgesture", data: { sid: SID, top: 10, gesture: true, sh: 100, ch: 50 } }));
  assert.deepEqual(g, { t: 1700000000000, what: "scrollgesture", data: { sid: SID, top: 10, gesture: true, sh: 100, ch: 50 } });
  const stamped = journalRowFromDiagLine(JSON.stringify({ ...base, t: 1700000000, ta: 1700000000.359, what: "scrollwrite", data: scrollWriteRow(SID, "land-bottom", 0, 10, true, 100, 50) }));
  assert.equal(stamped!.t, 1700000000359);
  assert.equal(journalRowFromDiagLine(JSON.stringify({ ...base, t: 1700000000, what: "send", data: { sid: SID } })), null, "not a scroll row");
  assert.equal(journalRowFromDiagLine(JSON.stringify({ ...base, surface: "feed", t: 1700000000, what: "scrollgesture", data: {} })), null, "not the chat");
  assert.equal(journalRowFromDiagLine("not json"), null);
  assert.equal(journalRowFromDiagLine(JSON.stringify({ ...base, what: "scrollgesture", data: {} })), null, "no clock at all");
});
