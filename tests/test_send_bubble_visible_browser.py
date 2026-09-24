#!/usr/bin/env python3
"""A composer send must show its bubble, and keep showing it, until its landing replaces it (the user 2026-09-22:
pressing Enter often produced no bubble in the transcript on the deployed build; a reload brought the message back).

The lab drives the real /chat page against a hermetic kernel whose one session is MID-TURN (the transcript ends inside
a tool call), so a real send reaches the kernel and is queued there, and measures after every checkpoint whether the
SENT TEXT is on the page in a visible element. Variants, each looped: a plain send; a rapid double send; a send while
scrolled up; a send right after the socket dropped and the page redialled with the skeleton diet; a send pressed DURING
the redial; and a reload after a send. The kernel's copy, the page's own bubble and the landed atom are all acceptable
carriers of the text; what is not acceptable is a checkpoint at which no visible element carries it.

Then the frame the live rows blamed, injected through the pane's own message channel in the kernel's frame shape (the
T262i lab's idiom, a real frame as the base): a frame that LANDS the send (a user row carrying the press's id), then a
frame built from an OLDER reading (its watermark behind: fewer transcript bytes, a newer live tail, the echo still in it)
that lacks the row — the page must keep the landed row and file `frame-stale` — and then the same older list with NO
watermark (an older kernel): the row goes, as it did before the guard, and the page files `frame-drops-landed` so the
loss is never silent. The landed frame is bumped ahead of the send's chatTail delta, the last frame the page received of
EITHER type (that delta advances the page's floor as much as a session frame does, which the session-only base did not
see), so the injection is ahead of the page's real floor on the transcript row; a bounded poll confirms the landed row
applied; and a later frame that removes it is a loss the guard files, not a refusal. SYNTHETIC fixtures only; skips loudly without the
extension deps or a Playwright browser.
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
from datetime import datetime, timezone
from pathlib import Path

from tests.dist_copy import copy_dist

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
EXT = os.path.join(ROOT, "vscode-extension")
sys.path.insert(0, HERE)
import test_ship_reship_served as _lab   # noqa: E402  the lab kernel's environment (the module, not its classes)

SID = "aaaaaaaa-1111-2222-3333-444444444444"
ROUNDS = int(os.environ.get("SEND_BUBBLE_ROUNDS", "1"))   # one round of every variant fits CI's per-test cap; more rounds by hand


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _seed_records(t0):
    """A mid-turn session: two answered asks, then a tool call whose result is still out (a send into it is queued by the kernel)."""
    return [
        {"type": "user", "timestamp": iso(t0), "uuid": "u1", "parentUuid": None, "promptSource": "sdk", "sessionId": SID,
         "message": {"role": "user", "content": "tighten the notes-api search"}},
        {"type": "assistant", "timestamp": iso(t0 + 10), "uuid": "a1", "parentUuid": "u1", "sessionId": SID,
         "message": {"role": "assistant", "model": "claude-fable-5-1", "stop_reason": "end_turn",
                     "content": [{"type": "text", "text": "\n\n".join("Paragraph %d of the reply." % i for i in range(14))}]}},
        {"type": "user", "timestamp": iso(t0 + 39), "uuid": "u2", "parentUuid": "a1", "promptSource": "sdk", "sessionId": SID,
         "message": {"role": "user", "content": "drop the unused import"}},
        {"type": "assistant", "timestamp": iso(t0 + 41), "uuid": "a2", "parentUuid": "u2", "sessionId": SID,
         "message": {"role": "assistant", "model": "claude-fable-5-1", "stop_reason": "tool_use",
                     "content": [{"type": "tool_use", "id": "tu_a2_0", "name": "Bash", "input": {"command": "uv run pytest -q"}}]}},
        {"type": "user", "timestamp": iso(t0 + 50), "uuid": "tr1", "parentUuid": "a2", "sessionId": SID,
         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu_a2_0", "content": "3 passed"}]}},
        {"type": "assistant", "timestamp": iso(t0 + 52), "uuid": "a3", "parentUuid": "tr1", "sessionId": SID,
         "message": {"role": "assistant", "model": "claude-fable-5-1", "stop_reason": "tool_use",
                     "content": [{"type": "tool_use", "id": "tu_a3_0", "name": "Bash", "input": {"command": "uv run pytest -q tests/test_search.py"}}]}},
    ]


def _kernel(lab, name, port, token, records=None, host_name=None):
    """Boot one hermetic kernel under `lab/name`: its own state root and, with `records`, the one session and its transcript
    (the T328 remote lab's helper). Returns (proc, log, transcript path or None)."""
    state = os.path.join(lab, name, "xdg", "romp")
    claude = os.path.join(lab, name, "claude")
    cwd = os.path.join(lab, name, "proj")
    for d in ("names", "sdk", "states"):
        os.makedirs(os.path.join(state, d), exist_ok=True)
    Path(state, "session-hosts").write_text("off\n")   # a test that mints its own state root pins the hosts off (CLAUDE.md)
    os.makedirs(cwd, exist_ok=True)
    Path(state, "usage.json").write_text(json.dumps({"five_hour": {"pct": 10}, "seven_day": {"pct": 10}}))
    transcript = None
    if records is not None:
        Path(state, "names", SID).write_text("web\t%s\t\t\n" % cwd)
        Path(state, "sdk", SID + ".json").write_text(json.dumps(
            {"sid": SID, "name": "web", "cwd": cwd, "mode": "auto", "effort": "high",
             "lastSid": SID, "alive": True, "model": "claude-fable-5-1", "liveModel": "Fable 5.1"}))
        proj = os.path.join(claude, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd)))
        os.makedirs(proj, exist_ok=True)
        transcript = os.path.join(proj, SID + ".jsonl")
        Path(transcript).write_text("".join(json.dumps(r) + "\n" for r in records))
    seams = {"ROMP_HOST_NAME": host_name} if host_name else {}
    env = _lab.kernel_env(os.path.join(lab, name), claude, os.path.join(lab, "dist"), port, token, **seams)
    log = os.path.join(lab, name + "-kernel.log")
    proc = subprocess.Popen([os.path.join(BIN, "romp-kernel")], stdout=open(log, "w"), stderr=subprocess.STDOUT, env=env)
    import urllib.request
    for _ in range(120):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=1)
            return proc, log, transcript
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
try { browser = await chromium.launch(); }
catch (e) { console.error("browser-launch-failed: " + e); process.exit(3); }
const page = await browser.newPage({ viewport: { width: 1000, height: 600 } });
page.on("console", (m) => { if (m.type() === "error") fs.appendFileSync(cfg.consoleLog, m.text() + "\n"); });
page.on("pageerror", (e) => fs.appendFileSync(cfg.consoleLog, "pageerror: " + e + "\n"));
// the instrumentation is an INIT script: it runs before the bundle, so the page's first session frame and the shim's first socket are
// seen too (a listener installed after the load missed the first frame, and a reload starts the page over)
await page.addInitScript(() => {
  window.__frames = 0; window.__sockets = []; window.__sent = []; window.__diag = []; window.__last = null; window.__lastAny = null; window.__wmLog = []; window.__types = [];
  window.addEventListener("message", (e) => { const m = e.data; if (m && typeof m.type === "string") window.__types.push(m.type);
    if (m && (m.type === "session" || m.type === "update" || m.type === "chatTail") && !m.__reposted) { window.__frames++;   // __reposted marks the driver's OWN posts (the injected frames and the red-first replay), so the listener never mistakes them for kernel frames
      if (m.type === "session" && Array.isArray(m.events)) window.__last = m;
      // the page's watermark floor advances on chatTail deltas too (render.ts sets s.wm on every applied chatTail), which
      // __last (session-only) does not see, so track the last frame of EITHER type that carried a watermark, and log every
      // transcript frame's type, watermark and count (the count at capture makes frames-since derivable)
      if (m.wm && typeof m.wm === "object") window.__lastAny = m;
      if (m.type === "chatTail" && m.wm && typeof m.wm === "object") window.__lastTail = m;   // the SEND's last kernel chatTail. PR 2077 (kernel.py _tail_noop) stopped the kernel sending the no-change EMPTY tail after a delta, so current main sends ONE delta with events everywhere: the red-first replays THIS, not a trailing empty tail that no longer exists
      window.__wmLog.push({ type: m.type, wm: (m.wm && typeof m.wm === "object") ? m.wm : null, ev: Array.isArray(m.events) ? m.events.length : null, n: window.__frames }); } });
  // the page's frame-* diag rows are read where the bundle FILES them (chatDiagRow's postMessage through the shim's
  // acquireVsCodeApi), not where a socket sends them (round eleven, 2026-09-24): the shim queues a clientDiag row while its
  // own socket is not open, and on a starved runner the local socket's redial after the drop below lagged the whole rest
  // of the run while the remote session's frames rode the relay socket, so the refusal happened and its row was never
  // sent; the hook on send read "none seen" of a refusal that was filed (reproduced by a CAPPED_CPU=50% run of this
  // class; a routeWebSocket road that closes every redial cannot stand in for it, the mock opens each redial and the
  // shim flushes its queue on the open). The shim defines acquireVsCodeApi after this init script runs, so a setter trap
  // wraps it the moment it is defined.
  const wrapApi = (fn) => function () { const o = fn(); const orig = o.postMessage; o.postMessage = function (m) {
    try { if (m && m.type === "clientDiag" && m.surface === "chat" && /^frame-/.test(m.what || "")) window.__diag.push({ what: m.what, data: m.data }); } catch (e) {}
    return orig.call(this, m); }; return o; };
  let api;
  Object.defineProperty(window, "acquireVsCodeApi", { configurable: true, get() { return api; }, set(fn) { api = typeof fn === "function" ? wrapApi(fn) : fn; } });
  const origSend = WebSocket.prototype.send;
  WebSocket.prototype.send = function (d) {
    try { const m = JSON.parse(d); if (m && m.type === "sendMessage") window.__sent.push({ text: m.text, qid: m.qid, t: Date.now() }); } catch (e) {}
    if (!window.__sockets.includes(this)) window.__sockets.push(this);
    return origSend.call(this, d);
  };
});
const armPage = async () => {
  await page.goto(cfg.chat);
  await page.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
  if (cfg.remote) {   // the remote host's tab appears once the hub reports the peer up and the relay socket is open (the T328 lab's idiom)
    const remoteTab = page.locator("#tabs .tab", { hasText: cfg.remote }).first();
    await remoteTab.waitFor({ timeout: 45000 });
    await remoteTab.click();
  }
  await page.waitForSelector(".turn.turn-user", { timeout: 20000 });
  await page.waitForTimeout(600);
};
const on = (v) => !cfg.variants || cfg.variants.includes(v);
await armPage();
const painted = () => page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 0)))));
// the measure: is the text on the page in a visible element? (our bubble, the kernel's copy, or the landed atom)
const measure = (text) => page.evaluate((t) => {
  const content = document.getElementById("content");
  const turns = Array.from(document.querySelectorAll("#content .turn"));
  const carriers = turns.filter((el) => (el.textContent || "").includes(t));
  const visible = carriers.filter((el) => el.getClientRects().length > 0 && getComputedStyle(el).display !== "none" && getComputedStyle(el).visibility !== "hidden");
  const tail = turns.slice(-4).map((el) => el.className);
  return { visible: visible.length, carriers: carriers.map((el) => el.className), tail, frames: window.__frames,
           sh: content ? content.scrollHeight : 0, st: content ? content.scrollTop : 0, ch: content ? content.clientHeight : 0,
           skeleton: !!document.querySelector(".tab.skeleton, [data-skeleton]"), composer: (document.getElementById("composer-input") || {}).value || "" };
}, text);
// the frame counter is SNAPSHOTTED before every action (snap) and the wait reads that snapshot: a frame that lands between the action and
// the wait's own read counted as none before, and every wait ran to its cap (16 of 16, at 3 to 5 s each: the lab's whole slowness)
let waitTimeouts = 0, waits = 0, lastSeen = 0;
const snap = async () => { lastSeen = await page.evaluate(() => window.__frames); };
const waitFrames = async (n, ms) => { waits++; try { await page.waitForFunction(({ b, n }) => window.__frames >= b + n, { b: lastSeen, n }, { timeout: ms }); } catch (e) { waitTimeouts++; } await snap(); };   // ONE argument: Playwright's waitForFunction(fn, arg, options)
const send = async (text) => { await snap(); await page.fill("#composer-input", text); await page.press("#composer-input", "Enter"); };
let stepN = 0; let parent = cfg.parent; const t0 = cfg.t0;
const iso = (x) => new Date(x * 1000).toISOString().replace(/\.\d{3}Z$/, ".000Z");
const step = () => {
  const i = stepN++;
  const t = t0 + 200 + i;
  let r;
  if (i % 2 === 0) { r = { type: "assistant", timestamp: iso(t), uuid: "s" + i, parentUuid: parent, sessionId: cfg.sid,
      message: { role: "assistant", model: "claude-fable-5-1", stop_reason: "tool_use", content: [{ type: "tool_use", id: "tu_s" + i, name: "Bash", input: { command: "true # step " + i } }] } }; }
  else { r = { type: "user", timestamp: iso(t), uuid: "s" + i, parentUuid: parent, sessionId: cfg.sid,
      message: { role: "user", content: [{ type: "tool_result", tool_use_id: "tu_s" + (i - 1), content: "ok" }] } }; }
  parent = "s" + i;
  fs.appendFileSync(cfg.transcript, JSON.stringify(r) + "\n");
};
const checks = [];   // every checkpoint: { variant, round, at, t (ms since the arm), ...measure }
const T0 = Date.now();
const check = async (variant, round, at, text) => { await painted(); const m = await measure(text); checks.push({ variant, round, at, text, t: Date.now() - T0, ...m }); return m; };
const settle = async (variant, round, text, pushes) => {
  for (let k = 0; k < pushes; k++) { await snap(); step(); await waitFrames(1, 3000); await check(variant, round, "push" + k, text); }
};
let n = 0;
const fresh = (tag) => `please ${tag} the notes-api search index, round ${++n}`;
// A. plain send into the mid-turn session
for (let r = 0; on("A") && r < cfg.rounds; r++) {
  const text = fresh("rebuild");
  await send(text);
  await check("plain", r, "press", text);
  await page.waitForTimeout(300); await check("plain", r, "300ms", text);
  await waitFrames(1, 3000); await check("plain", r, "frame", text);
  await settle("plain", r, text, 3);
}
// B. rapid double send
for (let r = 0; on("B") && r < cfg.rounds; r++) {
  const a = fresh("tighten"), b = fresh("document");
  await page.fill("#composer-input", a); await page.press("#composer-input", "Enter");
  await page.fill("#composer-input", b); await page.press("#composer-input", "Enter");
  await check("double-a", r, "press", a); await check("double-b", r, "press", b);
  await waitFrames(1, 3000); await check("double-a", r, "frame", a); await check("double-b", r, "frame", b);
  await settle("double-b", r, b, 2);
}
// C. send while scrolled up
for (let r = 0; on("C") && r < cfg.rounds; r++) {
  const text = fresh("profile");
  await page.evaluate(() => { const c = document.getElementById("content"); c.scrollTop = Math.max(0, c.scrollHeight - c.clientHeight - 900); });
  await page.waitForTimeout(200);
  await send(text);
  await check("scrolled-up", r, "press", text);
  await waitFrames(1, 3000); await check("scrolled-up", r, "frame", text);
  await page.evaluate(() => { const c = document.getElementById("content"); c.scrollTop = c.scrollHeight; });
  await settle("scrolled-up", r, text, 2);
}
// D. a redial: close every socket the page holds; the shim redials with the skeleton diet; send once the frame lands
for (let r = 0; on("D") && r < cfg.rounds; r++) {
  const text = fresh("index");
  await snap();
  await page.evaluate(() => { for (const ws of window.__sockets) { try { ws.close(); } catch (e) {} } });
  await waitFrames(1, 8000);
  await page.waitForTimeout(400);
  await send(text);
  await check("after-redial", r, "press", text);
  await waitFrames(1, 3000); await check("after-redial", r, "frame", text);
  await settle("after-redial", r, text, 2);
}
// E. a send pressed DURING the redial (the socket just closed, no frame yet)
for (let r = 0; on("E") && r < cfg.rounds; r++) {
  const text = fresh("compact");
  await snap();
  await page.evaluate(() => { for (const ws of window.__sockets) { try { ws.close(); } catch (e) {} } });
  await send(text);
  await check("mid-redial", r, "press", text);
  await waitFrames(1, 8000); await check("mid-redial", r, "frame", text);
  await page.waitForTimeout(800); await check("mid-redial", r, "later", text);
  await settle("mid-redial", r, text, 2);
}
// F. a reload after a send: the kernel's copy carries the text
if (on("F")) {
  const text = fresh("verify");
  await send(text);
  await check("reload", 0, "press", text);
  await waitFrames(1, 3000);
  await armPage();
  await check("reload", 0, "reloaded", text);
}
// G. the frame the live rows blamed, through the pane's own message channel (the kernel's real frame as the base)
const injected = {};
if (on("G")) {
  // the base: a real whole frame from THIS kernel. The page's first frame lands before the driver's listener exists, so a redial
  // (the sockets closed: the shim redials with the skeleton diet and the kernel serves the active tab whole) produces one it can hold
  await page.evaluate(() => { window.__last = null; for (const ws of window.__sockets) { try { ws.close(); } catch (e) {} } });
  try { await page.waitForFunction(() => !!window.__last, null, { timeout: 10000 }); } catch (e) {}
  await page.waitForTimeout(400);
  const text = fresh("land");
  await send(text);
  if (cfg.pauseBeforeCapture) await page.waitForTimeout(300);   // the pause runs by DEFAULT (300 ms on a ~19 s run) so this red-first runs unattended in CI: a chatTail landing in this window is counted; nAtSend from a fresh read AFTER the Enter would exclude it and the wait would time out, but nAtSend from lastSeen (the send's pre-Enter snapshot) is immune. SB_PAUSE_BEFORE_CAPTURE=0 opts OUT for a by-hand natural-timing run.
  const nAtSend = lastSeen;   // the snapshot the send took at its start (snap() before the Enter), NOT a fresh read after it: a chatTail arriving between the Enter and a fresh read would be counted and then excluded from the wait at fr.n > nAtSend (a latent flake, the reviewer 2026-09-23). waitFrames below re-snaps lastSeen, so capture it here.
  await waitFrames(1, 4000); await painted();
  // variant-G race (the reviewer, 2026-09-23): the listener's window.__last tracks SESSION frames only, but the page's
  // watermark floor advances on the send's chatTail DELTA too (render.ts sets s.wm on every applied chatTail), which
  // __last (session-only) does not see. Current main sends ONE delta carrying the send's events (PR 2077 stopped the
  // no-change empty tail that used to follow it). Wait for that delta (any chatTail past the send with a live above the
  // base session's) before capturing, and derive the injected watermark from the last frame of EITHER type, so the
  // injection is ahead of the page's real floor, not just the redial full's transcript row. Dropping the ev===0 filter is
  // safe: were a kernel to send a later empty tail with the same watermark, the either-type floor refuses it as stale.
  const baseLive = await page.evaluate(() => (window.__last && window.__last.wm && typeof window.__last.wm.live === "number") ? window.__last.wm.live : 0);
  injected.trailWait = await page.waitForFunction(({ bl, n0 }) => window.__wmLog.some((fr) => fr.n > n0 && fr.type === "chatTail" && fr.wm && typeof fr.wm.live === "number" && fr.wm.live > bl), { bl: baseLive, n0: nAtSend }, { timeout: 8000 }).then(() => "seen").catch((e) => { if (!e || e.name !== "TimeoutError") throw e; return "timeout"; });
  await painted();
  const base = await page.evaluate(() => window.__last);
  const qid = await page.evaluate(() => (window.__sent[window.__sent.length - 1] || {}).qid);
  injected.baseWm = base && base.wm ? base.wm : null;
  injected.floorWm = await page.evaluate(() => (window.__lastAny && window.__lastAny.wm) ? window.__lastAny.wm : null);
  injected.baseOk = !!(base && base.wm && Array.isArray(base.wm.tx) && base.wm.leaf && injected.floorWm && Array.isArray(injected.floorWm.tx));   // low 3: bump() maps floor.tx too, so the floor needs a keyed parse (a kernel wm whose parse could not be keyed carries tx null)
  injected.seen = await page.evaluate(() => {
    const lite = (wm) => wm ? { tx: wm.tx, live: wm.live } : null;   // low 2: drop the ~150-char leaf (it repeats across base, lastAny and every wmLog row; recorded once by the Python print)
    return { last: window.__last ? { type: window.__last.type, keys: Object.keys(window.__last).sort(), wm: lite(window.__last.wm) } : null,
             lastAny: window.__lastAny ? lite(window.__lastAny.wm) : null, sockets: window.__sockets.length, types: window.__types.slice(-30),
             wmLog: window.__wmLog.slice(-8).map((fr) => ({ type: fr.type, ev: fr.ev, n: fr.n, wm: lite(fr.wm) })) };
  });
  if (injected.baseOk) {
    const landedRow = { kind: "user", uuid: "11111111-2222-3333-4444-aaaaaaaaaaaa", md: text, qid, human: true, ts: new Date().toISOString().replace(/\.\d{3}Z$/, ".000Z") };
    const olderRow = { kind: "user", uuid: qid, md: text, ts: landedRow.ts };
    // Build and inject each frame in ONE page.evaluate. The EVENTS base is the last full session frame (window.__injBase;
    // a chatTail delta has no full list to append to). The WATERMARK floor is the last frame the page received of EITHER
    // type (window.__injFloor from window.__lastAny), snapshotted on the landed injection so the stale and bare frames
    // reuse it and stay BEHIND the landed frame. So the landed frame is ahead of the send's chatTail delta (the last frame the page received of either type),
    // on the transcript row; a bounded poll below confirms the landed row applied; and a later frame that removes it is a
    // loss the guard files, not a refusal (in G no transcript write happens, so the injected frame is never refused).
    const injectFrame = (which, row) => page.evaluate(({ which, row }) => {
      const strip = (evs) => evs.filter((e) => !(e && e.kind === "queued") && !(e && e.kind === "user" && typeof e.uuid === "string" && e.uuid.startsWith("echo:")));
      const bump = (wm, dSize, dLive) => ({ leaf: wm.leaf, tx: wm.tx.map((r, i) => (i === 0 ? [r[0] + (dSize > 0 ? 1 : 0), r[1] + dSize] : r)), live: (typeof wm.live === "number" ? wm.live : 0) + dLive });
      if (which === "newer") { window.__injBase = window.__last; window.__injFloor = (window.__lastAny && window.__lastAny.wm) ? window.__lastAny.wm : window.__last.wm; }
      const b = window.__injBase, floor = window.__injFloor;
      const f = { ...b, events: [...strip(b.events), row], wm: bump(floor, which === "newer" ? 400 : 0, which === "newer" ? 1 : 3), __reposted: true };
      if (which === "bare") delete f.wm;
      window.postMessage(f, "*");
      return { baseWm: b.wm || null, floorWm: floor || null, injWm: f.wm || null };
    }, { which, row });
    const injNewer = await injectFrame("newer", landedRow);
    injected.injWm = injNewer.injWm; injected.floorWmNewer = injNewer.floorWm;   // the bumped watermark actually shipped, and the floor it bumped from (a red names the frame; the older call reuses this same floor, asserted equal below)
    injected.landedWait = await page.waitForFunction((u) => { const el = document.querySelector('#content .turn[data-uuid="' + u + '"]'); return !!el && el.getClientRects().length > 0; }, landedRow.uuid, { timeout: 5000 }).then(() => "applied").catch((e) => { if (!e || e.name !== "TimeoutError") throw e; return "timeout"; });   // resolves to applied|timeout (no swallowed cap), so a red tells slow from dropped
    injected.diagAfterLanded = await page.evaluate(() => window.__diag.slice());
    await check("inject-landed", 0, "landed", text);
    injected.landed = await page.evaluate((u) => { const el = document.querySelector('#content .turn[data-uuid="' + u + '"]'); return !!el && el.getClientRects().length > 0; }, landedRow.uuid);
    // RED-FIRST (checked in): re-post the kernel's OWN last chatTail (the send's ONE delta on current main) after the landed
    // row is in the DOM. Its watermark is behind the injection (derived ahead of the page's floor of EITHER type: same leaf,
    // same parse-row count, a smaller size and live), so the guard REFUSES the re-post (frame-stale, type chatTail) and the
    // landed row survives. With the floor derived from window.__last.wm alone (the session-only base) instead of __lastAny,
    // the injection is only a MIXED reading of the page's real floor, so the re-posted delta APPLIES: it truncates the tail
    // and files frame-drops-landed, dropping the injected row (render.ts droppedLandedHuman). Red at that floor, green here.
    injected.socketsAtRepost = await page.evaluate(() => window.__sockets.map((s) => [String(s.url).replace(/token=[^&]*/, "token=X").replace(/^ws:\/\/[^/]*/, "").slice(0, 60), s.readyState]));
    injected.reposted = await page.evaluate((bl) => {
      const fr = window.__lastTail;   // the SEND's last kernel chatTail; NOT a connect-time tail (guard: its live is above the base session frame's read at capture)
      if (!fr || !fr.wm || typeof fr.wm.live !== "number" || fr.wm.live <= bl) return null;
      fr.__reposted = true;   // mark the driver's own re-post so the listener never re-captures it as a kernel frame
      window.postMessage(fr, "*");
      return { ev: Array.isArray(fr.events) ? fr.events.length : null, live: fr.wm.live, wm: { tx: fr.wm.tx, live: fr.wm.live } };
    }, baseLive);
    if (injected.reposted) {
      await painted();
      injected.afterKernelDelta = await page.evaluate((u) => { const el = document.querySelector('#content .turn[data-uuid="' + u + '"]'); return !!el && el.getClientRects().length > 0; }, landedRow.uuid);
      injected.diagAfterKernelDelta = await page.evaluate(() => window.__diag.slice());
    }
    injected.floorWmOlder = (await injectFrame("older", olderRow)).floorWm; await check("inject-stale", 0, "after-stale", text);   // the older frame reuses the landed call's floor snapshot (asserted equal in _assert_injected)
    injected.afterStale = await page.evaluate((u) => { const el = document.querySelector('#content .turn[data-uuid="' + u + '"]'); return !!el && el.getClientRects().length > 0; }, landedRow.uuid);
    injected.diagAfterStale = await page.evaluate(() => window.__diag.slice());
    await injectFrame("bare", olderRow); await painted();
    injected.afterBare = await page.evaluate((u) => { const el = document.querySelector('#content .turn[data-uuid="' + u + '"]'); return !!el; }, landedRow.uuid);
    injected.diagAfterBare = await page.evaluate(() => window.__diag.slice());
    injected.textVisibleAfterBare = (await measure(text)).visible;
    injected.wmLogEnd = await page.evaluate(() => window.__wmLog.slice());   // the kernel frames from load through the end (the driver's own posts are __reposted, excluded), so a red names the frames after the capture
  }
}
// H. the second report (the user 2026-09-22): an EARLIER message vanishes when a new send lands. Each send is landed the way the
// CLI lands a message it takes at once (two queue-operation records, then its native user record, then a step of the reply), and
// after every later frame EVERY landed row so far must still be on the page (by uuid), the pane shown or hidden during the landing.
const landed = [];   // { uuid, text }
const landedGone = [];
const landOne = (text, uuid) => {
  const t = t0 + 400 + landed.length * 10;
  const recs = [
    { type: "queue-operation", operation: "dequeue", timestamp: iso(t), sessionId: cfg.sid },
    { type: "user", timestamp: iso(t), uuid, parentUuid: parent, sessionId: cfg.sid, promptSource: "sdk", message: { role: "user", content: [{ type: "text", text }] } },
    { type: "assistant", timestamp: iso(t + 2), uuid: "r" + uuid.slice(-4), parentUuid: uuid, sessionId: cfg.sid,
      message: { role: "assistant", model: "claude-fable-5-1", stop_reason: "tool_use", content: [{ type: "tool_use", id: "tu_" + uuid.slice(-4), name: "Bash", input: { command: "true # after " + uuid.slice(-4) } }] } },
  ];
  parent = "r" + uuid.slice(-4);
  for (const r of recs) fs.appendFileSync(cfg.transcript, JSON.stringify(r) + "\n");
  landed.push({ uuid, text });
};
const rowsPresent = () => page.evaluate((ids) => ids.filter((u) => !document.querySelector('#content .turn[data-uuid="' + u + '"]')), landed.map((l) => l.uuid));
const setHidden = (hidden) => page.evaluate((h) => {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => (h ? "hidden" : "visible") });
  Object.defineProperty(document, "hidden", { configurable: true, get: () => h });
  document.dispatchEvent(new Event("visibilitychange"));
}, hidden);
for (let r = 0; on("H") && r < cfg.rounds * 3; r++) {
  const hidden = r % 3 === 2;                      // every third landing happens with the pane hidden
  const text = fresh("keep");
  await send(text);
  await waitFrames(1, 3000);
  if (hidden) await setHidden(true);
  await snap(); landOne(text, "11111111-2222-3333-4444-" + String(100000000000 + r).slice(-12));
  await waitFrames(1, 5000); await painted();
  await snap(); step(); await waitFrames(1, 5000); await painted();   // the reply goes on: another push after the landing
  if (hidden) { await setHidden(false); await painted(); }
  const gone = await rowsPresent();
  landedGone.push({ round: r, hidden, gone, tail: (await measure(text)).tail });
  await check("landed-rows", r, hidden ? "hidden-landing" : "landing", text);
}
const sent = await page.evaluate(() => window.__sent.length);
// the result goes to a FILE: a synchronous write of more than 64 KB to the captured stdout pipe is cut short (eight rounds of checkpoints)
fs.writeFileSync(cfg.out, JSON.stringify({ checks, sent, injected, landedGone, waits, waitTimeouts }));
fs.writeSync(1, "RESULT-FILE:" + cfg.out + "\n");
await browser.close();
process.exit(0);
"""


# the drivers' budgets, under the runner's per-test ceiling (CI's served-page step runs pytest with --timeout=600, thread method) LESS the
# setup the same per-test timer wraps: pytest-timeout's thread method times the first test's setUpClass too, and a stall it catches ends the
# whole pytest process with os._exit, so no driver output and no kernel tail is printed and every later lab in the process goes unreported
# (the box lab's fix, tests/test_needs_you_box_chat_served.py DRIVER_TIMEOUT_S). The local class's setup is the esbuild run and a healthz boot
# loop bounded at 60 s (LOCAL_SETUP_S), so 480 s leaves the rest for both; the remote class boots two kernels (two 60 s healthz loops, run in
# turn) and waits up to 30 s for the hub's tunnel row (REMOTE_SETUP_S), so its budget sits lower. A driver that runs past its budget has hit
# several frame waits in a row, and the TimeoutExpired reaches the test as its own failure with the kernel's tail in hand rather than the
# runner's bare per-test timeout. DriverBudget below pins both figures under the cap ci.yml states, less the setup they name.
LOCAL_SETUP_S = 60
REMOTE_SETUP_S = 150
DRIVER_TIMEOUT_S = 480
DRIVER_TIMEOUT_REMOTE_S = 420


def _deleaf(o, base):
    """Replace ONLY the printed base leaf (the ~150-char TMPDIR path, printed once) with "=", leaving a DIFFERENT leaf
    visible: the guard's first test is leaf equality (frame-guard.ts), so a failure caused by a frame on ANOTHER transcript
    must keep its leaf, not have its cause erased. Watermarks, uuid tails and one leaf line carry no transcript text."""
    return ({k: ("=" if (k == "leaf" and v == base) else _deleaf(v, base)) for k, v in o.items()} if isinstance(o, dict)
            else [_deleaf(x, base) for x in o] if isinstance(o, list) else o)


def _kernel_tail(*logs):
    """The last lines of each kernel log named, for a failure message (a log a kernel never wrote reads as empty)."""
    out = []
    for name, path in logs:
        try:
            text = open(path).read()
        except OSError:
            text = ""
        out.append("%s:\n%s" % (name, text[-1500:]))
    return "\n".join(out)


class ServedSendBubbleVisible(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(os.path.join(EXT, "node_modules", "playwright")):
            raise unittest.SkipTest("extension deps absent (npm ci not run here) — the served guard needs them")
        cls.lab = tempfile.mkdtemp(prefix="send-bubble-")
        b = subprocess.run(["node", "esbuild.js"], cwd=EXT, capture_output=True, text=True)
        if b.returncode != 0:
            raise unittest.SkipTest("esbuild failed here: " + (b.stderr or b.stdout)[-200:])
        dist = os.path.join(cls.lab, "dist")
        copy_dist(os.path.join(EXT, "dist"), dist)
        cls.state = os.path.join(cls.lab, "xdg", "romp")
        cwd = os.path.join(cls.lab, "proj")
        for d in ("names", "sdk", "states"):
            os.makedirs(os.path.join(cls.state, d), exist_ok=True)
        Path(cls.state, "session-hosts").write_text("off\n")   # a test that mints its own state root pins the hosts off (CLAUDE.md)
        os.makedirs(cwd, exist_ok=True)
        Path(cls.state, "names", SID).write_text("web\t%s\t\t\n" % cwd)
        Path(cls.state, "sdk", SID + ".json").write_text(json.dumps(
            {"sid": SID, "name": "web", "cwd": cwd, "mode": "auto", "effort": "high",
             "lastSid": SID, "alive": True, "model": "claude-fable-5-1", "liveModel": "Fable 5.1"}))
        Path(cls.state, "usage.json").write_text(json.dumps({"five_hour": {"pct": 10}, "seven_day": {"pct": 10}}))
        claude = os.path.join(cls.lab, "claude")
        proj = os.path.join(claude, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd)))
        os.makedirs(proj, exist_ok=True)
        t0 = int(time.time()) - 900
        cls.t0 = t0
        recs = _seed_records(t0)
        cls.transcript = os.path.join(proj, SID + ".jsonl")
        Path(cls.transcript).write_text("".join(json.dumps(r) + "\n" for r in recs))
        cls.port = _free_port()
        cls.token = "testtok-sendbubble"
        env = _lab.kernel_env(cls.lab, claude, dist, cls.port, cls.token)
        cls.klog = os.path.join(cls.lab, "kernel.log")
        cls.kernel = subprocess.Popen([os.path.join(BIN, "romp-kernel")],
                                      stdout=open(cls.klog, "w"), stderr=subprocess.STDOUT, env=env)
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

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "kernel", None):
            cls.kernel.kill()
            cls.kernel.wait()
        shutil.rmtree(getattr(cls, "lab", ""), ignore_errors=True)

    def test_the_sent_text_is_visible_at_every_checkpoint(self):
        cfg = os.path.join(self.lab, "cfg.json")
        console_log = os.path.join(self.lab, "console.log")
        Path(console_log).write_text("")
        with open(cfg, "w") as f:
            json.dump({"chat": "http://127.0.0.1:%d/chat?token=%s" % (self.port, self.token),
                       "transcript": self.transcript, "sid": SID, "t0": self.t0, "parent": "a3", "rounds": ROUNDS,
                       "consoleLog": console_log, "variants": None, "remote": None, "pauseBeforeCapture": os.environ.get("SB_PAUSE_BEFORE_CAPTURE") != "0", "out": os.path.join(self.lab, "result.json")}, f)
        driver = os.path.join(self.lab, "driver.mjs")
        with open(driver, "w") as f:
            f.write(DRIVER)
        try:
            p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=DRIVER_TIMEOUT_S,
                               env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
        except subprocess.TimeoutExpired as e:
            # the driver ran past its budget (several frame waits in a row): its output so far and the kernel's tail, not a bare traceback
            out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            self.fail("the driver ran past its %d s budget; its output so far:\n%s\n%s" % (DRIVER_TIMEOUT_S, out[-3000:], _kernel_tail(("kernel", self.klog))))
        if p.returncode == 3:
            raise unittest.SkipTest("no playwright browser on this box — the served guard needs one (CI installs none)")
        self.assertEqual(p.returncode, 0, "driver failed:\n" + p.stdout[-3000:] + p.stderr[-3000:] + "\nkernel:\n" + open(self.klog).read()[-2500:])
        r = self._result(p)
        checks = r["checks"]
        misses = [c for c in checks if c["visible"] == 0]
        print("SEND-BUBBLE: %d checkpoints, %d misses, %d sends reached the socket, %d of %d frame waits ran out" % (len(checks), len(misses), r["sent"], r["waitTimeouts"], r["waits"]))
        print("SEND-BUBBLE pace (s at each variant's last checkpoint): %s" % {v: round(max(c["t"] for c in checks if c["variant"] == v) / 1000) for v in dict.fromkeys(c["variant"] for c in checks)})
        for c in misses[:40]:
            print("  MISS", json.dumps({k: c[k] for k in ("variant", "round", "at", "carriers", "tail", "sh", "st", "ch", "composer")}))
        console = open(console_log).read()
        self.assertEqual(console.strip(), "", "the page logged errors:\n" + console[-2000:])
        _inj = r.get("injected", {})   # the ~150-char leaf repeats across base/floor/injWm and every diag/wmLog wm; strip it (printed once) so the cap drops no key
        _base = (_inj.get("baseWm") or {}).get("leaf")
        print("SEND-BUBBLE injected (leaf %s, others shown):" % _base, json.dumps(_deleaf(_inj, _base), default=str)[:8000])   # watermarks, uuid tails, the base leaf once as "="; a frame on another transcript keeps its leaf: no transcript text; one print covers a red at the misses line and at inj["landed"]
        self.assertEqual(misses, [], "every checkpoint after a send shows the sent text in a visible element; misses above")
        # the injected frames (the module docstring's second paragraph)
        inj = r["injected"]
        self._assert_injected(inj)
        self._assert_landings(r)

    def _result(self, p):
        """The driver's result, read from the file its last stdout line names (never the line itself: a 64 KB pipe write is cut)."""
        line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT-FILE:")), None)
        self.assertIsNotNone(line, "driver printed no result:\n" + p.stdout[-3000:])
        with open(line[len("RESULT-FILE:"):]) as f:
            return json.load(f)

    def _assert_injected(self, inj):
        self.assertTrue(inj.get("baseOk"), "the kernel's real frame carries a watermark with the leaf and the parse rows: %r" % (inj.get("seen"),))
        self.assertEqual(inj.get("trailWait"), "seen", "the SEND's chatTail delta was seen before the base capture (bounded to frames past the send; current main sends ONE delta carrying the events, PR 2077 dropped the trailing empty tail): %r" % (inj.get("seen"),))
        self.assertEqual(inj.get("landedWait"), "applied", "the landed row applied within the bounded poll, not a swallowed timeout: %r" % (inj,))
        self.assertTrue(inj["landed"], "the landing frame put the landed row on the page")
        # the RED-FIRST: the kernel's own last chatTail (the send's ONE delta on current main), re-posted after the landed row
        # is in the DOM, is REFUSED (its watermark is behind the injection, which is derived ahead of the page's floor of
        # EITHER type), not applied. Pin that a replay frame EXISTED (a missing one would silently pass as the default False),
        # the row's SURVIVAL, and the REFUSAL.
        self.assertTrue(inj.get("reposted"), "the send's kernel chatTail was available and above the base to re-post as the red-first: %r" % (inj.get("seen"),))
        self.assertTrue(inj.get("afterKernelDelta", False), "the kernel's own chatTail delta (%r), re-posted after the landed row, does not drop it: %r" % ((inj.get("reposted") or {}).get("wm"), inj))
        repost_stale = [d for d in inj.get("diagAfterKernelDelta", []) if d["what"] == "frame-stale" and d["data"].get("type") == "chatTail"]
        self.assertEqual(len(repost_stale), 1, "…and the re-post was refused once as frame-stale (type chatTail), not applied: %r" % inj.get("diagAfterKernelDelta"))
        self.assertEqual(inj.get("floorWmOlder"), inj.get("floorWmNewer"), "the older frame's floor equals the landed call's (window.__injFloor is snapshotted once on the landed injection and reused): %r vs %r" % (inj.get("floorWmOlder"), inj.get("floorWmNewer")))
        self.assertTrue(inj["afterStale"], "an OLDER frame lacking the row left the landed row on the page: %r" % (inj,))
        # attribute the frame-stale row to the INJECTED older frame by TYPE (session, built from the session base): the OTHER
        # frame-stale row in diagAfterStale is the red-first's OWN chatTail replay (refused just above), which this filter excludes.
        stale = [d for d in inj["diagAfterStale"] if d["what"] == "frame-stale" and d["data"].get("type") == "session"]
        self.assertEqual(len(stale), 1, "…the injected older (session) frame was filed once as frame-stale: %r" % inj["diagAfterStale"])
        self.assertEqual([d["what"] for d in inj["diagAfterStale"] if d["what"] == "frame-drops-landed"], [], "an ignored frame drops nothing")
        self.assertFalse(inj["afterBare"], "the same older list with NO watermark (an older kernel) is applied as before the guard: the row goes")
        self.assertEqual(inj["textVisibleAfterBare"] >= 1, True, "…the kernel's echo in it still carries the text")
        drops = [d for d in inj["diagAfterBare"] if d["what"] == "frame-drops-landed"]
        self.assertEqual(len(drops), 1, "…and the loss is filed as frame-drops-landed: %r" % inj["diagAfterBare"])
        self.assertEqual((drops[0]["data"]["type"], drops[0]["data"]["n"], drops[0]["data"]["wm"], drops[0]["data"]["expected"]), ("session", 1, False, None))
        self.assertEqual(drops[0]["data"]["keys"], ["aaaaaaaaaaaa"], "the row names the uuid's tail, never the text")

    def _assert_landings(self, r):
        # the second report: every landed row stays through every later send, the pane shown or hidden during the landing
        lg = r["landedGone"]
        self.assertGreaterEqual(len(lg), 3, "landings ran: %r" % (lg,))
        print("SEND-BUBBLE landings: %d rounds, gone per round %r" % (len(lg), [x["gone"] for x in lg]))
        self.assertEqual([x for x in lg if x["gone"]], [], "no earlier landed row left the page after a later send: %r" % ([x for x in lg if x["gone"]],))


class ServedSendBubbleVisibleRemote(ServedSendBubbleVisible):
    """The same lab through the HUB RELAY: a REMOTE hermetic kernel (host TESTHOST) owns the session and a HUB kernel with none of
    its own shows it through the relay after the mobile check-in handshake (the T328 remote lab's boot). Both of the user's
    live misses were on a remote session, so the sends, the landings (shown and hidden) and the injected frames run here on the
    remote tab: the frames reach the page through federation.ts prefixInbound, which prefixes ids and passes the watermark
    through. Variants A, G and H (the redial and reload variants are the local lab's)."""

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(os.path.join(EXT, "node_modules", "playwright")):
            raise unittest.SkipTest("extension deps absent (npm ci not run here) — the served guard needs them")
        cls.lab = tempfile.mkdtemp(prefix="send-bubble-remote-")
        b = subprocess.run(["node", "esbuild.js"], cwd=EXT, capture_output=True, text=True)
        if b.returncode != 0:
            raise unittest.SkipTest("esbuild failed here: " + (b.stderr or b.stdout)[-200:])
        copy_dist(os.path.join(EXT, "dist"), os.path.join(cls.lab, "dist"))
        cls.procs = []
        cls.t0 = int(time.time()) - 900
        cls.rport, cls.rtoken = _free_port(), "testtok-remote-sb"
        cls.port, cls.token = _free_port(), "testtok-hub-sb"
        try:
            rp, cls.rlog, cls.transcript = _kernel(cls.lab, "testhost", cls.rport, cls.rtoken, records=_seed_records(cls.t0), host_name="TESTHOST")
            cls.procs.append(rp)
            hp, cls.klog, _ = _kernel(cls.lab, "hub", cls.port, cls.token)
            cls.procs.append(hp)
        except unittest.SkipTest:
            cls.tearDownClass(); raise
        cls.kernel = None
        import urllib.request
        body = json.dumps({"host": "TESTHOST", "kernelPort": cls.rport, "busPort": _free_port(), "token": cls.rtoken}).encode()
        req = urllib.request.Request("http://127.0.0.1:%d/checkin?token=%s" % (cls.port, cls.token), data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            ans = json.loads(resp.read().decode())
        if not ans.get("ok"):
            cls.tearDownClass(); raise unittest.SkipTest("the hub refused the check-in: %r" % ans)
        rows = []
        for _ in range(60):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/tunnels?token=%s" % (cls.port, cls.token), timeout=3) as r2:
                    rows = json.loads(r2.read().decode()).get("tunnels") or []
            except Exception:
                rows = []
            row = next((t for t in rows if t.get("host") == "TESTHOST"), None)
            if row and row.get("status") == "up" and row.get("hasToken"):
                break
            time.sleep(0.5)
        else:
            cls.tearDownClass(); raise unittest.SkipTest("the hub never reported the checked-in peer up: %r" % (rows,))

    @classmethod
    def tearDownClass(cls):
        for p in getattr(cls, "procs", []):
            try:
                p.kill(); p.wait()
            except Exception:
                pass
        shutil.rmtree(getattr(cls, "lab", ""), ignore_errors=True)

    def test_the_sent_text_is_visible_at_every_checkpoint(self):
        cfg = os.path.join(self.lab, "cfg.json")
        console_log = os.path.join(self.lab, "console.log")
        Path(console_log).write_text("")
        with open(cfg, "w") as f:
            json.dump({"chat": "http://127.0.0.1:%d/chat?token=%s" % (self.port, self.token),
                       "transcript": self.transcript, "sid": SID, "t0": self.t0, "parent": "a3", "rounds": max(1, ROUNDS // 2),
                       "consoleLog": console_log, "variants": ["A", "G", "H"], "remote": "TESTHOST", "out": os.path.join(self.lab, "result.json")}, f)
        driver = os.path.join(self.lab, "driver.mjs")
        with open(driver, "w") as f:
            f.write(DRIVER)
        try:
            p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=DRIVER_TIMEOUT_REMOTE_S,
                               env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
        except subprocess.TimeoutExpired as e:
            out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            self.fail("the driver ran past its %d s budget; its output so far:\n%s\n%s" % (DRIVER_TIMEOUT_REMOTE_S, out[-3000:], _kernel_tail(("hub", self.klog), ("remote", self.rlog))))
        if p.returncode == 3:
            raise unittest.SkipTest("no playwright browser on this box — the served guard needs one (CI installs none)")
        self.assertEqual(p.returncode, 0, "driver failed:\n" + p.stdout[-3000:] + p.stderr[-3000:] + "\nhub:\n" + open(self.klog).read()[-2000:] + "\nremote:\n" + open(self.rlog).read()[-1200:])
        r = self._result(p)
        checks = r["checks"]
        misses = [c for c in checks if c["visible"] == 0]
        print("SEND-BUBBLE remote: %d checkpoints, %d misses, %d sends reached the socket, %d of %d frame waits ran out" % (len(checks), len(misses), r["sent"], r["waitTimeouts"], r["waits"]))
        for c in misses[:40]:
            print("  MISS", json.dumps({k: c[k] for k in ("variant", "round", "at", "carriers", "tail", "sh", "st", "ch", "composer")}))
        console = open(console_log).read()
        self.assertEqual(console.strip(), "", "the page logged errors:\n" + console[-2000:])
        _ri = r.get("injected", {})
        _rbase = (_ri.get("baseWm") or {}).get("leaf")
        print("SEND-BUBBLE remote injected (leaf %s, others shown):" % _rbase, json.dumps(_deleaf(_ri, _rbase), default=str)[:8000])   # a remote failure at the misses line or at inj["landed"] now carries the injected record too
        self.assertEqual(misses, [], "every checkpoint after a send into the remote session shows the sent text in a visible element; misses above")
        self._assert_injected(r["injected"])
        self._assert_landings(r)


class DriverBudget(unittest.TestCase):
    """Both drivers' budgets sit under the per-test ceiling CI's served-page step gives pytest, less the setup the same timer wraps
    (the comment above DRIVER_TIMEOUT_S), and both subprocess.run calls read them: a literal that drifted past the cap would let a
    stalled driver hit pytest-timeout first, which ends the process with no output and every later lab unreported. Needs no browser."""

    def _ci_cap(self):
        text = open(os.path.join(ROOT, ".github", "workflows", "ci.yml")).read()
        at = text.find('ROMP_SERVED_TESTS_REQUIRE: "1"')
        self.assertGreater(at, 0, "ci.yml names the served-page step by its ROMP_SERVED_TESTS_REQUIRE env")
        m = re.search(r"--timeout=(\d+)", text[at:])
        self.assertIsNotNone(m, "the served-page step runs pytest under --timeout")
        return int(m.group(1))

    def test_the_budgets_sit_under_the_ci_cap_less_the_setup(self):
        cap = self._ci_cap()
        self.assertLess(DRIVER_TIMEOUT_S + LOCAL_SETUP_S, cap, "the local driver's budget plus its class's setup bound stays under CI's per-test cap")
        self.assertLess(DRIVER_TIMEOUT_REMOTE_S + REMOTE_SETUP_S, cap, "the remote driver's budget plus its class's setup bound (two boots, the tunnel wait) stays under CI's per-test cap")
        self.assertLessEqual(DRIVER_TIMEOUT_REMOTE_S, DRIVER_TIMEOUT_S, "the remote class sets up more, so its budget is not the larger")

    def test_both_driver_runs_read_the_budgets(self):
        src = open(os.path.realpath(__file__)).read()
        runs = re.findall(r'subprocess\.run\(\["node", driver\][^\n]*timeout=([A-Za-z_0-9]+)', src)
        self.assertEqual(runs, ["DRIVER_TIMEOUT_S", "DRIVER_TIMEOUT_REMOTE_S"], "the local run reads DRIVER_TIMEOUT_S and the remote run DRIVER_TIMEOUT_REMOTE_S, no literal")
        self.assertEqual(len(re.findall(r"except subprocess\.TimeoutExpired", src)), 2, "each run reports a budget overrun with the kernel's tail")


if __name__ == "__main__":
    unittest.main()
