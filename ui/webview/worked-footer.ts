// The "worked …" footer's rule, pure: which reply carries the footer, and how long it says.
//
// A reply's footer depends on LATER events — the turn has to be complete (a genuine human prompt landed
// after it) or the session idle — which made it the one thing on a rendered turn that a later event could
// change without the kernel naming that turn in a chatTail. The chat's tail path re-renders exactly the
// events the kernel names as changed (render.ts syncViewInner), so the footer is patched by unit from this
// plan instead of a trailing window re-rendered on every tail.
export interface WorkedEvent { kind: string; human?: boolean }
export type Epoch<E> = (ev: E) => number | null;

/** Seconds the session worked on the prompt that reply `i` answers, or null when `i` carries no footer:
 *  a prompt itself; a reply that is not its turn's last (a later reply exists before the next genuine
 *  prompt); the final turn while the session is still working (the live spinner owns it); no clock on
 *  either end. The elapsed runs from the IMMEDIATE trigger — the most recent user-role line of ANY author
 *  (a nudge or a postal push that prompted the work, not the older human prompt: the user 2026-06-22, who
 *  saw "worked 23m" on a two-minute-old nudge) — to the reply's own stamp. Injected user lines (a postal
 *  push, /command stdout) belong to the same turn: the scan for the turn's end skips them. */
export function turnWorkedSecs<E extends WorkedEvent>(events: readonly E[], i: number, working: boolean, epoch: Epoch<E>): number | null {
  const ev = events[i];
  if (ev.kind === "user") return null;
  let completed = false;
  for (let j = i + 1; j < events.length; j++) {
    const e = events[j];
    if (e.kind !== "user") return null;
    if (e.human) { completed = true; break; }
  }
  if (!completed && working) return null;
  const end = epoch(ev);
  if (end == null) return null;
  let start: number | null = null;
  for (let j = i; j >= 0; j--) { const e = events[j]; if (e.kind === "user") { start = epoch(e); break; } }
  if (start == null) return null;
  const secs = end - start;
  return secs > 0 ? secs : null;
}

/** The footer to reconcile after a tail re-rendered events [from, len): the one reply BEFORE `from` whose
 *  footer the tail can have changed, and its seconds — null when it carries no footer now. That reply is the
 *  last non-prompt event before `from`, when it sits inside the rendered window (at or past `winStart`).
 *  No earlier reply can change: before `from` it is followed either by a non-prompt event (never a footer,
 *  before or after the tail) or by a genuine prompt (its turn was already complete, and a complete turn's
 *  footer reads nothing past that prompt). The tail changes that one reply's footer in four ways: a prompt
 *  landing completes its turn (the footer goes on); the session going idle with an empty suffix (`from` =
 *  len) completes it too; a reply landing in the same turn demotes it (the footer comes off, the new reply
 *  having been rendered with its own); the session going back to work on the same turn — a nudge, say —
 *  takes it off again. Replies at or past `from` were just rendered with their footer and are not named. */
export function workedFooterPlan<E extends WorkedEvent>(events: readonly E[], from: number, winStart: number, working: boolean, epoch: Epoch<E>): Array<{ unit: number; secs: number | null }> {
  for (let j = Math.min(from, events.length) - 1; j >= Math.max(0, winStart); j--) {
    if (events[j].kind !== "user") return [{ unit: j, secs: turnWorkedSecs(events, j, working, epoch) }];
  }
  return [];
}
