// The session header's Clear (the user 2026-09-08): in grouped mode, each session header carries a Clear
// on the far right of its row that clears every card of that session in the current view — every column,
// folded ones included — as one motion and ONE Undo batch, through the same optimistic path the ask-group
// clear takes. Only grouped mode renders headers, so the control exists only there. Source pins, in the
// style of the other feed tests.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const FEED = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "feed.ts"), "utf8");
const CSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "feed.css"), "utf8");

test("the header carries a plain-worded Clear on the far right, hidden when the session has no cards", () => {
  assert.match(FEED, /const clr = el\("button", "feed-sess-clear"\); clr\.textContent = "Clear";/);
  assert.match(FEED, /clr\.title = "Clear every card for this session"; clr\.dataset\.act = "sess-clear";/);
  // after the caret, count and service chip; before the full-width process list that wraps below
  assert.match(FEED, /h\.append\(nm, fold, cnt, svc, clr, svcList\);/);
  assert.match(FEED, /sclr\.dataset\.fsid = e\.sid;\s*\n\s*const ncards = sessionCards\(e\.sid\)\.length;\s*\n\s*sclr\.style\.display = ncards \? "" : "none";/);
  // no romp nouns in the copy: not "board", "goal", "card"… the button says the one word every card's Clear says
  const copy = FEED.match(/clr\.title = "([^"]+)"; clr\.dataset\.act = "sess-clear"/)![1];
  for (const noun of ["board", "goal", "column", "dismiss", "nudge"]) assert.doesNotMatch(copy, new RegExp(noun, "i"));
});

test("grouped mode only: headers (and so the control) are emitted under the grouped guard", () => {
  // the header entries are built inside `if (feedPrefs().grouped)`; flat mode never has a header to carry it
  const guard = FEED.indexOf("if (feedPrefs().grouped) {\n    const rank = new Map(sessionOrder.map(");
  assert.ok(guard > 0, "the grouped-mode header build lives under the grouped guard");
  assert.match(FEED.slice(guard, guard + 2500), /head = \{ kind: "sess", t: e\.t, sid: s, name: src\.name/);
  assert.match(FEED, /function dressHeaderIfLast\(card: HTMLElement, sid: string\): void \{\s*\n\s*if \(!feedPrefs\(\)\.grouped\) return;/);
});

test("the click is delegated on the stable columns root, never bound to the re-rendered header", () => {
  assert.match(FEED, /import \{ delegate \} from "\.\/actions";/);
  const at = FEED.indexOf('const cols = el("div", "feed-cols"); cols.id = "feed-cols";');
  assert.ok(at > 0);
  assert.match(FEED.slice(at, at + 900), /delegate\(cols, \{\s*\n\s*"sess-clear": \(b, ev\) => \{ ev\.stopPropagation\(\); const sid = b\.dataset\.fsid; if \(sid\) clearSessionCards\(sid\); \},/);
  assert.doesNotMatch(FEED, /sclr\.onclick|clr\.onclick = \(ev\) => \{[^}]*clearSessionCards/, "no handler on the header's own node");
});

test("one click clears every card of the session in the current view, as one Undo batch, through the group-clear path", () => {
  assert.match(FEED, /function sessionCards\(sid: string\): AskItem\[\] \{\s*\n\s*return viewFiltered\(asks\)\.filter\(\(a\) => a\.sid === sid\);/,
    "the current view's cards for the session — every column; folded cards are in the view too");
  const fn = FEED.slice(FEED.indexOf("function clearSessionCards(sid: string): void {"), FEED.indexOf("function reconcileCol("));
  assert.match(fn, /clearedStack\.push\(members\.slice\(\)\);/, "ONE batch: one Undo restores the whole session");
  assert.match(fn, /for \(const m of members\) \{ pendingCleared\.add\(m\.itemId\); vscodeApi\?\.postMessage\(\{ type: "askClear", itemId: m\.itemId, sid: m\.sid \}\); \}/,
    "askClear per member, suppressed from incoming pushes until the kernel confirms");
  assert.match(fn, /c\.dispatchEvent\(new MouseEvent\("mouseleave"\)\); c\.classList\.add\("dismissing"\);/, "flush the hover highlight, animate out");
  assert.match(fn, /if \(head\.getAttribute\("data-fsid"\) === sid\) startSessHeadExit\(key, head\);/, "every column's header leaves with its run, one motion");
  assert.match(fn, /setTimeout\(\(\) => \{[\s\S]*stillOurs\(\) && c\.classList\.contains\("dismissing"\)[\s\S]*dropDismissed\(ids\);\s*\n\s*\}, 180\);/,
    "finalize after the 180ms exit, only what is still ours and still dismissing");
  assert.doesNotMatch(fn, /confirm\(/, "no confirm dialog: Undo is the safety net");
});

test("the control wears the header's size and the caret's quiet monochrome treatment, pushed to the far right", () => {
  assert.match(CSS, /\.feed-sess-clear \{ flex: none; margin-left: auto; padding: 0 5px; color: var\(--dim\); background: transparent;\s*\n\s*border: 0; font: inherit; font-weight: 400; line-height: 1; cursor: pointer;/);
  assert.match(CSS, /\.feed-sess-clear:hover, \.feed-sess-clear:focus-visible \{ color: var\(--fg\); \}/);
  assert.doesNotMatch(CSS, /\.feed-sess-clear[^\n]*font-size/, "no new font size on this surface");
  assert.doesNotMatch(CSS, /\.feed-sess-clear[^\n]*(red|--st-|--accent)/, "monochrome: no status colour, no accent");
});
