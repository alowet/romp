// The chat's markdown pipeline in headless Chromium over the real modules: marked with the chat grammar (chat-md.ts,
// math.ts), then sanitizeMd (md-sanitize.ts), which runs renderMathPlaceholders as the post-pass chat-md.ts registers
// at load; userMd the same over the breaks:true instance. This is md() and userMd() as render.ts composes them,
// minus the PR-reference walk (render-math.test.ts and chat-md.test.ts pin render.ts to that order).
// What a source pin cannot see, and this leg measures:
//   • Math keeps its layout. KaTeX positions everything with inline style (a strut's height, a vlist row's top, a
//     radical's padding), and sanitizeMd keeps only colour in a `style` attribute, so KaTeX markup emitted by marked
//     and then sanitized would come back flat. The extensions emit an inert placeholder instead and KaTeX renders
//     into it after the sanitize: a fraction stacks, a superscript is raised, the radical has height, a display sum
//     stands at block level, and the rendered root is katex.render's own output byte for byte, so nothing of it
//     passed through DOMPurify. An author's own `style` beside the math still loses everything but its colour.
//   • A hand-written placeholder gets only what KaTeX renders under the fill's options: no link from \href, no image
//     (trust: false, KaTeX's own default, spelled out in math.ts and pinned by render-math.test.ts).
//   • An author's <style>, <form> and <button> in a message are gone, an author's id is prefixed, a checkbox written
//     by hand is forced disabled and a click leaves it unchecked.
//   • The registry: a pass registered twice runs once per sanitize; a second run of the fill is a no-op.
// Skips with a stated reason when no playwright browser is installed (CI installs none; tests/test_spend_modal_headless.py
// is the precedent, skipping without a playwright install). Synthetic values only.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { createRequire } from "node:module";

const EXT = process.cwd();                                        // npm test runs in vscode-extension
// resolve playwright and esbuild from the extension, not from wherever this bundle was written
const requireCjs = createRequire(path.join(EXT, "package.json"));
const UI = path.resolve(EXT, "..", "ui", "webview");
const KATEX_DIST = path.join(EXT, "node_modules", "katex", "dist");
const KATEX_CSS = fs.readFileSync(path.join(KATEX_DIST, "katex.min.css"), "utf8");

const ENTRY = `
import { marked } from "marked";
import katex from "katex";
import { chatMdExtensions, userMdHtml } from "./chat-md";
import { sanitizeMd, registerMdPostPass } from "./md-sanitize";
import { renderMathPlaceholders } from "./math";
marked.setOptions({ gfm: true, breaks: false });
marked.use(...chatMdExtensions);
function md(src: string): string { return sanitizeMd(marked.parse(src) as string).innerHTML; }
function userMd(src: string): string { return sanitizeMd(userMdHtml(src)).innerHTML; }
function markedOnly(src: string): string { return marked.parse(src) as string; }
// KaTeX's own output for the same TeX by the same DOM path (katex.render into a fresh element, the browser serializing),
// under the options the fill uses
function direct(tex: string, display: boolean): string {
  const el = document.createElement("div"); katex.render(tex, el, { displayMode: display, throwOnError: false, output: "html", trust: false }); return el.innerHTML;
}
function twice(src: string): { once: string; again: string } {
  const clean = sanitizeMd(marked.parse(src) as string); const once = clean.innerHTML;
  renderMathPlaceholders(clean); return { once, again: clean.innerHTML };
}
// the registry: a pass registered twice runs once per sanitize; a second pass runs too, after the fill
function registry(): { runs: number; other: number; sawKatex: boolean } {
  let runs = 0, other = 0, sawKatex = false;
  const counting = (root: ParentNode) => { runs++; sawKatex = sawKatex || root.querySelectorAll(".katex").length > 0; };
  const second = () => { other++; };
  registerMdPostPass(counting); registerMdPostPass(counting); registerMdPostPass(second);
  sanitizeMd(marked.parse("one $x$ formula") as string);
  return { runs, other, sawKatex };
}
(window as any).__pipe = { md, userMd, markedOnly, direct, twice, registry };
`;

function bundle(): string {
  const esbuild = requireCjs("esbuild");
  const r = esbuild.buildSync({
    stdin: { contents: ENTRY, resolveDir: UI, loader: "ts", sourcefile: "md-sanitize-postpass-entry.ts" },
    bundle: true, write: false, format: "iife", platform: "browser", target: "es2020",
    nodePaths: [path.join(EXT, "node_modules")], external: ["*.png", "*.svg", "*.woff", "*.ttf", "../media/*.woff2"], logLevel: "silent",
  });
  return r.outputFiles[0].text;
}

// a standards-mode page (KaTeX refuses quirks mode) with KaTeX's own sheet, its fonts served from the package
const PAGE_HTML = `<!DOCTYPE html><html><head><meta charset=utf-8><style>${KATEX_CSS}\nbody{font-size:16px}</style></head><body>
<div id=out></div>
<script src=/dist/postpass.js></script></body></html>`;

let pw: any = null;
try { pw = requireCjs("playwright"); } catch { pw = null; }

async function inBrowser(t: any, body: (page: any, errors: string[]) => Promise<void>): Promise<void> {
  if (!pw) { t.skip("playwright is not installed under vscode-extension; the browser leg needs it (CI installs no browsers)"); return; }
  let browser: any;
  try { browser = await pw.chromium.launch(); }
  catch (e) { t.skip("no playwright browser on this machine; the browser leg needs one (CI installs none): " + String((e as Error).message).split("\n")[0]); return; }
  const errors: string[] = [];
  try {
    const js = bundle();
    const page = await browser.newPage({ viewport: { width: 900, height: 600 } });
    page.on("pageerror", (e: Error) => { errors.push(e.message); });
    await page.route("http://romp.test/**", (route: any) => {
      const u = new URL(route.request().url());
      if (u.pathname === "/page") return route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: PAGE_HTML });
      if (u.pathname === "/dist/postpass.js") return route.fulfill({ status: 200, contentType: "application/javascript", body: js });
      if (u.pathname.startsWith("/fonts/")) {
        const f = path.join(KATEX_DIST, "fonts", path.basename(u.pathname));
        if (fs.existsSync(f)) return route.fulfill({ status: 200, contentType: "font/woff2", body: fs.readFileSync(f) });
      }
      return route.fulfill({ status: 404, body: "" });
    });
    await page.goto("http://romp.test/page");
    await page.waitForFunction(() => typeof (window as any).__pipe === "object", null, { timeout: 10000 });
    await page.evaluate(() => (document as any).fonts.ready);
    await body(page, errors);
  } finally {
    await browser.close();
  }
}

type Box = { top: number; bottom: number; height: number; width: number };

test("math keeps its KaTeX layout when rendered after the sanitizer, and is KaTeX's own output byte for byte; an author's style beside it keeps only its colour", { timeout: 60000 }, async (t) => {
  await inBrowser(t, async (page, errors) => {
    const MSG = [
      "The ratio is $\\frac{a}{b}$ and $x^2$ and $\\sqrt{d}$ and $a<b$ here.",
      "",
      "$$\\sum_{i=0}^{n} i^2$$",
      "",
      'A <span class="fx-red" style="color: rgb(200, 0, 0); position: fixed; top: 0; font-size: 80px">red</span> word.',
      "",
    ].join("\n");
    // 1. what reaches the sanitizer is the placeholder, not KaTeX: no style attribute for the colour rule to strip
    const before = await page.evaluate((src: string) => {
      const marked = (window as any).__pipe.markedOnly(src) as string;
      return { markedHasKatex: /class="katex/.test(marked), markedStyles: (marked.match(/ style="/g) || []).length,
        placeholders: (marked.match(/md-math-(inline|display)/g) || []).length };
    }, MSG);
    assert.equal(before.markedHasKatex, false, "marked emits placeholders, never KaTeX markup");
    assert.equal(before.markedStyles, 1, "the one inline style in marked's output is the author's span; the math placeholders carry none");
    assert.equal(before.placeholders, 5, "five placeholders (4 inline + 1 display)");

    // 2. the full pipeline: render, then measure
    const facts = await page.evaluate((src: string) => {
      const P = (window as any).__pipe;
      const out = document.getElementById("out") as HTMLElement;
      out.innerHTML = P.md(src);
      const box = (e: Element | null): Box | null => { if (!e) return null; const r = e.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, height: r.height, width: r.width }; };
      const katex = Array.from(out.querySelectorAll(".katex")) as HTMLElement[];
      const frac = out.querySelector(".mfrac") as HTMLElement | null;
      const fracGlyphs = frac ? Array.from(frac.querySelectorAll(".mord.mathnormal")) as HTMLElement[] : [];
      const fracA = fracGlyphs.find((g) => g.textContent === "a") || null;
      const fracB = fracGlyphs.find((g) => g.textContent === "b") || null;
      const sup = katex[1] || null;
      const supBase = sup ? sup.querySelector(".mord.mathnormal") : null;
      const supScript = sup ? sup.querySelector(".msupsub .mord") : null;
      const sqrt = katex[2] || null;
      const svg = sqrt ? sqrt.querySelector("svg") : null;
      const display = out.querySelector(".katex-display") as HTMLElement | null;
      const red = out.querySelector(".fx-red") as HTMLElement | null;
      const line = red ? red.parentElement as HTMLElement : null;
      return {
        placeholdersLeft: out.querySelectorAll(".md-math-inline, .md-math-display").length,
        katexCount: katex.length,
        katexStyled: out.querySelectorAll(".katex [style]").length,
        inlineParent: katex[0] ? katex[0].parentElement?.tagName : null,
        fracA: box(fracA), fracB: box(fracB),
        supBase: box(supBase), supScript: box(supScript),
        svg: box(svg),
        display: box(display), displayParentId: display ? display.parentElement?.id : null, displayInParagraph: display ? !!display.closest("p") : null,
        exactFrac: katex[0] ? katex[0].outerHTML === P.direct("\\frac{a}{b}", false) : false,
        exactDisplay: display ? display.outerHTML === P.direct("\\sum_{i=0}^{n} i^2", true) : false,
        redStyle: red ? red.getAttribute("style") : null,
        redPosition: red ? getComputedStyle(red).position : null,
        redFontSize: red ? getComputedStyle(red).fontSize : null,
        lineFontSize: line ? getComputedStyle(line).fontSize : null,
        ltEscaped: (out.textContent || "").includes("a<b"),
      };
    }, MSG);
    assert.equal(facts.placeholdersLeft, 0, "every placeholder was rendered and unwrapped");
    assert.equal(facts.katexCount, 5, "five formulas rendered");
    assert.ok(facts.katexStyled >= 10, "KaTeX's inline layout styles are all there: " + facts.katexStyled);
    assert.equal(facts.inlineParent, "P", "an inline formula's .katex root stands in the paragraph where the placeholder stood");
    assert.ok(facts.fracA && facts.fracB && facts.fracA.bottom <= facts.fracB.top + 1, "the fraction stacks: the numerator sits above the denominator: " + JSON.stringify([facts.fracA, facts.fracB]));
    assert.ok(facts.supBase && facts.supScript && facts.supScript.top < facts.supBase.top, "the superscript is raised above its base: " + JSON.stringify([facts.supBase, facts.supScript]));
    assert.ok(facts.svg && facts.svg.height > 5 && facts.svg.width > 5, "the radical's stretchy glyph has a box: " + JSON.stringify(facts.svg));
    assert.ok(facts.display && facts.display.height > 20, "the display sum is taller than a line: " + JSON.stringify(facts.display));
    assert.equal(facts.displayParentId, "out", "the display formula stands at block level, unwrapped");
    assert.equal(facts.displayInParagraph, false);
    assert.ok(facts.exactFrac, "the inline formula is katex.render's own output byte for byte: nothing of it passed through DOMPurify");
    assert.ok(facts.exactDisplay, "and so is the display one");
    assert.equal(facts.redStyle, "color: rgb(200, 0, 0)", "the author's span keeps only its colour declaration");
    assert.equal(facts.redPosition, "static");
    assert.equal(facts.redFontSize, facts.lineFontSize, "font-size: 80px was dropped");
    assert.ok(facts.ltEscaped, "a formula's `<` is text, never markup");
    assert.deepEqual(errors, [], "no page errors");
  });
});

test("a hand-written placeholder renders under the fill's options (no link from \\href), an empty one is unwrapped, and the user's own words take the same path", { timeout: 60000 }, async (t) => {
  await inBrowser(t, async (page, errors) => {
    const facts = await page.evaluate(() => {
      const P = (window as any).__pipe;
      const out = document.getElementById("out") as HTMLElement;
      out.innerHTML = P.md('hand <span class="md-math-inline">\\href{javascript:alert(1)}{x}</span> and <span class="md-math-inline"> </span> empty\n\n<div class="md-math-display">\\int_0^1 f</div>');
      const hand = { katex: out.querySelectorAll(".katex").length, anchors: out.querySelectorAll("a").length, hasJs: out.innerHTML.includes("javascript:"),
        placeholders: out.querySelectorAll(".md-math-inline, .md-math-display").length, display: out.querySelectorAll(".katex-display").length,
        text: out.textContent };
      out.innerHTML = P.userMd("Euler: $e^{i\\pi}+1=0$\nnext line");
      const user = { katex: out.querySelectorAll(".katex").length, br: out.querySelectorAll("br").length, placeholders: out.querySelectorAll(".md-math-inline").length };
      const t = P.twice("a $x^2$ b");
      return { hand, user, twiceSame: t.once === t.again, twiceKatex: (t.once.match(/class="katex"/g) || []).length };
    });
    assert.equal(facts.hand.katex, 2, "the two non-empty hand-written placeholders rendered (KaTeX flags the untrusted command in red)");
    assert.equal(facts.hand.anchors, 0, "\\href mints no link under the fill's options (trust: false, which is also KaTeX's default)");
    assert.equal(facts.hand.hasJs, false, "and the URL is nowhere in the markup");
    assert.equal(facts.hand.placeholders, 0, "no placeholder is left, the empty one included");
    assert.equal(facts.hand.display, 1, "the hand-written display placeholder renders in display mode");
    assert.ok((facts.hand.text || "").includes("empty"), "the empty placeholder's neighbours are intact");
    assert.equal(facts.user.katex, 1, "the user's own words render math through the same fill");
    assert.equal(facts.user.br, 1, "and keep their line break");
    assert.equal(facts.user.placeholders, 0);
    assert.ok(facts.twiceSame, "a second run of the fill over the same body is a no-op");
    assert.equal(facts.twiceKatex, 1);
    assert.deepEqual(errors, [], "no page errors");
  });
});

test("a message's own <style>, form and controls are gone, its ids are prefixed, and a hand-written checkbox is inert", { timeout: 60000 }, async (t) => {
  await inBrowser(t, async (page, errors) => {
    const facts = await page.evaluate(() => {
      const P = (window as any).__pipe;
      const out = document.getElementById("out") as HTMLElement;
      // the <style> comes AFTER a block: a document that OPENS with <style> has it hoisted into <head> by the HTML
      // parser, and DOMPurify hands back the <body>, so the case would pass with style allowed; here the sanitizer
      // is what removes it
      const src = [
        '<p id="top">top</p>',
        "",
        "<style>#out { display: none }</style>",
        "",
        '<form action="https://example.invalid/go"><button>Go</button></form>',
        "",
        "- [x] done",
        "",
        '<input type="checkbox" class="fx-hand"> <input type="text" class="fx-text">',
      ].join("\n");
      const dirty = P.markedOnly(src) as string;
      out.innerHTML = P.md(src);
      const hand = out.querySelector(".fx-hand") as HTMLInputElement | null;
      if (hand) hand.click();
      return {
        dirtyHasStyle: /<style>#out \{ display: none \}<\/style>/.test(dirty) && dirty.indexOf("<style>") > dirty.indexOf("<p id=\"top\">"),
        forbidden: out.querySelectorAll("style, form, button").length,
        outDisplay: getComputedStyle(out).display,
        goText: (out.textContent || "").includes("Go"),
        prefixed: out.querySelectorAll("p#user-content-top").length,
        raw: out.querySelectorAll("#top").length,
        task: out.querySelectorAll('li input[type="checkbox"][disabled]:checked').length,
        handDisabled: hand ? hand.disabled : null,
        handChecked: hand ? hand.checked : null,
        textInputs: out.querySelectorAll(".fx-text, input[type=text]").length,
      };
    });
    assert.ok(facts.dirtyHasStyle, "precondition: marked hands the sanitizer the <style>, after the paragraph");
    assert.equal(facts.forbidden, 0, "no style, form or button in the rendered message");
    assert.notEqual(facts.outDisplay, "none", "the message's <style> did not hide the transcript");
    assert.ok(facts.goText, "the button's text stays as prose");
    assert.equal(facts.prefixed, 1, "the author's id is prefixed user-content-");
    assert.equal(facts.raw, 0);
    assert.equal(facts.task, 1, "marked's task checkbox survives, disabled and ticked");
    assert.equal(facts.handDisabled, true, "a checkbox written by hand is forced disabled");
    assert.equal(facts.handChecked, false, "and a click leaves it unchecked");
    assert.equal(facts.textInputs, 0, "a text input does not survive");
    assert.deepEqual(errors, [], "no page errors");
  });
});

test("the post-pass registry: a pass registered twice runs once per sanitize, after the math fill", { timeout: 60000 }, async (t) => {
  await inBrowser(t, async (page, errors) => {
    const r = await page.evaluate(() => (window as any).__pipe.registry());
    assert.equal(r.runs, 1, "the counting pass ran once for one sanitize, though registered twice");
    assert.equal(r.other, 1, "the second pass ran too");
    assert.equal(r.sawKatex, true, "and by then the math fill had run: the passes see rendered math");
    assert.deepEqual(errors, [], "no page errors");
  });
});
