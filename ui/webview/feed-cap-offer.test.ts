// The cap-death billing-switch OFFER (the user's binding ruling, 2026-08-30: a session must NEVER
// silently switch billing in either direction). The kernel mints capOffer only for a login-billed
// session dead on the account's cap with a key on hand (tests/test_cap_switch_offer.py holds that
// matrix + the set_auth caller census); these pins hold the render half: the tradeoff stated
// plainly and visibly, the button's click-safety + latched ack, declining = the existing Clear,
// and the gesture census — the ONE setAuth postMessage in the feed is this button.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const UI = path.resolve(process.cwd(), "..", "ui", "webview");
const FEED = fs.readFileSync(path.join(UI, "feed.ts"), "utf8");
const RENDER = fs.readFileSync(path.join(UI, "render.ts"), "utf8");
const KERNEL = fs.readFileSync(path.resolve(process.cwd(), "..", "kernel", "kernel.py"), "utf8");

test("the offer states the tradeoff plainly and visibly — never tooltip-only", () => {
  assert.match(FEED, /This session bills the subscription, whose usage window is full — it can "\s*\n\s*\+ "bill your API key instead until the window resets at " \+ clockHM\(cap\.resetsAt\)/);
  assert.match(FEED, /"\. It switches back only if you switch it\."/, "the reverse direction named, per the ruling");
});

test("the button acknowledges, latches across pushes, and self-resolves — the T150 idiom", () => {
  assert.match(FEED, /a\._capBtn\.disabled = true; a\._capBtn\.textContent = "Switching…";   \/\/ ack before the round-trip/);
  assert.match(FEED, /if \(!\(a\._capBtn as HTMLButtonElement\)\.disabled\) \{/,
    "a push while the switch applies must not re-arm the button under the user");
  assert.match(FEED, /\} else \{ \(a\._capBtn as HTMLButtonElement\)\.disabled = false; a\._capBtn\.textContent = "Switch to the key"; \}/,
    "the offer vanishing (switch landed, or window reset) is what re-arms");
  assert.match(FEED, /const capBtn = el\("button", "fdismiss fcapswitch"\)/, "build-once on the card skeleton — click-safe");
});

test("only the explicit pick switches — the gesture census, both surfaces", () => {
  // the feed's ONE setAuth send is this button; the chat gear's ONE is the billing selector.
  // Any new sender shows up as a count change here before it ships.
  assert.equal((FEED.match(/type: "setAuth"/g) || []).length, 1, "feed: the offer button only");
  assert.equal((RENDER.match(/type: "setAuth"/g) || []).length, 1, "chat: the gear billing pick only");
  assert.match(KERNEL, /a session must NEVER\s*\n\s*silently switch billing in either direction/, "the ruling, verbatim at the mint");
});

test("the offer retires with the window and rides beside the auto-retry, never instead", () => {
  assert.match(KERNEL, /\(w\.get\("resets_at"\) or 0\) > now/, "resets_at passing ends the mint — the deciding event");
  assert.match(KERNEL, /_cap_off = _cap_switch_offer\(fsid, aerr\) if aerr else None/);
  assert.match(KERNEL, /\*\*\(\{"capOffer": _cap_off\} if _cap_off else \{\}\),/, "sparse — absent payloads are byte-identical");
  // the auto-retry contract is untouched: the retry button (a manual retry, as the chat pane sends) + auto ladder stay
  assert.match(FEED, /vscodeApi\?\.postMessage\(\{ type: "apiRetry", id: it\.sid, manual: true \}\);/);
});
