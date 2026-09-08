// Instrumenting every programmatic scroll write of the chat transcript (T262, the user 2026-09-08: the view
// "jumps up slightly on my scroll in many, many sessions", on a page whose bundle state is unknown). A recording
// alone cannot say WHICH writer moved the view; the laptop's client-diag journal can, once every write to
// #content.scrollTop rides one helper that files a breadcrumb — {surface:"chat", what:"scrollwrite",
// data:{sid, writer, before, after, delta, stick, gesture:false}} — and every scroll the writes do not explain
// files a "scrollgesture" marker, so the recording's timestamps line up against the journal.
//
// Cheap by construction: no stack traces, one row per write that actually moved the view, a per-session
// per-minute cap for each row kind (a following tail writes the bottom on every append; a wheel scroll fires
// dozens of gesture events a second), with one "capped" row at the cap so a silence in the journal is never
// mistaken for a quiet pane. The minute is the wall clock's minute bucket — a bound on volume, not a timer
// that decides behaviour. Pure and DOM-free so node --test executes it.

export const SCROLL_DIAG_CAP_PER_MINUTE = 40;

/** One kind of row's budget for one session within the current minute: "send" while under the cap, "cap"
 *  exactly once at the cap (the caller files a capped row), "drop" past it until the minute rolls. */
export class ScrollDiagBudget {
  private counts = new Map<string, { minute: number; n: number }>();
  constructor(private cap = SCROLL_DIAG_CAP_PER_MINUTE) {}
  take(sid: string, kind: string, nowMs: number): "send" | "cap" | "drop" {
    const minute = Math.floor(nowMs / 60000);
    const key = sid + " " + kind;
    let e = this.counts.get(key);
    if (!e || e.minute !== minute) { e = { minute, n: 0 }; this.counts.set(key, e); }
    e.n += 1;
    if (e.n <= this.cap) return "send";
    return e.n === this.cap + 1 ? "cap" : "drop";
  }
}

/** Is this #content scroll event the echo of the last programmatic write (its own scroll event, within a
 *  pixel of the value written), or a gesture nobody's code asked for? */
export function classifyScroll(scrollTop: number, lastWriteAfter: number | null): "write-echo" | "gesture" {
  return lastWriteAfter != null && Math.abs(scrollTop - lastWriteAfter) <= 1 ? "write-echo" : "gesture";
}

/** The breadcrumb for one write that moved the view. */
export function scrollWriteRow(sid: string, writer: string, before: number, after: number, stick: boolean) {
  return { sid, writer, before, after, delta: after - before, stick, gesture: false as const };
}
