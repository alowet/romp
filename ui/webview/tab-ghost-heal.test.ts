// An ENDED session must leave the tab strip even when the kernel's one-shot `closed` frame never arrived
// (the 2026-08-11 ghost: a session the kernel had ended stayed on the dashboard looking alive — last status
// still "working", transcript cached, fully clickable — and only a manual reload cleared it).
//
// The chain that minted it, each link by design: pane JS state survives WS reconnects (the shim reconnects,
// never reloads); a client that stops draining is force-dropped at the send-queue byte cap (a frozen webview
// popout, a sleeping laptop), so it is exactly the client that is DISCONNECTED at the kill moment and misses
// the one-shot `closed`; and applyTabOrder's keep re-adopted any locally-known tab the kernel's order didn't
// carry — forever. The fix makes the CONTINUOUS tabOrder push the authority: an id any push has carried is
// kernel-owned (`kernelListed`), and a later push omitting it dismisses the tab with the same teardown the
// `closed` event runs. `closed` stays as the fast path.
//
// One difference since T236 (the user 2026-09-03): an OMISSION is an absence, not a report of an end — the
// same push shape also follows a boot-partial list or a collapsed liveness read — so the teardown it runs
// keeps the session's unsent composer draft stashed under its id (back with the session if it returns);
// only a genuine end (the user's ✕, the kernel's own `closed`) clears it. See draft-teardown.test.ts.
//
// The executed model below runs the real reconcileTabOrder through the whole miss-and-heal cycle with
// applyTabOrder's bookkeeping; the source pins hold that wiring in render.ts.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { reconcileTabOrder } from "./tab-order";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");

// A stand-in for the client around a session death: the sessions map, the render order, and applyTabOrder's
// kernelListed bookkeeping. dismiss() mirrors dismissSession's teardown surface (session + view go; the draft
// goes only for a genuine end, never for an omission).
function model() {
  let order: string[] = [];
  const sessions = new Map<string, { state: string }>();
  const drafts = new Map<string, string>();
  const kernelListed = new Set<string>();
  const dismissed: string[] = [];
  const dismiss = (id: string, why: "end" | "omitted") => {
    dismissed.push(id);
    sessions.delete(id);
    if (why === "end") drafts.delete(id);      // a genuine end clears; an omission stashes (T236)
    order = order.filter((x) => x !== id);
  };
  return {
    dismissed,
    session(id: string, state = "working") { sessions.set(id, { state }); if (!order.includes(id)) order.push(id); },
    draft(id: string, text: string) { drafts.set(id, text); },
    closedEvent(id: string) { dismiss(id, "end"); },     // the kernel's one-shot frame, when it DOES arrive
    // a kernel tabOrder push, with applyTabOrder's new bookkeeping: kernel-owned omissions dismiss first,
    // then the reconcile (whose keep no longer applies to kernel-owned ids), then the add-only record.
    push(kernel: string[]) {
      for (const id of order.slice()) if (kernelListed.has(id) && !kernel.includes(id)) dismiss(id, "omitted");
      order = reconcileTabOrder(kernel, order, (id) => sessions.has(id), (id) => kernelListed.has(id));
      for (const id of kernel) kernelListed.add(id);
    },
    tabs() { return order.slice(); },
    state(id: string) { return sessions.get(id)?.state ?? null; },
    hasDraft(id: string) { return drafts.has(id); },
  };
}

test("a session ended while the socket was down leaves the strip on the reconnect's first push", () => {
  const m = model();
  m.session("web"); m.session("api");
  m.push(["web", "api"]);                 // both kernel-owned
  // api is ended while this client's socket is down (frozen popout force-dropped at the queue cap): the
  // one-shot `closed` frame is LOST, api's session survives in the maps with its last live status…
  assert.equal(m.state("api"), "working", "the cached state still claims a live session");
  // …and the reconnect's resync push no longer carries it. Before the fix this push KEPT the tab (its
  // session was locally known), so the ended session sat on the strip looking alive until a manual reload.
  m.push(["web"]);
  assert.deepEqual(m.tabs(), ["web"], "the omission is the removal event — the ghost heals");
  assert.deepEqual(m.dismissed, ["api"], "…with the same teardown the closed event runs");
  assert.equal(m.state("api"), null, "no live-looking cached session left behind");
  m.push(["web"]);                        // and it STAYS healed on every later push
  assert.deepEqual(m.tabs(), ["web"]);
});

test("the omission teardown KEEPS the session's composer draft — an absence is not the user's close (T236)", () => {
  const m = model();
  m.session("web"); m.session("api");
  m.push(["web", "api"]);
  m.draft("api", "half-typed message");
  m.push(["web"]);
  assert.deepEqual(m.tabs(), ["web"], "the tab still goes");
  assert.equal(m.hasDraft("api"), true, "…but the draft is stashed under its id, back with the session if it returns");
  // the kernel's own closed frame — the session actually ended — is what clears it
  m.session("api"); m.push(["web", "api"]);
  m.closedEvent("api");
  assert.equal(m.hasDraft("api"), false, "a genuine end clears the draft (the user 2026-08-04)");
});

test("the closed event remains the fast path; the push after it has nothing left to do", () => {
  const m = model();
  m.session("web"); m.session("api");
  m.push(["web", "api"]);
  m.closedEvent("api");                   // delivered normally this time
  assert.deepEqual(m.tabs(), ["web"]);
  m.push(["web"]);                        // the confirming push neither re-adds nor double-dismisses
  assert.deepEqual(m.tabs(), ["web"]);
  assert.deepEqual(m.dismissed, ["api"]);
});

test("a revival re-adopts the same sid after a ghost heal (dead sessions revive with their history)", () => {
  const m = model();
  m.session("web"); m.session("api");
  m.push(["web", "api"]);
  m.push(["web"]);                        // api ended + healed
  m.session("api", "opening");            // revived: the kernel lists the SAME sid again
  m.push(["web", "api"]);
  assert.deepEqual(m.tabs(), ["web", "api"]);
  assert.equal(m.state("api"), "opening");
});

test("a create placeholder the kernel has never listed still survives unrelated pushes", () => {
  const m = model();
  m.session("web");
  m.push(["web"]);
  m.session("provisional:new");           // client-minted optimistic tab — the kernel knows nothing yet
  m.push(["web"]);                        // an unrelated push must not eat it (the just-arrived grace)
  assert.deepEqual(m.tabs(), ["web", "provisional:new"]);
  assert.deepEqual(m.dismissed, []);
});

// ---- the wiring in render.ts -------------------------------------------------------------------------

test("applyTabOrder dismisses kernel-owned omissions BEFORE reconciling, then records add-only", () => {
  // the drop loop sits between ackClosingTabs and the reconcile, and dismissSession is the shared teardown
  assert.match(RENDER,
    /ackClosingTabs\(kernelOrder, report\);[\s\S]{0,1600}?const omitted = new Set\(order\.filter\(\(id\) => kernelListed\.has\(id\) && !inKernel\.has\(id\) && !liveSet\.has\(id\)\)\);[^\n]*\n(?:.*\n){0,3}?\s*for \(const id of order\.slice\(\)\) \{\s*\n\s*if \(omitted\.has\(id\)\) dismissSession\(id, "omitted", omitted\);\s*\n\s*\}/,
    "kernel-owned tabs the push stopped carrying get the closed-event teardown");
  // the reconcile passes the kernelListed predicate, so the pure model enforces the same rule
  assert.match(RENDER,
    /reconcileTabOrder\(retainLiveOmitted\(kernelOrder, order, liveSet\), order,\s*\n\s*\(id\) => sessions\.has\(id\) \|\| tabMeta\.has\(id\),\s*\n\s*\(id\) => kernelListed\.has\(id\)\)/);   // the retained order (T258) feeds the reconcile
  // add-only, recorded AFTER the reconcile: dropping entries would hand a late stale `session` frame the
  // never-listed keep and re-mint the ghost
  assert.match(RENDER, /for \(const id of next\) order\.push\(id\);\s*\n\s*for \(const id of kernelOrder\) kernelListed\.add\(id\);/);
  const body = RENDER.match(/function dismissSession\(id: string, why: DismissWhy, doomed\?: ReadonlySet<string>\): void \{[\s\S]*?\n\}/);
  assert.ok(body, "dismissSession not found");
  assert.doesNotMatch(body![0], /kernelListed/, "the record outlives the dismiss (add-only set)");
});

test("reconcileTabOrder's keep is gated on the kernel never having listed the id", () => {
  const TAB_ORDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "tab-order.ts"), "utf8");
  assert.match(TAB_ORDER, /kernelSeen: \(id: string\) => boolean = \(\) => false/,
    "the predicate defaults off so single-shot callers keep the plain adopt-verbatim semantics");
  assert.match(TAB_ORDER, /!inKernel\.has\(id\) && known\(id\) && !kernelSeen\(id\)/,
    "extras keep = locally known AND never kernel-listed");
});
