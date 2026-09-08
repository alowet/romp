// TAB GROUPS ARE TAGS (the user 2026-09-04): the chat tab strip sections by HOME tag — the first
// holder in tagOrder, the rule revealIn states — with the untagged trailing, per-browser on/off and
// per-section fold state under romp:tabgroups, and the section headers draggable to reorder
// tagOrder (the kernel-persisted union order the timeline's pill drag writes too). Executed tests on
// the pure module + source pins on render.ts / tag-menu.ts / styles.css (the tab-order.ts pattern;
// no jsdom for render.ts). Synthetic ids only.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { viewTagUnion } from "./session-views";
import { sectionTabs, anySectioned, homeTag, parseTabGroups, readTabGroups, writeTabGroups, isSectionCollapsed,
         toggleSectionCollapsed, setSectionCollapsed, planStrip, reorderTagOrder, applyTagOrder, TABGROUPS_KEY,
         DEFAULT_COLLAPSED, type TabSection } from "./tab-groups";

const ui = (...p: string[]) => fs.readFileSync(path.resolve(process.cwd(), "..", "ui", ...p), "utf8");
const RENDER = ui("webview", "render.ts");
const CSS = ui("webview", "styles.css");
const MENU = ui("webview", "tag-menu.ts");
const VIEWS = ui("webview", "session-views.ts");
const KERNEL = fs.readFileSync(path.resolve(process.cwd(), "..", "kernel", "kernel.py"), "utf8");

// the notes-api demo world: web + api in "infra", tests in "qa", a loose one; api ALSO in qa
const V = {
  active: "all",
  tags: [
    { id: "g1", name: "qa", color: "#DD42FF", members: ["tests", "api"] },
    { id: "g2", name: "infra", color: "#4EC9B0", members: ["web", "api"] },
    { id: "g3", name: "empty", color: "#e0af68", members: [] },
  ],
  remoteTags: [{ id: "TESTHOST-A:r1", host: "TESTHOST-A", name: "remotepool", color: "#7aa2f7", members: ["TESTHOST-A:m1"] }],
};

test("executed: the home-tag rule — one section per tab, its FIRST holder in tagOrder; sections in union order; the untagged trail", () => {
  const unions = viewTagUnion(V);
  const secs = sectionTabs(["web", "api", "loose", "tests"], unions);
  assert.deepEqual(secs.map((s) => [s.name, s.ids]),
    [["qa", ["api", "tests"]], ["infra", ["web"]], [null, ["loose"]]],
    "api holds qa AND infra — qa is first in the union order, so qa is its home; tabs keep strip order inside; the loose one trails");
  assert.equal(secs[0].color, "#DD42FF", "the section wears its tag's colour");
  assert.equal(homeTag("api", unions)!.name, "qa");
  // the SAME rule revealIn keys on (session-views.ts) — the two must never disagree
  assert.match(VIEWS, /const holder = unions\.find\(\(u\) => u\.members\.includes\(id\)\);/);
  // reorder the tags and api moves home with them — this is why reordering is first-class
  const flipped = viewTagUnion({ ...V, tagOrder: ["infra", "qa"] });
  assert.deepEqual(sectionTabs(["web", "api", "tests"], flipped).map((s) => [s.name, s.ids]),
    [["infra", ["web", "api"]], ["qa", ["tests"]]]);
  // a tag with no visible member yields no section; a remote-homed tag sections by NAME like any other
  assert.ok(!secs.some((s) => s.name === "empty"));
  assert.deepEqual(sectionTabs(["TESTHOST-A:m1"], unions).map((s) => s.name), ["remotepool"]);
});

test("executed: sectioning is on by default exactly when some tag holds a visible tab", () => {
  const unions = viewTagUnion(V);
  assert.equal(anySectioned(["web"], unions), true);
  assert.equal(anySectioned(["loose", "other"], unions), false, "an untagged world keeps the flat strip");
  assert.equal(anySectioned([], unions), false);
  assert.deepEqual(sectionTabs(["loose"], unions), [{ name: null, color: "", ids: ["loose"] }]);
});

test("executed: per-browser state — on by default, archived starts folded, toggles remember, junk reads as the default", () => {
  const d = parseTabGroups(null);
  assert.deepEqual(d, { on: true, collapsed: [], expanded: [] });
  assert.equal(isSectionCollapsed(d, "infra"), false);
  assert.equal(isSectionCollapsed(d, "archived"), true, "the archived tag exists to put sessions away — folded until opened");
  assert.ok(DEFAULT_COLLAPSED.has("archived"));
  const folded = toggleSectionCollapsed(d, "infra");
  assert.equal(isSectionCollapsed(folded, "infra"), true);
  assert.equal(isSectionCollapsed(toggleSectionCollapsed(folded, "infra"), "infra"), false, "toggling back opens it");
  const opened = toggleSectionCollapsed(d, "archived");
  assert.equal(isSectionCollapsed(opened, "archived"), false, "opening a default-folded section is remembered…");
  assert.deepEqual(opened.expanded, ["archived"]);
  assert.equal(isSectionCollapsed(toggleSectionCollapsed(opened, "archived"), "archived"), true, "…and folding it again drops the memory");
  assert.deepEqual(parseTabGroups('{"on":false,"collapsed":["qa",3],"expanded":"x"}'), { on: false, collapsed: ["qa"], expanded: [] },
    "wrong-typed entries drop; on=false is the one way off");
  assert.deepEqual(parseTabGroups("not json"), d, "a corrupt entry costs the preference, never the dashboard");
  assert.deepEqual(parseTabGroups("[1,2]"), d);
});

test("executed: write → read round-trips through localStorage under romp:tabgroups (the view-order two-path idiom)", () => {
  const store = new Map<string, string>();
  const g: any = globalThis;
  const savedLS = g.localStorage;
  g.localStorage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); } };
  try {
    writeTabGroups({ on: false, collapsed: ["qa"], expanded: ["archived"] });
    assert.ok(store.has(TABGROUPS_KEY), "persisted under the one key");
    assert.deepEqual(readTabGroups(), { on: false, collapsed: ["qa"], expanded: ["archived"] });
  } finally {
    g.localStorage = savedLS;
  }
  assert.equal(TABGROUPS_KEY, "romp:tabgroups");
});

test("executed: reorderTagOrder — the dragged group takes the target's slot, in the FULL union order", () => {
  const names = ["qa", "infra", "empty", "remotepool"];
  assert.deepEqual(reorderTagOrder(names, "remotepool", "infra"), ["qa", "remotepool", "infra", "empty"], "dragged up: lands before the target");
  assert.deepEqual(reorderTagOrder(names, "qa", "empty"), ["infra", "empty", "qa", "remotepool"], "dragged down: lands after the target");
  assert.deepEqual(reorderTagOrder(names, "qa", "qa"), names, "onto itself: unchanged");
  assert.deepEqual(reorderTagOrder(names, "nope", "qa"), names, "an unknown name: unchanged");
  assert.deepEqual(reorderTagOrder(["a", "a", "b"], "b", "a"), ["b", "a"], "duplicates collapse");
});

test("executed: applyTagOrder writes tagOrder AND re-sorts the local tags array — the timeline's pill-drag contract, so both surfaces agree", () => {
  const nv = applyTagOrder(V, ["infra", "remotepool", "qa", "empty"]);
  assert.deepEqual(nv.tagOrder, ["infra", "remotepool", "qa", "empty"], "the whole union order, remote-homed names included");
  assert.deepEqual(nv.tags!.map((t) => t.name), ["infra", "qa", "empty"], "locals re-sort to match (remote names simply aren't in it)");
  assert.deepEqual(viewTagUnion({ ...nv, remoteTags: V.remoteTags }).map((u) => u.name), ["infra", "remotepool", "qa", "empty"],
    "a rebuild from the posted blob renders the dragged order");
  assert.deepEqual(V.tags.map((t) => t.name), ["qa", "infra", "empty"], "the input blob is untouched");
  assert.deepEqual(applyTagOrder(null, ["a"]), { tagOrder: ["a"], tags: [] }, "a null blob is a fresh one");
});

test("the strip renders sections when the switch is on and some tag holds a visible tab (source pins)", () => {
  assert.match(RENDER, /const plan = planStrip\(visibleIds, viewTagUnion\(effViews\(\)\), readTabGroups\(\), activeId, phoneLayout\(\),/,
    "the pure module owns the rule; the phone layout and the create in flight are its inputs");
  assert.match(RENDER, /collapsedTabIds = plan\.folded;/);
  assert.match(RENDER, /if \("head" in item\) \{ bar\.appendChild\(makeGroupHead\(item\.head, item\.folded, item\.active\)\); continue; \}/);
});

test("executed: planStrip — sections + folds; the flat strip when off or untagged; the ACTIVE tab's section never folds", () => {
  const unions = viewTagUnion({ ...V, tags: [...V.tags, { id: "g4", name: "archived", color: "#6b7280", members: ["old1", "old2"] }] });
  const st = parseTabGroups(null);
  const p = planStrip(["web", "old1", "loose", "old2"], unions, st, "web", false);
  assert.equal(p.sectioned, true);
  assert.deepEqual(p.items, [
    { head: { name: "infra", color: "#4EC9B0", ids: ["web"] }, folded: false, active: true }, { id: "web" },
    { head: { name: "archived", color: "#6b7280", ids: ["old1", "old2"] }, folded: true, active: false },
    { head: { name: null, color: "", ids: ["loose"] }, folded: false, active: false }, { id: "loose" },
  ], "archived starts folded: its header alone stands in for old1/old2; infra holds the active tab");
  assert.deepEqual([...p.folded], ["old1", "old2"], "the ids keyboard cycling skips");
  const active = planStrip(["web", "old1", "loose"], unions, st, "old1", false);
  assert.deepEqual(active.items[2], { head: { name: "archived", color: "#6b7280", ids: ["old1"] }, folded: false, active: true },
    "the active tab's section renders open whatever the store says, and is marked as holding it");
  assert.deepEqual([...active.folded], []);
  assert.ok(!planStrip(["web", "old1"], unions, st, null, false).items.some((i) => "head" in i && i.active), "no active tab: no section holds it");
  const off = planStrip(["web", "old1"], unions, { ...st, on: false }, null, false);
  assert.deepEqual(off.items, [{ id: "web" }, { id: "old1" }], "switch off: the flat strip");
  assert.equal(off.sectioned, false);
  assert.deepEqual(planStrip(["loose"], unions, st, null, false).items, [{ id: "loose" }], "an untagged world: flat");
});

test("executed: the PHONE layout renders the flat strip — every visible id, nothing folded, whatever the store says (sectioning is desktop-only)", () => {
  // the kernel's phone chat page hides #tabs and builds its session list by scraping every rendered
  // tab; it has no header to unfold and no switch, so a folded section there (archived, by default)
  // made its sessions unreachable from the only switcher
  const unions = viewTagUnion({ ...V, tags: [...V.tags, { id: "g4", name: "archived", color: "#6b7280", members: ["old1", "old2"] }] });
  for (const st of [parseTabGroups(null), { on: true, collapsed: ["infra", "qa"], expanded: [] }]) {
    const p = planStrip(["web", "old1", "loose", "old2", "tests"], unions, st, null, true);
    assert.equal(p.sectioned, false);
    assert.deepEqual(p.items, [{ id: "web" }, { id: "old1" }, { id: "loose" }, { id: "old2" }, { id: "tests" }], "the flat strip, in strip order");
    assert.deepEqual([...p.folded], [], "visibleOrder excludes nothing on the phone");
  }
  // render.ts decides "phone" by the SAME media rule the kernel's page uses to swap the strip for its
  // list (_CHAT_MOBILE_CSS) — one string on each side, pinned equal here, so they cannot drift
  const media = RENDER.match(/const PHONE_LAYOUT_MEDIA = "([^"]+)";/)![1];
  assert.equal(media, "(pointer:coarse) and (max-width:1024px)");
  assert.ok(KERNEL.includes('"@media ' + media + '{"'), "the kernel's phone CSS gate is the very same rule");
  assert.match(RENDER, /function phoneLayout\(\): boolean \{\s*\n\s*try \{ return window\.matchMedia\(PHONE_LAYOUT_MEDIA\)\.matches; \} catch \{ return false; \}/);
  // …and the phone layout offers no switch, on either mount
  assert.match(RENDER, /\.\.\.\(phoneLayout\(\) \? \{\} : \{\s*\n\s*groupToggle: \{ label: "Group tabs by tag"/);
  // crossing the boundary (an iPad rotation) re-plans the strip: the CSS side of the same rule flips
  // the instant the media query does, so a plan sampled per render only went stale under the phone
  // list (folded tabs absent from the scrape) until the next push. The flip IS the event — one
  // listener on the same MediaQueryList, beside the fold-state listeners; no resize polling.
  assert.match(RENDER, /try \{ window\.matchMedia\(PHONE_LAYOUT_MEDIA\)\.addEventListener\("change", \(\) => renderTabs\(\)\); \} catch \{/);
  assert.ok(RENDER.indexOf("window.addEventListener(TABGROUPS_EVENT, () => renderTabs());") < RENDER.indexOf('matchMedia(PHONE_LAYOUT_MEDIA).addEventListener("change"'),
    "installed once at module scope with the other strip listeners, never inside a render");
});

test("executed + pinned: the section holding the ACTIVE tab is unfoldable while active — no fold action on its header, a title that says so, a click that stores nothing", () => {
  // planStrip renders the active tab's section open whatever the store says, so a fold click there
  // used to store folded=true that could not render: "click to fold this group" did nothing visible
  // on every click, and the stored fold bit when the user switched to another section
  const unions = viewTagUnion(V);
  const st = parseTabGroups(null);
  const marks = (activeId: string | null) => planStrip(["web", "api", "tests", "loose"], unions, st, activeId, false).items
    .filter((i): i is { head: TabSection; folded: boolean; active: boolean } => "head" in i).map((i) => [i.head.name, i.active]);
  assert.deepEqual(marks("web"), [["qa", false], ["infra", true], [null, false]], "exactly the section holding the active tab");
  assert.deepEqual(marks("tests"), [["qa", true], ["infra", false], [null, false]]);
  assert.deepEqual(marks(null), [["qa", false], ["infra", false], [null, false]]);
  // a user-folded section holding the active tab: open AND marked (the fold stays stored for later)
  const folded = setSectionCollapsed(st, "infra", true);
  const inf = planStrip(["web", "tests"], unions, folded, "web", false).items
    .find((i) => "head" in i && i.head.name === "infra") as { head: TabSection; folded: boolean; active: boolean };
  assert.deepEqual([inf.folded, inf.active], [false, true]);
  // render.ts: that header carries NO fold action (a distinct data-act the delegate flashes and
  // otherwise ignores), a title that says why, and no pointer cursor promising a click
  const head = RENDER.slice(RENDER.indexOf("function makeGroupHead("), RENDER.indexOf("function sectionHeadOf("));
  assert.match(head, /function makeGroupHead\(sec: TabSection, collapsed: boolean, holdsActive = false\): HTMLElement \{/);
  assert.match(head, /head\.dataset\.act = holdsActive \? "group-active" : "toggle-group";/);
  assert.match(head, /\? `\$\{name\} — this group holds the active tab; drag to reorder the groups`/);
  assert.match(head, /\+ \(holdsActive \? " holds-active" : ""\)\);/);
  assert.match(head, /head\.draggable = true;/, "it still drags to reorder the groups");
  const del = RENDER.slice(RENDER.indexOf('"group-active": () => {'), RENDER.indexOf('"group-active": () => {') + 120);
  assert.match(del, /^"group-active": \(\) => \{ \/\* [^*]*\*\/ \},/, "a no-op: the delegate's flash is the whole acknowledgement");
  assert.ok(!del.includes("writeTabGroups"), "…and nothing is stored");
  assert.match(CSS, /\.tab-group-head\.holds-active \{ cursor: default; \}/);
});

test("executed: a create in flight sections under the FIRST requested tag in tagOrder — its future home — from the first paint", () => {
  // the kernel tags a new session before its first push so the tab never lands untagged and jumps;
  // the client's provisional tab used to land in the untagged trail (a client-minted id in no
  // union) and move into its group when the frame arrived — the very jump the kernel avoids
  const unions = viewTagUnion(V);
  const st = parseTabGroups(null);
  const p = planStrip(["web", "prov1", "loose"], unions, st, "prov1", false, { id: "prov1", tags: ["infra", "qa"] });
  assert.deepEqual(p.items.map((i) => ("head" in i ? "#" + i.head.name : i.id)), ["#qa", "prov1", "#infra", "web", "#null", "loose"],
    "qa is first in tagOrder of the requested tags → qa is its home (the kernel's own home-tag rule)");
  const none = planStrip(["web", "prov1"], unions, st, "prov1", false, { id: "prov1", tags: [] });
  assert.deepEqual(none.items.map((i) => ("head" in i ? "#" + i.head.name : i.id)), ["#infra", "web", "#null", "prov1"], "no tags asked → the untagged trail");
  assert.deepEqual(V.tags.map((t) => t.members), [["tests", "api"], ["web", "api"], []], "the unions themselves are untouched");
  assert.match(RENDER, /provisionalTags = req\.tags\?\.slice\(\) \?\? \[\];/, "openProvisional keeps the request's tags…");
  assert.match(RENDER, /provisionalId \? \{ id: provisionalId, tags: provisionalTags \} : null\);/, "…and the plan sections the provisional under them");
  const drop = RENDER.slice(RENDER.indexOf("function dropProvisional("), RENDER.indexOf("function adoptProvisional("));
  assert.match(drop, /provisionalTags = \[\];/, "retired with the provisional");
});

test("executed: the header click sets the fold state from what it RENDERED — never a toggle of the stored bit", () => {
  // the active tab's section renders open whatever the store says; a stored toggle there inverted
  // the click: "fold" on default-folded archived (rendered open for the active tab) stored it OPEN
  // for good, and nothing visible changed
  const d = parseTabGroups(null);
  // archived: stored folded, rendered OPEN (active tab inside) → the click says "fold" → still folded, stored minimally
  assert.deepEqual(setSectionCollapsed(d, "archived", true), { on: true, collapsed: [], expanded: [] });
  assert.equal(isSectionCollapsed(setSectionCollapsed(d, "archived", true), "archived"), true);
  assert.deepEqual(toggleSectionCollapsed(d, "archived"), { on: true, collapsed: [], expanded: ["archived"] },
    "…where the stored toggle would have OPENED it");
  // infra folded by the user, then rendered open (active tab inside), click "fold" → stays folded
  const folded = setSectionCollapsed(d, "infra", true);
  assert.deepEqual(setSectionCollapsed(folded, "infra", true), folded);
  assert.deepEqual(setSectionCollapsed(folded, "infra", false), d, "and a rendered-folded click opens it");
  assert.deepEqual(setSectionCollapsed(setSectionCollapsed(d, "archived", false), "archived", true), d, "re-folding a default-folded section drops the memory");
  // the header carries its rendered state; the delegate reads it
  const head = RENDER.slice(RENDER.indexOf("function makeGroupHead("), RENDER.indexOf("function sectionHeadOf("));
  assert.match(head, /head\.dataset\.folded = collapsed \? "1" : "0";/);
  assert.match(RENDER, /if \(name\) writeTabGroups\(setSectionCollapsed\(readTabGroups\(\), name, el\.dataset\.folded !== "1"\)\);/,
    "rendered open → fold; rendered folded → open");
});

test("a folded section renders its header alone with a count + one pip by the TAB's state rule; cycling skips folded ids", () => {
  assert.match(RENDER, /function visibleOrder\(\): string\[\] \{ return order\.filter\(\(id\) => tabInView\(id\) && !collapsedTabIds\.has\(id\)\); \}/,
    "every cycling path walks visibleOrder (session-views.test pins the three callers)");
  const head = RENDER.slice(RENDER.indexOf("function makeGroupHead("), RENDER.indexOf("function sectionHeadOf("));
  assert.match(head, /n\.textContent = String\(sec\.ids\.length\);/, "the count");
  assert.match(head, /const kind = sectionPip\(sec\.ids\.map\(\(id\) => sessions\.get\(id\)\?\.status\)\);/,
    "one summary pip, classified by tab-state.ts — the same rule the tab itself wears (tab-state.test)");
  assert.match(head, /pip\.title = SECTION_PIP_TITLE\[kind\];/);
  assert.ok(!head.includes('"tab-dot"'), "never a .tab-dot — the kernel's mobile scrape keys on the tab pips' vocabulary");
  assert.match(head, /const sep = el\("div", "tab-group-sep"\);/, "the untagged trail is UNLABELED (the ruling): a separator, not a header");
  // the tab's own class comes from the same function
  assert.match(RENDER, /const stateCls = tabStateClass\(s\.status\);\s*\n\s*if \(stateCls\) tab\.classList\.add\(stateCls\);/);
  assert.match(CSS, /\.tab-group-pip\.retrying \{ background: #e67e22; \}/, "amber, the tab's .tab-retrying hue");
});

test("row hairlines count section headers and the separator as row members (T134's floating look must not return)", () => {
  // a wrapped row made only of folded headers got no line: the painter grouped `.tab` children only
  const painter = RENDER.slice(RENDER.indexOf("function paintTabRowLines("), RENDER.indexOf("let tabRowObserver"));
  assert.match(painter, /if \(!\(t\.classList\.contains\("tab"\) \|\| t\.classList\.contains\("tab-group-head"\) \|\| t\.classList\.contains\("tab-group-sep"\)\)\) continue;/);
  // the separator's offsetTop is the row's: gutters are padding, not margin (see the drag-live pin)
  assert.match(CSS, /\.tab-group-sep \{ flex: 0 0 auto; box-sizing: border-box; width: 13px; padding: 8px 6px; background: var\(--box-border\); background-clip: content-box; \}/);
});

test("the picker's Tags row is for SDK and Codex sessions: disabled behind a note on the tmux pick, and no `tags` ride a tmux create", () => {
  // the kernel refuses tags on a tmux create (a terminal session's id is unknown until it starts);
  // the row, prefilled from a tagged active tab, used to turn every terminal create into a refusal.
  // A Codex create takes them (the kernel applies parent/tags on one since the upstream fold's round
  // 2), so the row and the payload follow ONE predicate — executed here on each backend name
  const pred = RENDER.match(/function backendTakesTags\(be: string\): boolean \{ (return [^}]*); \}/);
  assert.ok(pred, "one predicate decides which backend a chip is for");
  const takes = new Function("be", pred![1]) as (be: string) => boolean;
  assert.equal(takes("sdk"), true);
  assert.equal(takes("codex"), true, "a Codex create takes tags");
  assert.equal(takes("tmux"), false, "a terminal session's id is unknown until it starts");
  assert.equal(takes(""), false);
  assert.match(KERNEL, /_create_codex_session\(nm, cwd, client=client,\s+parent=psid or "", tags=ctags\)/,
    "the premise: the kernel's createSession op applies tags on a Codex create");
  const sync = RENDER.slice(RENDER.indexOf("function syncPickerTags("), RENDER.indexOf("function syncPickerAuth("));
  assert.match(sync, /const takes = backendTakesTags\(pickerBackendChoice\(\)\);/);
  assert.match(sync, /wrap\.classList\.toggle\("disabled", !takes\);/);
  assert.match(sync, /\.forEach\(\(b\) => \{ b\.disabled = !takes; \}\);/);
  assert.match(sync, /note\.style\.display = takes \? "none" : "";/);
  assert.match(RENDER, /tgNote\.textContent = "Tags apply to SDK and Codex sessions";/);
  assert.match(RENDER, /beWrap\.addEventListener\("click", \(\) => \{ syncPickerAuth\(\); syncPickerTags\(\); \}\);/, "re-decided on every backend toggle");
  assert.match(RENDER, /syncPickerTags\(\);\s+\/\/ the backend toggle was just reset/, "…and on every open, after the backend reset");
  assert.match(RENDER, /const tags = backendTakesTags\(backend\)\s*\n\s*\? Array\.from\(tgWrap\.querySelectorAll<HTMLElement>\("\.picker-be-opt\.sel"\)\)/,
    "the create handler sends none for tmux, through the same predicate");
  assert.doesNotMatch(RENDER, /const tags = backend === "sdk"/, "no second, SDK-only copy of the rule");
  assert.match(RENDER, /:not\(\.picker-host\):not\(\.picker-auth\):not\(\.picker-tags\) \.picker-be-opt\.sel/, "a selected tag chip never reads as the backend pick");
  assert.match(CSS, /\.picker-tags\.disabled \.picker-be-opt \{ opacity: 0\.45; cursor: default; pointer-events: none; \}/);
});

test("headers are click-safe: data-act on the node, the action on the stable #tabs delegate, one render path via the event", () => {
  assert.match(RENDER, /head\.dataset\.act = holdsActive \? "group-active" : "toggle-group";/);
  assert.match(RENDER, /"toggle-group": \(el\) => \{\s*\n\s*const name = el\.dataset\.group;\s*\n\s*if \(name\) writeTabGroups\(setSectionCollapsed\(readTabGroups\(\), name, el\.dataset\.folded !== "1"\)\);/);
  assert.match(RENDER, /window\.addEventListener\(TABGROUPS_EVENT, \(\) => renderTabs\(\)\);/, "the same-window delivery");
  assert.match(RENDER, /window\.addEventListener\("storage", \(e\) => \{ if \(e\.key === TABGROUPS_KEY\) renderTabs\(\); \}\);/, "…and a sibling pane's");
  assert.match(RENDER, /if \(name\) writeTabGroups\(setSectionCollapsed/);
  assert.doesNotMatch(RENDER.slice(RENDER.indexOf('"toggle-group": (el) => {'), RENDER.indexOf('"toggle-group": (el) => {') + 300), /renderTabs\(\)/,
    "the toggle does not render itself — the event does, so a local toggle and a sibling pane's take one path");
});

test("dragging a header reorders tagOrder through the views path — the store the timeline's pill drag writes (source pins)", () => {
  assert.match(RENDER, /head\.draggable = true;/);
  assert.match(RENDER, /draggedGroup = name;/);
  const drop = RENDER.slice(RENDER.indexOf('tabs.addEventListener("drop"'), RENDER.indexOf("tabDragCommitted = true;"));
  assert.match(drop, /if \(draggedGroup\) \{/);
  assert.match(drop, /postTagOrder\(reorderTagOrder\(viewTagUnion\(effViews\(\)\)\.map\(\(u\) => u\.name\), draggedGroup, to\)\);/,
    "the FULL union order as a LENS write: the store's blob plus tagOrder, never the pending copy; setTimelineViews underneath (postTagOrder → postLens)");
  const over = RENDER.slice(RENDER.indexOf('tabs.addEventListener("dragover"'), RENDER.indexOf("if (!draggedId || !dragGeom) return;"));
  assert.match(over, /target\.classList\.add\("drop-target"\)/, "the target section wears the insertion cue");
  assert.doesNotMatch(over, /setTimeout|Date\.now/, "no time-based logic — the drop is the event");
  assert.match(CSS, /\.tab-group-head\.drop-target \{ box-shadow: inset 2px 0 0 var\(--accent\); \}/);
});

test("the switch lives at the foot of the chat tag-lens menu beside Configure tags…, desktop mount only", () => {
  assert.match(MENU, /groupToggle\?: \{ label: string; on: \(\) => boolean; toggle: \(\) => void \};/);
  assert.match(MENU, /if \(opts\.groupToggle\)\s*\n\s*row\(opts\.groupToggle\.label, opts\.groupToggle\.on\(\), null, true\)\.addEventListener\("click", \(\) => \{ opts\.groupToggle!\.toggle\(\); build\(\); \}\);/,
    "✓-marked when on; flips and repaints in place like the tag rows");
  assert.ok(MENU.indexOf("if (opts.groupToggle)") < MENU.indexOf('row("Configure tags…"'), "beside — above — Configure tags…");
  assert.match(RENDER, /groupToggle: \{ label: "Group tabs by tag", on: \(\) => readTabGroups\(\)\.on,/);
  const mobile = RENDER.slice(RENDER.indexOf('const mslot = document.getElementById("mtag-slot")'), RENDER.indexOf("paintTabRowLines(bar);"));
  assert.ok(!mobile.includes("groupToggle"), "the phone page hides the strip itself, so its mount offers no switch");
});

test("the picker's Tags row: prefilled from the ACTIVE tab, visible and editable, posted as `tags` on createSession", () => {
  assert.match(RENDER, /interface CreateReq \{ name: string; backend: string; dir: string; host: string; auth\?: string; tags\?: string\[\] \}/);
  assert.match(RENDER, /const tgWrap = el\("div", "picker-backend picker-tags"\);/);
  assert.match(RENDER, /const preset = new Set\(activeId \? unions\.filter\(\(u\) => u\.members\.includes\(activeId!\)\)\.map\(\(u\) => u\.name\) : \[\]\);/,
    "the active tab's tags pre-select — never a silent inherit");
  assert.match(RENDER, /b\.addEventListener\("click", \(\) => b\.classList\.toggle\("sel"\)\);/, "multi-select: each chip on its own");
  assert.match(RENDER, /\.\.\.\(tags\.length \? \{ tags \} : \{\}\) \}\);/, "absent when nothing is picked (the kernel's not-asked contract)");
  assert.match(RENDER, /tgWrapEl\.style\.display = pick \|\| !unions\.length \? "none" : "";/, "hidden with no tags to offer, and in pick-mode");
});

test("the section chrome reuses the strip's type sizes — labels match labels (font-size rule)", () => {
  const head = CSS.match(/\.tab-group-head \{[^}]*\}/)![0];
  const tab = CSS.match(/^\.tab \{[\s\S]*?\n\}/m)![0];
  assert.equal(head.match(/font-size: ([\d.]+em)/)![1], tab.match(/font-size: ([\d.]+em)/)![1], "the header wears the tab's size");
  assert.match(CSS, /\.tab-group-count \{ font-size: 0\.82em; opacity: 0\.7; \}/, "the count at the sub-line size every menu uses");
  assert.match(CSS, /\.tab-group-dot \{ flex: 0 0 auto; width: 7px; height: 7px; border-radius: 50%;/, "the tab pip's 7px dot");
  assert.match(CSS, /\.tab-group-pip\.blocked \{ background: var\(--st-blocked-bg\); \}/, "status colours keep their meaning");
  assert.match(CSS, /\.tab-group-sep \{ flex: 0 0 auto; box-sizing: border-box; width: 13px; padding: 8px 6px;/, "a 1px line inside 6px gutters (padding, so its rect is its footprint)");
});
