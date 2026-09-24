#!/usr/bin/env python3
"""A solo /clear on a session with NO conversation, run END TO END through the REAL kernel + the fake Agent
SDK, ends CLEAN: once the clear has run, no stuck dashed /clear bubble and no "Clearing conversation..." row
remain, and the /clear shows as a LANDED command row.

History: this scene was first written for PR 2103's follow-up as a red-first reproduction for a suspected
KERNEL bug, the empty-build refusal re-asserting the pre-clear state.
A contributor's runs of the real CLI 2.1.280 corrected that: the CLI writes a fresh-episode record GROUP (a
session caveat, the /clear command-name wrapper, and a local-command-stdout record) within milliseconds of
the fresh episode's init. The earlier synthetic fake SDK wrote NONE of those, so its fresh episode was empty
and the empty-build refusal held the stale state. The leftover was the FIXTURE's gap, not a product bug.

With the fake SDK now writing the CLI's record group (tests/fixtures/fake_agent_sdk), this scene ends on a
ready frame with the /clear a landed command row, in every run, so it is a GREEN regression test, not a
red-first: no kernel change is warranted for the clear-to-empty case. (The real CLI additionally refuses to
RESUME a truly empty transcript, so a live empty-session /clear takes a different path; the user's own
reported leftover remains the province of the 2103 diagnostic trap, not this fixture scene.) SYNTHETIC
fixtures only; skips LOUDLY without the extension deps or a browser.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
EXT = os.path.join(ROOT, "vscode-extension")
FAKE_SDK = os.path.join(HERE, "fixtures", "fake_agent_sdk")
sys.path.insert(0, HERE)
import test_ship_reship_served as _lab   # noqa: E402  the lab kernel's environment (kernel_env)
from test_queued_rescind_browser import _free_port, iso   # noqa: E402
from tests.dist_copy import copy_dist   # noqa: E402

SID = "aaaaaaaa-1111-2222-3333-444444444444"

DRIVER = r"""
import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(process.env.EXT_PKG);
const { chromium } = require("playwright");
const cfg = JSON.parse(fs.readFileSync(process.env.CFG, "utf8"));
let browser;
try { browser = await chromium.launch(); }
catch (e) { console.error("browser-launch-failed: " + e); process.exit(3); }
const page = await browser.newPage({ viewport: { width: 1000, height: 760 } });
page.on("console", (m) => { if (m.type() === "error") fs.appendFileSync(cfg.consoleLog, m.text() + "\n"); });
await page.addInitScript(() => {
  window.__sent = []; window.__frames = [];
  window.addEventListener("message", (e) => { const m = e.data; if (m && m.type) window.__frames.push({ type: m.type, state: m.status && m.status.state, kinds: Array.isArray(m.events) ? m.events.map((x) => x.kind).filter(Boolean) : null }); });
  const s = WebSocket.prototype.send;
  WebSocket.prototype.send = function (d) { try { const m = JSON.parse(d); if (m && m.type === "sendMessage") window.__sent.push({ text: m.text, qid: m.qid }); } catch (e) {} return s.call(this, d); };
});
await page.goto(cfg.chat);
await page.waitForSelector("#composer-input", { timeout: 20000 });
await page.waitForFunction(() => (window.__frames || []).some((f) => f.type === "session"), null, { timeout: 20000 }).catch((e) => { if (e.name !== "TimeoutError") throw e; });
// a SOLO /clear on an EMPTY conversation (no open cards, so no confirm)
await page.fill("#composer-input", "/clear"); await page.press("#composer-input", "Enter");
const btn = await page.$("button.confirm-btn.danger, .confirm button.danger"); if (btn) await btn.click();
await page.waitForFunction(() => (window.__sent || []).some((x) => x.text === "/clear"), null, { timeout: 8000 });
// IN FLIGHT: the dashed /clear bubble is on the page (the fake holds the clear on the gate file)
await page.waitForFunction(() => Array.from(document.querySelectorAll("#content .turn-queued .queued-bubble, #content .turn.echo")).some((b) => (b.textContent || "").indexOf("/clear") >= 0), null, { timeout: 8000 }).catch((e) => { if (e.name !== "TimeoutError") throw e; });
const mid = await page.evaluate(() => ({
  clearBubble: Array.from(document.querySelectorAll("#content .turn-queued .queued-bubble, #content .turn.echo")).some((b) => (b.textContent || "").indexOf("/clear") >= 0),
  clearingRow: !!document.querySelector("#content .turn-clearing"),
}));
// RELEASE the in-flight clear on an EVENT (the gate file), now the in-flight snapshot is read; the fake SDK
// waits on this file before running the /clear
fs.writeFileSync(cfg.gate, "");
// POLL, event-based, for the settled state: the /clear LANDED as a command row (.turn-cmd), the fresh
// episode the CLI's record group produces. Then one animation frame so the paint has settled. In the
// (unexpected) defect the row never lands, the poll times out, and the after read below still tells them
// apart: the stuck /clear bubble is then present.
await page.waitForFunction(() => Array.from(document.querySelectorAll("#content .turn.turn-cmd")).some((t) => (t.textContent || "").indexOf("/clear") >= 0), null, { timeout: 30000 }).catch((e) => { if (e.name !== "TimeoutError") throw e; });
await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r())));
const after = await page.evaluate(() => {
  const txt = (el) => (el.textContent || "");
  return {
    // the STUCK forms only (the optimistic pending chip, the kernel echo), never the landed command row
    clearStuck: Array.from(document.querySelectorAll("#content .turn-queued .slash-cmd-chip, #content .turn.echo")).some((b) => txt(b).indexOf("/clear") >= 0),
    clearLanded: Array.from(document.querySelectorAll("#content .turn.turn-cmd")).some((t) => txt(t).indexOf("/clear") >= 0),
    clearingRow: !!document.querySelector("#content .turn-clearing"),
    clearingText: Array.from(document.querySelectorAll("#content .turn, #content .notice, #statusline, #status-chip")).some((el) => txt(el).indexOf("Clearing conversation") >= 0),
    turnTexts: Array.from(document.querySelectorAll("#content .turn")).map((t) => txt(t).trim().slice(0, 80)),
    pill: (document.getElementById("status-chip") || {}).textContent || "",
    composer: (document.getElementById("composer-input") || {}).value || "",
  };
});
const frames = await page.evaluate(() => window.__frames || []);
await browser.close();
process.stdout.write("RESULT:" + JSON.stringify({ mid, after, frames }) + "\n", () => process.exit(0));
"""


class ClearEmptySessionEndsClean(unittest.TestCase):
    """GREEN regression: a solo /clear on an empty session, driven through the real kernel against the
    CLI-shaped fake SDK, ends with no stuck /clear bubble and no clearing row; the /clear is a landed command
    row. The leftover the earlier synthetic fixture showed was the fixture's gap, not a kernel bug."""
    maxDiff = None
    _r = None

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(os.path.join(EXT, "node_modules", "playwright")):
            raise unittest.SkipTest("extension deps absent (npm ci not run here), the served guard needs them")
        cls.lab = tempfile.mkdtemp(prefix="clear-empty-clean-")
        b = subprocess.run(["node", "esbuild.js"], cwd=EXT, capture_output=True, text=True)
        if b.returncode != 0:
            raise unittest.SkipTest("esbuild failed here: " + (b.stderr or b.stdout)[-200:])
        dist = os.path.join(cls.lab, "dist")
        copy_dist(os.path.join(EXT, "dist"), dist)
        cls.state = os.path.join(cls.lab, "xdg", "romp")
        cwd = os.path.join(cls.lab, "proj")
        for d in ("names", "sdk", "states"):
            os.makedirs(os.path.join(cls.state, d), exist_ok=True)
        Path(cls.state, "session-hosts").write_text("off")   # our own state root: no real host for the session
        os.makedirs(cwd, exist_ok=True)
        Path(cls.state, "names", SID).write_text("web\t%s\t\t\n" % cwd)
        Path(cls.state, "sdk", SID + ".json").write_text(json.dumps(
            {"sid": SID, "name": "web", "cwd": cwd, "mode": "auto", "effort": "high",
             "lastSid": SID, "alive": True, "model": "claude-fable-5-1", "liveModel": "Fable 5.1"}))
        Path(cls.state, "usage.json").write_text(json.dumps({"five_hour": {"pct": 10}, "seven_day": {"pct": 10}}))
        claude = os.path.join(cls.lab, "claude")
        proj = os.path.join(claude, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd)))
        os.makedirs(proj, exist_ok=True)
        Path(proj, SID + ".jsonl").write_text("")   # an EMPTY conversation: no turns, so the solo /clear forks nothing
        cls.port = _free_port()
        cls.token = "testtok-clearempty-clean"
        cls.gate = os.path.join(cls.lab, "clear-gate")   # the fake SDK waits on this file before running the /clear
        env = _lab.kernel_env(cls.lab, claude, dist, cls.port, cls.token,
                              PYTHONPATH=FAKE_SDK, ROMP_FAKE_SDK_REPLY="(cleared)",
                              ROMP_FAKE_SDK_GATE=cls.gate)   # an event, not a timer
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

    def _result(self):
        cls = type(self)
        if cls._r is None:
            cfg = os.path.join(self.lab, "cfg.json")
            console_log = os.path.join(self.lab, "console.log")
            open(console_log, "w").close()
            with open(cfg, "w") as f:
                json.dump({"chat": "http://127.0.0.1:%d/chat?token=%s" % (self.port, self.token),
                           "gate": self.gate, "consoleLog": console_log}, f)
            driver = os.path.join(self.lab, "driver.mjs")
            with open(driver, "w") as f:
                f.write(DRIVER)
            p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=300,
                               env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
            if p.returncode == 3:
                raise unittest.SkipTest("no playwright browser on this box (CI installs none)")
            self.assertEqual(p.returncode, 0, "driver failed:\n" + p.stdout[-3000:] + p.stderr[-3000:] + "\nkernel:\n" + open(self.klog).read()[-2000:])
            line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT:")), None)
            self.assertIsNotNone(line, "driver printed no result:\n" + p.stdout[-3000:])
            cls._r = json.loads(line[len("RESULT:"):])
        print("RESULT:" + json.dumps(cls._r), file=sys.stderr)
        return cls._r

    def test_a_solo_clear_on_an_empty_session_ends_clean(self):
        r = self._result()
        self.assertTrue(r["mid"]["clearBubble"], "the dashed /clear bubble is on the page while the clear is in flight: " + json.dumps(r["mid"]))
        a = r["after"]
        table = "\n  after=" + json.dumps(a)
        # With the CLI-shaped fixture the /clear LANDS as a command row and nothing stays stuck. (Under the
        # earlier record-less fixture the fresh episode was empty, the empty-build refusal held the stale
        # state, and a stuck /clear bubble + clearing row remained: the FIXTURE's gap, now closed.)
        self.assertTrue(a["clearLanded"], "the /clear is a LANDED command row (the CLI's command-name record)" + table)
        self.assertFalse(a["clearStuck"], "no STUCK '/clear' (optimistic chip or kernel echo) remains once the clear has run" + table)
        self.assertFalse(a["clearingRow"], "the 'Clearing conversation...' row is gone once the clear has run" + table)
        self.assertFalse(a["clearingText"], "no 'Clearing conversation...' text anywhere after the clear ran" + table)


if __name__ == "__main__":
    unittest.main()
