"""The chat page's NEEDS YOU BOX (plans/needs-you.md, phase three): a hermetic kernel over one synthetic live session in the
notes-api demo world, the real /chat page served from a copy of the built bundle, driven by Playwright, the feed pane closed.
The session's goal store holds three judge questions (diary block events in the fold's shape) and a fourth, working focus goal;
the transcript ends on an API error record only the user can clear (isApiErrorMessage, "prompt is too long"), so the fourth
card is a HARD STOP the kernel floors with a live-block object (state apiError) and the tab wears the red Blocked ring; a message
from a DIRECTED peer is held under STATE/postal/quarantine before boot and becomes a needs-you notice card at the first build.
The box lists the three questions (Reply, Clear) and the held message (Approve, Deny) under a "Needs you · 4" header, collapsed to that header by default and opened in steps,
wears the Needs you token on its edge, and lists no row for the hard stop. Clear
takes its row off the box with the next frame, on the first question and the second alike (the Continue button left the row on
2026-09-23; its offer and wire stay); Reply points the composer at the card (the chip with the card's title) and the row leaves
once the typed reply is filed. The header is a button the keyboard reaches (Shift+Tab from the composer), Enter opens it and Tab
lands on the first row's Reply; the level is the session's own (api's box at 0 while web's stands at 2) and a reload of the page
starts collapsed; a judges' credential row floors api's box at the items; in the shell the header's own gear opens the settings
at the Boxes section. The gear's Needs you box switch (a romp:settings save, through the settings page's own row, the card
opened) hides the box and leaves the ring; back on, the box returns at the level it stood.
Synthetic only: placeholder ids, invented text, hostname TESTHOST.

After the 2026-09-23 default flip the badge is the default; this lab opts into RING mode (it seeds tabStateBadge:false) because its subject is the ring, and the dot's default is covered by the badge lab (test_tab_badge_browser) and the gear-preview test (test 5)."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
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

SID = "cccccccc-1111-2222-3333-444444444444"
API = "dddddddd-1111-2222-3333-444444444444"     # a second session with a question and NO hard stop: its tab wears the Needs you ring
API_Q = "which port should the api listen on in the fixtures?"
BRIEF = "the suite targets Postgres in CI and SQLite locally; which should the fixtures load into?"
BACKGROUND = "The suite loads its fixtures through two loaders, one per database, and the CI job runs both in an order nobody wrote down."   # the distiller's re-orientation paragraph, the card's Background section
TWO_PARA_BRIEF = "The fixtures load into one database and the suite has two.\n\nThe CI job runs both loaders, one per database, in an order nobody wrote down."   # a multi-item brief: one paragraph per part (briefParts), the second part without an event time
LONG_BRIEF = " ".join("The fixtures load into one database and the suite has two: Postgres in CI and SQLite on a laptop, with different "
                      "date handling, so a fixture written for one fails on the other." for _ in range(30))   # past four lines at any width the lab runs at (CI's browser fit five repetitions in four; the round-fifteen CI red)
MID = "aaaaaaaa-bbbb-cccc-dddd-000000000301"
TOKEN_RGB = "rgb(217, 70, 239)"          # --st-needs-bg, the dark theme (styles.css)
QUESTIONS = ["which database does the suite target?", "should the parser keep the legacy header?", "is the fixtures directory versioned?"]

DRIVER = r"""
import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(process.env.EXT_PKG);
const { chromium } = require("playwright");
const cfg = JSON.parse(fs.readFileSync(process.env.CFG, "utf8"));
let browser;
try { browser = await chromium.launch(); }
catch (e) { console.error("browser-launch-failed: " + e); process.exit(3); }
const page = await browser.newPage({ viewport: { width: 1100, height: 760 } });
await page.addInitScript(() => { try { const s = JSON.parse(localStorage.getItem("romp:settings") || "{}"); s.tabStateBadge = false; localStorage.setItem("romp:settings", JSON.stringify(s)); } catch (e) {} });   // RING mode: this lab's subject is the ring, not the badge (the 2026-09-23 default flip; the dot is the badge lab's + test 5's)
await page.addInitScript((sid) => { window.__frameN = 0; window.__injN = 0; window.__lastStatus = null; window.addEventListener("message", (e) => { const m = e.data; if (!m || typeof m !== "object" || typeof m.type !== "string") return; if (e.source === window) { window.__injN++; return; } window.__frameN++;
  const rows = m.status && Array.isArray(m.status.notices) ? m.status.notices : null;   // only a frame that carries the box's rows: an early frame without them would empty the box when posted back
  if (m.id === sid && rows && rows.length && (m.type === "status" || m.type === "session" || m.type === "chatTail")) window.__lastStatus = { type: "status", id: sid, status: m.status }; }, true); }, cfg.sid);   // the kernel's frames counted and the session's latest status (the box's rows ride the chatTail frames' status here) kept, so a scene can post a status frame of its own that differs in one field and wait for the page to handle it, never on a delay
const errors = []; page.on("pageerror", (e) => errors.push(String(e).slice(0, 300)));
const out = { errors };
const mark = () => process.stdout.write("PARTIAL:" + JSON.stringify(out) + "\n");   // the record so far, after every scene: what a run that hits the driver's budget still reports
const rowSel = (id) => '#notices .ntc-row[data-item="' + id + '"]';
// a row's LINE (read as `.ntc-secs > .fask-distill` or `.ntc-body` below): on a goal row the card's distill line (the brief or the takeaway), drawn by the card's
// own builder since the box content round (plans/needs-you.md); on a notice row and on the credential row the kernel's markdown body, as before. A page
// before the round has no distill element on the row, so the reads fall to the body there
const readBox = () => page.evaluate(() => {
  const box = document.getElementById("notices"); const cs = box ? getComputedStyle(box) : null;
  const rows = box ? Array.from(box.querySelectorAll(".ntc-row")) : [];
  const tab = document.querySelector('#tabs .tab[data-id]');
  const tabs = Object.fromEntries(Array.from(document.querySelectorAll('#tabs .tab[data-id]')).map((t) => [t.getAttribute("data-id"), t.className]));   // every tab's classes by sid: the rings
  const vis = (el) => !!el && getComputedStyle(el).display !== "none";
  const level = box ? ["ntc-l0", "ntc-l1", "ntc-l2"].findIndex((c) => box.classList.contains(c)) : null;   // the box's level class (-1: none)
  return { shown: !!box && box.style.display !== "none" && !!cs && cs.display !== "none", border: cs ? cs.borderTopColor : null, borderLeft: cs ? cs.borderLeftWidth : null,
           head: box ? ((box.querySelector(".ntc-head .ntc-label") || {}).textContent || null) : null,
           dot: box && box.querySelector(".ntc-head .ntc-dot") ? getComputedStyle(box.querySelector(".ntc-head .ntc-dot")).backgroundColor : null,
           level, caret: box && box.querySelector(".ntc-head .ntc-caret") ? box.querySelector(".ntc-head .ntc-caret").textContent : null,
           head2: (() => { const h = box && box.querySelector(".ntc-head"); return h ? { role: h.getAttribute("role"), tabIndex: h.tabIndex, expanded: h.getAttribute("aria-expanded"), title: h.title, border: getComputedStyle(h.closest(".ntc-bar") || h).borderBottomColor, caretHidden: (h.querySelector(".ntc-caret") || {}).getAttribute ? h.querySelector(".ntc-caret").getAttribute("aria-hidden") : null, gear: !!(h.closest(".ntc-bar") || h).querySelector(".ntc-gear") } : null; })(),   // the header as a control: its role, its tab stop, its expanded state and title, its rule's colour, the caret's aria, the gear
           laidTitles: rows.map((r) => { const t = r.querySelector(".ntc-title"); return !!t && t.getBoundingClientRect().height > 0; }),   // LAID OUT, by rect: a hidden ancestor keeps a child's computed display and its textContent (the second contributor's post-merge review of PR 2093)
           laidButtons: rows.map((r) => Array.from(r.querySelectorAll(".ntc-actions button")).filter((b) => b.getBoundingClientRect().height > 0).length),
           headVisible: box ? vis(box.querySelector(".ntc-head")) : null, rowsVisible: rows.map((r) => vis(r)), bodiesVisible: rows.map((r) => vis((r.querySelector(".ntc-secs > .fask-distill") || r.querySelector(".ntc-body")))),
           theme: document.body.classList.contains("theme-light") ? "light" : "dark",
           rows: rows.map((r) => ({ id: r.getAttribute("data-item"), title: (r.querySelector(".ntc-title") || {}).textContent, body: ((r.querySelector(".ntc-secs > .fask-distill") || r.querySelector(".ntc-body")) || {}).textContent,
                                   buttons: Array.from(r.querySelectorAll(".ntc-actions button")).map((b) => b.textContent), disabled: Array.from(r.querySelectorAll(".ntc-actions button")).map((b) => b.disabled) })),
           tabClasses: tab ? tab.className : null, tabs };
});
const waitRows = (n, ms) => page.waitForFunction((n) => document.querySelectorAll("#notices .ntc-row").length === n, n, { timeout: ms }).then(() => true).catch(() => false);
await page.goto(cfg.chat);
await page.waitForSelector("#tabs .tab", { timeout: 30000 }).catch(() => {});
// 1. the box: four rows (the three questions and the held message), the header, the token edge, no row for the hard stop, the red ring on the tab
out.fourRows = await waitRows(4, 60000);
out.first = await readBox();
// 0. COLLAPSED BY DEFAULT and opened in steps (the user 2026-09-23): the header line alone, one click the items (titles and buttons), a second the
// full context (the background under each title); read in both themes at each level (the theme is the body's class, as the colour lab sets it)
const setTheme = (t) => page.evaluate((t) => document.body.classList.toggle("theme-light", t === "light"), t);
const foldTo = (level) => openNeedsBox(page, level);   // the shared fold helper (test_ship_reship_served NEEDS_BOX_OPEN_JS): a click per step, each waited on the level class, fail-soft at the base
out.levels = {};
for (const t of ["dark", "light"]) {
  await setTheme(t); await foldTo(0); out.levels[t + "0"] = await readBox();
  await foldTo(1); out.levels[t + "1"] = await readBox();
  await foldTo(2); out.levels[t + "2"] = await readBox();
}
await setTheme("dark");
// 0a. THE CLICK TARGET (the second contributor's review of PR 2120: with the padding on the bar and the fold action on the header alone, the bar's
// edges went dead): at level 0 a click at the bar's top-left corner (left + 3, top + 2), inside the header's padding, opens the items
await foldTo(0);
{
  const b = await page.evaluate(() => { const el = document.querySelector("#notices .ntc-bar") || document.querySelector("#notices .ntc-head"); const r = el.getBoundingClientRect(); return { left: r.left, top: r.top, right: r.right, bottom: r.bottom }; });   // the bar, or the bare header on a page without it (the base)
  await page.mouse.click(b.left + 3, b.top + 2);
  out.edgeClick = { opened: await page.waitForFunction(() => document.getElementById("notices").classList.contains("ntc-l1"), null, { timeout: 5000 }).then(() => true).catch((e) => { if (e.name !== "TimeoutError") throw e; return false; }), bar: b };
  out.edgeClick.cursor = await page.evaluate(() => { const el = document.querySelector("#notices .ntc-bar"); return el ? getComputedStyle(el).cursor : null; });   // null on a page without the bar (the base)
}
// 0b. THE KEYBOARD ROUTE (the second contributor's post-merge review of PR 2093: level 0 hid every row and the header was a plain div, so Tab and
// Shift+Tab never stopped inside the box). By ORDER, not press count: Shift+Tab from the composer until focus enters #notices, the header;
// Enter opens the items and the expanded state says so; Tab lands on the first row's Reply
await foldTo(0);
const active = () => page.evaluate(() => { const a = document.activeElement; return a ? { inBox: !!a.closest("#notices"), head: a.classList.contains("ntc-head"), cls: a.className, tag: a.tagName, act: a.dataset ? a.dataset.act || null : null, text: (a.textContent || "").trim().slice(0, 40) } : null; });   // head by class membership: the delegate's click flash (romp-acted) rides the class list
await page.focus("#composer-input");
out.keys = { entered: false, presses: 0 };
for (let i = 0; i < 40; i++) {   // loop-ok: bounded; the walk stops when focus enters the box
  await page.keyboard.press("Shift+Tab"); out.keys.presses = i + 1;
  const a = await active(); if (a && a.inBox) { out.keys.entered = true; out.keys.landed = a; break; }
}
if (out.keys.entered) {
  out.keys.headName = await page.locator("#notices .ntc-head").ariaSnapshot().catch((e) => "snapshot failed: " + e);   // the computed name on the standalone page too
  await page.keyboard.press("Enter");
  out.keys.opened = await page.waitForFunction(() => document.getElementById("notices").classList.contains("ntc-l1"), null, { timeout: 5000 }).then(() => true).catch(() => false);
  out.keys.afterEnter = await readBox(); out.keys.focusAfterEnter = await active();
  await page.keyboard.press("Tab"); out.keys.afterTab = await active();
  await page.keyboard.press("Shift+Tab");   // back on the header: Space advances the level too (the box arc's round three: only a regex pinned it)
  await page.keyboard.press(" ");
  out.keys.spaced = await page.waitForFunction(() => document.getElementById("notices").classList.contains("ntc-l2"), null, { timeout: 5000 }).then(() => true).catch(() => false);
  out.keys.focusAfterSpace = await active();
}
mark();
// 0c. THE LEVEL IS THE SESSION'S OWN (the same review: a mutant copying the last level to an unseen session passed the source pin): web at
// the full context, api's box (one question) reads collapsed, and back on web the level stands; the rows are waited for as ATTACHED, since
// level 0 hides them
await foldTo(2);
const switchTo = async (sid, n) => { await page.click('#tabs .tab[data-id="' + sid + '"]'); await page.waitForFunction((n) => document.querySelectorAll("#notices .ntc-row").length === n, n, { timeout: 15000 }).catch(() => {}); return readBox(); };
out.perSession = { api: await switchTo(cfg.api, 1), back: await switchTo(cfg.sid, 4) };
mark();
// 0d. A CREDENTIAL ROW FLOORS THE BOX AT THE ITEMS (the same review: a refused judge credential hid at level 0 under a header identical to a
// question's): the judge-auth-down latch seeded for api, whose one card becomes the "Fix credential…" row; api's box shows the items with no
// click, the header's click goes to the full context and back to the items, never to the header line, while the row shows; web is untouched
fs.writeFileSync(cfg.judgeAuth, JSON.stringify({ [cfg.api]: { t: Math.floor(Date.now() / 1000) - 60, mode: "key", note: "the API key is being refused" } }));
fs.utimesSync(cfg.order, new Date(), new Date());
await page.click('#tabs .tab[data-id="' + cfg.api + '"]');
out.floor = { row: await page.waitForSelector('#notices .ntc-row button[data-act="ntc-fix"]', { state: "attached", timeout: 60000 }).then(() => true).catch(() => false) };
out.floor.shown = await readBox();
await page.click("#notices .ntc-head"); out.floor.up = await page.waitForFunction(() => document.getElementById("notices").classList.contains("ntc-l2"), null, { timeout: 5000 }).then(() => true).catch(() => false);
out.floor.atTwo = await readBox();   // the full context at the floor: the next click descends to the items, and the title must say so
await page.click("#notices .ntc-head"); out.floor.down = await page.waitForFunction(() => document.getElementById("notices").classList.contains("ntc-l1"), null, { timeout: 5000 }).then(() => true).catch(() => false);
out.floor.after = await readBox();
// the floor's RELEASE (the box arc's round three): the seed removed, the credential row leaves, and the level stays at the items (the click stores
// the level after the shown one, never below the floor, so two clicks from the items keep 1 stored; before: 0 stored, the box dropped to its header line)
fs.unlinkSync(cfg.judgeAuth); fs.utimesSync(cfg.order, new Date(), new Date());
out.floor.released = await page.waitForSelector('#notices .ntc-row button[data-act="ntc-fix"]', { state: "detached", timeout: 60000 }).then(() => true).catch(() => false);
out.floor.afterRelease = await readBox();
out.floor.reusedRow = await page.evaluate(() => { const r = document.querySelector("#notices .ntc-row"); const b = r && r.querySelector(".ntc-body"); const d = r && r.querySelector(".ntc-secs > .fask-distill");
  return r ? { fault: r.classList.contains("ntc-fault"), bodyLaid: !!b && b.getBoundingClientRect().height > 0, lineLaid: !!d && d.getBoundingClientRect().height > 0, hasBody: !!b && (b.textContent || "").trim().length > 0 } : null; });   // the row reused for the plain question: no fault class, the markdown body hidden again at the items, the card's line in its place (the box content round)
out.floor.web = await switchTo(cfg.sid, 4);
await foldTo(2);   // the rest of the scenes read the bodies and their disclosures: the full context open
mark();
// the hard stop as the feed pane shows it from the same kernel's pushed frame: the focus goal's card under Needs you with the on-you API error badge
const feed = await browser.newPage({ viewport: { width: 1400, height: 900 } });
await feed.goto(cfg.feed);
const g4Sel = '[data-key="a:' + cfg.g4 + '"]';
out.hardStop = await feed.waitForSelector(g4Sel, { state: "attached", timeout: 60000 }).then(() => feed.evaluate((sel) => { const c = document.querySelector(sel);
  const badge = c ? c.querySelector(".fask-api") : null; const badges = c ? Array.from(c.querySelectorAll("a, span")).map((x) => x.textContent || "").filter((t) => t.startsWith("⚠")) : [];
  return { col: c ? c.parentElement.id : null, badges }; }, g4Sel)).catch(() => ({ col: null, badges: [] }));
mark();
await feed.close();
// 1b. a brief lands on the first question's card (the judge's blockSummary, written to the store): the row's body follows within the
// next frames with no gesture (the second review of PR 1967: the box repainted only when a row came or went)
// the kernel's own build event for a store write (the disclosure scene's second CI red, 2026-09-22: sixty seconds with no frame and no word
// from the kernel): GET /feed.json serves the pusher's warmed feed while a pane is attached, so its buildId advancing past the one read
// before the write, with the card's brief as written, is the kernel's word that its feed rebuilt over the new store; the box row follows by
// one chat build (_feed_needs_rows, the chat signature's `notices`). The order touch moves a file the view signature stats, so the rebuild
// follows at once rather than at the signature's 5 s clock bucket (the second contributor's read of PR 2031: the touch makes the rebuild
// prompt, it does not enable it). A miss records the kernel's pusher and build counters (GET /perf) beside the brief the kernel's last feed
// carries, so the failure names the link that did not fire: the write unseen, the feed not rebuilt, or the frame not shipped.
// The wait is polled from the DRIVER: an async predicate under page.waitForFunction resolves at once, since the Promise it returns is truthy
// (Playwright fulfils on the first truthy return; the second contributor's read of PR 2031: every scene's wait returned at once with False)
const kernelFeed = () => page.evaluate(async (u) => { try { const r = await fetch(u); return r.ok ? await r.json() : null; } catch (e) { return null; } }, cfg.feedJson);
const kernelPerf = () => page.evaluate(async (u) => { try { const r = await fetch(u); const p = await r.json(); return { pusher: p.pusher, builds: p.builds, stages_ms: p.stages_ms }; } catch (e) { return String(e); } }, cfg.perf);
const briefOf = (f, id) => (((f || {}).asks || []).find((a) => a.itemId === id) || {}).blockSummary;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const feedBuiltPast = async (floor, id, brief, ms) => {   // the kernel's feed build past `floor` carrying `brief` on the card: its build id, else null at the deadline
  if (typeof floor !== "number") return null;   // a null floor is the pre-write read's own miss (the floor pin names it): no poll, no counters pointing at the kernel (the second contributor's read of PR 2038)
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {   // loop-ok: bounded by the deadline, one fetch per 500 ms (the cadence the polling option asked for)
    const f = await kernelFeed();
    if (f && typeof f.buildId === "number" && typeof floor === "number" && f.buildId > floor && briefOf(f, id) === brief) return f.buildId;
    await sleep(500);
  }
  return null;
};
const writeStore = async (mutate) => {   // the feed build id before the write (null when that read fails: its own miss, never a floor of -1), the write (seq bumped), the order touch
  // The write is a PUBLICATION the kernel's own writers must see: `rev` advances as save_goals advances it, so a judge pass whose store predates
  // this write rebases onto it (the kernel's compare-and-swap keys on rev and, since the CI red of 2026-09-23, on the file's identity; before,
  // an in-place rewrite that left rev alone was invisible to a save holding an older base, and the pass's save erased the node just written)
  const b0 = ((await kernelFeed()) || {}).buildId; const st = JSON.parse(fs.readFileSync(cfg.store, "utf8")); mutate(st); st.seq = (st.seq || 0) + 1; st.rev = (st.rev || 0) + 1;
  fs.writeFileSync(cfg.store, JSON.stringify(st));
  fs.utimesSync(cfg.order, new Date(), new Date()); return typeof b0 === "number" ? b0 : null;
};
const onMiss = async (o) => {   // the counters, the kernel's own view of the card, and the FILE: a write the kernel published over reads as a node gone and rev moved
  o.perf = await kernelPerf(); o.kernelBrief = briefOf(await kernelFeed(), o.id);
  try { const st = JSON.parse(fs.readFileSync(cfg.store, "utf8")); o.store = { rev: st.rev, seq: st.seq, hasNode: !!(st.nodes || {})[o.id], brief: ((st.nodes || {})[o.id] || {}).blockSummary }; } catch (e) { o.store = String(e); }
  return o;
};
const builtRecord = async (id, floor, brief) => { const o = { id, floor, built: await feedBuiltPast(floor, id, brief, 90000) }; if (o.built === null) await onMiss(o); return o; };   // { id, floor, built }, the counters on a miss
// a brief is a FAMILY field (the store's distill families): the rebase adopts a family as a unit by its stamp, so an in-place edit of a
// brief stamps its family (briefedMt, as every kernel writer of a brief does) or a judge pass's save keeps its own (2026-09-23)
const briefNow = () => Math.floor(Date.now() / 1000);
const w1 = await writeStore((st) => { st.nodes[cfg.g1].blockSummary = cfg.brief; st.nodes[cfg.g1].briefedMt = briefNow(); });
out.brief = await builtRecord(cfg.g1, w1, cfg.brief);
out.brief.landed = await page.waitForFunction((a) => { const r = document.querySelector(a.sel); const b = r && (r.querySelector(".ntc-secs > .fask-distill") || r.querySelector(".ntc-body")); return !!b && (b.textContent || "").trim() === a.brief; }, { sel: rowSel(cfg.g1), brief: cfg.brief }, { timeout: 30000 }).then(() => true).catch(() => false);   // the row follows the kernel's word by one chat build
if (!out.brief.landed) await onMiss(out.brief);
mark();
out.brief.box = await readBox();
// 1c. a brief past the four-line clamp gets a disclosure on its row (the second contributor's review of PR 1967): the More button shows
// only once the body overflows, opens the row (the clamp lifted, the whole brief on screen), reads Less, and folds the row back
const w2 = await writeStore((st) => { st.nodes[cfg.g1].blockSummary = cfg.longBrief; st.nodes[cfg.g1].briefedMt = briefNow() + 1; });
const moreSel = rowSel(cfg.g1) + " .ntc-more";
// held on the kernel's build event, then the page's own events (the round-fifteen CI red read too early; the second red saw no frame for sixty
// seconds with no word from the kernel): the feed rebuilt past the write with the brief, the body carries it, its layout clips it, then the button
const landedAt = (sel, brief) => page.waitForFunction((a) => { const r = document.querySelector(a.sel); const b = r && (r.querySelector(".ntc-secs > .fask-distill") || r.querySelector(".ntc-body")); return !!b && (b.textContent || "").trim() === a.brief; }, { sel, brief }, { timeout: 30000 }).then(() => true).catch(() => false);
const clippedAt = (sel) => page.waitForFunction((s) => { const r = document.querySelector(s); const b = r && (r.querySelector(".ntc-secs > .fask-distill") || r.querySelector(".ntc-body")); return !!b && b.scrollHeight > b.clientHeight + 1; }, sel, { timeout: 15000 }).then(() => true).catch(() => false);
out.more = await builtRecord(cfg.g1, w2, cfg.longBrief);
out.more.landed = await landedAt(rowSel(cfg.g1), cfg.longBrief); if (!out.more.landed) await onMiss(out.more);
out.more.clipped = await clippedAt(rowSel(cfg.g1));
out.more.shown = await page.waitForSelector(moreSel, { timeout: 15000 }).then(() => true).catch(() => false);
out.more.before = await page.evaluate((s) => { const r = document.querySelector(s); const b = r && (r.querySelector(".ntc-secs > .fask-distill") || r.querySelector(".ntc-body")); const m = r && r.querySelector(".ntc-more");
  return b ? { open: r.classList.contains("ntc-open"), clamp: getComputedStyle(b).webkitLineClamp, clipped: b.scrollHeight > b.clientHeight + 1, label: m ? m.textContent : null, chars: (b.textContent || "").length, width: b.clientWidth } : null; }, rowSel(cfg.g1));
await page.click(moreSel).catch(() => {});
out.more.open = await page.waitForFunction((s) => { const r = document.querySelector(s); return !!r && r.classList.contains("ntc-open"); }, rowSel(cfg.g1), { timeout: 10000 }).then(() => true).catch(() => false);
out.more.after = await page.evaluate((s) => { const r = document.querySelector(s); const b = r && (r.querySelector(".ntc-secs > .fask-distill") || r.querySelector(".ntc-body")); const m = r && r.querySelector(".ntc-more");
  return b ? { clamp: getComputedStyle(b).webkitLineClamp, clipped: b.scrollHeight > b.clientHeight + 1, label: m ? m.textContent : null, text: (b.textContent || "").trim() } : null; }, rowSel(cfg.g1));
await page.click(moreSel).catch(() => {});
out.more.closed = await page.waitForFunction((s) => { const r = document.querySelector(s); return !!r && !r.classList.contains("ntc-open"); }, rowSel(cfg.g1), { timeout: 10000 }).then(() => true).catch(() => false);
out.more.box = await readBox();
mark();
// 2a. a Clear the clears log REFUSES (the log made read-only): the dialog says nothing changed, the row stays and its buttons let go
fs.chmodSync(cfg.ledger, 0o444);
await page.click(rowSel(cfg.g3) + ' [data-act="ntc-clear"]');
out.refused = { dialog: await page.waitForSelector("#confirm", { timeout: 30000 }).then(() => page.evaluate(() => (document.getElementById("confirm") || {}).textContent || "")).catch(() => null) };
out.refused.rearmed = await page.waitForFunction((s) => { const r = document.querySelector(s); return !!r && Array.from(r.querySelectorAll(".ntc-actions button")).every((b) => !b.disabled); }, rowSel(cfg.g3), { timeout: 30000 }).then(() => true).catch(() => false);
out.refused.box = await readBox();
out.refused.rowErr = await page.evaluate((s) => { const r = document.querySelector(s); const e = r && r.querySelector(".ntc-err"); return e && e.style.display !== "none" ? e.textContent : null; }, rowSel(cfg.g3));
await page.evaluate(() => { const b = Array.from(document.querySelectorAll("#confirm button")).find((x) => /Dismiss/.test(x.textContent || "")); if (b) b.click(); });
await page.waitForSelector("#confirm", { state: "detached", timeout: 10000 }).catch(() => {});
fs.chmodSync(cfg.ledger, 0o644);
// 2a'. THE SIGNATURE WITHOUT THE CONTINUE FLAG, executed (the box arc's round three): the session's latest kernel status frame, with every
// row's Continue flag flipped and nothing else, is posted to the page the way the kernel's socket frames arrive (a window message; the
// background lab drives its box the same way); no liveness changes and nothing is read in the composer; the wait is on the page HANDLING the
// posted frame (the injected-frame count), never a delay. The refused row's line and its re-armed buttons must survive that frame. The flip
// back posts the kernel's latest status UNMODIFIED (the round-two review: reposting the flipped copy left the later scenes on flipped flags)
const errRow = () => page.evaluate((s) => { const r = document.querySelector(s); const e = r && r.querySelector(".ntc-err"); return { err: e && e.style.display !== "none" ? e.textContent : null, buttons: r ? Array.from(r.querySelectorAll(".ntc-actions button")).map((b) => [b.textContent, b.disabled]) : null, injected: window.__injN, haveStatus: !!window.__lastStatus, cont: window.__lastStatus ? (window.__lastStatus.status.notices || []).map((n) => !!n.cont) : null }; }, rowSel(cfg.g3));
const postStatus = async (flip) => {   // the kernel's latest status with the rows, the Continue flags flipped when `flip`, else as the kernel sent them
  const n0 = await page.evaluate(() => window.__injN);
  const posted = await page.evaluate((flip) => { const st = window.__lastStatus; if (!st) return false;
    const shown = Array.from(document.querySelectorAll("#notices .ntc-row")).map((r) => r.dataset.item); const ids = (st.status.notices || []).map((n) => n.itemId);
    if (shown.length !== ids.length || shown.some((id) => !ids.includes(id))) return "stale:" + JSON.stringify({ shown, ids });   // the frame must list the rows the box shows
    const copy = JSON.parse(JSON.stringify(st)); if (flip) copy.status.notices = copy.status.notices.map((n) => ({ ...n, cont: !n.cont })); window.__lastInjected = copy; window.postMessage(copy, "*"); return true; }, flip);
  if (posted !== true) return { posted, handled: false };
  const handled = await page.waitForFunction((n) => window.__injN > n, n0, { timeout: 15000 }).then(() => true).catch((e) => { if (e.name !== "TimeoutError") throw e; return false; });
  return { posted, handled };
};
const flagsOf = (key) => page.evaluate((k) => { const st = window[k]; return st ? (st.status.notices || []).map((n) => !!n.cont) : null; }, key);
out.sigFlip = { before: await errRow() };
out.sigFlip.flip = await postStatus(true); out.sigFlip.flippedFlags = await flagsOf("__lastInjected");
out.sigFlip.after = await errRow();
out.sigFlip.flipBack = await postStatus(false); out.sigFlip.restoredFlags = await flagsOf("__lastInjected"); out.sigFlip.kernelFlags = await flagsOf("__lastStatus");
out.sigFlip.restored = await errRow();
mark();
// 2. Clear on the third question: the card's own askClear wire; the row leaves with the next frame
await page.click(rowSel(cfg.g3) + ' [data-act="ntc-clear"]');
out.clearLatched = await page.evaluate((s) => { const r = document.querySelector(s); return r ? Array.from(r.querySelectorAll("button")).every((b) => b.disabled) : null; }, rowSel(cfg.g3));
out.afterClear = { left: await page.waitForFunction((s) => !document.querySelector(s), rowSel(cfg.g3), { timeout: 60000 }).then(() => true).catch(() => false) };
out.afterClear.box = await readBox();
mark();
// 3. Continue is NOT offered on the row (the user 2026-09-23: Reply and Clear only for now; the stored offer and its wire stay for a later
//    return): the second question shows Reply and Clear alone, and its Clear takes the row off like the first's
out.secondButtons = await page.evaluate((s) => { const r = document.querySelector(s); return r ? Array.from(r.querySelectorAll(".ntc-actions button")).map((b) => b.textContent) : null; }, rowSel(cfg.g2));
out.secondContAct = await page.evaluate((s) => !!document.querySelector(s + ' [data-act="ntc-cont"]'), rowSel(cfg.g2));
await page.click(rowSel(cfg.g2) + ' [data-act="ntc-clear"]');
out.secondLatched = await page.evaluate((s) => { const r = document.querySelector(s); return r ? Array.from(r.querySelectorAll("button")).every((b) => b.disabled) : null; }, rowSel(cfg.g2));
out.afterSecond = { left: await page.waitForFunction((s) => !document.querySelector(s), rowSel(cfg.g2), { timeout: 60000 }).then(() => true).catch(() => false) };
out.afterSecond.box = await readBox();
mark();
// 4. Reply on the first question: the composer takes the card (the chip with its title); the typed reply is a follow-up on the card and the row leaves once filed
await page.click(rowSel(cfg.g1) + ' [data-act="ntc-reply"]');
out.chip = await page.waitForFunction(() => { const c = document.querySelector("#composer .composer-chip .composer-chip-label"); return c ? c.textContent : null; }, null, { timeout: 15000 }).then((h) => h.jsonValue()).catch(() => null);
out.rowStaysOnReply = await page.evaluate((s) => !!document.querySelector(s), rowSel(cfg.g1));
await page.fill("#composer-input", cfg.reply);
await page.press("#composer-input", "Enter");
out.afterReply = { left: await page.waitForFunction((s) => !document.querySelector(s), rowSel(cfg.g1), { timeout: 60000 }).then(() => true).catch(() => false) };
out.afterReply.box = await readBox();
mark();
// 4b. a BRAND-NEW card with a long brief (the round-thirteen verifier): its row is built detached and joined after, so the disclosure must be
// measured once the row stands in the box; the button shows with no gesture
const w3 = await writeStore((st) => {
  st.nodes[cfg.g5] = { id: cfg.g5, text: cfg.g5q, parentId: null, nodeComplete: false, blocked: true, blockWhy: cfg.g5q, blockSummary: cfg.longBrief, cleared: false, trail: [],
    t: Math.floor(Date.now() / 1000), log: [{ ev_t: Math.floor(Date.now() / 1000), src: "planner", kind: "block", why: "asked: " + cfg.g5q, at: Math.floor(Date.now() / 1000) }] };
  st.status[cfg.g5] = "blocked"; });
out.fresh = await builtRecord(cfg.g5, w3, cfg.longBrief);
out.fresh.row = await page.waitForSelector(rowSel(cfg.g5), { timeout: 30000 }).then(() => true).catch(() => false);   // after the kernel's word
out.fresh.landed = await landedAt(rowSel(cfg.g5), cfg.longBrief); if (!out.fresh.landed) await onMiss(out.fresh); out.fresh.clipped = await clippedAt(rowSel(cfg.g5));   // the same holds: the brief on the row, its layout clipping it
out.fresh.more = await page.waitForSelector(rowSel(cfg.g5) + " .ntc-more", { timeout: 15000 }).then(() => true).catch(() => false);
out.fresh.box = await readBox();
await foldTo(1);   // at the items level the line is clamped too and its button SHOWS (the box content round); below the full context the body and its button hid before it (the second contributor's post-merge review of PR 2093: pinned by source alone before)
out.fresh.moreAtItems = await page.evaluate((s) => { const m = document.querySelector(s + " .ntc-more"); return m ? getComputedStyle(m).display : "absent"; }, rowSel(cfg.g5));
await foldTo(2);
mark();
// 5. the switch, through the settings card's OWN ROW (the user 2026-09-23, who did not find it): the kernel's settings page (the card the
//    shell's gear opens; the chat page hosts none and relays) in the same browser context, its Chat tab, the row under the head named for
//    where the box sits, visible; its click saves, the chat page hears the store change and the box hides, leaving the ring; a second click
//    brings the box back
const [sp] = await Promise.all([page.waitForEvent("popup"), page.evaluate((u) => { window.open(u, "_blank"); }, cfg.chat.replace("/chat?token=", "/settings?token="))]);   // a popup of the chat page: the SAME
//   context and store, so the chat page hears the save as a storage event (a page in another context is another store, and the default context spawns none by the API)
await sp.waitForLoadState("domcontentloaded").catch(() => {});
await sp.waitForSelector("#rs-needsbox", { state: "attached", timeout: 30000 }).catch(() => {});
// the card OPENED, as every opener opens it (the openSettings message the page's own script listens for), on its Chat tab: the row is then
// on screen and the clicks below are real ones (the second contributor's post-merge review of PR 2093: the card never opened, the wait passed
// on a hidden pane's computed display and the scripted click saved through a hidden control)
await sp.evaluate(() => { window.postMessage({ romp: "openSettings", tab: "chat" }, "*"); });
out.switchRow = await sp.waitForFunction(() => { const p = document.getElementById("rsettings"); const cb = document.getElementById("rs-needsbox"); return !!p && !p.hidden && !!cb && cb.checkVisibility(); }, null, { timeout: 10000 }).then(() => sp.evaluate(() => {
  const cb = document.getElementById("rs-needsbox"); const lab = cb.closest("label"); let head = lab.previousElementSibling; while (head && !head.classList.contains("rs-sec")) head = head.previousElementSibling;   // loop-ok: walks up to the section head
  return { present: true, rendered: cb.checkVisibility() && cb.getBoundingClientRect().height > 0, checked: cb.checked, label: (lab.querySelector("b") || {}).textContent, head: head ? head.textContent : null, headSection: head ? head.getAttribute("data-section") : null, pane: cb.closest(".rs-pane").getAttribute("data-pane") };
})).catch(() => ({ present: false }));
const setBox = async (on) => { const cur = await sp.evaluate(() => (document.getElementById("rs-needsbox") || {}).checked); if (cur !== on) await sp.click("#rs-needsbox", { timeout: 5000 }).catch(() => {}); };   // a real click on the rendered control
await setBox(false);
out.off = { hidden: await page.waitForFunction(() => { const b = document.getElementById("notices"); return !!b && b.style.display === "none"; }, null, { timeout: 10000 }).then(() => true).catch(() => false) };
out.off.box = await readBox();
await setBox(true);
await sp.close();
out.on = { shown: await page.waitForFunction(() => { const b = document.getElementById("notices"); return !!b && b.style.display !== "none" && b.querySelectorAll(".ntc-row").length >= 1; }, null, { timeout: 10000 }).then(() => true).catch(() => false) };
out.on.levelKept = (await readBox()).level;   // read BEFORE any click (the same review: a fold to 2 from wherever the level stood undid a reset on rebuild before the read)
await foldTo(2);   // the rest of the scenes read the bodies and their disclosures
out.on.moreAfterRebuild = await page.waitForSelector(rowSel(cfg.g5) + " .ntc-more", { timeout: 15000 }).then(() => true).catch(() => false);   // the rebuilt row (host.replaceChildren, then the rows built anew) wears the disclosure too
out.on.box = await readBox();
mark();
// 6. a HIDDEN pane (the first contributor's post-merge review of PR 1967): the chat page inside a display:none iframe lays nothing out, so a
// fresh long-brief row measured there reads zero by zero; a zero measure is no information, and the pane's return re-runs the pass
const shell = await browser.newPage({ viewport: { width: 1400, height: 900 } });
await shell.goto(cfg.landing);                                                                     // the kernel's own shell: the chat pane is one of its iframes
let fr = null; for (let i = 0; i < 150 && !fr; i++) { fr = shell.frames().find((f) => /\/chat(\?|$)/.test(f.url())) || null; if (!fr) await shell.waitForTimeout(200); }   // loop-ok: bounded
out.hiddenPane = { frame: !!fr };
if (fr) {
  out.hiddenPane.loaded = await fr.waitForSelector("#notices .ntc-head", { timeout: 60000 }).then(() => true).catch(() => false);   // the box on screen once, collapsed to its header line (a fresh page)
  out.hiddenPane.collapsedFresh = await fr.evaluate(() => document.getElementById("notices").classList.contains("ntc-l0") && Array.from(document.querySelectorAll("#notices .ntc-row")).every((r) => getComputedStyle(r).display === "none"));   // collapsed by default: the rows attached and hidden
  await openNeedsBox(fr, 2);   // to the full context; a page without the levels (the base) shows everything already
  out.hiddenPane.rowsShown = await fr.waitForSelector("#notices .ntc-row", { timeout: 15000 }).then(() => true).catch(() => false);   // the rows visible at the full context
  out.hiddenPane.g5MoreBefore = await fr.waitForSelector(rowSel(cfg.g5) + " .ntc-more", { timeout: 15000 }).then(() => true).catch(() => false);   // the long-brief row's button stands before the hide
  // 6b. THE KEYBOARD ORDER WHERE THE GEAR IS DRAWN (the round-one verifier of PR 2105: the order pin ran only on the standalone page, and the gear
  // nested in the header's button was folded into its accessible name): Shift+Tab from the frame's composer enters the box on the gear, the last
  // control in the header; one more lands on the header, named by its label alone (aria-labelledby); Enter opens the items; Tab goes to the gear,
  // then to the first row's More (its long brief is clamped at the items since the box content round), then to its Reply
  await openNeedsBox(fr, 0);
  const frActive = () => fr.evaluate(() => { const a = document.activeElement; return a ? { inBox: !!a.closest("#notices"), head: a.classList.contains("ntc-head"), act: a.dataset ? a.dataset.act || null : null, text: (a.textContent || "").trim().slice(0, 40), labelledby: a.getAttribute("aria-labelledby"), labelText: (document.getElementById(a.getAttribute("aria-labelledby") || "") || {}).textContent || null } : null; });
  await fr.focus("#composer-input");
  out.shellKeys = { entered: false, presses: 0 };
  for (let i = 0; i < 40; i++) {   // loop-ok: bounded; the walk stops when focus enters the box
    await shell.keyboard.press("Shift+Tab"); out.shellKeys.presses = i + 1;
    const a = await frActive(); if (a && a.inBox) { out.shellKeys.entered = true; out.shellKeys.first = a; break; }
  }
  if (out.shellKeys.entered) {
    await shell.keyboard.press("Shift+Tab"); out.shellKeys.second = await frActive();
    out.shellKeys.headName = await fr.locator("#notices .ntc-head").ariaSnapshot().catch((e) => "snapshot failed: " + e);   // the COMPUTED accessible name, from the browser's accessibility tree (the post-merge review of PR 2108: the attribute and the label's text passed a mutant whose label carried its own aria-label)
    await shell.keyboard.press("Enter");
    out.shellKeys.opened = await fr.waitForFunction(() => document.getElementById("notices").classList.contains("ntc-l1"), null, { timeout: 5000 }).then(() => true).catch(() => false);
    await shell.keyboard.press("Tab"); out.shellKeys.afterTab1 = await frActive();
    // Enter on the FOCUSED GEAR opens the settings and leaves the level alone (the box arc's round three: only the keydown's target guard's regex
    // pinned that a key on the gear is the gear's own); the card is closed again by the shell's Escape chain
    out.shellKeys.levelBeforeGearEnter = await fr.evaluate(() => ["ntc-l0", "ntc-l1", "ntc-l2"].findIndex((c) => document.getElementById("notices").classList.contains(c)));
    await shell.keyboard.press("Enter");
    out.shellKeys.gearEnterOpened = await shell.waitForFunction(() => document.body.classList.contains("settings-open"), null, { timeout: 15000 }).then(() => true).catch(() => false);
    out.shellKeys.levelAfterGearEnter = await fr.evaluate(() => ["ntc-l0", "ntc-l1", "ntc-l2"].findIndex((c) => document.getElementById("notices").classList.contains(c)));
    await shell.keyboard.press("Escape");
    await shell.waitForFunction(() => !document.body.classList.contains("settings-open"), null, { timeout: 10000 }).catch(() => {});
    await fr.focus("#notices .ntc-bar .ntc-gear", { timeout: 5000 }).catch((e) => { if (e.name !== "TimeoutError") throw e; });   // fail-soft on the wait alone: a page without the bar (the base) reads whatever it shows
    await shell.keyboard.press("Tab"); out.shellKeys.afterTab2 = await frActive();   // the first row's first control: its disclosure, since its line is clamped at the items too (the box content round)
    await shell.keyboard.press("Tab"); out.shellKeys.afterTab3 = await frActive();   // then Reply
    out.shellKeys.headFocusable = await fr.evaluate(() => document.querySelector("#notices .ntc-head").querySelectorAll("button, [tabindex], a[href], input, select, textarea").length);   // no focusable descendant: the gear is a sibling (axe nested-interactive)
  }
  await openNeedsBox(fr, 2);
  // 6a. THE HEADER'S OWN GEAR, in the shell where a settings card can open (the second contributor's post-merge review of PR 2093: the strip's
  // gear lands on Tab strip with the box's section out of view): its click opens the settings' Chat tab with the Boxes section in the card's
  // view, and the box's level does not move
  // the bar's own strip beside the gear, its right margin: a click there toggles the level (the second contributor's review of PR 2120: dead before)
  await openNeedsBox(fr, 0);
  {
    out.marginClick = { levelBefore: await fr.evaluate(() => ["ntc-l0", "ntc-l1", "ntc-l2"].findIndex((c) => document.getElementById("notices").classList.contains(c))) };
    const width = await fr.evaluate(() => { const el = document.querySelector("#notices .ntc-bar") || document.querySelector("#notices .ntc-head"); return el.getBoundingClientRect().width; });
    await fr.click("#notices .ntc-bar", { position: { x: Math.max(1, width - 3), y: 2 }, timeout: 5000 }).catch((e) => { if (e.name !== "TimeoutError") throw e; });   // the gear's right margin: the bar's own click target (fail-soft: a page without the bar reads whatever it shows)
    out.marginClick.after = await fr.waitForFunction((l) => !document.getElementById("notices").classList.contains("ntc-l" + l), out.marginClick.levelBefore, { timeout: 5000 }).then(() => fr.evaluate(() => ["ntc-l0", "ntc-l1", "ntc-l2"].findIndex((c) => document.getElementById("notices").classList.contains(c)))).catch((e) => { if (e.name !== "TimeoutError") throw e; return -1; });
  }
  await openNeedsBox(fr, 2);
  out.gear = { present: await fr.evaluate(() => !!document.querySelector("#notices .ntc-bar .ntc-gear")), levelBefore: (await fr.evaluate(() => ["ntc-l0", "ntc-l1", "ntc-l2"].findIndex((c) => document.getElementById("notices").classList.contains(c)))) };
  if (out.gear.present) {
    await fr.click("#notices .ntc-bar .ntc-gear");
    out.gear.opened = await shell.waitForFunction(() => document.body.classList.contains("settings-open"), null, { timeout: 15000 }).then(() => true).catch(() => false);
    let setF = null; for (let i = 0; i < 50 && !setF; i++) { setF = shell.frames().find((f) => /\/settings(\?|$)/.test(f.url())) || null; if (!setF) await shell.waitForTimeout(100); }   // loop-ok: bounded
    out.gear.frame = !!setF;
    if (setF) {
      await setF.waitForSelector("#rsettings:not([hidden])", { timeout: 15000 }).catch(() => {});
      out.gear.mark = await setF.waitForFunction(() => (document.querySelector("#rsettings .rs-card") || {}).getAttribute && document.querySelector("#rsettings .rs-card").getAttribute("data-section-landed") === "boxes", null, { timeout: 15000 }).then(() => true).catch(() => false);   // the LANDING's mark (gear.js): a plain settings open shows the section in this window too, so only the mark tells the jump apart (the box arc's round three)
      out.gear.landed = await setF.waitForFunction(() => { const sec = document.querySelector('#rsettings .rs-pane:not([hidden]) .rs-sec[data-section="boxes"]'); const card = document.querySelector("#rsettings .rs-card"); if (!sec || !card) return false; const s = sec.getBoundingClientRect(), c = card.getBoundingClientRect(); return s.top >= c.top - 1 && s.bottom <= c.bottom + 1; }, null, { timeout: 10000 }).then(() => true).catch(() => false);
      out.gear.view = await setF.evaluate(() => { const shown = Array.from(document.querySelectorAll("#rsettings .rs-pane")).filter((pn) => !pn.hidden && getComputedStyle(pn).display !== "none").map((pn) => pn.dataset.pane);
        const sec = document.querySelector('#rsettings .rs-pane:not([hidden]) .rs-sec[data-section="boxes"]'); const card = document.querySelector("#rsettings .rs-card"); const cb = document.getElementById("rs-needsbox");
        const inView = (el) => { if (!el || !card) return null; const r = el.getBoundingClientRect(), c = card.getBoundingClientRect(); return r.top >= c.top - 1 && r.bottom <= c.bottom + 1; };
        return { shown, headInView: inView(sec), rowInView: inView(cb && cb.closest("label")), headText: sec ? sec.textContent : null }; });
    }
    out.gear.levelAfter = await fr.evaluate(() => ["ntc-l0", "ntc-l1", "ntc-l2"].findIndex((c) => document.getElementById("notices").classList.contains(c)));
    await shell.keyboard.press("Escape");   // the shell's Escape chain closes the card
    await shell.waitForFunction(() => !document.body.classList.contains("settings-open"), null, { timeout: 10000 }).catch(() => {});
  }
  await shell.evaluate(() => { window.__rompPaneToggle("chat", false); });                                                    // the rail hides the pane (display:none on its wrapper): the observer's word
  out.hiddenPane.hidden = await shell.waitForFunction(() => !document.body.classList.contains("po-chat"), null, { timeout: 10000 }).then(() => true).catch(() => false);
  const w4 = await writeStore((st) => {
    st.nodes[cfg.g6] = { id: cfg.g6, text: cfg.g6q, parentId: null, nodeComplete: false, blocked: true, blockWhy: cfg.g6q, blockSummary: cfg.longBrief, cleared: false, trail: [],
      t: Math.floor(Date.now() / 1000), log: [{ ev_t: Math.floor(Date.now() / 1000), src: "planner", kind: "block", why: "asked: " + cfg.g6q, at: Math.floor(Date.now() / 1000) }] };
    st.status[cfg.g6] = "blocked"; });
  Object.assign(out.hiddenPane, await builtRecord(cfg.g6, w4, cfg.longBrief));   // { id, floor, built }: the kernel's build event, read from the chat page's own fetch
  out.hiddenPane.row = await fr.waitForSelector(rowSel(cfg.g6), { state: "attached", timeout: 30000 }).then(() => true).catch(() => false);   // after the kernel's word
  out.hiddenPane.landed = await fr.waitForFunction((a) => { const r = document.querySelector(a.sel); const b = r && (r.querySelector(".ntc-secs > .fask-distill") || r.querySelector(".ntc-body")); return !!b && (b.textContent || "").trim() === a.brief; }, { sel: rowSel(cfg.g6), brief: cfg.longBrief }, { timeout: 30000 }).then(() => true).catch(() => false);
  if (!out.hiddenPane.landed) await onMiss(out.hiddenPane);
  out.hiddenPane.whileHidden = await fr.evaluate((a) => { const r = document.querySelector(a.g6); const b = r && (r.querySelector(".ntc-secs > .fask-distill") || r.querySelector(".ntc-body")); const g5 = document.querySelector(a.g5);
    return b ? { h: b.clientHeight, sh: b.scrollHeight, more: !!r.querySelector(".ntc-more"), g5More: !!(g5 && g5.querySelector(".ntc-more")) } : null; }, { g6: rowSel(cfg.g6), g5: rowSel(cfg.g5) });   // g5's button must stand: a zero measure removes nothing (the second contributor's post-merge note on PR 2018)
  await shell.evaluate(() => { window.__rompPaneToggle("chat", true); });                                                     // shown again
  out.hiddenPane.moreAfterShow = await fr.waitForSelector(rowSel(cfg.g6) + " .ntc-more", { timeout: 15000 }).then(() => true).catch(() => false);
  out.hiddenPane.clipped = await fr.evaluate((s) => { const r = document.querySelector(s); const b = r && (r.querySelector(".ntc-secs > .fask-distill") || r.querySelector(".ntc-body")); return !!b && b.scrollHeight > b.clientHeight + 1; }, rowSel(cfg.g6));
}
// 6c. THE ROW CARRIES WHAT THE CARD CARRIES (the user 2026-09-23, from a screenshot: a row at the items level showed its title and two buttons alone;
// plans/needs-you.md): the feed pane shown beside the chat pane, the fresh question's card and its row read at each level and compared. The store gives
// the card its other faces first: a background paragraph (the distiller's, its family stamped) and a sub-goal for two more toggles, a delegation's
// origin for a badge on its name row. At the items level the row shows the title, the card's distill line (clamped, whatever section is picked:
// the pick governs the full context only) and the card's badges, then Reply and Clear, and no session name, age or toggle; at the full context the card's toggles in the card's order with the card's
// labels and pressed states, and the same bodies. A press on the row's Background reaches the card and a press on the card's Summary reaches the row:
// the choice crosses the two documents (card-sections.ts, one builder for both).
out.content = { frame: !!fr };
if (fr) {
  await shell.evaluate(() => { window.__rompPaneToggle("feed", true); });
  let ff = null; for (let i = 0; i < 150 && !ff; i++) { ff = shell.frames().find((f) => /\/feed(\?|$)/.test(f.url())) || null; if (!ff) await shell.waitForTimeout(200); }   // loop-ok: bounded
  out.content.feedFrame = !!ff;
  if (ff) {
    const cardSel = '.fitem.ask[data-key="a:' + cfg.g6 + '"]';
    const w5 = await writeStore((st) => { st.nodes[cfg.g6].background = cfg.background; st.nodes[cfg.g6].distilledMt = briefNow() + 3;
      st.nodes[cfg.g6].origin = { peer: cfg.api, peerName: "api", goalId: cfg.api + ":g1" };
      st.nodes[cfg.g6].warns = [{ kind: "brief-failed", t: Math.floor(Date.now() / 1000) - 60, msg: "the first brief could not be written", detail: "the model returned nothing" }];   // the warning chip (the verifier's round two: the lab drove the origin badge alone); the kernel's distill pass is off (setUpClass), so the fixture stands
      st.nodes[cfg.g6].relayCarried = "a question to api is still parked on the far host: it went on before it could be withdrawn";   // the relayed question a far host still holds: the card's own dim line, drawn on the row too (a contributor's post-merge note on PR 2124)
      st.nodes[cfg.g6c] = { id: cfg.g6c, text: cfg.g6cText, parentId: cfg.g6, nodeComplete: false, blocked: false, cleared: false, trail: [], t: Math.floor(Date.now() / 1000), log: [] }; st.status[cfg.g6c] = "working"; });
    Object.assign(out.content, await builtRecord(cfg.g6, w5, cfg.longBrief));   // { id, floor, built }: the kernel's build past the write
    const vis = "const vis = (x) => !!x && getComputedStyle(x).display !== 'none' && x.getBoundingClientRect().height > 0;";
    out.content.cardReady = await ff.waitForFunction((s) => { const c = document.querySelector(s); if (!c) return false; const vis = (x) => !!x && getComputedStyle(x).display !== "none" && x.getBoundingClientRect().height > 0;
      const b = Array.from(c.querySelectorAll(".fask-row3 > .fask-secbtn")).find((x) => (x.textContent || "").trim() === "Background"); return vis(b) && vis(c.querySelector(".fask-row2 .fask-origin")); }, cardSel, { timeout: 60000 }).then(() => true).catch(() => false);   // the card wears the Background toggle and the origin badge once the build reaches the feed page
    const readCard = () => ff.evaluate((s) => { const c = document.querySelector(s); if (!c) return null; const vis = (x) => !!x && getComputedStyle(x).display !== "none" && x.getBoundingClientRect().height > 0;
      const t = c.querySelector(".fcard-title"); const d = c.querySelector(".fask-secs > .fask-distill");
      return { title: t ? (t.textContent || "").trim() : null, distill: d ? (d.textContent || "").trim() : null,
               badges: Array.from(c.querySelectorAll(".fask-row2 .fask-badges > *")).filter(vis).map((x) => (x.textContent || "").trim()),   // the badge slot's children: the same read as the row's (symmetric, the verifier's round two)
               chip: (() => { const ch = c.querySelector(".fask-warnchip"); return ch ? { tag: ch.tagName, cursor: getComputedStyle(ch).cursor, act: ch.dataset.act || null } : null; })(),   // the warning chip's face: the hand where a click opens the detail
               relay: (() => { const rn = c.querySelector(".fask-relaynote"); return rn ? { text: (rn.textContent || "").trim(), shown: vis(rn) } : null; })(),   // the relayed question's own line
               toggles: Array.from(c.querySelectorAll(".fask-row3 > .fask-secbtn")).filter(vis).map((x) => ({ label: (x.textContent || "").trim(), pressed: x.getAttribute("aria-pressed") })),
               bodies: { bg: vis(c.querySelector(".fask-bg-body")), distill: vis(d), stall: vis(c.querySelector(".fask-stall-body")), tree: vis(c.querySelector(".fask-checklist")) } }; }, cardSel);
    const readRow = () => fr.evaluate((s) => { const r = document.querySelector(s); if (!r) return null; const vis = (x) => !!x && getComputedStyle(x).display !== "none" && x.getBoundingClientRect().height > 0;
      const t = r.querySelector(".ntc-title"); const d = r.querySelector(".ntc-secs > .fask-distill"); const secsRow = r.querySelector(".ntc-secs-row");
      return { title: t ? (t.textContent || "").trim() : null, distill: d ? (d.textContent || "").trim() : null, clamp: d ? getComputedStyle(d).webkitLineClamp : null,
               badges: Array.from(r.querySelectorAll(".ntc-badges > *")).filter(vis).map((x) => (x.textContent || "").trim()),
               chip: (() => { const ch = r.querySelector(".fask-warnchip"); return ch ? { tag: ch.tagName, cursor: getComputedStyle(ch).cursor, act: ch.dataset.act || null } : null; })(),   // the row's chip: a span, the default cursor, no act
               relay: (() => { const rn = r.querySelector(".fask-relaynote"); return rn ? { text: (rn.textContent || "").trim(), shown: vis(rn) } : null; })(),   // the same line on the row, outside its sections
               togglesShown: vis(secsRow), toggles: secsRow ? Array.from(secsRow.querySelectorAll(".fask-secbtn")).filter(vis).map((x) => ({ label: (x.textContent || "").trim(), pressed: x.getAttribute("aria-pressed") })) : null,
               bodies: { bg: vis(r.querySelector(".fask-bg-body")), distill: vis(d), stall: vis(r.querySelector(".fask-stall-body")), tree: vis(r.querySelector(".fask-checklist")) },
               nameOrAge: !!r.querySelector(".fname, .ftime, .fask-row2"), buttons: Array.from(r.querySelectorAll(".ntc-actions button")).map((b) => (b.textContent || "").trim()) }; }, rowSel(cfg.g6));
    await openNeedsBox(fr, 1);
    out.content.rowLanded = await fr.waitForFunction((s) => { const r = document.querySelector(s); const b = r && r.querySelector(".ntc-badges .fask-origin"); return !!b && getComputedStyle(b).display !== "none"; }, rowSel(cfg.g6), { timeout: 30000 }).then(() => true).catch(() => false);   // the row's repaint with the badge: the frame's key carries the whole row
    out.content.cardL1 = await readCard(); out.content.rowL1 = await readRow();
    await openNeedsBox(fr, 2);
    out.content.cardL2 = await readCard(); out.content.rowL2 = await readRow();
    const pressRow = (label) => fr.evaluate((a) => { const r = document.querySelector(a.sel); const b = r && Array.from(r.querySelectorAll(".ntc-secs-row .fask-secbtn")).find((x) => (x.textContent || "").trim() === a.label); if (b) b.click(); return !!b; }, { sel: rowSel(cfg.g6), label });
    const pressCard = (label) => ff.evaluate((a) => { const c = document.querySelector(a.sel); const b = c && Array.from(c.querySelectorAll(".fask-row3 > .fask-secbtn")).find((x) => (x.textContent || "").trim() === a.label); if (b) b.click(); return !!b; }, { sel: cardSel, label });
    const cardPressed = (label) => ff.waitForFunction((a) => { const c = document.querySelector(a.sel); const b = c && Array.from(c.querySelectorAll(".fask-row3 > .fask-secbtn")).find((x) => (x.textContent || "").trim() === a.label); return !!b && b.getAttribute("aria-pressed") === "true"; }, { sel: cardSel, label }, { timeout: 10000 }).then(() => true).catch(() => false);
    const rowPressed = (label) => fr.waitForFunction((a) => { const r = document.querySelector(a.sel); const b = r && Array.from(r.querySelectorAll(".ntc-secs-row .fask-secbtn")).find((x) => (x.textContent || "").trim() === a.label); return !!b && b.getAttribute("aria-pressed") === "true"; }, { sel: rowSel(cfg.g6), label }, { timeout: 10000 }).then(() => true).catch(() => false);
    out.content.rowPressBg = await pressRow("Background"); out.content.cardFollowed = await cardPressed("Background");
    out.content.cardAfterRowPress = await readCard(); out.content.rowAfterRowPress = await readRow();
    out.content.cardPressSummary = await pressCard("Summary"); out.content.rowFollowed = await rowPressed("Summary");
    out.content.cardAfterCardPress = await readCard(); out.content.rowAfterCardPress = await readRow();
    // 6h. A PICK WITH NO FEED DOCUMENT UP (the round-three verdict: the shell loads the feed document at boot, so a pick made before the feed PANE is
    // shown reaches a live owner and proves nothing; here the premise is real): the feed's frame is navigated away, Background is picked on the row
    // with nobody to hear it, and the feed document comes back: it hydrates its persisted map, which knows nothing of the pick, and posts it; the
    // row keeps its own pick over that map and re-posts it, so the card comes up showing Background. Back to the default afterwards
    const feedUrl = ff.url();
    await ff.goto("about:blank").catch(() => {});
    out.content.noOwner = { blank: /about:blank/.test(ff.url()) };
    out.content.noOwner.pressed = await pressRow("Background"); out.content.noOwner.rowPressed = await rowPressed("Background");
    await ff.goto(feedUrl).catch(() => {});
    out.content.noOwner.cardUp = await ff.waitForSelector(cardSel, { timeout: 60000 }).then(() => true).catch(() => false);
    out.content.noOwner.cardFollowed = await cardPressed("Background");
    out.content.noOwner.rowStill = await fr.evaluate((s) => { const r = document.querySelector(s); const b = r && Array.from(r.querySelectorAll(".ntc-secs-row .fask-secbtn")).find((x) => (x.textContent || "").trim() === "Background"); return b ? b.getAttribute("aria-pressed") : null; }, rowSel(cfg.g6));
    await pressCard("Summary"); await rowPressed("Summary");
    // 6f. A PICK RE-RUNS THE ROW'S MORE PASS, AND THE ITEMS LEVEL SHOWS THE CLAMPED LINE WHATEVER THE PICK (round three of the box content PR, a
    // contributor's review): no store write between a press and its read (a write repaints the row and would hide the defect). Background pressed on
    // the row hides its line and takes its More with it; Summary pressed back brings the clipped line and its More; at the items level a Background
    // pressed on the card leaves the row's clamped line with its More and shows no paragraph
    const moreOf = () => fr.evaluate((s) => { const r = document.querySelector(s); const m = r && r.querySelector(".ntc-more"); const d = r && r.querySelector(".ntc-secs > .fask-distill"); const bg = r && r.querySelector(".fask-bg-body");
      const vis = (x) => !!x && getComputedStyle(x).display !== "none" && x.getBoundingClientRect().height > 0;
      return { more: !!m && vis(m), moreLabel: m ? m.textContent : null, line: vis(d), clamp: d ? getComputedStyle(d).webkitLineClamp : null, clipped: !!d && d.scrollHeight > d.clientHeight + 1, bg: vis(bg) }; }, rowSel(cfg.g6));
    out.content.pick = { before: await moreOf() };
    // the CLOSED direction first (the first note on PR 2124: a pick re-applied the sections and left More stale on the closed row): Background hides
    // the line and More goes with it, Summary picked back brings the clipped line with More; then the OPEN direction (the 0.17.1 fix, a contributor's
    // second note: Less stood over the line a Background pick hid): More pressed, the brief open, Background hides the line and its Less goes with it,
    // Summary picked back brings the open brief with Less (the open state kept), then Less closes it. Both directions, since the More pass run only
    // for an open row passes the open one alone (the contributor's note on the fix)
    out.content.pick.closedBg = { pressed: await pressRow("Background"), row: await rowPressed("Background"), face: await moreOf() };
    out.content.pick.closedSummary = { pressed: await pressRow("Summary"), row: await rowPressed("Summary"), face: await moreOf() };
    await fr.evaluate((s) => { const m = document.querySelector(s + " .ntc-more"); if (m) m.click(); }, rowSel(cfg.g6));
    out.content.pick.opened = await fr.waitForFunction((s) => { const r = document.querySelector(s); return !!r && r.classList.contains("ntc-open"); }, rowSel(cfg.g6), { timeout: 10000 }).then(() => true).catch(() => false);
    out.content.pick.beforeOpen = await moreOf();
    out.content.pick.pressedBg = await pressRow("Background"); out.content.pick.rowBg = await rowPressed("Background"); out.content.pick.afterBg = await moreOf();
    out.content.pick.pressedSummary = await pressRow("Summary"); out.content.pick.rowSummary = await rowPressed("Summary"); out.content.pick.afterSummary = await moreOf();
    await fr.evaluate((s) => { const m = document.querySelector(s + " .ntc-more"); if (m) m.click(); }, rowSel(cfg.g6));   // Less: the brief folds back
    out.content.pick.closed = await fr.waitForFunction((s) => { const r = document.querySelector(s); return !!r && !r.classList.contains("ntc-open"); }, rowSel(cfg.g6), { timeout: 10000 }).then(() => true).catch(() => false);
    await openNeedsBox(fr, 1);
    out.content.pick.itemsBefore = await moreOf();
    out.content.pick.cardBg = await pressCard("Background"); out.content.pick.rowFollowedBg = await rowPressed("Background");   // the card's pick reaches the row's toggles (hidden at the items) over the channel
    out.content.pick.itemsAfterCardBg = await moreOf();
    // a REPAINT with Background picked (the same note: the items face after a repaint was unpinned): a store write that moves a field the row
    // carries (the background paragraph itself, its family stamped), waited for on the row's own background body, then the items face read again
    const w7 = await writeStore((st) => { st.nodes[cfg.g6].background = cfg.background + " The second loader reads the first's fixtures."; st.nodes[cfg.g6].distilledMt = briefNow() + 9; });
    out.content.pick.repaint = await builtRecord(cfg.g6, w7, cfg.longBrief);
    out.content.pick.repainted = await fr.waitForFunction((s) => { const r = document.querySelector(s); const b = r && r.querySelector(".fask-bg-body"); return !!b && (b.textContent || "").includes("second loader reads"); }, rowSel(cfg.g6), { timeout: 30000 }).then(() => true).catch(() => false);   // the row repainted with the new paragraph
    out.content.pick.itemsAfterRepaint = await moreOf();
    await pressCard("Summary"); await rowPressed("Summary");
    await openNeedsBox(fr, 2);
    // 6d. THE STAMPS AND THE LANDINGS (round two of the box content PR): the brief becomes two paragraphs with two parts, the second part
    // without an event time, so the row's second stamp must read the card's static "<1m ago" and never an age counted from the epoch; the
    // row's line is a link like the card's and its click lands the way this chat page lands: at the turn the kernel's anchor names, or, when
    // the kernel serves none, in the landing toast that says no anchor was recorded (no goal here can carry a validated citation: the
    // synthetic transcript ends before every goal, and a goal reaching into it takes the API-error turn and becomes the hard stop)
    const w6 = await writeStore((st) => { st.nodes[cfg.g6].blockSummary = cfg.twoParaBrief; st.nodes[cfg.g6].briefedMt = briefNow() + 5;
      st.nodes[cfg.g6].briefParts = [{ id: cfg.g6c, since: Math.floor(Date.now() / 1000) - 120 }, { id: cfg.g6 + ":open" }]; });
    out.content.stamps = await builtRecord(cfg.g6, w6, cfg.twoParaBrief);
    const fAfter = await kernelFeed(); out.content.stamps.anchor = ((((fAfter || {}).asks || []).find((a) => a.itemId === cfg.g6) || {}).summaryAnchorUuid) || null;
    out.content.stamps.cardLanded = await ff.waitForFunction((s) => { const c = document.querySelector(s); const d = c && c.querySelector(".fask-secs > .fask-distill"); return !!d && d.querySelectorAll(".fask-para").length === 2; }, cardSel, { timeout: 30000 }).then(() => true).catch(() => false);
    out.content.stamps.rowLanded = await fr.waitForFunction((s) => { const r = document.querySelector(s); const d = r && r.querySelector(".ntc-secs > .fask-distill"); return !!d && d.querySelectorAll(".fask-para").length === 2; }, rowSel(cfg.g6), { timeout: 30000 }).then(() => true).catch(() => false);
    const readLine = (target, sel, lineSel) => target.evaluate((a) => { const r = document.querySelector(a.sel); const d = r && r.querySelector(a.lineSel); if (!d) return null;
      return { paras: Array.from(d.querySelectorAll(".fask-para")).map((p) => ({ text: (p.textContent || "").trim(), age: ((p.querySelector(".fask-para-age") || {}).textContent || null), link: p.classList.contains("fask-para-link") })),
               link: d.classList.contains("fask-distill-link"), title: d.getAttribute("title"), text: (d.textContent || "").trim() }; }, { sel, lineSel });
    out.content.stamps.card = await readLine(ff, cardSel, ".fask-secs > .fask-distill"); out.content.stamps.row = await readLine(fr, rowSel(cfg.g6), ".ntc-secs > .fask-distill");
    await fr.evaluate((s) => { const r = document.querySelector(s); const d = r && r.querySelector(".ntc-secs > .fask-distill"); if (d) d.click(); }, rowSel(cfg.g6));   // the row's line clicked
    out.content.stamps.landed = await fr.waitForFunction((u) => { if (u) { const t = document.querySelector('.turn[data-uuid="' + u + '"]'); if (!t) return false; const b = t.getBoundingClientRect(); return b.bottom > 0 && b.top < window.innerHeight; } return !!document.querySelector(".locate-toast"); }, out.content.stamps.anchor, { timeout: 15000 }).then(() => true).catch(() => false);   // the turn on screen (or, with no anchor recorded, the landing toast)
    // 6e. THE ONE STATE ACROSS A RELOAD: Background picked on the card, the shell reloaded, both frames up again; the feed hydrates its pick
    // from its view state and the chat page, a follower, takes the map when it says hello, so the row opens what the card opens
    out.content.reload = { pressed: await pressCard("Background"), cardPressed: await cardPressed("Background") };
    await shell.reload();
    let fr2 = null, ff2 = null; for (let i = 0; i < 150 && !(fr2 && ff2); i++) { fr2 = shell.frames().find((f) => /\/chat(\?|$)/.test(f.url())) || null; ff2 = shell.frames().find((f) => /\/feed(\?|$)/.test(f.url())) || null; if (!(fr2 && ff2)) await shell.waitForTimeout(200); }   // loop-ok: bounded
    out.content.reload.frames = !!(fr2 && ff2);
    if (fr2 && ff2) {
      out.content.reload.cardUp = await ff2.waitForSelector(cardSel, { timeout: 60000 }).then(() => true).catch(() => false);
      out.content.reload.rowUp = await fr2.waitForSelector(rowSel(cfg.g6), { state: "attached", timeout: 60000 }).then(() => true).catch(() => false);
      await openNeedsBox(fr2, 2);
      out.content.reload.rowFollowed = await fr2.waitForFunction((a) => { const r = document.querySelector(a.sel); const b = r && Array.from(r.querySelectorAll(".ntc-secs-row .fask-secbtn")).find((x) => (x.textContent || "").trim() === a.label); return !!b && b.getAttribute("aria-pressed") === "true"; }, { sel: rowSel(cfg.g6), label: "Background" }, { timeout: 15000 }).then(() => true).catch(() => false);
      const readT = (target, sel, btnSel) => target.evaluate((a) => { const c = document.querySelector(a.sel); if (!c) return null; const vis = (x) => !!x && getComputedStyle(x).display !== "none" && x.getBoundingClientRect().height > 0; return Array.from(c.querySelectorAll(a.btnSel)).filter(vis).map((x) => ({ label: (x.textContent || "").trim(), pressed: x.getAttribute("aria-pressed") })); }, { sel, btnSel });
      out.content.reload.card = await readT(ff2, cardSel, ".fask-row3 > .fask-secbtn"); out.content.reload.row = await readT(fr2, rowSel(cfg.g6), ".ntc-secs-row .fask-secbtn");
      // 6g. A LIVE COLLAPSED FLIP CROSSES THE CHANNEL (the verifier's round two: the whole-map post was executed by no test): the feed's Collapsed
      // preference flipped from the shell's storage (the feed hears the storage event and clears every pick through the shared setter, which posts
      // the map) empties the row's picks too: Background open on both a moment ago, the row's Background reads unpressed
      // the pick is made on the ROW here (the 0.17.1 fix, a contributor's second note: a row pick outlived every feed map that lacked it, since the feed
      // answered the row's set with nothing; the feed acknowledges it now, so the flip's map clears it on both documents)
      const pressRow2 = (label) => fr2.evaluate((a) => { const r = document.querySelector(a.sel); const b = r && Array.from(r.querySelectorAll(".ntc-secs-row .fask-secbtn")).find((x) => (x.textContent || "").trim() === a.label); if (b) b.click(); return !!b; }, { sel: rowSel(cfg.g6), label });
      const cardIs2 = (label, pressed) => ff2.waitForFunction((a) => { const c = document.querySelector(a.sel); const b = c && Array.from(c.querySelectorAll(".fask-row3 > .fask-secbtn")).find((x) => (x.textContent || "").trim() === a.label); return !!b && b.getAttribute("aria-pressed") === a.pressed; }, { sel: cardSel, label, pressed }, { timeout: 10000 }).then(() => true).catch(() => false);
      await ff2.evaluate((s) => { const c = document.querySelector(s); const b = c && Array.from(c.querySelectorAll(".fask-row3 > .fask-secbtn")).find((x) => (x.textContent || "").trim() === "Summary"); if (b) b.click(); }, cardSel);   // the reload scene's card pick closed first
      await cardIs2("Summary", "true");
      out.content.collapsed = { rowPick: await pressRow2("Background"), cardFollowed: await cardIs2("Background", "true") };
      const prefs = await shell.evaluate(() => { try { return JSON.parse(localStorage.getItem("romp:settings") || "{}"); } catch (e) { return {}; } });
      await shell.evaluate((p) => { localStorage.setItem("romp:settings", JSON.stringify(Object.assign({}, p, { collapsed: true }))); }, prefs);
      out.content.collapsed.rowCleared = await fr2.waitForFunction((a) => { const r = document.querySelector(a.sel); const b = r && Array.from(r.querySelectorAll(".ntc-secs-row .fask-secbtn")).find((x) => (x.textContent || "").trim() === "Background"); return !!b && b.getAttribute("aria-pressed") === "false"; }, { sel: rowSel(cfg.g6) }, { timeout: 15000 }).then(() => true).catch(() => false);
      // two kernel payloads AFTER the flip, each an event and never a wall-clock wait (the manager's read of the fix PR): a store write that moves the
      // row's brief (the line's text is written on every update whatever is open; a closed background body is not), the kernel's build past the write
      // carrying that brief, and the row's own repaint carrying the new sentence; a pick the feed had not acknowledged came back with the first of
      // them (the defect re-imposed it per payload); then the row's toggles are read again
      out.content.collapsed.payloads = [];
      for (const word of ["third", "fourth"]) {   // loop-ok: two writes
        const brief = cfg.twoParaBrief + " The " + word + " loader reads the fixtures of the one before.";
        const w = await writeStore((st) => { st.nodes[cfg.g6].blockSummary = brief; st.nodes[cfg.g6].briefedMt = briefNow() + 10 + out.content.collapsed.payloads.length; });
        const rec = await builtRecord(cfg.g6, w, brief);
        rec.repainted = await fr2.waitForFunction((a) => { const r = document.querySelector(a.sel); const b = r && r.querySelector(".ntc-distill"); return !!b && (b.textContent || "").includes(a.word + " loader reads"); }, { sel: rowSel(cfg.g6), word }, { timeout: 30000 }).then(() => true).catch(() => false);
        out.content.collapsed.payloads.push(rec);
      }
      out.content.collapsed.rowLater = await readT(fr2, rowSel(cfg.g6), ".ntc-secs-row .fask-secbtn");
      out.content.collapsed.card = await readT(ff2, cardSel, ".fask-row3 > .fask-secbtn"); out.content.collapsed.row = await readT(fr2, rowSel(cfg.g6), ".ntc-secs-row .fask-secbtn");
      await shell.evaluate((p) => { localStorage.setItem("romp:settings", JSON.stringify(p)); }, prefs);   // the preference back
      // the flip BACK with NO pick held (the manager's read of the fix PR): the feed's clear finds its map unchanged and posts none, so each document
      // re-applies its own hosts from its own storage listener (the chat page re-renders the box on the settings key: render.ts setupSettings), and the
      // row's default returns to Summary at once, with no payload between; an event wait on the toggle, never a sleep
      out.content.collapsed.backRow = await fr2.waitForFunction((a) => { const r = document.querySelector(a.sel); const b = r && Array.from(r.querySelectorAll(".ntc-secs-row .fask-secbtn")).find((x) => (x.textContent || "").trim() === "Summary"); return !!b && b.getAttribute("aria-pressed") === "true"; }, { sel: rowSel(cfg.g6) }, { timeout: 10000 }).then(() => true).catch(() => false);
      out.content.collapsed.backCard = await cardIs2("Summary", "true");
      await ff2.evaluate((s) => { const c = document.querySelector(s); const b = c && Array.from(c.querySelectorAll(".fask-row3 > .fask-secbtn")).find((x) => (x.textContent || "").trim() === "Summary"); if (b) b.click(); }, cardSel);   // back to the summary on both
    }
  }
  mark();
}
// 7. A FRESH PAGE STARTS COLLAPSED (the second contributor's post-merge review of PR 2093: the earlier read used a new context, which a level kept
// in localStorage would have passed): the SAME chat page reloaded, its rows waited for as attached, reads level 0 with every row hidden
out.reload = { before: (await readBox()).level };
await page.reload();
await page.waitForSelector("#notices .ntc-row", { state: "attached", timeout: 60000 }).catch(() => {});
out.reload.box = await readBox();
process.stdout.write("RESULT:" + JSON.stringify(out) + "\n");
await browser.close();
"""


# the driver's budget. Its bounded waits sum to about 2950 s serially (every helper counted PER CALL, the round-one verifier of PR 2105: the
# kernel's four 90 s deadlines, the 60 s row, card and credential-row waits, the 30 s and 15 s waits of the brief helpers per call, the fold
# helper's three 5 s waits per call, the shorter button, dialog, level, settings-card and frame waits, the frame loops), more than any per-test ceiling the runner gives (CI's served-page step runs pytest with --timeout=600, thread method), so
# the cap cannot be the sum: it is the ceiling less the SETUP the same per-test timer wraps (pytest-timeout's thread method times the first
# test's setUpClass too: the esbuild run and the healthz boot loop, bounded at about 60 to 120 s here), so a kernel that boots late and then
# stalls still hits this cap before the runner's, with the record below and the kernel's tail in hand rather than a bare per-test timeout
# that also skips every later served test in the process (the second contributor's read of PR 2038). A driver that runs past it has hit
# several deadlines in a row; the driver prints a PARTIAL line after every scene, and _result reports the last one with the kernel's tail.
DRIVER_TIMEOUT_S = 480


def _block(t, why):
    return {"ev_t": t, "src": "planner", "kind": "block", "why": why, "at": t}


class NeedsYouBoxChatServed(unittest.TestCase):
    maxDiff = None

    @classmethod
    def _skip(cls, why):
        if os.environ.get("ROMP_SERVED_TESTS_REQUIRE") == "1":
            raise AssertionError("ROMP_SERVED_TESTS_REQUIRE=1 but the served lab could not run: " + why)
        raise unittest.SkipTest(why)

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(os.path.join(EXT, "node_modules", "playwright")):
            cls._skip("extension deps absent (npm ci not run here): the served guard needs them")
        cls.lab = tempfile.mkdtemp(prefix="needs-you-box-")
        b = subprocess.run(["node", "esbuild.js"], cwd=EXT, capture_output=True, text=True)
        if b.returncode != 0:
            cls._skip("esbuild failed here: " + (b.stderr or b.stdout)[-200:])
        dist = os.path.join(cls.lab, "dist")
        copy_dist(os.path.join(EXT, "dist"), dist)
        state = os.path.join(cls.lab, "xdg", "romp")
        cwd = os.path.join(cls.lab, "notes-api")
        for d in ("names", "sdk", "states", "goals", os.path.join("postal", "quarantine")):
            os.makedirs(os.path.join(state, d), exist_ok=True)
        os.makedirs(cwd, exist_ok=True)
        Path(state, "session-hosts").write_text("off\n")
        claude = os.path.join(cls.lab, "claude")
        proj = os.path.join(claude, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd)))
        os.makedirs(proj, exist_ok=True)
        Path(state, "names", SID).write_text("web\t%s\t#9cd2ff\t#0c1a2e\n" % cwd)
        # alive: a LIVE session (_needs_you_rows: `cont` is the card's live bit, stored on the row though no button reads it since 2026-09-23), so
        # the Reply leg reaches the SDK backend for web, which on a box without the SDK logs "sdk session web crashed: ModuleNotFoundError" once
        # per send and the leg still passes (the reply is filed as the card's follow-up). The briefs' landing never depends on the backend: the
        # box rows come from the feed build of the store and ride the chat signature by value. Session hosts stay off (below), so no
        # romp-session-host starts.
        Path(state, "sdk", SID + ".json").write_text(json.dumps(
            {"sid": SID, "name": "web", "cwd": cwd, "mode": "auto", "effort": "high", "lastSid": SID, "alive": True,
             "model": "claude-opus-5", "liveModel": "Opus 5"}))
        # api: one question and no hard stop, so its tab wears the Needs you ring (the switch leg reads it: web's red ring is painted
        # first and alone, so a regression dropping the magenta ring would pass on web's tab); web stays first, the active tab
        Path(state, "names", API).write_text("api\t%s\t#1EA1EB\t#ffffff\n" % cwd)
        Path(state, "sdk", API + ".json").write_text(json.dumps(
            {"sid": API, "name": "api", "cwd": cwd, "mode": "auto", "effort": "high", "lastSid": API, "alive": True,
             "model": "claude-opus-5", "liveModel": "Opus 5"}))
        Path(state, "session-order.json").write_text(json.dumps([SID, API]))
        Path(state, "cleared.jsonl").write_text("")      # present, so the refused-clear leg can take its write bit away and give it back
        t0 = int(time.time()) - 3600
        iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))
        recs, parent = [], None
        for i in range(6):
            u, a = "u%d" % i, "a%d" % i
            recs.append({"type": "user", "uuid": u, "parentUuid": parent, "timestamp": iso(t0 + 10 * i), "sessionId": SID, "promptSource": "typed",
                         "message": {"role": "user", "content": "question %d about the notes api" % i}})
            recs.append({"type": "assistant", "uuid": a, "parentUuid": u, "timestamp": iso(t0 + 10 * i + 4), "sessionId": SID,
                         "message": {"role": "assistant", "model": "claude-opus-5", "stop_reason": "end_turn",
                                     "content": [{"type": "text", "text": "answer %d: the notes api keeps its shape." % i}]}})
            parent = a
        # the session is STOPPED on an API error only the user can clear (the transcript's last record, Claude Code's
        # isApiErrorMessage shape, "prompt is too long"): its focus goal (the store's lastNode) floors as a live block, the hard stop
        recs.append({"type": "user", "uuid": "u6", "parentUuid": parent, "timestamp": iso(t0 + 60), "sessionId": SID, "promptSource": "typed",
                     "message": {"role": "user", "content": "wire the fixtures directory into the integration suite"}})
        recs.append({"type": "assistant", "uuid": "e6", "parentUuid": "u6", "timestamp": iso(t0 + 62), "sessionId": SID, "isApiErrorMessage": True,
                     "apiErrorStatus": 400, "error": "invalid_request",
                     "message": {"role": "assistant", "content": [{"type": "text", "text": "API Error: 400 prompt is too long"}]}})
        Path(proj, SID + ".jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        Path(state, "states", SID + ".jsonl").write_text(json.dumps({"t": t0 + 70, "state": "idle"}) + "\n")
        # three questions the judges filed (diary events in the fold's shape, so the rollup keeps the flags), and the working focus goal
        cls.g = [SID + ":g%d" % i for i in range(1, 5)]
        nodes, status = {}, {}
        for i, q in enumerate(QUESTIONS):
            g = cls.g[i]
            nodes[g] = {"id": g, "text": q, "parentId": None, "nodeComplete": False, "blocked": True, "blockWhy": q, "cleared": False, "trail": [],
                        "t": t0 + 100 + i, "log": [_block(t0 + 200 + i, "asked: " + q)]}
            status[g] = "blocked"
        g4 = cls.g[3]
        nodes[g4] = {"id": g4, "text": "wire the fixtures directory into the integration suite", "parentId": None, "nodeComplete": False, "blocked": False,
                     "cleared": False, "trail": [], "t": t0 + 300, "log": []}
        status[g4] = "working"
        cls.store = os.path.join(state, "goals", SID + ".json")
        Path(cls.store).write_text(json.dumps(
            {"rompUuid": SID, "seq": 5, "lastNode": g4, "closedTurns": [], "nodes": nodes, "placements": {}, "status": status}))
        cls.ledger = os.path.join(state, "cleared.jsonl")
        cls.order = os.path.join(state, "session-order.json")
        Path(proj, API + ".jsonl").write_text(json.dumps(
            {"type": "user", "uuid": "p1", "parentUuid": None, "timestamp": iso(t0 + 20), "sessionId": API, "promptSource": "typed",
             "message": {"role": "user", "content": "set up the api fixtures"}}) + "\n" + json.dumps(
            {"type": "assistant", "uuid": "q1", "parentUuid": "p1", "timestamp": iso(t0 + 24), "sessionId": API,
             "message": {"role": "assistant", "model": "claude-opus-5", "stop_reason": "end_turn", "content": [{"type": "text", "text": API_Q}]}}) + "\n")
        Path(state, "states", API + ".jsonl").write_text(json.dumps({"t": t0 + 30, "state": "idle"}) + "\n")
        ga = API + ":g1"
        Path(state, "goals", API + ".json").write_text(json.dumps(
            {"rompUuid": API, "seq": 1, "lastNode": ga, "closedTurns": [], "placements": {}, "status": {ga: "blocked"},
             "nodes": {ga: {"id": ga, "text": "set up the api fixtures", "parentId": None, "nodeComplete": False, "blocked": True, "blockWhy": API_Q, "blockSummary": "the fixtures need a port the api will own",
                            "cleared": False, "trail": [], "t": t0 + 20, "log": [_block(t0 + 25, "asked: " + API_Q)]}}}))
        # a message from a DIRECTED peer, held for the user's decision: a needs-you notice with Approve and Deny at the first build
        Path(state, "postal", "quarantine", MID + ".json").write_text(json.dumps(
            {"mid": MID, "to": "web", "toId": SID, "frm": "api", "frmId": "11111111-2222-3333-4444-666666666666",
             "body": "the README draft is ready for a look, could you check the parser section before the release?",
             "kind": "coordinate", "origin": "TESTHOST", "via": "peer", "at": int(time.time()) - 600}))
        cls.port = _free_port()
        cls.token = "testtok-needsbox"
        # the distill pass OFF (the verifier's round on the 0.17.1 fix PR): this lab writes every brief, paragraph part and warn itself, and the
        # kernel's briefer, through a CLI the lab points at /bin/false, regenerated the question's brief on every pass and gave up every third
        # one, keeping the text, blanking its parts and writing its own brief-failed warn over the fixture's (read from a kept store: the give-up
        # warn naming 45 failed calls, briefParts None); the stamps scene's premise held or fell by where a read fell in that cycle
        env = _lab.kernel_env(cls.lab, claude, dist, cls.port, cls.token, ROMP_HOST_NAME="TESTHOST", ROMP_DISTILLER="0")
        cls.klog = os.path.join(cls.lab, "kernel.log")
        cls.kernel = subprocess.Popen([os.path.join(BIN, "romp-kernel")], stdout=open(cls.klog, "w"), stderr=subprocess.STDOUT, env=env)
        for _ in range(120):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/healthz" % cls.port, timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            cls.kernel.kill()
            cls._skip("hermetic kernel never served /healthz here")
        cls._r = None

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "kernel", None):
            cls.kernel.kill()
            cls.kernel.wait()
        shutil.rmtree(getattr(cls, "lab", ""), ignore_errors=True)

    def _result(self):
        if getattr(type(self), "_fail", None):
            self.fail(type(self)._fail)
        if self._r is None:
            cfg = os.path.join(self.lab, "needsbox.json")
            base = "http://127.0.0.1:%d" % self.port
            with open(cfg, "w") as f:
                json.dump({"chat": base + "/chat?token=" + self.token, "feed": base + "/feed?token=" + self.token, "feedJson": base + "/feed.json?token=" + self.token, "perf": base + "/perf?token=" + self.token, "sid": SID, "api": API, "g1": self.g[0], "g2": self.g[1], "g3": self.g[2], "g4": self.g[3],
                           "reply": "Postgres, the same as production", "store": self.store, "brief": BRIEF, "longBrief": LONG_BRIEF, "g5": SID + ":g5", "g5q": "should the fixtures use the production database name or a scratch one?", "g6": SID + ":g6", "g6q": "which of the two fixture loaders should the CI job run first?", "g6c": SID + ":g6c", "g6cText": "run the second loader under the first's fixtures", "background": BACKGROUND, "twoParaBrief": TWO_PARA_BRIEF, "landing": base + "/?token=" + self.token, "ledger": self.ledger, "order": self.order, "judgeAuth": os.path.join(os.path.dirname(os.path.dirname(self.store)), "judge-auth.json")}, f)
            driver = os.path.join(self.lab, "needsbox.mjs")
            Path(driver).write_text(_lab.NEEDS_BOX_OPEN_JS + DRIVER)   # the fold helper the held-mail lab shares
            try:
                p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=DRIVER_TIMEOUT_S,
                                   env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
            except subprocess.TimeoutExpired as e:
                # the driver ran past its budget (several deadlines in a row): say the record it had reached and what the kernel's tail says, instead
                # of a bare traceback in every test (the second contributor's read of PR 2031)
                out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
                partial = next((ln for ln in reversed(out.splitlines()) if ln.startswith("PARTIAL:")), "(no scene completed)")
                type(self)._fail = "the driver ran past its %d s budget; its record so far: %s; kernel: %s" % (DRIVER_TIMEOUT_S, partial[-3000:], self._kernel_tail())
                self.fail(type(self)._fail)
            if "browser-launch-failed" in p.stderr:
                self._skip("no playwright browser on this box")
            line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT:")), None)
            if line is None:
                type(self)._fail = "the driver produced no RESULT (stderr: %s; kernel: %s)" % (p.stderr[-2000:], open(self.klog).read()[-1500:])
                self.fail(type(self)._fail)
            type(self)._r = json.loads(line[len("RESULT:"):])
        return self._r

    def _built(self, rec, what):
        """The kernel's own build event for a store write, as the driver recorded it: the floor an int of at least 0 (a null floor is the
        pre-write read's own miss), the build id past it (never None, never the floor; a bool passed the old not-None check, since the async
        predicate under waitForFunction resolved at once with False: the second contributor's read of PR 2031). The message prints the record."""
        rec = {k: v for k, v in rec.items() if k != "box"}
        self.assertIsInstance(rec.get("floor"), int, "%s: the feed build id before the write was read (a null floor is its own miss): %r (kernel: %s)" % (what, rec, self._kernel_tail()))
        self.assertGreaterEqual(rec["floor"], 0)
        self.assertIsNotNone(rec.get("built"), "%s: the kernel's feed rebuilt past the write with the brief on the card, polled from the driver (GET /feed.json; a miss carries the pusher's counters): %r (kernel: %s)" % (what, rec, self._kernel_tail()))
        self.assertGreater(rec["built"], rec["floor"], "%s: the build id is past the floor: %r" % (what, rec))

    def _kernel_tail(self):
        try:
            return open(self.klog).read()[-1200:]
        except OSError:
            return ""

    def test_the_box_lists_the_questions_and_the_held_message_under_the_header_in_the_token_and_no_row_for_the_hard_stop(self):
        r = self._result()
        self.assertEqual(r["errors"], [], "no page error")
        self.assertTrue(r["fourRows"], "four rows within a minute: %r (kernel: %s)" % (r["first"], self._kernel_tail()))
        b = r["first"]
        self.assertTrue(b["shown"], "the box shows")
        self.assertEqual(b["head"], "Needs you · 4", "the header: the title with the count")
        self.assertEqual((b["border"], b["borderLeft"], b["dot"]), (TOKEN_RGB, "1px", TOKEN_RGB), "one thin edge and the dot in the Needs you token: %r" % b)
        ids = [x["id"] for x in b["rows"]]
        self.assertEqual(ids[:3], self.g[:3], "the three questions first, in the frame's order: %r" % ids)
        self.assertEqual(ids[3], "notice:%s:%s:1" % (SID, MID), "then the held message")
        self.assertNotIn(self.g[3], ids, "the hard stop (the focus goal under the on-you API error) has no row")
        hard = r["hardStop"]
        self.assertEqual(hard["col"], "col-needsInput-list", "the feed pane files the focus goal's card under Needs you from the same pushed frame: %r" % hard)
        self.assertTrue(any("Prompt too long" in t for t in hard["badges"]), "wearing the on-you API error badge, the hard stop the box leaves out: %r" % hard)
        self.assertTrue(any(x["id"] == self.g[0] for x in b["rows"]), "the questions are on the box while the hard stop is not")
        for row, q in zip(b["rows"][:3], QUESTIONS):
            self.assertEqual(row["title"], q, "the card's text is the row's title")
            self.assertEqual(row["buttons"], ["Reply", "Clear"], "a live session's question: Reply and Clear (the user 2026-09-23: no Continue button for now)")
            self.assertEqual(row["disabled"], [False, False], "two buttons, both live")
        self.assertEqual(b["rows"][3]["buttons"], ["Approve", "Deny"], "the held message keeps its stored actions")
        self.assertIn("ring-needs-you", b["tabClasses"] or "", "the tab wears the red Blocked ring for the hard stop (it outranks the Needs you ring): %r" % b["tabClasses"])
        self.assertIn("ring-waiting-on-you", (b["tabs"] or {}).get(API) or "", "api's tab, a question and no hard stop, wears the Needs you ring: %r" % b["tabs"])

    def test_a_brief_landing_on_a_card_reaches_its_row_with_no_gesture(self):
        r = self._result()
        self._built(r["brief"], "the short brief")
        self.assertTrue(r["brief"]["landed"], "the row's body follows the brief written to the store within the next frames: %r (kernel: %s)" % (r["brief"], self._kernel_tail()))
        row = next((x for x in r["brief"]["box"]["rows"] if x["id"] == self.g[0]), None)
        self.assertEqual(row and row["body"].strip(), BRIEF, "the brief is the row's line (the card's distill line since the box content round; before it the face rendered it as markdown, with its trailing newline)")
        self.assertEqual(r["brief"]["box"]["head"], "Needs you · 4", "and nothing else moved")

    def test_a_long_brief_gets_a_disclosure_on_its_row_that_lifts_the_clamp_and_folds_back(self):
        """The second contributor's review (2026-09-22): the row clamped the brief to four lines with no way to the rest. A More button
        shows once the body overflows, opens the row (the clamp lifted, the whole brief on screen), reads Less, and folds the row back."""
        r = self._result()
        m = r["more"]
        self._built(m, "the long brief")
        self.assertTrue(m["landed"], "the long brief reaches the row after the kernel's build (the read waits for it): %r (kernel: %s)" % ({k: v for k, v in m.items() if k != "box"}, self._kernel_tail()))
        self.assertTrue(m["clipped"], "and the layout clips it at four lines (the brief is long enough for any width): %r" % m["before"])
        self.assertTrue(m["shown"], "the More button shows on a brief past the clamp: %r" % m)
        self.assertEqual((m["before"] or {}).get("label"), "More"); self.assertEqual((m["before"] or {}).get("open"), False)
        self.assertTrue((m["before"] or {}).get("clipped"), "the body hides lines before the click: %r" % m["before"])
        self.assertEqual((m["before"] or {}).get("clamp"), "4", "the clamp stands on a closed row")
        self.assertTrue(m["open"], "the click opens the row")
        self.assertEqual((m["after"] or {}).get("clamp"), "none", "the clamp lifted: %r" % m["after"])
        self.assertFalse((m["after"] or {}).get("clipped"), "the whole brief is on screen")
        self.assertEqual((m["after"] or {}).get("label"), "Less"); self.assertEqual((m["after"] or {}).get("text"), LONG_BRIEF)
        self.assertTrue(m["closed"], "the second click folds the row back")
        self.assertEqual(m["box"]["head"], "Needs you · 4", "a disclosure is not a decision: nothing else moved")

    def test_a_brand_new_long_brief_row_and_a_rebuilt_row_both_get_the_disclosure(self):
        """The round-thirteen verifier (2026-09-22): the disclosure was measured while the row was still detached (built, then joined), so a
        fresh row with a long brief never got its button, nor did the rows the switch's off-then-on rebuilt; the first scene passed because it
        mutated a row already in the document. The measure runs over the rows once they stand in the box."""
        r = self._result()
        self._built(r["fresh"], "the fresh row")
        self.assertTrue(r["fresh"]["row"], "the new card's row arrives: %r (kernel: %s)" % ({k: v for k, v in r["fresh"].items() if k != "box"}, self._kernel_tail()))
        self.assertTrue(r["fresh"]["landed"] and r["fresh"]["clipped"], "with its long brief, clipped: %r" % r["fresh"])
        self.assertTrue(r["fresh"]["more"], "and wears the More button with no gesture (before: measured detached, 0 by 0, no button): %r" % r["fresh"]["box"])
        self.assertNotIn(r["fresh"]["moreAtItems"], ("none", "absent"), "at the items level the button shows too: the line is clamped there and More opens it (the box content round; before it the body and its button hid below the full context): %r" % r["fresh"]["moreAtItems"])
        self.assertTrue(r["on"]["shown"]); self.assertTrue(r["on"]["moreAfterRebuild"], "the rebuilt row wears it too (before: none after the switch's off-then-on)")

    def test_a_pane_hidden_while_a_long_brief_row_arrives_gets_its_disclosure_when_shown(self):
        """The first contributor's post-merge review of PR 1967 (low 1): a disclosure measured in a display:none pane read zero by zero and
        removed a closed row's button or left a fresh row without one until the next repaint. A zero measure is no information, and the
        chat visibility watcher's return edge (hidden, then visible) re-runs the pass, so the button appears when the pane is shown."""
        r = self._result(); h = r["hiddenPane"]
        self._built(h, "the hidden pane's row")   # the fourth scene's record, asserted (the second contributor's read of PR 2031: recorded and read by nothing)
        self.assertTrue(h["frame"] and h["loaded"] and h["hidden"] and h["row"] and h["landed"], "the shell's chat pane, shown once then hidden by the rail, builds the fresh row with its brief while hidden: %r (kernel: %s)" % (h, self._kernel_tail()))
        self.assertEqual((h["whileHidden"] or {}).get("h"), 0, "hidden, the body measures zero: %r" % h["whileHidden"])
        self.assertTrue(h["g5MoreBefore"], "the earlier long-brief row's button stood before the hide")
        self.assertTrue((h["whileHidden"] or {}).get("g5More"), "and stands while hidden: a zero measure is no information (with the guard deleted the pass removes it): %r" % h["whileHidden"])
        self.assertTrue(h["moreAfterShow"], "shown, the pane's return re-measures and the button appears (before: none until the next repaint): %r" % h)
        self.assertTrue(h["clipped"], "and the brief is clipped at four lines once laid out")

    def test_a_clear_the_clears_log_refuses_leaves_the_row_and_re_arms_its_buttons_and_says_so(self):
        r = self._result()
        d = r["refused"]
        self.assertIn("That clear did not land", d["dialog"] or "", "the dialog says so: %r" % d["dialog"])
        self.assertIn("nothing was cleared", d["dialog"] or "")
        self.assertTrue(d["rearmed"], "the row's buttons let go on the kernel's reply (they latched on the press): %r" % d["box"])
        self.assertIn(self.g[2], [x["id"] for x in d["box"]["rows"]], "the row stays")
        self.assertEqual(d["box"]["head"], "Needs you · 4")
        self.assertEqual(d["rowErr"], "That clear did not land", "and the row says why, the frame's title alone (the verifier's low: no doubled refusal): %r" % d["rowErr"])

    def test_a_frame_changing_only_the_continue_flag_leaves_the_refusal_line_and_the_buttons_alone(self):
        """The box arc's round three: the Continue flag left the row signature in PR 2105 with a source pin alone. Executed: the session's
        latest kernel status frame, with every row's Continue flag flipped and nothing else (no liveness change, nothing read in the composer),
        is posted to the page as the kernel's frames arrive, and the refused row keeps its refusal line and its re-armed buttons once the page
        has handled it (with the flag in the signature the row was rebuilt: the line wiped, a latched Clear re-enabled). The flip back posts
        the kernel's latest status unmodified, so the later scenes run on the kernel's flags."""
        r = self._result(); sf = r["sigFlip"]
        self.assertEqual(sf["before"]["err"], "That clear did not land", "premise: the refusal line stands before the flip: %r" % sf["before"])
        self.assertTrue(sf["before"]["haveStatus"], "premise: the session's latest status with the box's rows is in hand: %r" % sf["before"])
        self.assertIn(True, sf["before"]["cont"] or [], "premise: a live session's rows carry the Continue offer, so the flip changes the flag")
        self.assertEqual((sf["flip"]["posted"], sf["flip"]["handled"]), (True, True), "the frame with every row's flag flipped and nothing else was posted and handled: %r" % sf["flip"])
        self.assertEqual(sf["after"]["err"], "That clear did not land", "the refusal line survives that frame (before: the flag in the signature rebuilt the row and wiped the line): %r" % sf["after"])
        self.assertEqual([b[1] for b in sf["after"]["buttons"]], [False, False], "and the re-armed buttons stay re-armed: %r" % sf["after"])
        self.assertTrue(sf["flipBack"]["handled"], "the kernel's latest status posted back unmodified and handled: %r" % sf["restored"])
        self.assertEqual(sf["restoredFlags"], sf["kernelFlags"], "after the flip back the rows' Continue flags read the kernel's (the round-two review: the flipped copy was reposted and later scenes ran on flipped flags): %r" % sf)
        self.assertEqual(sf["flippedFlags"], [not f for f in sf["kernelFlags"]], "and the flipped frame differed from the kernel's in the flags alone")

    def test_clear_takes_its_row_off_the_box_with_the_next_frame(self):
        r = self._result()
        self.assertTrue(r["clearLatched"], "the row's buttons latch on the press")
        self.assertTrue(r["afterClear"]["left"], "the cleared question's row left: %r (kernel: %s)" % (r["afterClear"]["box"], self._kernel_tail()))
        self.assertEqual(r["afterClear"]["box"]["head"], "Needs you · 3")

    def test_continue_is_not_offered_and_the_second_question_clears_like_the_first(self):
        """The user 2026-09-23: Reply and Clear only for now. The stored offer (the row's cont) and the card's Continue wire stay for a later
        return; the button is gone from the row, and the row's Clear works as the first question's did."""
        r = self._result()
        self.assertEqual(r["secondButtons"], ["Reply", "Clear"], "the live question offers Reply and Clear alone")
        self.assertFalse(r["secondContAct"], "no Continue control on the row")
        self.assertTrue(r["secondLatched"], "the row's buttons latch on the press")
        self.assertTrue(r["afterSecond"]["left"], "the cleared question's row left: %r (kernel: %s)" % (r["afterSecond"]["box"], self._kernel_tail()))
        self.assertEqual(r["afterSecond"]["box"]["head"], "Needs you · 2")

    def test_the_box_is_collapsed_by_default_and_opens_in_two_steps_in_both_themes(self):
        """The user 2026-09-23: collapsed by default like the awaiting box, and successively expandable. Level 0: the header line alone (the label
        with the count), the rows hidden. One click: the items (each title with its buttons), the background paragraphs hidden. A second: the
        full context, the background under each title. The level is the page's state for the session, never a timer; a fresh page starts
        collapsed. Read at each level in the dark theme and the light one."""
        r = self._result()
        for t in ("dark", "light"):
            l0, l1, l2 = r["levels"][t + "0"], r["levels"][t + "1"], r["levels"][t + "2"]
            self.assertEqual((l0["theme"], l1["theme"], l2["theme"]), (t, t, t))
            self.assertEqual((l0["level"], l0["head"], l0["headVisible"]), (0, "Needs you · 4", True), "%s: collapsed, the header line alone: %r" % (t, l0))
            self.assertEqual((set(l0["rowsVisible"]), l0["caret"]), ({False}, "\u25b8"), "%s: level 0 shows no row, the caret pointing right: %r" % (t, l0))
            self.assertEqual((set(l0["laidTitles"]), l0["laidButtons"]), ({False}, [0, 0, 0, 0]), "%s: level 0 lays out no title and no button (by rect: a hidden ancestor keeps a child's computed display): %r" % (t, l0))
            self.assertEqual((l1["level"], set(l1["rowsVisible"]), set(l1["bodiesVisible"])), (1, {True}, {False}), "%s: one click shows the items and no background: %r" % (t, l1))
            self.assertEqual([row["buttons"] for row in l1["rows"]], [["Reply", "Clear"]] * 3 + [["Approve", "Deny"]], "%s: the buttons stand at level 1" % t)
            self.assertEqual((set(l1["laidTitles"]), l1["laidButtons"]), ({True}, [2, 2, 2, 2]), "%s: level 1 lays out every title and both buttons of every row (the second contributor's post-merge review of PR 2093: a display read passed with them hidden): %r" % (t, l1))
            self.assertEqual((l2["level"], set(l2["rowsVisible"]), l2["caret"]), (2, {True}, "\u25be"), "%s: a second click shows the full context, the caret down: %r" % (t, l2))
            self.assertTrue(any(l2["bodiesVisible"]), "%s: at level 2 a background paragraph shows where the row has one: %r" % (t, l2))
            # the header's rule is transparent while collapsed and drawn once open, in each theme; the next step is the header's title (the same review: neither read)
            self.assertEqual(l0["head2"]["border"], "rgba(0, 0, 0, 0)", "%s: collapsed, no rule under the header line: %r" % (t, l0["head2"]))
            self.assertNotEqual(l1["head2"]["border"], "rgba(0, 0, 0, 0)", "%s: open, the rule is drawn: %r" % (t, l1["head2"]))
            self.assertEqual((l0["head2"]["title"], l1["head2"]["title"], l2["head2"]["title"]), ("Show the items", "Show the full context", "Collapse"), "%s: the header's title names the next step" % t)
            self.assertEqual((l0["head2"]["expanded"], l1["head2"]["expanded"], l2["head2"]["expanded"]), ("false", "true", "true"), "%s: the expanded state follows the level" % t)
        self.assertTrue(r["hiddenPane"].get("collapsedFresh"), "a fresh page starts collapsed: %r" % r["hiddenPane"])
        self.assertEqual(r["reload"]["before"], 2, "premise: the page stood at the full context before its reload")
        self.assertEqual((r["reload"]["box"]["level"], set(r["reload"]["box"]["rowsVisible"])), (0, {False}), "the SAME page reloaded starts collapsed with its rows attached and hidden (the second contributor's post-merge review of PR 2093: a new context would pass a level kept in localStorage): %r" % r["reload"]["box"])

    def test_the_keyboard_reaches_the_header_enter_opens_the_items_and_tab_lands_on_reply(self):
        """The second contributor's post-merge review of PR 2093 (the regression): level 0 hid every row and the header was a plain div, so
        Tab and Shift+Tab never stopped inside the box where before the levels they reached every row's buttons. The header is a button
        with a tab stop: Shift+Tab from the composer enters the box on it, Enter opens the items with the expanded state saying so, and
        Tab from there lands on the first row's Reply. Pinned by order, not press count."""
        r = self._result(); k = r["keys"]
        self.assertTrue(k["entered"], "Shift+Tab from the composer enters the box within the walk: %r" % k)
        self.assertEqual((k["landed"]["head"], k["landed"]["act"]), (True, "ntc-fold"), "on the header, the fold control: %r" % k["landed"])
        self.assertTrue(k["opened"], "Enter opens the items: %r" % k)
        self.assertEqual((k["afterEnter"]["level"], k["afterEnter"]["head2"]["role"], k["afterEnter"]["head2"]["tabIndex"], k["afterEnter"]["head2"]["expanded"]), (1, "button", 0, "true"), "level 1, a button with a tab stop, expanded: %r" % k["afterEnter"]["head2"])
        self.assertEqual(k["afterEnter"]["head2"]["caretHidden"], "true", "the caret is decoration to assistive tech")
        self.assertRegex(((k.get("headName") or "").splitlines() or [""])[0], r'^- button "Needs you · \d+"$', "the computed accessible name on the standalone page: the label's text, a button (no gear here): %r" % k.get("headName"))
        self.assertTrue(k["focusAfterEnter"]["head"], "focus stays on the header after Enter: %r" % k["focusAfterEnter"])
        self.assertEqual((k["afterTab"]["inBox"], k["afterTab"]["text"], k["afterTab"]["act"]), (True, "Reply", "ntc-reply"), "Tab lands on the first row's Reply: %r" % k["afterTab"])
        self.assertTrue(k.get("spaced"), "Space on the header advances the level too (the box arc's round three): %r" % k.get("focusAfterSpace"))
        self.assertTrue((k.get("focusAfterSpace") or {}).get("head"), "and focus stays on the header")

    def test_the_bars_edges_and_the_strip_beside_the_gear_open_the_box(self):
        """The second contributor's review of PR 2120: with the padding on the bar and the fold action on the header alone, a click on the bar's
        top and bottom strips, its left edge, the gap before the gear and the margin right of it did nothing where at the base each opened the
        box. The padding is the header's again and the bar carries the fold action too: a click at the bar's top-left corner opens the items on
        the standalone page, and in the shell a click in the gear's right margin, the bar's own strip, toggles the level while a click on the
        gear leaves it alone (the gear scene)."""
        r = self._result(); e = r["edgeClick"]
        self.assertTrue(e["opened"], "a click at the bar's (left + 3, top + 2) at level 0 opens the items: %r" % e)
        self.assertEqual(e["cursor"], "pointer", "the bar shows the fold's cursor")
        m = r["marginClick"]
        self.assertNotEqual(m["after"], -1, "in the shell a click in the gear's right margin, the bar's own strip, toggles the level: %r" % m)
        self.assertNotEqual(m["after"], m["levelBefore"])

    def test_the_level_is_the_sessions_own(self):
        """The second contributor's post-merge review of PR 2093: the level pin spelled the code, so a mutant copying the last level to a
        session not seen before passed. web at the full context, api's box reads collapsed; back on web the level stands."""
        r = self._result(); ps = r["perSession"]
        self.assertEqual(([x["id"] for x in ps["api"]["rows"]], ps["api"]["level"], set(ps["api"]["rowsVisible"])), ([API + ":g1"], 0, {False}), "api's one question, collapsed (the rows attached and hidden): %r" % ps["api"])
        self.assertEqual(([x["id"] for x in ps["back"]["rows"]][:3], ps["back"]["level"]), (self.g[:3], 2), "back on web, the full context stands: %r" % ps["back"])

    def test_a_credential_row_floors_the_box_at_the_items(self):
        """The second contributor's post-merge review of PR 2093: a refused judge credential hid at level 0 under a header identical to a
        question's. While the row shows, the box stands at the items with no click, and the header's click goes to the full context and
        back to the items, never to the header line; the other session is untouched."""
        r = self._result(); f = r["floor"]
        self.assertTrue(f["row"], "the judge-auth latch seeded for api makes its card the Fix credential row: %r (kernel: %s)" % ({k: v for k, v in f.items() if k not in ("shown", "after", "web")}, self._kernel_tail()))
        self.assertEqual((f["shown"]["level"], set(f["shown"]["rowsVisible"]), [x["buttons"] for x in f["shown"]["rows"]]), (1, {True}, [["Fix credential\u2026"]]), "the items shown with no click, the fix as the row's one action: %r" % f["shown"])
        self.assertEqual(f["shown"]["head"], "Needs you · 1", "the count stays (the reference's no-Clear reason)")
        self.assertTrue(f["up"], "a click goes to the full context")
        self.assertTrue(f["down"], "the next comes back to the items, not the header line: %r" % f["after"])
        self.assertEqual((f["after"]["level"], f["after"]["head2"]["expanded"]), (1, "true"))
        self.assertEqual(f["shown"]["bodiesVisible"], [True], "the fault's explanation, the row's body, shows at the items (the box arc's round three: it hid with every body): %r" % f["shown"])
        self.assertEqual(f["shown"]["head2"]["title"], "Show the full context", "the title names the next step at the floor")
        self.assertEqual(f["after"]["head2"]["title"], "Show the full context", "and after the round trip too: 'Collapse' is never said where the next click cannot fold to the header line")
        self.assertEqual(f["web"]["level"], 2, "web's box stands where it was: %r" % f["web"])

    def test_the_title_at_the_floored_full_context_says_hide_the_full_context(self):
        """The round-one verifier of PR 2120: at the floor from the full context the next click descends to the items, and the title read 'Show
        the items' while the items already showed. The title is named by the transition: descending it says 'Collapse' only where the next
        level is the header line, else 'Hide the full context'."""
        r = self._result(); f = r["floor"]
        self.assertTrue(f["up"], "premise: the click to the full context at the floor ran")
        self.assertEqual((f["atTwo"]["level"], f["atTwo"]["head2"]["title"]), (2, "Hide the full context"), "the next click descends to the items, not the header line: %r" % f["atTwo"]["head2"])

    def test_the_floor_releases_to_the_items_when_the_credential_row_leaves(self):
        """The box arc's round three: a click at the floor stored the level after the SHOWN one, so two clicks from the items stored 0 and the
        box dropped to its header line when the credential row left. The click stores the maximum of that and the floor; the seed removed, the
        row leaves and the items stay."""
        r = self._result(); f = r["floor"]
        self.assertTrue(f["up"] and f["down"], "premise: the two clicks at the floor ran")
        self.assertTrue(f["released"], "the seed removed, the credential row leaves: %r (kernel: %s)" % ({k: v for k, v in f.items() if k in ("row", "up", "down", "released")}, self._kernel_tail()))
        self.assertEqual((f["afterRelease"]["level"], f["afterRelease"]["head"]), (1, "Needs you · 1"), "the box keeps the items when the row leaves (before: 0 stored, the box dropped to its header line): %r" % f["afterRelease"])
        self.assertEqual(f["reusedRow"], {"fault": False, "bodyLaid": False, "lineLaid": True, "hasBody": True}, "the reused row lost the fault class and its markdown body is hidden again at the items, the card's line showing in its place (a class never removed would keep the body showing; the box content round): %r" % f["reusedRow"])

    def test_where_the_gear_is_drawn_the_keyboard_meets_it_then_the_header_named_by_its_label(self):
        """The round-one verifier of PR 2105: the order pin ran only on the standalone page, where no gear is drawn, and the gear nested in the
        header's button was folded into the header's accessible name. In the shell: Shift+Tab from the composer enters the box on the gear, one
        more lands on the header, whose name is its label alone through aria-labelledby; Enter opens the items; Tab goes to the gear, then Reply."""
        r = self._result(); k = r["shellKeys"]
        self.assertTrue(k["entered"], "Shift+Tab from the composer enters the box within the walk: %r" % k)
        self.assertEqual(k["first"]["act"], "ntc-gear", "the gear, the header's last control, is the first stop backwards: %r" % k["first"])
        self.assertEqual((k["second"]["head"], k["second"]["labelledby"]), (True, "ntc-label"), "then the header, named by its label alone (before: the gear's name folded into it): %r" % k["second"])
        self.assertRegex(k["second"]["labelText"] or "", r"^Needs you · \d+$", "the label's text is the title with the count (the mechanism's witness): %r" % k["second"])
        self.assertNotIn("settings", k["second"]["labelText"] or "", "the gear's label is not in the label")
        first = (k.get("headName") or "").splitlines()[0] if k.get("headName") else ""
        self.assertRegex(first, r'^- button "Needs you · \d+"', "the COMPUTED accessible name, read from the browser's accessibility tree, is the label's text alone (the post-merge review of PR 2108: a label with an aria-label of its own renamed the header while the attribute pin passed): %r" % k.get("headName"))
        self.assertNotIn("settings", first, "and nothing of the gear in it")
        self.assertTrue(k["opened"], "Enter opens the items")
        self.assertEqual(k["afterTab1"]["act"], "ntc-gear", "Tab from the header: the gear: %r" % k["afterTab1"])
        self.assertTrue(k.get("gearEnterOpened"), "Enter on the focused gear opens the settings card (the box arc's round three: a key on the gear is the gear's own): %r" % k)
        self.assertEqual((k.get("levelBeforeGearEnter"), k.get("levelAfterGearEnter")), (1, 1), "and leaves the level alone")
        self.assertEqual(k.get("headFocusable"), 0, "the header has no focusable descendant: the gear is its sibling in the bar (axe nested-interactive)")
        self.assertEqual((k["afterTab2"]["inBox"], k["afterTab2"]["text"], k["afterTab2"]["act"]), (True, "More", "ntc-more"), "then the first row's More: its long brief is clamped at the items too since the box content round, and the disclosure comes before the buttons (before the round: no line and no button below the full context, so Tab reached Reply): %r" % k["afterTab2"])
        self.assertEqual((k["afterTab3"]["inBox"], k["afterTab3"]["text"], k["afterTab3"]["act"]), (True, "Reply", "ntc-reply"), "then the first row's Reply: %r" % k["afterTab3"])

    def test_the_headers_gear_opens_the_settings_at_the_boxes_section_in_the_shell(self):
        """The second contributor's post-merge review of PR 2093: the strip's gear, the only section-targeted opener, lands on Tab strip
        with the box's section out of view above it, so the body's diagnosis and the change did not meet. The section stays where a scan
        of the heads finds it, and the header wears its own gear, drawn where a settings card can open: in the shell its click opens the
        Chat tab with the Boxes section and its row in the card's view, and the box's level does not move."""
        r = self._result(); g = r["gear"]
        self.assertTrue(g["present"], "the gear is drawn in the shell's chat pane: %r" % g)
        self.assertTrue(g["opened"] and g["frame"], "its click opens the settings card: %r" % g)
        self.assertTrue(g.get("mark"), "the landing's own mark, data-section-landed=boxes, on the card (a plain settings open shows the section in this window too; the box arc's round three): %r" % g)
        self.assertTrue(g["landed"], "with the Boxes section head inside the card's view: %r" % g)
        self.assertEqual((g["view"]["shown"], g["view"]["headText"], g["view"]["headInView"], g["view"]["rowInView"]), (["chat"], "Boxes below the transcript", True, True), "the Chat tab, the section and the switch's row in view: %r" % g["view"])
        self.assertEqual((g["levelBefore"], g["levelAfter"]), (2, 2), "the gear's click is the gear's, not the fold's")
        self.assertFalse(r["first"]["head2"]["gear"], "the standalone chat page, where no settings card can open, draws none")

    def test_reply_points_the_composer_at_the_card_and_the_typed_reply_takes_the_row_off(self):
        r = self._result()
        self.assertEqual(r["chip"], QUESTIONS[0], "the composer's chip names the card, as a feed card click that lands in the chat does")
        self.assertTrue(r["rowStaysOnReply"], "Reply alone leaves the row: the reply is not written yet")
        self.assertTrue(r["afterReply"]["left"], "the typed reply is a follow-up on the card and its row left: %r (kernel: %s)" % (r["afterReply"]["box"], self._kernel_tail()))
        self.assertEqual(r["afterReply"]["box"]["head"], "Needs you · 1", "the held message alone remains")

    def _content(self):
        r = self._result(); c = r["content"]
        flat = {k: v for k, v in c.items() if not isinstance(v, dict)}
        self.assertTrue(c.get("frame") and c.get("feedFrame"), "the shell's chat pane and its feed pane, shown for the scene: %r" % flat)
        self._built(c, "the card's other faces")
        self.assertTrue(c.get("cardReady"), "the card wears the Background toggle and the origin badge once the build reaches the feed page: %r (kernel: %s)" % (c.get("cardL1"), self._kernel_tail()))
        return c   # the row's own repaint is each test's pin, not a premise here: a page before the round reds each test on its own line

    def test_a_pick_made_on_the_row_while_no_feed_document_is_up_stands_when_one_comes_up(self):
        """The verifier's round two, with the premise made real in round four (the shell loads the feed document at boot, so a pick before the feed
        pane is shown reaches a live owner): the feed's frame is navigated away, Background is picked on the row with nobody to hear it, and the
        feed document comes back and posts the map it hydrated, which knows nothing of the pick. A follower keeps its own picks over a received
        map and re-posts them, so the card comes up showing Background (before: the map overwrote the row's pick)."""
        c = self._content(); e = c.get("noOwner") or {}
        self.assertTrue(e.get("blank"), "the feed document is down while the row picks: %r" % e)
        self.assertTrue(e.get("pressed") and e.get("rowPressed"), "Background pressed on the row with no owner up: %r" % e)
        self.assertTrue(e.get("cardUp"), "the feed document back with the card: %r" % e)
        self.assertTrue(e.get("cardFollowed"), "the card shows Background: the row's own pick stood over the hydrated map and reached the owner (before: the map overwrote it): %r" % e)
        self.assertEqual(e.get("rowStill"), "true", "and the row still holds it: %r" % e)

    def test_the_row_at_the_items_level_shows_the_card_at_a_glance(self):
        """The user 2026-09-23, from a screenshot: a row at the items level showed its title and two buttons alone, while the feed card carried a
        brief, sections and badges. The row carries what the card carries (plans/needs-you.md): at the items level the title, the card's default-open
        section (the distill line, clamped to four lines), the badges the card's name row wears, then Reply and Clear; the session name, the age and
        the section toggles stay off it. Read on the shell against the same item's card in the feed pane."""
        c = self._content(); card, row = c["cardL1"], c["rowL1"]
        self.assertIsNotNone(row, "the row stands in the shell's chat pane: %r" % c.get("rowL1"))
        self.assertEqual(row["title"], card["title"], "the same title as the card: %r vs %r" % (row, card))
        self.assertTrue(c.get("rowLanded"), "the row repaints with the badge (the frame's key carries the whole row; before: no badge element on the row): %r" % row)
        self.assertEqual(row["distill"], card["distill"], "the card's default-open section under the title, the distill line (before: the row had no such element): %r vs %r" % (row, card))
        self.assertEqual(row["distill"], LONG_BRIEF); self.assertTrue(row["bodies"]["distill"], "shown at the items level: %r" % row)
        self.assertEqual(row["clamp"], "4", "clamped there like the brief was, More past it: %r" % row)
        self.assertEqual(row["badges"], card["badges"], "the card's badges on the row (before: none): %r vs %r" % (row, card))
        self.assertEqual((card.get("chip") or {}).get("tag"), "BUTTON", "the card's warning chip is the button that opens the detail: %r" % card.get("chip"))
        self.assertEqual((card.get("chip") or {}).get("cursor"), "pointer", "and shows the hand: %r" % card.get("chip"))
        self.assertEqual(((row.get("chip") or {}).get("tag"), (row.get("chip") or {}).get("act"), (row.get("chip") or {}).get("cursor")), ("SPAN", None, "auto"), "the row's chip is a span with no act and the default cursor (the contributor's note on the 0.17.1 fix: the shared rule gave the span the hand and the hover tint): %r" % row.get("chip"))
        self.assertEqual(row["badges"], ["\u21aa from api", "distill failed"], "the delegation's origin and the warning chip (every warn the distiller's own), as the card words them: %r" % row["badges"])
        self.assertEqual(card.get("relay"), {"text": "a question to api is still parked on the far host: it went on before it could be withdrawn", "shown": True}, "the card draws the relayed question a far host still holds as its own dim line: %r" % card.get("relay"))
        self.assertEqual(row.get("relay"), card.get("relay"), "and so does the row, through the same helper (before: the note rode the row's wire and key and was never drawn): %r vs %r" % (row.get("relay"), card.get("relay")))
        self.assertFalse(row["togglesShown"], "the section toggles wait for the full context: %r" % row)
        self.assertFalse(row["nameOrAge"], "no session name and no age on the row (the box is the session's own): %r" % row)
        self.assertEqual(row["buttons"], ["Reply", "Clear"])

    def test_the_row_at_the_full_context_shows_the_cards_toggles_in_the_cards_order_and_the_same_bodies(self):
        """The full context shows the card's section toggles in the card's order (Background, Summary, the sub-goals here), with the card's labels
        and pressed states, driving the same bodies with the same one-open rule and default (plans/needs-you.md)."""
        c = self._content(); card, row = c["cardL2"], c["rowL2"]
        self.assertTrue(row["togglesShown"], "the toggles show at the full context: %r" % row)
        self.assertEqual(row["toggles"], card["toggles"], "the card's toggles, labels and pressed states in the card's order (before: the row had none): %r vs %r" % (row, card))
        self.assertEqual([t["label"] for t in row["toggles"]][:2], ["Background", "Summary"], "the card's order: %r" % row["toggles"])
        self.assertEqual(len(row["toggles"]), 3, "and the sub-goals toggle for the child seeded: %r" % row["toggles"])
        self.assertEqual([t["pressed"] for t in row["toggles"]], ["false", "true", "false"], "the default: the summary open, one section at a time: %r" % row["toggles"])
        self.assertEqual(row["bodies"], card["bodies"]); self.assertEqual(row["bodies"], {"bg": False, "distill": True, "stall": False, "tree": False})

    def test_a_press_on_the_rows_toggle_reaches_the_card_and_a_press_on_the_card_reaches_the_row(self):
        """The disclosure is the item's, not the element's (the card's twin rule): the row and the card are two documents in the shell, and a
        pick on either reaches the other (card-sections.ts, the channel). Background pressed on the row opens it on the card; Summary pressed on the
        card reopens it on the row."""
        c = self._content()
        self.assertTrue(c["rowPressBg"], "the row's Background toggle was there to press")
        self.assertTrue(c["cardFollowed"], "the card follows the row's press (before: the row had no toggle, and a card's pick stayed in its document): %r" % c["cardAfterRowPress"])
        self.assertEqual(c["rowAfterRowPress"]["toggles"], c["cardAfterRowPress"]["toggles"])
        self.assertEqual([t["pressed"] for t in c["rowAfterRowPress"]["toggles"]], ["true", "false", "false"], "Background open on both, the summary closed: %r" % c["rowAfterRowPress"])
        self.assertEqual(c["rowAfterRowPress"]["bodies"], {"bg": True, "distill": False, "stall": False, "tree": False}); self.assertEqual(c["cardAfterRowPress"]["bodies"], c["rowAfterRowPress"]["bodies"])
        self.assertTrue(c["cardPressSummary"] and c["rowFollowed"], "the row follows the card's press: %r" % c["rowAfterCardPress"])
        self.assertEqual(c["rowAfterCardPress"]["toggles"], c["cardAfterCardPress"]["toggles"])
        self.assertEqual([t["pressed"] for t in c["rowAfterCardPress"]["toggles"]], ["false", "true", "false"])
        self.assertEqual(c["rowAfterCardPress"]["bodies"], {"bg": False, "distill": True, "stall": False, "tree": False}); self.assertEqual(c["cardAfterCardPress"]["bodies"], c["rowAfterCardPress"]["bodies"])

    def test_a_section_pick_re_runs_the_rows_more_pass(self):
        """Round three of the box content PR (a contributor's review): a pick re-applied the sections and left the row's More stale, standing with
        nothing to open once the line was hidden and missing once the line came back clipped. The chat page's afterApply hook (card-sections.ts
        SectionEnv, called last in every re-apply) runs the More pass. No store write between a press and its read. Both directions (the
        contributor's note on the 0.17.1 fix: the open direction alone let a pass run only for an open row through): the CLOSED row first
        (Background: the line hidden, More gone; Summary: the clipped line with More), then the OPEN row (More pressed: Less goes with the
        hidden line and comes back with it)."""
        c = self._content(); pk = c.get("pick") or {}
        self.assertTrue((pk.get("before") or {}).get("more"), "the premise: the long brief's line is clipped and More stands: %r" % pk.get("before"))
        cb = pk.get("closedBg") or {}; cs = pk.get("closedSummary") or {}
        self.assertTrue(cb.get("pressed") and cb.get("row"), "Background pressed on the CLOSED row: %r" % cb)
        self.assertEqual(((cb.get("face") or {}).get("line"), (cb.get("face") or {}).get("more")), (False, False), "closed row, Background open: the line hidden and More gone (the first note on PR 2124: More stood stale; a pass run only for an open row leaves it): %r" % cb.get("face"))
        self.assertTrue(cs.get("pressed") and cs.get("row"), "Summary pressed back on the closed row: %r" % cs)
        self.assertEqual(((cs.get("face") or {}).get("line"), (cs.get("face") or {}).get("more"), (cs.get("face") or {}).get("moreLabel")), (True, True, "More"), "the clipped line back with its More: %r" % cs.get("face"))
        self.assertTrue(pk.get("opened") and (pk.get("beforeOpen") or {}).get("moreLabel") == "Less", "More pressed: the brief open, the button reads Less: %r" % pk.get("beforeOpen"))
        self.assertTrue(pk.get("pressedBg") and pk.get("rowBg"), "Background pressed on the row: %r" % {k: v for k, v in pk.items() if not isinstance(v, dict)})
        self.assertEqual(((pk.get("afterBg") or {}).get("line"), (pk.get("afterBg") or {}).get("more")), (False, False), "Background open: the line hidden and its button gone with it, Less included (the 0.17.1 fix; before: Less stood over the hidden line): %r" % pk.get("afterBg"))
        self.assertTrue(pk.get("pressedSummary") and pk.get("rowSummary"), "Summary pressed back: %r" % {k: v for k, v in pk.items() if not isinstance(v, dict)})
        self.assertEqual(((pk.get("afterSummary") or {}).get("line"), (pk.get("afterSummary") or {}).get("moreLabel")), (True, "Less"), "the open brief back with Less (the open state kept across the picks): %r" % pk.get("afterSummary"))
        self.assertTrue(pk.get("closed"), "Less folds it back for the scenes after")

    def test_the_items_level_shows_the_clamped_line_whatever_the_pick(self):
        """The manager's ruling on the contributor's review (round three): the items level always shows the card's distill line, clamped with More,
        whatever section is picked; the pick governs the full context only. The row re-applies per level without writing the choice."""
        c = self._content(); pk = c.get("pick") or {}
        ib = pk.get("itemsBefore") or {}
        self.assertEqual((ib.get("line"), ib.get("clamp"), ib.get("more"), ib.get("bg")), (True, "4", True, False), "the items level: the clamped line with More, no paragraph: %r" % ib)
        self.assertTrue(pk.get("cardBg") and pk.get("rowFollowedBg"), "Background picked on the card while the row stands at the items: %r" % {k: v for k, v in pk.items() if not isinstance(v, dict)})
        ia = pk.get("itemsAfterCardBg") or {}
        self.assertEqual((ia.get("line"), ia.get("clamp"), ia.get("more"), ia.get("bg")), (True, "4", True, False), "still the clamped line with More and no paragraph (before: the row showed the whole paragraph unclamped with no More): %r" % ia)
        self._built(pk.get("repaint") or {}, "the repaint with Background picked")
        self.assertTrue(pk.get("repainted"), "the row repainted with the new background paragraph (the premise): %r" % {k: v for k, v in pk.items() if not isinstance(v, dict)})
        ir = pk.get("itemsAfterRepaint") or {}
        self.assertEqual((ir.get("line"), ir.get("clamp"), ir.get("more"), ir.get("bg")), (True, "4", True, False), "and after a repaint with Background picked, the same items face (a contributor's second note: unpinned before; without the level face in the update the repaint showed the paragraph): %r" % ir)

    def test_the_rows_paragraph_stamps_read_the_cards_and_a_part_without_a_time_reads_under_a_minute(self):
        """Round two of the box content PR (the verifier): the row stamped a part with no event time with an age counted from the epoch,
        where the card renders the static "<1m ago"; the stamp rendering is the shared builder's now (card-sections.ts applyDistillLanding),
        on each page's clock with the card's age words, so both pages read the same paragraphs, ages and link."""
        c = self._content(); st = c.get("stamps") or {}
        self._built(st, "the two-paragraph brief")
        flat = {k: v for k, v in st.items() if k not in ("card", "row")}
        self.assertTrue(st.get("cardLanded"), "the card splits the brief into its two stamped paragraphs (the premise): %r" % flat)
        self.assertTrue(st.get("rowLanded"), "and the row too (before: the row had no line to split): %r" % flat)
        card, row = st["card"], st["row"]
        self.assertIsNotNone(row, "the row's line stands: %r" % st)
        self.assertEqual([q["text"] for q in row["paras"]], [q["text"] for q in card["paras"]], "the same paragraphs with the same ages: %r vs %r" % (row, card))
        self.assertEqual(row["paras"][1]["age"], "<1m ago", "a part without an event time reads the static chip, never an age counted from the epoch (before: an epoch-sized age on the row): %r" % row)
        self.assertEqual(row["paras"][0]["age"], card["paras"][0]["age"], "the stamped part: the same words on both pages")
        self.assertEqual((row["link"], row["title"]), (card["link"], card["title"]), "the line is the same link on both pages: %r vs %r" % (row, card))

    def test_the_rows_line_lands_in_the_chat_page_the_way_the_page_lands(self):
        """The row's landing affordances are the card's (the verifier, low e): the line is the same link on both pages, and on the chat page
        its click lands the way the page lands: at the turn the kernel's anchor names (scrollToAnchor), or, when the kernel serves none, in
        the landing toast that says no anchor was recorded. No goal in this lab can carry a validated citation (the synthetic transcript ends
        before every goal, and a goal reaching into it takes the API-error turn and becomes the hard stop), so the executed road here is the
        honest one; the scroll is pinned at the source (ui/webview/card-sections.test.ts, the row's landings)."""
        c = self._content(); st = c.get("stamps") or {}
        flat = {k: v for k, v in st.items() if k not in ("card", "row")}
        self.assertTrue((st.get("card") or {}).get("link"), "the card's line is a link (the premise): %r" % st.get("card"))
        self.assertEqual(((st.get("row") or {}).get("link"), (st.get("row") or {}).get("title")), (True, st["card"]["title"]), "the row's line is the same link as the card's (before: the row had no line): %r vs %r" % (st.get("row"), st.get("card")))
        self.assertEqual(st["row"]["title"], "jump to where this was written" if st.get("anchor") else "no anchor recorded for this card", "the link's face says what the click does: %r" % flat)
        self.assertTrue(st.get("landed"), "the click on the row's line lands: the anchored turn on screen, or the landing toast when the kernel served no anchor: %r" % flat)

    def test_a_live_collapsed_flip_on_the_feed_clears_the_rows_picks_too(self):
        """The verifier's round two: the whole-map post in the shared setter was executed by no test (the reload is carried by the load-time map).
        The feed's Collapsed preference flipped live clears every pick through the setter, which posts the map: the row, Background open a
        moment before, reads it unpressed."""
        c = self._content(); cl = c.get("collapsed") or {}
        self.assertTrue(cl.get("rowPick") and cl.get("cardFollowed"), "Background picked on the ROW, the card following: %r" % {k: v for k, v in cl.items() if not isinstance(v, list)})
        self.assertTrue(cl.get("rowCleared"), "the row's Background unpressed after the feed's live Collapsed flip: the feed acknowledged the row's pick, so the flip's map clears it (the 0.17.1 fix; before: the row re-imposed its pick over every map that lacked it): %r" % cl)
        self.assertEqual([t["pressed"] for t in (cl.get("card") or [])], ["false", "false", "false"], "the card shows no section under the Collapsed default: %r" % cl.get("card"))
        self.assertEqual([t["pressed"] for t in (cl.get("row") or [])], ["false", "false", "false"], "and so does the row: its default reads the same Collapsed flag in the browser (before: the row opened Summary): %r" % cl.get("row"))
        for i, rec in enumerate(cl.get("payloads") or []):
            self._built(rec, "payload %d after the flip" % (i + 1))
            self.assertTrue(rec.get("repainted"), "payload %d after the flip repainted the row's background paragraph (the event the later read waits on): %r" % (i + 1, rec))
        self.assertEqual(len(cl.get("payloads") or []), 2, "two payloads observed after the flip: %r" % cl.get("payloads"))
        self.assertEqual([t["pressed"] for t in (cl.get("rowLater") or [])], ["false", "false", "false"], "and stays so two payloads later (before: re-imposed per payload): %r" % cl.get("rowLater"))
        self.assertEqual((cl.get("backRow"), cl.get("backCard")), (True, True), "the flip back with no pick held: no map crosses (the feed's map is unchanged), and each document returns its default to Summary from its own storage listener, no payload between: %r" % {k: cl.get(k) for k in ("backRow", "backCard")})

    def test_the_open_section_is_one_state_across_a_shell_reload(self):
        """The verifier's medium (2): three feed-only writers of the section choice never crossed the channel, so after a reload the card opened
        its persisted pick while the row opened the default. Every write goes through the shared setter now, the feed owns the state and the
        chat page takes the map when it loads: Background picked on the card, the shell reloaded, the row opens Background too."""
        c = self._content(); rl = c.get("reload") or {}
        self.assertTrue(rl.get("pressed") and rl.get("cardPressed"), "Background picked on the card before the reload: %r" % rl)
        self.assertTrue(rl.get("frames") and rl.get("cardUp") and rl.get("rowUp"), "both frames back with the card and the row: %r" % {k: v for k, v in rl.items() if k not in ("card", "row")})
        self.assertTrue(rl.get("rowFollowed"), "after the reload the row opens what the card opens: the feed's persisted pick reaches the chat page over the channel (before: the row opened the default): %r" % rl)
        self.assertEqual(rl["row"], rl["card"], "the same toggles with the same pressed states")
        self.assertEqual([t["pressed"] for t in rl["row"]], ["true", "false", "false"], "Background open on both: %r" % rl["row"])

    def test_the_switch_hides_the_box_and_leaves_the_ring_and_back_on_the_box_returns(self):
        """The user 2026-09-23, who looked for the switch and did not find it: the settings card's own row, under a head named for where the
        box sits, on the Chat tab; its click saves and hides the box, a second brings it back."""
        r = self._result()
        sw = r["switchRow"]
        self.assertTrue(sw.get("present"), "the row renders on the Chat tab: %r" % sw)
        self.assertEqual((sw["pane"], sw["label"], sw["head"], sw["headSection"], sw["checked"]), ("chat", "Needs you box", "Boxes below the transcript", "boxes", True), "a plainly labelled row under its own head, on by default: %r" % sw)
        self.assertTrue(sw.get("rendered"), "the card OPENED and the row is on screen, so the clicks that follow are real ones (the second contributor's post-merge review of PR 2093: the card never opened before): %r" % sw)
        self.assertTrue(r["off"]["hidden"], "the box hides on the row's save: %r" % r["off"]["box"])
        self.assertIn("ring-needs-you", r["off"]["box"]["tabClasses"] or "", "the red ring stays: the switch is the box's alone")
        self.assertIn("ring-waiting-on-you", (r["off"]["box"]["tabs"] or {}).get(API) or "", "and the Needs you ring on api's tab stays too: %r" % r["off"]["box"]["tabs"])
        self.assertTrue(r["on"]["shown"], "back on, the box returns with its rows: %r" % r["on"]["box"])
        self.assertEqual(r["on"]["levelKept"], 2, "at the level the page held for the session, read before any click (the same review: two mutants resetting the level on rebuild passed a read after a fold)")
        self.assertIn("ring-waiting-on-you", (r["on"]["box"]["tabs"] or {}).get(API) or "")


if __name__ == "__main__":
    unittest.main()
