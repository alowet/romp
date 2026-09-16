#!/usr/bin/env python3
"""The split-board scroll-back wall (the user's exact wall, 2026-09-15): TWO long cut-floor sessions shown side by
side, one per column, with focus on ONE column. Each column is its own /chat?col=N iframe with its own #content,
gap observer and relay socket. The question the earlier split lab (test_federated_split_cutfloor_served.py) did NOT
answer because its second column held a SHORT session (whose skeleton equals its whole content): does the
NON-FOCUSED column's LONG tab keep a head gap to scroll into, or is it served a skeleton with no head gap. The
driver records each relay socket's dial query (whether it carried an active= term) so the road is measured, not
guessed. Scenarios: focus column one (check column two), and the reverse.

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
SID_R2 = "11111111-2222-4333-8444-000000000904"  # a SECOND long cut-floor remote session (was short; now long, so it too has a head gap)
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
    Path(proj, SID_R2 + ".jsonl").write_text("".join(json.dumps(r) + "\n" for r in transcript(now - 90000, turns=600, compact_every=150)))
    os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
    km = load_source("romp_kernel_twocol_seed", os.path.join(BIN, "romp-kernel"))
    seed = _seed_cutfloor(km, state, os.path.join(proj, SID_R + ".jsonl"), SID_R, now)
    seed2 = _seed_cutfloor(km, state, os.path.join(proj, SID_R2 + ".jsonl"), SID_R2, now)
    if not seed["ok"] or not seed["ckpts"] or not seed2["ok"]:
        raise unittest.SkipTest("could not seed two cut-floor documents: %r %r" % (seed, seed2))
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


# The driver shows TWO long cut-floor sessions side by side (col 1 = remote SID_R, col 2 = remote SID_R2), focuses
# ONE column (cfg.focus), and for BOTH columns records the boot regions (is there a head gap?) and, after scrolling
# that column's #content to the top, whether the head page filled to turn 0 over the relay. It also records every
# intercepted socket's dial URL, so whether each column's relay carried an active= term is measured, not guessed.
DRIVER = r"""
import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(process.env.EXT_PKG);
const { chromium } = require("playwright");
const cfg = JSON.parse(fs.readFileSync(process.env.CFG, "utf8"));   // {url, focus, remote, remote2, bare, bare2}
let browser;
try { browser = await chromium.launch(cfg.launch || {}); }
catch (e) { console.error("browser-launch-failed: " + e); process.exit(3); }
const page = await browser.newPage({ viewport: { width: 1600, height: 760 } });
page.on("pageerror", () => {});
const dials = [];
const asks = {};   // bare sid -> [[lo,hi]...]
asks[cfg.bare] = []; asks[cfg.bare2] = [];
let hostDown = false;   // when true, the remote host's relay dials are refused (the host is offline)
await page.routeWebSocket((u) => /\/ws(\?|$)/.test(u.pathname + (u.search || "")), (ws) => {
  try { dials.push(ws.url()); } catch (e) {}
  if (hostDown && /\/remote\//.test(ws.url())) { try { ws.close(); } catch (e) {} return; }   // host offline: refuse the relay
  const server = ws.connectToServer();
  ws.onMessage((m) => { try { const f = JSON.parse(m); if (f && f.type === "loadTurns" && asks[f.id]) asks[f.id].push([f.lo, f.hi]); } catch (e) {} server.send(m); });
  server.onMessage((m) => ws.send(m));
  server.onClose(() => ws.close()); ws.onClose(() => server.close());
});
const out = { focus: cfg.focus, died: null };
const frameOf = async (fid) => { const h = await page.$("#" + fid); return h ? await h.contentFrame() : null; };
const colState = async (fid, rid) => {
  const fr = await frameOf(fid);
  if (!fr) return { missing: true };
  const boot = await fr.evaluate((id) => {
    const c = document.getElementById("content");
    const active = (() => { const t = document.querySelector("#tabs .tab.active[data-id]"); return t ? t.getAttribute("data-id") : null; })();
    const regions = (typeof window.__rompRegions === "function") ? window.__rompRegions(id) : null;
    const gaps = Array.from(document.querySelectorAll("#content .tx-gap")).map((g) => ({ lo: Number(g.dataset.lo), hi: Number(g.dataset.hi), h: g.offsetHeight }));
    return { activeTab: active, regions, gaps, turns: document.querySelectorAll("#content .turn[data-uuid]").length,
             hasGapRegion: !!(regions && regions.some((r) => r.kind === "gap")) };
  }, rid);
  // scroll this column's #content to the top twice (jump), let the observer fire and the relay answer
  await fr.evaluate(() => { const c = document.getElementById("content"); if (c) { c.scrollTop = 0; c.dispatchEvent(new Event("scroll")); } });
  await page.waitForTimeout(300);
  await fr.evaluate(() => { const c = document.getElementById("content"); if (c) { c.scrollTop = 0; c.dispatchEvent(new Event("scroll")); } });
  await page.waitForTimeout(1800);
  const after = await fr.evaluate((id) => {
    return { turns: document.querySelectorAll("#content .turn[data-uuid]").length,
             regions: (typeof window.__rompRegions === "function") ? window.__rompRegions(id) : null,
             gaps: Array.from(document.querySelectorAll("#content .tx-gap")).map((g) => ({ lo: Number(g.dataset.lo), hi: Number(g.dataset.hi), h: g.offsetHeight })) };
  }, rid);
  return { boot, after };
};
try {
  await page.addInitScript(() => { try { if (window === window.top && !sessionStorage.getItem("_labcleared")) { localStorage.removeItem("romp-chat-cols"); Object.keys(localStorage).filter((k) => k.indexOf("romp-vscode-state-chat") === 0).forEach((k) => localStorage.removeItem(k)); sessionStorage.setItem("_labcleared", "1"); } } catch (e) {} });   // first load only, so a reload preserves the split
  await page.goto(cfg.url);
  await page.waitForFunction((ids) => { const f = document.getElementById("f-chat"); const d = f && f.contentDocument; return !!(d && d.querySelector('#tabs .tab[data-id="' + ids[0] + '"]') && d.querySelector('#tabs .tab[data-id="' + ids[1] + '"]')); }, [cfg.remote, cfg.remote2], { timeout: 40000 });
  // move SID_R2 to a NEW column (col 2); the move focuses col 2
  await page.evaluate((r2) => window.__rompMoveTab(r2, "new"), cfg.remote2);
  await page.waitForFunction(() => !!document.getElementById("f-chat-2"), null, { timeout: 20000 });
  await page.waitForTimeout(600);
  // focus col 1 (col1 / reload_empty leave col 2 as the NON-focused column), or col 2 for the mirror
  const focusCol1 = async () => { const f1 = await frameOf("f-chat"); await f1.locator('#tabs .tab[data-id="' + cfg.remote + '"]').first().click(); };
  if (cfg.focus === "col2") { const f2 = await frameOf("f-chat-2"); await f2.locator('#tabs .tab[data-id="' + cfg.remote2 + '"]').first().click(); }
  else { await focusCol1(); }
  await page.waitForTimeout(500);
  if (cfg.focus === "host_offline") {
    // the user's exact road: col 2's remote host is OFFLINE at reload (no strip, !tabOrderSeen for that host), so the
    // one-shot fallback is blocked; then the host comes ONLINE (the relay reopens, the strip arrives) and the shown tab
    // must activate on that event. col 2 stays the NON-focused column and focus must not move off col 1.
    hostDown = true;   // the remote host goes offline
    const f2pre = await frameOf("f-chat-2");
    await f2pre.evaluate(() => { try { const k = "romp-vscode-state-chat:2"; const st = JSON.parse(localStorage.getItem(k) || "{}"); delete st.activeId; localStorage.setItem(k, JSON.stringify(st)); } catch (e) {} location.reload(); });
    await page.waitForTimeout(2600);   // col 2 reloads while the host is down: its relay dial is refused, no strip
    out.offlineFooter = await (async () => { const fr = await frameOf("f-chat-2"); try { return fr ? await fr.evaluate(() => document.querySelectorAll("#content .turn[data-uuid]").length) : null; } catch (e) { return "ERR"; } })();
    hostDown = false;   // the host comes back online: the relay reconnects (federation retry ~2s) and the strip arrives
    await page.waitForTimeout(5000);
    // low a: do NOT re-focus col 1 here. The common out.focusedFrame read below runs before any focusCol1 for this
    // scenario, so a focus hop from the activation is captured, not erased by a click.
  }
  // both columns must have rendered a turn
  const f1 = await frameOf("f-chat"); const f2 = await frameOf("f-chat-2");
  await f1.waitForFunction(() => document.querySelectorAll("#content .turn[data-uuid]").length >= 1, null, { timeout: 30000 });
  await f2.waitForFunction(() => document.querySelectorAll("#content .turn[data-uuid]").length >= 1, null, { timeout: 30000 });
  await page.waitForTimeout(800);
  out.focusedFrame = await page.evaluate(() => (document.activeElement && document.activeElement.id) || null);
  out.col1 = await colState("f-chat", cfg.remote);     // SID_R
  out.col2 = await colState("f-chat-2", cfg.remote2);  // SID_R2
  out.asks = asks;
  out.dials = dials.map((u) => { try { const q = new URL(u); return { path: q.pathname, active: q.searchParams.get("active"), skeleton: q.searchParams.get("skeleton"), col: q.searchParams.get("col") }; } catch (e) { return { raw: String(u) }; } })
                   .filter((d) => (d.path || "").indexOf("/remote/") === 0);
} catch (e) {
  out.died = String(e).slice(0, 500);
}
process.stdout.write("RESULT:" + JSON.stringify(out) + "\n");
await browser.close();
"""


class FederatedTwoColWall(unittest.TestCase):
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
        cls.lab = tempfile.mkdtemp(prefix="fed-twocol-")
        b = subprocess.run(["node", "esbuild.js"], cwd=EXT, capture_output=True, text=True)
        if b.returncode != 0:
            raise unittest.SkipTest("esbuild failed: " + (b.stderr or b.stdout)[-200:])
        copy_dist(os.path.join(EXT, "dist"), os.path.join(cls.lab, "dist"))
        cls.rport, cls.rtoken = _free_port(), "testtok-remote-2c"
        cls.hport, cls.htoken = _free_port(), "testtok-hub-2c"
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

    def _drive(self, focus):
        if focus not in type(self)._cache:
            cfg = os.path.join(self.lab, "cfg-%s.json" % focus)
            with open(cfg, "w") as f:
                json.dump({"url": "http://127.0.0.1:%d/?token=%s" % (self.hport, self.htoken),
                           "focus": focus, "remote": REMOTE, "remote2": REMOTE2, "bare": SID_R, "bare2": SID_R2}, f)
            driver = os.path.join(self.lab, "driver-%s.mjs" % focus)
            Path(driver).write_text(DRIVER)
            p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=400,
                               env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
            if "browser-launch-failed" in p.stderr:
                raise unittest.SkipTest("no playwright browser")
            line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT:")), None)
            self.assertIsNotNone(line, "no RESULT for %s (stderr: %s)" % (focus, p.stderr[-1500:]))
            type(self)._cache[focus] = json.loads(line[len("RESULT:"):])
        r = type(self)._cache[focus]
        print("TWOCOL[%s] %s" % (focus, json.dumps(r)), file=sys.stderr)
        return r

    def _assert_both_fill(self, r, focus):
        self.assertIsNone(r.get("died"), "%s driver error: %s" % (focus, r.get("died")))
        for name, sid in (("col1", SID_R), ("col2", SID_R2)):
            col = r.get(name) or {}
            boot = col.get("boot") or {}
            after = col.get("after") or {}
            self.assertTrue(boot.get("hasGapRegion"),
                            "%s: %s (a long session) shows a HEAD GAP at boot, focused or not: boot=%r dials=%r" % (focus, name, boot, r.get("dials")))
            self.assertTrue(any(x.get("kind") == "run" and x.get("lo") == 0 for x in (after.get("regions") or [])),
                            "%s: %s filled to turn 0 after scrolling to the top: after=%r asks=%r" % (focus, name, after, r.get("asks")))

    def test_focus_column_one_column_two_still_has_a_head_gap(self):
        self._assert_both_fill(self._drive("col1"), "col1")

    def test_focus_column_two_column_one_still_has_a_head_gap(self):
        self._assert_both_fill(self._drive("col2"), "col2")

    def test_host_offline_at_reload_then_online_column_two_fills_without_a_focus_change(self):
        # col 2's remote host is OFFLINE at reload (no strip: !tabOrderSeen for that host); when the host comes back
        # ONLINE the strip arrives and the shown tab activates on that event, filling to turn 0 with a head gap while
        # focus stays on col 1. This is a REGRESSION, green at base: in a clean lab the original one-shot re-runs on the
        # re-listing strip and fills col 2 too, so the base does NOT stay a skeleton. The user's block (the one-shot's
        # revalidation losing a race to the kill, and the re-listing not re-running) is not hermetically reproducible;
        # the red-first is the source pins in relay-active-rearm.test.ts.
        r = self._drive("host_offline")
        self.assertIsNone(r.get("died"), "driver error: %s" % r.get("died"))
        c2 = r.get("col2") or {}
        self.assertTrue((c2.get("boot") or {}).get("hasGapRegion"),
                        "col 2 (long, host offline-at-reload then online, non-focused) shows a HEAD GAP: boot=%r offlineFooter=%r dials=%r"
                        % (c2.get("boot"), r.get("offlineFooter"), r.get("dials")))
        self.assertTrue(any(x.get("kind") == "run" and x.get("lo") == 0 for x in ((c2.get("after") or {}).get("regions") or [])),
                        "col 2 fills to turn 0 on the strip's arrival, no scroll: after=%r" % c2.get("after"))
        self.assertNotEqual(r.get("focusedFrame"), "f-chat-2",
                            "the silent activation did NOT move focus to col 2: focusedFrame=%r" % r.get("focusedFrame"))


if __name__ == "__main__":
    unittest.main()
