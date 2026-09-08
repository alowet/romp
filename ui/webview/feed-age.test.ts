// The live clock a pane runs its ages on (feed-age.ts liveNow: the kernel's `now` on the last frame plus the
// local time elapsed since that frame ARRIVED) and the feed's age refresh, RUN: a quiet board sends a pane
// nothing between frames, so the pane keeps the clock moving itself and one 15 s pass repaints every stamped
// age — and, since the per-card update gate repaints a card only when its inputs change, every running
// duration too. Pure functions here (node --test runs them without a DOM), plus source pins on feed.ts's
// wiring; feed-render-incremental.test.ts runs the pass itself under a DOM stand-in. Synthetic only.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { liveNow, liveRefresher, paintAge, refreshAges, stampAge, type AgeEl } from "./feed-age";
import { ageColorReadable } from "./age-color";

const FEED = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "feed.ts"), "utf8");
// feed.ts's relAge, in shape (feed-relage.test.ts pins the real one); the refresh takes it as a parameter
const rel = (s: number) => s < 60 ? "<1m ago" : s < 3600 ? Math.round(s / 60) + "m ago" : s < 86400 ? Math.round(s / 3600) + "h ago" : Math.round(s / 86400) + "d ago";
const tint = ageColorReadable;
const mk = (): AgeEl => ({ textContent: null, style: { color: "" }, dataset: {} });

test("liveNow adds only the local clock's DELTAS to the kernel's clock — skew between the two never enters", () => {
  const hostNow = 1_000_000;                    // the kernel's clock, as of the frame (epoch s)
  const arrivedMs = 9_000_000_000;              // the browser's clock when the frame landed — hours off the kernel's; irrelevant
  assert.equal(liveNow(hostNow, arrivedMs, arrivedMs), hostNow, "at the arrival the kernel clock IS the frame's `now`");
  assert.equal(liveNow(hostNow, arrivedMs, arrivedMs + 15_000), hostNow + 15, "15 s later, 15 s older");
  assert.equal(liveNow(hostNow, arrivedMs, arrivedMs + 999), hostNow, "whole seconds only: ages never read ahead of the tick");
  assert.equal(liveNow(hostNow, arrivedMs, arrivedMs + 15_500), hostNow + 15, "15.5 s later: +15, the fraction dropped");
  assert.equal(liveNow(hostNow, arrivedMs, arrivedMs - 5_000), hostNow, "a local clock that steps BACK cannot make an age negative");
});

test("a quiet board's ages advance: every stamped element repaints from the live clock, tinted ones re-tint", () => {
  const T = 1_000_000, t = T - 240;                         // everything 4 minutes old at the payload
  const cardTime = mk(), groupTime = mk(), parenRow = mk(), tintedAge = mk();
  stampAge(cardTime, t, "plain", false, T, rel, tint);      // an ask card's stamp
  stampAge(groupTime, t, "plain", false, T, rel, tint);     // a group card's stamp
  stampAge(parenRow, t, "paren", true, T, rel, tint);       // a parenthesized, recency-tinted "(4m ago)"
  stampAge(tintedAge, t, "plain", true, T, rel, tint);      // a tinted "4m ago"
  assert.equal(cardTime.textContent, "4m ago"); assert.equal(groupTime.textContent, "4m ago");
  assert.equal(parenRow.textContent, "(4m ago)"); assert.equal(tintedAge.textContent, "4m ago");
  assert.equal(cardTime.style.color, "", "card stamps keep their own colour");
  assert.equal(parenRow.style.color, tint(240));
  // an hour passes with no payload: the 15 s tick's pass, from the live clock
  const n = refreshAges([cardTime, groupTime, parenRow, tintedAge], T + 3600, rel, tint);
  assert.equal(n, 4, "every stamped element is repainted (every label changed)");
  assert.equal(cardTime.textContent, "1h ago"); assert.equal(groupTime.textContent, "1h ago");
  assert.equal(parenRow.textContent, "(1h ago)"); assert.equal(tintedAge.textContent, "1h ago");
  assert.equal(parenRow.style.color, tint(3840)); assert.notEqual(parenRow.style.color, tint(240), "the tint aged");
  assert.equal(tintedAge.style.color, tint(3840));
  assert.equal(cardTime.style.color, "", "…and an untinted stamp stays untinted");
});

test("the anchor is a (now, nowAt) pair that travels with the frame: a re-emit after a quiet hour reads the same live clock as the arrival", () => {
  // federation re-emits the merged frame on a view-order write, on every remote host's frame and on a detach,
  // and the pane sets its clock from whatever frame it is handed. The pair pins the anchor to the WIRE arrival:
  // the same stored frame, re-emitted an hour later, anchors identically. Anchored on the emit instead, every
  // age would go back by the quiet period.
  const T = 1_000_000, arrivedMs = 5_000_000, hourLater = arrivedMs + 3_600_000;
  const anchor = (m: { now: number; nowAt?: number }, handledMs: number) =>
    liveNow(m.now, typeof m.nowAt === "number" ? m.nowAt : handledMs, handledMs);   // feed.ts's rule, pinned below
  assert.equal(anchor({ now: T, nowAt: arrivedMs }, arrivedMs), T, "at the arrival");
  assert.equal(anchor({ now: T, nowAt: arrivedMs }, hourLater), T + 3600, "the re-emit keeps the hour");
  assert.equal(anchor({ now: T }, hourLater), T, "a frame with no pair anchors on the handling — the VS Code pipe's frames, which are never re-emitted");
});

test("an unstamped element is left alone", () => {
  const plain = mk(); plain.textContent = "Blocked";       // a question node's meta carries no age
  assert.equal(paintAge(plain, 5, rel, tint), false);
  assert.equal(plain.textContent, "Blocked");
  const junk = mk(); junk.dataset.ageT = "not-a-number";
  assert.equal(refreshAges([plain, junk], 5, rel, tint), 0);
});

test("a second pass at the same `now` writes NOTHING, and a pass across a minute boundary writes exactly the labels that crossed it", () => {
  // Blink treats an identical textContent write as a real Text-node replacement once the document has created
  // a MutationObserver (gear.js does at boot), so the compare is what keeps a quiet 15 s pass off the layout.
  const T = 1_000_000;
  const writes = (init: number) => {
    let n = 0;
    const e = { _text: "" as string | null, style: { color: "" }, dataset: {} as AgeEl["dataset"],
      get textContent() { return this._text; }, set textContent(v: string | null) { this._text = v; n++; } };
    stampAge(e, T - init, "plain", true, T, rel, tint);
    return { e, count: () => n };
  };
  const a = writes(100), b = writes(150), c = writes(4 * 60);   // "2m ago", "3m ago" (rounded), "4m ago"
  const c0 = a.count() + b.count() + c.count();
  assert.equal(c0, 3, "the stamp paints once each");
  assert.equal(refreshAges([a.e, b.e, c.e], T, rel, tint), 0, "same now: nothing rewritten");
  assert.equal(a.count() + b.count() + c.count(), c0, "…and no textContent setter ran");
  assert.equal(a.e.style.color, tint(100));
  // 20 s later: a (120 s → "2m ago") and c (260 s → "4m ago") read the same; b (170 s) rounds to "3m ago" still — a
  // tinted colour may move on the ramp, so a tinted label rewrites its colour at most, never its text
  const nText = { a: a.count(), b: b.count(), c: c.count() };
  refreshAges([a.e, b.e, c.e], T + 20, rel, tint);
  assert.deepEqual({ a: a.count(), b: b.count(), c: c.count() }, nText, "no text changed: no textContent write");
  // untinted stamps (card time stamps) have only their text: a pass that moves no label writes nothing at all
  let wrote = 0;
  const plain = { _text: "" as string | null, style: { color: "" }, dataset: {} as AgeEl["dataset"],
    get textContent() { return this._text; }, set textContent(v: string | null) { this._text = v; wrote++; } };
  stampAge(plain, T - 100, "plain", false, T, rel, tint);          // "2m ago"
  assert.equal(refreshAges([plain], T + 20, rel, tint), 0);          // 120 s: still "2m ago"
  assert.equal(refreshAges([plain], T + 40, rel, tint), 0);          // 140 s: "2m ago"
  assert.equal(refreshAges([plain], T + 50, rel, tint), 1, "150 s rounds to 3m: the one label that crossed is rewritten");
  assert.equal(plain.textContent, "3m ago");
  assert.equal(wrote, 2, "one write at the stamp, one at the crossing");
});

test("the tint compares against a shadow of what was written, not the CSSOM read-back: a style that re-serialises the colour is still written once", () => {
  const T = 1_000_000;
  let sets = 0;
  const style = { _c: "", get color() { return this._c; }, set color(v: string) { sets++; this._c = v.replace(/\s+/g, ""); } };   // a browser's read-back need not equal the string written
  const e: AgeEl = { textContent: null, style, dataset: {} };
  stampAge(e, T - 240, "plain", true, T, rel, tint);
  assert.equal(sets, 1);
  assert.notEqual(e.style.color, tint(240), "the read-back differs from what was written");
  assert.equal(refreshAges([e], T, rel, tint), 0, "same now: nothing rewritten…");
  assert.equal(sets, 1, "…the colour included — compared against the shadow, so the re-serialised read-back does not force a write every pass");
});

test("a running DURATION is a stamp too (fmt 'dur'): workingFor's minutes-then-hours vocabulary, moving with the clock", () => {
  const T = 1_000_000;
  const d = mk();
  stampAge(d, T - 42 * 60, "dur", false, T, rel, tint);
  assert.equal(d.textContent, "42m", "the awaiting box's / narration's duration, bare — the caller places the separator");
  refreshAges([d], T + 18 * 60, rel, tint);
  assert.equal(d.textContent, "1h 0m", "past sixty minutes it splits out the hours, as workingFor always did");
  assert.equal(refreshAges([d], T + 18 * 60 + 30, rel, tint), 0, "within the same minute nothing is written");
  assert.equal(d.style.color, "", "untinted");
});

test("liveRefresher: a hidden pane skips the pass and catches up exactly once when shown; an ordinary resize runs nothing", () => {
  let hidden = false, passes = 0;
  const live = liveRefresher({ hidden: () => hidden, pass: () => { passes++; } });
  live.tick(); assert.equal(passes, 1, "visible: the tick runs the pass");
  live.catchUp(); assert.equal(passes, 1, "nothing owed: a resize or visibility flip runs nothing");
  hidden = true;
  live.tick(); live.tick(); assert.equal(passes, 1, "hidden: two ticks, no pass");
  live.catchUp(); assert.equal(passes, 1, "still hidden: the catch-up waits");
  hidden = false;
  live.catchUp(); assert.equal(passes, 2, "shown: ONE catch-up pass for the two skipped ticks");
  live.catchUp(); assert.equal(passes, 2, "…and only one");
  live.tick(); assert.equal(passes, 3, "the cadence resumes");
});

test("feed.ts reads a card's clock only through nowSec(), stamps every age and duration on the card face, and the live pass repaints them all", () => {
  assert.match(FEED, /import \{ liveNow, liveRefresher, refreshAges, stampAge \} from "\.\/feed-age";/);
  assert.match(FEED, /function nowSec\(\): number \{ return liveNow\(hostNow, hostNowAt, Date\.now\(\)\); \}/);
  assert.match(FEED, /if \(typeof m\.now === "number"\) \{\n\s*hostNow = m\.now;\n\s*hostNowAt = typeof m\.nowAt === "number" \? m\.nowAt : Date\.now\(\);/,
    "the payload's clock is recorded with when THAT FRAME ARRIVED (federation's `nowAt`) — never with when this handler ran");
  assert.equal((FEED.match(/hostNowAt = Date\.now\(\)/g) || []).length, 2,
    "the bare arrival time anchors only a frame with no `nowAt` (no federation layer) or no `now` at all (an older kernel)");
  // the card stamps: the ask card's and the group card's time — nothing on a card face reads hostNow raw any
  // more (a raw read is an age frozen at the frame); the provenance popovers and the sub-goal rows keep the
  // frame's clock at their own repaint, as before
  assert.match(FEED, /stampAge\(a\._time, it\.t, "plain", false, nowSec\(\), relAge, ageColorReadable\);/);
  assert.match(FEED, /stampAge\(a\._time, g\.t, "plain", false, nowSec\(\), relAge, ageColorReadable\);/);
  assert.doesNotMatch(FEED, /a\._time\.textContent = relAge\(/, "the time label is a stamp, not a one-off write");
  assert.match(FEED, /relAge\(nowSec\(\) - at\)/, "the latched Continue's title ages on the same clock");
  // the running DURATIONS: the awaiting box, the Awaiting-task pill, the waiting-on chip, the working narration
  // and the per-paragraph ages are stamped too — the per-card update gate repaints a card only when its inputs
  // change, so a duration baked into a caption would freeze on a card never re-sent
  assert.match(FEED, /function durSpan\(since: number\): HTMLElement \{\n\s*const d = el\("span", "fask-dur"\);\n\s*stampAge\(d, since, "dur", false, nowSec\(\), relAge, ageColorReadable\);/);
  assert.doesNotMatch(FEED, /, Date\.now\(\) \/ 1000\)/, "no elapsed label reads the browser clock any more (the clock anchor itself still does, feed-age.ts liveNow)");
  assert.match(FEED, /if \(bp!\[i\]\.since\) stampAge\(age, bp!\[i\]\.since, "plain", false, nowS, relAge, ageColorReadable\);/);
  // the 15 s live pass: the latched Continue's title, then every stamped age, writing only what changed,
  // through the shared visibility gate
  const pass = FEED.slice(FEED.indexOf("function livePass(): void {"), FEED.indexOf("const live = liveRefresher("));
  assert.ok(pass.length > 0, "the live pass exists");
  assert.match(pass, /const now = nowSec\(\);/);
  assert.match(pass, /if \(cont && cont\.disabled && \(it\.followupPending \|\| it\.recheck \|\| it\.rejudging\)\) \{\n\s*const ct = contTitle\(true, "a continue", it\.followupAt\);\n\s*if \(cont\.title !== ct\) cont\.title = ct;/);
  assert.match(pass, /refreshAges\(document\.querySelectorAll<HTMLElement>\("\[data-age-t\]"\), now, relAge, ageColorReadable\);/);
  assert.doesNotMatch(FEED, /t\.textContent = relAge\(now - it\.t\);/, "the old tick, which rewrote every label on the browser clock, is gone");
  // "hidden" is the paint gate's decision over its two measures (paint-gate.ts: the tab's visibility and the
  // observer's word on #feed-list), not a second probe of the pane's viewport; both release events catch up
  assert.match(FEED, /const live = liveRefresher\(\{ hidden: \(\) => paintHeld\(document\.hidden, feedIntersecting, true\), pass: livePass \}\);\nsetInterval\(live\.tick, 15000\);\ndocument\.addEventListener\("visibilitychange", live\.catchUp\);\n/);
  assert.match(FEED, /feedIntersecting = entries\.some\(\(e\) => e\.isIntersecting\);\n\s*releasePaint\(\);\n\s*live\.catchUp\(\);/);
  assert.doesNotMatch(FEED, /window\.innerWidth === 0 \|\| window\.innerHeight === 0/, "no zero-viewport probe beside the gate");
});
