// The kernel's `settingRefused` frame: a dashboard gesture that edits a small state store (a lane/tab flag,
// a card bell, a drag) was REFUSED because the store could not be read -- or, since the maintainer's fold on
// PR #1019, because its publish failed (_StateUnwritable) -- and the refusal is answered on the
// posting socket, addressed to the gesture (sid / itemId / flag). The rule it exists for: a refused gesture
// must reach the eye that made it AND end the optimistic state on that event. Before it, the kernel sent a
// `warn`, which only the chat page renders -- a refused bell on the feed page and a refused lane flag on the
// timeline page stayed painted as if they had landed until a reload, their sticky latches never released.
// The feed and chat handlers are pinned at source (the card-notify / undelivered-err pattern: their pages
// need a DOM); the timeline's runs for real -- romp-timeline-view.js loads under plain node, and
// Object.create(TimelinePanel.prototype) drives the method the way tests/test_timeline_touch.py does (review
// find, 2026-09-08: the regex pins could not tell a released latch from a wiped one). The boot dispatch is
// exercised for real too.
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
    // the arm catches the read fault AND the write fault (the write step is a fault boundary too); anchoring on
    // the read-only literal fell back to a catch thousands of lines above and sliced in unrelated warn frames
    const block = KERNEL.slice(KERNEL.lastIndexOf("except (_StateUnreadable, _StateUnwritable) as e:", call), call);
    assert.ok(block.length < 2000, "the arm's own except sits just above its refusal: " + what);
    assert.doesNotMatch(block, /"type": "warn"/, "no store-fault arm answers with a warn frame: " + what);
  }
});

test("timeline (executed): only the refused sid+flag leaves the latch; both copies repaint to the frame's value; the gear rebuilds only when open for that sid", () => {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { TimelinePanel } = require(path.join(ROOT, "ui", "romp-timeline-view.js"));
  const mk = (over: Record<string, unknown> = {}) => {
    const v: any = Object.create(TimelinePanel.prototype);
    v._pendingFlags = { s1: { notify: true, hideFromFeed: true }, s2: { notify: true } };
    v.data = { sessions: [{ id: "s1", notify: true, hideFromFeed: true }, { id: "s2", notify: true }] };
    v._laneMenu = { _sid: "s1", _session: { id: "s1", notify: true } };
    v.builds = 0; v._laneMenuBuild = function () { this.builds++; };
    v.draws = 0; v.draw = function () { this.draws++; };
    Object.assign(v, over);
    return v;
  };
  const posted: any[] = [];
  (globalThis as any).window = { parent: { postMessage: (m: any) => posted.push(m) } };
  try {
    const v = mk();
    v.settingRefused({ type: "settingRefused", gesture: "flag", sid: "s1", flag: "notify", value: false, text: "couldn't save that setting" });
    assert.deepEqual(v._pendingFlags, { s1: { hideFromFeed: true }, s2: { notify: true } }, "only s1's notify latch is released");
    assert.equal(v.data.sessions[0].notify, false, "the frame's session repaints to the kernel's painted value");
    assert.equal(v._laneMenu._session.notify, false, "so does the copy the open gear built from");
    assert.equal(v.data.sessions[1].notify, true, "another session is untouched");
    assert.deepEqual(v._laneRefusal, { sid: "s1", flag: "notify", text: "couldn't save that setting" });
    assert.equal(v.builds, 1, "the gear is open for s1: rebuilt in place");
    assert.equal(v.draws, 1);
    assert.deepEqual(posted, [{ romp: "notify", kind: "refused", text: "couldn't save that setting", sid: "s1" }], "filed in the shell's bell under its own kind");
    // the gear open for ANOTHER lane is neither rebuilt nor repainted
    const w = mk({ _laneMenu: { _sid: "s2", _session: { id: "s2", notify: true } } });
    w.settingRefused({ type: "settingRefused", gesture: "flag", sid: "s1", flag: "notify", value: false, text: "x" });
    assert.equal(w.builds, 0);
    assert.equal(w._laneMenu._session.notify, true);
    assert.equal(w.data.sessions[0].notify, false, "the frame's session still repaints");
    // the last latch on a sid releases the whole entry; a frame without a boolean value repaints nothing
    const u = mk({ _pendingFlags: { s1: { hideFromFeed: true } } });
    u.settingRefused({ type: "settingRefused", gesture: "flag", sid: "s1", flag: "hideFromFeed", text: "x" });
    assert.deepEqual(u._pendingFlags, {});
    assert.equal(u.data.sessions[0].hideFromFeed, true);
    // a bell gesture (the feed's) touches no lane state and rebuilds no gear
    const b = mk();
    b.settingRefused({ type: "settingRefused", gesture: "bell", sid: "s1", itemId: "s1:g1", value: true, text: "x" });
    assert.deepEqual(b._pendingFlags, { s1: { notify: true, hideFromFeed: true }, s2: { notify: true } });
    assert.equal(b.builds, 0);
    assert.equal(b.draws, 1, "…but still repaints, and files the text");
  } finally { delete (globalThis as any).window; }
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
  // the tooltip covers BOTH things filed under the kind (review find, 2026-09-08): a change that did not
  // save (a read OR a write fault), and a state file that could not be read or was moved aside
  assert.match(KERNEL, /refused:"a setting that could not be saved, or a state file that could not be read\. A change you made \\u2014 a lane or tab setting, a card bell, a lane order \\u2014 was not saved because romp could not read or write the file that holds it/);
  assert.match(KERNEL, /refused:"[^"]*could not be read \(the last values are shown until it can\), or held bytes romp could not parse and was moved aside/);
  assert.match(KERNEL, /\.rerr-chip\.k-refused\{color:#ffd166;border-color:rgba\(255,209,102,0\.6\)\}/);
  // and every pane files under it -- none under `warn`
  for (const src of [FEED, RENDER, VIEW]) assert.doesNotMatch(src.slice(src.indexOf("settingRefused")), /kind: ['"]warn['"]/);
});

