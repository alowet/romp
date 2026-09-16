#!/usr/bin/env python3
"""The phone's session picker lists the sessions in the desktop strip's order, under the same tag
headings (the user 2026-09-16, whose phone picker ran the sessions in another order than the strip on
their desktop once the tabs were grouped by tag).

The desktop strip is painted from planStrip (ui/webview/tab-groups.ts): one section per tag in tagOrder,
each holding every visible member it carries (a session under two tags has a copy in each), then the
untagged trail behind a separator. The phone's picker (kernel.py _CHAT_MOBILE_JS, #mlist) is built by
scraping the page's own hidden #tabs strip, so it lists whatever the strip renders in DOM order — and on
the phone layout the plan used to FLATTEN: planStrip(phone=true) returned the visible ids in their raw
view order with no headings, since a folded section there would have hidden its members from the
phone's only switcher. The two surfaces therefore read the same ids in two orders. Now the phone plan
sections like the desktop's (nothing folds there: the picker's heading is a label, not a fold control,
so every session stays reachable), and the picker mirrors the strip's children one for one: a heading
row per group header (the tag's chip and the count, cloned from the header), a row per tab copy, a
divider where the trail begins.

This lab drives a hermetic kernel's real /chat page twice: a desktop context reads the strip's children,
a phone context (a coarse pointer under 1024 px, the kernel's own media rule) opens the picker and reads
its rows; the two sequences must be identical. It also taps a copy under its second tag (the session
opens), taps a heading (nothing opens, the list stays), and folds a group in the phone's own store (the
phone lists its members regardless, where the desktop hides them). Skips LOUDLY without the extension
deps or a Playwright browser. SYNTHETIC fixtures only (the notes-api demo world, host TESTHOST,
placeholder sids). MOBILE_ORDER_DUMP=<path> writes the whole measurement."""
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
from datetime import datetime, timezone
from pathlib import Path

from tests.dist_copy import copy_dist

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
EXT = os.path.join(ROOT, "vscode-extension")
sys.path.insert(0, HERE)
import test_ship_reship_served as _lab   # noqa: E402  the lab kernel's environment: a list of names, never a copy of the runner's

# the notes-api demo world, in an order that interleaves the groups: the strip's raw order is
# web, tests, api, docs, deploy, auth, search, cache; grouped it reads qa (tests, docs, deploy), then
# infra (web, api, deploy), then the untagged trail (auth, search, cache) — deploy under both tags
NAMES = ["web", "tests", "api", "docs", "deploy", "auth", "search", "cache"]
SIDS = {n: "%s-1111-2222-3333-444444444444" % (chr(ord("a") + i) * 8) for i, n in enumerate(NAMES)}
NAME_OF = {v: k for k, v in SIDS.items()}
PALETTE = [("#9cd2ff", "#0c1a2e"), ("#1EA1EB", "#ffffff"), ("#54B204", "#ffffff"), ("#c98cff", "#1a0c2e"),
           ("#e5a50a", "#1a1200"), ("#4EC9B0", "#00201a")]
TAGS = [{"id": "tag-qa", "name": "qa", "color": "#DD42FF", "members": [SIDS[n] for n in ("tests", "docs", "deploy")]},
        {"id": "tag-infra", "name": "infra", "color": "#4EC9B0", "members": [SIDS[n] for n in ("web", "api", "deploy")]}]
TAG_ORDER = ["qa", "infra"]
MEMBERS = {"qa": {"tests", "docs", "deploy"}, "infra": {"web", "api", "deploy"}, None: {"auth", "search", "cache"}}


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
const MEDIA = "(pointer:coarse) and (max-width:1024px)";
// the strip's children and the picker's, one token each: a group heading (g:<tag>), a tab or row (t:<sid>/<copy>;
// the copy is the group the tab sits in, "" for the untagged trail, "-" on a flat strip), the trail's divider (sep)
const SEQ = `(root, k) => Array.from(root ? root.children : []).map((el) => {
  if (el.matches(k.head)) return "g:" + el.dataset.group;
  if (el.matches(k.sep)) return "sep";
  if (el.matches(k.tab)) return "t:" + el.dataset.id + "/" + (el.dataset.copy === undefined ? "-" : el.dataset.copy);
  return null; }).filter(Boolean)`;
const STRIP = { head: ".tab-group-head[data-group]", sep: ".tab-group-sep", tab: ".tab[data-id]" };
const PICKER = { head: ".mhead[data-group]", sep: ".msep", tab: ".mrow[data-id]" };
const readStrip = (page) => page.evaluate(([seq, k]) => (0, eval)(seq)(document.getElementById("tabs"), k), [SEQ, STRIP]);
const readPicker = (page) => page.evaluate(([seq, k]) => (0, eval)(seq)(document.getElementById("mlist"), k), [SEQ, PICKER]);
const settle = async (page) => {
  // attached, not visible: the phone page hides #tabs (display:none) and still renders every tab into it
  await page.waitForFunction((n) => document.querySelectorAll("#tabs .tab[data-id]").length >= n, cfg.count, { timeout: 30000 });
  // …and sectioned: the views frame that carries the tags can land after the tabs (under load it did), and a strip
  // read before it is flat. Bounded rather than required, so a strip that never sections (the phone before the fix)
  // still reaches the assertion, which then says what was there
  await page.waitForFunction(() => document.querySelectorAll("#tabs .tab-group-head[data-group]").length >= 2, null, { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(300);
};
// the picker built from that strip: a row per tab (a copy each), read once the rows are there
const pickerReady = (page) => page.waitForFunction((n) => document.querySelectorAll("#mlist .mrow[data-id]").length >= n, cfg.count, { timeout: 10000 });
const state = (page) => page.evaluate((m) => {
  const vis = (el) => !!el && getComputedStyle(el).display !== "none" && el.getClientRects().length > 0;
  const act = document.querySelector("#tabs .tab.active[data-id]");
  const cur = document.querySelector("#mcur .nm");
  return { phoneLayout: window.matchMedia(m).matches, stripVisible: vis(document.getElementById("tabs")),
           headerVisible: vis(document.getElementById("mhdr")), listOpen: !!document.querySelector("#mlist.open"),
           active: act ? act.dataset.id : null, current: cur ? cur.textContent.trim() : null,
           activeRows: Array.from(document.querySelectorAll("#mlist .mrow.active")).map((r) => r.dataset.id),
           rowNames: Array.from(document.querySelectorAll("#mlist .mrow[data-id]")).map((r) => (r.querySelector(".nm") || r).textContent.trim()),
           headTexts: Array.from(document.querySelectorAll("#mlist .mhead")).map((h) => h.textContent.trim()) };
}, MEDIA);
const out = {};
// 1. the DESKTOP strip: a mouse, a wide window — the order the user sees on their desktop
const desk = await browser.newContext({ viewport: { width: 1400, height: 800 } });
const dpage = await desk.newPage();
await dpage.goto(cfg.chat);
await settle(dpage);
out.desktop = { strip: await readStrip(dpage), ...(await state(dpage)) };
// 2. the PHONE: a coarse pointer under 1024 px (the kernel's own media rule), the picker in the strip's place
const phoneCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, deviceScaleFactor: 3 });
const page = await phoneCtx.newPage();
await page.goto(cfg.chat);
await settle(page);
await page.tap("#mcur");
await page.waitForSelector("#mlist.open", { timeout: 10000 });
await pickerReady(page);
await page.waitForTimeout(300);
out.phone = { strip: await readStrip(page), picker: await readPicker(page), ...(await state(page)) };
// 3. a copy under its SECOND tag is a row of its own and opens the session: the deploy row under infra (the
//    last deploy row), tapped
const copies = await page.$$('#mlist .mrow[data-id="' + cfg.deploy + '"]');
out.tapCopy = { copies: copies.length };
if (copies.length) {
  await copies[copies.length - 1].tap();
  await page.waitForFunction((id) => { const a = document.querySelector("#tabs .tab.active[data-id]"); return !!a && a.dataset.id === id; }, cfg.deploy, { timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(300);
  Object.assign(out.tapCopy, await state(page));
}
// 4. a heading is a label, not a pick: tapped, the list stays open and nothing opens
await page.evaluate(() => { const l = document.getElementById("mlist"); if (l && !l.classList.contains("open")) document.getElementById("mcur").click(); });
await page.waitForTimeout(200);
const before = await state(page);
const head = await page.$("#mlist .mhead[data-group]");
out.tapHead = { present: !!head, before: before.active };
if (head) {
  await head.tap();
  await page.waitForTimeout(400);
  Object.assign(out.tapHead, await state(page));
}
// 5. a FOLD in the phone's own store: qa folded. The desktop hides qa's members under its header; the phone lists
//    them regardless — its heading is a label, the picker its only switcher, so nothing may fold out of reach
const FOLD = JSON.stringify({ on: true, collapsed: ["qa"], expanded: [], pinned: [] });
await page.evaluate((v) => localStorage.setItem("romp:tabgroups", v), FOLD);
await page.reload();
await settle(page);
await page.tap("#mcur");
await page.waitForSelector("#mlist.open", { timeout: 10000 });
await pickerReady(page);
await page.waitForTimeout(300);
out.phoneFolded = { strip: await readStrip(page), picker: await readPicker(page), ...(await state(page)) };
await dpage.evaluate((v) => localStorage.setItem("romp:tabgroups", v), FOLD);
await dpage.reload();
await dpage.waitForFunction(() => document.querySelectorAll("#tabs .tab[data-id]").length >= 5, null, { timeout: 30000 });   // qa's three folded away
await dpage.waitForFunction(() => document.querySelectorAll("#tabs .tab-group-head[data-group]").length >= 2, null, { timeout: 15000 }).catch(() => {});
await dpage.waitForTimeout(300);
out.desktopFolded = { strip: await readStrip(dpage), ...(await state(dpage)) };
fs.writeFileSync(cfg.out, JSON.stringify(out));
fs.writeSync(1, "RESULT:" + cfg.out + "\n");
await browser.close();
process.exit(0);
"""


def names(seq):
    """A sequence with the sids replaced by the demo names, for readable diffs."""
    def one(tok):
        if tok.startswith("t:"):
            sid, _, copy = tok[2:].partition("/")
            return "t:%s/%s" % (NAME_OF.get(sid, sid), copy)
        return tok
    return [one(t) for t in seq]


def sections(seq):
    """A strip or picker as (group, {member names}) in order: a heading opens a group, the divider opens
    the untagged trail (None), and a sequence with no heading at all is one flat run ("-")."""
    out, cur = [], None
    for tok in names(seq):
        if tok.startswith("g:"):
            cur = (tok[2:], set()); out.append(cur)
        elif tok == "sep":
            cur = (None, set()); out.append(cur)
        elif tok.startswith("t:"):
            if cur is None:
                cur = ("-", set()); out.append(cur)
            cur[1].add(tok[2:].partition("/")[0])
    return out


class ServedMobilePickerOrder(unittest.TestCase):
    maxDiff = None
    result = None

    @classmethod
    def setUpClass(cls):
        try:
            cls._boot()
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def _boot(cls):
        if not os.path.isdir(os.path.join(EXT, "node_modules", "playwright")):
            raise unittest.SkipTest("extension deps absent (npm ci not run here) — the served guard needs them")
        probe = subprocess.run(["node", "-e", "const p=require(process.argv[1]);process.stdout.write(p.chromium.executablePath())",
                                os.path.join(EXT, "node_modules", "playwright")], capture_output=True, text=True)
        if probe.returncode != 0 or not os.path.exists(probe.stdout.strip()):
            raise unittest.SkipTest("no playwright browser on this box — the served guard needs one (CI installs none)")
        cls.lab = tempfile.mkdtemp(prefix="mobile-order-")
        b = subprocess.run(["node", "esbuild.js"], cwd=EXT, capture_output=True, text=True)
        if b.returncode != 0:
            raise unittest.SkipTest("esbuild failed here: " + (b.stderr or b.stdout)[-200:])
        dist = os.path.join(cls.lab, "dist")
        copy_dist(os.path.join(EXT, "dist"), dist)   # tests/dist_copy: skips the bundler's staging files
        state = os.path.join(cls.lab, "xdg", "romp")
        claude = os.path.join(cls.lab, "claude")
        cwd = os.path.join(cls.lab, "proj")
        for d in ("names", "sdk", "states"):
            os.makedirs(os.path.join(state, d), exist_ok=True)
        Path(state, "session-hosts").write_text("off\n")   # a lab root of its own: no per-session host process (CLAUDE.md, 2026-09-11)
        os.makedirs(cwd, exist_ok=True)
        proj = os.path.join(claude, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd)))
        os.makedirs(proj, exist_ok=True)
        t0 = int(time.time()) - 900
        for i, name in enumerate(NAMES):
            sid = SIDS[name]
            bg, fg = PALETTE[i % len(PALETTE)]
            Path(state, "names", sid).write_text("%s\t%s\t%s\t%s\n" % (name, cwd, bg, fg))
            Path(state, "sdk", sid + ".json").write_text(json.dumps(
                {"sid": sid, "name": name, "cwd": cwd, "mode": "auto", "effort": "high", "lastSid": sid, "alive": True,
                 "model": "claude-opus-5", "liveModel": "Opus 5"}))
            recs = [{"type": "user", "timestamp": iso(t0 + i), "uuid": "u1", "parentUuid": None, "promptSource": "typed", "sessionId": sid,
                     "message": {"role": "user", "content": "what does the %s session do in notes-api?" % name}},
                    {"type": "assistant", "timestamp": iso(t0 + i + 5), "uuid": "a1", "parentUuid": "u1", "sessionId": sid,
                     "message": {"role": "assistant", "model": "claude-opus-5", "stop_reason": "end_turn",
                                 "content": [{"type": "text", "text": "It keeps the %s side of the notes-api tidy." % name}]}}]
            Path(proj, sid + ".jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        Path(state, "timeline-views.json").write_text(json.dumps({"active": "all", "tags": TAGS, "tagOrder": TAG_ORDER}))
        Path(state, "usage.json").write_text(json.dumps({"five_hour": {"pct": 10}, "seven_day": {"pct": 10}}))
        cls.port, cls.token = _free_port(), "testtok-mobileorder"
        env = _lab.kernel_env(cls.lab, claude, dist, cls.port, cls.token, ROMP_HOST_NAME="TESTHOST")
        cls.klog = os.path.join(cls.lab, "kernel.log")
        cls.kernel = subprocess.Popen([os.path.join(BIN, "romp-kernel")], stdout=open(cls.klog, "w"), stderr=subprocess.STDOUT, env=env)
        for _ in range(120):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/healthz" % cls.port, timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise unittest.SkipTest("hermetic kernel never served /healthz here")

    @classmethod
    def tearDownClass(cls):
        k = getattr(cls, "kernel", None)
        if k:
            k.kill(); k.wait()
        shutil.rmtree(getattr(cls, "lab", ""), ignore_errors=True)

    @classmethod
    def _run(cls):
        """One driver run for every case (the taps are sequential on one page); its result, or its failure, is shared."""
        if cls.result is not None:
            if isinstance(cls.result, BaseException):
                raise cls.result
            return cls.result
        try:
            cls.result = cls._drive()
        except BaseException as e:
            cls.result = e
            raise
        return cls.result

    @classmethod
    def _drive(cls):
        cfg = os.path.join(cls.lab, "cfg.json")
        out = os.path.join(cls.lab, "result.json")
        with open(cfg, "w") as f:
            json.dump({"chat": "http://127.0.0.1:%d/chat?token=%s" % (cls.port, cls.token), "count": len(NAMES), "out": out,
                       "deploy": SIDS["deploy"]}, f)
        driver = os.path.join(cls.lab, "driver.mjs")
        with open(driver, "w") as f:
            f.write(DRIVER)
        p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=300,
                           env=dict(os.environ, EXT_PKG=os.path.join(EXT, "package.json"), CFG=cfg))
        if p.returncode == 3:
            raise unittest.SkipTest("no playwright browser on this box — the served guard needs one (CI installs none)")
        if p.returncode != 0:
            raise AssertionError("driver failed:\n" + p.stdout[-3000:] + p.stderr[-3000:] + "\nkernel:\n" + open(cls.klog).read()[-1500:])
        line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT:")), None)
        if line is None or not os.path.exists(out):
            raise AssertionError("driver printed no result:\n" + p.stdout[-3000:])
        result = json.loads(Path(out).read_text())
        if os.environ.get("MOBILE_ORDER_DUMP"):
            Path(os.environ["MOBILE_ORDER_DUMP"]).write_text(json.dumps(result, indent=1) + "\n")
        return result

    # ── the layouts the lab drove are the ones it meant to ──
    def test_the_two_contexts_land_on_the_two_layouts(self):
        r = self._run()
        self.assertFalse(r["desktop"]["phoneLayout"], "a mouse and 1400 px: the desktop layout")
        self.assertTrue(r["desktop"]["stripVisible"])
        self.assertTrue(r["phone"]["phoneLayout"], "a coarse pointer at 390 px: the kernel's phone rule holds")
        self.assertFalse(r["phone"]["stripVisible"], "the phone page hides the strip…")
        self.assertTrue(r["phone"]["headerVisible"], "…and shows the picker's header in its place")
        self.assertTrue(r["phone"]["listOpen"], "the tap on the current-session chip opened the list")

    # ── the bug: the picker's order is the desktop strip's, headings included ──
    def test_the_desktop_strip_groups_by_tag_in_tag_order_with_the_trail_last(self):
        # the fixture's shape (the kernel lists the newest session first, so the order inside a group is its own):
        # qa then infra, in tag order, deploy under both, the three untagged behind the divider
        r = self._run()
        self.assertEqual(sections(r["desktop"]["strip"]), [("qa", MEMBERS["qa"]), ("infra", MEMBERS["infra"]), (None, MEMBERS[None])],
                         names(r["desktop"]["strip"]))

    def test_the_phone_picker_reads_the_same_as_the_desktop_strip(self):
        r = self._run()
        self.assertEqual(names(r["phone"]["picker"]), names(r["desktop"]["strip"]),
                         "the phone picker (left) lists the sessions in another order, or without the strip's headings, "
                         "than the desktop strip (right)")
        self.assertEqual(names(r["phone"]["picker"]), names(r["phone"]["strip"]),
                         "…and mirrors its own page's strip one for one: the strip is the picker's one source")

    def test_the_rows_keep_their_state_cues(self):
        r = self._run()
        p = r["phone"]
        self.assertIsNotNone(p["active"], "an active tab")
        self.assertEqual(sorted(set(p["activeRows"])), [p["active"]], "every row of the active session wears .active (its copies too)")
        self.assertEqual(p["rowNames"], [t.split("/")[0][2:] for t in names(p["picker"]) if t.startswith("t:")],
                         "each row names its session")
        self.assertEqual(p["headTexts"], ["qa3", "infra3"], "a heading is the tag's chip and the member count, nothing else (no caret: it folds nothing)")
        self.assertEqual(p["current"], NAME_OF[p["active"]], "the current-session chip names the active session")

    # ── the copies: a session under two tags is a row under each, and either opens it ──
    def test_a_copy_under_its_second_tag_is_a_row_of_its_own_that_opens_the_session(self):
        r = self._run()
        t = r["tapCopy"]
        self.assertEqual(t["copies"], 2, "deploy is under qa and under infra: two rows")
        self.assertEqual(t["active"], SIDS["deploy"], "the tap on the infra copy opened deploy")
        self.assertEqual(t["current"], "deploy")
        self.assertFalse(t["listOpen"], "a pick closes the list")

    # ── a heading is a label ──
    def test_a_heading_is_a_label_not_a_pick(self):
        r = self._run()
        t = r["tapHead"]
        self.assertTrue(t["present"], "the picker has headings")
        self.assertEqual(t["active"], t["before"], "tapping a heading opens nothing")
        self.assertTrue(t["listOpen"], "…and the list stays open for the pick")

    # ── folds are the desktop's: the phone hides no session from its only switcher ──
    def test_a_fold_hides_nothing_on_the_phone_where_the_desktop_folds(self):
        r = self._run()
        self.assertEqual(names(r["phoneFolded"]["picker"]), names(r["desktop"]["strip"]),
                         "qa folded in the phone's store: the phone lists qa's members regardless, in the strip's order")
        self.assertEqual(sections(r["desktopFolded"]["strip"]), [("qa", set()), ("infra", MEMBERS["infra"]), (None, MEMBERS[None])],
                         "the same store on the desktop folds qa: its header alone, no member tab")


if __name__ == "__main__":
    unittest.main()
