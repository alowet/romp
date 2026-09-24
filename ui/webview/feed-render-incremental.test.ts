// The feed pane's per-card update gate, RUN: feed.ts booted under a DOM stand-in, fed synthetic frames through
// the window message it listens on, and watched for what each render REBUILT. The invariant these frames pin:
// a card repaints when the kernel sent it (a new object), when a board-level input it reads changed (the
// key), or when a gesture touched it; its column and order are re-applied on every render regardless; and
// the 15 s live pass moves its ages and durations on the kernel's clock, writing only the labels whose text
// changed. Two of the assertions are the regressions the paint key this gate replaced would
// fail: a re-dispatch of the same objects across a 15 s boundary rebuilds nothing (the key carried a
// fifteen-second clock term, so the first frame of every window repainted every card), and one session's
// `working` change repaints that session's cards alone (the key carried an epoch every status-set change
// bumped, so every card repainted). The last cases pin what the gate leaves to the animations themselves,
// now that no per-render className rewrite strips their classes: a fly ends on its own event or a backstop,
// skips a folded column's zero rect at either end, and one fly owns a card at a time; a reveal pulse ends;
// a session header's name nodes are minted only when what they show changes.
//
// The stand-in is the tree of plain objects the Outline pane's live-clock test boots its bundle under, grown to
// what feed.ts's boot and render paths touch: a small selector engine (descendant chains, classes, ids, attribute presence and
// equality; every pseudo-class, :hover included, matches nothing), insertBefore/sibling walks, dataset-backed
// data-* attributes, a style object with custom properties, EventTarget elements, and counters for the
// writes the gate is about (replaceChildren on a card's name node, textContent sets, getBoundingClientRect
// reads, scrollTop writes). gear.js's initGear returns at once when #rsettings already exists, so the
// settings modal never mounts. Synthetic only: the notes-api demo world, placeholder sids, hostname TESTHOST.
import { test, mock, after } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { prefixInbound } from "./federation";   // the inbound transform a remote host's frames and replies pass through (no DOM needed)
import * as CS from "./card-sections";   // the section registry the feed registers its cards in (the same module instance feed.ts imports); a namespace import, so a base
//                                           without the raw view still builds and its red is the observation's absence, said in words, not a missing export

// ── a DOM stand-in ─────────────────────────────────────────────────────────────────────────────────
class Style {
  [key: string]: any;
  private props = new Map<string, string>();
  setProperty(k: string, v: string): void { this.props.set(k, v); }
  removeProperty(k: string): void { this.props.delete(k); }
  getPropertyValue(k: string): string { return this.props.get(k) ?? ""; }
}
class Txt {
  nodeType = 3;
  parentNode: El | null = null;
  constructor(public textContent: string) {}
  get nextSibling(): El | Txt | null { return sib(this, 1); }
  remove(): void { this.parentNode?.removeChild(this); }
}
function sib(n: El | Txt, d: number): El | Txt | null {
  const p = n.parentNode; if (!p) return null;
  const i = p.childNodes.indexOf(n); return p.childNodes[i + d] ?? null;
}
const camel = (s: string) => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
type Compound = { tag: string | null; id: string | null; classes: string[]; attrs: { name: string; value: string | null }[]; pseudo: boolean };
function parseCompound(s: string): Compound {
  const c: Compound = { tag: null, id: null, classes: [], attrs: [], pseudo: false };
  const m = /^([a-zA-Z][\w-]*)?(.*)$/.exec(s)!;
  c.tag = m[1] ? m[1].toUpperCase() : null;
  const re = /\.([\w-]+)|#([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]|:[\w-]+(?:\([^)]*\))?/g;
  let t: RegExpExecArray | null;
  while ((t = re.exec(m[2]))) {
    if (t[1]) c.classes.push(t[1]);
    else if (t[2]) c.id = t[2];
    else if (t[3]) c.attrs.push({ name: t[3], value: t[4] ?? null });
    else c.pseudo = true;
  }
  return c;
}
class El extends EventTarget {
  nodeType = 1;
  id = ""; title = ""; hidden = false; value = ""; type = ""; checked = false; disabled = false;
  offsetWidth = 0; offsetHeight = 0; clientWidth = 800; clientHeight = 600; isContentEditable = false;
  onclick: ((ev: any) => void) | null = null;
  parentNode: El | null = null;
  childNodes: Array<El | Txt> = [];
  dataset: Record<string, string | undefined> = {};
  style = new Style();
  rc = 0;                                   // replaceChildren calls (the name nodes' rebuild)
  tc = 0;                                   // textContent sets
  ac = 0;                                   // setAttribute calls (a same-value write still queues a mutation record in a browser)
  private attrs = new Map<string, string>();
  private classes = new Set<string>();
  private _html = "";
  private _scrollTop = 0;
  classList = {
    add: (...c: string[]) => { for (const x of c) this.classes.add(x); },
    remove: (...c: string[]) => { for (const x of c) this.classes.delete(x); },
    toggle: (c: string, force?: boolean) => {
      const on = force === undefined ? !this.classes.has(c) : force;
      if (on) this.classes.add(c); else this.classes.delete(c);
      return on;
    },
    contains: (c: string) => this.classes.has(c),
  };
  constructor(public tagName: string) { super(); this.tagName = tagName.toUpperCase(); }
  get className(): string { return [...this.classes].join(" "); }
  set className(v: string) { this.classes = new Set(v.split(/\s+/).filter(Boolean)); }
  get textContent(): string { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v: string | null) { this.tc++; this.detachAll(); if (v !== null && v !== "") this.appendChild(new Txt(String(v))); }
  get innerHTML(): string { return this._html; }
  set innerHTML(v: string) { this.detachAll(); this._html = v; }
  get scrollTop(): number { return this._scrollTop; }
  set scrollTop(v: number) { scrollWrites.push(v); this._scrollTop = v; }
  get children(): El[] { return this.childNodes.filter((c): c is El => c instanceof El); }
  get firstChild(): El | Txt | null { return this.childNodes[0] ?? null; }
  get nextSibling(): El | Txt | null { return sib(this, 1); }
  get parentElement(): El | null { return this.parentNode; }
  get previousElementSibling(): El | null { for (let n = sib(this, -1); n; n = sib(n, -1)) if (n instanceof El) return n; return null; }
  get nextElementSibling(): El | null { for (let n = sib(this, 1); n; n = sib(n, 1)) if (n instanceof El) return n; return null; }
  get isConnected(): boolean { return this === body || body.contains(this); }
  private detachAll(): void { for (const c of this.childNodes) c.parentNode = null; this.childNodes = []; }
  private adopt(c: El | Txt | string): El | Txt { const n = typeof c === "string" ? new Txt(c) : c; n.parentNode?.removeChild(n); n.parentNode = this; return n; }
  appendChild<T extends El | Txt>(c: T): T { this.childNodes.push(this.adopt(c) as T); return c; }
  append(...cs: Array<El | Txt | string>): void { for (const c of cs) this.childNodes.push(this.adopt(c)); }
  prepend(...cs: Array<El | Txt | string>): void { this.childNodes.unshift(...cs.map((c) => this.adopt(c))); }
  replaceChildren(...cs: Array<El | Txt | string>): void { this.rc++; this.detachAll(); this.append(...cs); }
  insertBefore<T extends El | Txt>(node: T, ref: El | Txt | null): T {
    const n = this.adopt(node);
    const i = ref ? this.childNodes.indexOf(ref) : -1;
    if (i < 0) this.childNodes.push(n); else this.childNodes.splice(i, 0, n);
    return node;
  }
  removeChild(c: El | Txt): void { const i = this.childNodes.indexOf(c); if (i >= 0) { this.childNodes.splice(i, 1); c.parentNode = null; } }
  remove(): void { this.parentNode?.removeChild(this); }
  after(...cs: Array<El | Txt | string>): void { const p = this.parentNode; if (!p) return; const ref = sib(this, 1); for (const c of cs) p.insertBefore(typeof c === "string" ? new Txt(c) : c, ref); }
  before(...cs: Array<El | Txt | string>): void { const p = this.parentNode; if (!p) return; for (const c of cs) p.insertBefore(typeof c === "string" ? new Txt(c) : c, this); }
  replaceWith(c: El | Txt): void { const p = this.parentNode; if (!p) return; p.insertBefore(c, this); this.remove(); }
  get firstElementChild(): El | null { return this.children[0] ?? null; }
  get lastElementChild(): El | null { const c = this.children; return c[c.length - 1] ?? null; }
  get lastChild(): El | Txt | null { return this.childNodes[this.childNodes.length - 1] ?? null; }
  get childElementCount(): number { return this.children.length; }
  contains(x: El | Txt | null): boolean { for (let n: El | Txt | null = x; n; n = n.parentNode) if (n === this) return true; return false; }
  setAttribute(k: string, v: string): void { this.ac++; this.attrs.set(k, String(v)); if (k.startsWith("data-")) this.dataset[camel(k.slice(5))] = String(v); if (k === "id") this.id = v; }
  getAttribute(k: string): string | null { return this.attrs.get(k) ?? (k.startsWith("data-") ? this.dataset[camel(k.slice(5))] ?? null : k === "title" && this.title ? this.title : null); }
  hasAttribute(k: string): boolean { return this.getAttribute(k) !== null; }
  removeAttribute(k: string): void { this.attrs.delete(k); if (k === "title") this.title = ""; }
  getBoundingClientRect() {
    // a rendered element gets a rect from its place: a column's cards stack 100 px apart and each column sits
    // at its own left, so a card that changed column or slot has a different rect and one that did not has
    // the same; anything hidden (display:none on it or an ancestor) or detached is a zero rect, as in a browser
    rectReads++;
    for (let n: El | null = this; n; n = n.parentNode) if (n.style.display === "none") return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 };
    if (!this.isConnected) return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 };
    const p = this.parentNode!;
    const top = p.children.indexOf(this) * 100, left = p.id.length * 10;
    return { left, top, right: left + 300, bottom: top + 90, width: 300, height: 90 };
  }
  scrollIntoView(): void {}
  focus(): void {}
  blur(): void {}
  matchesCompound(c: Compound): boolean {
    if (c.pseudo) return false;
    if (c.tag && c.tag !== this.tagName) return false;
    if (c.id && c.id !== this.id) return false;
    for (const k of c.classes) if (!this.classes.has(k)) return false;
    for (const a of c.attrs) { const v = this.getAttribute(a.name); if (v === null) return false; if (a.value !== null && v !== a.value) return false; }
    return true;
  }
  matches(sel: string): boolean {
    return sel.split(",").some((one) => {
      const parts = one.trim().split(/\s+/).map(parseCompound);
      if (!this.matchesCompound(parts[parts.length - 1])) return false;
      let anc: El | null = this.parentNode;
      for (let i = parts.length - 2; i >= 0; i--) {
        while (anc && !anc.matchesCompound(parts[i])) anc = anc.parentNode;
        if (!anc) return false;
        anc = anc.parentNode;
      }
      return true;
    });
  }
  closest(sel: string): El | null { for (let n: El | null = this; n; n = n.parentNode) if (n.matches(sel)) return n; return null; }
  querySelectorAll(sel: string): El[] { return [...this.walk()].filter((e) => e.matches(sel)); }
  querySelector(sel: string): El | null { for (const e of this.walk()) if (e.matches(sel)) return e; return null; }
  *walk(): Generator<El> { for (const c of this.childNodes) if (c instanceof El) { yield c; yield* c.walk(); } }
  byId(id: string): El | null { for (const e of this.walk()) if (e.id === id) return e; return null; }
}
let rectReads = 0;
const scrollWrites: number[] = [];
const posted: any[] = [];
const body = new El("body");
const head = new El("div"); head.id = "feed-head";
const list = new El("div"); list.id = "feed-list";
const foot = new El("div"); foot.id = "feed-foot";
const gearGuard = new El("div"); gearGuard.id = "rsettings";   // initGear's idempotence check: present → the modal never mounts
body.append(head, list, foot, gearGuard);
const stores = { local: new Map<string, string>(), session: new Map<string, string>() };
const storage = (m: Map<string, string>) => ({
  getItem: (k: string) => (m.has(k) ? m.get(k)! : null),
  setItem: (k: string, v: string) => { m.set(k, String(v)); },
  removeItem: (k: string) => { m.delete(k); },
});
const win: any = new EventTarget();
win.parent = win; win.top = win;
win.location = { hash: "", search: "", protocol: "http:" };
win.innerWidth = 1200; win.innerHeight = 800;
win.setTimeout = (...a: Parameters<typeof setTimeout>) => setTimeout(...a);
win.clearTimeout = (t: ReturnType<typeof setTimeout>) => clearTimeout(t);
win.setInterval = (...a: Parameters<typeof setInterval>) => setInterval(...a);
win.requestAnimationFrame = (cb: () => void) => setTimeout(cb, 0);
win.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
win.getComputedStyle = () => ({ flexDirection: "row", order: "0" });
win.postMessage = () => {};
win.acquireVsCodeApi = () => ({ postMessage: (m: any) => posted.push(m) });
(globalThis as any).window = win;
(globalThis as any).requestAnimationFrame = win.requestAnimationFrame;
(globalThis as any).getComputedStyle = win.getComputedStyle;
(globalThis as any).MouseEvent = class MouseEvent extends Event { clientX = 0; clientY = 0; };
// the paint gate's second measure: render() observes #feed-list once; a test drives the callback by hand
const observers: { cb: (entries: { isIntersecting: boolean }[]) => void }[] = [];
(globalThis as any).IntersectionObserver = class { cb: any; constructor(cb: any) { this.cb = cb; observers.push(this); } observe() {} disconnect() {} };
const doc: any = new EventTarget();
Object.assign(doc, {
  body, head: new El("head"), documentElement: new El("html"), hidden: false, activeElement: body,
  createElement: (tag: string) => new El(tag),
  createTextNode: (s: string) => new Txt(s),
  getElementById: (id: string) => body.byId(id),
  querySelectorAll: (sel: string) => body.querySelectorAll(sel),
  querySelector: (sel: string) => body.querySelector(sel),
  contains: (x: El) => body.contains(x),
});
(globalThis as any).document = doc;
(globalThis as any).localStorage = storage(stores.local);
(globalThis as any).sessionStorage = storage(stores.session);

// ── the world: three sessions of a notes-api project, three cards ─────────────────────────────────
const T0 = 1781100000;                      // the browser clock at boot
const K0 = T0 - 300;                        // the kernel clock, five minutes behind — the age label follows it
const WEB = "11111111-2222-3333-4444-555555555555", API = "11111111-2222-3333-4444-666666666666", TESTS = "11111111-2222-3333-4444-777777777777";
const node = (id: string, text: string, who: string, whoSid: string, children: string[] = []) =>
  ({ id, kind: "ask", text, who, whoSid, whoColor: null, status: "open", t: K0 - 240, last: K0 - 240, children });
const cardOf = (itemId: string, sid: string, name: string, bg: string, text: string, column: string, extra: Record<string, unknown> = {}) => ({
  itemId, sid, name, color: { bg, fg: "#ffffff" }, text, t: K0 - 240, trgb: [96, 128, 160], live: true, turnId: "turn-" + itemId, column,
  summary: null, blockSummary: null, tree: [node(itemId, text, name, sid)], ...extra,
});
const g1 = cardOf("g1", WEB, "web", "#3366cc", "Wire the notes-api health route", "working",
  { tree: [node("g1", "Wire the notes-api health route", "web", WEB, ["g1a"]), node("g1a", "Add the /health handler", "web", WEB)] });
const g2 = cardOf("g2", API, "api", "#cc6633", "Write the notes-api README", "working");
const g3 = cardOf("g3", TESTS, "tests", "#33cc66", "Run the notes-api test suite", "working",
  { awaiting: { why: "", kind: "agents", count: 2, since: K0 - 600 } });   // a wait ten minutes old: its duration must move without a frame
// the frame shape: the kernel's `now` and federation's `nowAt` (when the frame landed, the pane's clock anchor),
// per-card `trgb`, the status sets, the session order and list
const frame = (asks: any[], over: Record<string, unknown> = {}) => ({
  type: "feed", now: K0, nowAt: T0 * 1000, buildId: 1, asks,
  working: [], awaiting: [], stateUnknown: [], order: [WEB, API, TESTS], selfHost: "TESTHOST",
  sessions: [{ sid: WEB, name: "web", color: g1.color }, { sid: API, name: "api", color: g2.color }, { sid: TESTS, name: "tests", color: g3.color }],
  bgServices: {}, ...over,
});
const listenerErrors: Error[] = [];
process.on("uncaughtException", (e) => { listenerErrors.push(e); });
const settle = () => new Promise<void>((r) => setImmediate(r));   // let a deferred listener exception land before the assertions
const dispatch = async (f: any) => {
  win.dispatchEvent(new MessageEvent("message", { data: f }));
  await settle();
  if (listenerErrors.length) { const es = listenerErrors.splice(0); throw new Error("a listener threw: " + es.map((e) => e.stack || e.message).join("\n---\n")); }
};
after(() => { assert.deepEqual(listenerErrors.map((e) => e.stack || e.message), [], "no listener threw outside a dispatch (a gesture handler, a timer)"); });
const card = (id: string): any => body.querySelector(`[data-key="a:${id}"]`);
const colOf = (id: string) => card(id)?.parentNode?.id;
const nameRebuilds = () => ({ g1: card("g1")._name.rc, g2: card("g2")._name.rc, g3: card("g3")._name.rc });
const ev = { stopPropagation() {}, preventDefault() {} };

test("frame A: three cards are built once each, in the Working column", async () => {
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  await import("./feed");                   // module load: gear (a no-op here), listeners, the 15 s live pass
  assert.equal(posted.filter((m) => m.type === "ready").length, 1, "the ready handshake");
  await dispatch(frame([g1, g2, g3]));
  assert.deepEqual(nameRebuilds(), { g1: 1, g2: 1, g3: 1 }, "each name node was built exactly once");
  assert.deepEqual({ g1: colOf("g1"), g2: colOf("g2"), g3: colOf("g3") }, { g1: "col-asks-list", g2: "col-asks-list", g3: "col-asks-list" });
  assert.equal(card("g1")._time.textContent, "4m ago", "on the kernel's clock (the browser clock is five minutes ahead)");
  assert.equal(card("g3")._awaitWhy.textContent, "Awaiting agents · 10m", "the awaiting box, with the wait's duration on the kernel's clock");
  assert.equal(card("g3")._awaitWhy.querySelector(".fask-dur")?.dataset.ageFmt, "dur", "…as a stamped element the live pass can reach");
  // open card 1's Sub-goals section (a gesture): the section state must survive the renders below untouched
  card("g1")._subBtn.onclick(ev);
  assert.equal(card("g1")._subBtn.getAttribute("aria-pressed"), "true");
  assert.equal(card("g1")._checklist.children.length, 1, "one sub-goal row");
});

test("frame B: only the card whose object changed repaints; it moves column; the other cards keep their DOM and their open section", async () => {
  const row = card("g1")._checklist.children[0];
  const readsBefore = rectReads;
  list.scrollTop = 120; scrollWrites.length = 0;
  const g2done = { ...g2, column: "completed" };
  await dispatch(frame([g1, g2done, g3]));
  assert.deepEqual(nameRebuilds(), { g1: 1, g2: 2, g3: 1 }, "exactly one name rebuild: the re-sent card");
  assert.equal(colOf("g2"), "col-completed-list", "the changed card moved to Completed");
  assert.equal(colOf("g1"), "col-asks-list"); assert.equal(colOf("g3"), "col-asks-list");
  assert.equal(body.byId("col-asks-count")!.textContent, "2"); assert.equal(body.byId("col-completed-count")!.textContent, "1");
  assert.equal(card("g1")._subBtn.getAttribute("aria-pressed"), "true", "the open section stayed open");
  assert.equal(card("g1")._checklist.children[0], row, "…and its rows are the same nodes, not a rebuild");
  assert.equal(scrollWrites[scrollWrites.length - 1], 120, "the scroll position is restored");
  assert.ok(rectReads > readsBefore, "a column changed, so the FLIP passes read rects");
  assert.ok(card("g2").classList.contains("fitem-flying"), "the card that crossed columns flies in the back layer");
  assert.match(card("g2").style.transform, /^translate\(/, "…inverted to its old spot first");
});

test("frame C: the same frame re-dispatched (a federation re-emit) rebuilds nothing and reads no rects", async () => {
  // frame B emptied api's run in Working, so its session header left as a ghost (re-keyed x:N until its exit
  // animation ends, or the 600 ms backstop) and g2 flew to Completed; 700 ms later both backstops have fired:
  // no transition ends under the stand-in, so the fly's own backstop is what takes the card out of the back
  // layer (before it, a card whose transitionend never came kept pointer-events:none until its next repaint)
  // (two ticks: a timer created inside a mock tick is stamped with the tick's END time, so one 700 ms tick
  // would run the nested animation frame AFTER the 650 ms backstop — the reverse of a browser's order)
  mock.timers.tick(20);
  assert.equal(card("g2").style.transform, "translate(0, 0)", "the frame after the invert releases the offset");
  mock.timers.tick(680);
  assert.equal(body.querySelectorAll(".sess-exit").length, 0, "the exited header is gone");
  assert.ok(!card("g2").classList.contains("fitem-flying"), "the fly ended by its backstop");
  assert.equal(card("g2").style.transform, "", "…and the card is back in normal flow");
  await dispatch(frame([g1, { ...g2, column: "completed" }, g3]));   // a fresh copy of g2 IS a new object: it repaints — that is the contract
  assert.deepEqual(nameRebuilds(), { g1: 1, g2: 3, g3: 1 });
  const readsBefore = rectReads;
  const tcBefore = { g1: card("g1")._title.tc, g2: card("g2")._title.tc, g3: card("g3")._title.tc };
  const same = frame([g1, card("g2")._it, g3]);              // now the very objects the cards were painted from
  await dispatch(same);
  await dispatch(same);
  assert.deepEqual(nameRebuilds(), { g1: 1, g2: 3, g3: 1 }, "zero rebuilds on identical objects under identical inputs");
  assert.deepEqual({ g1: card("g1")._title.tc, g2: card("g2")._title.tc, g3: card("g3")._title.tc }, tcBefore,
    "no title text was rewritten either");
  assert.equal(rectReads, readsBefore, "no card changed column or place: the FLIP passes read nothing");
});

test("…and across a 15 s boundary: the clock is not a paint input", async () => {
  // the key this gate replaced carried a fifteen-second term, so the first frame in every 15 s window
  // repainted every card. The live pass that fires inside this window moves the labels whose minute rolled
  // over (its own business, pinned below); it rebuilds no card.
  const before = nameRebuilds(), readsBefore = rectReads;
  const same = frame([g1, card("g2")._it, g3]);
  mock.timers.tick(16_000);
  await dispatch(same);
  assert.deepEqual(nameRebuilds(), before, "the same objects across a 15 s boundary: zero rebuilds");
  assert.equal(rectReads, readsBefore);
});

test("frame D: `working` naming card 1's session repaints card 1 (its dot) and leaves the other sessions' cards alone", async () => {
  // the key this gate replaced carried an epoch every status-set change bumped: every card repainted
  const g2now = card("g2")._it;
  await dispatch(frame([g1, g2now, g3], { working: ["web"] }));
  assert.deepEqual(nameRebuilds(), { g1: 2, g2: 3, g3: 1 }, "the key changed for web's card only");
  assert.ok(card("g1")._name.previousElementSibling?.classList.contains("fwork-dot"), "the working dot sits before the name");
  await dispatch(frame([g1, g2now, g3], { working: ["web"] }));
  assert.deepEqual(nameRebuilds(), { g1: 2, g2: 3, g3: 1 }, "…and the same inputs again change nothing");
});

test("column placement and the order walk are not gated: a changed session order moves the cards, and no card repaints", async () => {
  const same = frame([g1, card("g2")._it, g3], { working: ["web"] });
  await dispatch(same);                                          // settle on the objects the cards were painted from
  const before = nameRebuilds();
  const keys = () => body.byId("col-asks-list")!.children.map((c) => c.dataset.key).filter((k) => k && k.startsWith("a:"));
  assert.deepEqual(keys(), ["a:g1", "a:g3"], "web's run, then tests' — the kernel's session order");
  await dispatch(frame([g1, card("g2")._it, g3], { working: ["web"], order: [TESTS, API, WEB] }));
  assert.deepEqual(keys(), ["a:g3", "a:g1"], "the runs swapped places");
  assert.deepEqual(nameRebuilds(), before, "…and no card repainted: a card's column and slot are re-applied every render, outside the gate");
  await dispatch(same);
  assert.deepEqual(keys(), ["a:g1", "a:g3"]);
  assert.deepEqual(nameRebuilds(), before);
});

test("Revive latches on the click and re-arms on the kernel's reviveFailed for the revived session, its idle label restored and the reason toasted; a re-emit, another session's failure and an err for a different request leave the latch", async () => {
  // the kernel's parked-handoff card (build_feed): its sid IS the recipient the button revives (sid and blocked.toSid
  // are both the parked message's toId), so the kernel's reviveFailed, keyed by the revived id, names this card
  const p1 = cardOf("parked:m1", API, "api", "#cc6633", "Hand-off parked for api (offline)", "needs_input",
    { live: false, tree: [], blocked: { state: "parkedHandoff", toSid: API, toName: "api", what: "a handoff from web is parked: revive api to deliver it" } });
  await dispatch(frame([g1, card("g2")._it, g3, p1], { working: ["web"] }));
  const revive = card("parked:m1")._revive;
  assert.equal(revive.style.display, ""); assert.equal(revive.disabled, false); assert.equal(revive.textContent, "Revive api");
  const sent = posted.length;
  revive.onclick(ev);
  assert.deepEqual(posted.slice(sent).filter((m) => m.type === "reviveSession"), [{ type: "reviveSession", id: API }]);
  assert.equal(revive.disabled, true); assert.equal(revive.textContent, "Reviving…");
  await dispatch(frame([g1, card("g2")._it, g3, p1], { working: ["web"] }));   // the same objects again: nothing decided
  assert.equal(revive.disabled, true, "a re-emit is not a deciding event");
  const toastBefore = body.querySelector(".feed-toast")?.textContent ?? null;
  await dispatch({ type: "reviveFailed", id: WEB, name: "web", text: "the SDK backend could not resume it" });
  assert.equal(revive.disabled, true, "another session's revive failing is not this card's event");
  assert.equal(body.querySelector(".feed-toast")?.textContent ?? null, toastBefore, "…and nothing to say about it here");
  await dispatch({ type: "err", sid: API, op: "sendMessage", title: "That message was not delivered", text: "Nothing was sent." });
  assert.equal(revive.disabled, true, "a refusal of a DIFFERENT request on the same session is not this button's reply");
  await dispatch({ type: "reviveFailed", id: API, name: "api", text: "the SDK backend could not resume it (see the kernel log)" });
  assert.equal(revive.disabled, false, "the kernel's reply to the revive this page asked for re-arms it");
  assert.equal(revive.textContent, "Revive api", "…with the label it wore before the click");
  assert.equal(body.querySelector(".feed-toast")?.textContent, "Couldn't revive api: the SDK backend could not resume it (see the kernel log)",
    "…and says why here, where the button is (the chat pane shows the same failure in the session's own pane)");
  await dispatch(frame([g1, card("g2")._it, g3], { working: ["web"] }));   // delivered or dismissed elsewhere: the parked card leaves
  assert.ok(!card("parked:m1"));
});

test("a store gesture's session account re-arms nothing and brings nothing back: a latched Retry and Revive stay latched across it (so a second click posts once), a cleared card stays hidden and its Undo entry stands (the fourth review of PR 1967, the manager's ruling)", async () => {
  const sent0 = posted.length;                                            // this test's posts leave the shared list at its end: the tests after it count posts over the whole run
  const blockedG1 = { ...g1, blocked: { state: "apiError", what: "the API returned 529", status: 529 } };
  const p1 = cardOf("parked:m1", API, "api", "#cc6633", "Hand-off parked for api (offline)", "needs_input",
    { live: false, tree: [], blocked: { state: "parkedHandoff", toSid: API, toName: "api", what: "a handoff from web is parked: revive api to deliver it" } });
  await dispatch(frame([blockedG1, card("g2")._it, card("g3")._it, p1]));   // web is NOT working: its Retry shows; api's parked card carries Revive
  const c3 = card("g3");
  c3._clr.onclick(ev);                                                      // Clear FIRST (the sixth low: an assertion over a board with nothing cleared could not fail)
  assert.ok(c3.classList.contains("dismissing"), "the cleared card hides"); assert.ok(body.byId("feed-undoclear"), "and its Undo entry stands");
  const retry = card("g1")._apiRetry, revive = card("parked:m1")._revive;
  const sent = posted.length;
  retry.onclick(ev); revive.onclick(ev);
  assert.equal(posted.slice(sent).filter((m) => m.type === "apiRetry").length, 1); assert.equal(posted.slice(sent).filter((m) => m.type === "reviveSession").length, 1);
  assert.equal(retry.disabled, true); assert.equal(revive.disabled, true);
  // the store gestures' per-session accounts: a landed clear's (no ids), for each latched button's session; op rides on each
  await dispatch({ type: "err", sid: WEB, op: "askClear", itemId: "", itemIds: [], title: "That clear did not fully land for web", text: "The card is off the board; the session's own record of it could not be written." });
  await dispatch({ type: "err", sid: API, op: "askClearMany", itemId: "", itemIds: [], title: "That clear did not fully land for api", text: "The cards are off the board; the session's own record of them could not be written." });
  assert.equal(retry.disabled, true, "a store gesture's account is not the Retry's reply: it stays latched (before: re-armed on the session, and a second click posted twice)");
  assert.equal(revive.disabled, true, "nor the Revive's");
  assert.equal(posted.length - sent, 2, "one post each: the buttons stay disabled, so a second click posts nothing");
  assert.ok(c3.classList.contains("dismissing"), "the cleared card stays hidden: the account names no card"); assert.ok(body.byId("feed-undoclear"), "and its Undo entry stands");
  body.byId("feed-undoclear")!.onclick!(ev);                                // the entry is still there to undo
  assert.ok(!c3.classList.contains("dismissing"), "Undo brings the cleared card back from the entry the account left alone");
  mock.timers.tick(200);
  await dispatch({ type: "retryRefused", sid: WEB, text: "Couldn't retry: the session isn't connected right now." });   // the replies to THOSE requests release them
  await dispatch({ type: "reviveFailed", id: API, name: "api", text: "the SDK backend could not resume it" });
  assert.equal(retry.disabled, false); assert.equal(revive.disabled, false);
  await dispatch(frame([g1, card("g2")._it, card("g3")._it], { working: ["web"] }));   // the board as the tests around this one expect it
  assert.ok(!card("parked:m1"));
  posted.splice(sent0);
});

test("a reorder whose owed cards did not come back names them: an empty entry above the last clear's, so the next Undo restores nothing optimistically (the kernel's is the owed card) and the one after is the last clear's (the sixth executed review of PR 1967)", async () => {
  const sent0 = posted.length;
  const c3 = card("g3");
  c3._clr.onclick(ev);                                                      // Clear g3: the stack holds its entry
  body.byId("feed-undoclear")!.onclick!(ev);                                // Undo: g3 back optimistically, the kernel asked
  assert.ok(!c3.classList.contains("dismissing")); assert.equal(posted.slice(sent0).filter((m) => m.type === "undoClear").length, 1);
  mock.timers.tick(200);
  // the kernel went to an owed card first and its store refused: the reorder frame names g3 as not restored and the owed id
  await dispatch({ type: "err", ok: true, op: "undoClear", itemId: "g3", itemIds: ["g3"], owedIds: [API + ":g9"], title: "Undo went to earlier cards first",
                   text: "Once that session's goals file can be read and written again, one Undo brings them back and the next the last clear." });
  mock.timers.tick(700);
  assert.ok(!card("g3"), "the last clear's card is off the board again");
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev);                                                        // the next Undo is the owed card's (the kernel's newest batch): the entry standing for it pops
  assert.ok(!card("g3"), "nothing restored optimistically: the last clear's entry sits below it");
  assert.ok(undo.classList.contains("undo-busy"), "the round-trip cue: the payload brings the owed card");
  undo.onclick!(ev);                                                        // the press after: the last clear's entry
  mock.timers.tick(700);
  assert.ok(card("g3"), "g3 back optimistically, matching the kernel's press");
  assert.equal(posted.slice(sent0).filter((m) => m.type === "undoClear").length, 3);
  await dispatch(frame([g1, card("g2")._it, card("g3")._it], { working: ["web"] }));   // the payload: the cue clears, the board as before
  mock.timers.tick(7000);
  posted.splice(sent0);
});

test("the bell: a click acknowledges at once and its optimistic state is a paint input, so that card alone repaints on the next frame; a refused toggle releases the latch and repaints that card alone", async () => {
  const before = nameRebuilds();
  const bell = card("g1")._bell;
  assert.equal(bell._bellOn, false);
  const sent = posted.length;
  bell.onclick(ev);
  assert.equal(bell._bellOn, true, "acknowledged before the round-trip");
  assert.deepEqual(posted.slice(sent).filter((m) => m.type === "cardNotify"), [{ type: "cardNotify", itemId: "g1", sid: WEB, value: true }]);
  await dispatch(frame([g1, card("g2")._it, g3], { working: ["web"] }));   // the same objects: the latch rides the key
  assert.equal(bell._bellOn, true, "the payload does not carry it yet; the latch holds");
  assert.deepEqual(nameRebuilds(), { ...before, g1: before.g1 + 1 }, "web's card repainted under its new key, the others did not");
  await dispatch({ type: "settingRefused", gesture: "bell", itemId: "g1", sid: WEB, text: "the settings store could not be read" });
  assert.equal(bell._bellOn, false, "the refusal ends the optimistic state: the bell shows what the payload holds");
  assert.deepEqual(nameRebuilds(), { ...before, g1: before.g1 + 2 }, "…by repainting that card, and no other");
});

test("the grouped pref is a paint input through feedPrefs: grouping off repaints every card once (the name row shows, the headers leave), and the same inputs again repaint nothing", async () => {
  const before = nameRebuilds();
  const nameRow = (id: string) => card(id)._name.parentNode.style.display;
  const heads = () => body.querySelectorAll(".feed-sess-head").filter((h) => !h.classList.contains("sess-exit")).length;
  assert.equal(nameRow("g1"), "none", "grouped: the session header carries the name"); assert.ok(heads() > 0);
  const setPrefs = (v: string) => { stores.local.set("romp:settings", v); win.dispatchEvent(Object.assign(new Event("storage"), { key: "romp:settings", newValue: v })); };
  setPrefs(JSON.stringify({ grouped: false }));                  // the gear in another pane
  assert.deepEqual(nameRebuilds(), { g1: before.g1 + 1, g2: before.g2 + 1, g3: before.g3 + 1 }, "every card reads the pref: each repainted once");
  assert.deepEqual([nameRow("g1"), nameRow("g2"), nameRow("g3")], ["", "", ""], "each card carries its own name again");
  assert.equal(heads(), 0, "no session headers");
  await dispatch(frame([g1, card("g2")._it, g3], { working: ["web"] }));
  assert.deepEqual(nameRebuilds(), { g1: before.g1 + 1, g2: before.g2 + 1, g3: before.g3 + 1 }, "the same inputs again: nothing repainted");
  setPrefs("{}");
  assert.equal(nameRow("g1"), "none");
  assert.deepEqual(nameRebuilds(), { g1: before.g1 + 2, g2: before.g2 + 2, g3: before.g3 + 2 });
});

test("a HELD-MAIL notice card (plans/notice-cards.md, action kinds): Approve posts noticeAction of kind quarantine with the stored body and the card's sid, latches, and re-arms on the kernel's refusal with the reason toasted", async () => {
  // the kernel's card for a message held from a DIRECTED peer (_held_mail_backfill): a notice under the RECIPIENT, key = the
  // message id, producer postal, two stored actions of the quarantine kind
  const held = { key: "m1", rev: 1, producer: "postal", body: "from TESTHOST:api to web, held because peer TESTHOST is DIRECTED\n\nthe README draft is ready for a look", attachment: null,
    actions: [{ label: "Approve", kind: "quarantine", body: { mid: "m1", verdict: "approve" } }, { label: "Deny", kind: "quarantine", body: { mid: "m1", verdict: "deny" } }],
    expiresAt: null, dismissOnAction: true };
  const q1 = cardOf("notice:" + WEB + ":m1:1", WEB, "web", "#3366cc", "New message from api", "needs_input", { live: true, tree: [], blocked: null, notice: held });
  await dispatch(frame([g1, card("g2")._it, g3, q1], { working: ["web"] }));
  const c = card("notice:" + WEB + ":m1:1");
  assert.ok(c, "the card is on the board"); assert.equal(colOf("notice:" + WEB + ":m1:1"), "col-needsInput-list", "a held message needs you");
  assert.equal(c._nProd.textContent, "via postal");
  assert.match(c._nBody.textContent, /held because peer TESTHOST is DIRECTED/); assert.match(c._nBody.textContent, /the README draft is ready for a look/, "the message text is the body");
  assert.equal(c._blocked.style.display, "none", "no block chip: the card's own actions carry the decision");
  const [approve, deny] = Array.from(c._nActions.querySelectorAll("button")) as any[];
  assert.deepEqual([approve.textContent, deny.textContent, approve.disabled, deny.disabled], ["Approve", "Deny", false, false]);
  const sent = posted.length;
  approve.onclick(ev);
  assert.deepEqual(posted.slice(sent).filter((m) => m.type === "noticeAction"),
    [{ type: "noticeAction", itemId: "notice:" + WEB + ":m1:1", sid: WEB, kind: "quarantine", body: { mid: "m1", verdict: "approve" } }],
    "the KIND rides the wire with the stored body, never a route; no input on an approve");
  assert.deepEqual([approve.disabled, approve.textContent, deny.disabled, deny.textContent], [true, "Approve…", true, "Deny"], "both latch on the click (one decision per message); the one clicked says what it is doing");
  assert.equal(body.byId("quar-dialog"), null, "an approve asks nothing");
  await dispatch({ type: "noticeActionDone", itemId: "notice:" + WEB + ":m1:1", ok: false, error: "postal bus unreachable" });
  assert.deepEqual([approve.disabled, approve.textContent, deny.disabled], [false, "Approve", false], "the kernel's answer for this card re-arms both");
  assert.match(body.querySelector(".feed-toast")?.textContent ?? "", /refused: postal bus unreachable/, "…and says why");
  approve.onclick(ev);
  await dispatch({ type: "noticeActionDone", itemId: "notice:" + WEB + ":m1:1", ok: true, error: "" });
  assert.equal(card("notice:" + WEB + ":m1:1"), null, "delivered: the dismissing card left at once");
  assert.deepEqual(((CS as any).sectionHostsRaw as ((id: string) => HTMLElement[]) | undefined)?.("notice:" + WEB + ":m1:1") ?? [], [],
    "…and left the section registry with it: the completed dismiss-in-flight clear unregisters the twins it removes (a contributor's note on PR 2141)");
});

test("the held-mail card's Deny asks for the optional note first, on the document body: without a note posts the bare verdict, with one posts input.note, and the backdrop closes with no decision", async () => {
  const held = { key: "m2", rev: 1, producer: "postal", body: "from TESTHOST:api to web, held because peer TESTHOST is DIRECTED\n\nplease bump the parser", attachment: null,
    actions: [{ label: "Approve", kind: "quarantine", body: { mid: "m2", verdict: "approve" } }, { label: "Deny", kind: "quarantine", body: { mid: "m2", verdict: "deny" } }],
    expiresAt: null, dismissOnAction: true };
  const q2 = cardOf("notice:" + WEB + ":m2:1", WEB, "web", "#3366cc", "New message from api", "needs_input", { live: true, tree: [], blocked: null, notice: held });
  await dispatch(frame([g1, card("g2")._it, g3, q2], { working: ["web"] }));
  const deny = card("notice:" + WEB + ":m2:1")._nActions.querySelectorAll("button")[1] as any;
  const acts = () => posted.filter((m) => m.type === "noticeAction" && m.itemId === "notice:" + WEB + ":m2:1");
  // the backdrop: no decision, the message stays held, the button never latched
  deny.onclick(ev);
  let dlg = body.byId("quar-dialog") as any;
  assert.ok(dlg, "the note prompt is on the document body, outside the re-rendered feed root");
  assert.equal(acts().length, 0, "nothing posted before the prompt answers"); assert.equal(deny.disabled, false, "Deny latches only on the decision");
  const btns = () => Array.from(dlg.querySelectorAll("button")).map((b: any) => b.textContent);
  assert.deepEqual(btns(), ["Deny & send note", "Deny without note"], "two choices, no Cancel (the user 2026-07-26)");
  dlg.onclick({ target: dlg });
  assert.equal(body.byId("quar-dialog"), null, "the backdrop closed it"); assert.equal(acts().length, 0, "…and decided nothing");
  // without a note: the bare verdict
  deny.onclick(ev); dlg = body.byId("quar-dialog");
  (dlg.querySelectorAll("button")[1] as any).onclick();
  assert.deepEqual(acts(), [{ type: "noticeAction", itemId: "notice:" + WEB + ":m2:1", sid: WEB, kind: "quarantine", body: { mid: "m2", verdict: "deny" } }], "no input member at all");
  assert.deepEqual([deny.disabled, deny.textContent, body.byId("quar-dialog")], [true, "Deny…", null], "latched on the decision, the prompt gone");
  await dispatch({ type: "noticeActionDone", itemId: "notice:" + WEB + ":m2:1", ok: false, error: "the recipient is no longer live" });
  assert.equal(deny.disabled, false, "re-armed on the refusal");
  // with a note: the one click-time input the kind takes
  deny.onclick(ev); dlg = body.byId("quar-dialog");
  (dlg.querySelector("textarea") as any).value = "  not now, ask after the release  ";
  (dlg.querySelectorAll("button")[0] as any).onclick();
  assert.deepEqual(acts()[1], { type: "noticeAction", itemId: "notice:" + WEB + ":m2:1", sid: WEB, kind: "quarantine", body: { mid: "m2", verdict: "deny" }, input: { note: "not now, ask after the release" } }, "the note rides as input, trimmed");
  await dispatch({ type: "noticeActionDone", itemId: "notice:" + WEB + ":m2:1", ok: true, error: "" });
  assert.equal(card("notice:" + WEB + ":m2:1"), null, "dropped: the card left");
});

test("a handoff recipient's working state is a paint input: the delegating card repaints and its delegation line appears when the recipient starts working; an idle session's card does not repaint", async () => {
  const handoff = { id: API + ":h1", kind: "handoff", text: "write the README section", who: "api", whoSid: API, whoColor: null, status: "open", t: K0 - 200, last: K0 - 200, children: [] };
  const g1h = { ...g1, tree: [...g1.tree, handoff] };
  await dispatch(frame([g1h, card("g2")._it, g3], { working: ["web"] }));
  assert.equal(card("g1")._delegations.style.display, "none", "api is idle: no delegation line");
  const before = nameRebuilds();
  await dispatch(frame([g1h, card("g2")._it, g3], { working: ["web", "api"] }));   // the same objects; api starts working
  assert.equal(card("g1")._delegations.children.length, 1);
  assert.equal(card("g1")._delegations.querySelector(".fask-delegation")!.textContent, "api");
  assert.deepEqual(nameRebuilds(), { g1: before.g1 + 1, g2: before.g2 + 1, g3: before.g3 }, "web's card (its recipient's state) and api's own card (its dot); tests' card is untouched");
  await dispatch(frame([g1h, card("g2")._it, g3], { working: ["web"] }));
  assert.equal(card("g1")._delegations.style.display, "none", "idle again: the line is gone");
  await dispatch(frame([g1, card("g2")._it, g3], { working: ["web"] }));   // the tree as before
});

test("a remote host going down is a paint input: that host's card repaints (its host prefix takes the off mark) and no other card does", async () => {
  const downs: string[] = [];
  (globalThis as any).__rompFed = { down: () => downs };                    // what hostIsDown reads (federation.js publishes it)
  const r1 = cardOf("r1", "remote:" + API, "remote:api", "#996633", "Draft the notes-api docs", "working");
  await dispatch(frame([g1, card("g2")._it, g3, r1], { working: ["web"] }));
  const prefix = () => card("r1")._name.querySelector(".host-prefix")!;
  assert.equal(prefix().textContent, "remote:"); assert.ok(!prefix().classList.contains("off"));
  const before = { ...nameRebuilds(), r1: card("r1")._name.rc };
  downs.push("remote");
  await dispatch(frame([g1, card("g2")._it, g3, r1], { working: ["web"] }));   // the same objects: only the host's reachability changed
  assert.ok(prefix().classList.contains("off"), "the link is marked down");
  assert.deepEqual({ ...nameRebuilds(), r1: card("r1")._name.rc }, { ...before, r1: before.r1 + 1 }, "the remote card alone repainted");
  delete (globalThis as any).__rompFed;
  await dispatch(frame([g1, card("g2")._it, g3], { working: ["web"] }));
  assert.ok(!card("r1"));
});

test("a colour echo (an in-place write into the shared objects) repaints that session's cards through the key, once", async () => {
  const before = nameRebuilds();
  win.dispatchEvent(Object.assign(new Event("storage"), { key: "romp:color-echo", newValue: JSON.stringify({ sid: API, bg: "#cc3366" }) }));
  assert.deepEqual(nameRebuilds(), { g1: before.g1, g2: before.g2 + 1, g3: before.g3 }, "api's card repainted, the others did not");
  assert.equal(card("g2")._name.style.color, "#cc3366");
  await dispatch(frame([g1, card("g2")._it, g3], { working: ["web"] }));   // the same objects again, colour still echoed
  assert.deepEqual(nameRebuilds(), { g1: before.g1, g2: before.g2 + 1, g3: before.g3 }, "the echoed colour is in the key: no flap, no second rebuild");
});

test("the 15 s live pass moves ages and durations on cards no frame touched, writing only the labels whose text changed", () => {
  // 16.7 s have elapsed since boot (frame C's 700 ms, the 16 s boundary), so one pass has run, at 15 s. The pass
  // runs at every 15 s multiple on the kernel's clock — the frame's `now` plus the local time since its `nowAt`.
  // The cards are 240 s old at the frame and relAge rounds to the nearest minute, so "4m ago" becomes "5m ago" at
  // 270 s (30 s elapsed); the wait is 600 s old and workingFor floors, so "10m" becomes "11m" at 660 s (60 s).
  const before = nameRebuilds();
  const time1 = card("g1")._time, dur3 = card("g3")._awaitWhy.querySelector(".fask-dur")!;
  const t1 = time1.tc, d3 = dur3.tc;
  assert.equal(time1.textContent, "4m ago"); assert.equal(dur3.textContent, "10m");
  mock.timers.tick(15_000);                 // the pass at 30 s: the age label crossed its minute, the duration did not
  assert.equal(time1.textContent, "5m ago"); assert.equal(time1.tc, t1 + 1, "one write, at the minute it crossed");
  assert.equal(dur3.textContent, "10m"); assert.equal(dur3.tc, d3, "an unchanged label is not written");
  mock.timers.tick(30_000);                 // the passes at 45 s and 60 s: only the duration crossed, at 60 s
  assert.equal(dur3.textContent, "11m"); assert.equal(dur3.tc, d3 + 1);
  assert.equal(time1.textContent, "5m ago"); assert.equal(time1.tc, t1 + 1);
  mock.timers.tick(15_000);                 // the pass at 75 s: nothing crossed, nothing written
  assert.equal(time1.tc, t1 + 1); assert.equal(dur3.tc, d3 + 1);
  assert.deepEqual(nameRebuilds(), before, "the pass repaints labels, never cards");
  // a pane nobody can see skips the pass and catches up once when shown
  doc.hidden = true;
  mock.timers.tick(60_000);                 // the passes at 90-135 s: the age reads 6m from 90 s (330 s) on — nothing written while hidden
  assert.equal(time1.textContent, "5m ago"); assert.equal(time1.tc, t1 + 1);
  assert.equal(dur3.textContent, "11m"); assert.equal(dur3.tc, d3 + 1);
  doc.hidden = false;
  doc.dispatchEvent(new Event("visibilitychange"));
  assert.equal(time1.textContent, "6m ago", "shown: one catch-up pass"); assert.equal(time1.tc, t1 + 2);
  assert.equal(dur3.textContent, "12m"); assert.equal(dur3.tc, d3 + 1 + 1);   // 735 s
  doc.dispatchEvent(new Event("visibilitychange"));
  assert.equal(time1.tc, t1 + 2, "a second visibility flip with no skipped pass behind it runs nothing");
  // the other measure the paint gate reads: #feed-list off screen by the observer's word (the pane the shell has
  // display:none'd, for which document.hidden stays false) skips the pass the same way, and the observer's
  // callback is what catches it up — a same-size re-show fires no resize
  assert.equal(observers.length, 1, "render() observes #feed-list once");
  observers[0].cb([{ isIntersecting: false }]);
  mock.timers.tick(60_000);                 // the passes at 150-195 s: the age reads 7m from 150 s (390 s) on — nothing written off screen
  assert.equal(time1.textContent, "6m ago"); assert.equal(time1.tc, t1 + 2);
  assert.equal(dur3.textContent, "12m"); assert.equal(dur3.tc, d3 + 2);
  observers[0].cb([{ isIntersecting: true }]);
  assert.equal(time1.textContent, "7m ago", "on screen by the observer's word: one catch-up pass"); assert.equal(time1.tc, t1 + 3);
  assert.equal(dur3.textContent, "13m"); assert.equal(dur3.tc, d3 + 3);   // 795 s
  observers[0].cb([{ isIntersecting: true }]);
  assert.equal(time1.tc, t1 + 3, "a second callback with no skipped pass behind it runs nothing");
  assert.deepEqual(nameRebuilds(), before);
});

// The kernel clock as a card painted NOW reads it: the frame's `now` plus the local seconds since its `nowAt`
// (feed-age.ts liveNow). The tests below stamp their fixtures relative to it and tick 15 s at a time, one pass
// per tick (the pass runs at every 15 s of local time since the module loaded). Under the mock a pass fired
// inside a tick reads the clock at the tick's END (frame C's note), so each 15 s tick moves every label's clock
// by 15 s. Ages round to the minute (relAge), durations floor (workingFor).
const kernelNow = () => K0 + Math.floor((Date.now() - T0 * 1000) / 1000);
const dur = (el: any) => el.querySelector(".fask-dur");

test("the grouped-mode headers write their labels compare-first: three renders of one frame write no text; a background process appearing writes that header's chip alone", async () => {
  const same = frame([g1, card("g2")._it, g3], { working: ["web"] });
  await dispatch(same);
  const heads = () => body.querySelectorAll(".feed-sess-head").filter((h) => !h.classList.contains("sess-exit"));
  const writes = () => Object.fromEntries(heads().map((h: any) => [h.getAttribute("data-fsid"), h._fold.tc + h._foldn.tc + h._svc.tc]));
  const before = writes();
  assert.equal(Object.keys(before).length, 3, "one header per session run");
  await dispatch(same); await dispatch(same);
  assert.deepEqual(writes(), before, "the caret, the folded count and the process chip: compared and skipped");
  await dispatch(frame([g1, card("g2")._it, g3], { working: ["web"], bgServices: { web: ["dev server on :3000"] } }));
  const webHead = heads().find((h: any) => h.getAttribute("data-fsid") === WEB) as any;
  assert.equal(webHead._svc.textContent, "background process"); assert.equal(webHead._svc.style.display, "");
  assert.deepEqual(writes(), { ...before, [WEB]: before[WEB] + 1 }, "one write, on the header whose chip changed");
  await dispatch(same);                                          // the process is gone: the chip's count text and display change back
  assert.equal(webHead._svc.style.display, "none");
  assert.deepEqual(writes(), { ...before, [WEB]: before[WEB] + 2 });
});

test("the Awaiting-task pill's waited time and the waiting-on chip's elapsed time are stamped durations the pass moves, writing once at the minute they cross; a wait with no `since` carries no duration", async () => {
  const kNow = kernelNow();
  const g4 = cardOf("g4", TESTS, "tests", "#33cc66", "Run the lint pass", "working",
    { awaiting: { why: "", kind: "tasks", tasks: ["run the suite"], count: 1, since: kNow - 595 } });   // 9m 55s into the wait
  const g5 = cardOf("g5", API, "api", "#cc6633", "Ask web for the route list", "working",
    { waitingOn: { peerSid: WEB, name: "web", color: null, inCycle: false, since: kNow - 595 },
      awaiting: { why: "", kind: "tasks", tasks: ["lint"], count: 1 } });                             // a wait with no since
  await dispatch(frame([g1, card("g2")._it, g3, g4, g5], { working: ["web"] }));
  const pill = card("g4")._taskLbl, pillDur = dur(pill);
  assert.equal(card("g4")._taskBtn.style.display, "", "live tasks: the pill shows");
  assert.ok(pillDur, "…with the wait's duration as a stamped element");
  assert.equal(pillDur.dataset.ageFmt, "dur"); assert.equal(pillDur.dataset.ageT, String(kNow - 595));
  assert.equal(pillDur.textContent, "9m"); assert.match(pill.textContent, /^Awaiting .* · 9m$/);
  const chip = card("g5")._badges.querySelector(".fask-waiton"), chipDur = chip.querySelector(".fask-waiton-dur .fask-dur"), chipName = chip.querySelector(".fask-waiton-name");   // the chip is a state badge in the name row's slot (card-sections.ts stateBadges, round two of the box content PR)
  assert.equal(chipDur.textContent, "9m"); assert.equal(chipDur.dataset.ageT, String(kNow - 595));
  assert.equal(chipName.textContent, "web");
  assert.ok(!dur(card("g5")._taskLbl), "no since: no duration node, no guess");
  assert.doesNotMatch(card("g5")._taskLbl.textContent, / · /, "the label ends with the word alone");
  const w0 = { pill: pillDur.tc, chip: chipDur.tc, name: chipName.tc };
  mock.timers.tick(15_000);                                      // 610 s into both waits → "10m"
  assert.equal(pillDur.textContent, "10m"); assert.equal(chipDur.textContent, "10m");
  assert.deepEqual({ pill: pillDur.tc, chip: chipDur.tc, name: chipName.tc }, { pill: w0.pill + 1, chip: w0.chip + 1, name: w0.name }, "one write each; the peer's name node untouched");
  mock.timers.tick(15_000);                                      // 625 s → still "10m"
  assert.deepEqual({ pill: pillDur.tc, chip: chipDur.tc, name: chipName.tc }, { pill: w0.pill + 1, chip: w0.chip + 1, name: w0.name }, "no crossing, no write");
  await dispatch(frame([g1, card("g2")._it, g3], { working: ["web"] }));
  assert.ok(!card("g4") && !card("g5"), "the fixtures left with the frame");
});

let g7: any;   // the needs-you card the next two tests share
test("per-paragraph ages of a multi-item brief are stamps the pass moves; a paragraph with no event time is the static '<1m ago' chip", async () => {
  const kNow = kernelNow();
  g7 = cardOf("g7", WEB, "web", "#3366cc", "Decide the auth scheme", "needs_input",
    { blockSummary: "Pick between sessions and tokens.\n\nName the cookie domain.\n\nStill open: the refresh interval.",
      briefParts: [{ id: "g7a", since: kNow - 260 }, { id: "g7b", since: kNow - 600 }, { id: "g7c", since: null }] });
  await dispatch(frame([g1, card("g2")._it, g3, g7], { working: ["web"] }));
  const ages = (): any[] => card("g7")._distill.querySelectorAll(".fask-para-age");
  assert.equal(ages().length, 3, "one chip per paragraph");
  assert.deepEqual(ages().map((a) => a.textContent), ["4m ago", "10m ago", "<1m ago"]);
  assert.deepEqual(ages().map((a) => a.dataset.ageT), [String(kNow - 260), String(kNow - 600), undefined], "the third carries no stamp: nothing to count from");
  const w0 = ages().map((a) => a.tc);
  mock.timers.tick(15_000);                                      // 275 s rounds to 5m; 615 s stays 10m
  assert.deepEqual(ages().map((a) => a.textContent), ["5m ago", "10m ago", "<1m ago"]);
  assert.deepEqual(ages().map((a) => a.tc), [w0[0] + 1, w0[1], w0[2]]);
  mock.timers.tick(30_000);                                      // 305 s stays 5m; 645 s rounds to 11m
  assert.deepEqual(ages().map((a) => a.textContent), ["5m ago", "11m ago", "<1m ago"]);
  assert.deepEqual(ages().map((a) => a.tc), [w0[0] + 1, w0[1] + 1, w0[2]], "the unstamped chip is never written");
});

test("the latched Continue's hover title is refreshed by the pass once the payload carries the latch, compare-then-write", async () => {
  const cont = card("g7")._cont;
  assert.equal(cont.style.display, "", "a live needs-you card offers Continue");
  let sets = 0, held = "";
  const watch = () => { held = cont.title; Object.defineProperty(cont, "title", { get: () => held, set: () => { sets++; }, configurable: true }); };
  const unwatch = () => { delete cont.title; cont.title = held; };
  cont.onclick(ev);                                              // posts the gesture, latches the button, predicts the move to Working
  assert.equal(cont.disabled, true);
  assert.match(cont.title, /^a continue sent — /); assert.doesNotMatch(cont.title, /ago/, "no age: the click's own object carries no followupAt");
  watch(); mock.timers.tick(14_000); unwatch();                  // one pass, inside the prediction's 15 s ack window
  assert.equal(sets, 0, "the payload does not carry the latch yet: the pass has nothing to move and writes nothing");
  const kNow = kernelNow();
  await dispatch(frame([g1, card("g2")._it, g3, { ...g7, column: "working", followupPending: true, followupAt: kNow - 100 }], { working: ["web"] }));   // the kernel confirms, stamping the follow-up 100 s ago
  assert.equal(cont.disabled, true, "still latched: the judge has not ruled");
  assert.match(cont.title, /^a continue sent 2m ago — /, "the payload's stamp is the title's age now");
  watch(); mock.timers.tick(15_000); mock.timers.tick(15_000); unwatch();   // 115 s, 130 s: both round to 2m
  assert.equal(sets, 0, "two passes, no crossing: the title is compared and left alone");
  mock.timers.tick(30_000);                                      // 160 s rounds to 3m
  assert.match(cont.title, /^a continue sent 3m ago — /, "the pass moved the title's age");
  await dispatch(frame([g1, card("g2")._it, g3], { working: ["web"] }));
  assert.ok(!card("g7"));
});

test("the group card's time label is a stamp the pass moves: the newest member's time", async () => {
  const kNow = kernelNow();
  const h1 = cardOf("h1", API, "api", "#cc6633", "Ship the README", "working", { turnId: "turn-shared", groupTitle: "Ship the README and the CHANGELOG", t: kNow - 260 });
  const h2 = cardOf("h2", API, "api", "#cc6633", "Ship the CHANGELOG", "working", { turnId: "turn-shared", groupTitle: "Ship the README and the CHANGELOG", t: kNow - 300 });
  await dispatch(frame([g1, card("g2")._it, g3, h1, h2], { working: ["web"] }));
  const group = body.querySelector('[data-key="g:turn-shared"]') as any;
  assert.ok(group, "two asks of one typed turn fold into a group card"); assert.ok(!card("h1"), "the members are folded into it");
  assert.equal(group._time.textContent, "4m ago"); assert.equal(group._time.dataset.ageT, String(kNow - 260));
  const w0 = group._time.tc;
  mock.timers.tick(15_000);                                      // 275 s → 5m
  assert.equal(group._time.textContent, "5m ago"); assert.equal(group._time.tc, w0 + 1);
  mock.timers.tick(15_000);                                      // 290 s → still 5m
  assert.equal(group._time.tc, w0 + 1, "no crossing, no write");
  await dispatch(frame([g1, card("g2")._it, g3], { working: ["web"] }));
  assert.ok(!body.querySelector('[data-key="g:turn-shared"]'));
  mock.timers.tick(700);                                         // the in-place glides this frame started end (their backstop) before the fly cases below
});

test("Undo inside a card's 180 ms collapse keeps the restored card: the gesture strips .dismissing, which the class rewrite used to do", () => {
  const c3 = card("g3");
  c3._clr.onclick(ev);                      // Clear: .dismissing + a 180 ms removal timer, the id held back from pushes
  assert.ok(c3.classList.contains("dismissing"));
  assert.equal(posted.filter((m) => m.type === "askClear").length, 1);
  body.byId("feed-undoclear")!.onclick!(ev);   // Undo before the collapse ends: the same object, the same key
  assert.ok(!c3.classList.contains("dismissing"), "Undo took the class off");
  mock.timers.tick(200);                    // the collapse timer fires and finds nothing to remove
  assert.equal(card("g3"), c3, "the restored card is still on the board, the same element");
  assert.equal(colOf("g3"), "col-asks-list");
});

test("a card moving into a FOLDED column (display:none, a zero rect) gets no fly: nothing to glide to, and the class it would wear turns the pointer off", async () => {
  body.byId("col-completed-list")!.style.display = "none";   // the Completed section folded to its header
  const g3done = { ...card("g3")._it, column: "completed" };
  await dispatch(frame([g1, card("g2")._it, g3done], { working: ["web"] }));
  assert.equal(colOf("g3"), "col-completed-list", "the card moved");
  assert.ok(!card("g3").classList.contains("fitem-flying"), "no fly into a column nobody can see");
  assert.equal(card("g3").style.transform ?? "", "", "no inverted transform left on it");
  body.byId("col-completed-list")!.style.display = "";
});

test("…and a card LEAVING a folded column (a zero First rect) gets no fly either: nothing to glide from", async () => {
  body.byId("col-completed-list")!.style.display = "none";   // g3 sits in the folded Completed section
  await dispatch(frame([g1, card("g2")._it, { ...card("g3")._it, column: "working" }], { working: ["web"] }));
  assert.equal(colOf("g3"), "col-asks-list", "the card moved back to Working");
  assert.ok(!card("g3").classList.contains("fitem-flying"), "no fly from a spot nobody could see");
  assert.equal(card("g3").style.transform ?? "", "", "no inverted transform from the pane's corner");
  body.byId("col-completed-list")!.style.display = "";
});

test("a second fly of the same card while the first still runs keeps its own Invert through the first fly's cancel, and the first fly's backstop leaves it alone", async () => {
  const c2 = card("g2");
  await dispatch(frame([g1, { ...c2._it, column: "working" }, card("g3")._it], { working: ["web"] }));   // fly 1: Completed → Working
  assert.ok(c2.classList.contains("fitem-flying"));
  mock.timers.tick(20);                                        // fly 1 plays: its transition is running
  assert.equal(c2.style.transform, "translate(0, 0)");
  await dispatch(frame([g1, { ...c2._it, column: "completed" }, card("g3")._it], { working: ["web"] }));   // fly 2, mid-flight: back to Completed
  const inverted = c2.style.transform;
  assert.match(inverted, /^translate\(-?\d/, "fly 2 inverted the card to its old spot");
  assert.notEqual(inverted, "translate(0, 0)");
  // the browser cancels fly 1's transition on that write and tells EVERY listener before fly 2's Play frame
  c2.dispatchEvent(Object.assign(new Event("transitioncancel"), { propertyName: "transform" }));
  assert.equal(c2.style.transform, inverted, "fly 1's cancel handler is superseded; fly 2's ignores an event before its own Play — the Invert survives");
  assert.ok(c2.classList.contains("fitem-flying"), "…and the back layer stays on for the crossing");
  mock.timers.tick(20);                                        // fly 2 plays
  assert.equal(c2.style.transform, "translate(0, 0)");
  assert.match(c2.style.transition, /transform \.42s/);
  mock.timers.tick(610);                                       // fly 1's 650 ms backstop falls due: superseded, a no-op
  assert.match(c2.style.transition, /transform \.42s/, "fly 2 is still in flight");
  assert.ok(c2.classList.contains("fitem-flying"));
  mock.timers.tick(20);                                        // fly 2's own backstop ends it
  assert.equal(c2.style.transform, "");
  assert.equal(c2.style.transition, "");
  assert.ok(!c2.classList.contains("fitem-flying"));
});

test("a fly ends on its own transitionend; another property's transitionend is not this fly's", async () => {
  const c2 = card("g2");
  await dispatch(frame([g1, { ...c2._it, column: "working" }, card("g3")._it], { working: ["web"] }));   // Completed → Working
  assert.ok(c2.classList.contains("fitem-flying"));
  mock.timers.tick(20);                                        // played
  assert.equal(c2.style.transform, "translate(0, 0)");
  c2.dispatchEvent(Object.assign(new Event("transitionend"), { propertyName: "opacity" }));
  assert.ok(c2.classList.contains("fitem-flying"), "another property's end is not this fly's");
  assert.equal(c2.style.transform, "translate(0, 0)");
  c2.dispatchEvent(Object.assign(new Event("transitionend"), { propertyName: "transform" }));
  assert.ok(!c2.classList.contains("fitem-flying"), "the transform's end takes the card out of the back layer");
  assert.equal(c2.style.transform, ""); assert.equal(c2.style.transition, "");
  mock.timers.tick(700);
  assert.equal(c2.style.transform, "", "…and the backstop that follows has nothing to do");
});

test("a fly ends on a transitioncancel AFTER its Play: a card hidden or re-inserted mid-flight gets cancel, never end", async () => {
  const c2 = card("g2");
  await dispatch(frame([g1, { ...c2._it, column: "completed" }, card("g3")._it], { working: ["web"] }));   // Working → Completed
  assert.ok(c2.classList.contains("fitem-flying"));
  mock.timers.tick(20);                                        // played: the cancel is now this fly's own
  c2.dispatchEvent(Object.assign(new Event("transitioncancel"), { propertyName: "transform" }));
  assert.ok(!c2.classList.contains("fitem-flying"), "the cancel of its own transition ends the fly");
  assert.equal(c2.style.transform, ""); assert.equal(c2.style.transition, "");
});

test("the release frame stands down when the backstop already ended the fly: no identity transform is left on a settled card", async () => {
  const c2 = card("g2");
  await dispatch(frame([g1, { ...c2._it, column: "working" }, card("g3")._it], { working: ["web"] }));   // Completed → Working
  assert.ok(c2.classList.contains("fitem-flying"));
  mock.timers.tick(700);   // ONE tick: a timer created inside a tick is stamped at its end, so the nested animation frame runs AFTER the 650 ms backstop — a hidden tab's order
  assert.ok(!c2.classList.contains("fitem-flying"), "the backstop ended the fly");
  assert.equal(c2.style.transform, "", "the release frame found it ended and wrote nothing");
  assert.equal(c2.style.transition, "");
});

test("the back-layer class comes off whichever fly added it: a crossing fly superseded by an in-place shift of the same card", async () => {
  const c2 = card("g2");
  await dispatch(frame([g1, { ...c2._it, column: "completed" }, card("g3")._it], { working: ["web"] }));   // fly 1: Working → Completed, crossing
  assert.ok(c2.classList.contains("fitem-flying"));
  mock.timers.tick(20);                                        // fly 1 plays
  // fly 2: web's card lands in Completed above api's run, so g2 shifts within its column — no crossing
  await dispatch(frame([{ ...g1, column: "completed" }, card("g2")._it, card("g3")._it], { working: ["web"] }));
  assert.equal(colOf("g2"), "col-completed-list");
  assert.match(c2.style.transform, /^translate\(-?\d/, "fly 2 inverted the shift");
  c2.dispatchEvent(Object.assign(new Event("transitioncancel"), { propertyName: "transform" }));   // fly 1's transition was interrupted: its cancel
  assert.ok(c2.classList.contains("fitem-flying"), "fly 1 is superseded and touches nothing: the class stays for the fly that owns the card");
  mock.timers.tick(20);                                        // fly 2 plays
  mock.timers.tick(650);                                       // fly 2's backstop
  assert.ok(!c2.classList.contains("fitem-flying"), "fly 2 did not cross, and still takes the class off: whichever fly added it");
  assert.equal(c2.style.transform, ""); assert.equal(c2.style.transition, "");
  await dispatch(frame([g1, card("g2")._it, card("g3")._it], { working: ["web"] }));   // g1 back to Working
  mock.timers.tick(700);
});

test("Retry latches on the click and re-arms only on a deciding event: the kernel's reply frame, or a repaint of the card", async () => {
  const blockedG1 = { ...g1, blocked: { state: "apiError", what: "the API returned 529", status: 529 } };
  await dispatch(frame([blockedG1, card("g2")._it, card("g3")._it]));   // web is NOT working: the API-error unit shows
  const retry = card("g1")._apiRetry;
  assert.equal(retry.style.display, ""); assert.equal(retry.disabled, false); assert.equal(retry.textContent, "Retry");
  const sent = posted.length;
  retry.onclick(ev);
  assert.deepEqual(posted.slice(sent).filter((m) => m.type === "apiRetry"), [{ type: "apiRetry", id: WEB, manual: true }],
    "a MANUAL retry: the kernel fires it past every auto gate, as the chat pane's button does");
  assert.equal(retry.disabled, true); assert.equal(retry.textContent, "Retrying…");
  await dispatch(frame([blockedG1, card("g2")._it, card("g3")._it]));   // the same objects again: nothing decided
  assert.equal(retry.disabled, true, "a re-emit is not a deciding event");
  await dispatch({ type: "err", sid: API, op: "apiRetry", text: "another session's business" });
  assert.equal(retry.disabled, true, "another session's reply is not this card's event");
  await dispatch({ type: "err", text: "a reply that names no session" });
  assert.equal(retry.disabled, true, "a reply naming no session answers no request: nothing re-arms");
  await dispatch({ type: "err", sid: WEB, op: "askFollowUp", itemId: "g1", text: "this session's reply to a DIFFERENT request" });
  assert.equal(retry.disabled, true, "the reply to another request of this session is not this button's");
  await dispatch({ type: "err", sid: WEB, op: "apiRetry", text: "the retry was not delivered" });
  assert.equal(retry.disabled, false, "the kernel's refusal of THIS session's retry re-arms it");
  assert.equal(retry.textContent, "Retry");
  retry.onclick(ev);
  assert.equal(retry.disabled, true);
  await dispatch({ type: "retryRefused", sid: WEB, text: "Couldn't retry: the session isn't connected right now." });
  assert.equal(retry.disabled, false, "the backend's refusal of the manual retry (the kernel's retryRefused) re-arms it");
  assert.equal(body.querySelector(".feed-toast")?.textContent, "Couldn't retry: the session isn't connected right now.", "…and says why");
  retry.onclick(ev);
  assert.equal(retry.disabled, true);
  await dispatch({ type: "err", sid: WEB, text: "an older kernel's refusal names the session and no request" });
  assert.equal(retry.disabled, false, "a reply naming the session but no request releases the session's Retry, as before the op field");
  retry.onclick(ev);
  assert.equal(retry.disabled, true);
  await dispatch(frame([{ ...blockedG1 }, card("g2")._it, card("g3")._it]));   // a new object for the card: it repaints
  assert.equal(retry.disabled, false, "a repaint re-arms it too");
  await dispatch(frame([g1, card("g2")._it, card("g3")._it]));   // the block is gone: the unit hides
  assert.equal(card("g1")._apiRetry.style.display, "none");
});

test("Continue latches on the click and predicts the move; the kernel's refusal of THAT post re-arms it and returns the card, a refusal of another card's post leaves both", async () => {
  const needsG1 = { ...g1, column: "needs_input" };
  await dispatch(frame([needsG1, card("g2")._it, card("g3")._it], { working: ["api"] }));   // web is live and waiting on you, no live ask
  const cont = card("g1")._cont;
  assert.equal(cont.style.display, ""); assert.equal(cont.disabled, false); assert.equal(cont.textContent, "Continue");
  assert.equal(colOf("g1"), "col-needsInput-list");
  const sent = posted.length;
  cont.onclick(ev);
  assert.deepEqual(posted.slice(sent).filter((m) => m.type === "askFollowUp"), [{ type: "askFollowUp", itemId: "g1", sid: WEB, cont: true }]);
  assert.equal(cont.disabled, true); assert.equal(cont.textContent, "Sent");
  assert.equal(colOf("g1"), "col-asks-list", "the predicted move: the card goes to Working ahead of the kernel");
  await dispatch(frame([needsG1, card("g2")._it, card("g3")._it], { working: ["api"] }));   // the same objects: nothing decided
  assert.equal(cont.disabled, true, "a re-emit is not a deciding event");
  assert.equal(colOf("g1"), "col-asks-list", "…and the prediction holds");
  await dispatch({ type: "err", sid: WEB, op: "askFollowUp", itemId: "g1a", title: "That reply was not delivered", text: "Nothing was sent." });
  assert.equal(cont.disabled, true, "a refusal of another card's post is not this button's reply");
  await dispatch({ type: "err", sid: WEB, op: "askFollowUp", itemId: "g1", title: "That reply was not delivered", text: "Nothing was sent." });
  assert.equal(cont.disabled, false, "the kernel's refusal of this card's post re-arms it");
  assert.equal(cont.textContent, "Continue");
  assert.equal(colOf("g1"), "col-needsInput-list", "…and the predicted move yields to the kernel's answer: the card is back where the payload says");
  await dispatch(frame([g1, card("g2")._it, card("g3")._it]));   // web back to Working
  assert.equal(colOf("g1"), "col-asks-list");
});

test("a reveal pulse comes off when its animation ends, and a child's animation ending inside the card does not end it", async () => {
  const c1 = card("g1");
  await dispatch({ type: "revealCards", keys: ["g1"] });
  assert.ok(c1.classList.contains("card-pulse"));
  // animationend bubbles: a button's acted flash inside the card reaches the card's listener too
  c1.dispatchEvent(Object.assign(new Event("animationend"), { animationName: "romp-acted-pulse" }));
  assert.ok(c1.classList.contains("card-pulse"), "another animation's end is not this pulse's");
  c1.dispatchEvent(Object.assign(new Event("animationend"), { animationName: "romp-card-pulse" }));
  assert.ok(!c1.classList.contains("card-pulse"), "the pulse's own end takes the class off");
  mock.timers.tick(1600);
  assert.ok(!c1.classList.contains("card-pulse"), "…and the backstop that follows has nothing to do");
});

test("a second reveal pulse inside the first's window is not cut short by the first's backstop", async () => {
  const c1 = card("g1");
  await dispatch({ type: "revealCards", keys: ["g1"] });
  assert.ok(c1.classList.contains("card-pulse"));
  mock.timers.tick(600);
  await dispatch({ type: "revealCards", keys: ["g1"] });        // pulse again, 600 ms in
  mock.timers.tick(1000);                                       // the FIRST backstop's moment (1500 ms after it armed)
  assert.ok(c1.classList.contains("card-pulse"), "the second pulse still shows: one handle per element");
  mock.timers.tick(600);                                        // the second backstop
  assert.ok(!c1.classList.contains("card-pulse"), "…and it comes off at its own end");
});

test("a pulse ended by its animationend leaves no backstop behind: a later reveal inside 1500 ms is not cut short by it", async () => {
  const c1 = card("g1");
  await dispatch({ type: "revealCards", keys: ["g1"] });
  c1.dispatchEvent(Object.assign(new Event("animationend"), { animationName: "romp-card-pulse" }));
  assert.ok(!c1.classList.contains("card-pulse"));
  mock.timers.tick(600);
  await dispatch({ type: "revealCards", keys: ["g1"] });        // pulse again
  mock.timers.tick(1000);                                       // the first backstop's moment, had it survived the end
  assert.ok(c1.classList.contains("card-pulse"), "the second pulse still shows");
  mock.timers.tick(600);
  assert.ok(!c1.classList.contains("card-pulse"), "…and ends at its own backstop");
});

test("a session header's name nodes are minted only when what they show changes: an unchanged header re-mints nothing", async () => {
  // grouped mode's headers are not behind the per-card gate: updateSessHead runs for every header on every
  // render, and minted the name nodes each time (a Text-node replacement per header per render)
  const heads = () => Object.fromEntries(body.querySelectorAll(".feed-sess-head").filter((h: any) => !h.classList.contains("sess-exit"))
    .map((h: any) => [h.getAttribute("data-fsid"), h._name.rc]));
  const same = frame([g1, card("g2")._it, card("g3")._it]);   // the objects the cards were painted from
  await dispatch(same);
  const before = heads();
  assert.equal(Object.keys(before).length, 3, "one header per session run");
  await dispatch(same);
  await dispatch(same);
  assert.deepEqual(heads(), before, "an unchanged header re-mints nothing");
  await dispatch(frame([{ ...g1, name: "web-2" }, card("g2")._it, card("g3")._it]));   // web's card renamed: its header follows
  assert.deepEqual(heads(), { ...before, [WEB]: before[WEB] + 1 }, "the renamed session's header re-minted once; the others did not");
  assert.equal((body.querySelector(`.feed-sess-head[data-fsid="${WEB}"]`) as any)._name.textContent, "web-2");
});

test("a header's data-fsid and data-fcol are written only when they differ", async () => {
  const heads = () => body.querySelectorAll(".feed-sess-head").filter((h) => !h.classList.contains("sess-exit"));
  const same = frame([{ ...g1, name: "web-2" }, card("g2")._it, card("g3")._it]);   // the objects the cards were painted from
  await dispatch(same);
  const stamps = () => heads().map((h) => [h.getAttribute("data-fsid"), h.getAttribute("data-fcol"), h.ac]);
  const before = stamps();
  assert.equal(before.length, 3);
  assert.deepEqual(before.map((s) => s[1]), heads().map((h) => h.parentNode!.id.replace(/^col-|-list$/g, "")), "each header is stamped with the column it heads");
  await dispatch(same); await dispatch(same);
  assert.deepEqual(stamps(), before, "an unchanged sid or column is compared and not re-set");
});

test("a hovered session header is one (column, session) row: the same session's header in another column keeps its in-row badge and the floating hint sits under the hovered row", async () => {
  // grouped mode keys a header per (column, session), so a session with cards in two columns has two header
  // rows, both stamped with its sid. The hover-freeze painter found the hovered row by sid alone, so the twin in
  // the other column took the hovered branch too: its in-row badge was stripped, and the one floating hint was
  // re-placed under it (the last twin in document order), away from the row the pointer is on.
  const g1b = cardOf("g1b", WEB, "web", "#3366cc", "Check the notes-api health route", "needs_input");
  const g1c = cardOf("g1c", WEB, "web", "#3366cc", "Ship the notes-api health route", "completed");
  const four = [g1, g1b, card("g2")._it, card("g3")._it];
  await dispatch(frame(four));
  const heads = () => body.querySelectorAll(`.feed-sess-head[data-fsid="${WEB}"]`).filter((h) => !h.classList.contains("sess-exit"));
  assert.deepEqual(heads().map((h) => h.parentNode!.id), ["col-asks-list", "col-needsInput-list"], "web heads a run in Working and one in Blocked");
  const [hw, hb] = heads();
  const badged = (h: El) => h.children.some((c) => c.classList.contains("freeze-badge"));
  // the stand-in's rects derive from the parent list's id, so the two rows sit at different rights; the hint's
  // position says which row it was placed under
  const rightOf = (h: El) => (win.innerWidth - h.getBoundingClientRect().right) + "px";
  assert.notEqual(rightOf(hw), rightOf(hb));
  hw.dispatchEvent(new Event("mouseenter"));                     // the pointer rests on the Working row
  try {
    await dispatch(frame([...four, g1c]));                       // a push while it is held: one more web card, in Completed
    assert.equal(card("g1c"), null, "the payload is queued, not rendered");
    assert.ok(badged(hb), "the same session's Blocked header carries its in-row badge");
    assert.ok(!badged(hw), "never inside the hovered row");
    const note = body.byId("freeze-headnote");
    assert.ok(note, "the hovered row's hint floats");
    assert.equal(note!.style.right, rightOf(hw), "right-aligned under the hovered row, not under its twin");
  } finally {
    hw.dispatchEvent(new Event("mouseleave"));                   // release: the queued payload applies (on a failure too,
    await settle();                                              // so the next test never inherits a held gate)
  }
  assert.ok(card("g1c"), "the queued frame applied on release");
  assert.equal(body.byId("freeze-headnote"), null, "nothing pending: the hint comes off with the badges");
  await dispatch(frame([g1, card("g2")._it, card("g3")._it]));   // the three-card world back
  mock.timers.tick(700);                                          // the Blocked and Completed headers finish their exit
});

test("a hovered header's gate releases through its ghost: a Clear that takes the row out from under the pointer re-keys it, and the ghost's mouseleave still applies the queued frame", async () => {
  // a Clear on a run's last card starts the header's exit in the same click, with no render in between: the
  // element is re-keyed to a tombstone (x:N) while the pointer is still on it, and no render heal has run.
  // Its mouseleave must compute the key its mouseenter stored, or the gate stays held until a later local
  // render or a window blur. The stamps the key is read from survive the re-key; the data-key does not.
  const ha = body.querySelector(`.feed-sess-head[data-fsid="${API}"]`)!;   // api heads one run: its one card, g2
  assert.ok(!ha.classList.contains("sess-exit"));
  const stamps = () => [ha.getAttribute("data-fcol"), ha.getAttribute("data-fsid")];
  const before = stamps();
  assert.equal(before[0], ha.parentNode!.id.replace(/^col-|-list$/g, ""), "stamped with the column it heads");
  const g2it = card("g2")._it;                                   // the object g2 was painted from (its column too)
  const g1d = cardOf("g1d", WEB, "web", "#3366cc", "Document the notes-api health route", "working");
  ha.dispatchEvent(new Event("mouseenter"));                     // the pointer rests on api's header row
  try {
    await dispatch(frame([g1, g2it, card("g3")._it, g1d]));      // a push while it is held: one more web card
    assert.equal(card("g1d"), null, "the payload is queued");
    card("g2")._clr.onclick(ev);                                 // Clear api's last card: its header leaves with it
    assert.ok(ha.classList.contains("sess-exit"), "the header ghosts in the same click");
    assert.match(ha.dataset.key!, /^x:\d+$/, "re-keyed to a tombstone while still under the pointer");
    assert.deepEqual(stamps(), before, "the stamps stay");
    assert.equal(card("g1d"), null, "the clear itself is not a release");
    ha.dispatchEvent(new Event("mouseleave"));                   // the pointer leaves the ghost
    await settle();
    assert.ok(card("g1d"), "the ghost's mouseleave released the gate: the queued frame applied");
  } finally {                                                    // on a failure too, so the next test inherits neither
    win.dispatchEvent(new Event("blur"));                        // a held gate (the backstop release) nor a cleared g2
    await settle();
    mock.timers.tick(700);                                        // the cleared card's collapse and the ghost's exit end
    await dispatch(frame([g1, card("g3")._it]));                  // the kernel confirms the clear (g2 absent)
    await dispatch(frame([g1, g2it, card("g3")._it]));            // g2 back where it was, under a fresh api header
  }
  assert.equal(body.querySelectorAll(".sess-exit").length, 0);
  assert.ok(card("g2"));
});

test("a session header's Clear all releases the gate its row holds: the queued frame applies from the click, with no pointer leave and no render", async () => {
  // Clear all sits on the header row, so the pointer that clicks it is resting on the row, and the row holds the
  // hover-freeze gate from its mouseenter. The click turns the row into a pointer-inert ghost (reduced motion
  // removes it outright), and neither fires a mouseleave of its own; a card's Clear dispatches a synthetic
  // mouseleave for exactly this reason. Without the header's own dispatch, the kernel's confirmation of the
  // clear and every push behind it stayed queued until a later local render healed the stale hold, or a
  // window blur. No timer advances before the release is asserted: the 180 ms finalize's render would heal
  // the hold on its own (the stand-in's :hover matches nothing), and the point is the click, not the heal.
  const ha = body.querySelector(`.feed-sess-head[data-fsid="${API}"]`)!;   // api heads one run: its one card, g2
  assert.ok(!ha.classList.contains("sess-exit"));
  const g2it = card("g2")._it;                                   // the object g2 was painted from (its column too)
  const g1d = cardOf("g1d", WEB, "web", "#3366cc", "Document the notes-api health route", "working");
  ha.dispatchEvent(new Event("mouseenter"));                     // the pointer rests on api's header row, over its Clear all
  try {
    await dispatch(frame([g1, g2it, card("g3")._it, g1d]));      // a push while it is held: one more web card
    assert.equal(card("g1d"), null, "the payload is queued");
    // the click takes the path a real one takes: the delegate on the stable columns root, with the row's Clear
    // all as its target. The stand-in's events do not bubble, so the click is dispatched on the root with the
    // button shadowing its target; the delegate resolves the button by its data-act and reads its data-fsid.
    const cols = body.byId("feed-cols")!;
    const btn = (ha as any)._clear as El;
    const postedBefore = posted.length;
    const click = new Event("click");
    Object.defineProperty(click, "target", { value: btn });
    cols.dispatchEvent(click);
    const clears = posted.slice(postedBefore).filter((m) => m.type === "askClearMany");
    assert.deepEqual(clears.map((m) => [m.sid, m.itemIds]), [[API, ["g2"]]], "the click cleared the session's one card");
    assert.ok(card("g2").classList.contains("dismissing"));
    assert.ok(ha.classList.contains("sess-exit"), "the header ghosts in the same click");
    assert.equal(card("g1d"), null, "the release waits for the click's own handlers to finish");
    await settle();                                                // the flush is a microtask after the click's handlers
    assert.ok(card("g1d"), "the click released the gate: the queued frame applied with no pointer leave and no render");
    assert.equal(body.byId("freeze-headnote"), null, "nothing pending: the hint came off");
  } finally {                                                    // on a failure too, so the next test inherits neither
    win.dispatchEvent(new Event("blur"));                        // a held gate (the backstop release) nor a cleared g2
    await settle();
    mock.timers.tick(700);                                        // the cleared card's collapse and the ghost's exit end
    await dispatch(frame([g1, card("g3")._it]));                  // the kernel confirms the clear (g2 absent)
    await dispatch(frame([g1, g2it, card("g3")._it]));            // g2 back where it was, under a fresh api header
  }
  assert.equal(body.querySelectorAll(".sess-exit").length, 0);
  assert.ok(card("g2"));
});

test("a header re-mints its name nodes when its host's link goes down or comes back, and only then", async (t) => {
  t.after(() => mock.timers.reset());   // this test ticks the timers an earlier test enabled and hands them back disabled (its trailing reset, registered with the context now)
  let downList: string[] = [];
  (globalThis as any).__rompFed = { down: () => downList };                 // what hostIsDown reads (federation.js publishes it)
  const REMOTE = "remote:11111111-2222-3333-4444-888888888888";
  const g4 = cardOf("g4", REMOTE, "remote:docs", "#996633", "Draft the notes-api docs", "working");
  const four = () => frame([{ ...g1, name: "web-2" }, card("g2")._it, card("g3")._it, g4],
    { order: [WEB, API, TESTS, REMOTE], sessions: [{ sid: WEB, name: "web-2", color: g1.color }, { sid: API, name: "api", color: g2.color }, { sid: TESTS, name: "tests", color: g3.color }, { sid: REMOTE, name: "remote:docs", color: g4.color }] });
  await dispatch(four());
  const head = () => body.querySelector(`.feed-sess-head[data-fsid="${REMOTE}"]`) as any;
  assert.equal(head()._name.rc, 1, "minted once");
  assert.equal(head()._name.querySelector(".host-prefix").textContent, "remote:");
  assert.ok(!head()._name.querySelector(".host-prefix").classList.contains("off"));
  await dispatch(four());
  assert.equal(head()._name.rc, 1, "the same name, sid and link state: nothing re-minted");
  downList = ["remote"];
  await dispatch(four());
  assert.equal(head()._name.rc, 2, "the link went down: re-minted once…");
  assert.ok(head()._name.querySelector(".host-prefix").classList.contains("off"), "…with the off mark");
  await dispatch(four());
  assert.equal(head()._name.rc, 2, "still down: nothing");
  downList = [];
  await dispatch(four());
  assert.equal(head()._name.rc, 3, "back up: re-minted once…");
  assert.ok(!head()._name.querySelector(".host-prefix").classList.contains("off"), "…the mark gone");
  delete (globalThis as any).__rompFed;
  await dispatch(frame([g1, card("g2")._it, card("g3")._it]));
  mock.timers.tick(700);
});

test("a far host's parked-question note shows on its own line with no brief, in collapsed mode and on a working card, and clears on the next push", async (t) => {
  t.after(() => mock.timers.reset());   // registered with the test context (the second contributor's review): the trailing reset left the timers enabled for every later test after a red
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const note = "a question to api is still parked on PEERHOST: it went on before it could be withdrawn";
  // a blocked card with NO brief yet (the distiller still running): the section logic chooses "none" and hides the distill line
  const g4 = cardOf("g4", WEB, "web", "#3366cc", "Decide the exporter's client", "needs_input", { distillState: "blocked", relayNote: note });
  await dispatch(frame([g1, g4]));
  const rn = () => card("g4")._relayNote;
  assert.equal(card("g4")._distill.style.display, "none", "the distill line is hidden without a brief");
  assert.equal(rn().textContent, note, "the note is the card's own line");
  assert.equal(rn().style.display, "", "…and shows (appended inside the distill element it was hidden with it)");
  // compared by INDEX, never by node identity: a failed identity assertion formats two stand-in nodes (a cyclic
  // tree) and kills the runner before it prints a message (the manager's verifier, with the old placement restored)
  const kids = card("g4")._secs.parentNode.childNodes;
  assert.equal(kids.indexOf(rn()), kids.indexOf(card("g4")._face) + 1, "beside the sections, right after the face line, not inside them");
  assert.equal(kids.indexOf(card("g4")._face), kids.indexOf(card("g4")._secs) + 1, "the face line follows the sections");
  // collapsed mode: every section closed by default, the brief's included
  const setPrefs = (v: string) => { stores.local.set("romp:settings", v); win.dispatchEvent(Object.assign(new Event("storage"), { key: "romp:settings", newValue: v })); };
  setPrefs(JSON.stringify({ collapsed: true }));
  await dispatch(frame([g1, { ...g4, blockSummary: "Pick the client the exporter targets." }]));
  assert.equal(card("g4")._distill.style.display, "none", "collapsed: the brief's section is closed");
  assert.equal(rn().style.display, "", "the note still shows");
  assert.equal(rn().textContent, note);
  setPrefs(JSON.stringify({}));
  // a working-column card, where the brief is withheld: the note shows all the same
  await dispatch(frame([{ ...g1, relayNote: note }, g4], { working: ["web"] }));
  assert.equal(card("g1")._distill.style.display, "none", "working: no distill line");
  assert.equal(card("g1")._relayNote.style.display, "", "the note shows on a working card");
  assert.equal(card("g1")._relayNote.textContent, note);
  // the next push without the record clears it
  await dispatch(frame([g1, { ...g4, blockSummary: "Pick the client the exporter targets.", relayNote: null }]));
  assert.equal(rn().style.display, "none", "cleared when the kernel stops sending it");
  assert.equal(rn().textContent, "");
  assert.equal(card("g1")._relayNote.style.display, "none");
});

test("a NOTICE CARD (T370) renders its producer, body, pinned image and action buttons; an action posts noticeAction with the sid, latches, and re-arms on noticeActionDone", async () => {
  // the kernel's card (build_feed _notice_cards): the AskItem base plus the notice flavour; the body is markdown, the
  // attachment an image the kernel allowed and pinned, one /send action
  const n1 = cardOf("notice:" + WEB + ":figure:2", WEB, "web", "#3366cc", "A new version of the accuracy figure is ready", "completed", {
    live: false, tree: [], blocked: null,
    notice: { producer: "figure", key: "figure", rev: 2, body: "Regenerated after the sweep on **tests** finished.\n\n<img src=\"https://evil.example/x.png\">",
              attachment: { path: "/srv/notes-api/figures/accuracy.png", kind: "image", allowed: true, why: "", pin: "abc123.png" },
              actions: [{ label: "Send again", route: "/send", body: { text: "please regenerate" } }], expiresAt: null, dismissOnAction: true } });
  await dispatch(frame([g1, g2, g3, n1], { working: ["web"] }));
  const c = card("notice:" + WEB + ":figure:2");
  assert.ok(c, "the card is on the board"); assert.equal(colOf("notice:" + WEB + ":figure:2"), "col-completed-list", "an informational notice files under Completed");
  assert.equal(c._nProd.textContent, "via figure"); assert.equal(c._nProd.style.display, "");
  // the user 2026-09-19: a notice card never wears the distiller's "Distilling…" placeholder (a completed card with a null summary
  // is a goal awaiting its takeaway; a notice has nothing to distill: its body IS its text) nor the distiller line
  assert.equal(c._awaitSpin.style.display, "none", "no swirl on a notice card"); assert.equal(c._distill.style.display, "none", "no distiller line");
  assert.match(c._nBody.textContent, /Regenerated after the sweep on \*{0,2}tests\*{0,2} finished\./, "the body says its words (under the document stand-in the sanitizer has no DOM, so the plain-text fall-back; the served lab reads the rendered markdown)");
  assert.equal(c._nBody.querySelectorAll("img").length, 0, "no image element is ever adopted from the body");
  // the document stand-in has no location, so canPreview() cannot say http: the attachment shows as its file name (no
  // fetch); the served lab, in a browser, reads the inline picture from the file route with its pin
  assert.equal(c._nAttach.querySelectorAll("img").length, 0, "no fetch where the page cannot reach the kernel");
  const fname = c._nAttach.querySelector(".fask-nfile");
  assert.ok(fname, "the attachment's name stands in"); assert.equal(fname.textContent, "accuracy.png"); assert.match(fname.title, /accuracy\.png \(image\)$/);
  const btns = c._nActions.querySelectorAll("button");
  assert.equal(btns.length, 1); assert.equal(btns[0].textContent, "Send again");
  const sent = posted.length;
  btns[0].onclick(ev);
  assert.deepEqual(posted.slice(sent).filter((m) => m.type === "noticeAction"),
    [{ type: "noticeAction", itemId: "notice:" + WEB + ":figure:2", sid: WEB, kind: "send", body: { text: "please regenerate" } }], "the gesture carries the sid (federation routes by it) and the action's KIND (an older frame's route read as send)");
  assert.equal(btns[0].disabled, true); assert.equal(btns[0].textContent, "Send again…", "latched on the click");
  // a click on a down socket is dropped and never answered (a kernel restart): the next push, identical or not, lets the latch
  // go, so the button never reads "Send again…" for good (the review of PR 1757, medium 2)
  await dispatch(frame([g1, g2, g3, n1], { working: ["web"] }));
  assert.equal(btns[0].disabled, false); assert.equal(btns[0].textContent, "Send again", "re-armed from the payload on an identical push with no answer");
  btns[0].onclick(ev);
  assert.equal(btns[0].disabled, true, "latched again on the next click");
  await dispatch({ type: "noticeActionDone", itemId: "notice:" + WEB + ":figure:2", ok: false, error: "no running backend owns web" });
  assert.equal(btns[0].disabled, false); assert.equal(btns[0].textContent, "Send again", "re-armed on the kernel's answer");
  assert.match(body.querySelector(".feed-toast")?.textContent ?? "", /refused: no running backend owns web/, "a refusal says why");
  // round four, high: a SUCCESS on a card that dismisses on its action takes the card off the board at once with no re-arm
  // (re-armed, it invited a second click that delivered the words again before the kernel's rebuild landed); a success on
  // a card that stays re-arms
  let left = 0; card("notice:" + WEB + ":figure:2").addEventListener("mouseleave", () => { left++; });   // round six, low: the removal runs the card's own leave logic
  btns[0].onclick(ev);
  await dispatch({ type: "noticeActionDone", itemId: "notice:" + WEB + ":figure:2", ok: true, error: "" });
  assert.equal(card("notice:" + WEB + ":figure:2") === null, true, "the dismissing card left on the success answer");   // a boolean: a failure must not diff the element
  assert.equal(left, 1, "the removed card received its synthetic mouseleave (freezeLeave, the hover highlight), as the clear paths dispatch it");
  const n3 = cardOf("notice:" + WEB + ":stays:1", WEB, "web", "#3366cc", "A card that stays", "completed", {
    live: false, tree: [], blocked: null, notice: { producer: "figure", key: "stays", rev: 1, body: "", attachment: null,
    actions: [{ label: "Ping", route: "/send", body: { text: "ping" } }], expiresAt: null, dismissOnAction: false } });
  await dispatch(frame([g1, g2, g3, n3], { working: ["web"] }));
  const b3 = card("notice:" + WEB + ":stays:1")._nActions.querySelectorAll("button")[0];
  b3.onclick(ev); assert.equal(b3.disabled, true);
  await dispatch({ type: "noticeActionDone", itemId: "notice:" + WEB + ":stays:1", ok: true, error: "" });
  assert.ok(card("notice:" + WEB + ":stays:1"), "a card that stays is still on the board"); assert.equal(b3.disabled, false, "…and its button let go");
  // the HELD answer (the second executed review of PR 1935; a built-feed dispatch since round thirteen of PR 1967, the second contributor's review): the
  // words went out but the dismissal's write refused, so the card stays, its button stays spent, and the toast says both halves
  b3.onclick(ev); assert.equal(b3.disabled, true);
  await dispatch({ type: "noticeActionDone", itemId: "notice:" + WEB + ":stays:1", ok: true, held: true, error: "the card's dismissal could not be recorded" });
  assert.ok(card("notice:" + WEB + ":stays:1"), "the card stays on a held answer"); assert.equal(b3.disabled, true, "its button stays spent: a re-armed one would offer the delivery again");
  assert.equal(body.querySelector(".feed-toast")?.textContent, "The card's action ran, but the card's dismissal could not be recorded.", "the toast says both halves");
  await dispatch({ type: "noticeActionDone", itemId: "notice:" + WEB + ":stays:1", ok: true, error: "" });   // a plain success lets it go again, for the assertions below
  assert.equal(b3.disabled, false);
  // round five: a dismissing card back from Undo carries its action SPENT (the kernel drops the actions and sets acted): no button shows
  const nBack = cardOf("notice:" + WEB + ":figure:2", WEB, "web", "#3366cc", "A new version of the accuracy figure is ready", "completed", {
    live: false, tree: [], blocked: null, notice: { producer: "figure", key: "figure", rev: 2, body: "", attachment: null, actions: [], expiresAt: null, dismissOnAction: true, acted: true } });
  await dispatch(frame([g1, g2, g3, n3, nBack], { working: ["web"] }));
  const back = card("notice:" + WEB + ":figure:2");
  assert.ok(back, "Undo brought the card back"); assert.equal(back._nActions.querySelectorAll("button").length, 0, "…with no action to click"); assert.equal(back._nActions.style.display, "none");
  // a needs-you notice files under Blocked; a card with no body, attachment or actions hides those blocks
  const n2 = cardOf("notice:" + API + ":dropped-sends:1", API, "api", "#cc6633", "1 message you typed before the restart was not re-sent", "needs_input", {
    live: false, tree: [], blocked: null, notice: { producer: "dropped-sends", key: "dropped-sends", rev: 1, body: "", attachment: null, actions: [], expiresAt: null, dismissOnAction: true } });
  await dispatch(frame([g1, g2, g3, n1, n2], { working: ["web"] }));
  const c2 = card("notice:" + API + ":dropped-sends:1");
  assert.equal(colOf("notice:" + API + ":dropped-sends:1"), "col-needsInput-list", "needsYou files under Blocked");
  assert.equal(c2._nBody.style.display, "none"); assert.equal(c2._nAttach.style.display, "none"); assert.equal(c2._nActions.style.display, "none");
  assert.equal(c2._awaitSpin.style.display, "none", "an EMPTY needs-you notice: no swirl either (its null blockSummary is no brief on its way)"); assert.equal(c2._distill.style.display, "none");
  assert.equal(c2._nProd.textContent, "via dropped-sends");
  // Clear on a notice card is the ordinary askClear with the sid
  const sent2 = posted.length;
  c2._clr.onclick(ev);
  assert.deepEqual(posted.slice(sent2).filter((m) => m.type === "askClear"), [{ type: "askClear", itemId: "notice:" + API + ":dropped-sends:1", sid: API }]);
});

test("an OWNER-LESS notice card (no session) shows no session chip and heads its column in both modes; needs-you still wins its column", async () => {
  // the user 2026-09-18: a card with no session at the top of the feed. The kernel posts it under the reserved owner key
  // (kernel.py NOTICE_OWNERLESS_SID, "notes"; the pane's literal is pinned equal in federation-notice.test.ts) with the name
  // Notes and no colour; the feed board's SORT RULE ranks that owner before every session run, then the session order, then
  // time; needs-you still decides the column (plans/notice-cards.md, "Owner-less cards")
  const setPrefs = (v: string) => { stores.local.set("romp:settings", v); win.dispatchEvent(Object.assign(new Event("storage"), { key: "romp:settings", newValue: v })); };
  const notice = (key: string, t: number, column: string) =>
    ({ ...cardOf("notice:notes:" + key + ":1", "notes", "Notes", "", "A note for everyone " + key, column, { live: false, tree: [], blocked: null, board: "feed", category: column,
       notice: { producer: "cli", key, rev: 1, body: "", attachment: null, actions: [], expiresAt: null, dismissOnAction: false, acted: false } }), t, color: null });
  // ungrouped: one owner-less card older than every session card and one newer, both standing first, in their own time order
  setPrefs(JSON.stringify({ grouped: false, newestFirst: false }));
  const older = notice("old", 5, "completed"); const newer = notice("new", 5000, "completed"); const ask = notice("ask", 5001, "needs_input");
  // a SESSION's needs-you card, older than the Notes ask: a time sort would put it first, the owner rule puts Notes first
  const sAsk = { ...cardOf("s-ask", WEB, "web", "#3366cc", "A question from the web session", "needs_input", { live: true, tree: [], blocked: null }), t: 1 };
  await dispatch(frame([g1, g2, g3, sAsk, older, newer, ask], { working: ["web"] }));
  const c = card("notice:notes:new:1");
  assert.ok(c, "on the board"); assert.equal(c._name.style.display, "none", "no session chip: no session stands behind it (the name node hides; the row keeps its other parts)");
  assert.equal(card("g1")._name.style.display, "", "a session's card keeps its chip");
  assert.equal(colOf("notice:notes:new:1"), "col-completed-list"); assert.equal(colOf("notice:notes:ask:1"), "col-needsInput-list", "needs-you still wins its column");
  const order = (col: string) => Array.from(body.querySelector("#" + col)!.children).filter((n: any) => n.dataset && n.dataset.key).map((n: any) => n.dataset.key as string);
  const done = order("col-completed-list");
  assert.deepEqual(done.slice(0, 2), ["a:notice:notes:old:1", "a:notice:notes:new:1"], "the owner-less cards first, in their own time order (stable): " + done.join(" "));
  assert.ok(done.length > 2 && done.slice(2).every((k) => !k.startsWith("a:notice:notes:")), "the sessions' cards after them");
  assert.deepEqual(order("col-needsInput-list").filter((k) => k.startsWith("a:")), ["a:notice:notes:ask:1", "a:s-ask"], "and first in the needs-you column, above the session's older card");
  // grouped: the Notes run opens the column, its header says Notes, before the order list's first session
  setPrefs(JSON.stringify({ grouped: true, newestFirst: false }));
  await dispatch(frame([g1, g2, g3, sAsk, older, newer, ask], { working: ["web"], order: [WEB] }));
  // the needs-you column holds a Notes card AND a session's card: the Notes run's header stands first, then the session's,
  // and the Notes card precedes every session card (the completed column holds the two Notes cards and stream items alone)
  const heads = Array.from(body.querySelectorAll("#col-needsInput-list .feed-sess-head")).filter((h: any) => !h.classList.contains("sess-exit")) as any[];
  assert.ok(heads.length >= 2, "a header per run in the needs-you column: " + heads.length);
  assert.equal(heads[0].getAttribute("data-fsid"), "notes", "the Notes run heads the column, before the session runs");
  assert.match(heads[0].textContent, /Notes/, "its header says Notes");
  assert.notEqual(heads[1].getAttribute("data-fsid"), "notes", "then a session's run");
  const kids = order("col-needsInput-list").filter((k) => k.startsWith("a:"));
  assert.deepEqual(kids, ["a:notice:notes:ask:1", "a:s-ask"], "its card above the session's, though older: " + kids.join(" "));
  assert.equal(heads[1].getAttribute("data-fsid"), WEB, "the session order's first run follows");
  assert.equal(order("col-completed-list").filter((k) => k.startsWith("a:")).slice(0, 2).join(" "), "a:notice:notes:old:1 a:notice:notes:new:1", "the completed column's Notes run keeps its time order under its header");
  setPrefs(JSON.stringify({ grouped: false, newestFirst: false }));
});

test("a REMOTE host's owner-less card (sid host-prefixed by federation) ranks first, hides its chip, and its Notes header is plain text with no anchor, title, dead class or click", async () => {
  // round two of PR 1831: federation's prefixInbound hands the pane "TESTHOST:notes" and "TESTHOST:Notes"; the owner test strips
  // the host the way federation adds it (host-prefix bareId), so the rank, the chip and the header agree across hosts; the
  // header offered to revive a session named notes that never existed on the remote host
  const setPrefs = (v: string) => { stores.local.set("romp:settings", v); win.dispatchEvent(Object.assign(new Event("storage"), { key: "romp:settings", newValue: v })); };
  const remote = { ...cardOf("TESTHOST:notice:notes:r1:1", "TESTHOST:notes", "TESTHOST:Notes", "", "A note from the other machine", "needs_input", { live: false, tree: [], blocked: null, board: "feed", category: "needs_input",
    notice: { producer: "cli", key: "r1", rev: 1, body: "", attachment: null, actions: [], expiresAt: null, dismissOnAction: false, acted: false } }), t: 7000, color: null };
  const sAsk = { ...cardOf("s-ask2", WEB, "web", "#3366cc", "A question from the web session", "needs_input", { live: true, tree: [], blocked: null }), t: 1 };
  setPrefs(JSON.stringify({ grouped: true, newestFirst: false }));
  await dispatch(frame([g1, g2, g3, sAsk, remote], { working: ["web"], order: [WEB] }));
  const c = card("TESTHOST:notice:notes:r1:1");
  assert.ok(c, "on the board"); assert.equal(c._name.style.display, "none", "no session chip for the remote owner-less card");
  const order = (col: string) => Array.from(body.querySelector("#" + col)!.children).filter((n: any) => n.dataset && n.dataset.key).map((n: any) => n.dataset.key as string);
  assert.deepEqual(order("col-needsInput-list").filter((k) => k.startsWith("a:")), ["a:TESTHOST:notice:notes:r1:1", "a:s-ask2"], "the remote Notes run first, above the session's older card");
  const heads = Array.from(body.querySelectorAll("#col-needsInput-list .feed-sess-head")).filter((h: any) => !h.classList.contains("sess-exit")) as any[];
  assert.equal(heads[0].getAttribute("data-fsid"), "TESTHOST:notes", "its header heads the column");
  const nm = heads[0]._name;
  assert.equal(nm.tagName, "SPAN", "plain text: no anchor"); assert.equal(nm.className, "fname-plain");
  assert.equal(nm.getAttribute("title"), null, "no title"); assert.ok(!nm.classList.contains("dead"), "no dead class"); assert.equal(nm.onclick, null, "no click: nothing to open or revive");
  assert.match(nm.textContent, /Notes/, "the host-prefixed name reads through: " + nm.textContent);
  assert.equal(heads[1]._name.tagName, "A", "a session's header keeps its anchor"); assert.equal(heads[1]._name.getAttribute("title"), "open this session");
  setPrefs(JSON.stringify({ grouped: false, newestFirst: false }));
});

test("two hosts' owner-less cards under ONE key both render (the inbound prefix tells their ids apart), and an owner-less title click opens the card's own modal: the notice, no session gesture", async () => {
  // round three of PR 1831, medium B: federation prefixes a remote notice card's item id like its sid, so the local and the remote
  // Notes cards under the same hand-picked key are two elements (the remote one arrives through prefixInbound here, with the SAME
  // bare id as the local one: round four, low); medium A: the title click used to post showOnTimeline with sid notes and the
  // kernel offered to revive a session that never existed. Round four, medium 2: the modal it opens shows the NOTICE (title,
  // producer, body, actions) in place of the goal tree a notice never has, and offers no session gesture (Follow up, Check
  // status and Continue hidden; Clear stays); every assertion is scoped to the modal element.
  const setPrefs = (v: string) => { stores.local.set("romp:settings", v); win.dispatchEvent(Object.assign(new Event("storage"), { key: "romp:settings", newValue: v })); };
  setPrefs(JSON.stringify({ grouped: false, newestFirst: false }));
  const mk = (title: string, body: string, t: number) => ({ ...cardOf("notice:notes:same:1", "notes", "Notes", "", title, "completed", { live: false, tree: [], blocked: null, board: "feed", category: "completed",
    notice: { producer: "cli", key: "same", rev: 1, body, attachment: null, actions: [{ label: "Ping", route: "/send", body: { text: "ping" } }], expiresAt: null, dismissOnAction: false, acted: false } }), t, color: null });
  const local = mk("A local note", "Remember the standup moved to half past ten.", 10);
  const remoteIn = prefixInbound("TESTHOST", { type: "feed", asks: [mk("A remote note", "", 11)], sessions: [], working: [], awaiting: [], order: [] });
  const remote = remoteIn.asks[0];
  assert.equal(remote.itemId, "TESTHOST:notice:notes:same:1", "the same bare id, told apart by the host on the way in");
  await dispatch(frame([g1, local, remote], { working: ["web"] }));
  assert.ok(card("notice:notes:same:1"), "the local card"); assert.ok(card("TESTHOST:notice:notes:same:1"), "and the remote one, a second element");
  assert.equal(card("notice:notes:same:1")._title.textContent, "A local note"); assert.equal(card("TESTHOST:notice:notes:same:1")._title.textContent, "A remote note", "neither overwrote the other");
  const sent = posted.length;
  card("notice:notes:same:1")._title.onclick(ev);
  assert.equal(posted.length, sent, "the title click on an owner-less card posts nothing (no showOnTimeline, no openSession)");
  const modal = body.querySelector("#feed-modal") as any;
  assert.ok(modal, "it opens the card's modal instead");
  const q = (sel: string) => modal.querySelector(sel) as any;
  assert.equal(q("#feed-modal-title").style.display, ""); assert.equal(q("#feed-modal-title").textContent, "A local note", "the modal's title is the card's");
  assert.equal(q("#feed-modal-title").onclick, null, "the title locates nothing (a notice has no chat turn)");
  const mb = q("#feed-modal-body");
  assert.match(mb.querySelector(".fask-nbody")?.textContent ?? "", /Remember the standup moved to half past ten\./, "the body shows the notice's words");
  assert.equal(mb.querySelector(".fask-nprod")?.textContent, "via cli", "and the producer line");
  const mbtns = mb.querySelectorAll(".fask-nactions button");
  assert.equal(mbtns.length, 1); assert.equal(mbtns[0].textContent, "Ping", "and the card's action");
  assert.equal(q("#feed-modal-follow").style.display, "none", "no Follow up"); assert.equal(q("#feed-modal-status").style.display, "none", "no Check status");
  assert.equal(q("#feed-modal-continue").style.display, "none", "no Continue"); assert.equal(q("#feed-modal-clear").style.display, "", "Clear stays");
  const agent = q("#feed-modal-agent");
  assert.equal(agent.onclick, null, "the header's name opens no session"); assert.ok(agent.classList.contains("fname-plain")); assert.ok(!agent.classList.contains("dead"), "and is never struck");
  // the modal's action posts once with the card's sid, latches, and lets go on the kernel's refusal
  const sent2 = posted.length;
  mbtns[0].onclick(ev);
  assert.deepEqual(posted.slice(sent2).filter((m) => m.type === "noticeAction"), [{ type: "noticeAction", itemId: "notice:notes:same:1", sid: "notes", kind: "send", body: { text: "ping" } }]);
  assert.equal(mbtns[0].disabled, true, "latched");
  await dispatch({ type: "noticeActionDone", itemId: "notice:notes:same:1", ok: false, error: "an owner-less card has no actions" });
  const after = (body.querySelector("#feed-modal-body") as any).querySelectorAll(".fask-nactions button");
  assert.equal(after.length, 1); assert.equal(after[0].disabled, false, "re-armed on the answer (the face is rebuilt)");
  assert.ok(body.querySelector("#feed-modal"), "a refusal keeps the modal open");
  q(".feed-modal-close").onclick(ev);
  assert.equal(body.querySelector("#feed-modal"), null, "closed");
  setPrefs(JSON.stringify({ grouped: false, newestFirst: false }));
});

test("a REMOTE notice card's answer names the owning kernel's bare id: the inbound prefix dresses it too, so a dismissing card leaves on the answer and a refused one re-arms", async () => {
  // round four of PR 1831, medium 1: prefixInbound covered a row's itemId and never a reply's, so a remote card's noticeActionDone
  // missed the pane's map (keyed host:notice:...): the card stayed on the board with its button latched until the next push
  const HOSTB = "HOSTB";
  const rn = (key: string, dismiss: boolean) => cardOf("notice:" + WEB + ":" + key + ":1", WEB, "web", "#3366cc", "A remote figure is ready (" + key + ")", "completed", { live: false, tree: [], blocked: null,
    notice: { producer: "figure", key, rev: 1, body: "", attachment: null, actions: [{ label: "Send again", route: "/send", body: { text: "again" } }], expiresAt: null, dismissOnAction: dismiss } });
  const rf = prefixInbound(HOSTB, { type: "feed", asks: [rn("leaves", true), rn("stays", false)], sessions: [{ sid: WEB, name: "web", color: g1.color }], working: [], awaiting: [], stateUnknown: [], order: [WEB] });
  const leaves = HOSTB + ":notice:" + WEB + ":leaves:1", stays = HOSTB + ":notice:" + WEB + ":stays:1";
  assert.deepEqual(rf.asks.map((a: any) => a.itemId), [leaves, stays], "the rows' ids wear the host (round three)");
  await dispatch(frame([g1, g2, g3, ...rf.asks], { working: ["web"], sessions: [...frame([]).sessions, ...rf.sessions] }));
  assert.ok(card(leaves)); assert.ok(card(stays));
  const b1 = card(leaves)._nActions.querySelectorAll("button")[0];
  const sent = posted.length;
  b1.onclick(ev);
  assert.deepEqual(posted.slice(sent).filter((m) => m.type === "noticeAction").map((m) => [m.itemId, m.sid]), [[leaves, HOSTB + ":" + WEB]], "the gesture carries the prefixed ids (routeOutbound strips them)");
  assert.equal(b1.disabled, true, "latched");
  // the owning kernel answers with ITS id, bare; the socket's inbound transform dresses it the way it dressed the row
  await dispatch(prefixInbound(HOSTB, { type: "noticeActionDone", itemId: "notice:" + WEB + ":leaves:1", ok: true, error: "" }));
  assert.equal(card(leaves) === null, true, "the remote dismissing card left on the owning kernel's answer");
  const b2 = card(stays)._nActions.querySelectorAll("button")[0];
  b2.onclick(ev); assert.equal(b2.disabled, true);
  await dispatch(prefixInbound(HOSTB, { type: "noticeActionDone", itemId: "notice:" + WEB + ":stays:1", ok: false, error: "no running backend owns web" }));
  assert.ok(card(stays), "a refused card stays"); assert.equal(b2.disabled, false, "and its button let go on the answer, not on the next push");
});

test("on a data board, its needs-you card passes a tag lens its session is outside of (the card's OWN board decides), while a plain card of that session is hidden", async () => {
  // the 1861 read (medium): the lens read isNeedsYou against the FEED board, so a card in a data board's needs-you category was
  // dropped under a tag lens while the app badge still said one card needs you; the lens asks the card's own board. Since phase
  // four the board's cards show on the board's own view, so the lens is exercised there (the menu's Board row picks it).
  const HOT = { id: "urgent", title: "Urgent", categories: [{ id: "hot", title: "Hot", chip: "blocked" }, { id: "cool", title: "Cool", chip: "neutral" }],
    defaultCategory: "cool", rules: [], sort: { key: "t", dir: "desc" }, subSorts: [], groupBy: null, order: [], notify: ["hot"], needsYou: "hot", kinds: ["notice"] };
  const hot = cardOf("notice:" + API + ":decide:1", API, "api", "#cc6633", "Decide the retry policy", "needs_input", { live: false, tree: [], blocked: null, board: "urgent", category: "hot",
    notice: { producer: "cli", key: "decide", rev: 1, body: "", attachment: null, actions: [], expiresAt: null, dismissOnAction: false } });
  const cool = cardOf("notice:" + API + ":later:1", API, "api", "#cc6633", "A cool note", "completed", { live: false, tree: [], blocked: null, board: "urgent", category: "cool",
    notice: { producer: "cli", key: "later", rev: 1, body: "", attachment: null, actions: [], expiresAt: null, dismissOnAction: false } });
  const views = { tags: [{ id: "t1", name: "infra", members: [WEB] }] };   // web is tagged infra; api is outside every tag
  await dispatch(frame([g1, hot, cool], { boards: { urgent: HOT }, views }));
  (body.querySelector("#feed-viewbtn") as any).onclick(ev);
  const row = (body.querySelector(".feed-viewmenu") as any).querySelectorAll('[role="menuitemradio"]').find((x: any) => x.dataset.board === "urgent"); assert.ok(row, "the Urgent row");
  row.onclick(ev); await settle();
  assert.equal(colOf("notice:" + API + ":decide:1"), "col-hot-list"); assert.equal(colOf("notice:" + API + ":later:1"), "col-cool-list", "both on the board under All");
  win.dispatchEvent(Object.assign(new Event("storage"), { key: "romp:feedTags-set", newValue: JSON.stringify({ lens: { tags: ["infra"] }, t: 1 }) }));
  await settle();
  assert.equal(card("notice:" + API + ":later:1"), null, "the lens hides a plain card of a session outside it");
  assert.ok(card("notice:" + API + ":decide:1"), "the needs-you card of the same session stays: its OWN board's badge category passes every lens");
  win.dispatchEvent(Object.assign(new Event("storage"), { key: "romp:feedTags-set", newValue: JSON.stringify({ lens: { all: true }, t: 2 }) }));
  await settle();
  assert.ok(card("notice:" + API + ":later:1")); assert.ok(card("notice:" + API + ":decide:1"));
  (body.querySelector("#feed-viewbtn") as any).onclick(ev);
  (body.querySelector(".feed-viewmenu") as any).querySelectorAll('[role="menuitemradio"]').find((x: any) => x.dataset.board === "feed").onclick(ev); await settle();
  await dispatch(frame([g1, g2, g3]));
});

// ── the board view switch (plans/card-boards.md, phase four, section 8) ─────────────────────────────────────────────
const FIG_BOARD = { id: "figures", title: "Figures", categories: [{ id: "new", title: "New", chip: "neutral" }, { id: "kept", title: "Kept", chip: "working" }],
  defaultCategory: "new", rules: [], sort: { key: "t", dir: "desc" }, subSorts: [], groupBy: null, order: [], notify: [], needsYou: null, kinds: ["notice"] };
const figCard = (key: string, title: string, category: string, t: number, board = "figures") =>
  ({ ...cardOf("notice:" + WEB + ":" + key + ":1", WEB, "web", "#3366cc", title, "completed", { live: false, tree: [], blocked: null, board, category,
    notice: { producer: "figure", key, rev: 1, body: "", attachment: null, actions: [], expiresAt: null, dismissOnAction: false } }), t });
const viewBtn = () => body.querySelector("#feed-viewbtn") as any;
const openMenu = () => { viewBtn().onclick(ev); return body.querySelector(".feed-viewmenu") as any; };
const radios = (menu: any) => menu.querySelectorAll('[role="menuitemradio"]').map((r: any) => [r.dataset.board, r.getAttribute("aria-checked")]);
const pick = (menu: any, id: string) => { const r = menu.querySelectorAll('[role="menuitemradio"]').find((x: any) => x.dataset.board === id); assert.ok(r, "a row for " + id); r.onclick(ev); };
const colsRoot = () => body.querySelector("#feed-cols") as any;
const viewBoard = () => JSON.parse(stores.local.get("romp:feedview") || "{}").board;

test("the View menu's Board rows show one board at a time: a data board's cards under its own categories in its own order, the feed's cards off it, the pick persisted, and the feed back byte-for-byte", async () => {
  const f1 = figCard("fig1", "The accuracy figure", "new", K0 - 100), f2 = figCard("fig2", "The loss figure", "kept", K0 - 50), f3 = figCard("fig3", "The newest figure", "new", K0 - 10);
  const lost = { ...figCard("lost", "A card naming a board nobody knows", "x", K0 - 30, "gone"), sid: API, name: "api" };
  await dispatch(frame([g1, g2, f1, f2, f3, lost], { boards: { figures: FIG_BOARD } }));
  // the View menu: the four view rows, then a radio per board the frame carries, the feed current
  let menu = openMenu(); assert.ok(menu, "the menu opened");
  assert.deepEqual(radios(menu), [["feed", "true"], ["figures", "false"]], "a Board row per board the frame carries, the feed current");
  assert.equal(menu.querySelectorAll(".ctx-item").filter((r: any) => !r.classList.contains("ctx-board")).length, 4, "the four view rows stand");   // (the stand-in's selector engine has no :not)
  // on the feed (the default): the data board's cards are OFF the feed (their board's view shows them); a card naming a board nobody knows is the feed's, loudly
  assert.equal(colsRoot().dataset.board, "feed", "the columns root names the board it shows");
  assert.equal(card(f1.itemId), null, "a Figures card is not on the feed"); assert.equal(card(f2.itemId), null); assert.equal(card(f3.itemId), null);
  assert.equal(colOf(lost.itemId), "col-asks-list", "an unknown board's card files under the feed's default column"); assert.equal(card(lost.itemId)._nProd.textContent, "via figure · on an unknown board (gone)", "never a silent drop");
  // pick Figures: the columns come down and rebuild as the board's; its cards sit under their categories, newest first (its sort); no feed card, no unknown-board card
  pick(menu, "figures"); await settle();
  assert.equal(body.querySelector(".feed-viewmenu"), null, "a pick closes the menu");
  assert.equal(colsRoot().dataset.board, "figures");
  assert.equal(body.querySelector("#col-asks-list"), null, "the feed's columns are gone"); assert.ok(body.querySelector("#col-new-list")); assert.ok(body.querySelector("#col-kept-list"));
  assert.deepEqual(body.querySelectorAll("#feed-cols .feed-col-name").map((h: any) => [h.textContent, h.className]),
    [["New", "feed-col-name fcol-chip fcol-chip-neutral fcol-static"], ["Kept", "feed-col-name fcol-chip fcol-chip-working fcol-static"]], "the board's titles and chips, in its order; static (no drag) on a data board");
  assert.deepEqual((body.querySelector("#col-new-list") as any).children.map((c: any) => c.dataset.key), ["a:" + f3.itemId, "a:" + f1.itemId], "newest first: the board's sort, not the feed's preference");
  assert.equal(colOf(f2.itemId), "col-kept-list");
  assert.equal(card("g1"), null, "a feed card is not on the Figures board"); assert.equal(card(lost.itemId), null, "nor a card of an unknown board");
  assert.equal(body.querySelectorAll("#feed-cols .feed-sess-head").length, 0, "no session runs: the board groups nothing");
  assert.equal(viewBoard(), "figures", "the pick persists in the feed's own view state");
  assert.match(viewBtn().title, /showing the Figures board/);
  // back to the feed: the three columns return with every feed card, the pick cleared
  menu = openMenu(); assert.deepEqual(radios(menu), [["feed", "false"], ["figures", "true"]]);
  pick(menu, "feed"); await settle();
  assert.equal(colsRoot().dataset.board, "feed"); assert.ok(card("g1")); assert.ok(card("g2")); assert.equal(card(f1.itemId), null); assert.equal(colOf("g1"), "col-asks-list");
  assert.equal(viewBoard(), ""); assert.doesNotMatch(viewBtn().title, /board/);
  // a pick the frame cannot honour: the next frame carries no boards, the feed shows, the button says so, and the pick stands
  menu = openMenu(); pick(menu, "figures"); await settle(); assert.equal(colsRoot().dataset.board, "figures");
  await dispatch(frame([g1, g2, f1, f2, f3, lost], {}));
  assert.equal(colsRoot().dataset.board, "feed", "the feed shows"); assert.ok(card("g1"));
  assert.match(viewBtn().title, /board figures is not on this frame, so the feed shows/);
  assert.equal(card(f1.itemId)._nProd.textContent, "via figure · on an unknown board (figures)", "its cards read as an unknown board's until the frame carries it");
  assert.equal(viewBoard(), "figures", "the pick stands: the board comes back on its own");
  menu = openMenu(); assert.equal(menu.querySelectorAll('[role="menuitemradio"]').length, 0, "with the feed alone the menu is exactly what it was"); viewBtn().onclick(ev);
  await dispatch(frame([g1, g2, f1, f2, f3, lost], { boards: { figures: FIG_BOARD } }));
  assert.equal(colsRoot().dataset.board, "figures", "back on the next frame carrying it");
  // restore the feed for the tests below
  menu = openMenu(); pick(menu, "feed"); await settle(); assert.equal(colsRoot().dataset.board, "feed");
  await dispatch(frame([g1, g2, g3]));
});

test("on a session-grouped data board with the focused section ON, the section stays the feed's (hidden), the board's cards reconcile and no render throws; a data board's fold is keyed per board and its chips wear no drag affordance", async () => {
  // the 1886 read, HIGH: a data board with groupBy session took the grouping branch and handed focusedEntries buckets keyed by
  // its categories while the section read the feed's three keys: a TypeError on every render, three empty columns after a
  // reload. The section is the feed's (plans/card-boards.md section 4); a board opting in is phase five's. Medium 2: a fold on a
  // data board is stored as <board>:<category>; medium 3: a data board's chip has no drag affordance (its order is its definition's).
  const GRP = { id: "reviews", title: "Reviews", categories: [{ id: "open", title: "Open", chip: "blocked" }, { id: "done", title: "Done", chip: "completed" }],
    defaultCategory: "open", rules: [], sort: { key: "t", dir: "desc" }, subSorts: [], groupBy: "session", order: [], notify: [], needsYou: "open", kinds: ["notice"] };
  const r1 = { ...cardOf("notice:" + WEB + ":r1:1", WEB, "web", "#3366cc", "Review the retry policy", "needs_input", { live: false, tree: [], blocked: null, board: "reviews", category: "open",
    notice: { producer: "cli", key: "r1", rev: 1, body: "", attachment: null, actions: [], expiresAt: null, dismissOnAction: false } }), t: K0 - 20 };
  const r2 = { ...cardOf("notice:" + API + ":r2:1", API, "api", "#cc6633", "Reviewed the schema", "completed", { live: false, tree: [], blocked: null, board: "reviews", category: "done",
    notice: { producer: "cli", key: "r2", rev: 1, body: "", attachment: null, actions: [], expiresAt: null, dismissOnAction: false } }), t: K0 - 10 };
  const setPrefs = (v: string) => { stores.local.set("romp:settings", v); win.dispatchEvent(Object.assign(new Event("storage"), { key: "romp:settings", newValue: v })); };
  setPrefs(JSON.stringify({ grouped: true, newestFirst: false }));   // grouping on: the board's groupBy is what makes the runs
  await dispatch(frame([g1, g2, r1, r2], { boards: { reviews: GRP } }));
  // the focused section ON, the chat focused on web (the frame the kernel relays); the row by its place (the fourth view row), the same in every engine
  await dispatch({ type: "activeChat", id: WEB });
  const viewRows = (m: any) => m.querySelectorAll(".ctx-item").filter((r: any) => !r.classList.contains("ctx-board"));
  let menu = openMenu(); const focusRow = viewRows(menu)[3]; assert.ok(focusRow, "the focused-session row");
  focusRow.onclick(ev); await settle();
  assert.ok(body.querySelector("#feed-focus"), "the section shows on the feed");
  // pick the session-grouped board: the section hides, the board's cards reconcile under its columns with session headers, nothing throws
  menu = openMenu(); pick(menu, "reviews"); await settle();
  assert.equal(colsRoot().dataset.board, "reviews");
  assert.equal(body.querySelector("#feed-focus"), null, "the focused section is the feed's: hidden on a data board");
  assert.equal(colOf(r1.itemId), "col-open-list"); assert.equal(colOf(r2.itemId), "col-done-list", "the board's cards reconcile");
  assert.ok(body.querySelectorAll("#feed-cols .feed-sess-head").length >= 2, "the board groups by session: a header per run");
  await dispatch(frame([g1, g2, r1, r2], { boards: { reviews: GRP } }));   // a second frame: the render that used to throw
  assert.equal(colOf(r1.itemId), "col-open-list", "still reconciled on the next frame");
  // medium 3: a data board's chip is static, the feed's drags
  const chips = body.querySelectorAll("#feed-cols .feed-col-name");
  assert.ok(chips.every((c: any) => c.classList.contains("fcol-static") && !c.getAttribute("title")), "no drag affordance on a data board's chips");
  // medium 2: fold the Open column: the fold is keyed reviews:open in the view state and the column wears col-collapsed
  const fold = body.querySelector("#feed-cols .feed-col.col-open .fcol-fold") as any; assert.ok(fold, "the fold caret");
  fold.dispatchEvent(new Event("click")); await settle();
  assert.ok((body.querySelector("#feed-cols .feed-col.col-open") as any).classList.contains("col-collapsed"), "folded");
  assert.deepEqual(JSON.parse(stores.local.get("romp:feedview")!).cols.filter((k: string) => k.includes(":")), ["reviews:open"], "the fold is the board's own key");
  fold.dispatchEvent(new Event("click")); await settle();
  assert.ok(!(body.querySelector("#feed-cols .feed-col.col-open") as any).classList.contains("col-collapsed"), "unfolded");
  // back to the feed: the section returns, the feed's chips drag
  menu = openMenu(); pick(menu, "feed"); await settle();
  assert.ok(body.querySelector("#feed-focus"), "the section is back on the feed");
  assert.ok(body.querySelectorAll("#feed-cols .feed-col-name").every((c: any) => c.getAttribute("title") === "drag to reorder"), "the feed's chips drag");
  menu = openMenu(); viewRows(menu)[3].onclick(ev); await settle();
  await dispatch({ type: "activeChat", id: null });
  setPrefs(JSON.stringify({ grouped: false, newestFirst: false }));
  await dispatch(frame([g1, g2, g3]));
});

// ── the predicted move on a card that carries its category (plans/card-boards.md, phase two, round two) ──────────────────
// Every card the kernel builds carries `category` since phase two and askColumn reads it first; the optimistic follow-up
// move predicted `column` alone, so a Continue, a reply or a Check status left the card in Blocked (with the re-check
// styling) until the kernel re-filed it. The four follow-move tests are source pins that never boot feed.ts, which is how
// it escaped them; this one boots it.
test("Continue on a category-carrying card predicts the move to Working: the prediction writes the category too", async () => {
  const others = Array.from(body.querySelectorAll(".fitem")).map((c: any) => c._it).filter(Boolean);
  const g9 = cardOf("g9", WEB, "web", "#3366cc", "Decide the notes-api retry policy", "needs_input", { board: "feed", category: "needs_input" });
  await dispatch(frame([g9, ...others], { working: ["api"] }));   // web is live and waiting on you
  assert.equal(colOf("g9"), "col-needsInput-list", "the kernel filed it under Blocked by its category");
  const cont = card("g9")._cont;
  assert.equal(cont.style.display, ""); assert.equal(cont.disabled, false);
  const sent = posted.length;
  cont.onclick(ev);
  assert.deepEqual(posted.slice(sent).filter((m) => m.type === "askFollowUp"), [{ type: "askFollowUp", itemId: "g9", sid: WEB, cont: true }]);
  assert.equal(colOf("g9"), "col-asks-list", "the predicted move: the card goes to Working ahead of the kernel, category and column alike");
  const shown = card("g9")._it;
  assert.equal(shown.category, "working", "the rendered copy's category is the prediction");
  assert.equal((g9 as any).category, "needs_input", "the frame's own object is untouched (the copy-on-write rule)");
  await dispatch(frame([g9, ...others], { working: ["api"] }));   // a re-emit of the same objects: nothing decided
  assert.equal(colOf("g9"), "col-asks-list", "the prediction holds through a re-emit");
  await dispatch(frame([{ ...g9, column: "working", category: "working", followupPending: true, followupAt: K0 }, ...others], { working: ["web", "api"] }));
  assert.equal(colOf("g9"), "col-asks-list", "the kernel's re-filing confirms it");
});

// ── phase three of the boards: the kernel's fan-back on a category-carrying card, and a card on a data-defined board ────────
test("the kernel's cardPredict fan-back moves a category-carrying card to Working through askColumn (the 1837 round-two read, low 1)", async () => {
  const others = Array.from(body.querySelectorAll(".fitem")).map((c: any) => c._it).filter(Boolean).filter((it: any) => it.itemId !== "g9");
  // the card whose category disagrees with its column (a data-defined board's, or a kernel that files by category where the
  // column keeps the feed's word): the renderer files it by the category, so the fan-back must read the same field
  const g10 = cardOf("g10", WEB, "web", "#3366cc", "Approve the notes-api schema change", "working", { board: "feed", category: "needs_input" });
  await dispatch(frame([g10, ...others], { working: ["api"] }));
  assert.equal(colOf("g10"), "col-needsInput-list", "filed by its category");
  await dispatch({ type: "cardPredict", ids: ["g10"], flavor: "followup" });   // a reply fired in the chat: the kernel says so ahead of its rebuild
  assert.equal(colOf("g10"), "col-asks-list", "the fan-back predicted the move: Working by the card's category, not its column");
  await dispatch(frame([{ ...g10, column: "working", category: "working", followupPending: true, followupAt: K0 }, ...others], { working: ["web", "api"] }));
  assert.equal(colOf("g10"), "col-asks-list");
});

test("a notice card on a data-defined board is not on the feed: its own board's view shows it (phase four); a card naming a board nobody knows is the feed's, loudly", async () => {
  const FIG = { id: "figures", title: "Figures", categories: [{ id: "new", title: "New", chip: "neutral" }], defaultCategory: "new", rules: [], sort: { key: "t", dir: "desc" }, subSorts: [], groupBy: null, order: [], notify: [], needsYou: null, kinds: ["notice"] };
  const onFig = cardOf("notice:" + WEB + ":sweep:1", WEB, "web", "#3366cc", "The sweep finished", "completed", { live: false, tree: [], blocked: null, board: "figures", category: "new",
    notice: { producer: "figure", key: "sweep", rev: 1, body: "", attachment: null, actions: [], expiresAt: null, dismissOnAction: false } });
  const lost = cardOf("notice:" + WEB + ":lost:1", WEB, "web", "#3366cc", "A card of a board nobody knows", "completed", { live: false, tree: [], blocked: null, board: "gone", category: "x",
    notice: { producer: "figure", key: "lost", rev: 1, body: "", attachment: null, actions: [], expiresAt: null, dismissOnAction: false } });
  await dispatch(frame([g1, onFig, lost], { boards: { figures: FIG } }));
  assert.equal(card("notice:" + WEB + ":sweep:1"), null, "a data board's card is off the feed (phase four): its board's view shows it");
  assert.equal(colOf("notice:" + WEB + ":lost:1"), "col-asks-list", "an unknown board's card files under the feed's default column");
  assert.equal(card("notice:" + WEB + ":lost:1")._nProd.textContent, "via figure · on an unknown board (gone)", "and says so beside the producer, never a silent drop");
  await dispatch(frame([g1, g2, g3]));
});

const remoteWorld = async (hooks: any) => {
  hooks._resetClearGestureStateForTests();
  const g2it = card("g2")?._it ?? cardOf("g2", API, "api", "#cc6633", "a second card of api's", "working", { live: true, tree: [] });   // read after a dispatch when this test runs alone
  const R = "22222222-3333-4444-5555-666666666666";
  const remote = cardOf(R + ":g1", "TESTHOST:" + R, "TESTHOST:api", "#cc6633", "a remote host's card", "needs_input", { live: true, tree: [] });
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], sessions: FED_SESSIONS })); mock.timers.tick(700);
  return { g2it, R, remote };
};
const FED_SESSIONS = [...frame([]).sessions, { sid: "TESTHOST:22222222-3333-4444-5555-666666666666", name: "TESTHOST:api", color: null }];   // the merged payload lists the remote kernel's session while it is attached, cards or none

const B = (local: number, remote: number) => ({ buildIds: { "": local, TESTHOST: remote }, sessions: FED_SESSIONS });
const BA = (local: number, remote: number) => ({ ...B(local, remote), ackHosts: ["", "TESTHOST"] });   // both kernels account for their undos with a build floor (round fifteen); B() alone is the older kernels' road   // a merged payload's per-kernel builds, with the remote kernel's session listed

test("a federated pane: Undo is the round trip (the round-nine verifier's ruling on PR 1967): mixed clears cache no entry, Undo posts the request and restores nothing optimistically under the working cue, a stale held frame moves no card, a suppression ends on the card's own kernel's newer build listing it, a remote kernel's refusal re-shows its card by id", async (t) => {
  t.after(() => mock.timers.reset());   // registered with the test context (the second contributor's review): a red in this test no longer leaves the timers enabled for every later one
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const stackIds = hooks._clearedStackIdsForTests as () => string[][];
  const sent0 = posted.length;
  const { g2it, R, remote } = await remoteWorld(hooks);
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(1, 1) })); mock.timers.tick(700);   // the builds this page has seen
  card(R + ":g1")._clr.onclick(ev);                                         // a remote card's clear: its kernel has not confirmed it yet
  card("g3")._clr.onclick(ev);                                              // then a local clear: the most recent, so federation sends the undo to the local kernel
  mock.timers.tick(700);
  assert.deepEqual(stackIds(), [], "a federated pane caches no entry: stamps across kernels do not order");
  assert.ok(!card("g3") && !card(R + ":g1"), "the cleared cards are off");
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev);
  assert.equal(posted.slice(sent0).filter((m) => m.type === "undoClear").length, 1, "the request goes out");
  assert.ok(!card("g3") && !card(R + ":g1"), "nothing restored optimistically, no suppression released at the click"); assert.ok(undo.classList.contains("undo-busy"), "the working cue: the payload restores");
  await dispatch({ type: "undoRouted", hosts: [""] });                       // federation's word: the undo went to the local kernel (the most recent clear's); the send's moment is build 1 there
  // a stale merged frame, built before the send on both kernels (the remote's last held frame still lists its card, the local push still lists g3): no card moves
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(1, 1) })); mock.timers.tick(700);
  assert.ok(!card("g3") && !card(R + ":g1"), "a frame built before the send is no evidence: both cards stay off (round twelve; before: the local card came back on it)");
  // the local kernel's newer build lists g3: the evidence it was restored; the remote's held frame is still the old one
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(2, 1) })); mock.timers.tick(700);
  assert.ok(card("g3"), "the local card shows on its kernel's newer build"); assert.ok(!card(R + ":g1"), "the remote card keeps its suppression: the undo did not go to its kernel, and its kernel's build is the old one");
  await dispatch(frame([g1, g2it, g3], { working: ["web"], ...B(2, 2) })); mock.timers.tick(700);      // the confirming frame: the remote kernel took the clear
  assert.ok(!card(R + ":g1"), "and it stays off: no card moved twice"); assert.ok(!undo.classList.contains("undo-busy"), "the cue clears with the payload");
  // the remote kernel refused an undo on the round-trip road: the account frame from a kernel the undo went to clears the cue at once
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: ["TESTHOST"] });
  assert.ok(undo.classList.contains("undo-busy"));
  await dispatch({ type: "err", host: "TESTHOST", op: "undoClear", sid: "TESTHOST:" + R, itemId: "", itemIds: [], batches: [], owedBatch: [], batchesTotal: 0, title: "That undo did not land", text: "the clears log refused" });
  assert.ok(!undo.classList.contains("undo-busy"), "the account frame is the event the cue waits for (round eleven), from a kernel the undo went to (round twelve)");
  // the remote kernel refused the remote card's clear: its account re-shows that card by its id and nothing else
  await dispatch({ type: "err", host: "TESTHOST", op: "askClear", sid: "TESTHOST:" + R, itemId: R + ":g1", itemIds: [R + ":g1"], batches: [], owedBatch: [], batchesTotal: 0, title: "That clear did not land", text: "Nothing was cleared." });
  mock.timers.tick(700);
  assert.ok(card(R + ":g1"), "the remote card is back, stack or no stack");
  await dispatch({ type: "err", op: "clearAll", sid: WEB, itemId: "", itemIds: [], batches: [["g1", "g2"], ["g3"]], owedBatch: [], batchesTotal: 2, title: "That clear did not fully land for web", text: "The cards are off the board; the session's own record of them could not be written." });
  mock.timers.tick(700);
  assert.deepEqual(stackIds(), [], "no stack on a federated pane, whatever a frame carries");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("a federated pane, two clears on one kernel then Undo: the kernel restores the newer batch alone; a stale held frame listing both cards releases neither, and the kernel's newer build shows exactly the card it restored (the round-eleven verifier's HIGH on PR 1967)", async (t) => {
  t.after(() => mock.timers.reset());   // registered with the test context (the second contributor's review): a red in this test no longer leaves the timers enabled for every later one
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const sent0 = posted.length;
  const { g2it, remote } = await remoteWorld(hooks);
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(1, 1) })); mock.timers.tick(700);
  card("g3")._clr.onclick(ev);                                              // X: the older clear, its confirming frame not yet applied
  card("g1")._clr.onclick(ev);                                              // Y: the newer clear, the batch the undo restores
  mock.timers.tick(700);
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: [""] });
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(1, 1) })); mock.timers.tick(700);   // a stale held frame, built before the send, still listing X
  assert.ok(!card("g3") && !card("g1"), "a stale held frame releases nothing (before: both suppressions went at the click and X repainted for a beat)");
  await dispatch(frame([g1, g2it, remote], { working: ["web"], ...B(2, 1) })); mock.timers.tick(700);       // the kernel's newer build: Y restored, X still cleared
  assert.ok(card("g1"), "Y shows on its kernel's newer build"); assert.ok(!card("g3"), "X stays off: the kernel restored the newer batch alone");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("a federated pane, the two-Undo shape: a local clear, a remote clear, Undo (to the remote kernel, the most recent clear's), Undo (to the local kernel: the send consumed the routing): each card shows when its own kernel's newer build lists it (the eleventh executed review of PR 1967)", async (t) => {
  t.after(() => mock.timers.reset());   // registered with the test context (the second contributor's review): a red in this test no longer leaves the timers enabled for every later one
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const sent0 = posted.length;
  const { g2it, R, remote } = await remoteWorld(hooks);
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(1, 1) })); mock.timers.tick(700);
  card("g3")._clr.onclick(ev);                                              // a local clear
  card(R + ":g1")._clr.onclick(ev);                                         // then a remote card's clear: the most recent
  mock.timers.tick(700);
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: ["TESTHOST"] });       // the first Undo: the remote kernel's
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(1, 2) })); mock.timers.tick(700);   // the remote kernel's newer build lists its card; the local copy of g3 is stale
  assert.ok(card(R + ":g1"), "the remote card shows: its kernel restored it"); assert.ok(!card("g3"), "the local card stays off: the undo did not go to its kernel");
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: [""] });              // the second Undo: the local kernel alone (the send consumed the routing)
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(2, 2) })); mock.timers.tick(700);
  assert.ok(card("g3") && card(R + ":g1"), "both cards show, each on its own kernel's newer build (before: the page released by the previous clear's kernel on both presses and hid the local card until a reload)");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("a federated pane, the Clear-all shape: a remote card's clear in flight, Clear all (fanned out to every kernel), Undo (to every kernel): the remote card shows when the remote kernel's newer build lists it, the local cards when the local one's does (the eleventh executed review and the round-eleven verifier's MEDIUM on PR 1967)", async (t) => {
  t.after(() => mock.timers.reset());   // registered with the test context (the second contributor's review): a red in this test no longer leaves the timers enabled for every later one
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const sent0 = posted.length;
  const { g2it, R, remote } = await remoteWorld(hooks);
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(1, 1) })); mock.timers.tick(700);
  card(R + ":g1")._clr.onclick(ev);                                         // a remote card's clear, in flight
  body.byId("feed-clearall")!.onclick!(ev);                                  // Clear all: broadcast to every attached kernel, though only local cards are visible
  mock.timers.tick(700);
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: ["", "TESTHOST"] });  // federation's word: every kernel the Clear all reached
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(1, 2) })); mock.timers.tick(700);   // the remote kernel's newer build lists its restored card; the local held frame is the old one
  assert.ok(card(R + ":g1"), "the remote card shows: its kernel got the fanned-out undo and restored its newest batch (before: the page kept it suppressed for good)");
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(2, 2) })); mock.timers.tick(700);   // the local kernel's newer build
  assert.ok(card("g1") && card("g2") && card("g3") && card(R + ":g1"), "every card the kernels restored shows");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("a configured host that is down counts as attached: with one dead remote and only local cards the pane is federated, a clear caches no entry and Undo is the round trip (the tenth executed review of PR 1967)", async (t) => {
  t.after(() => mock.timers.reset());   // registered with the test context (the second contributor's review): a red in this test no longer leaves the timers enabled for every later one
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const stackIds = hooks._clearedStackIdsForTests as () => string[][];
  const sent0 = posted.length;
  hooks._resetClearGestureStateForTests();
  const g2it = card("g2")?._it ?? cardOf("g2", API, "api", "#cc6633", "a second card of api's", "working", { live: true, tree: [] });
  await dispatch(frame([g1, g2it, g3], { working: ["web"], pendingHosts: ["TESTHOST"], pendingDead: ["TESTHOST"], buildIds: { "": 1 } })); mock.timers.tick(700);
  card("g3")._clr.onclick(ev); mock.timers.tick(700);
  assert.deepEqual(stackIds(), [], "no entry: a dead remote host is an attached kernel");
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev);
  assert.ok(!card("g3"), "nothing restored optimistically"); assert.ok(undo.classList.contains("undo-busy"), "the round trip's cue");
  await dispatch({ type: "undoRouted", hosts: [""] });                       // federation's word: the undo went to the local kernel (the dead host is no target)
  await dispatch(frame([g1, g2it, g3], { working: ["web"], pendingHosts: ["TESTHOST"], pendingDead: ["TESTHOST"], buildIds: { "": 2 } })); mock.timers.tick(700);
  assert.ok(card("g3"), "the local kernel's newer build restores");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("a truncated frame is read as truncated: the older clears it left out keep their suppressions and their Undo entries below the rebuilt ones (the ninth executed review of PR 1967)", async (t) => {
  t.after(() => mock.timers.reset());   // registered with the test context (the second contributor's review): a red in this test no longer leaves the timers enabled for every later one
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const stackIds = hooks._clearedStackIdsForTests as () => string[][];
  const sent0 = posted.length;
  hooks._resetClearGestureStateForTests();
  const g2it = card("g2")?._it ?? cardOf("g2", API, "api", "#cc6633", "a second card of api's", "working", { live: true, tree: [] });
  const many = Array.from({ length: 22 }, (_, k) => cardOf("c" + (k + 1), WEB, "web", "#3366cc", "card " + (k + 1), "needs_input", { live: true, tree: [] }));
  await dispatch(frame(many, { working: ["web"] })); mock.timers.tick(700);
  for (const c of many) card(c.itemId)._clr.onclick(ev);                     // twenty-two single clears: twenty-two entries
  mock.timers.tick(700);
  assert.equal(stackIds().length, 22);
  // the kernel's account for the last clear (its store refused; the ledger took it) carries the newest twenty batches and the count of twenty-two
  const window = many.slice(2).reverse().map((c) => [c.itemId]);         // c22 down to c3
  await dispatch({ type: "err", op: "askClear", sid: WEB, itemId: "", itemIds: [], batches: window, owedBatch: [], batchesTotal: 22, title: "That clear did not fully land for web", text: "The card is off the board; the session's own record of it could not be written." });
  mock.timers.tick(700);
  assert.deepEqual(stackIds(), [...window, ["c2"], ["c1"]], "the window rebuilt on top, the two older entries kept below (before: dropped, twenty left)");
  assert.ok(!card("c1") && !card("c2"), "the older clears stay off the board (before: back for a payload, then gone again)");
  await dispatch(frame([], { working: ["web"] })); mock.timers.tick(700);      // the payload: every card cleared
  assert.equal(stackIds().length, 22);
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("the page's record of a cleared card ends when a live payload shows the card, so a later frame naming it builds its entry from the live board and not from the old snapshot (the round-ten verifier on PR 1967)", async (t) => {
  t.after(() => mock.timers.reset());   // registered with the test context (the second contributor's review): a red in this test no longer leaves the timers enabled for every later one
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const stackIds = hooks._clearedStackIdsForTests as () => string[][];
  const recordIds = hooks._clearedItemsIdsForTests as () => string[];
  const sent0 = posted.length;
  hooks._resetClearGestureStateForTests();
  const g2it = card("g2")?._it ?? cardOf("g2", API, "api", "#cc6633", "a second card of api's", "working", { live: true, tree: [] });
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
  card("g3")._clr.onclick(ev); mock.timers.tick(700);
  assert.deepEqual(recordIds(), ["g3"], "the clear records the card");
  await dispatch(frame([g1, g2it], { working: ["web"] })); mock.timers.tick(700);           // the kernel took the clear: the record stays, the card is off
  assert.deepEqual(recordIds(), ["g3"]);
  body.byId("feed-undoclear")!.onclick!(ev);                                               // Undo: restored optimistically
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);       // the payload shows the card: the record ends
  assert.deepEqual(recordIds(), [], "a live payload showing the card ends its record (before: kept for the pane's life)");
  const live = card("g3")._it;
  await dispatch({ type: "err", op: "askClear", sid: WEB, itemId: "", itemIds: [], batches: [["g3"]], owedBatch: [], batchesTotal: 1, title: "That clear did not fully land for web", text: "The card is off the board; the session's own record of it could not be written." });
  mock.timers.tick(700);
  assert.deepEqual(stackIds(), [["g3"]], "a frame naming the card rebuilds its entry");
  assert.equal((hooks._clearedStackItemsForTests as () => any[][])()[0][0], live, "from the live board's copy, not an old snapshot");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

// ── round thirteen of PR 1967: the evidence per suppression, the attachment from federation's host list, the record's cap ──────────────
test("a federated pane, a clear after an Undo: the suppression made after the send has no restore check, so a held frame built before its clear that lists the card releases nothing, nor does the kernel's next build past the old moment (the round-twelve verifier's HIGH on PR 1967; the twelfth executed review)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const sent0 = posted.length;
  const { g2it, remote } = await remoteWorld(hooks);
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(1, 1) })); mock.timers.tick(700);
  card("g3")._clr.onclick(ev); mock.timers.tick(700);
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: [""] });
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(2, 1) })); mock.timers.tick(700);
  assert.ok(card("g3"), "the control: the undone card shows on its kernel's newer build");
  card("g1")._clr.onclick(ev); mock.timers.tick(700);                                                      // a clear AFTER the undo, its confirming build in flight
  assert.ok(!card("g1"));
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(2, 1) })); mock.timers.tick(700);   // the held frame re-emitted (a remote rebuild merges the local kernel's last frame), still listing g1
  assert.ok(!card("g1"), "a held frame listing the card releases nothing: the suppression was made after the send (before: build 2 against the old undo's moment 1, and g1 painted back for a beat)");
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(3, 1) })); mock.timers.tick(700);   // the kernel's in-flight build, claimed before the clear, listing g1
  assert.ok(!card("g1"), "nor the kernel's next build past the old moment");
  await dispatch(frame([g2it, g3, remote], { working: ["web"], ...B(4, 1) })); mock.timers.tick(700);      // the confirming build
  assert.ok(!card("g1"), "and the confirming build keeps it off: no flap");
  assert.deepEqual((hooks._restoreChecksForTests as () => unknown[])(), [], "no check stands: the undone card's was judged, the later clear never had one");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("a remote kernel's card whose session has no row on the strip: the pane is federated by federation's host list (the merged payload's build map here), so its clear caches no entry and Undo is the round trip (the round-twelve verifier's HIGH 2 on PR 1967)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const stackIds = hooks._clearedStackIdsForTests as () => string[][];
  const sent0 = posted.length;
  hooks._resetClearGestureStateForTests();
  const g2it = card("g2")?._it ?? cardOf("g2", API, "api", "#cc6633", "a second card of api's", "working", { live: true, tree: [] });
  const R = "22222222-3333-4444-5555-666666666666";
  const remote = cardOf(R + ":g1", "TESTHOST:" + R, "TESTHOST:api", "#cc6633", "a remote host's card", "needs_input", { live: true, tree: [] });
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], buildIds: { "": 1, TESTHOST: 1 } })); mock.timers.tick(700);   // the session list carries no remote row
  assert.ok(card(R + ":g1"), "the remote card is on the board, session row or none");
  card(R + ":g1")._clr.onclick(ev); mock.timers.tick(700);
  assert.deepEqual(stackIds(), [], "no entry: the remote kernel is attached, session row or none (before: read as a single-kernel pane, the remote card's entry cached)");
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev);
  assert.ok(!card(R + ":g1"), "nothing restored optimistically across kernels (before: the click restored it with no round trip)"); assert.ok(undo.classList.contains("undo-busy"), "the round trip's cue");
  await dispatch({ type: "undoRouted", hosts: ["TESTHOST"] });
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], buildIds: { "": 1, TESTHOST: 2 } })); mock.timers.tick(700);
  assert.ok(card(R + ":g1"), "and the card shows on its kernel's newer build");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("a kernel with no build on record can give no evidence: at federation's word its suppressions take the click-time release, never a baseline of zero, so its held frame shows the card by that road, while the local kernel's suppression keeps its check (the round-twelve verifier's MEDIUM on PR 1967; the twelfth executed review)", async (t) => {
  t.after(() => { mock.timers.reset(); delete (globalThis as any).__rompFed; });
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const stackIds = hooks._clearedStackIdsForTests as () => string[][];
  const sent0 = posted.length;
  const { g2it, R, remote } = await remoteWorld(hooks);
  (globalThis as any).__rompFed = { hosts: () => ["TESTHOST"] };            // the manager's host list: the remote kernel attached, its frames carrying no build (an older kernel)
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], buildIds: { "": 1 }, sessions: FED_SESSIONS })); mock.timers.tick(700);
  card(R + ":g1")._clr.onclick(ev); card("g3")._clr.onclick(ev); mock.timers.tick(700);
  assert.deepEqual(stackIds(), [], "federated by the manager's host list alone");
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: ["", "TESTHOST"] });   // a fanned-out undo
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], buildIds: { "": 1 }, sessions: FED_SESSIONS })); mock.timers.tick(700);   // the held frame: no remote build, the local one at the send's
  assert.ok(card(R + ":g1"), "the remote card shows: released at the send, since its kernel can give no evidence (before: a baseline of zero, and no build to pass it, so hidden for good)");
  assert.ok(!card("g3"), "the local card waits for its kernel's newer build");
  assert.deepEqual((hooks._restoreChecksForTests as () => unknown[])(), [["g3", "", 1]], "the local card's check at the seen build; none for the kernel with no build on record");
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], buildIds: { "": 2 }, sessions: FED_SESSIONS })); mock.timers.tick(700);
  assert.ok(card("g3"), "and shows on it");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  delete (globalThis as any).__rompFed;
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("the local kernel's seen build advances from the payload's own build when the merged map lacks the local key, so the send is measured and a held frame at that build releases nothing (the round-twelve verifier's low on PR 1967)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const sent0 = posted.length;
  const { g2it, remote } = await remoteWorld(hooks);
  const M = (local: number, remoteBuild: number) => ({ buildIds: { TESTHOST: remoteBuild }, buildId: local, sessions: FED_SESSIONS });   // a merged map without the local key
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...M(5, 1) })); mock.timers.tick(700);
  card("g3")._clr.onclick(ev); mock.timers.tick(700);
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: [""] });
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...M(5, 1) })); mock.timers.tick(700);   // the held frame, at the build seen at the send
  assert.ok(!card("g3"), "a frame at the send's build releases nothing (the local kernel's build read from the payload's own when the map lacks the local key)");
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...M(6, 1) })); mock.timers.tick(700);
  assert.ok(card("g3"), "the newer build shows it (before: the local build was read from the map alone, which lacked it, so nothing ever released the card)");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("a kernel-served SINGLE-KERNEL pane receives the manager's undoRouted frame too, and writes no restore check: the kernel's in-flight build, claimed before a second clear, leaves that card off while its Undo entry stands (the thirteenth executed review of PR 1967: a regression against the carry)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const stackIds = hooks._clearedStackIdsForTests as () => string[][];
  const checks = hooks._restoreChecksForTests as () => unknown[];
  const sent0 = posted.length;
  hooks._resetClearGestureStateForTests();
  const g2it = card("g2")?._it ?? cardOf("g2", API, "api", "#cc6633", "a second card of api's", "working", { live: true, tree: [] });
  await dispatch(frame([g1, g2it, g3], { working: ["web"], buildId: 1 })); mock.timers.tick(700);
  card("g3")._clr.onclick(ev); card("g1")._clr.onclick(ev); mock.timers.tick(700);           // two clears, both in flight
  assert.deepEqual(stackIds(), [["g1"], ["g3"]]);
  body.byId("feed-undoclear")!.onclick!(ev);                                                  // Undo pops g1's entry optimistically
  await dispatch({ type: "undoRouted", hosts: [""] });                                        // the shim routes the send through the manager: its frame reaches this pane
  assert.ok(card("g1"), "the popped entry's card is back at once"); assert.ok(!card("g3"), "the other clear stays");
  assert.deepEqual(checks(), [], "no restore check on a single-kernel pane: the click released what it restored (before: a check on g3 at build 1)");
  await dispatch(frame([g1, g2it, g3], { working: ["web"], buildId: 2 })); mock.timers.tick(700);   // the kernel's in-flight build, claimed before g3's clear, still lists g3
  assert.ok(!card("g3"), "g3 stays off while its Undo entry stands (before: painted back on build 2 and hidden again on build 3)");
  assert.deepEqual(stackIds(), [["g3"]]);
  await dispatch(frame([g1, g2it], { working: ["web"], buildId: 3 })); mock.timers.tick(700);       // the confirming build
  assert.ok(!card("g3") && card("g1"));
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("a pane that flips from federated to single-kernel between the click and the restore: the check written at the send still judges, so the local kernel's newer build shows the card (the twelfth executed review of PR 1967; before: the evidence path returned at once on the single reading and the card stayed hidden)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const sent0 = posted.length;
  const { g2it, remote } = await remoteWorld(hooks);
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(1, 1) })); mock.timers.tick(700);
  card("g3")._clr.onclick(ev); mock.timers.tick(700);
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: [""] });
  await dispatch(frame([g1, g2it, g3], { working: ["web"], buildIds: { "": 1 } })); mock.timers.tick(700);   // the remote detached: a local-only frame at the seen build, the held one, listing g3
  assert.ok(!card("g3"), "the held frame, built at the send's build, releases nothing");
  await dispatch(frame([g1, g2it, g3], { working: ["web"], buildIds: { "": 2 } })); mock.timers.tick(700);
  assert.ok(card("g3"), "the newer build shows it (before: hidden for good)");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("a kernel's restart between the send and the restore: its build falls below the one last seen, which re-bases the check, so the new life's payload listing the card shows it (the twelfth executed review of PR 1967; before: hidden until the new counter passed the old value)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const sent0 = posted.length;
  const { g2it, R, remote } = await remoteWorld(hooks);
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(1, 50) })); mock.timers.tick(700);   // the remote kernel at build 50
  card(R + ":g1")._clr.onclick(ev); mock.timers.tick(700);
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: ["TESTHOST"] });
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(1, 50) })); mock.timers.tick(700);   // the held frame
  assert.ok(!card(R + ":g1"), "the held frame releases nothing");
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(1, 1) })); mock.timers.tick(700);    // the remote kernel restarted: its first build of the new life lists the card
  assert.ok(card(R + ":g1"), "a build below the last seen is the restart: the new life's payload shows the card (before: 1 > 50 never, hidden until build 51)");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("the record's cap holds the batch being written: a Clear all of 201 cards keeps all 201 records, the kernel's account naming the batch rebuilds the entry whole and Undo restores every card (the twelfth executed review of PR 1967; before: the batch's own first card went at the 201st record and stayed hidden)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const stackIds = hooks._clearedStackIdsForTests as () => string[][]; const recordIds = hooks._clearedItemsIdsForTests as () => string[];
  const sent0 = posted.length;
  hooks._resetClearGestureStateForTests();
  const g2it = card("g2")?._it ?? cardOf("g2", API, "api", "#cc6633", "a second card of api's", "working", { live: true, tree: [] });
  const many = Array.from({ length: 201 }, (_, k) => cardOf("m" + (k + 1), WEB, "web", "#3366cc", "card " + (k + 1), "needs_input", { live: true, tree: [] }));
  await dispatch(frame(many, { working: ["web"] })); mock.timers.tick(700);
  body.byId("feed-clearall")!.onclick!(ev); mock.timers.tick(700);
  assert.equal(recordIds().length, 201, "every card of the batch is on record (before: 200, the first evicted while its own batch was being written)");
  assert.deepEqual(stackIds().map((e) => e.length), [201], "one entry of 201");
  // the kernel's account for the Clear all (its store refused; the ledger took it) names the whole batch: the cards leave and the entry is rebuilt from the record
  await dispatch({ type: "err", op: "clearAll", sid: WEB, itemId: "", itemIds: [], batches: [many.map((c) => c.itemId)], owedBatch: [], batchesTotal: 1, title: "That clear did not fully land for web", text: "The cards are off the board; the session's own record of them could not be written." });
  mock.timers.tick(700);
  assert.equal(many.filter((c) => card(c.itemId)).length, 0, "the account's batch is off the board");
  assert.deepEqual(stackIds().map((e) => e.length), [201], "the entry rebuilt whole (before: 200 of 201)");
  body.byId("feed-undoclear")!.onclick!(ev); mock.timers.tick(700);
  assert.equal(many.filter((c) => card(c.itemId)).length, 201, "Undo restores every card of the batch optimistically (before: the missing card stayed hidden across two payloads)");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("the cap on a federated pane, where no stack holds the batch: a Clear all of 201 keeps all 201 records beside the held remote record, so a refused clear's account re-shows any of them by its id (the twelfth executed review of PR 1967)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const recordIds = hooks._clearedItemsIdsForTests as () => string[];
  const sent0 = posted.length;
  const { g2it, R, remote } = await remoteWorld(hooks);
  const many = Array.from({ length: 201 }, (_, k) => cardOf("m" + (k + 1), WEB, "web", "#3366cc", "card " + (k + 1), "needs_input", { live: true, tree: [] }));
  await dispatch(frame([...many, remote], { working: ["web"], ...B(1, 1) })); mock.timers.tick(700);
  card(R + ":g1")._clr.onclick(ev); mock.timers.tick(700);                                                  // the remote card's clear, in flight: its record is held by the suppression
  body.byId("feed-clearall")!.onclick!(ev); mock.timers.tick(700);                                           // Clear all: 201 records written with no stack to hold them
  assert.equal(recordIds().length, 202, "every record stands: the remote card's and all 201 of the batch");
  assert.ok(recordIds().includes("m1") && recordIds().includes(R + ":g1"), "the batch's first card and the held remote record among them (before: m1 evicted at the 201st record)");
  await dispatch(frame([remote], { working: ["web"], ...B(2, 1) })); mock.timers.tick(700);                 // the local kernel took the Clear all: the cards leave with its payload
  assert.equal(many.filter((c) => card(c.itemId)).length, 0);
  // the local kernel's account: the Clear all's store write refused after all; every card of the batch comes back from the record, by its id
  await dispatch({ type: "err", op: "clearAll", sid: WEB, itemId: "", itemIds: many.map((c) => c.itemId), batches: [], owedBatch: [], batchesTotal: 0, title: "That clear did not land for web", text: "Nothing was cleared." });
  mock.timers.tick(700);
  assert.equal(many.filter((c) => card(c.itemId)).length, 201, "every card back, the first included (before: 200, m1's record gone)");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("an entry cached before a second kernel attached is one kernel's guess: the Undo click on the now-federated pane wipes it, keeps the card off and shows the cue, and the local kernel's newer build restores (the second contributor's review of PR 1967: the wipe was pinned by source text alone)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const stackIds = hooks._clearedStackIdsForTests as () => string[][];
  const sent0 = posted.length;
  hooks._resetClearGestureStateForTests();
  const g2it = card("g2")?._it ?? cardOf("g2", API, "api", "#cc6633", "a second card of api's", "working", { live: true, tree: [] });
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);                          // a single-kernel pane
  card("g3")._clr.onclick(ev); mock.timers.tick(700);
  assert.deepEqual(stackIds(), [["g3"]], "the single-kernel pane caches the entry");
  const R = "22222222-3333-4444-5555-666666666666";
  const remote = cardOf(R + ":g1", "TESTHOST:" + R, "TESTHOST:api", "#cc6633", "a remote host's card", "needs_input", { live: true, tree: [] });
  await dispatch(frame([g1, g2it, remote], { working: ["web"], ...B(1, 1) })); mock.timers.tick(700);            // a second kernel attaches: the merged payload carries its build; the local kernel took the clear
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev);
  assert.deepEqual(stackIds(), [], "the entry is wiped: a guess about one kernel's stack, made before the second attached");
  assert.ok(!card("g3"), "the card stays off: no optimistic restore across kernels"); assert.ok(undo.classList.contains("undo-busy"), "the round trip's cue");
  assert.equal(posted.slice(sent0).filter((m) => m.type === "undoClear").length, 1, "one request");
  await dispatch({ type: "undoRouted", hosts: [""] });
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(2, 1) })); mock.timers.tick(700);
  assert.ok(card("g3"), "the local kernel's newer build restores it");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("on a federated pane an unrelated kernel's push leaves the working cue on: it clears once every kernel the undo went to has built past the send (the second contributor's review of PR 1967; before: any payload cleared it, and the re-press it invited went to the local kernel)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const sent0 = posted.length;
  const { g2it, R, remote } = await remoteWorld(hooks);
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(1, 1) })); mock.timers.tick(700);
  card(R + ":g1")._clr.onclick(ev); mock.timers.tick(700);
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: ["TESTHOST"] });
  assert.ok(undo.classList.contains("undo-busy"), "the round trip's cue");
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(2, 1) })); mock.timers.tick(700);   // the LOCAL kernel's push: the remote's held frame rides along, its build unchanged
  assert.ok(undo.classList.contains("undo-busy"), "the cue stays: the kernel the undo went to has not built past the send (before: off, with the remote card still hidden)");
  assert.ok(!card(R + ":g1"), "and the card is still off");
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...B(2, 2) })); mock.timers.tick(700);   // the remote kernel's newer build
  assert.ok(!undo.classList.contains("undo-busy"), "the cue clears on it"); assert.ok(card(R + ":g1"), "with the card back");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

// ── round fifteen of PR 1967: the undo account's build floor (the round-thirteen verifier's ruling) ──────────────────────────────────
test("a federated pane, two clears in one flight then Undo: the kernel's in-flight build past the send releases nothing until the undo's account lands; the account's floor judges, so the restored card shows on a build past it and the other clear stays off (the round-thirteen verifier's probe: before, the in-flight build painted it back)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const floors = hooks._restoreFloorsForTests as () => [string, number | null][];
  const sent0 = posted.length;
  const { g2it, remote } = await remoteWorld(hooks);
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(1, 1) })); mock.timers.tick(700);
  card("g3")._clr.onclick(ev); card("g1")._clr.onclick(ev); mock.timers.tick(700);           // X then Y, both in flight
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: [""] });
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(2, 1) })); mock.timers.tick(700);   // the kernel's in-flight build, claimed before X's clear applied, past the send
  assert.ok(!card("g3") && !card("g1"), "a build past the send releases nothing before the account (before: both released, and X painted back for a beat)");
  assert.deepEqual(floors(), [["g3", null], ["g1", null]], "two checks, no floor yet: the account has not landed");
  await dispatch({ type: "undoAck", op: "undoClear", buildId: 2 });                          // the landed undo's account: the counter stood at 2 when it was processed
  assert.deepEqual(floors(), [["g3", 2], ["g1", 2]], "the floor on both checks");
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(2, 1) })); mock.timers.tick(700);   // the same held frame again: at the floor, not past it
  assert.ok(!card("g3") && !card("g1"), "a build at the floor is no evidence");
  await dispatch(frame([g1, g2it, remote], { working: ["web"], ...BA(3, 1) })); mock.timers.tick(700);       // past the floor: Y restored, X cleared
  assert.ok(card("g1"), "the restored card shows on a build past the floor"); assert.ok(!card("g3"), "the other clear stays off, its suppression ended by absence");
  assert.deepEqual(floors(), [], "both checks judged");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("a remote kernel's undo account lands its floor on its own kernel's checks alone, and the local kernel's account touches none of them (round fifteen of PR 1967); the refusal's frame carries the floor too", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const floors = hooks._restoreFloorsForTests as () => [string, number | null][];
  const sent0 = posted.length;
  const { g2it, R, remote } = await remoteWorld(hooks);
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(1, 1) })); mock.timers.tick(700);
  card("g3")._clr.onclick(ev); card(R + ":g1")._clr.onclick(ev); mock.timers.tick(700);       // a local clear, then the remote card's: the most recent
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: ["TESTHOST"] });            // the undo goes to the remote kernel
  await dispatch({ type: "undoAck", op: "undoClear", buildId: 9 });                          // a LOCAL ack (no host stamp): not this check's kernel
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(1, 1) })); mock.timers.tick(700);   // the remote's held frame at the send's build
  assert.ok(!card(R + ":g1"), "the local kernel's account is no floor for the remote card: its held frame releases nothing");
  assert.deepEqual(floors(), [[R + ":g1", null]], "one check, the remote card's, untouched by the local account");
  await dispatch({ type: "undoAck", op: "undoClear", buildId: 1, host: "TESTHOST" });        // the remote kernel's, stamped by federation
  assert.deepEqual(floors(), [[R + ":g1", 1]], "its own kernel's floor lands");
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(1, 2) })); mock.timers.tick(700);
  assert.ok(card(R + ":g1"), "the remote card shows on its kernel's build past the floor"); assert.ok(!card("g3"), "the local clear stays: the undo did not go there");
  // a second Undo, refused by the local kernel: the refusal's frame carries the floor, which lands on the local check
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: [""] });
  assert.deepEqual(floors(), [["g3", null]]);
  await dispatch({ type: "err", op: "undoClear", buildId: 3, itemId: "", itemIds: [], batches: [], owedBatch: [], batchesTotal: 0, title: "That undo did not land", text: "the clears log refused" });
  assert.deepEqual(floors(), [["g3", 3]], "the refusal names the floor too");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

// ── the first contributor's post-merge review of PR 1967: the floor per undo, the reconnect drop, the mixed pane, the restart on the accounting road ──
const BM = (local: number, remote: number) => ({ ...B(local, remote), ackHosts: [""] });   // a MIXED pane: the local kernel accounts for its undos, the remote one is older
const lastSeq = () => (posted.filter((m) => m.type === "undoClear").slice(-1)[0] || {}).seq as number;   // the sequence the click minted

test("two undos to one kernel with a clear between them: the first undo's account lands its floor on its own check alone, so a build claimed before the second clear applied cannot release the second suppression (the post-merge review of PR 1967, M2: before, one floor served every check of the kernel and the card flapped)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const floors = hooks._restoreFloorsForTests as () => [string, number | null][];
  const seqs = hooks._restoreSeqsForTests as () => [string, number | null][];
  const sent0 = posted.length;
  const { g2it, remote } = await remoteWorld(hooks);
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(1, 1) })); mock.timers.tick(700);
  card("g3")._clr.onclick(ev); mock.timers.tick(700);                                          // X
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev); const s1 = lastSeq(); await dispatch({ type: "undoRouted", hosts: [""], seq: s1 });   // undo 1: X's check
  card("g1")._clr.onclick(ev); mock.timers.tick(700);                                          // Y, cleared after undo 1
  undo.onclick!(ev); const s2 = lastSeq(); await dispatch({ type: "undoRouted", hosts: [""], seq: s2 });   // undo 2: Y's check
  assert.ok(typeof s1 === "number" && typeof s2 === "number" && s2 > s1, "each click mints its own sequence: " + s1 + ", " + s2);
  assert.deepEqual(seqs(), [["g3", s1], ["g1", s2]], "each check carries the undo it was written for");
  await dispatch({ type: "undoAck", op: "undoClear", seq: s1, buildId: 2 });                  // undo 1's account: the counter stood at 2
  assert.deepEqual(floors(), [["g3", 2], ["g1", null]], "the floor lands on undo 1's check alone (before: on both)");
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(3, 1) })); mock.timers.tick(700);   // build 3: claimed after undo 1 (X restored) and before Y's clear applied, so it lists Y too
  assert.ok(card("g3"), "X shows: its kernel's build past its floor lists it");
  assert.ok(!card("g1"), "Y stays off: its undo's account has not landed, so no build is evidence for it (before: 3 > 2 on the shared floor, shown, then hidden again by the confirming build)");
  await dispatch({ type: "undoAck", op: "undoClear", seq: s2, buildId: 4 });                  // undo 2's account
  assert.deepEqual(floors(), [["g1", 4]]);
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(5, 1) })); mock.timers.tick(700);
  assert.ok(card("g1"), "Y shows on a build past its own floor");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("a MIXED pane, an accounting kernel beside an older one: the older kernel's check is judged by the build seen at the send, the accounting kernel's waits for its account (the post-merge review of PR 1967, low 4: a pane-wide reading would hold the older kernel's card for good)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const sent0 = posted.length;
  const { g2it, R, remote } = await remoteWorld(hooks);
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BM(1, 1) })); mock.timers.tick(700);
  card("g3")._clr.onclick(ev); card(R + ":g1")._clr.onclick(ev); mock.timers.tick(700);       // a local clear, then the remote card's: the most recent
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: ["TESTHOST"], seq: lastSeq() });   // to the older remote kernel
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BM(1, 2) })); mock.timers.tick(700);   // the remote's build past the send: evidence on an older kernel
  assert.ok(card(R + ":g1"), "the older kernel's card shows on the build seen past the send: no account will ever come from it (a pane-wide reading of the accounting flag would hold it for good)");
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: [""], seq: lastSeq() });   // the second Undo: the local, accounting kernel
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BM(2, 2) })); mock.timers.tick(700);   // the local kernel's build past the send, before its account
  assert.ok(!card("g3"), "the accounting kernel's card waits for the account");
  await dispatch({ type: "undoAck", op: "undoClear", seq: lastSeq(), buildId: 2 });
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BM(3, 2) })); mock.timers.tick(700);
  assert.ok(card("g3"), "and shows on a build past its floor");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("a kernel's restart on the accounting road: a build below the last seen re-bases the check and its floor, so the new life's payload listing the card shows it (the post-merge review of PR 1967, low 5: the check's floor stood at the old life's counter)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const sent0 = posted.length;
  const { g2it, R, remote } = await remoteWorld(hooks);
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(1, 50) })); mock.timers.tick(700);   // the remote kernel at build 50
  card(R + ":g1")._clr.onclick(ev); mock.timers.tick(700);
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: ["TESTHOST"], seq: lastSeq() });
  await dispatch({ type: "undoAck", op: "undoClear", seq: lastSeq(), buildId: 50, host: "TESTHOST" });   // the account from the old life
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(1, 50) })); mock.timers.tick(700);   // at the floor: no evidence
  assert.ok(!card(R + ":g1"), "a build at the floor releases nothing");
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(1, 1) })); mock.timers.tick(700);    // the new life's first build lists the card
  assert.ok(card(R + ":g1"), "the restart re-bases the floor: the new life's payload shows the card (before: hidden until the new counter passed 50)");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("a kernel's socket coming back drops its waiting checks and their suppressions, so a lost undo account never holds a restored card off the board: the remote relay socket's own reopen (romp:hostRelayUp, the event a redial fires) and the tunnel poll's hostUp as a second trigger for a remote kernel, the shim's wsup for the local one, each its own kernel's alone (the post-merge review of PR 1967, low 2; the post-merge note on PR 2018)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const floors = hooks._restoreFloorsForTests as () => [string, number | null][];
  const sent0 = posted.length;
  const { g2it, R, remote } = await remoteWorld(hooks);
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(1, 1) })); mock.timers.tick(700);
  card(R + ":g1")._clr.onclick(ev); mock.timers.tick(700);
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: ["TESTHOST"], seq: lastSeq() });   // the remote kernel's check; its account never comes
  card("g3")._clr.onclick(ev); mock.timers.tick(700);
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: [""], seq: lastSeq() });          // the local kernel's check; its account never comes
  assert.deepEqual(floors(), [[R + ":g1", null], ["g3", null]]);
  win.dispatchEvent(new Event("romp:hostRelayUp"));                                              // a detail-less event names no kernel: nothing drops (the second contributor's post-merge note on PR 2018)
  assert.deepEqual(floors(), [[R + ":g1", null], ["g3", null]], "an event without a host drops nothing, the local kernel's check included");
  win.dispatchEvent(Object.assign(new Event("romp:hostRelayUp"), { detail: { host: "TESTHOST" } }));   // the remote relay socket reopened (federation's own event on its onopen): the redial abandoned the account
  assert.deepEqual(floors(), [["g3", null]], "the remote kernel's check is dropped on its socket's own reopen, the local one stands (before: only the tunnel poll's frame, silent on a watchdog redial)");
  await dispatch({ type: "undoRouted", hosts: ["TESTHOST"], seq: 99 });                          // (nothing pending on the remote now: no new check)
  card(R + ":g1"); hooks._resetClearGestureStateForTests();
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(1, 1) })); mock.timers.tick(700);
  card(R + ":g1")._clr.onclick(ev); card("g3")._clr.onclick(ev); mock.timers.tick(700);
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: ["TESTHOST"], seq: lastSeq() });
  undo.onclick!(ev); await dispatch({ type: "undoRouted", hosts: [""], seq: lastSeq() });
  assert.deepEqual(floors(), [[R + ":g1", null], ["g3", null]]);
  await dispatch({ type: "hostUp", hosts: ["TESTHOST"] });                                       // the tunnel poll's word, the second trigger
  assert.deepEqual(floors(), [["g3", null]], "the poll's frame drops it too, the local one stands");
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(1, 1) })); mock.timers.tick(700);
  assert.ok(card(R + ":g1"), "the remote card shows on the next payload listing it (before: held off until a reload)"); assert.ok(!card("g3"), "the local card still waits");
  await dispatch({ type: "wsup" });                                                                // the local socket reopened (the shim's frame)
  assert.deepEqual(floors(), []);
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(1, 1) })); mock.timers.tick(700);
  assert.ok(card("g3"), "the local card shows too");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("a truncated frame's NAMED half: the account of a refused clear names its id among twenty-three, the log's newest twenty ride and the count says twenty-two, so the refused card comes back and its entry goes while the two older clears keep theirs (the second contributor's post-merge review of PR 1967: pinned by source text alone before)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const stackIds = hooks._clearedStackIdsForTests as () => string[][];
  const sent0 = posted.length;
  hooks._resetClearGestureStateForTests();
  const g2it = card("g2")?._it ?? cardOf("g2", API, "api", "#cc6633", "a second card of api's", "working", { live: true, tree: [] });
  const many = Array.from({ length: 23 }, (_, k) => cardOf("c" + (k + 1), WEB, "web", "#3366cc", "card " + (k + 1), "needs_input", { live: true, tree: [] }));
  await dispatch(frame(many, { working: ["web"] })); mock.timers.tick(700);
  for (const c of many) card(c.itemId)._clr.onclick(ev);
  mock.timers.tick(700);
  assert.equal(stackIds().length, 23); assert.ok(!card("c23"));
  const window = many.slice(2, 22).reverse().map((c) => [c.itemId]);   // c22 down to c3: the log's newest twenty (c23's own row refused)
  await dispatch({ type: "err", op: "askClear", sid: WEB, itemId: "c23", itemIds: ["c23"], batches: window, owedBatch: [], batchesTotal: 22, title: "That clear did not land for web", text: "Nothing was cleared." });
  mock.timers.tick(700);
  assert.ok(card("c23"), "the refused card comes back: the account names it (under the mutant it stays off through every later payload)");
  assert.deepEqual(stackIds(), [...window, ["c2"], ["c1"]], "twenty-two entries: the window rebuilt on top, the two older kept below, c23's gone");
  assert.ok(!card("c1") && !card("c2"), "the older clears the frame left out keep their suppressions");
  for (let i = 0; i < 3; i++) { await dispatch(frame([...many.slice(22)], { working: ["web"] })); mock.timers.tick(700); }   // three later payloads listing c23
  assert.ok(card("c23"), "and stays");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("the truncation read's OWED adjustment: an account whose list is an owed id over the newest twenty, with the count twenty-one, reads as truncated (the owed entry is no log batch), so the oldest clear keeps its suppression and its entry below the rebuilt ones (the second contributor's post-merge review of PR 1967: pinned by source text alone before)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const stackIds = hooks._clearedStackIdsForTests as () => string[][];
  const sent0 = posted.length;
  hooks._resetClearGestureStateForTests();
  const g2it = card("g2")?._it ?? cardOf("g2", API, "api", "#cc6633", "a second card of api's", "working", { live: true, tree: [] });
  const many = Array.from({ length: 21 }, (_, k) => cardOf("c" + (k + 1), WEB, "web", "#3366cc", "card " + (k + 1), "needs_input", { live: true, tree: [] }));
  await dispatch(frame(many, { working: ["web"] })); mock.timers.tick(700);
  for (const c of many) card(c.itemId)._clr.onclick(ev);
  mock.timers.tick(700);
  assert.equal(stackIds().length, 21);
  const window = many.slice(1).reverse().map((c) => [c.itemId]);       // c21 down to c2: the newest twenty
  await dispatch({ type: "err", op: "askClear", sid: WEB, itemId: "", itemIds: [], batches: [["owed:1"], ...window], owedBatch: ["owed:1"], batchesTotal: 21, title: "That clear did not fully land for web", text: "The card is off the board; the session's own record of it could not be written." });
  mock.timers.tick(700);
  assert.ok(!card("c1"), "the oldest clear stays off: the frame is truncated once the owed entry is set aside (under the mutant 21 > 21 reads whole, and c1 shows again)");
  assert.deepEqual(stackIds(), [[], ...window, ["c1"]], "twenty-two entries: the owed entry (no card of this page's), the window, and c1's kept below (under the mutant c1's drops)");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("a lost undo account on a LIVE socket: a later undo's account from that kernel drops its older floorless checks, so the card shows on the next frame listing it instead of staying off while every build lists it (the second contributor's post-merge note on PR 2018)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const floors = hooks._restoreFloorsForTests as () => [string, number | null][];
  const sent0 = posted.length;
  const { g2it, remote } = await remoteWorld(hooks);
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(1, 1) })); mock.timers.tick(700);
  card("g3")._clr.onclick(ev); mock.timers.tick(700);
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev); const s1 = lastSeq(); await dispatch({ type: "undoRouted", hosts: [""], seq: s1 });   // undo 1: its account is lost
  card("g1")._clr.onclick(ev); mock.timers.tick(700);
  undo.onclick!(ev); const s2 = lastSeq(); await dispatch({ type: "undoRouted", hosts: [""], seq: s2 });   // undo 2
  assert.deepEqual(floors(), [["g3", null], ["g1", null]]);
  await dispatch({ type: "undoAck", op: "undoClear", seq: s2, buildId: 3 });                  // undo 2's account: undo 1's will never come (in-order delivery)
  assert.deepEqual(floors(), [["g1", 3]], "the older floorless check is dropped, the acked one keeps its floor");
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(4, 1) })); mock.timers.tick(700);
  assert.ok(card("g3"), "the card of the lost account shows on the next frame listing it (before: off while every build listed it)"); assert.ok(card("g1"), "the acked undo's card shows past its floor");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("an undo account without a stack (the kernel's clears log could not be read) leaves the feed's stack and its suppressions as they are and takes back the click's restore: the popped card goes back off and its entry back on top, the other clear stays off, the dialog says why (the round-one verifier of PR 2025; round three, the second contributor's post-merge review of PR 2021: an empty stack on that frame emptied the stack and released every suppression)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const stackIds = hooks._clearedStackIdsForTests as () => string[][];
  const sent0 = posted.length;
  hooks._resetClearGestureStateForTests();
  const g2it = card("g2")?._it ?? cardOf("g2", API, "api", "#cc6633", "a second card of api's", "working", { live: true, tree: [] });
  await dispatch(frame([g1, g2it, g3], { working: ["web"], buildId: 1 })); mock.timers.tick(700);
  card("g3")._clr.onclick(ev); card("g1")._clr.onclick(ev); mock.timers.tick(700);
  body.byId("feed-undoclear")!.onclick!(ev);                                                  // pops g1's entry optimistically
  assert.deepEqual(stackIds(), [["g3"]]); assert.ok(card("g1") && !card("g3"));
  await dispatch({ type: "err", op: "undoClear", title: "romp could not read its record of cleared cards", text: "This Undo found nothing to bring back: romp could not read the record it keeps of cleared cards (a stand-in fault). The cards stay as they are. Once the record can be read again, press Undo again.", itemId: "", itemIds: [], buildId: 1, seq: lastSeq(), readFault: true });
  mock.timers.tick(700);
  assert.deepEqual(stackIds(), [["g1"], ["g3"]], "the frame carried no stack, so the feed's stands (before round two: an empty one emptied it), and the popped entry is back on top, newest first (before round three: it stayed popped): the kernel restored nothing");
  assert.ok(!card("g3"), "the other clear stays off (before: released, the card repainted beside a dialog saying the cards stay)");
  assert.ok(!card("g1"), "the click's restore is taken back: the kernel never restored the card (before round three: it stood on the board beside the dialog saying the cards stay as they are)");
  assert.ok(body.querySelector("#err-dialog"), "and the dialog says why");
  for (const d of body.querySelectorAll("#err-dialog")) d.remove();
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("the read-fault account takes back the click's optimistic restore by the undo's sequence and its positive marker (the second contributor's post-merge review of PR 2021; round six: the first contributor's round-two comment): an owed-note refusal with no stack and no ids takes nothing back and leaves the record standing, a two-card batch goes back off and back on the stack on the marked account, an account for another sequence moves nothing, a second account for the same one moves nothing, a payload omitting the cards shows none, and Undo once the log reads restores them again", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const stackIds = hooks._clearedStackIdsForTests as () => string[][];
  const sent0 = posted.length;
  hooks._resetClearGestureStateForTests();
  const g2it = card("g2")?._it ?? cardOf("g2", API, "api", "#cc6633", "a second card of api's", "working", { live: true, tree: [] });
  await dispatch(frame([g1, g2it, g3], { working: ["web"], buildId: 1 })); mock.timers.tick(700);
  card("g2")._clr.onclick(ev); mock.timers.tick(700);                                          // one clear, then Clear all over the two left: a two-card batch
  body.byId("feed-clearall")!.onclick!(ev); mock.timers.tick(700);
  assert.deepEqual(stackIds(), [["g1", "g3"], ["g2"]], "newest first: Clear all's batch on top");
  body.byId("feed-undoclear")!.onclick!(ev); const s1 = lastSeq();                            // pops the two-card batch optimistically
  assert.ok(card("g1") && card("g3") && !card("g2")); assert.deepEqual(stackIds(), [["g2"]]);
  const readFault = (seq: number, buildId: number) => ({ type: "err", op: "undoClear", title: "romp could not read its record of cleared cards", text: "This Undo found nothing to bring back: romp could not read the record it keeps of cleared cards (a stand-in fault). The cards stay as they are. Once the record can be read again, press Undo again.", itemId: "", itemIds: [], buildId, seq, readFault: true });
  const owedRead = (seq: number) => ({ type: "err", op: "undoClear", title: "romp could not read its note of earlier owed cards", text: "The undo went ahead, but romp could not read the note it keeps of cards an earlier undo left owed (a stand-in fault). If some cards stay hidden after this, press Undo again once romp can read it.", itemId: "", itemIds: [], buildId: 1, seq });
  await dispatch(owedRead(s1)); mock.timers.tick(700);
  assert.ok(card("g1") && card("g3"), "an owed-note refusal with no stack and no ids says nothing about the click's restore: nothing is taken back (before round six: keyed on what the account lacked, the batch went back off and the next Undo popped a phantom)"); assert.deepEqual(stackIds(), [["g2"]]);
  for (const d of body.querySelectorAll("#err-dialog")) d.remove();
  await dispatch(readFault(s1 - 1, 1)); mock.timers.tick(700);
  assert.ok(card("g1") && card("g3"), "an account for another undo's sequence takes nothing back"); assert.deepEqual(stackIds(), [["g2"]]);
  for (const d of body.querySelectorAll("#err-dialog")) d.remove();
  await dispatch(readFault(s1, 1)); mock.timers.tick(700);
  assert.ok(!card("g1") && !card("g3") && !card("g2"), "the click's two cards go back off: the kernel restored nothing (before: both stood on the board beside the dialog)");
  assert.deepEqual(stackIds(), [["g1", "g3"], ["g2"]], "the popped entry is back on top: the kernel's newest batch is still that clear's");
  for (const d of body.querySelectorAll("#err-dialog")) d.remove();
  await dispatch(frame([], { working: [], buildId: 2 })); mock.timers.tick(700);                 // the kernel's board: every card cleared
  assert.ok(!card("g1") && !card("g3"), "the payload shows none");
  await dispatch(readFault(s1, 2)); mock.timers.tick(700);
  assert.deepEqual(stackIds(), [["g1", "g3"], ["g2"]], "a second account for the same sequence moves nothing: the click's record was spent");
  for (const d of body.querySelectorAll("#err-dialog")) d.remove();
  body.byId("feed-undoclear")!.onclick!(ev); const s2 = lastSeq();                            // the log reads again: Undo restores the batch optimistically
  assert.ok(card("g1") && card("g3"), "restored optimistically"); assert.deepEqual(stackIds(), [["g2"]]);
  await dispatch({ type: "undoAck", op: "undoClear", seq: s2, buildId: 3 });                    // the landed undo's account: the record is spent
  await dispatch(frame([g1, g3], { working: ["web"], buildId: 4 })); mock.timers.tick(700);
  assert.ok(card("g1") && card("g3"), "the kernel's payload lists them");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("a floored check survives a later undo's account from its kernel: the first undo's ack lands its floor before the second clear, the second undo's ack drops no floored check, and a frame at the first floor listing the card leaves it off while one past it shows it (the second contributor's post-merge review of PR 2021: the floor-undefined half of the release, pinned by behaviour)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const floors = hooks._restoreFloorsForTests as () => [string, number | null][];
  const sent0 = posted.length;
  const { g2it, remote } = await remoteWorld(hooks);
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(1, 1) })); mock.timers.tick(700);
  card("g3")._clr.onclick(ev); mock.timers.tick(700);
  const undo = body.byId("feed-undoclear")!;
  undo.onclick!(ev); const s1 = lastSeq(); await dispatch({ type: "undoRouted", hosts: [""], seq: s1 });
  await dispatch({ type: "undoAck", op: "undoClear", seq: s1, buildId: 3 });                  // undo 1's account lands first
  assert.deepEqual(floors(), [["g3", 3]]);
  card("g1")._clr.onclick(ev); mock.timers.tick(700);
  undo.onclick!(ev); const s2 = lastSeq(); await dispatch({ type: "undoRouted", hosts: [""], seq: s2 });
  await dispatch({ type: "undoAck", op: "undoClear", seq: s2, buildId: 5 });
  assert.deepEqual(floors(), [["g3", 3], ["g1", 5]], "the floored older check stands: only a FLOORLESS older check is released by a later account (a mutant dropping the condition drops g3's)");
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(3, 1) })); mock.timers.tick(700);   // at the first floor: no evidence
  assert.ok(!card("g3"), "a frame at the floor listing the card leaves it off"); assert.ok(!card("g1"));
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(4, 1) })); mock.timers.tick(700);   // past it
  assert.ok(card("g3"), "past the floor the listed card shows"); assert.ok(!card("g1"), "the second undo's card waits for its own floor");
  await dispatch(frame([g1, g2it, g3, remote], { working: ["web"], ...BA(6, 1) })); mock.timers.tick(700);
  assert.ok(card("g1"), "and shows past it");
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("a standing read fault after the re-journal-first rows landed: the marked read-fault account puts the owed entry the click popped back, and the stack-less reorder frame adds no second stand-in for the same owed card, so the pane's stack equals the kernel's ([owed], [last clear]) and the next Undo restores the owed card optimistically (the first contributor's round-four comment on PR 2025: the extra entry left the pane one longer than the kernel and its last lit Undo drew a bare ack)", async (t) => {
  t.after(() => mock.timers.reset());
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });
  const hooks = (await import("./feed")) as any;
  const stackIds = hooks._clearedStackIdsForTests as () => string[][];
  const sent0 = posted.length;
  hooks._resetClearGestureStateForTests();
  const g2it = card("g2")?._it ?? cardOf("g2", API, "api", "#cc6633", "a second card of api's", "working", { live: true, tree: [] });
  await dispatch(frame([g1, g2it, g3], { working: ["web"], buildId: 1 })); mock.timers.tick(700);
  card("g3")._clr.onclick(ev); card("g1")._clr.onclick(ev); mock.timers.tick(700);              // g3 then g1 cleared on this page: their copies are the page's
  // the kernel's stack as an earlier press left it: g3 OWED (its re-journal refused) on top, then g1's clear; the pane takes it from an account's stack
  await dispatch({ type: "err", op: "clearAll", title: "That clear did not land", text: "a stand-in refusal", itemId: "", itemIds: [], batches: [["g3"], ["g1"]], owedBatch: ["g3"], batchesTotal: 1, buildId: 1 });
  mock.timers.tick(700);
  await dispatch(frame([g2it], { working: ["web"], buildId: 2 })); mock.timers.tick(700);                  // the kernel's board: both hidden by their flags
  assert.deepEqual(stackIds(), [["g3"], ["g1"]], "premise: the pane's stack equals the kernel's, the owed entry with g3's copy on top");
  for (const d of body.querySelectorAll("#err-dialog")) d.remove();
  body.byId("feed-undoclear")!.onclick!(ev); const s1 = lastSeq();                                          // pops the owed entry: g3 restored optimistically
  assert.ok(card("g3") && !card("g1")); assert.deepEqual(stackIds(), [["g1"]]);
  // the kernel's pair under a STANDING read fault after the re-journal-first rows landed (the boundary module's pin holds these shapes)
  await dispatch({ type: "err", op: "undoClear", title: "romp could not read its record of cleared cards", text: "This Undo found nothing to bring back: romp could not read the record it keeps of cleared cards (a stand-in fault). The cards stay as they are. Once the record can be read again, press Undo again.", itemId: "", itemIds: [], readFault: true, buildId: 3, seq: s1 });
  mock.timers.tick(700);
  assert.ok(!card("g3"), "the marked account takes the click's restore back"); assert.deepEqual(stackIds(), [["g3"], ["g1"]], "and puts the owed entry back on top");
  await dispatch({ type: "err", op: "undoClear", title: "Undo went to earlier cards first", text: "Some cards were still owed from an earlier undo, so Undo went to them first, and that did not fully land (the other message says which). Once the clears log can be read and written again, one Undo brings them back and the next the last clear.", itemId: "g1", itemIds: ["g1"], ok: true, owedIds: ["g3"], buildId: 3, seq: s1 });
  mock.timers.tick(700);
  assert.deepEqual(stackIds(), [["g3"], ["g1"]], "the stack-less reorder frame adds no second stand-in: the pane's stack equals the kernel's, the owed card's re-journal row its newest batch (before: [[], [g3], [g1]], one entry longer)");
  assert.ok(!card("g1") && !card("g3"), "both stay off");
  for (const d of body.querySelectorAll("#err-dialog")) d.remove();
  body.byId("feed-undoclear")!.onclick!(ev);                                                                // the next Undo: the owed card, optimistically, as the kernel restores it
  assert.ok(card("g3"), "the next click restores the owed card from the pane's copy (before: an empty entry's pop restored nothing and drew a bare ack)"); assert.deepEqual(stackIds(), [["g1"]]);
  hooks._resetClearGestureStateForTests(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); mock.timers.tick(700);
});

test("the feed's Undo stack equals the kernel's batches after every press, by enumeration over tests/fixtures/undo-stack-transitions.json (the boundary harness writes it; round eight of PR 1967)", async (t) => {
  t.after(() => mock.timers.reset());   // registered with the test context (the second contributor's review): the trailing reset left the timers enabled for every later test after a red
  mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"], now: T0 * 1000 });   // the test before this one reset them
  const hooks = (await import("./feed")) as any;
  const stackIds = hooks._clearedStackIdsForTests as () => string[][];
  const frameIds = hooks._clearedStackFrameIdsForTests as () => (string[] | null)[];
  const reset = hooks._resetClearGestureStateForTests as () => void;
  const T = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "..", "tests", "fixtures", "undo-stack-transitions.json"), "utf8"));
  const sent0 = posted.length;
  const g2it = card("g2")?._it ?? cardOf("g2", API, "api", "#cc6633", "a second card of api's", "working", { live: true, tree: [] });   // the board as the tests around this one hold it, restored at the end (a fresh item when this test runs alone)
  const cards: Record<string, any> = {
    [T.cards.A]: cardOf(T.cards.A, T.sids.A, "web", "#3366cc", "wire the notes-api health route", "needs_input", { live: true, tree: [] }),
    [T.cards.B]: cardOf(T.cards.B, T.sids.B, "api", "#cc6633", "decide the migration order for the notes table", "needs_input", { live: true, tree: [] }),
  };
  const byKey = new Map<string, any>();
  for (const t of T.transitions) byKey.set(t.from + "|" + t.input.join(","), t);
  const settle = () => { mock.timers.tick(700); for (const d of body.querySelectorAll("#err-dialog")) d.remove(); };
  let build = 1;
  const press = async (t: any) => {
    const action = t.input[0];
    if (action === "clearA") card(T.cards.A)._clr.onclick(ev);
    else if (action === "clearB") card(T.cards.B)._clr.onclick(ev);
    else if (action === "clearAll") body.byId("feed-clearall")!.onclick!(ev);
    else { body.byId("feed-undoclear")!.onclick!(ev); await dispatch({ type: "undoRouted", hosts: [""] }); }   // the manager's frame reaches a kernel-served single-kernel pane too (round fourteen)
    for (const f of t.frames) await dispatch(f);                              // the kernel's real frames for this press
    settle();
    const where = "after " + t.input.join("/") + " from " + t.from;
    // BEFORE the payload: the stack the clicks and the frames built, by the ITEMS its entries hold; the ids the entries took from the frame,
    // apart (the eighth executed review: one hook returning the frame's ids made the equality hold by construction); and the cards the kernel
    // restored this press already on the board, the optimistic restore
    assert.deepEqual(stackIds(), t.after, where + " (before the payload): the feed's stack by its items, top first, is the kernel's batches");
    if (t.frames.some((f: any) => f.type === "err")) assert.deepEqual(frameIds(), t.after, where + ": the ids the entries took from the frame are the kernel's batches");   // an account carries the stack; the landed undo's ack (round fifteen) carries none
    const before = T.states[t.from].visible as string[];
    for (const id of t.visible.filter((x: string) => !before.includes(x))) assert.ok(card(id), where + " (before the payload): " + id + " is on the board, restored optimistically");
    // the kernel's IN-FLIGHT build (round fourteen, the round-thirteen verifier): a payload claimed before the press, listing the from-state's cards
    // at a later build, lands first. The board must already read as the kernel will show it, except after a silent board Clear all, whose cards
    // leave with the kernel's payload and not before (a check written on a single-kernel pane released the other pending clear on exactly this frame)
    await dispatch(frame(before.map((id: string) => card(id)?._it ?? cards[id]), { buildId: ++build })); settle();
    const inflight = action === "clearAll" && !t.frames.length ? before : t.visible;   // a Clear all's account (a refusal) has reconciled the board already
    // an OWED id's showing is the payload's to decide (the reconcile's rule: a promise about the next Undo, not a word on its card), so a frame from
    // before the press decides it too, until the truth payload; the flicker that leaves on a double-fault undo is the shape a build floor on the
    // kernel's accounts would close (round fourteen's proposal), not this replay's claim
    const deferred = new Set<string>(t.frames.flatMap((f: any) => (Array.isArray(f.owedBatch) ? f.owedBatch.map(String) : [])));
    for (const id of [T.cards.A, T.cards.B]) if (!deferred.has(id)) assert.equal(!!card(id), inflight.includes(id), where + " (the kernel's in-flight build): " + id + " is on the board iff the kernel will show it");
    await dispatch(frame(t.visible.map((id: string) => card(id)?._it ?? cards[id]), { buildId: ++build }));   // the payload after it, a later build each press (round fourteen: the kernel's counter moves)
    settle(); mock.timers.tick(7000);
    assert.deepEqual(stackIds(), t.after, where + ": the feed's stack by its items, top first, is the kernel's batches");
    for (const id of [T.cards.A, T.cards.B]) assert.equal(!!card(id), t.visible.includes(id), where + ": " + id + " is on the board iff the kernel shows it");
  };
  let n = 0;
  for (const t of T.transitions) {
    reset(); build = 1;
    await dispatch(frame([cards[T.cards.A], cards[T.cards.B]])); settle();
    let key = T.start;
    for (const step of T.states[t.from].witness) {
      const st = byKey.get(key + "|" + step.join(","));
      assert.ok(st, "a witness step is a recorded transition");
      await press(st); key = st.to;
    }
    await press(t); n++;
  }
  assert.ok(n >= 100, "an enumeration, not a handful: " + n + " transitions");
  reset(); posted.splice(sent0);
  await dispatch(frame([g1, g2it, g3], { working: ["web"] })); settle();
});

test("a card that leaves the payload leaves the section registry on its way out: the raw view holds nothing for its id, with no pick and no Collapsed flip between (a contributor's post-merge note on PR 2124)", async () => {
  const raw = (CS as any).sectionHostsRaw as ((id: string) => HTMLElement[]) | undefined;
  assert.ok(raw, "the base has no view of the registry that keeps what it holds (sectionHosts drops disconnected hosts as it reads), so the observation this pin makes is itself new");
  const sectionHostsRaw = raw!;
  await dispatch(frame([g1, g2, g3]));
  assert.ok(card("g2"), "card 2 is on the board");
  assert.equal(sectionHostsRaw("g2").length, 1, "…and registered once as its own host");
  await dispatch(frame([g1, g3]));
  assert.equal(card("g2"), null, "card 2 left the board with the payload");
  assert.deepEqual(sectionHostsRaw("g2"), [], "the registry holds nothing for it: the unregister ran where the feed dropped it, not at a later read of the item or a flip");
  assert.equal(sectionHostsRaw("g1").length, 1, "a card that stayed keeps its one host");
  // the raw view is the test's: a detached host is what the registry HOLDS, while the reading view drops it as a belt
  const stray = document.createElement("div");
  CS.registerSectionHost("zz", stray);
  assert.equal(sectionHostsRaw("zz").length, 1, "the raw view reads the set as held");
  assert.deepEqual(CS.sectionHosts("zz"), [], "the reading view drops a host that is not in the document");
  assert.deepEqual(sectionHostsRaw("zz"), [], "…and that read emptied the set");
  await dispatch(frame([g1, g2, g3]));   // the board back to three for the tests that follow
});

test("the focused section's copy leaves the registry when the focus moves on (the board's card stays registered once), and the section's removal takes its copies out too (a contributor's note on PR 2141)", async () => {
  const raw = (CS as any).sectionHostsRaw as (id: string) => HTMLElement[];
  await dispatch(frame([g1, g2, g3]));
  assert.deepEqual({ g1: raw("g1").length, g2: raw("g2").length }, { g1: 1, g2: 1 }, "the board's cards alone before the section shows");
  // the switch is the view menu's fourth row (T347): open the menu from the footer's View button and press the row by its label
  const viewBtn = body.byId("feed-viewbtn"); assert.ok(viewBtn, "the footer's View button");
  const pressFocusedRow = () => { (viewBtn as any).onclick(ev); const row: any = body.querySelectorAll(".feed-viewmenu .ctx-item").find((r: any) => /Show focused session/.test(r.textContent || "")); assert.ok(row, "the Show focused session row"); row.onclick(ev); };
  pressFocusedRow();
  await dispatch({ type: "activeChat", id: WEB });   // the chat's focused session: its cards get a copy on top
  assert.ok(body.byId("feed-focus"), "the focused section is up");
  assert.deepEqual({ g1: raw("g1").length, g2: raw("g2").length }, { g1: 2, g2: 1 }, "the focused session's card has two hosts, the board's and the section's copy");
  await dispatch({ type: "activeChat", id: API });   // the focus moves on: g1's copy leaves the section, g2 gets one
  assert.deepEqual({ g1: raw("g1").length, g2: raw("g2").length }, { g1: 1, g2: 2 }, "the copy that left the section left the registry on its way out (the focused-copy exit unregisters), the board's card stays registered once");
  pressFocusedRow();   // the switch off: the section is removed with its copies
  assert.equal(body.byId("feed-focus"), null, "the section is gone");
  assert.deepEqual({ g1: raw("g1").length, g2: raw("g2").length }, { g1: 1, g2: 1 }, "the section's removal took its copies out of the registry");
});
