// judgingToWire in federation.ts is the twin of the kernel's _compact_judging: an older kernel's flat judging list
// converts to the per-lane compact shape the pane expands (T278c). The shared fixture pins both against the same
// synthetic entries: the Python side pins encode(judging_old) == judging_wire; this pins the twin gives the same.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { judgingToWire } from "./federation";

const fx = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "..", "tests", "fixtures", "timeline-bars-wire.json"), "utf8"));

test("the federation twin compacts a flat judging list exactly as the kernel does", () => {
  assert.deepEqual(judgingToWire(fx.judging_old), fx.judging_wire);
});

test("a per-lane map passes through, and nothing else becomes a map", () => {
  assert.equal(judgingToWire(fx.judging_wire), fx.judging_wire);
  assert.deepEqual(judgingToWire(null), {});
  assert.deepEqual(judgingToWire([]), {});
});
