// "Restart session" — the ONE row, built once for both menus that offer it: the chat strip's tab menu
// (render.ts showTabMenu) and the Sessions pane's row menu (fleet.ts showSessionMenu). The user asked for
// one action (2026-09-23) in place of End then Revive, the only in-product way a long-lived session could
// get onto a newly installed CLI — two destructive-looking steps through a confirm dialog for something
// that destroys nothing. The kernel's restartSession op relaunches the session's own process in place.
//
// What this module owns, so the two menus cannot drift:
//   * the gesture — idle restarts with no dialog, a working one confirms first (restartConfirmDetail
//     names what the click interrupts, the End dialog's shape); Cancel posts nothing;
//   * the ACKNOWLEDGEMENT (ui/CLAUDE.md's button rule: a post-and-wait control disables, changes its own
//     label and self-restores). The row latches to "Restarting…" on the click and the card stays up under
//     it — a restart changes nothing else on screen, by design, so the row is the only place the click can
//     show. It re-arms on the kernel's own reply for that sid (restarted / restartFailed / an unknownOp
//     refusal from a kernel older than this page), never on a clock;
//   * the latch is keyed by SID, never held on a node: the strip and the Sessions pane both rebuild on
//     every kernel push and the menu card outlives them, so a card reopened while a restart is in flight
//     shows the latched row too, and a settled sid restores a row only while its node is still connected.
import { addMenuItem, closeContextMenu, ConfirmButton } from "./ctx-menu";
import { RESTART_LABEL, RESTART_BUSY_LABEL, RESTART_SUBLINE, RESTART_BUSY_SUBLINE, restartConfirmDetail } from "./clear-confirm";
import type { ChipState } from "./status-chip";

const inFlight = new Set<string>();                 // sids this page has asked to restart and not heard back about
const latched = new Map<string, HTMLElement>();     // …and the row showing it, while that card is still up

/** Is a restart this page asked for still in flight for `sid`? */
export function restartInFlight(sid: string): boolean { return inFlight.has(sid); }

/** The kernel answered for `sid` (restarted, restartFailed, or an unknownOp refusal of the op): the latch
 *  lifts and any row still on screen re-arms in place. Idempotent — a sid with no latch settles to nothing. */
export function settleRestart(sid: string): void {
  inFlight.delete(sid);
  const row = latched.get(sid);
  latched.delete(sid);
  if (row && row.isConnected) dress(row, false);
}

/** Does restarting a session in each chip state interrupt anything? One entry per state of the kernel's chip
 *  (_session_chip, and build_session's `opening`), so a state added to ChipState fails to compile here until someone
 *  decides what a restart costs in it. The allow-list this replaced read every state it did not name as free, which
 *  is how a prompt and an API retry restarted with no dialog (the post-merge review of the restart row, 2026-09-24).
 *  A restart cuts the running turn: the relaunch interrupts it and the fresh CLI comes up at its end. */
export const RESTART_INTERRUPTS = {
  working: true, compacting: true,  // the chat's own reading of a turn in flight
  needsInput: true,                 // a turn paused on a permission or picker prompt, which the chip ranks above working; the question goes with it
  awaiting: true,                   // needsInput's legacy name, which an older remote kernel still sends: the same prompt
  retrying: true,                   // a turn still open while an API call is auto-retried, also ranked above working
  awaitingBg: true,                 // idle itself, but the background work it dispatched is retired with the client it belongs to (the reconnect's _drop_live_work)
  interrupting: false,              // a Stop already asked that turn to end: a restart sends nothing more (SdkSession.interrupt with climb=False) and the fresh CLI comes up when it ends
  clearing: false,                  // a /clear in flight: restarts with no dialog, as it always did; what that costs is not measured
  blocked: false, ready: false, idle: false, closed: false,   // no turn running
  opening: false,                   // the CLI is still starting, before its first turn
} satisfies Record<ChipState, boolean>;

/** The dialog's rule, read off RESTART_INTERRUPTS. A name the map lacks (no state yet, or one an older or newer remote
 *  kernel sends that this page does not know) takes no dialog, as before. */
export function restartInterrupts(state: string | null | undefined): boolean {
  return !!state && (RESTART_INTERRUPTS as Record<string, boolean>)[state] === true;
}

/** The confirm's title, the End dialog's shape. */
export function restartConfirmTitle(name: string): string { return `Restart “${name}”?`; }

/** The confirm's buttons: no danger mark — a restart destroys nothing (that is the whole claim the dialog
 *  is making), it only interrupts. */
export const RESTART_BUTTONS: ConfirmButton[] = [{ label: "Restart session", value: "restart" }, { label: "Cancel", value: "" }];

function dress(row: HTMLElement, busy: boolean): void {
  const label = row.querySelector(".ctx-item-label");
  const sub = row.querySelector(".ctx-item-sub");
  if (label) label.textContent = busy ? RESTART_BUSY_LABEL : RESTART_LABEL;
  if (sub) sub.textContent = busy ? RESTART_BUSY_SUBLINE : RESTART_SUBLINE;
  if (busy) row.setAttribute("aria-disabled", "true"); else row.removeAttribute("aria-disabled");
}

export interface RestartRowCtx {
  name: string;                 // the session as the user calls it, for the confirm's title
  state: string | null | undefined;   // its chip state as the menu read it: restartInterrupts decides the dialog, and a
                                      //  session waiting on your answer to a prompt hears that the question goes too
  titles: string[];             // its open tops, named in the confirm as the End dialog names them
  icon?: HTMLElement | null;    // the menu's drawn icon, where that menu draws them
  confirm: (title: string, detail: string, buttons: ConfirmButton[], cb: (v: string | null) => void) => void;
  post: () => void;             // the page's own postMessage of { type: "restartSession", id: sid }
}

/** Append the Restart session row to `menu` for `sid`. */
export function addRestartRow(menu: HTMLElement, sid: string, ctx: RestartRowCtx): HTMLElement {
  const working = restartInterrupts(ctx.state);         // a turn in flight or background work → confirm first; else straight through
  const asking = ctx.state === "needsInput" || ctx.state === "awaiting";   // …and one waiting on your answer loses the question
  const go = (row: HTMLElement) => {
    inFlight.add(sid);
    if (row.isConnected) { latched.set(sid, row); dress(row, true); }   // the acknowledgement, before the kernel round trip
    ctx.post();
  };
  const row = addMenuItem(menu, {
    icon: ctx.icon || null,
    className: "ctx-item-restart",
    label: RESTART_LABEL,
    sub: RESTART_SUBLINE,
    keepOpen: true,             // the row acts in place: the card stays up under the latched label
    pick: (r) => {
      if (restartInFlight(sid)) return;                 // already asked (the aria-disabled row's belt)
      if (!working) { go(r); return; }                  // idle: no dialog for a click that costs nothing
      // it is working: the dialog IS this click's acknowledgement, so the card goes first rather than
      // sitting under the overlay's dim (the Sessions pane's Delete order)
      closeContextMenu();
      ctx.confirm(restartConfirmTitle(ctx.name), restartConfirmDetail(ctx.titles, asking), RESTART_BUTTONS,
        (v) => { if (v === "restart") go(r); });        // Cancel, Escape, the backdrop: nothing posted
    },
  });
  if (restartInFlight(sid)) { latched.set(sid, row); dress(row, true); }   // a card reopened mid-restart
  return row;
}
