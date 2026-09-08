// The "worked …" footer's rule and the tail path's footer plan (worked-footer.ts). The chat's tail
// path re-renders exactly the events the kernel names as changed, so the one render that depends on later
// events — the footer on a turn's last reply — is patched from this plan. Synthetic events; epochs are seconds.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import { turnWorkedSecs, workedFooterPlan } from "./worked-footer";

type Ev = { kind: string; human?: boolean; t?: number };
const epoch = (e: Ev) => (e.t == null ? null : e.t);
const user = (t: number, human = true): Ev => ({ kind: "user", human, t });
const reply = (t: number): Ev => ({ kind: "assistant", t });
const tool = (t: number): Ev => ({ kind: "tool", t });

test("turnWorkedSecs: the turn's last reply carries the footer once a genuine prompt follows or the session is idle", () => {
  const evs = [user(100), tool(110), reply(160), user(200), reply(230)];
  assert.equal(turnWorkedSecs(evs, 2, true, epoch), 60, "a completed turn's last reply: prompt to reply");
  assert.equal(turnWorkedSecs(evs, 1, true, epoch), null, "not the turn's last reply");
  assert.equal(turnWorkedSecs(evs, 4, true, epoch), null, "the final turn while working: the spinner owns it");
  assert.equal(turnWorkedSecs(evs, 4, false, epoch), 30, "…and idle: the footer");
  assert.equal(turnWorkedSecs(evs, 0, false, epoch), null, "a prompt carries none");
  assert.equal(turnWorkedSecs([user(100), reply(100)], 1, false, epoch), null, "a zero elapsed carries no footer");
  assert.equal(turnWorkedSecs([user(100), reply(90)], 1, false, epoch), null, "…nor a negative one (a clock skew between the two stamps)");
});

test("turnWorkedSecs: the elapsed runs from the immediate trigger, and an injected user line does not end a turn", () => {
  const evs = [user(100), reply(140), user(1000, false), reply(1030), user(2000)];
  assert.equal(turnWorkedSecs(evs, 1, false, epoch), null, "a nudge followed the reply: the same turn continues, so this reply is not its last");
  assert.equal(turnWorkedSecs(evs, 3, false, epoch), 30, "measured from the nudge that prompted the work, not the older prompt");
});

test("plan: a status-only tail (from = len) names the current turn's last reply; idle puts the footer on, working takes it off", () => {
  const evs = [user(100), tool(110), reply(160), user(200), tool(205), reply(230)];
  assert.deepEqual(workedFooterPlan(evs, evs.length, 0, false, epoch), [{ unit: 5, secs: 30 }]);
  assert.deepEqual(workedFooterPlan(evs, evs.length, 0, true, epoch), [{ unit: 5, secs: null }],
    "back at work on the same turn: the current reply's footer comes off (null); the completed turn at 2 is not named, nothing about it changed");
});

test("plan: a prompt landing at the tail completes the previous turn, whose reply sits before `from`", () => {
  const evs = [user(100), reply(160), user(200)];
  assert.deepEqual(workedFooterPlan(evs, 2, 0, true, epoch), [{ unit: 1, secs: 60 }]);
});

test("plan (case B, completed): two prompts in one tail still name the reply the first of them completed", () => {
  // the old two-prompt walk spent its budget on the two new prompts and never reached the reply
  const evs = [user(100), reply(160), user(200), user(210)];
  assert.deepEqual(workedFooterPlan(evs, 2, 0, true, epoch), [{ unit: 1, secs: 60 }]);
  const evs2 = [user(100), reply(160), user(200), reply(230), user(300)];
  assert.deepEqual(workedFooterPlan(evs2, 2, 0, true, epoch), [{ unit: 1, secs: 60 }], "…however many turns the suffix carries");
});

test("plan (case A, demoted): a reply landing in the same turn takes the footer off the reply it follows", () => {
  // idle after the reply at 1: it wore the footer; the tail appends a tool call, so it is no longer its turn's last
  const evs = [user(100), reply(160), tool(170)];
  assert.deepEqual(workedFooterPlan(evs, 2, 0, true, epoch), [{ unit: 1, secs: null }]);
  // the same through an injected user line (a postal push) that sat before the tail: the turn continued
  const evs2 = [user(100), reply(160), user(1000, false), reply(1030)];
  assert.deepEqual(workedFooterPlan(evs2, 3, 0, true, epoch), [{ unit: 1, secs: null }], "the injected line is skipped: the reply at 1 is named, and it carries no footer now");
  assert.deepEqual(workedFooterPlan(evs2, 3, 0, false, epoch), [{ unit: 1, secs: null }], "idle or not: a later reply in the turn owns the footer");
});

test("plan: replies at or past `from` were just rendered with their footer, so only the one before is named", () => {
  const evs = [user(100), reply(160), user(200), tool(205), reply(230)];
  assert.deepEqual(workedFooterPlan(evs, 3, 0, false, epoch), [{ unit: 1, secs: 60 }], "a tool fill at 3 re-rendered 3..4: the turn's reply at 4 is fresh; only the previous turn's reply is patched");
  assert.deepEqual(workedFooterPlan(evs, 1, 0, false, epoch), [], "everything from 1 was rendered: nothing to patch");
  assert.deepEqual(workedFooterPlan(evs, 0, 0, false, epoch), [], "a rebuild from 0: nothing before it");
});

test("plan: exactly one reply is named, and none below the rendered window's start", () => {
  const evs = [user(0), reply(10), user(20), reply(30), user(40), reply(50), user(60), tool(65), reply(70)];
  assert.deepEqual(workedFooterPlan(evs, evs.length, 0, false, epoch), [{ unit: 8, secs: 10 }], "the earlier turns' replies are complete already; the tool at 7 is not its turn's last reply");
  assert.deepEqual(workedFooterPlan(evs, evs.length, 6, false, epoch), [{ unit: 8, secs: 10 }]);
  assert.deepEqual(workedFooterPlan(evs, evs.length, 9, false, epoch), [], "the reply is outside the rendered window");
  assert.deepEqual(workedFooterPlan([user(0), reply(10), user(20)], 2, 2, true, epoch), [], "…and so is the one a landing prompt completed");
});
