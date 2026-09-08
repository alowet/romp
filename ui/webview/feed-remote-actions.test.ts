// Feed card actions must carry the card's sid so the federation manager can route them to the OWNING
// kernel (the user 2026-07-02: clearing a remote session's card silently no-op'd on the local kernel and
// the card resurrected on every reload). Source-pin over feed.ts, like picker-host.test.ts.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const FEED = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "feed.ts"), "utf8");

test("every askClear send carries the card's sid (routes a remote clear to its kernel)", () => {
  // single-card clears post askClear; the group card, the modal's group clear and the session header post
  // ONE askClearMany for the batch (2026-09-08) — every one of them carries the session id
  const sends = FEED.match(/type: "askClear(?:Many)?"[^}]*/g) || [];
  assert.ok(sends.length >= 5, `found ${sends.length} clear sends — expected the 5 known sites`);
  for (const s of sends) assert.match(s, /,\s*sid(: (it|m|mem|cur|grp)\.sid)?\s*$/, `clear send missing sid: ${s}`);   // explicit or shorthand property
});

test("every showAskPath send carries a sid (a remote card's hover highlight routes to its kernel)", () => {
  // The cross-surface hover glow (the user 2026-08-03): showAskPath carried only the itemId, which
  // federation cannot route on (it is bare on both sides), so a remote card's hover landed on the
  // local kernel and the timeline/chat highlight never lit. Every send now names the owning sid —
  // from the item in scope where one is at hand, else resolved by sidOfItem (the pin-restore and
  // keyboard paths hold only an itemId).
  const sends = FEED.match(/type: "showAskPath"[^}]*/g) || [];
  assert.ok(sends.length >= 16, `found ${sends.length} showAskPath sends — expected the 16 known sites`);
  for (const s of sends) assert.match(s, /sid: (it\.sid|m\.sid|sidOfItem\()/, `showAskPath send missing sid: ${s}`);
});

test("askFollowUp carries sid too (remote follow-ups); the expand/detail channel died with FeedItem", () => {
  assert.doesNotMatch(FEED, /type: "expand"/);
  assert.match(FEED, /type: "askFollowUp"[^}]*sid: fbSid/);
  // both modal call sites hand postFollowUp the card's sid
  assert.match(FEED, /postFollowUp\(txt, grp\.members\[0\]\.itemId, grp\.members\[0\]\.sid, grp\.title\)/);
  assert.match(FEED, /postFollowUp\(txt, it\.itemId, it\.sid\)/);
});
