#!/usr/bin/env python3
"""A documented (cut-floor) long session in the shell's SPLIT, LOCAL (the long-session scroll-back diagnosis, the split leg,
2026-09-15). The bare /chat page fills a cut floor to the head (test_history_documented_local_served.py); this
drives the SAME cut-floor session inside the dashboard SHELL, where the chat pane is a /chat?col=N iframe with
its own #content, gap observer and socket. Local sessions (a bare uuid, no host prefix) move between columns
reliably, so this isolates the SPLIT mechanism from the federated relay and the gapHasAsk host-prefix quirk.

Scenarios, each a fresh shell load: col1 (the base pane, no split, a control), right (the session moved to a
new right column), left (the session in col 1 while a second session holds col 2), hidden (the session a
non-active tab of a column that becomes active after its frame landed). Per scenario: the scroll container and
observer root the column used, whether a .tx-gap element materializes with a real height, and whether scrolling
the column to the top asks loadTurns and the head page fills.

One hermetic kernel. Synthetic only: placeholder uuids, the 4a served builder's invented text."""
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

from tests.dist_copy import copy_dist
from romp_load import load_source

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
EXT = os.path.join(ROOT, "vscode-extension")
sys.path.insert(0, HERE)
import test_ship_reship_served as _lab                      # noqa: E402
from test_asm_checkpoint_served import transcript           # noqa: E402

os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)
_ST0 = Path(os.environ["XDG_STATE_HOME"]) / "romp"
_ST0.mkdir(parents=True, exist_ok=True)
(_ST0 / "session-hosts").write_text("off\n")

SID = "eeee2222-3333-4444-5555-666666666601"    # the cut-floor long session
SID2 = "eeee2222-3333-4444-5555-666666666602"   # a short second session, to make a split
COLOR = ("#64b5f6", "#0c1a2e")


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _short(t0, sid, n=4):
    out, parent = [], None
    for i in range(n):
        u, a = sid[:8] + "-u%03d" % i, sid[:8] + "-a%03d" % i
        out.append({"type": "user", "uuid": u, "parentUuid": parent, "sessionId": sid, "cwd": "/w/notes-api",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t0 + i * 120)),
                    "promptSource": "typed", "message": {"role": "user", "content": "short turn %d" % i}})
        out.append({"type": "assistant", "uuid": a, "parentUuid": u, "sessionId": sid, "cwd": "/w/notes-api",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t0 + i * 120 + 30)),
                    "message": {"role": "assistant", "model": "claude-opus-5", "stop_reason": "end_turn",
                                "content": [{"type": "text", "text": "short reply %d" % i}]}})
        parent = a
    return out


DRIVER = r"""
import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(process.env.EXT_PKG);
const { chromium } = require("playwright");
const cfg = JSON.parse(fs.readFileSync(process.env.CFG, "utf8"));   // {url, scenario, sid, sid2}
let browser;
try { browser = await chromium.launch(cfg.launch || {}); }
catch (e) { console.error("browser-launch-failed: " + e); process.exit(3); }
const page = await browser.newPage({ viewport: { width: 1400, height: 720 } });
page.on("pageerror", () => {});
const asks = [];
await page.routeWebSocket((u) => /\/ws(\?|$)/.test(u.pathname + (u.search || "")), (ws) => {
  const server = ws.connectToServer();
  ws.onMessage((m) => { try { const f = JSON.parse(m); if (f && f.type === "loadTurns" && f.id === cfg.sid) asks.push([f.lo, f.hi]); } catch (e) {} server.send(m); });
  server.onMessage((m) => ws.send(m));
  server.onClose(() => ws.close()); ws.onClose(() => server.close());
});
const out = { scenario: cfg.scenario, died: null };
const frameOf = async (fid) => { const h = await page.$("#" + fid); return h ? await h.contentFrame() : null; };
const tabsIn = async (fid) => { const fr = await frameOf(fid); return fr ? await fr.evaluate(() => Array.from(document.querySelectorAll("#tabs .tab[data-id]")).map((t) => t.getAttribute("data-id"))) : []; };
const activate = async (fid, sid) => { const fr = await frameOf(fid); await fr.locator('#tabs .tab[data-id="' + sid + '"]').first().click().catch(() => {}); };
try {
  await page.addInitScript(() => { try { if (window === window.top) { localStorage.removeItem("romp-chat-cols"); Object.keys(localStorage).filter((k) => k.indexOf("romp-vscode-state-chat") === 0).forEach((k) => localStorage.removeItem(k)); } } catch (e) {} });   // TOP frame only: a column iframe's load must not wipe the split state mid-flight
  await page.goto(cfg.url);
  await page.waitForFunction((sid) => { const f = document.getElementById("f-chat"); const d = f && f.contentDocument; return !!(d && d.querySelector('#tabs .tab[data-id="' + sid + '"]')); }, cfg.sid, { timeout: 40000 });
  let targetFid = "f-chat-2";
  if (cfg.scenario === "col1") {
    await activate("f-chat", cfg.sid);           // no split: just show the cut-floor session in the base pane
    targetFid = "f-chat";
  } else if (cfg.scenario === "right") {
    out.move = await page.evaluate((sid) => { const f = window.__rompMoveTab(sid, "new"); return f ? f.id : null; }, cfg.sid);
  } else if (cfg.scenario === "left") {
    out.move = await page.evaluate((s2) => { const f = window.__rompMoveTab(s2, "new"); return f ? f.id : null; }, cfg.sid2);
    targetFid = "f-chat";
    await frameOf("f-chat").then((fr) => fr && fr.locator('#tabs .tab[data-id="' + cfg.sid + '"]').first().click().catch(() => {}));
  } else if (cfg.scenario === "hidden") {
    out.move = await page.evaluate((sid) => { const f = window.__rompMoveTab(sid, "new"); return f ? f.id : null; }, cfg.sid);
    await page.waitForTimeout(500);
    await page.evaluate((s2) => window.__rompMoveTab(s2, 2), cfg.sid2);   // the short one joins col 2 and takes focus
    await page.waitForTimeout(800);
  }
  await page.waitForFunction((fid) => !!document.getElementById(fid), targetFid, { timeout: 20000 });
  out.paneRect = await page.evaluate((fid) => { const el = document.getElementById(fid); if (!el) return null; const p = el.closest(".pane") || el; const r = p.getBoundingClientRect(); const fr = el.getBoundingClientRect();
    return { paneW: Math.round(r.width), paneH: Math.round(r.height), frameW: Math.round(fr.width), frameH: Math.round(fr.height), paneDisplay: getComputedStyle(p).display, groupShown: document.body.classList.contains("po-chat") }; }, targetFid);
  const tf = await frameOf(targetFid);
  if (cfg.scenario === "hidden") {
    await tf.waitForFunction((sid) => !!document.querySelector('#tabs .tab[data-id="' + sid + '"]'), cfg.sid, { timeout: 20000 });
    out.hiddenBefore = await tf.evaluate((sid) => { const t = document.querySelector('#tabs .tab.active[data-id]'); return { active: t ? t.getAttribute("data-id") : null, regionsBuilt: !!(typeof window.__rompRegions === "function" && window.__rompRegions(sid)) }; }, cfg.sid);
    await tf.locator('#tabs .tab[data-id="' + cfg.sid + '"]').first().click();
  }
  await tf.waitForFunction(() => document.querySelectorAll("#content .turn[data-uuid]").length >= 1, null, { timeout: 30000 });
  await page.waitForTimeout(1000);
  out.tabs = { col1: await tabsIn("f-chat"), col2: await tabsIn("f-chat-2") };
  out.boot = await tf.evaluate((sid) => {
    const c = document.getElementById("content");
    const rect = c ? c.getBoundingClientRect() : null;
    const gaps = Array.from(document.querySelectorAll("#content .tx-gap")).map((g) => ({ lo: Number(g.dataset.lo), hi: Number(g.dataset.hi), sid: g.dataset.sid, h: g.offsetHeight }));
    const spacer = document.querySelector("#content .tx-spacer-top");
    return { contentId: c ? c.id : null, w: rect ? Math.round(rect.width) : null, h: rect ? Math.round(rect.height) : null,
             scrollH: c ? c.scrollHeight : null, clientH: c ? c.clientHeight : null, canScroll: c ? c.scrollHeight - c.clientHeight > 4 : null,
             gaps, spacerTopH: spacer ? spacer.offsetHeight : null, turns: document.querySelectorAll("#content .turn[data-uuid]").length,
             regions: (typeof window.__rompRegions === "function") ? window.__rompRegions(sid) : null };
  }, cfg.sid);
  const bootTurns = out.boot.turns;
  await tf.evaluate(() => { const c = document.getElementById("content"); c.scrollTop = 0; c.dispatchEvent(new Event("scroll")); });
  await page.waitForTimeout(300);
  await tf.evaluate(() => { const c = document.getElementById("content"); c.scrollTop = 0; c.dispatchEvent(new Event("scroll")); });
  try { await tf.waitForFunction((n) => document.querySelectorAll("#content .turn[data-uuid]").length > n, bootTurns, { timeout: 10000 }); } catch (e) {}
  await page.waitForTimeout(1800);
  out.asks = asks.slice(); out.asked = asks.length > 0;
  out.after = await tf.evaluate((sid) => {
    const c = document.getElementById("content");
    return { canScroll: c.scrollHeight - c.clientHeight > 4, turns: document.querySelectorAll("#content .turn[data-uuid]").length,
             gaps: Array.from(document.querySelectorAll("#content .tx-gap")).map((g) => ({ lo: Number(g.dataset.lo), hi: Number(g.dataset.hi), h: g.offsetHeight })),
             regions: (typeof window.__rompRegions === "function") ? window.__rompRegions(sid) : null };
  }, cfg.sid);
} catch (e) {
  out.died = String(e).slice(0, 500);
}
process.stdout.write("RESULT:" + JSON.stringify(out) + "\n");
await browser.close();
"""


class LocalSplitCutFloor(unittest.TestCase):
    maxDiff = None
    _cache = {}

    @classmethod
    def setUpClass(cls):
        try:
            cls._boot()
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def _boot(cls):
        if not os.path.isdir(os.path.join(EXT, "node_modules", "playwright")):
            raise unittest.SkipTest("extension deps absent")
        probe = subprocess.run(["node", "-e", "const p=require(process.argv[1]);process.stdout.write(p.chromium.executablePath())",
                                os.path.join(EXT, "node_modules", "playwright")], capture_output=True, text=True)
        if probe.returncode != 0 or not os.path.exists(probe.stdout.strip()):
            raise unittest.SkipTest("no playwright browser")
        cls.lab = tempfile.mkdtemp(prefix="local-split-cf-")
        b = subprocess.run(["node", "esbuild.js"], cwd=EXT, capture_output=True, text=True)
        if b.returncode != 0:
            raise unittest.SkipTest("esbuild failed: " + (b.stderr or b.stdout)[-200:])
        copy_dist(os.path.join(EXT, "dist"), os.path.join(cls.lab, "dist"))
        sub = os.path.join(cls.lab, "solo")
        state = os.path.join(sub, "xdg", "romp")
        claude = os.path.join(sub, "claude")
        cwd = os.path.join(sub, "proj")
        for d in ("names", "sdk", "states", "checkpoints"):
            os.makedirs(os.path.join(state, d), exist_ok=True)
        os.makedirs(cwd, exist_ok=True)
        Path(state, "session-hosts").write_text("off\n")
        Path(state, "usage.json").write_text(json.dumps({"five_hour": {"pct": 10}, "seven_day": {"pct": 10}}))
        proj = os.path.join(claude, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd)))
        os.makedirs(proj, exist_ok=True)
        now = int(time.time())
        for sid, sname in ((SID, "api"), (SID2, "web")):
            Path(state, "names", sid).write_text("%s\t%s\t%s\t%s\n" % (sname, cwd, COLOR[0], COLOR[1]))
            Path(state, "sdk", sid + ".json").write_text(json.dumps(
                {"sid": sid, "name": sname, "cwd": cwd, "mode": "auto", "effort": "high",
                 "lastSid": sid, "alive": True, "model": "claude-opus-5", "liveModel": "Opus 5"}))
        Path(proj, SID + ".jsonl").write_text("".join(json.dumps(r) + "\n" for r in transcript(now - 86400, turns=600, compact_every=150)))
        Path(proj, SID2 + ".jsonl").write_text("".join(json.dumps(r) + "\n" for r in _short(now - 3600, SID2)))
        # seed the cut-floor document for SID
        os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
        km = load_source("romp_kernel_localsplit_seed", os.path.join(BIN, "romp-kernel"))
        jd, em = km.jd, km.em
        saved_state = jd.STATE
        leaf = os.path.join(proj, SID + ".jsonl")
        try:
            jd._rebind_state(Path(state))
            em.set_checkpoint_dir(lambda: jd.STATE / "checkpoints")
            row = {"sid": SID, "name": "api", "path": leaf, "mtime": now, "anchor": SID}
            saved = (km._sessions, km._live_map)
            km._sessions = lambda now=None, **kw: [row]
            km._live_map = lambda: {}
            try:
                km.build_session(SID, now, {}, floor=0)
                ok = em.asm_checkpoint_write(leaf, SID, sdk_human=True, tree=km._parse(leaf, SID, now))
                ckpts = [os.path.basename(f) for f in glob.glob(os.path.join(str(state), "checkpoints", "*.asm.json.gz"))]
            finally:
                km._sessions, km._live_map = saved
            cls.seed = {"ok": bool(ok), "ckpts": ckpts}
            if not ok or not ckpts:
                raise unittest.SkipTest("could not seed a cut-floor document: %r" % cls.seed)
        finally:
            em.set_checkpoint_dir(None)
            jd._rebind_state(saved_state)
        cls.port, cls.token = _free_port(), "testtok-local-scf"
        env = _lab.kernel_env(sub, claude, os.path.join(cls.lab, "dist"), cls.port, cls.token)
        cls.klog = os.path.join(cls.lab, "kernel.log")
        cls.kernel = subprocess.Popen([os.path.join(BIN, "romp-kernel")], stdout=open(cls.klog, "w"), stderr=subprocess.STDOUT, env=env)
        cls.procs = [cls.kernel]
        for _ in range(120):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/healthz" % cls.port, timeout=1); break
            except Exception:
                time.sleep(0.5)
        else:
            cls.kernel.kill(); raise unittest.SkipTest("kernel never served /healthz")

    @classmethod
    def tearDownClass(cls):
        for p in getattr(cls, "procs", []):
            try:
                p.kill(); p.wait()
            except Exception:
                pass
        shutil.rmtree(getattr(cls, "lab", ""), ignore_errors=True)

    def _drive(self, scenario):
        if scenario not in type(self)._cache:
            cfg = os.path.join(self.lab, "cfg-%s.json" % scenario)
            with open(cfg, "w") as f:
                json.dump({"url": "http://127.0.0.1:%d/?token=%s" % (self.port, self.token),
                           "scenario": scenario, "sid": SID, "sid2": SID2}, f)
            driver = os.path.join(self.lab, "driver-%s.mjs" % scenario)
            Path(driver).write_text(DRIVER)
            p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=400,
                               env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
            if "browser-launch-failed" in p.stderr:
                raise unittest.SkipTest("no playwright browser")
            line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT:")), None)
            self.assertIsNotNone(line, "no RESULT for %s (stderr: %s)" % (scenario, p.stderr[-1500:]))
            type(self)._cache[scenario] = json.loads(line[len("RESULT:"):])
        r = type(self)._cache[scenario]
        print("LSPLITCF[%s] %s" % (scenario, json.dumps(r)), file=sys.stderr)
        return r

    def _assert_fills(self, scenario):
        r = self._drive(scenario)
        self.assertIsNone(r.get("died"), "%s driver error: %s" % (scenario, r.get("died")))
        b = r.get("boot") or {}
        self.assertEqual(b.get("contentId"), "content", "%s: scroll container is #content: %r" % (scenario, b))
        self.assertTrue(b.get("regions"), "%s: the column holds regions: %r" % (scenario, b))
        self.assertTrue(b.get("gaps") and (b["gaps"][0].get("h") or 0) > 4, "%s: a .tx-gap element with real height exists above the first turn: %r" % (scenario, b))
        self.assertTrue(r.get("asked"), "%s: scrolling the column to the top asked loadTurns: asks=%r" % (scenario, r.get("asks")))
        after = (r.get("after") or {}).get("regions") or []
        self.assertTrue(any(x["kind"] == "run" and x["lo"] == 0 for x in after),
                        "%s: the head page filled (a run at lo 0): after=%r asks=%r" % (scenario, r.get("after"), r.get("asks")))

    def test_col1_base_pane(self):
        self._assert_fills("col1")

    def test_right_column(self):
        self._assert_fills("right")

    def test_left_column(self):
        self._assert_fills("left")

    def test_hidden_then_active_tab(self):
        self._assert_fills("hidden")


if __name__ == "__main__":
    unittest.main()
