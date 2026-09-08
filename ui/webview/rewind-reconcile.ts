// The pending-rewind overlay and the editable-bubble set, as one pass over a session's events — pure, so
// node --test runs it without a DOM (render.ts reconcileRewind delegates here the way turnWorkedSecs
// delegates to worked-footer.ts).
//
// The pass has three outputs. The EDITABLE set: genuine human messages with a transcript uuid, after the
// last compaction (the CLI only addresses post-boundary records, so older bubbles get no edit affordance;
// the kernel re-validates regardless). The OVERLAY for a pending rewind: the edited bubble carries the new
// text and `pending`, every later event is dimmed (`rewound`); a bare delete dims from the deleted bubble
// on. The pending entry itself is retired when the branch landed (the old uuid is gone) or the TTL backstop
// expired. The `rewound` flags are stripped first because a chatTail delta REUSES prefix event objects
// across pushes.
//
// And the STALE signal the chat's exact tail path rests on. The tail re-renders exactly the events the
// kernel's `from` names (render.ts syncViewInner), so a prefix bubble whose edit buttons or dim depend on
// these outputs is repainted by THIS signal: a compaction landing at `from` strips the affordance from
// every earlier bubble; a failed rewind's TTL expiry lifts a dim no later `from` reaches back to. The
// signature is taken BEFORE the pass — its dim and editable parts describe the previous pass — and
// compared after it, on every path (a retired edit and a session with no edit pending both reach the
// comparison). `bound` is the tail's re-render start (chatTail's `from`): events at or past it are
// re-rendered anyway, so only the prefix below it counts as a change — unbounded, every human prompt
// landing (a new editable bubble) would mark the view stale and rebuild the whole window instead of taking
// the exact tail. The pending edit stays unbounded: its retirement lifts a dim that no `from` reaches back
// to.
export interface RewindEvent {
  kind: string;
  uuid?: string;
  human?: boolean;
  romp?: boolean;
  interruptMarker?: boolean;
  rewound?: boolean;
  md?: string;
  pending?: boolean;
  images?: unknown;
  texts?: { md: string }[];
}
export interface PendingRewind { uuid: string; text: string; ts: number; bare?: boolean }
export interface RewindOpts {
  sdk: boolean;         // the session's backend is the SDK: only its transcripts are addressable, so only they get an editable set
  now: number;          // Date.now() — injected so a test never sleeps
  ttlMs: number;        // the pending edit's backstop
  optPrefix: string;    // an optimistic echo's uuid prefix: never editable (send-pending.ts OPT_PREFIX)
  bound?: number;       // the tail's re-render start; the signature reads events below it (default: all)
}
export interface RewindResult { editable: Set<string>; pending: PendingRewind | null; stale: boolean }

/** The editable set and the rewind overlay as one string: which bubbles may be edited, which events are
 *  dimmed, and the pending edit (its uuid; its text, or "b" for a delete). "?" before the first pass. The
 *  editable and dimmed parts read events below `bound` only; the pending edit is unbounded. */
export function rewindSig(events: readonly RewindEvent[], editable: Set<string> | undefined,
                          pending: PendingRewind | null | undefined, bound: number = events.length): string {
  const eds: string[] = [], dim: number[] = [];
  const n = Math.min(bound, events.length);
  for (let i = 0; i < n; i++) {
    const e = events[i];
    if (editable && e.uuid && editable.has(e.uuid)) eds.push(e.uuid);
    if (e.rewound) dim.push(i);
  }
  return (editable ? eds.join(",") : "?") + "|" + dim.join(",") + "|" + (pending ? pending.uuid + ":" + (pending.bare ? "b" : pending.text) : "");
}

/** One pass over `events` (mutated in place: flags, the edited bubble's replacement, a queued echo's removal).
 *  `prevEditable` is the set the previous pass produced (undefined before the first), `pending` the session's
 *  pending rewind (null or undefined for none). Returns the new editable set, the pending entry still in force
 *  (null once retired) and whether the prefix below `bound` changed. */
export function reconcileRewindPass<E extends RewindEvent>(events: E[], prevEditable: Set<string> | undefined,
                                                            pending: PendingRewind | null | undefined, opts: RewindOpts): RewindResult {
  const before = rewindSig(events, prevEditable, pending, opts.bound);
  for (const e of events) if (e.rewound) delete e.rewound;
  let lastCompact = -1;
  for (let i = 0; i < events.length; i++) if (events[i].kind === "compact") lastCompact = i;
  const editable = new Set<string>();
  if (opts.sdk) {
    for (let i = lastCompact + 1; i < events.length; i++) {
      const e = events[i];
      if (e.kind === "user" && e.human && e.uuid && !e.romp && !e.interruptMarker && !e.uuid.startsWith(opts.optPrefix)) editable.add(e.uuid);
    }
  }
  let pr: PendingRewind | null = pending || null;
  if (pr) {
    const idx = events.findIndex((e) => e.kind === "user" && e.uuid === pr!.uuid);
    if (idx < 0 || opts.now - pr.ts > opts.ttlMs) {
      pr = null;                           // the branch landed (old uuid gone) — or the backstop expired
    } else if (pr.bare) {
      // DELETE rollback: the deleted bubble goes too — dim from it onward. No text replacement and no
      // queued-chip suppression (nothing was sent; the kernel's cut payload retires this in a beat).
      for (let j = idx; j < events.length; j++) events[j].rewound = true;
    } else {
      events[idx] = { ...events[idx], md: pr.text, pending: true, images: undefined };
      for (let j = idx + 1; j < events.length; j++) events[j].rewound = true;
      for (let j = events.length - 1; j > idx; j--) {
        const e = events[j];
        if (e.kind === "queued" && Array.isArray(e.texts)) {
          e.texts = e.texts.filter((t) => t.md !== pr!.text);
          if (!e.texts.length) events.splice(j, 1);
        }
      }
    }
  }
  return { editable, pending: pr, stale: rewindSig(events, editable, pr, opts.bound) !== before };
}
