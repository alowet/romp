// The federation manager REPLAYS the local kernel's views blob — on every merged tabOrder re-emit
// (localViews) and inside the merged lanes payload (perHostTl[LOCAL].views). Both stores adopt a
// blob only when its write sequence is at least the stored one (the 2026-09-05 review): the kernel's
// pusher builds frames from a warmed cache that can predate a write whose ack the pane already
// adopted, and a replay of that older blob would roll the pane back behind the ack. Executed against
// the real manager. Synthetic only (placeholder ids).
import { test } from "node:test";
import assert from "node:assert/strict";
import { FederationManager } from "./federation";
import { adoptViews, capsAdopts, announcedSeq, announcedAfter } from "./views-writes";

const U = "11111111-2222-3333-4444-555555555555";
const V = "99999999-8888-7777-6666-555555555555";

function withManager(fn: (fm: any, emitted: any[]) => void): void {
  const emitted: any[] = [];
  const store = new Map<string, string>();
  const g: any = globalThis;
  const hadWindow = "window" in g, prevWindow = g.window;
  const hadLS = "localStorage" in g, prevLS = g.localStorage;
  g.window = { dispatchEvent: (ev: any) => { if (ev && ev.data) emitted.push(ev.data); } };
  g.localStorage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); } };
  try { fn(new FederationManager(), emitted); } finally {
    if (hadWindow) g.window = prevWindow; else delete g.window;
    if (hadLS) g.localStorage = prevLS; else delete g.localStorage;
  }
}
const lastOf = (emitted: any[], type: string) => emitted.filter((m) => m && m.type === type).pop()!;
const views = (seq: number | undefined, active = "all") => ({ active, tags: [], ...(seq === undefined ? {} : { seq }) });

test("the replayed LOCAL views blob keeps the newest write sequence across tabOrder frames", () => {
  withManager((fm, emitted) => {
    fm.inbound("", { type: "tabOrder", order: [U], tabs: [{ id: U, name: "web" }], views: views(5) });
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 5);
    fm.inbound("", { type: "tabOrder", order: [U], tabs: [{ id: U, name: "web" }], views: views(4) });
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 5, "an older blob (the pusher's cache, delivered after a newer one) does not replace the stored one");
    fm.emitMergedOrder();
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 5, "a synthetic re-emit replays the newest");
    fm.inbound("", { type: "tabOrder", order: [U], tabs: [{ id: U, name: "web" }], views: views(6) });
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 6, "a newer blob lands as before");
    fm.inbound("", { type: "tabOrder", order: [U], tabs: [{ id: U, name: "web" }], views: views(undefined, "untagged") });
    assert.equal(lastOf(emitted, "tabOrder").views.active, "untagged", "a blob without a seq (a kernel from before the stamp) still adopts");
  });
});

test("a kernel's `caps` frame describes THAT kernel: the local one reaches the panes, a remote's is dropped", () => {
  withManager((fm, emitted) => {
    fm.inbound("TESTHOST", { type: "caps", caps: ["tagEdit"] });
    assert.equal(emitted.filter((m) => m.type === "caps").length, 0, "a remote kernel's capabilities would read as the local kernel's — the panes write only the local views store");
    fm.inbound("", { type: "caps", caps: ["tagEdit"] });
    assert.deepEqual(emitted.filter((m) => m.type === "caps"), [{ type: "caps", caps: ["tagEdit"] }], "the local kernel's frame is handed to the panes as-is");
  });
});

// The 2026-09-05 review: the local caps frame adopts the blob each store's
// gate last turned away when its viewsSeq (the seq of the blob the kernel's own connect push served) names it,
// and RE-EMITS before the caps frame is handed on — the panes see the local blob only through these re-emits,
// so the restored blob must meet their own gate before their caps door adopts it.
const typesOf = (emitted: any[]) => emitted.map((m) => m && m.type);
const lanes = (v: any) => ({ type: "data", data: { sessions: [{ id: U, name: "web" }], turns: {}, messages: [], judging: [], now: 1000, views: v } });
const order = (v: any) => ({ type: "tabOrder", order: [U], tabs: [{ id: U, name: "web" }], views: v });
test("the local kernel's `caps` frame adopts the blob each replayed store turned away when viewsSeq names it — the restarted kernel's connect push under an older seq — and re-emits it BEFORE the caps frame reaches the panes", () => {
  withManager((fm, emitted) => {
    fm.inbound("", order(views(1000)));
    fm.inbound("", lanes(views(1000)));
    fm.inbound("", { type: "caps", caps: ["tagEdit"], viewsSeq: 1000 });   // the load's caps frame: nothing was turned away, nothing is re-emitted
    assert.deepEqual(typesOf(emitted), ["tabOrder", "data", "caps"]);
    // the kernel restarted over a store restored from an older copy: its connect push carries seq 900
    fm.inbound("", order(views(900, "untagged")));
    fm.inbound("", lanes(views(900, "untagged")));
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 1000, "the gate turns the push away, as it must before the reconnect event…");
    assert.equal(lastOf(emitted, "data").data.views.seq, 1000, "…so the panes saw it wearing the stored blob");
    const n = emitted.length;
    fm.inbound("", { type: "caps", caps: ["tagEdit"], viewsSeq: 900 });
    assert.deepEqual(typesOf(emitted.slice(n)), ["tabOrder", "data", "caps"], "one re-emit per store that adopted, then the caps frame — in that order");
    const o = emitted[n], d = emitted[n + 1];
    assert.equal(o.views.seq, 900, "the merged order now carries the restored store's blob…");
    assert.equal(o.views.active, "untagged");
    assert.equal(o.reemit, true, "…as a synthetic re-emit (no host reported anything)");
    assert.equal(d.data.views.seq, 900, "…and so does the lanes payload");
    assert.deepEqual(d.data.sessions.map((s: any) => s.id), [U], "with its lanes intact");
    fm.inbound("", order(views(899)));
    fm.inbound("", lanes(views(899)));
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 900, "the store's own order gates again from the adopted seq");
    assert.equal(lastOf(emitted, "data").data.views.seq, 900);
    // a REMOTE kernel's caps frame is inert: it neither adopts the blobs just turned away nor re-emits
    const k = emitted.length;
    fm.inbound("TESTHOST", { type: "caps", caps: ["tagEdit"], viewsSeq: 899 });
    assert.equal(emitted.length, k, "a remote's caps frame emits nothing here");
    fm.emitMergedOrder();
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 900, "…and the replayed stores stand");
    fm.emitMergedTimeline(false);
    assert.equal(lastOf(emitted, "data").data.views.seq, 900);
    // the LOCAL caps frame naming them does adopt them — the same blobs a remote's frame left alone
    fm.inbound("", { type: "caps", caps: ["tagEdit"], viewsSeq: 899 });
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 899);
    assert.equal(lastOf(emitted, "data").data.views.seq, 899);
  });
});

test("a healthy reconnect keeps both stores' gates: the connect push is adopted, the caps frame names it and re-emits nothing, and a pusher frame built before a concurrent write is turned away whether it lands before or after the caps frame", () => {
  withManager((fm, emitted) => {
    fm.inbound("", order(views(1000)));
    fm.inbound("", lanes(views(1000)));
    // the socket came back on the same kernel; another dashboard's write landed meanwhile (seq 1001): the connect push is current
    fm.inbound("", order(views(1001, "untagged")));
    fm.inbound("", lanes(views(1001, "untagged")));
    // the pusher thread's frame, built from its cache before that write and enqueued BETWEEN the push and the caps
    // frame — the window an earlier fix left open: turned away and kept…
    fm.inbound("", order(views(1000)));
    fm.inbound("", lanes(views(1000)));
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 1001);
    assert.equal(lastOf(emitted, "data").data.views.seq, 1001);
    const n = emitted.length;
    fm.inbound("", { type: "caps", caps: ["tagEdit"], viewsSeq: 1001 });   // …and the caps frame names the connect push, not it
    assert.deepEqual(typesOf(emitted.slice(n)), ["caps"], "the kept frames' seq is not the one named: discarded, no re-emit, just the caps frame handed on");
    fm.emitMergedOrder();
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 1001, "the stores stand");
    fm.inbound("", order(views(1000)));                // the same stale frame landing AFTER the caps frame instead
    fm.inbound("", lanes(views(1000)));
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 1001, "turned away: the gate never opened, so the panes never see the older blob");
    assert.equal(lastOf(emitted, "data").data.views.seq, 1001);
    fm.inbound("", order(views(1001, "untagged")));
    fm.inbound("", lanes(views(1001, "untagged")));
    // that adoption let the kept blobs go: a later caps frame (another reconnect, same store) has nothing to adopt
    const k = emitted.length;
    fm.inbound("", { type: "caps", caps: ["tagEdit"], viewsSeq: 1001 });
    assert.deepEqual(typesOf(emitted.slice(k)), ["caps"]);
  });
});

test("a caps frame whose push served no views blob (viewsSeq null) adopts nothing and lets the kept blobs go; a frame without the field (an older kernel) adopts them outright", () => {
  withManager((fm, emitted) => {
    fm.inbound("", order(views(1000)));
    fm.inbound("", lanes(views(1000)));
    fm.inbound("", order(views(900)));                 // the restarted kernel's connect push under the restored store's seq: kept
    fm.inbound("", lanes(views(900)));
    let n = emitted.length;
    fm.inbound("", { type: "caps", caps: ["tagEdit"], viewsSeq: null });
    assert.deepEqual(typesOf(emitted.slice(n)), ["caps"], "nothing named: nothing adopted, nothing re-emitted");
    fm.emitMergedOrder();
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 1000);
    n = emitted.length;
    fm.inbound("", { type: "caps", caps: ["tagEdit"] });
    assert.deepEqual(typesOf(emitted.slice(n)), ["caps"], "the kept blobs were let go: a field-less frame finds nothing to adopt");
    // kept again, and a frame from a kernel before the field adopts it — the pre-field rule
    fm.inbound("", order(views(900, "untagged")));
    fm.inbound("", lanes(views(900, "untagged")));
    n = emitted.length;
    fm.inbound("", { type: "caps", caps: ["tagEdit"] });
    assert.deepEqual(typesOf(emitted.slice(n)), ["tabOrder", "data", "caps"]);
    assert.equal(emitted[n].views.seq, 900); assert.equal(emitted[n + 1].data.views.seq, 900);
  });
});

// The 2026-09-05 review: the caps frame's viewsSeq is also the kernel's announcement of its current store (the served blob's seq, or
// the store's current seq when the connect push carried no views frame; null only when the kernel has no store at
// all). A reconnect whose push carried no blob (a chat page's sentinel cycle sends no tabOrder) keeps nothing for
// the earlier rule to match; each replayed store remembers the announced seq in one slot until its next adoption that
// moves the store (a re-arrival of the stored blob leaves it), and
// the later blob at exactly that seq — the pusher's next frame after a restart over a store restored from an older
// copy — is adopted below the stored one.
test("the local caps frame's viewsSeq is remembered when a store kept nothing it names: the LATER blob at that seq is adopted below the stored one, another lower seq is turned away, the slot clears on an adoption that moves the store, and null, a missing field and a remote's frame announce nothing", () => {
  withManager((fm, emitted) => {
    fm.inbound("", order(views(1000)));
    fm.inbound("", lanes(views(1000)));
    let n = emitted.length;
    fm.inbound("", { type: "caps", caps: ["tagEdit"], viewsSeq: 900 });   // the sentinel cycle's push carried no blob; the restored store's current seq is 900
    assert.deepEqual(typesOf(emitted.slice(n)), ["caps"], "nothing kept: nothing adopted, nothing re-emitted on the frame itself");
    fm.inbound("", order(views(899)));
    fm.inbound("", lanes(views(899)));
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 1000, "a frame at another lower seq is a stale frame: turned away");
    assert.equal(lastOf(emitted, "data").data.views.seq, 1000);
    fm.inbound("", order(views(900, "untagged")));     // the pusher's next cycle: the restored store under its old seq
    fm.inbound("", lanes(views(900, "untagged")));
    const o = lastOf(emitted, "tabOrder"), d = lastOf(emitted, "data");
    assert.equal(o.views.seq, 900, "the announced seq IS the store the kernel said it holds: adopted below the stored one, and the merged order carries it");
    assert.equal(o.views.active, "untagged");
    assert.equal(d.data.views.seq, 900, "…and so does the lanes payload");
    assert.deepEqual(d.data.sessions.map((s: any) => s.id), [U]);
    fm.inbound("", order(views(899)));
    fm.inbound("", lanes(views(899)));
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 900, "the store's own order gates again from the adopted seq");
    assert.equal(lastOf(emitted, "data").data.views.seq, 900);
    fm.emitMergedOrder(); fm.emitMergedTimeline(false);
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 900, "a synthetic re-emit replays the adopted store");
    assert.equal(lastOf(emitted, "data").data.views.seq, 900);
    // the slot clears on an adoption that moves the store: a write landing before the announced blob arrives stamps the store past it
    fm.inbound("", { type: "caps", caps: ["tagEdit"], viewsSeq: 800 });
    fm.inbound("", order(views(1100)));
    fm.inbound("", lanes(views(1100)));
    fm.inbound("", order(views(800)));                 // the pusher's frame built before that write
    fm.inbound("", lanes(views(800)));
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 1100, "the announced seq is no longer a door once the store moved past it");
    assert.equal(lastOf(emitted, "data").data.views.seq, 1100);
    // null (the kernel has no store at all) announces nothing, and an earlier announcement does not outlive the frame
    fm.inbound("", { type: "caps", caps: ["tagEdit"], viewsSeq: 700 });
    fm.inbound("", { type: "caps", caps: ["tagEdit"], viewsSeq: null });
    fm.inbound("", order(views(700)));
    fm.inbound("", lanes(views(700)));
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 1100);
    assert.equal(lastOf(emitted, "data").data.views.seq, 1100);
    // a frame without the field (a kernel from before it) announces nothing either
    fm.inbound("", { type: "caps", caps: ["tagEdit"], viewsSeq: 650 });
    fm.inbound("", { type: "caps", caps: ["tagEdit"] });
    fm.inbound("", order(views(650)));
    fm.inbound("", lanes(views(650)));
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 1100);
    assert.equal(lastOf(emitted, "data").data.views.seq, 1100);
    // a REMOTE kernel's caps frame announces nothing here: the panes' stores are the local kernel's
    fm.inbound("TESTHOST", { type: "caps", caps: ["tagEdit"], viewsSeq: 600 });
    fm.inbound("", order(views(600)));
    fm.inbound("", lanes(views(600)));
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 1100);
    assert.equal(lastOf(emitted, "data").data.views.seq, 1100);
  });
});

test("…and across lanes payloads: an older LOCAL data frame keeps the stored views while its lanes still land", () => {
  withManager((fm, emitted) => {
    const lanes = (ids: string[], now: number, v: any) => ({ type: "data", data: { sessions: ids.map((id) => ({ id, name: id.slice(0, 4) })), turns: {}, messages: [], judging: [], now, views: v } });
    fm.inbound("", lanes([U], 1000, views(5)));
    fm.inbound("", lanes([U, V], 1001, views(4)));
    const d = lastOf(emitted, "data").data;
    assert.equal(d.views.seq, 5, "the stored blob stands");
    assert.deepEqual(d.sessions.map((s: any) => s.id), [U, V], "…and the frame's lanes still land — the blob is the only field the seq governs");
    assert.equal(d.now, 1001);
    fm.inbound("", lanes([U, V], 1002, views(7)));
    assert.equal(lastOf(emitted, "data").data.views.seq, 7);
    // a REMOTE host's lanes payload is not the local blob's store at all
    fm.inbound("TESTHOST", lanes([V], 900, views(1)));
    assert.equal(lastOf(emitted, "data").data.views.seq, 7, "a remote kernel's views are its own dashboards' prefs; the merge carries the local blob");
  });
});

// The 2026-09-05 review: the slot is cleared only by an adoption that CHANGES the stored blob. A re-arrival of the blob a store
// already holds (the same seq) is no new information and leaves the slot, so the blob at the announced seq is still
// adopted after it; a newer write still clears it (the earlier honesty rule).
test("a same-seq re-arrival leaves each store's announced slot standing — the announced blob is still adopted after it; a newer blob clears it", () => {
  withManager((fm, emitted) => {
    fm.inbound("", order(views(1000)));
    fm.inbound("", lanes(views(1000)));
    fm.inbound("", { type: "caps", caps: ["tagEdit"], viewsSeq: 900 });
    fm.inbound("", order(views(1000, "untagged")));   // the blob each store holds, arriving again
    fm.inbound("", lanes(views(1000, "untagged")));
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 1000);
    assert.equal(lastOf(emitted, "tabOrder").views.active, "untagged", "adopted (equal seq), as ever");
    assert.equal(lastOf(emitted, "data").data.views.active, "untagged");
    fm.inbound("", order(views(900, "site")));        // the pusher's next frame: the restored store under its old seq
    fm.inbound("", lanes(views(900, "site")));
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 900, "the slot stood through the re-arrival: the announced store is adopted below the stored one");
    assert.equal(lastOf(emitted, "data").data.views.seq, 900);
    fm.inbound("", order(views(900)));                // the adopted blob again: the ordinary rule, nothing to a spent slot
    fm.inbound("", lanes(views(900)));
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 900);
    // a newer write still clears it
    fm.inbound("", { type: "caps", caps: ["tagEdit"], viewsSeq: 800 });
    fm.inbound("", order(views(900)));                // held again: the slot stands…
    fm.inbound("", lanes(views(900)));
    fm.inbound("", order(views(1100)));               // …until the store moves
    fm.inbound("", lanes(views(1100)));
    fm.inbound("", order(views(800)));                // the pusher's frame built before that write
    fm.inbound("", lanes(views(800)));
    assert.equal(lastOf(emitted, "tabOrder").views.seq, 1100, "the newer write cleared the slot: 800 is the stale frame it looks like");
    assert.equal(lastOf(emitted, "data").data.views.seq, 1100);
  });
});

// The 2026-09-05 review's last failure, executed end to end. A PANE behind the router fills its slot from the same caps frame the router
// does, but sees the local blob only through the router's re-emits — and every merged re-emit (a remote host's push
// or lanes payload, a `closed` frame, a view-order storage event, a host drop) hands it the router's STORED blob at
// the pane's own held seq. The earlier clear on any adoption spent the pane's slot on that same-seq adoption; the pusher's frame then reached
// the router (adopted through its intact slot, re-emitted at the announced seq) and the pane turned it away: router
// 900, pane 1000, silently, until the next write. The gates below are the composition render.ts's takeViews /
// onKernelCaps and the timeline's _takeViews / setCaps use (views-writes.test.ts pins the former; timeline-views-
// ack.test.ts drives the real panel behind the real router), fed every frame the real manager dispatches.
function paneGate() {
  const p = {
    held: null as any, rejected: null as any, slot: null as number | null,
    take(v: any) { if (!v) return; if (adoptViews(p.held, v, p.slot)) { p.slot = announcedAfter(p.held, v, p.slot); p.held = v; p.rejected = null; } else p.rejected = v; },
    caps(m: any) { const adopted = capsAdopts(p.rejected, m.viewsSeq); if (adopted) p.held = p.rejected; p.slot = adopted ? null : announcedSeq(m.viewsSeq); p.rejected = null; },
  };
  return p;
}
function withPanes(fn: (fm: any, chat: any, tl: any, emitted: any[]) => void): void {
  withManager((fm, emitted) => {
    const chat = paneGate(), tl = paneGate();
    const w = (globalThis as any).window, dispatch = w.dispatchEvent;
    w.dispatchEvent = (ev: any) => {
      dispatch(ev);
      const m = ev && ev.data; if (!m) return;
      if (m.type === "tabOrder") chat.take(m.views);
      else if (m.type === "data" && m.data) tl.take(m.data.views);
      else if (m.type === "caps") { chat.caps(m); tl.caps(m); }
    };
    fn(fm, chat, tl, emitted);
  });
}
const remoteOrder = () => ({ type: "tabOrder", order: [V], tabs: [{ id: V, name: "api" }], views: views(5) });
const remoteLanes = () => ({ type: "data", data: { sessions: [{ id: V, name: "api" }], turns: {}, messages: [], judging: [], now: 1000, views: views(5) } });
const betweens: [string, (fm: any) => void][] = [
  ["no re-emit between (the earlier case)", () => {}],
  ["a remote host's tabOrder push", (fm) => fm.inbound("TESTHOST", remoteOrder())],
  ["a remote host's lanes payload", (fm) => fm.inbound("TESTHOST", remoteLanes())],
  ["a `closed` frame", (fm) => fm.inbound("", { type: "closed", id: U })],
  ["a synthetic re-emit (a view-order storage event, a host drop)", (fm) => { fm.emitMergedOrder(); fm.emitMergedTimeline(false); }],
];
for (const [what, between] of betweens) {
  test("the panes behind the router adopt the restored store after a sentinel-cycle reconnect with " + what, () => {
    withPanes((fm, chat, tl, emitted) => {
      fm.inbound("", order(views(1000)));
      fm.inbound("", lanes(views(1000)));
      fm.inbound("", { type: "caps", caps: ["tagEdit"], viewsSeq: 1000 });
      fm.inbound("TESTHOST", remoteOrder()); fm.inbound("TESTHOST", remoteLanes());   // a remote host federated in
      assert.equal(chat.held.seq, 1000); assert.equal(tl.held.seq, 1000);
      assert.equal(chat.slot, null); assert.equal(tl.slot, null);
      fm.inbound("", { type: "caps", caps: ["tagEdit"], viewsSeq: 900 });   // the restart over a restored store, met on a sentinel cycle: nothing kept anywhere
      assert.equal(chat.slot, 900); assert.equal(tl.slot, 900);
      between(fm);
      assert.equal(chat.held.seq, 1000); assert.equal(tl.held.seq, 1000);
      assert.equal(chat.slot, 900, "a re-emit hands the pane its own held blob again: the slot stands");
      assert.equal(tl.slot, 900);
      fm.inbound("", order(views(900, "site")));   // the local pusher's next frame: the restored store under its old seq
      fm.inbound("", lanes(views(900, "site")));
      assert.equal(lastOf(emitted, "tabOrder").views.seq, 900, "the router adopts it through its slot…");
      assert.equal(lastOf(emitted, "data").data.views.seq, 900);
      assert.equal(chat.held.seq, 900, "…and so does the chat pane, from the router's re-emit");
      assert.equal(chat.held.active, "site");
      assert.equal(tl.held.seq, 900, "…and the timeline pane, from the merged lanes payload");
      assert.equal(chat.slot, null); assert.equal(tl.slot, null);
      between(fm);
      assert.equal(chat.held.seq, 900); assert.equal(tl.held.seq, 900);
    });
  });
}
