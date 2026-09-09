// The board-wide Clear all reaches every attached kernel (T286, the user 2026-09-09): the feed footer's Clear all
// carries no session id and used to fall through to the local kernel alone, so a merged board's Clear all left every
// remote card standing. The router broadcasts it, local first; each kernel clears its own feed's cards and appends its
// own ledger rows; Undo follows the last clear to every kernel it reached. The session header's Clear all
// (askClearMany, routed by its session id) is unchanged. A kernel whose socket is down at the click misses it (the
// message is deliberately not a queued kernel setting) and its cards stay.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { routeOutbound, FederationManager } from "./federation";

const FED = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "federation.ts"), "utf8");
const SID = "11111111-2222-3333-4444-555555555555";

function withManager(fn: (fm: FederationManager, localSent: any[], remoteSent: [string, any][]) => void): void {
  const localSent: any[] = [], remoteSent: [string, any][] = [];
  const g: any = globalThis;
  const hadWindow = "window" in g, prevWindow = g.window;
  const hadLS = "localStorage" in g, prevLS = g.localStorage;
  g.window = { dispatchEvent: () => {}, __rompLocalSend: (m: any) => localSent.push(m) };
  g.localStorage = { getItem: () => null, setItem: () => {} };
  try {
    const fm = new FederationManager();
    (fm as any).sendRemote = (h: string, m: any) => remoteSent.push([h, m]);
    (fm as any).hostSeq = ["", "box2", "box3"];       // a board with two attached kernels' cards on it
    fn(fm, localSent, remoteSent);
  } finally {
    if (hadWindow) g.window = prevWindow; else delete g.window;
    if (hadLS) g.localStorage = prevLS; else delete g.localStorage;
  }
}

test("the router broadcasts the board-wide Clear all to every attached kernel, local first, the message untouched", () => {
  const r = routeOutbound({ type: "clearAll" }, new Set(["box2", "box3"]));
  assert.deepEqual(r.map((x) => x.host), ["", "box2", "box3"]);
  assert.ok(r.every((x) => x.msg.type === "clearAll" && Object.keys(x.msg).length === 1));
  assert.deepEqual(routeOutbound({ type: "clearAll" }).map((x) => x.host), [""], "a single-kernel board: the local kernel alone, as before");
});

test("a Clear all on a merged board reaches both kernels and Undo restores both sides", () => {
  withManager((fm, localSent, remoteSent) => {
    fm.outbound({ type: "clearAll" });
    assert.deepEqual(localSent.map((m) => m.type), ["clearAll"], "the local kernel does its part first");
    assert.deepEqual(remoteSent.map(([h, m]) => [h, m.type]), [["box2", "clearAll"], ["box3", "clearAll"]]);
    fm.outbound({ type: "undoClear" });
    assert.deepEqual(localSent.map((m) => m.type), ["clearAll", "undoClear"]);
    assert.deepEqual(remoteSent.map(([h, m]) => [h, m.type]),
      [["box2", "clearAll"], ["box3", "clearAll"], ["box2", "undoClear"], ["box3", "undoClear"]], "each kernel undoes its own batch");
    fm.outbound({ type: "undoClear" });
    assert.equal(remoteSent.length, 4, "a second Undo has no clear to follow to a remote kernel: local alone");
    assert.deepEqual(localSent.map((m) => m.type), ["clearAll", "undoClear", "undoClear"]);
  });
});

test("the session header's Clear all still goes to that session's kernel alone, and Undo follows it there alone", () => {
  withManager((fm, localSent, remoteSent) => {
    fm.outbound({ type: "askClearMany", sid: "box2:" + SID, itemIds: ["box2:" + SID + ":g1", "box2:" + SID + ":g2"] });
    assert.equal(localSent.length, 0);
    assert.deepEqual(remoteSent.map(([h, m]) => [h, m.type, m.sid]), [["box2", "askClearMany", SID]], "routed by id, bare");
    fm.outbound({ type: "undoClear" });
    assert.equal(localSent.length, 0, "the local kernel took no clear: nothing to undo there");
    assert.deepEqual(remoteSent.map(([h, m]) => [h, m.type]), [["box2", "askClearMany"], ["box2", "undoClear"]]);
    fm.outbound({ type: "askClear", sid: SID, itemId: SID + ":g5" });   // the feed's shape: routed by the session id
    fm.outbound({ type: "undoClear" });
    assert.deepEqual(localSent.map((m) => m.type), ["askClear", "undoClear"], "a local clear's Undo stays local");
    assert.equal(remoteSent.length, 2);
  });
});

test("Clear all is not a queued kernel setting: a kernel that is down at the click misses it and its cards stay", () => {
  assert.doesNotMatch(FED.slice(FED.indexOf("const KERNEL_SETTING"), FED.indexOf("]);", FED.indexOf("const KERNEL_SETTING"))), /clearAll/);
  assert.match(FED, /if \(msg\.type === "clearAll"\) return \[LOCAL, \.\.\.\(knownHosts \|\| \[\]\)\]\.map\(\(h\) => \(\{ host: h, msg \}\)\);/);
  assert.match(FED, /this\.diag\("senddrop", \{ host, msgType: \(msg && msg\.type\) \|\| "" \}\);\s*\n\s*this\.dropWarn\(host, msg\);/, "a non-setting on a down socket is dropped and warned, never queued");
});
