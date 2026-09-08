// The usage modal's "your order" (T247f) arranges the kernel's shared seed by the viewer's own drag order —
// the SAME algorithm the tab strip and the timeline lanes apply (view-order.ts applyViewOrder). The landing
// page loads no webview bundle, so the modal carries a twin inside kernel.py's _LANDING_USAGE_JS; this test
// runs that twin against the module on the same inputs, so the two cannot drift.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { applyViewOrder } from "./view-order";

const ROOT = path.resolve(process.cwd(), "..");
const KERNEL = fs.readFileSync(path.join(ROOT, "kernel", "kernel.py"), "utf8");

function twin(): (seed: readonly string[], view: readonly string[]) => string[] {
  const usageJS = KERNEL.split('_LANDING_USAGE_JS = """')[1].split('"""')[0];
  const line = usageJS.split("\n").find((l) => l.startsWith("function spApplyViewOrder(seed,view){"));
  assert.ok(line, "the landing JS carries spApplyViewOrder on one line");
  // eslint-disable-next-line @typescript-eslint/no-implied-eval
  return new Function(line + "; return spApplyViewOrder;")();
}

test("the landing's spApplyViewOrder is view-order.ts applyViewOrder, input for input", () => {
  const f = twin();
  const cases: Array<[any[], any[]]> = [
    [["a", "b", "c"], []],
    [["a", "b", "c"], ["c", "a"]],
    [["a", "b", "c"], ["zzz", "b"]],
    [["a", "a", "b", 7 as any, null as any], ["b", "b", "a"]],
    [["h1:x", "y", "h2:z"], ["h2:z", "y"]],
    [[], ["a"]],
    [["a"], [1 as any, undefined as any]],
    [["constructor", "toString", "__proto__", "a"], ["a", "__proto__"]],   // ids that collide with Object.prototype keys
  ];
  for (const [seed, view] of cases) {
    assert.deepEqual(f(seed as any, view as any), applyViewOrder(seed as any, view as any), JSON.stringify([seed, view]));
  }
});
