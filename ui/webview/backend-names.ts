// The backends as the user reads them (T288, the user 2026-09-09): the internal ids ("sdk", "tmux", "codex") and
// the kernel protocol are unchanged; every label a person sees comes from here, so the picker toggles, the
// gear's Default backend list, the tab tooltip's Backend row and any chip agree. The default needs no
// qualifier, so the word "SDK" appears in no user-facing copy: it is "Claude Code"; the terminal-driven
// variant is "Claude Code (tmux)"; the OpenAI agent is "Codex".
export type BackendId = "sdk" | "tmux" | "codex";
export const BACKEND_LABEL: Readonly<Record<BackendId, string>> = { sdk: "Claude Code", tmux: "Claude Code (tmux)", codex: "Codex" };

/** The label for a backend id; an unknown id reads as itself (never a lie, never blank). */
export function backendLabel(be: string | null | undefined): string {
  return (be && (BACKEND_LABEL as Record<string, string>)[be]) || String(be || "");
}

/** What the picker OFFERS: "Claude Code (tmux)" only while the kernel setting says so (off by default). The
 *  setting gates the offer alone; an existing tmux session keeps working and keeps its label whatever it says. */
export function offeredBackends(tmuxOn: boolean): BackendId[] {
  return tmuxOn ? ["sdk", "tmux", "codex"] : ["sdk", "codex"];
}

/** The default a new session starts from: the saved preference when it is on offer, else Claude Code. A saved
 *  default of tmux while the tmux backend is off is set aside, not erased: it returns when the setting comes back. */
export function effectiveDefaultBackend(pref: string | null | undefined, tmuxOn: boolean): BackendId {
  const p = (pref || "sdk") as BackendId;
  return (offeredBackends(tmuxOn) as string[]).includes(p) ? p : "sdk";
}
