// ONE machine-injected rendering for everything romp injects (T130, the user 2026-08-27: a nudge
// says romp above it, but the PR-watch notice printed a literal square-bracket prefix inside the
// bubble — the parser treated two romp-injected shapes differently). The contract, per shape:
//
//   MACHINE-VOICED (carry <!-- romp-injected --> at the injection site; classify "romp"; render
//   the romp mark + swirl above a gray bubble, the source prefix stripped for display):
//     kernel-restart resume · rename ping · process-died notice · dead-background-tasks notice ·
//     pr-watch landing family · generic watch family (markers added by T130) · auto/fork nudges ·
//     multi-goal bundles · awaiting backstop · debt reminders · the retry message · goal check-ins ·
//     the compaction suggestion (T207: person-voiced prose, but the ARRIVAL is the kernel's — a bare
//     send rendered as the user's own blue bubble and the user ruled it must read system-injected)
//   PERSON-VOICED BY DESIGN (no marker — they are written as the person's own words, per the
//   2026-06-20 rule and the injected-voice test): typed follow-ups · the Continue gesture ·
//   comment-thread openers · edit traces — these stay the user's blue. (Thread RELAYS moved to
//   the machine-voiced set by T145: the user ruled the arrival is romp moving content on their
//   behalf, not their own typed words — the prose still speaks as the person for the AGENT.)
//   THIRD-PARTY TAGGED (romp-tag with no romp-injected): the ⚙-labelled tag bubble.
//
// The classifier is executable here; the display strip and the marker discipline are source pins.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { senderKind } from "./sender-identity";

const RENDER = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "render.ts"), "utf8");
const KERNEL = fs.readFileSync(path.resolve(process.cwd(), "..", "kernel", "kernel.py"), "utf8");
const SDK = fs.readFileSync(path.resolve(process.cwd(), "..", "kernel", "sdk_backend.py"), "utf8");

test("every machine-voiced shape classifies 'romp' — the flag the markers set, never prose matching", () => {
  // the kernel authors 'romp' from the romp-injected marker; the classifier keys on that flag
  for (const shape of [
    { name: "kernel-restart resume", ev: { romp: true, md: "[romp] The romp kernel restarted…" } },
    { name: "pr-watch landing", ev: { romp: true, md: "[romp] The pull request you asked romp to watch has MERGED…", tag: "pr-watch" } },
    { name: "generic watch", ev: { romp: true, md: "[romp] The condition you asked romp to watch now HOLDS…", tag: "watch" } },
    { name: "thread relay (T145)", ev: { romp: true, md: "I took a side discussion with another assistant about this passage…", tag: "relay" } },
    { name: "auto-nudge", ev: { romp: true, rompAuto: true, md: "Where does this stand?" } },
    { name: "compaction suggestion (T207)", ev: { romp: true, md: "It's been quiet here for a while…" } },
    { name: "nudge button", ev: { romp: true, md: "Status update please?" } },
  ]) assert.equal(senderKind(shape.ev as never), "romp", shape.name + " wears the one machine treatment");
  // …and the romp flag OUTRANKS a tag: a tagged watch notice is romp's own voice, not a third party's
  assert.equal(senderKind({ romp: true, tag: "pr-watch", md: "x" } as never), "romp");
  // person-voiced injections stay the person's
  assert.equal(senderKind({ human: true, md: "ship it" } as never), "user", "typed follow-up");
  assert.equal(senderKind({ human: true, tag: "peer-ci", md: "build green" } as never), "tagged", "a third party's tag message (tag turns enter as human rows)");
  assert.equal(senderKind({ md: "<system-reminder>…" } as never), "injected", "harness noise");
});

test("the visible source prefix strips for DISPLAY only, in the romp render branch", () => {
  const at = RENDER.indexOf("} else if (romp && ev.md) {");
  assert.ok(at > 0, "the romp render branch exists");
  const branch = RENDER.slice(at, RENDER.indexOf("} else if (ev.md) {", at));
  assert.match(branch, /const raw = ev\.md\.replace\(\/<!--\[\\s\\S\]\*\?-->\/g, ""\)\.replace\(\/\^\\s\*\\\[romp\\\]\\s\*\/, ""\)\.trim\(\);/,
    "comments AND the literal source prefix strip from the displayed text");
  assert.ok(!branch.includes("ev.md =") && !RENDER.includes("ev.md = ev.md.replace"),
    "the transcript record is never mutated — the prefix still tells the AGENT where the message came from");
  // the plain user branch renders ev.md untouched (no strip — that is romp-only); the user's own
  // words go through userMd (newlines kept), a harness note through md
  const userBranch = RENDER.slice(RENDER.indexOf("} else if (ev.md) {", at));
  assert.match(userBranch.slice(0, 400), /bubble\.innerHTML = kind === "user" \? userMd\(ev\.md\) : md\(ev\.md\);/);
});

test("the watch notices carry the marker at the injection site — no prose pattern-matching anywhere", () => {
  assert.match(KERNEL, /return body \+ "\\n\\n<!-- romp-injected --><!-- romp-system --><!-- romp-tag: pr-watch -->"/);
  // T207: the compaction suggestion's send appends the injector tail (romp-note + injected)
  // right after the prose — the source pin that keeps it out of the blue-bubble class. T212
  // templated the prose per recipient (_compact_suggest_body names the runnable command), so
  // the pin follows the call, same tail.
  assert.match(KERNEL, /_compact_suggest_body\(_name_of\(sid\) or sid\[:8\]\) \+ "\\n\\n"\n\s+"<!-- romp-note:/);
  const sugSend = KERNEL.slice(KERNEL.indexOf("_compact_suggest_body(_name_of(sid)"), KERNEL.indexOf("_compact_suggest_body(_name_of(sid)") + 600);
  assert.match(sugSend, /<!-- romp-injected -->/);
  assert.ok(!sugSend.includes("<!-- romp-auto -->"),
    "NOT romp-auto: that marker means auto-NUDGES and its gist says 'nudged for a status update' — " +
    "injected alone gives the gray bubble with the prose's own first line as the gist");
  assert.match(KERNEL, /return body \+ "\\n\\n<!-- romp-injected --><!-- romp-system --><!-- romp-tag: watch -->"/);
  // the restart family already wore them
  assert.match(SDK, /<!-- romp-injected --><!-- romp-system -->\[romp\] The romp kernel restarted/);
  // and nobody classifies by matching the visible prefix
  assert.ok(!/startsWith\(["']\[romp\]/.test(RENDER), "no prose matching in the renderer");
});
