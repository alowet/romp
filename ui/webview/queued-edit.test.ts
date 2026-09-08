// EDITING a queued message (the user 2026-09-08): a message that has not reached the session yet — held in
// the SDK backend's queue (idx), parked in romp's FIFO (park), or still at the optimistic "sending…" stage
// — is the user's to change until it goes. The ✎ beside the ✕ loads the text into the composer under an
// editing pill; send posts editQueued and the kernel replaces the entry IN PLACE (same slot, a follow-up's
// wrapper kept), answering editResult like the ✕'s cancelResult. No jsdom harness → source pins, the
// repo's convention (queued-indicator.test.ts is the ✕'s twin of this file).
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const ROOT = path.resolve(process.cwd(), "..");
const RENDER = fs.readFileSync(path.join(ROOT, "ui", "webview", "render.ts"), "utf8");
const CSS = fs.readFileSync(path.join(ROOT, "ui", "webview", "styles.css"), "utf8");
const KERNEL = fs.readFileSync(path.join(ROOT, "kernel", "kernel.py"), "utf8");
const SDKBE = fs.readFileSync(path.join(ROOT, "kernel", "sdk_backend.py"), "utf8");

test("an editable queued bubble carries a ✎ beside its ✕ — the same three stages, the same recall gate, user words only", () => {
  assert.match(RENDER, /if \(t\.cancelable && !t\.romp && !isCmd && \(t\.idx !== undefined \|\| t\.park !== undefined \|\| t\.optimistic\)\)/,
    "romp's notices and slash commands are not edited — a command is cancelled and typed again");
  assert.match(RENDER, /bubble\.classList\.add\("editable"\);/);
  assert.match(RENDER, /el\("button", "queued-edit"\)/);
  assert.match(RENDER, /ed\.dataset\.act = "qedit";/, "delegated through the stable document.body delegate, like the ✕");
  assert.match(RENDER, /if \(t\.idx !== undefined\) ed\.dataset\.qidx = String\(t\.idx\);/);
  assert.match(RENDER, /if \(t\.park !== undefined\) ed\.dataset\.qpark = String\(t\.park\);/);
  assert.match(RENDER, /if \(t\.optimistic\) ed\.dataset\.qopt = "1";/);
  assert.match(RENDER, /\(ed as any\)\._qmd = t\.md;/, "the body rides along: the kernel's drift guard and the composer read it");
  assert.doesNotMatch(RENDER, /bubble\.addEventListener\("click"/, "the bubble itself still carries no listener");
  assert.match(CSS, /\.queued-bubble\.editable \{ padding-right: 52px; \}/, "room for both corner controls");
  assert.match(CSS, /\.queued-edit \{\s*\n\s*position: absolute; top: 3px; right: 26px;/);
  assert.match(CSS, /\.queued-edit:hover \{ color: var\(--accent\)/, "accent, not red — it changes the message, it does not remove it");
});

test("the qedit delegate loads the composer under an editing pill (the rewind edit's grammar)", () => {
  assert.match(RENDER, /qedit: \(el\) => \{/);
  assert.match(RENDER, /if \(sidQ !== activeId\) \{ warnToast\("open that session's chat to edit its queued message"\); return; \}/,
    "the edit rides the ACTIVE composer — another session's bubble is declined, never edited in the wrong box");
  assert.match(RENDER, /beginQueuedEdit\(sidQ, ref\);/);
  assert.match(RENDER, /type QueuedEditRef = \{ md: string; idx\?: number; park\?: number; qts\?: number; optimistic\?: boolean \};/);
  assert.match(RENDER, /const queuedEdits = new Map<string, QueuedEditRef>\(\);/);
  assert.match(RENDER, /function beginQueuedEdit\(sid: string, ref: QueuedEditRef\): void \{\s*\n\s*if \(composerEdits\.has\(sid\)\) cancelComposerEdit\(sid\);/,
    "one edit at a time: a rewind edit yields to a queued edit…");
  assert.match(RENDER, /function beginComposerEdit\(sid: string, uuid: string, orig: string\): void \{\s*\n\s*if \(queuedEdits\.has\(sid\)\) cancelQueuedEdit\(sid\);/,
    "…and a queued edit yields to a rewind edit");
  assert.match(RENDER, /label\.textContent = "Editing queued message — send replaces it in the queue";/);
  assert.match(RENDER, /if \(activeId && queuedEdits\.has\(activeId\)\) \{ cancelQueuedEdit\(activeId\); return; \}/, "Escape cancels it first");
});

test("send in queued-edit mode posts editQueued with the old body and keeps the words if the kernel refuses", () => {
  assert.match(RENDER, /const qmsg: Record<string, unknown> = \{ type: "editQueued", id: activeId, md: qedit\.md, text: typed \};/);
  assert.match(RENDER, /if \(qedit\.idx !== undefined\) qmsg\.idx = qedit\.idx;/);
  assert.match(RENDER, /if \(qedit\.park !== undefined\) qmsg\.park = qedit\.park;/);
  assert.match(RENDER, /if \(!typed\) return;\s*\/\/ an empty edit is not a send — to drop the message, use its ✕/);
  assert.match(RENDER, /pendingEditRestores\.set\(activeId \+ " " \+ qedit\.md, \{ typed, ref: qedit \}\);/);
  assert.match(RENDER, /applyQueuedEditLocally\(activeId, qedit, typed\);/, "the bubble shows the new words at once (acknowledge the click)");
  assert.doesNotMatch(RENDER, /registerOptimistic\(activeId, typed\);\s*\n\s*queuedEdits/, "an edit is not a new send — no optimistic send entry");
  // the verdict frame: cancelResult's twin
  assert.match(RENDER, /m\.type === "editResult" && typeof m\.id === "string"/);
  assert.match(RENDER, /applyQueuedEditLocally\(m\.id, stash\.ref, stash\.typed, true\);/, "the optimistic repaint is reversed");
  assert.match(RENDER, /if \(m\.id === activeId\) restoreToComposer\(stash\.typed\);/, "the typed words come back — never lost, never sent twice");
  assert.match(RENDER, /pendingEditRestores\.delete\(key\);/);
});

test("the optimistic repaint touches the client's copy of the queue AND our own pending-send entry", () => {
  assert.match(RENDER, /function applyQueuedEditLocally\(sid: string, ref: QueuedEditRef, text: string, back = false\): void/);
  assert.match(RENDER, /if \(p\.text === from && \(ref\.qts === undefined \|\| p\.ts === ref\.qts\)\) \{ p\.text = to; p\.body = pendingBody\(to, p\.imgPaths\); \}/,
    "our pending entry follows the edit, or the pending reconcile would paint the old words back");
  assert.match(RENDER, /if \(e\.kind !== "queued"\) continue;[\s\S]*?t\.md = to;/);
});

test("the kernel replaces the entry in place at every stage and answers with an authoritative editResult", () => {
  assert.match(KERNEL, /def _edit_parked\(sid, park, md, text\):/);
  assert.match(KERNEL, /def _edit_backend_queued\(be, sid, idx, md, text\):/);
  assert.match(KERNEL, /def _replace_followup_body\(text, body\):/, "a follow-up keeps its goal quote and markers");
  assert.match(KERNEL, /ops\[park\] = \("send", _replace_followup_body\(op\[1\], body\)\) \+ tuple\(op\[2:\]\)/, "same slot, same echo author");
  assert.match(KERNEL, /if park == 0 and inflight_head:\s*\n\s*return _edit_miss_text\(md\)/, "the head the backend holds is too late, like the ✕");
  assert.equal(KERNEL.split('"type": "editResult"').length - 1, 3, "one reply per arm: park + idx + the optimistic md-only arm");
  assert.match(KERNEL, /def _edit_miss_text\(md\):/);
  assert.match(KERNEL, /too late to edit — the message already reached the session as it was/);
  assert.match(KERNEL, /"cancelQueued", "dismissEcho", "apiRetry", "editQueued"/, "routes to the owning kernel across linked machines");
  assert.match(SDKBE, /def replace_queued\(self, idx: int, text: str, expect: str \| None = None\) -> str \| None:/,
    "the swap re-verifies the exact old text under the session lock — never a wrong-message rewrite");
  assert.match(SDKBE, /def edit_queued\(self, sid: str, idx: int, text: str, expect: str \| None = None\) -> str \| None:/);
  assert.match(SDKBE, /a\["_echo_text"\] = text/, "the optimistic echo is re-worded, so the live tail shows the edited message");
});
