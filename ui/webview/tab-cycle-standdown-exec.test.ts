// The session pair stands down at the PANE, EXECUTED against what is really open on the page (review, 2026-09-24):
// a nextTab / prevTab message, which the shell's Ctrl+Alt+arrows post and the VS Code view's rompChat.nextTab /
// prevTab post straight to the pane, must not switch the session behind a layer of this page, and must step again
// the moment the page closes that layer. The fake page is a small DOM (elements attached under a body, ids, classes,
// the hidden attribute, an inline display) and each layer is opened and closed the way the page's own code does it:
// the upload confirm through render.ts's real showConfirm and closeConfirm; the new-session picker through its real
// closePicker, which only HIDES it (the picker is built once and stays in the page, so a check that finds it without
// asking whether it is shown holds every key it gates for the rest of the page's life); the settings card and the
// Token usage panel through gear.js's real open and close lines; the rest by the few statements the page runs for
// them, pinned at source in the last test. Lifted in chat-exact-tail-exec.test.ts's idiom (an anchored slice, esbuild
// at run time, new Function): the message arm with the real cycleTab and asGesture beneath it, the snapshot view's
// Escape wiring, and the two older gates that read the same overlay check (the bare arrows, typing from anywhere).
// Synthetic: the notes-api demo's sessions.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { createRequire } from "node:module";

const requireCjs = createRequire(__filename);
const read = (...p: string[]): string => fs.readFileSync(path.resolve(process.cwd(), "..", ...p), "utf8");
const RENDER = read("ui", "webview", "render.ts");
const GEAR = read("ui", "webview", "gear.js");

function slice(src: string, startAnchor: string, endAnchor: string, name: string): string {
  const a = src.indexOf(startAnchor), b = src.indexOf(endAnchor, a);
  assert.ok(a > 0 && b > a, name + ": anchors not found (" + startAnchor.slice(0, 40) + " / " + endAnchor.slice(0, 40) + "); re-anchor");
  return src.slice(a, b);
}
/** A top-level render.ts function, through its closing brace. */
const fn = (start: string, name: string): string => slice(RENDER, start, "\n}\n", name) + "\n}\n";
const ts = (code: string): string => requireCjs("esbuild").transformSync(code, { loader: "ts" }).code;

type Listener = (e: any) => void;

/** One element of the fake page: what the lifted code touches, no more. */
class FakeEl {
  readonly tagName: string;
  id = ""; className = ""; hidden = false; disabled = false; textContent = "";
  readonly style: { display?: string } = {};
  readonly children: FakeEl[] = [];
  parentNode: FakeEl | null = null;
  readonly listeners: Record<string, Listener[]> = {};
  constructor(tag: string, readonly owner: FakeDoc) { this.tagName = tag.toUpperCase(); }
  hasClass(c: string): boolean { return this.className.split(/\s+/).includes(c); }
  get firstElementChild(): FakeEl | null { return this.children[0] ?? null; }
  contains(n: FakeEl | null): boolean { for (let x = n; x; x = x.parentNode) if (x === this) return true; return false; }
  appendChild(c: FakeEl): FakeEl { c.remove(); c.parentNode = this; this.children.push(c); return c; }
  append(...cs: FakeEl[]): void { for (const c of cs) this.appendChild(c); }
  /** Detached, as the DOM does it: no lookup finds it, and focus inside it falls back to the body. */
  remove(): void {
    const p = this.parentNode;
    if (!p) return;
    if (this.contains(this.owner.activeElement)) this.owner.activeElement = this.owner.body;
    p.children.splice(p.children.indexOf(this), 1);
    this.parentNode = null;
  }
  addEventListener(t: string, f: Listener): void { (this.listeners[t] ??= []).push(f); }
  removeEventListener(t: string, f: Listener): void { const l = this.listeners[t] ?? []; const i = l.indexOf(f); if (i >= 0) l.splice(i, 1); }
  fire(t: string): void { for (const f of (this.listeners[t] ?? []).slice()) f({ type: t, target: this, stopPropagation() {}, preventDefault() {} }); }
  focus(): void { this.owner.activeElement = this; }
}

/** The page's lookups read #id, .class, their compounds and :not([hidden]), joined by commas; any other selector is a
 *  new kind of lookup this fake does not know, so it throws rather than answer "absent" by accident. */
function selectorTest(sel: string): (n: FakeEl) => boolean {
  const alts = sel.split(",").map((raw) => {
    const s = raw.trim();
    const m = /^((?:[#.][\w-]+)+)(:not\(\[hidden\]\))?$/.exec(s);
    if (!m) throw new Error("the fake page reads #id, .class and :not([hidden]), not " + JSON.stringify(s) + ": extend it");
    const parts = m[1].match(/[#.][\w-]+/g) ?? [];
    const shownOnly = !!m[2];
    return (n: FakeEl) => parts.every((p) => (p[0] === "#" ? n.id === p.slice(1) : n.hasClass(p.slice(1)))) && (!shownOnly || !n.hidden);
  });
  return (n) => alts.some((t) => t(n));
}

class FakeDoc {
  readonly body: FakeEl;
  activeElement: FakeEl | null;
  readonly listeners: Record<string, Listener[]> = {};
  constructor() { this.body = new FakeEl("body", this); this.activeElement = this.body; }
  createElement(tag: string): FakeEl { return new FakeEl(tag, this); }
  /** Every attached element, in document order. */
  all(): FakeEl[] { const out: FakeEl[] = []; const walk = (n: FakeEl) => { for (const c of n.children) { out.push(c); walk(c); } }; walk(this.body); return out; }
  getElementById(id: string): FakeEl | null { return this.all().find((n) => n.id === id) ?? null; }
  querySelectorAll(sel: string): FakeEl[] { const t = selectorTest(sel); return this.all().filter(t); }
  querySelector(sel: string): FakeEl | null { return this.querySelectorAll(sel)[0] ?? null; }
  addEventListener(t: string, f: Listener): void { (this.listeners[t] ??= []).push(f); }
  removeEventListener(t: string, f: Listener): void { const l = this.listeners[t] ?? []; const i = l.indexOf(f); if (i >= 0) l.splice(i, 1); }
}

type Win = { keydown: Listener[]; addEventListener(t: string, f: Listener): void };
type Hooks = { order: string[]; active: string; switched: Array<[string, boolean]> };
type StateKey = "ctxMenuEl" | "metaMenuEl" | "citePreviewEl" | "openCommentKey" | "pendingCommentAnchor";
type Button = { label: string; value: string; danger?: boolean };
type PageApi = {
  onMsg: (m: { type: string; gesture?: boolean }) => void;
  escapeLayerOpen: () => boolean;
  activeId: () => string;
  set: (k: StateKey, v: unknown) => void;
  el: (tag: string, cls?: string) => FakeEl;
  showConfirm: (title: string, detail: string, buttons: Button[], cb: (v: string | null) => void) => void;
  closePicker: () => void;
  pickerVisible: () => boolean;
  typeTarget: (e: { target: FakeEl }) => FakeEl | null;
};
type Lifted = (h: Hooks, doc: FakeDoc, win: Win) => PageApi;

function lift(): Lifted {
  const el = ts(fn("function el(tag: string, cls?: string): HTMLElement {", "el"));
  const typing = ts(fn("function isTypingTarget(t: EventTarget | null): boolean {", "isTypingTarget"));
  // the chat window's bare-arrow handler, to its close; it registers itself on the window stub
  const keydown = ts(slice(RENDER, 'window.addEventListener("keydown", (e) => {\n  if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;',
    "\n});\n", "the bare-arrow handler") + "\n});\n");
  const typeGate = ts(fn("function typeFromAnywhereTarget(e: Event): HTMLTextAreaElement | null {", "typeFromAnywhereTarget"));
  const confirm = ts(slice(RENDER, "let confirmCb: ((v: string | null) => void) | null = null;", "// ---- move session", "showConfirm")
    + fn("function closeConfirm(value: string | null) {", "closeConfirm"));
  // pickerVisible and closePicker, and whatever the page keeps between them
  const picker = ts(slice(RENDER, "function pickerVisible(): boolean {", "function pickerRows(): HTMLElement[] {", "the picker's show and hide"));
  // the snapshot view's Escape: the page's list of layers (and the predicate the pair shares with it)
  const esc = ts(slice(RENDER, "// ESCAPE LEAVES THE VIEW", "/** Paint (or refresh) the view of `snapView`", "the snapshot Escape"));
  const gesture = ts(fn("function asGesture(fn: () => void): void {", "asGesture"));
  const cycle = ts(fn("function cycleTab(dir: number) {", "cycleTab"));
  // the message arm for the pair, up to the next arm; wrapped as a function of the message
  const arm = ts("function onMsg(m: any) { if (false) {} " + slice(RENDER, 'else if (m.type === "nextTab")', 'else if (m.type === "settingRefused"', "the pair's arm") + " }");
  const prelude = `
    const H = HOOKS;
    const document = DOC;
    const window = WIN;
    let installed = null;
    const installSnapshotEscape = (_w, hooks) => { installed = hooks; };
    let snapView = null;
    const leaveSnapshot = () => {};
    let ctxMenuEl = null, metaMenuEl = null, citePreviewEl = null, openCommentKey = null, pendingCommentAnchor = null;
    let activeId = H.active;
    let gestureHeld = false;
    const order = H.order;
    const lastStripItems = [];
    const collapsedTabIds = new Set();
    const liveAsks = new Map();
    const pickFirstVisibleTab = () => false;
    const visibleOrder = () => H.order.slice();
    const neighborOfFolded = () => null;
    const setActive = (id) => { H.switched.push([id, gestureHeld]); activeId = id; };
    const composerNoteHolds = () => false;
    let pickMode = false;
    const vscodeApi = null;
    const signalPickerOverlay = () => {};
    const syncComposerPh = () => {};
  `;
  const epilogue = `
    return {
      onMsg, escapeLayerOpen: () => installed.layerOpen(), activeId: () => activeId, el, showConfirm, closePicker, pickerVisible,
      typeTarget: (e) => typeFromAnywhereTarget(e),
      set: (k, v) => {
        if (k === "ctxMenuEl") ctxMenuEl = v; else if (k === "metaMenuEl") metaMenuEl = v; else if (k === "citePreviewEl") citePreviewEl = v;
        else if (k === "openCommentKey") openCommentKey = v; else if (k === "pendingCommentAnchor") pendingCommentAnchor = v;
        else throw new Error("unknown knob " + k);
      },
    };
  `;
  return new Function("HOOKS", "DOC", "WIN", prelude + el + typing + keydown + typeGate + confirm + picker + esc + gesture + cycle + arm + epilogue) as Lifted;
}

type Gear = { openSettings: () => void; openTokenUsage: () => void; closeTokenUsage: () => void; closeSettings: () => void };
/** gear.js's own lines for the Token usage panel's open and close and the settings card's close, run over the fake
 *  page; the card's open is the one statement that shows it (pinned in the last test). */
function liftGear(): (doc: FakeDoc) => Gear {
  const line = (start: string): string => {
    const a = GEAR.indexOf(start);
    assert.ok(a > 0 && GEAR.indexOf(start, a + 1) < 0, "gear.js: " + start.trim().slice(0, 40) + " is not one line any more; re-anchor");
    return GEAR.slice(a, GEAR.indexOf("\n", a)) + "\n";
  };
  const body = `
    var p = DOC.getElementById('rsettings'), raBack = DOC.getElementById('ranalytics-back'), raOpen = {};
    var endDrags = function () {}, raFetch = function () {}, clearSectionScroll = function () {}, setModalCls = function () {}, feedFull = function () {};
    ${line("  function raHide(e) {")}${line("  if (raOpen) raOpen.onclick = function (e) {")}${line("  function closeSettings() {")}
    return { openSettings: function () { p.hidden = false; }, openTokenUsage: function () { raOpen.onclick({ stopPropagation: function () {} }); },
             closeTokenUsage: function () { raHide({ stopPropagation: function () {} }); }, closeSettings: closeSettings };
  `;
  return new Function("DOC", body) as (doc: FakeDoc) => Gear;
}

let LIFTED: Lifted | null = null;
let GEAR_LIFTED: ((doc: FakeDoc) => Gear) | null = null;

const WEB = "11111111-2222-3333-4444-555555555501", API = "11111111-2222-3333-4444-555555555502", TESTS = "11111111-2222-3333-4444-555555555503";

/** A chat page with three sessions, web active, and what gear.js builds into it where the chat hosts its own gear
 *  (the VS Code view, whose commands post straight to the arm): the settings card and the Token usage panel, both
 *  hidden until opened. */
function page() {
  const doc = new FakeDoc();
  for (const id of ["rsettings", "ranalytics-back"]) { const n = doc.createElement("div"); n.id = id; n.hidden = true; doc.body.appendChild(n); }
  const composer = doc.createElement("textarea"); composer.id = "composer-input"; doc.body.appendChild(composer);
  const win: Win = { keydown: [], addEventListener(t, f) { if (t === "keydown") win.keydown.push(f); } };
  const H: Hooks = { order: [WEB, API, TESTS], active: WEB, switched: [] };
  const api = (LIFTED ??= lift())(H, doc, win);
  const gear = (GEAR_LIFTED ??= liftGear())(doc);
  return { doc, win, H, api, gear, composer };
}
type Page = ReturnType<typeof page>;
type Layer = { name: string; open: (p: Page) => void; close: (p: Page) => void };

/** Both messages in both forms: the VS Code view's post (no gesture field) and the shell's (gesture: true). */
function pressPair(api: PageApi): void {
  api.onMsg({ type: "nextTab" }); api.onMsg({ type: "prevTab" });
  api.onMsg({ type: "nextTab", gesture: true }); api.onMsg({ type: "prevTab", gesture: true });
}

// The statements the page runs for the layers this file does not lift (each pinned at source in the last test).
function mount(p: Page, id: string, cls?: string): FakeEl { const n = p.api.el("div", cls); n.id = id; p.doc.body.appendChild(n); return n; }
function unmount(p: Page, id: string): void { p.doc.getElementById(id)?.remove(); }
/** openPicker's own steps: build #picker the first time, then show it by display. */
function openPicker(p: Page): void {
  let overlay = p.doc.getElementById("picker");
  if (!overlay) { overlay = p.api.el("div", "picker-overlay"); overlay.id = "picker"; p.doc.body.appendChild(overlay); }
  overlay.style.display = "flex";
}
/** A menu card or the citation preview: the page appends it and holds it in its state; the close removes and clears. */
function stateLayer(name: string, key: StateKey, cls: string): Layer {
  return {
    name,
    open: (p) => { const n = p.api.el("div", cls); p.doc.body.appendChild(n); p.api.set(key, n); },
    close: (p) => { p.doc.querySelector("." + cls)?.remove(); p.api.set(key, null); },
  };
}

const UPLOAD: Button[] = [{ label: "Wait for the upload", value: "wait" }, { label: "Send without it", value: "now", danger: true }];

/** Every layer the pair stands down under, opened and closed as the page does it. */
const LAYERS: Layer[] = [
  { name: "the upload confirm",
    open: (p) => p.api.showConfirm("An attachment is still uploading", "Send now and your message goes without it. Or just wait.", UPLOAD, () => {}),
    close: (p) => { const b = p.doc.all().find((n) => n.tagName === "BUTTON" && n.textContent === "Wait for the upload"); if (!b) throw new Error("the confirm has no Wait button"); b.fire("click"); } },
  { name: "the new-session picker", open: openPicker, close: (p) => p.api.closePicker() },
  { name: "the move prompt", open: (p) => mount(p, "move-prompt", "picker-overlay confirm-overlay"), close: (p) => unmount(p, "move-prompt") },
  { name: "the fork prompt", open: (p) => mount(p, "fork-prompt", "picker-overlay confirm-overlay"), close: (p) => unmount(p, "fork-prompt") },
  stateLayer("a tab or selection menu", "ctxMenuEl", "ctx-menu"),
  stateLayer("the model or effort menu", "metaMenuEl", "meta-menu"),
  stateLayer("the citation preview", "citePreviewEl", "cite-preview"),
  { name: "the settings card", open: (p) => p.gear.openSettings(), close: (p) => p.gear.closeSettings() },
  { name: "the Token usage panel", open: (p) => { p.gear.openSettings(); p.gear.openTokenUsage(); }, close: (p) => p.gear.closeSettings() },
  { name: "the file view", open: (p) => mount(p, "romp-fileview"), close: (p) => unmount(p, "romp-fileview") },
  { name: "the file browser", open: (p) => mount(p, "romp-filebrowse"), close: (p) => unmount(p, "romp-filebrowse") },
  { name: "the picture viewer", open: (p) => mount(p, "romp-lightbox"), close: (p) => unmount(p, "romp-lightbox") },
];

test("with nothing open, the pair steps the strip as the reader's gesture, both ways, past the page's hidden panels", () => {
  const { H, api, doc } = page();
  assert.equal(doc.querySelectorAll("#rsettings, #ranalytics-back").length, 2, "the page holds both panels, hidden");
  assert.equal(api.escapeLayerOpen(), false, "the view's Escape has nothing to yield to");
  api.onMsg({ type: "nextTab" });
  assert.deepEqual(H.switched, [[API, true]], "next: web to api, announced as the reader's own switch");
  api.onMsg({ type: "prevTab" });
  assert.deepEqual(H.switched, [[API, true], [WEB, true]], "previous: back to web");
  api.onMsg({ type: "prevTab" });
  assert.deepEqual(H.switched[2], [TESTS, true], "and it wraps");
});

test("under each layer the pair stands down, and once the page closes that layer the pair steps again, twice over", () => {
  const problems: string[] = [];
  for (const L of LAYERS) {
    const p = page();
    for (const round of [1, 2]) {
      p.H.switched.length = 0;
      L.open(p);
      pressPair(p.api);
      if (p.H.switched.length) problems.push(L.name + ", open (" + round + "): the pair switched the session behind it");
      if (p.api.activeId() !== WEB) problems.push(L.name + ", open (" + round + "): the session it was opened over is no longer the active one");
      if (!p.api.escapeLayerOpen()) problems.push(L.name + ", open (" + round + "): the view's Escape does not yield to it");
      L.close(p);
      p.H.switched.length = 0;
      p.api.onMsg({ type: "nextTab" });                  // the VS Code view's post
      p.api.onMsg({ type: "prevTab", gesture: true });   // the shell's
      if (JSON.stringify(p.H.switched) !== JSON.stringify([[API, true], [WEB, true]]))
        problems.push(L.name + ", closed (" + round + "): the pair did not step, switched " + JSON.stringify(p.H.switched));
      if (p.api.escapeLayerOpen()) problems.push(L.name + ", closed (" + round + "): the view's Escape still yields to it");
    }
  }
  assert.deepEqual(problems, []);
});

test("the new-session picker stays in the page once used, hidden, and a hidden picker holds nothing", () => {
  const p = page();
  openPicker(p);
  assert.equal(p.api.pickerVisible(), true);
  p.api.closePicker();
  assert.ok(p.doc.getElementById("picker"), "closePicker hides the picker in place: the element outlives the dialog");
  assert.equal(p.api.pickerVisible(), false);
  p.api.onMsg({ type: "nextTab" });
  assert.deepEqual(p.H.switched, [[API, true]], "the pair steps past the hidden picker");
});

test("the Token usage panel's own close returns to the settings card, which still holds the pair; the card's close frees it", () => {
  const p = page();
  p.gear.openSettings(); p.gear.openTokenUsage();
  assert.equal(p.doc.getElementById("rsettings")?.hidden, true, "the card hides under the panel (gear.js's opener)");
  pressPair(p.api);
  assert.deepEqual(p.H.switched, [], "the panel is up");
  p.gear.closeTokenUsage();
  pressPair(p.api);
  assert.deepEqual(p.H.switched, [], "back on the card");
  p.gear.closeSettings();
  p.api.onMsg({ type: "nextTab" });
  assert.deepEqual(p.H.switched, [[API, true]]);
});

test("the pair switches past both comment popovers alike, the thread and the new-comment box", () => {
  // a switch closes either popover (setActive: a popover belongs to its session's view) and its draft persists
  const cases: Array<[string, StateKey, unknown]> = [
    ["an open comment thread", "openCommentKey", { sid: WEB, tid: "t1" }],
    ["the new-comment box", "pendingCommentAnchor", { sid: WEB, uuid: "u1", exact: "the notes list page" }],
  ];
  for (const [name, key, value] of cases) {
    const p = page();
    mount(p, "cmt-pop", "cmt-pop");
    p.api.set(key, value);
    p.api.onMsg({ type: "nextTab" });
    p.api.onMsg({ type: "nextTab", gesture: true });
    assert.deepEqual(p.H.switched, [[API, true], [TESTS, true]], name + ": the pair steps, from VS Code and from the shell");
  }
});

test("the snapshot view's Escape still yields to an open comment thread", () => {
  const p = page();
  p.api.set("openCommentKey", { sid: WEB, tid: "t1" });
  assert.equal(p.api.escapeLayerOpen(), true);
});

/** A bare ArrowRight on the chat window, through the page's own handler. */
type KeyEv = { key: string; target: FakeEl; defaultPrevented: boolean; altKey: boolean; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean; preventDefault(): void };
function arrowRight(p: Page): void {
  const e: KeyEv = { key: "ArrowRight", target: p.doc.body, defaultPrevented: false, altKey: false, ctrlKey: false, metaKey: false, shiftKey: false,
                     preventDefault() { e.defaultPrevented = true; } };
  for (const f of p.win.keydown) f(e);
}

test("the bare arrows step the strip again once the picker is closed", () => {
  const p = page();
  assert.equal(p.win.keydown.length, 1, "the handler registered itself");
  arrowRight(p);
  assert.deepEqual(p.H.switched.map(([id]) => id), [API], "nothing open: the arrow steps");
  openPicker(p); arrowRight(p);
  assert.deepEqual(p.H.switched.map(([id]) => id), [API], "the open picker owns the arrows");
  p.api.closePicker(); arrowRight(p);
  assert.deepEqual(p.H.switched.map(([id]) => id), [API, TESTS], "closed: the arrow steps again");
});

test("typing from anywhere drops into the box again once the picker is closed", () => {
  const p = page();
  const target = () => p.api.typeTarget({ target: p.doc.body });
  assert.equal(target(), p.composer, "nothing open: the box");
  openPicker(p);
  assert.equal(target(), null, "the open picker owns the keys");
  p.api.closePicker();
  assert.equal(target(), p.composer, "closed: the box again");
});

test("typing from anywhere stands down under the Token usage panel as under the settings card", () => {
  const p = page();
  const target = () => p.api.typeTarget({ target: p.doc.body });
  p.gear.openSettings();
  assert.equal(target(), null, "the settings card");
  p.gear.openTokenUsage();
  assert.equal(target(), null, "the Token usage panel, the card hidden under it: a letter typed there must not land in the draft");
  p.gear.closeSettings();
  assert.equal(target(), p.composer, "both closed: the box");
});

test("the page opens and closes each layer the way this file's page does", () => {
  // the picker: built once, shown by display; closePicker (run for real above) only hides it
  const open = slice(RENDER, "function openPicker(pick = false, prompt?: string, allowNew = false) {", "\nfunction ", "openPicker");
  assert.match(open, /let overlay = document\.getElementById\("picker"\);\n\s*if \(!overlay\) \{\n\s*overlay = el\("div", "picker-overlay"\); overlay\.id = "picker";/);
  assert.match(open, /\n    document\.body\.appendChild\(overlay\);\n/, "appended once, inside the build");
  assert.match(open, /\n  overlay\.style\.display = "flex";\n/, "shown by display on every open");
  // the move and fork prompts wear the confirm chrome and close by removal (the break-out dialog's close is the third)
  assert.match(RENDER, /const overlay = el\("div", "picker-overlay confirm-overlay"\); overlay\.id = "move-prompt";/);
  assert.match(RENDER, /const overlay = el\("div", "picker-overlay confirm-overlay"\); overlay\.id = "fork-prompt";/);
  assert.equal(RENDER.match(/const close = \(\) => \{ overlay\.remove\(\); document\.removeEventListener\("keydown", onKey, true\); \};/g)?.length, 3);
  // the menus and the citation preview: the page's state holds each, and its close clears it
  assert.match(RENDER, /function onTabMenuClosed\(\) \{\n\s*ctxMenuEl = null;/);
  assert.match(RENDER, /metaMenuEl\?\.remove\(\);\n\s*metaMenuEl = null;/);
  assert.match(RENDER, /if \(citePreviewEl\) \{ citePreviewEl\.remove\(\); citePreviewEl = null; \}/);
  assert.match(RENDER, /const pop = el\("div", "cite-preview"\);/);
  // gear.js builds both panels hidden, and the card's opener shows it (its close and the panel's lines run above)
  assert.match(GEAR, /'<div id=rsettings hidden>/);
  assert.match(GEAR, /'<div id=ranalytics-back hidden>/);
  assert.match(GEAR, /\n    p\.hidden = false; feedFull\(true\); setModalCls\(true\);/);
  // the full-pane surfaces: each open mounts its id on the body, each close removes it
  for (const [file, id] of [["file-view.ts", "romp-fileview"], ["file-browse.ts", "romp-filebrowse"], ["preview.ts", "romp-lightbox"]]) {
    const src = read("ui", "webview", file);
    assert.ok(src.includes('wrap.id = "' + id + '";'), file + " names its backdrop " + id);
    assert.ok(src.includes('document.getElementById("' + id + '")?.remove();'), file + " closes by removal");
    assert.ok(src.includes("document.body.appendChild(wrap);"), file + " mounts on the body");
  }
});
