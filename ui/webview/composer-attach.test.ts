// The composer 📎 attach button opens a file picker on the machine whose SCREEN
// the user is looking at, routed by host the same way Browse… splits:
//
//   • VS Code webview → the host extension's native open dialog (type:"pickFile");
//     the editor IS the local machine, so the dialog is on the right screen and
//     the picked path comes back as droppedPath.
//   • Web dashboard (http/https, any pointer) → the BROWSER's own picker (a
//     hidden <input type=file>) and the bytes ship via shipFileToHost → dropFile.
//     The old behavior posted pickFile to the kernel, whose native dialog opens
//     on the KERNEL's machine — the wrong screen entirely from a remote browser,
//     and on a headless kernel nothing but a warning.
//   • TOUCH keeps the phone photo-picker UX (accept=image/*, the user 2026-06-17);
//     a desktop browser gets an unscoped multi-select picker — attributes set per
//     open, when the pointer type is known.
//
// The chat renderer has no jsdom harness, so — like the other webview tests —
// pin the wiring at the source level.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");

test("📎 on the web (touch or desktop) opens the BROWSER's picker, never the kernel's dialog", () => {
  // a hidden file input…
  assert.match(RENDER, /createElement\("input"\)/);
  assert.match(RENDER, /filePicker\.type = "file"/);
  // …opened from the click handler (a real gesture, required by iOS) whenever the page
  // is the web dashboard OR the pointer is touch; only VS Code desktop falls through
  assert.match(RENDER, /const isWebPage = location\.protocol === "http:" \|\| location\.protocol === "https:";/);
  assert.match(RENDER, /if \(!isTouch\(\) && !isWebPage\) return;\s*\/\/ VS Code desktop → the host-dialog path/);
  // touch is gated on pointer:coarse (a phone), NOT viewport width — desktop panes are narrow too
  assert.match(RENDER, /matchMedia\("\(pointer:coarse\)"\)\.matches/);
  // picker scope is decided PER OPEN: photos-only single pick on touch (the phone photo-picker
  // UX), any files + multi-select on a desktop browser
  assert.match(RENDER, /if \(isTouch\(\)\) \{ filePicker\.accept = "image\/\*"; filePicker\.multiple = false; \}/);
  assert.match(RENDER, /else \{ filePicker\.removeAttribute\("accept"\); filePicker\.multiple = true; \}/);
  assert.match(RENDER, /filePicker\.click\(\);/);
});

test("📎 routes the chosen files through the existing dropFile pipeline (no new path)", () => {
  // chosen files go to shipFileToHost, which already posts {type:"dropFile"} and
  // gets {type:"droppedPath"} back — we reuse it rather than add a second uploader
  assert.match(RENDER, /filePicker\.files \|\| \[\]\)\.forEach\(\(f\) => shipFileToHost\(f\)\)/);
  assert.match(RENDER, /const name = f\.name \|\| "pasted\.png";/);
  assert.match(RENDER, /\{ type: "dropFile", name, b64, shipId \}/);
});

test("📎 in the VS Code webview still uses the native host dialog (pickFile)", () => {
  // mousedown (keeps the textarea focused) bails on touch AND on the web page,
  // so the browser picker owns those; only the VS Code webview posts pickFile
  assert.match(RENDER, /addEventListener\("mousedown", \(e\) => \{\s*if \(isTouch\(\) \|\| isWebPage\) return;/);
  assert.match(RENDER, /vscodeApi\?\.postMessage\(\{ type: "pickFile" \}\)/);
});

test("shipFileToHost stamps the session id so federation routes the bytes to the OWNING kernel", () => {
  // the saved drops/ path rides the prompt and is read by the agent on the session's own
  // machine — bytes saved on any other kernel would hand the agent a nonexistent path.
  // routeOutbound routes any `id` field by host prefix (SCALAR_ID); the stamp is what
  // engages it (multi-kernel-merge.test.ts pins the routing itself). The sid is captured
  // at SHIP time (with the pending chip), not at encode time — a tab switch mid-encode
  // must not reroute the bytes away from the session the user attached them to. Callers
  // that already verified against a session (the pasted-path flow) pass THEIR captured
  // sid; the default keeps ship-time capture for everyone else.
  assert.match(RENDER, /function shipFileToHost\(f: File, sidAt: string \| null = activeId, kind: PendingShip\["kind"\] = "composer"\)/);
  assert.match(RENDER, /const sid = sidAt;/);
  assert.match(RENDER, /if \(sid\) msg\.id = sid;\s*\/\/ the owning session → the owning kernel/);
});

test("a REMOTE session's drops and pastes ship BYTES — a local path never rides its prompt", () => {
  // The user (2026-08-11) dragged a laptop screenshot into a server-hosted session's chat: the drop
  // handler preferred the path branches (File.path / text/uri-list), so the prompt carried a path
  // that exists only on the laptop, and the agent on the server couldn't open it. The path branches
  // are a LOCAL-session fast path (zero-copy, the agent reads the original file); a session owned by
  // a remote host (hostOf) skips them and ships the bytes through the same dropFile route the phone
  // already rides — the saved drops/ path comes back valid on the machine the agent reads.
  assert.match(RENDER, /const remote = hostOf\(activeId \|\| ""\);/);
  assert.match(RENDER, /if \(!remote\) \{\s*\n\s*const p = \(f as any\)\.path as string \| undefined;/,
    "the drop's path branches are gated on local ownership");
  assert.match(RENDER, /if \(p && !hostOf\(activeId \|\| ""\)\) addComposerFile\(activeId, p\);/,
    "the paste's path branch wears the same gate");
  // a path-only drag (no File objects — nothing to ship) is a dead end for a remote session,
  // and it is SAID, never silently mis-attached
  assert.match(RENDER, /That drag carried only this machine's path, which/);
  assert.match(RENDER, /drop the file itself \(or paste it\) and the bytes will be shipped over\./);
});

test("an oversize file is refused LOUDLY — named size and cap in a toast, never a silent return", () => {
  // one cap constant, checked before the read; drag-drop, paste and both pickers all
  // funnel through shipFileToHost, so the toast covers every arrival path
  assert.match(RENDER, /const SHIP_MAX_BYTES = 50 \* 1024 \* 1024;/);
  assert.match(RENDER, /if \(f\.size > SHIP_MAX_BYTES\) \{/);
  // the refusal names the file, its actual size, and the 50 MB cap
  assert.match(RENDER, /warnToast\(\(f\.name \|\| "This file"\) \+ " is " \+ \(f\.size \/ \(1024 \* 1024\)\)\.toFixed\(1\)/);
  assert.match(RENDER, /attachments over 50 MB can't be shipped, so it was not attached\./);
  // the bare silent return is gone
  assert.doesNotMatch(RENDER, /too big to ship over postMessage/);
});
