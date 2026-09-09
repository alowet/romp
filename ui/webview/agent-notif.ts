// Parsing a harness <task-notification> — a backgrounded Agent or Bash command coming to rest — into the
// bits worth showing (the user 2026-06-30). It arrives folded into a user turn's `reminders` as raw inner
// XML:
//   <task-id>…</task-id><tool-use-id>…</tool-use-id><output-file>…</output-file>
//   <status>completed</status><summary>Agent "Ring A agent 3 rerun" came to rest</summary>
//   <note>…boilerplate…</note><result>…the agent's final message…</result>
// Dumping that under "system reminder" buried the one thing that matters — WHAT the task did.
//
// TWO shapes reach here (the user 2026-07-23): an AGENT ("Agent \"name\" came to rest", carrying a <result>
// final message) and a background COMMAND ("Background command \"desc\" completed (exit code N)", whose
// useful detail is the shell command + its output, NOT a result field — the kernel joins those in by
// tool-use-id, see build_session's taskOutputs). We keep a clean label + a compact status, the tool-use-id
// join key, and (for an agent) its result; the internal ids + boilerplate note are dropped. render.ts owns
// the DOM (renderAgentNotif); this owns the (pure, testable) parse.

export interface AgentNotif {
  kind: "agent" | "command" | "task";   // an Agent came to rest | a background Bash command | an unlabelled task
  label: string;      // the agent name, or the command's description — never the whole summary re-printed
  status: string;     // the raw <status> (completed / failed / …)
  detail: string;     // a compact head suffix: "exit 0" for a command, else the status word
  result: string;     // an agent's final message (markdown); "" for a command (its detail is command+output)
  summary: string;    // the raw summary line, kept as a fallback
  toolUseId: string;  // joins to the event's taskOutputs → a command's shell + output tail
}

// The card's one-line head, in the user's terms (the user 2026-09-07): "Background agent finished · <description>"
// rather than the bare "<description> · completed" — the head must say WHAT this is (a background agent's
// report, not a message anyone typed) before it says which one. A command keeps its exit code; a failed
// status reads as "failed". Pure, so the test executes the exact strings the card shows.
export function notifHead(a: AgentNotif): string {
  const status = (a.status || "").trim().toLowerCase();
  const word = !status || status === "completed" ? "finished" : status === "killed" || status === "stopped" ? "stopped" : status;
  if (a.kind === "agent") return `Background agent ${word} · ${a.label}`;
  if (a.kind === "command") return `Background command ${word} · ${a.label}` + (/^exit \d+$/.test(a.detail) ? ` · ${a.detail}` : "");
  return `Background task ${word} · ${a.label}`;
}

export function parseAgentNotif(text: string): AgentNotif | null {
  // Only a task-notification (has a <task-id> or an Agent/Background-command summary); a plain reminder → null.
  if (!/<task-id>|<summary>\s*(?:Agent|Background command)\b/.test(text)) return null;
  const grab = (t: string) => (text.match(new RegExp("<" + t + ">([\\s\\S]*?)</" + t + ">")) || [])[1] || "";
  const summary = grab("summary").trim();
  const status = grab("status").trim();
  const result = grab("result").trim();
  const toolUseId = grab("tool-use-id").trim();
  if (!summary && !result) return null;

  const agentM = summary.match(/Agent\s+"([^"]+)"/);           // Agent "<label>" came to rest
  const cmdM = summary.match(/Background command\s+"([^"]+)"/); // Background command "<desc>" completed (exit code N)
  const exitM = summary.match(/exit code\s+(\d+)/i);
  let kind: AgentNotif["kind"], label: string, detail: string;
  if (agentM) {
    kind = "agent"; label = agentM[1]; detail = status || "returned";
  } else if (cmdM) {
    kind = "command"; label = cmdM[1];
    detail = exitM ? "exit " + exitM[1] : (status || "done");   // "exit 0" reads at a glance; the word is the fallback
  } else {
    kind = "task";
    label = summary.replace(/\s+came to rest.*$/i, "").replace(/\s+completed.*$/i, "").trim() || "Task";
    detail = status || "returned";
  }
  return { kind, label, status, detail, result, summary, toolUseId };
}
