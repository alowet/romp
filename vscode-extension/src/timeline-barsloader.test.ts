// The timeline ships a LANES skeleton first, then the heavy BARS ({type:"bars"} → applyBars). Until all the
// data is in, the timeline shows ONLY the romp wordmark loader (R + spinning swirl-o + m + p + dots) — NO
// lanes, NO gridlines (the user 2026-06-26: partial data + empty gridlines read as broken). draw() returns
// early with the loader while !_barsLoaded. Source-level pins (no jsdom for the SVG renderer).
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const SRC = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "romp-timeline-view.js"), "utf8");

test("the bars-loaded gate starts false and flips true when applyBars lands real (or settled) content", () => {
  assert.match(SRC, /this\._barsLoaded = false;/);
  // the user 2026-07-03: applyBars no longer latches unconditionally — a warming-and-empty cold payload
  // keeps the loader; content or a settled (non-warming) build finalizes the load.
  assert.match(SRC, /if \(!\(m && m\.warming\) \|\| hasContent\) \{\s*\n\s*this\._barsLoaded = true;/);
});

test("a full one-shot data object through update() also marks the bars loaded (test harness / older clients)", () => {
  // 2026-09-07: the verdict is named (`ownBars`) because update() also uses it to decide whether a bars frame
  // parked ahead of its skeleton is older than this full object (timeline-hidden-hold.test.ts)
  assert.match(SRC, /const ownBars = !!\(data\.turns && Object\.keys\(data\.turns\)\.length\);\s*\n\s*if \(ownBars\) this\._barsLoaded = true;/);
});

test("draw() shows ONLY the loader and returns early until bars are ready (no lanes, no gridlines)", () => {
  // ready = the flag is set OR the data already carries turns (a full one-shot / a direct draw())
  assert.match(SRC, /const barsReady = this\._barsLoaded \|\| !!\(data\.turns && Object\.keys\(data\.turns\)\.length\);/);
  assert.match(SRC, /if \(!barsReady\) \{ this\._showLoader\(true\); this\._reapCompactBars\(null\); this\._reapWorkLabels\(null\); this\._reapMetaDots\(null\); return; \}/);
  assert.match(SRC, /this\._showLoader\(false\);/);
});

test("_showLoader toggles a wordmark overlay against the SVG", () => {
  assert.match(SRC, /_showLoader\(show\)/);
  assert.match(SRC, /this\.svg\.style\.display = show \? 'none' : '';/);
});

test("the loader is shown FROM CONSTRUCTION, before any data — no blank timeline on a cold start", () => {
  // the user 2026-07-03: on a kernel restart the timeline showed nothing until the first payload, because
  // draw() bails on null data and the loader only lived inside draw(). The constructor now raises it up front
  // and arms the backstop, so the romp swirl is up the instant the iframe (re)loads.
  const ctor = SRC.slice(SRC.indexOf("constructor(host)"), SRC.indexOf("destroy()"));
  assert.match(ctor, /this\._showLoader\(true\);\s*\n\s*this\._armLoaderBackstop\(\);/);
});

test("the loader is the full ROMP wordmark — R, m, p letters + the reverse-spinning swirl-o + dots", () => {
  assert.match(SRC, /_buildLoader\(\)/);
  assert.match(SRC, /mk\('R', '#1EA1EB'\)/);
  assert.match(SRC, /mk\('m', '#54B204'\)/);
  assert.match(SRC, /mk\('p', '#4EA8A9'\)/);
  assert.match(SRC, /o\.src = mediaUrl\('romp-swirl-o\.svg'\)/);
  assert.match(SRC, /@keyframes tl-rl-spin\{to\{transform:rotate\(-360deg\)\}\}/);
  assert.match(SRC, /rl-dots/);
});
