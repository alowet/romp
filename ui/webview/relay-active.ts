// Re-arming a kernel's ACTIVE tab when the socket to it (re)opens (T246, the user 2026-09-07: after an attached
// kernel restarted, the pane stopped receiving live events for that host's active session until the user's
// next send).
//
// A kernel serves the tab a client is LOOKING AT from the live change key (its per-client `active`:
// _active_chat_sig folds in the backend's live tail, its queue, the snapshot row and every side file) and
// every other session from the file-stat cache (_chat_build_sig), which no in-memory stream ever busts. A
// client declares its tab two ways: the `?active=` connect hint (the pane shim's LOCAL socket carries it on
// every dial, from the PERSISTED state) and the `activeTab` message (render.ts notifyActive, on every tab
// switch). The federation relay carries no connect hint, and a remote kernel that restarted mints a fresh
// client with no active tab — so the session the user was watching streamed nowhere until their next send
// moved a file-stat input. federation.ts dispatches romp:hostRelayUp on the relay's own open, the exact
// moment the fresh kernel-side client exists; render.ts re-announces the active tab on it through
// notifyActive (routeOutbound strips the host prefix), when this decision says that host owns the tab.
//
// The LOCAL socket gets the same re-arm on its own open (romp:wsup, the shim's reconnect event; review fold
// 2026-09-08): its ?active= hint reads the persisted activeId, and a dismissal's fallback or a sole-tab
// adoption changes activeId without setActive, so the persisted copy can name a tab the user has left —
// after a local kernel restart the hint then keyed a tab nobody was looking at, the same symptom class for a
// local session. Re-announcing the LIVE activeId on the open removes the dependence on the persisted copy;
// the kernel's activeTab handler just records the id and wakes the pusher, so a hint that was already right
// costs one wake.
//
// Pure and DOM-free so node --test executes it.
import { hostOf } from "./host-prefix";

/** Should the pane re-send `activeTab` for `activeId` now that the socket to `host` is open? `host` is the
 *  relay's host name, or "" for the pane shim's LOCAL socket. Only when the tab is that kernel's: another
 *  host's tab means nothing to this kernel (its handler would record an id it does not know), and no tab
 *  names nothing to re-arm. */
export function activeTabToReannounce(activeId: string | null, host: string): boolean {
  if (!activeId) return false;
  return hostOf(activeId) === host;
}
