// Does a user-role event have anything to SHOW? (T261, the user 2026-09-08: a blue rail dot with no message beside
// it.) The kernel strips romp's own markers and the harness's injected reminders out of a user record's text;
// a record that was nothing but those arrives with an empty `md`, and the user branch of the event renderer
// appended the rail dot BEFORE it checked for a bubble — so the dot stood alone on the rail, claiming a message
// nobody could see. The rule: a rail dot never stands alone. An event with nothing to show renders nothing (a
// zero-height unit, so the scroll↔unit map still counts it), and the dot is drawn only for a turn that draws
// a bubble. Pure and DOM-free so node --test executes it.
export function userTurnShows(ev: { md?: string | null; images?: readonly unknown[] | null }): boolean {
  return !!(ev.md && ev.md.trim()) || !!(ev.images && ev.images.length);
}
