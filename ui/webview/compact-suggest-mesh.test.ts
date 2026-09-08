// Suggest /compact is ONE value across every attached machine (T248, the user 2026-09-07: their gear
// showed the box unchecked with the mixed mark, yet a session on an attached machine received the
// suggestion that night — the attached kernel's own copy was on). The first cut (T208) made the setting
// per-install on purpose; the user overruled that: no mixed state for this setting, ever. So the checkbox
// now rides federation's KERNEL_SETTING broadcast like setFileEditing — one click writes every attached
// kernel, and the mixed mark for this control can only be transient (the next fill clears it). The gt
// gating stays: a queued flush must not undo a newer choice. Its copy and gate also stop naming
// "workers": a workers roster is a convention the user runs on top of romp, not something romp knows.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const ROOT = path.resolve(process.cwd(), "..");
const read = (...p: string[]) => fs.readFileSync(path.join(ROOT, ...p), "utf8");
const GEAR = read("ui", "webview", "gear.js");
const FED = read("ui", "webview", "federation.ts");
const KERNEL = read("bin", "romp-kernel");

test("setCompactSuggest is a KERNEL_SETTING: one click writes every attached kernel (T248)", () => {
  const setSrc = FED.match(/const KERNEL_SETTING = new Set\(\[([\s\S]*?)\]\)/);
  assert.ok(setSrc, "federation.ts's KERNEL_SETTING set located");
  assert.ok(setSrc![1].includes('"setCompactSuggest"'),
    "the set carries it — the broadcast is what makes the one answer reach every machine");
  // the gear still stamps the gesture: the kernel orders applies by gt, so a queued flush from a frozen
  // tab can never undo a newer choice made elsewhere
  assert.ok(GEAR.includes("post({ type: 'setCompactSuggest', enabled: csg.checked, gt: gclock.stamp('compact-suggest') })"),
    "the post is gesture-stamped, unchanged");
  assert.ok(!GEAR.includes("Suggest /compact are kernel-side but PER-INSTALL"),
    "the gear's routing comment no longer calls it per-install");
});

test("the Suggest /compact copy names no workers and promises every connected machine (T248)", () => {
  const at = GEAR.indexOf("id=rs-suggestcompact");
  assert.ok(at > 0, "the checkbox exists");
  const sub = GEAR.slice(at, GEAR.indexOf("</label>", at));
  assert.ok(!/workers/i.test(sub), "no 'workers' in the copy — not a romp concept");
  assert.ok(!sub.includes("keeps its own copy"), "no per-install sentence");
  assert.ok(sub.includes("Applies on every connected machine’s kernel."),
    "the fileEditing wording: the setting follows to every attached kernel");
  assert.ok(sub.includes("Off by default for a fresh install"), "the default stays stated");
  assert.ok(/muted sessions/.test(sub) && /mid-turn/.test(sub), "the muted and mid-turn exclusions stay named");
});

test("the suggestion's gate reads no session tags: a *_workers roster is not romp's concept (T248)", () => {
  assert.ok(!KERNEL.includes("def _worker_tag_member"), "the tag-roster gate is deleted, not bypassed");
  assert.ok(!KERNEL.includes("_worker_tag_member("), "…and nothing calls it");
  const start = KERNEL.indexOf("# ── the compaction SUGGESTION");
  const end = KERNEL.indexOf("\ndef _compact_suggest_body(", start);
  assert.ok(start > 0 && end > start, "the regime's block comment located");
  const block = KERNEL.slice(start, end);
  assert.ok(!/recycle|owns workers|workers are excluded|workers-only/i.test(block),
    "the block comment carries neither the recycle framing nor the workers exclusion");
  assert.ok(block.includes("Session TAGS are not a gate"), "…and says so in romp's terms");
  const tick = KERNEL.slice(KERNEL.indexOf("def _compact_suggest_tick("), KERNEL.indexOf("\ndef ", KERNEL.indexOf("def _compact_suggest_tick(") + 10));
  assert.ok(/hideFromFeed/.test(tick) && /threadOf/.test(tick) && /_PROGRESSING_STATES/.test(tick),
    "the muted, comment-thread and mid-turn gates stay");
  assert.ok(!/worker/i.test(tick), "no worker gate in the tick");
});
