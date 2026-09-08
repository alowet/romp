// Regression guard for the chat-webview XSS hole: untrusted transcript markdown
// (user prompts, assistant output, subagent reports, postal bodies) is rendered
// to .innerHTML. `marked` emits raw HTML verbatim, so md() MUST route its output
// through DOMPurify before returning — otherwise a payload like
// `<img src=x onerror=...>` or `[x](javascript:...)` executes in the webview and
// can postMessage the host to open files / drive sessions. There is no jsdom
// harness for the chat renderer, so — like the other webview tests — pin it at
// the source level (assert the sanitizer is wired into md()).
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");

test("md() sanitizes marked output with DOMPurify before returning HTML", () => {
  assert.match(RENDER, /import DOMPurify from "dompurify";/);
  // (the signature grew an optional repo parameter for PR links — pr-links.ts — so match it loosely)
  const mdFn = RENDER.match(/function md\(src: string[^\n]*?\): string \{[\s\S]*?\n\}/)?.[0] || "";
  assert.ok(mdFn, "md() function not found");
  // marked is still used to parse, but its output must pass through DOMPurify.sanitize
  assert.match(mdFn, /marked\.parse\(/);
  assert.match(mdFn, /DOMPurify\.sanitize\(/);
  // the old, unsanitized `return marked.parse(src) as string;` must be gone
  assert.doesNotMatch(mdFn, /return\s+marked\.parse\(src\)\s+as\s+string;/);
});

test("dompurify is a declared dependency", () => {
  const pkg = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "package.json"), "utf8"));
  const has = (pkg.dependencies && pkg.dependencies.dompurify) ||
              (pkg.devDependencies && pkg.devDependencies.dompurify);
  assert.ok(has, "dompurify must be declared in package.json");
});
