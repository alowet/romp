// The VS Code timeline surface's entry point: bundles the shared TimelinePanel
// (ui/romp-timeline-view.js — the SAME file the kernel injects into /timeline)
// together with the boot glue, into dist/timeline.js for the rompTimeline
// webview view. The extension host holds the kernel WebSocket (app=timeline)
// and relays frames via postMessage, exactly like chat/feed.
import { installDomHelpers, dispatchFrame, bridgeFunctions } from "./timeline-boot";
import { installSettingsSync, loadSettings, onExternalSettingsChange } from "./settings";
import { applyTheme } from "./theme";
import { perfFrameHandler } from "./perf-telemetry";
import { listenForFrames } from "./frame-listener";

// CJS view module — esbuild inlines it into this bundle at build time.
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { TimelinePanel } = require("../romp-timeline-view.js");

const api = (window as any).acquireVsCodeApi();
const post = (m: Record<string, unknown>) => api.postMessage(m);

installDomHelpers(HTMLElement.prototype);
Object.assign(window, bridgeFunctions(post));
// Usage bars belong to the host's chrome (here: the status-bar item's menu),
// not the pane — the view hands the /usage payload to the host and keeps its
// own toolbar copy hidden, like it does for the web shell's rail.
(window as any).__rompForwardUsage = (usage: unknown) => post({ type: "usageData", usage });

let panel: any = null;
// wrapped through the pane's performance collector like every pane's listener (ui/webview/perf-telemetry.ts):
// each frame's handling is timed by type, and the kernel page's inline boot twin does the same
// …and installed through the same helper as every pane (frame-listener.ts): there is no federation.js in a VS Code
// webview, so only the window listener is installed here; the kernel page's inline boot twin registers with it
listenForFrames(perfFrameHandler("timeline", post, (ev: MessageEvent) => { dispatchFrame(panel, ev.data); }));

// the overall theme (2026-08-28): body classes at boot + on settings writes, like every pane
installSettingsSync();
applyTheme(document, loadSettings());
onExternalSettingsChange((s) => applyTheme(document, s));

panel = new TimelinePanel(document.getElementById("host"));
post({ type: "ready" }); // ask the kernel to push the initial lanes (like chat/feed/fleet)
