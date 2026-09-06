// A PDF opens in its OWN browser tab (the user 2026-09-06, who wanted what OpenReview and HotCRP do:
// the paper full size in a tab of its own, not a small window inside the dashboard). The opener is
// ONE window.open inside the click gesture aimed at the kernel's /file URL — the browser's own viewer
// renders the inline application/pdf response from its cache, nothing lands on disk — and a null
// handle (the browser blocked the popup) falls back to the in-app view so the PDF is never
// unreachable. Executed here with a stubbed window/location; the wiring is pinned in source.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { openPdfTab, fileUrl } from "./preview";

const UI = path.resolve(process.cwd(), "..", "ui", "webview");
const PREVIEW = fs.readFileSync(path.join(UI, "preview.ts"), "utf8");
const VIEW = fs.readFileSync(path.join(UI, "file-view.ts"), "utf8");
const KERNEL = fs.readFileSync(path.resolve(process.cwd(), "..", "bin", "romp-kernel"), "utf8");
const GUIDE = fs.readFileSync(path.resolve(process.cwd(), "..", "docs", "guide.md"), "utf8");

const SID = "11111111-2222-3333-4444-555555555555";
const g = globalThis as any;

function withBrowser(protocol: string, open: ((...a: unknown[]) => unknown) | null, run: () => void): unknown[][] {
  const calls: unknown[][] = [];
  const savedLoc = g.location, savedWin = g.window;
  g.location = { protocol };
  g.window = { open: (...a: unknown[]) => { calls.push(a); return open ? open(...a) : null; } };
  try { run(); } finally { g.location = savedLoc; g.window = savedWin; }
  return calls;
}

test("web dashboard, popup allowed: ONE window.open on the kernel's /file URL, in a new tab, opener severed by hand", () => {
  let ok = false;
  const handle: { opener: unknown } = { opener: { theDashboard: true } };   // what a fresh tab holds until disowned
  const calls = withBrowser("https:", () => handle, () => { ok = openPdfTab("/tmp/paper.pdf", SID); });
  assert.equal(ok, true);
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0], [fileUrl("/tmp/paper.pdf", SID), "_blank"],
    "the same-origin file URL, a new tab, and NO noopener feature: it would return null even on success");
  assert.equal(calls[0][0], "/file?path=%2Ftmp%2Fpaper.pdf&sid=" + SID);
  assert.equal(handle.opener, null,
    "the tab's opener is severed on the handle (a link inside the PDF navigates the tab to a foreign site — it must not hold the dashboard)");
});

test("a federated session's PDF goes through the relay URL, still same-origin", () => {
  const calls = withBrowser("http:", () => ({}), () => { openPdfTab("out/report.pdf", "gpu1:" + SID); });
  assert.equal(calls[0][0], "/remote/gpu1/file?path=out%2Freport.pdf&sid=" + SID);
});

test("popup BLOCKED (null handle): reports false so the caller falls back to the in-app view", () => {
  let ok = true;
  const calls = withBrowser("https:", null, () => { ok = openPdfTab("/tmp/paper.pdf", SID); });
  assert.equal(ok, false);
  assert.equal(calls.length, 1, "it did try — the block is the browser's verdict, read from the handle");
});

test("a non-PDF path is not the opener's business: false, no attempt — the viewer's media branch decides by Content-Type", () => {
  let ok = true;
  const calls = withBrowser("https:", () => ({}), () => { ok = openPdfTab("/tmp/notes.md", SID); });
  assert.equal(ok, false);
  assert.equal(calls.length, 0);
});

test("not the web dashboard (a webview origin): no attempt at all, false", () => {
  let ok = true;
  const calls = withBrowser("vscode-webview:", () => ({}), () => { ok = openPdfTab("/tmp/paper.pdf", SID); });
  assert.equal(ok, false);
  assert.equal(calls.length, 0, "the webview sandbox cannot window.open — callers keep their own path");
});

test("wiring: the card and the viewer open the tab first and fall back to the in-app view", () => {
  // the card's click → openPdf → the tab, else the lightbox
  assert.match(PREVIEW, /export function openPdf\(path: string, sid\?: string \| null\): void \{\n  if \(!openPdfTab\(path, sid\)\) openLightbox\(path, sid\);\n\}/);
  const pf = PREVIEW.slice(PREVIEW.indexOf("export function previewFull"));
  assert.match(pf, /box\.onclick = \(ev\) => \{ ev\.stopPropagation\(\); openPdf\(path, sid\); \};/);
  // the opener itself: synchronous, two-argument window.open — the gesture and the handle both matter
  const opener = PREVIEW.slice(PREVIEW.indexOf("export function openPdfTab"), PREVIEW.indexOf("export function openPdf("));
  assert.match(opener, /if \(previewKind\(path\) !== "pdf" \|\| !canPreview\(\)\) return false;/, "the kind check is the opener's own");
  assert.match(opener, /const w = window\.open\(fileUrl\(path, sid\), "_blank"\);/);
  assert.doesNotMatch(opener, /"noopener/, "the noopener FEATURE makes window.open return null on success — the block signal would be lost");
  assert.match(opener, /if \(!w\) return false;[^\n]*\n\s+try \{ w\.opener = null; \}/, "…so the link is severed on the handle instead, before anything else");
  assert.doesNotMatch(opener, /await|\.then\(/, "the open happens inside the click gesture, never after a fetch");
  // the viewer: a .pdf path takes the tab BEFORE anything on screen is touched, by extension, synchronously
  const view = VIEW.slice(VIEW.indexOf("export function openFileView("));
  const branch = view.indexOf("if (openPdfTab(path, sid ?? null)) return;");
  assert.ok(branch > 0, "the viewer's PDF branch exists");
  assert.ok(branch < view.indexOf('document.getElementById("romp-fileview")?.remove();'),
    "…and runs before the current viewer (if any) is replaced");
  assert.ok(branch < view.indexOf("closeGuard && !closeGuard()"), "…and before the unsaved-edits ask: the tab disturbs nothing");
});

test("the kernel serves a PDF inline WITH its name, so the tab is titled and a Save names the file", () => {
  assert.match(KERNEL, /if mime == "application\/pdf":\n\s+#[^\n]*\n(\s+#[^\n]*\n)*\s+extra\["Content-Disposition"\] = _attachment_disposition\(os\.path\.basename\(fp\), kind="inline"\)/);
  assert.match(KERNEL, /def _attachment_disposition\(name, kind="attachment"\):/);
  assert.match(KERNEL, /disp = '%s; filename="%s"' % \(kind, safe\)/);
  assert.doesNotMatch(KERNEL.slice(KERNEL.indexOf("def _file_preview"), KERNEL.indexOf("def _file_download")),
    /kind="attachment"/, "the view route never serves a PDF as an attachment — the tab must render it");
});

test("an oversize PDF's tab is not a dead end, and the listing marks such a file download-only up front", () => {
  // a navigation (Sec-Fetch-Dest: document) to a PDF over the cap gets a page whose one link is the download
  // half of the route; a fetch / iframe / HEAD keeps the plain text the viewer parses (review find 2026-09-06)
  assert.match(KERNEL, /if not head and mime == "application\/pdf" and self\._is_navigation\(\):/);
  assert.match(KERNEL, /return self\._send\(413, _too_large_page\(msg, os\.path\.basename\(fp\), q\), "text\/html; charset=utf-8",/);
  assert.match(KERNEL, /def _is_navigation\(self\):/);
  assert.match(KERNEL, /\.get\("Sec-Fetch-Dest"\) or ""\)\.strip\(\)\.lower\(\) == "document"/);
  assert.match(KERNEL, /def _too_large_page\(msg, name, q, route="\/file"\):/);
  // the relay: an error verdict is prose (text/plain), and an oversize remote PDF's tab gets the page too
  assert.match(KERNEL, /route="\/remote\/%s\/file" % quote\(host, safe=""\)/);
  assert.match(KERNEL, /if status not in \(200, 206\):/);
  assert.match(KERNEL, /dq = \{"path": \(q\.get\("path"\) or \[""\]\)\[0\], "download": "1"\}/);
  // the listing's verdict follows /file's caps, so the browser routes an oversize row to the download
  assert.match(KERNEL, /row\["viewable"\] = \(bool\(_m\) and size <= _PREVIEW_MAX_BYTES\) \\\n\s+or \(not _m and _is_text_path\(e\.name\) and size <= _TEXT_MAX_BYTES\)/);
  // the relay names a remote PDF from the REQUESTED path, never the remote's header, on HEAD and GET
  const relay = KERNEL.slice(KERNEL.indexOf("def _remote_file("), KERNEL.indexOf("def _relay_download("));
  assert.equal((relay.match(/_attachment_disposition\(os\.path\.basename\(rp\), kind="inline"\)/g) || []).length, 2, "HEAD and GET");
});

test("the guide says so, in the user's terms", () => {
  assert.match(GUIDE, /\*\*Opening a PDF\.\*\* .*opens\nin a new browser tab/);
  assert.match(GUIDE, /If the browser\nblocks the new tab, the PDF opens in the in-app viewer instead; a PDF too large to show\noffers a download in its place\./);
});
