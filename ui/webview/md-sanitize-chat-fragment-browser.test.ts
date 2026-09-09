// A message's own `#fragment` link over the REAL chat bundle (render.ts) in headless Chromium, at an http: origin.
// The sanitizer prefixes every author id and name user-content- (md-sanitize.ts, GitHub's rule) and leaves the
// href as written, so the browser's default lookup, which reads the bare name, finds nothing: a footnote's back
// link or a `[section](#install)` over the reply's own `<a name>` would die. The chat's click delegate resolves the
// fragment itself (render.ts; md-sanitize.ts userContentTarget): the message's own rendered body first, then the
// document; found, the target is revealed (a closed <details> above it opened) and scrolled into view and the
// default action cancelled, so the page's hash stays as it was; not found, the click is left to the browser.
// The first test states the delegate's contract over the markup the sanitizer produces; the second runs the
// chat's own pipeline (marked + sanitizeMd, as md() runs them) on a message with a `#` link and clicks it; the
// third posts a session frame so render.ts's own md() renders the reply, and clicks there. Skips with a stated
// reason when no playwright browser is installed (CI installs none; tests/test_spend_modal_headless.py is the
// precedent, skipping without a playwright install). Synthetic values only.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { createRequire } from "node:module";
import { chatBody, ATTACH_TITLE_WEB } from "../../vscode-extension/src/page-skeleton";

const EXT = process.cwd();                                        // npm test runs in vscode-extension
// resolve playwright and esbuild from the extension, not from wherever this bundle was written
const requireCjs = createRequire(path.join(EXT, "package.json"));
const UI = path.resolve(EXT, "..", "ui", "webview");
const STYLES = fs.readFileSync(path.join(UI, "styles.css"), "utf8").replace(/^@import [^\n]*\n/m, "");

const BUILD = { bundle: true, write: false, format: "iife", platform: "browser", target: "es2020",
  nodePaths: [path.join(EXT, "node_modules")], external: ["*.png", "*.svg", "*.woff", "*.ttf", "../media/*.woff2"], logLevel: "silent" };
function bundle(entry: string): string {
  const r = requireCjs("esbuild").buildSync({ ...BUILD, entryPoints: [path.join(UI, entry)] });
  return r.outputFiles[0].text;
}
// md() as render.ts runs it, minus the PR-reference walk: marked with the chat's options and grammar, then sanitizeMd
function probeBundle(): string {
  const contents = [
    'import { marked } from "marked";',
    'import { sanitizeMd } from "./md-sanitize";',
    'import { chatMdExtensions } from "./chat-md";',
    "marked.setOptions({ gfm: true, breaks: false });",
    "marked.use(...chatMdExtensions);",
    "(window as any).__mdProbe = (s: string) => sanitizeMd(marked.parse(s) as string).innerHTML;",
  ].join("\n");
  const r = requireCjs("esbuild").buildSync({ ...BUILD, stdin: { contents, resolveDir: UI, sourcefile: "md-probe.ts", loader: "ts" } });
  return r.outputFiles[0].text;
}

// the chat page as the web dashboard serves it: the shared skeleton, the chat's sheet, a fake acquireVsCodeApi (the
// kernel's shim's role), then the chat bundle and, when a test asks for it, the probe
const chatHtml = (probe: boolean) => `<!DOCTYPE html><html lang=en><head><meta charset=utf-8><style>${STYLES}</style></head><body>
${chatBody(ATTACH_TITLE_WEB)}
<script>window.acquireVsCodeApi=function(){return{postMessage:function(){}}};</script>
<script src=/dist/render.js></script>${probe ? "\n<script src=/dist/probe.js></script>" : ""}</body></html>`;

let pw: any = null;
try { pw = requireCjs("playwright"); } catch { pw = null; }

async function inChat(t: any, probe: boolean, body: (page: any, errors: string[]) => Promise<void>): Promise<void> {
  if (!pw) { t.skip("playwright is not installed under vscode-extension; the browser leg needs it (CI installs no browsers)"); return; }
  let browser: any;
  try { browser = await pw.chromium.launch(); }
  catch (e) { t.skip("no playwright browser on this machine; the browser leg needs one (CI installs none): " + String((e as Error).message).split("\n")[0]); return; }
  const errors: string[] = [];
  try {
    const renderJs = bundle("render.ts");
    const probeJs = probe ? probeBundle() : "";
    const page = await browser.newPage({ viewport: { width: 900, height: 600 } });
    page.on("pageerror", (e: Error) => { errors.push(e.message); });
    await page.route("**/*", (route: any) => {
      const u = new URL(route.request().url());
      if (u.hostname !== "romp.test") return route.fulfill({ status: 404, body: "" });
      if (u.pathname === "/chat") return route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: chatHtml(probe) });
      if (u.pathname === "/dist/render.js") return route.fulfill({ status: 200, contentType: "application/javascript", body: renderJs });
      if (u.pathname === "/dist/probe.js") return route.fulfill({ status: 200, contentType: "application/javascript", body: probeJs });
      return route.fulfill({ status: 404, body: "" });
    });
    await page.goto("http://romp.test/chat");
    if (probe) await page.waitForFunction(() => typeof (window as any).__mdProbe === "function", null, { timeout: 10000 });
    await body(page, errors);
  } finally {
    await browser.close();
  }
}

const FILLER = Array.from({ length: 80 }, (_, i) => "<p>Filler paragraph " + (i + 1) + " so the transcript scrolls.</p>").join("\n");

// fill a message body the way render.ts does (body.innerHTML = md(text)), alone in the transcript: `html` is either
// the markup the sanitizer produces (the delegate's contract) or, through the probe, a message's markdown
async function show(page: any, html: string, throughMd: boolean): Promise<string> {
  return page.evaluate(([h, viaMd]: [string, boolean]) => {
    document.querySelectorAll(".fx-turn").forEach((n) => n.remove());
    const content = document.getElementById("content") as HTMLElement;
    const turn = document.createElement("div"); turn.className = "turn turn-assistant fx-turn";
    const body = document.createElement("div"); body.className = "assistant md fx-body";
    body.innerHTML = viaMd ? (window as any).__mdProbe(h) : h;
    turn.appendChild(body); content.appendChild(turn);
    content.scrollTop = 0;
    history.replaceState(null, "", location.pathname);
    return body.innerHTML;
  }, [html, throughMd] as [string, boolean]);
}
type Landed = { hash: string; inView: boolean; prevented: boolean | null; detailsOpen: boolean | null };
// one real click at the link's centre; then where the target stands relative to the transcript's viewport, the page's
// hash, whether the click's default action was cancelled, and whether a <details> above the target is open. The
// window listener runs after the document's delegate, so what it reads is the delegate's verdict; for a click with a
// modifier held it then cancels the default itself, so the browser opens no window of its own over the test.
async function clickLink(page: any, linkSel: string, targetSel: string, modifier?: "Shift"): Promise<Landed> {
  const link = page.locator(linkSel).first();
  await link.scrollIntoViewIfNeeded();                              // an earlier click may have scrolled it out of the transcript's viewport
  const box = await link.boundingBox();
  assert.ok(box, linkSel + " has a box");
  await page.evaluate((mod: boolean) => { (window as any).__lastClick = null; window.addEventListener("click", (e) => { (window as any).__lastClick = e.defaultPrevented; if (mod) e.preventDefault(); }, { once: true }); }, !!modifier);
  if (modifier) await page.keyboard.down(modifier);
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  if (modifier) await page.keyboard.up(modifier);
  return page.evaluate((sel: string) => {
    const content = document.getElementById("content") as HTMLElement;
    const target = document.querySelector(sel) as HTMLElement | null;
    const c = content.getBoundingClientRect();
    const r = target ? target.getBoundingClientRect() : null;
    const details = target ? target.closest("details") : null;
    return { hash: location.hash, inView: !!r && r.top >= c.top - 1 && r.bottom <= c.bottom + 1,
             prevented: (window as any).__lastClick as boolean | null, detailsOpen: details ? details.hasAttribute("open") : null };
  }, targetSel);
}

test("the delegate lands a message's `#` link on its prefixed target, revealing a closed <details>, with the hash untouched; a fragment with no target is left to the browser", { timeout: 60000 }, async (t) => {
  await inChat(t, false, async (page, errors) => {
    // the markup the sanitizer produces for a reply with a footnote, a section anchor and a folded note
    await show(page, [
      '<p>Claim.<sup id="user-content-fn1"><a href="#fnref1" class="fx-fwd">1</a></sup> <a href="#install" class="fx-install">install</a>',
      ' <a href="#note" class="fx-note">the note</a> <a href="#found" class="fx-found">the searchable</a> <a href="#nowhere" class="fx-none">missing</a></p>',
      FILLER,
      '<a name="user-content-install" class="fx-install-anchor"></a><p class="fx-install-p">Install section.</p>',
      '<p id="user-content-fnref1">1. a note <a href="#fn1" class="fx-back">back</a>.</p>',
      FILLER,
      '<details class="fx-details"><summary>notes</summary><p id="user-content-note">the folded note</p></details>',
      FILLER,
      '<div hidden="until-found" class="fx-until"><p id="user-content-found">shown when found</p></div>',
    ].join("\n"), false);
    const before = await page.evaluate(() => ({ inView: (() => { const c = document.getElementById("content")!.getBoundingClientRect(); const r = document.querySelector("#user-content-fnref1")!.getBoundingClientRect(); return r.top >= c.top && r.bottom <= c.bottom; })(), hash: location.hash }));
    assert.equal(before.inView, false, "precondition: the footnote starts out of view");
    assert.equal(before.hash, "");

    const fwd = await clickLink(page, ".fx-fwd", "#user-content-fnref1");
    assert.equal(fwd.prevented, true, "the delegate cancelled the click's default action");
    assert.equal(fwd.inView, true, "the footnote is in view: resolved under the prefix");
    assert.equal(fwd.hash, "", "the page's hash is untouched");

    const back = await clickLink(page, ".fx-back", "#user-content-fn1");
    assert.equal(back.prevented, true);
    assert.equal(back.inView, true, "the back link lands on the prefixed sup");
    assert.equal(back.hash, "");

    const install = await clickLink(page, ".fx-install", ".fx-install-p");
    assert.equal(install.prevented, true);
    assert.equal(install.inView, true, "a link over the reply's own <a name> lands on it under the prefix");
    assert.equal(install.hash, "");

    const note = await clickLink(page, ".fx-note", "#user-content-note");
    assert.equal(note.prevented, true);
    assert.equal(note.detailsOpen, true, "the closed <details> above the target was opened, as the browser's fragment navigation would");
    assert.equal(note.inView, true, "and the folded note is in view");
    assert.equal(note.hash, "");

    await page.evaluate(() => { (document.getElementById("content") as HTMLElement).scrollTop = 0; });
    const none = await clickLink(page, ".fx-none", "#user-content-nowhere");
    assert.equal(none.prevented, false, "a fragment that names nothing is left to the browser");
    assert.equal(none.hash, "#nowhere", "whose default action sets the hash, as before");

    // a target under hidden="until-found" is revealed the way the browser's fragment navigation reveals it
    await page.evaluate(() => { history.replaceState(null, "", location.pathname); (document.getElementById("content") as HTMLElement).scrollTop = 0; });
    const found = await clickLink(page, ".fx-found", "#user-content-found");
    assert.equal(found.prevented, true);
    assert.equal(await page.evaluate(() => (document.querySelector(".fx-until") as HTMLElement).hasAttribute("hidden")), false, "hidden=until-found was removed from the target's ancestor");
    assert.equal(found.inView, true, "and the target is in view");
    assert.equal(found.hash, "");

    // a click with a modifier held asked the browser for a window of its own: the delegate leaves it alone
    await page.evaluate(() => { (document.getElementById("content") as HTMLElement).scrollTop = 0; });
    const shifted = await clickLink(page, ".fx-fwd", "#user-content-fnref1", "Shift");
    assert.equal(shifted.prevented, false, "the delegate did not cancel a shift-click");
    assert.equal(shifted.inView, false, "and did not scroll to the target");
    assert.deepEqual(errors, [], "no page errors");
  });
});

test("through the chat's own pipeline: a reply's `<p id>` is prefixed and its `[link](#id)` still lands on it, in the reply's body before an older message's", { timeout: 60000 }, async (t) => {
  await inChat(t, true, async (page, errors) => {
    // an OLDER message carrying the same id: the click in the newer one must land in its own body, not there
    const html = await page.evaluate(([older, newer]: [string, string]) => {
      document.querySelectorAll(".fx-turn").forEach((n) => n.remove());
      const content = document.getElementById("content") as HTMLElement;
      const out: string[] = [];
      for (const [cls, src] of [["fx-older", older], ["fx-newer", newer]] as const) {
        const turn = document.createElement("div"); turn.className = "turn turn-assistant fx-turn";
        const body = document.createElement("div"); body.className = "assistant md " + cls;
        body.innerHTML = (window as any).__mdProbe(src);
        turn.appendChild(body); content.appendChild(turn);
        out.push(body.innerHTML);
      }
      content.scrollTop = 0;
      history.replaceState(null, "", location.pathname);
      return out;
    }, ['<p id="dup" class="fx-dup-older">the older dup</p>\n\nolder text',
        ['[go to top](#top) and [dup](#dup)', '', FILLER.replace(/<\/?p>/g, "").split("\n").join("\n\n"), '', '<p id="top" class="fx-top">Top paragraph.</p>', '', '<p id="dup" class="fx-dup-here">this message\'s dup</p>'].join("\n")] as [string, string]);
    // DOMPurify re-adds the attributes it keeps, so their order is its own: match the two whatever the order
    assert.match(html[1], /<p (?=[^>]*\bid="user-content-top")(?=[^>]*\bclass="fx-top")[^>]*>/, "the reply's id is prefixed by the sanitizer");
    assert.match(html[1], /href="#top"/, "and its href is left as written");
    assert.doesNotMatch(html[1], /id="top"/);

    const top = await clickLink(page, ".fx-newer a[href='#top']", ".fx-top");
    assert.equal(top.prevented, true, "the delegate cancelled the click");
    assert.equal(top.inView, true, "the reply's own paragraph is in view");
    assert.equal(top.hash, "", "the hash is untouched");

    await page.evaluate(() => { (document.getElementById("content") as HTMLElement).scrollTop = 0; });
    const dup = await clickLink(page, ".fx-newer a[href='#dup']", ".fx-dup-here");
    assert.equal(dup.prevented, true);
    assert.equal(dup.inView, true, "a duplicated id resolves in the reply's own body first");
    const olderInView = await page.evaluate(() => { const c = document.getElementById("content")!.getBoundingClientRect(); const r = document.querySelector(".fx-dup-older")!.getBoundingClientRect(); return r.top >= c.top && r.bottom <= c.bottom; });
    assert.equal(olderInView, false, "not in the older message's");
    assert.deepEqual(errors, [], "no page errors");
  });
});

test("through render.ts's own md(): a session frame's reply renders with its ids prefixed and its `#` link lands", { timeout: 60000 }, async (t) => {
  await inChat(t, false, async (page, errors) => {
    // the kernel's session frame, as the pane's frame listener receives it: the one session is adopted as the active
    // tab and its events are rendered by render.ts (renderEventInner: body.innerHTML = md(ev.md))
    const SID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
    const reply = ["[go to top](#top)", "", FILLER.replace(/<\/?p>/g, "").split("\n").join("\n\n"), "", '<p id="top" class="fx-top">Top paragraph.</p>'].join("\n");
    await page.evaluate(([sid, md]: [string, string]) => {
      window.postMessage({ type: "session", id: sid, name: "web", cwd: "/tmp/TESTHOST/notes-api", status: { state: "idle", sinceEpoch: null },
                           events: [{ kind: "assistant", md, uuid: "11111111-2222-4333-8444-555555555555" }] }, "*");
    }, [SID, reply] as [string, string]);
    await page.waitForSelector("#content .turn-assistant .md .fx-top", { state: "attached", timeout: 10000 });
    const facts = await page.evaluate(() => {
      const body = document.querySelector("#content .turn-assistant .md") as HTMLElement;
      history.replaceState(null, "", location.pathname);
      (document.getElementById("content") as HTMLElement).scrollTop = 0;
      return { prefixed: body.querySelectorAll("p#user-content-top.fx-top").length, raw: body.querySelectorAll("#top").length,
               href: (body.querySelector("a") as HTMLAnchorElement).getAttribute("href") };
    });
    assert.equal(facts.prefixed, 1, "render.ts's md() prefixed the reply's id");
    assert.equal(facts.raw, 0);
    assert.equal(facts.href, "#top", "and left the href as written");
    const top = await clickLink(page, "#content .turn-assistant .md a[href='#top']", ".fx-top");
    assert.equal(top.prevented, true, "the delegate cancelled the click");
    assert.equal(top.inView, true, "the reply's own paragraph is in view");
    assert.equal(top.hash, "", "the hash is untouched");
    assert.deepEqual(errors, [], "no page errors");
  });
});
