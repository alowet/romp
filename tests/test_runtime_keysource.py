"""Runtime credential source contract, using synthetic secrets and mocked op only.

These tests distinguish inspecting a configured reference from retrieving its value,
and exercise source removal and failure without accessing the developer's credentials.
"""
import os
import stat
import subprocess
import tempfile
import traceback
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest


ROOT = Path(__file__).resolve().parents[1]
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)
ks = SourceFileLoader(
    "romp_runtime_keysource_test", str(ROOT / "kernel" / "keysource.py")
).load_module()

REF = "op://test-vault/test-item/credential"
OTHER_REF = "op://test-vault/other-item/credential"
BOOT_KEY = "sk-ant-TEST-startup-do-not-reuse"
OLD_KEY = "sk-ant-TEST-provider-old"
NEW_KEY = "sk-ant-TEST-provider-new"
SECRET_STDERR = "TEST-sensitive-provider-stderr"


@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / "service.env"
    monkeypatch.setenv("ROMP_SERVICE_ENV_FILE", str(path))
    monkeypatch.setenv("ROMP_SERVICE_ENV", str(path))
    monkeypatch.delenv("ROMP_API_KEY_REF", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ROMP_SUPERVISED", raising=False)
    ks._CACHE = ((), "")
    ks._AUTHORITATIVE_PATHS.clear()
    ks._ENV_PROVIDER_PATHS.clear()
    ks._TMUX_SCRUBBED.clear()
    # Unexpected retrieval fails locally: no test may invoke the real executable. The tmux scrub the
    # claim runs has its own runner (keysource._TMUX_RUN, bound at import for exactly this reason):
    # recorded here, never run — no test may touch a tmux server, private socket dir or not.
    with mock.patch.object(
        ks.subprocess, "run", side_effect=AssertionError("unexpected credential retrieval")
    ) as op, mock.patch.object(ks, "_TMUX_RUN") as tmux:
        yield SimpleNamespace(path=path, root=tmp_path, op=op, tmux=tmux)
    ks._CACHE = ((), "")
    ks._AUTHORITATIVE_PATHS.clear()
    ks._ENV_PROVIDER_PATHS.clear()
    ks._TMUX_SCRUBBED.clear()


def result(value=OLD_KEY.encode(), returncode=0):
    return subprocess.CompletedProcess(
        ["op", "read", "--no-newline", REF], returncode,
        stdout=value, stderr=SECRET_STDERR.encode(),
    )


def safe_failure(call, *hidden):
    with pytest.raises(ks.KeySourceError) as caught:
        call()
    error = caught.value
    rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    for value in (OLD_KEY, NEW_KEY, BOOT_KEY, SECRET_STDERR, *hidden):
        assert value not in str(error)
        assert value not in repr(error)
        assert value not in rendered
    return error


def test_metadata_and_legacy_reader_never_retrieve_provider(env):
    env.path.write_text(f"ROMP_API_KEY_REF={REF}\n")
    source = ks.select_source(BOOT_KEY)

    assert source.kind == "op"
    assert source.configured
    source.validate()
    assert source.fingerprint()
    assert source.fingerprint() == ks.read_source().fingerprint()
    assert source == ks.parse_source(env.path.read_text())
    assert REF not in repr(source)
    assert ks.read_key() == ""
    env.op.assert_not_called()


def test_resolve_executes_literal_reference_with_bounded_noninteractive_io(env):
    # Shell syntax and spaces must stay inside one argument, never be evaluated.
    reference = "op://test vault/item;$(touch SHOULD_NOT_EXIST)/credential field"
    env.op.side_effect = None
    env.op.return_value = result()

    assert ks.KeySource("op", reference).resolve() == OLD_KEY

    args, kwargs = env.op.call_args
    assert args == (["op", "read", "--no-newline", reference],)
    assert not kwargs.get("shell", False)
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["stdout"] == subprocess.PIPE
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert 0 < kwargs["timeout"] <= 30
    assert kwargs["check"] is False
    assert not (env.root / "SHOULD_NOT_EXIST").exists()


def test_each_resolution_observes_rotation_without_caching_or_disk_writes(env):
    env.path.write_text(f"ROMP_API_KEY_REF={REF}\n")
    source = ks.select_source(BOOT_KEY)
    body = env.path.read_bytes()
    names = sorted(env.root.iterdir())
    env.op.side_effect = [result(OLD_KEY.encode()), result(NEW_KEY.encode())]

    with mock.patch.object(ks, "open", create=True, side_effect=AssertionError("disk access")), \
            mock.patch.object(ks.os, "open", side_effect=AssertionError("disk access")), \
            mock.patch.object(ks.tempfile, "mkstemp", side_effect=AssertionError("disk access")):
        assert source.resolve() == OLD_KEY
        assert source.resolve() == NEW_KEY

    assert env.op.call_count == 2
    assert env.path.read_bytes() == body
    assert sorted(env.root.iterdir()) == names
    assert ks._CACHE[1].value == REF
    assert source.value == REF
    assert all(key not in repr(vars(ks)) for key in (OLD_KEY, NEW_KEY))


@pytest.mark.parametrize("provider_failure", ["nonzero", "missing", "timeout", "oserror"])
def test_provider_failures_are_safe_credential_errors(env, provider_failure):
    env.op.side_effect = None
    if provider_failure == "nonzero":
        env.op.return_value = result(returncode=1)
    elif provider_failure == "missing":
        env.op.side_effect = FileNotFoundError(SECRET_STDERR)
    elif provider_failure == "timeout":
        env.op.side_effect = subprocess.TimeoutExpired(
            ["op", "read", REF], 15, output=OLD_KEY.encode(), stderr=SECRET_STDERR.encode()
        )
    else:
        env.op.side_effect = OSError(SECRET_STDERR)

    safe_failure(ks.KeySource("op", REF).resolve)
    assert env.op.call_count == 1


@pytest.mark.parametrize("value", [
    b"", b"\n", OLD_KEY.encode() + b"\n", OLD_KEY.encode() + b"\nsecond-line",
    OLD_KEY.encode() + b"\x00", OLD_KEY.encode() + b" trailing-space",
    b"\xff\xfe", b"x" * 16385,
])
def test_empty_malformed_or_oversized_provider_output_fails_safely(env, value):
    env.op.side_effect = None
    env.op.return_value = result(value)
    safe_failure(ks.KeySource("op", REF).resolve)


@pytest.mark.parametrize("reference", [
    "", "not-a-reference", "op://", "op://vault/item", "op://vault//field",
    "op://vault/item/", "op://vault/item/section/field/extra",
    "op://vault/item/field\nPRIVATE_REF_MARKER", "op://vault/item/field\0PRIVATE_REF_MARKER",
])
def test_invalid_reference_never_runs_op_and_does_not_echo_input(env, reference):
    source = ks.KeySource("op", reference)
    assert source.configured  # Invalid explicit configuration cannot become login mode.
    safe_failure(source.resolve, "PRIVATE_REF_MARKER")
    env.op.assert_not_called()


@pytest.mark.parametrize("body", [
    f"ANTHROPIC_API_KEY={BOOT_KEY}\nROMP_API_KEY_REF={REF}\n",
    f"ROMP_API_KEY_REF={REF}\nANTHROPIC_API_KEY={BOOT_KEY}\n",
])
def test_file_provider_wins_both_file_and_ambient_legacy_key(env, monkeypatch, body):
    monkeypatch.setenv("ANTHROPIC_API_KEY", BOOT_KEY)
    env.path.write_text(body)
    source = ks.select_source(BOOT_KEY)
    assert (source.kind, source.value) == ("op", REF)
    env.op.assert_not_called()


def test_foreground_provider_wins_ambient_legacy_key(env, monkeypatch):
    monkeypatch.setenv("ROMP_API_KEY_REF", REF)
    monkeypatch.setenv("ANTHROPIC_API_KEY", BOOT_KEY)
    source = ks.select_source(BOOT_KEY)
    assert (source.kind, source.value) == ("op", REF)
    env.op.assert_not_called()


@pytest.mark.parametrize("startup_key", ["", BOOT_KEY])
def test_removing_foreground_provider_cannot_become_login_or_ambient_key(env, monkeypatch, startup_key):
    monkeypatch.setenv("ROMP_API_KEY_REF", REF)
    assert ks.select_source(startup_key).kind == "op"
    # Remembering selection must not block subsequent reads while it remains configured.
    assert ks.select_source(startup_key).value == REF
    monkeypatch.delenv("ROMP_API_KEY_REF")

    source = ks.select_source(startup_key)
    assert source.configured
    assert source.kind == "error"
    safe_failure(source.resolve)
    env.op.assert_not_called()


def test_empty_foreground_provider_stays_explicit_until_reconfigured(env, monkeypatch):
    monkeypatch.setenv("ROMP_API_KEY_REF", REF)
    assert ks.select_source(BOOT_KEY).kind == "op"
    monkeypatch.setenv("ROMP_API_KEY_REF", "")
    assert ks.select_source(BOOT_KEY).configured
    safe_failure(lambda: ks.select_source(BOOT_KEY).resolve())
    monkeypatch.setenv("ROMP_API_KEY_REF", OTHER_REF)
    assert ks.select_source(BOOT_KEY).value == OTHER_REF
    env.op.assert_not_called()


def test_restoring_foreground_reference_recovers_from_removal(env, monkeypatch):
    monkeypatch.setenv("ROMP_API_KEY_REF", REF)
    assert ks.select_source(BOOT_KEY).value == REF
    monkeypatch.delenv("ROMP_API_KEY_REF")
    safe_failure(lambda: ks.select_source(BOOT_KEY).resolve())
    monkeypatch.setenv("ROMP_API_KEY_REF", OTHER_REF)

    assert ks.select_source(BOOT_KEY).value == OTHER_REF
    env.op.assert_not_called()


def test_foreground_provider_authority_is_isolated_by_service_file_path(env, monkeypatch):
    monkeypatch.setenv("ROMP_API_KEY_REF", REF)
    assert ks.select_source(BOOT_KEY).kind == "op"
    monkeypatch.delenv("ROMP_API_KEY_REF")
    safe_failure(lambda: ks.select_source(BOOT_KEY).resolve())

    other_path = env.root / "other-service.env"
    monkeypatch.setenv("ROMP_SERVICE_ENV_FILE", str(other_path))
    assert ks.select_source(BOOT_KEY).resolve() == BOOT_KEY
    monkeypatch.setenv("ROMP_SERVICE_ENV_FILE", str(env.path))
    safe_failure(lambda: ks.select_source(BOOT_KEY).resolve())
    env.op.assert_not_called()


def test_explicit_file_key_can_replace_a_removed_foreground_provider(env, monkeypatch):
    monkeypatch.setenv("ROMP_API_KEY_REF", REF)
    assert ks.select_source(BOOT_KEY).kind == "op"
    monkeypatch.delenv("ROMP_API_KEY_REF")
    safe_failure(lambda: ks.select_source(BOOT_KEY).resolve())

    ks.write_source(ks.KeySource("file", NEW_KEY))
    assert ks.select_source(BOOT_KEY).resolve() == NEW_KEY
    env.op.assert_not_called()


def test_explicit_file_source_takes_priority_over_foreground_provider(env, monkeypatch):
    monkeypatch.setenv("ROMP_API_KEY_REF", OTHER_REF)
    env.path.write_text(f"ANTHROPIC_API_KEY={OLD_KEY}\n")
    source = ks.select_source(BOOT_KEY)
    assert (source.kind, source.resolve()) == ("file", OLD_KEY)
    env.op.assert_not_called()


def test_removing_selected_file_provider_cannot_restore_foreground_provider(env, monkeypatch):
    monkeypatch.setenv("ROMP_API_KEY_REF", OTHER_REF)
    assert ks.select_source(BOOT_KEY).value == OTHER_REF
    env.path.write_text(f"ROMP_API_KEY_REF={REF}\n")
    assert ks.select_source(BOOT_KEY).value == REF
    env.path.unlink()

    source = ks.select_source(BOOT_KEY)
    assert source.configured
    safe_failure(source.resolve)
    env.op.assert_not_called()


@pytest.mark.parametrize("credential", ["raw", "provider"])
@pytest.mark.parametrize("edit", ["remove-file", "empty-file", "remove-assignment"])
def test_supervised_kernel_restart_cannot_restore_removed_source(env, monkeypatch, credential, edit):
    monkeypatch.setenv("ROMP_SUPERVISED", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", BOOT_KEY)
    if credential == "provider":
        monkeypatch.setenv("ROMP_API_KEY_REF", REF)
        env.path.write_text(f"ROMP_API_KEY_REF={REF}\n")
        assert ks.select_source(BOOT_KEY).value == REF
    else:
        env.path.write_text(f"ANTHROPIC_API_KEY={OLD_KEY}\n")
        assert ks.select_source(BOOT_KEY).value == OLD_KEY
    if edit == "remove-file":
        env.path.unlink()
    elif edit == "empty-file":
        env.path.write_text("")
    else:
        env.path.write_text("ROMP_PERF=1\n")

    # A fresh kernel under the still-running manager receives its original environment,
    # but none of the previous kernel's authority maps or discarded startup-key state.
    restarted = SourceFileLoader(
        "romp_runtime_keysource_restarted_test", str(ROOT / "kernel" / "keysource.py")
    ).load_module()
    assert not restarted._AUTHORITATIVE_PATHS
    assert not restarted._ENV_PROVIDER_PATHS
    source = restarted.select_source(BOOT_KEY)
    if credential == "provider":
        assert source.kind == "error"
        assert source.configured
        with pytest.raises(restarted.KeySourceError) as caught:
            source.resolve()
        assert REF not in str(caught.value)
        assert BOOT_KEY not in str(caught.value)
        monkeypatch.delenv("ROMP_API_KEY_REF")
        assert restarted.select_source("") == source
    else:
        assert source.kind == "file"
        assert not source.configured
        assert source.resolve() == ""
        assert restarted.select_source("") == source
    env.op.assert_not_called()


@pytest.mark.parametrize("credential", ["raw", "provider"])
def test_foreground_fresh_kernel_keeps_explicit_environment_auth(env, monkeypatch, credential):
    monkeypatch.setenv("ANTHROPIC_API_KEY", BOOT_KEY)
    if credential == "provider":
        monkeypatch.setenv("ROMP_API_KEY_REF", REF)
    restarted = SourceFileLoader(
        "romp_runtime_keysource_foreground_restart_test", str(ROOT / "kernel" / "keysource.py")
    ).load_module()
    source = restarted.select_source(BOOT_KEY)
    if credential == "provider":
        assert (source.kind, source.value) == ("op", REF)
    else:
        assert (source.kind, source.resolve()) == ("environment", BOOT_KEY)
    env.op.assert_not_called()


def test_supervised_service_without_key_source_still_allows_login(env, monkeypatch):
    monkeypatch.setenv("ROMP_SUPERVISED", "1")
    source = ks.select_source()
    assert not source.configured
    assert source.resolve() == ""
    env.path.write_text(f"ROMP_API_KEY_REF={REF}\n")
    assert ks.select_source().value == REF
    env.op.assert_not_called()


def test_provider_failure_does_not_fall_back_to_competing_keys(env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", BOOT_KEY)
    env.path.write_text(f"ANTHROPIC_API_KEY={BOOT_KEY}\nROMP_API_KEY_REF={REF}\n")
    env.op.side_effect = None
    env.op.return_value = result(returncode=1)

    safe_failure(lambda: ks.select_source(BOOT_KEY).resolve())
    assert ks.select_source(BOOT_KEY).kind == "op"
    assert env.op.call_count == 1


def test_provider_failure_after_success_cannot_reuse_previous_resolved_key(env):
    env.path.write_text(f"ROMP_API_KEY_REF={REF}\n")
    env.op.side_effect = [result(), result(returncode=1)]
    assert ks.select_source(BOOT_KEY).resolve() == OLD_KEY

    safe_failure(lambda: ks.select_source(BOOT_KEY).resolve())
    assert env.op.call_count == 2


@pytest.mark.parametrize("edit", ["remove-file", "remove-assignment", "empty-reference"])
def test_removing_or_emptying_selected_provider_cannot_revive_startup_key(env, edit):
    env.path.write_text(f"ROMP_API_KEY_REF={REF}\n")
    assert ks.select_source(BOOT_KEY).kind == "op"
    if edit == "remove-file":
        env.path.unlink()
    elif edit == "remove-assignment":
        env.path.write_text("ROMP_PERF=1\n")
    else:
        env.path.write_text(f"ROMP_API_KEY_REF=\nANTHROPIC_API_KEY={BOOT_KEY}\n")

    selected = ks.select_source(BOOT_KEY)
    assert selected.configured
    safe_failure(selected.resolve)
    env.op.assert_not_called()


@pytest.mark.parametrize("edit", ["remove-file", "remove-assignment", "empty-key"])
def test_removing_or_emptying_legacy_source_cannot_revive_startup_key(env, edit):
    env.path.write_text(f"ANTHROPIC_API_KEY={OLD_KEY}\n")
    assert ks.select_source(BOOT_KEY).resolve() == OLD_KEY
    if edit == "remove-file":
        env.path.unlink()
    elif edit == "remove-assignment":
        env.path.write_text("ROMP_PERF=1\n")
    else:
        env.path.write_text("ANTHROPIC_API_KEY=\n")

    assert ks.select_source(BOOT_KEY).resolve() == ""
    env.op.assert_not_called()


@pytest.mark.parametrize("file_source", [f"ROMP_API_KEY_REF={REF}", f"ANTHROPIC_API_KEY={OLD_KEY}"])
@pytest.mark.parametrize("failure_at", ["stat", "open"])
def test_unreadable_previously_selected_source_cannot_reuse_cached_value(env, file_source, failure_at):
    env.path.write_text(file_source + "\n")
    assert ks.select_source(BOOT_KEY).configured
    if failure_at == "stat":
        context = mock.patch.object(ks.os, "stat", side_effect=PermissionError(SECRET_STDERR))
    else:
        # Permission-only changes must invalidate the cache even if bytes/mtime are unchanged.
        env.path.chmod(0o000)
        context = mock.patch.object(ks, "open", create=True, side_effect=PermissionError(SECRET_STDERR))
    with context:
        selected = ks.select_source(BOOT_KEY)
    assert selected.kind == "error"
    assert selected.configured
    safe_failure(selected.resolve)
    env.op.assert_not_called()


def test_explicit_new_source_recovers_from_removed_provider(env):
    env.path.write_text(f"ROMP_API_KEY_REF={REF}\n")
    assert ks.select_source(BOOT_KEY).kind == "op"
    env.path.unlink()
    safe_failure(lambda: ks.select_source(BOOT_KEY).resolve())

    ks.write_source(ks.KeySource("op", OTHER_REF))
    assert ks.select_source(BOOT_KEY).value == OTHER_REF
    ks.write_source(ks.KeySource("file", NEW_KEY))
    assert ks.select_source(BOOT_KEY).resolve() == NEW_KEY
    env.op.assert_not_called()


def test_atomic_reference_selection_removes_competing_keys_without_resolving(env):
    original = (
        f"# keep this comment\nANTHROPIC_API_KEY={OLD_KEY}\nROMP_PERF=1\n"
        f"ROMP_API_KEY_REF={OTHER_REF}\nANTHROPIC_API_KEY={BOOT_KEY}\n"
    )
    env.path.write_text(original)
    env.path.chmod(0o644)
    real_replace = os.replace
    replacements = []

    marker = Path(ks.marker_path(str(env.path)))

    def observe_replace(source_path, destination_path):
        if Path(destination_path) == marker:          # the durable op memory rides its own atomic write
            return real_replace(source_path, destination_path)
        source_path = Path(source_path)
        assert Path(destination_path) == env.path
        assert source_path.parent == env.path.parent
        assert env.path.read_text() == original  # Original survives until the atomic replace.
        assert stat.S_IMODE(source_path.stat().st_mode) == 0o600
        pending = source_path.read_text()
        assert "ANTHROPIC_API_KEY=" not in pending
        assert pending.count("ROMP_API_KEY_REF=") == 1
        assert f"ROMP_API_KEY_REF={REF}" in pending
        replacements.append(source_path)
        real_replace(source_path, destination_path)

    with mock.patch.object(ks.os, "replace", side_effect=observe_replace):
        ks.write_source(ks.KeySource("op", REF))

    assert len(replacements) == 1
    assert stat.S_IMODE(env.path.stat().st_mode) == 0o600
    assert env.path.read_text() == f"# keep this comment\nROMP_PERF=1\nROMP_API_KEY_REF={REF}\n"
    assert sorted(env.root.iterdir()) == [env.path, marker], "no temp file left; the marker is the memory"
    assert marker.read_text() == "op\n"
    assert ks.select_source(BOOT_KEY).value == REF
    env.op.assert_not_called()


def test_failed_atomic_selection_preserves_old_configuration_and_cleans_temp_file(env):
    original = f"ANTHROPIC_API_KEY={OLD_KEY}\nROMP_PERF=1\n"
    env.path.write_text(original)
    with mock.patch.object(ks.os, "replace", side_effect=OSError("synthetic rename failure")):
        with pytest.raises(OSError, match="synthetic rename failure"):
            ks.write_source(ks.KeySource("op", REF))
    assert env.path.read_text() == original
    assert sorted(env.root.iterdir()) == [env.path]
    env.op.assert_not_called()


@pytest.mark.parametrize("consumer,attribute", [
    ("kernel/sdk_backend.py", "_keysrc"), ("cli/keyswap.py", "ks"),
])
@pytest.mark.parametrize("origin", ["file", "environment"])
def test_loading_a_consumer_preserves_prior_provider_removal(env, monkeypatch, consumer, attribute, origin):
    import sys
    if origin == "file":
        env.path.write_text(f"ROMP_API_KEY_REF={REF}\n")
    else:
        monkeypatch.setenv("ROMP_API_KEY_REF", REF)
    assert ks.select_source(BOOT_KEY).kind == "op"
    if origin == "file":
        env.path.unlink()
    else:
        monkeypatch.delenv("ROMP_API_KEY_REF")

    # The judge may select a provider before the SDK is loaded lazily. Loading a consumer must
    # share that module, including its remembered authority, rather than re-execute and reset it.
    monkeypatch.setitem(sys.modules, "romp_keysource", ks)
    module_name = "romp_lazy_source_consumer_test"
    try:
        loaded = SourceFileLoader(module_name, str(ROOT / consumer)).load_module()
        assert getattr(loaded, attribute) is ks
        assert ks.select_source(BOOT_KEY).kind == "error"
        safe_failure(lambda: ks.select_source(BOOT_KEY).resolve())
        env.op.assert_not_called()
    finally:
        sys.modules.pop(module_name, None)


def test_op_credentials_are_claimed_out_of_the_environment_and_reach_only_the_op_subprocess(env, monkeypatch):
    """op's own credential (a service-account token, a signed-in session token) must reach the kernel for
    headless use — and no child of the kernel: claim_op_env() takes the names out of os.environ once, and
    resolve() gives them back to the `op read` subprocess alone (review find, 2026-09-05: they were inherited
    by every Claude session and every judge call, a vault-wide credential in every agent's shell)."""
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "synthetic-op-token")
    monkeypatch.setenv("OP_SESSION_my_account", "synthetic-op-session")
    monkeypatch.setenv("OP_ACCOUNT", "my.1password.example")
    monkeypatch.setenv("UNRELATED_VAR", "kept")
    ks._OP_ENV.clear(); ks._OP_CLAIM_SAID = False
    try:
        # no reference anywhere: romp is not the op consumer (a session-side helper may be) → hands off
        assert ks.claim_op_env() == {} and "OP_SERVICE_ACCOUNT_TOKEN" in os.environ
        assert ks.strip_op_env({"OP_SERVICE_ACCOUNT_TOKEN": "x", "A": "1"}) == {"OP_SERVICE_ACCOUNT_TOKEN": "x", "A": "1"}
        monkeypatch.setenv("ROMP_API_KEY_REF", REF)                  # now romp runs op itself
        claimed = ks.claim_op_env()
        assert set(claimed) == {"OP_SERVICE_ACCOUNT_TOKEN", "OP_SESSION_my_account", "OP_ACCOUNT"}
        for name in claimed:
            assert name not in os.environ, name
        assert os.environ["UNRELATED_VAR"] == "kept"
        # a value that appears later is claimed too, and the stash is idempotent
        monkeypatch.setenv("OP_CONNECT_TOKEN", "synthetic-connect")
        assert "OP_CONNECT_TOKEN" in ks.claim_op_env() and "OP_CONNECT_TOKEN" not in os.environ
        env.op.side_effect = None
        env.op.return_value = result(NEW_KEY.encode())
        assert ks.KeySource("op", REF).resolve() == NEW_KEY
        sub_env = env.op.call_args.kwargs["env"]
        assert sub_env["OP_SERVICE_ACCOUNT_TOKEN"] == "synthetic-op-token"
        assert sub_env["OP_SESSION_my_account"] == "synthetic-op-session"
        assert "UNRELATED_VAR" not in sub_env, "op sees a whitelist, not the process environment (2026-09-06)"
        assert "OP_SERVICE_ACCOUNT_TOKEN" not in os.environ, "resolving hands nothing back to the process"
        # a child env built before the claim is scrubbed the same way
        child = {"OP_SERVICE_ACCOUNT_TOKEN": "x", "OP_SESSION_acct": "y", "PATH": "/bin", "OPTIONAL": "keep"}
        assert ks.strip_op_env(child) == {"PATH": "/bin", "OPTIONAL": "keep"}
        assert ks.is_op_env_name("OP_SESSION_anything") and not ks.is_op_env_name("OPTIONAL")
    finally:
        ks._OP_ENV.clear()


def test_a_stray_byte_in_an_unrelated_line_does_not_turn_the_source_into_an_error(env):
    env.path.write_bytes(b"# caf\xe9 note\nROMP_API_KEY_REF=" + REF.encode() + b"\n")
    assert ks.read_source(str(env.path)) == ks.KeySource("op", REF)


def test_the_claim_says_which_names_it_took_once_and_never_a_value(env, monkeypatch, capsys):
    monkeypatch.setenv("ROMP_API_KEY_REF", REF)
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "synthetic-op-token-value")
    ks._OP_ENV.clear(); ks._OP_CLAIM_SAID = False
    try:
        ks.claim_op_env(); ks.claim_op_env()
        err = capsys.readouterr().err
        assert err.count("op credentials claimed") == 1
        assert "OP_SERVICE_ACCOUNT_TOKEN" in err and "synthetic-op-token-value" not in err
    finally:
        ks._OP_ENV.clear(); ks._OP_CLAIM_SAID = False


def test_one_reserved_names_rule_for_the_doors_the_launch_and_the_fork():
    op = ks.KeySource("op", REF); err = ks.KeySource("error", error="x"); plain = ks.KeySource("file", "k")
    all3 = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
    assert ks.runtime_reserved_names("key", op) == all3
    assert ks.runtime_reserved_names("", op) == all3, "no pick with a configured source launches keyed"
    assert ks.runtime_reserved_names("login", op) == ("ANTHROPIC_API_KEY",), "a login session keeps its own token"
    assert ks.runtime_reserved_names("login", err) == ("ANTHROPIC_API_KEY",)
    assert ks.runtime_reserved_names("key", plain) == () and ks.runtime_reserved_names("", None) == ()


def test_a_garbled_key_line_is_an_error_while_a_garbled_comment_is_not(env):
    env.path.write_bytes(b"ANTHROPIC_API_KEY=sk-ant-TEST-\xff\xfe-garbled\n")
    src = ks.read_source(str(env.path))
    assert src.kind == "error" and "not valid UTF-8" in src.error and "ANTHROPIC_API_KEY" in src.error
    env.path.write_bytes(b"# caf\xe9\nROMP_API_KEY_REF=" + REF.encode() + b"\n")
    ks._CACHE = ((), "")
    assert ks.read_source(str(env.path)) == ks.KeySource("op", REF)


def test_tmux_server_scrub_runs_one_unset_per_credential_name(env):
    ran = ks.tmux_unset_global(["OP_SERVICE_ACCOUNT_TOKEN", "OP_SESSION_acct", "PATH", "OP_ACCOUNT",
                                "ANTHROPIC_API_KEY", "HOME"], socket="probe")
    assert ran == [["tmux", "-L", "probe", "set-environment", "-gu", "ANTHROPIC_API_KEY"],
                   ["tmux", "-L", "probe", "set-environment", "-gu", "OP_ACCOUNT"],
                   ["tmux", "-L", "probe", "set-environment", "-gu", "OP_SERVICE_ACCOUNT_TOKEN"],
                   ["tmux", "-L", "probe", "set-environment", "-gu", "OP_SESSION_acct"]]
    assert env.tmux.call_count == 4, "one list for the server scrub: op's names and the startup key, nothing else"
    env.op.assert_not_called(), "a tmux scrub is not a credential retrieval"
    env.tmux.side_effect = FileNotFoundError
    assert ks.tmux_unset_global(["OP_ACCOUNT"]) == [], "no tmux: nothing to do, nothing raised"
    env.tmux.side_effect = RuntimeError("anything at all")
    assert ks.tmux_unset_global(["OP_ACCOUNT"]) == [], "best effort by contract: never raises"


def _tmux_unsets(tmux):
    return sorted(c.args[0][-1] for c in tmux.call_args_list if c.args[0][-3:-1] == ["set-environment", "-gu"])


def test_becoming_the_op_consumer_mid_run_scrubs_the_tmux_server(env, monkeypatch):
    """Review find (2026-09-06): the tmux server scrub ran once, in kernel main(), and only if the claim
    happened THEN. A box that started with op's token but no reference (an apiKeyHelper box, or an operator
    adding the token first) and then `romp keyswap`ped to a reference with no restart claimed the token
    out of the kernel's environment on the next launch — while the tmux server, started by the manager
    with the same environment, kept it (and the manager's startup ANTHROPIC_API_KEY) for every new pane.
    Reproduced against a real private-socket tmux server before this fix."""
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "synthetic-op-token")
    monkeypatch.setenv("ROMP_TMUX_SOCKET", "probe")
    env.path.write_text("ROMP_PERF=1\n")                              # no reference: not the consumer
    ks._OP_ENV.clear(); ks._OP_CLAIM_SAID = False
    try:
        assert ks.claim_op_env() == {}
        env.tmux.assert_not_called()
        env.path.write_text("ROMP_PERF=1\nROMP_API_KEY_REF=%s\n" % REF)   # the keyswap, no restart
        ks._CACHE = ((), "")
        assert set(ks.claim_op_env()) == {"OP_SERVICE_ACCOUNT_TOKEN"}
        assert _tmux_unsets(env.tmux) == ["ANTHROPIC_API_KEY", "OP_SERVICE_ACCOUNT_TOKEN"]
        assert all(c.args[0][:3] == ["tmux", "-L", "probe"] for c in env.tmux.call_args_list), "the kernel's server"
        n = env.tmux.call_count
        ks.claim_op_env(); ks.claim_op_env()
        assert env.tmux.call_count == n, "once per name per process"
        monkeypatch.setenv("OP_SESSION_acct", "synthetic-session")      # a name that appears later
        ks.claim_op_env()
        assert _tmux_unsets(env.tmux) == ["ANTHROPIC_API_KEY", "OP_SERVICE_ACCOUNT_TOKEN", "OP_SESSION_acct"]
    finally:
        ks._OP_ENV.clear(); ks._OP_CLAIM_SAID = False


def test_a_tmux_launch_env_drops_the_startup_key_only_while_a_reference_governs(env, monkeypatch):
    child = {"OP_SERVICE_ACCOUNT_TOKEN": "x", "ANTHROPIC_API_KEY": "synthetic-stale-key", "PATH": "/bin"}
    ks._OP_ENV.clear()
    env.path.write_text("ANTHROPIC_API_KEY=%s\n" % OLD_KEY)             # a static-key box
    assert ks.strip_tmux_env(dict(child)) == child, "static-key panes rely on the inheritance"
    env.path.write_text("ROMP_API_KEY_REF=%s\n" % REF)
    ks._CACHE = ((), "")
    assert ks.strip_tmux_env(dict(child)) == {"PATH": "/bin"}
    assert ks.is_tmux_scrub_name("ANTHROPIC_API_KEY") and ks.is_tmux_scrub_name("OP_SESSION_x")
    assert not ks.is_tmux_scrub_name("ANTHROPIC_AUTH_TOKEN") and not ks.is_tmux_scrub_name("PATH")


def test_the_op_memory_survives_a_kernel_restart_and_follows_an_intentional_switch(env):
    """Review find (2026-09-06): "op was authoritative" lived in a process dict. A supervised kernel
    restart with the reference line gone from the file, and no ROMP_API_KEY_REF in the manager's
    environment, launched every session without an explicit pick on the login. The memory is now a
    sibling marker (`service.env.source`, the word `op`, 0600) that a non-op selection removes."""
    env.path.write_text("ROMP_PERF=1\nROMP_API_KEY_REF=%s\n" % REF)
    assert ks.select_source().kind == "op"
    marker = env.root / "service.env.source"
    assert marker.read_text() == "op\n" and stat.S_IMODE(marker.stat().st_mode) == 0o600
    assert ks.marker_path(str(env.path)) == str(marker)
    # the restart: memory gone, line gone
    ks._AUTHORITATIVE_PATHS.clear(); ks._CACHE = ((), "")
    env.path.write_text("ROMP_PERF=1\n")
    src = ks.select_source(BOOT_KEY)
    assert src.kind == "error" and "reference was removed" in src.error
    safe_failure(lambda: src.resolve())
    # an intentional swap to a static profile clears it, so the next restart is not an error
    ks.write_source(ks.KeySource("file", NEW_KEY), str(env.path))
    assert not marker.exists()
    ks._AUTHORITATIVE_PATHS.clear(); ks._CACHE = ((), "")
    assert ks.select_source().value == NEW_KEY
    env.path.write_text("ROMP_PERF=1\n")
    ks._AUTHORITATIVE_PATHS.clear(); ks._CACHE = ((), "")
    assert ks.select_source(BOOT_KEY).kind == "environment", "no op memory: the old behaviour"
    # a swap back to a reference re-arms it, and a hand edit to a static key is a selection too
    ks.write_source(ks.KeySource("op", REF), str(env.path))
    assert marker.read_text() == "op\n"
    env.path.write_text("ANTHROPIC_API_KEY=%s\n" % OLD_KEY)
    ks._AUTHORITATIVE_PATHS.clear(); ks._CACHE = ((), "")
    assert ks.select_source().value == OLD_KEY and not marker.exists()
    env.op.assert_not_called()


def test_the_marker_never_fails_a_selection(env, monkeypatch):
    env.path.write_text("ROMP_API_KEY_REF=%s\n" % REF)
    monkeypatch.setattr(ks.tempfile, "mkstemp", mock.Mock(side_effect=OSError("read-only")))
    assert ks.select_source().kind == "op"
    assert not (env.root / "service.env.source").exists()


_REAL_RUN = subprocess.run     # captured before any fixture patches it


def test_op_read_gets_a_minimal_environment(env, tmp_path, monkeypatch):
    """Review find (2026-09-06): resolve() copied all of os.environ into the `op read` subprocess — the
    kernel's ROMP_SERVE_TOKEN (full control of every session), the manager's startup ANTHROPIC_API_KEY,
    the reference itself — into a third-party binary that needs none of it. Proved with a fake `op` on
    PATH that answers with the NAMES it was given."""
    shim = tmp_path / "bin"; shim.mkdir()
    (shim / "op").write_text("#!/bin/sh\nprintf '%s' \"$(env | cut -d= -f1 | sort | paste -sd, -)\"\n")   # --no-newline, like op
    (shim / "op").chmod(0o755)
    monkeypatch.setenv("PATH", str(shim) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("ROMP_SERVE_TOKEN", "synthetic-serve-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-startup-key")
    monkeypatch.setenv("ROMP_API_KEY_REF", REF)
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "synthetic-op-token")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("HOME", str(tmp_path))
    ks._OP_ENV.clear(); ks._OP_CLAIM_SAID = False
    env.op.side_effect = _REAL_RUN
    try:
        names = set(ks.KeySource("op", REF).resolve().split(","))
    finally:
        ks._OP_ENV.clear(); ks._OP_CLAIM_SAID = False
    for absent in ("ROMP_SERVE_TOKEN", "ANTHROPIC_API_KEY", "ROMP_API_KEY_REF", "ROMP_SERVICE_ENV_FILE"):
        assert absent not in names, absent
    for present in ("PATH", "HOME", "XDG_CONFIG_HOME", "LC_ALL", "OP_SERVICE_ACCOUNT_TOKEN"):
        assert present in names, present
    assert not any(n.startswith("ROMP_") for n in names), "nothing of romp's reaches op"


# ---- the generic key command (ROMP_API_KEY_CMD, 2026-09-07) -------------------------------------------
#
# romp must not know about 1Password specifically: a key source may be ANY command that prints the key
# (Claude Code's apiKeyHelper contract), and the op reference is a thin shorthand over the same runner.
# The fake scripts below stand in for a secret manager's CLI; every value is synthetic.

CMD = "fetch-synthetic-key --field api"


def _script(tmp_path, monkeypatch, name, body):
    """A fake CLI on a temp PATH — the shape an operator's key command has."""
    shim = tmp_path / "bin"; shim.mkdir(exist_ok=True)
    (shim / name).write_text("#!/bin/sh\n" + body + "\n")
    (shim / name).chmod(0o755)
    monkeypatch.setenv("PATH", str(shim) + os.pathsep + os.environ["PATH"])
    return name


def test_a_command_source_parses_validates_and_fingerprints_without_running_anything(env):
    env.path.write_text(f"ROMP_PERF=1\nROMP_API_KEY_CMD={CMD}\n")
    source = ks.select_source(BOOT_KEY)
    assert (source.kind, source.value) == ("command", CMD)
    assert source.configured
    source.validate()
    assert source.fingerprint() == ks.fingerprint("cmd:" + CMD)
    assert source.fingerprint() != ks.KeySource("op", CMD).fingerprint(), "the kind is part of the identity"
    assert source == ks.parse_source(env.path.read_text())
    assert ks.is_provider_kind("command") and ks.is_provider_kind("op") and not ks.is_provider_kind("file")
    assert ks.read_key() == "", "a command line is never a raw key"
    assert ks.runtime_reserved_names("key", source) == ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
    # a quoted line reads the same way systemd hands it over
    assert ks.parse_source(f'ROMP_API_KEY_CMD="{CMD}"\n').value == CMD
    env.op.assert_not_called()


@pytest.mark.parametrize("command", ["", "   ", "cmd\nPRIVATE_CMD_MARKER", "cmd\0PRIVATE_CMD_MARKER"])
def test_an_invalid_command_line_never_runs_and_stays_an_explicit_choice(env, command):
    source = ks.KeySource("command", command)
    assert source.configured, "an invalid provider is not permission to fall to the login"
    safe_failure(source.resolve, "PRIVATE_CMD_MARKER")
    env.op.assert_not_called()


def test_a_command_source_resolves_through_sh_with_bounded_noninteractive_io(env):
    """The contract: `/bin/sh -c <line>` (a pipeline or a helper script an operator already has works
    as-is), stdin and stderr to /dev/null, the same timeout every provider gets, never a shell-less argv."""
    env.op.side_effect = None
    env.op.return_value = subprocess.CompletedProcess(CMD, 0, stdout=NEW_KEY.encode() + b"\n", stderr=b"")
    assert ks.KeySource("command", CMD).resolve() == NEW_KEY, "one trailing newline is forgiven"
    args, kwargs = env.op.call_args
    assert args == (CMD,) and kwargs["shell"] is True
    assert kwargs["stdin"] == subprocess.DEVNULL and kwargs["stderr"] == subprocess.DEVNULL
    assert kwargs["stdout"] == subprocess.PIPE and kwargs["check"] is False
    assert kwargs["timeout"] == ks.KEY_CMD_TIMEOUT == ks.OP_TIMEOUT
    assert not any(k.startswith("ROMP_") for k in kwargs["env"])


def test_the_op_shorthand_runs_through_the_same_runner_in_argv_form(env, monkeypatch):
    """`KeySource("op", ref)` is `op read --no-newline <ref>` handed to the shared runner: same env, same
    timeout, the reference as ONE argument. Proved by making the runner the observation point."""
    seen = []
    real = ks._run_key_command

    def spy(cmd, **kw):
        seen.append((cmd, kw))
        return real(cmd, **kw)
    monkeypatch.setattr(ks, "_run_key_command", spy)
    env.op.side_effect = None
    env.op.return_value = result(OLD_KEY.encode())
    assert ks.KeySource("op", REF).resolve() == OLD_KEY
    (cmd, kw), = seen
    assert cmd == ["op", "read", "--no-newline", REF] and kw["shell"] is False
    assert kw["tolerate_newline"] is False, "--no-newline promised none; a newline is a malformed key"
    env.op.return_value = result(OLD_KEY.encode() + b"\n")
    safe_failure(ks.KeySource("op", REF).resolve)


def test_a_key_command_on_a_real_shell_strips_one_trailing_newline(env, tmp_path, monkeypatch):
    _script(tmp_path, monkeypatch, "fetch-synthetic-key", 'echo "%s"' % NEW_KEY)   # echo adds the newline
    env.op.side_effect = _REAL_RUN
    assert ks.KeySource("command", CMD).resolve() == NEW_KEY
    _script(tmp_path, monkeypatch, "fetch-synthetic-key", 'printf "%s\\r\\n"' % NEW_KEY)   # a CRLF one too
    assert ks.KeySource("command", CMD).resolve() == NEW_KEY


@pytest.mark.parametrize("body,expect", [
    ('echo "%s" >&2; echo "%s" >&2; exit 1' % (SECRET_STDERR, OLD_KEY), "failed"),   # stderr is a credential hazard: never quoted
    ("exit 0", "empty"),                                                             # printed nothing
    ('printf "%s\\nsecond-line\\n"' % OLD_KEY, "invalid"),                            # two lines
    ('printf "%s  \\n"' % OLD_KEY, "invalid"),                                        # inner whitespace beyond the newline
    ("no-such-binary-anywhere-synthetic", "not found"),                             # sh: 127
])
def test_key_command_failures_are_static_safe_messages(env, tmp_path, monkeypatch, body, expect):
    _script(tmp_path, monkeypatch, "fetch-synthetic-key", body)
    env.op.side_effect = _REAL_RUN
    error = safe_failure(ks.KeySource("command", CMD).resolve)
    assert "key command" in str(error) and expect in str(error), str(error)
    assert CMD not in str(error), "the command line itself may name a vault or a path; it stays out too"


def test_a_key_command_that_hangs_is_cut_off_at_the_shared_timeout(env, tmp_path, monkeypatch):
    _script(tmp_path, monkeypatch, "fetch-synthetic-key", "sleep 5; echo never")
    monkeypatch.setattr(ks, "KEY_CMD_TIMEOUT", 1)
    env.op.side_effect = _REAL_RUN
    error = safe_failure(ks.KeySource("command", CMD).resolve)
    assert "timed out" in str(error)


def test_the_key_command_gets_the_same_minimal_environment_as_op(env, tmp_path, monkeypatch):
    """A whitelist, not a copy: PATH/HOME and the ordinary-CLI names, op's claimed credential names if
    any were claimed, and NOTHING of romp's — a key command is expected to fetch its own credential."""
    _script(tmp_path, monkeypatch, "fetch-synthetic-key", "env | cut -d= -f1 | sort | paste -sd, -")
    monkeypatch.setenv("ROMP_SERVE_TOKEN", "synthetic-serve-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-startup-key")
    monkeypatch.setenv("ROMP_API_KEY_CMD", CMD)
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "synthetic-op-token")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("HOME", str(tmp_path))
    ks._OP_ENV.clear(); ks._OP_CLAIM_SAID = False
    env.op.side_effect = _REAL_RUN
    try:
        names = set(ks.KeySource("command", CMD).resolve().split(","))
        assert "OP_SERVICE_ACCOUNT_TOKEN" not in os.environ, "a command source claims op's names too"
    finally:
        ks._OP_ENV.clear(); ks._OP_CLAIM_SAID = False
    for absent in ("ROMP_SERVE_TOKEN", "ANTHROPIC_API_KEY", "ROMP_API_KEY_CMD", "ROMP_SERVICE_ENV_FILE"):
        assert absent not in names, absent
    for present in ("PATH", "HOME", "XDG_CONFIG_HOME", "LC_ALL", "OP_SERVICE_ACCOUNT_TOKEN"):
        assert present in names, present
    assert not any(n.startswith("ROMP_") for n in names), "nothing of romp's reaches the key command"
    assert ks.key_command_env is ks.op_subprocess_env, "the old name is the same function"


def test_both_provider_lines_is_an_error_not_a_precedence_rule(env, monkeypatch):
    env.path.write_text(f"ROMP_API_KEY_CMD={CMD}\nROMP_API_KEY_REF={REF}\nANTHROPIC_API_KEY={BOOT_KEY}\n")
    source = ks.select_source(BOOT_KEY)
    assert source.kind == "error" and source.configured
    assert "one of ROMP_API_KEY_CMD or ROMP_API_KEY_REF, not both" in source.error
    safe_failure(source.resolve)
    assert ks.provider_consumer(), "an invalid provider configuration is still a provider choice"
    # the same rule for the manager's environment
    env.path.unlink(); ks._CACHE = ((), "")
    monkeypatch.setenv("ROMP_API_KEY_CMD", CMD); monkeypatch.setenv("ROMP_API_KEY_REF", REF)
    assert ks.select_source(BOOT_KEY).kind == "error"
    env.op.assert_not_called()


def test_a_static_key_line_beside_a_command_line_is_ignored_and_removed_on_swap(env):
    env.path.write_text(f"ANTHROPIC_API_KEY={BOOT_KEY}\nROMP_API_KEY_CMD={CMD}\n")
    assert ks.select_source(BOOT_KEY) == ks.KeySource("command", CMD)
    ks.write_source(ks.KeySource("command", CMD + " --other"), str(env.path))
    body = env.path.read_text()
    assert body == f"ROMP_API_KEY_CMD={CMD} --other\n" and BOOT_KEY not in body
    ks.write_source(ks.KeySource("op", REF), str(env.path))
    assert env.path.read_text() == f"ROMP_API_KEY_REF={REF}\n", "a provider swap replaces the other provider's line"


def test_the_durable_marker_round_trips_the_command_kind(env):
    """The `service.env.source` marker holds the provider KIND: a supervised restart after the command
    line vanished must refuse to fall to the login, exactly as it does for a vanished reference."""
    env.path.write_text(f"ROMP_PERF=1\nROMP_API_KEY_CMD={CMD}\n")
    assert ks.select_source().kind == "command"
    marker = env.root / "service.env.source"
    assert marker.read_text() == "command\n" and stat.S_IMODE(marker.stat().st_mode) == 0o600
    assert ks.read_marker(str(env.path)) == "command"
    ks._AUTHORITATIVE_PATHS.clear(); ks._CACHE = ((), "")          # the restart
    env.path.write_text("ROMP_PERF=1\n")
    src = ks.select_source(BOOT_KEY)
    assert src.kind == "error" and "key command was removed" in src.error
    safe_failure(src.resolve)
    ks.write_source(ks.KeySource("op", REF), str(env.path))       # provider to provider: the word follows
    assert marker.read_text() == "op\n"
    ks.write_source(ks.KeySource("command", CMD), str(env.path))
    assert marker.read_text() == "command\n"
    ks.write_source(ks.KeySource("file", NEW_KEY), str(env.path))
    assert not marker.exists(), "an intentional switch to a static key clears it"
    env.op.assert_not_called()


def test_a_command_in_the_environment_selects_and_its_removal_is_an_error(env, monkeypatch):
    monkeypatch.setenv("ROMP_API_KEY_CMD", CMD)
    assert ks.select_source(BOOT_KEY) == ks.KeySource("command", CMD)
    monkeypatch.delenv("ROMP_API_KEY_CMD")
    src = ks.select_source(BOOT_KEY)
    assert src.kind == "error" and "key command was removed from the environment" in src.error
    # supervised: the file alone governs, and a command in the environment is not a fallback
    monkeypatch.setenv("ROMP_SUPERVISED", "1"); monkeypatch.setenv("ROMP_API_KEY_CMD", CMD)
    ks._ENV_PROVIDER_PATHS.clear(); ks._AUTHORITATIVE_PATHS.clear()
    src = ks.select_source(BOOT_KEY)
    assert src.kind == "error" and "key command was removed" in src.error
    env.op.assert_not_called()


def test_a_command_source_makes_romp_the_provider_consumer_and_scrubs_tmux(env, monkeypatch):
    """The tmux gate generalizes: with a key command configured, ANTHROPIC_API_KEY must still leave tmux
    launches and the server's globals (a keyswap retired it), and op's names are scrubbed if present."""
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "synthetic-op-token")
    monkeypatch.setenv("ROMP_TMUX_SOCKET", "probe")
    env.path.write_text("ANTHROPIC_API_KEY=%s\n" % OLD_KEY)
    ks._OP_ENV.clear(); ks._OP_CLAIM_SAID = False
    child = {"OP_SERVICE_ACCOUNT_TOKEN": "x", "ANTHROPIC_API_KEY": "synthetic-stale-key", "PATH": "/bin"}
    try:
        assert not ks.provider_consumer() and ks.op_consumer is ks.provider_consumer
        assert ks.strip_tmux_env(dict(child)) == child
        env.path.write_text("ROMP_API_KEY_CMD=%s\n" % CMD); ks._CACHE = ((), "")     # the keyswap, no restart
        assert ks.provider_consumer()
        assert ks.strip_tmux_env(dict(child)) == {"PATH": "/bin"}
        assert set(ks.claim_op_env()) == {"OP_SERVICE_ACCOUNT_TOKEN"}
        assert _tmux_unsets(env.tmux) == ["ANTHROPIC_API_KEY", "OP_SERVICE_ACCOUNT_TOKEN"]
    finally:
        ks._OP_ENV.clear(); ks._OP_CLAIM_SAID = False
    env.path.unlink(); ks._CACHE = ((), "")
    monkeypatch.setenv("ROMP_API_KEY_CMD", CMD)
    assert ks.provider_consumer(), "the manager's environment counts too"
    env.op.assert_not_called()
