// romp-manager's default tmux server and the service cgroup (2026-09-05): the manager runs as a
// systemd user service that relies on systemd's default KillMode=control-group, so a tmux server it
// starts bare dies with `systemctl --user restart romp-manager`, and every session's tmux jobs die
// with it. tmuxStartArgv is the pure argv choice, and it mirrors the kernel's cli_scope_supported
// exactly: scoped when ROMP_CLI_SCOPE=1, or under ROMP_SUPERVISED unless ROMP_CLI_SCOPE=0 — and then
// only on Linux with systemd-run on PATH. A terminal-run manager scopes nothing unless asked. No tmux
// on PATH → null: nothing to start, nothing to log (the behaviour before the scopes). scopedStartFailure
// turns the scoped call's execFileSync error into the log line's content: the tool that failed and its
// first stderr line, bounded (startTmuxServer pipes stderr on that call for it). After a failed scoped
// start the bare call runs and the log then READS where the server sits (the #953 review: a timed-out
// scoped call kills only tmux's client, the daemon it forked stays inside the scope, so the old fixed
// line predicted a loss that would not happen): placementFromCgroup places a /proc/<pid>/cgroup text,
// tmuxServerPlacement asks tmux for the server pid and reads that file (never throws), bareEnsuredLine
// words the line from the answer.
// Run: node --test tests/manager-*.test.js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

process.env.ROMP_STATE_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'romp-mgr-tmux-scope-'));
const { tmuxStartArgv, scopedStartFailure, commandOnPath, TMUX_START_ARGV,
        placementFromCgroup, tmuxServerPlacement, bareEnsuredLine, TMUX_SERVER_PID_ARGV } = require(path.join(__dirname, '..', 'bin', 'romp-manager'));

const BARE = ['tmux', 'start-server', ';', 'set', '-g', 'exit-empty', 'off'];
const both = (name) => name === 'systemd-run' || name === 'tmux';   // a Linux box with both installed
const tmuxOnly = (name) => name === 'tmux';                         // no systemd-run
const SUPERVISED = { ROMP_SUPERVISED: '1' };                         // what bin/romp-service's unit sets
const pick = (env, opts = {}) => tmuxStartArgv({ platform: 'linux', env, onPath: both, now: () => 1725000000000, ...opts });

test('the bare tmux argv is the one the manager always used', () => {
  assert.deepEqual(TMUX_START_ARGV, BARE);
});

test('under the supervised service on linux with systemd-run: the server starts inside a transient scope', () => {
  const p = pick(SUPERVISED);
  assert.equal(p.scoped, true);
  assert.equal(p.argv[0], 'systemd-run');
  for (const flag of ['--user', '--scope', '--quiet', '--collect']) assert.ok(p.argv.includes(flag), flag);
  const unit = p.argv.find((a) => a.startsWith('--unit='));
  assert.equal(unit, '--unit=romp-tmux-1725000000000');
  // the tmux argv follows `--`, verbatim
  const dash = p.argv.indexOf('--');
  assert.ok(dash > 0);
  assert.deepEqual(p.argv.slice(dash + 1), BARE);
});

test('two picks get two unit names (systemd refuses a duplicate as "already loaded")', () => {
  let t = 1;
  const a = pick(SUPERVISED, { now: () => t++ });
  const b = pick(SUPERVISED, { now: () => t++ });
  assert.notEqual(a.argv.find((x) => x.startsWith('--unit=')), b.argv.find((x) => x.startsWith('--unit=')));
});

// The switch mirrors the kernel's (cli_scope_supported): the same environment gives the same answer.
test('a terminal-run manager (ROMP_SUPERVISED unset) scopes nothing, systemd-run or not', () => {
  assert.deepEqual(pick({}), { argv: BARE, scoped: false });
  assert.deepEqual(pick({ ROMP_SUPERVISED: '' }), { argv: BARE, scoped: false }, 'an empty value is unset');
});

test('ROMP_CLI_SCOPE=1 turns the scope on for a manager run outside the service', () => {
  assert.equal(pick({ ROMP_CLI_SCOPE: '1' }).scoped, true);
});

test('ROMP_CLI_SCOPE=0 turns the scope off under the service', () => {
  assert.deepEqual(pick({ ...SUPERVISED, ROMP_CLI_SCOPE: '0' }), { argv: BARE, scoped: false });
});

test('an empty ROMP_CLI_SCOPE under the service is the default (on), as in the kernel', () => {
  assert.equal(pick({ ...SUPERVISED, ROMP_CLI_SCOPE: '' }).scoped, true);
});

test('systemd-run absent: the bare call, even under the service', () => {
  assert.deepEqual(pick(SUPERVISED, { onPath: tmuxOnly }), { argv: BARE, scoped: false });
});

test('darwin: the bare call, whatever is on PATH or in the environment (launchd owns the lineage there)', () => {
  assert.deepEqual(pick(SUPERVISED, { platform: 'darwin' }), { argv: BARE, scoped: false });
  assert.deepEqual(pick({ ROMP_CLI_SCOPE: '1' }, { platform: 'darwin' }), { argv: BARE, scoped: false });
});

// tmux is checked FIRST: a tmux-less box used to log "systemd-run could not start the tmux server in
// a scope … " at every start, because the scoped call failed on the missing tmux inside the scope.
test('tmux absent: null — nothing to start, nothing to log, whatever else is on PATH', () => {
  const systemdRunOnly = (name) => name === 'systemd-run';
  assert.equal(pick(SUPERVISED, { onPath: systemdRunOnly }), null);
  assert.equal(pick({ ROMP_CLI_SCOPE: '1' }, { onPath: systemdRunOnly }), null);
  assert.equal(pick({}, { onPath: () => false }), null);
  assert.equal(pick({}, { platform: 'darwin', onPath: () => false }), null);
});

test('the returned bare argv is a copy — a caller cannot mutate the constant', () => {
  const p = pick({});
  p.argv.push('x');
  assert.deepEqual(TMUX_START_ARGV, BARE);
});

test('commandOnPath finds an executable on the given PATH and nothing else', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'romp-onpath-'));
  fs.writeFileSync(path.join(dir, 'systemd-run'), '#!/bin/sh\nexit 0\n', { mode: 0o755 });
  fs.writeFileSync(path.join(dir, 'not-exec'), 'x', { mode: 0o644 });
  const env = { PATH: ['', dir, '/nonexistent-dir'].join(path.delimiter) };
  assert.equal(commandOnPath('systemd-run', env), true);
  assert.equal(commandOnPath('not-exec', env), false);
  assert.equal(commandOnPath('missing', env), false);
  assert.equal(commandOnPath('systemd-run', { PATH: '' }), false);
  assert.equal(commandOnPath('systemd-run', {}), false);
});

// startTmuxServer's failure line. execFileSync's error carries the piped stderr; with stdio 'ignore' its
// message was "Command failed: <argv>", the argv and nothing about why, and the line named systemd-run
// even when tmux had failed inside a scope that did start. systemd-run's logger prefixes every line
// "Failed to …"; anything else on stderr is the command's own, so it is tmux that failed.
const failed = (over) => Object.assign(new Error('Command failed: systemd-run --user --scope --quiet --collect --unit=romp-tmux-1 -- tmux start-server ; set -g exit-empty off'),
                                       { status: 1, signal: null, stderr: null }, over);

test("systemd-run's own failure: its first stderr line, and systemd-run named", () => {
  const e = failed({ stderr: Buffer.from('Failed to start transient scope unit: Failed to connect to bus: No such file or directory\n') });
  assert.deepEqual(scopedStartFailure(e),
    { tool: 'systemd-run', detail: 'Failed to start transient scope unit: Failed to connect to bus: No such file or directory' });
});

test('tmux failing inside the scope: tmux named, and its line carried', () => {
  const e = failed({ stderr: Buffer.from('error connecting to /nonexistent/tmux-0/default (No such file or directory)\n') });
  assert.deepEqual(scopedStartFailure(e),
    { tool: 'tmux', detail: 'error connecting to /nonexistent/tmux-0/default (No such file or directory)' });
});

test('the first non-blank stderr line only, trimmed; a string stderr reads the same as a Buffer', () => {
  const two = '\n  Failed to create bus connection: Connection refused  \nsecond line, not for the log\n';
  assert.equal(scopedStartFailure(failed({ stderr: Buffer.from(two) })).detail, 'Failed to create bus connection: Connection refused');
  assert.equal(scopedStartFailure(failed({ stderr: two })).detail, 'Failed to create bus connection: Connection refused');
});

test('a long line is cut to 200 characters, the last an ellipsis', () => {
  const { tool, detail } = scopedStartFailure(failed({ stderr: Buffer.from('Failed to ' + 'x'.repeat(500) + '\n') }));
  assert.equal(tool, 'systemd-run');
  assert.equal(detail.length, 200);
  assert.ok(detail.startsWith('Failed to xxx'));
  assert.ok(detail.endsWith('…'));
  // at the bound exactly: untouched
  assert.equal(scopedStartFailure(failed({ stderr: Buffer.from('Failed to ' + 'x'.repeat(190)) })).detail.length, 200);
});

test('nothing on stderr: the exit status, and systemd-run named (the command that ran)', () => {
  assert.deepEqual(scopedStartFailure(failed({ stderr: Buffer.alloc(0), status: 1 })), { tool: 'systemd-run', detail: 'exit 1, nothing on stderr' });
  assert.deepEqual(scopedStartFailure(failed({ stderr: null, status: 3 })), { tool: 'systemd-run', detail: 'exit 3, nothing on stderr' });
  assert.deepEqual(scopedStartFailure(failed({ stderr: Buffer.from('\n  \n'), status: 2 })), { tool: 'systemd-run', detail: 'exit 2, nothing on stderr' });
});

test('a timeout or a signal with nothing on stderr says so; a stderr line wins over either', () => {
  assert.equal(scopedStartFailure(failed({ code: 'ETIMEDOUT', status: null, signal: 'SIGTERM', stderr: Buffer.alloc(0) })).detail, 'timed out after 5 s');
  assert.equal(scopedStartFailure(failed({ status: null, signal: 'SIGKILL', stderr: Buffer.alloc(0) })).detail, 'killed by SIGKILL');
  assert.equal(scopedStartFailure(failed({ code: 'ETIMEDOUT', status: null, signal: 'SIGTERM', stderr: Buffer.from('Failed to connect to bus\n') })).detail, 'Failed to connect to bus');
});

test("a spawn error (no exit at all): the error's own first line, systemd-run named", () => {
  const e = Object.assign(new Error('spawnSync systemd-run ENOENT'), { code: 'ENOENT', status: null, signal: null, stderr: null });
  assert.deepEqual(scopedStartFailure(e), { tool: 'systemd-run', detail: 'spawnSync systemd-run ENOENT' });
  assert.deepEqual(scopedStartFailure(null), { tool: 'systemd-run', detail: 'null' });
});

// Where the server sits after the bare call, read from its cgroup — never predicted. The old line after a
// scoped failure always said "without a scope … a service restart will take it down"; on a scoped call
// that timed out the server was already up inside the scope (systemd-run exec'd the client in place; the
// timeout killed the client, not the daemon it forked), and after a service restart an earlier manager's
// scope may still hold the server while systemd-run fails this time. Both predicted a loss that would not
// happen.
const UNSCOPED_LINE = 'tmux server ensured without a scope — under the service, a service restart will take it down';

test('placementFromCgroup: a romp-tmux scope on the path is scoped, named; anything else is unscoped', () => {
  assert.deepEqual(placementFromCgroup('0::/user.slice/user-1000.slice/user@1000.service/app.slice/romp-tmux-1725000000000.scope\n'),
    { placement: 'scoped', unit: 'romp-tmux-1725000000000.scope' });
  assert.deepEqual(placementFromCgroup('0::/user.slice/user-1000.slice/user@1000.service/app.slice/romp-manager.service\n'),
    { placement: 'unscoped' });
  assert.deepEqual(placementFromCgroup('0::/init.scope\n'), { placement: 'unscoped' }, "pid 1's cgroup: the bats fake's answer");
});

test('placementFromCgroup: cgroup v1 is one line per controller, each ending in the unit — every line is tried', () => {
  const v1 = '12:pids:/user.slice/user-1000.slice/user@1000.service/romp-tmux-7.scope\n'
    + '3:cpu,cpuacct:/user.slice/user-1000.slice/user@1000.service/romp-tmux-7.scope\n'
    + '1:name=systemd:/user.slice/user-1000.slice/user@1000.service/romp-tmux-7.scope\n';
  assert.deepEqual(placementFromCgroup(v1), { placement: 'scoped', unit: 'romp-tmux-7.scope' });
});

test("placementFromCgroup: a session's romp-session scope is not the manager's claim; an empty file is unknown", () => {
  assert.deepEqual(placementFromCgroup('0::/user.slice/user-1000.slice/user@1000.service/app.slice/romp-session-11111111-2222-3333-4444-555555555555.scope\n'),
    { placement: 'unscoped' });
  assert.deepEqual(placementFromCgroup(''), { placement: 'unknown', why: 'empty cgroup file' });
  assert.deepEqual(placementFromCgroup('\n  \n'), { placement: 'unknown', why: 'empty cgroup file' });
});

test("tmuxServerPlacement asks for the server pid, then reads THAT pid's cgroup", () => {
  const read = [];
  const r = tmuxServerPlacement({ serverPid: () => '4242\n', readCgroup: (pid) => { read.push(pid); return '0::/app.slice/romp-tmux-9.scope\n'; } });
  assert.deepEqual(r, { placement: 'scoped', unit: 'romp-tmux-9.scope' });
  assert.deepEqual(read, ['4242'], 'the pid as tmux printed it, trimmed');
});

test('tmuxServerPlacement never throws: every failure of the probe is unknown, with its first line as the why', () => {
  const noServer = Object.assign(new Error('Command failed: tmux display-message -p #{pid}'),
                                 { status: 1, stderr: Buffer.from('no server running on /nonexistent/tmux-0/default\n') });
  assert.deepEqual(tmuxServerPlacement({ serverPid: () => { throw noServer; } }),
    { placement: 'unknown', why: 'no server running on /nonexistent/tmux-0/default' });
  const timedOut = Object.assign(new Error('spawnSync tmux ETIMEDOUT'), { code: 'ETIMEDOUT', stderr: Buffer.alloc(0) });
  assert.deepEqual(tmuxServerPlacement({ serverPid: () => { throw timedOut; } }),
    { placement: 'unknown', why: 'spawnSync tmux ETIMEDOUT' }, "nothing on stderr: the error's own first line");
  assert.deepEqual(tmuxServerPlacement({ serverPid: () => '' }), { placement: 'unknown', why: 'tmux reported no server pid' });
  assert.deepEqual(tmuxServerPlacement({ serverPid: () => 'abc' }), { placement: 'unknown', why: 'tmux reported no server pid' });
  const gone = Object.assign(new Error("ENOENT: no such file or directory, open '/proc/4242/cgroup'"), { code: 'ENOENT' });
  assert.deepEqual(tmuxServerPlacement({ serverPid: () => '4242', readCgroup: () => { throw gone; } }),
    { placement: 'unknown', why: "ENOENT: no such file or directory, open '/proc/4242/cgroup'" });
  const long = Object.assign(new Error('x'), { stderr: Buffer.from('no server ' + 'y'.repeat(500)) });
  const { why } = tmuxServerPlacement({ serverPid: () => { throw long; } });
  assert.equal(why.length, 200);
  assert.ok(why.endsWith('…'), 'bounded like the failure line');
});

test('bareEnsuredLine: unscoped is the line as it always was, byte for byte', () => {
  assert.equal(bareEnsuredLine({ placement: 'unscoped' }), UNSCOPED_LINE);
});

test('bareEnsuredLine: a scoped server names its unit and predicts no loss', () => {
  const line = bareEnsuredLine({ placement: 'scoped', unit: 'romp-tmux-1725000000000.scope' });
  assert.ok(line.startsWith('tmux server ensured'), line);
  assert.ok(line.includes('romp-tmux-1725000000000.scope'), 'the unit that holds it');
  assert.ok(line.includes('leaves it'), 'a restart leaves it alive');
  assert.ok(!line.includes('will take it down') && !line.includes('without a scope'), 'no prediction of a loss');
});

test('bareEnsuredLine: an unreadable placement says so, carries the why, and predicts no loss', () => {
  const line = bareEnsuredLine({ placement: 'unknown', why: 'no server running on /nonexistent/tmux-0/default' });
  assert.ok(line.startsWith('tmux server ensured'), line);
  assert.ok(line.includes('could not be read (no server running on /nonexistent/tmux-0/default)'), line);
  assert.ok(!line.includes('will take it down') && !line.includes('without a scope'), 'no prediction of a loss');
});

test('the probe is tmux display-message -p #{pid}: the server pid, and no server started when there is none', () => {
  assert.deepEqual(TMUX_SERVER_PID_ARGV, ['tmux', 'display-message', '-p', '#{pid}']);
});
