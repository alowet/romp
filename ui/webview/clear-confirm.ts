// A typed /clear ends the conversation, and the kernel's episode boundary then settles the
// session's open cards with it (plans/clear-episodes.md). The chat composer is the one place romp
// sees the command BEFORE it runs, so it must never pass silently while open cards exist (the user
// 2026-07-27): sendComposer gates the send on an explicit confirm when clearConfirmDetail returns a
// detail. Pure helpers here so the gate's logic is node-testable without the DOM.

// mirrors the kernel's _is_clear_cmd (sdk_backend.py), the same truth table, client-side. The only
// divergence is which leading/trailing code points each side treats as whitespace: JS String.trim() and
// Python str.strip() have whitespace sets that differ on a few non-typeable control/BOM code points (the
// BOM/ZWNBSP U+FEFF, NEL U+0085 and the like). Pre-existing and not reachable from the composer or a
// keyboard, so the two predicates agree on every send a user can make; deliberately NOT reconciled here.
export function isClearCmd(text: string): boolean {
  const t = text.trim();
  return t === "/clear" || t.startsWith("/clear ");
}

// Codex's own word for the same operation (its TUI's /new): the kernel runs it as a clear on a Codex session
// (2026-09-19), so the composer gives it the same confirm there — and only there (sendComposer reads the
// session's backend; a Claude session never sees a confirm for a command its CLI refuses as unknown).
export function isNewCmd(text: string): boolean {
  const t = text.trim();
  return t === "/new" || t.startsWith("/new ");
}

export interface OpenCardNode { depth: number; done: boolean; cleared?: boolean; text: string; }

// The two sentences every surface that renames or ends a session shows (the chat's tab strip and its close button, the
// Sessions pane's row menu): one copy, so the surfaces never drift apart (the Sessions pane review, 2026-09-16).
export const RENAME_SUBLINE = "the name is a label: mail, goals and history follow the session";
export const END_SESSION_STANDING = "The session shuts down. Its history stays on disk; revive it any time from the picker or the timeline.";

// The open TOP-level cards a /clear would drop — the same population the kernel's boundary settle
// takes (open tops only; completed stay, already-cleared are gone). Blocked tops count: they are
// open, and dropping an owed question is exactly the silent loss the gate exists to stop.
export function openTopTitles(tree: OpenCardNode[] | undefined | null): string[] {
  return (tree || []).filter((n) => n.depth === 0 && !n.done && !n.cleared).map((n) => n.text);
}

// The confirm modal's detail line, or null when no confirm is needed (nothing open to drop).
export function clearConfirmDetail(titles: string[]): string | null {
  if (!titles.length) return null;
  const list = titles.join(", ");
  const shown = list.length > 140 ? list.slice(0, 139) + "…" : list;
  const n = titles.length;
  return (n === 1 ? "Its 1 open card gets dropped with it: " : "Its " + n + " open cards get dropped with it: ")
    + shown
    + ". Undo on the feed restores the cards, but the agent will no longer remember the work behind them.";
}

// The END confirm's detail (the user 2026-08-15, who ended a session holding an open task and got no
// warning before its card left the working surfaces): same open-top population as the /clear gate,
// framed for ending — the cards aren't destroyed (the goal store keeps them; revive brings them back),
// but they leave the board with the session, and that deserves naming before the click.
export function endConfirmDetail(titles: string[], base: string): string {
  if (!titles.length) return base;
  const list = titles.join(", ");
  const shown = list.length > 140 ? list.slice(0, 139) + "…" : list;
  const n = titles.length;
  return (n === 1 ? "1 card is still open on its board: " : n + " cards are still open on its board: ")
    + shown + ". Ending takes them off the working surfaces with it. " + base;
}


// ── Restart session (the user 2026-09-23) ────────────────────────────────────────────────────────
// One action for what End + Revive was doing in two: the session's own CLI process is replaced by a
// fresh one that picks the same conversation up. The reason it exists is a CLI UPGRADE — a session
// launched before one keeps the binary it started with, so a model only the newer CLI knows is out of
// reach from it. Nothing about the session changes, which is exactly why the copy has to say so: the
// user is being asked to accept an interruption for a change they will not see.
// One copy for both menus (the chat's tab menu, the Sessions pane's row menu), like the two above.
export const RESTART_LABEL = "Restart session";
export const RESTART_BUSY_LABEL = "Restarting…";                 // the row's own label while the relaunch is in flight
export const RESTART_SUBLINE = "relaunches its CLI on the version installed now — the conversation stays";
export const RESTART_BUSY_SUBLINE = "replacing its CLI; the tab and the conversation stay put";
export const RESTART_STANDING = "It keeps its name, its place and its whole conversation — only the program running it is replaced, by one that picks up where it left off.";

// The restart confirm's detail, shown ONLY when the session is working (an idle one restarts with no
// dialog at all): what the click interrupts, named the way the End dialog names what it drops — the open
// tops are what the running turn is about, so they say more than "a turn" does. `asking` is a session
// waiting on your answer to a prompt: the question goes with the turn, and the dialog says so (the
// review of the restart row, 2026-09-24, which found the dialog silent about it).
export function restartConfirmDetail(titles: string[], asking = false): string {
  const cut = asking ? "The turn it is running now is cut off, and the question it is asking you goes away with it. "
    : "The turn it is running now is cut off. ";
  if (!titles.length) return cut + RESTART_STANDING;
  const list = titles.join(", ");
  const shown = list.length > 140 ? list.slice(0, 139) + "…" : list;
  const n = titles.length;
  return (n === 1 ? "It is working on 1 open card: " : "It is working on " + n + " open cards: ")
    + shown + ". " + cut + RESTART_STANDING;
}
