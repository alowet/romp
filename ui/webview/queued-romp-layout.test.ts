// T243 follow-up (my review's round-2 finding, 2026-09-07): the queued NUDGE form nests the landed .romp-tag +
// .romp-bubble inside the .queued-bubble wrapper — but .romp-bubble kept its landed max-width: 72% inside a
// wrapper already capped at 72%, the wrapper's block flow put the tag on the LEFT, and the wrapper-anchored ✕
// floated 100px+ off the bubble on the tag's row. Measured with a real browser against the real stylesheet:
// the queued nudge must be the landed nudge's width, right-aligned like it, with the ✕ in the bubble's corner
// and a one-line gist staying one line. Runs only where a Playwright browser exists (CI installs none) — it
// SKIPS LOUDLY there; the CI-safe source pins live in queued-indicator.test.ts.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const CSS_PATH = path.resolve(process.cwd(), "..", "ui", "webview", "styles.css");
const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");

const LONG = "Where does each of these stand? Tell me what shipped, what is next, or exactly what you need from me if you are stuck on any of it.";
const GIST_LONG = LONG.slice(0, 88).replace(/\s+\S*$/, "") + "…";
const tag = `<div class="romp-tag"><img class="romp-tag-logo" alt=""> romp</div>`;
// the ✕ sits where render.ts puts it: inside the nested romp bubble for a nudge (T243b), on the wrapper for a notice
const rb = (gist: string, cls = "", withX = false) =>
  `<div class="romp-bubble md nudge-collapsible${cls}" data-act="nudgetoggle"><div class="nudge-gist"><span class="nudge-caret">▸</span>${gist}</div>` +
  `<div class="nudge-full md"><p>${LONG}</p><p>${LONG}</p></div>${withX ? '<button class="queued-x">✕</button>' : ""}</div>`;
const html = `<body style="margin:0;width:700px">
<div id="landed-short" class="turn turn-user romp">${tag}${rb("follow-up · notes-api tests")}</div>
<div id="landed-long" class="turn turn-user romp">${tag}${rb(GIST_LONG)}</div>
<div id="q-short" class="turn turn-queued"><div class="queued-head"><span class="queued-count">1 queued nudge</span></div>
  <div class="queued-bubble md cancelable queued-romp">${tag}${rb("follow-up · notes-api tests", "", true)}</div></div>
<div id="q-long" class="turn turn-queued"><div class="queued-head"><span class="queued-count">1 queued nudge</span></div>
  <div class="queued-bubble md cancelable queued-romp">${tag}${rb(GIST_LONG, "", true)}</div></div>
<div id="q-sys" class="turn turn-queued"><div class="queued-head"><span class="queued-count">1 queued notice</span></div>
  <div class="queued-bubble md cancelable queued-romp queued-sys"><div class="notice-card notice-card-romp notice-nested"><div class="notice-head"><span class="notice-chip notice-chip-romp">romp</span><span class="notice-head-text">${GIST_LONG}</span></div></div><button class="queued-x">✕</button></div></div>
</body>`;

type Box = { l: number; r: number; t: number; b: number; w: number; h: number } | null;
type Measured = Record<string, { wrap: Box; tag: Box; bubble: Box; x: Box; gist: Box }>;

// The measurement runs in a standalone driver process (the T225 served-test pattern): the test bundle is
// CommonJS without top-level await, and esbuild must never try to bundle playwright itself.
const DRIVER = `
import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(process.env.EXT_PKG);
let chromium;
try { chromium = require("playwright").chromium; } catch (e) { process.exit(3); }
let browser;
try { browser = await chromium.launch(); } catch (e) { process.exit(3); }
const page = await browser.newPage({ viewport: { width: 900, height: 1100 } });
await page.setContent(fs.readFileSync(process.env.HTML_PATH, "utf8"));
await page.addStyleTag({ path: process.env.CSS_PATH });
const out = await page.evaluate(() => {
  const r = (el) => { if (!el) return null; const b = el.getBoundingClientRect(); return { l: Math.round(b.left), r: Math.round(b.right), t: Math.round(b.top), b: Math.round(b.bottom), w: Math.round(b.width), h: Math.round(b.height) }; };
  const res = {};
  for (const id of ["landed-short", "landed-long", "q-short", "q-long", "q-sys"]) {
    const turn = document.getElementById(id);
    res[id] = { wrap: r(turn.querySelector(".queued-bubble")), tag: r(turn.querySelector(".romp-tag")),
                bubble: r(turn.querySelector(".romp-bubble") || turn.querySelector(".notice-card")),
                x: r(turn.querySelector(".queued-x")), gist: r(turn.querySelector(".nudge-gist")) };
  }
  return res;
});
if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT, fullPage: true });
fs.writeSync(1, "RESULT:" + JSON.stringify(out) + "\\n");
await browser.close();
process.exit(0);
`;

function measure(): Measured | null {
  const os = require("node:os");
  const cp = require("node:child_process");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "qromp-layout-"));
  const driver = path.join(dir, "driver.mjs"); fs.writeFileSync(driver, DRIVER);
  const htmlPath = path.join(dir, "page.html"); fs.writeFileSync(htmlPath, html);
  try {
    const p = cp.spawnSync(process.execPath, [driver], { encoding: "utf8", timeout: 120000,   // the running node, never PATH
      env: { ...process.env, EXT_PKG: path.resolve(process.cwd(), "package.json"), HTML_PATH: htmlPath, CSS_PATH: CSS_PATH,
             SHOT: process.env.QROMP_LAYOUT_SHOT || "" } });
    if (p.status === 3) return null;                                  // no playwright / no browser here
    if (p.status !== 0) throw new Error("layout driver failed: " + String(p.stderr || p.stdout || p.error || "").slice(-800));
    const line = (p.stdout || "").split("\n").find((l: string) => l.startsWith("RESULT:"));
    if (!line) throw new Error("layout driver printed no result: " + (p.stdout || "").slice(-400));
    return JSON.parse(line.slice("RESULT:".length));
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
}

const m = measure();
const skip = m ? false : "no Playwright browser here — the layout pin needs one (CI installs none); the CI-safe source pins live in queued-indicator.test.ts";

test("a queued nudge is the landed nudge's width and stands on the landed side (T243b)", { skip }, () => {
  const L = m!["landed-long"], Q = m!["q-long"];
  assert.ok(Q.bubble!.w >= L.bubble!.w * 0.95, `queued bubble ${Q.bubble!.w}px vs landed ${L.bubble!.w}px — no 72%-of-72% double shrink`);
  assert.ok(Math.abs(Q.bubble!.r - Q.wrap!.r) <= 2, "the bubble hugs the wrapper's right edge like the landed bubble hugs the turn's");
  assert.ok(Math.abs(Q.tag!.r - Q.wrap!.r) <= 4, `the romp tag stands on the right (tag right ${Q.tag!.r}, wrapper right ${Q.wrap!.r})`);
});

test("the ✕ sits in the queued nudge bubble's corner, not off in the wrapper's gap (T243b)", { skip }, () => {
  const Q = m!["q-long"];
  const inside = Q.x!.l >= Q.bubble!.l && Q.x!.r <= Q.bubble!.r + 1 && Q.x!.t >= Q.bubble!.t && Q.x!.b <= Q.bubble!.b;
  assert.ok(inside, `✕ ${JSON.stringify(Q.x)} must lie inside the bubble ${JSON.stringify(Q.bubble)}`);
});

test("a one-line queued gist stays one line, as landed (T243b)", { skip }, () => {
  const L = m!["landed-short"], Q = m!["q-short"];
  assert.ok(Q.gist!.h <= L.gist!.h + 2, `queued gist height ${Q.gist!.h} vs landed ${L.gist!.h} — the 72%-of-itself cap wrapped it`);
});

test("the queued SYSTEM notice card spans its wrapper with the ✕ inside its corner (unchanged, round 1)", { skip }, () => {
  const S = m!["q-sys"];
  assert.ok(Math.abs(S.bubble!.w - S.wrap!.w) <= 2, "the card spans the wrapper");
  assert.ok(S.x!.l >= S.bubble!.l && S.x!.r <= S.bubble!.r + 1, "the ✕ is inside the card's corner");
});

test("render.ts hosts the nudge's ✕ inside the nested romp bubble (CI-safe pin, T243b)", () => {
  const body = RENDER.split("function renderQueued(")[1].split("\nfunction ")[0];
  assert.match(body, /let xHost: HTMLElement = bubble;/);
  assert.match(body, /xHost = rb;/, "a nudge's ✕ lives in its bubble's corner");
  assert.match(body, /xHost\.appendChild\(x\);/);
});
