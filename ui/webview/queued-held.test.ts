import { test } from "node:test";
import * as assert from "node:assert/strict";
import { reconcileHeld, heldAsQueued, landsCopy, type HeldCopy, type HeldEvent, type HeldQueued } from "./queued-held";

// T262i: a kernel queued copy that left the queue frame before its landed record arrived is HELD in place, marked
// landing, until the atom carrying its id arrives; an id-less copy is held by text for one push; never a phantom.

const mail = "[romp mail from api] the fixtures batch is labeled";
const base: HeldEvent[] = [{ kind: "user", uuid: "u1", md: "tighten the search" }, { kind: "assistant", uuid: "a1", md: "…" }];

test("an identified copy that vanished from the queue is held until the atom with its id lands, then released", () => {
  const prev: HeldQueued[] = [{ md: mail, qid: "echo:m1", qts: 5, romp: true }];
  // push 1: the queue no longer lists it, nothing landed → held, anchored on the last kernel event
  let r = reconcileHeld(prev, [], base, []);
  assert.deepEqual(r.held.map((h) => [h.qid, h.since, h.pushes]), [["echo:m1", "a1", 0]]);
  assert.deepEqual(heldAsQueued(r.held[0]), { md: mail, qid: "echo:m1", qts: 5, romp: true, rompSystem: undefined, rompAuto: undefined, followUp: undefined, goal: undefined, fuCtx: undefined, imgPaths: undefined, landing: true });
  // push 2: still nothing → still held (an identified copy waits for its atom)
  r = reconcileHeld(r.prev, r.held, base, []);
  assert.deepEqual(r.held.map((h) => [h.qid, h.pushes]), [["echo:m1", 1]]);
  // push 3: the atom with its id lands → released (the atom takes the slot)
  r = reconcileHeld(r.prev, r.held, [...base, { kind: "user", uuid: "am1", md: mail, qid: "echo:m1" }], []);
  assert.deepEqual(r.held, []);
  // a record of several sends carrying the id among its qids releases it too
  let r2 = reconcileHeld(prev, [], base, []);
  r2 = reconcileHeld(r2.prev, r2.held, [...base, { kind: "user", uuid: "am9", md: "x y", blocks: [mail, "y"], qids: ["echo:m1", "q9"] }], []);
  assert.deepEqual(r2.held, []);
});

test("a held identified copy is dropped once a LATER landing shows the CLI passed it, or once the queue lists it again", () => {
  const prev: HeldQueued[] = [{ md: mail, qid: "echo:m1" }];
  let r = reconcileHeld(prev, [], base, []);
  // another message landed after the anchor without this copy's id: first-in-first-out says this copy is not coming
  r = reconcileHeld(r.prev, r.held, [...base, { kind: "user", uuid: "u2", md: "something else" }], []);
  assert.deepEqual(r.held, [], "a later landing drops the hold");
  // the kernel's echo or an undelivered verdict is not a landing
  let r2 = reconcileHeld(prev, [], base, []);
  r2 = reconcileHeld(r2.prev, r2.held, [...base, { kind: "user", uuid: "echo:x", md: "something else" }, { kind: "user", uuid: "u3", md: "lost", undelivered: true }], []);
  assert.deepEqual(r2.held.map((h) => h.qid), ["echo:m1"], "an echo or a verdict is not a later landing");
  // the copy is listed again (the queue frame shows it): nothing to hold
  let r3 = reconcileHeld(prev, [], base, []);
  r3 = reconcileHeld(r3.prev, r3.held, base, [{ md: mail, qid: "echo:m1" }]);
  assert.deepEqual(r3.held, []);
  assert.deepEqual(r3.prev.map((p) => p.qid), ["echo:m1"], "…and it is the previous frame's copy again");
  // the anchor left the resident window: the same reading as a later landing (never a phantom)
  let r4 = reconcileHeld(prev, [], base, []);
  r4 = reconcileHeld(r4.prev, r4.held, [{ kind: "assistant", uuid: "a7", md: "…" }], []);
  assert.deepEqual(r4.held, []);
});

test("an id-less copy is held by text for the push it vanished on and dropped at the next, unless its text lands first", () => {
  const prev: HeldQueued[] = [{ md: mail }];
  let r = reconcileHeld(prev, [], base, []);
  assert.deepEqual(r.held.map((h) => [h.qid, h.pushes]), [[undefined, 0]]);
  const held1 = r.held;
  r = reconcileHeld(r.prev, held1, base, []);
  assert.deepEqual(r.held, [], "dropped at the next push that carries the queue");
  // …but a landing of the text on that next push claims it (released, not dropped: the atom is there)
  let r2 = reconcileHeld(prev, [], base, []);
  r2 = reconcileHeld(r2.prev, r2.held, [...base, { kind: "user", uuid: "am2", md: mail }], []);
  assert.deepEqual(r2.held, []);
  // a same-text copy still queued: not vanished, nothing held
  assert.deepEqual(reconcileHeld(prev, [], base, [{ md: mail }]).held, []);
  // an OLDER record of the same text (before the anchor) is history, not this copy's landing: still held
  const older: HeldEvent[] = [{ kind: "user", uuid: "am0", md: mail }, ...base];
  let r3 = reconcileHeld(prev, [], older, []);
  assert.deepEqual(r3.held.map((h) => [h.qid, h.since]), [[undefined, "a1"]], "held: the same-text record predates the vanish");
  r3 = reconcileHeld(r3.prev, r3.held, [...older, { kind: "user", uuid: "am1", md: mail }], []);
  assert.deepEqual(r3.held, [], "…and the record after the anchor claims it");
});

test("our own bubble and hidden copies never become held copies; a landing is a real record only", () => {
  const prev: HeldQueued[] = [{ md: "mine", optimistic: true }, { md: "hidden", qid: "h1", hiddenByPending: true }, { md: mail, qid: "echo:m1" }];
  const r = reconcileHeld(prev, [], base, []);
  assert.deepEqual(r.held.map((h) => h.qid), ["echo:m1"]);
  assert.equal(landsCopy({ kind: "user", uuid: "echo:m1", md: mail }, { md: mail, qid: "echo:m1" }), false, "the kernel's echo is not a landing");
  assert.equal(landsCopy({ kind: "user", uuid: "optimistic:1", md: mail }, { md: mail }), false, "our bubble is not a landing");
  assert.equal(landsCopy({ kind: "user", uuid: "u9", md: mail }, { md: mail, qid: "echo:m1" }), false, "an id-bearing copy needs its id, not its text");
  assert.equal(landsCopy({ kind: "user", uuid: "u9", md: mail }, { md: mail }), true);
});
