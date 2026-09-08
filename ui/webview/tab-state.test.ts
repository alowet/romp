// tab-state.ts: the tab strip's ONE state → class rule, shared by the tab and a folded section
// header's summary pip (tab groups, 2026-09-04). The header once classed every "blocked" member red
// while the tab rendered a transient, auto-retrying API error amber — a folded group showed "waiting
// on you" over a tab that needed nothing (a false interrupt). Executed on the pure module; the render.ts
// call sites are pinned in tab-groups.test.ts. Synthetic statuses only.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import { tabStateClass, sectionPip, SECTION_PIP_TITLE } from "./tab-state";

test("executed: tabStateClass — the strip's rule, on-you blocks red, transient API errors amber", () => {
  assert.equal(tabStateClass({ state: "working" }), "tab-working");
  assert.equal(tabStateClass({ state: "blocked" }), "tab-retrying", "a transient API error auto-retries: amber, not red");
  assert.equal(tabStateClass({ state: "blocked", apiTooLong: true }), "tab-blocked");
  assert.equal(tabStateClass({ state: "blocked", apiSpendLimit: true }), "tab-blocked");
  assert.equal(tabStateClass({ state: "blocked", apiModelLimit: true }), "tab-blocked");
  assert.equal(tabStateClass({ state: "blocked", apiAuthErr: true }), "tab-blocked");
  assert.equal(tabStateClass({ state: "blocked", apiRefusal: true }), "tab-blocked");
  assert.equal(tabStateClass({ state: "needsInput" }), "tab-awaiting");
  assert.equal(tabStateClass({ state: "awaiting" }), "tab-awaiting", "the legacy name an older remote kernel sends");
  assert.equal(tabStateClass({ state: "retrying" }), "tab-retrying");
  assert.equal(tabStateClass({ state: "compacting" }), "tab-compacting");
  assert.equal(tabStateClass({ state: "clearing" }), "tab-compacting");
  assert.equal(tabStateClass({ state: "closed" }), "tab-closed");
  assert.equal(tabStateClass({ state: "ready" }), "", "no tab treatment → no class");
  assert.equal(tabStateClass(undefined), "");
});

test("executed: sectionPip — a folded header's pip is red ONLY for a member the tab itself renders red", () => {
  // the finding: a transient auto-retrying API error (state blocked, no on-you flag) turned the
  // header pip red — "blocked or waiting on you" — over an amber tab
  assert.equal(sectionPip([{ state: "ready" }, { state: "blocked" }]), "retrying", "the tab is amber, so is the pip");
  assert.equal(sectionPip([{ state: "ready" }, { state: "blocked", apiTooLong: true }]), "blocked", "on you → red");
  assert.equal(sectionPip([{ state: "working" }, { state: "needsInput" }]), "blocked", "waiting on you outranks working");
  assert.equal(sectionPip([{ state: "working" }, { state: "blocked" }]), "working", "progress outranks a stall that is not on you");
  assert.equal(sectionPip([{ state: "ready" }, { state: "working" }]), "working");
  assert.equal(sectionPip([{ state: "ready" }, undefined, { state: "closed" }]), null, "nothing happening → no pip");
  assert.equal(sectionPip([]), null);
  assert.match(SECTION_PIP_TITLE.blocked, /waiting on you/);
  assert.match(SECTION_PIP_TITLE.retrying, /retrying on its own/);
  assert.match(SECTION_PIP_TITLE.working, /working/);
});
