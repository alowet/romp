"""Global test isolation (2026-07-07): point XDG_STATE_HOME at a fresh temp dir BEFORE any test module
loads bin/romp-judge or bin/romp-kernel — both resolve their state root at import time. Without this,
any test that skips its own rebind writes into the REAL ~/.local/state/romp (the diary guard's
judge-errors.jsonl lines from legacy-flag fixtures made that visible). conftest.py imports before every
test module, so this is a suite-wide floor; per-class _rebind_state/tempdir isolation still layers on
top exactly as before."""
import atexit
import os
import shutil
import sys
import tempfile

import pytest

# Temp-directory hygiene, the child-process half (2026-09-06): every temp path a run creates lives
# under ONE private root, removed when the run ends. tests/__init__.py's mkdtemp hook (the other
# half; its comment has the leak's history) records and removes what THIS process mints through
# tempfile.mkdtemp, but a test's children — kernels, git, `mktemp -d` in a shell — and mkstemp or
# os.mkdir paths are outside its sight (a full run left ~5,600 of those per run at up to ten a
# second). So the process's temp dir is redirected: tempfile.tempdir is set directly (gettempdir()
# caches its first answer, and tests/__init__.py has already called it by the time this runs), and
# TMPDIR is exported so every child inherits the same root. Import-time, not pytest_configure: this
# module's own XDG floor below and every module-level mkdtemp at collection must land inside it.
# The two removals compose without overlap: pytest_sessionfinish runs the hook's sweep, whose scope
# is gettempdir() and so the inside of this root; pytest_unconfigure then removes the root whole
# (whatever the sweep could not see) and tests/__init__.py's romp-tests-state-* dir — the package
# imports first, so that dir and this root were minted before the redirect and are the two things a
# run puts outside the root; the hook recorded both but skips them as outside its scope. Under
# pytest-xdist both hooks run in the controller and in every worker: each imported this file and so
# owns a root of its own (a worker's sits inside the controller's, since it inherits that TMPDIR).
# The atexit registrations are silent fallbacks for a normal exit that skipped the hooks, each a
# no-op on what the other removed; nothing runs after an os._exit (pytest-timeout's thread method
# ends a hung run that way), so a hang leaves two top-level entries in the system temp dir, this
# root and that state dir, both under the romp-tests- prefix.
# The system temp dir — the one the RUN was handed, before any redirect — is recorded once, by the
# first conftest to import: an xdist worker inherits the controller's record along with its TMPDIR
# (setdefault, not an assignment: a worker's own gettempdir() is the controller's root, and
# recording that put the worker's fallback one level deeper than a socket path can bear under a
# long TMPDIR — four socket tests failed at bind under -n 2). A test that must leave the root (an
# AF_UNIX socket path that would not fit sun_path under a nested root) falls back to it, and only
# to it — a literal system path in a `dir=` would bypass the redirect (one did).
os.environ.setdefault("ROMP_TESTS_SYSTEM_TMPDIR", tempfile.gettempdir())
_TMP_ROOT = tempfile.mkdtemp(prefix="romp-tests-")
tempfile.tempdir = _TMP_ROOT
os.environ["TMPDIR"] = _TMP_ROOT
_PACKAGE_STATE_DIR = getattr(sys.modules.get("tests"), "STATE_DIR", None)


def _remove_run_dirs(report=False):
    """Remove the root and the package state dir. A survivor is named on stderr when asked: rmtree
    with ignore_errors swallows a child still writing under the root or a 000-mode directory a test
    left behind, and the run would otherwise end green with the root standing. Only unconfigure
    asks; the atexit fallback stays silent so it neither repeats the notice nor contradicts it."""
    for d in (_TMP_ROOT, _PACKAGE_STATE_DIR):
        if d:
            shutil.rmtree(d, ignore_errors=True)
            if report and os.path.isdir(d):
                print("[tests] not removed at run end: %s" % d, file=sys.stderr)


atexit.register(_remove_run_dirs)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """The in-process half (tests/__init__.py): remove every directory this process made through
    tempfile.mkdtemp inside the root, this module's state root included, when the session ends. Runs
    in the controller and in every xdist worker, since each is its own pytest session, and last, after
    pytest's own runner sessionfinish has performed the deferred teardown an interrupted run leaves
    behind, so nothing is swept from under a fixture still closing. The package's atexit hook does the
    same at interpreter exit; both are idempotent, and pytest_unconfigure below takes the root itself
    afterwards."""
    try:
        from tests import remove_made_dirs
    except Exception:
        return
    remove_made_dirs()


def pytest_unconfigure(config):
    _remove_run_dirs(report=True)


os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp(prefix="romp-tests-state-")   # inside the root; the hook records it
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel exports this to its sessions; it outranks the XDG floor


# No test may reach a REAL manager control port (2026-08-27): on a machine running a live romp,
# every shell the manager tree spawns inherits ROMP_MANAGER_PORT, and any test kernel that dials
# "the manager" through the inherited value restarts the ACTUAL deployment — the serve-layer
# restart test's pop-then-restore raced the /restart handler's post-ack env read and took a
# self-hosted instance down mid-suite, repeatedly. POISONED to a dead port, never popped: an
# absent var is the one unsafe state, because _restart_this_kernel treats absent as "no manager"
# but _run_main_update maps absent to the DEFAULT port — the live one — so only a dead value is
# safe against every consumer. Import-time, so collection-time code is floored too.
os.environ["ROMP_MANAGER_PORT"] = "1"

# No test may read the REAL service.env (2026-09-04): sdk_backend.work_api_key now reads the manager
# env file LIVE (kernel/keysource.py) instead of popping os.environ once, so on a machine running a
# live romp every auth test would otherwise resolve the developer's ACTUAL API key — quietly billing
# nothing, but making the key material a test input, putting it one assertion message away from a
# terminal, and making the pinned fixture-key tests pass or fail on whether this box happens to have
# a key configured. Pointed at a path inside the temp state root that is never created, so every read
# is the "no file" case and the startup-pop fallback governs, exactly as before the live source
# existed. Both spellings, because keysource accepts both. Import-time (collection is floored too)
# plus a per-test re-assert below, on the same reasoning as the manager port.
_NO_SERVICE_ENV = os.path.join(os.environ["XDG_STATE_HOME"], "no-such-service.env")
os.environ["ROMP_SERVICE_ENV_FILE"] = _NO_SERVICE_ENV
os.environ["ROMP_SERVICE_ENV"] = _NO_SERVICE_ENV
# A runtime provider can also be selected directly from the manager's environment. Remove its
# inherited reference before module loading, so an auth test cannot resolve a developer's vault
# merely because the isolated service.env is absent. Tests set synthetic references explicitly.
os.environ.pop("ROMP_API_KEY_REF", None)
# Every shell under a romp-managed session inherits ROMP_SUPERVISED=1 from the kernel (the service
# unit exports it), and keysource gives that variable authority: a supervised manager reads the env
# file only and ignores a startup key. Twenty-five tests that stage a startup key went red when the
# suite ran from inside a romp session while CI stayed green (review find, 2026-09-05). The floor is
# the unsupervised case; a test that wants supervision sets the variable itself.
os.environ.pop("ROMP_SUPERVISED", None)


def _reset_keysource_state():
    """keysource remembers which path selected which source for the PROCESS (that is the resurrection
    guard); under one pytest process that memory would leak between test modules. Every loaded copy of
    the module (each SourceFileLoader name is its own module object) is reset."""
    import sys
    for name, m in list(sys.modules.items()):
        if "keysource" in name and hasattr(m, "_AUTHORITATIVE_PATHS"):
            m._AUTHORITATIVE_PATHS.clear()
            getattr(m, "_ENV_PROVIDER_PATHS", set()).clear()
            m._CACHE = ((), "")


@pytest.fixture(autouse=True)
def _no_real_service_env():
    """Re-asserted, not defaulted: a module-level write in one test file executes during collection
    and would otherwise hold for the whole run. A test that needs its own env file points the vars at
    a temp path in setUp, which runs AFTER this fixture (pytest fills fixtures in the item's setup
    phase, before TestCase.run calls setUp) — so per-test intent still wins."""
    for var in ("ROMP_SERVICE_ENV_FILE", "ROMP_SERVICE_ENV"):
        os.environ[var] = _NO_SERVICE_ENV
    os.environ.pop("ROMP_API_KEY_REF", None)
    os.environ.pop("ROMP_SUPERVISED", None)
    _reset_keysource_state()
    yield


@pytest.fixture(autouse=True)
def _dead_manager_port():
    """The import-time poison above covers collection, but a module-level env write in a test file
    ALSO executes during collection — so one module's write (or pop) would otherwise hold for the
    entire run phase, erasing the floor for every test after it. Re-assert per test: no
    module-level write can outlive collection against this."""
    os.environ["ROMP_MANAGER_PORT"] = "1"
    yield


# No test may reach the REAL `claude` CLI (2026-08-12): _judge_claude_bin honors ROMP_CLAUDE_BIN
# first, so this floors every judge call a test forgot to stub at /bin/false — empty stdout, the
# dead-CLI row, byte-for-byte what a claude-less CI runner produces. Found when an unstubbed
# _judge_run in the kernel suite exec'd the live CLI on a dev machine: run alone it made a real
# (billed!) model call and passed; in the full suite the process env's key had already been claimed
# by an sdk-backend construction, the live CLI refused "Not logged in", and the judge-auth latch
# that refusal now correctly feeds floored the synthetic session's cards — 25 stays-in-Working
# tests red locally, green on CI, purely machine-dependent. Tests that assert _judge_claude_bin's
# own resolution pop this var themselves (test_judge.py), as they always had to.
os.environ["ROMP_CLAUDE_BIN"] = "/bin/false"

# No test kernel may fetch the Models API (2026-09-02): the kernel's lazy _sdk() build (_sdk_locked)
# fires the T222 catalog refresh, `_refresh_model_catalog("boot")` — an async GET to
# api.anthropic.com on any credential the process carries: the manager-env key
# sdk_backend.work_api_key claimed, else a bare ANTHROPIC_API_KEY, else an ANTHROPIC_AUTH_TOKEN
# bearer. A DEFENSIVE floor: no test reached the network before this line (checked, not assumed —
# the one in-process _sdk() driver, test_kernel_headless_ops' SdkSingleFlight, runs the refresh
# inside the test process with the module loader mocked, and it stopped only because the mocked
# module's work_api_key handed http.client a credential it rejects before a socket opens), but any
# in-process _sdk() call is one exported key away from a real request no test asserts on, on a key
# the test never chose. The kernel-SPAWNING tests floor it in their subprocess env
# (test_gear_select_matrix, test_ship_reship, test_awaiting_box_sync); this floors every test,
# whatever the developer's shell exports.
# Set, not setdefault: "off" is the only value the switch recognises, so no outer intent is being
# overridden. The catalog suite unsets the var inside its own tests — FetchAndFallback pops it in
# setUp to drive the fetch against a local fake server; StalenessEvent and ModelsRoute set it in
# setUp and pop it in tearDown — leaving it absent for every test after that module in a serial
# run; hence the per-test re-assert below, on the same reasoning as the manager-port one
# (tests/test_model_catalog_floor.py pins both). Those pops still win inside their own tests:
# pytest fills every fixture, autouse included, in the item's setup phase, before runtest hands
# the case to TestCase.run(), which is what calls setUp.
os.environ["ROMP_MODEL_CATALOG"] = "off"


@pytest.fixture(autouse=True)
def _no_model_catalog_fetch():
    os.environ["ROMP_MODEL_CATALOG"] = "off"
    yield


# No test may reach the REAL `systemd-run` (2026-09-05): constructing the SDK backend decides once
# whether to spawn CLIs inside per-session transient scopes (sdk_backend.cli_scope_supported), and
# that verdict defaults to ON under the supervised service — ROMP_SUPERVISED=1 is inherited by every
# tool shell of a session running on a self-hosted romp, so a suite run from one would probe the
# live user manager at every backend construction and route every _options() through the wrapper.
# Floored to the explicit off value; the truth-table tests pass their own environ and are unaffected.
# Per-test re-assert below, on the same reasoning as the manager-port floor.
os.environ["ROMP_CLI_SCOPE"] = "0"


@pytest.fixture(autouse=True)
def _no_cli_scope():
    os.environ["ROMP_CLI_SCOPE"] = "0"
    yield


# No test may reach the machine's REAL tmux server (2026-09-06): keysource.claim_op_env scrubs the tmux
# server's globals the moment romp becomes the op consumer, which any test that configures a reference
# and constructs the SDK backend (or resolves a key) does — and on a developer's box that `tmux
# set-environment -gu` would land on the live server every session runs in. The same private socket
# directory the bats suites use (tests/tmux-private.bash): tmux puts every socket, `-L` ones included,
# under $TMUX_TMPDIR/tmux-<uid>/, and the directory must exist or tmux 3.4 silently falls back to the
# default. No server ever exists there, so a scrub from a test exits with "no server running".
os.environ["TMUX_TMPDIR"] = tempfile.mkdtemp(prefix="romp-tests-tmux-")
os.environ.pop("TMUX", None)
os.environ.pop("ROMP_TMUX_SOCKET", None)


@pytest.fixture(autouse=True)
def _no_live_tmux_server():
    os.environ["TMUX_TMPDIR"] = _TMUX_PRIVATE
    yield


_TMUX_PRIVATE = os.environ["TMUX_TMPDIR"]


@pytest.fixture(autouse=True)
def _stub_place_llm(monkeypatch):
    """Card-first placer floor (2026-07-08): every loaded romp-judge instance gets a no-op place_llm so
    no test can reach a real `claude -p` subprocess through _card_route_subs (a plan test whose mocked
    sub lands on a card with open sub-goals would otherwise fire the real second call). Placer tests
    override jd.place_llm in-body; monkeypatch restores whatever was there after each test."""
    seen = set()
    for m in list(sys.modules.values()):
        for j in (m, getattr(m, "jd", None)):
            if j is not None and id(j) not in seen and getattr(j, "_card_route_subs", None) is not None:
                seen.add(id(j))
                monkeypatch.setattr(j, "place_llm", lambda *a, **k: "")
    yield
