#!/usr/bin/env python3
"""The chat rows, the SERVED leg (the user 2026-09-15: a second row of chat columns). The dashboard's chat columns
live inside a static #chat-area wrapper holding two flex rows (#chat-row-1 around the first pane, #chat-row-2 for the
bottom row) and the #gv-rows gutter between them; the split script (_LANDING_SPLIT_JS) appends a later column into
the row its store entry names, shows the bottom row while a column is in it, and keeps the rows' share as rowSplit.

The node-side test (tests/test_chat_split.py RowsExecute) drives the split script against a DOM stub; this one drives
the REAL page: a hermetic kernel serves the dashboard with FIVE synthetic sessions, a headless browser opens it once at
1440 x 900, and ONE driver run walks the story in order with real pointer drags, each step landing in its own assertion:
  1. B's tab dragged from the first column to the chat area's BOTTOM edge: the bottom zone mounts on the page's tabDrag
     message, the rectangle shows the area's bottom half with B's name, and the drop opens the bottom row on B —
     #chat-row-2 visible with one column, the two rows' boxes stacked without overlap at about half the height each,
     the store carrying row:2 and rowSplit 0.5 — while the first pane's document is the SAME document (a nonce stamped
     on it before the drag is still there: the wrapper was in the markup from the first paint, nothing re-parented #f-chat);
  2. C's tab dragged to the BOTTOM ROW's right edge: its rectangle the right half of the bottom row's column at that
     row's height, and the drop a second column in the bottom row, one over two;
  3. D's tab dragged to the TOP row's right edge: two over two — the top row's panes share one top and height, the bottom
     row's another, no pane overlaps another — and the walk (__rompChatFrameIds) is the top row then the bottom;
  4. the CAP: E's drag mounts every making zone refused, the rectangle over the bottom zone says so, and the drop opens
     nothing and moves nothing;
  5. the ROW GUTTER dragged 120 px down: rowSplit changes and the rows' heights follow it; a reload restores the
     arrangement at that share;
  6. the FOLD: the bottom row's two sessions moved home one by one — the row stands on the second, folds on the last:
     #chat-row-2 and #gv-rows hidden, the top row at the area's full height, the store the bytes a never-stacked browser
     writes ({v:2, cols:[{n:4, ids:[D]}]}), the first pane's document still the one stamped after the reload;
  7. back to one: the last column's close leaves {v:2, cols:[]} and the first column listing every session;
  8. the whole story runs in under a minute and a half (the driver waits on conditions, never on fixed sleeps).
Screenshots of the 1 + 1 stack and the 2 x 2, dark and light, land in the directory ROMP_ROWS_SHOTS names (default
/tmp/chat-rows-shots) for a human look. Skips LOUDLY when the extension deps or a playwright browser are absent (CI
installs none). Synthetic only: placeholder sids, invented notes-api prompt text, no real session data."""
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
from romp_load import load_source
from tests.dist_copy import copy_dist
# Hermetic state BEFORE the loads — they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
# the kernel refuses to boot with a retired key variable or a 1Password name in its environment (kernel/credentials.py
# check_boot_environment): the lab's kernel env is scrubbed by the kernel's own rule, read from the module itself
_cred = load_source("romp_credentials_rows_served", os.path.join(ROOT, "kernel", "credentials.py"))
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")

SID_A = "11111111-2222-4333-8444-000000000401"   # "web": the first column's session
SID_B = "11111111-2222-4333-8444-000000000402"   # "api": the bottom row opens on it
SID_C = "11111111-2222-4333-8444-000000000403"   # "tests": the bottom row's second column
SID_D = "11111111-2222-4333-8444-000000000404"   # "docs": the top row's second column
SID_E = "11111111-2222-4333-8444-000000000405"   # "lint": the fifth, refused at the cap
SESSIONS = [(SID_A, "web", 1), (SID_B, "api", 2), (SID_C, "tests", 3), (SID_D, "docs", 4), (SID_E, "lint", 5)]
SLACK_PX = 40
SHOTS = os.environ.get("ROMP_ROWS_SHOTS", "/tmp/chat-rows-shots")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _transcript(sid, tag, cwd, pairs):
    """`pairs` CLOSED user/assistant turns for `sid` (an OPEN turn would invite the boot reconcile to resume
    it); `tag` keeps the sessions' message uuids apart."""
    out, parent, t = [], None, 1_700_000_000
    filler = ["The ranking pass reads its weights from the notes-api config now.",
              "Tokenizer edge cases (hyphens, quotes) are covered by the new fixture set.",
              "Index rebuild time is dominated by the stemmer; caching its table halves it."]
    for i in range(pairs):
        u = "11111111-2222-4333-8444-%02x00000c%04x" % (tag, i)
        a = "11111111-2222-4333-8444-%02x00000d%04x" % (tag, i)
        ts = lambda k: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t + i * 60 + k))
        out.append({"type": "user", "uuid": u, "parentUuid": parent, "timestamp": ts(0), "sessionId": sid, "cwd": cwd,
                    "message": {"role": "user", "content": "please keep going with the search module notes (part %d)" % (i + 1)}})
        body = "\n\n".join(["Note %d." % (i + 1)] + [filler[(i + k) % len(filler)] for k in range(2)])
        out.append({"type": "assistant", "uuid": a, "parentUuid": u, "timestamp": ts(5), "sessionId": sid, "cwd": cwd,
                    "message": {"id": "msg_rows_%d_%04d" % (tag, i), "type": "message", "role": "assistant", "model": "claude-sonnet-5",
                                "content": [{"type": "text", "text": body}], "stop_reason": "end_turn"}})
        parent = a
    return "\n".join(json.dumps(r) for r in out) + "\n"


# The chat iframes are SAME-ORIGIN with the shell, so every probe reads a column's document from the shell
# context (document.getElementById(fid).contentDocument): no frame handles that a navigation could tear down.
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
const die = async (why) => {
  out.ms = Date.now() - out.t0;
  fs.writeSync(1, "RESULT:" + JSON.stringify({ ...out, died: why }) + "\n");
  await browser.close();
  process.exit(0);
};
const T = 15000;
const waitFn = async (fn, arg, why) => page.waitForFunction(fn, arg, { timeout: T }).catch(async (e) => { await die(why + " (" + String(e).split("\n")[0] + ")"); });
const waitTabs = (fid, sids) => waitFn(([fid, sids]) => {
  const f = document.getElementById(fid); const d = f && f.contentDocument; if (!d) return false;
  const ids = Array.from(d.querySelectorAll("#tabs .tab[data-id]")).map((t) => t.dataset.id);
  return sids.every((s) => ids.includes(s));
}, [fid, sids], fid + " never showed tabs " + sids.join(","));
const waitNoTabs = (fid, sids) => waitFn(([fid, sids]) => {
  const f = document.getElementById(fid); const d = f && f.contentDocument; if (!d) return false;
  const ids = Array.from(d.querySelectorAll("#tabs .tab[data-id]")).map((t) => t.dataset.id);
  return ids.length > 0 && sids.every((s) => !ids.includes(s));
}, [fid, sids], fid + " still lists " + sids.join(","));
const waitActive = (fid, sid) => waitFn(([fid, sid]) => {
  const f = document.getElementById(fid); const d = f && f.contentDocument;
  const t = d && d.querySelector("#tabs .tab.active[data-id]"); return !!t && t.dataset.id === sid;
}, [fid, sid], fid + " never activated " + sid);
const waitBootGone = () => waitFn(() => !document.getElementById("romp-boot"), null, "boot splash never cleared");
const waitGone = (id) => waitFn((id) => !document.getElementById(id), id, id + " never left the row");
const waitDraggable = (fid, sid) => waitFn(([fid, sid]) => { const f = document.getElementById(fid); const d = f && f.contentDocument; const t = d && d.querySelector('#tabs .tab[data-id="' + sid + '"]'); return !!(t && t.draggable); }, [fid, sid], sid + "'s tab in " + fid + " never became draggable");
const activeIn = (fid) => page.evaluate((fid) => { const f = document.getElementById(fid); const d = f && f.contentDocument; const t = d && d.querySelector("#tabs .tab.active[data-id]"); return t ? t.dataset.id : null; }, fid);
const tabsIn = (fid) => page.evaluate((fid) => { const f = document.getElementById(fid); const d = f && f.contentDocument; return d ? Array.from(d.querySelectorAll("#tabs .tab[data-id]")).map((t) => t.dataset.id) : null; }, fid);
const clickTab = async (fid, sid) => { const fr = await (await page.$("#" + fid)).contentFrame(); await fr.locator('#tabs .tab[data-id="' + sid + '"]').first().click(); };
const store = () => page.evaluate(() => localStorage.getItem("romp-chat-cols"));
const frames = () => page.evaluate(() => window.__rompChatFrameIds());
// the first pane's DOCUMENT identity: a nonce stamped on its document element; a reload (or a re-parenting of the iframe,
// which reloads it) gives a fresh document without it
const stamp = () => page.evaluate(() => { const d = document.getElementById("f-chat").contentDocument; const n = "n-" + Math.random().toString(36).slice(2); d.documentElement.setAttribute("data-rows-nonce", n); return n; });
const nonce = () => page.evaluate(() => { const d = document.getElementById("f-chat").contentDocument; return d ? d.documentElement.getAttribute("data-rows-nonce") : null; });
// the boxes the browser laid out: the chat area, its rows and gutter, every chat pane (null when absent), with the computed display
const geometry = () => page.evaluate(() => {
  const r = (id) => { const e = document.getElementById(id); if (!e) return null; const b = e.getBoundingClientRect(); return { left: b.left, top: b.top, width: b.width, height: b.height, right: b.right, bottom: b.bottom, display: getComputedStyle(e).display }; };
  return { area: r("chat-area"), row1: r("chat-row-1"), row2: r("chat-row-2"), gvRows: r("gv-rows"), p1: r("chat-pane"), p2: r("chat-pane-2"), p3: r("chat-pane-3"), p4: r("chat-pane-4"), cls: document.getElementById("chat-area").className, frames: window.__rompChatFrameIds(), cols: localStorage.getItem("romp-chat-cols") };
});
const rectIn = (fid, sel) => page.evaluate(([fid, sel]) => {
  const f = document.getElementById(fid); const fr = f.getBoundingClientRect(); const el = f.contentDocument.querySelector(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect(); return { x: fr.left + r.left, y: fr.top + r.top, w: r.width, h: r.height };
}, [fid, sel]);
// a REAL drag of a tab: the pointer presses on it and moves past the threshold, so the page's dragstart fires (its
// tabDrag message mounts the shell's zones); moves carry the drag over a zone (Chromium's intercepted drag dispatches
// dragenter/dragover there); the release drops
const dragStart = async (fid, sid) => {
  await waitDraggable(fid, sid);
  const t = await rectIn(fid, '#tabs .tab[data-id="' + sid + '"]');
  if (!t) await die("no tab for " + sid + " in " + fid);
  await page.mouse.move(t.x + t.w / 2, t.y + t.h / 2);
  await page.mouse.down();
  await page.mouse.move(t.x + t.w / 2 + 24, t.y + t.h / 2 + 6, { steps: 4 });
};
const zones = () => page.evaluate(() => Array.from(document.querySelectorAll(".col-drop")).map((z) => {
  const r = z.getBoundingClientRect();
  return { cls: z.className, parent: z.parentElement.id, col: z.getAttribute("data-col"), row: z.getAttribute("data-row"), refused: z.getAttribute("data-refused"), left: r.left, top: r.top, width: r.width, height: r.height };
}));
const ghost = () => page.evaluate(() => { const g = document.getElementById("col-ghost"); const r = g.getBoundingClientRect(); return { cls: g.className, text: g.textContent, left: r.left, top: r.top, width: r.width, height: r.height, display: getComputedStyle(g).display }; });
const overZone = async (z) => {
  await page.mouse.move(z.left + z.width / 2, z.top + z.height / 2, { steps: 8 });
  await waitFn(() => document.getElementById("col-ghost").classList.contains("on"), null, "the rectangle never showed over the zone " + z.cls);
  return ghost();
};
// the screenshots: the shell and every pane read the theme from romp:settings (the shell on its own event, the panes on the storage event)
fs.mkdirSync(cfg.shots, { recursive: true });
const theme = async (t) => {
  await page.evaluate((t) => { const s = JSON.parse(localStorage.getItem("romp:settings") || "{}"); s.theme = t; localStorage.setItem("romp:settings", JSON.stringify(s)); window.dispatchEvent(new Event("romp:settings")); }, t);
  await page.waitForFunction((light) => {
    if (document.body.classList.contains("theme-light") !== light) return false;
    return window.__rompChatFrameIds().every((id) => { const d = document.getElementById(id).contentDocument; return !!d && d.body && d.body.classList.contains("theme-light") === light; });
  }, t === "yatharth-light", { timeout: T }).catch(() => {});
};
const shots = async (name) => {
  await page.screenshot({ path: cfg.shots + "/" + name + "-dark.png" });
  await theme("yatharth-light"); await page.screenshot({ path: cfg.shots + "/" + name + "-light.png" }); await theme("classic");
  out.shots = (out.shots || []).concat([name + "-dark.png", name + "-light.png"]);
};

// ---- load: every session is a tab in the first column; the first column shows A ----
await page.goto(cfg.url);
await waitTabs("f-chat", [cfg.a, cfg.b, cfg.c, cfg.d, cfg.e]);
await waitBootGone();
if ((await activeIn("f-chat")) !== cfg.a) { await clickTab("f-chat", cfg.a); await waitActive("f-chat", cfg.a); }
out.before = Object.assign(await geometry(), { nonce: await stamp() });

// ---- 1. B to the BOTTOM edge: the bottom row opens on it ----
await dragStart("f-chat", cfg.b);
await waitFn(() => !!document.querySelector(".col-drop.col-drop-bottom"), null, "the bottom zone never mounted for B's drag");
out.s1 = { zones: await zones() };
const bottom1 = out.s1.zones.find((z) => z.cls.includes("col-drop-bottom"));
out.s1.ghost = await overZone(bottom1);
await page.mouse.up();
await waitTabs("f-chat-2", [cfg.b]); await waitActive("f-chat-2", cfg.b); await waitNoTabs("f-chat", [cfg.b]);
out.s1.after = Object.assign(await geometry(), { nonce: await nonce(), col1Tabs: await tabsIn("f-chat"), col2Tabs: await tabsIn("f-chat-2"), zonesLeft: (await zones()).length, ghostAfter: await ghost() });
await shots("stack-1-1");

// ---- 2. C to the BOTTOM ROW's right edge: a second column beside B ----
await dragStart("f-chat", cfg.c);
await waitFn(() => !!document.querySelector('.col-drop.col-drop-edge[data-row="2"]'), null, "the bottom row's edge never mounted for C's drag");
out.s2 = { zones: await zones() };
const edge2 = out.s2.zones.find((z) => z.cls.includes("col-drop-edge") && z.row === "2");
out.s2.ghost = await overZone(edge2);
await page.mouse.up();
await waitTabs("f-chat-3", [cfg.c]); await waitActive("f-chat-3", cfg.c); await waitNoTabs("f-chat", [cfg.c]);
out.s2.after = Object.assign(await geometry(), { nonce: await nonce() });

// ---- 3. D to the TOP row's right edge: two over two ----
await dragStart("f-chat", cfg.d);
await waitFn(() => !!document.querySelector('.col-drop.col-drop-edge[data-row="1"]'), null, "the top row's edge never mounted for D's drag");
out.s3 = { zones: await zones() };
const edge1 = out.s3.zones.find((z) => z.cls.includes("col-drop-edge") && z.row === "1");
out.s3.ghost = await overZone(edge1);
await page.mouse.up();
await waitTabs("f-chat-4", [cfg.d]); await waitActive("f-chat-4", cfg.d); await waitNoTabs("f-chat", [cfg.d]);
out.s3.after = Object.assign(await geometry(), { nonce: await nonce() });
await shots("grid-2-2");

// ---- 4. the CAP: E's drag mounts every making zone refused ----
await dragStart("f-chat", cfg.e);
await waitFn(() => !!document.querySelector(".col-drop.col-drop-bottom"), null, "the bottom zone never mounted for E's drag");
out.s4 = { zones: await zones() };
const bottom4 = out.s4.zones.find((z) => z.cls.includes("col-drop-bottom"));
out.s4.ghost = await overZone(bottom4);
await page.mouse.up();
await waitFn(() => document.querySelectorAll(".col-drop").length === 0, null, "the zones never unmounted after the refused drop");
out.s4.after = Object.assign(await geometry(), { nonce: await nonce(), col1Tabs: await tabsIn("f-chat") });

// ---- 5. the ROW GUTTER dragged 120 px down, then a reload ----
const gutterBefore = await geometry();
const gr = gutterBefore.gvRows;
await page.mouse.move(gr.left + gr.width / 2, gr.top + gr.height / 2);
await page.mouse.down();
await page.mouse.move(gr.left + gr.width / 2, gr.top + gr.height / 2 + 120, { steps: 10 });
await page.mouse.up();
await waitFn(() => { const s = JSON.parse(localStorage.getItem("romp-chat-cols") || "{}"); return typeof s.rowSplit === "number" && Math.abs(s.rowSplit - 0.5) > 0.02; }, null, "rowSplit never changed after the gutter drag");
out.s5 = { before: gutterBefore, after: Object.assign(await geometry(), { nonce: await nonce() }) };
await page.reload();
await waitTabs("f-chat", [cfg.a, cfg.e]); await waitTabs("f-chat-2", [cfg.b]); await waitTabs("f-chat-3", [cfg.c]); await waitTabs("f-chat-4", [cfg.d]);
await waitBootGone();
out.s5.reloaded = Object.assign(await geometry(), { nonceGone: await nonce() });
out.s5.nonce2 = await stamp();

// ---- 6. the FOLD: B then C home ----
await page.evaluate((sid) => window.__rompMoveTab(sid, 1), cfg.b);
await waitGone("chat-pane-2"); await waitTabs("f-chat", [cfg.a, cfg.b, cfg.e]);
out.s6 = { onB: Object.assign(await geometry(), { nonce: await nonce() }) };
await page.evaluate((sid) => window.__rompMoveTab(sid, 1), cfg.c);
await waitGone("chat-pane-3"); await waitTabs("f-chat", [cfg.a, cfg.b, cfg.c, cfg.e]);
await waitFn(() => !document.getElementById("chat-area").classList.contains("rows"), null, "the bottom row never folded");
out.s6.onC = Object.assign(await geometry(), { nonce: await nonce(), bytes: await store() });

// ---- 7. back to one ----
await page.evaluate(() => window.__rompCloseSplit(4));
await waitGone("chat-pane-4"); await waitTabs("f-chat", [cfg.a, cfg.b, cfg.c, cfg.d, cfg.e]);
out.s7 = Object.assign(await geometry(), { nonce: await nonce(), col1Tabs: await tabsIn("f-chat") });
out.ms = Date.now() - out.t0;
fs.writeSync(1, "RESULT:" + JSON.stringify(out) + "\n");
await browser.close();
"""


class ServedChatRows(unittest.TestCase):
    """One kernel, one page, one driver run in setUpClass; each method asserts one step of the shared result."""
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(os.path.join(EXT, "node_modules", "playwright")):
            raise unittest.SkipTest("extension deps absent (npm ci not run here) — the served leg needs them")
        cls.lab = tempfile.mkdtemp(prefix="chat-rows-")
        b = subprocess.run(["node", "esbuild.js"], cwd=EXT, capture_output=True, text=True)
        if b.returncode != 0:
            raise unittest.SkipTest("esbuild failed here: " + (b.stderr or b.stdout)[-200:])
        dist = os.path.join(cls.lab, "dist")
        copy_dist(os.path.join(EXT, "dist"), dist)   # skips a concurrent build's staging files (tests/dist_copy.py)
        state = os.path.join(cls.lab, "xdg", "romp")
        cwd = os.path.join(cls.lab, "proj")
        os.makedirs(os.path.join(state, "names"), exist_ok=True)
        os.makedirs(os.path.join(state, "sdk"), exist_ok=True)
        os.makedirs(cwd, exist_ok=True)
        claude = os.path.join(cls.lab, "claude")
        proj = os.path.join(claude, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd)))
        os.makedirs(proj, exist_ok=True)
        # five synthetic SDK sessions so the chat page has five tabs; their transcripts hold only CLOSED turns, so the boot
        # reconcile never resumes any and no CLI is ever spawned
        for sid, name, tag in SESSIONS:
            Path(state, "names", sid).write_text("%s\t%s\t\t\n" % (name, cwd))
            Path(state, "sdk", sid + ".json").write_text(json.dumps(
                {"sid": sid, "name": name, "cwd": cwd, "mode": "auto", "effort": "high", "lastSid": sid, "alive": True}))
            Path(proj, sid + ".jsonl").write_text(_transcript(sid, tag, cwd, 6))
        Path(state, "usage.json").write_text(json.dumps({"five_hour": {"pct": 100}, "seven_day": {"pct": 10}}))   # park sends
        cls.port = _free_port()
        cls.token = "testtok-chatrows"
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
        for k in [k for k in cls.env if k in _cred.RETIRED_VARS or _cred.is_op_env_name(k)]:   # the kernel's own boot rule (module top)
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
            json.dump({"url": "http://127.0.0.1:%d/?token=%s" % (cls.port, cls.token),
                       "a": SID_A, "b": SID_B, "c": SID_C, "d": SID_D, "e": SID_E, "shots": SHOTS}, f)
        driver = os.path.join(cls.lab, "driver.mjs")
        with open(driver, "w") as f:
            f.write(DRIVER)
        t0 = time.monotonic()
        try:
            p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=300,
                               env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
        except subprocess.TimeoutExpired as e:
            so = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode()
            cls.driver_error = "driver timed out; partial output:\n%s" % so
            return
        cls.driver_s = time.monotonic() - t0
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
        shutil.rmtree(getattr(cls, "lab", ""), ignore_errors=True)

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

    # ── helpers over the geometry snapshots ─────────────────────────────────────────────────────────────
    @staticmethod
    def _overlap(a, b):
        return a["left"] < b["right"] and b["left"] < a["right"] and a["top"] < b["bottom"] and b["top"] < a["bottom"]

    def _assert_rows_stacked(self, g, where):
        r1, r2 = g["row1"], g["row2"]
        self.assertEqual(g["cls"], "rows", where + ": the area wears .rows while a column is in the bottom row")
        self.assertNotEqual(r2["display"], "none", where + ": the bottom row is shown")
        self.assertNotEqual(g["gvRows"]["display"], "none", where + ": the row gutter is shown")
        self.assertGreater(r2["height"], 100, where + ": the bottom row has real height: %r" % r2)
        self.assertLessEqual(r1["bottom"], r2["top"], where + ": the rows do not overlap: %r / %r" % (r1, r2))
        self.assertLessEqual(abs(g["gvRows"]["top"] - r1["bottom"]), 1, where + ": the gutter sits under the top row")
        self.assertLessEqual(abs(r2["top"] - g["gvRows"]["bottom"]), 1, where + ": …and over the bottom row")
        self.assertLessEqual(abs(r1["left"] - r2["left"]), 1); self.assertLessEqual(abs(r1["width"] - r2["width"]), 1, where + ": the rows share the area's width")

    def test_0_the_page_opens_on_one_column_with_no_bottom_row(self):
        r = self._r()
        g = r["before"]
        self.assertEqual(g["cls"], "", "no .rows: the bottom row and its gutter hidden")
        self.assertEqual(g["row2"]["display"], "none"); self.assertEqual(g["gvRows"]["display"], "none")
        self.assertLessEqual(abs(g["row1"]["height"] - g["area"]["height"]), 1, "the top row fills the area: %r vs %r" % (g["row1"], g["area"]))
        self.assertLessEqual(abs(g["p1"]["height"] - g["area"]["height"]), 1, "…and the first pane the row")
        self.assertEqual(g["frames"], ["f-chat"]); self.assertIsNone(g["cols"], "nothing written before a gesture")
        self.assertTrue(g["nonce"].startswith("n-"))

    def test_1_a_tab_dragged_to_the_bottom_edge_opens_the_bottom_row_on_it_without_reloading_the_first_pane(self):
        r = self._r()
        s, before = r["s1"], r["before"]
        bottom = [z for z in s["zones"] if "col-drop-bottom" in z["cls"]]
        self.assertEqual(len(bottom), 1, "one bottom zone, on the chat area: %r" % s["zones"])
        self.assertEqual(bottom[0]["parent"], "chat-area")
        self.assertLessEqual(abs(bottom[0]["left"] - before["area"]["left"]), 1); self.assertLessEqual(abs(bottom[0]["width"] - before["area"]["width"]), 1, "the zone spans the area's width")
        self.assertLessEqual(abs((bottom[0]["top"] + bottom[0]["height"]) - before["area"]["bottom"]), 1, "…along its bottom edge")
        self.assertLessEqual(abs(bottom[0]["height"] - max(72, min(180, 0.2 * before["row1"]["height"]))), 1, "a fifth of the (only) row's height, clamped")
        edges = [z for z in s["zones"] if "col-drop-edge" in z["cls"]]
        self.assertEqual([z["row"] for z in edges], ["1"], "one column: the top row's edge alone beside it")
        gh = s["ghost"]
        self.assertEqual(gh["cls"], "on"); self.assertEqual(gh["text"], "api", "the dragged session's name, no verb")
        self.assertLessEqual(abs(gh["top"] - (before["area"]["top"] + before["area"]["height"] / 2)), 2, "the rectangle is the area's bottom half: %r vs %r" % (gh, before["area"]))
        self.assertLessEqual(abs(gh["height"] - before["area"]["height"] / 2), 2)
        self.assertLessEqual(abs(gh["left"] - before["area"]["left"]), 1); self.assertLessEqual(abs(gh["width"] - before["area"]["width"]), 1)
        a = s["after"]
        self.assertEqual(a["frames"], ["f-chat", "f-chat-2"])
        self.assertEqual(json.loads(a["cols"]), {"v": 2, "cols": [{"n": 2, "ids": [SID_B], "row": 2}], "rowSplit": 0.5}, "row:2 on the entry, the half as the share")
        self._assert_rows_stacked(a, "after the drop")
        self.assertLessEqual(abs(a["row1"]["height"] - a["row2"]["height"]), 2, "at rowSplit 0.5 the rows are the same height: %r / %r" % (a["row1"], a["row2"]))
        self.assertLessEqual(abs(a["p2"]["top"] - a["row2"]["top"]), 1, "the new column is in the bottom row: %r" % a["p2"])
        self.assertLessEqual(abs(a["p2"]["width"] - a["row2"]["width"]), 1, "…and has the row to itself (no gutter ahead of it)")
        self.assertLessEqual(abs(a["p1"]["height"] - a["row1"]["height"]), 1, "the first pane now fills the top row only")
        self.assertEqual(a["nonce"], before["nonce"], "the first pane's document is the SAME document: nothing re-parented #f-chat")
        self.assertEqual(a["col2Tabs"], [SID_B]); self.assertNotIn(SID_B, a["col1Tabs"])
        self.assertEqual(a["zonesLeft"], 0, "every zone unmounted at the drop"); self.assertEqual(a["ghostAfter"]["display"], "none")

    def test_2_a_tab_dragged_to_the_bottom_row_s_right_edge_adds_a_column_beside_its_first(self):
        r = self._r()
        s, prev = r["s2"], r["s1"]["after"]
        rows = sorted(z["row"] for z in s["zones"] if "col-drop-edge" in z["cls"])
        self.assertEqual(rows, ["1", "2"], "an edge per row: %r" % s["zones"])
        e2 = next(z for z in s["zones"] if "col-drop-edge" in z["cls"] and z["row"] == "2")
        self.assertEqual(e2["parent"], "chat-pane-2", "the bottom row's edge rides its rightmost pane")
        self.assertLessEqual(abs(e2["left"] + e2["width"] - prev["p2"]["right"]), 1, "…at its right")
        gh = s["ghost"]
        self.assertEqual(gh["text"], "tests")
        self.assertLessEqual(abs(gh["top"] - prev["row2"]["top"]), 2, "the rectangle is at the bottom row's top: %r vs %r" % (gh, prev["row2"]))
        self.assertLessEqual(abs(gh["height"] - prev["row2"]["height"]), 2, "…and the bottom row's height")
        self.assertLessEqual(abs(gh["left"] - (prev["p2"]["left"] + prev["p2"]["width"] / 2)), 2, "…the right half of the bottom row's column")
        a = s["after"]
        self.assertEqual(a["frames"], ["f-chat", "f-chat-2", "f-chat-3"])
        self.assertEqual(json.loads(a["cols"]), {"v": 2, "cols": [{"n": 2, "ids": [SID_B], "row": 2}, {"n": 3, "ids": [SID_C], "row": 2}], "rowSplit": 0.5})
        self._assert_rows_stacked(a, "one over two")
        self.assertLessEqual(abs(a["p3"]["top"] - a["row2"]["top"]), 1, "column 3 is in the bottom row")
        self.assertLessEqual(abs(a["p2"]["right"] + 7 - a["p3"]["left"]), 1, "…beside column 2 behind a 7 px gutter: %r / %r" % (a["p2"], a["p3"]))
        half = (prev["p2"]["width"] - 7) / 2
        self.assertLessEqual(abs(a["p2"]["width"] - half), SLACK_PX, "column 2 is about half its old width: %r" % a["p2"])
        self.assertLessEqual(abs(a["p3"]["width"] - half), SLACK_PX, "…and so is the new column")
        self.assertLessEqual(abs(a["p1"]["width"] - prev["p1"]["width"]), 1, "the top row's pane is untouched by a halving in the bottom row")
        self.assertEqual(a["nonce"], r["before"]["nonce"])

    def test_3_a_tab_dragged_to_the_top_row_s_right_edge_completes_two_over_two(self):
        r = self._r()
        s, prev = r["s3"], r["s2"]["after"]
        e1 = next(z for z in s["zones"] if "col-drop-edge" in z["cls"] and z["row"] == "1")
        self.assertEqual(e1["parent"], "chat-pane", "the top row's edge rides the first pane, its rightmost")
        gh = s["ghost"]
        self.assertEqual(gh["text"], "docs")
        self.assertLessEqual(abs(gh["top"] - prev["row1"]["top"]), 2); self.assertLessEqual(abs(gh["height"] - prev["row1"]["height"]), 2, "the rectangle at the top row's height, not the area's")
        a = s["after"]
        self.assertEqual(a["frames"], ["f-chat", "f-chat-4", "f-chat-2", "f-chat-3"], "the walk: the top row left to right, then the bottom row")
        self.assertEqual(json.loads(a["cols"]), {"v": 2, "cols": [{"n": 2, "ids": [SID_B], "row": 2}, {"n": 3, "ids": [SID_C], "row": 2}, {"n": 4, "ids": [SID_D]}], "rowSplit": 0.5})
        self._assert_rows_stacked(a, "two over two")
        for k in ("p1", "p4"):
            self.assertLessEqual(abs(a[k]["top"] - a["row1"]["top"]), 1, k + " is in the top row"); self.assertLessEqual(abs(a[k]["height"] - a["row1"]["height"]), 1)
        for k in ("p2", "p3"):
            self.assertLessEqual(abs(a[k]["top"] - a["row2"]["top"]), 1, k + " is in the bottom row"); self.assertLessEqual(abs(a[k]["height"] - a["row2"]["height"]), 1)
        panes = [a[k] for k in ("p1", "p2", "p3", "p4")]
        for i in range(4):
            for j in range(i + 1, 4):
                self.assertFalse(self._overlap(panes[i], panes[j]), "panes %d and %d overlap: %r / %r" % (i, j, panes[i], panes[j]))
        self.assertLessEqual(abs(a["p1"]["right"] + 7 - a["p4"]["left"]), 1, "column 4 beside the first pane behind a 7 px gutter")
        half = (prev["p1"]["width"] - 7) / 2
        self.assertLessEqual(abs(a["p1"]["width"] - half), SLACK_PX); self.assertLessEqual(abs(a["p4"]["width"] - half), SLACK_PX, "the top row's halving")
        self.assertLessEqual(abs(a["p2"]["width"] - prev["p2"]["width"]), 1, "the bottom row is untouched by a halving in the top row")
        self.assertEqual(a["nonce"], r["before"]["nonce"])

    def test_4_at_the_cap_every_making_zone_is_refused_and_a_drop_changes_nothing(self):
        r = self._r()
        s, prev = r["s4"], r["s3"]["after"]
        making = [z for z in s["zones"] if "col-drop-edge" in z["cls"] or "col-drop-bottom" in z["cls"]]
        self.assertEqual(len(making), 3, "the two edges and the bottom zone: %r" % s["zones"])
        self.assertTrue(all(z["refused"] == "1" for z in making), "every making zone is mounted refused: %r" % making)
        self.assertEqual(sorted(s["ghost"]["cls"].split()), ["on", "refused"]); self.assertEqual(s["ghost"]["text"], "Four columns at most")
        a = s["after"]
        self.assertEqual(a["frames"], prev["frames"], "nothing opened"); self.assertEqual(a["cols"], prev["cols"], "nothing moved")
        self.assertIn(SID_E, a["col1Tabs"], "E is still the first column's")
        self.assertEqual(a["nonce"], r["before"]["nonce"])

    def test_5_the_row_gutter_changes_the_share_and_a_reload_restores_it(self):
        r = self._r()
        s = r["s5"]
        b, a = s["before"], s["after"]
        split = json.loads(a["cols"])["rowSplit"]
        self.assertGreater(split, 0.5, "dragged down: the top row's share grew: %r" % split)
        self.assertLess(split, 1)
        total = a["row1"]["height"] + a["row2"]["height"]
        self.assertLessEqual(abs(a["row1"]["height"] / total - split), 0.02, "the rows' heights follow the share: %r / %r vs %r" % (a["row1"], a["row2"], split))
        self.assertLessEqual(abs(a["row1"]["height"] - (b["row1"]["height"] + 120)), SLACK_PX, "about the drag: %r -> %r" % (b["row1"], a["row1"]))
        self.assertLessEqual(abs(a["area"]["height"] - b["area"]["height"]), 1, "the area itself did not move")
        self.assertEqual(a["nonce"], r["before"]["nonce"], "a gutter drag reloads nothing")
        rl = s["reloaded"]
        self.assertEqual(json.loads(rl["cols"]), json.loads(a["cols"]), "the store survives the reload as written")
        self.assertEqual(rl["frames"], ["f-chat", "f-chat-4", "f-chat-2", "f-chat-3"], "the arrangement comes back in its rows")
        self._assert_rows_stacked(rl, "after the reload")
        total2 = rl["row1"]["height"] + rl["row2"]["height"]
        self.assertLessEqual(abs(rl["row1"]["height"] / total2 - split), 0.02, "…at the dragged share")
        self.assertIsNone(rl["nonceGone"], "a reload is a fresh document (the nonce is gone), so the steps after it stamp anew")
        self.assertTrue(s["nonce2"].startswith("n-"))

    def test_6_the_bottom_row_folds_when_its_last_column_goes_and_the_store_is_the_shape_from_before_the_rows(self):
        r = self._r()
        s = r["s6"]
        onB = s["onB"]
        self.assertEqual(onB["frames"], ["f-chat", "f-chat-4", "f-chat-3"]); self.assertIsNone(onB["p2"])
        self._assert_rows_stacked(onB, "one member left in the bottom row")
        self.assertLessEqual(abs(onB["p3"]["width"] - onB["row2"]["width"]), 1, "the remaining column takes the row (its gutter went with the closed neighbour)")
        self.assertLessEqual(abs(onB["p3"]["left"] - onB["row2"]["left"]), 1)
        self.assertEqual(onB["nonce"], r["s5"]["nonce2"])
        onC = s["onC"]
        self.assertEqual(onC["cls"], "", "the row folded: no .rows")
        self.assertEqual(onC["row2"]["display"], "none"); self.assertEqual(onC["gvRows"]["display"], "none")
        self.assertLessEqual(abs(onC["row1"]["height"] - onC["area"]["height"]), 1, "the top row takes the full height: %r vs %r" % (onC["row1"], onC["area"]))
        self.assertLessEqual(abs(onC["p1"]["height"] - onC["area"]["height"]), 1); self.assertLessEqual(abs(onC["p4"]["height"] - onC["area"]["height"]), 1)
        self.assertEqual(onC["frames"], ["f-chat", "f-chat-4"])
        self.assertEqual(onC["bytes"], json.dumps({"v": 2, "cols": [{"n": 4, "ids": [SID_D]}]}, separators=(",", ":")),
                         "BYTE-IDENTICAL to what a browser that never stacked writes: no row, no rowSplit")
        self.assertEqual(onC["nonce"], r["s5"]["nonce2"], "the fold re-parents nothing either")

    def test_7_back_to_one_column(self):
        r = self._r()
        s = r["s7"]
        self.assertEqual(s["frames"], ["f-chat"]); self.assertEqual(json.loads(s["cols"]), {"v": 2, "cols": []})
        self.assertEqual(s["cls"], ""); self.assertLessEqual(abs(s["p1"]["width"] - s["row1"]["width"]), 1, "the first pane has the row again")
        self.assertEqual(sorted(s["col1Tabs"]), sorted([SID_A, SID_B, SID_C, SID_D, SID_E]))
        self.assertEqual(s["nonce"], r["s5"]["nonce2"])

    def test_8_the_whole_story_runs_in_under_a_minute_and_a_half_and_left_its_screenshots(self):
        r = self._r()
        self.assertLess(r["ms"], 90_000, "the driver waits on conditions, never on fixed sleeps: %d ms" % r["ms"])
        self.assertEqual(r.get("shots"), ["stack-1-1-dark.png", "stack-1-1-light.png", "grid-2-2-dark.png", "grid-2-2-light.png"])
        for name in r["shots"]:
            self.assertTrue(os.path.getsize(os.path.join(SHOTS, name)) > 10_000, name + " is a real screenshot")


if __name__ == "__main__":
    unittest.main()
