// REGRESSION GUARD (the user 2026-06-29): the distiller's captions were silently removed once, and the
// source-regex pins didn't catch it — they were just rewritten to assert the removal. These tests EXECUTE the
// real rule (ui/webview/distiller-line.ts), so if the distiller line stops showing — or starts showing the
// planner's why, or sticks on a placeholder — they FAIL. feed.ts routes both the card and the modal node
// through these functions, so this is the single executable source of truth for "is the distiller shown?".
import { test } from "node:test";
import * as assert from "node:assert/strict";
import { distillText, distillInputs, applyDistillLine, distillPending } from "./distiller-line";

// ── distillText: the rule, executed ───────────────────────────────────────────────────────────────────────
test("a COMPLETED item shows the distiller's takeaway (summary)", () => {
  assert.equal(distillText(true, false, "Shipped: see commit abc123", "ignored brief"), "Shipped: see commit abc123");
});

test("a BLOCKED item shows the distiller's decision brief (blockSummary)", () => {
  assert.equal(distillText(false, true, "ignored takeaway", "Decide: A vs B"), "Decide: A vs B");
});

test("the line stays EMPTY until the distiller produces — never a stuck placeholder", () => {
  assert.equal(distillText(true, false, null, null), "", "no summary yet → nothing (not '(generating…)')");
  assert.equal(distillText(true, false, "", null), "", "settled-empty → nothing");
  assert.equal(distillText(true, false, "   ", null), "", "whitespace-only → nothing (trimmed)");
});

test("a completed card never leaks the blockSummary, and a blocked card never leaks the summary", () => {
  assert.equal(distillText(true, false, null, "block brief"), "", "completed + only blockSummary → nothing");
  assert.equal(distillText(false, true, "done takeaway", null), "", "blocked + only summary → nothing");
});

test("neither completed nor blocked → nothing (an open/working card carries no distiller line)", () => {
  assert.equal(distillText(false, false, "x", "y"), "");
});

test("the takeaway is shown VERBATIM (trimmed) — a copy-pasteable artifact survives intact", () => {
  const artifact = "  romp --mail send ui3 \"hi\"\npath: ~/x/y.ts  ";
  assert.equal(distillText(true, false, artifact, null), artifact.trim());
});

// distillText structurally CANNOT show the why: its signature has no `why` parameter. This is the invariant
// that keeps the why-rationale lines (which the user dropped) from ever creeping back via this path.
test("distillText has no `why` input, so it can never display the planner's rationale", () => {
  assert.equal(distillText.length, 4, "(completed, blocked, summary, blockSummary) — exactly four params, no why");
});

// ── distillInputs: a card in the Working column carries NO distilled line (the user 2026-07-22) ──────────────
test("a card in the Working column shows no distilled line, whatever its genuine state says", () => {
  // A summary describes work that has stopped. The moment the card is working again it describes a past that
  // may no longer hold, and a card reading "in motion" while wearing a settled takeaway contradicts itself.
  assert.deepEqual(distillInputs("blocked", "working"), { completed: false, blocked: false },
    "genuinely blocked but displaced to Working (recheck/rejudge) → withhold the brief for now");
  assert.deepEqual(distillInputs("completed", "working"), { completed: false, blocked: false },
    "same for a takeaway on a card that went back to working");
  assert.deepEqual(distillInputs(null, "working"), { completed: false, blocked: false });
  assert.deepEqual(distillInputs(undefined, "working"), { completed: false, blocked: false });
});

test("the line comes back untouched the moment the card settles again", () => {
  // Withheld, not discarded: nothing about the payload changes while it is hidden, so a card that settles
  // back to exactly where it was renders exactly what it had before.
  assert.deepEqual(distillInputs("blocked", "needs_input"), { completed: false, blocked: true });
  assert.deepEqual(distillInputs(null, "needs_input"), { completed: false, blocked: true }, "a stall floor: filed under needs_input with no distill state, it reads blocked, so the card and the Needs you row both show the Distilling caption until its brief lands");
  assert.deepEqual(distillInputs(undefined, "needs_input"), { completed: false, blocked: true });
  assert.deepEqual(distillInputs("completed", "completed"), { completed: true, blocked: false });
  const { completed, blocked } = distillInputs("blocked", "needs_input");
  assert.equal(distillText(completed, blocked, null, "Decide: consolidate the Internals pages or not"),
    "Decide: consolidate the Internals pages or not");
});

test("distillState still decides a settled card, and an absent field falls back to the column", () => {
  // distillState is the GENUINE resolution state, so it still resolves a settled card whose column disagrees.
  assert.deepEqual(distillInputs("blocked", "completed"), { completed: false, blocked: true },
    "genuine state wins over a disagreeing settled column");
  // older / remote payloads omit the field: read the column's old meaning so federation frames still render
  assert.deepEqual(distillInputs(undefined, "needs_input"), { completed: false, blocked: true },
    "no distillState (old/remote) + needs_input column → blocked (legacy behavior preserved)");
  assert.deepEqual(distillInputs(undefined, "completed"), { completed: true, blocked: false });
});

// ── applyDistillLine: the SHOW/HIDE behavior, executed against a fake element (no DOM needed) ───────────────
function fakeEl() { return { textContent: "x", style: { display: "x" } }; }

test("applyDistillLine SHOWS the line (display unset) and sets the text when the distiller has produced", () => {
  const el = fakeEl();
  const out = applyDistillLine(el, true, false, "Done: X", null);
  assert.equal(out, "Done: X");
  assert.equal(el.textContent, "Done: X");
  assert.equal(el.style.display, "", "a produced summary is shown (display cleared, not 'none')");
});

test("applyDistillLine HIDES the line when there's nothing to show — no empty box, no placeholder", () => {
  const el = fakeEl();
  applyDistillLine(el, true, false, "", null);
  assert.equal(el.textContent, "");
  assert.equal(el.style.display, "none");
});

test("applyDistillLine shows the blockSummary on a blocked card", () => {
  const el = fakeEl();
  applyDistillLine(el, false, true, null, "Decide A vs B");
  assert.equal(el.textContent, "Decide A vs B");
  assert.equal(el.style.display, "");
});

// ── distillPending: the "distiller is running → show the spinning swirl" rule, executed (the user 2026-06-29) ──
test("a COMPLETED card is distill-PENDING while its summary is null (distiller running → spinner)", () => {
  assert.equal(distillPending(true, false, null, null), true, "no summary yet → pending");
  assert.equal(distillPending(true, false, undefined, null), true, "undefined summary → pending");
});

test("a COMPLETED card is NOT pending once the distiller settled — produced OR gave up", () => {
  assert.equal(distillPending(true, false, "Shipped X", null), false, "produced takeaway → line shows, no spin");
  assert.equal(distillPending(true, false, "", null), false, "gave-up '' sentinel → no spin, no line");
});

test("a BLOCKED card is distill-PENDING while its blockSummary is null — but NOT when live-blocked (on you)", () => {
  assert.equal(distillPending(false, true, null, null), true, "awaiting decision brief → pending");
  assert.equal(distillPending(false, true, null, "Decide A vs B"), false, "brief produced → no spin");
  assert.equal(distillPending(false, true, null, null, true), false, "live permission/picker block is ON YOU → no distill spin");
});

test("an open/working card (neither completed nor blocked) is never distill-pending", () => {
  assert.equal(distillPending(false, false, null, null), false);
});

// The states the kernel's _landing_inputs mirrors term for term (T388), one producible pair added: the SAME rows sit in
// tests/test_card_summary_anchor.py LINE_RULE_TABLE, and the Python test pins that this file carries them.
const LINE_RULE_TABLE: Array<[string, "completed" | "blocked" | null, string, boolean, boolean]> = [
  ["stall floor", null, "needs_input", false, true],
  ["permission floor", "blocked", "needs_input", false, true],
  ["real block in recheck", "blocked", "working", false, false],
  ["done confirming", null, "working", false, false],
  ["completed", "completed", "completed", true, false],
  ["plain working", null, "working", false, false],
  ["completed under a needs-input column", "completed", "needs_input", true, false],   // the producible pair the six left out
];

test("distillInputs over the states the kernel's landing rule mirrors", () => {
  for (const [name, state, column, completed, blocked] of LINE_RULE_TABLE) {
    assert.deepEqual(distillInputs(state, column), { completed, blocked }, name);
  }
});
