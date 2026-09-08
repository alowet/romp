#!/usr/bin/env python3
"""T260 (the user 2026-09-08): the chat scrollbar's notches are links — the pointer turns into the link cursor
over a notch, and a click jumps the transcript to that message.

The served guard drives the real /chat page from a hermetic kernel (synthetic transcript: five user prompts,
each answered by a long reply, so the first prompt sits far above the fold when the page opens at the tail).
It checks, in the browser: the box stays pointer-events:none while each notch takes the pointer with the
link cursor; hovering a notch shows the accent ring in BOTH themes (the painted 8×2 mark unchanged); and a
click on the first prompt's notch lands the chat on that message — the turn carrying that uuid is in view and
wears the deep-link flash, exactly as a comment tick's jump does (the pendingAnchor route, not a pixel jump).

Skips LOUDLY without the extension deps or a Playwright browser (CI installs none); the CI-safe pins ride
ui/webview/scroll-marks.test.ts. Pass NOTCH_CLICK_SHOTS=<path-prefix> for PNGs. All fixtures synthetic.
"""
import json
import os
import re
import shutil
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

SID = "aaaaaaaa-1111-2222-3333-555555555555"
PROMPTS = 5
USER_UUID = "11111111-2222-3333-4444-%012d"       # % k → the k-th prompt's uuid
REPLY_UUID = "22222222-3333-4444-5555-%012d"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


DRIVER = r"""
import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(process.env.EXT_PKG);
const { chromium } = require("playwright");
const cfg = JSON.parse(fs.readFileSync(process.env.CFG, "utf8"));
let browser;
try { browser = await chromium.launch(); }
catch (e) { console.error("browser-launch-failed: " + e); process.exit(3); }
const page = await browser.newPage({ viewport: { width: 1000, height: 600 }, deviceScaleFactor: 2 });
await page.goto(cfg.chat);
await page.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
try { await page.waitForSelector(".scroll-marks .scroll-mark", { timeout: 20000 }); }
catch (e) {
  const st = await page.evaluate(() => ({ turns: document.querySelectorAll(".turn[data-unit]").length,
    box: (document.querySelector(".scroll-marks") || {}).outerHTML || null, sh: document.getElementById("content")?.scrollHeight }));
  console.error("no notch painted: " + JSON.stringify(st)); process.exit(1);
}
await page.waitForTimeout(600);
const first = cfg.firstUuid;
const sel = `.scroll-marks .scroll-mark[data-uuid="${first}"]`;
// what the page holds before any gesture: the notches' dress, the pointer contract, the target's position
const inView = (turn, content) => {
  if (!turn) return false;
  const c = content.getBoundingClientRect(), r = turn.getBoundingClientRect();
  return r.bottom > c.top && r.top < c.bottom;
};
const survey = () => page.evaluate((first) => {
  const content = document.getElementById("content");
  const box = document.querySelector(".scroll-marks");
  const marks = Array.from(document.querySelectorAll(".scroll-marks .scroll-mark"));
  const target = document.querySelector(`.turn[data-uuid="${first}"]`);
  const m0 = marks.find((m) => m.dataset.uuid === first);
  const cs = m0 ? getComputedStyle(m0) : null;
  const c = content.getBoundingClientRect();
  const r = target ? target.getBoundingClientRect() : null;
  return {
    count: marks.length,
    acts: marks.map((m) => m.dataset.act), uuids: marks.map((m) => m.dataset.uuid), titles: marks.map((m) => m.title),
    boxPointer: getComputedStyle(box).pointerEvents,
    notchPointer: cs && cs.pointerEvents, cursor: cs && cs.cursor,
    paint: m0 ? { w: m0.offsetWidth, h: m0.offsetHeight } : null,
    theme: document.body.className,
    targetRendered: !!target,
    targetInView: !!target && r.bottom > c.top && r.top < c.bottom,
    flashed: Array.from(document.querySelectorAll(".turn.anchor-flash")).map((t) => t.dataset.uuid),
  };
}, first);
const before = await survey();
// HOVER (dark theme): the accent ring, the painted size unchanged
await page.hover(sel);
await page.waitForTimeout(120);
const hoverDark = await page.evaluate((sel) => { const m = document.querySelector(sel); const cs = getComputedStyle(m);
  return { shadow: cs.boxShadow, opacity: cs.opacity, w: m.offsetWidth, h: m.offsetHeight, cursor: cs.cursor,
           accent: getComputedStyle(document.body).getPropertyValue("--accent").trim() }; }, sel);
if (cfg.shots) {
  const b = await page.evaluate((sel) => { const r = document.querySelector(sel).getBoundingClientRect(); return { x: r.x, y: r.y }; }, sel);
  await page.screenshot({ path: cfg.shots + "-hover-dark.png" });
  await page.screenshot({ path: cfg.shots + "-hover-dark-zoom.png",
    clip: { x: Math.max(0, b.x - 60), y: Math.max(0, b.y - 40), width: 80, height: 80 } });
}
// HOVER (light theme): the same ring in the light accent
await page.evaluate(() => document.body.classList.add("theme-light"));
await page.mouse.move(5, 5);
await page.hover(sel);
await page.waitForTimeout(120);
const hoverLight = await page.evaluate((sel) => { const m = document.querySelector(sel); const cs = getComputedStyle(m);
  return { shadow: cs.boxShadow, opacity: cs.opacity, w: m.offsetWidth, h: m.offsetHeight, cursor: cs.cursor,
           accent: getComputedStyle(document.body).getPropertyValue("--accent").trim(),
           light: document.body.classList.contains("theme-light") }; }, sel);
if (cfg.shots) await page.screenshot({ path: cfg.shots + "-hover-light.png" });
await page.evaluate(() => document.body.classList.remove("theme-light"));
await page.mouse.move(5, 5);
await page.waitForTimeout(120);
// CLICK the first prompt's notch: the chat lands on that message
await page.click(sel);
let landed = null;
try {
  await page.waitForSelector(`.turn.anchor-flash[data-uuid="${first}"]`, { timeout: 8000 });
  landed = await survey();
} catch (e) {
  landed = await survey();
  landed.error = "no flash landed on the clicked uuid: " + String(e).slice(0, 200);
}
if (cfg.shots) await page.screenshot({ path: cfg.shots + "-landed.png" });
fs.writeSync(1, "RESULT:" + JSON.stringify({ before, hoverDark, hoverLight, landed }) + "\n");
await browser.close();
process.exit(0);
"""


class ServedNotchClickJumps(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(os.path.join(EXT, "node_modules", "playwright")):
            raise unittest.SkipTest("extension deps absent (npm ci not run here) — the served guard needs them")
        cls.lab = tempfile.mkdtemp(prefix="notch-click-")
        b = subprocess.run(["node", "esbuild.js"], cwd=EXT, capture_output=True, text=True)
        if b.returncode != 0:
            raise unittest.SkipTest("esbuild failed here: " + (b.stderr or b.stdout)[-200:])
        dist = os.path.join(cls.lab, "dist")
        shutil.copytree(os.path.join(EXT, "dist"), dist)
        cls.state = os.path.join(cls.lab, "xdg", "romp")
        cwd = os.path.join(cls.lab, "proj")
        for d in ("names", "sdk", "states"):
            os.makedirs(os.path.join(cls.state, d), exist_ok=True)
        os.makedirs(cwd, exist_ok=True)
        Path(cls.state, "names", SID).write_text("web\t%s\t\t\n" % cwd)
        Path(cls.state, "sdk", SID + ".json").write_text(json.dumps(
            {"sid": SID, "name": "web", "cwd": cwd, "mode": "auto", "effort": "high",
             "lastSid": SID, "alive": True, "model": "claude-fable-5-1", "liveModel": "Fable 5.1"}))
        Path(cls.state, "usage.json").write_text(json.dumps({"five_hour": {"pct": 100}, "seven_day": {"pct": 10}}))
        claude = os.path.join(cls.lab, "claude")
        # the kernel finds a session's transcript under Claude's project dir: EVERY non-alphanumeric char of the
        # realpath becomes '-' (jd._proj_dir)
        proj = os.path.join(claude, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd)))
        os.makedirs(proj, exist_ok=True)
        # five prompts, each answered by a long reply: the page opens at the tail, so the FIRST prompt is far
        # above the fold — the notch is the only way to reach it in one gesture
        t0 = "2026-09-07T10:%02d:00.000Z"
        recs = []
        prev = None
        for k in range(PROMPTS):
            u, a = USER_UUID % k, REPLY_UUID % k
            recs.append({"type": "user", "uuid": u, "parentUuid": prev, "timestamp": t0 % (2 * k), "sessionId": SID,
                         "message": {"role": "user", "content": "notes-api: prompt %d, please summarize the retry curve" % k}})
            recs.append({"type": "assistant", "uuid": a, "parentUuid": u, "timestamp": t0 % (2 * k + 1), "sessionId": SID,
                         "message": {"role": "assistant", "model": "claude-fable-5-1", "stop_reason": "end_turn",
                                     "content": [{"type": "text", "text": "\n\n".join("Paragraph %d of reply %d." % (i, k) for i in range(14))}]}})
            prev = a
        Path(proj, SID + ".jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        cls.port = _free_port()
        cls.token = "testtok-notchclick"
        env = dict(os.environ, XDG_STATE_HOME=os.path.join(cls.lab, "xdg"), CLAUDE_CONFIG_DIR=claude,
                   ROMP_MANAGER_PORT="1", ROMP_KERNEL_NO_OPEN="1", ROMP_SERVE_TOKEN=cls.token,
                   ROMP_KERNEL_PORT=str(cls.port), ROMP_DIST_DIR=dist, ROMP_MODEL_CATALOG="off")
        env.pop("ROMP_STATE_DIR", None)
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

    def _drive(self, script, name):
        cfg = os.path.join(self.lab, name + ".json")
        with open(cfg, "w") as f:
            json.dump({"chat": "http://127.0.0.1:%d/chat?token=%s" % (self.port, self.token),
                       "firstUuid": USER_UUID % 0,
                       "shots": os.environ.get("NOTCH_CLICK_SHOTS", "")}, f)
        driver = os.path.join(self.lab, name + ".mjs")
        with open(driver, "w") as f:
            f.write(script)
        p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=240,
                           env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
        if p.returncode == 3:
            raise unittest.SkipTest("no playwright browser on this box — the served guard needs one (CI installs none)")
        self.assertEqual(p.returncode, 0, "driver failed:\n" + p.stdout[-3000:] + p.stderr[-3000:])
        line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT:")), None)
        self.assertIsNotNone(line, "driver printed no result:\n" + p.stdout[-3000:])
        return json.loads(line[len("RESULT:"):])

    def test_a_notch_is_a_link_that_lands_the_chat_on_its_message(self):
        r = self._drive(DRIVER, "click")
        b, hd, hl, landed = r["before"], r["hoverDark"], r["hoverLight"], r["landed"]
        # the dress: one notch per prompt, each a link to its message, with the rail's time on the tip
        self.assertEqual(b["count"], PROMPTS, "one notch per prompt: %r" % b)
        self.assertEqual(b["acts"], ["markjump"] * PROMPTS, "every notch routes the delegated click: %r" % b["acts"])
        self.assertEqual(sorted(b["uuids"]), sorted(USER_UUID % k for k in range(PROMPTS)), "each notch names its message: %r" % b["uuids"])
        for t in b["titles"]:
            self.assertRegex(t, r"\d\d:\d\d", "the tip carries the rail's HH:MM: %r" % t)
            self.assertTrue(t.endswith("click to jump to your message"), "the tip says what a click does: %r" % t)
        # the pointer contract: the box passive over the native scrollbar, the notch a link with the link cursor
        self.assertEqual(b["boxPointer"], "none", "the box never intercepts the scrollbar: %r" % b)
        self.assertEqual(b["notchPointer"], "auto", "the notch takes the pointer: %r" % b)
        self.assertEqual(b["cursor"], "pointer", "the link cursor over a notch: %r" % b)
        self.assertEqual(b["paint"], {"w": 8, "h": 2}, "the painted mark is still 8×2 — the hit box is the pseudo: %r" % b)
        self.assertFalse(b["targetInView"], "the first prompt starts OFF-screen (the page opens at the tail), else the jump proves nothing: %r" % b)
        # hover, both themes: the accent ring (the theme's own accent), full opacity, size unchanged
        for name, h, accent in (("dark", hd, "#9cd2ff"), ("light", hl, "#C2410C")):
            self.assertEqual(h["accent"].lower(), accent.lower(), "%s theme accent token resolved: %r" % (name, h))
            rgb = "rgb(%d, %d, %d)" % tuple(int(accent[i:i + 2], 16) for i in (1, 3, 5))
            self.assertIn(rgb, h["shadow"], "%s hover ring is the accent: %r" % (name, h))
            self.assertIn("1.5px", h["shadow"], "%s hover ring is a ring, not a fill: %r" % (name, h))
            self.assertEqual(h["opacity"], "1", "%s hover lifts the notch to full opacity: %r" % (name, h))
            self.assertEqual((h["w"], h["h"]), (8, 2), "%s hover keeps the painted size: %r" % (name, h))
            self.assertEqual(h["cursor"], "pointer", "%s theme: link cursor: %r" % (name, h))
        self.assertTrue(hl["light"], "the light theme was on for the light hover: %r" % hl)
        # THE CLICK: the chat landed on the clicked message — rendered, in view, wearing the deep-link flash
        self.assertNotIn("error", landed, "landing: %r" % landed)
        self.assertTrue(landed["targetRendered"], "the target turn is rendered after the click: %r" % landed)
        self.assertTrue(landed["targetInView"], "…and in view: %r" % landed)
        self.assertIn(USER_UUID % 0, landed["flashed"], "the flash (one per navigation) sits on the clicked message: %r" % landed["flashed"])
        self.assertEqual(landed["count"], PROMPTS, "the notches survived the landing paint: %r" % landed)


if __name__ == "__main__":
    unittest.main()
