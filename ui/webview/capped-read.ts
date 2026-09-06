// Reading a URL document's body under a byte cap, INCREMENTALLY (the URL viewer's review, 2026-09-06).
// The first cut called r.text() and measured afterwards, which was wrong three ways: the whole body was
// buffered before any check whenever Content-Length was absent (or described compressed bytes), a
// closed modal did not stop the read, and `.length` counts UTF-16 code units rather than bytes — a
// 2.4 MB UTF-8 document of 0.8 M code units slipped under a 2 MB cap. This reader pulls the stream
// chunk by chunk, counts the BYTES as they arrive, cancels the source the moment the running total
// passes the cap (so at most one chunk past it is ever pulled), decodes with a streaming TextDecoder so
// a multi-byte codepoint split across two chunks decodes correctly, and stops on an AbortSignal. Pure:
// ReadableStream, TextDecoder and DOMException are globals in the browser and in Node ≥ 18 alike, so
// it executes under `node --test` (capped-read.test.ts) instead of being pinned.

export type CappedRead = { text: string; bytes: number } | { tooLarge: true; bytesSeen: number };

function abortError(): Error {
  return typeof DOMException !== "undefined"
    ? new DOMException("the read was aborted", "AbortError")
    : Object.assign(new Error("the read was aborted"), { name: "AbortError" });
}

/** Read `stream` as UTF-8 text while its byte count stays ≤ `cap`. Resolves `{ text, bytes }` for a body
 *  within the cap, `{ tooLarge, bytesSeen }` once the bytes read exceed it (the source is cancelled at
 *  that moment — the rest is never pulled), and REJECTS with an AbortError when `signal` fires (the
 *  source is cancelled then too, so a torn-down viewer keeps pulling nothing). */
export async function readTextCapped(stream: ReadableStream<Uint8Array>, cap: number, signal?: AbortSignal): Promise<CappedRead> {
  const reader = stream.getReader();
  const cancel = () => reader.cancel().catch(() => { /* already settled */ });
  if (signal?.aborted) { await cancel(); throw abortError(); }
  // The abort cancels the SOURCE, not just this loop: a pending read() settles as done and no further
  // chunk is pulled — the loop then notices the signal and rejects rather than returning a torso.
  const onAbort = () => { void cancel(); };
  signal?.addEventListener("abort", onAbort, { once: true });
  const decoder = new TextDecoder("utf-8");
  let seen = 0;
  let text = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (signal?.aborted) throw abortError();
      if (done) break;
      seen += value.byteLength;
      if (seen > cap) {
        await cancel();
        return { tooLarge: true, bytesSeen: seen };
      }
      text += decoder.decode(value, { stream: true });
    }
    text += decoder.decode();                          // flush a trailing partial sequence (as U+FFFD)
    return { text, bytes: seen };
  } finally {
    signal?.removeEventListener("abort", onAbort);
  }
}

/** Base-1024, the unit the cap is set in (2 * 1024 * 1024 IS 2 MB here): a trailing ".0" is dropped
 *  so the cap reads "2 MB", and anything under a megabyte is whole kilobytes. */
export function humanSize(n: number): string {
  if (n >= 1024 * 1024) return (n / (1024 * 1024)).toFixed(1).replace(/\.0$/, "") + " MB";
  return Math.max(1, Math.round(n / 1024)) + " KB";
}

function withCommas(n: number): string {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** The refusal's words. `bytes` is the size when it is KNOWN (a Content-Length the server declared);
 *  null when the streaming reader tripped the cap mid-body — the true size was never measured, and
 *  naming one would claim it. A known size that rounds to the same words as the cap ("2.1 MB … 2.1 MB",
 *  the cosmetic bug) is spelled out in bytes instead, so the pair never reads as equal. */
export function overCapWords(bytes: number | null, cap: number): string {
  const limit = humanSize(cap);
  if (bytes === null) return "this document is over " + limit + " — too large to show here";
  const size = humanSize(bytes);
  const shown = size === limit ? withCommas(bytes) + " bytes" : size;
  return "this document is " + shown + ", over the " + limit + " limit";
}
