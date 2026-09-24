// romp feed — a stream of rounded "deliverable cards" on a backdrop. Each card is
// ONE deliverable (a turn's "did" phrase) from some session, newest on top. The
// session name links to that session's tab; the checkbox dismisses the card; the
// message expands to a (pre-generated) action paragraph.
//
// Rendering is KEYED + INCREMENTAL: cards are kept alive across the host's live
// pushes and updated in place — never torn down — so hovering one doesn't flicker
// when the sessions stream new deliverables in. A kept card is REPAINTED only when
// its inputs changed (feed-card-gate.ts): the kernel re-sent it, a board-level input
// it reads moved, a gesture touched it, or the 15 s live pass aged it. Its column and
// order are re-applied on every render regardless.
import { distillText, distillInputs, applyDistillLine, distillPending, distillStaleNote, distillParas } from "./distiller-line";
import { openContextMenu, CtxItem } from "./ctx-menu";   // the one menu builder (the v0.16.0 tidy): the card menu's card, dismissal and keys
import { flipNeeded } from "./feed-flip";
import { delegate } from "./actions";
import { paintHeld, paintReleased, publishPaneHidden } from "./paint-gate";
import { linkifyPrRefs, setLinkedText, installPrLinkOpener } from "./pr-links";
import { cardInputsKey, cardNeedsUpdate, type GateEnv } from "./feed-card-gate";
import { spinFor, awaitWord, groupRows, waitsNote, GROUP_TITLE, ROW_KIND_OF_LEGACY, type AwaitRow } from "./spin-caption";
import { onlyTag, matchesOnly } from "./only-filter";
import { searchMatches, searchSids } from "./feed-search";
import { TagLens, lensAll, lensLabel, lensVisible, lensUnions } from "./tag-lens";
import { openTagMenu, tagMenuButton, syncTagFilter, tagChip } from "./tag-menu";
import { SessionViews } from "./session-views";
import { freezeDiff, contentSig } from "./feed-freeze";
import { hostNameNodes, hostPartsNodes, hostIsDown, hostOf, bareId } from "./host-prefix";
import { extHoverMatches } from "./card-key";
import { provenanceRows, provenanceGroupRows, rootStart, type ProvFmt, type ProvRow } from "./provenance";
import { ageColorReadable } from "./age-color";
import { liveNow, liveRefresher, refreshAges, stampAge, relAge } from "./feed-age";   // relAge: the age words, shared with the chat page's Needs you row (card-sections.ts stamps through the page's environment)
import { badgeCardHalf, clearBoundaryNotices, frameCardsUnknown, sdkProblemNotices, syncNotices, type CardsUnknown,
  type ClearNoticeRow, type SdkNoticeRow, type SyncNoticeRow } from "./badge-mirror";
import { initStrip } from "./strip";
import { installSettingsSync, loadSettings, onExternalSettingsChange } from "./settings";
import { applyTheme } from "./theme";
import { hostsGear, openGear } from "./gear-host";
import { canPreview } from "./preview";
import { sanitizeMd } from "./md-sanitize";
import { noticeBodyNodes, noticeAttachmentNodes } from "./notice-face";   // the one face the feed card, its modal and the chat box share
import { applySections, resolveSec, stallText, secChoice, cardTreeExpanded, clearedTag, parkedTag, nodeStatusClass, TREE_INDENT_EM, CLEARED_TIP, registerSectionHost,
         replaceSectionChoices, configureSectionSync, buildSectionElements, cardSpin, applySpin, applyDistillLanding, stateBadges, DISTILL_FAIL_RE, sectionActs,
         applyRelayNote, type AskTreeNode, type NodeLogRow, type SectionEnv, type SecChoice, unregisterSectionHost } from "./card-sections";   // the card's sections, one builder with the chat box's row (plans/needs-you.md)
import { initFileView, setFileViewIdentity, hostStub } from "./file-view";
import { initFileBrowse, openFileBrowse } from "./file-browse";
import { VIEW_STATE_KEY, parseViewState, serializeViewState, pruneViewState, capViewState, type FeedViewState, threadKey, threadKeys } from "./feed-view-state";
import { inInputEvent } from "./input-event";
import { focusedEntries, focusedCardCount } from "./feed-focus";   // the focused-session section's pure pick (T347)
import { FEED_BOARD, columnOf, columnTable, feedColumns, isNeedsYou, adoptBoards, boardOf, boardById, knownBoards, type Board, type FeedCategory } from "./board-def";   // the feed as one board definition (plans/card-boards.md, phase one)
import { wireTip, setTip, pruneTip } from "./tip";
import { perfFrameHandler } from "./perf-telemetry";
import { listenForFrames } from "./frame-listener";

// (The standalone-deliverable "FeedItem" subsystem was REMOVED 2026-07-07: the kernel had emitted
// items: [] permanently — goal cards are the only feed unit — so its types, renderers, expand/detail
// machinery, and CSS were all unreachable. Payload-contract audit.)

// Asks inbox (the DEFAULT view; request registry REQUESTS.md): one persistent
// card per OPEN ask of the user's, sorted into THREE state columns derived from each
// ask's newest link. Clear (the user-only, binary) removes it — inbox-zero. The
// deliverables stream is the safety-net behind the header toggle.
interface DecisionBrief { context: string; question: string; options: string[] | null; sid: string; t: number }
interface AskQuestion { reply_id: string; sid: string; name: string; t: number; brief: DecisionBrief | null; qtype?: "decision" | "action" | "idea"; nodeId?: string }
// One node of the ask's request DAG (flat list, root first; nest via children ids;
// a node under two parents appears in both → render twice, dim the repeat).
// One verdict-log row (kernel _node_log_rows): who did what to this node, when, and — when the
// parse resolves it — the exact chat turn to jump to (evT time-nav fallback otherwise).
interface AskItem {
  sessionStarted?: { why: string; parent: string | null } | null;   // T319: the root is work the SESSION started (a workflow, an
                                                                    //   agent, its own thread) with no request of the user's to nest
                                                                    //   under; the face says so in one line instead of posing as an ask
  itemId: string; sid: string; name: string; color: { bg: string; fg: string } | null;
  text: string; t: number; live: boolean;
  turnId: string;
  trgb: [number, number, number];
  board?: string;                                  // the board model (plans/card-boards.md, phase two): the kernel writes "feed" on every card it builds
  category?: string;                               // the board's category id, the kernel's raw column value for the feed; absent from an older kernel's frame
  column: FeedCategory;                            // RAW kernel value (build_feed): working/needs_input/completed. askColumn() maps it to the local Column. NOT "asks": that was a stale lie that silently broke `it.column === "asks"` checks.
  followupPending?: boolean;                       // you followed up on a settled card → optimistically reopened, awaiting the judge's re-file (kernel)
  followupAt?: number | null;                      // when that follow-up/continue went — the latched button's honest age (T150)
  doneConfirming?: boolean;                        // the done verdict is in, only the settle event is pending → steady "done, confirming" chip on the Working card; placement deliberately does NOT move early (no working↔done flicker) (kernel build_feed ← judge rollup confirming export; the user 2026-07-24)
  recheck?: boolean;                               // soft-block you answered with a TARGETED follow-up → de-urgented (dotted), moved to Working, dropped from the "need input" count, until the judge resolves or re-blocks it (kernel build_feed; the user 2026-06-27)
  rejudging?: boolean;                             // soft-block + a PLAIN thread reply after it → moves to WORKING while the reply is in flight (echo/open turn), with a "Re-judging…" swirl; returns to Needs-You on its own if the judge leaves it blocked (kernel build_feed; the user 2026-07-02, immediate)
  nudgeFailed?: boolean;                           // the ONE auto-nudge on this stalled goal didn't resolve it → red "follow-up failed" chip (renamed off "stalled" 2026-07-23 — that word is the yellow romp-holding section's now); the failure also records a BLOCK verdict, so the card reaches Needs-you via the normal ladder (kernel _mark_nudge_failed, 2026-07-07)
  stalled?: { why: string; since: number; note?: string | null; blocked?: boolean } | null;
  working?: { since?: number | null; toolUses?: number | null } | null;   // open-turn narration: tool count + start (kernel _open_turn_progress; the user 2026-08-13)   // romp's nudge gate is HOLDING this working card behind a reviver that isn't retiring, so nothing is moving it (kernel _stalled_goals; the user 2026-07-23). `why` = the kernel's mechanical reason, always present; `note` = the staller's plain-language version, null until the judge writes one. Drives the Stalled section button — its own colour, since this is romp being the bottleneck, not you
  interrupting?: boolean;                          // a user interrupt is IN FLIGHT (dispatched, not yet settled) → steady "interrupting…" badge from the click until it settles, THEN yields to `interrupted` — never flickering to "working" in between (kernel build_feed; the user 2026-07-07)
  interrupted?: boolean;                           // the user STOPPED this session mid-turn and hasn't messaged it since → "interrupted" badge; its quiet is user-chosen, auto-nudge holds off until their next message (kernel build_feed; the user 2026-07-05)
  retrying?: { since?: number | null; count?: number } | null;   // the OPEN turn is inside an api-retry storm (kernel _session_retrying, live backend state) → "⚠ retrying since HH:MM" chip on the working card; without it a storm reads as plain healthy Working (the user 2026-07-09)
  autoFiled?: boolean;                             // settled → moved to COMPLETED by the auto-filing rule (keeps the green ring)
  explicitDone?: boolean;                          // every path explicitly DONE-stamped → blue ring (blue+green when settled agrees)
  // the owning session is live-blocked (permission/picker, or stopped on an API error) ON this card's
  // work → the card itself files under BLOCKED (the user's ruling 2026-06-11; apiError 2026-06-16).
  blocked?: { state: string; what: string; status?: number; text?: string;
              tooLong?: boolean;   // apiError: a "prompt is too long" error (on you → compact) vs a transient API error
              spendLimit?: boolean;   // apiError: a monthly spend cap (on you → raise it, never auto-retried; the user 2026-07-14)
              modelLimit?: boolean;   // apiError: this session's MODEL is out of allowance (on you → switch model or add credits; the user 2026-08-01)
              refusal?: boolean;   // apiError: the model's safeguards refused the prompt itself (on you → rewrite it or drop the thread; never auto-retried — deterministic on the same input, the user 2026-08-15)
              mode?: string; login?: string; since?: number;   // judgeAuth adds these: which billing its judges ride ('key'|'login') + the first refusal time — romp can't analyze the session until the credential is fixed (the user 2026-08-12)
              capOffer?: { resetsAt: number; window?: string };   // apiError: login-billed session dead on the account's cap + a key on hand → the explicit switch OFFER; the pick is yours alone, both directions (2026-08-30)
              toName?: string; toSid?: string };  // parkedHandoff adds to* (the held-mail flavour left 2026-09-19: a notice card now)
  // a NOTICE CARD (T370, plans/notice-cards.md): a producer's card the kernel made without a judge; the flavour object
  // discriminates the family the way blocked.state does the kernel-made ones. The face shows the title (text), the producer
  // beside the session, the body (markdown through the sanitizer), the attachment (an image inline, pinned as posted), and
  // the action buttons the kernel executes against its allowlist; Clear dismisses it through cleared.jsonl like every card
  notice?: { producer: string; key: string; rev: number; body: string;
             attachment: { path: string; kind: string | null; allowed: boolean; why: string; pin: string | null } | null;
             actions: { label: string; kind?: string; route?: string; body: Record<string, unknown> }[];   // of a KIND the kernel defines (send, quarantine); route: an older frame's spelling of send
             expiresAt: number | null; dismissOnAction: boolean; acted?: boolean } | null;   // acted: the one-shot action ran (a card back from Undo carries no actions)
  summary?: string | null;                         // distiller's key takeaway for a COMPLETED goal → the done card's one auto-written line (kernel asks.append); null until produced
  distillState?: "completed" | "blocked" | null;   // the GENUINE resolution state the distiller line keys on, so the brief/takeaway rides the real block instead of the transient `column` (which recheck/rejudging flicker to working) — the user 2026-07-21; absent from older/remote payloads → fall back to column
  blockSummary?: string | null;                    // block-distiller's decision brief for a BLOCKED goal → the blocked card's one auto-written line (kernel 466393c); null until produced
  relayNote?: string | null;   // a far host still holds a relayed question after its wait ended (kernel relayCarried) → its own dim line under the brief, never a brief paragraph
  briefParts?: { id?: string; since: number }[] | null;   // MULTI-item brief: one {id, since} per paragraph IN ORDER (judge briefParts) → per-paragraph "Nm ago" stamps; null/absent = single ask, the card header's age is the stamp (the user 2026-07-24)
  summaryParts?: { id?: string; since: number }[] | null;   // the DONE twin: per-paragraph done-event stamps for a takeaway the distiller split by <completed-items> (the user 2026-07-24)
  summaryStale?: boolean;                          // the user followed up AFTER the shown takeaway (kernel: followupAt > distilledMt) → the summary section carries the stale note until the re-distill lands (the user 2026-08-19)
  background?: string | null;                      // distiller's BACKGROUND section: re-orientation for a reader who forgot the thread → the card's collapsed-by-default section above the takeaway (the user 2026-07-02)
  summaryAnchorUuid?: string | null;               // click the summary line → the completion turn's wrap-up block (kernel build_feed completed pin; cited/latest-prose fallbacks — the user 2026-07-14)
  summaryAnchorQuote?: string | null;              // the distiller's verbatim supporting sentence, pre-located in the cited atom (T218) — the landing scrolls to and highlights it; null keeps the whole-message landing
  summaryAnchorsPara?: ({ u: string; q?: string } | null)[] | null;   // per-paragraph landings (T220, the user's ruling): aligned to the takeaway's paragraphs; null entry = that paragraph falls back to the whole-summary landing
  warns?: { kind: string; t: number; msg: string; detail: string }[] | null;   // judge-stamped anomalies (judge _node_warn → kernel build_feed): yellow "warning" chip; click opens the detail modal (the user 2026-07-02)
  failLog?: { t: number; line: string; model: string; note: string }[] | null;   // the summarizer's failed ATTEMPTS on this card (judge _fail_log): when, which line, which MODEL, the literal error — the chip's hover history + the modal's "What was tried" (the user 2026-08-18, who needed to SEE "tried opus — 529" ×3 to know switching the model would fix it)
  nudged?: { count: number; times: number[] } | null;   // auto-nudge HISTORY (kernel _nudge_times): how many times romp followed up + when — the stalled chip's evidence (tooltip + modal line, the user 2026-07-02)
  warnRows?: { t: number; judge: string; err: string; note?: string; debug?: { input?: string; reply?: string } }[] | null;   // DEBUG MODE only (romp debug on): every judge failure touching this card (kernel _card_warn_rows) → "Warnings (debug)" modal section; rows captured in debug carry the failing call's input + reply (the user 2026-07-09)
  origin?: { peer: string; peerSid: string; peerHost?: string; color: { bg: string; fg: string } | null; live?: boolean } | null;
  handoffTo?: { peer: string; peerSid: string; peerHost?: string; color?: { bg: string; fg: string } | null } | null;  // sender-side handoff provenance (the user 2026-08-24): this card IS a top-level "↪ delegated to <peer>" tracking node — the kernel titles it with the WORK and ships the delegation here, the mirror of origin's "↪ from"; click opens the recipient
  satellite?: boolean | null;                        // tracked delegation (the user 2026-08-24): this card is the recipient-side copy of a delegator-homed primary — off the default board; the session filter still reaches it (nothing runs in secret)
  delegTracked?: { name: string; host?: string; sid: string; color?: { bg: string; fg: string } | null }[] | null;  // tracked delegation PRIMARY: the recipient identities whose live status this one card carries  // courier handoff: planted by a peer's message → "↪ from <peer>"; peerHost = a FEDERATED sender's host, rendered as the quiet "host:" prefix (absent on older payloads / local senders). live = the sender's linked entry is still OPEN; false → the badge is PROVENANCE, dimmed (the completed-column merge, the user 2026-08-16)
  waitingOn?: { peerSid: string; name: string; color: { bg: string; fg: string } | null; inCycle: boolean; kind?: string; since?: number } | null;  // unanswered msg out to a live peer → "Awaiting <peer>" chip, or "Handed off to <peer>" when kind is "delegate" (peer name in native colour, no emoji; kernel _wait_for_graph; the user 2026-06-22 / 2026-07-25). since = when the unanswered ask was sent → the chip's elapsed readout (the user 2026-08-23)
  awaiting?: { why?: string | null; kind?: string | null; since?: number | null; count?: number | null; tasks?: string[] | null;
               items?: AwaitRow[] | null;   // the awaited ROWS grouped by kind (slice 2, 2026-09-05) — the pill lists them; count = how many (T225)
               peers?: { name: string; host?: string; sid?: string; color?: { bg: string; fg: string } | null }[] | null } | null;   // peers: delegation wait → the box names them in identity colour (the user 2026-08-23)   // AWAITING flavor: held in Working, ⏳ awaiting badge — waiting on dispatched/delegated work (agents/subagents/a build), NOT on you (kernel build_feed; the user 2026-06-22). The peer case rides waitingOn; this carries the generic "why". `tasks` = live bg-task descriptions (the user 2026-07-13): present → the compact "Awaiting task" pill (expands the list, like Sub-goals) replaces the boxed why. since = the wait's own event time → the box/pill elapsed readout (the user 2026-08-23)
  groupTitle?: string;                             // host: this ask shares a typed turn with siblings → the group's title
  groupN?: number;                                 // host: sibling count for that turn (>1 ⇒ fold into one group card)
  provisional?: boolean;                           // a LIVE-PROMPT placeholder (kernel _provisional_card): the session is working an in-progress turn the planner hasn't classified yet. No goal node (empty tree) — dim, non-interactive, no clear/nudge/modal; replaced by the real card once the planner places the segment.
  judging?: boolean;                               // the turn has SETTLED and the judge's pass is due/in flight → the swirl chip says Analyzing… — on a provisional card while the planner's classify is pending (the user 2026-07-12), and on a REAL working card while the closer's verdict is (the settle→verdict gap, the user 2026-07-13); an open turn stays the honest Working…
  notify?: boolean | null;                         // per-card bell (the user 2026-07-28): the kernel fires an OS notification when THIS card enters needs_input/completed. EFFECTIVE state (card override > session override > the master bell's default, 2026-08-09) — with the master on, every card arrives armed unless muted. True/absent, never false
  tree: AskTreeNode[];                             // the ask's DAG, rendered as a tree in the expanded body
}
// A GROUP = N sibling asks minted by ONE typed turn (shared turnId), folded into a
// single card. DERIVED at render time from the current asks, so membership shrinks
// as the user clears members (a lone survivor falls back to a normal single card).
interface AskGroup {
  turnId: string; title: string; members: AskItem[];   // members sorted chronologically
  name: string; color: { bg: string; fg: string } | null; sid: string;   // shared asking session
  t: number; trgb: [number, number, number]; column: Column; live: boolean;
}
let asks: AskItem[] = [];
let viewAsks = true;           // asks inbox is the default; deliverables behind the toggle
const expandedAsks = new Set<string>();
// Per-node collapse state, key = askId + ":" + nodeId. INVERTED sense: a node is
// EXPANDED (its history rows AND its descendant subtree visible) by default;
// collapsing it adds the key here and hides its WHOLE subtree. Empty set = the
// tree is fully open, which matches the always-expanded look it had before
// collapse was deepened to cover children, not just rows.
const collapsedNodes = new Set<string>();
// Per-node LOG-story expand state (the user 2026-07-20), key = askId + ":" + nodeId. Default collapsed:
// an open sub shows a one-line "asked you · 2h ago" gist; membership here expands the full
// block/unblock history. Progressive disclosure — same key shape as collapsedNodes, survives re-renders.
const nodeLogOpen = new Set<string>();
let fullscreenAskId: string | null = null; // ask itemId OR group key "g:<turnId>" shown in the modal (single-click)
let modalRenderedId: string | null = null; // last target the modal body was built for → reset body cache on change
// Per-sub FOLLOW-UP target (the user 2026-06-17): a blocked sub-node's "↳ follow up" re-points the (robust,
// outside-the-tree-body) footer composer at THAT sub instead of the whole card, so the answer files under it
// and unblocks just that branch. null = the composer follows up on the whole card (the default).
let followupSub: { itemId: string; title: string } | null = null;
// Set by renderModal (captures the footer composer); called from a tree node's "↳ follow up" — kept as a
// module ref (not threaded through renderTreeBody) so the per-node button reads the CURRENT opener at click time.
let openSubFollowUp: ((itemId: string, title: string) => void) | null = null;
let hoverAskId: string | null = null;      // transient hover focus (white border + previewed journey)
let pinnedAskId: string | null = null;     // double-click PIN (persists after hover-leave)
// KEYBOARD-NAV cursor (the user 2026-07-01): "" = mouse mode; "cards" = an arrow cursor over cards; "card" =
// focus is inside one card, arrows step its clickable elements. Armed when the shell hands the feed keyboard
// focus (Alt+Arrow). Reuses the mouse hover + click code paths so behavior can't drift. See the kb* block below.
let kbMode: "" | "cards" | "card" = "";
let kbCardEl: HTMLElement | null = null;    // the card the cursor is on
let kbEls: HTMLElement[] = [];              // that card's clickable elements (in "card" mode)
let kbElIdx = -1;
// effective focus = hover ?? pinned; the white border + lit timeline journey follow it.
function applyFocus() {
  const eff = hoverAskId ?? pinnedAskId;
  for (const [id, card] of askEls) card.classList.toggle("focused", id === eff);
  for (const [tid, card] of groupEls) card.classList.toggle("focused", "g:" + tid === eff);
  // the focused-session section's copies (T347) light with the card below — one card, two elements
  for (const [id, card] of fsAskEls) card.classList.toggle("focused", id === eff);
  for (const [tid, card] of fsGroupEls) card.classList.toggle("focused", "g:" + tid === eff);
}
const askEls = new Map<string, HTMLElement>();
// The FOCUSED SESSION section's own element caches (T347): the section duplicates the focused session's
// cards above the board, so each card there is a SECOND element, keyed "f:a:<itemId>" / "f:g:<turnId>" and
// cached here, never in askEls/groupEls — the board's reconcile, its FLIP capture and every lookup by a
// card's bare key see only the copy below, so nothing below moves because the section did.
const fsAskEls = new Map<string, HTMLElement>();
const fsGroupEls = new Map<string, HTMLElement>();
/** Every element on the page that renders this card: the board's, and the focused section's copy when the
 *  section shows it. Clear, its 180 ms finish and Undo resolve by ITEM through these, never by one element,
 *  so a gesture on either copy reaches both (the review of T347: Clear on a copy left the card below). */
function cardTwins(itemId: string): HTMLElement[] {
  const out: HTMLElement[] = [];
  const a = askEls.get(itemId); if (a) out.push(a);
  const f = fsAskEls.get(itemId); if (f) out.push(f);
  return out;
}
function groupTwins(turnId: string): HTMLElement[] {
  const out: HTMLElement[] = [];
  const g = groupEls.get(turnId); if (g) out.push(g);
  const f = fsGroupEls.get(turnId); if (f) out.push(f);
  return out;
}
// Optimistically-cleared item ids: Clear animates a card out + posts askClear, but a feed push that
// arrives BEFORE the kernel processes the clear still lists the card — re-rendering it strips the
// `.dismissing` class (updateAskCard resets className) so it pops back, then a later push drops it. We
// suppress those ids from incoming payloads until the kernel's payload confirms the clear (no longer
// lists them), so a stale push can't resurrect a card mid-dismiss (the user 2026-06-19).
const pendingCleared = new Set<string>();
// A LIFO of recently-cleared card batches, holding the AskItem data itself (a single Clear pushes [it]; a
// Clear-all pushes the whole batch). "Undo" pops the latest and re-inserts those cards IMMEDIATELY —
// optimistic restore — so the card reappears on click instead of waiting on the kernel round-trip + next feed
// build. Mirrors the kernel's _undo_clear (restores the most-recent clear batch). (the user 2026-06-27.)
const clearedStack: AskItem[][] = [];
const clearedItems = new Map<string, AskItem>();   // the cards this page cleared and no live payload has shown since, by id: what a refused clear re-shows, stack or no stack (a federated pane
//                                                    keeps none; round ten of PR 1967); a record ends when a payload shows the card unsuppressed, and the map is bounded (the round-ten verifier)
const CLEARED_ITEMS_CAP = 200;                        // past this the oldest EVICTABLE record goes: never one under suppression, on the stack, or in the batch being written (rounds twelve and thirteen of PR 1967)
function recordCleared(it: AskItem): void { clearedItems.set(it.itemId, it); }   // the one writer of the record; the cap runs once the batch is held (evictClearedRecords)
// the cap: past it the oldest EVICTABLE record goes, never one under suppression, on the stack, or in the batch being written (`writing`). The
// twelfth executed review of PR 1967 found the batch's own oldest members evicted at the 201st record: the writers suppress a batch's ids after
// the entry is pushed, and the board's Clear all never does, so the hold set is taken after the splice, with this batch named
function evictClearedRecords(writing: Iterable<string>): void {
  if (clearedItems.size <= CLEARED_ITEMS_CAP) return;
  const held = new Set<string>(writing);
  for (const id of pendingCleared) held.add(id);
  for (const e of clearedStack) for (const x of e) held.add(x.itemId);
  for (const id of Array.from(clearedItems.keys())) {   // insertion order: the oldest first
    if (clearedItems.size <= CLEARED_ITEMS_CAP) break;
    if (!held.has(id)) clearedItems.delete(id);
  }
}
let lastUndoHosts = new Set<string>([""]);   // federation's word on where the last undo went (the undoRouted frame it hands the panes at the send; round twelve of PR 1967)
const undoSentBuild = new Map<string, number>();   // per kernel the undo went to: the build of its this page had seen at the send, so a later payload of that kernel built past it is evidence
const lastSeenBuild = new Map<string, number>();   // per kernel: the build of the last payload this page applied (the merged payload's per-host map; the payload's own build for the local kernel when the map lacks it)
// per SUPPRESSION the last undo reached for (round thirteen of PR 1967, the round-twelve verifier's HIGH and the twelfth executed review): the ids
// suppressed on the routed kernels at the send, each with the build of its kernel this page had seen then. A payload of that kernel built past it
// that lists the card is the evidence the card was restored (releaseRestoredByEvidence); an id suppressed after the send has no entry, so no payload
// releases it by evidence (a per-kernel record measured every later clear against the old undo's moment and painted the card back for a beat). An
// entry leaves once judged, or when the absence rule ends the suppression
const restoreChecks = new Map<string, { host: string; sentBuild: number; floor?: number; seq?: number }>();   // `seq`: the undo the check was written for (the per-undo sequence this page mints); an account's floor lands on that undo's checks alone; `floor` (round fifteen): the kernel's build counter when it processed the undo, from its account; until it lands a check on an accounting kernel releases nothing
let undoSeq = 0;   // the per-undo sequence (the post-merge review of PR 1967, M2): minted on each undoClear, carried by federation's routing frame and echoed by the kernel on the ack and every undo err frame
const undoPopped = new Map<number, AskItem[]>();   // per undo sequence: the batch the click restored optimistically, until the kernel's account for that undo comes (the second contributor's post-merge review of PR 2021): an account that carries no stack and names no ids says the kernel restored nothing, and the click's restore is taken back from this record; bounded
const UNDO_POPPED_CAP = 8;
let ackHosts = new Set<string>();   // the kernels whose last payload says they account for every undo with a build floor (`undoAck`; `ackHosts` on a merged payload): their checks wait for the account; an older kernel's take the build seen at the send, as before
let payloadHosts: string[] = [];   // the kernels whose builds the last merged payload carried (its per-host map, the local key aside): federation's word on the attachment, with pendingHosts and pendingDead (attachedHosts)
// The inverse of pendingCleared: ids we've optimistically RESTORED, kept (with their cached card) until a
// kernel push actually carries them again — otherwise the very next push (before the kernel un-archived) would
// replace `asks` and drop the just-restored card, a flicker. Dropped once the kernel lists the id.
const pendingRestored = new Map<string, AskItem>();

// The Undo stack's writers (round eight of PR 1967). The kernel's own stack is the ids an earlier undo left owed (its next Undo writes
// their rows first, so they are the newest batch) over the clears log's batches by stamp; this page's stack must read the same, press
// after press, for the optimistic Undo to restore what the kernel restores. Two rules keep it so, proven by enumeration in
// feed-render-incremental.test.ts over tests/fixtures/undo-stack-transitions.json: a batch this page makes goes UNDER the owed entries
// (pushClearedEntry), and every gesture account the kernel sends carries its stack except any sent while its clears log cannot be read (a refused clear alone ships none too; the branches below take those) (`batches`, `owedBatch`, and `batchesTotal`, the count of
// log batches before the wire's bound, so a truncated stack reads as truncated), which this page takes as its
// own (reconcileClearedStack): a refusal leaves the kernel's stack as it was, so the entry the click popped comes back; ids that came back
// leave; ids this page never held stand in an entry of their own (empty, so the Undo on it is the round trip).
function pushClearedEntry(entry: AskItem[]): void {
  for (const it of entry) recordCleared(it);
  const writing = entry.map((it) => it.itemId);
  if (federatedPane()) { evictClearedRecords(writing); return; }   // a federated pane keeps no stack: its Undo is the round trip (federatedPane)
  let i = clearedStack.length;
  const owedIds = new Set<string>();
  while (i > 0 && (clearedStack[i - 1] as any)._owed) { i--; for (const it of clearedStack[i]) owedIds.add(it.itemId); for (const id of ((clearedStack[i] as any)._ids as string[] | undefined) ?? []) owedIds.add(id); }
  // the owed entries stay on top: the kernel's next Undo is theirs. An id they hold counts once, as owed (a card cleared again while owed: the
  // kernel's re-journal-first row supersedes its log row and one Undo restores it whole), so it does not enter the new entry
  const rest = entry.filter((it) => !owedIds.has(it.itemId));
  if (rest.length) clearedStack.splice(i, 0, rest);
  evictClearedRecords(writing);                            // the cap, with this batch held: on the stack now, and named for the ids a writer suppresses after the push
}

function reconcileClearedStack(batches: string[][], owedBatch: string[], truncated = false, namedIds: string[] = []): void {
  // a single-kernel pane's frame (federatedPane gates the call): every id is this kernel's
  const known = new Map<string, AskItem>();
  for (const [id, it] of clearedItems) known.set(id, it);   // the page's record of what it cleared, for cards no live payload has shown since (one source: the enumeration's mutant on it reds)
  for (const a of asks) known.set(a.itemId, a);              // the live board's copy wins for a card on the board
  const owed = new Set(owedBatch);
  const cleared = new Set<string>();
  for (const b of batches) for (const id of b) cleared.add(id);
  // the kernel's next payload is the truth for every card its stack names: no optimistic stickiness past a gesture account. A log batch's
  // cards are off the board (an optimistic restore the kernel did not make, or a clear that landed): gone now, suppressed until a payload
  // omits them. An OWED id is a promise about the next Undo, not a word on its card: the card may well show (a clear whose flag step
  // refused left no flag, and the undo's flag step refused too), so the payload says whether it stays
  const hidden = new Set<string>();
  for (const id of cleared) if (!owed.has(id)) hidden.add(id);
  const named = new Set(namedIds);                          // the ids the account itself names (a refused batch)
  for (const id of cleared) { pendingRestored.delete(id); if (hidden.has(id)) pendingCleared.add(id); }
  // a card the kernel holds cleared leaves the board and enters the page's record with its live copy: a second frame in the same press (the
  // ledger's account, then the reorder) builds its entry from that record, since the board no longer shows it
  asks = asks.filter((a) => { if (!hidden.has(a.itemId)) return true; recordCleared(a); return false; });
  evictClearedRecords([]);                                 // the cap, after the hidden ids are suppressed above (held)
  // what this page suppressed and no log batch hides (a refused clear, an owed card that shows) comes back where it was, its collapse undone.
  // A TRUNCATED frame says nothing about the batches it left out: a suppression the frame neither names nor carries stays until a payload
  // omits or shows the card (the ninth executed review: read as "not cleared", the older clears flapped back and their Undo entries went)
  for (const id of Array.from(pendingCleared)) {
    if (hidden.has(id)) continue;
    if (truncated && !named.has(id) && !cleared.has(id)) continue;
    pendingCleared.delete(id);
    const it = known.get(id);
    if (!it) continue;
    for (const c of cardTwins(id)) c.classList.remove("dismissing");
    if (!asks.some((a) => a.itemId === id)) asks.push(it);
  }
  // the stack is the frame's, oldest first so the newest batch ends on top; under a TRUNCATED frame an entry the frame neither carries nor
  // names is an older clear beyond the window and stays, below the rebuilt ones
  const older: AskItem[][] = [];
  if (truncated) {
    for (const e of clearedStack) {
      const ids = ((e as any)._ids as string[] | undefined) ?? e.map((it) => it.itemId);
      if (ids.length && !ids.some((id) => cleared.has(id) || named.has(id))) older.push(e);
    }
  }
  clearedStack.length = 0;
  clearedStack.push(...older);
  for (const ids of batches.slice().reverse()) {
    const e: AskItem[] = [];
    for (const id of ids) { const it = known.get(id); if (it) e.push(it); }
    (e as any)._ids = ids.slice();                         // the batch's ids, whether or not this page holds their items
    if (ids.length && ids.every((id) => owed.has(id))) (e as any)._owed = true;
    clearedStack.push(e);
  }
  render();
}

// test hooks (the enumeration in feed-render-incremental.test.ts): the stack's entries by the ITEMS they hold, top first; the ids each
// entry took from the kernel's frame, apart (the eighth executed review: one hook returning the frame's ids made the equality hold by
// construction); and a reset between sequences
export function _clearedStackIdsForTests(): string[][] {
  return clearedStack.map((e) => e.map((it) => it.itemId)).reverse();
}
export function _clearedItemsIdsForTests(): string[] { return Array.from(clearedItems.keys()); }
export function _restoreChecksForTests(): [string, string, number][] { return Array.from(restoreChecks, ([id, c]) => [id, c.host, c.sentBuild] as [string, string, number]); }
export function _restoreFloorsForTests(): [string, number | null][] { return Array.from(restoreChecks, ([id, c]) => [id, c.floor ?? null] as [string, number | null]); }
export function _restoreSeqsForTests(): [string, number | null][] { return Array.from(restoreChecks, ([id, c]) => [id, c.seq ?? null] as [string, number | null]); }
export function _clearedStackItemsForTests(): AskItem[][] { return clearedStack.map((e) => e.slice()).reverse(); }
export function _clearedStackFrameIdsForTests(): (string[] | null)[] {
  return clearedStack.map((e) => ((e as any)._ids as string[] | undefined) ?? null).reverse();
}
export function _resetClearGestureStateForTests(): void { clearedStack.length = 0; clearedItems.clear(); pendingCleared.clear(); pendingRestored.clear(); lastUndoHosts = new Set([""]); undoSentBuild.clear(); lastSeenBuild.clear(); restoreChecks.clear(); payloadHosts = []; ackHosts = new Set(); undoSeq = 0; undoPopped.clear(); }
// Finish an optimistic dismiss: the 180ms fade just removed the card element, so drop the item(s) from the
// LOCAL model and re-render NOW — in grouped mode a run whose last card left takes its session-name header
// with it, and the column count follows, instead of both lingering until the next kernel push (the user
// 2026-07-13: "the card disappears really fast… make [the session name] disappear immediately"). Only the
// local view advances; pendingCleared still guards incoming pushes until the kernel confirms the clear.
function dropDismissed(ids: string[]): void {
  const gone = new Set(ids);
  asks = asks.filter((a) => !gone.has(a.itemId));
  render();
}
// Optimistic follow-up MOVE (the user 2026-06-30): submitting a follow-up on a blocked card moves it to
// Working IMMEDIATELY, instead of waiting out the kernel round-trip (be.send + build_feed + push). The kernel
// stays AUTHORITATIVE — this is only a short-lived prediction: the kernel's own optimistic_followup flips the
// card to working, and the next push that confirms it clears the prediction (reconcileFollowMove).
//
// The prediction ends on an EVENT, never a stopwatch (the user 2026-07-21). It used to get 4 seconds to be
// confirmed by a payload and then reverted with "that follow-up didn't move the card to Working", but the
// feed serves a goal-store snapshot frozen for the length of a judge pass — routinely 30-80s — so a reply
// landing mid-pass could not be confirmed inside any window worth waiting, and the toast fired while the
// session was already working the reply. Both halves are fixed: the kernel now punches user writes through
// that snapshot (_feed_goals), and it ANSWERS the prediction instead of leaving the client to time it out.
// cardMoveAck carries ok — false is the one real failure, the goal gone from the store or sealed by a view
// clear, and the only thing worth a toast — plus the buildId of the newest feed build already underway, so
// the prediction can wait for a payload built AFTER the gesture rather than trusting one that could not
// possibly know about it yet. MOVE_ACK_MS is now only a backstop for an answer that never arrives.
const MOVE_ACK_MS = 15000;
const pendingFollowMove = new Map<string, number>();   // card itemId → backstop timer id; KEY = still predicting
// card itemId → the ack's buildId AND the kernel whose counter it is on. Every kernel numbers feed
// builds independently, so an ack is only comparable against the SAME host's frame of a merged payload
// (the user 2026-08-15: the local kernel's buildId, large after days of uptime, "outranked" a remote
// ack's small post-restart buildId on the first merged emission — see reconcileFollowMove).
const pendingMoveAck = new Map<string, { host: string; buildId: number }>();
// What KIND of reply put each prediction in flight (the user 2026-07-20: EVERY context-carrying reply flips
// its card to Working instantly, not just the feed composer's own follow-up):
//  - "followup": a message rides along → the prediction wears the re-check styling ("Followed up" chip),
//    and an unconfirmed prediction reverts WITH a toast (a silently-unheeded message must be apparent).
//  - "answer": a picker/permission answer resolved the session's live block — no chip, and the prediction
//    YIELDS to the first authoritative payload (see reconcileFollowMove). The revert is SILENT: an unheeded
//    answer re-shows the ⏸ blocked card, which IS the signal — unlike a message, nothing can be lost.
// Sub-goals the user crossed off in the modal whose kernel ack hasn't landed yet. Sticky rather than a
// one-shot DOM edit: the feed re-renders on every kernel push, and a push already in flight when the
// click happened still carries the OLD tree, so a one-shot paint would flip the tick straight back off
// (the user 2026-07-23). An entry survives until the authoritative tree agrees, or until the kernel says
// it disagrees — nodeOverrideResult, whose failure path reverts it and says why out loud.
const pendingDone = new Set<string>();
function reconcilePendingDone(asks: AskItem[], cardsUnknown = false) {
  if (!pendingDone.size) return;
  const seen = new Map<string, string>();               // nodeId -> its status in this payload
  for (const a of asks) for (const n of a.tree || []) seen.set(n.id, n.status);
  for (const id of Array.from(pendingDone)) {
    const st = seen.get(id);
    // done → the kernel caught up, drop the optimistic flag. Absent → the node is gone from the tree
    // entirely, so there is nothing left to paint and holding the flag would leak it forever — unless this
    // payload cannot vouch for every host's cards (the gate in applyFeedPayload, T404 round seven).
    if (st === "done" || (st === undefined && !cardsUnknown)) pendingDone.delete(id);
  }
}
type MoveKind = "followup" | "answer";
const pendingMoveKind = new Map<string, MoveKind>();
// card itemId → the payload's own object the predicted copy replaced in `asks` (applyFollowMove), so the
// kernel's refusal of the post can put it back (revertFollowMove) instead of waiting for the next frame
const predictedFrom = new Map<string, AskItem>();
// COLUMN-FLIP TRIPWIRE (the user 2026-07-28, who watched a just-replied card bounce Working →
// Completed → Working and could not be told afterwards WHICH layer bounced it — every candidate
// mechanism checked out sound post-hoc, and no surface records what the view actually SHOWED).
// Every rendered column change posts a clientDiag breadcrumb (client-diag.jsonl) carrying what
// most recently changed the render's inputs, so the next bounce is attributed from the recorded
// trail instead of unreproducible archaeology. Ids only, no card text.
const shownCol = new Map<string, string>();            // itemId → column as last RENDERED (post-prediction)
let lastFeedEvent = "init";                            // the input change the next render reflects
let feedAnnounced = false;                             // {romp:'ready'} posted to the shell once, on the first payload's render
let lastPayloadBuildId = 0;
function auditShownColumns(list: AskItem[]) {
  const seen = new Set<string>();
  const firstRender = shownCol.size === 0;             // a fresh pane "appears" everything — not a delta
  const appeared: string[] = [];
  for (const a of list) {
    seen.add(a.itemId);
    const prev = shownCol.get(a.itemId);
    if (prev === undefined) appeared.push(a.itemId);
    if (prev !== undefined && prev !== a.column) {
      vscodeApi?.postMessage({ type: "clientDiag", surface: "feed", what: "colflip",
        data: { id: a.itemId, from: prev, to: a.column, ev: lastFeedEvent,
                buildId: lastPayloadBuildId, predicted: pendingFollowMove.has(a.itemId) } });
    }
    shownCol.set(a.itemId, a.column);
  }
  const gone: string[] = [];
  for (const id of Array.from(shownCol.keys())) if (!seen.has(id)) { gone.push(id); shownCol.delete(id); }
  // ITEM-SET TRIPWIRE (the user 2026-07-31, cards blinking in and out): the colflip trail above only
  // records column CHANGES, so a card leaving/re-entering the render entirely — the observed flicker —
  // was invisible to every log. Same breadcrumb channel; ids only, no card text. `ev` names the input
  // change this render reflects, so a blink is attributed to the layer that dropped the card (a host
  // payload, a filter, a fold) instead of re-guessed from pixels.
  if (!firstRender && (appeared.length || gone.length)) {
    vscodeApi?.postMessage({ type: "clientDiag", surface: "feed", what: "itemset",
      data: { appeared, gone, total: list.length, ev: lastFeedEvent, buildId: lastPayloadBuildId } });
  }
}
function clearFollowMove(itemId: string, why = "") {
  const t = pendingFollowMove.get(itemId); if (t) clearTimeout(t);
  pendingFollowMove.delete(itemId); pendingMoveKind.delete(itemId); pendingMoveAck.delete(itemId);
  predictedFrom.delete(itemId);
  if (why) lastFeedEvent = "clear:" + why;             // tripwire attribution only; behavior unchanged
}
// The kernel REFUSED the post a prediction rode on (an `err` naming the card's askFollowUp; review find,
// 2026-09-08): the card goes back to what the payload says NOW, on that reply, rather than sitting in Working
// until the next frame. The refusal is the event the no-answer backstop only approximated; the backstop's own
// toast blamed silence, and here the kernel has spoken. Puts the payload's object back in the slot the copy
// took, so the render shows the kernel's state and the gate repaints that card alone (a new identity).
function revertFollowMove(itemId: string): void {
  const orig = predictedFrom.get(itemId);
  clearFollowMove(itemId, "refused");
  if (orig) { const i = asks.findIndex((a) => a.itemId === itemId); if (i >= 0 && asks[i] !== orig) asks[i] = orig; }
  render();
}
function optimisticFollowMove(itemId: string, kind: MoveKind = "followup") {
  const prev = pendingFollowMove.get(itemId); if (prev) clearTimeout(prev);
  pendingMoveKind.set(itemId, kind);
  pendingMoveAck.delete(itemId);                       // a fresh gesture waits on its OWN answer, not the last one's
  lastFeedEvent = "predict:" + kind;
  const timer = window.setTimeout(() => {
    if (!pendingFollowMove.has(itemId)) return;        // a push already confirmed the move → nothing to do
    const k = pendingMoveKind.get(itemId);
    clearFollowMove(itemId, "backstop-noack");         // give the kernel authority: drop the prediction
    // Reaching here means the kernel never answered AT ALL (see ackFollowMove) — not that it declined the
    // move, which is what the old wording claimed on every mid-pass reply. An "answer" prediction has no
    // ack by design and always yields to the first payload, so it never gets this far.
    if (k !== "answer") feedToast("romp didn’t confirm that move, so the card is back to the state romp reports. Check it.");
    render();                                          // fall back to the kernel-authoritative state
  }, MOVE_ACK_MS);
  pendingFollowMove.set(itemId, timer);
}
// The kernel's ANSWER to a predicted move (cardMoveAck, the user 2026-07-21). ok=false is the only genuine
// "it didn't stick": the goal is no longer in the store (compacted or rotated away) or a view clear sealed
// it — worth interrupting for, and precise about what happened, including that a follow-up's message still
// went out. ok=true records the buildId the prediction must outlive and re-arms the window SILENTLY: the
// kernel has spoken, so nothing from here on is worth a toast, but a prediction must never outlive the
// answer either, so the backstop stays armed in case a payload goes missing.
function ackFollowMove(itemId: string, ok: boolean, buildId: number, host: string, why = "") {
  if (!pendingFollowMove.has(itemId)) return;
  if (!ok) {
    clearFollowMove(itemId, "ack-fail");
    // `why` (the second executed review of PR 1935, 2026-09-21): the store REFUSED the reopen's write, so the card is still on the
    // board and the toast says that; without it the one answer was "gone", and a card that had stayed read as vanished
    feedToast(why ? "Your reply was sent, but the card could not be moved to Working: " + why
                  : "Your reply was sent, but that card isn’t on the board any more to move to Working.");
    render();
    return;
  }
  pendingMoveAck.set(itemId, { host, buildId });
  const prev = pendingFollowMove.get(itemId); if (prev) clearTimeout(prev);
  pendingFollowMove.set(itemId, window.setTimeout(() => {
    if (!pendingFollowMove.has(itemId)) return;
    clearFollowMove(itemId, "backstop-noconfirm"); render();   // silent wedge guard: no payload ever answered the ack
  }, MOVE_ACK_MS));
}
// On a fresh authoritative payload: a predicted card the kernel now lists as working (or no longer lists at
// all — cleared/absorbed) is CONFIRMED → drop the prediction + its timer. Else keep predicting (not caught up)
// — EXCEPT an "answer" prediction, which yields to the first payload either way: the kernel rebuilds the feed
// right after retiring the picker (answerAsk → _mark_views_dirty), so a payload that still shows the card out
// of Working is post-answer truth — a real remaining/renewed block (e.g. the next permission prompt of a
// burst). Holding the prediction there would MASK a genuine "needs you"; dropping it re-shows the ⏸ card.
function reconcileFollowMove(incoming: AskItem[], buildId: number, buildIds?: Record<string, number>, cardsUnknown = false) {
  for (const id of Array.from(pendingFollowMove.keys())) {
    const a = incoming.find((x) => x.itemId === id);
    // absent → gone, unless this payload cannot vouch for every host's cards (the gate in applyFeedPayload, T404 round
    // seven): then the prediction waits for a payload that can, with the MOVE_ACK_MS backstop standing behind it
    if (!a && cardsUnknown) continue;
    if (!a || askColumn(a) === "asks" || pendingMoveKind.get(id) === "answer") {
      clearFollowMove(id, !a ? "gone" : askColumn(a) === "asks" ? "confirmed" : "answer-yield");   // Working by the kernel's category (askColumn, the boards' phase two)
      continue;
    }
    // ACKED, yet this payload still shows the card elsewhere. Trust it ONLY if it was built after the kernel
    // took the gesture: an older payload (one already in flight when the click landed) cannot know about the
    // reopen, and taking it as the answer is exactly the bounce back to Completed this replaced. A NEWER one
    // is the kernel's own state, so yield to it silently — the reply landed, the card simply moved on (the
    // work finished, a fresh block arrived), which is honest to show and never a failed move.
    //
    // "After" only means anything on ONE counter (the user 2026-08-15, whose reply to a remote card
    // bounced Working → Completed → Working): every kernel numbers its own feed builds, and the merged
    // payload's top-level buildId is the LOCAL kernel's — days of uptime vs a just-restarted remote made
    // it "outrank" every remote ack instantly, dropping the prediction while the cached remote frame
    // still predated the reopen. So compare the ack against the CARD's own kernel: its host's entry in
    // the per-host buildIds map (mergeHostFeeds). A single-kernel payload has no map — there the
    // top-level buildId IS the card's kernel's counter, for local (un-acked-host "") cards. A payload
    // that can't be placed on the ack's counter simply doesn't outrank: the prediction waits for
    // confirmation by content, with the MOVE_ACK_MS backstop unchanged behind it.
    const acked = pendingMoveAck.get(id);
    if (acked === undefined) continue;
    const cardHost = hostOf(a.sid);
    if (cardHost !== acked.host) continue;   // an ack from some other kernel says nothing about this card
    const mark = buildIds ? buildIds[cardHost] : (cardHost === "" ? buildId : undefined);
    if (typeof mark === "number" && mark > acked.buildId) clearFollowMove(id, "outranked");
  }
}
// Render-time: keep each still-unconfirmed predicted card in Working, styled like the kernel's own re-checked
// follow-up (recheck + followupPending), so the optimistic card matches the authoritative one with no jump.
//
// COPY the card, never write into it (the user 2026-08-02, who watched a just-replied card bounce
// working → blocked → working): on the federated page the ask objects in a payload ARE the
// FederationManager's cached per-host frames, served by reference (mergeHostFeeds concatenates the cached
// arrays and the merged frame arrives via a same-realm MessageEvent — no structured clone). An in-place
// `a.column = "working"` therefore wrote the prediction INTO that cache, and the next merged re-emit —
// fired by ANY host's frame, seconds later — handed the pane its own edit back as kernel truth, which
// reconcileFollowMove took as the kernel's confirmation and dropped the prediction. The next local build
// already in flight when the reply landed (honestly pre-reply) then bounced the card back to Blocked with
// no prediction left to hold it. Replacing the list SLOT with a copy keeps the render identical while the
// cached frame stays exactly what the kernel sent, so the prediction ends only on the real events.
function applyFollowMove(list: AskItem[]) {
  if (!pendingFollowMove.size) return;
  // now, in the server's epoch-second unit (kernel is local). Bump the predicted card's sort key to now so
  // the INSTANT optimistic move lands at the BOTTOM of Working, matching where the kernel's authoritative
  // followupAt stamp keeps it once this prediction clears — no top-flash then lurch-down (the user 2026-07-03).
  const nowSec = Math.floor(Date.now() / 1000);
  for (let i = 0; i < list.length; i++) {
    const a = list[i];
    if (!pendingFollowMove.has(a.itemId) || askColumn(a) === "asks") continue;   // already in Working by its category (its column from an older kernel)
    // the prediction names the feed's Working under BOTH keys: askColumn reads the category first since phase two of the
    // boards (plans/card-boards.md), so a copy predicting the column alone stayed in Blocked until the kernel re-filed it
    // (the 1837 read); the frame's own object keeps its category, as it keeps its column
    const c: AskItem = { ...a, column: "working", category: "working" };
    if ((pendingMoveKind.get(a.itemId) ?? "followup") === "followup") { c.recheck = true; c.followupPending = true; }   // plain move / answer: no chip
    if (c.t < nowSec) c.t = nowSec;   // sort to the bottom (newest); the group's repr follows via buildGroup
    predictedFrom.set(a.itemId, a);   // what a refusal of the post puts back (revertFollowMove)
    list[i] = c;
  }
}
// (drag-to-Working and the modal's "Move to Working" button were REMOVED, the user 2026-07-25: a
// messageless recategorize voids verdicts while adding no information — zero recorded uses, and a
// reply to the card does everything it did plus gives the agent something to act on. The kernel/judge
// reopen machinery stays: the reply path is its remaining caller, and historical "move" journal
// events still replay.)
// Group cards keyed by turnId, stored under "g:"+turnId. The focus state
// (hoverAskId/pinnedAskId) holds EITHER a raw ask itemId OR a group key
// "g:"+turnId; applyFocus + focusAnchorId understand both.
const groupEls = new Map<string, HTMLElement>();


// The three columns. The HOST decides each ask's column by DAG path accounting
// (completed only when every subgraph node is DONE); we just map its snake_case.
type Column = string;   // the ACTIVE board's local column keys: the feed's three CSS names, a data board's category ids (plans/card-boards.md, phase four)
function askColumn(it: AskItem): Column {
  // it.column is AUTHORITATIVE — the kernel already floors a live permission/picker block to needs_input (and
  // parked handoffs / placeholders set it too), so the client just maps its snake_case. We no longer re-route
  // by it.blocked: that crafty override existed only because the kernel used to report a picker-blocked card as
  // "working" while showing it under Blocked — it now reports needs_input directly (the user 2026-06-29). An
  // API-error card stays in its natural column (working): the kernel keeps column=working for it (a transient
  // stall, not a block), so it lands in "asks" with just the "⚠ API error" chip + Retry.
  return columnOf(boardOf(it), it.category ?? it.column);   // the card's OWN board's table (the category since phase two; column from an older kernel): a feed card keeps its feed key whatever board is shown
}

// How opaque the recency tint is over the (black) page — low = a faint, very
// see-through wash of the hawaii color; the colormap itself darkens with age.
const TINT_ALPHA = 0.22;

// Session identity colours are 6-digit hex; split one into [r,g,b] channels. The card border colour is
// CSS-driven from these channels (--card-r/g/b) so the outline is a PLAIN rgba (not color-mix(), which a
// reused card node can silently reject) AND the highlight can bold the SAME colour by just raising the alpha
// in CSS (the user 2026-07-15). Returns null for a non-hex value so the caller can fall back to the recency
// tint channels.
function hexToRgb(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-fA-F]{6})$/.exec((hex || "").trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
// Write the card's outline channels so CSS paints rest (0.5α) + a bolded .focused/.pinned in the SAME colour.
function setCardChannels(card: HTMLElement, rgb: [number, number, number]) {
  card.style.setProperty("--card-r", String(rgb[0]));
  card.style.setProperty("--card-g", String(rgb[1]));
  card.style.setProperty("--card-b", String(rgb[2]));
  card.style.borderColor = "";   // CSS owns border-color now (rgba(var(--card-*), …)); clear any stale inline
}
const hostApi =
  typeof (window as any).acquireVsCodeApi === "function" ? (window as any).acquireVsCodeApi() : undefined;
// every post this pane makes passes here, so a jump into a session (openSession, showOnTimeline, whichever click
// made it) is noted in ONE place and the focused-session section follows at once (T416, noteOwnJump)
const vscodeApi = hostApi ? { postMessage: (m: any) => { noteOwnJump(m); hostApi.postMessage(m); } } : undefined;
// PR links inside cards open the PR and nothing else: capture-phase on the document, so the card's own
// click (modal / pin) under the link never fires. Web → the viewer's browser; VS Code → the host's
// openExternal via `openLink` (view-routing.ts; extension.ts opens it for the feed panel). Once, on the
// stable document, keyed off the anchor's href across the press (the click-safety rule: the anchors
// themselves are rebuilt by pushes).

installPrLinkOpener(document, vscodeApi ? (m) => vscodeApi.postMessage(m) : undefined);

// The settings gear (the ⛭ modal + analytics) rides THIS bundle for VS Code's feed panel: gear.js
// builds its DOM here and rides our one kernel channel, opened by a {romp:'openSettings'} window
// message (the VS Code menu). The kernel's dashboard serves the gear on its own /settings page
// instead (settings-page.ts; the user 2026-09-10, so the Feed pane is no longer required for
// settings) and flags its feed page so no second gear is mounted here — an opener in this document
// (the login card below) then goes up to the shell, which forwards it there (gear-host.ts).
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { initGear } = require("./gear.js");
if (hostsGear(window)) initGear((m: Record<string, unknown>) => vscodeApi?.postMessage(m));
// the gesture clock the gear stamps its settings posts with — one module graph per document, so
// the gear's learning (each store's stamp from /version on open) serves the banner below too
// eslint-disable-next-line @typescript-eslint/no-var-requires
const gclock = require("./gesture-clock.js");

// The romp strip (VS Code only — the host opts in via __rompShowStrip): usage
// bars + the gear button, docked below #feed-foot. The gear raises the modal
// in THIS document (the gear listener above).
initStrip(() => openGear(window),
  (m: Record<string, unknown>) => vscodeApi?.postMessage(m));
installSettingsSync();   // a gear save in ANOTHER VS Code pane lands here via the host
// the overall theme applies to THIS document too (2026-08-28): at boot and on every settings
// write — before this only the chat pane wore the body classes, so a light theme could never
// reach the feed
applyTheme(document, loadSettings());
onExternalSettingsChange((s) => { applyTheme(document, s); render(); });

// Card-display prefs read straight from the shared 'romp:settings' (the kernel's ⛭ gear writes it; same
// document as this feed bundle). Default ON. These gate the CARDS only — the modal always shows everything
// (the user 2026-06-17). `!== false` so a missing key defaults to shown.
// Memoised on the RAW settings string: called per card per render, and each call parsed the blob. Keyed on
// the raw string, the memo is exact and needs no invalidation. `colormap` rides along for the per-card
// update gate (feed-card-gate.ts): a colormap pick repaints every card once, as the settings epoch did.
type FeedPrefs = { newestFirst: boolean; collapsed: boolean; grouped: boolean; stacked: boolean; colormap: string };
const PREFS_DEFAULT: FeedPrefs = { newestFirst: false, collapsed: false, grouped: true, stacked: false, colormap: "aurora" };
let prefsRaw: string | null | undefined;
let prefsMemo: FeedPrefs = PREFS_DEFAULT;
function feedPrefs(): FeedPrefs {
  let raw: string | null = null;
  try { raw = localStorage.getItem("romp:settings"); } catch { return PREFS_DEFAULT; }
  if (raw === prefsRaw) return prefsMemo;
  try {
    const s = JSON.parse(raw || "{}");
    // newestFirst + collapsed default OFF (=== true): the feed's natural order is oldest-first, and cards
    // arrive with their summary open (the user 2026-07-07). collapsed is the DEFAULT section state new cards
    // inherit — a per-card expand overrides just that card without turning the mode off. (Sub-goals is now one
    // of the mutually-exclusive sections 2026-07-08; the same `collapsed` default applies — see resolveSec.)
    // grouped (the user 2026-07-13): each column groups its cards by SESSION (tab/lane order), a session-name
    // header on the backdrop between runs, the per-card name dropped — the compact by-session read.
    // Default ON (!== false, same day): grouping is the feed's normal reading mode; the toggle opts OUT.
    prefsMemo = { newestFirst: s.newestFirst === true, collapsed: s.collapsed === true, grouped: s.grouped !== false,
                  stacked: s.stacked === true, colormap: String(s.colormap || "aurora").toLowerCase() };
  } catch { prefsMemo = PREFS_DEFAULT; }
  prefsRaw = raw;
  return prefsMemo;
}
// The kernel's session order (session-order.json — the SAME order the chat tabs + timeline lanes hold; the
// user 2026-07-13: grouped-mode sessions must match it). Rides every feed push; federation concatenates
// per-host orders local-first, ids pre-prefixed.
let sessionOrder: string[] = [];
// The owner-less notice cards' owner key (kernel.py NOTICE_OWNERLESS_SID; the user 2026-09-18: a card with no session at the
// top of the feed). The feed board's SORT RULE, never a card field or a timestamp trick (plans/notice-cards.md, "Owner-less
// cards"): within a column, the owner-less run ranks before every session run, then the session order, then time.
const NOTICE_OWNERLESS_SID = "notes";
// A remote host's owner-less card arrives with its sid host-prefixed (federation prefixInbound: "host:notes"), so the test
// strips the prefix the way federation adds it: one helper for the rank, the chip and the header (round two of PR 1831)
const isOwnerless = (sid: string | null | undefined): boolean => !!sid && bareId(sid) === NOTICE_OWNERLESS_SID;
const ownerRank = (sid: string): number => isOwnerless(sid) ? 0 : 1;
// The chat tab strip's sessions (sid+name+color), riding every feed push: the footer's session-filter
// menu lists exactly the tabs (the user 2026-08-08) — a session with no cards still appears, and
// filtering to it shows an empty board. Federation prefixes sid+name per host and concatenates.
let sessionsMeta: { sid: string; name: string; color: { bg: string; fg: string } | null; githubRepo?: string | null }[] = [];
// The GitHub repository a card's session works in (owner/repo, or null) — the kernel ships it on the
// session rows above, derived from the session tree's origin remote; a `#123` in the card's text links
// to that repository's PR page (pr-links.ts; the user 2026-09-06). Null → the text stays plain.
function prRepoOf(sid: string | undefined): string | null {
  return (sid && sessionsMeta.find((s) => s.sid === sid)?.githubRepo) || null;
}
// Attached hosts whose CARD payload hasn't merged yet (the user 2026-08-25: sessions land via the
// faster channels, cards trail with no cue) — the federation merge names them (pendingHosts), the
// board hints per host, and the hint retires ONLY on the real events: that host's first contribution
// (an empty one included) or its detach. The 45s mark ESCALATES the copy ("still waiting…"), never
// hides — the first cut's backstop RETIRED the hint while the host genuinely still pended (the user
// 2026-08-25, round two: the dots vanished, the cards still hadn't come; the signal knew, the
// backstop overrode it — a backstop must never make the board lie about a true wait). A DEAD link
// (pendingDead, from the merge's socket truth) names itself instead of waiting open-endedly.
let pendingHosts: string[] = [];
let pendingDead: string[] = [];
// every kernel the last undo went to has a build in this payload past the one seen at the send: the cue's clear on a federated pane (the second
// contributor's review, 2026-09-22). A kernel with no build on record gave no measure, so it does not hold the cue
function undoRoutedBuilt(m: any): boolean {
  const perHost = m.buildIds && typeof m.buildIds === "object" && !Array.isArray(m.buildIds) ? m.buildIds as Record<string, number> : undefined;
  const local = typeof m.buildId === "number" ? m.buildId : undefined;
  for (const h of lastUndoHosts) {
    const sent = undoSentBuild.get(h); if (sent === undefined) continue;
    const built = perHost && typeof perHost[h] === "number" ? perHost[h] : (h === "" ? local : undefined);
    if (typeof built !== "number" || built <= sent) return false;
  }
  return true;
}
// On a FEDERATED pane a suppression ends on the EVIDENCE that the card was restored (round twelve of PR 1967, the round-eleven verifier's design;
// per suppression since round thirteen, the round-twelve verifier's HIGH): federation's word at the send (undoRouted) writes a restore check on
// every card then suppressed on the kernels the undo went to, with the build of its kernel this page had seen at that moment, and a payload from
// that kernel built past it that lists the card releases the suppression. A stale held frame, built before the send, releases nothing; a kernel
// the undo never reached never lists a restored card with a newer build; a kernel that restored an older batch shows exactly what it restored;
// a card cleared AFTER the send has no check, so no payload releases it by evidence. A build below the one last seen from a kernel is its restart
// (the counter is per process; the twelfth executed review): the check re-bases to the new life and that payload judges the card. The single-kernel
// pane releases at the click instead, as the enumeration proves it, so the undoRouted branch writes no check there (the attachment read at the send,
// the click's moment; the frame reaches every kernel-served pane, the thirteenth executed review); a pane that flips from federated to single-kernel
// between the click and the restore keeps its checks, so no gate on the attachment stands HERE. Apart from applyFeedPayload's absence-driven writers,
// which stand behind the cards-unknown gate: this one acts on presence and needs no such gate
function releaseRestoredByEvidence(incomingAsks: AskItem[], m: any): void {
  for (const id of Array.from(restoreChecks.keys())) if (!pendingCleared.has(id)) restoreChecks.delete(id);   // the absence rule, or a click, ended the suppression: judged elsewhere
  if (!restoreChecks.size) return;
  const perHost = m.buildIds && typeof m.buildIds === "object" && !Array.isArray(m.buildIds) ? m.buildIds as Record<string, number> : undefined;
  const local = typeof m.buildId === "number" ? m.buildId : undefined;
  const builtOf = (h: string): number | undefined => (perHost && typeof perHost[h] === "number" ? perHost[h] : (h === "" ? local : undefined));
  for (const c of restoreChecks.values()) {                        // a kernel's restart re-bases every check on it, listed or not: the new life's payload judges
    const built = builtOf(c.host), seen = lastSeenBuild.get(c.host);
    if (typeof built === "number" && seen !== undefined && built < seen) { c.sentBuild = -1; c.floor = -1; }
  }
  for (const a of incomingAsks) {
    const c = restoreChecks.get(a.itemId);
    if (!c) continue;
    const built = builtOf(c.host);
    // the FLOOR (round fifteen of PR 1967, the round-thirteen verifier's ruling): on a kernel that accounts for its undos, the build counter it
    // reported when it processed the undo; a build past it read the store after every earlier clear applied and the undo's batch restored, so
    // a listed card is restored, while a build claimed before it (in flight, however it is stamped) is no evidence. Until the account lands the
    // check releases nothing (the safe direction: the card stays off; the absence rule stands). An older kernel sends no account: the build
    // seen at the send stands as its floor, as before
    const floor = ackHosts.has(c.host) ? c.floor : c.sentBuild;
    if (floor === undefined || typeof built !== "number") continue;
    if (built > floor) { pendingCleared.delete(a.itemId); restoreChecks.delete(a.itemId); }
  }
}
// an undo's account from kernel `host` (the ack of a landed undo, a refusal, the reorder's frame): its build floor lands on the checks written
// for THAT undo on that kernel alone, by the per-undo sequence the kernel echoes (the post-merge review of PR 1967, M2: two undos to one kernel
// with a clear between them put the first undo's floor on the second undo's check, and a build claimed before that clear applied passed it);
// an account with no sequence (a kernel between round fifteen and this) lands on every check of its kernel, as before
function setUndoFloor(host: string, seq: unknown, floor: unknown): void {
  if (typeof floor !== "number") return;
  for (const c of restoreChecks.values()) if (c.host === host && (typeof seq !== "number" || c.seq === seq)) c.floor = floor;
  // an account for undo N on a LIVE socket says every earlier undo's account from this kernel has come or never will (in-order delivery on the
  // pressing socket): this kernel's FLOORLESS checks with a lower sequence lost theirs, so they take the click-time release now, or the card
  // would stay off while every build listed it (the second contributor's post-merge note on PR 2018); a floored check keeps waiting for evidence
  if (typeof seq === "number") for (const [id, c] of Array.from(restoreChecks)) if (c.host === host && c.floor === undefined && typeof c.seq === "number" && c.seq < seq) { restoreChecks.delete(id); pendingCleared.delete(id); }
}
// a kernel's socket came back (the shim's `wsup` frame for the local kernel; for a remote one the relay socket's own reopen, federation's
// `romp:hostRelayUp` event, listened for below, and the tunnel poll's `hostUp` frame as a second trigger): the undo's account rides the
// pressing client's queue alone, which the redial may have abandoned, so a check still waiting for it would hold a restored card off the
// board for good (the absence rule never covers a listed card); its suppressions take the click-time release instead (the post-merge review)
function dropChecksOnReconnect(host: string): void {
  for (const [id, c] of Array.from(restoreChecks)) if (c.host === host) { restoreChecks.delete(id); pendingCleared.delete(id); }
}
// a remote kernel's relay socket reopened: federation's own event on its onopen, the exact event a redial fires (the artifacts pane's pattern;
// the post-merge note on PR 2018: the tunnel poll's hostUp is a proxy, silent on a watchdog redial and loud on an upSeq bump with the socket intact)
window.addEventListener("romp:hostRelayUp", (ev) => { const h = String((ev as CustomEvent).detail?.host || ""); if (h) dropChecksOnReconnect(h); });

// the kernels attached, by federation's own account and never by sessions or cards (rounds twelve and thirteen of PR 1967: a remote card's coming
// and going flipped the reading, then a remote card whose kernel had no session row on the strip read as a single-kernel pane and took the
// optimistic cross-kernel Undo): the hosts pending or down (the merge's lists), the kernels whose builds the last merged payload carried, and the
// manager's host list where the page has one
function attachedHosts(): Set<string> {
  const out = new Set<string>();
  for (const h of pendingHosts) out.add(h);
  for (const h of pendingDead) out.add(h);
  for (const h of payloadHosts) out.add(h);
  const fed = (globalThis as any).__rompFed;   // the slot federation.js publishes (read off globalThis, as host-prefix reads it)
  if (fed && typeof fed.hosts === "function") { try { for (const h of fed.hosts()) if (typeof h === "string") out.add(h); } catch (_) { /* the slot's shape is federation's; a throw is no attachment */ } }
  out.delete("");
  return out;
}
// A FEDERATED pane: more than one kernel attached. Undo on such a pane is the round trip (the round-nine verifier's ruling on PR 1967): stamps
// across kernels do not order, so a merged stack cannot say which kernel's batch the next Undo reaches (federation routes undoClear to the
// kernels of the most recent clear), and an optimistic pop would restore one kernel's card while another kernel restored its own. The optimistic
// Undo, and the stack the enumeration proves equal to the kernel's, stay where the proof holds: a single-kernel pane. Here: no entry is cached,
// none is popped, the button shows the working cue, and the payload restores what the kernels restored (releaseRestoredByEvidence); a remote
// kernel's account re-shows the cards of a refused clear by their ids
function federatedPane(): boolean { return attachedHosts().size > 0; }
// the kernel a suppressed card belongs to: its recorded copy's session (a remote session wears federation's host prefix), else the id's own prefix
// when it names an attached kernel (a notice card dismissed by its answer has no record), else the local kernel
function suppressedHostOf(id: string): string {
  const rec = clearedItems.get(id);
  if (rec) return hostOf(rec.sid);
  const h = hostOf(id);
  return attachedHosts().has(h) ? h : "";
}
const hostloadTimers = new Map<string, number>();
const hostloadLong = new Set<string>();
function syncHostloadBackstops(): void {
  for (const h of pendingHosts) {
    if (!hostloadTimers.has(h)) {
      hostloadTimers.set(h, window.setTimeout(() => { hostloadLong.add(h); render(); }, 45000));
    }
  }
  for (const [h, t] of Array.from(hostloadTimers)) {
    if (!pendingHosts.includes(h)) {   // the payload landed (or the host detached) — the ONLY removals
      window.clearTimeout(t);
      hostloadTimers.delete(h);
      hostloadLong.delete(h);
    }
  }
}
// The feed's LOCAL tag lens (the user 2026-08-25, T70): the shared TagLens model (tag-lens.ts, the
// multi-select every surface speaks) applied as THIS board's own deliberate narrowing — never the
// shared blob's `active` (the decoupling ruling stands); the payload's views blob feeds tag
// DEFINITIONS only (lensUnions). Persistence is sessionStorage, the feed's storage-split convention
// (romp:feedOnly's reasoning): reload-proof, but a fresh window starts on All — a lens persisting
// for days would read as silently missing cards, and the disclosure line only mitigates. The tags
// dialog's "set for all surfaces" writes localStorage romp:feedTags-set {lens,t}; the storage
// listener below adopts it into this pane's own lens (the PR-B adoption contract).
let feedTagViews: SessionViews | null = null;
let feedLens: TagLens = { all: true };
try { feedLens = JSON.parse(sessionStorage.getItem("romp:feedTags") || "") || { all: true }; } catch { /* default All */ }
function setFeedLens(l: TagLens): void {
  feedLens = l;
  try {
    if (lensAll(l)) sessionStorage.removeItem("romp:feedTags");
    else sessionStorage.setItem("romp:feedTags", JSON.stringify(l));
  } catch { /* storage blocked */ }
}
try {
  window.addEventListener("storage", (e) => {
    if (e.key !== "romp:feedTags-set" || !e.newValue) return;
    try {
      const v = JSON.parse(e.newValue);
      if (v && v.lens) { setFeedLens(v.lens as TagLens); render(); }
    } catch { /* malformed set-for-all — ignore */ }
  });
} catch { /* no storage events */ }
// The one session the board is filtered to, or null — the DEFAULT, nothing selected, everything shows.
// sessionStorage, deliberately: it survives this tab's reloads (webviews reload on updates) but a fresh
// window always starts unfiltered — a filter that persisted for days would read as silently lost cards.
let feedOnlySid: string | null = null;
try { feedOnlySid = sessionStorage.getItem("romp:feedOnly") || null; } catch { /* storage blocked */ }
function setFeedOnly(sid: string | null): void {
  feedOnlySid = sid;
  try { sid ? sessionStorage.setItem("romp:feedOnly", sid) : sessionStorage.removeItem("romp:feedOnly"); } catch { /* ignore */ }
}
// The SEARCH query (the user 2026-08-23): type-to-filter by session name, host prefix included —
// "TESTHOST" keeps every session on that machine. Same storage lifetime as the session filter: survives
// this tab's reloads, never a fresh window (a filter persisting for days reads as silently lost cards).
let feedSearchQ = "";
try { feedSearchQ = sessionStorage.getItem("romp:feedSearch") || ""; } catch { /* storage blocked */ }
function setFeedSearch(q: string): void {
  feedSearchQ = q;
  try { q ? sessionStorage.setItem("romp:feedSearch", q) : sessionStorage.removeItem("romp:feedSearch"); } catch { /* ignore */ }
}

// OPTIMISTIC colour echo from the chat pane's tab menu (the user 2026-08-08): the chat repaints its
// tabs the instant a swatch is picked, but this pane kept the old colour until the kernel's next feed
// REBUILD pushed — a second or two. The echo arrives kernel-free on two host-matched channels (the
// same pair settings sync rides): the browser's same-origin iframes hear the localStorage write
// (`storage` fires cross-document), and VS Code's extension fans {colorSync} to its other panels.
// Apply it to every copy this pane holds and re-render; the kernel's own re-broadcast reconciles.
// IN PLACE, deliberately: these objects are federation's held frame, so the write lands in the cache too
// and a re-emit before the kernel's own rebuild keeps the new colour (copies in this pane's list alone
// would hand the old colour back on the next merged emission). The per-card update gate cannot see an
// in-place write through object identity, so the colour rides the card key instead (feed-card-gate.ts).
function applyColorEcho(sid: string, bg: string): void {
  if (!sid || !bg) return;
  const color = { bg, fg: "#ffffff" };   // fg fixed white, matching the kernel's _name_color
  let hit = false;
  for (const a of asks) if (a.sid === sid) { a.color = color; hit = true; }
  for (const s of sessionsMeta) if (s.sid === sid) { s.color = color; hit = true; }
  const nm = sessionsMeta.find((s) => s.sid === sid)?.name || asks.find((a) => a.sid === sid)?.name;
  if (nm) sessionColors.set(nm, bg);     // held-mail cards look colours up by name
  if (hit) render();
}
window.addEventListener("storage", (e) => {
  if (e.key !== "romp:color-echo" || !e.newValue) return;
  try {
    const v = JSON.parse(e.newValue);
    applyColorEcho(typeof v.sid === "string" ? v.sid : "", typeof v.bg === "string" ? v.bg : "");
  } catch { /* malformed echo — the kernel push corrects momentarily */ }
});
// names of sessions currently WORKING → a working dot before that name everywhere
// it renders (card titles, modal title, group name). Pushed in each feed message.
// INSTANT chat acknowledgment for a card click (the user 2026-08-24: clicking into a not-shown
// session felt slow): the felt latency is the kernel ROUND-TRIP — click → WS → _reveal_chat_for →
// focus frame — and a busy kernel holds its WS handler behind push builds, while the chat already
// HOLDS every session's data (measured: the chat's own first render of a 6000-event hidden
// transcript is ~25ms). So the click also drops a same-origin echo the chat hears in milliseconds
// (the storage event; the romp:color-echo precedent), activating the tab/peek and the loader
// immediately; the kernel's focus frame follows and lands the anchor idempotently. VS Code webviews
// don't share localStorage — there the kernel path stands alone, unchanged.
function focusEcho(sid: string): void {
  try { localStorage.setItem("romp:focus-echo", JSON.stringify({ sid, t: Date.now() })); } catch { /* storage blocked */ }
}
let workingSet = new Set<string>();
// This machine's own name (kernel _self_host, on every feed payload) and the identity colour of every
// session the feed knows, keyed "host:name" for a remote one and plain for a local one: a session's colour is
// its identity everywhere else, so a renderer holding only a name can look one up (first built for the held
// mail's route line, the user 2026-07-29; that line is a notice card's body since 2026-09-19).
let feedSelfHost = "";
const sessionColors = new Map<string, string>();
// session name -> live background-process descriptions the JUDGE classified as services (kernel bgServices:
// a dev server the session keeps around — nobody waits on it, so it is session furniture, not a status).
// Rendered as a neutral chip on the grouped-mode session header; flat mode has no headers (the chat view's
// background-task box still lists the processes there).
let bgServicesMap: Record<string, string[]> = {};
const openBgSvc = new Set<string>();   // sids with the chip's process list expanded — survives re-renders
// COLLAPSED threads (the user 2026-07-31): grouped mode's session header carries a caret, and folding one
// leaves the header alone in every column that thread appears in, with a count of what is folded away.
// Keyed by SID, not by column-run, for the reason the request turns on: cards that do not exist yet must
// arrive collapsed too, and a card's column is not knowable when you fold the thread. Persisted across
// reloads with the rest of the disclosure state, and deliberately NOT pruned when the cards go away.
const collapsedThreads = new Set<string>();
// names of sessions idle-but-AWAITING background work (the user 2026-07-13): the same dot in await-green —
// matching the chat chip's Awaiting color — so a held session reads differently from a working one.
let awaitingSet = new Set<string>();
// Sessions the kernel LISTS but whose live state it could not read. These draw a gray ring, which
// is what lets a BLANK pip mean "alive and quiet" and nothing else — before it, an unreadable state
// and an idle one were the same nothing, so a rendering hole was indistinguishable from health.
let unknownSet = new Set<string>();
type DotState = "" | "work" | "await" | "unknown";
const dotFor = (name: string): DotState =>
  workingSet.has(name) ? "work" : awaitingSet.has(name) ? "await"
  : unknownSet.has(name) ? "unknown" : "";
// The pip explains itself on hover (the user 2026-07-22: learn the states from tooltips, not the
// CLI). It encodes TURN state — is anything running? — not attention; attention lives in the card.
const DOT_TIP: Record<Exclude<DotState, "">, string> = {
  work: "working — a turn is running right now",
  await: "awaiting — idle, but background work it dispatched is still running",
  unknown: "state unknown — romp couldn't read this session's live state",
};
// Ensure a `.fwork-dot` sits immediately before `nameEl` iff `state` is non-empty (idempotent on
// re-render; an existing dot RETINTS in place when the state flips). The name's text/color are untouched.
function setWorkDot(nameEl: HTMLElement | null, state: DotState | boolean) {
  if (!nameEl) return;
  const st: DotState = state === true ? "work" : state === false ? "" : state;
  const prev = nameEl.previousElementSibling;
  const has = !!prev && prev.classList.contains("fwork-dot");
  const paint = (d: Element) => {          // one kind class at a time; "work" is the bare base class
    for (const k of ["await", "unknown"]) d.classList.toggle(k, st === k);
    (d as HTMLElement).title = st ? DOT_TIP[st] : "";
  };
  if (st && !has) {
    const d = el("span", "fwork-dot"); paint(d);
    nameEl.parentElement?.insertBefore(d, nameEl);
  } else if (st && has) paint(prev!);
  else if (!st && has) prev!.remove();
}

let hostNow = Math.floor(Date.now() / 1000);
// …and WHEN that clock was read (ms, the browser's clock): the frame's `nowAt` when federation stamped one,
// else the handling. Every age and duration on a card reads the kernel's clock through nowSec() (feed-age.ts
// liveNow): the frame's `now` plus the local time since it landed, so the browser's skew from the kernel
// never enters an age, and a quiet board's ages keep moving between frames.
let hostNowAt = Date.now();
function nowSec(): number { return liveNow(hostNow, hostNowAt, Date.now()); }
let showDismissed = false;
let dismissedCount = 0;
let canUndoClear = false;   // host: cleared.jsonl has rows → the UndoClear button shows
// FLIP-across-identity (the user 2026-06-29): which render KEY covered each goal itemId on the LAST render.
// A goal's card can change identity — a group ("g:"+turnId) dissolving to a solo ask ("a:"+itemId), a goal
// absorbed under an umbrella ("a:"+umbrellaId) — which is a DIFFERENT DOM node, so the normal FLIP (reuse one
// node) can't slide it and it would pop. We map the new card back to its predecessor's old rect so it slides
// from there instead of appearing from nowhere. Rebuilt every render.
let prevItemKey = new Map<string, string>();

// ONE builder for every Clear on the feed (the user 2026-09-08): the card's, the turn-group's and the
// session header's wear the same element, class set, label and hover, so they cannot drift apart. Callers
// add behaviour (an onclick, a data-act) and, for the header, a layout-only positional class.
function clearButton(title: string, label = "Clear"): HTMLElement {
  const b = el("button", "fdismiss");
  b.textContent = label;   // "Clear" on a card; the session header's says "Clear all" (T271, the user 2026-09-08) — same chrome, same builder
  b.title = title;
  return b;
}

function el(tag: string, cls?: string): HTMLElement {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  return e;
}
// A text write that compares first. In a document that has created a MutationObserver — gear.js creates
// several at boot — Blink treats an identical textContent write as a real Text-node replacement and dirties
// layout (feed-age.ts has the mechanism). The grouped-mode session headers repaint on every render (they are
// not behind the per-card update gate), so their labels write through here.
function setText(e: HTMLElement, s: string): void { if (e.textContent !== s) e.textContent = s; }

// A lightweight yes/no overlay for the feed. Separate from the ask #feed-modal
// (a different state machine); Esc or a backdrop click cancels.
function feedConfirm(message: string, confirmLabel: string, onConfirm: () => void): void {
  const back = el("div", "fconfirm-back");
  const box = el("div", "fconfirm-box");
  const msg = el("div", "fconfirm-msg"); msg.textContent = message;
  const btns = el("div", "fconfirm-btns");
  const cancel = el("button", "fconfirm-btn"); cancel.textContent = "Cancel";
  const ok = el("button", "fconfirm-btn primary"); ok.textContent = confirmLabel;
  btns.append(cancel, ok);
  box.append(msg, btns);
  back.append(box);
  const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
  const close = () => { back.remove(); document.removeEventListener("keydown", onKey); };
  cancel.onclick = (e) => { e.stopPropagation(); close(); };
  ok.onclick = (e) => { e.stopPropagation(); close(); onConfirm(); };
  back.onclick = (e) => { if (e.target === back) close(); };
  document.addEventListener("keydown", onKey);
  document.body.appendChild(back);
  ok.focus();
}

// The warn-detail overlay (the user 2026-07-02): clicking a card's yellow "warning" chip opens this —
// one entry per judge-stamped anomaly, each telling in detail what happened and why it's unexpected,
// so pipeline misbehavior is followable from the card instead of buried in judge-errors.jsonl.
// Same lightweight overlay pattern as feedConfirm (its own state machine; Esc / backdrop / Close).
// A warn kind stamped by a GIVEN-UP summarizer line (summary/brief/stall) — these get the "distill
// failed" chip label and the modal's Try again (the user 2026-08-13); other anomaly kinds stay "warning".
// DISTILL_FAIL_RE (the distiller's own failure kinds) is card-sections.ts's since the box content round: the warning chip reads it there

// Feedback for the modal's Try again (the user 2026-08-13, round 2: the first cut leaned on the card's
// Distilling… swirl, which only shows where the done-side line is the visible one — on a Working card
// the click looked like a silent no-op even as the retry SUCCEEDED). Success and refusal both toast,
// and silence itself is caught: a kernel that predates the redistill op drops it with no result at all,
// so a backstop timer names that case instead of leaving the click unanswered (the ack event is the
// signal; the timer only speaks when it never comes).
let redistillWatch: { itemId: string; timer: number } | null = null;
function armRedistillWatch(itemId: string): void {
  if (redistillWatch) window.clearTimeout(redistillWatch.timer);
  redistillWatch = {
    itemId,
    timer: window.setTimeout(() => {
      redistillWatch = null;
      feedToast("no answer from the kernel about the summary retry — it may predate this feature (restart romp to update it)");
    }, 6000),
  };
}

function feedWarnModal(cardTitle: string, warns: { kind: string; t: number; msg: string; detail: string }[],
                       ctx?: { itemId: string; sid: string },
                       failLog?: { t: number; line: string; model: string; note: string }[] | null): void {
  const back = el("div", "fconfirm-back fwarn-back");
  const box = el("div", "fconfirm-box fwarn-box");
  const head = el("div", "fwarn-head"); head.textContent = "Unexpected behavior";
  const sub = el("div", "fwarn-sub"); sub.textContent = cardTitle;
  box.append(head, sub);
  for (const w of warns) {
    const entry = el("div", "fwarn-entry");
    const meta = el("div", "fwarn-meta");
    meta.textContent = w.kind + " · " + relAge(Math.max(0, Date.now() / 1000 - w.t));
    const body = el("div", "fwarn-detail"); body.textContent = w.detail || w.msg;
    entry.append(meta, body);
    box.append(entry);
  }
  // The attempt log (the user 2026-08-18): each failed try as its own line — when, which model, the
  // literal error — so a one-model outage reads as "tried opus — 529, tried opus — 529, …" at a glance
  // instead of hiding inside prose. Chronological, capped at the kernel (judge _fail_log).
  if (failLog && failLog.length) {
    const entry = el("div", "fwarn-entry");
    const meta = el("div", "fwarn-meta"); meta.textContent = "What was tried";
    entry.append(meta);
    for (const f of failLog) {
      const row = el("div", "fwarn-detail");
      row.textContent = `${clockHM(f.t)} · tried ${f.model} for the ${f.line} — ${f.note}`;
      entry.append(row);
    }
    box.append(entry);
  }
  const btns = el("div", "fconfirm-btns");
  // "Try again" on a given-up summary line (the user 2026-08-13): the kernel journals the re-arm and the
  // next triage pass re-runs the distiller — the card's own "Distilling…" swirl is the live cue after
  // the modal closes; a kernel refusal comes back as a redistillResult toast (fail loudly).
  if (ctx && warns.some((w) => DISTILL_FAIL_RE.test(w.kind))) {
    const retry = el("button", "fconfirm-btn") as HTMLButtonElement;
    retry.textContent = "Try again";
    retry.onclick = (e) => {
      e.stopPropagation();
      retry.disabled = true; retry.textContent = "retrying…";   // acknowledged before any round-trip
      armRedistillWatch(ctx.itemId);                            // silence gets named, never swallowed
      vscodeApi?.postMessage({ type: "redistill", itemId: ctx.itemId, sid: ctx.sid });
      window.setTimeout(close, 300);   // cosmetic beat so the pressed label registers; the op is already posted
    };
    btns.append(retry);
  }
  const ok = el("button", "fconfirm-btn primary"); ok.textContent = "Close";
  btns.append(ok);
  box.append(btns);
  back.append(box);
  const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
  const close = () => { back.remove(); document.removeEventListener("keydown", onKey); };
  ok.onclick = (e) => { e.stopPropagation(); close(); };
  back.onclick = (e) => { if (e.target === back) close(); };
  document.addEventListener("keydown", onKey);
  document.body.appendChild(back);
  ok.focus();
}

// A feed click on a session link. Live → open its tab. Closed (tab gone) → offer
// to revive it: the kernel's own confirmRevive dialog routes only to chat
// clients, so from a feed-only view an "open" would silently no-op; ask here and
// post reviveSession directly (the kernel reopens the most-recent incarnation).
function openOrReviveSession(sid: string, live: boolean, name: string): void {
  if (live) { vscodeApi?.postMessage({ type: "openSession", id: sid }); return; }
  feedConfirm(`“${name}” is closed — revive it?`, "Revive",
    () => vscodeApi?.postMessage({ type: "reviveSession", id: sid }));
}

function clockHM(t: number): string {
  return new Date(t * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

// The latched Continue/Check-status button explains itself (T150, the user 2026-08-28: a card read
// 'Sent' and clicking did nothing — the latch was honest, the silence was not). One title writer for
// both states of both buttons: while held, it names WHAT was sent, WHEN, and the exact event that
// re-arms it; enabled, it says what a click does. The hover title is the minimum honest surface for
// a disabled control (the buttons rule) — the label itself stays one word.
function contTitle(latched: boolean, verb: string, at?: number | null): string {
  return latched
    ? verb + " sent" + (at ? " " + relAge(nowSec() - at) : "") +
      " — waiting for the session's reply to be judged; this re-arms then, and the card moves on its own"
    : verb === "a continue"
      ? "nothing needed from you — asks the session to keep going"
      : "asks the session where each open item stands";
}

// relAge (the age words) lives in feed-age.ts since the box content round: the chat page's Needs you row stamps the same words

// A RUNNING duration as its own stamped element (feed-age.ts fmt "dur"): "42m" / "1h 5m" since an event
// time, repainted by the 15 s live pass like every other age. Every elapsed label on a card renders through
// here — the awaiting box, the Awaiting-task pill, the waiting-on chip, the working narration — because the
// per-card update gate repaints a card only when its inputs change, and a duration baked into a caption
// string would freeze on a card the kernel has no reason to re-send (a long wait whose record does not
// change). On the kernel's clock (nowSec), like every other age here; these read Date.now() before.
function durSpan(since: number): HTMLElement {
  const d = el("span", "fask-dur");
  stampAge(d, since, "dur", false, nowSec(), relAge, ageColorReadable);
  return d;
}
/** waitedSuffix's live twin: [" · ", <duration>] for a known start, [] otherwise — no since, no duration, never a guess. */
function durNodes(since: number | null | undefined): (string | HTMLElement)[] {
  return since && since > 0 ? [" · ", durSpan(since)] : [];
}

function dayLabel(t: number, now: number): string {
  const d = new Date(t * 1000);
  const ymd = (x: Date) => `${x.getFullYear()}-${x.getMonth()}-${x.getDate()}`;
  if (ymd(d) === ymd(new Date(now * 1000))) return "Today";
  if (ymd(d) === ymd(new Date((now - 86400) * 1000))) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

// ---- header (built once, then updated in place): title + "N need input" + live ----
let headerBuilt = false;
let elTitle: HTMLElement, elMeta: HTMLElement;

function ensureHeader() {
  if (headerBuilt) return;
  const head = document.getElementById("feed-head")!;
  head.innerHTML = "";
  elTitle = el("span", "fh-title"); elTitle.textContent = "romp";
  elMeta = el("span", "fh-meta");
  head.append(elTitle, elMeta);    // no toggles, chips, or buttons — one view, nothing clickable
  headerBuilt = true;
}

// ---- ask card (the inbox unit) ----
// Anatomy (the user 2026-06-14): row1 = ask text, full width across the top; row2 = worker
// name (identity color, clickable) on its own row below it; row3 = age bottom-left, status
// badges + Clear bottom-right. Stacking the age/actions onto their own row frees the title
// and the (often long) session name to use the full card width instead of competing for it.
// Click the CARD → expand + light the DAG path on the timeline.
// Expanded body = the request DAG as a tree of NODES (state machine only); each
// node clicks to reveal its OWN reply history; ? nodes carry a decision sub-card.
// ── per-card notification bell (the user 2026-07-28) ─────────────────────────────────────────────
// Every card wears a small bell BUTTON in its bottom-right corner (the user 2026-07-28, round 2 —
// promoted from a right-click-only toggle): click it to arm/disarm an OS notification for when THIS
// card blocks on you or completes (kernel notify-cards.json; the session-wide version lives on the
// timeline lane / tab menu, and the bottom bar's master bell defaults every card ON at once — the
// kernel resolves the three most-specific-wins and sends the effective state, so a click here is a
// per-card override against the defaults). Armed = accent bell, always visible; off = slashed dim bell, revealed on
// card hover (the tab-close idiom — no clutter on a quiet feed). Right-clicking the card still opens
// the labelled menu for the same toggle. Optimism mirrors the lane toggles: pendingNotify holds the
// clicked value sticky across pushes until the kernel's payload agrees, so the bell never flickers
// back while the rebuild lands.
const pendingNotify = new Map<string, boolean>();   // itemId -> clicked value, until the payload confirms
// (the menu's card, its dismissal on a press outside, Escape, a scroll or the window's blur, and its keys are the shared
// builder's: ctx-menu.ts openContextMenu)

// the same drawn bell as the chat tab menu's toggle icon (16-unit viewBox, currentColor, slash = off)
function cardBellSvg(off: boolean): string {
  const slash = off ? '<line x1="1.6" y1="14.4" x2="14.4" y2="1.6"/>' : "";
  return '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" '
    + 'stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">'
    + '<path d="M8 2 C5.9 2.2 4.7 3.8 4.7 5.8 L4.7 8 L3.4 9.9 L12.6 9.9 L11.3 8 L11.3 5.8 C11.3 3.8 10.1 2.2 8 2 Z"/>'
    + '<path d="M6.6 11.6 A1.5 1.5 0 0 0 9.4 11.6"/>' + slash + "</svg>";
}

function cardNotifyOn(it: { itemId: string; notify?: boolean | null }): boolean {
  return pendingNotify.has(it.itemId) ? !!pendingNotify.get(it.itemId) : !!it.notify;
}

// paint the corner bell to a state: armed = accent + unslashed (always visible via .on), off = slashed
// dim (hover-revealed). The title explains the CLICK, so it always describes the opposite state.
function paintCardBell(card: HTMLElement, on: boolean): void {
  const btn = (card as any)._bell as HTMLElement | undefined;
  if (!btn) return;
  if ((btn as any)._bellOn === on) return;   // steady state: never churn the svg under a press (click-safety)
  (btn as any)._bellOn = on;
  btn.classList.toggle("on", on);
  btn.innerHTML = cardBellSvg(!on);
  const say = on ? "system notifications on for this task — click to stop"
    : "notify me when this task blocks on you or completes";
  setTip(btn, say);                                    // styled tip (tip.ts), not a native title
  btn.setAttribute("aria-label", say);                 // the icon-only button keeps an accessible name
}

// the ONE toggle path — the corner bell click and the right-click menu both land here
function setCardNotify(card: HTMLElement, it: AskItem, value: boolean): void {
  pendingNotify.set(it.itemId, value);               // sticky until the kernel's payload carries it
  paintCardBell(card, value);                        // acknowledge instantly, before the round-trip
  vscodeApi?.postMessage({ type: "cardNotify", itemId: it.itemId, sid: it.sid, value });
}

// The kernel's reply to a latched click re-arms THAT button (review find, 2026-09-08). Each card-face latch
// (Retry → "Retrying…", Revive → "Reviving…", Approve/Deny → "Delivering…", Continue → "Sent") holds the
// acknowledgement until the kernel answers its own post (the click-safe rule), and since the per-card update
// gate repaints a card only when the kernel re-sends it, the reply IS the event on a refusal (a success
// re-sends the card, and that repaint re-arms it). Every refusal names the request it answers, and only the
// latch that made that request lets go: `reviveFailed` names the revived id (the parked card's sid IS that id,
// and its blocked.toSid), `retryRefused` and an `err` whose op is apiRetry name the session
// names the held message's mid, an `err` whose op is askFollowUp names the card. A reply that names a session
// but no request (an `err` from a kernel older than the op field) releases the session's Retry and Revive, as
// it did before; one that names neither releases nothing: it answers no request, so every latch stays a
// request the kernel has not answered. No clock anywhere. Returns how many buttons let go, so a caller can
// speak only when this page's own click was the one answered (the chat pane voices its own).
type LatchReply =
  | { kind: "revive"; id: string }
  | { kind: "retry"; sid: string }
  | { kind: "followup"; itemId: string }
  | { kind: "session"; sid: string };
function rearmLatches(reply: LatchReply): number {
  let n = 0;
  const arm = (b: HTMLButtonElement | undefined, label: string) => {
    if (b && b.disabled) { b.disabled = false; b.textContent = label; n++; }
  };
  for (const card of [...askEls.values(), ...fsAskEls.values()]) {   // the focused section's copies hold the same latches (T347)
    const a = card as any;
    const it = a._it as AskItem | undefined;
    if (!it) continue;
    const reviveIdle = () => (a._revive && (a._revive as any)._idle) || "Revive";
    switch (reply.kind) {
      case "revive": if ((it.blocked?.toSid || it.sid) === reply.id) arm(a._revive, reviveIdle()); break;
      case "retry": if (it.sid === reply.sid) arm(a._apiRetry, "Retry"); break;
      case "followup":
        if (it.itemId === reply.itemId && a._cont && (a._cont as HTMLButtonElement).disabled) {
          arm(a._cont, "Continue");
          (a._cont as HTMLButtonElement).title = contTitle(false, "a continue", it.followupAt);
        }
        break;
      case "session": if (it.sid === reply.sid) { arm(a._apiRetry, "Retry"); arm(a._revive, reviveIdle()); } break;
    }
  }
  return n;
}

function showCardMenu(e: MouseEvent, card: HTMLElement): void {
  const it = (card as any)._it as AskItem | undefined;   // the freshest payload copy (updateAskCard stashes it)
  if (!it) return;
  const on = cardNotifyOn(it);
  const icon = el("span", "ctx-icon" + (on ? "" : " off"));
  icon.innerHTML = cardBellSvg(!on);
  const items: CtxItem[] = [{ icon, label: on ? "Stop notifying" : "Notify me",
    sub: on ? "no more system notifications for this card" : "system notification when this card blocks on you or completes",
    pick: () => setCardNotify(card, it, !on) }];
  // Browse the session's working tree. Only the sid rides: the feed payload doesn't carry cwd, and
  // "." lets the OWNING kernel resolve it authoritatively (_resolve_open_path) rather than this pane
  // scraping another pane's state. Gated on canPreview() (web only): the VS Code webview can't reach
  // the kernel origin, and the editor has its own explorer.
  if (canPreview()) items.push({ label: "Browse files", pick: () => openFileBrowse(".", it.sid) });
  openContextMenu(e.clientX, e.clientY, items);   // at the cursor, clamped inside the pane (the shared card)
}

function makeAskCard(it: AskItem): HTMLElement {
  const card = el("div", "fitem ask");
  card.dataset.key = "a:" + it.itemId;
  const main = el("div", "fitem-main");
  // ROW 1 — ask title (left, wraps) with the TIME trailing it, right-justified on the title's LAST line
  // (the user 2026-07-07): small + faded so it reads as metadata, not part of the title. The title still
  // must NOT flex-grow (blank space right of it would trigger locate) — the time's margin-left:auto right-
  // aligns it instead. Freeing the time from row3 lets Background/Summary own that row (one on each side).
  const row1 = el("div", "fask-row1");
  const title = el("div", "fcard-title nav"); title.title = "locate this in the text";
  const time = el("span", "ftime");
  row1.append(title, time);
  // ROW 2 — the session name on its own row, directly below the title
  const row2 = el("div", "fask-row2");
  const idwrap = el("div", "fask-id");
  const name = el("a", "fname"); name.title = "open this session";
  idwrap.append(name);
  const actions = el("div", "fask-actions");
  // THE STATE BADGES of the name row (a delegation's origin, "↩ re-judging", "done, confirming", "follow-up failed", "interrupting…",
  // "interrupted", the "warning" chip, "Awaiting <peer>", "↪ delegated to") are drawn by the shared builder (card-sections.ts stateBadges)
  // into this one slot on every update, with the card's conditions, precedence and order; the Needs you row draws the same badges from the
  // same fields. The slot is display: contents, so the badges stay row2's own flex items and wrap with the name as they always did.
  const badges = el("span", "fask-badges");
  const blkBadge = el("a", "fask-blocked"); blkBadge.style.display = "none";   // ⏸ live permission/picker block → click opens the session
  const apiBadge = el("span", "fask-apierror"); apiBadge.textContent = "⚠ API error"; apiBadge.style.display = "none";   // red: session stopped on an API error
  // filled red (a new chip, deliberately distinct from the outlined api-trouble family): romp's OWN
  // analysis of this session is refused on its credential — the session may be fine; the judges are
  // down, and every card here is frozen until the user fixes the key/login (the user 2026-08-12)
  const jauthBadge = el("span", "fask-jauth"); jauthBadge.style.display = "none";
  // "⚠ retrying since HH:MM" (the user 2026-07-09): the session's OPEN turn is inside an api-retry storm —
  // still in motion, so the card stays in Working, but the storm must be visible: the API-error badge above
  // only fires once the session is idle-stalled, and nimbus's card read plain healthy "Working" through an
  // ~80-minute storm. Same red api-trouble family, faded (in motion, not stopped); no Retry button — the
  // auto-retry is already doing that.
  const retryBadge = el("span", "fask-retrying"); retryBadge.style.display = "none";
  const apiRetry = el("button", "fdismiss fretry"); apiRetry.textContent = "Retry"; apiRetry.title = "send “retry” into this session to resume"; apiRetry.style.display = "none";
  // the auth-expired card offers THE FIX, not just the problem (T157, the user: watch it, log in,
  // it works again): opens the gear's Billing login — the paste-code flow that works from the phone
  const apiLogin = el("button", "fdismiss ffollow"); apiLogin.textContent = "Log in…";
  apiLogin.title = "open Billing login — sign in from any browser (your phone works) and this session recovers on its next turn";
  apiLogin.style.display = "none";
  // CAP-SWITCH OFFER (the user's binding ruling, 2026-08-30: a session must NEVER silently switch
  // billing in either direction): a login-billed session dead on the account's usage cap gets an
  // explicit offer to bill the key for the rest of the window — the pick is the user's alone, and
  // switching back is equally manual. Declining is just Clear; the kernel stops minting the offer
  // the moment the window resets (the deciding event), and the post-reset auto-retry runs either way.
  const capLine = el("span", "fask-capoffer"); capLine.style.display = "none";
  const capBtn = el("button", "fdismiss fcapswitch") as HTMLButtonElement;
  capBtn.textContent = "Switch to the key"; capBtn.style.display = "none";
  const revive = el("button", "fdismiss frevive"); revive.textContent = "Revive"; revive.title = "bring this offline session back so the parked hand-off is delivered"; revive.style.display = "none";
  // RESUME-GATE buttons (the user 2026-07-21): a boot-deferred high-context session — Proceed reloads it now,
  // Compact on resume /compacts first so future turns shrink (still one reload now), Skip leaves it dormant.
  // QUARANTINE buttons (per-host trust): a held message from a DIRECTED peer — Approve delivers it,
  // Edit opens the modal to change the text before delivering, Deny drops it. Human-in-the-loop is the
  // whole point of directed trust, so nothing reaches the session until one of these is clicked.
  // The header "awaiting" chip was REMOVED (the user 2026-07-04): it duplicated the "Awaiting background
  // agents" box in the card body, which says the same thing with room for the full "why" — so the chip was
  // pure redundancy. The awaiting state now reads only from that body box (see the awaitSpin block below).
  const clr = clearButton("clear this task");   // plain-spoken (the user 2026-07-13, over the inbox-zero jargon)
  // "Continue" (the user 2026-08-08): the needs-you card's one-click "nothing needed from me, keep
  // going" — a REPLY with a kernel-canned body (askFollowUp cont:true), never a bare column move (the
  // removed cardMove is the cautionary tale: a move with no message adds no information). The card
  // history that earned it (2026-07-25..08-08): 58% of blocked episodes resolved with no input on the
  // card, and a fifth of Clears landed on sessions visibly mid-turn — a "stop" sent where the user
  // meant "keep going". Shown only on live needs-you cards without a live ask (updateAskCard).
  const cont = el("button", "fdismiss fcontinue") as HTMLButtonElement; cont.textContent = "Continue";
  cont.title = "nothing needed from you — tells this session to keep going and decide open questions itself";
  cont.style.display = "none";
  // The action corner (the user 2026-08-08): Continue+Clear ride the END of row1 in EVERY mode —
  // right-justified beside the timestamp when there's room, dropping below when the title/time need
  // the width (they keep first claim). wrap-reverse stacks the overflow line UNDER the first, so when
  // only one button fits per line Clear stays the higher one; on one line Continue sits left of Clear
  // (source order). Generalizes the grouped-mode float (2026-07-13) to all modes — the re-home dance
  // between rows is gone, which is the strongest form of the click-safety rule (the buttons never move).
  const btns = el("span", "fask-btns");
  btns.append(cont, clr);
  // The card-face "Status?" sweep was REMOVED (the user 2026-07-21): a card still Working doesn't need a
  // status poke from the card face, and once the decision brief carries a paragraph per blocked sub-goal
  // (the briefer's per-sub-goal takeaway) the summary already says where each thing stands, so the sweep was
  // redundant clutter on the face. The sweep still lives one click deeper as the modal footer's "Check
  // status" (feed-modal-status), and each sub-goal keeps its own "Check status" in the modal tree.
  // Manual "Nudge" REMOVED (the user 2026-06-30): once Auto Nudge is robust you never hand-nudge — the
  // background nudge follows up on a stalled working goal automatically, so the manual button (and the whole
  // concept of manually nudging) is gone. Working cards now have no footer action of their own.
  // The card's own "Follow up" button was REMOVED (the user 2026-07-01): click-to-cite covers it — clicking the
  // card (its summary or a sub-goal) drops a dismissible context chip in the chat composer, so a follow-up
  // needs no dedicated button. The MODAL keeps its Follow up (feed-modal-follow) for reading-then-replying, and
  // the modal tree keeps its per-sub-goal Follow up.
  // Session-STATE badges (⏸ approval / ⚠ API error / ⏳ waiting) ride the SESSION-NAME row, right after the
  // name — they describe the session's live state, and keeping them OFF the action row stops them shoving
  // the buttons past the card's right edge on a narrow card (the user 2026-06-19; mirrors the ↻ Followed-up
  // chip moved up 2026-06-18). idwrap is flex:1 so the name ellipsizes before the badge is ever clipped.
  // COMPACTNESS (the user 2026-07-07): Clear rides the NAME row (right side, after the chips) and the
  // Background/Summary toggles ride the TIME row — freeing a whole action row. So the action row holds only
  // Retry / Revive (rare states); both rows flex-WRAP so nothing overflows or overlaps on a narrow card.
  actions.append(revive);   // (the held-mail Approve and Deny left this row 2026-09-19: a notice card's stored actions now)
  // "↪ from <peer>" provenance + the "reopened"/"↻ Followed up" chips ride the name row's right side;
  // row2 wraps them onto a new line when there isn't room, so the provenance never overlaps a chip
  // (the user 2026-06-20). origin sits left of the chips, matching the "from … · Followed up" reading order.
  // (Clear left this row 2026-08-08 — it rides row1's action corner in every mode now, see fask-btns.)
  // EVERY session-state badge rides row2 DIRECTLY — grouped mode hides idwrap wholesale (the card
  // drops its name into the session header), which silently blanked whatever lived inside it: first
  // found as the lone red Retry (the user 2026-08-24, screenshot — its ⚠ badge sat hidden in the
  // wrap), then the same mechanism for ⚠ retrying-since, judge-auth, and the ⏸ approval chip. As
  // direct children they render in BOTH modes, count toward row2's grouped-mode liveness, and the
  // API badge stays immediately before its Retry button — one visual unit. idwrap keeps only the
  // name. Placement only; every badge's mint/retire semantics are untouched.
  row2.append(idwrap, retryBadge, apiBadge, apiRetry, apiLogin, capLine, capBtn, jauthBadge, blkBadge, badges);
  // the bell BUTTON (the user 2026-07-28): INLINE in row1's metadata cluster, right after the
  // timestamp (the last line's tail), the one spot that never shoves the title — and in-flow, so it
  // cannot overlap the floated Clear. It hides with VISIBILITY, so its slot is reserved whether or
  // not the pointer is over the card (the user 2026-07-31): round 4's display:none made an off bell
  // cost zero space, but then hovering materialized it into that line and re-wrapped the title,
  // moving everything below it — layout must not shift because the mouse moved. Session-level arming
  // shows on the lane/tab instead, so an armed SESSION doesn't stamp every card.
  const bellBtn = el("button", "fask-bellbtn");
  bellBtn.onclick = (ev: Event) => {
    ev.stopPropagation();                            // never open the modal under the toggle
    const cur = (card as any)._it as AskItem | undefined;   // freshest payload copy, not this closure
    const live = cur || it;
    setCardNotify(card, live, !cardNotifyOn(live));
  };
  row1.append(bellBtn);   // inline after the time — the metadata cluster's tail
  row1.append(btns);      // the action corner floats from the END of the flow, so title+time keep first claim
  // ROW 3 — Background (left) · Summary (right), always one line, opposite sides. Populated below, once the
  // toggle buttons exist (they're declared with the distiller sections). The time now trails the title (row1).
  const row3 = el("div", "fask-row3");
  // the user's handoff spec (2026-06-10): below the main session, list the OTHER
  // sessions this ask was handed to — but only while they are LIVE-WORKING on
  // an unfinished branch. Idle or finished recipients disappear; presence on
  // the list therefore always means active, so the dot is always on.
  const delegations = el("div", "fask-delegations");
  // The DISTILLER's own line, restored 2026-06-29 (the user: show everything the distiller produces — just NOT
  // the planner's why-created/why-blocked/why-done rationales). One line per card: a completed card shows the
  // takeaway (summary), a blocked card the decision brief (blockSummary). Shown ONLY once it exists — no
  // generating-state placeholder (which used to stick) and no why tooltip. Filled in updateAskCard.
  // TWO collapsible sections since 2026-07-02 (the user: "I come back after a long time and forget the
  // context"): BACKGROUND (re-orientation, collapsed by default) above the takeaway (expanded by default),
  // each toggled by a small +/− button. Collapse state lives in module sets keyed by itemId so the keyed
  // incremental re-render never snaps a section shut.
  // Collapsed sections are REAL buttons — "background" / "summary" in the Clear button's chrome — and
  // sit SIDE BY SIDE on one row when both are collapsed (the user 2026-07-02, round 5). The whole thing
  // is ONE flex-wrap container: the full-width bodies force their own lines, lone buttons share a row.
  // Open, the body runs the full card width and its collapse control is a block "less" button on its own
  // line under the text, always bottom-left (the old trailing-inline placement wrapped unpredictably).
  // TOGGLE buttons (the user 2026-07-02, round 7 — replaces the separate less control): the Background /
  // Summary buttons are always-visible press toggles, capitalized like Clear. Both collapsed → the two buttons
  // sit side by side on one row. Expanding background splits them apart — each button heads its own
  // content — with one clear line between the background part and the summary part; expanding only the
  // summary keeps the buttons side by side with its text below. A pressed toggle wears .on (bright +
  // filled) so what's showing is visible at a glance; clicking again collapses.
  // the section toggles (Background · Summary · Stalled · Sub-goals · Awaiting task), the bodies they drive, the sub-goal checklist and the
  // awaiting swirl come from the shared builder (card-sections.ts buildSectionElements), so the Needs you row builds the same elements in
  // the same order and neither page hand-builds the other's; the toggles ride row3, GROUPED left, wrapping together as a block (the user
  // 2026-07-08), with Retry/Revive (rare) trailing on the right (actions)
  const se = buildSectionElements();
  const { bgBtn, bgBody, takeBtn, distill, subBtn, stallBtn, stallBody, taskBtn, taskLbl, secs, checklist, awaitSpin, awaitWhy } = se;
  secs.style.display = "none";
  row3.append(...se.toggles, actions);
  // NOTICE CARD (T370): the producer label beside the session name, then the body, the attachment and the actions, all
  // hidden until updateAskCard finds it.notice. The body is the sanitizer's inert DOM adopted (never innerHTML), the
  // attachment an image the kernel already judged and pinned, the actions buttons the kernel executes (noticeAction).
  const nprod = el("span", "fask-nprod"); nprod.style.display = "none";
  row2.appendChild(nprod);
  const nbody = el("div", "fask-nbody"); nbody.style.display = "none";
  const nattach = el("div", "fask-nattach"); nattach.style.display = "none";
  const nactions = el("div", "fask-nactions"); nactions.style.display = "none";
  main.append(row1, row2, row3, secs, nbody, nattach, nactions, awaitSpin, checklist, delegations);   // no expand button: body click opens the modal
  card.append(main);
  // Follow-up lives in the modal now (the user 2026-06-10), not on the card.

  // title → locate the turn the card stands for. A normal card anchors on "prompt" (the originating
  // user message). A DELEGATION card (it.origin) has NO originating user prompt — it was planted by a
  // peer's postal message — so "prompt" lands on whatever user turn is nearest in time (an unrelated
  // message — the user hit this). For origin cards anchor on "work" instead, landing where the
  // delegation was processed, mirroring the modal tree-node nav (rompinfra, the user 2026-06-16).
  // agent → open session; Clear → inbox-zero. stopPropagation so the card-body handlers don't also fire.
  let titleAnchor = it.origin ? "work" : "prompt";
  // PREFERRED: the card's root node carries the EXACT turn uuid (kernel 996ebd7) → id-based deep-link,
  // killing the nearest-time miss (delegation cards land on where the work happened, not an unrelated
  // user message). The card's root node is the one whose id IS the card's itemId. Null → time fallback.
  // (The chat's kind guard still refuses a non-user uuid for "prompt"-intent, so a normal card with only
  // a reply uuid falls back to time as before — no regression; delegation "work" cards deep-link.)
  // The root node carries TWO uuids (bugs 92e23ff): anchorUuid = the WORK turn (where it resolved), and
  // promptAnchorUuid = the user's MINTING message (a user turn). A "prompt"-intent title jumps by the prompt
  // uuid (resolves by id on the user turn — no kind-guard refusal, no time-landing heuristic); a "work"
  // (origin) title keeps the work uuid. cardAnchorUuid stays the WORK uuid — goNoted (the why-line) reuses it.
  const rootNode = it.tree?.find((n) => n.id === it.itemId);
  const cardAnchorUuid = rootNode?.anchorUuid ?? null;
  let titleUuid = titleAnchor === "prompt" ? (rootNode?.promptAnchorUuid ?? null) : cardAnchorUuid;
  // No minting user message — an autonomous NOTE the agent wrote itself (no opener), or the opener got
  // compacted off the active path — so a "prompt" jump has nothing to land on and used to honest-fail with
  // the "couldn't locate this in the transcript" toast. Fall back to WHERE THE NOTE WAS WRITTEN: the work
  // turn (an assistant turn). That needs anchor "work" so the chat's kind guard accepts a non-user uuid
  // (a "prompt" intent refuses an assistant turn). (the user 2026-06-30.)
  if (titleAnchor === "prompt" && !titleUuid && cardAnchorUuid) { titleAnchor = "work"; titleUuid = cardAnchorUuid; }
  // A PROVISIONAL placeholder has no goal node / timeline anchor — clicking anywhere just opens the live
  // session (go see what it's working on); the modal, timeline deep-link, and path-hover are all skipped.
  title.onclick = (ev) => { ev.stopPropagation(); if (isOwnerless(it.sid)) { fullscreenAskId = it.itemId; renderModal(); return; } if (it.provisional) { openOrReviveSession(it.sid, it.live, it.name); return; } focusEcho(it.sid); vscodeApi?.postMessage({ type: "showOnTimeline", itemId: it.itemId, sid: it.sid, t: it.t, anchor: titleAnchor, anchorUuid: titleUuid }); };   // an owner-less card: the title opens the card, never a session gesture (round three of PR 1831)
  // (The auto-line is plain text now — no deep-link — so no onclick here; its hover tooltip = the planner's
  // why, set in updateAskCard. The inline sub-goal checkmarks remain clickable via wireNodeZones.)
  name.onclick = (ev) => { ev.stopPropagation(); openOrReviveSession(it.sid, it.live, it.name); };
  clr.onclick = (ev) => {
    ev.stopPropagation();
    // Flush this card's cross-surface hover highlight NOW: clearing removes the card, so its own mouseleave
    // never fires and the timeline/chat highlight stuck until you moved the mouse (the user 2026-07-03). The
    // synthetic mouseleave runs the exact leave logic (clears the highlight, or restores a pinned card's).
    card.dispatchEvent(new MouseEvent("mouseleave"));
    dressHeaderIfLast(askEls.get(it.itemId) ?? card, it.sid);   // the run's last card takes its header with it — one motion (2026-08-24); the BOARD's element when Clear came from the section's copy (T347)
    pendingCleared.add(it.itemId);   // suppress from incoming pushes until the kernel confirms the clear
    pushClearedEntry([(card as any)._it ?? it]);   // cache the FRESHEST payload copy for an instant optimistic Undo (the closure's `it` is the card's creation-time object)
    // BY ITEM, not by this element (T347): the focused-session section holds a second element for the same
    // card, and Clear on either copy clears the card, so both wear .dismissing now and both leave together.
    // The stale-timeout guard is per element: a render inside the window that revived the card (its update
    // resets the class) or replaced its element leaves that copy alone.
    for (const c of cardTwins(it.itemId)) c.classList.add("dismissing");
    vscodeApi?.postMessage({ type: "askClear", itemId: it.itemId, sid: it.sid });
    setTimeout(() => {
      const twins = cardTwins(it.itemId).filter((c) => c.classList.contains("dismissing"));
      if (!twins.length) return;
      // …and the registry (card-sections.ts): a departed host never waits for a read of its item or a Collapsed flip
      for (const c of twins) { c.remove(); unregisterSectionHost(it.itemId, c); if (askEls.get(it.itemId) === c) askEls.delete(it.itemId); if (fsAskEls.get(it.itemId) === c) fsAskEls.delete(it.itemId); }
      dropDismissed([it.itemId]);
    }, 180);
  };
  cont.onclick = (ev) => {
    ev.stopPropagation();
    // the kernel supplies the canned body (CONTINUE_TEXT) — the client sends only the gesture, so the
    // copy has one voice-tested home. Ack INSTANTLY (disable + relabel, the click-safety rule), then the
    // same optimistic move a typed reply gets; updateAskCard re-arms the label once the judge has ruled.
    vscodeApi?.postMessage({ type: "askFollowUp", itemId: it.itemId, sid: it.sid, cont: true });
    cont.disabled = true; cont.textContent = "Sent";
    cont.title = contTitle(true, "a continue", null);
    optimisticFollowMove(it.itemId);
    render();
  };
  // HOVER (120ms intent debounce so sweeps don't spam) → white border + preview
  // this card's timeline journey. LEAVE → restore the pinned card's journey, or
  // clear if none pinned.
  let hoverTimer: number | undefined;
  card.addEventListener("mouseenter", () => {
    freezeEnter(it.itemId, isFocusCopy(card));         // hover-freeze: pointer truth, no debounce; which twin holds it (T410)
    if (it.provisional) return;                        // no timeline path for a placeholder
    hoverTimer = window.setTimeout(() => {
      hoverTimer = undefined;
      hoverAskId = it.itemId; applyFocus();
      vscodeApi?.postMessage({ type: "showAskPath", itemId: it.itemId, sid: it.sid, locate: false });
    }, 120);
  });
  card.addEventListener("mouseleave", () => {
    freezeLeave(it.itemId, isFocusCopy(card));         // hover-freeze: leaving the card flushes queued payloads
    if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = undefined; }
    if (hoverAskId === it.itemId) {
      hoverAskId = null; applyFocus();
      const pin = focusAnchorId(pinnedAskId);
      if (pin) vscodeApi?.postMessage({ type: "showAskPath", itemId: pin, sid: sidOfItem(pin), locate: false });   // back to the pin (ask or group)
      else vscodeApi?.postMessage({ type: "showAskPath", itemId: it.itemId, sid: it.sid, off: true });      // clear
    }
  });
  // card BODY single click → open the modal; double click → pin/unpin (locks the
  // journey in place; hovering others still previews, leave returns to the pin).
  // the shared builder's clicks (the badges, the line and its paragraphs, the awaited peers, the sub-goal triangles): one binding on the card,
  // the stable root above nodes rebuilt on every update (ui/CLAUDE.md, click-safe controls; these controls wear the repository's press pulse
  // now), installed BEFORE the card's own click below so an act's stopImmediatePropagation keeps the modal shut (round three of the box content PR)
  delegate(card, sectionActs(sectionEnv, () => card));
  // Debounced ~220ms so a double never opens the modal first.
  let pending: number | undefined;
  card.addEventListener("click", () => {
    if (it.provisional) { openOrReviveSession(it.sid, it.live, it.name); return; }   // placeholder → open the session
    if (pending) { clearTimeout(pending); pending = undefined; return; }   // 2nd click — let dblclick handle it
    pending = window.setTimeout(() => {
      pending = undefined;
      fullscreenAskId = it.itemId;
      vscodeApi?.postMessage({ type: "cardOpened", itemId: it.itemId, sid: it.sid });   // the open-metric row (2026-08-25)
      vscodeApi?.postMessage({ type: "showAskPath", itemId: it.itemId, sid: it.sid, locate: false });
      render();
    }, 220);
  });
  card.addEventListener("dblclick", () => {
    if (it.provisional) return;                        // a placeholder can't be pinned (no timeline path)
    if (pending) { clearTimeout(pending); pending = undefined; }
    pinnedAskId = pinnedAskId === it.itemId ? null : it.itemId;
    applyFocus();
    // double-click = PIN + jump the TIMELINE to the painted DAG (the user's
    // ruling: hover/single-click only highlight; only a double pans)
    if (pinnedAskId === it.itemId) vscodeApi?.postMessage({ type: "showAskPath", itemId: it.itemId, sid: it.sid, locate: false, jump: true });
    else if (!pinnedAskId && hoverAskId !== it.itemId) vscodeApi?.postMessage({ type: "showAskPath", itemId: it.itemId, sid: it.sid, off: true });
  });

  // right-click → the per-card bell menu (the user 2026-07-28). Reads the FRESH item off the card
  // (a._it, restashed every updateAskCard) — the closure's `it` goes stale after the first push.
  card.addEventListener("contextmenu", (ev) => {
    if (it.provisional) return;                    // a placeholder has no stable identity to arm
    ev.preventDefault(); ev.stopPropagation();
    showCardMenu(ev, card);
  });

  const a = card as any;
  a._title = title; a._name = name; a._time = time; a._badges = badges;
  a._bell = bellBtn;
  a._row1 = row1; a._row2 = row2;   // grouped mode re-homes Clear between these (the user 2026-07-13)
  a._blocked = blkBadge;
  a._apiBadge = apiBadge; a._apiRetry = apiRetry; a._apiLogin = apiLogin; a._retryBadge = retryBadge; a._revive = revive; a._clr = clr;
  a._capLine = capLine; a._capBtn = capBtn;
  a._jauthBadge = jauthBadge;
  a._cont = cont;
  a._nProd = nprod; a._nBody = nbody; a._nAttach = nattach; a._nActions = nactions;
  a._delegations = delegations;
  a._checklist = checklist;
  a._distill = distill;
  a._secs = secs; a._bgBtn = bgBtn; a._bgBody = bgBody; a._takeBtn = takeBtn; a._subBtn = subBtn;
  a._stallBtn = stallBtn; a._stallBody = stallBody;
  a._taskBtn = taskBtn; a._taskLbl = taskLbl;
  a._awaitSpin = awaitSpin; a._awaitWhy = awaitWhy;
  return card;
}

// Which card section a card shows — the three sections are MUTUALLY EXCLUSIVE (the user 2026-07-08, was
// bg/summary only): "bg" | "summary" | "subgoals" | "none". At most ONE open at a time, or none. Keyed by
// itemId in a module map so the keyed incremental re-render never snaps a section shut. Absent = the DEFAULT,
// which the footer "Collapsed" toggle sets: OFF → "summary" open (a completed card's takeaway shows); ON →
// "none" (collapsed), so NEW cards arrive collapsed too. Clicking a toggle sets an explicit per-card override
// (click the open one → off; click another → switch) that survives the mode.

// ── disclosure state across a reload (the user 2026-07-24) ────────────────────────────────────────────
// A kernel restart reloads this page, which used to wipe every section you had opened. The five collections
// above are exactly the state worth carrying: what the USER chose to open. Everything else module-level here
// is a DOM cache or an in-flight optimistic record, and restoring those would resurrect predictions made
// against a kernel that no longer exists — see feed-view-state.ts.
// Column-layout state (the user 2026-08-16; drag extended to BOTH layouts 2026-08-24): which
// categories are folded to their header, and the dragged column order — ONE order, two renderings
// (the user thinks of the two layouts as one arrangement): a drag in either layout re-sequences both. Layout
// state, not card state — prune-exempt, persisted with the rest (the key stays `order`, so an
// arrangement dragged before the merge survives it).
const collapsedCols = new Set<string>();
let colOrder: string[] = [];                         // [] = each layout's own CSS default
// THE FOCUSED SESSION section (T347, the user 2026-09-11, who wanted the focused session's cards on top): the
// chat pane's active tab, relayed by the kernel as {type:"activeChat", id} to the feed clients of the same
// window (on every tab switch, and once when this client registers), and the View menu's switch that puts
// that session's cards above a divider. The switch is view state (persisted with the rest, prune-exempt,
// OFF by default); the sid is not persisted — a reloaded feed registers and is told again.
let focusedSid: string | null = null;
let showFocused = false;
// THE SWITCH ON THE LOCAL SIGNAL (T416, the user 2026-09-14, whose chat tab moved at once on a feed click while this
// section took long to follow). Measured on the served dashboard page: the kernel relays activeChat within 4 to 22 ms
// of the chat's activeTab post and the rebuild here takes 2 to 6 ms, one to two frames end to end; the lag was this
// pane's hover-freeze parking the frame as focusStale while the pointer rested on the header or card the reader had
// just clicked, for as long as it rested there. The section now moves on the LOCAL signal, at once and through the
// freeze when the signal is the reader's own gesture (never a push): this pane's own jump into a session (every
// openSession and showOnTimeline post, noted in the ONE place they all pass, the host api's postMessage above, and
// only when the post runs inside the reader's input event and outside a render) and the chat's active-tab change
// handed across the page by the shell ({romp: "activeChat", id, nonce, gesture}: the chat posts its tab to the parent
// on every switch, the shell hands it to the feed pane; a kernel-driven switch, a focus frame or a re-activation,
// arrives with gesture false and defers under a held card exactly as a push does). The kernel's frame then
// reconciles: focusPending holds the locally applied session against a frame built before the kernel took the
// switch (the strip's pending rule, tab-meta.ts): only the ECHO clears it, the frame carrying the pending session
// and, when both sides know it, the chat's announcement number (a burst of switches faster than the round trip
// returns the same session under different numbers), or the kernel's marked reaffirm (its answer when a jump
// reached a closed session and the chat got its confirmRevive instead of a tab change); a disagreeing frame yields
// and never wins by count (an event, never a count: the round-two review). A standalone /feed page has no shell: its
// own clicks still switch at once, and a strip click reaches it on the kernel's frame as before. An open card menu
// (tabScopeKey) still defers the paint to its release: its anchor must stand.
// THE JUMP SCROLL (T414, folded in here): with the section on, this pane's own Summary or card jump into a session (a
// showOnTimeline post) scrolls the feed's box to the top with the same switch, so the section, now showing that
// session's cards, is in view; a session name or a peer chip (an openSession post) only switches. The click is the
// event and nothing waits on a frame, so a jump that changes no tab leaves nothing standing. A jump into a session
// this pane knows to be closed switches and scrolls nothing (the kernel answers the chat's confirmRevive; no tab
// changes). A plain scroll, no animated chase: the reader's own gesture's consequence.
let focusPending: { sid: string | null; nonce: number | null } | null = null;
// render time (T416 round two): render() and renderModal() hold these while they run, so a post a render makes (a
// handler assignment once missing its braces posted a jump on every push) can never read as the reader's jump
let inRender = false;
let inModalRender = false;
// a reader's gesture arriving THROUGH a frame (the shell's revealCard for a bell click or a notification tap, marked
// gesture on the frame): honoured for the post that frame makes (round three)
let frameGesture = false;
function scrollFeedTop(): void {
  const list = document.getElementById("feed-list");
  if (list) list.scrollTop = 0;
}
/** This pane's own jump into a session, read off the post every jump makes: the section follows at once. Only a post
 *  made inside the reader's input event (a click, a key) and outside a render counts; a showOnTimeline (a Summary or
 *  card jump) also scrolls the feed's box to the top (T414), an openSession (a session name, a peer chip) only switches. */
function noteOwnJump(m: any): void {
  if (!m || (m.type !== "openSession" && m.type !== "showOnTimeline")) return;
  if (inRender || inModalRender || !(inInputEvent() || frameGesture)) return;   // a render-time or unprompted post is no gesture of the reader's
  const sid = typeof m.id === "string" && m.id ? m.id : typeof m.sid === "string" && m.sid ? m.sid : "";
  if (!sid || !focusedIdentity(sid).live) return;   // a closed session's jump changes no tab, so it moves nothing here
  applyLocalFocus(sid, m.type === "showOnTimeline", true, null);
}
/** The section follows a local signal: `jump` scrolls the box to the top (this pane's own Summary or card jump, T414);
 *  `gesture` says the switch is the reader's own, which passes the hover-freeze (a kernel-driven switch relayed by the
 *  shell defers under a held card like a push); `nonce` is the chat's announcement number the kernel echoes. */
function applyLocalFocus(sid: string | null, jump: boolean, gesture: boolean, nonce: number | null): void {
  const changed = sid !== focusedSid;
  focusedSid = sid;
  if (changed) focusPending = { sid, nonce };   // held until the kernel's echo of this very switch, or its marked answer
  else if (focusPending && focusPending.sid === sid && nonce != null) focusPending.nonce = nonce;   // the chat announcing the switch this pane made: its echo is the one to wait for
  if (!showFocused) return;
  // the reader's gesture paints whether or not it changed the record: when the kernel's frame beat the shell's relay for
  // the same switch under a held card, the frame parked the paint (focusStale) and the relay finds nothing changed; the
  // gesture releases that park and paints now (the round-three review: the original lag, restored by a coin-flip order)
  if (changed || (gesture && focusStale)) {
    if (tabScopeKey || (!gesture && freezeKey)) focusStale = true;   // an open card menu, or a held card under a switch the reader did not make: the paint waits for the release (T347)
    else { render(); focusStale = false; }
  }
  if (jump) scrollFeedTop();   // the reader asked to look at this session's cards, the one already focused included (T414)
}
// The section's OWN block layout (T410, the user 2026-09-13, who wanted the section's blocks movable, resizable
// and collapsible on their own, none leaving the section): its dragged block order ([] = follow the board's
// arrangement, as the section did from T347), the blocks' flex weights by column key (a missing key = 1, the
// equal split) and the collapsed block keys, applied to WHICHEVER session is focused. Layout state like
// collapsedCols/colOrder: persisted with the rest, prune-exempt, painted by applyFocusLayout.
let focusOrder: string[] = [];
let focusW: Record<string, number> = {};
// PROVENANCE of the stored focusOrder (T410 review): true while it was minted by the arrow keys out of a FOLLOWING
// state (a key sequence the user can walk back), false once a drag pinned it or the board's own order moved (the
// arrangement the section follows changed under it). The keys' no-trace rule clears the stored order only under
// this flag: an arrow press that happens to land on the followed arrangement must never clear an order the user
// pinned by DRAG (one press cleared a drag-pinned section, and a board drag then rearranged it). Not persisted: a
// reload reads any stored order as pinned, the conservative side.
let focusOrderByKeys = false;
const collapsedFocusCols = new Set<string>();
// The whole section folded to its LABEL (T410b, the user 2026-09-14): "Current session: <name>" alone, the blocks,
// their cards and the quiet line hidden under it, the divider standing. A view switch like showFocused: persisted
// with the rest, prune-exempt; painted by paintFocusFold.
let focusFolded = false;

// ── the board view switch (plans/card-boards.md, phase four, section 8) ─────────────────────────────────────────
// ONE board shows at a time: the feed, or a data-defined board the frame carries. The pick is the feed pane's own view
// state (FeedViewState.board, prune-exempt) from the View menu's Board rows, or the page's ?board= query (the docking
// kit's hook: that pick is the page's, never written to the view state, and the Board rows hide). A pick naming a board
// the frame does not carry (removed, a remote host gone) shows the feed and says so once, never a blank pane; the pick
// stands, so the board comes back on its own when the frame carries it again.
let activeBoardId = "";
let boardQuery = "";
try { boardQuery = new URLSearchParams(window.location.search).get("board") || ""; } catch { boardQuery = ""; }
let boardFallbackSaid = "";
function activeBoard(): Board {
  const want = boardQuery || activeBoardId;
  if (!want || want === FEED_BOARD.id) return FEED_BOARD;
  const b = boardById(want);
  if (b) return b;
  if (boardFallbackSaid !== want) { boardFallbackSaid = want; try { feedToast("Board " + want + " is not on this frame: showing the feed"); } catch { /* before the footer exists */ } }
  return FEED_BOARD;
}
const activeCols = (): readonly Column[] => feedColumns(activeBoard());
/** The ACTIVE board's cards out of a list: the render pass and the hover-freeze hint read the same filter, so the hint counts
 *  what is on screen and nothing else (a card naming an unknown board is the feed's, boardOf). */
const onActiveBoard = (list: AskItem[]): AskItem[] => { const b = activeBoard(); return list.filter((a) => boardOf(a) === b); };
/** A column fold's key in the view state: the feed's columns by their names (as always), a data board's as `<board>:<category>`
 *  so a fold on one board never folds a same-named category on another (the 1886 read, medium 2). */
const foldKey = (key: string): string => (activeBoard() === FEED_BOARD ? key : activeBoard().id + ":" + key);
/** An order the user dragged applies only when it names every column of the ACTIVE board once (the feed's stored order
 *  means nothing on a data board's columns, and a board's order nothing on the feed). */
const orderComplete = (o: readonly string[]): boolean => { const cols = activeCols(); return o.length === cols.length && cols.every((k) => o.includes(k)); };
/** The side-by-side default order: the feed's literal (the build order, pinned), a data board's categories in its order. */
const rowDefault = (): string[] => (activeBoard() === FEED_BOARD ? ROW_DEFAULT : [...activeCols()]);
/** Beside a card's producer: "on an unknown board (<id>)" for a card naming a board this renderer does not know (it renders on
 *  the feed under the default category: the loud fallback, never a silent drop); nothing otherwise. A data board's cards render
 *  on their own board since phase four, so a known board's title never needs saying here (phase three's "on <title>" went). */
function boardLabelOf(it: { board?: string | null }): string {
  return it.board && it.board !== FEED_BOARD.id && boardOf(it) === FEED_BOARD ? "an unknown board (" + it.board + ")" : "";
}
function setActiveBoard(id: string): void {
  const next = id === FEED_BOARD.id ? "" : id;
  if (next === activeBoardId) return;
  activeBoardId = next;
  skipFlipOnce = true; prevCols = new Map();   // a switch is a new board, not cards moving: nothing glides
  persistViewState();
  render();
}

(function hydrateViewState() {
  let st;
  try { st = parseViewState(localStorage.getItem(VIEW_STATE_KEY)); } catch { return; }   // private mode / blocked storage → run without it
  replaceSectionChoices(Object.entries(st.sec) as [string, SecChoice][], { quiet: true });   // through the shared setter: the chat page's row hears it (card-sections.ts); no host exists yet
  for (const k of st.tree) cardTreeExpanded.add(k);
  for (const k of st.nodes) collapsedNodes.add(k);
  for (const k of st.logs) nodeLogOpen.add(k);
  for (const k of st.asks) expandedAsks.add(k);
  for (const k of st.threads) for (const key of threadKeys(k)) collapsedThreads.add(key);   // a pre-T263c bare sid = every column
  for (const k of st.cols) collapsedCols.add(k);
  colOrder = st.order.slice();
  showFocused = st.focused;   // the focused-session section's switch (T347); a blob saved before it reads OFF
  focusOrder = st.focusOrder.slice();   // the section's own block layout (T410); a blob saved before it reads as the defaults
  focusW = { ...st.focusW };
  for (const k of st.focusCols) collapsedFocusCols.add(k);
  focusFolded = st.focusFolded;   // the section's fold (T410b); a blob saved before it reads unfolded
  activeBoardId = st.board;   // the board pick (phase four); a blob saved before it, or naming the feed, reads as the feed
  // the feed OWNS the section choice (card-sections.ts): it posts its hydrated map for a chat page already up and answers a later hello,
  // and a pick that arrives from the chat page's row is persisted here like the card's own
  configureSectionSync({ role: "owner", onChange: () => persistViewState() });
})();

function currentViewState(): FeedViewState {
  const sec: Record<string, string> = {};
  secChoice.forEach((v, k) => { sec[k] = v; });
  return { v: 1, sec, tree: [...cardTreeExpanded], nodes: [...collapsedNodes], logs: [...nodeLogOpen],
           asks: [...expandedAsks], threads: [...collapsedThreads], cols: [...collapsedCols],
           order: colOrder.slice(), focused: showFocused,
           focusOrder: focusOrder.slice(), focusW: { ...focusW }, focusCols: [...collapsedFocusCols], focusFolded, board: activeBoardId };
}

// Written at the END of every render rather than from each toggle handler: the feed re-renders on every
// interaction anyway, so this cannot miss a mutation site as hand-placed save() calls would. render() also
// runs on every kernel push, so the write is gated on the serialised value actually CHANGING — that makes it
// effectively event-driven on real state change, not a per-push localStorage write.
let lastViewWrite = "";
function persistViewState(): void {
  const json = serializeViewState(capViewState(currentViewState()));
  if (json === lastViewWrite) return;
  lastViewWrite = json;
  try { localStorage.setItem(VIEW_STATE_KEY, json); } catch { /* quota / private mode → the feed still works */ }
}

// Self-clean, event-based: the kernel's payload names the full live card set, so anything whose card is gone
// (cleared, archived) is dropped now. `live` must be the UNFILTERED payload — see pruneViewState.
function pruneViewStateTo(live: Set<string>): void {
  const kept = pruneViewState(currentViewState(), live);
  const keep = (s: Set<string>, xs: string[]) => { s.clear(); for (const k of xs) s.add(k); };
  replaceSectionChoices(Object.entries(kept.sec) as [string, SecChoice][], { quiet: true });   // through the shared setter, so the chat page's row drops the same; this render applies every card next
  keep(cardTreeExpanded, kept.tree);
  keep(collapsedNodes, kept.nodes);
  keep(nodeLogOpen, kept.logs);
  keep(expandedAsks, kept.asks);
  keep(collapsedThreads, kept.threads);   // pass-through: a thread stays collapsed with no cards on the board
}


// Paints a card's face from its payload copy. Whether to call it at all is reconcileCol's decision (the
// per-card update gate, feed-card-gate.ts): a card is repainted when its object is a new one or a
// board-level input it reads changed, and left alone otherwise. Everything this function reads outside
// `it` is therefore in that key — an input added here is added there.
// A notice card's body (T370): markdown through the chat's renderer and the one sanitizer, remote loads stripped on the
// inert DOM BEFORE adoption (no request ever starts). Should the sanitizer itself fail (no DOM to build it on, as in a
// document stand-in), the body falls to PLAIN TEXT: nothing unsanitized ever reaches the page, and the card still says its
// words; the served lab reads the rendered form.

// The notice FACE, one body for the card and the card's modal (round four of PR 1831): the producer line (and the board the
// card belongs to when it is not the feed's), the body through the sanitizer, the attachment (the pinned picture where the page
// can reach the kernel, else its name) and the actions as buttons that post noticeAction with the card's sid and latch on the
// click; the kernel's noticeActionDone or the next push re-arms them (the card's rule, PR 1757).
function fillNoticeFace(it: AskItem, nt: NonNullable<AskItem["notice"]>, onBoard: string, nProd: HTMLElement, nBody: HTMLElement, nAttach: HTMLElement, nActions: HTMLElement): void {
  nProd.textContent = (nt.producer ? "via " + nt.producer : "") + (onBoard ? (nt.producer ? " · " : "") + "on " + onBoard : "");
  nProd.title = (nt.producer ? "posted by " + nt.producer + " (revision " + nt.rev + ")" : "") + (onBoard ? (nt.producer ? "; " : "") + "on the " + onBoard + " board" : "");
  nProd.style.display = nProd.textContent ? "" : "none";
  nBody.replaceChildren();
  if (nt.body && nt.body.trim()) nBody.append(...noticeBodyNodes(nt.body));
  nBody.style.display = nt.body && nt.body.trim() ? "" : "none";
  nAttach.replaceChildren(...noticeAttachmentNodes(nt.attachment as any, it.sid));
  nAttach.style.display = nAttach.childNodes.length ? "" : "none";
  nActions.replaceChildren();
  for (const act of nt.actions || []) {
    const b = el("button", "fdismiss fnact") as HTMLButtonElement;
    b.textContent = act.label; (b as any)._idle = act.label;
    b.onclick = (ev: Event) => {
      ev.stopPropagation();
      // the action's KIND rides the wire (an older frame's route reads as send); the click may add only the input the kind
      // names: a held-mail Deny asks for the optional note first, every other action goes at once
      const kind = act.kind || (act.route === "/send" ? "send" : "");
      const go = (input?: Record<string, unknown>) => {
        vscodeApi?.postMessage({ type: "noticeAction", itemId: it.itemId, sid: it.sid, kind, body: act.body, ...(input ? { input } : {}) });
        b.disabled = true; b.textContent = act.label + "…";
        // a card that dismisses on its action resolves on ONE of them (a held message's Approve or Deny): its other buttons
        // latch too until the kernel answers, so a second decision cannot race the first; rearmNoticeButtons lets every one go
        if (nt.dismissOnAction) for (const o of Array.from(nActions.querySelectorAll("button")) as HTMLButtonElement[]) o.disabled = true;
      };
      if (kind === "quarantine" && act.body && (act.body as any).verdict === "deny") showDenyNoteDialog((note) => go(note ? { note } : undefined));
      else go();
    };
    nActions.appendChild(b);
  }
  nActions.style.display = (nt.actions || []).length ? "" : "none";
}

// The modal of a NOTICE card shows the notice (round four of PR 1831, medium 2): the same face as the card, in place of the goal
// tree a notice never has (the tree body read "No work yet." and the title hid, so an owner-less card's title opened an overlay
// with nothing of the card). Rebuilt on every modal render, which is what re-arms a latched button on a push (the card's rule).
function renderNoticeModalBody(host: HTMLElement, it: AskItem, nt: NonNullable<AskItem["notice"]>): void {
  host.innerHTML = ""; (host as any)._sig = "";
  const wrap = el("div", "feed-modal-notice");
  const prod = el("div", "fask-nprod feed-modal-nprod"), nb = el("div", "fask-nbody"), na = el("div", "fask-nattach"), nac = el("div", "fask-nactions");
  fillNoticeFace(it, nt, boardLabelOf(it), prod, nb, na, nac);
  wrap.append(prod, nb, na, nac);
  host.appendChild(wrap);
  (host as any)._nActions = nac;   // the answer handler re-arms or closes through the modal's own buttons
}

// A notice card's action buttons let go on EVERY push, gated or not (the review of PR 1757, medium 2): a click on a down
// socket is dropped and never answered (a kernel restart), and the card gate skips an unchanged card's update, so a latch
// that waited for the card's own update or the kernel's answer read "Send again…" for good. The kernel's noticeActionDone
// and the next push both re-arm; a success on a dismissing card takes the card off at once (the noticeActionDone handler).
function rearmNoticeButtons(card: any): void {
  const acts = card._nActions as HTMLElement | undefined;
  if (!acts || !card._it?.notice) return;
  for (const b of Array.from(acts.querySelectorAll("button")) as HTMLButtonElement[]) { b.disabled = false; b.textContent = (b as any)._idle || b.textContent; }
}

// what THIS page hands the shared section builder (card-sections.ts): the collapsed-by-default preference, the node click zones (the
// modal's and the card's, wireNodeZones), the PR repo a row's links use, the live duration nodes, and how a peer's session is opened
const sectionEnv: SectionEnv = {
  collapsed: () => feedPrefs().collapsed,
  wireNode: (it, node, mark, txt, wire) => { wireNodeZones(it as AskItem, node, mark, txt, null, wire); },
  repoOf: (sid) => prRepoOf(sid),
  durNodes: (since) => durNodes(since),
  openSession: (sid) => { vscodeApi?.postMessage({ type: "openSession", id: sid }); },
  nowSec: () => nowSec(), relAge: (sec) => relAge(sec), ageTint: (sec) => ageColorReadable(sec), clockHM: (t) => clockHM(t),
  // a landing: the timeline (the chat pane in the shell, the timeline view in VS Code) shows the turn; focusEcho first, as every card link
  landing: (it, target) => { focusEcho(it.sid); vscodeApi?.postMessage({ type: "showOnTimeline", itemId: it.itemId, sid: it.sid, t: it.t, anchor: target.anchor, anchorUuid: target.anchorUuid, quote: target.quote }); },
  // Toast AND file it in the error center (the user 2026-07-28): a transient pop-up left no trace of a click that couldn't do anything, so
  // the failure was unreportable a minute later. The entry carries the card so clicking it jumps back here.
  noAnchor: (it) => {
    feedToast("couldn't locate this in the transcript — no anchor was recorded for this card");
    try { window.parent?.postMessage({ romp: "notify", kind: "locate", text: "Couldn't jump to this summary: no anchor was recorded for this card", sid: it.sid, itemId: it.itemId }, "*"); } catch { /* no shell (VS Code view) */ }
  },
  openWarns: (it, title) => { if (it.warns && it.warns.length) feedWarnModal(title, it.warns, { itemId: it.itemId, sid: it.sid }, it.failLog); },   // the warn-detail overlay: what happened and why
  workDot: (peer, name) => setWorkDot(peer, dotFor(name)),   // the board's live working/awaiting dot before a tracked recipient's name
};
function updateAskCard(card: HTMLElement, it: AskItem) {
  const a = card as any;
  a._it = it;   // the freshest payload copy — the right-click bell menu reads this, never a stale closure; and the gate's identity
  // per-card bell: retire the optimistic value once the kernel's payload agrees (event-based, no timer),
  // then render whichever stands. Same sticky-optimism shape as the timeline lane's _pendingFlags.
  if (pendingNotify.has(it.itemId) && !!it.notify === pendingNotify.get(it.itemId)) pendingNotify.delete(it.itemId);
  if (a._bell) (a._bell as HTMLElement).style.display = it.provisional ? "none" : "";   // no stable identity to arm
  paintCardBell(card, cardNotifyOn(it));
  card.className = "fitem ask" + (it.live ? " live" : " dead") + (it.itemId === (hoverAskId ?? pinnedAskId) ? " focused" : "") + (it.itemId === pinnedAskId ? " pinned" : "") + (it.provisional ? " provisional" : "");
  // PROVISIONAL placeholder: a dim, italic, non-interactive card from the live prompt while the planner
  // hasn't classified the in-progress turn yet. No Clear/Nudge (nothing to curate), no auto-line, no tree.
  card.style.opacity = it.provisional ? ".62" : "";
  a._title.style.fontStyle = it.provisional ? "italic" : "";
  const [r, g, b] = it.trgb;
  card.style.background = `rgba(${r}, ${g}, ${b}, ${TINT_ALPHA})`;
  // GHOST prompt: a provisional placeholder gets a dashed outline so it reads as not-yet-real (the user
  // 2026-06-19), distinct from the solid recency-tinted border of a real card. Reset to solid when the
  // planner replaces it with the classified card.
  if (it.provisional) {
    card.style.borderStyle = "dashed";
    card.style.borderWidth = "1.5px";
    card.style.borderColor = "rgba(255, 255, 255, 0.45)";
  } else if (it.recheck) {
    // RE-CHECK: a soft-block you've already replied to — de-urgented with the same dotted treatment as a
    // provisional card (you're no longer the bottleneck), but readable, until the judge resolves or
    // re-blocks it (the user 2026-06-27).
    card.style.borderStyle = "dashed";
    card.style.borderWidth = "1.5px";
    card.style.borderColor = "rgba(255, 255, 255, 0.32)";
  } else {
    card.style.borderStyle = "";
    card.style.borderWidth = "";
    // outline the card in ITS session's identity colour (the user 2026-07-15) — CSS paints it at 0.5α at rest
    // and bolds the SAME colour on hover/pin. Fall back to the recency-tint channels for the rare colourless
    // session so the border never voids to transparent.
    setCardChannels(card, (it.color && hexToRgb(it.color.bg)) || [r, g, b]);
  }
  // a re-check card dims slightly (between a normal card and a provisional ghost) so it reads as "handled, pending"
  if (!it.provisional) card.style.opacity = it.recheck ? ".8" : "";
  setLinkedText(a._title, it.text, prRepoOf(it.sid));   // `#123` in the goal text → its PR page; keyed, so an unchanged title keeps its anchors across pushes (pr-links.ts)
  // an OWNER-LESS notice card has no session chip: no session stands behind it, so no name to open and no dot to paint; the
  // run header above it says Notes (the user 2026-09-18)
  const ownerless = isOwnerless(it.sid);
  a._name.style.display = ownerless ? "none" : "";
  if (!ownerless) {
    a._name.replaceChildren(...hostNameNodes(it.name, it.sid));   // remote "host:" prefix = quiet metadata
    if (it.color) a._name.style.color = it.color.bg;
    setWorkDot(a._name, dotFor(it.name));   // working/awaiting dot before the session name
  }
  // ↪ from <sender> and ↪ delegated to <peer>: state badges, drawn below with the rest (stateBadges) once the swirl caption is known
  // a tracked delegation's recipients: a state badge too (stateBadges), with this page's live dot before each name (sectionEnv.workDot)
  stampAge(a._time, it.t, "plain", false, nowSec(), relAge, ageColorReadable);   // stamped: the 15 s live pass moves it
  // hover the stamp for provenance (the user 2026-07-27): the age marks the NEWEST event (a done card's
  // age is its completion), so the popover tells where the thread came from — started when, each sub +
  // its time, what the stamp marks.
  wireAgeTip(a._time, () => provenanceRows(it, hostNow, PROV_FMT));
  // the name row's state badges (re-judging, done confirming, follow-up failed, the interrupt words, the warning chip, the peer wait, the
  // delegation's origin and handoff) are drawn below, after the swirl's caption is known, by the shared builder (stateBadges)
  a._clr.style.display = it.provisional ? "none" : "";   // a placeholder has nothing to curate — no Clear
  // (The card-face "Status?" sweep was removed 2026-07-21 — see the comment where it used to be declared.)
  // ⏳ awaiting: held in Working, waiting on work it dispatched/delegated (agents, a subagent, a build). The
  // peer case already shows the "Awaiting <peer>" chip (waitingOn), so the generic awaiting box is suppressed
  // then. (The old header "awaiting" chip is gone — the body box below carries it; the user 2026-07-04.)
  // SPINNING SWIRL + a short caption in the card body (the user 2026-06-29): a card with a re-evaluation or
  // dispatched work in flight shows the spinning romp swirl saying what's happening. The whole ladder lives
  // in ./spin-caption so spin-caption.test.ts EXECUTES it — a source-regex pin is what let the recheck /
  // rejudging branches be silently wrong (the user 2026-07-21); see that file for the cases + the contract.
  // distillInputs (in ./distiller-line so the test EXECUTES the rule) maps state→(completed,blocked). A card
  // in the Working column yields neither: a summary describes work that has stopped, so it is withheld while
  // the card is in motion and re-renders untouched when it settles (the user 2026-07-22). See that file for
  // why this supersedes the 2026-07-21 pin-the-brief rule.
  const { completed: dCompleted, blocked: dBlocked } = distillInputs(it.distillState, it.column);
  // The card is not left mute in that window: the Working displacement only happens under recheck/rejudging,
  // and both raise the "Analyzing…" swirl below, which says the judge is looking at it again.
  // A NOTICE card never wears the distiller's placeholder (the user 2026-09-19: an empty card posted from the command line has
  // nothing to distill): its body IS its text and no judge ever reads it, so a null summary on a completed notice (the row
  // stamps summary and blockSummary null) is not a takeaway on its way; the spinner is the goal kind's.
  const spin = cardSpin(it, dCompleted, dBlocked, sectionEnv);   // the swirl ladder over the item's fields (card-sections.ts): one rule with the Needs you row
  applySpin(a, it, spin, sectionEnv);
  const spinCaption = spin.caption;
  // THE STATE BADGES, drawn into the name row's slot with the card's conditions, precedence and order (card-sections.ts stateBadges):
  // "↩ re-judging" on recheck only, and never while the swirl's "Analyzing…" caption already says it (the user 2026-06-29: don't show both)
  a._badges.replaceChildren(...stateBadges(it, sectionEnv, spinCaption));
  // ⏸ live block badge: the session is stopped mid-turn on a permission prompt /
  // picker FOR THIS CARD's work — the card files under BLOCKED while it lasts
  const isApiErr = it.blocked?.state === "apiError";
  const isJudgeAuth = it.blocked?.state === "judgeAuth";
  // the resume-gate card carries its own explanatory text + Proceed/Compact/Skip buttons, so the ⏸ chip
  // (which only speaks permission/picker) would just misread — suppress it there (the user 2026-07-21).
  const showBlk = !!it.blocked && !isApiErr && !isJudgeAuth;
  a._blocked.style.display = showBlk ? "" : "none";
  if (showBlk && it.blocked) {
    // live prompts only — the paused-stall badge retired with the floor (2026-07-07; a failed nudge now
    // records a real block and the follow-up-failed CHIP carries that story)
    a._blocked.textContent = it.blocked.state === "permission" ? "⏸ approval"
      : "⏸ picker";
    setTip(a._blocked as HTMLElement, it.blocked.what + " — click to jump to the prompt in the chat");
    // the prompt (a picker / permission approval) is the session's LIVE bottom → `live` lands the chat right
    // on it, not wherever it was last scrolled (the user 2026-07-08).
    a._blocked.onclick = (ev: Event) => { ev.stopPropagation(); vscodeApi?.postMessage({ type: "openSession", id: it.sid, live: true }); };
  }
  // The DISTILLER's line (restored 2026-06-29): completed card → takeaway (it.summary), blocked card → decision
  // brief (it.blockSummary), shown ONLY when produced; never a generating placeholder, never the planner's why.
  // The rule lives in ./distiller-line so distiller-line.test.ts can EXECUTE it (a regex pin let it silently
  // turn off once — the user 2026-06-29). updateAskCard runs every push, so this re-applies on every refresh.
  const distillShown = it.notice ? (((a._distill as HTMLElement).style.display = "none"), "")   // a notice has no distiller line: its body is the text
    : applyDistillLine(a._distill as HTMLElement, dCompleted, dBlocked, it.summary, it.blockSummary);
  if (distillShown) linkifyPrRefs(a._distill as HTMLElement, prRepoOf(it.sid));   // the takeaway's `#123` links too
  // A judge-auth card explains itself ON THE CARD FACE (the user 2026-08-12: a message, not just a
  // chip): no decision brief can exist here — the distiller is one of the very judges that are down —
  // so the distill line carries blocked.what instead of sitting empty. applyDistillLine re-runs every
  // push, so the line restores itself the moment the latch clears and a real brief/takeaway returns.
  if (isJudgeAuth && it.blocked && !distillShown) {
    const dle = a._distill as HTMLElement;
    dle.textContent = it.blocked.what || "";
    dle.style.display = it.blocked.what ? "" : "none";
  }
  // the line's paragraphs, their per-item ages and their landings (T220 citations first, then the tree row's work anchor), the stale note and
  // the whole line's link to where it was written: the shared builder (card-sections.ts applyDistillLanding), one rule with the Needs you
  // row; this page's landings post showOnTimeline (sectionEnv.landing) and its no-anchor click toasts and files the miss (sectionEnv.noAnchor)
  applyDistillLanding(a, it, distillShown, dCompleted, dBlocked, sectionEnv);
  // TWO collapsible distiller sections (the user 2026-07-02): BACKGROUND (re-orientation for a reader who
  // forgot the thread, collapsed by default) above the takeaway (expanded by default), each with a +/−.
  applySections(a, it, !!distillShown, sectionEnv);   // bg/summary/sub-goals (mutually exclusive): applyDistillLine returns the line's TEXT (string), coerce to "has content"
  // A SESSION-STARTED root (T319): work the session began on its own (a Workflow run, an agent, a thread of
  // its own) that stands as a card only because its parent is gone, no request could host it, or it is
  // blocked (needs-you breaks through). The face says what it is and why in one line, so it never reads as
  // something the user asked for. Its OWN line, created once beside the sections and kept outside them: the
  // distill line lives inside the collapsible sections, whose logic hides it without a takeaway and whose
  // decision brief would otherwise displace the face; both show.
  {
    let fe = a._face as HTMLElement | undefined;
    if (!fe) {
      fe = el("div", "fask-distill fask-face");
      const secs = a._secs as HTMLElement;
      secs.parentNode!.insertBefore(fe, secs.nextSibling);
      a._face = fe;
    }
    const ss = it.sessionStarted;
    if (ss) {
      fe.textContent = (ss.parent ? "Started by the session while working on \u201c" + ss.parent + "\u201d: " : "Started by the session on its own: ") + (ss.why || "");
      fe.style.display = "";
    } else {
      fe.textContent = "";
      fe.style.display = "none";
    }
  }
  // A far host still holds a relayed question after its wait ended (it.relayNote, kernel relayCarried: the
  // question went on before it could be withdrawn, or the host could not be reached to withdraw it). Its OWN
  // line like the face above, created once beside the sections, kept OUTSIDE them and set AFTER the section
  // logic: appended inside the distill element it was hidden with that line (no brief yet → the sections
  // choose none and set the element's display to none; likewise in collapsed mode, on a card whose open
  // section is not the summary, and on a working-column card, where the brief is withheld). Never a
  // paragraph OF the brief either: the per-paragraph stamps map briefParts onto the brief's paragraphs and
  // allow exactly one extra, so a note paragraph dropped every stamp and citation on a briefed top node.
  // The effect is RUN in feed-render-incremental.test.ts (no brief, collapsed mode, a working card); the helper lives in card-sections.ts so the row draws it too.
  applyRelayNote(a, it);   // the shared helper (card-sections.ts): the Needs you row draws the same line after its sections
  // API error → a red "API error" badge + a Retry button that pastes "retry" into the session to resume
  // the stalled turn (the user 2026-06-16). The card STAYS in Working (the user 2026-06-29) — an API error is
  // a transient stall, not a block — so this badge + Retry are the only API-error cue; no column move.
  const spendLimit = !!(it.blocked && it.blocked.spendLimit);
  const modelLimit = !!(it.blocked && it.blocked.modelLimit);
  const refusal = !!(it.blocked && it.blocked.refusal);
  const authErr = !!(it.blocked && (it.blocked as { authErr?: boolean }).authErr);
  // …and the whole unit RETIRES the moment the session recovers (the user 2026-08-24, screenshot: a
  // GREEN awaiting dot beside a lone red Retry — the control read as arbitrary): visibility keys on
  // the session's LIVE state from this very payload — a session working again, or awaiting the
  // background work it dispatched, has resumed, and there is nothing to resume by hand no matter
  // what the card's stored block record still says. The same sets the session dot reads
  // (workingSet/awaitingSet), refreshed on every push — event-keyed, never a timer.
  const apiRecovered = workingSet.has(it.name) || awaitingSet.has(it.name);
  const showApiErr = isApiErr && !apiRecovered;
  a._apiBadge.style.display = showApiErr ? "" : "none";
  // Retry pastes "retry" to resume a stalled turn — useless against a monthly spend cap (retrying can't lift a
  // billing limit), so hide it there and let the badge tell you to raise the cap (the user 2026-07-14).
  // A spent MODEL allowance is the same shape: Retry re-fails until you switch model or top up, and the
  // badge says so (the user 2026-08-01). Its window does reset on its own, which the badge title carries.
  // A safeguards REFUSAL is the same shape again (the user 2026-08-15): deterministic on the same input,
  // so Retry re-collects the same refusal — the badge names the real fix (rewrite it or drop the thread).
  a._apiRetry.style.display = (showApiErr && !spendLimit && !modelLimit && !refusal) ? "" : "none";
  // a dead credential's card carries THE FIX (T157): the gear's Billing login — phone-workable
  const loginBtn = a._apiLogin as HTMLButtonElement;
  loginBtn.style.display = (showApiErr && authErr) ? "" : "none";
  if (showApiErr && authErr) loginBtn.onclick = (ev: Event) => {
    ev.stopPropagation();
    openGear(window);   // the login flow lives in the gear's Billing block (here, or on the shell's settings page)
  };
  // "Continue" shows on a LIVE needs-you card with no live ask attached: the gesture claims "you're not
  // waiting on me", which means nothing in Working/Completed, can't answer a real permission prompt or
  // picker (it.blocked — text sent there would just queue behind the ask), and has no one to tell on a
  // dead session. Re-arm the label only once its own reply has been judged (same contract as the modal's
  // Check status): while followupPending/recheck holds, the disabled "Sent" IS the acknowledgement.
  const contBtn = a._cont as HTMLButtonElement;
  contBtn.style.display = (askColumn(it) === "needsInput" && it.live && !it.provisional && !it.blocked)
    ? "" : "none";
  if (contBtn.disabled && !it.followupPending && !it.recheck && !it.rejudging) {
    contBtn.disabled = false; contBtn.textContent = "Continue";
  }
  contBtn.title = contTitle(contBtn.disabled, "a continue", it.followupAt);
  if (showApiErr && it.blocked) {
    // on-you errors name themselves: a spend cap (raise it), "prompt too long" (compact), or a spent model
    // allowance (switch model); other API errors are transient and auto-retrying (2026-06-29 / 07-14 / 08-01).
    a._apiBadge.textContent = spendLimit ? "⚠ Spend limit"
      : it.blocked.tooLong ? "⚠ Prompt too long"
      : modelLimit ? "⚠ Model limit"
      : refusal ? "⚠ Safeguards refused"
      : it.blocked.status ? `⚠ API error · ${it.blocked.status}` : "⚠ API error";
    // a refusal's raw CLI text buries the remedy — the kernel's `what` states it plainly, so tip with that
    setTip(a._apiBadge as HTMLElement, (spendLimit || refusal) ? it.blocked.what : (it.blocked.text || it.blocked.what));
    // The latched "Retrying…" re-arms on any repaint of this card — a new object or a key flip; the expected
    // path is the session resuming, which moves the working set (the key) and hides the whole unit — and on
    // the kernel's reply to THIS click (rearmLatches): `retryRefused` when the backend could not take the
    // send, or an `err` naming this session's apiRetry when the kernel has no such session. Before the
    // per-card update gate it re-armed on the next push of any card. The click is a MANUAL retry (the chat
    // pane sends the same): the kernel fires it past every auto gate, so the button is never a dead no-op on
    // a paused or suppressed thread. Revive below latches the same way and re-arms on `reviveFailed`.
    a._apiRetry.disabled = false; a._apiRetry.textContent = "Retry";
    a._apiRetry.onclick = (ev: Event) => {
      ev.stopPropagation();
      vscodeApi?.postMessage({ type: "apiRetry", id: it.sid, manual: true });
      a._apiRetry.disabled = true; a._apiRetry.textContent = "Retrying…";
    };
  }
  // CAP-SWITCH OFFER (2026-08-30): the tradeoff stated plainly, the pick the user's alone. The
  // latched "Switching…" survives pushes (the T150 idiom — the payload still says login until the
  // reconnect applies the pick) and self-resolves: once authLive flips to key, the kernel stops
  // minting the offer and both elements hide.
  const cap = (showApiErr && it.blocked && it.blocked.capOffer) || null;
  (a._capLine as HTMLElement).style.display = cap ? "" : "none";
  (a._capBtn as HTMLButtonElement).style.display = cap ? "" : "none";
  if (cap) {
    a._capLine.textContent = "This session bills the subscription, whose usage window is full — it can "
      + "bill your API key instead until the window resets at " + clockHM(cap.resetsAt)
      + ". It switches back only if you switch it.";
    if (!(a._capBtn as HTMLButtonElement).disabled) {
      a._capBtn.title = "bills THIS session to the API key — only your pick switches billing, in either "
        + "direction, and the auto-retry at the reset runs whether or not you switch";
      a._capBtn.onclick = (ev: Event) => {
        ev.stopPropagation();
        vscodeApi?.postMessage({ type: "setAuth", id: it.sid, value: "key" });
        a._capBtn.disabled = true; a._capBtn.textContent = "Switching…";   // ack before the round-trip
        a._capBtn.title = "the switch is applying — it lands the way a gear billing pick does, and this offer clears itself";
      };
    }
  } else { (a._capBtn as HTMLButtonElement).disabled = false; a._capBtn.textContent = "Switch to the key"; }
  // JUDGE-AUTH (the user 2026-08-12): romp's own analysis of this session is refused on its credential —
  // the judges bill what the session bills (kernel _judge_auth), that credential is failing, and no card
  // here can move until the user fixes it. The chip names which credential; no Retry (nothing in-session
  // to resume — the latch clears itself on the judges' next successful call once the credential works).
  (a._jauthBadge as HTMLElement).style.display = isJudgeAuth ? "" : "none";
  if (isJudgeAuth && it.blocked) {
    // a STORED login's refusal names the login (T346); the machine's own and the key keep their plain words
    a._jauthBadge.textContent = it.blocked.login ? `⚠ Can't analyze · ${it.blocked.login}`
      : it.blocked.mode === "key" ? "⚠ Can't analyze · API key" : "⚠ Can't analyze · login";
    setTip(a._jauthBadge as HTMLElement, (it.blocked.what || "")
      + (it.blocked.text ? ` — the CLI said: ${it.blocked.text}` : ""));
  }
  // "⚠ retrying since HH:MM" — the OPEN turn is inside an api-retry storm (kernel `retrying`: the live
  // backend state, with the storm's start from the states log). The card stays in Working — the storm is
  // in motion, not a block — but says so instead of reading as plain healthy Working for the storm's whole
  // life (the user 2026-07-09: an ~80-minute storm was invisible on the card). The stopped-on-error badge
  // (isApiErr) outranks it; the kernel never sets both, this is belt-and-suspenders.
  const rt = it.retrying;
  (a._retryBadge as HTMLElement).style.display = (rt && !isApiErr) ? "" : "none";
  if (rt && !isApiErr) {
    a._retryBadge.textContent = rt.since ? `⚠ retrying since ${clockHM(rt.since)}` : "⚠ retrying";
    setTip(a._retryBadge as HTMLElement, "this session's turn keeps hitting API errors and is auto-retrying"
      + (rt.count ? ` (attempt ${rt.count})` : "")
      + " — still in motion, not stalled; it resumes on its own when the API recovers");
  }
  // PARKED HANDOFF → a "Revive" button that brings the offline recipient back so the parked message is
  // delivered; the existing Clear button dismisses it (rides cleared.jsonl). (the user 2026-06-22.)
  const isParked = it.blocked?.state === "parkedHandoff";
  a._revive.style.display = isParked ? "" : "none";
  if (isParked && it.blocked) {
    const toSid = it.blocked.toSid || it.sid;
    a._revive.disabled = false; a._revive.textContent = `Revive ${it.blocked.toName || it.name}`;
    (a._revive as any)._idle = a._revive.textContent;   // the label rearmLatches restores on the kernel's reviveFailed for toSid
    a._revive.onclick = (ev: Event) => {
      ev.stopPropagation();
      vscodeApi?.postMessage({ type: "reviveSession", id: toSid });
      a._revive.disabled = true; a._revive.textContent = "Reviving…";
    };
  }
  // QUARANTINE (per-host trust) → a COMPACT "New message" card under the RECIPIENT session's name —
  // that delivery is what you're approving (the user 2026-07-26; the full-body card made the feed
  // scroll). One dim line names the sender (host:name) with the bus's 90-char gist; clicking it opens
  // the decision modal with the whole body, read-only (peer content, never auto-run). Approve
  // delivers; Deny opens the same modal's feedback step (optional note mailed back to the sender).
  // The decision CARRIES THE CARD'S sid so the federation manager routes it to the kernel that
  // actually holds the file — without it a remote hold's verdict landed on the local kernel and
  // Approve silently did nothing (same shape as the askClear routing fix, 2026-07-02). No optimistic
  // clear — the next kernel push removes the card on success, or re-renders it (buttons re-enabled)
  // if the bus refused (e.g. the recipient is no longer live; the warn toast says why).
  // Human-in-the-loop is the whole point of directed trust.
  // NOTICE CARD (T370, plans/notice-cards.md): the producer beside the name; the body through the markdown sanitizer with
  // remote loads stripped BEFORE adoption; an image attachment inline from the file route with its pin (the picture as
  // posted), only where the page can reach the kernel (canPreview) and only when the kernel allowed it; the actions as
  // buttons that latch on the click and re-arm on the kernel's noticeActionDone (a refusal is toasted; a success with
  // dismissOnAction leaves at once on the answer). A card back from Undo with its action spent carries no actions and
  // `acted`, so no button shows. Rebuilt only when the notice's own fields change (the rev key).
  const nt = it.notice || null;
  const nProd = a._nProd as HTMLElement, nBody = a._nBody as HTMLElement, nAttach = a._nAttach as HTMLElement, nActions = a._nActions as HTMLElement;
  for (const e of [nProd, nBody, nAttach, nActions]) e.style.display = nt ? "" : "none";   // the face fill below refines each block
  if (nt) {
    // a card on a data-defined board shows on the feed under the feed's default column until the board has a view of its own
    // (phase four's switch); its board's title rides the producer label so the reader knows where it belongs
    const onBoard = boardLabelOf(it);
    const nkey = JSON.stringify([nt.key, nt.rev, nt.producer, nt.body, nt.attachment, nt.actions, it.sid, onBoard]);
    if ((a._nKey as string | undefined) !== nkey) {
      a._nKey = nkey;
      fillNoticeFace(it, nt, onBoard, nProd, nBody, nAttach, nActions);
    }
    // re-armed from the payload on EVERY update (the review of PR 1757, medium 2): a click on a down socket is dropped and
        // shape, disabled = false on every update, and the kernel's answer or the next push both let go
  } else {
    a._nKey = undefined;
  }
  (a._clr as HTMLElement).style.display = "";   // (a held message is a notice card since 2026-09-19: its Approve and Deny are stored actions, its Clear as every card's)

  // (Follow-up is modal-only now — no card button; the body click opens the modal. the user 2026-06-16.)
  // the user's handoff spec (2026-06-10): every session this ask was handed to,
  // ANYWHERE in its tree (not just the last hop), shown below the main session
  // — bold, identity color, always with the working dot — but ONLY while that
  // session is live-working and its branch is unfinished. Idle or finished →
  // the line disappears. The main session stays on its own row above.
  const ho = a._delegations as HTMLElement;
  ho.innerHTML = "";
  const hseen = new Set<string>();
  for (const n of it.tree || []) {
    if (n.kind !== "handoff" || n.status === "done") continue;       // finished branch → gone
    if (!n.whoSid || n.who === it.name || hseen.has(n.whoSid)) continue;
    if (!workingSet.has(n.who)) continue;                            // idle → gone
    hseen.add(n.whoSid);
    const line = el("div", "fask-delegation-line");
    const nm = el("a", "fask-delegation"); nm.textContent = n.who;
    if (n.whoColor) nm.style.color = n.whoColor.bg;
    nm.title = n.text || "open this session";
    nm.onclick = (ev) => { ev.stopPropagation(); vscodeApi?.postMessage({ type: "openSession", id: n.whoSid }); };
    line.appendChild(nm);
    setWorkDot(nm, true);                  // presence == actively working, dot always on
    ho.appendChild(line);
  }
  ho.style.display = ho.children.length ? "" : "none";

  // GROUPED mode (the user 2026-07-13): the session header on the backdrop carries the identity + working
  // dot, so the card drops its own name; row2 hides entirely once nothing on it shows. (The Clear re-home
  // between rows is GONE, the user 2026-08-08: the action corner lives in row1 in every mode now — see
  // fask-btns at construction — so there is nothing to move between renders, which is the strongest form
  // of the click-safety rule.)
  const gmode = feedPrefs().grouped;
  ((a._name as HTMLElement).parentElement as HTMLElement).style.display = gmode ? "none" : "";
  const r2 = a._row2 as HTMLElement;
  const r2live = (Array.from(r2.children) as HTMLElement[]).some((c) => c.style.display !== "none" && !(c.classList.contains("fask-badges") && c.childElementCount === 0));   // the badge slot counts only when it holds a badge (display: contents, never hidden itself)
  r2.style.display = gmode && !r2live ? "none" : "";

  // (bg / summary / sub-goals are wired above in applySections — one mutually-exclusive selection.)
}

// One end of a held message's route: "host:" as quiet metadata, the session name in its identity
// colour. The colour is looked up by the name a peer addresses (sessionColors, filled per payload) and
// simply absent when that session has no cards here — an invented colour would be a lie about identity.

// Resolve a focus key (set on hoverAskId/pinnedAskId) to the itemId the timeline
// path-preview understands: a raw ask id maps to itself; a group key "g:<turnId>"
// maps to its FIRST (chronological) live member (v1 — siblings share the turn).
// Returns null if the key is empty or the group has no live members left.
function focusAnchorId(key: string | null): string | null {
  if (!key) return null;
  if (key.startsWith("g:")) {
    const tid = key.slice(2);
    // by turnId only — finds the survivor even after a dissolving group's members lose groupTitle
    const members = asks.filter((a) => a.turnId === tid).sort((a, b) => a.t - b.t);
    return members.length ? members[0].itemId : null;
  }
  return key;
}

// The session that owns a feed itemId — every showAskPath must carry it: federation's routeOutbound
// keys on `sid` (an itemId alone can only go local), so without it a remote card's hover landed on
// the LOCAL kernel, which knows nothing of that goal, and the timeline/chat highlight never lit
// (the user 2026-08-03). Same contract as the askClear sid fix (2026-07-02).
function sidOfItem(itemId: string | null): string | undefined {
  if (!itemId) return undefined;
  return asks.find((a) => a.itemId === itemId)?.sid;
}

// Liveness ANOMALY (the user's simplification, 2026-06-11): ring a card only when
// its computed liveness DISAGREES with the column it's filed in — agreement is
// the normal case and carries no information.
//   ASKS + settled    → green ring: nothing can move this without you; it really
//                       belongs in COMPLETED (or AWAITING) — likely a missed DONE.
//   ASKS + stalled    → dashed orange ring: an unfinished handoff nobody is
//                       working — a dropped delegation that will never finish.
//   COMPLETED + active → gold ring: filed done, but the owning session is mid-turn
//                       — it may still be chewing on this.
// Everything else (active/delegated in ASKS, anything in AWAITING) is expected:
// no ring. delegated/stalled are impossible in COMPLETED by construction (an
// unfinished handoff keeps the fold from completing). Tooltips stay on every card.
// Rings (the user's simplification, 2026-06-12-eve): rings exist ONLY in
// COMPLETED, where every card arrived one of two ways — the judge model stamped
// it done, or the auto-filer noticed nothing was moving it. Agreement is the
// expected state and gets NO ink:
//   no ring          = judged done AND settled — both agree; Clear with confidence
//   green            = auto-filed only — the judge never stamped it; verify, then
//                      Clear (right) or Follow up (wrong); either click is a label
//   blue             = judged done only — not settled yet (often still mid-turn
//                      on it, or waiting); glance before clearing
// A member's rolled-up status → the chat-timeline mark vocabulary (● done /
// ? needs the user / ○ not finished), derived from the host's per-ask column.
function memberStatus(m: AskItem): "done" | "question" | "open" {
  const c = askColumn(m);
  return c === "completed" ? "done" : c === "needsInput" ? "question" : "open";
}
function memberMark(m: AskItem): string {
  const s = memberStatus(m);
  return s === "done" ? "●" : s === "question" ? "⏸" : "○";
}

// Fold N sibling asks (shared turnId) into one AskGroup. Column = WORST member
// (any needs-input → needsInput; else any open → asks; else completed). Identity
// (name/color/sid) is the shared asking session; age/tint follow the newest member.
// The typed-turn GROUPS a card list forms — the render's rule, shared with the jump-unfold (T263e) so the two
// can never disagree: host-flagged asks (groupTitle) gather by turnId, and a turn folds only with ≥2 current
// members — a lone survivor (siblings cleared) renders as a single card.
function turnGroups(list: AskItem[]): Map<string, AskItem[]> {
  const byTurn = new Map<string, AskItem[]>();
  for (const a of list) {
    if (!a.groupTitle || !a.turnId) continue;
    const arr = byTurn.get(a.turnId) || []; arr.push(a); byTurn.set(a.turnId, arr);
  }
  for (const [tid, ms] of Array.from(byTurn)) if (ms.length < 2) byTurn.delete(tid);
  return byTurn;
}
function buildGroup(turnId: string, members: AskItem[]): AskGroup {
  const ms = members.slice().sort((a, b) => a.t - b.t);                       // chronological
  const repr = ms.reduce((x, y) => (y.t > x.t ? y : x), ms[0]);               // most-recent → freshest age/tint
  const column: Column = ms.some((m) => askColumn(m) === "needsInput") ? "needsInput"
    : ms.some((m) => askColumn(m) === "asks") ? "asks" : "completed";
  return {
    turnId, title: ms[0].groupTitle || ms[0].text, members: ms,
    name: ms[0].name, color: ms[0].color, sid: ms[0].sid,
    t: repr.t, trgb: repr.trgb, column, live: ms.some((m) => m.live),
  };
}

// ---- grouped sibling-asks card ----
// One card for a whole typed turn that minted several asks: title = the turn
// summary; one line per member (status circle + member text), the circles filling
// in (○ → ●) as each sub-part completes. Body click → modal (members stacked).
// Clear clears EVERY member. Hover/pin/focus mirror the ask card, keyed by group.
function makeGroupCard(g: AskGroup): HTMLElement {
  const card = el("div", "fitem ask fgroup");
  card.dataset.key = "g:" + g.turnId;
  const fkey = "g:" + g.turnId;

  const main = el("div", "fitem-main");
  const row1 = el("div", "fask-row1");
  const title = el("div", "fcard-title nav"); title.title = "locate this in the text";
  const time = el("span", "ftime");
  row1.append(title, time);   // time trails the title, right-justified (the user 2026-07-07) — matches the ask card
  const row2 = el("div", "fask-row2");
  const idwrap = el("div", "fask-id");
  const name = el("a", "fname"); name.title = "open this session";
  idwrap.append(name);   // no "· N parts" label — the member checklist below already shows the count
  const clr = clearButton("clear ALL sub-asks of this request (inbox-zero)");
  // Clear rides row1's action corner in every mode (the user 2026-08-08) — matches the ask card. Same
  // fask-btns wrapper so the float/wrap CSS is shared; no Continue here (a group is a multi-ask turn —
  // its members carry their own).
  const btns = el("span", "fask-btns");
  btns.append(clr);
  row1.append(btns);
  row2.append(idwrap);
  const memberList = el("div", "fgroup-members");   // no row3: the group card has no time-row content left
  main.append(row1, row2, memberList);
  card.append(main);

  const m0 = () => ((card as any)._g as AskGroup | undefined)?.members?.[0];
  title.onclick = (ev) => { ev.stopPropagation(); const m = m0(); if (m) vscodeApi?.postMessage({ type: "showAskPath", itemId: m.itemId, sid: m.sid }); };
  name.onclick = (ev) => { ev.stopPropagation(); const cur = (card as any)._g as AskGroup; if (cur?.sid) openOrReviveSession(cur.sid, cur.live, cur.name); };
  clr.onclick = (ev) => {
    ev.stopPropagation();
    card.dispatchEvent(new MouseEvent("mouseleave"));   // flush the group's stuck hover highlight (see the ask card's clear)
    const cur = (card as any)._g as AskGroup;
    dressHeaderIfLast(groupEls.get(cur.turnId) ?? card, cur.sid);   // a group is one session's turn — same one-motion rule (2026-08-24); the board's element from a copy (T347)
    for (const c of groupTwins(cur.turnId)) c.classList.add("dismissing");   // both copies of the group (T347), see the ask card's Clear
    pushClearedEntry(cur.members.slice());   // cache the whole batch for an instant optimistic Undo
    for (const m of cur.members) pendingCleared.add(m.itemId);
    // ONE kernel batch for every member (askClearMany): the kernel's Undo restores a batch by its one
    // stamp, so per-member posts left N-1 members archived after an Undo the client had shown whole
    vscodeApi?.postMessage({ type: "askClearMany", itemIds: cur.members.map((m) => m.itemId), sid: cur.sid });
    // only finalize if a render in the 180ms window didn't revive (re-render clears
    // .dismissing) or replace this card — else a stale timeout yanks the wrong one
    setTimeout(() => {
      const twins = groupTwins(cur.turnId).filter((c) => c.classList.contains("dismissing"));
      if (!twins.length) return;
      for (const c of twins) { c.remove(); if (groupEls.get(cur.turnId) === c) groupEls.delete(cur.turnId); if (fsGroupEls.get(cur.turnId) === c) fsGroupEls.delete(cur.turnId); }
      dropDismissed(cur.members.map((m) => m.itemId));
    }, 180);
  };
  // hover (120ms intent) → white border + preview the group's timeline journey
  // (first member). leave → restore the pin (ask OR group) or clear.
  let hoverTimer: number | undefined;
  card.addEventListener("mouseenter", () => {
    freezeEnter(fkey, isFocusCopy(card));              // hover-freeze: pointer truth, no debounce; which twin holds it (T410)
    hoverTimer = window.setTimeout(() => {
      hoverTimer = undefined;
      hoverAskId = fkey; applyFocus();
      const m = m0(); if (m) vscodeApi?.postMessage({ type: "showAskPath", itemId: m.itemId, sid: m.sid, locate: false });
    }, 120);
  });
  card.addEventListener("mouseleave", () => {
    freezeLeave(fkey, isFocusCopy(card));              // hover-freeze: leaving the card flushes queued payloads
    if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = undefined; }
    if (hoverAskId === fkey) {
      hoverAskId = null; applyFocus();
      const pin = focusAnchorId(pinnedAskId);
      if (pin) vscodeApi?.postMessage({ type: "showAskPath", itemId: pin, sid: sidOfItem(pin), locate: false });
      else { const m = m0(); if (m) vscodeApi?.postMessage({ type: "showAskPath", itemId: m.itemId, sid: m.sid, off: true }); }
    }
  });
  // body single-click → modal; double-click → pin/unpin (debounced ~220ms).
  let pending: number | undefined;
  card.addEventListener("click", () => {
    if (pending) { clearTimeout(pending); pending = undefined; return; }
    pending = window.setTimeout(() => {
      pending = undefined;
      fullscreenAskId = fkey;
      const m = m0(); if (m) vscodeApi?.postMessage({ type: "cardOpened", itemId: m.itemId, sid: m.sid });   // the open-metric row (2026-08-25)
      if (m) vscodeApi?.postMessage({ type: "showAskPath", itemId: m.itemId, sid: m.sid, locate: false });
      render();
    }, 220);
  });
  card.addEventListener("dblclick", () => {
    if (pending) { clearTimeout(pending); pending = undefined; }
    pinnedAskId = pinnedAskId === fkey ? null : fkey;
    applyFocus();
    const m = m0();
    // double-click = PIN + jump the TIMELINE (same contract as single cards)
    if (pinnedAskId === fkey && m) vscodeApi?.postMessage({ type: "showAskPath", itemId: m.itemId, sid: m.sid, locate: false, jump: true });
    else if (!pinnedAskId && hoverAskId !== fkey && m) vscodeApi?.postMessage({ type: "showAskPath", itemId: m.itemId, sid: m.sid, off: true });
  });

  const a = card as any;
  a._title = title; a._name = name; a._time = time; a._members = memberList;
  a._row1 = row1; a._row2 = row2; a._clr = clr;   // Clear lives in row1's action corner (2026-08-08)
  return card;
}

function updateGroupCard(card: HTMLElement, g: AskGroup) {
  const a = card as any;
  a._g = g;                                          // current group for the (reused) handlers
  const fkey = "g:" + g.turnId;
  const eff = hoverAskId ?? pinnedAskId;
  card.className = "fitem ask fgroup" + (g.live ? " live" : " dead")
    + (fkey === eff ? " focused" : "") + (fkey === pinnedAskId ? " pinned" : "");
  const [r, gg, b] = g.trgb;
  card.style.background = `rgba(${r}, ${gg}, ${b}, ${TINT_ALPHA})`;
  // outline in the group's session identity colour (the user 2026-07-15) — CSS: 0.5α rest, bolded on hover/pin
  setCardChannels(card, (g.color && hexToRgb(g.color.bg)) || [r, gg, b]);
  setLinkedText(a._title, g.title, prRepoOf(g.sid));   // keyed like the ask card's title
  a._name.replaceChildren(...hostNameNodes(g.name, g.sid));
  if (g.color) a._name.style.color = g.color.bg;
  setWorkDot(a._name, dotFor(g.name));   // working/awaiting dot before the session name
  stampAge(a._time, g.t, "plain", false, nowSec(), relAge, ageColorReadable);
  wireAgeTip(a._time, () => provenanceGroupRows(g.members.map(rootStart), g.t, hostNow, PROV_FMT));
  // member lines — rebuilt only when the member set or any member's status changes
  const memSig = g.members.map((m) => m.itemId + ":" + memberStatus(m)).join("|");
  if (a._memSig !== memSig) {
    a._memSig = memSig;
    const host = a._members as HTMLElement; host.innerHTML = "";
    for (const m of g.members) {
      const line = el("div", "fgroup-member st-" + memberStatus(m));
      const dot = el("span", "fgroup-dot"); dot.textContent = memberMark(m); line.appendChild(dot);
      const txt = el("span", "fgroup-mtext"); txt.textContent = m.text; linkifyPrRefs(txt, prRepoOf(m.sid || g.sid)); line.appendChild(txt);
      host.appendChild(line);
    }
  }
  // GROUPED mode (the user 2026-07-13) — same treatment as the ask card: the backdrop header carries the
  // name + dot, the emptied name row hides. (Clear rides row1's action corner in every mode now, the
  // user 2026-08-08 — no re-home between renders.)
  const gmode = feedPrefs().grouped;
  ((a._name as HTMLElement).parentElement as HTMLElement).style.display = gmode ? "none" : "";
  (a._row2 as HTMLElement).style.display = gmode ? "none" : "";   // the group's row2 is only the name now
}

// Transient hover-highlight signal: hovering a modal line emits its event id(s);
// the host writes timeline-hover.json {id, ids, nonce} (debounced) and db_timeline
// draws a light transient outline on the matching timeline events. null = clear.
// Hovering a PARENT line sends the union of everything underneath it.
function hoverEmit(ids: string | string[] | null) {
  if (Array.isArray(ids)) vscodeApi?.postMessage({ type: "hoverHighlight", ids });
  else vscodeApi?.postMessage({ type: "hoverHighlight", id: ids });
}

// Node STATE → mark, exactly three (the user's model: completed / needing input /
// not finished), in the chat timeline's visual language: ● filled green = done,
// ○ hollow = not finished, ? = needs the user. Status is ROLLED-UP host-side (a
// node is ● when every path below it ends done; a ○ or ? anywhere below
// propagates up), so a completed ask reads as a column of filled dots. The
// disclosure triangle is the only arrow — no glyph shares its shape.
function nodeMark(n: AskTreeNode): string {   // AUTHORITATIVE nodes keep the same glyph; the .auth-* class adds a white ring
  // CLEARED does not touch the mark (the user 2026-07-26: the box means DONE, and only done — a
  // cleared node wears the strike + "cleared" chip, and its mark keeps saying whether it finished).
  if (n.status === "done") return "●";
  if (n.status === "question") return "⏸";   // blocked → the red pause (was an amber ?), consistent w/ the ledger
  return "○";
}
// The cleared row's plain-language story (the user 2026-07-25: a struck-through sub-goal read as
// unexplained machinery, and nothing on screen said the strike means YOU cleared it). One word on the
// row, the sentence on hover, in both the card checklist and the modal. Named "cleared", not
// "dropped" — the same word the Clear button and the undo already use (the user 2026-07-26).



// One human phrase per verdict-log row — the modal's per-item story speaks in outcomes
// ("asked you", "you answered"), never judge internals (the user 2026-07-20).
function logPhrase(r: NodeLogRow): string {
  if (r.kind === "block") return r.src === "user" ? "you flagged a block" : "asked you";
  if (r.kind === "unblock") return r.src === "user" ? "you answered" : "unblocked";
  if (r.kind === "done") return r.src === "user" ? "you checked it off" : "marked done";
  if (r.kind === "reopen") return "reopened";
  // a clear is only "you" when the user did it — the episode boundary clears with src "romp"
  // when a /clear drops the conversation's open cards (the user 2026-07-27)
  if (r.kind === "clear") return r.src === "romp" ? "dropped with the cleared conversation" : "you cleared it";
  if (r.kind === "dismiss") return "dismissed";
  if (r.kind === "settle") return "settled";
  return r.kind || "updated";
}
const logRowT = (r: NodeLogRow): number => r.at || r.evT || 0;
// the provenance popover (hover the card's age stamp) borrows the same vocabulary the card renders with
const PROV_FMT: ProvFmt = { rel: relAge, clock: clockHM, phrase: logPhrase };
// The shared styled tooltip (tip.ts) carries every age stamp's provenance (the user 2026-07-27: the
// native title tooltip was dense and unaligned). Times sit in their own right-aligned column, rows
// wear the modal history-row look (.age-tip-row in feed.css). Rebuilt per hover, so it is click-safe;
// a lazy rows thunk keeps the assembly off the render path entirely. Placed ABOVE the stamp (it sits
// at a card's bottom edge), flipping below when there is no headroom. Cards are keyed + updated IN
// PLACE across pushes, so the hovered stamp usually survives a re-render — unconditionally hiding on
// render made the tip vanish ~a second into every hover (the feed re-renders on every kernel push;
// the user 2026-07-27): pruneTip (called after each render) hides only when the anchor was actually
// torn out of the DOM, where its mouseleave can never fire.
function wireAgeTip(elm: HTMLElement, rows: () => ProvRow[]): void {
  wireTip(elm, (tip) => {
    for (const r of rows()) {
      const row = el("div", "age-tip-row" + (r.kind === "stamp" ? " stamp" : ""));
      const w = el("span", "age-tip-when"); w.textContent = r.when;
      const x = el("span", "age-tip-what"); x.textContent = r.what;
      // each line wears its own recency colour — time AND text, the chat tab-tip treatment (the user
      // 2026-07-27); the un-timed remainder row keeps the panel's dim default
      if (r.t > 0) { const c = ageColorReadable(hostNow - r.t); row.style.color = c; w.style.color = c; }
      row.append(w, x); tip.appendChild(row);
    }
  }, { place: "above" });
}
// the node's owning session for navigation (a handoff node lives in the recipient's transcript) —
// the same resolution wireNodeZones uses for its zones
function navSidOf(it: AskItem, node: AskTreeNode): string {
  return node.whoSid || (node.kind === "handoff" ? node.id.split(":")[0] : it.sid);
}

// Canned one-click status asks (the user 2026-07-20). The reply shapes are exactly the verdicts the
// judge's planner files off a nudge reply — done / in progress / blocked-on-you / obsolete — so the
// session's answer heals the card without any new ingestion machinery.
//
// VOICE (the user 2026-07-24): the session has no idea romp is tracking it, so these read as the person
// it works for asking, in their words. The old opener announced a status check on "this card", naming a
// romp OBJECT the recipient has never heard of, and the four labeled reply slots read as a form. The
// same four answers still come back — a person asking "what shipped, what's next, or what do you need
// from me" gets them without naming the taxonomy. Same rule as the clear-wrap message.
function statusAskOne(title: string): string {
  return "Where does \"" + title + "\" stand? One line: what shipped, what's next, or exactly what you "
       + "need from me if you're stuck. If it isn't worth doing anymore, say so.";
}
function statusSweepText(it: AskItem): { n: number; text: string } {
  const open = (it.tree || []).filter((n) => n.status !== "done" && !n.cleared && n.kind !== "handoff" && n.id !== it.itemId);
  const lines = open.slice(0, 15).map((n) => "- " + (n.text || "(sub-goal)"));
  const more = open.length > 15 ? "\n(+" + (open.length - 15) + " more)" : "";
  return { n: open.length,
           text: "Where does each of these stand? One line each: what shipped, what's next, or exactly "
               + "what you need from me if you're stuck. If one isn't worth doing anymore, say so:\n"
               + lines.join("\n") + more };
}
// True if any DESCENDANT of `node` is itself a question. Node status is ROLLED UP
// (a ? anywhere below makes every ancestor ?), so this distinguishes the ACTUAL
// pending question (the LOWEST ? in a branch) from its rolled-up ancestors — only
// the lowest one renders a reply box (the user 2026-06-10). Cycle-safe (DAG).
function hasQuestionDescendant(node: AskTreeNode, byId: Map<string, AskTreeNode>): boolean {
  const stack = [...(node.children || [])];
  const seen = new Set<string>();
  while (stack.length) {
    const cid = stack.pop()!;
    if (seen.has(cid)) continue; seen.add(cid);
    const c = byId.get(cid); if (!c) continue;
    if (c.status === "question") return true;
    for (const gc of c.children || []) stack.push(gc);
  }
  return false;
}

// Re-render trigger: per-node expansion + node states + which questions have briefs.
function treeSig(it: AskItem): string {
  return it.tree.map((n) =>
    n.id + n.status + (n.cleared ? "x" : "") + (n.whoWorking ? "W" : "")
    // parked can mint/retire off a DIFFERENT top's dispatch (tops are siblings), which changes
    // nothing else in THIS tree — without it in the sig an open group modal kept a stale tag
    + (n.parked && n.parked.n ? "p" + n.parked.n : "")
    + (collapsedNodes.has(it.itemId + ":" + n.id) ? "c" : "")
    + (nodeLogOpen.has(it.itemId + ":" + n.id) ? "L" : "") + ((n.log || []).length || "")).join("|");
}

// Render the DAG as a Linux-style node tree (modal body only). Sig-guarded so a
// host re-push never collapses a node the user just opened or clobbers a
// half-typed answer.
function renderTreeBody(host: HTMLElement, it: AskItem, skipRoot = false) {
  const sig = (skipRoot ? "s|" : "") + treeSig(it);
  if ((host as any)._sig === sig) return;
  (host as any)._sig = sig;
  host.innerHTML = "";
  if (!it.tree.length) { const b = el("div", "fx-body"); b.textContent = "No work yet."; host.appendChild(b); return; }
  const box = el("div", "ftree");
  const byId = new Map(it.tree.map((n) => [n.id, n] as const));
  const briefs = new Map<string, AskQuestion>();   // decision sub-cards retired with openQuestions (2026-07-07)
  const seen = new Set<string>();
  const root = it.tree[0];
  if (skipRoot) {
    // The single-ask modal HEADER already shows the root goal's text (and credits it), so
    // rendering the root's own line here duplicated the title (the user 2026-06-15). Render the
    // root's CHILDREN at depth 0 instead; mark the root seen so a child linking back won't redraw
    // it. build_feed gives every goal node rows:[], so the root has no history rows to preserve.
    seen.add(root.id);
    const kids = (root.children || []).map((c) => byId.get(c)).filter(Boolean) as AskTreeNode[];
    if (!kids.length) { const b = el("div", "fx-body"); b.textContent = "No sub-work yet."; host.appendChild(b); return; }
    for (const k of kids) renderTreeNode(box, it, k, byId, briefs, seen, 0, root.who);
  } else {
    // group modal: each member's tree is stacked with the member's text AS its root line (no
    // per-member header), so the root line stays. pass root.who → the root isn't re-attributed.
    renderTreeNode(box, it, root, byId, briefs, seen, 0, root.who);
  }
  host.appendChild(box);
}

// Debug-mode judge warnings (the user 2026-07-09): every judge failure touching this card, appended
// below the tree. The kernel only emits warnRows while `romp debug on`, so the section
// simply never exists in normal mode. One line per failure (time · judge · kind — evidence); a row
// captured in debug mode expands (native <details>) to the failing call's full input + reply, so a
// rejection is inspectable the moment it happens, without reproducing it.
function applyModalWarnings(host: HTMLElement, it: AskItem): void {
  const rows = it.warnRows || [];
  let sec = host.querySelector(":scope > .fmodal-warns") as HTMLElement | null;
  if (!rows.length) { sec?.remove(); return; }
  const sig = rows.map((r) => r.t + r.judge + r.err).join("|");
  if (sec && (sec as any)._sig === sig) return;   // unchanged → keep the DOM (an open <details> survives the push)
  sec?.remove();
  sec = el("div", "fmodal-warns");
  (sec as any)._sig = sig;
  const head = el("div", "fmodal-warns-head");
  head.textContent = `Warnings — ${rows.length} judge failure${rows.length === 1 ? "" : "s"} (debug mode)`;
  sec.appendChild(head);
  for (const r of rows.slice().reverse()) {       // newest first: the live story on top
    const row = el("div", "fmodal-warn-row");
    const line = el("div", "fmodal-warn-line");
    line.textContent = `${clockHM(r.t)} · ${r.judge} · ${r.err}${r.note ? " — " + r.note : ""}`;
    row.appendChild(line);
    if (r.debug && (r.debug.input || r.debug.reply)) {
      const det = document.createElement("details");
      det.className = "fmodal-warn-det";
      const sum = document.createElement("summary");
      sum.textContent = "input + reply";
      det.appendChild(sum);
      for (const [cap, txt] of [["input", r.debug.input], ["reply", r.debug.reply]] as const) {
        if (!txt) continue;
        const capEl = el("div", "fmodal-warn-cap"); capEl.textContent = cap;
        const pre = document.createElement("pre"); pre.className = "fmodal-warn-pre"; pre.textContent = txt;
        det.append(capEl, pre);
      }
      row.appendChild(det);
    }
    sec.appendChild(row);
  }
  host.appendChild(sec);
}

// Hierarchy is shown by INDENTATION alone (no ASCII tree connectors — the
// disclosure triangles + indent levels already carry the structure; the user's
// de-clutter ruling 2026-06-10).

// Wire a goal node's mark / text / (optional time) into click+hover ZONES — shared by the modal tree AND
// the card's inline sub-goal checklist so they navigate IDENTICALLY (the user 2026-06-17): the TEXT jumps
// to the MESSAGE that minted it (anchor "prompt"); the CHECKBOX (+ the time, when there is one) to where it
// got CHECKED OFF / marked BLOCKED (anchor "work", by id via anchorUuid when resolved). A not-yet-resolved
// node's checkbox + text light together as one unit. `meta` is null on the card (no time cell). `wire`
// false (a dim repeat node) skips the wiring but still returns goWork — the modal's rationale links to it.
function wireNodeZones(it: AskItem, node: AskTreeNode, mark: HTMLElement, txt: HTMLElement, meta: HTMLElement | null, wire: boolean): (ev: Event) => void {
  // itemId = the CLICKED node's own id, not the card's top (the user 2026-07-01): the kernel's _cite_for
  // seeds the composer chip from it, so a sub-goal click cites THAT sub-goal — its own title and its own
  // injected context in the audit preview — instead of a generic top-goal chip. The kernel uses itemId
  // only for the citation; the chat landing is fully anchorUuid-based, so navigation is unchanged.
  const navId = node.id || it.turnId;
  const navSid = node.whoSid || (node.kind === "handoff" ? node.id.split(":")[0] : it.sid);
  // An agentTask-OPEN node is authoritatively unchecked — never "resolved", so the mark hover can't read
  // "jump to where this got checked off" on an item the agent hasn't crossed off (the user 2026-07-01).
  // Defense-in-depth for the kernel's _agent_open_set fix: correct even if a stale build serves status:"done".
  // ...and a rolled-UP question ancestor (qderived) is not itself resolved: the block landed on a
  // descendant, so its own anchor is its mint, and the hover must not claim "filed under Needs you" here.
  const resolved = (node.status === "done" || (node.status === "question" && !node.qderived)) && node.auth !== "open";
  // time-nav fallback for the work jump: where it resolved (mt) for resolved nodes, the newest
  // activity (last) for open ones — matching the newest-seg work anchor (the user 2026-07-20)
  const resolveT = (resolved && node.mt) ? node.mt : (node.last || node.t);
  // anchorUuid can arrive null for a beat (the kernel's cache-only parse goes cold on every transcript
  // write); fall to the stored promptAnchorUuid rather than dispatch a null the chat can only toast on
  // (the user 2026-07-20: three dead clicks on a blocked sub's ⏸ mark in one cold beat).
  const goWork = (ev: Event) => { ev.stopPropagation(); focusEcho(navSid); vscodeApi?.postMessage({ type: "showOnTimeline", itemId: navId, sid: navSid, t: resolveT, anchor: "work", anchorUuid: node.anchorUuid ?? node.promptAnchorUuid ?? null }); };
  // prompt-intent: jump to the minting user message. But a node with no opener (an autonomous note, or an
  // opener compacted off-path) has no promptAnchorUuid, so the jump would honest-fail with "couldn't locate".
  // Fall back to goWork — where the work actually happened — rather than toast (the user 2026-06-30).
  const goMsg = (ev: Event) => {
    if (!node.promptAnchorUuid && node.anchorUuid) { goWork(ev); return; }
    ev.stopPropagation(); focusEcho(navSid); vscodeApi?.postMessage({ type: "showOnTimeline", itemId: navId, sid: navSid, t: node.t, anchor: "prompt", anchorUuid: node.promptAnchorUuid ?? null });
  };
  if (!wire) return goWork;
  // tooltip names the destination by status: a node that needs you was "filed under Needs you", a done node "checked off"
  const workTitle = node.status === "question" && !node.qderived ? "jump to where this was filed under Needs you"
                  : resolved ? "jump to where this got checked off" : "jump to the latest work on this";
  const linkHover = (group: HTMLElement[]) => {
    const on = () => group.forEach((g) => g.classList.add("lz-hl"));
    const off = () => group.forEach((g) => g.classList.remove("lz-hl"));
    group.forEach((g) => { g.addEventListener("mouseenter", on); g.addEventListener("mouseleave", off); });
  };
  txt.classList.add("lz-nav");
  if (node.status === "done") {
    // DONE: TEXT → the minting message (its own zone); MARK + META jump to where it resolved (goWork),
    // as one pair. Hovering the mark or the time lights BOTH (shared target).
    txt.title = "jump to the message that asked for this"; txt.onclick = goMsg;
    mark.classList.add("lz-nav"); mark.title = workTitle; mark.onclick = goWork;
    if (meta) { meta.classList.add("lz-nav"); meta.title = workTitle; meta.onclick = goWork; }
    linkHover([txt]);
    linkHover(meta ? [mark, meta] : [mark]);
  } else {
    // NOT done (open or blocked): every zone answers "where does this STAND?" — the newest event on the
    // node — not where it was born (the user 2026-07-20: clicking a stale sub's title landed on a bare
    // 'retry' mint prompt, useless for deciding what to do with it). goWork targets the node's newest
    // trail segment (kernel _node_anchor_uuids); the minting ask is still one hop away in the chat.
    txt.title = workTitle; txt.onclick = goWork;
    mark.classList.add("lz-nav"); mark.title = workTitle; mark.onclick = goWork;
    if (meta) { meta.classList.add("lz-nav"); meta.title = "jump to the latest work here"; meta.onclick = goWork; }
    linkHover(meta ? [mark, txt, meta] : [mark, txt]);   // one shared target → one shared highlight
  }
  if (node.cleared) {
    // a cleared node's hover must SAY cleared first — "jump to the message that asked for this" alone
    // read as mystery machinery (the user 2026-07-25); the nav still works, the story leads.
    txt.title = CLEARED_TIP + "; click to jump to the message that asked for it";
  }
  return goWork;
}

function renderTreeNode(box: HTMLElement, it: AskItem, node: AskTreeNode, byId: Map<string, AskTreeNode>, briefs: Map<string, AskQuestion>, seen: Set<string>, depth: number, parentWho: string) {
  const repeat = seen.has(node.id);
  // An optimistically-done sub-goal reads as done for this whole render, by rewriting the node rather
  // than patching the DOM after the fact: the mark, the strike-through class, the "Needs you" label and
  // the action buttons all derive from status, so one substitution keeps them agreeing instead of three
  // separate edits that can drift from how a genuinely-done node draws (see pendingDone).
  if (!repeat && pendingDone.has(node.id) && node.status !== "done") node = { ...node, status: "done" };
  const nodeKey = it.itemId + ":" + node.id;
  const expandable = !repeat && (node.children || []).length > 0;
  const line = el("div", "ftree-node st-" + nodeStatusClass(node) + (repeat ? " repeat" : "") + (depth === 0 ? " ftree-root" : "") + (node.derived ? " derived" : "") + (node.auth ? " auth-" + node.auth : ""));
  // the event this line stands for (handoff → its postal msg id; root → the typed
  // turn) — lets a chat rail-dot hover ring this line back (applyExtHover)
  line.dataset.eid = node.kind === "handoff" ? node.id : it.turnId;
  if (depth) line.style.paddingLeft = (depth * TREE_INDENT_EM) + "em";
  // disclosure triangle: ▶ collapsed / ▼ expanded; non-expandable nodes get a blank spacer (no pointer)
  const tri = el("span", "ftree-tri" + (expandable ? " nav" : " empty"));
  tri.textContent = expandable ? (collapsedNodes.has(nodeKey) ? "▶" : "▼") : "";
  // ONLY the triangle toggles expand/collapse (the user 2026-06-10). stopPropagation
  // so the click doesn't bubble to the line, whose click navigates instead.
  if (expandable) tri.onclick = (ev) => { ev.stopPropagation(); if (collapsedNodes.has(nodeKey)) collapsedNodes.delete(nodeKey); else collapsedNodes.add(nodeKey); render(); };
  line.appendChild(tri);
  const mark = el("span", "ftree-mark"); mark.textContent = nodeMark(node); line.appendChild(mark);
  // blocked rolls UP (kernel flatten, the user 2026-07-11): a rolled-up ancestor's ⏸ says the block is below
  if (node.status === "question") mark.title = node.qderived ? "a sub-goal inside it needs you: the ⏸ below is the ask" : "needs you";
  const txt = el("span", "ftree-text"); txt.textContent = node.text || "(node)"; linkifyPrRefs(txt, prRepoOf(it.sid)); line.appendChild(txt);
  if (node.cleared) line.appendChild(clearedTag());   // same one-word story as the card checklist
  if (node.parked && node.parked.n && !node.cleared) line.appendChild(parkedTag(node.parked.n));   // and the parked hint
  // (The node's why/blocked/done rationale hover tooltip was removed 2026-06-27 — just the goal text now.)
  if (node.who && node.who !== parentWho) {
    const who = el("a", "ftree-who"); who.title = node.whoWorking ? "open this session (working now)" : "open this session";
    who.appendChild(document.createTextNode("→ "));
    // working dot LEFT of the name (after the arrow): the agent this is handed to is
    // live-working, so the user knows the item is likely to get finished
    if (node.whoWorking) who.appendChild(el("span", "ftree-who-dot"));
    who.appendChild(document.createTextNode(node.who));
    if (node.whoColor) who.style.color = node.whoColor.bg;
    who.onclick = (ev) => { ev.stopPropagation(); if (node.whoSid) vscodeApi?.postMessage({ type: "openSession", id: node.whoSid }); };
    line.appendChild(who);
  }
  const meta = el("span", "ftree-meta");
  // a node needing the user reads as "Needs you" (the category's colour): the marker + this label are the block
  // signal, distinct from a recency-tinted age (the user 2026-06-17). Other states show "(Xm ago)".
  meta.textContent = node.status === "question" ? (node.qderived ? "Needs you inside" : "Needs you") : "(" + relAge(hostNow - node.last) + ")";   // the category's word (plans/needs-you.md)
  if (node.status !== "question" && node.trgb) meta.style.color = "rgb(" + node.trgb.join(",") + ")";   // Hawaii recency tint
  line.appendChild(meta);
  // Whole-line click NAVIGATES into the chat. PREFERRED: node.anchorUuid (kernel 996ebd7) deep-links to
  // the EXACT turn by id — where the node resolved (done/blocked) or was minted (open) — killing the
  // nearest-time mismatch. FALLBACK (anchorUuid null/off-path): the time path below. anchor:"work"
  // lands on the ASSISTANT turn, never the user prompt (the user 2026-06-16, who wanted blocked and
  // completed things to jump to places in the chat that are NOT the user's message). A blocked/done
  // node sends node.mt — the segment where the planner applied the block/done op, i.e. where the work
  // actually got blocked or finished — so the click lands on THAT assistant action, not where the node
  // was first minted. An open node sends node.t (its own start). navSid is the node's session
  // (a handoff node lives in the recipient's transcript).
  // Click/hover zones for this node, via the SHARED wireNodeZones (so the card's sub-goal checklist clicks
  // identically). Returns goWork; the inline rationale below links to the same place. (the user 2026-06-17.)
  const goWork = wireNodeZones(it, node, mark, txt, meta, !repeat);
  // NON-DONE-node surgical actions in the MODAL tree (the user 2026-06-17, widened from blocked-only
  // 2026-07-20: stale OPEN subs were unactionable — 'I don't know what to do with them'): act on a
  // SPECIFIC sub-goal, not just the whole card. Wired AROUND the shared wireNodeZones (which the
  // card checklist also uses) so only the modal flips — the card checklist + ledger marks stay pure-nav.
  // Skips repeats (dim back-links) and handoff nodes (those resolve in another session's store). A rolled-UP
  // question ancestor (qderived — the block lives in a descendant) gets NO action buttons: "Done" there would
  // resolve the whole subtree and "Follow up" would file the answer off-target; the actual ask below has them.
  if (!repeat && node.status !== "done" && !node.cleared && !node.qderived && node.kind !== "handoff") {
    // The MARK stays pure NAV here (it keeps wireNodeZones → jump to the latest work), EXACTLY like the
    // main card — clicking a node in the modal no longer silently crosses it off, which was confusing (the
    // user 2026-06-29). Instead explicit BUTTONS sit on the line: "Done" crosses it off, "Drop" clears it,
    // "Status?" asks the session where it stands, "Follow up" answers just this sub-goal.
    const acts = el("span", "ftree-node-acts");
    // Done/Drop/Status? are SUB-TASK-ONLY (the user 2026-06-30): not on the TOP-LEVEL goal (the tree root) —
    // the card's own Clear resolves the whole goal, and the card-level "Check status" sweeps every open sub.
    // The root is it.tree[0]; in the skip-root single-ask modal it's never drawn here anyway, so every drawn
    // node IS a sub-task and keeps them. "Follow up" stays on every non-done node.
    const isRoot = node.id === it.tree?.[0]?.id;
    if (!isRoot) {
      // "Done": post nodeOverride op:resolve — the kernel marks the node resolved + clears the block + re-rolls
      // inline (no judge pass; bugs owns the handler 3dded52). Immediate-apply (no draft to lose on a re-render).
      const done = el("button", "ftree-act-btn ftree-act-done"); done.textContent = "Done";
      done.title = node.status === "question"
        ? "mark this sub-goal done — it stops blocking and the thread's other work continues"
        : "mark this sub-goal done — you're asserting it's finished";
      // Crosses off IMMEDIATELY, then reconciles (the user 2026-07-23, for whom this felt very slow): the
      // click used to post and paint nothing, so the tick waited on a store write, a rollup and a full
      // feed rebuild. Drop and Check status beside it already acknowledged instantly; this was the odd
      // one out. The kernel's ack is what clears or reverts it — see nodeOverrideResult.
      done.onclick = (ev) => {
        ev.stopPropagation();
        pendingDone.add(node.id);
        vscodeApi?.postMessage({ type: "nodeOverride", sid: it.sid, nodeId: node.id, op: "resolve" });
        renderModal();   // repaint through the same path a real done takes, so it looks identical
      };
      // "Drop": the item-level clear (the user 2026-07-20, who wanted it as an item-level clear) —
      // clears it as no-longer-needed via the same user-authority seam as a card Clear. Acknowledges
      // instantly (fades + strikes the line; the mark stays honest); the kernel push confirms.
      const drop = el("button", "ftree-act-btn ftree-act-drop"); drop.textContent = "Drop";
      drop.title = "clear this sub-goal off the board — no longer needed, without claiming it was done";
      drop.onclick = (ev) => {
        ev.stopPropagation();
        vscodeApi?.postMessage({ type: "nodeOverride", sid: it.sid, nodeId: node.id, op: "clear" });
        // the mark is left ALONE — the box means done, and dropping doesn't finish anything
        line.classList.remove("st-open", "st-question"); acts.remove();
        line.classList.add("st-cleared");
        line.appendChild(clearedTag());   // instant ack wears the same tag the re-render will draw
      };
      // "Check status": ONE-CLICK targeted ask — the session states where this item stands and the judge
      // files the reply on this node (the same askFollowUp + romp-goal-id path a typed per-sub follow-up
      // rides). Named "Check status" to match the modal footer's sweep, not the old "Status?" (the user
      // 2026-07-21: one verb for the same act, whether it sweeps the card or checks a single sub-goal).
      const stat = el("button", "ftree-act-btn ftree-act-status") as HTMLButtonElement; stat.textContent = "Check status";
      stat.title = "ask the session where this item stands right now — the reply files back onto this sub-goal";
      stat.onclick = (ev) => {
        ev.stopPropagation();
        vscodeApi?.postMessage({ type: "askFollowUp", itemId: node.id, title: node.text || "(sub-goal)",
                                 text: statusAskOne(node.text || "this sub-goal"), sid: it.sid });
        stat.disabled = true; stat.textContent = "Asked";   // instant ack; the ↻ Followed up chip takes over on the next push
        optimisticFollowMove(it.itemId);
      };
      acts.append(done, drop, stat);
    }
    // "Follow up": re-target the footer composer at THIS sub so the answer files under it and unblocks just
    // this branch (the judge reopens + force-files under any node id — no kernel change).
    const fu = el("button", "ftree-act-btn ftree-act-fup"); fu.textContent = "Follow up";
    fu.title = node.status === "question" ? "follow up on this sub-goal that needs you" : "follow up on this specific sub-goal";
    fu.onclick = (ev) => { ev.stopPropagation(); openSubFollowUp?.(node.id, node.text || "(sub-goal)"); };
    acts.append(fu);
    line.appendChild(acts);
  }
  // a per-node "↻ Followed up" chip while THIS sub is optimistically reopened by a follow-up, until the judge
  // re-files it (node.followupPending, emitted per-node by build_feed's flatten — judges 047264f).
  if (!repeat && node.followupPending) {
    const chip = el("span", "ftree-followedup"); chip.textContent = "↻ Followed up";
    chip.title = "you followed up on this sub-goal — reopened to working; the planner will re-file it on the next pass";
    line.appendChild(chip);
  }
  // Hovering a node lights ITS OWN work-bars on the timeline — the union of this node's segment trail
  // and everything under it — via the SAME showAskPath the card uses, just scoped to this node (the
  // host resolves the node's subtree segments). Leaving restores the card's full path. (Before: it
  // emitted the goal-node id through hoverHighlight, which the timeline matches against SEGMENT ids,
  // so a sub-node hover never lit anything — the user 2026-06-16.)
  if (!repeat) {
    line.addEventListener("mouseenter", () => vscodeApi?.postMessage({ type: "showAskPath", itemId: node.id, sid: it.sid, locate: false }));
    line.addEventListener("mouseleave", () => vscodeApi?.postMessage({ type: "showAskPath", itemId: it.itemId, sid: it.sid, locate: false }));
  }
  box.appendChild(line);
  if (repeat) return;                                   // dim repeat: line only, no descent
  seen.add(node.id);
  // The DISTILLER's per-node line (restored 2026-06-29, the user: show everything the distiller produces, just
  // NOT the planner's why-created/why-blocked/why-done rationales). A done node shows its takeaway
  // (node.summary), a blocked node its decision brief (node.blockSummary) — ONLY when produced (non-empty),
  // never a generating-state placeholder. pre-wrap (CSS) keeps a copy-pasteable artifact intact across lines.
  const nodeDistill = distillText(node.status === "done", node.status === "question",
                                  node.summary, node.blockSummary);
  // The card's BACKGROUND section always shows in the MODAL (the user 2026-07-02): the root node renders
  // both sections in full, labeled "background" / "summary" — no collapsing here, the modal is the
  // full-detail view. Only the root carries it (it.background is a top-goal field).
  const modalBg = node.id === it.itemId && nodeDistill && it.background ? it.background : null;
  if (modalBg) {
    const bl = el("div", "ftree-seclabel"); bl.textContent = "background";
    bl.style.paddingLeft = ((depth + 1) * TREE_INDENT_EM) + "em";
    const bb = el("div", "ftree-summary"); bb.textContent = modalBg; linkifyPrRefs(bb, prRepoOf(it.sid));
    bb.style.paddingLeft = ((depth + 1) * TREE_INDENT_EM) + "em";
    const sl = el("div", "ftree-seclabel"); sl.textContent = "summary";
    sl.style.paddingLeft = ((depth + 1) * TREE_INDENT_EM) + "em";
    box.append(bl, bb, sl);
  }
  if (nodeDistill) {
    const sum = el("div", "ftree-summary");
    sum.style.paddingLeft = ((depth + 1) * TREE_INDENT_EM) + "em";
    sum.textContent = nodeDistill;
    linkifyPrRefs(sum, prRepoOf(it.sid));
    // parity with the card's distiller line (the user 2026-06-29): the modal summary is also a LINK — clicking
    // it follows to where the node resolved (its work anchor, the SAME target as the node's mark/time zones).
    // Wired on EITHER anchor: goWork itself falls to the prompt anchor when the work one is cold-null, so
    // gating on anchorUuid alone dead-ended the line during a cold beat (the user 2026-07-20).
    // The brief's OWN landing first (T388): the kernel resolves the text atom that carries the line (a validated
    // citation, else the opening sentence located in the newest segment's turn) and its span, so the click never
    // lands on the node's work anchor, which for a long turn can be a tool call inside a collapsed group.
    if (!repeat && node.summaryAnchorUuid) {
      sum.classList.add("ftree-summary-link");
      sum.title = "jump to where this was written";
      // the ROW's own session, never the card's (navSidOf, the same resolver goWork uses): a serving-folded worker
      // row inside the sender's card resolved its landing in the worker's parse, and the worker's atom sent to
      // the sender's chat could only honest-fail (the verifier's first round)
      const su = node.summaryAnchorUuid, sq = node.summaryAnchorQuote || undefined, ss = navSidOf(it, node);
      sum.onclick = (ev: Event) => { ev.stopPropagation(); focusEcho(ss); vscodeApi?.postMessage({ type: "showOnTimeline", itemId: node.id || it.turnId, sid: ss, t: node.mt ?? node.t, anchor: "work", anchorUuid: su, quote: sq }); };
    } else if (!repeat && (node.anchorUuid || node.promptAnchorUuid)) {
      sum.classList.add("ftree-summary-link");
      sum.title = "jump to where this was written";
      sum.onclick = goWork;
    }
    box.appendChild(sum);
  }
  // The same note in the modal tree (node.relayNote): its own line under the node's brief, never part of it.
  if (node.relayNote) {
    const rn = el("div", "ftree-relaynote");
    rn.style.paddingLeft = ((depth + 1) * TREE_INDENT_EM) + "em";
    rn.textContent = node.relayNote;
    box.appendChild(rn);
  }
  // The per-item STORY (the user 2026-07-20: 'I don't know if they're still active'): a non-done node
  // with verdict history shows a one-line gist — its newest event in outcome words + how long ago —
  // expandable (keyed, survives re-renders) to the full block/unblock log, each row jumping to its own
  // chat turn (exact anchor when warm, ev-time nearest otherwise). Progressive disclosure: gist →
  // history → transcript, each one click.
  if (!repeat && node.status !== "done" && !node.cleared && node.log && node.log.length) {
    const rows = node.log;
    const last = rows[rows.length - 1];
    const opened = nodeLogOpen.has(nodeKey);
    const gist = el("div", "ftree-log-gist" + (opened ? " open" : ""));
    gist.style.paddingLeft = ((depth + 1) * TREE_INDENT_EM) + "em";
    gist.textContent = (opened ? "▾ " : "▸ ") + logPhrase(last) + " · " + relAge(hostNow - logRowT(last));
    gist.title = opened ? "collapse this item's history" : "expand this item's history";
    gist.onclick = (ev) => { ev.stopPropagation(); if (opened) nodeLogOpen.delete(nodeKey); else nodeLogOpen.add(nodeKey); render(); };
    box.appendChild(gist);
    if (opened) {
      for (const r of rows) {
        const rt = logRowT(r);
        const row = el("div", "ftree-log-row");
        row.style.paddingLeft = ((depth + 1) * TREE_INDENT_EM) + "em";
        const when = el("span", "ftree-log-when"); when.textContent = relAge(hostNow - rt);
        const what = el("span", "ftree-log-what"); what.textContent = logPhrase(r) + (r.why ? " — " + r.why : "");
        row.append(when, what);
        row.title = "jump to this moment in the chat";
        row.onclick = (ev) => {
          ev.stopPropagation();
          focusEcho(navSidOf(it, node));
          vscodeApi?.postMessage({ type: "showOnTimeline", itemId: node.id, sid: navSidOf(it, node),
                                   t: r.evT || rt, anchor: "work", anchorUuid: r.anchorUuid ?? null });
        };
        box.appendChild(row);
      }
    }
  }
  // (the in-feed decision sub-card was removed — a blocked node shows its red BLOCKED marker and
  // links to the session; answering happens in the session, not in the feed. the user 2026-06-15.)
  // node history (rows) — progressive, only when this node was clicked open.
  // the user's ruling: every report that arrived IS a completed sub-thing — it
  // gets a filled green dot. (State still lives on the node line: the dot on a
  // report never holds anything open.) The one exception is the report that IS
  // the currently-open question — that keeps its ?.
  if (!collapsedNodes.has(nodeKey)) {
    // ONE chronological stream per level (the user's ruling): reports and
    // delegations interleave by the time their line DISPLAYS — a report's own
    // time, a delegation's rolled-up last-activity. Each visible sibling list
    // reads oldest → newest; deeper levels re-sort within their own parent
    // (cross-branch disorder when expanded is accepted).
    const entries: { t: number; render: () => void }[] = [];
    // collapsed node hides its WHOLE subtree — descendants render only when this
    // node is expanded. This is what makes the collapse "deep".
    const kids = (node.children || []).map((c) => byId.get(c)).filter(Boolean) as AskTreeNode[];
    for (const k of kids) {
      entries.push({ t: k.last, render: () => renderTreeNode(box, it, k, byId, briefs, seen, depth + 1, node.who) });
    }
    entries.sort((a, b) => a.t - b.t);
    for (const e of entries) e.render();
  }
}

// auto-grow the follow-up composer like the main message box (capped a few lines)
function growFollowUp(ta: HTMLTextAreaElement) {
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
}

// ⛶ full-screen tree modal over the whole feed (deep hierarchies, full width).
// Header credits the ask (title · agent · age · Clear); body = the state tree with
// progressive per-node history. Driven by fullscreenAskId; re-rendered each push.
function renderModal() {
  inModalRender = true;   // the modal's paint is render time: a post it makes is no jump of the reader's (T416 round two)
  try { renderModalNow(); } finally { inModalRender = false; }
}
function renderModalNow() {
  let m = document.getElementById("feed-modal");
  // The open target is EITHER a single ask (itemId) OR a group ("g:<turnId>" key).
  const isGroup = !!fullscreenAskId && fullscreenAskId.startsWith("g:");
  const tid = isGroup ? fullscreenAskId!.slice(2) : "";
  // Collect by turnId only (NOT groupTitle) so a dissolving group is detected even
  // if its survivors lost the flag; a group down to ONE member converts to that
  // survivor's normal single-ask modal rather than closing.
  const gMembers = isGroup ? asks.filter((a) => a.turnId === tid).sort((a, b) => a.t - b.t) : [];
  if (isGroup && gMembers.length === 1) fullscreenAskId = gMembers[0].itemId;
  const grp = isGroup && gMembers.length >= 2 ? buildGroup(tid, gMembers) : null;
  // …OR a synthetic blocked-session card ("b:<sid>") — its modal is the ERROR
  // explanation (what's suspicious + what to note for a correction), nothing else.
  const it = (fullscreenAskId && !fullscreenAskId.startsWith("g:") && !fullscreenAskId.startsWith("i:"))
    ? asks.find((a) => a.itemId === fullscreenAskId) : null;
  if (!it && !grp) { if (m) { m.remove(); hoverEmit(null); } modalRenderedId = null; return; }   // closed / dissolved → clear hover highlight
  if (!m) {
    m = el("div", ""); m.id = "feed-modal";
    const inner = el("div", "feed-modal-inner");
    const head = el("div", "feed-modal-head");
    const ttl = el("div", "feed-modal-title"); ttl.id = "feed-modal-title";
    const agent = el("a", "fname feed-modal-agent"); agent.id = "feed-modal-agent";
    const close = el("button", "feed-modal-close"); close.textContent = "✕"; close.title = "close (Esc)";
    close.onclick = () => { fullscreenAskId = null; renderModal(); };
    head.append(ttl, agent, close);   // TOP bar: session name (+ a title for group/standalone) at the left, ✕ at the right
    // BOTTOM bar (the user 2026-06-16): the checklist sits at the top; age + Follow up + Clear live below it
    // in one row, and the Follow-up composer drops in under that row when the button is toggled.
    const age = el("span", "ftime feed-modal-age"); age.id = "feed-modal-age";
    const fup = el("button", "fdismiss ffollow feed-modal-follow"); fup.id = "feed-modal-follow"; fup.textContent = "Follow up"; fup.title = "send a follow-up to this session — the card returns to ASKS"; fup.style.display = "none";
    // (Nudge moved OUT of the modal footer onto the working CARD itself — the user 2026-06-18.)
    // (The "Move to Working" button was removed — the user 2026-07-25; reply or Clear cover its cases.)
    // "Check status" (the user 2026-07-20): the card-level sweep, in the modal too — one message asking
    // the session where every open/blocked item stands. The single-ask branch wires + shows it.
    const cs = el("button", "fdismiss feed-modal-status"); cs.id = "feed-modal-status"; cs.textContent = "Check status";
    cs.title = "ask this session where every open item on this card stands — replies file back onto the card";
    cs.style.display = "none";
    const clr = el("button", "fdismiss feed-modal-clear"); clr.id = "feed-modal-clear"; clr.textContent = "Clear";
    // "Continue" (the user 2026-08-08): the card's one-click "nothing needed from me, keep going", in the
    // modal too. Left of Clear, matching the card's action corner. The single-ask branch wires + shows it.
    const cont = el("button", "fdismiss feed-modal-continue"); cont.id = "feed-modal-continue"; cont.textContent = "Continue";
    cont.title = "nothing needed from you — tells this session to keep going and decide open questions itself";
    cont.style.display = "none";
    const footRow = el("div", "feed-modal-foot-row"); footRow.append(age, fup, cs, cont, clr);
    const fubox = el("div", "ffollow-box feed-modal-follow-box"); fubox.id = "feed-modal-follow-box"; fubox.style.display = "none";
    const fuin = el("textarea", "fq-input feed-modal-follow-input") as HTMLTextAreaElement; fuin.id = "feed-modal-follow-input"; fuin.placeholder = "follow up on this…"; fuin.rows = 1;
    fuin.addEventListener("input", () => growFollowUp(fuin));
    const fusend = el("button", "fq-send feed-modal-follow-send"); fusend.id = "feed-modal-follow-send"; fusend.textContent = "Send";
    fubox.append(fuin, fusend);
    // when a blocked sub is the follow-up target, this label says so (click → revert to the whole card)
    const futgt = el("div", "feed-modal-follow-target"); futgt.id = "feed-modal-follow-target"; futgt.style.display = "none";
    const nudges = el("div", "feed-modal-nudges"); nudges.id = "feed-modal-nudges"; nudges.style.display = "none";
    const foot = el("div", "feed-modal-foot"); foot.id = "feed-modal-foot"; foot.append(nudges, footRow, futgt, fubox);
    const body = el("div", "feed-modal-body"); body.id = "feed-modal-body";
    inner.append(head, body, foot);
    m.appendChild(inner);
    m.onclick = (ev) => { if (ev.target === m) { fullscreenAskId = null; renderModal(); } };  // backdrop closes
    document.body.appendChild(m);
  }
  const body = document.getElementById("feed-modal-body") as HTMLElement;
  // reset the body cache when the open target changes (ask↔group, or a different one)
  // Shared follow-up composer wiring (single-ask AND group modals): the button
  // toggles the box, Enter sends (Shift+Enter = newline), Escape closes. Only
  // the keys we act on are swallowed — everything else (Cmd/Ctrl+V paste, copy,
  // select-all) propagates so VS Code's webview clipboard handler can run.
  function wireFollowUp(fupEl: HTMLButtonElement, fuboxEl: HTMLElement, fuinEl: HTMLTextAreaElement, fusendEl: HTMLButtonElement, send: (txt: string) => void) {
    fupEl.style.display = "";
    // Send/⏎ posts the follow-up and CLOSES the modal — once it's gone through there's nothing left to do
    // here, so drop back to the feed (the user 2026-06-19). (The kernel optimistically reopens the card with
    // a "Followed up" chip, which you then see in the list.)
    const submit = () => { const txt = fuinEl.value.trim(); if (!txt) return; send(txt); fuinEl.value = ""; fuinEl.style.height = ""; fuboxEl.style.display = "none"; fullscreenAskId = null; renderModal(); };
    fupEl.onclick = () => { const show = fuboxEl.style.display === "none"; fuboxEl.style.display = show ? "" : "none"; if (show) fuinEl.focus(); };
    fusendEl.onclick = submit;
    fuinEl.onkeydown = (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); ev.stopPropagation(); submit(); }
      else if (ev.key === "Escape") { ev.stopPropagation(); fuboxEl.style.display = "none"; }
    };
  }

  if (modalRenderedId !== fullscreenAskId) {
    body.innerHTML = ""; (body as any)._sig = "";
    // a fresh target gets a fresh, collapsed follow-up composer
    const fb0 = document.getElementById("feed-modal-follow-box") as HTMLElement | null;
    if (fb0) { fb0.style.display = "none"; const i0 = document.getElementById("feed-modal-follow-input") as HTMLTextAreaElement | null; if (i0) { i0.value = ""; i0.style.height = ""; } }
    followupSub = null;   // a fresh target → the composer follows up on the whole card until a sub is picked
    // fresh open shows ONE level (the user's ruling): the root's reports + its
    // direct children as lines, everything beneath those children folded until
    // clicked. Seeding overrides any unfolds left from a previous open.
    for (const mem of (it ? [it] : grp ? grp.members : [])) {
      const rootId = mem.tree.length ? mem.tree[0].id : null;
      for (const n of mem.tree) {
        const key = mem.itemId + ":" + n.id;
        if (n.id === rootId) collapsedNodes.delete(key);
        // fold any non-root node that HAS a subtree to hide (one-level default view). `n.rows` was removed
        // from AskTreeNode in the payload audit — reading `.length` off the now-undefined field threw and
        // ABORTED the whole modal render → a blank modal (the user 2026-07-08; the typecheck flagged it but
        // esbuild doesn't type-check, so it shipped). Children alone decide foldability now.
        else if ((n.children || []).length) collapsedNodes.add(key);
      }
      // EXCEPTION to one-level (the user): expand the branch DOWN to each pending
      // question so its reply box is reachable without manual unfolding — only that
      // branch's ancestors, never the whole tree.
      const byId = new Map(mem.tree.map((n) => [n.id, n] as const));
      const root = mem.tree[0];
      if (root) {
        const walk = (n: AskTreeNode, ancestors: string[]) => {
          if (n.status === "question" && !hasQuestionDescendant(n, byId))
            for (const aid of ancestors) collapsedNodes.delete(mem.itemId + ":" + aid);   // open the path to the box
          const next = [...ancestors, n.id];
          for (const cid of n.children || []) { if (next.includes(cid)) continue; const c = byId.get(cid); if (c) walk(c, next); }
        };
        walk(root, []);
      }
    }
  }
  modalRenderedId = fullscreenAskId;
  // nudge HISTORY (the user 2026-07-02): the stalled chip's evidence, one click away — when romp followed
  // up on this goal. Hidden unless the single-ask target has recorded fires.
  const nudEl = document.getElementById("feed-modal-nudges") as HTMLElement | null;
  if (nudEl) {
    const nu = it?.nudged;
    if (nu && nu.times.length) {
      nudEl.textContent = `romp followed up ${nu.count}× — ${nu.times.map(clockHM).join(", ")}`;
      nudEl.title = "automatic follow-ups romp sent on this goal (they render in the chat as gray romp bubbles with the swirl)";
      nudEl.style.display = "";
    } else {
      nudEl.style.display = "none";
    }
  }
  const ttlEl = document.getElementById("feed-modal-title") as HTMLElement;
  const agent = document.getElementById("feed-modal-agent") as HTMLElement;
  const ageEl = document.getElementById("feed-modal-age") as HTMLElement;
  const clrEl = document.getElementById("feed-modal-clear") as HTMLElement;
  const csEl = document.getElementById("feed-modal-status") as HTMLButtonElement | null;
  const contEl = document.getElementById("feed-modal-continue") as HTMLButtonElement | null;
  const fupEl = document.getElementById("feed-modal-follow") as HTMLButtonElement;
  const fuboxEl = document.getElementById("feed-modal-follow-box") as HTMLElement;
  const fuinEl = document.getElementById("feed-modal-follow-input") as HTMLTextAreaElement;
  const fusendEl = document.getElementById("feed-modal-follow-send") as HTMLButtonElement;
  // Per-sub follow-up re-targeting (the user 2026-06-17): a blocked sub's "↳ follow up" points the footer
  // composer at that sub; the label says which (click it to revert to the whole card); sending reverts too.
  const futgtEl = document.getElementById("feed-modal-follow-target") as HTMLElement;
  const setFollowTarget = (sub: { itemId: string; title: string } | null) => {
    followupSub = sub;
    if (!futgtEl) return;
    if (sub) { futgtEl.textContent = "↳ following up on: " + sub.title; futgtEl.style.display = ""; }
    else { futgtEl.style.display = "none"; }
  };
  if (futgtEl) futgtEl.onclick = () => setFollowTarget(null);   // revert to the whole card
  openSubFollowUp = (itemId, title) => { setFollowTarget({ itemId, title }); fuboxEl.style.display = ""; fuinEl.focus(); };
  // POST a follow-up to the picked sub if one is set, else the card/group fallback; then revert to the card.
  const postFollowUp = (txt: string, fbId: string, fbSid?: string, fbTitle?: string) => {
    const tgt = followupSub;   // a sub-goal belongs to the same session → same sid routes it
    vscodeApi?.postMessage({ type: "askFollowUp", itemId: tgt ? tgt.itemId : fbId, title: tgt ? tgt.title : fbTitle, text: txt, sid: fbSid });
    // Optimistically move THIS card (fbId is the visible card/group, even when a sub-goal is the message target)
    // to Working now, then re-render the feed so it slides over immediately — the kernel reconciles on its push.
    optimisticFollowMove(fbId);
    render();
    setFollowTarget(null);
  };
  setFollowTarget(followupSub);   // sync the label to the current target on every (re)render
  // modal title = a locate link, same as the collapsed card's title (the user
  // 2026-06-10: every title should jump to the thing in the text/timeline)
  ttlEl.classList.add("nav");
  ttlEl.title = "locate this in the text";
  ttlEl.style.display = "";    // default shown (group / standalone); the single-ask branch hides it — its
                               // top-level goal IS the first line of the tree, not a separate header title
  clrEl.style.display = "";   // re-shown here because the blocked branch below hides it
  // default-hidden + reset every render; only the single-ask branch shows it (group/standalone never do)
  if (csEl) { csEl.style.display = "none"; }   // disabled/label NOT reset here — "Asked" survives the per-push re-render
  if (contEl) { contEl.style.display = "none"; }   // same contract as Check status: "Sent" survives re-renders
  let titleHoverId: string | null = null;   // the originating typed turn → chat/timeline hover highlight
  if (grp) {
    ttlEl.textContent = grp.title;
    titleHoverId = grp.turnId;
    const gm0 = grp.members[0];   // prompt-intent title → the first member's MINTING message (resolves by id, kernel 92e23ff)
    const gm0Prompt = gm0.tree?.find((n) => n.id === gm0.itemId)?.promptAnchorUuid ?? null;
    ttlEl.onclick = () => { focusEcho(grp.sid); vscodeApi?.postMessage({ type: "showOnTimeline", itemId: gm0.itemId, sid: grp.sid, t: grp.t, anchor: "prompt", anchorUuid: gm0Prompt }); };   // braced (T416 round two): without them the post ran on every paint of the modal, a jump nobody made
    agent.replaceChildren(...hostNameNodes(grp.name, grp.sid)); if (grp.color) agent.style.color = grp.color.bg; setWorkDot(agent, dotFor(grp.name)); agent.classList.toggle("dead", !grp.live);
    agent.onclick = () => vscodeApi?.postMessage({ type: "openSession", id: grp.sid });
    ageEl.textContent = relAge(hostNow - grp.t);
    wireAgeTip(ageEl, () => provenanceGroupRows(grp.members.map(rootStart), grp.t, hostNow, PROV_FMT));
    ageEl.style.color = "rgb(" + grp.trgb.join(",") + ")";   // tint the age by recency (the time colour scheme)
    clrEl.onclick = () => { vscodeApi?.postMessage({ type: "askClearMany", itemIds: grp.members.map((mem) => mem.itemId), sid: grp.sid }); fullscreenAskId = null; renderModal(); };   // one batch, one Undo
    // follow-up on a group goes to the session that took the typed prompt — one
    // message prefixed with the GROUP title, filed under the first member's ask
    wireFollowUp(fupEl, fuboxEl, fuinEl, fusendEl, (txt) => postFollowUp(txt, grp.members[0].itemId, grp.members[0].sid, grp.title));
    renderGroupModalBody(body, grp.members);
  } else if (it) {
    // The top-level goal IS the modal: render it as the ROOT of the tree list (not a separate header
    // title), so a goal with no sub-work is just one list line carrying its own done/blocked state, and
    // any sub-goals render beneath it as the rest of the list (the user 2026-06-16). The header above the
    // tree is only the session name + a recency-tinted age; Follow up moved to the footer below the tree.
    // a NOTICE card's modal shows the notice (round four of PR 1831): its title heads the overlay (a notice has no tree whose
    // first line could stand in), the title locates nothing and lights no chat turn (a notice has none), and an OWNER-LESS
    // card's header name is plain text: no session to open, none to revive (the card header's rule since round two)
    const nt = it.notice || null;
    const ownerless = isOwnerless(it.sid);
    ttlEl.style.display = nt ? "" : "none";
    if (nt) { ttlEl.textContent = it.text; ttlEl.classList.remove("nav"); ttlEl.title = ""; ttlEl.onclick = null; }
    titleHoverId = nt ? null : it.turnId;
    agent.replaceChildren(...hostNameNodes(it.name, it.sid)); agent.style.color = it.color ? it.color.bg : "";
    agent.classList.toggle("fname-plain", ownerless);
    if (ownerless) { setWorkDot(agent, false); agent.classList.remove("dead"); agent.title = ""; agent.onclick = null; }
    else { setWorkDot(agent, dotFor(it.name)); agent.classList.toggle("dead", !it.live); agent.onclick = () => vscodeApi?.postMessage({ type: "openSession", id: it.sid }); }
    ageEl.textContent = relAge(hostNow - it.t);
    wireAgeTip(ageEl, () => provenanceRows(it, hostNow, PROV_FMT));
    ageEl.style.color = "rgb(" + it.trgb.join(",") + ")";   // tint the age by recency (the time colour scheme)
    clrEl.onclick = () => { vscodeApi?.postMessage({ type: "askClear", itemId: it.itemId, sid: it.sid }); fullscreenAskId = null; renderModal(); };
    if (nt) {
      // no session gesture on a notice card's modal: the kernel's follow-up road reads the session out of a GOAL id
      // ("sid:gN"), so Follow up, Check status and Continue on a notice id ("notice:<sid>:<key>:<rev>") are refused as a
      // session no kernel has ("the pane addressed the wrong kernel"), and for an owner-less card there is no session at all;
      // Clear stays (the ordinary askClear with the card's sid, the ledger's road). Round four of PR 1831, medium 2.
      fupEl.style.display = "none"; fuboxEl.style.display = "none";
      if (csEl) csEl.style.display = "none";
      if (contEl) contEl.style.display = "none";
      renderNoticeModalBody(body, it, nt);
    } else {
    // "Check status" (the user 2026-07-20): shown when the card has open/blocked subs to sweep and the
    // session is live to answer. Same ack + re-arm contract as the card button (event-based: the judge's
    // re-file clears the asked state via the fresh modal render).
    if (csEl && it.live && statusSweepText(it).n > 0) {
      csEl.style.display = "";
      if (csEl.disabled && !it.followupPending && !it.recheck && !it.rejudging) { csEl.disabled = false; csEl.textContent = "Check status"; }
      csEl.title = contTitle(csEl.disabled, "a status ask", it.followupAt);
      csEl.onclick = () => {
        const sweep = statusSweepText(it);
        if (!sweep.n) return;
        vscodeApi?.postMessage({ type: "askFollowUp", itemId: it.itemId, text: sweep.text, sid: it.sid });
        csEl.disabled = true; csEl.textContent = "Asked";
        csEl.title = contTitle(true, "a status ask", null);
        optimisticFollowMove(it.itemId);
        render();
      };
    }
    // "Continue" — same gating as the card's button (live needs-you, no live ask), same ack contract.
    if (contEl && askColumn(it) === "needsInput" && it.live && !it.provisional && !it.blocked) {
      contEl.style.display = "";
      if (contEl.disabled && !it.followupPending && !it.recheck && !it.rejudging) { contEl.disabled = false; contEl.textContent = "Continue"; }
      contEl.title = contTitle(contEl.disabled, "a continue", it.followupAt);
      contEl.onclick = () => {
        vscodeApi?.postMessage({ type: "askFollowUp", itemId: it.itemId, sid: it.sid, cont: true });
        contEl.disabled = true; contEl.textContent = "Sent";
        contEl.title = contTitle(true, "a continue", null);
        optimisticFollowMove(it.itemId);
        render();
      };
    }
    // follow-up works in ANY state (the user 2026-06-10) — asks, awaiting, or completed;
    // toggling the button reveals the composer.
    wireFollowUp(fupEl, fuboxEl, fuinEl, fusendEl, (txt) => postFollowUp(txt, it.itemId, it.sid));
    renderTreeBody(body, it, false);   // root goal IS the first list line; sub-goals render beneath it
    applyModalWarnings(body, it);      // debug mode: this card's judge failures, input+reply expandable (the user 2026-07-09)
    }
  }
  // The bottom bar always shows (every modal has an age + Clear); the Follow-up button inside it hides
  // itself for standalone deliverables (no follow-up), and the composer stays collapsed until toggled.
  // modal title hover → light the originating message in the chat (+ its timeline
  // glyph), the same join the title CLICK locates to (the user 2026-06-12). Asks
  // and groups carry the typed-turn id; deliverable/blocked modals have no chat
  // message to point at, so they clear. onmouseenter/leave (assignable props, not
  // addEventListener) so each re-render overwrites instead of stacking handlers.
  ttlEl.onmouseenter = titleHoverId ? () => hoverEmit(titleHoverId) : null;
  ttlEl.onmouseleave = titleHoverId ? () => hoverEmit(null) : null;
}


// Group modal body: each member's own flat tree stacked, member text as its root
// line, chronological. Sig-guarded (member set + per-member tree sigs) so a host
// repush doesn't tear down an open subtree. Collapse state lives in collapsedNodes
// (keyed by itemId:nodeId), so it survives even a full rebuild here.
function renderGroupModalBody(host: HTMLElement, members: AskItem[]) {
  const sig = members.map((m) => m.itemId + "@" + treeSig(m)).join("‖");
  if ((host as any)._sig === sig) return;
  (host as any)._sig = sig;
  host.innerHTML = "";
  for (const m of members) {
    const sec = el("div", "fgroup-modal-member");
    renderTreeBody(sec, m);   // renders m.tree rooted at m's ask node → member text IS the root line
    host.appendChild(sec);
  }
}

// A column entry is an ask card or a group card; the reconcile picks the right
// builder + cache map by kind.
type Entry =
  | { kind: "ask"; t: number; ask: AskItem }
  | { kind: "group"; t: number; group: AskGroup }
  // a SESSION HEADER row in grouped mode (the user 2026-07-13): the session's name + working dot on the
  // column backdrop, heading that session's run of cards. Only emitted for runs that exist.
  // `folded` = how many of this run's cards the header is standing in for (0 when the thread is expanded)
  // `col` = the column this header heads: the fold is per (session, column) — T263c, the user 2026-09-08
  | { kind: "sess"; t: number; sid: string; col: Column; name: string; color: { bg: string; fg: string } | null; live: boolean; folded: number };

// ONE counting rule (the user 2026-08-26): every number on the board counts CARDS, never rows — a
// turn-group entry is worth its members, a folded session header is worth the cards it stands in for.
// Both the section chips and the fold accumulator read THIS, so expanded and collapsed can never
// disagree (the traced bug: the chip counted a group as 1 row while the fold header said "cards").
function entryCards(e: Entry): number {
  return e.kind === "sess" ? e.folded : e.kind === "group" ? e.group.members.length : 1;
}
/** The session an entry belongs to: a card's or a turn-group's owner, a run header's own sid. */
function entrySid(e: Entry): string {
  return e.kind === "ask" ? e.ask.sid : e.kind === "group" ? e.group.sid : e.sid;
}

// Grouped-mode session headers, one reused element per (column, sid) — same keyed-incremental treatment as
// cards so re-renders never rebuild a header mid-press. Pruned when a reconcile drops them from the DOM.
const sessHeadEls = new Map<string, HTMLElement>();
function makeSessHead(): HTMLElement {
  const h = el("div", "feed-sess-head");
  const nm = el("a", "fname"); nm.title = "open this session";
  // Neutral background-process chip (the user 2026-07-24): processes this session keeps running that the
  // judge classified as SERVICES (kernel bgServices — a dev server nobody waits on). Session furniture, so
  // it rides the header, never a card, and wears NO waiting/urgency framing — the .fask-secbtn chip
  // vocabulary, dim by default. Click expands the process list (keyed expand, survives re-renders).
  const svc = el("button", "fask-secbtn feed-sess-svcbtn"); svc.style.display = "none";
  const svcList = el("div", "feed-sess-svclist"); svcList.style.display = "none";
  // FOLD control (the user 2026-07-31), immediately right of the name where they asked for it. A caret is
  // the universal collapse affordance and costs one glyph, where a word chip would repeat on every header;
  // it is the same typographic vocabulary as the sub-goal triangles, never an emoji. Always drawn rather
  // than shown on hover: a hover-only control is invisible on the phone, which is where the feed is read
  // most. The count beside it is what keeps the folded row from dead-ending — you can see what is under it.
  const fold = el("button", "feed-sess-fold");
  const cnt = el("span", "feed-sess-foldn"); cnt.style.display = "none";
  // CLEAR for the whole session (the user 2026-09-08): far right of the header row, the header's own size,
  // as quiet as the caret — the card's Clear in the same chrome, reading "Clear all" (T271, the user 2026-09-08:
  // it clears the whole session, so its label says so). One click clears every card this
  // session has in the current view (every column, folded ones included), with the same optimistic Undo
  // the group clear uses instead of a confirm dialog. The action is DELEGATED on the stable columns root
  // (data-act, installed once where the root is built) — never bound to this header node, which grouped
  // mode re-homes and re-renders; the header only says which session it stands for (data-fsid).
  // THE card's Clear, built by the same builder (the user 2026-09-08: same size, the outline, blue on hover),
  // plus one positional class that carries layout only (far right of the row) — never a lookalike
  const clr = clearButton("clear every card for this session", "Clear all");
  clr.classList.add("feed-sess-clear"); clr.dataset.act = "sess-clear"; clr.style.display = "none";
  h.append(nm, fold, cnt, svc, clr, svcList);
  (h as any)._name = nm; (h as any)._fold = fold; (h as any)._foldn = cnt;
  (h as any)._svc = svc; (h as any)._svcList = svcList; (h as any)._clear = clr;
  // HOVER-FREEZE for the header row too (the user 2026-09-09, T285): a push while the pointer rests on the
  // row — its name, its caret, its Clear all — must not rebuild the row under the pointer (the click-safety
  // rule; a rebuilt Clear all lost the click). The row holds the same payload gate a card holds, keyed by
  // the session it stands for, and releases it on mouseleave exactly like a card; entering the row's own
  // buttons is entering the row (mouseenter/leave do not fire between a row and its children).
  h.addEventListener("mouseenter", () => freezeEnter(sessFreezeKey(h)));
  h.addEventListener("mouseleave", () => freezeLeave(sessFreezeKey(h)));
  return h;
}
/** The hover-freeze key a session header holds: "h:<column>:<sid>", read from the data-fcol and data-fsid stamps at
 *  event time (grouped mode re-homes and re-stamps headers across renders; the stamps are the row's identity). The
 *  key names the (column, session) ROW, the identity reconcileCol keys the element by, not the session alone: a
 *  session heads a run in every column it has cards in, and the badge painter must tell the hovered row from that
 *  session's headers in the other columns. */
function sessFreezeKey(h: HTMLElement): string {
  return "h:" + (h.getAttribute("data-fcol") || "") + ":" + (h.getAttribute("data-fsid") || "");
}
function updateSessHead(h: HTMLElement, e: Entry & { kind: "sess" }): void {
  // the hover-freeze key and its badge painter read the row's session and column from these stamps (sessFreezeKey);
  // compare first, like the labels below: the DOM's change-an-attribute steps queue a mutation record for a
  // same-value write too
  if (h.getAttribute("data-fsid") !== e.sid) h.setAttribute("data-fsid", e.sid);
  if (h.getAttribute("data-fcol") !== e.col) h.setAttribute("data-fcol", e.col);
  let nm = (h as any)._name as HTMLElement;
  // the owner-less run's header name is a SPAN, no anchor at all (round two of PR 1831: an anchor offered to open or revive a
  // session named notes that never existed); a header is keyed per (column, sid), so the swap happens once per header
  if (isOwnerless(e.sid) !== (nm.tagName === "SPAN")) {
    const sw = el(isOwnerless(e.sid) ? "span" : "a", isOwnerless(e.sid) ? "fname-plain" : "fname");
    nm.replaceWith(sw); (h as any)._name = sw; (h as any)._nmSig = undefined; nm = sw;
  }
  // the name nodes are minted only when what they show changes: headers repaint every render (they are not
  // behind the per-card update gate), and each mint is a Text-node replacement — the same reason cards are
  // gated. hostNameNodes reads the name, the sid's host prefix and whether that host's link is down.
  const nmSig = e.name + "\u0000" + e.sid + "\u0000" + (hostIsDown(e.sid) ? "d" : "");
  if ((h as any)._nmSig !== nmSig) { (h as any)._nmSig = nmSig; nm.replaceChildren(...hostNameNodes(e.name, e.sid)); }
  if (e.color) nm.style.color = e.color.bg;
  if (isOwnerless(e.sid)) {
    // the owner-less run's header (Notes, or a remote host's host:Notes) is PLAIN TEXT: no session stands behind it, so no
    // anchor to open, no title, no dead class, no revive offer, no dot
    nm.classList.remove("dead"); nm.removeAttribute("title"); nm.onclick = null;
  } else {
    nm.title = "open this session";
    nm.classList.toggle("dead", !e.live);
    nm.onclick = (ev) => { ev.stopPropagation(); openOrReviveSession(e.sid, e.live, e.name); };
    setWorkDot(nm, dotFor(e.name));   // the working/awaiting dot rides the header, not the cards
  }
  // the fold caret + the "n cards" stand-in for what it hides
  const fold = (h as any)._fold as HTMLElement, foldn = (h as any)._foldn as HTMLElement;
  // per (session, COLUMN) — T263c, the user 2026-09-08: the same session folds in Blocked and stays open in
  // Working; a card that lands in this column later inherits this column's fold
  const tkey = threadKey(e.sid, e.col);
  const shut = collapsedThreads.has(tkey);
  h.classList.toggle("folded", shut);
  setText(fold, shut ? "▸" : "▾");               // ▸ folded / ▾ open
  fold.title = shut ? "show this session's cards in this column" : "collapse this session's cards in this column to its name — new cards here stay folded too";
  fold.setAttribute("aria-expanded", shut ? "false" : "true");
  fold.setAttribute("aria-label", (shut ? "expand " : "collapse ") + e.name);
  foldn.style.display = shut && e.folded ? "" : "none";
  // just the number (the user 2026-08-26) — the section chips' own vocabulary; the words live on hover
  setText(foldn, String(e.folded));
  foldn.title = e.folded === 1 ? "1 card folded under this session" : e.folded + " cards folded under this session";
  fold.onclick = (ev) => {
    ev.stopPropagation();   // the fold IS the acknowledgement: local state + an immediate re-render
    if (collapsedThreads.has(tkey)) collapsedThreads.delete(tkey); else collapsedThreads.add(tkey);
    render();
  };
  // the session-wide Clear: which session, and only while it has cards in the current view (a header
  // exists only for a run, so this is a guard against a stale header, not a common state)
  const sclr = (h as any)._clear as HTMLElement;
  sclr.dataset.fsid = e.sid;
  const ncards = sessionCards(e.sid).length;
  sclr.style.display = ncards ? "" : "none";
  sclr.setAttribute("aria-label", "clear every card for " + e.name);
  const svc = (h as any)._svc as HTMLElement, svcList = (h as any)._svcList as HTMLElement;
  const procs = e.live ? bgServicesMap[e.name] || [] : [];
  const open = procs.length > 0 && openBgSvc.has(e.sid);
  svc.style.display = procs.length ? "" : "none";
  setText(svc, procs.length === 1 ? "background process" : procs.length + " background processes");
  svc.title = open ? "hide the processes" : "processes this session keeps running — click to list";
  svc.classList.toggle("on", open);
  svc.setAttribute("aria-pressed", open ? "true" : "false");
  svc.onclick = (ev) => {
    ev.stopPropagation();   // the expand IS the acknowledgement: local state + immediate re-render
    if (openBgSvc.has(e.sid)) openBgSvc.delete(e.sid); else openBgSvc.add(e.sid);
    render();
  };
  svcList.style.display = open ? "" : "none";
  if (open) svcList.replaceChildren(...procs.map((d) => {
    const r = el("div", "feed-sess-svcrow"); r.textContent = d; return r;
  }));
}

// Undo (top right): restore the most recently cleared card — the host pops
// the newest cleared.jsonl row. Built fresh wherever the top strip renders: on
// the legend row when columns exist, and on the empty state too (clearing the
// LAST card is exactly when undo is wanted). One word (the user 2026-08-24,
// dropping "Undo clear"): it sits right beside Clear all — context enough.
function makeUndoClearBtn(): HTMLElement {
  const b = el("button", "fdismiss ffollow");   // restorative → blue hover (.ffollow), not Clear's red
  b.id = "feed-undoclear";
  b.textContent = "Undo";
  b.title = "restore the most recently cleared card";
  b.onclick = (ev) => {
    ev.stopPropagation();
    b.classList.add("romp-acted");   // instant press acknowledgment (CLAUDE.md), before any round-trip
    // OPTIMISTIC restore (the user 2026-06-27): re-insert the most-recently-cleared batch RIGHT NOW from the
    // client cache, instead of waiting for the kernel to un-archive + rebuild + re-push the feed (the lag the
    // user felt). The kernel's undoClear reconciles on its next push; pendingCleared is dropped for these ids
    // so that push can't re-suppress them.
    if (federatedPane()) clearedStack.length = 0;         // entries cached before a second kernel attached are one kernel's guesses: the round trip below
    const batch = clearedStack.pop();
    const seq = ++undoSeq;                                // the per-undo sequence: the kernel echoes it on the undo's account, so its floor lands on this undo's checks alone
    if (batch && batch.length) {
      undoPopped.set(seq, batch);                         // the click's restore, kept by the undo's sequence until the kernel accounts for it: an account that restored nothing takes it back
      for (const k of Array.from(undoPopped.keys())) { if (undoPopped.size <= UNDO_POPPED_CAP) break; undoPopped.delete(k); }
      for (const it of batch) {
        pendingCleared.delete(it.itemId);
        pendingRestored.set(it.itemId, it);                                  // stay sticky until the kernel push carries it
        // a card still inside its 180 ms collapse keeps its element AND its object, so the per-card update
        // gate would leave `.dismissing` on it and the collapse timer would then remove the restored card:
        // the Undo gesture is the event that takes the class off
        for (const c of cardTwins(it.itemId)) c.classList.remove("dismissing");   // the board's element and the focused section's copy (T347)
        if (!asks.some((a) => a.itemId === it.itemId)) asks.push(it);        // show it NOW
      }
      render();
    } else {
      // the round trip restores the newest batch of the kernels federation sends the undo to. On a single-kernel pane that is this kernel: every
      // suppression goes now, so the payload can show the restored cards. On a FEDERATED pane the click releases NOTHING (round twelve of PR 1967,
      // the round-eleven verifier's design): a release by the routing's hosts freed cards the kernel did not restore, and a suppression ends only on
      // the evidence that the card was restored, its own kernel's payload built after the send listing it (applyFeedPayload)
      if (!federatedPane()) pendingCleared.clear();
      // WORKING cue (the user 2026-07-31): with nothing in this page's cache the restore is a full
      // kernel round-trip and the button read dead for a beat (the optimistic branch above needs no
      // cue — its card appears instantly). Three pulsing accent dots + an accent border say "on it"
      // WITHOUT disabling: each further click keeps popping older batches. Cleared by the NEXT feed
      // payload (the push undoClear triggers — the event this cue is waiting for), with a timeout
      // backstop so a lost push can never trap it.
      b.classList.add("undo-busy");
      if (!b.querySelector(".undo-dots")) {
        const d = el("span", "undo-dots");
        d.append(el("i"), el("i"), el("i"));
        b.appendChild(d);
      }
      window.clearTimeout(undoBusyBackstop);
      undoBusyBackstop = window.setTimeout(clearUndoBusy, 6000);
    }
    vscodeApi?.postMessage({ type: "undoClear", seq });
  };
  return b;
}

let undoBusyBackstop = 0;
function clearUndoBusy(): void {
  window.clearTimeout(undoBusyBackstop);
  const b = document.getElementById("feed-undoclear");
  if (b) { b.classList.remove("undo-busy"); b.querySelector(".undo-dots")?.remove(); }
}

// Clear-all + UndoClear live in #feed-foot — a footer bar in normal flow BELOW the scrolling card
// list, so they can never overlap a card (the user 2026-06-15). Appended once; render() toggles
// each one's display. Clear all is appended first (left); UndoClear second (far right).
function ensureUndoClear(): HTMLElement {
  let b = document.getElementById("feed-undoclear");
  if (!b) { b = makeUndoClearBtn(); (document.getElementById("feed-foot") || document.body).appendChild(b); }
  return b;
}

// Clear all: inbox-zero every open card at once. Destructive, so it hovers RED (.fdismiss); the single
// Undo restores the whole batch (the host clears them as one cleared.jsonl batch).
function makeClearAllBtn(): HTMLElement {
  const b = el("button", "fdismiss");
  b.id = "feed-clearall";
  b.textContent = "Clear all";
  b.title = "clear every open card (inbox-zero) — Undo restores them";
  b.onclick = (ev) => {
    ev.stopPropagation();
    // the batch this gesture makes goes on the Undo stack as the session's Clear all does (round eight of PR 1967): Undo after it restores
    // optimistically, and the page holds every batch it made, which keeps its stack equal to the kernel's (a refusal's frame reconciles it);
    // the cards leave with the kernel's payload, as before
    const members = asks.filter((a) => !pendingCleared.has(a.itemId));
    if (members.length) pushClearedEntry(members.slice());
    vscodeApi?.postMessage({ type: "clearAll" });
  };
  return b;
}

function ensureClearAll(): HTMLElement {
  let b = document.getElementById("feed-clearall");
  if (!b) { b = makeClearAllBtn(); (document.getElementById("feed-foot") || document.body).appendChild(b); }
  return b;
}

// The feed's mount of the SHARED tag-lens menu (tag-menu.ts — one component every surface mounts;
// the user's generalized design). The button is the shared monochrome tag glyph; active (a narrowed
// lens) wears the accent like every footer .on state. The menu inherits cross-pane dismissal free
// (romp:menu-echo). Configure routes to the tags dialog through the kernel (openTagsDialog).
function ensureTagLensBtn(): HTMLElement {
  let b = document.getElementById("feed-taglens") as HTMLElement | null;
  if (!b) {
    b = tagMenuButton("filter this board by tag — combinations union; All shows everything", (btn) => {
      openTagMenu(btn, {
        lens: () => feedLens,
        unions: () => lensUnions(feedTagViews),
        onApply: (l) => { setFeedLens(l); render(); },
        onConfigure: () => vscodeApi?.postMessage({ type: "openTagsDialog" }),
      });
    });
    b.id = "feed-taglens";
    // FOOTER DRESS (the user 2026-08-25, round two: at rest the button outlined blue, and All faded
    // it darker than its neighbours): the shared component ships its own inline style, and inline
    // beats every class rule — strip it and wear the EXACT sibling vocabulary, so the resting state
    // is the neighbours' computed style by construction and can never drift dark again. Active is
    // the standard .on accent ONLY — the class the siblings use, never an inline colour.
    b.removeAttribute("style");
    b.className = "fdismiss ffollow feed-modetoggle";
    (document.getElementById("feed-foot") || document.body).appendChild(b);
  }
  // THE BUTTON CONVENTION (the user 2026-08-25), shared renderer — subsumes the 696 instance
  // toggle: same .on class mechanics (mode "class", so the footer's sibling dress stands), plus
  // the chips of everything selected beside the button, identical to every other mount
  let ch = document.getElementById("feed-tagchips") as HTMLElement | null;
  if (!ch) {
    ch = document.createElement("span");
    ch.id = "feed-tagchips";
    ch.setAttribute("style", "display:inline-flex;gap:5px;align-items:center;margin-left:2px;");
    b.after(ch);
  }
  syncTagFilter(b, ch, feedLens, lensUnions(feedTagViews) as never, (l) => { setFeedLens(l); render(); }, "class");
  return b;
}

// The footer VIEW MENU (the user 2026-08-24): the three view controls — sort direction, single-column
// layout, by-session grouping — live behind ONE monochrome icon button now, a popup wearing the shared
// .ctx-menu vocabulary, where three word-buttons crowded the footer and the labels can breathe.
// Prefs still write the shared romp:settings (the ⛭ gear's watcher and other panes read the same keys).
// The button is ensure-once; the menu lives on document.body outside render()'s reconcile, opening
// upward like the session menu (click-safety: a push can never rebuild it mid-press).
function setViewPref(key: string, on: boolean, after?: (on: boolean) => void): void {
  try {
    const s = JSON.parse(localStorage.getItem("romp:settings") || "{}");
    s[key] = on;
    localStorage.setItem("romp:settings", JSON.stringify(s));
  } catch { /* ignore */ }
  after?.(on);   // runs BEFORE the re-render (e.g. apply the stack style var), on the NEW value
  window.dispatchEvent(new Event("romp:settings"));   // same-doc signal -> re-render (order / layout / grouping)
}
// "Single column view" (the user 2026-08-18, the footer "Stack" button then): force the one-column
// layout at ANY width — the same stacked view the narrow container query produces, as a standing
// choice. The pref drives a style() container condition on #feed-list (see feed.css), so the CSS
// stays the single owner of what stacking means; the narrow query still stacks regardless.
function applyStacked(on: boolean) {
  document.getElementById("feed-list")?.style.setProperty("--romp-stack", on ? "on" : "off");
}
// FORCED stacking (the user 2026-08-19): at or under the container query's own 540px the layout
// stacks regardless of the pref, so the toggle is a no-op there — the menu row says so instead of
// lying: still ✓-checked (stacking IS on), faded, inert, tooltip naming the way out (more width).
// Width changes are the event — a ResizeObserver on #feed-list, installed once.
const STACK_FORCED_W = 540;   // MUST match feed.css's @container (max-width: 540px) stack query
let stackResizeWatch: ResizeObserver | null = null;
let stackForced = false;
function refreshStackForced(): void {
  const list = document.getElementById("feed-list");
  const forced = !!list && list.clientWidth > 0 && list.clientWidth <= STACK_FORCED_W;
  if (forced === stackForced) return;
  stackForced = forced;
  if (viewMenuEl) paintViewMenu(viewMenuEl);   // an open menu repaints on the deciding event
}
// (The "Collapsed" default-section toggle moved into the settings modal, 2026-08-18 — a set-and-forget
// preference, not a per-glance view action. The pref and its behavior are unchanged; the gear writes
// romp:settings.collapsed and the settings watcher below drops the per-card overrides on change.)

let viewMenuEl: HTMLElement | null = null;
function closeViewMenu(): void {
  if (viewMenuEl?.contains(document.activeElement)) document.getElementById("feed-viewbtn")?.focus();
  viewMenuEl?.remove(); viewMenuEl = null;
  document.removeEventListener("pointerdown", viewMenuAway, true);
  document.removeEventListener("keydown", viewMenuKey, true);
}
function viewMenuAway(ev: Event): void {
  const t = ev.target as Node;
  if (viewMenuEl && !viewMenuEl.contains(t) && !(document.getElementById("feed-viewbtn")?.contains(t))) closeViewMenu();
}
function viewMenuKey(ev: KeyboardEvent): void { if (ev.key === "Escape") closeViewMenu(); }
// The rows: "Sort by most recent ↓/↑" keeps the Modified button's rule (the user 2026-08-18) — both
// directions are valid sorts, so the arrow IS the state and the row never wears the ✓; "Single column
// view" and "Group by session" are ✓ rows over the same prefs the old Stack/Group buttons wrote
// ("Group" organizes each column BY SESSION, the user 2026-07-13 — kernel tab/lane order, a name+dot
// header opening each session's run; grouped still defaults ON via feedPrefs' !== false, so the ✓
// reads exactly the way the pressed button did). Rows are real <button>s — Tab-reachable and
// Enter/Space-activatable, the operability the replaced footer buttons had — built ONCE per open and
// then synced IN PLACE (paintViewMenu below), so a live repaint (a settings change from another pane,
// the width crossing 540px) never swaps a row out from under a pressed pointer (click-safety), and a
// click always acts on the prefs AS OF the click, not as of the last paint.
function buildViewMenu(menu: HTMLElement): void {
  const mk = (check: boolean, act: () => void): HTMLElement => {
    const r = el("button", "ctx-item");
    (r as HTMLButtonElement).type = "button";
    r.setAttribute("role", check ? "menuitemcheckbox" : "menuitem");
    r.onclick = (ev) => {
      ev.stopPropagation();
      if (r.classList.contains("forced")) return;   // stacking is automatic at this width — a no-op toggle lies
      act();
      closeViewMenu();
    };
    menu.appendChild(r);
    return r;
  };
  mk(false, () => setViewPref("newestFirst", !feedPrefs().newestFirst));
  mk(true, () => setViewPref("stacked", !feedPrefs().stacked, applyStacked));
  mk(true, () => setViewPref("grouped", !feedPrefs().grouped));
  // "Show focused session" (T347, the user 2026-09-11): the chat's focused session's cards on top of the
  // feed, above a divider. View state of the feed itself, not a shared pref: it rides the feed's persisted
  // view state (FeedViewState.focused, OFF by default), never romp:settings, so the gear and the other panes
  // have nothing to read — and the click re-renders directly, the way the fold carets do.
  mk(true, () => { showFocused = !showFocused; persistViewState(); render(); });
  // the BOARD rows (plans/card-boards.md, phase four): one menuitemradio per board the frame carries, the feed first,
  // shown once a second board exists (with the feed alone the menu is exactly what it was); hidden under a ?board= page
  // (that pick is the page's). A board created by `romp card -b` is a row on the next open, no reload.
  const boards = knownBoards();
  if (!boardQuery && boards.length > 1) {
    const cur = activeBoard();
    for (const b of boards) {
      const r = el("button", "ctx-item ctx-board");
      (r as HTMLButtonElement).type = "button";
      r.setAttribute("role", "menuitemradio");
      r.setAttribute("aria-checked", b === cur ? "true" : "false");
      r.classList.toggle("current", b === cur);
      r.dataset.board = b.id;
      r.textContent = "Board: " + b.title;
      r.title = b === cur ? "the board shown now" : "show the " + b.title + " board (its cards under its own categories)";
      r.onclick = (ev) => { ev.stopPropagation(); setActiveBoard(b.id); closeViewMenu(); };
      menu.appendChild(r);
    }
  }
}
// Sync the four rows to the CURRENT prefs — labels, ✓s, the forced state — without rebuilding them.
function paintViewMenu(menu: HTMLElement): void {
  const p = feedPrefs();
  const rows = Array.from(menu.querySelectorAll(".ctx-item")).filter((r) => !r.classList.contains("ctx-board"));   // the four view rows; the Board radios below them paint at build (a pick closes the menu)
  if (rows.length !== 4) return;
  const set = (i: number, label: string, opts: { current: boolean; forced?: boolean; title: string }) => {
    const r = rows[i] as HTMLElement;
    r.textContent = label;
    r.title = opts.title;
    r.classList.toggle("current", opts.current);
    r.classList.toggle("forced", !!opts.forced);
    if (r.getAttribute("role") === "menuitemcheckbox") r.setAttribute("aria-checked", opts.current ? "true" : "false");
    if (opts.forced) r.setAttribute("aria-disabled", "true"); else r.removeAttribute("aria-disabled");
  };
  set(0, "Sort by most recent " + (p.newestFirst ? "\u2193" : "\u2191"), {
    current: false,   // a DIRECTION row — never the ✓-current mark
    title: p.newestFirst ? "newest at the top — click for oldest first" : "oldest at the top — click for newest first",
  });
  set(1, "Single column view", {
    current: p.stacked || stackForced, forced: stackForced,
    title: stackForced ? "stacked automatically at this width — widen the feed to unstack into three columns"
      : p.stacked ? "one-column layout at any width — click for side-by-side columns when the feed is wide"
      : "stack the columns into one, whatever the width",
  });
  set(2, "Group by session", {
    current: p.grouped,
    title: p.grouped ? "grouped by session — click for the flat column order"
      : "group each column's cards by session (tab order), a session header between runs",
  });
  set(3, "Show focused session", {
    current: showFocused,
    title: showFocused ? "the chat's focused session has its cards on top — click to hide the section"
      : "put the chat's focused session's cards on top of the feed, above a divider",
  });
}
function openViewMenu(btn: HTMLElement): void {
  closeSessList();   // one menu at a time: a keyboard open fires no pointerdown, so the away-closers never ran
  const menu = el("div", "ctx-menu feed-viewmenu");
  menu.setAttribute("role", "menu");
  refreshStackForced();   // decide the forced row from the CURRENT width, not the last observed one
  buildViewMenu(menu);
  paintViewMenu(menu);
  document.body.appendChild(menu);
  // above the footer, left-aligned to the button, clamped into the viewport (the session menu's placement)
  const r = btn.getBoundingClientRect();
  menu.style.bottom = Math.round(window.innerHeight - r.top + 6) + "px";
  menu.style.left = Math.round(Math.max(6, Math.min(r.left, window.innerWidth - menu.offsetWidth - 6))) + "px";
  viewMenuEl = menu;
  (menu.querySelector(".ctx-item") as HTMLElement | null)?.focus();   // a keyboard open lands on the first row
  document.addEventListener("pointerdown", viewMenuAway, true);
  document.addEventListener("keydown", viewMenuKey, true);
}
// A WORD, not an icon (the user 2026-08-24, round two: the ordering glyph beside "Sessions ▴" read
// as "not what I would expect for what to show"): "View ▴" says exactly what clicking does — the
// footer's own word-button vocabulary, the same upward caret its Sessions neighbour wears. The
// original glyph existed to be compact; one short word costs a few px and buys first-look legibility.
function ensureViewMenuBtn(): HTMLElement {
  let b = document.getElementById("feed-viewbtn") as HTMLElement | null;
  if (!b) {
    b = el("button", "fdismiss ffollow feed-modetoggle");
    b.id = "feed-viewbtn";
    b.textContent = "View \u25b4";
    b.title = "view options — sort direction, single column, group by session, the focused session on top";
    b.setAttribute("aria-haspopup", "menu");
    b.onclick = (ev) => {   // opening the menu IS the acknowledgement (same as the session filter)
      ev.stopPropagation();
      if (viewMenuEl) closeViewMenu(); else openViewMenu(b!);
    };
    (document.getElementById("feed-foot") || document.body).appendChild(b);
  }
  const list = document.getElementById("feed-list");
  if (!stackResizeWatch && list && typeof ResizeObserver !== "undefined") {
    stackResizeWatch = new ResizeObserver(() => refreshStackForced());
    stackResizeWatch.observe(list);
  }
  return b;
}

// The SESSION COMBOBOX (the user 2026-08-24, merging the 2026-08-08 session picker and the
// 2026-08-23 search box): ONE footer control owns "which sessions am I looking at". Collapsed, a
// single "Sessions ▴" word-button. Open, the top-bar-style input with the session list beneath —
// every row written the way every other surface writes a session (bold name in its identity colour,
// "host:" prefix folded quiet, the shared working/awaiting dot; the current pick wears the accent
// wash, exactly today's menu). TYPING narrows the list AND applies the live substring filter
// (romp:feedSearch — semantics unchanged); PICKING a row applies the exact-session filter
// (romp:feedOnly — semantics unchanged), rendered as a chip in the bar whose ✕ hands the bar back
// to typing. The two filters compose downstream exactly as before (viewFiltered). Invariants kept
// from both parents: an ACTIVE filter of either kind force-opens the bar (a compact state can never
// hide a live filter); Escape folds, and folding with anything live CLEARS it; the wrap is
// ensure-once and the list lives on document.body outside render()'s reconcile (click-safety); the
// list is built ONCE per open and typing only toggles row display, so a keystroke can never rebuild
// a row out from under a press.
let sessListEl: HTMLElement | null = null;
function closeSessList(): void {
  sessListEl?.remove(); sessListEl = null;
  document.removeEventListener("pointerdown", sessListAway, true);
  document.removeEventListener("keydown", sessListKey, true);
}
function sessListAway(ev: Event): void {
  const t = ev.target as Node;
  if (!sessListEl || sessListEl.contains(t) || document.getElementById("feed-search")?.contains(t)) return;
  closeSessList();
  // an away-click closes the LIST only — never a filter-clearing fold: clicking a card must not
  // wipe a live filter (clear-on-fold is for EXPLICIT folds — Escape, the button). With nothing
  // live the bar collapses quietly; force-open keeps it up otherwise.
  if (!feedSearchQ.trim() && !feedOnlySid) document.getElementById("feed-search")?.classList.remove("open");
}
function sessListKey(ev: KeyboardEvent): void { if (ev.key === "Escape") { closeSessList(); foldSessBox(); } }
// A session's name in the list wears EXACTLY the identity treatment every other surface gives it (the
// user 2026-08-08): bold, in the session's own colour, host prefix folded quiet — the way the chat tabs
// and the grouped session headers write it. Never a colour swatch: a dot beside a name on this board
// already MEANS working/awaiting (the shared fwork-dot vocabulary), so that status dot rides here too.
function sessMenuName(s: { sid: string; name: string; color: { bg: string; fg: string } | null }): HTMLElement {
  const nm = el("span", "fsm-name");
  nm.replaceChildren(...hostNameNodes(s.name, s.sid));
  if (s.color) nm.style.color = s.color.bg;
  return nm;
}
// Typing narrows the OPEN list in place: display toggles only, never a rebuild (click-safety). The
// "All sessions" row always shows — the way back can never be filtered away (no-dead-end).
function filterSessList(q: string): void {
  if (!sessListEl) return;
  sessListEl.querySelectorAll<HTMLElement>(".fsm-row").forEach((r) => {
    const name = r.getAttribute("data-name");
    r.style.display = name === null || searchMatches(q, name) ? "" : "none";
  });
}
function repaintSessListCurrent(): void {
  if (!sessListEl) return;
  sessListEl.querySelectorAll<HTMLElement>(".fsm-row").forEach((r) => {
    const on = (r.getAttribute("data-sid") || null) === feedOnlySid;
    r.classList.toggle("on", on);
    r.setAttribute("aria-selected", on ? "true" : "false");   // option rows select; checked is the checkbox pattern
  });
}
function openSessList(): void {
  closeViewMenu();   // one menu at a time: a keyboard open fires no pointerdown, so the away-closers never ran
  const wrap = document.getElementById("feed-search");
  if (!wrap || sessListEl) return;
  const menu = el("div", "feed-sessmenu");
  menu.setAttribute("role", "listbox");
  const row = (pick: string | null, label: HTMLElement, name: string | null, dotName?: string) => {
    const r = el("div", "fsm-row");
    r.appendChild(label);
    if (dotName) setWorkDot(label, dotFor(dotName));   // inserts the status dot before the name, in place
    r.setAttribute("role", "option");
    if (pick !== null) r.setAttribute("data-sid", pick);
    if (name !== null) r.setAttribute("data-name", name);
    // TAG CHIPS inline (the user 2026-08-25 — the unification call's smaller variant): the session's
    // name-keyed union tags as compact outline chips, the dialog's own one-chip-per-name vocabulary,
    // NON-interactive (grouping made visible; the two controls stay separate and the pick is
    // untouched). The strip ellipsizes in the row's leftover space so names stay primary.
    // (Deliberately NOT built, decided: search matching tag names — the pick list stays sessions-only.)
    if (pick !== null) {
      const chips = el("span", "fsm-chips");
      for (const g of lensUnions(feedTagViews)) {
        if (!g.members.includes(pick)) continue;
        const c = tagChip(g.name, g.color || null);   // the one tag chip (T321); the class is the dialog's layout hook
        c.classList.add("fsm-chip-tag");
        chips.appendChild(c);
      }
      if (chips.childElementCount) r.appendChild(chips);
    }
    r.onclick = (ev) => {   // pick = the exact filter, worn as the bar's chip; the list closes, the bar stays
      ev.stopPropagation();
      const already = (r.getAttribute("data-sid") || null) === feedOnlySid;
      setFeedOnly(already ? null : pick);
      const inp = document.getElementById("feed-search-input") as HTMLInputElement | null;
      if (inp) { inp.value = ""; inp.focus(); }   // back to typing mode; the chip carries the pick
      setFeedSearch("");
      closeSessList();
      render();
    };
    menu.appendChild(r);
  };
  const all = el("span", "");
  all.textContent = "All sessions";
  row(null, all, null);
  // tab order: rank by the kernel's session-order list (the same rank grouped mode sorts by); a sid the
  // list doesn't know keeps its place in the kernel's tab list (stable sort), after the ranked ones
  const rank = new Map(sessionOrder.map((s, i) => [s, i] as const));
  const rows = sessionsMeta.slice().sort((a, b) => (rank.get(a.sid) ?? 1e9) - (rank.get(b.sid) ?? 1e9));
  for (const s of rows) row(s.sid, sessMenuName(s), s.name, s.name);
  document.body.appendChild(menu);
  // above the footer, aligned to the BAR and at least its width (combobox convention), clamped in
  const r = wrap.getBoundingClientRect();
  menu.style.minWidth = Math.max(150, Math.round(r.width)) + "px";
  menu.style.bottom = Math.round(window.innerHeight - r.top + 6) + "px";
  menu.style.left = Math.round(Math.max(6, Math.min(r.left, window.innerWidth - menu.offsetWidth - 6))) + "px";
  sessListEl = menu;
  repaintSessListCurrent();
  filterSessList(feedSearchQ);
  document.addEventListener("pointerdown", sessListAway, true);
  document.addEventListener("keydown", sessListKey, true);
}
// Folding with anything live CLEARS it — the bar never hides an active filter of either kind.
function foldSessBox(): void {
  const wrap = document.getElementById("feed-search");
  const inp = document.getElementById("feed-search-input") as HTMLInputElement | null;
  let changed = false;
  if (inp && inp.value.trim()) { inp.value = ""; changed = true; }
  if (feedSearchQ.trim()) { setFeedSearch(""); changed = true; }
  if (feedOnlySid) { setFeedOnly(null); changed = true; }
  wrap?.classList.remove("open");
  closeSessList();
  if (changed) render();
}
function ensureSessionBox(): HTMLElement {
  let wrap = document.getElementById("feed-search") as HTMLElement | null;
  if (!wrap) {
    wrap = el("span", "");
    wrap.id = "feed-search";
    const btn = el("button", "fdismiss ffollow feed-modetoggle");
    btn.id = "feed-search-btn";
    btn.textContent = "Sessions \u25b4";
    btn.title = "filter the board by session — type to narrow (host prefix counts), or pick one exactly";
    btn.setAttribute("aria-haspopup", "listbox");
    const chip = el("span", "fsm-chip");
    chip.id = "feed-sess-chip";
    chip.hidden = true;
    const inp = document.createElement("input");
    inp.id = "feed-search-input";
    inp.type = "search";
    inp.placeholder = "session or host…";
    inp.setAttribute("aria-label", "filter cards by session name (host prefix included), or pick a session from the list");
    const openBox = () => { wrap!.classList.add("open"); openSessList(); inp.focus(); };
    btn.onclick = (ev) => { ev.stopPropagation(); wrap!.classList.contains("open") ? foldSessBox() : openBox(); };
    inp.onfocus = () => { if (!sessListEl) openSessList(); };   // focus re-opens the list (a pick closed it)
    inp.oninput = () => { setFeedSearch(inp.value); filterSessList(inp.value); render(); };   // live: narrows list AND board
    inp.onkeydown = (ev) => { if (ev.key === "Escape") { ev.stopPropagation(); foldSessBox(); } };
    inp.onblur = () => {   // an empty bar folds quietly when focus leaves AND the list is gone — a row
      //                      press keeps the list (blur fires first); the away-closer owns that case
      if (!sessListEl && !inp.value.trim() && !feedOnlySid) wrap!.classList.remove("open");
    };
    const clr = el("button", "");
    clr.id = "feed-search-clear";
    (clr as HTMLButtonElement).type = "button";
    clr.setAttribute("aria-label", "Clear search");
    clr.title = "Clear search";
    clr.hidden = true;   // shown only with text to clear (the top bar's semantics); render() below syncs it
    clr.textContent = "\u00d7";
    clr.onclick = (ev) => {   // clear + REFOCUS — the user is mid-search, never fold under them
      ev.stopPropagation();
      inp.value = ""; setFeedSearch(""); filterSessList(""); inp.focus(); render();
    };
    wrap.appendChild(btn); wrap.appendChild(chip); wrap.appendChild(inp); wrap.appendChild(clr);
    (document.getElementById("feed-foot") || document.body).appendChild(wrap);
  }
  const inp = wrap.querySelector("input") as HTMLInputElement;
  if (inp && inp.value !== feedSearchQ && document.activeElement !== inp) inp.value = feedSearchQ;
  const clrBtn = document.getElementById("feed-search-clear");
  if (clrBtn && inp) clrBtn.hidden = !inp.value.trim();   // trimmed, like the fold + the filter — whitespace is no query
  // the chip quotes the picked session verbatim, dot included — a narrowed board must never look whole
  const chip = document.getElementById("feed-sess-chip") as HTMLElement | null;
  const cur = feedOnlySid ? sessionsMeta.find((s) => s.sid === feedOnlySid) : undefined;
  if (chip) {
    chip.hidden = !cur;
    if (cur) {
      // the ✕ is built ONCE (a per-render rebuild would swap it under a press — click-safety);
      // only the NAME re-quotes each render, so colour echoes and the working/awaiting dot stay live
      let nm = (chip as any)._nm as HTMLElement | undefined;
      if (!nm) {
        nm = el("span", "fsm-name");
        const x = el("button", "fsm-chipx");
        (x as HTMLButtonElement).type = "button";
        x.textContent = "\u00d7";
        x.setAttribute("aria-label", "show all sessions");
        x.title = "show all sessions — back to typing";
        x.onclick = (ev) => {
          ev.stopPropagation();
          setFeedOnly(null);
          repaintSessListCurrent();
          (document.getElementById("feed-search-input") as HTMLInputElement | null)?.focus();
          render();
        };
        chip.replaceChildren(nm, x);
        (chip as any)._nm = nm;
      }
      nm.replaceChildren(...hostNameNodes(cur.name, cur.sid));
      nm.style.color = cur.color ? cur.color.bg : "";
      setWorkDot(nm, dotFor(cur.name));
    }
  }
  // an ACTIVE filter of either kind force-opens the bar — never hidden behind the collapsed button
  const active = !!feedSearchQ.trim() || !!feedOnlySid;
  if (active) wrap.classList.add("open");
  const btn = document.getElementById("feed-search-btn");
  if (btn) { btn.classList.toggle("on", active); btn.setAttribute("aria-pressed", active ? "true" : "false"); }
  return wrap;
}

// (The footer "Sub-goals" checkbox was removed 2026-07-08: sub-goals is now a per-card "Sub-goals" button
// beside Summary — wired in applySections as the third mutually-exclusive section.)

// Build the three columns (Asks | Awaiting | Completed) inside #feed-list once;
// rebuild if torn down (empty state). "Awaiting" (the user's ruling 2026-06-10):
// matches the session-chip vocabulary — anything here awaits HIM (a question,
// an action like reload, an idea), red like the awaiting chip.
const STACK_DEFAULT = ["completed", "needsInput", "asks"];   // the stacked CSS default, top-down (2026-07-30)
const ROW_DEFAULT = ["asks", "needsInput", "completed"];     // the side-by-side CSS default — the build order

// Paint the column-order state (ONE order, two renderings — the user 2026-08-24): each column's
// --col-order var feeds BOTH layouts' `order:` rules; with no custom order the var comes OFF, so
// each layout keeps its own default (stacked: Completed→Blocked→Working, the user 2026-07-30; side
// by side: Working→Blocked→Completed, the build order). Also each section's fold (stacked-only CSS).
// Idempotent; runs at build, per toggle, and per drag re-slot.
function applyColStack(): void {
  const custom = orderComplete(colOrder) ? colOrder : null;
  for (const key of activeCols()) {
    // the BOARD's column, under #feed-cols: the focused-session section above it carries the same column
    // classes (T347), and a bare query would land on that copy first. The fold is the board's alone; the
    // section's blocks take their order from applyFocusLayout below (the board's, until the user drags THERE).
    const col = document.querySelector<HTMLElement>("#feed-cols .feed-col.col-" + key);
    if (!col) continue;
    const folded = collapsedCols.has(foldKey(key));
    col.classList.toggle("col-collapsed", folded);
    if (custom) col.style.setProperty("--col-order", String(custom.indexOf(key) + 1));
    else col.style.removeProperty("--col-order");
    const fold = col.querySelector<HTMLElement>(".fcol-fold");
    if (fold) {
      fold.textContent = folded ? "▸" : "▾";
      fold.setAttribute("aria-expanded", String(!folded));
    }
  }
  applyFocusLayout();   // the section mirrors the board's arrangement until it has an order of its own (T410)
}

// The focused-session section's BLOCK LAYOUT (T410, the user 2026-09-13, who wanted the section's blocks
// movable, resizable and collapsible on their own, none leaving the section). ORDER: the section's own
// focusOrder once it holds three keys, else the board's arrangement exactly as before (colOrder, or each
// layout's CSS default with the var off) — so nothing changes for anyone who never drags in the section.
// WIDTH: each block's weight (focusW, 1 = the equal split) as its flex-grow; the blocks' flex-basis is 0, so the
// weights ARE the split. FOLD: a collapsed block wears col-collapsed (its list hidden, the block shrunk to its
// head — the inline weight cleared so the class's flex: 0 0 auto stands — and the others take the room). The
// gutter is hidden on a collapsed block and on the last expanded block in visual order (nothing to its right
// to trade width with; in the stacked layout the CSS hides every gutter). HEIGHT is never resized: the section
// grows with what the focused session holds. Idempotent; runs at build, per fold, per drag re-slot, per resize.
function applyFocusLayout(): void {
  if (!document.getElementById("feed-focus")) return;
  const order = orderComplete(focusOrder) ? focusOrder : orderComplete(colOrder) ? colOrder : null;
  const visual = (order || rowDefault()).filter((k) => !collapsedFocusCols.has(k));
  for (const key of activeCols()) {
    const twin = document.querySelector<HTMLElement>("#feed-focus .feed-col.col-" + key);
    if (!twin) continue;
    if (order) twin.style.setProperty("--col-order", String(order.indexOf(key) + 1));
    else twin.style.removeProperty("--col-order");
    const folded = collapsedFocusCols.has(key);
    twin.classList.toggle("col-collapsed", folded);
    twin.style.flexGrow = folded ? "" : String(focusW[key] ?? 1);
    const fold = twin.querySelector<HTMLElement>(".fcol-fold");
    if (fold) {
      fold.textContent = folded ? "▸" : "▾";
      fold.setAttribute("aria-expanded", String(!folded));
      fold.setAttribute("aria-label", (folded ? "Expand " : "Collapse ") + (fold.dataset.label || ""));
    }
    const gutter = twin.querySelector<HTMLElement>(".focus-gutter");
    if (gutter) gutter.hidden = folded || visual[visual.length - 1] === key;
  }
}

// The GUTTER on a section block's right edge (T410): dragging it trades width between this block and the next
// expanded block in visual order. The two weights move as a pair — sum preserved, floor 0.35 each — so a drag
// can never empty a block or spill past its neighbour; the weights paint live as flex-grow and persist on
// release. Pointer capture, like the block drag, so the drag survives leaving the 8px zone. Width only: the
// section's height follows its content and is never resized (see applyFocusLayout).
function wireFocusGutter(gutter: HTMLElement, key: string): void {
  gutter.addEventListener("pointerdown", (down) => {
    const col = FOCUS_SLOTS.col(key);
    const order = orderComplete(focusOrder) ? focusOrder : orderComplete(colOrder) ? colOrder : rowDefault();
    const visual = order.filter((k) => !collapsedFocusCols.has(k));
    const next = visual[visual.indexOf(key) + 1];
    const other = next ? FOCUS_SLOTS.col(next) : null;
    if (!col || !next || !other) return;
    down.preventDefault();
    down.stopPropagation();
    gutter.setPointerCapture(down.pointerId);
    gutter.classList.add("active");
    const w0 = focusW[key] ?? 1, sum = w0 + (focusW[next] ?? 1);
    const px = col.getBoundingClientRect().width + other.getBoundingClientRect().width;   // the pair's pixels = the pair's weights
    const startX = down.clientX;
    const MIN_W = 0.35;
    const move = (ev: PointerEvent) => {
      if (!px) return;
      const w = Math.min(sum - MIN_W, Math.max(MIN_W, w0 + (ev.clientX - startX) * sum / px));
      focusW = { ...focusW, [key]: w, [next]: sum - w };
      applyFocusLayout();
    };
    const up = () => {
      gutter.removeEventListener("pointermove", move);
      gutter.removeEventListener("pointerup", up);
      gutter.removeEventListener("pointercancel", up);
      gutter.classList.remove("active");
      for (const k of Object.keys(focusW)) focusW[k] = Math.round(focusW[k] * 1000) / 1000;   // three decimals in the blob
      persistViewState();
    };
    gutter.addEventListener("pointermove", move);
    gutter.addEventListener("pointerup", up);
    gutter.addEventListener("pointercancel", up);
  });
}

// The BLOCK's KEYS (T410b): ArrowLeft / ArrowRight on the section's focused chip move its block one slot within
// the section (ArrowUp / ArrowDown the same, the stacked layout's axis), persisted at once — the keyboard's road to
// the drag. The order it moves from is the one on screen: the section's own, else what the section follows (the
// board's, or the layout's default), exactly as the drag seeds itself.
function wireBlockKeys(chip: HTMLElement, key: string): void {
  chip.addEventListener("keydown", (e) => {
    const delta = e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : 0;
    if (!delta) return;
    const colsEl = FOCUS_SLOTS.container();
    if (!colsEl) return;
    e.preventDefault();
    e.stopPropagation();   // the chip's key, not the card cursor's (kbMode listens on the document for the same arrows)
    const vertical = getComputedStyle(colsEl).flexDirection === "column";
    const cur = FOCUS_SLOTS.get();
    const fallback = FOCUS_SLOTS.fallback(vertical ? STACK_DEFAULT : ROW_DEFAULT);
    const hadCustom = orderComplete(cur);
    const order = (hadCustom ? cur : fallback).slice();
    // one slot among the blocks ON SCREEN (visibleKeys): a hidden neighbour is skipped, never swapped behind
    const visible = visibleKeys(order, FOCUS_SLOTS.col);
    const from = visible.indexOf(key), to = from + delta;
    if (from < 0 || to < 0 || to >= visible.length) return;
    const nv = visible.slice();
    nv.splice(from, 1);
    nv.splice(to, 0, key);
    const next = placeVisible(order, visible, nv);
    // the no-trace rule per PROVENANCE (T410 review): an order the keys minted out of a following state
    // (focusOrderByKeys) is walked back to nothing stored when a press lands on the arrangement the section follows;
    // an order the user pinned by DRAG is never cleared by a key that happens to land there. (From a following state
    // itself the order IS the fallback and a one-slot move always leaves it, so the clear rests on the flag alone.)
    if (next.join() === fallback.join() && focusOrderByKeys) {
      FOCUS_SLOTS.set([]);
      focusOrderByKeys = false;
    } else {
      FOCUS_SLOTS.set(next);
      if (!hadCustom) focusOrderByKeys = true;   // minted by the keys out of a following state: walkable back
    }
    persistViewState();
  });
}

// Drag a section by its CATEGORY CHIP — in BOTH layouts now (the user 2026-08-24, reversing the
// 2026-08-16 stacked-only exclusion with their own ask: the columns should drag around in
// three-column view just as the sections already do stacked): stacked, the drag re-slots the section vertically;
// side by side, it reorders the three columns horizontally. ONE persisted order feeds both
// renderings (colOrder). The grab cursor on the chip is the affordance. While dragging, the grabbed
// section FOLLOWS the pointer along the drag axis (a transform, so nothing reflows under the hand)
// and the displaced sections FLIP-animate into their provisional slots — the arrangement you see
// mid-drag is the arrangement you get on drop.
//
// ONE implementation for two containers (T410): the BOARD (the chip drags a column of #feed-cols; colOrder,
// the default `slots`) and the focused-session SECTION (its chip drags a block of #feed-focus; focusOrder). A
// SlotDrag names the container (the drag axis is read from it), the order it reads and writes, the element per
// key and the order a drag starts from when none is stored — so the BOUND is the container: a section drag
// never touches a board column, and a board drag never reaches the section.
type SlotDrag = {
  container: () => HTMLElement | null;
  col: (key: string) => HTMLElement | null;
  get: () => string[];
  set: (order: string[]) => void;
  fallback: (layoutDefault: string[]) => string[];   // the seed order with nothing stored
};
const BOARD_SLOTS: SlotDrag = {
  container: () => document.getElementById("feed-cols"),
  col: (k) => document.querySelector<HTMLElement>("#feed-cols .feed-col.col-" + k),   // the board's, not the focused section's copy (T347)
  get: () => colOrder,
  set: (o) => { colOrder = o; applyColStack(); },
  fallback: (d) => d,   // each layout's own CSS default
};
const FOCUS_SLOTS: SlotDrag = {
  container: () => document.querySelector<HTMLElement>("#feed-focus .feed-focus-cols"),
  col: (k) => document.querySelector<HTMLElement>("#feed-focus .feed-col.col-" + k),
  get: () => focusOrder,
  set: (o) => { focusOrder = o; applyFocusLayout(); },
  fallback: (d) => (orderComplete(colOrder) ? colOrder : d),   // the section follows the board until it has an order of its own
};
// A re-slot walks VISIBLE blocks only (T410 review round two): in the single-column layout a focused block whose
// category has no cards is display: none (col-empty), and its rect is all zeros, so a midpoint walk over every key
// read 0 for each hidden block after the dragged one and jumped the target to the LAST slot on the first move
// (a 14 px jiggle on the one visible chip stored an order the user never chose; a one-slot drag past a visible
// neighbour landed behind a hidden one, surfacing only when that block's first card arrived). The dragged block
// moves among the blocks on screen; hidden blocks keep their relative places in the stored order.
function visibleKeys(order: string[], colOf: (k: string) => HTMLElement | null): string[] {
  return order.filter((k) => {
    const e = colOf(k);
    if (!e) return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 || r.height > 0;   // display: none (a hidden block) is the zero rect; a folded block still has its head
  });
}
function placeVisible(order: string[], visible: string[], newVisible: string[]): string[] {
  const out = order.slice();
  const slotsIdx = order.map((k, i) => (visible.includes(k) ? i : -1)).filter((i) => i >= 0);
  newVisible.forEach((k, i) => { out[slotsIdx[i]] = k; });
  return out;
}
const DRAG_SLOP_PX = 4;   // a pointer that moved past this from the press is a DRAG; under it the gesture is a click (T410 review)
function wireColDrag(chip: HTMLElement, col: HTMLElement, key: string, slots: SlotDrag = BOARD_SLOTS): void {
  chip.addEventListener("pointerdown", (down) => {
    if (down.button !== 0) return;   // the primary button (or a touch, a pen) arms the drag; a right press never did anything useful
    const colsEl = slots.container();
    if (!colsEl) return;
    const startOrder = slots.get().slice();   // what the press started from: a gesture that ends elsewhere CHANGED an order
    const vertical = getComputedStyle(colsEl).flexDirection === "column";   // the drag AXIS, per layout
    // the pointerdown's default STANDS (T410 review): the browser focuses a focusable chip natively, pointer-initiated,
    // so a mouse click arms the arrow keys without a Tab and without the keyboard's :focus-visible ring or a
    // scroll-into-view (a scripted focus() inside a prevented pointerdown painted the ring on every click and lurched
    // a clipped chip into view); selection and touch are held by the chip's CSS (user-select: none, touch-action: none)
    down.stopPropagation();
    chip.setPointerCapture(down.pointerId);
    col.classList.add("col-dragging");
    let dragged = false;   // a pointer that moved past the slop: the chip gives focus back when the drag ends (a click keeps it)
    const pos = (ev: PointerEvent) => (vertical ? ev.clientY : ev.clientX);
    const edge = (r: DOMRect) => (vertical ? r.top : r.left);
    const midOf = (r: DOMRect) => (vertical ? r.top + r.height / 2 : r.left + r.width / 2);
    const translate = (d: number) => (vertical ? "translateY(" + d + "px)" : "translateX(" + d + "px)");
    const fallback = slots.fallback(vertical ? STACK_DEFAULT : ROW_DEFAULT);   // each layout's own default, or what the container follows
    const hadCustom = orderComplete(slots.get());   // for the no-trace rule in up()
    const start = pos(down);
    let slotShift = 0;   // the dragged section's own accumulated slot movement — folded into its
    //                      follow-transform so a re-slot never yanks it out from under the pointer
    const applyOrderFlip = (order: string[]) => {
      const els: Array<[string, HTMLElement]> = [];
      for (const k of activeCols()) {
        const e = slots.col(k);   // this container's element for the key, never the other container's
        if (e) els.push([k, e]);
      }
      const before = new Map(els.map(([k, e]) => [k, edge(e.getBoundingClientRect())]));
      slots.set(order);
      for (const [k, e] of els) {
        const d = (before.get(k) || 0) - edge(e.getBoundingClientRect());
        if (!d) continue;
        if (k === key) { slotShift -= d; continue; }   // both rects carry the follow-transform, so d is pure slot delta
        e.animate([{ transform: translate(d) }, { transform: translate(0) }],
                  { duration: 150, easing: "ease" });
      }
    };
    const move = (ev: PointerEvent) => {
      const cur = slots.get();
      const order = (orderComplete(cur) ? cur : fallback).slice();
      // the slot whose axis midpoint the pointer is past — walk the OTHER VISIBLE sections' rects (visibleKeys: a
      // block the single-column layout hides has a zero rect and no slot to offer)
      const visible = visibleKeys(order, slots.col);
      const from = visible.indexOf(key);
      let to = from;
      if (from >= 0) {
        for (const other of visible) {
          if (other === key) continue;
          const oc = slots.col(other);
          if (!oc) continue;
          const m = midOf(oc.getBoundingClientRect());
          const oi = visible.indexOf(other);
          if (oi < from && pos(ev) < m) { to = Math.min(to, oi); }
          if (oi > from && pos(ev) > m) { to = Math.max(to, oi); }
        }
      }
      if (to !== from) {
        const nv = visible.slice();
        nv.splice(from, 1);
        nv.splice(to, 0, key);
        applyOrderFlip(placeVisible(order, visible, nv));   // hidden blocks keep their relative places
      }
      col.style.transform = translate(pos(ev) - start - slotShift);
      if (Math.abs(pos(ev) - start) > DRAG_SLOP_PX) dragged = true;   // a trackpad tap or a slipping click stays a click
    };
    const up = () => {
      chip.removeEventListener("pointermove", move);
      chip.removeEventListener("pointerup", up);
      chip.removeEventListener("pointercancel", up);
      // a DRAG ends with the chip no longer holding focus, so the arrow keys go back to the card cursor (a click that
      // never moved keeps the focus it took: that is how the keys arm)
      if (dragged && chip.tabIndex >= 0 && document.activeElement === chip) chip.blur();
      // settle: animate from wherever the hand left it into its slot, then drop the transform
      const hang = col.style.transform;
      col.style.transform = "";
      if (hang && hang !== translate(0)) {
        col.animate([{ transform: hang }, { transform: translate(0) }],
                    { duration: 150, easing: "ease" });
      }
      col.classList.remove("col-dragging");
      // a drag dropped back where it started leaves NO trace (review 2026-08-24): without a
      // pre-existing custom order, ending on this layout's own default must not mint an EXPLICIT
      // order — that would silently re-arrange the OTHER layout, which keeps a different default (and in
      // the section, dropping back on the board's arrangement keeps FOLLOWING the board rather than pinning it)
      const cur = slots.get();
      if (!hadCustom && orderComplete(cur) && cur.join() === fallback.join()) slots.set([]);
      // the keys' provenance flag drops only when this gesture CHANGED a stored order (T410 review round three): a
      // section drag that landed elsewhere pinned its order by drag, a board drag that landed elsewhere changed what
      // the section follows; a click, and a there-and-back drag, leave a key-minted order walkable back
      if (slots.get().join() !== startOrder.join()) focusOrderByKeys = false;
      persistViewState();
    };
    chip.addEventListener("pointermove", move);
    chip.addEventListener("pointerup", up);
    chip.addEventListener("pointercancel", up);
  });
}

function ensureCols(list: HTMLElement) {
  const board = activeBoard();
  const stale = document.getElementById("feed-cols");
  if (stale && stale.dataset.board !== board.id) { stale.remove(); removeFocusSection(); }   // the view switch (phase four): another board's columns come down whole
  if (!document.getElementById("feed-cols")) {
    list.innerHTML = "";
    const cols = el("div", "feed-cols"); cols.id = "feed-cols"; cols.dataset.board = board.id;
    // Header actions ride the STABLE columns root (the click-safety rule): the header nodes under it are
    // re-homed and re-rendered on every push, and a native click needs mousedown and mouseup on one element.
    // delegate() also flashes the pressed control (.romp-acted), the instant acknowledgement.
    delegate(cols, {
      "sess-clear": (b, ev) => { ev.stopPropagation(); const sid = b.dataset.fsid; if (sid) clearSessionCards(sid); },
    });
    // "Working" (the user's rename, 2026-06-11): every card is an ASK; the left
    // column holds the ones being worked — internal keys keep the old names
    // each header is a filled state chip reproducing the chat status chips
    // (styles.css .chip): working=yellow, blocked=awaiting-red, completed=ready-blue.
    for (const [key, label, chip] of columnTable(activeBoard())) {   // the board's categories, in its order (board-def.ts)
      const col = el("div", "feed-col col-" + key);
      const head = el("div", "feed-col-head");
      // header furniture (the user 2026-08-16): a caret LEFT of the chip folds the whole category to
      // its header (stacked-only, hidden side by side by CSS), and the CHIP ITSELF drags the section
      // to a new slot — in BOTH layouts since 2026-08-24 (see wireColDrag). These live on the
      // build-once header, so they are click-safe across the feed's constant re-renders.
      const fold = el("button", "fcol-fold");
      fold.setAttribute("aria-label", "Collapse " + label);
      fold.addEventListener("click", (ev) => {
        ev.stopPropagation();
        if (collapsedCols.has(foldKey(key))) collapsedCols.delete(foldKey(key)); else collapsedCols.add(foldKey(key));
        applyColStack();
        persistViewState();
      });
      const name = el("span", "feed-col-name fcol-chip fcol-chip-" + chip); name.textContent = label;
      if (board === FEED_BOARD) { name.title = "drag to reorder"; wireColDrag(name, col, key); }   // the chip ITSELF drags (the user 2026-08-16), the grab
      else name.classList.add("fcol-static");   // a data board's columns keep their definition's order: no drag, no grab cursor, no title (a no-op affordance lies; per-board order is phase five's)
      //                                         cursor it wears in the stacked layout is the affordance
      const count = el("span", "feed-col-count"); count.id = "col-" + key + "-count";
      head.append(name, fold, count);         // caret RIGHT of the chip — the same side as the
      //                                          session headers' fold (the user 2026-07-31 / 2026-08-16)
      const body = el("div", "feed-col-list"); body.id = "col-" + key + "-list";
      col.append(head, body);
      cols.appendChild(col);
    }
    list.appendChild(cols);
    applyColStack();
  }
  const lists: Record<Column, HTMLElement> = {}, counts: Record<Column, HTMLElement> = {};
  for (const key of activeCols()) { lists[key] = document.getElementById("col-" + key + "-list")!; counts[key] = document.getElementById("col-" + key + "-count")!; }
  return { lists, counts };
}

// Keyed in-place reconcile of ONE column (mixes ask + standalone cards; a card
// whose column changed is MOVED, not rebuilt — no hover flicker). Records each key
// in `globalDesired` for the cross-column cache cleanup the caller runs after.
// A grouped session header leaves as ONE MOTION with its run's last card (the user 2026-08-24,
// whose recording showed the header popping out a frame after the card finished fading): the exit
// wears the card-dismiss family (fade + slight shrink + height collapse) instead of vanishing at
// the next render. The element is UN-KEYED first — dropped from sessHeadEls and re-keyed to a
// tombstone — so a reappearing run mints a FRESH header while the ghost finishes; DOM removal keys
// on animationend (the event), with a backstop timeout so a lost event can never trap the ghost,
// and reduced motion removes at once (no animation ever plays there).
let sessGhostSeq = 0;
function startSessHeadExit(key: string, head: HTMLElement): void {
  if (sessHeadEls.get(key) === head) sessHeadEls.delete(key);
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    head.remove();
    return;
  }
  head.dataset.key = "x:" + (++sessGhostSeq);   // keyed-but-never-desired: survives the unkeyed-child sweep
  head.classList.add("sess-exit");
  const done = () => head.remove();
  head.addEventListener("animationend", done, { once: true });
  window.setTimeout(done, 600);                 // backstop — a lost event can never trap the ghost
}
// The CONJUNCTION half: when a dismissing card is its run's LAST, the header starts its exit at the
// same moment (the same click), not at the post-dismiss render. Grouped mode only; a run with other
// live cards keeps its header rock-steady. The walk reads the CURRENT DOM: back to the run's own
// header, then across the run for any member that is neither the leaving card nor already dismissing.
function dressHeaderIfLast(card: HTMLElement, sid: string): void {
  if (!feedPrefs().grouped) return;
  let head: HTMLElement | null = null;
  for (let p = card.previousElementSibling as HTMLElement | null; p; p = p.previousElementSibling as HTMLElement | null) {
    if (p.classList.contains("feed-sess-head")) { head = p; break; }
  }
  if (!head || head.getAttribute("data-fsid") !== sid || head.classList.contains("sess-exit")) return;
  for (let n = head.nextElementSibling as HTMLElement | null; n && !n.classList.contains("feed-sess-head"); n = n.nextElementSibling as HTMLElement | null) {
    if (n !== card && n.classList.contains("fitem") && !n.classList.contains("dismissing")) return;   // the run lives on
  }
  const key = head.dataset.key || "";
  startSessHeadExit(key, head);
}

// What a Clear may take: not a PLACEHOLDER (provisional / awaiting / blocked stand-ins carry no goal to
// curate: the kernel keeps listing them, so a clear would only suppress them on this page until reload).
// The card-level Clear hides itself for those; the session Clear must not reach around that (the review of
// the session Clear, 2026-09-08). A held message's card is a notice card since 2026-09-19: Clear dismisses
// it as any card's, and the held file stays the bus's to decide.
function clearable(it: AskItem): boolean {
  return !it.provisional;   // (a held message's card is a notice card since 2026-09-19: Clear dismisses it as any card, the held file stays)
}
// Every CLEARABLE card a session has in the CURRENT view (the same filters render reads: scope, lens,
// `#only=`), across every column, folded-under-the-header ones included — the set the header's Clear removes.
function sessionCards(sid: string): AskItem[] {
  return viewFiltered(asks).filter((a) => a.sid === sid && clearable(a));
}
// The session header's Clear (the user 2026-09-08): one click, every card of that session in the current
// view, as ONE motion and ONE Undo batch. The same optimistic path the ask-group clear takes, applied to
// every card and turn-group of the session in every column: flush each card's cross-surface hover
// highlight, mark it .dismissing, start every column's header for this session on its exit at the same
// moment (the one-motion rule), cache the whole batch on clearedStack so Undo restores the session in one
// click, suppress the ids from incoming pushes (pendingCleared) and post ONE askClearMany — one kernel
// batch, one cleared.jsonl stamp, so the kernel's UndoClear restores the whole gesture the way the client's
// does (N single posts stamped N batches, and Undo brought back only the last-posted card while the
// client restored all N: phantom cards). Finalize after the 180ms exit only what is STILL ours and still
// dismissing — a render inside the window that revived a card (re-render resets its class) or replaced
// its element must not be yanked by a stale timeout — and drop from the model only ids still pending
// (an Undo inside the window deleted its ids from pendingCleared; a kernel-confirmed clear already left).
function clearSessionCards(sid: string): void {
  const members = sessionCards(sid);
  if (!members.length) return;
  const ids = members.map((m) => m.itemId);
  const turns = new Set(members.map((m) => m.turnId).filter(Boolean));
  const leaving: [HTMLElement, () => boolean, () => void][] = [];
  for (const m of members) {
    const c = askEls.get(m.itemId);
    if (c) leaving.push([c, () => askEls.get(m.itemId) === c, () => { askEls.delete(m.itemId); unregisterSectionHost(m.itemId, c); }]);
    const f = fsAskEls.get(m.itemId);   // the focused section's copy leaves with its card (T347)
    if (f) leaving.push([f, () => fsAskEls.get(m.itemId) === f, () => { fsAskEls.delete(m.itemId); unregisterSectionHost(m.itemId, f); }]);
  }
  for (const [tid, g] of Array.from(groupEls)) {
    if (turns.has(tid) && ((g as any)._g as AskGroup | undefined)?.sid === sid) leaving.push([g, () => groupEls.get(tid) === g, () => groupEls.delete(tid)]);
  }
  for (const [tid, g] of Array.from(fsGroupEls)) {
    if (turns.has(tid) && ((g as any)._g as AskGroup | undefined)?.sid === sid) leaving.push([g, () => fsGroupEls.get(tid) === g, () => fsGroupEls.delete(tid)]);
  }
  for (const [c] of leaving) { c.dispatchEvent(new MouseEvent("mouseleave")); c.classList.add("dismissing"); }
  // The header row holds the hover-freeze gate too, and its Clear all sits on the row: the pointer that clicked it
  // is resting on the row by construction. The ghost is pointer-inert (and reduced motion removes the row outright),
  // so no mouseleave of its own ever fires; dispatch the synthetic one, as the card loop above does, so the release
  // comes from the click and the kernel's confirmation of the clear applies at once instead of queueing behind
  // the hold. freezeLeave ignores a key it does not hold, so the session's headers in the other columns are safe.
  for (const [key, head] of Array.from(sessHeadEls)) if (head.getAttribute("data-fsid") === sid) { head.dispatchEvent(new MouseEvent("mouseleave")); startSessHeadExit(key, head); }
  pushClearedEntry(members.slice());   // one batch: one Undo brings the whole session back
  for (const m of members) pendingCleared.add(m.itemId);
  vscodeApi?.postMessage({ type: "askClearMany", itemIds: ids, sid });   // ONE kernel batch (see above)
  setTimeout(() => {
    for (const [c, stillOurs, forget] of leaving) if (stillOurs() && c.classList.contains("dismissing")) { c.remove(); forget(); }
    dropDismissed(ids.filter((id) => pendingCleared.has(id)));
  }, 180);
}

function reconcileCol(listEl: HTMLElement, entries: Entry[], globalDesired: Set<string>, gate: GateEnv) {
  const existing = new Map<string, HTMLElement>();
  for (const c of Array.from(listEl.children) as HTMLElement[]) {
    const k = c.dataset.key;
    if (k) existing.set(k, c); else c.remove();
  }
  const ordered: HTMLElement[] = [];
  const colDesired = new Set<string>();
  for (const e of entries) {
    let key: string, card: HTMLElement;
    if (e.kind === "ask") {
      key = "a:" + e.ask.itemId;
      card = askEls.get(e.ask.itemId) || makeAskCard(e.ask);
      askEls.set(e.ask.itemId, card);
      registerSectionHost(e.ask.itemId, card);   // the item's twin set for its sections (card-sections.ts): a press here reaches every host
      // THE UPDATE GATE (feed-card-gate.ts): repaint only a card the kernel re-sent (a new object — the pane
      // shim's delta reassembly and federation's merge keep an unchanged card's object by reference) or whose
      // board-level inputs changed (the key). Everything below — placement, the insertBefore order walk, the
      // cross-column removal — stays unconditional, so a card whose column or sort changed still moves. The
      // key is stored only after updateAskCard returns: a throw mid-update leaves the card marked for another
      // try, not recorded as painted.
      const ik = cardInputsKey(e.ask, gate);
      if (cardNeedsUpdate(card as any, e.ask, ik)) { updateAskCard(card, e.ask); (card as any)._ik = ik; }
      rearmNoticeButtons(card as any);   // outside the gate: an identical push (the same card object) still lets a latched action go (T370)
    } else if (e.kind === "sess") {
      // grouped-mode session header — keyed per (column, sid): one session can head a run in EVERY column
      key = "s:" + listEl.id + ":" + e.sid;
      card = sessHeadEls.get(key) || makeSessHead();
      card.dataset.key = key;
      sessHeadEls.set(key, card);
      updateSessHead(card, e);
    } else {
      key = "g:" + e.group.turnId;
      card = groupEls.get(e.group.turnId) || makeGroupCard(e.group);
      groupEls.set(e.group.turnId, card);
      updateGroupCard(card, e.group);
    }
    globalDesired.add(key); colDesired.add(key);
    ordered.push(card);
  }
  for (const [k, c] of existing) {
    if (colDesired.has(k)) continue;
    if (c.classList.contains("sess-exit")) continue;             // a ghost mid-exit — its end event removes it
    if (k.startsWith("s:")) startSessHeadExit(k, c);             // headers leave as one motion (2026-08-24)
    else c.remove();
  }
  let cur: ChildNode | null = listEl.firstChild;
  for (const node of ordered) {
    if (cur === node) { cur = cur.nextSibling; continue; }
    listEl.insertBefore(node, cur);
  }
  // an empty column shows NOTHING (the user 2026-06-25) — no "—" placeholder. (Any stray non-keyed child,
  // including an old placeholder, is already removed at the top of this reconcile.)
}

// ── THE FOCUSED SESSION SECTION (T347, the user 2026-09-11, who wanted the focused session's cards on top) ──
// When a tab has focus in the chat pane, the feed puts that session's cards ABOVE the board: the session's
// name as the head, the board's three columns (Working / Needs you / Completed, the same chips), a horizontal
// rule under it. The board below stays exactly as it is, so those cards appear twice. A VIEW, not a move:
// the section has its own elements and caches (fsAskEls / fsGroupEls, keys "f:a:…" / "f:g:…"), and
// nothing below is touched by it — the FLIP capture reads #feed-cols, the modal's and the keyboard scope's
// lookups match the bare keys, applyFocus lights both copies. EVENT-based: it rebuilds inside render(),
// which the kernel's activeChat frame (a tab switch) and the feed's own frames drive; no timer anywhere.
// Built once and synced in place: the head's name link and the column heads are stable nodes
// (click-safety), only the card lists reconcile — with the same builders and the same update gate the
// board uses, so a copy repaints exactly when the card below would.
function ensureFocusSection(list: HTMLElement): HTMLElement {
  let sec = document.getElementById("feed-focus");
  if (!sec) {
    sec = el("section", "");
    sec.id = "feed-focus";
    sec.setAttribute("aria-label", "the chat's focused session");
    // the LABEL (T410b, the user 2026-09-14): "Current session: <name>", the section's own fold control. The label
    // text is a button carrying the accessible name and aria-expanded; the NAME keeps the session headers' click
    // (open, or offer to revive) and its hover title; a click anywhere else on the row folds the whole section to
    // this row (the blocks, their cards and the quiet line hidden, the divider standing) and back. The caret is the
    // block carets' vocabulary (▾ open, ▸ folded) and sits at the END of the label line (the user's word); folded,
    // the focused session's card count follows the name in the column count's dress, before the caret (paintFocusFold).
    const head = el("div", "feed-focus-head");
    const fold = el("button", "feed-focus-fold") as HTMLButtonElement; fold.type = "button"; fold.textContent = "Current session:";
    fold.setAttribute("aria-expanded", "true"); fold.setAttribute("aria-controls", "feed-focus-cols");
    const nm = el("a", "fname"); nm.title = "open this session";
    const caret = el("span", "feed-focus-caret"); caret.textContent = "▾"; caret.setAttribute("aria-hidden", "true");
    const ncount = el("span", "feed-col-count feed-focus-count");
    head.append(fold, nm, ncount, caret);
    head.addEventListener("click", (ev) => {
      if ((ev.target as HTMLElement).closest(".fname")) return;   // the name's own click (it stops propagation too)
      focusFolded = !focusFolded;
      paintFocusFold();
      persistViewState();
    });
    const empty = el("div", "feed-focus-empty");
    const cols = el("div", "feed-cols feed-focus-cols"); cols.id = "feed-focus-cols";   // what the label's aria-controls names
    const lists: Partial<Record<Column, HTMLElement>> = {}, counts: Partial<Record<Column, HTMLElement>> = {};
    // the board's own column chips and labels (ensureCols), with the section's OWN furniture (T410): the CHIP drags
    // the block within the section exactly as the board's chips drag its columns (the user 2026-09-14, who wanted no
    // grip: the heads above and below the divider read the same), and, focused, its arrow keys move the block a slot;
    // a fold caret folds the block to its head in BOTH layouts; a gutter on the block's right edge resizes it
    // against its neighbour. Order, widths and folds are the section's own state (applyFocusLayout), never the
    // board's; a block never crosses the divider. Build-once nodes, click-safe across renders.
    for (const [key, label, chip] of columnTable(activeBoard())) {   // the board's categories, in its order (board-def.ts)
      const col = el("div", "feed-col col-" + key);
      const h = el("div", "feed-col-head");
      // the chip: the drag handle (the board's own affordance, the grab cursor) and the keyboard's handle too, so it
      // takes focus and its title promises the keys (wireBlockKeys)
      const name = el("span", "feed-col-name fcol-chip fcol-chip-" + chip); name.textContent = label;
      name.tabIndex = 0; name.title = "Drag to reorder, or press the arrow keys"; name.setAttribute("aria-keyshortcuts", "ArrowLeft ArrowRight");
      const fold = el("button", "fcol-fold"); fold.dataset.label = label;
      fold.setAttribute("aria-label", "Collapse " + label);
      fold.addEventListener("click", (ev) => {
        ev.stopPropagation();
        if (collapsedFocusCols.has(key)) collapsedFocusCols.delete(key); else collapsedFocusCols.add(key);
        applyFocusLayout();
        persistViewState();
      });
      const count = el("span", "feed-col-count");
      h.append(name, fold, count);
      wireColDrag(name, col, key, FOCUS_SLOTS);   // the chip drags, within the section only
      wireBlockKeys(name, key);                   // …and, focused, the arrow keys move the block a slot
      const body = el("div", "feed-col-list");
      const gutter = el("div", "focus-gutter"); gutter.title = "drag to resize";
      wireFocusGutter(gutter, key);
      col.append(h, body, gutter);
      cols.appendChild(col);
      lists[key] = body; counts[key] = count;
    }
    // the rule is the section's SIBLING, placed right after it below (the user 2026-09-19: the divider under the tinted
    // box, not inside it, so the box's rounded bottom edge closes above the rule); it leaves with the section
    const rule = el("hr", "feed-focus-divider");
    sec.append(head, empty, cols);
    (sec as any)._rule = rule;
    (sec as any)._head = head; (sec as any)._name = nm; (sec as any)._empty = empty; (sec as any)._cols = cols;
    (sec as any)._fold = fold; (sec as any)._caret = caret; (sec as any)._count = ncount;
    (sec as any)._lists = lists; (sec as any)._counts = counts;
  }
  // directly above the board, every render: the section, then its rule, right before #feed-cols (the host loading
  // strip, which announces what is coming, keeps the very top while it shows). A fresh section takes the board's
  // column order at once.
  const board = document.getElementById("feed-cols"), rule = (sec as any)._rule as HTMLElement;
  if (board && (sec.nextSibling !== rule || rule.nextSibling !== board)) { list.insertBefore(sec, board); list.insertBefore(rule, board); applyColStack(); }
  return sec;
}
/** How the section names the focused session: this pane's session list (the chat's tab set, relayed per
 *  frame), else a card of that session, else the kernel's 8-character stub — the same resolution the file
 *  viewer's identity uses (setFileViewIdentity). Liveness is a card's word when there is one; a tab with no
 *  cards is taken as live (the chat is showing it). */
function focusedIdentity(sid: string): { name: string; color: { bg: string; fg: string } | null; live: boolean } {
  const s = sessionsMeta.find((x) => x.sid === sid);
  const a = asks.find((x) => x.sid === sid);
  if (s) return { name: s.name, color: s.color ?? a?.color ?? null, live: a ? !!a.live : true };
  if (a) return { name: a.name, color: a.color ?? null, live: !!a.live };
  return { name: hostStub(sid)?.name || sid.slice(0, 8), color: null, live: true };
}
function renderFocusSection(list: HTMLElement, buckets: Record<Column, Entry[]>, gate: GateEnv): void {
  const sec = ensureFocusSection(list) as any;
  const head = sec._head as HTMLElement, nm = sec._name as HTMLElement, empty = sec._empty as HTMLElement;
  const lists = sec._lists as Record<Column, HTMLElement>, counts = sec._counts as Record<Column, HTMLElement>;
  const total = focusedCardCount(buckets, entryCards);
  const sid = focusedSid;
  if (sid) {
    const who = focusedIdentity(sid);
    // the name nodes are minted only when what they show changes (the session headers' rule): a Text-node
    // replacement per render is the churn the card gate exists to avoid
    const sig = who.name + "\u0000" + sid + "\u0000" + (hostIsDown(sid) ? "d" : "");
    if (sec._nmSig !== sig) {
      sec._nmSig = sig; nm.replaceChildren(...hostNameNodes(who.name, sid));
      (sec._fold as HTMLElement).setAttribute("aria-label", "Current session: " + who.name);   // the label's accessible name (T410b)
    }
    nm.style.color = who.color ? who.color.bg : "";
    nm.classList.toggle("dead", !who.live);
    nm.onclick = (ev) => { ev.stopPropagation(); openOrReviveSession(sid, who.live, who.name); };   // the session headers' click: open, or offer to revive
    setWorkDot(nm, dotFor(who.name));   // the same working / awaiting dot the session headers wear
  } else {
    setText(empty, "No session is focused in the chat");
  }
  // the two quiet states: no tab focused → the line stands in for the head; a focused session with no cards →
  // the head stays and the line says so. The rule stays in both, so the section still reads as a section. The
  // fold (T410b) hides the blocks and the line under the label: paintFocusFold owns those two displays.
  head.style.display = sid ? "" : "none";
  sec._total = total;
  paintFocusFold();
  const desired = new Set<string>();
  for (const k of Object.keys(buckets) as Column[]) {
    reconcileFocusCol(lists[k], buckets[k], gate, desired);
    const n = buckets[k].reduce((acc, e) => acc + entryCards(e), 0);   // the board's counting rule: CARDS, and a number only when there are some
    setText(counts[k], n ? String(n) : "");
    counts[k].style.display = n ? "" : "none";
    // a block with no cards (T410, the user 2026-09-14): single column, it hides whole, head and all, until a card
    // arrives (the CSS under the stacked query); side by side its head stands as the board's do
    lists[k].parentElement?.classList.toggle("col-empty", n === 0);
  }
  // a copy whose card left the focused session's view — cleared, folded into another turn, or the focus
  // moved on — goes now; the board's copy below has its own cache and its own exit
  for (const id of Array.from(fsAskEls.keys())) if (!desired.has("f:a:" + id)) { const f = fsAskEls.get(id); f?.remove(); if (f) unregisterSectionHost(id, f); fsAskEls.delete(id); }
  for (const tid of Array.from(fsGroupEls.keys())) if (!desired.has("f:g:" + tid)) { fsGroupEls.get(tid)?.remove(); fsGroupEls.delete(tid); }
}
// reconcileCol's twin for ONE of the section's columns: the same keyed in-place reconcile (a card whose
// column changed is MOVED, not rebuilt), over the section's own caches, under the section's own keys —
// "f:a:<itemId>" / "f:g:<turnId>" in data-key, so the board's FLIP capture, the reveal jump and the modal's
// lookups (all by the bare key) never take a copy for the card. Entries never include a run header
// (focusedEntries drops them); one that did would be skipped, not built.
function reconcileFocusCol(listEl: HTMLElement, entries: Entry[], gate: GateEnv, desired: Set<string>): void {
  const existing = new Map<string, HTMLElement>();
  for (const c of Array.from(listEl.children) as HTMLElement[]) {
    const k = c.dataset.key;
    if (k) existing.set(k, c); else c.remove();
  }
  const ordered: HTMLElement[] = [];
  const colDesired = new Set<string>();
  for (const e of entries) {
    let key: string, card: HTMLElement;
    if (e.kind === "ask") {
      key = "f:a:" + e.ask.itemId;
      card = fsAskEls.get(e.ask.itemId) || makeAskCard(e.ask);
      card.dataset.key = key;   // the builder stamps the bare key; the copy wears the section's
      fsAskEls.set(e.ask.itemId, card);
      registerSectionHost(e.ask.itemId, card);   // the focused section's copy is a twin too
      // THE UPDATE GATE (feed-card-gate.ts), as the board applies it: repaint a copy only when the kernel
      // re-sent the card or a board-level input it reads changed
      const ik = cardInputsKey(e.ask, gate);
      if (cardNeedsUpdate(card as any, e.ask, ik)) { updateAskCard(card, e.ask); (card as any)._ik = ik; }
      rearmNoticeButtons(card as any);   // outside the gate: an identical push (the same card object) still lets a latched action go (T370)
    } else if (e.kind === "group") {
      key = "f:g:" + e.group.turnId;
      card = fsGroupEls.get(e.group.turnId) || makeGroupCard(e.group);
      card.dataset.key = key;
      fsGroupEls.set(e.group.turnId, card);
      updateGroupCard(card, e.group);
    } else continue;
    desired.add(key); colDesired.add(key);
    ordered.push(card);
  }
  for (const [k, c] of existing) if (!colDesired.has(k)) c.remove();
  let cur: ChildNode | null = listEl.firstChild;
  for (const node of ordered) {
    if (cur === node) { cur = cur.nextSibling; continue; }
    listEl.insertBefore(node, cur);
  }
}
// The section's FOLD (T410b): folded, the label row stands alone — the blocks (and their cards) and the quiet line
// hidden, the divider standing — with the focused session's card count after the name; the caret reads the state
// and the label button says it to assistive tech. Only while a session is focused (no focus: the quiet line, as
// ever). Idempotent; runs per render (the count follows the cards) and per click on the label.
function paintFocusFold(): void {
  const sec = document.getElementById("feed-focus") as any;
  if (!sec) return;
  const total: number = sec._total || 0;
  const folded = !!focusedSid && focusFolded;
  sec.classList.toggle("folded", folded);
  // the quiet line is the NO-FOCUS state alone (the user 2026-09-14: a focused session with no cards shows its label
  // and its blocks, nothing said under a head); folded, the blocks go under the label
  (sec._empty as HTMLElement).style.display = focusedSid ? "none" : "";
  (sec._cols as HTMLElement).style.display = focusedSid && !folded ? "" : "none";
  (sec._caret as HTMLElement).textContent = folded ? "▸" : "▾";
  (sec._fold as HTMLElement).setAttribute("aria-expanded", String(!folded));
  const count = sec._count as HTMLElement;
  setText(count, folded && total ? String(total) : "");   // the board's rule: a number only when there are cards
  count.style.display = folded && total ? "" : "none";
}
function removeFocusSection(): void {
  const sec = document.getElementById("feed-focus") as any;
  if (sec) { (sec._rule as HTMLElement | undefined)?.remove(); sec.remove(); }   // the rule is the section's sibling
  for (const [id, f] of Array.from(fsAskEls)) unregisterSectionHost(id, f);   // the copies leave the registry with the section
  fsAskEls.clear(); fsGroupEls.clear();
}

// ── FLIP: animate a card FLYING to its new column when its status changes (the user 2026-06-27) ──
// Cards are reused DOM nodes that reconcileCol MOVES between columns, so a status change relocates the same
// element — perfect for FLIP (First-Last-Invert-Play): record each card's screen rect + column BEFORE the
// move, then after it, offset the card back to where it was and transition that offset to zero so it glides to
// its new home. The flying card sits in the BACK layer (position:relative; z-index:-1 → behind sibling cards
// but above the column background) so it never flies OVER other content. Respects prefers-reduced-motion.
type FlipState = { rect: DOMRect; col: string };
// column id per card key as of the LAST render — the flip gate compares the next render against it
let prevCols: Map<string, string> = new Map();
// the card keys of a render's buckets, mapped to the column each lands in (the same keys reconcileCol mints)
function columnsOf(buckets: Record<Column, Entry[]>): Map<string, string> {
  const m = new Map<string, string>();
  for (const col of Object.keys(buckets) as Column[]) {
    buckets[col].forEach((e, i) => {
      const key = e.kind === "ask" ? "a:" + e.ask.itemId : e.kind === "group" ? "g:" + e.group.turnId : "s:" + col + ":" + e.sid;
      m.set(key, col + ":" + i);   // column AND position: a card that moved within its column glides too (the user 2026-06-29)
    });
  }
  return m;
}
// the fly walks the ACTIVE board's columns (activeCols); the constant that named the feed's three went with phase four
let flySeq = 0;   // the fly token: the element remembers the newest fly's number (see the write phase)
function captureCardRects(cols: ReturnType<typeof ensureCols>): Map<string, FlipState> {
  const m = new Map<string, FlipState>();
  for (const key of activeCols()) {
    const colEl = cols.lists[key];
    for (const c of Array.from(colEl.children) as HTMLElement[]) {
      if (c.dataset.key) m.set(c.dataset.key, { rect: c.getBoundingClientRect(), col: colEl.id });
    }
  }
  return m;
}
function flyColumnChanges(first: Map<string, FlipState>, cols: ReturnType<typeof ensureCols>): void {
  if (!first.size) return;
  try { if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return; } catch { /* no matchMedia */ }
  // READ every card's new position first, then WRITE: a transform written between two rect reads dirties
  // layout, so the next read forces a fresh layout of the whole document — one per card, 155 times per
  // feed frame (measured 2026-09-04: the largest single cost on the main thread the chat pane's clicks share).
  const moves: { c: HTMLElement; dx: number; dy: number; crossed: boolean }[] = [];
  for (const key of activeCols()) {
    const colEl = cols.lists[key];
    for (const c of Array.from(colEl.children) as HTMLElement[]) {
      const k = c.dataset.key; if (!k) continue;
      const prev = first.get(k);
      if (!prev) continue;                                 // brand-new card → no FLIP (nothing to glide from)
      // a card nobody could see — its column folded to the header (display:none) — has a zero First rect:
      // nothing to glide from, and a fly from (0,0) zooms in from the pane's corner
      if (!prev.rect.width && !prev.rect.height) continue;
      const now = c.getBoundingClientRect();
      // …and a target nobody can see has a zero Last rect and no transition to run, so a fly written to it
      // would never end: the class it wears, pointer-events:none, stayed until the card's next repaint, and
      // the per-card update gate no longer rewrites className every render. Nothing to glide to; leave it.
      if (!now.width && !now.height) continue;
      const dx = prev.rect.left - now.left, dy = prev.rect.top - now.top;
      if (!dx && !dy) continue;                            // didn't move → leave it alone
      moves.push({ c, dx, dy, crossed: prev.col !== colEl.id });
    }
  }
  for (const { c, dx, dy, crossed } of moves) {
    // Two flavors of move, ONE FLIP (the user 2026-06-29): a card that CHANGED COLUMN flies in the BACK
    // layer (z-index:-1 → behind the other cards, so it never sails over them); a card that STAYED in its
    // column but shifted — because the card that left it vacated a slot — glides IN PLACE in normal flow, so
    // the remaining cards reflow smoothly to their new spots instead of snapping there in a discrete jump.
    // ONE fly owns an element at a time: a second render can fly the same card while the first fly's 420 ms
    // transition still runs — two deltas within half a second on an active board. The second Invert cancels
    // the first transition, and the browser delivers that transitioncancel to EVERY listener on the element
    // before the second fly's Play frame. Two guards: a per-element token, so a superseded fly's
    // end/cancel/backstop removes its own listeners and touches nothing else; and `played`, so a fly ignores
    // transition events that arrive before its own Play wrote the transition — those belong to the fly it
    // cancelled. Without them the older fly's cancel handler wiped the newer Invert and the card snapped
    // where it should have glided (reproduced in Chromium).
    const mine = ++flySeq;
    (c as any)._flySeq = mine;
    if (crossed) c.classList.add("fitem-flying");
    // Invert: jump the card back to its old spot, instantly.
    c.style.transition = "none";
    c.style.transform = `translate(${dx}px, ${dy}px)`;
    // the fly ends on its own event — end OR cancel (a card re-inserted or hidden mid-flight gets
    // transitioncancel, never transitionend) — with a backstop so a lost event can never leave the card in
    // the back layer, pointer-events off (absorbIntoParent's idiom). Idempotent: whichever fires first.
    let flown = false, played = false;
    const done = (ev?: TransitionEvent) => {
      if (flown) return;
      if (ev && (ev.propertyName !== "transform" || !played)) return;   // not this fly's transition
      flown = true;
      c.removeEventListener("transitionend", done);
      c.removeEventListener("transitioncancel", done);
      if ((c as any)._flySeq !== mine) return;             // superseded: the newer fly owns the element's styles
      c.classList.remove("fitem-flying");                  // whichever fly added it — the element is settled now
      c.style.transition = ""; c.style.transform = "";     // back to normal flow + stacking
    };
    c.addEventListener("transitionend", done);
    c.addEventListener("transitioncancel", done);
    window.setTimeout(done, 650);
    // Play: next frame, release the offset with a transition → it glides to its new home. Unless the fly
    // already ended or was superseded (a hidden tab pauses animation frames while the backstop's timer
    // still runs): a release after that would leave an inline identity transform on a settled card.
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (flown || (c as any)._flySeq !== mine) return;
      played = true;
      c.style.transition = "transform .42s cubic-bezier(.22, .61, .36, 1)";
      c.style.transform = "translate(0, 0)";
    }));
  }
}

// ── Absorb: when a top-level ask card becomes a SUB-GOAL of another card, it shrinks + flies INTO the parent
// instead of just vanishing (the user 2026-06-29). Detected at reconcile time: a card that's leaving the board
// AND whose itemId now appears as a node inside some still-visible ask's tree. We detach the leaving node to a
// fixed overlay at its old spot, then transition it scaling down + translating to the parent card's center.
function absorbIntoParent(card: HTMLElement, fromRect: DOMRect, parent: HTMLElement): void {
  const to = parent.getBoundingClientRect();
  if (!to.width || !fromRect.width) { card.remove(); return; }   // parent off-screen → just drop it
  card.remove();                                                 // out of column flow first
  card.classList.add("fitem-absorbing");
  Object.assign(card.style, {
    position: "fixed", left: `${fromRect.left}px`, top: `${fromRect.top}px`,
    width: `${fromRect.width}px`, height: `${fromRect.height}px`, margin: "0",
  });
  document.body.appendChild(card);
  const dx = (to.left + to.width / 2) - (fromRect.left + fromRect.width / 2);
  const dy = (to.top + to.height / 2) - (fromRect.top + fromRect.height / 2);
  let gone = false;
  const done = () => { if (gone) return; gone = true; card.removeEventListener("transitionend", done); card.remove(); };
  requestAnimationFrame(() => requestAnimationFrame(() => {
    card.style.transition = "transform .4s cubic-bezier(.4, 0, .2, 1), opacity .4s ease";
    card.style.transformOrigin = "center center";
    card.style.transform = `translate(${dx}px, ${dy}px) scale(0.14)`;
    card.style.opacity = "0";
  }));
  card.addEventListener("transitionend", done);
  setTimeout(done, 650);                                         // backstop if transitionend never fires
}

// THE view: one screen, three columns merging open asks with standalone
// completions; cards move between columns as links arrive.
// A small transient notice at the bottom of the feed — used to surface an inconsistency (e.g. an optimistic
// follow-up move the kernel never confirmed), so a behavior change is visible rather than silent. Auto-dismisses.
let feedToastEl: HTMLElement | null = null;
let feedToastTimer: number | undefined;
function feedToast(text: string) {
  if (feedToastEl) feedToastEl.remove();
  const t = el("div", "feed-toast"); t.textContent = text; t.setAttribute("role", "status");
  document.body.appendChild(t); feedToastEl = t;
  requestAnimationFrame(() => t.classList.add("show"));
  clearTimeout(feedToastTimer);
  feedToastTimer = window.setTimeout(() => {
    t.classList.remove("show");
    window.setTimeout(() => { if (feedToastEl === t) feedToastEl = null; t.remove(); }, 300);
  }, 4200);
}

// ── usage-limit banner (the user 2026-08-18): a judge layer down on a USAGE LIMIT must say so ──
// loudly, never fail quietly into retries. The kernel ships the judge-limit latch on the feed
// payload (self-expiring at the window reset, cleared by the next successful call). Built ONCE and
// updated in place — the button must survive re-renders (the click-safety rule), and it
// acknowledges immediately, then the latch clearing hides the banner on a later payload.
type JlIdent = { name: string; host?: string; sid?: string; color?: { bg: string; fg: string } | null };
let judgeLimit: { bucket?: string; resets_at?: number; model?: string;
                  loginSessions?: JlIdent[]; billingUnknown?: JlIdent[] } | null = null;
// The dismiss latches to THIS episode's identity — a NEW episode (different bucket or reset time)
// is new information and re-shows the banner; nothing else does (event-based, no timers). Stored
// in localStorage so the dismissal survives re-renders and reloads for the episode's lifetime.
const jlEpisodeKey = (j: { bucket?: string; resets_at?: number } | null) =>
  (j?.bucket || "") + ":" + (j?.resets_at || 0);
let jlSessOpen = false;   // the session list's keyed expand — module state, survives re-renders
function ensureJudgeLimit(): HTMLElement {
  let b = document.getElementById("judge-limit-banner");
  if (b) return b;
  b = el("div", "judge-limit-banner");
  b.id = "judge-limit-banner";
  const txt = el("span", "jl-text"); b.appendChild(txt);
  const btn = el("button", "jl-switch") as HTMLButtonElement;
  btn.type = "button";
  btn.textContent = "Run analysis on Opus until then";
  btn.title = "switch the analysis model to Opus (cheaper per token than Fable) while the Fable window is full";
  btn.onclick = () => {
    btn.disabled = true;
    btn.textContent = "Switching…";                      // acknowledge before the round-trip
    // gt: a settings gesture like any gear pick — stamped at the click, through the gesture clock, so
    // the kernel can order it (with the gear never opened in this document the clock has learned
    // nothing and this is the wall clock; a refusal then offers Apply anyway)
    vscodeApi?.postMessage({ type: "setJudgeModel", model: "opus", gt: gclock.stamp("judge-model") });
  };
  b.appendChild(btn);
  const sess = el("span", "jl-sess"); b.appendChild(sess);   // who the window actually touches (2026-08-28)
  const x = el("button", "jl-dismiss") as HTMLButtonElement;
  x.type = "button";
  x.textContent = "✕";
  x.title = "dismiss this notice — it returns only if a new limit episode starts";
  x.onclick = () => {
    // the hide IS the acknowledgment, immediate and local; the latch key makes it stick (build-once
    // button — the listener survives every re-render, per the click-safety rule)
    try { localStorage.setItem("romp:jlDismiss", jlEpisodeKey(judgeLimit)); } catch { /* storage blocked */ }
    paintJudgeLimit();
  };
  b.appendChild(x);
  // the "+N more" toggle is REBUILT per paint, so its action rides the build-once banner root
  // (delegation to the stable ancestor — the same rule the tab strip follows)
  b.addEventListener("click", (ev) => {
    const t = ev.target as HTMLElement;
    if (t && t.dataset && t.dataset.act === "jl-more") { jlSessOpen = !jlSessOpen; paintJudgeLimit(); }
  });
  const list = document.getElementById("feed-list")!;
  list.parentElement!.insertBefore(b, list);
  return b;
}
function paintJudgeLimit(): void {
  const b = ensureJudgeLimit();
  if (!judgeLimit) { b.style.display = "none"; return; }
  let dismissed = "";
  try { dismissed = localStorage.getItem("romp:jlDismiss") || ""; } catch { /* storage blocked */ }
  if (dismissed === jlEpisodeKey(judgeLimit)) { b.style.display = "none"; return; }
  const ra = judgeLimit.resets_at;
  const when = typeof ra === "number" && ra > 0
    ? new Date(ra * 1000).toTimeString().slice(0, 5) : "";
  const fable = judgeLimit.bucket === "fable";
  const txt = b.querySelector(".jl-text")!;
  // the HONEST scope (the user 2026-08-28, correction round — the everything-is-paused framing was
  // wrong: a judge call bills the JUDGED session's account, so key-billed analysis keeps flowing):
  // the window is the login account's; only the sessions billing it pause.
  txt.textContent = fable
    ? "The account's Fable usage window is full" + (when ? " (resets " + when + ")." : ".")
    : "The account's usage window is full" + (when ? "; it resumes at " + when + "." : ".");
  // WHO it touches: the sessions billing this account lose BOTH their turns (rate-limited) and
  // their card analysis until the reset; everyone else's analysis continues on their own billing.
  // Names wear the standard session chip — bold, identity colour, quiet host: prefix (the user's
  // ask). Inline when few; a keyed "+N more" expand when many; unknown billing said, never omitted.
  const sessEl = b.querySelector(".jl-sess") as HTMLElement;
  sessEl.replaceChildren();
  const names = judgeLimit.loginSessions || [];
  const unk = judgeLimit.billingUnknown || [];
  const chip = (p: JlIdent) => {
    const c = el("b", "jl-chip");
    c.replaceChildren(...hostPartsNodes(p.host, p.name));
    if (p.color && p.color.bg) c.style.color = p.color.bg;
    return c;
  };
  const appendChips = (list: JlIdent[]) => list.forEach((p, i) => { if (i) sessEl.append(", "); sessEl.appendChild(chip(p)); });
  if (names.length) {
    const many = names.length > 3;
    const shown = many && !jlSessOpen ? names.slice(0, 2) : names;
    sessEl.append("Analysis and turns pause for the sessions billing it: ");
    appendChips(shown);
    if (many) {
      const more = el("span", "jl-more");
      more.dataset.act = "jl-more";
      more.textContent = jlSessOpen ? " · fewer" : " +" + (names.length - shown.length) + " more";
      more.title = jlSessOpen ? "collapse the list" : "show every affected session";
      sessEl.appendChild(more);
    }
    sessEl.append(". Other sessions' analysis continues on their own billing.");
  } else {
    sessEl.append("No live session bills this account — every session's analysis continues on its own billing.");
  }
  if (unk.length) {
    const u = el("span", "jl-unknown");
    u.textContent = " · billing unknown for ";
    sessEl.appendChild(u);
    appendChips(unk);
    const u2 = el("span", "jl-unknown");
    u2.textContent = " (their CLI doesn't report it)";
    sessEl.appendChild(u2);
  }
  const btn = b.querySelector(".jl-switch") as HTMLButtonElement;
  btn.style.display = fable ? "" : "none";
  if (!judgeLimit || !fable) { btn.disabled = false; btn.textContent = "Run analysis on Opus until then"; }
  b.style.display = "";
}

// The render's display-side view: the footer session filter (the user 2026-08-08 — display-side
// only, `asks` stays complete so flipping it needs no kernel round-trip) composed with the search
// query (the user 2026-08-23 — a card passes when its session's meta name matches OR its own
// per-card label does, so a just-died session's cards keep matching after the meta list drops it).
// Shared by render() and the hover-freeze badge painter, so the deferred-churn hint counts exactly
// what the user would see move.
function viewScope(list: AskItem[]): AskItem[] {
  // The board shows EVERY session's cards, whatever tag view the tabs/timeline hold (the user's
  // 2026-08-25 ruling, superseding the 2026-08-24 feed-follows-the-view coupling after living with
  // it): the feed is the attention/clearing surface — hidden-elsewhere work still lands and clears
  // here. Its ONLY narrowing is its own local scoping (this combobox exact filter + search) and
  // the feed-local TAG LENS (viewBase). A tracked
  // delegation's satellite lives under its delegator's PRIMARY card: the default board hides it,
  // and picking its session in the filter is the one-click path back.
  let shown = feedOnlySid ? list.filter((a) => a.sid === feedOnlySid) : list.filter((a) => !a.satellite);
  const sMatch = searchSids(feedSearchQ, sessionsMeta);
  if (sMatch) shown = shown.filter((a) => sMatch.has(a.sid) || searchMatches(feedSearchQ, (a as { name?: string }).name));
  return shown;
}

// The feed-local TAG LENS slot (the user 2026-08-25, T70; disclosure lineage: the 665 outside-view
// treatments, retired with the shared-view coupling, live again here under the user's OWN lens).
// Needs-you always passes — the same interrupt rule the satellite and internals lens wear: a
// view-hidden session that needs the human is this board's whole job.
function viewBase(list: AskItem[]): AskItem[] {
  const s = viewScope(list);
  if (lensAll(feedLens)) return s;   // default All = today's board, byte-identical
  const u = lensUnions(feedTagViews);
  return s.filter((a) => lensVisible(feedLens, u, a.sid) || isNeedsYou(boardOf(a), a.category ?? a.column));   // the card's OWN board's badge category passes every lens (the 1861 read: a data board's needs-you card was dropped while the badge counted it)
}

// The disclosure count: what the TAG LENS alone hides (breakthroughs already show; counting them
// would double-speak) — viewScope minus viewBase, by construction.
function outsideLensCount(list: AskItem[]): number {
  return lensAll(feedLens) ? 0 : viewScope(list).length - viewBase(list).length;
}

// The board's final display view. (The 2026-08-25 team-internals lens lived in this slot for a
// day and RETIRED the same day on the user's verdict: team-internal cards must not be CREATED —
// chain-rooted minting in the courier owns that now — rather than created-then-foldable. No
// display class, no footer toggle; the slot family stays so future lenses layer the same way.)
// INSIDE this helper on purpose — the hover-freeze churn badges count through it, so they see
// exactly what the board shows (a filter outside would paint +N for cards that never appear).
function viewFiltered(list: AskItem[]): AskItem[] {
  return viewBase(list);
}

// The per-host loading strip (the user 2026-08-25): while an attached host's cards are pending,
// one quiet line per host — the romp loader family scoped to a strip, never a board takeover; the
// cards already present stay fully live. Retires per host on the exact event of its first merged
// contribution (pendingHosts, federation.ts) or on the standing can't-trap backstop; the lines are
// non-interactive, so a per-render rebuild is click-safe by construction.
function ensureHostLoad(list: HTMLElement): void {
  let strip = document.getElementById("feed-hostload");
  if (!pendingHosts.length) { strip?.remove(); return; }   // the real events emptied the list — the only way off
  if (!strip) {
    strip = el("div", "");
    strip.id = "feed-hostload";
  }
  // FIRST child in either board state (the user 2026-08-30: the reconnect strip sits at the TOP of
  // the feed, above the first column chip — it announces what is COMING, so it leads). Re-inserted
  // only when displaced (a fresh empty-state paint replaces children); non-interactive, so the move
  // is click-safe by construction.
  if (list.firstChild !== strip) list.insertBefore(strip, list.firstChild);
  strip.replaceChildren(...pendingHosts.map((h) => {
    const line = el("div", "hostload-line");
    const swirl = el("span", "fask-awaiting-swirl");   // the shared reverse-spin glyph, LEFT of the text
    const txt = el("span", "");
    txt.textContent = pendingDead.includes(h)
      ? "can\u2019t reach " + h + " \u2014 its cards return when it reconnects"
      : hostloadLong.has(h)
        ? "still waiting on " + h + "\u2026"
        : "loading cards from " + h + "\u2026";
    line.append(swirl, txt);
    return line;
  }));
}

// ── HIDDEN-PAINT HOLD (the user 2026-09-07, whose dashboard froze on the return to its browser tab) ──
// Every payload is APPLIED the moment it arrives — applyFeedPayload's bookkeeping (mirrorBadges feeds the
// shell's bell, clearUndoBusy, pendingCleared/pendingRestored, reconcileFollowMove and the follow-move
// backstops it retires) never waits — but the PAINT is owed while nobody can see it, and settled once,
// synchronously, on the event that makes the pane visible again: the tab's visibilitychange, or the
// observer's callback for a display:none pane (each is blind to the other's case; paint-gate.ts). Before
// this, a hidden tab rendered every payload in full — the FLIP pass pinned two forced layouts and a
// double rAF per moved card onto the return frame — and the hidden-tab pile-up was the freeze. NOT the
// hover-freeze queue below: that holder withholds the payload itself, and a confirming payload held back
// lets the follow-move backstop revert a move the kernel had already confirmed.
// The same two measures are this pane's hidden word for the kernel's pane shim (paint-gate.ts publishPaneHidden):
// the shim's zero-viewport probe misses a pane hidden after a first show in Chromium, so the release path and the
// hidden arm of visibilitychange publish document.hidden OR the observer's last word as window.__rompPaneHidden,
// on the same events, and nothing until the observer has spoken.
let feedIntersecting: boolean | null = null;   // #feed-list on screen by the observer's last word; null until it speaks (the gate reads null as on screen; nothing is published for it)
let paintDirty = false;        // a render was withheld while the pane could not be seen
let skipFlipOnce = false;      // the release paint snaps: cards that moved while away have no old spot to glide from
let feedWatching = false;
function watchFeedVisibility(list: HTMLElement): void {
  if (typeof IntersectionObserver === "undefined") return;   // no observer → the tab's visibility alone gates
  new IntersectionObserver((entries) => {
    feedIntersecting = entries.some((e) => e.isIntersecting);
    releasePaint();
    live.catchUp();   // the 15 s age pass skipped while off screen (feed-age.ts liveRefresher); one pass, same measure
  }).observe(list);
}
// The owed paint, settled the moment both measures say the pane can be seen. Synchronous on purpose (no
// requestAnimationFrame hop): on a tab switch the compositor shows the cached frame until the page paints,
// so a paint inside the event handler is the earliest fresh frame.
function releasePaint(): void {
  publishPaneHidden(document.hidden, feedIntersecting);
  if (!paintReleased(paintDirty, document.hidden, feedIntersecting)) return;
  paintDirty = false;
  skipFlipOnce = true;
  render();
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) releasePaint(); });
document.addEventListener("visibilitychange", () => { if (document.hidden) publishPaneHidden(true, feedIntersecting); });   // the hidden arm releases nothing, so the release path never publishes it

function render() {
  const list = document.getElementById("feed-list")!;
  if (!feedWatching) { feedWatching = true; watchFeedVisibility(list); }
  if (paintHeld(document.hidden, feedIntersecting, list.childElementCount > 0)) { paintDirty = true; return; }
  pruneTip();   // drop the styled tip only if the render tore its hovered anchor out (tip.ts pruneTip)
  applyFollowMove(asks);   // keep optimistically-moved follow-up cards in Working until the kernel confirms (or reverts)
  inRender = true;   // the body is render time: a post it makes is never the reader's jump (noteOwnJump, T416 round two)
  try { renderBody(list); } finally { inRender = false; }   // a throw inside the body must not leave the mark set (round three)
}
function renderBody(list: HTMLElement) {
  paintJudgeLimit();   // the usage-limit banner above the columns (build-once; hidden when unlatched)
  auditShownColumns(asks); // tripwire: what this render SHOWS is the record a bounce report needs
  const prevScroll = list.scrollTop;
  // footer pane (below the cards, no overlap): view menu · Session filter · Search | Clear all · Undo
  const showCA = !!asks.length;
  ensureViewMenuBtn().style.display = showCA ? "" : "none";       // sort + layout menu (the user 2026-08-24)
  ensureTagLensBtn().style.display = showCA ? "" : "none";        // the feed-local tag lens (the user 2026-08-25, T70)
  ensureSessionBox().style.display = showCA ? "" : "none";        // session combobox: type-or-pick filter (the user 2026-08-24)
  { const b = activeBoard(); const want = boardQuery || activeBoardId;   // the board shown, and a pick the frame cannot honour, said on the View button (phase four)
    ensureViewMenuBtn().title = "view options: sort direction, single column, group by session, the focused session on top"
      + (b !== FEED_BOARD ? "; showing the " + b.title + " board" : want && want !== FEED_BOARD.id ? "; board " + want + " is not on this frame, so the feed shows" : ""); }
  ensureClearAll().style.display = showCA ? "" : "none";
  ensureUndoClear().style.display = canUndoClear ? "" : "none";
  const foot = document.getElementById("feed-foot");
  // show the footer whenever there are cards (so the Sub-goals toggle is reachable) or an undo is available
  if (foot) foot.style.display = (showCA || canUndoClear) ? "" : "none";

  if (!asks.length) {   // the removed FeedItem subsystem left a stale second operand here (a read of the gone
    //                     `standalone` array) that threw a ReferenceError on an EMPTY feed → the inbox-zero
    //                     wordmark never rendered (the user 2026-07-08; payload-audit fallout). Goal cards are
    //                     the only feed unit now, so an empty asks list IS an empty feed.
    for (const [id, c] of Array.from(askEls)) unregisterSectionHost(id, c);   // an emptied board leaves nothing registered
    askEls.clear(); groupEls.clear();
    skipFlipOnce = false;   // this IS the release paint when the board emptied while away — the snap is spent
    removeFocusSection();   // an empty board is the wordmark alone; the section returns with the cards (T347)
    // inbox zero → the romp wordmark (a CSS background). role/aria-label + title keep the meaning for hover /
    // screen readers, since a background image carries no accessible text. Created ONCE (idempotent): on the
    // transition from cards→empty we mint it (its CSS fade-in plays once, the user 2026-06-25), and every
    // subsequent empty push leaves it in place so the logo doesn't re-fade on the 0.5s cadence.
    if (!list.querySelector(".feed-empty")) {
      list.innerHTML = "";
      const e = el("div", "feed-empty"); e.title = "All tasks complete";
      e.setAttribute("role", "img"); e.setAttribute("aria-label", "All tasks complete");
      list.appendChild(e);
    }
    ensureHostLoad(list);   // an attached host's cards may be the ONLY thing coming — say so here too
    return;
  }

  const cols = ensureCols(list);
  const board = activeBoard();
  const buckets: Record<Column, Entry[]> = {};
  for (const k of activeCols()) buckets[k] = [];
  // The display-side view filters (session filter + search), shared with the hover-freeze badge
  // painter so the deferred-churn hint counts exactly what the user would see move (viewFiltered).
  // The ACTIVE board's cards alone (phase four): a card names its board; one naming an id this renderer does not know
  // is the feed's, under the feed's default category with its producer line saying so (boardLabelOf).
  let shown = onActiveBoard(viewFiltered(asks));
  // Derive sibling GROUPS at render time, keyed by the shared typed turn (turnId) — turnGroups, the rule the
  // jump-unfold reads too, so what renders as a group and what unfolds as one can never disagree (T263e).
  const byTurn = turnGroups(shown);
  const grouped = new Set<string>();   // itemIds folded into a group → excluded from single ask cards
  for (const [tid, members] of byTurn) {
    members.forEach((m) => grouped.add(m.itemId));
    const g = buildGroup(tid, members);
    buckets[g.column].push({ kind: "group", t: g.t, group: g });
  }
  for (const a of shown) { if (grouped.has(a.itemId)) continue; buckets[askColumn(a)].push({ kind: "ask", t: a.t, ask: a }); }
  // Oldest-at-top by default (the user 2026-06-27): the newest work sits at the BOTTOM of each column, and
  // new/moved cards stack onto the bottom (matches the fly animation). The footer "Newest first" toggle
  // (default off, the user 2026-07-07) reverses each column to newest-at-top.
  // the feed: the user's direction preference; a data board: its definition's sort direction (its key is time until phase five's sub-sorts)
  const newestFirst = board === FEED_BOARD ? feedPrefs().newestFirst : board.sort.dir === "desc";
  for (const k of Object.keys(buckets) as Column[]) buckets[k].sort((x, y) => newestFirst ? y.t - x.t : x.t - y.t);
  // the board's owner rule (stable, so each run keeps the column's time order): the owner-less cards first in every mode, on a board whose order names it
  if (board.order.includes("ownerRank")) for (const k of Object.keys(buckets) as Column[]) buckets[k].sort((x, y) => ownerRank(entrySid(x)) - ownerRank(entrySid(y)));
  // THE FOCUSED SESSION's view of these buckets (T347), taken HERE, before grouping: the section shows one
  // session, so it carries no run headers, and a thread folded below must not empty it — the fold hides
  // cards behind a caret the section does not have, and a compact view never dead-ends (ui/CLAUDE.md).
  const focusBuckets = showFocused && board === FEED_BOARD ? focusedEntries(buckets, focusedSid, entrySid) : null;   // the focused section is the FEED's (the goal kind's road, plans/card-boards.md section 4); a board opting in is phase five's (the 1886 read, high: on a session-grouped data board the section read the feed's three keys and threw on every render)
  // GROUPED mode (the user 2026-07-13): within each column, cards gather by SESSION — session order = the
  // kernel's session-order list (the same order the chat tabs + timeline lanes hold; sessions the list
  // doesn't know keep their time order after it) — with a name+dot header entry opening each run. The sort
  // is stable, so per-session cards keep the column's newest/oldest order. Headers only where a run exists.
  if (feedPrefs().grouped && board.groupBy === "session") {   // grouping is the BOARD's to offer (phase four: the notes board groups nothing)
    const rank = new Map(sessionOrder.map((s, i) => [s, i] as const));
    const eSid = (e: Entry) => e.kind === "ask" ? e.ask.sid : e.kind === "group" ? e.group.sid : e.sid;
    for (const k of Object.keys(buckets) as Column[]) {
      const extra = new Map<string, number>();   // sids the order list doesn't know → after it, first-seen order
      for (const e of buckets[k]) { const s = eSid(e); if (!rank.has(s) && !extra.has(s)) extra.set(s, extra.size); }
      const rk = (e: Entry) => { const s = eSid(e); return isOwnerless(s) ? -1 : rank.has(s) ? rank.get(s)! : 1e9 + (extra.get(s) || 0); };   // the owner-less run heads the column (a remote host's too)
      buckets[k].sort((x, y) => rk(x) - rk(y));
      const withHeads: Entry[] = [];
      let cur: string | null = null;
      let head: (Entry & { kind: "sess" }) | null = null;
      for (const e of buckets[k]) {
        const s = eSid(e);
        if (s !== cur) {
          cur = s;
          const src: any = e.kind === "ask" ? e.ask : e.kind === "group" ? e.group : e;
          head = { kind: "sess", t: e.t, sid: s, col: k, name: src.name, color: src.color || null, live: !!src.live, folded: 0 };
          withHeads.push(head);
        }
        // A COLLAPSED thread contributes its header and nothing else — the run's cards are counted onto the
        // header instead of rendered, so the folded row still says how much is under it. CARDS, not rows
        // (entryCards): a turn-group folds as its member count, the same rule the section chip reads.
        if (collapsedThreads.has(threadKey(s, k))) { if (head) head.folded += entryCards(e); continue; }
        withHeads.push(e);
      }
      buckets[k] = withHeads;
    }
  }

  // FLIP-across-identity bookkeeping (the user 2026-06-29): map every goal itemId this render → the card KEY
  // that renders it, so the next render can slide a card whose IDENTITY changed (group↔solo, umbrella absorb)
  // from its predecessor's old spot. An ask/group "covers" its own id AND its tree node ids, so an umbrella
  // card covers the goals it just absorbed (their solo cards were the predecessors).
  const curItemKey = new Map<string, string>();
  const coverInto = (key: string, ids: string[]) => { for (const id of ids) if (!curItemKey.has(id)) curItemKey.set(id, key); };
  for (const k of Object.keys(buckets) as Column[]) for (const e of buckets[k]) {
    if (e.kind === "ask") coverInto("a:" + e.ask.itemId, [e.ask.itemId, ...(e.ask.tree || []).map((n) => n.id)]);
    else if (e.kind === "group") coverInto("g:" + e.group.turnId, e.group.members.flatMap((m) => [m.itemId, ...(m.tree || []).map((n) => n.id)]));
    // (the "item"/standalone bucket kind was removed with the FeedItem subsystem — no third branch)
  }

  // The per-card update gate's inputs, resolved ONCE for this render (feed-card-gate.ts cardInputsKey):
  // everything updateAskCard reads outside the ask object. A card is repainted when its object or this key
  // changed, so a frame's cost scales with the cards the kernel re-sent and the cards a changed input
  // reaches, not with the board.
  const gprefs = feedPrefs();
  const gate: GateEnv = {
    dot: dotFor, working: (n) => workingSet.has(n),
    focusId: hoverAskId ?? pinnedAskId, pinnedId: pinnedAskId, notifyOn: cardNotifyOn,
    prefs: { grouped: gprefs.grouped, collapsed: gprefs.collapsed, colormap: gprefs.colormap },
    hostDown: hostIsDown, selfHost: feedSelfHost, repo: prRepoOf,
    boardTitle: (it) => boardLabelOf(it),   // a card on a data-defined board: its label reads the title
  };
  // The focused session's section above the board (T347): its own elements and caches, the same builders and
  // the same update gate. Painted BEFORE the board's FLIP capture below: the section sits above the board, so
  // its height is part of where every board card rests, and a First rect read before the section settled would
  // have every card below glide by the section's change on top of its own move (a card moving column on a
  // frame that also changes the section's card count). The capture itself reads #feed-cols alone, so no copy
  // in the section is ever a First or a Last rect, and the board's reconcile after it is what it always was.
  if (focusBuckets) renderFocusSection(list, focusBuckets, gate); else removeFocusSection();

  // FLIP step 1 (the user 2026-06-27): record every visible card's position + column BEFORE the reconcile, so
  // a card that changes column can FLY from its old spot to the new one instead of teleporting. Only when
  // something CAN move: the capture and the fly each force a layout of the whole document, and most frames
  // change a card in place (text, tint, status chip) with every card staying where it was (2026-09-04).
  const nextCols = columnsOf(buckets);
  // The release paint after a hidden stretch SNAPS (skipFlipOnce, 2026-09-07): a card that moved while nobody
  // watched has no old spot in the user's eye to glide from — motion on return is motion without new
  // information (the 2026-07-29 rule) — and the two forced layouts plus a double rAF per moved card are what
  // the return frame cannot afford. prevCols still records the painted columns, so the NEXT move glides.
  const needFlip = !skipFlipOnce && flipNeeded(prevCols, nextCols);
  skipFlipOnce = false;
  prevCols = nextCols;
  const flipFirst = needFlip ? captureCardRects(cols) : new Map<string, FlipState>();

  const desired = new Set<string>();
  for (const k of activeCols()) reconcileCol(cols.lists[k], buckets[k], desired, gate);
  // the count chip shows the number only when there ARE cards; an empty column shows nothing — not "0"
  // (the user 2026-06-25). Empty string collapses the chip (it has no padding/background of its own).
  const setCount = (elc: HTMLElement, n: number) => { elc.textContent = n ? String(n) : ""; elc.style.display = n ? "" : "none"; };
  // Headers aren't cards — but a FOLDED header stands in for its run, so its cards count. The column chip
  // reports what is on the board, never what you happen to have open: folding a thread must not read as
  // work having left the column (the user 2026-07-31). ONE counting rule (the user 2026-08-26): a number
  // is always CARDS, never rows — a turn-group row is its members, a folded header is the cards it hides
  // (entryCards, which the fold accumulator uses too) — so a section's number cannot move on any fold or
  // grouping, only when cards actually enter or leave the column.
  const nCards = (es: Entry[]) => es.reduce((n, e) => n + entryCards(e), 0);
  for (const k of activeCols()) setCount(cols.counts[k], nCards(buckets[k]));

  // Remove cards no longer in the payload — EXCEPT one mid-dismiss (.dismissing): let its own 180ms timer
  // finish the collapse animation instead of yanking it instantly on a push (the user 2026-06-19).
  const undismissed = (el?: HTMLElement) => !!el && !el.classList.contains("dismissing");
  // A card that's leaving because it became a SUB-GOAL of another card absorbs INTO that parent (the user
  // 2026-06-29). Map each visible ask's NON-root tree-node ids → that ask's card, so a leaving id can find its
  // new home. (Falls back to an instant remove if there's no parent or motion is reduced.)
  let reduceMotion = false;
  try { reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { /* no matchMedia */ }
  const subgoalParent = new Map<string, HTMLElement>();
  if (!reduceMotion) for (const a of asks) {
    const pcard = askEls.get(a.itemId); if (!pcard) continue;
    for (const node of a.tree) { if (node.id !== a.itemId && !subgoalParent.has(node.id)) subgoalParent.set(node.id, pcard); }
  }
  for (const id of Array.from(askEls.keys())) {
    if (desired.has("a:" + id) || !undismissed(askEls.get(id))) continue;
    const leaving = askEls.get(id)!;
    const parent = subgoalParent.get(id), first = flipFirst.get("a:" + id);
    if (parent && first && parent !== leaving) absorbIntoParent(leaving, first.rect, parent);
    else leaving.remove();
    askEls.delete(id); unregisterSectionHost(id, leaving);   // a card that left the payload leaves the registry now, not at the next read of its item or a Collapsed flip
  }
  for (const tid of Array.from(groupEls.keys())) if (!desired.has("g:" + tid) && undismissed(groupEls.get(tid))) { groupEls.get(tid)?.remove(); groupEls.delete(tid); }

  // The tag lens's disclosure line (the user 2026-08-25, T70; lineage: the 665 outside-view line +
  // promoted banner, retired with the shared-view coupling, revived under the user's OWN lens —
  // what a filter hides stays one glance from reach, never silent, the 2026-08-11 rule). The click
  // resets to All, purely local (no kernel round-trip: sessionStorage + render).
  const lensOutN = outsideLensCount(asks);
  let lmore = document.getElementById("feed-lensmore");
  if (!lmore) {
    lmore = el("div", "");
    lmore.id = "feed-lensmore";
    lmore.title = "cards the tag filter hides — click to show all";
    lmore.onclick = () => { setFeedLens({ all: true }); render(); };
    list.appendChild(lmore);
  }
  const lensShownN = viewFiltered(asks).length;
  lmore.classList.toggle("prominent", lensOutN > lensShownN);
  lmore.style.display = lensOutN ? "" : "none";
  if (lensOutN) {
    lmore.textContent = lensOutN > lensShownN
      ? "Showing \u201c" + lensLabel(feedLens) + "\u201d \u2014 " + lensOutN
        + (lensOutN === 1 ? " card is" : " cards are") + " outside this filter \u00b7 show all"
      : lensOutN + (lensOutN === 1 ? " card" : " cards") + " outside this tag filter \u2014 show all";
  }
  ensureHostLoad(list);
  list.scrollTop = prevScroll;
  // Stale-freeze heal (hover-freeze): a LOCAL render can detach or re-key the hovered element with
  // no mouseleave — a removed element never fires leave events (typing in search filters the card
  // out; toggling Group swaps the ask card for a group card in place). :hover is live pointer
  // truth, checked per render (event-based, never a timer): no card under the pointer → the freeze
  // is stale, clear it and flush the queue; a DIFFERENT card under the pointer (re-keyed in place,
  // so no enter event ever fired) → re-arm to the element actually being hovered.
  if (freezeKey) {
    // a card OR a session header under the pointer (T285): both hold the gate
    const hov = document.querySelector<HTMLElement>(".feed-cols .fitem:hover, .feed-sess-head:hover");
    if (!hov) { freezeKey = null; flushFreeze(); }
    else { const k = hov.classList.contains("feed-sess-head") ? sessFreezeKey(hov) : kbHoverId(hov); if (k && k !== freezeKey) freezeKey = k; freezeCopy = isFocusCopy(hov); }
  }
  paintFreezeBadges();   // hover-freeze: local renders while frozen re-sync the +N/-N hints (no-op unfrozen)
  // stale-ring heal: releaseTabScope sweeps the DOCUMENT, but a card DETACHED at release (filtered
  // out by search, say) keeps its ring and the reconcile may reattach that cached element later —
  // with no scope active, any ring inside a card is stale; strip per render (kbMode owns its own)
  if (!tabScopeKey && !kbMode) document.querySelectorAll(".fitem .kbd-focus").forEach((n) => n.classList.remove("kbd-focus"));
  // keyboard-scope focus restore (the user 2026-08-24): a re-render may rebuild the focused
  // control's element, and a rebuild must not eat keyboard focus (click-safety, applied to the
  // keyboard). Find the control again by LOGICAL identity — class + label, then the old slot.
  if (tabScopeKey && tabScopeSig) {
    const card = cardElByKey(tabScopeKey, tabScopeCopy);
    const ae = document.activeElement;
    if (!card) releaseTabScope();
    else if (!ae || ae === document.body || !card.contains(ae)) {
      const els = cardControls(card);
      let i = els.findIndex((e2) => ctrlSig(e2) === tabScopeSig!.sig);
      if (i < 0) i = Math.min(tabScopeSig.idx, els.length - 1);
      if (i >= 0) tabScopeFocus(card, els, i);
      else releaseTabScope();
    }
  }
  // FLIP-across-identity: a card whose KEY is new this render (group→solo, solo→group, umbrella absorb) has no
  // First rect of its own, so the normal FLIP can't slide it. Alias it to its PREDECESSOR's rect — the card
  // key that covered one of its goals LAST render — so it glides in from where that predecessor sat instead of
  // popping (the user 2026-06-29). First predecessor found wins; never overwrite a card's own real First rect.
  if (!reduceMotion) for (const [itemId, curKey] of curItemKey) {
    if (flipFirst.has(curKey)) continue;                 // this card has its own First rect → normal FLIP path
    const prevKey = prevItemKey.get(itemId);
    if (prevKey && prevKey !== curKey && flipFirst.has(prevKey)) flipFirst.set(curKey, flipFirst.get(prevKey)!);
  }
  // FLIP step 2: any card whose column changed flies from its recorded spot to the new one (in the back layer).
  if (needFlip) flyColumnChanges(flipFirst, cols);
  prevItemKey = curItemKey;   // remember this render's identity map for the next FLIP-across-identity
  renderModal();   // keep the ⛶ full-screen tree (if open) in sync with this push
  applyExtHover(); // reconcile/renderModal may have rebuilt nodes — re-apply the rail-dot outlines (cards AND modal rows)
  persistViewState();   // whatever the user opened survives the reload a kernel restart brings (no-op unless it changed)
}

window.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && fullscreenAskId) { fullscreenAskId = null; renderModal(); }
});

// Focus policy (the user 2026-06-13): the feed is MOUSE-driven and almost never
// needs the keyboard — but clicking a card stole focus from the CHAT iframe,
// killing the chat's keyboard nav until you clicked back into it. So after any
// click in the feed, hand focus straight BACK to the chat — UNLESS the feed
// genuinely wants keys right now: a modal/help overlay is open (Esc closes it, its
// follow-up/report fields type) or the click landed in a text field. The check
// runs AFTER the click's own handler (deferred a tick), so a card click that just
// OPENED a modal keeps focus, and clicking ✕/backdrop to CLOSE one returns focus
// to chat. Same-origin combined page only — a no-op on the standalone /feed page
// or inside VS Code, where there's no sibling chat-frame to reach.
function feedWantsKeys(t: EventTarget | null): boolean {
  if (kbMode) return true;   // keyboard-nav is active → keep focus in the feed so the arrows land here
  if (document.getElementById("feed-modal")) return true;
  const el = t as HTMLElement | null;
  return !!el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
}
function returnFocusToChat(): void {
  try {
    if (!window.parent || window.parent === window) return;
    const chat = window.parent.document.getElementById("chat-frame") as HTMLIFrameElement | null;
    chat?.contentWindow?.focus();   // restores the chat document's last-focused element (tab/composer)
  } catch { /* cross-origin / not embedded → leave focus where it is */ }
}
window.addEventListener("click", (e) => {
  const t = e.target;
  setTimeout(() => { if (!feedWantsKeys(t)) returnFocusToChat(); }, 0);
});

// ── keyboard navigation of cards + their elements (the user 2026-07-01) ── the shell hands the feed keyboard
// focus via {romp:'paneFocus'} (Alt+Arrow); from there plain Arrow keys move a cursor over cards, Enter drops
// INTO a card and steps its clickable elements, Enter on one ACTIVATES it (a real click), Escape steps back
// out. Every highlight + action reuses the mouse path — card cursor = the same hoverAskId/applyFocus/showAskPath
// the hover uses; element cursor dispatches a real mouseenter (so zone highlights + timeline light exactly as on
// hover) and Enter calls the element's own click() — so the keyboard can never drift from the mouse.
const KB_EL_SEL = ".fcard-title.nav,.fask-distill-link,.fname,.fask-apiRetry,.fask-revive,.fdismiss,.fask-secbtn,.fask-bellbtn,.fcheck .lz-nav,.fask-delegation";
function kbCardEls(): HTMLElement[] {
  // VISUAL order, not DOM order (review 2026-08-24): the columns re-sequence via --col-order — in
  // both layouts since the drag extended — so the arrow cursor sorts cards by their column's
  // effective `order` (getComputedStyle resolves the var), DOM order within a column.
  // the BOARD's cards, under #feed-cols: the focused-session section (T347) above it carries the same column
  // classes, and a walk over both would interleave a copy with its card below by column order — the section is
  // a view of the board, and the cursor's field stays the board
  const els = Array.from(document.querySelectorAll<HTMLElement>("#feed-cols .fitem:not(.dismissing)"));
  const slot = new Map<HTMLElement, number>();
  for (const e of els) {
    const col = e.closest<HTMLElement>(".feed-col");
    slot.set(e, col ? parseInt(getComputedStyle(col).order || "0", 10) || 0 : 0);
  }
  return els.map((e, i) => ({ e, i, s: slot.get(e) || 0 }))
    .sort((a, b) => a.s - b.s || a.i - b.i)
    .map((x) => x.e);
}
function kbHoverId(el: HTMLElement): string {
  let key = el.dataset.key || "";
  if (key.startsWith("f:")) key = key.slice(2);         // a focused-section copy (T347) IS the card below: the same identity under an "f:" prefix
  return key.startsWith("g:") ? key : key.slice(2);   // group card → "g:<tid>" (applyFocus key); ask/deliverable → itemId
}
function kbSelectCard(el: HTMLElement | null): void {
  kbCardEl = el;
  const id = el ? kbHoverId(el) : null;
  hoverAskId = id; applyFocus();                       // the SAME white .focused ring the mouse hover shows
  if (el) el.scrollIntoView({ block: "nearest" });
  if (id && !id.startsWith("g:")) vscodeApi?.postMessage({ type: "showAskPath", itemId: id, sid: sidOfItem(id), locate: false });   // same lit timeline journey
}
function kbEnterCards(): void {
  kbMode = "cards";
  const cards = kbCardEls();
  kbSelectCard((kbCardEl && cards.indexOf(kbCardEl) >= 0) ? kbCardEl : (cards[0] || null));
}
function kbClearEl(): void {
  document.querySelectorAll(".kbd-focus").forEach((e) => e.classList.remove("kbd-focus"));
  if (kbEls[kbElIdx]) kbEls[kbElIdx].dispatchEvent(new MouseEvent("mouseleave"));
}
function kbSelectEl(idx: number): void {
  kbClearEl();
  kbElIdx = idx;
  const el = kbEls[idx];
  if (!el) return;
  el.classList.add("kbd-focus");                       // accent ring so title/Clear/etc read as focused
  el.scrollIntoView({ block: "nearest" });
  el.dispatchEvent(new MouseEvent("mouseenter"));       // reuse the element's OWN hover (zone .lz-hl + timeline)
}
function kbEnterCard(): void {
  if (!kbCardEl) return;
  kbEls = Array.from(kbCardEl.querySelectorAll<HTMLElement>(KB_EL_SEL)).filter((e) => e.offsetParent !== null);
  if (!kbEls.length) return;                            // nothing focusable inside → stay on the card cursor
  kbMode = "card"; kbSelectEl(0);
}
function kbExitCard(): void { kbClearEl(); kbEls = []; kbElIdx = -1; kbMode = "cards"; }   // back to the card cursor
function kbExit(): void { kbClearEl(); kbEls = []; kbElIdx = -1; kbMode = ""; kbCardEl = null; hoverAskId = null; applyFocus(); }

window.addEventListener("keydown", (e) => {
  if (!kbMode) return;
  if (e.altKey || e.ctrlKey || e.metaKey) return;      // Alt+Arrow is the shell's pane move; leave other combos alone
  if (document.getElementById("feed-modal")) return;   // the modal owns keys while it's open
  const k = e.key, fwd = (k === "ArrowDown" || k === "ArrowRight"), back = (k === "ArrowUp" || k === "ArrowLeft");
  if (kbMode === "cards") {
    if (fwd || back) {
      const cards = kbCardEls();
      let i = kbCardEl ? cards.indexOf(kbCardEl) : -1;
      if (i < 0 && hoverAskId) i = cards.findIndex((c) => kbHoverId(c) === hoverAskId);   // survive a re-render by key
      i = (i < 0) ? 0 : Math.max(0, Math.min(cards.length - 1, i + (fwd ? 1 : -1)));
      e.preventDefault(); kbSelectCard(cards[i] || null);
    } else if (k === "Enter") { e.preventDefault(); kbEnterCard(); }
    else if (k === "Escape") { e.preventDefault(); kbExit(); }
  } else if (kbMode === "card") {
    if (fwd || back) { e.preventDefault(); kbSelectEl(Math.max(0, Math.min(kbEls.length - 1, kbElIdx + (fwd ? 1 : -1)))); }
    else if (k === "Enter") { e.preventDefault(); kbEls[kbElIdx]?.click(); }   // EXACTLY a mouse click on that element
    else if (k === "Escape") { e.preventDefault(); kbExitCard(); }
  }
});
window.addEventListener("blur", () => { if (kbMode) kbExit(); });   // shell moved focus to another pane → drop the cursor

// Re-render when the card-display prefs change: a 'storage' event fires for a change made in ANOTHER
// same-origin pane/tab, and the ⛭ gear (same document) dispatches a "romp:settings" event after it writes
// (a same-doc write fires no storage event). Either way the cards re-gate to the new Explanations/Sub-goals.
// The collapsed DEFAULT now changes from the settings modal (2026-08-18), so the override-drop that
// used to live in the footer toggle rides the settings-change event instead: when `collapsed` flips —
// whichever surface flipped it — the per-card section overrides drop, so every card visibly re-flows
// to the new default. And the stacked pref re-applies on every change (another window's gear or a
// same-page toggle both land here).
let lastCollapsedPref = feedPrefs().collapsed;
function onSettingsChanged(): void {
  const p = feedPrefs();
  if (p.collapsed !== lastCollapsedPref) { lastCollapsedPref = p.collapsed; replaceSectionChoices([]); }   // through the shared setter, which re-applies every card here (the render gate leaves a card whose payload stood alone) and posts the map; the chat page reads the same flag for the row's default in the browser
  applyStacked(p.stacked);
  if (viewMenuEl) paintViewMenu(viewMenuEl);   // an open view menu re-reads the prefs it shows
  render();
}
window.addEventListener("storage", (e) => { if (e.key === "romp:settings") onSettingsChanged(); });
window.addEventListener("romp:settings", () => onSettingsChanged());
applyStacked(feedPrefs().stacked);   // boot: a persisted Stack takes effect before the first render

// The VS Code pipe's down-banner (the user 2026-07-21): while the extension host's kernel
// socket is down, the pane says so instead of sitting silently frozen on its last frame —
// and counts the typed messages the pipe is holding for delivery on reconnect. Only the
// extension posts pipeState; in the browser the page shim's own stale/disconnected bars cover this.
function pipeBanner(up: boolean, queued: number): void {
  const b = document.getElementById("rpipe");
  if (up) { if (b) b.remove(); return; }
  const bar = b || document.body.appendChild(Object.assign(document.createElement("div"), { id: "rpipe" }));
  bar.textContent = queued > 0
    ? `romp is unreachable — reconnecting… ${queued} message${queued === 1 ? "" : "s"} held, sending when it's back`
    : "romp is unreachable — reconnecting…";
}

// Card trouble badges mirror into the shell's notification bell (the user 2026-07-27): the chip on the
// card stays exactly as it was; the bell gets ONE durable entry per episode. badge-mirror.ts owns the
// episode identity (signature-keyed on the badge's own since/t); this wrapper owns the plumbing — the
// persisted seen-set (shared across tabs via localStorage, so two open dashboards don't double-log) and
// the {romp:'notify'} post the shell's bell listens for. Storing only the ACTIVE set is what re-arms a
// cleared badge and keeps the store from growing: a card that left the payload takes its sigs with it.
const BADGE_SEEN_KEY = "romp:cardNotified";
function mirrorBadges(items: AskItem[], clears: ClearNoticeRow[], sdk: SdkNoticeRow[], sync: SyncNoticeRow[], opts?: { cardsUnknown?: CardsUnknown }): void {
  let seen: string[] = [];
  try { seen = JSON.parse(localStorage.getItem(BADGE_SEEN_KEY) || "[]"); } catch { /* fresh */ }
  const seenSet = new Set(seen);
  // cardsUnknown (the Task tracking switch, T404 rounds five and six): not every card in the frame was built (the frame is
  // the switch's own off frame, or a merged frame naming an off host), so an absent card may sit behind a stand-in rather
  // than have left; the card half then keeps the stored card marks, and mints the on hosts' notices either way
  // (badge-mirror.ts). A stand-in frame never feeds a writer that prunes by absence
  const badges = badgeCardHalf(items, seenSet, opts?.cardsUnknown ?? false);
  // /clear boundary settles share the same seen-set + bell (the user 2026-07-27): a clear that
  // dropped open cards logs one durable entry naming them, so the drop is never silent.
  const boundary = clearBoundaryNotices(clears, seenSet);
  // …and so do SDK-backend failures (the user 2026-07-28): a crashed session thread, a dropped stream
  // or a refused setting is a romp problem, and it belongs where the user's other problems are.
  const sdkProblems = sdkProblemNotices(sdk, seenSet);
  // …and so do the automatic fleet syncs (the user 2026-07-30): romp moving commits between machines
  // by itself left no trace once the network panel's phase line cleared, successes least of all.
  const syncs = syncNotices(sync, seenSet);
  for (const n of [...badges.notices, ...boundary.notices, ...sdkProblems.notices, ...syncs.notices]) {
    try {
      window.parent?.postMessage({ romp: "notify", kind: n.kind, text: n.text, sid: n.sid, itemId: n.itemId }, "*");
    } catch { /* no shell (VS Code view) */ }
  }
  const active = new Set([...badges.active, ...boundary.active, ...sdkProblems.active, ...syncs.active]);
  try { localStorage.setItem(BADGE_SEEN_KEY, JSON.stringify(Array.from(active))); } catch { /* storage full */ }
}

// ── HOVER-FREEZE (the user 2026-08-24) ──────────────────────────────────────────────────────────
// While the pointer rests on a card — or on a session header row and its buttons (T285) — the board
// must not move under it: incoming feed payloads QUEUE (newest wins — intermediate states were never
// on screen, so nothing owes them an animation) instead of rendering, and the deferred churn shows
// as a subtle +N/-N beside the column pills and, in grouped mode, the session headers. Only the PAYLOAD path defers: the hovered card's own
// controls and every local gesture still render live from the displayed model. Flush is event-based
// (repo rule, no timers): the hovered card's mouseleave applies everything at once — a card CLEARED
// under the pointer flushes too, via its synthetic mouseleave — and window blur is the backstop.
let freezeKey: string | null = null;     // the hovered card's focus key, or null — pointer truth, no debounce
let freezeCopy = false;                  // which twin holds it: the focused section's copy or the board's element (T410)
let pendingFeedPayload: any = null;      // newest queued payload; older ones are superseded unseen
let focusStale = false;                  // an activeChat frame landed while the gate was held: the section repaints on release (T347)
function freezeEnter(key: string, copy = false): void { freezeKey = key; freezeCopy = copy; }
function freezeLeave(key: string, copy = false): void {
  if (tabScopeKey === key && tabScopeCopy === copy) releaseTabScope();   // hover-away releases the keyboard scope too, and
  //                                                                        only the scope held on THIS twin (T347b low, T410)
  // both twins of a card share the bare key (T347), so the pair (key, copy) is the hold: leaving one twin never
  // releases a hold taken on the other (the pointer crossing from the board's card to its copy above)
  if (freezeKey !== key || freezeCopy !== copy) return;
  freezeKey = null;
  flushFreeze();
}
let flushQueued = false;
function flushFreeze(): void {
  if (flushQueued) return;
  flushQueued = true;
  queueMicrotask(() => {   // after the CURRENT gesture's handlers finish — a synthetic mouseleave
    flushQueued = false;   // dispatched mid-click (the clear path) must not re-render the board under
    //                        the rest of its own handler (pendingCleared.add, .dismissing come after
    //                        the dispatch). Gesture-ordering, not a timer: no time window anywhere.
    // EITHER holder keeps the queue (post-merge audit 2026-08-24): with the keyboard scope on card
    // A and the pointer merely visiting card B, B's mouseleave queues this flush — running it would
    // apply the payload and move the card being keyed. The scope's own release paths all flush.
    if (freezeKey || tabScopeKey) return;
    const m = pendingFeedPayload;
    pendingFeedPayload = null;
    if (m) applyFeedPayload(m);          // render() repaints the badges away (nothing pending)
    else if (focusStale) render();       // a tab switch that landed while a card was held paints now (T347)
    focusStale = false;                  // either way the section is current: applyFeedPayload renders too
  });
}
window.addEventListener("blur", () => { releaseTabScope(); freezeKey = null; flushFreeze(); });   // backstop:
//   focus left the pane — BOTH gate holders release (the keyboard scope has no pointer to leave with)

// The queued payload's would-be card list — the same pre-filters applyFeedPayload will apply,
// WITHOUT its bookkeeping side effects (a hint must never mutate pendingCleared or the disclosure
// state; the flush re-runs the real thing).
function payloadView(m: any): AskItem[] {
  const incoming: AskItem[] = Array.isArray(m.asks) ? m.asks : [];
  const only = onlyTag();
  const vis = only ? incoming.filter((a) => matchesOnly(a.name, only)) : incoming;
  let out = pendingCleared.size ? vis.filter((a) => !pendingCleared.has(a.itemId)) : vis;
  // mirror the optimistic-restore overlay applyFeedPayload keeps (read-only): a restored card the
  // flush will push right back must not hint as a departure
  if (pendingRestored.size) {
    const present = new Set(out.map((a) => a.itemId));
    const inIncoming = new Set(incoming.map((a) => a.itemId));   // carried by the payload → the flush DROPS
    out = out.slice();                                            // its overlay entry; it rides (or is filtered
    //                                                               with) the normal path, so no re-add here
    for (const it of pendingRestored.values()) if (!present.has(it.itemId) && !inIncoming.has(it.itemId)) out.push(it);
  }
  return out;
}
// Paint (or clear) the deferred-churn badges: +N accent / -N block-red beside each column pill, and
// beside each on-board session header in grouped mode. Ensure-once spans on the build-once column
// heads; session badges ride the reconciled headers (found by the data-fsid stamp) and are re-synced
// at every render tail, so a local re-render while frozen can never strand a stale count.
function paintFreezeParts(b: HTMLElement, c: { add: number; del: number }): void {
  b.replaceChildren();
  if (c.add) { const i = el("i", "fz-add"); i.textContent = "+" + c.add; b.appendChild(i); }
  if (c.add && c.del) b.appendChild(document.createTextNode("/"));
  if (c.del) { const i = el("i", "fz-del"); i.textContent = "-" + c.del; b.appendChild(i); }
  // the explicit reading (the user 2026-08-25, liking the +N/−N but wanting it to say what it
  // means): a parenthetical in the accent dress, well under their verbosity ceiling
  const note = el("i", "fz-note");
  note.textContent = " (" + (c.add + c.del) + " changed — mouse away to apply)";
  b.appendChild(note);
  b.title = "updates waiting while you hover — they apply when the pointer leaves the card";
}
// Has the FROZEN card's own content changed in the withheld payload? Churn elsewhere and a stale
// card under the pointer are different facts (the user 2026-08-25) — this one gets its own line,
// shown WITH the churn badges when both are true. Group keys compare the turn's member set
// (itemId-sorted, so payload order can never fake a change); ask keys compare the one item.
function pendingSelfChanged(key: string): boolean {
  if (!pendingFeedPayload) return false;
  const pend = payloadView(pendingFeedPayload);
  const byId = (a: AskItem, b2: AskItem) => (a.itemId < b2.itemId ? -1 : 1);
  // CONTENT-projected compares only (contentSig — the user 2026-08-25): the whole-item compare
  // flagged the per-build recency-tint recompute as "this card updated" on nearly every card
  if (key.startsWith("g:")) {
    const tid = key.slice(2);
    const cur = asks.filter((a) => a.turnId === tid).slice().sort(byId).map((a) => contentSig(a as any)).join("|");
    const nxt = pend.filter((a) => a.turnId === tid).slice().sort(byId).map((a) => contentSig(a as any)).join("|");
    return cur !== nxt;
  }
  return contentSig(asks.find((a) => a.itemId === key) as any) !== contentSig(pend.find((a) => a.itemId === key) as any);
}
function paintFreezeBadges(): void {
  if (!pendingFeedPayload) {
    document.querySelectorAll(".freeze-badge").forEach((n) => n.remove());   // the floating header note is one too
    document.getElementById("freeze-selfnote")?.remove();
    return;
  }
  const toItems = (list: AskItem[]) => onActiveBoard(viewFiltered(list)).map((a) => ({ id: a.itemId, col: askColumn(a) as string, sid: a.sid }));   // the render pass's own board filter: the hint counts what is on screen (the 1886 read, medium 1)
  const d = freezeDiff(toItems(asks), toItems(payloadView(pendingFeedPayload)));
  const put = (host: Element | null, c: { add: number; del: number } | undefined) => {
    if (!host) return;
    let b = host.querySelector(":scope > .freeze-badge") as HTMLElement | null;
    if (!c || (!c.add && !c.del)) { b?.remove(); return; }
    if (!b) { b = el("span", "freeze-badge"); host.appendChild(b); }
    paintFreezeParts(b, c);
  };
  for (const key of activeCols()) {
    put(document.querySelector("#feed-cols .feed-col.col-" + key + " .feed-col-head"), d.cols[key]);   // the board's heads, never the focused section's (T347)
  }
  const groupedNow = feedPrefs().grouped;
  // The HOVERED header row must not change shape (T285 review): a badge appended inside it lands after the
  // auto-margin Clear all and slides that button out from under the pointer — the click loss the header
  // hold exists to prevent, caused by the hold's own hint. That row's badge floats instead: body-mounted,
  // pointer-inert, right-aligned just under the row (the self-note idiom), so the row's rect stands.
  // The hovered row is ONE (column, session) header, matched by its whole key: a session with cards in two
  // columns heads a run in each, and the other column's header keeps its in-row badge and never gets the float.
  const hoveredHead = freezeKey && freezeKey.startsWith("h:") ? freezeKey : null;
  let headNote = document.getElementById("freeze-headnote") as HTMLElement | null;
  let floated = false;
  document.querySelectorAll<HTMLElement>(".feed-sess-head").forEach((h) => {
    const sid = h.getAttribute("data-fsid") || "";
    const c = groupedNow ? d.sess[sid] : undefined;
    if (sessFreezeKey(h) !== hoveredHead) { put(h, c); return; }
    put(h, undefined);                                   // never inside the hovered row
    if (!c || (!c.add && !c.del)) return;
    if (!headNote) { headNote = el("div", "freeze-badge"); headNote.id = "freeze-headnote"; document.body.appendChild(headNote); }
    paintFreezeParts(headNote, c);
    const r = h.getBoundingClientRect();
    headNote.style.top = Math.round(r.bottom + 2) + "px";
    headNote.style.right = Math.max(0, Math.round(window.innerWidth - r.right)) + "px";
    floated = true;
  });
  if (!floated) headNote?.remove();
  // the hovered/keyed card's OWN pending update — its own line, independent of the churn badges
  // (both show when both are true). Body-mounted and pointer-inert: it must never affect hover,
  // and the frozen card's rect is stable by construction (that is the freeze's whole contract).
  const selfKey = freezeKey || tabScopeKey;
  const selfCard = selfKey ? cardElByKey(selfKey, freezeKey ? freezeCopy : tabScopeCopy) : null;   // the HELD twin's rect (T410)
  let selfNote = document.getElementById("freeze-selfnote");
  if (!selfKey || !selfCard || !pendingSelfChanged(selfKey)) {
    selfNote?.remove();
  } else {
    if (!selfNote) {
      selfNote = el("div", "");
      selfNote.id = "freeze-selfnote";
      selfNote.textContent = "(this card updated — mouse away to refresh)";
      document.body.appendChild(selfNote);
    }
    const r = selfCard.getBoundingClientRect();
    selfNote.style.left = Math.round(r.left + 12) + "px";
    selfNote.style.top = Math.round(r.bottom - 24) + "px";
  }
}

// ── CARD KEYBOARD SCOPE (the user 2026-08-24) ──────────────────────────────────────────────────
// Tab, pressed while a card is hovered (a click puts the pointer there too) or held by the keyboard
// card cursor, scopes to THAT card: it cycles every visible control on it — section pills, Clear,
// retries, the bell, follow-up, sub-goal links — wrapping at the ends; Enter/Space activate; the
// accent .kbd-focus ring marks the stop. Escape or the pointer leaving the card releases back to
// normal page order. Focus survives the feed's constant re-renders by LOGICAL control identity
// (class + label, then the old slot) — the click-safety rule applied to keyboard focus. While focus
// is inside, the card holds the payload gate hover-freeze uses, so the board cannot move the card
// being keyed (same gate as the pointer).
let tabScopeKey: string | null = null;
let tabScopeCopy = false;   // the scope holds the focused section's copy, not the board's element (T347)
let tabScopeSig: { sig: string; idx: number } | null = null;
function cardElByKey(key: string, copy = false): HTMLElement | null {
  // `copy`: the focused-session section's element for the card (T347), keyed one prefix over the board's;
  // the keyboard scope re-finds the element it holds, never the other twin (a Tab from a hovered copy used to
  // resolve to the board's card and scroll away from the pointer)
  const k = key.startsWith("g:") ? key : "a:" + key;
  return document.querySelector<HTMLElement>('[data-key="' + (copy ? "f:" + k : k) + '"]');
}
/** Is this card element the focused section's copy (T347)? Its key wears the section's prefix. */
function isFocusCopy(card: HTMLElement | null): boolean { return !!card && (card.dataset.key || "").startsWith("f:"); }
function cardControls(card: HTMLElement): HTMLElement[] {
  // the card's own DOM order IS its visual reading order — title row, pills, tail controls
  return Array.from(card.querySelectorAll<HTMLElement>(KB_EL_SEL)).filter((e) => e.offsetParent !== null);
}
function ctrlSig(e: HTMLElement): string {
  return e.className + "|" + (e.getAttribute("aria-label") || e.textContent || "").trim().slice(0, 24);
}
function tabScopeFocus(card: HTMLElement, els: HTMLElement[], i: number): void {
  document.querySelectorAll(".kbd-focus").forEach((n) => n.classList.remove("kbd-focus"));
  const el2 = els[i];
  if (!el2) return;
  tabScopeKey = kbHoverId(card);
  tabScopeCopy = isFocusCopy(card);   // which twin the scope holds (T347)
  tabScopeSig = { sig: ctrlSig(el2), idx: i };
  if (el2.tabIndex < 0 && !el2.matches("button, a, input")) el2.tabIndex = -1;   // focusable, outside page order
  el2.classList.add("kbd-focus");
  el2.focus();
}
function releaseTabScope(): void {
  if (!tabScopeKey) return;
  tabScopeKey = null;
  tabScopeCopy = false;
  tabScopeSig = null;
  document.querySelectorAll(".kbd-focus").forEach((n) => n.classList.remove("kbd-focus"));
  const ae = document.activeElement as HTMLElement | null;
  if (ae && ae.closest(".fitem")) ae.blur();
  if (!freezeKey) flushFreeze();   // the scope held the payload gate — releasing applies the queue
}
window.addEventListener("keydown", (e) => {
  if (document.getElementById("feed-modal")) return;   // the modal owns keys while it is open
  if (e.key === "Escape" && tabScopeKey) {
    e.preventDefault(); e.stopPropagation();
    releaseTabScope();
    return;
  }
  if (e.key === "Tab") {
    let card = tabScopeKey ? cardElByKey(tabScopeKey, tabScopeCopy) : null;
    // the HOVERED element itself, copy or board (T347): the freeze key names the card, not which twin the
    // pointer rests on, and Tab must land where the pointer is
    if (!card) card = document.querySelector<HTMLElement>(".fitem:hover") || (freezeKey ? cardElByKey(freezeKey) : null) || kbCardEl;
    if (!card || !card.isConnected) return;
    const ae = document.activeElement as HTMLElement | null;
    if (ae && /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName) && !card.contains(ae)) return;   // typing elsewhere
    const els = cardControls(card);
    if (!els.length) return;
    e.preventDefault(); e.stopPropagation();
    let i = ae ? els.indexOf(ae) : -1;
    i = e.shiftKey ? (i <= 0 ? els.length - 1 : i - 1) : (i >= els.length - 1 ? 0 : i + 1);   // WRAP at the ends
    //                                                     (Shift+Tab = the same cycle, reversed)
    tabScopeFocus(card, els, i);
    // SELECT-ON-FOCUS for the view pills (the user 2026-08-24): landing on a SELECTOR applies it at
    // once, no Enter — radio-group semantics. The split: .fask-secbtn (Background/Summary/Sub-goals,
    // which switch what the card SHOWS) are selectors; everything else — Clear, retries, the bell,
    // follow-up, session names, sub-goal links — is an ACTION and must never fire from mere focus
    // (action is the default for anything ambiguous). The click lives HERE, in the Tab gesture, and
    // NOT in tabScopeFocus: the render-tail focus restore calls tabScopeFocus too, and a click there
    // would re-apply per re-render — one application per user gesture. The already-selected pill is
    // a no-op (focus keeps, nothing toggles), so cycling through it never flips the card's view off.
    const landed = els[i];
    if (landed && landed.matches(".fask-secbtn") && !landed.classList.contains("on")) landed.click();
    return;
  }
  if ((e.key === "Enter" || e.key === " ") && tabScopeKey) {
    const ae = document.activeElement as HTMLElement | null;
    const card = cardElByKey(tabScopeKey, tabScopeCopy);
    if (!ae || !card || !card.contains(ae)) return;
    if (ae.matches("button, a, input")) return;   // native activation already fires the click
    e.preventDefault();
    ae.click();                                   // EXACTLY a mouse click on that control
  }
}, true);

// The feed payload's full application — model swap, bookkeeping, render. One body, two callers:
// the message handler applies live when no card is hovered; flushFreeze applies the newest queued
// payload when the pointer leaves (hover-freeze above).
function applyFeedPayload(m: any): void {
  judgeLimit = m.judgeLimit && typeof m.judgeLimit === "object"
    ? m.judgeLimit as { bucket?: string; resets_at?: number; model?: string } : null;
  const incomingAsks: AskItem[] = Array.isArray(m.asks) ? m.asks : [];
  // THE GATE for absence (T404 round seven). A card absent from this payload is the event every writer below acts on:
  // a clear confirmed, a card's disclosure state pruned, a predicted move given up as gone, an optimistic tick retired,
  // a badge mark pruned. That reading holds only when the payload was BUILT over every host's cards. The Task tracking
  // switch's off frame is a stand-in with no cards (the single-kernel one returns before this function; a merged frame
  // carries an off host's stand-in beside the others' frames and names that host in offHosts), a host attached but
  // yet to send a frame is named in pendingHosts, and a page load's very first merged frame, built before the first
  // /tunnels answer has said which remote hosts exist at all, is marked hostsUnread (round nine), so while any host's
  // cards are unknown, every absence-driven writer stands down: nothing is confirmed, pruned, retired or forgotten
  // by a card not being here, and presence-driven work goes on. The store bounds hold: the badge mirror keeps only the
  // off hosts' marks, and the view state grows by gestures alone (feed-view-state.ts), so a long mixed state (an
  // attached ISOLATED peer never adopts the switch: _converge_peer_settings stands down for it) costs stale entries
  // for cards that left, never growth without a gesture. The frame's own `off` stays the local kernel's word.
  const cardsUnknown = frameCardsUnknown(m);
  // A clear is CONFIRMED once the kernel's payload no longer lists it → stop suppressing it. Then drop
  // any still-pending (kernel hasn't caught up) from this payload so a stale push can't resurrect them.
  if (!cardsUnknown) for (const id of Array.from(pendingCleared)) if (!incomingAsks.some((a) => a.itemId === id)) pendingCleared.delete(id);
  { const acks = new Set<string>(Array.isArray(m.ackHosts) ? m.ackHosts.map(String) : []); if (m.undoAck === true) acks.add(""); ackHosts = acks; }   // which kernels account for an undo with a floor (round fifteen)
  releaseRestoredByEvidence(incomingAsks, m);               // a federated pane's release: by the card's presence in its own kernel's newer build, never by absence
  // the page's record of a cleared card ends when a live payload shows the card unsuppressed (a restore landed, a refused clear came back): the
  // board's copy is the fresh one, and a later frame naming the id must not rebuild an entry from the old snapshot (the round-ten verifier)
  if (!cardsUnknown) for (const id of Array.from(clearedItems.keys())) if (!pendingCleared.has(id) && incomingAsks.some((a) => a.itemId === id)) clearedItems.delete(id);
  // demo/recording view filter (the user 2026-07-14): `#only=<tag>` shows only matching-name cards; the
  // clear/follow bookkeeping above still runs against the FULL payload, so hidden cards stay consistent.
  // Self-clean the persisted disclosure state against the AUTHORITATIVE live set (the user 2026-07-24).
  // incomingAsks, deliberately — not `visible` below: `#only=` hides cards without ending them, and
  // pruning against the filtered list would throw away the hidden cards' sections. Event-based: a card
  // leaving the payload (cleared, archived) IS the signal, so nothing ages out on a timer. Not while a host's
  // cards are unknown (the gate above): a card of an off host has not left, it was not built.
  if (!cardsUnknown) pruneViewStateTo(new Set(incomingAsks.map((a) => a.itemId)));
  const only = onlyTag();
  const visible = only ? incomingAsks.filter((a) => matchesOnly(a.name, only)) : incomingAsks;
  asks = pendingCleared.size ? visible.filter((a) => !pendingCleared.has(a.itemId)) : visible;
  // confirm/clear optimistic follow-up moves against the authoritative payload. buildId says WHEN this
  // payload read the store, which is what makes "the kernel has answered my click" an event and not a
  // guess (see reconcileFollowMove); a kernel too old to send one reads as 0 and simply never confirms
  // an acked prediction early, leaving the backstop to retire it.
  lastFeedEvent = "payload";                         // tripwire: this render's inputs are the fresh payload
  lastPayloadBuildId = typeof m.buildId === "number" ? m.buildId : 0;
  // per-host counters when this is a merged multi-kernel payload (mergeHostFeeds.buildIds);
  // absent on a single-kernel payload, where the top-level buildId is the one counter there is
  const perHostBuildIds = m.buildIds && typeof m.buildIds === "object" && !Array.isArray(m.buildIds)
    ? m.buildIds as Record<string, number> : undefined;
  // the build seen per kernel: what an undo's send moment is measured against (round twelve). The local kernel's from the map when it carries it,
  // else the payload's own (a merged map without the local key left the local record standing still; the round-twelve verifier's low); no numeric
  // build, no record (a kernel with none on record takes the click-time release at the send, never a baseline of zero)
  if (perHostBuildIds) { for (const [h, n] of Object.entries(perHostBuildIds)) if (typeof n === "number") lastSeenBuild.set(h, n); }
  if ((!perHostBuildIds || typeof perHostBuildIds[""] !== "number") && typeof m.buildId === "number") lastSeenBuild.set("", m.buildId);
  payloadHosts = perHostBuildIds ? Object.keys(perHostBuildIds).filter((h) => h !== "") : [];   // federation's word on the kernels attached (attachedHosts)
  reconcileFollowMove(incomingAsks, lastPayloadBuildId, perHostBuildIds, !!cardsUnknown);
  reconcilePendingDone(incomingAsks, !!cardsUnknown);   // retire an optimistic tick once the real tree carries it
  // An optimistic Undo is CONFIRMED once the kernel's payload carries the id again → stop forcing it.
  // Until then, keep the cached card in `asks` so the replace above can't drop the just-restored card (flicker).
  if (pendingRestored.size) {
    for (const id of Array.from(pendingRestored.keys())) if (incomingAsks.some((a) => a.itemId === id)) pendingRestored.delete(id);
    const present = new Set(asks.map((a) => a.itemId));
    for (const it of pendingRestored.values()) if (!present.has(it.itemId)) asks.push(it);
  }
  workingSet = new Set(Array.isArray(m.working) ? m.working : []);
  if (typeof m.selfHost === "string" && m.selfHost) feedSelfHost = m.selfHost;
  // Index every session's colour by the name a peer would address it by. Federation merges the hosts'
  // payloads, so one pass over the merged asks covers the whole fleet; a card whose session has no
  // cards of its own simply gets no colour, which is honest rather than invented.
  for (const a of incomingAsks) {
    if (!a.color || !a.name) continue;
    sessionColors.set(a.name, a.color.bg);
    const c = a.sid ? a.sid.indexOf(":") : -1;             // remote sid → also index the bare name under its host
    if (c > 0 && !a.name.includes(":")) sessionColors.set(a.sid.slice(0, c) + ":" + a.name, a.color.bg);
  }
  awaitingSet = new Set(Array.isArray(m.awaiting) ? m.awaiting : []);   // await-green awaiting dots (the user 2026-07-13)
  unknownSet = new Set(Array.isArray(m.stateUnknown) ? m.stateUnknown : []);   // listed-but-unreadable → gray ring, never a blank
  bgServicesMap = m.bgServices && typeof m.bgServices === "object" ? m.bgServices : {};   // session name -> judge-classified service descs → the session-header chip (2026-07-24)
  if (Array.isArray(m.order)) sessionOrder = m.order.filter((x: any) => typeof x === "string");   // grouped-mode session rank (tab/lane order)
  pendingHosts = Array.isArray(m.pendingHosts) ? m.pendingHosts.filter((h: any) => typeof h === "string") : [];
  pendingDead = Array.isArray(m.pendingDead) ? m.pendingDead.filter((h: any) => typeof h === "string") : [];
  syncHostloadBackstops();
  adoptBoards(m.boards);   // the data-defined boards the kernel ships (plans/card-boards.md, phase three), the frame's whole word: a frame without the field (an older kernel's) holds none
  if (m.views && typeof m.views === "object") feedTagViews = m.views as SessionViews;   // tag DEFINITIONS only — never `active`
  if (Array.isArray(m.sessions)) {
    sessionsMeta = m.sessions.filter((s: any) => s && typeof s.sid === "string" && typeof s.name === "string");
    // a filter aimed at a session the tab strip no longer shows is moot — clear it (the deciding
    // event: the session left the tab list), rather than leaving the board silently pinned to nothing
    if (feedOnlySid && !sessionsMeta.some((s) => s.sid === feedOnlySid)) setFeedOnly(null);
  }
  if (typeof m.now === "number") {
    hostNow = m.now;
    hostNowAt = typeof m.nowAt === "number" ? m.nowAt : Date.now();   // the pair travels together: the frame's clock, and when THAT frame arrived (federation stamps it, so a re-emit of a held frame does not re-anchor)
  } else {
    hostNow = Math.floor(Date.now() / 1000);   // an older kernel's frame carries no clock: the browser's own, from here
    hostNowAt = Date.now();
  }
  mirrorBadges(incomingAsks, Array.isArray(m.clearNotices) ? m.clearNotices : [],
    Array.isArray(m.sdkNotices) ? m.sdkNotices : [],
    Array.isArray(m.syncNotices) ? m.syncNotices : [], { cardsUnknown });   // card trouble chips + /clear drops + SDK failures + fleet syncs also log in the shell's bell (chips stay on the cards)
  if (typeof m.dismissedCount === "number") dismissedCount = m.dismissedCount;
  // the push the undo was waiting on has landed (or any fresher one): cue off. On a FEDERATED pane the merge lands on any kernel's push, so the
  // cue waits until every kernel the undo went to has built past the send (a proxy for its restore having landed; the second contributor's
  // review, 2026-09-22: an unrelated local push cleared it with the remote card still off and invited a re-press that went local); the
  // six-second backstop and the account frame's clear stand
  if (!federatedPane() || undoRoutedBuilt(m)) clearUndoBusy();
  if (typeof m.showDismissed === "boolean") showDismissed = m.showDismissed;
  if (typeof m.canUndoClear === "boolean") canUndoClear = m.canUndoClear;
  render();
  if (!feedAnnounced) {
    feedAnnounced = true;
    // First content is on screen → tell the shell, the way the timeline does: the boot splash's cue, and the
    // exact event a notification tap's card reveal waits for — the shell holds its {romp:'revealCard'} until
    // the feed has cards to scroll to (kernel.py _LANDING_REVEAL_JS). Standalone page: no parent, nothing to say.
    try { if (window.parent && window.parent !== window) window.parent.postMessage({ romp: "ready", app: "feed" }, "*"); } catch { /* no shell */ }
  }
}


// every frame's synchronous handling time is measured (perf-telemetry.ts: one clientDiag row a
// minute, read by `romp perf client`); the handler itself is unchanged
// …and handed the merged frames by direct call from federation.js when this page has it (frame-listener.ts)
listenForFrames(perfFrameHandler("feed", (m) => vscodeApi?.postMessage(m), (e: MessageEvent) => {
  const m = e.data;
  if (!m) return;
  if (m.type === "pipeState") { pipeBanner(!!m.up, Number(m.queued) || 0); return; }
  if (m.romp === "paneFocus") { kbEnterCards(); return; }   // the shell handed us keyboard focus → arm card nav
  if (m.romp === "activeChat") { applyLocalFocus(typeof m.id === "string" && m.id ? m.id : null, false, !!m.gesture, typeof m.nonce === "number" ? m.nonce : null); return; }   // the chat pane's tab change, handed across the page by the shell (T416): the reader's own passes the hover-freeze, a kernel-driven one defers under a held card; no jump scroll
  if (m.romp === "revealCard") {
    // a bell-entry click (the user 2026-07-28) or a notification tap (2026-09-06) jumps to the card it was
    // minted from: scroll it into view and pulse it accent so the eye lands on the right card. A card in a
    // FOLDED thread has no element yet — unfold first (the same rule revealCards follows: the navigation wins
    // over the disclosure). A card that no longer exists under its own key (cleared, or folded into a group)
    // falls back to opening the session.
    // The shell shows this pane and posts the jump in the SAME task, before the observer has re-measured
    // the list (its callback waits for a rendering step): a paint owed from a hidden stretch is settled
    // here on the shell's word, or a card added while away is not there to find (2026-09-07). The
    // observer's next callback re-measures, so a wrong word costs one unseen paint, never a stale pane.
    if (paintDirty) { feedIntersecting = true; releasePaint(); }
    const key = "a:" + String(m.itemId || "");
    unfoldThreadsFor(new Set([key]));
    // Match the key STRUCTURALLY, never an interpolated attribute selector: a crafted push-card value
    // with a quote or bracket would throw a SyntaxError inside querySelector and abort this handler,
    // dropping the openSession fallback too (review find on #940, 2026-09-07).
    const target = (Array.from(document.querySelectorAll("[data-key]")) as HTMLElement[])
      .find((c) => c.dataset.key === key) || null;
    if (target) {
      target.scrollIntoView({ block: "center", behavior: "smooth" });
      target.classList.remove("reveal-pulse"); void target.offsetWidth;   // restart the animation on a repeat jump
      target.classList.add("reveal-pulse");
      target.addEventListener("animationend", () => target.classList.remove("reveal-pulse"), { once: true });
    } else if (m.sid) {
      frameGesture = !!m.gesture;   // the bell click or the notification tap behind this frame is the reader's gesture (round three)
      try { vscodeApi?.postMessage({ type: "openSession", id: String(m.sid) }); } finally { frameGesture = false; }
    }
    return;
  }
  if (m.type === "feed") {
    // the Task tracking switch off (T404): the kernel builds no feed and sends this flag; the page shows its notice in
    // place of the list (rendered by the kernel, hidden while on) and applies nothing; the next real frame swaps back
    const ttOff = document.getElementById("tt-off"), ttList = document.getElementById("feed-list");
    if (ttOff) ttOff.hidden = !m.off;
    if (ttList) ttList.hidden = !!m.off;
    if (m.off) {
      // the notice IS this frame's content: the romp loader, whose observer watches the list the off frame leaves empty,
      // would otherwise sit over the notice to its 30 s failsafe (T404 round two, medium 1)
      document.getElementById("pane-spin")?.classList.add("gone");
      // the error center is not task tracking (round four, the ruling): the off frame carries the notice rings, and the
      // shell's bell is fed from here as from a built frame, so a failed sync, a refused write or a session that cannot
      // start is told while off; the frame stays loaded hidden while the shell closes the pane, so this runs
      mirrorBadges([], Array.isArray(m.clearNotices) ? m.clearNotices : [], Array.isArray(m.sdkNotices) ? m.sdkNotices : [], Array.isArray(m.syncNotices) ? m.syncNotices : [], { cardsUnknown: true });
      if (typeof m.dismissedCount === "number") dismissedCount = m.dismissedCount;
      if (typeof m.canUndoClear === "boolean") canUndoClear = m.canUndoClear;
      return;
    }
    // HOVER-FREEZE: a hovered card must not move on screen — queue the payload (newest wins) and
    // hint the deferred churn on the headers instead; mouseleave/blur flush it (see freezeEnter).
    if (freezeKey || tabScopeKey) { pendingFeedPayload = m; paintFreezeBadges(); return; }
    applyFeedPayload(m);
  } else if (m.type === "activeChat") {
    // THE FOCUSED SESSION (T347): the kernel relays the chat pane's active tab to the feed clients of the same
    // window — on every tab switch, and once when this client registers, so a reloaded feed learns the focus
    // without waiting for one. The frame IS the event: the section repaints here, never on a clock. While a
    // card is held under the pointer (hover-freeze) the repaint waits for the release, like a payload does:
    // the held card's rect standing still is that gate's whole contract, and the section's height sits above it.
    // Since T416 the local signal has usually moved the section already (applyLocalFocus): the frame carrying the
    // pending session settles the record and changes nothing; one that disagrees is a push built before the kernel
    // took the switch and yields; only the ECHO (the pending session, and the chat's announcement number when both
    // sides know it) or the kernel's marked reaffirm answer clears the record, never a count of disagreeing frames
    // (a burst of switches faster than the round trip would otherwise land a stale one for a whole round trip: the
    // round-two review). An unchanged session is no event.
    const id = typeof m.id === "string" && m.id ? m.id : null;
    const nonce = typeof m.nonce === "number" ? m.nonce : null;
    if (focusPending) {
      // the echo is an agreeing frame whose number is at or above the record's (a watermark): the record's own echo, or
      // a later announcement of the same session (the chat re-announcing after a socket flap, with a new number) that
      // would otherwise leave the record standing for the page's life; a burst back to the same session is still
      // protected, since its earlier announcement's frame carries a lower number. One caveat for a SECOND delivery path:
      // the frames ride one ordered socket, so an echo can never overtake an earlier frame; a path that could reorder
      // them would let the stale frame land after the echo cleared the record (the round-three review).
      const echo = id === focusPending.sid && (focusPending.nonce == null || nonce == null || nonce >= focusPending.nonce);
      if (!m.reaffirm && !echo) return;
      focusPending = null;
    }
    if (id === focusedSid) return;
    focusedSid = id;
    if (!showFocused) return;
    if (freezeKey || tabScopeKey) { focusStale = true; return; }
    render();
  } else if (m.type === "hoverCards") {
    // rail-dot hover in the CHAT panel → white-outline the card(s) built from
    // that turn, plus the matching ROWS inside an open modal (eid). The host
    // fans the same hover out to the timeline.
    extHoverKeys = new Set(Array.isArray(m.keys) ? m.keys.map(String) : []);
    extHoverEid = typeof m.eid === "string" && m.eid ? m.eid : null;
    applyExtHover();
  } else if (m.type === "nodeOverrideResult" && typeof m.nodeId === "string") {
    // The kernel's verdict on a Done click. Agreement is silent — the optimistic tick simply stays until
    // the next payload carries it for real. Disagreement REVERTS the tick and says why, out loud: a
    // cross-off that quietly un-crossed itself a second later would be worse than the slow version it
    // replaced (fail loudly, CLAUDE.md).
    if (!m.ok) {
      pendingDone.delete(m.nodeId);
      renderModal();
      feedToast("couldn't mark that sub-goal done: " + (String(m.error || "") || "the kernel refused it"));
    }
  } else if (m.type === "redistillResult" && typeof m.itemId === "string") {
    // The kernel's verdict on the warn modal's Try again — BOTH answers toast (the user 2026-08-13,
    // round 2: success used to lean on the Distilling… swirl, which a Working card withholds, so a
    // WORKING retry read as a silent no-op). The success copy promises what is actually true in every
    // column: the line regenerates on the next judge pass over this card.
    if (redistillWatch && redistillWatch.itemId === m.itemId) {
      window.clearTimeout(redistillWatch.timer);
      redistillWatch = null;
    }
    if (m.ok) feedToast("summary retry armed — it regenerates on the next judge pass over this card");
    else feedToast("couldn't retry the summary: " + (String(m.error || "") || "the kernel refused it"));
  } else if (m.type === "revealCards") {
    // chat rail CLICK → scroll to the card(s) covering that turn and pulse them (the user 2026-07-23).
    // Distinct from hoverCards, which only outlines whatever is already on screen: this one MOVES the
    // feed. A turn can belong to several cards; all of them pulse, and the first is what we scroll to.
    revealCards(new Set(Array.isArray(m.keys) ? m.keys.map(String) : []));
  } else if (m.type === "openCard" && typeof m.key === "string") {
    // rail-dot click → open this card's modal (key is fullscreenAskId-shaped:
    // ask itemId, "i:<itemId>" standalone, "g:<turnId>" group). hl = the clicked
    // turn's event id: ring its row(s) and scroll the first one into view.
    fullscreenAskId = m.key;
    vscodeApi?.postMessage({ type: "cardOpened", itemId: m.key, sid: "" });   // rail-dot opens count too (2026-08-25)
    if (typeof m.hl === "string" && m.hl) extHoverEid = m.hl;
    renderModal();
    applyExtHover();
    if (extHoverEid) document.querySelector(".dot-hl[data-eid]")?.scrollIntoView({ block: "center" });
  } else if (m.type === "settingRefused" && typeof m.text === "string" && m.text) {
    // the kernel refused a bell toggle this page posted (its store could not be read): end the optimistic
    // state ON THIS EVENT — the card's sticky latch drops and the bell repaints to what the payload holds
    // (the card gate's key reads the latch through cardNotifyOn) — and say why. A SOFT refusal: nothing typed was lost, so the fading
    // toast (the chat's weight for the same class), never the must-dismiss dialog; the shell's bell keeps the
    // durable record under its own `refused` kind, so muting judge warnings never mutes these. A `warn`
    // frame had no handler on this page, so the bell stayed painted as if the click had landed until a reload.
    if (m.gesture === "bell" && typeof m.itemId === "string" && m.itemId) pendingNotify.delete(m.itemId);
    render();
    window.parent?.postMessage({ romp: "notify", kind: "refused", text: m.text,
                                 sid: typeof m.sid === "string" ? m.sid : "",
                                 itemId: typeof m.itemId === "string" ? m.itemId : "" }, "*");
    feedToast(m.text);
  } else if (m.type === "reviveFailed" && typeof m.id === "string" && m.id) {
    // the kernel's reply to a Revive (review find, 2026-09-08): the parked card whose button this page latched
    // lets go, and the reason rides the fading toast, only when a latch here was the one answered; the chat
    // pane of the same dashboard shows the failure in the revived session's own pane either way, so a revive
    // clicked there says nothing twice.
    if (rearmLatches({ kind: "revive", id: m.id })) {
      feedToast("Couldn't revive " + String(m.name || m.id) + ": " + String(m.text || "unknown error"));
    }
  } else if (m.type === "noticeActionDone" && typeof m.itemId === "string" && m.itemId) {
    // the kernel's answer to a notice card's action (T370). A refusal: the latched buttons let go and the reason is said
    // (the card stays). A success on a card that dismisses on its action: the kernel cleared it, so the card leaves NOW and
    // no button re-arms (round four, high: re-armed, it invited a second click that delivered the words again before the
    // push that removes the card landed). A success on a card that stays: its buttons let go.
    const twins = cardTwins(m.itemId);
    const dismisses = twins.some((c) => !!((c as any)._it?.notice?.dismissOnAction)) || !!asks.find((a) => a.itemId === m.itemId)?.notice?.dismissOnAction;
    // the card's modal, when it shows this card (round four of PR 1831): a success on a dismissing card closes it with the card;
    // any other answer re-renders it, which rebuilds the notice face and so re-arms its buttons (the same rule as the card's)
    // `held` (the second executed review of PR 1935, 2026-09-21): the words went out but the dismissal's write refused, so the card
    // STAYS and its buttons stay spent (a re-armed button would offer the delivery again; the kernel refuses it, but the pane
    // should not ask); the toast says both halves. Before this the answer was ok false for a delivery that had happened.
    const held = !!m.ok && !!m.held;
    if (fullscreenAskId === m.itemId) { if (m.ok && dismisses && !held) fullscreenAskId = null; renderModal(); }
    if (m.ok && dismisses && !held) {
      pendingCleared.add(m.itemId);   // a push already in flight must not paint it back before the kernel's rebuild lands
      for (const c of twins) c.dispatchEvent(new MouseEvent("mouseleave"));   // removed under the pointer: the card's own leave logic (freezeLeave, the hover highlight off or back to the pin), as the clear paths dispatch it (round six, low)
      for (const c of twins) { c.remove(); unregisterSectionHost(m.itemId, c); if (askEls.get(m.itemId) === c) askEls.delete(m.itemId); if (fsAskEls.get(m.itemId) === c) fsAskEls.delete(m.itemId); }
      dropDismissed([m.itemId]);
    } else if (!held) {
      for (const c of twins) {
        for (const b of Array.from(((c as any)._nActions as HTMLElement | undefined)?.querySelectorAll("button") || []) as HTMLButtonElement[]) {
          b.disabled = false; b.textContent = (b as any)._idle || b.textContent;
        }
      }
    }
    if (!m.ok) feedToast("The card's action was refused: " + String(m.error || "unknown error"));
    else if (held) feedToast("The card's action ran, but " + String(m.error || "the card could not be dismissed") + ".");
  } else if (m.type === "undoAck") {
    // a landed undo's account (round fifteen of PR 1967): nothing to say but the build floor, the kernel's counter when it processed the undo;
    // the checks on that kernel judge their payloads by it from here on. Federation stamps a remote kernel's ack with its host
    setUndoFloor(typeof m.host === "string" ? m.host : "", m.seq, m.buildId);
    if (typeof m.seq === "number") undoPopped.delete(m.seq);   // the undo landed: the click's record of what it restored is spent
  } else if (m.type === "wsup") {
    dropChecksOnReconnect("");                                   // the local kernel's socket reopened (the shim's frame): a lost account holds nothing off the board
  } else if (m.type === "hostUp" && Array.isArray(m.hosts)) {
    // the tunnel poll's word that a remote kernel came back (a down-to-up transition): a SECOND trigger beside the relay socket's own reopen
    // (the romp:hostRelayUp listener above), kept for the one case that event never covers: a relay socket that never opens again on this
    // page while the poll's row reads up, so no reopen fires here and the account it lost would hold the card off until a reload (the
    // post-merge note on PR 2018: this frame alone missed the watchdog redial that loses the account, and fired on an upSeq bump with the
    // socket intact; the second contributor's post-merge review of PR 2021 asked for the case by name)
    for (const h of m.hosts) if (typeof h === "string" && h) dropChecksOnReconnect(h);
  } else if (m.type === "retryRefused" && typeof m.sid === "string" && m.sid) {
    // the backend could not take the manual retry's send: the Retry this page latched lets go, and says why
    if (rearmLatches({ kind: "retry", sid: m.sid })) feedToast(String(m.text || "Couldn't retry: the kernel refused it."));
  } else if (m.type === "undoRouted" && Array.isArray(m.hosts)) {
    // federation's word on where the undo went (round twelve of PR 1967, the round-eleven verifier's design): the send's moment, per kernel, as the
    // build of that kernel this page had seen. The click releases NOTHING on a federated pane; a suppression ends on the EVIDENCE that the card was
    // restored, a payload from the card's own kernel built past this moment that lists it (releaseRestoredByEvidence). A stale held frame, built before the
    // send, cannot release it; a kernel the undo never reached never lists a restored card with a newer build; a kernel that restored an older batch
    // shows exactly the cards it restored
    lastUndoHosts = new Set<string>(m.hosts.map(String));
    undoSentBuild.clear();
    for (const h of lastUndoHosts) { const seen = lastSeenBuild.get(h); if (seen !== undefined) undoSentBuild.set(h, seen); }   // the cue's measure per kernel: none for a kernel with no build on record
    // the restore checks, per suppression (round thirteen): every card suppressed on a routed kernel, at that kernel's seen build. A kernel with no
    // build on record can give no evidence, so its suppressions take the click-time release here instead, never a baseline of zero (the round-twelve
    // verifier's MEDIUM, the twelfth executed review)
    // on a FEDERATED pane alone, read at the send, the click's moment: the kernel-served shim routes every send through the manager, so this frame
    // reaches a single-kernel pane too, and there the click released the popped entry's ids while the OTHER pending clears stayed suppressed; a
    // check on those let the kernel's in-flight build, claimed before the clear, paint the card back for a beat (the thirteenth executed review,
    // 2026-09-22: a regression against the carry). The evidence PATH stays ungated, so a pane that flips to single-kernel between the click and
    // the restore keeps the checks it wrote as a federated one
    if (federatedPane()) {
      for (const id of Array.from(pendingCleared)) {
        const h = suppressedHostOf(id);
        if (!lastUndoHosts.has(h)) continue;
        if (restoreChecks.has(id)) continue;                     // a check stands until judged: the undo that wrote it accounts for it, a later undo does not re-arm it for its own sequence
        const seen = lastSeenBuild.get(h);
        if (seen === undefined) { pendingCleared.delete(id); restoreChecks.delete(id); continue; }
        restoreChecks.set(id, { host: h, sentBuild: seen, seq: typeof m.seq === "number" ? m.seq : undefined });
      }
    }
  } else if (m.type === "err" && typeof m.text === "string" && m.text) {
    // the dialog interrupts; the bell KEEPS it (the user 2026-07-29) — dismissing the modal must not erase
    // the fact that a message never landed. Same {romp:'notify'} bridge the card-badge mirror below uses.
    const title = typeof m.title === "string" && m.title ? m.title : "That action was not delivered";
    const copy = typeof m.copy === "string" ? m.copy : "";
    // an information frame (`ok`: the landed reorder, "the last clear stands") is a dialog and no bell entry: nothing went undelivered (the round-four verifier of PR 1967)
    if (m.ok !== true) window.parent?.postMessage({ romp: "notify", kind: "undelivered",
                                                   text: copy ? title + ": " + copy : title,
                                                   sid: typeof m.sid === "string" ? m.sid : "" }, "*");
    showErrDialog(title, m.text, copy);
    const sid = typeof m.sid === "string" ? m.sid : typeof m.id === "string" ? m.id : "";
    // the kernel's reply IS the event, for the request it names (rearmLatches): a refused apiRetry releases
    // that session's Retry; a refused askFollowUp releases that card's Continue, and its predicted move yields
    // to the kernel's answer (revertFollowMove; the no-answer backstop would have bounced it later with a toast
    // that blamed silence). A reply naming a session and no request is an older kernel's: the session's Retry
    // and Revive, as before. A store gesture's session account (a clear, a drop, an undo: `op` rides) re-arms NOTHING:
    // no feed latch belongs to those requests, and a latch is released only by the reply to the request that made it
    // (the fourth review of PR 1967 and the manager's ruling, 2026-09-21, reversing the round-three verifier's ask to
    // re-arm on the session: the `!op` branch is for old kernels' frames, not because a store's refusal is those
    // buttons' reply). One naming neither answers no request here.
    const op = typeof m.op === "string" ? m.op : "";
    const itemId = typeof m.itemId === "string" ? m.itemId : "";
    // a clear the clears log refused (the second review of PR 1967, 2026-09-21): the reply names the batch's ids; they leave pendingCleared
    // (the click's suppression, released before only when a payload omitted the card, which a refused clear never does) and the cached
    // Undo entry, and the board repaints them where they were, as the dialog says nothing changed
    const refusedIds = Array.isArray(m.itemIds) ? m.itemIds.map(String) : (op === "askClear" && itemId ? [itemId] : []);
    const storeOp = op === "askClear" || op === "askClearMany" || op === "nodeOverride" || op === "clearAll" || op === "undoClear";
    const fromHost = typeof m.host === "string" ? m.host : "";   // federation stamps a remote kernel's account with its host (prefixInbound); the local kernel's has none
    if (op === "undoClear") setUndoFloor(fromHost, m.seq, m.buildId);   // the refusal's and the reorder's frames carry the undo's build floor (round fifteen) and its sequence
    if (storeOp && Array.isArray(m.batches) && !fromHost && !federatedPane()) {
      // the kernel's stack rides every gesture account sent while its clears log reads (round eight of PR 1967; none while it cannot be read): this page takes it as its own, which covers a refused clear (its
      // ids are not in the batches: back where they were), a refused undo (the batch the click popped is still the newest: back on top), a
      // reorder (the owed batch restored, the last clear's entry back on top) and ids this page never held (an entry standing for them). The
      // branches below are the road for an older kernel's frame, which carries no stack, for the current kernel's stack-less frames (the read-fault
      // account and any account beside it while the log cannot be read), and for every frame on a FEDERATED pane, which keeps
      // no stack (federatedPane): there a refused clear's cards come back by their ids and nothing else moves
      const owedB: string[] = Array.isArray(m.owedBatch) ? m.owedBatch.map(String) : [];
      const bats: string[][] = m.batches.map((b: any) => (Array.isArray(b) ? b.map(String) : []));
      // the frame carries the newest log batches and the count before the bound (round ten): with older batches left out, the frame says
      // nothing about their cards, so the reconcile keeps their entries and suppressions
      const truncated = typeof m.batchesTotal === "number" && m.batchesTotal > bats.length - (owedB.length ? 1 : 0);
      reconcileClearedStack(bats, owedB, truncated, refusedIds);
      if (op === "undoClear" && typeof m.seq === "number") undoPopped.delete(m.seq);   // the stack reconciled the click's restore: its record is spent
    } else if ((op === "askClear" || op === "askClearMany" || op === "nodeOverride" || op === "clearAll") && refusedIds.length) {
      for (const id of refusedIds) pendingCleared.delete(id);
      // the card comes back NOW, in either window (the third review of PR 1967): inside the 180 ms collapse the per-card identity gate
      // would keep `.dismissing` and the timer would remove the element, and after it dropDismissed has pruned the item from `asks`, so a
      // bare render() brought nothing back until the next payload; the class comes off and the cached item is re-pushed, as Undo does
      // the refused cards come back by their ids, stack or no stack (a federated pane keeps none, round ten of PR 1967): the collapse class off,
      // the suppression released above, so the next render shows them again from `asks`
      for (const id of refusedIds) for (const c of cardTwins(id)) c.classList.remove("dismissing");
      for (let i = clearedStack.length - 1; i >= 0; i--) {
        if (!clearedStack[i].some((it) => refusedIds.includes(it.itemId))) continue;
        clearedStack.splice(i, 1);                                     // the optimistic Undo entry for a clear that never happened goes
      }
      for (const id of refusedIds) { const it = clearedItems.get(id); if (it && !asks.some((a) => a.itemId === id)) asks.push(it); }   // its cards back on the board, from the page's own record of them
      render();
    } else if (op === "undoClear" && refusedIds.length) {
      // a refused undo (the third review of PR 1967): the optimistic restore stood as a phantom the dialog contradicted; the batch the
      // kernel named leaves `asks` and pendingRestored, is suppressed again and goes back on the Undo stack, since the kernel keeps
      // it owed and the next Undo reaches it
      const back = asks.filter((a) => refusedIds.includes(a.itemId));
      for (const id of refusedIds) { pendingRestored.delete(id); pendingCleared.add(id); }
      asks = asks.filter((a) => !refusedIds.includes(a.itemId));
      if (back.length) clearedStack.push(back);
      // a reorder whose owed cards did not come back (`owedIds`; the sixth executed review of PR 1967): their re-journal is the kernel's newest
      // batch, so the NEXT Undo is theirs; an empty entry above the last clear's stands for them (that pop restores nothing optimistically and
      // takes the round-trip cue, the payload bringing them), and the pop after matches the kernel's: the last clear
      // unless the top entry already stands for those cards (the first contributor's round-four comment on PR 2025, 2026-09-22): under a STANDING
      // read fault the kernel's reorder frame ships no stack, so this branch runs after the marked read-fault account took the click's restore
      // back, and when the click had popped the owed entry itself (this page held the owed card's copy, so it restored it optimistically) that
      // entry is back on top already; a second stand-in above it left the pane's stack one entry longer than the kernel's, and its last lit
      // Undo restored nothing and drew a bare ack
      if (Array.isArray(m.owedIds) && m.owedIds.length) {
        const owedNow = m.owedIds.map(String);
        const top = clearedStack[clearedStack.length - 1];
        const topIds: string[] = top ? (((top as any)._ids as string[] | undefined) ?? top.map((it) => it.itemId)) : [];
        if (!(topIds.length && topIds.every((id) => owedNow.includes(id)))) clearedStack.push([]);
      }
      if (op === "undoClear" && typeof m.seq === "number") undoPopped.delete(m.seq);   // the refusal named the click's batch: its record is spent
      render();
    } else if (op === "undoClear" && m.readFault === true && !fromHost && !federatedPane() && !Array.isArray(m.batches) && typeof m.seq === "number" && undoPopped.has(m.seq)) {
      // the kernel's read-fault account by its POSITIVE marker (`readFault`; round six of PR 2025, the first contributor's round-two comment): keyed on
      // what an account lacked, the take-back fired on an owed-note refusal whose ledger read faulted after the undo rows landed, took back a batch
      // the kernel had restored, and the next Undo popped a phantom; an account without the marker settles nothing about the click, so the record
      // stands for the one that does (this marker, the ack, a stack).
      // the local kernel's frame on a single-kernel pane alone, as the stack branch above (the round-three verifier of PR 2025: a federated click
      // keeps no record, so the guard is a belt; a remote kernel's account names no click of this page).
      // an undo account that carries no stack and names no ids: the kernel restored NOTHING (its clears log could not be read, the read-fault
      // account; the second contributor's post-merge review of PR 2021): the click's optimistic restore stood as cards the kernel never restored
      // beside a dialog saying the cards stay as they are, since the revert above runs on the ids an account names. The batch this click popped,
      // kept by the undo's sequence, leaves the board and pendingRestored, is suppressed again and goes back on top of the stack: the kernel's
      // newest batch is still that clear's, so the next Undo, once the log reads, is its
      const popped = undoPopped.get(m.seq)!;
      const ids = popped.map((it) => it.itemId);
      for (const id of ids) { pendingRestored.delete(id); pendingCleared.add(id); }
      asks = asks.filter((a) => !ids.includes(a.itemId));
      clearedStack.push(popped);
      if (op === "undoClear" && typeof m.seq === "number") undoPopped.delete(m.seq);   // the marked account settled the click: its record is spent
      render();
    }
    // an undo account with neither a stack nor ids nor the marker (an owed-note refusal beside a landed undo) says nothing about the click's
    // restore, so the click's record stands for the account that does (round six); UNDO_POPPED_CAP bounds a record no account ever settles
    if (op === "undoClear" && (!federatedPane() || lastUndoHosts.has(fromHost))) clearUndoBusy();   // an undo's account from a kernel the undo went to is the event the round trip's cue waits for: a refusal sends no payload (rounds eleven and twelve of PR 1967)
    if (op === "apiRetry" && sid) rearmLatches({ kind: "retry", sid });
    else if (op === "askFollowUp" && itemId) {
      rearmLatches({ kind: "followup", itemId });
      if (pendingFollowMove.has(itemId)) revertFollowMove(itemId);
    } else if (!op && sid) rearmLatches({ kind: "session", sid });   // an old kernel's reply naming a session and no request; a store gesture's account (op rides) re-arms nothing (the fourth review of PR 1967)
  } else if (m.type === "pickerOptions" && typeof m.name === "string") {
    // the host read the blocked session's live resume-picker screen — show the
    // same options in-page; a choice goes back as keystrokes (transport only,
    // the user decides — the never-auto-answer rule holds).
    showPickerDialog(String(m.name), Array.isArray(m.options) ? m.options.map(String) : []);
  } else if (m.type === "colorSync" && typeof m.sid === "string" && typeof m.bg === "string") {
    // VS Code leg of the optimistic colour echo (see applyColorEcho): the extension fans the chat
    // pane's swatch pick here, since each webview's localStorage is its own — no storage event.
    applyColorEcho(m.sid, m.bg);
  } else if (m.type === "cardPredict" && Array.isArray(m.ids)) {
    // kernel fan-back (the user 2026-07-20): a context-carrying reply just fired SOMEWHERE — the chat's
    // citation follow-up, a picker/permission answer typed in the chat, another feed view's button — so
    // flip the named card(s) to Working NOW instead of waiting out the rebuild+push round trip. Same
    // prediction machinery as the local buttons (idempotent when this view initiated it); the kernel's
    // next push stays authoritative. An id may name a SUB-goal (a per-sub follow-up target): resolve it
    // to the visible top card that carries it in its tree.
    const kind: MoveKind = m.flavor === "answer" ? "answer" : "followup";
    let moved = false;
    for (const raw of m.ids.map(String)) {
      const top = asks.find((a) => a.itemId === raw) ?? asks.find((a) => a.tree?.some((n) => n.id === raw));
      if (top && askColumn(top) !== "asks") { optimisticFollowMove(top.itemId, kind); moved = true; }   // Working through askColumn: the category first (the 1837 round-two read, low 1)
    }
    if (moved) render();
  } else if (m.type === "cardMoveAck" && Array.isArray(m.ids)) {
    // the kernel's answer to the prediction above (_ack_card_move). Ids resolve exactly as cardPredict's do
    // — the kernel may name a SUB-goal that a visible top card carries — and an id this view never predicted
    // is a no-op, so the ack is safe to broadcast to every feed pane.
    const bid = typeof m.buildId === "number" ? m.buildId : 0;
    // which kernel's counter `bid` is on: federation stamps a remote ack with its host (prefixInbound);
    // an unstamped ack came from the local kernel — host "", the same value hostOf gives local cards
    const ackHost = typeof m.host === "string" ? m.host : "";
    const why = typeof m.why === "string" ? m.why : "";   // the user's copy of a store fault, when the reopen's write refused
    for (const raw of m.ids.map(String)) {
      const top = asks.find((a) => a.itemId === raw) ?? asks.find((a) => a.tree?.some((n) => n.id === raw));
      ackFollowMove(top ? top.itemId : raw, !!m.ok, bid, ackHost, why);
    }
  }
}));

// ---- the deny-note prompt (the held-mail card's Deny, a notice action of kind quarantine): the one click-time input any
// action kind takes (plans/notice-cards.md, "Action kinds"): an optional note back to the sender, which the bus mails to
// the origin host so the sender's agent learns why instead of waiting forever (the user 2026-07-26). No Cancel button
// (the user: two choices, deny with a note or without); the backdrop closes without deciding and the message stays held.
// Lives on document.body outside the re-rendered feed root, so a kernel push mid-decision cannot eat the note.
function showDenyNoteDialog(onDeny: (note?: string) => void): void {
  document.getElementById("quar-dialog")?.remove();
  const overlay = el("div", "pickdlg-overlay"); overlay.id = "quar-dialog";
  const box = el("div", "pickdlg-box qdlg-box");
  const title = el("div", "pickdlg-title"); title.textContent = "Deny this message. Send a note back to the sender?";
  const ta = el("textarea", "qdlg-text qdlg-feedback") as HTMLTextAreaElement;
  ta.placeholder = "optional: tell the sender why (delivered to them as postal mail)";
  const row = el("div", "qdlg-actions");
  const withNote = el("button", "fdismiss fq fq-no") as HTMLButtonElement; withNote.textContent = "Deny & send note";
  withNote.title = "drop the message and mail your note back to the sender";
  withNote.onclick = () => { const note = ta.value.trim(); overlay.remove(); onDeny(note || undefined); };
  const bare = el("button", "fdismiss fq") as HTMLButtonElement; bare.textContent = "Deny without note";
  bare.title = "drop the message; nothing is sent back";
  bare.onclick = () => { overlay.remove(); onDeny(undefined); };
  row.append(withNote, bare);
  box.append(title, ta, row);
  overlay.appendChild(box);
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  document.body.appendChild(overlay);
  ta.focus();
}

// ---- in-page resume-picker dialog (the answerPicker flow, no native QuickPick) ----
function showPickerDialog(name: string, options: string[]) {
  document.getElementById("picker-dialog")?.remove();
  if (!options.length) return;   // host already toasted "no longer on screen"
  const overlay = el("div", "pickdlg-overlay"); overlay.id = "picker-dialog";
  const box = el("div", "pickdlg-box");
  const title = el("div", "pickdlg-title");
  title.textContent = `${name} is waiting on the resume picker — choose to answer it`;
  box.append(title);
  options.forEach((opt, i) => {
    const btn = el("button", "pickdlg-opt");
    btn.textContent = opt;
    btn.onclick = () => {
      vscodeApi?.postMessage({ type: "answerPickerChoice", name, n: i });
      overlay.remove();
    };
    box.append(btn);
  });
  const cancel = el("button", "pickdlg-opt pickdlg-cancel");
  cancel.textContent = "Cancel";
  cancel.onclick = () => overlay.remove();
  box.append(cancel);
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  overlay.appendChild(box);   // the box INTO the overlay (the verifier of PR 1967, 2026-09-21: built and never attached, so a refusal painted a bare dim sheet with no words and no button)
  document.body.appendChild(overlay);
  (box.querySelector("button") as HTMLElement | null)?.focus();
}

// The kernel's LOUD channel (the user 2026-07-29). The feed had no error surface at all: every failure here
// went to feedToast, which fades, and a kernel `warn` had no handler on this page whatsoever — so an action
// fired from a card could fail with the page showing nothing. A refused reply is typed work that is gone, so
// it gets a dialog you must dismiss, reusing the resume-picker dialog's chrome rather than inventing another.
function showErrDialog(title: string, text: string, copy: string) {
  document.getElementById("err-dialog")?.remove();
  const overlay = el("div", "pickdlg-overlay"); overlay.id = "err-dialog";
  const box = el("div", "pickdlg-box");
  const h = el("div", "pickdlg-title"); h.textContent = title;
  const d = el("div", "pickdlg-detail"); d.textContent = text;
  box.append(h, d);
  if (copy) {
    const c = el("button", "pickdlg-opt");
    c.textContent = "Copy my text";
    c.onclick = () => { navigator.clipboard?.writeText(copy); c.textContent = "Copied"; };
    box.append(c);
  }
  const ok = el("button", "pickdlg-opt pickdlg-cancel");
  ok.textContent = "Dismiss";
  ok.onclick = () => overlay.remove();
  box.append(ok);
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  overlay.appendChild(box);   // the box INTO the overlay (the verifier of PR 1967, 2026-09-21: built and never attached, so a refusal painted a bare dim sheet with no words and no button)
  document.body.appendChild(overlay);
  (box.querySelector("button") as HTMLElement | null)?.focus();
}

// White outline for cards named by a chat rail-dot hover — and, when a modal is
// open, for the modal rows/node-lines whose event matches (data-eid, set in
// renderTreeNode). Re-applied after each render() since reconcile/renderModal
// may rebuild nodes mid-hover.
let extHoverKeys = new Set<string>();
let extHoverEid: string | null = null;
function applyExtHover() {
  document.querySelectorAll<HTMLElement>("[data-key]").forEach((c) => {
    // via extHoverMatches, NOT a raw set lookup: the host names cards by goal-node id and the DOM keys
    // them by render namespace ("a:<itemId>"), so comparing them directly never matched and the whole
    // timeline→feed / chat→feed highlight was dead (see ./card-key).
    c.classList.toggle("dot-hl", extHoverMatches(c.dataset.key, extHoverKeys));
  });
  document.querySelectorAll<HTMLElement>("[data-eid]").forEach((c) => {
    c.classList.toggle("dot-hl", !!extHoverEid && c.dataset.eid === extHoverEid);
  });
}

// Scroll to the named cards and pulse them. Same key bridge as the hover (./card-key), so it lands on
// exactly the cards a hover would have outlined. The class is removed and re-added across a forced
// reflow, or a second click on the same card would re-add a class it already has and CSS would replay
// nothing — the "clicked again and it didn't flash" bug this shape avoids.
// A target inside a FOLDED thread has no element to scroll to, and a jump that lands on nothing is the
// silent no-op a collapse must never cause (the user 2026-07-31). Unfold the owning thread(s) and render
// before looking: the navigation wins over the disclosure, and the thread stays open afterwards so you
// can see where you were taken. Shared by every "take me to this card" entry (revealCards, revealCard).
function unfoldThreadsFor(keys: Set<string>): void {
  if (!collapsedThreads.size) return;
  let opened = false;
  // the run each card RENDERS in — per (session, column), T263c — read from the MODEL, never a memo of the last
  // paint (T263e, review of T263d: a memo went stale in flat mode and under a held paint): a member of a typed
  // turn with ≥2 current members renders in the group's column (buildGroup: the worst member's), else in its
  // own — the render's own rule, shared (turnGroups)
  const colOf = new Map<string, Column>();
  for (const [tid, ms] of turnGroups(viewFiltered(asks))) { const c = buildGroup(tid, ms).column; for (const m of ms) colOf.set(m.itemId, c); }
  for (const a of asks) {
    const tkey = threadKey(a.sid, colOf.get(a.itemId) ?? askColumn(a));
    if (collapsedThreads.has(tkey) && extHoverMatches("a:" + a.itemId, keys)) {
      collapsedThreads.delete(tkey); opened = true;
    }
  }
  if (opened) render();
}

function revealCards(keys: Set<string>) {
  unfoldThreadsFor(keys);
  const hits = Array.from(document.querySelectorAll<HTMLElement>("[data-key]"))
    .filter((c) => extHoverMatches(c.dataset.key, keys));
  if (!hits.length) return;
  hits[0].scrollIntoView({ block: "center", behavior: "smooth" });
  for (const c of hits) {
    c.classList.remove("card-pulse");
    void c.offsetWidth;
    c.classList.add("card-pulse");
    // and off again when the animation ends (the per-card update gate no longer rewrites className every
    // render, which used to strip it); under reduced motion no animation runs and the class paints a steady
    // accent ring, so a backstop a little past the animation's 1.4 s takes it off. animationend bubbles, so
    // only the pulse's own end counts — a button's acted flash inside the card must not end it. One pulse per
    // element at a time: a second reveal inside the window re-arms the same handle, so the first reveal's
    // backstop cannot cut the second's animation short.
    const prev = (c as any)._pulse as { off: (ev?: AnimationEvent) => void; t: number } | undefined;
    if (prev) { window.clearTimeout(prev.t); c.removeEventListener("animationend", prev.off); }
    const off = (ev?: AnimationEvent) => {
      if (ev && ev.animationName !== "romp-card-pulse") return;
      c.removeEventListener("animationend", off); window.clearTimeout(cur.t); (c as any)._pulse = undefined; c.classList.remove("card-pulse");
    };
    const cur = { off, t: window.setTimeout(off, 1500) };
    (c as any)._pulse = cur;
    c.addEventListener("animationend", off);
  }
}

// ── the 15 s LIVE PASS ────────────────────────────────────────────────────────────────────────────
// Keep every "Xm ago" and every running duration honest between host pushes, on the kernel's clock (nowSec):
// on the delta path a quiet board sends a pane nothing between the 60 s reposts, and the per-card update gate
// (feed-card-gate.ts) repaints a card only when its inputs change, so this pass is what moves time on every
// card the kernel does not re-send. Every age-bearing label on a card face is stamped (feed-age.ts stampAge)
// and the pass repaints them all from one clock, rather than each render path owning a copy of the
// formatting.
//
// The pass WRITES ONLY WHAT CHANGED: relAge rounds to the minute and then the hour, so a handful of labels
// move per tick on a board of hundreds, and in a document that has ever created a MutationObserver — gear.js
// creates several at boot — Blink treats an identical textContent write as a real Text-node replacement that
// dirties layout (paintAge compares first). A pane nobody can see skips the pass and catches up once when
// shown (liveRefresher, the Outline pane's pattern), by the paint gate's own two measures (paint-gate.ts):
// the tab hidden, or #feed-list off screen by the observer's word, which is how a pane the shell has
// display:none'd reads. The two events that release an owed paint catch the pass up, so the feed has one
// definition of "hidden".
function livePass(): void {
  const now = nowSec();
  for (const card of [...askEls.values(), ...fsAskEls.values()]) {   // …and the focused section's copies (T347)
    const it = (card as any)._it as AskItem | undefined;
    if (!it) continue;
    // the latched Continue's hover title names how long ago it was sent (contTitle, T150): a title, so it
    // cannot be stamped — refreshed here for the few latched buttons, compare-then-write like the rest, and
    // only once the payload itself carries the latch (the same test updateAskCard re-arms on): a click
    // latches the button before any frame lands, and the stale object's followupAt would name an older
    // follow-up
    const cont = (card as any)._cont as HTMLButtonElement | undefined;
    if (cont && cont.disabled && (it.followupPending || it.recheck || it.rejudging)) {
      const ct = contTitle(true, "a continue", it.followupAt);
      if (cont.title !== ct) cont.title = ct;
    }
  }
  refreshAges(document.querySelectorAll<HTMLElement>("[data-age-t]"), now, relAge, ageColorReadable);
}
const live = liveRefresher({ hidden: () => paintHeld(document.hidden, feedIntersecting, true), pass: livePass });
setInterval(live.tick, 15000);
document.addEventListener("visibilitychange", live.catchUp);

initFileView((m) => vscodeApi?.postMessage(m));   // the file browser opens the viewer in this pane (and saves ride the poster)
// …and how the viewer names the session a file was opened from: this pane's session list (the same tab
// set the chat has, relayed per frame, dormant sessions included), else a card carrying the session's
// name and colour — never sessionColors, which is keyed by NAME; a sid neither knows falls to the
// kernel's 8-character stub.
setFileViewIdentity((id) => {
  const s = sessionsMeta.find((x) => x.sid === id) ?? asks.find((a) => a.sid === id);
  return s && s.name ? { name: s.name, color: s.color ?? null } : hostStub(id);
});
initFileBrowse((m) => vscodeApi?.postMessage(m));   // …and a Browse files ask lands its sibling overlay

vscodeApi?.postMessage({ type: "ready" });

// the notice's button while the Task tracking switch is off (T404): the settings on Task tracking
document.getElementById("tt-off-btn")?.addEventListener("click", () => {
  // through gear-host's one road (the shell forwards it into the settings iframe at the Task tracking tab); a standalone
  // /feed or /fleet page has no shell to ask and hosts no gear, so it goes to the dashboard with the tab named in the hash,
  // which the landing opens (T404 round two, medium 2: the bare post reached nothing on the only page where the notice shows)
  if (!openGear(window, { tab: "tasks" })) window.location.assign("/" + window.location.search + "#settings=tasks");
});
