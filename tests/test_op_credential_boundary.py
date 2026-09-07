#!/usr/bin/env python3
"""Where op's own credential may and may not go (2026-09-05), pinned at the source across the four
programs that spawn children: the kernel (claims first, scrubs the tmux server, strips revives), the
manager (a scrubbed tmux server), the launcher (scrubs the server's globals before a pane exists), and the
door (the request's auth decides which credential names are reserved). Since 2026-09-06 the tmux scrub
also covers the manager's startup ANTHROPIC_API_KEY, fires whenever romp BECOMES the op consumer (not
only at kernel start), and reads the env file's own reference line — the three review finds of that day.
Synthetic throughout."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)


def _read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


class KernelBoundary(unittest.TestCase):
    def test_the_claim_is_the_kernels_first_act_and_scrubs_the_tmux_server(self):
        src = _read("kernel/kernel.py")
        main = src[src.rindex("\ndef main():"):]
        claim = main.index("jd._keysrc.claim_op_env()")
        self.assertLess(claim, main.index("_ensure_bundles()"), "before the first child")
        self.assertLess(claim, main.index("threading.Thread("), "before the first thread")
        # the tmux server scrub lives INSIDE the claim (keysource.claim_op_env), so a claim that happens
        # later — a keyswap to a reference with no restart — scrubs the server too; no second call site
        ks = _read("kernel/keysource.py")
        claim_fn = ks[ks.index("\ndef claim_op_env("):ks.index("\ndef strip_op_env(")]
        self.assertIn('tmux_unset_global(pending, os.environ.get("ROMP_TMUX_SOCKET", ""))', claim_fn)
        self.assertIn("(set(_OP_ENV) | {KEY_VAR}) - _TMUX_SCRUBBED", claim_fn, "op's names and the startup key, once each")

    def test_both_tmux_launch_paths_strip_the_credential_and_the_startup_key(self):
        src = _read("kernel/kernel.py")
        self.assertIn("jd._keysrc.strip_tmux_env(env)   # op's credential stays with the kernel", src)
        self.assertIn('env=jd._keysrc.strip_tmux_env(dict(os.environ)))', src, "the revive launch too")
        ks = _read("kernel/keysource.py")
        self.assertIn("def is_tmux_scrub_name(name: str) -> bool:", ks, "the ONE name list")
        self.assertIn("return is_op_env_name(name) or name == KEY_VAR", ks)

    def test_the_door_passes_the_requests_auth_to_the_one_rule(self):
        src = _read("kernel/kernel.py")
        self.assertIn('eerr = _env_error(env_req, str((b or {}).get("auth") or ""))', src)
        self.assertIn("jd._keysrc.runtime_reserved_names(auth or \"\", jd._keysrc.select_source())", src)
        sb = _read("kernel/sdk_backend.py")
        self.assertIn('env_request_error(env, (reg or {}).get("auth") or "")', sb, "set_env knows the session's auth")
        self.assertIn('err = env_request_error(env, auth or "")', sb, "spawn knows the pick")
        self.assertIn("_keysrc.runtime_reserved_names(sess.auth, key_source)", sb, "the launch")
        self.assertIn('_keysrc.runtime_reserved_names(reg.get("auth") or "", self._work_key_source())', sb, "the fork copy")


class ManagerAndLauncher(unittest.TestCase):
    def test_the_manager_starts_the_tmux_server_without_op_credentials_when_romp_runs_op(self):
        src = _read("bin/romp-manager")
        self.assertIn("function withoutOpCredentials(env)", src)
        self.assertIn("if (!out.ROMP_API_KEY_REF && !serviceEnvHasRef(env)) return out;", src,
                      "a helper box keeps its environment; the env file's own line counts as configured")
        self.assertRegex(src, r"k === 'OP_SERVICE_ACCOUNT_TOKEN' \|\| k === 'OP_CONNECT_HOST' \|\| k === 'OP_CONNECT_TOKEN' \|\| k === 'OP_ACCOUNT' \|\| k\.startsWith\('OP_SESSION_'\)\s*\|\| k === 'ANTHROPIC_API_KEY'")
        self.assertEqual(src.count("env: withoutOpCredentials(process.env) });"), 3,
                         "the scoped start, the bare start, and the pid probe after a failed scoped start (a tmux "
                         "client that starts no server, scrubbed all the same: every tmux exec here is)")

    def test_the_launcher_scrubs_the_servers_globals_before_the_pane_exists(self):
        src = _read("bin/romp")
        block = src[src.index('if _romp_op_consumer; then'):src.index('tmux new-session -d -s "$name" -c "$work_dir"')]
        self.assertIn('tmux set-environment -gu "$op_var"', block)
        self.assertIn("tmux show-environment -g", block)
        self.assertIn("OP_SESSION_[A-Za-z0-9_]*|ANTHROPIC_API_KEY", block, "the startup key too")
        helper = src[src.index("_romp_op_consumer() {"):src.index("# The kernel serve token")]
        self.assertIn('[[ -n "${ROMP_API_KEY_REF:-}" ]] && return 0', helper)
        self.assertIn("ROMP_API_KEY_REF=*) return 0 ;;", helper, "the env file's own line")
        self.assertIn("${ROMP_SERVICE_ENV_FILE:-${ROMP_SERVICE_ENV:-${XDG_CONFIG_HOME:-$HOME/.config}/romp/service.env}}", helper)


if __name__ == "__main__":
    unittest.main()
