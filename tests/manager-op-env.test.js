// romp-manager's tmux server start environment (2026-09-08): romp holds no API key and runs no secret-manager
// CLI, so the manager hands `tmux start-server` its environment UNCHANGED (withoutOpCredentials is a plain copy;
// the provider-gated scrub is retired with the providers). What guards the panes instead is the refusal to start
// at all while the environment carries a retired provider variable: every pane the server creates inherits the
// SERVER's globals, and a `romp new -t` session's `exec claude` would read a leftover ANTHROPIC_API_KEY from there
// while the kernel alone refused to boot. Synthetic values throughout.
// Run: node --test tests/manager-*.test.js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

process.env.ROMP_STATE_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'romp-mgr-op-env-'));
const mgr = require(path.join(__dirname, '..', 'bin', 'romp-manager'));
const { withoutOpCredentials, retiredCredentialNames, retiredCredentialMessage } = mgr;

const ENV = { PATH: '/usr/bin', HOME: '/nonexistent', ANTHROPIC_AUTH_TOKEN: 'synthetic-bearer', OP_ACCOUNT: 'acct',
              ROMP_EXPECTED_AUTH: 'key' };

test('the tmux start environment is a plain copy: nothing scrubbed, nothing mutated', () => {
  const out = withoutOpCredentials(ENV);
  assert.deepEqual(out, ENV);
  assert.notStrictEqual(out, ENV, 'a copy, so a caller cannot mutate the manager environment through it');
  assert.equal(mgr.serviceEnvHasRef, undefined, 'the provider-file reader is retired with the providers');
});

test('a retired provider variable in the environment is named, never valued, and refuses the start', () => {
  assert.deepEqual(retiredCredentialNames(ENV), [], 'the declaration and a login token are not retired names');
  for (const name of ['ROMP_API_KEY_CMD', 'ROMP_API_KEY_REF', 'ANTHROPIC_API_KEY']) {
    const found = retiredCredentialNames({ ...ENV, [name]: 'synthetic-value-never-printed' });
    assert.deepEqual(found, [name]);
    const msg = retiredCredentialMessage(found);
    assert.match(msg, /did NOT start/);
    assert.match(msg, new RegExp(name));
    assert.match(msg, /apiKeyHelper/);
    assert.match(msg, /ROMP_EXPECTED_AUTH=key/);
    assert.doesNotMatch(msg, /synthetic-value/, 'names and files only, never a value');
  }
  assert.deepEqual(retiredCredentialNames({ ...ENV, ANTHROPIC_API_KEY: '', ROMP_API_KEY_REF: 'op://v/i/f' }),
                   ['ROMP_API_KEY_REF', 'ANTHROPIC_API_KEY'], 'an empty value is still the variable');
});

test('startManager refuses before the tmux server starts (source pin: the check is its first statement)', () => {
  const src = fs.readFileSync(path.join(__dirname, '..', 'bin', 'romp-manager'), 'utf8');
  const body = src.slice(src.indexOf('function startManager() {'));
  const check = body.indexOf('retiredCredentialNames(process.env)');
  const tmux = body.indexOf('startTmuxServer();');
  assert.ok(check > 0 && tmux > 0 && check < tmux, 'the refusal runs before startTmuxServer()');
  assert.ok(body.slice(check, tmux).includes('process.exit(1)'), 'and it exits rather than warns');
});
