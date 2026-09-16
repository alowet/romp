"""The cold-boot chat build diet, the client half (the user's ruling 2026-09-14: the selected tab builds first; the strip's other tabs
spread over later refreshes; hidden tabs are not built until shown). A hermetic kernel over TWENTY-SEVEN synthetic sessions, the real
/chat page served from a copy of the built bundle, driven by Playwright. Roads, one browser: (1) the dial: after a reload whose recorded
reason is a kernel restart the chat pane's first socket dials skeleton=1 beside active=, and after a build reload it does too (any reload
the reload core fired; restarts are invisible and a newer build is offered, so the one reload left is the one the user accepts, 2026-09-16); (2) the first
refresh: one full session frame, the selected tab's, ahead of the strip's paint, the other tabs as statuses with the strip listing the
skeleton set; (3) the spread: the visible skeletons fill on later idle callbacks one at a time, and tabs the #only= filter hides stay
skeletons until the filter shows them; (4) the measurement: time to the selected tab's first row, to the strip's 27 tabs, to every visible
tab built, for the restart reload and for a fresh open with no record; (5) a plain reload right after a restart reload dials no diet: the
record is consumed by the read that acted on it; (6) after a restart record every pane of the served dashboard dials, and only the chat
pane's dial carries the term; (7) lifting the #only= filter re-arms the idle prefetch: the revealed skeletons are asked for with no kernel
push in between; (8a) a record a standalone feed page's reload wrote steers no chat dial and is consumed; (8b) a malformed record is
consumed; (8c) a scalar or fieldless record is consumed and diets nothing; (9) a tagged section folded before a restart reload keeps its
tabs unbuilt while folded, and opening it re-arms the prefetch so their asks follow with no kernel push in between; (10) a SIBLING chat
document in the same browser context opening that section (the tab-groups store's storage event) re-arms this page too. (11) The Outline pane's provisional row (plans/outline-pane-provisional-row.md, 2026-09-15), on a SECOND boot of the same kernel
with goal stores seeded: a chat page dialing the diet with its idle prefetch held by the lab, then the Outline page; the Outline's dial
carries provrows=1 and its first frame lists every session, all but the selected one provisional, while the chat has one full frame and
/perf counts the cold skips; a click on a second tab builds it and its row loses the mark on the next frame; a muted session's
provisional row shows no goals; a raw unflagged Outline socket makes the kernel build every tab. The fresh open after a boot (no record, no diet)
is covered by NEITHER half today: this lab measures it and the design decision on it is the manager's. Synthetic only (placeholder ids,
invented text)."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from tests.dist_copy import copy_dist  # noqa: E402

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
EXT = os.path.join(ROOT, "vscode-extension")
sys.path.insert(0, HERE)
import test_ship_reship_served as _lab  # noqa: E402  the lab kernel's environment
from test_live_paused_window_browser import _free_port  # noqa: E402

N_SESSIONS = 27
TURNS_EACH = 12
GROUPS = ("web", "api", "tests")   # names web-01.., api-02.., tests-03..: #only=web shows nine of the twenty-seven


def sid_of(i):
    return "%08d-1111-2222-3333-%012d" % (i, i)


def name_of(i):
    return "%s-%02d" % (GROUPS[i % 3], i)


# the lab's own driver head: the shared one (the window lab's) expects one session with forty rendered rows and a bottom landing
DRIVER = r"""
import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(process.env.EXT_PKG);
const { chromium } = require("playwright");
const cfg = JSON.parse(fs.readFileSync(process.env.CFG, "utf8"));
let browser;
try { browser = await chromium.launch(cfg.launch || {}); }
catch (e) { console.error("browser-launch-failed: " + e); process.exit(3); }
const context = await browser.newContext({ viewport: { width: 1200, height: 700 } });   // an explicit context: road 10 opens a sibling document in it, so the tab-groups store's storage event crosses
const page = await context.newPage();
const pageEvents = [];
page.on("pageerror", (e) => pageEvents.push("pageerror:" + String(e).slice(0, 300)));
page.on("console", (m) => { if (m.type() === "error") pageEvents.push("console:" + m.text().slice(0, 300)); });
// ── the cold-boot diet roads ──
// every dial's URL (the shim's new WebSocket), and every frame the page receives with a clock, from before the page's scripts run
await page.addInitScript(() => {
  window.__dials = []; const W = window.WebSocket;
  window.WebSocket = function (url, protos) { window.__dials.push(String(url)); return protos === undefined ? new W(url) : new W(url, protos); };
  window.WebSocket.prototype = W.prototype; window.WebSocket.CONNECTING = 0; window.WebSocket.OPEN = 1; window.WebSocket.CLOSING = 2; window.WebSocket.CLOSED = 3;
  window.__frames = []; window.__t0 = performance.now(); window.__idles = 0;
  window.__sent = []; const send = WebSocket.prototype.send;   // every frame the page sends its kernel (the prefetch's needFull asks among them)
  WebSocket.prototype.send = function (d) { try { const m = JSON.parse(d); if (m && m.type) window.__sent.push(m); } catch (e) { /* not a frame */ } return send.call(this, d); };
  const ric = window.requestIdleCallback; if (typeof ric === "function") window.requestIdleCallback = function (cb, o) { window.__idles++; return ric.call(window, cb, o); };
  try { window.__loads = Number(sessionStorage.getItem("romp-lab:loads") || "0") + 1; sessionStorage.setItem("romp-lab:loads", String(window.__loads)); } catch (e) { window.__loads = -1; }
  window.addEventListener("message", (e) => { const m = e.data; if (!m || !m.type) return;
    window.__frames.push({ t: Math.round(performance.now() - window.__t0), type: m.type, id: m.id || null, n: Array.isArray(m.events) ? m.events.length : null, skel: Array.isArray(m.skeleton) ? m.skeleton.length : null }); });
  // paint marks: the first transcript row, the strip at twenty-seven tabs
  window.__paint = { firstRow: null, strip27: null, skelAtStrip27: null, skelMax: 0 };
  const mo = new MutationObserver(() => {
    if (window.__paint.firstRow === null && document.querySelector("#content .turn[data-uuid]")) window.__paint.firstRow = Math.round(performance.now() - window.__t0);
    const sk = document.querySelectorAll("#tabs .tab-skeleton").length; if (sk > window.__paint.skelMax) window.__paint.skelMax = sk;
    if (window.__paint.strip27 === null && document.querySelectorAll("#tabs .tab, #tabs [data-sid]").length >= 27) { window.__paint.strip27 = Math.round(performance.now() - window.__t0); window.__paint.skelAtStrip27 = sk; }
  });
  document.addEventListener("DOMContentLoaded", () => mo.observe(document.documentElement, { childList: true, subtree: true, attributes: true }));
});
await page.goto(cfg.chat);
await page.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
const sids = cfg.sids, selected = cfg.selected;
const fullsBy = () => page.evaluate(() => { const by = {}; for (const f of window.__frames) if (f.type === "session" && f.n) by[f.id] = (by[f.id] || 0) + 1; return by; });
const firstFrames = (n) => page.evaluate((k) => window.__frames.slice(0, k), n);
const allBuiltT = () => page.evaluate((all) => { const seen = new Set(); for (const f of window.__frames) { if (f.type === "session" && f.n) { seen.add(f.id); if (seen.size >= all.length) return f.t; } } return null; }, sids);
const waitFulls = (k, ms) => page.waitForFunction((k) => { const s = new Set(); for (const f of window.__frames) if (f.type === "session" && f.n) s.add(f.id); return s.size >= k; }, k, { timeout: ms }).catch(() => {});
// ROAD 4a (the FRESH open: the page the driver head opened, no reload record; the kernel half's case, measured here)
await waitFulls(sids.length, 60000);
const skelOf = () => page.evaluate(() => { const f = window.__frames.find((x) => x.skel !== null); return f ? { type: f.type, n: f.skel, t: f.t } : null; });
const painted = () => page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 0)))));
const nav = () => page.evaluate(() => ({ loads: window.__loads, href: location.href.replace(/token=[^&]*/, "token=X"), types: Array.from(new Set(window.__frames.map((f) => f.type))) }));
const fresh = { dial: (await page.evaluate(() => window.__dials[0] || null)), paint: await page.evaluate(() => window.__paint), allBuilt: await allBuiltT(), fulls: Object.keys(await fullsBy()).length,
  first: await firstFrames(40), skel: await skelOf(), nav: await nav() };
// the selected tab: the page's persisted state names it (the shim's ?active= reads activeId from the state blob)
await page.evaluate((sel) => { const k = "romp-vscode-state-chat"; let st = {}; try { st = JSON.parse(localStorage.getItem(k) || "{}") || {}; } catch (e) {} st.activeId = sel; localStorage.setItem(k, JSON.stringify(st)); }, selected);
// ROAD 1 + 2 + 4b: a RESTART reload (the reload core's durable record set as the core writes it)
await page.evaluate(() => { sessionStorage.setItem("romp:reloadReason", JSON.stringify({ reason: "restart", t: Date.now() })); });
await page.reload();
await page.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
await page.waitForFunction(() => !!document.querySelector("#content .turn[data-uuid]"), null, { timeout: 30000 }).catch(() => {});
await page.waitForFunction(() => window.__paint.strip27 !== null, null, { timeout: 20000 }).catch(() => {});
const restart = { dial: (await page.evaluate(() => window.__dials[0] || null)), paint: await page.evaluate(() => window.__paint),
  first: await firstFrames(60), skel: await skelOf(), nav: await nav(),
  fullsBeforeFirstRow: await page.evaluate(() => { const t = window.__paint.firstRow; return window.__frames.filter((f) => f.type === "session" && f.n && t !== null && f.t <= t).map((f) => f.id); }),
  firstRowUuid: await page.evaluate(() => { const r = document.querySelector("#content .turn[data-uuid]"); return r ? r.getAttribute("data-uuid") : null; }) };
// ROAD 3 (the spread): the visible skeletons fill over idle callbacks
await waitFulls(sids.length, 60000);
const spread = { allBuilt: await allBuiltT(), fulls: Object.keys(await fullsBy()).length, paint: await page.evaluate(() => window.__paint),
  gaps: await page.evaluate(() => { const ts = window.__frames.filter((f) => f.type === "session" && f.n).map((f) => f.t); const g = []; for (let i = 1; i < ts.length; i++) g.push(ts[i] - ts[i - 1]); return g; }) };
// ROAD 3b (hidden tabs): the #only= filter on this top-level page hides the api-* and tests-* tabs; a restart reload under it must not
// prefetch them; lifting the filter loads them
await page.evaluate(() => { location.hash = "#only=web"; });
await page.evaluate(() => { sessionStorage.setItem("romp:reloadReason", JSON.stringify({ reason: "restart", t: Date.now() })); });
await page.reload();
await page.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
const webIds = sids.filter((s, i) => cfg.names[i].startsWith("web"));
// strip facts, not frame accounting (this page's federation manager takes some frames off the message event): a skeleton tab element
// leaves the strip when its full lands, and a hidden tab has no element while the filter hides it
const skelCount = () => page.evaluate(() => document.querySelectorAll("#tabs .tab-skeleton").length);
const tabCount = () => page.evaluate(() => document.querySelectorAll("#tabs .tab, #tabs [data-sid]").length);
await page.waitForFunction(() => document.querySelectorAll("#tabs .tab, #tabs [data-sid]").length >= 9, null, { timeout: 15000 }).catch(() => {});
await painted();
const hiddenStart = { tabs: await tabCount(), skel: await skelCount() };
await page.waitForFunction(() => document.querySelectorAll("#tabs .tab-skeleton").length === 0, null, { timeout: 40000 }).catch(() => {});   // the visible skeletons fill on idle callbacks
await page.waitForTimeout(1500);   // idle callbacks past the visible set: a hidden tab built by mistake would show as a loaded tab when the filter lifts
const hidden = { dial: (await page.evaluate(() => window.__dials[0] || null)), start: hiddenStart, tabs: await tabCount(), skelVisibleAfterWait: await skelCount(), nav: await nav() };
await page.evaluate(() => { location.hash = ""; });
await page.waitForFunction(() => document.querySelectorAll("#tabs .tab, #tabs [data-sid]").length >= 27, null, { timeout: 15000 }).catch(() => {});
const skelAfterReveal = await skelCount();   // the tabs the filter hid come back: skeletons at the head (never built while hidden), loaded tabs at the base
await page.waitForFunction(() => document.querySelectorAll("#tabs .tab-skeleton").length === 0, null, { timeout: 60000 }).catch(() => {});
const revealed = { skelAfterReveal, skelFinal: await skelCount(), tabs: await tabCount() };
// ROAD 5 (round two, medium 1): a PLAIN reload right after a restart reload dials no diet: the record was consumed by the read that acted on it
await page.evaluate(() => { sessionStorage.setItem("romp:reloadReason", JSON.stringify({ reason: "restart", t: Date.now() })); });
await page.reload();
await page.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
const restart2 = { dial: (await page.evaluate(() => window.__dials[0] || null)), recordLeft: await page.evaluate(() => sessionStorage.getItem("romp:reloadReason")) };
await page.reload();
await page.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
const plain = { dial: (await page.evaluate(() => window.__dials[0] || null)) };
// ROAD 7 (round two, medium 3): the #only= filter lifted with the wire quiet: the revealed skeletons are asked for by the idle prefetch itself
await page.evaluate(() => { location.hash = "#only=web"; });
await page.evaluate(() => { sessionStorage.setItem("romp:reloadReason", JSON.stringify({ reason: "restart", t: Date.now() })); });
await page.reload();
await page.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
await page.waitForFunction(() => document.querySelectorAll("#tabs .tab-skeleton").length === 0, null, { timeout: 40000 }).catch(() => {});   // the shown skeletons filled
await page.waitForFunction(() => { const f = window.__frames; const last = f.length ? f[f.length - 1].t : 0; return performance.now() - window.__t0 - last > 1500; }, null, { timeout: 30000 }).catch(() => {});   // the wire quiet: no frame for 1.5 s
const beforeReveal = await page.evaluate(() => ({ idles: window.__idles, frames: window.__frames.length, needFull: window.__sent.filter((m) => m.type === "needFull").length, skel: document.querySelectorAll("#tabs .tab-skeleton").length }));
await page.evaluate(() => { location.hash = ""; });
await painted();
const skelAtReveal = await page.evaluate(() => document.querySelectorAll("#tabs .tab-skeleton").length);   // the revealed tabs appear as skeletons: never built while hidden (a hidden tab has no strip element to count before the reveal)
const skelSidsAtReveal = await page.evaluate(() => Array.from(document.querySelectorAll("#tabs .tab-skeleton")).map((e) => e.getAttribute("data-id")).filter(Boolean));   // a tab carries its session as data-id
const revealable = cfg.sids.filter((s, i) => !((cfg.names[i] || "").startsWith("web")));   // the fixed set the #only=web lift reveals, a known set, never a DOM snapshot that can miss a skeleton that paints a beat late
await page.waitForFunction((n) => window.__sent.filter((m) => m.type === "needFull").length > n, beforeReveal.needFull, { timeout: 10000 }).catch(() => {});
const afterReveal = await page.evaluate(([b, skelSids, revealable]) => { const asks = window.__sent.filter((m) => m.type === "needFull"); const firstAsk = asks.length > b.needFull ? asks[b.needFull] : null;
  // kernel frames that FILL a revealed skeleton, landing between the reveal and the first ask (a re-send for the already loaded active tab is not a fill)
  const fills = window.__frames.slice(b.frames).filter((f) => f.type === "session" && f.n && skelSids.includes(f.id)).length;
  return { idles: window.__idles, needFull: asks.length, firstAskWhy: firstAsk ? firstAsk.why : null, firstAskRevealed: firstAsk ? revealable.includes(firstAsk.id) : null, pushesBeforeFirstAsk: fills, skel: document.querySelectorAll("#tabs .tab-skeleton").length, skelSids: skelSids.length }; }, [beforeReveal, skelSidsAtReveal, revealable]);
afterReveal.skelAtReveal = skelAtReveal;
await page.waitForFunction(() => document.querySelectorAll("#tabs .tab-skeleton").length === 0, null, { timeout: 60000 }).catch(() => {});
const revealFilled = { skel: await page.evaluate(() => document.querySelectorAll("#tabs .tab-skeleton").length), needFull: await page.evaluate(() => window.__sent.filter((m) => m.type === "needFull" && m.why === "prefetch").length) };
// ROAD 6 (round two, medium 2): the served dashboard's shell after a restart record: every pane dials, the chat pane's dial alone carries the term
await page.evaluate(() => { sessionStorage.setItem("romp:reloadReason", JSON.stringify({ reason: "restart", t: Date.now() })); });
await page.goto(cfg.chat.replace("/chat?", "/?"));
await page.waitForTimeout(4000);
const paneDials = [];
for (const fr of page.frames()) { try { const ds = await fr.evaluate(() => (window.__dials || []).slice()); for (const d of ds) paneDials.push(d.replace(/token=[^&]*/, "token=X")); } catch (e) { /* a frame without the hook */ } }
await page.goto(cfg.chat);
await page.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
// ROAD 8c (round two, low b): a scalar or fieldless record is consumed and diets nothing
const scalars = [];
for (const raw of ["5", "\"x\"", "{}"]) {
  await page.evaluate((r) => { sessionStorage.setItem("romp:reloadReason", r); }, raw);
  await page.reload();
  await page.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
  scalars.push({ raw, dial: (await page.evaluate(() => window.__dials[0] || null)), recordLeft: await page.evaluate(() => sessionStorage.getItem("romp:reloadReason")) });
}
// ROAD 9 (round two, medium 1 and the executed fold gate): the api section folded, a restart reload, its nine tabs unbuilt while folded; the header
// clicked open, the idle prefetch re-armed, their asks following with no kernel push filling them first
await page.evaluate(() => { const h = document.querySelector('[data-act="toggle-group"][data-group="api"]'); if (h) h.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
await page.waitForFunction(() => { const h = document.querySelector('[data-act="toggle-group"][data-group="api"]'); return !!h && h.dataset.folded === "1"; }, null, { timeout: 5000 }).catch(() => {});
const foldedBefore = await page.evaluate(() => { const h = document.querySelector('[data-act="toggle-group"][data-group="api"]'); return h ? h.dataset.folded : null; });
await page.evaluate(() => { sessionStorage.setItem("romp:reloadReason", JSON.stringify({ reason: "restart", path: "/chat", t: Date.now() })); });
await page.reload();
await page.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
await page.waitForFunction(() => { const h = document.querySelector('[data-act="toggle-group"][data-group="api"]'); return !!h && h.dataset.folded === "1"; }, null, { timeout: 10000 }).catch(() => {});
await page.waitForFunction((api) => { const shown = Array.from(document.querySelectorAll("#tabs .tab-skeleton")).map((e) => e.getAttribute("data-id")).filter((id) => id && !api.includes(id)); return shown.length === 0; }, cfg.apiSids, { timeout: 40000 }).catch(() => {});   // the shown skeletons filled
await page.waitForFunction(() => { const f = window.__frames; const last = f.length ? f[f.length - 1].t : 0; return performance.now() - window.__t0 - last > 1500; }, null, { timeout: 30000 }).catch(() => {});   // the wire quiet
const folded = await page.evaluate((api) => ({ header: (document.querySelector('[data-act="toggle-group"][data-group="api"]') || {}).dataset ? document.querySelector('[data-act="toggle-group"][data-group="api"]').dataset.folded : null,
  apiFulls: window.__frames.filter((f) => f.type === "session" && f.n && api.includes(f.id)).length, apiAsks: window.__sent.filter((m) => m.type === "needFull" && api.includes(m.id)).length,
  idles: window.__idles, frames: window.__frames.length, needFull: window.__sent.filter((m) => m.type === "needFull").length }), cfg.apiSids);
await page.evaluate(() => { const h = document.querySelector('[data-act="toggle-group"][data-group="api"]'); if (h) h.dispatchEvent(new MouseEvent("click", { bubbles: true })); });   // opened
await page.waitForFunction((n) => window.__sent.filter((m) => m.type === "needFull").length > n, folded.needFull, { timeout: 10000 }).catch(() => {});
const unfolded = await page.evaluate(([b, api]) => { const asks = window.__sent.filter((m) => m.type === "needFull"); const firstAsk = asks.length > b.needFull ? asks[b.needFull] : null;
  const fills = window.__frames.slice(b.frames).filter((f) => f.type === "session" && f.n && api.includes(f.id)).length;
  return { header: (document.querySelector('[data-act="toggle-group"][data-group="api"]') || { dataset: {} }).dataset.folded, idles: window.__idles, needFull: asks.length, firstAskWhy: firstAsk ? firstAsk.why : null, firstAskApi: firstAsk ? api.includes(firstAsk.id) : null, pushesBeforeFirstAsk: fills }; }, [folded, cfg.apiSids]);
await page.waitForFunction(() => document.querySelectorAll("#tabs .tab-skeleton").length === 0, null, { timeout: 60000 }).catch(() => {});
const unfoldedFilled = { skel: await page.evaluate(() => document.querySelectorAll("#tabs .tab-skeleton").length),
  apiLoaded: await page.evaluate((api) => api.filter((id) => { const e = document.querySelector(`#tabs .tab[data-id="${id}"]`); return !!e && !e.classList.contains("tab-skeleton"); }).length, cfg.apiSids),   // the strip's own word: the api tabs shown and loaded
  apiFulls: await page.evaluate((api) => window.__frames.filter((f) => f.type === "session" && f.n && api.includes(f.id)).length, cfg.apiSids) };
// ROAD 10 (round three, medium 1): the api section folded again on this page and a restart reload; a SIBLING chat document in the same
// browser context clicks the section open; the store's storage event reaches this page, whose repaint must re-arm the prefetch for the
// nine revealed tabs (before the fix the storage half rendered alone: nothing asked until an unrelated event)
await page.evaluate(() => { const h = document.querySelector('[data-act="toggle-group"][data-group="api"]'); if (h) h.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
await page.waitForFunction(() => { const h = document.querySelector('[data-act="toggle-group"][data-group="api"]'); return !!h && h.dataset.folded === "1"; }, null, { timeout: 5000 }).catch(() => {});
await page.evaluate(() => { sessionStorage.setItem("romp:reloadReason", JSON.stringify({ reason: "restart", path: "/chat", t: Date.now() })); });
await page.reload();
await page.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
await page.waitForFunction((api) => { const shown = Array.from(document.querySelectorAll("#tabs .tab-skeleton")).map((e) => e.getAttribute("data-id")).filter((id) => id && !api.includes(id)); return shown.length === 0; }, cfg.apiSids, { timeout: 40000 }).catch(() => {});
await page.waitForFunction(() => { const f = window.__frames; const last = f.length ? f[f.length - 1].t : 0; return performance.now() - window.__t0 - last > 1500; }, null, { timeout: 30000 }).catch(() => {});
const siblingBefore = await page.evaluate((api) => ({ header: (document.querySelector('[data-act="toggle-group"][data-group="api"]') || { dataset: {} }).dataset.folded, idles: window.__idles, frames: window.__frames.length, needFull: window.__sent.filter((m) => m.type === "needFull").length, apiAsks: window.__sent.filter((m) => m.type === "needFull" && api.includes(m.id)).length }), cfg.apiSids);
const sibling = await context.newPage();
await sibling.goto(cfg.chat);
await sibling.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
await sibling.waitForFunction(() => { const h = document.querySelector('[data-act="toggle-group"][data-group="api"]'); return !!h && h.dataset.folded === "1"; }, null, { timeout: 10000 }).catch(() => {});
await sibling.evaluate(() => { const h = document.querySelector('[data-act="toggle-group"][data-group="api"]'); if (h) h.dispatchEvent(new MouseEvent("click", { bubbles: true })); });   // the sibling opens the section: the store writes, this page's storage event fires
await page.waitForFunction((n) => window.__sent.filter((m) => m.type === "needFull").length > n, siblingBefore.needFull, { timeout: 10000 }).catch(() => {});
const siblingAfter = await page.evaluate(([b, api]) => { const asks = window.__sent.filter((m) => m.type === "needFull"); const firstAsk = asks.length > b.needFull ? asks[b.needFull] : null;
  const fills = window.__frames.slice(b.frames).filter((f) => f.type === "session" && f.n && api.includes(f.id)).length;
  return { header: (document.querySelector('[data-act="toggle-group"][data-group="api"]') || { dataset: {} }).dataset.folded, idles: window.__idles, needFull: asks.length, firstAskWhy: firstAsk ? firstAsk.why : null, firstAskApi: firstAsk ? api.includes(firstAsk.id) : null, pushesBeforeFirstAsk: fills }; }, [siblingBefore, cfg.apiSids]);
await page.waitForFunction(() => document.querySelectorAll("#tabs .tab-skeleton").length === 0, null, { timeout: 60000 }).catch(() => {});
const siblingFilled = { skel: await page.evaluate(() => document.querySelectorAll("#tabs .tab-skeleton").length), apiLoaded: await page.evaluate((api) => api.filter((id) => { const e = document.querySelector(`#tabs .tab[data-id="${id}"]`); return !!e && !e.classList.contains("tab-skeleton"); }).length, cfg.apiSids) };
await sibling.close();
// ROAD 1b: a BUILD reload dials the diet too (the follow-up after PR 1661: restarts are invisible, and since 2026-09-16 a newer build is
// offered, so the one reload the core fires is the one the user accepts: a fresh page on a kernel that has the build)
await page.evaluate(() => { sessionStorage.setItem("romp:reloadReason", JSON.stringify({ reason: "newer build", path: "/chat", t: Date.now() })); });
await page.reload();
await page.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
const build = { dial: (await page.evaluate(() => window.__dials[0] || null)) };
// ROAD 8a (low 1): a record a standalone FEED page's own reload wrote (its path) lingers in the tab and must not steer the next chat document's dial; it is consumed
await page.evaluate(() => { sessionStorage.setItem("romp:reloadReason", JSON.stringify({ reason: "restart", path: "/feed", t: Date.now() })); });
await page.reload();
await page.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
const feedRecord = { dial: (await page.evaluate(() => window.__dials[0] || null)), recordLeft: await page.evaluate(() => sessionStorage.getItem("romp:reloadReason")) };
// ROAD 8b (low 6): a malformed record is consumed too
await page.evaluate(() => { sessionStorage.setItem("romp:reloadReason", "{not json"); });
await page.reload();
await page.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
const malformed = { dial: (await page.evaluate(() => window.__dials[0] || null)), recordLeft: await page.evaluate(() => sessionStorage.getItem("romp:reloadReason")) };
process.stdout.write("RESULT:" + JSON.stringify({ fresh, restart, spread, hidden, revealed, build, webIds, restart2, plain, beforeReveal, afterReveal, revealFilled, paneDials, feedRecord, malformed, scalars, foldedBefore, folded, unfolded, unfoldedFilled, siblingBefore, siblingAfter, siblingFilled }) + "\n");
await browser.close();
"""


# ROAD 11: the Outline pane's provisional row. Its own browser run on a SECOND boot of the kernel (the cold set is real only right after
# a boot: the first driver's fresh open warmed every tab). The chat page's requestIdleCallback is HELD so the prefetch that fills the
# strip's skeletons waits for the lab: the cold set stands while the Outline connects and reads; the click and the raw socket then
# release tabs by the kernel's own roads.
OUTLINE_DRIVER = r"""
import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(process.env.EXT_PKG);
const { chromium } = require("playwright");
const cfg = JSON.parse(fs.readFileSync(process.env.CFG, "utf8"));
let browser;
try { browser = await chromium.launch(cfg.launch || {}); }
catch (e) { console.error("browser-launch-failed: " + e); process.exit(3); }
const ctx = await browser.newContext({ viewport: { width: 1200, height: 700 } });
const errors = [];
const wrapDials = () => {
  window.__dials = []; const W = window.WebSocket;
  window.WebSocket = function (url, protos) { window.__dials.push(String(url)); return protos === undefined ? new W(url) : new W(url, protos); };
  window.WebSocket.prototype = W.prototype; window.WebSocket.CONNECTING = 0; window.WebSocket.OPEN = 1; window.WebSocket.CLOSING = 2; window.WebSocket.CLOSED = 3;
  window.__t0 = performance.now();
};
// the chat page: the full frames it receives, and its idle callbacks held until the lab releases them
const chat = await ctx.newPage();
chat.on("pageerror", (e) => errors.push("chat pageerror:" + String(e).slice(0, 300)));
await chat.addInitScript(wrapDials);
await chat.addInitScript(() => {
  window.__fulls = [];
  window.addEventListener("message", (e) => { const m = e.data; if (m && m.type === "session" && Array.isArray(m.events) && m.events.length) window.__fulls.push({ t: Math.round(performance.now() - window.__t0), id: m.id }); });
  window.__held = []; const ric = window.requestIdleCallback;
  window.requestIdleCallback = function (cb) { window.__held.push(cb); return 0; };
  window.__releaseIdle = () => { const held = window.__held.splice(0); window.requestIdleCallback = ric; for (const cb of held) ric.call(window, cb); return held.length; };
});
// the restart record and the selected tab, written on a same-origin document before the chat page loads (a boot has no record)
await chat.goto(cfg.chat.replace("/chat?", "/healthz?"));
await chat.evaluate((sel) => { sessionStorage.setItem("romp:reloadReason", JSON.stringify({ reason: "restart", t: Date.now() }));
  localStorage.setItem("romp-vscode-state-chat", JSON.stringify({ activeId: sel })); }, cfg.selected);
await chat.goto(cfg.chat);
await chat.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
await chat.waitForFunction(() => window.__fulls.length >= 1, null, { timeout: 30000 }).catch(() => {});
const chatFulls = () => chat.evaluate(() => window.__fulls.map((f) => f.id));
const chatStart = { dial: await chat.evaluate(() => window.__dials[0] || null), fulls: await chatFulls(),
  skel: await chat.evaluate(() => document.querySelectorAll("#tabs .tab-skeleton").length) };
// the Outline page: every feed frame's ledgers, reduced to what the road reads
const outline = await ctx.newPage();
outline.on("pageerror", (e) => errors.push("outline pageerror:" + String(e).slice(0, 300)));
await outline.addInitScript(wrapDials);
await outline.addInitScript(() => {
  window.__feeds = [];
  // the pane's merged frames (feed among them) reach its handlers by direct call through the federation manager, never as a window
  // message event; the shim hands every local frame, deltas already applied, to window.__rompFed.inbound, so the recorder wraps that
  const record = (m) => { if (!m || m.type !== "feed" || !Array.isArray(m.ledgers)) return;
    window.__feeds.push({ t: Math.round(performance.now() - window.__t0), n: m.ledgers.length, prov: m.ledgers.filter((r) => r.provisional).map((r) => r.sid),
      rows: Object.fromEntries(m.ledgers.map((r) => [r.sid, { provisional: !!r.provisional, name: r.name, state: r.status ? r.status.state : null,
        provState: !!(r.status && r.status.provisional), keys: r.ledger ? Object.keys(r.ledger).sort() : null, current: r.ledger ? r.ledger.current : "absent",
        tree: r.ledger && Array.isArray(r.ledger.tree) ? r.ledger.tree.map((n) => n.text) : null,
        anchors: r.ledger && Array.isArray(r.ledger.tree) ? r.ledger.tree.map((n) => [n.promptAnchor || null, n.workAnchor || null]) : null }])) }); };
  let fed = null;
  Object.defineProperty(window, "__rompFed", { configurable: true, get() { return fed; },
    set(v) { fed = v; if (v && typeof v.inbound === "function" && !v.__labWrapped) { const inb = v.inbound; v.__labWrapped = true; v.inbound = (h, m) => { record(m); return inb(h, m); }; } } });
  window.addEventListener("message", (e) => { if (!fed) record(e.data); });   // a page without the manager: the window event
});
await outline.goto(cfg.fleet);
await outline.waitForFunction(() => window.__feeds.length >= 1, null, { timeout: 20000 }).catch(() => {});
const fullsAtFirst = await chatFulls();   // read at once: the chat's fulls when the Outline's first frame landed (its prefetch is held)
await outline.waitForFunction(() => document.querySelectorAll("#fleet-list .fl-session").length >= 1, null, { timeout: 15000 }).catch(() => {});
await outline.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 0)))));
const perf = async () => { const r = await outline.request.get(cfg.perf); const j = await r.json(); const c = j.builds && j.builds.chat ? j.builds.chat : {};
  return { coldSkipped: c.coldSkipped === undefined ? null : c.coldSkipped, built: c.built === undefined ? null : c.built, memo: j.memos ? j.memos.outlineProvisional || null : null }; };
const dom = () => outline.evaluate(() => {
  const secs = Array.from(document.querySelectorAll("#fleet-list .fl-session")).map((sec) => { const head = sec.querySelector(".fl-head"); return {
    sid: head ? head.dataset.sid : null, prov: sec.classList.contains("fl-prov-sess"), title: head ? head.title : null,
    rows: sec.querySelectorAll(".ledger-tnode[data-nid]").length, nav: sec.querySelectorAll(".ledger-tnode[data-nid] .lz-nav").length,
    acts: sec.querySelectorAll(".ledger-tmark[data-act], .ledger-ttext[data-act], .ledger-ttime[data-act]").length,
    nameUnderline: (() => { const nm = sec.querySelector(".fl-name"); return nm ? getComputedStyle(nm).borderBottomStyle : null; })() }; });
  return { sections: secs, provSections: secs.filter((x) => x.prov).length };
});
const first = { feed: await outline.evaluate(() => window.__feeds[0] || null), fullsAtFirst, dial: await outline.evaluate(() => window.__dials[0] || null),
  dials: await outline.evaluate(() => window.__dials.length), dom: await dom(), perf: await perf() };   // dials: a redial would show here
// the click: a second tab in the chat strip; the kernel builds it and the Outline's next frame carries its built row
await chat.click('#tabs [data-id="' + cfg.click + '"]');
await outline.waitForFunction((sid) => { const f = window.__feeds; const last = f.length ? f[f.length - 1] : null; return !!(last && last.rows[sid] && !last.rows[sid].provisional); }, cfg.click, { timeout: 30000 }).catch(() => {});
await outline.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 0)))));
const afterClick = { feed: await outline.evaluate(() => window.__feeds[window.__feeds.length - 1] || null), fulls: await chatFulls(), dom: await dom(), perf: await perf(),
  heldStill: await chat.evaluate(() => window.__held.length) };
// a raw Outline socket WITHOUT the flag: an older pane; the kernel builds every tab for it (the chat's prefetch still held: these are the
// kernel's own builds, read from /perf and from the Outline's rows; the chat page holds its skeletons and is owed no full frame for them)
await outline.evaluate((u) => { window.__raw = new WebSocket(u); }, cfg.rawWs);
await outline.waitForFunction(() => { const f = window.__feeds; const last = f.length ? f[f.length - 1] : null; return !!(last && last.prov.length === 0); }, null, { timeout: 90000 }).catch(() => {});
const unflagged = { fullsDistinct: new Set(await chatFulls()).size, feed: await outline.evaluate(() => window.__feeds[window.__feeds.length - 1] || null), perf: await perf(),
  rawDial: await outline.evaluate(() => window.__dials[window.__dials.length - 1] || null), heldStill: await chat.evaluate(() => window.__held.length) };
await outline.evaluate(() => { try { window.__raw.close(); } catch (e) { /* closed */ } });
process.stdout.write("RESULT:" + JSON.stringify({ chatStart, first, afterClick, unflagged, errors }) + "\n");
await browser.close();
"""

GOAL_I, MUTED_I, SELECTED_I = 2, 4, 3   # api-02: a goal store, the tab the road clicks; web-04: a store AND hideFromFeed; web-03: the selected tab, built, a store too


def _goal_store(sid):
    t = int(time.time()) - 600   # recent: the pane's recency slider hides a session whose tops are older than its cut
    return {"rompUuid": sid, "seq": 1, "placementsV": 1, "status": {}, "lastNode": "g2",
            "nodes": {"g1": {"text": "index the notes", "t": t, "mt": t, "parentId": None},
                      "g2": {"text": "write the search route", "t": t + 100, "mt": t + 100, "parentId": "g1"}}}


class ColdBootDiet(unittest.TestCase):
    maxDiff = None

    @classmethod
    def _skip(cls, why):
        if os.environ.get("ROMP_SERVED_TESTS_REQUIRE") == "1":
            raise AssertionError("ROMP_SERVED_TESTS_REQUIRE=1 but the served lab could not run: " + why)
        raise unittest.SkipTest(why)

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(os.path.join(EXT, "node_modules", "playwright")):
            cls._skip("extension deps absent (npm ci not run here) — the served guard needs them")
        cls.lab = tempfile.mkdtemp(prefix="cold-boot-diet-")
        b = subprocess.run(["node", "esbuild.js"], cwd=EXT, capture_output=True, text=True)
        if b.returncode != 0:
            cls._skip("esbuild failed here: " + (b.stderr or b.stdout)[-200:])
        dist = os.path.join(cls.lab, "dist")
        copy_dist(os.path.join(EXT, "dist"), dist)
        cls.state = os.path.join(cls.lab, "xdg", "romp")
        cwd = os.path.join(cls.lab, "proj")
        for d in ("names", "sdk", "states"):
            os.makedirs(os.path.join(cls.state, d), exist_ok=True)
        os.makedirs(cwd, exist_ok=True)
        Path(cls.state, "session-hosts").write_text("off\n")
        Path(cls.state, "usage.json").write_text(json.dumps({"five_hour": {"pct": 100}, "seven_day": {"pct": 10}}))
        claude = os.path.join(cls.lab, "claude")
        proj = os.path.join(claude, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd)))
        os.makedirs(proj, exist_ok=True)
        base = int(time.time()) - 3 * 3600
        cls.sids, cls.names = [], []
        for i in range(1, N_SESSIONS + 1):
            sid, name = sid_of(i), name_of(i)
            cls.sids.append(sid); cls.names.append(name)
            Path(cls.state, "names", sid).write_text("%s\t%s\t\t\n" % (name, cwd))
            Path(cls.state, "sdk", sid + ".json").write_text(json.dumps(
                {"sid": sid, "name": name, "cwd": cwd, "mode": "auto", "effort": "high", "lastSid": sid, "alive": True,
                 "model": "claude-fable-5-1", "liveModel": "Fable 5.1"}))
            recs, prev = [], None
            for k in range(TURNS_EACH):
                t0 = base + i * 60 + 2 * k
                u = "%08d-2222-3333-4444-%012d" % (i, 2 * k); a = "%08d-2222-3333-4444-%012d" % (i, 2 * k + 1)
                tu = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t0)); ta = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t0 + 1))
                recs.append({"type": "user", "uuid": u, "parentUuid": prev, "timestamp": tu, "sessionId": sid,
                             "message": {"role": "user", "content": "question %d for %s about the notes api" % (k, name)}})
                recs.append({"type": "assistant", "uuid": a, "parentUuid": u, "timestamp": ta, "sessionId": sid,
                             "message": {"role": "assistant", "model": "claude-fable-5-1", "stop_reason": "end_turn",
                                         "content": [{"type": "text", "text": "answer %d for %s: the notes api keeps its shape." % (k, name)}]}})
                prev = a
            Path(proj, sid + ".jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        api_sids = [s for s, n in zip(cls.sids, cls.names) if n.startswith("api")]
        Path(cls.state, "timeline-views.json").write_text(json.dumps({"tags": [{"id": "tag-api", "name": "api", "color": "#7ee787", "members": api_sids}], "tagOrder": ["api"]}))
        cls.api_sids = api_sids
        cls.port = _free_port()
        cls.token = "testtok-coldboot"
        cls.env = _lab.kernel_env(cls.lab, claude, dist, cls.port, cls.token)
        cls.klog = os.path.join(cls.lab, "kernel.log")
        cls._boot_kernel()
        cls._r = None
        cls._ro = None

    @classmethod
    def _boot_kernel(cls):
        """Start the lab kernel (a second time for road 11: the cold set is real only right after a boot) and wait for /healthz."""
        cls.kernel = subprocess.Popen([os.path.join(BIN, "romp-kernel")], stdout=open(cls.klog, "a"), stderr=subprocess.STDOUT, env=cls.env)
        import urllib.request
        for _ in range(120):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/healthz" % cls.port, timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            cls.kernel.kill()
            cls._skip("hermetic kernel never served /healthz here")

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "kernel", None):
            cls.kernel.kill()
            cls.kernel.wait()
        shutil.rmtree(getattr(cls, "lab", ""), ignore_errors=True)

    def _result(self):
        if getattr(type(self), "_fail", None):   # the driver failed once: every test reports that failure instead of re-driving the browser (seven runs of a minute each)
            self.fail(type(self)._fail)
        if self._r is None:
            cfg = os.path.join(self.lab, "diet.json")
            with open(cfg, "w") as f:
                json.dump({"chat": "http://127.0.0.1:%d/chat?token=%s" % (self.port, self.token), "sid": self.sids[0], "sids": self.sids,
                           "names": self.names, "selected": self.sids[2], "apiSids": self.api_sids, "shots": ""}, f)   # session 3 (web-03): visible under #only=web, not in the api section
            driver = os.path.join(self.lab, "diet.mjs")
            Path(driver).write_text(DRIVER)
            p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=400,
                               env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
            if "browser-launch-failed" in p.stderr:
                self._skip("no playwright browser on this box")
            line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT:")), None)
            if line is None:
                type(self)._fail = "the driver produced no RESULT (stderr: %s)" % p.stderr[-2000:]
                self.fail(type(self)._fail)
            type(self)._r = json.loads(line[len("RESULT:"):])
        print("DIET:", json.dumps(self._r), file=sys.stderr)   # every test's call: pytest shows the failing test's captured stderr alone
        return self._r

    def _result_outline(self):
        """Road 11 on a SECOND boot: the diet driver first (its fresh open warms every tab, so it must have run), then the goal stores
        and the mute seeded, the kernel restarted, the Outline driver run once; every test of the road reads this one result."""
        if getattr(type(self), "_fail_o", None):
            self.fail(type(self)._fail_o)
        if self._ro is None:
            self._result()
            goals = os.path.join(self.state, "goals")
            os.makedirs(goals, exist_ok=True)
            for i in (GOAL_I, MUTED_I, SELECTED_I):
                Path(goals, sid_of(i) + ".json").write_text(json.dumps(_goal_store(sid_of(i))))
            Path(self.state, "session-flags.json").write_text(json.dumps({sid_of(MUTED_I): {"hideFromFeed": True}}))
            self.kernel.kill(); self.kernel.wait()
            type(self)._boot_kernel()
            cfg = os.path.join(self.lab, "outline.json")
            base = "http://127.0.0.1:%d" % self.port
            with open(cfg, "w") as f:
                json.dump({"chat": base + "/chat?token=" + self.token, "fleet": base + "/fleet?token=" + self.token, "perf": base + "/perf?token=" + self.token,
                           "rawWs": "ws://127.0.0.1:%d/ws?app=fleet&delta=1&iid=lab-unflagged&token=%s" % (self.port, self.token),
                           "sids": self.sids, "selected": sid_of(SELECTED_I), "click": sid_of(GOAL_I)}, f)
            driver = os.path.join(self.lab, "outline.mjs")
            Path(driver).write_text(OUTLINE_DRIVER)
            p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=400,
                               env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
            if "browser-launch-failed" in p.stderr:
                self._skip("no playwright browser on this box")
            line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT:")), None)
            if line is None:
                type(self)._fail_o = "the Outline driver produced no RESULT (stderr: %s)" % p.stderr[-2000:]
                self.fail(type(self)._fail_o)
            type(self)._ro = json.loads(line[len("RESULT:"):])
        print("OUTLINE:", json.dumps(self._ro), file=sys.stderr)
        return self._ro

    def test_the_first_dial_after_a_restart_reload_is_a_skeleton_dial_and_a_build_reload_dials_the_diet_too(self):
        r = self._result()
        self.assertIsNotNone(r["restart"]["dial"], "the page dialed after the restart reload")
        self.assertIn("&skeleton=1", r["restart"]["dial"], "the first dial after a kernel restart's reload declares the diet: %r" % r["restart"]["dial"])
        self.assertIn("&active=" + self.sids[2], r["restart"]["dial"], "…beside the selected tab: %r" % r["restart"]["dial"])
        self.assertIn("&skeleton=1", r["build"]["dial"] or "", "a build reload dials the diet too: the one reload the core fires lands a fresh page on a kernel that just restarted (the follow-up after PR 1661): %r" % r["build"]["dial"])
        self.assertNotIn("skeleton=1", r["fresh"]["dial"] or "", "a fresh open dials as before (the kernel half's case): %r" % r["fresh"]["dial"])

    def test_the_first_refresh_after_a_restart_reload_builds_the_selected_tab_first_and_the_rest_as_skeletons(self):
        r = self._result()
        rs = r["restart"]
        self.assertEqual(rs["paint"]["skelMax"], N_SESSIONS - 1, "the strip drew the other twenty-six as skeleton tabs: %r" % rs["paint"])
        self.assertEqual(rs["fullsBeforeFirstRow"], [self.sids[2]], "one full frame, the selected tab's, ahead of the first row painted: %r" % rs["fullsBeforeFirstRow"])
        self.assertIsNotNone(rs["firstRowUuid"], "a row painted: %r" % rs["paint"])
        self.assertIsNotNone(rs["paint"]["firstRow"]); self.assertIsNotNone(rs["paint"]["strip27"])

    def test_the_visible_skeletons_fill_on_later_idle_callbacks_and_hidden_tabs_wait_for_the_filter_to_show_them(self):
        r = self._result()
        self.assertEqual(r["spread"]["fulls"], N_SESSIONS, "every tab built in the end: %r" % r["spread"]["fulls"])
        h = r["hidden"]
        self.assertIn("&skeleton=1", h["dial"] or "")
        hidden_n = N_SESSIONS - len(r["webIds"])   # the strip carries one element beyond the tabs, so the counts are read against the unfiltered strip
        self.assertEqual(rv_tabs := r["revealed"]["tabs"], h["start"]["tabs"] + hidden_n, "the filter hid the eighteen api and tests tabs and showed the nine web tabs: %r then %r" % (h["start"], r["revealed"]))
        self.assertGreaterEqual(h["start"]["skel"], 1, "the shown tabs other than the selected start as skeletons: %r" % h["start"])
        self.assertEqual(h["skelVisibleAfterWait"], 0, "the shown skeletons filled on idle callbacks: %r" % h)
        rv = r["revealed"]
        self.assertGreaterEqual(rv["tabs"], N_SESSIONS, "lifting the filter shows every tab: %r" % rv)
        self.assertEqual(rv["skelAfterReveal"], hidden_n, "the tabs the filter hid come back as SKELETONS: none was built while hidden (at the base they came back loaded): %r" % rv)
        self.assertEqual(rv["skelFinal"], 0, "…and load once shown: %r" % rv)

    def test_a_plain_reload_after_a_restart_reload_dials_no_diet_the_record_consumed_on_the_read(self):
        # round two, medium 1
        r = self._result()
        self.assertIn("&skeleton=1", r["restart2"]["dial"] or "", "the restart reload dialed the diet: %r" % r["restart2"])
        self.assertIsNone(r["restart2"]["recordLeft"], "the read that acted on the record consumed it: %r" % r["restart2"])
        self.assertNotIn("skeleton=1", r["plain"]["dial"] or "", "the plain reload right after dials as before: %r" % r["plain"])

    def test_a_feed_pages_record_steers_no_chat_dial_and_a_malformed_record_is_consumed(self):
        # the follow-up after PR 1661, lows 1 and 6
        r = self._result()
        f = r["feedRecord"]
        self.assertNotIn("skeleton=1", f["dial"] or "", "a record a standalone feed page's reload wrote steers no chat dial: %r" % f)
        self.assertIsNone(f["recordLeft"], "…and is consumed, so it lingers for no later document: %r" % f)
        m = r["malformed"]
        self.assertNotIn("skeleton=1", m["dial"] or "", "a malformed record dials no diet: %r" % m)
        self.assertIsNone(m["recordLeft"], "…and is consumed (removed before it is parsed): %r" % m)
        for s in r["scalars"]:   # round two, low b: only an object with the fields counts
            self.assertNotIn("skeleton=1", s["dial"] or "", "a scalar or fieldless record dials no diet: %r" % s)
            self.assertIsNone(s["recordLeft"], "…and is consumed: %r" % s)

    def test_a_folded_section_keeps_its_tabs_unbuilt_and_opening_it_re_arms_the_prefetch(self):
        # round two, medium 1 (the unfold re-arms the idle prefetch) and the executed fold gate (the follow-up's low 3)
        r = self._result()
        self.assertEqual(r["foldedBefore"], "1", "the api section folded on the header's click before the reload: %r" % r["foldedBefore"])
        f = r["folded"]
        self.assertEqual(f["header"], "1", "the fold survived the restart reload: %r" % f)
        self.assertEqual((f["apiFulls"], f["apiAsks"]), (0, 0), "no folded tab was built or asked for while folded (the shown skeletons filled and the wire went quiet): %r" % f)
        u = r["unfolded"]
        self.assertEqual(u["header"], "0", "the header's click opened the section: %r" % u)
        self.assertGreater(u["idles"], f["idles"], "opening the section scheduled an idle pass: %r -> %r" % (f, u))
        self.assertGreater(u["needFull"], f["needFull"], "…and the prefetch asked: %r -> %r" % (f, u))
        self.assertEqual((u["firstAskWhy"], u["firstAskApi"]), ("prefetch", True), "…the first ask the prefetch's own, and it names a revealed api tab: %r" % u)
        # what the road proves is the event above (the first ask is the prefetch's, for a revealed tab), not the ABSENCE of a kernel
        # push in the window: that raced the pusher's cycle on a slow runner and reddened peers' CI (the repo rule: no timing claims,
        # 2026-09-15). pushesBeforeFirstAsk stays in the RESULT as a diagnostic, unasserted.
        self.assertEqual(r["unfoldedFilled"]["skel"], 0, "every tab filled once shown: %r" % r["unfoldedFilled"])
        self.assertEqual(r["unfoldedFilled"]["apiLoaded"], len(self.api_sids), "…the nine api tabs among them, shown and loaded in the strip: %r" % r["unfoldedFilled"])

    def test_only_the_chat_panes_dial_carries_the_term_after_a_restart_record(self):
        # round two, medium 2: the served dashboard's shell opens every pane; the term is the chat pane's alone
        r = self._result()
        dials = r["paneDials"]
        apps = sorted(set(re.search(r"app=([a-z]+)", d).group(1) for d in dials if re.search(r"app=([a-z]+)", d)))
        self.assertGreaterEqual(len(apps), 2, "the shell dialed more than one pane: %r" % dials)
        with_term = sorted(set(re.search(r"app=([a-z]+)", d).group(1) for d in dials if "skeleton=1" in d))
        self.assertIn("chat", apps, "the chat pane dialed: %r" % dials)
        self.assertEqual(with_term, ["chat"], "the term rides the chat pane's dial alone: %r" % dials)

    def test_lifting_the_filter_re_arms_the_idle_prefetch(self):
        # round two, medium 3 (renamed 2026-09-15: the road proves the prefetch's own ask for a revealed tab, not the absence of a push in a window)
        r = self._result()
        b, a = r["beforeReveal"], r["afterReveal"]
        self.assertEqual(b["skel"], 0, "the shown skeletons had filled before the reveal (a hidden tab has no strip element): %r" % b)
        self.assertGreaterEqual(a["skelAtReveal"], 1, "the revealed tabs appeared as skeletons, never built while hidden: %r" % a)
        self.assertGreater(a["idles"], b["idles"], "the reveal scheduled an idle pass: %r -> %r" % (b, a))
        self.assertGreater(a["needFull"], b["needFull"], "…and the prefetch asked for a revealed skeleton: %r -> %r" % (b, a))
        self.assertGreaterEqual(a["skelSids"], 1, "the revealed skeletons carry their sids in the strip: %r" % a)
        # the road's proof: the first ask is the prefetch's own AND names one of the revealed skeletons (the event), not the absence of a
        # kernel push in the window (that raced the pusher's cycle on a slow runner and reddened peers' CI; the repo rule forbids timing
        # claims, 2026-09-15). pushesBeforeFirstAsk stays in the RESULT as a diagnostic, unasserted.
        self.assertEqual((a["firstAskWhy"], a["firstAskRevealed"]), ("prefetch", True), "…the first ask the prefetch's own, for a revealed tab: %r" % a)
        self.assertEqual(r["revealFilled"]["skel"], 0, "every revealed skeleton filled: %r" % r["revealFilled"])

    def test_a_sibling_documents_section_open_re_arms_the_prefetch_here_too(self):
        # round three, medium 1: the tab-groups store's storage half re-arms like the CustomEvent half
        r = self._result()
        b, a = r["siblingBefore"], r["siblingAfter"]
        self.assertEqual(b["header"], "1", "the api section folded again on this page before the sibling opened it: %r" % b)
        self.assertEqual(b["apiAsks"], 0, "no folded tab asked for while folded: %r" % b)
        self.assertEqual(a["header"], "0", "the sibling's click opened the section here (the store's storage event repainted): %r" % a)
        self.assertGreater(a["idles"], b["idles"], "…and this page scheduled an idle pass: %r -> %r" % (b, a))
        self.assertGreater(a["needFull"], b["needFull"], "…and asked: %r -> %r" % (b, a))
        self.assertEqual((a["firstAskWhy"], a["firstAskApi"]), ("prefetch", True), "…the first ask the prefetch's own, and it names a revealed api tab: %r" % a)
        # the event above is the proof, not the ABSENCE of a kernel push in the window: that raced the pusher's cycle on a slow runner and
        # reddened peers' CI (the repo rule: no timing claims, 2026-09-15). pushesBeforeFirstAsk stays in the RESULT as a diagnostic, unasserted.
        self.assertEqual(r["siblingFilled"]["apiLoaded"], len(self.api_sids), "the nine api tabs shown and loaded: %r" % r["siblingFilled"])

    def test_the_outline_panes_dial_carries_the_capability_and_the_chat_panes_does_not(self):
        # road 11, the shell: the Outline's dial declares provrows=1 (the shim adds it for its app), the chat's dial carries the diet alone
        r = self._result()
        dials = r["paneDials"]
        by_app = {}
        for d in dials:
            m = re.search(r"app=([a-z]+)", d)
            if m:
                by_app.setdefault(m.group(1), []).append(d)
        self.assertIn("fleet", by_app, "the shell dialed the Outline pane: %r" % dials)
        self.assertTrue(all("&provrows=1" in d for d in by_app["fleet"]), "the Outline's dials carry the capability: %r" % by_app["fleet"])
        self.assertEqual(sorted(a for a, ds in by_app.items() if any("provrows=1" in d for d in ds)), ["fleet"], "no other pane's dial carries it: %r" % dials)
        self.assertTrue(all("skeleton=1" not in d for d in by_app["fleet"]), "the Outline dials no skeleton diet: %r" % by_app["fleet"])

    def test_with_the_outline_connected_the_gate_stays_on_and_the_pane_gets_a_provisional_row_per_skipped_tab(self):
        # road 11: the first frame
        r = self._result_outline()
        self.assertEqual(r["errors"], [], "no page error on either page")
        self.assertIn("&skeleton=1", r["chatStart"]["dial"] or "", "the chat dialed the diet: %r" % r["chatStart"])
        self.assertNotIn("provrows", r["chatStart"]["dial"] or "", "the chat's dial carries no Outline term")
        self.assertIn("&provrows=1", r["first"]["dial"] or "", "the Outline's dial declares the capability: %r" % r["first"]["dial"])
        sel, f = sid_of(SELECTED_I), r["first"]["feed"]
        self.assertIsNotNone(f, "the Outline received a feed frame with ledgers")
        self.assertEqual(f["n"], N_SESSIONS, "every session has a row: %r" % f["n"])
        self.assertEqual(sorted(f["prov"]), sorted(s for s in self.sids if s != sel), "all but the selected tab are provisional: %d rows" % len(f["prov"]))
        self.assertEqual(r["first"]["fullsAtFirst"], [sel], "the chat built its selected tab alone while the Outline read: %r" % r["first"]["fullsAtFirst"])
        self.assertGreaterEqual(r["first"]["perf"]["coldSkipped"], N_SESSIONS - 1, "/perf counts the cold skips: %r" % r["first"]["perf"])
        self.assertEqual(r["chatStart"]["skel"], N_SESSIONS - 1, "the strip holds the other twenty-six as skeletons: %r" % r["chatStart"])
        g = f["rows"][sid_of(GOAL_I)]
        self.assertTrue(g["provisional"] and g["provState"], "the store-backed row is provisional, its status too: %r" % g)
        self.assertEqual(g["tree"], ["index the notes", "write the search route"], "its goals come from the store alone: %r" % g)
        self.assertEqual(g["anchors"], [[None, None], [None, None]], "no anchors without the transcript: %r" % g["anchors"])
        self.assertEqual(g["keys"], ["archivedTops", "current", "tree"], "the pane's three ledger fields, nothing more: %r" % g["keys"])
        self.assertIsNone(g["current"], "current is blank until the tab is built")
        self.assertEqual(f["rows"][sid_of(MUTED_I)]["tree"], [], "a muted session's provisional row shows no goals: %r" % f["rows"][sid_of(MUTED_I)])
        self.assertFalse(f["rows"][sel]["provisional"], "the selected tab's row is the built one")
        memo = r["first"]["perf"]["memo"]
        self.assertIsNotNone(memo, "the memo reports under /perf memos.outlineProvisional")
        self.assertGreaterEqual(memo["miss"], 2, "the two provisional stores walked once each: %r" % memo)
        self.assertGreaterEqual(memo["bypass_empty"], N_SESSIONS - 3, "the storeless tabs bypass the walk: %r" % memo)
        # the memo's occupancy is read after the frame, not with it, and the pusher's cycle snapshots the reader set (a flagged Outline
        # connected) at its start: a cycle that began before the Outline registered evicts, at its attach, the entries the Outline's
        # connect push stored (CI at f58c85b1: miss 2, entries 0 at this read, then miss 4, hit 1, entries 1 by the click), and the next
        # cycle walks them again. So the claim is the eviction's INVARIANT, never more entries than cold store-backed tabs, against the
        # frame's own provisional set (the lab seeded GOAL_I and MUTED_I; the muted row's tree is emptied at the read, the entry stays)
        self.assertLessEqual(memo["entries"], len([x for x in (sid_of(GOAL_I), sid_of(MUTED_I)) if x in f["prov"]]),
                             "never an entry beyond the frame's cold store-backed tabs: %r" % memo)

    def test_the_outline_marks_a_provisional_session_lightly_and_withholds_its_jumps(self):
        # road 11: the DOM of the first frame
        r = self._result_outline()
        secs = {x["sid"]: x for x in r["first"]["dom"]["sections"]}
        g, sel = secs.get(sid_of(GOAL_I)), secs.get(sid_of(SELECTED_I))
        self.assertIsNotNone(g, "the store-backed session shows a section: %r" % r["first"]["dom"])
        self.assertTrue(g["prov"], "marked provisional: %r" % g)
        self.assertEqual(g["rows"], 2, "its two goals render: %r" % g)
        self.assertEqual((g["nav"], g["acts"]), (0, 0), "no pointer class and no jump action on its mark, text or time: %r" % g)
        self.assertEqual(g["nameUnderline"], "dashed", "the light mark under the name: %r" % g)
        self.assertIn("its transcript has not been loaded since the restart", g["title"] or "", "the head says why: %r" % g["title"])
        self.assertIsNotNone(sel, "the built session shows a section too")
        self.assertFalse(sel["prov"]); self.assertEqual(sel["rows"], 2)
        self.assertGreaterEqual(sel["acts"], 2, "the built row's mark and text jump: %r" % sel)
        self.assertEqual(sel["title"], "Open this session")
        m = secs.get(sid_of(MUTED_I))
        self.assertTrue(m is None or m["rows"] == 0, "the muted session shows no goal row: %r" % m)

    def test_a_click_on_a_second_tab_builds_it_and_its_row_loses_the_mark_on_the_next_frame(self):
        r = self._result_outline()
        a, g = r["afterClick"], sid_of(GOAL_I)
        self.assertEqual(a["fulls"], [sid_of(SELECTED_I), g], "the click built the second tab and nothing else: %r" % a["fulls"])
        self.assertGreaterEqual(a["heldStill"], 1, "the chat's idle prefetch stayed held: the build was the click's: %r" % a["heldStill"])
        row = a["feed"]["rows"][g]
        self.assertFalse(row["provisional"], "the built row replaced the provisional one: %r" % row)
        self.assertEqual(row["tree"], ["index the notes", "write the search route"], "the same goals, now the build's: %r" % row)
        self.assertEqual(sorted(a["feed"]["prov"]), sorted(s for s in self.sids if s not in (sid_of(SELECTED_I), g)), "the other twenty-five stay provisional")
        sec = {x["sid"]: x for x in a["dom"]["sections"]}[g]
        self.assertFalse(sec["prov"], "the section lost the light mark: %r" % sec)
        self.assertGreaterEqual(sec["acts"], 2, "and its jumps are back: %r" % sec)
        # the memo's entries, not its hits: a hit needs a cycle whose store and cleared keys equal the entry's, and a key can move
        # once after a boot (CI at 61bf4bda read miss 3, hit 0 here and hit 1 later); hit and miss are pinned by the unit test
        # (tests/test_outline_provisional_rows.py test_06), the lab pins the eviction rule: the built tab's entry went, the cold one stays
        self.assertLessEqual(a["perf"]["memo"]["entries"], len([x for x in (sid_of(GOAL_I), sid_of(MUTED_I)) if x in a["feed"]["prov"]]),
                             "the clicked tab, built now, holds no entry; at most the muted cold tab's remains: %r" % a["perf"]["memo"])
        self.assertGreaterEqual(a["perf"]["memo"]["miss"], 2, "both store-backed tabs were walked: %r" % a["perf"]["memo"])

    def test_an_unflagged_outline_socket_makes_the_kernel_build_every_tab(self):
        r = self._result_outline()
        u = r["unflagged"]
        self.assertNotIn("provrows", u["rawDial"] or "", "the raw socket dialed without the flag: %r" % u["rawDial"])
        self.assertGreaterEqual(u["perf"]["built"] - r["afterClick"]["perf"]["built"], N_SESSIONS - 2, "the kernel built the remaining tabs for the older pane: %r then %r" % (r["afterClick"]["perf"], u["perf"]))
        self.assertGreaterEqual(u["heldStill"], 1, "with the chat's prefetch still held: the builds were the kernel's: %r" % u["heldStill"])
        self.assertEqual(u["feed"]["prov"], [], "and no row is provisional any more: %r" % u["feed"]["prov"])
        self.assertEqual(u["perf"]["memo"]["entries"], 0, "every tab built, no provisional row left: every entry went at the attach that built them: %r" % u["perf"]["memo"])
        self.assertEqual(u["fullsDistinct"], 2, "the chat page, holding its skeletons, was handed no full frame it had not asked for: %r" % u["fullsDistinct"])

    def test_the_measurement_is_reported(self):
        r = self._result()
        m = {"fresh": {"firstRow": r["fresh"]["paint"]["firstRow"], "strip27": r["fresh"]["paint"]["strip27"], "allBuilt": r["fresh"]["allBuilt"], "skeletonTabs": r["fresh"]["paint"]["skelMax"]},
             "restart": {"firstRow": r["restart"]["paint"]["firstRow"], "strip27": r["restart"]["paint"]["strip27"], "allBuilt": r["spread"]["allBuilt"], "skeletonTabs": r["restart"]["paint"]["skelMax"]},
             "hiddenRoad": {"start": r["hidden"]["start"], "skelVisibleAfterWait": r["hidden"]["skelVisibleAfterWait"], "revealed": r["revealed"]}}
        print("MEASURE:", json.dumps(m), file=sys.stderr)
        for k in ("fresh", "restart"):
            self.assertIsNotNone(m[k]["firstRow"], "%s: the selected tab painted a row" % k)
            self.assertIsNotNone(m[k]["strip27"], "%s: the strip painted twenty-seven tabs" % k)


if __name__ == "__main__":
    unittest.main()
