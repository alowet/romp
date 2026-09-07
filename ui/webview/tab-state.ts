// THE TAB STRIP'S STATE → CLASS RULE, in one place. The tab itself wears it (render.ts renderTabs),
// and a folded section header's summary pip (tab groups, 2026-09-04) reads the SAME rule — the
// header once classed any "blocked" member red, while the strip distinguishes an on-you block from a
// transient API error that auto-retries (amber, needs no attention), so a folded group showed a red
// "waiting on you" pip over a tab that, unfolded, was amber. Pure and DOM-free so it runs in node
// tests; the Status interface in render.ts is a superset of the shape read here.
export interface TabStateLike {
  state?: string;
  apiTooLong?: boolean;
  apiSpendLimit?: boolean;
  apiModelLimit?: boolean;
  apiAuthErr?: boolean;
  apiRefusal?: boolean;
}

/** The tab's state class for a status, or "" for a state with no tab treatment (ready/idle). */
export function tabStateClass(s: TabStateLike | null | undefined): string {
  const st = s?.state || "";
  if (st === "working") return "tab-working";
  // "blocked" is an API error. An on-YOU one — "prompt is too long" (compact), a monthly spend cap
  // (raise it, the user 2026-07-14), a spent model allowance (switch model, the user 2026-08-01), an
  // auth failure, or a safeguards refusal (rewrite the ask, the user 2026-08-15) — is alarm-red
  // dashed; a TRANSIENT API error is auto-retrying and needs no attention → the amber retrying
  // treatment, not red (the user 2026-06-29).
  if (st === "blocked") return (s!.apiTooLong || s!.apiSpendLimit || s!.apiModelLimit || s!.apiAuthErr || s!.apiRefusal) ? "tab-blocked" : "tab-retrying";
  if (st === "needsInput" || st === "awaiting") return "tab-awaiting";   // legacy name = an older remote kernel
  if (st === "retrying") return "tab-retrying";                          // amber: soft-blocked on an API auto-retry
  if (st === "compacting" || st === "clearing") return "tab-compacting"; // both: a context op in flight
  if (st === "closed") return "tab-closed";                              // dead session: read-only, struck-through label
  return "";
}

export type SectionPip = "blocked" | "retrying" | "working";

/** A folded header's ONE pip for its members' states, in the tab's own colours and by the tab's own
 *  rule: red when a member is blocked on you or waiting for you; else gold when one is working; else
 *  amber when one is stalled on an API error that is auto-retrying (shown only when nothing in the
 *  group is making progress — it is not on you); null when nothing is happening. */
export function sectionPip(states: ReadonlyArray<TabStateLike | null | undefined>): SectionPip | null {
  const cls = states.map(tabStateClass);
  if (cls.some((c) => c === "tab-blocked" || c === "tab-awaiting")) return "blocked";
  if (cls.includes("tab-working")) return "working";
  if (cls.includes("tab-retrying")) return "retrying";
  return null;
}

export const SECTION_PIP_TITLE: Record<SectionPip, string> = {
  blocked: "a session in this group is blocked or waiting on you",
  working: "a session in this group is working",
  retrying: "a session in this group hit an API error and is retrying on its own",
};
