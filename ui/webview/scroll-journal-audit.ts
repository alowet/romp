// Reading the scroll journal for the move nobody wrote (T262k, the user 2026-09-08). For most of a day the chat
// transcript snapped away from where the reader had put it: a single scroll event, 0.1–2.7 s after they reached the
// bottom (or right after a land), read a scrollTop tens of pixels above the bottom — the same value every time for a
// given tab — with no "scrollwrite" row, no "tailchange" row, and scrollHeight unchanged at the read. Six such moves in
// five minutes of one capture; the go-to-bottom chip appeared after each. Every capture was read by hand.
//
// This module is that reading, as code, so the fingerprint is recognizable from the rows alone and a recurrence is a
// function call away from any journal (the laptop's client-diag.jsonl, a kernel-side check, a test fixture). It is
// pure and DOM-free; it consumes the rows the pane files through scroll-write.ts (scrollWriteRow, tailChangeRow,
// spacerRow, and the scroll listener's gesture row) and answers two questions:
//
//   unwrittenMoves(rows)    — which scroll events moved the view without a write to explain them? A move is a
//                             "scrollgesture" row whose top differs from the last recorded position by at least
//                             `minPx`, arriving at least `idleMs` after that position was recorded (so it is not the
//                             next sample of the reader's own burst) and with no further gesture within `settleMs`
//                             after it (a reader's burst continues; the snap is one event). Each move says whether a
//                             tail-height change or a spacer re-size filed since the last position accounts for its
//                             size (Chrome clamps a bottom reader when the tail shrinks and carries them along when
//                             a spacer above re-sizes — both legitimate, both unwritten) or nothing does.
//   repeatedLandings(moves) — which landing values recur? The snap's signature was one fixed value per tab.
//
// Limits, stated so a quiet result is read correctly: a move inside a gesture (the snap landed mid-burst once) is not
// separable from the burst by position alone and is not reported; a reader's single fast flick after a pause is
// reported as a move with `explained: "none"` — repeatedLandings tells the two apart, since a flick lands anywhere.

export type JournalRow = { t: number; what: string; data: any };

export type UnwrittenMove = {
  t: number;                   // when the move was read (ms, the row's clock)
  from: number;                // the last recorded position before it
  to: number;                  // the position the move landed on
  delta: number;               // to - from
  sh: number;                  // scrollHeight at the read
  ch: number;                  // clientHeight at the read
  distAfter: number;           // sh - to - ch: how far above the bottom the move left the reader
  idleMs: number;              // how long the last position had stood
  explained: "none" | "tail-change" | "spacer";
  by?: any;                    // the tailchange or spacer row that explains it, when one does
};

export type AuditOptions = { minPx?: number; idleMs?: number; settleMs?: number; tolPx?: number; sid?: string };

const DEFAULTS = { minPx: 24, idleMs: 400, settleMs: 150, tolPx: 2 };

/** The moves no write explains, in row order. `rows` are one journal's chat rows (any sid mix; pass `sid` to pick
 *  one, else rows are grouped by their data.sid). Rows need a millisecond `t`; the kernel's client-diag `t` is whole
 *  seconds, so a caller reading that file should stamp arrival time and pass it as `t`. */
export function unwrittenMoves(rows: JournalRow[], opts: AuditOptions = {}): UnwrittenMove[] {
  const o = { ...DEFAULTS, ...opts };
  const bySid = new Map<string, JournalRow[]>();
  for (const r of rows) {
    const sid = String(r?.data?.sid ?? "");
    if (o.sid != null && sid !== o.sid) continue;
    let list = bySid.get(sid);
    if (!list) { list = []; bySid.set(sid, list); }
    list.push(r);
  }
  const out: UnwrittenMove[] = [];
  for (const list of bySid.values()) out.push(...auditOne(list, o));
  return out.sort((a, b) => a.t - b.t);
}

function auditOne(rows: JournalRow[], o: Required<Omit<AuditOptions, "sid">> & { sid?: string }): UnwrittenMove[] {
  const out: UnwrittenMove[] = [];
  let pos: number | null = null, posT = 0;
  let since: JournalRow[] = [];                                     // tailchange / spacer rows since `pos` was recorded
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i], d = r.data || {};
    if (r.what === "scrollwrite") {
      if (typeof d.after === "number") { pos = d.after; posT = r.t; since = []; }
      continue;
    }
    if (r.what === "tailchange" || r.what === "spacer") { since.push(r); continue; }
    if (r.what !== "scrollgesture" || typeof d.top !== "number") continue;
    const top = d.top;
    if (pos != null) {
      const delta = top - pos, idle = r.t - posT;
      const next = nextGesture(rows, i + 1);
      const isolated = next == null || next.t - r.t >= o.settleMs;
      if (Math.abs(delta) >= o.minPx && idle >= o.idleMs && isolated) {
        const sh = Number(d.sh) || 0, ch = Number(d.ch) || 0;
        const by = explain(since, delta, o.tolPx);
        out.push({ t: r.t, from: pos, to: top, delta, sh, ch, distAfter: sh - top - ch, idleMs: idle,
          explained: by ? (by.what === "spacer" ? "spacer" : "tail-change") : "none", ...(by ? { by: by.data } : {}) });
      }
    }
    pos = top; posT = r.t; since = [];
  }
  return out;
}

function nextGesture(rows: JournalRow[], from: number): JournalRow | null {
  for (let j = from; j < rows.length; j++) if (rows[j].what === "scrollgesture") return rows[j];
  return null;
}

/** The tailchange or spacer row since the last position whose size accounts for `delta`: a tail that shrank by
 *  |delta| clamps a bottom reader up by |delta| (dh == delta); a top spacer that grew by delta carries the content
 *  under it down by delta and Chrome's anchoring carries the reader with it (dTop == delta). */
function explain(since: JournalRow[], delta: number, tol: number): JournalRow | null {
  for (const r of since) {
    const d = r.data || {};
    if (r.what === "tailchange" && typeof d.dh === "number" && Math.abs(d.dh - delta) <= tol) return r;
    if (r.what === "spacer" && typeof d.dTop === "number" && Math.abs(d.dTop - delta) <= tol) return r;
  }
  return null;
}

/** Landing values that recur among the moves (rounded to a tenth of a pixel), most frequent first. The snap landed
 *  on ONE value per tab, again and again; a reader's own flicks land anywhere. */
export function repeatedLandings(moves: UnwrittenMove[]): { to: number; count: number; distAfter: number }[] {
  const groups = new Map<number, { to: number; count: number; distAfter: number }>();
  for (const m of moves) {
    const key = Math.round(m.to * 10) / 10;
    const g = groups.get(key);
    if (g) g.count += 1; else groups.set(key, { to: key, count: 1, distAfter: Math.round(m.distAfter * 10) / 10 });
  }
  return [...groups.values()].filter((g) => g.count >= 2).sort((a, b) => b.count - a.count || a.to - b.to);
}

/** Parse one client-diag.jsonl line into a journal row, or null for anything that is not a chat scroll row. `t` is
 *  the row's own whole-second clock unless the line carries a finer `ta` (an arrival stamp a capture added). */
export function journalRowFromDiagLine(line: string): JournalRow | null {
  let d: any;
  try { d = JSON.parse(line); } catch { return null; }
  if (!d || d.surface !== "chat" || typeof d.what !== "string") return null;
  if (d.what !== "scrollgesture" && d.what !== "scrollwrite" && d.what !== "tailchange" && d.what !== "spacer") return null;
  const t = typeof d.ta === "number" ? d.ta * 1000 : typeof d.t === "number" ? d.t * 1000 : NaN;
  if (!Number.isFinite(t)) return null;
  return { t, what: d.what, data: d.data || {} };
}
