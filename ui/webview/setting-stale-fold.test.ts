// The stale-settings toast folds one refused gesture's N refusals into ONE notice naming the
// refusing kernels (the #879 review's note: N kernels refusing one stale flush drew N identical
// toasts naming no host). BEHAVIORAL, the gear-models-frame.test.ts way: the toast block of gear.js
// (STALE_LABELS through the settingStale listener) is lifted out and run against stand-ins for
// window/document/setTimeout and the closure names it reads (p, fill, post, gclock), then driven
// with frames the way federation hands them to the gear — a remote kernel's frame host-stamped by
// prefixInbound, the local kernel's without a host. Synthetic hosts only (the notes-api demo world).
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const GEAR = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "gear.js"), "utf8");

// A minimal DOM: what staleToast and the fold touch — className/id/textContent/title, children with
// parentNode, appendChild/remove, setAttribute, classList, querySelector by class, click listeners.
type Node = {
  tag: string; id: string; className: string; textContent: string; title: string; type: string;
  children: Node[]; parentNode: Node | null; clicks: Array<(e: any) => void>;
  appendChild(c: Node): void; remove(): void; setAttribute(k: string, v: string): void;
  classList: { add(c: string): void; contains(c: string): boolean };
  querySelector(sel: string): Node | null; addEventListener(type: string, fn: (e: any) => void): void;
};
function node(tag: string): Node {
  const n: Node = {
    tag, id: "", className: "", textContent: "", title: "", type: "", children: [], parentNode: null, clicks: [],
    appendChild(c) { c.parentNode = n; n.children.push(c); },
    remove() { if (n.parentNode) { const p = n.parentNode; p.children.splice(p.children.indexOf(n), 1); n.parentNode = null; } },
    setAttribute() { /* role/aria — not under test */ },
    classList: { add(c) { n.className += " " + c; }, contains(c) { return n.className.split(" ").includes(c); } },
    querySelector(sel) { return n.children.find((c) => c.className.split(" ").includes(sel.slice(1))) || null; },
    addEventListener(type, fn) { if (type === "click") n.clicks.push(fn); },
  };
  return n;
}

function lift() {
  const start = GEAR.indexOf("  var STALE_LABELS");
  const at = GEAR.indexOf("m.type !== 'settingStale'", start);
  const stop = GEAR.indexOf("\n  });\n", at) + "\n  });\n".length;
  assert.ok(start > 0 && at > start && stop > at, "anchors not found — the gear's stale-toast block moved; re-anchor");
  const src = GEAR.slice(start, stop);
  const listeners: Array<(e: any) => void> = [];
  const win = { addEventListener: (type: string, fn: (e: any) => void) => { if (type === "message") listeners.push(fn); } };
  const body = node("body");
  const byId: Record<string, Node> = {};
  const doc = {
    body,
    getElementById: (id: string) => byId[id] || null,
    createElement: (tag: string) => node(tag),
    addEventListener: () => { /* the Escape handler — not under test */ },
  };
  // ids register when appended to body (the container is created once, then found by id)
  body.appendChild = (c: Node) => { c.parentNode = body; body.children.push(c); if (c.id) byId[c.id] = c; };
  const timers: Array<{ fn: () => void; ms: number }> = [];
  const setTimeout = (fn: () => void, ms: number) => { timers.push({ fn, ms }); return timers.length; };
  const p = { hidden: true };
  let fills = 0;
  const fill = () => { fills++; };
  const posts: any[] = [];
  const post = (m: any) => posts.push(m);
  const learned: Array<[string, number]> = [];
  const gclock = { learn: (s: string, gt: number) => learned.push([s, gt]), stamp: (s: string) => { learned.push([s, -1]); return 7777; } };
  const fn = new Function("window", "document", "p", "fill", "post", "gclock", "setTimeout", src);
  fn(win, doc, p, fill, post, gclock, setTimeout);
  const frame = (m: any) => listeners.forEach((l) => l({ data: m }));
  const box = () => byId["rs-stale-toasts"];
  const texts = () => (box() ? box().children.map((t) => t.querySelector(".rs-stale-toast-msg")!.textContent) : []);
  return { frame, box, texts, timers, p, fills: () => fills, posts, learned };
}

const REFUSED = { type: "settingStale", setting: "judge-model", storedGt: 2000, gt: 1000, kept: "fable",
                  gesture: { type: "setJudgeModel", model: "opus" } };

test("three kernels refusing one gesture draw ONE toast that names all three", () => {
  const g = lift();
  g.frame({ ...REFUSED, host: "web" });
  g.frame({ ...REFUSED, host: "api" });
  g.frame({ ...REFUSED });                         // the local kernel: no host key
  assert.equal(g.box().children.length, 1, "one toast for one refused gesture");
  assert.deepEqual(g.texts(), ["Triage model: opus was not applied on web, api, this machine. Keeping fable."]);
  assert.deepEqual(g.learned.filter(([, gt]) => gt > 0), [["judge-model", 2000], ["judge-model", 2000], ["judge-model", 2000]],
    "every frame teaches the clock the stamp it lost to");
});

test("the same host refusing twice is named once; a different gesture gets its own toast", () => {
  const g = lift();
  g.frame({ ...REFUSED, host: "web" });
  g.frame({ ...REFUSED, host: "web" });            // a duplicate delivery
  assert.deepEqual(g.texts(), ["Triage model: opus was not applied on web. Keeping fable."]);
  g.frame({ ...REFUSED, gt: 999, host: "web" });   // an older click of the same setting — its own identity
  assert.equal(g.box().children.length, 2);
  g.frame({ ...REFUSED, setting: "auto-nudge", kept: false, gesture: { type: "setAutoNudge", enabled: true }, host: "web" });
  assert.equal(g.box().children.length, 3);
  assert.equal(g.texts()[2], "Auto Nudge: on was not applied on web. Keeping off.", "booleans read as on/off, the refused one too");
});

test("a frame without gt (an older kernel) keeps one toast per frame — no key, no fold", () => {
  const g = lift();
  const { gt: _gt, ...old } = REFUSED;
  g.frame({ ...old, host: "web" });
  g.frame({ ...old, host: "api" });
  assert.equal(g.box().children.length, 2);
  assert.deepEqual(g.texts(), ["Triage model: opus was not applied on web. Keeping fable.",
                               "Triage model: opus was not applied on api. Keeping fable."]);
});

test("a dismissed or expired toast never absorbs a later frame: liveness is the node's presence, not a window", () => {
  const g = lift();
  g.frame({ ...REFUSED, host: "web" });
  const first = g.box().children[0];
  first.remove();                                  // click-dismissed (the container's delegated handler)
  g.frame({ ...REFUSED, host: "api" });
  assert.equal(g.box().children.length, 1, "a fresh toast, not a resurrection");
  assert.deepEqual(g.texts(), ["Triage model: opus was not applied on api. Keeping fable."]);
  // the self-clearing backstop: run the 12000ms callbacks, then the same key again
  g.timers.filter((t) => t.ms === 12000).forEach((t) => t.fn());
  assert.equal(g.box().children.length, 0, "expired");
  g.frame({ ...REFUSED, host: "web" });
  assert.deepEqual(g.texts(), ["Triage model: opus was not applied on web. Keeping fable."]);
});

test("a toast already fading does not absorb a later refusal of the same gesture: it gets its own toast", () => {
  // the 11 s fade precedes the 12 s removal; with liveness read as parentNode alone, a refusal arriving
  // in that second was written into a toast at opacity 0 and never seen (the #945 review). Event-keyed
  // still: the fade class is read at the frame, no cleanup rides the timers.
  const g = lift();
  g.frame({ ...REFUSED, host: "web" });
  g.timers.filter((t) => t.ms === 11000).forEach((t) => t.fn());   // the fade arms; the node is still on screen
  g.frame({ ...REFUSED, host: "api" });
  assert.equal(g.box().children.length, 2, "a fresh toast, not a write into the fading one");
  assert.ok(g.box().children[0].classList.contains("fade"));
  assert.ok(!g.box().children[1].classList.contains("fade"));
  assert.deepEqual(g.texts(), ["Triage model: opus was not applied on web. Keeping fable.",
                               "Triage model: opus was not applied on api. Keeping fable."]);
});

test("the folded toast keeps its Apply anyway: one click re-issues the echo with a fresh stamp", () => {
  const g = lift();
  g.frame({ ...REFUSED, host: "web" });
  g.frame({ ...REFUSED, host: "api" });
  const t = g.box().children[0];
  const btn = t.children.find((c) => c.className === "rs-stale-toast-act")!;
  assert.ok(btn, "the action button rides the folded toast");
  assert.equal(btn.textContent, "Apply opus anyway", "the label names the value one click would apply everywhere");
  assert.equal(btn.type, "button");
  assert.ok(btn.title && btn.title !== "click to dismiss", "the button has its own tooltip, not the toast's dismiss one: " + btn.title);
  assert.ok(btn.title.includes("opus"), "…and it names the value too");
  btn.clicks.forEach((fn) => fn({}));
  assert.deepEqual(g.posts, [{ type: "setJudgeModel", model: "opus", gt: 7777 }],
    "the echoed gesture, stamped through the clock (which has learned both refusals' storedGt)");
  assert.deepEqual(g.learned[g.learned.length - 1], ["judge-model", -1], "stamp('judge-model') minted it");
  assert.ok(t.children.findIndex((c) => c.className === "rs-stale-toast-act") < t.children.findIndex((c) => c.className === "rs-stale-toast-x"),
    "the action sits before the ✕");
});

test("no action when the echo's type is not the setting's, or when there is no echo (an older kernel)", () => {
  const g = lift();
  g.frame({ ...REFUSED, host: "web", gesture: { type: "setAutoNudge", enabled: true } });
  const { gesture: _g, ...noEcho } = REFUSED;
  g.frame({ ...noEcho, gt: 1001, host: "web" });
  assert.equal(g.box().children.length, 2);
  for (const t of g.box().children)
    assert.equal(t.children.find((c) => c.className === "rs-stale-toast-act"), undefined, "no Apply anyway");
  // and neither shows a refused value: an echo for another setting is not this setting's value, and no
  // echo carries none — the copy degrades to the value-less form
  assert.deepEqual(g.texts(), ["Triage model: not applied on web. Keeping fable.", "Triage model: not applied on web. Keeping fable."]);
});

test("an echo of an unexpected shape shows no refused value: plain Apply anyway, value-less copy", () => {
  // every emitter posts {type, <one value field>, gt}; a future two-field gesture reads as no value
  // rather than guessing which field is the pick
  const g = lift();
  g.frame({ ...REFUSED, host: "web", gesture: { type: "setJudgeModel", model: "opus", scope: "all" } });
  assert.deepEqual(g.texts(), ["Triage model: not applied on web. Keeping fable."]);
  const btn = g.box().children[0].children.find((c) => c.className === "rs-stale-toast-act")!;
  assert.equal(btn.textContent, "Apply anyway", "the action still rides: the echo's type is the setting's");
});

test("the open modal re-fills once per frame; a closed one never does", () => {
  const g = lift();
  g.frame({ ...REFUSED, host: "web" });
  g.frame({ ...REFUSED, host: "api" });
  assert.equal(g.fills(), 0, "closed: fill() runs on the next open anyway");
  g.p.hidden = false;
  g.frame({ ...REFUSED, host: "gpu1" });
  g.frame({ ...REFUSED, gt: 5, host: "gpu1" });
  assert.equal(g.fills(), 2, "open: the frame IS the event — one re-read per frame, folded or not");
});
