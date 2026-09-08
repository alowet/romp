// What a `session` frame's events mean for a session the pane already holds (T249b, the user 2026-09-07).
//
// The kernel's full frame carries the transcript's events; render.ts upsert took `msg.events` as the new resident
// transcript whenever the field was present — an EMPTY array included, because `[]` is truthy. A kernel whose read
// of the transcript failed for one cycle (the file unreadable at build time) sent exactly that: a session frame
// with `events: []` for a session with content. The pane blanked the transcript to a placeholder, and the content
// frame a cycle later read as a FIRST build, which re-landed the reader through the full-show route — the
// recorded scroll snap. The kernel now keeps its previous build instead of sending an emptied one; this is the
// pane's own half of the same rule: a frame that would take a conversation from content to nothing is
// status-shaped (its chip, name and meta still apply), never a transcript wipe. Nothing legitimate empties a held
// transcript through this path — a /clear is never events-empty (its boundary card), a fork mints a new id — and
// when it fires the pane files one client-diag row per session, so a kernel that does send such frames is seen.
// Pure and DOM-free so node --test executes it.

/** Keep the resident events instead of taking the frame's? Only when the pane holds a transcript WITH events and
 *  the frame's events are an EMPTY array. A frame with no `events` field at all is already handled by the caller
 *  (it keeps the resident events); a frame with events replaces them as before. */
export function keepResidentEvents(prev: readonly unknown[] | null | undefined, incoming: unknown): boolean {
  return !!prev && prev.length > 0 && Array.isArray(incoming) && incoming.length === 0;
}
