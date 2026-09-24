#!/usr/bin/env python3
"""The Task tracking switch across attached machines, on the served dashboard (T404 round seven). Over the queued lab's boot (a
hermetic kernel with one local session) two stand-in remote kernels check in as peers (the check-in handshake, no ssh: the
hermetic federated dashboard's harness): HOSTON and HOSTOFF each serve a feed frame with one card carrying a warn chip and a
sub-goal. The real feed page in a real browser merges the three hosts' frames. Stage A, every host on: both remote cards
show, their warn chips ring the shell's bell and the mirror stores a mark per card naming its host, and a real click on each
card's Sub-goals button writes the card's disclosure state (romp:feedview). Two stale marks are then seeded into the store
(a HOSTON card and a local card that are in no frame). Stage B, HOSTOFF flips off (it pushes the switch's stand-in frame:
off, empty lists) and HOSTON pushes a frame with a NEW card carrying a warn: the merged frame names HOSTOFF off, the view
state is byte-identical (the gate: no writer prunes while a host's cards are unknown), HOSTOFF's mark is kept, the two
stale marks are pruned (the on hosts' absent marks prune as ever: the store's bound), and the new card's notice rings with
its mark written. Stage B2 (round eight, the medium): the page RELOADS while HOSTOFF is off; the first merged frame names both
remotes pending with no host off, and the marks and the view state survive it intact (a pending host's cards are not in hand
either). Stage C: HOSTOFF flips back on WITH its card and nothing re-rings (its mark was kept). Stage C2: HOSTOFF pushes a frame
with no cards: the merged frame names no host, pruning resumes, HOSTOFF's disclosure entry and mark leave while HOSTON's stand.
Stage D: a plain reload with every host on: no warn re-rings. Round nine: each reload's first /tunnels answer is held for 1.5 s so
the local kernel's push surely lands first, the frame hook is an init script that trap-registers on the federation manager's
handle, and the first merged frame of each reload is asserted: no host known, the frame saying its host list is unread, and the
store unmoved across it. Skips LOUDLY without the extension deps or a browser (a failure under ROMP_SERVED_TESTS_REQUIRE=1).
SYNTHETIC fixtures only: hosts HOSTON and HOSTOFF, placeholder sids, invented goal text."""
import base64
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import unittest
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
from test_queued_rescind_browser import QueuedLab, SID   # noqa: E402  the shared boot

SID_ON = "22222222-3333-4444-5555-666666666666"
SID_OFF = "77777777-8888-4444-5555-999999999999"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _card(sid, goal, text, now):
    """One feed card as a kernel builds it (feed.ts AskItem), carrying a warn chip (the bell's w| mark) and one sub-goal
    (so the card shows its Sub-goals button, the disclosure gesture the lab clicks)."""
    item = sid + ":" + goal
    node = lambda nid, t, children: {"id": nid, "kind": "ask", "text": t, "who": "api", "whoSid": sid, "whoColor": None,   # noqa: E731
                                     "status": "open", "t": now - 60, "last": now - 30, "children": children}
    return {"itemId": item, "sid": sid, "name": "api", "color": {"bg": "#345", "fg": "#fff"}, "text": text, "t": now - 60,
            "live": True, "turnId": "t-" + goal, "trgb": [128, 128, 128], "column": "needs_input",
            "tree": [node(item, text, [item + ":s1"]), node(item + ":s1", "write the tests for it", [])],
            "warns": [{"kind": "distill", "t": now - 30, "msg": "the summarizer gave up"}]}


def _on_frame(sid, cards, now):
    return {"type": "feed", "now": now, "buildId": 1, "asks": cards, "items": [], "working": [], "awaiting": [], "stateUnknown": [],
            "order": [sid], "sessions": [{"sid": sid, "name": "api"}], "clearNotices": [], "sdkNotices": [], "syncNotices": [],
            "dismissedCount": 0, "showDismissed": False, "canUndoClear": False}


def _off_frame(now):
    """The switch's stand-in frame, as kernel.py _feed_off_frame builds it: off, every list empty, the rings real (empty here)."""
    f = {"type": "feed", "off": True, "now": now}
    for k in ("items", "asks", "working", "awaiting", "stateUnknown", "order", "sessions", "ledgers", "hosts", "pendingHosts", "pendingDead"):
        f[k] = []
    f.update({"dismissedCount": 0, "showDismissed": False, "canUndoClear": False, "clearNotices": [], "sdkNotices": [], "syncNotices": []})
    return f


class _StandInKernel:
    """A remote kernel's stand-in behind the check-in handshake: answers the supervisor's GETs (/sessions and the rest), accepts
    WebSocket upgrades from the kernel's relay (/ws?app=<pane>), pushes its current feed frame to every app=feed socket, and
    takes the lab's control route (GET /__lab/frame?mode=...) to swap the frame and push it. One thread per connection."""

    def __init__(self, name, token, frames, first):
        self.name, self.token, self.frames, self.mode = name, token, frames, first
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(32)
        self.port = self.srv.getsockname()[1]
        self.lock = threading.Lock()
        self.feed_conns = []
        self.closing = threading.Event()
        self.pushed = []
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self.closing.is_set():   # loop-ok: ends when the listener is closed (close())
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            conn.settimeout(60)
            head = b""
            while b"\r\n\r\n" not in head:   # loop-ok: a line reader over one request head
                chunk = conn.recv(4096)
                if not chunk:
                    return
                head += chunk
            req, _, rest = head.partition(b"\r\n\r\n")
            lines = req.decode("latin-1").split("\r\n")
            parts = lines[0].split(" ")
            method, target = parts[0], parts[1]
            headers = {k.lower(): v for k, v in (ln.split(": ", 1) for ln in lines[1:] if ": " in ln)}
            u = urllib.parse.urlsplit(target)
            q = urllib.parse.parse_qs(u.query)
            if headers.get("upgrade", "").lower() == "websocket":
                accept = base64.b64encode(hashlib.sha1((headers["sec-websocket-key"] + WS_GUID).encode()).digest()).decode()
                conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                              "Sec-WebSocket-Accept: %s\r\n\r\n" % accept).encode())
                if (q.get("app") or [""])[0] == "feed":
                    with self.lock:
                        self.feed_conns.append(conn)
                        frame = self.frames[self.mode]
                    self._send_text(conn, json.dumps(frame))
                self._drain(conn, rest)
                return
            body = self._route(method, u.path, q)
            conn.sendall(("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n"
                          % len(body)).encode() + body)
        except (OSError, ValueError, KeyError, IndexError):
            pass
        finally:
            with self.lock:
                if conn in self.feed_conns:
                    self.feed_conns.remove(conn)
            try:
                conn.close()
            except OSError:
                pass

    def _route(self, method, path, q):
        if path == "/__lab/frame":      # the lab's control: swap the frame and push it to every feed socket
            mode = (q.get("mode") or [""])[0]
            if mode not in self.frames:
                return json.dumps({"ok": False, "error": "no such mode"}).encode()
            with self.lock:
                self.mode = mode
                conns = list(self.feed_conns)
            data = json.dumps(self.frames[mode])
            sent = 0
            for c in conns:
                try:
                    self._send_text(c, data)
                    sent += 1
                except OSError:
                    pass
            self.pushed.append((mode, sent))
            return json.dumps({"ok": True, "mode": mode, "sent": sent}).encode()
        if path in ("/sessions", "/sids"):
            return b"[]"
        if path == "/version":
            return json.dumps({"sha": "0000000", "ver": "0.0.0", "pid": 1, "autoNudge": False, "settings": {},
                               "taskTracking": not self.frames[self.mode].get("off")}).encode()
        return b"{}" if method == "GET" else b'{"ok": true}'

    @staticmethod
    def _send_text(conn, text):
        data = text.encode()
        n = len(data)
        if n < 126:
            hdr = bytes([0x81, n])
        elif n < 65536:
            hdr = bytes([0x81, 126]) + struct.pack(">H", n)
        else:
            hdr = bytes([0x81, 127]) + struct.pack(">Q", n)
        conn.sendall(hdr + data)

    def _drain(self, conn, buf):
        """Read the client's frames until it closes: a ping is answered with a pong, a close ends the socket, the rest is dropped."""
        def need(n):
            nonlocal buf
            while len(buf) < n:   # loop-ok: a reader bounded by the socket's life
                chunk = conn.recv(65536)
                if not chunk:
                    raise OSError("closed")
                buf += chunk
        while not self.closing.is_set():   # loop-ok: one client frame per pass, ends on close or EOF
            need(2)
            opcode, masked, ln = buf[0] & 0x0F, buf[1] & 0x80, buf[1] & 0x7F
            i = 2
            if ln == 126:
                need(4); ln = struct.unpack(">H", buf[2:4])[0]; i = 4
            elif ln == 127:
                need(10); ln = struct.unpack(">Q", buf[2:10])[0]; i = 10
            if masked:
                need(i + 4); i += 4
            need(i + ln)
            buf = buf[i + ln:]
            if opcode == 8:
                try:
                    conn.sendall(b"\x88\x00")
                except OSError:
                    pass
                return
            if opcode == 9:
                conn.sendall(b"\x8a\x00")

    def close(self):
        self.closing.set()
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=1):
                pass
        except OSError:
            pass
        for op in (lambda: self.srv.shutdown(socket.SHUT_RDWR), self.srv.close):
            try:
                op()
            except OSError:
                pass
        with self.lock:
            conns = list(self.feed_conns)
        for c in conns:
            try:
                c.close()
            except OSError:
                pass


DRIVER = r"""
import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(process.env.EXT_PKG);
const { chromium } = require("playwright");
const cfg = JSON.parse(fs.readFileSync(process.env.CFG, "utf8"));
let browser;
try { browser = await chromium.launch(); }
catch (e) { console.error("browser-launch-failed: " + e); process.exit(3); }
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page = await ctx.newPage();
const errors = [];
// a load's FIRST merged feed frame, as an event (round ten): a binding the feed frame's init script calls once per load, which
// the /tunnels hold below waits on; a reload arms a fresh one. Round nine held the list 1.5 s from the reload call, and a
// starved runner's reload outlived the seconds, so the list landed before the frame (the v0.17.0 cut's local run, and
// every run under a half-core quota).
let firstFrame = null;
const armFirstFrame = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); firstFrame = { promise, resolve }; };
armFirstFrame();
await page.exposeFunction("__ttFirstFeedFrame", () => { if (firstFrame) firstFrame.resolve(); });
// the slow-load road (the reproduction by delay): the feed frame's document answers late, as on a starved runner
if (cfg.slowFeedLoadMs) await page.route((u) => u.pathname === "/feed", async (route) => { await new Promise((r) => setTimeout(r, cfg.slowFeedLoadMs)); await route.continue(); });
page.on("pageerror", (e) => errors.push("page: " + e.message));
page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text().slice(0, 300)); });
// the shell's bell: every notify the feed pane posts up, so a card's warn ringing is observable here; installed before any
// script of the page runs (an init script on the top window), since the first frame rings before a post-load hook could listen
await page.addInitScript(() => { if (window !== window.top) return; const w = window; w.__notes = []; window.addEventListener("message", (e) => { const d = e.data; if (d && d.romp === "notify") w.__notes.push({ kind: d.kind, itemId: d.itemId }); }); });
// the feed page's frame hook, ALSO an init script (round nine): the frames that matter are a load's first ones, applied before
// any post-load hook exists. The manager's window handle is trapped with a setter, so the hook registers on onFrame the moment
// federation.js publishes it, ahead of the pane's own handler (frames are delivered in registration order), and each record
// carries the store BEFORE the pane's writers run on that frame: the marks' count and the disclosure entries' count
await page.addInitScript(() => {
  if (!location.pathname.startsWith("/feed")) return;
  const w = window; w.__ttFrames = [];
  const before = () => { try { return { marks: JSON.parse(localStorage.getItem("romp:cardNotified") || "[]").length, sec: Object.keys(JSON.parse(localStorage.getItem("romp:feedview") || "{}").sec || {}).length }; } catch { return { marks: -1, sec: -1 }; } };
  const note = (m, via) => { if (m && m.type === "feed" && !w.__ttFirstSeen) { w.__ttFirstSeen = true; try { const fn = window.__ttFirstFeedFrame; if (fn) fn(); } catch (e) {} }
    if (m && m.type === "feed") w.__ttFrames.push({ via, off: m.off === true, hostsUnread: m.hostsUnread === true, offHosts: Array.isArray(m.offHosts) ? m.offHosts.slice() : null, pendingHosts: Array.isArray(m.pendingHosts) ? m.pendingHosts.slice() : null, askIds: Array.isArray(m.asks) ? m.asks.map((a) => a.itemId) : [], before: before() }); };
  window.addEventListener("message", (e) => note(e.data, "window"));
  let fed;
  Object.defineProperty(w, "__rompFed", { configurable: true, get() { return fed; }, set(v) { fed = v; try { if (v && typeof v.onFrame === "function") v.onFrame((e) => note(e.data, "fed")); } catch {} } });
});
// the first /tunnels answer of a load is HELD until that load's first merged feed frame is on record (round ten: the event
// round nine's 1.5 s approximated): the local kernel's push lands on its open socket and the frame is built with no remote
// host in hand, then the list goes through, and every later poll passes at once. Bounded at 20 s, so a page that never
// builds a frame fails on its own assertion instead of hanging here.
await page.route("**/tunnels", async (route) => { const armed = firstFrame; if (armed) await Promise.race([armed.promise, new Promise((r) => setTimeout(r, 20000))]); await route.continue(); });
await page.goto(cfg.landing);
await page.waitForSelector("#rail-gear", { timeout: 20000 });
const frameBy = async (part) => { let f = page.frames().find((x) => x.url().includes(part)); for (let i = 0; i < 100 && !f; i++) { await page.waitForTimeout(100); f = page.frames().find((x) => x.url().includes(part)); } return f; };
// the feed page and its hook: every feed frame the pane receives, by either path, with the switch's per-host list, the pending list
// and the card ids it carried; re-installed after each reload (the frames the pane applied BEFORE the hook are the reload's first
// ones, so the hook goes in as early as the page allows and the reload stages read the store, which every frame writes)
const hookFeed = async () => {   // the hook is the init script's; this finds the frame and waits for its list
  const f = await frameBy("/feed");
  if (!f) { console.error("no feed frame"); process.exit(4); }
  await f.waitForSelector("#feed-list", { timeout: 15000 });
  return f;
};
let feedF = await hookFeed();
const reload = async () => { armFirstFrame(); await page.reload(); await page.waitForSelector("#rail-gear", { timeout: 20000 }); feedF = await hookFeed(); };
const frames = () => feedF.evaluate(() => window.__ttFrames);
const lastFrame = () => feedF.evaluate(() => { const f = window.__ttFrames; return f.length ? f[f.length - 1] : null; });
const waitFrame = (pred, why) => feedF.waitForFunction((p) => { const f = window.__ttFrames; const last = f.length ? f[f.length - 1] : null; return !!last && (new Function("f", "return (" + p + ")(f)"))(last); }, pred.toString(), { timeout: 30000 }).catch(() => { errors.push("timeout: " + why); });
const store = () => feedF.evaluate(() => ({ view: localStorage.getItem("romp:feedview"), marks: JSON.parse(localStorage.getItem("romp:cardNotified") || "[]") }));
const notes = () => page.evaluate(() => window.__notes.slice());
const ctl = async (base, mode) => { const r = await fetch(base + "/__lab/frame?mode=" + mode); return r.json(); };
const out = { errors };
// ── stage A: every host on; both remote cards on screen, their chips ringing, a real click on each card's Sub-goals button ──
await waitFrame((f) => f.askIds.includes(CFG_OFF_CARD) && f.askIds.includes(CFG_ON_CARD0) && f.offHosts && f.offHosts.length === 0 && f.pendingHosts && f.pendingHosts.length === 0, "both remote cards in one merged frame with no host pending or off");
const clickSubs = async (itemId) => {
  // the card's section buttons are five, most hidden (Background shows only with a background); wait for the VISIBLE sub-goals one,
  // which reads "1 sub-goal" for one child and "N sub-goals" for more
  const sel = '[data-key="a:' + itemId + '"] .fask-secbtn';
  const ok = await feedF.waitForFunction((s) => { const b = Array.from(document.querySelectorAll(s)).find((x) => /sub-goal/i.test(x.textContent || "") && getComputedStyle(x).display !== "none"); if (!b) return false; b.click(); return true; }, sel, { timeout: 15000 }).then(() => true).catch(() => false);
  if (!ok) errors.push("no visible Sub-goals button on " + itemId);
};
await clickSubs(cfg.offCard);
await clickSubs(cfg.onCard0);
await page.mouse.move(3, 3);   // the pointer off every card: a hovered card queues payloads (hover-freeze)
// the pane persists its view state in a render's tail, and a section click alone renders nothing new: one more frame from the
// on host (the same frame again) is a merged frame, a render and the persist, exactly as the next kernel push would be
out.ctlRepush = await ctl(cfg.hostOnCtl, "on");
await feedF.waitForFunction((ids) => { try { const v = JSON.parse(localStorage.getItem("romp:feedview") || "{}"); return ids.every((id) => v.sec && v.sec[id] === "subgoals"); } catch { return false; } }, [cfg.offCard, cfg.onCard0], { timeout: 15000 }).catch(() => { errors.push("timeout: the two Sub-goals choices persisted"); });
await feedF.waitForFunction((ids) => { const m = JSON.parse(localStorage.getItem("romp:cardNotified") || "[]"); return ids.every((id) => m.some((s) => s.startsWith("w|" + id + "|"))); }, [cfg.offCard, cfg.onCard0], { timeout: 15000 }).catch(() => { errors.push("timeout: both cards' marks stored"); });
// three stale marks that no frame carries: an on host's card and a local card that left (the reporting hosts' absent marks are
// what the mixed frame must still prune, the store's bound, while the off host's are kept), and one in the OLD shape with no host
// segment (stored before round seven): kept while any host is not in hand, pruned once every host is (round eight, low 1)
await feedF.evaluate((stale) => { const m = JSON.parse(localStorage.getItem("romp:cardNotified") || "[]"); localStorage.setItem("romp:cardNotified", JSON.stringify(m.concat(stale))); }, [cfg.staleOnMark, cfg.staleLocalMark, cfg.staleOldMark]);
out.a = { frame: await lastFrame(), store: await store(), notes: await notes() };
out.frames = await frames();
// ── stage B: HOSTOFF flips off (its stand-in frame), HOSTON pushes a frame with a NEW card carrying a warn ──
out.ctlOff = await ctl(cfg.hostOffCtl, "off");
await waitFrame((f) => f.offHosts && f.offHosts.includes(CFG_HOST_OFF), "a merged frame naming HOSTOFF off");
out.ctlOn2 = await ctl(cfg.hostOnCtl, "on2");
await waitFrame((f) => f.askIds.includes(CFG_ON_CARD2) && f.offHosts && f.offHosts.includes(CFG_HOST_OFF), "the mixed frame carrying the new card");
await page.waitForTimeout(800);   // the render's tail persists the view state; the mirror writes on the frame
out.b = { frame: await lastFrame(), store: await store(), notes: await notes(), frames: (await frames()).length };
// ── stage B2 (round eight, the medium): a RELOAD while HOSTOFF is off. The first merged frame names both remotes pending and no
// host off; before this round the pane read their cards as gone, pruned every remote mark and re-rang every remote warn ──
await reload();
await waitFrame((f) => f.offHosts && f.offHosts.includes(CFG_HOST_OFF) && f.askIds.includes(CFG_ON_CARD2), "after the reload, the mixed frame again");
await page.waitForTimeout(800);
out.b2 = { frame: await lastFrame(), store: await store(), notes: await notes(), frames: await frames() };
// ── stage C: HOSTOFF flips back on WITH its card: nothing re-rings, its mark having been kept through the off frames and the reload ──
out.ctlBackOn = await ctl(cfg.hostOffCtl, "on");
await waitFrame((f) => f.offHosts && f.offHosts.length === 0 && f.pendingHosts && f.pendingHosts.length === 0 && f.askIds.includes(CFG_OFF_CARD) && f.askIds.includes(CFG_ON_CARD2), "every host on again, HOSTOFF's card back");
await page.waitForTimeout(800);
out.c = { frame: await lastFrame(), store: await store(), notes: await notes() };
// ── stage C2: HOSTOFF pushes a frame with no cards: its card left for real, so pruning resumes ──
out.ctlOnEmpty = await ctl(cfg.hostOffCtl, "on-empty");
await waitFrame((f) => f.offHosts && f.offHosts.length === 0 && f.askIds.includes(CFG_ON_CARD2) && !f.askIds.includes(CFG_OFF_CARD), "a merged frame naming no host off, without HOSTOFF's card");
await page.waitForTimeout(800);
out.c2 = { frame: await lastFrame(), store: await store(), notes: await notes() };
// ── stage D: a plain reload with every host on: the first frame names both remotes pending; no warn re-rings ──
await reload();
await waitFrame((f) => f.offHosts && f.offHosts.length === 0 && f.pendingHosts && f.pendingHosts.length === 0 && f.askIds.includes(CFG_ON_CARD0) && f.askIds.includes(CFG_ON_CARD2), "after the plain reload, every host reporting");
await page.waitForTimeout(800);
out.d = { frame: await lastFrame(), store: await store(), notes: await notes(), frames: await frames() };
await browser.close();
process.stdout.write("RESULT:" + JSON.stringify(out) + "\n", () => process.exit(0));
"""


class ServedTaskTrackingFederation(QueuedLab):
    _r = None
    _fakes = None

    @classmethod
    def tearDownClass(cls):
        for f in cls._fakes or []:
            f.close()
        super().tearDownClass()

    def _checkin(self, fake):
        req = urllib.request.Request("http://127.0.0.1:%d/checkin?token=%s" % (self.port, self.token),
                                     data=json.dumps({"host": fake.name, "kernelPort": fake.port, "busPort": fake.port, "token": fake.token}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        j = json.loads(urllib.request.urlopen(req, timeout=10).read())
        self.assertTrue(j.get("ok"), "the check-in handshake took the stand-in: %r" % (j,))

    def _wait_up(self, names):
        rows = None
        for _ in range(80):   # bounded: the handshake wakes the supervisor, whose pass marks the row up within seconds
            rows = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/tunnels?token=%s" % (self.port, self.token), timeout=10).read())
            by = {r["host"]: r for r in (rows.get("tunnels") if isinstance(rows, dict) else rows) or [] if isinstance(r, dict) and "host" in r}
            if all(by.get(n, {}).get("status") == "up" and by.get(n, {}).get("hasToken") for n in names):
                return by
            time.sleep(0.5)
        self.fail("the stand-in hosts never read up in /tunnels: %r" % (rows,))

    def _result(self):
        cls = type(self)
        if cls._r is None:
            now = int(time.time())
            on0, on2 = _card(SID_ON, "g1", "add pagination to the notes list", now), _card(SID_ON, "g2", "rename the search endpoint", now)
            off1 = _card(SID_OFF, "g1", "cache the tag counts", now)
            host_on = _StandInKernel("HOSTON", "stand-in-token-on-DO-NOT-USE",
                                     {"on": _on_frame(SID_ON, [on0], now), "on2": _on_frame(SID_ON, [on0, on2], now + 5)}, "on")
            host_off = _StandInKernel("HOSTOFF", "stand-in-token-off-DO-NOT-USE",
                                      {"on": _on_frame(SID_OFF, [off1], now), "off": _off_frame(now + 5), "on-empty": _on_frame(SID_OFF, [], now + 10)}, "on")
            cls._fakes = [host_on, host_off]
            self._checkin(host_on)
            self._checkin(host_off)
            self._wait_up(["HOSTON", "HOSTOFF"])
            base = "http://127.0.0.1:%d" % self.port
            cfg = os.path.join(self.lab, "cfg_fed.json")
            stale_on = "w|%s:gone|%d|distill|@HOSTON" % (SID_ON, now - 900)
            stale_local = "n|%s:gone|@" % SID                         # the local host's shape: the empty segment
            stale_old = "w|%s:old|%d|distill" % (SID_ON, now - 900)     # the shape before round seven: no segment at all
            with open(cfg, "w") as f:
                json.dump({"landing": base + "/?token=" + self.token, "hostOnCtl": "http://127.0.0.1:%d" % host_on.port,
                           "slowFeedLoadMs": getattr(self, "SLOW_FEED_MS", 0),
                           "hostOffCtl": "http://127.0.0.1:%d" % host_off.port, "hostOff": "HOSTOFF", "hostOn": "HOSTON",
                           "offCard": off1["itemId"], "onCard0": on0["itemId"], "onCard2": on2["itemId"],
                           "staleOnMark": stale_on, "staleLocalMark": stale_local, "staleOldMark": stale_old}, f)
            driver = os.path.join(self.lab, "driver_fed.mjs")
            src = DRIVER.replace("CFG_OFF_CARD", json.dumps(off1["itemId"])).replace("CFG_ON_CARD0", json.dumps(on0["itemId"])) \
                        .replace("CFG_ON_CARD2", json.dumps(on2["itemId"])).replace("CFG_HOST_OFF", json.dumps("HOSTOFF"))
            with open(driver, "w") as f:
                f.write(src)
            p = subprocess.run(["node", driver], capture_output=True, text=True, timeout=300,
                               env=dict(os.environ, EXT_PKG=os.path.join(self.EXT, "package.json"), CFG=cfg))
            if p.returncode == 3:
                raise unittest.SkipTest("no playwright browser on this box — the served guard needs one (CI installs none)")
            self.assertEqual(p.returncode, 0, "driver failed:\n" + p.stdout[-3000:] + p.stderr[-3000:] + "\nkernel:\n" + open(self.klog).read()[-1500:])
            line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT:")), None)
            self.assertIsNotNone(line, "driver printed no result:\n" + p.stdout[-3000:])
            cls._r = json.loads(line[len("RESULT:"):])
            cls._r["cfg"] = json.load(open(cfg))
            cls._r["pushed"] = {"on": host_on.pushed, "off": host_off.pushed}
            if os.environ.get("TASK_TRACKING_DUMP"):
                with open(os.environ["TASK_TRACKING_DUMP"], "w") as f:
                    json.dump(cls._r, f, indent=1)
        print("RESULT:" + json.dumps(cls._r)[:6000], file=sys.stderr)
        return cls._r

    def _marks(self, stage):
        return self._result()[stage]["store"]["marks"]

    def test_stage_a_every_host_on_both_remote_cards_ring_the_bell_with_a_mark_naming_their_host_and_their_sub_goals_choice_persists(self):
        r = self._result(); a = r["a"]; c = r["cfg"]; table = "\n  " + json.dumps(a)[:2500] + "\n  errors: " + json.dumps(r["errors"])
        self.assertEqual([e for e in r["errors"] if e.startswith("timeout")], [], "every wait of stage A held" + table)
        self.assertIn(c["offCard"], a["frame"]["askIds"], table); self.assertIn(c["onCard0"], a["frame"]["askIds"], table)
        self.assertEqual(a["frame"]["offHosts"], [], "no host off" + table); self.assertEqual(a["frame"]["pendingHosts"], [], table)
        view = json.loads(a["store"]["view"])
        self.assertEqual(view["sec"].get(c["offCard"]), "subgoals", "HOSTOFF's card keeps the click" + table)
        self.assertEqual(view["sec"].get(c["onCard0"]), "subgoals", "HOSTON's card keeps the click" + table)
        marks = a["store"]["marks"]
        self.assertTrue(any(m.startswith("w|" + c["offCard"] + "|") and m.endswith("|@HOSTOFF") for m in marks), "HOSTOFF's mark names its host" + table)
        self.assertTrue(any(m.startswith("w|" + c["onCard0"] + "|") and m.endswith("|@HOSTON") for m in marks), "HOSTON's mark names its host" + table)
        rung = {n["itemId"] for n in a["notes"] if n["kind"] == "warn"}
        self.assertTrue({c["offCard"], c["onCard0"]} <= rung, "both warns rang the shell's bell" + table)

    def test_stage_b_the_medium_a_host_off_leaves_the_view_state_byte_identical_keeps_its_marks_prunes_the_on_hosts_absent_marks_and_the_new_card_still_rings(self):
        r = self._result(); a, b = r["a"], r["b"]; c = r["cfg"]; table = "\n  a: " + json.dumps(a["store"])[:1200] + "\n  b: " + json.dumps(b)[:2500] + "\n  errors: " + json.dumps(r["errors"])
        self.assertEqual([e for e in r["errors"] if e.startswith("timeout")], [], "every wait held" + table)
        self.assertEqual(b["frame"]["offHosts"], ["HOSTOFF"], "the merged frame names the off host, and no other" + table)
        self.assertFalse(b["frame"]["off"], "the frame's own off is the local kernel's word: on" + table)
        self.assertIn(c["onCard2"], b["frame"]["askIds"], "the new card rode the mixed frame" + table)
        self.assertNotIn(c["offCard"], b["frame"]["askIds"], "…without HOSTOFF's card, which was not built" + table)
        self.assertEqual(b["store"]["view"], a["store"]["view"], "romp:feedview byte-identical across the mixed frame: no writer pruned by absence" + table)
        marks = b["store"]["marks"]
        self.assertTrue(any(m.startswith("w|" + c["offCard"] + "|") for m in marks), "the off host's mark is kept" + table)
        self.assertNotIn(c["staleOnMark"], marks, "the on host's absent mark pruned: the store's bound" + table)
        self.assertNotIn(c["staleLocalMark"], marks, "the local host's absent mark pruned" + table)
        self.assertIn(c["staleOldMark"], marks, "a mark in the shape before round seven names no host: kept while a host is not in hand (low 1)" + table)
        self.assertTrue(any(m.startswith("w|" + c["onCard2"] + "|") and m.endswith("|@HOSTON") for m in marks), "the new card's mark is written" + table)
        rung_b = [n for n in b["notes"] if n["kind"] == "warn" and n["itemId"] == c["onCard2"]]
        self.assertEqual(len(rung_b), 1, "the new card's warn rang once" + table)

    def test_stage_b2_the_round_eight_medium_a_reload_while_a_host_is_off_keeps_the_marks_and_the_view_state_through_the_pending_first_frame(self):
        r = self._result(); b, b2 = r["b"], r["b2"]; c = r["cfg"]; table = "\n  b: " + json.dumps(b["store"])[:1200] + "\n  b2: " + json.dumps(b2)[:3000] + "\n  errors: " + json.dumps(r["errors"])
        self.assertEqual([e for e in r["errors"] if e.startswith("timeout")], [], "every wait held" + table)
        self.assertEqual(b2["store"]["view"], b["store"]["view"], "romp:feedview byte-identical across the reload: the pending first frame pruned nothing" + table)
        marks = b2["store"]["marks"]
        self.assertTrue(any(m.startswith("w|" + c["offCard"] + "|") for m in marks), "the off host's mark survived the reload" + table)
        for card in (c["onCard0"], c["onCard2"]):
            self.assertTrue(any(m.startswith("w|" + card + "|") for m in marks), "the on host's marks survived the reload: " + card + table)
        self.assertEqual([n for n in b2["notes"] if n["kind"] == "warn"], [], "no warn re-rang on the reload" + table)
        self.assertEqual(b2["frame"]["offHosts"], ["HOSTOFF"], table)

    def test_stage_c_the_off_host_back_on_with_its_card_re_rings_nothing(self):
        r = self._result(); cc = r["c"]; c = r["cfg"]; table = "\n  c: " + json.dumps(cc)[:2500] + "\n  errors: " + json.dumps(r["errors"])
        self.assertEqual([e for e in r["errors"] if e.startswith("timeout")], [], "every wait held" + table)
        self.assertEqual(cc["frame"]["offHosts"], [], table); self.assertEqual(cc["frame"]["pendingHosts"], [], table)
        self.assertIn(c["offCard"], cc["frame"]["askIds"], "HOSTOFF's card is back" + table)
        self.assertEqual([n for n in cc["notes"] if n["kind"] == "warn"], [], "its warn did not re-ring: the mark was kept" + table)
        view = json.loads(cc["store"]["view"])
        self.assertEqual(view["sec"].get(c["offCard"]), "subgoals", "HOSTOFF's disclosure entry stands, its card being back" + table)
        self.assertNotIn(c["staleOldMark"], cc["store"]["marks"], "every host in hand: the old-shape mark prunes by absence like any other" + table)

    def test_stage_d_a_plain_reload_with_every_host_on_re_rings_nothing(self):
        r = self._result(); d = r["d"]; c = r["cfg"]; table = "\n  d: " + json.dumps(d)[:3000] + "\n  errors: " + json.dumps(r["errors"])
        self.assertEqual([e for e in r["errors"] if e.startswith("timeout")], [], "every wait held" + table)
        self.assertEqual([n for n in d["notes"] if n["kind"] == "warn"], [], "no warn re-rang on the plain reload" + table)
        marks = d["store"]["marks"]
        for card in (c["onCard0"], c["onCard2"]):
            self.assertTrue(any(m.startswith("w|" + card + "|") for m in marks), "the on host's marks stand: " + card + table)

    def test_stage_c2_the_host_on_with_no_cards_resumes_pruning_its_entry_and_mark_leave_while_the_on_hosts_stand(self):
        r = self._result(); b, cc = r["b"], r["c2"]; c = r["cfg"]; table = "\n  b: " + json.dumps(b["store"])[:1200] + "\n  c2: " + json.dumps(cc)[:2500] + "\n  errors: " + json.dumps(r["errors"])
        self.assertEqual([e for e in r["errors"] if e.startswith("timeout")], [], "every wait held" + table)
        self.assertEqual(cc["frame"]["offHosts"], [], table)
        view = json.loads(cc["store"]["view"])
        self.assertNotIn(c["offCard"], view["sec"], "HOSTOFF's card left the frame for real: its disclosure entry prunes" + table)
        self.assertEqual(view["sec"].get(c["onCard0"]), "subgoals", "HOSTON's entry stands" + table)
        marks = cc["store"]["marks"]
        self.assertFalse(any(m.startswith("w|" + c["offCard"] + "|") for m in marks), "HOSTOFF's mark prunes" + table)
        self.assertTrue(any(m.startswith("w|" + c["onCard0"] + "|") for m in marks) and any(m.startswith("w|" + c["onCard2"] + "|") for m in marks), "HOSTON's marks stand" + table)

    def test_the_page_threw_nothing_and_every_frame_carried_the_per_host_lists(self):
        # round ten: the first-frame claim below is what a starved runner broke under the 1.5 s hold (see the SlowLoad class)
        r = self._result(); table = "\n  " + json.dumps(r["errors"]) + "\n  frames: " + json.dumps(r["frames"])[:2000]
        self.assertEqual([e for e in r["errors"] if e.startswith("page:")], [], "no uncaught error in the page" + table)
        merged = [f for f in r["frames"] + r["b2"]["frames"] + r["d"]["frames"] if f["offHosts"] is not None]
        self.assertGreater(len(merged), 2, "merged frames carry offHosts and pendingHosts" + table)
        self.assertTrue(all(f["pendingHosts"] is not None for f in merged), table)
        # round nine: the hook is an init script, so a reload's very first merged frame is on record. It is built before the first
        # /tunnels answer (held 1.5 s by the driver): no host off, none pending, and the frame says its host list is not read;
        # the store the next frame found is the store this one found, so nothing pruned on it
        for stage in ("b2", "d"):
            fr = [f for f in r[stage]["frames"] if f["offHosts"] is not None]
            self.assertGreaterEqual(len(fr), 2, stage + ": the first two merged frames are on record" + table)
            first = fr[0]
            self.assertEqual((first["offHosts"], first["pendingHosts"], first["hostsUnread"]), ([], [], True), stage + ": the first frame knows no host and says so" + table)
            self.assertEqual(fr[1]["before"], first["before"], stage + ": the store did not move across the unread frame" + table)
            self.assertTrue(any(f["hostsUnread"] is False and (f["pendingHosts"] or f["offHosts"] or f["askIds"]) for f in fr[1:]), stage + ": the list landed and the frames went on" + table)


if __name__ == "__main__":
    unittest.main()


class ServedTaskTrackingFederationSlowLoad(ServedTaskTrackingFederation):
    """The same lab with the feed frame's document answering 3 s late on every load: a starved runner's reload, the shape of
    the v0.17.0 cut's local red and of every run under a half-core quota (2026-09-24). The first merged frame of each reload
    must still be built before the host list is in hand, because the hold is on the frame, not on a clock; under round
    nine's 1.5 s hold this class reds on the first-frame assertion (the reproduction by delay, executed at the base)."""
    _r = None
    _fakes = None
    SLOW_FEED_MS = 3000

