// The feed applies every payload while the tab is hidden but paints none of them (the user 2026-09-07,
// whose dashboard froze on the return to its browser tab): each hidden render was a full paint — the FLIP
// pass's two forced layouts and a double rAF per moved card all piled onto the return frame. Now render()
// is owed while nobody can see the pane and settled ONCE, synchronously, on the event that shows it, with
// the flip skipped (cards that moved while away snap into place: motion without new information, the
// 2026-07-29 rule). State keeps flowing: the follow-move backstop must find its prediction already
// confirmed by a payload applied hidden, or it would revert a move the kernel had confirmed.
//
// feed.ts has import-time DOM side effects (the repo convention: no test imports it), so this has two
// halves — the harness below runs the PINNED lines against the pure modules they call (paint-gate.ts,
// feed-flip.ts), and the source pins hold feed.ts to exactly that wiring.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { paintHeld, paintReleased } from "./paint-gate";
import { flipNeeded } from "./feed-flip";

type Ask = { itemId: string; column: string };
type Payload = { asks: Ask[] };

// The harness: feed.ts's render() gate, flip decision, release path and the follow-move backstop, line for
// line (the pins below are what keep this honest), over a list whose "content" is its painted cards.
function feedHarness() {
  const st = {
    hidden: false, intersecting: true,
    asks: [] as Ask[], painted: 0,                     // painted = list.childElementCount after the last paint
    pendingFollowMove: new Map<string, true>(),
    paintDirty: false, skipFlipOnce: false,
    prevCols: new Map<string, string>(),
    paints: 0, flipChecks: 0, lastNeedFlip: null as boolean | null,
  };
  const columnsOf = (asks: Ask[]) => new Map(asks.map((a, i) => ["a:" + a.itemId, a.column + ":" + i] as const));
  const flipNeededSpy = (a: Map<string, string>, b: Map<string, string>) => { st.flipChecks++; return flipNeeded(a, b); };
  function render() {
    if (paintHeld(st.hidden, st.intersecting, st.painted > 0)) { st.paintDirty = true; return; }
    const nextCols = columnsOf(st.asks);
    const needFlip = !st.skipFlipOnce && flipNeededSpy(st.prevCols, nextCols);
    st.skipFlipOnce = false;
    st.prevCols = nextCols;
    st.lastNeedFlip = needFlip;
    st.paints++; st.painted = st.asks.length;
  }
  // applyFeedPayload: model swap + reconcileFollowMove (a prediction the kernel now lists as working is
  // confirmed → dropped) + render(); nothing here looks at the visibility
  function applyFeedPayload(m: Payload) {
    st.asks = m.asks;
    for (const id of Array.from(st.pendingFollowMove.keys())) {
      const a = m.asks.find((x) => x.itemId === id);
      if (!a || a.column === "working") st.pendingFollowMove.delete(id);
    }
    render();
  }
  // ackFollowMove's backstop timer body
  function backstop(itemId: string): "kept" | "reverted" {
    if (!st.pendingFollowMove.has(itemId)) return "kept";
    st.pendingFollowMove.delete(itemId); render(); return "reverted";
  }
  function releasePaint() {
    if (!paintReleased(st.paintDirty, st.hidden, st.intersecting)) return;
    st.paintDirty = false;
    st.skipFlipOnce = true;
    render();
  }
  return { st, render, applyFeedPayload, backstop, releasePaint, columnsOf };
}

test("hidden → ten payloads → zero paints, while the asks model and the follow-move bookkeeping keep updating", () => {
  const f = feedHarness();
  f.applyFeedPayload({ asks: [{ itemId: "g1", column: "asks" }, { itemId: "g2", column: "needsInput" }] });   // first content, visible
  assert.equal(f.st.paints, 1);
  f.st.pendingFollowMove.set("g2", true);          // the user replied to g2: predicted into Working
  f.st.hidden = true;                              // the tab goes to the background
  for (let i = 0; i < 10; i++) {
    f.applyFeedPayload({ asks: [{ itemId: "g1", column: "asks" }, { itemId: "g2", column: i >= 3 ? "working" : "needsInput" }, { itemId: "g" + (10 + i), column: "asks" }] });
  }
  assert.equal(f.st.paints, 1, "no paint while hidden");
  assert.equal(f.st.paintDirty, true, "a paint is owed");
  assert.equal(f.st.asks.length, 3, "the model is the newest payload's");
  assert.equal(f.st.asks[2].itemId, "g19");
  assert.equal(f.st.pendingFollowMove.size, 0, "the confirming payload (g2 working) retired the prediction while hidden");
});

test("the follow-move backstop that fires after a confirming payload was applied hidden does not revert", () => {
  const f = feedHarness();
  f.applyFeedPayload({ asks: [{ itemId: "g2", column: "needsInput" }] });
  f.st.pendingFollowMove.set("g2", true);
  f.st.hidden = true;
  f.applyFeedPayload({ asks: [{ itemId: "g2", column: "working" }] });   // the kernel confirms while the tab is hidden
  assert.equal(f.backstop("g2"), "kept", "MOVE_ACK_MS elapses: the prediction is already confirmed, nothing to revert");
  assert.equal(f.st.paints, 1, "and the backstop's render() is held like any other");
});

test("release → exactly one synchronous paint, the flip decision skipped, prevCols = the painted columns", () => {
  const f = feedHarness();
  f.applyFeedPayload({ asks: [{ itemId: "g1", column: "asks" }, { itemId: "g2", column: "needsInput" }] });
  f.st.hidden = true;
  f.applyFeedPayload({ asks: [{ itemId: "g2", column: "completed" }, { itemId: "g1", column: "working" }] });   // both moved while away
  f.applyFeedPayload({ asks: [{ itemId: "g2", column: "completed" }, { itemId: "g1", column: "working" }, { itemId: "g3", column: "asks" }] });
  const checksBefore = f.st.flipChecks;
  f.st.hidden = false; f.releasePaint();           // visibilitychange → visible
  assert.equal(f.st.paints, 2, "one paint for the whole hidden stretch");
  assert.equal(f.st.lastNeedFlip, false, "cards snap into place");
  assert.equal(f.st.flipChecks, checksBefore, "flipNeeded was not even consulted");
  assert.deepEqual(f.st.prevCols, f.columnsOf(f.st.asks), "the flip baseline is what was painted");
  assert.equal(f.st.paintDirty, false);
  f.releasePaint();                                // a second release event (the observer's callback) owes nothing
  assert.equal(f.st.paints, 2);
  // the NEXT move, seen live, glides again: the skip was one-shot
  f.applyFeedPayload({ asks: [{ itemId: "g1", column: "working" }, { itemId: "g2", column: "completed" }, { itemId: "g3", column: "completed" }] });
  assert.equal(f.st.paints, 3);
  assert.equal(f.st.lastNeedFlip, true);
});

test("a display:none pane holds too, and the tab's return alone does not release it — the observer does", () => {
  const f = feedHarness();
  f.applyFeedPayload({ asks: [{ itemId: "g1", column: "asks" }] });
  f.st.intersecting = false; f.st.hidden = true;
  f.applyFeedPayload({ asks: [{ itemId: "g1", column: "working" }] });
  f.st.hidden = false; f.releasePaint();
  assert.equal(f.st.paints, 1, "tab back, pane still display:none");
  f.st.intersecting = true; f.releasePaint();
  assert.equal(f.st.paints, 2);
});

// ── source pins: feed.ts wires exactly the lines the harness ran ──
const SRC = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "feed.ts"), "utf8");
const body = (name: string) => new RegExp("^function " + name + "\\([\\s\\S]*?\\n\\}", "m").exec(SRC)![0];

test("render() is gated first, on the shared pure decision, and nothing else in feed.ts is", () => {
  assert.match(SRC, /import \{ paintHeld, paintReleased \} from "\.\/paint-gate";/);
  assert.match(SRC, /function render\(\) \{\n  const list = document\.getElementById\("feed-list"\)!;\n  if \(!feedWatching\) \{ feedWatching = true; watchFeedVisibility\(list\); \}\n  if \(paintHeld\(document\.hidden, feedIntersecting, list\.childElementCount > 0\)\) \{ paintDirty = true; return; \}\n  pruneTip\(\);/,
    "the gate precedes every paint-side step (pruneTip, applyFollowMove, the footer, the columns)");
  assert.equal(SRC.split("paintHeld(").length - 1, 1, "one gate, in render(): no other path is withheld");
  assert.match(SRC, /let feedIntersecting = true;/, "visible until the observer says otherwise: no observer → the tab alone gates");
});

test("the flip is skipped exactly once after a release, and prevCols still records what was painted", () => {
  assert.match(SRC, /const needFlip = !skipFlipOnce && flipNeeded\(prevCols, nextCols\);\n\s*skipFlipOnce = false;\n\s*prevCols = nextCols;/);
  assert.match(SRC, /askEls\.clear\(\); groupEls\.clear\(\);\n\s*skipFlipOnce = false;/, "the empty-board paint spends the snap too");
  const rel = body("releasePaint");
  assert.match(rel, /if \(!paintReleased\(paintDirty, document\.hidden, feedIntersecting\)\) return;\n\s*paintDirty = false;\n\s*skipFlipOnce = true;\n\s*render\(\);/);
  assert.doesNotMatch(rel, /requestAnimationFrame|setTimeout|queueMicrotask/, "the release paints synchronously: the earliest fresh frame after the compositor's cached one");
});

test("BOTH release events run the same release: visibilitychange→visible and the observer's callback", () => {
  assert.match(SRC, /document\.addEventListener\("visibilitychange", \(\) => \{ if \(!document\.hidden\) releasePaint\(\); \}\);/);
  const watch = body("watchFeedVisibility");
  assert.match(watch, /new IntersectionObserver\(\(entries\) => \{\n\s*feedIntersecting = entries\.some\(\(e\) => e\.isIntersecting\);\n\s*releasePaint\(\);\n\s*\}\)\.observe\(list\);/);
  assert.match(watch, /if \(typeof IntersectionObserver === "undefined"\) return;/);
});

test("state is applied whatever the visibility: the payload path and its bookkeeping never look at the gate", () => {
  const apply = body("applyFeedPayload");
  assert.doesNotMatch(apply, /document\.hidden|paintDirty|feedIntersecting|paintHeld/);
  for (const must of ["reconcileFollowMove(", "mirrorBadges(", "clearUndoBusy();", "pendingCleared", "pendingRestored", "reconcilePendingDone("]) {
    assert.ok(apply.includes(must), "applyFeedPayload still runs " + must);
  }
  assert.equal((apply.match(/\brender\(\);/g) || []).length, 1, "ONE gated render");
  assert.match(apply, /\n  render\(\);\n  if \(!feedAnnounced\) \{/, "…followed only by the shell's first-content announcement");
  // the message handler applies live unless a card is hovered/keyed — the hover-freeze holder is not
  // widened into a hidden holder (it withholds the payload itself, which the backstop test above forbids)
  assert.match(SRC, /if \(m\.type === "feed"\) \{[\s\S]*?if \(freezeKey \|\| tabScopeKey\) \{ pendingFeedPayload = m; paintFreezeBadges\(\); return; \}\n\s*applyFeedPayload\(m\);/);
  assert.doesNotMatch(SRC, /freezeKey \|\| tabScopeKey \|\| document\.hidden|document\.hidden \|\| freezeKey/);
});

test("the follow-move backstop yields to a prediction a payload already retired; the payload retires it on `working`", () => {
  const ack = body("ackFollowMove");
  const guard = ack.indexOf('if (!pendingFollowMove.has(itemId)) return;\n    clearFollowMove(itemId, "backstop-noconfirm"); render();');
  assert.ok(guard > 0, "the backstop checks the prediction still stands before it reverts");
  assert.match(body("reconcileFollowMove"), /if \(!a \|\| a\.column === "working" \|\| pendingMoveKind\.get\(id\) === "answer"\) \{\n\s*clearFollowMove\(/);
});

test("a bell jump settles the owed paint on the shell's word before it looks for the card", () => {
  // the shell shows the pane and posts revealCard in the same task, before the observer re-measures
  assert.match(SRC, /if \(m\.romp === "revealCard"\) \{[\s\S]*?if \(paintDirty\) \{ feedIntersecting = true; releasePaint\(\); \}\n\s*const key = "a:" \+ String\(m\.itemId \|\| ""\);/);
});
