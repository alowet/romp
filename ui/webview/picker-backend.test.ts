// A per-session backend picker on the + dialog (the user 2026-06-23): a segmented toggle, defaulting to the
// gear's Default backend but overridable for THIS new session. Since T288 (the user 2026-09-09) the toggles
// read "Claude Code", "Claude Code (tmux)" and "Codex" from backend-names.ts, and "Claude Code (tmux)" is on
// offer only while the kernel setting says so (off by default; the local sessionList reply carries it).
// Source-pin over render.ts.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const CSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "styles.css"), "utf8");

test("the + dialog builds a Claude Code | Claude Code (tmux) | Codex backend toggle from the shared names, hidden in pick-mode", () => {
  assert.match(RENDER, /import \{ backendLabel, effectiveDefaultBackend \} from "\.\/backend-names";/);
  assert.match(RENDER, /const beWrap = el\("div", "picker-backend"\)/);
  assert.match(RENDER, /mkBe\("sdk", backendLabel\("sdk"\)/);
  assert.match(RENDER, /mkBe\("tmux", backendLabel\("tmux"\)/);
  assert.match(RENDER, /mkBe\("codex", backendLabel\("codex"\)/);
  assert.match(RENDER, /box\.appendChild\(beWrap\)/);
  // hidden + reset to the EFFECTIVE default each open (a saved tmux default while the backend is off → Claude Code)
  assert.match(RENDER, /beWrapEl\.style\.display = pick \? "none" : ""/);
  assert.match(RENDER, /const def = effectiveDefaultBackend\(loadSettings\(\)\.backend, kernelTmuxBackend\);/);
  assert.match(RENDER, /\.classList\.toggle\("sel", \(x as HTMLElement\)\.dataset\.be === def\)\);\s*\n\s*syncPickerBackends\(\);/, "the offer is applied on every open");
});

test("the tmux toggle is on offer only while the kernel setting is on: absent when off, present when on (T288)", () => {
  // the setting rides the LOCAL sessionList reply; assumed off until a kernel says on
  assert.match(RENDER, /let kernelTmuxBackend = false;/);
  assert.match(RENDER, /if \(typeof m\.tmuxBackend === "boolean" && !from\) \{ kernelTmuxBackend = m\.tmuxBackend; syncPickerBackends\(\); \}/);
  const sync = RENDER.slice(RENDER.indexOf("function syncPickerBackends(): void {"), RENDER.indexOf("\n}\n", RENDER.indexOf("function syncPickerBackends(): void {")));
  assert.match(sync, /const tmuxBtn = wrap\.querySelector\('\.picker-be-opt\[data-be="tmux"\]'\) as HTMLElement \| null;/);
  assert.match(sync, /tmuxBtn\.style\.display = kernelTmuxBackend \? "" : "none";/, "off → the toggle is not shown; on → it is");
  // the reply lands AFTER the open reset the row: the effective default is re-applied while the user has not
  // picked this open (a saved tmux default lands once the toggle is on offer), and a selected toggle that went
  // off offer always hands the selection back, so the create never sends a backend the picker does not show;
  // an explicit pick made this open is never undone
  assert.match(RENDER, /let pickerBackendPicked = false;/);
  assert.match(RENDER, /b\.addEventListener\("click", \(\) => \{ pickerBackendPicked = true; beWrap\.querySelectorAll/, "a click is an explicit pick");
  assert.match(RENDER, /pickerBackendPicked = false;   \/\/ a fresh open/, "each open forgets the last pick");
  assert.match(sync, /const def = effectiveDefaultBackend\(loadSettings\(\)\.backend, kernelTmuxBackend\);\s*\n\s*const cur = wrap\.querySelector\("\.picker-be-opt\.sel"\) as HTMLElement \| null;\s*\n\s*if \(!pickerBackendPicked \|\| \(!kernelTmuxBackend && cur\?\.dataset\.be === "tmux"\)\) \{/);
  assert.match(sync, /syncPickerAuth\(\); syncPickerTags\(\);/, "the Billing and Tags rows follow the new choice");
  // the kernel's reply carries the setting as a boolean, off by default
  const KERNEL = fs.readFileSync(path.resolve(process.cwd(), "..", "kernel", "kernel.py"), "utf8");
  assert.match(KERNEL, /"tmuxBackend": jd\._state_str\("tmux-backend", "off"\) == "on",/, "the sessionList reply");
});

test("createSession uses the picked backend, falling back to the EFFECTIVE gear default", () => {
  assert.match(RENDER, /const beSel = beWrap\.querySelector\("\.picker-be-opt\.sel"\)/);
  assert.match(RENDER, /const backend = beSel\?\.dataset\.be \|\| effectiveDefaultBackend\(loadSettings\(\)\.backend, kernelTmuxBackend\);/);
  assert.match(RENDER, /return beSel\?\.dataset\.be \|\| effectiveDefaultBackend\(loadSettings\(\)\.backend, kernelTmuxBackend\);/, "pickerBackendChoice too");
  assert.match(RENDER, /startCreate\(\{ name, backend,/);
});

test("the toggle's selected option is the romp ACCENT (the user 2026-06-24), not the working-yellow", () => {
  assert.match(CSS, /\.picker-be-opt\.sel \{[^}]*background: var\(--accent\)/);
  assert.doesNotMatch(CSS, /\.picker-be-opt\.sel \{[^}]*background: var\(--st-working-bg\)/);
});
