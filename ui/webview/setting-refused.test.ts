// The kernel's `settingRefused` frame: a dashboard gesture that edits a small state store (a lane/tab flag,
// a card bell, a drag) was REFUSED because the store could not be read, and the refusal is answered on the
// posting socket, addressed to the gesture (sid / itemId / flag). The rule it exists for: a refused gesture
// must reach the eye that made it AND end the optimistic state on that event. Before it, the kernel sent a
// `warn`, which only the chat page renders -- a refused bell on the feed page and a refused lane flag on the
// timeline page stayed painted as if they had landed until a reload, their sticky latches never released.
// No jsdom for the renderers, so the pane handlers are pinned at source (the card-notify / undelivered-err
// pattern); the boot dispatch is exercised for real.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { dispatchFrame } from "./timeline-boot";

const ROOT = path.resolve(process.cwd(), "..");
const KERNEL = fs.readFileSync(path.join(ROOT, "kernel", "kernel.py"), "utf8");
const VIEW = fs.readFileSync(path.join(ROOT, "ui", "romp-timeline-view.js"), "utf8");
const FEED = fs.readFileSync(path.join(ROOT, "ui", "webview", "feed.ts"), "utf8");
const RENDER = fs.readFileSync(path.join(ROOT, "ui", "webview", "render.ts"), "utf8");
const BOOT = fs.readFileSync(path.join(ROOT, "ui", "webview", "timeline-boot.ts"), "utf8");

test("the kernel answers a refused store write on the DELIVERING socket, addressed to the gesture", () => {
  const fn = KERNEL.slice(KERNEL.indexOf("def _refuse_setting("), KERNEL.indexOf("\ndef _session_order():"));
  assert.match(fn, /_reply\(client, \{"type": "settingRefused", "gesture": str\(gesture\), "sid": str\(sid or ""\),\n\s+"itemId": str\(item_id or ""\), "flag": str\(flag or ""\),\n\s+"value": value if isinstance\(value, bool\) else None, "text": text\}\)/);
  assert.match(fn, /if not client or not callable\(client\.get\("send"\)\):\n\s+return/, "a dead socket is the client's problem; the refusal already stands");
  // every store-fault arm of _dispatch_ws refuses through it, naming its gesture -- the flag toggle carries
  // sid + flag + the value the kernel still paints, the bell the card + its painted value, the drag neither
  // (no shipped pane posts it; the contract holds all the same)
  assert.match(KERNEL, /_refuse_setting\(client, e, "that setting", "flag", sid=msg\["id"\], flag=msg\["flag"\],\n\s+value=_painted_flag_value\(str\(msg\["id"\]\), str\(msg\["flag"\]\)\)\)/);
  assert.match(KERNEL, /_refuse_setting\(client, e, "that bell", "bell", sid=msg\.get\("sid"\) or "", item_id=msg\["itemId"\],\n\s+value=bool\(_notify_card_effective\(_notify_cards\(\), str\(msg\["itemId"\]\), str\(msg\.get\("sid"\) or ""\)\)\)\)/);
  assert.match(KERNEL, /_refuse_setting\(client, e, "the new order", "order"\)/);
  // ...and none of those except blocks still sends the frame no pane but the chat renders
  for (const what of ['"that setting", "flag"', '"that bell", "bell"', '"the new order", "order"']) {
    const call = KERNEL.indexOf("_refuse_setting(client, e, " + what);
    assert.ok(call > 0, what);
    const block = KERNEL.slice(KERNEL.lastIndexOf("except _StateUnreadable as e:", call), call);
    assert.doesNotMatch(block, /"type": "warn"/, "no store-fault arm answers with a warn frame: " + what);
  }
});

test("both timeline boots (VS Code and the kernel's inline browser twin) hand the frame to the panel", () => {
  assert.match(BOOT, /if \(m\.type === "settingRefused" && panel\.settingRefused\) \{ panel\.settingRefused\(m\); return true; \}/);
  const bootStart = KERNEL.indexOf("_TIMELINE_BOOT = ");
  const boot = KERNEL.slice(bootStart, KERNEL.indexOf('"""', bootStart + 60));
  assert.match(boot, /else if\(m\.type==="settingRefused"&&panel\.settingRefused\)panel\.settingRefused\(m\);/);
  // for real: the frame reaches the panel method, an older panel without it is skipped, never thrown at
  const got: any[] = [];
  assert.equal(dispatchFrame({ settingRefused: (m: any) => got.push(m) }, { type: "settingRefused", sid: "s1", flag: "notify", text: "couldn't save that setting" }), true);
  assert.equal(got[0].flag, "notify");
  assert.equal(dispatchFrame({}, { type: "settingRefused" }), false);
});

test("timeline: the lane gear's latch drops, the lane repaints to the kernel's painted value, the gear says why", () => {
  const fn = VIEW.slice(VIEW.indexOf("  settingRefused(m) {"), VIEW.indexOf("\n  }", VIEW.indexOf("  settingRefused(m) {")));
  assert.match(fn, /if \(m && m\.gesture === 'flag' && sid && flag\) \{/, "the frame names its gesture; nothing is inferred from empty fields");
  // the sticky latch for THAT sid+flag is released (a push no longer re-applies the refused value)
  assert.match(fn, /const pend = this\._pendingFlags\[sid\];\n\s+if \(pend\) \{ delete pend\[flag\];/);
  // the value the kernel still paints (carried by the frame) lands on both copies a click may have written --
  // never a value recorded at the click, which a second click before the first refusal made wrong
  assert.match(fn, /if \(typeof m\.value === 'boolean'\) \{/);
  assert.match(fn, /for \(const s of targets\) if \(s\) s\[flag\] = m\.value;/);
  assert.doesNotMatch(VIEW, /_pendingFlagsPrev/, "no per-flag pre-click slot remains");
  // the refusal is shown in the gear (rebuilt in place if open) and filed in the shell's bell under its own kind
  assert.match(fn, /this\._laneRefusal = \{ sid, flag, text \};/);
  assert.match(fn, /if \(this\._laneMenu && this\._laneMenu\._sid === sid && this\._laneMenuBuild\) this\._laneMenuBuild\(\);/);
  assert.match(fn, /window\.parent\.postMessage\(\{ romp: 'notify', kind: 'refused', text, sid \}, '\*'\);/);
  assert.match(fn, /this\.draw\(\);/);
  // the gear renders the refusal row for THIS lane, dismissible, in the dialog's refusal dress
  assert.match(VIEW, /if \(this\._laneRefusal && this\._laneRefusal\.sid === s\.id\) \{\n\s+const er = menu\.createDiv\(\);/);
  assert.match(VIEW, /er\.createSpan\(\{ text: '⚠ ' \+ this\._laneRefusal\.text \}\);/);
  assert.match(VIEW, /ex\.addEventListener\('click', \(e\) => \{ e\.stopPropagation\(\); this\._laneRefusal = null; build\(\); \}\);/);
  assert.match(VIEW, /this\._laneMenuBuild = build;/);
});

test("feed: the card bell's latch drops, the card repaints, the reason toasts (soft) and is filed in the bell", () => {
  const i = FEED.indexOf('} else if (m.type === "settingRefused" && typeof m.text === "string" && m.text) {');
  assert.ok(i > 0, "the feed page handles the frame");
  const arm = FEED.slice(i, FEED.indexOf('} else if (m.type === "err"', i));
  assert.match(arm, /if \(m\.gesture === "bell" && typeof m\.itemId === "string" && m\.itemId\) pendingNotify\.delete\(m\.itemId\);/);
  assert.match(arm, /\n\s+render\(\);/, "the repaint follows the release: the paint key reads the latch");
  // a bell toggle is a SOFT refusal (nothing typed was lost): the fading toast, never the must-dismiss dialog
  assert.match(arm, /feedToast\(m\.text\);/);
  assert.doesNotMatch(arm, /showErrDialog/);
  assert.match(arm, /window\.parent\?\.postMessage\(\{ romp: "notify", kind: "refused", text: m\.text,/);
  // the release precedes the paint, and the paint key still reads the latch (else the bell would not repaint)
  assert.ok(arm.indexOf("pendingNotify.delete") < arm.indexOf("render();"));
  assert.match(FEED, /\+ "\|" \+ \(pendingNotify\.has\(it\.itemId\) \? String\(pendingNotify\.get\(it\.itemId\)\) : ""\)/);
  // and the page still has NO warn handler: undelivered-err.test.ts pins that, and it stays true on purpose
  assert.doesNotMatch(FEED, /m\.type === "warn"/);
});

test("chat: the tab menu's local copy repaints to the kernel's painted value, the reason toasts and is filed", () => {
  assert.doesNotMatch(RENDER, /pendingFlagPrev/, "no per-flag pre-click slot remains");
  const i = RENDER.indexOf('else if (m.type === "settingRefused" && typeof m.text === "string" && m.text) {');
  assert.ok(i > 0, "the chat page handles the frame");
  const arm = RENDER.slice(i, RENDER.indexOf('else if (m.type === "warn"', i));
  assert.match(arm, /if \(m\.gesture === "flag" && typeof m\.sid === "string" && typeof m\.flag === "string" && m\.sid && m\.flag\) \{/);
  assert.match(arm, /if \(s && typeof m\.value === "boolean"\) \(s as any\)\[m\.flag\] = m\.value;/);
  assert.match(arm, /notifyShell\("refused", m\.text, typeof m\.sid === "string" \? m\.sid : ""\);/);
  assert.match(arm, /warnToast\(m\.text\);/);
});

test("the shell's bell knows the `refused` kind: listed, labelled, explained, and worn in the warning yellow", () => {
  // KINDS drives the filter row, KINDLBL the chip, DESC the tooltip -- a kind missing from any of the three
  // renders as an unlabelled entry with no way to mute it. Its own kind, so muting `warn` (the judge's
  // anomaly stamp) never mutes a change of yours that did not land
  assert.match(KERNEL, /var KINDS=\[[^\]]*'refused','undelivered'\]/);
  assert.match(KERNEL, /refused:'not saved'/);
  assert.match(KERNEL, /refused:"a change you made \\u2014 a lane or tab setting, a card bell, a tag or view, a lane order \\u2014 was not saved because romp could not read the file that holds it/);
  assert.match(KERNEL, /\.rerr-chip\.k-refused\{color:#ffd166;border-color:rgba\(255,209,102,0\.6\)\}/);
  // and every pane files under it -- none under `warn`
  for (const src of [FEED, RENDER, VIEW]) assert.doesNotMatch(src.slice(src.indexOf("settingRefused")), /kind: ['"]warn['"]/);
});

