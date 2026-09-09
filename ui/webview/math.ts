// TeX math for chat markdown: inline \( .. \) and $ .. $, display \[ .. \] and $$ .. $$
// (the user 2026-08-03). marked has no math syntax, so without this every formula an agent
// writes reaches the transcript as raw TeX source.
//
// Rendering happens AFTER the sanitizer, not inside marked. KaTeX carries every piece of vertical
// layout in inline `style` (a strut's height and vertical-align, a vlist row's top, a fraction line's
// border width, a radical's padding), and the shared sanitizer (md-sanitize.ts) keeps only colour
// declarations in a `style` attribute, so KaTeX's output passed through sanitizeMd would come back
// flat: numerator and denominator on one line, a superscript at the baseline. The extensions therefore
// emit an INERT placeholder (class md-math-inline or md-math-display, a span inside a paragraph or a
// div for a display paragraph of its own, the TeX as its text, HTML-escaped) that the sanitizer treats
// as any element with text, and renderMathPlaceholders below renders KaTeX into each placeholder on
// the sanitized DOM, so its styles never meet DOMPurify. Nothing an author writes gains by hand-writing
// the placeholder markup: KaTeX renders only what TeX says, under `trust: false` (no \href, \url,
// \includegraphics, \htmlClass, \htmlStyle, \htmlData), which is KaTeX's own safety model. KaTeX
// renders with output: "html" ONLY, no MathML twin. The KaTeX layout CSS ships via styles.css
// (@import "katex/dist/katex.min.css"; fonts emitted to dist/fonts/ by esbuild). chat-md.ts registers
// the post-pass with the sanitizer (md-sanitize.ts registerMdPostPass), so every sanitizeMd call in the
// chat bundle renders math, the file viewer's mdBlock included when it runs in the chat page; a bundle
// without the grammar (feed.js) has neither the placeholders nor KaTeX.
//
// The delimiter problem: `$` is everywhere in chat text that is NOT math (shell variables,
// prices), and a naive $..$ tokenizer strikes a formula through half a sentence the way the
// single-tilde del rule once did (render.ts). Code spans and fences are already safe: marked
// consumes them whole when the inline walker reaches the backtick, and a backtick never
// enters math content (rule below), so a candidate can never pair up across a code-span
// boundary either. The rules that disarm bare prose, for inline $ .. $ only:
//   - the opener $ must touch its content: "$x", "$5", never "$ x"
//   - content stays on one line and contains no $ and no backtick
//   - the closer $ must touch its content AND be followed by end-of-text, whitespace, or
//     closing punctuation. This is the rule that spares shell and price prose: "$HOME/$USER"
//     (closer followed by "U"), "$FOO,$BAR" (followed by "B"), "$5-$10" (followed by "1")
//     all stay literal, while "$x$-axis" and "**$O(n)$**" still render ("-", "*" are in
//     the set).
// \( \) / \[ \] / $$ $$ carry no real ambiguity and pass through with only a non-blank
// content check. Escaped \$ needs nothing: the walker meets the backslash first and marked's
// escape tokenizer consumes both characters before any math rule sees the $.
import katex from "katex";
import type { TokenizerAndRendererExtension, Tokens } from "marked";

type MathToken = Tokens.Generic & { text: string; display: boolean };

/** The placeholder classes: inline math, and display math (KaTeX's displayMode). The class is the whole
 *  contract between the extensions and renderMathPlaceholders; the tag (span in a paragraph, div for a
 *  display paragraph of its own) only keeps an unrendered placeholder in the flow it came from. */
export const MATH_INLINE_CLASS = "md-math-inline";
export const MATH_DISPLAY_CLASS = "md-math-display";

// Closing punctuation allowed right after the closing $ (plus whitespace / end-of-text).
// Includes markdown emphasis/strike markers so **$O(n)$** works, and the common CJK stops.
const AFTER_CLOSE = "[\\s.,;:!?)\\]}\"'*_~\\-、。，；：！？）】」]";

const INLINE_PAREN = /^\\\(([\s\S]+?)\\\)/;                 // \( .. \)   inline
const INLINE_BRACKET = /^\\\[([\s\S]+?)\\\]/;               // \[ .. \]   display
const INLINE_DOLLARS = /^\$\$([\s\S]+?)\$\$/;               // $$ .. $$   display
const INLINE_DOLLAR = new RegExp(
  "^\\$(?![\\s$])([^$\\n`]*?[^\\s$\\n`])\\$(?=" + AFTER_CLOSE + "|$)",
);

// Block-level display math: a $$ .. $$ or \[ .. \] paragraph of its own, so multi-line
// formulas never reach markdown's block rules (a "- " or "#" line inside a formula would
// otherwise be carved into a list or heading before the inline pass could see it).
const BLOCK_DOLLARS = /^ {0,3}\$\$([\s\S]+?)\$\$ *(?:\n+|$)/;
const BLOCK_BRACKET = /^ {0,3}\\\[([\s\S]+?)\\\] *(?:\n+|$)/;

function escapeText(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** The placeholder marked emits for a formula: the TeX as escaped text under the class that names the
 *  mode. `block` picks the tag, a div for a display paragraph of its own, a span inside a paragraph. */
export function mathPlaceholder(tex: string, display: boolean, block: boolean): string {
  const cls = display ? MATH_DISPLAY_CLASS : MATH_INLINE_CLASS;
  const tag = block ? "div" : "span";
  return `<${tag} class="${cls}">${escapeText(tex)}</${tag}>`;
}

export const mathBlock: TokenizerAndRendererExtension = {
  name: "mathBlock",
  level: "block",
  start(src: string) {
    const m = src.match(/(?:^|\n) {0,3}(?:\$\$|\\\[)/);
    return m ? m.index : undefined;
  },
  tokenizer(src: string) {
    const m = BLOCK_DOLLARS.exec(src) || BLOCK_BRACKET.exec(src);
    if (!m || !m[1].trim()) return undefined;
    return { type: "mathBlock", raw: m[0], text: m[1].trim(), display: true } as MathToken;
  },
  renderer(token) {
    return mathPlaceholder((token as MathToken).text, true, true);
  },
};

export const mathInline: TokenizerAndRendererExtension = {
  name: "mathInline",
  level: "inline",
  start(src: string) {
    const m = src.match(/\$|\\\(|\\\[/);
    return m ? m.index : undefined;
  },
  tokenizer(src: string) {
    let m: RegExpExecArray | null; let display = false;
    if ((m = INLINE_PAREN.exec(src))) display = false;
    else if ((m = INLINE_BRACKET.exec(src)) || (m = INLINE_DOLLARS.exec(src))) display = true;
    else m = INLINE_DOLLAR.exec(src);
    if (!m || !m[1].trim()) return undefined;
    return { type: "mathInline", raw: m[0], text: m[1].trim(), display } as MathToken;
  },
  renderer(token) {
    const t = token as MathToken;
    return mathPlaceholder(t.text, t.display, false);
  },
};

/** The belt under the fill: the TeX as text in a code element where the placeholder stood, so a formula
 *  can never blank a message and the reader still sees what was written. A block placeholder (the div a
 *  display paragraph of its own becomes) turns into a code block; a span, display mode or not, into a code
 *  span, so the paragraph it sits in survives the serialization to innerHTML (a <pre> inside a <p> splits
 *  the paragraph when the HTML is parsed again). */
function showSource(el: HTMLElement, tex: string): void {
  const doc = el.ownerDocument;
  const code = doc.createElement("code");
  code.textContent = tex;
  if (el.tagName === "DIV") { const pre = doc.createElement("pre"); pre.appendChild(code); el.replaceWith(pre); }
  else el.replaceWith(code);
}

/** Render KaTeX into every math placeholder under `root`, the SANITIZED DOM (sanitizeMd's body), and
 *  unwrap each so the rendered `.katex` (or `.katex-display`) root stands where the placeholder stood,
 *  exactly where marked's own KaTeX output used to. The selector reaches a placeholder an author typed by
 *  hand as well (no class name is special-cased): it renders under the same options, so it gains nothing.
 *  throwOnError: false paints bad TeX as KaTeX's flagged source instead of throwing; the catch is a belt for
 *  the residual throws (an internal error), showing the TeX as text (showSource) with a word on the console
 *  once per call, so a formula can never blank a message. A second run over the same root is a no-op: no
 *  placeholder survives the first. Plain and exported: chat-md.ts registers it as sanitizeMd's post-pass,
 *  and the tests call it directly. */
export function renderMathPlaceholders(root: ParentNode): void {
  let reported = false;      // the belt's console report, once per call
  root.querySelectorAll("." + MATH_INLINE_CLASS + ", ." + MATH_DISPLAY_CLASS).forEach((node) => {
    const el = node as HTMLElement;
    const display = el.classList.contains(MATH_DISPLAY_CLASS);
    const tex = el.textContent || "";
    if (!tex.trim()) { el.replaceWith(...Array.from(el.childNodes)); return; }
    try {
      // trust: false is KaTeX's own default, spelled out so that enabling trust is a visible edit (render-math.test.ts
      // pins the option): under it no TeX command mints a link, an image or an HTML attribute of the author's choosing
      katex.render(tex, el, { displayMode: display, throwOnError: false, output: "html", trust: false });
      el.replaceWith(...Array.from(el.childNodes));
    } catch (e) {
      if (!reported) { reported = true; console.error("math: KaTeX could not lay out a formula; its source is shown instead", e); }
      showSource(el, tex);
    }
  });
}
