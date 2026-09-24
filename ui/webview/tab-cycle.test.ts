// Cycling the sessions of a chat column by key (the user 2026-09-23): the browser's "Go to the next / previous
// session" commands and their default chords, beside the VS Code view's rompChat.nextTab / prevTab, which had the
// keys already. The chord rules run against the real keybindings model; the shell's registration (palette-main.ts),
// the pane's message arm (render.ts) and the pane-focus script's bail (kernel.py) are pinned at source — the repo's
// convention where there is no DOM — and the VS Code bindings are read from the extension's own manifest.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { DEFAULT_CHORDS } from "./commands";
import { BUILT_IN, FIXED_KEYS, builtInOwner, chordMap, chordOf, conflictOf, dispatchable, displayChord, resolveChord, yieldsTo } from "./keybindings";

const read = (...p: string[]) => fs.readFileSync(path.resolve(process.cwd(), "..", ...p), "utf8");
const MAIN = read("ui", "webview", "palette-main.ts");
const RENDER = read("ui", "webview", "render.ts");
const KERNEL = read("kernel", "kernel.py");
const MANIFEST = JSON.parse(read("vscode-extension", "package.json"));
const PREVIEW = read("ui", "webview", "preview.ts");
const MODAL = read("ui", "webview", "shortcuts-modal.ts");
const PAIR = [["chat.nextTab", "ArrowRight"], ["chat.prevTab", "ArrowLeft"]] as const;

test("the defaults are literal Ctrl+Alt+arrows: one chord on every platform, and the one a browser's keydown spells", () => {
  assert.equal(DEFAULT_CHORDS["chat.nextTab"], "Ctrl+Alt+ArrowRight");
  assert.equal(DEFAULT_CHORDS["chat.prevTab"], "Ctrl+Alt+ArrowLeft");
  for (const [id, key] of PAIR) {
    const d = DEFAULT_CHORDS[id];
    assert.equal(resolveChord(d, true), resolveChord(d, false), "no Mod: a Mac gets Control+Option, not the Cmd+Option the browser owns");
    assert.equal(chordOf({ key, ctrlKey: true, altKey: true, shiftKey: false, metaKey: false }), resolveChord(d, false));
  }
  assert.equal(displayChord(DEFAULT_CHORDS["chat.nextTab"], true), "⌃⌥→");
  assert.equal(displayChord(DEFAULT_CHORDS["chat.nextTab"], false), "Ctrl+Alt+→");
});

test("the bare arrows are the pair's FIXED keys: shown on its rows, refused by the recorder, gone from the built-in section", () => {
  // the maintainer (2026-09-23): the arrows already switch sessions and belong in the keymap — so the pair's rows carry them
  assert.deepEqual(FIXED_KEYS["chat.nextTab"], ["ArrowRight", "Go to the next session, from the tab bar"]);
  assert.deepEqual(FIXED_KEYS["chat.prevTab"], ["ArrowLeft", "Go to the previous session, from the tab bar"]);
  for (const mac of [true, false]) {
    assert.equal(builtInOwner("ArrowRight", mac), FIXED_KEYS["chat.nextTab"][1], "still a built-in: the panes own the bare arrows");
    assert.equal(builtInOwner("ArrowLeft", mac), FIXED_KEYS["chat.prevTab"][1]);
  }
  assert.ok(!BUILT_IN.some(([spec]) => /Arrow(Left|Right)/.test(spec) && !spec.includes("+")), "the separate built-in line is gone");
  assert.match(MODAL, /const fixedKey = FIXED_KEYS\[c\.id\];\n\s*if \(fixedKey\) \{[\s\S]*?fk\.className = "rkeys-chip rkeys-fixedkey";\n\s*fk\.textContent = displayChord\(fixedKey\[0\], mac\);[\s\S]*?where\.textContent = "from the tab bar";/,
               "the row shows the fixed key, dressed like the built-in section's chips, and where it works");
  assert.match(MODAL, /\.rkeys-chip\.rkeys-fixedkey\{color:#9aa0a6;border-color:#33363b\}/);
});

test("the chords are free: no built-in behaviour owns them and no other default holds them", () => {
  const cmds = Object.entries(DEFAULT_CHORDS).map(([id, chord]) => ({ id, chord }));
  for (const mac of [true, false]) {
    for (const [id] of PAIR) {
      assert.equal(builtInOwner(DEFAULT_CHORDS[id], mac), null, "the shell's Alt+Arrow pane focus is not Ctrl+Alt+Arrow");
      assert.equal(conflictOf(DEFAULT_CHORDS[id], id, cmds, {}, mac), null);
    }
  }
});

test("the chord fires from the composer, where the strip's bare arrows do not — and never inside an input method's composition", () => {
  assert.equal(dispatchable({ ctrlKey: true, altKey: true, metaKey: false }, true), true, "a Ctrl/Alt chord dispatches whatever holds the focus");
  assert.equal(dispatchable({ ctrlKey: false, altKey: false, metaKey: false }, true), false, "a bare arrow while typing is typing");
  assert.equal(dispatchable({ ctrlKey: true, altKey: true, metaKey: false, isComposing: true }, true), false, "a composing keydown is the composition's");
  assert.equal(dispatchable({ ctrlKey: true, altKey: true, metaKey: false, keyCode: 229 }, false), false, "…the legacy keyCode too");
  assert.equal(dispatchable({ ctrlKey: true, altKey: true, metaKey: false, repeat: true }, false), false, "an auto-repeat never re-fires a chord");
  // the shell's Alt+Arrow capture bails on any further modifier, so a Ctrl+Alt+Arrow keydown reaches the dispatcher
  assert.match(KERNEL, /if\(!e\.altKey\|\|e\.shiftKey\|\|e\.ctrlKey\|\|e\.metaKey\)return;\s+\/\/ Alt\(Option\)\+Arrow ONLY \(no other modifiers\)/);
});

test("a chord the reader saved for another command outranks the pair's default, and the dialog says which way it went", () => {
  const cmds = [{ id: "chat.nextSplit" }, { id: "chat.nextTab", chord: "Ctrl+Alt+ArrowRight" }, { id: "chat.prevTab", chord: "Ctrl+Alt+ArrowLeft" }];
  const saved = { "chat.nextSplit": "Ctrl+Alt+ArrowRight" };                  // bound before the pair existed
  for (const mac of [true, false]) {
    assert.equal(chordMap(cmds, saved, mac).get("Ctrl+Alt+ArrowRight"), "chat.nextSplit", "the saved binding keeps its key");
    assert.equal(chordMap(cmds, saved, mac).get("Ctrl+Alt+ArrowLeft"), "chat.prevTab", "the other default stands");
    assert.equal(yieldsTo("chat.nextTab", cmds, saved, mac), "chat.nextSplit", "…and the dialog can name the winner");
    assert.equal(yieldsTo("chat.prevTab", cmds, saved, mac), null);
    assert.equal(chordMap(cmds, {}, mac).get("Ctrl+Alt+ArrowRight"), "chat.nextTab", "with nothing saved the default dispatches");
    assert.equal(yieldsTo("chat.nextTab", cmds, {}, mac), null);
    assert.equal(chordMap(cmds, { "chat.nextTab": "" }, mac).has("Ctrl+Alt+ArrowRight"), false, "a deliberate unbind holds no chord and takes none");
    assert.equal(yieldsTo("chat.nextTab", cmds, { "chat.nextTab": "" }, mac), null);
  }
  // two SAVED bindings on one chord (a hand-edited store) keep the old rule: the last registered wins
  assert.equal(chordMap([{ id: "a" }, { id: "b" }], { a: "Ctrl+K", b: "Ctrl+K" }, false).get("Ctrl+K"), "b");
  assert.match(MODAL, /row\.dataset\.cmd = c\.id;/, "every dialog row carries its command id");
  assert.match(MODAL, /const winner = yieldsTo\(c\.id, bindableCommands\(\), overrides, mac\);[\s\S]*?y\.textContent = "yields to \\u201c" \+ \(other \? other\.title : winner\) \+ "\\u201d";/,
               "a yielding default's row says so");
});

test("palette-main.ts registers the pair, posting the pane the messages the VS Code view posts — as the reader's gesture, and not under a full-pane surface", () => {
  assert.match(MAIN, /const stepSession = \(type: "nextTab" \| "prevTab"\): void => \{ if \(fullPaneUp\(\)\) return; chatPost\(\{ type, gesture: true \}\); \};/);
  assert.match(MAIN, /querySelector\("#romp-fileview, #romp-filebrowse, #romp-lightbox"\)/, "the type-to-focus gate's list of full-pane surfaces");
  assert.match(MAIN, /registerCommand\(\{ id: "chat\.nextTab", title: "Go to the next session", run: \(\) => stepSession\("nextTab"\) \}\);/);
  assert.match(MAIN, /registerCommand\(\{ id: "chat\.prevTab", title: "Go to the previous session", run: \(\) => stepSession\("prevTab"\) \}\);/);
  assert.match(MAIN, /postMessage\(\{ type: "jumpSession", id: sid, gesture: true \}, "\*"\)/, "the per-tab hot key says so too");
  // the arm stands down under a layer of the page (2026-09-24: the shell's check saw only the full-pane surfaces, and
  // the VS Code command never passes through it); the braces keep the next arm's else off the inner if.
  // tab-cycle-standdown-exec.test.ts runs the arm under each layer
  assert.match(RENDER, /else if \(m\.type === "nextTab"\) \{ if \(!paneLayerOpen\(\)\) asGesture\(\(\) => cycleTab\(1\)\); \}[^\n]*\n\s*else if \(m\.type === "prevTab"\) \{ if \(!paneLayerOpen\(\)\) asGesture\(\(\) => cycleTab\(-1\)\); \}/,
               "one arm for the shell's post and the VS Code host's, run as the reader's gesture unless a layer of the page is up");
  assert.match(RENDER, /installSnapshotEscape\(window, \{\n\s*showing: \(\) => !!snapView,\n\s*typing: isTypingTarget,\n\s*layerOpen: \(\) => paneLayerOpen\(\) \|\| !!openCommentKey,/,
               "the pair and the snapshot view's Escape read one list of the page's layers; the Escape also yields to an open comment thread");
  assert.match(RENDER, /if \(m\.gesture === true\) asGesture\(\(\) => setActive\(m\.id\)\); else setActive\(m\.id\);/, "a jump carries its gesture only when the sender says so");
  assert.match(RENDER, /const gesture = gestureHeld \|\| inInputEvent\(\);/, "notifyActive reads the flag");
  assert.match(RENDER, /function asGesture\(fn: \(\) => void\): void \{\n\s*const was = gestureHeld;\n\s*gestureHeld = true;\n\s*try \{ fn\(\); \} finally \{ gestureHeld = was; \}/);
  // "Switch to <name>" is the per-tab hot key's title: the dialog's solo heading strips that prefix and the served split
  // test lists the hot-key rows by it, so the pair must not wear it (CI caught the first spelling, 2026-09-23)
  for (const m of MAIN.matchAll(/id: "chat\.(?:next|prev)Tab", title: "([^"]+)"/g)) assert.doesNotMatch(m[1], /^Switch to /, m[1]);
});

test("the pane's side of a chord switch: menus follow the draft, a folded tab steps, the viewer and a focused tab leave modified arrows alone", () => {
  // the slash menu and the mention card re-read the box after the draft swap, as the clear path does
  assert.match(RENDER, /ta\.value = drafts\.get\(id\) \?\? "";\n\s*refreshComposerMenus\?\.\(\);/);
  assert.match(RENDER, /refreshComposerMenus = \(\) => \{ updateSlash\(\); updateMention\(\); \};/);
  // cycleTab: the folded branch runs before the visible-count check, so one tab on screen is somewhere to step to
  const cyc = RENDER.slice(RENDER.indexOf("function cycleTab(dir: number) {"), RENDER.indexOf("\n}\n", RENDER.indexOf("function cycleTab(dir: number) {")));
  assert.ok(cyc.indexOf("neighborOfFolded(lastStripItems, activeId, dir > 0 ? 1 : -1)") < cyc.indexOf("if (ord.length < 2) return;"), cyc);
  assert.ok(!/const ord = visibleOrder\(\);\s*\n\s*if \(ord\.length < 2 \|\| !activeId\) return;/.test(cyc), "the old early return is gone");
  // the picture viewer steps only on a BARE arrow; a focused tab's own handler ignores every modified key
  assert.match(PREVIEW, /if \(ev\.ctrlKey \|\| ev\.altKey \|\| ev\.metaKey\) return;[^\n]*\n[^\n]*\n\s*if \(\(ev\.key === "ArrowLeft" \|\| ev\.key === "ArrowRight"\) && step\) \{/);
  assert.match(RENDER, /function onTabKey\(e: KeyboardEvent\) \{\n\s*if \(!order\.length\) return;\n\s*if \(e\.ctrlKey \|\| e\.altKey \|\| e\.metaKey\) return;/);
});

test("VS Code binds the same pair to Ctrl+Alt+arrows (Cmd+Alt on a Mac) while the romp panel is active, and posts the same messages", () => {
  const kb = MANIFEST.contributes.keybindings as Array<{ command: string; key?: string; mac?: string; when: string }>;
  const next = kb.find((k) => k.command === "rompChat.nextTab" && k.key);
  const prev = kb.find((k) => k.command === "rompChat.prevTab" && k.key);
  assert.equal(next?.key, "ctrl+alt+right");
  assert.equal(prev?.key, "ctrl+alt+left");
  assert.equal(next?.mac, "cmd+alt+right");
  assert.equal(prev?.mac, "cmd+alt+left");
  for (const k of kb.filter((x) => x.command === "rompChat.nextTab" || x.command === "rompChat.prevTab")) {
    assert.equal(k.when, "activeWebviewPanelId == 'rompChat'");
  }
  const EXT = read("vscode-extension", "src", "extension.ts");
  assert.match(EXT, /registerCommand\("rompChat\.nextTab", \(\) => panel\?\.webview\.postMessage\(\{ type: "nextTab" \}\)\)/);
  assert.match(EXT, /registerCommand\("rompChat\.prevTab", \(\) => panel\?\.webview\.postMessage\(\{ type: "prevTab" \}\)\)/);
});
