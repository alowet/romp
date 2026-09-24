// The upload dialog ("An attachment is still uploading": Wait for the upload / Send without it) answers for the
// session it opened over, EXECUTED. The dialog is pane-local and stays up across a switch that never passes its
// backdrop (a session's hot key, the switcher, a feed card's jump), and its "Send without it" re-entered
// sendComposer, which reads whatever box is active, so after a switch it sent the OTHER session's draft (the
// post-merge review of 2026-09-24). composer-ship-gate.test.ts pins the gate's shape at the source; this file
// drives it: sendComposer, showConfirm and closeConfirm are lifted out of render.ts, transpiled at run time and run
// over a minimal fake DOM (the reload-notices.test.ts idiom), and the dialog is answered by clicking its buttons by
// label, the way a person does. The session switch is a stand-in for setActive's draft swap (the leaving box is
// stashed in drafts, the entering one is restored, the strip repaints for the entering tab), since setActive itself
// is far too wide to lift; a session's end is dismissSession's teardown in the same way. Synthetic sessions only
// (web, api).
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { createRequire } from "node:module";

const requireCjs = createRequire(__filename);
const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");

function liftBetween(startAnchor: string, endAnchor: string): string {
  const a = RENDER.indexOf(startAnchor), b = RENDER.indexOf(endAnchor, a);
  assert.ok(a > 0 && b > a, `anchors not found: ${startAnchor.slice(0, 40)} or ${endAnchor.slice(0, 40)} moved; re-anchor`);
  return requireCjs("esbuild").transformSync(RENDER.slice(a, b), { loader: "ts" }).code;
}

/** Enough of Element for the confirm dialog: an id, a class, text, children, click listeners fired by hand, focus. */
class FakeEl {
  children: FakeEl[] = []; parent: FakeEl | null = null; listeners: Record<string, Function[]> = {};
  textContent = ""; id = "";
  constructor(public tag: string, public className = "") {}
  has(c: string): boolean { return this.className.split(/\s+/).includes(c); }
  appendChild(c: FakeEl): FakeEl { c.parent = this; this.children.push(c); return c; }
  remove(): void { if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this); this.parent = null; }
  get firstElementChild(): FakeEl | null { return this.children[0] ?? null; }
  addEventListener(t: string, f: Function): void { (this.listeners[t] ??= []).push(f); }
  fire(t: string): void { for (const f of this.listeners[t] ?? []) f({ target: this }); }
  focus(): void { /* the dialog focuses its first button; nothing here reads it */ }
  walk(): FakeEl[] { return this.children.flatMap((c) => [c, ...c.walk()]); }
}

/** The page the lifted closures read: two sessions, web (open, its box typed, one upload in flight) and api (a draft of
 *  its own), with every send, toast and strip repaint recorded. `typed` is what web's box holds. */
function world(typed: string) {
  const body = new FakeEl("body");
  const keys: Function[] = [];
  return {
    FakeEl,
    document: {
      body,
      getElementById: (id: string) => body.walk().find((e) => e.id === id) ?? null,
      addEventListener: (t: string, f: Function) => { if (t === "keydown") keys.push(f); },
      removeEventListener: (t: string, f: Function) => { const i = keys.indexOf(f); if (t === "keydown" && i >= 0) keys.splice(i, 1); },
    },
    keys,
    activeId: "web",
    ta: { value: typed },
    drafts: new Map<string, string>([["api", "the api draft stays put"]]),
    sessions: new Map<string, { name: string }>([["web", { name: "web" }], ["api", { name: "api" }]]),
    tabMeta: new Map<string, { name: string }>(),
    pendingShips: new Map<string, unknown[]>([["web", [{ key: "shot.png", shipId: "s1" }]]]),
    composerFiles: new Map<string, string[]>(),
    sendOnShip: new Set<string>(),
    sent: [] as { sid: string; text: string }[],     // every flushStaged: the one door every normal send leaves by
    toasts: [] as string[],                           // warnToast: stays until it fades or is dismissed, and a reload replays it
    ephemeral: [] as string[],                        // ephemeralWarnToast: reports a state, so a reload does not replay it
    stripPaints: [] as (string | null)[],             // every renderComposerFiles, in order: the last one is what the strip shows
  };
}
type World = ReturnType<typeof world>;
type Api = { sendComposer: () => void; switchTo: (id: string) => void; end: (id: string, landOn: string) => void;
             gateSid: () => string | null; activeId: () => string };

function page(typed = "ship the release notes") {
  const W = world(typed);
  const prelude = `
    const W = WORLD;
    const document = W.document;
    const el = (tag, cls) => new W.FakeEl(tag, cls);
    let activeId = W.activeId;
    const ta = W.ta;
    let shipGateSid = null;
    const pendingShips = W.pendingShips, composerFiles = W.composerFiles, sendOnShip = W.sendOnShip;
    const drafts = W.drafts, draftStartedAt = new Map(), sessions = W.sessions, tabMeta = W.tabMeta;
    const composerCitations = new Map(), composerEdits = new Map(), histWalk = new Map(), lastSent = new Map();
    const stagedMsgs = { count: () => 0 };
    const hostIsDown = () => false, isProvisionalId = () => false, provisionalId = null, provisionalQueue = [];
    const composerAnswersAsk = () => null;
    const addCustomLiveAsk = () => { throw new Error("no picker in this world"); }, sendTextLiveAsk = addCustomLiveAsk;
    const persistDrafts = () => {};
    const clearBox = () => { ta.value = ""; };
    const renderComposerFiles = (id) => { W.stripPaints.push(id); };
    const renderComposerChips = () => {};
    const flushStaged = (sid, typed) => { W.sent.push({ sid, text: typed.text }); return 1; };
    const endReloadHoldIfIdle = () => {};
    const warnToast = (msg) => { W.toasts.push(msg); return el("div", "warn-toast"); };
    const ephemeralWarnToast = (msg) => { W.ephemeral.push(msg); };
    const liveSession = () => undefined;
    const registerOptimistic = () => {}, previewKind = () => null;
    const isClearCmd = () => false, isNewCmd = () => false;
    const clearConfirmDetail = () => null, openTopTitles = () => [], ledgers = new Map();
    const openMcpPanel = () => {}, setComposerAskMode = () => {};
    const vscodeApi = { postMessage: () => { throw new Error("a normal send leaves by flushStaged in this world"); } };
    const pendingRewind = new Map(), reconcileRewind = () => {}, appendActive = () => {};
  `;
  const confirm = liftBetween("let confirmCb: ((v: string | null) => void) | null = null;", "// ---- move session (the user 2026-09-01) ----");
  const close = liftBetween("function closeConfirm(value: string | null) {", "// Inline validation message under the search box");
  const send = liftBetween("const sendComposer = (opts?: { pastShipGate?: boolean }) => {", "// an explicit send button on the right of the box");
  const tail = `
    // setActive's draft swap, as it runs on a real switch: the leaving box into drafts, the entering one out, the
    // strip repainted for the entering tab. The dialog is left exactly as it was, as a real switch leaves it.
    const switchTo = (id) => {
      if (ta.value) drafts.set(activeId, ta.value); else drafts.delete(activeId);
      activeId = id;
      ta.value = drafts.get(id) ?? "";
      renderComposerFiles(id);
    };
    // dismissSession(id, "end"), as the kernel's closed frame runs it: an open box is stashed first, then the session,
    // its draft and its attached files go (the kernel's tab list, tabMeta, still names it until the next tab push),
    // and the page lands on another tab. The dialog is left up, as a real end leaves it.
    const end = (id, landOn) => {
      const was = activeId === id;
      if (was) { if (ta.value) drafts.set(id, ta.value); else drafts.delete(id); }
      sessions.delete(id); drafts.delete(id); composerFiles.delete(id);
      if (was) { activeId = landOn; ta.value = drafts.get(landOn) ?? ""; renderComposerFiles(landOn); }
    };
    return { sendComposer: () => sendComposer(), switchTo, end, gateSid: () => shipGateSid, activeId: () => activeId };
  `;
  const api = (new Function("WORLD", prelude + confirm + close + send + tail) as (w: World) => Api)(W);
  const dialog = () => W.document.getElementById("confirm");
  const click = (label: string) => {
    const btn = (dialog()?.walk() || []).find((e) => e.has("confirm-btn") && e.textContent === label);
    assert.ok(btn, `the open dialog has a "${label}" button`);
    btn.fire("click");
  };
  return { W, ...api, dialog, click };
}

/** Enter on web's box with its upload in flight: the dialog opens over web and nothing is sent yet. */
function openGate(p: ReturnType<typeof page>): void {
  p.sendComposer();
  const d = p.dialog();
  assert.ok(d, "the upload dialog is open");
  assert.equal(d.walk().find((e) => e.has("confirm-title"))?.textContent, "An attachment is still uploading");
  assert.equal(p.gateSid(), "web", "the dialog opened for web");
  assert.deepEqual(p.W.sent, [], "nothing sends while the dialog is up");
}

test("Send without it, answered on the dialog's own session, sends that session's message", () => {
  const p = page();
  openGate(p);
  p.click("Send without it");
  assert.deepEqual(p.W.sent, [{ sid: "web", text: "ship the release notes" }]);
  assert.equal(p.dialog(), null, "the dialog closed");
  assert.equal(p.gateSid(), null);
  assert.deepEqual(p.W.toasts, []);
  assert.equal(p.W.ta.value, "", "the box cleared on the send");
});

test("Send without it after a session switch sends nothing, leaves both drafts alone and says where the message is", () => {
  const p = page();
  openGate(p);
  p.switchTo("api");
  assert.ok(p.dialog(), "a switch leaves the dialog up (nothing closes it)");
  assert.equal(p.W.ta.value, "the api draft stays put", "the box now holds api's draft");
  p.click("Send without it");
  assert.deepEqual(p.W.sent, [], "neither session's draft was sent: web's is not in the box, and api's was never asked to go");
  assert.equal(p.activeId(), "api", "the answer does not move the person back");
  assert.equal(p.W.ta.value, "the api draft stays put", "api's draft is untouched");
  assert.equal(p.W.drafts.get("web"), "ship the release notes", "web's message is still in its tab's box");
  assert.equal(p.dialog(), null, "the dialog closed");
  assert.equal(p.gateSid(), null, "the gate un-registered, so the last ack cannot resolve a closed dialog");
  assert.deepEqual([...p.W.sendOnShip], [], "no hold is armed: back on web before its upload lands, nothing sends by itself");
  assert.equal(p.W.toasts.length, 1, "the refused answer is said out loud, never a silent nothing");
  assert.deepEqual(p.W.ephemeral, [], "on the warn toast, not the ephemeral one: it reports what happened to a send");
  assert.equal(p.W.toasts[0], "The message on “web” was not sent: the open tab changed while the upload dialog was up. "
    + "It's still in that tab's message box.", "it names the session whose message did not go, and where the message is now");
});

test("a session the page no longer knows by name: the refusal still speaks, without naming a box it cannot vouch for", () => {
  const p = page();
  openGate(p);
  p.switchTo("api");
  p.W.sessions.delete("web");
  p.click("Send without it");
  assert.deepEqual(p.W.sent, []);
  assert.deepEqual(p.W.toasts, ["The message was not sent: the open tab changed while the upload dialog was up."]);
});

test("the dialog's session ended under it: named from the kernel's tab list, and no box claimed, since its draft went with it", () => {
  const p = page();
  openGate(p);
  p.W.tabMeta.set("web", { name: "web" });   // the tab list still names web until the next tab push
  p.end("web", "api");
  assert.ok(p.dialog(), "the end leaves the dialog up");
  assert.equal(p.W.drafts.has("web"), false, "web's draft went with the session");
  p.click("Send without it");
  assert.deepEqual(p.W.sent, [], "api's draft, now in the box, was never asked to go");
  assert.deepEqual(p.W.toasts, ["The message on “web” was not sent: the open tab changed while the upload dialog was up."]);
});

test("a box holding only the upload: the refusal claims no message is left in that box, since nothing would have gone", () => {
  for (const typed of ["", "  \n "]) {
    const p = page(typed);
    openGate(p);
    p.switchTo("api");
    p.click("Send without it");
    assert.deepEqual(p.W.sent, [], JSON.stringify(typed));
    assert.deepEqual(p.W.toasts, ["The message on “web” was not sent: the open tab changed while the upload dialog was up."],
      "box " + JSON.stringify(typed) + ": on web's own tab this answer sends nothing either, so there is no message to point at");
  }
});

test("a box whose only content is a file that finished uploading: the refusal says it is still there, since that file would have gone", () => {
  const p = page("");
  p.W.composerFiles.set("web", ["docs/diagram.png"]);   // one file attached, a second still uploading
  openGate(p);
  p.switchTo("api");
  p.click("Send without it");
  assert.deepEqual(p.W.sent, []);
  assert.deepEqual(p.W.composerFiles.get("web"), ["docs/diagram.png"], "the attached file stays with web");
  assert.deepEqual(p.W.toasts, ["The message on “web” was not sent: the open tab changed while the upload dialog was up. "
    + "It's still in that tab's message box."]);
});

test("away and back before answering: the dialog's session is open again, so Send without it sends its message", () => {
  const p = page();
  openGate(p);
  p.switchTo("api");
  p.switchTo("web");
  p.click("Send without it");
  assert.deepEqual(p.W.sent, [{ sid: "web", text: "ship the release notes" }], "web's own draft, restored by the switch back");
  assert.equal(p.W.drafts.get("api"), "the api draft stays put");
  assert.deepEqual(p.W.toasts, []);
});

test("another session's upload dialog replacing this one stays registered: the registration its own last upload closes it by", () => {
  const p = page();
  openGate(p);
  p.switchTo("api");
  p.W.pendingShips.set("api", [{ key: "notes.pdf", shipId: "s2" }]);   // api has an upload of its own in flight
  p.sendComposer();   // Enter in api's box: api's dialog opens, and opening it cancels web's
  assert.equal(p.dialog()?.walk().find((e) => e.has("confirm-title"))?.textContent, "An attachment is still uploading");
  assert.equal(p.gateSid(), "api", "web's cancelled answer un-registered only its own gate, not api's");
  assert.deepEqual(p.W.sent, []);
  assert.deepEqual(p.W.toasts, [], "a cancel says nothing");
  assert.deepEqual([...p.W.sendOnShip], [], "and holds nothing");
  p.click("Send without it");
  assert.deepEqual(p.W.sent, [{ sid: "api", text: "the api draft stays put" }], "api's dialog answers for api, its own tab");
  assert.equal(p.gateSid(), null);
  assert.equal(p.W.drafts.get("web"), "ship the release notes", "web's message is still in its tab's box");
});

test("Wait for the upload after a switch holds the dialog's session and leaves the open tab's strip alone", () => {
  const p = page();
  openGate(p);
  p.switchTo("api");
  p.click("Wait for the upload");
  assert.deepEqual([...p.W.sendOnShip], ["web"], "the hold is web's: its last ack releases it (or says so, from another tab)");
  assert.deepEqual(p.W.sent, []);
  assert.equal(p.W.stripPaints[p.W.stripPaints.length - 1], "api",
    "the strip under api's box still shows api's files, not web's held strip");
  assert.deepEqual(p.W.toasts, []);
});

test("Wait for the upload on the dialog's own session holds it and repaints its strip as staged", () => {
  const p = page();
  openGate(p);
  p.click("Wait for the upload");
  assert.deepEqual([...p.W.sendOnShip], ["web"]);
  assert.deepEqual(p.W.stripPaints, ["web"], "the strip repaints once, for web, to show the held head");
  assert.deepEqual(p.W.sent, []);
});
