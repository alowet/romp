// The pending-rewind pass (rewind-reconcile.ts), RUN: the editable set, the overlay, the pending edit's
// retirement, and the STALE signal the chat's exact tail path rests on — a prefix bubble below the tail's
// re-render start whose edit affordance or dim changed marks the view stale; a plain human-prompt append at
// the tail does not. `now` is injected; nothing sleeps. Synthetic events, placeholder uuids.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import { reconcileRewindPass, rewindSig, type PendingRewind, type RewindEvent } from "./rewind-reconcile";

type Ev = RewindEvent & { kind: string; uuid?: string };
const OPT = "optimistic:";
const user = (uuid: string, md = "ask " + uuid): Ev => ({ kind: "user", human: true, uuid, md });
const reply = (uuid: string): Ev => ({ kind: "assistant", uuid, md: "reply" });
const opts = (over: Partial<{ sdk: boolean; now: number; ttlMs: number; bound: number }> = {}) =>
  ({ sdk: true, now: 100_000, ttlMs: 30_000, optPrefix: OPT, ...over });
const A = "11111111-2222-3333-4444-aaaaaaaaaaaa", B = "11111111-2222-3333-4444-bbbbbbbbbbbb", C = "11111111-2222-3333-4444-cccccccccccc";

test("the editable set: genuine human prompts with a uuid after the last compaction, on an SDK session; an optimistic echo, an injected line and a non-SDK session get none", () => {
  const evs: Ev[] = [user(A), reply("r1"), { kind: "user", human: true, uuid: OPT + "5", md: "echo" }, { kind: "user", romp: true, uuid: "n1", md: "nudge" }, user(B)];
  const r = reconcileRewindPass(evs, undefined, null, opts());
  assert.deepEqual([...r.editable].sort(), [A, B].sort());
  assert.equal(r.pending, null);
  assert.equal(r.stale, true, "the first pass (no previous set) reads as a change");
  assert.deepEqual([...reconcileRewindPass(evs, r.editable, null, opts({ sdk: false })).editable], [], "a CLI session: nothing addressable");
});

test("a compaction landing at the tail's `from` strips the affordance from every earlier bubble: stale, though nothing below `from` was re-rendered", () => {
  const evs: Ev[] = [user(A), reply("r1"), user(B), reply("r2")];
  const first = reconcileRewindPass(evs, undefined, null, opts());
  assert.deepEqual([...first.editable].sort(), [A, B].sort());
  evs.push({ kind: "compact" });                                    // the chatTail appended it at index 4
  const r = reconcileRewindPass(evs, first.editable, null, opts({ bound: 4 }));
  assert.deepEqual([...r.editable], [], "nothing after the boundary is a human prompt");
  assert.equal(r.stale, true, "the bubbles below `from` lost their edit buttons: the tail cannot repaint them, this signal does");
});

test("a plain human-prompt append does NOT mark the view stale: the signature reads the prefix below the tail's re-render start", () => {
  const evs: Ev[] = [user(A), reply("r1")];
  const first = reconcileRewindPass(evs, undefined, null, opts());
  evs.push(user(C));                                                // the landing prompt, at from = 2
  const r = reconcileRewindPass(evs, first.editable, null, opts({ bound: 2 }));
  assert.deepEqual([...r.editable].sort(), [A, C].sort(), "the new bubble is editable…");
  assert.equal(r.stale, false, "…and it is at or past `from`, so the tail renders it itself: no whole-window rebuild");
  const again = reconcileRewindPass(evs, r.editable, null, opts());   // an unchanged re-pass, unbounded
  assert.equal(again.stale, false);
  assert.equal(reconcileRewindPass(evs, r.editable, null, opts({ bound: evs.length })).stale, false, "the same with bound = len (a status-only tail)");
});

test("a pending edit dims every later event and replaces the bubble's text; an unchanged re-pass while it stands is NOT stale (the signature is taken before the strip)", () => {
  const evs: Ev[] = [user(A), reply("r1"), user(B, "old text"), reply("r2"), { kind: "queued", texts: [{ md: "new text" }, { md: "another" }] }];
  const pr: PendingRewind = { uuid: B, text: "new text", ts: 100_000 };
  const first = reconcileRewindPass(evs, new Set([A, B]), pr, opts());
  assert.equal(first.pending, pr, "the edit stands: the old uuid is still in the transcript and the TTL has not run out");
  assert.equal(first.stale, true, "the overlay appeared");
  assert.deepEqual(evs.map((e) => !!e.rewound), [false, false, false, true, true], "everything after the edited bubble dims");
  assert.equal(evs[2].md, "new text"); assert.equal(evs[2].pending, true);
  assert.deepEqual(evs[4].texts, [{ md: "another" }], "the queued echo of the edit's own text is suppressed (the overlay shows it in place)");
  const again = reconcileRewindPass(evs, first.editable, first.pending, opts({ now: 110_000 }));
  assert.equal(again.stale, false, "the same edit, the same dims: a pass that changes nothing marks nothing stale");
  assert.deepEqual(evs.map((e) => !!e.rewound), [false, false, false, true, true], "the flags were stripped and re-applied, not doubled or lost");
  // a queued echo whose only text was the edit's leaves the transcript
  const evs2: Ev[] = [user(B, "old"), { kind: "queued", texts: [{ md: "new text" }] }];
  reconcileRewindPass(evs2, undefined, pr, opts());
  assert.equal(evs2.length, 1, "the emptied queued event is spliced out");
});

test("a bare delete dims from the deleted bubble itself, with no text replacement", () => {
  const evs: Ev[] = [user(A), reply("r1"), user(B, "gone"), reply("r2")];
  const r = reconcileRewindPass(evs, new Set([A, B]), { uuid: B, text: "", ts: 100_000, bare: true }, opts());
  assert.deepEqual(evs.map((e) => !!e.rewound), [false, false, true, true]);
  assert.equal(evs[2].md, "gone"); assert.equal(evs[2].pending, undefined);
  assert.equal(r.stale, true);
  assert.equal(rewindSig(evs, r.editable, r.pending).endsWith("|" + B + ":b"), true, "the signature names the delete as such");
});

test("the TTL backstop retires a failed rewind and lifts its dim: stale, with nothing rewound and the entry gone", () => {
  const evs: Ev[] = [user(A), reply("r1"), user(B, "new text"), reply("r2"), reply("r3")];
  const pr: PendingRewind = { uuid: B, text: "new text", ts: 100_000 };
  const live = reconcileRewindPass(evs, new Set([A, B]), pr, opts({ now: 120_000 }));
  assert.equal(live.pending, pr); assert.deepEqual(evs.map((e) => !!e.rewound), [false, false, false, true, true]);
  const r = reconcileRewindPass(evs, live.editable, live.pending, opts({ now: 130_001, bound: evs.length }));   // a status-only tail after the TTL
  assert.equal(r.pending, null, "expired");
  assert.deepEqual(evs.map((e) => !!e.rewound), [false, false, false, false, false], "the dim is lifted");
  assert.equal(r.stale, true, "no `from` reaches back to those turns: this signal repaints them");
});

test("the retirement is stale on a PARTIAL tail too: the pending edit is unbounded in the signature (no dimmed event lies below the tail's start)", () => {
  const evs: Ev[] = [user(A), reply("r1"), user(B, "new text"), reply("r2"), reply("r3")];
  const pr: PendingRewind = { uuid: B, text: "new text", ts: 100_000 };
  const live = reconcileRewindPass(evs, new Set([A, B]), pr, opts({ now: 120_000 }));
  // the tail re-renders from 3 (the first dimmed event), so the dims below the bound are empty before and after;
  // only the pending part of the signature can carry the change — and it must
  const r = reconcileRewindPass(evs, live.editable, live.pending, opts({ now: 130_001, bound: 3 }));
  assert.equal(r.pending, null);
  assert.equal(r.stale, true, "the edited bubble at 2 lost its pending text: below `from`, repainted by this signal");
});

test("the branch landing (the old uuid gone from the payload) retires the edit the same way", () => {
  const evs: Ev[] = [user(A), reply("r1"), user(C, "new text")];   // the kernel's new transcript: B is gone, C is the rewound prompt
  const r = reconcileRewindPass(evs, new Set([A, B]), { uuid: B, text: "new text", ts: 100_000 }, opts({ bound: 2 }));
  assert.equal(r.pending, null);
  assert.deepEqual([...r.editable].sort(), [A, C].sort());
  assert.equal(r.stale, true, "the prefix's editable set changed (B left it)");
});
