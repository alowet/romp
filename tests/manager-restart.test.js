// romp-manager's restart-storm guard (the user 2026-06-24): the kernel was SIGTERM'd + respawned 300+ times
// because every /restart restarted 1:1. restartGate coalesces near-simultaneous requests into one trailing
// restart and, once the rate looks like a storm, holds to one restart per cooldown. Pure decision function,
// time injected — unit-tested here. Run: node --test tests/manager-restart.test.js
const { test } = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const { restartGate } = require(path.join(__dirname, '..', 'bin', 'romp-manager'));

const OPTS = { coalesceMs: 3000, stormWindowMs: 60000, stormMax: 8, stormCooldownMs: 30000 };
const burst = (n, start = 1000, gap = 100) => Array.from({ length: n }, (_, i) => start + i * gap);

test('first restart goes through immediately', () => {
  assert.equal(restartGate({ last: null, history: [] }, 1000, OPTS).action, 'restart');
});

test('a rapid second request coalesces into a single trailing restart', () => {
  const g = restartGate({ last: 1000, history: [1000] }, 1500, OPTS);   // 500ms later
  assert.equal(g.action, 'coalesce');
  assert.ok(g.scheduleIn > 0 && g.scheduleIn <= OPTS.coalesceMs);
});

test('a request after the coalesce window restarts', () => {
  assert.equal(restartGate({ last: 1000, history: [1000] }, 4001, OPTS).action, 'restart');
});

test('a storm (>= stormMax in window) widens the gap to the cooldown — caps a tight loop', () => {
  const history = burst(8);                                            // 8 restarts in 700ms
  const g = restartGate({ last: history[7], history }, history[7] + 4000, OPTS); // 4s > coalesce, < cooldown
  assert.equal(g.inStorm, true);
  assert.equal(g.action, 'coalesce');
});

test('after the cooldown elapses a restart goes through even mid-storm (latest code still loads)', () => {
  const history = burst(8);
  assert.equal(restartGate({ last: history[7], history }, history[7] + 31000, OPTS).action, 'restart');
});

test('old restarts age out of the window — no false storm', () => {
  const history = burst(8);
  const g = restartGate({ last: history[7], history }, history[7] + 70000, OPTS);
  assert.equal(g.inStorm, false);
  assert.equal(g.action, 'restart');
});

// Quiet-window deploy deferral (the user 2026-07-20): peers deploying with `romp --refresh` bounced
// the kernel 11x in one day, each bounce cutting whatever SDK turns were in flight. quietGate is the
// pure apply/wait decision: apply when the kernel reports zero in-flight turns (or is unreachable —
// nothing to cut), wait otherwise, with a backstop cap so a never-quiet fleet still gets its deploy.
const { quietGate } = require(path.join(__dirname, '..', 'bin', 'romp-manager'));
const QOPTS = { maxDeferMs: 900000 };

test('quiet fleet applies immediately', () => {
  const g = quietGate({ since: 1000 }, 0, 2000, QOPTS);
  assert.equal(g.action, 'apply');
  assert.equal(g.reason, 'quiet');
});

test('in-flight turns defer the bounce', () => {
  const g = quietGate({ since: 1000 }, 2, 2000, QOPTS);
  assert.equal(g.action, 'wait');
  assert.match(g.reason, /2 turn/);
});

test('an unreachable kernel applies — nothing a restart could cut', () => {
  assert.equal(quietGate({ since: 1000 }, null, 2000, QOPTS).action, 'apply');
});

test('the backstop cap applies even while busy — a deploy can never starve', () => {
  const g = quietGate({ since: 1000 }, 5, 1000 + QOPTS.maxDeferMs, QOPTS);
  assert.equal(g.action, 'apply');
  assert.equal(g.reason, 'backstop cap');
});

test('just under the cap still waits', () => {
  assert.equal(quietGate({ since: 1000 }, 5, 999 + QOPTS.maxDeferMs, QOPTS).action, 'wait');
});

// quietTick — the CHAIN around quietGate (the 2026-08-14 incident: a queued refresh logged its backstop
// and then silently never applied; the old loop re-armed the next tick only inside the busy-probe
// callback, so a probe whose callback never fired killed the pending refresh with zero further log
// lines). Dependency-injected: these tests drive the exact seams that failed.
const { quietTick } = require(path.join(__dirname, '..', 'bin', 'romp-manager'));

test('quietTick: a probe whose callback never fires cannot kill the chain (schedule-first)', () => {
  let scheduled = 0;
  quietTick({ pending: () => ({ since: 0 }), fetchBusy: () => {}, now: () => 1000,
              opts: QOPTS, log: () => {}, schedule: () => { scheduled++; }, apply: () => {} });
  assert.equal(scheduled, 1);
});

test('quietTick: a double-fired probe callback evaluates once (http timeout + error both fire)', () => {
  let applied = 0; let cb; const park = { since: 0 };   // one park object, as the real pendingQuiet is
  quietTick({ pending: () => park, fetchBusy: (c) => { cb = c; }, now: () => 1000,
              opts: QOPTS, log: () => {}, schedule: () => {}, apply: () => { applied++; } });
  cb(0); cb(0);
  assert.equal(applied, 1);
});

test('quietTick: a throwing evaluation is LOUD and leaves the refresh queued', () => {
  let logged = ''; let applied = 0; const park = { since: 0 };
  quietTick({ pending: () => park, fetchBusy: (c) => c(0), now: () => { throw new Error('boom'); },
              opts: QOPTS, log: (m) => { logged = m; }, schedule: () => {}, apply: () => { applied++; } });
  assert.match(logged, /stays queued/);
  assert.equal(applied, 0);
});

test('quietTick: a satisfied pending (an immediate restart won) neither probes nor re-arms', () => {
  let scheduled = 0;
  quietTick({ pending: () => null, fetchBusy: () => { throw new Error('must not probe'); },
              now: () => 0, opts: QOPTS, log: () => {}, schedule: () => { scheduled++; }, apply: () => {} });
  assert.equal(scheduled, 0);
});

test('quietTick: a quiet fleet applies through the injected apply', () => {
  let applied = null; const park = { since: 0 };
  quietTick({ pending: () => park, fetchBusy: (c) => c(0), now: () => 1000,
              opts: QOPTS, log: () => {}, schedule: () => {}, apply: (g) => { applied = g; } });
  assert.equal(applied && applied.reason, 'quiet');
});

// T224: the busy answer binds to the park that ISSUED the probe. quietTick used to read pendingQuiet
// at RESPONSE time, so a probe issued for park A whose answer landed after A was cleared and park B
// replaced it drove B's apply decision off A's count — a wrong-generation read (a stale busy:0 from
// A applied B's refresh over in-flight turns; a stale busy count from A held B for nothing).
test('quietTick: a stale answer from a replaced park is DROPPED loudly, never applied to the new park', () => {
  const parkA = { since: 0, gen: 1 }, parkB = { since: 500, gen: 2 };
  let current = parkA; let cb; let applied = 0; let logged = '';
  quietTick({ pending: () => current, fetchBusy: (c) => { cb = c; }, now: () => 1000,
              opts: QOPTS, log: (m) => { logged = m; }, schedule: () => {}, apply: () => { applied++; } });
  current = parkB;            // park A cleared and replaced while A's probe was in flight
  cb(0);                      // A's stale quiet answer lands
  assert.equal(applied, 0, "park B's decision must not ride park A's answer");
  assert.match(logged, /stale/i, 'the drop is on the record');
});

test('quietTick: the answer to the CURRENT park still applies exactly as before', () => {
  const park = { since: 0 };
  let applied = null;
  quietTick({ pending: () => park, fetchBusy: (c) => c(0), now: () => 1000,
              opts: QOPTS, log: () => {}, schedule: () => {}, apply: (g) => { applied = g; } });
  assert.equal(applied && applied.reason, 'quiet');
});

// T121: the PARKED quiet poll is also the kernel's drain-lease refresher — one probe reads the
// count AND holds new turn starts, and the lease dies by itself when this manager stops polling
// (no off-switch to forget; a fresh kernel boots clear by construction).
test('the parked quiet poll refreshes the kernel drain lease in the same probe', () => {
  const fs = require('node:fs');
  const src = fs.readFileSync(path.join(__dirname, '..', 'bin', 'romp-manager'), 'utf8');
  assert.ok(src.includes("fetchBusy(KERNEL_PORT, cb, holdTurns ? '/busy?drain=1' : '/busy')"),
    'the quiet tick binds the drain-refresh spelling of the probe — while a turn is in flight (T240)');
  assert.ok(src.includes('const holdTurns = park.lastInflight === undefined || park.lastInflight > 0;'),
    'the hold is asked for only while a turn is actually in flight (or on the first, uninformed poll) — background-only busyness defers without freezing other sessions');
  assert.ok(src.includes('path: path || \'/busy\''),
    'a plain /busy stays side-effect free — only the parked poll holds');
});

// ── T160 (the user 2026-08-28): deploys bounce IMMEDIATELY by default ─────────────────────────────
// The quiet window is an explicit opt-in now (`restart-all --quiet`), never the implicit deploy
// default: parked windows cost minutes per push (0–570s measured) and still cut turns at the
// backstop. Source pins on the CLI dispatch, the one place the default lives.
test('restart-all dispatches IMMEDIATE by default — --quiet is the explicit drain spelling', () => {
  const src = require('node:fs').readFileSync(path.join(__dirname, '..', 'bin', 'romp-manager'), 'utf8');
  assert.match(src, /process\.argv\[3\] === '--quiet' \? \{ when: 'quiet' \} : \{\}/,
    'the dispatch default sends NO when param (immediate); --quiet opts into the drain');
  assert.doesNotMatch(src, /'--now' \? \{\} : \{ when: 'quiet' \}/,
    'the old quiet-by-default dispatch is gone');
});
