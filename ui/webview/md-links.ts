// Pure helpers behind "a markdown link opens in the file viewer" (the user 2026-09-06): a chat message
// linking `https://<this dashboard>/figs/run-1/evidence.md` used to open the RAW text in a new tab; it
// presents in the in-pane viewer now, rendered, with its figures resolved against the document. This
// module is string → string only — no DOM, no fetch — so it executes under `node --test` (the DOM
// wiring in render.ts / file-view.ts is pinned at the source, as every viewer test is).
//
// Two rules the helpers encode, both deliberate:
//   • SAME ORIGIN ONLY. The viewer fetches the URL from the browser, and a cross-origin fetch is a
//     CORS guess — sometimes it works, mostly it does not, and a try-then-fall-back would flash the
//     loader before opening the tab anyway. A `.md` on another origin (a GitHub blob page whose path
//     merely ends in .md) keeps today's new-tab behaviour exactly. No kernel proxy either: the repo
//     has kept the kernel's /file relay a preview relay, never a general URL fetch (_remote_file's
//     docstring), and this feature adds no kernel surface at all.
//   • A RENDERED DOCUMENT'S RELATIVE REFERENCES RESOLVE AGAINST THE DOCUMENT, not the page. marked
//     leaves `![fig](fig.png)` as `<img src="fig.png">`, which the browser would fetch from the
//     dashboard's root — wrong for a URL document (its own directory) and wrong for a local file
//     (the kernel's /file route for the sibling on disk). Each mode has its own resolver below.

/** Does `href` name a markdown file on THIS page's origin — the one case the viewer intercepts?
 *  http/https only, same origin as `pageOrigin`, pathname ending .md/.markdown (case-insensitive,
 *  ?query and #fragment tolerated). Anything else — another origin, a relative href, mailto:,
 *  vscode://, file://, `.md.png`, malformed input — is false, and nothing here ever throws. */
export function isMarkdownUrl(href: string, pageOrigin: string): boolean {
  if (typeof href !== "string" || typeof pageOrigin !== "string" || !href || !pageOrigin) return false;
  let u: URL, origin: string;
  try { u = new URL(href); } catch { return false; }        // relative or malformed — not an absolute URL
  // location.origin is already normalised (lower-case host, default port dropped); parsing the page
  // origin the same way keeps a hand-written or upper-cased caller value comparable. "null" (an
  // opaque origin — a sandboxed webview) is not a URL and can match nothing.
  try { origin = new URL(pageOrigin).origin; } catch { return false; }
  if (u.protocol !== "http:" && u.protocol !== "https:") return false;
  if (u.origin !== origin) return false;
  return /\.(md|markdown)$/i.test(u.pathname);
}

const SCHEME_RE = /^[a-z][a-z0-9+.-]*:/i;                    // the same shape the chat's anchor delegate keys on

/** Resolve a relative `src`/`href` found INSIDE a rendered document against the document's URL
 *  (`new URL(ref, base).href`). Returned unchanged: a ref that already carries a scheme (http:,
 *  data:, blob:, mailto:, javascript: — DOMPurify has already dropped the dangerous ones), a bare
 *  `#fragment` (in-document), an empty ref, or any ref when `base` is not itself a URL. Root-relative
 *  (`/x.png`) resolves against the base's origin, `../x.png` walks the base's directory. */
export function resolveDocRelative(ref: string, base: string): string {
  if (typeof ref !== "string" || !ref) return ref;
  if (ref.startsWith("#")) return ref;
  if (SCHEME_RE.test(ref)) return ref;
  if (typeof base !== "string" || !base) return ref;
  try { return new URL(ref, base).href; } catch { return ref; }
}

/** Join a relative reference found in a LOCAL document (`docPath` on the session's disk) into the
 *  sibling's path: `./`, `../`, doubled slashes and a trailing `#fragment` are normalised away and a
 *  percent-encoded name (`my%20notes.md`) is decoded, because the link is a URL by convention but the
 *  kernel wants a path. An absolute (`/…`) or home-anchored (`~…`) ref, a ref with a scheme, or an
 *  empty ref comes back untouched — there is nothing to join. */
export function joinDocPath(docPath: string, rel: string): string {
  if (typeof rel !== "string" || !rel) return rel;
  if (SCHEME_RE.test(rel)) return rel;
  let r = rel.replace(/#.*$/, "");                           // the kernel wants a path; the fragment rides separately (data-frag)
  try { r = decodeURIComponent(r); } catch { /* a stray % — keep the bytes as written */ }
  if (!r) return rel;
  if (r.startsWith("/") || r.startsWith("~")) return r;
  const dir = typeof docPath === "string" ? docPath.slice(0, docPath.lastIndexOf("/") + 1) : "";
  const out: string[] = [];
  const segs = (dir + r).split("/");
  for (let i = 0; i < segs.length; i++) {
    const s = segs[i];
    if (s === "" && i > 0) continue;                        // `a//b`, or a trailing slash
    if (s === ".") continue;
    if (s === "..") {
      const last = out.length ? out[out.length - 1] : undefined;
      if (last === undefined || last === "..") out.push(".."); // above a relative doc's start: keep climbing
      else if (last !== "") out.pop();                         // root's parent is root
      continue;
    }
    out.push(s);
  }
  const joined = out.join("/");
  return joined || (dir.startsWith("/") ? "/" : ".");
}

/** A GitHub-style slug for a heading's text, so a document's own `[top](#evidence)` has an id to land
 *  on (marked 12 emits none): lower-case; letters of any script, digits, spaces and hyphens kept,
 *  everything else dropped; whitespace runs become one hyphen. Empty → "section", a stable fallback so
 *  every heading gets an id. Idempotent — a slug slugs to itself — which is what lets a hand-written
 *  `#my-section` fragment find the same id the heading "My Section" was given. */
export function headingSlug(text: string): string {
  const s = String(text ?? "").toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, "").trim().replace(/\s+/g, "-");
  return s || "section";
}

/** Make heading slugs unique in document order, GitHub's way: the first `x` stays `x`, later ones
 *  become `x-1`, `x-2`, … — skipping a suffix an earlier heading already holds as its own slug.
 *  Amortised linear: each base keeps the NEXT suffix to try, so a duplicate never rescans the
 *  suffixes already handed out (restarting at 1 per duplicate was quadratic — 12,000 repeated
 *  headings in an 84 KB document took 11 s to render and froze the page, ✕ included). An explicitly
 *  numbered heading that already holds `base-N` just advances that base's counter past it. */
export function uniqueSlugs(slugs: string[]): string[] {
  const used = new Set<string>();
  const next = new Map<string, number>();
  return slugs.map((s) => {
    let out = s;
    if (used.has(out)) {
      let n = next.get(s) ?? 1;
      for (out = s + "-" + n; used.has(out); out = s + "-" + ++n) { /* held by an explicit heading — keep advancing */ }
      next.set(s, n + 1);
    }
    used.add(out);
    return out;
  });
}

/** The title-bar halves for a URL document: `host/dir/` (dimmed in the bar, like a local path's
 *  directory) and the basename, percent-decoded for reading. A non-URL yields the whole string as
 *  the basename and no directory, so a bar can always be drawn. */
export function urlTitleParts(href: string): { dir: string; base: string } {
  let u: URL;
  try { u = new URL(href); } catch { return { dir: "", base: href }; }
  const cut = u.pathname.lastIndexOf("/");
  const dec = (s: string): string => { try { return decodeURIComponent(s); } catch { return s; } };
  return { dir: u.host + dec(u.pathname.slice(0, cut + 1)), base: dec(u.pathname.slice(cut + 1)) };
}
