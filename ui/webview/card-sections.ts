// THE CARD'S SECTIONS, one builder for the feed card and the Needs you box's row (plans/needs-you.md, "the row carries what the card
// carries", the user 2026-09-23): the press toggles Background · Summary · Stalled · N sub-goals · Awaiting task in the card's order, the
// one-open rule with its default, the state behind them (secChoice by item id, the tree's expanded branches), and the bodies they drive
// (the background paragraph, the distill line, the stall note, the sub-goal tree, the awaited rows). Moved here verbatim from feed.ts
// (2026-09-24) so the chat page's row draws the same disclosure from the same fields and never a second copy; what the two pages do
// differently rides SectionEnv (the collapsed-by-default preference, the node click zones, the PR repo for links, the live durations,
// opening a session). Every host that shows an item's sections registers here (registerSectionHost), so a press on any of them reaches
// them all: the feed card, its focused-section copy and the chat box's row are one twin set for the item.
import { linkifyPrRefs } from "./pr-links";
import { hostPartsNodes } from "./host-prefix";
import { awaitWord, groupRows, waitsNote, GROUP_TITLE, ROW_KIND_OF_LEGACY, spinFor, type AwaitRow, type Spin } from "./spin-caption";
import { distillPending, distillParas, distillStaleNote } from "./distiller-line";
import { stampAge } from "./feed-age";
import { setTip } from "./tip";   // the interrupting chip's styled tip, as the card had it (tip.ts), never a native title

function el(tag: string, cls?: string): HTMLElement {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  return e;
}

export interface NodeLogRow {
  kind: string; src: string; why?: string | null;
  at?: number | null; evT?: number | null; anchorUuid?: string | null;
}

export interface AskTreeNode {
  born?: { kind: string; via: string; why: string; healed?: boolean } | null;   // T319: a step the session started on its own
                                                                                //   (via: workflow | agent | work); why it sits under this goal
  id: string; kind: "ask" | "handoff"; text: string; who: string;
  whoSid: string; whoColor: { bg: string; fg: string } | null;   // agent → colored session link
  whoWorking?: boolean;                                          // that agent is currently WORKING → yellow dot before its name
  status: "done" | "question" | "open"; t: number; last: number;
  mt?: number;                                                   // last-modified (done/block segment) → blocked/done nodes deep-link to where they RESOLVED, not where they were minted
  anchorUuid?: string | null;                                    // EXACT turn uuid for this node's WORK target (where it resolved — an assistant turn); mark/time zones jump here. null when unresolvable
  promptAnchorUuid?: string | null;                              // EXACT turn uuid for this node's PROMPT target = the user's minting message (a user turn) → prompt-intent jumps (title, text) resolve BY ID (kernel 92e23ff)
  derived?: boolean;                                             // done by roll-up/roll-down (kernel), not explicit → DIMMED ✓ disc
  qderived?: boolean;                                            // "question" by roll-UP (the block lives in a descendant) → tooltip says so; the actual ask carries its own ⏸ below (kernel flatten, the user 2026-07-11)
  auth?: "open" | "done";                                        // AUTHORITATIVE tier: mirrors an item on the agent's OWN to-do list → solidity=authority disc (open = bold accent ring; done = heaviest check). Absent = plain judge-inferred node.
  followupPending?: boolean;                                     // this sub was optimistically reopened by a per-sub follow-up → "↻ Followed up" chip (kernel flatten, judges 047264f)
  summary?: string | null;                                       // the DISTILLER's key takeaway for a completed goal (artifact or 1-3 sentences) → the modal's auto-line for a DONE node (kernel flatten 78fc97b)
  blockSummary?: string | null;                                  // the BLOCK-distiller's decision brief for a blocked goal → the modal's auto-line for a BLOCKED node (kernel 466393c); null until produced
  summaryAnchorUuid?: string | null;                            // the brief/summary line's own landing (kernel T388): the text atom that carries it
  summaryAnchorQuote?: string | null;                           // …and its located span, sent as the click's quote
  relayNote?: string | null;   // a far host still holds a relayed question after its wait ended (kernel relayCarried) → its own dim line under the brief, never a brief paragraph
  trgb?: [number, number, number];                               // last-activity recency tint (timestamp)
  cleared?: boolean;                                             // user-cleared sub (nodeOverride op:clear) → struck-through faded row + "cleared" chip; the mark stays tied to status (box = done, the user 2026-07-26)
  reviewedEarlier?: boolean;                                     // this done sub predates the top's review boundary (kernel flatten ↔ jd.review_boundary, the distiller's own scoping) → collapsed behind one "N reviewed earlier" row (the user 2026-08-19)
  parked?: { n: number } | null;                                 // LEAPFROGGED open row (kernel _parked_rows, the user 2026-08-24): nothing filed under it while n younger siblings were dispatched past it → quiet "parked" tag + the card's dim sub-goals suffix; retires on its own delegation edge or any verdict
  log?: NodeLogRow[] | null;                                     // the node's newest verdict rows (kernel _node_log_rows, non-done only) → the modal's per-item story (the user 2026-07-20)
  children: string[];
}

/** The fields of a feed item the sections read: the card's AskItem satisfies it, and so does the chat box's row (the kernel's _needs_you_rows
 *  carries every one of them from the same feed item). */
export interface SectionItem {
  itemId: string; sid: string; t?: number | null;
  background?: string | null;
  summary?: string | null; blockSummary?: string | null;
  briefParts?: { id?: string; since: number }[] | null; summaryParts?: { id?: string; since: number }[] | null;   // the distill line's per-paragraph stamps
  summaryAnchorUuid?: string | null; summaryAnchorQuote?: string | null;   // the whole line's landing: where the takeaway or brief was written
  summaryAnchorsPara?: ({ u: string; q?: string } | null)[] | null;   // T220: a paragraph's own citation
  summaryStale?: boolean | null;
  tree?: AskTreeNode[] | null;
  stalled?: { why: string; since?: number; note?: string | null; blocked?: boolean } | null;
  awaiting?: { why?: string | null; kind?: string | null; since?: number | null; count?: number | null; tasks?: string[] | null;
               peers?: { name: string; host?: string; sid?: string; color?: { bg: string; fg: string } | null }[] | null;
               items?: AwaitRow[] | null } | null;
}

/** What a page supplies to the shared builder: its collapsed-by-default preference, how a sub-goal row's zones are wired, the PR repo for
 *  a row's links, the live duration nodes, how a peer's session is opened, its clock and age words (the feed's kernel-synced clock and its
 *  recency tint; the stamped ages are repainted by each page's own live pass over [data-age-t]), and its landings: where a click on the
 *  distill line or a paragraph goes (the feed posts showOnTimeline; the chat page scrolls to the turn), what a line without an anchor says,
 *  and what the warning chip opens (the feed's detail overlay; the chat page has none). */
export interface SectionEnv {
  collapsed(): boolean;
  wireNode(it: SectionItem, node: AskTreeNode, mark: HTMLElement, txt: HTMLElement, wire: boolean): void;
  repoOf(sid: string | undefined): string | null;
  durNodes(since: number | null | undefined): (string | HTMLElement)[];
  openSession(sid: string): void;
  nowSec(): number;
  relAge(sec: number): string;
  ageTint(sec: number): string;
  clockHM(t: number): string;
  landing(it: SectionItem, target: { anchorUuid: string; quote?: string; anchor: "work" }): void;
  noAnchor(it: SectionItem): void;
  openWarns?(it: BadgeItem & SectionItem, title: string): void;   // the warning chip's destination; a page without one gets a chip that promises no click (a span, no click sentence)
  workDot?(peer: HTMLElement, name: string): void;   // the feed's live working/awaiting dot before a tracked recipient's name; a page without one leaves the name bare
  afterApply?(a: HTMLElement): void;   // called LAST after a host is re-applied from a pick or the channel (round three of the box content PR): the chat page runs
  //                                       its items-level face and its More pass there, which the apply alone left stale
}
export type SecChoice = "bg" | "summary" | "subgoals" | "tasks" | "stall" | "none";
const SEC_CHOICES: readonly string[] = ["bg", "summary", "subgoals", "tasks", "stall", "none"];

// the twin set per item: every host element that shows the item's sections (a feed card, its focused-section copy, the chat box's row).
// The set is EXACT: a host is unregistered where it leaves (the feed's map deletions, the chat box's row drops), and a host that left
// the document is dropped on the next read as a belt; before, a departed card stayed registered until a read of the same item or a
// Collapsed flip, and every focus change added registered copies (a contributor's post-merge note on PR 2124, 2026-09-24)
const hosts = new Map<string, Set<HTMLElement>>();
export function registerSectionHost(itemId: string, a: HTMLElement): void {
  let set = hosts.get(itemId);
  if (!set) { set = new Set(); hosts.set(itemId, set); }
  set.add(a);
}
export function unregisterSectionHost(itemId: string, a: HTMLElement): void {   // a host that sheds its sections (the Needs you row turned credential row) leaves the set
  const set = hosts.get(itemId); if (!set) return;
  set.delete(a); if (!set.size) hosts.delete(itemId);
}
export function sectionHosts(itemId: string): HTMLElement[] {
  const set = hosts.get(itemId);
  if (!set) return [];
  for (const a of Array.from(set)) if (!a.isConnected) set.delete(a);
  if (!set.size) hosts.delete(itemId);
  return Array.from(set);
}
/** The raw set, for tests alone: what the registry holds for an item WITHOUT dropping disconnected hosts as it reads (sectionHosts
 *  does), so a pin can say a card that left the payload left the registry through the unregister on its way out, not through the read. */
export function sectionHostsRaw(itemId: string): HTMLElement[] { return Array.from(hosts.get(itemId) || []); }
// THE CHOICE ACROSS DOCUMENTS (plans/needs-you.md, the row carries what the card carries): the card lives in the feed page and the Needs you
// row in the chat page, two documents in the shell, each with its own copy of this module and its own secChoice. EVERY write to the choice
// goes through setSectionChoice or replaceSectionChoices below (a press, the feed's hydration from localStorage, its prune to the live card
// set, its clear when the Collapsed preference flips), and each posts on a BroadcastChannel (same origin; the shell's panes are), which
// persists nothing. The feed page is the OWNER of the state (it persists the map in its view state) and the chat page a FOLLOWER: a
// follower says hello when it loads and the owner answers with its whole map, and the owner posts its map when it loads too, so whichever
// document comes up second gets the state (the shell loads the feed pane on demand); a follower's own pick goes to the owner as a set, which
// the owner applies and persists. In VS Code the chat and feed webviews are separate origins, so nobody hears: each page keeps its own choice
// there (plans/needs-you.md; a fallback through the extension host is deferred to after the release). The receiver re-applies to every host
// it has for the item with the item and environment each host remembered. The channel is the WINDOW's: Node has a BroadcastChannel of its
// own, and one that has posted keeps the process alive, so the node test run hung on the first module importing this (2026-09-24, twice);
// a page without a window, or a test's stand-in window, gets no channel and keeps its own choice.
// THE ACKNOWLEDGEMENT (a contributor's second note on PR 2124, the 0.17.1 fix): a follower's set is applied by the owner and answered with an
// ack naming the choice applied; the follower drops its own pick only when the acknowledged choice still equals it (a stale ack spares a
// newer pick). Without it a row pick outlived every feed map that lacked it (the Collapsed clear, the prune once the item left the live set):
// the chat page re-imposed and re-posted, the feed persisted again, per payload, until a reload. A set carries the sender's role, so an owner
// acks a follower's set alone; an ack is the owner's word and every owner ignores it (a shell feed pane and a standalone feed tab are two
// owning documents of one origin: a plain set would bounce between them forever).
type SectionSyncMsg = { kind: "hello" } | { kind: "set"; id: string; choice: SecChoice | null; from?: "owner" | "follower" }
                    | { kind: "ack"; id: string; choice: SecChoice | null } | { kind: "map"; entries: [string, SecChoice][] };
const sectionChannel: BroadcastChannel | null = typeof window !== "undefined" && typeof (window as { BroadcastChannel?: unknown }).BroadcastChannel === "function" ? new window.BroadcastChannel("romp-card-sections") : null;
let syncRole: "owner" | "follower" = "follower";
let onChoiceChange: (() => void) | null = null;
// a FOLLOWER's own picks, kept until the owner speaks for the item (a set from the owner, or a map carrying the same choice): a pick made on
// the row before the feed document is up would otherwise be discarded when the feed hydrates and posts its map (the verifier's round two);
// the follower re-imposes them over a received map and re-posts them, so the owner persists them like its own
const ownPicks = new Map<string, SecChoice | null>();
function postSync(m: SectionSyncMsg): void { try { sectionChannel?.postMessage(m); } catch { /* a closed channel */ } }
function reapplyHosts(id: string): void {
  for (const c of sectionHosts(id)) {
    const h = c as any; if (!h._it || !h._sectionEnv) continue;
    applySections(h, h._it, !!h._distillShown, h._sectionEnv);
    (h._sectionEnv as SectionEnv).afterApply?.(c);   // last: the page's own pass over what the apply changed
  }
}
/** A far host still holds a relayed question after its wait ended (it.relayNote, the kernel's relayCarried: the question went on before it
 *  could be withdrawn, or the host could not be reached to withdraw it): its OWN dim line, created once beside the sections, kept OUTSIDE
 *  them and set AFTER the section logic (inside the distill element it was hidden with that line; as a paragraph OF the brief it dropped
 *  every per-paragraph stamp). Both pages call it after applySections, the card (feed.ts) and the Needs you row (render.ts), since the row
 *  carries what the card carries (a contributor's post-merge note on PR 2124: the note rode the row's wire and key and was never drawn, so a
 *  change to it alone repainted the box with nothing visible moving). The anchor is the host's face when it has one (the card), else its
 *  sections container (the row). */
export function applyRelayNote(a: any, it: { relayNote?: string | null }): void {
  let rn = a._relayNote as HTMLElement | undefined;
  if (!rn) {
    rn = el("div", "fask-distill fask-relaynote");
    const anchor = (a._face as HTMLElement | undefined) || (a._secs as HTMLElement);
    anchor.parentNode!.insertBefore(rn, anchor.nextSibling);
    a._relayNote = rn;
  }
  const note = (it.relayNote || "").trim();
  rn.textContent = note;
  rn.style.display = note ? "" : "none";
}
/** A tree branch's disclosure (the triangle, or the reviewed-earlier row) flipped for an item, every host of the item re-applied. */
export function toggleTreeBranch(key: string, itemId: string): void {
  if (cardTreeExpanded.has(key)) cardTreeExpanded.delete(key); else cardTreeExpanded.add(key);
  reapplyHosts(itemId);
}
/** THE BUILDER'S CLICKS, DELEGATED (ui/CLAUDE.md, click-safe controls; round three of the box content PR): the badges, the line and its
 *  paragraphs, the awaited peers, the sub-goal triangles and a sub-goal's text are rebuilt on every apply, so instead of a handler on each
 *  rebuilt node they carry data-act, and each page installs this map ONCE on a stable root through actions.ts delegate (one binding that the
 *  rebuilds never touch, with the repository's press pulse on the control): the feed on each card (installed before the card's own open-modal
 *  click, so the act's stopImmediatePropagation keeps the modal shut), the chat page on #notices. `hostOf` finds the host element (the card or
 *  the row) whose remembered item the act reads. */
export function sectionActs(env: SectionEnv, hostOf: (el: HTMLElement) => HTMLElement | null): Record<string, (el: HTMLElement, ev: Event) => void> {
  const item = (el: HTMLElement) => { const h = hostOf(el) as any; return h && h._it ? { host: h as HTMLElement, it: h._it as SectionItem & BadgeItem } : null; };
  return {
    "sec-open-session": (el, ev) => { ev.stopImmediatePropagation(); if (el.dataset.sid) env.openSession(el.dataset.sid); },
    "sec-open-warns": (el, ev) => { ev.stopImmediatePropagation(); const p = item(el); if (p) env.openWarns?.(p.it, p.it.text || ""); },
    "sec-landing": (el, ev) => { ev.stopImmediatePropagation(); const p = item(el); if (p && el.dataset.uuid) env.landing(p.it, { anchorUuid: el.dataset.uuid, quote: el.dataset.quote, anchor: "work" }); },
    "sec-no-anchor": (el, ev) => { ev.stopImmediatePropagation(); const p = item(el); if (p) env.noAnchor(p.it); },
    "sec-tree": (el, ev) => { ev.stopImmediatePropagation(); const p = item(el); if (p && el.dataset.key) toggleTreeBranch(el.dataset.key, p.it.itemId); },
  };
}
function reapplyAllHosts(): void { for (const id of Array.from(hosts.keys())) reapplyHosts(id); }
/** The page's role in the sync and what it does when the choice changes by any road (the feed persists its view state). Called once at load,
 *  after the owner hydrated its map: the owner then posts the map for a follower already up. */
export function configureSectionSync(opts: { role: "owner" | "follower"; onChange?: () => void }): void {
  syncRole = opts.role; onChoiceChange = opts.onChange || null;
  if (syncRole === "owner") postSync({ kind: "map", entries: Array.from(secChoice.entries()) });
  else postSync({ kind: "hello" });
}
/** ONE item's choice (null forgets it): posted to the other document, re-applied to this document's hosts, the change callback run. */
export function setSectionChoice(id: string, choice: SecChoice | null, opts: { fromPeer?: boolean } = {}): void {
  if (choice === null) secChoice.delete(id); else secChoice.set(id, choice);
  if (!opts.fromPeer) { postSync({ kind: "set", id, choice, from: syncRole }); if (syncRole === "follower") ownPicks.set(id, choice); }
  else ownPicks.delete(id);   // the owner spoke for this item
  reapplyHosts(id);
  onChoiceChange?.();
}
/** The whole map at once (the feed's hydration, its prune to the live set, its clear on a Collapsed flip): posted as a map. A map that is
 *  already what is asked for is no change: no post, no persist (the prune runs on every feed render). `quiet` skips the re-apply of this
 *  document's hosts, for a caller whose own render applies every host next; a caller that is NOT quiet gets the re-apply even when the map
 *  did not move, since what changed may be the DEFAULT the hosts resolve against (the manager's read of the 0.17.1 fix: a Collapsed flip
 *  with no pick held found the map unchanged and returned, so a card whose payload stood alone kept the old default until its next repaint;
 *  the chat page's rows follow from the page's own settings listener either way). */
export function replaceSectionChoices(entries: Iterable<[string, SecChoice]>, opts: { fromPeer?: boolean; quiet?: boolean } = {}): void {
  const next = new Map<string, SecChoice>();
  for (const [k, v] of entries) if (SEC_CHOICES.includes(v)) next.set(k, v);
  let same = next.size === secChoice.size;
  if (same) for (const [k, v] of next) if (secChoice.get(k) !== v) { same = false; break; }
  if (same) { if (!opts.quiet) reapplyAllHosts(); return; }
  secChoice.clear();
  for (const [k, v] of next) secChoice.set(k, v);
  if (!opts.fromPeer && syncRole === "owner") postSync({ kind: "map", entries: Array.from(secChoice.entries()) });   // the map is the owner's word alone: the feed's hydration runs before it is configured as the owner, and configureSectionSync posts the map then
  if (!opts.quiet) reapplyAllHosts();
  onChoiceChange?.();
}
/** What the other document said (exported for the pins; the channel's listener calls it). */
export function receiveSectionSync(d: SectionSyncMsg | null): void {
  if (!d || typeof d !== "object") return;
  if (d.kind === "hello") { if (syncRole === "owner") postSync({ kind: "map", entries: Array.from(secChoice.entries()) }); return; }
  if (d.kind === "set") {
    if (typeof d.id !== "string" || (d.choice !== null && !SEC_CHOICES.includes(d.choice as string))) return;
    setSectionChoice(d.id, d.choice, { fromPeer: true });
    if (syncRole === "owner" && d.from === "follower") postSync({ kind: "ack", id: d.id, choice: d.choice });   // the owner's word back to the follower, and to no other owner
    return;
  }
  if (d.kind === "ack") {
    if (syncRole === "owner" || typeof d.id !== "string" || (d.choice !== null && !SEC_CHOICES.includes(d.choice as string))) return;
    if (ownPicks.has(d.id) && ownPicks.get(d.id) === d.choice) ownPicks.delete(d.id);   // acknowledged as it stands; a stale ack for an older pick spares the newer one
    return;
  }
  if (d.kind === "map") {
    if (syncRole === "owner" || !Array.isArray(d.entries)) return;
    const entries = d.entries.filter((e) => Array.isArray(e) && typeof e[0] === "string");
    for (const [id, choice] of entries) if (ownPicks.get(id) === choice) ownPicks.delete(id);   // the owner carries it: acknowledged
    const merged = new Map<string, SecChoice>(entries);
    for (const [id, choice] of ownPicks) { if (choice === null) merged.delete(id); else merged.set(id, choice); }   // this document's own picks stand over the map
    replaceSectionChoices(Array.from(merged.entries()), { fromPeer: true });
    for (const [id, choice] of ownPicks) postSync({ kind: "set", id, choice, from: syncRole });   // and reach the owner, which persists and acknowledges them
  }
}
sectionChannel?.addEventListener("message", (ev: MessageEvent) => receiveSectionSync(ev.data as SectionSyncMsg | null));
/** For the pins that join two bundles of this module over a real channel: close it, so their process can exit (Node's channel holds the loop). */
export function closeSectionSync(): void { try { sectionChannel?.close(); } catch { /* closed already */ } }
export const secChoice = new Map<string, SecChoice>();   // READ here; every write goes through setSectionChoice / replaceSectionChoices above
export function resolveSec(id: string, hasAwaitTasks = false, collapsed = false): "bg" | "summary" | "subgoals" | "tasks" | "stall" | "none" {
  // an awaiting-on-tasks card OPENS its task list by default (the user 2026-08-23: the wait is the
  // one thing to read on that card); an explicit user pick and collapsed mode still win
  return secChoice.get(id) ?? (collapsed ? "none" : hasAwaitTasks ? "tasks" : "summary");
}
// The Stalled body's text: the staller's plain-language note when the judge has written one, else the
// kernel's own mechanical reason. Never a waiting-on-the-judge placeholder — a stalled card always has
// something true to say about why it is stuck, because the kernel knew the reason before the judge was
// ever asked. That is the whole point of grounding this surface in the mechanical why.
export function stallText(st: { why: string; note?: string | null } | null | undefined): string {
  if (!st) return "";
  const note = (st.note || "").trim();
  return note || ("Nothing is moving this: romp is waiting on " + st.why + ".");
}
// Per-node EXPAND state for a CARD's inline sub-goal tree, keyed "itemId:nodeId" (the user 2026-07-08, who referred to the
// little triangle-y icons from the outline view). A node is COLLAPSED by default; membership here means the
// user clicked its triangle open. So the tree opens showing only the top level and expands on demand — like
// the modal's one-level view. Empty default = everything collapsed. (Its OWN state, not the modal's
// `collapsedNodes`, which uses the inverse sense + its own seeding.)
export const cardTreeExpanded = new Set<string>();

export const CLEARED_TIP = "you cleared this off the board — no longer needed; the box still shows whether it was done";
export function clearedTag(): HTMLElement {
  const tag = el("span", "fcleared-tag");
  tag.textContent = "cleared";
  tag.title = CLEARED_TIP;
  return tag;
}

// The parked row's plain-language story (the user 2026-08-24: a queued ask silently sat 40 minutes
// while the same card's younger items were dispatched one after another, and nothing said so). One
// quiet word on the row, the explanation on hover — a hint, never a needs-you alarm; the kernel
// retires it the instant the row gets its own delegation or any verdict (_parked_rows).
export function parkedTag(n: number): HTMLElement {
  const tag = el("span", "fparked-tag");
  tag.textContent = "parked";
  tag.title = "nothing has happened here yet — " + n + " newer ask" + (n === 1 ? " was" : "s were")
    + " dispatched past this one; this tag clears on its own dispatch or any ruling";
  return tag;
}

export function nodeStatusClass(n: AskTreeNode): string {
  if (n.cleared) return "cleared";
  if (n.status === "done") return "done";
  if (n.status === "question") return "question";
  return "open";
}

export const TREE_INDENT_EM = 1.4;

// Fill + wire the card's THREE mutually-exclusive sections — Background, Summary, Sub-goals (the user
// 2026-07-08). At most ONE open at a time (or none): clicking the open one closes it, clicking another
// switches. Each button shows only when it has content to reveal — bg present / a produced takeaway/brief /
// the goal has sub-goals — so an unavailable choice falls back to "none". The bg/summary BODIES live in
// `_secs`; the sub-goal TREE lives in `_checklist` below. stopPropagation on every toggle — the card-body
// click opens the modal.
export function applySections(a: any, it: SectionItem, distillShown: boolean, env: SectionEnv): void {
  a._distillShown = distillShown;   // remembered on the host, so a twin's re-apply from a press on another host uses its own
  a._it = it; a._sectionEnv = env;   // and its item and its page's environment, for a re-apply from another document's pick (the channel below)
  const id = it.itemId;
  const bg = distillShown && it.background ? it.background : null;
  // does the card have a sub-goal tree to show? (the root has a non-handoff child — handoffs live in the
  // delegations section). byId/root are reused by the tree builder below.
  const tree = it.tree || [];
  const byId = new Map(tree.map((n) => [n.id, n] as const));
  const root = tree.find((n) => n.id === it.itemId) || tree[0];
  // DIRECT sub-goals only — one level below (the user 2026-07-15): the button reads "3 sub-goals" for the
  // goal's immediate children, matching what the tree first shows when opened; deeper levels aren't folded
  // into this headline number — the user drills into them by expanding a child's ▶ triangle. Distinct
  // non-handoff direct children, deduped once. (Was the whole-subtree count, every depth.)
  let subCount = 0;
  if (root) {
    const seenC = new Set<string>([root.id]);
    for (const cid of (root.children || [])) {
      if (seenC.has(cid)) continue;
      seenC.add(cid);
      const n = byId.get(cid);
      if (!n || n.kind === "handoff") continue;
      subCount++;
    }
  }
  const hasSubs = subCount > 0;
  // live background tasks (the user 2026-07-13): when the card is AWAITING on tasks, the compact
  // "Awaiting task" pill joins the section toggles and expands this list (the old boxed caption is gone)
  const taskList = ((it.awaiting && it.awaiting.tasks) || []).filter(Boolean);
  // …and since slice 2 (2026-09-05) the awaited ROWS, grouped by kind — agents, commands, watches,
  // peers — so the pill shows for ANY wait the kernel can enumerate, not only a bg-task one (a wait on
  // live subagents had no clickable affordance on the card). An older kernel ships descriptions only;
  // they read as rows of the legacy kind's group, so the list never goes blank on a mixed deployment.
  const awKind = (it.awaiting && it.awaiting.kind) || "";
  const awItems: AwaitRow[] = ((it.awaiting && it.awaiting.items) || []).filter((r) => r && r.kind);
  const taskRows: AwaitRow[] = awItems.length ? awItems
    : taskList.map((d) => ({ kind: ROW_KIND_OF_LEGACY[awKind] || "commands", label: d }));
  const hasTasks = taskRows.length > 0;
  // resolve the selection (default = summary open), falling back to "none" if the chosen section is empty
  // the stall note (the user 2026-07-23) — shown whenever the kernel says romp is holding this card, with
  // or without a judge-written note, since `why` alone already answers "why is nothing happening"
  const stall = it.stalled && it.stalled.why ? it.stalled : null;
  let choice = resolveSec(id, hasTasks, env.collapsed());
  if (choice === "bg" && !bg) choice = "none";
  if (choice === "summary" && !distillShown) choice = "none";
  if (choice === "subgoals" && !hasSubs) choice = "none";
  if (choice === "tasks" && !hasTasks) choice = "none";
  if (choice === "stall" && !stall) choice = "none";
  const pick = (want: "bg" | "summary" | "subgoals" | "tasks" | "stall") => (ev: Event) => {
    ev.stopPropagation();
    // click the showing one → off; else switch to it. The setter re-applies every host of the item, so both elements of the card (T347: the
    // disclosure is the CARD's, so the board's element and the focused section's copy show the same section after a pick on either) and
    // the Needs you row in the chat page, another document (the box content round), through the channel
    setSectionChoice(id, choice === want ? "none" : want);
    if (!sectionHosts(id).length) { applySections(a, it, distillShown, env); env.afterApply?.(a); }   // a host outside the registry (a test's bare element) re-applies itself
  };
  // Background toggle — visible only when there IS background; pressed (.on) when its body is showing
  a._bgBtn.style.display = bg ? "" : "none";
  a._bgBtn.classList.toggle("on", choice === "bg");
  a._bgBtn.setAttribute("aria-pressed", choice === "bg" ? "true" : "false");
  a._bgBtn.title = choice === "bg" ? "hide the background" : "show the background";
  a._bgBody.style.display = choice === "bg" ? "" : "none";
  if (choice === "bg") a._bgBody.textContent = bg as string;
  a._bgBtn.onclick = pick("bg");
  // Summary toggle
  a._takeBtn.style.display = distillShown ? "" : "none";
  a._takeBtn.classList.toggle("on", choice === "summary");
  a._takeBtn.setAttribute("aria-pressed", choice === "summary" ? "true" : "false");
  a._takeBtn.title = choice === "summary" ? "hide the summary" : "show the summary";
  (a._distill as HTMLElement).style.display = choice === "summary" ? "" : "none";
  a._takeBtn.onclick = pick("summary");
  // Stalled toggle — same press-toggle as the others; its colour is the difference (see .fask-stallbtn)
  a._stallBtn.style.display = stall ? "" : "none";
  a._stallBtn.classList.toggle("on", choice === "stall");
  a._stallBtn.setAttribute("aria-pressed", choice === "stall" ? "true" : "false");
  a._stallBtn.title = stall
    ? (choice === "stall" ? "hide why this is stalled" : "romp is holding this — show why")
    : "";
  a._stallBody.style.display = choice === "stall" ? "" : "none";
  if (choice === "stall") a._stallBody.textContent = stallText(stall);
  a._stallBtn.onclick = pick("stall");
  // Sub-goals toggle — visible only when the goal HAS sub-goals; pressed when the tree is showing
  const subBtn = a._subBtn as HTMLElement;
  subBtn.style.display = hasSubs ? "" : "none";
  subBtn.textContent = subCount === 1 ? "1 sub-goal" : subCount + " sub-goals";
  // dim " · N parked" suffix (the user 2026-08-24): the card-level gist of the row tags. Counts ONLY
  // rows the checklist this button toggles can actually reach — the same walk, stopping at handoff
  // nodes (delegations render in their own section) and at the root (the card head, not a row) — so
  // the suffix never advertises rows no expansion reveals (review 2026-08-24; a parked ask under a
  // LIVE delegation is the modal tree's to show).
  let parkedCount = 0;
  if (root) {
    const pseen = new Set<string>([root.id]);
    const pwalk = (nid: string) => {
      const n = byId.get(nid);
      if (!n || n.kind === "handoff" || pseen.has(n.id)) return;
      pseen.add(n.id);
      if (n.parked && n.parked.n) parkedCount++;
      for (const c of n.children || []) pwalk(c);
    };
    for (const c of (root.children || [])) pwalk(c);
  }
  if (hasSubs && parkedCount) {
    const pk = el("span", "fask-subparked");
    pk.textContent = " · " + parkedCount + " parked";
    subBtn.appendChild(pk);
  }
  subBtn.classList.toggle("on", choice === "subgoals");
  subBtn.setAttribute("aria-pressed", choice === "subgoals" ? "true" : "false");
  subBtn.title = choice === "subgoals" ? "hide the sub-goals" : "show the sub-goals";
  subBtn.onclick = pick("subgoals");
  // "Awaiting task" pill (the user 2026-07-13) — visible only while live bg tasks exist; the mini swirl
  // inside keeps the "in flight" cue; pressed when the task list is showing. No preachy tooltip.
  // "Awaiting", not "Waiting on": the chat chip and timeline badge already label this exact state
  // Awaiting, and two words for one state read as two states (the user 2026-08-13).
  const taskBtn = a._taskBtn as HTMLElement;
  taskBtn.style.display = hasTasks ? "" : "none";
  // the KIND words the pill (the user 2026-08-15): "Awaiting watch", "Awaiting 3 agents" — the wait's
  // class in the visible label (tooltips are dead on the touch PWA). ONE rule with the chat chip and
  // the awaiting box (awaitWord, slice 2): one row → its word, several of a kind → count + word, mixed
  // kinds → the number alone ("Awaiting 4"); a single named peer → its name in identity colour.
  const pillPeers = (it.awaiting && it.awaiting.peers) || [];
  const pillWord = awaitWord(awKind, (it.awaiting && it.awaiting.count) ?? taskRows.length, taskRows);
  const pillLbl = a._taskLbl as HTMLElement;
  pillLbl.replaceChildren("Awaiting ");
  if (pillPeers.length === 1 && taskRows.every((r) => r.kind === "peer")) {
    const nm = el("span", "fask-waiton-name");
    nm.replaceChildren(...hostPartsNodes(pillPeers[0].host, pillPeers[0].name));
    if (pillPeers[0].color && pillPeers[0].color.bg) nm.style.color = pillPeers[0].color.bg;
    pillLbl.appendChild(nm);
  } else pillLbl.append(pillWord);
  // the wait's elapsed time rides the pill exactly as it rides the awaiting box and the working
  // narration — a stuck wait must be glanceable everywhere the state shows (the user 2026-08-23) —
  // as a stamped duration the 15 s live pass keeps moving (durNodes, the live twin of waitedSuffix)
  pillLbl.append(...env.durNodes(it.awaiting && it.awaiting.since));   // the waited time, live (durSpan)
  taskBtn.classList.toggle("on", choice === "tasks");
  taskBtn.setAttribute("aria-pressed", choice === "tasks" ? "true" : "false");
  taskBtn.title = choice === "tasks" ? "hide the tasks" : "show the tasks";
  taskBtn.onclick = pick("tasks");
  // the bg/summary/stall BODIES container shows only when one of those is open (the tree is a separate
  // element). "stall" MUST be here: stallBody lives inside _secs, so without it the Stalled toggle pressed
  // .on while its body stayed inside a display:none parent — the button "selected but nothing happened"
  // (the user 2026-07-23, the very first click on the day-old section).
  a._secs.style.display = (choice === "bg" || choice === "summary" || choice === "stall") ? "" : "none";
  // the inline sub-goal TREE (in _checklist), shown only when choice === "subgoals". Whole subtree, indented
  // by depth, with the outline's ▶/▼ disclosure triangles to fold branches (the user 2026-07-08). Same
  // inclusion rules as the modal's renderTreeNode: skip handoffs, a node reached under two parents renders
  // ONCE (dim ".repeat", not re-descended). renderTree() re-runs itself on a triangle toggle (collapse state
  // changed) without touching the buttons.
  const cl = a._checklist as HTMLElement;
  const renderTree = () => {
    cl.innerHTML = "";
    // the TASK list (the user 2026-07-13): same view/spot as the sub-goal checklist — one row per live
    // background task, a small spinning swirl as its mark (in flight), the task's own description as text
    if (choice === "tasks") {
      // …grouped by KIND since slice 2 (2026-09-05): a small dim header per group when more than one
      // shows (agents / commands / watches / peers), labels only — the chat's box carries the controls
      const groups = groupRows(taskRows);
      const peerByName = new Map(pillPeers.map((p) => [p.name, p]));
      // one row; `sub` = a NESTED row (what the agent above it is itself waiting on, kernel `waits`,
      // 2026-09-10): indented, the first under its agent led by a small dim "waiting on", the rest by its
      // blank twin so the marks align; a nested row with waits of its own says their count in its label —
      // one level drawn, like the chat's box. Labels only here; the chat box carries the controls.
      const taskRow = (r: AwaitRow, sub: "first" | "rest" | null): HTMLElement => {
        const row = el("div", "fcheck ftask" + (sub ? " ftask-sub" : ""));
        if (sub) { const on = el("span", "ftask-waits-on" + (sub === "first" ? "" : " ftask-waits-blank")); on.textContent = sub === "first" ? "waiting on" : ""; row.appendChild(on); }
        const tri = el("span", "fcheck-tri empty");
        const mark = el("span", "fcheck-mark");
        mark.appendChild(el("span", "fask-awaiting-swirl ftask-swirl"));
        const txt = el("span", "fcheck-text");
        const p = r.kind === "peer" ? peerByName.get(r.label || "") : undefined;
        if (p) {
          // a peer row names the session the way the awaiting box does: identity colour, quiet host prefix,
          // click opens the session (the standard session-chip gesture)
          txt.replaceChildren(...hostPartsNodes(p.host, p.name));
          if (p.color && p.color.bg) txt.style.color = p.color.bg;
          if (p.sid) {
            const sid = p.sid;
            txt.title = "waiting on " + p.name + " — click opens the session";
            txt.style.cursor = "pointer";
            txt.dataset.act = "sec-open-session"; txt.dataset.sid = sid;   // delegated (sectionActs)
          }
        } else txt.textContent = r.label || r.kind;
        const deeper = sub ? waitsNote(r) : "";
        if (deeper) { const dp = el("span", "ftask-deeper"); dp.textContent = " · waiting on " + deeper; txt.appendChild(dp); }
        row.append(tri, mark, txt);
        return row;
      };
      for (const g of groups) {
        if (groups.length > 1) { const gh = el("div", "ftask-group"); gh.textContent = GROUP_TITLE[g.kind] || "Other"; cl.appendChild(gh); }
        for (const r of g.rows) {
          cl.appendChild(taskRow(r, null));
          ((r.waits || []).filter((w) => w && w.kind)).forEach((w, i) => cl.appendChild(taskRow(w, i === 0 ? "first" : "rest")));
        }
      }
      cl.style.display = cl.children.length ? "" : "none";
      return;
    }
    if (choice !== "subgoals" || !root) { cl.style.display = "none"; return; }
    const rows: { node: AskTreeNode; depth: number; repeat: boolean; expandable: boolean; collapsed: boolean }[] = [];
    const seen = new Set<string>([root.id]);   // a child linking back to the root counts as a repeat (as the modal)
    const walk = (nid: string, depth: number) => {
      const n = byId.get(nid);
      if (!n || n.kind === "handoff") return;   // delegations render in their own section, not the checklist
      const repeat = seen.has(n.id);
      const expandable = !repeat && (n.children || []).some((c) => { const cn = byId.get(c); return !!cn && cn.kind !== "handoff"; });
      // DEFAULT COLLAPSED (the user 2026-07-08): the tree opens showing only the top level; a branch is
      // expanded only once its triangle was clicked (in cardTreeExpanded), just like the modal's one-level view.
      const collapsed = expandable && !cardTreeExpanded.has(id + ":" + n.id);
      rows.push({ node: n, depth, repeat, expandable, collapsed });
      if (repeat || collapsed) return;           // a repeat is dim + NOT re-descended; a collapsed branch is hidden
      seen.add(n.id);
      for (const c of n.children || []) walk(c, depth + 1);
    };
    // REVIEWED-EARLIER fold (the user 2026-08-19): direct children whose outcomes the user already
    // reviewed (kernel reviewedEarlier, from the SAME boundary the distiller scopes the takeaway with)
    // collapse behind one row, so a re-completed card presents only the new work — the old material is
    // one click away, never gone. Fresh rows first; the fold row sits below them.
    // …counting what the walk RENDERS: a handoff child is skipped by walk (delegations live in their own section), so a
    // reviewed handoff counted in the label made "3 reviewed earlier" open to two rows (the 2026-09-18 read)
    const shown = (c: string) => { const n = byId.get(c); return !!n && n.kind !== "handoff"; };
    const revKids = (root.children || []).filter((c) => shown(c) && !!byId.get(c)?.reviewedEarlier);
    const freshKids = (root.children || []).filter((c) => shown(c) && !byId.get(c)?.reviewedEarlier);
    const revOpen = cardTreeExpanded.has(id + ":reviewed");
    for (const c of freshKids) walk(c, 0);
    const freshEnd = rows.length;
    // the fold's kids sit ONE level under the fold row, their visual parent (depth 1, the modal outline's indent), never
    // flush with the fresh rows above it (the user's 2026-09-18 screenshot: the reviewed rows read as a second batch of
    // fresh ones); their own children indent from there
    if (revOpen) for (const c of revKids) walk(c, 1);
    const paintRow = ({ node: s, depth, repeat, expandable, collapsed }: typeof rows[number]) => {
      const row = el("div", "fcheck " + nodeStatusClass(s) + (s.auth ? " auth-" + s.auth : "") + (repeat ? " repeat" : ""));
      if (depth) row.style.paddingLeft = (depth * TREE_INDENT_EM) + "em";   // same per-level indent as the modal outline
      // disclosure triangle: ▶ collapsed / ▼ expanded; a non-expandable node gets a blank same-width spacer so
      // marks stay aligned. Only the triangle toggles (stopPropagation so the row click still opens the modal).
      const tri = el("span", "fcheck-tri" + (expandable ? " nav" : " empty"));
      tri.textContent = expandable ? (collapsed ? "▶" : "▼") : "";
      if (expandable) { tri.dataset.act = "sec-tree"; tri.dataset.key = id + ":" + s.id; }   // delegated (sectionActs → toggleTreeBranch re-applies every host)
      const mark = el("span", "fcheck-mark");
      // ✓ blue disc (done) / ⏸ red pause (question = blocked) / empty ring (not done) — the SAME notation as the
      // ledger checklist + the Sessions pane (the user 2026-06-24). The OPEN mark is an empty element the CSS draws as a
      // 13px hollow circle matching the done disc's size (the user 2026-07-08: the ○ glyph read too small);
      // AUTHORITATIVE keeps the glyph, .auth-* only rings it. Blocked ROLLS UP (kernel flatten, the user
      // 2026-07-11): an ancestor of a blocked sub wears the ⏸ too, so the block is visible even while the
      // branch is collapsed — its tooltip points DOWN to the real ask.
      mark.textContent = s.status === "done" ? "✓" : s.status === "question" ? "⏸" : "";
      if (s.status === "question") mark.title = s.qderived ? "a sub-goal inside it needs you: expand to find it" : "needs you";
      const txt = el("span", "fcheck-text"); txt.textContent = s.text; linkifyPrRefs(txt, env.repoOf(it.sid));
      row.append(tri, mark, txt);
      if (s.cleared) row.appendChild(clearedTag());   // the strike alone doesn't say WHY — see CLEARED_TIP
      if (s.parked && s.parked.n && !s.cleared) row.appendChild(parkedTag(s.parked.n));   // leapfrogged — see parkedTag
      // clicks match the modal tree node exactly (text → the message, checkbox → where it resolved) via the
      // SAME wireNodeZones; a dim repeat is display-only (wire=false).
      env.wireNode(it, s, mark, txt, !repeat);
      cl.appendChild(row);
    };
    rows.slice(0, freshEnd).forEach(paintRow);
    if (revKids.length) {
      // the fold row: same gesture grammar as a branch triangle — click toggles, state survives
      // re-renders via cardTreeExpanded (keyed per card), and the label carries the count. Its expanded state
      // is "expanded", NEVER "open": "open" is the not-done STATUS class (.fcheck.open .fcheck-mark draws the
      // hollow 13px ring), so the open fold wore the ring and its ✓ glyph sat low inside it, a checkmark that
      // moved down in its box the moment the fold was opened (the user's 2026-09-18 screenshot)
      const row = el("div", "fcheck freviewed" + (revOpen ? " expanded" : ""));
      const tri = el("span", "fcheck-tri nav"); tri.textContent = revOpen ? "▼" : "▶";
      const mark = el("span", "fcheck-mark"); mark.textContent = "✓";
      const txt = el("span", "fcheck-text");
      txt.textContent = revKids.length + " reviewed earlier";
      row.title = "sub-goals you reviewed before your follow-up — the update above doesn't re-present them";
      row.dataset.act = "sec-tree"; row.dataset.key = id + ":reviewed";   // delegated (sectionActs → toggleTreeBranch)
      row.append(tri, mark, txt);
      cl.appendChild(row);
    }
    rows.slice(freshEnd).forEach(paintRow);
    cl.style.display = cl.children.length ? "" : "none";
  };
  renderTree();
}

// THE STATE BADGES of the card's name row, as the Needs you box's row wears them too (plans/needs-you.md): one place for their words and
// tooltips, read by the feed card (updateAskCard) and the row builder. The peer-facing ones (awaiting a peer, a delegation's origin or
// handoff) build their nodes here, since the peer's name wears its identity colour and a quiet host prefix on both surfaces.
/** The card's section toggles in the card's order (Background · Summary · Stalled · Sub-goals · Awaiting task), the bodies they drive and
 *  the sub-goal checklist, as fresh elements: built here for the feed card and for the Needs you row alike, so neither hand-builds the other's
 *  class names or order. The caller places `toggles` on its toggles row and `secs`, `checklist` and `awaitSpin` in its body. */
export function buildSectionElements(): { toggles: HTMLElement[]; bgBtn: HTMLElement; takeBtn: HTMLElement; stallBtn: HTMLElement; subBtn: HTMLElement; taskBtn: HTMLElement; taskLbl: HTMLElement;
                                          secs: HTMLElement; bgBody: HTMLElement; distill: HTMLElement; stallBody: HTMLElement; checklist: HTMLElement; awaitSpin: HTMLElement; awaitWhy: HTMLElement } {
  const bgBtn = el("button", "fask-secbtn"); bgBtn.textContent = "Background";
  const bgBody = el("div", "fask-bg-body");
  const takeBtn = el("button", "fask-secbtn"); takeBtn.textContent = "Summary";
  const distill = el("div", "fask-distill");
  // "Sub-goals" — the THIRD mutually-exclusive section (the user 2026-07-08, moved off the footer): shows/hides
  // the inline sub-goal tree (the checklist below). Sits right of Summary; hidden when the card has no
  // sub-goals. Wired in applySections alongside Background/Summary (one open at a time, or none).
  const subBtn = el("button", "fask-secbtn"); subBtn.textContent = "Sub-goals"; subBtn.style.display = "none";
  // "Stalled" — the FIFTH mutually-exclusive section (the user 2026-07-23): romp is holding this card and
  // nothing is moving it. Same press-toggle interaction as Background/Summary, but it keeps the WORKING
  // colour in both states (see .fask-stallbtn) so it still draws the eye while open — the one section whose
  // point is that something is wrong. Filled in applySections.
  const stallBtn = el("button", "fask-secbtn fask-stallbtn"); stallBtn.textContent = "Stalled"; stallBtn.style.display = "none";
  const stallBody = el("div", "fask-stall-body");
  // "Awaiting task" — the FOURTH mutually-exclusive section (the user 2026-07-13): a compact pill (with
  // the mini spinning swirl inside) that replaces the old boxed awaiting caption when live bg TASKS exist;
  // click expands the task list in the checklist spot, same interaction as Sub-goals. Filled in applySections.
  const taskBtn = el("button", "fask-secbtn fask-taskbtn"); taskBtn.style.display = "none";
  const taskGlyph = el("span", "fask-awaiting-swirl"); taskGlyph.setAttribute("aria-hidden", "true");
  const taskLbl = el("span", "fask-taskbtn-lbl");
  taskBtn.append(taskGlyph, taskLbl);
  const secs = el("div", "fask-secs");
  secs.append(bgBody, distill, stallBody);   // the BODIES only; the toggles ride the caller's toggles row, one body shows at a time
  const checklist = el("div", "fask-checklist");
  // ⏳ AWAITING cue (the user 2026-06-29): a small romp swirl spinning in the SAME body spot the distiller line
  // will eventually fill — a completed/blocked card shows its takeaway there; a WORKING card that's awaiting
  // dispatched/delegated work shows the spinning swirl instead, a glanceable "in flight, not stalled" sign.
  // The "why" rides beside it (it was tooltip-only on the ⏳ badge). Shown only while a caption exists; see applySpin.
  const awaitSpin = el("div", "fask-awaiting"); awaitSpin.style.display = "none";
  const awaitGlyph = el("span", "fask-awaiting-swirl"); awaitGlyph.setAttribute("aria-hidden", "true");
  const awaitWhy = el("span", "fask-awaiting-why");
  awaitSpin.append(awaitGlyph, awaitWhy);
  return { toggles: [bgBtn, takeBtn, stallBtn, subBtn, taskBtn], bgBtn, takeBtn, stallBtn, subBtn, taskBtn, taskLbl, secs, bgBody, distill, stallBody, checklist, awaitSpin, awaitWhy };
}

/** The item as the swirl ladder and the badges read it (spin-caption.ts SpinItem plus the fields the distill states need). */
export interface SpinFields {
  notice?: unknown; blocked?: unknown; column?: string | null; judging?: boolean | null; provisional?: boolean | null;   // notice: the notice card's payload on the feed, read for truth alone
  working?: { since?: number | null; toolUses?: number | null } | null; sessState?: string | null;
  summary?: string | null; blockSummary?: string | null; awaiting?: SectionItem["awaiting"]; waitingOn?: unknown;
  recheck?: boolean | null; rejudging?: boolean | null;
}
/** The card's swirl for the item: spinFor over the item's fields with the distiller's pending rule, on the page's clock. One call for the
 *  card and the row, so a re-judging card (rejudging, not recheck) says "Analyzing…" on both and wears no chip on either. */
export function cardSpin(it: SpinFields, dCompleted: boolean, dBlocked: boolean, env: { nowSec(): number }): Spin {
  return spinFor(it as Parameters<typeof spinFor>[0], !it.notice && distillPending(dCompleted, dBlocked, it.summary, it.blockSummary, !!it.blocked), dCompleted, env.nowSec());
}
/** Draw the swirl box (`awaitSpin`, `awaitWhy` from buildSectionElements) for a spin: the caption, the AWAITING case's rounded box, the
 *  at-rest floor, a delegation wait naming its peers in their colours, a running duration on its own live element. */
export function applySpin(a: { _awaitSpin: HTMLElement; _awaitWhy: HTMLElement }, it: SpinFields & { awaiting?: SectionItem["awaiting"] }, spin: Spin, env: SectionEnv): void {
  const spinCaption = spin.caption, spinTip = spin.tip, awaitingBg = spin.awaitingBg;
  a._awaitSpin.style.display = spinCaption ? "" : "none";
  // The AWAITING case gets a rounded box (its distinct read); the swirl spins in every case now —
  // except the at-rest floor (`still`): quiet/unknown keep the glyph as the state anchor, stilled,
  // because spin reads as in-flight and nothing is (the user 2026-08-14).
  a._awaitSpin.classList.toggle("await-paused", awaitingBg);
  a._awaitSpin.classList.toggle("await-still", !!spin.still);
  if (!spinCaption) return;
  // a DELEGATION wait names its peers the way the "↪ from" line does (the user 2026-08-23): the
  // quiet host: prefix + the peer's identity colour, never a colourless "Awaiting peer". The
  // ladder's caption stays the fallback (older kernel payloads carry no peers).
  const awPeers = (awaitingBg && it.awaiting && it.awaiting.peers) || [];
  if (awPeers.length) {
    a._awaitWhy.replaceChildren();
    a._awaitWhy.append("Awaiting ");
    awPeers.forEach((p, i) => {
      if (i) a._awaitWhy.append(", ");
      const nm = el("span", "fask-waiton-name");
      nm.replaceChildren(...hostPartsNodes(p.host, p.name));
      if (p.color && p.color.bg) nm.style.color = p.color.bg;
      if (p.sid) {
        // the standard session-chip gesture (the handoffTo idiom): click opens the session
        nm.title = "waiting on " + p.name + " — click opens the session";
        nm.style.cursor = "pointer";
        nm.dataset.act = "sec-open-session"; nm.dataset.sid = p.sid;   // delegated (sectionActs)
      }
      a._awaitWhy.appendChild(nm);
    });
    a._awaitWhy.append(...env.durNodes(it.awaiting && it.awaiting.since));
  } else if (spin.dur) {   // the caption's running duration, live (feed-age.ts fmt "dur"; the page's own pass repaints it)
    const d = el("span", "fask-dur"); stampAge(d, spin.dur.since, "dur", false, env.nowSec(), env.relAge, env.ageTint);
    a._awaitWhy.replaceChildren(spin.dur.text, d);
  } else a._awaitWhy.textContent = spinCaption;
  a._awaitSpin.title = spinTip || spinCaption;
  // HONEST fallback (the user 2026-08-26): a peer-kind wait with no named session says WHY the
  // name is missing, instead of presenting "peer" as a style — identity is only truly unknowable
  // when the record predates identity capture or an older/offline kernel shipped the payload.
  if (awaitingBg && !awPeers.length && it.awaiting && it.awaiting.kind === "peer")
    a._awaitSpin.title += " (No session is named in this wait's record — it predates identity capture, or an older kernel shipped it.)";
}

/** THE DISTILL LINE'S PARAGRAPHS, STAMPS AND LANDINGS, after applyDistillLine set its text: a multi-item brief or summary splits into its
 *  paragraphs (distillParas, the shared gate), each stamped with its part's age (stampAge on the page's clock, repainted by the page's live
 *  pass; a part with no event time reads the static "<1m ago" the chip always showed) and linked to where its piece resolved (T220: the
 *  paragraph's own citation first, then the item's tree row's work anchor); the stale-takeaway note is prepended; and the whole line is a
 *  link to where the takeaway or brief was written, or an honest click that says no anchor was recorded. Moved here from the card
 *  (2026-09-24) so the Needs you row's line carries the same affordances through its page's landings. */
export function applyDistillLanding(a: { _distill: HTMLElement }, it: SectionItem, distillShown: string, dCompleted: boolean, dBlocked: boolean, env: SectionEnv): void {
  const dle = a._distill;
  const bp = dCompleted ? it.summaryParts : dBlocked ? it.briefParts : null;   // parts must belong to the state being shown: briefParts <-> blocked brief, summaryParts <-> takeaway
  const pAnchors = (distillShown && it.summaryAnchorsPara) || null;
  // PER-PARAGRAPH ages (the user 2026-07-24): a MULTI-item decision brief writes one paragraph per owed item IN ORDER (briefParts), so each
  // paragraph can wear the age of ITS OWN ask; the DONE side mirrors it with summaryParts. The gates (distillParas): the parts must belong to
  // the STATE being shown, multi-item only, and the paragraph count must MATCH the parts (a missing stamp beats a wrong one).
  // ONE EXTRA TRAILING PARAGRAPH is allowed and left UNSTAMPED (the user 2026-07-29): the judge prompts put whatever is still open in a last paragraph
  // of its own, which belongs to no item and carries no item's age; a bigger surplus means the mapping cannot be trusted.
  if (distillShown && ((bp && bp.length > 1) || (pAnchors && pAnchors.some(Boolean)))) {
    const split = distillParas(distillShown, bp);
    const paras = split.paras;
    const stampOk = split.stamps !== null;
    const anchOk = !!(pAnchors && paras.length === pAnchors.length);   // count drift → drop, never mis-map
    if (stampOk || anchOk) {
      dle.textContent = "";
      const nowS = env.nowSec();
      paras.forEach((p, i) => {
        const para = el("div", "fask-para");
        para.textContent = p;
        if (stampOk && i < bp!.length) {
          const age = el("span", "fask-para-age");
          if (bp![i].since) stampAge(age, bp![i].since, "plain", false, nowS, env.relAge, env.ageTint);   // stamped: the live pass moves it
          else age.textContent = env.relAge(0);   // no event time → the static "<1m ago" this chip always showed; nothing to count from
          para.append(" ", age);
        }
        // T220 first: the paragraph's own citation, with its located span riding the landing
        const cited = anchOk ? pAnchors![i] : null;
        let au: string | null = null, aq: string | undefined;
        if (cited && cited.u) { au = cited.u; aq = cited.q; }
        else if (stampOk && i < bp!.length) {
          // T153: the item's tree row carries its WORK anchor
          const pid = bp![i].id;
          const prow = pid ? (it.tree || []).find((r) => r.id === pid) : undefined;
          if (prow && prow.anchorUuid) au = prow.anchorUuid;
        }
        if (au) {
          const u = au;
          para.classList.add("fask-para-link");
          para.title = "jump to where this piece resolved";
          para.dataset.act = "sec-landing"; para.dataset.uuid = u; if (aq) para.dataset.quote = aq;   // delegated (sectionActs → env.landing)
        }
        dle.append(para);
      });
    }
  }
  // STALE-takeaway note (the user 2026-08-19): the rule lives in ./distiller-line so the test EXECUTES it. Prepended after the
  // parts-split (which rewrites the element), so it survives either rendering.
  const staleNote = distillStaleNote(!!it.summaryStale, dCompleted, distillShown);
  if (staleNote) { const sn = el("div", "fsum-stale"); sn.textContent = staleNote; dle.prepend(sn); }
  // The distiller line is a LINK: clicking it jumps to where the takeaway/brief was actually written — the biggest contiguous
  // assistant-text block in the goal's work span (it.summaryAnchorUuid; kernel _seg_best_text). stopPropagation so it doesn't also open
  // the card's modal. Without an anchor the line must still ACKNOWLEDGE the click instead of rendering as silently dead text (the user
  // 2026-07-20): the same affordance, an honest outcome (env.noAnchor: the feed toasts and files it in the error center).
  if (distillShown && it.summaryAnchorUuid) {
    dle.classList.add("fask-distill-link");
    dle.title = "jump to where this was written";
    dle.dataset.act = "sec-landing"; dle.dataset.uuid = it.summaryAnchorUuid;   // delegated (sectionActs → env.landing)
    if (it.summaryAnchorQuote) dle.dataset.quote = it.summaryAnchorQuote; else delete dle.dataset.quote;
  } else if (distillShown) {
    dle.classList.add("fask-distill-link");
    dle.title = "no anchor recorded for this card";
    dle.dataset.act = "sec-no-anchor"; delete dle.dataset.uuid; delete dle.dataset.quote;   // delegated (sectionActs → env.noAnchor)
  } else {
    dle.classList.remove("fask-distill-link");
    delete dle.dataset.act; delete dle.dataset.uuid; delete dle.dataset.quote;
    dle.removeAttribute("title");
  }
}

export const DISTILL_FAIL_RE = /^(summary|brief|stall)-failed$/;   // the distiller's own failures (judge _node_warn kinds): a chip of these alone reads "distill failed"
export const BADGE_WORDS = {
  rejudging: { text: "↩ re-judging", title: "you followed up — no longer waiting on you; the judge will resolve it or re-block it on the next pass" },
  nudgeFailed: { text: "follow-up failed", title: "romp followed up once; the response didn't resolve it and it won't be re-asked — it's waiting on you" },
  interrupting: { text: "interrupting…", title: "stop sent — waiting for this session to reach a stopping point" },
  interrupted: { text: "interrupted", title: "you stopped this session mid-turn; romp won't follow up on its own until you message it again" },
} as const;

export interface BadgeItem {
  itemId?: string; sid?: string; text?: string | null;
  recheck?: boolean | null; rejudging?: boolean | null; nudgeFailed?: boolean | null; doneConfirming?: boolean | null;
  warns?: { kind: string; t: number; msg: string; detail: string }[] | null;   // judge-stamped anomalies → the yellow "warning" chip
  failLog?: { t: number; line: string; model: string; note: string }[] | null;   // the summarizer's failed attempts: the chip's hover evidence
  nudged?: { count: number; times: number[] } | null;
  interrupting?: boolean | null; interrupted?: boolean | null;
  waitingOn?: { peerSid?: string; name: string; color?: { bg: string; fg: string } | null; inCycle?: boolean; kind?: string; since?: number | null } | null;
  origin?: { peer: string; peerSid: string; peerHost?: string; color?: { bg: string; fg: string } | null; live?: boolean } | null;
  handoffTo?: { peer: string; peerSid: string; peerHost?: string; color?: { bg: string; fg: string } | null } | null;
  delegTracked?: { sid: string; name: string; host?: string; color?: { bg: string; fg: string } | null }[] | null;   // a tracked delegation's recipients (the ONE card, homed under the delegator)
}

/** The badges the card's name row shows for this item, in the card's order, as fresh elements, with the card's own conditions and
 *  precedence: a delegation's origin; "↩ re-judging" on a targeted follow-up (recheck) only, and not while the swirl already says
 *  "Analyzing…" (a plain reply after a block is `rejudging`: it moves to Working with the swirl as its ONLY cue, never a chip beside it);
 *  "done, confirming"; "follow-up failed", which outranks both interrupt words; "interrupting…" then "interrupted", never together; the
 *  "warning" chip (or "distill failed" when every warn is the distiller's), its hover the attempt history or the last message, its click
 *  the page's detail; "Awaiting <peer>" (or "Handed off to", or "Deadlock") with the wait's live duration; and "↪ delegated to". The
 *  caller hands the spin caption it drew for the item (cardSpin), so both pages apply the one rule. */
export function stateBadges(it: BadgeItem, env: Pick<SectionEnv, "durNodes" | "openSession" | "clockHM" | "openWarns" | "workDot">, spinCaption: string | null = null): HTMLElement[] {   // openWarns optional: see SectionEnv
  const out: HTMLElement[] = [];
  const badge = (cls: string, text: string, title: string) => { const b = el("span", cls); b.textContent = text; b.title = title; return b; };
  // ↪ PROVENANCE, one anchor as the card always drew it: "↪ from <sender>" for a courier handoff (planted by a peer's message; click opens
  // the sender; "↪ from" in dim gray, the peer name in the bold session-name style in its own identity colour, the user 2026-06-16; a
  // federated sender wears the quiet "host:" prefix), STACKED with " · ↪ delegated to <peer>" for a sender-side handoff (the user 2026-08-24)
  // and " · ↪ delegated to <a>, <b>" for a tracked delegation's recipients with the board's live dot (the feed's workDot): origin and the
  // delegations are different facts about one card, so they stack rather than replace (review 2026-08-24). Absorbed (the sender's linked
  // entry closed): the whole badge dimmed, provenance rather than an active handoff, and the title warns that a clear takes the linked entry
  // with it (the user 2026-08-16). Each recipient carries its own click; the anchor's own click opens the sender, or the recipient when there
  // is no sender (the verifier's round two on PR 2124: the separator and the one-anchor rendering had been lost in the move here).
  const hasOrigin = !!(it.origin && it.origin.peer), hasHandoff = !!(it.handoffTo && it.handoffTo.peerSid), hasTracked = !!(it.delegTracked && it.delegTracked.length);
  if (hasOrigin || hasHandoff || hasTracked) {
    const og = el("a", "fask-origin" + (hasOrigin && it.origin!.live === false ? " fask-origin-absorbed" : ""));
    let had = false;
    if (hasOrigin) {
      const o = it.origin!;
      const pre = el("span", "fask-origin-pre"); pre.textContent = "↪ from ";
      const peer = el("span", "fask-origin-peer"); peer.replaceChildren(...hostPartsNodes(o.peerHost, o.peer)); if (o.color) peer.style.color = o.color.bg;
      og.append(pre, peer);
      og.title = (o.live === false ? "delegated by " + o.peer + "; their linked entry closed with this card" : "delegated by " + o.peer + " — clearing this card also clears their linked entry") + " · click opens the session";
      og.dataset.act = "sec-open-session"; og.dataset.sid = o.peerSid;   // delegated (sectionActs)
      had = true;
    }
    if (hasHandoff) {
      const h = it.handoffTo!;
      if (!had) { og.title = "delegated to " + h.peer + "; their result checks this card off · click opens the session"; og.dataset.act = "sec-open-session"; og.dataset.sid = h.peerSid; }
      const pre = el("span", "fask-origin-pre"); pre.textContent = (had ? " · " : "") + "↪ delegated to ";
      const peer = el("span", "fask-origin-peer"); peer.replaceChildren(...hostPartsNodes(h.peerHost, h.peer)); if (h.color && h.color.bg) peer.style.color = h.color.bg;
      peer.title = "delegated to " + h.peer + "; their result checks this card off · click opens the session"; peer.style.cursor = "pointer";
      peer.dataset.act = "sec-open-session"; peer.dataset.sid = h.peerSid;   // the recipient's own click (the nearest act wins)
      og.append(pre, peer);
      had = true;
    }
    if (hasTracked) {
      const ds = it.delegTracked!;
      if (!had) { og.title = "a tracked handoff: the work runs with " + ds.map((d) => d.name).join(", ") + " and reports back to this card"; }
      const pre = el("span", "fask-origin-pre"); pre.textContent = (had ? " · " : "") + "↪ delegated to ";
      og.append(pre);
      ds.forEach((d, i) => {
        if (i) og.append(", ");
        const peer = el("span", "fask-origin-peer");
        peer.replaceChildren(...hostPartsNodes(d.host, d.name));
        if (d.color && d.color.bg) peer.style.color = d.color.bg;
        env.workDot?.(peer, d.name);
        peer.title = "a tracked handoff: the work runs with " + d.name + " and reports back to this card · click opens the session";
        peer.style.cursor = "pointer";
        peer.dataset.act = "sec-open-session"; peer.dataset.sid = d.sid;   // delegated (sectionActs)
        og.append(peer);
      });
    }
    out.push(og);
  }
  if (it.recheck && spinCaption !== "Analyzing…") out.push(badge("fask-followedup", BADGE_WORDS.rejudging.text, BADGE_WORDS.rejudging.title));
  if (it.doneConfirming) out.push(badge("fask-doneconfirming", "done, confirming", "ruled done — it files under Completed once the session has moved on; a follow-up before then reopens it in place"));   // (the user 2026-07-24): an indicator, never a move
  if (it.nudgeFailed) {
    const b = badge("fask-nudgefailed", BADGE_WORDS.nudgeFailed.text, BADGE_WORDS.nudgeFailed.title);
    // the chip label says "follow-up failed"; its tooltip carries the EVIDENCE — romp did follow up, and when (the user 2026-07-02)
    if (it.nudged && it.nudged.times && it.nudged.times.length) b.title = `romp followed up ${it.nudged.count}× (${it.nudged.times.map(env.clockHM).join(", ")}); the response didn't resolve it and it won't be re-asked — it's waiting on you`;
    out.push(b);
  }
  if (it.interrupting && !it.nudgeFailed) { const b = badge("fask-interrupting", BADGE_WORDS.interrupting.text, ""); setTip(b, BADGE_WORDS.interrupting.title); out.push(b); }   // styled tip (tip.ts), not a native title
  if (it.interrupted && !it.interrupting && !it.nudgeFailed) out.push(badge("fask-interrupted", BADGE_WORDS.interrupted.text, BADGE_WORDS.interrupted.title));
  if (it.warns && it.warns.length) {
    // "warning" chip: a judge stamped an anomaly on this goal — the latest msg on hover, detail on click. A BUTTON so it is focusable.
    const allDistill = it.warns.every((w) => DISTILL_FAIL_RE.test(w.kind));
    const lbl = allDistill ? "distill failed" : "warning";
    const chip = el(env.openWarns ? "button" : "span", "fask-warnchip"); chip.textContent = it.warns.length > 1 ? `${lbl} ×${it.warns.length}` : lbl;
    // hover = the attempt history when one exists (the user 2026-08-18, who wanted a model's repeated failure visible at a glance, since switching it is then the obvious fix)
    chip.title = (it.failLog && it.failLog.length ? it.failLog.map((f) => `${env.clockHM(f.t)} tried ${f.model} — ${f.note}`).join("\n") : it.warns[it.warns.length - 1].msg)
      + (env.openWarns ? "\n— click for what happened and why" : "");   // a page with no destination promises no click (the chat page: the hover is the whole evidence)
    if (env.openWarns) chip.dataset.act = "sec-open-warns";   // delegated (sectionActs → env.openWarns with the host's freshest item)
    out.push(chip);
  }
  const wo = it.waitingOn;
  if (wo) {
    const b = el("span", "fask-waiton" + (wo.inCycle ? " fask-waiton-cycle" : ""));
    const pre = el("span", "fask-waiton-pre"); pre.textContent = wo.inCycle ? "Deadlock " : wo.kind === "delegate" ? "Handed off to " : "Awaiting ";
    const name = el("span", "fask-waiton-name"); name.textContent = wo.name; if (wo.color && wo.color.bg) name.style.color = wo.color.bg;
    b.append(pre, name);
    const dur = env.durNodes(wo.since); if (dur.length) { const w = el("span", "fask-waiton-dur"); w.append(...dur); b.appendChild(w); }
    b.title = wo.inCycle ? "MUTUAL WAIT — this session and " + wo.name + " are each waiting on the other (a deadlock); auto-nudge surfaces it instead of nudging"
      : wo.kind === "delegate" ? "this session handed work to " + wo.name + " and acts when the result comes back — not stalled, so auto-nudge skips it"
      : "this session has an unanswered message out to " + wo.name + " — waiting on its reply, not stalled, so auto-nudge skips it";
    out.push(b);
  }
  return out;
}
