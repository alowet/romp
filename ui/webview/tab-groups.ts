// TAB GROUPS ARE TAGS (the user 2026-09-04). The chat tab strip renders one section per tag, in the
// user's tag order, each tab under its HOME tag — the FIRST holder tag in tagOrder, the rule
// revealIn already states ("a tagged session's home is its first holder tag"), so a tab's section
// and its reveal agree. Sessions in no tag trail in an unlabeled section. No new store and no new
// session field: the kernel's views blob (tags, members, tagOrder) is the whole model, the headers
// are the very tags the Tags flyout edits, and reordering the groups IS reordering tagOrder — the
// kernel-persisted union order the timeline's tag-pill drag writes too, so the two surfaces cannot
// disagree. A session may hold other tags as well; they filter, they do not section.
//
// Per-browser state, this viewer's like romp:vieworder: whether the strip sections at all (ON by
// default whenever some tag holds a visible tab; the chat tag-lens menu's "Group tabs by tag" turns
// it off) and which sections are folded. `archived` starts folded — that tag exists to put sessions
// away. Notification is view-order.ts's two-path idiom: localStorage reaches other panes (the
// storage event), a same-window CustomEvent reaches the writer. Pure and DOM-free (the tab-order.ts
// pattern) so the rule executes in node tests; render.ts paints it.
import { SessionViews, TagUnion, viewTags } from "./session-views";

export const TABGROUPS_KEY = "romp:tabgroups";
export const TABGROUPS_EVENT = "romp-tabgroups";
/** sections that start folded until the user opens them (remembered per browser once toggled) */
export const DEFAULT_COLLAPSED: ReadonlySet<string> = new Set(["archived"]);

/** One strip section: a tag's name + colour and the visible tabs homed in it. name null = the
 *  trailing untagged section (unlabeled by the user's ruling — a separator, not a header). */
export interface TabSection { name: string | null; color: string; ids: string[] }

export interface TabGroupsState {
  on: boolean;          // the sectioned strip (default true)
  collapsed: string[];  // sections the user folded
  expanded: string[];   // default-folded sections the user opened
}

/** THE home-tag rule: the first union (they arrive in tagOrder) holding the id, or null. */
export function homeTag(id: string, unions: readonly TagUnion[]): TagUnion | null {
  return unions.find((u) => u.members.includes(id)) || null;
}

/** Section the visible ids: one section per home tag, sections in UNION order (tagOrder governs —
 *  which is why reordering tags is first-class), tabs inside keep their strip order, the untagged
 *  trail last. A tag holding no visible id yields no section. */
export function sectionTabs(visibleIds: readonly string[], unions: readonly TagUnion[]): TabSection[] {
  const byName = new Map<string, TabSection>();
  const loose: string[] = [];
  for (const id of visibleIds) {
    const home = homeTag(id, unions);
    if (!home) { loose.push(id); continue; }
    let s = byName.get(home.name);
    if (!s) { s = { name: home.name, color: home.color || "", ids: [] }; byName.set(home.name, s); }
    s.ids.push(id);
  }
  const out: TabSection[] = [];
  for (const u of unions) { const s = byName.get(u.name); if (s && !out.includes(s)) out.push(s); }
  if (loose.length) out.push({ name: null, color: "", ids: loose });
  return out;
}

/** Does any tag hold a visible tab? Sectioning is on by default exactly then — an untagged world
 *  renders the flat strip it always had. */
export function anySectioned(visibleIds: readonly string[], unions: readonly TagUnion[]): boolean {
  return visibleIds.some((id) => homeTag(id, unions) !== null);
}

const fresh = (): TabGroupsState => ({ on: true, collapsed: [], expanded: [] });

/** A stored blob; anything malformed reads as the default rather than throwing (view-order's rule:
 *  a corrupt entry may cost you a preference, never the dashboard). */
export function parseTabGroups(raw: string | null | undefined): TabGroupsState {
  if (!raw) return fresh();
  try {
    const o = JSON.parse(raw);
    if (!o || typeof o !== "object" || Array.isArray(o)) return fresh();
    const strs = (xs: unknown) => (Array.isArray(xs) ? xs.filter((x): x is string => typeof x === "string") : []);
    return { on: o.on !== false, collapsed: strs(o.collapsed), expanded: strs(o.expanded) };
  } catch {
    return fresh();
  }
}

export function readTabGroups(): TabGroupsState {
  try {
    return parseTabGroups(localStorage.getItem(TABGROUPS_KEY));
  } catch {
    return fresh();   // private mode / blocked storage → the defaults, every time
  }
}

/** Persist and tell every pane — `storage` fires only in OTHER same-origin contexts, so the writing
 *  window gets the same news through a CustomEvent (one notification path, two deliveries). */
export function writeTabGroups(st: TabGroupsState): void {
  try {
    localStorage.setItem(TABGROUPS_KEY, JSON.stringify({ on: st.on, collapsed: st.collapsed, expanded: st.expanded }));
  } catch {
    /* quota / private mode → this preference just doesn't outlive the page */
  }
  try {
    window.dispatchEvent(new CustomEvent(TABGROUPS_EVENT));
  } catch {
    /* no window (node test) */
  }
}

/** Folded? The user's explicit fold or open wins; otherwise the default set decides. */
export function isSectionCollapsed(st: TabGroupsState, name: string): boolean {
  if (st.collapsed.includes(name)) return true;
  if (st.expanded.includes(name)) return false;
  return DEFAULT_COLLAPSED.has(name);
}

/** Set a section's fold state EXPLICITLY. The header's click passes the state it RENDERED, not the
 *  stored one: the active tab's section renders open whatever the store says, and toggling the
 *  stored bit there inverted the click — "fold" on a stored-folded, rendered-open `archived` stored
 *  it OPEN for good, with nothing visible changing. Minimal storage: a name is listed only where it
 *  differs from the default set. */
export function setSectionCollapsed(st: TabGroupsState, name: string, folded: boolean): TabGroupsState {
  const collapsed = st.collapsed.filter((n) => n !== name);
  const expanded = st.expanded.filter((n) => n !== name);
  if (folded) { if (!DEFAULT_COLLAPSED.has(name)) collapsed.push(name); }
  else if (DEFAULT_COLLAPSED.has(name)) expanded.push(name);
  return { on: st.on, collapsed, expanded };
}

export function toggleSectionCollapsed(st: TabGroupsState, name: string): TabGroupsState {
  return setSectionCollapsed(st, name, !isSectionCollapsed(st, name));
}

/** One strip item: a section header (folded or open; `active` = it holds the active tab) or a tab. */
export type StripItem = { head: TabSection; folded: boolean; active: boolean } | { id: string };
export interface StripPlan {
  items: StripItem[];
  folded: Set<string>;   // the ids a folded header stands in for — keyboard cycling skips them
  sectioned: boolean;
}

/** The strip PLAN render.ts paints, pure so the rule executes in node tests.
 *  - `phone`: the kernel's phone chat page hides the strip and builds its own session list by scraping
 *    every rendered tab; it has no header to unfold and no switch, so a folded section there made its
 *    sessions unreachable (`archived` starts folded). Sectioning is DESKTOP-ONLY: on the phone layout
 *    the plan is the flat strip, always — every visible id, nothing folded.
 *  - `pending`: a provisional tab (a create in flight) with the tags the request named. Its future
 *    home is the first of those in tagOrder — the kernel's own home-tag rule — so it renders there
 *    from the first paint instead of landing in the untagged trail and jumping when the frame arrives.
 *  - The ACTIVE tab's section never renders folded: keyboard focus must never land on a hidden node.
 *    Its header is marked `active`, and render.ts gives that header no fold action: a fold stored
 *    there could not render (nothing changed on screen, on every click) and then bit when the user
 *    switched tabs. The section is unfoldable while it holds the active tab. */
export function planStrip(visibleIds: readonly string[], unions: readonly TagUnion[], st: TabGroupsState,
                          activeId: string | null, phone: boolean,
                          pending?: { id: string; tags: readonly string[] } | null): StripPlan {
  let u = unions;
  if (pending && pending.tags.length && visibleIds.includes(pending.id)) {
    u = unions.map((x) => (pending.tags.includes(x.name) && !x.members.includes(pending.id)
      ? { ...x, members: [...x.members, pending.id] } : x));
  }
  const sectioned = !phone && st.on && anySectioned(visibleIds, u);
  const items: StripItem[] = [];
  const folded = new Set<string>();
  if (!sectioned) {
    for (const id of visibleIds) items.push({ id });
    return { items, folded, sectioned };
  }
  for (const sec of sectionTabs(visibleIds, u)) {
    const active = activeId !== null && sec.ids.includes(activeId);
    const f = sec.name !== null && !active && isSectionCollapsed(st, sec.name);
    items.push({ head: sec, folded: f, active });
    if (f) { for (const id of sec.ids) folded.add(id); continue; }
    for (const id of sec.ids) items.push({ id });
  }
  return { items, folded, sectioned };
}

/** The header drag: `from` takes `to`'s slot in the FULL union order (every name, not only the
 *  sectioned ones — the persisted order must stay complete). Unknown or equal names → unchanged. */
export function reorderTagOrder(names: readonly string[], from: string, to: string): string[] {
  const list = names.filter((n, i) => typeof n === "string" && names.indexOf(n) === i);
  const fi = list.indexOf(from), ti = list.indexOf(to);
  if (fi < 0 || ti < 0 || fi === ti) return list;
  const out = list.filter((n) => n !== from);
  const at = out.indexOf(to);
  out.splice(fi < ti ? at + 1 : at, 0, from);
  return out;
}

/** Write an order onto a views blob the way the timeline's pill drag does: tagOrder carries the
 *  whole union order (remote-homed names included, viewer-side), and the local tags array re-sorts
 *  to match — the natural store for local-only readers. Returns a new blob. */
export function applyTagOrder(views: SessionViews | null | undefined, order: readonly string[]): SessionViews {
  const nv: SessionViews = JSON.parse(JSON.stringify(views || {}));
  nv.tagOrder = order.slice();
  const ix = new Map(order.map((n, i) => [n, i] as const));
  const rank = (name: string | undefined) => (name !== undefined && ix.has(name) ? ix.get(name)! : order.length);
  nv.tags = viewTags(nv).slice().sort((a, b) => rank(a.name) - rank(b.name));
  delete nv.groups;
  return nv;
}
