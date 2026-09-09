// The settings gear's cached /models list follows the kernel's models frame — and is never overwritten by
// an OLDER response that lands late. BEHAVIORAL: the cache block of gear.js (`var choices` through the
// models listener) is lifted out and run against a fake window and a controllable fetch, so these pin
// what the code DOES. A pin that only matched the listener's text would prove nothing about the frame
// reaching the gear or the cache moving: the gear lives in the FEED bundle, and the kernel must send the
// frame there too (test_model_versions.py pins the kernel side).
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const GEAR = fs.readFileSync(path.resolve(process.cwd(), "..", "ui", "webview", "gear.js"), "utf8");
const tick = () => new Promise((r) => setImmediate(r));

// A <select> stand-in with the spec's value semantics the paint relies on: rewriting the options selects
// the FIRST one (the selectedness setting algorithm); assigning a value selects it only if an option
// carries it, else NOTHING — selectedIndex -1, value "" (a repaint that hands a held value straight back
// blanks the select when the new list lacks it); appendChild adds an option the way setShow's off-list
// injection does. `values` is the option values in order, for the assertions. Null selects (fillChoices
// guards each with `if (jm) …`) cannot show pickers left empty — nothing is there to be empty.
type Opt = { value: string; textContent: string };
type Sel = { innerHTML: string; value: string; options: Opt[]; values: string[]; appendChild(o: Opt): void };
function sel(): Sel {
  const s: any = { _html: "", _v: "" };
  const parse = (): Opt[] =>
    [...s._html.matchAll(/<option value="([^"]*)">([^<]*)<\/option>/g)].map((m) => ({ value: m[1], textContent: m[2] }));
  Object.defineProperty(s, "innerHTML", { get() { return s._html; }, set(h: string) { s._html = h; const o = parse(); s._v = o.length ? o[0].value : ""; } });
  Object.defineProperty(s, "options", { get: parse });
  Object.defineProperty(s, "values", { get() { return parse().map((o) => o.value); } });
  Object.defineProperty(s, "value", { get() { return s._v; }, set(v: string) { s._v = parse().some((o) => o.value === v) ? v : ""; } });
  s.appendChild = (o: Opt) => { s._html += '<option value="' + o.value + '">' + o.textContent + "</option>"; };
  return s as Sel;
}
// the one document call the block makes: setShow's injected <option>
const DOC = { createElement: (tag: string): Opt => { assert.equal(tag, "option"); return { value: "", textContent: "" }; } };
const SELECTS = ["jm", "im", "je", "ie", "jc", "dm", "de", "cmm", "cme"] as const;   // jc: the judge concurrency select (T277)

// The block, evaluated with the closure variables it reads passed in: `window` (the listener's target),
// `document` (the injected option), `fetch`/`ku` (the read), and the nine <select>s — real stand-ins by
// default, or null (the guards).
function lift(withSelects = true) {
  const start = GEAR.indexOf("  var choices = null");
  const at = GEAR.indexOf("m.type !== 'models'", start);
  const stop = GEAR.indexOf("\n  });\n", at) + "\n  });\n".length;
  assert.ok(start > 0 && at > start && stop > at, "anchors not found — the gear's models cache block moved; re-anchor");
  const src = GEAR.slice(start, stop);
  const listeners: Array<(e: any) => void> = [];
  const win = { addEventListener: (type: string, fn: (e: any) => void) => { if (type === "message") listeners.push(fn); } };
  const pending: Array<(d: any) => void> = [];        // one resolver per fetch, in request order
  const fetchStub = (url: string) => {
    assert.equal(url, "/models");
    return new Promise<any>((res) => pending.push((d: any) => res({ json: async () => d })));
  };
  const S: Record<(typeof SELECTS)[number], Sel | null> = Object.fromEntries(SELECTS.map((k) => [k, withSelects ? sel() : null])) as any;
  const fn = new Function("window", "document", "fetch", "ku", ...SELECTS,
    src + "\n  return { fillChoices: fillChoices, choices: function () { return choices; } };");
  const api = fn(win, DOC, fetchStub, (p: string) => p, ...SELECTS.map((k) => S[k]));
  const frame = (rev: number) => listeners.forEach((l) => l({ data: { type: "models", rev } }));
  return { api, listeners, pending, frame, S };
}
const list = (rev: number | undefined, def: string, versions: Array<{ value: string; label: string }> = []) =>
  ({ ...(rev === undefined ? {} : { rev }), models: [{ label: "Fable", value: "fable", default: def, versions }],
     efforts: [{ label: "High", value: "high" }] });

test("executed: the models frame re-reads /models and replaces the cache the family rows read at click time", async () => {
  const { api, listeners, pending, frame } = lift();
  assert.equal(listeners.length, 1, "the listener is registered on the window");
  const first = api.fillChoices();
  assert.equal(pending.length, 1, "the first fill fetches");
  pending[0](list(1, "claude-fable-5"));
  await first;
  assert.equal(api.choices().models[0].default, "claude-fable-5", "pinned");
  frame(2);                                              // the kernel: Latest un-pinned the family
  assert.equal(pending.length, 2, "the frame fetches again");
  pending[1](list(2, "fable"));
  await tick(); await tick();
  assert.equal(api.choices().models[0].default, "fable", "the next family click sends the alias");
  // a frame that names no type the gear knows, or an unrelated frame, fetches nothing
  listeners[0]({ data: { type: "palette" } });
  listeners[0]({ data: null });
  assert.equal(pending.length, 2);
});

test("executed: an OLDER /models response landing after a newer one is dropped — the newest rev applied wins", async () => {
  // the frame's re-read can overlap the first fill (or two quick frames each other), and the two responses
  // can resolve out of order: without the rev check the stale list overwrote the fresh one
  const { api, pending, frame } = lift();
  const first = api.fillChoices();                       // request 1, in flight
  frame(5);                                              // request 2
  assert.equal(pending.length, 2);
  pending[1](list(5, "fable"));                          // the newer answers first
  await tick(); await tick();
  assert.equal(api.choices().models[0].default, "fable");
  pending[0](list(4, "claude-fable-5"));                 // the older lands late
  await first; await tick();
  assert.equal(api.choices().models[0].default, "fable", "the stale first fill did not win");
  // and the same when two frames' reads cross
  frame(6); frame(7);
  pending[3](list(7, "claude-fable-5-1"));
  pending[2](list(6, "fable"));
  await tick(); await tick();
  assert.equal(api.choices().models[0].default, "claude-fable-5-1", "rev 7 applied; rev 6 dropped");
  assert.equal(api.choices().rev, 7);
});

test("a payload without a rev (an older kernel) always applies", async () => {
  const { api, pending, frame } = lift();
  const first = api.fillChoices();
  pending[0](list(3, "claude-fable-5"));
  await first;
  frame(4);
  pending[1](list(undefined, "fable"));
  await tick(); await tick();
  assert.equal(api.choices().models[0].default, "fable");
});

test("the guards still hold with no selects in the document", async () => {
  const { api, pending } = lift(false);
  const first = api.fillChoices();
  pending[0](list(1, "fable"));
  assert.equal((await first).models[0].default, "fable", "a fill with nothing to paint still returns the list");
});

test("executed: when the frame's re-read overtakes the page-load fill, every picker is still painted — from the list that won", async () => {
  // a page-load fill that returned early because the frame's re-read had already applied a newer list,
  // BEFORE writing any <option>s, left every later fill() short-circuiting on the cache — eight empty
  // pickers for the life of the page. The paint keys on the list, not on which fetch carried it.
  const V = [{ value: "claude-fable-5", label: "Fable 5" }];
  const { api, pending, frame, S } = lift();
  const first = api.fillChoices();                       // page load: request 1
  frame(6);                                              // a pick elsewhere during it: request 2
  pending[1](list(6, "fable", V));                       // request 2 resolves first
  await tick(); await tick();
  pending[0](list(5, "claude-fable-5", V));              // request 1 lands late, older
  await first; await tick();
  assert.equal(api.choices().models[0].default, "fable", "the newer list is the cache");
  for (const k of SELECTS) assert.ok(S[k]!.innerHTML.length > 0, `${k} is painted`);
  assert.deepEqual(S.jm!.values, ["fable", "claude-fable-5"], "family + version options, from the list that won");
  assert.deepEqual(S.je!.values, ["", "high"]);
  assert.deepEqual(S.jc!.values, ["", ...Array.from({ length: 16 }, (_, i) => String(i + 1))], "Default, then the kernel's whole 1..16 range (T277)");
  assert.deepEqual(S.dm!.values, ["triage", "fable", "claude-fable-5"], "the distilling sentinel leads");
  assert.deepEqual(S.de!.values, ["triage", "none", "high"]);
  assert.deepEqual(S.cmm!.values, ["session", "default", "fable", "claude-fable-5"], "the comment sentinels lead");
  assert.deepEqual(S.cme!.values, ["session", "high"]);
  // a later modal open (fill → fillChoices) is a cache hit and the pickers stay painted
  assert.equal((await api.fillChoices()).models[0].default, "fable");
  assert.equal(pending.length, 2, "no third fetch");
  S.jm!.value = "fable";
  assert.equal(S.jm!.value, "fable", "a pick can land on the painted options");
});

test("executed: a frame's repaint keeps the value each select held while the modal is up", async () => {
  // a rewrite resets a select to its first option, which is why a listener that only re-fetched could
  // not repaint; the paint gives every select its value back when the new list still offers it
  const V = [{ value: "claude-fable-5", label: "Fable 5" }];
  const { api, pending, frame, S } = lift();
  const first = api.fillChoices();
  pending[0](list(1, "claude-fable-5", V));
  await first;
  S.jm!.value = "claude-fable-5"; S.je!.value = "high"; S.dm!.value = "fable"; S.cme!.value = "session";
  frame(2);                                              // Latest un-pinned the family elsewhere; a session learned 5.1
  const V2 = V.concat([{ value: "claude-fable-5-1", label: "Fable 5.1" }]);
  pending[1](list(2, "fable", V2));
  await tick(); await tick();
  assert.equal(api.choices().models[0].default, "fable", "the cache moved");
  assert.deepEqual(S.jm!.values, ["fable", "claude-fable-5", "claude-fable-5-1"], "…and so did the options");
  assert.deepEqual(S.cmm!.values, ["session", "default", "fable", "claude-fable-5", "claude-fable-5-1"]);
  assert.equal(S.jm!.value, "claude-fable-5", "the pinned version the user had selected is still selected");
  assert.equal(S.je!.value, "high");
  assert.equal(S.dm!.value, "fable");
  assert.equal(S.cme!.value, "session");
  // a stale response repaints nothing (the list did not move), so a value is never disturbed for no reason
  const html = S.jm!.innerHTML;
  frame(3); frame(4);
  pending[3](list(4, "fable", V2));                      // the newer, same list
  pending[2](list(3, "claude-fable-5", V));              // the older, dropped
  await tick(); await tick();
  assert.equal(api.choices().rev, 4);
  assert.equal(S.jm!.innerHTML, html);
  assert.equal(S.jm!.value, "claude-fable-5");
});

test("executed: a repaint keeps a held value the new list LACKS — as a marked off-list option, never a blank select", async () => {
  // per the spec a select assigned a value none of its options carries deselects everything — value "",
  // the version menu's label read from it empty. So a stored value fill() had injected (the kernel's
  // truth, ahead of this page's list) or a learned version that has since left the list would go BLANK
  // on the next frame. The held value is re-injected the way fill() injects it: marked, selected, once.
  const V = [{ value: "claude-fable-5", label: "Fable 5" }, { value: "claude-fable-5-1", label: "Fable 5.1" }];
  const { api, pending, frame, S } = lift();
  const first = api.fillChoices();
  pending[0](list(1, "fable", V));
  await first;
  // fill(): the stored judge model is one this list lacks → setShow injected it, marked, and selected it
  S.jm!.appendChild({ value: "claude-fable-6", textContent: "claude-fable-6 — not in this kernel's list" });
  S.jm!.value = "claude-fable-6";
  S.im!.value = "claude-fable-5-1";                      // a learned version, picked
  S.je!.value = "high";
  frame(2);
  pending[1](list(2, "fable", V.slice(0, 1)));           // the learned 5.1 left the list
  await tick(); await tick();
  assert.equal(S.jm!.value, "claude-fable-6", "the stored value the kernel holds is still selected");
  assert.deepEqual(S.jm!.values, ["fable", "claude-fable-5", "claude-fable-6"], "…re-injected after the rewrite, last");
  assert.match(S.jm!.options[2].textContent, /not in this kernel's list/, "…and marked as off-list");
  assert.equal(S.im!.value, "claude-fable-5-1", "so is the version that left the list");
  assert.deepEqual(S.im!.values, ["fable", "claude-fable-5", "claude-fable-5-1"]);
  assert.equal(S.je!.value, "high", "an in-list value is given back plainly");
  assert.deepEqual(S.je!.values, ["", "high"], "nothing injected for it");
  // the next repaint injects the off-list value once more — never a second copy
  frame(3);
  pending[2](list(3, "fable", V.slice(0, 1)));
  await tick(); await tick();
  assert.deepEqual(S.jm!.values, ["fable", "claude-fable-5", "claude-fable-6"]);
  assert.equal(S.jm!.value, "claude-fable-6");
  // a select nobody has picked on holds its first option; a repaint leaves it there, injecting nothing
  assert.equal(S.dm!.value, "triage");
  assert.deepEqual(S.dm!.values, ["triage", "fable", "claude-fable-5"]);
});
