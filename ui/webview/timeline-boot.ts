// The VS Code timeline surface's boot pieces — the glue between the shared
// TimelinePanel (ui/romp-timeline-view.js) and a host that speaks the kernel's
// WS protocol through acquireVsCodeApi/postMessage.
//
// The BROWSER twin of this file is the kernel's inline _TIMELINE_BOOT block
// (bin/romp-kernel): same DOM-helper shims, same __rompTimeline* bridge set,
// same inbound-frame dispatch. They are not auto-shared (the web one must stay
// an injected string so an edit to the view goes live on reload), so
// timeline-boot.test.ts pins the two bridge sets against each other.
//
// Everything here is pure/injectable so the node test runner can exercise it
// headlessly; timeline-main.ts is the thin entry that wires it to the real
// window.

import { writeViewOrder } from "./view-order";

export type Post = (m: Record<string, unknown>) => void;

// The 3 Obsidian DOM helpers TimelinePanel expects on every element.
export function installDomHelpers(proto: any): void {
  if (!proto.createEl)
    proto.createEl = function (tag: string, o?: { cls?: string; text?: string }) {
      const e = document.createElement(tag);
      if (o && o.cls) e.className = o.cls;
      if (o && o.text) e.textContent = o.text;
      this.appendChild(e);
      return e;
    };
  if (!proto.createDiv) proto.createDiv = function (o?: { cls?: string; text?: string }) { return this.createEl("div", o); };
  if (!proto.createSpan) proto.createSpan = function (o?: { cls?: string; text?: string }) { return this.createEl("span", o); };
}

// Inbound kernel frame → TimelinePanel method. Returns whether the frame was
// one of the panel's (so callers can ignore the rest of the host chatter).
export function dispatchFrame(panel: any, m: any): boolean {
  if (!m || !panel) return false;
  if (m.type === "data") { panel.update(m.data); return true; }
  if (m.type === "bars" && panel.applyBars) { panel.applyBars(m); return true; }
  if (m.type === "activeChat" && panel.setActiveChat) { panel.setActiveChat(m.activeChat); return true; }
  if (m.type === "hover" && panel.setHover) { panel.setHover(m); return true; }
  // chat rail CLICK → pan to that moment and pulse it (the user 2026-07-23). Deliberately not the
  // `focus` path: focusEvent also drives openChat, and the click came FROM the chat, so that would be a
  // round trip back into the pane the user is already looking at. revealEvent pans + pulses only.
  if (m.type === "revealEvent" && panel.revealEvent) { panel.revealEvent(m.sid, m.t, m.id); return true; }
  // the kernel's pick memory moved (a pin, a Latest un-pin, a refused pin dropped — from any surface or
  // dashboard) or its catalog grew: the lane picker re-reads /models so its family rows send the fresh default
  if (m.type === "models" && panel.refreshModels) { panel.refreshModels(); return true; }
  // the kernel refused a gesture this page posted (a lane flag whose store could not be read): the panel
  // ends its optimistic state on this event and shows the reason in the gear
  if (m.type === "settingRefused" && panel.settingRefused) { panel.settingRefused(m); return true; }
  if (m.type === "tagEditFailed" && panel.tagEditFailed) { panel.tagEditFailed(m); return true; }
  // the kernel's answer to one of THIS page's views writes (a targeted tag edit, or a whole-blob lens/
  // order write): the panel adopts the returned blob and settles or reverts its optimistic copy
  if ((m.type === "tagEditAck" || m.type === "viewsAck") && panel.viewsAck) { panel.viewsAck(m); return true; }
  // what the kernel can do for this page, sent on every `ready` (a reconnect re-sends it); and the
  // kernel's answer to an op it does not know — a refusal of that write, and the cap is withdrawn
  if (m.type === "caps" && panel.setCaps) { panel.setCaps(m); return true; }
  if (m.type === "unknownOp" && panel.unknownOp) { panel.unknownOp(m); return true; }
  return false;
}

// A lane's open-external URL → the message to post. A vscode:// deep link is
// unwrapped into the kernel's deepLink op (the extension host reveals the chat
// panel when it sees one go by — the analogue of the browser shell's
// {romp:'reveal',pane:'chat'}); anything else is an openLink for the host to
// hand to the OS.
export function openExternalMessage(url: string): Record<string, unknown> {
  try {
    const u = new URL(url);
    if (u.protocol === "vscode:") {
      const q = u.searchParams;
      return {
        type: "deepLink",
        session: q.get("session"),
        anchor: q.get("anchor") || undefined,
        anchorT: Number(q.get("anchorT")) || undefined,
        anchorKind: q.get("anchorKind") || undefined,
        compose: q.get("compose") === "1",
      };
    }
  } catch { /* not parseable — let the host decide */ }
  return { type: "openLink", href: url };
}

// The window.__rompTimeline* host bridges the view calls into. Keyed by the
// exact global names the view uses (pinned against the kernel's _TIMELINE_BOOT
// by timeline-boot.test.ts).
export function bridgeFunctions(post: Post): Record<string, (...a: any[]) => void> {
  return {
    __rompTimelineOpenExternal: (url: string) => post(openExternalMessage(String(url))),
    // A lane drag writes the VIEWER's arrangement (the user 2026-07-31), the same store the chat strip
    // writes — not the kernel's session-order.json, which is only the arrival-order seed now. Sending it
    // to a kernel could never interleave hosts anyway: each one can only record its own sids.
    __rompTimelineWriteOrder: (order: unknown) =>
      writeViewOrder(Array.isArray(order) ? order.filter((x): x is string => typeof x === "string") : []),
    __rompTimelineCompact: (name: string) => post({ type: "compact", name }),
    // `extra` rides op flags beside the command text — the lane submenu's Latest row sends
    // `{ floating: true }` so the kernel forgets the family's remembered pin
    __rompTimelineSendCommand: (name: string, cmd: string, extra?: Record<string, unknown>) => post({ type: "sendCommand", name, cmd, ...(extra || {}) }),
    __rompTimelineSetFlag: (id: string, flag: string, value: unknown) => post({ type: "setSessionFlag", id, flag, value: !!value }),
    // a whole-blob write; `edited` names the tag ids the gesture changed (a lens or order write: none), so
    // the kernel acks a refusal on an untouched tag as ok with the refusal listed
    __rompTimelineSetViews: (views: unknown, writeId?: unknown, edited?: unknown) =>
      post({ type: "setTimelineViews", views, writeId, edited: Array.isArray(edited) ? edited : [] }),
    // one targeted tag edit: the op {op, tid, …} rides NESTED under `edit` (the kernel's tagEdit message),
    // so no field of it sits at the top level where the federation router reads session addresses
    __rompTimelineTagEdit: (writeId: unknown, edit: unknown) => post({ type: "tagEdit", writeId, edit }),
    __rompTimelineEditTag: (edit: unknown) => post({ type: "editTag", edit }),
    __rompTimelineDismiss: (id: string) => post({ type: "dismissLane", id }),
    __rompTimelineHover: (sid?: string, segIds?: unknown[], t0?: number, t1?: number) =>
      post(sid ? { type: "timelineHover", sid, segIds: segIds || [], t0, t1 } : { type: "timelineHover", off: true }),
  };
}
