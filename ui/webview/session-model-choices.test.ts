// The custom-model option reaches the SESSION pickers only (the user 2026-08-13).
//
// /models serves two model lists: `models` is the Claude ladder, which the judge-tier dropdowns read
// and _set_judge_model validates against; `sessionModels` adds the CLI's ANTHROPIC_CUSTOM_MODEL_OPTION
// and is what a per-session picker should read. Get this backwards and the gear offers the judges a
// value the kernel then silently refuses — a control that quietly does nothing.
//
// Source-level pins, in the style of gear.test.ts: the wiring is a one-line choice in three files, and
// what matters is which list each surface reaches for.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const ROOT = path.resolve(process.cwd(), "..");
const read = (...p: string[]) => fs.readFileSync(path.join(ROOT, ...p), "utf8");
const KERNEL = read("bin", "romp-kernel");
const CHAT = read("ui", "webview", "render.ts");
const TIMELINE = read("ui", "romp-timeline-view.js");
const GEAR = read("ui", "webview", "gear.js");

test("the kernel serves both lists, and only the session one carries the extra", () => {
  assert.match(KERNEL, /"sessionModels": _session_model_choices\(\)/,
    "/models must publish the session list alongside the ladder");
  assert.match(KERNEL, /"models": MODEL_CHOICES/,
    "`models` stays the Claude ladder — the judge dropdowns read it");
});

for (const [surface, src] of [["chat statusline", CHAT], ["timeline lane", TIMELINE]] as const) {
  test(`the ${surface} picker prefers sessionModels, falling back to models`, () => {
    assert.match(src, /Array\.isArray\(d\.sessionModels\) \? d\.sessionModels : d\.models/,
      "a session picker takes the extra when the kernel offers it, and still works against an older kernel");
  });
}

test("the gear's judge dropdowns keep reading the Claude-only list", () => {
  assert.ok(!GEAR.includes("sessionModels"),
    "the judge tiers validate against _MODEL_VALUES — offering them the routed model would refuse the pick");
  assert.match(GEAR, /choices\.models/, "…so they stay on `models`");
});
