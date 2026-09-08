// A "Previously attached" row that only remembers a mail-trust tier must SAY so (the user
// 2026-08-12): a hub's known row for a spoke — a tier set in the relay era, no tunnel ever
// attached from that machine — rendered as "Previously attached", which reads as a past ssh
// session that never happened. The kernel stamps `attached` on the attach/detach/check-in
// writers (_known_note attached=True; trust-only writers never touch it), and BOTH popover
// copies split the row treatment on it: label, tooltip, and the button (Attach, not Re-attach).
// Pinned in both copies per the net-trust-pending discipline.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const ROOT = path.resolve(process.cwd(), "..");
const KERNEL = fs.readFileSync(path.join(ROOT, "kernel", "kernel.py"), "utf8");
const STRIP = fs.readFileSync(path.join(ROOT, "ui", "webview", "strip.ts"), "utf8");

test("kernel: the known store records attach-path writes distinctly from trust-only ones", () => {
  assert.match(KERNEL, /def _known_note\(host, trust=None, share=None, attached=None\):/);
  assert.match(KERNEL, /if attached:\s*\n\s*e\["attached"\] = True/);
  // calls carry nested parens (bool(on), r.get(...)) — match to the end of the single-line call
  assert.ok((KERNEL.match(/_known_note\(.*attached=True\)/g) || []).length >= 5,
    "attach, alias-fold, detach, checkin_set and checkin_apply all stamp the flag");
});

test("web popover: a trust-only row is labeled, tooltipped, and buttoned as never-attached", () => {
  assert.match(KERNEL, /var kwas=!!k\.attached;/);
  // \uXXXX escapes in the inline JS are literally two backslashes in the file — hence \\\\
  assert.match(KERNEL, /trust remembered \\\\u00b7 never attached here/);
  assert.match(KERNEL, /No tunnel to '\+kh\+' has ever been attached from this machine/);
  assert.match(KERNEL, /\(kwas\?'Re-attach':'Attach'\)/);
  assert.match(KERNEL, /A row marked \\\\u201ctrust remembered\\\\u201d was never attached from this machine/,
    "the section header explains the mixed rows");
});

test("VS Code popover: the same split, in step", () => {
  assert.match(STRIP, /const kwas = !!k\.attached;/);
  assert.match(STRIP, /trust remembered · never attached here · \$\{k\.trust \|\| "directed"\}/);
  assert.match(STRIP, /No tunnel to \$\{k\.host\} has ever been attached from this machine/);
  assert.match(STRIP, /kwas \? "Re-attach" : "Attach"/);
  assert.match(STRIP, /A row marked “trust remembered” was never attached from this "\s*\n\s*\+ "machine/);
});
