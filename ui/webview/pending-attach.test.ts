// While a picked/dropped/pasted file's bytes ship to the kernel (shipFileToHost →
// dropFile → droppedPath), the attachment strip shows a PENDING chip — name +
// pulsing dots — from the instant the file is chosen. On a phone that round trip
// is seconds long (base64 + a fragmented WS send + the kernel write), and with
// nothing on screen it read as a dead click (the user 2026-08-11: "seemed like it
// didn't work for a second and then the thumbnail appeared").
//
// Lifecycle is EVENT-based end to end: the chip goes up on pick, and comes down
// only on the ack (droppedPath), the kernel's loud nack (dropSaveFailed), a
// FileReader error, or the user's own ✕ — never a timer.
//
// The chat renderer has no jsdom harness, so — like the other webview tests —
// pin the wiring at the source level.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const CSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "styles.css"), "utf8");
const KERNEL = fs.readFileSync(path.resolve(process.cwd(), "..", "kernel", "kernel.py"), "utf8");

test("the pending chip goes up BEFORE the encode starts — pick-to-feedback is immediate", () => {
  // registry keyed by session, like composerFiles beside it
  assert.match(RENDER, /const pendingShips = new Map<string, PendingShip\[\]>\(\);/);   // entries retain shipId + payload (T215)
  // registered at the TOP of shipFileToHost (before new FileReader), with the sid captured once —
  // at call time via the sidAt default (a pasted-path caller passes the sid it verified against)
  assert.match(RENDER, /const name = f\.name \|\| "pasted\.png";\s*\n\s*const sid = sidAt;.*\n\s*const shipId = "s".*\n\s*addPendingShip\(sid, name, shipId\);.*\n\s*const reader = new FileReader\(\);/);
});

test("the strip renders pending chips (name + pulsing dots) and shows even with no real attachments", () => {
  // the strip's empty-check counts pending ships too
  assert.match(RENDER, /if \(!paths\.length && !pending\.length\) \{ strip\.style\.display = "none"; return; \}/);
  // each pending entry renders as a composer-file-pending chip with the ship-dots
  assert.match(RENDER, /composer-file composer-file-pending/);
  assert.match(RENDER, /composer-ship-dots/);
  // the ✕ removes just the CHIP — the escape hatch for an ack lost to a mid-ship disconnect
  assert.match(RENDER, /aria-label", "Dismiss pending attachment"/);
});

test("the droppedPath ack retires the chip it answers, then attaches the thumbnail", () => {
  assert.match(RENDER, /const owner = retirePendingShip\(m\.path, ackShip\) \|\| activeId;/);
  assert.match(RENDER, /retirePendingShip\(m\.path, ackShip\)[\s\S]{0,300}addComposerFile\(owner, m\.path\)/,
    "the ack attaches to the composer that SHIPPED the file (the 2026-08-16 wrong-tab attach)");
});

test("ack↔chip matching mirrors the kernel's saved-name sanitizer, FIFO as the fallback", () => {
  // drops/<ms>-<safe name>: the JS sanitizer mirrors _save_dropped_file's regex …
  assert.match(RENDER, /name\.replace\(\/\[\^\\w.-\]\+\/g, "_"\)\.slice\(-80\)/);
  assert.match(KERNEL, /re\.sub\(r"\[\^\\w.-\]\+", "_", name\)\[-80:\]/);
  // … and an unmatched ack still retires the OLDEST entry (the kernel answers in order)
  assert.match(RENDER, /list\.splice\(i >= 0 \? i : 0, 1\);/);
});

test("a failed kernel save is NACKED and surfaces loudly — never a silent stuck chip", () => {
  // kernel: the no-path branch replies dropSaveFailed instead of nothing
  assert.match(KERNEL, /ack = \{"type": "dropSaveFailed", "name": str\(msg\["name"\]\)\}/);   // built then shipId-stamped (T215)
  // client: the nack retires the chip and says so in a toast
  assert.match(RENDER, /m\.type === "dropSaveFailed" && typeof m\.name === "string"/);
  assert.match(RENDER, /retirePendingShip\(m\.name, nackShip\) \|\| activeId;[\s\S]{0,400}warnToast\(m\.name \+ " couldn't be saved on the kernel/);   // the nack also ends the reload hold (T272)
  // a FileReader failure retires it too — an unreadable file must not pulse forever
  assert.match(RENDER, /reader\.onerror = \(\) => retirePendingShip\(name, shipId\);/);
});

test("chips are never revived from a reload — names persist only to say what was LOST (T215)", () => {
  // The chips themselves stay in-memory: a reload kills the payload, so a revived chip would pulse
  // over a file nothing can ever retire. What DOES persist is the ship NAMES (persistDrafts's
  // shipsInFlight), read once at startup to warn that those uploads died with the page — the VS Code
  // pipe reloads its webview on kernel reconnect, which was the silent-vanish face of the T215 wedge.
  assert.match(RENDER, /shipsInFlight: \[\.\.\.pendingShips\.values\(\)\]\.flat\(\)\.map\(\(p\) => p\.name\)/);
  assert.doesNotMatch(RENDER, /pendingShips\.set\([^)]*shipsInFlight/, "never rebuild chips from the persisted names");
  assert.match(RENDER, /still uploading when this page reloaded, so it was NOT attached — attach it again\./);
  // the clear is a DIRECT setState with no dependency on later declarations: v1 rode persistDrafts,
  // whose stagedMsgs read sits below this block — the TDZ throw died in its own catch and the clear
  // never ran, so the toast re-fired on every reload (review finding 2026-09-01)
  assert.match(RENDER, /vscodeApi\?\.setState\?\.\(\{ \.\.\.\(vscodeApi\.getState\?\.\(\) \|\| \{\}\), shipsInFlight: \[\] \}\);/,
    "the loss toast fires once — the record clears directly, immune to module-eval order");
  // …reached from the toast WITHOUT crossing a persistDrafts call: the clear must never ride it
  // (stagedMsgs is not initialized yet at module-eval; its TDZ throw dies in persistDrafts' catch)
  assert.match(RENDER, /attach (?:it|them) again\."\)\);(?:(?!persistDrafts\(\);)[\s\S]){0,600}?setState\?\.\(\{ \.\.\.\(vscodeApi\.getState\?\.\(\) \|\| \{\}\), shipsInFlight: \[\] \}\)/,
    "the startup clear must be the direct setState, not a persistDrafts ride");
});

test("a kernel restart between ship and ack RE-SHIPS the retained bytes on reconnect (T215)", () => {
  // The ack rides the socket the dropFile went out on, so a restart in that window means it can
  // never arrive: the chip pulsed forever and a held send never fired. The payload is retained on
  // the entry and re-shipped on romp:wsup — the exact kernel-is-back event, never a timer.
  assert.match(RENDER, /interface PendingShip \{ name: string; shipId: string; b64\?: string \}/);
  assert.match(RENDER, /if \(entry\) entry\.b64 = b64;/);
  assert.match(RENDER, /function reshipPendingUploads\(hosts\?: readonly string\[\]\): void \{/);
  assert.match(RENDER, /window\.addEventListener\("romp:wsup", \(\) => \{\n  reshipPendingUploads\(\);/);   // the listener grew a body (T246: the local active-tab re-arm rides it too)
  // an entry still ENCODING has no payload — its own onload ships on the fresh socket, never doubled
  assert.match(RENDER, /if \(!p\.b64\) continue;/);
  // the re-ship rides the same dropFile shape, same shipId, routed to the owning session
  assert.match(RENDER, /\{ type: "dropFile", name: p\.name, b64: p\.b64, shipId: p\.shipId \}/);
});

test("duplicate acks from a re-ship race are DROPPED, never attached to the active tab (T215)", () => {
  // kernel: the ack/nack echoes the client's shipId when one was sent
  assert.match(KERNEL, /ack\["shipId"\] = str\(msg\["shipId"\]\)/);
  assert.match(KERNEL, /_reply\(client, ack\)/);
  // client: an id-carrying ack that matches NO pending entry answers a chip already retired
  assert.match(RENDER, /function shipOwner\(shipId: string\): string \| null \{/);
  assert.match(RENDER, /if \(ackShip && !shipOwner\(ackShip\)\) return;/);
  assert.match(RENDER, /if \(nackShip && !shipOwner\(nackShip\)\) return;/);
  // and an id-carrying ack retires ONLY its own entry — never a FIFO guess across sessions
  assert.match(RENDER, /if \(shipId && i < 0\) continue;/);
});

test("the chip wears the accent loader-dots motif from styles.css", () => {
  assert.match(CSS, /\.composer-file-pending \{[^}]*dashed/);
  assert.match(CSS, /\.composer-ship-dots i \{[^}]*var\(--accent\)/);
  assert.match(CSS, /@keyframes ship-bnc/);
  // staggered like the romp loader's dots
  assert.match(CSS, /\.composer-ship-dots i:nth-child\(3\) \{ animation-delay: 0\.32s; \}/);
});

test("federated sessions heal too: every ack socket's comeback re-ships ITS entries (T215 review)", () => {
  const FED = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "federation.ts"), "utf8");
  // a remote session's ack rides that host's relay, so the re-ship is SCOPED to the socket that
  // reconnected: no scope = the local kernel's own entries; a hosts list = exactly those relays'
  assert.match(RENDER, /if \(hosts \? hosts\.indexOf\(h\) < 0 : h\) continue;/);
  // the relay's own redial is the one event a remote kernel restart fires — federation dispatches
  // it, the chat re-ships on it (v1 listened to romp:wsup alone and never healed federated wedges)
  assert.match(FED, /window\.dispatchEvent\(new CustomEvent\("romp:hostRelayUp", \{ detail: \{ host: conn\.host \} \}\)\);/);
  assert.match(RENDER, /window\.addEventListener\("romp:hostRelayUp", \(e\) => \{/);
  // …and NOT the kernel-reported hostUp: federation dispatches it in the tick it re-dials the relay,
  // so the socket is still CONNECTING and a re-ship there raised a false "unreachable" toast an RTT
  // before the relay's own onopen re-shipped correctly (review finding 2026-09-01, reverted here)
  assert.doesNotMatch(RENDER, /m\.hosts\.map\(String\)/, "hostUp must not re-ship — romp:hostRelayUp is the event");
  assert.match(RENDER, /if \(m\.type === "hostUp"\) \{ refreshSettledPreviews\(\); healPathImgs\(\); \}/);
});

test("dismissing the LAST pending chip settles an armed hold loudly — never a forever-wait (T215 review)", () => {
  // the ✕ removed the very entry whose ack the hold was waiting for; same contract as the nack:
  // cancelled loudly, never auto-sent
  assert.match(RENDER, /const held = sendOnShip\.delete\(id\);\s*\n\s*const gateWasOpen = shipGateSid === id;\s*\n\s*if \(gateWasOpen\) \{ shipGateSid = null; closeConfirm\(null\); \}\s*\n\s*if \(held \|\| gateWasOpen\) warnToast\("The pending upload was dismissed — your held message was NOT sent\."\);/);
});
