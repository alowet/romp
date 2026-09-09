// THE TAG-LENS MENU'S TAGS ARE CHIPS (the user 2026-09-09, T283): each union tag renders as the shared
// tag chip and acts as a toggle button — selected = full colour, unselected = faded (its colour kept),
// aria-pressed on the chip, one tag per line with the chip at the left, the menu staying open across
// toggles. All and (no tags) keep the row grammar (All the exclusive pick), the group switch row is
// unchanged. Executed against a stub document (the tab-groups pattern: no jsdom) plus source pins on
// tag-menu.ts and the two sheets. Synthetic tags only.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const ui = (...p: string[]) => fs.readFileSync(path.resolve(process.cwd(), "..", "ui", ...p), "utf8");
const MENU = ui("webview", "tag-menu.ts");
const CSS = ui("webview", "styles.css");
const FEED_CSS = ui("webview", "feed.css");
const OPEN = MENU.slice(MENU.indexOf("export function openTagMenu"), MENU.indexOf("export function tagMenuButton"));
const LOOP = OPEN.slice(OPEN.indexOf("for (const u of opts.unions())"), OPEN.indexOf("if (opts.groupToggle || opts.onConfigure)"));

type Node = { tag: string; attrs: Record<string, string>; kids: Node[]; text?: string; style: Record<string, string>;
              handlers: Record<string, () => void>; setAttribute(k: string, v: string): void; getAttribute(k: string): string | null;
              appendChild(c: Node): void; addEventListener(k: string, fn: () => void): void; remove(): void;
              getBoundingClientRect(): { left: number; right: number; top: number; bottom: number };
              offsetWidth: number; offsetHeight: number; textContent: string; dataset: Record<string, string> };

/** The real openTagMenu against a stub document; returns the menu's rows and the recorded applies. */
function open(lens: { all?: boolean; none?: boolean; tags?: string[] }, unions: { name: string; color: string }[]) {
  const created: Node[] = [];
  const mk = (tag: string): Node => {
    const n: Node = { tag, attrs: {}, kids: [], style: {}, handlers: {}, offsetWidth: 200, offsetHeight: 100, dataset: {},
      get textContent() { return this.kids.map((k) => k.tag === "#text" ? k.text || "" : k.textContent).join(""); },
      set textContent(v: string) { this.kids = v ? [{ tag: "#text", text: v } as Node] : []; },
      setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
      appendChild(c) { this.kids.push(c); }, addEventListener(k, fn) { this.handlers[k] = fn; }, remove() { /* detached */ },
      getBoundingClientRect() { return { left: 10, right: 40, top: 10, bottom: 30 }; } };
    created.push(n); return n;
  };
  const g = globalThis as any;
  const saved = { document: g.document, window: g.window, localStorage: g.localStorage };
  const body = mk("body");
  g.document = { createElement: mk, createTextNode: (t: string) => ({ tag: "#text", text: t }), body, addEventListener() { /* closers */ } };
  g.window = { addEventListener() { /* storage */ }, innerWidth: 1200, innerHeight: 800 };
  g.localStorage = { setItem() { /* echo */ } };
  const applies: { lens: unknown; done: boolean }[] = [];
  let current = lens;
  // the stub document stays installed until close(): the rows' click handlers rebuild the menu through it
  const restore = () => { g.document = saved.document; g.window = saved.window; g.localStorage = saved.localStorage; };
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const mod = require("./tag-menu");
    mod.closeTagMenu();
    mod.openTagMenu(mk("button"), {
      lens: () => current,
      unions: () => unions.map((u) => ({ ...u, members: [], ids: [], localId: null, locals: [], remotes: [] })),
      onApply: (l: unknown, done: boolean) => { applies.push({ lens: l, done }); current = l as typeof lens; },
    });
    const menu = body.kids[body.kids.length - 1];
    return { menu, applies, rows: () => menu.kids, created, close: () => { mod.closeTagMenu(); restore(); } };
  } catch (e) { restore(); throw e; }
}

const label = (n: Node): string => n.kids.map((k) => k.tag === "#text" ? (k.text || "") : label(k)).join("");   // recursive: the return type is stated (tsc strict)
const chipOf = (row: Node) => row.kids.find((k) => k.tag === "span" && "aria-pressed" in k.attrs) as Node | undefined;

test("each union tag is its own chip acting as a toggle: selected full colour + aria-pressed=true, unselected faded + the off class", () => {
  const m = open({ tags: ["infra"] }, [{ name: "infra", color: "#54B204" }, { name: "qa", color: "#3355aa" }]);
  const rows = m.rows();
  assert.equal(label(rows[0]), "All"); assert.equal(label(rows[1]), "(no tags)");
  const infra = chipOf(rows[2])!, qa = chipOf(rows[3])!;
  assert.ok(infra && qa, "the two tags render as chips, one per row, after All and (no tags)");
  assert.equal(infra.attrs["aria-pressed"], "true");
  assert.equal(infra.attrs["role"], "button");
  assert.doesNotMatch(infra.attrs.style, /opacity/, "a selected chip stands at full opacity");
  assert.equal(infra.attrs["class"], undefined, "…and wears no off class");
  assert.match(infra.attrs.style, /border:1px solid #54B204;color:#54B204;/, "the chip keeps the tag's own colour");
  assert.equal(qa.attrs["aria-pressed"], "false");
  assert.equal(qa.attrs["class"], "tag-chip-off", "an unselected chip wears the faded class");
  assert.match(qa.attrs.style, /opacity:0\.45;/, "…and paints the same fade inline for a sheet-less host");
  assert.match(qa.attrs.style, /border:1px solid #3355aa;color:#3355aa;/, "faded, not recoloured");
  assert.equal(label(rows[2]), "infra"); assert.equal(label(rows[3]), "qa");
  for (const r of [rows[2], rows[3]]) assert.ok(!label(r).includes("✓"), "the tag rows carry no ✓: the chip's state IS the mark");
  m.close();
});

test("clicking a chip's row toggles that tag and the menu stays open and repaints", () => {
  const m = open({ tags: ["infra"] }, [{ name: "infra", color: "#54B204" }, { name: "qa", color: "#3355aa" }]);
  const before = m.rows().length;
  m.rows()[3].handlers.click();   // qa: off → on
  assert.deepEqual(m.applies, [{ lens: { none: undefined, tags: ["infra", "qa"] }, done: false }], "the toggle applies without closing (done=false)");
  const rows = m.rows();
  assert.equal(rows.length, before, "repainted in place: the same rows");
  assert.equal(chipOf(rows[3])!.attrs["aria-pressed"], "true", "the chip now reads selected");
  assert.equal(chipOf(rows[3])!.attrs["class"], undefined);
  rows[2].handlers.click();       // infra: on → off
  assert.equal(chipOf(m.rows()[2])!.attrs["aria-pressed"], "false");
  assert.equal(chipOf(m.rows()[2])!.attrs["class"], "tag-chip-off");
  m.close();
});

test("All and (no tags) keep the row grammar: All is the exclusive pick that closes the menu, (no tags) toggles with the ✓", () => {
  const m = open({ none: true, tags: ["infra"] }, [{ name: "infra", color: "#54B204" }]);
  const rows = m.rows();
  assert.ok(rows[1].kids.some((k) => k.tag === "span" && label(k) === "✓"), "(no tags) selected → its ✓");
  assert.ok(!rows[0].kids.some((k) => k.tag === "span" && label(k) === "✓"), "All not selected → no ✓");
  rows[0].handlers.click();
  assert.deepEqual(m.applies.at(-1), { lens: { all: true }, done: true }, "All applies as the exclusive pick and closes");
  m.close();
});

test("source pins: the tag rows build through the shared tagChip, the state is a class the two sheets define at the same opacity", () => {
  assert.match(LOOP, /const chip = tagChip\(u\.name, u\.color \|\| null, \{ off: !on \}\);/, "the pill every surface wears, faded when off");
  assert.match(LOOP, /chip\.setAttribute\("aria-pressed", on \? "true" : "false"\);/);
  assert.doesNotMatch(LOOP, /✓|--check-bg|border-radius:50%/, "no dot, no ✓ on the tag rows");
  assert.match(MENU, /export const TAG_CHIP_OFF_CLASS = "tag-chip-off";/);
  assert.match(MENU, /export const TAG_CHIP_OFF_OPACITY = "0\.45";/);
  for (const [name, sheet] of [["styles.css", CSS], ["feed.css", FEED_CSS]] as const)
    assert.match(sheet, /\n\.tag-chip-off \{ opacity: 0\.45; \}\n/, name + " defines the faded class at the inline value");
  // the ✓ grammar survives for All / (no tags) / the group switch: the row helper still paints it from the token
  assert.match(OPEN, /background:var\(--check-bg, #1EA1EB\)/);
  assert.match(OPEN, /row\("All", lensAll\(lens\)\)/); assert.match(OPEN, /row\("\(no tags\)", !lensAll\(lens\) && !!lens\.none\)/);
});
