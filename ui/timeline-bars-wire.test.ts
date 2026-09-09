// The bars frame's wire shape (T278b), the view's half of the round trip: tests/test_timeline_bars_wire.py pins
// that the kernel encodes the fixture's `old` bars into its `wire` bars (the first prompt line, capped; no tid,
// uuid or workUuid); this test pins that the view renders a `wire` bar exactly as it rendered the `old` one:
// the same tip text (reqText), the same work anchor (workAnchorOf), the same prompt anchor and lane. The
// fixture is synthetic (invented prompts, placeholder ids).
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { createRequire } from "node:module";

const viewPath = path.resolve(process.cwd(), "..", "ui", "romp-timeline-view.js");
const { reqText, workAnchorOf, dotLit, barLit } = createRequire(__filename)(viewPath);
const fx = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "..", "tests", "fixtures", "timeline-bars-wire.json"), "utf8"));

test("the fixture carries the same bars in both shapes", () => {
  assert.equal(fx.old.length, fx.wire.length);
  assert.ok(fx.old.length >= 5);
  for (const w of fx.wire) for (const gone of ["tid", "uuid", "workUuid"]) assert.equal(gone in w, false, gone + " left the wire");
});

test("the tip renders the wire prompt exactly as it rendered the full prompt", () => {
  for (const [o, w] of fx.old.map((o: any, i: number) => [o, fx.wire[i]])) {
    assert.equal(reqText(w.prompt), reqText(o.prompt), o.id);
    assert.ok(reqText(w.prompt).length <= 92, "at most 90 chars plus the ellipsis");
  }
});

test("the work anchor, the prompt anchor and the lane derive to the old values", () => {
  for (const [o, w] of fx.old.map((o: any, i: number) => [o, fx.wire[i]])) {
    assert.equal(workAnchorOf(w), o.replyUuid || o.workUuid || o.uuid || null, o.id);
    assert.equal(w.promptId, o.uuid, "the prompt-dot anchor was always the promptId");
    assert.equal(w.workId, o.workUuid, "the work anchor's second rung was always the workId");
    assert.equal(fx.sid, o.tid, "the lane key is the tid every bar carried");
  }
});

test("hover matching reads only id, promptId and workId, which the wire still carries", () => {
  for (const w of fx.wire) {
    const hit = (x: string) => x === w.promptId;
    assert.equal(dotLit(w, hit), true);
    assert.equal(barLit(w, (x: string) => x != null && x === w.workId), !!w.workId);   // a null workId lights nothing
  }
});
