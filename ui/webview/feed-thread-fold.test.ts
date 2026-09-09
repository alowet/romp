// COLLAPSIBLE THREADS in the grouped feed (the user 2026-07-31): a caret right of each session-header name
// folds that run away to its name alone, and it STAYS folded — including for cards that do not exist yet
// — until you expand it again. Persisted with the rest of the feed's disclosure state.
//
// Keyed by (SID, COLUMN) since T263c (the user 2026-09-08, who wanted to collapse a session's Blocked or
// Completed cards independently of its Working ones): each column's header folds its own run, a card that
// lands in that column later inherits that column's fold, and a card moving columns shows under the fold
// state of the column it moves to. A pre-T263c bare-sid entry reads as every column (threadKeys), so an
// older fold keeps folding until a column is opened.
//
// No jsdom for the feed renderer, so the render side is pinned at the source; the STATE side is executed in
// feed-view-state.test.ts.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const FEED = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "feed.ts"), "utf8");
const CSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "feed.css"), "utf8");

test("the caret sits to the RIGHT of the session name, where it was asked for", () => {
  assert.match(FEED, /const fold = el\("button", "feed-sess-fold"\);/);
  assert.match(FEED, /h\.append\(nm, fold, cnt, svc, clr, svcList\);/, "name, then caret — not a leading tree triangle (the session-wide Clear sits after, at the far right; the user 2026-09-08)");
});

test("it is a caret, and it says which way it will go", () => {
  assert.match(FEED, /setText\(fold, shut \? "▸" : "▾"\);/);   // compare-first: headers repaint every render
  assert.match(FEED, /fold\.setAttribute\("aria-expanded", shut \? "false" : "true"\);/);
  assert.match(FEED, /fold\.setAttribute\("aria-label", \(shut \? "expand " : "collapse "\) \+ e\.name\);/);
});

test("folding hides that thread's cards and counts them onto the header", () => {
  // the header stands in for the run: entries are counted, not rendered
  assert.match(FEED, /if \(collapsedThreads\.has\(threadKey\(s, k\)\)\) \{ if \(head\) head\.folded \+= entryCards\(e\); continue; \}/,
    "the check is per (session, column): `k` is the column being assembled");
  assert.match(FEED, /setText\(foldn, String\(e\.folded\)\);/, "bare number (the user 2026-08-26) — words on hover only");
  assert.match(FEED, /foldn\.style\.display = shut && e\.folded \? "" : "none";/);
});

test("the column count reports the BOARD, not what you have open", () => {
  // folding a thread must not read as its work having left the column
  assert.match(FEED, /const nCards = \(es: Entry\[\]\) => es\.reduce\(\(n, e\) => n \+ entryCards\(e\), 0\);/);
});

test("the fold is per (SESSION, COLUMN) — T263c — so a card that does not exist yet inherits its column's fold", () => {
  assert.match(FEED, /const collapsedThreads = new Set<string>\(\);/);
  // the header entry carries its column, and the caret reads and toggles THAT key
  assert.match(FEED, /\| \{ kind: "sess"; t: number; sid: string; col: Column; name: string;/);
  assert.match(FEED, /head = \{ kind: "sess", t: e\.t, sid: s, col: k, name: src\.name,/);
  assert.match(FEED, /const tkey = threadKey\(e\.sid, e\.col\);\s*\n\s*const shut = collapsedThreads\.has\(tkey\);/);
  assert.match(FEED, /if \(collapsedThreads\.has\(tkey\)\) collapsedThreads\.delete\(tkey\); else collapsedThreads\.add\(tkey\);/);
  assert.doesNotMatch(FEED, /collapsedThreads\.(has|add|delete)\(e\.sid\)|collapsedThreads\.(has|add|delete)\(a\.sid\)|collapsedThreads\.has\(s\)/,
    "no site keys the fold by the bare sid any more");
  // the caret says which column it folds
  assert.match(FEED, /fold\.title = shut \? "show this session's cards in this column" : "collapse this session's cards in this column to its name — new cards here stay folded too";/);
  // …and it survives a reload with the rest of the disclosure state; a pre-T263c bare sid reads as every column
  assert.match(FEED, /for \(const k of st\.threads\) for \(const key of threadKeys\(k\)\) collapsedThreads\.add\(key\);/);
  assert.match(FEED, /threads: \[\.\.\.collapsedThreads\]/);
});

test("the click acknowledges immediately and cannot be lost to a re-render", () => {
  // the header ELEMENT is reused across renders (sessHeadEls), so the button node survives; the handler is
  // re-pointed at the current entry each update, and the fold is its own acknowledgement (local + render)
  assert.match(FEED, /fold\.onclick = \(ev\) => \{\s*\n\s*ev\.stopPropagation\(\);[\s\S]{0,200}?render\(\);\s*\n\s*\};/);
  assert.match(FEED, /card = sessHeadEls\.get\(key\) \|\| makeSessHead\(\);/);
});

test("a jump into a folded thread unfolds it instead of landing on nothing", () => {
  // revealCards scrolls to a DOM element; a folded card has none, so the navigation would silently no-op
  // the run the card RENDERS in (T263d): a turn-group member renders in the group's column (buildGroup's worst
  // member), not its own — keying the unfold by askColumn(a) opened an unrelated run and left the group's shut
  // …read from the MODEL, never a memo of the last paint (T263e: a memo of the grouped render went stale in flat
  // mode and under a held paint, so a reveal could unfold a run the card no longer renders in)
  assert.match(FEED, /for \(const \[tid, ms\] of turnGroups\(viewFiltered\(asks\)\)\) \{ const c = buildGroup\(tid, ms\)\.column; for \(const m of ms\) colOf\.set\(m\.itemId, c\); \}/,
    "the group rule the render applies, over the current filtered board");
  assert.match(FEED, /const tkey = threadKey\(a\.sid, colOf\.get\(a\.itemId\) \?\? askColumn\(a\)\);\s*\n\s*if \(collapsedThreads\.has\(tkey\) && extHoverMatches\("a:" \+ a\.itemId, keys\)\) \{/,
    "the run the card renders in — a group member's is the group's column — is what a jump unfolds");
  assert.doesNotMatch(FEED, /renderedCol/, "no memo of the last paint");
  // ONE rule for what forms a group: the render's bucket pass and the unfold both read turnGroups
  assert.match(FEED, /function turnGroups\(list: AskItem\[\]\): Map<string, AskItem\[\]> \{/);
  assert.match(FEED, /for \(const \[tid, ms\] of Array\.from\(byTurn\)\) if \(ms\.length < 2\) byTurn\.delete\(tid\);/, "a turn folds only with ≥2 current members");
  assert.match(FEED, /const byTurn = turnGroups\(shown\);/, "the render reads the shared rule");
  assert.equal((FEED.match(/turnGroups\(/g) || []).length, 3, "declared once, read by the render and by the unfold — nowhere else re-derives the rule");
  assert.match(FEED, /if \(opened\) render\(\);/);
});

test("the caret is a bare glyph, and a folded header keeps its group's spacing", () => {
  // a chip outline on every header would draw a border down the whole column
  assert.match(CSS, /\.feed-sess-fold \{[^}]*border: 0;/);
  assert.match(CSS, /\.feed-sess-fold \{[^}]*cursor: pointer/);
  assert.match(CSS, /\.feed-sess-fold:hover, \.feed-sess-fold:focus-visible \{ color: var\(--fg\); \}/);
  assert.match(CSS, /\.feed-sess-head\.folded \{ margin-bottom: 7px; \}/);
  // the count reuses the header's existing label size rather than adding one
  assert.match(CSS, /\.feed-sess-foldn \{[^}]*font-size: 0\.72em/);
});
