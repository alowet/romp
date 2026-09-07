// THE CHAT PANE'S VIEWS WRITES ARE ACKNOWLEDGED (the user 2026-09-05, who lost a batch of tag
// renames and assignments). The tab menu's Tags flyout had the timeline dialog's shape: every
// gesture posted the WHOLE blob from the pane's own un-echoed optimistic copy, so a New tag… then a
// second gesture on it carried the pre-burst `at` stamp and the kernel's stale-writer guard refused the
// second against the first; the copy cleared on an exact echo or after THREE frames, whichever came first.
// Now: tag gestures post TARGETED tagEdit ops; lens and order edits keep the whole-blob write; both
// carry a writeId the kernel's ack names, and the optimistic copy clears on the ACK — never on a
// frame count. Executed tests on the pure module (views-writes.ts) plus source pins on render.ts
// (the tab-order.ts pattern; no jsdom for render.ts). Synthetic ids only.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { ackOutcome, adoptViews, applyTagEdit, createInFlight, mintWriteId, rederivePending, seqOf, lensBlob, applyLensFields, isPlaceholderId, capsAdopts, announcedSeq, announcedAfter, type InflightWrite } from "./views-writes";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const S1 = { active: "all", at: 113, tags: [{ id: "g1", name: "qa", color: "#DD42FF", members: ["tests"], mtime: 113 }] };

const W1: InflightWrite = { id: "w1", edit: { op: "create", name: "qa", color: "#DD42FF", sids: ["tests"] }, newId: "pending-1" };
const W2: InflightWrite = { id: "w2", edit: { op: "rename", tid: "g1", newName: "quality" } };

test("executed: an ok ack settles ITS write; the copy clears only when nothing else is in flight", () => {
  // the burst: a create (w1) and the rename typed before its echo (w2), both in flight
  const a = ackOutcome([W1, W2], { type: "tagEditAck", writeId: "w1", ok: true, views: S1 });
  assert.deepEqual(a, { inflight: [W2], clearPending: false, rederive: false, refusal: null },
    "the create's ack leaves the rename's optimistic copy showing — the user's typed name never blinks to 'tag N'");
  const b = ackOutcome(a.inflight, { type: "tagEditAck", writeId: "w2", ok: true, views: S1 });
  assert.deepEqual(b, { inflight: [], clearPending: true, rederive: false, refusal: null }, "the last ack settles the copy");
});

test("executed: a refusal drops ITS write only and names the tag and the reason; a later in-flight write keeps its copy", () => {
  const why = 'a tag named "web" already exists';
  const r = ackOutcome([W1, W2], { type: "tagEditAck", writeId: "w1", ok: false, error: why, views: S1 });
  assert.deepEqual(r, { inflight: [W2], clearPending: false, rederive: true, refusal: why },
    "the refused write is dropped; the rename still in flight is not — the copy is re-derived without the refused change (the 2026-09-05 review: a refusal cleared the whole list, and a later write flapped off and back on)");
  assert.deepEqual(ackOutcome([W1], { type: "tagEditAck", writeId: "w1", ok: false, error: why, views: S1 }),
    { inflight: [], clearPending: true, rederive: false, refusal: why }, "with nothing else in flight the store's blob (in the ack) is what stands");
  // the whole-blob path's refusal lists the tags the guard kept, each with a NAME-FREE reason; the
  // kernel's one-line `error` names each tag once — and the page never prefixes the name a second time
  const reason = "your copy predates a newer edit to it, so your change was not applied and the newer state was kept";
  const w = ackOutcome([{ id: "w3", blob: S1 }], { type: "viewsAck", writeId: "w3", ok: false, refused: [{ tid: "gA", name: "web", reason }], error: '"web": ' + reason, views: S1 });
  assert.equal(w.refusal, '"web": ' + reason, "the kernel's line as-is: the name once, then what was refused and what was kept");
  assert.equal(w.clearPending, true);
  // no error text at all → still a plain word, never an empty toast
  assert.equal(ackOutcome([{ id: "w4" }], { writeId: "w4", ok: false }).refusal, "refused");
  assert.equal(ackOutcome([{ id: "w5" }], { writeId: "w5", ok: false, refused: [{ name: "qa", reason: "kept" }] }).refusal, '"qa": kept',
    "with only the rows, the same shape is composed here");
  // ok WITH refusals listed (the guard kept the store's copy of tags this write did not edit — a lens
  // write from a stale copy): the write is settled, nothing is toasted, the ack's blob is the base
  assert.deepEqual(ackOutcome([{ id: "w6", blob: S1 }], { type: "viewsAck", writeId: "w6", ok: true, refused: [{ tid: "gA", name: "web", reason }], views: S1 }),
    { inflight: [], clearPending: true, rederive: false, refusal: null }, "nothing the user did was refused");
});

test("executed: the pending copy re-derives from the store's blob plus the writes still in flight — only the refused change reverts", () => {
  const base = { active: "all", seq: 5, tags: [{ id: "gA", name: "web", color: "#3b82f6", members: ["s1"] }] };
  // A (recolor) refused, B (addMember, posted after A from the copy that showed the recolor) still in flight
  const B: InflightWrite = { id: "wB", edit: { op: "addMember", tid: "gA", sids: ["s2"] } };
  const p = rederivePending(base, [B])!;
  assert.deepEqual(p.tags, [{ id: "gA", name: "web", color: "#3b82f6", members: ["s1", "s2"] }], "the add shows, the refused recolor does not");
  assert.deepEqual(base.tags[0].members, ["s1"], "the base is never mutated");
  assert.equal(rederivePending(base, []), null, "nothing in flight → the base itself shows");
  // a whole-blob write in flight IS the state it posted; a targeted op after it applies on top
  const blob = { active: "all", tags: [{ id: "gA", name: "web", color: "#000000", members: [] }], actives: { chat: { tags: ["web"] } } };
  const q = rederivePending(base, [{ id: "wL", blob }, { id: "wC", edit: { op: "create", name: "qa", color: "#DD42FF", sids: ["s3"] }, newId: "pending-x" }])!;
  assert.deepEqual(q.actives, { chat: { tags: ["web"] } });
  assert.deepEqual(q.tags, [{ id: "gA", name: "web", color: "#000000", members: [] }, { id: "pending-x", name: "qa", color: "#DD42FF", members: ["s3"] }],
    "the create's row wears the placeholder id its gesture drew");
  // every op, applied the way the gesture applied it; an unknown tid is a no-op
  const t2 = { active: "gA", tags: [{ id: "gA", name: "web", members: ["s1", "s2"] }, { id: "gB", name: "api", members: ["s3"] }] };
  assert.equal(applyTagEdit(t2, { op: "rename", tid: "gA", newName: "site" }).tags![0].name, "site");
  assert.equal(applyTagEdit(t2, { op: "recolor", tid: "gB", color: "#54B204" }).tags![1].color, "#54B204");
  const del = applyTagEdit(t2, { op: "delete", tid: "gA" });
  assert.deepEqual([del.tags!.map((t) => t.id), del.active], [["gB"], "all"], "a deleted active tag falls back to All, as the gesture did");
  assert.deepEqual(applyTagEdit(t2, { op: "removeMember", tid: "gA", sids: ["s1"] }).tags![0].members, ["s2"]);
  const mv = applyTagEdit(t2, { op: "move", tid_from: "gA", tid_to: "gB", sid: "s2" });
  assert.deepEqual([mv.tags![0].members, mv.tags![1].members], [["s1"], ["s3", "s2"]]);
  assert.deepEqual(applyTagEdit(t2, { op: "rename", tid: "gZ", newName: "x" }).tags, t2.tags, "an unknown tid changes nothing — the kernel refuses it");
  assert.equal(createInFlight([B]), false);
  assert.equal(createInFlight([B, W1]), true, "a create in flight gates the next New tag…");
});

test("executed: a refusal's nameless summary row (the entries past the door's row bound, the 2026-09-05 review) renders as its reason alone, after the named rows", () => {
  const rows = [
    { tid: "g9", name: "qa", reason: "a write is read to 64 tags and it was past that bound, so it was not created" },
    { reason: "3 more entries past the 64-tag read bound were not read (1 of them this write edited)", more: 3, moreEdited: 1 },
  ];
  const out = ackOutcome([W2], { type: "viewsAck", writeId: "w2", ok: false, refused: rows });
  assert.equal(out.refusal, '"qa": a write is read to 64 tags and it was past that bound, so it was not created; 3 more entries past the 64-tag read bound were not read (1 of them this write edited)',
    "no name prefix on the summary row — the same shape the kernel's own bounded `error` line has");
  assert.equal(ackOutcome([W2], { type: "viewsAck", writeId: "w2", ok: false, error: "bounded by the kernel", refused: rows }).refusal, "bounded by the kernel",
    "the kernel's one-line error wins when present");
});

test("executed: an ack for a write this page never made counts as information — nothing stays pinned", () => {
  assert.deepEqual(ackOutcome([], { type: "viewsAck", writeId: "w-from-a-previous-load", ok: true, views: S1 }),
    { inflight: [], clearPending: true, rederive: false, refusal: null });
  assert.deepEqual(ackOutcome([{ id: "w9" }], { type: "viewsAck", writeId: "w-other", ok: true, views: S1 }),
    { inflight: [{ id: "w9" }], clearPending: false, rederive: false, refusal: null }, "…but our own in-flight write still holds its copy");
});

test("executed: a blob is adopted by write SEQUENCE, never by arrival order — older is ignored, equal or newer lands, no seq adopts", () => {
  const held = { active: "all", tags: [], seq: 12 };
  assert.equal(adoptViews(held, { active: "all", tags: [], seq: 11 }), false, "the pusher's warmed cache, delivered after the ack: ignored");
  assert.equal(adoptViews(held, { active: "all", tags: [], seq: 12 }), true, "the same write, seen again (the ack's blob then its frame): fine");
  assert.equal(adoptViews(held, { active: "all", tags: [], seq: 13 }), true);
  assert.equal(adoptViews(held, { active: "all", tags: [] }), true, "a kernel from before the stamp sends no seq — nothing is gated on a field it never sends");
  assert.equal(adoptViews(null, { active: "all", tags: [], seq: 3 }), true, "nothing held yet");
  assert.equal(adoptViews({ active: "all", tags: [] }, { active: "all", tags: [], seq: 3 }), true, "a seq-less base yields to the first stamped blob");
  assert.equal(adoptViews(held, null), false);
  assert.equal(seqOf({ seq: 7 } as any), 7);
  assert.equal(seqOf({ seq: "7" } as any), null, "a non-number is no seq");
  assert.equal(seqOf(null), null);
});

test("executed: capsAdopts — the caps frame adopts the kept blob only when viewsSeq (what the kernel's own connect push served) names its seq; an older kernel's frame, without the field, adopts it outright", () => {
  // the kernel restarted over a store restored from an older copy: its connect push carries seq 900 where the page holds 1000
  const held = { active: "all", tags: [{ id: "g1", name: "qa", color: "", members: [] }], seq: 1000 } as any;
  const restored = { active: "all", tags: [], seq: 900 } as any;
  assert.equal(adoptViews(held, restored), false, "the connect push meets the gate first and is turned away…");
  assert.equal(capsAdopts(restored, 900), true, "…and the caps frame that follows names it (viewsSeq 900): adopted, zero residual, no wait on the pusher's repost");
  assert.equal(adoptViews(restored, { active: "all", tags: [], seq: 899 }), false, "the gate re-arms at its seq: the store's own order gates again");
  // the residual an earlier fix left: a pusher-thread frame built before a concurrent write (seq 1000), enqueued
  // between the connect push (seq 1001, adopted) and the caps frame — turned away and kept
  const stale = { active: "all", tags: [], seq: 1000 } as any;
  assert.equal(capsAdopts(stale, 1001), false, "the caps frame names the connect push's seq, not the stale frame's: discarded, the gate stands at 1001");
  assert.equal(capsAdopts(stale, null), false, "the connect push carried no views blob (viewsSeq null): nothing to match, nothing adopted");
  assert.equal(capsAdopts(stale, "1000"), false, "a non-number is no seq");
  assert.equal(capsAdopts(stale, undefined), true, "a caps frame without the field (a kernel from before it) adopts the kept blob — the pre-field rule");
  assert.equal(capsAdopts(null, 900), false); assert.equal(capsAdopts(undefined, undefined), false, "nothing kept: nothing to adopt, whatever the frame says");
  assert.equal(capsAdopts({ active: "all", tags: [] } as any, 900), false, "a kept blob without a seq cannot match (unreachable: the gate adopts every seq-less blob)");
});

// The 2026-09-05 review: the caps frame's viewsSeq is also the kernel's ANNOUNCEMENT of its current store
// (the served blob's seq, or the store's current seq when the connect push carried no views frame — a chat page's
// sentinel cycle sends no tabOrder; null only when the kernel has no store at all). A restart over a store restored
// from an older copy, met by such a reconnect, kept nothing for capsAdopts to match: the pusher's next frame (the
// restored store, under its old seq) was turned away and no second caps frame comes. The client remembers the
// announced seq in one slot per store and adopts the LATER blob that carries it, below the held one.
test("executed: announcedSeq + adoptViews(announced) — a caps frame that adopted no kept blob names the kernel's current store, and the later blob at exactly that seq is adopted below the held one; another lower seq is still turned away; a cleared slot is the old verdict; null and a missing field announce nothing", () => {
  const held = { active: "all", tags: [{ id: "g1", name: "qa", color: "", members: [] }], seq: 1000 } as any;
  assert.equal(capsAdopts(null, 900), false, "the sentinel cycle's push carried no blob, so nothing is kept: the caps frame adopts nothing…");
  const announced = announcedSeq(900);
  assert.equal(announced, 900, "…and its viewsSeq — the restored store's current seq — is remembered as the kernel's announced store");
  assert.equal(adoptViews(held, { active: "all", tags: [], seq: 899 }, announced), false, "a frame at another lower seq is a stale frame: turned away");
  assert.equal(adoptViews(held, { active: "all", tags: [], seq: 900 }, announced), true, "the pusher's next frame carries the announced seq: that IS the store the kernel said it holds — adopted below the held one");
  assert.equal(adoptViews(held, { active: "all", tags: [], seq: 900 }), false, "…and only because it was announced: the same blob with no slot meets the old verdict");
  assert.equal(adoptViews(held, { active: "all", tags: [], seq: 900 }, null), false, "a cleared slot (the caller clears it on every adoption that changes the held blob — announcedAfter): a write that landed first stamped the store past the announcement, and 900 is the stale frame it looks like");
  assert.equal(adoptViews(held, { active: "all", tags: [], seq: 1100 }, announced), true, "a newer blob adopts as ever");
  assert.equal(adoptViews(held, { active: "all", tags: [] }, announced), true, "a seq-less blob adopts as ever");
  assert.equal(adoptViews(held, null, announced), false);
  assert.equal(announcedSeq(null), null, "viewsSeq null — the kernel has no store at all — announces nothing");
  assert.equal(announcedSeq(undefined), null, "a frame without the field (a kernel from before it) announces nothing");
  assert.equal(announcedSeq("900"), null); assert.equal(announcedSeq(NaN), null, "a non-number is no seq");
});

// The 2026-09-05 review: the slot is cleared only by an adoption that CHANGES the held blob. In the browser a pane sees the local
// blob only through the federation router, which replays its stored blob on every merged re-emit (a remote host's
// push, a `closed` frame, a view-order storage event, a host drop) — a re-arrival of the blob the pane already holds,
// at its own seq. The earlier clear on any adoption spent the slot on that re-arrival, and the restored store the
// router adopted and re-emitted next at the announced seq was turned away by the pane: router 900, pane 1000,
// silently, until the next write (federation-views-seq.test.ts executes the failure against the real router).
test("executed: announcedAfter — a re-arrival of the held blob (the same seq) leaves the slot; a different seq, a seq-less side, or the announced seq itself clears it; null stays null", () => {
  const held = { active: "all", tags: [], seq: 1000 } as any;
  const v = (seq?: number) => ({ active: "all", tags: [], ...(seq === undefined ? {} : { seq }) }) as any;
  assert.equal(announcedAfter(held, v(1000), 900), 900, "the blob already held, arriving again (the router's re-emit of its stored blob): no new information, the slot stands");
  assert.equal(announcedAfter(held, v(900), 900), null, "the announced store itself, adopted below the held one: the announcement is spent");
  assert.equal(announcedAfter(held, v(1100), 900), null, "a newer write stamped the store past the announcement: cleared");
  assert.equal(announcedAfter(held, v(), 900), null, "a seq-less blob changes the held one: cleared");
  assert.equal(announcedAfter(null, v(900), 900), null, "nothing held yet: the arrival is the store, cleared");
  assert.equal(announcedAfter(null, v(1000), 900), null);
  assert.equal(announcedAfter(v(), v(), 900), null, "two seq-less blobs cannot be told apart: cleared, the old verdict");
  assert.equal(announcedAfter(held, v(1000), 1000), null, "the announced seq arriving at the held seq: the announced store has arrived, the slot is spent");
  assert.equal(announcedAfter(held, v(1000), null), null, "no slot in, none out");
  // the composition every gate uses: the same-seq re-arrival is adopted (i >= h) and leaves the slot, so the announced blob still lands after it
  let slot: number | null = 900;
  assert.equal(adoptViews(held, v(1000), slot), true); slot = announcedAfter(held, v(1000), slot);
  assert.equal(slot, 900);
  assert.equal(adoptViews(held, v(900), slot), true, "…and the restored store, re-emitted after it, is adopted below the held one"); slot = announcedAfter(held, v(900), slot);
  assert.equal(slot, null);
  assert.equal(adoptViews(v(900), v(900), slot), true, "the same blob again meets the ordinary rule");
});

test("pins: render.ts keeps the last blob its gate turned away, lets it go on the next adoption, and on the caps frame adopts it only when viewsSeq names it — before anything else it does there", () => {
  const take = RENDER.slice(RENDER.indexOf("function takeViews("), RENDER.indexOf("\n}\n", RENDER.indexOf("function takeViews(")));
  assert.match(take, /if \(adoptViews\(sessionViews, v, announcedViewsSeq\)\) \{ announcedViewsSeq = announcedAfter\(sessionViews, v, announcedViewsSeq\); sessionViews = v; rejectedViews = null; return true; \}\s*\n\s*rejectedViews = v;/,
    "an adoption lets the kept blob go and re-derives the announced slot from the held blob BEFORE it moves (cleared only when the adoption changes it); a rejection keeps this one (the LAST turned away — the connect push is the last frame before caps on the handler's thread); the gate reads the announced seq");
  const caps = RENDER.slice(RENDER.indexOf("function onKernelCaps("), RENDER.indexOf("function onUnknownOp("));
  assert.match(caps, /kernelCaps = new Set\([\s\S]*?\);\n\s*const adopted = capsAdopts\(rejectedViews, m\.viewsSeq\);\n\s*if \(adopted\) sessionViews = rejectedViews;\n\s*announcedViewsSeq = adopted \? null : announcedSeq\(m\.viewsSeq\);\n\s*rejectedViews = null;\n\s*if \(viewsWrites\.length\) \{/,
    "the verdict runs on EVERY caps frame, in-flight writes or not, on the frame's viewsSeq, and before the in-flight drop: the dropped copy reverts to the adopted base; the kept blob is let go either way; a frame that adopted nothing leaves the announced seq in the one slot");
  assert.equal((RENDER.match(/announcedViewsSeq = /g) || []).length, 2, "past its declaration the slot is written in exactly two places: the gate's re-derivation on adoption, and the caps frame");
  assert.match(caps, /\} else if \(!adopted\) return;/, "nothing in flight and nothing adopted: the caps frame changes nothing shown");
  assert.match(caps, /if \(activeId\) assertPeekFor\(activeId\);[^\n]*\n\s*renderTabs\(\);\n\}/, "an adoption renders like any views arrival: the peek is re-derived and the strip redrawn");
  assert.doesNotMatch(RENDER, /forgetSeq|adoptOnCaps/, "the held seq is never forgotten and no kept blob is adopted unnamed: the gate is never left open (the one-cycle flap window an earlier fix left)");
});

test("executed: write ids are unique per page across same-ms gestures", () => {
  const a = mintWriteId(1), b = mintWriteId(2);
  assert.notEqual(a, b);
  assert.match(a, /^w[0-9a-z]+-1$/);
});

test("pins: render.ts posts a writeId on every views write and routes both acks to onViewsAck", () => {
  const pv = RENDER.slice(RENDER.indexOf("function postViews(v: SessionViews, edited: string[] = [])"), RENDER.indexOf("\n}\n", RENDER.indexOf("function postViews(")));
  assert.match(pv, /const writeId = holdViews\(v, \{ blob: v \}\);/, "the record keeps the blob it posted: a refusal elsewhere re-derives from it");
  assert.match(pv, /vscodeApi\.postMessage\(\{ type: "setTimelineViews", views: v, writeId, edited \}\);/,
    "a lens/order edit is still the whole blob (the kernel owns no lens op), with its writeId and the tag ids it changed (none) — a refusal on an untouched tag is acked ok, no toast");
  assert.match(RENDER, /warnToast\("Tag edit not applied — " \+ out\.refusal\);/, "the toast adds no second name: the reason names the tag once and says what was kept");
  const pte = RENDER.slice(RENDER.indexOf("function postTagEdit("), RENDER.indexOf("\n}\n", RENDER.indexOf("function postTagEdit(")));
  assert.match(pte, /if \(!kernelCaps\.has\("tagEdit"\)\) \{\s*\n\s*const edited = \[edit\.tid, edit\.tid_from, edit\.tid_to\]\.filter\(\(t\): t is string => !!t\);\s*\n\s*const row = newId \? viewTags\(nv\)\.find\(\(t\) => t\.id === newId\) : undefined;\s*\n\s*if \(row\) \{ if \(\/\^pending-\/\.test\(row\.id\)\) row\.id = "g" \+ Date\.now\(\)\.toString\(36\); edited\.push\(row\.id\); \}\s*\n\s*postViews\(nv, edited\);\s*\n\s*return;\s*\n\s*\}/,
    "no `tagEdit` capability announced (an older kernel) → the pre-cap whole-blob write naming the tags it changed; a create's row takes a client-minted g… id, never the pending- placeholder, and is named as edited (the 2026-09-05 review)");
  assert.match(pte, /const writeId = holdViews\(nv, \{ edit, newId \}\);\s*\n\s*if \(vscodeApi\) vscodeApi\.postMessage\(\{ type: "tagEdit", writeId, edit \}\);/,
    "a tag gesture is a targeted op, NESTED under `edit` so no tag name sits at the top level where the federation router reads session addresses");
  assert.match(RENDER, /else if \(m\.type === "viewsAck" \|\| m\.type === "tagEditAck"\) onViewsAck\(m\);/);
  assert.match(RENDER, /else if \(m\.type === "caps"\) onKernelCaps\(m\);\s*\n\s*else if \(m\.type === "unknownOp"\) onUnknownOp\(m\);/,
    "the kernel's caps (every `ready`) and its answer to an op it does not know both have a door");
  const caps = RENDER.slice(RENDER.indexOf("function onKernelCaps("), RENDER.indexOf("\n}\n", RENDER.indexOf("function onKernelCaps(")));
  assert.match(caps, /kernelCaps = new Set\(/);
  assert.match(caps, /if \(viewsWrites\.length\) \{\s*\n\s*viewsWrites = \[\]; pendingSessionViews = null;\s*\n\s*warnToast\(/,
    "a caps frame with writes in flight is a re-established socket: their acks may never come, so they are dropped and the user is told");
  const unk = RENDER.slice(RENDER.indexOf("function onUnknownOp("), RENDER.indexOf("\n}\n", RENDER.indexOf("function onUnknownOp(")));
  assert.match(unk, /if \(typeof m\.op === "string"\) kernelCaps\.delete\(m\.op\);/, "the capability is withdrawn");
  assert.match(unk, /viewsWrites\.some\(\(w\) => w\.id === m\.writeId\)\)\s*\n\s*onViewsAck\(\{ type: "unknownOp", writeId: m\.writeId, ok: false,/, "…and the write is refused, through the one ack door");
  const ack = RENDER.slice(RENDER.indexOf("function onViewsAck("), RENDER.indexOf("\n}\n", RENDER.indexOf("function onViewsAck(")));
  assert.match(ack, /const out = ackOutcome\(viewsWrites, m\);/, "the pure module decides; render.ts applies");
  assert.match(ack, /takeViews\(m\.views\);/, "the ack's blob is the new base unless a newer frame already overtook it (the seq decides), verdict regardless");
  assert.match(ack, /if \(out\.clearPending\) pendingSessionViews = null;\s*\n\s*else if \(out\.rederive\) pendingSessionViews = rederivePending\(sessionViews, viewsWrites\);/,
    "a refusal with other writes in flight re-derives the copy from the base plus them — only the refused change reverts");
  assert.match(ack, /if \(out\.refusal\) warnToast\(/, "a refusal is LOUD — the flyout has no error surface of its own");
  assert.match(ack, /syncNewTagInput\(\);/, "…and the flyout's New tag… input is re-armed in place — never by rebuilding the flyout, which would drop typed text");
  const sync = RENDER.slice(RENDER.indexOf("function syncNewTagInput("), RENDER.indexOf("\n}\n", RENDER.indexOf("function syncNewTagInput(")));
  assert.match(sync, /const busy = createInFlight\(viewsWrites\);\s*\n\s*tagsFlyNewInput\.disabled = busy;\s*\n\s*tagsFlyNewInput\.placeholder = busy \? "creating…" : "New tag…";/,
    "disabled and saying so while a create is in flight (a second Enter before the ack made a second tag)");
  assert.match(RENDER, /function dismissTabMenu\(\) \{\s*\n\s*ctxMenuEl\?\.remove\(\);\s*\n\s*ctxMenuEl = null;\s*\n\s*tagsFlyNewInput = null;/, "a closed menu forgets its input");
});

test("pins: every views arrival in render.ts goes through the ONE seq-gated adopter, and the exact-echo clear is legacy-only", () => {
  const take = RENDER.slice(RENDER.indexOf("function takeViews("), RENDER.indexOf("\n}\n", RENDER.indexOf("function takeViews(")));
  assert.match(take, /if \(adoptViews\(sessionViews, v, announcedViewsSeq\)\) \{ announcedViewsSeq = announcedAfter\(sessionViews, v, announcedViewsSeq\); sessionViews = v; rejectedViews = null; return true; \}/, "adopt by write sequence, never by arrival order — or by the seq the caps frame announced; the slot is re-derived from the held blob before it moves");
  assert.match(take, /what: "views-stale-blob"/, "an ignored blob leaves one breadcrumb per page load — a visible fact, not a flicker");
  assert.doesNotMatch(RENDER, /pendingViewsAge/, "no frame counter anywhere in render.ts");
  const cap = RENDER.slice(RENDER.indexOf("function captureViews("), RENDER.indexOf("\n}\n", RENDER.indexOf("function captureViews(")));
  assert.match(cap, /^\s*takeViews\(v\);/m, "a pushed frame is adopted through the gate");
  assert.match(cap, /if \(pendingSessionViews && v && seqOf\(v\) === null\s*\n\s*&& \(viewsKey\(v\) === viewsKey\(pendingSessionViews\) \|\| \+\+legacyViewsAge >= 3\)\) \{\s*\n\s*pendingSessionViews = null; viewsWrites = \[\]; legacyViewsAge = 0;/,
    "the exact-echo clear and the three-frame yield survive ONLY for a blob without a seq (a kernel that acks nothing); a stamped kernel's frames never clear a write they cannot name");
  assert.equal((cap.match(/>= 3/g) || []).length, 1, "one legacy yield, under the seq-less condition, nowhere else");
  assert.equal((RENDER.match(/(?<!pending)(?<!\w)sessionViews = /g) || []).length, 2,
    "the base is assigned in exactly two places: inside the gate, and the caps frame's adoption of the blob the gate last turned away");
  assert.match(RENDER, /if \(adopted\) sessionViews = rejectedViews;/, "…that second one is the reconnect event's adoption and nothing else");
});

test("pins: the Tags flyout's local edits are targeted ops on ONE optimistic blob", () => {
  const at = RENDER.indexOf("const editUnion = (g: TagUnion");
  const body = RENDER.slice(at, at + 4200);   // the union editor's two op sites and its post (the pending-union comment sits inside this window)
  const fly = RENDER.slice(at, RENDER.indexOf("// BROWSE FILES", at));
  assert.ok(body.includes('ops.push({ op: "addMember", tid: g.localId, sids: edit.add.slice() });'), "a local add is an addMember by the tag's stored id");
  assert.ok(body.includes('ops.push({ op: "removeMember", tid: g.localId, sids: edit.remove.slice() });'), "a local remove is a removeMember by id");
  assert.doesNotMatch(body, /op: "(?:addMember|removeMember|rename|recolor|delete)", name:/, "no op but create carries a tag name");
  assert.match(body, /for \(const op of ops\) postTagEdit\(nv, op\);/, "N ops, the one copy shown for all of them");
  assert.match(body, /else if \(mirrored\) \{ pendingSessionViews = nv; renderTabs\(\); \}/,
    "a remote-only edit has no local op: its mirror shows until the next frame");
  assert.match(RENDER, /if \(pendingSessionViews && v && !viewsWrites\.length\) pendingSessionViews = null;/,
    "…which captureViews lets go on any frame, seq or not — a copy with no write in flight is that mirror alone");
  assert.match(RENDER, /postTagEdit\(nv, \{ op: "create", name, color, sids: \[id\] \}, tg\.id\);/,
    "New tag… is ONE create carrying the session — the tag and its first member land together; the kernel mints the id (the placeholder rides along for the legacy path's re-id)");
  assert.match(fly, /if \(e2\.key !== "Enter"\) return;\s*\n\s*if \(createInFlight\(viewsWrites\)\) return;/, "one create at a time: Enter is ignored while one is in flight");
  assert.match(fly, /nrow\.appendChild\(inp\);\s*\n\s*tagsFlyNewInput = inp; syncNewTagInput\(\);/, "the input renders disabled when a create is already in flight");
  assert.doesNotMatch(fly, /postViews\(/, "no whole-blob write anywhere in the flyout's tag edits");
});

// ── The 2026-09-05 review: a lens or order write is built from the STORE's blob, never the
// pending copy. Built from the pending copy, the whole-blob write carried every targeted edit still in
// flight as this page's claim on those tags, and a rename the kernel had refused as a duplicate landed
// through the next lens toggle (two tags, one name). The copy the page SHOWS still includes the in-flight
// edits: the write's record keeps its fields, and a re-derivation re-applies exactly them.
test("executed: a lens or order write posts the store's blob plus its fields, shows the current copy plus the same fields, and a refused edit in flight reverts alone", () => {
  const base: any = { active: "all", actives: { chat: { all: true }, timeline: { all: true }, outline: { all: true } }, at: 100, seq: 5,
                      tags: [{ id: "gA", name: "web", color: "#3b82f6", members: ["s1"], mtime: 100 }, { id: "gB", name: "api", color: "#54B204", members: ["s2"], mtime: 100 }] };
  const rename: InflightWrite = { id: "w1", edit: { op: "rename", tid: "gA", newName: "notes" } };
  const fields = { actives: { ...base.actives, chat: { tags: ["web"] } } };
  const posted = lensBlob(base, fields);
  assert.equal(posted.tags![0].name, "web", "the POSTED blob carries the store's tags — never an edit still in flight");
  assert.deepEqual(posted.actives!.chat, { tags: ["web"] });
  assert.equal((posted as any).seq, 5); assert.equal((posted as any).at, 100);   // the store's stamps ride along: the guard's evidence time
  const shown = rederivePending(base, [rename, { id: "w2", lens: fields }])!;
  assert.equal(shown.tags![0].name, "notes", "the copy SHOWN keeps the in-flight rename…");
  assert.deepEqual(shown.actives!.chat, { tags: ["web"] }, "…and the lens");
  const out = ackOutcome([rename, { id: "w2", lens: fields }], { writeId: "w1", ok: false, error: 'a tag named "notes" already exists', views: base });
  assert.ok(out.rederive);
  const after = rederivePending(base, out.inflight)!;
  assert.equal(after.tags![0].name, "web", "the refused rename reverts…");
  assert.deepEqual(after.actives!.chat, { tags: ["web"] }, "…and the lens write still in flight keeps its fields");
  // an ORDER write: tagOrder rides, the posted tags array re-sorts to it (the pill-drag contract), the copy shown takes the order
  const ordered = lensBlob(base, { tagOrder: ["api", "web"] });
  assert.deepEqual(ordered.tags!.map((t) => t.id), ["gB", "gA"]);
  assert.deepEqual(ordered.tagOrder, ["api", "web"]);
  assert.deepEqual(rederivePending(base, [{ id: "w3", lens: { tagOrder: ["api", "web"] } }])!.tagOrder, ["api", "web"]);
  // copies, never the input; a page holding no blob yet writes onto the empty shape
  assert.deepEqual(base.tags.map((t: any) => t.id), ["gA", "gB"]); assert.deepEqual(base.actives.chat, { all: true });
  assert.deepEqual(lensBlob(null, { actives: { chat: { none: true } } }), { active: "all", tags: [], actives: { chat: { none: true } } });
  assert.deepEqual(applyLensFields({ active: "all", groups: [{ id: "g1", name: "x", color: "", members: [] }] } as any, { active: "g1" }),
    { active: "g1", tags: [{ id: "g1", name: "x", color: "", members: [] }] }, "the legacy key reads as tags");
});

test("executed: isPlaceholderId names an optimistic create's row and nothing else", () => {
  assert.equal(isPlaceholderId("pending-abc"), true);
  assert.equal(isPlaceholderId("g7"), false);
  assert.equal(isPlaceholderId("xpending-1"), false);
  assert.equal(isPlaceholderId(null), false);
  assert.equal(isPlaceholderId(undefined), false);
});

test("pins: render.ts builds every lens and order write from the store's blob (postLens), and the Tags flyout offers no gesture on a create still in flight", () => {
  assert.match(RENDER, /function postLens\(fields: LensFields\) \{\s*\n\s*const v = lensBlob\(sessionViews, fields\);\s*\n\s*const writeId = holdViews\(applyLensFields\(effViews\(\), fields\), \{ lens: fields \}\);\s*\n\s*if \(vscodeApi\) vscodeApi\.postMessage\(\{ type: "setTimelineViews", views: v, writeId, edited: \[\] \}\);/,
    "the posted blob is the STORE's (sessionViews) plus the fields; the copy shown is the current one plus the fields; the record keeps the fields");
  assert.equal((RENDER.match(/\bpostViews\(/g) || []).length, 2, "postViews (a whole blob as posted) has ONE caller left: the no-capability tag path");
  assert.match(RENDER, /if \(!kernelCaps\.has\("tagEdit"\)\) \{[\s\S]{0,700}postViews\(nv, edited\);/);
  for (const site of [
    /postLens\(\{ actives: Object\.assign\(\{\}, \(v \|\| \{\}\)\.actives, \{ chat: l \}\) \}\);/,
    /postLens\(\{ actives: Object\.assign\(\{\}, \(mv2 \|\| \{\}\)\.actives, \{ chat: l \}\) \}\);/,
    /function revealSession\(id: string\) \{ const r = revealIn\(effViews\(\), id\); postLens\(\{ active: r\.active, actives: r\.actives \}\); \}/,
  ]) assert.match(RENDER, site);
  assert.equal((RENDER.match(/onApply: \(l\) => \{ postLens\(\{ actives: Object\.assign\(\{\}, \(effViews\(\) \|\| \{\}\)\.actives, \{ chat: l \}\) \}\); \},/g) || []).length, 2,
    "both tag-lens menus (desktop and phone)");
  const at = RENDER.indexOf("const editUnion = (g: TagUnion");
  const fly = RENDER.slice(at, RENDER.indexOf("// BROWSE FILES", at));
  assert.equal((fly.match(/if \(g\.localId && !g\.pending\) \{/g) || []).length, 2, "a pending union takes no add or remove op");
  assert.match(fly, /if \(g\.pending\) \{[\s\S]{0,500}busy\.textContent = "creating…"; row\.appendChild\(busy\);\s*\n\s*sub\.appendChild\(row\);\s*\n\s*continue;/,
    "a held tag whose create is in flight renders with no ✕");
  assert.match(fly, /const others = unionFor\(\)\.filter\(\(g\) => !g\.members\.includes\(id\) && !g\.pending\);/, "…and is not offered to join");
});
