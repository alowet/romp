# tests/git-hermetic.bash: git in a bats test reads none of the developer's configuration.
#
# Use from a bats file: `load git-hermetic` at the top and `git_hermetic` as the first line of
# setup(), before any git command runs.
#
# Why (2026-09-06): the fixture repos here are built with `git init` + `git commit` in temp dirs,
# and those commands honoured the developer's global git config. On one box a global
# core.hooksPath ran a pre-commit hook (a gitleaks scan) on every seed commit and a pre-push hook
# on every fixture push, an LFS filter would run on every checkout, and a credential helper or
# url.insteadOf rewrite could reach a real remote. CI has no global git config, so a test that
# leans on one is already broken there; this makes every run match. GIT_CONFIG_GLOBAL is honoured
# by git >= 2.32. The identity is synthetic and exported (not defaulted) so a developer's own
# GIT_AUTHOR_* cannot leak into fixture commits either. The env identity outranks `git config
# user.*` and `-c user.*`, so a test that must pin a particular author exports its own
# GIT_AUTHOR_* / GIT_COMMITTER_* after this call; other config keys still yield to `-c`.

git_hermetic() {
    export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
    export GIT_AUTHOR_NAME="romp tests" GIT_AUTHOR_EMAIL="tests@example.invalid"
    export GIT_COMMITTER_NAME="romp tests" GIT_COMMITTER_EMAIL="tests@example.invalid"
}
