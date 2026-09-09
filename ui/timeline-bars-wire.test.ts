// The bars frame's wire shape, the view's half of the round trip (T278b/T278c): tests/test_timeline_bars_wire.py
// pins that the kernel encodes the fixture's `old` bars into its `wire` bars (id/start/end by name, the rest under
// one-letter keys with defaults omitted, the first prompt line) and its flat judging into per-lane compact entries;
// this test pins that the view's expanders give every reader back exactly what it read before, that untouched
// lanes keep their identity, and that hover and anchors still resolve. The fixture is synthetic.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { createRequire } from "node:module";

const viewPath = path.resolve(process.cwd(), "..", "ui", "romp-timeline-view.js");
const { reqText, workAnchorOf, dotLit, barLit, expandBar, expandBars, expandJudging } = createRequire(__filename)(viewPath);
const fx = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "..", "tests", "fixtures", "timeline-bars-wire.json"), "utf8"));
const DROPPED = ["tid", "uuid", "workUuid"];

test("the fixture carries the same bars in both shapes, and the wire carries no long names", () => {
  assert.equal(fx.old.length, fx.wire.length);
  assert.ok(fx.old.length >= 5);
  for (const w of fx.wire) {
    for (const gone of DROPPED.concat(["promptId", "workId", "replyUuid", "prompt", "summary", "msgCaption", "src", "mids", "pending", "nudgeAuto", "romp", "cont", "open"])) assert.equal(gone in w, false, gone + " left the wire");
    for (const kept of ["id", "start", "end"]) assert.ok(kept in w, kept + " rides by name");
  }
});

test("expanding a wire bar gives back the old bar, minus the three duplicates, with defaults filled", () => {
  for (const [o, w] of fx.old.map((o: any, i: number) => [o, fx.wire[i]])) {
    const want: any = {};
    for (const k in o) if (!DROPPED.includes(k)) want[k] = o[k];
    want.prompt = fx.wire_prompt[fx.old.indexOf(o)];   // the kernel's first-line shaping, from the fixture
    want.pending = false;
    assert.deepEqual(expandBar(w), want, o.id);
    assert.equal(reqText(expandBar(w).prompt), reqText(o.prompt), "the tip text is unchanged");
    assert.equal(workAnchorOf(expandBar(w)), o.replyUuid || o.workUuid || o.uuid || null);
  }
});

test("a long-named bar passes through the expander with its defaults filled", () => {
  const b = { id: "x", start: 1, end: 2, promptId: "p", summary: "s", tid: "fork-1" };
  const e = expandBar(b);
  assert.equal(e.promptId, "p"); assert.equal(e.summary, "s"); assert.equal(e.src, "typed"); assert.deepEqual(e.mids, []);
  assert.equal(e.open, false); assert.equal(e.pending, false); assert.equal(e.tid, "fork-1", "an extra field rides through");
});

test("an untouched lane expands once and keeps its identity across frames", () => {
  const lane = fx.wire.slice();
  const a = expandBars({ [fx.sid]: lane }), b = expandBars({ [fx.sid]: lane });
  assert.equal(a[fx.sid], b[fx.sid], "the same wire array expands to the same array");
  assert.notEqual(expandBars({ [fx.sid]: fx.wire.slice() })[fx.sid], a[fx.sid], "a new wire array is a new expansion");
});

test("compact judging expands to the flat entries every reader saw", () => {
  assert.deepEqual(expandJudging(fx.judging_wire), fx.judging_long);
  assert.deepEqual(expandJudging([]), []);
  assert.deepEqual(expandJudging({}), []);
  const legacy = [{ judge: "closer", sid: fx.sid, t: 1 }];
  assert.equal(expandJudging(legacy), legacy, "a legacy list passes through untouched");
});

test("hover matching reads only id, promptId and workId, which the wire still carries", () => {
  for (const w of fx.wire) {
    const e = expandBar(w);
    assert.equal(dotLit(e, (x: string) => x === e.promptId), !!e.promptId);
    assert.equal(barLit(e, (x: string) => x != null && x === e.workId), !!e.workId);
  }
});
