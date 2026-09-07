// The file viewer — a big modal over the CHAT pane (the user 2026-08-15: the first cut filled the
// FEED pane, and reading a file cost the cards; the click came out of the chat, so the file presents
// over the chat, ~95% of the pane behind a dimmed backdrop, ✕ top right — and the feed is never touched).
//
// Clicking a file path in the chat used to post `openFile`, which the kernel served by running an
// opener on ITS machine (the user 2026-08-08). Read the dashboard from another device — a laptop
// across the internet, a phone — and that is the wrong screen entirely; on a kernel with no desktop it
// did nothing at all, silently, which is how the user found it. The only place a file can actually be
// shown is the browser you are looking at, so the bytes come over the same `/file` route the image
// previews already use (federation-aware via fileUrl, so a remote session's file is relayed from the
// host that owns it).
//
// Living in the CHAT page also removes a whole relay: the click and the viewer are the same document
// now, so there is no shell forwarding, no feed-pane bring-forward/put-back, and the standalone /chat
// page views files exactly like the framed one. The module stays pane-agnostic on purpose: the file
// BROWSER (file-browse.ts, feed bundle) opens files through this same viewer in the FEED document, so
// whichever bundle imports it gets the identical modal.
import hljs from "highlight.js/lib/core";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { fileUrl } from "./preview";
import { hostOf, bareId, hostNameNodes } from "./host-prefix";
import { kernelUrl } from "./media";
import { quoteSrcLabel } from "./docreview";
// eslint-disable-next-line @typescript-eslint/no-var-requires
const gclock = require("./gesture-clock.js");   // the gesture clock every settings post stamps through

// hljs is registered per-bundle. Same language set (and grammar registrations) the chat's fence
// highlighting uses, dup-guarded, so importing this module alongside render.ts costs nothing.
import bash from "highlight.js/lib/languages/bash";
import python from "highlight.js/lib/languages/python";
import javascript from "highlight.js/lib/languages/javascript";
import typescript from "highlight.js/lib/languages/typescript";
import json from "highlight.js/lib/languages/json";
import xml from "highlight.js/lib/languages/xml";
import cssLang from "highlight.js/lib/languages/css";
import markdown from "highlight.js/lib/languages/markdown";
import diff from "highlight.js/lib/languages/diff";
import yaml from "highlight.js/lib/languages/yaml";

for (const [name, lang] of Object.entries({
  bash, sh: bash, shell: bash, python, py: python, javascript, js: javascript,
  typescript, ts: typescript, json, xml, html: xml, css: cssLang, markdown, md: markdown,
  diff, yaml, yml: yaml,
})) {
  try { hljs.registerLanguage(name, lang as any); } catch { /* dup alias */ }
}

// Extension → the hljs language to force. Anything absent is shown unhighlighted rather than guessed:
// highlightAuto on a config file or a log picks a language at random and paints it misleadingly, and a
// wrong highlight reads as information the file does not contain.
const LANG: Record<string, string> = {
  py: "python", pyi: "python", js: "javascript", jsx: "javascript", mjs: "javascript",
  cjs: "javascript", ts: "typescript", tsx: "typescript", json: "json", jsonc: "json",
  yaml: "yaml", yml: "yaml", sh: "bash", bash: "bash", zsh: "bash", bats: "bash",
  html: "xml", htm: "xml", xml: "xml", svg: "xml", vue: "xml", css: "css", scss: "css",
  md: "markdown", markdown: "markdown", diff: "diff", patch: "diff",
};

function langFor(path: string): string | null {
  const ext = path.slice(path.lastIndexOf(".") + 1).toLowerCase();
  return LANG[ext] || null;
}

// marked is a per-bundle singleton. render.ts makes the SAME calls with the SAME choices — GFM without
// hard breaks, strikethrough only on DOUBLE tildes (marked's stock GFM `del` tokenizer fires on a
// single ~, so prose between two "approximately" tildes renders struck through; GitHub itself only
// strikes ~~double~~) — so configuring here too is an idempotent no-op in the chat bundle, and keeps
// this module correct anywhere it's bundled without render.ts.
marked.setOptions({ gfm: true, breaks: false });
marked.use({
  tokenizer: {
    del(src: string) {
      const m = /^~~(?=\S)([\s\S]*?\S)~~/.exec(src);
      if (!m) return undefined;
      return { type: "del", raw: m[0], text: m[1], tokens: (this as { lexer: { inlineTokens(s: string): unknown[] } }).lexer.inlineTokens(m[1]) };
    },
  },
} as Parameters<typeof marked.use>[0]);

// ── view-format preferences ────────────────────────────────────────────────────────────────────────
// The Raw ⇄ Rendered choice for markdown and the word-wrap toggle persist in localStorage, NOT a kernel
// file — per-browser view state, the same call feed-view-state.ts makes for the feed's open sections (it
// must survive a kernel restart without a round-trip to the thing that just restarted). RENDERED is the
// default for markdown (the user 2026-08-09); Raw stays one click away.
const FMT_KEY = "romp:fileviewFmt";
// wrap is GONE from the format state (the user 2026-08-24: "there doesn't need to be a button for
// that") — long lines always soft-wrap; a stored wrap key from the toggle era is simply ignored.
type FileViewFmt = { md: "rendered" | "raw" };

// Any malformed/foreign value reads as the defaults rather than throwing — a corrupt entry may cost the
// stored preference, never the viewer (feed-view-state's parseViewState contract).
function parseFmt(raw: string | null | undefined): FileViewFmt {
  const def: FileViewFmt = { md: "rendered" };
  if (!raw) return def;
  try {
    const o = JSON.parse(raw) as { md?: unknown };
    if (!o || typeof o !== "object") return def;
    return { md: o.md === "raw" ? "raw" : "rendered" };
  } catch { return def; }
}

function loadFmt(): FileViewFmt {
  try { return parseFmt(localStorage.getItem(FMT_KEY)); } catch { return parseFmt(null); }
}

function saveFmt(f: FileViewFmt): void {
  try { localStorage.setItem(FMT_KEY, JSON.stringify(f)); } catch { /* storage full */ }
}

function el(tag: string, cls?: string): HTMLElement {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  return e;
}

// ── raw-mode editing (the file browser's slice 2, the user 2026-08-14) ─────────────────────────────
// The save op rides the WS poster the pane's boot hands initFileView; replies route back to the OPEN
// viewer through these module-level hooks (the viewer itself is a per-open closure).
let post: (m: Record<string, unknown>) => void = () => { /* bound by initFileView */ };

// ── the session the file was opened from (the user 2026-09-03) ────────────────────────────────────
// The viewer knows only a sid, and its openers mostly know no more: the relay branch initFileView
// keeps and the conflict Reload live in this module, the file browser hands over a bare sid. So the
// session's name and colour are RESOLVED from the sid here, through a lookup each hosting document
// registers once at boot beside initFileView (render.ts reads its tab set, feed.ts its session list).
// Unregistered, or a sid the document cannot name, the title bar carries no chip: an identity is
// looked up, never invented.
export interface FileViewIdentity { name: string; color: { bg: string; fg: string } | null }
let identityOf: (sid: string) => FileViewIdentity | null = () => null;
export function setFileViewIdentity(fn: typeof identityOf): void { identityOf = fn; }
/** The tail of a resolver's ladder when its lists hold no row for the sid — the kernel's own
 *  _peer_identity fallback: the sid's first 8 characters as an uncolored stub, a remote sid's `host:`
 *  kept in front so hostNameNodes still renders the host quiet. An empty sid names nothing. */
export function hostStub(sid: string): FileViewIdentity | null {
  const bare = bareId(sid);
  if (!bare) return null;
  const host = hostOf(sid);
  return { name: (host ? host + ":" : "") + bare.slice(0, 8), color: null };
}
let saveSeq = 0;
let editHooks: { reqId: number; saved: (mtimeNs: string) => void; failed: (err: string) => void } | null = null;
// Set by the open viewer: returns false to VETO a close (an editor holding unsaved changes asks
// first). The guard must live in closeFileView itself, because the browser overlay and the Escape
// handler both close through it without knowing an edit is in progress.
let closeGuard: (() => boolean) | null = null;
// ONE live media object URL at a time (images used to render as line-numbered mojibake; now an
// image/PDF view holds its bytes in an object URL). The URL is per-open state, but — like editHooks
// and gitHooks above — the teardown must be reachable from BOTH exits (closeFileView and the replace
// path), so the open viewer registers its URL here and each exit revokes it. Without the revoke
// every image view leaks its blob for the page's life.
let mediaUrlLive: string | null = null;
function dropMediaUrl(): void {
  if (mediaUrlLive) {
    try { URL.revokeObjectURL(mediaUrlLive); } catch { /* already gone */ }
    mediaUrlLive = null;
  }
}

// ── viewer action registry (the user 2026-08-22) ── INTERNAL SEAM, no compatibility promise:
// reshape freely. Anything acting on the OPEN file declares itself here instead of hand-wiring into
// openFileView's action row, where every file-viewer change used to collide. mount() runs once per
// open and returns the action's element for the row (or null to sit this file out); an action that
// answers asynchronously (the GitHub link's kernel ask) mounts a placeholder and fills it in when its
// reply lands. Ordering is registration order, after the built-ins.
export interface FileViewActionCtx { path: string; sid: string | null; }
export interface FileViewAction { id: string; mount: (ctx: FileViewActionCtx) => HTMLElement | null; }
const fileViewActions: FileViewAction[] = [];
export function registerFileViewAction(a: FileViewAction): void {
  if (!fileViewActions.some((x) => x.id === a.id)) fileViewActions.push(a);
}

// ── the GitHub link (the user 2026-08-15) — the registry's first entry ─────────────────────────────
// One unit in the action row: the control and, when the kernel gave one, its reason as a caption
// beside it. The OWNING kernel answers the lazy fileGitLink ask, and until it does the unit holds a
// PLACEHOLDER — a dimmed disabled button and the loader's pulsing dots where the caption will go —
// because the check takes up to 3 s when the kernel must ask origin, and an empty slot for that long
// read as the old no-button state (found in review; the loading-state rule). The answer ALWAYS fills
// the slot (the user 2026-09-05, who could not tell an uncommitted file from a broken link when the
// button simply never appeared). A real URL is an anchor — the browser owns the new tab. No URL is
// a real disabled <button>: assistive tech reads the state and the label, and there is no href to
// follow or to go stale. The reason rides in the tooltip AND as the caption, because a tooltip alone
// needs a mouse — touch has no hover, and a disabled button takes no focus — so the caption is what
// makes the reason glanceable, and it is shown whole: the sheet wraps it inside a bounded width, since
// nothing in the unit takes a tap, click or focus that could finish a truncated sentence. A URL
// whose branch is not on origin stays an anchor, dashed, with the note as its caption, since GitHub
// 404s it until the push. One question per open, reqId-guarded; a socket drop while it is out is
// the one thing that loses the reply, and the shim's reconnect event re-asks (initFileView), so the
// placeholder never outlives its wait. Exported for the DOM-shape test.
const GH_REASONLESS = "this kernel predates link reasons; restart it after updating";
let gitSeq = 0;
let gitHooks: { reqId: number; apply: (url: string, reason: string) => void; ask: () => void } | null = null;
export const githubLinkAction: FileViewAction = {
  id: "github-link",
  mount({ path, sid }) {
    const unit = el("span", "fileview-gh");
    // pending: a real disabled button (never an hrefless anchor, which has no role to read) and the
    // loader's three dots in the caption's place; aria-busy names the wait for assistive tech
    const wait = el("button", "fileview-btn") as HTMLButtonElement;
    wait.type = "button"; wait.disabled = true; wait.textContent = "GitHub ↗";
    wait.title = "Checking GitHub…"; wait.setAttribute("aria-label", wait.title);
    const dots = el("span", "fileview-gh-dots");
    for (let i = 0; i < 3; i++) dots.appendChild(el("i", "fileview-dot"));
    unit.setAttribute("aria-busy", "true");
    unit.appendChild(dots); unit.appendChild(wait);
    const reqId = ++gitSeq;
    const ask = () => post({ type: "fileGitLink", path, sid: sid || undefined, reqId });
    gitHooks = {
      reqId,
      ask,
      apply: (url, reason) => {
        let ctl: HTMLElement;
        if (url) {
          const a = el("a", "fileview-btn") as HTMLAnchorElement;
          a.href = url; a.target = "_blank"; a.rel = "noopener";
          a.title = reason ? url + "\n" + reason : url;      // the full URL one hover away, and the note with it
          if (reason) { a.classList.add("fileview-gh-note"); a.setAttribute("aria-label", "GitHub: " + reason); }
          ctl = a;
        } else {
          // an older kernel answers without a reason — say what that means, rather than invent one
          const b = el("button", "fileview-btn") as HTMLButtonElement;
          b.type = "button"; b.disabled = true;
          b.title = "No GitHub link: " + (reason || GH_REASONLESS);
          b.setAttribute("aria-label", b.title);
          ctl = b;
        }
        ctl.textContent = "GitHub ↗";
        const why = reason || (url ? "" : GH_REASONLESS);
        const parts: HTMLElement[] = [];
        if (why) {
          const cap = el("span", "fileview-gh-why");
          cap.textContent = why;                             // whole, wrapped by the sheet — no tooltip to reach for
          parts.push(cap);                                   // before the control: it annotates what follows
        }
        parts.push(ctl);
        unit.replaceChildren(...parts);                      // the placeholder leaves with the wait
        unit.removeAttribute("aria-busy");
      },
    };
    ask();
    return unit;
  },
};
registerFileViewAction(githubLinkAction);

// ── quote a passage into the composer (the user 2026-08-23, the three-verbs consolidation) ────────
// Selecting text in the viewer seeds the SAME labeled quote chip a VS Code editor highlight does:
// the selection posts in the editorSelection shape to the composer's window — this document's, or
// the shell's chat pane (composerWindow below) — so render.ts's existing handler owns the chip end
// to end (no import cycle — the browseFiles precedent), labeled path:line via quoteSrcLabel. From
// there the flow is the chat's own: type a note (or none), Stage, keep going, send once. This
// REPLACED the viewer's separate review layer — the per-file comment store (romp:fileviewComments),
// the painted marks, and the one-shot Submit that assembled a message — because batching notes for
// one hand-off is exactly what quote chips + ⌘⏎ staging already do, and "comment" now means only
// the transcript's live threads.

// The retired store's data would otherwise sit in localStorage forever on every browser that
// ever commented — sweep it on load.
try { localStorage.removeItem("romp:fileviewComments"); } catch { /* storage may be denied */ }

// Where a quote seed lands (2026-09-03): the composer in THIS document when there is one (the
// chat-hosted viewer posts to its own window, and render.ts's editorSelection handler owns the chip
// end to end); otherwise the SHELL, when this document is framed by one. The feed (the file browser's
// document) hosts the viewer without a composer, and the shell forwards the seed into the chat pane
// (the editorSelection arm in kernel.py's landing shell). Before this, a selection in the feed-hosted
// viewer was dead air. No composer and no shell (a VS Code webview's cross-origin parent throws; a
// standalone pane has none) → null, and the gesture stands down without a fresh read. Presence is the
// DOM id, the Back button's import-free idiom (render.ts's inRompShell keys on the same node).
function composerWindow(): Window | null {
  if (document.getElementById("composer-input")) return window;
  try { if (window.parent !== window && window.parent.document.getElementById("chat-pane")) return window.parent; }
  catch { /* a cross-origin parent (VS Code) is not the romp shell */ }
  return null;
}

export function closeFileView(): void {
  const wrap = document.getElementById("romp-fileview");
  if (!wrap) return;
  if (closeGuard && !closeGuard()) return;   // unsaved edits, and the user chose to keep them
  closeGuard = null;
  editHooks = null;
  gitHooks = null;                                     // a reply landing after the close decorates nothing
  dropMediaUrl();                                      // an image/PDF view's bytes leave with the viewer
  wrap.remove();
  document.body.classList.remove("fileview-open");
}

/** Show `path` in a modal over this pane. Re-opening replaces whatever is up — never stacks. */
export function openFileView(path: string, sid?: string | null): void {
  // The replace path bypasses closeFileView, so it needs the same dirty ask: opening file B over an
  // edited-but-unsaved file A must not silently eat A's buffer.
  if (document.getElementById("romp-fileview") && closeGuard && !closeGuard()) return;
  closeGuard = null;
  editHooks = null;
  gitHooks = null;                                     // the replace path skips closeFileView — same drop
  dropMediaUrl();                                      // …and the old viewer's image bytes (the Reload path)
  document.getElementById("romp-fileview")?.remove();
  // backdrop (the whole overlay carries the id every open/closed check targets) + the ~95% card.
  // The backdrop treatment matches the lightbox: dimmed, click outside the card closes, content
  // clicks don't (the user 2026-08-15: it must be obvious the chat is still right behind it).
  const wrap = el("div");
  wrap.id = "romp-fileview";
  wrap.onclick = (ev) => { if (ev.target === wrap) closeFileView(); };
  const box = el("div", "fileview");
  document.body.classList.add("fileview-open");

  const bar = el("div", "fileview-bar");
  // BACK to the listing (the user 2026-08-24): a file opened FROM the browser overlays it with the
  // listing intact beneath (the one-directional stack above) — closing just the viewer IS the back.
  // The button renders only when a listing is actually underneath; a viewer opened from a path link
  // has nowhere to go back to and shows none. Import-free by design: presence is the DOM id (the
  // browser may not even be loaded in this document).
  if (document.getElementById("romp-filebrowse")) {
    const back = el("button", "fileview-btn fileview-back") as HTMLButtonElement;
    back.type = "button"; back.textContent = "‹ Files"; back.title = "Back to the file listing";
    back.addEventListener("click", () => closeFileView());
    bar.appendChild(back);
  }
  // Directory then basename as TWO elements, because only the directory may be truncated: the filename
  // is what identifies the file, so it never shrinks however deep the path is. (A single text node with
  // the rtl-ellipsis trick would truncate the right end — exactly the wrong half.)
  const name = el("div", "fileview-name");
  name.title = path;                                   // the full path, one hover away
  const cut = path.lastIndexOf("/");
  const dir = el("span", "fileview-dir");
  dir.textContent = cut >= 0 ? path.slice(0, cut + 1) : "";
  const base = el("span", "fileview-base");
  base.textContent = path.slice(cut + 1);
  if (cut >= 0) {
    // The discoverability path into the file BROWSER: the directory half of the title is a click
    // into its listing. Posted to our OWN window — initFileBrowse listens on the same channel the
    // shell relays into, so no import cycle between the two overlays.
    dir.classList.add("fileview-dir-link");
    dir.title = "Browse this file's folder";
    dir.addEventListener("click", () => {
      try { window.postMessage({ romp: "browseFiles", path: path.slice(0, cut) || "/", sid }, "*"); }
      catch { /* messaging our own window cannot really fail */ }
    });
  }
  name.appendChild(dir); name.appendChild(base);
  // The SESSION this file was opened from: a pill in the session's identity colour (the colour its
  // tab wears), "host:" quiet for a remote session (and marked while its link is down). Resolved
  // through the hosting document's registered lookup — no sid, or a sid it cannot name, and there is
  // no chip.
  const owner = sid ? identityOf(sid) : null;
  let sess: HTMLElement | null = null;
  if (owner) {
    sess = el("span", "fileview-sess");
    sess.replaceChildren(...hostNameNodes(owner.name, sid));
    if (owner.color) { sess.style.background = owner.color.bg; sess.style.color = owner.color.fg; }
    sess.title = "Opened from the " + owner.name + " session";
  }
  const acts = el("div", "fileview-acts");

  // ── format toggles (the user 2026-08-09) ── A markdown file opens RENDERED, its Raw form one click
  // away; everything else keeps the code view, whose long lines the Wrap toggle can soft-wrap. Both
  // choices persist per browser (FMT_KEY above). These buttons are built once per open and never
  // re-rendered by kernel pushes — the viewer is a static overlay — so direct listeners are click-safe
  // here, same as Copy path below.
  const fmt = loadFmt();
  let text: string | null = null;             // set once the fetch lands; earlier clicks just save the pref
  let mtimeNs = "";                           // the file's mtime at load, NANOSECONDS AS A STRING —
  //   saveFile's conflict floor (ns because whole seconds let a same-second agent write slip the
  //   guard; a string because ~1.7e18 exceeds JS's safe-integer range and a number would round)
  let isText = false;                         // the kernel's verdicts (text/plain AND faithful UTF-8)
  // ── the media verdicts: a .png used to open as line-numbered mojibake — the fetch pipeline called
  // r.text() on ANY 200. All read from the KERNEL's Content-Type, never a client-side extension
  // re-test (the authoritative-source rule; the kernel derives the mime locally and the relay
  // re-derives it, so the header is a verdict, not an echo).
  let isImage = false;                        // image/* → one <img> at an object URL
  let isPdf = false;                          // application/pdf → the lightbox's iframe treatment
  let isSvgImage = false;                     // image/svg+xml exactly — unlocks the Source toggle
  let svgSource = false;                      // the SVG Source view is up (the highlighted XML)
  let svgText: string | null = null;          // the decoded SVG bytes, read once on first toggle
  let mediaBlob: Blob | null = null;          // the fetched bytes — the Source toggle decodes THESE
  let objUrl: string | null = null;           // this open's object URL (registered as mediaUrlLive)
  // The text the CURRENT view shows: the SVG Source view reads the decoded blob, every other text
  // view reads the fetch pipeline's text. The quote seed's failed-re-read fallback anchors against
  // THIS (a selection in the Source view must find its line in that XML; falling back to `text` —
  // null the whole time media mode is up — would strip every SVG quote's line label).
  const viewText = (): string | null => (svgSource && svgText !== null ? svgText : text);
  let editing = false;
  let dirty = false;
  let eolCRLF = false;                        // the file's dominant line ending — textareas normalize
  //   CRLF→LF on assignment, so an untouched CRLF file would otherwise save with every ending rewritten
  let ta: HTMLTextAreaElement | null = null;   // the FALLBACK surface (and the buffer pre-CodeMirror)
  let cm: { value(): string; focus(): void; destroy(): void } | null = null;   // the CodeMirror handle when mounted
  const bufValue = (): string | null => (cm ? cm.value() : ta ? ta.value : null);   // whichever surface owns the buffer
  const isMd = langFor(path) === "markdown";  // .md/.markdown — the only kind with a Rendered form
  const segBtns: Array<["rendered" | "raw", HTMLButtonElement]> = [];
  if (isMd) {
    for (const mode of ["rendered", "raw"] as const) {
      const b = el("button", "fileview-btn") as HTMLButtonElement;
      b.type = "button";
      b.textContent = mode === "rendered" ? "Rendered" : "Raw";
      b.title = mode === "rendered" ? "The prose the markdown means" : "The file's actual bytes";
      b.addEventListener("click", () => { fmt.md = mode; saveFmt(fmt); renderBody(); });
      segBtns.push([mode, b]);
      acts.appendChild(b);
    }
  }
  // ── the SVG Source toggle ── an SVG is served (and shown) as an image, but it IS also XML worth
  // reading; the toggle swaps in the existing highlighted-code view (langFor maps svg → xml) built
  // from the SAME fetched bytes — no second request. Appears only once an image/svg+xml body landed.
  const srcBtn = el("button", "fileview-btn") as HTMLButtonElement;
  srcBtn.type = "button"; srcBtn.textContent = "Source"; srcBtn.title = "The SVG's XML, highlighted";
  srcBtn.hidden = true;
  srcBtn.addEventListener("click", () => {
    if (svgText === null) {
      if (!mediaBlob) return;
      void mediaBlob.text().then((t) => { svgText = t; svgSource = true; renderBody(); });
      return;
    }
    svgSource = !svgSource;
    renderBody();
  });
  acts.appendChild(srcBtn);

  // ── edit (the raw-mode slice) ── exactly what raw mode can show is what Edit can touch: the
  // button arms only when the kernel served text/plain WITH a Last-Modified to anchor the save's
  // conflict floor (an old remote kernel that mirrors neither gets no Edit rather than an unguarded
  // one). Markdown edits from its Raw view — what you edit is what raw shows.
  const editBtn = el("button", "fileview-btn") as HTMLButtonElement;
  editBtn.type = "button"; editBtn.textContent = "Edit"; editBtn.title = "Edit this file in place";
  editBtn.hidden = true;
  // The consent gate (the user 2026-08-22): editing is a kernel-side opt-in the SAVE ROUTE enforces —
  // this popup is where the one yes happens, and it broadcasts through the settings mesh so every
  // attached kernel's save route opens together (setFileEditing rides KERNEL_SETTING). The flag is
  // read fresh per click, never cached: another machine's gear may have flipped it meanwhile. A
  // decline changes nothing and is asked again next time — consent latches only on yes. If /version
  // is unreachable the popup still asks: the kernel-side gate refuses regardless, so the worst a
  // wrongly-granted yes here can do is draw one refused save with its plain-words error.
  async function editingAllowed(): Promise<boolean> {
    let on = false;
    try {
      const v = await (await fetch(kernelUrl("/version"), { cache: "no-store" })).json();
      on = !!v.fileEditing;
      gclock.learnAll(v.settingsGt);   // the same read teaches the clock every store's current stamp
    } catch { /* ask below */ }
    if (on) return true;
    if (!window.confirm(
      "Allow editing files from the dashboard?\n\n" +
      "Saves write straight to disk on the file's machine — and this applies on every machine " +
      "connected here. A session working in that folder is told when you edit under it.\n\n" +
      "You can turn this off later in the settings gear.")) return false;
    // gt = the consent's own click, stamped through the gesture clock (above every stamp the read
    // above reported): federation queues this per host across a down socket, and the kernel orders
    // applies by the stamp — a flush hours later must not outrank a newer gesture
    post({ type: "setFileEditing", enabled: true, gt: gclock.stamp("file-editing") });
    return true;
  }
  editBtn.addEventListener("click", () => {
    void editingAllowed().then((ok) => {
      if (!ok) return;
      if (isMd && fmt.md === "rendered") { fmt.md = "raw"; saveFmt(fmt); }
      enterEdit();
    });
  });
  const saveBtn = el("button", "fileview-btn") as HTMLButtonElement;
  saveBtn.type = "button"; saveBtn.textContent = "Save"; saveBtn.title = "Write the file (Ctrl/Cmd+S)";
  saveBtn.hidden = true;
  saveBtn.addEventListener("click", () => doSave());
  const cancelBtn = el("button", "fileview-btn") as HTMLButtonElement;
  cancelBtn.type = "button"; cancelBtn.textContent = "Cancel"; cancelBtn.title = "Leave edit mode";
  cancelBtn.hidden = true;
  cancelBtn.addEventListener("click", () => { if (confirmDiscard()) exitEdit(); });
  acts.appendChild(editBtn); acts.appendChild(saveBtn); acts.appendChild(cancelBtn);
  // Registered actions render after the built-ins — the registry walk is the ONE place row
  // conventions live (see registerFileViewAction above). The GitHub link mounts here.
  for (const a of fileViewActions) {
    const n = a.mount({ path, sid: sid || null });
    if (n) acts.appendChild(n);
  }

  // ── download (the user 2026-08-09) ── Any linked file can be SAVED, including everything the pane
  // cannot show: the kernel's ?download=1 serves anything on disk (the rationale lives with
  // _file_download in kernel.py). Same-origin and cookie-authed like the view fetch, and
  // federation-aware for free — fileUrl already routes a remote session's file through the relay.
  const dlUrl = fileUrl(path, sid) + "&download=1";
  const dl = el("button", "fileview-btn") as HTMLButtonElement;
  dl.type = "button"; dl.textContent = "Download"; dl.title = "Save this file to your device";
  dl.addEventListener("click", () => startDownload(dlUrl, dl));
  acts.appendChild(dl);

  const copy = el("button", "fileview-btn") as HTMLButtonElement;
  copy.type = "button"; copy.textContent = "Copy path"; copy.title = path;
  copy.addEventListener("click", () => {
    navigator.clipboard?.writeText(path).then(
      () => { copy.textContent = "Copied"; setTimeout(() => { copy.textContent = "Copy path"; }, 1200); },
      () => { copy.textContent = "Copy failed"; });
  });
  const close = el("button", "fileview-btn fileview-close") as HTMLButtonElement;
  close.type = "button"; close.textContent = "✕"; close.title = "Close (Esc)";
  close.setAttribute("aria-label", "Close the file viewer");
  close.addEventListener("click", closeFileView);
  acts.appendChild(copy); acts.appendChild(close);
  bar.appendChild(name); if (sess) bar.appendChild(sess); bar.appendChild(acts);

  const body = el("div", "fileview-body");
  // Per the loading-state rule the first thing up is the romp loader, not a blank pane — a file coming
  // over an ssh tunnel to a phone is a real wait.
  const load = el("div", "fileview-load");
  load.innerHTML = '<img src="/media/romp-swirl-glyph.svg" alt=""><span>romp</span>'
    + '<i class="fileview-dot"></i><i class="fileview-dot"></i><i class="fileview-dot"></i>';
  body.appendChild(load);

  box.appendChild(bar); box.appendChild(body);
  wrap.appendChild(box);
  document.body.appendChild(wrap);

  // A 200 whose bytes will not DECODE — a zero-byte file, a mid-write/truncated image — fires the
  // img's error event and used to leave the browser's mute broken-image glyph: no reason, no way
  // out. This is the 413/415 pane idiom instead: plain words naming what happened, the path, and
  // the Download the view could not be. Keyed on the img's own error event, the exact deciding
  // signal (never a timer, never a byte sniff). The PDF iframe has no equivalent failure event —
  // the browser's viewer owns that surface and reports inside it — so this covers images only,
  // deliberately.
  const imgFailed = () => {
    if (!wrap.isConnected) return;              // settled after a close/replace — paint nothing
    const why = el("div", "fileview-err");
    why.textContent = "this image failed to decode — it may be mid-write or truncated";
    const hint = el("div", "fileview-err-hint");
    hint.textContent = path;
    why.appendChild(hint);
    const offer = el("button", "fileview-btn fileview-err-dl") as HTMLButtonElement;
    offer.type = "button"; offer.textContent = "Download";
    offer.title = "Save this file to your device";
    offer.addEventListener("click", () => startDownload(dlUrl, offer));
    why.appendChild(offer);
    body.replaceChildren(why);
  };

  // Chooses the body for the current prefs and syncs the buttons. The pressed state flips SYNCHRONOUSLY
  // in the click handler — the immediate acknowledgement ui/CLAUDE.md requires — and so does the content
  // swap, since the text is already in memory.
  const renderBody = () => {
    const rendered = isMd && fmt.md === "rendered";
    for (const [mode, b] of segBtns) {
      const on = fmt.md === mode;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", String(on));
      b.hidden = editing;                       // format choices leave with edit mode; Save/Cancel own the bar
    }
    editBtn.hidden = editing || text === null || !isText || !mtimeNs;
    saveBtn.hidden = !editing;
    cancelBtn.hidden = !editing;
    if (isImage || isPdf) {
      // Media mode. The quote gesture gates off the RENDERED views only: a chip's label anchors to
      // text and an <img>/iframe body has none (affordance honesty: no real target, no affordance —
      // the mouseup seed below gates the same way). The SVG SOURCE view is a TEXT view — codeBlock
      // output, real text nodes — so selections there quote like any text view (a blanket media
      // gate would make an .svg's XML unquotable). Edit is already off through the isText arm
      // above; the md segs cannot exist (an .md is never served image/*); Download, Copy path, the
      // GitHub link, ✕ and the dir-link all keep working — none of them needs the text.
      srcBtn.hidden = !(isSvgImage && objUrl !== null);
      srcBtn.classList.toggle("on", svgSource);
      srcBtn.setAttribute("aria-pressed", String(svgSource));
      if (objUrl === null) return;            // the romp loader holds the body until the bytes land
      if (svgSource && svgText !== null) {
        body.replaceChildren(codeBlock(svgText, path, true));   // long lines always soft-wrap (the user 2026-08-24)
        return;
      }
      body.replaceChildren(isPdf ? pdfBlock(objUrl, path) : imgBlock(objUrl, path, imgFailed));
      return;
    }
    if (text === null || editing) return;   // loading, or the textarea owns the body right now
    body.replaceChildren(rendered ? mdBlock(text) : codeBlock(text, path, true));   // long lines always soft-wrap (the user 2026-08-24)
  };

  // Selection → labeled quote chip (the user 2026-08-23): mouseup is the gesture's settle point.
  // The chip behaves exactly like a VS Code editor highlight's — one live source-labeled chip,
  // replaced by the next selection, persisting until sent, staged, or ✕'d — because it IS that
  // chip: render.ts's editorSelection handler seeds it. The post carries THIS viewer's sid, so the
  // chip lands in the session the file was opened FOR even if the active tab changed while the
  // modal was up (the 2026-08-19 routing rule: the gesture's session, never activeId-at-gesture).
  let seedSeq = 0;                                 // last gesture wins if two fresh reads race
  box.addEventListener("mouseup", () => {
    if (editing) return;   // CodeMirror selections are edit gestures, not quotes
    // No chip target reachable → no seed (the no-sink gating): the post would be dead air and the
    // label's fresh read dead work. The target is this document's composer (the chat-hosted viewer)
    // or, from a pane without one — the feed — the shell, which forwards the seed into the chat pane
    // (composerWindow above).
    const seedTarget = composerWindow();
    if (!seedTarget) return;
    // RENDERED media has no honest text to quote — an <img>/iframe body owns its own selection
    // surface; the SVG SOURCE view is a real text view and quotes like any other (renderBody's
    // media gate, same rule).
    if ((isImage || isPdf) && !(svgSource && svgText !== null)) return;
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.anchorNode || !box.contains(sel.anchorNode)) return;
    const picked = sel.toString().trim();
    if (!picked) return;
    // The label's line is minted NOW, not at open: agents edit these same trees, so the open-time
    // snapshot's numbering may have quietly moved. Anchor against a fresh read; a FAILED re-read
    // falls back to the snapshot rather than fabricating drift nobody observed (the old Submit
    // guard's rule) — viewText, not text, because the SVG Source view's snapshot is the decoded
    // blob and `text` stays null in media mode. quoteSrcLabel itself degrades to the bare path
    // when the passage cannot be honestly found in whichever bytes it gets.
    const seq = ++seedSeq;
    fetch(fileUrl(path, sid), { cache: "no-store" })
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .catch(() => viewText())
      .then((doc) => {
        if (seq !== seedSeq) return;
        try { seedTarget.postMessage({ type: "editorSelection", text: picked, sid: sid || undefined, src: quoteSrcLabel(path, doc, picked) }, "*"); }
        catch { /* messaging our own window or the same-origin shell cannot really fail */ }
      });
  });

  // ── edit mode (the raw-mode slice) ── a plain textarea holding the raw bytes: an embedded editor
  // is a different project, and a textarea that keeps your changes beats a half-editor. The kernel's
  // mtime floor does the real safety work (agents edit these same trees — see _save_file).
  const confirmDiscard = (): boolean =>
    !editing || !dirty || window.confirm("Discard unsaved changes to " + path.slice(cut + 1) + "?");
  closeGuard = confirmDiscard;
  const norm = (s: string): string => s.replace(/\r\n/g, "\n");   // the textarea's own view of any text
  // The editing substrate is CodeMirror 6 (the user 2026-08-22), living in its OWN lazily-loaded
  // bundle so people who never edit download nothing (the main bundles import none of it — the
  // contract is the window global the chunk registers). The URL derives from the page's own running
  // bundle script — same directory, same ?v= cache token — so it resolves on the kernel pages and
  // the VS Code webview alike, and a rebuilt kernel always serves a matching chunk. A failed load
  // rejects ONCE and clears the latch so a later attempt retries fresh.
  let edChunk: Promise<{ mount: (host: HTMLElement, opts: object) => { value(): string; focus(): void; destroy(): void } }> | null = null;
  const editorChunk = () => edChunk || (edChunk = new Promise((res, rej) => {
    const w = window as any;
    if (w.__rompEditor) return res(w.__rompEditor);
    const self = Array.from(document.querySelectorAll("script[src]"))
      .map((n) => (n as HTMLScriptElement).src).find((u) => /\/(render|feed)\.js/.test(u));
    if (!self) return rej(new Error("no bundle script tag to derive the editor chunk URL from"));
    const sc = document.createElement("script");
    sc.src = self.replace(/\/(render|feed)\.js/, "/editor-chunk.js");
    sc.onload = () => { const e = (window as any).__rompEditor; e ? res(e) : rej(new Error("editor chunk loaded but did not register")); };
    sc.onerror = () => { edChunk = null; rej(new Error("the editor bundle failed to load")); };
    document.head.appendChild(sc);
  }));
  const enterFallback = () => {                 // the plain textarea: LOUD fallback, never a silent one
    ta = el("textarea", "fileview-editor") as HTMLTextAreaElement;
    ta.value = text!;                           // the browser normalizes CRLF→LF on assignment…
    ta.spellcheck = false;
    ta.addEventListener("input", () => { dirty = ta!.value !== norm(text!); });   // …so compare normalized
    ta.addEventListener("keydown", (e) => {     // the editor's own save chord; Esc falls through to onKey
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); doSave(); }
    });
    body.replaceChildren(ta);
    ta.focus();
  };
  let editSeq = 0;                              // stale chunk resolutions (edit left before load) no-op
  const enterEdit = () => {
    if (text === null || editing) return;
    editing = true; dirty = false;
    eolCRLF = /\r\n/.test(text);
    renderBody();
    // per the loading-state rule the chunk wait shows the romp loader, not a blank body
    const wait = el("div", "fileview-load");
    wait.innerHTML = '<img src="/media/romp-swirl-glyph.svg" alt=""><span>romp</span>'
      + '<i class="fileview-dot"></i><i class="fileview-dot"></i><i class="fileview-dot"></i>';
    body.replaceChildren(wait);
    const my = ++editSeq;
    editorChunk().then((ed) => {
      if (!editing || my !== editSeq) return;   // edit mode left (or re-entered) while the chunk loaded
      const host = el("div", "fileview-cm");
      body.replaceChildren(host);
      cm = ed.mount(host, {
        text: norm(text!), ext: path.slice(path.lastIndexOf(".") + 1),
        onChange: () => { dirty = cm!.value() !== norm(text!); },
        onSave: () => doSave(),
      });
      cm.focus();
    }).catch((err) => {
      if (!editing || my !== editSeq) return;
      document.getElementById("fileview-save-err")?.remove();
      const bar2 = el("div", "fileview-err");   // loud: say the editor is degraded, never pretend
      bar2.id = "fileview-save-err";
      bar2.textContent = String(err && (err as Error).message || err) + " — editing in the plain fallback editor.";
      enterFallback();
      body.prepend(bar2);
    });
  };
  const exitEdit = () => {
    editing = false; dirty = false; ta = null;
    cm?.destroy(); cm = null;
    editHooks = null;                           // a cancelled save's late ack must not touch a NEW session
    saveBtn.disabled = false; saveBtn.textContent = "Save";
    renderBody();
  };
  const doSave = () => {
    const buf = bufValue();
    if (!editing || buf === null || saveBtn.disabled) return;
    if (!dirty) { exitEdit(); return; }         // nothing changed — leaving is the honest ack
    saveBtn.disabled = true; saveBtn.textContent = "Saving…";   // acknowledge before the round-trip
    // restore the file's own line endings — an untouched CRLF file must round-trip byte-identical
    const content = eolCRLF ? buf.replace(/\n/g, "\r\n") : buf;
    editHooks = {
      reqId: ++saveSeq,
      saved: (mtNs) => {
        mtimeNs = mtNs;
        text = content;
        // Keystrokes typed DURING the round-trip survive the ack (the review's in-flight-typing
        // finding): if the live buffer moved past the snapshot we saved, stay in edit mode with the
        // new baseline — never re-render over what the user is still typing.
        if (bufValue() !== null && bufValue() !== norm(content)) {
          dirty = true;
          saveBtn.disabled = false; saveBtn.textContent = "Save";
          return;
        }
        exitEdit();                             // re-renders the highlighted view from the saved bytes
      },
      failed: (err) => {
        saveBtn.disabled = false; saveBtn.textContent = "Save";
        // Loud, in place, and the BUFFER SURVIVES: the error bar sits above the textarea. A conflict
        // (the disk moved — an agent wrote it) offers Reload, which re-opens fresh — behind the same
        // discard confirm, so the user's edits are never thrown away silently (never a merge UI).
        document.getElementById("fileview-save-err")?.remove();
        const bar2 = el("div", "fileview-err");
        bar2.id = "fileview-save-err";
        bar2.textContent = err;
        if (/changed on disk/.test(err)) {
          const re = el("button", "fileview-btn fileview-err-dl") as HTMLButtonElement;
          re.type = "button"; re.textContent = "Reload file";
          re.title = "Fetch the file as it is now (asks before discarding your edits)";
          re.addEventListener("click", () => {
            if (!confirmDiscard()) return;
            dirty = false;                      // confirmed once — the replace guard must not ask twice
            openFileView(path, sid);
          });
          bar2.appendChild(re);
        }
        body.prepend(bar2);
      },
    };
    post({ type: "saveFile", path, sid: sid || undefined, content, baseMtimeNs: mtimeNs, reqId: saveSeq });
  };
  renderBody();   // buttons take their initial state now; the loader stays up until the fetch lands

  const onKey = (e: KeyboardEvent) => {
    if (e.key !== "Escape" || !document.getElementById("romp-fileview")) return;
    e.preventDefault();
    if (editing) {                              // Escape peels edit mode first, never the whole viewer
      if (confirmDiscard()) exitEdit();
      return;
    }
    closeFileView();
    document.removeEventListener("keydown", onKey);
  };
  document.addEventListener("keydown", onKey);

  fetch(fileUrl(path, sid), { cache: "no-store" }).then((r): Promise<string | Blob> => {
    // Every failure says WHY, in the pane, rather than leaving a blank one: the kernel distinguishes
    // "not a type I serve" from "too big" from "not text after all", and that is exactly what the
    // person who clicked needs to know (a 413 names the size and the cap). The status rides along so
    // the catch below can tell "the file is there but I can't show it" from "there is no file".
    if (!r.ok) return r.text().then((t) => {
      throw Object.assign(new Error(t || ("HTTP " + r.status)), { status: r.status });
    });
    // Edit arms off the KERNEL's verdicts, never a client guess: text/plain AND a faithful UTF-8
    // round-trip (the latin-1 fallback re-decodes non-UTF-8 files — saving that back would rewrite
    // every non-ASCII byte, the review's executed repro), anchored by the ns mtime header (an old
    // kernel that sends neither simply gets no Edit button).
    isText = (r.headers.get("Content-Type") || "").startsWith("text/plain")
      && r.headers.get("X-Romp-Text-Utf8") !== "0";
    mtimeNs = r.headers.get("X-Romp-Mtime-Ns") || "";
    // Media branches on the SAME kernel verdict (an image 200 wears image/* and no X-Romp-Text-Utf8 —
    // tests/test_kernel_preview.py pins that contract server-side). The bytes below are the one fetch
    // either way: media takes them as a blob for an object URL, never a second request.
    const ct = r.headers.get("Content-Type") || "";
    isImage = ct.startsWith("image/");
    isPdf = ct.startsWith("application/pdf");
    isSvgImage = ct === "image/svg+xml";
    return isImage || isPdf ? r.blob() : r.text();
  }).then((t) => {
    if (!document.getElementById("romp-fileview")) return;    // closed while it was in flight
    if (t instanceof Blob) {
      // Minted only now — a viewer closed (above) or REPLACED mid-flight creates nothing to leak,
      // and never clobbers the new open's mediaUrlLive registration.
      if (!wrap.isConnected) return;
      mediaBlob = t;
      objUrl = URL.createObjectURL(t);
      mediaUrlLive = objUrl;                   // registered so close/replace can revoke (dropMediaUrl)
      renderBody();
      return;
    }
    text = t;
    renderBody();
  }).catch((err) => {
    if (!document.getElementById("romp-fileview")) return;
    const why = el("div", "fileview-err");
    const msg = String(err && err.message || err);
    why.textContent = msg;
    if (!msg.includes(path)) {
      // The kernel's 404/413/415 bodies name the RESOLVED path themselves now — the hint exists for
      // errors that don't (a network failure, an old kernel), not to say the same path twice.
      const hint = el("div", "fileview-err-hint");
      hint.textContent = path;
      why.appendChild(hint);
    }
    // A refusal-to-RENDER is not a dead end (ui/CLAUDE.md): when the file exists, the kernel's own
    // words are followed by the way out — the download the view could not be. A 404 stays offerless,
    // because offering to download a file that is not there would be a lie.
    if (offersDownload((err as { status?: number }).status)) {
      const offer = el("button", "fileview-btn fileview-err-dl") as HTMLButtonElement;
      offer.type = "button"; offer.textContent = "Download";
      offer.title = "Save this file to your device";
      offer.addEventListener("click", () => startDownload(dlUrl, offer));
      why.appendChild(offer);
    }
    body.replaceChildren(why);
  });
}

// Which fetch failures still deserve a Download offer? Exactly the ones that mean the file EXISTS:
// 413 (too large to render) and 415 (on disk but not viewable — a .zip, a binary named like text).
// A 404 is genuinely missing, and gets nothing.
function offersDownload(status: number | undefined): boolean {
  return status === 413 || status === 415;
}

// Kick the browser's downloader at `url` without touching the pane: a clicked <a download> starts a
// same-origin, cookie-authed request the BROWSER owns (its progress UI, its save location), and since
// the kernel answers with Content-Disposition: attachment the page never navigates — the viewer, the
// feed behind it, and the scroll position all stay put. The button acknowledges the click itself
// (ui/CLAUDE.md), because the browser's download UI can take a beat to appear over a slow tunnel.
function startDownload(url: string, btn: HTMLButtonElement): void {
  const a = document.createElement("a");
  a.href = url;
  a.download = "";               // a hint; the kernel's attachment disposition is what actually decides
  document.body.appendChild(a);
  a.click();
  a.remove();
  const was = btn.textContent;
  btn.textContent = "Downloading…";
  setTimeout(() => { btn.textContent = was; }, 1500);
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Wrap mode's numbering. The flat sibling gutter cannot survive soft-wrapping — one logical line becomes
// several visual lines and every number below it drifts — so wrap mode RESTRUCTURES instead of shipping a
// misaligned column: each logical line is its own row (.fv-cl) whose number is a CSS counter in ::before
// (the chat's .cl/.ct treatment, styles.css), so the numbers stay glued to their lines however tall a
// wrapped line grows, and being ::before content they still never copy with the code. hljs spans can
// cross newlines, so each row re-opens the spans the previous row left unclosed and closes its own —
// render.ts's wrapCodeLines balance walk.
function wrapNumberedHtml(html: string): string {
  const lines = html.split("\n");
  if (lines.length && lines[lines.length - 1] === "") lines.pop();   // a trailing newline is not a line
  let open: string[] = [];
  return lines.map((ln) => {
    const prefix = open.join("");
    const re = /<span[^>]*>|<\/span>/g; let m; const stack = open.slice();
    while ((m = re.exec(ln))) { if (m[0] === "</span>") stack.pop(); else stack.push(m[0]); }
    const suffix = "</span>".repeat(Math.max(0, stack.length));
    open = stack;
    return `<span class="fv-cl"><span class="fv-ct">${prefix}${ln}${suffix}</span></span>`;
  }).join("");
}

// Line-numbered <pre>. In the default (no-wrap) view the gutter is a sibling column rather than text in
// the same <pre>, so selecting the code and copying it does NOT drag the line numbers along with it; the
// wrap view keeps that copy-safety a different way (see wrapNumberedHtml above).
function codeBlock(text: string, path: string, wrapLines: boolean): HTMLElement {
  const wrap = el("div", "fileview-code");
  const lines = text.split("\n");
  if (lines.length && lines[lines.length - 1] === "") lines.pop();   // a trailing newline is not a line
  const lang = langFor(path);
  let hl: string | null = null;
  if (lang) {
    try { hl = hljs.highlight(text, { language: lang }).value; }
    catch { hl = null; }                               // a broken grammar must never cost the content
  }
  const pre = el("pre", "fileview-pre");
  const code = el("code", "hljs");
  if (wrapLines) {
    pre.classList.add("fileview-wrap");
    code.innerHTML = wrapNumberedHtml(hl !== null ? hl : escapeHtml(text));
    pre.appendChild(code);
    wrap.appendChild(pre);
    return wrap;
  }
  const gutter = el("div", "fileview-gutter");
  gutter.textContent = lines.map((_, i) => String(i + 1)).join("\n");
  gutter.setAttribute("aria-hidden", "true");
  if (hl !== null) code.innerHTML = hl; else code.textContent = text;
  pre.appendChild(code);
  wrap.appendChild(gutter); wrap.appendChild(pre);
  return wrap;
}

// Markdown rendered as the prose it means (the user 2026-08-09: Rendered is the default, Raw one click
// away). The file is arbitrary bytes off a disk and marked emits raw HTML verbatim, so — exactly like the
// chat's md() in render.ts — the output goes through DOMPurify before it ever reaches .innerHTML: an
// <img onerror> or a javascript: href in a README must never run in the dashboard.
function mdBlock(text: string): HTMLElement {
  const box = el("div", "fileview-md");
  try {
    const dirty = marked.parse(text) as string;
    // html + svg, in lockstep with the chat's md(): KaTeX draws stretchy glyphs (\sqrt radicals,
    // wide accents) as inline <svg> even in html output, and the html-only profile ate them.
    box.innerHTML = DOMPurify.sanitize(dirty, { USE_PROFILES: { html: true, svg: true }, ADD_DATA_URI_TAGS: ["img"] });
  } catch {
    box.textContent = text;                            // a marked bug must never cost the content
  }
  // Links open a NEW tab: the viewer lives inside the chat pane's document, and letting a README link
  // navigate it away would silently eat the chat until a reload.
  box.querySelectorAll("a[href]").forEach((a) => {
    (a as HTMLAnchorElement).target = "_blank";
    (a as HTMLAnchorElement).rel = "noopener";
  });
  // Fenced blocks: highlight only a language the fence NAMES and this bundle registers — the same
  // no-guessing rule as langFor; an unnamed block stays plain rather than being painted at random.
  box.querySelectorAll("pre code").forEach((node) => {
    const codeEl = node as HTMLElement;
    const lang = (codeEl.className.match(/language-([\w-]+)/) || [])[1];
    if (!lang || !hljs.getLanguage(lang)) return;
    try {
      codeEl.innerHTML = hljs.highlight(codeEl.textContent || "", { language: lang }).value;
      codeEl.classList.add("hljs");
    } catch { /* leave plain */ }
  });
  return box;
}

// The image body: ONE <img> aimed at the object URL — never innerHTML, never an iframe. That is the
// whole SVG-safety story (an <img> never runs SVG scripts — the same surface the kernel's preview
// comments and the relay's local type re-derivation rely on), and for every other image it is simply
// the right element. Centered and capped like the lightbox's image (.romp-lightbox-img), so a huge
// plot fits the card and a small icon renders at its own size. Bytes that will not decode fire the
// img's error event into onDecodeFail (armed before src, so no event can slip past), where the open
// viewer swaps in its failure pane — the caller owns the pane; this stays a pure element builder.
function imgBlock(objUrl: string, path: string, onDecodeFail: () => void): HTMLElement {
  const box = el("div", "fileview-imgbox");
  const img = el("img", "fileview-img") as HTMLImageElement;
  img.addEventListener("error", onDecodeFail, { once: true });
  img.src = objUrl;
  img.alt = path;
  box.appendChild(img);
  return box;
}

// The PDF body mirrors the lightbox's treatment exactly (openLightbox's pdf arm, preview.ts): the
// browser's own viewer in a PLAIN iframe — className, src, title, nothing more — aimed at the
// already-fetched bytes instead of a second network fetch.
function pdfBlock(objUrl: string, path: string): HTMLElement {
  const frame = el("iframe", "fileview-frame") as HTMLIFrameElement;
  frame.src = objUrl;
  frame.title = path;
  return frame;
}

/** Bind the pane's WS poster and route saveFile + fileGitLink replies back to the open viewer.
 *  Called once, from the pane's boot (render.ts and feed.ts today — either document, one mechanism);
 *  every reply is reqId-guarded so one landing after a close or a replace-open touches nothing. The
 *  viewFile branch honors a shell's relay of a chat file-link click — nothing sends it since the
 *  viewer moved into the chat document, but a not-yet-reloaded shell page still might, and honoring
 *  it costs nothing. */
export function initFileView(poster: (m: Record<string, unknown>) => void): void {
  post = poster;
  window.addEventListener("message", (e: MessageEvent) => {
    const m = e.data;
    if (!m) return;
    if (m.romp === "viewFile" && typeof m.path === "string" && m.path) {
      openFileView(m.path, typeof m.sid === "string" ? m.sid : null);
    } else if (m.type === "fileGitLink" && gitHooks && m.reqId === gitHooks.reqId) {
      const h = gitHooks; gitHooks = null;
      h.apply(String(m.url || ""), String(m.reason || ""));
    } else if (m.type === "fileSaved" && editHooks && m.reqId === editHooks.reqId) {
      const h = editHooks; editHooks = null;
      h.saved(String(m.mtimeNs || ""));
    } else if (m.type === "fileSaveFailed" && editHooks && m.reqId === editHooks.reqId) {
      const h = editHooks; editHooks = null;
      h.failed(String(m.error || "the save failed"));
    } else if (m.type === "warn" && editHooks) {
      // A federation drop (the session's host unreachable) answers a saveFile with a warn instead
      // of a reply — the feed page renders no toasts, so without this the button spins forever
      // (the same hole the browse overlay closed for listDir).
      const h = editHooks; editHooks = null;
      h.failed(String(m.text || "the session's host is not answering — the save was not sent"));
    }
  });
  // A socket drop mid-save loses the ack, and the frame itself may or may not have reached the
  // kernel — the honest answer is to say exactly that and re-arm Save: a save that DID land will
  // refuse the retry as "changed on disk", and Reload resolves it from there. Keying on the shim's
  // own drop event (not a timer) is the house rule; the browse overlay set the precedent.
  window.addEventListener("romp:wsdown", () => {
    if (!editHooks) return;
    const h = editHooks; editHooks = null;
    h.failed("the connection dropped mid-save — it may or may not have landed; "
      + "Save again once the connection returns (a save that DID land will refuse as changed-on-disk)");
  });
  // A drop while the GitHub ask is out loses its reply (the frame went; nothing re-sends it), and the
  // placeholder would pulse for the rest of the open. The socket's RETURN is the event that re-asks —
  // same reqId, so a first reply that was merely late and the second are one answer (the browse
  // overlay's re-ask on romp:wsup is the precedent). A read-only query: asking twice costs nothing.
  window.addEventListener("romp:wsup", () => { if (gitHooks) gitHooks.ask(); });
}
