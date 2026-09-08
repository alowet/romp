#!/usr/bin/env python3
"""T245 (the user 2026-09-07): the chat scrollbar's blue user-message notches drifted once a turn with many
inline figures was on screen — a notch sat well below the thumb while the message it marked was in view.

Convicted at the source: contentOffsetFrame is a virtual prefix-sum over cached measured unit heights, and
the cache is refreshed only inside a paint (paintScrollMarks ← scheduleRailSticky's rAF, whose triggers are
scroll, resize and a few render-side callers). previewFull's figures are lazy, async-decoded images with
no intrinsic size before load, so every figure that loads after the paint grows its turn and the content's
scrollHeight with NO repaint: the native thumb moves to the new truth while the notches keep the stale,
smaller frame. Nothing keyed the paint on "a rendered unit changed height".

The executed guard here drives the real /chat page: after the first paint a rendered turn GROWS (a block
appended to the last turn — the same thing a late figure does), and the user message's notch must follow
the scrollbar's truth (red on main: the notch stays where the stale frame put it). Skips LOUDLY without the
extension deps or a Playwright browser (CI installs none); the CI-safe pins ride
ui/webview/scroll-marks.test.ts. All fixtures synthetic.
"""
import json
import os
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

SID = "aaaaaaaa-1111-2222-3333-444444444444"


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
const page = await browser.newPage({ viewport: { width: 1000, height: 600 } });
await page.goto(cfg.chat);
await page.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
await page.waitForSelector(".scroll-marks .scroll-mark", { timeout: 20000 });
await page.waitForTimeout(600);
const measure = () => page.evaluate(() => {
  const content = document.getElementById("content");
  const c = content.getBoundingClientRect();
  const marks = Array.from(document.querySelectorAll(".scroll-marks .scroll-mark")).map((m) => parseFloat(m.style.top));
  // the FIRST user turn's slot middle in scroll space, as the scrollbar sees it
  const turn = document.querySelector(".turn.turn-user[data-unit]");
  const tr = turn.getBoundingClientRect();
  const mid = content.scrollTop + (tr.top - c.top) + tr.height / 2;
  const expected = Math.round((mid / content.scrollHeight) * (c.height - 4));
  return { marks, expected, scrollHeight: content.scrollHeight, turns: document.querySelectorAll(".turn[data-unit]").length };
});
const before = await measure();
// a rendered unit GROWS after the paint — exactly what a late-loading figure does to its turn
await page.evaluate(() => {
  const turns = document.querySelectorAll(".turn[data-unit]");
  const last = turns[turns.length - 1];
  const block = document.createElement("div");
  block.style.height = "1500px"; block.textContent = "late figure stand-in";
  last.appendChild(block);
});
await page.waitForTimeout(400);            // several frames — the repaint is event-keyed, not timed; this is slack
const after = await measure();
if (cfg.shots) await page.screenshot({ path: cfg.shots + "-after-growth.png" });
fs.writeSync(1, "RESULT:" + JSON.stringify({ before, after }) + "\n");
await browser.close();
process.exit(0);
"""


class ServedNotchFollowsGrowth(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(os.path.join(EXT, "node_modules", "playwright")):
            raise unittest.SkipTest("extension deps absent (npm ci not run here) — the served guard needs them")
        cls.lab = tempfile.mkdtemp(prefix="notch-growth-")
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
        proj = os.path.join(claude, "projects", cwd.replace("/", "-"))
        os.makedirs(proj, exist_ok=True)
        # a user message near the top, then a tall-ish assistant reply — the notch marks the user turn
        t0 = "2026-09-07T00:00:%02d.000Z"
        recs = [{"type": "user", "uuid": "11111111-2222-3333-4444-555555555555", "parentUuid": None,
                 "timestamp": t0 % 0, "sessionId": SID, "message": {"role": "user", "content": "plot the retry curve"}},
                {"type": "assistant", "uuid": "22222222-3333-4444-5555-666666666666",
                 "parentUuid": "11111111-2222-3333-4444-555555555555", "timestamp": t0 % 5, "sessionId": SID,
                 "message": {"role": "assistant", "model": "claude-fable-5-1", "stop_reason": "end_turn",
                             "content": [{"type": "text", "text": "\n\n".join("Paragraph %d of the reply." % i for i in range(12))}]}}]
        Path(proj, SID + ".jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        cls.port = _free_port()
        cls.token = "testtok-notchgrowth"
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

    def test_a_notch_follows_its_message_when_a_rendered_turn_grows_after_the_paint(self):
        cfg = os.path.join(self.lab, "cfg.json")
        with open(cfg, "w") as f:
            json.dump({"chat": "http://127.0.0.1:%d/chat?token=%s" % (self.port, self.token),
                       "shots": os.environ.get("NOTCH_GROWTH_SHOTS", "")}, f)
        driver = os.path.join(self.lab, "driver.mjs")
        with open(driver, "w") as f:
            f.write(DRIVER)
        p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=240,
                           env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
        if p.returncode == 3:
            raise unittest.SkipTest("no playwright browser on this box — the served guard needs one (CI installs none)")
        self.assertEqual(p.returncode, 0, "driver failed:\n" + p.stdout[-3000:] + p.stderr[-3000:])
        line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT:")), None)
        self.assertIsNotNone(line, "driver printed no result:\n" + p.stdout[-3000:])
        r = json.loads(line[len("RESULT:"):])
        b, a = r["before"], r["after"]
        self.assertEqual(len(b["marks"]), 1, "one notch: the one user message (%r)" % b)
        self.assertGreater(a["scrollHeight"], b["scrollHeight"] + 1000, "the rendered turn did grow: %r → %r" % (b["scrollHeight"], a["scrollHeight"]))
        d_before = abs(b["marks"][0] - b["expected"])
        d_after = abs(a["marks"][0] - a["expected"])
        # THE FIX, two halves in one verdict so the evidence carries both numbers: (1) with every unit rendered
        # the frame is the scrollbar's own truth (on main the notch sat off its message by the turn gaps the
        # unit-height sum omits); (2) after a rendered unit grows — no scroll, no resize, no new event — the
        # notch follows (on main it stayed on the stale frame's position)
        self.assertTrue(d_before <= 3 and d_after <= 3,
                        "notch vs its message — before growth: notch %r expected %r (off by %d); after growth: notch %r expected %r (off by %d)"
                        % (b["marks"], b["expected"], d_before, a["marks"], a["expected"], d_after))


if __name__ == "__main__":
    unittest.main()
