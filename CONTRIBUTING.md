# Contributing

Thanks for looking at Romp.

This is a personal side project. Bug reports and pull requests are
welcome, and I'd rather hear about a problem than not. Responses may be slow, and
I may not get to everything. 

If you're interested in reporting bugs and making PRs, please try to reproduce them or ground your suggestions with the latest code at the tip of the main branch rather than a tagged release version.

## Running the tests

```bash
python3 -m pytest -q       # the Python pipeline (kernel/, cli/, postal/)
bats tests/*.bats          # the shell surfaces (hooks, postal, manager)
cd vscode-extension && npm ci && npm test
```

The Python and shell suites are also the CI gate, across Python 3.10 to 3.13 on
Linux; the macOS cells run on demand from the Actions tab (they are billed even
on a public repo, so they are not part of the per-push matrix).

Three things about the test environment are worth knowing, because all have
produced confusing failures:

- The bats suite takes about a minute on Linux and about fifteen on macOS. That
  is expected, not a hang.
- Some tests behave differently depending on whether a `tmux` binary exists on
  the machine, because romp treats "no tmux at all" as headless and falls back
  to file-derived sessions. Tests that care now pin this explicitly; if you add
  one that calls into session liveness, pin it too rather than inheriting the
  machine's state.
- On macOS, run the bats suite with a modern bash (`brew install bash`; bats
  picks it up via `env bash` when `/opt/homebrew/bin` precedes `/bin` on PATH).
  The stock `/bin/bash` 3.2 does not fail a test on a mid-test `[[ ]]`
  assertion — only the last command's status counts — so a stale assertion can
  pass silently for months. Linux CI runs bash 5 and is the arbiter; two
  assertions went stale exactly this way while CI was offline.

## A message listener from another world clones every frame it can see

The pane pages receive the kernel's frames as `message` events on `window`.
Blink hands a listener in the page's own JavaScript world the event's data
object itself, but a listener in another world, a browser extension's content
script, that reads `event.data` receives a structured clone of the whole
object, made synchronously inside the dispatch: 35-46 ms and about 7 MB of
garbage per dispatch of a 7 MB frame in a Chromium probe, against 0 ms for a
direct call. The live `romp perf client` rows show it as a `fed:<type>` share
far above federation's own compute (about 1 ms per frame).

`federation.js` therefore hands its merged frames (`feed`, `tabOrder`, `data`,
`bars`) to the pane's handler by direct call (`window.__rompFed.onFrame`,
through `ui/webview/frame-listener.ts`) and dispatches them on `window` only
when nothing registered. Every other frame still arrives as a `window` event,
so a foreign listener still sees those, and a new frame type that grows large
should go through the registry too.

To check a browser for such a listener before or after a deploy: open DevTools
on the dashboard, pick the feed iframe in the console's context selector, and
time a dispatch of a large frame:

```js
const big = Array.from({ length: 150000 }, (_, i) => ({ i, s: "x" }));
const t = performance.now();
window.dispatchEvent(new MessageEvent("message", { data: big }));
performance.now() - t
```

Under a millisecond means no foreign reader: only same-world listeners saw the
event. Tens of milliseconds means a listener in another world read
`event.data` and paid for the clone. This timing is the detection step.
`getEventListeners(window).message` cannot be, because it is per-world: it
lists only the listeners registered from the world whose context the console
is running in, so in the page's own context it shows romp's listeners and
nothing else, whether or not a content script is present. To see a content
script's listener, switch the console's context selector to that extension's
context (listed under the frame by extension name) and run the enumeration
there. Every romp listener on a kernel pane page comes from that page's pane
bundle (`feed.js` on the feed page, `render.js` on the chat, and so on; the
kernel-served timeline's is its inline boot; under a dev build with source
maps DevTools may show the source file names), and any other URL, in
particular a `chrome-extension://` one, is the foreign listener. With no
foreign listener present, a large `fed:<type>` share in the live rows is not
the clone and needs another explanation before anything is built on this one.
