#!/usr/bin/env python3
"""The LOCAL redial self-heal (the long-session scroll-back diagnosis, 2026-09-15, review round two). The FEDERATED
twin (test_federated_history_scroll_served.py FederatedRedialReask) cuts a RELAY socket mid-answer, where a relay drop
fires no romp:wsdown so the page must re-send the outstanding loadTurns itself on romp:hostRelayUp. The LOCAL road is
different and needs no such re-ask: a cut-floor session is served to a proto-2 page; the page scrolls up to ask the
first head page, the LOCAL socket is cut with that loadTurns outstanding (its reply lost, and onWireDown clears the
window-ask records), and the page then SITS (no further scroll). The socket's reopen rebuilds the session, the gap
observer re-fires on the recreated gap element (gapHasAsk no longer suppresses it, the records were cleared), and it
re-asks by itself, so the page fills with no scroll, no timer and no local re-ask. This lab pins that self-heal: it is
why the redial fix ships the parse plus the RELAY re-ask (the user's road), and dropped a local re-ask this road never
needed (the review's medium 1).

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

SID = "eeee3333-4444-5555-6666-777777777701"
COLOR = ("#64b5f6", "#0c1a2e")


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


DRIVER = r"""
import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(process.env.EXT_PKG);
const { chromium } = require("playwright");
const cfg = JSON.parse(fs.readFileSync(process.env.CFG, "utf8"));   // {chat, sid}
let browser;
try { browser = await chromium.launch(cfg.launch || {}); }
catch (e) { console.error("browser-launch-failed: " + e); process.exit(3); }
const page = await browser.newPage({ viewport: { width: 1000, height: 640 } });
page.on("pageerror", () => {});
await page.addInitScript((sid) => {
  window.__sent = []; window.__wsup = 0; window.__cut = false;
  window.addEventListener("romp:wsup", () => { window.__wsup++; });
  const send = WebSocket.prototype.send;
  WebSocket.prototype.send = function (d) {
    try { const m = JSON.parse(d);
      if (m && m.type) window.__sent.push({ type: m.type, id: m.id || null, lo: m.lo, hi: m.hi });
      if (m && m.type === "loadTurns" && m.id === sid && !window.__cut) {
        window.__cut = true; window.__cutSpan = [m.lo, m.hi];
        try { this.close(); } catch (e) {}    // cut the LOCAL socket with this loadTurns outstanding: its reply is lost, the shim redials
        return;                                 // drop this first ask; a later (re-ask) loadTurns for the same span passes through
      }
    } catch (e) {}
    return send.call(this, d);
  };
}, cfg.sid);
const out = { died: null };
const askCount = (span) => page.evaluate(([s, sp]) => window.__sent.filter((m) => m.type === "loadTurns" && m.id === s && m.lo === sp[0] && m.hi === sp[1]).length, [cfg.sid, span]);
try {
  await page.goto(cfg.chat);
  await page.waitForSelector("#content .turn[data-uuid]", { timeout: 40000 });
  await page.waitForTimeout(800);
  out.bootTurns = await page.evaluate(() => document.querySelectorAll("#content .turn[data-uuid]").length);
  // jump to the TOP so the head-gap element materializes past virtualization and its observer fires the first
  // loadTurns (which the send hook cuts); a few jumps until __cut, then STOP (no scroll drives the fill below)
  for (let i = 0; i < 20 && !(await page.evaluate(() => window.__cut)); i++) {
    await page.evaluate(() => { const c = document.getElementById("content"); c.scrollTop = 0; c.dispatchEvent(new Event("scroll")); });
    await page.waitForTimeout(300);
  }
  out.cut = await page.evaluate(() => ({ cut: !!window.__cut, span: window.__cutSpan || null }));
  // SIT: no further scroll. Wait for the redial (romp:wsup) and the outstanding page to re-load via the re-ask.
  const span = out.cut.span;
  try { await page.waitForFunction(() => window.__wsup > 0, null, { timeout: 15000 }); } catch (e) {}
  let filled = false;
  if (span) { try { await page.waitForFunction(([s, sp, n]) => document.querySelectorAll("#content .turn[data-uuid]").length > n, [cfg.sid, span, out.bootTurns], { timeout: 12000 }); filled = true; } catch (e) {} }
  await page.waitForTimeout(1200);
  out.wsup = await page.evaluate(() => window.__wsup);
  out.reasks = span ? await askCount(span) : 0;   // the first ask was DROPPED; a value >= 2 means the redial re-sent it (and it landed)
  out.filled = filled;
  out.afterTurns = await page.evaluate(() => document.querySelectorAll("#content .turn[data-uuid]").length);
  out.regionsAfter = await page.evaluate((sid) => (typeof window.__rompRegions === "function" ? window.__rompRegions(sid) : null), cfg.sid);
} catch (e) {
  out.died = String(e).slice(0, 400);
}
process.stdout.write("RESULT:" + JSON.stringify(out) + "\n");
await browser.close();
"""


class LocalRedialReask(unittest.TestCase):
    maxDiff = None
    _r = None

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
        cls.lab = tempfile.mkdtemp(prefix="local-redial-")
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
        Path(state, "names", SID).write_text("api\t%s\t%s\t%s\n" % (cwd, COLOR[0], COLOR[1]))
        Path(state, "sdk", SID + ".json").write_text(json.dumps(
            {"sid": SID, "name": "api", "cwd": cwd, "mode": "auto", "effort": "high",
             "lastSid": SID, "alive": True, "model": "claude-opus-5", "liveModel": "Opus 5"}))
        proj = os.path.join(claude, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd)))
        os.makedirs(proj, exist_ok=True)
        leaf = os.path.join(proj, SID + ".jsonl")
        now = int(time.time())
        Path(leaf).write_text("".join(json.dumps(r) + "\n" for r in transcript(now - 86400, turns=600, compact_every=150)))
        os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
        km = load_source("romp_kernel_localredial_seed", os.path.join(BIN, "romp-kernel"))
        jd, em = km.jd, km.em
        saved_state = jd.STATE
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
        cls.port, cls.token = _free_port(), "testtok-local-redial"
        env = _lab.kernel_env(sub, claude, os.path.join(cls.lab, "dist"), cls.port, cls.token)
        cls.klog = os.path.join(cls.lab, "kernel.log")
        k = subprocess.Popen([os.path.join(BIN, "romp-kernel")], stdout=open(cls.klog, "w"), stderr=subprocess.STDOUT, env=env)
        cls.procs.append(k)
        for _ in range(120):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/healthz" % cls.port, timeout=1); break
            except Exception:
                time.sleep(0.5)
        else:
            k.kill(); raise unittest.SkipTest("kernel never served /healthz")

    @classmethod
    def tearDownClass(cls):
        for p in getattr(cls, "procs", []):
            try:
                p.kill(); p.wait()
            except Exception:
                pass
        shutil.rmtree(getattr(cls, "lab", ""), ignore_errors=True)

    def _result(self):
        if type(self)._r is None:
            cfg = os.path.join(self.lab, "cfg.json")
            with open(cfg, "w") as f:
                json.dump({"chat": "http://127.0.0.1:%d/chat?token=%s" % (self.port, self.token), "sid": SID}, f)
            driver = os.path.join(self.lab, "driver.mjs")
            Path(driver).write_text(DRIVER)
            p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=400,
                               env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
            if "browser-launch-failed" in p.stderr:
                raise unittest.SkipTest("no playwright browser")
            line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT:")), None)
            self.assertIsNotNone(line, "no RESULT (stderr: %s)" % p.stderr[-1500:])
            type(self)._r = json.loads(line[len("RESULT:"):])
        print("LOCALREDIAL %s" % json.dumps(type(self)._r), file=sys.stderr)
        return type(self)._r

    def test_the_local_redial_self_heals_the_outstanding_page_with_no_scroll(self):
        r = self._result()
        self.assertIsNone(r.get("died"), "driver error: %s" % r.get("died"))
        self.assertTrue((r.get("cut") or {}).get("cut"), "the first loadTurns fired and cut the local socket: %r" % r.get("cut"))
        self.assertGreater(r.get("wsup") or 0, 0, "the local socket redialed (romp:wsup): %r" % r)
        # the first ask was DROPPED; the outstanding page re-loads because the gap observer re-fires after the redial's
        # rebuild (onWireDown cleared the ask records, so gapHasAsk no longer suppresses it): no scroll, no local re-ask
        self.assertTrue(r.get("filled"), "the outstanding page re-loaded after the redial with no scroll (the observer's self-heal): reasks=%r after=%r boot=%r regions=%r"
                        % (r.get("reasks"), r.get("afterTurns"), r.get("bootTurns"), r.get("regionsAfter")))


if __name__ == "__main__":
    unittest.main()
