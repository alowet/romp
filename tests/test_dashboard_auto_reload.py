"""The dashboard OFFERS a reload on a newer build and never reloads itself; a restart of the same build is invisible.

Three rulings, each superseding the last: 2026-07-13 (a banner the reader clicks), 2026-09-08 (T265: the page reloads
itself on a restart and on a newer bundle, never mid-gesture) and 2026-09-16 (the page never reloads itself: a same-build
restart owes nothing and says nothing, a newer build is one persistent line with Reload and Not now, Not now is kept per
build, an unknownOp refusal sharpens the wording, explicit gestures keep their reload, and a kernel that must force a
reload sends reloadRequired). The reload core (kernel.py _RELOAD_CORE_JS, window.__rompReload on every kernel-served
page) runs here for REAL: node executes the IIFE between its anchors with fakes for document, window, location,
sessionStorage, localStorage and fetch, one process per scenario (the core installs once per window), and the scenario
reads its state back by name; the offer hook's calls are recorded (OFFERS). The idle holds are exercised on an ACCEPTED
offer (R.accept(), the user's Reload click) or on the forced request. Pinned alongside: the wiring (the shim's raise,
the shim's reconnect, the shell's socket, the stale banner as the offer's home, the pages that embed the core) and the
remote exclusion (federation drops remote keepalives, so a REMOTE kernel's restart or bundle never reaches the core).
Synthetic values only."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from romp_load import load_source

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)
km = load_source("romp_kernel_autoreload", os.path.join(BIN, "romp-kernel"))

# The browser the core thinks it runs in. `var` at module scope shadows node's globals; the core's own
# `document.addEventListener` calls land in LISTENERS so a scenario can emit the gesture events by name.
HARNESS = r"""
var LISTENERS = {}, STORE = {}, LOCAL = {}, OFFERS = [], REMOVED = [], FETCHES = [], RELOADS = 0, REFUSE = false, PERSISTED = 0, WLISTENERS = {};
var SEL = { rangeCount: 0, isCollapsed: true, toString: function () { return ""; } };
var COMPOSER = { tagName: "TEXTAREA", value: "" };              // the chat composer, one editable among any
var FOCUSED = true;                                             // document.hasFocus()
var IFRAMES = [];
var SPLASH = [], HEALTH_BOOT = null;                            // the restart button's splash classes; the boot id /healthz answers with
var document = {
  createElement: function () { return { id: "", innerHTML: "", classList: { add: function (c) { SPLASH.push("+" + c); }, remove: function (c) { SPLASH.push("-" + c); } } }; },
  addEventListener: function (t, f) { (LISTENERS[t] = LISTENERS[t] || []).push(f); },
  getSelection: function () { return SEL; },
  hasFocus: function () { return FOCUSED; },
  getElementById: function (id) { return id === "composer-input" ? COMPOSER : null; },
  activeElement: null,
  body: { classList: { remove: function () { REMOVED.push(Array.prototype.slice.call(arguments)); } }, appendChild: function () {} },
  querySelectorAll: function () { return IFRAMES; }
};
var TIMERS = [], _setTimeout = globalThis.setTimeout, _clearTimeout = globalThis.clearTimeout;
function clearTimeout(id) { var t = TIMERS[id - 1]; if (t) t.cleared = true; else _clearTimeout(id); }   // a re-armed backstop retires its earlier entry
function liveTimers() { return TIMERS.filter(function (t) { return !t.cleared; }); }
var CLOCK = 0, _realNow = Date.now.bind(Date); Date.now = function () { return _realNow() + CLOCK; };   // a scenario advances the clock the core reads
function setTimeout(f, ms) { if (ms > 0) { TIMERS.push({ f: f, ms: ms, at: Date.now() }); return TIMERS.length; } return _setTimeout(f, ms); }   // `at`: when it was armed, so a scenario can advance the clock to its due instant   // a bound's backstop is recorded, never waited for; the zero-delay ticks run
var SHIM_PERSISTS = [];                                        // the panes' __rompShimPersist calls the core made before a reload
function pane(busy, since, other) { return { contentWindow: { __rompReload: { busyHere: function (skipFresh) { return skipFresh ? (other ? other() : '') : busy(); } }, __rompFreshPendingSince: since || 0,
                                                              __rompShimPersist: function () { SHIM_PERSISTS.push(1); } } }; }   // an iframe the shell's walk visits; `other` answers past the fresh answer
var DIAG = [];                                                  // what a pane's socket would carry up: the shell's held breadcrumb
var window = { addEventListener: function (t, f) { (WLISTENERS[t] = WLISTENERS[t] || []).push(f); } };
window.parent = window;
window.__rompPersistForReload = function () { PERSISTED++; };
var location = { pathname: "/", reload: function () { RELOADS++; if (REFUSE) throw new Error("host forbids reload"); } };
var sessionStorage = {
  setItem: function (k, v) { STORE[k] = v; }, getItem: function (k) { return k in STORE ? STORE[k] : null; },
  removeItem: function (k) { delete STORE[k]; }
};
var localStorage = {                                            // the Not now's home: per build, across this browser's pages
  setItem: function (k, v) { LOCAL[k] = v; }, getItem: function (k) { return k in LOCAL ? LOCAL[k] : null; },
  removeItem: function (k) { delete LOCAL[k]; }
};
var VERSION = null;
function fetch(u) { FETCHES.push(u); return Promise.resolve({ ok: true, status: 200, json: function () { return Promise.resolve(VERSION); },
  headers: { get: function (k) { return k === "X-Romp-Boot" ? HEALTH_BOOT : null; } } }); }   // ok and status: the core checks them before the body; the boot header: the restart button's poll
function emit(t) { (LISTENERS[t] || []).forEach(function (f) { f({}); }); }
function wemit(t) { (WLISTENERS[t] || []).forEach(function (f) { f({}); }); }
function tick() { return new Promise(function (r) { setTimeout(r, 0); }); }
function state() {
  var R = window.__rompReload;
  return { reloads: RELOADS, fired: R.fired(), owed: R.owed(), offered: R.offered(), waiting: R.waiting, persisted: PERSISTED, removed: REMOVED.slice(), refusedFor: R.refusedFor(),
           stored: STORE["romp:reloaded"] ? JSON.parse(STORE["romp:reloaded"]) : null, reason: STORE["romp:reloadReason"] ? JSON.parse(STORE["romp:reloadReason"]) : null,
           notNow: LOCAL["romp:reloadNotNow"] ? JSON.parse(LOCAL["romp:reloadNotNow"]) : null, fetches: FETCHES.length };
}
function out(o) { process.stdout.write("RESULT:" + JSON.stringify(o) + "\n"); }
"""


OFFER = "A newer romp build is ready."
BEHIND = "A newer romp build is ready; this page is behind the kernel and some actions fall back to older paths until you reload."


def run_core(scenario, v=7, boot="1.1", code="abc1234", local=None):
    """`local`: what this browser's localStorage holds before the page loads (a Not now from an earlier page)."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not installed")
    d = tempfile.mkdtemp(prefix="reload-core-")
    path = os.path.join(d, "core.js")
    with open(path, "w") as f:
        f.write(HARNESS + ("LOCAL = %s;\n" % json.dumps({k: json.dumps(v_) for k, v_ in (local or {}).items()}))
                + km._reload_core_js(v, boot, code)
                + "\nif(window.__rompReload)window.__rompReload.offer=function(o){OFFERS.push(o);};\n"   # the offer hook, as the shell or a standalone pane installs one
                + "(async function(){\n" + scenario + "\n})();\n")
    r = subprocess.run([node, path], capture_output=True, text=True, timeout=60)
    shutil.rmtree(d, ignore_errors=True)
    if r.returncode != 0:
        raise AssertionError("node failed:\n" + r.stderr)
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("RESULT:")), None)
    assert line, "no RESULT line:\n" + r.stdout
    return json.loads(line[len("RESULT:"):])


class ReloadCoreExecuted(unittest.TestCase):
    def test_a_newer_dv_is_offered_and_the_accepted_offer_reloads_at_once_when_idle_and_persists_first(self):
        s = run_core("""
var R = window.__rompReload;
R.noteDv(7); var same = state();          // the page's own build
R.noteDv(5); var older = state();         // an OLDER token (a rolled-back peer) is not drift
R.noteDv(8); var offered = state();       // a newer one: the offer, and nothing else (2026-09-16)
R.accept();                               // the user's Reload
out({ same: same, older: older, offered: offered, offers: OFFERS, after: state() });""")
        self.assertEqual(s["same"]["reloads"], 0); self.assertIsNone(s["same"]["offered"])
        self.assertEqual(s["older"]["reloads"], 0); self.assertIsNone(s["older"]["offered"])
        o = s["offered"]
        self.assertEqual(o["reloads"], 0, "a newer build is offered, never taken")
        self.assertIsNone(o["owed"], "nothing owed: no hold, no backstop, no line")
        self.assertEqual(o["offered"], {"dv": 8, "code": "", "behind": False, "text": OFFER})
        self.assertEqual(s["offers"], [{"dv": 8, "code": "", "behind": False, "text": OFFER}, None], "the hook saw the offer, then its retirement at the accept")
        a = s["after"]
        self.assertEqual(a["reloads"], 1)
        self.assertTrue(a["fired"])
        self.assertEqual(a["stored"]["reason"], "build")
        self.assertEqual(a["stored"]["detail"], "8")
        self.assertEqual(a["stored"]["from"], 7)
        self.assertEqual(a["stored"]["path"], "/", "the marker names the page that reloaded")
        self.assertEqual(a["reason"], {"reason": "build", "path": "/", "t": a["reason"]["t"]}, "the durable record for the chat pane's diet is written by the accepted reload")
        self.assertEqual(a["persisted"], 1, "the pane's persist hook ran before the reload")
        self.assertIn(["settings-open", "picker-open"], a["removed"], "the lifted modals close")

    def test_a_restart_is_a_reopen_against_a_new_boot_id_and_the_boot_id_alone_owes_nothing(self):
        s = run_core("""
var R = window.__rompReload;
VERSION = { boot: "1.1", dist_ver: 7 }; R.checkBoot(); await tick(); await tick(); var blip = state();
VERSION = { boot: "2.2", dist_ver: 7 }; R.checkBoot(); await tick(); await tick();
out({ blip: blip, restarted: R.restarted(), after: state(), offers: OFFERS });""")
        self.assertEqual(s["blip"]["reloads"], 0, "the same kernel answered: a socket blip, not a restart")
        self.assertEqual(s["blip"]["fetches"], 1)
        self.assertEqual(s["restarted"], 1, "the new boot id is a restart, counted")
        self.assertEqual(s["after"]["reloads"], 0, "and owes nothing by itself (2026-09-16)")
        self.assertIsNone(s["after"]["owed"]); self.assertIsNone(s["after"]["offered"]); self.assertEqual(s["offers"], [])

    def test_a_restart_with_an_unchanged_build_never_reloads_and_never_offers(self):
        """Invisible restarts (the user 2026-09-14, restated 2026-09-16 as the ruling's first point): a new boot id with the
        SAME code identity and dist_ver is a restart of the build this page already runs; the board stays on screen, the
        shim's redial carries the diet, no reload is owed, no offer stands, no hold and no line."""
        s = run_core("""
var R = window.__rompReload;
var held = 0; R.held = function () { held++; };
VERSION = { boot: "2.2", dist_ver: 7, code_ident: "abc1234" }; R.checkBoot(); await tick(); await tick();
VERSION = { boot: "2.2", dist_ver: 7, code_ident: "abc1234" }; R.checkBoot(); await tick(); await tick();   // the poll after the restart
out({ after: state(), restarted: R.restarted(), offers: OFFERS, held: held, timers: TIMERS.length });""", code="abc1234")
        self.assertEqual(s["after"]["reloads"], 0, "the same build restarted: nothing to reload onto")
        self.assertIsNone(s["after"]["owed"]); self.assertIsNone(s["after"]["offered"])
        self.assertEqual(s["offers"], [], "no offer: nothing newer is served")
        self.assertEqual(s["held"], 0, "no hold, so no notification-center line"); self.assertEqual(s["timers"], 0, "no backstop armed")
        self.assertEqual(s["restarted"], 1, "the restart was seen and counted once; the poll after it is not another")

    def test_a_restart_onto_a_changed_build_is_offered_and_the_accepted_reload_waits_for_the_reconnected_panes_first_frame(self):
        s = run_core("""
var R = window.__rompReload;
window.__rompFreshPending = true;                       // the shim's redial is awaiting its resync frame
window.__rompFreshPendingSince = Date.now();
VERSION = { boot: "2.2", dist_ver: 7, code_ident: "def5678" }; R.checkBoot(); await tick(); await tick(); var offered = state();
R.accept(); var held = state();
window.__rompFreshPending = false; R.ended(); await tick(); await tick();
out({ offered: offered, held: held, after: state() });""", code="abc1234")
        self.assertEqual(s["offered"]["reloads"], 0, "a changed build is offered, never taken (2026-09-16)")
        self.assertIsNone(s["offered"]["owed"])
        self.assertEqual(s["offered"]["offered"], {"dv": 0, "code": "def5678", "behind": False, "text": OFFER}, "the offer names the code identity that changed")
        self.assertEqual(s["held"]["reloads"], 0, "accepted but held: the reload must land on a warm kernel")
        self.assertEqual(s["held"]["owed"], {"reason": "build", "detail": "def5678"})
        self.assertEqual(s["held"]["waiting"], "fresh")
        self.assertEqual(s["after"]["reloads"], 1, "the resync frame is the ending event")
        self.assertEqual(s["after"]["stored"]["reason"], "build")
        self.assertEqual(s["after"]["stored"]["detail"], "def5678")

    def test_a_version_without_a_code_identity_decides_nothing_on_a_restart(self):
        # a kernel whose /version carries no identity (one from before 2026-09-14; a body that lost the field) says nothing about
        # the build: the dist_ver stands alone, and a restart never reloads (2026-09-16; before it the fail-safe was a reload)
        s = run_core("""
var R = window.__rompReload;
VERSION = { boot: "2.2", dist_ver: 7 }; R.checkBoot(); await tick(); await tick();
out({ after: state(), restarted: R.restarted(), offers: OFFERS });""", code="abc1234")
        self.assertEqual(s["after"]["reloads"], 0); self.assertIsNone(s["after"]["offered"]); self.assertEqual(s["offers"], [])
        self.assertEqual(s["restarted"], 1)

    def test_the_fresh_hold_is_read_from_the_panes_the_shell_holds_and_a_pane_that_never_arms_it_holds_nothing(self):
        """The shell's walk over its panes, executed over two fakes of busyHere (the reload accepted from the offer the changed build
        stood): the chat pane holds while its flag stands, the
        other pane never does, and the chat pane's ending event fires the reload. A pin, green at the round-one head: the walk
        existed there. The round-two medium (the shim arming the hold in every pane, the Files page never clearing it) has its
        red in ui/webview/pane-shim-stale.test.ts, which runs the real shim; the fakes here stand in for what that shim does."""
        s = run_core("""
var R = window.__rompReload;
var chat = { pending: true, since: Date.now() };
IFRAMES = [pane(function () { return ''; }),                                                            // a Files pane: nothing to wait for
           pane(function () { return chat.pending && Date.now() - chat.since < 60000 ? 'fresh' : ''; })];  // the chat pane's busyHere, the core's own rule
VERSION = { boot: "2.2", dist_ver: 7, code_ident: "def5678" }; R.checkBoot(); await tick(); await tick(); R.accept(); var held = state();
chat.pending = false; R.ended(); await tick(); await tick();
out({ held: held, after: state() });""", code="abc1234")
        self.assertEqual(s["held"]["reloads"], 0)
        self.assertEqual(s["held"]["waiting"], "fresh", "the walk found the chat pane's hold")
        self.assertEqual(s["after"]["reloads"], 1, "the chat pane's frame ended it")
        self.assertEqual(s["after"]["stored"]["detail"], "def5678", "the record names the build the page lands on")

    def test_a_fresh_hold_older_than_the_bound_no_longer_holds_and_the_backstop_runs_the_walk_once_more(self):
        """A frame that never comes must not hold a deploy's reload forever (the round-two review): the hold is read with its
        stamp, one older than the bound no longer counts, and the shell arms one backstop timer for the bound when it first
        holds on 'fresh', so the reload fires without any event once the bound has passed."""
        s = run_core("""
var R = window.__rompReload;
window.__rompFreshPending = true; window.__rompFreshPendingSince = Date.now();
VERSION = { boot: "2.2", dist_ver: 7, code_ident: "def5678" }; R.checkBoot(); await tick(); await tick(); R.accept(); var held = state();
var armed = TIMERS.map(function (t) { return t.ms; });
R.tryFire(); var armedAgain = TIMERS.length;                                     // a second walk while held arms no second timer
window.__rompFreshPendingSince = Date.now() - 60001;                              // the bound passes with the flag still up
TIMERS[0].f(); await tick(); await tick();
var expiredAtOnce = null;
out({ held: held, armed: armed, armedAgain: armedAgain, after: state() });""", code="abc1234")
        self.assertEqual(s["held"]["waiting"], "fresh")
        self.assertEqual(len(s["armed"]), 1, "one backstop for the bound, armed when the hold was first seen")
        self.assertTrue(59000 <= s["armed"][0] <= 60000, "armed for the window's edge, a minute from the stamp: %r" % s["armed"])
        self.assertEqual(s["armedAgain"], 1)
        self.assertEqual(s["after"]["reloads"], 1, "the backstop's walk fired the reload once the hold was older than the bound")
        self.assertEqual(s["after"]["stored"]["reason"], "build")
        t = run_core("""
var R = window.__rompReload;
window.__rompFreshPending = true; window.__rompFreshPendingSince = Date.now() - 60001;   // a stale flag: some earlier redial's, never cleared
VERSION = { boot: "2.2", dist_ver: 7, code_ident: "def5678" }; R.checkBoot(); await tick(); await tick(); R.accept();
out({ after: state(), timers: TIMERS.length });""", code="abc1234")
        self.assertEqual(t["after"]["reloads"], 1, "a flag older than the bound holds nothing")
        self.assertEqual(t["timers"], 0)

    def test_the_fresh_bound_is_per_page_across_staggered_chat_columns(self):
        """Round three's low 1: two chat columns whose drops stagger by 40 s chained two bounds (the backstop found the second
        pane inside its own minute and re-armed), so the reload landed at 120 s where the line says a minute at most. The
        shell keys the bound on the earliest stamp its walk has seen: at the first stamp plus the bound every pane's hold
        is over, and one backstop fires the reload."""
        s = run_core("""
var R = window.__rompReload;
var t0 = Date.now() - 60000;                                                     // the first column dropped a minute ago
IFRAMES = [pane(function () { return ''; }, 0),                                  // a Files pane
           pane(function () { return 'fresh'; }, t0),                             // the first chat column, its own stamp at the bound
           pane(function () { return 'fresh'; }, t0 + 40000)];                    // the second, dropped 40 s later, inside its own bound
VERSION = { boot: "2.2", dist_ver: 7, code_ident: "def5678" }; R.checkBoot(); await tick(); await tick(); R.accept();
out({ after: state(), timers: TIMERS.length });""", code="abc1234")
        self.assertEqual(s["after"]["reloads"], 1, "the page's bound is the first column's, not the last's")
        self.assertEqual(s["after"]["stored"]["reason"], "build")
        t = run_core("""
var R = window.__rompReload;
var t0 = Date.now() - 30000;
IFRAMES = [pane(function () { return 'fresh'; }, t0), pane(function () { return 'fresh'; }, t0 + 20000)];
VERSION = { boot: "2.2", dist_ver: 7, code_ident: "def5678" }; R.checkBoot(); await tick(); await tick(); R.accept(); var held = state();
IFRAMES[0].contentWindow.__rompReload.busyHere = function () { return ''; };     // the first column's frame lands
R.ended(); await tick(); await tick(); var stillHeld = state();
out({ held: held, stillHeld: stillHeld, timers: TIMERS.length });""", code="abc1234")
        self.assertEqual(t["held"]["waiting"], "fresh", "inside the bound both columns hold")
        self.assertEqual(t["stillHeld"]["waiting"], "fresh", "the second column still awaits its frame inside the page's bound")
        self.assertEqual(t["stillHeld"]["reloads"], 0)
        self.assertEqual(t["timers"], 1, "one backstop per hold")
        # round four, low 1: the stamp resets whenever no pane holds fresh, even while another hold stands, so a later, genuinely
        # new drop is judged by its own stamp (executed: a drop, its frame while the user types, the backstop, a second drop,
        # the draft cleared five seconds into the redial: the pane must still hold)
        w = run_core("""
var R = window.__rompReload;
var chat = { hold: 'fresh' };
IFRAMES = [pane(function () { return chat.hold; }, Date.now())];
R.noteDv(8); R.accept(); var first = state();                                              // held on the drop
CLOCK += 5000; chat.hold = ''; document.activeElement = COMPOSER; COMPOSER.value = "a draft";
R.ended(); await tick(); await tick(); var typingHeld = state();               // the frame landed; the draft holds
CLOCK += 65000; TIMERS.shift().f(); await tick(); await tick();                // the backstop: still typing
CLOCK += 10000; chat.hold = 'fresh'; IFRAMES[0].contentWindow.__rompFreshPendingSince = Date.now();   // a second drop
CLOCK += 5000; document.activeElement = null; R.ended(); await tick(); await tick();
out({ first: first, typingHeld: typingHeld, after: state() });""")
        self.assertEqual(w["first"]["waiting"], "fresh")
        self.assertEqual(w["typingHeld"]["waiting"], "typing")
        self.assertEqual(w["after"]["reloads"], 0, "five seconds into a new redial the pane still holds; the old stamp is gone")
        self.assertEqual(w["after"]["waiting"], "fresh")

    def test_a_hold_standing_for_the_bound_files_one_breadcrumb_through_a_panes_socket(self):
        """A page that never reloads after a deploy was unreadable from the kernel (the 8:04 PM PT boot of 2026-09-14): the
        shell now files one clientDiag row, surface reload-core, what held, with the reason, the hold and its age, through
        a pane's diagnostics door (the shim's __rompDiag, its own socket) when a hold has stood for the bound; once per owed
        request, and never for a hold that ended. The core names no send route of its own (the federation pin below)."""
        s = run_core("""
var R = window.__rompReload;
IFRAMES = [pane(function () { return 'typing'; }, 0)];
IFRAMES[0].contentWindow.__rompDiag = function (what, data) { DIAG.push({ what: what, data: data }); };
R.noteDv(8); R.accept(); var held = state();
var armed = TIMERS.map(function (t) { return t.ms; });
CLOCK += 60000; TIMERS.shift().f(); await tick(); await tick(); var afterOne = { diag: DIAG.slice(), timers: TIMERS.length, state: state() };
CLOCK += 60000; TIMERS.shift().f(); await tick(); await tick(); var afterTwo = { diag: DIAG.slice(), state: state() };
IFRAMES[0].contentWindow.__rompReload.busyHere = function () { return ''; }; R.ended(); await tick(); await tick();
out({ held: held, armed: armed, afterOne: afterOne, afterTwo: afterTwo, after: state() });""")
        self.assertEqual(s["held"]["waiting"], "typing")
        self.assertEqual(s["armed"], [60000], "the backstop is armed for any hold, not the fresh one alone")
        self.assertEqual(len(s["afterOne"]["diag"]), 1, "one breadcrumb when the bound passed with the hold standing")
        row = s["afterOne"]["diag"][0]
        self.assertEqual(row["what"], "held")
        self.assertIn('window.__rompDiag=function(what,data){try{send({type:"clientDiag",surface:"reload-core",what:what,data:data});}catch(e){}};', km._shim("chat", 5),
                      "the pane's door carries it up its own socket as a clientDiag row of surface reload-core (ui/webview/pane-shim-stale.test.ts runs it)")
        self.assertEqual([row["data"]["reason"], row["data"]["detail"], row["data"]["hold"]], ["build", "8", "typing"])
        self.assertGreaterEqual(row["data"]["ageMs"], 0)
        self.assertEqual(s["afterOne"]["state"]["reloads"], 0, "typing is unbounded by design: still held")
        self.assertEqual(s["afterOne"]["timers"], 1, "the backstop re-arms while the hold stands")
        self.assertEqual(len(s["afterTwo"]["diag"]), 1, "filed once per owed request, not once per minute")
        self.assertEqual(s["after"]["reloads"], 1, "the draft's focus leaving ends the hold")

        t = run_core("""
var R = window.__rompReload;
IFRAMES = [pane(function () { return 'sends'; }, 0)];
IFRAMES[0].contentWindow.__rompDiag = function (what, data) { DIAG.push({ what: what, data: data }); };
R.noteDv(8); R.accept();
IFRAMES[0].contentWindow.__rompReload.busyHere = function () { return ''; }; R.ended(); await tick(); await tick();
CLOCK += 60000; TIMERS.shift().f(); await tick(); await tick();
out({ diag: DIAG.length, after: state() });""")
        self.assertEqual(t["after"]["reloads"], 1)
        self.assertEqual(t["diag"], 0, "a hold that ended before the bound files nothing")

    def test_a_second_reason_for_the_same_wait_files_no_second_breadcrumb(self):
        # round four, low 2: a forced request arriving while the accepted reload is held is the same wait, not a new one; the latch
        # clears only when the owed request itself changes
        u = run_core("""
var R = window.__rompReload;
IFRAMES = [pane(function () { return 'typing'; }, 0)];
IFRAMES[0].contentWindow.__rompDiag = function (what, data) { DIAG.push({ what: what, data: data }); };
R.noteDv(8); R.accept(); CLOCK += 60000; TIMERS.shift().f(); await tick(); await tick();
R.request("required", "a forced request inside the same wait"); CLOCK += 60000; TIMERS.shift().f(); await tick(); await tick();
out({ diag: DIAG.length, owed: state().owed });""")
        self.assertEqual(u["owed"]["reason"], "build", "the first request stands")
        self.assertEqual(u["diag"], 1, "a second reason for the same wait files no second row")

    def test_a_bound_reached_with_no_door_files_the_row_at_the_next_bound(self):
        # round four, low 3: the latch is set only once a door took the row; no pane yet, or a door that throws, retries
        v = run_core("""
var R = window.__rompReload;
IFRAMES = [pane(function () { return 'typing'; }, 0)];
R.noteDv(8); R.accept(); CLOCK += 60000; TIMERS.shift().f(); await tick(); await tick(); var none = DIAG.length;
IFRAMES[0].contentWindow.__rompDiag = function () { throw new Error("a door that throws"); };
CLOCK += 60000; TIMERS.shift().f(); await tick(); await tick(); var thrown = DIAG.length;
IFRAMES[0].contentWindow.__rompDiag = function (what, data) { DIAG.push({ what: what, data: data }); };
CLOCK += 60000; TIMERS.shift().f(); await tick(); await tick();
out({ none: none, thrown: thrown, later: DIAG.length });""")
        self.assertEqual(v["none"], 0, "no door yet: nothing filed")
        self.assertEqual(v["thrown"], 0, "a door that throws files nothing and does not latch")
        self.assertEqual(v["later"], 1, "the row is not lost: the next bound files it through the door that appeared")

    def test_a_pane_that_drops_after_the_fresh_window_ended_opens_its_own_while_an_older_pane_still_answers_fresh(self):
        """The 1698 lows, low 4: the page's fresh bound is a window. A column that dropped at the first minute's start and never
        got its frame keeps answering fresh with its old stamp; a column that drops AFTER that minute ended must not be judged
        by the old stamp (a ten-second-old redial read as expired, and the reload fired over it). Panes that drop inside a
        running window still join it (the round-three requirement: two staggered columns, one minute)."""
        s = run_core("""
var R = window.__rompReload;
var t0 = Date.now();
var a = pane(function () { return 'fresh'; }, t0);                              // its frame never comes
IFRAMES = [a];
R.noteDv(8); R.accept(); var first = state();
document.activeElement = COMPOSER; COMPOSER.value = "a draft that spans the bound";        // the draft begins inside the minute
CLOCK += 65000; TIMERS.shift().f(); await tick(); await tick(); var afterBound = state();   // the window ended; typing holds
CLOCK += 5000; var tB = Date.now(); var b = pane(function () { return 'fresh'; }, tB); IFRAMES = [a, b];   // a second column drops now
CLOCK += 10000; document.activeElement = null; R.ended(); await tick(); await tick();          // the draft clears ten seconds later
var held = state();
// the backstop stands for the next event ahead (an earlier hold's cadence, then the new window's EDGE): the walks run there
var fired = 0; for (var k = 0; k < 3 && state().reloads === 0; k++) { var t = liveTimers().pop(); if (!t) break; CLOCK += Math.max(0, t.at + t.ms - Date.now()); t.f(); await tick(); await tick(); fired++; }   // the clock moves to the timer's due instant
out({ first: first, afterBound: afterBound, held: held, fired: fired, sinceB: Date.now() - tB, atEdge: state(), shimPersists: SHIM_PERSISTS.length });""")
        self.assertEqual(s["first"]["waiting"], "fresh", "the first column's minute")
        self.assertEqual(s["afterBound"]["waiting"], "typing", "past the minute only the draft holds")
        self.assertEqual(s["held"]["reloads"], 0, "the new column's redial keeps its own minute")
        self.assertEqual(s["held"]["waiting"], "fresh")
        # the round-three review's item 4: the backstop is armed for the window's edge, so the reload lands within the minute of
        # the reconnect, not at the next tick of a fixed cadence (measured before: a reload 55 s late)
        self.assertEqual(s["atEdge"]["reloads"], 1, "the walk at the edge fires the reload")
        self.assertLessEqual(s["sinceB"], 61000, "within a minute of the second column's reconnect (a second of real clock inside the run): %r ms, %r backstops" % (s["sinceB"], s["fired"]))
        self.assertEqual(s["shimPersists"], 2, "the core asked every pane's shim to say what its queue still held")
        t = run_core("""
var R = window.__rompReload;
var t0 = Date.now();
IFRAMES = [pane(function () { return 'fresh'; }, t0)];
R.noteDv(8); R.accept();
CLOCK += 40000; IFRAMES.push(pane(function () { return 'fresh'; }, Date.now()));   // a second column drops inside the window
CLOCK += 20000; TIMERS.shift().f(); await tick(); await tick();
out({ after: state() });""")
        self.assertEqual(t["after"]["reloads"], 1, "a drop inside the running window joins it and ends with it: one minute for the page")

    def test_a_panes_fresh_answer_does_not_mask_its_upload_at_the_windows_edge(self):
        """The round-four review's high, pre-existing: a pane answering fresh was read as fresh alone, so at the page window's edge
        the reload fired over that pane's upload or queued sends. The walk asks a fresh pane again for its other holds."""
        s = run_core("""
var R = window.__rompReload;
var t0 = Date.now();
IFRAMES = [pane(function () { return 'fresh'; }, t0),                                            // column A
           pane(function () { return 'fresh'; }, t0 + 20000, function () { return 'upload'; })];   // column B, an upload in flight
R.noteDv(8); R.accept(); var held = state();
CLOCK += 65000; liveTimers().pop().f(); await tick(); await tick(); var atEdge = state();          // the window's edge
IFRAMES[1].contentWindow.__rompReload.busyHere = function () { return ''; }; R.ended(); await tick(); await tick();
out({ held: held, atEdge: atEdge, after: state() });""")
        self.assertEqual(s["held"]["waiting"], "upload", "the upload outranks the fresh answer from the first walk")
        self.assertEqual(s["atEdge"]["reloads"], 0, "at the edge the upload still holds")
        self.assertEqual(s["atEdge"]["waiting"], "upload")
        self.assertEqual(s["after"]["reloads"], 1, "the upload's end lets the reload go")

    def test_the_backstop_never_re_arms_itself_at_zero_delay(self):
        """The round-four review's medium: with the window's edge in the past and a draft standing, the backstop was armed for
        a past instant and the walk repeated at the browser's clamp, hundreds of times a second. An edge already past is
        not an event: the timer stands for the next stamp's expiry or the ordinary cadence, always ahead."""
        s = run_core("""
var R = window.__rompReload;
IFRAMES = [pane(function () { return 'fresh'; }, Date.now())];
document.activeElement = COMPOSER; COMPOSER.value = "a draft";
R.noteDv(8); R.accept();
var delays = [];
for (var i = 0; i < 5; i++) { CLOCK += 65000; var t = liveTimers().pop(); delays.push(t ? t.ms : null); if (t) t.f(); await tick(); await tick(); }
out({ delays: delays, timers: TIMERS.length, after: state() });""")
        self.assertTrue(all(d and d > 1000 for d in s["delays"]), "every backstop stands for a future instant: %r" % s["delays"])
        self.assertLessEqual(s["timers"], 8, "one timer per walk, never a storm: %r" % s["timers"])
        self.assertEqual(s["after"]["reloads"], 0, "the draft still holds")

    def test_a_pane_detached_between_the_listing_and_the_call_holds_nothing_and_the_walk_goes_on(self):
        # the 1715 lows, low 1 (pre-existing): the walk's first busyHere call on a pane was outside any try, so a pane whose
        # window went away between panes() and the call threw out of busy() and tryFire(): no reload and no backstop
        s = run_core("""
var R = window.__rompReload;
IFRAMES = [{ contentWindow: { __rompReload: { busyHere: function () { throw new Error("detached"); } }, __rompFreshPendingSince: 0 } },
           pane(function () { return 'upload'; }, 0)];
R.noteDv(8); R.accept(); var held = state();
IFRAMES[1].contentWindow.__rompReload.busyHere = function () { return ''; }; R.ended(); await tick(); await tick();
out({ held: held, after: state() });""")
        self.assertEqual(s["held"]["waiting"], "upload", "the second pane's hold is read past the first pane's throw")
        self.assertEqual(s["after"]["reloads"], 1, "and the reload goes when it ends")

    def test_the_bells_connection_line_names_the_pane_by_the_page_side_label_helper(self):
        """The 1715 lows, low 4: the bell's line read PN[m.app] || m.app, the raw key for a page outside the label list; the
        page's helper mirrors _pane_label (the rail's word, else the key capitalised), run here for every key."""
        holders = [n for n in dir(km) if isinstance(getattr(km, n, None), str) and "var PN=" in getattr(km, n)]
        self.assertEqual(len(holders), 1, holders)
        js = getattr(km, holders[0])
        self.assertIn("'Kernel connection lost: '+paneLabel(m.app)+' pane (reconnecting)'", js, "the line reads the helper")
        line_expr = "'Kernel connection lost: '+paneLabel(m.app)+' pane (reconnecting)'"
        a = js.index("var PN=")
        fn_start = js.index("function paneLabel(k){", a)
        slice_js = js[a:js.index("}", js.index("return PN[k]", fn_start)) + 1]
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not installed")
        probe = slice_js + """
var OUT = {}, LINES = {}; ["chat", "timeline", "fleet", "feed", "files", "settings", "shell", ""].forEach(function (k) { OUT[k] = paneLabel(k); var m = { app: k }; LINES[k] = """ + line_expr + """; });
process.stdout.write("RESULT:" + JSON.stringify({ labels: OUT, lines: LINES }) + "\\n");
"""
        d = tempfile.mkdtemp(prefix="pane-label-")
        path = os.path.join(d, "label.js")
        with open(path, "w") as f:
            f.write(probe)
        r = subprocess.run([node, path], capture_output=True, text=True, timeout=60)
        shutil.rmtree(d, ignore_errors=True)
        self.assertEqual(r.returncode, 0, "node failed:\n" + r.stderr)
        res = json.loads(next(ln for ln in r.stdout.splitlines() if ln.startswith("RESULT:"))[len("RESULT:"):])
        out = res["labels"]
        self.assertEqual(out, {"chat": "Chat", "timeline": "Sessions", "fleet": "Outline", "feed": "Feed", "files": "Files",
                               "settings": "Settings", "shell": "Shell", "": ""})
        for k, v in out.items():
            self.assertEqual(v, km._pane_label(k) if k else "", k)
        # the produced notice text, driven (the 1725 lows, low 2), in the reader's words: no em-dash (the user's writing rule)
        self.assertEqual(res["lines"]["settings"], "Kernel connection lost: Settings pane (reconnecting)")
        self.assertEqual(res["lines"]["fleet"], "Kernel connection lost: Outline pane (reconnecting)")
        for k, line in res["lines"].items():
            self.assertNotIn("\u2014", line, k); self.assertNotIn("fleet", line, k)

    def test_a_pane_whose_door_throws_on_the_read_does_not_end_the_search_for_a_door(self):
        # the 1725 lows, low 4 (pre-existing): the door walk wrapped the whole loop in one try, so one pane throwing on the read
        # ended the search and no door took the row on that pass
        s = run_core("""
var R = window.__rompReload;
var bad = pane(function () { return 'typing'; }, 0); Object.defineProperty(bad.contentWindow, "__rompDiag", { get: function () { throw new Error("detached"); } });
var good = pane(function () { return ''; }, 0); good.contentWindow.__rompDiag = function (what, data) { DIAG.push({ what: what, data: data }); };
IFRAMES = [bad, good];
R.noteDv(8); R.accept(); CLOCK += 60000; TIMERS.shift().f(); await tick(); await tick();
out({ diag: DIAG.length });""")
        self.assertEqual(s["diag"], 1, "the next pane's door took the row")

    def test_a_door_that_throws_when_called_does_not_end_the_search_either(self):
        # round two, low 4: a door that throws when CALLED (not read) ended the search on every pass and cost the breadcrumb
        s = run_core("""
var R = window.__rompReload;
var bad = pane(function () { return 'typing'; }, 0); bad.contentWindow.__rompDiag = function () { throw new Error("a door that throws"); };
var good = pane(function () { return ''; }, 0); good.contentWindow.__rompDiag = function (what, data) { DIAG.push({ what: what, data: data }); };
IFRAMES = [bad, good];
R.noteDv(8); R.accept(); CLOCK += 60000; TIMERS.shift().f(); await tick(); await tick();
out({ diag: DIAG.length });""")
        self.assertEqual(s["diag"], 1, "the next pane's door took the row on the same pass")

    def test_the_breadcrumbs_age_counts_from_the_holds_start_not_the_last_backstop(self):
        # the 1698 lows, low 3: a row filed at a later bound (no door at the earlier ones) read 60000 for a three-minute hold
        s = run_core("""
var R = window.__rompReload;
IFRAMES = [pane(function () { return 'typing'; }, 0)];
R.noteDv(8); R.accept();
CLOCK += 60000; TIMERS.shift().f(); await tick(); await tick();                 // no door yet
CLOCK += 60000; TIMERS.shift().f(); await tick(); await tick();                 // still none
IFRAMES[0].contentWindow.__rompDiag = function (what, data) { DIAG.push({ what: what, data: data }); };
CLOCK += 60000; TIMERS.shift().f(); await tick(); await tick();
out({ diag: DIAG });""")
        self.assertEqual(len(s["diag"]), 1)
        self.assertGreaterEqual(s["diag"][0]["data"]["ageMs"], 180000, "three minutes held, three minutes said")

    def test_every_pane_names_itself_by_its_label_never_its_key(self):
        """The round-three review's medium A: a line a pane says about itself read the Outline pane's internal key and would
        read the Sessions pane's for that pane. The shim bakes LABEL from _pane_label, the one map every surface renders
        (_PANE_ORDER), rendered here for every key; a source grep of added lines cannot catch an interpolated key."""
        labels = dict(km._PANE_ORDER)
        self.assertEqual(labels["fleet"], "Outline"); self.assertEqual(labels["timeline"], "Sessions")
        for app in list(labels) + ["settings"]:
            label = getattr(km, "_pane_label", lambda a: "")(app)   # the map is this change's: at the base the red is the assertion
            self.assertEqual(label, labels.get(app, "Settings"), app)
            self.assertNotIn("fleet", label.lower(), app); self.assertNotIn("timeline", label.lower(), app)
            js = km._shim(app, 5, no_stale=(app in ("files", "settings")))
            self.assertIn('var APP="%s";var LABEL="%s";' % (app, label), js, "the shim bakes the label beside the key")
            self.assertIn('" queued for the "+LABEL+" pane could not be sent before the dashboard reloaded; "', js, "the loss line reads the label")
        self.assertIn("try{if(ps[i].__rompShimPersist)ps[i].__rompShimPersist();}catch(e){}", km._reload_core_js(5, "1.1", "abc"),
                      "the core asks every pane's shim what its queue still holds, right before the reload")

    def test_build_drift_after_a_reconnect_reloads_once_the_chat_pane_has_its_frame(self):
        # the pre-existing build-drift reload after any reconnect (the round-two review found it held forever behind a Files pane
        # whose flag stood unstamped and uncleared): an unstamped flag holds nothing, a stamped one holds until the frame
        s = run_core("""
var R = window.__rompReload;
window.__rompFreshPending = true;                                                  // a flag with no stamp: never a hold
R.noteDv(8); R.accept(); var unstamped = state();
out({ unstamped: unstamped });""")
        self.assertEqual(s["unstamped"]["reloads"], 1, "a flag without a stamp holds nothing")
        t = run_core("""
var R = window.__rompReload;
IFRAMES = [pane(function () { return ''; })];
window.__rompFreshPending = true; window.__rompFreshPendingSince = Date.now();
R.noteDv(8); R.accept(); var held = state();
window.__rompFreshPending = false; R.ended(); await tick(); await tick();
out({ held: held, after: state() });""")
        self.assertEqual(t["held"]["waiting"], "fresh")
        self.assertEqual(t["held"]["owed"]["reason"], "build")
        self.assertEqual(t["after"]["reloads"], 1)

    def test_restarted_counts_restarts_and_one_changed_build_across_two_restarts_is_one_offer(self):
        # lows b and c of the round-two review: BOOT re-latches so the polls after a restart do not count again; since 2026-09-16
        # the same changed build seen across two boots is ONE offer (the hook is not called again), and the accepted reload's
        # record names the build, not a boot
        s = run_core("""
var R = window.__rompReload;
R.noteVersion({ boot: "2.2", dist_ver: 7, code_ident: "abc1234" }); R.noteVersion({ boot: "2.2", dist_ver: 7, code_ident: "abc1234" });
var one = R.restarted();
R.noteVersion({ boot: "3.3", dist_ver: 7, code_ident: "abc1234" }); var two = R.restarted(); var quiet = state();
window.__rompFreshPending = true; window.__rompFreshPendingSince = Date.now();
var heldCalls = 0; R.held = function () { heldCalls++; };
R.noteVersion({ boot: "4.4", dist_ver: 7, code_ident: "def5678" }); var offersAfterOne = OFFERS.length;
R.noteVersion({ boot: "5.5", dist_ver: 7, code_ident: "def5678" }); var offersAfterTwo = OFFERS.length; var offered = state();
R.accept(); var owed = state().owed;
window.__rompFreshPending = false; R.ended(); await tick(); await tick();
out({ one: one, two: two, quiet: quiet, offersAfterOne: offersAfterOne, offersAfterTwo: offersAfterTwo, offered: offered, owed: owed, heldCalls: heldCalls, after: state() });""", code="abc1234")
        self.assertEqual(s["one"], 1, "two polls of one restarted kernel count one restart")
        self.assertEqual(s["two"], 2, "a further boot id counts again")
        self.assertIsNone(s["quiet"]["offered"], "the same build across two restarts offers nothing")
        self.assertEqual([s["offersAfterOne"], s["offersAfterTwo"]], [1, 1], "one changed build, one offer, whatever the boot count")
        self.assertEqual(s["offered"]["offered"]["code"], "def5678"); self.assertEqual(s["offered"]["reloads"], 0)
        self.assertEqual(s["owed"], {"reason": "build", "detail": "def5678"}, "the accepted request names the build")
        self.assertEqual(s["heldCalls"], 1, "one wait, announced once")
        self.assertEqual(s["after"]["stored"]["detail"], "def5678")

    def test_both_held_maps_render_the_fresh_wording_when_run(self):
        """The held hooks executed (round three, low 3): the pane's (installed by the shim on a standalone page, rendering into
        its bar) and the shell's (installed by the stale block, a notification-center line), each sliced from its source and
        run under node over fakes of the sink: the fresh hold renders the wording that names the chat pane and the bound, a
        gesture hold renders nothing."""
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not installed")
        shim = km._shim("chat", 5)
        a = shim.index("window.__rompReload.held=function(b){")
        pane_fn = shim[a + len("window.__rompReload.held="):shim.index("};", a) + 2]
        stale = km._STALE_JS
        b = stale.index("RL.held=function(b){")
        shell_fn = stale[b + len("RL.held="):stale.index("};", b) + 2]
        js = """
var OUT = [];
var window = { __rompNotify: function (k, t) { OUT.push(["shell", k, t]); } };
function selfBar(t, k) { OUT.push(["pane", k, t]); }
var pane = %s;
var shell = %s;
["fresh", "pointer", "typing", "selection", "upload", "sends"].forEach(function (b) { pane(b, { reason: "restart" }); shell(b, { reason: "restart" }); });
process.stdout.write("RESULT:" + JSON.stringify(OUT) + "\\n");
""" % (pane_fn, shell_fn)
        d = tempfile.mkdtemp(prefix="held-maps-")
        path = os.path.join(d, "held.js")
        with open(path, "w") as f:
            f.write(js)
        r = subprocess.run([node, path], capture_output=True, text=True, timeout=60)
        shutil.rmtree(d, ignore_errors=True)
        self.assertEqual(r.returncode, 0, "node failed:\n" + r.stderr)
        line = next((ln for ln in r.stdout.splitlines() if ln.startswith("RESULT:")), None)
        out = json.loads(line[len("RESULT:"):])
        wording = "The dashboard will reload onto the new build once the chat pane has caught up, within a minute of its reconnect."
        typing = "The dashboard will reload onto the new build once the draft is sent or cleared."
        selection = "The dashboard will reload onto the new build once the selected text is released."
        upload = "The dashboard will reload once the upload in progress finishes."
        sends = "The dashboard will reload once the queued messages have left, a minute at most."   # the sends hold carries its bound too (round four, low 4)
        # typing and selection stay unbounded by design, so they say what the page waits on (the manager 2026-09-14: a user with a
        # draft saw stale UI after a deploy with no clue); pointer, pan and drag are momentary and stay silent
        self.assertEqual([o for o in out if o[0] == "pane"],
                         [["pane", "held", wording], ["pane", "held", typing], ["pane", "held", selection], ["pane", "held", upload], ["pane", "held", sends]],
                         "the pane's bar: the fresh, typing, selection and upload wordings; nothing for the pointer")
        self.assertEqual([o for o in out if o[0] == "shell"],
                         [["shell", "reload", wording], ["shell", "reload", typing], ["shell", "reload", selection], ["shell", "reload", upload], ["shell", "reload", sends]],
                         "the shell's notification center: the same")

    def test_the_settings_restart_button_hands_the_new_kernels_answer_to_the_reload_core(self):
        """Round three, low 5b: the rail's restart button polled /healthz until a NEW boot id answered and then reloaded the page
        unconditionally, an exception to the ruling. Now the flip drops the splash and hands the decision to the reload core:
        the same code restarted reloads nothing (the panes redial), a changed build is OFFERED (2026-09-16: the user asked for
        a restart, not a reload; the ↻ keeps no reload of its own). The button's function is sliced from the served landing
        and run over the harness's fetch (a /healthz answering with the boot header, then /version), the core baked beside
        it. tests/test_kernel_refresh_button.py pins the button's source."""
        html = km._landing()
        a = html.index("window.__rompRestart=function(){")
        fn = html[a:html.index("var rf=document.getElementById('rail-refresh');", a)]
        self.assertNotIn("if(b&&b!==%s)location.reload()" % json.dumps(km._BOOT_ID), fn, "the flip no longer reloads by itself")
        self.assertIn("window.__rompReload.checkBoot()", fn)
        same = run_core(fn + """
var R = window.__rompReload;
HEALTH_BOOT = "9.9"; VERSION = { boot: "9.9", dist_ver: 7, code_ident: "abc1234" };
window.__rompRestart();
var polls = TIMERS.map(function (t) { return t.ms; });
TIMERS.shift().f(); await tick(); await tick(); await tick(); await tick();
out({ polls: polls, splash: SPLASH, fetches: FETCHES, restarted: R.restarted(), after: state() });""", code="abc1234")
        self.assertEqual(same["polls"], [500], "one poll armed for the new kernel's answer")
        self.assertEqual(same["fetches"][:1], ["/restart"])
        self.assertIn("/healthz", same["fetches"])
        self.assertIn("/version", same["fetches"], "the flip asked the core, which read /version")
        self.assertEqual(same["restarted"], 1, "the core counted the restart")
        self.assertEqual(same["after"]["reloads"], 0, "the same code restarted: the board stays")
        self.assertIsNone(same["after"]["owed"]); self.assertIsNone(same["after"]["offered"])
        self.assertEqual(same["splash"][-1], "+gone", "the splash the button raised is dropped when the new kernel answers")
        changed = run_core(fn + """
var R = window.__rompReload;
HEALTH_BOOT = "9.9"; VERSION = { boot: "9.9", dist_ver: 7, code_ident: "def5678" };
window.__rompRestart(); TIMERS.shift().f(); await tick(); await tick(); await tick(); await tick(); var offered = state();
R.accept(); await tick();
out({ offered: offered, after: state() });""", code="abc1234")
        self.assertEqual(changed["offered"]["reloads"], 0, "a changed build is offered through the core, not taken (2026-09-16)")
        self.assertEqual(changed["offered"]["offered"]["code"], "def5678"); self.assertIsNone(changed["offered"]["owed"])
        self.assertEqual(changed["after"]["reloads"], 1, "the user's Reload takes it")
        self.assertEqual(changed["after"]["stored"], {"reason": "build", "detail": "def5678", "from": 7, "path": "/", "t": changed["after"]["stored"]["t"]})

    def test_the_code_identity_changes_with_the_bytes_of_the_kernel_code(self):
        """Low d of the round-two review: a dirty tree reads the same git sha before and after an edit, so the identity the core
        compares is over the code's bytes. Over a private tree: stable across calls, changed by one byte, the environment
        stand-in wins, and /version carries it."""
        import importlib
        d = tempfile.mkdtemp(prefix="code-ident-")
        os.makedirs(os.path.join(d, "kernel"))
        with open(os.path.join(d, "kernel", "a.py"), "w") as f:
            f.write("x = 1\n")
        old_root = km.ROOT
        try:
            km.ROOT = type(old_root)(d)
            km._CODE_IDENT[0] = None
            first = km._code_ident()
            km._CODE_IDENT[0] = None
            self.assertEqual(km._code_ident(), first, "the same bytes read the same identity")
            self.assertRegex(first, r"^[0-9a-f]{12}$")
            with open(os.path.join(d, "kernel", "a.py"), "w") as f:
                f.write("x = 2\n")
            km._CODE_IDENT[0] = None
            self.assertNotEqual(km._code_ident(), first, "one changed byte is a changed build")
            km._CODE_IDENT[0] = None
            os.environ["ROMP_CODE_IDENT"] = "lab-build"
            try:
                self.assertEqual(km._code_ident(), "lab-build")
            finally:
                del os.environ["ROMP_CODE_IDENT"]
                km._CODE_IDENT[0] = None
            self.assertEqual(km._version_info()["code_ident"], km._code_ident(), "/version carries the identity the core compares")
            os.remove(os.path.join(d, "kernel", "a.py"))
            km._CODE_IDENT[0] = None
            self.assertEqual(km._code_ident(), "", "no kernel code at all reads empty, never a hash of nothing that compares equal across builds (round three, low 5a)")
        finally:
            km.ROOT = old_root
            km._CODE_IDENT[0] = None
            shutil.rmtree(d, ignore_errors=True)

    def test_the_reload_cores_and_the_bells_user_facing_lines_carry_no_em_dash(self):
        # the user's writing rule bars them; the reload line and the bell's filter descriptions and connection lines carried one
        import re as _re
        core = km._reload_core_js(5, "1.1", "abc")
        self.assertNotIn("\u2014", core); self.assertIn("'Reloaded onto build '+LOADED+': '+why+'.'", core)
        holder = next(getattr(km, n) for n in dir(km) if isinstance(getattr(km, n, None), str) and "var PN=" in getattr(km, n))
        # the code lines of every page script the reload road serves: the bell holder, the pane shim and the stale block; a
        # trailing comment is cut at its first `//` after whitespace, whatever the spacing (round two, low 3)
        for name, js in (("the bell holder", holder), ("the pane shim", km._shim("chat", 5)), ("the stale block", km._STALE_JS)):
            for ln in js.splitlines():
                if ln.lstrip().startswith("//") or ln.lstrip().startswith("#"):
                    continue
                body = _re.split(r"\s+//", ln, maxsplit=1)[0]
                self.assertNotIn("\\u2014", body, "%s: %s" % (name, body[:100])); self.assertNotIn("\u2014", body, "%s: %s" % (name, body[:100]))

    def test_the_shim_arms_the_fresh_hold_on_a_reconnect_and_the_resync_frame_ends_it(self):
        js = km._shim("chat", 5)
        self.assertIn('if(openSock===this){armFresh();', js, "the drop arms the hold the core reads: the shell's socket may reopen and ask /version before this pane redials")
        self.assertIn('pendingWhy="";freshPending=true;armFresh();', js, "the reopen restamps it")
        self.assertIn('pendingWhy="foreground";freshPending=true;armFresh();', js, "and the foreground redial")
        self.assertIn('function armFresh(){if(APP==="chat"){if(!window.__rompFreshPending)window.__rompFreshPendingSince=Date.now();window.__rompFreshPending=true;}}', js,
                      "the chat pane alone, stamped once per hold for the bound (ui/webview/pane-shim-stale.test.ts runs it)")
        self.assertIn('if(freshPending){freshPending=false;window.__rompFreshPending=false;clearStale();try{if(window.__rompReload)window.__rompReload.ended();}catch(e){}}', js,
                      "the first real frame clears it and is the ending event")
        core = km._reload_core_js(5, "1.1", "abc")
        self.assertIn("try{if(!skipFresh&&window.__rompFreshPending&&Date.now()-(window.__rompFreshPendingSince||0)<FRESH_HOLD_MS)return 'fresh';}catch(e){}", core,
                      "the pane's own fresh check, skipped when the shell's walk asks again for the pane's other holds")
        self.assertIn('var LOADED=5,BOOT="1.1",CODE="abc",FRESH_HOLD_MS=60000,', core, "the page's own code identity is baked beside its build and boot")
        wording = "The dashboard will reload onto the new build once the chat pane has caught up, within a minute of its reconnect."
        self.assertIn(wording, js, "the held wording, the pane's bar")
        self.assertIn(wording, km._STALE_JS, "and the shell's")
        self.assertIn("CODE=%s," % json.dumps(km._code_ident() or ""), km._reload_core(), "the served core bakes this kernel's code identity")

    def test_version_readings_feed_both_signals(self):
        s = run_core("""
var R = window.__rompReload;
R.noteVersion({ boot: "1.1", dist_ver: 7 }); var quiet = state();
R.noteVersion({ boot: "1.1", dist_ver: 9 }); var offered = state();
R.accept();
out({ quiet: quiet, offered: offered, after: state() });""")
        self.assertEqual(s["quiet"]["reloads"], 0); self.assertIsNone(s["quiet"]["offered"])
        self.assertEqual(s["offered"]["offered"]["dv"], 9, "the poll's dist_ver is the same signal as the keepalive's dv")
        self.assertEqual(s["offered"]["reloads"], 0)
        self.assertEqual(s["after"]["stored"]["reason"], "build")

    def test_a_held_pointer_arms_and_the_pointerup_fires(self):
        s = run_core("""
var R = window.__rompReload;
emit("pointerdown");
R.noteDv(8); R.accept(); var held = state();
emit("pointerup"); var atOnce = state(); await tick();
out({ held: held, atOnce: atOnce, after: state() });""")
        self.assertEqual(s["held"]["reloads"], 0)
        self.assertEqual(s["held"]["waiting"], "pointer")
        self.assertEqual(s["held"]["owed"]["reason"], "build", "armed, not dropped")
        self.assertEqual(s["atOnce"]["reloads"], 0, "the fire waits one tick so the click the same press produces lands on its control first")
        self.assertEqual(s["after"]["reloads"], 1)

    def test_a_drag_in_flight_arms_and_dragend_fires(self):
        s = run_core("""
var R = window.__rompReload;
emit("dragstart"); R.noteDv(8); R.accept(); var held = state(); emit("dragend"); await tick();
out({ held: held, after: state() });""")
        self.assertEqual(s["held"]["waiting"], "drag")
        self.assertEqual(s["held"]["reloads"], 0)
        self.assertEqual(s["after"]["reloads"], 1)

    def test_a_selection_being_made_arms_and_its_collapse_fires(self):
        s = run_core("""
var R = window.__rompReload;
SEL = { rangeCount: 1, isCollapsed: false, toString: function () { return "some words"; } };
R.noteDv(8); R.accept(); var held = state();
SEL = { rangeCount: 1, isCollapsed: true, toString: function () { return ""; } }; emit("selectionchange"); await tick();
out({ held: held, after: state() });""")
        self.assertEqual(s["held"]["waiting"], "selection")
        self.assertEqual(s["held"]["reloads"], 0)
        self.assertEqual(s["after"]["reloads"], 1)

    def test_a_composer_with_text_and_focus_arms_and_emptying_or_blurring_fires(self):
        s = run_core("""
var R = window.__rompReload;
document.activeElement = COMPOSER; COMPOSER.value = "half a thought";
R.noteDv(8); R.accept(); var held = state();
COMPOSER.value = "half a thought, more"; emit("input"); await tick(); var typing = state();
COMPOSER.value = ""; emit("input"); await tick();
out({ held: held, typing: typing, after: state() });""")
        self.assertEqual(s["held"]["waiting"], "typing")
        self.assertEqual(s["typing"]["reloads"], 0, "typing keeps the hold")
        self.assertEqual(s["after"]["reloads"], 1, "an emptied composer releases it")
        s2 = run_core("""
var R = window.__rompReload;
document.activeElement = COMPOSER; COMPOSER.value = "draft"; R.noteDv(8); R.accept();
document.activeElement = null; emit("focusout"); await tick();
out({ after: state() });""")
        self.assertEqual(s2["after"]["reloads"], 1, "a blurred composer releases it (the draft is persisted already)")

    def test_a_window_blur_releases_every_hold(self):
        s = run_core("""
var R = window.__rompReload;
emit("pointerdown"); emit("dragstart"); R.noteDv(8); R.accept(); var held = state(); wemit("blur"); await tick();
out({ held: held, after: state() });""")
        self.assertEqual(s["held"]["reloads"], 0)
        self.assertEqual(s["after"]["reloads"], 1)

    def test_a_refused_reload_puts_the_offer_back(self):
        # a page whose parent forbids location.reload: the accepted offer returns as an offer (the line with its Reload), the user
        # may try again, and nothing re-attempts on its own; a strictly newer build is a new offer
        s = run_core("""
var R = window.__rompReload; var refused = [];
R.refused = function (o) { refused.push(o); }; REFUSE = true;
R.noteDv(8); R.accept(); var first = state();
emit("pointerup"); await tick(); emit("selectionchange"); await tick(); R.noteVersion({ boot: "1.1", dist_ver: 8 }); var again = state();
R.accept(); var retried = state();
REFUSE = false; R.noteDv(9); var newer = state(); R.accept();
out({ refused: refused, first: first, again: again, retried: retried, newer: newer, after: state(), offers: OFFERS });""")
        f = s["first"]
        self.assertEqual(f["reloads"], 1, "the reload was attempted")
        self.assertFalse(f["fired"], "…and stood down when the parent threw")
        self.assertEqual(f["waiting"], "refused")
        self.assertEqual(f["refusedFor"], "build:8", "the refusal latches for this build")
        self.assertEqual(f["stored"], None, "no marker and no un-lifted modal for a reload that never happened")
        self.assertEqual(f["removed"], [])
        self.assertIsNone(f["owed"], "nothing owed any more"); self.assertEqual(f["offered"]["dv"], 8, "the offer is back")
        self.assertEqual(s["refused"][0], {"reason": "build", "detail": "8"})
        self.assertEqual(s["again"]["reloads"], 1, "gesture ends and the poll do not re-attempt the refused build")
        self.assertEqual(s["retried"]["reloads"], 2, "the user's second Reload tries again (refused again here)")
        self.assertEqual(s["newer"]["offered"]["dv"], 9, "a strictly newer build is a new offer")
        self.assertEqual(s["after"]["reloads"], 3); self.assertTrue(s["after"]["fired"])
        self.assertEqual([o and o["dv"] for o in s["offers"]], [8, None, 8, None, 8, 9, None], "offer, accept; back, accept; back, replaced by 9 in place; accepted")

    def test_the_fresh_page_announces_once_from_the_marker(self):
        s = run_core("""
var R = window.__rompReload; var notes = [];
STORE["romp:reloaded"] = JSON.stringify({ reason: "restart", detail: "2.2", from: 6, t: 1 });
var first = R.announce(function (k, t) { notes.push([k, t]); });
var second = R.announce(function (k, t) { notes.push([k, t]); });
out({ first: first, second: second, notes: notes, left: STORE["romp:reloaded"] || null });""")
        self.assertEqual(s["first"], "Reloaded onto build 7: the kernel restarted.")
        self.assertEqual(s["notes"], [["reload", "Reloaded onto build 7: the kernel restarted."]])
        self.assertIsNone(s["second"], "one line per reload")
        self.assertIsNone(s["left"], "the marker is consumed")
        s2 = run_core("""
var R = window.__rompReload;
STORE["romp:reloaded"] = JSON.stringify({ reason: "build", detail: "9", from: 6, t: 1 });
out({ first: R.announce(null) });""")
        self.assertEqual(s2["first"], "Reloaded onto build 7: a newer romp build was served.")
        s2b = run_core("""
var R = window.__rompReload;
STORE["romp:reloaded"] = JSON.stringify({ reason: "required", detail: "a wire change", from: 6, t: 1 });
out({ first: R.announce(null) });""")
        self.assertEqual(s2b["first"], "Reloaded onto build 7: the kernel asked for a reload (a wire change).", "the safety valve's reload says so")
        s3 = run_core("""
var R = window.__rompReload;
STORE["romp:reloaded"] = JSON.stringify({ reason: "build", detail: "9", from: 6, path: "/feed", t: 1 });
out({ first: R.announce(null), left: STORE["romp:reloaded"] || null });""")
        self.assertIsNone(s3["first"], "a marker another page wrote (a standalone /feed reload) is not this page's to announce")
        self.assertIsNotNone(s3["left"], "…and it is LEFT for the page it names (T272, 2026-09-08): sessionStorage is shared across the shell "
                                         "and its same-origin panes, and a pane's shim that read as standalone for a beat consumed the "
                                         "shell's marker before the path check — the shell then found nothing to announce, and the "
                                         "notification-center line the served test waits for never appeared")
        # the shell's marker (path "/") survives a pane's early announce and is announced by the shell itself, once
        s4 = run_core("""
var R = window.__rompReload; var notes = [];
STORE["romp:reloaded"] = JSON.stringify({ reason: "restart", detail: "2.2", from: 6, path: "/", t: 1 });
location.pathname = "/chat"; var pane = R.announce(null);
location.pathname = "/"; var shell = R.announce(function (k, t) { notes.push([k, t]); }); var again = R.announce(null);
out({ pane: pane, shell: shell, again: again, notes: notes, left: STORE["romp:reloaded"] || null });""")
        self.assertIsNone(s4["pane"], "the chat pane leaves the shell's marker alone")
        self.assertEqual(s4["shell"], "Reloaded onto build 7: the kernel restarted.", "the shell announces its own reload")
        self.assertEqual(s4["notes"], [["reload", "Reloaded onto build 7: the kernel restarted."]])
        self.assertIsNone(s4["again"], "one line per reload"); self.assertIsNone(s4["left"], "consumed by its own page")

    def test_the_shell_composes_gesture_state_across_its_panes_and_a_pane_forwards_its_request(self):
        s = run_core("""
var R = window.__rompReload;
var paneBusy = "pointer";
var pane = { __rompReload: { busyHere: function () { return paneBusy; } }, __rompPersistForReload: function () { PERSISTED += 10; } };
IFRAMES = [{ contentWindow: pane }];
R.request("build", "8"); var held = state();
paneBusy = ""; R.tryFire();            // the pane's ending event calls the shell's tryFire
out({ held: held, after: state() });""")
        self.assertEqual(s["held"]["reloads"], 0)
        self.assertEqual(s["held"]["waiting"], "pointer", "a pane's held pointer holds the shell's reload")
        self.assertEqual(s["after"]["reloads"], 1)
        self.assertEqual(s["after"]["persisted"], 11, "the shell and every pane persisted before the reload")
        # a pane under a same-origin shell forwards every decision: its proposal, the accept, the dismiss, the behind and the
        # forced request; its own core never offers and never fires (ONE offer for the top document)
        s2 = run_core("""
var shellReqs = [];
window.parent = { __rompReload: { request: function (r, d) { shellReqs.push([r, d]); }, propose: function (dv, code) { shellReqs.push(["propose", dv, code]); },
  accept: function () { shellReqs.push(["accept"]); }, dismiss: function () { shellReqs.push(["dismiss"]); }, behind: function () { shellReqs.push(["behind"]); },
  tryFire: function () { shellReqs.push(["tryFire"]); } } };
var R = window.__rompReload;
R.noteDv(8); R.accept(); R.dismiss(); R.behind(); R.require("a wire change"); emit("pointerup"); await tick();
out({ shellReqs: shellReqs, inShell: R.inShell(), after: state(), offers: OFFERS });""")
        self.assertTrue(s2["inShell"])
        self.assertEqual(s2["shellReqs"], [["propose", 8, ""], ["accept"], ["dismiss"], ["behind"], ["required", "a wire change"], ["tryFire"]])
        self.assertEqual(s2["after"]["reloads"], 0, "the top document reloads, never the pane alone")
        self.assertIsNone(s2["after"]["offered"]); self.assertEqual(s2["offers"], [], "the pane's own hook is never called")

    def test_a_panes_queued_sends_hold_the_reload_until_its_flush(self):
        s = run_core("""
var R = window.__rompReload; var queued = 1;
window.__rompPaneBusy = function () { return queued ? "sends" : ""; };   // the shim: everConnected && queue.length > queuedDiag
R.noteDv(8); R.accept(); var held = state();                            // the offer accepted while the pane's queue holds
queued = 0; R.ended(); await tick();                                    // the shim's ws.onopen flush
out({ held: held, after: state() });""")
        self.assertEqual(s["held"]["reloads"], 0, "a prompt typed during the outage sits in the pane's queue: the shell's earlier reopen must not take the page down")
        self.assertEqual(s["held"]["waiting"], "sends")
        self.assertEqual(s["after"]["reloads"], 1, "the flush is the ending event")

    def test_a_held_reload_wears_a_face_once_per_hold_and_never_for_a_gesture(self):
        # T272 follow-up (the manager's review): nothing displayed the core's `waiting`, so a reload held by a pane's
        # reason (an upload in flight) sat invisible. The `held` hook fires once per owed request and reason — the shell
        # files a notification-center line, a standalone pane raises its bar — and never for a momentary gesture hold.
        s = run_core("""
var R = window.__rompReload; var held = []; R.held = function (b, o) { held.push([b, o && o.reason]); };
var busyReason = "upload";
window.__rompPaneBusy = function () { return busyReason; };
R.noteDv(8); R.accept();                              // accepted, held on the pane's upload
R.ended(); await tick(); R.ended(); await tick();     // re-asks while the same hold stands: no second line
busyReason = "held-send"; R.ended(); await tick();    // the reason changed: one line for it
busyReason = ""; R.ended(); await tick();             // idle: fires
out({ held: held, reloads: RELOADS, waiting: R.waiting });""")
        self.assertEqual(s["held"], [["upload", "build"], ["held-send", "build"]], "once per hold reason, with the owed request")
        self.assertEqual(s["reloads"], 1)
        s2 = run_core("""
var R = window.__rompReload; var held = []; R.held = function (b) { held.push(b); };
emit("pointerdown"); R.noteDv(8); R.accept();           // a held pointer: a gesture hold, no line
var during = state();
emit("pointerup"); await tick();
out({ held: held, during: during, reloads: RELOADS });""")
        self.assertEqual(s2["during"]["waiting"], "pointer")
        self.assertEqual(s2["held"], ["pointer"], "the hook is told every hold; the shell's line filters gestures out (the two held maps)")
        self.assertEqual(s2["reloads"], 1)

    def test_a_touch_pan_holds_from_pointercancel_until_the_finger_lifts(self):
        s = run_core("""
var R = window.__rompReload;
emit("pointerdown"); emit("pointercancel");       // the touch became a scroll: the browser cancels the pointer, the finger is still down
R.noteDv(8); R.accept(); var panning = state();
emit("pointerup"); await tick(); var stillPanning = state();   // no pointerup comes for a cancelled pointer, but even one must not release the pan
emit("touchend"); await tick();
out({ panning: panning, stillPanning: stillPanning, after: state() });""")
        self.assertEqual(s["panning"]["reloads"], 0)
        self.assertEqual(s["panning"]["waiting"], "pan")
        self.assertEqual(s["stillPanning"]["reloads"], 0)
        self.assertEqual(s["after"]["reloads"], 1, "touchend releases the pan")

    def test_a_selection_counts_only_in_the_focused_document(self):
        s = run_core("""
var R = window.__rompReload;
SEL = { rangeCount: 1, isCollapsed: false, toString: function () { return "an old highlight"; } };
FOCUSED = false; R.noteDv(8); R.accept();
out({ after: state() });""")
        self.assertEqual(s["after"]["reloads"], 1, "a highlight left in a pane the user is not in is not a gesture being made")

    def test_typing_in_any_editable_holds_not_only_the_composer(self):
        s = run_core("""
var R = window.__rompReload;
var pickerInput = { tagName: "INPUT", type: "text", value: "new-sess" };
document.activeElement = pickerInput; R.noteDv(8); R.accept(); var held = state();
var sel = { tagName: "SELECT", value: "x" }; document.activeElement = sel; emit("focusout"); await tick();
out({ held: held, after: state() });""")
        self.assertEqual(s["held"]["waiting"], "typing", "the new-session picker's name box holds like the composer")
        self.assertEqual(s["held"]["reloads"], 0)
        self.assertEqual(s["after"]["reloads"], 1, "a focused <select> is not text entry")

    def test_a_foreign_parent_leaves_the_pane_to_reload_itself(self):
        s = run_core("""
Object.defineProperty(window, "parent", { get: function () { throw new Error("cross-origin"); } });
var R = window.__rompReload; R.noteDv(8); R.accept();
out({ inShell: R.inShell(), after: state() });""")
        self.assertFalse(s["inShell"])
        self.assertEqual(s["after"]["reloads"], 1, "an iframe in another app reloads itself")


class ReloadOfferExecuted(unittest.TestCase):
    """The ruling of 2026-09-16, executed in the real core."""

    def test_a_same_build_restart_is_silent_and_a_newer_build_is_one_offer_with_no_hold_and_no_timer(self):
        s = run_core("""
var R = window.__rompReload;
var held = 0; R.held = function () { held++; };
VERSION = { boot: "2.2", dist_ver: 7, code_ident: "abc1234" }; R.checkBoot(); await tick(); await tick(); var restart = state();
R.noteDv(8); var once = state(); R.noteDv(8); R.noteVersion({ boot: "2.2", dist_ver: 8, code_ident: "abc1234" });   // the keepalives and polls after it
out({ restart: restart, restarted: R.restarted(), once: once, after: state(), offers: OFFERS, held: held, timers: TIMERS.length });""", code="abc1234")
        self.assertEqual([s["restart"]["reloads"], s["restart"]["owed"], s["restart"]["offered"], s["restarted"]], [0, None, None, 1], "a same-build restart: counted, nothing else")
        self.assertEqual(s["once"]["offered"], {"dv": 8, "code": "", "behind": False, "text": OFFER})
        self.assertEqual(s["offers"], [{"dv": 8, "code": "", "behind": False, "text": OFFER}], "one offer per build, however many readings carry it")
        self.assertEqual([s["after"]["reloads"], s["after"]["owed"], s["held"], s["timers"]], [0, None, 0, 0], "an offer owes nothing: no reload, no hold, no line, no backstop")

    def test_not_now_is_kept_per_build_and_a_strictly_newer_build_re_offers(self):
        s = run_core("""
var R = window.__rompReload;
R.noteDv(8); R.dismiss(); var declined = state();
R.noteDv(8); R.noteVersion({ boot: "1.1", dist_ver: 8 }); var still = state();
R.noteDv(9); var newer = state();
out({ declined: declined, still: still, newer: newer, offers: OFFERS });""")
        self.assertIsNone(s["declined"]["offered"]); self.assertEqual(s["declined"]["notNow"], {"dv": 8, "code": ""}, "the Not now is kept, per build, in localStorage")
        self.assertIsNone(s["still"]["offered"], "the declined build stays quiet through every later reading")
        self.assertEqual(s["newer"]["offered"]["dv"], 9, "a strictly newer build is new information")
        self.assertEqual([o and o["dv"] for o in s["offers"]], [8, None, 9])
        # another page of this browser (a second tab on the same build) reads the kept Not now
        t = run_core("""
var R = window.__rompReload;
R.noteDv(8); var quiet = state(); R.noteDv(9); var offered = state();
out({ quiet: quiet, offered: offered });""", local={"romp:reloadNotNow": {"dv": 8, "code": ""}})
        self.assertIsNone(t["quiet"]["offered"], "declined in another tab: quiet here too")
        self.assertEqual(t["offered"]["offered"]["dv"], 9)
        # the code identity: declined for one, another re-offers; and a declined build seen with BOTH signals stays declined
        u = run_core("""
var R = window.__rompReload;
R.noteVersion({ boot: "2.2", dist_ver: 8, code_ident: "def5678" }); var both = state(); R.dismiss();
R.noteVersion({ boot: "2.2", dist_ver: 8, code_ident: "def5678" }); var quiet = state();
R.noteVersion({ boot: "3.3", dist_ver: 8, code_ident: "ghi9012" }); var other = state();
out({ both: both, quiet: quiet, other: other, notNow: state().notNow });""", code="abc1234")
        self.assertEqual(u["both"]["offered"], {"dv": 8, "code": "def5678", "behind": False, "text": OFFER}, "one offer carries both signals")
        self.assertIsNone(u["quiet"]["offered"]); self.assertEqual(u["notNow"], {"dv": 8, "code": "def5678"})
        self.assertEqual(u["other"]["offered"]["code"], "ghi9012", "another code identity re-offers")
        # a malformed Not now record is read as none
        v = run_core("""
var R = window.__rompReload; R.noteDv(8); out({ after: state() });""", local={"romp:reloadNotNow": "junk"})
        self.assertEqual(v["after"]["offered"]["dv"], 8)

    def test_an_unknown_op_refusal_sharpens_the_standing_offers_wording_once_and_latches_for_a_later_one(self):
        s = run_core("""
var R = window.__rompReload;
R.noteDv(8); R.behind(); R.behind(); R.noteDv(8);
out({ after: state(), offers: OFFERS });""")
        self.assertEqual([o["text"] for o in s["offers"]], [OFFER, BEHIND], "the wording moves once; a second refusal and the next keepalive repaint nothing")
        self.assertEqual(s["after"]["offered"], {"dv": 8, "code": "", "behind": True, "text": BEHIND})
        self.assertEqual(s["after"]["reloads"], 0, "still an offer: a refusal never reloads")
        t = run_core("""
var R = window.__rompReload;
R.behind(); var none = state(); R.noteDv(8);
out({ none: none, offers: OFFERS });""")
        self.assertIsNone(t["none"]["offered"], "a refusal alone offers nothing: nothing newer is known")
        self.assertEqual([o["text"] for o in t["offers"]], [BEHIND], "the offer that comes later wears the reason")

    def test_the_safety_valve_is_a_forced_request_through_the_same_holds(self):
        s = run_core("""
var R = window.__rompReload;
emit("pointerdown"); R.require("a wire change"); var held = state();
emit("pointerup"); await tick();
out({ held: held, after: state() });""")
        self.assertEqual(s["held"]["owed"], {"reason": "required", "detail": "a wire change"})
        self.assertEqual([s["held"]["reloads"], s["held"]["waiting"]], [0, "pointer"], "forced, yet never mid-gesture")
        self.assertEqual(s["after"]["reloads"], 1)
        self.assertEqual(s["after"]["stored"]["reason"], "required"); self.assertEqual(s["after"]["reason"]["reason"], "required")


class ReloadWiringPinned(unittest.TestCase):
    def test_the_panes_and_the_shell_hand_the_kernels_frames_to_the_core(self):
        # the shim: an unknownOp on THIS page's socket sharpens the offer and goes on to the bundle; a reloadRequired is the safety
        # valve and never reaches the bundle; the shell's own socket carries the valve too
        js = km._shim("chat", 5)
        self.assertIn('if(msg&&msg.type==="reloadRequired"){try{if(window.__rompReload)window.__rompReload.require(msg.why);}catch(e){}return;}', js)
        self.assertIn('if(msg&&msg.type==="unknownOp"){try{if(window.__rompReload)window.__rompReload.behind();}catch(e){}}', js)
        self.assertLess(js.index('msg.type==="unknownOp"'), js.index("enqueue(msg);};"), "the refusal is read before the frame is handed on")
        self.assertIn("else if(m&&m.type==='reloadRequired'){if(window.__rompReload)window.__rompReload.require(m.why);}", km._LANDING_MOBILE_JS)
        src = open(os.path.join(ROOT, "kernel", "kernel.py")).read()
        for frame in ('"type": "reloadRequired"', "'type': 'reloadRequired'", "type=\"reloadRequired\""):
            self.assertNotIn(frame, src, "nothing in the kernel sends the valve today")

    def test_a_standalone_pane_renders_the_offer_as_its_own_bar_with_reload_and_not_now(self):
        js = km._shim("feed", 5)
        self.assertIn('window.__rompReload.offer=function(o){var have=document.getElementById("romp-stale-self");var mine=have&&have.dataset.kind==="offer";', js)
        self.assertIn('if(!o){if(mine)have.remove();return;}if(mine){have.firstChild.textContent=o.text;return;}selfBar(o.text,"offer");};', js,
                      "null takes the bar down; a wording change is written into the standing bar; else the bar is raised")
        self.assertIn("!window.__rompReload.inShell()){window.__rompReload.offer=", js, "a standalone page only: in the shell the banner speaks")
        self.assertIn('x.textContent=(kind==="offer")?"Not now":"Dismiss"', js)
        self.assertIn('x.onclick=(kind==="offer")?function(){try{window.__rompReload.dismiss();}catch(e){}b.remove();}:function(){b.remove();}', js)
        self.assertIn('r.onclick=(kind==="offer")?function(){r.disabled=true;r.textContent="Reloading\u2026";try{window.__rompReload.accept();}catch(e){location.reload();}}:function(){location.reload();}', js)
        self.assertIn('if((have.dataset.kind==="warn"||have.dataset.kind==="offer")&&(kind||"conn")==="conn")have.remove();else return;', js, "the offer yields the one slot to the connection bar")
        self.assertIn('if(b&&b.dataset.kind==="conn"){b.remove();try{var RO=window.__rompReload;if(RO&&RO.offer&&RO.offered())RO.offer(RO.offered());}catch(e){}}', js, "and returns when it retires")

    def test_every_kernel_served_page_embeds_the_core_with_its_build_and_boot(self):
        shim = km._shim("feed", 123)
        self.assertIn("/*reload-core*/", shim)
        self.assertLess(shim.find("/*reload-core*/"), shim.find("/*shim-core*/"), "the core is defined before the shim asks it")
        self.assertIn("var LOADED=123,BOOT=%s," % json.dumps(km._BOOT_ID), shim)
        self.assertIn("/*reload-core*/", km._stale_block(123))
        self.assertIn("var LOADED=123,BOOT=%s," % json.dumps(km._BOOT_ID), km._stale_block(123))
        self.assertLess(km._stale_block(123).find("/*reload-core*/"), km._stale_block(123).find("var RL=window.__rompReload;"))
        self.assertIn("var LOADED=0,", km._reload_core())
        with self.assertRaises(RuntimeError):
            km._RELOAD_CORE_JS = km._RELOAD_CORE_JS.replace("/*end-reload-core*/", "", 1)
            try:
                km._reload_core_js()
            finally:
                km._RELOAD_CORE_JS = km._RELOAD_CORE_JS.replace("window.__rompReload=R;})();", "window.__rompReload=R;})();/*end-reload-core*/", 1)

    def test_the_shim_hands_the_core_its_keepalives_dv_and_asks_on_a_standalone_reconnect(self):
        js = km._shim("chat", 5)
        # 2026-09-16: the dv itself goes to the core (noteDv proposes, deduped by build); no request, no refused fallback; the bar of
        # the core's absence is latched once per page life
        self.assertIn('function raiseBuild(dv){var R=window.__rompReload;if(R){R.noteDv(dv);return;}', js)
        self.assertIn('if(buildRaised)return;buildRaised=true;selfBar("A newer romp build is available.","build");}', js)
        self.assertNotIn('R.request("build","")', js, "the shim requests nothing: a newer build is proposed")
        self.assertNotIn("R.refused=", js, "no refused fallback: a refused accept puts the offer back (the core)")
        self.assertNotIn('postMessage({romp:"wsStale",build:1}', js, "the build:1 hand-off to the banner is gone")
        self.assertIn('if(msg&&msg.type==="ka"){if(LOADEDV&&msg.dv&&msg.dv>LOADEDV)raiseBuild(msg.dv);', js, "the keepalive's dv is still the event, and rides in")
        self.assertIn("if(window.__rompReload&&!window.__rompReload.inShell())window.__rompReload.checkBoot();", js)
        # the pane's queued sends hold the reload, and the flush is the ending event (review find, 2026-09-08)
        self.assertIn('window.__rompPaneBusy=function(){var q=everConnected&&queue.length>queuedDiag;if(!q){sendsSince=0;return "";}if(!sendsSince)sendsSince=Date.now();return Date.now()-sendsSince<SENDS_HOLD_MS?"sends":"";};', js)
        self.assertIn("queue=[];queuedDiag=0;\ntry{if(window.__rompReload)window.__rompReload.ended();}catch(e){}", js)
        # a standalone page consumes its own marker; nobody else would
        self.assertIn("try{if(window.__rompReload&&!window.__rompReload.inShell())window.__rompReload.announce(null);}catch(e){}", js)
        # …on the RECONNECT branch only: the first open is not a restart
        i = js.find("if(wasReconn){")
        self.assertGreater(i, 0)
        self.assertLess(i, js.find("window.__rompReload.checkBoot();"))

    def test_the_shell_asks_on_its_own_sockets_reopen_and_feeds_its_keepalive(self):
        js = km._LANDING_MOBILE_JS
        self.assertIn("var shellOpened=false;", js)
        self.assertIn("if(shellOpened&&window.__rompReload)window.__rompReload.checkBoot();shellOpened=true;", js)
        self.assertIn("if(m&&m.type==='ka'){if(m.dv&&window.__rompReload)window.__rompReload.noteDv(m.dv);}", js)

    def test_the_banner_is_the_offers_home_and_the_poll_feeds_the_core(self):
        js = km._STALE_JS
        # 2026-09-16: the shell's #rstale box paints the core's offer (the hook), Reload is the core's accept, Not now its dismiss
        self.assertIn("if(RL){RL.offer=function(o){offer=o||null;rl.disabled=false;rl.textContent='Reload';paint();};", js)
        self.assertIn("RL.announce(function(k,t){if(window.__rompNotify)window.__rompNotify(k,t);});RL.offer(RL.offered());}", js, "an offer proposed before the hook paints at install")
        self.assertIn("if(RL)RL.noteVersion(v);", js)
        self.assertIn("else if(loaded&&served>loaded&&served!==dismissed){buildStale=true;paint();}", js, "the banner's own wording only where the core is absent")
        self.assertIn("if(m&&m.romp==='wsStale'){if(m.build){if(RL)RL.checkBoot();else buildStale=true;}else connStale=true;paint();}", js,
                      "an older pane's build:1 asks the core for the authoritative /version reading; a connection stale paints the prompt")
        self.assertIn("else if(m&&m.romp==='wsFresh'){connStale=false;paint();}", js, "the CONNECTION prompt retires on the resync; the offer, if one stands, paints again")
        self.assertIn("else if(offer){box.classList.add('offer');dm.textContent='Not now';show(offer.text);}", js, "the offer's own wording, the accent class, Not now")
        self.assertIn("if(connStale){box.classList.remove('offer');dm.textContent='Dismiss';show(CONNMSG);}", js, "the connection prompt outranks the offer while it stands")
        self.assertIn("rl.onclick=function(){if(RL&&offer){rl.disabled=true;rl.textContent='Reloading\u2026';RL.accept();}else location.reload();};", js,
                      "Reload acknowledges at once and is the core's accept; without an offer it is the plain reload of a frozen view")
        self.assertIn("else if(RL&&offer)RL.dismiss();", js, "Not now is the core's dismiss, kept per build")
        self.assertNotIn("RL.refused=", js); self.assertNotIn("RL.request(", js)
        css = km._STALE_CSS
        self.assertIn("#rstale.offer .rs-reload{background:var(--accent,#9cd2ff);color:var(--accent-fg,#0c1a2e);border-color:transparent}", css, "the offer's action wears the accent")
        self.assertIn("#rstale button:disabled{opacity:.55;cursor:default}", css)
        html = km._landing()
        self.assertIn(":root{--accent:#9cd2ff;--accent-fg:#0c1a2e}", html, "the landing defines the token the rule reads")
        self.assertIn("body.theme-light{--accent:#C2410C;--accent-fg:#FFF8F2;", html, "and the light theme re-resolves it")

    def test_the_shells_banner_paints_the_offer_and_its_buttons_drive_the_core(self):
        """_STALE_JS executed over a DOM fake: the core's offer hook paints the line with Not now and the accent class; Reload
        acknowledges and calls accept (never location.reload while an offer stands); Not now calls dismiss; the connection prompt
        outranks a standing offer and the offer returns when it retires; an older pane's build:1 asks for /version; with nothing
        offered the Reload button is the plain reload."""
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not installed")
        js = """
var CALLS = [], RELOADS = 0, classes = {}, LISTEN = {};
var msg = { textContent: "" }, rl = { textContent: "Reload", disabled: false, onclick: null, tagName: "BUTTON" }, dm = { textContent: "Dismiss", onclick: null, tagName: "BUTTON" };
var box = { classList: { add: function () { for (var i = 0; i < arguments.length; i++) classes[arguments[i]] = true; }, remove: function () { for (var i = 0; i < arguments.length; i++) delete classes[arguments[i]]; } },
            querySelector: function () { return msg; }, addEventListener: function () {}, getBoundingClientRect: function () { return { left: 0, top: 0, width: 100, height: 20 }; }, style: {} };
var document = { getElementById: function (id) { return id === "rstale" ? box : id === "rstale-reload" ? rl : id === "rstale-dismiss" ? dm : null; } };
var RL = { offer: null, held: null, announce: function () {}, offered: function () { return null; },
           noteVersion: function (v) { CALLS.push(["noteVersion", v.dist_ver]); }, checkBoot: function () { CALLS.push(["checkBoot"]); },
           accept: function () { CALLS.push(["accept"]); }, dismiss: function () { CALLS.push(["dismiss"]); } };
var window = { addEventListener: function (t, f) { (LISTEN[t] = LISTEN[t] || []).push(f); }, __rompNotify: function (k, t) { CALLS.push(["notify", k, t]); }, __rompReload: RL, innerWidth: 800, innerHeight: 600 };
var location = { reload: function () { RELOADS++; } };
function fetch() { return { then: function () { return { then: function () { return { "catch": function () {} }; } }; } }; }   /* the poll never answers here */
function setInterval() {}
%s
var OUT = {};
function snap() { return { text: msg.textContent, shown: !!classes.show, offer: !!classes.offer, dismiss: dm.textContent, reload: rl.textContent, disabled: rl.disabled }; }
OUT.installed = snap();
RL.offer({ dv: 8, code: "", behind: false, text: %s });
OUT.offered = snap();
RL.offer({ dv: 8, code: "", behind: true, text: %s });
OUT.behind = snap();
var message = LISTEN.message[0];
message({ data: { romp: "wsStale" } }); OUT.connOverOffer = snap();
message({ data: { romp: "wsFresh" } }); OUT.offerBack = snap();
message({ data: { romp: "wsStale", build: 1 } }); OUT.buildAsks = { calls: CALLS.slice(), snap: snap() }; message({ data: { romp: "wsFresh" } });
dm.onclick(); OUT.afterNotNow = { calls: CALLS.slice() };
RL.offer(null); OUT.retired = snap();
RL.offer({ dv: 9, code: "", behind: false, text: %s });
rl.onclick(); OUT.afterReload = { calls: CALLS.slice(), reloads: RELOADS, snap: snap() };
RL.offer(null);
rl.onclick(); OUT.plainReload = RELOADS;
message({ data: { romp: "wsStale" } }); dm.onclick(); OUT.connDismissed = snap();
process.stdout.write("RESULT:" + JSON.stringify(OUT) + "\\n");
""" % (km._STALE_JS.replace("__LOADEDVER__", "7"), json.dumps(OFFER), json.dumps(BEHIND), json.dumps(OFFER))
        d = tempfile.mkdtemp(prefix="stale-banner-")
        path = os.path.join(d, "stale.js")
        with open(path, "w") as f:
            f.write(js)
        r = subprocess.run([node, path], capture_output=True, text=True, timeout=60)
        shutil.rmtree(d, ignore_errors=True)
        self.assertEqual(r.returncode, 0, "node failed:\n" + r.stderr)
        o = json.loads(next(ln for ln in r.stdout.splitlines() if ln.startswith("RESULT:"))[len("RESULT:"):])
        self.assertFalse(o["installed"]["shown"], "nothing to say at install")
        self.assertEqual(o["offered"], {"text": OFFER, "shown": True, "offer": True, "dismiss": "Not now", "reload": "Reload", "disabled": False})
        self.assertEqual(o["behind"]["text"], BEHIND, "the sharpened wording is written into the standing line")
        self.assertEqual(o["connOverOffer"]["text"], "romp lost the live connection to the dashboard, so what you see may be stale.")
        self.assertEqual([o["connOverOffer"]["offer"], o["connOverOffer"]["dismiss"]], [False, "Dismiss"], "the connection prompt outranks the offer")
        self.assertEqual([o["offerBack"]["text"], o["offerBack"]["offer"], o["offerBack"]["dismiss"]], [BEHIND, True, "Not now"], "the offer returns when the prompt retires")
        self.assertEqual(o["buildAsks"]["calls"], [["checkBoot"]], "an older pane's build:1 asks the core for the authoritative reading")
        self.assertEqual(o["afterNotNow"]["calls"], [["checkBoot"], ["dismiss"]], "Not now is the core's dismiss")
        self.assertFalse(o["retired"]["shown"], "the hook's null takes the line down")
        self.assertEqual(o["afterReload"]["calls"][-1], ["accept"], "Reload is the core's accept")
        self.assertEqual(o["afterReload"]["reloads"], 0, "never location.reload while an offer stands: the core persists first")
        self.assertEqual([o["afterReload"]["snap"]["disabled"], o["afterReload"]["snap"]["reload"]], [True, "Reloading\u2026"], "the click is acknowledged at once")
        self.assertEqual(o["plainReload"], 1, "with no offer the button is the plain reload of a frozen view")
        self.assertFalse(o["connDismissed"]["shown"])

    def test_a_held_reload_is_told_to_the_notification_center_and_to_a_standalone_panes_bar(self):
        # the shell's stale script installs the `held` hook: the line names what the reload waits for (an upload, a held
        # send, queued sends) and skips momentary gesture holds; a standalone pane (no shell) raises its own bar
        js = km._STALE_JS
        self.assertIn("RL.held=function(b){var t=(b==='upload'?'The dashboard will reload once the upload in progress finishes.'", js)
        self.assertIn("if(t&&window.__rompNotify)window.__rompNotify('reload',t);", js)
        shim = km._shim("chat", 7) if callable(getattr(km, "_shim", None)) else ""
        self.assertIn("window.__rompReload.held=function(b){var t=(b==='upload'?", shim)
        self.assertIn("if(t)selfBar(t,'held');", shim)
        self.assertIn("!window.__rompReload.inShell()", shim, "only a standalone pane raises its own bar; in the shell the center speaks")

    def test_a_remote_kernels_restart_or_bundle_never_reaches_the_core(self):
        fed = open(os.path.join(ROOT, "ui", "webview", "federation.ts")).read()
        self.assertIn('if (msg && msg.type === "ka") return;', fed, "federation drops a remote kernel's keepalive")
        core = km._reload_core_js()
        self.assertNotIn("__rompLocalSend", core)
        self.assertNotIn("host", core, "the core knows no hosts: it reads THIS page's socket and /version only")
        self.assertIn("fetch('/version'", core, "…and /version is the serving kernel's own")

    def test_the_superseded_rule_is_recorded_with_both_dates(self):
        # three rulings by date, each recorded as superseding the one before it (2026-07-13, 2026-09-08, 2026-09-16)
        src = open(os.path.join(ROOT, "kernel", "kernel.py")).read()
        block = src[src.index("# ── the dashboard OFFERS a reload on a newer build"):src.index("_RELOAD_CORE_JS = r")]
        self.assertIn("2026-09-16", block); self.assertIn("2026-09-08", block); self.assertIn("2026-07-13", block)
        self.assertIn("2026-09-16 supersedes 2026-09-08", block); self.assertIn("2026-09-08 (T265) supersedes 2026-07-13", block)
        self.assertLess(block.index("2026-07-13"), block.index("2026-09-08 (T265) supersedes"), "oldest first")
        ext = open(os.path.join(ROOT, "vscode-extension", "src", "extension.ts")).read()
        self.assertIn("2026-09-16", ext, "the VS Code exception names the ruling it stands beside")
        self.assertIn("2026-09-08", ext, "and the one it superseded")
        self.assertIn("OFFERS the reload", ext)


if __name__ == "__main__":
    unittest.main()
