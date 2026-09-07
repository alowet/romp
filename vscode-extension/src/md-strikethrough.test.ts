// Strikethrough must require DOUBLE tildes (the user 2026-06-26): marked's built-in GFM `del` fires on a
// SINGLE tilde, so prose with two "approximately" tildes ("~21 Wh … ~1.5 days") rendered as one big struck-
// through run. The chat overrides the `del` tokenizer to require ~~ (matching GitHub). The override lives in
// ui/webview/chat-md.ts (shared by the assistant singleton and the user-text instance), so this test runs the
// REAL definition — no mirrored copy to drift — and source-pins that render.ts wires it into its marked.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import { Marked } from "marked";
import * as fs from "node:fs";
import * as path from "node:path";
import { delDoubleTilde } from "../../ui/webview/chat-md";

const m = new Marked({ gfm: true, breaks: false }, delDoubleTilde);

test("a single ~ (approximately) does NOT strike through", () => {
  const html = m.parse("near the ~21 Wh/day budget and it gives ~1.5 days of buffer") as string;
  assert.doesNotMatch(html, /<del>/, "lone tildes stay literal — no strikethrough");
  assert.match(html, /~21/);
  assert.match(html, /~1\.5/);
});

test("double ~~ still strikes through", () => {
  const html = m.parse("this is ~~struck~~ out") as string;
  assert.match(html, /<del>struck<\/del>/);
});

test("chat-md.ts holds the del-requires-double-tilde override and render.ts's marked takes it", () => {
  const ui = (f: string) => fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", f), "utf8");
  const grammar = ui("chat-md.ts");
  assert.match(grammar, /del\(src: string\)/);
  assert.match(grammar, /\/\^~~\(\?=\\S\)\(\[\\s\\S\]\*\?\\S\)~~\//, "the ~~-only del regex");
  assert.match(grammar, /export const chatMdExtensions: MarkedExtension\[\] = \[delDoubleTilde, /);
  const render = ui("render.ts");
  assert.match(render, /marked\.use\(\.\.\.chatMdExtensions\);/, "the singleton takes the shared grammar");
  assert.doesNotMatch(render, /del\(src: string\)/, "no second copy of the tokenizer in render.ts");
});
