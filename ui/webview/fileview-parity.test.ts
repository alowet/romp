// The file VIEWER mounts in both documents (file-view.ts is one shared module), but the chat page
// loads styles.css alone and the feed page feed.css alone — so its dress is declared in BOTH sheets
// (the .romp-acted / filebrowse precedent). The copies had already drifted once (feed.css lacked the
// a.fileview-btn anchor rules, so the GitHub link rendered hrefless-underlined there, 2026-08-26).
// This pins the shared chrome byte-equal so it cannot drift again. Rules that are deliberately
// pane-specific (wrap mode, load cue, the md body's typography where the feed sheet carries a
// fallback) are not pinned. The md body's own rule IS: its `contain: layout` is what keeps a
// file's fixed-positioned element inside the note, and it has to hold in both documents, as do
// the width caps on the media a file draws itself (svg, canvas, video), which under containment
// would otherwise be clipped and unreachable, and the table rule that gives a wide table a
// horizontal scroll of its own for the same reason.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const read = (f: string) => fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", f), "utf8");
const CHAT = read("styles.css");
const FEED = read("feed.css");

const RULES = [
  "#romp-fileview {", ".fileview {", "body.fileview-open {", ".fileview-bar {", ".fileview-name {",
  ".fileview-dir {", ".fileview-base {", ".fileview-sess {", ".fileview-sess .host-prefix {", ".fileview-acts {",
  ".fileview-bar .fileview-name {", ".fileview-bar .fileview-acts {",   // the bar's own wrap (scoped: the file browser's row wears .fileview-acts too)
  ".fileview-btn {", ".fileview-btn:hover {",
  "a.fileview-btn {", ".fileview-gh {", ".fileview-gh-why {", ".fileview-gh-dots {",
  // one disabled dress for every bar button: the GitHub unit's no-link state and the text-size control's ends
  '.fileview-btn:disabled, .fileview-btn[aria-disabled="true"] {', '.fileview-btn:disabled:hover, .fileview-btn[aria-disabled="true"]:hover {',
  '.fileview-btn:disabled:active, .fileview-btn[aria-disabled="true"]:active {', ".fileview-size-reset {", ".fileview-size-reset.fileview-size-default {",
  "a.fileview-gh-note {", ".fileview-body {", ".fileview-md {",
  ":where(.fileview-md) svg, :where(.fileview-md) canvas, :where(.fileview-md) video {",
  ':where(.fileview-md :is(svg, canvas)[width]:not([width$="%"])) {',
  ".fileview-md table {",
  ".fileview-cm {", ".fileview-cm .cm-editor {", ".fileview-editor {", ".fileview > .fileview-err {",
  ".fileview-dir-link {", ".fileview-dir-link:hover {",
  ".fileview-imgbox {", ".fileview-img {", ".fileview-frame {",
];

function ruleOf(css: string, head: string): string {
  const at = css.indexOf(head);
  assert.ok(at >= 0, head + " present");
  return css.slice(at, css.indexOf("}", at) + 1);
}

test("the viewer's shared chrome exists in BOTH sheets, byte-equal", () => {
  for (const head of RULES) {
    assert.equal(ruleOf(CHAT, head), ruleOf(FEED, head), head + " mirrors exactly");
  }
});
