#!/usr/bin/env python3
"""T252 (the user 2026-09-07): a message sent while the session is mid-turn appears where it was sent and
stays there. The pending bubble is drawn at its SEND POSITION from the first paint — right after the last
kernel event at the press — so the steps that stream in afterwards land below it, and the absorbed atom the
kernel places at the send time replaces it in the same spot. No "joined mid-turn" header, no jump/✕ cue.

The executed guard drives the real /chat page against a hermetic kernel: the socket's outbound send is
dropped in the page (the message never reaches the kernel, so nothing parks or echoes — the client's bubble
is the only copy, which is the case under test), the composer sends, two tool steps are appended to the
transcript, and then the CLI's own record of a mid-turn splice — a `queued_command` attachment stamped with
the SEND time — lands the atom above those steps. Asserted: the bubble's position in scroll space never
changes while steps stream in below it; a scrolled-up reader is not moved; the landed message takes the
bubble's slot; no header and no cue exist at any point. Red on main: the bubble rode the tail, so it moved
below the streamed steps and the landing appeared higher up with a header and a cue.

Skips LOUDLY without the extension deps or a Playwright browser (CI installs none). SYNTHETIC fixtures only.
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
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
EXT = os.path.join(ROOT, "vscode-extension")

SID = "aaaaaaaa-1111-2222-3333-444444444444"
TEXT = "and also update the docstring"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


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
try { await page.waitForSelector(".turn.turn-user", { timeout: 20000 }); }
catch (e) {   // say what the page held instead of a bare timeout
  const st = await page.evaluate(() => ({ turns: Array.from(document.querySelectorAll(".turn")).map((t) => t.className.slice(5, 40)),
    threads: Array.from(document.querySelectorAll(".thread")).map((t) => (t.style.display || "shown") + "/" + t.childElementCount),
    tabs: (document.getElementById("tabs") || {}).textContent, text: (document.body.innerText || "").replace(/\s+/g, " ").slice(0, 200) }));
  console.error("no user turn rendered: " + JSON.stringify(st)); process.exit(1);
}
await page.waitForTimeout(600);
// the send never reaches the kernel: the client's bubble is the only copy of the message
await page.evaluate(() => {
  const orig = WebSocket.prototype.send;
  window.__dropped = 0;
  WebSocket.prototype.send = function (d) {
    try { const m = JSON.parse(d); if (m && m.type === "sendMessage") { window.__dropped++; return; } } catch (e) {}
    return orig.call(this, d);
  };
});
const measure = () => page.evaluate((text) => {
  const content = document.getElementById("content");
  const c = content.getBoundingClientRect();
  const yOf = (n) => Math.round(content.scrollTop + n.getBoundingClientRect().top - c.top);
  const turns = Array.from(document.querySelectorAll(".turn[data-unit]"));
  const pending = document.querySelector(".turn-queued");
  const landed = turns.find((t) => t.classList.contains("turn-user") && (t.textContent || "").includes(text)) || null;
  const tools = turns.filter((t) => t.classList.contains("turn-tool") || t.classList.contains("turn-toolgroup"));
  return {
    scrollTop: content.scrollTop, scrollHeight: content.scrollHeight,
    pending: pending ? { y: yOf(pending), unit: Number(pending.dataset.unit), idx: turns.indexOf(pending) } : null,
    landed: landed ? { y: yOf(landed), unit: Number(landed.dataset.unit), idx: turns.indexOf(landed) } : null,
    toolIdx: tools.map((t) => turns.indexOf(t)),
    header: document.querySelectorAll(".absorbed-tag").length, cue: document.querySelectorAll(".turn-absorbed-cue").length,
    dropped: window.__dropped,
  };
}, cfg.text);
await page.fill("#composer-input", cfg.text);
await page.press("#composer-input", "Enter");
await page.waitForSelector(".turn-queued", { timeout: 10000 });
await page.waitForTimeout(300);
const pressed = await measure();
// a scrolled-up reader: nothing that follows may move the viewport
await page.evaluate(() => { const c = document.getElementById("content"); c.scrollTop = Math.max(0, c.scrollTop - 150); });
await page.waitForTimeout(200);
const scrolled = await measure();
// two tool steps stream in while the CLI holds the send
// the steps are on the page when the transcript's unit classes change (compact mode folds consecutive tools:
// on main all three Bashes fold into one group; with the fix the bubble splits the run into a lone tool and a group)
const classesOf = () => page.evaluate(() => JSON.stringify(Array.from(document.querySelectorAll(".turn[data-unit]")).map((t) => t.className)));
const beforeSteps = await classesOf();
fs.appendFileSync(cfg.transcript, cfg.steps.map((r) => JSON.stringify(r)).join("\n") + "\n");
await page.waitForFunction((was) => JSON.stringify(Array.from(document.querySelectorAll(".turn[data-unit]")).map((t) => t.className)) !== was, beforeSteps, { timeout: 20000 });
await page.waitForTimeout(500);
const streamed = await measure();
// shots show the tail (the reader's scroll position was already measured); the landing below does not read scrollTop
const shot = async (name) => { if (!cfg.shots) return; await page.evaluate(() => { const c = document.getElementById("content"); c.scrollTop = c.scrollHeight; }); await page.waitForTimeout(150); await page.screenshot({ path: cfg.shots + name }); };
await shot("-pending.png");
// the CLI takes it at the boundary: its attachment record carries the SEND time, so the atom lands above the steps
fs.appendFileSync(cfg.transcript, JSON.stringify(cfg.landing) + "\n");
await page.waitForFunction((text) => Array.from(document.querySelectorAll(".turn.turn-user")).some((t) => (t.textContent || "").includes(text)), cfg.text, { timeout: 20000 });
await page.waitForTimeout(500);
const landed = await measure();
await shot("-landed.png");
fs.writeSync(1, "RESULT:" + JSON.stringify({ pressed, scrolled, streamed, landed }) + "\n");
await browser.close();
process.exit(0);
"""


class ServedPendingInPlace(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(os.path.join(EXT, "node_modules", "playwright")):
            raise unittest.SkipTest("extension deps absent (npm ci not run here) — the served guard needs them")
        cls.lab = tempfile.mkdtemp(prefix="pending-in-place-")
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
        Path(cls.state, "usage.json").write_text(json.dumps({"five_hour": {"pct": 10}, "seven_day": {"pct": 10}}))
        claude = os.path.join(cls.lab, "claude")
        # the kernel finds a session's transcript under Claude's project dir: EVERY non-alphanumeric char of the
        # realpath becomes '-' (jd._proj_dir). A slashes-only munge missed the '_' pytest's temp root can carry,
        # so the kernel found no transcript and drew an API-error turn instead (the batch-only flake, 2026-09-08).
        proj = os.path.join(claude, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd)))
        os.makedirs(proj, exist_ok=True)
        # a running turn: the reply is tall enough to overflow the pane, then a tool call whose result is in
        t0 = int(time.time()) - 900
        cls.t0 = t0
        recs = [
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
        ]
        cls.transcript = os.path.join(proj, SID + ".jsonl")
        Path(cls.transcript).write_text("".join(json.dumps(r) + "\n" for r in recs))
        # the steps the session runs while the send waits, and the splice the CLI writes when it takes it
        cls.steps = [
            {"type": "assistant", "timestamp": iso(t0 + 60), "uuid": "a3", "parentUuid": "tr1", "sessionId": SID,
             "message": {"role": "assistant", "model": "claude-fable-5-1", "stop_reason": "tool_use",
                         "content": [{"type": "tool_use", "id": "tu_a3_0", "name": "Bash", "input": {"command": "uv run pytest -q tests/test_search.py"}}]}},
            {"type": "user", "timestamp": iso(t0 + 61), "uuid": "tr2", "parentUuid": "a3", "sessionId": SID,
             "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu_a3_0", "content": "5 passed"}]}},
            {"type": "assistant", "timestamp": iso(t0 + 62), "uuid": "a4", "parentUuid": "tr2", "sessionId": SID,
             "message": {"role": "assistant", "model": "claude-fable-5-1", "stop_reason": "tool_use",
                         "content": [{"type": "tool_use", "id": "tu_a4_0", "name": "Bash", "input": {"command": "git diff --stat"}}]}},
            {"type": "user", "timestamp": iso(t0 + 63), "uuid": "tr3", "parentUuid": "a4", "sessionId": SID,
             "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu_a4_0", "content": "1 file changed"}]}},
        ]
        cls.landing = {"type": "attachment", "timestamp": iso(t0 + 55), "uuid": "att1", "parentUuid": "tr3", "isSidechain": False,
                       "sessionId": SID, "attachment": {"type": "queued_command", "prompt": TEXT}}
        cls.port = _free_port()
        cls.token = "testtok-pendinginplace"
        env = dict(os.environ, XDG_STATE_HOME=os.path.join(cls.lab, "xdg"), CLAUDE_CONFIG_DIR=claude,
                   ROMP_MANAGER_PORT="1", ROMP_KERNEL_NO_OPEN="1", ROMP_SERVE_TOKEN=cls.token,
                   ROMP_KERNEL_PORT=str(cls.port), ROMP_DIST_DIR=dist, ROMP_MODEL_CATALOG="off")
        for k in ("ROMP_STATE_DIR", "ROMP_API_KEY_CMD", "ANTHROPIC_API_KEY"):
            env.pop(k, None)
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

    def test_the_pending_bubble_holds_its_send_position_and_the_landing_replaces_it_in_place(self):
        cfg = os.path.join(self.lab, "cfg.json")
        with open(cfg, "w") as f:
            json.dump({"chat": "http://127.0.0.1:%d/chat?token=%s" % (self.port, self.token), "text": TEXT,
                       "transcript": self.transcript, "steps": self.steps, "landing": self.landing,
                       "shots": os.environ.get("PENDING_IN_PLACE_SHOTS", "")}, f)
        driver = os.path.join(self.lab, "driver.mjs")
        with open(driver, "w") as f:
            f.write(DRIVER)
        p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=240,
                           env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
        if p.returncode == 3:
            raise unittest.SkipTest("no playwright browser on this box — the served guard needs one (CI installs none)")
        self.assertEqual(p.returncode, 0, "driver failed:\n" + p.stdout[-3000:] + p.stderr[-3000:] + "\nkernel:\n" + open(self.klog).read()[-1500:])
        line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT:")), None)
        self.assertIsNotNone(line, "driver printed no result:\n" + p.stdout[-3000:])
        r = json.loads(line[len("RESULT:"):])
        pr, sc, st, ld = r["pressed"], r["scrolled"], r["streamed"], r["landed"]
        self.assertEqual(pr["dropped"], 1, "the send was dropped at the socket: the client's bubble is the only copy (%r)" % pr)
        self.assertIsNotNone(pr["pending"], "the press drew the pending bubble: %r" % pr)
        self.assertEqual(pr["header"] + pr["cue"] + st["header"] + st["cue"] + ld["header"] + ld["cue"], 0,
                         "no 'joined mid-turn' header and no cue at any point: %r" % r)
        # THE RULE: the bubble keeps its slot while steps stream in below it
        self.assertIsNotNone(st["pending"], "still pending after the steps: %r" % st)
        self.assertEqual(st["pending"]["y"], pr["pending"]["y"],
                         "the bubble did not move in scroll space: pressed at %r, after the steps %r" % (pr["pending"], st["pending"]))
        new_tools = [i for i in st["toolIdx"] if i not in pr["toolIdx"]] or st["toolIdx"][-1:]
        self.assertTrue(all(i > st["pending"]["idx"] for i in new_tools), "the streamed steps sit BELOW the bubble: %r" % st)
        self.assertEqual(st["scrollTop"], sc["scrollTop"], "a scrolled-up reader is not moved by the steps: %r → %r" % (sc["scrollTop"], st["scrollTop"]))
        # the landing takes the bubble's slot
        self.assertIsNone(ld["pending"], "the landing retired the bubble: %r" % ld)
        self.assertIsNotNone(ld["landed"], "the landed message is on the page: %r" % ld)
        self.assertEqual(ld["landed"]["idx"], st["pending"]["idx"], "same slot in the transcript: bubble %r, landed %r" % (st["pending"], ld["landed"]))
        self.assertLessEqual(abs(ld["landed"]["y"] - st["pending"]["y"]), 40,
                             "same place on the page (the bare group's one-line head is the only difference): bubble y %r, landed y %r" % (st["pending"]["y"], ld["landed"]["y"]))


if __name__ == "__main__":
    unittest.main()
