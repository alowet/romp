// Paste-to-focus (the user 2026-09-05): dictation tools land the whole utterance at once — a paste,
// not keystrokes — so type-to-focus (composer-citation.test.ts, "SELECT → TYPE → ⌘⏎") never fired,
// and after selecting transcript text nothing editable was focused: the dictated text went nowhere.
// Focusing the box when the selection ends was ruled out (it collapses the page selection and breaks
// plain copy). Instead a window-level, bubble-phase paste listener — the SAME gates as type-to-focus,
// through one shared helper — takes a paste nobody claimed, focuses the box, inserts the text at the
// caret and fires the input event the composer's bookkeeping listens for. A paste has already
// dispatched at the body by the time it bubbles to window, so unlike the keystroke (whose native
// insertion follows focus) this one must preventDefault and insert itself. No jsdom for this
// renderer, so the wiring is pinned at source (the repo convention); the insertion helper is a pure
// module and is exercised directly below.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { insertAtCaret, type CaretBox } from "./composer-insert";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");

const TYPE_MARK = "// SELECT → TYPE → ⌘⏎";
const PASTE_MARK = "// SELECT → PASTE → ⌘⏎";

// the paste handler's code: from its registration to the top-level close of its arrow function
function pasteHandler(): { at: number; block: string; tail: string } {
  const mark = RENDER.indexOf(PASTE_MARK);
  assert.ok(mark > 0, "the paste-to-focus handler exists");
  const at = RENDER.indexOf('window.addEventListener("paste"', mark);
  assert.ok(at > mark, "the handler follows its design note");
  const close = RENDER.indexOf("\n}", at);   // the body is indented, so the first column-0 brace closes the handler
  return { at, block: RENDER.slice(at, close), tail: RENDER.slice(close, close + 5) };
}
function gates(): string {
  return RENDER.split("function typeFromAnywhereTarget(")[1].split("\n}")[0];
}

test("the paste listener is window-level, bubble phase, installed once, beside type-to-focus", () => {
  const { at, tail } = pasteHandler();
  assert.equal(RENDER.match(/window\.addEventListener\("paste"/g)?.length, 1, "one window paste listener");
  assert.equal(tail, "\n});\n", "no capture flag: bubble phase, so every element handler has already spoken");
  assert.match(RENDER.slice(at), /^window\.addEventListener\("paste", \(e\) => \{\n/, "a plain listener on window, no options bag");
  // it sits right after the type-to-focus handler — one keydown registration between the two notes
  const typeAt = RENDER.indexOf(TYPE_MARK);
  const pasteAt = RENDER.indexOf(PASTE_MARK);
  assert.ok(typeAt > 0 && pasteAt > typeAt, "paste-to-focus follows type-to-focus");
  const between = RENDER.slice(typeAt, pasteAt);
  assert.equal(between.match(/window\.addEventListener\(/g)?.length, 1);
  assert.match(between, /window\.addEventListener\("keydown"/);
});

test("both defaults run ONE gate list — typeFromAnywhereTarget — never a duplicated copy", () => {
  assert.equal(RENDER.match(/function typeFromAnywhereTarget\(/g)?.length, 1, "the helper is defined once");
  assert.match(RENDER, /function typeFromAnywhereTarget\(e: Event\): HTMLTextAreaElement \| null \{/);
  const { block } = pasteHandler();
  assert.match(block, /const ta = typeFromAnywhereTarget\(e\);\s*\n\s*if \(!ta\) return;/);
  // the keystroke handler goes through the very same call
  const typeAt = RENDER.indexOf(TYPE_MARK);
  const keydown = RENDER.slice(RENDER.indexOf('window.addEventListener("keydown"', typeAt), RENDER.indexOf("\n}", typeAt));
  assert.match(keydown, /const ta = typeFromAnywhereTarget\(e\);\s*\n\s*if \(!ta\) return;/);
  // and neither re-implements a gate inline
  const inline = /isTypingTarget|picker-overlay|romp-fileview|romp-filebrowse|romp-lightbox|rsettings|ra-back|rkeys-back|meta-menu|liveAsks|ctxMenuEl|composerNoteHolds|ta\.disabled/;
  assert.doesNotMatch(block, inline, "the paste handler carries no gate of its own");
  assert.doesNotMatch(keydown, inline, "the keydown handler carries no gate of its own");
});

test("it stands down when the box is focused, a typing target is active, or any surface owns the input", () => {
  const { block } = pasteHandler();
  assert.match(block, /^window\.addEventListener\("paste", \(e\) => \{\s*\n\s*if \(e\.defaultPrevented\) return;/, "an element handler that already acted wins");
  const g = gates();
  // the box itself: missing, read-only, or ALREADY focused — a paste into the focused box is native,
  // and the composer's own paste handler (files, path-shaped text) keeps its default
  assert.match(g, /if \(!ta \|\| ta\.disabled \|\| document\.activeElement === ta\) return null;/);
  assert.match(RENDER, /ta\.addEventListener\("paste", \(e\) => \{\s*\n\s*const files = Array\.from\(e\.clipboardData\?\.files \|\| \[\]\);/, "the composer's own paste handler is untouched");
  // a typing target (input, textarea, contenteditable, SELECT) keeps its paste
  assert.match(g, /if \(isTypingTarget\(e\.target\) \|\| isTypingTarget\(document\.activeElement\)\) return null;/);
  assert.match(RENDER, /elm\.tagName === "TEXTAREA" \|\| elm\.tagName === "INPUT" \|\| elm\.tagName === "SELECT" \|\| elm\.isContentEditable === true/);
  // the live-ask card, an open context menu / #picker / #confirm, the full-pane surfaces, the pane's
  // modals + meta menus, and the T236 hand-over note — each one a gate the keystroke already had
  assert.match(g, /if \(activeId && liveAsks\.has\(activeId\)\) return null;/);
  assert.match(g, /if \(ctxMenuEl \|\| document\.querySelector\("\.picker-overlay"\)\) return null;/);
  assert.match(g, /document\.getElementById\("romp-fileview"\) \|\| document\.getElementById\("romp-filebrowse"\)\s*\n\s*\|\| document\.getElementById\("romp-lightbox"\)\) return null;/);
  assert.match(g, /document\.querySelector\("#rsettings:not\(\[hidden\]\), #ra-back:not\(\[hidden\]\), #rkeys-back, \.meta-menu"\)\) return null;/);
  assert.match(g, /if \(composerNoteHolds\(\)\) return null;/);
  assert.match(g, /return ta;\s*$/, "the box comes back only once every gate has passed");
});

test("a plain-text paste is claimed: preventDefault, focus without scrolling, insert at the caret, input event", () => {
  const { block } = pasteHandler();
  assert.match(block, /const dt = e\.clipboardData;/);
  assert.match(block, /const text = dt\.getData\("text\/plain"\);\s*\n\s*if \(!text\) return;/, "an empty paste changes nothing");
  // the order matters: cancel the native (body-targeted) paste, focus, then insert through the one helper
  assert.match(block, /e\.preventDefault\(\);\s*\n\s*ta\.focus\(\{ preventScroll: true \}\);\s*\n\s*insertAtCaret\(ta, text\);/);
  assert.match(RENDER, /import \{ insertAtCaret \} from "\.\/composer-insert";/);
  assert.doesNotMatch(block, /ta\.value\s*=|setRangeText|dispatchEvent/, "the insertion is the helper's, not a second copy");
});

test("the armed quote chip is never touched — it stages on ⌘⏎ exactly as after typing", () => {
  // the focus collapses the page selection, and a collapse never clears the chip (the selectionchange
  // pins in composer-citation.test.ts) — so this handler has no business with the citation state
  const { block } = pasteHandler();
  assert.doesNotMatch(block, /composerCitations|removeCitation|renderComposerChips|seedTranscriptQuote|clearEditorCitation|dropCitation|transcriptSelection/);
  assert.doesNotMatch(block, /getSelection|removeAllRanges/, "the page selection is left to the focus call alone");
});

test("a clipboard carrying files stands down, on purpose and said so", () => {
  const { block } = pasteHandler();
  // the composer attaches files inline in its OWN paste handler (per-file: local path vs shipped bytes
  // by host), not through a callable this branch could reuse — so a file paste from the bare area is
  // left exactly as it was, rather than half-handled (a focus with nothing attached)
  assert.match(block, /if \(!dt \|\| dt\.files\.length\) return;/);
  assert.doesNotMatch(block, /shipFileToHost|addComposerFile/);
  assert.match(block, /stay out of scope here/);
});

// ── insertAtCaret, the pure helper ────────────────────────────────────────────────────────────────
// A fake box with the platform's setRangeText("end") semantics: replace [start, end) and park the
// caret after the inserted text.
class FakeBox implements CaretBox {
  value: string;
  selectionStart: number;
  selectionEnd: number;
  calls: Array<[string, number, number, string | undefined]> = [];
  events: Event[] = [];
  constructor(value: string, start: number, end = start) { this.value = value; this.selectionStart = start; this.selectionEnd = end; }
  setRangeText(replacement: string, start: number, end: number, mode?: "select" | "start" | "end" | "preserve"): void {
    this.calls.push([replacement, start, end, mode]);
    this.value = this.value.slice(0, start) + replacement + this.value.slice(end);
    if (mode === "end") this.selectionStart = this.selectionEnd = start + replacement.length;
  }
  dispatchEvent(event: Event): boolean { this.events.push(event); return true; }
}

test("insertAtCaret puts the text at the caret and leaves the caret after it", () => {
  const box = new FakeBox("hello world", 5);
  insertAtCaret(box, ", dictated");
  assert.equal(box.value, "hello, dictated world");
  assert.equal(box.selectionStart, 15);
  assert.equal(box.selectionEnd, 15);
  assert.deepEqual(box.calls, [[", dictated", 5, 5, "end"]]);
});

test("insertAtCaret replaces the box's own selection, the way a native paste does", () => {
  const box = new FakeBox("fix the typo", 4, 7);   // "the" selected
  insertAtCaret(box, "every");
  assert.equal(box.value, "fix every typo");
  assert.equal(box.selectionStart, 9);
  assert.equal(box.selectionEnd, 9);
});

test("insertAtCaret fires ONE bubbling input event, after the text is in place", () => {
  const box = new FakeBox("", 0);
  let seenAtDispatch: string | null = null;
  box.dispatchEvent = (ev: Event) => { box.events.push(ev); seenAtDispatch = box.value; return true; };
  insertAtCaret(box, "note to self");
  assert.equal(box.events.length, 1);
  assert.equal(box.events[0].type, "input");
  assert.equal(box.events[0].bubbles, true);
  assert.equal(seenAtDispatch, "note to self", "the composer's input listener reads the inserted text");
});
