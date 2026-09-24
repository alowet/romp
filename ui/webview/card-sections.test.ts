// THE SHARED CARD BUILDER, EXECUTED (round two of the box content PR, the verifier's low a): the feed card and the Needs you row draw the
// card's section toggles, its swirl caption and its name-row state badges through card-sections.ts, so the conditions, the precedence, the
// order and the wording live in one place and are pinned here by running that place. The module builds DOM, so a small plain-object stand-in
// (the pr-links test's idiom) provides createElement and createTextNode before the module loads; nothing here needs layout. The wiring of
// both pages into the module is pinned at the source below, the way the other webview tests pin the renderers.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import * as mod from "./card-sections";
const { buildSectionElements, stateBadges, cardSpin, BADGE_WORDS } = mod;

// ── a DOM stand-in: elements and text nodes with the members the builder touches ────────────────────────────
class T { nodeType = 3; parentNode: E | null = null; constructor(public textContent: string) {} }
class E {
  nodeType = 1; parentNode: E | null = null; childNodes: Array<E | T> = [];
  className = ""; title = ""; type = ""; onclick: ((ev: unknown) => void) | null = null;
  style: Record<string, string> = {}; dataset: Record<string, string | undefined> = {};
  attrs = new Map<string, string>();
  constructor(public tagName: string) {}
  get classList() {
    const self = this;
    const set = () => new Set(self.className.split(/\s+/).filter(Boolean));
    const write = (s: Set<string>) => { self.className = Array.from(s).join(" "); };
    return {
      add: (...cs: string[]) => { const s = set(); cs.forEach((c) => s.add(c)); write(s); },
      remove: (...cs: string[]) => { const s = set(); cs.forEach((c) => s.delete(c)); write(s); },
      toggle: (c: string, on?: boolean) => { const s = set(); const want = on === undefined ? !s.has(c) : on; if (want) s.add(c); else s.delete(c); write(s); return want; },
      contains: (c: string) => set().has(c),
    };
  }
  get textContent(): string { return this.childNodes.map((n) => n.textContent).join(""); }
  set textContent(v: string | null) { this.childNodes = v ? [new T(v)] : []; }
  get children(): E[] { return this.childNodes.filter((n): n is E => n instanceof E); }
  private adopt(n: E | T | string): E | T { const node = typeof n === "string" ? new T(n) : n; node.parentNode = this; return node; }
  append(...ns: Array<E | T | string>) { for (const n of ns) this.childNodes.push(this.adopt(n)); }
  appendChild(n: E | T) { this.childNodes.push(this.adopt(n)); return n; }
  prepend(...ns: Array<E | T | string>) { this.childNodes.unshift(...ns.map((n) => this.adopt(n))); }
  replaceChildren(...ns: Array<E | T | string>) { this.childNodes = ns.map((n) => this.adopt(n)); }
  insertBefore(n: E | T, ref: E | T | null) { const node = this.adopt(n); const i = ref ? this.childNodes.indexOf(ref) : -1; if (i < 0) this.childNodes.push(node); else this.childNodes.splice(i, 0, node); return node; }
  get nextSibling(): E | T | null { const p = this.parentNode; if (!p) return null; const i = p.childNodes.indexOf(this); return i >= 0 && i + 1 < p.childNodes.length ? p.childNodes[i + 1] : null; }
  setAttribute(k: string, v: string) { this.attrs.set(k, v); }
  getAttribute(k: string) { return this.attrs.has(k) ? this.attrs.get(k)! : null; }
  removeAttribute(k: string) { this.attrs.delete(k); }
  querySelectorAll() { return [] as E[]; }
  querySelector() { return null; }
  addEventListener() { /* the styled tip wires hover listeners on the interrupting chip */ }
  removeEventListener() {}
}
// the module touches document only when a builder runs (its load creates the section channel, which needs none), so a static import is
// fine with the stand-in installed at module level, before any test runs (the test bundle is CommonJS: no top-level await)
(globalThis as any).document = { createElement: (tag: string) => new E(tag.toUpperCase()), createTextNode: (t: string) => new T(t),
                                  body: new E("BODY"), documentElement: new E("HTML"), addEventListener() {}, removeEventListener() {} };   // the styled tip (tip.ts) wires document listeners on first use

const env = {
  durNodes: (since: number | null | undefined) => (since ? [" · ", Object.assign(new E("SPAN"), { className: "dur" }) as unknown as HTMLElement] : []),
  openSession: (_sid: string) => { opened.push(_sid); },
  clockHM: (t: number) => "hm" + t,
  openWarns: (it: unknown, title: string) => { warnsOpened.push(title); },
  workDot: (peer: HTMLElement, name: string) => { (peer as unknown as E).dataset.dot = name; },
};
let opened: string[] = [], warnsOpened: string[] = [];
const badges = (it: Parameters<typeof stateBadges>[0], caption: string | null = null) => stateBadges(it, env as any, caption) as unknown as E[];
const classes = (els: E[]) => els.map((e) => e.className);

test("buildSectionElements: the card's toggles in the card's order, the bodies they drive, the checklist and the swirl box", () => {
  const se = buildSectionElements() as unknown as Record<string, any>;
  assert.deepEqual((se.toggles as E[]).map((b) => [b.tagName, b.className, b.textContent]),
    [["BUTTON", "fask-secbtn", "Background"], ["BUTTON", "fask-secbtn", "Summary"], ["BUTTON", "fask-secbtn fask-stallbtn", "Stalled"], ["BUTTON", "fask-secbtn", "Sub-goals"], ["BUTTON", "fask-secbtn fask-taskbtn", ""]],
    "Background · Summary · Stalled · Sub-goals · Awaiting task, one element each, built for both pages");
  assert.deepEqual([se.subBtn.style.display, se.stallBtn.style.display, se.taskBtn.style.display], ["none", "none", "none"], "the three conditional toggles start hidden; applySections shows them");
  assert.deepEqual((se.secs as E).children.map((c) => c.className), ["fask-bg-body", "fask-distill", "fask-stall-body"], "the bodies only, in the toggles' order; the toggles ride the caller's row");
  assert.equal((se.checklist as E).className, "fask-checklist");
  assert.deepEqual((se.awaitSpin as E).children.map((c) => [c.className, c.getAttribute("aria-hidden")]), [["fask-awaiting-swirl", "true"], ["fask-awaiting-why", null]], "the swirl glyph (decoration) and its why");
  assert.equal((se.awaitSpin as E).style.display, "none", "no caption yet");
  assert.deepEqual((se.taskBtn as E).children.map((c) => c.className), ["fask-awaiting-swirl", "fask-taskbtn-lbl"], "the Awaiting task pill: the mini swirl and its label");
});

test("stateBadges: nothing for a plain item; each state its badge with the card's words", () => {
  assert.deepEqual(badges({}), []);
  assert.deepEqual(badges({ recheck: true }).map((b) => [b.className, b.textContent, b.title]), [["fask-followedup", BADGE_WORDS.rejudging.text, BADGE_WORDS.rejudging.title]]);
  assert.equal(BADGE_WORDS.rejudging.text, "↩ re-judging");
  assert.deepEqual(badges({ doneConfirming: true }).map((b) => [b.className, b.textContent]), [["fask-doneconfirming", "done, confirming"]]);
  assert.deepEqual(badges({ nudgeFailed: true }).map((b) => [b.className, b.textContent, b.title]), [["fask-nudgefailed", "follow-up failed", BADGE_WORDS.nudgeFailed.title]]);
  assert.deepEqual(badges({ interrupting: true }).map((b) => [b.className, b.textContent]), [["fask-interrupting", "interrupting…"]]);
  assert.deepEqual(badges({ interrupted: true }).map((b) => [b.className, b.textContent, b.title]), [["fask-interrupted", "interrupted", BADGE_WORDS.interrupted.title]]);
});

test("stateBadges: the card's precedence: the swirl's Analyzing caption replaces the re-judging chip; a plain reply (rejudging) never wears it; follow-up failed outranks both interrupt words; the interrupt words never show together", () => {
  assert.deepEqual(badges({ recheck: true }, "Analyzing…"), [], "the swirl already says it (the user 2026-06-29: don't show both)");
  assert.deepEqual(badges({ rejudging: true }), [], "rejudging: the swirl is the ONLY cue (the medium of round two: the row wore the chip where the card withheld it)");
  assert.deepEqual(classes(badges({ nudgeFailed: true, interrupting: true, interrupted: true })), ["fask-nudgefailed"]);
  assert.deepEqual(classes(badges({ interrupting: true, interrupted: true })), ["fask-interrupting"], "in flight outranks settled");
  assert.deepEqual(classes(badges({ interrupted: true, nudgeFailed: false })), ["fask-interrupted"]);
});

test("stateBadges: the warning chip, a focusable button, its label by the warns' family, its hover the attempt history or the last message, its click the page's detail", () => {
  warnsOpened = [];
  const one = badges({ text: "wire the fixtures", warns: [{ kind: "brief-failed", t: 1, msg: "the brief could not be written", detail: "" }] });
  assert.deepEqual(one.map((b) => [b.tagName, b.className, b.textContent]), [["BUTTON", "fask-warnchip", "distill failed"]], "every warn the distiller's own → 'distill failed'");
  assert.equal(one[0].title, "the brief could not be written\n— click for what happened and why");
  assert.equal(one[0].dataset.act, "sec-open-warns", "delegated: the act, routed by sectionActs with the host's freshest item");
  const two = badges({ warns: [{ kind: "brief-failed", t: 1, msg: "a", detail: "" }, { kind: "cite-miss", t: 2, msg: "the cite missed", detail: "" }] });
  assert.equal(two[0].textContent, "warning ×2", "a mixed family counts as warnings");
  const logged = badges({ warns: [{ kind: "summary-failed", t: 1, msg: "m", detail: "" }], failLog: [{ t: 5, line: "", model: "opus", note: "529" }] });
  assert.equal(logged[0].title, "hm5 tried opus — 529\n— click for what happened and why", "the attempt history when one exists (the user 2026-08-18)");
});

test("stateBadges: the peer wait, the origin, the handoff and the tracked delegation, with their clicks", () => {
  opened = [];
  const w = badges({ waitingOn: { name: "api", kind: "delegate", since: 10 } });
  assert.deepEqual(w.map((b) => [b.className, b.textContent]), [["fask-waiton", "Handed off to api · "]], "a delegate wait; the live duration rides its own element");
  assert.deepEqual(classes(badges({ waitingOn: { name: "api", inCycle: true } })), ["fask-waiton fask-waiton-cycle"]);
  assert.equal(badges({ waitingOn: { name: "api", inCycle: true } })[0].textContent, "Deadlock api");
  assert.equal(badges({ waitingOn: { name: "api" } })[0].textContent, "Awaiting api");
  const o = badges({ origin: { peer: "api", peerSid: "s-api", live: false } });
  assert.deepEqual(o.map((b) => [b.tagName, b.className, b.textContent]), [["A", "fask-origin fask-origin-absorbed", "↪ from api"]], "absorbed: the same badge, dimmed, never removed");
  assert.deepEqual([o[0].dataset.act, o[0].dataset.sid], ["sec-open-session", "s-api"], "delegated: the act names the sender");
  assert.equal(badges({ origin: { peer: "api", peerSid: "s-api", live: true } })[0].className, "fask-origin");
  const h = badges({ handoffTo: { peer: "tests", peerSid: "s-t" } });
  assert.deepEqual([h[0].textContent, h[0].dataset.act, h[0].dataset.sid], ["↪ delegated to tests", "sec-open-session", "s-t"], "a handoff alone: the anchor opens the recipient");
  const d = badges({ delegTracked: [{ sid: "s1", name: "web" }, { sid: "s2", name: "api" }] });
  assert.equal(d[0].textContent, "↪ delegated to web, api"); assert.equal(d[0].dataset.act, undefined, "a tracked delegation alone: the anchor itself opens nothing; each recipient does");
  assert.deepEqual(d[0].children.filter((c) => c.className === "fask-origin-peer").map((c) => [c.dataset.dot, c.dataset.act, c.dataset.sid]), [["web", "sec-open-session", "s1"], ["api", "sec-open-session", "s2"]], "the page's live dot before each recipient (the feed's workDot), each with its own click");
  // STACKED, as the card always drew it (the verifier's round two): ONE anchor, " · " between the facts, the absorbed class dimming the whole badge
  const stacked = badges({ origin: { peer: "api", peerSid: "s-api", live: false }, handoffTo: { peer: "tests", peerSid: "s-t" }, delegTracked: [{ sid: "s1", name: "web" }] });
  assert.equal(stacked.length, 1, "one anchor for the three facts");
  assert.deepEqual([stacked[0].className, stacked[0].textContent, stacked[0].dataset.sid], ["fask-origin fask-origin-absorbed", "↪ from api · ↪ delegated to tests · ↪ delegated to web", "s-api"], "the sender first, the separators, the whole badge absorbed; the anchor's own click opens the sender");
  assert.deepEqual(stacked[0].children.filter((c) => c.className === "fask-origin-peer").map((c) => c.dataset.sid), ["s-api", "s-t", "s1"].map((x, i) => i === 0 ? undefined : x), "the recipients carry their own clicks; the sender's name is the anchor's");
});

test("stateBadges: the card's order when every badge shows", () => {
  const all = badges({ recheck: true, doneConfirming: true, nudgeFailed: true, interrupting: true, interrupted: true,
                       warns: [{ kind: "x", t: 1, msg: "m", detail: "" }], waitingOn: { name: "api" },
                       origin: { peer: "api", peerSid: "s" }, handoffTo: { peer: "tests", peerSid: "t" }, delegTracked: [{ sid: "u", name: "docs" }] });
  assert.deepEqual(classes(all), ["fask-origin", "fask-followedup", "fask-doneconfirming", "fask-nudgefailed", "fask-warnchip", "fask-waiton"],
    "the one provenance anchor (origin, the handoff and the tracked delegation stacked in it), re-judging, done confirming, follow-up failed (the interrupt words yield to it), the warning chip, the peer wait");
  assert.equal(all[0].textContent, "↪ from api · ↪ delegated to tests · ↪ delegated to docs");
});

test("cardSpin: a targeted follow-up (recheck) and a plain reply (rejudging) both say Analyzing…, so neither wears the chip beside the swirl", () => {
  const clock = { nowSec: () => 1000 };
  assert.equal(cardSpin({ recheck: true, blockSummary: "the brief" }, false, true, clock).caption, "Analyzing…");
  assert.equal(cardSpin({ rejudging: true, blockSummary: "the brief" }, false, true, clock).caption, "Analyzing…");
  assert.equal(cardSpin({ blockSummary: "the brief", blocked: {} }, false, true, clock).caption, null, "a blocked card with its brief: no spin");
  assert.deepEqual(badges({ recheck: true }, cardSpin({ recheck: true, blockSummary: "b" }, false, true, clock).caption), [], "the rule, end to end");
});

// ── the wiring: both pages draw through the module ─────────────────────────────────────────────────────────
const W = (f: string) => fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", f), "utf8");
const FEED = W("feed.ts"), RENDER = W("render.ts"), MOD = W("card-sections.ts");
test("the feed card and the Needs you row build the toggles, draw the swirl, the landings and the badges through the shared module, and never keep a copy", () => {
  assert.match(FEED, /const se = buildSectionElements\(\);\s*\n\s*const \{ bgBtn, bgBody, takeBtn, distill, subBtn, stallBtn, stallBody, taskBtn, taskLbl, secs, checklist, awaitSpin, awaitWhy \} = se;/, "the card's elements");
  assert.match(FEED, /row3\.append\(\.\.\.se\.toggles, actions\);/, "in the builder's order");
  assert.match(RENDER, /const se = buildSectionElements\(\);/, "the row's elements"); assert.match(RENDER, /secsRow\.append\(\.\.\.se\.toggles\);/);
  assert.match(FEED, /const spin = cardSpin\(it, dCompleted, dBlocked, sectionEnv\);[^\n]*\n\s*applySpin\(a, it, spin, sectionEnv\);\s*\n\s*const spinCaption = spin\.caption;/, "the card's swirl");
  assert.match(RENDER, /const spin = cardSpin\(it, dCompleted, dBlocked, noticeSectionEnv\); applySpin\(rowAny, it, spin, noticeSectionEnv\);/, "the row's swirl");
  assert.match(FEED, /a\._badges\.replaceChildren\(\.\.\.stateBadges\(it, sectionEnv, spinCaption\)\);/, "the card's badges, with the caption");
  assert.match(RENDER, /badgesEl\.replaceChildren\(\.\.\.stateBadges\(it, noticeSectionEnv, spin\.caption\)\);/, "the row's badges, with the caption");
  assert.match(FEED, /applyDistillLanding\(a, it, distillShown, dCompleted, dBlocked, sectionEnv\);/, "the card's line");
  assert.match(RENDER, /applyDistillLanding\(rowAny, it, shown, dCompleted, dBlocked, noticeSectionEnv\);/, "the row's line");
  assert.match(RENDER, /const \{ completed: dCompleted, blocked: dBlocked \} = distillInputs\(n\.distillState, n\.column \|\| ""\);/, "the row reads the card's distill rule (a stall floor with no brief yet reads blocked and shows the Distilling caption; before: the row's own copy read it as neither)");
  assert.match(RENDER, /applySections\(rowAny, it, !!shown, noticeSectionEnv\);\s*\n\s*applyRelayNote\(rowAny, n\);/, "the relayed question's line is drawn on the row after its sections");
  assert.match(FEED, /applyRelayNote\(a, it\);/, "and on the card through the same helper");
  assert.match(RENDER, /for \(const k of \["_secs", "_checklist", "_badges", "_awaitSpin", "_relayNote"\]\)/, "a row shedding its sections sheds the note too");
  // the Collapsed flag flipped with NO pick held: the feed's clear finds its map unchanged and posts no map, so the row's default follows from
  // the chat page's own listener on the settings key, which re-renders the box, and the row's update re-applies the sections on every render
  assert.match(RENDER, /onExternalSettingsChange\(\(\) => renderNotices\(\)\);/, "the box re-renders on the settings key's storage event");
  assert.match(RENDER, /applySections\(rowAny, it, !!shown, noticeSectionEnv\);/, "and every render re-applies the row's sections against the flag");
  for (const gone of [/fupBadge/, /nfBadge/, /intingBadge/, /warnChip/, /waitOnBadge/, /dcBadge/, /a\._followedup/, /a\._warnChip/, /a\._waitOn/, /a\._origin\b/, /spinFor\(/, /function relAge\(/])
    assert.doesNotMatch(FEED, gone, "no second copy in the feed: " + gone.source);
  assert.match(FEED, /row2\.append\(idwrap, retryBadge, apiBadge, apiRetry, apiLogin, capLine, capBtn, jauthBadge, blkBadge, badges\);/, "the name row's one badge slot");
  assert.match(MOD, /export function stateBadges\(it: BadgeItem, env: Pick<SectionEnv, "durNodes" \| "openSession" \| "clockHM" \| "openWarns" \| "workDot">, spinCaption: string \| null = null\): HTMLElement\[\] \{/);
});

test("every write to the section choice goes through the module's setters, which cross the shell's two documents; the feed owns the state and the chat page follows", () => {
  assert.doesNotMatch(FEED, /secChoice\.(set|clear|delete)\(/, "the feed's three writers (hydrate, prune, the Collapsed clear) go through replaceSectionChoices (the medium of round two: they never crossed the channel)");
  assert.match(FEED, /replaceSectionChoices\(Object\.entries\(st\.sec\) as \[string, SecChoice\]\[\], \{ quiet: true \}\);/, "hydration");
  assert.match(FEED, /replaceSectionChoices\(Object\.entries\(kept\.sec\) as \[string, SecChoice\]\[\], \{ quiet: true \}\);/, "the prune to the live set (quiet: the render applies every card next; a map that did not move is no change at all)");
  assert.match(MOD, /let same = next\.size === secChoice\.size;\s*\n\s*if \(same\) for \(const \[k, v\] of next\) if \(secChoice\.get\(k\) !== v\) \{ same = false; break; \}\s*\n\s*if \(same\) \{ if \(!opts\.quiet\) reapplyAllHosts\(\); return; \}/, "the whole-map setter posts and persists nothing when nothing moved (the prune runs on every render), and re-applies the hosts unless quiet, the default having moved");
  assert.match(FEED, /lastCollapsedPref = p\.collapsed; replaceSectionChoices\(\[\]\); \}/, "the Collapsed flip re-applies every card (the render gate would not) and posts the map");
  assert.match(FEED, /configureSectionSync\(\{ role: "owner", onChange: \(\) => persistViewState\(\) \}\);/, "the owner persists every change, a follower's pick included");
  assert.match(RENDER, /configureSectionSync\(\{ role: "follower" \}\);/, "the chat page says hello and takes the map");
  assert.match(MOD, /setSectionChoice\(id, choice === want \? "none" : want\);/, "a press writes through the setter");
  assert.match(MOD, /if \(d\.kind === "hello"\) \{ if \(syncRole === "owner"\) postSync\(\{ kind: "map", entries: Array\.from\(secChoice\.entries\(\)\) \}\); return; \}/, "the owner answers a hello with its map");
  assert.match(MOD, /if \(syncRole === "owner"\) postSync\(\{ kind: "map", entries: Array\.from\(secChoice\.entries\(\)\) \}\);\s*\n\s*else postSync\(\{ kind: "hello" \}\);/, "and posts it when it loads, for a follower already up");
  assert.match(MOD, /const sectionChannel: BroadcastChannel \| null = typeof window !== "undefined" && typeof \(window as \{ BroadcastChannel\?: unknown \}\)\.BroadcastChannel === "function" \? new window\.BroadcastChannel\("romp-card-sections"\) : null;/, "the WINDOW's channel only: Node's own kept the test process alive once a message was posted at load");
});

test("the row's landings are the chat page's own: the line and a paragraph scroll to the turn, a sub-goal row's text jumps to its work anchor, no anchor says so in the landing toast", () => {
  assert.match(RENDER, /landing: \(_it, target\) => \{[^\n]*\n\s*flashedAnchor = null; pendingAnchorQuote = target\.quote \?\? null; pendingAnchorClick = true;[^\n]*\n\s*scrollToAnchor\(target\.anchorUuid\);/,
    "the row's landing re-arms the flash, hands the quoted span over and marks the click as the reader's before it scrolls, as the other landers do (a contributor's post-merge note on PR 2124)");
  assert.match(RENDER, /txt\.classList\.add\("lz-nav"\); txt\.title = "jump to where this was worked on";[^\n]*\n\s*txt\.dataset\.act = "sec-landing"; txt\.dataset\.uuid = node\.anchorUuid;/, "a sub-goal's text: the landing act, delegated on #notices");
  assert.match(RENDER, /\.\.\.sectionActs\(noticeSectionEnv, \(el\) => el\.closest\("\.ntc-row"\) as HTMLElement \| null\),/, "the builder's acts installed on the box's stable root");
  assert.match(FEED, /delegate\(card, sectionActs\(sectionEnv, \(\) => card\)\);\s*\n[^\n]*\n\s*let pending: number \| undefined;\s*\n\s*card\.addEventListener\("click", \(\) => \{/, "and on each card, before the card's own open-modal click");
  assert.match(RENDER, /afterApply: \(a\) => \{ noticeRowLevelFace\(a\); noticeMoreButton\(a, noticeLineOf\(a\)\); \},/, "the chat page's after-apply: the items-level face and the More pass");
  assert.match(MOD, /\(h\._sectionEnv as SectionEnv\)\.afterApply\?\.\(c\);   \/\/ last/, "called last in every re-apply");
  assert.match(RENDER, /landToast\("couldn't locate this in the transcript — no anchor was recorded for this card"\);/);
  assert.match(RENDER, /if \(!body \|\| body\.style\.display === "none" \|\| \(!overflows && !open\)\) \{ if \(b\) b\.remove\(\); return; \}/, "no button over a hidden line, whatever the open state (the 0.17.1 fix: Less stood over the line a pick hid)");
  assert.match(RENDER, /collapsed: \(\) => noticeCollapsedPref\(\),/, "the row's default follows the feed's Collapsed flag in the browser");
  assert.match(RENDER, /function noticeCollapsedPref\(\): boolean \{ try \{ return JSON\.parse\(localStorage\.getItem\("romp:settings"\) \|\| "\{\}"\)\.collapsed === true; \} catch \{ return false; \} \}/);
  assert.doesNotMatch(RENDER, /openWarns: \(\) => \{/, "the chat page names no warn destination: the shared builder gives its chip no button role and no click sentence");
  assert.match(MOD, /if \(syncRole === "owner" && d\.from === "follower"\) postSync\(\{ kind: "ack", id: d\.id, choice: d\.choice \}\);/, "the owner acknowledges a follower's set alone");
  assert.match(MOD, /if \(!opts\.fromPeer && syncRole === "owner"\) postSync\(\{ kind: "map", entries: Array\.from\(secChoice\.entries\(\)\) \}\);/, "the map is the owner's word alone (the feed hydrates before it is configured as the owner)");
  assert.match(MOD, /if \(ownPicks\.has\(d\.id\) && ownPicks\.get\(d\.id\) === d\.choice\) ownPicks\.delete\(d\.id\);/, "the follower retires the pick the ack names as it stands");
  assert.match(RENDER, /refreshAges\(document\.querySelectorAll<HTMLElement>\("#notices \[data-age-t\]"\), noticeNowSec\(\), relAge, \(\) => ""\);/, "the row's stamped ages repainted by the page's own pass");
  assert.match(MOD, /else age\.textContent = env\.relAge\(0\);/, "a part with no event time: the static '<1m ago' (the medium of round two: the row printed an epoch-sized age)");
});

test("sectionActs: one delegated map for both pages, each act stopping the click at its root and reading the host's remembered item", () => {
  const { sectionActs, cardTreeExpanded } = mod as any;
  const calls: unknown[] = [];
  const env2 = { ...env, openSession: (sid: string) => calls.push(["open", sid]), openWarns: (it: any, title: string) => calls.push(["warns", it.itemId, title]),
                 landing: (it: any, t: any) => calls.push(["land", it.itemId, t.anchorUuid, t.quote]), noAnchor: (it: any) => calls.push(["none", it.itemId]) };
  const host = new E("DIV") as any; host._it = { itemId: "i1", sid: "s1", text: "wire the fixtures" };
  const acts = sectionActs(env2, () => host);
  let stopped = 0; const ev = { stopImmediatePropagation() { stopped++; } };
  const at = (act: string, data: Record<string, string>) => { const e = new E("SPAN"); Object.assign(e.dataset, { act, ...data }); return e; };
  acts["sec-open-session"](at("sec-open-session", { sid: "s-api" }), ev);
  acts["sec-open-warns"](at("sec-open-warns", {}), ev);
  acts["sec-landing"](at("sec-landing", { uuid: "u5", quote: "the fixtures" }), ev);
  acts["sec-no-anchor"](at("sec-no-anchor", {}), ev);
  assert.deepEqual(calls, [["open", "s-api"], ["warns", "i1", "wire the fixtures"], ["land", "i1", "u5", "the fixtures"], ["none", "i1"]]);
  assert.equal(stopped, 4, "every act stops the click before the card's own open-modal handler");
  cardTreeExpanded.delete("i1:g2");
  acts["sec-tree"](at("sec-tree", { key: "i1:g2" }), ev);
  assert.ok(cardTreeExpanded.has("i1:g2"), "the tree act flips the branch"); acts["sec-tree"](at("sec-tree", { key: "i1:g2" }), ev); assert.ok(!cardTreeExpanded.has("i1:g2"));
});

test("a follower's own pick survives the owner's map and reaches the owner; the owner's later word for the item retires it", () => {
  const { configureSectionSync, setSectionChoice, receiveSectionSync, secChoice } = mod as any;
  configureSectionSync({ role: "follower" });
  setSectionChoice("i9", "bg");                                      // the row picked before the feed document came up
  receiveSectionSync({ kind: "map", entries: [["i8", "stall"]] });   // the feed hydrates and posts its map, which knows nothing of i9
  assert.deepEqual([secChoice.get("i9"), secChoice.get("i8")], ["bg", "stall"], "the map is taken and the row's own pick stands over it (the verifier's round two: it was discarded)");
  receiveSectionSync({ kind: "set", id: "i9", choice: "summary" });  // the owner speaks for the item
  receiveSectionSync({ kind: "map", entries: [] });
  assert.equal(secChoice.get("i9"), undefined, "after the owner's word, a later map governs the item");
  receiveSectionSync({ kind: "map", entries: [["i7", "bg"]] });
  setSectionChoice("i7", "none"); receiveSectionSync({ kind: "map", entries: [["i7", "none"]] }); receiveSectionSync({ kind: "map", entries: [] });
  assert.equal(secChoice.get("i7"), undefined, "a map carrying the follower's own choice acknowledges it: a later map governs");
});

test("the owner acknowledges a follower's set and the follower retires its pick on that word alone; a stale acknowledgement spares a newer pick; owners ignore acks", () => {
  const { configureSectionSync, setSectionChoice, receiveSectionSync, secChoice } = mod as any;
  configureSectionSync({ role: "follower" });
  setSectionChoice("i5", "bg");                                        // the row picks
  receiveSectionSync({ kind: "ack", id: "i5", choice: "bg" });          // the feed applied it and says so
  receiveSectionSync({ kind: "map", entries: [] });                     // the Collapsed clear (or the prune once the item left)
  assert.equal(secChoice.get("i5"), undefined, "acknowledged, the pick yields to the next map that lacks it (the 0.17.1 fix: it outlived every such map before)");
  setSectionChoice("i6", "bg"); setSectionChoice("i6", "stall");        // a newer pick after an older one
  receiveSectionSync({ kind: "ack", id: "i6", choice: "bg" });          // the ack for the older pick arrives late
  receiveSectionSync({ kind: "map", entries: [] });
  assert.equal(secChoice.get("i6"), "stall", "a stale acknowledgement spares the newer pick, which stands over the map");
  receiveSectionSync({ kind: "ack", id: "i6", choice: "summary" });     // an ack the allowlist admits, for a choice never picked
  receiveSectionSync({ kind: "ack", id: "i6", choice: "sideways" });    // outside the allowlist: ignored
  receiveSectionSync({ kind: "map", entries: [] });
  assert.equal(secChoice.get("i6"), "stall", "neither retires the pick");
  configureSectionSync({ role: "owner" });
  secChoice.clear(); receiveSectionSync({ kind: "set", id: "i5", choice: "bg", from: "owner" });   // another owner's set: applied, never acknowledged (nothing to observe here but the map)
  assert.equal(secChoice.get("i5"), "bg");
  receiveSectionSync({ kind: "ack", id: "i5", choice: "bg" });          // an owner ignores acks: its map stands
  assert.equal(secChoice.get("i5"), "bg");
  configureSectionSync({ role: "follower" }); secChoice.clear();
});

test("the Collapsed flag flipped with no pick held: an unchanged map still re-applies every host unless quiet, since the default they resolve against moved; nothing is persisted", () => {
  // the manager's read of the 0.17.1 fix: the feed's clear on the flip found its map unchanged and returned before the re-apply, so a card whose
  // payload stood alone kept the old default until its next repaint (the chat page's rows follow from the page's own settings listener either way)
  const { configureSectionSync, replaceSectionChoices, registerSectionHost, applySections, secChoice } = mod as any;
  let writes = 0, applied = 0, collapsed = false;
  configureSectionSync({ role: "owner", onChange: () => { writes++; } });
  replaceSectionChoices([], { quiet: true });                        // the map is empty to begin with
  const se = buildSectionElements() as unknown as Record<string, any>;
  const host = Object.assign(new E("DIV"), { isConnected: true, _bgBtn: se.bgBtn, _takeBtn: se.takeBtn, _stallBtn: se.stallBtn, _subBtn: se.subBtn, _taskBtn: se.taskBtn, _taskLbl: se.taskLbl,
                                             _bgBody: se.bgBody, _distill: se.distill, _stallBody: se.stallBody, _secs: se.secs, _checklist: se.checklist, _awaitSpin: se.awaitSpin, _awaitWhy: se.awaitWhy });
  const hostEnv = { ...env, collapsed: () => collapsed, wireNode: () => {}, repoOf: () => null, nowSec: () => 0, relAge: () => "", ageTint: () => "", landing: () => {}, noAnchor: () => {}, afterApply: () => { applied++; } };
  applySections(host, { itemId: "i5", sid: "s", text: "t", background: "why" }, true, hostEnv);
  registerSectionHost("i5", host);
  assert.equal(se.takeBtn.getAttribute("aria-pressed"), "true", "premise: no pick held, the default opens Summary");
  collapsed = true;                                                  // the flag flips, the map stays empty
  replaceSectionChoices([], { quiet: true });                        // the prune's road: unchanged and quiet, nothing happens
  assert.equal(applied, 0, "a quiet unchanged map re-applies nothing (the prune runs on every render)");
  replaceSectionChoices([]);                                         // the flip's road: unchanged, not quiet
  assert.equal(applied, 1, "every host re-applied (before: the unchanged map returned first, and the card kept the old default until its next repaint)");
  assert.equal(se.takeBtn.getAttribute("aria-pressed"), "false", "and resolved against the new default: nothing open under Collapsed");
  assert.deepEqual([writes, secChoice.size], [0, 0], "nothing persisted, the map unchanged");
});

test("applyRelayNote: the relayed question's line is created once beside the sections, after the face when the host has one, and shows only with a note", () => {
  const { applyRelayNote } = mod as any;
  const row = new E("DIV"); const attach = new E("DIV"); const secs = new E("DIV"); const spin = new E("DIV"); row.append(attach, secs, spin);
  const host: any = Object.assign(new E("DIV"), { _secs: secs });               // the row: no face, so the note lands after the sections container
  applyRelayNote(host, { relayNote: "a question to api is still parked on the far host" });
  assert.deepEqual(row.childNodes.map((c) => (c as E) === host._relayNote ? "note" : (c as E) === secs ? "secs" : (c as E) === spin ? "spin" : "attach"), ["attach", "secs", "note", "spin"], "after the sections, before the swirl box");
  assert.deepEqual([host._relayNote.className, host._relayNote.textContent, host._relayNote.style.display], ["fask-distill fask-relaynote", "a question to api is still parked on the far host", ""]);
  applyRelayNote(host, { relayNote: null });
  assert.deepEqual([row.childNodes.length, host._relayNote.style.display], [4, "none"], "the same element, hidden without a note; never a second one");
  const card = new E("DIV"); const face = new E("DIV"); const csecs = new E("DIV"); card.append(csecs, face);
  const chost: any = Object.assign(new E("DIV"), { _face: face, _secs: csecs });   // the card: the face is the anchor
  applyRelayNote(chost, { relayNote: "  the note  " });
  assert.deepEqual([card.childNodes.indexOf(chost._relayNote), chost._relayNote.textContent], [2, "the note"], "after the face, trimmed");
});

test("the warning chip on a page with no destination is a span that promises no click; with one it is a button whose hover says so", () => {
  const withOut = stateBadges({ warns: [{ kind: "brief-failed", t: 1, msg: "the brief could not be written", detail: "" }] }, { ...env, openWarns: undefined } as any) as unknown as E[];
  assert.deepEqual([withOut[0].tagName, withOut[0].title, withOut[0].dataset.act], ["SPAN", "the brief could not be written", undefined], "no button role, no click sentence, no act (the chat page)");
  const withIt = badges({ warns: [{ kind: "brief-failed", t: 1, msg: "the brief could not be written", detail: "" }] });
  assert.deepEqual([withIt[0].tagName, withIt[0].dataset.act], ["BUTTON", "sec-open-warns"], "the feed's chip keeps its destination");
  assert.match(withIt[0].title, /click for what happened and why$/);
});

