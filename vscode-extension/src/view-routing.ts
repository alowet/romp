// THE reveal table: which webview→host messages make the extension reveal a
// sibling romp surface, and which are handled locally instead of being
// forwarded to the kernel. Pure decision core (like kernel-attach.ts) so the
// node test runner can pin the routing headlessly; extension.ts supplies the
// actual panel/view reveals.
//
// This is the VS Code analogue of the browser shell's cross-pane focus wiring
// ({romp:'reveal',pane:'chat'} → _LANDING_FOCUS_JS in bin/romp-kernel): the
// kernel opens/focuses the session tab itself (routed by wid), the host only
// brings the right surface forward.

export type App = "chat" | "feed" | "fleet" | "timeline";

export type Routed = {
  // Reveal the chat editor panel? preserveFocus=false means an intentional
  // jump INTO the chat (focus it); true means "bring it into view" while the
  // user keeps working where they clicked.
  revealChat: { preserveFocus: boolean } | null;
  // Reveal the feed editor panel? (chat's ledger dot opens the feed beside it)
  revealFeed: { preserveFocus: boolean } | null;
  // An href the HOST opens (OS browser / deep link) — the webview can't.
  // When set, the message is NOT forwarded to the kernel.
  openLinkLocally: string | null;
  forward: boolean;
};

const NONE: Routed = { revealChat: null, revealFeed: null, openLinkLocally: null, forward: true };

export function routeViewMessage(app: App, m: any): Routed {
  if (!m || typeof m.type !== "string") return { ...NONE, forward: false };

  // Any pane may hold a link the host must open (the timeline's, and since 2026-09-06 the PR links in
  // feed cards and outline rows): the kernel has no openLink handler, so forwarding it is a dead click.
  if (m.type === "openLink" && typeof m.href === "string")
    return { ...NONE, openLinkLocally: m.href, forward: false };

  if (app === "chat") {
    // reveal side-effects ride along; the kernel does the real work
    if (m.type === "dotOpen") return { ...NONE, revealFeed: { preserveFocus: true } };
    return NONE;
  }

  if (app === "feed" || app === "fleet") {
    // Clicking into a session (or locating a card's chat turn) brings the CHAT
    // panel forward — surface reveal is the host's job; the kernel opens/
    // focuses the tab itself.
    if (m.type === "openSession") return { ...NONE, revealChat: { preserveFocus: false } };
    if (m.type === "showOnTimeline") return { ...NONE, revealChat: { preserveFocus: true } }; // kernel locates the chat for prompt AND work clicks
    if (m.type === "showAskPath" && m.locate !== false && !m.jump && !m.off)
      return { ...NONE, revealChat: { preserveFocus: true } };
    return NONE;
  }

  // timeline
  if (m.type === "deepLink") return { ...NONE, revealChat: { preserveFocus: true } }; // a lane click jumps the chat there
  if (m.type === "usageData") return { ...NONE, forward: false }; // host-consumed (status-bar chrome), not a kernel op
  return NONE;
}
