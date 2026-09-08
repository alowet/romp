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

/** The cap a page actually runs with: the default, or the positive integer in localStorage under
 *  "romp:scrollDiagCap" (T262j, the user 2026-09-08: a capture on their laptop hit the 40/min gesture cap within
 *  seconds of trackpad scrolling, and every unwritten move for the rest of the minute went unrecorded; a laptop
 *  capturing sets the key, everyone else keeps the default). Anything that is not a positive integer → the default. */
export const SCROLL_DIAG_CAP_KEY = "romp:scrollDiagCap";
export function readScrollDiagCap(getItem: (key: string) => string | null): number {
  let raw: string | null = null;
  try { raw = getItem(SCROLL_DIAG_CAP_KEY); } catch { raw = null; }
  const n = raw == null ? NaN : Number(raw);
  return Number.isInteger(n) && n > 0 ? n : SCROLL_DIAG_CAP_PER_MINUTE;
}

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

/** The breadcrumb for one re-size of a view's virtualization spacers (T262j): a top spacer re-estimate paired with
 *  a bottom one leaves scrollHeight unchanged yet moves everything under the top spacer, and Chrome's scroll
 *  anchoring then moves the reader by the same amount with no pane write. `top`/`bot` = [before, after] heights. */
export function spacerRow(sid: string, topBefore: number, topAfter: number, botBefore: number, botAfter: number, sh = 0, ch = 0) {
  return { sid, top: [topBefore, topAfter], bot: [botBefore, botAfter], dTop: topAfter - topBefore, dBot: botAfter - botBefore, sh, ch };
}

/** The breadcrumb for one height change of the transcript's TAIL outside the append path (T262f, the user
 *  2026-09-08): the active view's element or the live-ask host grew or shrank, by `dh` px, with `last` naming the
 *  tail element (its class list, or "live-ask"). Chrome moves a bottom reader down itself when the tail grows and
 *  clamps them back when it shrinks — both unwritten, so the scroll rows alone cannot say WHICH element flapped;
 *  this row, filed beside them, names it. `stick` = the view's recorded follow mode at the change. */
export function tailChangeRow(sid: string, dh: number, last: string, stick: boolean, sh = 0, ch = 0) {
  return { sid, dh, last: String(last || "").slice(0, 60), stick, sh, ch };
}

/** The class list of the tail element of a view: its last child that is not a virtualization spacer. */
export function tailLabel(children: ArrayLike<{ className?: string }>): string {
  for (let i = children.length - 1; i >= 0; i--) {
    const c = String(children[i]?.className || "");
    if (c.indexOf("tx-spacer") < 0) return c;
  }
  return "";
}

/** The breadcrumb for one write that moved the view. `sh`/`ch` = #content's scrollHeight/clientHeight after the
 *  write (T262e, the user 2026-09-08: their laptop's rows showed the view moving UP by the same 95 px on two
 *  sessions with no write between the rows — an UNWRITTEN move, which the rows could not classify: a browser
 *  CLAMP after the transcript's tail shrank (scrollHeight drops, the new top equals scrollHeight − clientHeight)
 *  reads exactly like the browser's scroll anchoring absorbing a layout change above the viewport (scrollHeight
 *  unchanged). With both numbers on every row the next log tells them apart in one pass.) */
export function scrollWriteRow(sid: string, writer: string, before: number, after: number, stick: boolean, sh = 0, ch = 0) {
  return { sid, writer, before, after, delta: after - before, stick, gesture: false as const, sh, ch };
}
