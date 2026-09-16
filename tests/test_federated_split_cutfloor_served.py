#!/usr/bin/env python3
"""A documented (cut-floor) long session watched FEDERATED, in a SPLIT COLUMN (the long-session scroll-back diagnosis, the
split leg, 2026-09-15). The unsplit federated cut floor fills to the head (test_federated_cutfloor_served.py);
this drives the SAME session in the shell's side-by-side split, where each column is its own /chat?col=N iframe
with its own #content, gap observer and relay socket. The questions: in a split column does the gap element
materialize past virtualization, does the observer fire when the column's #content is scrolled to its top, and
does the head page fill over the relay. Scenarios: the remote session in the RIGHT column (a new column), in
the LEFT column (col 1 while a second session holds col 2), and as a HIDDEN tab that becomes active after its
frame landed. Report per scenario the observer root and scroll container and whether the gap filled.

Two hermetic kernels, no ssh; hermetic XDG floor at module top. Synthetic only: placeholder uuids, TESTHOST,
the 4a served builder's invented text."""
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

SID_R = "11111111-2222-4333-8444-000000000903"   # the watched remote session, cut-floor
SID_R2 = "11111111-2222-4333-8444-000000000904"  # a short second remote session, to make a split
HOST = "TESTHOST"
REMOTE = HOST + ":" + SID_R
REMOTE2 = HOST + ":" + SID_R2
WID = "hublab"
COLOR = ("#64b5f6", "#0c1a2e")


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _short_transcript(t0, sid, n=4):
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


def _seed_cutfloor(km, state, leaf, sid, now):
    jd, em = km.jd, km.em
    saved_state = jd.STATE
    try:
        jd._rebind_state(Path(state))
        em.set_checkpoint_dir(lambda: jd.STATE / "checkpoints")
        row = {"sid": sid, "name": "api", "path": leaf, "mtime": now, "anchor": sid}
        saved = (km._sessions, km._live_map)
        km._sessions = lambda now=None, **kw: [row]
        km._live_map = lambda: {}
        try:
            km.build_session(sid, now, {}, floor=0)
            ok = em.asm_checkpoint_write(leaf, sid, sdk_human=True, tree=km._parse(leaf, sid, now))
            ckpts = [os.path.basename(f) for f in glob.glob(os.path.join(str(state), "checkpoints", "*.asm.json.gz"))]
        finally:
            km._sessions, km._live_map = saved
        return {"ok": bool(ok), "ckpts": ckpts}
    finally:
        em.set_checkpoint_dir(None)
        jd._rebind_state(saved_state)


def _remote_kernel(lab, port, token):
    """The remote kernel: a cut-floor session SID_R (a seeded assembly document) and a short session SID_R2."""
    name = "testhost"
    state = os.path.join(lab, name, "xdg", "romp")
    claude = os.path.join(lab, name, "claude")
    cwd = os.path.join(lab, name, "proj")
    for d in ("names", "sdk", "states", "checkpoints"):
        os.makedirs(os.path.join(state, d), exist_ok=True)
    os.makedirs(cwd, exist_ok=True)
    Path(state, "session-hosts").write_text("off\n")
    Path(state, "usage.json").write_text(json.dumps({"five_hour": {"pct": 10}, "seven_day": {"pct": 10}}))
    proj = os.path.join(claude, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd)))
    os.makedirs(proj, exist_ok=True)
    now = int(time.time())
    for sid, sname in ((SID_R, "api"), (SID_R2, "web")):
        Path(state, "names", sid).write_text("%s\t%s\t%s\t%s\n" % (sname, cwd, COLOR[0], COLOR[1]))
        Path(state, "sdk", sid + ".json").write_text(json.dumps(
            {"sid": sid, "name": sname, "cwd": cwd, "mode": "auto", "effort": "high",
             "lastSid": sid, "alive": True, "model": "claude-opus-5", "liveModel": "Opus 5"}))
    Path(proj, SID_R + ".jsonl").write_text("".join(json.dumps(r) + "\n" for r in transcript(now - 86400, turns=600, compact_every=150)))
    Path(proj, SID_R2 + ".jsonl").write_text("".join(json.dumps(r) + "\n" for r in _short_transcript(now - 3600, SID_R2)))
    os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
    km = load_source("romp_kernel_split_seed", os.path.join(BIN, "romp-kernel"))
    seed = _seed_cutfloor(km, state, os.path.join(proj, SID_R + ".jsonl"), SID_R, now)
    if not seed["ok"] or not seed["ckpts"]:
        raise unittest.SkipTest("could not seed a cut-floor document: %r" % seed)
    env = _lab.kernel_env(os.path.join(lab, name), claude, os.path.join(lab, "dist"), port, token, ROMP_HOST_NAME=name.upper())
    log = os.path.join(lab, name + "-kernel.log")
    proc = subprocess.Popen([os.path.join(BIN, "romp-kernel")], stdout=open(log, "w"), stderr=subprocess.STDOUT, env=env)
    for _ in range(120):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=1); return proc, log, seed
        except Exception:
            time.sleep(0.5)
    proc.kill(); proc.wait(); raise unittest.SkipTest("remote kernel never served /healthz")


def _hub_kernel(lab, port, token):
    name = "hub"
    state = os.path.join(lab, name, "xdg", "romp")
    claude = os.path.join(lab, name, "claude")
    cwd = os.path.join(lab, name, "proj")
    for d in ("names", "sdk", "states", "checkpoints"):
        os.makedirs(os.path.join(state, d), exist_ok=True)
    os.makedirs(cwd, exist_ok=True)
    Path(state, "session-hosts").write_text("off\n")
    Path(state, "usage.json").write_text(json.dumps({"five_hour": {"pct": 10}, "seven_day": {"pct": 10}}))
    env = _lab.kernel_env(os.path.join(lab, name), claude, os.path.join(lab, "dist"), port, token, ROMP_HOST_NAME=name.upper())
    log = os.path.join(lab, name + "-kernel.log")
    proc = subprocess.Popen([os.path.join(BIN, "romp-kernel")], stdout=open(log, "w"), stderr=subprocess.STDOUT, env=env)
    for _ in range(120):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=1); return proc, log
        except Exception:
            time.sleep(0.5)
    proc.kill(); proc.wait(); raise unittest.SkipTest("hub kernel never served /healthz")


# The driver takes a scenario in cfg.scenario: "right" | "left" | "hidden". It loads the shell fresh (localStorage
# cleared), makes the split for that scenario, scrolls the target column's #content to the top, and reports the
# observer root / scroll container and whether the head page filled over the relay.
DRIVER = r"""
import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(process.env.EXT_PKG);
const { chromium } = require("playwright");
const cfg = JSON.parse(fs.readFileSync(process.env.CFG, "utf8"));   // {url, scenario, remote, remote2, bare}
let browser;
try { browser = await chromium.launch(cfg.launch || {}); }
catch (e) { console.error("browser-launch-failed: " + e); process.exit(3); }
const page = await browser.newPage({ viewport: { width: 1400, height: 720 } });
page.on("pageerror", () => {});
const relayAsks = [];
await page.routeWebSocket((u) => /\/ws(\?|$)/.test(u.pathname + (u.search || "")), (ws) => {
  const server = ws.connectToServer();
  ws.onMessage((m) => { try { const f = JSON.parse(m); if (f && f.type === "loadTurns" && f.id === cfg.bare) relayAsks.push([f.lo, f.hi]); } catch (e) {} server.send(m); });
  server.onMessage((m) => ws.send(m));
  server.onClose(() => ws.close()); ws.onClose(() => server.close());
});
const out = { scenario: cfg.scenario, died: null };
const frameOf = async (fid) => { const h = await page.$("#" + fid); return h ? await h.contentFrame() : null; };
const tabsIn = async (fid) => { const fr = await frameOf(fid); return fr ? await fr.evaluate(() => Array.from(document.querySelectorAll("#tabs .tab[data-id]")).map((t) => t.getAttribute("data-id"))) : []; };
try {
  await page.addInitScript(() => { try { if (window === window.top) { localStorage.removeItem("romp-chat-cols"); Object.keys(localStorage).filter((k) => k.indexOf("romp-vscode-state-chat") === 0).forEach((k) => localStorage.removeItem(k)); } } catch (e) {} });   // TOP frame only
  await page.goto(cfg.url);
  // wait until col 1 (f-chat) lists the remote session (federation merged it)
  await page.waitForFunction((rid) => { const f = document.getElementById("f-chat"); const d = f && f.contentDocument; return !!(d && d.querySelector('#tabs .tab[data-id="' + rid + '"]')); }, cfg.remote, { timeout: 40000 });
  // make the split for the scenario
  let targetFid = "f-chat-2";
  if (cfg.scenario === "right") {
    await page.evaluate((rid) => window.__rompMoveTab(rid, "new"), cfg.remote);   // remote to a NEW right column
  } else if (cfg.scenario === "left") {
    await page.evaluate((r2) => window.__rompMoveTab(r2, "new"), cfg.remote2);      // the SHORT session to the right; remote stays col 1
    targetFid = "f-chat";
  } else if (cfg.scenario === "hidden") {
    await page.evaluate((rid) => window.__rompMoveTab(rid, "new"), cfg.remote);     // remote to col 2
    await page.waitForTimeout(500);
    await page.evaluate((r2) => window.__rompMoveTab(r2, 2), cfg.remote2);          // the short one JOINS col 2 and becomes active (the move focuses it)
    await page.waitForTimeout(800);
  }
  await page.waitForFunction((fid) => !!document.getElementById(fid), targetFid, { timeout: 20000 });
  out.paneRect = await page.evaluate((fid) => { const el = document.getElementById(fid); if (!el) return null; const pn = el.closest(".pane") || el; const r = pn.getBoundingClientRect(); const fr = el.getBoundingClientRect(); return { paneW: Math.round(r.width), paneH: Math.round(r.height), frameW: Math.round(fr.width), frameH: Math.round(fr.height) }; }, targetFid);
  const tf = await frameOf(targetFid);
  if (cfg.scenario === "hidden") {
    // the remote is now the NON-active tab of col 2 (the short one took focus); wait until its frame is BUILT while hidden, then activate it
    await tf.waitForFunction((rid) => !!document.querySelector('#tabs .tab[data-id="' + rid + '"]'), cfg.remote, { timeout: 20000 });
    out.hiddenBefore = await tf.evaluate((rid) => { const t = document.querySelector('#tabs .tab.active[data-id]'); return { active: t ? t.getAttribute("data-id") : null, has: !!(typeof window.__rompRegions === "function" && window.__rompRegions(rid)) }; }, cfg.remote);
    await tf.locator('#tabs .tab[data-id="' + cfg.remote + '"]').first().click();   // hidden -> active
  }
  // the target column shows the remote: wait for a rendered turn
  await tf.waitForFunction(() => document.querySelectorAll("#content .turn[data-uuid]").length >= 1, null, { timeout: 30000 });
  await page.waitForTimeout(1000);
  out.tabs = { col1: await tabsIn("f-chat"), col2: await tabsIn("f-chat-2") };
  out.boot = await tf.evaluate((rid) => {
    const c = document.getElementById("content");
    const rect = c ? c.getBoundingClientRect() : null;
    const gaps = Array.from(document.querySelectorAll("#content .tx-gap")).map((g) => ({ lo: Number(g.dataset.lo), hi: Number(g.dataset.hi), sid: g.dataset.sid, h: g.offsetHeight }));
    const spacer = document.querySelector("#content .tx-spacer-top");
    return { contentId: c ? c.id : null, w: rect ? Math.round(rect.width) : null, h: rect ? Math.round(rect.height) : null,
             scrollH: c ? c.scrollHeight : null, clientH: c ? c.clientHeight : null, canScroll: c ? c.scrollHeight - c.clientHeight > 4 : null,
             gaps, spacerTopH: spacer ? spacer.offsetHeight : null, turns: document.querySelectorAll("#content .turn[data-uuid]").length,
             regions: (typeof window.__rompRegions === "function") ? window.__rompRegions(rid) : null };
  }, cfg.remote);
  const bootTurns = out.boot.turns;
  await tf.evaluate(() => { const c = document.getElementById("content"); c.scrollTop = 0; c.dispatchEvent(new Event("scroll")); });
  await page.waitForTimeout(300);
  await tf.evaluate(() => { const c = document.getElementById("content"); c.scrollTop = 0; c.dispatchEvent(new Event("scroll")); });
  try { await tf.waitForFunction((n) => document.querySelectorAll("#content .turn[data-uuid]").length > n, bootTurns, { timeout: 10000 }); } catch (e) {}
  await page.waitForTimeout(1800);
  out.relayAsks = relayAsks.slice();
  out.asked = relayAsks.length > 0;
  out.after = await tf.evaluate((rid) => {
    const c = document.getElementById("content");
    return { canScroll: c.scrollHeight - c.clientHeight > 4, turns: document.querySelectorAll("#content .turn[data-uuid]").length,
             gaps: Array.from(document.querySelectorAll("#content .tx-gap")).map((g) => ({ lo: Number(g.dataset.lo), hi: Number(g.dataset.hi), h: g.offsetHeight })),
             regions: (typeof window.__rompRegions === "function") ? window.__rompRegions(rid) : null };
  }, cfg.remote);
} catch (e) {
  out.died = String(e).slice(0, 500);
}
process.stdout.write("RESULT:" + JSON.stringify(out) + "\n");
await browser.close();
"""


class FederatedSplitCutFloor(unittest.TestCase):
    maxDiff = None
    _cache = {}

    @classmethod
    def setUpClass(cls):
        cls.procs = []
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
        cls.lab = tempfile.mkdtemp(prefix="fed-split-cf-")
        b = subprocess.run(["node", "esbuild.js"], cwd=EXT, capture_output=True, text=True)
        if b.returncode != 0:
            raise unittest.SkipTest("esbuild failed: " + (b.stderr or b.stdout)[-200:])
        copy_dist(os.path.join(EXT, "dist"), os.path.join(cls.lab, "dist"))
        cls.rport, cls.rtoken = _free_port(), "testtok-remote-scf"
        cls.hport, cls.htoken = _free_port(), "testtok-hub-scf"
        rp, cls.rlog, cls.seed = _remote_kernel(cls.lab, cls.rport, cls.rtoken)
        cls.procs.append(rp)
        hp, cls.hlog = _hub_kernel(cls.lab, cls.hport, cls.htoken)
        cls.procs.append(hp)
        body = json.dumps({"host": HOST, "kernelPort": cls.rport, "busPort": _free_port(), "token": cls.rtoken}).encode()
        req = urllib.request.Request("http://127.0.0.1:%d/checkin?token=%s" % (cls.hport, cls.htoken), data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if not json.loads(resp.read().decode()).get("ok"):
                raise unittest.SkipTest("the hub refused the check-in")
        for _ in range(60):
            rows = []
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/tunnels?token=%s" % (cls.hport, cls.htoken), timeout=3) as r2:
                    rows = json.loads(r2.read().decode()).get("tunnels") or []
            except Exception:
                rows = []
            if next((t for t in rows if t.get("host") == HOST and t.get("status") == "up" and t.get("hasToken")), None):
                break
            time.sleep(0.5)
        else:
            raise unittest.SkipTest("the hub never reported the checked-in peer up")

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
                json.dump({"url": "http://127.0.0.1:%d/?token=%s" % (self.hport, self.htoken),
                           "scenario": scenario, "remote": REMOTE, "remote2": REMOTE2, "bare": SID_R}, f)
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
        print("SPLITCF[%s] %s" % (scenario, json.dumps(r)), file=sys.stderr)
        return r

    def _assert_fills(self, r, scenario):
        self.assertIsNone(r.get("died"), "%s driver error: %s" % (scenario, r.get("died")))
        b = r.get("boot") or {}
        self.assertEqual(b.get("contentId"), "content", "%s: the scroll container is #content: %r" % (scenario, b))
        self.assertTrue(b.get("regions"), "%s: the column holds regions: %r" % (scenario, b))
        self.assertTrue(b.get("gaps"), "%s: a .tx-gap element exists above the first turn: %r" % (scenario, b))
        self.assertTrue(r.get("asked"), "%s: scrolling the column to the top asked loadTurns over the relay: relayAsks=%r" % (scenario, r.get("relayAsks")))
        after = (r.get("after") or {}).get("regions") or []
        self.assertTrue(any(x["kind"] == "run" and x["lo"] == 0 for x in after),
                        "%s: the head page filled over the relay (a run at lo 0): after=%r relayAsks=%r" % (scenario, r.get("after"), r.get("relayAsks")))

    def test_right_column(self):
        self._assert_fills(self._drive("right"), "right")

    def test_left_column(self):
        self._assert_fills(self._drive("left"), "left")

    def test_hidden_then_active_tab(self):
        self._assert_fills(self._drive("hidden"), "hidden")


if __name__ == "__main__":
    unittest.main()
