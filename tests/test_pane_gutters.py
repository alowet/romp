#!/usr/bin/env python3
"""The shell's pane gutters must WORK with split chat columns in the row, not just parse (2026-09-08).

The dashboard's chat|fleet|feed panes are sized by flex-grow weights the gutter script (_LANDING_JS in
kernel.py) keeps in sync with `--g-<k>` vars on .row and persists in localStorage. Split screen (the user
2026-09-08, who wanted several sessions side by side instead of tabbing through them) adds chat columns to
that row AFTER the script has run, so the script grew a registry: a column registers its pane id and grow
key, takes a fair grow (the average of what is already on screen) or the width it was dragged to before a
reload, and gets its own chat|chat gutter wired through the same drag code. The review of the first cut found
the fair grow averaging the new column's own undefined grow in as NaN, so the first split opened 0px wide;
that is the regression this file pins by running the code, since a source pin cannot tell NaN from 50.

The chat ROWS (the user 2026-09-15) put every chat column inside #chat-area, a wrapper that takes the outer
row's --g-chat weight, holding two flex rows of columns (the first pane on its own inner weight --g-chat1):
a weight is relative to its CONTAINER, so a grab, a halving or a hand-back normalises the grabbed pane's
siblings alone and never moves the outer weights; gv-a/gv-b/gv-c pair the chat AREA with the outline, the
feed and the files; and the gutter between the two rows rides the same drag code vertically, reporting the
top row's share instead of writing a grow (__rompRowGutter). A store from before the rows seeds chat1 from
chat, so a stored later column keeps its proportion against the first pane.

This EXECUTES the real _LANDING_JS in node against a DOM stub (the test_error_center.py pattern) and drives
the whole story over one JSON result: the boot defaults; a fresh column's fair grow over its row; the reload
paths of __rompGrowFairIfNew (a stored width is kept, a missing one falls to the average) by re-running the
blob against a re-seeded store; a drag on a chat|chat gutter moving only that pair inside the row; gv-a
pairing the chat area with the outline (fleet) pane; unregistering a closed column; the unregistered fallback
keys; the halving and the hand-back inside a row; the row gutter's drag; and the pre-rows store's seed. The
stub records the `--g-*` vars the script sets on .row, because the script's `grow` object is a closure.

Synthetic only: no network, no real DOM, invented widths.
"""
import json
import os
import subprocess
import tempfile
import unittest
from romp_load import load_source

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
# Hermetic state BEFORE the loads — they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
km = load_source("romp_kernel_gutters", os.path.join(BIN, "romp-kernel"))

# Everything _LANDING_JS touches, and nothing else: .col (the timeline band's --tl var, never driven here),
# .row (records the --g-* vars), the gutters + panes by id — each pane with the parentElement the served
# markup gives it (the chat area and the other panes in .row, the chat panes in #chat-row-1, the two chat
# rows in #chat-area), since a grab normalises the grabbed pane's siblings — getComputedStyle(el).display
# for shown(), body.classList (po-fleet / po-timeline reads, drag/dragv/dragh writes), localStorage, and the
# window's mousemove/mouseup listeners a drag installs and removes. f-timeline is stubbed PRESENT (the served
# shell always carries the iframe, kernel.py `<iframe id=f-timeline …>`), so the 'load' hookup runs; the
# script also guards the null case (`tf&&…`, `tf?…:0`), so a stub without it would pass too.
HARNESS = r"""
'use strict';
const STORE = {};
global.localStorage = {
  getItem: (k) => (k in STORE ? STORE[k] : null),
  setItem: (k, v) => { STORE[k] = String(v); },
  removeItem: (k) => { delete STORE[k]; },
};
const ROW = {};   // the --g-* vars the script sets on .row (its `grow` object is a closure)
const rowEl = { style: { setProperty: (k, v) => { ROW[k] = v; }, removeProperty: (k) => { delete ROW[k]; } },
                getBoundingClientRect: () => ({ top: 0, height: 800, left: 0, bottom: 800 }) };   // the landing line is placed by the row's rect (main, 2026-09)
const colEl = { style: { setProperty() {} }, getBoundingClientRect: () => ({ bottom: 800 }) };
// the containers the panes sit in: the chat rows inside the chat area (the served markup, kernel.py _landing)
const areaEl = { id: 'chat-area-box', getBoundingClientRect: () => ({ left: 0, top: 0, width: 600, height: 807, bottom: 807 }) };
const row1El = { id: 'chat-row-1-box', getBoundingClientRect: () => ({ left: 0, top: 0, width: 600, height: 400, bottom: 400 }) };
function mkEl(id, w, display, parent, h) {
  return {
    id: id, offsetWidth: w, offsetHeight: h || 800, _display: display, _ls: {}, parentElement: parent || rowEl, style: {},
    getBoundingClientRect() { return { left: 0, top: this._top || 0, width: this.offsetWidth, height: this.offsetHeight, bottom: (this._top || 0) + this.offsetHeight }; },   // the drag's landing line reads the left pane's rect
    addEventListener(k, f) { (this._ls[k] = this._ls[k] || []).push(f); },
    fire(k, ev) { (this._ls[k] || []).slice().forEach((f) => f(ev)); },
  };
}
let EL = {};
let WL = {};
let APPLIED = [];   // the shares the row gutter's release reports
// Fresh gutters, panes and window listeners for every boot of the blob: a re-run models a RELOAD, and the
// previous instance's mousedown handlers must not linger on the same stub gutter (two closures dragging
// one row would corrupt every width below).
function resetDom() {
  EL = {};
  WL = {};
  APPLIED = [];
  ['gh', 'gv-a', 'gv-b', 'gv-c', 'gv-chat-2', 'gv-chat-3', 'gv-rows', 'f-timeline', 'gv-ghost', 'gv-ghost-h'].forEach((id) => { EL[id] = mkEl(id, 0, 'flex'); });
  EL['chat-area'] = mkEl('chat-area', 600, 'flex');   // the chat area: the outer row's chat side (the rows, 2026-09-15)
  EL['chat-pane'] = mkEl('chat-pane', 600, 'flex', row1El);
  EL['fleet-pane'] = mkEl('fleet-pane', 300, 'none');   // hidden by default, like the real rail
  EL['feed-pane'] = mkEl('feed-pane', 400, 'flex');
  EL['files-pane'] = mkEl('files-pane', 400, 'none');   // the fourth top pane (main, 2026-09), hidden by default
  EL['chat-pane-2'] = mkEl('chat-pane-2', 500, 'flex', row1El);   // the split's client-made column (shown once made), in the top row
  EL['chat-pane-3'] = mkEl('chat-pane-3', 450, 'flex', row1El);
  EL['chat-row-1'] = mkEl('chat-row-1', 600, 'flex', areaEl, 400);   // the two chat rows, 400 px each behind the 7 px row gutter
  EL['chat-row-2'] = mkEl('chat-row-2', 600, 'flex', areaEl, 400); EL['chat-row-2']._top = 407;
  for (const k in ROW) delete ROW[k];
}
const BODY = new Set(['po-chat', 'po-feed']);
global.window = {
  innerHeight: 900,
  addEventListener: (k, f) => { (WL[k] = WL[k] || []).push(f); },
  removeEventListener: (k, f) => { WL[k] = (WL[k] || []).filter((g) => g !== f); },
};
global.getComputedStyle = (el) => ({ display: el._display });
global.document = {
  querySelector: (sel) => (sel === '.col' ? colEl : sel === '.row' ? rowEl : null),
  getElementById: (id) => EL[id] || null,
  body: { classList: {
    contains: (c) => BODY.has(c),
    add: (...cs) => cs.forEach((c) => BODY.add(c)),
    remove: (...cs) => cs.forEach((c) => BODY.delete(c)),
  } },
};
function showFleet(on) { EL['fleet-pane']._display = on ? 'flex' : 'none'; if (on) BODY.add('po-fleet'); else BODY.delete('po-fleet'); }
function winFire(k, ev) { (WL[k] || []).slice().forEach((f) => f(ev)); }
function grows() { return Object.assign({}, ROW); }
function store() { return JSON.parse(STORE['romp-pane-grow'] || 'null'); }
function ghostH() { return Object.assign({}, EL['gv-ghost-h'].style); }
function drag(gid, x0, x1) {
  const snap = {};
  EL[gid].fire('mousedown', { preventDefault() {}, clientX: x0 });
  snap.afterDown = grows();           // every shown pane normalised to its px width
  snap.dragging = BODY.has('drag') && BODY.has('dragv');
  snap.listeners = { move: (WL['mousemove'] || []).length, up: (WL['mouseup'] || []).length };
  winFire('mousemove', { clientX: x1 });
  snap.afterMove = grows();
  winFire('mouseup', {});
  snap.afterUp = grows();
  snap.dragAfterUp = BODY.has('drag') || BODY.has('dragv');
  snap.listenersAfterUp = { move: (WL['mousemove'] || []).length, up: (WL['mouseup'] || []).length };
  snap.store = store();
  return snap;
}
// the ROW gutter's drag: the pointer's Y, the horizontal landing line, the share reported at release
function dragRows(y0, y1) {
  const snap = {};
  EL['gv-rows'].fire('mousedown', { preventDefault() {}, clientY: y0 });
  snap.afterDown = { grows: grows(), ghost: ghostH(), dragging: BODY.has('drag') && BODY.has('dragh'), dragv: BODY.has('dragv') };
  winFire('mousemove', { clientY: y1 });
  snap.afterMove = { grows: grows(), ghost: ghostH(), applied: APPLIED.slice() };
  winFire('mouseup', {});
  snap.afterUp = { grows: grows(), ghost: ghostH(), applied: APPLIED.slice(), drag: BODY.has('drag') || BODY.has('dragh'), store: store(),
                   listeners: { move: (WL['mousemove'] || []).length, up: (WL['mouseup'] || []).length } };
  return snap;
}
"""

DRIVER = r"""
const out = {};
// 1) boot with an empty store: the defaults land on .row
resetDom();
BOOT();
out.boot = { grows: grows(), store: store() };
// 2) a split column registers, then asks for a fair grow while it has NO grow of its own yet: the average
//    of its ROW's shown panes' finite grows (the first pane's chat1 60 — the outer row's chat 60 and feed 40 are
//    another container's scale), never NaN (review find 2026-09-08)
window.__rompRegisterPane('chat-pane-2', 'chat2');
window.__rompGrowFair('chat2');
out.fair = { grows: grows(), store: store(),
  finite: typeof ROW['--g-chat2'] === 'number' && isFinite(ROW['--g-chat2']) };
// 3a) a RELOAD with a stored width for the column: __rompGrowFairIfNew keeps it (no re-fair)
resetDom();
STORE['romp-pane-grow'] = JSON.stringify({ chat: 60, fleet: 34, feed: 40, chat2: 123 });
BOOT();
window.__rompRegisterPane('chat-pane-2', 'chat2');
window.__rompGrowFairIfNew('chat2');
out.ifNewKept = { grows: grows(), store: store() };
// 3b) a RELOAD with nothing stored for the column: it falls through to the fair average
resetDom();
STORE['romp-pane-grow'] = JSON.stringify({ chat: 60, fleet: 34, feed: 40 });
BOOT();
window.__rompRegisterPane('chat-pane-2', 'chat2');
window.__rompGrowFairIfNew('chat2');
out.ifNewFair = { grows: grows(), store: store() };
// 4) the column's own chat|chat gutter, wired the way the split script wires it (left = the previous
//    column, here the first chat pane; right = the new column). Drag 100px to the right: the top row's two
//    panes to px, then the pair moves; the outer row's weights are not touched.
window.__rompGutter('gv-chat-2', function () { return 'chat-pane'; }, 'chat-pane-2');
out.dragChatChat = drag('gv-chat-2', 500, 600);
// 5) gv-a's left neighbour is the chat AREA: with the outline (fleet) pane shown, a drag on gv-a moves chat|fleet in
//    the outer row (its shown panes to px first) and leaves the row's inner weights where the last drag left them
showFleet(true);
out.dragGvA = drag('gv-a', 500, 560);
showFleet(false);
// 6) closing the column: its grow leaves the store and .row; a later fair grow (a new column made after
//    the close) averages only what is still registered, though the closed pane's element is still there
window.__rompUnregisterPane('chat-pane-2');
out.unregister = { grows: grows(), store: store() };
window.__rompRegisterPane('chat-pane-3', 'chat3');
window.__rompGrowFair('chat3');
out.fairAfterClose = { grows: grows(), store: store() };
window.__rompUnregisterPane('chat-pane-3');
// 7) no split at all: gv-b with fleet hidden pairs the chat area with feed, through the
//    unregistered fallback keys (key('chat-area') → chat, key('feed-pane') → feed)
out.dragGvB = drag('gv-b', 500, 480);
// 8) a NEW chat column takes HALF the rightmost column of its row (the chat split, 2026-09-11): __rompSplitGrow normalises
//    the ROW's shown panes to their pixels first (the outer row is another container: not written), then the left pane's
//    key and the new key each take half the left pane's width, persisted; a hidden or missing left pane writes nothing
resetDom();
STORE['romp-pane-grow'] = JSON.stringify({ chat: 60, fleet: 34, feed: 40, chat2: 25 });
BOOT();
window.__rompRegisterPane('chat-pane-2', 'chat2');
out.splitGrow = { wrote: window.__rompSplitGrow('chat-pane-2', 'chat3'), grows: grows(), store: store(),
                  hidden: window.__rompSplitGrow('fleet-pane', 'chat9'), missing: window.__rompSplitGrow('chat-pane-77', 'chat9'), after: grows() };
// 9) a CLOSING column hands its width to the column on its LEFT (review find 2026-09-11, the halving's twin): the row's
//    shown panes to their pixels first, then the left pane's key takes the closing pane's width plus the 7 px gutter that
//    goes with it (the row keeps its width: one gutter fewer); the outer row is not written; a hidden or missing pane on
//    either side writes nothing; the closing pane's own key is dropped by the unregister that follows
resetDom();
STORE['romp-pane-grow'] = JSON.stringify({ chat: 60, fleet: 34, feed: 40, chat2: 25 });
BOOT();
window.__rompRegisterPane('chat-pane-2', 'chat2');
out.splitShrink = { wrote: window.__rompSplitShrink('chat-pane', 'chat-pane-2'), grows: grows(), store: store(),
                    hiddenLeft: window.__rompSplitShrink('fleet-pane', 'chat-pane-2'), missingGone: window.__rompSplitShrink('chat-pane', 'chat-pane-77'), after: grows() };
window.__rompUnregisterPane('chat-pane-2');
out.splitShrink.unregistered = { grows: grows(), store: store() };
// 10) the ROW gutter (the chat rows, 2026-09-15): wired by the split script through __rompRowGutter, its drag writes NO
//     grow (a row pair is a share, not px), moves the horizontal landing line across the chat area, clamps at the pair's
//     minimum (min(120, a quarter): 120 of 800), and the release reports the top row's share, once, to the hook
resetDom();
for (const k in STORE) delete STORE[k];   // a fresh browser: the boot defaults
BOOT();
window.__rompRowGutter('gv-rows', 'chat-row-1', 'chat-row-2', function (s) { APPLIED.push(s); });
out.rows = dragRows(400, 500);
out.rowsFar = dragRows(400, 1200);
out.rowsAfter = { grows: grows(), store: store() };
// 11) a store from BEFORE the rows (no chat1): the first pane's inner weight starts at the chat weight it wore, so a
//     stored later column keeps its proportion against it rather than facing a default 60
resetDom();
for (const k in STORE) delete STORE[k];
STORE['romp-pane-grow'] = JSON.stringify({ chat: 640, fleet: 34, feed: 400, chat2: 400 });
BOOT();
out.legacy = { grows: grows(), store: store() };
console.log(JSON.stringify(out));
"""


class PaneGuttersExecute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # the blob is a self-invoking function; wrapping it as BOOT lets the driver re-run it against a
        # re-seeded store, which is exactly what a reload of the shell does
        script = HARNESS + "const BOOT = function () {" + km._LANDING_JS + "};\n" + DRIVER
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(script)
            path = f.name
        try:
            r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        finally:
            os.unlink(path)
        assert r.returncode == 0, "the gutter JS threw: " + r.stderr[:800]
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_1_boot_with_an_empty_store_sets_the_defaults_on_the_row(self):
        a = self.out["boot"]
        self.assertEqual(a["grows"], {"--g-chat": 60, "--g-chat1": 60, "--g-fleet": 34, "--g-feed": 40, "--g-files": 40}, "the chat area's weight and the first pane's inner one")
        self.assertIsNone(a["store"], "booting alone writes nothing: the store fills on the first drag or fair grow")

    def test_2_a_fresh_columns_fair_grow_averages_only_finite_grows(self):
        # the zero-width regression: chat-pane-2 is shown and registered but has no grow yet, so the old
        # average was (60 + undefined + 40) / 3 = NaN, which flex read as 0 and the column opened 0px wide
        a = self.out["fair"]
        self.assertTrue(a["finite"], "the new column's grow is a finite number, never NaN")
        self.assertEqual(a["grows"]["--g-chat2"], 60, "the average of its row's finite grows: the first pane's chat1 60 (the outer row's chat and feed are another scale)")
        self.assertEqual(a["grows"]["--g-chat"], 60)
        self.assertEqual(a["grows"]["--g-feed"], 40)
        self.assertEqual(a["store"], {"chat": 60, "chat1": 60, "fleet": 34, "feed": 40, "files": 40, "chat2": 60}, "and it persists")

    def test_3_grow_fair_if_new_keeps_a_stored_width_and_fairs_a_missing_one(self):
        kept = self.out["ifNewKept"]
        self.assertEqual(kept["grows"]["--g-chat2"], 123, "a dragged width survives the reload: setGrow applied, no re-fair")
        self.assertEqual(kept["store"]["chat2"], 123)
        fair = self.out["ifNewFair"]
        self.assertEqual(fair["grows"]["--g-chat2"], 60, "nothing stored for it → the fair average over its row")
        self.assertEqual(fair["store"], {"chat": 60, "chat1": 60, "fleet": 34, "feed": 40, "files": 40, "chat2": 60}, "chat1 seeded from the stored chat (a store from before the rows)")

    def test_4_a_chat_chat_gutter_drag_moves_only_that_pair(self):
        a = self.out["dragChatChat"]
        # the grab normalises the ROW's shown panes to their px widths (the first pane's inner weight and the column's);
        # the outer row's chat, feed and hidden fleet keep their weights
        self.assertEqual(a["afterDown"], {"--g-chat": 60, "--g-chat1": 600, "--g-chat2": 500, "--g-feed": 40, "--g-fleet": 34, "--g-files": 40})
        self.assertTrue(a["dragging"], "body.drag + body.dragv while the pointer is held")
        self.assertEqual(a["listeners"], {"move": 1, "up": 1})
        # a drag moves a LANDING LINE (main, 2026-09): the pointer's +100px writes nothing until the release…
        self.assertEqual(a["afterMove"], a["afterDown"], "mousemove positions the ghost line; no pane re-lays out mid-drag")
        # …then chat1 +100, chat2 -100, the others exactly where the grab left them
        self.assertEqual(a["afterUp"]["--g-chat1"], 700)
        self.assertEqual(a["afterUp"]["--g-chat2"], 400)
        self.assertEqual(a["afterUp"]["--g-chat"], 60, "the chat area's share against the feed is untouched by a chat|chat drag")
        self.assertEqual(a["afterUp"]["--g-feed"], a["afterDown"]["--g-feed"], "feed is untouched by the drag")
        self.assertEqual(a["afterUp"]["--g-fleet"], a["afterDown"]["--g-fleet"], "fleet is untouched by the drag")
        self.assertFalse(a["dragAfterUp"], "body.drag / body.dragv are removed on mouseup")
        self.assertEqual(a["listenersAfterUp"], {"move": 0, "up": 0}, "the drag's window listeners are removed")
        self.assertEqual(a["store"], {"chat": 60, "chat1": 700, "fleet": 34, "feed": 40, "files": 40, "chat2": 400}, "the store holds the dragged widths")

    def test_5_gv_a_pairs_the_chat_area_with_fleet_and_leaves_the_row_s_inner_weights_alone(self):
        a = self.out["dragGvA"]
        # fleet is shown for this drag, so the OUTER row normalises: the chat area (600), fleet (300) and feed (400) to px;
        # the top row's chat1/chat2 stay where the last drag left them (another container)
        self.assertEqual(a["afterDown"], {"--g-chat": 600, "--g-chat1": 700, "--g-chat2": 400, "--g-fleet": 300, "--g-feed": 400, "--g-files": 40})
        # +60px: the pair that moves is chat|fleet — the whole chat area against the outline — and no column inside it moves
        self.assertEqual(a["afterUp"]["--g-chat"], 660)
        self.assertEqual(a["afterUp"]["--g-fleet"], 240)
        self.assertEqual(a["afterUp"]["--g-chat1"], 700, "the first pane's inner weight is not gv-a's business")
        self.assertEqual(a["afterUp"]["--g-chat2"], 400, "nor the column's")
        self.assertEqual(a["afterUp"]["--g-feed"], 400)
        self.assertEqual(a["store"], {"chat": 660, "chat1": 700, "fleet": 240, "feed": 400, "files": 40, "chat2": 400})

    def test_6_unregistering_a_closed_column_drops_it_everywhere(self):
        a = self.out["unregister"]
        self.assertNotIn("--g-chat2", a["grows"], "its --g-chat2 var leaves .row")
        self.assertNotIn("chat2", a["store"], "and its grow leaves the store")
        self.assertEqual(a["store"], {"chat": 660, "chat1": 700, "fleet": 240, "feed": 400, "files": 40})
        # a column made after the close averages its row: the first pane's 700 alone; had the closed pane still
        # counted (its element is still in the stub, still in the row), the average would be 550
        b = self.out["fairAfterClose"]
        self.assertEqual(b["grows"]["--g-chat3"], 700)
        self.assertNotIn("--g-chat2", b["grows"])
        self.assertEqual(b["store"], {"chat": 660, "chat1": 700, "fleet": 240, "feed": 400, "files": 40, "chat3": 700})

    def test_7_unregistered_ids_fall_back_to_the_fixed_keys(self):
        # no split, fleet hidden: gv-b's left neighbour is the chat area (lastChat() → 'chat-area'), and key() resolves
        # the fixed ids to chat / feed
        a = self.out["dragGvB"]
        self.assertEqual(a["afterDown"], {"--g-chat": 600, "--g-chat1": 700, "--g-fleet": 240, "--g-feed": 400, "--g-files": 40},
                         "the outer row's shown panes to px; the closed columns are gone from the grab, the first pane's inner weight is another container's")
        # -20px: chat -20, feed +20; fleet (hidden) untouched
        self.assertEqual(a["afterUp"]["--g-chat"], 580)
        self.assertEqual(a["afterUp"]["--g-feed"], 420)
        self.assertEqual(a["afterUp"]["--g-fleet"], 240)
        self.assertEqual(a["store"], {"chat": 580, "chat1": 700, "fleet": 240, "feed": 420, "files": 40})

    def test_8_a_new_column_takes_half_the_rightmost_column_after_every_shown_pane_is_normalised(self):
        # the chat split's honest half-width (2026-09-11): the top row's panes report chat-pane 600 and chat2 500, so the
        # grab-style normalisation writes those two first — never a mixed scale — and then chat2 and the new chat3 each take
        # 250; the outer row (chat 60, feed 40, the hidden outline and files panes) keeps its stored weights
        a = self.out["splitGrow"]
        self.assertTrue(a["wrote"])
        self.assertEqual(a["grows"], {"--g-chat": 60, "--g-chat1": 600, "--g-chat2": 250, "--g-chat3": 250, "--g-feed": 40, "--g-fleet": 34, "--g-files": 40})
        self.assertEqual(a["store"], {"chat": 60, "chat1": 600, "fleet": 34, "feed": 40, "files": 40, "chat2": 250, "chat3": 250}, "persisted, so __rompGrowFairIfNew keeps it when the column is made")
        self.assertFalse(a["hidden"], "a hidden left pane is never written")
        self.assertFalse(a["missing"], "nor a missing one")
        self.assertEqual(a["after"], a["grows"], "…and the refusals changed nothing")

    def test_9_a_closing_column_hands_its_width_to_the_column_on_its_left(self):
        # the halving's twin (review find 2026-09-11): with only the closing column's key deleted, flex gave its pixels to
        # EVERY pane by weight, so a tab dragged out and back narrowed the chat by a third per round trip. The top row's
        # panes report chat-pane 600 and chat2 500: the normalisation writes those two, then chat1 takes 600 + 500 + the
        # 7 px gutter that goes with the closing column; the outer row is not written
        a = self.out["splitShrink"]
        self.assertTrue(a["wrote"])
        self.assertEqual(a["grows"], {"--g-chat": 60, "--g-chat1": 1107, "--g-chat2": 500, "--g-feed": 40, "--g-fleet": 34, "--g-files": 40})
        self.assertEqual(a["store"], {"chat": 60, "chat1": 1107, "fleet": 34, "feed": 40, "files": 40, "chat2": 500}, "persisted: the width survives a reload")
        self.assertFalse(a["hiddenLeft"], "a hidden left pane is never written")
        self.assertFalse(a["missingGone"], "nor for a missing closing pane")
        self.assertEqual(a["after"], a["grows"], "…and the refusals changed nothing")
        u = a["unregistered"]
        self.assertEqual(u["grows"], {"--g-chat": 60, "--g-chat1": 1107, "--g-feed": 40, "--g-fleet": 34, "--g-files": 40}, "the unregister that follows drops the closing column's key alone")
        self.assertEqual(u["store"], {"chat": 60, "chat1": 1107, "fleet": 34, "feed": 40, "files": 40})

    def test_10_the_row_gutter_moves_a_horizontal_line_and_reports_the_top_row_s_share_writing_no_grow(self):
        # the chat rows (2026-09-15): the grab at y 400 (the divider: row 1 is 400 tall from 0) writes no grow — a row pair is a
        # share, not px — puts the drag classes on (dragh, not dragv) and shows #gv-ghost-h across the chat area at the divider;
        # the move repositions it; the release reports 500 / 800 to the hook, once, hides the line and drops the classes
        boot = self.out["boot"]["grows"]
        a = self.out["rows"]
        self.assertEqual(a["afterDown"]["grows"], boot, "no normalisation: nothing is written at the grab")
        self.assertTrue(a["afterDown"]["dragging"], "body.drag + body.dragh"); self.assertFalse(a["afterDown"]["dragv"])
        self.assertEqual(a["afterDown"]["ghost"], {"left": "0px", "width": "600px", "top": "400px", "display": "block"}, "the line spans the chat area, at the divider")
        self.assertEqual(a["afterMove"]["ghost"]["top"], "500px", "the line follows the pointer"); self.assertEqual(a["afterMove"]["grows"], boot); self.assertEqual(a["afterMove"]["applied"], [])
        self.assertEqual(a["afterUp"]["applied"], [0.625], "the top row's share of the pair: 500 of 800")
        self.assertEqual(a["afterUp"]["grows"], boot, "still no grow written: the share is the split script's to keep")
        self.assertIsNone(a["afterUp"]["store"]); self.assertEqual(a["afterUp"]["ghost"]["display"], "none"); self.assertFalse(a["afterUp"]["drag"])
        self.assertEqual(a["afterUp"]["listeners"], {"move": 0, "up": 0})
        f = self.out["rowsFar"]
        self.assertEqual(f["afterMove"]["ghost"]["top"], "680px", "clamped at the pair's minimum: min(120, 800 / 4) = 120 from the bottom")
        self.assertEqual(f["afterUp"]["applied"], [0.625, 0.85], "680 of 800")
        self.assertEqual(self.out["rowsAfter"], {"grows": boot, "store": None})

    def test_11_a_store_from_before_the_rows_seeds_the_first_pane_s_inner_weight_from_the_chat_weight(self):
        a = self.out["legacy"]
        self.assertEqual(a["grows"], {"--g-chat": 640, "--g-chat1": 640, "--g-fleet": 34, "--g-feed": 400, "--g-files": 40, "--g-chat2": 400},
                         "chat1 starts at the stored chat, so the stored column 2 keeps its 640:400 proportion against the first pane")
        self.assertEqual(a["store"], {"chat": 640, "fleet": 34, "feed": 400, "chat2": 400}, "seeded in memory: the store is written with the next change, not at boot")


if __name__ == "__main__":
    unittest.main()
