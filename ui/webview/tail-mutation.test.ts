// A tail element leaving the DOM — even for part of one frame — is on the record (T262j, the user 2026-09-08). The
// remaining snap lands at scrollHeight − clientHeight − h, the bubble's height, from any position, 93 ms after a
// land that took, with scrollHeight unchanged at the next read and NO tail-change row: a clamp against a transcript
// momentarily h px shorter WITHIN a frame. A ResizeObserver reports frame-end sizes and cannot see that; a
// MutationObserver on the active view's element (and on the live-ask host) sees every child removed at the tail,
// including one re-appended in the same task, so a "tailmut" row names what left, whether it came back, and the
// scroll height before (the last one the pane recorded) and after. Pure summary executed here; wiring pinned.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { summarizeTailMutations, tailMutRow } from "./scroll-write";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const SID = "11111111-2222-4333-8444-000000000201";
const n = (cls: string) => ({ cls });

test("a removal at the END of the container is a tail removal; a node removed and re-added in the same task is re-added", () => {
  const bubble = n("turn turn-queued");
  const s = summarizeTailMutations([
    { removed: [bubble], added: [], atEnd: true },
    { removed: [], added: [bubble], atEnd: true },
  ]);
  assert.deepEqual(s, { removedTail: ["turn turn-queued"], addedTail: ["turn turn-queued"], reAdded: true });
});

test("a removal in the MIDDLE is not a tail removal; a removal with a different node appended is not a re-add", () => {
  const a = n("turn turn-assistant"), b = n("turn turn-tool");
  assert.equal(summarizeTailMutations([{ removed: [a], added: [], atEnd: false }]), null, "nothing left the tail");
  assert.deepEqual(summarizeTailMutations([{ removed: [a], added: [b], atEnd: true }]), { removedTail: ["turn turn-assistant"], addedTail: ["turn turn-tool"], reAdded: false });
  assert.equal(summarizeTailMutations([{ removed: [], added: [b], atEnd: true }]), null, "an append alone is the append path's business");
});

test("the row carries what left, whether it came back, and the scroll height before and after", () => {
  assert.deepEqual(tailMutRow(SID, { removedTail: ["turn turn-queued"], addedTail: ["turn turn-queued"], reAdded: true }, 9114, 9114, 8148.3, 902, "view"),
                   { sid: SID, where: "view", removed: ["turn turn-queued"], added: ["turn turn-queued"], reAdded: true, shBefore: 9114, shAfter: 9114, st: 8148.3, ch: 902 });
  assert.equal(tailMutRow(SID, { removedTail: ["x".repeat(80)], addedTail: [], reAdded: false }, 1, 2, 3, 4, "live-ask").removed[0].length, 40, "classes bounded");
});

test("render.ts observes the active view's children and the live-ask host's, and files the row through the capped diag path", () => {
  assert.match(RENDER, /import \{[^}]*\bsummarizeTailMutations\b[^}]*\btailMutRow\b[^}]*\} from "\.\/scroll-write";/);
  assert.match(RENDER, /function scrollDiagRow\(kind: "scrollwrite" \| "scrollgesture" \| "tailchange" \| "spacer" \| "tailmut" \| "unitchange", data: any\): void \{/);
  assert.match(RENDER, /mo\?: MutationObserver; \}/, "the View carries its mutation observer");
  assert.match(RENDER, /v\.mo = new MutationObserver\(\(records\) => \{/);
  assert.match(RENDER, /v\.mo\.observe\(elv, \{ childList: true \}\);/);
  assert.equal((RENDER.match(/v\.ro\?\.disconnect\(\); v\.mo\?\.disconnect\(\); v\.el\.remove\(\);/g) || []).length, 2, "both view-removal sites disconnect it");
  assert.match(RENDER, /const tailMo = new MutationObserver\(\(records\) => \{/, "the live-ask host too");
  assert.equal((RENDER.match(/scrollDiagRow\("tailmut", tailMutRow\(/g) || []).length, 2);
  // the "before" is the last scroll height the pane recorded, kept current by every write and every scroll event
  assert.match(RENDER, /let lastKnownSh = 0;/);
  assert.match(RENDER, /lastKnownSh = content\.scrollHeight;/);
});
