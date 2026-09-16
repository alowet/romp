// A restart in flight is an event, not a window (2026-09-15): the kernel's own converge and a peer's push asked
// restart-all three seconds apart, and the second SIGTERM killed a kernel two seconds old. inflightGate is the pure
// decision on the record's phase: from the SIGTERM until the successor is spawned a second request is FOLDED into the
// restart in flight (the successor loads the disk as it stands); from the spawn until the successor answers its port
// one TRAILING restart is kept and sent when it does, if the successor's own verdict says its disk holds code it does
// not run; a second ask during that boot is new information and restarts the successor at once; the successor's exit
// ends the flight. The wiring is executed with a stand-in child and a stand-in kernel port.
// Run: node --test tests/manager-fold.test.js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');

const ROOTS = [];
const tmpRoot = (prefix) => { const d = fs.mkdtempSync(path.join(os.tmpdir(), prefix)); ROOTS.push(d); return d; };
process.on('exit', () => { for (const d of ROOTS) fs.rmSync(d, { recursive: true, force: true }); });
const STATE = tmpRoot('romp-mgr-fold-');
process.env.ROMP_STATE_DIR = STATE;
process.env.ROMP_READY_PROBE_MS = '20';
const MGR = path.join(__dirname, '..', 'bin', 'romp-manager');
const mgr = require(MGR);
const { restartKernel, kernels } = mgr;
// The new names, reached through guards so a base without them fails on the behaviour each test states, never on a TypeError.
const inflightGate = mgr.inflightGate || (() => 'absent');
const inflightAfterExit = mgr.inflightAfterExit || (() => 'absent');
const awaitReady = mgr.awaitReady || (() => {});
const SRC = fs.readFileSync(MGR, 'utf8');

const AUDIT = path.join(STATE, 'restart-audit.jsonl');
const rows = () => (fs.existsSync(AUDIT) ? fs.readFileSync(AUDIT, 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l)) : []);
const resetAudit = () => { try { fs.unlinkSync(AUDIT); } catch (e) { /* none yet */ } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// A stand-in child: records the signals it is sent, never exits on its own.
function standIn(pid) {
  return { pid, signals: [], exitCode: null, signalCode: null, kill(sig) { this.signals.push(sig); } };
}
function seed(id, child, over) {
  kernels.clear();
  kernels.set(id, Object.assign({ spec: { id, port: 1, stateDir: STATE }, child, restarts: 0, quickCrashes: 0,
                                  startedAt: Date.now(), stopping: false, requested: null, inflight: null, trail: null }, over || {}));
  return kernels.get(id);
}
// A stand-in kernel port: answers /busy and /version as told.
async function kernelPort(restartPending) {
  const seen = [];
  const srv = http.createServer((req, res) => {
    seen.push(req.url);
    res.setHeader('Content-Type', 'application/json');
    if (req.url.startsWith('/version')) return res.end(JSON.stringify({ restart_pending: restartPending }));
    res.end(JSON.stringify({ busy: 0 }));
  });
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  return { port: srv.address().port, seen, close: () => new Promise((r) => srv.close(r)) };
}

test('the pure gate: no flight restarts, a signaled flight folds, a spawned successor trails once, a second ask restarts', () => {
  assert.equal(inflightGate(null), 'restart');
  assert.equal(inflightGate(undefined), 'restart');
  assert.equal(inflightGate('signaled'), 'fold');
  assert.equal(inflightGate('spawned'), 'trail');
  assert.equal(inflightGate('spawned', true), 'restart', 'a trail already pending: the new ask is new information');
});

test('the phase after an exit: a booting successor that dies ends the flight, a signaled restart keeps its phase', () => {
  assert.equal(inflightAfterExit('spawned'), null);
  assert.equal(inflightAfterExit(null), null);
  assert.equal(inflightAfterExit('signaled'), 'signaled');
  assert.match(SRC, /cur\.inflight = inflightAfterExit\(cur\.inflight\)/, 'the exit handler applies it before it respawns');
});

test('two restart requests during one restart kill once: the second is folded and noted', () => {
  resetAudit();
  const child = standIn(4242);
  const rec = seed('main', child);
  assert.ok(restartKernel('main', 'restart-all'), 'the first request restarts');
  const second = restartKernel('main', 'restart-all');
  assert.deepEqual(child.signals, ['SIGTERM'], 'one SIGTERM for two requests: the base sent one at once and one three seconds later (its coalesce gate)');
  assert.equal(second, 'folded', 'the second request rides the restart in flight');
  assert.equal(rec.inflight, 'signaled', 'the record says a restart is in flight');
  const r = rows();
  assert.deepEqual(r.map((x) => x.action), ['manager-sigterm', 'restart-folded'], 'the ledger: one sigterm, one fold');
  assert.equal(r[1].into, 4242, 'the fold names the pid it rode');
  assert.equal(r[1].trigger, 'restart-all');
});

test('a request while the successor is up but not yet answering is kept as one trailing restart, never a second kill', () => {
  resetAudit();
  const child = standIn(5151);
  const rec = seed('main', child, { inflight: 'spawned' });
  assert.equal(restartKernel('main', 'p2p-update'), 'trailing');
  assert.deepEqual(child.signals, [], 'nothing signaled: the new kernel is still booting');
  assert.equal(rec.trail, 'p2p-update', 'one trailing restart kept');
  assert.deepEqual(rows().map((x) => x.action), ['restart-trailing']);
});

test('a second ask during one boot restarts the successor at once: a person asking twice recovers a hung boot', () => {
  resetAudit();
  const child = standIn(5252);
  const rec = seed('main', child, { inflight: 'spawned', trail: 'p2p-update' });
  const r = restartKernel('main', 'restart-all');
  assert.equal(r, true, 'an ordinary restart, not a fold or a trail');
  assert.deepEqual(child.signals, ['SIGTERM'], 'the hung successor is signaled (the base signaled too; the round-one head folded forever)');
  assert.equal(rec.trail, null, 'the pending trail rides this restart');
  assert.equal(rec.inflight, 'signaled');
  assert.deepEqual(rows().map((x) => x.action), ['manager-sigterm']);
});

test('the successor answering its port ends the flight; the trailing restart goes out only when its disk holds code it does not run', async () => {
  resetAudit();
  const stale = await kernelPort(true);
  try {
    const child = standIn(6161);
    const rec = seed('main', child, { inflight: 'spawned', trail: 'p2p-update' });
    rec.spec.port = stale.port;
    awaitReady('main', child);
    await sleep(300);
    assert.ok(stale.seen.some((u) => u.startsWith('/version')), 'the successor was asked for its verdict');
    assert.deepEqual(child.signals, ['SIGTERM'], 'restart_pending true: the trailing restart went out once');
    assert.equal(rec.trail, null, 'and the trail is consumed');
    assert.deepEqual(rows().map((x) => x.action), ['manager-sigterm']);
  } finally { await stale.close(); }
  resetAudit();
  const current = await kernelPort(false);
  try {
    const child = standIn(6262);
    const rec = seed('main', child, { inflight: 'spawned', trail: 'p2p-update' });
    rec.spec.port = current.port;
    awaitReady('main', child);
    await sleep(300);
    assert.deepEqual(child.signals, [], 'restart_pending false: the successor already runs the disk; no restart for a checkout it loaded');
    assert.equal(rec.inflight, null, 'the flight is over');
    assert.equal(rec.trail, null, 'and the trail is dropped');
    assert.deepEqual(rows().map((x) => x.action), ['restart-trailing-current'], 'the ledger says the trail was current');
  } finally { await current.close(); }
});

test('the successor answering with restart_pending true and no trail pending is restarted: the disk moved after it loaded its code', async () => {
  resetAudit();
  const stale = await kernelPort(true);
  try {
    const child = standIn(6363);
    const rec = seed('main', child, { inflight: 'spawned' });
    rec.spec.port = stale.port;
    awaitReady('main', child);
    await sleep(300);
    assert.deepEqual(child.signals, ['SIGTERM'], 'restarted on its own verdict (the after-pull race: main advanced during its boot)');
    assert.equal(rows()[0].trigger, 'successor-behind-disk');
  } finally { await stale.close(); }
  resetAudit();
  const current = await kernelPort(false);
  try {
    const child = standIn(6464);
    const rec = seed('main', child, { inflight: 'spawned' });
    rec.spec.port = current.port;
    awaitReady('main', child);
    await sleep(300);
    assert.deepEqual(child.signals, [], 'current and no trail: nothing');
    assert.equal(rec.inflight, null);
    assert.deepEqual(rows(), []);
  } finally { await current.close(); }
});

test('the probes act once per ask: a version ask that times out answers its callback once', async () => {
  const srv = http.createServer(() => { /* accept, never answer */ });
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  try {
    const calls = [];
    (mgr.fetchVersion || ((p, cb) => { cb(null); cb(null); }))(srv.address().port, (v) => calls.push(v));
    await sleep(5600);
    assert.deepEqual(calls, [null], 'one null for the timeout, not two (the destroy fires the error too)');
    assert.match(SRC, /let acted = false;\s*\/\/ fetchBusy fires its callback twice on a timeout/, 'awaitReady guards its probe the same way');
  } finally { await new Promise((r) => srv.close(r)); }
});

test('restart-all separates what it signaled from what rode a flight', () => {
  resetAudit();
  kernels.clear();
  const a = standIn(9191), b = standIn(9292), c = standIn(9393);
  kernels.set('a', { spec: { id: 'a', port: 1, stateDir: STATE }, child: a, restarts: 0, quickCrashes: 0, startedAt: Date.now(), stopping: false, requested: null, inflight: null, trail: null });
  kernels.set('b', { spec: { id: 'b', port: 1, stateDir: STATE }, child: b, restarts: 0, quickCrashes: 0, startedAt: Date.now(), stopping: false, requested: null, inflight: 'signaled', trail: null });
  kernels.set('c', { spec: { id: 'c', port: 1, stateDir: STATE }, child: c, restarts: 0, quickCrashes: 0, startedAt: Date.now(), stopping: false, requested: null, inflight: 'spawned', trail: null });
  const out = {};
  const ids = mgr.restartAll('restart-all', out);
  assert.deepEqual(ids.sort(), ['a', 'b', 'c'], 'the ids array stays whole');
  assert.deepEqual(out, { signaled: ['a'], folded: ['b'], trailing: ['c'] }, 'restarted names a signal only; folded and trailing apart');
  assert.deepEqual([a.signals, b.signals, c.signals], [['SIGTERM'], [], []]);
  assert.match(SRC, /restarted: r\.self \? r\.ids : \(r\.signaled \|\| \[\]\)/, 'the /restart-all answer lists a signal under restarted');
  kernels.clear();
});

test('a successor that never answers keeps the flight open only until it exits or a second ask arrives', async () => {
  resetAudit();
  const child = standIn(7171);
  const rec = seed('main', child, { inflight: 'spawned' });
  rec.spec.port = 1;   // nothing listens: the probe fails and is asked again, bounded by the exit below
  awaitReady('main', child);
  await sleep(120);
  assert.equal(rec.inflight, 'spawned', 'no answer, no end of flight');
  assert.deepEqual(child.signals, [], 'and no signal on its own');
  assert.equal(restartKernel('main', 'restart-all'), 'trailing', 'the first ask trails');
  assert.equal(restartKernel('main', 'restart-all'), true, 'the second ask restarts the hung successor');
  assert.deepEqual(child.signals, ['SIGTERM']);
  child.exitCode = 1;   // the child leaves: the probe stands down (its exit handler ends the flight)
  await sleep(120);
  kernels.clear();
});

test('the storm history is not carried across a respawn, and the single-kernel restart answer names a fold or a trail', () => {
  assert.doesNotMatch(SRC, /_rs: prev \? prev\._rs/, 'a completed restart is a fresh record for the storm gate');
  assert.match(SRC, /return restartKernel\(kid\) \? json\(200, restartAnswer\(kid\)\)/, 'POST /restart answers through restartAnswer');
  const child = standIn(8181);
  seed('main', child, { inflight: 'signaled' });
  restartKernel('main', 'restart');
  assert.deepEqual(mgr.restartAnswer ? mgr.restartAnswer('main') : null, { ok: true, restarted: 'main', folded: true }, 'a folded request says so');
  seed('main', standIn(8282));
  restartKernel('main', 'restart');
  assert.deepEqual(mgr.restartAnswer ? mgr.restartAnswer('main') : null, { ok: true, restarted: 'main' }, 'an ordinary restart is the plain answer');
});
