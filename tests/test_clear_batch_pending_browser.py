#!/usr/bin/env python3
"""A /clear sent in a batch with a message, run END TO END through the REAL kernel + a FAKE Agent SDK, must
leave NO stuck rows once the clear has run: no "Clearing conversation…" row, no dashed /clear chip, no
"sending…" group, and the message present only as its LANDED row beside the reply and the boundary card.

The user's report (chat page): sending a `/clear` and a text message TOGETHER in one batch left the
transcript stuck with FOUR un-retired elements while the agent's reply rendered below and the status pill
read Ready: (1) a "Clearing conversation…" SESSION row with its spinner, (2) a dashed pending /clear chip,
(3) a "sending…" group, and (4) the message still a dashed pending bubble.

Unlike the first cut of this lab, which HAND-INJECTED the fresh-episode frames (its base already had the
clearing row gone and the message landed, so it could only red on the chip and the sending group), this
lab boots a hermetic kernel over an IDLE session and drives a REAL /clear+message batch through the real
SdkBackend against a fake `claude_agent_sdk` (tests/fixtures/fake_agent_sdk) that actually processes the
clear (its init flips lastSid to a fresh episode) and answers the message (it writes the CLI's transcript
records, which the kernel lands and renders through its real parse path). So the fresh-episode scene, the
Ready pill, the clear boundary card and every retirement come from the kernel itself.

What the real kernel path shows (and the first, injected cut could not): the FOUR report elements appear
together WHILE the clear runs (the `mid` snapshot, held there by the gate the fake SDK waits on), the "Clearing
conversation…" row, the dashed /clear chip, and the message's dashed pending bubble. Once the clear has
run, the fresh-episode arrives as a full `session` frame that REPLACES the view, so the "Clearing
conversation…" row and the message's pending bubble are dropped by that replacement and the message lands
as its own row: those two are UNREPRODUCED as PERSISTENT rows here (the after-assertions guard that they
are gone). At the base the /clear PERSISTS, dressed "sending…": the CLIENT's own optimistic bubble and the
kernel's own /clear echo. The fix ends both: the client retires the /clear bubble at the CLEAR BOUNDARY
(the fresh episode) and the kernel retires its echo by the taken copy's qid, while the CLI-shaped fixture
writes the /clear's command-name record so it LANDS as a command row. `clearStuck` is the reliable
regression signal: it matches only the two STUCK forms (the optimistic chip, the kernel echo), never the
landed command row, so it is RED at the base (a stuck /clear rides on) and green after.
SYNTHETIC fixtures only; skips LOUDLY without the extension deps or a browser.
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

# Hermetic state BEFORE any romp-code load below: romp modules resolve their state root at import
# time and only pytest runs conftest's floor, so a bare unittest or script run would otherwise write
# REAL ~/.local/state/romp (test_state_isolation_order.py is the ratchet).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel exports it to its sessions; it outranks the XDG floor

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
MSG = "please rebuild the notes-api search index"
REPLY = "Rebuilt the notes-api search index; three shards refreshed."

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
page.on("pageerror", (e) => fs.appendFileSync(cfg.consoleLog, "pageerror: " + e + "\n"));
// record every sendMessage frame's press-id (qid); nothing is held back, the real kernel drives every push
await page.addInitScript(() => {
  window.__sent = []; window.__frames = [];
  window.addEventListener("message", (e) => { const m = e.data; if (m && m.type) window.__frames.push({ type: m.type, state: m.status && m.status.state, hasEvents: Array.isArray(m.events), kinds: Array.isArray(m.events) ? m.events.map((x) => x.kind).filter(Boolean) : null }); });
  const origSend = WebSocket.prototype.send;
  WebSocket.prototype.send = function (d) { try { const m = JSON.parse(d); if (m && m.type === "sendMessage") window.__sent.push({ text: m.text, qid: m.qid }); } catch (e) {} return origSend.call(this, d); };
});
await page.goto(cfg.chat);
await page.waitForSelector("#tabs .tab, #tabs [data-sid]", { timeout: 20000 });
await page.waitForSelector("#composer-input", { timeout: 20000 });
// the session is IDLE: wait for its first real session frame (the seeded pre-clear turn)
await page.waitForSelector(".turn.turn-user", { timeout: 20000 });
await page.waitForTimeout(500);

// the batch: /clear then the message, two Enters in the same second. With no open cards there is no confirm.
const send = async (text) => { await page.fill("#composer-input", text); await page.press("#composer-input", "Enter");
  const btn = await page.$("button.confirm-btn.danger, .confirm button.danger"); if (btn) await btn.click(); };
await send("/clear");
await send(cfg.msg);
await page.waitForFunction(() => (window.__sent || []).some((s) => s.text === "/clear") && (window.__sent || []).some((s) => s.text.indexOf("rebuild") >= 0), null, { timeout: 8000 });
const qids = await page.evaluate((msg) => ({
  clear: ((window.__sent || []).find((s) => s.text === "/clear") || {}).qid,
  msg: ((window.__sent || []).find((s) => s.text === msg) || {}).qid,
}), cfg.msg);

// the IN-FLIGHT state (the report's starting point): the "Clearing conversation…" row is up and the
// message is a dashed pending bubble, WHILE the clear is still running (the fake SDK holds it in flight on the gate file)
await page.waitForSelector("#content .turn-clearing", { timeout: 8000 }).catch(() => {});
const mid = await page.evaluate((msg) => {
  const txt = (el) => (el.textContent || "");
  const chip = document.getElementById("status-chip");
  return {
    clearingRow: !!document.querySelector("#content .turn-clearing"),
    clearingText: Array.from(document.querySelectorAll("#content .turn, #content .notice")).some((el) => txt(el).indexOf("Clearing conversation") >= 0),
    clearChip: Array.from(document.querySelectorAll("#content .turn-queued .slash-cmd-chip, #content .turn.echo")).some((c) => txt(c).indexOf("/clear") >= 0),
    msgBubble: Array.from(document.querySelectorAll("#content .turn-queued .queued-bubble, #content .turn.echo .user-bubble")).some((b) => txt(b).indexOf(msg) >= 0),
    pill: chip ? (chip.textContent || "").trim() : "",
  };
}, cfg.msg);

// RELEASE the in-flight clear on an EVENT, now that the in-flight snapshot is read: the fake SDK is
// waiting on this file, so creating it is what lets the /clear run; no timer decides the timing.
fs.writeFileSync(cfg.gate, "");
// Before reading, WAIT on the FRAMES so the after-read never races the paint (with the 800ms settle gone it
// could read before the base's stuck chip was drawn, a false green there in a few runs of many). Wait until
// the recorded frames show a chatTail arriving AFTER the last clear-card session frame (the fresh episode's
// full replace), then ONE animation frame, so the settled tail (fixed head) or the chip the session frame
// itself paints (pre-fix base) is on screen before we read. A TimeoutError is the expected no-chatTail case,
// where that session frame already painted the chip; only a TimeoutError is swallowed.
await page.waitForFunction(() => {
  const fr = window.__frames || [];
  let lastClearSession = -1;
  for (let i = 0; i < fr.length; i++) {
    const f = fr[i];
    if (f && f.type === "session" && Array.isArray(f.kinds) && f.kinds.indexOf("clear") >= 0) lastClearSession = i;
  }
  if (lastClearSession < 0) return false;
  for (let i = lastClearSession + 1; i < fr.length; i++) if (fr[i] && fr[i].type === "chatTail") return true;
  return false;
}, null, { timeout: 8000 }).catch((e) => { if (e.name !== "TimeoutError") throw e; });
await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r())));
// Now POLL, event-based, to the settled ready state the report describes: the boundary card is up AND the
// message has landed as its own row (not a queued bubble). A SYNCHRONOUS predicate (a plain boolean DOM read),
// so Playwright actually polls it; a Promise-returning predicate would be evaluated once and never poll (the
// lab-quality rule). Both products reach this state; the frame-wait above pins the paint and the assertions
// below tell them apart.
await page.waitForFunction((c) => {
  const txt = (el) => (el.textContent || "");
  const reply = Array.from(document.querySelectorAll("#content .turn")).some((t) => txt(t).indexOf(c.reply) >= 0);
  const boundary = Array.from(document.querySelectorAll("#content .turn, #content .notice")).some((el) => txt(el).indexOf("Conversation cleared") >= 0 || txt(el).indexOf("fresh one starts") >= 0);
  const landed = Array.from(document.querySelectorAll("#content .turn.turn-user:not(.echo) .user-bubble")).some((b) => txt(b).indexOf(c.msg) >= 0);
  return reply && boundary && landed;
}, { reply: cfg.reply, msg: cfg.msg }, { timeout: 30000 }).catch(() => {});

const after = await page.evaluate((c) => {
  const txt = (el) => (el.textContent || "");
  const msg = c.msg, reply = c.reply;
  const clearingRow = !!document.querySelector("#content .turn-clearing");
  const clearingText = Array.from(document.querySelectorAll("#content .turn, #content .notice, #statusline, #status-chip")).some((el) => txt(el).indexOf("Clearing conversation") >= 0);
  const clearChip = Array.from(document.querySelectorAll("#content .turn-queued .slash-cmd-chip")).some((ch) => txt(ch).indexOf("/clear") >= 0);
  const clearEcho = Array.from(document.querySelectorAll("#content .turn.echo")).some((t) => txt(t).indexOf("/clear") >= 0);
  const sendingGroup = Array.from(document.querySelectorAll("#content .queued-head")).some((h) => txt(h).toLowerCase().indexOf("sending") >= 0);
  const msgInQueued = Array.from(document.querySelectorAll("#content .turn-queued .queued-bubble, #content .turn.echo .user-bubble")).some((b) => txt(b).indexOf(msg) >= 0);
  const msgLanded = Array.from(document.querySelectorAll("#content .turn.turn-user:not(.echo) .user-bubble")).some((b) => txt(b).indexOf(msg) >= 0);
  const replyShown = Array.from(document.querySelectorAll("#content .turn")).some((t) => txt(t).indexOf(reply) >= 0);
  const boundaryCard = Array.from(document.querySelectorAll("#content .turn, #content .notice")).some((el) => txt(el).indexOf("Conversation cleared") >= 0 || txt(el).indexOf("fresh one starts") >= 0);
  // The regression signal: a STUCK "/clear" (the defect), NOT the LANDED /clear command row (the fixed
  // state). With the CLI-shaped fixture the /clear lands as a command row (.turn-cmd, which carries a
  // .user-bubble), so a "/clear text anywhere" read would false-match it; scope instead to the two STUCK
  // forms, the optimistic pending chip (.turn-queued .slash-cmd-chip) and the kernel echo (.turn.echo).
  const clearStuck = Array.from(document.querySelectorAll("#content .turn-queued .slash-cmd-chip, #content .turn.echo")).some((b) => txt(b).indexOf("/clear") >= 0);
  const turnTexts = Array.from(document.querySelectorAll("#content .turn")).map((t) => (txt(t) || "").trim().slice(0, 80));
  const chip = document.getElementById("status-chip");
  const pill = chip ? (chip.textContent || "").trim() : "";
  const composer = (document.getElementById("composer-input") || {}).value || "";
  return { clearingRow, clearingText, clearChip, clearEcho, clearStuck, turnTexts, sendingGroup, msgInQueued, msgLanded, replyShown, boundaryCard, pill, composer };
}, cfg);

const frames = await page.evaluate(() => window.__frames || []);
await browser.close();
process.stdout.write("RESULT:" + JSON.stringify({ qids, mid, after, frames }) + "\n", () => process.exit(0));
"""


class ServedClearBatchRealKernel(unittest.TestCase):
    """Boot a hermetic kernel over an IDLE session with the fake Agent SDK, and drive a real /clear+message batch."""
    maxDiff = None
    _r = None

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(os.path.join(EXT, "node_modules", "playwright")):
            raise unittest.SkipTest("extension deps absent (npm ci not run here), the served guard needs them")
        cls.lab = tempfile.mkdtemp(prefix="clear-batch-real-")
        b = subprocess.run(["node", "esbuild.js"], cwd=EXT, capture_output=True, text=True)
        if b.returncode != 0:
            raise unittest.SkipTest("esbuild failed here: " + (b.stderr or b.stdout)[-200:])
        dist = os.path.join(cls.lab, "dist")
        copy_dist(os.path.join(EXT, "dist"), dist)
        cls.state = os.path.join(cls.lab, "xdg", "romp")
        cwd = os.path.join(cls.lab, "proj")
        for d in ("names", "sdk", "states"):
            os.makedirs(os.path.join(cls.state, d), exist_ok=True)
        Path(cls.state, "session-hosts").write_text("off")     # our own state root: no real host for the session
        os.makedirs(cwd, exist_ok=True)
        Path(cls.state, "names", SID).write_text("web\t%s\t\t\n" % cwd)
        Path(cls.state, "sdk", SID + ".json").write_text(json.dumps(
            {"sid": SID, "name": "web", "cwd": cwd, "mode": "auto", "effort": "high",
             "lastSid": SID, "alive": True, "model": "claude-fable-5-1", "liveModel": "Fable 5.1"}))
        Path(cls.state, "usage.json").write_text(json.dumps({"five_hour": {"pct": 10}, "seven_day": {"pct": 10}}))
        claude = os.path.join(cls.lab, "claude")
        proj = os.path.join(claude, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd)))
        os.makedirs(proj, exist_ok=True)
        # an IDLE session: a CLOSED pre-clear turn (last record is an assistant end_turn), so the boot never
        # resumes-and-runs it, the /clear the driver sends is fed at once as its own fresh turn
        t0 = int(time.time()) - 900
        recs = [
            {"type": "user", "timestamp": iso(t0), "uuid": "u1", "parentUuid": None, "promptSource": "sdk", "sessionId": SID,
             "message": {"role": "user", "content": "tighten the notes-api search"}},
            {"type": "assistant", "timestamp": iso(t0 + 10), "uuid": "a1", "parentUuid": "u1", "sessionId": SID,
             "message": {"role": "assistant", "model": "claude-fable-5-1", "stop_reason": "end_turn",
                         "content": [{"type": "text", "text": "Earlier reply, before the clear."}]}},
        ]
        Path(proj, SID + ".jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        cls.port = _free_port()
        cls.token = "testtok-clearbatch"
        cls.gate = os.path.join(cls.lab, "clear-gate")   # the fake SDK waits on this file before running the /clear; the driver creates it after the in-flight snapshot
        # the fake Agent SDK on the kernel's import path, and the synthetic reply it answers the message with
        env = _lab.kernel_env(cls.lab, claude, dist, cls.port, cls.token,
                              PYTHONPATH=FAKE_SDK, ROMP_FAKE_SDK_REPLY=REPLY,
                              ROMP_FAKE_SDK_GATE=cls.gate)   # the fake holds the /clear IN FLIGHT until the driver creates this file (an event, not a timer)
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
                           "sid": SID, "msg": MSG, "reply": REPLY, "gate": self.gate, "consoleLog": console_log}, f)
            driver = os.path.join(self.lab, "driver.mjs")
            with open(driver, "w") as f:
                f.write(DRIVER)
            p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=300,
                               env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
            if p.returncode == 3:
                raise unittest.SkipTest("no playwright browser on this box, the served guard needs one (CI installs none)")
            self.assertEqual(p.returncode, 0, "driver failed:\n" + p.stdout[-3000:] + p.stderr[-3000:] + "\nkernel:\n" + open(self.klog).read()[-2500:])
            line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT:")), None)
            self.assertIsNotNone(line, "driver printed no result:\n" + p.stdout[-3000:])
            cls._r = json.loads(line[len("RESULT:"):])
        print("RESULT:" + json.dumps(cls._r), file=sys.stderr)   # the whole measurement rides EVERY test's captured stderr
        return cls._r

    def test_the_batch_runs_end_to_end_through_the_real_kernel(self):
        r = self._result()
        self.assertTrue(r["qids"]["clear"], "the /clear reached the kernel with a press id: " + json.dumps(r["qids"]))
        self.assertTrue(r["qids"]["msg"], "the message reached the kernel with a press id: " + json.dumps(r["qids"]))
        self.assertTrue(r["after"]["replyShown"], "the fake agent's reply rendered (the real kernel ran the batch): " + json.dumps(r["after"]))

    def test_the_in_flight_state_shows_all_four_report_elements(self):
        # the report's starting point, reproduced through the real kernel: while the clear is running the
        # page carries the "Clearing conversation…" row (1), a dashed /clear chip (2)+(3), and the message
        # as a dashed pending bubble (4), the FOUR elements together
        m = self._result()["mid"]
        table = "\n  mid=" + json.dumps(m)
        self.assertTrue(m["clearingRow"], "(1) the 'Clearing conversation…' row is up while the clear runs" + table)
        self.assertTrue(m["clearChip"], "(2)/(3) the /clear shows as a pending chip while it runs" + table)
        self.assertTrue(m["msgBubble"], "(4) the batched message is a dashed pending bubble while the clear runs" + table)

    def test_after_the_clear_ran_no_stuck_rows_remain(self):
        r = self._result()
        a = r["after"]
        table = "\n  after=" + json.dumps(a) + "\n  qids=" + json.dumps(r["qids"])
        # THE regression signal, reliable at the base: a STUCK "/clear" (the optimistic pending chip or the
        # kernel echo), NOT the landed /clear command row the CLI-shaped fixture now produces. Base (client
        # boundary-retire reverted): a stuck /clear chip rides on, so red; fixed: it lands as a command row
        # and no stuck chip remains, so green.
        self.assertFalse(a["clearStuck"], "no STUCK '/clear' (optimistic chip or kernel echo) rides the settled conversation; the /clear is a LANDED command row" + table)
        self.assertFalse(a["clearingRow"], "the 'Clearing conversation…' row is gone once the clear has run" + table)
        self.assertFalse(a["clearingText"], "no 'Clearing conversation…' text anywhere (row or statusline)" + table)
        self.assertFalse(a["sendingGroup"], "no 'sending…' group left owed" + table)
        self.assertFalse(a["msgInQueued"], "the message is no longer a dashed pending bubble" + table)
        # and the fresh-episode scene the real kernel produced
        self.assertTrue(a["msgLanded"], "the message is present as its LANDED row (the kernel's record)" + table)
        self.assertTrue(a["replyShown"], "the agent's reply rendered" + table)
        self.assertTrue(a["boundaryCard"], "the 'Conversation cleared' boundary card marks the fresh episode" + table)
        self.assertEqual(a["composer"], "", "the composer is empty" + table)


class FakeSdkRefusesWithoutClaudeConfigDir(unittest.TestCase):
    """The fake claude_agent_sdk must FAIL LOUD rather than write transcripts under the real
    ~/.claude when CLAUDE_CONFIG_DIR is unset. Loaded by file path under a private name so it never shadows the
    real package in sys.modules for the other tests in the run."""
    def _load_fake(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("_fake_cas_probe", os.path.join(FAKE_SDK, "claude_agent_sdk", "__init__.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_unset_claude_config_dir_raises_and_a_set_one_is_used(self):
        fake = self._load_fake()
        saved = os.environ.pop("CLAUDE_CONFIG_DIR", None)
        try:
            with self.assertRaises(RuntimeError):
                fake._proj_dir("/tmp/some-proj")     # unset -> refuse, never touch ~/.claude
            os.environ["CLAUDE_CONFIG_DIR"] = "/tmp/hermetic-claude-root"
            self.assertTrue(fake._proj_dir("/tmp/some-proj").startswith("/tmp/hermetic-claude-root/projects/"),
                            "with the var set, transcripts go under the hermetic root")
        finally:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
            if saved is not None:
                os.environ["CLAUDE_CONFIG_DIR"] = saved


if __name__ == "__main__":
    unittest.main()
