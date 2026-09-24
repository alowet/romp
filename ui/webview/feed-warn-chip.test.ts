// The yellow "warning" chip + warn-detail overlay (the user 2026-07-02): a judge that hits an anomaly
// on a goal (e.g. the distiller's SOURCE citation didn't come back — judge _node_warn) stamps it on the
// node; the kernel ships it as card `warns`; the card shows a yellow pill whose click opens an overlay
// telling, per warn, what happened and why it's unexpected — so pipeline misbehavior is followable from
// the card instead of buried in judge-errors.jsonl. Source pin.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const FEED = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "feed.ts"), "utf8") + fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "card-sections.ts"), "utf8");   // the badges moved to card-sections.ts (round two of the box content PR: one builder for the card and the Needs you row)
const CSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "feed.css"), "utf8") + fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "card-sections.css"), "utf8");

test("the warning chip is a button where a click opens the detail and a span where nothing does, built once, riding the wrapping chip row", () => {
  assert.match(FEED, /const chip = el\(env\.openWarns \? "button" : "span", "fask-warnchip"\);/,
    "a BUTTON (focusable) on a page with a warn destination (the feed's overlay), a SPAN on one without (the chat page's row): no click is promised where none acts");
  assert.match(FEED, /const lbl = allDistill \? "distill failed" : "warning";/, "plain text label, no emoji/glyph");
  assert.match(FEED, /row2\.append\(idwrap, retryBadge, apiBadge, apiRetry, apiLogin, capLine, capBtn, jauthBadge, blkBadge, badges\)/);
  assert.match(FEED, /a\._badges = badges;/);
});

test("the click reads the card's CURRENT warns and opens the detail overlay (click-safe)", () => {
  // the handler is wired ONCE in build and reads _warnsData off the card element at click time, so the
  // incremental re-render (updateAskCard mutates in place) can never orphan the action mid-press.
  assert.match(FEED, /if \(env\.openWarns\) chip\.dataset\.act = "sec-open-warns";/, "delegated: the act routes to the page's openWarns with the host's freshest item (the badges are rebuilt on every update); a page without a destination gets a span that promises no click (the 0.17.1 fix)"); assert.match(FEED, /"sec-open-warns": \(el, ev\) => \{ ev\.stopImmediatePropagation\(\); const p = item\(el\); if \(p\) env\.openWarns\?\.\(p\.it, p\.it\.text \|\| ""\); \},/);
  assert.match(FEED, /openWarns: \(it, title\) => \{ if \(it\.warns && it\.warns\.length\) feedWarnModal\(title, it\.warns, \{ itemId: it\.itemId, sid: it\.sid \}, it\.failLog\); \},/);
  assert.match(FEED, /delegate\(card, sectionActs\(sectionEnv, \(\) => card\)\);/,
    "stopPropagation so the chip click never also opens the card modal");
});

test("updateAskCard toggles the chip on it.warns and refreshes the data it reads", () => {
  assert.match(FEED, /if \(it\.warns && it\.warns\.length\) \{\s*\n\s*\/\/ "warning" chip/, "built from the item on every update: no stashed copy to refresh");

  assert.match(FEED, /out\.push\(chip\);/);
  assert.match(FEED, /chip\.textContent = it\.warns\.length > 1 \? `\$\{lbl\} ×\$\{it\.warns\.length\}` : lbl;/,
    "multiple live warns show a count");
  assert.match(FEED, /it\.warns\[it\.warns\.length - 1\]\.msg\)\s*\n\s*\+ \(env\.openWarns \? "\\n— click for what happened and why" : ""\)/,
    "hover: the attempt history when one exists, else the latest msg — detail is a click away");
  assert.match(FEED, /tried \$\{f\.model\} — \$\{f\.note\}/,
    "each hover line is one attempt: model + literal error (the user 2026-08-18)");
});

test("the modal lists the attempt log — when, which model, the literal error (the user 2026-08-18)", () => {
  // "tried opus — 529, tried opus — 529, …" at a glance is what tells the user ONE model is down and
  // switching it fixes everything; prose can't carry that shape
  assert.match(FEED, /failLog\?: \{ t: number; line: string; model: string; note: string \}\[\] \| null/);
  assert.match(FEED, /meta\.textContent = "What was tried";/);
  assert.match(FEED, /tried \$\{f\.model\} for the \$\{f\.line\} — \$\{f\.note\}/);
  assert.match(FEED, /feedWarnModal\(title, it\.warns, \{ itemId: it\.itemId, sid: it\.sid \}, it\.failLog\)/,
    "the click hands the modal the card's freshest attempt data");
});

test("a given-up summarizer wears its NAME — 'distill failed' — and its modal offers Try again (the user 2026-08-13)", () => {
  // the chip says what actually happened when the warns are all summarizer give-ups; other anomaly
  // kinds keep the generic label (a mixed set is not purely a distill story)
  assert.match(FEED, /export const DISTILL_FAIL_RE = \/\^\(summary\|brief\|stall\)-failed\$\/;/);   // card-sections.ts: the chip and the modal read one family
  assert.match(FEED, /const allDistill = it\.warns\.every\(\(w\) => DISTILL_FAIL_RE\.test\(w\.kind\)\);/);
  assert.match(FEED, /const lbl = allDistill \? "distill failed" : "warning";/);
  // the modal's Try again: ids threaded from the card's freshest payload, instant acknowledgement,
  // then the redistill op — the re-armed line reads pending, so the card's Distilling… swirl takes over
  assert.match(FEED, /ctx\?: \{ itemId: string; sid: string \}/);
  assert.match(FEED, /\{ itemId: it\.itemId, sid: it\.sid \}, it\.failLog\)/);
  assert.match(FEED, /if \(ctx && warns\.some\(\(w\) => DISTILL_FAIL_RE\.test\(w\.kind\)\)\) \{/);
  assert.match(FEED, /retry\.disabled = true; retry\.textContent = "retrying…";/);
  assert.match(FEED, /vscodeApi\?\.postMessage\(\{ type: "redistill", itemId: ctx\.itemId, sid: ctx\.sid \}\);/);
  // the kernel's refusal is loud; success is the swirl, silently
  assert.match(FEED, /m\.type === "redistillResult" && typeof m\.itemId === "string"/);
  assert.match(FEED, /couldn't retry the summary: /);
});

test("Try again answers OUT LOUD in every column — success, refusal, and silence (the user 2026-08-13, round 2)", () => {
  // the first cut leaned on the Distilling… swirl, which a Working card withholds — the retry SUCCEEDED
  // and still read as a silent no-op. Success now toasts a promise true in every column…
  assert.match(FEED, /feedToast\("summary retry armed — it regenerates on the next judge pass over this card"\)/);
  // …and SILENCE is named too: a kernel that predates the redistill op drops it with no result at all,
  // so the click arms a backstop watch that only speaks when the ack never comes
  assert.match(FEED, /armRedistillWatch\(ctx\.itemId\);/);
  assert.match(FEED, /let redistillWatch: \{ itemId: string; timer: number \} \| null = null;/);
  assert.match(FEED, /no answer from the kernel about the summary retry — it may predate this feature/);
  // the ack — either verdict — disarms the watch before it can cry wolf
  assert.match(FEED, /if \(redistillWatch && redistillWatch\.itemId === m\.itemId\) \{\s*\n\s*window\.clearTimeout\(redistillWatch\.timer\);/);
});

test("the overlay lists each warn's kind/age and full detail", () => {
  assert.match(FEED, /function feedWarnModal\(cardTitle: string/);
  assert.match(FEED, /meta\.textContent = w\.kind \+ " · " \+ relAge\(/);
  assert.match(FEED, /body\.textContent = w\.detail \|\| w\.msg;/, "detail is the payload; msg is the floor");
  assert.match(FEED, /const onKey = \(e: KeyboardEvent\) => \{ if \(e\.key === "Escape"\) close\(\); \};/,
    "Esc closes, like feedConfirm");
});

test("the chip is a yellow pill and the overlay detail preserves its paragraphs", () => {
  assert.match(CSS, /\.fask-warnchip \{[^}]*color: #ffd166/);
  assert.match(CSS, /button\.fask-warnchip \{ cursor: pointer; \}/, "the hand belongs to the button alone");
  assert.match(CSS, /button\.fask-warnchip:hover \{ background:/, "and so does the hover tint");
  assert.doesNotMatch(CSS, /\n\.fask-warnchip \{[^}]*cursor/, "the shared rule names no cursor: the chat page's span shows the default one");
  assert.doesNotMatch(CSS, /\n\.fask-warnchip:hover/, "and no hover tint reaches the span (the contributor's note on the 0.17.1 fix: the span looked clickable)");
  assert.match(CSS, /\.fwarn-detail \{[^}]*white-space: pre-wrap/,
    "the what-happened/why-unexpected sections keep their blank-line structure");
});
