// The viewer's ledger over remote rows (review find, 2026-09-09): a remote kernel's feed and archive projection read
// only their own cleared.jsonl, so an id the LOCAL ledger clears for a remote card (clearedForeign on the local
// payload, bare) must drop that remote ask/item and read that remote archived top cleared, subtree with it, while
// local rows and untouched remote rows pass through exactly as before. Same harness as feed-clock-anchor.test.ts.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import { mergeHostFeeds, applyViewerClears } from "./federation";

const SID = "11111111-2222-3333-4444-555555555555";
const A = "HOSTA:" + SID;

function remoteFeed() {
  return {
    type: "feed", now: 100,
    asks: [{ itemId: SID + ":g1", sid: A }, { itemId: SID + ":g2", sid: A }],
    items: [{ itemId: SID + ":g9", sid: A }],
    ledgers: [{ sid: A, name: "HOSTA:api", ledger: { tree: [], archivedTops: [
      { id: SID + ":g1", depth: 0, cleared: false, done: true },
      { id: SID + ":g1a", depth: 1, cleared: false, done: true },
      { id: SID + ":g3", depth: 0, cleared: false, done: true },
      { id: SID + ":g3a", depth: 1, cleared: false, done: true },
    ] } }],
  };
}

test("a foreign clear on the local payload drops the remote ask and reads the remote archived top cleared, subtree with it", () => {
  const local = { type: "feed", now: 7, asks: [{ itemId: SID + ":g1", sid: SID }], ledgers: [], clearedForeign: [SID + ":g1", SID + ":g9"] };
  const remote = remoteFeed();
  const merged = mergeHostFeeds({ "": local, HOSTA: remote }, ["", "HOSTA"]);
  assert.deepEqual(merged.asks.map((a: any) => [a.sid, a.itemId]), [[SID, SID + ":g1"], [A, SID + ":g2"]], "the remote g1 ask is gone; the LOCAL g1 stays (the local kernel already applied its ledger)");
  assert.deepEqual(merged.items.map((c: any) => c.itemId), [], "the remote item is gone");
  const tops = merged.ledgers.find((l: any) => l.sid === A).ledger.archivedTops;
  assert.deepEqual(tops.map((n: any) => [n.id.split(":").pop(), n.cleared]),
    [["g1", true], ["g1a", true], ["g3", false], ["g3a", false]], "g1 and its child read cleared; g3 untouched");
  assert.equal(remote.ledgers[0].ledger.archivedTops[0].cleared, false, "the host payload's own rows are not mutated");
  assert.equal(remote.asks.length, 2);
});

test("without foreign ids nothing changes, and a remote host with none named passes through", () => {
  const remote = remoteFeed();
  const merged = mergeHostFeeds({ "": { type: "feed", now: 7, asks: [], ledgers: [] }, HOSTA: remote }, ["", "HOSTA"]);
  assert.equal(merged.asks.length, 2);
  assert.deepEqual(merged.ledgers[0].ledger.archivedTops.map((n: any) => n.cleared), [false, false, false, false]);
  const other = { type: "feed", now: 7, asks: [], ledgers: [], clearedForeign: [SID + ":zz"] };
  const merged2 = mergeHostFeeds({ "": other, HOSTA: remoteFeed() }, ["", "HOSTA"]);
  assert.equal(merged2.asks.length, 2, "an id that names nothing drops nothing");
});

test("the overlay is pure over the rows it is given and ignores junk ids", () => {
  const merged: any = { asks: [{ itemId: SID + ":g1", sid: A }], items: [] };
  const ledgers = [{ sid: A, ledger: { tree: [], archivedTops: [{ id: SID + ":g1", depth: 0, cleared: false }] } }];
  applyViewerClears(merged, ledgers, [SID + ":g1", 42, null]);
  assert.equal(merged.asks.length, 0);
  assert.equal(ledgers[0].ledger.archivedTops[0].cleared, true);
  applyViewerClears(merged, ledgers, undefined);   // no ids: a no-op
});
