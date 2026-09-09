// A mid-turn safeguards model swap must be visible in the chat, never silent (the user 2026-08-03:
// fable's safeguards flagged a message, the CLI silently retried on opus, and nothing in the chat said
// so). The kernel emits {kind:"modelFallback"} from the transcript's system/model_refusal_fallback
// record. T279: render.ts wears it as a SOURCED notice in the shared notice-card grammar — the
// "safeguards" chip, a one-line head naming the models and the refusal category, and the API's
// explanation (plus the CLI's own line) folded one click away — never as the user's bubble and never in
// the red API-error dress. render.ts has import-time DOM side effects → source pins (rewind-delete.test.ts
// precedent).
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const RENDER = fs.readFileSync(
  path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const CSS = fs.readFileSync(
  path.resolve(process.cwd(), "..", "ui", "webview", "styles.css"), "utf8");

function renderer(): string {
  const fn = RENDER.slice(RENDER.indexOf("function renderModelFallback"));
  return fn.slice(0, fn.indexOf("\n}"));
}

test("the modelFallback kind is dispatched to its renderer", () => {
  assert.match(RENDER, /if \(ev\.kind === "modelFallback"\) return renderModelFallback\(ev\);/);
  // the union carries the payload the kernel sends: raw ids, the CLI's line, the refusal's category,
  // the API's explanation and the scope (session model swapped vs. one local reply)
  for (const field of ["category", "explanation", "scope"]) {
    assert.match(RENDER, new RegExp('kind: "modelFallback";[^}]*' + field + '\\?: string'), field + " is typed on the event");
  }
});

test("the notice is a sourced notice card: the safeguards chip, in the warning voice", () => {
  const body = renderer();
  assert.match(body, /noticeCard\(\{ variant: "refusal", chip: "safeguards"/);
  assert.match(RENDER, /type NoticeVariant = [^;]*"refusal"/, "the grammar's variant union admits it");
  // never a red/blocked dress: a swap is a warning about provenance, not a failure of the turn
  assert.doesNotMatch(body, /apierror|gaveup/);
  assert.doesNotMatch(RENDER, /"modelswap-(line|text|body)"|turn-modelswap/, "the old slim rail line's classes are gone");
});

test("the head names both models via prettyModel and the refusal category", () => {
  const body = renderer();
  assert.match(body, /prettyModel\(ev\.from\)/);
  assert.match(body, /prettyModel\(ev\.to\)/);
  assert.match(body, /safeguards flagged this message/);
  assert.match(body, /ev\.category/);
  // 'local' scope: only that reply came from the fallback model — the session's model is unchanged
  assert.match(body, /ev\.scope === "local"/);
  assert.match(body, /switched to/);
});

test("the API's explanation and the CLI's own line fold under the head, keyed by the record's uuid", () => {
  const body = renderer();
  assert.match(body, /ev\.explanation/);
  assert.match(body, /ev\.md/, "the CLI's verbatim line still rides along — never paraphrased chrome");
  assert.match(body, /"mswap:" \+ ev\.uuid/, "fold keyed by the record's uuid");
});

test("a truncated head is recoverable: the full head is the hover, and the fold restates the swap", () => {
  // progressive disclosure never dead-ends: a narrow pane ellipsizes the head from the right, which cuts
  // exactly the swap and the category the card exists to surface (review, 2026-09-09)
  const body = renderer();
  assert.match(body, /querySelector\("\.notice-head-text"\)\?\.setAttribute\("title", head\)/);
  assert.match(body, /el\("div", "refusal-swap"\)/);
  assert.match(CSS, /\.refusal-swap \{/);
  assert.doesNotMatch(RENDER, /Slim rail line in the warning voice/, "the retired treatment's comment is gone too");
});

test("the refusal variant wears the heads-up amber, like the other notice variants wear theirs", () => {
  assert.match(CSS, /\.notice-card-refusal \{ border-left-color: var\(--warn/);
  assert.match(CSS, /\.notice-chip-refusal \{ color: var\(--warn/);
  assert.match(CSS, /\.notice-dot-refusal \{ border-color: var\(--warn/);
  assert.doesNotMatch(CSS, /\.modelswap-(line|text|body)/, "the retired line's rules are gone");
});
