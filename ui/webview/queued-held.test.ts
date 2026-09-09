import { test } from "node:test";
import * as assert from "node:assert/strict";
import { reconcileHeld, heldAsQueued, landsCopy, lastKernelUuid, type HeldMemory, type HeldEvent, type HeldQueued } from "./queued-held";

// T262i: a kernel queued copy that left the queue frame before its landed record arrived is HELD in place, marked
// landing, until the atom carrying its id arrives; an id-less copy is held by text for one push; never a phantom.
// The follow-up (the first review's reproductions): a copy judged against the PREVIOUS push's anchor, so one that
// vanishes and lands in the same push is released; a landing that releases a sibling is not a "later" landing; a
// copy the user cancelled here, or one that vanished on a settled session, is never held; copies count per text.

const mail = "[romp mail from api] the fixtures batch is labeled";
const base: HeldEvent[] = [{ kind: "user", uuid: "u1", md: "tighten the search" }, { kind: "assistant", uuid: "a1", md: "…" }];
const fresh = (): HeldMemory => ({ prev: [], anchor: null, held: [] });
const withCard = (qid?: string): HeldMemory => reconcileHeld(fresh(), base, [{ md: mail, ...(qid ? { qid, qts: 5 } : {}), romp: true }]);

test("an identified copy that vanished from the queue is held until the atom with its id lands, then released", () => {
  let m = withCard("echo:m1");
  assert.deepEqual([m.prev.map((p) => p.qid), m.anchor, m.held], [["echo:m1"], "a1", []], "the memory: the copies listed, the push's anchor");
  // push 1: the queue no longer lists it, nothing landed → held, judged against the previous push's anchor
  m = reconcileHeld(m, base, []);
  assert.deepEqual(m.held.map((h) => [h.qid, h.since, h.pushes]), [["echo:m1", "a1", 0]]);
  assert.deepEqual(heldAsQueued(m.held[0]), { md: mail, qid: "echo:m1", qts: 5, romp: true, rompSystem: undefined, rompAuto: undefined, followUp: undefined, goal: undefined, fuCtx: undefined, imgPaths: undefined, landing: true });
  // push 2: still nothing → still held (an identified copy waits for its atom)
  m = reconcileHeld(m, base, []);
  assert.deepEqual(m.held.map((h) => [h.qid, h.pushes]), [["echo:m1", 1]]);
  // push 3: the atom with its id lands → released (the atom takes the slot)
  m = reconcileHeld(m, [...base, { kind: "user", uuid: "am1", md: mail, qid: "echo:m1" }], []);
  assert.deepEqual(m.held, []);
  // a record of several sends carrying the id among its qids releases it too
  let m2 = reconcileHeld(withCard("echo:m1"), base, []);
  m2 = reconcileHeld(m2, [...base, { kind: "user", uuid: "am9", md: "x y", blocks: [mail, "y"], qids: ["echo:m1", "q9"] }], []);
  assert.deepEqual(m2.held, []);
});

test("a copy that vanishes and lands in the SAME push is released, never held (the anchor is the previous push's)", () => {
  const m = reconcileHeld(withCard("echo:m1"), [...base, { kind: "user", uuid: "am1", md: mail, qid: "echo:m1" }], []);
  assert.deepEqual(m.held, [], "its landing sits after the previous push's tail: released");
  assert.equal(m.anchor, "am1", "…and the new anchor is that landing");
  const t = reconcileHeld(withCard(), [...base, { kind: "user", uuid: "am1", md: mail }], []);
  assert.deepEqual(t.held, [], "the id-less copy too, by text");
});

test("a held identified copy is dropped once a LATER landing shows the CLI passed it — but a landing that releases a sibling is not later", () => {
  let m = reconcileHeld(withCard("echo:m1"), base, []);
  m = reconcileHeld(m, [...base, { kind: "user", uuid: "u2", md: "something else" }], []);
  assert.deepEqual(m.held, [], "a later landing drops the hold");
  // the kernel's echo or an undelivered verdict is not a landing
  let m2 = reconcileHeld(withCard("echo:m1"), base, []);
  m2 = reconcileHeld(m2, [...base, { kind: "user", uuid: "echo:x", md: "something else" }, { kind: "user", uuid: "u3", md: "lost", undelivered: true }], []);
  assert.deepEqual(m2.held.map((h) => h.qid), ["echo:m1"], "an echo or a verdict is not a later landing");
  // two copies taken at one boundary: the first's record lands alone — the second stays held for its own
  let m3 = reconcileHeld(fresh(), base, [{ md: "first mail", qid: "echo:a" }, { md: "second mail", qid: "echo:b" }]);
  m3 = reconcileHeld(m3, base, []);
  assert.deepEqual(m3.held.map((h) => h.qid), ["echo:a", "echo:b"]);
  m3 = reconcileHeld(m3, [...base, { kind: "user", uuid: "aa", md: "first mail", qid: "echo:a" }], []);
  assert.deepEqual(m3.held.map((h) => h.qid), ["echo:b"], "the first's landing releases the first and is not a later landing for the second");
  m3 = reconcileHeld(m3, [...base, { kind: "user", uuid: "aa", md: "first mail", qid: "echo:a" }, { kind: "user", uuid: "ab", md: "second mail", qid: "echo:b" }], []);
  assert.deepEqual(m3.held, []);
  // the copy is listed again (the queue frame shows it): nothing to hold
  let m4 = reconcileHeld(withCard("echo:m1"), base, []);
  m4 = reconcileHeld(m4, base, [{ md: mail, qid: "echo:m1" }]);
  assert.deepEqual([m4.held, m4.prev.map((p) => p.qid)], [[], ["echo:m1"]]);
  // the anchor left the resident window: the same reading as a later landing (never a phantom)
  let m5 = reconcileHeld(withCard("echo:m1"), base, []);
  m5 = reconcileHeld(m5, [{ kind: "assistant", uuid: "a7", md: "…" }], []);
  assert.deepEqual(m5.held, []);
});

test("a copy the user cancelled here, or one that vanished on a SETTLED session, is never held", () => {
  const cancelled = (c: { md: string; qid?: string }) => c.qid === "echo:m1";
  const m = reconcileHeld(withCard("echo:m1"), base, [], { cancelled });
  assert.deepEqual(m.held, [], "the ✕ said so: nothing will land");
  const s = reconcileHeld(withCard("echo:m1"), base, [], { settled: true });
  assert.deepEqual(s.held, [], "a settled session took nothing: cancelled or dropped");
  let h = reconcileHeld(withCard("echo:m1"), base, []);
  h = reconcileHeld(h, base, [], { settled: true });
  assert.deepEqual(h.held, [], "…and a hold is dropped the push the session settles without a landing");
});

test("an id-less copy is held by text for the push it vanished on and dropped at the next, unless its text lands first", () => {
  let m = reconcileHeld(withCard(), base, []);
  assert.deepEqual(m.held.map((h) => [h.qid, h.pushes]), [[undefined, 0]]);
  m = reconcileHeld(m, base, []);
  assert.deepEqual(m.held, [], "dropped at the next push that carries the queue");
  let m2 = reconcileHeld(withCard(), base, []);
  m2 = reconcileHeld(m2, [...base, { kind: "user", uuid: "am2", md: mail }], []);
  assert.deepEqual(m2.held, []);
  // a same-text copy still queued: not vanished, nothing held
  assert.deepEqual(reconcileHeld(withCard(), base, [{ md: mail }]).held, []);
  // an OLDER record of the same text (before the anchor) is history, not this copy's landing: still held
  const older: HeldEvent[] = [{ kind: "user", uuid: "am0", md: mail }, ...base];
  let m3 = reconcileHeld(reconcileHeld(fresh(), older, [{ md: mail }]), older, []);
  assert.deepEqual(m3.held.map((h) => [h.qid, h.since]), [[undefined, "a1"]], "held: the same-text record predates the vanish");
  m3 = reconcileHeld(m3, [...older, { kind: "user", uuid: "am1", md: mail }], []);
  assert.deepEqual(m3.held, [], "…and the record after the anchor claims it");
  // two identical id-less copies, one taken: one is held (counted per text)
  let m4 = reconcileHeld(fresh(), base, [{ md: mail }, { md: mail }]);
  m4 = reconcileHeld(m4, base, [{ md: mail }]);
  assert.deepEqual(m4.held.map((h) => h.md), [mail], "the copy that left is the one held");
});

test("our own bubble and hidden copies never become held copies; a landing is a real record only; the anchor skips uuid-less markers", () => {
  const prev: HeldQueued[] = [{ md: "mine", optimistic: true }, { md: "hidden", qid: "h1", hiddenByPending: true }, { md: mail, qid: "echo:m1" }];
  const m = reconcileHeld(reconcileHeld(fresh(), base, prev), base, []);
  assert.deepEqual(m.held.map((h) => h.qid), ["echo:m1"]);
  assert.equal(landsCopy({ kind: "user", uuid: "echo:m1", md: mail }, { md: mail, qid: "echo:m1" }), false, "the kernel's echo is not a landing");
  assert.equal(landsCopy({ kind: "user", uuid: "optimistic:1", md: mail }, { md: mail }), false, "our bubble is not a landing");
  assert.equal(landsCopy({ kind: "user", uuid: "u9", md: mail }, { md: mail, qid: "echo:m1" }), false, "an id-bearing copy needs its id, not its text");
  assert.equal(landsCopy({ kind: "user", uuid: "u9", md: mail }, { md: mail }), true);
  assert.equal(lastKernelUuid([...base, { kind: "compacting" }, { kind: "queued" }]), "a1", "a uuid-less marker or a queued group is no anchor");
});
