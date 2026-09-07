// The drain gate's silent-degradation risk: were kernelToken() to swallow a
// token-read failure into '' with zero log, or fetchBusy to parse only `.busy` out of the kernel's
// response, DISCARDING the `draining` field — the kernel's own refusal signal — a parked deploy
// would believe new turn starts were held while the kernel armed nothing; busy never quiets, and
// the 15-minute backstop SIGTERMs the kernel MID-TURN with no line anywhere naming the cause.
// The degrade BEHAVIOR is deliberate (count-only polling keeps working; the /busy read
// arm needs no token) — these tests pin that the degradation is VISIBLE, once per park.
// Run: node --test tests/manager-drain.test.js
'use strict';
const { test, before, after, beforeEach } = require('node:test');
const assert = require('node:assert');
const http = require('node:http');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

// STATE_ROOT bakes from env when the manager module loads — point it at a temp dir BEFORE the
// require (this file runs in its own process under node --test, so no other suite is disturbed).
const STATE = fs.mkdtempSync(path.join(os.tmpdir(), 'romp-mgr-drain-'));
process.env.ROMP_STATE_DIR = STATE;
delete process.env.ROMP_SERVE_TOKEN;
delete process.env.ROMP_SUPERVISED;            // a park's apply must never take the supervised-exit arm
process.env.ROMP_QUIET_POLL_MS = '25';         // the park tests run REAL parks: fast polls…
process.env.ROMP_QUIET_MAX_DEFER_MS = '250';   // …and a near backstop (both bake at require time)

// KERNEL_PORT bakes at require time too, and the park tests below poll it for real — so the
// manager loads in before(), once the scripted kernel stub owns a port to bake in.
let kernelToken, fetchBusy, resetDrainNotices, queueQuietRestart, clearPendingQuiet;
let kstub;

const TOKEN_FILE = path.join(STATE, 'serve-token');

// One /busy stub per test: records the request, answers with a fixed body.
function serve(body) {
  return new Promise((resolve) => {
    const seen = [];
    const srv = http.createServer((req, res) => {
      seen.push({ url: req.url, token: req.headers['x-romp-token'] || null });
      res.setHeader('Content-Type', 'application/json');
      res.end(body);
    });
    srv.listen(0, '127.0.0.1', () =>
      resolve({ port: srv.address().port, seen, close: () => new Promise((r) => srv.close(r)) }));
  });
}

// The park tests' kernel: each request consumes the next scripted answer (a JSON body, or HOLD to
// park the response server-side for a later release(body) — an in-flight probe, made repeatable);
// an exhausted script answers with `fallback`.
const HOLD = Symbol('hold');
function scriptedStub() {
  return new Promise((resolve) => {
    const stub = { answers: [], fallback: JSON.stringify({ busy: 0, draining: true }),
                   held: [], seen: [] };
    const srv = http.createServer((req, res) => {
      stub.seen.push(req.url);
      res.setHeader('Content-Type', 'application/json');
      const next = stub.answers.length ? stub.answers.shift() : stub.fallback;
      if (next === HOLD) { stub.held.push(res); return; }
      res.end(next);
    });
    srv.listen(0, '127.0.0.1', () => {
      stub.port = srv.address().port;
      stub.release = (body) => { const r = stub.held.shift(); if (r) r.end(body); };
      stub.close = () => new Promise((r) => { stub.held.splice(0).forEach((h) => h.destroy()); srv.close(r); });
      resolve(stub);
    });
  });
}

before(async () => {
  kstub = await scriptedStub();
  process.env.ROMP_SERVE_PORT = String(kstub.port);
  ({ kernelToken, fetchBusy, resetDrainNotices, queueQuietRestart, clearPendingQuiet } =
    require(path.join(__dirname, '..', 'bin', 'romp-manager')));
});
after(async () => { await kstub.close(); });

const poll = (port, p) =>
  new Promise((resolve) => fetchBusy(port, (busy, draining) => resolve({ busy, draining }), p));

// The notices go through the manager's log() → process.stderr; capture around each probe.
async function captured(fn) {
  const orig = process.stderr.write;
  let out = '';
  process.stderr.write = (chunk) => { out += chunk; return true; };
  try { await fn(); } finally { process.stderr.write = orig; }
  return out;
}

beforeEach(() => {
  resetDrainNotices();
  if (typeof clearPendingQuiet === 'function') clearPendingQuiet();   // no park leaks across tests
  kstub.answers.length = 0;
  kstub.fallback = JSON.stringify({ busy: 0, draining: true });
  kstub.held.splice(0).forEach((r) => r.destroy());
  kstub.seen.length = 0;
  try { fs.unlinkSync(TOKEN_FILE); } catch (e) { /* absent is fine */ }
});

// Capture stderr while `run` executes, resolving with everything captured once `untilRe` matches
// (the park tests wait on the apply line this way — event-keyed, no fixed sleep).
function capturedUntil(untilRe, run, ms) {
  return new Promise((resolve, reject) => {
    const orig = process.stderr.write;
    let out = '';
    let settled = false;
    const done = (err) => {
      if (settled) return;
      settled = true;
      process.stderr.write = orig;
      clearTimeout(tm);
      if (err) reject(err); else resolve(out);
    };
    const tm = setTimeout(() => done(new Error(`never logged ${untilRe} — captured:\n${out}`)), ms || 8000);
    process.stderr.write = (chunk) => { out += chunk; if (untilRe.test(out)) setImmediate(() => done()); return true; };
    Promise.resolve().then(run).catch(done);
  });
}

const waitFor = (cond, ms = 2000) => new Promise((resolve, reject) => {
  const t0 = Date.now();
  const iv = setInterval(() => {
    if (cond()) { clearInterval(iv); resolve(); }
    else if (Date.now() - t0 > ms) { clearInterval(iv); reject(new Error('condition never held')); }
  }, 5);
});

test('a readable token file rides every poll as X-Romp-Token, with no notice', async () => {
  fs.writeFileSync(TOKEN_FILE, 'drain-probe-credential\n');
  const s = await serve(JSON.stringify({ busy: 1, draining: true }));
  let logged = '';
  let got;
  try {
    logged = await captured(async () => { got = await poll(s.port, '/busy?drain=1'); });
  } finally { await s.close(); }
  assert.equal(s.seen[0].token, 'drain-probe-credential', 'the 0600 token file is read fresh and attached');
  assert.equal(got.busy, 1);
  assert.equal(got.draining, true, 'the callback now carries the kernel’s draining answer');
  assert.equal(logged, '', 'a healthy handshake logs nothing');
});

test('an unreadable token file polls token-less and says so ONCE, naming path and error', async () => {
  const s = await serve(JSON.stringify({ busy: 0, draining: false }));
  let logged = '';
  let first, second;
  try {
    logged = await captured(async () => {
      first = await poll(s.port);          // plain /busy — the read arm, no drain ask
      second = await poll(s.port);
    });
  } finally { await s.close(); }
  assert.equal(s.seen[0].token, null, 'no invented header — the poll goes token-less');
  assert.equal(first.busy, 0, 'count-only polling still works (degrade behavior unchanged)');
  assert.equal(second.busy, 0);
  const lines = logged.split('\n').filter((l) => /serve token/.test(l));
  assert.equal(lines.length, 1, 'ONE clear line, not one per 3s poll');
  assert.match(lines[0], /serve-token/, 'the line names the token path');
  assert.match(lines[0], /ENOENT|no such file/i, 'the line names the read error');
});

test('a drain=1 poll the kernel answers draining:false logs the refusal ONCE per park', async () => {
  fs.writeFileSync(TOKEN_FILE, 'drain-probe-credential\n');
  const s = await serve(JSON.stringify({ busy: 3, draining: false }));
  let logged = '';
  let got;
  try {
    logged = await captured(async () => {
      got = await poll(s.port, '/busy?drain=1');
      await poll(s.port, '/busy?drain=1');   // the 3s re-poll must not repeat the line
    });
  } finally { await s.close(); }
  assert.equal(got.busy, 3, 'the count still reads — the refusal degrades, never breaks, the poll');
  assert.equal(got.draining, false);
  const lines = logged.split('\n').filter((l) => /refused the drain/i.test(l));
  assert.equal(lines.length, 1, 'rate-limited: once per park, not per poll');
  assert.match(lines[0], /not held/i, 'the line says what the refusal means: no hold armed');
});

test('a fresh park re-arms the refusal notice (resetDrainNotices is the per-park seam)', async () => {
  fs.writeFileSync(TOKEN_FILE, 'drain-probe-credential\n');
  const s = await serve(JSON.stringify({ busy: 2, draining: false }));
  let logged = '';
  try {
    logged = await captured(async () => {
      await poll(s.port, '/busy?drain=1');
      resetDrainNotices();                   // queueQuietRestart calls this when a new park begins
      await poll(s.port, '/busy?drain=1');
    });
  } finally { await s.close(); }
  assert.equal(logged.split('\n').filter((l) => /refused the drain/i.test(l)).length, 2);
});

test('a plain /busy read never cries refusal — only a poll that ASKED for the drain', async () => {
  fs.writeFileSync(TOKEN_FILE, 'drain-probe-credential\n');
  const s = await serve(JSON.stringify({ busy: 5, draining: false }));
  let logged = '';
  try {
    logged = await captured(async () => { await poll(s.port); });
  } finally { await s.close(); }
  assert.equal(logged, '', 'draining:false on a read-only poll is normal, not a refusal');
});

test('an older kernel without the draining field stays silent (unknown is not refused)', async () => {
  fs.writeFileSync(TOKEN_FILE, 'drain-probe-credential\n');
  const s = await serve(JSON.stringify({ busy: 2 }));
  let logged = '';
  let got;
  try {
    logged = await captured(async () => { got = await poll(s.port, '/busy?drain=1'); });
  } finally { await s.close(); }
  assert.equal(got.busy, 2);
  assert.equal(got.draining, null);
  assert.equal(logged, '', 'no field is no evidence — never a false refusal line against an old kernel');
});

test('kernelToken prefers the env, then the token file', () => {
  fs.writeFileSync(TOKEN_FILE, 'file-credential\n');
  assert.equal(kernelToken(), 'file-credential');
  process.env.ROMP_SERVE_TOKEN = 'env-credential';
  try { assert.equal(kernelToken(), 'env-credential'); }
  finally { delete process.env.ROMP_SERVE_TOKEN; }
});

// ── the park's drain EVIDENCE ───────────────────────────────────────────────────────────────────
// A single latched boolean (drainRefused, set on the first draining:false answer, never cleared)
// would be WRONG here: kernelToken() reads the token fresh per poll, so a refusal can be TRANSIENT
// (token restored mid-park → every later poll arms the hold), and the backstop line would then
// claim the hold was 'never armed' — false. And a stamp that read pendingQuiet at RESPONSE time
// would let an in-flight probe from a just-cleared park mark a brand-new park that never polled.
// These tests drive REAL parks against the scripted kernel stub (fast polls + a near backstop,
// baked above): evidence is counted per park, stamped only on the park that issued the poll, and
// the apply line renders what the counts actually show.

test('a park held only by background work polls plainly, carries its identity, and counts no refusal (T240c behavioral)', async () => {
  // mutation check (review): forcing park.lastAsked = true left every source pin green while the
  // backstop line blamed a lost hold — this drives the REAL park through the stub instead
  fs.writeFileSync(TOKEN_FILE, 'drain-probe-credential\n');
  kstub.seen.length = 0;
  // the first, uninformed poll ASKS for the hold and the kernel arms it; every later poll is plain
  // (0 in flight) and answers draining:false by construction — none of those may count as a refusal
  kstub.answers = [JSON.stringify({ busy: 1, inflight: 0, background: 1, draining: true })];
  kstub.fallback = JSON.stringify({ busy: 1, inflight: 0, background: 1, draining: false });
  let logged;
  try {
    logged = await capturedUntil(/applying deferred refresh/, () => { queueQuietRestart('ghost'); });
  } finally { clearPendingQuiet(); }
  const applyLine = logged.split('\n').find((l) => /applying deferred refresh/.test(l));
  assert.match(applyLine, /backstop cap/, 'background work never quiets here, so the backstop applies');
  assert.doesNotMatch(applyLine, /refused|never armed|LOST/, 'plain polls answer draining:false by construction — no refusal');
  const drainPolls = kstub.seen.filter((u) => /drain=1/.test(u));
  assert.ok(drainPolls.length <= 1, 'only the first, uninformed poll asks for the hold: ' + kstub.seen.join(' '));
  assert.ok(kstub.seen.length >= 2 && kstub.seen.every((u) => /[?&]park=\d+/.test(u)),
    'every parked poll carries the park identity: ' + kstub.seen.join(' '));
});

test('a real refusal on a poll that ASKED for the hold is still counted (T240c behavioral)', async () => {
  fs.writeFileSync(TOKEN_FILE, 'drain-probe-credential\n');
  kstub.seen.length = 0;
  kstub.answers = [];
  kstub.fallback = JSON.stringify({ busy: 1, inflight: 1, background: 0, draining: false });   // a turn in flight, hold refused
  let logged;
  try {
    logged = await capturedUntil(/applying deferred refresh/, () => { queueQuietRestart('ghost'); });
  } finally { clearPendingQuiet(); }
  const applyLine = logged.split('\n').find((l) => /applying deferred refresh/.test(l));
  assert.match(applyLine, /never armed/, 'every asked poll was refused: the hold never armed');
  assert.ok(kstub.seen.every((u) => /drain=1/.test(u)), 'a turn in flight: every poll asks for the hold');
});

test('a transient refusal (the hold arms later) renders the armed-after-refusal cause, never "never armed"', async () => {
  fs.writeFileSync(TOKEN_FILE, 'drain-probe-credential\n');
  kstub.answers = [JSON.stringify({ busy: 1, draining: false })];   // first poll: hold refused once…
  kstub.fallback = JSON.stringify({ busy: 1, draining: true });     // …every later poll arms it
  let logged;
  try {
    logged = await capturedUntil(/applying deferred refresh/, () => { queueQuietRestart('ghost'); });
  } finally { clearPendingQuiet(); }
  const applyLine = logged.split('\n').find((l) => /applying deferred refresh/.test(l));
  assert.match(applyLine, /backstop cap/, 'busy never quiets, so the backstop applies');
  assert.match(applyLine, /refused 1 time\(s\) before arming/,
    'the cause is the truth this park saw: refused once, then armed');
  assert.doesNotMatch(applyLine, /never armed/,
    'a transient refusal must not read as a hold that never armed');
});

test('a hold that ARMED and was then LOST renders the lost-after-arming cause, never "before arming" (T227)', async () => {
  // the other order: the first poll arms the hold, every later poll is refused (the token file went
  // away mid-park). Two bare counters read this as "refused N before arming" — the ordering flag
  // says what actually happened.
  fs.writeFileSync(TOKEN_FILE, 'drain-probe-credential\n');
  // two refusals BEFORE the arm, then the hold arms, then every later poll is refused: the line must
  // count the post-arm refusals on their own and name the pre-arm ones separately (the review's
  // catch: a boolean flag let the whole total read as "after arming")
  kstub.answers = [JSON.stringify({ busy: 1, draining: false }), JSON.stringify({ busy: 1, draining: false }),
                   JSON.stringify({ busy: 1, draining: true })];
  kstub.fallback = JSON.stringify({ busy: 1, draining: false });
  let logged;
  try {
    logged = await capturedUntil(/applying deferred refresh/, () => { queueQuietRestart('ghost'); });
  } finally { clearPendingQuiet(); }
  const applyLine = logged.split('\n').find((l) => /applying deferred refresh/.test(l));
  assert.match(applyLine, /backstop cap/);
  assert.match(applyLine, /armed and was then LOST/, 'the cause states the order that happened');
  const m = /refused (\d+) time\(s\) after arming, (\d+) before/.exec(applyLine);
  assert.ok(m, 'the line splits post-arm from pre-arm refusals: ' + applyLine);
  assert.equal(Number(m[2]), 2, 'exactly the two scripted pre-arm refusals read as "before"');
  assert.ok(Number(m[1]) >= 1, 'the post-arm count is the loss itself, never inflated by the pre-arm two');
  assert.doesNotMatch(applyLine, /before arming|never armed/,
    'the reversed order must not borrow the other cause');
});

test('an in-flight probe from a cleared park never stamps the park that replaced it', async () => {
  fs.writeFileSync(TOKEN_FILE, 'drain-probe-credential\n');
  kstub.answers = [HOLD];                                           // park A's first probe parks server-side
  kstub.fallback = JSON.stringify({ busy: 1, draining: true });     // park B's own polls all arm the hold
  let logged;
  try {
    logged = await capturedUntil(/applying deferred refresh/, async () => {
      queueQuietRestart('ghost');                 // park A issues the probe the stub is holding
      await waitFor(() => kstub.held.length === 1);
      clearPendingQuiet();                        // an immediate restart satisfies A mid-flight
      queueQuietRestart('ghost');                 // park B begins; it never sees a refusal itself
      kstub.release(JSON.stringify({ busy: 1, draining: false }));  // A's stale refusal lands during B
    });
  } finally { clearPendingQuiet(); }
  const applyLine = logged.split('\n').find((l) => /applying deferred refresh/.test(l));
  assert.match(applyLine, /backstop cap/);
  assert.doesNotMatch(applyLine, /never armed|refused/,
    'park B armed on every poll it issued — park A\'s stale answer is not B\'s evidence');
});

test('a second refusal episode after a recovery logs again (the armed poll re-arms the notice)', async () => {
  fs.writeFileSync(TOKEN_FILE, 'drain-probe-credential\n');
  kstub.answers = [
    JSON.stringify({ busy: 2, draining: false }),   // episode 1: refused → the loud line
    JSON.stringify({ busy: 2, draining: true }),    // recovery: the hold armed
    JSON.stringify({ busy: 2, draining: false }),   // episode 2: refused again → new information
  ];
  const logged = await captured(async () => {
    await poll(kstub.port, '/busy?drain=1');
    await poll(kstub.port, '/busy?drain=1');
    await poll(kstub.port, '/busy?drain=1');
  });
  const refusals = logged.split('\n').filter((l) => /refused the drain/i.test(l));
  assert.equal(refusals.length, 2,
    'one line per refusal EPISODE — a lost-recovered-lost hold is two events, not one');
  assert.match(logged, /armed the drain hold/i, 'the recovery itself goes on the record');
});

// The park half of the wiring lives inside queueQuietRestart's closures (module state: pendingQuiet,
// KERNEL_PORT), so the probe spelling is pinned at the source like the suite's other closure pins
// (T121/T160); the park's evidence behavior itself is driven for real above.
test('the park records drain evidence and the backstop line names it (source pin)', () => {
  const src = fs.readFileSync(path.join(__dirname, '..', 'bin', 'romp-manager'), 'utf8');
  assert.match(src, /drainRefusedCount/, 'the park counts refusals, never latching one bit');
  assert.match(src, /drainArmedCount/, 'the park counts arms, so a transient refusal reads true');
  assert.ok(src.includes("fetchBusy(KERNEL_PORT, cb, holdTurns ? '/busy?drain=1&' + pk : '/busy?' + pk)"),
    'the parked poll still binds the drain-refresh spelling of the probe — while a turn is in flight (T240), carrying the park identity (T240c)');
  assert.match(src, /never armed/, 'the backstop apply line can still say the hold never armed');
  assert.match(src, /resetDrainNotices\(\)/, 'a fresh park re-arms the once-per-episode notices');
  assert.ok(src.includes('if (draining === false && park.lastAsked) {'),
    'only a poll that ASKED for the hold can record a refusal — a plain /busy answers draining:false by construction (T240)');
});
