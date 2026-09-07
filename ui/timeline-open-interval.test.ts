// An awaiting or compacting interval the session is STILL in arrives with its end at the payload's own
// clock (kernel _state_intervals ends an open span at `now`): the renderer reads an end within 2 s of
// data.now — or a null end — as OPEN and draws it to the live edge, the way barEndT draws an open work
// bar, so the stripe glides with the edge instead of sitting at the kernel's build clock until the next
// rebuild (the lanes frame is projected from the cached build, so its clock can trail the live edge by
// up to a rebuild). The end stays numeric on the wire: a null end was a wire break for every already-loaded
// renderer (Math.min(null, t1) = 0 dropped the stripe). Headless draw() over a minimal DOM shim (the
// timeline-render.test.ts pattern), with the live edge pushed MAX_INTERP_AHEAD past data.now so "to the
// live edge" and "to the payload's end" land on different pixels.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { createRequire } from "node:module";

function makeNode(tag: string): any {
  const n: any = {
    tag, _attrs: {}, children: [] as any[], style: {}, dataset: {}, textContent: "", parentNode: null,
    classList: { _s: new Set<string>(), add(...a: string[]) { a.forEach((c) => this._s.add(c)); },
      remove(...a: string[]) { a.forEach((c) => this._s.delete(c)); },
      toggle(c: string, f?: boolean) { f ? this._s.add(c) : this._s.delete(c); }, contains(c: string) { return this._s.has(c); } },
    setAttribute(k: string, v: any) { this._attrs[k] = v; }, getAttribute(k: string) { return this._attrs[k]; },
    setAttributeNS(_n: any, k: string, v: any) { this._attrs[k] = v; }, removeAttribute(k: string) { delete this._attrs[k]; },
    appendChild(c: any) { c.parentNode = n; this.children.push(c); return c; },
    insertBefore(c: any, ref: any) { c.parentNode = n; const i = this.children.indexOf(ref); i < 0 ? this.children.push(c) : this.children.splice(i, 0, c); return c; },
    removeChild(c: any) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); return c; },
    get firstChild() { return this.children[0] || null; },
    _ls: {} as any,
    addEventListener(t: string, fn: any) { (n._ls[t] = n._ls[t] || []).push(fn); }, removeEventListener() {},
    querySelector() { return null; }, querySelectorAll() { return []; },
    getBoundingClientRect() { return { width: 1400, height: 420, left: 0, top: 0, right: 1400, bottom: 420 }; },
    closest() { return null; }, focus() {},
    createEl(t: string, o: any) { const e = makeNode(t); if (o && o.cls) e.classList.add(o.cls); if (o && o.text) e.textContent = o.text; this.appendChild(e); return e; },
    createDiv(o: any) { return this.createEl("div", o); }, createSpan(o: any) { return this.createEl("span", o); },
  };
  return n;
}
const g: any = global;
g.document = {
  createElement(t: string) { return t === "canvas" ? { getContext() { return { font: "", measureText(s: string) { return { width: (s ? s.length : 0) * 6 }; } }; } } : makeNode(t); },
  createElementNS(_n: any, t: string) { return makeNode(t); },
  body: makeNode("body"), documentElement: makeNode("html"), head: makeNode("head"),
  getElementById() { return null; },
  addEventListener() {}, removeEventListener() {},
};
g.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
g.getComputedStyle = () => ({ backgroundColor: "rgb(30,30,30)" });
g.requestAnimationFrame = () => 0;
g.addEventListener = () => {}; g.removeEventListener = () => {};
g.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
g.window = g;
g.innerWidth = 1400; g.innerHeight = 800;

const viewPath = path.resolve(process.cwd(), "..", "ui", "romp-timeline-view.js");
const { TimelinePanel } = createRequire(__filename)(viewPath);
const SRC = fs.readFileSync(viewPath, "utf8");

const NOW = 1_781_000_000;
// The view's glide cap, read from the source: how far the live edge is pushed past data.now below.
const AHEAD = Number(/const MAX_INTERP_AHEAD = (\d+);/.exec(SRC)![1]);
function lane(id: string, name: string, extra: any) {
  return {
    id, name, color: "#7aa2f7", state: "working", live: true, model: "m", effort: "high",
    context: 40, since: NOW - 60, awaiting: [], compacting: [], compactions: [], pendingMail: 0, faded: false, stale: false, ...extra,
  };
}
function turn(id: string) {
  return { id, promptId: id + "#p", workId: id + "#w", start: NOW - 400, end: NOW - 200, prompt: "do the thing", src: "typed",
    mids: [], pending: false, summary: "did the thing", tid: "fork-" + id, uuid: "u-" + id, workUuid: "w-" + id, replyUuid: "r-" + id };
}
function collect(node: any, pred: (n: any) => boolean, out: any[] = []): any[] {
  if (pred(node)) out.push(node);
  for (const c of node.children || []) collect(c, pred, out);
  return out;
}
const hatch = (fill: string) => (n: any) => n.tag === "rect" && n.getAttribute("fill") === fill;
const right = (r: any) => Number(r.getAttribute("x")) + Number(r.getAttribute("width"));
const width = (r: any) => Number(r.getAttribute("width"));
// The transparent hover rect drawn right after a stripe (the same parent, the next child) — the stripe's hit
// target; entering it shows the tip, which the panel is stubbed to hand back as html.
function tipOf(panel: any, stripe: any): string {
  const kids = stripe.parentNode.children, hit = kids[kids.indexOf(stripe) + 1];
  assert.ok(hit && hit.tag === "rect" && hit.getAttribute("fill") === "transparent" && hit._ls.mouseenter, "a hover rect follows the stripe");
  const tips: string[] = [];
  panel.showTip = (html: string) => tips.push(html);
  hit._ls.mouseenter[0]({ clientX: 10, clientY: 10 });
  assert.equal(tips.length, 1, "one tip per enter");
  return tips[0];
}

// A panel live-following with its edge AHEAD s past data.now (the glide the view does between kernel
// frames, at its cap), gaps uncollapsed so x is linear in time.
function livePanel(data: any) {
  const panel: any = new TimelinePanel(makeNode("div"));
  panel.data = data;
  panel._collapseGaps = false;
  panel._pinned = true; panel._frozeFromPin = false;
  panel._nowBaseSec = NOW; panel._nowBaseMs = performance.now() - 5 * AHEAD * 1000;   // clamps to AHEAD
  return panel;
}

test("an open interval (end at the payload clock) draws to the live edge; a closed one stops at its end; a null end draws the same", () => {
  const ids = ["S1", "S2", "S3", "S4", "S5", "S6", "S7"];
  const panel = livePanel({
    now: NOW,
    sessions: [
      lane("S1", "web", { state: "needsInput", awaiting: [[NOW - 100, NOW]] }),        // OPEN: the kernel's shape, end == now
      lane("S2", "api", { awaiting: [[NOW - 100, NOW - 30]] }),                        // closed 30 s ago
      lane("S3", "tests", { awaiting: [[NOW - 100, NOW - 60]] }),                      // closed 60 s ago (with S2: px per second)
      lane("S4", "docs", { state: "needsInput", awaiting: [[NOW - 100, null]] }),      // a null end still reads as open
      lane("S5", "build", { compactions: [{ t: NOW }] }),                              // a marker ending at x(now): the reference pixel
      lane("S6", "lint", { state: "needsInput", awaiting: [[NOW - 100, NOW - 1]] }),   // an end within 2 s of the clock: open (the kernel's clock and the payload's can differ by a second)
      lane("S7", "deploy", { awaiting: [[NOW - 100, NOW - 3]] }),                      // 3 s: closed
    ],
    turns: Object.fromEntries(ids.map((id) => [id, [turn(id + ":1")]])),
    messages: [], activeChat: null, focus: null, hover: null, usage: null,
  });
  assert.doesNotThrow(() => panel.draw(), "draw() accepts numeric and null interval ends");
  const stripes = collect(panel.svg, hatch("url(#vault-await-hatch)"));
  assert.equal(stripes.length, 6, "every awaiting span draws (a null end used to draw nothing)");
  const [open, closed30, closed60, openNull, open1, closed3] = stripes;
  const marker = collect(panel.svg, hatch("url(#vault-compact-hatch)"));
  assert.equal(marker.length, 1, "one compaction marker");
  const xNow = right(marker[0]);
  const pps = (width(closed30) - width(closed60)) / 30;
  assert.ok(pps > 0.05, "the window resolves seconds to pixels: " + pps);
  assert.ok(Math.abs(right(closed30) - (xNow - 30 * pps)) < 1, "a closed span stops at its own end");
  assert.ok(Math.abs(right(open) - (xNow + AHEAD * pps)) < 1,
    "the open span reaches the live edge, " + AHEAD + " s past the payload's now (it used to stop at x(now), the build clock)");
  assert.ok(Math.abs(right(openNull) - right(open)) < 0.01, "a null end lands on the same live edge");
  assert.equal(open.getAttribute("x"), openNull.getAttribute("x"), "…starting where the payload says");
  assert.ok(Math.abs(right(open1) - (xNow + AHEAD * pps)) < 1, "an end 1 s before the clock reads open: to the live edge");
  assert.ok(Math.abs(right(closed3) - (xNow - 3 * pps)) < 1, "an end 3 s before the clock reads closed: at its own end");
});

test("the awaiting tooltip reads 'now' for an open span (a payload-clock or null end) and a clock time for a closed one", () => {
  const panel = livePanel({
    now: NOW,
    sessions: [
      lane("S1", "web", { state: "needsInput", awaiting: [[NOW - 100, NOW]] }),
      lane("S2", "api", { awaiting: [[NOW - 100, NOW - 30]] }),
      lane("S3", "tests", { state: "needsInput", awaiting: [[NOW - 100, null]] }),
    ],
    turns: { S1: [turn("S1:1")], S2: [turn("S2:1")], S3: [turn("S3:1")] },
    messages: [], activeChat: null, focus: null, hover: null, usage: null,
  });
  panel.draw();
  const stripes = collect(panel.svg, hatch("url(#vault-await-hatch)"));
  assert.equal(stripes.length, 3);
  const [open, closed, openNull] = stripes.map((st) => tipOf(panel, st));
  assert.match(open, /blocked on your input · \d\d:\d\d(:\d\d)?–now</, "open: to now");
  assert.match(openNull, /blocked on your input · \d\d:\d\d(:\d\d)?–now</, "a null end: to now");
  assert.match(closed, /blocked on your input · \d\d:\d\d(:\d\d)?–\d\d:\d\d/, "closed: to its end");
  assert.doesNotMatch(closed, /–now</);
});

test("an open compacting interval draws its cross-hatch to the live edge; a null end draws the same", () => {
  const panel = livePanel({
    now: NOW,
    sessions: [
      lane("S1", "web", { state: "compacting", compacting: [[NOW - 50, NOW]] }),    // open: end at the payload clock
      lane("S2", "api", { compactions: [{ t: NOW }] }),                             // the x(now) reference marker
      lane("S3", "tests", { state: "compacting", compacting: [[NOW - 50, null]] }), // a null end reads as open too
    ],
    turns: { S1: [turn("S1:1")], S2: [turn("S2:1")], S3: [turn("S3:1")] },
    messages: [], activeChat: null, focus: null, hover: null, usage: null,
  });
  assert.doesNotThrow(() => panel.draw());
  const hx = collect(panel.svg, hatch("url(#vault-compact-hatch)"));
  assert.equal(hx.length, 3, "the two live compacting stripes and the marker (a null end used to draw nothing)");
  const [stripe, marker, nullStripe] = hx;
  assert.ok(right(stripe) > right(marker) + 2, "the open compacting stripe runs past x(now) to the live edge");
  assert.ok(Math.abs(right(nullStripe) - right(stripe)) < 0.01, "a null end lands on the same live edge");
  assert.equal(nullStripe.getAttribute("x"), stripe.getAttribute("x"));
});

test("the compacting tooltip reads 'compacting' for an open span and 'compacted' for a closed one", () => {
  const panel = livePanel({
    now: NOW,
    sessions: [
      lane("S1", "web", { state: "compacting", compacting: [[NOW - 50, NOW]] }),
      lane("S2", "api", { compacting: [[NOW - 100, NOW - 30]] }),
    ],
    turns: { S1: [turn("S1:1")], S2: [turn("S2:1")] },
    messages: [], activeChat: null, focus: null, hover: null, usage: null,
  });
  panel.draw();
  const hx = collect(panel.svg, hatch("url(#vault-compact-hatch)"));
  assert.equal(hx.length, 2);
  const [open, closed] = hx.map((st) => tipOf(panel, st));
  assert.match(open, /<span class="k">compacting<\/span>.*context compacting · \d\d:\d\d(:\d\d)?–now</, "open: still compacting, to now");
  assert.match(closed, /<span class="k">compacted<\/span>.*context compacted · \d\d:\d\d(:\d\d)?–\d\d:\d\d/, "closed: compacted, to its end");
  assert.doesNotMatch(closed, /–now</);
});
