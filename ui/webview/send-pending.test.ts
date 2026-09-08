// Send durability on the client (the 2026-09-05/06 audits). Two things went wrong at once: a send fed
// into a running turn is taken by the CLI at a later tool boundary and placed at its SEND time, so the
// pending bubble at the bottom vanished and the message reappeared higher up with no cue; and the
// client's bubble had a 20 s lifetime, so when the kernel's own echo was pruned early the send simply
// looked delivered. Now: (1) a pending send has NO lifetime — it ends on a landing, the kernel's
// never-delivered verdict, or the user's ✕; (2) the pending bubble is drawn AT ITS SEND POSITION from the
// start — right after its anchor, the last stable kernel event at the press — so the steps that stream
// in afterwards land below it and the absorbed atom, which the kernel places at the send time, replaces
// it in the same spot (T252, the user 2026-09-07: a header plus a button that jumps somewhere and later
// disappears is weird; the first cut's "joined mid-turn" header and the jump/✕ cue are gone);
// (3) every composer send posts a clientDiag breadcrumb (never the text).
// The 2026-09-06 adversarial review then fixed the decision's frame: (4) every verdict is read from the
// events AFTER the send's anchor, never from a 30-event tail count; (5) [retired with the cue];
// (6) the lost verdict shares the anchor; (7) exact text, one landing per send; (8) a connection
// drop repaints once; (9) the bare label is per bubble; (10) the kernel's own copy clears "not confirmed".
// Round 3 of that review: (11) receipt is attributed per send, like landings; (12) the ✕ removes the
// bubble's own entry; (13) a stamp taken late reads the events' own times. Round 4: (14) a late stamp
// presumes the frame's newest queued copy of its text is its own (the queued bubble carries no stamp).
// The decisions are executed through send-pending.ts; the DOM half is pinned in render.ts/styles.css.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { newPending, pendingBody, reconcilePending, dropPending, injectionGroups, scanFrom, queuedCopyToHide, foreignKey, landedIn, provisionalIn, bareGroupLabel, type TailEvent, type PendingSend } from "./send-pending";

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
  assert.deepEqual(r.landed.map((l) => l.idx), [1], "…naming the landed event: the slot the bubble held");
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

// ── (5) the bubble sits at its send position: right after its anchor, from the first paint ────────

test("the pending bubble is placed right after its anchor and stays there while steps stream in below (T252)", () => {
  const tail: TailEvent[] = [{ kind: "user", md: "first", uuid: "u1" }, { kind: "assistant", md: "…", uuid: "a1" }];
  const list = press(tail, TEXT);
  assert.equal(list[0].at?.after, "a1", "anchored to the last stable kernel event at the press");
  let r = reconcilePending(tail, list);
  assert.deepEqual(injectionGroups(tail, r.inject), [{ idx: 2, sends: [list[0]] }], "at the press the slot IS the tail");
  // two tool steps stream in while the CLI holds the send: they land below the bubble, the bubble does not move
  const streaming: TailEvent[] = [...tail, { kind: "tool", uuid: "t1" }, { kind: "tool", uuid: "t2" }];
  r = reconcilePending(streaming, list);
  assert.equal(r.inject.length, 1, "still pending, still drawn");
  assert.deepEqual(injectionGroups(streaming, r.inject), [{ idx: 2, sends: [list[0]] }], "same slot: after a1, above t1 and t2");
  // the CLI takes it at the boundary: the kernel places the absorbed atom at its SEND time — the bubble's slot
  const landed: TailEvent[] = [...tail, { kind: "user", md: TEXT, uuid: "att1", absorbed: true }, { kind: "tool", uuid: "t1" }, { kind: "tool", uuid: "t2" }];
  r = reconcilePending(landed, list);
  assert.deepEqual(r.landed.map((l) => l.idx), [2], "the landing replaces the bubble in place: same index");
  assert.equal(r.keep.length, 0);
});

test("several pending sends: each after its own anchor, in send order; same anchor → one group in order", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  const list = press(tail, "one", "two");                 // pressed against the same frame
  const later: TailEvent[] = [...tail, { kind: "tool", uuid: "t1" }];
  const third = newPending("three", undefined, T0 + 9);
  const all = [...list, third];
  const r = reconcilePending(later, all);                  // the third is stamped now, after t1
  assert.equal(third.at?.after, "t1");
  assert.deepEqual(injectionGroups(later, r.inject), [
    { idx: 2, sends: [third] },                            // highest slot first, so the caller can splice bottom-up
    { idx: 1, sends: [list[0], list[1]] },                 // one bare group for the two that share an anchor, in send order
  ]);
  // no events at all: the only slot is the head, which is also the tail
  const none = press([], "hello");
  assert.deepEqual(injectionGroups([], reconcilePending([], none).inject), [{ idx: 0, sends: [none[0]] }]);
  // an anchor that left the resident window: everything resident is later than the send, so the slot is the head
  assert.equal(scanFrom([{ kind: "tool", uuid: "zz" }], { after: "gone", place: null, queuedForeign: [], queuedForeignIds: [], queuedResident: {}, seen: [], queued: 0 }), 0);
});

test("a send pressed while an earlier send's echo is the newest event is placed BELOW that echo (review of the first cut)", () => {
  // the anchor skips the kernel's echo atoms (an echo is not a stable place to bound the landing scan), but as a
  // PLACEMENT that inverted consecutive sends: the second message sat above the first until both landed. A user
  // event the kernel stamped at or before the press — an echo, a never-delivered bubble, a landed atom — is
  // older than this send, so the bubble goes below it, exactly where the absorbed atom will be placed by time.
  const isoAt = (s: number) => new Date(s * 1000).toISOString();
  const S = Math.floor(T0 / 1000);
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1", ts: isoAt(S - 30) }];
  const first = press(tail, "first message");
  const echoed: TailEvent[] = [...tail, { kind: "user", md: "first message", uuid: "echo:1", ts: isoAt(S - 2) }];
  reconcilePending(echoed, first);                              // the kernel's echo covers the first send
  const second = newPending("second message", undefined, T0);   // pressed with the echo as the newest event
  const list = [...first, second];
  const r = reconcilePending(echoed, list);
  assert.equal(second.at?.after, "a1", "the scan anchor still skips the echo");
  assert.deepEqual(r.inject, [second]);
  assert.deepEqual(injectionGroups(echoed, r.inject), [{ idx: 2, sends: [second] }], "…but the bubble is placed below it");
  // a never-delivered bubble from an earlier send: older than this press, so below it too
  const lost: TailEvent[] = [...tail, { kind: "user", md: "older", uuid: "echo:9", undelivered: true, ts: isoAt(S - 5) }];
  const p = press(lost, "newer");
  assert.deepEqual(injectionGroups(lost, reconcilePending(lost, p).inject), [{ idx: 2, sends: [p[0]] }]);
  // a user event that arrives AFTER the press is a later send: the bubble stays above it
  const later: TailEvent[] = [...tail, { kind: "user", md: "someone else's later message", uuid: "u7", ts: isoAt(S + 30) }];
  const q = newPending("mine", undefined, T0);
  reconcilePending(tail, [q]);                                  // pressed against the tail before u7 arrived
  assert.deepEqual(injectionGroups(later, reconcilePending(later, [q]).inject), [{ idx: 1, sends: [q] }]);
});

test("the placement floor is the last user event AT THE PRESS, by identity, never a clock (second review)", () => {
  // a press-time frame already proves precedence: every event resident at the press is older than the send. Comparing
  // the client's press second with the kernel host's stamps re-inverted the order whenever the kernel clock led by more
  // than the gap between two presses (a phone, a remote browser), and misplaced a bubble below a later-received event
  // when the client clock led. So the press records the last user event's uuid (an echo counts) as the floor.
  const isoAt = (s: number) => new Date(s * 1000).toISOString();
  const S = Math.floor(T0 / 1000);
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1", ts: isoAt(S - 30) }];
  // kernel host 3 s AHEAD: the first send's echo is stamped after the second press's second
  const echoed: TailEvent[] = [...tail, { kind: "user", md: "first", uuid: "echo:1", ts: isoAt(S + 3) }];
  const second = newPending("second", undefined, T0);
  let r = reconcilePending(echoed, [second]);
  assert.equal(second.at?.place, "echo:1", "the floor is recorded at the press");
  assert.deepEqual(injectionGroups(echoed, r.inject), [{ idx: 2, sends: [second] }], "below the echo, whatever the clocks say");
  // the echo → landed swap: the floor's uuid is gone, the landed atom carries its text — still the floor
  const landedFirst: TailEvent[] = [...tail, { kind: "user", md: "first", uuid: "u1", absorbed: true, ts: isoAt(S + 3) }, { kind: "tool", uuid: "t1" }];
  r = reconcilePending(landedFirst, [second]);
  assert.deepEqual(injectionGroups(landedFirst, r.inject), [{ idx: 2, sends: [second] }], "below the landed first message, above the later tool");
  // client clock AHEAD: a peer's message the kernel receives after the press, stamped at or before the press second,
  // was not resident at the press — the bubble stays above it
  const peerLater: TailEvent[] = [...tail, { kind: "user", md: "a peer's message", uuid: "u9", ts: isoAt(S - 1) }];
  const mine = newPending("mine", undefined, T0);
  reconcilePending(tail, [mine]);
  assert.deepEqual(injectionGroups(peerLater, reconcilePending(peerLater, [mine]).inject), [{ idx: 1, sends: [mine] }]);
  // no user event at the press: no floor, the anchor rules
  const bare = press(tail, "alone");
  assert.equal(bare[0].at?.place, null);
  assert.deepEqual(injectionGroups(tail, reconcilePending(tail, bare).inject), [{ idx: 1, sends: [bare[0]] }]);
  // a LATE entry (pressed against no frame) reads the frame's own stamps for its floor, like its anchor
  const lateFrame: TailEvent[] = [...tail, { kind: "user", md: "older", uuid: "echo:5", ts: isoAt(S - 2) }, { kind: "user", md: "newer", uuid: "echo:6", ts: isoAt(S + 2) }];
  const late: PendingSend = { ...newPending("late one", undefined, T0), late: true };
  reconcilePending(lateFrame, [late]);
  assert.equal(late.at?.place, "echo:5", "the last user event the kernel stamped before the press");
  assert.doesNotMatch(read("send-pending.ts").split("export function placementIndex(")[1].split("\n}")[0], /eventSecond|pressS|p\.ts/, "placement reads no clock");
});

test("the text fallback finds the floor by ORDINAL, so a later send of the same text never pulls the bubble down (third review)", () => {
  // A = "ok" pressed and echoed; B = "next" pressed with echo:A the newest user event; A lands, two steps stream,
  // then the user sends "ok" again. The fallback used to take the LAST same-text user event — the new send's echo —
  // and B's bubble dropped to the tail under a message pressed after it, until B landed.
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  const echoedA: TailEvent[] = [...tail, { kind: "user", md: "ok", uuid: "echo:A" }];
  const b = newPending("next", undefined, T0);
  reconcilePending(echoedA, [b]);
  assert.equal(b.at?.place, "echo:A");
  assert.equal(b.at?.placeOrd, 1, "one same-text user event from the anchor through the floor");
  const later: TailEvent[] = [...tail, { kind: "user", md: "ok", uuid: "uA", absorbed: true }, { kind: "tool", uuid: "t1" }, { kind: "tool", uuid: "t2" }, { kind: "user", md: "ok", uuid: "echo:C" }];
  assert.deepEqual(injectionGroups(later, reconcilePending(later, [b]).inject), [{ idx: 2, sends: [b] }], "below uA, above t1 — not under the newer echo");
  const laterLanded: TailEvent[] = [...later.slice(0, 4), { kind: "user", md: "ok", uuid: "uC" }];
  assert.deepEqual(injectionGroups(laterLanded, reconcilePending(laterLanded, [b]).inject), [{ idx: 2, sends: [b] }], "…nor under its landed atom");
  // two identical echoes as the tail: the floor is the SECOND, so after both land the bubble sits below the second
  const twin: TailEvent[] = [...tail, { kind: "user", md: "ok", uuid: "echo:A1" }, { kind: "user", md: "ok", uuid: "echo:A2" }];
  const c = newPending("next", undefined, T0 + 1);
  reconcilePending(twin, [c]);
  assert.equal(c.at?.placeOrd, 2);
  const twinLanded: TailEvent[] = [...tail, { kind: "user", md: "ok", uuid: "uA1" }, { kind: "user", md: "ok", uuid: "uA2" }, { kind: "tool", uuid: "t1" }];
  assert.deepEqual(injectionGroups(twinLanded, reconcilePending(twinLanded, [c]).inject), [{ idx: 3, sends: [c] }]);
  // the floor sits ABOVE the anchor (steps followed the last message before the press): the anchor already covers
  // it, and a later same-text send must not become a floor
  const stepsAfter: TailEvent[] = [{ kind: "user", md: "ok", uuid: "u0" }, { kind: "tool", uuid: "t0" }, { kind: "assistant", md: "…", uuid: "a1" }];
  const d = press(stepsAfter, "next")[0];
  assert.equal(d.at?.placeOrd, 0, "no same-text event after the anchor: the floor is not in play");
  const stepsAfterLater: TailEvent[] = [...stepsAfter, { kind: "tool", uuid: "t3" }, { kind: "user", md: "ok", uuid: "echo:D" }];
  assert.deepEqual(injectionGroups(stepsAfterLater, reconcilePending(stepsAfterLater, [d]).inject), [{ idx: 3, sends: [d] }], "right after the anchor");
});

test("an earlier pending send's landing or echo is a floor for every later send, whatever its text (T252b)", () => {
  // X then Y pressed against [a1], both with no floor; the kernel ships X's absorbed atom: Y's bubble must sit
  // BELOW it. Landings were recorded into `seen` for same-text entries only and placement never read them, so Y
  // was spliced before uX and read above the first message until it landed — the very move this work ends.
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  const [x, y] = press(tail, "first", "second");
  assert.equal(y.at?.place, null);
  let frame: TailEvent[] = [...tail, { kind: "user", md: "first", uuid: "uX", absorbed: true }, { kind: "tool", uuid: "t1" }];
  let r = reconcilePending(frame, [x, y]);
  assert.deepEqual(r.landed.map((l) => l.p), [x]);
  assert.deepEqual(r.keep, [y]);
  assert.deepEqual(y.floors?.map((f) => f.uuid), ["uX"], "X's landing is recorded as Y's floor");
  assert.deepEqual(injectionGroups(frame, r.inject), [{ idx: 2, sends: [y] }], "below uX, above t1");
  // the echo variant: X's echo arrives while both are pending — Y sits below it, and X is covered
  const [x2, y2] = press(tail, "first", "second");
  frame = [...tail, { kind: "user", md: "first", uuid: "echo:X" }];
  r = reconcilePending(frame, [x2, y2]);
  assert.deepEqual(r.inject, [y2]);
  assert.deepEqual(y2.floors?.map((f) => f.uuid), ["echo:X"]);
  assert.deepEqual(injectionGroups(frame, r.inject), [{ idx: 2, sends: [y2] }]);
  // …and when that echo becomes the landed atom, the landing takes over as the floor
  frame = [...tail, { kind: "user", md: "first", uuid: "uX2", absorbed: true }, { kind: "tool", uuid: "t1" }];
  r = reconcilePending(frame, [x2, y2]);
  assert.deepEqual(y2.floors?.map((f) => f.uuid), ["echo:X", "uX2"]);
  assert.deepEqual(injectionGroups(frame, r.inject), [{ idx: 2, sends: [y2] }]);
  // a LATER send never becomes a floor for an earlier one: Z pressed after Y, lands first (a different route)
  const [y3, z3] = press(tail, "second", "third");
  frame = [...tail, { kind: "user", md: "third", uuid: "uZ" }];
  r = reconcilePending(frame, [y3, z3]);
  assert.deepEqual(r.landed.map((l) => l.p), [z3]);
  assert.equal(y3.floors, undefined, "z3 was registered after y3: its landing is not y3's floor");
  assert.deepEqual(injectionGroups(frame, r.inject), [{ idx: 1, sends: [y3] }], "y3 stays above the later send's atom");
});

test("a send pressed while the kernel's queue holds OTHER texts is drawn below that queue, and below their atoms once they land (T252b)", () => {
  // the kernel's queued group has no uuid and is no user event, so it was never the anchor nor the floor: a send
  // pressed while it held a romp nudge, another client's message, or a queue predating a page reload was spliced
  // ABOVE the queue although it runs after those texts, and dropped down when one of them landed
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  const queued: TailEvent[] = [...tail, { kind: "queued", texts: [{ md: "a nudge from elsewhere" }, { md: "mine" }] }];
  const mine = newPending("mine", undefined, T0);
  let r = reconcilePending(queued, [mine]);
  assert.deepEqual(mine.at?.queuedForeign, ["a nudge from elsewhere", "mine"], "every copy the queue held at the press is ahead of the send — a same-text copy included: it predates the press, so it is an older send's (second review)");
  assert.equal(mine.at?.queued, 1, "…and it is background for the landing scan as before");
  assert.deepEqual(injectionGroups(queued, r.inject), [{ idx: 2, sends: [mine] }], "below the queue, not above it");
  // our copy hidden (render.ts) leaves the foreign text visible: still below
  const hidden: TailEvent[] = [...tail, { kind: "queued", texts: [{ md: "a nudge from elsewhere" }, { md: "mine", hiddenByPending: true }] }];
  assert.deepEqual(injectionGroups(hidden, reconcilePending(hidden, [mine]).inject), [{ idx: 2, sends: [mine] }]);
  // the foreign text lands and the queue drains: the bubble sits below its atom, above what streams after
  const landed: TailEvent[] = [...tail, { kind: "user", md: "a nudge from elsewhere", uuid: "uN" }, { kind: "tool", uuid: "t1" }];
  r = reconcilePending(landed, [mine]);
  assert.deepEqual(injectionGroups(landed, r.inject), [{ idx: 2, sends: [mine] }]);
  // OUR copy is the one the kernel lists AFTER the press: not in the frame at the press, hidden by render.ts
  // when it appears — the in-place rule (right after the anchor) holds for it
  const mine2 = newPending("mine", undefined, T0 + 1);
  r = reconcilePending(tail, [mine2]);
  assert.deepEqual(mine2.at?.queuedForeign, []);
  const listed: TailEvent[] = [...tail, { kind: "queued", texts: [{ md: "mine" }] }];
  r = reconcilePending(listed, [mine2]);
  assert.deepEqual(r.unqueue, [mine2], "the copy that appears after the press is this send's: hidden, ours drawn");
  assert.deepEqual(injectionGroups(listed, r.inject), [{ idx: 1, sends: [mine2] }]);
  // a same-text copy PRESENT at the press is an older send's (another client, an earlier press): ahead, below the group
  const older: TailEvent[] = [...tail, { kind: "queued", texts: [{ md: "mine" }] }];
  const mine3 = newPending("mine", undefined, T0 + 2);
  r = reconcilePending(older, [mine3]);
  assert.deepEqual(mine3.at?.queuedForeign, ["mine"]);
  assert.deepEqual(injectionGroups(older, r.inject), [{ idx: 2, sends: [mine3] }]);
  // render.ts: the stale merge-into-the-group comment is gone; the tail group is described as a floor
  assert.doesNotMatch(RENDER, /Ours merges INTO it when present/);
  assert.match(RENDER, /a group holding OTHER texts is a floor/);
});

test("foreign and floor texts match the kernel's landed shapes: a nudge's quote and markers, a multi-block record, and by ordinal (T252b review)", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  // (1) a goal-marked romp nudge: the queued group ships the split BODY, the landed atom keeps the full text
  const body = "where does this stand?";
  const full = "> the goal's context line\n\n" + body + "\n\n<!-- romp-goal-id: g1 --><!-- romp-injected -->";
  const x = newPending("mine", undefined, T0);
  reconcilePending([...tail, { kind: "queued", texts: [{ md: body }, { md: "mine" }] }], [x]);
  assert.deepEqual(x.at?.queuedForeign, [body, "mine"], "every copy present at the press is ahead (the same-text one is an older send's)");
  const nudgeLanded: TailEvent[] = [...tail, { kind: "user", md: full, uuid: "uN" }, { kind: "assistant", md: "…", uuid: "a2" }, { kind: "queued", texts: [{ md: "mine", hiddenByPending: true }] }];
  assert.deepEqual(injectionGroups(nudgeLanded, reconcilePending(nudgeLanded, [x]).inject), [{ idx: 2, sends: [x] }], "below the landed nudge, whatever wrapping the kernel kept");
  // (2) a multi-block record: two foreign texts taken at one boundary land as ONE user record
  const y = newPending("mine", undefined, T0 + 1);
  reconcilePending([...tail, { kind: "queued", texts: [{ md: "F" }, { md: "G" }, { md: "mine" }] }], [y]);
  const blocks: TailEvent[] = [...tail, { kind: "user", md: "F G", uuid: "uFG", blocks: ["F", "G"] }, { kind: "tool", uuid: "t1" }];
  assert.deepEqual(injectionGroups(blocks, reconcilePending(blocks, [y]).inject), [{ idx: 2, sends: [y] }], "below the record that holds both");
  // (3) by ordinal: one copy of F queued at the press; F lands; another client queues F AGAIN, and later echoes it —
  // the press-time copy is the first landing, and the newer copies are later than this send
  const z = newPending("mine", undefined, T0 + 2);
  reconcilePending([...tail, { kind: "queued", texts: [{ md: "F" }, { md: "mine" }] }], [z]);
  const again: TailEvent[] = [...tail, { kind: "user", md: "F", uuid: "uF1" }, { kind: "tool", uuid: "t1" }, { kind: "queued", texts: [{ md: "mine", hiddenByPending: true }, { md: "F" }] }];
  // the kernel's queued copies carry no identity, so a copy still shown in the group is read as the press-time one
  // (fourth review): the group holds the bubble below it while it shows a copy of the key — the fed-copy case, where
  // an identical text the kernel had already forwarded lands first, is the common one; a same-text copy re-queued by
  // another client after the press-time one landed keeps ours below the group until ours lands — the known limit
  assert.deepEqual(injectionGroups(again, reconcilePending(again, [z]).inject), [{ idx: 4, sends: [z] }], "below the group while it still shows a copy of F");
  const echoed: TailEvent[] = [...tail, { kind: "user", md: "F", uuid: "uF1" }, { kind: "tool", uuid: "t1" }, { kind: "user", md: "F", uuid: "echo:F2" }];
  assert.deepEqual(injectionGroups(echoed, reconcilePending(echoed, [z]).inject), [{ idx: 4, sends: [z] }], "…and, uF1 having been learned as someone else's while the group showed F, below the newer F's echo until this send lands");
  // two copies of F at the press: the second landing is the floor
  const w = newPending("mine", undefined, T0 + 3);
  reconcilePending([...tail, { kind: "queued", texts: [{ md: "F" }, { md: "F" }, { md: "mine" }] }], [w]);
  const twoLanded: TailEvent[] = [...tail, { kind: "user", md: "F", uuid: "uF1" }, { kind: "user", md: "F", uuid: "uF2" }, { kind: "tool", uuid: "t1" }];
  assert.deepEqual(injectionGroups(twoLanded, reconcilePending(twoLanded, [w]).inject), [{ idx: 3, sends: [w] }]);
  const oneLanded: TailEvent[] = [...tail, { kind: "user", md: "F", uuid: "uF1" }, { kind: "queued", texts: [{ md: "F" }, { md: "mine", hiddenByPending: true }] }];
  assert.deepEqual(injectionGroups(oneLanded, reconcilePending(oneLanded, [w]).inject), [{ idx: 3, sends: [w] }], "one press-time copy still queued: below the group");
  // (4) an earlier send's ECHO floor survives the earlier send's ✕: when its atom lands under a new uuid the floor
  // is followed by text and ordinal, with no entry left to record the landing
  const [x4, y4] = press(tail, "first", "second");
  reconcilePending([...tail, { kind: "user", md: "first", uuid: "echo:X" }], [x4, y4]);
  assert.deepEqual(y4.floors?.map((f) => [f.uuid, f.text, f.ord]), [["echo:X", "first", 1]]);
  dropPending([x4, y4], "first", x4.ts);   // the ✕ the kernel could not honour: the CLI had taken it
  const afterX: TailEvent[] = [...tail, { kind: "user", md: "first", uuid: "uX", absorbed: true }, { kind: "tool", uuid: "t1" }];
  assert.deepEqual(injectionGroups(afterX, reconcilePending(afterX, [y4]).inject), [{ idx: 2, sends: [y4] }], "below X's atom, under its new uuid");
});

test("the queue's copies count as they were at the press: a later press matching a queued text, resident carriers, and the key's gates (T252b second review)", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  // (1) another client's "y" queued; A presses "x", then B presses "y": both run after that y, and A before B
  const foreignY: TailEvent[] = [...tail, { kind: "queued", texts: [{ md: "y" }] }];
  const a = newPending("x", undefined, T0); reconcilePending(foreignY, [a]);
  const b = newPending("y", undefined, T0 + 1); let r = reconcilePending(foreignY, [a, b]);
  assert.deepEqual(b.at?.queuedForeign, ["y"], "the copy predates B's press: ahead of B, whatever its text");
  assert.deepEqual(injectionGroups(foreignY, r.inject), [{ idx: 2, sends: [a, b] }], "both below the group, in send order");
  // (2) a carrier of the text already resident at the press (a never-delivered verdict for an earlier F) is not
  // the press-time copy's landing: the group holding F stays the floor
  const resident: TailEvent[] = [...tail, { kind: "user", md: "F", uuid: "echo:F0", undelivered: true }, { kind: "queued", texts: [{ md: "F" }] }];
  const c = newPending("mine", undefined, T0 + 2); r = reconcilePending(resident, [c]);
  assert.deepEqual(injectionGroups(resident, r.inject), [{ idx: 3, sends: [c] }], "below the group, not at the group's own index");
  const residentLanded: TailEvent[] = [...tail, { kind: "user", md: "F", uuid: "echo:F0", undelivered: true }, { kind: "user", md: "F", uuid: "uF" }, { kind: "tool", uuid: "t1" }];
  assert.deepEqual(injectionGroups(residentLanded, reconcilePending(residentLanded, [c]).inject), [{ idx: 3, sends: [c] }], "…and below the copy's landing once it lands");
  // (3) the key: a leading quote block is set aside only for a romp-marked text (the kernel's own gate); a
  // user's blockquote is part of the text; image chips and image paths are set aside like the kernel strips them
  assert.equal(foreignKey("> the goal\n\nbody\n\n<!-- romp-goal-id: g1 -->"), "body");
  assert.notEqual(foreignKey("> hi\nok"), foreignKey("ok"), "a typed blockquote is not wrapping");
  assert.equal(foreignKey("look /tmp/shot.png"), foreignKey("look"));
  assert.equal(foreignKey("look [Image #1]"), foreignKey("look"));
  // an image-bearing foreign message (tmux route): queued with the path, landed with the chips stripped
  const imgQueued: TailEvent[] = [...tail, { kind: "queued", texts: [{ md: "look /tmp/shot.png" }] }];
  const d = newPending("mine", undefined, T0 + 3); reconcilePending(imgQueued, [d]);
  const imgLanded: TailEvent[] = [...tail, { kind: "user", md: "look", uuid: "uI", images: [{}] }, { kind: "tool", uuid: "t1" }];
  assert.deepEqual(injectionGroups(imgLanded, reconcilePending(imgLanded, [d]).inject), [{ idx: 2, sends: [d] }]);
  // a copy whose text is a user's blockquote plus ours: still a copy present at the press, still ahead
  const quoted: TailEvent[] = [...tail, { kind: "queued", texts: [{ md: "> hi\nok" }] }];
  const e = newPending("ok", undefined, T0 + 4); r = reconcilePending(quoted, [e]);
  assert.deepEqual(injectionGroups(quoted, r.inject), [{ idx: 2, sends: [e] }]);
});

test("empty keys, retired verdicts, a verdict seen first, and the CLI's delimiters (T252b third review)", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }, { kind: "tool", uuid: "t1" }];
  // (1) an image-only queued copy keys to nothing: a reminders-only user record (md "") that lands after the press
  // is not its carrier — only an event that carries images can be
  const imgQueued: TailEvent[] = [...tail, { kind: "queued", texts: [{ md: "/tmp/shot.png" }] }];
  const b = newPending("typed after", undefined, T0); reconcilePending(imgQueued, [b]);
  const notified: TailEvent[] = [...tail, { kind: "user", md: "", uuid: "uR" }, { kind: "tool", uuid: "t2" }, { kind: "queued", texts: [{ md: "/tmp/shot.png" }] }];
  assert.deepEqual(injectionGroups(notified, reconcilePending(notified, [b]).inject), [{ idx: 5, sends: [b] }], "below the group, not after the notification");
  const imgLanded: TailEvent[] = [...tail, { kind: "user", md: "", uuid: "uR" }, { kind: "tool", uuid: "t2" }, { kind: "user", md: "", uuid: "uImg", images: [{}] }, { kind: "tool", uuid: "t3" }];
  assert.deepEqual(injectionGroups(imgLanded, reconcilePending(imgLanded, [b]).inject), [{ idx: 5, sends: [b] }], "below the image's atom once it lands");
  // (2) a resident verdict counted at the press may be retired by the kernel: the group test must not then read a
  // copy queued AFTER the press as a press-time one
  const withVerdict: TailEvent[] = [tail[0], { kind: "user", md: "F", uuid: "echo:F0", undelivered: true }, { kind: "queued", texts: [{ md: "F" }] }];
  const c = newPending("mine", undefined, T0 + 1); reconcilePending(withVerdict, [c]);
  const verdictGone: TailEvent[] = [tail[0], { kind: "user", md: "F", uuid: "uF" }, { kind: "tool", uuid: "t1" }, { kind: "queued", texts: [{ md: "F" }] }];
  // the group still shows a copy of F, so uF is read as someone else's landing and the bubble stays below the group
  // (the known limit: the kernel's queued copies carry no identity — fourth review)
  assert.deepEqual(injectionGroups(verdictGone, reconcilePending(verdictGone, [c]).inject), [{ idx: 4, sends: [c] }], "below the group while it shows a copy of F");
  // (3) an earlier send's never-delivered verdict, seen already flagged (a reconnect): a floor for the later send
  const [p3, b3] = press([tail[0]], "first", "second");
  const lostFirst: TailEvent[] = [tail[0], { kind: "user", md: "first", uuid: "echo:P", undelivered: true }];
  const r = reconcilePending(lostFirst, [p3, b3]);
  assert.deepEqual(r.lost, [p3]);
  assert.deepEqual(b3.floors?.map((f) => f.uuid), ["echo:P"]);
  assert.deepEqual(injectionGroups(lostFirst, r.inject), [{ idx: 2, sends: [b3] }], "below the verdict bubble, exactly as below the unflagged echo");
  // (4) the CLI replaces only the path and leaves the delimiters: both sides keep them
  for (const [q, l] of [["look (/tmp/a.png)", "look ()"], ["look `/tmp/a.png`", "look ``"], ["look '/tmp/a.png'", "look ''"], ["look \"/tmp/a.png\"", "look \"\""], ["look /tmp/a.png,", "look ,"]])
    assert.equal(foreignKey(q), foreignKey(l), q);
  assert.notEqual(foreignKey("design.png.bak notes"), foreignKey("notes"), "not a path: an ordinary token stays");
});

test("a copy still shown in the group holds the bubble below it, and copies are counted per block (T252b fourth review)", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  // (1) an identical text the kernel had already FED lands first (its echo was hidden behind the queued copy): that
  // landing is not the queued copy's — the group still shows the press-time F, so the bubble stays below the group,
  // and below the queued copy's own atom once it lands
  const fed: TailEvent[] = [...tail, { kind: "queued", texts: [{ md: "F" }] }];
  const a = newPending("mine", undefined, T0); reconcilePending(fed, [a]);
  const fedLanded: TailEvent[] = [...tail, { kind: "user", md: "F", uuid: "uF1", absorbed: true }, { kind: "queued", texts: [{ md: "F" }, { md: "mine", hiddenByPending: true }] }];
  assert.deepEqual(injectionGroups(fedLanded, reconcilePending(fedLanded, [a]).inject), [{ idx: 3, sends: [a] }], "still below the group");
  const bothLanded: TailEvent[] = [...tail, { kind: "user", md: "F", uuid: "uF1", absorbed: true }, { kind: "tool", uuid: "t1" }, { kind: "user", md: "F", uuid: "uF2" }, { kind: "tool", uuid: "t2" }];
  assert.deepEqual(injectionGroups(bothLanded, reconcilePending(bothLanded, [a]).inject), [{ idx: 4, sends: [a] }], "below the second F once the group has drained");
  // (2) two press-time copies of F land as ONE record with two blocks: that is two carriers, so a third F queued
  // after the press is later than the send
  const two: TailEvent[] = [...tail, { kind: "queued", texts: [{ md: "F" }, { md: "F" }] }];
  const b = newPending("mine", undefined, T0 + 1); reconcilePending(two, [b]);
  const oneRecord: TailEvent[] = [...tail, { kind: "user", md: "F F", uuid: "uFF", blocks: ["F", "F"] }, { kind: "tool", uuid: "t1" }];
  assert.deepEqual(injectionGroups(oneRecord, reconcilePending(oneRecord, [b]).inject), [{ idx: 2, sends: [b] }], "after the record that holds both copies");
  const thirdLanded: TailEvent[] = [...tail, { kind: "user", md: "F F", uuid: "uFF", blocks: ["F", "F"] }, { kind: "tool", uuid: "t1" }, { kind: "user", md: "F", uuid: "uF3" }, { kind: "tool", uuid: "t2" }];
  assert.deepEqual(injectionGroups(thirdLanded, reconcilePending(thirdLanded, [b]).inject), [{ idx: 2, sends: [b] }], "…and above a third F queued after the send");
  // a floor's ordinal counts blocks the same way: X's landing in a two-block record with an older same-text copy
  const [x, y] = press(tail, "first", "second");
  const xTwice: TailEvent[] = [...tail, { kind: "user", md: "first first", uuid: "uXX", blocks: ["first", "first"] }, { kind: "tool", uuid: "t1" }];
  const r = reconcilePending(xTwice, [x, y]);
  assert.deepEqual(y.floors?.map((f) => [f.uuid, f.ord]), [["uXX", 2]], "two copies in the record count as two");
  assert.deepEqual(injectionGroups(xTwice, r.inject), [{ idx: 2, sends: [y] }]);
});

// ── (T252c) identity from the kernel: qid on the queued copies and on the landed atom ─────────────

test("the two limits fall with identities: a same-text copy queued later, and both landings in one frame (T252c)", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  // (1) another client's F is queued (qid f1); we press; F lands (the atom carries qid f1); another client queues
  // F AGAIN (qid f2) — by text the group still "shows F"; by identity the press-time copy has landed
  const queued: TailEvent[] = [...tail, { kind: "queued", texts: [{ md: "F", qid: "f1", qts: 1 }] }];
  const mine = newPending("mine", undefined, T0);
  reconcilePending(queued, [mine]);
  assert.deepEqual(mine.at?.queuedForeignIds, ["f1"], "the copies' ids are recorded at the press");
  const again: TailEvent[] = [...tail, { kind: "user", md: "F", uuid: "uF1", qid: "f1" }, { kind: "tool", uuid: "t1" },
                              { kind: "queued", texts: [{ md: "mine", qid: "m1", qts: 2, hiddenByPending: true }, { md: "F", qid: "f2", qts: 3 }] }];
  assert.deepEqual(injectionGroups(again, reconcilePending(again, [mine]).inject), [{ idx: 2, sends: [mine] }], "right after the press-time copy's landing, above the newer F");
  const echoed: TailEvent[] = [...tail, { kind: "user", md: "F", uuid: "uF1", qid: "f1" }, { kind: "tool", uuid: "t1" }, { kind: "user", md: "F", uuid: "echo:f2" }];
  assert.deepEqual(injectionGroups(echoed, reconcilePending(echoed, [mine]).inject), [{ idx: 2, sends: [mine] }], "…and above the newer F's echo");
  // (2) the reconnect: a fed same-text copy (no id we saw) and the press-time copy (qid f1) both land in ONE frame
  const both: TailEvent[] = [...tail, { kind: "user", md: "F", uuid: "uF0", qid: "f0" }, { kind: "tool", uuid: "t1" }, { kind: "user", md: "F", uuid: "uF1", qid: "f1" }, { kind: "tool", uuid: "t2" }];
  const late = newPending("mine", undefined, T0 + 1);
  reconcilePending(queued, [late]);
  assert.deepEqual(injectionGroups(both, reconcilePending(both, [late]).inject), [{ idx: 4, sends: [late] }], "below the copy we were queued behind, by its id, whatever landed first");
  // without ids the same frames degrade to today's reading (the legacy path, an older kernel)
  const strip = (evs: TailEvent[]): TailEvent[] => evs.map((e) => ({ ...e, qid: undefined, texts: e.texts?.map((t) => ({ ...t, qid: undefined })) }));
  const legacy = newPending("mine", undefined, T0 + 2);
  reconcilePending(strip(queued), [legacy]);
  assert.deepEqual(legacy.at?.queuedForeignIds, []);
  assert.deepEqual(injectionGroups(strip(again), reconcilePending(strip(again), [legacy]).inject), [{ idx: 4, sends: [legacy] }], "legacy: below the group while it shows a copy of F");
  const legacy2 = newPending("mine", undefined, T0 + 3);
  reconcilePending(strip(queued), [legacy2]);
  assert.deepEqual(injectionGroups(strip(both), reconcilePending(strip(both), [legacy2]).inject), [{ idx: 2, sends: [legacy2] }], "legacy: the first landing is read as the copy's");
});

test("our own send's identity is latched from the kernel's first copy and then rules landing, cover and hiding (T252c)", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  const p = newPending("continue", undefined, T0);
  reconcilePending(tail, [p]);
  assert.equal(p.qid, undefined);
  // the kernel lists our copy with its id: the copy covers us and we latch the id
  let r = reconcilePending([...tail, { kind: "queued", texts: [{ md: "continue", qid: "c9", qts: 5 }] }], [p]);
  assert.equal(p.qid, "c9");
  assert.deepEqual(r.unqueue, [p]);
  assert.equal(queuedCopyToHide([{ md: "continue", qid: "c8" }, { md: "continue", qid: "c9" }], "continue", "c9"), 1, "the copy to hide is OURS by id, not the newest by text");
  // another client's same-text copy landing does NOT retire us: only the atom carrying our id does
  r = reconcilePending([...tail, { kind: "user", md: "continue", uuid: "uX", qid: "c8" }, { kind: "queued", texts: [{ md: "continue", qid: "c9", qts: 5 }] }], [p]);
  assert.deepEqual(r.keep, [p], "a same-text landing with another id is not ours");
  r = reconcilePending([...tail, { kind: "user", md: "continue", uuid: "uX", qid: "c8" }, { kind: "user", md: "continue", uuid: "uMine", qid: "c9" }], [p]);
  assert.deepEqual(r.landed.map((l) => [l.p, l.idx]), [[p, 2]], "our landing, by id, even behind a same-text one");
  // the echo path latches too: the echo's uuid IS the copy's id
  const q = newPending("go", undefined, T0 + 1);
  reconcilePending(tail, [q]);
  r = reconcilePending([...tail, { kind: "user", md: "go", uuid: "echo:g1" }], [q]);
  assert.equal(q.qid, "echo:g1");
  r = reconcilePending([...tail, { kind: "user", md: "go", uuid: "uG", qid: "echo:g1" }], [q]);
  assert.deepEqual(r.landed.map((l) => l.idx), [1]);
});

test("floors carry the earlier send's identity and follow it through the echo → landed swap exactly (T252c)", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  const [x, y] = press(tail, "first", "second");
  let r = reconcilePending([...tail, { kind: "user", md: "first", uuid: "echo:x1" }], [x, y]);
  assert.equal(x.qid, "echo:x1");
  assert.deepEqual(y.floors?.map((f) => [f.uuid, f.qid]), [["echo:x1", "echo:x1"]]);
  dropPending([x, y], "first", x.ts);   // the ✕ the kernel could not honour
  // X's atom lands under a new uuid but with X's id, behind an unrelated same-text message that has none of it
  const frame: TailEvent[] = [...tail, { kind: "user", md: "first", uuid: "uOther" }, { kind: "tool", uuid: "t1" }, { kind: "user", md: "first", uuid: "uX", qid: "echo:x1" }, { kind: "tool", uuid: "t2" }];
  assert.deepEqual(injectionGroups(frame, reconcilePending(frame, [y]).inject), [{ idx: 4, sends: [y] }], "below X's own atom, found by id, not the first same-text one");
});

test("identity edges: a copy without an id beside an echo, a landing carrying several ids, and an identified copy whose landing lost its id (T252c review)", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  // the tmux route: the queued copy carries a stamp but no id, the echo a random uuid, the landing nothing — text decides
  // throughout, and our bubble never doubles beside the kernel's copies
  const p = newPending("go on", undefined, T0);
  reconcilePending(tail, [p]);
  let r = reconcilePending([...tail, { kind: "queued", texts: [{ md: "go on", qts: 5 }] }], [p]);
  assert.equal(p.qid, undefined, "no id to latch");
  assert.deepEqual(r.unqueue, [p]);
  r = reconcilePending([...tail, { kind: "user", md: "go on", uuid: "echo:random" }], [p]);
  assert.equal(r.inject.length, 0, "the echo covers by text");
  r = reconcilePending([...tail, { kind: "user", md: "go on", uuid: "uL" }], [p]);
  assert.deepEqual(r.landed.map((l) => l.idx), [1]);
  // a record the CLI wrote from two sends lands with one id per block: ours retires on its own block's id
  const [x, y] = press(tail, "one", "two");
  reconcilePending([...tail, { kind: "queued", texts: [{ md: "one", qid: "q1", qts: 1 }, { md: "two", qid: "q2", qts: 2 }] }], [x, y]);
  assert.deepEqual([x.qid, y.qid], ["q1", "q2"]);
  r = reconcilePending([...tail, { kind: "user", md: "one two", uuid: "uXY", blocks: ["one", "two"], qids: ["q1", "q2"] }], [x, y]);
  assert.deepEqual(r.landed.map((l) => [l.p.text, l.idx]), [["one", 1], ["two", 1]]);
  // an identified press-time copy whose landing carries no id (a kernel restart between feed and landing): the text
  // floor still holds — the bubble stays below that message, never jumps above it
  const z = newPending("mine", undefined, T0 + 5);
  reconcilePending([...tail, { kind: "queued", texts: [{ md: "F", qid: "f1", qts: 1 }] }], [z]);
  const lostId: TailEvent[] = [...tail, { kind: "user", md: "F", uuid: "uF" }, { kind: "tool", uuid: "t1" }];
  assert.deepEqual(injectionGroups(lostId, reconcilePending(lostId, [z]).inject), [{ idx: 2, sends: [z] }]);
  // …while an identified copy whose landing DOES carry the id ignores the text path (the newer-copy case stays exact)
  const withId: TailEvent[] = [...tail, { kind: "user", md: "F", uuid: "uF", qid: "f1" }, { kind: "tool", uuid: "t1" }, { kind: "queued", texts: [{ md: "F", qid: "f2", qts: 9 }] }];
  assert.deepEqual(injectionGroups(withId, reconcilePending(withId, [z]).inject), [{ idx: 2, sends: [z] }]);
});

test("a bubble that changes slot marks the view stale, so the incremental repaint never trusts a shifted prefix (second review)", () => {
  // chatTail lowers v.rendered to the kernel index and the normal-mode append path re-renders from there, assuming
  // the DOM prefix still matches s.events — which also requires the bubble's SLOT to be unchanged. The settle
  // signature therefore carries each group's slot beside its texts.
  const fn = RENDER.split("function reconcileOptimistic(")[1].split("\nfunction ")[0];
  assert.match(fn, /settle\(groups\.flatMap\(\(g\) => g\.sends\.map\(\(p\) => g\.idx \+ ":" \+ p\.text\)\)\);/);
  assert.match(fn, /const groups = injectionGroups\(s\.events as TailEvent\[\], inject\);/);
});

test("queuedCopyToHide: the newest not-yet-hidden copy of the text, never a copy the kernel marked non-cancelable", () => {
  // the kernel marks a queued copy cancelable:false when no recall exists (a tmux queue): that copy stays the
  // one bubble shown, with its honest "can't be recalled" tooltip, and ours is suppressed as before — hiding it
  // behind our bubble's ✕ offered a cancel the kernel would refuse (review of the first cut)
  const texts = [{ md: "a" }, { md: "b", cancelable: false }, { md: "a", hiddenByPending: true }, { md: "a" }];
  assert.equal(queuedCopyToHide(texts, "a"), 3, "the newest visible copy");
  assert.equal(queuedCopyToHide(texts.slice(0, 3), "a"), 0, "…skipping one already hidden");
  assert.equal(queuedCopyToHide(texts, "b"), -1, "a non-cancelable copy is never hidden");
  assert.equal(queuedCopyToHide(texts, "zzz"), -1);
  assert.equal(queuedCopyToHide([{ md: " a " }], "a"), 0, "trimmed match, like every other text test");
  // render.ts: a copy the helper refuses keeps covering our bubble (the send leaves `inject`)
  assert.match(RENDER, /const k = queuedCopyToHide\(q\.texts, p\.text, p\.qid\);/);
  assert.match(RENDER, /if \(k < 0\) return null;\s*\/\/ no copy to hide/);
  assert.match(RENDER, /const hid = hideQueuedCopy\(s, p\);\s*\n\s*if \(hid === null\) covered\.add\(p\); else if \(hid\.held\) heldBy\.set\(p, hid\.held\);/);
  assert.match(RENDER, /const inject = r\.inject\.filter\(\(p\) => !covered\.has\(p\)\);/);
});

test("the kernel's queued copy at the tail is hidden for a send drawn in place — one bubble per message (T252)", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  const list = press(tail, TEXT);
  const r = reconcilePending([...tail, { kind: "tool", uuid: "t1" }, { kind: "queued", texts: [{ md: TEXT }] }], list);
  assert.equal(list[0].received, true, "the kernel's copy proves receipt");
  assert.deepEqual(r.inject, [list[0]], "…but ours stays drawn, at its slot");
  assert.deepEqual(r.unqueue, [list[0]], "and the caller drops the kernel's tail copy for it");
  // an ECHO atom covers ours as before: the kernel draws that atom itself, at the send time
  const r2 = reconcilePending([...tail, { kind: "user", md: TEXT, uuid: "echo:1" }], press(tail, TEXT));
  assert.equal(r2.inject.length, 0);
  assert.equal(r2.unqueue.length, 0);
});

test("render.ts draws the bubble at its slot, strips its own injections before applying kernel indices, and carries no header or cue", () => {
  assert.match(RENDER, /const groups = injectionGroups\(s\.events as TailEvent\[\], inject\);\s*\n\s*for \(const g of groups\)\s*\n\s*s\.events\.splice\(g\.idx, 0, \{ kind: "queued", bare: true, texts: g\.sends\.map\(mk\), uuid: OPT_PREFIX \+ g\.sends\[0\]\.ts/,
    "the bare group is spliced at the slot, never pushed at the tail");
  assert.doesNotMatch(RENDER, /s\.events\.push\(\{ kind: "queued", bare: true/, "no tail push remains");
  assert.match(RENDER, /function stripOptimistic\(s: Session\): void \{/, "one strip, used by every ingest path");
  const tail = RENDER.slice(RENDER.indexOf("function chatTail(msg: any) {"), RENDER.indexOf("s.events.length = from;"));
  assert.match(tail, /stripOptimistic\(s\);/, "the delta's kernel index is applied to KERNEL events only — a mid-array bubble would shift it");
  // …but only once the delta is going to be applied: stripping before the gap/head early returns left s.events
  // without the bubble while the DOM still showed it (review of the first cut)
  const afterReturns = tail.slice(tail.indexOf("if (from < 0) return;"));
  assert.match(afterReturns, /stripOptimistic\(s\);/, "the strip sits after both early returns");
  assert.doesNotMatch(tail.slice(0, tail.indexOf("if (from > kernelLen) {")), /stripOptimistic\(s\);/, "…and not before the gap check");
  assert.match(tail, /const kernelLen = s\.events\.reduce\(\(n, e\) => n \+ \(isOptimistic\(e\) \? 0 : 1\), 0\);/, "the gap check counts kernel events without mutating");
  for (const gone of ["absorbedHeader", "absorbedCues", "noteAbsorbedLanding", "renderAbsorbedCue", "appendAbsorbedCues", "dismissAbsorbedCue", "cueRendered", "abjump", "abdismiss", "absorbed-tag", "turn-absorbed-cue"])
    assert.ok(!RENDER.includes(gone), gone + " is gone from render.ts");
  for (const gone of [".absorbed-tag", ".turn-absorbed-cue", ".absorbed-cue-line", ".absorbed-cue-act"])
    assert.ok(!CSS.includes(gone), gone + " is gone from styles.css");
  // the "not confirmed" state and the ✕ on the pending bubble itself stay
  assert.match(RENDER, /if \(t\.optimistic && t\.lost\) bubble\.dataset\.lost = "1";/);
  assert.match(RENDER, /if \(t\.optimistic\) x\.dataset\.qopt = "1";/);
});

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
  assert.match(RENDER, /const nLost = texts\.filter\(\(t\) => t\.lost\)\.length;\s*\n\s*fillBareLabel\(label, nLost, texts\.length - nLost\);/);
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
  assert.deepEqual(r.inject, [list[0], list[1]], "both drawn in place (T252); the kernel's one copy is hidden for the first");
  assert.deepEqual(r.unqueue, [list[0]]);
  r = reconcilePending([...tail, { kind: "queued", texts: [{ md: "continue" }, { md: "continue" }] }], list);
  assert.deepEqual(list.map((p) => p.received), [true, true]);
  assert.deepEqual(r.unqueue, [list[0], list[1]], "two kernel copies, both hidden: two bubbles for two sends, in place");
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
  assert.deepEqual(list[0].at, { after: "a1", place: "u-old", placeText: TEXT, placeOrd: 0, queuedForeign: [], queuedForeignIds: [], queuedResident: {}, seen: ["u-old"], queued: 0 });
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
    assert.equal(r.inject.length, 1, "ours stays drawn at its send slot (T252)…");
    assert.equal(r.unqueue.length, 1, "…and the kernel's copy is the one hidden: no double bubble");
    assert.equal(list[0].received, true);
    // every later push, the same copy keeps proving receipt — the entry never sat unconfirmed until the CLI took it
    r = reconcilePending([step, q], list);
    assert.equal(r.inject.length, 1);
    assert.equal(r.unqueue.length, 1);
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
  assert.deepEqual(early[0].at, { after: "a1", place: null, placeText: undefined, placeOrd: 0, queuedForeign: [], queuedForeignIds: [], queuedResident: {}, seen: [], queued: 0 });
  assert.equal(r.inject.length, 1);
  r = reconcilePending([step, { kind: "queued", texts: [{ md: TEXT }] }], early);
  assert.equal(r.inject.length, 1);
  assert.equal(r.unqueue.length, 1, "the copy that follows is this send's: hidden, ours drawn, receipt proven");
  assert.equal(early[0].received, true);
  // two identical sends pressed against the same placeholder frame own one copy EACH — and when the frame
  // lists only one of them (the kernel had not received the second), the second waits for its own
  const pair = [late(), late()];
  r = reconcilePending([step, { kind: "queued", texts: [{ md: TEXT }, { md: TEXT }] }], pair);
  assert.deepEqual(pair.map((p) => p.at?.queued), [0, 0]);
  assert.equal(r.inject.length, 2, "both copies are the pair's: both hidden, both of ours drawn");
  assert.equal(r.unqueue.length, 2);
  const pair2 = [late(), late()];
  r = reconcilePending([step, { kind: "queued", texts: [{ md: TEXT }] }], pair2);
  assert.deepEqual(pair2.map((p) => p.at?.queued), [0, 0], "fewer copies than presses: the count floors at zero");
  assert.equal(r.inject.length, 2, "both drawn; one copy proves one send, the other waits for its own");
  assert.equal(r.unqueue.length, 1);
  r = reconcilePending([step, { kind: "queued", texts: [{ md: TEXT }, { md: TEXT }] }], pair2);
  assert.equal(r.unqueue.length, 2);
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

// ── (T252c, second review) identity decides where the frame SHOWS it; text decides where it does not ──────

test("two identical identified sends the CLI took as one record both retire on that landing (T252c second review)", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  const [p1, p2] = press(tail, "ok", "ok");
  reconcilePending([...tail, { kind: "queued", texts: [{ md: "ok", qid: "echo:q1", qts: 1 }, { md: "ok", qid: "echo:q2", qts: 2 }] }], [p1, p2]);
  assert.deepEqual([p1.qid, p2.qid], ["echo:q1", "echo:q2"]);
  const landing: TailEvent[] = [...tail, { kind: "user", md: "ok ok", uuid: "uXY", blocks: ["ok", "ok"], qids: ["echo:q1", "echo:q2"] }];
  const r = reconcilePending(landing, [p1, p2]);
  assert.deepEqual(r.landed.map((l) => [l.p, l.idx]), [[p1, 1], [p2, 1]], "each retires on its own block's id, whatever the other claimed of the text");
  assert.deepEqual(r.keep, []);
  // and the frames after: nothing lingers
  assert.deepEqual(reconcilePending(landing, [p1, p2].filter((p) => !r.landed.some((l) => l.p === p))).keep, []);
});

test("an id the frame no longer carries leaves the decision to text: a restart that re-minted the mirrors, or an older kernel (T252c second review)", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  const latched = (text: string, ts: number): PendingSend => {
    const p = newPending(text, undefined, ts);
    reconcilePending(tail, [p]);
    reconcilePending([...tail, { kind: "queued", texts: [{ md: text, qid: "echo:old" + ts, qts: 1 }] }], [p]);
    assert.equal(p.qid, "echo:old" + ts);
    return p;
  };
  // (1) the restored copy carries no id: it still covers ours, by text — ours drawn at its slot, that copy hidden
  let p = latched("rename it", T0);
  let r = reconcilePending([...tail, { kind: "queued", texts: [{ md: "rename it" }] }], [p]);
  assert.deepEqual([r.unqueue, r.inject], [[p], [p]], "one bubble, never ours beside the kernel's copy");
  // (2) an echo under a new uuid covers by text, and the first identity stays latched: nothing in the frame contradicts it
  r = reconcilePending([...tail, { kind: "user", md: "rename it", uuid: "echo:new" }], [p]);
  assert.deepEqual([r.inject, r.keep], [[], [p]], "the echo covers");
  assert.equal(p.qid, "echo:old" + T0);
  // (3) that echo flagged never-delivered is the verdict, by text
  r = reconcilePending([...tail, { kind: "user", md: "rename it", uuid: "echo:new", undelivered: true }], [p]);
  assert.deepEqual(r.lost, [p]);
  // (4) a record the CLI wrote from the restored copy and a later identified send: our block carries no id, text lands it
  p = latched("rename it", T0 + 1);
  r = reconcilePending([...tail, { kind: "user", md: "rename it and go", uuid: "uB", blocks: ["rename it", "and go"], qids: [null, "echo:new2"] }], [p]);
  assert.deepEqual(r.landed.map((l) => l.idx), [1]);
});

test("an id the frame still shows queued or echoed refuses a same-text landing that lacks it (T252c second review)", () => {
  const tail: TailEvent[] = [{ kind: "assistant", md: "…", uuid: "a1" }];
  const [a, b] = press(tail, "ok", "ok");
  reconcilePending([...tail, { kind: "queued", texts: [{ md: "ok", qid: "echo:q1", qts: 1 }, { md: "ok", qid: "echo:q2", qts: 2 }] }], [a, b]);
  // the first copy lands unpaired (no id on the record) while the second is still queued under its id
  let r = reconcilePending([...tail, { kind: "user", md: "ok", uuid: "u1" }, { kind: "queued", texts: [{ md: "ok", qid: "echo:q2", qts: 2 }] }], [a, b]);
  assert.deepEqual(r.landed.map((l) => l.p), [a], "the id-less landing is the first send's, by text");
  assert.deepEqual([r.keep, r.unqueue, r.inject], [[b], [b], [b]], "the second is still in the queue under its id: not that landing's");
  // the same with the second copy fed: its echo shows the id — and the first send, landed, does not go on to claim
  // that echo as its own cover on the way out
  r = reconcilePending([...tail, { kind: "user", md: "ok", uuid: "u1" }, { kind: "user", md: "ok", uuid: "echo:q2" }], [a, b]);
  assert.deepEqual([r.landed.map((l) => l.p), r.keep, r.inject], [[a], [b], []]);
  // a send read by text (its id is nowhere in the frame) never takes an echo another send owns by id
  const [c, d] = press(tail, "go", "go");
  reconcilePending([...tail, { kind: "queued", texts: [{ md: "go", qid: "echo:c1", qts: 1 }, { md: "go", qid: "echo:d1", qts: 2 }] }], [c, d]);
  assert.deepEqual([c.qid, d.qid], ["echo:c1", "echo:d1"]);
  r = reconcilePending([...tail, { kind: "user", md: "go", uuid: "echo:d1" }], [c, d]);
  assert.deepEqual([r.keep, r.inject], [[c, d], [c]], "the echo is the second send's cover; the first, unshown, is drawn by us");
});
