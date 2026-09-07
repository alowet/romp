// T241 (the user 2026-09-07): highlighting text INSIDE a comment thread's popover seeded a quote chip on the
// MAIN composer's chip box. transcriptSelection() qualified any selection whose endpoints resolve via
// closest(".turn") — and the popover's message rows are the chat renderer's own .turn elements — so a
// thread highlight read as a transcript highlight and the document's selectionchange listener seeded the
// active session's chips. A selection inside #cmt-pop now qualifies as NOTHING for the main composer; the
// thread-side quote (seeding the thread's own reply box) is a separate follow-up — the popover's composer
// has no chip grammar yet, and a per-gesture blockquote insert would be destructive.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");

// ── executed: transcriptSelection() over a minimal DOM shim (no jsdom dependency) ──────────────────────────
type Shim = { cls: string; id?: string; parent: Shim | null; attrs: Record<string, string> };
function shimTree(): { transcriptTurn: Shim; popTurn: Shim; composer: Shim } {
  const body: Shim = { cls: "", parent: null, attrs: {} };
  const chat: Shim = { cls: "chat", parent: body, attrs: {} };
  const transcriptTurn: Shim = { cls: "turn user", parent: chat, attrs: { "data-uuid": "u-1" } };
  const pop: Shim = { cls: "cmt-pop", id: "cmt-pop", parent: body, attrs: {} };
  const msgs: Shim = { cls: "cmt-msgs", parent: pop, attrs: {} };
  const popTurn: Shim = { cls: "turn assistant", parent: msgs, attrs: { "data-uuid": "ca-1" } };
  const composer: Shim = { cls: "composer", parent: body, attrs: {} };
  return { transcriptTurn, popTurn, composer };
}
function run(startEl: Shim, endEl: Shim, text: string): { text: string; uuid: string | null } | null {
  const src = ("function transcriptSelection() {" + RENDER.split("function transcriptSelection(): { text: string; uuid: string | null } | null {")[1].split("\n}")[0] + "\n}")
    .replace(/\(n: Node \| null\)/g, "(n)");   // the one TypeScript annotation in the body — plain JS for new Function
  const prelude = `
    class Element {
      constructor(s) { Object.assign(this, s); this.parentElement = s.parent ? new Element(s.parent) : null; }
      matches(sel) {
        if (sel.startsWith("#")) return this.id === sel.slice(1);
        if (sel.startsWith(".")) return (" " + this.cls + " ").includes(" " + sel.slice(1) + " ");
        return false;
      }
      closest(sel) { let n = this; while (n) { if (n.matches(sel)) return n; n = n.parentElement; } return null; }
      getAttribute(k) { return this.attrs[k] ?? null; }
    }
    const textNode = (el) => ({ parentElement: new Element(el) });   // a Text node inside the element
    const range = { collapsed: false, startContainer: textNode(START), endContainer: textNode(END), toString: () => TEXT };
    const window = { getSelection: () => ({ rangeCount: 1, getRangeAt: () => range }) };`;
  return new Function("START", "END", "TEXT", prelude + "\n" + src + "\nreturn transcriptSelection();")(startEl, endEl, text);
}

test("a selection inside the comment popover qualifies as NOTHING for the main composer (T241)", () => {
  const { popTurn } = shimTree();
  assert.equal(run(popTurn, popTurn, "Jitter prevents thundering herds."), null,
    "the thread's rows are .turn elements too — they must never seed the main chip box");
});

test("a transcript selection still qualifies exactly as before", () => {
  const { transcriptTurn } = shimTree();
  assert.deepEqual(run(transcriptTurn, transcriptTurn, "Use exponential backoff."), { text: "Use exponential backoff.", uuid: "u-1" });
});

test("mixed endpoints (transcript ↔ popover, or into the composer) never qualify", () => {
  const { transcriptTurn, popTurn, composer } = shimTree();
  assert.equal(run(transcriptTurn, popTurn, "across"), null);
  assert.equal(run(transcriptTurn, composer, "into the composer"), null);
});

test("the exclusion is stated at the qualifier, where the Enter-to-reply shortcut shares it", () => {
  const q = RENDER.split("function transcriptSelection(): { text: string; uuid: string | null } | null {")[1].split("\n}")[0];
  assert.match(q, /closest\?\.\("#cmt-pop"\)|closest\("#cmt-pop"\)/, "a turn inside #cmt-pop is the thread's, not the transcript's");
});
