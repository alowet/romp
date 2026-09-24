// The chat page's NEEDS YOU BOX (#notices; plans/needs-you.md, phase three; the approval box of plans/notice-cards.md, "Action
// kinds and the held-mail card", 2026-09-19, before it): the active session's Needs you items that are not hard stops, listed
// above the background box under a "Needs you · N" header, rendered from status.notices on every status change. A goal row
// (kind "goal") offers Reply (the composer takes the card) and Clear, on the card's own wires (the Continue button left the
// row on 2026-09-23; the stored offer and its wire stay); a notice row posts the same noticeAction wire the feed card posts
// (the action's KIND with the stored body, a deny's optional note as the click's input), re-armed or removed on
// noticeActionDone, or Clear when it has no stored action. The gear's Needs you box switch hides the box; the tab's cue and
// the feed still say it. Source pins (the chat renderer has no jsdom harness); the behaviour rides
// tests/test_held_mail_chat_served.py and tests/test_needs_you_box_chat_served.py.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { createRequire } from "node:module";

const UI = path.resolve(process.cwd(), "..", "ui", "webview");
const RENDER = fs.readFileSync(path.join(UI, "render.ts"), "utf8");
const CSS = fs.readFileSync(path.join(UI, "styles.css"), "utf8");
const FEED = fs.readFileSync(path.join(UI, "feed.ts"), "utf8");
const NOTICE_FACE = fs.readFileSync(path.join(UI, "notice-face.ts"), "utf8");
const fn = (name: string) => { const i = RENDER.indexOf("function " + name + "("); assert.ok(i >= 0, name); return RENDER.slice(i, RENDER.indexOf("\n}\n", i) + 3); };

test("the status carries the rows and the box renders on every status change beside the background box", () => {
  assert.match(RENDER, /interface Status \{ state: ChipState; sinceEpoch: number \| null; modelFallback\?: ModelFallback \| null; notices\?: ChatNotice\[\] \| null;/, "the slice on the status, after main's model-fallback field");
  assert.match(RENDER, /interface ChatNotice \{ itemId: string; key: string; rev: number; title: string; body: string; producer: string; attachment\?: NoticeAttachment \| null;\s*\n\s*actions: \{ label: string; kind\?: string; route\?: string; body: Record<string, unknown> \}\[\];\s*\n\s*kind\?: "goal" \| "notice";[^\n]*\n\s*cont\?: boolean;[^\n]*\n\s*fix\?: "credential";[^\n]*\n(?:\s*\/\/[^\n]*\n)+\s*summary\?: string \| null; blockSummary\?: string \| null;[^]*?handoffTo\?: BadgeItem\["handoffTo"\];[^]*?sessState\?: string \| null \}/, "the row carries the feed card's attachment too (low e), and since phase three its kind, its Continue offer and its fix");
  // awaitKey is the status key every status-carrying frame compares (the T225 pins): the rows are part of it, so a hold or a
  // decision repaints the box through the same awaitChanged road as the background box
  // by id AND face (the second review of PR 1967): a brief landing, a Continue offered, a retitle or the credential fix repaints the box
  assert.match(fn("awaitKey"), /\(st\.notices \|\| \[\]\)\.map\(\(n\) => JSON\.stringify\(n\)\)\]\);/, "the row's WHOLE face (the box content round: a section field or a badge moving repaints the box, as the kernel's signature keys the same fields)");
  assert.match(fn("awaitChanged"), /if \(sid === activeId\) renderBgTasks\(\);\s*\n\s*if \(sid === activeId\) renderNotices\(\);/);
  assert.match(RENDER, /renderBgTasks\(\); \/\/ swap in the active session's background-task box \(or hide if none\)\s*\n\s*renderNotices\(\); \/\/ swap in the active session's approval box/, "the tab switch");
  assert.match(RENDER, /    renderBgTasks\(\);\s*\n\s*renderNotices\(\);\s*\n\s*\} else if \(!activeId\) \{/, "the session frame");
});

test("the box: rows keyed by the notice id and reconciled in place, the shared notice face, the kernel's actions as buttons naming their act and index", () => {
  const r = fn("renderNotices");
  assert.match(r, /const host = document\.getElementById\("notices"\);/);
  assert.match(r, /const rows: ChatNotice\[\] = \(s && s\.status && s\.status\.notices\) \|\| \[\];/);
  assert.match(r, /if \(!s \|\| !activeId \|\| !rows\.length \|\| !settings\.needsBox\) \{ for \(const r of Array\.from\(host\.querySelectorAll<HTMLElement>\("\.ntc-row"\)\)\) unregisterSectionHost\(r\.dataset\.item \|\| "", r\); host\.replaceChildren\(\); host\.style\.display = "none"; return; \}/, "hidden with no row, and under the gear's switch (phase three); every row leaves the registry first (the verifier of PR 2141)");
  assert.doesNotMatch(r.replace(/if \(!s \|\| !activeId \|\| !rows\.length \|\| !settings\.needsBox\) \{ for \(const r of Array\.from\(host\.querySelectorAll<HTMLElement>\("\.ntc-row"\)\)\) unregisterSectionHost\(r\.dataset\.item \|\| "", r\); host\.replaceChildren\(\);[^\n]*/, ""), /host\.replaceChildren\(\)/, "with rows, the box is never rebuilt whole: a press must survive a frame (the review of PR 1890, medium 1)");
  assert.match(r, /let bar = host\.querySelector<HTMLElement>\("\.ntc-bar"\);\s*\n\s*if \(!bar\) \{ bar = buildNoticeBar\(\); host\.prepend\(bar\); \}/, "the bar (the header and the gear) is built once and kept");
  assert.match(r, /lab\.textContent = "Needs you · " \+ rows\.length;/, "the title with the count");
  assert.match(r, /let prev: HTMLElement = bar;/, "the rows follow the bar in the frame's order");
  assert.match(r, /for \(const r of Array\.from\(host\.querySelectorAll<HTMLElement>\("\.ntc-row"\)\)\) if \(!want\.has\(r\.dataset\.item \|\| ""\)\) \{ unregisterSectionHost\(r\.dataset\.item \|\| "", r\); r\.remove\(\); \}/, "a row that left leaves, and leaves the item's twin set as it goes (the registry is exact)");
  assert.match(r, /if \(!s \|\| !activeId \|\| !rows\.length \|\| !settings\.needsBox\) \{ for \(const r of Array\.from\(host\.querySelectorAll<HTMLElement>\("\.ntc-row"\)\)\) unregisterSectionHost\(r\.dataset\.item \|\| "", r\); host\.replaceChildren\(\); host\.style\.display = "none"; return; \}/,
    "the box emptied whole (no rows, the switch off, a snapshot) unregisters every row BEFORE replaceChildren detaches it: the drop loop never runs on that road (the verifier of PR 2141)");
  assert.match(r, /if \(!row\) \{ row = buildNoticeRow\(n, s\.id\);/); assert.match(r, /updateNoticeRow\(row, n, s\.id\);/, "an existing row is updated in place");
  const u = fn("updateNoticeRow");
  assert.match(u, /if \(body && row\._body !== \(n\.body \|\| ""\)\) \{ body\.replaceChildren\(\.\.\.noticeBodyNodes\(n\.body \|\| ""\)\);/, "the body through the shared face (low e)");
  assert.match(u, /att\.replaceChildren\(\.\.\.noticeAttachmentNodes\(n\.attachment, sid\)\);/, "the attachment through the shared face");
  assert.match(u, /const sig = noticeActionsSig\(n\);\s*\n\s*if \(row\._sig !== sig\) \{/, "the buttons and the refusal line are rebuilt only when the row's own actions change");
  const b = fn("buildNoticeRow");
  assert.match(b, /row\.className = "ntc-row"; row\.dataset\.item = n\.itemId;/, "the row is keyed by the notice id: the kernel's answer finds it");
  const plain = fn("noticeRowPlain");
  assert.match(plain, /const deny = act\.kind === "quarantine" && !!act\.body && \(act\.body as any\)\.verdict === "deny";/);
  assert.match(plain, /noticeButton\(act\.label, deny \? "ntc-deny" : "ntc-ok", deny \? "ntc-deny-step" : "ntc-go", i\)/, "an approve goes at once; a deny opens the note first");
  const step = fn("noticeRowDenyStep");
  assert.match(step, /noticeButton\("Deny & send note", "ntc-deny", "ntc-deny-note", idx\), noticeButton\("Deny without note", "ntc-deny", "ntc-deny-bare", idx\), noticeButton\("Back", "ntc-back", "ntc-back", idx\)/);
  assert.doesNotMatch(r + u + b + plain + step, /Edit/, "nobody edits held mail");
  assert.match(RENDER, /import \{ noticeBodyNodes, noticeAttachmentNodes, type NoticeAttachment \} from "\.\/notice-face";/);
  assert.match(FEED, /import \{ noticeBodyNodes, noticeAttachmentNodes \} from "\.\/notice-face";/, "the feed card reads the same module");
  assert.doesNotMatch(FEED, /function noticeBodyNodes/, "one definition, in notice-face.ts");
  assert.match(NOTICE_FACE, /export function noticeBodyNodes\(md: string\): Node\[\]/); assert.match(NOTICE_FACE, /export function noticeAttachmentNodes\(att: NoticeAttachment \| null \| undefined, sid: string\): HTMLElement\[\]/);
});

test("the clicks ride one delegate on the stable container; every button of the row latches on a decision; the kind and the note ride the wire", () => {
  const i = RENDER.indexOf('const host = document.getElementById("notices");\n  if (!host) return;\n  const rowOf');
  assert.ok(i >= 0, "the delegate installs on #notices once");
  const d = RENDER.slice(i, RENDER.indexOf("})();", i));
  assert.match(d, /delegate\(host, \{/);
  for (const act of ["ntc-go", "ntc-deny-step", "ntc-deny-note", "ntc-deny-bare", "ntc-back"]) assert.ok(d.includes('"' + act + '":'), act);
  assert.match(d, /return \(\(s && s\.status && s\.status\.notices\) \|\| \[\]\)\.find\(\(n\) => n\.itemId === row\.dataset\.item\) \|\| null;/, "the notice is read from the active frame at click time, never a stale closure");
  assert.match(d, /const kind = act\.kind \|\| \(act\.route === "\/send" \? "send" : ""\);/);
  assert.match(d, /vscodeApi\?\.postMessage\(\{ type: "noticeAction", itemId: n\.itemId, sid: activeId, kind, body: act\.body, \.\.\.\(input \? \{ input \} : \{\}\) \}\);/, "the same wire as the feed card");
  assert.match(d, /for \(const b of Array\.from\(row\.querySelectorAll\("button"\)\) as HTMLButtonElement\[\]\) b\.disabled = true;/, "every button of the row latches");
  assert.match(d, /go\(p\[0\], p\[1\], p\[2\], el as HTMLButtonElement, t \? \{ note: t \} : undefined\)/, "the note rides as input, trimmed, or not at all");
});

test("the kernel's answer re-arms the row on a refusal, saying why in the row, and drops it on a success; the box is a box below; the slice's ids wear the host", () => {
  const i = RENDER.indexOf('else if (m.type === "noticeActionDone" && typeof m.itemId === "string" && m.itemId) {');
  assert.ok(i >= 0, "the handler sits in the inbound dispatch");
  const h = RENDER.slice(i, RENDER.indexOf('else if (m.type === "err"', i));
  assert.match(h, /document\.querySelector<HTMLElement>\(noticeRowSelector\(m\.itemId\)\)/, "the row by the answer's id (a remote host's is prefixed on the way in, like the row's)");
  // `held` (the second executed review of PR 1935, carried here): a delivery whose dismissal's write refused keeps the row with its
  // buttons spent and says so; a plain success drops the row; a refusal re-arms the buttons and says why
  assert.match(h, /if \(m\.ok && !m\.held\) \{ unregisterSectionHost\(m\.itemId, row\); row\.remove\(\);/, "a row a completed action removes leaves the item's twin set too");
  assert.match(h, /if \(!m\.ok\) for \(const b of Array\.from\(row\.querySelectorAll\("button"\)\) as HTMLButtonElement\[\]\) \{ b\.disabled = false; b\.textContent = \(b as any\)\._idle \|\| b\.textContent; \}/);
  assert.match(h, /e\.textContent = \(m\.ok \? "That action ran, but " : "That action was refused: "\) \+ String\(m\.error \|\| "the kernel did not say why"\); e\.style\.display = "";/, "one shape for both refusal rows: a sentence, as the err path's title is (the round-three verifier)");
  const FEEDSRC = fs.readFileSync(path.join(UI, "feed.ts"), "utf8");
  assert.match(FEEDSRC, /const held = !!m\.ok && !!m\.held;/, "the feed card keeps a held card too");
  assert.match(FEEDSRC, /if \(m\.ok && dismisses && !held\) \{/); assert.match(FEEDSRC, /\} else if \(!held\) \{/, "a held card's buttons stay spent");
  assert.match(FEEDSRC, /else if \(held\) feedToast\("The card's action ran, but " \+ String\(m\.error \|\| "the card could not be dismissed"\) \+ "\."\);/);
  assert.match(RENDER, /const BOXES_BELOW = \["notices", "bg-tasks", "footer"\];/); assert.match(RENDER, /for \(const boxId of BOXES_BELOW\) \{/, "the bottom-box rule covers the approval box (low a); the list is shared with the footprint record (the review of PR 1926)");
  const FED = fs.readFileSync(path.join(UI, "federation.ts"), "utf8");
  assert.match(FED, /out\.status = \{ \.\.\.out\.status, notices: out\.status\.notices\.map\(\(n: any\) => \(n && typeof n === "object" && typeof n\.itemId === "string"\) \? _prefixOriginAndPeers\(host, \{ \.\.\.n, itemId: prefixNoticeId\(host, n\.itemId\) \}\) : n\) \};/, "the slice's ids wear the host (medium 2), and each row's sender and peers take the same rewrite a card gets (a contributor's post-merge note on PR 2124)");
});

test("a refused act re-arms the row the kernel's reply names, with the reason in the row (the second review of PR 1967)", () => {
  const i = RENDER.indexOf('else if (m.type === "err" && typeof m.text === "string" && m.text) {');
  assert.ok(i >= 0);
  const h = RENDER.slice(i, RENDER.indexOf('else if (m.type === "dirCompletions")', i));
  assert.match(h, /const refusedIds = \[typeof m\.itemId === "string" \? m\.itemId : "", \.\.\.\(Array\.isArray\(m\.itemIds\) \? m\.itemIds\.map\(String\) : \[\]\)\]\.filter\(Boolean\);/,
    "the card the reply names, and the batch a clears-log refusal names");
  assert.match(h, /const row = document\.querySelector<HTMLElement>\(noticeRowSelector\(id\)\); if \(!row\) continue;/);
  assert.match(h, /b\.disabled = false; b\.textContent = \(b as any\)\._idle \|\| b\.textContent;/, "the latched buttons let go with their idle labels");
  assert.match(h, /e\.textContent = title; e\.style\.display = "";/, "and the row says why: the frame's title, a sentence, alone (no doubled refusal)");
  // the kernel's clears-log refusal names the request: op, the first id and the batch
  const KERNEL = fs.readFileSync(path.join(UI, "..", "..", "kernel", "kernel.py"), "utf8");
  assert.match(KERNEL, /def _gesture_store_refusal\(client, gesture, skipped, ids=None, op="", seq=None\):/);
  assert.match(KERNEL, /"itemId": acct_ids\[0\] if acct_ids else "", "itemIds": list\(acct_ids\)\}/, "every account's frame names the request and the account's own ids (the third review: not the whole batch)");
  assert.match(RENDER, /if \(m\.ok !== true\) notifyShell\("undelivered", copy \? title \+ ": " \+ copy : title, typeof m\.sid === "string" \? m\.sid : ""\);/, "the chat page's err handler files no bell entry for an information frame, as the feed's does not (the round-six verifier)");
  assert.match(KERNEL, /_send\(title, text, "", _ids\)\s+continue\s+notices = key\.startswith\("notice:"\)/, "the ledger's refusal names the whole batch");
  // the op is the request's own type (a pin elsewhere splits the dispatcher's source on the quoted op name, so no arm repeats its literal)
  for (const arm of ['_gesture_store_refusal(client, "clear", _skipped, ids=[str(msg["itemId"])], op=str(msg.get("type") or ""))',
                     '_gesture_store_refusal(client, "clear", _skipped, ids=_ids, op=str(msg.get("type") or ""))',
                     '_gesture_store_refusal(client, "drop", _skipped, ids=[str(msg["nodeId"])], op=str(msg.get("type") or ""))']) assert.ok(KERNEL.includes(arm), arm);
  assert.equal((KERNEL.match(/if LEDGER_KEY not in _skipped/g) || []).length, 3, "askClear, nodeOverride and clearAll keep the citations on a refusal...");
  assert.ok(KERNEL.includes("if _ids and LEDGER_KEY not in _skipped:"), "...and so does the batch clear");
});

test("the box is collapsed by default and opens in steps (the user 2026-09-23): three levels the page holds per session in the one fold store, the header's click advancing them, the sheet hiding the rows below level 1 and the background below level 2", () => {
  // the level lives in openFolds, the ONE fold store (ui/CLAUDE.md), as two boolean keys per session set together by the click (the second
  // contributor's post-merge review of PR 2093: a Map of its own stood outside the census of merged keys, notice-vocab.test.ts)
  assert.match(RENDER, /function noticeBoxKeys\(sid: string\): \[string, string\] \{ return \["ntcbox:" \+ sid \+ ":items", "ntcbox:" \+ sid \+ ":context"\]; \}/, "one key per level above 0");
  assert.doesNotMatch(RENDER, /noticeBoxLevel\b/, "the Map of its own is gone");
  assert.match(fn("noticeBoxLevelOf"), /const \[k1, k2\] = noticeBoxKeys\(sid\); return openFolds\.has\(k2\) \? 2 : openFolds\.has\(k1\) \? 1 : 0;/, "collapsed by default: neither key");
  assert.match(fn("setNoticeBoxLevel"), /for \(const \[k, on\] of \[\[k1, level >= 1\], \[k2, level >= 2\]\] as \[string, boolean\]\[\]\) \{ if \(on\) openFolds\.add\(k\); else openFolds\.delete\(k\); \}/, "both keys set together");
  assert.match(fn("applyNoticeBoxLevel"), /const level = noticeBoxShownLevel\(sid, rows\);\s*\n\s*host\.classList\.toggle\("ntc-l0", level === 0\); host\.classList\.toggle\("ntc-l1", level === 1\); host\.classList\.toggle\("ntc-l2", level === 2\);/, "one class per level on the box, the shown level (a credential row floors it)");
  assert.match(fn("renderNotices"), /applyNoticeBoxLevel\(host, s\.id, rows\);/, "applied on every render, before the rows");
  assert.doesNotMatch(fn("renderNotices"), /setNoticeBoxLevel|openFolds\.(add|delete)\(/, "the renderer never writes the level");
  const i = RENDER.indexOf('const host = document.getElementById("notices");\n  if (!host) return;\n  const rowOf');
  const d = RENDER.slice(i, RENDER.indexOf("})();", i));
  assert.match(d, /"ntc-fold": \(\) => \{ if \(!activeId\) return; const s = liveSession\(activeId\); setNoticeBoxLevel\(activeId, noticeBoxNextLevel\(activeId, \(s && s\.status && s\.status\.notices\) \|\| \[\]\)\); renderNotices\(\); \},/, "the header's click stores the next level: the items, then the full context, then folded back, never below the floor");
  assert.match(fn("noticeBoxNextLevel"), /return Math\.max\(\(noticeBoxShownLevel\(sid, rows\) \+ 1\) % 3, noticeBoxFloor\(rows\)\);/, "one helper for the click and the title (the box arc's round three: two clicks at the floor stored 0 and the box dropped to its header line when the row left)");
  assert.match(CSS, /#notices\.ntc-l0 \.ntc-row \{ display: none; \}/, "level 0: the rows hidden");
  assert.match(CSS, /#notices:not\(\.ntc-l2\) \.ntc-body, #notices:not\(\.ntc-l2\) \.ntc-attach \{ display: none; \}/, "below level 2: the markdown body and the attachment hidden");
  assert.match(CSS, /#notices\.ntc-l0 \.ntc-more \{ display: none; \}/, "the disclosure hides with the rows at level 0 only: at the items level it opens the clamped distill line (the box content round)");
  assert.match(CSS, /#notices:not\(\.ntc-l2\) \.ntc-row \.ntc-secs-row \{ display: none; \}/, "the section toggles at the full context only");
  assert.match(CSS, /\.ntc-row \.ntc-distill \{[^}]*display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; \}/, "the distill line clamped to four lines in the box, at the items and at the full context");
  assert.match(CSS, /\.ntc-row\.ntc-open \.ntc-distill \{ display: block; -webkit-line-clamp: unset; overflow: visible; \}/, "and the disclosure lifts the clamp");
  assert.match(CSS, /\.ntc-head \.ntc-caret \{[^}]*font-size: 0\.72em; width: 10px;/, "the awaiting box's caret");
});

test("phase three: a goal row's Reply and Clear on the card's own wires (Continue stored, its button gone since 2026-09-23); a no-action notice's Clear; the kind and the offer ride the row's face and its type", () => {
  assert.match(RENDER, /kind\?: "goal" \| "notice";/, "the row says its kind"); assert.match(RENDER, /cont\?: boolean;/, "and whether Continue is offered");
  const sigLine = (RENDER.match(/function noticeActionsSig\(n: ChatNotice\): string \{ return [^\n]*/) || [""])[0];
  assert.match(sigLine, /JSON\.stringify\(\[n\.kind \|\| "notice", n\.fix \|\| "", \(n\.actions \|\| \[\]\)\.map/, "the face signature carries the kind, the fix and the actions");
  assert.doesNotMatch(sigLine, /n\.cont/, "and NOT the Continue offer while no button reads it (the second contributor's post-merge review of PR 2093: a backend going up or down flipped it and rebuilt the row, wiping a refusal line and re-enabling a latched Clear)");
  assert.match(fn("awaitKey"), /JSON\.stringify\(n\)/, "the frame's key still carries the offer (the whole row since the box content round): the row repaints when it returns with the button");
  const plain = fn("noticeRowPlain");
  assert.match(plain, /if \(n\.kind === "goal"\) \{[^]*?acts\.appendChild\(noticeButton\("Reply", "ntc-ok", "ntc-reply", 0\)\);[^\n]*\n\s*acts\.appendChild\(noticeButton\("Clear", "ntc-clear", "ntc-clear", 1\)\);[^\n]*\n\s*return;/, "a goal row: Reply, then Clear at the next index; no Continue button (the user 2026-09-23: Reply and Clear only for now, the stored offer and its wire kept)");
  assert.doesNotMatch(plain, /noticeButton\("Continue"/, "the Continue button is gone from every row");
  assert.match(plain, /if \(!\(n\.actions \|\| \[\]\)\.length\) \{ acts\.appendChild\(noticeButton\("Clear", "ntc-clear", "ntc-clear", 0\)\); return; \}/, "a notice with no stored action offers Clear");
  const i = RENDER.indexOf('const host = document.getElementById("notices");\n  if (!host) return;\n  const rowOf');
  const d = RENDER.slice(i, RENDER.indexOf("})();", i));
  assert.match(d, /"ntc-reply": \(el\) => \{ const p = item\(el\); if \(p && activeId\) setCitation\(activeId, \{ itemId: p\[1\]\.itemId, title: p\[1\]\.title \}\); \},/, "Reply points the composer at the card, as a feed card click that lands in the chat does; the row stays until the reply is judged");
  assert.match(d, /"ntc-cont": \(el\) => \{[^\n]*vscodeApi\?\.postMessage\(\{ type: "askFollowUp", itemId: p\[1\]\.itemId, sid: activeId, cont: true \}\); latch\(p\[0\], el as HTMLButtonElement\); \},/, "Continue is the card's Continue wire, and the row latches");
  assert.match(d, /"ntc-clear": \(el\) => \{[^\n]*vscodeApi\?\.postMessage\(\{ type: "askClear", itemId: p\[1\]\.itemId, sid: activeId \}\); latch\(p\[0\], el as HTMLButtonElement\); \},/, "Clear is the card's Clear wire, and the row latches");
  assert.match(RENDER, /fix\?: "credential";/, "the row says when its one action is the credential fix");
  assert.match(plain, /if \(n\.kind === "goal" && n\.fix === "credential"\) \{[^]*?noticeButton\("Fix credential…", "ntc-ok", "ntc-fix", 0\)\);\s*\n\s*return;/, "the credential row: the fix alone, no Reply, no Continue, no Clear (a Clear would hide the fault while the refusals go on)");
  assert.match(d, /"ntc-fix": \(\) => openSettingsOn\("general"\),/, "the fix opens the settings' General tab, where the Billing block sits");
  assert.match(fn("buildNoticeBar"), /bar\.className = "ntc-bar";[^]*?head\.className = "ntc-head";[^]*?head\.dataset\.act = "ntc-fold";[^]*?el\("span", "ntc-caret"\)[^]*?el\("span", "ntc-dot"\)[^]*?el\("span", "ntc-label"\)[^]*?bar\.appendChild\(head\);/, "the bar, then the header inside it: the fold control, the caret, the dot and the label");
  assert.match(RENDER, /onExternalSettingsChange\(\(\) => renderNotices\(\)\);/, "a settings save repaints the box: the gear's switch takes effect at once");
  const SETTINGS = fs.readFileSync(path.join(UI, "settings.ts"), "utf8");
  assert.match(SETTINGS, /needsBox: boolean;/); assert.match(SETTINGS, /needsBox: true,/, "on by default");
  const GEAR = fs.readFileSync(path.join(UI, "gear.js"), "utf8");
  assert.match(GEAR, /<input type=checkbox id=rs-needsbox checked>/, "the row under Chat, on by default");
  assert.match(GEAR, /<div class='rs-sec' data-section=boxes>Boxes below the transcript<\/div>" \+\s*\n\s*'<label class=rs-row><input type=checkbox id=rs-needsbox checked>/, "the switch heads a section of its own, named for where the box sits (the user 2026-09-23, who did not find it under Display)");
  assert.match(GEAR, /<b>Needs you box<\/b>/); assert.match(GEAR, /s\.needsBox = nb\.checked; save\(s\);/, "the save the chat page hears"); assert.match(GEAR, /if \(nb\) nb\.checked = s\.needsBox !== false;/, "a store from before the key reads as on");
  assert.match(CSS, /\.ntc-bar \{[^}]*border-bottom: 1px solid var\(--box-border\);/, "the header bar in the background box's grammar");
  assert.match(CSS, /\.ntc-head \.ntc-dot \{[^}]*background: var\(--st-needs-bg\); \}/, "the dot in the token");
  assert.doesNotMatch(CSS.slice(CSS.indexOf("#notices {"), CSS.indexOf("\n", CSS.indexOf("#notices {") + 200)), /--st-working-bg|border-left: 3px/, "the working gold's thick edge is gone: one thin line in the token, the awaiting box's dress");
});

test("the keyboard reaches both box headers (the second contributor's post-merge review of PR 2093): a button role and a tab stop, Enter or Space pressing the header, the expanded state with the level, the caret decoration, the next step as the title", () => {
  const h = fn("buildNoticeBar");
  assert.match(h, /head\.setAttribute\("role", "button"\); head\.tabIndex = 0;/, "the Needs you header is a button the keyboard can reach");
  assert.match(h, /head\.addEventListener\("keydown", \(e\) => \{ if \(e\.key === "Enter" \|\| e\.key === " "\) \{ e\.preventDefault\(\); head\.click\(\); \} \}\);/, "Enter or Space press the header through its click (the delegate's path), focus kept; no target guard, since the header has no focusable descendant (the gear is its sibling in the bar)");
  assert.match(h, /const caret = el\("span", "ntc-caret"\); caret\.setAttribute\("aria-hidden", "true"\); head\.appendChild\(caret\);/, "the caret is decoration");
  assert.doesNotMatch(h, /head\.setAttribute\("aria-label"/, "no aria-label: it would drop 'Needs you · N' from the name");
  assert.match(h, /const label = el\("span", "ntc-label"\); label\.id = "ntc-label"; head\.appendChild\(label\);\s*\n\s*head\.setAttribute\("aria-labelledby", "ntc-label"\);/, "the name is the label alone: the gear nested in the button is not folded into it (the round-one verifier of PR 2105)");
  const a = fn("applyNoticeBoxLevel");
  assert.match(a, /head\.setAttribute\("aria-expanded", level > 0 \? "true" : "false"\); head\.title = noticeBoxStepTitle\(sid, rows\);/, "the expanded state and the next step as the title move with the level, the title by the transition the next click makes");
  const st = fn("noticeBoxStepTitle");
  assert.match(st, /if \(next > shown\) return next === 1 \? "Show the items" : "Show the full context";\s*\n\s*return next === 0 \? "Collapse" : "Hide the full context";/, "ascending names what shows next; descending says 'Collapse' only where the next level is the header line, else 'Hide the full context' (the round-one verifier of PR 2120: at the floor from the full context 'Show the items' read while the items already showed)");
  assert.doesNotMatch(a, /caret\.title/, "the title is the header's, not the hidden caret's");
  const bg = RENDER.split("function renderBgTasks(")[1].split("\nfunction ")[0];
  assert.match(bg, /head\.setAttribute\("role", "button"\); head\.tabIndex = 0; head\.setAttribute\("aria-expanded", open \? "true" : "false"\);/, "the background box's header, the same gap at the base, has the same route");
  assert.match(bg, /head\.addEventListener\("keydown", \(e\) => \{ if \(e\.target !== head\) return; if \(e\.key === "Enter" \|\| e\.key === " "\) \{ e\.preventDefault\(\); head\.click\(\); \} \}\);/);
  assert.match(bg, /car\.setAttribute\("aria-hidden", "true"\)/);
  // the box arc's round three: the background header kept the keyboard through neither its own click nor a push (the render empties the box)
  assert.match(bg, /const refocusHead = !!document\.activeElement && document\.activeElement\.classList\.contains\("bg-fold-head"\) && host\.contains\(document\.activeElement\)\s*\n\s*&& document\.activeElement\.matches\(":focus-visible"\);\s*\n\s*host\.replaceChildren\(\);/, "a KEYBOARD focus on the header is remembered before the box is emptied (a mouse click's is not: the next Enter still reaches the composer)");
  assert.match(bg, /host\.appendChild\(head\);\s*\n\s*if \(refocusHead\) head\.focus\(\);\s*\n\s*if \(!open\) return;/, "and the new header takes it back once it stands, before the early return");
  assert.match(CSS, /\.ntc-head:focus-visible, \.bg-fold-head:focus-visible \{ outline: 1px solid var\(--accent\); outline-offset: -2px; \}/, "both headers show the keyboard's focus in the accent, inside the boxes' clipping overflow");
});

test("a judges' credential row floors the box at the items while it shows (the second contributor's post-merge review of PR 2093): a fault must not hide under a header that reads like a question's", () => {
  assert.match(fn("noticeBoxFloor"), /return rows\.some\(\(n\) => n\.kind === "goal" && n\.fix === "credential"\) \? 1 : 0;/);
  assert.match(fn("noticeBoxShownLevel"), /return Math\.max\(noticeBoxLevelOf\(sid\), noticeBoxFloor\(rows\)\);/, "the shown level is the stored one or the floor, whichever is higher; the stored level never goes below the floor while the row shows (the click stores noticeBoxNextLevel), so the box keeps the items when the row leaves");
  assert.match(fn("noticeRowPlain"), /row\.classList\.toggle\("ntc-fault", n\.kind === "goal" && n\.fix === "credential"\);/, "the credential row wears the fault class");
  assert.match(CSS, /#notices:not\(\.ntc-l2\) \.ntc-row\.ntc-fault \.ntc-body \{ display: -webkit-box; \}/, "and its body, the refusal's explanation, shows at the items where every other body waits for the full context (the box arc's round three)");
});

test("the box's own gear (the second contributor's post-merge review of PR 2093: the strip's gear lands on Tab strip with the box's section out of view): the shell's glyph at the bar's right end, beside the header, opening the settings' Chat tab at the Boxes section, drawn only where a settings card can open", () => {
  const h = fn("buildNoticeBar");
  assert.match(h, /if \(\(window as any\)\.__rompShowStrip \|\| inRompShell\(\)\) \{\s*\n\s*const gear = el\("button", "ntc-gear"\) as HTMLButtonElement; gear\.type = "button"; gear\.dataset\.act = "ntc-gear";/, "the same reachability gate as the strip's gear");
  assert.match(h, /bar\.appendChild\(gear\);/, "the gear is the bar's child, beside the header, never inside the role=button header (axe nested-interactive; the box arc's round three)");
  assert.doesNotMatch(h, /head\.appendChild\(gear\)/);
  assert.match(h, /gear\.title = "Needs you box settings"; gear\.setAttribute\("aria-label", "Needs you box settings"\); gear\.textContent = GEAR_GLYPH;/);
  const i = RENDER.indexOf('const host = document.getElementById("notices");\n  if (!host) return;\n  const rowOf');
  const d = RENDER.slice(i, RENDER.indexOf("})();", i));
  assert.match(d, /"ntc-gear": \(\) => openSettingsOn\("chat", "boxes"\),/, "straight to the section that holds the switch");
  const GEAR = fs.readFileSync(path.join(UI, "gear.js"), "utf8");
  assert.match(GEAR, /<div class='rs-sec' data-section=boxes>Boxes below the transcript<\/div>/, "the anchor showSection scrolls to");
  assert.match(CSS, /\.ntc-bar \.ntc-gear \{[^}]*font-size: 15px; line-height: 1; border: none; border-radius: 5px; background: transparent; color: var\(--dim\);/, "the strip gear's shape at the header's size, in the box's tokens");
  assert.match(CSS, /\.ntc-bar \.ntc-gear:hover \{ color: var\(--fg\); background: color-mix\(in srgb, var\(--fg\) 8%, transparent\); \}/, "the hover in tokens too (css-vocab.test.ts reads every .ntc- colour)");
});

test("the box's chrome: the background box's frame, its one thin edge in the Needs you token, a header bar with the dot, above the background box, dense-chrome aware", () => {
  assert.match(CSS, /#notices \{ flex: 0 0 auto; min-height: 0; max-height: min\(40vh, 280px\); overflow: auto; box-sizing: border-box; margin: 8px 10px 0;\s*\n\s*border: 1px solid var\(--st-needs-bg\); border-radius: 8px; background: var\(--box-bg\);/);
  assert.match(CSS, /\.ntc-body \{[^}]*-webkit-line-clamp: 4;/, "the message text clamped");
  assert.match(CSS, /\.ntc-row\.ntc-open \.ntc-body \{ display: block; -webkit-line-clamp: unset; overflow: visible; \}/, "the brief's disclosure lifts the clamp (the second contributor's review)");
  assert.match(RENDER, /"ntc-more": \(el\) => \{[^\n]*const key = "notice:" \+ \(row\.dataset\.item \|\| ""\) \+ ":brief"; if \(openFolds\.has\(key\)\) openFolds\.delete\(key\); else openFolds\.add\(key\); row\.classList\.toggle\("ntc-open", openFolds\.has\(key\)\);/, "the disclosure toggles on the delegate, keyed by the item id in the one fold store, both ways, no latch");
  assert.match(RENDER, /row\.classList\.toggle\("ntc-open", openFolds\.has\("notice:" \+ n\.itemId \+ ":brief"\)\);[^\n]*\n  noticeMoreButton\(row, noticeLineOf\(row\)\);/, "re-applied on every row update, both ways; the disclosure rides the row's line (the box content round)");
  assert.match(fn("noticeLineOf"), /return \(\(row as any\)\._distill as HTMLElement \| undefined\) \?\? row\.querySelector<HTMLElement>\("\.ntc-body"\);/, "the line: the distill line on a row wearing the card's sections, else the markdown body");
  assert.match(fn("renderNoticeDisclosures"), /noticeMoreButton\(r, noticeLineOf\(r\)\);/, "the pass over the rows measures the same line (the head run of the box content round: it read the hidden body and removed the button the update had made)");
  assert.match(RENDER, /"ntc-more": \(el\) => \{[^\n]*noticeMoreButton\(row, noticeLineOf\(row\)\); \},/, "and so does the toggle");
  assert.match(fn("noticeSectionsFor"), /const want = n\.kind === "goal" && !n\.fix;\n  if \(want && !rowAny\._distill\) \{/, "the card's sections join a goal row without a fix when a frame first calls for them");
  assert.match(fn("noticeSectionsFor"), /\} else if \(!want && rowAny\._distill\) \{/, "and leave it when one stops (the credential row keeps its fault's explanation in the body; rows are reused by item)");
  assert.match(fn("updateNoticeRow"), /const sections = noticeSectionsFor\(row, n\);/, "decided on every frame, never at build");
  assert.match(RENDER, /const overflows = !!body && body\.style\.display !== "none" && body\.scrollHeight > body\.clientHeight \+ 1;/, "the button shows only when the body overflows");
  assert.match(RENDER, /if \(body && body\.style\.display !== "none" && body\.clientHeight === 0 && body\.scrollHeight === 0\) return;/, "a zero measure (a display:none pane) is no information: the row stands as it is (the post-merge review of PR 1967)");
  assert.match(RENDER, /watchChatVisibility\(document\.body, \{ \.\.\.browserChatVisibilityDeps\(\), onShown: renderNoticeDisclosures \}\);/, "the pane's return re-runs the disclosure pass");
  assert.match(RENDER, /window\.addEventListener\("resize", renderNoticeDisclosures\);/, "and so does a resize: Firefox's observer never reports the hidden pane (the second contributor's post-merge note on PR 2018)");
  assert.match(CSS, /\.ntc-bar \{ flex: 0 0 auto; display: flex; align-items: center; gap: 0; cursor: pointer;\n[^}]*position: sticky; top: 0; z-index: 1;\n  background: linear-gradient\(var\(--box-bg\), var\(--box-bg\)\), var\(--bg\); \}/, "an opaque ground under the box's wash, above the rows (the second contributor's review), on the bar since the box arc's round three; no gap and no padding on the bar, its cursor the fold's");
  assert.match(CSS, /\.ntc-head \{ flex: 1 1 auto; min-width: 0; display: flex; align-items: center; gap: 7px; padding: 7px 11px; font-size: 0\.92em; user-select: none; \}/, "the padding is the header's: the click target and the focus ring cover the whole line (the second contributor's review of PR 2120: on the bar it shrank the target to the text line)");
  assert.match(CSS, /body\.dense-chrome \.ntc-head \{ padding: 5px 11px; \}/, "the header compacts with the background box's");
  assert.match(fn("buildNoticeBar"), /bar\.dataset\.act = "ntc-fold";/, "the bar too is the fold control: every strip of it toggles the level, the gear resolving to its own action first");
  assert.match(CSS, /\.ntc-bar \.ntc-gear \{[^}]*margin: 0 11px 0 0;/, "the gear's right margin is the bar's 11px edge");
  assert.match(CSS, /\.ntc-btn\.ntc-ok \{ color: var\(--accent-ink\); border-color: color-mix\(in srgb, var\(--accent\) 90%, transparent\); \}/, "the ok label is the accent's ink token (the light theme's darker clay: the accent read 4.07:1 as text on the cream wash) and the ok border is the accent's own, on both themes, at the share that clears the 3:1 non-text floor on the light theme");
  assert.match(CSS, /\.ntc-btn\.ntc-deny \{ color: var\(--deny\); border-color: color-mix\(in srgb, var\(--deny\) \d+%, transparent\); \}/, "the deny label and border are the per-theme deny token (the second contributor's post-merge note on PR 2014)"); assert.match(CSS, /\.ntc-btn\.ntc-ok \{ color: var\(--accent-ink\); border-color: color-mix/);
  assert.match(CSS, /body\.dense-chrome #notices \{ margin: 4px 10px 0; \}/);
  assert.match(CSS, /\.ntc-attach \.fask-nimg \{ display: block; max-width: 100%;/, "the pinned picture in the row");
  assert.ok(CSS.indexOf("#notices {") > CSS.indexOf("#bg-tasks {"), "declared beside the background box's rules");
});

test("the row's badge slot sets no size of its own: the chips size themselves, so the row's chips are the card's size", () => {
  assert.match(CSS, /\.ntc-row \.ntc-badges \{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px; \}/, "the slot lays the chips out and nothing more");
  assert.doesNotMatch(CSS, /\.ntc-row \.ntc-badges \{[^}]*font-size/, "no font-size on the slot (a contributor's post-merge note on PR 2124: 0.86em there multiplied the chips' own em sizes, 14 percent smaller than the card's)");
});

test("awaitKey and awaitChanged, executed: a status frame moving one card field on one row re-renders the box, and an unchanged one does not", () => {
  // the whole-row key (awaitKey) and the re-render it drives (awaitChanged), lifted from render.ts and transpiled at run time (the models-rev
  // pattern), with the renderers counted (a contributor's post-merge note on PR 2124: the key was pinned by its source text alone)
  const req = createRequire(__filename);
  const lift = (name: string) => req("esbuild").transformSync(fn(name), { loader: "ts" }).code;
  const prelude = "let activeId = 's1'; const H = { bg: 0, notices: 0, sub: 0 }; const renderBgTasks = () => { H.bg++; }; const renderNotices = () => { H.notices++; }; const renderSubHead = () => { H.sub++; }; const liveSession = () => null;\n";
  const api = new Function(prelude + lift("awaitKey") + lift("awaitChanged") + "\nreturn { awaitKey, awaitChanged, H };")() as { awaitKey: (st: unknown) => string; awaitChanged: (sid: string) => void; H: { bg: number; notices: number; sub: number } };
  const row = { itemId: "s1:g1", kind: "goal", title: "which port?", body: "", cont: true, origin: { peer: "api", peerSid: "s2", live: true }, warns: null, tree: null };
  const status = (r: Record<string, unknown>) => ({ state: "idle", sinceEpoch: 1, notices: [r], awaitingWhy: "", awaitingKind: "", awaitingCount: null });
  const before = api.awaitKey(status(row));
  assert.equal(api.awaitKey(status({ ...row })), before, "an equal row, an equal key");
  const moved = api.awaitKey(status({ ...row, origin: { ...row.origin, live: false } }));
  assert.notEqual(moved, before, "one card field of one row moved (origin.live): the key moves");
  // the message handlers' pattern: the key before and after a frame, awaitChanged when it moved
  const apply = (b: string, a: string) => { if (a !== b) api.awaitChanged("s1"); };
  apply(before, api.awaitKey(status({ ...row })));
  assert.equal(api.H.notices, 0, "an unchanged row re-renders nothing");
  apply(before, moved);
  assert.deepEqual([api.H.notices, api.H.bg], [1, 1], "the moved field re-renders the box (and the awaiting box, which rides the same key)");
  api.awaitChanged("other");
  assert.equal(api.H.notices, 1, "another session's change leaves the active box alone");
});
