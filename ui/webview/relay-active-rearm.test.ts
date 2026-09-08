// T246 (the user 2026-09-07): after an ATTACHED kernel restarts, the chat pane stopped receiving live events
// for that host's ACTIVE session until the user's next send.
//
// Why: a kernel keys the tab a client is LOOKING AT (its per-client `active`, set by the `?active=` connect
// hint or an `activeTab` message) on the live change key (_active_chat_sig: the backend's live tail, its
// queue, the snapshot row, every side file); every OTHER session is served from the file-stat cache
// (_chat_build_sig), which no in-memory stream ever busts. The pane shim's local socket carries `?active=`
// on every dial, so a LOCAL kernel restart re-arms it for free. The federation relay (federation.ts
// connect) carries no such hint, and nothing re-sent `activeTab` on the relay's reopen — so the restarted
// remote kernel minted a client with no active tab, served the watched session as a background one, and
// its reply streamed nowhere until the user's next send moved a file-stat input. The fix re-announces
// the active tab on romp:hostRelayUp — the relay's own open event, the exact moment the fresh kernel-side
// client exists — when, and only when, that host owns the tab. Executed helper + render.ts wiring pins.
// Synthetic ids only.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { activeTabToReannounce } from "./relay-active";

const SID = "11111111-2222-4333-8444-000000000246";
// the sources are read from the tree, not the bundled test's own dir (node --test runs from vscode-extension/)
const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const FED = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "federation.ts"), "utf8");

test("the active tab is re-announced on the relay's open only when THAT host owns it", () => {
  assert.equal(activeTabToReannounce("TESTHOST:" + SID, "TESTHOST"), true, "the watched tab is that host's");
  assert.equal(activeTabToReannounce("TESTHOST:" + SID, "hostB"), false, "another host's relay reopened — its kernel never had this tab");
  assert.equal(activeTabToReannounce(SID, "TESTHOST"), false, "a LOCAL tab: the pane shim's ?active= already covers the local socket");
  assert.equal(activeTabToReannounce(null, "TESTHOST"), false, "no tab open");
  assert.equal(activeTabToReannounce("TESTHOST:" + SID, ""), false, "an event with no host names no relay");
});

test("render.ts re-sends activeTab on romp:hostRelayUp for that host's active tab, beside the upload re-ship", () => {
  assert.match(RENDER, /import \{ activeTabToReannounce \} from "\.\/relay-active";/);
  // the same listener the T215 re-ship uses (pending-attach.test.ts pins its header) gains the re-arm; the
  // decision is the pure helper's, so a host mismatch never posts a stray activeTab at a kernel that
  // does not know the session
  const m = RENDER.match(/window\.addEventListener\("romp:hostRelayUp", \(e\) => \{([\s\S]*?)\n\}\);/);
  assert.ok(m, "the romp:hostRelayUp listener exists");
  assert.match(m![1], /reshipPendingUploads\(\[h\]\)/, "the upload re-ship is still there");
  assert.match(m![1], /if \(activeTabToReannounce\(activeId, h\)\) notifyActive\(\);/, "the active tab is re-announced through the one activeTab sender (notifyActive → routeOutbound strips the host prefix)");
});

test("the relay dial carries no connect-time active hint — the reopen event is where the tab is re-armed", () => {
  // Documenting the shape the fix composes with: federation's URL names app/token/wid only (the shim's
  // local socket adds ?active= from its persisted state; the relay reads the pane's LIVE activeId on the
  // open event instead — a persisted copy can lag a dismissal/adoption, which never call setActive)
  const url = FED.match(/const url = `\$\{proto\}\$\{location\.host\}\/remote\/[\s\S]*?;\n/);
  assert.ok(url, "the relay URL builder");
  assert.doesNotMatch(url![0], /active=/);
  // and the open event is dispatched AFTER flushPending, so a queued setting still precedes the activeTab
  const onopen = FED.match(/ws\.onopen = \(\) => \{([\s\S]*?)\n    \};/);
  assert.ok(onopen);
  assert.ok(onopen![1].indexOf("this.flushPending(conn)") < onopen![1].indexOf('"romp:hostRelayUp"'));
});
