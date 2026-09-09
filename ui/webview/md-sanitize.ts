// ONE sanitizer for every piece of markdown the dashboard renders as HTML: the chat's md() and userMd()
// (render.ts) and the file viewer's mdBlock (file-view.ts). The two used to spell the same DOMPurify
// profile in two places, and that profile was DOMPurify's default html list, which keeps <style>, <form>,
// <button>, <dialog>, inline `style`, `id`, `name` and the `background` attribute. A markdown file is
// arbitrary bytes off a disk and a chat message is untrusted text, so the rules their HTML lives under sit
// here, once, and both call sanitizeMd.
//
// What a note's or a message's HTML may do, modelled on GitHub's rules for a README (GitHub strips an inline
// `style` whole and allows no inline SVG; both survive here in the narrowed form described below):
//   • no <style> block, no <dialog>, and no form-associated element: a <style> blanked the whole viewer
//     (`.fileview { display: none }`), and a `<form action=...><button>` navigated the pane's document to
//     the action URL. style's text goes with it (DOMPurify's default FORBID_CONTENTS); a form's or a
//     button's TEXT stays as prose (KEEP_CONTENT), so a note reads the same minus the control.
//   • <input> survives ONLY as marked's task-list checkbox, `- [x] done` becomes <input checked disabled
//     type=checkbox>: every other input goes, and a checkbox that lacks `disabled` gets it, so nothing in
//     a note is a live control.
//   • an author's id and name are PREFIXED `user-content-` (SANITIZE_NAMED_PROPS, the rule GitHub applies):
//     a `<p id="tabs">` can no longer dress itself in the page's #tabs CSS or shadow getElementById for the
//     page's own controls, and `<a name="install">` still exists under its prefixed name. An `href="#install"`
//     is NOT rewritten to match: the chat's click delegate (render.ts) resolves a message's `#` click through
//     userContentTarget below, since the browser's default lookup reads the bare name and finds nothing.
//     Rewriting hrefs here would break the viewer's section links: its heading ids (`md-<slug>`, minted by
//     mdBlock AFTER the sanitize) never gain the prefix, so a rewritten `#user-content-results` would name
//     nothing.
//   • an inline `style` keeps only `color` and `background-color` declarations whose value is a literal
//     colour: coloured spans in existing notes and transcripts survive; positioning, sizing and layout never
//     reach the page. Everything else in the attribute is dropped, and the attribute goes when nothing is
//     left: colorOnlyStyle below is the whole grammar, applied by a DOMPurify uponSanitizeAttribute hook on
//     every element, inline SVG included.
//   • data-* never rides in (ALLOW_DATA_ATTR: false): both pages key their delegated actions off data-act.
//   • the `background` attribute is forbidden outright (FORBID_ATTR): `<td background=URL>` makes the browser
//     fetch the URL the moment the note renders, a tracking pixel with no click and no gate; DOMPurify's html
//     list keeps it, GitHub's allowlist does not, and it has no safe value here. `bgcolor` fetches nothing and
//     stays, as a colour-only inline style does.
//   • no image map: `<map>`, `<area>` and `usemap` go (FORBID_TAGS, FORBID_ATTR), as GitHub drops them. The
//     prefix rule renames `<map name="nav">` to user-content-nav and leaves `usemap="#nav"` as written, so no
//     map an author writes could bind to its picture anyway, and an <area> is a link element neither page's
//     link handling reaches. Dropped, the picture is inert prose.
//   • html + svg profiles (KaTeX's stretchy glyphs used to come through here as inline <svg>; a note's own
//     inline SVG still does), data: URIs on <img> (the CSP allows them; inline transcript images rely on them).
//
// What does NOT pass through here: KaTeX. Its layout is all inline style, which the colour-only rule would
// strip, so the math extensions emit an inert placeholder and KaTeX is rendered into it on the sanitized
// DOM afterwards (math.ts renderMathPlaceholders), as a POST-PASS this module runs at the end of sanitizeMd
// for every caller: the module that installs the math grammar (chat-md.ts) registers the fill at load
// (registerMdPostPass), so the chat's md() and userMd(), and the viewer's mdBlock when it runs inside the
// chat page whose marked singleton carries that grammar, all render math, and a bundle without the grammar
// (feed.js) never sees the pass or KaTeX. A renderer romp itself runs never goes through the sanitizer;
// only what an author wrote does.
import DOMPurify from "dompurify";
import type { Config, DOMPurify as DOMPurifyInstance, UponSanitizeAttributeHookEvent } from "dompurify";

/** Tags a note may not keep: the style sheet, the dialog, every form-associated element, and the image map. */
export const MD_FORBID_TAGS: readonly string[] = [
  "style", "dialog",
  "form", "button", "select", "option", "optgroup", "textarea", "fieldset", "legend", "label", "datalist", "output", "meter", "progress",
  "map", "area",
];

/** Attributes a note may not keep at all: `background`, a remote fetch on render with no safe value, and `usemap`, the
 *  image map's binding (the map itself is forbidden above). Every other attribute the profiles allow either is safe as
 *  written or is rewritten (id and name prefixed, style filtered). */
export const MD_FORBID_ATTR: readonly string[] = ["background", "usemap"];

/** The prefix SANITIZE_NAMED_PROPS puts on an author's id and name (DOMPurify's own constant is not exported). A
 *  `#fragment` clicked in a chat message is looked up under it (userContentTarget below); the viewer's minted `md-`
 *  heading ids are set after the sanitize and never carry it. */
export const USER_CONTENT_PREFIX = "user-content-";

/** The element an author's `#id` names in `root` after the sanitize: the first whose `id` is the prefixed spelling or
 *  the bare one, else the first `<a name>` with either, in document order (the browser's own fragment rule, applied to
 *  both spellings). The bare arm serves ids the sanitizer never saw: the page's own ids when `root` is the document
 *  (what the browser's default would have scrolled to), and an author who typed the prefix. Nothing when neither is
 *  found. The chat's click delegate (render.ts) reads it as is, the message's body first and then the document. */
export function userContentTarget(root: ParentNode, id: string): Element | undefined {
  const own = USER_CONTENT_PREFIX + id;
  return Array.from(root.querySelectorAll("[id]")).find((e) => { const v = e.getAttribute("id"); return v === own || v === id; })
    || Array.from(root.querySelectorAll("a[name]")).find((e) => { const v = e.getAttribute("name"); return v === own || v === id; });
}

/** The one profile. Spread `RETURN_DOM: true` onto it to take the sanitized <body> back (sanitizeMd does). */
export const MD_PURIFY: Config = {
  USE_PROFILES: { html: true, svg: true },
  ADD_DATA_URI_TAGS: ["img"],
  ALLOW_DATA_ATTR: false,
  FORBID_TAGS: [...MD_FORBID_TAGS],
  FORBID_ATTR: [...MD_FORBID_ATTR],
  SANITIZE_NAMED_PROPS: true,
};

// ── the colour grammar ──────────────────────────────────────────────────────────────────────────────
// A value is a literal colour when it is one of: a bare keyword (a named colour, `transparent`,
// `currentcolor`, a CSS-wide keyword such as `inherit` or `unset`; an unknown word is a declaration the
// browser ignores, never a function or a URL; a hyphenated word such as `revert-layer` fails the pattern),
// `#` and 3 to 8 hex digits, or rgb()/rgba()/hsl()/hsla() whose arguments are 3 or 4 plain numbers or
// percentages (an angle unit, deg/grad/rad/turn, is accepted on any argument by the one shared pattern,
// though only an hsl hue can carry one and the browser discards an rgb() written with one; `none` is CSS
// Color 4's missing component), separated by commas, spaces or a slash. Nothing else: no nested
// parentheses (so no url(, var(, expression(, calc(), no `!important`, no quotes, no backslash escapes,
// no comments.
const KEYWORD = /^[a-z]+$/i;
const HEX = /^#[0-9a-f]{3,8}$/i;
const COLOR_FN = /^(rgba?|hsla?)\(([^()]*)\)$/i;
const COLOR_ARG = /^(?:[+-]?(?:\d+\.?\d*|\.\d+)(?:%|deg|grad|rad|turn)?|none)$/i;
const KEPT_PROPERTIES = new Set(["color", "background-color"]);

/** Whether `v` (already trimmed) is a literal colour under the grammar above. */
export function isLiteralColor(v: string): boolean {
  if (KEYWORD.test(v) || HEX.test(v)) return true;
  const m = COLOR_FN.exec(v);
  if (!m) return false;
  const args = m[2].trim().split(/\s*[,/]\s*|\s+/).filter((a) => a.length > 0);
  return args.length >= 3 && args.length <= 4 && args.every((a) => COLOR_ARG.test(a));
}

/** The declarations of a `style` attribute that survive: `color` and `background-color` with a literal
 *  colour, in their order, as `name: value` joined by `; `. Empty when nothing survives (the caller drops
 *  the attribute). Splitting on `;` is safe because no surviving value can contain one. */
export function colorOnlyStyle(style: string): string {
  const kept: string[] = [];
  for (const decl of style.split(";")) {
    const at = decl.indexOf(":");
    if (at < 0) continue;
    const name = decl.slice(0, at).trim().toLowerCase();
    const value = decl.slice(at + 1).trim();
    if (!KEPT_PROPERTIES.has(name) || !value || !isLiteralColor(value)) continue;
    kept.push(name + ": " + value);
  }
  return kept.join("; ");
}

/** The DOMPurify uponSanitizeAttribute hook body: rewrites a `style` attribute to its colour
 *  declarations, drops it when none survive, and leaves every other attribute to DOMPurify. */
export function styleAttributeHook(ev: Pick<UponSanitizeAttributeHookEvent, "attrName" | "attrValue" | "keepAttr">): void {
  if (ev.attrName !== "style") return;
  const kept = colorOnlyStyle(ev.attrValue);
  if (kept) ev.attrValue = kept;
  else ev.keepAttr = false;
}

let hooksInstalled = false;
/** Install the style hook on the (module-global) DOMPurify instance, once. Idempotent: DOMPurify's hooks
 *  are a list, and a second registration would run the same rewrite twice per attribute. `purify` is a
 *  seam for the node tests, which have no window for the real instance to sanitize in. */
export function installMdSanitizeHooks(purify: Pick<DOMPurifyInstance, "addHook"> = DOMPurify): void {
  if (hooksInstalled) return;
  hooksInstalled = true;
  purify.addHook("uponSanitizeAttribute", (_node, ev) => { styleAttributeHook(ev); });
}

/** marked's task checkbox is the one control a note keeps, inert: every other <input> goes, and a
 *  checkbox without `disabled` gets it. Runs on the sanitized DOM, after DOMPurify. */
function keepOnlyInertCheckboxes(root: ParentNode): void {
  root.querySelectorAll("input").forEach((node) => {
    const input = node as HTMLInputElement;
    if ((input.getAttribute("type") || "").toLowerCase() !== "checkbox") { input.remove(); return; }
    if (!input.hasAttribute("disabled")) input.setAttribute("disabled", "");
  });
}

const postPasses: Array<(root: ParentNode) => void> = [];
/** Register a DOM pass sanitizeMd runs on every sanitized body before handing it back. For the module that installs a
 *  marked extension whose output needs a render AFTER the sanitize (chat-md.ts: the math placeholders KaTeX fills,
 *  math.ts renderMathPlaceholders), registered at load: the grammar and its fill travel together, so every sanitizeMd
 *  caller in a bundle that parses with the grammar renders the same way (the chat's md() and userMd(); the viewer's
 *  mdBlock when it runs inside the chat page, whose marked singleton carries the extensions), and a bundle that never
 *  imports the module (feed.js) has neither the grammar nor the pass nor the library behind it. One mechanism, no
 *  per-caller call to forget. Idempotent: a pass registered twice runs once. */
export function registerMdPostPass(pass: (root: ParentNode) => void): void {
  if (!postPasses.includes(pass)) postPasses.push(pass);
}

/** Sanitize marked's HTML under the profile above and return the sanitized <body>: its children are the
 *  nodes to adopt (mdBlock) or its innerHTML the string to set (md, userMd), after any DOM post-pass of
 *  the caller's own (PR links, heading ids). The registered passes (the math fill) have run by then. The
 *  only DOMPurify.sanitize call in the dashboard's source. */
export function sanitizeMd(dirty: string): HTMLElement {
  installMdSanitizeHooks();
  const clean = DOMPurify.sanitize(dirty, { ...MD_PURIFY, RETURN_DOM: true }) as HTMLElement;   // the sanitized <body>
  keepOnlyInertCheckboxes(clean);
  for (const pass of postPasses) pass(clean);
  return clean;
}
