// The chat's markdown grammar, in ONE place, and the renderer for the user's OWN words.
//
// Two marked configurations render the chat, and they must agree on everything except line breaks:
//   - the shared `marked` singleton (render.ts, file-view.ts) — `breaks: false`: assistant output is real
//     markdown, where a single newline is a soft wrap and a paragraph break takes a blank line;
//   - `userMarked` below — `breaks: true`: what the user typed is not authored markdown. Shift+Enter in the
//     composer means "new line", and the bubble must show the line the person made (the user 2026-09-06:
//     a multi-line message ran together into one paragraph once it reached the chat). marked's `breaks`
//     option turns each newline inside a paragraph into <br> and touches nothing else — fenced code keeps
//     its literal newlines, lists stay lists, a blank line is still a paragraph break.
// Both take the SAME extensions from `chatMdExtensions`, so a user message with math or strikethrough
// renders exactly as it did before — only its newlines are kept. Pure (no DOM): the executed tests import
// it directly, the way render-math.test.ts exercises math.ts. Sanitizing is the caller's job: render.ts's
// userMd() runs the output through the same DOMPurify profile md() uses before it ever reaches innerHTML.
import { Marked, type MarkedExtension } from "marked";
import { mathBlock, mathInline } from "./math";

// Strikethrough requires DOUBLE tildes (the user 2026-06-26). marked's built-in GFM `del` tokenizer also
// fires on a SINGLE tilde, so prose like "near the ~21 Wh/day budget … gives ~1.5–2 days" renders as one big
// <del> struck through from the first ~ to the second. GitHub itself only strikes ~~double~~, so match that:
// a lone ~ (commonly "approximately") stays literal. Returning undefined lets marked treat the ~ as text.
export const delDoubleTilde = {
  tokenizer: {
    del(src: string) {
      const m = /^~~(?=\S)([\s\S]*?\S)~~/.exec(src);
      if (!m) return undefined;
      return { type: "del", raw: m[0], text: m[1], tokens: (this as { lexer: { inlineTokens(s: string): unknown[] } }).lexer.inlineTokens(m[1]) };
    },
  },
} as MarkedExtension;

// TeX math ($..$, $$..$$, \(..\), \[..\]) rendered via KaTeX. All delimiter heuristics (the
// $-vs-shell/price disambiguation) live in math.ts; the output is plain spans + inline styles
// (output: "html"), which DOMPurify's html profile in md() passes through unchanged.
export const chatMdExtensions: MarkedExtension[] = [delDoubleTilde, { extensions: [mathBlock, mathInline] }];

// The user-text instance: the chat grammar with hard line breaks. Its own `Marked` so the singleton's
// `breaks: false` — every assistant message — is untouched.
export const userMarked = new Marked({ gfm: true, breaks: true }, ...chatMdExtensions);

/** marked's HTML for the user's own typed text: newlines kept as <br>, otherwise the chat grammar.
 *  UNSANITIZED — render.ts's userMd() is the only caller that reaches innerHTML, and it purifies first. */
export function userMdHtml(src: string): string {
  return userMarked.parse(src) as string;
}
