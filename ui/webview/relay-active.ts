// Re-arming a remote kernel's ACTIVE tab when its relay socket (re)opens (T246, the user 2026-09-07: after an
// attached kernel restarted, the pane stopped receiving live events for that host's active session until the
// user's next send).
//
// A kernel serves the tab a client is LOOKING AT from the live change key (its per-client `active`:
// _active_chat_sig folds in the backend's live tail, its queue, the snapshot row and every side file) and
// every other session from the file-stat cache (_chat_build_sig), which no in-memory stream ever busts. A
// client declares its tab two ways: the `?active=` connect hint (the pane shim's LOCAL socket carries it on
// every dial, from the persisted state) and the `activeTab` message (render.ts notifyActive, on every tab
// switch). The federation relay carries no connect hint, and a remote kernel that restarted mints a fresh
// client with no active tab — so the session the user was watching streamed nowhere until their next send
// moved a file-stat input. federation.ts dispatches romp:hostRelayUp on the relay's own open, the exact
// moment the fresh kernel-side client exists; render.ts re-announces the active tab on it through
// notifyActive (routeOutbound strips the host prefix), when this decision says that host owns the tab.
//
// Pure and DOM-free so node --test executes it. Reads the pane's LIVE activeId, never the persisted copy:
// a dismissal's fallback and a sole-tab adoption change activeId without setActive, so the persisted
// value can lag the box the user is actually typing into.
import { hostOf } from "./host-prefix";

/** Should the pane re-send `activeTab` for `activeId` now that `host`'s relay socket is open? Only when the
 *  tab is that host's: a local tab is the local socket's business (its connect hint), another host's tab
 *  means nothing to this kernel, and no tab or no host names nothing to re-arm. */
export function activeTabToReannounce(activeId: string | null, host: string): boolean {
  if (!activeId || !host) return false;
  return hostOf(activeId) === host;
}
