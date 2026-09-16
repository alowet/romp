# Split a chat pane top and bottom (drag a tab to the bottom edge)

A design line for a feature on the user's list (open since 2026-09-12): drag a tab to the BOTTOM edge of a
chat pane to split it into a top and a bottom pane, the vertical counterpart of today's side-by-side column
split (drag a tab to the right edge to open a column). The user gave the GO on 2026-09-15, to follow the
scroll-back fixes. This doc decides the layout model, the drop target, the divider, focus and the strip in a
stacked pane, the kernel's part (nothing new to serve), the served lab, and the risks. It is a `feature`. No
code here.

Line references re-checked at main 7891c4c0 by grepping each cited symbol. An earlier revision of this doc
carried kernel.py numbers that were roughly 430 to 660 lines LOW (approximate offsets, not grepped) and a few
wrong render.ts numbers; those are corrected throughout. Cite by symbol name first, the line as a current pin.

## 1. The premise, in code: the side split today

Dragging a tab to a pane's right edge opens a new chat column. The gesture spans two documents that talk by
`postMessage`: the chat PAGE owns the tab and the native drag, the SHELL mounts the drop zones and performs
the mutation. The shell half lives in one embedded string, `_LANDING_SPLIT_JS` (`kernel.py:58876`).

- **The tab is a native HTML5 draggable** (no pixel-slop threshold, the browser owns click-vs-drag). Marked at
  build: `render.ts:6767` `tab.draggable = !s.sub && !fedMissing && !isProvisionalId(id) && !settings.tabsLocked`.
  `dragstart` wires through `wireTabDrag` (`render.ts:6347`), which calls `postTabDrag` (`render.ts:6335`); the
  on:true post is `{ romp: "tabDrag", on, sid, name, stripH }` to `window.parent`. The strip's own `#tabs` drop
  path only REORDERS within a strip (`reorderTo`, `render.ts:5913`); it never opens a column.
- **The shell mounts the drop zones** on that message (the `tabDrag` handler, `kernel.py:59049`). `mountZones`
  (`kernel.py:59043`) lays a COLUMN zone over every chat pane but the source (drop moves the session there)
  plus, on the rightmost pane, an EDGE zone (drop opens a new column). The edge band is
  `edgeWidth(w)=max(72,min(180,0.2*w))` of the pane WIDTH (`kernel.py:59029`); the drop preview `ghostRect` is
  the RIGHT HALF of the rightmost pane, full row height (`kernel.py:59030`). The affordance: a column zone
  toggles `.over` on itself (`cue`, `kernel.py:59035`); the edge zone shows `#col-ghost`, a fixed rectangle at
  the right half labelled with the dragged session's name, or "Four columns at most" in the `.refused` state at
  the cap (`showGhost`, `kernel.py:59031`).
- **The mutation is one function**, `moveTab(sid, to)` (`kernel.py:58963`, exposed `window.__rompMoveTab`,
  `:59002`). `to` is a column number or `"new"`. The `"new"` path: `canSplit()` (`:58952`, cap `MAX=4` counting
  the first column, `CK`/`MAX` at `:58878`), `__rompSplitGrow` halves the rightmost column's width, `unlist`
  the sid (`:58956`), push `{n, ids:[sid]}`, `save()` (`:58883`), then `make(n, sid, state)` (`:58935`), and
  the new iframe's `contentWindow.focus()` (`:58972`).
- **`make()` builds a column** (`kernel.py:58935`): a `.gv` gutter and a `<div class="pane chat-col"
  data-col=N style="flex:var(--g-chatN,60) 1 0">` wrapping `<iframe src="/chat?col=N&skeleton=1">`, inserted
  before `gv-a` in the `.row`, then `__rompRegisterPane`, `__rompGrowFairIfNew`, the col-resize gutter
  (`__rompGutter`), `__rompWireFocus`, `__rompWireEsc`. It SEEDS the dragged session as the column's persisted
  `activeId` first (`seed`, `:58911`), so the shim dials `?active=<sid>` and the page restores that tab through
  the arrival path (`restoreIfShown`, `render.ts:13058`, called from the reconnect path at `render.ts:5784`).
  So a drag-created pane reveals its seeded tab at once; `silentActivate` (section 6) is the FALLBACK for when
  that tab is unlisted or held elsewhere, or when focus later leaves the pane.
- **The dial terms** (the served `/chat` shim): `/ws?...&col=<N>&skeleton=1`. `col=N` sets the page's
  per-column state key and is LOG-ONLY on the kernel (parsed "for the logs", `kernel.py:64549`; printed only in
  the drop-client log row, `:46169`), never branching what is served. `skeleton=1` is the term that changes
  served content (`:64547`, gated to `app=="chat"`): the strip with a skeleton list, one full frame for the
  `active` tab, a light status per other tab (the diet, `_resolve_reconnect` `:46502`, `_skeleton_for`
  `:46482`).
- **View state is browser localStorage, per browser, no kernel store.** Three keys: `romp-chat-cols`
  (`{v:2, cols:[{n, ids}]}` in row order; key + `MAX` at `kernel.py:58878`, `save()` `:58883`, `read()`
  `:59077`, restored at boot `:59092`); `romp-vscode-state-chat:N` (a column's own active tab, drafts, scroll;
  `BK` `kernel.py:58879`); `romp-pane-grow` (pane widths as flex-grow numbers). The kernel's
  `timeline-views.json` stores tag filters, NOT layout.
- **The layout axis is a single horizontal flex row**: `.row{display:flex}` (`kernel.py:60405`, the base HTML),
  each pane `flex:var(--g-chatN,60) 1 0`, 7px `.gv` gutters between (styling in the shell CSS). Desktop only
  (`mobile()` disables the split and `__rompChatSets` returns null).

**The prior art that matters most:** the shell's outer `.col` (`kernel.py:60404`) is ALREADY a vertical
flexbox: it stacks the pane `.row` (`:60405`) over a `row-resize` gutter `#gh` (`:60423`) over a timeline band
`#tl-pane` (`:60424`). So a horizontal divider between a top and a bottom region is not new machinery; what is
new is applying it to split ONE chat pane into two chat panes, NESTED inside a single column.

## 2. The layout model

**Decision: one level. A flat list of columns (horizontal), each column OPTIONALLY split into a top and a
bottom chat pane. Not a full nested grid.** A bottom split does NOT hold a column split inside it; the grid is
at most two rows deep and only within a single column. Rationale: the persisted shape is already a flat `cols`
list in row order, and, in code, a bottom pane is a column with a different placement, so the minimal extension
is a per-pane placement rather than an arbitrary rows-and-columns tree.

**Persistence: a bottom pane is an ordinary `cols` entry carrying a placement, under the existing v:2.** Extend
each entry to `{n, ids, place?, parent?, ratio?}`: a side column leaves `place` absent (or `'side'`); a bottom
pane is `place:'below'` with `parent` the number of the column it sits under (1 for the first column) and
`ratio` the top/bottom height split. Because a bottom pane is a `cols` entry with its OWN number `n`, it dials
`/chat?col=n&skeleton=1`, gets its own `romp-vscode-state-chat:n` blob, and the partition readers stay
UNCHANGED: `ownerOf` (`kernel.py:58896`), `sets()` (`:58897`) and `nextNumber()` (`:58898`) all iterate `cols`
without caring about placement. Any pane is splittable, INCLUDING the first column, which has no `cols` entry of
its own (it is the implicit column 1 that derives "the rest"): its bottom pane is a `cols` entry with
`parent:1`. Keeping the version at 2 is deliberate for the multi-tab transition window: an old bundle's
`add(c.n, c.ids)` in `read()` (`kernel.py:59077`) reads `{n, ids}` and IGNORES `place`/`parent`/`ratio`, so it
renders a bottom pane as a side column, mis-placed but never dropped, rather than the whole-store drop a v:3
bump would cause when an old tab fails the `raw.v===2` check (`:59082`).

**The partition and the cap are nearly free; the DOM and the routing are the work.** Because a bottom pane is a
`cols` entry, `canSplit()` (`kernel.py:58952`, `cols.length+1<MAX`) counts it against `MAX=4` automatically,
and `nextNumber()` already avoids every `cols[].n`. The page-side pure partition in `chat-columns.ts`
(`colFromSearch` `:16`, `ownerOf` `:26`, `columnHolds` `:37`, `ColSets` `:11`; the page filters by its own
`?col=N` via `COL` `render.ts:1028`, `readColSets` `:1040`, `heldHere` `:1047`, `tabInView` `:1048`) admits a
numbered bottom pane with NO change, and each pane boots its own `FederationManager` (one relay per host)
exactly as a side column does. What is genuinely new is placement-aware shell code:
- `make()` (`kernel.py:58935`) must NEST a `place:'below'` pane inside its parent column's pane div as a
  vertical flex child with a `row-resize` gutter, instead of inserting a side column into the `.row`. This is a
  new branch of `make()` (or a sibling builder); the side-column path is unchanged.
- `close()` (`kernel.py:58985`) must un-nest a bottom pane: its ids return to its parent column's top pane, the
  bottom iframe and the vertical gutter go, and the parent pane returns to a single iframe.
- `frames()` (`:58887`), `frameOfWin` (`:58888`), `colOf` (`:58889`) and `frameOfCol` (`:58890`) already resolve
  any numbered frame, so a bottom pane's `f-chat-<n>` is routed for ownership and messages with no change. But
  the FOCUS nav (`allCols` `:55686`, `visCols` `:55705`, `moveFocus` `:55714`) treats `__rompChatFrameIds()` as
  a HORIZONTAL list, so it must be taught to exclude a bottom pane from the left/right column walk and reach it
  on the vertical axis instead (section 4). Give the shell a columns-only accessor (top row: the first column
  and every `place!=='below'` entry) distinct from the all-frames one used for routing.

**The divider.** A per-column horizontal (`row-resize`) gutter between the top and bottom panes, ratio-traded
and PERSISTED in the entry's `ratio`. This is a NEW gutter, not a reuse: `gutter()` (`kernel.py:55644`,
`window.__rompGutter` `:55660`) is WIDTH-based (it reads `offsetWidth`/`clientX` and writes the shared
`romp-pane-grow` flex-grow store for the fixed `PANES` list). The two sub-panes of a split column are not in
that list and trade HEIGHT, so the vertical divider is a height-based sibling: the `.gv` pattern (a ghost line
on `mousemove`, both sizes written ONCE on `mouseup`, `body.drag iframe{pointer-events:none}` to hold the
mouse, a min clamp) applied to the `row-resize` axis the `#gh` band gutter (`kernel.py:60423`) already uses, but
writing the entry's `ratio` rather than the pane-grow store. Its min clamp must leave EACH sub-pane a one-row
tab strip plus the composer floor (`COMPOSER_MIN_H=38` `render.ts:18922`; the composer self-caps at 60% of the
iframe via `composerMaxH` `:18923`).

## 3. The drop target, focus on creation, and keyboard

**A bottom-edge zone on every non-source pane, mirroring the right-edge zone.** In `mountZones`
(`kernel.py:59043`), beside the column and edge zones, mount a bottom-edge zone whose HEIGHT axis mirrors the
width edge: `edgeWidth` applied to the pane HEIGHT (a band `max(72,min(180,0.2*h))` at the pane's bottom), a
`ghostRect` that is the pane's BOTTOM HALF rather than the right half, and a drop that calls
`moveTab(sid, "down")`, a new `to` value that splits that pane's column vertically. The affordance mirrors the
edge ghost (`#col-ghost` or a sibling over the bottom half, labelled with the session name, `.refused` at the
pane cap). Desktop-only. Unlike the right-edge zone (rightmost pane only), the bottom-edge zone belongs on every
column, since any column can be split; it is suppressed on a pane that already holds a bottom split (at most two
rows deep) and on a lone-session later column (a split would twin it).

**`moveTab(sid, "down")` seeds and focuses, like the "new" path.** It resolves the source's column (`from =
ownerOf(sid)`, 1 for the first column), refuses if that column is already split, allocates `nextNumber()`,
`unlist`s the sid, pushes `{n, ids:[sid], place:'below', parent:from, ratio:0.5}`, `save()`s, `make()`s the
nested bottom pane (which seeds the sid into its blob so its shim dials `?active=<sid>`), and focuses the new
bottom iframe (mirroring the `"new"` path's `contentWindow.focus()`, `kernel.py:58972`). Without the seed and
the focus the bottom pane starts no-active behind the diet and depends on the `silentActivate` fallback from its
first frame (section 6).

**Keyboard parity.** Add `chat.splitDown` (the analog of `chat.split`, `Mod+\`, `commands.ts:32`, registered
`palette-main.ts:186`) that calls `moveTab(activeId, "down")`, plus move-up/down-a-pane analogs of
`chat.moveToNextColumn` (`palette-main.ts:208`).

**The vertical focus-nav graph is real new code, not a free slot.** `moveFocus(dir)` (`kernel.py:55714`,
Alt/Option+Arrow) is column-indexed only: Down from a column enters the timeline band, Up from a column no-ops.
It has NO notion of two panes stacked in one column. Extend the vertical axis so that, in a split column,
Alt-Down from the TOP pane moves to the BOTTOM pane (not straight to the timeline), Alt-Up from the BOTTOM pane
returns to the top, and Alt-Down from the BOTTOM pane then enters the timeline. `setFocus` (`kernel.py:55687`)
already tracks a numbered chat frame and rings exactly one pane, so ownership and the ring need no change; only
the up/down GRAPH does.
**Open question to resolve in the feature:** when the timeline's Alt-Up returns to a split column, which pane
does it land on? `lastCol` (`kernel.py:55681`) tracks a column, not a within-column pane. Track the last-focused
pane per split column (extend `lastChat`, `:55684`) and return there.

## 4. Focus arbitration and the strip in a stacked pane

**Focus arbitration is unchanged; exactly one column owns each session.** The shell's
`target(sid)=frameOfCol(ownerOf(sid))` (`kernel.py:58905`, exposed as `window.__rompChatTarget` `:59010`) is the
authority; each page's `focusIsOurs(sid)` (`render.ts:8284`) asks it and acts only if the owning frame is
itself, else `forwardToOwner` (`render.ts:8299`) hands the message to the owner. The shell's own focus RING is
event-based: `setFocus` (`kernel.py:55687`) on child pointerdown, focusin or window-focus, exactly one
`.pane-focused`. A bottom pane is an ordinary numbered column, so `ownerOf`/`target`/`focusIsOurs` resolve it
with no new arbitration; the only focus code that must grow is the horizontal-versus-vertical nav graph
(section 3).

**The strip does not collapse to icons; it wraps then scrolls.** `#tabs` wraps onto rows (`flex-wrap:wrap`,
`styles.css:402`) and `#tabbar` SCROLLS once the rows exceed `max-height:var(--tabbar-cap,150px)` with
`overflow-y:auto` (`styles.css:389`); the user's only height control is the `#tabbar-resize` grip
(`styles.css:425`, wired `render.ts:13995`). In a short bottom pane the strip wraps then scrolls inside its cap.
(This is orthogonal to `collapsedTabIds` `render.ts:1055`, the user's per-tag-section fold.)

**A folded active tab is a designed state, inherited unchanged.** When the active tab's tag section is folded,
its section header stands in (`makeGroupHead` `render.ts:6114`; `standIn`/`snapView` around `:6172`):
`focusActiveTab` lands on the header (`render.ts:7858`), and `showActive` renders the section SNAPSHOT
(`renderSnapshot` `render.ts:12930`) rather than a transcript. `silentActivate` deliberately leaves any fold
alone (no `unfoldSectionOf` `render.ts:7871`, the #1754 decision), so a bottom pane that silently adopts a
folded tab shows that header-plus-snapshot, consistent with a side column.

**What the design must specify for a stacked pane:**
1. The divider min clamp reserves, for EACH sub-pane, at least one strip row plus the composer floor
   (`COMPOSER_MIN_H=38` `render.ts:18922`; `composerMaxH` caps at 60% `:18923`), so a short bottom pane never
   hides its whole strip or composer.
2. There is NO auto-scroll-active in `#tabbar`, so a short scrolling strip can leave the active tab (or its
   folded stand-in header) off-screen. The feature should add scroll-active-into-view on activation for a short
   pane; if it does not, the doc must say the active affordance can be off-screen and that is accepted.
3. A freshly-split bottom pane inherits the silent no-unfold behaviour: if its adopted tab is under a folded
   section it shows the section snapshot, not the transcript, until the user opens the section. That is the
   intended first view (unfolding on a fresh split departs from `silentActivate`'s silence and is not
   recommended).

## 5. The kernel side: nothing new to serve

A bottom pane is a chat column with a different PLACEMENT, so it dials exactly as a column does:
`/chat?col=N&skeleton=1` with its own `iid`. To the kernel it is byte-for-byte a side-column client: `col=N`
stays page-and-log only (`kernel.py:64549`, `:46169`); `skeleton=1` drives the same diet (`_resolve_reconnect`
`:46502`, which reads `active`/`kind`/`_skeleton_for` and never reads `col`). The placement is pure shell CSS
and localStorage; the kernel never learns it. The only kernel-visible change is one more `col=N` client per
split.

**One #1754 behaviour each pane inherits (not new kernel state, worth naming):** every `/chat` page
re-announces its own shown tab to the relay on `romp:hostRelayUp` / `romp:wsup` (`shownTabForRelay`
`render.ts:12670` + `announceActiveToRelay` `:12663`, wired in the listeners at `render.ts:16159` and `:16149`),
and `silentActivate` (`render.ts:12684`) gives a shown-but-no-active pane an active without a focus hop. A
bottom pane is another `col=N` page that runs this path independently: one more `activeTab` op on its own
socket. This changes no kernel contract.

## 6. The served lab: a long session in EVERY pane (the wall lesson)

**The central correctness link: the vertical split inherits the side split's total dependence on #1754.** A
chat column is a shell column (`colSets !== null`), and a shell column does NOT adopt the first arriving frame:
it must activate a tab to reveal a transcript body. So EVERY pane that is not the currently focused column
relies on the #1754 recovery to fill: the restore (`restoreIfShown`, `render.ts:13058`, from the reconnect path
at `:5784`) when the persisted active still names a held-and-shown tab, and `staleActiveFallback` to
`silentActivate` (`render.ts:8375` to `:12684`) when it does not. The bottom pane is the focused column at the
split instant (section 3 seeds and focuses it), but it becomes non-focused the moment focus moves: a click on
the top pane, an Alt-arrow, or ANY shell reload (which restores the ring to one pane). The SOURCE (top) pane is
non-focused the instant the drop lands if it still holds sessions, the exact pane that historically read "no
session shown" (`render.ts:6612`, the 2026-09-12 report). From that point each non-focused pane fills ENTIRELY
through the #1754 path; without `silentActivate` it would sit on the scroll-back wall.

**Two faces, do not conflate them:**
- A LOCAL session in a bottom pane: the kernel's no-active diet does NOT apply (it is scoped to `kind=='relay'`,
  `kernel.py:46474` and `:46557`); a no-active local dial gets the fail-safe WHOLE push. So the local wall is
  purely PAGE-side (no body revealed because `colSets !== null`), and `silentActivate`'s `showActive` is the
  fix.
- A REMOTE (federated) session in a bottom pane: the pane rides a relay socket, the no-active diet DOES skeleton
  its shown tab, and `silentActivate`'s `showActive` to `notifyActive`, plus the `romp:hostRelayUp`/`romp:wsup`
  re-announce, carries the shown tab past the diet.
Both faces are #1754; the lab exercises both. See `plans/federated-pane-dial-terms.md` section 7 (the deferred
widening of the diet to LOCAL pages): if that lands, the two faces become identical, so the lab must assert
fill-to-turn-0 regardless of whether the kernel dieted or pushed whole.

**The lab, grounded in the existing harness:**
- **Boot** from `tests/test_chat_split_served.py` `setUpClass` (single kernel, real pointer drag, reload
  restore): build the dist, seed XDG state, write `session-hosts` `off`, `Popen bin/romp-kernel`, poll
  `/healthz`. Seed at least two sessions in the SAME column, each a LONG session with a head gap: the local
  cut-floor seed precedent is `tests/test_local_split_cutfloor_served.py`. For the remote face, add the
  two-kernel shape (`tests/test_federated_twocol_wall_served.py`).
- **Drive the split.** In PR1 (the model) create it via the keyboard command / `__rompMoveTab(sid,'down')`; in
  PR2 (the drag) drive a real pointer drag to the bottom edge (`page.mouse.down`, a move past the threshold so
  the page posts `{romp:"tabDrag"}` and the shell mounts zones, a move to the bottom-band coordinates so the
  bottom ghost gains `.on`, then `page.mouse.up`).
- **Assert the bottom pane is STACKED under, not beside:** the new frame has the SAME left as the top pane and a
  GREATER top, inside one column (contrast the horizontal split's greater LEFT, equal top), and the
  between-panes gutter's computed cursor is `row-resize`, never `col-resize`.
- **Assert the bottom dial:** hook `window.WebSocket` for FULL dial URLs (the cold-boot `wrapDials` pattern in
  `tests/test_cold_boot_diet_browser.py`), read the bottom frame's dials, and assert its `/ws` URL carries
  `&skeleton=1` and an `iid=` distinct from the top pane's. (Do not use the twocol lab's dial projection: it
  drops `iid`.)
- **Assert fill in EVERY pane (the headline):** for BOTH the top and the bottom frame, scroll `#content` to the
  top and assert `window.__rompRegions(sid)` has a run region with `lo===0` (filled to turn 0) plus a head gap,
  NOT a skeleton and not empty. Assert this for the NON-FOCUSED pane specifically (drive focus to the other
  pane, or reload the shell so the ring lands on one pane), and for the SOURCE pane. A test that only checks the
  just-focused new pane would pass even with `silentActivate` removed, so the non-focused fill-to-turn-0 check
  is the assertion that pins the wall lesson.
- **Assert the diet per bottom pane on ITS OWN socket** (`routeWebSocket`, counting `type=="session"` fulls
  versus `type=="status"`), or the bottom frame's `#tabs .tab-skeleton` count, NOT the kernel-wide
  `/perf builds.chat` (a slow runner mixes every pane's frames into that window).
- **Assert persistence:** reload the shell and assert `romp-chat-cols` (v:2 with the entry's
  `place:'below'`/`parent`/`ratio`) restores the top and bottom panes, their sessions, and the height ratio;
  assert each recreated pane redials and each fills to turn 0. The reload is exactly where the non-focused
  pane's #1754 dependence bites.

**Red first at main:** there is no bottom-edge zone, no `moveTab("down")`, no nested vertical chat gutter, and
no bottom-pane placement, so the split/dial/fill/persist assertions fail. Every drive selector is a name the
feature introduces, so the lab is written after each PR lands, its selectors pinned to the chosen names. Run it
with `ROMP_SERVED_TESTS_REQUIRE=1 ROMP_SERVED_TESTS_ENGINES=chromium uv run --python 3.13 --with pytest pytest
tests/test_<newlab>.py` under `capped`; CI picks it up via the `tests/test_*_served.py` glob.

## 7. Risks and open questions

- **The wall dependence is the top risk.** The feature is correct only because #1754 fills a non-focused shell
  pane; the lab's non-focused fill-to-turn-0 assertion is the guard, and it must run for both the local and the
  remote face. If `federated-pane-dial-terms.md` section 7 later widens the diet to local pages, the assertion
  must not depend on which path served the frame.
- **The DOM nesting and the vertical gutter are the real work**, not the partition. Only `make()`, `close()`,
  the new `row-resize` gutter with a persisted `ratio`, `moveTab("down")`, the bottom-edge zone, and the
  `moveFocus` graph are new; `ownerOf`/`sets`/`nextNumber`/`canSplit` are unchanged.
- **The persistence transition window.** A bottom pane is a `cols` entry with `place`/`parent`/`ratio` under
  v:2 (not a v:3 bump), so an old bundle in another tab renders it as a side column (mis-placed) instead of
  dropping the whole store. The new pane still needs its `romp-chat-cols` CustomEvent dispatched for cross-tab
  liveness.
- **The horizontal-versus-vertical frame lists.** Because a bottom pane is a `cols` entry, `frames()` and the
  all-frames routing include it, but the focus nav's `allCols`/`visCols` must exclude it from the left/right
  column walk. A columns-only accessor (top row only) is required so a bottom pane does not appear as a fourth
  horizontal column to Alt-Left/Right.
- **Tab-strip real estate and the active affordance at small heights.** The strip wraps then scrolls with no
  collapse-to-icons mode and no auto-scroll-active, so a short bottom pane can scroll the active tab or its
  folded stand-in header off-screen. The divider min clamp is the backstop; scroll-active-into-view on a short
  pane is the recommended addition.
- **The composer in a bottom pane.** One composer per `/chat` page, bottom-anchored; it self-limits to 60% of
  the iframe (`composerMaxH`, `render.ts:18923`), so a short bottom pane self-caps rather than eating the
  transcript. The divider min clamp is the backstop.
- **The vertical focus graph and the timeline return target** (section 3) are undefined today and must be
  designed: Alt-Up from the timeline into a split column needs a per-column last-focused-pane memory.
- **Tier.** This is a `feature` (a new capability inside the existing model, no kernel contract change). The
  user's GO stands from 2026-09-15; the code follows this refinement as a stack of two feature PRs.
