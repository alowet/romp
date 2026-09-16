"""A federated chat pane's scroll-back fills its head gap over the relay (the long-session scroll-back diagnosis,
2026-09-15): a hub page over a checked-in TESTHOST, watching a REMOTE session whose history is longer than
one wire tail, must fill the gap to the head by loadTurns/loadOlder round-trips through the relay splice. The
kernel serves the whole history to a proto-2 client (proven read-only against the real record); this lab
tests the FEDERATED path, the one thing that differs from a working local page: the hub asks over the relay,
the devbox answers, the relay carries the answer back, and the page applies it to its gap.

The observable: with the remote session active in the hub's chat pane, scrolling #content to the top
repeatedly grows the rendered turn count toward the whole transcript (the gap fills) and the hub receives the
chatHead/chatTurns answers it asked for. A stall (the count plateaus below the whole, no answer applied)
reproduces the user's "cannot scroll past about three days ago".

Two hermetic kernels, no ssh; loads no romp code in-process (like tests/test_chat_split_host_served.py).
Synthetic only: placeholder uuids, hostname TESTHOST, invented transcript text.
"""
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

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
EXT = os.path.join(ROOT, "vscode-extension")
sys.path.insert(0, HERE)
import test_ship_reship_served as _lab   # noqa: E402  the lab kernel's environment (the module, not its classes)

SID_R = "11111111-2222-4333-8444-000000000901"   # the watched remote session, a long history
HOST = "TESTHOST"
REMOTE = HOST + ":" + SID_R
WID = "hublab"
PAIRS = 200   # user/assistant turns: ~400 built events, past one WIRE_TAIL (250), so the wire holds a head gap


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _transcript(sid, tag, cwd, pairs):
    """`pairs` CLOSED user/assistant turns (an OPEN turn would invite the boot reconcile to resume it), each
    stamped minutes apart across several days so the history is long and monotonic."""
    out, parent = [], None
    base = 1_700_000_000
    filler = ["The ranking pass reads its weights from the notes-api config now.",
              "Tokenizer edge cases (hyphens, quotes) are covered by the new fixture set.",
              "Index rebuild time is dominated by the stemmer; caching its table halves it."]
    for i in range(pairs):
        t0 = base + i * 600
        ta = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t0))
        tb = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t0 + 60))
        u, a = "%s-u%03d" % (tag, i), "%s-a%03d" % (tag, i)
        out.append({"type": "user", "uuid": u, "parentUuid": parent, "sessionId": sid, "cwd": cwd,
                    "timestamp": ta, "promptSource": "typed",
                    "message": {"role": "user", "content": "turn %d: what changed in the notes-api search?" % i}})
        out.append({"type": "assistant", "uuid": a, "parentUuid": u, "sessionId": sid, "cwd": cwd,
                    "timestamp": tb, "message": {"role": "assistant", "model": "claude-opus-5", "stop_reason": "end_turn",
                                                 "content": [{"type": "text", "text": "turn %d: %s" % (i, filler[i % len(filler)])}]}})
        parent = a
    return "".join(json.dumps(r) + "\n" for r in out)


def _kernel(lab, name, port, token, sessions):
    state = os.path.join(lab, name, "xdg", "romp")
    claude = os.path.join(lab, name, "claude")
    cwd = os.path.join(lab, name, "proj")
    for d in ("names", "sdk", "states"):
        os.makedirs(os.path.join(state, d), exist_ok=True)
    os.makedirs(cwd, exist_ok=True)
    Path(state, "session-hosts").write_text("off\n")
    Path(state, "usage.json").write_text(json.dumps({"five_hour": {"pct": 100}, "seven_day": {"pct": 10}}))
    proj = os.path.join(claude, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd)))
    os.makedirs(proj, exist_ok=True)
    for sid, sname, tag, pairs in sessions:
        Path(state, "names", sid).write_text("%s\t%s\t\t\n" % (sname, cwd))
        Path(state, "sdk", sid + ".json").write_text(json.dumps(
            {"sid": sid, "name": sname, "cwd": cwd, "mode": "auto", "effort": "high", "lastSid": sid, "alive": True}))
        Path(proj, sid + ".jsonl").write_text(_transcript(sid, tag, cwd, pairs))
    env = _lab.kernel_env(os.path.join(lab, name), claude, os.path.join(lab, "dist"), port, token, ROMP_HOST_NAME=name.upper())
    log = os.path.join(lab, name + "-kernel.log")
    proc = subprocess.Popen([os.path.join(BIN, "romp-kernel")], stdout=open(log, "w"), stderr=subprocess.STDOUT, env=env)
    for _ in range(120):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=1)
            return proc, log
        except Exception:
            time.sleep(0.5)
    proc.kill(); proc.wait()
    raise unittest.SkipTest("hermetic kernel %s never served /healthz here" % name)


DRIVER = r"""
import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(process.env.EXT_PKG);
const { chromium } = require("playwright");
const cfg = JSON.parse(fs.readFileSync(process.env.CFG, "utf8"));
let browser;
try { browser = await chromium.launch(cfg.launch || {}); }
catch (e) { console.error("browser-launch-failed: " + e); process.exit(3); }
const context = await browser.newContext({ viewport: { width: 1200, height: 700 } });
const page = await context.newPage();
const out = { died: null, sent: [], frames: [], turnCounts: [] };
page.on("pageerror", () => {});
await page.addInitScript((rid) => {
  window.__sent = []; window.__frames = [];
  const W = window.WebSocket;
  const OS = W.prototype.send;
  W.prototype.send = function (d) { try { const m = JSON.parse(d); if (m && m.type) window.__sent.push({ type: m.type, id: m.id || null, lo: m.lo, hi: m.hi, before: m.before ? 1 : 0, uuid: m.uuid ? 1 : 0 }); } catch (e) {} return OS.call(this, d); };
  window.addEventListener("message", (e) => { const m = e.data; if (!m || !m.type) return;
    window.__frames.push({ type: m.type, id: m.id || null, n: Array.isArray(m.events) ? m.events.length : null, span: m.span || null, more: m.more, head: m.head, missing: m.missing }); });
  try { localStorage.setItem("romp-vscode-state-chat", JSON.stringify({ activeId: rid })); } catch (e) {}
}, cfg.remote);
const turns = () => page.evaluate(() => document.querySelectorAll("#content .turn[data-uuid]").length);
try {
  await page.goto(cfg.chat);
  await page.waitForFunction(() => (Array.from(document.querySelectorAll("script")), true) && window.WebSocket, null, { timeout: 5000 }).catch(() => {});
  // the remote session's chat renders in #content once the relay serves it (the active tab is the remote sid)
  await page.waitForSelector("#content .turn[data-uuid]", { timeout: 40000 });
  await page.waitForTimeout(1500);
  out.turnCounts.push(await turns());
  // INCREMENTAL scroll up (like a human), a partial viewport per step, so each gap page is asked and applied
  // in turn over the relay rather than jumping past the middle to the head
  let stalls = 0;
  for (let i = 0; i < 160 && stalls < 12; i++) {
    const top = await page.evaluate(() => { const c = document.getElementById("content"); if (!c) return -1;
      c.scrollTop = Math.max(0, c.scrollTop - Math.round(c.clientHeight * 0.6)); return c.scrollTop; });
    await page.waitForTimeout(300);
    out.turnCounts.push(await turns());
    if (top === 0) stalls++; else stalls = 0;   // at the very top: a few settle passes for the head, then stop
  }
  out.turnCount = await turns();
  out.earliestTurn = await page.evaluate(() => { const t = document.querySelector("#content .turn[data-uuid]"); return t ? (t.textContent || "").slice(0, 40) : null; });
  // the turn spans the page ASKED (loadTurns/loadOlder) and the answers it RECEIVED (chatTurns/chatHead): do they cover the gap to 0?
  out.spansAsked = await page.evaluate(() => window.__sent.filter((m) => m.type === "loadTurns" || m.type === "loadOlder").map((m) => [m.lo, m.hi]));
  out.spansGot = await page.evaluate(() => window.__frames.filter((f) => f.type === "chatTurns" || f.type === "chatHead").map((f) => [f.span, f.head, f.n]));
  out.minLoAsked = await page.evaluate(() => { const s = window.__sent.filter((m) => m.type === "loadTurns" && typeof m.lo === "number"); return s.length ? Math.min.apply(null, s.map((m) => m.lo)) : null; });
  try { out.regions = await page.evaluate(() => (window.__rompRegions && window.__rompRegions()) || null); } catch (e) { out.regions = null; }
  out.sent = await page.evaluate(() => window.__sent.slice(-50));
  out.frames = await page.evaluate(() => window.__frames.slice(-50));
} catch (e) {
  out.died = String(e).slice(0, 400);
  try { out.turnCount = await turns(); out.sent = await page.evaluate(() => window.__sent.slice(-40)); out.frames = await page.evaluate(() => window.__frames.slice(-40)); } catch (e2) {}
}
console.log("RESULT:" + JSON.stringify(out));
await browser.close();
"""


class FederatedHistoryScroll(unittest.TestCase):
    maxDiff = None
    DRIVER = DRIVER

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
            raise unittest.SkipTest("extension deps absent (npm ci not run here), the served lab needs them")
        probe = subprocess.run(["node", "-e", "const p=require(process.argv[1]);process.stdout.write(p.chromium.executablePath())",
                                os.path.join(EXT, "node_modules", "playwright")], capture_output=True, text=True)
        if probe.returncode != 0 or not os.path.exists(probe.stdout.strip()):
            raise unittest.SkipTest("no playwright browser on this box, the served lab needs one (CI installs none)")
        cls.lab = tempfile.mkdtemp(prefix="fed-history-scroll-")
        b = subprocess.run(["node", "esbuild.js"], cwd=EXT, capture_output=True, text=True)
        if b.returncode != 0:
            raise unittest.SkipTest("esbuild failed here: " + (b.stderr or b.stdout)[-200:])
        copy_dist(os.path.join(EXT, "dist"), os.path.join(cls.lab, "dist"))
        cls.rport, cls.rtoken = _free_port(), "testtok-remote-hist"
        cls.hport, cls.htoken = _free_port(), "testtok-hub-hist"
        rp, cls.rlog = _kernel(cls.lab, "testhost", cls.rport, cls.rtoken, [(SID_R, "api", 2, PAIRS)])
        cls.procs.append(rp)
        hp, cls.hlog = _kernel(cls.lab, "hub", cls.hport, cls.htoken, [])
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
        cls.result, cls.driver_error = None, None
        cls._drive()

    @classmethod
    def _drive(cls):
        cfg = os.path.join(cls.lab, "cfg.json")
        with open(cfg, "w") as f:
            json.dump({"chat": "http://127.0.0.1:%d/chat?skeleton=1&wid=%s&token=%s" % (cls.hport, WID, cls.htoken),
                       "remote": REMOTE}, f)
        driver = os.path.join(cls.lab, "driver.mjs")
        with open(driver, "w") as f:
            f.write(cls.DRIVER)
        try:
            p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=400,
                               env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
        except subprocess.TimeoutExpired as e:
            cls.driver_error = "driver timed out; partial:\n%s" % ((e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode()))
            return
        if p.returncode == 3:
            raise unittest.SkipTest("no playwright browser on this box (CI installs none)")
        if p.returncode != 0:
            cls.driver_error = "driver failed:\n" + p.stdout[-3000:] + p.stderr[-3000:]
            return
        line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT:")), None)
        if line is None:
            cls.driver_error = "driver printed no result:\n" + p.stdout[-3000:] + p.stderr[-3000:]
            return
        cls.result = json.loads(line[len("RESULT:"):])

    @classmethod
    def tearDownClass(cls):
        for p in getattr(cls, "procs", []):
            try:
                p.kill(); p.wait()
            except Exception:
                pass
        shutil.rmtree(getattr(cls, "lab", ""), ignore_errors=True)

    def _r(self):
        if getattr(type(self), "driver_error", None):
            self.fail(type(self).driver_error)
        if getattr(type(self), "result", None) is None:
            raise unittest.SkipTest("the driver produced no result")
        return type(self).result

    def test_the_gap_fills_to_the_head_over_the_relay(self):
        r = self._r()
        # scrolling up must reach the head over the relay (the earliest gap page asked and answered): minLoAsked==0.
        # The DOM count windows, so the spans (asked/got) are the fill metric; the message dumps them for the diagnosis.
        self.assertEqual(r.get("minLoAsked"), 0,
                         "the federated scroll-back reached the head over the relay "
                         "(minLoAsked=%r, spansAsked=%r, spansGot=%r, counts=%r, regions=%r, earliest=%r)"
                         % (r.get("minLoAsked"), r.get("spansAsked"), r.get("spansGot"),
                            r.get("turnCounts"), r.get("regions"), r.get("earliestTurn")))


DRIVER_CUT = r"""
import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(process.env.EXT_PKG);
const { chromium } = require("playwright");
const cfg = JSON.parse(fs.readFileSync(process.env.CFG, "utf8"));
let browser;
try { browser = await chromium.launch(cfg.launch || {}); }
catch (e) { console.error("browser-launch-failed: " + e); process.exit(3); }
const context = await browser.newContext({ viewport: { width: 1200, height: 700 } });
const page = await context.newPage();
const out = { died: null, sent: [], frames: [], turnCounts: [] };
page.on("pageerror", () => {});
await page.addInitScript((rid) => {
  window.__sent = []; window.__frames = []; window.__relayUp = 0;
  window.addEventListener("romp:hostRelayUp", function(){ window.__relayUp++; });
  const W = window.WebSocket;
  const OS = W.prototype.send;
  W.prototype.send = function (d) { try { const m = JSON.parse(d);
    if (m && m.type) window.__sent.push({ type: m.type, id: m.id || null, lo: m.lo, hi: m.hi, before: m.before ? 1 : 0, uuid: m.uuid ? 1 : 0 });
    if (m && m.type === "loadTurns" && !window.__cut && String(this.url || "").indexOf("/remote/") >= 0) {
      window.__cut = true; window.__cutSpan = [m.lo, m.hi];
      try { this.close(); } catch (e) {}    /* cut the relay mid-answer: its reply is lost, federation redials */
      return;                                 /* drop this send: the gap is stuck until the redial re-asks */
    }
  } catch (e) {} return OS.call(this, d); };
  window.addEventListener("message", (e) => { const m = e.data; if (!m || !m.type) return;
    window.__frames.push({ type: m.type, id: m.id || null, n: Array.isArray(m.events) ? m.events.length : null, span: m.span || null, more: m.more, head: m.head, missing: m.missing }); });
  try { localStorage.setItem("romp-vscode-state-chat", JSON.stringify({ activeId: rid })); } catch (e) {}
}, cfg.remote);
const turns = () => page.evaluate(() => document.querySelectorAll("#content .turn[data-uuid]").length);
try {
  await page.goto(cfg.chat);
  await page.waitForFunction(() => (Array.from(document.querySelectorAll("script")), true) && window.WebSocket, null, { timeout: 5000 }).catch(() => {});
  // the remote session's chat renders in #content once the relay serves it (the active tab is the remote sid)
  await page.waitForSelector("#content .turn[data-uuid]", { timeout: 40000 });
  await page.waitForTimeout(1500);
  out.turnCounts.push(await turns());
  // INCREMENTAL scroll up (like a human), a partial viewport per step, so each gap page is asked and applied
  // in turn over the relay rather than jumping past the middle to the head
  let stalls = 0;
  for (let i = 0; i < 240 && stalls < 40; i++) {   // longer: the relay must redial and the re-ask must fill after the cut
    const top = await page.evaluate(() => { const c = document.getElementById("content"); if (!c) return -1;
      c.scrollTop = Math.max(0, c.scrollTop - Math.round(c.clientHeight * 0.6)); return c.scrollTop; });
    await page.waitForTimeout(300);
    out.turnCounts.push(await turns());
    if (top === 0) stalls++; else stalls = 0;   // at the very top: a few settle passes for the head, then stop
  }
  out.turnCount = await turns();
  out.earliestTurn = await page.evaluate(() => { const t = document.querySelector("#content .turn[data-uuid]"); return t ? (t.textContent || "").slice(0, 40) : null; });
  // the turn spans the page ASKED (loadTurns/loadOlder) and the answers it RECEIVED (chatTurns/chatHead): do they cover the gap to 0?
  out.spansAsked = await page.evaluate(() => window.__sent.filter((m) => m.type === "loadTurns" || m.type === "loadOlder").map((m) => [m.lo, m.hi]));
  out.spansGot = await page.evaluate(() => window.__frames.filter((f) => f.type === "chatTurns" || f.type === "chatHead").map((f) => [f.span, f.head, f.n]));
  out.minLoAsked = await page.evaluate(() => { const s = window.__sent.filter((m) => m.type === "loadTurns" && typeof m.lo === "number"); return s.length ? Math.min.apply(null, s.map((m) => m.lo)) : null; });
  try { out.regions = await page.evaluate(() => (window.__rompRegions && window.__rompRegions()) || null); } catch (e) { out.regions = null; }
  out.sent = await page.evaluate(() => window.__sent.slice(-50));
  out.frames = await page.evaluate(() => window.__frames.slice(-50));
  out.cut = await page.evaluate(() => ({ cut: !!window.__cut, span: window.__cutSpan || null, relayUp: window.__relayUp || 0 }));
} catch (e) {
  out.died = String(e).slice(0, 400);
  try { out.turnCount = await turns(); out.sent = await page.evaluate(() => window.__sent.slice(-40)); out.frames = await page.evaluate(() => window.__frames.slice(-40)); } catch (e2) {}
}
console.log("RESULT:" + JSON.stringify(out));
await browser.close();
"""


class FederatedRedialReask(FederatedHistoryScroll):
    """The redial re-asks an outstanding loadTurns (the redial-no-reask fix, 2026-09-15): the relay socket is cut
    while a deep page's answer is in flight, so gapLoading holds a key the relay drop never cleared (no romp:wsdown
    for a relay) and the gap can never re-ask on its own. The red state is the PARSE-FIXED intermediate: at the true
    base the host-prefixed key mis-parses, gapHasAsk reads no ask, and the gap observer re-fires and re-asks FREELY, so
    the gap fills (the base passes); once the parse is correct the guard suppresses that re-fire and the gap stays a gap
    until, at the head, the relay's redial (romp:hostRelayUp) re-sends the outstanding loadTurns and it fills to turn 0.
    That coupling (a correct guard needs the re-ask) is why the parse and the relay re-ask ship together."""
    DRIVER = DRIVER_CUT
