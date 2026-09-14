// CHAT COLUMNS, the page's half of the partition (the user 2026-09-11, who asked for columns that hold
// different sessions instead of each showing the whole board). The shell owns ONE fact: which sessions each
// later column holds, persisted under `romp-chat-cols` and read by every column page through the parent
// window's `__rompChatSets()` as `{"2": [sid…], "3": [sid…]}`. The first column has no entry: it holds every
// session no entry lists, so a session that arrives with no gesture (a peer's spawn, a remote host's tabs, a
// revive whose column has closed) lands there. Each page filters its strip by that fact through `tabInView`
// (render.ts), so the keyboard walk, the hidden-active re-point, the tag sections and the strip signature
// compose with it for free. Pure: no DOM, no window; render.ts hands it the search string and the sets.
export type ColSets = Record<string, string[]>;

/** The column this page is, from its own `location.search`: the pane shim's rule, byte for byte. The first
 *  column is `""` (`?col=1` folds to it, so its state blob keeps the unsuffixed key every older page had);
 *  every later column is its number as a string; a standalone page or the VS Code webview has no search. */
export function colFromSearch(search: string): string {
  let col = "";
  try { col = new URLSearchParams(search || "").get("col") || ""; } catch { col = ""; }
  return col === "1" ? "" : col;
}

/** The column whose entry lists `id`, else `""` (the first column, which derives). A doubly listed id (a
 *  store another dashboard wrote before this shell reconciled it; the shell's own writes never produce one
 *  and its `sets()` resolves one by row order) belongs to ONE column, the first key holding it, so no two
 *  columns ever both show a tab for it. */
export function ownerOf(sets: ColSets, id: string): string {
  for (const col of Object.keys(sets)) {
    const ids = sets[col];
    if (Array.isArray(ids) && ids.includes(id)) return col;
  }
  return "";
}

/** Whether column `col` holds `id` under `sets`. `null` sets means no partition at all (a standalone page,
 *  the VS Code webview, the phone, a shell without the split script): everything is held. A later column
 *  holds the ids its entry lists; the first column (`""`) holds every id no entry lists. */
export function columnHolds(sets: ColSets | null, col: string, id: string): boolean {
  if (sets === null) return true;
  return ownerOf(sets, id) === col;
}

/** THE LAYOUT of the chat area (the layout tree, the user 2026-09-14): the shell's `__rompChatLayout()`, `panes` how
 *  many panes the tree lays out (1: the one chat, every session behind its tab). null: no shell (a standalone page,
 *  the VS Code webview) or an older shell — one pane, as ever. */
export type ChatLayout = { panes: number };

/** The shell's answer, sanitised: `panes` an integer of at least 1, else 1 (never a throw); anything that is not an
 *  object is no layout at all. */
export function parseChatLayout(raw: unknown): ChatLayout | null {
  if (!raw || typeof raw !== "object") return null;
  const n = Number((raw as { panes?: unknown }).panes);
  return { panes: Number.isInteger(n) && n >= 1 ? n : 1 };
}

/** THE PANE HEADER RULE: a pane wears a one-line header (its one session's dot, name and ⋯) in the tab strip's place
 *  exactly when the layout has two or more panes AND this pane shows exactly one session. With none or two or more
 *  (the first pane is the overflow: a session placed in no pane stays reachable there, never a dead end) the strip
 *  shows as ever. */
export function paneHeaderShown(layout: ChatLayout | null, visibleHeld: number): boolean {
  return !!layout && layout.panes >= 2 && visibleHeld === 1;
}
