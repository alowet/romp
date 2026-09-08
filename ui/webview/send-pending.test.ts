// Send durability on the client (the 2026-09-05/06 audits). Two things went wrong at once: a send fed
// into a running turn is taken by the CLI at a later tool boundary and placed at its SEND time, so the
// pending bubble at the bottom vanished and the message reappeared higher up with no cue; and the
// client's bubble had a 20 s lifetime, so when the kernel's own echo was pruned early the send simply
// looked delivered. Now: (1) a pending send has NO lifetime — it ends on a landing, the kernel's
// never-delivered verdict, or the user's ✕; (2) a landed absorbed atom wears a "joined mid-turn" header
// and, when it landed above the tail, leaves a cue where the bubble sat ("delivered into the running
// turn at HH:MM · jump"); (3) every composer send posts a clientDiag breadcrumb (never the text).
// The 2026-09-06 adversarial review then fixed the decision's frame: (4) every verdict is read from the
// events AFTER the send's anchor, never from a 30-event tail count; (5) the cue anchors on a RENDERED
// event; (6) the lost verdict shares the anchor; (7) exact text, one landing per send; (8) a connection
// drop repaints once; (9) the bare label is per bubble; (10) the kernel's own copy clears "not confirmed".
// Round 3 of that review: (11) receipt is attributed per send, like landings; (12) the ✕ removes the
// bubble's own entry; (13) a stamp taken late reads the events' own times. Round 4: (14) a late stamp
// presumes the frame's newest queued copy of its text is its own (the queued bubble carries no stamp).
// The decisions are executed through send-pending.ts; the DOM half is pinned in render.ts/styles.css.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { newPending, pendingBody, reconcilePending, dropPending, cueAnchor, landedIn, provisionalIn, bareGroupLabel, type TailEvent, type PendingSend } from "./send-pending";

const read = (f: string) => fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", f), "utf8");
const RENDER = read("render.ts");
const CSS = read("styles.css");
const T0 = 1_700_000_000_000;
const TEXT = "rename this to fetch_notes";

// The press: registerOptimistic reconciles the fresh entry against the tail as it stands BEFORE any
// kernel round-trip, which stamps the anchor. Every scenario below starts there.
const press = (tail: TailEvent[], ...texts: string[]): PendingSend[] => {
  const list = texts.map((t, i) => newPending(t, undefined, T0 + i));
  reconcilePending(tail, list);
  return list;
};
const filler = (n: number, prefix = "f"): TailEvent[] =>
  Array.from({ length: n }, (_, i) => (i % 3 === 0 ? { kind: "thinking", uuid: `${prefix}${i}` } : i % 3 === 1 ? { kind: "tool", uuid: `${prefix}${i}` } : { kind: "assistant", md: "…", uuid: `${prefix}${i}` }));

// ── (1) no lifetime ──────────────────────────────────────────────────────────────────────────────

test("a pending send survives past 20 s — and past any time — without confirmation", () => {
  const list = press([{ kind: "assistant", md: "still working on the earlier step", uuid: "a0" }], TEXT);
  // nothing happens for a minute, then an hour: the wall clock moves on and the kernel's stamps move on
  // with it, and the decision reads neither
  const realNow = Date.now;
  try {
    for (const later of [T0 + 21_000, T0 + 60_000, T0 + 3_600_000]) {
      Date.now = () => later;
      const r = reconcilePending([
        { kind: "assistant", md: "still working on the earlier step", uuid: "a0" },
        { kind: "assistant", md: "…", uuid: "a-" + later, ts: new Date(later).toISOString() },
      ], list);
      assert.equal(r.keep.length, 1, `still pending at +${(later - T0) / 1000}s`);
      assert.equal(r.inject.length, 1, "…and still shown: nothing in the payload accounts for it");
    }
  } finally {
    Date.now = realNow;
  }
  assert.doesNotMatch(RENDER, /OPT_TTL_MS/, "the 20 s backstop is gone from render.ts");
});

test("it clears on the kernel's echo (suppressed) and ends on the landing (retired, with the index)", () => {
  const list = press([{ kind: "assistant", md: "…", uuid: "a1" }], TEXT);
  let r = reconcilePending([{ kind: "assistant", md: "…", uuid: "a1" }, { kind: "user", md: TEXT, uuid: "echo:1" }], list);
  assert.equal(r.keep.length, 1, "the kernel's provisional never retires the entry");
  assert.equal(r.inject.length, 0, "…but ours steps aside while it is visible");
  r = reconcilePending([
    { kind: "assistant", md: "…", uuid: "a1" },
    { kind: "user", md: TEXT, uuid: "att1", absorbed: true },
    { kind: "tool", uuid: "t9" },
  ], list);
  assert.equal(r.keep.length, 0, "a landed user atom ends it");
  assert.deepEqual(r.landed.map((l) => l.idx), [1], "…naming the landed event, for the cue");
});

test("an image send lands even though the paths are gone from the text", () => {
  // the composer appends the dragged paths to the typed text; the CLI rewrites them to "[Image #N]" and the
  // kernel strips the placeholders and renders the pictures — so the sent text can never match verbatim
  const text = 'compare with the old one\n/tmp/notes-api/docs/before.png "/tmp/notes-api/docs/after one.png"';
  const imgs = ["/tmp/notes-api/docs/before.png", "/tmp/notes-api/docs/after one.png"];
  assert.equal(pendingBody(text, imgs), "compare with the old one");
  const p = newPending(text, imgs, T0);
  const landed: TailEvent = { kind: "user", uuid: "u7", md: "compare with the old one", images: [{}, {}] };
  assert.equal(landedIn(landed, p), true);
  assert.equal(landedIn({ kind: "user", uuid: "u8", md: "compare with the old one" }, p), false,
    "the body alone is not enough — the landing must carry the pictures");
  assert.equal(landedIn({ kind: "user", uuid: "u9", md: 'compare with the old one\n""', images: [{}, {}] }, p), true,
    "a quoted path's leftover quotes do not break the match");
  assert.equal(landedIn({ kind: "user", uuid: "u10", md: "compare with the old one, then the new", images: [{}] }, p), false,
    "exact body, not a substring");
  assert.equal(landedIn({ kind: "user", uuid: "u11", md: text }, p), true, "paths landing verbatim (an SDK session) match the text itself");
  reconcilePending([{ kind: "assistant", md: "…", uuid: "a1" }], [p]);   // the press: anchored on a tail without it
  const r = reconcilePending([{ kind: "assistant", md: "…", uuid: "a1" }, landed], [p]);
  assert.equal(r.keep.length, 0, "the pictures-bearing atom after the anchor is the landing");
});

test("the kernel's never-delivered verdict ends the entry — its bubble carries the text and the resend", () => {
  const list = press([{ kind: "assistant", md: "…", uuid: "a1" }], TEXT);
  const r = reconcilePending([{ kind: "assistant", md: "…", uuid: "a1" }, { kind: "user", md: TEXT, uuid: "echo:1", undelivered: true }], list);
  assert.equal(r.keep.length, 0);
  assert.equal(r.lost.length, 1);
  assert.equal(r.inject.length, 0, "never a 'sending…' bubble beside a 'never delivered' one");
  // the kernel's undelivered bubble is the resend path: copy to composer / dismiss (undelivered-echo.test.ts)
  assert.match(RENDER, /re\.dataset\.act = "echorestore";/);
});

test("a connection drop marks unconfirmed sends 'not confirmed' — an event, and reversible by a confirmation", () => {
  assert.match(RENDER, /window\.addEventListener\("romp:wsdown", \(\) => markPendingLost\("connection"\)\);/);
  assert.match(RENDER, /if \(m\.type === "pipeState"\) \{ if \(!m\.up\) markPendingLost\("connection"\);/,
    "the VS Code pipe's down edge too — it never fires romp:wsdown");
  assert.match(RENDER, /function markPendingLost\(why: string\): void \{[\s\S]{0,600}?for \(const p of list\) if \(!p\.lost && !p\.received\) \{ p\.lost = why; changed = true; \}/);
  // the bubble says so, in the bare group's own label and on the bubble; ✕ stays the way back
  assert.match(RENDER, /if \(t\.optimistic && t\.lost\) bubble\.title = "not confirmed — the connection dropped after this was sent; ✕ moves it back to the composer to send again";/);
  assert.match(CSS, /\.queued-head \.queued-count \.lost \{ color: var\(--warn\); \}/);
  // a confirmation after the reconnect retires it like any other: the flag is display-only
  const list = press([{ kind: "assistant", md: "…", uuid: "a1" }], "go ahead");
  list[0].lost = "connection";
  const r = reconcilePending([{ kind: "assistant", md: "…", uuid: "a1" }, { kind: "user", md: "go ahead", uuid: "u1" }], list);
  assert.equal(r.keep.length, 0);
});

// ── (4) the anchor: verdicts are read after the send, never from a tail count ─────────────────────

test("a landing 100 events above the tail still ends the bubble — the scan is bounded by the send's anchor, not a count", () => {
  const before: TailEvent[] = [{ kind: "user", md: "first ask", uuid: "u0" }, ...filler(12, "b"), { kind: "tool", uuid: "t-last" }];
  const list = press(before, TEXT);
  assert.equal(list[0].at?.after, "t-last", "anchored on the last stable kernel event at the press");
  list[0].lost = "connection";                   // the socket dropped while the turn ran on
  // the reconnect's full frame: the absorbed atom sits at its SEND time, a hundred events above the tail
  const after: TailEvent[] = [...before, { kind: "user", md: TEXT, uuid: "att1", absorbed: true }, ...filler(100, "g")];
  const r = reconcilePending(after, list);
  assert.equal(r.keep.length, 0, "the landing is after the anchor, wherever the tail has grown to");
  assert.deepEqual(r.landed.map((l) => l.idx), [before.length]);
  // the same depth for the kernel's never-delivered verdict
  const list2 = press(before, TEXT);
  const r2 = reconcilePending([...before, { kind: "user", md: TEXT, uuid: "echo:9", undelivered: true }, ...filler(100, "g")], list2);
  assert.equal(r2.lost.length, 1);
});

test("an anchor that left the resident window (the transcript grew past the wire tail) means everything resident is later", () => {
  const list = press([{ kind: "assistant", md: "…", uuid: "old-anchor" }], TEXT);
  // the next full frame is a re-windowed tail that no longer holds the anchor event
  const r = reconcilePending([...filler(40, "w"), { kind: "user", md: TEXT, uuid: "u-new" }, ...filler(5, "z")], list);
  assert.equal(r.keep.length, 0);
  assert.equal(r.landed[0].idx, 40);
  // and a send into an empty transcript has nothing to anchor on: the head is the start
  const list2 = press([], TEXT);
  assert.equal(list2[0].at?.after, null);
  assert.equal(reconcilePending([{ kind: "user", md: TEXT, uuid: "u1" }], list2).landed.length, 1);
});

test("what was already there at the press is background: an older identical message, a kernel echo, a queued copy", () => {
  const tail: TailEvent[] = [
    { kind: "user", md: TEXT, uuid: "u-old" },
    { kind: "assistant", md: "done", uuid: "a1" },
    { kind: "user", md: TEXT, uuid: "echo:prev" },
    { kind: "queued", texts: [{ md: TEXT }] },
  ];
  const list = press(tail, TEXT);
  assert.equal(list[0].at?.after, "a1", "the anchor skips the kernel's echo: it is replaced when its text lands");
  assert.deepEqual(list[0].at?.seen, ["u-old", "echo:prev"]);
  assert.equal(list[0].at?.queued, 1);
  const r = reconcilePending(tail, list);
  assert.equal(r.keep.length, 1, "not retired by the older copy");
  assert.equal(list[0].received, undefined, "the old echo and the old queued copy prove nothing about THIS send");
  assert.equal(r.inject.length, 1, "…and cover nothing: our bubble shows beside the older copies (two sends, two bubbles)");
});

// ── (5) the cue anchors on a rendered event ──────────────────────────────────────────────────────

test("cueAnchor: the last kernel event after the landed atom, or null when it landed at the tail", () => {
  const events: TailEvent[] = [
    { kind: "user", uuid: "u1", md: "first comment" },
    { kind: "user", uuid: "att1", md: "second comment", absorbed: true },
    { kind: "tool", uuid: "t1" },
    { kind: "tool", uuid: "t2" },
    { kind: "user", uuid: "echo:9", md: "a third send, still pending at the kernel" },
    { kind: "queued", uuid: "optimistic:123", texts: [{ md: "ours" }] },
  ];
  assert.equal(cueAnchor(events, 1), "t2", "under the event the bubble sat under — never our injection or the kernel's echo");
  assert.equal(cueAnchor(events.slice(0, 2), 1), null, "landed AT the tail: the swap was in place, no cue owed");
  assert.equal(cueAnchor([events[0], events[1], { kind: "tool" }], 1), null, "nothing stable to hang it on");
});

test("cueAnchor skips what the chat does not draw: a thinking tail anchors on the tool before it in compact mode", () => {
  const events: TailEvent[] = [
    { kind: "user", uuid: "u1", md: "first comment" },
    { kind: "user", uuid: "att1", md: "second comment", absorbed: true },
    { kind: "tool", uuid: "t1" },
    { kind: "thinking", uuid: "th1" },
  ];
  const compact = (e: TailEvent) => e.kind !== "thinking";
  assert.equal(cueAnchor(events, 1, compact), "t1", "compact mode hides thinking — the cue needs an item that renders");
  assert.equal(cueAnchor(events, 1), "th1", "full mode draws the thinking block, so the bubble did sit under it");
  assert.equal(cueAnchor([events[0], events[1], events[3]], 1, compact), null, "only hidden events after the landing: no place for a cue");
  // render.ts hands over the current mode's rule, and compact mode is what hides thinking (compact.ts)
  assert.match(RENDER, /const cueRendered = \(e: TailEvent\): boolean => !\(settings\.compact && e\.kind === "thinking"\);/);
  assert.match(RENDER, /const after = cueAnchor\(s\.events as TailEvent\[\], idx, cueRendered\);/);
});

// ── (6) the lost verdict shares the anchor ───────────────────────────────────────────────────────

test("a resend of a never-delivered message is not retired by the old verdict — only a verdict after the send counts", () => {
  // the flow the never-delivered bubble offers: copy to composer, Enter — the old bubble is still in the tail
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }, { kind: "user", md: TEXT, uuid: "echo:old", undelivered: true }];
  const list = press(tail, TEXT);
  let r = reconcilePending(tail, list);
  assert.equal(r.lost.length, 0, "the old verdict is about the old send");
  assert.equal(r.keep.length, 1);
  assert.equal(r.inject.length, 1, "…and the old verdict is not a provisional either: our bubble shows");
  assert.equal(provisionalIn(tail[1], list[0]), false, "a never-delivered echo never suppresses");
  // the kernel's echo for the resend, then ITS verdict — that one ends the entry
  r = reconcilePending([...tail, { kind: "user", md: TEXT, uuid: "echo:new" }], list);
  assert.equal(r.inject.length, 0);
  r = reconcilePending([...tail, { kind: "user", md: TEXT, uuid: "echo:new", undelivered: true }], list);
  assert.equal(r.lost.length, 1);
  // a shorter send that the old never-delivered text merely contains is not its resend at all
  const list2 = press([{ kind: "user", md: "ok, go ahead and rename it", uuid: "echo:old", undelivered: true }], "go ahead");
  assert.equal(reconcilePending([{ kind: "user", md: "ok, go ahead and rename it", uuid: "echo:old", undelivered: true }], list2).keep.length, 1);
});

// ── (7) exact text, one landing per send ─────────────────────────────────────────────────────────

test("two identical sends in flight: the first landing retires the first, the second the second — across pushes", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  const list = press(tail, "continue", "continue");
  let r = reconcilePending([...tail, { kind: "user", md: "continue", uuid: "u1", absorbed: true }, { kind: "tool", uuid: "t1" }], list);
  assert.equal(r.landed.length, 1, "one landing, one entry");
  assert.equal(r.landed[0].p, list[0], "…the earlier send");
  assert.equal(r.keep.length, 1);
  assert.equal(r.inject.length, 1, "the second still shows: its message has not landed");
  // the next push (the first entry is gone from the list): the claimed landing stays claimed
  r = reconcilePending([...tail, { kind: "user", md: "continue", uuid: "u1", absorbed: true }, { kind: "tool", uuid: "t1" }], r.keep);
  assert.equal(r.keep.length, 1, "the first send's landing does not retire the second");
  r = reconcilePending([...tail, { kind: "user", md: "continue", uuid: "u1", absorbed: true }, { kind: "tool", uuid: "t1" }, { kind: "user", md: "continue", uuid: "u2" }], r.keep);
  assert.equal(r.landed.length, 1);
  assert.equal(r.landed[0].idx, 3, "the second landing is the second send's");
  // both landing in one push: attributed in order
  const list2 = press(tail, "continue", "continue");
  r = reconcilePending([...tail, { kind: "user", md: "continue", uuid: "u1" }, { kind: "user", md: "continue", uuid: "u2" }], list2);
  assert.deepEqual(r.landed.map((l) => [l.p, l.idx]), [[list2[0], 1], [list2[1], 2]]);
});

test("exact text: a pending 'test' is not retired when 'test the continue button' lands, nor the reverse", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  const list = press(tail, "test", "test the continue button");
  let r = reconcilePending([...tail, { kind: "user", md: "test the continue button", uuid: "u1" }], list);
  assert.deepEqual(r.landed.map((l) => l.p.text), ["test the continue button"]);
  assert.deepEqual(r.keep.map((p) => p.text), ["test"]);
  r = reconcilePending([...tail, { kind: "user", md: "test the continue button", uuid: "u1" }, { kind: "user", md: "test", uuid: "u2" }], r.keep);
  assert.deepEqual(r.landed.map((l) => [l.p.text, l.idx]), [["test", 2]]);
  // edge whitespace is the one tolerance: the composer trims, the kernel strips
  assert.equal(landedIn({ kind: "user", md: "  test\n", uuid: "u3" }, newPending("test")), true);
  // the kernel's echo and queued bubble are matched the same way
  const p = newPending("test");
  assert.equal(provisionalIn({ kind: "user", md: "test the continue button", uuid: "echo:1" }, p), false);
  assert.equal(provisionalIn({ kind: "queued", texts: [{ md: "test the continue button" }] }, p), false);
  assert.equal(provisionalIn({ kind: "queued", texts: [{ md: "test" }] }, p), true);
});

// ── (8) a connection drop repaints once ──────────────────────────────────────────────────────────

test("markPendingLost repaints only when an entry actually changed — the shim fires the down edge on every redial", () => {
  const fn = RENDER.slice(RENDER.indexOf("function markPendingLost("), RENDER.indexOf("\n}\n", RENDER.indexOf("function markPendingLost(")));
  assert.match(fn, /let changed = false;/);
  assert.match(fn, /if \(!changed\) continue;/, "an unchanged session is neither reconciled nor marked stale");
  assert.match(fn, /if \(sid === activeId\) activeChanged = true;/);
  assert.match(fn, /if \(activeChanged\) appendActive\(\);/, "the active chat rebuilds only for its own change");
  assert.doesNotMatch(fn, /if \(activeId && pendingSent\.has\(activeId\)\) appendActive\(\);/);
});

// ── (9) the bare label is per bubble ─────────────────────────────────────────────────────────────

test("the bare group's label counts lost and sending bubbles separately", () => {
  const texts = (n: number, m: number) => bareGroupLabel(n, m).parts.map((p) => (p.lost ? "!" : "") + p.text);
  assert.deepEqual(texts(0, 1), ["sending…"]);
  assert.deepEqual(texts(0, 3), ["sending 3…"]);
  assert.deepEqual(texts(1, 0), ["!not confirmed"]);
  assert.deepEqual(texts(2, 0), ["!2 not confirmed"]);
  assert.deepEqual(texts(1, 1), ["!not confirmed", "sending…"], "a mixed group names both states, the lost one first");
  assert.deepEqual(texts(1, 2), ["!not confirmed", "sending 2…"]);
  assert.match(bareGroupLabel(1, 0).title, /^The connection dropped after this was sent/);
  assert.match(bareGroupLabel(0, 1).title, /^on its way to the session/);
  assert.match(bareGroupLabel(1, 1).title, /^The connection dropped after this was sent[\s\S]*The rest: on its way/);
  // render.ts builds the label from the bubbles' own states, and the ✕'s recount reads them back off the
  // surviving bubbles (data-lost) — never off the label's previous class
  assert.match(RENDER, /const nLost = ev\.texts\.filter\(\(t\) => t\.lost\)\.length;\s*\n\s*fillBareLabel\(label, nLost, ev\.texts\.length - nLost\);/);
  assert.match(RENDER, /if \(t\.optimistic && t\.lost\) bubble\.dataset\.lost = "1";/);
  assert.match(RENDER, /const nLost = bubbles\.filter\(\(b\) => \(b as HTMLElement\)\.dataset\.lost === "1"\)\.length;\s*\n\s*fillBareLabel\(label, nLost, bubbles\.length - nLost\);/);
  assert.doesNotMatch(RENDER, /label\.classList\.contains\("lost"\)/);
  assert.match(RENDER, /const span = el\("span", part\.lost \? "lost" : ""\);/, "only the lost part wears the warn color");
});

// ── (10) the kernel's own copy clears "not confirmed" ────────────────────────────────────────────

test("the kernel's echo or queued copy seen after the press proves receipt: 'not confirmed' clears and never returns", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  const list = press(tail, TEXT);
  list[0].lost = "connection";                                   // the drop, as markPendingLost writes it
  let r = reconcilePending([...tail, { kind: "user", md: TEXT, uuid: "echo:1" }], list);
  assert.equal(list[0].lost, undefined, "the kernel minted this echo on receipt of the send: the drop did not lose it");
  assert.equal(list[0].received, true);
  r = reconcilePending(tail, list);                              // the echo blinks in its echo→landed handoff
  assert.equal(r.inject.length, 1);
  assert.equal(r.inject[0].lost, undefined, "…and our bubble steps back in as 'sending…', not as a false loss");
  // a queued copy that was not listed at the press is the same proof
  const list2 = press([{ kind: "queued", texts: [{ md: TEXT }] }], TEXT);
  list2[0].lost = "connection";
  reconcilePending([{ kind: "queued", texts: [{ md: TEXT }] }], list2);
  assert.equal(list2[0].lost, "connection", "one copy at the press, one copy now: nothing new");
  reconcilePending([{ kind: "queued", texts: [{ md: TEXT }, { md: TEXT }] }], list2);
  assert.equal(list2[0].lost, undefined, "a second copy is this send's");
  // a later drop leaves a received send alone (render.ts markPendingLost's guard)
  assert.match(RENDER, /if \(!p\.lost && !p\.received\) \{ p\.lost = why; changed = true; \}/);
});

// ── (11) receipt is attributed per send, like landings ───────────────────────────────────────────

test("two identical sends, one kernel echo: the first is received and covered; the second still shows, still unconfirmed", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  const list = press(tail, "continue", "continue");
  let r = reconcilePending([...tail, { kind: "user", md: "continue", uuid: "echo:1" }], list);
  assert.deepEqual(list.map((p) => p.received), [true, undefined], "one echo is one send's receipt");
  assert.deepEqual(r.inject, [list[1]], "the kernel's copy covers one bubble; ours shows for the other");
  assert.deepEqual(list[1].at?.seen, ["echo:1"], "the claimed echo is background for the later send");
  // the drop (as render.ts markPendingLost writes it): only the unconfirmed send is marked
  for (const p of list) if (!p.lost && !p.received) p.lost = "connection";
  assert.deepEqual(list.map((p) => p.lost), [undefined, "connection"]);
  // the same echo on later pushes proves nothing new — even once the first entry is gone (its ✕)
  r = reconcilePending([...tail, { kind: "user", md: "continue", uuid: "echo:1" }], [list[1]]);
  assert.equal(list[1].received, undefined);
  assert.equal(list[1].lost, "connection", "the bubble the kernel never received keeps saying so");
  assert.equal(r.inject.length, 1);
  // a second echo is the second send's
  reconcilePending([...tail, { kind: "user", md: "continue", uuid: "echo:1" }, { kind: "user", md: "continue", uuid: "echo:2" }], list);
  assert.deepEqual(list.map((p) => p.received), [true, true]);
  assert.equal(list[1].lost, undefined);
  // the claimed echo's verdict is the claimant's too: its never-delivered flag ends the first send only
  const list2 = press(tail, "continue", "continue");
  reconcilePending([...tail, { kind: "user", md: "continue", uuid: "echo:1" }], list2);
  r = reconcilePending([...tail, { kind: "user", md: "continue", uuid: "echo:1", undelivered: true }], list2);
  assert.deepEqual(r.lost, [list2[0]]);
  assert.deepEqual(r.keep, [list2[1]]);
});

test("both 'not confirmed', one echo arrives: one label clears, the other stays — and the landing retires the received one", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  const list = press(tail, "continue", "continue");
  list[0].lost = list[1].lost = "connection";
  reconcilePending([...tail, { kind: "user", md: "continue", uuid: "echo:1" }], list);
  assert.deepEqual(list.map((p) => p.lost), [undefined, "connection"]);
  const r = reconcilePending([...tail, { kind: "user", md: "continue", uuid: "u1" }], list);   // the echo→landed handoff
  assert.deepEqual(r.landed.map((l) => l.p), [list[0]]);
  assert.deepEqual(r.keep, [list[1]]);
  assert.equal(list[1].lost, "connection", "still unconfirmed: the kernel has shown one copy, and it landed");
});

test("queued copies are handed out by position: one new copy confirms one send; the copies a press listed are its background", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  const list = press(tail, "continue", "continue");
  let r = reconcilePending([...tail, { kind: "queued", texts: [{ md: "continue" }] }], list);
  assert.deepEqual(list.map((p) => p.received), [true, undefined]);
  assert.deepEqual(r.inject, [list[1]], "one kernel copy, one of ours: two bubbles for two sends");
  r = reconcilePending([...tail, { kind: "queued", texts: [{ md: "continue" }, { md: "continue" }] }], list);
  assert.deepEqual(list.map((p) => p.received), [true, true]);
  assert.equal(r.inject.length, 0);
  // a second press that already saw the first send's copy counts it as background, not as its own
  const a = press(tail, "continue");
  reconcilePending([...tail, { kind: "queued", texts: [{ md: "continue" }] }], a);
  const b = newPending("continue", undefined, T0 + 1);
  const both = [a[0], b];
  reconcilePending([...tail, { kind: "queued", texts: [{ md: "continue" }] }], both);   // b's press: one copy listed already
  assert.equal(b.at?.queued, 1);
  assert.equal(b.received, undefined, "the copy b's press listed is a's");
  reconcilePending([...tail, { kind: "queued", texts: [{ md: "continue" }, { md: "continue" }] }], both);
  assert.deepEqual(both.map((p) => p.received), [true, true]);
});

// ── (12) the ✕ removes the bubble's OWN entry ────────────────────────────────────────────────────

test("✕ on one of two identical bubbles removes that bubble's entry, never the first with the text", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  const A = newPending("continue", undefined, T0), B = newPending("continue", undefined, T0 + 5000);
  const list = [A, B];
  reconcilePending(tail, list);
  A.lost = "connection";                                   // A dropped; B was sent after the reconnect
  let r = reconcilePending(tail, list);
  assert.deepEqual(r.inject.map((p) => p.lost), ["connection", undefined], "the group reads 'not confirmed · sending…'");
  // the ✕ on B's bubble names B (data-qts) — the first-with-the-text lookup took A
  assert.equal(dropPending(list, "continue", B.ts), B);
  assert.deepEqual(list, [A]);
  r = reconcilePending(tail, list);
  assert.deepEqual(r.inject.map((p) => p.lost), ["connection"], "the dismissed bubble stays gone; the lost one stays put");
  // the ✕ on the LOST bubble of the pair
  const C = newPending("continue", undefined, T0), D = newPending("continue", undefined, T0 + 5000);
  const list2 = [C, D];
  reconcilePending(tail, list2);
  C.lost = "connection";
  assert.equal(dropPending(list2, "continue", C.ts), C);
  assert.deepEqual(list2, [D]);
  // a bubble whose entry a push already retired removes nothing — never a neighbour with the same text
  assert.equal(dropPending(list2, "continue", T0 + 999), undefined);
  assert.deepEqual(list2, [D]);
  // a ✕ on the KERNEL's own queued copy names no entry of ours: the first pending send with the text goes
  assert.equal(dropPending(list2, "continue"), D);
  assert.deepEqual(list2, []);
  // render.ts: the identity rides the bubble's ✕, and the handler removes by it
  assert.match(RENDER, /const mk = \(p: PendingSend\) => \(\{ md: p\.text, optimistic: true, cancelable: true, imgPaths: p\.imgPaths, lost: p\.lost, qts: p\.ts \}\);/);
  assert.match(RENDER, /if \(t\.qts !== undefined\) x\.dataset\.qts = String\(t\.qts\);/);
  assert.match(RENDER, /const qts = el\.dataset\.qts !== undefined \? Number\(el\.dataset\.qts\) : undefined;\s*\n\s*if \(dropPending\(list, qmd, qts\)\) \{ if \(list\.length\) pendingSent\.set\(sidQ, list\); else pendingSent\.delete\(sidQ\); \}/);
  assert.doesNotMatch(RENDER, /list\.findIndex\(\(p\) => p\.text === qmd\)/);
});

// ── (13) a late stamp reads the events' own times ────────────────────────────────────────────────

test("a send pressed against no frame (a placeholder tab): the first frame's copy of it is this send's, not background", () => {
  const isoAt = (s: number) => new Date(s * 1000).toISOString();   // kernel.py iso(t): ISO-8601 UTC, whole seconds
  const pressMs = T0 + 250;                                          // the press, on the client's clock
  const S = Math.floor(pressMs / 1000);
  const late = (): PendingSend => ({ ...newPending(TEXT, undefined, pressMs), late: true });   // registerOptimistic, no resident session
  // the first frame holds an older identical message, the last step before the send, this send's own
  // echo, and a step after it
  const frame: TailEvent[] = [
    { kind: "user", md: TEXT, uuid: "u-old", ts: isoAt(S - 3600) },
    { kind: "assistant", md: "…", uuid: "a1", ts: isoAt(S - 2) },
    { kind: "user", md: TEXT, uuid: "echo:1", ts: isoAt(S) },     // the kernel stamps the echo at its receipt: the press's second, or later
    { kind: "assistant", md: "…", uuid: "a2", ts: isoAt(S + 1) },
  ];
  let list = [late()];
  let r = reconcilePending(frame, list);
  assert.equal(list[0].at?.after, "a1", "the anchor is the last stable event stamped BEFORE the press — not a2");
  assert.deepEqual(list[0].at?.seen, ["u-old"], "the old message is background; this send's echo is not");
  assert.equal(list[0].received, true);
  assert.equal(r.inject.length, 0, "the kernel's echo covers our bubble: no double bubble");
  const landed: TailEvent[] = [frame[0], frame[1], { kind: "user", md: TEXT, uuid: "u1", ts: isoAt(S) }, frame[3]];
  r = reconcilePending(landed, list);
  assert.equal(r.keep.length, 0, "the echo→landed handoff retires it");
  // the CLI was idle: the first frame already holds the LANDED atom
  list = [late()];
  r = reconcilePending(landed, list);
  assert.equal(list[0].at?.after, "a1", "…and the landed atom is not the anchor either");
  assert.deepEqual(r.landed.map((l) => l.idx), [2], "it is the landing: the bubble ends, instead of never ending");
  // a first frame that predates the send entirely stamps exactly as a press-time stamp would
  list = [late()];
  reconcilePending([frame[0], frame[1]], list);
  assert.deepEqual(list[0].at, { after: "a1", seen: ["u-old"], queued: 0 });
  // a press-time stamp reads no stamp: its frame predates the press by construction, so an identical
  // message that landed within the press's own second is still background
  const prompt = press([frame[1], { kind: "user", md: TEXT, uuid: "u-same-second", ts: isoAt(Math.floor(T0 / 1000)) }], TEXT);
  assert.deepEqual(prompt[0].at?.seen, ["u-same-second"]);
  assert.equal(prompt[0].at?.after, "u-same-second");
  // render.ts marks the entry when the press finds no resident session, and stamps it nowhere else
  assert.match(RENDER, /const p = newPending\(text, imgPaths\);\s*\n\s*arr\.push\(p\);/);
  assert.match(RENDER, /if \(!s\) \{ p\.late = true; return; \}/);
  // the clock the bound compares against: the kernel stamps the echo atom at its receipt of the send, in
  // whole seconds (sdk_backend.py send). That the chat builder ships every event's stamp as iso(t) is
  // proven behaviourally, not pinned here: tests/test_kernel_fed_echo_absorbed.py (ChatEventSaysAbsorbed)
  // reads a built user event's ts back as iso(t) of its atom.
  const SDK = fs.readFileSync(path.resolve(process.cwd(), "..", "kernel", "sdk_backend.py"), "utf8");
  assert.match(SDK, /sent_t = int\(time\.time\(\)\)/);
  assert.match(SDK, /"t": sent_t\b/);
});

test("a late stamp presumes the first frame's newest queued copy of the text is this send's own (busy and held queues)", () => {
  const isoAt = (s: number) => new Date(s * 1000).toISOString();
  const pressMs = T0 + 250;
  const S = Math.floor(pressMs / 1000);
  const late = (): PendingSend => ({ ...newPending(TEXT, undefined, pressMs), late: true });
  const step: TailEvent = { kind: "assistant", md: "…", uuid: "a1", ts: isoAt(S - 2) };
  // the queued bubble carries no stamp: a busy session's queue (the CLI holds the text) and a held one
  // (an account limit; the kernel holds it, for hours) look the same to the stamp
  for (const q of [{ kind: "queued", texts: [{ md: TEXT }] }, { kind: "queued", texts: [{ md: TEXT }], held: { reason: "limit" } }] as TailEvent[]) {
    const list = [late()];
    let r = reconcilePending([step, q], list);
    assert.equal(list[0].at?.queued, 0, "the frame's one copy is presumed this press's, not background");
    assert.equal(r.inject.length, 0, "the kernel's copy covers our bubble for the whole wait: no double bubble beside it");
    assert.equal(list[0].received, true);
    // every later push, the same copy keeps covering it — the entry never sat uncovered until the CLI took it
    r = reconcilePending([step, q], list);
    assert.equal(r.inject.length, 0);
    // …and when the CLI takes the text, the landing ends the bubble (a tmux route: no echo in between)
    r = reconcilePending([step, { kind: "user", md: TEXT, uuid: "u1", ts: isoAt(S + 40) }], list);
    assert.deepEqual(r.landed.map((l) => l.idx), [1]);
  }
  // an older identical copy queued BEFORE the press sits at the head: the newest copy is ours, the older
  // one is background, so a second frame with a third copy would prove nothing about this send
  const list = [late()];
  reconcilePending([step, { kind: "queued", texts: [{ md: TEXT }, { md: TEXT }] }], list);
  assert.equal(list[0].at?.queued, 1);
  // the frame was built before the kernel received the send: no copy yet, none presumed; the copy that
  // follows covers it, exactly as at a press-time stamp
  const early = [late()];
  let r = reconcilePending([step], early);
  assert.deepEqual(early[0].at, { after: "a1", seen: [], queued: 0 });
  assert.equal(r.inject.length, 1);
  r = reconcilePending([step, { kind: "queued", texts: [{ md: TEXT }] }], early);
  assert.equal(r.inject.length, 0);
  assert.equal(early[0].received, true);
  // two identical sends pressed against the same placeholder frame own one copy EACH — and when the frame
  // lists only one of them (the kernel had not received the second), the second waits for its own
  const pair = [late(), late()];
  r = reconcilePending([step, { kind: "queued", texts: [{ md: TEXT }, { md: TEXT }] }], pair);
  assert.deepEqual(pair.map((p) => p.at?.queued), [0, 0]);
  assert.equal(r.inject.length, 0, "both copies are the pair's: neither bubble doubles");
  const pair2 = [late(), late()];
  r = reconcilePending([step, { kind: "queued", texts: [{ md: TEXT }] }], pair2);
  assert.deepEqual(pair2.map((p) => p.at?.queued), [0, 0], "fewer copies than presses: the count floors at zero");
  assert.equal(r.inject.length, 1, "one copy covers one send; the other waits for its own");
  r = reconcilePending([step, { kind: "queued", texts: [{ md: TEXT }, { md: TEXT }] }], pair2);
  assert.equal(r.inject.length, 0);
  // a press-time stamp presumes nothing: its frame predates the press, so every listed copy is background
  const prompt = press([step, { kind: "queued", texts: [{ md: TEXT }] }], TEXT);
  assert.equal(prompt[0].at?.queued, 1);
  // the ✕ on the kernel's copy (which names no entry) drops the one it covers — ours — so cancelling the
  // queued send leaves no orphan bubble behind
  const covered = [late()];
  reconcilePending([step, { kind: "queued", texts: [{ md: TEXT }] }], covered);
  const mine = covered[0];
  assert.equal(dropPending(covered, TEXT), mine);
  assert.equal(covered.length, 0);
});

// ── (2) the absorbed header and the mid-turn cue ─────────────────────────────────────────────────

test("the landed absorbed atom wears the 'joined mid-turn' header, with the taken-at time one level deeper", () => {
  assert.match(RENDER, /if \(\(ev as any\)\.absorbed && !romp && !injected && !tagged\) turn\.appendChild\(absorbedHeader\(\(ev as any\)\.landedAt\)\);/);
  assert.match(RENDER, /function absorbedHeader\(landedAt\?: number \| null\): HTMLElement \{\s*\n\s*const h = el\("div", "absorbed-tag"\);\s*\n\s*h\.textContent = "joined mid-turn";/);
  assert.match(RENDER, /h\.title = "Sent while the session was working[^"]*"\s*\n\s*\+ \(typeof landedAt === "number" \? ", and the session took it at " \+ hhmm\(landedAt\) : ""\)/,
    "the time rides the tooltip, not the one-line head");
  // one header family: the follow-up header's size and alignment, dim rather than accent
  assert.match(CSS, /\.absorbed-tag \{ max-width: 72%; margin-bottom: 1px; font-size: 0\.82em; color: var\(--dim\); \}/);
});

test("a landing above the tail leaves the cue where the bubble sat; jump scrolls to the atom; both actions retire it", () => {
  // recorded at the landing that retired the bubble (never re-derived per build), keyed to the anchor event
  assert.match(RENDER, /for \(const \{ idx \} of r\.landed\) noteAbsorbedLanding\(s, idx\);/);
  assert.match(RENDER, /function noteAbsorbedLanding\(s: Session, idx: number\): void \{[\s\S]{0,400}?if \(!ev \|\| !ev\.absorbed \|\| !ev\.uuid\) return;\s*\n\s*const after = cueAnchor\(s\.events as TailEvent\[\], idx, cueRendered\);\s*\n\s*if \(!after\) return;/);
  assert.match(RENDER, /cues\.push\(\{ after, target: ev\.uuid, landedAt: typeof ev\.landedAt === "number" \? ev\.landedAt : null \}\);/);
  // rendered with the anchor item on every window build (single events, tool groups, retry groups), so it keeps its place
  assert.equal((RENDER.match(/appendAbsorbedCues\(v, s, /g) || []).length, 3, "hung under every item shape appendItem renders");
  assert.match(RENDER, /line\.appendChild\(document\.createTextNode\("delivered into the running turn"\s*\n\s*\+ \(c\.landedAt != null \? " at " \+ hhmm\(c\.landedAt\) : ""\)\)\);/);
  // click-safe: data-act on the body delegate; jump = scrollToAnchor on the atom's uuid, and the cue is done
  assert.match(RENDER, /jump\.dataset\.act = "abjump"; jump\.dataset\.target = c\.target;/);
  assert.match(RENDER, /x\.dataset\.act = "abdismiss"; x\.dataset\.target = c\.target;/);
  assert.match(RENDER, /abjump: \(elx\) => \{[\s\S]{0,400}?dismissAbsorbedCue\(sidC, target\);[\s\S]{0,200}?if \(target\) scrollToAnchor\(target\);/);
  assert.match(RENDER, /abdismiss: \(elx\) => \{[\s\S]{0,300}?dismissAbsorbedCue\(sidC, elx\.dataset\.target \|\| ""\);/);
  // the interrupt marker's chrome, shared by selector rather than copied
  assert.match(CSS, /\.turn-absorbed-cue \.dot, \.turn-interrupt \.dot \{ background: var\(--dim\); border: none; \}/);
  assert.match(CSS, /\.absorbed-cue-line, \.interrupt-line \{[^}]*font-style: italic/);
  assert.match(CSS, /\.absorbed-cue-act,\n\.undelivered-act \{/);
  // the cue leaves with its tab, like the pending sends
  assert.equal((RENDER.match(/absorbedCues\.delete\(id\);/g) || []).length, 2);
});

// ── (3) the breadcrumb ───────────────────────────────────────────────────────────────────────────

test("every composer send posts a clientDiag breadcrumb — sid, time, length, route; never the text", () => {
  const m = RENDER.match(/vscodeApi\.postMessage\(\{ type: "clientDiag", surface: "chat", what: "send",\s*\n\s*data: \{ ([^}]*) \} \}\);/);
  assert.ok(m, "the breadcrumb is posted from routeUserMessage");
  const fields = m![1];
  assert.match(fields, /\bsid\b/); assert.match(fields, /ts: Date\.now\(\)/); assert.match(fields, /len: text\.length/); assert.match(fields, /route:/);
  assert.doesNotMatch(fields, /\btext\b(?!\.length)/, "the text itself never leaves the client");
  assert.doesNotMatch(fields, /\bbody\b|\bmd\b/);
  // one owner: the breadcrumb sits in routeUserMessage, which every send path (plain, quote, follow-up, staged flush) goes through
  const fn = RENDER.slice(RENDER.indexOf("function routeUserMessage("), RENDER.indexOf("\n}\n", RENDER.indexOf("function routeUserMessage(")));
  assert.ok(fn.includes('what: "send"'));
});

// ── (15) one record, several sends ───────────────────────────────────────────────────────────────

test("two back-to-back sends the CLI took as ONE record retire both bubbles; a third with other text stays", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  const list = press(tail, "continue", "continue", "and the docstring");
  // the kernel's user event for the batched record: md is the blocks joined; `blocks` lists each send
  const rec: TailEvent = { kind: "user", md: "continue continue", uuid: "u1", blocks: ["continue", "continue"] };
  const r = reconcilePending([...tail, rec], list);
  assert.deepEqual(r.landed.map((l) => [l.p, l.idx]), [[list[0], 1], [list[1], 1]], "one copy per block, in send order");
  assert.deepEqual(r.keep, [list[2]], "the third send's text is in no block");
  assert.equal(landedIn(rec, list[2]), false);
  assert.equal(landedIn(rec, list[0]), true);
  // two sends of DIFFERENT texts batched the same way: each block is its own send's landing
  const list2 = press(tail, "continue", "and the docstring");
  const rec2: TailEvent = { kind: "user", md: "continue and the docstring", uuid: "u2", blocks: ["continue", "and the docstring"] };
  const r2 = reconcilePending([...tail, rec2], list2);
  assert.deepEqual(r2.landed.map((l) => [l.p.text, l.idx]), [["continue", 1], ["and the docstring", 1]]);
  // a record of two copies that was already there at the press is background twice over
  const list3 = press([...tail, rec], "continue");
  assert.deepEqual(list3[0].at?.seen, ["u1", "u1"], "seen counts copies, not events");
  assert.equal(reconcilePending([...tail, rec], list3).keep.length, 1, "neither copy is this send's");
  // across pushes: the first of three identical sends retired on its own record earlier; the two-block
  // record then retires exactly the two that remain — the claims on one record are counted
  const list4 = press(tail, "continue", "continue", "continue");
  let r4 = reconcilePending([...tail, { kind: "user", md: "continue", uuid: "u0" }], list4);
  assert.deepEqual(r4.landed.map((l) => l.p), [list4[0]]);
  r4 = reconcilePending([...tail, { kind: "user", md: "continue", uuid: "u0" }, rec], r4.keep);
  assert.deepEqual(r4.landed.map((l) => l.p), [list4[1], list4[2]]);
  assert.equal(r4.keep.length, 0);
  // a fourth identical send pressed later finds every copy already there: the record of two is two
  const list5 = press([...tail, { kind: "user", md: "continue", uuid: "u0" }, rec], "continue");
  assert.deepEqual(list5[0].at?.seen, ["u0", "u1", "u1"], "the press lists the two-block record twice");
  assert.equal(reconcilePending([...tail, { kind: "user", md: "continue", uuid: "u0" }, rec], list5).keep.length, 1);
  // the same counting for the kernel's copies: a record of several sends is never an echo (one text each)
  assert.equal(provisionalIn({ kind: "user", md: "continue continue", uuid: "echo:1", blocks: ["continue", "continue"] }, list[0]), true,
    "…but were one ever shipped with blocks, its copies would be read the same way");
});
