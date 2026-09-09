// The chat pane's hold on the dashboard's self-reload (T272 follow-up, the manager's review 2026-09-08): a reload takes
// an upload in flight's bytes and a held send's release with it, so the pane reports itself busy while either is
// pending — but ONLY while the ack can still arrive. A ship to a host whose relay is down, or to a host no longer
// attached, has no ack coming until that host returns; holding every restart and build reload for it would stop the
// dashboard from ever reloading, silently. So the hold counts ships whose host is the local kernel or an attached,
// reachable host, and a held reload wears a face (heldReloadText) on the notification center or a standalone pane's
// bar, since nothing displayed the core's `waiting` before. Pure and DOM-free so node --test executes it.

export type FedView = { hosts?: () => string[]; down?: () => string[] } | null | undefined;

/** The host prefix of a sid ("" for the local kernel). */
const hostOfSid = (sid: string): string => { const i = sid.indexOf(":"); return i > 0 ? sid.slice(0, i) : ""; };

/** Whether a pending ship for `sid` still has an ack coming: local, or a host the federation manager lists as
 *  attached and not down. No manager loaded (a single-kernel page): every ship holds. */
export function shipHoldsReload(sid: string, fed: FedView): boolean {
  const host = hostOfSid(sid);
  if (!host) return true;
  if (!fed) return true;
  try {
    if (typeof fed.hosts === "function" && fed.hosts().indexOf(host) < 0) return false;   // detached or removed: gone
    if (typeof fed.down === "function" && fed.down().indexOf(host) >= 0) return false;   // its relay is down
  } catch { return true; }
  return true;
}

/** The pane's busy reason for the reload core, from what is pending: "upload" while a ship whose ack can still
 *  arrive awaits it, "held-send" while a send is held on such a ship; "" otherwise. */
export function reloadHoldReason(shipSids: string[], gateSid: string | null, fed: FedView): string {
  const live = shipSids.filter((sid) => shipHoldsReload(sid, fed));
  if (live.length) return "upload";
  if (gateSid && shipHoldsReload(gateSid, fed)) return "held-send";
  return "";
}

/** The line a held reload wears, per the pane's reason; null for a momentary gesture hold (the core's own
 *  pointer/pan/drag/selection/typing reasons), which needs no line. */
export function heldReloadText(reason: string): string | null {
  switch (reason) {
    case "upload": return "The dashboard will reload once the upload in progress finishes.";
    case "held-send": return "The dashboard will reload once the held message has been sent.";
    case "sends": return "The dashboard will reload once the queued messages have left.";
    case "pointer": case "pan": case "drag": case "selection": case "typing": case "": return null;
    default: return "The dashboard will reload once the page is idle (" + reason + ").";
  }
}
