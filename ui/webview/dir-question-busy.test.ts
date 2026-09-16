// The FOLDER QUESTION keeps the provisional TAB (round four of the held-column deferral, 2026-09-15). The create flow's real
// functions are lifted from render.ts (the chat-split-exec.test.ts pattern) over a world that plays the shell (a parent window
// counting colBusy posts), the kernel (createSession / cancelCreate sent), the dialog (showConfirm's head mirrored — the real
// closeConfirm is lifted — answered by the test) and the picker (an element with a display; the real dismissDirPromptForPicker
// runs first, as in openPicker), and driven the way the page is: a create from the picker, text typed into the provisional
// tab's box, the kernel's createDirMissing, then each of the user's answers. What is pinned:
//   * the question keeps the TAB — its box holds the text, the column is busy by provisionalId alone, no colBusy:false, the
//     backstop stood down (the kernel answered);
//   * a DISMISSAL (Escape, the backdrop, the picker closed with no create) makes it a failed create: the text in its own box and
//     under its own id only — no other session's draft touched, a sub-agent viewer active or not — busy stays, no flip; the
//     user's ✕ is the one discard, and that flips;
//   * "Create it and start" retries on the SAME tab (one tab, one create; the backstop armed again); "Edit the path" keeps the
//     tab and prefills the picker; the same name created from there is the retry too;
//   * the picker opened OVER the prompt (the palette's Mod+Shift+O) dismisses it first as its own create's — quietly — so a
//     second create's question can never settle the first; and an older prompt a newer dialog cancels settles nothing.
// The default world models a HELD column (once its listed member is gone nothing is held here, focusAfterDismiss); `nextActive`
// models an ordinary one. Synthetic ids only.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { createRequire } from "node:module";
import { provisionalName, mintProvisionalId, isProvisionalId } from "./provisional";
import { StagedStack, quoteReplyBody, stagedPosts, isCitationShape } from "./staged-messages";
import { takeReloadNotices, keepReloadNotices } from "./reload-notices";
import { columnHolds, columnEmptiness } from "./chat-columns";
import { isSubId } from "./subagent-view";

const requireCjs = createRequire(__filename);
const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const fn = (name: string): string => {
  const i = RENDER.indexOf(`function ${name}(`);
  assert.ok(i >= 0, `${name} not found`);
  return RENDER.slice(i, RENDER.indexOf("\n}\n", i) + 3);
};
const lineOpt = (name: string): string => { const i = RENDER.indexOf(`function ${name}(`); return i >= 0 ? RENDER.slice(i, RENDER.indexOf("\n", i) + 1) : ""; };   // a ONE-LINE function; "" on an older render.ts
const fnOpt = (name: string): string => (RENDER.indexOf(`function ${name}(`) >= 0 ? fn(name) : "");   // "" on an older render.ts: the tests then fail on behaviour, not on a missing lift

const A = "11111111-2222-3333-4444-555555555501", B = "11111111-2222-3333-4444-555555555502", C = "11111111-2222-3333-4444-555555555503";
const VIEWER = C + "/agent/a1";
const REQ = { name: "notes", backend: "sdk", dir: "/proj/not-there-yet", host: "" };
const TYPED = "notes for a session whose folder is not there yet";

type Hooks = { posts: Record<string, unknown>[]; boot: Record<string, unknown>[]; sent: Record<string, unknown>[]; seq: string[]; confirms: string[]; pickers: number; persisted: number; timers: (() => void)[]; cleared: number; toasts: string[]; answered: (string | null)[]; claims: string[]; fired: number; reloadEnded: number; closeSplit: number[] };
type Ship = { name: string; shipId: string; b64?: string };
type State = { provisionalId: string | null; dirQuestionFor: string | null; failed: string[]; activeId: string | null; drafts: Record<string, string>; sessions: string[]; timer: boolean; why: Record<string, string> };
type Api = {
  startCreate: (req: typeof REQ, mkdir?: boolean) => void; onCreateDirMissing: (m: Record<string, unknown>) => void; closePicker: (abandon?: boolean) => void;
  openPicker: () => void; cancelProvisional: () => void; closeTabLocally: (id: string) => void;
  onCreateWarn: (m: { text: string; rid?: unknown }) => void; showConfirm: (title: string, detail: string, buttons: { label: string; value: string }[], cb: (v: string | null) => void) => void;
  stale: (m: { rid?: unknown }) => boolean; fireTimers: () => number; settle: () => void; resolveTo: (sid: string) => void; route: (m: { rid?: unknown }) => string;
  adopt: (sid: string) => void; orphans: () => string[];
  // round ten: the hand-off's two halves (the real take arrow and adoptSessionState), an upload in flight and its held send, the kernel's ack (the real droppedPath branch)
  take: (sid: string) => any; adoptState: (sid: string, st: unknown) => void; ship: (id: string, name: string, shipId: string, b64?: string, kind?: "composer" | "comment") => void; holdSend: (id: string) => boolean;
  ships: () => Record<string, Ship[]>; heldSend: () => string[]; ack: (m: Record<string, unknown>) => void; shipFail: (name: string, shipId: string) => void;   // shipFail: the FileReader failed on it (round eleven)
  // round twelve: the shell's session question and the column's reason, the close question, a mini comment box, the strip as last seen, a host detach, the local socket's edges
  sessionBusy: (sid: string) => boolean; busyWhy: () => string; askClose: () => void; openComment: (text: string) => void; comment: () => string | null; closeComment: () => void;
  strip: (ids: string[]) => void; detach: (host: string) => void; wsdown: () => void; wsup: () => void;
  setSets: (sets: Record<string, string[]>) => void; reclaim: () => void;   // round thirteen: the shell's sets as they stand, and renderTabs's reclaim of the handed-off marker
  heading: (sid: string) => string;   // round fourteen: the held strip's heading, its count
  unverified: (sid: string) => boolean; removeFile: (id: string, idx: number) => void;   // round twenty-one
  rollback: (sid: string, stash: Record<string, unknown>) => void;   // round twenty-two
  legacyFor: (name: string) => string | undefined;   // round sixteen: the ship a legacy (untagged) answer names, by the saved name
  shipUnposted: (id: string, name: string, shipId: string, b64?: string, kind?: "composer" | "comment") => void; post: (id: string, shipId: string) => void;   // round eighteen: the post boundary
  draft: (sid: string, text: string) => void;   // round fifteen: a session's draft, written as the box's stash would
  held: { stage: (id: string, text: string, cites?: unknown[]) => void; cite: (id: string, chips?: unknown[]) => void; attach: (id: string) => void; staged: () => Record<string, unknown[]>; citations: () => Record<string, unknown>; files: () => Record<string, unknown>; entries: () => Record<string, unknown>; drafts: () => Record<string, string> };
  busy: () => boolean; answer: (v: string | null) => void; confirm: () => { title: string; buttons: string[]; key: string | null } | null;
  overlays: () => number; clickButton: (label: string) => boolean; rid: () => string | null;
  type: (t: string) => void; composer: () => string; picker: () => { open: boolean; search: string; dir: string }; state: () => State;
};

// the source pane's half of the hand-off is an arrow on window, not a function: sliced whole (assigned onto the harness's window)
const TAKE = (() => { const i = RENDER.indexOf("(window as any).__rompTakeSessionState = "); assert.ok(i >= 0, "the take arrow"); return RENDER.slice(i, RENDER.indexOf("\n};\n", i) + 4); })();
// the kernel's upload ack is a branch of the message switch: sliced and wrapped, so the test runs the real attach + held-send release
// a one-line arrow assigned on window (the shell's questions): sliced whole, "" on an older render.ts
const winLine = (name: string): string => { const i = RENDER.indexOf(`(window as any).${name} = `); return i >= 0 ? RENDER.slice(i, RENDER.indexOf("\n", i) + 1) : ""; };
const ON_DROPPED = (() => { const i = RENDER.indexOf('if (m.type === "droppedPath" && typeof m.path === "string")'); const j = RENDER.indexOf('} else if (m.type === "dropSaveFailed"', i); assert.ok(i >= 0 && j > i, "the droppedPath branch"); return "function onDroppedPath(m: any): void {\n" + RENDER.slice(i, j + 1) + "\n}\n"; })();

function world(o: { activeId: string | null; mru: string[]; order: string[]; nextActive: string | null; store?: Record<string, unknown>; session?: Record<string, string>; sets?: Record<string, string[]> | null }): { api: Api; HOOKS: Hooks; store: Record<string, unknown>; session: Record<string, string> } {
  const store: Record<string, unknown> = o.store ?? {};
  const session: Record<string, string> = o.session ?? {};   // the page's sessionStorage (the reload notices ride it)
  const HOOKS: Hooks = { posts: [], boot: [], sent: [], seq: [], confirms: [], pickers: 0, persisted: 0, timers: [], cleared: 0, toasts: [], answered: [], claims: [], fired: 0, reloadEnded: 0, closeSplit: [] };
  const win = { parent: { postMessage(m: Record<string, unknown>) { HOOKS.posts.push(m); if (m.romp === "colBusy") HOOKS.seq.push("flip:" + m.busy); if (m.romp === "colEmpty") HOOKS.seq.push("empty"); },
                          __rompCloseSplit(n: number) { HOOKS.closeSplit.push(n); } },
                __rompReload: { ended() { HOOKS.reloadEnded++; } } };   // the reload core's ending-event door, counted (round eleven)
  const js = requireCjs("esbuild").transformSync(
    [lineOpt("columnBusy"), fn("syncColumnBusy"), fn("dropProvisional"), fn("openProvisional"), fn("cancelProvisional"), fn("failProvisional"),
     fn("onCreateDirMissing"), fnOpt("dirWhy"), fnOpt("dismissDirPromptForPicker"), fn("closePicker"), fn("startCreate"), fn("closeConfirm"), fn("closeTabLocally"),
     fn("showConfirm"), fnOpt("onCreateWarn"), lineOpt("createReplyIsStale"), lineOpt("mintRid"),
     fn("persistDrafts").replace("function persistDrafts(", "function persistDraftsReal("), fnOpt("restoreFailedProvisionals"),
     fnOpt("bootComposerState"), fnOpt("announceColumnBusy"), lineOpt("retireRid"), fnOpt("finishBoot"), fnOpt("routeCreateReply"), lineOpt("rememberSettled"), fn("resolveProvisionalToExisting"),
     fn("adoptProvisional"), fnOpt("moveProvisionalState"), fn("orphanStateSids"), lineOpt("heldHere"),
     fnOpt("mergeCitations"), fn("addPendingShip"), fn("shipSafeName"), fn("shipOwner"), fn("retirePendingShip"), fn("endReloadHoldIfIdle"), fn("addComposerFile"), fn("adoptSessionState"), TAKE, ON_DROPPED,
     fnOpt("shipFailed"), fnOpt("sendHeldFor"), fn("flushStaged"), fn("routeUserMessage"), fn("noteOrphanState"),
     fnOpt("shipRecord"), fnOpt("retainShipBytes"), fnOpt("failShipsOfHost"), fnOpt("columnBusyWhy"), fnOpt("askCloseUpload"), fnOpt("abandonPendingUploads"), fn("reshipPendingUploads"), fn("noteColumnEmptiness"),
     fnOpt("composerShips"), lineOpt("reclaimHandedOff"), fnOpt("legacyShipFor"), lineOpt("legacyNameOf"), fnOpt("uploadingHeading"), fnOpt("postShipFrame"), fnOpt("noteAmbiguity"),
     lineOpt("isUnverified"), lineOpt("markLegacyFile"), lineOpt("unmarkLegacyFile"), lineOpt("dropLegacyMarks"), lineOpt("moveLegacyMarks"), fnOpt("armHold"), fnOpt("disarmUnverified"), fn("removeComposerFile"),
     lineOpt("filePaths"), fnOpt("fileEntriesOf"), fnOpt("restoreComposerAfterRefusedRescind"), fnOpt("citeKey"),   /* noteAmbiguity: gone since round nineteen; lifted when an older render.ts (780e439e) still has it, so the fail-before run reads clean */
     winLine("__rompSessionBusy"), winLine("__rompColumnBusyWhy")].join("\n"),
    { loader: "ts" }).code;
  const prelude = `
    const { provisionalName, mintProvisionalId, isProvisionalId, isSubId, columnHolds, columnEmptiness, StagedStack, HOOKS, STORE, takeReloadNotices, quoteReplyBody, stagedPosts, isCitationShape } = W;
    let tabOrderSeen = true;   // the board has been heard: the orphan offer speaks (round eleven)
    let lastStripIds = W.order.slice(); let boardLive = new Set(); const hostsSeen = new Set([""]); let colEmptyPosted = false;   // the strip as last judged (round twelve): the world's order, every member listed, the local host heard
    const handedOff = new Set(); let wsIsUp = true; const hostOf = (sid) => { const i = String(sid).indexOf(":"); return i > 0 ? String(sid).slice(0, i) : ""; };
    let CMTBOX = null; const cmtShippedImgs = [];   // the mini comment box: #cmt-pop answers querySelector with it while open; the echo's thumbnail list
    const lastSent = new Map(), draftStartedAt = new Map(); const hostIsDown = () => false; const previewKind = (p) => (/\.(png|jpe?g|gif|webp)$/i.test(String(p)) ? "img" : "file");
    const ephemeralWarnToast = (t) => { HOOKS.toasts.push(t); };
    const COL = "2"; let colSets = W.sets;   // this page: a later column, whose set the shell answers (round nine: the orphan enumeration reads it)
    const claimSession = (sid) => { HOOKS.claims.push(sid); }; const mintQid = () => "q-1"; const registerOptimistic = () => {};
    const renderComposerChips = () => {}; const renderComposerFiles = () => {}; const renderStagedStrip = () => {};
    const sessionStorage = { getItem: (k) => (k in W.SESSION ? W.SESSION[k] : null), setItem: (k, v) => { W.SESSION[k] = String(v); }, removeItem: (k) => { delete W.SESSION[k]; } };
    let provisionalId = null, provisionalTags = [], pendingNewSession = null, provisionalTimer = undefined, dirQuestionFor = null, pendingCarry = "", dirQuestion = false;
    let columnBusyTold = false, lastCreate = null, pickMode = false, activeId = W.activeId, confirmCb = null, confirmKey = null, provisionalRid = null;
    const failedWhy = new Map(); const failedInfo = new Map(); let wantActiveGone = W.wantActiveGone; const supersededRids = []; const settledRids = new Map(); let pendingCreate = null;
    const RELOADED_WHY = "The page reloaded while this session was being created. Start it again from the session picker, or discard this tab with its ✕.";
    const pendingShips = new Map(); let stagedMsgs; const composerCitations = new Map(), composerFiles = new Map();   // stagedMsgs: created in the epilogue, in PRODUCTION order relative to the boot
    const sendOnShip = new Set(); let shipGateSid = null; const fireHeldSend = () => { HOOKS.fired++; }; let shipOrder = 0, postOrder = 0; const legacyFiles = new Map(); const UNVERIFIED_NOTICE = "An attachment from an older kernel is on this message, so it can't be sent automatically — check it and send it yourself.";   // the upload gate's stores; the held send's release, counted; the posts' counter (round eighteen) — and the creation counter an older render.ts (5818185b) still increments, so the fail-before run reads clean
    const provisionalQueue = []; const failedProvisionals = new Set(); const pendingSent = new Map(); const sessions = new Map(); const closingTabs = new Map();
    // the per-column state store the real page reads at boot (vscodeApi.getState) and writes on every draft change (setState replaces it)
    const vscodeApiState = { getState: () => STORE, setState: (s) => { for (const k of Object.keys(STORE)) delete STORE[k]; Object.assign(STORE, s); } };
    const drafts = new Map();   // filled by the REAL boot (bootComposerState), below
    const order = W.order.slice(); const mru = W.mru.slice();
    const PROVISIONAL_WAIT_MS = 90000;
    const EL = { "composer-input": { value: "", focus() {} }, picker: { style: { display: "none" } }, "picker-search": { value: "" }, "picker-dir": { value: "", focus() {}, select() {} } };
    // a mini DOM for the REAL dialog (showConfirm / closeConfirm): elements with an id, children, listeners; #confirm found by walking the body
    const mk = (tag, cls) => { const n = { tagName: tag, className: cls || "", id: "", textContent: "", children: [], parent: null, handlers: {}, dataset: {}, _key: undefined,
      appendChild(c) { c.parent = n; n.children.push(c); return c; },
      remove() { if (n.parent) { const i = n.parent.children.indexOf(n); if (i >= 0) n.parent.children.splice(i, 1); n.parent = null; } },
      addEventListener(t, f) { (n.handlers[t] = n.handlers[t] || []).push(f); }, click() { (n.handlers.click || []).forEach((f) => f({ target: n })); },
      get firstElementChild() { return n.children[0] || null; }, focus() {} }; return n; };
    const body = mk("body", ""); const findId = (node, id) => { if (node.id === id) return node; for (const c of node.children) { const r = findId(c, id); if (r) return r; } return null; };
    const document = { body, getElementById: (id) => (id === "cmt-pop" ? (CMTBOX ? { querySelector: () => CMTBOX } : null) : (EL[id] || findId(body, id))), addEventListener() {}, removeEventListener() {} };
    const el = (tag, cls) => mk(tag, cls);
    const warnToast = (t) => { HOOKS.toasts.push(t); };
    const vscodeApi = { postMessage: (m) => { HOOKS.sent.push(m); }, ...vscodeApiState };
    const renderTabs = () => {}; const growComposer = () => {};
    // the real setActive swaps the box: the leaving tab's text to its draft, the arriving tab's draft into the box
    const setActive = (id) => { if (activeId && activeId !== id && EL["composer-input"].value) drafts.set(activeId, EL["composer-input"].value); activeId = id; EL["composer-input"].value = drafts.get(id) ?? ""; };
    // the HELD column: once the listed member is gone nothing is held here, so a dismissed tab leaves the box unbound (focusAfterDismiss); an ordinary column reselects (W.nextActive)
    const dismissSession = (id) => { sessions.delete(id); const i = order.indexOf(id); if (i >= 0) order.splice(i, 1); const j = mru.indexOf(id); if (j >= 0) mru.splice(j, 1); drafts.delete(id); persistDrafts(); if (activeId === id) activeId = W.nextActive; };   // the real "close" branch persists
    const persistDrafts = () => { HOOKS.persisted++; HOOKS.seq.push("persist"); persistDraftsReal(); }; const loadComposerFor = () => {}; const stashActiveDraft = () => {};
    const createDirPrompt = () => "the folder question"; const askDirComplete = () => {};
    // the real openPicker's first act (lifted), then the picker
    const openPicker = () => { if (typeof dismissDirPromptForPicker === "function") dismissDirPromptForPicker(); EL.picker.style.display = "block"; HOOKS.pickers++; };
    const rememberDir = () => {}; const signalPickerOverlay = () => {}; const syncComposerPh = () => {};
    const setTimeout = (f) => { HOOKS.timers.push(f); return HOOKS.timers.length; }; const clearTimeout = () => { HOOKS.cleared++; };
  `;
  const epilogue = `
    // THE BOOT, in production's order: stagedMsgs is created and restored, then the composer's state (drafts, files, citations,
    // the failed creates with their orphan sweep, the lost ships), then the busy baseline — the real functions. On a render.ts
    // from before round seven (the fail-before run) the failed-create restore ran BEFORE stagedMsgs existed: that order is
    // reproduced here, and its store rewrite fails exactly as production's did
    if (typeof bootComposerState === "function") { stagedMsgs = new StagedStack(); try { stagedMsgs.restore(STORE.staged); } catch (e) { /* */ } if (typeof finishBoot === "function") finishBoot(); else { bootComposerState(); announceColumnBusy(); } }
    else { for (const [k, v] of Object.entries((STORE.drafts && typeof STORE.drafts === "object") ? STORE.drafts : {})) drafts.set(k, v); if (typeof restoreFailedProvisionals === "function") restoreFailedProvisionals(); stagedMsgs = new StagedStack(); try { stagedMsgs.restore(STORE.staged); } catch (e) { /* */ } }
    HOOKS.boot = HOOKS.posts.splice(0); HOOKS.seq.length = 0;   // what the boot said (the busy baseline) is read apart from what the page says afterwards
    const overlay = () => findId(body, "confirm");
    return {
      startCreate, onCreateDirMissing, closePicker, openPicker, cancelProvisional, closeTabLocally, showConfirm,
      onCreateWarn: (m) => { if (typeof onCreateWarn === "function") onCreateWarn(m); else { if (provisionalId) failProvisional(m.text); else warnToast(m.text); } },
      busy: () => (typeof columnBusy === "function" ? columnBusy() : (!!provisionalId || failedProvisionals.size > 0)),
      answer: (v) => { closeConfirm(v); },
      // the dialog up, read off the real overlay: its title, its buttons' labels, what it is about
      confirm: () => { const o = overlay(); if (!o) return null; const box = o.children[0]; return { title: box.children[0].textContent, buttons: box.children[2].children.map((b) => b.textContent), key: confirmKey }; },
      overlays: () => body.children.filter((c) => c.id === "confirm").length,
      clickButton: (label) => { const o = overlay(); const b = o && o.children[0].children[2].children.find((x) => x.textContent === label); if (b) b.click(); return !!b; },
      rid: () => provisionalRid,
      stale: (m) => (typeof createReplyIsStale === "function" ? createReplyIsStale(m) : false),
      settle: () => { dropProvisional(); syncColumnBusy(); },   // a settlement that is not a cancel (the focus / the session's frame adopting): the request is NOT superseded
      resolveTo: (sid) => resolveProvisionalToExisting(sid),     // the real settlement onto a running session (remembers the request as settled)
      adopt: (sid) => adoptProvisional(sid),                     // the real settlement onto the session the create made
      orphans: () => orphanStateSids(),                          // what this page would hand the shell at a close (the sids it holds state for and does not show)
      take: (sid) => window.__rompTakeSessionState(sid),         // the shell's close(): this page's state for a session, taken whole (round ten: the real arrow)
      adoptState: (sid, st) => adoptSessionState(sid, st),       // the receiving pane's half
      // a file picked: the chip is up, the bytes retained (through the real retention when it exists) and — with bytes — the frame POSTED (the real post when it exists, round eighteen)
      ship: (id, name, shipId, b64, kind) => { addPendingShip(id, name, shipId, kind || "composer"); if (b64) { if (typeof retainShipBytes === "function") retainShipBytes(id, shipId, b64); else pendingShips.get(id).find((p) => p.shipId === shipId).b64 = b64; if (typeof postShipFrame === "function") postShipFrame(id, pendingShips.get(id).find((p) => p.shipId === shipId)); } },
      shipUnposted: (id, name, shipId, b64, kind) => { addPendingShip(id, name, shipId, kind || "composer"); if (b64) { if (typeof retainShipBytes === "function") retainShipBytes(id, shipId, b64); else pendingShips.get(id).find((p) => p.shipId === shipId).b64 = b64; } },   // still encoding: no frame out
      post: (id, shipId) => { postShipFrame(id, pendingShips.get(id).find((p) => p.shipId === shipId)); },   // the reader finished: the frame leaves the page
      holdSend: (id) => { if (typeof armHold === "function") return armHold(id); sendOnShip.add(id); return true; },   // "Wait for the upload" — through the one door when it exists (round twenty-one)
      ships: () => Object.fromEntries([...pendingShips].map(([k, v]) => [k, v.map((p) => ({ name: p.name, shipId: p.shipId, ...(p.b64 ? { b64: p.b64 } : {}) }))])),
      heldSend: () => [...sendOnShip],
      ack: (m) => onDroppedPath(m),                              // the kernel's droppedPath, through the real branch
      shipFail: (name, shipId) => shipFailed(name, shipId, name + " could not be read, so it was not attached — try again."),   // the reader's failure path (round eleven)
      sessionBusy: (sid) => window.__rompSessionBusy(sid), busyWhy: () => columnBusyWhy(), askClose: () => askCloseUpload(),
      openComment: (text) => { CMTBOX = { value: text, dispatchEvent() {}, focus() {} }; }, comment: () => (CMTBOX ? CMTBOX.value : null), closeComment: () => { CMTBOX = null; },
      strip: (ids) => { lastStripIds = ids.slice(); noteColumnEmptiness(ids); },   // renderTabs's judgement of the kernel's strip
      detach: (host) => failShipsOfHost(host, "was still uploading when " + host + " was detached, so it was not attached — attach it again once the host is back."),   // what the romp:hostDetached listener does (pinned in chat-split.test.ts)
      wsdown: () => { wsIsUp = false; }, wsup: () => { wsIsUp = true; reshipPendingUploads(); },   // the shim's edges, as the page's listeners read them
      setSets: (s) => { colSets = s; }, reclaim: () => reclaimHandedOff(),   // what renderTabs does first: reads the sets, reclaims the marker for a sid shown here again
      heading: (sid) => uploadingHeading(sid),
      unverified: (sid) => (typeof isUnverified === "function" ? isUnverified(sid) : false), removeFile: (id, idx) => removeComposerFile(id, idx),   // round twenty-one: the mark, and the user's ✕ on a chip
      rollback: (sid, stash) => restoreComposerAfterRefusedRescind(sid, stash),   // round twenty-two: the refused rescind's restore, with the stash as the press left it
      legacyFor: (name) => { const p = legacyShipFor(name, ""); const q = p && p.ship ? p.ship : p; return q ? q.shipId : undefined; },   // what the nack branch does with an untagged local name (rounds sixteen, seventeen, nineteen; an older render.ts answered { ship, matches })
      draft: (sid, text) => { drafts.set(sid, text); persistDrafts(); },
      route: (m) => (typeof routeCreateReply === "function" ? routeCreateReply(m).kind : "?"),
      // (each persists, as the page's own staging / citing / attaching does)
      held: { stage: (id, text, cites) => { stagedMsgs.push(id, { text, cites: cites || [] }); persistDrafts(); }, cite: (id, chips) => { composerCitations.set(id, chips || [{ title: "a card", itemId: "g1" }]); persistDrafts(); }, attach: (id) => { composerFiles.set(id, typeof filePaths === "function" ? [{ path: "/tmp/a.png", legacy: false }] : ["/tmp/a.png"]); persistDrafts(); },
              staged: () => stagedMsgs.entries(), citations: () => Object.fromEntries(composerCitations), files: () => Object.fromEntries([...composerFiles].map(([k, v]) => [k, v.map((e) => (typeof e === "string" ? e : e.path))])), entries: () => Object.fromEntries(composerFiles), drafts: () => Object.fromEntries(drafts) },
      fireTimers: () => { const t = HOOKS.timers.splice(0); for (const f of t) f(); return t.length; },
      type: (t) => { EL["composer-input"].value = t; }, composer: () => EL["composer-input"].value,
      picker: () => ({ open: EL.picker.style.display !== "none", search: EL["picker-search"].value, dir: EL["picker-dir"].value }),
      state: () => ({ provisionalId, dirQuestionFor, failed: [...failedProvisionals], activeId, drafts: Object.fromEntries(drafts), sessions: [...sessions.keys()], timer: provisionalTimer !== undefined, why: Object.fromEntries(failedWhy) }),
    };
  `;
  const make = new Function("W", "window", prelude + js + epilogue) as (w: unknown, win: unknown) => Api;
  const api = make({ provisionalName, mintProvisionalId, isProvisionalId, isSubId, columnHolds, columnEmptiness, StagedStack, HOOKS, STORE: store, SESSION: session, takeReloadNotices, quoteReplyBody, stagedPosts, isCitationShape, sets: o.sets === undefined ? { "2": [C] } : o.sets, activeId: o.activeId, mru: o.mru, order: o.order, nextActive: o.nextActive, wantActiveGone: null }, win);
  return { api, HOOKS, store, session };
}
const flips = (h: Hooks, busy: boolean) => h.posts.filter((p) => p.romp === "colBusy" && p.busy === busy).length;
const last = (h: Hooks) => h.posts[h.posts.length - 1];

// a create from the picker in a column showing C, text typed into the provisional tab's box, then the kernel's folder question
function asked(o: Partial<Parameters<typeof world>[0]> = {}) {
  const w = world({ activeId: C, mru: [C, A], order: [A, B, C], nextActive: null, ...o });
  w.api.startCreate(REQ);
  const id = w.api.state().provisionalId!;
  assert.ok(id && isProvisionalId(id), "a provisional tab"); assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, true), 1);
  w.api.type(TYPED);
  w.api.onCreateDirMissing({ name: REQ.name, dir: REQ.dir, status: { canCreate: true } });
  return { w, id };
}

test("the folder question keeps the provisional TAB: its text in its box, the column busy by that tab alone, no flip, the backstop stood down", () => {
  const { w, id } = asked();
  const st = w.api.state();
  assert.equal(st.provisionalId, id, "the tab stays: the create in flight"); assert.ok(st.sessions.includes(id)); assert.equal(st.activeId, id);
  assert.equal(w.api.composer(), TYPED, "its text where it was typed"); assert.deepEqual(st.drafts, {}, "carried nowhere");
  assert.equal(st.dirQuestionFor, id, "the question is this create's"); assert.equal(st.timer, false, "the kernel answered: the wait is the user's");
  assert.deepEqual(w.api.confirm(), { title: "That folder isn't there", buttons: ["Create it and start", "Edit the path"], key: "dir:" + id }, "the prompt, keyed to the create (no request id on this reply: the tab's)");
  assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, false), 0, "no colBusy:false — a held column stands under the prompt");
});

test("dismissed (Escape, the backdrop): a FAILED create — the text in its own box and under its own id, no other session's draft touched, busy stays, no flip; the ✕ discards and flips", () => {
  const { w, id } = asked();
  w.api.answer(null);
  const st = w.api.state();
  assert.equal(st.provisionalId, null); assert.deepEqual(st.failed, [id], "a failed create now"); assert.equal(st.dirQuestionFor, null);
  assert.deepEqual(st.drafts, { [id]: TYPED }, "the text under the failed tab's own id and nowhere else"); assert.equal(w.api.composer(), TYPED); assert.equal(st.activeId, id, "shown, in place");
  assert.equal(w.api.confirm()?.title, "Couldn't start notes", "said, as for any failed create"); assert.equal(w.api.overlays(), 1);
  assert.equal(w.api.busy(), true, "busy: the failed tab holds the text"); assert.equal(flips(w.HOOKS, false), 0);
  w.api.closeTabLocally(id);   // the user's ✕: the one discard
  assert.deepEqual(w.api.state().failed, []); assert.deepEqual(w.api.state().drafts, {});
  assert.equal(w.api.busy(), false); assert.equal(flips(w.HOOKS, false), 1); assert.deepEqual(last(w.HOOKS), { romp: "colBusy", busy: false }, "the flip, last");
});

test("a sub-agent viewer active when the create started: dismissed, the text is in the failed tab and nothing is written under the viewer's id or any session's", () => {
  const { w, id } = asked({ activeId: VIEWER, mru: [VIEWER, C], nextActive: VIEWER });
  w.api.answer(null);
  assert.deepEqual(w.api.state().drafts, { [id]: TYPED }); assert.deepEqual(w.api.state().failed, [id]); assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, false), 0);
});

test("an ordinary column (not held): the same — the failed tab holds the text; it is never appended to the tab the column falls back to", () => {
  const { w, id } = asked({ nextActive: C });
  w.api.answer(null);
  assert.deepEqual(w.api.state().drafts, { [id]: TYPED }, "not C's draft"); assert.equal(w.api.state().drafts[C], undefined); assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, false), 0);
});

test("Create it and start: the retry on the SAME tab — the same create with mkdir, the text where it was, the backstop armed again; that create's settlement flips", () => {
  const { w, id } = asked();
  const timers = w.HOOKS.timers.length;
  w.api.answer("create");
  const creates = w.HOOKS.sent.filter((m) => m.type === "createSession");
  assert.equal(creates.length, 2); assert.equal(creates[1].mkdir, true, "the very same create, with mkdir");
  const st = w.api.state();
  assert.equal(st.provisionalId, id, "one tab, one create"); assert.deepEqual(st.sessions.filter(isProvisionalId), [id]); assert.equal(w.api.composer(), TYPED);
  assert.equal(st.dirQuestionFor, null, "the question is answered"); assert.equal(st.timer, true); assert.equal(w.HOOKS.timers.length, timers + 1, "the backstop, armed again");
  assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, false), 0);
  w.api.cancelProvisional();   // one settlement (the ✕ on a pending tab)
  assert.equal(w.api.busy(), false); assert.equal(flips(w.HOOKS, false), 1); assert.deepEqual(last(w.HOOKS), { romp: "colBusy", busy: false });
});

test("Edit the path: the tab stays and the picker is prefilled to retry it; the same name created from there is the retry; the picker closed with no create dismisses it into a failed tab", () => {
  const a = asked();
  a.w.api.answer("edit");
  assert.deepEqual(a.w.api.picker(), { open: true, search: REQ.name, dir: REQ.dir }); assert.equal(a.w.api.state().provisionalId, a.id, "the tab stays"); assert.equal(a.w.api.state().dirQuestionFor, a.id);
  assert.equal(a.w.api.busy(), true); assert.equal(flips(a.w.HOOKS, false), 0);
  a.w.api.startCreate({ ...REQ, dir: "/proj/there" });   // the path edited, the same name: the retry
  assert.equal(a.w.api.state().provisionalId, a.id, "the same tab"); assert.equal(a.w.api.composer(), TYPED); assert.equal(a.w.api.state().dirQuestionFor, null); assert.equal(a.w.api.picker().open, false);
  assert.equal(a.w.api.busy(), true); assert.equal(flips(a.w.HOOKS, false), 0);
  const b = asked();
  b.w.api.answer("edit");
  b.w.api.closePicker();   // Escape, the backdrop, the toggle: no create came
  assert.deepEqual(b.w.api.state().failed, [b.id], "dismissed: a failed create"); assert.deepEqual(b.w.api.state().drafts, { [b.id]: TYPED }); assert.equal(b.w.api.busy(), true); assert.equal(flips(b.w.HOOKS, false), 0);
});

test("the picker opened OVER the prompt (Mod+Shift+O) dismisses it first, quietly, as its own create's; a second create's question then settles only itself; no flip until both are discarded", () => {
  const { w, id: id1 } = asked();
  w.api.openPicker();
  assert.deepEqual(w.api.state().failed, [id1], "the first create: a failed tab, its text kept"); assert.deepEqual(w.api.state().drafts, { [id1]: TYPED });
  assert.equal(w.api.overlays(), 0, "quietly: no dialog — the picker the user asked for is the foreground"); assert.equal(w.api.confirm(), null);
  assert.match(w.api.state().why[id1] || "", /^That folder isn't there/, "…the tab's own placeholder says why");
  assert.equal(w.api.picker().open, true); assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, false), 0);
  w.api.startCreate({ ...REQ, name: "notes-2", dir: "/proj/also-missing" });
  const id2 = w.api.state().provisionalId!;
  assert.ok(id2 && id2 !== id1, "a second create, its own tab"); assert.equal(w.api.composer(), "", "nothing carried: the first create's text stays in its failed tab");
  w.api.type("the second note");
  w.api.onCreateDirMissing({ name: "notes-2", dir: "/proj/also-missing", status: { canCreate: true } });
  assert.deepEqual(w.api.confirm(), { title: "That folder isn't there", buttons: ["Create it and start", "Edit the path"], key: "dir:" + id2 }, "the second question, keyed to the second create");
  assert.equal(w.api.state().provisionalId, id2); assert.deepEqual(w.api.state().failed, [id1]); assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, false), 0, "busy throughout");
  w.api.answer(null);
  assert.deepEqual(w.api.state().failed, [id1, id2]); assert.deepEqual(w.api.state().drafts, { [id1]: TYPED, [id2]: "the second note" });
  w.api.closeTabLocally(id1);
  assert.equal(w.api.busy(), true, "the second failed tab still holds text"); assert.equal(flips(w.HOOKS, false), 0);
  w.api.closeTabLocally(id2);
  assert.equal(w.api.busy(), false); assert.equal(flips(w.HOOKS, false), 1);
});

test("an older prompt a newer create's dialog cancels settles nothing: the second create stands, the first's text came along into its box", () => {
  const { w, id: id1 } = asked();
  w.api.startCreate({ ...REQ, name: "notes-2", dir: "/proj/also-missing" });   // a second create straight away, the first prompt still up: it supersedes the first (and takes its text)
  const id2 = w.api.state().provisionalId!;
  assert.ok(id2 !== id1); assert.equal(w.api.composer(), TYPED, "the superseded create's text, in the new tab's box"); assert.deepEqual(w.api.state().failed, []);
  w.api.onCreateDirMissing({ name: "notes-2", dir: "/proj/also-missing", status: { canCreate: true } });   // its dialog cancels the first prompt first
  assert.equal(w.api.state().provisionalId, id2, "the first prompt's cancel settled nothing"); assert.deepEqual(w.api.state().failed, []); assert.equal(w.api.state().dirQuestionFor, id2);
  assert.deepEqual(w.api.confirm(), { title: "That folder isn't there", buttons: ["Create it and start", "Edit the path"], key: "dir:" + id2 });
  assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, false), 0);
});

test("round five: a create's request id rides the request; a late reply naming a superseded create is ignored, the current create untouched", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null });
  w.api.startCreate(REQ);
  const sentA = w.HOOKS.sent.filter((m) => m.type === "createSession")[0];
  assert.equal(typeof sentA.rid, "string", "every attempt carries a request id"); assert.equal(w.api.rid(), sentA.rid, "the pending tab waits on it");
  const idA = w.api.state().provisionalId!;
  w.api.type("for A, on a slow host");
  w.api.openPicker(); w.api.startCreate({ ...REQ, name: "notes-b", dir: "/proj/also-not-there" });   // A superseded before its host answered (its text comes along)
  const idB = w.api.state().provisionalId!, sentB = w.HOOKS.sent.filter((m) => m.type === "createSession")[1];
  assert.ok(idB !== idA); assert.equal(w.api.rid(), sentB.rid); assert.notEqual(sentB.rid, sentA.rid);
  // A's late folder question: nobody's — no prompt over B, B still pending with its backstop, no question pending
  w.api.onCreateDirMissing({ name: REQ.name, dir: REQ.dir, status: { canCreate: true }, rid: sentA.rid });
  assert.equal(w.api.overlays(), 0, "ignored"); assert.equal(w.api.state().dirQuestionFor, null); assert.equal(w.api.state().provisionalId, idB); assert.equal(w.api.state().timer, true);
  // A's late refusal: nobody's either — B is not failed, nothing toasted
  w.api.onCreateWarn({ text: "the host refused A", rid: sentA.rid });
  assert.equal(w.api.state().provisionalId, idB); assert.deepEqual(w.api.state().failed, []); assert.deepEqual(w.HOOKS.toasts, []); assert.equal(flips(w.HOOKS, false), 0);
  // B's own question: B's prompt, keyed to B's request
  w.api.onCreateDirMissing({ name: "notes-b", dir: "/proj/also-not-there", status: { canCreate: true }, rid: sentB.rid });
  assert.deepEqual(w.api.confirm(), { title: "That folder isn't there", buttons: ["Create it and start", "Edit the path"], key: "dir:" + sentB.rid }); assert.equal(w.api.state().dirQuestionFor, idB);
  // …and after the retry (a new request id) A's — or the first attempt's — late question is stale too
  w.api.answer("create");
  const sentB2 = w.HOOKS.sent.filter((m) => m.type === "createSession")[2];
  assert.notEqual(sentB2.rid, sentB.rid); assert.equal(w.api.rid(), sentB2.rid); assert.equal(sentB2.mkdir, true);
  w.api.onCreateDirMissing({ name: "notes-b", dir: "/proj/also-not-there", status: { canCreate: true }, rid: sentB.rid });
  assert.equal(w.api.overlays(), 0, "the first attempt's late question: ignored"); assert.equal(w.api.state().dirQuestionFor, null);
});

test("round five: a reply WITHOUT a request id (an older kernel) is read as today — the current create's", () => {
  const { w, id } = asked();
  assert.equal(w.api.overlays(), 1, "the folder question landed though it named no request");
  w.api.answer("create");
  w.api.onCreateWarn({ text: "the kernel said no" });   // no rid: the current create's verdict
  assert.deepEqual(w.api.state().failed, [id]); assert.equal(w.api.state().why[id], "the kernel said no");
});

test("round five: an unrelated dialog replacing the folder question leaves ONE #confirm — the newer, working on its first click — and the create is a failed tab with its text, its reason on the tab", () => {
  const { w, id } = asked();
  assert.equal(w.api.overlays(), 1);
  let delivered = null;
  w.api.showConfirm("That action was not delivered", "the kernel could not take it", [{ label: "Dismiss", value: "ok" }], (v) => { delivered = v; });
  assert.equal(w.api.overlays(), 1, "never two #confirm"); assert.equal(w.api.confirm()?.title, "That action was not delivered", "the newer dialog is the one up");
  assert.deepEqual(w.api.state().failed, [id], "the folder question's create: a failed tab"); assert.deepEqual(w.api.state().drafts, { [id]: TYPED }, "its text kept");
  assert.match(w.api.state().why[id] || "", /^That folder isn't there/, "the reason on the tab, not in a second dialog"); assert.equal(w.api.busy(), true); assert.equal(flips(w.HOOKS, false), 0);
  assert.equal(w.api.clickButton("Dismiss"), true);
  assert.equal(delivered, "ok", "the visible dialog's own callback ran on the first click"); assert.equal(w.api.overlays(), 0, "…and it is gone"); assert.equal(w.api.confirm(), null);
});

// ---- round six ----
test("round six: a reply naming a request is stale ONLY while a different create is pending — with none pending it is main's: the toast", () => {
  // a namesake with tags: the kernel's focus settles the tab, then warns that the tags were not changed — that warning must reach the user
  const a = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: C });
  a.api.startCreate(REQ); const ridA = a.api.rid()!;
  a.api.settle();   // the settlement (the focus / the session's frame adopts): no create pending — a ✕ would retire the request instead (round seven)
  assert.equal(a.api.stale({ rid: ridA }), false, "no create pending: nothing is stale");
  a.api.onCreateWarn({ text: '"notes" is already running; its tags were not changed', rid: ridA });
  assert.deepEqual(a.HOOKS.toasts, ['"notes" is already running; its tags were not changed'], "main's path: the toast, not dropped");
  // …while a DIFFERENT create is pending, the first's late warning IS stale
  const b = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null });
  b.api.startCreate(REQ); const rid1 = b.api.rid()!;
  b.api.openPicker(); b.api.startCreate({ ...REQ, name: "notes-2" });
  assert.equal(b.api.stale({ rid: rid1 }), true); assert.equal(b.api.stale({ rid: b.api.rid()! }), false); assert.equal(b.api.stale({}), false, "no id: never stale");
  b.api.onCreateWarn({ text: "late", rid: rid1 }); assert.deepEqual(b.HOOKS.toasts, [], "dropped: another create is pending");
});

test("round six: after the backstop failed the tab on the generic reason, the host's late authoritative warning is toasted AND becomes the tab's reason", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: C });
  w.api.startCreate(REQ); const rid = w.api.rid()!; const id = w.api.state().provisionalId!;
  w.api.type(TYPED);
  assert.equal(w.api.fireTimers(), 1, "the 90 s backstop");
  assert.deepEqual(w.api.state().failed, [id]); assert.equal(w.api.state().why[id], "romp asked to start it, but nothing came back.");
  w.api.onCreateWarn({ text: "late authoritative detail", rid });
  assert.deepEqual(w.HOOKS.toasts, ["late authoritative detail"], "the toast path (provisional.test.ts describes it; this runs it)");
  assert.equal(w.api.state().why[id], "late authoritative detail", "the tab's reason is the authoritative one now");
  assert.equal((w.store.failed as any)[id].why, "late authoritative detail", "…persisted with the tab");
});

test("round six: a failed create survives a reload — the tab is back with its text and reason, busy; its ✕ clears record and draft; an orphan new-* draft is dropped", () => {
  const store: Record<string, unknown> = {};
  const { w, id } = (() => { const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store }); w.api.startCreate(REQ); const id = w.api.state().provisionalId!; w.api.type(TYPED);
    w.api.onCreateDirMissing({ name: REQ.name, dir: REQ.dir, status: { canCreate: true } }); return { w, id }; })();
  const rid = w.api.rid();
  w.api.answer(null);   // dismissed: a failed create
  const rec = (store.failed as any)[id];
  assert.deepEqual(rec, { name: "notes", dir: REQ.dir, why: rec.why, rid }, "the record beside the drafts: name, folder, reason, request"); assert.match(rec.why, /^That folder isn't there/);
  assert.equal((store.drafts as any)[id], TYPED, "the text, under the tab's id");
  (store.drafts as any)["new-orphan-from-an-older-build"] = "reachable by nothing";
  // the page reloads over the same store
  const r = world({ activeId: null, mru: [], order: [A, B, C], nextActive: null, store });
  const st = r.api.state();
  assert.ok(st.sessions.includes(id), "the failed tab is back"); assert.deepEqual(st.failed, [id]); assert.match(st.why[id], /^That folder isn't there/, "…with its reason"); assert.equal(st.drafts[id], TYPED, "…and its text");
  assert.equal(r.api.busy(), true, "busy for the shell, as before the reload");
  assert.equal(st.drafts["new-orphan-from-an-older-build"], undefined, "the orphan draft is dropped"); assert.equal((store.drafts as any)["new-orphan-from-an-older-build"], undefined, "…from the store too");
  r.api.closeTabLocally(id);   // the one discard
  assert.deepEqual(r.api.state().failed, []); assert.equal((store.failed as any)[id], undefined, "the record went"); assert.equal((store.drafts as any)[id], undefined, "…and the draft");
  assert.equal(Object.keys((store.drafts as any) || {}).filter((k) => isProvisionalId(k)).length, 0, "no new-* draft remains");
  assert.equal(r.api.busy(), false);
});

test("round six: a success focus naming a replaced create is stale while another is pending; one naming the pending create, or none at all, is not", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null });
  w.api.startCreate(REQ); const ridA = w.api.rid()!;
  w.api.openPicker(); w.api.startCreate({ ...REQ, name: "notes-b" }); const ridB = w.api.rid()!;
  assert.equal(w.api.stale({ type: "focus", id: "s-a", rid: ridA } as any), true, "A's late success focus: ignored, B keeps the front");
  assert.equal(w.api.stale({ type: "focus", id: "s-b", rid: ridB } as any), false, "B's own focus applies");
  assert.equal(w.api.stale({ type: "focus", id: "s-x" } as any), false, "a focus without a request id (an older kernel) applies");
});

// ---- round seven ----
test("round seven: a failed create is persisted whatever the tab holds — a staged message, a citation, an attachment, or nothing — and comes back after a reload with it", () => {
  for (const kind of ["staged", "citation", "attachment", "empty"] as const) {
    const store: Record<string, unknown> = {};
    const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store });
    w.api.startCreate(REQ); const id = w.api.state().provisionalId!;
    if (kind === "staged") w.api.held.stage(id, "a staged line"); if (kind === "citation") w.api.held.cite(id); if (kind === "attachment") w.api.held.attach(id);
    w.api.onCreateDirMissing({ name: REQ.name, dir: REQ.dir, status: { canCreate: true } });
    w.api.answer(null);
    assert.ok((store.failed as any)?.[id], kind + ": the record is written though no plain draft was typed"); assert.match((store.failed as any)[id].why, /^That folder isn't there/);
    const r = world({ activeId: null, mru: [], order: [A, B, C], nextActive: null, store });
    const st = r.api.state();
    assert.deepEqual(st.failed, [id], kind + ": the tab is back"); assert.match(st.why[id], /^That folder isn't there/, kind + ": with its reason");
    if (kind === "staged") assert.deepEqual((r.api.held.staged()[id] || []).map((m: any) => m.text), ["a staged line"], "the staged message is back, not swept");
    if (kind === "citation") assert.equal((r.api.held.citations()[id] as any[])?.[0]?.title, "a card", "the citation is back, not swept");
    if (kind === "attachment") assert.deepEqual(r.api.held.files()[id], ["/tmp/a.png"], "the attachment is back, not swept");
    r.api.closeTabLocally(id);
    assert.equal((store.failed as any)[id], undefined, kind + ": the ✕ took the record");
  }
});

test("round seven: a superseded request stays stale after the replacing create settles — its focus and warning dropped — while the settled create's own late warning toasts", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: C });
  w.api.startCreate(REQ); const ridA = w.api.rid()!;
  w.api.openPicker(); w.api.startCreate({ ...REQ, name: "notes-b" }); const ridB = w.api.rid()!;
  w.api.settle();   // B lands (the focus / its frame adopts): nothing pending
  assert.equal(w.api.rid(), null);
  assert.equal(w.api.stale({ type: "focus", id: "s-a", rid: ridA } as any), true, "A's tagged focus, late: dropped — B's tab keeps the front (the kernel's push lists the real session in the first column)");
  w.api.onCreateWarn({ text: "A: tags were not changed", rid: ridA }); assert.deepEqual(w.HOOKS.toasts, [], "A's late warning: dropped");
  w.api.onCreateWarn({ text: "B: tags were not changed", rid: ridB }); assert.deepEqual(w.HOOKS.toasts, ["B: tags were not changed"], "B's own late warning: toasted (never superseded)");
  assert.equal(w.api.stale({ type: "focus", id: "s-b", rid: ridB } as any), false);
  // the ✕ on a pending tab retires its request too: a late folder question for it must not land on a later create
  const c = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: C });
  c.api.startCreate(REQ); const ridC = c.api.rid()!; c.api.cancelProvisional(); c.api.startCreate({ ...REQ, name: "notes-d" });
  c.api.onCreateDirMissing({ name: REQ.name, dir: REQ.dir, status: { canCreate: true }, rid: ridC });
  assert.equal(c.api.overlays(), 0, "the cancelled create's late question: nobody's"); assert.equal(c.api.state().dirQuestionFor, null);
});

test("round seven: the boot's orphan sweep REWRITES the store — the composer state restores after stagedMsgs exists, in one real sequence", () => {
  const store: Record<string, unknown> = { drafts: { "new-orphan-from-an-older-build": "reachable by nothing", [C]: "c's draft" }, staged: {} };
  const r = world({ activeId: null, mru: [], order: [A, B, C], nextActive: null, store });
  assert.equal(r.api.state().drafts["new-orphan-from-an-older-build"], undefined, "pruned in memory");
  assert.equal((store.drafts as any)["new-orphan-from-an-older-build"], undefined, "…and on disk: the rewrite ran (before round seven it threw in stagedMsgs's dead zone and was swallowed)");
  assert.equal((store.drafts as any)[C], "c's draft", "the rest of the store is intact");
});

test("round seven: a restored failed tab sets the busy baseline — one colBusy:true at boot, and its ✕ posts exactly one colBusy:false", () => {
  const store: Record<string, unknown> = {};
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store });
  w.api.startCreate(REQ); const id = w.api.state().provisionalId!; w.api.type(TYPED);
  w.api.onCreateDirMissing({ name: REQ.name, dir: REQ.dir, status: { canCreate: true } }); w.api.answer(null);
  const r = world({ activeId: null, mru: [], order: [A, B, C], nextActive: null, store });   // the held column's iframe reloads
  assert.equal(r.api.busy(), true); assert.deepEqual(r.HOOKS.boot.filter((p) => p.romp === "colBusy"), [{ romp: "colBusy", busy: true }], "the baseline, said once at boot");
  r.api.closeTabLocally(id);
  assert.deepEqual(r.HOOKS.posts.filter((p) => p.romp === "colBusy"), [{ romp: "colBusy", busy: false }], "the ✕: exactly one colBusy:false — the shell completes the held close");
});

// ---- round eight ----
test("round eight: a reply is routed by its request, never by the pending create — with B pending, A's follow-ups reach A's tab or a toast, and B stands", () => {
  // A settled on a running session, B pending: A's follow-up warning is a toast; B is untouched
  const a = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: C });
  a.api.startCreate(REQ); const ridA = a.api.rid()!; a.api.resolveTo(A);
  a.api.openPicker(); a.api.startCreate({ ...REQ, name: "notes-b" }); const idB = a.api.state().provisionalId!;
  assert.equal(a.api.route({ rid: ridA }), "settled");
  a.api.onCreateWarn({ text: '"notes" is already running; its tags were not changed', rid: ridA });
  assert.deepEqual(a.HOOKS.toasts, ['"notes" is already running; its tags were not changed']); assert.equal(a.api.state().provisionalId, idB, "B still pending"); assert.deepEqual(a.api.state().failed, [], "B not failed");
  // A backstopped, B pending: A's late authoritative reason refines A's tab; B is untouched
  const b = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: C });
  b.api.startCreate(REQ); const ridA2 = b.api.rid()!; const idA2 = b.api.state().provisionalId!; b.api.fireTimers(); b.api.answer("ok");   // the backstop's own "Couldn't start" dialog, dismissed
  b.api.openPicker(); b.api.startCreate({ ...REQ, name: "notes-b" }); const idB2 = b.api.state().provisionalId!;
  assert.equal(b.api.route({ rid: ridA2 }), "failed");
  b.api.onCreateWarn({ text: "late authoritative detail for A", rid: ridA2 });
  assert.equal(b.api.state().why[idA2], "late authoritative detail for A", "A's tab, refined"); assert.equal(b.api.state().provisionalId, idB2, "B still pending"); assert.deepEqual(b.api.state().failed, [idA2], "B not failed");
  // A failed, B pending: A's late folder question refines A's reason and asks nothing of B
  b.api.onCreateDirMissing({ name: REQ.name, dir: REQ.dir, status: { canCreate: true }, rid: ridA2 });
  assert.equal(b.api.overlays(), 0, "no prompt over B"); assert.equal(b.api.state().dirQuestionFor, null); assert.match(b.api.state().why[idA2], /^That folder isn't there/); assert.equal(b.api.state().provisionalId, idB2);
  // a request no tab remembers (a create from before a reload), B pending: a warning is said, a folder question is dropped
  assert.equal(b.api.route({ rid: "c-from-before-the-reload" }), "unknown");
  b.api.onCreateWarn({ text: "an old create's word", rid: "c-from-before-the-reload" }); assert.ok(b.HOOKS.toasts.includes("an old create's word")); assert.equal(b.api.state().provisionalId, idB2);
  b.api.onCreateDirMissing({ name: "old", dir: "/old", status: { canCreate: true }, rid: "c-from-before-the-reload" }); assert.equal(b.api.overlays(), 0); assert.equal(b.api.state().dirQuestionFor, null);
  // no request id (an older kernel): the pending create's, as ever
  assert.equal(b.api.route({}), "current"); assert.equal(b.api.route({ rid: b.api.rid()! }), "pending");
  b.api.onCreateWarn({ text: "B's own verdict" }); assert.deepEqual(b.api.state().failed.sort(), [idA2, idB2].sort(), "no id: the pending create's verdict, as today");
});

test("round eight: a create still pending at reload comes back as a failed tab holding its staged text, busy until its ✕; staged text under no record is swept", () => {
  const store: Record<string, unknown> = {};
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store });
  w.api.startCreate(REQ); const id = w.api.state().provisionalId!; const rid = w.api.rid()!;
  assert.deepEqual(store.pending, { id, name: "notes", dir: REQ.dir, rid }, "the pending create is on disk from the start");
  w.api.held.stage(id, "staged before the reload");   // staging moved the text out of the plain draft
  (store.staged as any)["new-orphan-staged"] = [{ text: "nobody's", cites: [] }];
  const r = world({ activeId: null, mru: [], order: [A, B, C], nextActive: null, store });   // the page reloads mid-create
  const st = r.api.state();
  assert.deepEqual(st.failed, [id], "back as a failed create"); assert.equal(st.why[id], "The page reloaded while this session was being created. Start it again from the session picker, or discard this tab with its ✕.");
  assert.deepEqual((r.api.held.staged()[id] || []).map((m: any) => m.text), ["staged before the reload"], "its staged text is with it");
  assert.equal(r.api.busy(), true, "busy: a held column stays"); assert.equal(store.pending, null, "the failed record replaced the pending one"); assert.ok((store.failed as any)[id]);
  assert.equal((store.staged as any)["new-orphan-staged"], undefined, "staged text under no record: swept, and the store rewritten");
  r.api.closeTabLocally(id);
  assert.equal((store.failed as any)[id], undefined); assert.equal((store.staged as any)[id], undefined, "the ✕ took the staged text too"); assert.equal(r.api.busy(), false);
  // a failure clears the pending record (the failed record replaces it); the same-tab retry updates it
  const v = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: C, store: {} });
  v.api.startCreate(REQ); v.api.onCreateDirMissing({ name: REQ.name, dir: REQ.dir, status: { canCreate: true } }); const rid1 = v.api.rid()!;
  v.api.answer("create"); assert.equal((v.store.pending as any).rid, v.api.rid(), "the retry's request"); assert.notEqual((v.store.pending as any).rid, rid1);
  v.api.fireTimers(); assert.equal(v.store.pending, null, "failed: the failed record replaces it"); assert.ok((v.store.failed as any)[v.api.state().failed[0]]);
});

test("round eight: at boot the lost-upload notice comes before the replay of the last page's notices — executed, not read off the file", () => {
  const session: Record<string, string> = {}; keepReloadNotices({ getItem: (k) => session[k] ?? null, setItem: (k, v) => { session[k] = v; }, removeItem: (k) => { delete session[k]; } }, ["what the last page was saying"]);
  const w = world({ activeId: null, mru: [], order: [A, B, C], nextActive: null, store: { shipsInFlight: ["a.png"] }, session });
  assert.equal(w.HOOKS.toasts.length, 2, "both said: " + JSON.stringify(w.HOOKS.toasts));
  assert.match(w.HOOKS.toasts[0], /was still uploading when this page reloaded/, "the loss first"); assert.equal(w.HOOKS.toasts[1], "what the last page was saying", "…then the replay");
  assert.equal(session["romp:reloadNotices"], undefined, "consumed once");
});

// ---- round nine ----
const X = "11111111-2222-3333-4444-555555555510";   // the session the create makes
const CARD = { title: "a card", itemId: "g1" };
// a create in flight with everything a provisional tab can hold: a staged message carrying a citation, an unsent citation chip, an attached file, a plain draft
function laden(o: Parameters<typeof world>[0]) {
  const w = world(o); w.api.startCreate(REQ); const id = w.api.state().provisionalId!;
  w.api.held.stage(id, "staged while opening", [CARD]); w.api.held.cite(id); w.api.held.attach(id); w.api.type(TYPED);
  return { w, id };
}
const nothingUnder = (w: ReturnType<typeof world>, id: string) => {
  assert.equal(w.api.held.staged()[id], undefined, "no staged text under the retired id"); assert.equal(w.api.held.citations()[id], undefined); assert.equal(w.api.held.files()[id], undefined); assert.equal(w.api.held.drafts()[id], undefined);
  for (const k of ["staged", "citations", "files", "drafts"]) assert.equal(((w.store as any)[k] || {})[id], undefined, k + ": nothing under the retired id on disk");
};

test("round nine: adoption carries the staged message (with its citation), the unsent chip and the attached file to the new session — nothing stays under the retired id, the store rewritten", () => {
  const { w, id } = laden({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {} });
  w.api.adopt(X);
  assert.deepEqual(w.api.held.staged()[X], [{ text: "staged while opening", cites: [CARD] }], "the staged message, its citation with it");
  assert.deepEqual(w.api.held.citations()[X], [CARD], "the unsent chip");
  assert.deepEqual(w.api.held.files()[X], ["/tmp/a.png"], "the attached file"); assert.equal(w.api.held.drafts()[X], TYPED, "the plain draft, as before");
  nothingUnder(w, id);
  assert.deepEqual((w.store.staged as any)[X], [{ text: "staged while opening", cites: [CARD] }], "on disk under the real sid"); assert.deepEqual((w.store.files as any)[X], [{ path: "/tmp/a.png", legacy: false }]);
  assert.deepEqual(w.HOOKS.claims, [X]); assert.equal(w.api.busy(), false);
});

test("round nine: resolution to a session shown in ANOTHER pane keys the moved state under it BEFORE the flip, and the hand-off enumerates that sid — the receiving pane gets all four", () => {
  const { w, id } = laden({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {}, sets: { "2": [] } });   // a HELD column (a peer dropped it): its set is empty
  w.api.resolveTo(A);   // the kernel's focus: "notes" is A, running, shown in the first column
  assert.deepEqual(w.api.held.staged()[A], [{ text: "staged while opening", cites: [CARD] }]); assert.deepEqual(w.api.held.citations()[A], [{ title: "a card", itemId: "g1" }]); assert.deepEqual(w.api.held.files()[A], ["/tmp/a.png"]); assert.equal(w.api.held.drafts()[A], TYPED);
  nothingUnder(w, id);
  assert.ok(w.api.orphans().includes(A), "the hand-off enumerates A: this page holds A's state and does not show A"); assert.ok(!w.api.orphans().some((s) => s.startsWith("new-")), "…and never the retired id");
  assert.deepEqual(w.HOOKS.posts[w.HOOKS.posts.length - 1], { romp: "colBusy", busy: false }, "the flip, last");
  assert.ok(w.HOOKS.seq.lastIndexOf("persist") < w.HOOKS.seq.lastIndexOf("flip:false"), "persisted (the moved state under A) before the flip that lets the shell close and transfer");
  // the next boot over the same store: the sweep finds nothing under a provisional id, and A's entries stand
  const r = world({ activeId: null, mru: [], order: [A, B, C], nextActive: null, store: w.store, sets: { "2": [] } });
  assert.deepEqual(r.api.held.staged()[A], [{ text: "staged while opening", cites: [CARD] }]); assert.deepEqual(r.api.held.files()[A], ["/tmp/a.png"]);
  assert.equal(Object.keys((r.store.staged as any) || {}).filter((k) => k.startsWith("new-")).length, 0); assert.equal(Object.keys((r.store.drafts as any) || {}).filter((k) => k.startsWith("new-")).length, 0);
});

// ---- round ten ----
const QUOTE = { title: "a highlighted line", quote: "the highlighted line" }, QUOTE2 = { title: "another line", quote: "another highlighted line" }, CARD2 = { title: "a second card", itemId: "g2" };
const SHIP = { name: "photo.png", shipId: "s1", b64: "QUJD" };
const receiving = () => world({ activeId: A, mru: [A], order: [A], nextActive: null, store: {}, sets: { "": [A] } });   // the pane that SHOWS A

test("round ten: a context-only staged citation (quotes, no words) survives both settlements and the hand-off — the load filter is the store's, never a move's", () => {
  const a = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {} });
  a.api.startCreate(REQ); const idA = a.api.state().provisionalId!;
  a.api.held.stage(idA, "", [QUOTE]);   // ⌘⏎ over an empty box: the context alone
  a.api.adopt(X);
  assert.deepEqual(a.api.held.staged()[X], [{ text: "", cites: [QUOTE] }], "adoption: the context-only item, under the new session"); assert.equal(a.api.held.staged()[idA], undefined);
  assert.deepEqual((a.store.staged as any)[X], [{ text: "", cites: [QUOTE] }], "…and on disk");
  const b = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {}, sets: { "2": [] } });   // a held column
  b.api.startCreate(REQ); const idB = b.api.state().provisionalId!;
  b.api.held.stage(idB, "", [QUOTE]);
  b.api.resolveTo(A);
  assert.deepEqual(b.api.held.staged()[A], [{ text: "", cites: [QUOTE] }], "resolution: under the running session");
  const st = b.api.take(A);   // the shell's close(): to the pane that shows A
  assert.deepEqual(st.staged, [{ text: "", cites: [QUOTE] }], "taken whole"); assert.equal(b.api.held.staged()[A], undefined, "…and gone from the closing page");
  const r = receiving(); r.api.adoptState(A, st);
  assert.deepEqual(r.api.held.staged()[A], [{ text: "", cites: [QUOTE] }], "adopted whole");
  const again = world({ activeId: null, mru: [], order: [A], nextActive: null, store: r.store, sets: { "": [A] } });   // the receiving pane reloads
  assert.deepEqual(again.api.held.staged()[A], [{ text: "", cites: [QUOTE] }], "…and back after a reload (restore() keeps a context-only item now)");
});

test("round ten: adoption JOINS the create's text onto a draft already under the arriving session — never over it", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: { drafts: { [X]: "typed for it before its frame came" } } });
  w.api.startCreate(REQ); w.api.type(TYPED);
  w.api.adopt(X);
  assert.equal(w.api.held.drafts()[X], "typed for it before its frame came\n\n" + TYPED, "what was there first, a blank line, the create's text — as resolution and adoptSessionState join");
  assert.equal(w.api.composer(), "typed for it before its frame came\n\n" + TYPED, "…and that is what the box shows");
});

test("round ten: an upload in flight on the pending tab is the new session's after adoption — the ack attaches the file under the real sid and the send held on it fires there", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {} });
  w.api.startCreate(REQ); const id = w.api.state().provisionalId!;
  w.api.ship(id, SHIP.name, SHIP.shipId, SHIP.b64); w.api.holdSend(id);
  w.api.adopt(X);
  assert.deepEqual(w.api.ships(), { [X]: [SHIP] }, "the pending chip under the real sid, none under the retired id"); assert.deepEqual(w.api.heldSend(), [X], "the held send, re-keyed");
  w.api.ack({ type: "droppedPath", path: "drops/1700000000000-photo.png", shipId: "s1" });
  assert.deepEqual(w.api.held.files()[X], ["drops/1700000000000-photo.png"], "the saved path on the real session's strip"); assert.equal(w.api.held.files()[id], undefined, "nothing under the retired id");
  assert.deepEqual(w.api.ships(), {}); assert.deepEqual(w.api.heldSend(), []); assert.equal(w.HOOKS.fired, 1, "the held send fired — the real session is the active tab"); assert.deepEqual(w.HOOKS.toasts, []);
});

test("round eleven: an upload never crosses documents — a create resolved to a session shown elsewhere with two uploads in flight holds the column; the unread one fails → the held send is cancelled loudly and the words stay the real session's draft; the read one acks → busy false last, the hand-off carries the completed file and the draft, nothing re-sent", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {}, sets: { "2": [] } });   // a held column
  w.api.startCreate(REQ); const id = w.api.state().provisionalId!;
  w.api.ship(id, SHIP.name, SHIP.shipId, SHIP.b64); w.api.ship(id, "late.png", "s2"); w.api.holdSend(id); w.api.type(TYPED);   // two uploads, one still unread; "Wait for the upload"
  w.api.resolveTo(A);
  assert.equal(w.api.busy(), true, "busy: an upload of this document is in flight"); assert.equal(flips(w.HOOKS, false), 0, "no flip: the column stays held");
  assert.deepEqual(Object.keys(w.api.ships()), [A], "the chips are the real session's"); assert.equal(w.api.ships()[A].length, 2); assert.deepEqual(w.api.heldSend(), [A]);
  w.api.shipFail("late.png", "s2");   // the FileReader failed on the unread one
  assert.deepEqual(w.api.heldSend(), [], "the held send is cancelled: it would go short of an attachment"); assert.equal(w.HOOKS.fired, 0);
  assert.ok(w.HOOKS.toasts.some((t) => /late\.png .*NOT sent/.test(t)), "said: " + JSON.stringify(w.HOOKS.toasts));
  assert.equal(w.api.held.drafts()[A], TYPED, "the words stay the real session's draft"); assert.equal(w.api.busy(), true, "still busy: the other ship's ack is owed"); assert.equal(flips(w.HOOKS, false), 0);
  w.api.ack({ type: "droppedPath", path: "drops/1700000000000-photo.png", shipId: "s1" });
  assert.deepEqual(w.api.held.files()[A], ["drops/1700000000000-photo.png"], "the completed file, under the real sid"); assert.equal(w.HOOKS.fired, 0);
  assert.deepEqual(w.HOOKS.sent.filter((m) => m.type === "sendMessage" || m.type === "askFollowUp"), [], "nothing sent: the hold was cancelled");
  assert.equal(w.api.busy(), false); assert.equal(flips(w.HOOKS, false), 1); assert.deepEqual(last(w.HOOKS), { romp: "colBusy", busy: false }, "the flip, last");
  assert.ok(w.HOOKS.seq.lastIndexOf("persist") < w.HOOKS.seq.lastIndexOf("flip:false"), "persisted before the flip");
  assert.ok(w.HOOKS.posts.some((p) => p.romp === "orphanState" && (p.sids as string[]).includes(A)), "the completed file under an unshown session is offered to the pane that shows it");
  const st = w.api.take(A);
  assert.deepEqual(st, { draft: TYPED, citations: [], files: [{ path: "drops/1700000000000-photo.png", legacy: false }], staged: [] }, "the hand-off's exact fields: no upload, no held send; each file with its provenance (round twenty-two)");
  assert.deepEqual(w.HOOKS.sent.filter((m) => m.type === "dropFile").map((m) => m.shipId), ["s1"], "one frame per upload — its creation post (the unread one never posted) — and no re-send, ever");
  // the receiving pane ignores an upload or a held-send field an older page might still send: never a chip, never a hold, never a re-ship
  const r = receiving(); r.api.adoptState(A, { ...st, ships: [{ name: "x.png", shipId: "s9", b64: "QUJD" }], heldSend: true });
  assert.deepEqual(r.api.ships(), {}); assert.deepEqual(r.api.heldSend(), []); assert.deepEqual(r.HOOKS.sent.filter((m) => m.type === "dropFile"), []);
  assert.deepEqual(r.api.held.files()[A], ["drops/1700000000000-photo.png"]); assert.equal(r.api.held.drafts()[A], TYPED);
});

test("round eleven: the held send fires BY SID from a document that does not show the tab, once every ship it waited on completed — the draft, the acked file on its trailing line, to the real session; the stores empty; nothing left to hand over", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {}, sets: { "2": [] } });
  w.api.startCreate(REQ); const id = w.api.state().provisionalId!;
  w.api.ship(id, SHIP.name, SHIP.shipId, SHIP.b64); w.api.holdSend(id); w.api.type(TYPED);
  w.api.resolveTo(A);
  assert.equal(w.api.state().activeId, null, "the held column shows no tab"); assert.equal(w.api.busy(), true);
  w.api.ack({ type: "droppedPath", path: "drops/1700000000001-photo.png", shipId: "s1" });
  const sent = w.HOOKS.sent.filter((m) => m.type === "sendMessage");
  assert.deepEqual(sent.map((m) => ({ id: m.id, text: m.text, paths: m.paths })), [{ id: A, text: TYPED + "\ndrops/1700000000001-photo.png", paths: ["drops/1700000000001-photo.png"] }], "one message, to A by sid, the attachment on its trailing line");
  assert.equal(w.HOOKS.fired, 0, "not the box's send: the tab is not shown here"); assert.deepEqual(w.HOOKS.toasts, []);
  assert.equal(w.api.held.drafts()[A], undefined); assert.equal(w.api.held.files()[A], undefined); assert.deepEqual(w.api.heldSend(), []);
  assert.equal(w.api.busy(), false); assert.deepEqual(last(w.HOOKS), { romp: "colBusy", busy: false }, "the flip, last"); assert.equal(w.api.take(A), null, "nothing left to hand over");
});

test("round eleven: in ONE document (adoption: the column stays) two uploads on the pending tab — the first ack does not fire the held send, the last does, both files with it; a failure cancels the hold and the later ack sends nothing", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {} });
  w.api.startCreate(REQ); const id = w.api.state().provisionalId!;
  w.api.ship(id, "a.png", "s1", "QUJD"); w.api.ship(id, "b.png", "s2", "QUJD"); w.api.holdSend(id); w.api.type(TYPED);
  w.api.adopt(X);
  assert.equal(w.api.busy(), true, "busy: the acks are owed to this document"); assert.equal(flips(w.HOOKS, false), 0);
  w.api.ack({ type: "droppedPath", path: "drops/1-a.png", shipId: "s1" });
  assert.equal(w.HOOKS.fired, 0, "one ship still pending"); assert.deepEqual(w.api.held.files()[X], ["drops/1-a.png"]); assert.equal(w.api.busy(), true);
  w.api.ack({ type: "droppedPath", path: "drops/2-b.png", shipId: "s2" });
  assert.equal(w.HOOKS.fired, 1, "the last ack fires the box's send (the tab is active here)"); assert.deepEqual(w.api.held.files()[X], ["drops/1-a.png", "drops/2-b.png"], "both files on the strip for it");
  assert.equal(w.api.busy(), false); assert.equal(flips(w.HOOKS, false), 1); assert.deepEqual(last(w.HOOKS), { romp: "colBusy", busy: false });
  const v = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {} });
  v.api.startCreate(REQ); const idv = v.api.state().provisionalId!;
  v.api.ship(idv, "a.png", "s1", "QUJD"); v.api.ship(idv, "b.png", "s2"); v.api.holdSend(idv); v.api.type(TYPED);
  v.api.adopt(X);
  v.api.shipFail("b.png", "s2");
  assert.deepEqual(v.api.heldSend(), [], "cancelled at the failure"); assert.ok(v.HOOKS.toasts.some((t) => /NOT sent/.test(t)));
  v.api.ack({ type: "droppedPath", path: "drops/1-a.png", shipId: "s1" });
  assert.equal(v.HOOKS.fired, 0, "the surviving ack sends nothing"); assert.deepEqual(v.api.held.files()[X], ["drops/1-a.png"]); assert.equal(v.api.held.drafts()[X], TYPED, "the words kept as the draft");
  assert.equal(v.api.busy(), false);
});

test("round eleven: the take tells the reload core when it empties a box that held words (the typing hold's ending event), and says nothing when the box was empty", () => {
  const w = receiving(); w.api.type("half a thought");
  const st = w.api.take(A);
  assert.equal(st.draft, "half a thought"); assert.equal(w.api.composer(), ""); assert.equal(w.HOOKS.reloadEnded, 1, "told once: the box that held the typing hold was emptied");
  const v = receiving();
  assert.equal(v.api.take(A), null); assert.equal(v.HOOKS.reloadEnded, 0, "an empty box held nothing: nothing to end");
});

test("round ten: flavours never mix in a carry — a goal chip keeps the list and the quotes stage as context, whichever side held them; quotes stack; two goals: the arriving one, said; the receiving pane's adopt follows the same rule", () => {
  const held = () => world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {}, sets: { "2": [] } });
  // the running session holds a goal chip; the create carried a quote chip
  const a = held(); a.api.held.cite(A, [CARD]); a.api.startCreate(REQ); a.api.held.cite(a.api.state().provisionalId!, [QUOTE]); a.api.resolveTo(A);
  assert.deepEqual(a.api.held.citations()[A], [CARD], "the goal keeps the list"); assert.deepEqual(a.api.held.staged()[A], [{ text: "", cites: [QUOTE] }], "the quote is context, staged: on the strip, released ahead of the follow-up's words");
  // the reverse: quotes on the running session, a goal on the create — the quotes stage (a goal cannot be context alone), behind what was staged
  const b = held(); b.api.held.cite(A, [QUOTE]); b.api.held.stage(A, "already staged here"); b.api.startCreate(REQ); const idB = b.api.state().provisionalId!; b.api.held.cite(idB, [CARD]); b.api.held.stage(idB, "staged on the pending tab", [QUOTE2]); b.api.resolveTo(A);
  assert.deepEqual(b.api.held.citations()[A], [CARD]);
  assert.deepEqual(b.api.held.staged()[A], [{ text: "already staged here", cites: [] }, { text: "staged on the pending tab", cites: [QUOTE2] }, { text: "", cites: [QUOTE] }], "what was staged here, what arrived staged, then the displaced quotes");
  // one flavour: quotes stack, as the composer stacks them
  const c = held(); c.api.held.cite(A, [QUOTE]); c.api.startCreate(REQ); c.api.held.cite(c.api.state().provisionalId!, [QUOTE2]); c.api.resolveTo(A);
  assert.deepEqual(c.api.held.citations()[A], [QUOTE, QUOTE2]); assert.equal(c.api.held.staged()[A], undefined);
  // two goals: one goal per message — the arriving card is the follow-up and the replaced one is said
  const d = held(); d.api.held.cite(A, [CARD]); d.api.startCreate(REQ); d.api.held.cite(d.api.state().provisionalId!, [CARD2]); d.api.resolveTo(A);
  assert.deepEqual(d.api.held.citations()[A], [CARD2]); assert.equal(d.HOOKS.toasts.length, 1); assert.match(d.HOOKS.toasts[0], /a second card is the follow-up now; the earlier card \(a card\) was replaced/);
  // the receiving pane's adopt: the same rule, the same order
  const r = receiving(); r.api.held.cite(A, [CARD]); r.api.adoptState(A, { citations: [QUOTE], staged: [{ text: "arrived staged", cites: [] }] });
  assert.deepEqual(r.api.held.citations()[A], [CARD]); assert.deepEqual(r.api.held.staged()[A], [{ text: "arrived staged", cites: [] }, { text: "", cites: [QUOTE] }]);
});

// ---- round twelve ----
const RA = "TESTHOST:11111111-2222-3333-4444-555555555521";   // a session on an attached remote host

test("round twelve: a session with an upload in flight, or a send held on one, is BUSY for the shell's move question until the ack; a moved-away message's held send is refused here (the belt) and the file is offered on", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {}, sets: { "2": [] } });
  w.api.startCreate(REQ); const id = w.api.state().provisionalId!;
  w.api.ship(id, SHIP.name, SHIP.shipId, SHIP.b64); w.api.holdSend(id); w.api.type(TYPED);
  w.api.resolveTo(A);
  assert.equal(w.api.sessionBusy(A), true, "an upload in flight: the session cannot move"); assert.equal(w.api.sessionBusy(B), false);
  const st = w.api.take(A);   // the shell moved the tab anyway (an older shell): the words left with it
  assert.equal(st.draft, TYPED);
  w.api.ack({ type: "droppedPath", path: "drops/1700000000000-photo.png", shipId: "s1" });
  assert.deepEqual(w.HOOKS.sent.filter((m) => m.type === "sendMessage"), [], "the belt: nothing of the message is here — no bare path is sent");
  assert.ok(w.HOOKS.toasts.some((t) => /moved to another column/.test(t)), "said: " + JSON.stringify(w.HOOKS.toasts));
  assert.deepEqual(w.api.held.files()[A], ["drops/1700000000000-photo.png"], "the file, under the session"); assert.deepEqual(w.api.heldSend(), []);
  assert.ok(w.HOOKS.posts.some((p) => p.romp === "orphanState" && (p.sids as string[]).includes(A)), "…offered to the pane that shows it");
  assert.equal(w.api.sessionBusy(A), false, "released"); assert.equal(w.api.busy(), false);
  const v = receiving(); v.api.holdSend(A);
  assert.equal(v.api.sessionBusy(A), true, "a held send alone pins the session too");
});

test("round twelve: the ack is routed by the SHIP — a composer upload lands on the composer though a comment box is open (the held send fires), a comment's upload lands in the box, a legacy ack with no ship id keeps the old reading", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {} });
  w.api.startCreate(REQ); const id = w.api.state().provisionalId!;
  w.api.ship(id, "photo.png", "s1", "QUJD"); w.api.holdSend(id); w.api.type(TYPED);
  w.api.adopt(X);
  w.api.openComment("a note ");
  w.api.ack({ type: "droppedPath", path: "drops/1-photo.png", shipId: "s1" });
  assert.deepEqual(w.api.held.files()[X], ["drops/1-photo.png"], "the composer's upload, on the composer's strip"); assert.equal(w.HOOKS.fired, 1, "the held send fired");
  assert.equal(w.api.comment(), "a note ", "the comment box untouched"); assert.equal(w.api.busy(), false);
  w.api.ship(X, "shot.png", "s2", "QUJD", "comment");
  w.api.ack({ type: "droppedPath", path: "drops/2-shot.png", shipId: "s2" });
  assert.equal(w.api.comment(), "a note drops/2-shot.png ", "a comment's upload lands in the box"); assert.deepEqual(w.api.held.files()[X], ["drops/1-photo.png"]);
  w.api.ship(X, "old.png", "s3", "QUJD");
  w.api.ack({ type: "droppedPath", path: "drops/3-old.png" });   // an older kernel: no ship id echoed — matched by the saved name to the composer's ship (round sixteen)
  assert.equal(w.api.comment(), "a note drops/2-shot.png ", "a legacy ack matched to the composer's ship is the composer's, box open or not"); assert.deepEqual(w.api.held.files()[X], ["drops/1-photo.png", "drops/3-old.png"]); assert.equal(w.api.ships()[X], undefined, "…and retires it");
  w.api.ship(X, "q.png", "s5", "QUJD", "comment");
  w.api.ack({ type: "droppedPath", path: "drops/5-nomatch.png" });   // matched to nothing: main's reading — the open box is the comment's
  assert.equal(w.api.comment(), "a note drops/2-shot.png drops/5-nomatch.png ", "no ship named: an open box is the comment's, as on main"); assert.deepEqual(w.api.ships()[X].map((p) => p.shipId), ["s5"], "nothing retired");
  w.api.closeComment();
});

test("round twelve: a host DETACHED fails every upload shipped to it — loudly, the held send cancelled — and touches no other host's", () => {
  const w = receiving();
  w.api.ship(RA, "remote.png", "r1", "QUJD"); w.api.holdSend(RA); w.api.ship(A, "local.png", "l1", "QUJD");
  assert.equal(w.api.busy(), true);
  w.api.detach("TESTHOST");
  assert.deepEqual(Object.keys(w.api.ships()), [A], "the remote ship is gone, the local one stands"); assert.deepEqual(w.api.heldSend(), []);
  assert.ok(w.HOOKS.toasts.some((t) => /remote\.png .*TESTHOST was detached/.test(t) && /NOT sent/.test(t)), "said: " + JSON.stringify(w.HOOKS.toasts));
  assert.equal(w.api.busy(), true, "the local upload still holds");
  w.api.ack({ type: "droppedPath", path: "drops/1-local.png", shipId: "l1" });
  assert.equal(w.api.busy(), false);
});

test("round twelve: what holds the column, by name; a column held only by an upload for a session shown elsewhere asks the user on this user's close — keep waiting, or close anyway and lose it", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {}, sets: { "2": [] } });
  assert.equal(w.api.busyWhy(), "");
  w.api.startCreate(REQ); const id = w.api.state().provisionalId!;
  assert.equal(w.api.busyWhy(), "create");
  w.api.ship(id, SHIP.name, SHIP.shipId, SHIP.b64); w.api.holdSend(id); w.api.type(TYPED);
  w.api.resolveTo(A);
  assert.equal(w.api.busyWhy(), "upload-unshown", "the only hold: an upload for A, which this column does not show");
  w.api.askClose();
  assert.deepEqual(w.api.confirm(), { title: "An upload is still on its way", buttons: ["Keep waiting", "Close anyway"], key: "close-upload:2" });
  assert.equal(w.api.clickButton("Keep waiting"), true);
  assert.equal(Object.keys(w.api.ships()).length, 1, "kept"); assert.deepEqual(w.HOOKS.closeSplit, []); assert.equal(w.api.busy(), true);
  w.api.askClose(); assert.equal(w.api.clickButton("Close anyway"), true);
  assert.deepEqual(w.api.ships(), {}, "abandoned"); assert.deepEqual(w.api.heldSend(), [], "the held send never fires short of it");
  assert.equal(w.api.held.drafts()[A], TYPED, "the words stay the session's draft, to travel with the close");
  assert.equal(w.api.busy(), false); assert.equal(flips(w.HOOKS, false), 1); assert.deepEqual(w.HOOKS.closeSplit, [2], "…and the shell is asked to close again");
  const v = world({ activeId: A, mru: [A], order: [A], nextActive: null, store: {}, sets: { "2": [A] } });   // the session IS shown here: its chip's ✕ can release the hold
  v.api.ship(A, "a.png", "a1", "QUJD");
  assert.equal(v.api.busyWhy(), "upload");
});

test("round twelve: a frame the shim's own queue flushes on the reconnect is not re-shipped by that reconnect's romp:wsup — one frame per upload; a ship made before the drop is re-shipped once", () => {
  const w = receiving();
  const frames = () => w.HOOKS.sent.filter((m) => m.type === "dropFile").map((m) => m.shipId);
  w.api.ship(A, "before.png", "p1", "QUJD");   // shipped on the live socket (its frame posted), unacked at the drop
  w.api.wsdown();
  w.api.ship(A, "during.png", "q1", "QUJD");   // posted while down: the shim queues it and flushes it on the open
  assert.deepEqual(frames(), ["p1", "q1"], "each ship posted once at creation");
  w.api.wsup();
  assert.deepEqual(frames(), ["p1", "q1", "p1"], "the queued frame rides the shim's flush; only the earlier ship is re-sent");
  w.api.wsdown(); w.api.wsup();
  assert.deepEqual(frames(), ["p1", "q1", "p1", "p1", "q1"], "a second drop before the acks: both re-ship (the kernel answers one path per ship id)");
});

test("round twelve: the strip's last member gone while an upload was in flight — the emptiness is reported on the release, before the flip", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {}, sets: { "2": [C] } });
  w.api.ship(C, "c.png", "c1", "QUJD");
  w.api.strip([A, B]);   // the kernel's strip no longer lists C
  assert.equal(w.HOOKS.posts.filter((p) => p.romp === "colEmpty").length, 0, "not from under a hold");
  w.api.ack({ type: "droppedPath", path: "drops/1-c.png", shipId: "c1" });
  assert.deepEqual(w.HOOKS.posts.filter((p) => p.romp === "colEmpty"), [{ romp: "colEmpty", gone: [C], crossed: [] }], "said on the release");
  assert.deepEqual(last(w.HOOKS), { romp: "colBusy", busy: false }, "the flip, last"); assert.ok(w.HOOKS.seq.indexOf("empty") < w.HOOKS.seq.lastIndexOf("flip:false"));
});

// ---- round thirteen ----
test("round thirteen: a comment's upload acked after its popover closed never reaches the composer — retired, said by name; a send held on the composer's uploads is neither released nor gated by it", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {} });
  w.api.startCreate(REQ); const id = w.api.state().provisionalId!;
  w.api.ship(id, "photo.png", "s1", "QUJD"); w.api.holdSend(id); w.api.type(TYPED);
  w.api.adopt(X);
  w.api.ship(X, "shot.png", "s2", "QUJD", "comment");   // the comment's clip, then the popover closes
  w.api.ack({ type: "droppedPath", path: "drops/2-shot.png", shipId: "s2" });
  assert.equal(w.api.held.files()[X], undefined, "the comment's file is on no composer strip");
  assert.ok(w.HOOKS.toasts.some((t) => /2-shot\.png arrived after its comment was closed/.test(t)), "said by name: " + JSON.stringify(w.HOOKS.toasts));
  assert.equal(w.HOOKS.fired, 0, "the held send is not released by it"); assert.deepEqual(w.api.heldSend(), [X], "…and still armed: it waits on the composer's own ship");
  assert.deepEqual(w.api.ships()[X].map((p) => p.shipId), ["s1"], "the comment's chip retired");
  w.api.ack({ type: "droppedPath", path: "drops/1-photo.png", shipId: "s1" });
  assert.equal(w.HOOKS.fired, 1, "the composer's own last ship releases it"); assert.deepEqual(w.api.held.files()[X], ["drops/1-photo.png"]); assert.equal(w.api.busy(), false);
});

test("round thirteen: a tab moved back with NO state clears the handed-off marker the moment this column shows the sid again — a later send held on an upload here, with nothing typed, goes", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {}, sets: { "2": [] } });
  w.api.startCreate(REQ); w.api.type(TYPED); w.api.resolveTo(A);
  assert.equal(w.api.take(A).draft, TYPED, "the words left with the tab: the marker stands");
  w.api.setSets({ "2": [A] }); w.api.reclaim();   // the tab comes back to this column with no state (the shell skipped the adopt); renderTabs reads the sets
  w.api.ship(A, "later.png", "l1", "QUJD"); w.api.holdSend(A);   // an attachment and "Wait for the upload", nothing typed
  w.api.ack({ type: "droppedPath", path: "drops/9-later.png", shipId: "l1" });
  const sent = w.HOOKS.sent.filter((m) => m.type === "sendMessage");
  assert.deepEqual(sent.map((m) => ({ id: m.id, text: m.text })), [{ id: A, text: "drops/9-later.png" }], "the held send goes: the attachment alone was the message");
  assert.ok(!w.HOOKS.toasts.some((t) => /moved to another column/.test(t)), "no belt toast: the words were never elsewhere for this send");
});

// ---- round fourteen ----
test("round fourteen: a COMMENT upload's failure is the comment's alone — the composer's held send stays armed and fires when the composer's own file lands; a composer upload's failure still cancels it", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {} });
  w.api.startCreate(REQ); const id = w.api.state().provisionalId!;
  w.api.ship(id, "photo.png", "s1", "QUJD"); w.api.holdSend(id); w.api.type(TYPED);   // the composer's attachment, "Wait for the upload"
  w.api.adopt(X);
  w.api.ship(X, "shot.png", "s2", "QUJD", "comment");   // a comment's clip for the same session…
  w.api.shipFail("shot.png", "s2");                      // …fails first (the reader, an empty encoding, a nack, a detach)
  assert.deepEqual(w.api.heldSend(), [X], "the composer's hold stands"); assert.equal(w.HOOKS.fired, 0);
  assert.ok(w.HOOKS.toasts.some((t) => /shot\.png could not be read/.test(t)), "the comment's failure is said"); assert.ok(!w.HOOKS.toasts.some((t) => /NOT sent/.test(t)), "…and nothing about the composer's message");
  assert.deepEqual(w.api.ships()[X].map((p) => p.shipId), ["s1"], "the comment's chip is gone, the composer's stands");
  w.api.ack({ type: "droppedPath", path: "drops/1-photo.png", shipId: "s1" });
  assert.equal(w.HOOKS.fired, 1, "the composer's file landed: the held send fires"); assert.deepEqual(w.api.held.files()[X], ["drops/1-photo.png"]); assert.equal(w.api.busy(), false);
  const v = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {} });
  v.api.startCreate(REQ); const idv = v.api.state().provisionalId!;
  v.api.ship(idv, "a.png", "a1", "QUJD"); v.api.ship(idv, "b.png", "b1", "QUJD"); v.api.holdSend(idv); v.api.adopt(X);
  v.api.shipFail("b.png", "b1");   // a COMPOSER ship fails: the message would be incomplete
  assert.deepEqual(v.api.heldSend(), [], "cancelled, as before"); assert.ok(v.HOOKS.toasts.some((t) => /NOT sent/.test(t)));
});

test("round fourteen: the held strip's heading counts the COMPOSER's uploads — a comment's chip beside them is not one the send waits for", () => {
  const w = receiving();
  w.api.ship(A, "one.png", "c1", "QUJD"); w.api.ship(A, "shot.png", "m1", "QUJD", "comment");
  assert.equal(w.api.heading(A), "staged — sends when the upload finishes", "one composer upload: no count (the comment's is not counted)");
  w.api.ship(A, "two.png", "c2", "QUJD");
  assert.equal(w.api.heading(A), "staged — sends when the upload finishes (2 still uploading)", "two composer uploads");
  assert.equal(w.api.heading(B), "staged — sends when the upload finishes");
});

// ---- round fifteen ----
test("round fifteen: an UNTAGGED droppedPath (the VS Code picker) for the active session lands on ITS composer and is inert beyond it — another session's sole pending upload and held send stand; that session's own tagged ack then sends its words with its file alone", () => {
  const w = receiving();   // A is the active session
  w.api.draft(B, "B words waiting"); w.api.ship(B, "b.png", "b1", "QUJD"); w.api.holdSend(B);   // B owns the document's only pending upload, and a send held on it
  w.api.ack({ type: "droppedPath", path: "/synthetic/picked-for-A.txt" });   // the picker's answer for A: no shipId, no ship
  assert.deepEqual(w.api.held.files()[A], ["/synthetic/picked-for-A.txt"], "A's composer gets the picked file");
  assert.equal(w.api.held.files()[B], undefined, "nothing on B's strip");
  assert.deepEqual(w.api.ships()[B].map((p) => p.shipId), ["b1"], "B's record intact"); assert.deepEqual(w.api.heldSend(), [B], "B's hold intact");
  assert.deepEqual(w.HOOKS.sent.filter((m) => m.type === "sendMessage"), [], "nothing sent"); assert.equal(w.HOOKS.fired, 0);
  w.api.ack({ type: "droppedPath", path: "drops/1-b.png", shipId: "b1" });   // B's own tagged ack
  const sent = w.HOOKS.sent.filter((m) => m.type === "sendMessage");
  assert.deepEqual(sent.map((m) => ({ id: m.id, text: m.text, paths: m.paths })), [{ id: B, text: "B words waiting\ndrops/1-b.png", paths: ["drops/1-b.png"] }], "B's held send fires with B's file alone");
  assert.deepEqual(w.api.held.files()[A], ["/synthetic/picked-for-A.txt"], "A's strip untouched by B's release"); assert.deepEqual(w.api.heldSend(), []);
});

test("round sixteen: an untagged, un-picked frame is a LEGACY kernel's ack — matched by the saved name to the ship it answers, wherever that ship lives, and settled as a tagged ack would be", () => {
  // (a) the active session's own upload: the chip retired, the file attached — and the held send CANCELLED, said (round nineteen: an untagged answer never sends)
  const w = receiving(); w.api.ship(A, "photo.png", "a1", "QUJD"); w.api.holdSend(A); w.api.type(TYPED);
  w.api.ack({ type: "droppedPath", path: "drops/1700000000000-photo.png" });
  assert.equal(w.api.ships()[A], undefined, "the chip is retired"); assert.deepEqual(w.api.held.files()[A], ["drops/1700000000000-photo.png"]); assert.equal(w.HOOKS.fired, 0, "no automatic send from an untagged answer");
  assert.deepEqual(w.api.heldSend(), [], "the hold is cancelled"); assert.ok(w.HOOKS.toasts.some((t) => /answered by an older kernel that names no upload/.test(t)), "said: " + JSON.stringify(w.HOOKS.toasts)); assert.equal(w.api.composer(), TYPED, "the words stay in the box"); assert.equal(w.api.busy(), false);
  // (b) no active tab, one matching pending ship: attached to its owner, the chip retired, the hold cancelled and said — nothing sent, nothing silent
  const v = world({ activeId: null, mru: [], order: [A, B], nextActive: null, store: {}, sets: { "2": [] } });
  v.api.draft(A, "A words waiting"); v.api.ship(A, "photo.png", "a1", "QUJD"); v.api.holdSend(A);
  v.api.ack({ type: "droppedPath", path: "drops/1-photo.png" });
  assert.deepEqual(v.HOOKS.sent.filter((m) => m.type === "sendMessage"), [], "nothing sent"); assert.deepEqual(v.api.held.files()[A], ["drops/1-photo.png"]); assert.equal(v.api.held.drafts()[A], "A words waiting", "the draft kept");
  assert.equal(v.api.ships()[A], undefined); assert.deepEqual(v.api.heldSend(), []); assert.equal(v.api.busy(), false); assert.ok(v.HOOKS.toasts.some((t) => /older kernel/.test(t))); assert.ok(!v.HOOKS.toasts.some((t) => /no session is open/.test(t)));
  // (c) no active tab, no match: said, nothing retired, nothing attached
  const u = world({ activeId: null, mru: [], order: [A, B], nextActive: null, store: {}, sets: { "2": [] } });
  u.api.ship(A, "other.png", "o1", "QUJD");
  u.api.ack({ type: "droppedPath", path: "drops/1-photo.png" });
  assert.ok(u.HOOKS.toasts.some((t) => /1-photo\.png arrived, but no session is open/.test(t)), "said: " + JSON.stringify(u.HOOKS.toasts)); assert.deepEqual(u.api.ships()[A].map((p) => p.shipId), ["o1"], "nothing retired"); assert.equal(u.api.held.files()[A], undefined);
  // (g) two pending ships with the same sanitised name: the FIRST POSTED takes the file (the best guess; it decides no send)
  const g = receiving(); g.api.ship(A, "photo.png", "p1", "QUJD"); g.api.ship(A, "photo.png", "p2", "QUJD");
  g.api.ack({ type: "droppedPath", path: "drops/2-photo.png" });
  assert.deepEqual(g.api.ships()[A].map((p) => p.shipId), ["p2"], "the first-posted match retired, the later one waits for its own ack");
  // a legacy ack for another session's ship, A active: it is that ship's, not A's
  const o = receiving(); o.api.ship(B, "b.png", "b1", "QUJD");
  o.api.ack({ type: "droppedPath", path: "drops/3-b.png" });
  assert.deepEqual(o.api.held.files()[B], ["drops/3-b.png"]); assert.equal(o.api.held.files()[A], undefined); assert.equal(o.api.ships()[B], undefined);
});

test("round sixteen: a PICKED frame (the extension's 📎 / editor handoff, the kernel's native dialog) stands for no upload — it lands on the active composer only, retires nothing, releases nothing, and is said when no session is open", () => {
  // (d) a composer pick while a comment ship for the same session is pending (its popover closed): the pick is the composer's
  const w = receiving(); w.api.ship(A, "doc.txt", "c1", "QUJD", "comment");
  w.api.ack({ type: "droppedPath", path: "/synthetic/doc.txt", picked: true });
  assert.deepEqual(w.api.held.files()[A], ["/synthetic/doc.txt"], "the pick, on the active composer"); assert.deepEqual(w.api.ships()[A].map((p) => p.shipId), ["c1"], "the comment's ship untouched — though its name matches"); assert.deepEqual(w.HOOKS.toasts, []);
  // (e) no active tab: said, nothing placed
  const v = world({ activeId: null, mru: [], order: [A, B], nextActive: null, store: {}, sets: { "2": [] } }); v.api.ship(A, "doc.txt", "c1", "QUJD");
  v.api.ack({ type: "droppedPath", path: "/synthetic/doc.txt", picked: true });
  assert.ok(v.HOOKS.toasts.some((t) => /doc\.txt was picked, but no session is open/.test(t))); assert.equal(v.api.held.files()[A], undefined); assert.deepEqual(v.api.ships()[A].map((p) => p.shipId), ["c1"]);
  // (f) the round-fifteen probe with the pick tagged: A active, B's sole ship and held send — B untouched, nothing sent
  const f = receiving(); f.api.draft(B, "B words waiting"); f.api.ship(B, "b.png", "b1", "QUJD"); f.api.holdSend(B);
  f.api.ack({ type: "droppedPath", path: "/synthetic/b.png", picked: true });   // even a pick whose NAME matches B's upload
  assert.deepEqual(f.api.held.files()[A], ["/synthetic/b.png"]); assert.equal(f.api.held.files()[B], undefined); assert.deepEqual(f.api.ships()[B].map((p) => p.shipId), ["b1"]); assert.deepEqual(f.api.heldSend(), [B]);
  assert.deepEqual(f.HOOKS.sent.filter((m) => m.type === "sendMessage"), []);
});

test("round sixteen: a legacy (untagged) nack is matched by name and fails that ship under its kind's rule; matched to nothing, it is said and nothing is touched", () => {
  const w = receiving(); w.api.ship(A, "a.png", "a1", "QUJD"); w.api.holdSend(A); w.api.ship(B, "b.png", "b1", "QUJD"); w.api.holdSend(B);
  w.api.shipFail("nobody.png", undefined as unknown as string);   // no ship of that name
  assert.ok(w.HOOKS.toasts.some((t) => /nobody\.png could not be read/.test(t))); assert.deepEqual(w.api.heldSend(), [A, B], "both holds stand"); assert.equal(Object.keys(w.api.ships()).length, 2);
  w.api.shipFail("a.png", w.api.legacyFor("a.png") as string);   // resolved by name, as the nack branch resolves it
  assert.equal(w.api.ships()[A], undefined, "A's ship failed"); assert.deepEqual(w.api.heldSend(), [B], "A's hold cancelled, B's stands");
});

// ---- round seventeen ----

test("round seventeen: two hosts each with a pending upload of one name — an answer settles only the ANSWERING host's ship; the local kernel's answer never touches a remote host's", () => {
  const w = receiving();
  w.api.draft(RA, "remote words"); w.api.ship(RA, "same.txt", "r1", "QUJD"); w.api.holdSend(RA);   // TESTHOST's session uploads same.txt first
  w.api.ship(A, "same.txt", "a1", "QUJD"); w.api.holdSend(A); w.api.type(TYPED);                  // the local session too
  w.api.ack({ type: "droppedPath", path: "drops/1-same.txt", host: "TESTHOST" });   // TESTHOST's legacy answer, stamped by federation
  assert.equal(w.api.ships()[RA], undefined, "the remote ship retired"); assert.deepEqual(w.api.ships()[A].map((p) => p.shipId), ["a1"], "the local ship untouched though it is the same name");
  assert.deepEqual(w.api.held.files()[RA], ["drops/1-same.txt"], "the file lands on the remote session"); assert.equal(w.api.held.files()[A], undefined, "nothing on the local session's strip");
  assert.deepEqual(w.HOOKS.sent.filter((m) => m.type === "sendMessage"), [], "an untagged answer sends nothing (round nineteen)"); assert.deepEqual(w.api.heldSend(), [A], "the remote hold cancelled, the local one stands"); assert.equal(w.api.held.drafts()[RA], "remote words");
  w.api.ack({ type: "droppedPath", path: "drops/2-same.txt" });   // the local kernel's legacy answer: no host key
  assert.equal(w.api.ships()[A], undefined); assert.equal(w.HOOKS.fired, 0, "the local match attaches and cancels — never fires"); assert.deepEqual(w.api.heldSend(), []); assert.equal(w.api.composer(), TYPED);
});



// ---- round nineteen ----
test("round nineteen: two same-name TAGGED uploads with held sends both release normally — an up-to-date kernel names its uploads, and no name heuristic touches them", () => {
  const w = receiving();
  w.api.draft(B, "B words"); w.api.ship(B, "same.bin", "b1", "QUJD"); w.api.holdSend(B);
  w.api.type(TYPED); w.api.holdSend(A); w.api.ship(A, "same.bin", "a1", "QUJD");
  assert.deepEqual(w.api.heldSend(), [B, A], "both holds stand: nothing is cancelled for a name a tagged kernel will name");
  w.api.ack({ type: "droppedPath", path: "drops/1-same.bin", shipId: "a1" });
  assert.equal(w.HOOKS.fired, 1, "A's tagged answer releases A's send"); assert.deepEqual(w.api.held.files()[A], ["drops/1-same.bin"]);
  w.api.ack({ type: "droppedPath", path: "drops/2-same.bin", shipId: "b1" });
  assert.deepEqual(w.HOOKS.sent.filter((m) => m.type === "sendMessage").map((m) => ({ id: m.id, text: m.text })), [{ id: B, text: "B words\ndrops/2-same.bin" }], "B's tagged answer releases B's send, by sid, with B's file");
  assert.deepEqual(w.api.heldSend(), []); assert.equal(w.api.busy(), false); assert.deepEqual(w.HOOKS.toasts, []);
});

test("round nineteen: untagged answers have no send side effects — across a reconnect seam and a near-name pair, each answer attaches its best guess, cancels that owner's hold with the notice, and nothing is ever sent automatically", () => {
  const w = receiving();
  w.api.ship(A, "x-foo.txt", "a1", "QUJD"); w.api.type(TYPED); w.api.holdSend(A);   // A's upload, posted first
  w.api.draft(B, "B words"); w.api.ship(B, "foo.txt", "b1", "QUJD"); w.api.holdSend(B);   // B's, a near name, posted second
  w.api.wsdown(); w.api.wsup();   // the reconnect re-posts both (postSeq rewritten) while the old socket's answers may still be draining
  w.api.ack({ type: "droppedPath", path: "drops/1-x-foo.txt" });   // exact name: A's
  assert.equal(w.api.ships()[A], undefined, "A's chip retired"); assert.deepEqual(w.api.held.files()[A], ["drops/1-x-foo.txt"]); assert.deepEqual(w.api.ships()[B].map((p) => p.shipId), ["b1"], "no suffix relation: B's foo.txt is not x-foo.txt");
  assert.deepEqual(w.api.heldSend(), [B], "A's hold cancelled"); assert.equal(w.HOOKS.fired, 0);
  w.api.ack({ type: "droppedPath", path: "drops/2-foo.txt" });   // exact name: B's
  assert.equal(w.api.ships()[B], undefined); assert.deepEqual(w.api.held.files()[B], ["drops/2-foo.txt"]); assert.deepEqual(w.api.heldSend(), []);
  assert.deepEqual(w.HOOKS.sent.filter((m) => m.type === "sendMessage" || m.type === "askFollowUp"), [], "nothing sent, by either answer"); assert.equal(w.HOOKS.fired, 0);
  assert.equal(w.HOOKS.toasts.filter((t) => /older kernel that names no upload/.test(t)).length, 2, "one notice per cancelled hold"); assert.equal(w.api.composer(), TYPED); assert.equal(w.api.held.drafts()[B], "B words");
});

test("round nineteen: an untagged nack fails ONE best-guess ship — the first posted of that exact name — and cancels that owner's hold with the failure's own notice; a second same-name ship stands", () => {
  const n = receiving(); n.api.draft(B, "B words"); n.api.ship(B, "same.bin", "b1", "QUJD"); n.api.holdSend(B); n.api.holdSend(A); n.api.ship(A, "same.bin", "a1", "QUJD");
  assert.deepEqual(n.api.heldSend(), [B, A], "nothing cancelled at the post: no name is ambiguous for a kernel that names its uploads");
  n.api.shipFail("same.bin", n.api.legacyFor("same.bin") as string);   // a legacy nack: the first-posted of that exact name
  assert.equal(n.api.ships()[B], undefined, "B's, posted first, is the one failed"); assert.deepEqual(n.api.ships()[A].map((p) => p.shipId), ["a1"], "A's stands");
  assert.deepEqual(n.api.heldSend(), [A], "B's hold cancelled by the failure, A's stands"); assert.ok(n.HOOKS.toasts.some((t) => /same\.bin could not be read.*NOT sent/.test(t))); assert.equal(n.api.legacyFor("nobody.bin"), undefined, "no such name: no guess");
});

// ---- round twenty ----
test("round twenty: an UNMATCHED untagged answer that lands on the active composer disarms that composer's automatic send — its own later tagged answer attaches and sends NOTHING; a pick does not disarm", () => {
  const w = receiving();   // A is the active session, current kernel
  w.api.ship(A, "a.png", "a1", "QUJD"); w.api.type(TYPED); w.api.holdSend(A);
  w.api.ack({ type: "droppedPath", path: "drops/9-foreign.png", host: "TESTHOST" });   // a legacy remote's late answer: its chip was ✕'d, no record matches — the active composer takes the file, as on main
  assert.deepEqual(w.api.held.files()[A], ["drops/9-foreign.png"], "attached to A"); assert.deepEqual(w.api.ships()[A].map((p) => p.shipId), ["a1"], "A's own upload still pending");
  assert.deepEqual(w.api.heldSend(), [], "A's hold disarmed"); assert.ok(w.HOOKS.toasts.some((t) => /arrived from an older kernel that names no upload and was attached here/.test(t)), "said: " + JSON.stringify(w.HOOKS.toasts));
  w.api.ack({ type: "droppedPath", path: "drops/1-a.png", shipId: "a1" });   // A's own tagged answer
  assert.deepEqual(w.api.held.files()[A], ["drops/9-foreign.png", "drops/1-a.png"], "the file attached"); assert.equal(w.HOOKS.fired, 0, "NOTHING sent: the foreign file would have ridden the message"); assert.deepEqual(w.HOOKS.sent.filter((m) => m.type === "sendMessage"), []);
  assert.equal(w.api.composer(), TYPED, "the words stay for the user"); assert.equal(w.api.busy(), false);
  const v = receiving(); v.api.ship(A, "a.png", "a1", "QUJD"); v.api.type(TYPED); v.api.holdSend(A);
  v.api.ack({ type: "droppedPath", path: "/synthetic/pick.txt", picked: true });   // the user's own pick on the active composer
  assert.deepEqual(v.api.heldSend(), [A], "a pick is the user's act: the hold stands"); assert.deepEqual(v.api.held.files()[A], ["/synthetic/pick.txt"]);
  v.api.ack({ type: "droppedPath", path: "drops/1-a.png", shipId: "a1" });
  assert.equal(v.HOOKS.fired, 1, "…and A's tagged answer releases it, the pick riding along"); assert.deepEqual(v.HOOKS.toasts, []);
});

// ---- round twenty-one ----
test("round twenty-one: an older kernel's guessed attachment makes the composer UNVERIFIED — durably: a provisional's hold does not transfer onto it, its tagged answers send nothing, a reload remembers, the gate refuses to wait; the user's ✕ on the legacy chip verifies it again and a new hold fires", () => {
  const w = world({ activeId: A, mru: [A], order: [A], nextActive: A, store: {}, sets: { "": [A] } });   // A active; a dismissal falls back to A
  w.api.ship(A, "a.png", "a1", "QUJD"); w.api.type(TYPED); assert.equal(w.api.holdSend(A), true);
  w.api.ack({ type: "droppedPath", path: "drops/9-foreign.png", host: "TESTHOST" });   // an unmatched legacy answer: attached to A by the fallback
  assert.equal(w.api.unverified(A), true, "A is unverified"); assert.deepEqual(w.api.heldSend(), [], "A's hold gone"); assert.deepEqual((w.store.files as any)[A], [{ path: "drops/9-foreign.png", legacy: true }], "…and the mark is on disk, on the entry");
  assert.equal(w.api.holdSend(A), false, "no hold may be armed on it"); assert.ok(w.HOOKS.toasts.some((t) => /can't be sent automatically/.test(t)));
  const r = world({ activeId: null, mru: [], order: [A], nextActive: null, store: w.store, sets: { "": [A] } });   // a reload over the same store
  assert.equal(r.api.unverified(A), true, "the reload remembers");
  w.api.startCreate(REQ); const P = w.api.state().provisionalId!;   // a create in flight, with its own upload and a held send
  w.api.ship(P, "p.png", "p1", "QUJD"); w.api.type("P words"); assert.equal(w.api.holdSend(P), true);
  w.api.resolveTo(A);   // the kernel: the create is A, running
  assert.deepEqual(w.api.heldSend(), [], "P's hold is NOT transferred onto the unverified A: cancelled"); assert.equal(w.HOOKS.toasts.filter((t) => /can't be sent automatically/.test(t)).length >= 2, true, "…and said");
  assert.deepEqual(w.api.ships()[A].map((p) => p.shipId), ["a1", "p1"], "P's upload is A's now"); assert.ok((w.api.held.drafts()[A] || "").includes("P words"), "P's words moved");
  w.api.ack({ type: "droppedPath", path: "drops/1-a.png", shipId: "a1" }); w.api.ack({ type: "droppedPath", path: "drops/2-p.png", shipId: "p1" });
  assert.deepEqual(w.api.held.files()[A], ["drops/9-foreign.png", "drops/1-a.png", "drops/2-p.png"]); assert.equal(w.HOOKS.fired, 0, "nothing sent"); assert.deepEqual(w.HOOKS.sent.filter((m) => m.type === "sendMessage"), []);
  w.api.removeFile(A, 0);   // the user's ✕ on the legacy chip
  assert.equal(w.api.unverified(A), false, "verified again"); assert.ok(!((w.store.files as any)[A] || []).some((e: any) => e.legacy), "…on disk too");
  w.api.ship(A, "z.png", "z1", "QUJD"); assert.equal(w.api.holdSend(A), true, "a NEW hold may be armed");
  w.api.ack({ type: "droppedPath", path: "drops/3-z.png", shipId: "z1" });
  assert.equal(w.HOOKS.fired, 1, "…and fires normally");
});

test("round twenty-one: the mark travels with the file across the hand-off — the receiving pane is unverified and a hold it held is cancelled; a legacy answer matched to its own ship marks that owner too", () => {
  const w = world({ activeId: C, mru: [C], order: [A, B, C], nextActive: null, store: {}, sets: { "2": [] } });
  w.api.ship(A, "a.png", "a1", "QUJD"); w.api.draft(A, "A words");
  w.api.ack({ type: "droppedPath", path: "drops/1-a.png" });   // a legacy answer matched to A's own ship: attached, A unverified
  assert.equal(w.api.unverified(A), true);
  const st = w.api.take(A);
  assert.deepEqual(st.files, [{ path: "drops/1-a.png", legacy: true }], "the file rides the state with its provenance (round twenty-two)"); assert.equal(w.api.unverified(A), false, "…and leaves the source with the file");
  const v = receiving(); v.api.ship(A, "v.png", "v1", "QUJD"); assert.equal(v.api.holdSend(A), true);
  v.api.adoptState(A, st);
  assert.equal(v.api.unverified(A), true, "the receiving pane is unverified"); assert.deepEqual(v.api.heldSend(), [], "its hold cancelled"); assert.ok(v.HOOKS.toasts.some((t) => /can't be sent automatically/.test(t)));
  assert.deepEqual(v.api.held.files()[A], ["drops/1-a.png"]);
});

// ---- round twenty-two ----
test("round twenty-two: the mark lives on the entry — a path held twice is unverified twice: one ✕ leaves it unverified, no hold arms, a tagged answer sends nothing; the second ✕ verifies it and a new hold fires with the verified files only", () => {
  const w = world({ activeId: A, mru: [A], order: [A], nextActive: A, store: {}, sets: { "": [A] } });
  w.api.ack({ type: "droppedPath", path: "drops/9-L.png", host: "TESTHOST" });   // an unmatched legacy answer: L attached to the active A, unverified
  w.api.adoptState(A, { files: [{ path: "drops/9-L.png", legacy: true }] });      // a hand-off brings another L, marked
  assert.deepEqual(w.api.held.entries()[A], [{ path: "drops/9-L.png", legacy: true }, { path: "drops/9-L.png", legacy: true }], "held twice, marked twice");
  w.api.removeFile(A, 0);   // the user ✕'s one
  assert.equal(w.api.unverified(A), true, "one L remains — still unverified"); assert.equal(w.api.holdSend(A), false, "no hold may be armed");
  w.api.ship(A, "v.png", "v1", "QUJD"); w.api.type(TYPED);
  w.api.ack({ type: "droppedPath", path: "drops/1-v.png", shipId: "v1" });
  assert.equal(w.HOOKS.fired, 0, "a tagged answer sends nothing"); assert.deepEqual(w.api.held.files()[A], ["drops/9-L.png", "drops/1-v.png"]);
  w.api.removeFile(A, 0);   // the second L
  assert.equal(w.api.unverified(A), false, "verified"); assert.deepEqual(w.api.held.files()[A], ["drops/1-v.png"]);
  w.api.ship(A, "z.png", "z1", "QUJD"); assert.equal(w.api.holdSend(A), true, "a new hold arms");
  w.api.ack({ type: "droppedPath", path: "drops/2-z.png", shipId: "z1" });
  assert.equal(w.HOOKS.fired, 1, "…and fires with the verified files only");
});

test("round twenty-two: the refused rescind's rollback restores a legacy file WITH its mark — the ✕ in the cancel window is overridden as before, never its provenance", () => {
  const w = receiving();
  w.api.ack({ type: "droppedPath", path: "drops/9-L.png", host: "TESTHOST" });   // L attached after the message was queued: unverified
  const stash = { before: "", after: "", cites: [], files: JSON.parse(JSON.stringify(w.api.held.entries()[A])), armedCites: [], armedFiles: ["drops/5-armed.png"] };   // the press stashed the strip as it stood, then armed its own file
  w.api.ack({ type: "droppedPath", path: "drops/5-armed.png", shipId: "none" });   // (the armed file arrives by any road: here a tagged frame for no ship is dropped, so attach it as the press would)
  w.api.rollback(A, { ...stash, files: [] }); w.api.removeFile(A, 0);   // (clear the way: nothing before, L gone) — now the real sequence:
  w.api.ack({ type: "droppedPath", path: "drops/9-L.png", host: "TESTHOST" });
  const armedStash = { before: "", after: "", cites: [], files: JSON.parse(JSON.stringify(w.api.held.entries()[A])), armedCites: [], armedFiles: ["drops/5-armed.png"] };
  w.api.adoptState(A, { files: ["drops/5-armed.png"] });   // the press's own file, verified
  w.api.removeFile(A, 0);   // the user ✕'s L inside the cancel window
  assert.equal(w.api.unverified(A), false);
  w.api.rollback(A, armedStash);   // cancelResult ok:false
  assert.deepEqual(w.api.held.entries()[A], [{ path: "drops/9-L.png", legacy: true }], "the armed file goes, L comes back WITH its mark"); assert.equal(w.api.unverified(A), true, "unverified again");
});

test("round twenty-two: entries round-trip through the store with their provenance; an older store's bare paths load as verified entries", () => {
  const store: Record<string, unknown> = {};
  const w = world({ activeId: A, mru: [A], order: [A], nextActive: A, store, sets: { "": [A] } });
  w.api.ack({ type: "droppedPath", path: "drops/9-L.png", host: "TESTHOST" }); w.api.adoptState(A, { files: ["drops/1-ok.png"] });
  assert.deepEqual((store.files as any)[A], [{ path: "drops/9-L.png", legacy: true }, { path: "drops/1-ok.png", legacy: false }], "persisted as entries");
  const r = world({ activeId: null, mru: [], order: [A], nextActive: null, store, sets: { "": [A] } });
  assert.deepEqual(r.api.held.entries()[A], [{ path: "drops/9-L.png", legacy: true }, { path: "drops/1-ok.png", legacy: false }], "back with their marks"); assert.equal(r.api.unverified(A), true);
  const o = world({ activeId: null, mru: [], order: [A], nextActive: null, store: { files: { [A]: ["drops/old-1.png", "drops/old-2.png"] } }, sets: { "": [A] } });   // a store from before the entries
  assert.deepEqual(o.api.held.entries()[A], [{ path: "drops/old-1.png", legacy: false }, { path: "drops/old-2.png", legacy: false }], "bare paths load as verified entries"); assert.equal(o.api.unverified(A), false);
});
