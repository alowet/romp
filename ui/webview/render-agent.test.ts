// Subagent (Task/Agent) display, disclosed progressively (the user 2026-07-17: default compact, click to
// go deeper): level 0 is ONE head row (Agent + description + the run-state rail dot) plus, while the
// agent runs, a three-row preview of its latest tool calls; level 1 — ONE click on the head's inline
// fold — reveals everything, all OPEN and in the label's order: the prompt as markdown (the prompt
// field, not the tool JSON — the user 2026-07-08), the full list of tool calls, then the report as
// markdown once the agent has finished.
//
// PINS MOVED DELIBERATELY (2026-09-05): the 2026-07-08 cut nested the prompt and the report as
// collapsed caret boxes INSIDE the fold, so reading the prompt took two clicks — the user found that
// odd. The fold now carries the rest in one click, with nothing nested, and its label says what the
// click reveals ("prompt · 12 tool calls" / "… · report · 3 lines"). No jsdom harness for the chat
// renderer, so — like the other webview tests — pin it at the source level.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const CSS = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "styles.css"), "utf8");

// the Agent branch of renderTool, from `if (signal) {` to the `} else if (!ev.output) {` that follows it
const AGENT = (RENDER.match(/if \(signal\) \{[\s\S]*?\n    \} else if \(!ev\.output\) \{/) || [""])[0];

test("the PROMPT is the prompt field, markdown-rendered into an agent-report box, OPEN inside the fold (no nested caret box)", () => {
  assert.ok(AGENT.length > 500, "found the Agent branch");
  // the prompt shown is the actual prompt field (not the raw tool JSON)…
  assert.match(AGENT, /try \{ const o = JSON\.parse\(ev\.input\); if \(o && typeof o\.prompt === "string"\) promptText = o\.prompt; \}/);
  // …rendered as markdown into an agent-report box (the "nicer font" — no more preEl(promptText))…
  assert.match(AGENT, /const box = el\("div", "agent-report md"\); box\.innerHTML = md\(promptText\); highlight\(box\);\s*\n\s*body\.appendChild\(box\);/);
  // …appended DIRECTLY to the fold body: no foldable() wrapper anywhere in the branch (2026-09-05 — the
  // nested "prompt" / "report · N lines" caret boxes cost a second click)
  assert.doesNotMatch(AGENT, /foldable\(/, "nothing nested inside the Agent fold");
  assert.doesNotMatch(AGENT, /fkey \+ ":agent"/, "no sub-keys — one fold, one key");
  assert.doesNotMatch(RENDER, /body\.appendChild\(preEl\(promptText\)\)/, "the plain <pre> prompt is gone");
  assert.doesNotMatch(RENDER, /el\("div", "agent-fold"\)/, "the shared agent-fold body wrapper is gone");
});

test("level 0 is ONE head row: the fold hangs off the head's inline toggle under the tool's own key", () => {
  assert.match(AGENT, /const body = el\("div", "agent-folds"\);/);
  assert.match(AGENT, /if \(body\.childElementCount\) \{/);
  assert.match(AGENT, /inlineFold\(head, turn, label, body, fkey\);/, "the same fkey as before, so an open fold survives re-renders");
});

test("the fold LABEL says what one click reveals: prompt · N tool calls [· report · N lines]", () => {
  assert.match(AGENT, /const label = agentFoldLabel\(\{ stepsTotal: ev\.stepsTotal \?\? steps\.length, reportLines: ev\.output \? countLines\(ev\.output\) : null \}\);/);
  // the old two-shape label is gone
  assert.doesNotMatch(RENDER, /`prompt \+ report · /);
});

test("the fold's CONTENT order is prompt, then every tool call (one dim row each, the preview's classes), then the report", () => {
  const iPrompt = AGENT.indexOf("md(promptText)");
  const iSteps = AGENT.indexOf('el("div", "agent-gist agent-steps")');
  const iReport = AGENT.indexOf("md(ev.output)");
  assert.ok(iPrompt > 0 && iSteps > iPrompt && iReport > iSteps, `order: prompt ${iPrompt} < steps ${iSteps} < report ${iReport}`);
  // the steps list: the shared row builder over stepLines (every step, the clock's elapsed on the last row while running)
  assert.match(AGENT, /appendGistRows\(list, stepLines\(steps, ev\.agentGist, Date\.now\(\)\)\);/);
  assert.match(AGENT, /const steps = ev\.agentSteps \|\| \[\];/);
  // the cap note, one line, only when the kernel cut the oldest calls
  assert.match(AGENT, /const note = stepsNote\(steps\.length, ev\.stepsTotal\);\s*\n\s*if \(note\) \{ const n = el\("div", "agent-steps-note"\); n\.textContent = note; list\.appendChild\(n\); \}/);
  // the report: markdown in the same green-edged box, appended last, no caret box
  assert.match(AGENT, /const box = el\("div", "agent-report md"\); box\.innerHTML = md\(ev\.output\); highlight\(box\);\s*\n\s*body\.appendChild\(box\);/);
  assert.match(CSS, /\.agent-report \{[^}]*border-left: 2px solid rgba\(87, 181, 15/);
  // the list wears the preview's classes and size — no new font-size; the note rides the same block
  assert.match(CSS, /\.agent-folds > \.agent-steps \{ margin: [^}]*\}/);
  assert.match(CSS, /\.agent-steps-note \{[^}]*\}/);
  assert.doesNotMatch(CSS, /\.agent-steps[^{]*\{[^}]*font-size/, "the steps list inherits .agent-gist's 0.86em");
  // the old per-section uppercase label + the 300px preview clamp are both gone
  assert.doesNotMatch(RENDER, /agent-fold-label/, "the per-section labels are gone");
  assert.doesNotMatch(CSS, /\.agent-fold-label \{/, "the .agent-fold-label rule is gone");
  assert.doesNotMatch(RENDER, /el\("div", "io-clamp agent-clamp"\)/, "the 300px report clamp block is removed");
});

test("the level-0 preview shows only while RUNNING with the fold CLOSED; a FINISHED head still carries the open-transcript arrow", () => {
  const tail = (RENDER.match(/if \(\(ev\.name === "Task" \|\| ev\.name === "Agent"\) && ev\.agentId\) \{[\s\S]*?\n  \}\n  return turn;/) || [""])[0];
  assert.ok(tail.length > 200, "found the arrow/preview block");
  // the arrow is gated on agentId alone — nothing about output, clock or run-state (the user asked that a
  // finished agent keep its arrow, 2026-09-05)
  assert.match(tail, /head\.appendChild\(agentOpenButton\(ev\.agentId, ev\.uuid \|\| null, renderingOwnerSid \|\| renderingSid \|\| null\)\);/);
  assert.doesNotMatch(tail.split("agentOpenButton")[0], /agentGist|agentRunning|ev\.output|agentSteps/);
  // the preview: the clock ships only while running (kernel: agentGist goes at finish), and the fold's
  // open state comes from openFolds under the fold's own key — closed → preview, open → the full list
  assert.match(tail, /if \(ev\.agentGist && !\(fkey && openFolds\.has\(fkey\)\)\) head\.insertAdjacentElement\("afterend", renderAgentGist\(ev\.agentSteps, ev\.agentGist\)\);/);
  assert.match(CSS, /\.turn-tool\.fold-open > \.agent-preview \{ display: none; \}/, "the click itself hides it, before the next rebuild");
});

test("a still-running agent (dispatched, no report yet) reads as RUNNING — amber working dot, not green ✓ (the user 2026-06-24)", () => {
  // mirrors the TUI's clearer running/done split: an Agent/Task with no output yet is still going, so it gets
  // a solid amber working dot instead of the green success dot.
  assert.match(RENDER, /const agentRunning = \(ev\.name === "Task" \|\| ev\.name === "Agent"\) && !ev\.output && !ev\.isError;/);
  assert.match(RENDER, /dot\(ev\.isError \? "ring" : agentRunning \? "working" : "green"\)/);
  assert.match(CSS, /\.dot\.working \{ background: var\(--st-working-bg\)/);
});
