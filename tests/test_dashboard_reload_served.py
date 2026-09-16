#!/usr/bin/env python3
"""The served leg of the reload OFFER (the user 2026-09-16, superseding the 2026-09-08 self-reload, which superseded the
2026-07-13 banner): the dashboard never reloads itself. A newer build is one persistent line with Reload and Not now; a
restart onto the same build is invisible beyond the reconnect; the reader keeps their place through the reload they take.

Executed against the REAL page: a hermetic kernel serves the dashboard from a private copy of dist; the driver opens it,
scrolls the chat transcript to mid-history, and
  1. bumps a dist bundle's mtime (the kernel's next keepalive carries a higher `dv`, the authoritative drift signal) and
     asserts the offer line appears in the shell's banner ("A newer romp build is ready.", Reload, Not now) and the page
     did NOT reload through three more keepalives; the panes did not move (the banner is fixed);
  2. clicks Not now, asserts the line is gone and stays gone through later keepalives (the Not now is kept per build),
     bumps again and asserts a strictly newer build re-offers;
  3. clicks Reload and asserts the page reloaded once, landed the chat tab on the reader's saved position (not the
     bottom), left one "Reloaded onto build …" line in the notification center, and settled (no second reload);
  4. kills the kernel and relaunches it on the same port, a socket reopen against a NEW boot id of the SAME build, and
     asserts NO reload and NO offer: the board stays, the reader's place holds, the pane's redial lands its fresh frame,
     the notification center gains no line;
  5. relaunches with another code identity, a restart onto a CHANGED build, and asserts the offer and no reload; then
     sends an op the kernel does not know from the chat pane's socket and asserts the offer's wording gains the reason
     (the unknownOp refusal, an exact event); then accepts and asserts one reload with its line.
Skips LOUDLY when the extension deps or a playwright browser are absent (CI installs none); the decision code itself runs
in node in test_dashboard_auto_reload.py regardless. All fixtures synthetic."""
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

from tests.dist_copy import copy_dist

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
EXT = os.path.join(ROOT, "vscode-extension")
SID = "11111111-2222-4333-8444-000000000201"

import sys
sys.path.insert(0, HERE)
import test_ship_reship_served as _lab   # noqa: E402  the lab kernel's environment and the cfg.relaunch stanza (the module,
#                                   not its classes: an imported TestCase would be collected here a second time)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _transcript(cwd, pairs):
    """`pairs` closed user/assistant turns (an OPEN turn would invite the boot reconcile to resume it)."""
    out, parent, t = [], None, 1_700_000_000
    filler = ["The ranking pass reads its weights from the notes-api config now.",
              "Tokenizer edge cases (hyphens, quotes) are covered by the new fixture set.",
              "Index rebuild time is dominated by the stemmer; caching its table halves it.",
              "The pagination cursor survives a re-sort because it encodes the sort key too."]
    for i in range(pairs):
        u = "11111111-2222-4333-8444-0000000a%04x" % i
        a = "11111111-2222-4333-8444-0000000b%04x" % i
        ts = lambda k: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t + i * 60 + k))
        out.append({"type": "user", "uuid": u, "parentUuid": parent, "timestamp": ts(0), "sessionId": SID, "cwd": cwd,
                    "message": {"role": "user", "content": "please keep going with the search module notes (part %d)" % (i + 1)}})
        body = "\n\n".join(["Note %d." % (i + 1)] + [filler[(i + k) % len(filler)] for k in range(3)])
        out.append({"type": "assistant", "uuid": a, "parentUuid": u, "timestamp": ts(5), "sessionId": SID, "cwd": cwd,
                    "message": {"id": "msg_lab_%04d" % i, "type": "message", "role": "assistant", "model": "claude-sonnet-5",
                                "content": [{"type": "text", "text": body}], "stop_reason": "end_turn"}})
        parent = a
    return "\n".join(json.dumps(r) for r in out) + "\n"


DRIVER = r"""
import { createRequire } from "node:module";
import fs from "node:fs";
import { spawn } from "node:child_process";
const require = createRequire(process.env.EXT_PKG);
const { chromium } = require("playwright");
const cfg = JSON.parse(fs.readFileSync(process.env.CFG, "utf8"));
let browser;
try { browser = await chromium.launch(); }
catch (e) { console.error("browser-launch-failed: " + e); process.exit(3); }
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const out = {};
const die = async (why) => {
  fs.writeSync(1, "RESULT:" + JSON.stringify({ ...out, died: why }) + "\n");
  await browser.close();
  process.exit(0);
};
const chatFrame = () => page.frames().find((f) => f.url().split("?")[0].endsWith("/chat"));
const waitChat = async () => {
  await page.waitForFunction(() => Array.from(document.querySelectorAll("iframe")).some((f) => (f.getAttribute("src") || "").startsWith("/chat")), null, { timeout: 20000 });
  let fr = null;
  for (let i = 0; i < 200 && !fr; i++) { fr = chatFrame(); if (!fr) await page.waitForTimeout(100); }
  if (!fr) await die("no /chat frame");
  await fr.waitForFunction(() => {
    const c = document.getElementById("content");
    return !!c && c.querySelectorAll(".turn").length > 20 && c.scrollHeight > c.clientHeight + 500;
  }, null, { timeout: 30000 }).catch(async () => { await die("chat never overflowed"); });
  return fr;
};
const info = (fr) => fr.evaluate(() => {
  const c = document.getElementById("content");
  const cr = c.getBoundingClientRect();
  const els = Array.from(c.querySelectorAll("[data-uuid]"));
  let anchor = null;
  for (const el of els) { const r = el.getBoundingClientRect(); if (r.bottom > cr.top) { anchor = { uuid: el.dataset.uuid, top: Math.round(r.top - cr.top) }; break; } }
  return { scrollTop: c.scrollTop, scrollHeight: c.scrollHeight, clientHeight: c.clientHeight, anchor,
           chipHidden: (document.getElementById("jump-bottom") || { hidden: true }).hidden };
});
const notices = () => page.evaluate(() => { try { return JSON.parse(localStorage.getItem("romp:notices") || "[]").filter((n) => n.kind === "reload").map((n) => n.text); } catch (e) { return []; } });
const probeSet = () => page.evaluate(() => { window.__probe = 1; return 1; });
const probeAlive = () => page.evaluate(() => window.__probe === 1).catch(() => false);
const shell = () => page.evaluate(() => window.__rompReload ? { waiting: window.__rompReload.waiting, owed: window.__rompReload.owed(), offered: window.__rompReload.offered(), fired: window.__rompReload.fired() } : null).catch(() => null);
// the banner as the reader sees it: shown, the offer class, the line, the two buttons
const banner = () => page.evaluate(() => { const b = document.getElementById("rstale"); if (!b) return null;
  return { shown: b.classList.contains("show"), offer: b.classList.contains("offer"), text: b.querySelector(".rs-msg").textContent,
           reload: document.getElementById("rstale-reload").textContent, dismiss: document.getElementById("rstale-dismiss").textContent }; }).catch(() => null);
const waitOffer = (ms) => page.waitForFunction(() => { const b = document.getElementById("rstale"); return !!b && b.classList.contains("show") && b.classList.contains("offer"); }, null, { timeout: ms }).then(() => true).catch(() => false);
const paneBox = () => page.evaluate(() => { const f = document.querySelector('iframe[src^="/chat"]'); const r = f.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; });
const bump = (n) => { const t = new Date(Date.now() + n * 60 * 1000); fs.utimesSync(cfg.bumpFile, t, t); };
const relaunch = (env) => { const k = spawn(cfg.relaunch.cmd, [], { env, detached: true,
  stdio: ["ignore", fs.openSync(cfg.relaunch.log, "a"), fs.openSync(cfg.relaunch.log, "a")] }); k.unref(); fs.writeSync(1, "KPID:" + k.pid + "\n"); return k; };

// ---- load, scroll to mid-history ----
await page.goto(cfg.url);
let fr = await waitChat();
await page.waitForTimeout(800);
await fr.evaluate(() => { const c = document.getElementById("content"); c.scrollTop = Math.round(c.scrollHeight * 0.45); });
await page.waitForTimeout(600);
out.before = await info(fr);
out.paneBefore = await paneBox();
await probeSet();
out.noticesBefore = await notices();
out.bannerBefore = await banner();

// ---- 1. bump the bundle: the offer appears; the page does NOT reload ----
bump(1);
out.offerShown = await waitOffer(15000);                   // one keepalive (ROMP_WS_KEEPALIVE=2 in the lab env) carries the higher dv
out.bannerOffer = await banner();
out.paneWithOffer = await paneBox();
await page.waitForTimeout(6500);                           // three more keepalives: a reload owed would have fired by now
out.probeAfterOffer = await probeAlive();
out.shellAfterOffer = await shell();
out.noticesAfterOffer = await notices();

// ---- 2. Not now: gone, and kept gone through later keepalives; a strictly newer build re-offers ----
await page.click("#rstale-dismiss");
out.bannerAfterNotNow = await banner();
out.notNowKept = await page.evaluate(() => { try { return JSON.parse(localStorage.getItem("romp:reloadNotNow") || "null"); } catch (e) { return null; } });
await page.waitForTimeout(4500);                           // two keepalives carrying the declined dv
out.bannerAfterKeepalives = await banner();
bump(2);
out.reoffered = await waitOffer(15000);
out.shellReoffered = await shell();

// ---- 3. Reload: one reload, the reader's place, one line; then the fresh page settles ----
await probeSet();
await page.click("#rstale-reload");
out.reloadedOnClick = await page.waitForFunction(() => window.__probe !== 1, null, { timeout: 15000 }).then(() => true).catch(() => false);
if (!out.reloadedOnClick) await die("no reload after the Reload click");
fr = await waitChat();
let after = null;
for (let i = 0; i < 25; i++) { after = await info(fr); if (after.scrollHeight - after.scrollTop - after.clientHeight > 2 && after.scrollTop > 0) break; await page.waitForTimeout(200); }
out.after = after;
out.noticesAfterReload = await notices();
await probeSet();
await page.waitForTimeout(7000);
out.settledAfterReload = await probeAlive();
out.bannerAfterReload = await banner();

// ---- 4. a kernel restart of the SAME build: kill + relaunch on the same port ----
const beforeRestart = await info(fr);
process.kill(cfg.kernelPid, "SIGKILL");
await page.waitForTimeout(500);
const k2 = relaunch(cfg.relaunch.env);
out.restartSeen = await page.waitForFunction(() => window.__rompReload && window.__rompReload.restarted() >= 1, null, { timeout: 60000 }).then(() => true).catch(() => false);
out.freshAfterRestart = await fr.waitForFunction(() => window.__rompFreshPending === false, null, { timeout: 60000 }).then(() => true).catch(() => false);
await page.waitForTimeout(7000);                           // three keepalives on the new kernel
out.probeAfterRestart = await probeAlive();
out.shellAfterRestart = await shell();
out.bannerAfterRestart = await banner();
out.afterRestart = await info(fr).catch(() => null);
out.beforeRestart = beforeRestart;
out.noticesAfterRestart = await notices();

// ---- 5. a restart onto a CHANGED build: the offer, no reload; an unknown op sharpens its wording; the accept reloads ----
process.kill(k2.pid, "SIGKILL");
await page.waitForTimeout(500);
relaunch({ ...cfg.relaunch.env, ROMP_CODE_IDENT: "changed-build" });
out.offerOnChangedBuild = await waitOffer(60000);
out.bannerChangedBuild = await banner();
await page.waitForTimeout(7000);
out.probeAfterChangedBuild = await probeAlive();
out.shellAfterChangedBuild = await shell();
out.noticesAfterChangedBuild = await notices();
// the chat pane asks its kernel for something it does not know: the kernel answers unknownOp on that socket (an exact event)
await fr.evaluate(() => { window.__rompLocalSend({ type: "labNoSuchOp" }); });
out.behindWording = await page.waitForFunction(() => { const m = document.querySelector("#rstale .rs-msg"); return !!m && /behind the kernel/.test(m.textContent); }, null, { timeout: 15000 }).then(() => true).catch(() => false);
out.bannerBehind = await banner();
out.probeAfterBehind = await probeAlive();
await probeSet();
await page.click("#rstale-reload");
const t0 = Date.now();
out.reloadedOnAccept = await page.waitForFunction(() => window.__probe !== 1, null, { timeout: 90000 }).then(() => true).catch(() => false);
out.acceptReloadMs = Date.now() - t0;
if (!out.reloadedOnAccept) await die("no reload after accepting the changed build's offer");
fr = await waitChat();
out.noticesFinal = await notices();
out.bannerFinal = await banner();
fs.writeSync(1, "RESULT:" + JSON.stringify(out) + "\n");
await browser.close();
process.exit(0);
"""



class ServedAutoReload(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(os.path.join(EXT, "node_modules", "playwright")):
            raise unittest.SkipTest("extension deps absent (npm ci not run here) — the served leg needs them")
        cls.lab = tempfile.mkdtemp(prefix="auto-reload-")
        b = subprocess.run(["node", "esbuild.js"], cwd=EXT, capture_output=True, text=True)
        if b.returncode != 0:
            raise unittest.SkipTest("esbuild failed here: " + (b.stderr or b.stdout)[-200:])
        dist = os.path.join(cls.lab, "dist")
        copy_dist(os.path.join(EXT, "dist"), dist)
        cls.bump_file = os.path.join(dist, "render.js")
        state = os.path.join(cls.lab, "xdg", "romp")
        cwd = os.path.join(cls.lab, "proj")
        os.makedirs(os.path.join(state, "names"), exist_ok=True)
        os.makedirs(os.path.join(state, "sdk"), exist_ok=True)
        os.makedirs(cwd, exist_ok=True)
        # one synthetic SDK session so the chat page has a tab (the test_ship_reship_served lab shape); its transcript
        # holds only CLOSED turns, so the boot reconcile never tries to resume it and no CLI is ever spawned
        Path(state, "names", SID).write_text("web\t%s\t\t\n" % cwd)
        Path(state, "sdk", SID + ".json").write_text(json.dumps(
            {"sid": SID, "name": "web", "cwd": cwd, "mode": "auto", "effort": "high", "lastSid": SID, "alive": True}))
        Path(state, "usage.json").write_text(json.dumps({"five_hour": {"pct": 100}, "seven_day": {"pct": 10}}))   # park sends
        claude = os.path.join(cls.lab, "claude")
        proj = os.path.join(claude, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd)))
        os.makedirs(proj, exist_ok=True)
        Path(proj, SID + ".jsonl").write_text(_transcript(cwd, 60))   # long: overflows the pane several times over
        cls.port = _free_port()
        cls.token = "testtok-autoreload"
        cls.env = _lab.kernel_env(cls.lab, claude, dist, cls.port, cls.token,
                                  ROMP_WS_KEEPALIVE="2")                       # the dv rides the keepalive: keep the wait short
        # a name outside the relaunch list, planted in the lab kernel's environment so the check on the cfg.json the
        # driver reads has something the file must not carry
        cls.env["RUNNER_SECRET_PROBE"] = "abc"
        cls.klog = os.path.join(cls.lab, "kernel.log")
        cls.kernel = subprocess.Popen([os.path.join(BIN, "romp-kernel")],
                                      stdout=open(cls.klog, "w"), stderr=subprocess.STDOUT, env=cls.env)
        cls.relaunched_pids = []
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
        for pid in [getattr(cls, "kernel", None) and cls.kernel.pid] + list(getattr(cls, "relaunched_pids", [])):
            if pid:
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        if getattr(cls, "kernel", None):
            cls.kernel.wait()
        shutil.rmtree(getattr(cls, "lab", ""), ignore_errors=True)

    def test_a_newer_build_is_offered_not_now_is_kept_reload_is_a_click_and_a_same_build_restart_is_invisible(self):
        cfg = os.path.join(self.lab, "cfg.json")
        with open(cfg, "w") as f:
            json.dump({"url": "http://127.0.0.1:%d/?token=%s" % (self.port, self.token),
                       "kernelPid": self.kernel.pid, "bumpFile": self.bump_file,
                       "relaunch": _lab.relaunch_cfg(self.env, self.klog)}, f)
        # the file carries only what the driver and the relaunched kernel need: the probe the lab planted in its
        # kernel's environment (checked first, so the file check cannot pass without it) must not be in it (names
        # only in the report, never the values)
        self.assertIn("RUNNER_SECRET_PROBE", sorted(self.env), "the lab plants the probe in its kernel's environment")
        written = json.loads(Path(cfg).read_text(encoding="utf-8"))
        self.assertNotIn("RUNNER_SECRET_PROBE", sorted(written["relaunch"]["env"]),
                         "the lab's cfg.json carries a name of the lab kernel's environment outside the relaunch list")
        driver = os.path.join(self.lab, "driver.mjs")
        with open(driver, "w") as f:
            f.write(DRIVER)
        try:
            p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=300,
                               env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
        except subprocess.TimeoutExpired as e:
            so = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode()
            type(self).relaunched_pids = [int(ln.split(":", 1)[1]) for ln in so.splitlines() if ln.startswith("KPID:")]
            self.fail("driver timed out; partial output:\n%s" % so)
        type(self).relaunched_pids = [int(ln.split(":", 1)[1]) for ln in p.stdout.splitlines() if ln.startswith("KPID:")]
        if p.returncode == 3:
            raise unittest.SkipTest("no playwright browser on this box — the served leg needs one (CI installs none)")
        self.assertEqual(p.returncode, 0, "driver failed:\n" + p.stdout[-3000:] + p.stderr[-3000:])
        line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT:")), None)
        self.assertIsNotNone(line, "driver printed no result:\n" + p.stdout[-3000:])
        r = json.loads(line[len("RESULT:"):])
        self.assertNotIn("died", r, "driver aborted early: %r" % r)
        OFFER = "A newer romp build is ready."
        BEHIND = "A newer romp build is ready; this page is behind the kernel and some actions fall back to older paths until you reload."
        b, a = r["before"], r["after"]
        self.assertGreater(b["scrollHeight"] - b["scrollTop"] - b["clientHeight"], 200, "the reader was scrolled up before: %r" % b)
        self.assertFalse((r["bannerBefore"] or {}).get("shown"), "nothing to say on a current page: %r" % r["bannerBefore"])
        # 1. the offer, and no reload
        self.assertTrue(r["offerShown"], "the higher dv on the keepalive stands the offer: %r" % r)
        self.assertEqual(r["bannerOffer"], {"shown": True, "offer": True, "text": OFFER, "reload": "Reload", "dismiss": "Not now"}, "the one line, its two buttons")
        self.assertTrue(r["probeAfterOffer"], "the page must not reload on its own: %r" % r)
        self.assertIsNone((r["shellAfterOffer"] or {}).get("owed"), "nothing owed: no hold, no backstop: %r" % r["shellAfterOffer"])
        self.assertEqual(((r["shellAfterOffer"] or {}).get("offered") or {}).get("text"), OFFER)
        self.assertEqual(r["paneWithOffer"], r["paneBefore"], "the banner is fixed: the panes did not move: %r → %r" % (r["paneBefore"], r["paneWithOffer"]))
        self.assertEqual(len(r["noticesBefore"]), 0); self.assertEqual(len(r["noticesAfterOffer"]), 0, "an offer writes no notification-center line")
        # 2. Not now, kept per build; a newer build re-offers
        self.assertFalse(r["bannerAfterNotNow"]["shown"], "Not now takes the line down: %r" % r["bannerAfterNotNow"])
        self.assertEqual((r["notNowKept"] or {}).get("dv"), ((r["shellAfterOffer"] or {}).get("offered") or {}).get("dv"), "the declined build is kept in localStorage: %r" % r["notNowKept"])
        self.assertFalse(r["bannerAfterKeepalives"]["shown"], "the declined build stays quiet through later keepalives: %r" % r["bannerAfterKeepalives"])
        self.assertTrue(r["reoffered"], "a strictly newer build re-offers: %r" % r)
        self.assertGreater(((r["shellReoffered"] or {}).get("offered") or {}).get("dv", 0), (r["notNowKept"] or {}).get("dv", 0))
        # 3. Reload is the user's click: one reload, the reader's place, one line, then quiet
        self.assertTrue(r["reloadedOnClick"])
        same_row = a["anchor"]["uuid"] == b["anchor"]["uuid"] and abs(a["anchor"]["top"] - b["anchor"]["top"]) <= 60
        same_pixel = abs(a["scrollTop"] - b["scrollTop"]) <= 60
        self.assertTrue(same_row or same_pixel, "the reader's place survives the reload, by the anchor row or by the scroll pixel: %r → %r" % (b, a))
        self.assertGreater(a["scrollHeight"] - a["scrollTop"] - a["clientHeight"], 200, "…and is not the bottom: %r" % a)
        self.assertFalse(a["chipHidden"], "off the bottom, the go-to-bottom chip shows")
        self.assertEqual(len(r["noticesAfterReload"]), 1, "one notification-center line per reload: %r" % r["noticesAfterReload"])
        self.assertRegex(r["noticesAfterReload"][0], r"^Reloaded onto build \d+: a newer romp build was served\.$")
        self.assertTrue(r["settledAfterReload"], "one reload per click; the fresh page must not reload again: %r" % r)
        self.assertFalse(r["bannerAfterReload"]["shown"], "on the current build the line is gone: %r" % r["bannerAfterReload"])
        # 4. a same-build restart is invisible: seen, counted, no reload, no offer, no line
        self.assertTrue(r["restartSeen"], "the shell saw the new boot id: %r" % r)
        self.assertTrue(r["probeAfterRestart"], "a restart of the same build must not reload the page: %r" % r)
        self.assertTrue(r["freshAfterRestart"], "the chat pane redialed and landed its fresh frame: %r" % r)
        self.assertIsNone((r["shellAfterRestart"] or {}).get("owed")); self.assertIsNone((r["shellAfterRestart"] or {}).get("offered"), "no offer: the same build: %r" % r["shellAfterRestart"])
        self.assertFalse(r["bannerAfterRestart"]["shown"], "no line: %r" % r["bannerAfterRestart"])
        self.assertEqual(len(r["noticesAfterRestart"]), 1, "no new notification-center line: %r" % r["noticesAfterRestart"])
        br, ar = r["beforeRestart"], r["afterRestart"]
        self.assertIsNotNone(ar, "the chat frame is the same document: %r" % r)
        self.assertLessEqual(abs(ar["scrollTop"] - br["scrollTop"]), 60, "the reader's place held through the restart: %r → %r" % (br, ar))
        # 5. a changed build is offered, an unknown op sharpens the wording, the accept reloads
        self.assertTrue(r["offerOnChangedBuild"], "a restart onto a changed build stands the offer: %r" % r)
        self.assertEqual(r["bannerChangedBuild"]["text"], OFFER)
        self.assertTrue(r["probeAfterChangedBuild"], "…and never reloads by itself: %r" % r)
        self.assertEqual(((r["shellAfterChangedBuild"] or {}).get("offered") or {}).get("code"), "changed-build", "the offer names the code identity: %r" % r["shellAfterChangedBuild"])
        self.assertEqual(len(r["noticesAfterChangedBuild"]), 1)
        self.assertTrue(r["behindWording"], "the kernel's unknownOp refusal sharpened the line: %r" % r)
        self.assertEqual(r["bannerBehind"]["text"], BEHIND)
        self.assertTrue(r["probeAfterBehind"], "a refusal never reloads the page: %r" % r)
        self.assertTrue(r["reloadedOnAccept"]); self.assertLess(r["acceptReloadMs"], 60000, "the accept lands within the fresh bound: %r" % r)
        self.assertEqual(len(r["noticesFinal"]), 2, "one more line for the accepted reload: %r" % r["noticesFinal"])
        self.assertRegex(r["noticesFinal"][-1], r"a newer romp build was served\.$")
        self.assertFalse(r["bannerFinal"]["shown"], "the fresh page is on the served build: %r" % r["bannerFinal"])

if __name__ == "__main__":
    unittest.main()
