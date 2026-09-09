// The backends as the user reads them (T288, the user 2026-09-09): "Claude Code" (the default, no qualifier),
// "Claude Code (tmux)" (offered only while the kernel setting is on) and "Codex"; the ids and the protocol are
// unchanged. One module names them for the picker, the gear and the tooltip, so the surfaces cannot drift apart.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { BACKEND_LABEL, backendLabel, offeredBackends, effectiveDefaultBackend } from "./backend-names";

const read = (...p: string[]) => fs.readFileSync(path.resolve(process.cwd(), "..", ...p), "utf8");
const RENDER = read("ui", "webview", "render.ts");
const GEAR = read("ui", "webview", "gear.js");

test("the three names, and an unknown id reads as itself", () => {
  assert.deepEqual(BACKEND_LABEL, { sdk: "Claude Code", tmux: "Claude Code (tmux)", codex: "Codex" });
  assert.equal(backendLabel("sdk"), "Claude Code");
  assert.equal(backendLabel("tmux"), "Claude Code (tmux)");
  assert.equal(backendLabel("codex"), "Codex");
  assert.equal(backendLabel("future"), "future", "never a lie, never blank");
  assert.equal(backendLabel(null), "");
  for (const label of Object.values(BACKEND_LABEL)) assert.doesNotMatch(label, /\bSDK\b/, "the word never reaches the user");
});

test("the offer: Claude Code (tmux) only while the setting is on; the default falls back to Claude Code", () => {
  assert.deepEqual(offeredBackends(false), ["sdk", "codex"]);
  assert.deepEqual(offeredBackends(true), ["sdk", "tmux", "codex"]);
  assert.equal(effectiveDefaultBackend("tmux", false), "sdk", "a saved tmux default is set aside while the backend is off");
  assert.equal(effectiveDefaultBackend("tmux", true), "tmux", "…and returns with the setting");
  assert.equal(effectiveDefaultBackend("codex", false), "codex");
  assert.equal(effectiveDefaultBackend("sdk", false), "sdk");
  assert.equal(effectiveDefaultBackend(undefined, false), "sdk", "no preference is the default");
  assert.equal(effectiveDefaultBackend("", true), "sdk");
});

test("no user-facing copy in the picker, the tooltip or the gear says SDK; every label comes from the shared names", () => {
  // the picker toggles and the tooltip row read backendLabel; the gear's select spells the same three names
  assert.match(RENDER, /mkBe\("sdk", backendLabel\("sdk"\)/);
  assert.match(RENDER, /mkBe\("tmux", backendLabel\("tmux"\)/);
  assert.match(RENDER, /mkBe\("codex", backendLabel\("codex"\)/);
  assert.match(RENDER, /rows\.push\(\["Backend", backendLabel\(be\)\]\)/, "the tab tooltip's Backend row");
  assert.match(GEAR, /<option value=sdk>Claude Code<\/option><option value=tmux>Claude Code \(tmux\)<\/option><option value=codex>Codex<\/option>/);
  // the word "SDK" in a string a person reads: the picker tips, the tooltip row, the gear's HTML. Comments and
  // identifiers (status.backend === "sdk", sdkOnly) are not copy; only quoted strings count here.
  const pickerTips = [...RENDER.matchAll(/mkBe\("[a-z]+", backendLabel\("[a-z]+"\), "([^"]*)"\)/g)].map((m) => m[1]);
  assert.equal(pickerTips.length, 3);
  for (const tip of pickerTips) assert.doesNotMatch(tip, /\bSDK\b/, tip);
  // …and every quoted string in the picker's builder (the Tags note among them, the review's find)
  const picker = RENDER.slice(RENDER.indexOf('const beWrap = el("div", "picker-backend")'), RENDER.indexOf("actions.appendChild(newSess)"));
  assert.ok(picker.length > 1000 && picker.length < 40000, "the picker's builder located");
  for (const m of picker.matchAll(/"([^"\n]*)"|`([^`\n]*)`/g)) assert.doesNotMatch(m[1] || m[2] || "", /\bSDK\b/, (m[1] || m[2] || "").slice(0, 80));
  // the kernel's own copy that names a backend to the user (warn toasts, refusals) reads the shared names too
  const KERNEL = read("kernel", "kernel.py");
  for (const phrase of ["needs the SDK backend", "need an SDK or Codex session", "needs an SDK session", "runs on tmux, so there is nothing", "tmux sessions still work"])
    assert.ok(!KERNEL.includes(phrase), "kernel copy still says: " + phrase);
  const gearHtml = GEAR.slice(0, GEAR.indexOf("var gclock") > 0 ? GEAR.length : GEAR.length);
  const userStrings = [...gearHtml.matchAll(/'([^'\n]*<span class=rs-sub>[^'\n]*)'/g)].map((m) => m[1]);
  for (const s of userStrings) assert.doesNotMatch(s, /\bSDK\b/, s.slice(0, 80));
});
