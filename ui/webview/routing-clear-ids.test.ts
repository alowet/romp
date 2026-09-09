// A remote route strips only its own host's prefix (T287, the user 2026-09-09): the session header's Clear all
// reached the owning kernel with every item id cut at its first colon ("sid:g448" → "g448"), so the owner recorded a
// node id with no session, cleared nothing, and the cards came back with the next payload and every restart. The
// same first-colon reading kept the viewer's-ledger overlay from ever matching a remote row.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import { routeOutbound, stripHost, mergeHostFeeds } from "./federation";

const SID = "11111111-2222-3333-4444-555555555555";

test("stripHost removes exactly the route's own host prefix and nothing else", () => {
  assert.equal(stripHost("box2", "box2:" + SID), SID);
  assert.equal(stripHost("box2", "box2:" + SID + ":g1"), SID + ":g1");
  assert.equal(stripHost("box2", SID + ":g448"), SID + ":g448", "an unprefixed card id keeps its session");
  assert.equal(stripHost("box2", "box3:" + SID), "box3:" + SID, "another host's prefix is not ours to strip");
  assert.equal(stripHost("", SID + ":g1"), SID + ":g1");
});

test("a session header's Clear all routed to a remote kernel keeps every item id whole", () => {
  const r = routeOutbound({ type: "askClearMany", sid: "box2:" + SID, itemIds: [SID + ":g448", SID + ":g449", "box2:" + SID + ":g450"] });
  assert.equal(r.length, 1);
  assert.equal(r[0].host, "box2");
  assert.equal(r[0].msg.sid, SID, "the sid loses its host prefix");
  assert.deepEqual(r[0].msg.itemIds, [SID + ":g448", SID + ":g449", SID + ":g450"],
    "the owner receives session-qualified card ids, whether or not one arrived prefixed");
  const single = routeOutbound({ type: "askClear", sid: "box2:" + SID, itemId: SID + ":g5" });
  assert.deepEqual([single[0].host, single[0].msg.sid, single[0].msg.itemId], ["box2", SID, SID + ":g5"]);
  const local = routeOutbound({ type: "askClearMany", sid: SID, itemIds: [SID + ":g1"] });
  assert.deepEqual([local[0].host, local[0].msg.itemIds], ["", [SID + ":g1"]], "a local route touches nothing");
});

test("the viewer's-ledger overlay matches a remote row by its prefixed sid and its unprefixed item id", () => {
  const A = "box2:" + SID;
  const remote = { type: "feed", now: 1, asks: [{ itemId: SID + ":g1", sid: A }, { itemId: SID + ":g2", sid: A }], items: [],
                   ledgers: [{ sid: A, name: "box2:api", ledger: { tree: [], archivedTops: [
                     { id: SID + ":g1", depth: 0, cleared: false, done: true }, { id: SID + ":g1a", depth: 1, cleared: false, done: true },
                     { id: SID + ":g3", depth: 0, cleared: false, done: true }] } }] };
  const local = { type: "feed", now: 7, asks: [{ itemId: SID + ":g1", sid: SID }], ledgers: [], clearedForeign: [SID + ":g1"] };
  const merged = mergeHostFeeds({ "": local, box2: remote }, ["", "box2"]);
  assert.deepEqual(merged.asks.map((a: any) => [a.sid, a.itemId.split(":").pop()]), [[SID, "g1"], [A, "g2"]],
    "the remote g1 is dropped, the local twin stays");
  const tops = merged.ledgers.find((l: any) => l.sid === A).ledger.archivedTops;
  assert.deepEqual(tops.map((n: any) => [n.id.split(":").pop(), n.cleared]), [["g1", true], ["g1a", true], ["g3", false]]);
});
