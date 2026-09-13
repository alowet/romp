#!/usr/bin/env python3
"""Tiles, the SERVED leg (the user 2026-09-13, who wanted the chat as a 2×2 or 2×3 grid of sessions side by side, each with
its own composer, instead of switching tabs). Tiles are a LAYOUT of the chat split (tests/test_chat_split_served.py drives
the split itself): the shell's _LANDING_SPLIT_JS lays the first column and the later ones out as a rows×cols grid inside
#chat-pane's own slot — no gutters, the other panes where they were — every tile a column of the same partition at
/chat?col=N&skeleton=1 with its own socket, strip, composer and live-ask; a tile showing one session wears a one-line
header (dot, name, ⋯) in the tab strip's place (render.ts syncTileHead by chat-columns.ts tileHeaderShown); the first
tile keeps the strip for whatever no tile shows.

The node-side test (tests/test_chat_split.py TilesExecute) drives the split script against a DOM stub; this one drives
the REAL page: a hermetic kernel serves the dashboard with EIGHT synthetic sessions, a headless browser opens it once
at 1440×900, and ONE driver run walks the story, each step landing in its own assertion here:
  1. Tiles 2×2 from the palette's door (__rompChatTiles): four chat frames in a 2×2 grid inside #chat-pane (the row's
     other panes untouched), the active session kept in the first tile, three tiles filled from the strip in order, each
     later tile showing ONE session with the tile header and NO tab strip, the first tile's strip listing the other five;
     every tile has its own composer; the first frame never moved (no reload); the tile overlay sits on the first cell;
  2. Tiles 2×3: six frames, tiles 2–6 each one session with the header, the first tile's strip the remaining three;
     each tile ~a third of the chat area wide and the desktop chat (no phone header) at that width;
  3. the light theme (a settings write, as the gear makes one): every tile follows, the seam and the header re-skin;
  4. 2×3 → 2×2 folds the surplus two tiles' sessions back into the first tile;
  5. a reload restores the grid: four frames, the class, the headers;
  6. `focused`: every activeTab a tile posts at its boot says focused:false; a click into a tile's composer posts one
     with focused:true and the feed's activeChat follows it (the kernel lets the feed follow that tile,
     tests/test_kernel_active_chat_relay.py); then a focus from the shell — what a feed card, a deep link or the switcher
     deliver — to a session on the first tile's strip: that column reports it focused:true and the feed's activeChat
     moves to it (review 2026-09-13: the first cut sent every focus message unfocused, and the feed went stale);
  7. Back to tabs: one frame, the row, {v:2, cols:[]} byte for byte, no header, every session on the one strip.
Beside steps 2 and 3, the first tile's + opens the picker: the lifted first frame is the whole viewport (dark and light),
the grid stays a grid around it (review 2026-09-13: the first-cell rule outranked the lift and the picker stayed the size
of its cell). The first frame's document carries a nonce set before the first transition and still there after each: a
moved or re-made iframe loads a new document without it.
Screenshots of the 2×2 and 2×3 states, dark and light, land in $ROMP_TILES_SHOTS (else the lab dir) for the PR — safe by
construction: synthetic sessions, invented notes-api prompt text, placeholder ids, no real session data.
Skips LOUDLY when the extension deps or a playwright browser are absent (CI installs none)."""
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
EXT = os.path.join(ROOT, "vscode-extension")
# Hermetic state BEFORE the loads — they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
from romp_load import load_source
from tests.dist_copy import copy_dist
_cred = load_source("romp_credentials_tiles_served", os.path.join(ROOT, "kernel", "credentials.py"))
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")

# eight synthetic sessions: the notes-api demo world's names; the first is the active one the story starts on
SESSIONS = [("11111111-2222-4333-8444-00000000040%d" % k, name, k)
            for k, name in ((1, "web"), (2, "api"), (3, "tests"), (4, "docs"), (5, "lint"), (6, "deploy"), (7, "search"), (8, "auth"))]
SIDS = [s for s, _, _ in SESSIONS]
NAMES = {s: n for s, n, _ in SESSIONS}
BOARD = len(SESSIONS)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _transcript(sid, tag, cwd, pairs):
    """`pairs` CLOSED user/assistant turns for `sid` (an OPEN turn would invite the boot reconcile to resume it)."""
    out, parent, t = [], None, 1_700_000_000
    filler = ["The ranking pass reads its weights from the notes-api config now.",
              "Tokenizer edge cases (hyphens, quotes) are covered by the new fixture set.",
              "Index rebuild time is dominated by the stemmer; caching its table halves it.",
              "The pagination cursor survives a re-sort because it encodes the sort key too."]
    for i in range(pairs):
        u = "11111111-2222-4333-8444-%02x00000c%04x" % (tag, i)
        a = "11111111-2222-4333-8444-%02x00000d%04x" % (tag, i)
        ts = lambda k: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t + i * 60 + k))
        out.append({"type": "user", "uuid": u, "parentUuid": parent, "timestamp": ts(0), "sessionId": sid, "cwd": cwd,
                    "message": {"role": "user", "content": "please keep going with the search module notes (part %d)" % (i + 1)}})
        body = "\n\n".join(["Note %d." % (i + 1)] + [filler[(i + k) % len(filler)] for k in range(3)])
        out.append({"type": "assistant", "uuid": a, "parentUuid": u, "timestamp": ts(5), "sessionId": sid, "cwd": cwd,
                    "message": {"id": "msg_tiles_%d_%04d" % (tag, i), "type": "message", "role": "assistant", "model": "claude-sonnet-5",
                                "content": [{"type": "text", "text": body}], "stop_reason": "end_turn"}})
        parent = a
    return "\n".join(json.dumps(r) for r in out) + "\n"


# The chat iframes are SAME-ORIGIN with the shell, so every probe reads a tile's document from the shell context.
DRIVER = r"""
import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(process.env.EXT_PKG);
const { chromium } = require("playwright");
const cfg = JSON.parse(fs.readFileSync(process.env.CFG, "utf8"));
let browser;
try { browser = await chromium.launch(); }
catch (e) { console.error("browser-launch-failed: " + e); process.exit(3); }
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const out = { t0: Date.now() };
// every chat column's activeTab reports at the wire, with the column and the `focused` flag (step 6), and every
// activeChat the kernel relays to the feed's socket (the feed's focused-session section is a view of it)
const activeTabs = [], activeChats = [];
await page.routeWebSocket(() => true, (ws) => {   // every pane socket: the chat columns' carry ?col=N (the first none)
  const url = new URL(ws.url()), col = url.searchParams.get("col") || "", app = url.searchParams.get("app") || "";
  const server = ws.connectToServer();
  ws.onMessage((m) => { try { const f = JSON.parse(m); if (f && f.type === "activeTab") activeTabs.push({ col, id: f.id, focused: f.focused }); } catch (e) { /* a non-JSON frame */ } server.send(m); });
  server.onMessage((m) => { if (app === "feed") { try { const f = JSON.parse(m); if (f && f.type === "activeChat") activeChats.push({ id: f.id }); } catch (e) { /* a non-JSON frame */ } } ws.send(m); });
  server.onClose(() => ws.close()); ws.onClose(() => server.close());
});
// the pages' errors, for a death's record (a thrown render is the likeliest way a wait never resolves)
const errors = [];
page.on("pageerror", (e) => errors.push("page: " + String(e).split("\n")[0]));
page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text().slice(0, 300)); });
const die = async (why) => {
  out.ms = Date.now() - out.t0; out.errors = errors.slice(-20);
  try { out.atDeath = await page.evaluate(() => window.__rompChatFrameIds().map((fid) => { const f = document.getElementById(fid); const d = f && f.contentDocument; return { fid, tabs: d ? Array.from(d.querySelectorAll("#tabs .tab[data-id]")).map((t) => t.dataset.id) : null, body: d && d.body ? d.body.className : null, ready: d ? d.readyState : null, empty: d && d.getElementById("no-sessions") ? d.getElementById("no-sessions").textContent : null, tileHead: d && d.getElementById("tile-head") ? d.getElementById("tile-head").textContent : null }; })); } catch (e) { out.atDeath = String(e); }
  fs.writeSync(1, "RESULT:" + JSON.stringify({ ...out, died: why }) + "\n"); await browser.close(); process.exit(0); };
const T = 20000;
const waitFn = async (fn, arg, why) => page.waitForFunction(fn, arg, { timeout: T }).catch(async (e) => { await die(why + " (" + String(e).split("\n")[0] + ")"); });
const waitTabs = (fid, sids) => waitFn(([fid, sids]) => { const f = document.getElementById(fid); const d = f && f.contentDocument; if (!d) return false;
  const ids = Array.from(d.querySelectorAll("#tabs .tab[data-id]")).map((t) => t.dataset.id); return sids.every((s) => ids.includes(s)); }, [fid, sids], fid + " never showed tabs " + sids.join(","));
const waitActive = (fid, sid) => waitFn(([fid, sid]) => { const f = document.getElementById(fid); const d = f && f.contentDocument; const t = d && d.querySelector("#tabs .tab.active[data-id]"); return !!t && t.dataset.id === sid; }, [fid, sid], fid + " never activated " + sid);
const waitBootGone = () => waitFn(() => !document.getElementById("romp-boot"), null, "boot splash never cleared");
const waitFrames = (n) => waitFn((n) => window.__rompChatFrameIds().length === n, n, "never " + n + " chat frames");
// a tile has SETTLED when its page shows its one session: the header up (body.tile-head) and a painted transcript
const waitTileHead = (fid) => waitFn((fid) => { const f = document.getElementById(fid); const d = f && f.contentDocument; if (!d || !d.body) return false;
  const h = d.getElementById("tile-head"); return d.body.classList.contains("tile-head") && !!h && getComputedStyle(h).display !== "none" && !!(h.querySelector(".tile-name") || {}).textContent; }, fid, fid + " never wore the tile header");
const waitPainted = (fid) => waitFn((fid) => { const f = document.getElementById(fid); const d = f && f.contentDocument; if (!d) return false;
  return Array.from(d.querySelectorAll("#content .thread")).some((el) => el.style.display !== "none" && el.children.length > 0); }, fid, fid + " never painted a transcript");
const waitClass = (want) => waitFn((want) => document.getElementById("chat-pane").classList.contains("chat-grid") === want, want, "#chat-pane never " + (want ? "wore" : "dropped") + " .chat-grid");
const clickTab = async (fid, sid) => { const fr = await (await page.$("#" + fid)).contentFrame(); await fr.locator('#tabs .tab[data-id="' + sid + '"]').first().click(); };
const activeIn = (fid) => page.evaluate((fid) => { const f = document.getElementById(fid); const d = f && f.contentDocument; const t = d && d.querySelector("#tabs .tab.active[data-id]"); return t ? t.dataset.id : null; }, fid);
const tabsIn = (fid) => page.evaluate((fid) => { const f = document.getElementById(fid); const d = f && f.contentDocument; return d ? Array.from(d.querySelectorAll("#tabs .tab[data-id]")).map((t) => t.dataset.id) : null; }, fid);
// what a tile's page shows: the header (on, name, dot class, state class), the strip's display, the phone header's display, its composer, its width
const tileOf = (fid) => page.evaluate((fid) => {
  const f = document.getElementById(fid); const d = f && f.contentDocument; if (!d || !d.body) return null;
  const h = d.getElementById("tile-head"), bar = d.getElementById("tabbar"), mh = d.getElementById("mhdr"), ta = d.getElementById("composer-input"), la = d.getElementById("live-ask"), pick = d.getElementById("tile-pick"), ns = d.getElementById("no-sessions");
  const cs = (e) => (e ? getComputedStyle(e).display : null);
  const fr = f.getBoundingClientRect();
  return { headOn: d.body.classList.contains("tile-head"), head: h ? { display: cs(h), name: (h.querySelector(".tile-name") || {}).textContent || "", dot: (h.querySelector(".tab-dot") || {}).className || "", cls: h.className, more: !!h.querySelector('.tile-more[data-act="tile-menu"]') } : null,
           tabbar: cs(bar), mhdr: cs(mh), composer: !!ta && cs(ta) !== "none", liveAsk: !!la, tabs: Array.from(d.querySelectorAll("#tabs .tab[data-id]")).map((t) => t.dataset.id),
           pick: pick ? pick.textContent : null, empty: ns ? ns.textContent : null, width: fr.width, height: fr.height, left: fr.left, top: fr.top, pane: f.parentElement && f.parentElement.id, body: { light: d.body.classList.contains("theme-light") } };
}, fid);
const shell = () => page.evaluate(() => {
  const cp = document.getElementById("chat-pane"), cs = getComputedStyle(cp), r = (e) => { const b = e.getBoundingClientRect(); return { left: b.left, top: b.top, width: b.width, height: b.height }; };
  const pane1 = document.getElementById("chat-pane-1"), f1 = document.getElementById("f-chat");
  return { frameIds: window.__rompChatFrameIds(), layout: window.__rompChatLayout(), cols: localStorage.getItem("romp-chat-cols"), sets: window.__rompChatSets(),
           gridClass: cp.classList.contains("chat-grid"), display: cs.display, columns: cs.gridTemplateColumns, rows: cs.gridTemplateRows, gap: cs.gap, seam: cs.backgroundColor,
           rowKids: Array.from(document.querySelector(".row").children).map((e) => e.id || e.className),
           paneKids: Array.from(cp.children).map((e) => ({ id: e.id, cls: e.className, area: e.style.gridArea || "", rect: r(e) })),
           chatPane: r(cp), overlay: pane1 ? r(pane1) : null, first: r(f1), firstPos: getComputedStyle(f1).position,
           feed: r(document.getElementById("feed-pane")), fleet: r(document.getElementById("fleet-pane")), light: document.body.classList.contains("theme-light"),
           crossShown: Array.from(document.querySelectorAll("#chat-pane .col-x")).map((x) => getComputedStyle(x).display) };
});
const shot = (name) => page.screenshot({ path: cfg.shots + "/" + name + ".png" });
// the first tile's + opens the picker: the shell lifts the first frame (body.picker-open, #f-chat.lifted); its box, its
// position, the grid's display and every tile's cell while lifted; then the picker closes (Escape, else the backdrop)
const liftFirst = async () => {
  { const fr = await (await page.$("#f-chat")).contentFrame(); await fr.locator("#tabs .tab-add").click(); }
  await waitFn(() => document.body.classList.contains("picker-open") && document.getElementById("f-chat").classList.contains("lifted")
    && (() => { const d = document.getElementById("f-chat").contentDocument, o = d && d.getElementById("picker"); return !!o && o.style.display !== "none"; })(), null, "the first tile's picker never lifted");
  const r = await page.evaluate(() => {
    const f = document.getElementById("f-chat"), b = f.getBoundingClientRect(), cs = getComputedStyle(f), cp = document.getElementById("chat-pane");
    const d = f.contentDocument, o = d && d.getElementById("picker"), ob = o ? o.getBoundingClientRect() : null;
    return { left: b.left, top: b.top, width: b.width, height: b.height, position: cs.position, zIndex: cs.zIndex, vw: window.innerWidth, vh: window.innerHeight,
             appH: getComputedStyle(document.documentElement).getPropertyValue("--app-h").trim(), gridDisplay: getComputedStyle(cp).display, paneLifted: cp.classList.contains("lifted"),
             picker: ob ? { width: ob.width, height: ob.height } : null, paneKids: Array.from(cp.children).map((e) => ({ id: e.id, area: e.style.gridArea || "" })) }; });
  await page.keyboard.press("Escape");
  const byKey = await page.waitForFunction(() => !document.body.classList.contains("picker-open"), null, { timeout: 3000 }).then(() => true).catch(() => false);
  if (!byKey) { const fr = await (await page.$("#f-chat")).contentFrame(); await fr.locator("#picker").click({ position: { x: 4, y: 4 } }); }
  await waitFn(() => !document.body.classList.contains("picker-open") && !document.getElementById("f-chat").classList.contains("lifted"), null, "the first tile's picker never closed");
  r.after = await page.evaluate(() => { const f = document.getElementById("f-chat"), b = f.getBoundingClientRect(); return { width: b.width, height: b.height, position: getComputedStyle(f).position }; });
  return r;
};
// a NONCE on the first frame's DOCUMENT (its window): a moved or re-made iframe loads a new document without it; a kept one
// still carries it after each transition. Marked before the first transition, and again after the reload (a new document)
let nonce = null;
const markDoc = async () => { nonce = await page.evaluate(() => { const f = document.getElementById("f-chat"), n = "tiles-" + Math.random().toString(36).slice(2); f.__tilesMark = 1; f.contentWindow.__tilesDocNonce = n; return n; }); return nonce; };
const docNonce = () => page.evaluate((n) => document.getElementById("f-chat").contentWindow.__tilesDocNonce === n, nonce);
const setTheme = async (theme) => {
  await page.evaluate((theme) => { localStorage.setItem("romp:settings", JSON.stringify({ theme })); window.dispatchEvent(new Event("romp:settings")); }, theme);
  await waitFn((light) => document.body.classList.contains("theme-light") === light, theme === "yatharth-light", "the shell never switched theme to " + theme);
  await waitFn((light) => window.__rompChatFrameIds().every((fid) => { const d = document.getElementById(fid).contentDocument; return !!d && d.body && d.body.classList.contains("theme-light") === light; }), theme === "yatharth-light", "a tile never followed the theme " + theme);
};

// ---- load: every session is a tab in the one chat; the first is active ----
await page.goto(cfg.url);
await waitTabs("f-chat", cfg.sids);
await waitBootGone();
if ((await activeIn("f-chat")) !== cfg.sids[0]) { await clickTab("f-chat", cfg.sids[0]); await waitActive("f-chat", cfg.sids[0]); }
await waitPainted("f-chat");
// the fill follows the first tile's STRIP order (the kernel's tab order, whatever it is), the active tab skipped: read it, derive the rest
const act = cfg.sids[0], order = await tabsIn("f-chat"), rest = order.filter((s) => s !== act);
const fill22 = rest.slice(0, 3), fill23 = rest.slice(0, 5), keep22 = [act].concat(rest.slice(3)), keep23 = [act].concat(rest.slice(5));
out.order = order; out.fill22 = fill22; out.fill23 = fill23; out.keep22 = keep22; out.keep23 = keep23;
out.before = await shell();
out.before.nonce = await markDoc();   // a mark on the first frame's node, and the nonce on its document

// ---- 1. Tiles 2×2 ----
out.s1 = { r: await page.evaluate(() => window.__rompChatTiles("2x2")) };
await waitFrames(4);
await waitClass(true);
for (const fid of ["f-chat-2", "f-chat-3", "f-chat-4"]) { await waitTileHead(fid); await waitPainted(fid); }
await waitTabs("f-chat", keep22);
out.s1.shell = await shell();
out.s1.tiles = {}; for (const fid of out.s1.shell.frameIds) out.s1.tiles[fid] = await tileOf(fid);
out.s1.firstKept = await page.evaluate(() => document.getElementById("f-chat").__tilesMark === 1);
out.s1.firstDocKept = await docNonce();
await shot("tiles-2x2-dark");

// ---- 2. Tiles 2×3 ----
out.s2 = { r: await page.evaluate(() => window.__rompChatTiles("2x3")) };
await waitFrames(6);
for (const fid of ["f-chat-2", "f-chat-3", "f-chat-4", "f-chat-5", "f-chat-6"]) { await waitTileHead(fid); await waitPainted(fid); }
await waitTabs("f-chat", keep23);
out.s2.shell = await shell();
out.s2.tiles = {}; for (const fid of out.s2.shell.frameIds) out.s2.tiles[fid] = await tileOf(fid);
out.s2.firstDocKept = await docNonce();
await shot("tiles-2x3-dark");
out.s2.lift = await liftFirst();

// ---- 3. the light theme: every tile follows ----
await setTheme("yatharth-light");
out.s3 = { shell: await shell() };
out.s3.tiles = {}; for (const fid of out.s3.shell.frameIds) out.s3.tiles[fid] = await tileOf(fid);
await shot("tiles-2x3-light");
out.s3.lift = await liftFirst();

// ---- 4. 2×3 → 2×2 folds the surplus home ----
out.s4 = { r: await page.evaluate(() => window.__rompChatTiles("2x2")) };
await waitFrames(4);
await waitTabs("f-chat", keep22);
out.s4.shell = await shell();
out.s4.col1Tabs = await tabsIn("f-chat");
out.s4.tiles = {}; for (const fid of out.s4.shell.frameIds) out.s4.tiles[fid] = await tileOf(fid);
out.s4.firstDocKept = await docNonce();
await shot("tiles-2x2-light");
await setTheme("classic");

// ---- 5. a reload restores the grid ----
activeTabs.length = 0;
await page.reload();
await waitFrames(4);
await waitClass(true);
await waitTabs("f-chat", keep22);
for (const fid of ["f-chat-2", "f-chat-3", "f-chat-4"]) { await waitTileHead(fid); await waitPainted(fid); }
await waitBootGone();
out.s5 = { shell: await shell() };
out.s5.tiles = {}; for (const fid of out.s5.shell.frameIds) out.s5.tiles[fid] = await tileOf(fid);
out.s5.nonce = await markDoc();   // a reload is a new document: marked afresh for the transitions after it

// ---- 6. focused: the boot's reports say false; a click into a tile's composer says true ----
const until = async (pred, ms) => { const t0 = Date.now(); while (!pred() && Date.now() - t0 < ms) await new Promise((r) => setTimeout(r, 50)); return pred(); };   // a node-side condition (the wire's record), bounded
out.s6 = { boot: activeTabs.slice() };
activeTabs.length = 0; activeChats.length = 0;
{ const fr = await (await page.$("#f-chat-3")).contentFrame(); await fr.locator("#composer-input").click(); }
out.s6.sawFocused = await until(() => activeTabs.some((a) => a.col === "3" && a.focused === true), 5000);
out.s6.feedFollowedClick = await until(() => activeChats.some((c) => c.id === fill22[1]), 5000);
out.s6.afterClick = activeTabs.slice(); out.s6.feedAfterClick = activeChats.slice();
// ---- 6b. a focus from the shell to a session on the first tile's strip (the frame a feed card, a deep link, the switcher
//          and the kernel's reveal deliver): the first column reports it focused:true and the feed's activeChat follows ----
const jump = keep22[1];
activeTabs.length = 0; activeChats.length = 0;
await page.evaluate((sid) => document.getElementById("f-chat").contentWindow.postMessage({ type: "focus", id: sid }, "*"), jump);
await waitActive("f-chat", jump);
out.s6.jump = { sid: jump, sawReport: await until(() => activeTabs.some((a) => a.col === "" && a.id === jump && a.focused === true), 5000),
                sawFeed: await until(() => activeChats.some((c) => c.id === jump), 5000) };
out.s6.jump.reports = activeTabs.slice(); out.s6.jump.feed = activeChats.slice(); out.s6.jump.active = await activeIn("f-chat");

// ---- 7. Back to tabs ----
out.s7 = { r: await page.evaluate(() => window.__rompChatTilesOff()) };
await waitFrames(1);
await waitClass(false);
await waitTabs("f-chat", cfg.sids);
out.s7.shell = await shell();
out.s7.first = await tileOf("f-chat");
out.s7.firstDocKept = await docNonce();
out.ms = Date.now() - out.t0;
fs.writeSync(1, "RESULT:" + JSON.stringify(out) + "\n");
await browser.close();
process.exit(0);
"""


class ServedChatTiles(unittest.TestCase):
    """One kernel, one page, one driver run in setUpClass; each method asserts one step of the shared result."""
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(os.path.join(EXT, "node_modules", "playwright")):
            raise unittest.SkipTest("extension deps absent (npm ci not run here) — the served leg needs them")
        cls.lab = tempfile.mkdtemp(prefix="chat-tiles-")
        b = subprocess.run(["node", "esbuild.js"], cwd=EXT, capture_output=True, text=True)
        if b.returncode != 0:
            raise unittest.SkipTest("esbuild failed here: " + (b.stderr or b.stdout)[-200:])
        dist = os.path.join(cls.lab, "dist")
        copy_dist(os.path.join(EXT, "dist"), dist)
        state = os.path.join(cls.lab, "xdg", "romp")
        cwd = os.path.join(cls.lab, "proj")
        os.makedirs(os.path.join(state, "names"), exist_ok=True)
        os.makedirs(os.path.join(state, "sdk"), exist_ok=True)
        os.makedirs(cwd, exist_ok=True)
        claude = os.path.join(cls.lab, "claude")
        proj = os.path.join(claude, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd)))
        os.makedirs(proj, exist_ok=True)
        for sid, name, tag in SESSIONS:
            Path(state, "names", sid).write_text("%s\t%s\t\t\n" % (name, cwd))
            Path(state, "sdk", sid + ".json").write_text(json.dumps(
                {"sid": sid, "name": name, "cwd": cwd, "mode": "auto", "effort": "high", "lastSid": sid, "alive": True}))
            Path(proj, sid + ".jsonl").write_text(_transcript(sid, tag, cwd, 12))
        Path(state, "usage.json").write_text(json.dumps({"five_hour": {"pct": 100}, "seven_day": {"pct": 10}}))   # park sends
        cls.shots = os.environ.get("ROMP_TILES_SHOTS") or os.path.join(cls.lab, "shots")
        os.makedirs(cls.shots, exist_ok=True)
        cls.port = _free_port()
        cls.token = "testtok-chattiles"
        cls.env = dict(os.environ,
                       XDG_STATE_HOME=os.path.join(cls.lab, "xdg"),
                       CLAUDE_CONFIG_DIR=claude,
                       ROMP_MANAGER_PORT="1", ROMP_KERNEL_NO_OPEN="1",
                       ROMP_SERVE_TOKEN=cls.token, ROMP_KERNEL_PORT=str(cls.port),
                       ROMP_DIST_DIR=dist, ROMP_MODEL_CATALOG="off",
                       ROMP_POSTAL_PORT=str(_free_port()), ROMP_POSTAL_PEERS="0", ROMP_POSTAL_CLIENT_ONLY="1")
        cls.env.pop("ROMP_STATE_DIR", None)
        for k in ("ROMP_MANAGER_PID", "ROMP_SUPERVISED", "ROMP_SID", "ROMP_SESSION_NAME"):
            cls.env.pop(k, None)
        for k in [k for k in cls.env if k in _cred.RETIRED_VARS or _cred.is_op_env_name(k)]:   # the kernel's own boot rule
            cls.env.pop(k, None)
        cls.klog = os.path.join(cls.lab, "kernel.log")
        cls.kernel = subprocess.Popen([os.path.join(BIN, "romp-kernel")],
                                      stdout=open(cls.klog, "w"), stderr=subprocess.STDOUT, env=cls.env)
        import urllib.request
        for _ in range(120):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/healthz" % cls.port, timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            cls.kernel.kill()
            raise unittest.SkipTest("hermetic kernel never served /healthz here")
        cls.result, cls.driver_error = None, None
        cls._drive()

    @classmethod
    def _drive(cls):
        cfg = os.path.join(cls.lab, "cfg.json")
        with open(cfg, "w") as f:
            json.dump({"url": "http://127.0.0.1:%d/?token=%s" % (cls.port, cls.token), "sids": SIDS, "shots": cls.shots}, f)
        driver = os.path.join(cls.lab, "driver.mjs")
        with open(driver, "w") as f:
            f.write(DRIVER)
        try:
            p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=300,
                               env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
        except subprocess.TimeoutExpired as e:
            so = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode()
            cls.driver_error = "driver timed out; partial output:\n%s" % so
            return
        if p.returncode == 3:
            raise unittest.SkipTest("no playwright browser on this box — the served leg needs one (CI installs none)")
        if p.returncode != 0:
            cls.driver_error = "driver failed:\n" + p.stdout[-3000:] + p.stderr[-3000:]
            return
        line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT:")), None)
        if line is None:
            cls.driver_error = "driver printed no result:\n" + p.stdout[-3000:] + p.stderr[-3000:]
            return
        r = json.loads(line[len("RESULT:"):])
        if "died" in r:
            cls.driver_error = "driver aborted early: %s\n%s" % (r["died"], json.dumps(r, indent=1)[-3000:])
            return
        cls.result = r

    @classmethod
    def tearDownClass(cls):
        k = getattr(cls, "kernel", None)
        if k:
            try:
                os.kill(k.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            k.wait()
        if not os.environ.get("ROMP_TILES_SHOTS"):
            shutil.rmtree(getattr(cls, "lab", ""), ignore_errors=True)
        else:   # the screenshots are the deliverable; the rest of the lab goes
            for name in os.listdir(getattr(cls, "lab", "")):
                p = os.path.join(cls.lab, name)
                if p != cls.shots:
                    shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.unlink(p)

    def _r(self):
        if self.driver_error:
            tail = ""
            try:
                with open(self.klog) as fh:
                    tail = "\nkernel log tail:\n" + fh.read()[-2000:]
            except OSError:
                pass
            self.fail(self.driver_error + tail)
        return self.result

    # ── helpers over a step's record ──────────────────────────────────────────────────────────────────────────────
    def _assert_tile_shows_one(self, tiles, fid, sid):
        t = tiles[fid]
        self.assertIsNotNone(t, "%s has a document" % fid)
        self.assertEqual(t["tabs"], [sid], "%s lists its one session: %r" % (fid, t["tabs"]))
        self.assertTrue(t["headOn"], "%s wears the tile header (body.tile-head): %r" % (fid, t))
        self.assertEqual(t["head"]["display"], "flex", "%s's header is shown" % fid)
        self.assertEqual(t["head"]["name"], NAMES[sid], "%s's header names its session: %r" % (fid, t["head"]))
        self.assertTrue(t["head"]["dot"].startswith("tab-dot"), "the strip's own dot: %r" % t["head"]["dot"])
        self.assertTrue(t["head"]["more"], "the ⋯ is a delegated action (data-act)")
        self.assertEqual(t["tabbar"], "none", "%s hides its tab strip under the header" % fid)
        self.assertEqual(t["mhdr"], "none", "%s is the DESKTOP chat at its width: no phone header" % fid)
        self.assertTrue(t["composer"], "%s has its own composer" % fid)
        self.assertTrue(t["liveAsk"], "%s has its own live-ask host" % fid)

    def _assert_grid(self, sh, rows, cols, n):
        b = self._r()["before"]
        self.assertTrue(sh["gridClass"], "#chat-pane wears .chat-grid: %r" % sh)
        self.assertEqual(sh["display"], "grid")
        self.assertEqual(len(sh["columns"].split()), cols, "%d columns: %r" % (cols, sh["columns"]))
        self.assertEqual(len(sh["rows"].split()), rows, "%d rows: %r" % (rows, sh["rows"]))
        self.assertEqual(sh["gap"], "1px", "a 1 px seam, no gutter")
        self.assertEqual(sh["layout"], {"layout": "grid", "rows": rows, "cols": cols})
        self.assertEqual(len(sh["frameIds"]), n)
        self.assertEqual(sh["rowKids"], b["rowKids"], "the row is untouched: no chat gutters, the other panes in their places: %r" % sh["rowKids"])
        self.assertNotIn("gv-chat-2", sh["rowKids"])
        self.assertEqual(sh["firstPos"], "static", "the first frame is a grid item (never moved, never lifted out)")
        # the overlay tile sits on the first frame's cell, so the ring and the drop zone land where the frame is
        self.assertIsNotNone(sh["overlay"], "the first tile's overlay exists")
        for k in ("left", "top", "width", "height"):
            self.assertLessEqual(abs(sh["overlay"][k] - sh["first"][k]), 1.5, "the overlay's %s is the first frame's: %r vs %r" % (k, sh["overlay"], sh["first"]))
        # every later tile takes an explicit cell, row-major after the first; the cells share the chat area evenly
        areas = [p["area"] for p in sh["paneKids"] if p["id"].startswith("chat-pane-") and p["id"] != "chat-pane-1"]
        want = ["%d / %d" % (k // cols + 1, k % cols + 1) for k in range(1, n)]
        self.assertEqual(areas, want, "explicit cells, row-major: %r" % areas)
        cell_w = (sh["chatPane"]["width"] - (cols - 1)) / cols
        for p in sh["paneKids"]:
            if p["id"].startswith("chat-pane-") and p["id"] != "chat-pane-1":
                self.assertLessEqual(abs(p["rect"]["width"] - cell_w), 2, "%s is a cell wide (%r vs %r)" % (p["id"], p["rect"]["width"], cell_w))
        self.assertTrue(all(d == "none" for d in sh["crossShown"]), "no cross on a tile: a tile is emptied from its header, never closed: %r" % sh["crossShown"])

    def _order(self):
        """The first tile's strip order at load, the active first; the fill takes the rest in this order."""
        r = self._r()
        self.assertEqual(sorted(r["order"]), sorted(SIDS), "every session on the strip at load: %r" % r["order"])
        return r["fill22"], r["fill23"], r["keep22"], r["keep23"]

    def test_1_tiles_2x2_lays_four_tiles_in_a_grid_keeps_the_active_first_and_fills_the_rest_each_with_its_header_and_composer(self):
        r = self._r()
        fill22, _, keep22, _ = self._order()
        b = r["before"]
        self.assertFalse(b["gridClass"]); self.assertEqual(b["layout"], {"layout": "row", "rows": 1, "cols": 1})
        s = r["s1"]
        self.assertTrue(s["r"], "__rompChatTiles('2x2') answered true")
        sh = s["shell"]
        self._assert_grid(sh, 2, 2, 4)
        self.assertEqual(sh["frameIds"], ["f-chat", "f-chat-2", "f-chat-3", "f-chat-4"])
        st = json.loads(sh["cols"])
        self.assertEqual(st, {"v": 2, "layout": "grid", "grid": [2, 2], "cols": [{"n": 2, "ids": [fill22[0]]}, {"n": 3, "ids": [fill22[1]]}, {"n": 4, "ids": [fill22[2]]}]},
                         "the store carries the layout and the shape; the active (web) stayed in the first tile, the next three of the strip filled in its order: %r" % st)
        self.assertEqual(sh["sets"], {"2": [fill22[0]], "3": [fill22[1]], "4": [fill22[2]]})
        # the other panes kept their places and sizes
        self.assertLessEqual(abs(sh["feed"]["width"] - b["feed"]["width"]), 2, "the feed pane's width is untouched: %r vs %r" % (sh["feed"], b["feed"]))
        self.assertLessEqual(abs(sh["fleet"]["width"] - b["fleet"]["width"]), 2, "the outline's too")
        self.assertLessEqual(abs(sh["chatPane"]["width"] - b["chatPane"]["width"]), 2, "the chat area's slot is the one width it had")
        # the tiles: the first keeps the strip for the other five; every later one shows its one session with the header and no strip
        t = s["tiles"]
        self.assertFalse(t["f-chat"]["headOn"], "the first tile shows the strip, not a header (five sessions there)")
        self.assertNotEqual(t["f-chat"]["tabbar"], "none")
        self.assertEqual(sorted(t["f-chat"]["tabs"]), sorted(keep22), "the first tile's strip: web (active, kept) and the four not placed: %r" % t["f-chat"]["tabs"])
        self.assertTrue(t["f-chat"]["composer"])
        for fid, sid in zip(("f-chat-2", "f-chat-3", "f-chat-4"), fill22):
            self._assert_tile_shows_one(t, fid, sid)
            self.assertEqual(t[fid]["pane"], "chat-pane-" + fid[-1], "%s's frame sits in its tile pane" % fid)
        # the first frame never moved: a moved iframe reloads its document, and the fill reads that document's strip
        self.assertTrue(s["firstKept"], "the first iframe is the same node"); self.assertTrue(s["firstDocKept"], "…and its DOCUMENT is the one marked before the transition (the nonce set on its window is still there)")
        self.assertEqual(t["f-chat"]["pane"], "chat-pane", "the first frame is #chat-pane's own item (the grid), not a moved child")

    def test_2_tiles_2x3_makes_six_tiles_five_with_a_header_and_the_first_tile_the_overflow_each_a_third_wide_and_the_desktop_chat(self):
        r = self._r()
        _, fill23, _, keep23 = self._order()
        s = r["s2"]
        self.assertTrue(s["r"])
        sh = s["shell"]
        self._assert_grid(sh, 2, 3, 6)
        self.assertEqual(sh["sets"], {str(k + 2): [fill23[k]] for k in range(5)}, "the widening filled two more tiles from the first tile's strip in order: %r" % sh["sets"])
        t = s["tiles"]
        self.assertEqual(sorted(t["f-chat"]["tabs"]), sorted(keep23), "the first tile keeps web (active) and the two not placed: %r" % t["f-chat"]["tabs"])
        self.assertFalse(t["f-chat"]["headOn"]); self.assertNotEqual(t["f-chat"]["tabbar"], "none")
        for k, fid in enumerate(["f-chat-2", "f-chat-3", "f-chat-4", "f-chat-5", "f-chat-6"]):
            self._assert_tile_shows_one(t, fid, fill23[k])
        # sizing: a tile is about a third of the chat area on a 1440 px dashboard (~ 450 px or less), and it renders the desktop chat compactly
        w = t["f-chat-2"]["width"]
        self.assertLessEqual(w, 480, "a 2×3 tile is narrow: %r px" % w); self.assertGreater(w, 150, "…but a real width")
        for fid in sh["frameIds"]:
            self.assertEqual(t[fid]["mhdr"], "none", "%s: the phone header never shows on a mouse desktop, however narrow the tile" % fid)
            self.assertTrue(t[fid]["composer"], "%s keeps its composer" % fid)
        self.assertTrue(s["firstDocKept"], "the widening re-made no first frame: its document still carries the nonce")

    def _assert_lifted_to_the_viewport(self, lift, theme):
        """The picker opened from the first tile lifts its frame to the WHOLE viewport, as in the row (review 2026-09-13: the
        first-cell rule `#chat-pane.chat-grid>#f-chat` at (1,1,0) outranked `body.picker-open iframe.lifted` at (0,2,2), so the
        lifted first frame stayed static, 100% of its cell, and the picker opened ~428×304 inside the tile); the grid stays a
        grid around it, every other tile on its cell; closing puts the frame back in its cell."""
        self.assertEqual(lift["position"], "fixed", "%s: the lifted first frame is fixed to the viewport: %r" % (theme, lift))
        for k, want in (("left", 0), ("top", 0), ("width", lift["vw"]), ("height", lift["vh"])):
            self.assertLessEqual(abs(lift[k] - want), 1, "%s: the lifted frame's %s is the viewport's (%r vs %r): %r" % (theme, k, lift[k], want, lift))
        self.assertEqual((lift["vw"], lift["vh"]), (1440, 900), "the lab's viewport")
        self.assertEqual(lift["zIndex"], "200", "over every pane")
        self.assertIsNotNone(lift["picker"], "the picker is up inside it")
        self.assertGreater(lift["picker"]["width"], 1000, "%s: the picker's overlay spans the lifted frame, not a 428 px cell: %r" % (theme, lift["picker"]))
        self.assertGreater(lift["picker"]["height"], 700, "%s: …and its height: %r" % (theme, lift["picker"]))
        self.assertEqual(lift["gridDisplay"], "grid", "the grid stays a grid while its first frame is lifted (the .lifted pane rule)"); self.assertTrue(lift["paneLifted"])
        areas = [p["area"] for p in lift["paneKids"] if p["id"].startswith("chat-pane-") and p["id"] != "chat-pane-1"]
        self.assertEqual(areas, ["1 / 2", "1 / 3", "2 / 1", "2 / 2", "2 / 3"], "every other tile keeps its explicit cell under the lift")
        a = lift["after"]
        self.assertEqual(a["position"], "static", "closed: the first frame is a grid item again")
        self.assertLess(a["width"], 500, "…the size of its cell: %r" % a); self.assertLess(a["height"], 460)

    def test_2b_the_first_tile_s_picker_lifts_its_frame_to_the_whole_viewport_in_a_2x3_grid_dark_and_light(self):
        r = self._r()
        self._assert_lifted_to_the_viewport(r["s2"]["lift"], "dark")
        self._assert_lifted_to_the_viewport(r["s3"]["lift"], "light")

    def test_3_the_light_theme_reaches_every_tile_and_the_seam(self):
        s = self._r()["s3"]
        self.assertTrue(s["shell"]["light"], "the shell switched")
        self.assertEqual(s["shell"]["seam"], "rgba(0, 0, 0, 0.14)", "the tiles' seam in the light gutters' line colour: %r" % s["shell"]["seam"])
        for fid, t in s["tiles"].items():
            self.assertTrue(t["body"]["light"], "%s followed the theme" % fid)
        self.assertEqual(len(s["tiles"]), 6)

    def test_4_2x3_to_2x2_folds_the_surplus_tiles_sessions_back_into_the_first_tile(self):
        s = self._r()["s4"]
        fill22, _, keep22, _ = self._order()
        self.assertTrue(s["r"])
        sh = s["shell"]
        self._assert_grid(sh, 2, 2, 4)
        self.assertEqual(sh["sets"], {"2": [fill22[0]], "3": [fill22[1]], "4": [fill22[2]]}, "the last two tiles folded: %r" % sh["sets"])
        self.assertEqual(sorted(s["col1Tabs"]), sorted(keep22), "the two folded sessions are back on the first tile's strip: %r" % s["col1Tabs"])
        for fid, sid in zip(("f-chat-2", "f-chat-3", "f-chat-4"), fill22):
            self._assert_tile_shows_one(s["tiles"], fid, sid)
        self.assertTrue(s["firstDocKept"], "the fold re-made no first frame")

    def test_5_a_reload_restores_the_grid_with_its_headers(self):
        s = self._r()["s5"]
        fill22, _, keep22, _ = self._order()
        sh = s["shell"]
        self._assert_grid(sh, 2, 2, 4)
        self.assertEqual(json.loads(sh["cols"])["layout"], "grid")
        for fid, sid in zip(("f-chat-2", "f-chat-3", "f-chat-4"), fill22):
            self._assert_tile_shows_one(s["tiles"], fid, sid)
        self.assertEqual(sorted(s["tiles"]["f-chat"]["tabs"]), sorted(keep22))

    def test_6_a_tile_s_boot_reports_focused_false_and_a_click_into_its_composer_reports_focused_true(self):
        s = self._r()["s6"]
        boot = s["boot"]
        self.assertTrue(boot, "the reload's boot posted activeTab reports")
        self.assertTrue(all(a["focused"] is False for a in boot), "every boot / restore report says focused:false: %r" % boot)
        self.assertTrue(any(a["col"] == "3" for a in boot), "tile 3 reported at its boot too")
        clicked = [a for a in s["afterClick"] if a["col"] == "3"]
        self.assertTrue(clicked, "the click into tile 3's composer posted an activeTab from column 3: %r" % s["afterClick"])
        self.assertEqual(clicked[-1]["focused"], True, "…saying the user's gesture made it: %r" % clicked)
        self.assertEqual(clicked[-1]["id"], self._order()[0][1], "…for the tile's own session (the second of the fill)")
        self.assertTrue(all(a["focused"] is not True for a in s["afterClick"] if a["col"] != "3"), "no other tile claimed a gesture: %r" % s["afterClick"])
        self.assertTrue(s["feedFollowedClick"], "the kernel relayed the click's session to the feed's socket as activeChat: %r" % s["feedAfterClick"])
        self.assertEqual(s["feedAfterClick"][-1]["id"], self._order()[0][1])

    def test_6b_a_focus_from_the_shell_is_reported_focused_true_and_the_feed_s_active_chat_follows_it(self):
        """Review 2026-09-13: the first cut marked only the page's own gestures focused, so a focus MESSAGE (a feed card, a deep
        link, the switcher, the kernel's reveal after a create) changed the active tab unfocused, the kernel refused it once it
        followed a session, and the feed's section went stale — in the row too. Now every navigation that changes the active
        tab reports focused:true; here the frame the shell delivers."""
        s = self._r()["s6"]
        j = s["jump"]
        fill22, _, keep22, _ = self._order()
        self.assertEqual(j["sid"], keep22[1], "a session on the first tile's strip, not the active one")
        self.assertEqual(j["active"], j["sid"], "the first column switched to it")
        self.assertTrue(j["sawReport"], "the first column (col '') reported the focus with focused:true: %r" % j["reports"])
        first = [a for a in j["reports"] if a["col"] == ""]
        self.assertEqual(first[-1], {"col": "", "id": j["sid"], "focused": True}, "…the last report from that column names it, focused: %r" % first)
        self.assertTrue(j["sawFeed"], "the feed's socket received activeChat for it (the record moved off tile 3's session): %r" % j["feed"])
        self.assertEqual(j["feed"][-1]["id"], j["sid"])
        self.assertTrue(all(a["focused"] is not True for a in j["reports"] if a["col"] != ""), "no tile claimed the navigation: %r" % j["reports"])

    def test_7_back_to_tabs_leaves_one_frame_the_row_and_the_v2_store(self):
        s = self._r()["s7"]
        self.assertTrue(s["r"])
        sh = s["shell"]
        self.assertEqual(sh["frameIds"], ["f-chat"]); self.assertFalse(sh["gridClass"]); self.assertEqual(sh["display"], "block")
        self.assertEqual(sh["cols"], '{"v":2,"cols":[]}', "the shape the row always wrote, byte for byte")
        self.assertEqual(sh["layout"], {"layout": "row", "rows": 1, "cols": 1}); self.assertEqual(sh["sets"], {})
        self.assertIsNone(sh["overlay"], "the overlay is gone")
        self.assertEqual([p["id"] for p in sh["paneKids"]], ["f-chat"], "the first frame alone in #chat-pane")
        f = s["first"]
        self.assertFalse(f["headOn"], "no header: the one chat wears its strip"); self.assertNotEqual(f["tabbar"], "none")
        self.assertEqual(sorted(f["tabs"]), sorted(SIDS), "every session on the one strip")
        self.assertTrue(s["firstDocKept"], "Back to tabs re-made no first frame: its document still carries the nonce")

    def test_8_the_screenshots_exist(self):
        self._r()
        for name in ("tiles-2x2-dark", "tiles-2x3-dark", "tiles-2x3-light", "tiles-2x2-light"):
            p = os.path.join(self.shots, name + ".png")
            self.assertTrue(os.path.isfile(p) and os.path.getsize(p) > 10_000, "%s was written" % p)


if __name__ == "__main__":
    unittest.main()
