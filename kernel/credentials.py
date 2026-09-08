#!/usr/bin/env python3
"""romp holds no API key. This module is the whole of romp's contact with API credentials since
2026-09-08 (the user, after a contributor PR's test printed a key from a session's environment: remove
whatever let a less secure key path exist, and keep only the most secure one):

- Sessions and judge children authenticate through Claude Code's OWN credential resolution. The user
  configures `apiKeyHelper` in Claude Code's settings; the CLI runs it and holds the key. A login-billed
  launch gets `"apiKeyHelper": ""` in its per-session settings layer (the SDK's settings option, the
  CLI's --settings), which disables the helper for that one process: verified on Claude Code 2.1.257
  with a marker-writing fixture helper, the --settings layer outranks the settings files for the same
  key, and the empty string is the value that disables it (null falls through to the files).
- The kernel's own two API calls (the model catalog, the fast-mode org probe) read the same
  `apiKeyHelper` from the same settings files, in Claude Code's own precedence, and run it in-process
  (helper_key). The value lives in process memory for the helper's TTL and goes to the one request that
  asked; it is never written to an environment variable, a file or a log line.
- The retired providers (a ROMP_API_KEY_CMD command, a ROMP_API_KEY_REF 1Password reference, an
  ANTHROPIC_API_KEY= line in service.env, the service.env.source marker) and a key in the kernel's own
  environment are a boot FAILURE with migration text (check_boot_environment): a key romp holds is a key
  a session can print.

stdlib only, loaded by path as `romp_credentials` from the kernel, the SDK backend and the judges."""
import json
import os
import subprocess
import sys
import threading
import time

# The provider variables romp used to read. Any of them in service.env or in the kernel's environment
# stops the kernel at boot (check_boot_environment); the names are the whole of what the check ever says.
RETIRED_VARS = ("ROMP_API_KEY_CMD", "ROMP_API_KEY_REF", "ANTHROPIC_API_KEY")
RETIRED_MARKER_SUFFIX = ".source"           # service.env.source: the retired provider marker beside the file
# Login credentials the kernel claims out of its own environment at startup and hands back to a
# login-billed launch only (sdk_backend.startup_auth_env). Not key material; unchanged by the retirement.
LOGIN_TOKEN_VARS = ("ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
# The 1Password CLI's own names. romp no longer runs `op`, so it neither claims nor forwards them; the
# judges still keep them out of their children (a service-account token reads every field the account
# can see), and the test floor keeps them out of every test's environment.
OP_ENV_NAMES = ("OP_SERVICE_ACCOUNT_TOKEN", "OP_CONNECT_HOST", "OP_CONNECT_TOKEN", "OP_ACCOUNT")
OP_ENV_PREFIX = "OP_SESSION_"
# What tests/conftest.py pops out of every test's environment before any romp module loads, pinned by
# tests/test_key_source_floor.py: no test may see a real credential or a real declaration.
FLOOR_ENV_NAMES = RETIRED_VARS + LOGIN_TOKEN_VARS + ("ROMP_EXPECTED_AUTH",) + OP_ENV_NAMES
FLOOR_ENV_PREFIXES = (OP_ENV_PREFIX,)

HELPER_KEY = "apiKeyHelper"
HELPER_TTL_VAR = "CLAUDE_CODE_API_KEY_HELPER_TTL_MS"      # the CLI's own refresh interval, in milliseconds
HELPER_TTL_DEFAULT_MS = 300_000                          # five minutes: the CLI's documented default
HELPER_TIMEOUT_S = 15
# The environment the helper runs with, and nothing more (a whitelist, never a copy: the kernel's
# environment carries the serve token, full control of every session, which no third-party script may
# see). PATH to run, HOME and CLAUDE_CONFIG_DIR and the XDG names to find its own config, the rest for
# ordinary command-line behaviour. A helper that needs a credential of its own reads it from a file.
HELPER_ENV_PASSTHROUGH = ("PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "TERM",
                          "CLAUDE_CONFIG_DIR")
HELPER_ENV_PREFIXES = ("LC_", "XDG_")
# Claude Code's managed settings, the top of its precedence: one path per platform (its documentation).
MANAGED_SETTINGS = {"darwin": "/Library/Application Support/ClaudeCode/managed-settings.json"}
MANAGED_SETTINGS_DEFAULT = "/etc/claude-code/managed-settings.json"


class CredentialError(Exception):
    """A helper that did not produce a key, or a settings file that could not be read, said in STATIC
    words plus at most a file path: no helper output ever rides the message (stderr is discarded, stdout
    is the key), so quoting one names no value."""


# ---------------------------------------------------------------------------
# The service environment file (ROMP_EXPECTED_AUTH and service knobs; never a key)
# ---------------------------------------------------------------------------

def service_env_path() -> str:
    """The path of the env file the manager is configured from. `ROMP_SERVICE_ENV_FILE` is the name the
    installer and the macOS launcher use (`bin/romp-service`, `bin/romp-node-launch`), so it is the
    primary; `ROMP_SERVICE_ENV` is accepted as an alias. Default `${XDG_CONFIG_HOME:-~/.config}/romp/
    service.env`, the same expression those two scripts compute, so all three always name one file."""
    for var in ("ROMP_SERVICE_ENV_FILE", "ROMP_SERVICE_ENV"):
        p = (os.environ.get(var) or "").strip()
        if p:
            return os.path.expanduser(p)
    base = (os.environ.get("XDG_CONFIG_HOME") or "").strip() or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "romp", "service.env")


def env_file_assignments(text, names) -> dict:
    """The literal NAME=VALUE assignments in an env file's text for the given names: the last assignment
    wins, one layer of matching quotes is stripped (systemd strips one too), comments and blank lines are
    skipped. Never sourced, never expanded."""
    out = {}
    want = set(names)
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or name not in want:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[name] = value
    return out


def retired_in_env_file(path=None) -> list:
    """The retired provider NAMES a service.env still assigns (an empty value counts: the line is what the
    migration removes). [] for a missing file. An unreadable file is a boot failure in its own words."""
    p = path or service_env_path()
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        return []
    except OSError as e:
        raise RuntimeError("%s: cannot read the service environment file (%s). romp did NOT start. Fix the "
                           "file's permissions, then start again." % (p, e.__class__.__name__))
    found = env_file_assignments(text, RETIRED_VARS)
    return [n for n in RETIRED_VARS if n in found]


def check_boot_environment(path=None, environ=None) -> None:
    """Stop the kernel BEFORE anything is spawned when a retired key path is still configured: a retired
    variable in service.env, the provider marker beside it, or a retired variable in the kernel's own
    environment (the SDK's transport hands every session this process's environment, so a key there
    would bill every session and could be printed by any of them). RuntimeError in the shape the
    serve-token read uses (kernel._serve_token_read_or_mint): what was found, what romp did NOT do, the
    fix, then start again. Variable NAMES and paths only, never a value."""
    p = path or service_env_path()
    env = os.environ if environ is None else environ
    in_file = retired_in_env_file(p)
    marker = p + RETIRED_MARKER_SUFFIX
    has_marker = os.path.exists(marker)
    in_env = [n for n in RETIRED_VARS if n in env]
    if not (in_file or has_marker or in_env):
        return
    found = []
    if in_file:
        found.append("%s carries %s" % (p, ", ".join(in_file)))
    if has_marker:
        found.append("%s (the retired provider marker) exists" % marker)
    if in_env:
        found.append("the manager's environment carries %s" % ", ".join(in_env))
    several = (len(in_file) + len(in_env) + int(has_marker)) > 1
    raise RuntimeError(
        "%s. romp no longer holds an API key (a key romp holds is a key a session can print), so romp did NOT "
        "start. Remove %s, configure apiKeyHelper in Claude Code's settings (%s: {\"apiKeyHelper\": \"<a script "
        "that prints the key>\"}), declare the billing with ROMP_EXPECTED_AUTH=key in %s, then start again."
        % ("; ".join(found), "them" if several else "it", os.path.join(claude_config_dir(), "settings.json"), p))


# ---------------------------------------------------------------------------
# Claude Code's settings and its apiKeyHelper
# ---------------------------------------------------------------------------

def claude_config_dir() -> str:
    """Where Claude Code keeps its user settings: $CLAUDE_CONFIG_DIR, else ~/.claude (its documentation)."""
    return os.path.expanduser((os.environ.get("CLAUDE_CONFIG_DIR") or "").strip() or "~/.claude")


def managed_settings_path() -> str:
    return MANAGED_SETTINGS.get(sys.platform, MANAGED_SETTINGS_DEFAULT)


def settings_files(cwd=None) -> list:
    """The settings files a `claude` launched in `cwd` reads, highest precedence first, in Claude Code's own
    order: managed settings, the project's local file, the project's shared file, the user's file. The
    per-session --settings layer (sdk_backend.flag_settings_path) sits between the first two and is romp's
    own, so it is not listed here."""
    cwd = os.path.realpath(cwd or os.getcwd())
    return [managed_settings_path(),
            os.path.join(cwd, ".claude", "settings.local.json"),
            os.path.join(cwd, ".claude", "settings.json"),
            os.path.join(claude_config_dir(), "settings.json")]


def _read_settings(path):
    """One settings file as a dict; None when absent. Unreadable or unparsable is loud: the CLI would refuse
    it too, and a silently skipped file would misreport the box as helper-less."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return None
    except OSError:
        raise CredentialError("Claude Code settings file cannot be read: %s" % path)
    try:
        d = json.loads(text)
    except ValueError:
        raise CredentialError("Claude Code settings file is not valid JSON: %s" % path)
    return d if isinstance(d, dict) else {}


def api_key_helper(cwd=None):
    """The `apiKeyHelper` command Claude Code would run for a process in `cwd`: the value in the
    highest-precedence settings file that DEFINES it as a string. "" when that file sets it to "" (the
    value that disables the helper; a login launch's per-session layer uses it), None when no file defines
    it (a null falls through to the next file, as it does in the CLI). Read fresh on every call, never
    cached: Claude Code hot-reloads its settings files, and a helper the user just added must count at
    once; the cost is four stats."""
    for p in settings_files(cwd):
        d = _read_settings(p)
        if d is None or HELPER_KEY not in d:
            continue
        v = d.get(HELPER_KEY)
        if isinstance(v, str):
            return v.strip()
    return None


def key_available(cwd=None) -> bool:
    """Whether a session launched in `cwd` bills the key by Claude Code's own resolution: an apiKeyHelper is
    configured there. Read, never run."""
    return bool(api_key_helper(cwd))


def helper_ttl_s() -> float:
    raw = (os.environ.get(HELPER_TTL_VAR) or "").strip()
    try:
        ms = int(raw) if raw else HELPER_TTL_DEFAULT_MS
    except ValueError:
        ms = HELPER_TTL_DEFAULT_MS
    return max(0, ms) / 1000.0


def helper_env() -> dict:
    return {k: v for k, v in os.environ.items()
            if k in HELPER_ENV_PASSTHROUGH or k.startswith(HELPER_ENV_PREFIXES)}


def run_helper(cmd) -> str:
    """Run the helper once, the way Claude Code runs it: through /bin/sh, stdin /dev/null (a prompt would
    hang until the timeout), stderr discarded and never logged (a secret manager's diagnostics can quote
    its own token), stdout the key: non-empty, one line, no whitespace, at most 16 KiB, one trailing
    newline forgiven (a script's echo adds one). Every failure is a CredentialError in static words."""
    try:
        r = subprocess.run(cmd, shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=HELPER_TIMEOUT_S, check=False, env=helper_env())
    except FileNotFoundError:
        raise CredentialError("apiKeyHelper could not run: /bin/sh is not available") from None
    except subprocess.TimeoutExpired:
        raise CredentialError("apiKeyHelper timed out after %d s" % HELPER_TIMEOUT_S) from None
    except OSError:
        raise CredentialError("apiKeyHelper could not be run") from None
    if r.returncode:
        raise CredentialError("apiKeyHelper is not on the manager's PATH (exit 127)" if r.returncode == 127
                              else "apiKeyHelper failed (non-zero exit)")
    try:
        value = r.stdout.decode("utf-8")
    except UnicodeError:
        raise CredentialError("apiKeyHelper printed bytes that are not a key") from None
    if value.endswith("\n"):
        value = value[:-2] if value.endswith("\r\n") else value[:-1]
    if not value or len(value) > 16384 or any(c.isspace() or c == "\0" for c in value):
        raise CredentialError("apiKeyHelper printed an empty or invalid key (one line on stdout, exit 0)")
    return value


_HELPER_LOCK = threading.Lock()
_HELPER_MEMO = {"cmd": None, "value": "", "at": 0.0}    # in process memory only; forget_helper_key drops it


def helper_key(cwd=None, now=None) -> str:
    """The key Claude Code's configured helper prints, for the kernel's OWN API calls (the model catalog,
    the fast-mode org probe). "" when no helper is configured, so the caller says so in its own words.
    Memoized in process memory for the helper's TTL (CLAUDE_CODE_API_KEY_HELPER_TTL_MS, five minutes by
    default, the CLI's own interval) keyed on the helper command: a changed helper re-runs at once, a
    rotated vault item is picked up within the TTL. `now` is a monotonic clock, injectable by tests."""
    cmd = api_key_helper(cwd)
    if not cmd:
        return ""
    now = time.monotonic() if now is None else now
    with _HELPER_LOCK:
        m = _HELPER_MEMO
        if m["cmd"] == cmd and m["value"] and now - m["at"] < helper_ttl_s():
            return m["value"]
    value = run_helper(cmd)
    with _HELPER_LOCK:
        _HELPER_MEMO.update(cmd=cmd, value=value, at=now)
    return value


def forget_helper_key() -> None:
    with _HELPER_LOCK:
        _HELPER_MEMO.update(cmd=None, value="", at=0.0)
