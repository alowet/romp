// DOCUMENTS OVER A REAL CHANNEL (the 0.17.1 fix, a contributor's second note on PR 2124; the two-owner case from the contributor's note on the
// fix): bundles of card-sections.ts, owners (feed documents) and a follower (the chat page), joined by Node's BroadcastChannel the way the
// shell's frames are joined by the browser's. The defect: a row pick outlived every feed map that lacked it, because the feed applied the
// row's set and answered nothing, so the chat page re-imposed and re-posted the pick and the feed persisted it again, per payload. With the
// acknowledgement: after a row pick the Collapsed flip leaves both documents empty, and five prunes after a row pick and Clear cost the
// owner one view-state write, not one per payload; with two owners (a shell feed pane and a standalone feed tab) a follower's pick is one set
// and one acknowledgement per owner and nothing more, since an acknowledgement is the owner's word and no owner answers it (a plain set in
// its place bounced between the owners without end: over 100,000 sets in a second in the contributor's probe). The module reads
// `window.BroadcastChannel`, so the stand-in window hands it Node's class; the bundle is built once per file from the source and loaded
// through a cleared require cache (one bundle, one module instance per document). HYGIENE: Node's channel holds the event loop, so every
// document is opened INSIDE its test's try block and an after hook closes every loaded instance's channel, tolerating a missing export
// (at the base the file hung to its time bound after its failures; in CI that is the job's cap), and removes the bundle's directory.
import { test, after } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { createRequire } from "node:module";
import { BroadcastChannel } from "node:worker_threads";

class T { nodeType = 3; parentNode: E | null = null; constructor(public textContent: string) {} }
class E {
  nodeType = 1; parentNode: E | null = null; childNodes: Array<E | T> = []; className = ""; title = ""; type = ""; isConnected = false;
  style: Record<string, string> = {}; dataset: Record<string, string | undefined> = {}; attrs = new Map<string, string>();
  constructor(public tagName: string) {}
  get classList() { const self = this; const set = () => new Set(self.className.split(/\s+/).filter(Boolean)); const write = (s: Set<string>) => { self.className = Array.from(s).join(" "); };
    return { add: (...cs: string[]) => { const s = set(); cs.forEach((c) => s.add(c)); write(s); }, remove: (...cs: string[]) => { const s = set(); cs.forEach((c) => s.delete(c)); write(s); },
             toggle: (c: string, on?: boolean) => { const s = set(); const want = on === undefined ? !s.has(c) : on; if (want) s.add(c); else s.delete(c); write(s); return want; }, contains: (c: string) => set().has(c) }; }
  get textContent(): string { return this.childNodes.map((n) => n.textContent).join(""); }
  set textContent(v: string | null) { this.childNodes = v ? [new T(v)] : []; }
  append(...ns: Array<E | T | string>) { for (const n of ns) this.childNodes.push(typeof n === "string" ? new T(n) : n); }
  appendChild(n: E | T) { this.childNodes.push(n); return n; }
  prepend(...ns: Array<E | T | string>) { this.childNodes.unshift(...ns.map((n) => typeof n === "string" ? new T(n) : n)); }
  replaceChildren(...ns: Array<E | T | string>) { this.childNodes = ns.map((n) => typeof n === "string" ? new T(n) : n); }
  setAttribute(k: string, v: string) { this.attrs.set(k, v); } getAttribute(k: string) { return this.attrs.get(k) ?? null; } removeAttribute(k: string) { this.attrs.delete(k); }
  querySelectorAll() { return [] as E[]; } querySelector() { return null; } addEventListener() {} removeEventListener() {}
}
(globalThis as any).document = { createElement: (tag: string) => new E(tag.toUpperCase()), createTextNode: (t: string) => new T(t), body: new E("BODY"), documentElement: new E("HTML"), addEventListener() {}, removeEventListener() {} };
(globalThis as any).window = { BroadcastChannel };   // the browser's channel, in Node's clothes

const tick = () => new Promise<void>((r) => setTimeout(r, 30));   // a delivery hop over Node's channel
const until = async (pred: () => boolean, ms: number): Promise<boolean> => { const t0 = Date.now(); while (!pred() && Date.now() - t0 < ms) await tick(); return pred(); };   // loop-ok: a PRESENCE wait, bounded by its deadline (the verifier's round two on the fix PR: counts read after a fixed number of ticks)

// the bundle of the module under test, built ONCE per file at run time into one temporary directory (a directory per test was never removed,
// three left per run: the manager's read of the fix PR); esbuild is loaded through a runtime require (createRequire), which the test bundler
// does not follow (its own API refuses to be bundled)
const req = createRequire(__filename);
let bundleDir: string | null = null, bundlePath: string | null = null;
function bundleOnce(): string {
  if (bundlePath) return bundlePath;
  const esbuild = req("esbuild");
  const src = path.resolve(process.cwd(), "..", "ui", "webview", "card-sections.ts");
  bundleDir = fs.mkdtempSync(path.join(os.tmpdir(), "romp-card-sections-"));
  bundlePath = path.join(bundleDir, "card-sections.js");
  esbuild.buildSync({ entryPoints: [src], bundle: true, format: "cjs", platform: "node", outfile: bundlePath, logLevel: "silent" });
  return bundlePath;
}
// every module instance this file loaded, so the after hook can close each one's channel whatever a test did before its own finally
const loaded: any[] = [];
function loadFresh(out: string): any { delete req.cache[req.resolve(out)]; const m = req(out); loaded.push(m); return m; }
const closeAll = (...ms: any[]) => { for (const m of ms) { try { m?.closeSectionSync?.(); } catch { /* closed already, or a module without the export */ } } };
after(() => {
  closeAll(...loaded); loaded.length = 0;
  if (bundleDir) fs.rmSync(bundleDir, { recursive: true, force: true });
  bundleDir = bundlePath = null;
});
function twoDocuments(): { owner: any; follower: any; writes: { n: number } } {
  const out = bundleOnce();
  const owner = loadFresh(out); const follower = loadFresh(out);
  const writes = { n: 0 };
  owner.configureSectionSync({ role: "owner", onChange: () => { writes.n++; } });
  follower.configureSectionSync({ role: "follower" });
  return { owner, follower, writes };
}

test("a row pick then the Collapsed flip: both documents end empty (the pick was acknowledged, so the map that lacks it governs)", async () => {
  let docs: { owner: any; follower: any; writes: { n: number } } | null = null;
  try {
    docs = twoDocuments(); const { owner, follower, writes } = docs;
    await tick();                                                   // the hello and the load-time map
    follower.setSectionChoice("i1", "bg");                          // the row picks
    await tick();
    assert.equal(owner.secChoice.get("i1"), "bg", "the owner applied and persisted the row's pick");
    const afterPick = writes.n;
    owner.replaceSectionChoices([]);                                // the Collapsed clear
    await tick(); await tick();
    assert.deepEqual([owner.secChoice.size, follower.secChoice.size], [0, 0], "both documents empty after the flip (before: the follower re-imposed the pick and the owner persisted it again)");
    assert.equal(writes.n, afterPick + 1, "the flip is one write; nothing came back");
  } finally { closeAll(docs?.owner, docs?.follower); }
});

test("a row pick then Clear: five prunes cost the owner one write, not one per payload", async () => {
  let docs: { owner: any; follower: any; writes: { n: number } } | null = null;
  try {
    docs = twoDocuments(); const { owner, follower, writes } = docs;
    await tick();
    owner.replaceSectionChoices([["i0", "stall"]]);                 // another item's standing pick, so the map is never the same as an empty one
    await tick();
    follower.setSectionChoice("i2", "bg");                          // the row picks
    await tick();
    const afterPick = writes.n;
    for (let i = 0; i < 5; i++) { owner.replaceSectionChoices([["i0", "stall"]], { quiet: true }); await tick(); }   // the prune, once the item left the live set, per payload
    assert.deepEqual([owner.secChoice.get("i2"), follower.secChoice.get("i2")], [undefined, undefined], "the dropped item is gone on both documents");
    assert.equal(writes.n, afterPick + 1, "one write for the five prunes (before: one per prune plus one per re-imposed pick)");
  } finally { closeAll(docs?.owner, docs?.follower); }
});

test("a pick made before any owner is up still stands when the owner comes up and posts its map", async () => {
  let follower: any = null, owner: any = null;
  try {
    const out = bundleOnce();
    follower = loadFresh(out); follower.configureSectionSync({ role: "follower" });
    follower.setSectionChoice("i3", "subgoals");                    // nobody hears it
    await tick();
    owner = loadFresh(out); owner.replaceSectionChoices([["i9", "bg"]], { quiet: true }); owner.configureSectionSync({ role: "owner" });   // the feed hydrates (no post: not yet the owner) and, configured, posts its map
    await tick(); await tick(); await tick();   // the map, the follower's re-post, the acknowledgement
    assert.deepEqual([follower.secChoice.get("i3"), follower.secChoice.get("i9")], ["subgoals", "bg"], "the follower took the map and kept its own pick");
    assert.equal(owner.secChoice.get("i3"), "subgoals", "and the owner has the pick, re-posted and acknowledged");
    owner.replaceSectionChoices([]);
    await tick(); await tick();
    assert.deepEqual([owner.secChoice.size, follower.secChoice.size], [0, 0], "and, acknowledged, it yields to a later map that lacks it");
  } finally { closeAll(owner, follower); }
});

test("two owners and a follower: a follower pick is one set and one acknowledgement per owner, an owner pick one set and none, and nothing more after a few ticks", async () => {
  // two owning documents of one origin (a shell feed pane and a standalone feed tab) with the chat page: counted on a spy channel of the test's
  // own. An acknowledgement in the shape of a plain set would be answered by the other owner, and that answer by the first, without end (the
  // contributor's probe: over 100,000 sets in one second after one chat pick); the counts here are exact and bounded
  const counts: Record<string, number> = {};
  let spy: BroadcastChannel | null = null, a: any = null, b: any = null, f: any = null;
  try {
    const out = bundleOnce();
    spy = new BroadcastChannel("romp-card-sections");
    spy.onmessage = (ev: unknown) => { const k = String(((ev as { data?: { kind?: string } }).data || {}).kind); counts[k] = (counts[k] || 0) + 1; };
    a = loadFresh(out); b = loadFresh(out); f = loadFresh(out);
    a.configureSectionSync({ role: "owner" }); b.configureSectionSync({ role: "owner" }); f.configureSectionSync({ role: "follower" });
    await tick(); await tick();                                     // the owners' load-time maps, the follower's hello and its answers
    for (const k of Object.keys(counts)) delete counts[k];
    f.setSectionChoice("i1", "bg");                                 // the row picks
    assert.ok(await until(() => (counts.ack || 0) === 2, 3000), "the second acknowledgement arrives (a bounded wait, not a count of ticks): " + JSON.stringify(counts));
    const afterPick = { ...counts };
    assert.deepEqual(afterPick, { set: 1, ack: 2 }, "one set from the follower, one acknowledgement from each owner, no map and no second set");
    assert.deepEqual([a.secChoice.get("i1"), b.secChoice.get("i1"), f.secChoice.get("i1")], ["bg", "bg", "bg"], "all three documents hold the pick");
    await tick(); await tick(); await tick();                       // the ABSENCE half stays time-bounded: nothing can prove a message will never come
    assert.deepEqual(counts, afterPick, "and nothing more after a few ticks");
    a.setSectionChoice("i2", "stall");                              // an owner picks (a press on a card)
    assert.ok(await until(() => (counts.set || 0) === 2, 3000), "the owner's set arrives: " + JSON.stringify(counts));
    await tick(); await tick(); await tick();                       // and the absence of any acknowledgement, time-bounded
    assert.deepEqual(counts, { set: 2, ack: 2 }, "an owner's set is acknowledged by nobody: one set, no ack");
    assert.deepEqual([b.secChoice.get("i2"), f.secChoice.get("i2")], ["stall", "stall"], "the other owner and the follower took it");
  } finally { try { spy?.close(); } catch { /* closed already */ } closeAll(a, b, f); }
});
