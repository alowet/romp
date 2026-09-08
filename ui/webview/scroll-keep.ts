// Where a full show of the ACTIVE view lands, and how the per-view saved spot is kept (T249, the user
// 2026-09-07: the chat pane snapped their scroll back to an earlier position a few seconds after they
// scrolled, on a session served through the relay from an attached kernel).
//
// landActive ends every show that no anchor scrolled with ONE rule: an unshown or follow-mode view lands at
// the bottom, any other view lands on its saved `scrollTop`. Until now that saved spot was written only by a
// tab switch (the tab being LEFT), the jump-to-bottom button, the tab-strip/ledger resize compensation and
// the nav trail — never by the reader's own scrolling. So the spot named where the tab was when it was
// last left, and every full show of an already-shown tab (a fork/first-build frame, a settings rerender, a
// revive failure, a dismissal's fallback) landed the reader back there: they had scrolled to the bottom,
// a frame arrived, and the view jumped up to a bubble they had read minutes earlier.
//
// Two rules, both pure so node --test executes them:
//  1. the saved spot FOLLOWS the reader — the #content scroll listener records the active shown view's
//     position and follow-mode on every scroll (followReader), so landActive's rule lands where they are —
//     except while a DEFERRED build is pending (review find, 2026-09-08): showActive reveals the entering
//     view a frame before its heavy build, the browser clamps scrollTop to that stale or empty DOM, and the
//     clamp's scroll event arrives before the frame callback that lands the view; recorded, it sent a
//     compact-mode tab switch and a settings rerender to the bottom instead of the saved spot. The pending
//     build is the event that marks the transient, so `building` suppresses the record until it lands;
//  2. a show of a view that is ALREADY on screen keeps the reader's place across its rebuild the way the
//     live append does (keepPlaceAcrossShow → captureScrollAnchor before, restoreScrollAnchor after): a
//     rebuild can move content above the viewport, and only an anchor keeps the line being read still.
//     A tab SWITCH is not that: the entering view is not displayed yet, so its explicit spot semantics
//     (the leaving-tab save, the nav trail's remembered spot, the jump button) are untouched. A caller that
//     must EMPTY the view before showing it (rerenderAll, on a settings change) captures the anchor first
//     and hands it to showActive, which by then has no DOM to capture from.
// Event-based throughout: the scroll event and the show itself; no timer, no age threshold.

export interface KeepView { scrollTop: number; stick: boolean; shown: boolean; }

/** The reader scrolled the active view: its saved spot and follow-mode follow them. A view not yet shown
 *  keeps its defaults (its first land goes to the bottom regardless), a hidden pane never scrolls, and while
 *  a deferred build is pending (`building`) the position is the reveal's clamp, not the reader's — the
 *  build's own land fires the next scroll event, and that one is recorded. */
export function followReader(v: KeepView | null | undefined, scrollTop: number, near: boolean, building = false): void {
  if (!v || !v.shown || building) return;
  v.scrollTop = scrollTop;
  v.stick = near;
}

/** landActive's landing when no anchor scrolled: "bottom" for an unshown or follow-mode view, else the saved spot. */
export function landSpot(v: KeepView): number | "bottom" {
  return (!v.shown || v.stick) ? "bottom" : v.scrollTop;
}

/** Must this show keep the reader's place across the rebuild? Only when the view is the one on screen
 *  already (displayed, in a visible pane), has been shown before, and nothing is navigating (no pending
 *  anchor or moment: a deep link lands where it says). A tab switch fails `displayed`; a first show fails
 *  `shown`; a hidden pane has nothing to keep. */
export function keepPlaceAcrossShow(v: KeepView, displayed: boolean, visible: boolean, navigating: boolean): boolean {
  return v.shown && displayed && visible && !navigating;
}
