// A page's VIEWS WRITES in flight, and what the kernel's answer to one of them means (the user
// 2026-09-05, who lost a batch of tag renames and assignments): every write of the views blob —
// a targeted tag edit (`tagEdit`) or a whole-blob lens/order write (`setTimelineViews`) — carries
// a writeId, and the kernel answers it on the same socket with {tagEditAck|viewsAck, writeId, ok,
// views, error?, refused?}. The optimistic copy a gesture showed clears on that ACK — an event —
// never on a count of frames: a frame that does not echo the edit says nothing about it (it may
// predate the write, or the kernel may have refused it), and the three-frame yield this replaces
// dropped good edits and kept refused ones alike. Pure, shared by render.ts (the tab strip) and
// mirrored by hand in ui/romp-timeline-view.js (which cannot import TS).
import type { SessionTag, SessionViews } from "./session-views";

/** one targeted tag edit — the kernel applies it through its /tag merge, which reads the store first
 *  and so is never judged stale against this page's own earlier writes. Every op but create addresses
 *  the tag by its stored id (`tid`): a name is what a refused rename would have changed, so a
 *  follow-up addressed by name could land on whichever OTHER tag already had it. The message nests
 *  this under `edit`, so no top-level `name` can read as a session address to the federation router. */
export interface TagEditOp {
  op: "create" | "rename" | "recolor" | "addMember" | "removeMember" | "delete" | "move";
  /** the tag's stored id — every op but create and move */
  tid?: string;
  /** move only: off `tid_from`, onto `tid_to`, as ONE write on the kernel — both halves or neither */
  tid_from?: string;
  tid_to?: string;
  /** create only: the typed name, or none for the kernel's default ("tag N", minted unique there) */
  name?: string;
  newName?: string;
  color?: string;
  sid?: string;
  sids?: string[];
}

export interface ViewsAck {
  type?: string;
  writeId?: unknown;
  ok?: boolean;
  views?: SessionViews | null;
  /** the store's write sequence after this write — the blob's own `seq`, repeated for the poster */
  seq?: number | null;
  error?: string;
  /** the whole-blob path: each tag the stale-writer guard kept the store's copy of, with its reason —
   *  and, past the door's row bound, ONE nameless summary row whose reason counts the rest (`more`) and
   *  how many of them the write edited (`moreEdited`); a row without a name renders as its reason alone */
  refused?: { tid?: string; name?: string; reason?: string; more?: number; moreEdited?: number }[];
  /** a targeted edit: the tag it touched — a create's caller learns the kernel-minted id and name here */
  tid?: string;
  name?: string;
}

/** the blob's write sequence, or null for a blob from a kernel that does not stamp one */
export function seqOf(v: SessionViews | null | undefined): number | null {
  const s = v && (v as any).seq;
  return typeof s === "number" && Number.isFinite(s) ? s : null;
}

/** Whether an incoming blob may replace the held one: yes when its seq is at least the held seq, or
 *  when either side carries no seq (a kernel from before the stamp, or nothing held yet), or when its
 *  seq is the one the kernel ANNOUNCED as its current store at connect (`announced`: the slot the
 *  caller fills from the caps frame through announcedSeq, one per store, cleared by the next
 *  adoption that CHANGES the held blob — announcedAfter) — a blob carrying that seq IS the announced
 *  store, not a stale frame, however far below the held seq it sits (the 2026-09-05 review). The order the socket delivered them in
 *  decides nothing — the pusher builds frames from a warmed cache that can predate a write whose ack
 *  already arrived, and federation re-emits stored blobs; the seq is the store's own order, so an
 *  older blob is ignored wherever it turns up. */
export function adoptViews(held: SessionViews | null | undefined, incoming: SessionViews | null | undefined, announced: number | null = null): boolean {
  if (!incoming) return false;
  const h = seqOf(held), i = seqOf(incoming);
  return h === null || i === null || i >= h || (typeof announced === "number" && i === announced);
}

/** Whether the kernel's `caps` frame — the reconnect event — adopts the blob the gate last REJECTED
 *  since its last adoption (the 2026-09-05 review). The kernel's seq floor lives
 *  for its process, so a store restored while the kernel was down is served under its old seq after
 *  the restart, and a page that stayed open across it holds the higher seq: its gate turns the
 *  kernel's connect push away. The kernel sends that push BEFORE the caps frame, and the frame names
 *  what the push served: `served` is its `viewsSeq`, the write seq of the views blob the ready
 *  handler's own push put on this socket (read from the frames that handler's thread enqueued, so a
 *  pusher-thread frame is never what it names), null when the push carried none, undefined when the
 *  frame has no such field (a kernel from before it). The kept blob is adopted when its seq equals
 *  `served`: the restore case (the kept blob IS the connect push), the gate re-arming at its seq. A
 *  pusher frame built before a concurrent write and enqueued between the push and the caps frame is
 *  kept too, but its seq is older than the push's, so it never matches and is discarded — the gate
 *  stands, and the next pusher cycle carries the newer blob. A frame without the field adopts the
 *  kept blob outright, the pre-field rule. Nothing kept: nothing to adopt, whatever the frame says —
 *  but the frame's viewsSeq is then the kernel's announcement of its current store, which the caller
 *  remembers (announcedSeq) for the blob that carries it later. */
export function capsAdopts(rejected: SessionViews | null | undefined, served: unknown): boolean {
  if (!rejected) return false;
  if (served === undefined) return true;
  return typeof served === "number" && Number.isFinite(served) && seqOf(rejected) === served;
}

/** The seq the caps frame ANNOUNCES as the kernel's current views store, for the client to remember
 *  when the frame adopted no kept blob (the 2026-09-05 review): its `viewsSeq` when that
 *  is a number — the seq of the views blob the connect push served, or the store's current seq when
 *  the push carried no views frame (a chat page's sentinel cycle sends no tabOrder) — and null when
 *  it is null (the kernel has no store at all) or the frame has no such field (a kernel from before
 *  it). The caller keeps it in ONE slot per store, overwritten by each caps frame and cleared by the
 *  next adoption that CHANGES the held blob (announcedAfter), and hands it to adoptViews as
 *  `announced`, so a LATER blob carrying
 *  exactly that seq is adopted even below the held one. Without it, a restart over a store restored
 *  from an older copy met by a sentinel-cycle reconnect left nothing kept for capsAdopts to match:
 *  the pusher's next frame (the restored store, under its old seq) was turned away, and no second
 *  caps frame comes. The clear on a changing adoption is what keeps the slot honest: a write that
 *  lands first stamps the store past what was announced, and a frame at the announced seq is then
 *  the stale frame it looks like. */
export function announcedSeq(served: unknown): number | null {
  return typeof served === "number" && Number.isFinite(served) ? served : null;
}

/** The announced slot AFTER the gate adopts `incoming` over `held` (the 2026-09-05 review).
 *  The slot is cleared only by an adoption that CHANGES the held blob: a seq other than the held one
 *  (a newer write by the ordinary rule, or the announced seq itself below the held one), a seq-less
 *  side, or the announced seq arriving at the held seq (the announced store has arrived; the
 *  announcement is spent). A re-arrival of the blob already held — the same seq on both sides — is no
 *  new information and leaves the slot standing. That case is not rare: in the browser a pane sees the
 *  local blob only through the federation router, which replays its stored blob on every merged
 *  re-emit (a remote host's push, a `closed` frame, a view-order storage event, a host drop). An earlier
 *  rule cleared the slot on ANY adoption, so a re-emit landing between the caps frame and the pusher's next
 *  frame spent the pane's slot, and when the router adopted the pusher's frame at the announced seq
 *  and re-emitted it, the pane turned it away: the router carried the restored store and the pane the
 *  pre-restore one, silently, until the next write. The honesty argument stands as it was: a write
 *  that lands first stamps the store strictly past the held seq and clears the slot; only an arrival
 *  that changes nothing leaves it. Null in is null out. */
export function announcedAfter(held: SessionViews | null | undefined, incoming: SessionViews | null | undefined, announced: number | null): number | null {
  if (typeof announced !== "number") return null;
  const h = seqOf(held), i = seqOf(incoming);
  return i !== null && i === h && i !== announced ? announced : null;
}

/** the fields a lens or order write sets — the whole-blob write's only content of its own: the
 *  legacy scalar, the per-surface lenses, and the union display order */
export type LensFields = Partial<Pick<SessionViews, "active" | "actives" | "tagOrder">>;

/** whether a tag id is the placeholder an optimistic create's row wears until the kernel's ack
 *  names the real one — such a row takes no gesture (the 2026-09-05 review: a rename
 *  or delete on it posted the placeholder as the tid and was refused as "no longer exists") */
export function isPlaceholderId(id: string | null | undefined): boolean {
  return typeof id === "string" && /^pending-/.test(id);
}

/** one write in flight: its id, and what it did — the targeted op (with the placeholder id its
 *  optimistic row wears, for a create), the lens/order fields it set, or the whole blob it posted
 *  (the no-capability path's tag edits) — so the pending copy can be re-derived without it when
 *  another write is refused (the 2026-09-05 review) */
export interface InflightWrite {
  id: string;
  edit?: TagEditOp;
  blob?: SessionViews;
  lens?: LensFields;
  /** a create's optimistic row id (the `pending-…` placeholder the ack's blob replaces) */
  newId?: string;
}

/** The blob a lens or order write POSTS: the store's blob (`base`, the last one adopted — never
 *  the pending copy) with the fields set. A whole-blob write built from the pending copy carried
 *  every targeted edit still in flight as if it were the client's own claim on those tags, and a
 *  rename the kernel had refused as a duplicate landed through the next lens toggle (the
 *  2026-09-05 review). The kernel keeps the store's copy of any tag a write with an empty
 *  `edited` differs on, so what rides here must be exactly what the store served. The tags
 *  array re-sorts to `tagOrder` when one is given — the pill-drag contract that the stored array
 *  reads in the dragged order too: over the socket the kernel's door orders the stored array by
 *  the write's `tagOrder` itself (the array is not the write's to set under an empty `edited`),
 *  and on the Electron path, where the posted blob IS the file, this re-sort is what does it. */
export function lensBlob(base: SessionViews | null | undefined, fields: LensFields): SessionViews {
  const v = applyLensFields(base || { active: "all", tags: [] }, fields);
  if (fields.tagOrder) {
    const ix = new Map(fields.tagOrder.map((n, i) => [n, i] as const));
    const rank = (name: string | undefined) => (name !== undefined && ix.has(name) ? ix.get(name)! : fields.tagOrder!.length);
    v.tags = (Array.isArray(v.tags) ? v.tags : []).slice().sort((a, b) => rank(a.name) - rank(b.name));
  }
  return v;
}

/** the same fields applied to a blob the page SHOWS (the pending copy, in-flight edits included) —
 *  a copy, never the input */
export function applyLensFields(v: SessionViews | null | undefined, fields: LensFields): SessionViews {
  const nv = JSON.parse(JSON.stringify(v || { active: "all", tags: [] })) as SessionViews;
  if (!Array.isArray(nv.tags)) nv.tags = Array.isArray(nv.groups) ? nv.groups : [];
  delete nv.groups;
  if (fields.active !== undefined) nv.active = fields.active;
  if (fields.actives !== undefined) nv.actives = JSON.parse(JSON.stringify(fields.actives));
  if (fields.tagOrder !== undefined) nv.tagOrder = fields.tagOrder.slice();
  return nv;
}

export interface AckOutcome {
  /** the writes still in flight after this ack */
  inflight: InflightWrite[];
  /** drop the optimistic copy now: nothing is in flight any more (settled, or the last one refused) */
  clearPending: boolean;
  /** this write was refused while others are still in flight: rebuild the copy from the store's
   *  blob plus those writes (rederivePending), so only the refused change reverts */
  rederive: boolean;
  /** a refusal's one-line reason for the user, else null */
  refusal: string | null;
}

/** a write id: the ms stamp plus a per-page counter, so two same-ms gestures never share one */
export function mintWriteId(seq: number): string {
  return "w" + Date.now().toString(36) + "-" + seq.toString(36);
}

/** What one ack means for the page. ok → this write is settled; the copy clears once NOTHING is in
 *  flight (a later gesture may still be pending). Refused → THIS write is dropped and its change
 *  reverts: with nothing else in flight the store's blob (the ack carries it) is what stands; with
 *  other writes still pending the copy is re-derived from that blob plus those writes, so a later
 *  in-flight gesture never flaps off and back on (the 2026-09-05 review: a refusal
 *  cleared the whole list). The reason surfaces either way. An ack for a write this page never made
 *  (a previous load's) still counts as information: with nothing of ours in flight, the returned
 *  blob is the base and no copy stays pinned. */
export function ackOutcome(inflight: readonly InflightWrite[], m: ViewsAck): AckOutcome {
  const rest = inflight.filter((w) => w.id !== m.writeId);
  if (m.ok === false) {
    // the kernel's one-line `error` already names each refused tag ONCE before its reason; with only
    // the rows, compose the same shape here — never a name prefix on top of a reason that carries it
    const rows = (m.refused || []).filter((r) => r && (r.reason || r.name))
      .map((r) => (r.name ? '"' + r.name + '": ' : "") + (r.reason || "refused"));
    return { inflight: rest, clearPending: rest.length === 0, rederive: rest.length > 0,
             refusal: m.error || rows.join("; ") || "refused" };
  }
  // ok with refusals listed: the guard kept the store's copy of tags this write did not edit (a stale
  // copy, not a lost edit) — the ack's blob carries them, and there is nothing to tell the user
  return { inflight: rest, clearPending: rest.length === 0, rederive: false, refusal: null };
}

/** whether a create is in flight — the gate on a second [+ New tag] / New tag… before the first is
 *  answered (the 2026-09-05 review: two clicks before the ack made two tags) */
export function createInFlight(inflight: readonly InflightWrite[]): boolean {
  return inflight.some((w) => !!w.edit && w.edit.op === "create");
}

/** One targeted op applied to a client blob's LOCAL tags, the way the gesture applied it
 *  optimistically — a copy, never the input. Unknown tids are no-ops (the kernel will refuse them);
 *  a create's row wears `newId` (the placeholder its ack replaces) so a re-derived copy shows the
 *  same row the gesture drew. Members are the viewer-relative id strings every client holds. */
export function applyTagEdit(v: SessionViews, edit: TagEditOp, newId?: string): SessionViews {
  const nv = JSON.parse(JSON.stringify(v || {})) as SessionViews;
  const tags: SessionTag[] = (Array.isArray(nv.tags) ? nv.tags : (Array.isArray(nv.groups) ? nv.groups : [])).slice();
  delete nv.groups;
  const byId = (tid?: string) => tags.find((t) => t.id === tid);
  const sids = (edit.sids || []).concat(edit.sid ? [edit.sid] : []);
  switch (edit.op) {
    case "create":
      tags.push({ id: newId || "pending-" + Date.now().toString(36), name: edit.name || "", color: edit.color || "", members: sids.slice() });
      break;
    case "rename": { const t = byId(edit.tid); if (t && edit.newName) t.name = edit.newName; break; }
    case "recolor": { const t = byId(edit.tid); if (t && edit.color) t.color = edit.color; break; }
    case "delete": {
      const i = tags.findIndex((t) => t.id === edit.tid);
      if (i >= 0) tags.splice(i, 1);
      if (nv.active === edit.tid) nv.active = "all";
      break;
    }
    case "addMember": { const t = byId(edit.tid); if (t) t.members = Array.from(new Set((t.members || []).concat(sids))); break; }
    case "removeMember": { const t = byId(edit.tid); if (t) t.members = (t.members || []).filter((m) => !sids.includes(m)); break; }
    case "move": {
      const from = byId(edit.tid_from), to = byId(edit.tid_to);
      if (from) from.members = (from.members || []).filter((m) => !sids.includes(m));
      if (to) to.members = Array.from(new Set((to.members || []).concat(sids)));
      break;
    }
  }
  nv.tags = tags;
  return nv;
}

/** The optimistic copy the page should show for the writes still in flight, rebuilt from `base`
 *  (the store's blob) oldest write first: a lens or order write sets its fields; a targeted op
 *  applies on top; a whole-blob write (the no-capability path) IS the state it posted. Null when
 *  nothing is in flight — the base itself is what shows. */
export function rederivePending(base: SessionViews | null | undefined, inflight: readonly InflightWrite[]): SessionViews | null {
  if (!inflight.length) return null;
  let p: SessionViews = JSON.parse(JSON.stringify(base || { active: "all", tags: [] }));
  for (const w of inflight) {
    if (w.lens) p = applyLensFields(p, w.lens);
    else if (w.blob) p = JSON.parse(JSON.stringify(w.blob));
    else if (w.edit) p = applyTagEdit(p, w.edit, w.newId);
  }
  return p;
}
