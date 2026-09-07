// Every webview surface that can carry a link the HOST must open — the timeline's deep links, and the
// PR links pr-links.ts writes into feed cards and outline rows (2026-09-06) — posts {type:"openLink"}
// in VS Code, where a webview cannot open a browser itself. view-routing.ts routes it host-side for
// every pane (view-routing.test.ts pins the pure router); THIS pins the other half, the host's
// consumption of that verdict: each panel's onDidReceiveMessage must act on `openLinkLocally` and
// honor `forward`. The router alone was pinned once, and the feed and outline panels forwarded the
// message to a kernel with no handler for it — a dead click, invisible to every test.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

const SRC = fs.readFileSync(path.join(process.cwd(), "src", "extension.ts"), "utf8");

/** the handler text that follows each `const r = routeViewMessage(...)` up to its pipe.send */
function routedBlocks(): { app: string; body: string }[] {
  const out: { app: string; body: string }[] = [];
  const re = /const r = routeViewMessage\(([^,]+), m\);([\s\S]*?)pipe\.send\(m\);/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(SRC))) out.push({ app: m[1].trim(), body: m[2] });
  return out;
}

test("every panel routed through view-routing opens a host-side link and drops the message from the kernel pipe", () => {
  const blocks = routedBlocks();
  const apps = blocks.map((b) => b.app).sort();
  assert.deepEqual(apps, ['"chat"', '"feed"', '"fleet"', "app"], "the chat, feed and outline panels, and the sidebar views (timeline/fleet)");
  for (const b of blocks) {
    if (b.app === '"chat"') continue;   // the chat panel opens links BEFORE routing (pinned below)
    assert.match(b.body, /if \(r\.openLinkLocally\) openLink\(r\.openLinkLocally\);/, b.app + ": the host opens the link");
    assert.match(b.body, /if \(r\.forward\) $/, b.app + ": a locally handled message is not also forwarded (forward:false)");
  }
});

test("the chat panel handles openLink itself, ahead of the router", () => {
  const chat = SRC.slice(SRC.indexOf("function wirePanel("), SRC.indexOf('const r = routeViewMessage("chat", m);'));
  assert.match(chat, /if \(m\.type === "openLink" && typeof m\.href === "string"\) \{ openLink\(String\(m\.href\)\); return; \}/);
});

test("openLink sends a normal URL to the OS browser and feeds the extension's own deep links to its URI handler", () => {
  const fn = SRC.match(/function openLink\(href: string\) \{[\s\S]*?\n\}/)?.[0] || "";
  assert.match(fn, /vscode\.Uri\.parse\(href, true\)/);
  assert.match(fn, /uri\.scheme === "vscode" && uri\.authority\.toLowerCase\(\) === "romp\.romp-chat-view"/);
  assert.match(fn, /vscode\.env\.openExternal\(uri\);/);
});
