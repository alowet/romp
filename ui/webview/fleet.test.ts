// Fleet — the by-SESSION view that mirrors the chat's ledger box (the user 2026-06-23): each session, then its
// goal TREE (collapsible checkmark nodes, recency-coloured times). It rides the FEED payload (reads `ledgers`),
// renders the same .ledger-* DOM, and copies render.ts's recency-colour helpers so the colours match exactly.
// No jsdom harness, so pin the wiring at source.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const SRC = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "fleet.ts"), "utf8");

test("fleet rides the FEED payload, reading its per-session `ledgers`", () => {
  assert.match(SRC, /m\.type !== "feed"/);                  // the proven feed channel
  assert.match(SRC, /if \(!Array\.isArray\(m\.ledgers\)\) return;/);   // only a ledgers-bearing push counts as loaded
  assert.match(SRC, /sessions = m\.ledgers as FleetSession\[\]/);
});

test("fleet.ts applies no delta itself: the shim reassembles every {type:\"delta\"} frame before the bundle sees it — and one that arrives raw is loud, never dropped", () => {
  // a host that hands the pane a kernel frame unreassembled would otherwise have every update fall through
  // the `m.type !== "feed"` return in silence; the guard says so and asks for the whole slot with the
  // message the shim itself uses (needSlot). Run for real in fleet-live-clock.test.ts.
  assert.match(SRC, /if \(m\.type === "delta"\) \{[\s\S]*?"delta-unapplied"[\s\S]*?\{ type: "needSlot", slot: m\.slot \}[\s\S]*?return;\n\s*\}\n\s*if \(m\.type !== "feed"\) return;/);
  assert.doesNotMatch(SRC, /applyDelta|from "\.\/feed-delta"/);
});

test("each session renders the real LEDGER TREE — .ledger-* nodes, marks, collapse, recency time", () => {
  assert.match(SRC, /el\("div", "ledger-tree"\)/);
  assert.match(SRC, /"ledger-tnode"/);
  assert.match(SRC, /el\("span", "ledger-tmark lz-nav"\)/);
  assert.match(SRC, /n\.done \? "✓" : n\.blocked \? "⏸" : ""/);   // the ledger box's marks
  assert.match(SRC, /el\("span", "ledger-tri"/);                   // the collapse triangle
  assert.match(SRC, /el\("span", "ledger-ttext lz-nav"\)/);
  assert.match(SRC, /el\("span", "ledger-ttime"\)/);
});

test("ledger parity (the user 2026-06-24): pointer-cursor zones + grouped hover highlight (no ⊕ summary expander)", () => {
  // .lz-nav → the pointer cursor (styles.css) on the checkbox / text / time, so each reads as clickable
  assert.match(SRC, /"ledger-tmark lz-nav"/);
  assert.match(SRC, /"ledger-ttext lz-nav"/);
  assert.match(SRC, /if \(time\.textContent\) \{ time\.classList\.add\("lz-nav"\)/);
  // grouped hover (.lz-hl toggled together) — the ledger box's linkHover, ported verbatim
  assert.match(SRC, /function linkHover\(group: HTMLElement\[\]\)/);
  assert.match(SRC, /g\.classList\.add\("lz-hl"\)/);
  assert.match(SRC, /linkHover\(\[mark, txt\]\)/);                  // open node: checkbox + text are one block
  assert.match(SRC, /linkHover\(time\.textContent \? \[mark, time\] : \[mark\]\)/);   // resolved: checkbox + time
  // the ⊕/⊖ distiller-summary expander + its panel + delegate were removed 2026-06-27 (just the goals now)
  assert.doesNotMatch(SRC, /ledger-tsum/);
  assert.doesNotMatch(SRC, /sumToggle/);
  assert.doesNotMatch(SRC, /sumOpen/);
  assert.doesNotMatch(SRC, /sum: \(el\) => \{/);
});

test("a session-level collapse caret folds the whole session's tree WITHOUT opening it (the user 2026-06-24)", () => {
  // the caret is in the .fl-head but carries its OWN data-act="sessfold" (innermost), so a click on it folds
  // while a click on the name (data-act="open") still jumps into the session.
  assert.match(SRC, /const sessFolded = new Set<string>\(\)/);
  assert.match(SRC, /caret\.dataset\.act = "sessfold"; caret\.dataset\.sid = s\.sid;/);
  assert.match(SRC, /head\.appendChild\(caret\)/);
  // folded → render the head only, skip the tree (a provisional signature row joins the tree when present)
  assert.match(SRC, /if \(!sfolded\) \{\s*\n\s*for \(const r of visibleRoots\) renderFleetNode\(ctx, r, 0, treeBox, now, false\);/);
  assert.match(SRC, /sec\.appendChild\(treeBox\);\s*\n\s*\}/);
  // the delegate toggles per-session fold, separate from the row "open" action
  assert.match(SRC, /sessfold: \(el\) => \{/);
  assert.match(SRC, /if \(sessFolded\.has\(sid\)\) sessFolded\.delete\(sid\); else sessFolded\.add\(sid\);/);
});

test("recency colour comes from the SHARED age-color module (identical to the ledger box)", () => {
  // was a verbatim copy of render.ts's ramp; extracted 2026-07-27 into ui/webview/age-color.ts when the
  // feed's age-provenance popover would have made a third copy — fleet now imports the one source
  assert.match(SRC, /import \{ ageColorReadable \} from "\.\/age-color";/);
  const AGE = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "age-color.ts"), "utf8");
  assert.match(AGE, /export function ageColorReadable\(ageSecs: number\)/);
  assert.match(AGE, /const LO = 120, HI = 345600/);               // the same recency curve
  assert.match(SRC, /function stampSubtreeRecency/);              // the same subtree recency rollup
  assert.match(SRC, /const dt = now - nodeRecency\(n\);/);        // done text/time take the rolled-up recency…
  assert.match(SRC, /time\.style\.color = ageColorReadable\(dt\)/); // …in the shared colour
});

test("completed top goals hide by default; 'Show completed' lives in the docked control bar (the user 2026-06-29)", () => {
  assert.match(SRC, /localStorage\.getItem\(DONE_KEY\) === "1"/);  // default OFF
  // the top-row selection (open-only vs +done +archived) is the pure, BEHAVIORALLY-tested ./fleet-roots
  // (fleet-roots.test.ts) — here we just pin that fleet.ts routes through it (the user 2026-06-27)
  assert.match(SRC, /import \{ fleetVisibleRoots \} from "\.\/fleet-roots"/);
  // archived COMPLETED tops now carry their subtree; only depth-0 archived nodes are roots, the rest go in byId
  assert.match(SRC, /const archRoots = archivedTops\.filter\(\(n\) => n\.depth === 0\)/);
  assert.match(SRC, /visibleRoots = fleetVisibleRoots\(roots, archRoots, sd\)/);   // non-search path gates by Show-completed
  assert.match(SRC, /const byId = new Map\(\[\.\.\.tree, \.\.\.archivedTops\]\.map/);   // archived descendants resolvable for expansion
  assert.match(SRC, /createTextNode\("Show completed"\)/);
});

test("the search bar matches session NAME or goal CONTENT, expands hits, and says 'No results' (the user 2026-06-29)", () => {
  assert.match(SRC, /let searchQuery = "";/);
  assert.match(SRC, /const sq = searchQuery\.trim\(\)\.toLowerCase\(\);/);
  // a session is kept if its NAME or any goal TEXT matches (subtreeHit over its visible nodes)
  assert.match(SRC, /const subtreeHit = \(id: string\): boolean =>/);
  assert.match(SRC, /node\.text\.toLowerCase\(\)\.includes\(sq\)/);
  // search stays WITHIN the current view (the user 2026-06-30): it gates by Show-completed + the recency cutoff
  // FIRST (`base`), THEN a name match keeps the session's in-window tops and a content match keeps just the
  // hitting ones — it does NOT reach past the toggle/slider
  assert.match(SRC, /const base = fleetVisibleRoots\(roots, archRoots, sd\)\.filter\(\(r\) => \(now - nodeRecency\(r\)\) <= cutoff\);/);
  assert.match(SRC, /visibleRoots = s\.name\.toLowerCase\(\)\.includes\(sq\) \? base : base\.filter\(\(r\) => subtreeHit\(r\.id\)\)/);
  // a collapsed branch that CONTAINS a match is force-expanded so the hit is revealed
  assert.match(SRC, /const hitChild = expandable && curSearch && !!ctx\.subtreeHit\s*\n?\s*&& \(n\.children \|\| \[\]\)\.some\(\(cid\) => ctx\.subtreeHit!\(cid\)\);/);
  assert.match(SRC, /const isFolded = expandable && !hitChild &&/);
  // the matched substring is highlighted (text-node based, never innerHTML)
  assert.match(SRC, /function highlightInto\(elm: HTMLElement, text: string, q: string\)/);
  assert.match(SRC, /highlightInto\(txt, n\.text, curSearch\)/);
  // empty search result → "No results", NOT the wordmark
  assert.match(SRC, /if \(!any && sq\) \{/);
  assert.match(SRC, /nr\.textContent = "No results for/);
  // wired to the #fleet-search input (in the kernel page body), re-rendering on each keystroke
  assert.match(SRC, /document\.getElementById\("fleet-search"\)/);
  assert.match(SRC, /search\.addEventListener\("input", \(\) => \{ searchQuery = search\.value; syncClear\(\); render\(\); \}\)/);
});

test("the search bar has a trailing ✕ clear button, shown only while there's text (the user 2026-06-29)", () => {
  // the clear button lives in the kernel fleet page next to the input; fleet.ts wires it to blank the query
  assert.match(SRC, /document\.getElementById\("fleet-search-clear"\)/);
  // shown only when there's text (hidden toggled off the input value), and clears + refocuses on click
  assert.match(SRC, /clear\.hidden = search\.value === ""/);
  assert.match(SRC, /clear\?\.addEventListener\("click", \(\) => \{ search\.value = ""; searchQuery = ""; syncClear\(\); search\.focus\(\); render\(\); \}\)/);
});

test("the controls DOCK into #fleet-foot as a bottom bar — not a floating overlay (the user 2026-06-29)", () => {
  // mountControls fills the in-flow #fleet-foot rectangle (mounted once) instead of appending a position:fixed
  // float to <body>. The old floating row + the foot-hiding line are gone.
  assert.match(SRC, /function mountControls\(\)/);
  assert.match(SRC, /const foot = document\.getElementById\("fleet-foot"\)/);
  assert.match(SRC, /foot\.dataset\.mounted = "1"/);
  assert.match(SRC, /foot\.append\(left, right\)/);
  assert.doesNotMatch(SRC, /position:fixed;bottom:8px;right:10px/);   // no longer floats
  assert.doesNotMatch(SRC, /foot\.style\.display = "none"/);          // the footer is the panel now, not hidden
});

test("'Group by session' toggles the FLAT chronological view (the user 2026-06-29)", () => {
  // default ON (grouped); OFF = one merged list newest-first, each top goal tagged with its session
  assert.match(SRC, /const GROUP_KEY = "romp:fleetGroupBySession"/);
  assert.match(SRC, /function isGrouped\(\): boolean/);
  assert.match(SRC, /createTextNode\("Group"\)/);   // short label; tooltip carries the full meaning
  assert.match(SRC, /const grouped = isGrouped\(\);/);
  // flat list: merge every survivor's visible roots, sort newest-first, render into one .fl-flat tree with the
  // session tag (flat=true)
  assert.match(SRC, /el\("div", "ledger-tree fl-flat"\)/);
  assert.match(SRC, /flatRoots\.sort\(\(a, b\) => nodeRecency\(b\.root\) - nodeRecency\(a\.root\)\)/);
  assert.match(SRC, /renderFleetNode\(ctx, root, 0, treeBox, now, true\)/);
  // the right-side session tag is added only on a flat top row
  assert.match(SRC, /if \(flat && depth === 0\) \{/);
  assert.match(SRC, /el\("span", "fl-sesslabel"\)/);
});

test("Collapse / Expand are STICKY persisted toggle MODES that render() obeys (the user 2026-06-29)", () => {
  assert.match(SRC, /const FOLD_MODE_KEY = "romp:fleetFoldMode"/);   // persisted across restarts/reopens
  assert.match(SRC, /function foldMode\(\): FoldMode/);
  assert.match(SRC, /function toggleFoldMode\(m: "collapse" \| "expand"\)/);
  assert.match(SRC, /collapse\.textContent = "Collapse"/);
  assert.match(SRC, /expand\.textContent = "Expand"/);
  assert.match(SRC, /toggleFoldMode\("collapse"\)/);
  assert.match(SRC, /toggleFoldMode\("expand"\)/);
  // render() snapshots the mode and OVERRIDES the per-node fold state with it
  assert.match(SRC, /curFoldMode = foldMode\(\);/);
  assert.match(SRC, /curFoldMode === "collapse" \? true/);
  assert.match(SRC, /curFoldMode === "expand" \? false/);
  // the active button "stays clicked" (.on), painted from the persisted mode
  assert.match(SRC, /function paintFoldButtons\(\)/);
  assert.match(SRC, /c\.classList\.toggle\("on", m === "collapse"\)/);
});

test("a manual fold LEAVES the sticky mode, baking its look first (the user 2026-06-29)", () => {
  // bakeFoldMode writes the mode's current look into the sets then clears the mode, so only the hand-toggled
  // node differs; both the node-fold and session-fold handlers call it before applying the manual toggle
  assert.match(SRC, /function bakeFoldMode\(\)/);
  assert.match(SRC, /if \(n\.children && n\.children\.length\) \{ folded\.add\(fkey\(s\.sid, n\.id\)\); expanded\.delete\(fkey\(s\.sid, n\.id\)\); \}/);
  assert.match(SRC, /bakeFoldMode\(\);[^\n]*hand-fold leaves the sticky/);
});

test("a super-category AUTO-COLLAPSES the instant it finishes, overriding a manual expand (the user 2026-06-29)", () => {
  // event-based on the not-done → done TRANSITION (tracked in seenDone), so it fires once: clear the manual
  // expand so defaultFold folds the finished top, even if it was expanded mid-progress; re-arm when it reopens.
  assert.match(SRC, /const seenDone = new Set<string>\(\);/);
  assert.match(SRC, /for \(const r of s\.ledger\?\.tree \|\| \[\]\) \{/);
  assert.match(SRC, /if \(r\.depth !== 0\) continue;/);
  assert.match(SRC, /if \(r\.done\) \{ if \(!seenDone\.has\(k\)\) \{ expanded\.delete\(k\); seenDone\.add\(k\); \} \}/);
  assert.match(SRC, /else seenDone\.delete\(k\);/);                       // reopened → re-arm the transition
  // it runs over EVERY top goal, before the survivors filter, so it sticks even when "Show completed" is off
  assert.match(SRC, /for \(const s of sessions\) \{\s*\n\s*for \(const r of s\.ledger\?\.tree/);
});

test("the mark's WHY rule (markReason) survives — as the hover card's state line, not a native tooltip", () => {
  // the checkbox explanation the user asked for 2026-06-24 — explicit / inferred (roll-up vs roll-down) /
  // dismissed / blocked / open — now LEADS the hover card (2026-07-13), which also carries the full goal
  // text; the native mark/txt titles were dropped so they can't pop redundantly on top of the card.
  assert.match(SRC, /function markReason\(n: LedgerNode, byId: Map<string, LedgerNode>\): string \{/);
  assert.match(SRC, /"done — inferred: every sub-step is complete"/);
  assert.match(SRC, /"done — inferred: a parent goal was checked off"/);
  // cleared wording moved to the honest-flag model 2026-07-26 (the box means done) — pinned in cleared-tag.test.ts
  assert.match(SRC, /"completed, then cleared off the board"/);
  assert.doesNotMatch(SRC, /mark\.title = /);
  assert.doesNotMatch(SRC, /txt\.title = /);
});

test("hovering a row shows the modal's story: state, background, takeaway/brief, sub-goals (the user 2026-07-13)", () => {
  // one persistent panel on document.body — render() wipes #fleet-list every push, so the card must live
  // outside the wipe; wiring is delegated to the stable list, INSTANT show (the one tooltip
  // treatment, 2026-08-28 — the 120ms intent debounce is gone), keyed per (sid, nid)
  assert.match(SRC, /row\.dataset\.nid = n\.id;/);
  assert.match(SRC, /document\.body\.appendChild\(card\);/);
  assert.match(SRC, /showHoverCard\(row, sid, nid\);/);
  assert.doesNotMatch(SRC, /hoverShowT/, "no show-intent timer — the hover card is instant-in");
  // the hide grace is the SHARED tip constant, so the fleet card and every styled tip agree
  assert.match(SRC, /window\.setTimeout\(hideHoverCard, TIP_GRACE_MS\);/);
  // the modal's sections, from data the pane already holds (ledger node + the matching feed card)
  assert.match(SRC, /state\.textContent = markReason\(n, byId\)/);
  assert.match(SRC, /if \(ask\?\.background && ask\.background\.trim\(\)\) section\("Background", ask\.background\);/);
  assert.match(SRC, /if \(summary\) section\("Key takeaway", summary\);/);
  assert.match(SRC, /else if \(brief\) section\("Decision brief", brief\);/);
  assert.match(SRC, /lab\.textContent = "Sub-goals";/);
  // background rides only on feed cards → the asks slice is kept as a by-id lookup
  assert.match(SRC, /asksById = new Map\(\(Array\.isArray\(m\.asks\) \? m\.asks : \[\]\)/);
  // click (navigates) and scroll (moves the anchor) drop the card at once; a row-to-card transit doesn't
  assert.match(SRC, /list\.addEventListener\("click", hideHoverCard\);/);
  assert.match(SRC, /list\.addEventListener\("scroll", hideHoverCard, true\);/);
  assert.match(SRC, /card\.addEventListener\("mouseleave", scheduleHideHover\);/);
  const CSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "fleet-pane.css"), "utf8");
  assert.match(CSS, /\.fl-hover\{position:fixed;z-index:60/);
  assert.match(CSS, /\.fl-hover-sub \.m\.open\{/);
});

test("a node/header click opens that session AND flips back to chat (the user 2026-06-24)", () => {
  // openSession() posts openSession to the kernel AND asks the shell to leave the Fleet view (the tab bar —
  // which holds the Fleet toggle — is hidden while Fleet is shown, so picking a session must return there).
  assert.match(SRC, /function openSession\(sid: string\) \{ vscodeApi\?\.postMessage\(\{ type: "openSession", id: sid \}\); backToChat\(\); \}/);
  // click-safe (the user 2026-06-24): the open action is DELEGATED to the stable #fleet-list (render() rebuilds
  // its children every push, so a per-node onclick gets dropped mid-click) — see click-safe.test.ts. The
  // header + each row declare data-act="open" + data-sid; the delegate routes them to openSession.
  assert.match(SRC, /open: \(el\) => \{ const sid = el\.dataset\.sid; if \(sid\) openSession\(sid\); \}/);
  assert.match(SRC, /head\.dataset\.act = "open"; head\.dataset\.sid = s\.sid;/);
  assert.match(SRC, /row\.dataset\.act = "open"; row\.dataset\.sid = s\.sid;/);
  // leaving Fleet is now the shell strip's "Chat" toggle; openSession still returns via {romp:"toggleFleet", to:"chat"}
  assert.match(SRC, /window\.parent\.postMessage\(\{ romp: "toggleFleet", to: "chat" \}/);
});

test("fleet nodes DEEP-LINK to the same place the feed modal does (the user 2026-06-27)", () => {
  // the node carries the kernel's per-node anchor uuids (already sent in build_session's tree)
  assert.match(SRC, /promptAnchorUuid\?: string \| null; anchorUuid\?: string \| null;/);
  // zones declare data-act mirroring the modal: TEXT → the asking message; a RESOLVED mark/time → the work
  assert.match(SRC, /txt\.dataset\.act = "goprompt"/);
  assert.match(SRC, /mark\.dataset\.act = resolved \? "gowork" : "goprompt"/);
  assert.match(SRC, /time\.dataset\.act = "gowork"/);
  // delegated (click-safe) through fleetNavTo, which posts the SAME showOnTimeline message shape as feed.ts
  assert.match(SRC, /goprompt: \(el\) => fleetNavTo\(el, "prompt"\)/);
  assert.match(SRC, /gowork: \(el\) => fleetNavTo\(el, "work"\)/);
  assert.match(SRC, /vscodeApi\?\.postMessage\(\{ type: "showOnTimeline", itemId: nid, sid, t, anchor: kind, anchorUuid \}\)/);
  // work jump uses the resolved node's mt (where it resolved), prompt jump uses its start t — like wireNodeZones
  assert.match(SRC, /const t = kind === "work" \? \(\(resolved && n\.mt\) \? n\.mt : n\.t\) : n\.t;/);
});

test("it's a MODULE (own scope) so it doesn't collide with feed.ts's globals", () => {
  assert.match(SRC, /export \{\};/);
});

test("the loader holds until the LEDGERS actually land — not just any feed message (the user 2026-06-29)", () => {
  // `loaded` flips true only when m.ledgers is an array (the kernel built the fleet data, maybe empty) — a
  // bare feed push that beat the cold ledger build is ignored, so the loader keeps holding instead of dropping
  // onto a blank pane. render() bails before the empty path while !loaded, leaving #fleet-list empty.
  assert.match(SRC, /let loaded = false;/);
  assert.match(SRC, /if \(!Array\.isArray\(m\.ledgers\)\) return;\s*\n\s*loaded = true;/);
  assert.match(SRC, /if \(!loaded\) \{ emptyShown = false; return; \}/);
});

test("the romp loader is kept up (beating the _pane_spin 8s backstop) until data lands", () => {
  // a big cold fleet build can exceed the shared loader's 8s backstop; re-assert the loader until `loaded`,
  // then stop — so there's never a blank gap between the loader hiding and the tasks painting.
  assert.match(SRC, /const _keepLoader = setInterval\(\(\) => \{/);
  assert.match(SRC, /if \(loaded\) \{ clearInterval\(_keepLoader\); return; \}/);
  assert.match(SRC, /spin\.classList\.remove\("gone"\)/);
});

test("provisional (about-to-appear) work gets a dotted swirl signature in the fleet (the user 2026-06-29)", () => {
  const CSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "styles.css"), "utf8");
  // read from feed.asks (the SAME payload), keep only provisional cards
  assert.match(SRC, /\.filter\(\(a: any\) => a && a\.provisional && a\.sid\)/);
  // a dotted signature row: swirl + gist, click-opens the session
  assert.match(SRC, /const makeProvRow = \(p: ProvCard, flat: boolean\) =>/);
  assert.match(SRC, /el\("div", "ledger-tnode ledger-top fl-prov"\)/);
  assert.match(SRC, /row\.appendChild\(el\("span", "fl-prov-swirl"\)\)/);
  // a session that's ONLY provisional (skipped above for an empty tree) still gets a minimal section
  assert.match(SRC, /for \(const \[, p\] of Array\.from\(provBySid\)/);
  // and the flat view shows them too
  assert.match(SRC, /if \(flatRoots\.length \|\| provBySid\.size\)/);
  assert.match(CSS, /\.fl-prov-swirl \{[\s\S]*?url\(\.\.\/media\/romp-swirl-glyph\.svg\)/);
  assert.match(CSS, /@keyframes fl-prov-spin \{ to \{ transform: rotate\(-360deg\); \} \}/);
});

test("genuinely-empty fleet fades in the romp WORDMARK (like the feed), once per empty transition", () => {
  const CSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "styles.css"), "utf8");
  // the empty branch mints .fl-wordmark (not the old text), with .no-anim when it was ALREADY empty (no replay)
  assert.match(SRC, /el\("div", "fl-wordmark" \+ \(emptyShown \? " no-anim" : ""\)\)/);
  assert.match(SRC, /emptyShown = true;/);
  assert.match(SRC, /\} else \{\s*\n\s*emptyShown = false;\s*\n\s*\}/);   // reset when work reappears
  // the wordmark + its one-time fade live in styles.css (the fleet page loads /dist/styles.css)
  assert.match(CSS, /\.fl-wordmark \{[\s\S]*?url\(\.\.\/media\/romp-wordmark\.png\)/);
  assert.match(CSS, /animation: fl-wordmark-in 1s ease both;/);
  assert.match(CSS, /\.fl-wordmark\.no-anim \{ animation: none; \}/);
  assert.match(CSS, /@keyframes fl-wordmark-in \{ from \{ opacity: 0; \} to \{ opacity: 0\.75; \} \}/);
});

test("an ARCHIVED node's zones deep-link too: fleetNode searches archivedTops, not just the live tree (the user 2026-07-11)", () => {
  // the miss made an archived row's text a dead click: fleetNode returned null → bare openSession, no jump
  assert.match(SRC, /\(s\?\.ledger\?\.tree \|\| \[\]\)\.find\(\(n\) => n\.id === nid\)\s*\n?\s*\|\| \(s\?\.ledger\?\.archivedTops \|\| \[\]\)\.find\(\(n\) => n\.id === nid\) \|\| null/);
  // the kernel's archived projection now carries the anchors this nav reads (null → time fallback);
  // a junk mint quote ('retry') ships no prompt anchor (jd.junk_quote, the user 2026-07-20)
  const KERNEL = fs.readFileSync(path.resolve(process.cwd(), "..", "bin", "romp-kernel"), "utf8");
  assert.match(KERNEL, /"promptAnchorUuid": None if jd\.junk_quote\(nd\.get\("quote"\)\) else nd\.get\("promptUuid"\),/);
  assert.match(KERNEL, /"anchorUuid": nd\.get\("summaryAnchor"\),/);
});

// ── the pending-host strip (the user 2026-09-02) ─────────────────────────────────────────────────
// After a kernel restart or a phone re-foreground, an attached host's sessions were simply ABSENT from
// this pane for up to two minutes — no row, no cue — and read as wiped state. The feed merge names such
// hosts (pendingHosts / pendingDead, riding the same feed message the ledgers do); this pane wears the
// feed's own strip for them, and it leaves only on the merge's events. Source pins (no jsdom here).
test("the fleet reads pendingHosts/pendingDead off the feed payload — the merge is the ONLY writer", () => {
  assert.match(SRC, /pendingHosts = Array\.isArray\(m\.pendingHosts\) \? m\.pendingHosts\.filter\(\(h: any\) => typeof h === "string"\) : \[\];/);
  assert.match(SRC, /pendingDead = Array\.isArray\(m\.pendingDead\) \? m\.pendingDead\.filter\(\(h: any\) => typeof h === "string"\) : \[\];/);
  assert.doesNotMatch(SRC, /setTimeout\([^)]*pendingHosts/, "no timer ever edits the pending set");
});

test("one quiet line per pending host LEADS the list, the feed's copy family, swirl left of the text", () => {
  assert.match(SRC, /if \(pendingHosts\.length\) list\.appendChild\(hostLoadStrip\(\)\);   \/\/ leads the list: what is still coming/);
  assert.match(SRC, /strip\.id = "fleet-hostload";/);
  assert.match(SRC, /const line = el\("div", "hostload-line"\);/);
  assert.match(SRC, /const swirl = el\("span", "fask-awaiting-swirl"\);/);
  assert.match(SRC, /"reconnecting to " \+ h \+ "\\u2026"/, "a dead link names itself (fail loudly)");
  assert.match(SRC, /"loading sessions from " \+ h \+ "\\u2026"/, "an open link still waiting on its first payload");
  assert.match(SRC, /line\.append\(swirl, txt\);/);
  // the inbox-zero wordmark must not claim "every session is clear" while a host is still coming
  assert.match(SRC, /\} else if \(!any && !pendingHosts\.length\) \{/);
});

test("the strip's styles live in the fleet's own sheet, mirroring feed.css — this page never loads feed.css", () => {
  const CSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "fleet-pane.css"), "utf8");
  const FEEDCSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "feed.css"), "utf8");
  assert.match(CSS, /#fleet-hostload\{display:flex;flex-direction:column;gap:4px;padding:8px 14px\}/);
  assert.match(CSS, /\.hostload-line\{display:flex;align-items:center;gap:7px;color:var\(--dim,#9a9a9a\);font-size:0\.82em\}/,
    "same geometry + scale as feed.css's .hostload-line");
  assert.match(CSS, /\.fask-awaiting-swirl\{width:14px;height:14px;flex:0 0 auto;background:url\(\.\.\/media\/romp-swirl-glyph\.svg\) center \/ contain no-repeat;\s*animation:fask-swirl-spin 2\.4s linear infinite\}/);
  assert.match(CSS, /@keyframes fask-swirl-spin\{to\{transform:rotate\(-360deg\)\}\}/, "reverse spin, like every romp loader");
  assert.match(FEEDCSS, /\.hostload-line \{ display: flex; align-items: center; gap: 7px; color: var\(--dim\); font-size: 0\.82em; \}/,
    "the feed's rule this mirrors is still the reference");
});

test("the outline's lens write carries a writeId and `edited: []`, so the kernel applies the lens only (the 2026-09-05 review)", () => {
  // before this change this was the one views write posted without either: the kernel judged its tag set as a
  // whole blob, and a targeted edit that landed in the same second as the pane's frame copy was reverted
  // by the next lens change. The empty list is the kernel's word that the write changes no tag.
  assert.match(SRC, /import \{ mintWriteId \} from "\.\/views-writes";/);
  assert.match(SRC, /function postOutlineLens\(v: SessionViews\) \{\s*\n\s*vscodeApi\?\.postMessage\(\{ type: "setTimelineViews", views: v, writeId: mintWriteId\(\+\+outlineViewsWriteSeq\), edited: \[\] \}\);/);
  // both lens paths (the tag menu's apply, the chips' remove) post through it, from the frame copy the pane
  // holds with only the outline lens changed
  const sites = SRC.match(/const v = JSON\.parse\(JSON\.stringify\(fleetViews \|\| \{ active: "all", tags: \[\] \}\)\);\s*\n\s*v\.actives = Object\.assign\(\{\}, v\.actives, \{ outline: l \}\);\s*\n\s*fleetViews = v;[^\n]*\n\s*postOutlineLens\(v\);/g) || [];
  assert.equal(sites.length, 2, "the two lens gestures post the same shape");
  assert.equal((SRC.match(/type: "setTimelineViews"/g) || []).length, 1, "one post site: no views write leaves this pane without the two fields");
  assert.doesNotMatch(SRC, /type: "setTimelineViews", views: v \}/);
});
