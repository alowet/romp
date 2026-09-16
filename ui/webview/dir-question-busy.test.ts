// The FOLDER QUESTION keeps the provisional TAB (round four of the held-column deferral, 2026-09-15). The create flow's real
// functions are lifted from render.ts (the chat-split-exec.test.ts pattern) over a world that plays the shell (a parent window
// counting colBusy posts), the kernel (createSession / cancelCreate sent), the dialog (showConfirm's head mirrored — the real
// closeConfirm is lifted — answered by the test) and the picker (an element with a display; the real dismissDirPromptForPicker
// runs first, as in openPicker), and driven the way the page is: a create from the picker, text typed into the provisional
// tab's box, the kernel's createDirMissing, then each of the user's answers. What is pinned:
//   * the question keeps the TAB — its box holds the text, the column is busy by provisionalId alone, no colBusy:false, the
//     backstop stood down (the kernel answered);
//   * a DISMISSAL (Escape, the backdrop, the picker closed with no create) makes it a failed create: the text in its own box and
//     under its own id only — no other session's draft touched, a sub-agent viewer active or not — busy stays, no flip; the
//     user's ✕ is the one discard, and that flips;
//   * "Create it and start" retries on the SAME tab (one tab, one create; the backstop armed again); "Edit the path" keeps the
//     tab and prefills the picker; the same name created from there is the retry too;
//   * the picker opened OVER the prompt (the palette's Mod+Shift+O) dismisses it first as its own create's — quietly — so a
//     second create's question can never settle the first; and an older prompt a newer dialog cancels settles nothing.
// The default world models a HELD column (once its listed member is gone nothing is held here, focusAfterDismiss); `nextActive`
// models an ordinary one. Synthetic ids only.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { createRequire } from "node:module";
import { provisionalName, mintProvisionalId, isProvisionalId } from "./provisional";

const requireCjs = createRequire(__filename);
const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const fn = (name: string): string => {
  const i = RENDER.indexOf(`function ${name}(`);
  assert.ok(i >= 0, `${name} not found`);
  return RENDER.slice(i, RENDER.indexOf("\n}\n", i) + 3);
};
const lineOpt = (name: string): string => { const i = RENDER.indexOf(`function ${name}(`); return i >= 0 ? RENDER.slice(i, RENDER.indexOf("\n", i) + 1) : ""; };   // a ONE-LINE function; "" on an older render.ts
const fnOpt = (name: string): string => (RENDER.indexOf(`function ${name}(`) >= 0 ? fn(name) : "");   // "" on an older render.ts: the tests then fail on behaviour, not on a missing lift

const A = "11111111-2222-3333-4444-555555555501", B = "11111111-2222-3333-4444-555555555502", C = "11111111-2222-3333-4444-555555555503";
const VIEWER = C + "/agent/a1";
const REQ = { name: "notes", backend: "sdk", dir: "/proj/not-there-yet", host: "" };
const TYPED = "notes for a session whose folder is not there yet";

type Hooks = { posts: Record<string, unknown>[]; sent: Record<string, unknown>[]; seq: string[]; confirms: string[]; pickers: number; persisted: number; timers: (() => void)[]; cleared: number; toasts: string[]; answered: (string | null)[] };
type State = { provisionalId: string | null; dirQuestionFor: string | null; failed: string[]; activeId: string | null; drafts: Record<string, string>; sessions: string[]; timer: boolean; why: Record<string, string> };
type Api = {
  startCreate: (req: typeof REQ, mkdir?: boolean) => void; onCreateDirMissing: (m: Record<string, unknown>) => void; closePicker: (abandon?: boolean) => void;
  openPicker: () => void; cancelProvisional: () => void; closeTabLocally: (id: string) => void;
  onCreateWarn: (m: { text: string; rid?: unknown }) => void; showConfirm: (title: string, detail: string, buttons: { label: string; value: string }[], cb: (v: string | null) => void) => void;
  busy: () => boolean; answer: (v: string | null) => void; confirm: () => { title: string; buttons: string[]; key: string | null } | null;
  overlays: () => number; clickButton: (label: string) => boolean; rid: () => string | null;
  type: (t: string) => void; composer: () => string; picker: () => { open: boolean; search: string; dir: string }; state: () => State;
};

function world(o: { activeId: string | null; mru: string[]; order: string[]; nextActive: string | null }): { api: Api; HOOKS: Hooks } {
  const HOOKS: Hooks = { posts: [], sent: [], seq: [], confirms: [], pickers: 0, persisted: 0, timers: [], cleared: 0, toasts: [], answered: [] };
  const win = { parent: { postMessage(m: Record<string, unknown>) { HOOKS.posts.push(m); if (m.romp === "colBusy") HOOKS.seq.push("flip:" + m.busy); } } };
  const js = requireCjs("esbuild").transformSync(
    [lineOpt("columnBusy"), fn("syncColumnBusy"), fn("dropProvisional"), fn("openProvisional"), fn("cancelProvisional"), fn("failProvisional"),
     fn("onCreateDirMissing"), fnOpt("dirWhy"), fnOpt("dismissDirPromptForPicker"), fn("closePicker"), fn("startCreate"), fn("closeConfirm"), fn("closeTabLocally"),
     fn("showConfirm"), fnOpt("onCreateWarn"), lineOpt("createReplyIsStale"), lineOpt("mintRid")].join("\n"),
    { loader: "ts" }).code;
  const prelude = `
    const { provisionalName, mintProvisionalId, isProvisionalId, HOOKS } = W;
    let provisionalId = null, provisionalTags = [], pendingNewSession = null, provisionalTimer = undefined, dirQuestionFor = null, pendingCarry = "", dirQuestion = false;
    let columnBusyTold = false, lastCreate = null, pickMode = false, activeId = W.activeId, confirmCb = null, confirmKey = null, provisionalRid = null;
    const failedWhy = new Map();
    const provisionalQueue = []; const failedProvisionals = new Set(); const drafts = new Map(); const pendingSent = new Map(); const sessions = new Map(); const closingTabs = new Map();
    const order = W.order.slice(); const mru = W.mru.slice();
    const PROVISIONAL_WAIT_MS = 90000;
    const EL = { "composer-input": { value: "", focus() {} }, picker: { style: { display: "none" } }, "picker-search": { value: "" }, "picker-dir": { value: "", focus() {}, select() {} } };
    // a mini DOM for the REAL dialog (showConfirm / closeConfirm): elements with an id, children, listeners; #confirm found by walking the body
    const mk = (tag, cls) => { const n = { tagName: tag, className: cls || "", id: "", textContent: "", children: [], parent: null, handlers: {}, dataset: {}, _key: undefined,
      appendChild(c) { c.parent = n; n.children.push(c); return c; },
      remove() { if (n.parent) { const i = n.parent.children.indexOf(n); if (i >= 0) n.parent.children.splice(i, 1); n.parent = null; } },
      addEventListener(t, f) { (n.handlers[t] = n.handlers[t] || []).push(f); }, click() { (n.handlers.click || []).forEach((f) => f({ target: n })); },
      get firstElementChild() { return n.children[0] || null; }, focus() {} }; return n; };
    const body = mk("body", ""); const findId = (node, id) => { if (node.id === id) return node; for (const c of node.children) { const r = findId(c, id); if (r) return r; } return null; };
    const document = { body, getElementById: (id) => EL[id] || findId(body, id), addEventListener() {}, removeEventListener() {} };
    const el = (tag, cls) => mk(tag, cls);
    const warnToast = (t) => { HOOKS.toasts.push(t); };
    const vscodeApi = { postMessage: (m) => { HOOKS.sent.push(m); } };
    const renderTabs = () => {}; const growComposer = () => {};
    // the real setActive swaps the box: the leaving tab's text to its draft, the arriving tab's draft into the box
    const setActive = (id) => { if (activeId && activeId !== id && EL["composer-input"].value) drafts.set(activeId, EL["composer-input"].value); activeId = id; EL["composer-input"].value = drafts.get(id) ?? ""; };
    // the HELD column: once the listed member is gone nothing is held here, so a dismissed tab leaves the box unbound (focusAfterDismiss); an ordinary column reselects (W.nextActive)
    const dismissSession = (id) => { sessions.delete(id); const i = order.indexOf(id); if (i >= 0) order.splice(i, 1); const j = mru.indexOf(id); if (j >= 0) mru.splice(j, 1); drafts.delete(id); if (activeId === id) activeId = W.nextActive; };
    const persistDrafts = () => { HOOKS.persisted++; HOOKS.seq.push("persist"); }; const loadComposerFor = () => {}; const stashActiveDraft = () => {};
    const createDirPrompt = () => "the folder question"; const askDirComplete = () => {};
    // the real openPicker's first act (lifted), then the picker
    const openPicker = () => { if (typeof dismissDirPromptForPicker === "function") dismissDirPromptForPicker(); EL.picker.style.display = "block"; HOOKS.pickers++; };
    const rememberDir = () => {}; const signalPickerOverlay = () => {}; const syncComposerPh = () => {};
    const setTimeout = (f) => { HOOKS.timers.push(f); return HOOKS.timers.length; }; const clearTimeout = () => { HOOKS.cleared++; };
  `;
  const epilogue = `
    const overlay = () => findId(body, "confirm");
    return {
      startCreate, onCreateDirMissing, closePicker, openPicker, cancelProvisional, closeTabLocally, showConfirm,
      onCreateWarn: (m) => { if (typeof onCreateWarn === "function") onCreateWarn(m); else { if (provisionalId) failProvisional(m.text); else warnToast(m.text); } },
      busy: () => (typeof columnBusy === "function" ? columnBusy() : (!!provisionalId || failedProvisionals.size > 0)),
      answer: (v) => { closeConfirm(v); },
      // the dialog up, read off the real overlay: its title, its buttons' labels, what it is about
      confirm: () => { const o = overlay(); if (!o) return null; const box = o.children[0]; return { title: box.children[0].textContent, buttons: box.children[2].children.map((b) => b.textContent), key: confirmKey }; },
      overlays: () => body.children.filter((c) => c.id === "confirm").length,
      clickButton: (label) => { const o = overlay(); const b = o && o.children[0].children[2].children.find((x) => x.textContent === label); if (b) b.click(); return !!b; },
      rid: () => provisionalRid,
      type: (t) => { EL["composer-input"].value = t; }, composer: () => EL["composer-input"].value,
      picker: () => ({ open: EL.picker.style.display !== "none", search: EL["picker-search"].value, dir: EL["picker-dir"].value }),
      state: () => ({ provisionalId, dirQuestionFor, failed: [...failedProvisionals], activeId, drafts: Object.fromEntries(drafts), sessions: [...sessions.keys()], timer: provisionalTimer !== undefined, why: Object.fromEntries(failedWhy) }),
    };
  `;
  const make = new Function("W", "window", prelude + js + epilogue) as (w: unknown, win: unknown) => Api;
  const api = make({ provisionalName, mintProvisionalId, isProvisionalId, HOOKS, activeId: o.activeId, mru: o.mru, order: o.order, nextActive: o.nextActive }, win);
  return { api, HOOKS };
}
const flips = (h: Hooks, busy: boolean) => h.posts.filter((p) => p.romp === "colBusy" && p.busy === busy).length;
const last = (h: Hooks) => h.posts[h.posts.length - 1];

// a create from the picker in a column showing C, text typed into the provisional tab's box, then the kernel's folder question
function asked(o: Partial<Parameters<typeof world>[0]> = {}) {
  const w = world({ activeId: C, mru: [C, A], order: [A, B, C], nextActive: null, ...o });
  w.api.startCreate(REQ);
  const id = w.api.state().provisionalId!;
  assert.ok(id && isProvisionalId(id), "a provisional tab"); assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, true), 1);
  w.api.type(TYPED);
  w.api.onCreateDirMissing({ name: REQ.name, dir: REQ.dir, status: { canCreate: true } });
  return { w, id };
}

test("the folder question keeps the provisional TAB: its text in its box, the column busy by that tab alone, no flip, the backstop stood down", () => {
  const { w, id } = asked();
  const st = w.api.state();
  assert.equal(st.provisionalId, id, "the tab stays: the create in flight"); assert.ok(st.sessions.includes(id)); assert.equal(st.activeId, id);
  assert.equal(w.api.composer(), TYPED, "its text where it was typed"); assert.deepEqual(st.drafts, {}, "carried nowhere");
  assert.equal(st.dirQuestionFor, id, "the question is this create's"); assert.equal(st.timer, false, "the kernel answered: the wait is the user's");
  assert.deepEqual(w.api.confirm(), { title: "That folder isn't there", buttons: ["Create it and start", "Edit the path"], key: "dir:" + id }, "the prompt, keyed to the create (no request id on this reply: the tab's)");
  assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, false), 0, "no colBusy:false — a held column stands under the prompt");
});

test("dismissed (Escape, the backdrop): a FAILED create — the text in its own box and under its own id, no other session's draft touched, busy stays, no flip; the ✕ discards and flips", () => {
  const { w, id } = asked();
  w.api.answer(null);
  const st = w.api.state();
  assert.equal(st.provisionalId, null); assert.deepEqual(st.failed, [id], "a failed create now"); assert.equal(st.dirQuestionFor, null);
  assert.deepEqual(st.drafts, { [id]: TYPED }, "the text under the failed tab's own id and nowhere else"); assert.equal(w.api.composer(), TYPED); assert.equal(st.activeId, id, "shown, in place");
  assert.equal(w.api.confirm()?.title, "Couldn't start notes", "said, as for any failed create"); assert.equal(w.api.overlays(), 1);
  assert.equal(w.api.busy(), true, "busy: the failed tab holds the text"); assert.equal(flips(w.HOOKS, false), 0);
  w.api.closeTabLocally(id);   // the user's ✕: the one discard
  assert.deepEqual(w.api.state().failed, []); assert.deepEqual(w.api.state().drafts, {});
  assert.equal(w.api.busy(), false); assert.equal(flips(w.HOOKS, false), 1); assert.deepEqual(last(w.HOOKS), { romp: "colBusy", busy: false }, "the flip, last");
});

test("a sub-agent viewer active when the create started: dismissed, the text is in the failed tab and nothing is written under the viewer's id or any session's", () => {
  const { w, id } = asked({ activeId: VIEWER, mru: [VIEWER, C], nextActive: VIEWER });
  w.api.answer(null);
  assert.deepEqual(w.api.state().drafts, { [id]: TYPED }); assert.deepEqual(w.api.state().failed, [id]); assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, false), 0);
});

test("an ordinary column (not held): the same — the failed tab holds the text; it is never appended to the tab the column falls back to", () => {
  const { w, id } = asked({ nextActive: C });
  w.api.answer(null);
  assert.deepEqual(w.api.state().drafts, { [id]: TYPED }, "not C's draft"); assert.equal(w.api.state().drafts[C], undefined); assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, false), 0);
});

test("Create it and start: the retry on the SAME tab — the same create with mkdir, the text where it was, the backstop armed again; that create's settlement flips", () => {
  const { w, id } = asked();
  const timers = w.HOOKS.timers.length;
  w.api.answer("create");
  const creates = w.HOOKS.sent.filter((m) => m.type === "createSession");
  assert.equal(creates.length, 2); assert.equal(creates[1].mkdir, true, "the very same create, with mkdir");
  const st = w.api.state();
  assert.equal(st.provisionalId, id, "one tab, one create"); assert.deepEqual(st.sessions.filter(isProvisionalId), [id]); assert.equal(w.api.composer(), TYPED);
  assert.equal(st.dirQuestionFor, null, "the question is answered"); assert.equal(st.timer, true); assert.equal(w.HOOKS.timers.length, timers + 1, "the backstop, armed again");
  assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, false), 0);
  w.api.cancelProvisional();   // one settlement (the ✕ on a pending tab)
  assert.equal(w.api.busy(), false); assert.equal(flips(w.HOOKS, false), 1); assert.deepEqual(last(w.HOOKS), { romp: "colBusy", busy: false });
});

test("Edit the path: the tab stays and the picker is prefilled to retry it; the same name created from there is the retry; the picker closed with no create dismisses it into a failed tab", () => {
  const a = asked();
  a.w.api.answer("edit");
  assert.deepEqual(a.w.api.picker(), { open: true, search: REQ.name, dir: REQ.dir }); assert.equal(a.w.api.state().provisionalId, a.id, "the tab stays"); assert.equal(a.w.api.state().dirQuestionFor, a.id);
  assert.equal(a.w.api.busy(), true); assert.equal(flips(a.w.HOOKS, false), 0);
  a.w.api.startCreate({ ...REQ, dir: "/proj/there" });   // the path edited, the same name: the retry
  assert.equal(a.w.api.state().provisionalId, a.id, "the same tab"); assert.equal(a.w.api.composer(), TYPED); assert.equal(a.w.api.state().dirQuestionFor, null); assert.equal(a.w.api.picker().open, false);
  assert.equal(a.w.api.busy(), true); assert.equal(flips(a.w.HOOKS, false), 0);
  const b = asked();
  b.w.api.answer("edit");
  b.w.api.closePicker();   // Escape, the backdrop, the toggle: no create came
  assert.deepEqual(b.w.api.state().failed, [b.id], "dismissed: a failed create"); assert.deepEqual(b.w.api.state().drafts, { [b.id]: TYPED }); assert.equal(b.w.api.busy(), true); assert.equal(flips(b.w.HOOKS, false), 0);
});

test("the picker opened OVER the prompt (Mod+Shift+O) dismisses it first, quietly, as its own create's; a second create's question then settles only itself; no flip until both are discarded", () => {
  const { w, id: id1 } = asked();
  w.api.openPicker();
  assert.deepEqual(w.api.state().failed, [id1], "the first create: a failed tab, its text kept"); assert.deepEqual(w.api.state().drafts, { [id1]: TYPED });
  assert.equal(w.api.overlays(), 0, "quietly: no dialog — the picker the user asked for is the foreground"); assert.equal(w.api.confirm(), null);
  assert.match(w.api.state().why[id1] || "", /^That folder isn't there/, "…the tab's own placeholder says why");
  assert.equal(w.api.picker().open, true); assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, false), 0);
  w.api.startCreate({ ...REQ, name: "notes-2", dir: "/proj/also-missing" });
  const id2 = w.api.state().provisionalId!;
  assert.ok(id2 && id2 !== id1, "a second create, its own tab"); assert.equal(w.api.composer(), "", "nothing carried: the first create's text stays in its failed tab");
  w.api.type("the second note");
  w.api.onCreateDirMissing({ name: "notes-2", dir: "/proj/also-missing", status: { canCreate: true } });
  assert.deepEqual(w.api.confirm(), { title: "That folder isn't there", buttons: ["Create it and start", "Edit the path"], key: "dir:" + id2 }, "the second question, keyed to the second create");
  assert.equal(w.api.state().provisionalId, id2); assert.deepEqual(w.api.state().failed, [id1]); assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, false), 0, "busy throughout");
  w.api.answer(null);
  assert.deepEqual(w.api.state().failed, [id1, id2]); assert.deepEqual(w.api.state().drafts, { [id1]: TYPED, [id2]: "the second note" });
  w.api.closeTabLocally(id1);
  assert.equal(w.api.busy(), true, "the second failed tab still holds text"); assert.equal(flips(w.HOOKS, false), 0);
  w.api.closeTabLocally(id2);
  assert.equal(w.api.busy(), false); assert.equal(flips(w.HOOKS, false), 1);
});

test("an older prompt a newer create's dialog cancels settles nothing: the second create stands, the first's text came along into its box", () => {
  const { w, id: id1 } = asked();
  w.api.startCreate({ ...REQ, name: "notes-2", dir: "/proj/also-missing" });   // a second create straight away, the first prompt still up: it supersedes the first (and takes its text)
  const id2 = w.api.state().provisionalId!;
  assert.ok(id2 !== id1); assert.equal(w.api.composer(), TYPED, "the superseded create's text, in the new tab's box"); assert.deepEqual(w.api.state().failed, []);
  w.api.onCreateDirMissing({ name: "notes-2", dir: "/proj/also-missing", status: { canCreate: true } });   // its dialog cancels the first prompt first
  assert.equal(w.api.state().provisionalId, id2, "the first prompt's cancel settled nothing"); assert.deepEqual(w.api.state().failed, []); assert.equal(w.api.state().dirQuestionFor, id2);
  assert.deepEqual(w.api.confirm(), { title: "That folder isn't there", buttons: ["Create it and start", "Edit the path"], key: "dir:" + id2 });
  assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, false), 0);
});

test("round five: a create's request id rides the request; a late reply naming a superseded create is ignored, the current create untouched", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null });
  w.api.startCreate(REQ);
  const sentA = w.HOOKS.sent.filter((m) => m.type === "createSession")[0];
  assert.equal(typeof sentA.rid, "string", "every attempt carries a request id"); assert.equal(w.api.rid(), sentA.rid, "the pending tab waits on it");
  const idA = w.api.state().provisionalId!;
  w.api.type("for A, on a slow host");
  w.api.openPicker(); w.api.startCreate({ ...REQ, name: "notes-b", dir: "/proj/also-not-there" });   // A superseded before its host answered (its text comes along)
  const idB = w.api.state().provisionalId!, sentB = w.HOOKS.sent.filter((m) => m.type === "createSession")[1];
  assert.ok(idB !== idA); assert.equal(w.api.rid(), sentB.rid); assert.notEqual(sentB.rid, sentA.rid);
  // A's late folder question: nobody's — no prompt over B, B still pending with its backstop, no question pending
  w.api.onCreateDirMissing({ name: REQ.name, dir: REQ.dir, status: { canCreate: true }, rid: sentA.rid });
  assert.equal(w.api.overlays(), 0, "ignored"); assert.equal(w.api.state().dirQuestionFor, null); assert.equal(w.api.state().provisionalId, idB); assert.equal(w.api.state().timer, true);
  // A's late refusal: nobody's either — B is not failed, nothing toasted
  w.api.onCreateWarn({ text: "the host refused A", rid: sentA.rid });
  assert.equal(w.api.state().provisionalId, idB); assert.deepEqual(w.api.state().failed, []); assert.deepEqual(w.HOOKS.toasts, []); assert.equal(flips(w.HOOKS, false), 0);
  // B's own question: B's prompt, keyed to B's request
  w.api.onCreateDirMissing({ name: "notes-b", dir: "/proj/also-not-there", status: { canCreate: true }, rid: sentB.rid });
  assert.deepEqual(w.api.confirm(), { title: "That folder isn't there", buttons: ["Create it and start", "Edit the path"], key: "dir:" + sentB.rid }); assert.equal(w.api.state().dirQuestionFor, idB);
  // …and after the retry (a new request id) A's — or the first attempt's — late question is stale too
  w.api.answer("create");
  const sentB2 = w.HOOKS.sent.filter((m) => m.type === "createSession")[2];
  assert.notEqual(sentB2.rid, sentB.rid); assert.equal(w.api.rid(), sentB2.rid); assert.equal(sentB2.mkdir, true);
  w.api.onCreateDirMissing({ name: "notes-b", dir: "/proj/also-not-there", status: { canCreate: true }, rid: sentB.rid });
  assert.equal(w.api.overlays(), 0, "the first attempt's late question: ignored"); assert.equal(w.api.state().dirQuestionFor, null);
});

test("round five: a reply WITHOUT a request id (an older kernel) is read as today — the current create's", () => {
  const { w, id } = asked();
  assert.equal(w.api.overlays(), 1, "the folder question landed though it named no request");
  w.api.answer("create");
  w.api.onCreateWarn({ text: "the kernel said no" });   // no rid: the current create's verdict
  assert.deepEqual(w.api.state().failed, [id]); assert.equal(w.api.state().why[id], "the kernel said no");
});

test("round five: an unrelated dialog replacing the folder question leaves ONE #confirm — the newer, working on its first click — and the create is a failed tab with its text, its reason on the tab", () => {
  const { w, id } = asked();
  assert.equal(w.api.overlays(), 1);
  let delivered = null;
  w.api.showConfirm("That action was not delivered", "the kernel could not take it", [{ label: "Dismiss", value: "ok" }], (v) => { delivered = v; });
  assert.equal(w.api.overlays(), 1, "never two #confirm"); assert.equal(w.api.confirm()?.title, "That action was not delivered", "the newer dialog is the one up");
  assert.deepEqual(w.api.state().failed, [id], "the folder question's create: a failed tab"); assert.deepEqual(w.api.state().drafts, { [id]: TYPED }, "its text kept");
  assert.match(w.api.state().why[id] || "", /^That folder isn't there/, "the reason on the tab, not in a second dialog"); assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, false), 0);
  assert.equal(w.api.clickButton("Dismiss"), true);
  assert.equal(delivered, "ok", "the visible dialog's own callback ran on the first click"); assert.equal(w.api.overlays(), 0, "…and it is gone"); assert.equal(w.api.confirm(), null);
});
