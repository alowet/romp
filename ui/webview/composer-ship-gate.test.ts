// Sending while an attachment is still UPLOADING must never silently drop it (the user 2026-08-16:
// the composer said "uploading", allowed the send, and the message went without the image — the send
// reads only the acked composerFiles list, and pendingShips was never consulted). The gate: a send
// with ships in flight opens the same pane-local confirm the /clear guard uses — send WITHOUT the
// upload explicitly, or hold the send and let the LAST droppedPath ack fire it (event-based). A save
// nack cancels the hold loudly; any successful send supersedes it. The ack also attaches the file to
// the composer that SHIPPED it (retirePendingShip now returns the owning sid) instead of whatever tab
// is active at ack time — the same report's second face. Source pins.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const CSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "styles.css"), "utf8");

test("a send with ships in flight is gated by the confirm: send-without is explicit, wait is the default", () => {
  assert.match(RENDER, /const shipping = \(pendingShips\.get\(activeId\) \|\| \[\]\)\.length;/,
    "the send path finally consults the in-flight list");
  assert.match(RENDER, /if \(shipping && !opts\?\.pastShipGate\) \{/);
  assert.match(RENDER, /\{ label: "Wait for the upload", value: "wait" \}/);
  assert.match(RENDER, /\{ label: "Send without " \+ them, value: "now", danger: true \}/,
    "sending without the file is the marked-dangerous, explicit choice");
  // the answer is for the session the dialog opened over (2026-09-24): the dialog stays up across a session switch,
  // so a switched "Send without it" refuses out loud, on the warn toast, rather than send the open tab's draft; it
  // points at that tab's box only while the box holds what the answer would have sent there; and "Wait" repaints
  // the strip only under its own tab. The shape is pinned here; composer-ship-gate-exec.test.ts drives it.
  assert.match(RENDER, /if \(v === "now"\) \{\s*\n\s*if \(activeId === sid\) sendComposer\(\{ pastShipGate: true \}\);\s*\n\s*else \{/);
  assert.match(RENDER, /const kept = !!\(drafts\.get\(sid\) \|\| ""\)\.trim\(\) \|\| \(composerFiles\.get\(sid\) \|\| \[\]\)\.length > 0;/);
  assert.match(RENDER, /warnToast\(\(name \? "The message on “" \+ name \+ "”" : "The message"\) \+ " was not sent: the open "\s*\n\s*\+ "tab changed while the upload dialog was up\."\s*\n\s*\+ \(name && kept \? " It's still in that tab's message box\." : ""\)\);/);
  assert.match(RENDER, /else if \(v === "wait"\) \{ sendOnShip\.add\(sid\); if \(sid === activeId\) renderComposerFiles\(sid\); \}/);
});

test("the held send fires on the LAST ack — event-based — and a nack cancels it loudly", () => {
  assert.match(RENDER, /if \(owner && \(sendOnShip\.has\(owner\) \|\| gateOpen\) && !\(pendingShips\.get\(owner\) \|\| \[\]\)\.length\) \{/,
    "the deciding event is the last pending ship retiring — for a held send AND an open gate dialog");
  assert.match(RENDER, /if \(owner === activeId\) fireHeldSend\(\);/);
  assert.match(RENDER, /the held message was not sent; review it there/,
    "a mid-hold tab switch surfaces instead of sending a background composer");
  assert.match(RENDER, /const held = !!owner && sendOnShip\.delete\(owner\);/,
    "a failed save cancels the hold — it must not fire without the file it waited for");
  assert.match(RENDER, /\+ \(held \|\| gateWasOpen \? " Your message was NOT sent\." : ""\)/);
});

test("the OPEN gate dialog resolves itself on the last ack: closes and sends, no click needed", () => {
  // the user 2026-08-19: pressing Enter mid-upload popped the dialog, the upload finished, and the
  // dialog just sat there. The upload finishing IS the answer to the question the dialog asks.
  assert.match(RENDER, /let shipGateSid: string \| null = null;/);
  assert.match(RENDER, /shipGateSid = sid;\s*\/\/ the last-ship ack resolves the open dialog itself/);
  assert.match(RENDER, /const gateOpen = shipGateSid === owner;/);
  assert.match(RENDER, /if \(gateOpen\) \{ shipGateSid = null; closeConfirm\(null\); \}/,
    "the dialog dismisses itself the moment the last ship lands, then the send fires");
  assert.match(RENDER, /if \(shipGateSid === sid\) shipGateSid = null;\n\s*endReloadHoldIfIdle\(\);\n\s*if \(v === "now"\)/,
    "any button (or cancel) un-registers the gate — the ack path can never resolve a closed dialog — but only its own: "
    + "another session's upload dialog replacing it has registered itself by the time this one's cancel runs");
  // a FAILED save also moots the dialog — it closes, but never auto-sends without the file
  assert.match(RENDER, /const gateWasOpen = shipGateSid === owner;/);
  assert.match(RENDER, /if \(gateWasOpen\) \{ shipGateSid = null; closeConfirm\(null\); \}/);
});

test("a held send LOOKS staged: the files strip wears the staged head with a live count and a Cancel", () => {
  // the user 2026-08-22: after "Wait for the upload" the only cue was the dimmed send button, which
  // read as nothing happening. The head rides renderComposerFiles — the renderer that already runs
  // on the wait click, every ack, and every tab switch, so the line tracks exactly those events.
  assert.match(RENDER, /if \(id && sendOnShip\.has\(id\)\) \{\s*\n\s*const head = el\("div", "staged-head held-head"\);/);
  assert.match(RENDER, /"staged — sends when the upload finishes"/);
  assert.match(RENDER, /pending\.length > 1 \? " \(" \+ pending\.length \+ " still uploading\)" : ""/,
    "the live count rides each ack's re-render");
  assert.match(RENDER, /cancel\.addEventListener\("click", \(\) => \{ sendOnShip\.delete\(id\); renderComposerFiles\(id\); \}\);/,
    "Cancel un-holds — message and attachments stay, nothing sends");
  const CSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "styles.css"), "utf8");
  assert.match(CSS, /\.held-head \{ flex: 1 1 100%; \}/, "full-width: it owns the strip's top line");
});

test("any successful send supersedes a hold, so a spent hold can never double-send", () => {
  const hits = RENDER.match(/sendOnShip\.delete\(sid\);\s+\/\/ a send happened — any held one is superseded/g) || [];
  assert.equal(hits.length, 2, "both delivery paths (provisional queue and live route) clear it");
});

test("the ack attaches to the composer that SHIPPED the file, not whatever tab is active", () => {
  assert.match(RENDER, /function retirePendingShip\(key: string, shipId\?: string\): string \| null \{/);
  assert.match(RENDER, /const owner = retirePendingShip\(m\.path, ackShip\) \|\| activeId;/);
  assert.match(RENDER, /addComposerFile\(owner, m\.path\);/);
});

test("a held send is visible on the button and always inspectable", () => {
  assert.match(RENDER, /sendBtn\.classList\.toggle\("send-held", held\);/);
  // inspectable through the ONE styled tip: a native title beside the button's setTip showed two
  // stacked tooltip boxes while a hold was armed (2026-09-02)
  assert.match(RENDER, /setTip\(sendBtn, held \? "Send \(Enter\)\\nsends when the upload finishes" : "Send \(Enter\)"\);/);
  assert.match(CSS, /#composer-send\.send-held \{ opacity: 0\.45; \}/);
});
