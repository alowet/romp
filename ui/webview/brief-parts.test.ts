// Per-paragraph brief ages (the user 2026-07-24). A MULTI-item decision brief writes one paragraph
// per owed item in order (judge BLOCK_BRIEF_SYS 2026-07-21), and the kernel ships briefParts —
// [{id, since}] in that same order, each `since` the ask's own block-event time — so the card stamps
// every paragraph with a live "Nm ago" of ITS OWN ask. The incident this serves: a card re-displayed
// a brief whose go-ahead the user had given two hours earlier; a per-paragraph age makes exactly that
// staleness visible at a glance. Source-pinned like the sibling stall-section test: feed.ts builds
// the card imperatively, so the wiring is asserted over the source.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const FEED = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "feed.ts"), "utf8");
const CSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "feed.css"), "utf8");
const KERNEL = fs.readFileSync(path.resolve(process.cwd(), "..", "kernel", "kernel.py"), "utf8");
const JUDGE = fs.readFileSync(path.resolve(process.cwd(), "..", "kernel", "judge.py"), "utf8");
// Prompts are WRAPPED string literals, so any phrase in them spans source lines. Join adjacent literals
// before matching, or these pins assert where the line breaks fall rather than what the prompt says.
const JUDGE_FLAT = JUDGE.replace(/"[ \t]*\n[ \t]*"/g, "");

test("the AskItem declares briefParts and summaryParts in the kernel's shape", () => {
  assert.match(FEED, /briefParts\?: \{ id\?: string; since: number \}\[\] \| null;/);
  assert.match(FEED, /summaryParts\?: \{ id\?: string; since: number \}\[\] \| null;/);
});

test("the kernel ships briefParts and summaryParts beside the brief and takeaway", () => {
  assert.ok(KERNEL.includes('"briefParts": nodes[nid].get("briefParts") or None'));
  assert.ok(KERNEL.includes('"summaryParts": nodes[nid].get("summaryParts") or None'));
});

test("the distiller side is the model's call — split per item or stay one story", () => {
  assert.ok(JUDGE_FLAT.includes("Never pad a single story into per-item paragraphs."),
    "DISTILL_SYS offers the per-item form without forcing takeaway bloat");
  assert.ok(JUDGE.includes('nodes[top]["summaryParts"] = ([{"id": d["id"], "since": _done_since(d)} for d in _dsubs]'),
    "summaryParts written in <completed-items> order with each item's own done time");
});

test("the judge stores one {id, since} per owed item, in order, multi-item only", () => {
  assert.ok(JUDGE.includes('nodes[top]["briefParts"] = ([{"id": d["id"], "since": _block_since(d)} for d in blkd]'),
    "written from the SAME blkd list the owed paragraphs were ordered by");
  assert.ok(JUDGE.includes("if (not proc_only and len(blkd) > 1) else None)"),
    "single-item briefs store nothing — the card header's age is that stamp (the user's rule)");
});

test("the renderer gates on state-matched parts + multi-item + the paragraph-count match", () => {
  assert.ok(FEED.includes("const bp = dCompleted ? it.summaryParts : dBlocked ? it.briefParts : null;"),
    "parts must belong to the state being shown: briefParts <-> blocked brief, summaryParts <-> takeaway");
  assert.ok(FEED.includes("if (distillShown && ((bp && bp.length > 1) || (pAnchors && pAnchors.some(Boolean))))"),
    "multi-item stamps or per-paragraph citations (T220) — a single unstamped, uncited ask keeps the header age");
  assert.ok(FEED.includes("const stampOk = !!(bp && bp.length > 1 && (paras.length === bp.length || paras.length === bp.length + 1));"),
    "the model may merge paragraphs — a missing stamp beats a wrong one — but ONE extra trailing "
    + "paragraph is the still-open line, which is expected, not a mismatch");
  assert.match(FEED, /split\(\/\\n\\s\*\\n\/\)/, "paragraphs split on blank lines, the brief's own separator");
});

// The still-open paragraph (the user 2026-07-29): all three judge prompts now end a summary with whatever
// is NOT finished, alone, in one short sentence. That paragraph belongs to no <completed-items> item and no
// <owed> row, so it must render WITHOUT an age chip — and, before this, its mere presence pushed the count
// to items+1 and the exact-match gate silently dropped every stamp on the card.
test("the trailing still-open paragraph renders unstamped, and only the item paragraphs get ages", () => {
  assert.ok(FEED.includes("if (stampOk && i < bp!.length) {"),
    "the chip is appended only for paragraphs that HAVE a part; the extra one gets none");
  const block = FEED.slice(FEED.indexOf("// PER-PARAGRAPH ages"), FEED.indexOf("// The distiller line is a LINK"));
  assert.ok(/paras\.forEach\(\(p, i\) => \{[\s\S]*?if \(stampOk && i < bp!\.length\) \{[\s\S]*?if \(bp!\[i\]\.since\) stampAge\(age, bp!\[i\]\.since/.test(block),
    "the guard wraps the stamp's since lookup itself, so bp[i] is never read past the end");
  assert.ok(block.includes("ONE EXTRA TRAILING PARAGRAPH"), "the why is recorded where the gate lives");
});

// The prompt side of this contract is asserted in tests/test_distill_paragraph_contract.py, which loads
// judge.py and reads the CONCATENATED prompt strings. Don't re-assert it over the source text here: the
// prompts are wrapped literals, so any phrase spans source lines and a grep pins line breaks, not behavior.

test("each paragraph wears its own live age chip", () => {
  assert.ok(FEED.includes('el("span", "fask-para-age")'));
  assert.ok(FEED.includes('if (bp![i].since) stampAge(age, bp![i].since, "plain", false, nowS, relAge, ageColorReadable);'),
    "the ask's OWN block-event age, via the shared relAge vocabulary — stamped, so the 15 s live pass moves it on a card the update gate does not repaint");
  assert.ok(FEED.includes('else age.textContent = relAge(0);'), "no event time → the static chip it always showed, unstamped (nothing to count from)");
});

test("the chip inherits the brief's font size — dimness is the only differentiation", () => {
  const rule = CSS.match(/\.fask-para-age \{[^}]*\}/);
  assert.ok(rule, "the chip has a css rule");
  assert.ok(!/font-size/.test(rule![0]),
    "no new font-size on this surface (the consistent-fonts rule); var(--dim) does the work");
  assert.match(rule![0], /var\(--dim\)/);
});
