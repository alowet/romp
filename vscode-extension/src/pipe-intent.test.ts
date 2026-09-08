// intentOp gates what survives a KernelPipe reconnect: user intent (typed text,
// explicit picks) delivers after the socket returns; view chatter drops, because
// the reconnect reloads the webview and resyncs it fresh (the user 2026-07-21).
import { test } from "node:test";
import * as assert from "node:assert/strict";
import { INTENT_OPS, intentOp } from "./pipe-intent";

test("typed-text ops are intent — losing them loses the user's words", () => {
  for (const t of ["sendMessage", "askFollowUp", "askText", "addCustomAsk", "sendCommand", "rewindSend"]) {
    assert.ok(intentOp(t), `${t} must survive a reconnect`);
  }
});

test("explicit state-changing picks are intent", () => {
  // setTimelineViews and tagEdit are the two views writes (a lens/order blob; a targeted tag edit,
  // 2026-09-05) — a tag renamed during a reconnect window must still land
  for (const t of ["setModel", "setEffort", "setMode", "setFast", "interrupt", "endSession",
    "nodeOverride", "askClear", "answerAsk", "submitAsk", "renameSession", "moveSession",
    "setTimelineViews", "tagEdit", "editTag"]) {
    assert.ok(intentOp(t), `${t} must survive a reconnect`);
  }
});

test("a remote-tag edit is intent — its local half is already on screen when it is posted", () => {
  // editTag is the federation op for a tag whose home is another kernel (render.ts's union add/remove,
  // the timeline's __rompTimelineEditTag hook, 2026-08-24): the pane mirrors the edit locally right
  // beside the post, so a post dropped on reconnect leaves a half-applied edit the user believes landed
  assert.ok(intentOp("editTag"), "a queued editTag must be kept across the extension's reconnect");
});

test("view chatter is not intent — the reconnect reload resyncs it", () => {
  for (const t of ["ready", "openSession", "showAskPath", "showOnTimeline", "dotHover",
    "hoverHighlight", "loadOlder", "requestSessions", "openByName", "dotOpen", "imgRequest"]) {
    assert.ok(!intentOp(t), `${t} is view state, not user intent`);
  }
});

test("non-strings never classify as intent", () => {
  assert.ok(!intentOp(undefined));
  assert.ok(!intentOp(null));
  assert.ok(!intentOp(42));
  assert.ok(!INTENT_OPS.has(""));
});
