// The + dialog's HOST picker (federation, the user 2026-07-02): this machine | each attached SSH host,
// so a new session can be created ON a remote kernel (the federation manager routes createSession over
// that host's tunnel; the tab arrives prefixed host:name). Source-pin over render.ts, like
// picker-backend.test.ts.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");

test("the + dialog builds a Host row listing local + attached hosts, hidden with none attached", () => {
  assert.match(RENDER, /const hostWrap = el\("div", "picker-backend picker-host"\)/);
  assert.match(RENDER, /box\.appendChild\(hostWrap\)/);
  // options rebuilt each open from the federation manager's live host list
  assert.match(RENDER, /__rompFed\?\.hosts\?\.\(\)/);
  assert.match(RENDER, /hostWrapEl\.style\.display = pick \|\| !hosts\.length \? "none" : ""/);
});

test("the this-machine option wears the machine's REAL name, not 'local' (the user 2026-08-12)", () => {
  // the name is the kernel's peer identity (_self_host — short hostname, ROMP_HOST_NAME override),
  // carried on the local sessionList reply; the row then reads as a list of machines by name
  const KERNEL = fs.readFileSync(path.resolve(process.cwd(), "..", "kernel", "kernel.py"), "utf8");
  assert.match(KERNEL, /"selfHost": _self_host\(\)/);
  assert.match(RENDER, /b\.textContent = h \|\| localSelfHost \|\| "local"/);
  // the Host row is built on open, BEFORE the reply lands — the handler relabels the button in
  // place, so only the first-ever open briefly shows the "local" placeholder
  assert.match(RENDER, /if \(typeof m\.selfHost === "string" && m\.selfHost && !from\) \{\s*\n\s*localSelfHost = m\.selfHost;/);
  assert.match(RENDER, /querySelector\('#picker \.picker-host \.picker-be-opt\[data-host=""\]'\)/);
  // …and the adoption sits BEFORE the stale-list drop guard: the name is this machine's identity,
  // not list data — switching the picker to a remote host before the local reply lands must not
  // throw the name away with the (rightly dropped) stale list
  const adopt = RENDER.indexOf("localSelfHost = m.selfHost");
  const drop = RENDER.indexOf("if (from !== pickerListHost) return;");
  assert.ok(adopt >= 0 && drop >= 0 && adopt < drop, "selfHost is adopted before the stale-list drop");
});

test("createSession carries the picked host (empty = local) so the manager routes it to that kernel", () => {
  assert.match(RENDER, /const hostSel = \(hostWrap\.querySelector\("\.picker-be-opt\.sel"\) as HTMLElement \| null\)\?\.dataset\.host \|\| ""/);
  // (…the Tags row's picks ride the same request since tab groups, 2026-09-04)
  assert.match(RENDER, /startCreate\(\{ name, backend,\s*\n\s*dir: dirInput\.value\.trim\(\), host: hostSel, \.\.\.\(auth \? \{ auth \} : \{\}\), \.\.\.\(tags\.length \? \{ tags \} : \{\}\) \}\)/);
  // the PROVISIONAL tab (2026-07-30, which replaced the "Opening…" cue) must be matched against the
  // PREFIXED tab name a remote create produces — provisionalName() is where that join is spelled
  assert.match(RENDER, /openProvisional\(req\);/);
});

test("picking a remote host disables the (host-local) Browse… dialog", () => {
  // The disable moved into applyBrowseState, which also hides the button on a kernel with no desktop at
  // all — see picker-dir.test.ts. The host row's job is unchanged: pick remote, lose Browse.
  assert.match(RENDER, /applyBrowseState\(h\);/);
  assert.match(RENDER, /function applyBrowseState\(host: string\)[\s\S]*?b\.disabled = !!host;/);
});
