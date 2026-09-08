// The chat's client-side PENDING SEND (render.ts registerOptimistic / reconcileOptimistic): a composer
// send shows its bubble the instant Enter is pressed and re-asserts it on every push until the kernel's
// payload accounts for the message. The DECISIONS live here, pure, so send-pending.test.ts executes
// them (the repo's extract-for-execution idiom); render.ts owns the DOM and the per-session maps.
//
// An entry has NO LIFETIME. It used to expire after 20 s ("a real send always echoes within this"), and
// the 2026-09-06 audit watched the case that assumption misses: the kernel's own echo was pruned early,
// nothing showed a message the CLI still held for 30 s, and the client's bubble gave up at 20 s — the
// send looked lost, then reappeared higher up. An entry now ends on EVENTS only:
//   - a LANDED user atom carrying the text, placed AFTER the send's anchor (below), that no earlier
//     pending send with the same text has already claimed,
//   - the kernel's NEVER-DELIVERED verdict on it, placed after the same anchor (its dropped-echo bubble
//     takes over, with the copy-to-composer and dismiss actions),
//   - the user's ✕ (render.ts's qx delegate drops the entry).
// A kernel PROVISIONAL (its echo atom, its queued bubble) only COVERS one of ours for the push it is
// visible on — the durable record is the kernel's (a persisted echo, the dropped marking, the fed-text
// guard in prune_live), but if it blinks, ours steps straight back in; a copy seen after the press also
// proves the kernel RECEIVED that one send (`received`, attributed per send like a landing). Nothing here
// reads a clock for a press-time entry: the frame resident at the press is older than the send by
// construction, so its anchor AND its placement floor are recorded by identity; only a LATE stamp (stampBase)
// compares stamps to order events.
//
// THE ANCHOR (2026-09-06 review): every decision is read from the events AFTER the send, never from a
// count of tail events. At the first reconcile after the press the entry records the uuid of the last
// stable kernel event (`at.after`) and the uuids of the user events that ALREADY carried the text
// (`at.seen`: an older identical message, an old echo, an undismissed never-delivered bubble). A
// landing, a verdict or a provisional counts for this send only when it sits after the anchor and is
// not in `seen`. ONE RECORD CAN CARRY SEVERAL SENDS (2026-09-07 review): the CLI takes back-to-back
// sends at one boundary as one user record with a text block each, and the kernel ships those blocks
// (`blocks`); such a record is as many copies as it has matching blocks, and `seen` lists its uuid once
// per copy already spoken for. The old form read the last 30 events and assumed the landing was near the tail — but an
// absorbed atom is placed at its SEND time, so after a gap in pushes (a sleep, a reconnect, a turn with
// many thinking and tool events) it sat far above the tail and, with the lifetime gone, the bubble never
// ended. When the anchor itself has left the resident window (the transcript grew past the wire tail),
// everything resident is after it, so the scan starts at the head.

export type SendBase = {
  after: string | null;   // uuid of the last stable kernel event at the press; null → nothing to anchor on, scan from the head
  place: string | null;   // PLACEMENT FLOOR: uuid of the last USER event at the press, an echo included (T252 second
                          //   review) — older than this send, so the bubble is drawn below it; the anchor skips echoes
                          //   (not a stable place to bound the landing scan), but for placement an echo is exactly the
                          //   earlier send the bubble must follow. null → no user event at the press, the anchor rules
  placeText?: string;     // that event's text: when its uuid leaves (the echo → landed swap), the landed atom carrying
                          //   the same text after the anchor is the floor…
  placeOrd?: number;      //   …found by ORDINAL: how many same-text user events sit after the anchor through the floor
                          //   at the press (the floor itself included). Events before the floor only ever swap echo →
                          //   landed in place, so the k-th match stays the floor while a LATER send of the same text
                          //   (its echo, its atom) lands beyond it and is never taken (third review). 0 → the floor sits
                          //   at or above the anchor, which already covers it: no fallback
  queuedForeign: string[]; // the texts of every visible copy the kernel's tail queue held at the press, one entry
                          //   per copy (a queued romp nudge, another client's message, an earlier press of this
                          //   client, a queue predating a page reload): at a press-time stamp every one of them
                          //   predates the press, so the send runs after them all — its bubble is drawn below that
                          //   group while a press-time copy is still queued and below their atoms once they land
                          //   (T252b). A LATE stamp leaves out the newest `own` copies of this send's text, the
                          //   ones the queued presumption reads as this press's. The group carries no uuid and is
                          //   no user event, so neither the anchor nor the floor ever saw it
  queuedForeignIds: string[]; // the IDS of the copies the tail queue held at the press, when the kernel gave them one
                          //   (T252c: qid on each queued copy, the same id its echo and its landed atom carry): the
                          //   exact reading — a copy is still queued while the group shows its id, and has landed
                          //   when a user event carries it — with no text or ordinal involved. Copies without an id
                          //   (an older kernel, a queue restored after a kernel death) stay in queuedForeign and take
                          //   the text path
  queuedResident?: Record<string, string[]>; // per foreign key: the uuids of user events after the anchor that
                          //   already carried the text AT THE PRESS (a never-delivered verdict for an earlier copy) —
                          //   not the queued copies' landings, so placement's ordinal counts them out while they are
                          //   still present; the kernel retires a verdict once a same-text record lands, and a
                          //   retired one must not keep the count unreachable (second and third reviews)
  seen: string[];         // uuids of the user events carrying the text that are background for this send: what
                          //   the press found, and what an earlier same-text entry claimed since — ONE ENTRY PER
                          //   COPY (a record of several sends lists its uuid once per spoken-for block)
  queued: number;         // copies of the text the kernel's queued bubble(s) already listed at the press
};

/** A placement floor recorded from an earlier send's kernel event: found by uuid, else by the `ord`-th user
 *  event after the anchor carrying `text` (the echo → landed swap keeps the position, changes the uuid). */
export type Floor = { uuid: string; text?: string; ord: number; qid?: string };   // qid: the earlier send's identity, followed exactly through the echo → landed swap

export type PendingSend = {
  text: string;        // the sent body, byte for byte — what the kernel echoes and the transcript lands
  body: string;        // `text` minus its image paths, whitespace-collapsed: an image send lands with the
                       //   paths rewritten to "[Image #N]" and stripped, so `text` itself can never match
  ts: number;          // press time (ms) — the bubble's identity (the ✕ names it), never a lifetime
  at?: SendBase;       // the send's place in the events (stamped by the first reconcile after the press)
  late?: boolean;      // the press found NO resident frame for the session (a placeholder tab, still
                       //   loading), so the stamp is taken at the first frame — which may already hold this
                       //   send's own echo or landing; stampBase then reads the events' own stamps
  imgPaths?: string[]; // dragged images → the bubble's thumbnails, and the image-aware landing match
  lost?: string;       // an event after the press that makes non-delivery LIKELY ("connection": the
                       //   socket dropped) — the bubble says "not confirmed" instead of "sending…"
  qid?: string;        // this send's IDENTITY once the kernel has shown it (T252c): the queued copy's id or the echo's
                       //   uuid, latched from the first copy attributed to this send by text and position — from then
                       //   on the landing, the cover and the hidden copy are decided by id (an event that carries an id
                       //   is ours only if it carries THIS one); an event without an id (an older kernel, tmux) keeps
                       //   deciding by text
  floors?: Floor[];    // kernel user events that belong to EARLIER-registered pending sends — their covering
                       //   echoes and their landed atoms, recorded as they are claimed (T252b): an earlier send's
                       //   message sits above this one whatever its text, so its bubble is drawn below them. Each
                       //   carries the event's text and its ordinal among same-text user events after this send's
                       //   anchor, so the echo → landed swap is followed even when the earlier entry is gone (its ✕)
  received?: boolean;  // the kernel has shown a copy of the text attributed to THIS send (an echo atom or
                       //   a queued copy after the press that no earlier same-text send claimed): the send
                       //   reached it, so a connection drop before or after cannot have lost it — `lost` is
                       //   cleared and never set again
};

/** The slice of a chat event the decisions read (render.ts's ChatEvent is a superset). */
export type TailEvent = {
  kind: string;
  md?: string;
  uuid?: string;
  qid?: string;         // a landed user atom: the id of the queued copy it lands (T252c; the kernel pairs them)
  qids?: string[];      // a record of SEVERAL sends: one id (or null) per text block, in block order
  ts?: string;          // the kernel's stamp for the event, ISO-8601 UTC (kernel.py `iso(t)`, whole seconds)
  absorbed?: boolean;
  undelivered?: boolean;
  images?: unknown[];
  texts?: { md?: string; hiddenByPending?: boolean; qid?: string; qts?: number; cancelable?: boolean }[];   // qid/qts: the copy's identity (T252c); hiddenByPending: render.ts hid this copy for a send drawn in place
  blocks?: string[];    // a user record the CLI wrote from SEVERAL sends taken at one boundary: one text per
                        //   block (kernel.py build_session ships them when there are two or more); `md` is
                        //   the blocks joined, so each block is a copy of its own send
};

export const OPT_PREFIX = "optimistic:";
export const isOptimisticUuid = (u?: string): boolean => !!u && u.startsWith(OPT_PREFIX);
export const isKernelEchoUuid = (u?: string): boolean => !!u && u.startsWith("echo:");
const collapse = (s: string): string => s.replace(/\s+/g, " ").trim();
/** The text a kernel event and a queued copy share once the kernel's wrapping is set aside (T252b review):
 *  - a romp-marked text (a nudge, a follow-up: `<!-- romp-… -->` in its tail) is queued as its split BODY but
 *    landed with the full text — a LEADING `> ` goal-quote block, the body, the marker comments (the kernel
 *    splits a landed record only for a human author). The comments go, and the leading quote block goes only
 *    when a romp marker is present — the kernel's own gate; a blockquote the user typed is part of their text;
 *  - the CLI's image chips (`[Image #N]`) and image paths go: an image-bearing message is queued with the path
 *    or the chip and landed with the chips stripped (kernel.py, images present), the same asymmetry
 *    landedCopies sets aside for this client's own sends. */
export const foreignKey = (s: string): string => {
  const marked = /<!--\s*romp-/.test(s);
  let t = s.replace(/<!--[\s\S]*?-->/g, " ");
  if (marked) {
    const lines = t.split("\n");
    let i = 0;
    while (i < lines.length && (/^\s*>/.test(lines[i]) || (i > 0 && !lines[i].trim()))) i++;
    if (i > 0 && lines.slice(0, i).some((l) => /^\s*>/.test(l))) t = lines.slice(i).join("\n");
  }
  // the CLI's own extraction (kernel _IMG_PATH_RE): a leading delimiter, a path from `/` or `~/`, the extension
  // at a word boundary — only the PATH is replaced, so whatever delimiter wrapped it stays on both sides
  t = t.replace(/\[Image #\d+\]/g, "").replace(/(^|[\s'"`(])((?:~\/|\/)[^\s'"`()]+\.(?:png|jpe?g|gif|webp))\b/gi, "$1");
  return collapse(t.replace(/"/g, ""));   // a quoted path may leave its quotes behind: set aside on both sides (noq)
};
/** Whether a user event carries `text` (on the foreignKey) in its md or any of its blocks — a record the CLI
 *  wrote from several queued messages taken at one boundary lists each as a block (T252b review). */
const carriesText = (e: TailEvent, text: string): boolean => carriedCopies(e, text) > 0;
/** How many copies of `text` (on the foreignKey) a user event carries: one when its md IS the text, else one per
 *  matching block — a record the CLI wrote from several queued messages taken at one boundary is as many copies
 *  as it has matching blocks, the shape textCopies reads for this client's own sends (fourth review). */
const carriedCopies = (e: TailEvent, text: string): number => {
  if (e.kind !== "user" || isOptimisticUuid(e.uuid)) return 0;
  const k = foreignKey(text);
  // an image-only text keys to nothing: only an event that carries images can be its carrier — a reminders-only
  // user record (a task notification landed mid-turn, md "") is not (the kernel's own by-text prune refuses an
  // empty key the same way; third review)
  if (!k) return Array.isArray(e.images) && e.images.length > 0 && (!e.md || !foreignKey(e.md)) ? 1 : 0;
  if (typeof e.md === "string" && foreignKey(e.md) === k) return 1;
  let n = 0;
  if (Array.isArray(e.blocks)) for (const b of e.blocks) if (typeof b === "string" && foreignKey(b) === k) n++;
  return n;
};

/** `text` with its shipped image paths removed (quoted or bare, however the composer joined them). */
export function pendingBody(text: string, imgPaths?: string[]): string {
  let t = text;
  for (const p of imgPaths || []) t = t.split('"' + p + '"').join(" ").split(p).join(" ");
  return collapse(t);
}

export function newPending(text: string, imgPaths?: string[], now: number = Date.now()): PendingSend {
  return { text, body: pendingBody(text, imgPaths), ts: now, imgPaths };
}

/** EXACT text match, trimmed: the composer trims what it sends and the kernel strips what it lands
 *  (`" ".join(blocks).strip()`; a follow-up's body after `_split_followup`), so the two agree byte for
 *  byte apart from edge whitespace. Never a substring test — "test" is not "test the continue button",
 *  and a landing of the longer message must not retire the shorter send (2026-09-06 review). */
const sameText = (md: string, text: string): boolean => md.trim() === text.trim();

/** How many COPIES of the send's text a user event carries: one when its md IS the text; otherwise one
 *  per text block that is. The CLI takes back-to-back sends at one boundary as ONE user record with a
 *  block per send (the shape the kernel's own echo prune, `_atom_user_texts`, was written for), and the
 *  event's md is the blocks joined — so with an md-only test none of those sends' bubbles ever ended
 *  (2026-09-07 review). The kernel ships `blocks` only when there are two or more. */
function textCopies(e: TailEvent, p: PendingSend): number {
  if (typeof e.md === "string" && sameText(e.md, p.text)) return 1;
  let n = 0;
  if (Array.isArray(e.blocks)) for (const b of e.blocks) if (typeof b === "string" && sameText(b, p.text)) n++;
  return n;
}

/** How many copies of this send a LANDED user atom carries: a user event whose uuid is not the kernel's
 *  echo prefix and whose md (or one of whose blocks) IS the text — or, for an image send, whose md is
 *  the body and which carries images (the CLI rewrote the paths to "[Image #N]"; the kernel strips the
 *  placeholders and renders the pictures, so the paths are gone from the text; a quoted path may leave
 *  its quotes behind, so those are set aside on both sides). */
export function landedCopies(e: TailEvent, p: PendingSend): number {
  if (e.kind !== "user" || typeof e.md !== "string" || isKernelEchoUuid(e.uuid)) return 0;
  if (p.qid && (e.qid || (Array.isArray(e.qids) && e.qids.length)))   // identity decides (T252c): ours only if it carries THIS send's id
    return e.qid === p.qid || (Array.isArray(e.qids) && e.qids.includes(p.qid)) ? 1 : 0;
  const n = textCopies(e, p);
  if (n) return n;
  if (p.imgPaths && p.imgPaths.length && Array.isArray(e.images) && e.images.length > 0) {
    const noq = (s: string) => collapse(s.replace(/"/g, ""));
    return noq(e.md) === noq(p.body) ? 1 : 0;
  }
  return 0;
}
export const landedIn = (e: TailEvent, p: PendingSend): boolean => landedCopies(e, p) > 0;

/** How many copies of the send's text a kernel queued bubble lists. */
function queuedCopies(e: TailEvent, p: PendingSend): number {
  if (e.kind !== "queued" || !Array.isArray(e.texts)) return 0;
  let n = 0;
  for (const x of e.texts) if (typeof x.md === "string" && sameText(x.md, p.text)) n++;
  return n;
}

/** The kernel's own PROVISIONAL copies of the send: its queued bubble's, or its unlanded echo atom (one
 *  text, the send's own — the kernel builds every echo from a single block). A never-delivered echo is a
 *  VERDICT, not a provisional (lostIn), and never suppresses a bubble. */
function provisionalCopies(e: TailEvent, p: PendingSend): number {
  if (e.kind === "queued") return queuedCopies(e, p);
  if (!(e.kind === "user" && isKernelEchoUuid(e.uuid) && !e.undelivered)) return 0;
  if (p.qid) return e.uuid === p.qid ? 1 : 0;         // the echo's uuid IS the copy's id (T252c)
  return textCopies(e, p);
}
export const provisionalIn = (e: TailEvent, p: PendingSend): boolean => provisionalCopies(e, p) > 0;

/** The kernel's verdict that the send was LOST: its echo, flagged never-delivered (the CLI died holding
 *  it, or the session moved past it). That bubble carries the text and the resend/dismiss actions. */
function lostCopies(e: TailEvent, p: PendingSend): number {
  if (!(e.kind === "user" && !!e.undelivered)) return 0;
  if (p.qid && isKernelEchoUuid(e.uuid)) return e.uuid === p.qid ? 1 : 0;   // the verdict is the echo, by id (T252c)
  return textCopies(e, p);
}
export const lostIn = (e: TailEvent, p: PendingSend): boolean => lostCopies(e, p) > 0;

/** The copies of the send a USER event carries in whichever role it plays — the roles are disjoint (a
 *  landed atom is never the kernel's echo; the verdict is the flagged echo), so at most one is non-zero. */
const copiesIn = (e: TailEvent, p: PendingSend): number =>
  e.kind !== "user" ? 0 : landedCopies(e, p) || lostCopies(e, p) || provisionalCopies(e, p);

/** How many copies of the event `u` are already spoken for from this send's point of view. */
const spokenFor = (at: SendBase, u: string): number => { let n = 0; for (const s of at.seen) if (s === u) n++; return n; };

/** A kernel event a pending send can be anchored to: it has a uuid the kernel will keep. The client's own
 *  injections and the kernel's echo atoms are excluded — an echo is replaced by the landed atom (a new
 *  uuid) the moment its text lands, so it is not a stable place. */
const stableUuid = (e: TailEvent): boolean => !!e.uuid && !isOptimisticUuid(e.uuid) && !isKernelEchoUuid(e.uuid);

/** The kernel's second for an event, off its ISO stamp (kernel.py `iso(t)`); null when it carries none. */
const eventSecond = (e: TailEvent): number | null => {
  if (!e.ts) return null;
  const ms = Date.parse(e.ts);
  return isNaN(ms) ? null : Math.floor(ms / 1000);
};

/** Where this send sits among the kernel's events, read once at the first reconcile after the press.
 *
 *  At a PRESS-TIME stamp (the normal path) everything resident predates the send by construction — the
 *  frame arrived before the keystroke — so the whole frame is background and no stamp is read. A LATE
 *  stamp (`p.late`: the press found no frame — a placeholder tab, still loading) reads a frame that may
 *  already hold this send's own echo or landing, and it used to read them as background: our dashed
 *  bubble sat beside the kernel's echo, or a landed send's bubble never ended (2026-09-06 review, round
 *  3). So a late stamp reads the events' own stamps: an event the kernel stamped at or after the press's
 *  second is not before the send — neither the anchor nor background. Events with no stamp keep the
 *  press-time reading, with ONE exception, the queued bubble (below).
 *
 *  THE QUEUED PRESUMPTION (round 4): the kernel's queued bubble carries no stamp at all — its texts are
 *  the queue's bodies and positions — so a late stamp cannot read which of its copies predate the press.
 *  A late entry therefore PRESUMES the newest `own` copies of its text in the frame (one per identical
 *  send pressed against the same placeholder frame; the caller counts them) are this press's own, not
 *  background: the press just happened, and a copy of the same text that appeared with the first frame
 *  is the one the kernel added at its receipt. Without this, a send into a busy or held session whose
 *  first frame already listed it recorded that copy as background, so the entry never got a position
 *  until the CLI took the text: our bubble sat beside the kernel's copy for the whole wait, and its ✕
 *  would have cancelled the real queued send by body. The presumption's cost, stated: when the kernel had
 *  NOT yet received the send as the frame was built and an older identical message sits in the queue (a
 *  held queue keeps one for hours), that older copy is read as this send's — receipt is presumed, and a
 *  send lost on its way to the kernel hides behind the older copy until the queue moves. That case needs
 *  the same text queued twice around a page load; the double bubble needed only a send into a queue. A
 *  stamp on each queued text would make the reading exact and remove the presumption.
 *
 *  THE CLOCK ASSUMPTION, stated once: the press is the client's clock (ms); the events wear the kernel
 *  host's clock in whole seconds — the echo atom is stamped `int(time.time())` at the kernel's receipt
 *  of the send (sdk_backend.py `send`, before the CLI can see the text), the landed atom by the CLI's
 *  transcript record, at or after that (T237b), and both reach the client as `ts = iso(t)`. The bound
 *  holds when the two clocks agree to the second: exactly for a client on the kernel's machine (the
 *  VS Code webview, the served page there), and for a phone as well as its clock is set. A client
 *  running BEHIND the kernel reads an older identical message stamped inside the skew as this send's;
 *  one running AHEAD reads this send's own copy as background, which is the pre-fix reading. The bound
 *  is confined to the late stamp because that is the only stamp that can meet the send's own records,
 *  and because at a press-time stamp it could only misfire (an identical message that landed within
 *  the press's second would read as this send's). */
export function stampBase(events: TailEvent[], p: PendingSend, own: number = p.late ? 1 : 0): SendBase {
  const pressS = p.late ? Math.floor(p.ts / 1000) : Infinity;
  const beforeSend = (e: TailEvent): boolean => { const s = eventSecond(e); return s === null || s < pressS; };
  let after: string | null = null;
  for (let i = events.length - 1; i >= 0; i--) if (stableUuid(events[i]) && beforeSend(events[i])) { after = events[i].uuid!; break; }
  let place: string | null = null, placeText: string | undefined, placeOrd = 0;
  let floorIdx = -1;
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.kind === "user" && e.uuid && !isOptimisticUuid(e.uuid) && beforeSend(e)) { place = e.uuid; placeText = typeof e.md === "string" ? e.md : undefined; floorIdx = i; break; }
  }
  if (floorIdx >= 0 && placeText !== undefined) {
    let anchorIdx = -1;
    if (after !== null) for (let i = events.length - 1; i >= 0; i--) if (events[i].uuid === after) { anchorIdx = i; break; }
    for (let i = anchorIdx + 1; i <= floorIdx; i++) {
      const e = events[i];
      if (e.kind === "user" && !isOptimisticUuid(e.uuid) && typeof e.md === "string" && sameText(e.md, placeText)) placeOrd++;
    }
  }
  const seen: string[] = [];
  let queued = 0;
  for (const e of events) {
    if (e.kind === "queued") { queued += queuedCopies(e, p); continue; }
    if (e.kind !== "user" || !e.uuid || isOptimisticUuid(e.uuid) || !beforeSend(e)) continue;
    const n = copiesIn(e, p);
    for (let k = 0; k < n; k++) seen.push(e.uuid);   // once per COPY: a record of several sends is several
  }
  // every visible copy the tail queue held at the press is ahead of this send (T252b): a press-time frame
  // predates the press by construction, so none of them is this send's — a same-text copy is an older send's
  // (another client, an earlier press). A late stamp leaves out the newest `own` copies of this text (the
  // queued presumption). Beside them, the carriers of each text already resident after the anchor: those
  // are not the queued copies' landings, so placement counts them out (second review).
  const queuedForeign: string[] = [];
  const queuedForeignIds: string[] = [];
  const queuedResident: Record<string, string[]> = {};
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.kind !== "queued") continue;
    let skipOwn = p.late ? own : 0;
    const copies = (e.texts || []).filter((t) => typeof t.md === "string" && !t.hiddenByPending);
    for (let k = copies.length - 1; k >= 0; k--) {
      const md = copies[k].md as string;
      if (skipOwn > 0 && foreignKey(md) === foreignKey(p.text)) { skipOwn--; continue; }
      if (copies[k].qid) queuedForeignIds.unshift(copies[k].qid!);   // an identified copy takes the id path first (T252c)…
      queuedForeign.unshift(md);                                     //   …and every copy keeps the text path as its fallback
    }
    break;
  }
  if (queuedForeign.length) {
    let anchorIdx = -1;
    if (after !== null) for (let i = events.length - 1; i >= 0; i--) if (events[i].uuid === after) { anchorIdx = i; break; }
    for (const f of queuedForeign) {
      const k = foreignKey(f);
      if (k in queuedResident) continue;
      const us: string[] = [];
      for (let i = anchorIdx + 1; i < events.length; i++) if (carriesText(events[i], f) && events[i].uuid) us.push(events[i].uuid!);
      queuedResident[k] = us;
    }
  }
  // the queued presumption (above): a late stamp's newest `own` copies are this press's, so the count of
  // background copies stops short of them — at zero when the frame lists fewer than presumed (the kernel
  // had not received every press yet; the copies still to come cover those entries in order)
  return { after, place, placeText, placeOrd, queuedForeign, queuedForeignIds, queuedResident, seen, queued: Math.max(0, queued - (p.late ? own : 0)) };
}

/** The first index AFTER the send's anchor — or 0 when there is no anchor, or when the anchor has left the
 *  resident window (then everything resident is later than the send). */
export function scanFrom(events: TailEvent[], at: SendBase): number {
  if (at.after === null) return 0;
  for (let i = events.length - 1; i >= 0; i--) if (events[i].uuid === at.after) return i + 1;
  return 0;
}

export type Reconciled = {
  keep: PendingSend[];                        // still pending after this push
  inject: PendingSend[];                      // …and drawn by us: not covered by the kernel's echo atom (a queued
                                              //   copy does not cover — ours stays in place and the copy is hidden, T252)
  unqueue: PendingSend[];                     // …whose kernel cover is a QUEUED copy: the caller hides that copy
  landed: { p: PendingSend; idx: number }[];  // retired by a landing; idx = the landed event's index — the slot the bubble held
  lost: PendingSend[];                        // retired by the kernel's never-delivered verdict
};

/** One push's decision for a session's pending sends, read off the KERNEL's events (the caller has
 *  already stripped its own injections). Entries are read in registration order, and ONE kernel record
 *  accounts for ONE entry — the same rule for a landing and for the kernel's provisional copy:
 *   - the k-th landing after the anchor retires the k-th pending send with that text, and a landing an
 *     earlier entry took is background (`seen`) for every later entry with the same text — two
 *     identical sends in flight used to both retire on the first landing (2026-09-06 review). A record
 *     of SEVERAL sends (`blocks`) is as many landings as it has matching blocks, so the claims on one
 *     record are COUNTED (this push in `claimed`, for good in `seen`), never booleaned — two sends the
 *     CLI took as one record used to leave both bubbles pending for ever (2026-09-07 review);
 *   - the k-th kernel copy of the text after the anchor — an echo atom no earlier entry claimed, or a
 *     queued copy beyond the entry's press-time count — covers the k-th pending send with that text: it
 *     hides that send's bubble for this push and proves the kernel received THAT send (`received`). A
 *     claimed echo joins later same-text entries' `seen` for good; queued copies carry no identity, so
 *     they are handed out by position within a push (the copies an entry's press listed are its
 *     background). One echo used to mark every same-text entry received and clear every "not confirmed"
 *     (2026-09-06 review, round 3): with two identical sends in flight and one of them lost, the lost
 *     one read "sending…" for good, and nothing could ever mark it.
 *  Identical texts carry no identity of their own, so WHICH send a copy belongs to is attributed by
 *  order, exactly as landings are; the COUNT of confirmed sends is what the kernel's records support.
 *  When the kernel hides a fed send's echo behind a same-text queued copy (its chat dedups by text), a
 *  received send can read "not confirmed" after a drop until a copy of its own shows; that clears on the
 *  next kernel copy, and the error is toward "not confirmed", never toward a false "sending…". */
export function reconcilePending(events: TailEvent[], list: PendingSend[]): Reconciled {
  // First reconcile after the send: whatever the events ALREADY hold for this text is background — an
  // older identical message, an old echo, an undismissed never-delivered bubble — not this send. Only
  // what appears after the anchor, beyond that set, is this send's (the user 2026-08-09, who watched
  // resends vanish in the call that created them; the 2026-09-06 review, which watched a resend of a
  // never-delivered message retired as lost by the old verdict). Late entries stamped against this frame
  // each presume ONE of its queued copies of their text is their own (stampBase's queued presumption), so
  // identical sends pressed against the same placeholder frame own as many copies as there were presses.
  const lateOwn = new Map<string, number>();
  for (const p of list) if (!p.at && p.late) lateOwn.set(p.text, (lateOwn.get(p.text) || 0) + 1);
  for (const p of list) if (!p.at) p.at = stampBase(events, p, p.late ? lateOwn.get(p.text) || 1 : 0);
  const r: Reconciled = { keep: [], inject: [], unqueue: [], landed: [], lost: [] };
  const claimed = new Map<string, number>();           // "index\0text" → copies of that text in that landing taken by earlier entries THIS push
  const takenCopies = new Map<string, Set<number>>();  // text → queued-copy positions taken by an earlier entry THIS push
  // an earlier entry's covering echo / landed atom is a FLOOR for every entry registered after it (T252b),
  // recorded with its text and its ordinal among same-text user events after THAT entry's anchor, so the
  // echo → landed swap can be followed by text when the earlier entry is gone before its atom lands (its ✕)
  const floorFor = (owner: PendingSend, at: number) => {
    const u = events[at].uuid;
    if (!u) return;
    const i = list.indexOf(owner);
    for (const q of list.slice(i + 1)) {
      if (!q.floors) q.floors = [];
      if (q.floors.some((f) => f.uuid === u)) continue;
      const text = owner.text;   // the earlier SEND's own text — a record of several sends carries it as a block, and its md is the blocks joined
      let ord = 0;
      if (q.at) for (let j = scanFrom(events, q.at); j <= at; j++) ord += carriedCopies(events[j], text);
      q.floors.push({ uuid: u, text, ord, qid: owner.qid });
    }
  };
  for (const p of list) {
    const at = p.at!;
    const from = scanFrom(events, at);
    let landedIdx = -1, lostIdx = -1, echoIdx = -1, copies = 0, idCopy = -1;
    for (let i = from; i < events.length; i++) {
      const e = events[i];
      if (e.kind === "queued") {
        copies += queuedCopies(e, p);
        // the kernel's copy of THIS send, by id (T252c): the cover, wherever the copy sits in the group
        if (p.qid && (e.texts || []).some((t) => t.qid === p.qid)) idCopy = i;
        continue;
      }
      // the copies of this event that are NOT this send's: background at the stamp, or claimed by an
      // entry retired since (`seen`); a landing an earlier entry took this push is counted in `claimed`
      const spoken = e.uuid ? spokenFor(at, e.uuid) : 0;
      if (landedIdx < 0 && landedCopies(e, p) > spoken + (claimed.get(i + "\0" + p.text) || 0)) { landedIdx = i; continue; }
      if (lostIdx < 0 && lostCopies(e, p) > spoken) { lostIdx = i; continue; }
      if (echoIdx < 0 && provisionalCopies(e, p) > spoken) echoIdx = i;   // the first echo no earlier entry claimed (`seen`)
    }
    // ONE kernel copy covers ONE send: an unclaimed echo atom first — its uuid is then background for
    // every later same-text entry, this push and every push after (the claim must outlive the claimant:
    // a ✕ on it must not hand its echo to the next entry; an echo is one text, so one entry in `seen` is
    // the whole of it) — else the first queued copy beyond this entry's press-time count that no
    // earlier entry took this push.
    let covered = false, byQueued = false;
    if (echoIdx >= 0) {
      covered = true;
      const u = events[echoIdx].uuid;
      if (u) for (const q of list) if (q !== p && q.at && q.text === p.text && !q.at.seen.includes(u)) q.at.seen.push(u);
      if (!p.qid && u) p.qid = u;                  // the echo's uuid is the copy's id: latched (T252c)
      floorFor(p, echoIdx);
    } else if (p.qid && idCopy >= 0) {
      covered = true; byQueued = true;              // our identified copy is in the queue: exact, whatever its position
    } else if (!p.qid && copies > at.queued) {
      const taken = takenCopies.get(p.text) || new Set<number>();
      for (let k = at.queued; k < copies; k++) if (!taken.has(k)) { taken.add(k); covered = true; byQueued = true; break; }
      takenCopies.set(p.text, taken);
      if (covered) {                                // latch the identity of the copy just attributed, when the kernel gave it one
        let seen = 0;
        outer: for (let i = from; i < events.length; i++) {
          const e = events[i];
          if (e.kind !== "queued") continue;
          for (const t of e.texts || []) {
            if (typeof t.md !== "string" || !sameText(t.md, p.text)) continue;
            if (seen === [...taken].sort((a, b) => a - b).pop()) { if (t.qid) p.qid = t.qid; break outer; }
            seen++;
          }
        }
      }
    }
    if (covered) p.received = true;             // the kernel holds this send: proven once, latched
    if (p.received) p.lost = undefined;         // the drop is older news than the kernel's own copy
    if (landedIdx >= 0) {
      const ck = landedIdx + "\0" + p.text;             // per text: a record of two DIFFERENT sends is one landing for each
      claimed.set(ck, (claimed.get(ck) || 0) + 1);
      r.landed.push({ p, idx: landedIdx });
      floorFor(p, landedIdx);
      continue;
    }
    if (lostIdx >= 0) { r.lost.push(p); floorFor(p, lostIdx); continue; }   // the verdict IS the earlier send's echo: a floor for later sends
    r.keep.push(p);
    // The kernel's ECHO atom covers ours: the kernel draws that atom itself, at the send time. A QUEUED copy
    // does not: it sits in the kernel's group at the tail, and the bubble the user watches is ours, at its
    // send slot — so ours stays drawn and the caller hides that copy, one bubble per message (T252).
    if (!covered || byQueued) r.inject.push(p);
    if (covered && byQueued) r.unqueue.push(p);
  }
  // Every landing claimed this push is spoken for: one copy per claim becomes background for every
  // pending send with the same text that STAYS, on every push after (the retired entry's claim would
  // otherwise leave with it, and the next identical send would retire on a record that was never its
  // own). Once per claim — the claimant leaves the list with this push — so `seen` counts exactly.
  for (const { p, idx } of r.landed) {
    const u = events[idx].uuid;
    if (u) for (const q of r.keep) if (q.text === p.text) q.at!.seen.push(u);
  }
  return r;
}

/** The entry a ✕ on a pending bubble removes: the one the bubble NAMES (`ts`, ridden on the ✕ as
 *  data-qts) — or, for a ✕ on the KERNEL's own queued/parked copy, which names no entry of ours, the
 *  first pending send with that text, the one the kernel's first copy covers. Same-text entries carry
 *  different states (lost, received), and the first-with-the-text lookup the ✕ used for every bubble
 *  dropped the wrong one from a "not confirmed · sending…" pair: the next push brought the dismissed
 *  bubble back and the other was gone without a gesture (2026-09-06 review, round 3). Returns the removed
 *  entry; undefined when none matched — a bubble whose entry a push already retired removes nothing,
 *  never a neighbour with the same text. */
export function dropPending(list: PendingSend[], text: string, ts?: number): PendingSend | undefined {
  const i = ts !== undefined ? list.findIndex((p) => p.ts === ts && p.text === text) : list.findIndex((p) => p.text === text);
  return i >= 0 ? list.splice(i, 1)[0] : undefined;
}

/** Where the caller draws the pending bubbles: each at the index right AFTER its anchor — the last stable
 *  kernel event at the press — so the steps that stream in afterwards land below it and the absorbed atom,
 *  which the kernel places at the send time, replaces it in the same slot (T252, the user 2026-09-07: the
 *  bubble used to ride the tail and then vanish, its message reappearing higher up under a header and a
 *  cue). Sends that share an anchor form ONE group, in send order; groups come highest index first, so a
 *  caller splicing them into the events array bottom-up keeps every lower index valid. No anchor (nothing
 *  stable at the press) or an anchor that left the resident window puts the bubble at the head: everything
 *  resident is later than the send (scanFrom). */
export type InjectionGroup = { idx: number; sends: PendingSend[] };
export function injectionGroups(events: TailEvent[], inject: PendingSend[]): InjectionGroup[] {
  const byIdx = new Map<number, PendingSend[]>();
  for (const p of inject) {
    const idx = p.at ? placementIndex(events, p) : events.length;
    const g = byIdx.get(idx);
    if (g) g.push(p); else byIdx.set(idx, [p]);
  }
  return [...byIdx.entries()].sort((x, y) => y[0] - x[0]).map(([idx, sends]) => ({ idx, sends }));
}

/** The slot for one send: after its scan anchor, and after its PLACEMENT FLOOR — the last user event at the
 *  press (an earlier send's echo atom, a never-delivered bubble, a landed atom), which the anchor rule skips
 *  (an echo is not a stable place to bound the LANDING scan, since the landed atom replaces it under a new
 *  uuid) but which is older than this send all the same. Without it a second message pressed while the
 *  first's echo was the newest event sat ABOVE it until both landed (review of the first cut). The floor is
 *  found by identity: its uuid, or — once the echo has become the landed atom — the k-th user event after
 *  the anchor carrying its text, k being how many such events sat through the floor at the press (a later
 *  send of the same text lands beyond the k-th and is never taken; the last match used to be, and pulled
 *  the bubble to the tail under a newer message — third review). A floor at or above the anchor is already
 *  covered by the anchor. Never by comparing the client's clock with the kernel's stamps: the frame
 *  resident at the press is older than the send by construction, and a clock comparison re-inverted the
 *  order whenever the kernel clock led the client by more than the gap between two presses (second
 *  review). A user event that arrives after the press is a later send and stays below the bubble — with two
 *  exceptions that are older than the send all the same (T252b): an EARLIER pending send's covering echo or
 *  landed atom (`floors`, recorded as reconcilePending claims them, whatever their text), and the texts the
 *  kernel's tail queue held at the press (`queuedForeign`: the bubble sits below that group while it holds
 *  them, and below their atoms once they land — the group carries no uuid and is no user event, so the
 *  anchor and the floor never saw it, and a send was drawn above texts it runs after). */
export function placementIndex(events: TailEvent[], p: PendingSend): number {
  const at = p.at!;
  const base = scanFrom(events, at);
  let idx = base;
  if (at.place && at.placeOrd && at.placeOrd > 0) {
    let found = -1;
    for (let j = events.length - 1; j >= base; j--) if (events[j].uuid === at.place) { found = j + 1; break; }
    if (found < 0 && at.placeText !== undefined) {
      let n = 0, last = -1;
      for (let j = base; j < events.length; j++) {
        const e = events[j];
        if (e.kind === "user" && !isOptimisticUuid(e.uuid) && typeof e.md === "string" && sameText(e.md, at.placeText)) {
          n++; last = j;
          if (n === at.placeOrd) { found = j + 1; break; }   // the floor, under its landed uuid
        }
      }
      if (found < 0 && last >= 0) found = last + 1;         // fewer matches than at the press (a pruned echo): the newest stands in
    }
    if (found > idx) idx = found;
  }
  // the k-th user event after the anchor carrying `text` (md or a block) — the ordinal reading that never takes a
  // LATER copy of the same words; -1 when fewer than k have landed
  const kthCarrier = (text: string, k: number): { idx: number; count: number } => {
    let n = 0, last = -1;
    for (let j = base; j < events.length; j++) {
      const c = carriedCopies(events[j], text);
      if (!c) continue;
      n += c; last = j;
      if (n >= k) return { idx: j, count: n };
    }
    return { idx: last, count: n };
  };
  // an earlier pending send's echo or landed atom: below it, whatever its text — by uuid, else by its text's ordinal
  for (const f of p.floors || []) {
    let found = -1;
    if (f.qid) for (let j = events.length - 1; j >= base; j--) if (events[j].qid === f.qid || events[j].uuid === f.qid) { found = j + 1; break; }   // by identity (T252c)
    if (found < 0) for (let j = events.length - 1; j >= base; j--) if (events[j].uuid === f.uuid) { found = j + 1; break; }
    if (found < 0 && f.text !== undefined && f.ord > 0) { const k = kthCarrier(f.text, f.ord); if (k.idx >= 0) found = k.idx + 1; }
    if (found > idx) idx = found;
  }
  // the identified copies the kernel's queue held at the press (T252c): a copy is still queued while the group shows
  // its id, and has landed when a user event carries it — exact, no text, no count
  // the keys whose identified copies RESOLVED by id this frame skip the text path below: the text path is the
  // fallback for a copy whose landing lost its id (a kernel restart between feed and landing) or an older kernel
  const resolvedKeys = new Set<string>();
  if (at.queuedForeignIds && at.queuedForeignIds.length) {
    let groupIdx = -1;
    for (let j = events.length - 1; j >= base; j--) if (events[j].kind === "queued") { groupIdx = j; break; }
    for (const id of at.queuedForeignIds) {
      let floor = -1, text: string | undefined;
      for (let j = events.length - 1; j >= base; j--) {
        const e = events[j];
        if (e.qid === id || (Array.isArray(e.qids) && e.qids.includes(id))) { floor = j + 1; text = typeof e.md === "string" ? e.md : undefined; break; }
      }
      if (floor < 0 && groupIdx >= 0) {
        const c = (events[groupIdx].texts || []).find((t) => t.qid === id && !t.hiddenByPending);
        if (c) { floor = groupIdx + 1; text = c.md; }
      }
      if (floor > idx) idx = floor;
      if (floor >= 0 && text !== undefined) resolvedKeys.add(foreignKey(text));
    }
  }
  // the texts the kernel's queue held at the press, COUNTED per text: the press-time copies are the first k
  // landings of that text, so the floor is the k-th carrier (never a later copy another client sent), and the
  // group is a floor only while a press-time copy is still queued (fewer than k have landed)
  if (at.queuedForeign && at.queuedForeign.length) {
    const counts = new Map<string, { text: string; n: number }>();
    for (const f of at.queuedForeign) { const k = foreignKey(f); const c = counts.get(k); if (c) c.n++; else counts.set(k, { text: f, n: 1 }); }
    let groupIdx = -1;
    for (let j = events.length - 1; j >= base; j--) if (events[j].kind === "queued") { groupIdx = j; break; }
    for (const { text, n: copies } of counts.values()) {
      const key = foreignKey(text);
      if (resolvedKeys.has(key)) continue;          // the identity path placed this key exactly
      const residents = (at.queuedResident ||= {})[key] ||= [];
      // The kernel's queued copies carry no identity, so which landing is the press-time copy's is read off the
      // GROUP (fourth review): while it still shows a copy of the key, the press-time copy has not landed, so every
      // carrier landed so far was someone else's — an identical text the kernel had already forwarded (canned
      // texts: the Continue button, a retry, a repeated nudge) — and is learned as a resident, so the count keeps
      // looking past it. Two costs, stated: a same-text copy another client queues after the press-time one landed
      // reads as the press-time one and keeps this bubble below it until this send lands; and the learning needs the
      // frame in which the group still shows the key — a socket down from before the fed copy landed until after the
      // press-time copy was taken (a laptop asleep for a whole turn) delivers both landings at once, nothing is
      // learned, and the bubble sits between them until this send lands (fifth review). A stamp on each queued copy
      // would make both readings exact.
      const groupShows = groupIdx >= 0 && (events[groupIdx].texts || []).some((t) => typeof t.md === "string" && !t.hiddenByPending && foreignKey(t.md) === key);
      if (groupShows) for (let j = base; j < events.length; j++) { const e = events[j]; if (e.uuid && carriedCopies(e, text) && !residents.includes(e.uuid)) residents.push(e.uuid); }
      const resident = residents.reduce((acc, u) => { const e = events.find((x) => x.uuid === u); return acc + (e ? carriedCopies(e, text) : 0); }, 0);
      const n = copies + resident;   // the carriers resident at the press, and those learned since, come first
      const k = kthCarrier(text, n);
      let floor = k.idx >= 0 ? k.idx + 1 : -1;
      if (groupShows) floor = Math.max(floor, groupIdx + 1);
      if (floor > idx) idx = floor;
    }
  }
  return idx;
}

/** Which copy of `text` in a kernel queued group the caller hides for a send drawn at its own slot: the NEWEST
 *  copy not already hidden (the group lists the queue in order; ours is the latest press with that text), or -1
 *  when there is none — including when the only copies are ones the kernel marked cancelable:false (no recall
 *  exists there: a tmux queue). That copy stays the one bubble shown, with its honest tooltip, and ours is
 *  suppressed as before: hidden behind our bubble's ✕ it offered a cancel the kernel would refuse (review of the
 *  first cut). */
export function queuedCopyToHide(texts: { md?: string; cancelable?: boolean; hiddenByPending?: boolean; optimistic?: boolean; qid?: string }[], text: string, qid?: string): number {
  if (qid) {   // OUR copy by identity (T252c): never the newest same-text one
    const k = texts.findIndex((t) => t.qid === qid && !t.hiddenByPending && !t.optimistic);
    if (k >= 0) return texts[k].cancelable === false ? -1 : k;
  }
  for (let k = texts.length - 1; k >= 0; k--) {
    const t = texts[k];
    if (t.hiddenByPending || t.optimistic || typeof t.md !== "string" || !sameText(t.md, text)) continue;
    if (t.cancelable === false) return -1;
    return k;
  }
  return -1;
}

/** The bare group's one-line header, from its bubbles' OWN states: the lost ones (the connection dropped
 *  after the press and nothing has confirmed them) read "not confirmed", the rest "sending…". A group
 *  used to read "N not confirmed" when ANY bubble was lost, and kept that label for the survivors after
 *  a ✕ (2026-09-06 review). */
export type BareLabelPart = { text: string; lost: boolean };
export function bareGroupLabel(nLost: number, nSending: number): { parts: BareLabelPart[]; title: string } {
  const parts: BareLabelPart[] = [];
  if (nLost > 0) parts.push({ text: nLost === 1 ? "not confirmed" : `${nLost} not confirmed`, lost: true });
  if (nSending > 0) parts.push({ text: nSending === 1 ? "sending…" : `sending ${nSending}…`, lost: false });
  const lostTitle = "The connection dropped after " + (nLost === 1 ? "this was" : "these were")
    + " sent, and romp has not confirmed the session has " + (nLost === 1 ? "it" : "them") + ". ✕ moves "
    + (nLost === 1 ? "it" : "one") + " back to the composer to send again.";
  const sendingTitle = "on its way to the session — cancellable until the session takes it";
  const title = nLost > 0 && nSending > 0 ? lostTitle + " The rest: " + sendingTitle + "."
    : nLost > 0 ? lostTitle : sendingTitle;
  return { parts, title };
}
