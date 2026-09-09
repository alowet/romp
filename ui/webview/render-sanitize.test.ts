// Regression guard for the chat-webview XSS hole: untrusted transcript markdown
// (user prompts, assistant output, subagent reports, postal bodies) is rendered
// to .innerHTML. `marked` emits raw HTML verbatim, so md() MUST route its output
// through DOMPurify before returning — otherwise a payload like
// `<img src=x onerror=...>` or `[x](javascript:...)` executes in the webview and
// can postMessage the host to open files / drive sessions. There is no jsdom
// harness for the chat renderer, so — like the other webview tests — pin it at
// the source level (assert the sanitizer is wired into md()). The DOMPurify call
// lives in md-sanitize.ts (sanitizeMd), one sanitizer shared with the file viewer's
// mdBlock; md() and userMd() call it. What the sanitizer does is executed in
// headless Chromium (md-sanitize-browser.test.ts, md-sanitize-postpass-browser.test.ts).
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const VIEW = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "file-view.ts"), "utf8");
const SANITIZE = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "md-sanitize.ts"), "utf8");

test("md() sanitizes marked output with DOMPurify before returning HTML", () => {
  assert.match(RENDER, /import \{[^}]*\bsanitizeMd\b[^}]*\} from "\.\/md-sanitize";/);
  assert.doesNotMatch(RENDER, /from "dompurify"|DOMPurify\.sanitize\(/, "render.ts holds no sanitizer of its own");
  assert.match(SANITIZE, /import DOMPurify from "dompurify";/);
  assert.match(SANITIZE, /export function sanitizeMd\(dirty: string\): HTMLElement \{[\s\S]*?DOMPurify\.sanitize\(dirty, /);
  // (the signature grew an optional repo parameter for PR links — pr-links.ts — so match it loosely)
  const mdFn = RENDER.match(/function md\(src: string[^\n]*?\): string \{[\s\S]*?\n\}/)?.[0] || "";
  assert.ok(mdFn, "md() function not found");
  // marked is still used to parse, but its output must pass through sanitizeMd (the DOMPurify call)
  assert.match(mdFn, /marked\.parse\(/);
  assert.match(mdFn, /const clean = sanitizeMd\(dirty\);/);
  // the old, unsanitized `return marked.parse(src) as string;` must be gone
  assert.doesNotMatch(mdFn, /return\s+marked\.parse\(src\)\s+as\s+string;/);
});

test("the file viewer's mdBlock adopts the same sanitizer's output, and spells no profile of its own", () => {
  assert.match(VIEW, /import \{ sanitizeMd \} from "\.\/md-sanitize";/);
  assert.doesNotMatch(VIEW, /from "dompurify"|DOMPurify\.sanitize\(/, "the viewer holds no sanitizer of its own");
  const mdBlock = VIEW.match(/function mdBlock\([^\n]*\{[\s\S]*?\n\}/)?.[0] || "";
  assert.ok(mdBlock, "mdBlock not found");
  assert.match(mdBlock, /marked\.parse\(/);
  // the sanitized <body>'s children are adopted as they are (no re-parse of a serialized string)
  assert.match(mdBlock, /box\.replaceChildren\(\.\.\.Array\.from\(sanitizeMd\(dirty\)\.childNodes\)\);/);
  assert.doesNotMatch(mdBlock, /box\.innerHTML = /, "nothing reaches the viewer's innerHTML unsanitized");
});

test("dompurify is a declared dependency", () => {
  const pkg = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "package.json"), "utf8"));
  const has = (pkg.dependencies && pkg.dependencies.dompurify) ||
              (pkg.devDependencies && pkg.devDependencies.dompurify);
  assert.ok(has, "dompurify must be declared in package.json");
});
