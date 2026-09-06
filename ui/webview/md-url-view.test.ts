// A markdown link on the dashboard's OWN origin opens in the file viewer, rendered (the user
// 2026-09-06) — it used to open the raw text in a new tab. The viewer grew a URL mode: the browser
// fetches the URL itself (no kernel route, no proxy — the kernel's /file relay is a preview relay and
// stays one), mdBlock renders it with the shared Rendered ⇄ Raw preference, and relative figures and
// links inside the document resolve against the document rather than the page. Cross-origin .md links
// keep the new tab exactly. No jsdom harness for these modules → source pins, plus the executed
// helpers in md-links.test.ts. Synthetic hosts/paths only (TESTHOST, /figs/run-1/evidence.md).
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const web = (f: string) => fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", f), "utf8");
const RENDER = web("render.ts");
const VIEW = web("file-view.ts");
const CHAT_CSS = web("styles.css");
const FEED_CSS = web("feed.css");
const KERNEL = fs.readFileSync(path.resolve(process.cwd(), "..", "kernel", "kernel.py"), "utf8");

// the chat's global anchor-click delegate (the same isolation chat-link-open.test.ts uses)
const HANDLER = (RENDER.match(/closest\?\.\("a\[href\]"\)[\s\S]*?\}, true\);/) || [""])[0];
// the URL viewer, from its export to the next top-level function
const URL_FN = (VIEW.split("export function openUrlView")[1] || "").split("// Kick the browser's downloader")[0];
// the markdown renderer
const MD_FN = (VIEW.split("function mdBlock(")[1] || "").split("// The image body:")[0];
// the local viewer (the split file-view.test.ts uses — openUrlView sits AFTER offersDownload so it
// never leaks into this slice)
const OPEN_FN = VIEW.split("export function openFileView")[1].split("function offersDownload")[0];

// ── 1. the interception: same-origin .md, BEFORE window.open, web only ──

test("the anchor delegate routes a same-origin .md href to the viewer BEFORE the new-tab window.open", () => {
  assert.ok(HANDLER, "found the anchor-click handler");
  assert.match(HANDLER, /if \(!a\.dataset\.newTab && isMarkdownUrl\(href, location\.origin\)\) \{ openUrlView\(href\); return; \}/);
  const viewer = HANDLER.indexOf("openUrlView(href)");
  const tab = HANDLER.indexOf('window.open(href, "_blank", "noopener,noreferrer")');
  assert.ok(viewer > -1 && tab > -1 && viewer < tab, "the viewer branch precedes window.open");
  // …inside the web arm: the check sits after the http/https protocol test
  const webArm = HANDLER.indexOf('location.protocol === "http:" || location.protocol === "https:"');
  assert.ok(webArm > -1 && webArm < viewer, "the .md branch lives in the web (http/https) arm");
  // the cross-origin path still reaches the exact new-tab call it always did
  assert.match(HANDLER, /window\.open\(href, "_blank", "noopener,noreferrer"\);/);
  // the VS Code branch is untouched — openLink still posts to the host, and never opens the viewer
  assert.match(HANDLER, /\} else if \(vscodeApi\) \{\s*\n\s*vscodeApi\.postMessage\(\{ type: "openLink", href \}\);/);
  const vsArm = HANDLER.slice(HANDLER.indexOf("} else if (vscodeApi) {"));
  assert.doesNotMatch(vsArm, /openUrlView/, "the webview cannot reach the kernel origin — no viewer there");
  // the helpers arrive on their own import lines (the openFileView import is pinned verbatim elsewhere)
  assert.match(RENDER, /import \{ openFileView \} from "\.\/file-view";/);
  assert.match(RENDER, /import \{ openUrlView \} from "\.\/file-view";/);
  assert.match(RENDER, /import \{ isMarkdownUrl \} from "\.\/md-links";/);
});

test("the whole-backtick URL anchors (url-code-link) flow through the same delegate — no handler of their own", () => {
  const linkify = RENDER.split("function linkifyFileUris(")[1].split("const previewable")[0];
  assert.match(linkify, /a\.href = t;/, "an absolute http(s) href — the delegate sees a scheme");
  assert.match(linkify, /a\.className = "url-code-link";/);
  assert.doesNotMatch(linkify, /addEventListener\("click"|onclick|window\.open|openUrlView/,
    "the anchor carries no click logic; the document-level delegate decides viewer vs tab");
});

// ── 2. the URL viewer itself ──

test("openUrlView exists, fetches the given href from the browser (never fileUrl), and adds no kernel surface", () => {
  assert.match(VIEW, /export function openUrlView\(href: string\): void \{/);
  assert.ok(VIEW.indexOf("export function openUrlView") > VIEW.indexOf("function offersDownload"),
    "sits after offersDownload — outside the slice file-view.test.ts takes as openFileView's body");
  assert.doesNotMatch(OPEN_FN, /openUrlView|kind: "url"/, "the local viewer's body is untouched by URL mode");
  assert.match(URL_FN, /fetch\(href, \{ cache: "no-store" \}\)/);
  assert.doesNotMatch(URL_FN, /fileUrl\(|kernelUrl\(|\/file\?|\/remote\//, "the URL is fetched as given — no kernel route, no relay");
  assert.doesNotMatch(URL_FN, /\bpost\(/, "nothing is asked of the kernel over the socket either");
  // …and the kernel gained no route for it
  assert.doesNotMatch(KERNEL, /\/(fetch-url|url-proxy|proxy-url|remote-url)\b/, "no URL relay route was added");
});

test("URL mode: the loader is up before the fetch, the body renders through mdBlock with the document's URL as base", () => {
  assert.match(VIEW, /function loaderEl\(\): HTMLElement \{/);
  assert.match(VIEW, /const load = el\("div", "fileview-load"\);\s*\n\s*load\.innerHTML = '<img src="\/media\/romp-swirl-glyph\.svg" alt=""><span>romp<\/span>'/);
  const loader = URL_FN.indexOf("body.appendChild(loaderEl());");
  const fetchAt = URL_FN.indexOf("fetch(href, { cache");
  assert.ok(loader > -1 && fetchAt > -1 && loader < fetchAt, "loader first, then the fetch replaces it");
  assert.match(URL_FN, /mdBlock\(text, \{ kind: "url", href \}\)/);
  assert.match(URL_FN, /codeBlock\(text, parts\.base, true\)/, "Raw is the same soft-wrapped code view, highlighted as markdown");
  assert.match(URL_FN, /if \(text === null\) return;/, "the loader holds the body until the bytes land");
});

test("URL mode shares the Rendered ⇄ Raw preference (the same localStorage key) and acknowledges the toggle synchronously", () => {
  assert.match(URL_FN, /const fmt = loadFmt\(\);/);
  assert.match(URL_FN, /b\.addEventListener\("click", \(\) => \{ fmt\.md = mode; saveFmt\(fmt\); renderBody\(\); \}\);/);
  assert.match(URL_FN, /b\.classList\.toggle\("on", on\);/);
  assert.match(VIEW, /const FMT_KEY = "romp:fileviewFmt";/);
  assert.equal((VIEW.match(/localStorage\.(get|set)Item\(FMT_KEY/g) || []).length, 2, "one key, read and written in one place");
});

test("URL mode chrome: host/dir/ dimmed (not a browse link) + basename; Open ↗ link-out; Copy URL; ✕; Esc closes", () => {
  assert.match(URL_FN, /const parts = urlTitleParts\(href\);/);
  assert.match(URL_FN, /el\("span", "fileview-dir"\)[\s\S]*?dir\.textContent = parts\.dir;/);
  assert.match(URL_FN, /el\("span", "fileview-base"\)[\s\S]*?base\.textContent = parts\.base;/);
  assert.doesNotMatch(URL_FN, /fileview-dir-link|browseFiles/, "no file browser for a URL — the directory half is plain");
  // the link-out: an anchor in the button dress, new tab, noopener — the GitHub link's treatment
  assert.match(URL_FN, /el\("a", "fileview-btn fileview-gh"\)/);
  assert.match(URL_FN, /a\.href = href; a\.target = "_blank"; a\.rel = "noopener";/);
  assert.match(URL_FN, /a\.textContent = "Open ↗";/);
  // …and it marks itself data-new-tab: its href IS the same-origin .md the delegate would otherwise
  // route straight back into this viewer — the marker is what makes the tab open
  assert.match(URL_FN, /a\.dataset\.newTab = "1";/);
  assert.ok(HANDLER.includes("!a.dataset.newTab &&"), "the delegate honours the marker before the .md check");
  // the marker rides ONLY the link-out: a rendered document's own anchors never carry it, so a
  // sibling .md link keeps navigating in place
  assert.doesNotMatch(MD_FN, /newTab|new-tab/);
  // Copy copies the URL (the local mode's Copy path equivalent), with the same feedback words
  assert.match(URL_FN, /copy\.textContent = "Copy URL";/);
  assert.match(URL_FN, /navigator\.clipboard\?\.writeText\(href\)/);
  assert.match(URL_FN, /copy\.textContent = "Copied";/);
  assert.match(URL_FN, /copy\.textContent = "Copy failed";/);
  // ✕ and Esc close through the shared closeFileView
  assert.match(URL_FN, /el\("button", "fileview-btn fileview-close"\)/);
  assert.match(URL_FN, /close\.addEventListener\("click", closeFileView\);/);
  assert.match(URL_FN, /if \(e\.key !== "Escape" \|\| !document\.getElementById\("romp-fileview"\)\) return;/);
  // the same modal shell: the id every open/closed check targets, backdrop click closes, body class
  assert.match(URL_FN, /wrap\.id = "romp-fileview";/);
  assert.match(URL_FN, /wrap\.onclick = \(ev\) => \{ if \(ev\.target === wrap\) closeFileView\(\); \};/);
  assert.match(URL_FN, /document\.body\.classList\.add\("fileview-open"\);/);
});

test("URL mode has NO Edit / Save / Download / GitHub / ‹ Files — every one of those is keyed on a kernel reply", () => {
  assert.doesNotMatch(URL_FN, /textContent = "(Edit|Save|Cancel|Download|‹ Files|GitHub ↗)"/);
  assert.doesNotMatch(URL_FN, /fileViewActions|registerFileViewAction|fileGitLink|editingAllowed|enterEdit|startDownload/);
  assert.doesNotMatch(URL_FN, /headers\.get\("(X-Romp-[A-Za-z-]+|Content-Type)"\)/, "no kernel verdict headers are read — there is no kernel reply");
});

test("URL mode replaces an open viewer through the same guarded path (unsaved edits ask first; registrations drop)", () => {
  assert.match(URL_FN, /if \(document\.getElementById\("romp-fileview"\) && closeGuard && !closeGuard\(\)\) return;/);
  for (const drop of ["closeGuard = null;", "editHooks = null;", "gitHooks = null;", "dropMediaUrl();"])
    assert.ok(URL_FN.includes(drop), drop + " before the old viewer is torn down");
  assert.ok(URL_FN.indexOf("dropMediaUrl();") < URL_FN.indexOf('document.getElementById("romp-fileview")?.remove();'));
});

// ── 3. loud failures, and the 2 MB cap mirrored from the kernel ──

test("a non-OK status shows `HTTP <status> from <host>` in the pane, plus the link-out — never console-only", () => {
  assert.match(URL_FN, /if \(!r\.ok\) \{ fail\("HTTP " \+ r\.status \+ " from " \+ host\); return; \}/);
  const failFn = (URL_FN.split("const fail = ")[1] || "").split("\n  };")[0];
  assert.ok(failFn, "the failure pane builder exists");
  assert.match(failFn, /el\("div", "fileview-err"\)/);
  assert.match(failFn, /why\.textContent = words;/);
  assert.match(failFn, /el\("div", "fileview-err-hint"\)[\s\S]*?hint\.textContent = href;/, "the URL under the words");
  assert.match(failFn, /why\.appendChild\(linkOut\(\)\);/, "the way out: the URL in a new tab");
  assert.match(failFn, /body\.replaceChildren\(why\);/);
  assert.match(failFn, /if \(!wrap\.isConnected\) return;/, "a failure landing after a close paints nothing");
  assert.doesNotMatch(URL_FN, /console\.(log|warn|error)/);
});

test("a thrown fetch (network) says the document could not be loaded from this page, with the link-out", () => {
  assert.match(URL_FN, /\.catch\(\(err\) => \{\s*\n\s*fail\("this document could not be loaded from this page — " \+ String\(err && \(err as Error\)\.message \|\| err\)\);/);
});

test("the body cap is the kernel's 2 MB text cap: Content-Length when declared, the decoded length otherwise", () => {
  assert.match(VIEW, /const URL_TEXT_MAX_BYTES = 2 \* 1024 \* 1024;/);
  assert.match(KERNEL, /^_TEXT_MAX_BYTES = 2 \* 1024 \* 1024/m, "the kernel's cap the viewer mirrors");
  assert.match(URL_FN, /const declared = Number\(r\.headers\.get\("Content-Length"\) \|\| ""\);/);
  assert.match(URL_FN, /if \(declared > URL_TEXT_MAX_BYTES\) \{ tooLarge\(declared\); return; \}/);
  assert.match(URL_FN, /if \(t\.length > URL_TEXT_MAX_BYTES\) \{ tooLarge\(t\.length\); return; \}/);
  assert.match(URL_FN, /too large to show here \(the cap is " \+ humanSize\(URL_TEXT_MAX_BYTES\) \+ "\)"/);
  // ordering: status → declared length → body → decoded length; the body is never read past a refusal
  const status = URL_FN.indexOf("if (!r.ok)");
  const declared = URL_FN.indexOf("if (declared > URL_TEXT_MAX_BYTES)");
  const readBody = URL_FN.indexOf("return r.text()");
  const decoded = URL_FN.indexOf("if (t.length > URL_TEXT_MAX_BYTES)");
  assert.ok(status < declared && declared < readBody && readBody < decoded, "status, header cap, read, decoded cap");
  // no Content-Type sniffing: the path decided it is markdown, the body is text and renders as markdown
  assert.doesNotMatch(URL_FN, /headers\.get\("Content-Type"\)/);
  assert.match(URL_FN, /return r\.text\(\)\.then/, "read as text, whatever the server labelled it");
  // executed: the pipeline model — an absent/unparseable Content-Length falls through to the decoded length
  const CAP = 2 * 1024 * 1024;
  const route = (ok: boolean, status: number, lengthHeader: string | null, textLen: number) => {
    if (!ok) return "HTTP " + status;
    const declared = Number(lengthHeader || "");
    if (declared > CAP) return "large";
    if (textLen > CAP) return "large";
    return "ok";
  };
  assert.equal(route(false, 404, null, 0), "HTTP 404");
  assert.equal(route(true, 200, String(CAP + 1), 10), "large", "the header alone refuses — the body is never read");
  assert.equal(route(true, 200, String(CAP), CAP), "ok", "exactly the cap is fine");
  assert.equal(route(true, 200, null, CAP + 1), "large", "no header: the decoded length decides");
  assert.equal(route(true, 200, "not-a-number", 10), "ok", "an unparseable header is not a refusal");
  assert.equal(route(true, 200, "", 10), "ok");
});

// ── 4. relative references inside the rendered document ──

test("mdBlock takes the document's location and rewrites relative img/src and a/href AFTER DOMPurify", () => {
  assert.match(VIEW, /type MdDocLoc = \{ kind: "url"; href: string \} \| \{ kind: "file"; path: string; sid: string \| null \};/);
  assert.match(VIEW, /function mdBlock\(text: string, doc\?: MdDocLoc\): HTMLElement \{/);
  const sanitize = MD_FN.indexOf("DOMPurify.sanitize(");
  const rewrite = MD_FN.indexOf("resolveDocRelative(");
  assert.ok(sanitize > -1 && rewrite > sanitize, "sanitise first; the rewrite only ever sees what DOMPurify kept");
  // the ATTRIBUTE, never the property — .src/.href are already resolved against the page (the wrong base)
  assert.match(MD_FN, /const src = img\.getAttribute\("src"\) \|\| "";/);
  assert.match(MD_FN, /const href = a\.getAttribute\("href"\) \|\| "";/);
  assert.doesNotMatch(MD_FN, /img\.src\b|a\.href\b/, "no property reads");
  // URL mode: both resolve against the document URL through the executed helper
  assert.match(MD_FN, /const abs = resolveDocRelative\(src, doc\.href\);\s*\n\s*if \(abs !== src\) img\.setAttribute\("src", abs\);/);
  assert.match(MD_FN, /a\.setAttribute\("href", resolveDocRelative\(href, doc\.href\)\);/);
  // in-document and already-absolute anchors are left alone
  assert.match(MD_FN, /if \(!href \|\| href\.startsWith\("#"\) \|\| \/\^\[a-z\]\[a-z0-9\+\.-\]\*:\/i\.test\(href\)\) return;/);
  // the two helpers arrive from the pure module
  assert.match(VIEW, /import \{ resolveDocRelative, joinDocPath, urlTitleParts \} from "\.\/md-links";/);
});

test("local file mode: a relative image is the sibling over the kernel's /file route (fileUrl, never hand-built)", () => {
  assert.match(MD_FN, /img\.setAttribute\("src", fileUrl\(joinDocPath\(doc\.path, src\), doc\.sid\)\);/);
  // gated to path-shaped refs: a scheme (http:, data:) or a protocol-relative URL is the browser's
  assert.match(MD_FN, /else if \(src && !\/\^\[a-z\]\[a-z0-9\+\.-\]\*:\/i\.test\(src\) && !src\.startsWith\("\/\/"\)\) \{/);
  assert.doesNotMatch(MD_FN, /"\/file\?path="|\/remote\//, "the route is fileUrl's to build (federation-aware)");
  assert.match(VIEW, /import \{ fileUrl \} from "\.\/preview";/);
  // openFileView hands mdBlock its location
  assert.match(OPEN_FN, /mdBlock\(text, \{ kind: "file", path, sid: sid \|\| null \}\)/);
});

test("local file mode: a relative link opens the sibling in the viewer via ONE delegated data-act listener on the body", () => {
  // the anchor carries the joined path as data, keeps its href for hover, and is not forced to _blank
  assert.match(MD_FN, /const joined = joinDocPath\(doc\.path, href\);\s*\n\s*a\.dataset\.act = "fv-open";\s*\n\s*a\.dataset\.path = joined;\s*\n\s*a\.title = joined;/);
  assert.match(MD_FN, /if \(\(a as HTMLElement\)\.dataset\.act === "fv-open"\) return;\s*\n\s*\(a as HTMLAnchorElement\)\.target = "_blank";/);
  // …the delegate: actions.ts's delegate, installed once per open on the body (stable across the
  // Rendered ⇄ Raw swaps that rebuild its children), preventDefault, then openFileView with this sid
  assert.match(VIEW, /import \{ delegate \} from "\.\/actions";/);
  assert.match(OPEN_FN, /delegate\(body, \{\s*\n\s*"fv-open": \(a, ev\) => \{\s*\n\s*ev\.preventDefault\(\);\s*\n\s*const target = a\.dataset\.path;\s*\n\s*if \(target\) openFileView\(target, sid\);/);
  assert.equal((OPEN_FN.match(/delegate\(body/g) || []).length, 1, "one listener per open, never in a render path");
  assert.ok(OPEN_FN.indexOf("delegate(body") < OPEN_FN.indexOf("const renderBody ="), "installed before any render can run");
  // the chat's document-level delegate ignores scheme-less hrefs, so the click reaches the body listener
  assert.match(HANDLER, /if \(!\/\^\[a-z\]\[a-z0-9\+\.-\]\*:\/i\.test\(href\)\) return;/);
});

// ── 5. styling: no new rules — the URL viewer wears the viewer's existing chrome in BOTH sheets ──

test("every class the URL viewer uses is already declared in both sheets (nothing new to mirror)", () => {
  for (const head of ["#romp-fileview {", ".fileview {", ".fileview-bar {", ".fileview-name {", ".fileview-dir {",
    ".fileview-base {", ".fileview-acts {", ".fileview-btn {", "a.fileview-btn {", ".fileview-body {",
    ".fileview-err {", ".fileview-err-hint {", ".fileview-load {", ".fileview-md {"]) {
    assert.ok(CHAT_CSS.includes(head), head + " in styles.css");
    assert.ok(FEED_CSS.includes(head), head + " in feed.css");
  }
  assert.doesNotMatch(URL_FN, /style\.|cssText|innerHTML = '<style/, "no inline styling");
});
