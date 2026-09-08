// A pane's one frame listener, installed on both delivery paths.
//
// Every pane handles the frames it receives in ONE window "message" handler: the kernel's frames (through the
// shim and federation.js on a kernel page, the extension host's pipe in VS Code) and the shell's `romp:` posts.
// federation.js emits its MERGED frames (`feed`, `tabOrder`, `data`, `bars`) by direct call to the handlers
// registered with it and dispatches on window only when none is registered (federation.ts emit): a "message"
// listener in another JavaScript world (a browser extension's content script) that reads event.data forces a
// structured clone of the frame on every window dispatch, tens of milliseconds for a large board. So the pane
// installs the SAME handler on window and in the registry; federation picks one path per frame, so each frame
// arrives exactly once, and the perf brackets (perf-telemetry.ts) nest the same way on either path.
//
// Kept import-free: federation.ts must never be imported by a pane bundle (federation-single-instance.test.ts),
// so the registry is reached through the window slot federation.js publishes before the bundle loads. Without
// the slot (a VS Code webview, an older federation.js) the window listener carries every frame, as before.

/** Install `handler` as the pane's frame listener on window and, when the page's federation manager is present,
 *  in its direct-delivery registry. Returns the handler. */
export function listenForFrames(handler: (e: MessageEvent) => void): (e: MessageEvent) => void {
  window.addEventListener("message", handler);
  // no registry on this page (a VS Code webview, an older federation.js): the window path carries every frame
  const fed = (window as any).__rompFed;
  if (fed && typeof fed.onFrame === "function") fed.onFrame(handler);
  return handler;
}
