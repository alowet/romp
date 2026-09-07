// The URL viewer's capped body read, EXECUTED against synthetic streams (the review of 2026-09-06:
// r.text() buffered the whole body, a closed modal did not cancel the read, and .length counted UTF-16
// code units instead of bytes). ReadableStream / TextDecoder / AbortController are Node globals, so
// these run the real reader. Fixtures are invented bytes; nothing here is recorded data.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import { readTextCapped, humanSize, overCapWords, settleUrlResponse } from "./capped-read";

const enc = new TextEncoder();

// A source that hands out `chunks` one per pull, recording how many were pulled and whether the
// consumer cancelled it. `gate` (optional) holds the pull AFTER `holdAt` chunks until released — the
// shape of a body still arriving from the network.
function source(chunks: Uint8Array[], opts: { holdAt?: number } = {}) {
  // pullsStarted: how many times the stream asked the source for a chunk; pulled: chunks handed out
  const state = { pullsStarted: 0, pulled: 0, cancelled: false, release: () => { /* set below when a gate exists */ } };
  const gate = opts.holdAt === undefined ? null : new Promise<void>((res) => { state.release = res; });
  const stream = new ReadableStream<Uint8Array>({
    async pull(controller) {
      state.pullsStarted++;
      if (gate && state.pulled === opts.holdAt) await gate;
      if (state.cancelled) return;                       // a well-behaved source stops once cancelled
      if (state.pulled >= chunks.length) { controller.close(); return; }
      controller.enqueue(chunks[state.pulled++]);
    },
    cancel() { state.cancelled = true; },
  }, { highWaterMark: 0 });        // no read-ahead: a pull happens only when the reader asks
  return { stream, state };
}

test("a body of exactly the cap is accepted, in full, with its byte count", async () => {
  const { stream, state } = source([enc.encode("12345"), enc.encode("67890")]);
  const got = await readTextCapped(stream, 10);
  assert.deepEqual(got, { text: "1234567890", bytes: 10 });
  assert.equal(state.cancelled, false, "a body within the cap is never cancelled");
  assert.equal(state.pulled, 2);
});

test("a body over the cap is refused after at most ONE chunk past it, and the source is cancelled", async () => {
  const six = enc.encode("abcdef");
  const { stream, state } = source([six, six, six, six, six]);
  const got = await readTextCapped(stream, 10);
  assert.ok("tooLarge" in got, "refused");
  assert.equal(got.bytesSeen, 12, "the running total the moment it passed the cap — one chunk past, not the whole body");
  assert.equal(state.cancelled, true, "the source was cancelled");
  assert.ok(state.pulled < 5, "the rest of the body was never pulled (" + state.pulled + " of 5 chunks)");
});

test("a multi-byte UTF-8 body split mid-codepoint across chunks decodes correctly under the cap", async () => {
  const whole = enc.encode("héllo — €uro ✓");            // 2-, 3- and 3-byte sequences
  // split INSIDE the euro sign (E2 82 AC): find it and cut after its first byte
  const at = whole.indexOf(0xe2) + 1;
  const { stream } = source([whole.slice(0, at), whole.slice(at, at + 1), whole.slice(at + 1)]);
  const got = await readTextCapped(stream, 1024);
  assert.deepEqual(got, { text: "héllo — €uro ✓", bytes: whole.byteLength });
});

test("the cap is BYTES, not code units: a body of few characters but many bytes is refused", async () => {
  // 8 code units of 3 bytes each = 24 bytes; a code-unit count would have accepted it under a cap of 20
  const { stream, state } = source([enc.encode("€€€€"), enc.encode("€€€€")]);
  const got = await readTextCapped(stream, 20);
  assert.ok("tooLarge" in got && got.bytesSeen === 24);
  assert.equal(state.cancelled, true);
});

test("an already-aborted signal rejects with an AbortError and cancels the source without reading", async () => {
  const ac = new AbortController();
  ac.abort();
  const { stream, state } = source([enc.encode("never"), enc.encode("read")]);
  await assert.rejects(readTextCapped(stream, 100, ac.signal), (e: Error) => e.name === "AbortError");
  assert.equal(state.cancelled, true);
  assert.equal(state.pulled, 0, "not one chunk consumed");
});

test("an abort MID-BODY rejects with an AbortError, cancels the source, and pulls nothing further", async () => {
  const ac = new AbortController();
  const { stream, state } = source([enc.encode("first"), enc.encode("second"), enc.encode("third")], { holdAt: 1 });
  const pending = readTextCapped(stream, 100, ac.signal);
  await new Promise((r) => setTimeout(r, 10));            // the reader has taken "first" and is waiting on the gate
  assert.equal(state.pulled, 1);
  assert.equal(state.pullsStarted, 2, "the second pull is in flight, held by the gate");
  ac.abort();                                              // the viewer was closed
  await assert.rejects(pending, (e: Error) => e.name === "AbortError", "never resolves with a torso");
  assert.equal(state.cancelled, true, "the source was cancelled — the network read stops");
  state.release();                                         // let the held pull settle; it must deliver nothing
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(state.pulled, 1, "the held pull handed out nothing after the cancel");
  assert.equal(state.pullsStarted, 2, "and the stream never asked the source for another chunk");
});

test("an empty body is accepted as empty text", async () => {
  const { stream } = source([]);
  assert.deepEqual(await readTextCapped(stream, 10), { text: "", bytes: 0 });
});

// ── the refusal's words: base-1024 like the cap itself, and never an equal-looking pair ──

const CAP = 2 * 1024 * 1024;

test("humanSize is base-1024 with a trailing .0 dropped, so the 2 MiB cap reads '2 MB'", () => {
  assert.equal(humanSize(CAP), "2 MB");
  assert.equal(humanSize(1024 * 1024), "1 MB");
  assert.equal(humanSize(2.5 * 1024 * 1024), "2.5 MB");
  assert.equal(humanSize(3_000_000), "2.9 MB", "3,000,000 bytes is 2.86 MiB");
  assert.equal(humanSize(1536), "2 KB", "whole kilobytes below a megabyte");
  assert.equal(humanSize(12), "1 KB", "never '0 KB'");
});

test("overCapWords: a KNOWN size names it against the limit; a size that would read equal is spelled in bytes", () => {
  assert.equal(overCapWords(3_000_000, CAP), "this document is 2.9 MB, over the 2 MB limit");
  assert.equal(overCapWords(10 * 1024 * 1024, CAP), "this document is 10 MB, over the 2 MB limit");
  // the cosmetic bug: 2,097,252 bytes rounds to the same words as the cap
  assert.equal(overCapWords(2_097_252, CAP), "this document is 2,097,252 bytes, over the 2 MB limit");
  // sweep the whole collision band: no pair of equal-looking words anywhere past the cap
  for (let n = CAP + 1; n < CAP + 60_000; n += 997) {
    const words = overCapWords(n, CAP);
    assert.doesNotMatch(words, /is 2 MB, over the 2 MB/, words);
  }
});

test("overCapWords: the streaming refusal names no measured size — the true size was never read", () => {
  assert.equal(overCapWords(null, CAP), "this document is over 2 MB — too large to show here");
});

// ── settleUrlResponse: the pre-read decision, and the transfer STOPS on every refusal ──
// A refused response used to paint its words and return while the body kept downloading for a modal
// already closed (measured live: received bytes kept climbing after the close). The verdict helper
// fires `stop` — the open's AbortController.abort — on every verdict that will not read the body.

function resp(over: { ok?: boolean; status?: number; headers?: Record<string, string>; body?: ReadableStream<Uint8Array> | null | "stream" }) {
  const h = new Map(Object.entries(over.headers || {}).map(([k, v]) => [k.toLowerCase(), v]));
  const body = over.body === "stream" || over.body === undefined ? source([enc.encode("# doc\n")]).stream : over.body;
  return { ok: over.ok ?? true, status: over.status ?? 200, headers: { get: (n: string) => h.get(n.toLowerCase()) ?? null }, body };
}
// a `stop` that behaves like the real one: aborting the controller also cancels the response body
function stopper(body: ReadableStream<Uint8Array> | null) {
  const ac = new AbortController();
  const calls = { n: 0 };
  return { ac, calls, stop: () => { calls.n++; ac.abort(); if (body) void body.cancel().catch(() => {}); } };
}

test("settleUrlResponse: a non-OK status → http verdict, and the transfer is stopped", () => {
  const { stream, state } = source([enc.encode("nope")]);
  const r = resp({ ok: false, status: 404, body: stream });
  const s = stopper(r.body);
  assert.deepEqual(settleUrlResponse(r, CAP, s.stop), { kind: "http", status: 404 });
  assert.equal(s.calls.n, 1, "stop fired exactly once");
  assert.equal(s.ac.signal.aborted, true, "the controller is aborted");
  return new Promise<void>((done) => setTimeout(() => { assert.equal(state.cancelled, true, "…and the body's source was cancelled"); done(); }, 5));
});

test("settleUrlResponse: a declared Content-Length past the cap → declared-too-large with the number, transfer stopped", () => {
  const { stream, state } = source([enc.encode("x")]);
  const r = resp({ headers: { "Content-Length": String(CAP + 1) }, body: stream });
  const s = stopper(r.body);
  assert.deepEqual(settleUrlResponse(r, CAP, s.stop), { kind: "declared-too-large", bytes: CAP + 1 });
  assert.equal(s.calls.n, 1);
  assert.equal(s.ac.signal.aborted, true);
  return new Promise<void>((done) => setTimeout(() => { assert.equal(state.cancelled, true); done(); }, 5));
});

test("settleUrlResponse: no body stream → no-body, stop still fires (symmetry: every non-read verdict aborts)", () => {
  const r = resp({ body: null });
  const s = stopper(null);
  assert.deepEqual(settleUrlResponse(r, CAP, s.stop), { kind: "no-body" });
  assert.equal(s.calls.n, 1);
  assert.equal(s.ac.signal.aborted, true);
});

test("settleUrlResponse: an OK response with a body under (or without) a declared length → read, and stop NEVER fires", () => {
  const cases: Record<string, string>[] = [{}, { "Content-Length": String(CAP) }, { "Content-Length": "12" }, { "Content-Length": "not-a-number" }, { "content-length": "0" }];
  for (const headers of cases) {
    const r = resp({ headers });
    const s = stopper(r.body);
    assert.deepEqual(settleUrlResponse(r, CAP, s.stop), { kind: "read" }, JSON.stringify(headers));
    assert.equal(s.calls.n, 0, "the body is about to be read — nothing is stopped: " + JSON.stringify(headers));
    assert.equal(s.ac.signal.aborted, false);
  }
});

test("settleUrlResponse: the order is status, then declared length, then body — a 404 with a huge Content-Length is an http verdict", () => {
  const r = resp({ ok: false, status: 500, headers: { "Content-Length": String(10 * CAP) }, body: null });
  const s = stopper(null);
  assert.deepEqual(settleUrlResponse(r, CAP, s.stop), { kind: "http", status: 500 });
  assert.equal(s.calls.n, 1, "stopped once, not once per reason");
});

// ── a 200 that is a WEB PAGE, not the document (review find on #958, 2026-09-07) ──
// A proxy's SPA fallback or an auth page answers a missing/gated .md with 200 text/html; rendering that
// as the document showed a scrambled page under the document's name with no error.

test("settleUrlResponse: a 200 labelled text/html → not-document with the bare type, transfer stopped", () => {
  const { stream, state } = source([enc.encode("<!doctype html><html>app shell</html>")]);
  const r = resp({ headers: { "Content-Type": "text/html; charset=utf-8" }, body: stream });
  const s = stopper(r.body);
  assert.deepEqual(settleUrlResponse(r, CAP, s.stop), { kind: "not-document", type: "text/html" });
  assert.equal(s.calls.n, 1, "stop fired exactly once");
  assert.equal(s.ac.signal.aborted, true);
  return new Promise<void>((done) => setTimeout(() => { assert.equal(state.cancelled, true, "the page's bytes are not downloaded"); done(); }, 5));
});

test("settleUrlResponse: only text/html is refused — markdown, plain text, octet-stream and an ABSENT type all read", () => {
  for (const type of ["text/markdown", "text/plain; charset=utf-8", "application/octet-stream", "text/x-markdown", null]) {
    const r = resp({ headers: type === null ? {} : { "Content-Type": type }, body: source([enc.encode("# doc")]).stream });
    const s = stopper(r.body);
    assert.deepEqual(settleUrlResponse(r, CAP, s.stop), { kind: "read" }, String(type));
    assert.equal(s.calls.n, 0, "read never stops the transfer: " + String(type));
  }
});

test("settleUrlResponse: a non-OK text/html answer is still the http verdict (the status is the news)", () => {
  const r = resp({ ok: false, status: 404, headers: { "Content-Type": "text/html" }, body: source([enc.encode("<h1>404</h1>")]).stream });
  const s = stopper(r.body);
  assert.deepEqual(settleUrlResponse(r, CAP, s.stop), { kind: "http", status: 404 });
});
