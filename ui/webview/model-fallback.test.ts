// A mid-turn safeguards model swap must be visible in the chat, never silent (the user 2026-08-03:
// fable's safeguards flagged a message, the CLI silently retried on opus, and nothing in the chat said
// so). The kernel emits {kind:"modelFallback"} from the transcript's system/model_refusal_fallback
// record; render.ts wears it as the retried note's slim rail line in the warning voice, with the CLI's
// full explanation one click away. render.ts has import-time DOM side effects → source pins
// (rewind-delete.test.ts precedent).
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const RENDER = fs.readFileSync(
  path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const CSS = fs.readFileSync(
  path.resolve(process.cwd(), "..", "ui", "webview", "styles.css"), "utf8");

test("the modelFallback kind is dispatched to its renderer", () => {
  assert.match(RENDER, /if \(ev\.kind === "modelFallback"\) return renderModelFallback\(ev\);/);
  // and the union carries the payload the kernel sends (raw ids + the CLI's explanation)
  assert.match(RENDER, /kind: "modelFallback"; from\?: string; to\?: string; md\?: string/);
});

test("the head names both models via prettyModel, in the WARN severity", () => {
  // 2026-09-08 (the notice-vocabulary pass): a SESSION notice with the warn severity on its rail; the gist string
  // lives in modelFallbackGist, shared with compact mode's group head
  const body = RENDER.split("function renderModelFallback(")[1].split("\nfunction ")[0];
  assert.match(body, /notice\(\{ src: "session", glyph: "power", sev: "warn", gist: modelFallbackGist\(ev\), body,/);
  const gist = RENDER.split("function modelFallbackGist(")[1].split("\n}")[0];
  assert.match(gist, /prettyModel\(ev\.from\)/);
  assert.match(gist, /prettyModel\(ev\.to\)/);
  assert.match(gist, /safeguards flagged this message/);
  assert.doesNotMatch(body, /apierror|gaveup/);
});

test("the full CLI notice is one click away and the fold survives re-renders", () => {
  const body = RENDER.split("function renderModelFallback(")[1].split("\nfunction ")[0];
  assert.match(body, /body\.textContent = ev\.md;/, "verbatim notice — never paraphrased chrome");
  // 2026-09-08: keyed through the builder (openFolds "notice:mswap:<uuid>"), toggled by the delegate
  assert.match(body, /key: ev\.uuid \? "mswap:" \+ ev\.uuid : undefined/, "fold keyed by the record's uuid");
  const nc = RENDER.split("function notice(spec: NoticeSpec)")[1].split("\nfunction ")[0];
  assert.match(nc, /applyFold\(card, "notice-open", fkey\)/);
  assert.match(RENDER, /noticetoggle: \(el\) => \{[\s\S]{0,400}?rememberFold\(card, "notice-open", el\.dataset\.nkey \|\| undefined\);/);
});

test("the body is hidden until expanded, in the one notice family; the warn is the rail's colour", () => {
  assert.match(CSS, /\.notice-collapsible:not\(\.notice-open\) > \.notice-body \{ display: none; \}/);
  assert.match(CSS, /\.notice-sev-warn\s+\{ --notice-rail: var\(--warn\);/);
  assert.match(CSS, /\.notice-prose \{ white-space: pre-wrap;/);   // the CLI's text keeps its line breaks
  assert.doesNotMatch(CSS, /\.modelswap-/);
});
