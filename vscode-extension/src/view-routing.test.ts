// The reveal table: which webview→host messages reveal a sibling surface, and
// which are handled locally instead of forwarded. Pins the pre-existing feed
// behavior (openSession focuses chat, locates preserve focus) and the new
// timeline/fleet routes.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import { routeViewMessage } from "./view-routing";

test("feed: openSession focuses the chat panel", () => {
  const r = routeViewMessage("feed", { type: "openSession", id: "s1" });
  assert.deepEqual(r.revealChat, { preserveFocus: false });
  assert.equal(r.forward, true);
});

test("feed: locate-style clicks reveal chat without stealing focus", () => {
  assert.deepEqual(routeViewMessage("feed", { type: "showOnTimeline", itemId: "n1" }).revealChat,
    { preserveFocus: true });
  assert.deepEqual(routeViewMessage("feed", { type: "showAskPath", itemId: "n1" }).revealChat,
    { preserveFocus: true });
});

test("feed: showAskPath variants that must NOT reveal (off / jump / locate:false)", () => {
  for (const m of [
    { type: "showAskPath", off: true },
    { type: "showAskPath", jump: true },
    { type: "showAskPath", locate: false },
  ]) {
    const r = routeViewMessage("feed", m);
    assert.equal(r.revealChat, null, JSON.stringify(m));
    assert.equal(r.forward, true);
  }
});

test("fleet routes like feed (openSession focuses, showOnTimeline preserves)", () => {
  assert.deepEqual(routeViewMessage("fleet", { type: "openSession", id: "s1" }).revealChat,
    { preserveFocus: false });
  assert.deepEqual(routeViewMessage("fleet", { type: "showOnTimeline", itemId: "n1" }).revealChat,
    { preserveFocus: true });
});

test("timeline: a lane deep link reveals chat (preserving focus) and still reaches the kernel", () => {
  const r = routeViewMessage("timeline", { type: "deepLink", session: "s1" });
  assert.deepEqual(r.revealChat, { preserveFocus: true });
  assert.equal(r.forward, true);
});

test("timeline: openLink is handled locally by the host, never forwarded", () => {
  const r = routeViewMessage("timeline", { type: "openLink", href: "https://example.com" });
  assert.equal(r.openLinkLocally, "https://example.com");
  assert.equal(r.forward, false);
  assert.equal(r.revealChat, null);
});

test("feed and outline panes: a PR link's openLink is handled locally by the host too, never forwarded", () => {
  // pr-links.ts posts {type:"openLink"} from a feed card or an outline row in VS Code; the kernel has
  // no handler for it, so a forwarded one would be a dead click
  for (const app of ["feed", "fleet"] as const) {
    const r = routeViewMessage(app, { type: "openLink", href: "https://github.com/example-org/notes-api/pull/12" });
    assert.equal(r.openLinkLocally, "https://github.com/example-org/notes-api/pull/12", app);
    assert.equal(r.forward, false, app);
    assert.equal(r.revealChat, null, app);
  }
});

test("timeline: drive ops (compact etc.) just forward", () => {
  const r = routeViewMessage("timeline", { type: "compact", name: "sess" });
  assert.equal(r.revealChat, null);
  assert.equal(r.forward, true);
});

test("chat: the ledger dot opens the feed beside it without stealing focus", () => {
  const r = routeViewMessage("chat", { type: "dotOpen" });
  assert.deepEqual(r.revealFeed, { preserveFocus: true });
  assert.equal(r.forward, true);
});

test("chat: ordinary ops route nowhere", () => {
  const r = routeViewMessage("chat", { type: "sendMessage", text: "hi" });
  assert.equal(r.revealChat, null);
  assert.equal(r.revealFeed, null);
  assert.equal(r.forward, true);
});

test("malformed messages are dropped, not forwarded", () => {
  assert.equal(routeViewMessage("feed", null).forward, false);
  assert.equal(routeViewMessage("timeline", { no: "type" }).forward, false);
});

test("timeline: usageData is host chrome (status bar), never forwarded to the kernel", () => {
  const r = routeViewMessage("timeline", { type: "usageData", usage: { fiveHour: { pct: 50 } } });
  assert.equal(r.forward, false);
  assert.equal(r.revealChat, null);
});
