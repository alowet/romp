// The SOURCE a harness-injected user-role record is shown under (the user 2026-09-07: background-agent
// reports and system notices were rendering as the user's own bubbles). The kernel classifies each record
// by its own fields — the CLI's `origin.kind` stamp first, then the notification's <summary> — and ships
// `source` on the event (event_model.injected_source); this maps it to the notice card's head IN THE USER'S
// TERMS ("Background agent finished · <description>", "System notice · Scheduled task", "From <session>"),
// never the harness's. Pure and DOM-free so node --test executes it; render.ts owns the DOM.
//
// The model DOES know which subagent a notification came from: the notification carries the task id, the
// launching tool-use id and the agent's description ("Agent \"<description>\" came to rest"), so the head
// shows at least that description — the same words the parent agent read.

export interface InjectedSource {
  kind: "subagent" | "task" | "system" | "peer";
  name?: string;      // subagent/task: the description the notification names; peer: the sender's display name
  status?: string;    // subagent/task: the notification's raw <status> (completed / failed / killed …)
  label?: string;     // system: what kind of notice ("Scheduled task", "System reminder", …)
  subagent?: boolean; // peer: sent by one of this session's in-process background agents
}

export interface InjectedHead {
  variant: "agent" | "reminder" | "peer";   // the noticeCard skin
  chip: string;                             // the small type chip
  head: string;                             // the one-line gist
}

// The status word as the user would say it: a task "finished", not "completed" (the harness's word).
export function statusWord(status?: string): string {
  const s = (status || "").trim().toLowerCase();
  if (!s || s === "completed") return "finished";
  if (s === "killed" || s === "stopped") return "stopped";
  return s;   // failed / timed out / … read as they are
}

export function injectedHead(src: InjectedSource): InjectedHead {
  switch (src.kind) {
    case "subagent":
      return { variant: "agent", chip: "agent", head: `Background agent ${statusWord(src.status)}${src.name ? " · " + src.name : ""}` };
    case "task":
      return { variant: "agent", chip: "task", head: `Background command ${statusWord(src.status)}${src.name ? " · " + src.name : ""}` };
    case "peer":
      return { variant: "peer", chip: src.subagent ? "background agent" : "peer",
               head: `From ${src.name || "another session"}` };
    default:
      return { variant: "reminder", chip: "system",
               head: src.label && src.label !== "System reminder" ? `System notice · ${src.label}` : "System notice" };
  }
}
