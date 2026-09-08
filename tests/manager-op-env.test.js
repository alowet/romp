// romp-manager's tmux server start environment and credentials (2026-09-05, extended 2026-09-06): every pane
// the server ever creates inherits the SERVER's globals, so what the manager hands `tmux start-server` is
// what every terminal session's `exec claude` sees. withoutOpCredentials drops op's own credential names
// and the manager's startup ANTHROPIC_API_KEY — but only when a key PROVIDER is configured (a key command,
// ROMP_API_KEY_CMD, since 2026-09-07; or a 1Password reference, ROMP_API_KEY_REF), in the manager's
// environment OR as a line of the service env file (what `romp keyswap` rewrites with no manager restart).
// A box with no provider keeps everything: static-key panes rely on the inheritance, and an apiKeyHelper
// box's sessions need op's environment. Synthetic values throughout.
// Run: node --test tests/manager-*.test.js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

process.env.ROMP_STATE_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'romp-mgr-op-env-'));
const { withoutOpCredentials, serviceEnvHasRef } = require(path.join(__dirname, '..', 'bin', 'romp-manager'));

const REF = 'op://test-vault/test-item/credential';
const STALE = {
  OP_SERVICE_ACCOUNT_TOKEN: 'synthetic-op-token', OP_SESSION_acct: 'synthetic-session', OP_ACCOUNT: 'acct',
  OP_CONNECT_HOST: 'h', OP_CONNECT_TOKEN: 't', ANTHROPIC_API_KEY: 'synthetic-stale-key',
  ANTHROPIC_AUTH_TOKEN: 'synthetic-bearer', PATH: '/usr/bin', HOME: '/nonexistent',
};
const CREDS = ['OP_SERVICE_ACCOUNT_TOKEN', 'OP_SESSION_acct', 'OP_ACCOUNT', 'OP_CONNECT_HOST', 'OP_CONNECT_TOKEN', 'ANTHROPIC_API_KEY'];
const envFile = (body) => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'romp-mgr-op-env-file-'));
  const f = path.join(d, 'service.env');
  if (body !== null) fs.writeFileSync(f, body, { mode: 0o600 });
  return f;
};

test('a reference in the manager environment: op names and ANTHROPIC_API_KEY leave the tmux start env', () => {
  const out = withoutOpCredentials({ ...STALE, ROMP_API_KEY_REF: REF, ROMP_SERVICE_ENV_FILE: envFile(null) });
  for (const k of CREDS) assert.equal(out[k], undefined, k);
  assert.equal(out.ANTHROPIC_AUTH_TOKEN, 'synthetic-bearer', 'a login token is not the key source; it stays');
  assert.equal(out.PATH, '/usr/bin'); assert.equal(out.HOME, '/nonexistent');
  assert.equal(STALE.OP_SERVICE_ACCOUNT_TOKEN, 'synthetic-op-token', 'the input is not mutated');
});

test('a reference in the env FILE alone (a keyswap with no restart) scrubs the same names', () => {
  const f = envFile('# service env\nROMP_PERF=1\n  ROMP_API_KEY_REF=' + REF + '\n');
  assert.equal(serviceEnvHasRef({ ROMP_SERVICE_ENV_FILE: f }), true);
  const out = withoutOpCredentials({ ...STALE, ROMP_SERVICE_ENV_FILE: f });
  for (const k of CREDS) assert.equal(out[k], undefined, k);
});

test('no reference anywhere: the environment is handed over untouched (static-key and helper boxes)', () => {
  const f = envFile('ANTHROPIC_API_KEY=synthetic-static-key\nROMP_PERF=1\n# ROMP_API_KEY_REF=' + REF + ' (a comment is not a line)\n');
  assert.equal(serviceEnvHasRef({ ROMP_SERVICE_ENV_FILE: f }), false);
  assert.deepEqual(withoutOpCredentials({ ...STALE, ROMP_SERVICE_ENV_FILE: f }), { ...STALE, ROMP_SERVICE_ENV_FILE: f });
  assert.equal(serviceEnvHasRef({ ROMP_SERVICE_ENV_FILE: envFile(null) }), false, 'no file: no reference');
});

test('a key command (ROMP_API_KEY_CMD) is a provider too: in the manager environment or the env file', () => {
  const CMD = 'fetch-synthetic-key --field api';
  let out = withoutOpCredentials({ ...STALE, ROMP_API_KEY_CMD: CMD, ROMP_SERVICE_ENV_FILE: envFile(null) });
  for (const k of CREDS) assert.equal(out[k], undefined, k);
  assert.equal(out.ANTHROPIC_AUTH_TOKEN, 'synthetic-bearer');
  const f = envFile('ROMP_PERF=1\nROMP_API_KEY_CMD=' + CMD + '\n');
  assert.equal(serviceEnvHasRef({ ROMP_SERVICE_ENV_FILE: f }), true);
  out = withoutOpCredentials({ ...STALE, ROMP_SERVICE_ENV_FILE: f });
  for (const k of CREDS) assert.equal(out[k], undefined, k);
  assert.equal(serviceEnvHasRef({ ROMP_SERVICE_ENV_FILE: envFile('# ROMP_API_KEY_CMD=' + CMD + '\n') }), false, 'a comment is not a line');
});

test('the file is found the way the launchers find it: ROMP_SERVICE_ENV_FILE, then the alias, then XDG', () => {
  const f = envFile('ROMP_API_KEY_REF=' + REF + '\n');
  assert.equal(serviceEnvHasRef({ ROMP_SERVICE_ENV: f }), true);
  const xdg = fs.mkdtempSync(path.join(os.tmpdir(), 'romp-mgr-op-env-xdg-'));
  fs.mkdirSync(path.join(xdg, 'romp'));
  fs.writeFileSync(path.join(xdg, 'romp', 'service.env'), 'ROMP_API_KEY_REF=' + REF + '\n');
  assert.equal(serviceEnvHasRef({ XDG_CONFIG_HOME: xdg }), true);
  assert.equal(serviceEnvHasRef({ XDG_CONFIG_HOME: xdg, ROMP_SERVICE_ENV_FILE: envFile('ROMP_PERF=1\n') }), false, 'the override wins');
});
