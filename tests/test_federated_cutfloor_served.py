#!/usr/bin/env python3
"""A documented (cut-floor) long session watched FEDERATED over the relay (the long-session scroll-back diagnosis, the
cut-floor leg, 2026-09-15). With the whole-chat-frames switch OFF (the deployed devbox posture), a long
session's assembly document floors its frame near the tail: floor > 0, tailLo == floor, headKnown false, the
turns below the floor a head gap the proto-2 wire fills with loadTurns pages. The LOCAL leg (a page on the
owning kernel) is covered by test_history_documented_local_served.py and works (the frame carries the floor,
the page builds a head-gap region and element, scrolling to the top asks and the gap fills). THIS tests the
FEDERATED leg: the SAME cut-floor session viewed through a HUB page over the relay, in the skeleton posture the
hub dials (skeleton=1 & active=the remote sid). The questions the manager asked: does the relay-applied frame
carry the floor as the hub receives it, does the page build the head-gap element above the first rendered turn,
does scrolling to the top ask loadTurns over the relay, and does the head page fill.

Two hermetic kernels, no ssh; loads no romp code against live state (a hermetic XDG floor set at module top,
the seed rebinds onto the lab's own remote state root). Synthetic only: placeholder uuids, hostname TESTHOST,
the 4a served builder's invented text.
"""
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
import test_ship_reship_served as _lab                      # noqa: E402  the served-lab kernel environment
from test_asm_checkpoint_served import transcript           # noqa: E402  the compacted long-transcript builder

# hermetic state floor BEFORE any romp import: setUpClass load_source's romp to seed the document, so the floor is
# set at module top, below romp_load and above every load_source (test_state_isolation_order.py)
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)
_ST0 = Path(os.environ["XDG_STATE_HOME"]) / "romp"
_ST0.mkdir(parents=True, exist_ok=True)
(_ST0 / "session-hosts").write_text("off\n")

SID_R = "11111111-2222-4333-8444-000000000902"   # the watched remote session, a documented (cut-floor) long history
HOST = "TESTHOST"
REMOTE = HOST + ":" + SID_R
WID = "hublab"
COLOR = ("#64b5f6", "#0c1a2e")


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _seed_cutfloor(km, state, leaf, sid, now):
    """Seed the assembly document into the remote kernel's OWN checkpoints dir, so its first parse restores lazily
    (cutTurn near the tail) and every proto-2 frame carries floor > 0. The pattern of test_history_documented_local_served.py:
    a whole parse populates the assembly entry, then asm_checkpoint_write with sdk_human matching _display_sdk_human."""
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
            km.build_session(sid, now, {}, floor=0)                                     # whole parse: populate the assembly entry
            ok = em.asm_checkpoint_write(leaf, sid, sdk_human=True, tree=km._parse(leaf, sid, now))
            ckpts = [os.path.basename(f) for f in glob.glob(os.path.join(str(state), "checkpoints", "*.asm.json.gz"))]
            human = bool(km._display_sdk_human(sid))
        finally:
            km._sessions, km._live_map = saved
        return {"ok": bool(ok), "ckpts": ckpts, "sdkHuman": human,
                "stats": em.asm_checkpoint_stats() if not ok else None}
    finally:
        em.set_checkpoint_dir(None)
        jd._rebind_state(saved_state)


def _kernel(lab, name, port, token, seed_session=None):
    """Boot one hermetic lab kernel. seed_session, when given, is (sid, sname, cwd) whose leaf is the compacted long
    transcript and whose assembly document is seeded (a cut floor); else the kernel holds no session (the hub)."""
    state = os.path.join(lab, name, "xdg", "romp")
    claude = os.path.join(lab, name, "claude")
    cwd = os.path.join(lab, name, "proj")
    for d in ("names", "sdk", "states", "checkpoints"):
        os.makedirs(os.path.join(state, d), exist_ok=True)
    os.makedirs(cwd, exist_ok=True)
    Path(state, "session-hosts").write_text("off\n")
    Path(state, "usage.json").write_text(json.dumps({"five_hour": {"pct": 10}, "seven_day": {"pct": 10}}))
    seed = None
    if seed_session:
        sid, sname, _ = seed_session
        Path(state, "names", sid).write_text("%s\t%s\t%s\t%s\n" % (sname, cwd, COLOR[0], COLOR[1]))
        Path(state, "sdk", sid + ".json").write_text(json.dumps(
            {"sid": sid, "name": sname, "cwd": cwd, "mode": "auto", "effort": "high",
             "lastSid": sid, "alive": True, "model": "claude-opus-5", "liveModel": "Opus 5"}))
        proj = os.path.join(claude, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd)))
        os.makedirs(proj, exist_ok=True)
        leaf = os.path.join(proj, sid + ".jsonl")
        now = int(time.time())
        recs = transcript(now - 86400, turns=600, compact_every=150)   # the writer cuts before the last settled turn: a small floored tail over ~2 turns, everything above the head gap
        Path(leaf).write_text("".join(json.dumps(r) + "\n" for r in recs))
        os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
        km = load_source("romp_kernel_cutfloor_seed", os.path.join(BIN, "romp-kernel"))
        seed = _seed_cutfloor(km, state, leaf, sid, now)
        if not seed["ok"] or not seed["ckpts"]:
            raise unittest.SkipTest("could not seed a cut-floor document: %r" % seed)
    env = _lab.kernel_env(os.path.join(lab, name), claude, os.path.join(lab, "dist"), port, token, ROMP_HOST_NAME=name.upper())
    log = os.path.join(lab, name + "-kernel.log")
    proc = subprocess.Popen([os.path.join(BIN, "romp-kernel")], stdout=open(log, "w"), stderr=subprocess.STDOUT, env=env)
    for _ in range(120):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=1)
            return proc, log, seed
        except Exception:
            time.sleep(0.5)
    proc.kill(); proc.wait()
    raise unittest.SkipTest("hermetic kernel %s never served /healthz" % name)


DRIVER = r"""
import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(process.env.EXT_PKG);
const { chromium } = require("playwright");
const cfg = JSON.parse(fs.readFileSync(process.env.CFG, "utf8"));   // {chat, remote:"TESTHOST:<sid>", bare:"<sid>"}
let browser;
try { browser = await chromium.launch(cfg.launch || {}); }
catch (e) { console.error("browser-launch-failed: " + e); process.exit(3); }
const page = await browser.newPage({ viewport: { width: 1000, height: 640 } });
page.on("pageerror", () => {});
await page.addInitScript((rid) => {
  const send = WebSocket.prototype.send;
  window.__sent = [];
  WebSocket.prototype.send = function (d) { try { const m = JSON.parse(d); if (m && m.type) window.__sent.push(m); } catch (e) {} return send.call(this, d); };
  try { localStorage.setItem("romp-vscode-state-chat", JSON.stringify({ activeId: rid })); } catch (e) {}
}, cfg.remote);
// capture the raw frames the RELAY carries (routeWebSocket proxies the socket, so a WebSocket.prototype.send hook
// is blind to what the page sends over it; capture BOTH directions HERE): session frames server->client and
// loadTurns asks client->server, both by the bare sid the wire carries (federation prefixes it page-side)
const frames = [];
const relayAsks = [];
await page.routeWebSocket((u) => /\/ws(\?|$)/.test(u.pathname + (u.search || "")), (ws) => {
  const server = ws.connectToServer();
  ws.onMessage((m) => {
    try { const f = JSON.parse(m); if (f && f.type === "loadTurns" && f.id === cfg.bare) relayAsks.push([f.lo, f.hi]); } catch (e) {}
    server.send(m);
  });
  server.onMessage((m) => {
    try { const f = JSON.parse(m);
      if (f && f.type === "session" && f.id === cfg.bare) frames.push({ proto: f.proto, floor: f.floor, tailLo: f.tailLo, headKnown: f.headKnown, headTotal: f.headTotal, events: Array.isArray(f.events) ? f.events.length : null, headCards: Array.isArray(f.headCards) ? f.headCards.length : null });
    } catch (e) {}
    ws.send(m);
  });
  server.onClose(() => ws.close()); ws.onClose(() => server.close());
});
const out = { died: null };
try {
  await page.goto(cfg.chat);
  await page.waitForSelector("#content .turn[data-uuid]", { timeout: 40000 });
  await page.waitForTimeout(1200);
  out.frame = frames[0] || null; out.framesN = frames.length;
  out.regions = await page.evaluate((sid) => (typeof window.__rompRegions === "function" ? window.__rompRegions(sid) : null), cfg.remote);
  out.boot = await page.evaluate(() => {
    const c = document.getElementById("content");
    const gaps = Array.from(document.querySelectorAll("#content .tx-gap")).map((g) => ({ lo: Number(g.dataset.lo), hi: Number(g.dataset.hi), sid: g.dataset.sid, h: g.offsetHeight }));
    const spacer = document.querySelector("#content .tx-spacer-top");
    return { top: c.scrollTop, sh: c.scrollHeight, ch: c.clientHeight, canScroll: c.scrollHeight - c.clientHeight > 4,
             gaps, spacerTopH: spacer ? spacer.offsetHeight : null, turns: document.querySelectorAll("#content .turn[data-uuid]").length };
  });
  const bootTurns = out.boot.turns;
  // scroll to the very top so virtualization materializes the head-gap element and the observer fires
  await page.evaluate(() => { const c = document.getElementById("content"); c.scrollTop = 0; c.dispatchEvent(new Event("scroll")); });
  await page.waitForTimeout(300);
  await page.evaluate(() => { const c = document.getElementById("content"); c.scrollTop = 0; c.dispatchEvent(new Event("scroll")); });
  // the head page filling (turns growing) is the observable a routed socket does not hide; the relay ask is captured Node-side
  try { await page.waitForFunction((n) => document.querySelectorAll("#content .turn[data-uuid]").length > n, bootTurns, { timeout: 10000 }); } catch (e) {}
  await page.waitForTimeout(1800);
  out.relayAsks = relayAsks.slice();
  out.asked = relayAsks.length > 0;
  out.gapAtTop = await page.evaluate(() => Array.from(document.querySelectorAll("#content .tx-gap")).map((g) => ({ lo: Number(g.dataset.lo), hi: Number(g.dataset.hi), sid: g.dataset.sid, h: g.offsetHeight })));
  out.regionsAfter = await page.evaluate((sid) => (typeof window.__rompRegions === "function" ? window.__rompRegions(sid) : null), cfg.remote);
  out.after = await page.evaluate(() => { const c = document.getElementById("content"); return { canScroll: c.scrollHeight - c.clientHeight > 4, turns: document.querySelectorAll("#content .turn[data-uuid]").length, gaps: document.querySelectorAll("#content .tx-gap").length }; });
  out.earliest = await page.evaluate(() => { const t = document.querySelector("#content .turn[data-uuid]"); return t ? (t.textContent || "").slice(0, 40) : null; });
} catch (e) {
  out.died = String(e).slice(0, 400);
}
process.stdout.write("RESULT:" + JSON.stringify(out) + "\n");
await browser.close();
"""


class FederatedCutFloor(unittest.TestCase):
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
        cls.lab = tempfile.mkdtemp(prefix="fed-cutfloor-")
        b = subprocess.run(["node", "esbuild.js"], cwd=EXT, capture_output=True, text=True)
        if b.returncode != 0:
            raise unittest.SkipTest("esbuild failed: " + (b.stderr or b.stdout)[-200:])
        copy_dist(os.path.join(EXT, "dist"), os.path.join(cls.lab, "dist"))
        cls.rport, cls.rtoken = _free_port(), "testtok-remote-cf"
        cls.hport, cls.htoken = _free_port(), "testtok-hub-cf"
        rp, cls.rlog, cls.seed = _kernel(cls.lab, "testhost", cls.rport, cls.rtoken, seed_session=(SID_R, "api", "proj"))
        cls.procs.append(rp)
        hp, cls.hlog, _ = _kernel(cls.lab, "hub", cls.hport, cls.htoken, seed_session=None)
        cls.procs.append(hp)
        body = json.dumps({"host": HOST, "kernelPort": cls.rport, "busPort": _free_port(), "token": cls.rtoken}).encode()
        req = urllib.request.Request("http://127.0.0.1:%d/checkin?token=%s" % (cls.hport, cls.htoken), data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if not json.loads(resp.read().decode()).get("ok"):
                raise unittest.SkipTest("the hub refused the check-in")
        rows = []
        for _ in range(60):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/tunnels?token=%s" % (cls.hport, cls.htoken), timeout=3) as r2:
                    rows = json.loads(r2.read().decode()).get("tunnels") or []
            except Exception:
                rows = []
            row = next((t for t in rows if t.get("host") == HOST), None)
            if row and row.get("status") == "up" and row.get("hasToken"):
                break
            time.sleep(0.5)
        else:
            raise unittest.SkipTest("the hub never reported the checked-in peer up: %r" % (rows,))

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
                json.dump({"chat": "http://127.0.0.1:%d/chat?skeleton=1&wid=%s&token=%s" % (self.hport, WID, self.htoken),
                           "remote": REMOTE, "bare": SID_R}, f)
            driver = os.path.join(self.lab, "driver.mjs")
            Path(driver).write_text(DRIVER)
            p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=400,
                               env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
            if "browser-launch-failed" in p.stderr:
                raise unittest.SkipTest("no playwright browser")
            line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT:")), None)
            klog = ""
            try:
                klog = open(self.rlog).read()[-1200:]
            except OSError:
                pass
            self.assertIsNotNone(line, "no RESULT (stderr: %s)\nremote kernel:\n%s" % (p.stderr[-1500:], klog))
            type(self)._r = json.loads(line[len("RESULT:"):])
        print("FEDCUTFLOOR seed=%r r=%s" % (getattr(type(self), "seed", None), json.dumps(type(self)._r)), file=sys.stderr)
        return type(self)._r

    def test_the_relay_frame_carries_the_cut_floor(self):
        # the manager's first question: does the RELAY-applied frame carry the floor as the hub receives it
        r = self._result()
        f = r.get("frame")
        self.assertIsNotNone(f, "the hub received a session frame for the remote sid over the relay: %r" % r)
        self.assertEqual(f.get("proto"), 2, "proto 2: %r" % f)
        self.assertGreater(f.get("floor") or 0, 100, "the relay frame carries the cut floor near the tail, not 0: %r seed=%r" % (f, getattr(type(self), "seed", None)))
        self.assertEqual(f.get("tailLo"), f.get("floor"), "tailLo equals the floor: %r" % f)
        self.assertEqual(f.get("headKnown"), False, "headKnown false (older history above the floor): %r" % f)

    def test_the_hub_page_builds_the_head_gap_and_asks_over_the_relay(self):
        # the manager's second question: does the page build the head-gap element above the first rendered turn, and
        # does scrolling to the top ask loadTurns over the relay (does the gap fill, or is there nothing to scroll into)
        r = self._result()
        self.assertIsNotNone(r.get("regions"), "the hub page holds regions from the relay cut-floor frame: boot=%r frame=%r" % (r.get("boot"), r.get("frame")))
        self.assertIn("gap", [x["kind"] for x in r["regions"]], "there is a head gap for the turns below the floor: %r" % r["regions"])
        self.assertTrue(r.get("gapAtTop"), "a .tx-gap element exists above the first rendered turn once scrolled to the top: boot=%r after=%r" % (r.get("boot"), r.get("after")))
        self.assertTrue(r.get("asked"), "scrolling to the top asked loadTurns over the relay: relayAsks=%r died=%r" % (r.get("relayAsks"), r.get("died")))
        after = r.get("regionsAfter") or []
        self.assertTrue(any(x["kind"] == "run" and x["lo"] == 0 for x in after),
                        "the head page filled over the relay (a run at lo 0): regionsAfter=%r relayAsks=%r" % (after, r.get("relayAsks")))


if __name__ == "__main__":
    unittest.main()
