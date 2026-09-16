// The FOLDER QUESTION is still the create in flight (round three of the held-column deferral, 2026-09-15). The create flow's
// real functions are lifted from render.ts (the chat-split-exec.test.ts pattern) over a world that plays the shell (a parent
// window counting colBusy posts), the kernel (createSession / cancelCreate sent), the dialog (showConfirm captured, answered
// by the test) and the picker (an element with a display), and driven the way the page is: a create from the picker, text
// typed into the provisional tab's box, the kernel's createDirMissing, then each of the user's answers. What is pinned:
//   * the question keeps the column BUSY — no colBusy:false is posted when the provisional drops for the prompt, so a column
//     another dashboard dropped stays held under it (before this the flip fired there and the carry died with the document);
//   * "Edit the path" keeps the question (and the carry) alive in the picker; the picker closing with NO create abandons it —
//     the text lands in a draft the shell's close() hands home, persisted BEFORE the flip, which is the last act;
//   * "Create it and start" is the retry: the carry is restored into the new provisional's box, busy stays, and that
//     create's settlement is what flips; startCreate's own picker close does not abandon the question it retries;
//   * the prompt dismissed abandons the same way; with nothing typed the abandonment still ends the question.
// The world models a HELD column: once the provisional goes, no tab is held here (focusAfterDismiss), so the box is unbound
// and the abandoned text falls to the tab the column showed last (mru). Synthetic ids only.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { createRequire } from "node:module";
import { provisionalName, mintProvisionalId } from "./provisional";

const requireCjs = createRequire(__filename);
const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const fn = (name: string): string => {
  const i = RENDER.indexOf(`function ${name}(`);
  assert.ok(i >= 0, `${name} not found`);
  return RENDER.slice(i, RENDER.indexOf("\n}\n", i) + 3);
};
const lineOpt = (name: string): string => {   // a ONE-LINE function, to the end of its line; "" when absent on an older render.ts (the tests then fail on behaviour, not on a missing lift)
  const i = RENDER.indexOf(`function ${name}(`);
  return i >= 0 ? RENDER.slice(i, RENDER.indexOf("\n", i) + 1) : "";
};
const fnOpt = (name: string): string => (RENDER.indexOf(`function ${name}(`) >= 0 ? fn(name) : "");

const A = "11111111-2222-3333-4444-555555555501", B = "11111111-2222-3333-4444-555555555502", C = "11111111-2222-3333-4444-555555555503";
const REQ = { name: "notes", backend: "sdk", dir: "/proj/not-there-yet", host: "" };
const TYPED = "notes for a session whose folder is not there yet";

type Hooks = { posts: Record<string, unknown>[]; sent: Record<string, unknown>[]; seq: string[]; confirms: string[]; pickers: number; persisted: number; loaded: (string | null)[]; activated: string[]; timers: (() => void)[] };
type Api = {
  startCreate: (req: typeof REQ, mkdir?: boolean) => void; onCreateDirMissing: (m: Record<string, unknown>) => void; closePicker: (abandon?: boolean) => void;
  cancelProvisional: () => void; busy: () => boolean; answer: (v: string | null) => void; confirm: () => { title: string; buttons: string[] } | null;
  type: (t: string) => void; composer: () => string; picker: () => { open: boolean; search: string; dir: string };
  state: () => { provisionalId: string | null; pendingCarry: string; dirQuestion: boolean | undefined; activeId: string | null; drafts: Record<string, string> };
};

function world(o: { activeId: string | null; mru: string[]; order: string[]; nextActive: string | null }): { api: Api; HOOKS: Hooks } {
  const HOOKS: Hooks = { posts: [], sent: [], seq: [], confirms: [], pickers: 0, persisted: 0, loaded: [], activated: [], timers: [] };
  const win = { parent: { postMessage(m: Record<string, unknown>) { HOOKS.posts.push(m); if (m.romp === "colBusy") HOOKS.seq.push("flip:" + m.busy); } } };
  const js = requireCjs("esbuild").transformSync(
    [lineOpt("columnBusy"), fn("syncColumnBusy"), fn("dropProvisional"), fn("openProvisional"), fn("cancelProvisional"), fn("onCreateDirMissing"),
     fnOpt("abandonDirQuestion"), fn("stashActiveDraft"), fn("closePicker"), fn("startCreate")].join("\n"), { loader: "ts" }).code;
  const prelude = `
    const { provisionalName, mintProvisionalId, HOOKS } = W;
    let provisionalId = null, provisionalTags = [], pendingNewSession = null, provisionalTimer = undefined, pendingCarry = "", dirQuestion = false;
    let columnBusyTold = false, lastCreate = null, pickMode = false, activeId = W.activeId;
    const provisionalQueue = []; const failedProvisionals = new Set(); const drafts = new Map(); const pendingSent = new Map(); const sessions = new Map();
    const order = W.order.slice(); const mru = W.mru.slice();
    const PROVISIONAL_WAIT_MS = 90000;
    const EL = { "composer-input": { value: "", focus() {} }, picker: { style: { display: "none" } }, "picker-search": { value: "" }, "picker-dir": { value: "", focus() {}, select() {} } };
    const document = { getElementById: (id) => EL[id] || null };
    const vscodeApi = { postMessage: (m) => { HOOKS.sent.push(m); } };
    const renderTabs = () => {}; const growComposer = () => {};
    const setActive = (id) => { activeId = id; HOOKS.activated.push(id); };
    // the HELD column: once the provisional goes no tab is held here, so nothing to fall back on (focusAfterDismiss) — the box unbound
    const dismissSession = (id) => { sessions.delete(id); const i = order.indexOf(id); if (i >= 0) order.splice(i, 1); const j = mru.indexOf(id); if (j >= 0) mru.splice(j, 1); if (activeId === id) activeId = W.nextActive; };
    const persistDrafts = () => { HOOKS.persisted++; HOOKS.seq.push("persist"); }; const loadComposerFor = (sid) => { HOOKS.loaded.push(sid); };
    let confirm = null; const showConfirm = (title, detail, buttons, cb) => { confirm = { title, buttons: buttons.map((b) => b.value), cb }; HOOKS.confirms.push(title); };
    const createDirPrompt = () => "the folder question"; const openPicker = () => { EL.picker.style.display = "block"; HOOKS.pickers++; }; const askDirComplete = () => {};
    const rememberDir = () => {}; const signalPickerOverlay = () => {}; const syncComposerPh = () => {};
    const setTimeout = (f) => { HOOKS.timers.push(f); return HOOKS.timers.length; }; const clearTimeout = () => {}; const failProvisional = () => {};
  `;
  const epilogue = `
    return {
      startCreate, onCreateDirMissing, closePicker, cancelProvisional,
      busy: () => (typeof columnBusy === "function" ? columnBusy() : (!!provisionalId || failedProvisionals.size > 0)),
      answer: (v) => { const c = confirm; confirm = null; if (c) c.cb(v); },
      confirm: () => (confirm ? { title: confirm.title, buttons: confirm.buttons } : null),
      type: (t) => { EL["composer-input"].value = t; }, composer: () => EL["composer-input"].value,
      picker: () => ({ open: EL.picker.style.display !== "none", search: EL["picker-search"].value, dir: EL["picker-dir"].value }),
      state: () => ({ provisionalId, pendingCarry, dirQuestion, activeId, drafts: Object.fromEntries(drafts) }),
    };
  `;
  const make = new Function("W", "window", prelude + js + epilogue) as (w: unknown, win: unknown) => Api;
  const api = make({ provisionalName, mintProvisionalId, HOOKS, activeId: o.activeId, mru: o.mru, order: o.order, nextActive: o.nextActive }, win);
  return { api, HOOKS };
}
const flips = (h: Hooks, busy: boolean) => h.posts.filter((p) => p.romp === "colBusy" && p.busy === busy).length;

// a create from the picker in a column showing C, the text typed into the provisional tab's box, then the kernel's folder question
function askedWorld() {
  const w = world({ activeId: C, mru: [C, A], order: [A, B, C], nextActive: null });
  w.api.startCreate(REQ);
  assert.equal(w.api.busy(), true, "a provisional tab: busy");
  assert.equal(flips(w.HOOKS, true), 1);
  w.api.type(TYPED);
  w.api.onCreateDirMissing({ name: REQ.name, dir: REQ.dir, status: { canCreate: true } });
  return w;
}

test("the folder question keeps the column busy: no flip when the provisional drops for the prompt", () => {
  const w = askedWorld();
  assert.deepEqual(w.api.confirm(), { title: "That folder isn't there", buttons: ["create", "edit"] });
  assert.equal(w.api.state().provisionalId, null, "the provisional tab is gone…");
  assert.equal(w.api.state().pendingCarry, TYPED, "…its text carried for the retry");
  assert.equal(w.api.state().activeId, null, "the held column shows no tab now: the box is unbound");
  assert.equal(w.api.busy(), true, "the question IS the create in flight: the shell keeps holding the column");
  assert.equal(flips(w.HOOKS, false), 0, "no colBusy:false posted — before this the held column closed here, prompt and carry with it");
});

test("Edit the path keeps the question and its carry alive in the picker; closing the picker with no create abandons it: the text lands in a draft, persisted, THEN the flip", () => {
  const w = askedWorld();
  w.api.answer("edit");
  assert.equal(w.HOOKS.pickers, 1); assert.deepEqual(w.api.picker(), { open: true, search: REQ.name, dir: REQ.dir }, "reopened to retry THIS create");
  assert.equal(w.api.busy(), true, "still the create in flight"); assert.equal(flips(w.HOOKS, false), 0); assert.equal(w.api.state().pendingCarry, TYPED, "the carry waits for the create from the picker");
  w.api.closePicker();   // Escape, the backdrop, the toggle: no create came
  assert.equal(w.api.busy(), false, "abandoned: the question is over");
  assert.equal(w.api.state().pendingCarry, "");
  assert.equal(w.api.state().drafts[C], TYPED, "the text is the draft of the tab the column showed last (C): its owner's box, once the shell hands it over at the close");
  assert.equal(flips(w.HOOKS, false), 1, "exactly one flip");
  assert.deepEqual(w.HOOKS.seq.slice(-2), ["persist", "flip:false"], "persisted first, the flip last");
  assert.deepEqual(w.HOOKS.posts[w.HOOKS.posts.length - 1], { romp: "colBusy", busy: false }, "the flip is the last thing the shell hears");
});

test("Create it and start is the retry: the carry comes back into the new provisional's box, busy stays, and that create's settlement flips", () => {
  const w = askedWorld();
  w.api.answer("create");
  const creates = w.HOOKS.sent.filter((m) => m.type === "createSession");
  assert.equal(creates.length, 2); assert.equal(creates[1].mkdir, true, "the very same create, with mkdir");
  assert.ok(w.api.state().provisionalId, "a new provisional tab"); assert.equal(w.api.composer(), TYPED, "with the text back in its box");
  assert.equal(w.api.state().pendingCarry, ""); assert.equal(w.api.state().drafts[C], undefined, "startCreate's own picker close did not abandon the question it was retrying");
  assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, false), 0, "busy throughout: no flip yet");
  w.api.cancelProvisional();   // one settlement (the ✕): the text is the user's to drop
  assert.equal(w.api.busy(), false); assert.equal(flips(w.HOOKS, false), 1); assert.deepEqual(w.HOOKS.posts[w.HOOKS.posts.length - 1], { romp: "colBusy", busy: false });
});

test("the prompt dismissed (Escape, the backdrop, a newer dialog) abandons the question the same way", () => {
  const w = askedWorld();
  w.api.answer(null);
  assert.equal(w.api.busy(), false); assert.equal(w.api.state().pendingCarry, ""); assert.equal(w.api.state().drafts[C], TYPED);
  assert.deepEqual(w.HOOKS.seq.slice(-2), ["persist", "flip:false"]);
});

test("with nothing typed the abandonment still ends the question, writing no draft", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null });
  w.api.startCreate(REQ);
  w.api.onCreateDirMissing({ name: REQ.name, dir: REQ.dir, status: { canCreate: true } });
  assert.equal(w.api.busy(), true);
  w.api.answer(null);
  assert.equal(w.api.busy(), false); assert.deepEqual(w.api.state().drafts, {}); assert.equal(flips(w.HOOKS, false), 1);
});
