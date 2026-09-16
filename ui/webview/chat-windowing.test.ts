// Bidirectional virtualization of the chat transcript (the user 2026-06-25). A long session renders one row
// per event (or per folded compact item) — thousands of nodes — which made switching to / scrolling a big
// session slow. Both modes now render a bounded window of UNITS [winStart, winEnd) with a TOP spacer for the
// hidden head and a BOTTOM spacer for the hidden tail; on scroll we re-render AROUND wherever the viewport
// lands, so random-access jumps work, not just contiguous scroll-back. Source-level pins (no jsdom for the
// renderer), mirroring the other render.ts tests.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const CSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "styles.css"), "utf8");

test("windowing constants are sane: a tail, a render radius and a re-window margin, a switch cap", () => {
  // (the trailing re-check window, TAIL_RECHECK, is gone: the tail path re-renders exactly from the kernel's
  // first changed event — chat-exact-tail.test.ts)
  const tail = Number(/const WINDOW_TAIL = (\d+);/.exec(RENDER)?.[1]);
  const radius = Number(/const WINDOW_RADIUS = (\d+);/.exec(RENDER)?.[1]);
  const margin = Number(/const REVIRT_MARGIN = (\d+);/.exec(RENDER)?.[1]);
  const cap = Number(/const WINDOW_CAP = (\d+);/.exec(RENDER)?.[1]);
  assert.ok(tail > 0, "a tail window");
  assert.ok(radius > margin && margin > 0, "radius > margin > 0");
  assert.ok(cap > tail, "cap > tail");
});

test("units unify both modes: one per event (normal) or the folded compactDisplay stream (compact)", () => {
  assert.match(RENDER, /function displayItems\(s: Session\): DisplayItem\[\]/);
  assert.match(RENDER, /if \(!settings\.compact\) \{[\s\S]*?out\.push\(\{ kind: "event", index: i \}\);/);
  assert.match(RENDER, /out = compactDisplay\([\s\S]*?\n\s*\}\s*\n\s*return withGapItems\(s, out\);/, "the folded stream, then the gaps between the runs interleaved (T386 stage 2)");
});

test("every rendered row is tagged data-unit, so the scroll↔unit map can locate it", () => {
  assert.match(RENDER, /node\.dataset\.unit = String\(u\);/);          // appendItem (window build)
  assert.match(RENDER, /node\.dataset\.unit = String\(i\);\s*\/\/ unit === event/); // normal incremental append
});

test("renderWindowItems renders [unitStart, unitEnd) with a TOP and a BOTTOM spacer", () => {
  assert.match(RENDER, /function renderWindowItems\(v: View, s: Session, items: DisplayItem\[\], unitStart: number, unitEnd: number, working: boolean\): void/);
  assert.match(RENDER, /if \(unitStart > 0\) v\.el\.appendChild\(el\("div", "tx-spacer tx-spacer-top"\)\);/);
  assert.match(RENDER, /if \(unitEnd < total\) v\.el\.appendChild\(el\("div", "tx-spacer tx-spacer-bot"\)\);/);
  assert.match(RENDER, /v\.winStart = unitStart; v\.winEnd = unitEnd;/);
  assert.match(RENDER, /v\.spacerCount = unitStart; v\.spacerCountBot = total - unitEnd;/);
});

test("sizeSpacers sizes BOTH spacers by hidden-unit count × avg, caching only a visible measurement", () => {
  assert.match(RENDER, /function sizeSpacers\(v: View\): void/);
  assert.match(RENDER, /const topAfter = top \? hiddenHeight\(v, 0, v\.spacerCount \?\? 0, avg\) : 0, botAfter = bot \? hiddenHeight\(v, total - \(v\.spacerCountBot \?\? 0\), total, avg\) : 0;/, "both spacers by the hidden units' own heights: a gap's estimate, else the average (T386 stage 2)");
  assert.match(RENDER, /if \(top\) top\.style\.height = topAfter \+ "px";\s*\n\s*if \(bot\) bot\.style\.height = botAfter \+ "px";/);
  assert.match(RENDER, /if \(h > 0 && n > 0\) v\.avgTurnH = h \/ n;/);   // don't cache a display:none 0
});

test("unitAtScroll maps a spacer by avg height and a rendered row by its data-unit", () => {
  assert.match(RENDER, /function unitAtScroll\(v: View, content: HTMLElement\): number/);
  assert.match(RENDER, /if \(st < topH\) \{[^\n]*\n\s*if \(!v\.gapUnits\) return Math\.max\(0, Math\.floor\(st \/ avg\)\);/, "in the top spacer: the average when no gap sits in it, else a walk over the hidden units' heights (T386 stage 2)");
  assert.match(RENDER, /if \(st < t0 \+ c\.offsetHeight\) return lastUnit;/);                  // straddling a rendered row
  assert.match(RENDER, /return \(v\.winEnd \?\? 0\) \+ Math\.floor\(\(st - bTop\) \/ avg\);/);  // in the bottom spacer
});

test("scroll re-windows around the viewport (steady scroll OR jump) when near a rendered edge", () => {
  assert.match(RENDER, /function virtualizeToViewport\(\): void/);
  // CHEAP px pre-check on every scroll; the precise unit walk only runs when near a rendered edge
  assert.match(RENDER, /const nearTopEdge = \(v\.winStart \?\? 0\) > 0 && st < topH \+ edgePx;/);
  assert.match(RENDER, /const nearBotEdge = \(v\.winEnd \?\? total\) < total && st \+ vh > renderedBottom - edgePx;/);
  assert.match(RENDER, /if \(!nearTopEdge && !nearBotEdge\) return;/);
  assert.match(RENDER, /const idx = unitAtScroll\(v, content\);/);
  assert.match(RENDER, /renderWindowItems\(v, s, items, Math\.max\(0, c - WINDOW_RADIUS\), Math\.min\(items\.length, c \+ WINDOW_RADIUS\), working\);/);
  // it re-anchors the focus unit so it doesn't jump, coalesced to one frame; a re-window of resident content shows no cue (T402, T386 stage 2)
  assert.match(RENDER, /writeScroll\(content, yNow - beforeY, "rewindow"\);/);   // (T262: every #content write rides writeScroll)
  assert.doesNotMatch(RENDER, /showLoadingPill\(\)|hideLoadingPill\(\)/, "the per-fetch pill is retired: the ONE landing notice and the gaps' glyphs replace it (T386 stage 2)");
  assert.match(RENDER, /c\.addEventListener\("scroll", virtualizeToViewport, \{ passive: true \}\);/);
});

test("the ONE landing notice shows while a navigation's window is on the wire, pinned top-center of the chat SECTION, never the viewport (T365, T386 stage 2)", () => {
  assert.match(RENDER, /function showLandingNotice\(sid: string, t: number \| null \| undefined\): void/);
  assert.match(RENDER, /landingNoticeEl\.textContent = landingNotice\(t, clockOf\);/, "its words come from the pure rule: the target's time in the reader's clock, and the click to stay");
  assert.match(RENDER, /landingNoticeEl\.addEventListener\("click", \(\) => cancelLanding\(\)\);/, "clicking it is the ONLY cancel");
  const fn = RENDER.slice(RENDER.indexOf("function showLandingNotice(sid: string"), RENDER.indexOf("function hideLandingNotice(): void"));
  // T365 (the user 2026-09-12): a viewport-fixed pill appended to the body sat on the tabs, and on the tabs themselves
  // once the strip wrapped; it now rides a zero-height anchor inserted right before #content, the transcript's top edge
  assert.doesNotMatch(fn, /document\.body\.appendChild/, "the pill no longer lands in the body");
  assert.match(fn, /anchor\.className = "tx-loading-anchor";/);
  assert.match(fn, /content\.parentNode\.insertBefore\(anchor, content\);/, "the anchor sits right before #content, below the strip and the ledger box");
  assert.match(fn, /if \(!landingNoticeEl\.isConnected\)/, "idempotent: one anchor, re-made only if a rebuild dropped it");
  assert.ok(!CSS.includes("#live-paused") && !CSS.includes(".live-paused"), "the paused strip's CSS is gone with the strip (T386 stage 2)");
  const anchorRule = CSS.slice(CSS.indexOf(".tx-loading-anchor {")); const anchorBody = anchorRule.slice(0, anchorRule.indexOf("}"));
  assert.match(anchorBody, /position: relative;/); assert.match(anchorBody, /height: 0;/); assert.match(anchorBody, /pointer-events: none;/);
  const pillRule = CSS.slice(CSS.indexOf(".tx-landing-notice {")); const pillBody = pillRule.slice(0, pillRule.indexOf("}"));
  assert.match(pillBody, /position: absolute; top: 10px; left: 50%; transform: translateX\(-50%\);/);
  assert.doesNotMatch(pillBody, /position: fixed/);
  // the surface is tokened for both themes (reads on cream): no hard-coded dark rgba background or border
  assert.match(pillBody, /background: var\(--vscode-menu-background, var\(--surface-raised\)\);/);
  assert.match(pillBody, /border: 1px solid var\(--menu-border\);/);
  assert.doesNotMatch(pillBody, /rgba\(20, 24, 33/);
  assert.match(pillBody, /pointer-events: auto; cursor: pointer;/, "the notice takes the click: the ONE cancel must be reachable (T386 stage 2, HIGH)");
  assert.match(anchorBody, /pointer-events: none;/, "…while its anchor stays inert, so it never eats the transcript's clicks");
});

test("syncView: a fresh build / rewind renders the TAIL window, clamped to the last compaction boundary", () => {
  // the default window opens AT (never below) the newest compaction — pre-compaction history is scrubbed
  // from the default view (the user 2026-07-07); lastCompactUnit floors the window start.
  assert.match(RENDER, /if \(firstBuild \|\| rewind\) \{\s*\n\s*const start = Math\.max\(0, total - WINDOW_TAIL, lastCompactUnit\(s, items\)\);\s*\n\s*renderWindowItems\(v, s, items, start, total, working\);/);
});

test("syncView: a pure tab switch is a NO-OP render (reveal the cached DOM)", () => {
  assert.match(RENDER, /if \(v\.rendered === len && !v\.stale && v\.el\.childNodes\.length > 0\) return v;/);
});

test("syncView: compact / an in-place change re-renders the CURRENT window; a browse append just grows the bottom spacer", () => {
  // compact mode and any stale (tool-group toggle, off-screen update) re-render where the user is
  assert.match(RENDER, /if \(settings\.compact \|\| v\.stale\) \{[\s\S]*?renderWindowItems\(v, s, items, ws, we, working\);/);
  // browsing history away from the tail: appended events land below the window → grow the bottom spacer only
  assert.match(RENDER, /if \(!wasAtTail\) \{\s*\n\s*v\.spacerCountBot = total - \(v\.winEnd \?\? total\);/);
});

test("a new message while scrolled UP keeps the viewport put (no backwards jump)", () => {
  // appendActive: at the bottom → follow it; scrolled up → restore ANCHOR-relative after the sync (the
  // turn at the viewport top keeps its exact offset — raw scrollTop only when the anchor was evicted; the
  // user 2026-07-05, subagent report cards growing ABOVE the viewport moved the raw offset's meaning), and
  // tell syncView atBottom=stick so a compact append KEEPS winStart (content above the viewport unchanged)
  // instead of evicting the top — which (with the compact full-rebuild that resets scrollTop) was jumping
  // the view "backwards" when messages arrived (the user 2026-06-25).
  assert.match(RENDER, /const before = content\.scrollTop;/);
  assert.match(RENDER, /syncView\(activeId, stick\);/);
  assert.match(RENDER, /else if \(!\(v && restoreScrollAnchor\(content, v, anchor, before\)\)\) writeScroll\(content, before, "append-raw", false, before\);/);
  // the compact branch keeps winStart on a scrolled-up append
  assert.match(RENDER, /const keepTop = wasAtTail && atBottom === false;/);
  assert.match(RENDER, /const ws = keepTop \? \(v\.winStart \?\? 0\)/);
});

test("an oversized view (window grew past the cap) re-collapses to the tail on switch", () => {
  // `!reshow &&` leads since T249: the re-collapse is a SWITCH rule, never applied to a re-show of the view on screen
  assert.match(RENDER, /if \(!reshow && !pendingAnchor && pendingAnchorT == null\s*\n?\s*&& v\.el\.querySelectorAll\("\.turn"\)\.length > WINDOW_CAP\) \{/);
  assert.match(RENDER, /v\.rendered = 0; v\.winStart = 0; v\.avgTurnH = undefined; v\.stick = true;/);
});

test("a deep-link off the current window renders a fresh window AROUND the target unit, then lands", () => {
  assert.match(RENDER, /let u = items\.findIndex\(\(it\) => it\.kind === "toolgroup" \|\| it\.kind === "noticegroup" \? it\.indices\.includes\(idx\) : it\.kind === "event" && it\.index === idx\);/, "a gap item indexes no event (T386 stage 2)");
  assert.match(RENDER, /renderWindowItems\(v, s, items, Math\.max\(0, u - WINDOW_RADIUS\), Math\.min\(items\.length, u \+ WINDOW_RADIUS\), working\);/);
});

test("round two/three code fixes each carry a pin (T386 stage 2, low 1)", () => {
  const winStart = RENDER.indexOf("function chatWindow(msg: any) {");
  const win = RENDER.slice(winStart, RENDER.indexOf("\nfunction ", winStart + 1));
  const cTurns = RENDER.slice(RENDER.indexOf("function chatTurns(msg: any)"), RENDER.indexOf("function chatHead(msg: any)") >= 0 ? RENDER.indexOf("function chatHead(msg: any)") : winStart);
  // the socket death clears every in-flight ask's state, not the glyph alone (medium 1)
  assert.match(RENDER, /function onWireDown\(\): void \{[\s\S]*?if \(hostOf\(parseGapKey\(k\)\.sid\) === ""\) gapLoading\.delete\(k\);[\s\S]*?windowAsks\.clear\(\); loadingOlder\.clear\(\);[\s\S]*?hideLandingNotice\(\);/, "the wire's down edge (the socket's or the pane's) clears the page asks, every ask record, the older-ask set and the notice");
  // sizeSpacers does not average the gap element (medium 3, round one)
  const pxBlock = RENDER.slice(RENDER.indexOf("if (v.pxPerTurn == null) {"), RENDER.indexOf("if (h > 0 && turns > 0) v.pxPerTurn = h / turns;"));
  assert.match(pxBlock, /if \(c\.classList\.contains\("tx-spacer"\) \|\| c\.classList\.contains\("tx-gap"\) \|\| !c\.classList\.contains\("turn"\)\) continue;/, "the px-per-turn measure skips the gap element and every non-turn child (pinned inside its own block; round four low 3, round five)");
  const unitBlock = RENDER.slice(RENDER.indexOf("if (v.avgTurnH == null) {"), RENDER.indexOf("if (h > 0 && n > 0) v.avgTurnH = h / n;"));
  assert.match(unitBlock, /c\.classList\.contains\("tx-gap"\)\) continue;/, "…and so does the per-unit measure");
  // the region-fill view resets (chatTurns, chatWindow) keep the measured averages across fills (low 1); chatHead's prepend reset may still clear them
  assert.ok(cTurns.includes("v.rendered = 0; v.winStart = 0; v.winEnd = 0; v.spacerCount = undefined;"), "chatTurns resets the window");
  assert.doesNotMatch(cTurns, /v\.winEnd = 0; v\.avgTurnH = undefined;/, "…without clearing the measured average (the fill keeps it, low 1)");
  assert.doesNotMatch(win, /v\.winEnd = 0; v\.avgTurnH = undefined;/, "chatWindow's fill keeps the measured average too (low 1)");
  // a second deep link while one is on the wire is refused with a cue, not silently repointed (low 6, low 4)
  assert.match(RENDER, /if \(live\) \{ landTrail\.push\("pointer-fetch-busy"\); landToast\("still going to the earlier message"\); return false; \}/, "the busy refusal toasts a cue");
  // the cancelled mark is read once before any early return (low 2)
  assert.ok(win.indexOf("const rec = takeWindowAsk(msg.id,") >= 0 && win.indexOf("const rec = takeWindowAsk(msg.id,") < win.indexOf("!Array.isArray(msg.span)"), "the cancelled mark is read before the missing/span-less return");
  // a mid-transcript gap keeps headTotal null (low 7)
  assert.match(RENDER, /s\.regions && s\.regions\.some\(\(r\) => r\.kind === "gap"\)\)\) s\.headTotal/, "chatTail keeps no head total while a gap holds older history");
});

test("round four and five fixes each carry a pin (T386 stage 2, round five low 1)", () => {
  const fill = RENDER.slice(RENDER.indexOf("function fillInPlace(sid: string, v: View | undefined): void {"), RENDER.indexOf("\nfunction ", RENDER.indexOf("function fillInPlace(sid: string, v: View | undefined): void {") + 1));
  assert.match(fill, /const keepVisible = !!keep && keep\.y < content\.clientHeight - 1;/, "a row anchors the fill when it intersects the viewport, whatever the sign of its top (medium 1)");
  assert.doesNotMatch(fill, /keep\.y >= -1/, "…no lower bound on the row's top");
  assert.match(fill, /const turnsNow = turnOfEvents\(s\);\s*\n\s*const pointBefore = turnUnderTop\(v, s, items, turnsNow, content, topBefore\);/, "the point under the viewport top is named as a turn before the rebuild (medium B)");
  assert.match(fill, /if \(pointBefore != null\) u = unitOfTurn\(items, turnsNow, Math\.floor\(pointBefore\)\);/, "…and the window renders around the unit holding that turn in the NEW items, never a stale unit index (round six: unitOfTurn)");
  assert.match(fill, /const mapped = pointBefore != null \? yOfTurn\(v, s, items, turnsNow, content, pointBefore\) : null;\s*\n\s*y = mapped != null \? mapped : topBefore;/, "…and put back by its turn after it, scrollTop kept only when the point cannot be named (medium A: the anchor row gone falls to the turn, never a doubled write)");
  assert.doesNotMatch(fill, /heightAbove/, "the view-coordinate tautology is gone");
  assert.match(RENDER, /function turnUnderTop\(v: View, s: Session, items: DisplayItem\[\], turns: number\[\], content: HTMLElement, top: number\): number \| null \{/, "the turn-under-top helper");
  assert.match(RENDER, /function yOfTurn\(v: View, s: Session, items: DisplayItem\[\], turns: number\[\], content: HTMLElement, t: number\): number \| null \{/, "the turn-to-scroll helper");
  assert.match(RENDER, /if \(hostOf\(parseGapKey\(k\)\.sid\) === ""\) gapLoading\.delete\(k\);[\s\S]*?windowAsks\.clear\(\); loadingOlder\.clear\(\);/, "the socket death clears the cancelled mark too (medium 2)");
  assert.match(RENDER, /const liveLanding = !!landingNoticeSid \|\| Array\.from\(windowAsks\.values\(\)\)\.some\(\(a\) => a\.some\(\(r\) => !r\.cancelled && !!r\.gap\)\);/, "the wsdown toast fires only for a landing the reader had not cancelled (low 1)");
  assert.match(RENDER, /const nospan = !msg\.missing && Array\.isArray\(msg\.events\) && msg\.events\.length > 0 && !Array\.isArray\(msg\.span\);/, "missing is tested first; only a reply with events and no span is an older host (medium 3; round five low 3)");
  assert.match(RENDER, /const preJumpOrigin = rec\.origin;/, "the pre-jump origin is consumed by every window reply (low 2)");
  const px = RENDER.slice(RENDER.indexOf("if (v.pxPerTurn == null) {"), RENDER.indexOf("if (h > 0 && turns > 0) v.pxPerTurn = h / turns;"));
  assert.match(px, /\|\| !c\.classList\.contains\("turn"\)\) continue;/, "px-per-turn counts turn rows only, never cards or dividers (round five)");
});

test("round six fixes each carry a pin (T386 stage 2): rows name their turn, the fill reads it, a fill that shows nothing re-windows", () => {
  const fill = RENDER.slice(RENDER.indexOf("function fillInPlace(sid: string, v: View | undefined): void {"), RENDER.indexOf("\nfunction ", RENDER.indexOf("function fillInPlace(sid: string, v: View | undefined): void {") + 1));
  const under = RENDER.slice(RENDER.indexOf("function turnUnderTop("), RENDER.indexOf("\nfunction ", RENDER.indexOf("function turnUnderTop(") + 1));
  const yOf = RENDER.slice(RENDER.indexOf("function yOfTurn("), RENDER.indexOf("\nfunction ", RENDER.indexOf("function yOfTurn(") + 1));
  const append = RENDER.slice(RENDER.indexOf("function appendItem("), RENDER.indexOf("\nfunction ", RENDER.indexOf("function appendItem(") + 1));
  // medium: the point is named by POSITION, the row's own turn stamped at its paint, never a uuid lookup into s.events (a row anchored on a tool_result uuid has none)
  assert.match(append, /const turnOf = turns && f0 >= 0 && f0 < turns\.length \? String\(turns\[f0\]\) : null;/, "appendItem knows the unit's absolute turn");
  assert.match(append, /node\.dataset\.unit = String\(u\); if \(turnOf != null\) node\.dataset\.turn = turnOf;/, "…and stamps it on every node the unit appends, beside data-unit");
  assert.match(RENDER, /const turns = s\.regions \? turnOfEvents\(s\) : null;\s*\/\/[^\n]*\n\s*for \(let u = unitStart; u < unitEnd; u\+\+\) prevEpoch = appendItem\(v, s, items, u, prevEpoch, walk, working, turns\);/, "renderWindowItems names the turns once per paint and hands them to every unit");
  assert.match(under, /const tr = c\.dataset\.turn;[^\n]*\n\s*if \(tr != null && tr !== ""\) return Number\(tr\) \+ \(top - y0\) \/ h;/, "turnUnderTop reads the row's own turn");
  assert.doesNotMatch(under, /s\.events\.findIndex/, "…and looks nothing up by uuid");
  assert.match(yOf, /const tr = c\.dataset\.turn; if \(tr == null \|\| tr === "" \|\| Number\(tr\) !== whole\) continue;/, "yOfTurn finds the row by its own turn");
  assert.doesNotMatch(yOf, /s\.events\.findIndex/, "…and looks nothing up by uuid either");
  // the unit holding a turn is the gap containing it or the LAST run unit at or below it (equality on a first unit missed folded user rows)
  assert.match(RENDER, /function unitOfTurn\(items: DisplayItem\[\], turns: number\[\], t: number\): number \{[\s\S]*?if \(turns\[f\] <= t\) u = i; else break;/, "unitOfTurn: the last unit at or below the turn");
  assert.match(fill, /if \(u < 0\) \{ const rowEl = v\.el\.querySelector\(`\.turn\[data-uuid="\$\{cssEscape\(keep\.uuid\)\}"\]`\) as HTMLElement \| null; const tr = rowEl\?\.dataset\.turn; if \(tr\) u = unitOfTurn\(items, turnsNow, Number\(tr\)\); \}/, "an anchor row no event uuid names still centres the window by its turn");
  // a fill that leaves no row on screen re-windows once around the named point and puts it back
  assert.match(fill, /if \(pointBefore != null && !rowOnScreen\(v, content\)\) \{\s*\n\s*const u2 = unitOfTurn\(items, turnsNow, Math\.floor\(pointBefore\)\);[\s\S]*?const y2 = yOfTurn\(v, s, items, turnsNow, content, pointBefore\);\s*\n\s*writeScroll\(content, y2 != null \? y2 : topBefore, "gap-fill", false, topBefore\);/, "the zero-row post-check re-windows around the point");
  assert.match(RENDER, /function rowOnScreen\(v: View, content: HTMLElement\): boolean \{/, "the on-screen row check");
  // low: a run opening mid-turn starts AT its lo, so its first user row begins lo + 1 (the tail slice that opens with an assistant)
  const turnsFn = RENDER.slice(RENDER.indexOf("function turnOfEvents(s: Session): number[] {"), RENDER.indexOf("\nfunction ", RENDER.indexOf("function turnOfEvents(s: Session): number[] {") + 1));
  assert.match(turnsFn, /let t = \(first && first\.kind === "user"\) \|\| r\.lo === 0 \? r\.lo - 1 : r\.lo;/, "turnOfEvents: a user-first run and the head run (head cards precede turn 0) count up from lo - 1; a run opening mid-turn starts at lo");
  assert.doesNotMatch(turnsFn, /let t = r\.lo - 1;/, "…the unconditional lo - 1 is gone");
  // the px-per-turn measure takes the WHOLE row, action strip included: a gap stands for rows as they will render, and every user row
  // (history rows too) carries the strip; subtracting it drew the gap 16 percent short in the regions lab's sizing road
  const px = RENDER.slice(RENDER.indexOf("if (v.pxPerTurn == null) {"), RENDER.indexOf("if (h > 0 && turns > 0) v.pxPerTurn = h / turns;"));
  assert.match(px, /h \+= c\.offsetHeight;/, "px-per-turn sums whole rows");
  assert.doesNotMatch(px, /msg-acts/, "…and subtracts no action strip");
});

test("round seven fixes each carry a pin (T386 stage 2): a fault has its own word, a cancelled landing is not busy, the dead evidence writers are gone", () => {
  const winStart = RENDER.indexOf("function chatWindow(msg: any) {");
  const win = RENDER.slice(winStart, RENDER.indexOf("\nfunction ", winStart + 1));
  // medium 1: the kernel's fault (missing true, fault true) is no verdict on the anchor: its own trail word and toast, the seek ended, never "couldn't locate"
  assert.ok(win.indexOf("if (msg.fault) {") >= 0 && win.indexOf("if (msg.fault) {") < win.indexOf("if (msg.missing || !(msg.events || []).length || !Array.isArray(msg.span)) {"), "chatWindow tests fault before missing (a fault carries missing too)");
  assert.match(win, /if \(msg\.fault\) \{[\s\S]*?landTrail\.push\("window-fault"\);\s*\n\s*vscodeApi\?\.postMessage\(\{ type: "locateDiag", id: msg\.id, ok: false, trail: landTrail\.slice\(\), anchor: anchorUuid, kind: "fault"[^\n]*\n\s*landToast\("the history could not be loaded just now"\);\s*\n\s*clearSeek\(\);/, "a fault files kind fault, says the history could not be loaded just now, and ends the seek");
  assert.match(win, /landToast\(nospan \? "this session's host is an older version; open it there to jump" : "couldn't locate this in the transcript"\);\s*\n\s*clearSeek\(\);/, "the honest end ends the seek too");
  // medium 3 (round seven), re-shaped in round eight: the landing's state is one record per ask; the cancel marks its own record only
  const cancel = RENDER.slice(RENDER.indexOf("function cancelLanding(): void {"), RENDER.indexOf("\n/**", RENDER.indexOf("function cancelLanding(): void {")));
  assert.match(cancel, /const rec = liveWindowAsk\(sid\);[\s\S]*?if \(rec\) \{ rec\.cancelled = true; rec\.origin = null; rec\.gap = null; \}/, "the cancel marks the live ask's record and consumes its origin and gap, nothing else's");
  assert.match(cancel, /for \(const g of Array\.from\(gv\.el\.querySelectorAll\("\.tx-gap\.tx-gap-loading"\)\) as HTMLElement\[\]\) \{ if \(!gapHasAsk\(sid, \{ lo: Number\(g\.dataset\.lo\), hi: Number\(g\.dataset\.hi\) \}\)\) g\.classList\.remove\("tx-gap-loading"\); \}/, "…and every gap no ask names any more sheds its glyph (the truth, not a held record)");
  assert.match(RENDER, /if \(live\) \{ landTrail\.push\("pointer-fetch-busy"\);/, "the busy gate reads a LIVE window ask on another anchor alone; a cancelled ask, an older fetch in flight, or this landing's own re-attempt is not busy");
  // round eight: one record per ask, resolved only by its own reply, superseded only by a newer ask on its anchor, expired by the socket death
  assert.match(RENDER, /^interface WindowAsk \{ anchor: string; nav: boolean; named: boolean; t: number \| null; kind: string \| null; origin: number \| null; gap: \{ lo: number; hi: number \} \| null; cancelled: boolean; \}$/m, "the record carries every mark an ask writes");
  assert.match(RENDER, /const i = anchor == null \? 0 : a\.findIndex\(\(r\) => r\.anchor === anchor\);\s*\n\s*if \(i < 0\) return null;\s*\n\s*const \[rec\] = a\.splice\(i, 1\);/, "a reply takes the OLDEST record on its anchor, or the oldest of all when it names none, and never another's");
  const around = RENDER.slice(RENDER.indexOf("function requestAround(sid: string, uuid: string): boolean {"), RENDER.indexOf("\nfunction chatWindow(msg: any) {"));
  assert.match(around, /if \(!s \|\| s\.proto !== 2 \|\| loadingOlder\.has\(sid\) \|\| liveWindowAsk\(sid\)\) return false;/, "a live ask makes the session busy; a cancelled one does not");
  assert.match(around, /for \(let i = arr\.length - 1; i >= 0; i--\) if \(arr\[i\]\.cancelled && arr\[i\]\.anchor === uuid\) arr\.splice\(i, 1\);\s*\/\/[^\n]*\n\s*const rec: WindowAsk = \{ anchor: uuid, nav,/, "a fresh ask on the anchor supersedes a cancelled twin, then leaves its own record");
  assert.match(around, /preJumpIntoGap\(sid, pendingAnchorT, rec\);/, "the pre-jump writes the ask's own record");
  assert.match(around, /arr\.push\(rec\);[^\n]*\n\s*vscodeApi\?\.postMessage\(\{ type: "loadAround", id: sid, uuid \}\);/, "the record and the ask are one step: a throw in the notice or the pre-jump strands no live record without its ask");
  assert.match(around, /try \{ showLandingNotice\(sid, pendingAnchorT\); preJumpIntoGap\(sid, pendingAnchorT, rec\); \} catch \(e\) \{ landTrail\.push\("pre-jump-threw"\); \}/, "…and neither may lose the ask");
  assert.match(RENDER, /if \(rec\) \{ rec\.gap = \{ lo: r\.lo, hi: r\.hi \}; rec\.origin = content\.scrollTop; \}/, "…its gap and its origin");
  assert.match(win, /^\s*const rec = takeWindowAsk\(msg\.id, typeof msg\.anchor === "string" \? msg\.anchor : undefined\);\s*\n\s*const s = sessions\.get\(msg\.id\);\s*\n\s*if \(!rec\) \{/m, "chatWindow resolves the reply to its record first; a reply with no record merges in place and moves nothing");
  assert.ok(win.indexOf('landTrail.push("window-stray");') > 0 && win.indexOf('landTrail.push("window-stray");') < win.indexOf("const cancelled = rec.cancelled;"), "…and says so in the trail");
  assert.match(win, /const wasLanding = !cancelled && landingNoticeSid === msg\.id;/, "a cancelled ask's reply leaves the notice to the live ask");
  assert.match(RENDER, /for \(const r of windowAsks\.get\(sid\) \?\? \[\]\) if \(!r\.cancelled && r\.gap && r\.gap\.lo === gap\.lo && r\.gap\.hi === gap\.hi\) return true;/, "gapHasAsk reads the live records");
  // the redial re-ask (2026-09-15): a gapLoading key parses from the RIGHT (a host-prefixed remote sid stays whole, so the in-flight
  // guard matches a federated gap), and a redial re-sends every outstanding loadTurns, event-keyed, no timer
  assert.match(RENDER, /const parts = k\.split\(":"\); const hi = Number\(parts\.pop\(\)\), lo = Number\(parts\.pop\(\)\);\s*\n\s*return \{ sid: parts\.join\(":"\), lo, hi \};/, "a gapLoading key parses from the right: a remote sid keeps its host prefix");
  assert.match(RENDER, /reaskOutstandingGaps\(Array\.from\(gapLoading\), h\);/, "a relay reopen (romp:hostRelayUp) re-sends that host's outstanding loadTurns");
  assert.doesNotMatch(RENDER, /\b(cancelledLandings|preJumpFrom|pendingWindowNav)\b|const landingGaps\b/, "no per-session slot for a landing's state remains");
  // low 7: the older edge's evidence writers lost their reader with the pill's latch and are off the scroll hot path
  assert.doesNotMatch(RENDER, /olderEvidence|noteOlderEvidence|NAV_KEYS/, "no dead evidence writer on wheel, touch, key or drag");
  // low 6: the notice has the hover cue the pill had; nothing styles the retired pill
  assert.match(CSS, /\.tx-landing-notice:hover \{ border-color: var\(--accent\); \}/, "the notice shows an accent border on hover: it takes the only cancel click");
  assert.doesNotMatch(CSS, /tx-loading-pill/, "no rule for the retired pill");
});

test("round nine fixes each carry a pin (T386 stage 2): an older fetch in flight re-points, only a live ask is busy; the pipe's down edge clears like the socket's", () => {
  const sca = RENDER.slice(RENDER.indexOf("function scrollToAnchor("), RENDER.indexOf("\nfunction ", RENDER.indexOf("function scrollToAnchor(") + 1));
  assert.match(sca, /if \(live\) \{ landTrail\.push\("pointer-fetch-busy"\); landToast\("still going to the earlier message"\); return false; \}\s*\n(\s*\/\/[^\n]*\n)*\s*if \(loadingOlder\.has\(activeId\)\) \{ pendingOlderAnchor\.set\(activeId, uuid\); pendingOlderKeepY\.delete\(activeId\); pendingAnchor = uuid; anchorPendingOlder = true; landTrail\.push\("pointer-fetch-older"\); return false; \}/, "only a live window ask is busy; an older fetch in flight is re-pointed onto the anchor and arms the landing for chatHead's arrival");
  assert.doesNotMatch(sca, /loadingOlder\.has\(activeId\) \|\| liveWindowAsk\(activeId\)/, "the unconditional refusal is gone");
  assert.match(RENDER, /if \(landedNow \|\| !anchorPendingOlder\) \{ pendingAnchor = null; pendingAnchorKeepY = null; \}/, "the reload restore's caller keeps its arm while an older fetch is pointed at the anchor");
  assert.match(RENDER, /^window\.addEventListener\("romp:wsdown", \(\) => onWireDown\(\)\);$/m, "the socket's down edge runs the one clear");
  assert.match(RENDER, /if \(m\.type === "pipeState"\) \{ if \(!m\.up\) \{ markPendingLost\("connection"\); onWireDown\(\); \} pipeBanner\(!!m\.up, Number\(m\.queued\) \|\| 0\); return; \}/, "…and so does the VS Code pane's pipe-down edge");
  assert.match(RENDER, /function onWireDown\(\): void \{[\s\S]*?if \(hostOf\(parseGapKey\(k\)\.sid\) === ""\) gapLoading\.delete\(k\);[\s\S]*?windowAsks\.clear\(\); loadingOlder\.clear\(\);[\s\S]*?hideLandingNotice\(\);[\s\S]*?pendingAnchor = null; anchorPendingOlder = false;/, "the clear: page asks, every ask record, the older-ask set, the glyphs, the notice, the arm");
});

test("round ten fixes each carry a pin (T386 stage 2): a re-attempt waits on its own live ask; the not-rendered path names the state it saw", () => {
  const sca = RENDER.slice(RENDER.indexOf("function scrollToAnchor("), RENDER.indexOf("\nfunction ", RENDER.indexOf("function scrollToAnchor(") + 1));
  assert.match(sca, /const live = liveWindowAsk\(activeId\);\s*\n\s*if \(live && live\.anchor === uuid\) \{ anchorPendingOlder = true; landTrail\.push\("pointer-fetch-waiting"\); if \(pendingAnchorClick\) pulseLandingNotice\(\); return false; \}[^\n]*\n\s*if \(live\) \{ landTrail\.push\("pointer-fetch-busy"\); landToast\("still going to the earlier message"\); return false; \}/, "the same landing's re-attempt waits without a cue (a real second click pulses the notice, round eleven); a different anchor while one is live is refused with the cue");
  assert.match(sca, /scrollDiagRow\("landmiss", \{ sid: activeId, anchor: uuid\.slice\(-12\), proto:[^\n]*noframe: !sm \|\| sm\.proto == null, trail: landTrail\.slice\(-4\) \}\);\s*\n\s*pendingAnchor = uuid; landTrail\.push\("pointer-not-rendered"\); return false;/, "the not-rendered path files the branch state it saw (proto, events, regions, the head, the older wire, whether a frame existed) before it stands the attempt down");
  assert.doesNotMatch(RENDER, /awaitingFrameAnchor|pointer-no-frame|frame-rearm/, "no arm-keeping for a shape that did not reproduce: the reload restore runs only once a frame is on the tab");
  assert.match(RENDER, /\| "unitchange" \| "regionask" \| "landmiss", data: any\): void \{/, "the row kind is budgeted with the other scroll rows");
});

test("round eleven fixes each carry a pin (T386 stage 2): a real second click re-pulses the notice; no page-side wait for the handshake remains (the kernel serves no chat frame before it)", () => {
  assert.doesNotMatch(RENDER, /readySent|frameAfterReady|restore-waits-frame/, "the wait for the kernel's answer to ready lives in the kernel (no chat frame before the handshake), not in the page");
  const sca = RENDER.slice(RENDER.indexOf("function scrollToAnchor("), RENDER.indexOf("\nfunction ", RENDER.indexOf("function scrollToAnchor(") + 1));
  assert.match(sca, /if \(live && live\.anchor === uuid\) \{ anchorPendingOlder = true; landTrail\.push\("pointer-fetch-waiting"\); if \(pendingAnchorClick\) pulseLandingNotice\(\); return false; \}/, "a real second click on the anchor a landing is on the wire for pulses the notice; a pass's re-attempt does not");
  assert.match(RENDER, /pendingAnchorClick = typeof m\.anchor === "string";/, "the focus frame marks the click");
  assert.match(RENDER, /pendingAnchorKeepY = null; pendingAnchorClick = false;\s*\n\s*\/\/ Diagnostics: log every landing attempt/, "…and the pass clears it");
  assert.match(CSS, /\.tx-landing-notice\.pulse \{ animation: tx-notice-pulse 500ms ease-out; \}/, "the pulse is one short animation");
});

test("the spacer is invisible, non-interactive vertical space", () => {
  assert.match(CSS, /\.tx-spacer \{ width: 100%; pointer-events: none; \}/);
});

test("the landing notice's pulse is one-shot (the follow-up after PR 1584, low 1): the class leaves on animationend and a re-shown notice never carries a stale one", () => {
  assert.match(RENDER, /function pulseLandingNotice\(\): void \{\s*\n\s*const n = landingNoticeEl; if \(!n \|\| n\.style\.display === "none"\) return;\s*\n\s*if \(pulseEnd\) \{ n\.removeEventListener\("animationend", pulseEnd\); pulseEnd = null; \}\s*\n\s*n\.classList\.remove\("pulse"\); void n\.offsetWidth; n\.classList\.add\("pulse"\);\s*\n\s*const end = \(\) => \{ n\.classList\.remove\("pulse"\); if \(pulseEnd === end\) pulseEnd = null; \};\s*\n\s*pulseEnd = end;\s*\n\s*n\.addEventListener\("animationend", end, \{ once: true \}\);/,
    "the pulse removes its own class on the animation's end, one listener per pulse, held in pulseEnd so a hide can remove it (the tidy after PR 1642, low 2)");
  assert.match(RENDER, /function hideLandingNotice\(\): void \{\s*\n\s*if \(landingNoticeEl\) \{\s*\n\s*if \(pulseEnd\) \{ landingNoticeEl\.removeEventListener\("animationend", pulseEnd\); pulseEnd = null; \}[^\n]*\n\s*landingNoticeEl\.classList\.remove\("pulse"\);\s*\n\s*landingNoticeEl\.style\.display = "none";/,
    "the hide path removes a cut pulse's handler and its class: no dead closure stays on the reused element");
  assert.match(RENDER, /landingNoticeEl\.classList\.remove\("pulse"\);[^\n]*\n\s*landingNoticeEl\.style\.display = "";/,
    "the show path drops a pulse the hide cut short before the element is shown again");
  assert.match(CSS, /\.tx-landing-notice\.pulse \{ animation: tx-notice-pulse 500ms ease-out; \}/, "the animation itself is unchanged: one short pulse");
});


test("the skeleton prefetch never builds a tab the strip does not show (the user 2026-09-14): tabInView and the #only= filter gate it", () => {
  assert.match(RENDER, /const next = nextPrefetch\(skeletonTabs, activeId, awaitingFull, document\.hidden \|\| paneHidden\(\), stripShowsTab\);/,
    "the idle prefetch's gate is the strip's own visibility, stripShowsTab (the views, another column's holds, the #only= filter, a collapsed section's fold)");
  assert.match(RENDER, /function stripShowsTab\(id: string\): boolean \{ return stripShows\(id\) && !collapsedTabIds\.has\(id\); \}/, "a tab folded under a collapsed section header is not shown, so not prefetched (the follow-up after PR 1661, low 3)");
  // THE REVEAL IS DETECTED WHERE THE SHOWN SET IS COMPUTED (PR 1671 round four): renderTabs compares the tabs it shows now (visibleIds
  // less the plan's folded ids) with the last paint's and re-arms the prefetch when any went hidden to shown, so every bare renderTabs()
  // is safe by construction (rounds two and three re-armed call sites one by one and missed the kernel's tabOrder frame, the media flip
  // and the renamed frame). The executed roads are strip-reveal-rearm.test.ts; here the wiring: the detector sits between the plan and
  // the signature skip, once, and the listeners and view writers repaint bare.
  const rt = RENDER.slice(RENDER.indexOf("\nfunction renderTabs() {"), RENDER.indexOf("\nfunction stripAftermath("));
  const det = rt.indexOf("const shownNow = visibleIds.filter((id) => !plan.folded.has(id));");
  assert.ok(det > 0, "renderTabs computes the shown set from visibleIds and the plan's folded ids");
  assert.match(rt, /const shownNow = visibleIds\.filter\(\(id\) => !plan\.folded\.has\(id\)\);\s*\n\s*if \(revealedTabs\(lastShownTabIds, shownNow\)\.length\) schedulePrebuild\(\);\s*\n\s*lastShownTabIds = new Set\(shownNow\);/,
    "…checks it against the last paint's (revealedTabs, tab-groups.ts) and re-arms on any reveal, then remembers it");
  assert.ok(rt.indexOf("const plan = planStrip(") < det && det < rt.indexOf("const stripSig = JSON.stringify(["), "after the plan, before the signature skip");
  assert.equal((rt.match(/schedulePrebuild\(\)/g) || []).length, 1, "one arm inside renderTabs: the detector's");
  assert.match(RENDER, /^let lastShownTabIds: Set<string> \| null = null;$/m, "null until the first paint, which arms once");
  assert.equal(RENDER.includes("renderTabsAndPrefetch"), false, "the round-three helper is gone: no caller needs to know");
  assert.match(RENDER, /^window\.addEventListener\(TABGROUPS_EVENT, \(\) => renderTabs\(\)\);$/m, "a section opened repaints bare (this window)");
  assert.match(RENDER, /^window\.addEventListener\("storage", \(e\) => \{ if \(e\.key === TABGROUPS_KEY\) renderTabs\(\); \}\);$/m, "…and from a sibling document");
  assert.match(RENDER, /^window\.addEventListener\("storage", \(e\) => \{ if \(e\.key === "romp-chat-cols"\) renderTabs\(\); \}\);$/m, "…and another column's holds");
  assert.match(RENDER, /^const onOnlyHashChange = \(\): void => renderTabs\(\);/m, "…and the #only= filter's change");
  assert.match(RENDER, /^try \{ window\.matchMedia\(PHONE_LAYOUT_MEDIA\)\.addEventListener\("change", \(\) => renderTabs\(\)\); \} catch \{/m, "…and the phone/desktop flip");
  assert.match(RENDER, /captureViews\(m\.views \|\| null\);\s*\n\s*applyTabOrder\(m\.order, m\.tabs,/, "the kernel's tabOrder frame adopts the blob, then repaints through applyTabOrder…");
  const ato = RENDER.slice(RENDER.indexOf("\nfunction applyTabOrder("), RENDER.indexOf("\nfunction syncTabKeysWithStrip("));
  assert.match(ato, /\n  renderTabs\(\);\s*\n\s*syncTabKeysWithStrip\(\);\s*\n\}/, "…whose bare renderTabs() is the reveal's repaint for a peer's view or lens change");
});
