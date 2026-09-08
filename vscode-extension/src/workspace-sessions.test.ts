import { test } from "node:test";
import * as assert from "node:assert/strict";
import { citeText, normalizeDir, sessionMatchesFolders, sessionsForWorkspace } from "./workspace-sessions";
import { parsePorcelain } from "./session-diff";
import * as fs from "node:fs";
import * as path from "node:path";

test("normalizeDir strips trailing slashes", () => {
  assert.equal(normalizeDir("/a/b/"), "/a/b");
  assert.equal(normalizeDir("/"), "/");
  assert.equal(normalizeDir(""), "/");
});

test("session matches the window that has its dir (or a parent/child of it) open", () => {
  assert.ok(sessionMatchesFolders("/repos/romp", ["/repos/romp"]));               // exact
  assert.ok(sessionMatchesFolders("/repos/romp-vscode", ["/repos/romp-vscode"])); // a worktree opened directly
  assert.ok(sessionMatchesFolders("/repos/romp/ui", ["/repos/romp"]));            // session below the root
  assert.ok(sessionMatchesFolders("/repos/romp", ["/repos/romp/vscode-extension"]));     // window on a subfolder
  assert.ok(!sessionMatchesFolders("/repos/romp", ["/repos/romp-vscode"]));       // sibling is NOT a prefix match
  assert.ok(!sessionMatchesFolders("/repos/other", ["/repos/romp"]));
  assert.ok(!sessionMatchesFolders("", ["/repos/romp"]));
});

test("sessionsForWorkspace filters by dir", () => {
  const sessions = [
    { id: "1", name: "here", dir: "/repos/romp" },
    { id: "2", name: "away", dir: "/repos/other" },
  ];
  assert.deepEqual(sessionsForWorkspace(sessions, ["/repos/romp"]).map((s) => s.name), ["here"]);
});

test("citeText: bare file, single line, and range", () => {
  assert.equal(citeText("/a/f.ts"), "/a/f.ts");
  assert.equal(citeText("/a/f.ts", 5, 5, false), "/a/f.ts");        // cursor only, no selection
  assert.equal(citeText("/a/f.ts", 5, 5, true), "/a/f.ts:5");
  assert.equal(citeText("/a/f.ts", 5, 9, true), "/a/f.ts:5-9");
});

// parsePorcelain reads `git status --porcelain=v1 -z`: NUL-separated `XY path` records, paths raw
// (git quotes and escapes nothing under -z), and a rename's SOURCE in the record after its
// destination. Every fixture below is that byte shape. The newline-split parser this replaced
// C-unquoted only the outer quotes, split renames on the first " -> ", and read X alone.
test("parsePorcelain: modified, added, untracked, renamed (a spaced name arrives unquoted under -z)", () => {
  const out = [
    " M ui/webview/render.ts",
    "A  vscode-extension/src/new.ts",
    "?? notes.txt",
    "R  new name.ts", "old name.ts",
    "",
  ].join("\0");
  const files = parsePorcelain(out);
  assert.deepEqual(files.map((f) => f.path),
    ["ui/webview/render.ts", "vscode-extension/src/new.ts", "notes.txt", "new name.ts"]);
  assert.equal(files[0].status, "M");
  assert.equal(files[2].untracked, true);
  assert.equal(files[3].status, "R");
  assert.equal(files[3].renamedFrom, "old name.ts");
});

test("parsePorcelain: a -z rename is two records, destination then source", () => {
  const files = parsePorcelain("R  new.txt\0old.txt\0");
  assert.deepEqual(files.map((f) => [f.path, f.status, f.untracked, f.renamedFrom]),
    [["new.txt", "R", false, "old.txt"]]);
});

test("parsePorcelain: an unstaged rename (' R', X blank) carries its source too", () => {
  const files = parsePorcelain(" R newer.txt\0new.txt\0");
  assert.deepEqual(files.map((f) => [f.path, f.status, f.renamedFrom]), [["newer.txt", "R", "new.txt"]]);
});

test("parsePorcelain: R or C in either column takes one source record; other entries take none", () => {
  const files = parsePorcelain("C  copy.txt\0orig.txt\0RM moved.txt\0was.txt\0 M plain.txt\0?? loose.txt\0");
  assert.deepEqual(files.map((f) => [f.path, f.status, f.renamedFrom]), [
    ["copy.txt", "C", "orig.txt"],
    ["moved.txt", "RM", "was.txt"],
    ["plain.txt", "M", undefined],
    ["loose.txt", "??", undefined],
  ]);
});

test("parsePorcelain: unusual names round-trip byte for byte", () => {
  const names = [
    "notes/雪.txt",         // non-ASCII: octal-escaped in quotes without -z
    'say "hi".txt',         // embedded double quote
    "back\\slash.txt",      // embedded backslash
    "line1\nline2.txt",     // embedded newline: a record boundary to a newline-split parser
    "trail.txt ",           // trailing space: the old unquote() trimmed it off
    "a -> z.txt",           // the rename arrow as ordinary path text
  ];
  for (const name of names) {
    assert.deepEqual(parsePorcelain(` M ${name}\0`).map((f) => f.path), [name], JSON.stringify(name));
  }
});

test("parsePorcelain: ' -> ' inside a renamed path is path text, not a separator", () => {
  const files = parsePorcelain("R  b -> c.txt\0a -> z.txt\0");
  assert.deepEqual(files.map((f) => [f.path, f.renamedFrom]), [["b -> c.txt", "a -> z.txt"]]);
});

test("parsePorcelain: the NUL after the last record ends it, it is not an extra record", () => {
  assert.deepEqual(parsePorcelain(" M a.txt\0").map((f) => [f.path, f.status, f.untracked, f.renamedFrom]),
    [["a.txt", "M", false, undefined]]);
});

test("parsePorcelain: a rename whose source record is cut off keeps the destination and invents no source", () => {
  for (const out of ["R  new.txt\0", "R  new.txt"]) {
    assert.deepEqual(parsePorcelain(out).map((f) => [f.path, f.renamedFrom]), [["new.txt", undefined]],
      JSON.stringify(out));
  }
});

// (review find, 2026-09-08) The record-shape filter (`XY<space>`) runs on entries only, never on
// the record a rename consumes as its source: a source path that happens to start with two letters
// and a space is still the source. A source shaped like a RENAME record is the sharp case: parsed as
// an entry, it would swallow the entry behind it as its own source, and that file would vanish
// from the pick list.
test("parsePorcelain: a rename source shaped like a status record is still consumed as the source", () => {
  const files = parsePorcelain("R  new.txt\0RM plan.txt\0 M plain.txt\0");
  assert.deepEqual(files.map((f) => [f.path, f.status, f.renamedFrom]), [
    ["new.txt", "R", "RM plan.txt"],
    ["plain.txt", "M", undefined],
  ]);
});

test("parsePorcelain tolerates junk", () => {
  assert.deepEqual(parsePorcelain(""), []);
  assert.deepEqual(parsePorcelain("\0\0xx"), []);     // empty records, and one too short to carry a path
  assert.deepEqual(parsePorcelain("abcd\0"), []);      // no separating space: not a status record
});

test("diffSessionChanges asks git for the -z shape parsePorcelain reads, through an args-preserving gitIn", () => {
  const SRC = fs.readFileSync(path.join(process.cwd(), "src", "extension.ts"), "utf8");
  assert.match(SRC, /parsePorcelain\(await gitIn\(s\.dir, \["status", "--porcelain=v1", "-z"\]\)\)/);
  assert.match(SRC, /execFile\("git", \["-C", dir, \.\.\.args\]/);
});
