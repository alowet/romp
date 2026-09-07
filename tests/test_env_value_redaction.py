#!/usr/bin/env python3
"""tests/conftest.py's report redaction (2026-09-05): no test report may print a value from the
process environment, or a credential-shaped token from anywhere.

The assertion rule the suite follows (never render an environment mapping, never compare a
credential's value in a message) is what keeps a live key off a terminal; the hook is the safety net
for the assertion nobody wrote that way. Pinned here:
  RedactionRule: the value set (16 characters or more; exempt, never when the name is
    credential-shaped: path-valued names, the shell's and the ones GitHub Actions exports, the XDG_*
    and PYTEST_* families, and any value that is an absolute path this machine has) and the
    replacement (every occurrence, longest value first, and each
    whitespace-separated chunk of a value that is 16 characters or more, because pprint renders a
    value with spaces as adjacent literals on separate lines and a whole-value replace misses them).
  WriteTimeCapture: a value is noted the moment it is written into os.environ (a plain assignment,
    update, setdefault, os.putenv, os.environb, mock.patch.dict), so a value present only between the
    per-test samples is redacted too.
  CredentialPattern: the second net, independent of provenance: credential-shaped tokens by pattern
    (tests/credential_patterns.py) in any report, pytest's own renderings of a failed comparison
    included (the diff's `- <a>` and `+ <a>` lines under the E marker, the quoted operands of an
    `assert '<a>' == '<b>'`, a --showlocals line `name = '<a>'`, the `+  where '<a>' = f()` and
    `+  and   '<b>' = g()` lines, the haystack of `assert '<a>' in '<b>'` and unittest's `'<a>' not
    found in '<b>'`, the elements of a list, tuple or set repr, unittest's `Lists differ:` line, its
    quoted per-element lines and its diff of a container spread over lines, and the fragments of a
    value pytest ellipsized at default verbosity or unittest shortened with `[N chars]`); a JWT by its
    shape wherever it sits, cut or whole (a cut inside its header up to the header bound, and the stated
    limit past it); the dotted rest of a token that qualifies; the head of a cut
    key bounded at the widest cut a tool makes, and a wider head taken with its cut and tail by the
    format rule, quoted or bare; the `hf_` and `rpa_` rules' letters-and-digits class and its cost;
    and the fragment rule's documented costs (a camelCase name or a digit-bearing run against a cut is
    redacted, a Capitalised word or a single-case identifier is not).
  ScrubCost: the scrub is linear: a 200 KB adversarial line (a run of repeated prefixes, of one case,
    of digits, of dashes, of dots) is scrubbed within a generous budget; the first of them took 80
    seconds before the cut-key rule's head was bounded.
  ReportShapes: the hook's work on a report object of each outcome (a failure's longrepr, a skip's
    tuple, a passed test's sections); a changed failure keeps its crash location, its message scrubbed
    in pytest's E-marked rendering, through xdist's serialization round trip.
  HookEndToEnd: subprocess pytest runs against a copy of the conftest. A test that fails with a probe
    value in its message and on its stdout prints the marker, never the value, and its short summary
    line still ends in the assertion message; the same for a value
    set inside mock.patch.dict and gone before the assertion, a header-shaped value split by
    assertDictEqual, a pattern-shaped token with no provenance, a passed test's captured output
    under -rA, a collection error, a failed comparison of two unknown-format tokens under
    --showlocals (pytest's diff lines, its assert line and the locals all show the marker), and the
    where/and/in/not-found/Lists-differ/Tuples-differ renderings of two such tokens at default
    verbosity, and the ellipsized renderings of two keys and two 64-character tokens compared with
    `==` (as strings, in a list, in a tuple, and through unittest's `[N chars]` shortening).

Every probe value is synthetic and assembled at run time ("romp-test-fixture-" + a uuid; a
pattern-shaped probe is a public key prefix joined to uuids), so no literal in this file is a
credential.
"""
import base64
import hashlib
import json
import os
import pprint
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

HERE = os.path.dirname(os.path.realpath(__file__))
CONFTEST = os.path.join(HERE, "conftest.py")
PATTERNS = os.path.join(HERE, "credential_patterns.py")


def _conftest():
    """The loaded conftest module, whatever name pytest gave it; None under a bare unittest run."""
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None)
        if f and os.path.realpath(f) == CONFTEST:
            return m
    return None


def probe_value(tag=""):
    return "romp-test-fixture-%s%s" % (tag + "-" if tag else "", uuid.uuid4().hex)


def patterned_probe(prefix="sk-ant-api03-"):
    """A token of a public key format, assembled at run time: a prefix and two uuids of tail."""
    return prefix + uuid.uuid4().hex + uuid.uuid4().hex


def _b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _jwt_parts(claims=1):
    """A fabricated JWT's three segments, assembled at run time: the public HS256 header, a claim set
    of invented values (`claims` uuids besides a subject and a timestamp), a signature hashed from a
    uuid."""
    hdr = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = {"sub": str(uuid.uuid4()), "iat": 1700000000}
    for i in range(claims):
        body["c%d" % i] = uuid.uuid4().hex
    pay = _b64url(json.dumps(body, separators=(",", ":")).encode())
    sig = _b64url(hashlib.sha256(uuid.uuid4().bytes).digest())
    return hdr, pay, sig


def _jwt_header_of(width):
    """A fabricated JOSE header of exactly `width` base64url characters (a multiple of 4: unpadded base64url
    reaches no other width): RS256 with a `kid` of uuid hex padded to fill it. Assembled at run time."""
    assert width % 4 == 0, width
    n = width * 3 // 4                                            # bytes of JSON
    pad_len = n - len('{"alg":"RS256","kid":""}')
    pad = (uuid.uuid4().hex * (pad_len // 32 + 1))[:pad_len]
    hdr = _b64url(json.dumps({"alg": "RS256", "kid": pad}, separators=(",", ":")).encode())
    assert len(hdr) == width and hdr.startswith("eyJ"), (len(hdr), width)
    return hdr


def _copy_hook(d):
    """The conftest and the pattern module it loads by path, as a subprocess pytest run sees them."""
    shutil.copy(CONFTEST, os.path.join(d, "conftest.py"))
    shutil.copy(PATTERNS, os.path.join(d, "credential_patterns.py"))


class _WithConftest(unittest.TestCase):
    def setUp(self):
        self.cf = _conftest()
        if self.cf is None:
            self.skipTest("the redaction hook lives in the pytest conftest")


class RedactionRule(_WithConftest):
    def test_values_of_sixteen_or_more_characters_are_collected(self):
        long_v, short_v = probe_value("long"), "short-value"
        env = {"SOME_TOKEN": long_v, "PLAIN": short_v, "OTHER": "x" * 16, "EMPTY": ""}
        got = self.cf.env_values_to_redact(env)
        self.assertTrue(long_v in got, "a long value is collected")
        self.assertTrue("x" * 16 in got, "sixteen characters is the floor")
        self.assertFalse(short_v in got, "a value under the floor is not")
        self.assertFalse("" in got)
        self.assertEqual(self.cf.ENV_VALUE_MIN_LEN, 16)

    def test_path_valued_shell_names_are_exempt_unless_credential_shaped(self):
        p = "/some/where/deep/enough/to/count"
        self.assertFalse(os.path.exists(p), "by NAME: the path rule below does not apply to a path that is not there")
        env = {"PWD": p, "HOME": p, "XDG_STATE_HOME": p, "PATH": p, "CLAUDE_CONFIG_DIR": p,
               "TMUX_TMPDIR": p, "ROMP_TESTS_SYSTEM_TMPDIR": p,
               # GitHub Actions: the runner's dirs and the six names setup-python exports the
               # interpreter prefix under, which every stdlib and site-packages frame of a CI
               # traceback quotes
               "GITHUB_WORKSPACE": p, "RUNNER_TEMP": p, "RUNNER_TOOL_CACHE": p, "pythonLocation": p,
               "Python_ROOT_DIR": p, "Python3_ROOT_DIR": p, "LD_LIBRARY_PATH": p, "PKG_CONFIG_PATH": p,
               "XDG_DATA_DIRS": p + os.pathsep + p}
        self.assertEqual(self.cf.env_values_to_redact(env), set(), "a traceback quotes these paths")
        env = {"PWD_TOKEN": p, "ANTHROPIC_PWD": p, "MY_SECRET_PATH": p}
        self.assertEqual(self.cf.env_values_to_redact(env), {p}, "a credential-shaped name is never exempt")
        self.assertTrue(self.cf.env_value_qualifies("SOME_TOKEN", p))
        self.assertFalse(self.cf.env_value_qualifies("TMUX_TMPDIR", p),
                         "the private tmux socket dir conftest mints is a path a failure may quote")

    def test_pytests_own_bookkeeping_names_are_exempt(self):
        # pytest writes PYTEST_CURRENT_TEST (`<node id> (setup|call|teardown)`) for every phase of
        # every test. Noted, it grew the set by one value per test (23,000 over a full run, 99% of the
        # set), slowed every report's scrub in step, and made the node id of every test already run a
        # target in later reports (a quoted child pytest line rendered `FAILED [REDACTED-ENV-VALUE]`).
        nodeid = "tests/test_x.py::Case::test_method (call)"
        env = {"PYTEST_CURRENT_TEST": nodeid, "PYTEST_VERSION": "9.1.1-" + "x" * 16,
               "PYTEST_XDIST_TESTRUNUID": uuid.uuid4().hex, "PYTEST_XDIST_WORKER": "gw" + "0" * 16,
               "PYTEST_ADDOPTS": "-p no:cacheprovider --strict-markers"}
        self.assertEqual(self.cf.env_values_to_redact(env), set())
        self.assertFalse(self.cf.note_env_value("PYTEST_CURRENT_TEST", nodeid), "the write hook applies the same rule")
        self.assertFalse(nodeid in self.cf._ENV_VALUES_SEEN)
        live = os.environ.get("PYTEST_CURRENT_TEST")
        self.assertTrue(live, "pytest sets it for the running test")
        self.assertFalse(live in self.cf._ENV_VALUES_SEEN, "the running test's own node id was not noted at its write")
        self.assertTrue(self.cf.env_value_qualifies("PYTEST_API_KEY", probe_value()), "a credential-shaped name is never exempt")

    def test_a_value_that_is_a_path_this_machine_has_is_exempt_under_any_name(self):
        # a traceback quotes the interpreter's prefix on every stdlib and site-packages frame, and a
        # developer's shell names that prefix under any variable (a pyenv root, a conda prefix), as
        # setup-python does on CI; a PATH-style list of existing dirs (LD_LIBRARY_PATH) is the same
        d = tempfile.mkdtemp(prefix="romp-test-path-value-")
        try:
            lib = os.path.join(d, "lib")
            os.mkdir(lib)
            self.assertGreaterEqual(len(d), self.cf.ENV_VALUE_MIN_LEN)
            env = {"PYENV_ROOT": d, "CONDA_PREFIX": lib, "SOME_LIBRARY_PATH": lib + os.pathsep + d}
            self.assertEqual(self.cf.env_values_to_redact(env), set(), "a path this machine has is not a value")
            self.assertFalse(self.cf.note_env_value("PYENV_ROOT", d))
            self.assertFalse(d in self.cf._ENV_VALUES_SEEN)
            missing = os.path.join(d, "no-such-" + uuid.uuid4().hex)
            self.assertTrue(self.cf.env_value_qualifies("PYENV_ROOT", missing), "a path that does not exist is a value")
            self.assertTrue(self.cf.env_value_qualifies("SOME_LIBRARY_PATH", d + os.pathsep + missing),
                            "every chunk of a list must exist")
            self.assertTrue(self.cf.env_value_qualifies("PYENV_ROOT", os.path.basename(d) + "/lib"),
                            "a relative path is a value: its existence depends on the cwd")
            self.assertTrue(self.cf.env_value_qualifies("MY_API_KEY", d), "a credential-shaped name is never exempt")
            self.assertTrue(self.cf.env_value_qualifies("PYENV_ROOT", probe_value()), "no token is a path that exists")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_the_replacement_covers_every_occurrence_longest_first(self):
        a = probe_value("a")
        b = a + "-suffix"                       # contains a: replaced whole, not as a + "-suffix"
        text = "first %s then %s and %s again; short ok" % (a, b, a)
        red = self.cf.redact_env_values(text, {a, b})
        self.assertFalse(a in red, "the value is gone from the text")
        self.assertEqual(red.count(self.cf.ENV_VALUE_REDACTED), 3)
        self.assertEqual(red, "first %s then %s and %s again; short ok" % ((self.cf.ENV_VALUE_REDACTED,) * 3))
        self.assertEqual(self.cf.redact_env_values("nothing here", {a, ""}), "nothing here")

    def test_a_value_with_whitespace_is_also_redacted_chunk_by_chunk(self):
        # pprint (assertDictEqual, assertEqual on long containers) renders a value with spaces as
        # adjacent string literals on separate lines, so the whole value is never contiguous in the
        # report and a whole-value replace leaves the token half standing
        tok = probe_value("bearer")
        v = "Authorization: Bearer " + tok
        text = pprint.pformat({"h": v}, width=40)
        self.assertFalse(v in text, "pprint split the value across lines (the case this covers)")
        self.assertTrue(tok in text)
        red = self.cf.redact_env_values(text, {v})
        self.assertFalse(tok in red, "the token chunk is gone")
        self.assertTrue(self.cf.ENV_VALUE_REDACTED in red)
        self.assertTrue("Authorization:" in red, "a chunk under the floor is no secret and stays")
        self.assertTrue("Bearer" in red)
        # the same value contiguous is still replaced whole, once
        self.assertEqual(self.cf.redact_env_values("h=" + v + ";", {v}), "h=" + self.cf.ENV_VALUE_REDACTED + ";")
        # a value without whitespace gains no chunks; a short chunk of a long value is not a value
        self.assertEqual(self.cf.redact_env_values("keep ab cd", {"ab cd " + tok}), "keep ab cd")

    def test_the_process_environment_is_what_the_hook_reads_by_default(self):
        v = probe_value("live")
        os.environ["ROMP_TEST_REDACTION_PROBE"] = v
        try:
            self.assertTrue(v in self.cf.env_values_to_redact(), "the default is os.environ")
        finally:
            os.environ.pop("ROMP_TEST_REDACTION_PROBE", None)


class WriteTimeCapture(_WithConftest):
    """A value present only between the per-test samples (set inside mock.patch.dict, or exported and
    popped in a try/finally) used to escape the set; it is noted at the write now."""

    def _gone(self, name):
        self.assertFalse(name in os.environ, "%s present" % name)

    def test_a_value_set_inside_patch_dict_and_gone_before_the_assertion_is_noted(self):
        v = probe_value("patchdict")
        with mock.patch.dict(os.environ, {"ROMP_TEST_REDACTION_PD": v}):
            self.assertTrue(v in self.cf._ENV_VALUES_SEEN, "noted at the write, inside the block")
        self._gone("ROMP_TEST_REDACTION_PD")
        self.assertTrue(v in self.cf._ENV_VALUES_SEEN, "gone from the environment, still redacted")
        self.assertTrue(v not in self.cf.redact_env_values("x " + v, self.cf._ENV_VALUES_SEEN))

    def test_every_write_path_is_noted(self):
        vals = {}
        vals["set"] = probe_value("setitem")
        os.environ["ROMP_TEST_REDACTION_W1"] = vals["set"]
        vals["update"] = probe_value("update")
        os.environ.update({"ROMP_TEST_REDACTION_W2": vals["update"]})
        vals["setdefault"] = probe_value("setdefault")
        os.environ.setdefault("ROMP_TEST_REDACTION_W3", vals["setdefault"])
        vals["putenv"] = probe_value("putenv")
        os.putenv("ROMP_TEST_REDACTION_W4", vals["putenv"])          # bypasses os.environ entirely
        vals["bytes"] = probe_value("bytes")
        os.environb[b"ROMP_TEST_REDACTION_W5"] = vals["bytes"].encode()
        try:
            for how, v in vals.items():
                self.assertTrue(v in self.cf._ENV_VALUES_SEEN, how)
        finally:
            for n in ("W1", "W2", "W3", "W5"):
                os.environ.pop("ROMP_TEST_REDACTION_" + n, None)
            os.unsetenv("ROMP_TEST_REDACTION_W4")

    def test_the_write_hook_applies_the_same_rule_as_the_sampler(self):
        short = "short-val"
        os.environ["ROMP_TEST_REDACTION_SHORT"] = short
        p = "/a/path/long/enough/to/qualify/by/length"
        was = os.environ.get("LS_COLORS")
        os.environ["LS_COLORS"] = p                                  # a path-valued shell name: exempt
        try:
            self.assertFalse(short in self.cf._ENV_VALUES_SEEN, "under the floor")
            self.assertFalse(p in self.cf._ENV_VALUES_SEEN, "a path-valued name is exempt at the write too")
        finally:
            os.environ.pop("ROMP_TEST_REDACTION_SHORT", None)
            if was is None:
                os.environ.pop("LS_COLORS", None)
            else:
                os.environ["LS_COLORS"] = was
        self.assertTrue(self.cf.note_env_value("A_TOKEN", probe_value("direct")))
        self.assertFalse(self.cf.note_env_value("A_TOKEN", "tiny"))
        self.assertFalse(self.cf.note_env_value(b"PWD", b"/x/y/z/long/enough/to/count/twice"))
        self.assertFalse(self.cf.note_env_value(3, None))

    def test_the_hook_is_installed_once(self):
        self.assertTrue(getattr(os._Environ.__setitem__, "_romp_notes_values", False))
        self.assertTrue(getattr(os.putenv, "_romp_notes_values", False))
        before = (os._Environ.__setitem__, os.putenv)
        self.cf._install_env_write_hook()
        self.assertEqual((os._Environ.__setitem__, os.putenv), before, "a second install stacks no wrapper")


class CredentialPattern(_WithConftest):
    def test_credential_shaped_tokens_are_redacted_by_pattern_whatever_their_provenance(self):
        for prefix in ("sk-ant-api03-", "sk-or-v1-", "sk-proj-", "hf_", "AIza", "rpa_"):
            tok = patterned_probe(prefix)
            text = "the child said %s and moved on" % tok
            red = self.cf.redact_credential_tokens(text)
            self.assertFalse(tok in red, prefix)
            self.assertEqual(red, "the child said %s and moved on" % self.cf.CREDENTIAL_REDACTED, prefix)

    def test_a_long_token_where_a_value_sits_is_redacted_and_ordinary_text_is_not(self):
        tok = uuid.uuid4().hex + uuid.uuid4().hex                   # 64 characters, no known prefix
        for text in ("KEY=%s" % tok, "Authorization: Bearer %s" % tok, "{'X_TOKEN': '%s'}" % tok,
                     'header: "%s"' % tok, "x-api-key:%s" % tok):
            red = self.cf.redact_credential_tokens(text)
            self.assertFalse(tok in red, text[:12])
            self.assertTrue(self.cf.CREDENTIAL_REDACTED in red)
        for text in ("sha256:1a2b3c1a2b3c", "XDG_STATE_HOME=/tmp/romp-tests-state-%s/floor" % tok,
                     "the word %s alone" % tok, "at: 1700000000", "n=%s" % uuid.uuid4().hex[:23],
                     "testMethod=test_a_long_descriptive_name_without_a_digit_in_it_stays_readable"):
            self.assertEqual(self.cf.redact_credential_tokens(text), text, text[:20])
        self.assertEqual(self.cf.redact_credential_tokens(None), None)

    def test_the_generic_floor_is_24_with_a_digit_and_40_for_mixed_case_without_one(self):
        # a 31-character hex after `=` slipped through the old floor of 32; 24 is the floor now. A token
        # of letters only is caught at 40 when it mixes cases (a base64 tail can lack a digit); an
        # all-lowercase one of any length is an identifier and stays
        red = self.cf.redact_credential_tokens
        for n in (24, 31):
            hexn = uuid.uuid4().hex[:n]
            self.assertEqual(red("KEY=%s" % hexn), "KEY=" + self.cf.CREDENTIAL_REDACTED, n)
        hex23 = uuid.uuid4().hex[:23]
        self.assertEqual(red("KEY=%s" % hex23), "KEY=%s" % hex23, "under the floor")
        mixed40, mixed39 = "aB" * 20, ("aB" * 20)[:39]
        self.assertEqual(red("KEY=%s" % mixed40), "KEY=" + self.cf.CREDENTIAL_REDACTED)
        self.assertEqual(red("KEY=%s" % mixed39), "KEY=%s" % mixed39, "39 mixed-case characters without a digit stay")
        lower44 = "a" * 44
        self.assertEqual(red("KEY=%s" % lower44), "KEY=%s" % lower44, "one case, no digit: an identifier")
        # the cost the docstring names: a test method name with a digit, 24 characters or more, in a value position
        self.assertEqual(red("testMethod=test_with_2_digits_and_a_long_name"), "testMethod=" + self.cf.CREDENTIAL_REDACTED)

    def test_a_token_alone_on_a_line_is_a_value_position(self):
        # an apiKeyHelper's stdout contract is one token on one line, with nothing to mark it as a value
        red = self.cf.redact_credential_tokens
        tok = uuid.uuid4().hex                                     # 32 characters, no known prefix
        self.assertEqual(red(tok), self.cf.CREDENTIAL_REDACTED)
        self.assertEqual(red(tok + "\n"), self.cf.CREDENTIAL_REDACTED + "\n", "a trailing newline is the contract")
        self.assertEqual(red("line one\n%s\nline three" % tok), "line one\n%s\nline three" % self.cf.CREDENTIAL_REDACTED)
        self.assertEqual(red("the word %s alone" % tok), "the word %s alone" % tok, "a token among words is not a value")
        short = uuid.uuid4().hex[:23]
        self.assertEqual(red(short), short, "the floor applies to a bare line too")

    def test_a_pytest_node_id_and_a_named_git_sha_are_kept(self):
        red = self.cf.redact_credential_tokens
        node = "tests/test_x.py::Case::test_method_with_2_digits_and_a_long_name"
        self.assertEqual(red(node), node, "the segment after :: is a test's name")
        self.assertEqual(red(node + " FAILED"), node + " FAILED")
        tok = uuid.uuid4().hex
        self.assertEqual(red("x-api-key:%s" % tok), "x-api-key:" + self.cf.CREDENTIAL_REDACTED, "one colon is still a value position")
        sha = hashlib.sha1(b"romp-test-fixture-commit").hexdigest()     # 40 lowercase hex, a commit id's shape
        self.assertTrue(any(c.isdigit() for c in sha) and len(sha) == 40)
        for text in ("commit=%s" % sha, "commit: %s" % sha, "{'commit': '%s'}" % sha, "Commit: %s" % sha,
                     "HEAD_COMMIT=%s" % sha, "objects/%s" % sha, "repo@%s" % sha):
            self.assertEqual(red(text), text, text[:12])
        for text in ("KEY=%s" % sha, sha, "sha: %s" % sha):
            self.assertEqual(red(text), text.replace(sha, self.cf.CREDENTIAL_REDACTED), text[:8])
        # a 40-hex token that is not a sha's alphabet (upper case, a '-') is not exempted by the commit word
        other = "A1" * 20
        self.assertEqual(red("commit=%s" % other), "commit=" + self.cf.CREDENTIAL_REDACTED)

    def test_pytests_own_renderings_of_a_failed_comparison_are_value_positions(self):
        # a compared token slipped the net: pytest's diff lines, its assert line and a --showlocals line
        # put the value after nothing the value positions knew (`E         - `, `assert '`, `== '`, `= '`)
        red, R = self.cf.redact_credential_tokens, self.cf.CREDENTIAL_REDACTED
        a, b = uuid.uuid4().hex, uuid.uuid4().hex                  # 32 characters each, no known prefix
        self.assertEqual(red("E         - %s" % b), "E         - " + R, "the marker and the sign stay")
        self.assertEqual(red("E         + %s" % a), "E         + " + R)
        self.assertEqual(red("E       - %s\nE       + %s\nE       ?  ^^\n" % (a, b)),
                         "E       - %s\nE       + %s\nE       ?  ^^\n" % (R, R), "unittest's diff, as pytest renders it")
        self.assertEqual(red("E       AssertionError: assert '%s' == '%s'" % (a, b)),
                         "E       AssertionError: assert '%s' == '%s'" % (R, R), "both operands")
        self.assertEqual(red('assert "%s" == "%s"' % (a, b)), 'assert "%s" == "%s"' % (R, R))
        self.assertEqual(red("E       AssertionError: '%s' != '%s'" % (a, b)),
                         "E       AssertionError: '%s' != '%s'" % (R, R), "unittest's assertEqual line")
        self.assertEqual(red("a          = '%s'" % a), "a          = '%s'" % R, "a --showlocals line")
        self.assertEqual(red('name = "%s"' % a), 'name = "%s"' % R)
        # what stays: a diff line that is more than the token, one under the floor, and a `- <token>` line
        # without the E marker (a bullet in captured output, not pytest's diff)
        for text in ("E         - the word %s here" % a, "E         - %s" % uuid.uuid4().hex[:23], "- %s" % a,
                     "E         - %s and more" % a, "E         -%s" % a):
            self.assertEqual(red(text), text, text[:16])
        # a 40-hex sha on a diff line is a value, as on a bare line: nothing there names it a commit
        sha = hashlib.sha1(b"romp-test-fixture-diff").hexdigest()
        self.assertEqual(red("E         - %s" % sha), "E         - " + R)

    def test_pytests_where_and_in_lines_and_container_reprs_are_value_positions(self):
        # the second round of renderings a compared token slipped: the `+  where '<a>' = f()` and
        # `+  and   '<b>' = g()` lines under an assert, the haystack of `assert '<a>' in '<b>'` (unittest's
        # `'<a>' not found in '<b>'`), the elements of a list, tuple or set repr (unittest's `Lists differ:`
        # line), unittest's quoted per-element lines, and its diff of a container spread over lines
        red, R = self.cf.redact_credential_tokens, self.cf.CREDENTIAL_REDACTED
        a, b = uuid.uuid4().hex, uuid.uuid4().hex                  # 32 characters each, no known prefix
        self.assertEqual(red("E        +  where '%s' = f()" % a), "E        +  where '%s' = f()" % R)
        self.assertEqual(red('E        +  and   "%s" = g()' % b), 'E        +  and   "%s" = g()' % R)
        self.assertEqual(red("E       AssertionError: assert '%s' in '%s'" % (a, b)),
                         "E       AssertionError: assert '%s' in '%s'" % (R, R), "both operands")
        self.assertEqual(red("E       AssertionError: '%s' not found in '%s'" % (a, b)),
                         "E       AssertionError: '%s' not found in '%s'" % (R, R), "unittest's assertIn line")
        self.assertEqual(red("E       AssertionError: Lists differ: ['%s', '%s'] != ['%s']" % (a, b, b)),
                         "E       AssertionError: Lists differ: ['%s', '%s'] != ['%s']" % (R, R, R))
        self.assertEqual(red("Tuples differ: ('%s',) != ('%s',)" % (a, b)), "Tuples differ: ('%s',) != ('%s',)" % (R, R))
        self.assertEqual(red("{'%s'}" % a), "{'%s'}" % R, "a set repr")
        self.assertEqual(red('["%s", "%s"]' % (a, b)), '["%s", "%s"]' % (R, R), "double quotes")
        self.assertEqual(red("E       '%s'" % a), "E       '%s'" % R, "unittest's First differing element line")
        self.assertEqual(red("E       - ['%s',\nE       -  '%s']\nE       + ['%s',\nE       +  '%s']" % (a, b, b, a)),
                         "E       - ['%s',\nE       -  '%s']\nE       + ['%s',\nE       +  '%s']" % (R, R, R, R),
                         "unittest's diff of a list, one element per line")
        # what stays: a token among the words of a haystack (nothing marks it as a value), a quoted line
        # that is more than the token, an element under the floor
        for text in ("E       AssertionError: assert 'x' in 'the word %s here'" % a, "E       '%s' and more" % a,
                     "['%s']" % uuid.uuid4().hex[:23], "the word %s alone" % a):
            self.assertEqual(red(text), text, text[:24])

    def test_an_ellipsized_value_is_redacted_on_both_sides_of_the_ellipsis(self):
        # at default verbosity pytest keeps the head and the tail of a compared value's repr, 11 to 13
        # characters each, joined by `...`; the short summary cuts a message with `...` appended and no
        # closing quote; unittest shortens a long container repr with `[N chars]`. Each fragment is a piece
        # of the value: a known prefix against the cut is a truncated key whatever follows it, and 8 or more
        # token characters against the cut are a fragment when they carry a digit or mixed case
        red, R = self.cf.redact_credential_tokens, self.cf.CREDENTIAL_REDACTED
        k = patterned_probe()                                      # a public prefix and 64 hex
        a = uuid.uuid4().hex + uuid.uuid4().hex                    # 64 hex, no known prefix
        # pytest's assert line for two keys: the prefix and 5 characters, the cut, 13 of the tail
        self.assertEqual(red("assert '%s...%s' == '%s...%s'" % (k[:12], k[-13:], k[:12], k[-13:])),
                         "assert '%s' == '%s'" % (R, R))
        # two unknown-format tokens: 12 of the head and 13 of the tail, each a fragment
        self.assertEqual(red("assert '%s...%s' == '%s...%s'" % (a[:12], a[-13:], a[:12], a[-13:])),
                         "assert '%s...%s' == '%s...%s'" % (R, R, R, R))
        # in a list or a tuple the fragments are 11 characters
        self.assertEqual(red("assert ['%s...%s'] == ['%s...%s']" % (a[:11], a[-12:], a[:11], a[-12:])),
                         "assert ['%s...%s'] == ['%s...%s']" % (R, R, R, R))
        self.assertEqual(red("assert ('%s...%s',) == ('%s...%s',)" % (a[:11], a[-11:], a[:11], a[-11:])),
                         "assert ('%s...%s',) == ('%s...%s',)" % (R, R, R, R))
        # the short summary's cut: a head against the ellipsis with no closing quote; a key's own cut, cut again
        self.assertEqual(red("FAILED test_x.py::test_y - AssertionError: assert '%s..." % a[:17]),
                         "FAILED test_x.py::test_y - AssertionError: assert '%s..." % R)
        self.assertEqual(red("assert '%s....." % k[:12]), "assert '%s.." % R)
        # unittest's [N chars]: the head beside it, the tail beside it, a fragment between two of them, and a
        # key's head against it with the tail it keeps
        self.assertEqual(red("Lists differ: ['%s[88 chars]%s'] != ['%s[88 chars]%s']" % (a[:41], a[-3:], a[:41], a[-3:])),
                         "Lists differ: ['%s[88 chars]%s'] != ['%s[88 chars]%s']" % (R, a[-3:], R, a[-3:]))
        self.assertEqual(red("['sk-[13 chars]%s']" % a[-30:]), "['sk-[13 chars]%s']" % R)
        self.assertEqual(red("'[13 chars]%s[20 chars]%s'" % (a[:12], a[-9:])), "'[13 chars]%s[20 chars]%s'" % (R, R))
        self.assertEqual(red("['%s[101 chars]%s']" % (k[:54], k[-3:])), "['%s']" % R)
        # a mixed-case fragment without a digit qualifies when the upper-case letter is not its first
        self.assertEqual(red("'abcdEfghijk...'"), "'%s...'" % R)
        # what stays: a Capitalised word, a single-case identifier, words, a fragment under the floor, a bare
        # cut, a prefix with nothing before the cut, a cut among words
        for text in ("'Connecting...'", "'Reconnecting...'", "'test_a_long_...ithout_digits'",
                     "'the quick br...the lazy dog'", "'abc1234...'", "'...'", "'hf_...'", "loading... done",
                     "'%s'" % a[:12]):
            self.assertEqual(red(text), text, text)

    def test_a_cut_keys_head_is_bounded_at_the_widest_cut_a_tool_makes(self):
        # the head between a known prefix and the cut is matched up to CUT_HEAD_MAX characters. pytest's
        # saferepr at its default 240 leaves 118 of the repr (117 of a quoted string) on each side of the
        # `...`: a --showlocals line, a traceback's arguments, the operands on a `+  where` line; unittest's
        # `[N chars]` leaves at most 63 (a common prefix of up to 22 it does not shorten, then 41); the `==`
        # operands 13. The bound is what keeps the scrub linear (ScrubCost). A head beyond it (pytest at -v
        # keeps 1198) is the format rule's own match, and that rule takes the cut and the tail with the run:
        # one marker at every width, quoted or bare
        red, R = self.cf.redact_credential_tokens, self.cf.CREDENTIAL_REDACTED
        self.assertEqual(self.cf._credpat.CUT_HEAD_MAX, 120)
        k = "sk-ant-api03-" + uuid.uuid4().hex * 5                  # 173 characters
        self.assertEqual(red("key        = '%s...%s'" % (k[:117], k[-118:])), "key        = '%s'" % R, "pytest's 240 cut, quoted")
        self.assertEqual(red("%s...%s" % (k[:118], k[-119:])), R, "the same cut of an unquoted repr")
        h = "hf_" + uuid.uuid4().hex * 5
        self.assertEqual(red("E        +  where '%s...%s' = f()" % (h[:117], h[-118:])), "E        +  where '%s' = f()" % R)
        self.assertEqual(red("['%s[90 chars]%s']" % (k[:61], k[-5:])), "['%s']" % R, "unittest's widest head, 22 + 41")
        # the head counted after the prefix, within the bound and past it (1191 is pytest's -v cut), quoted
        run = uuid.uuid4().hex * 80
        for n in (1, 19, 20, 120, 121, 130, 1191):
            self.assertEqual(red("key = 'sk-ant-%s...%s'" % (run[:n], k[-100:])), "key = '%s'" % R, n)
        self.assertEqual(red("'sk-ant-a...'"), "'%s'" % R, "one character of head is a head")
        # and past the bound in bare text, the shape a test or a child process prints itself: the tail ends
        # at the end of the text, a space, a newline or a sentence's dot, with no quote for the fragment rule
        # to see. The head was redacted and the tail showed whole until the format rules took both
        # (2026-09-06); unittest's form and a JWT cut deep in its payload are the same shape
        wide = "sk-ant-api03-" + uuid.uuid4().hex * 10               # 333 characters
        g = "AIza" + run[:136] + "..." + run[-100:]
        hdr, pay, sig = _jwt_parts(claims=6)
        jwt = "%s.%s.%s" % (hdr, pay, sig)
        self.assertGreater(len(pay), 170)
        for text, want, secret in (("cut: %s...%s" % (wide[:135], wide[-118:]), "cut: %s" % R, wide),
                                   ("%s...%s " % (wide[:135], wide[-118:]), "%s " % R, wide),
                                   ("%s...%s\n" % (wide[:135], wide[-118:]), "%s\n" % R, wide),
                                   ("%s...%s. Next" % (wide[:135], wide[-118:]), "%s. Next" % R, wide),
                                   ("%s[88 chars]%s" % (wide[:135], wide[-5:]), R, wide),
                                   ("E         - %s...%s" % (h[:133], h[-40:]), "E         - %s" % R, h),
                                   ("k=%s" % g, "k=%s" % R, run),
                                   ("%s...%s" % (jwt[:len(hdr) + 150], jwt[-118:]), R, jwt),
                                   ("key %s... more" % wide, "key %s more" % R, wide)):   # a sentence's ellipsis after a whole key
            out = red(text)
            self.assertEqual(out, want, text[:20])
            for i in range(0, len(secret) - 8 + 1):
                self.assertFalse(secret[i:i + 8] in out, "a piece of the key reached the output")

    def test_the_hf_and_rpa_rules_take_a_real_tokens_letters_and_the_wider_class_they_keep(self):
        # a Hugging Face token is `hf_` and 34 letters (gitleaks' rule: `hf_` then 34 letters of either
        # case); RunPod publishes the `rpa_` prefix and no body format. Both rules take letters and digits,
        # wider than gitleaks' class on purpose (the module docstring says why): a real token is one marker
        # whole, cut within the bound and cut past it, bare or quoted, and so is a body of the same width
        # with digits in it — pinned so that narrowing the class, or widening it, is a deliberate change.
        # The class is narrow in the other direction, so an `hf_`-prefixed identifier is not redacted; its
        # cost is a body no real token has, with `_` or `-` in it: the format rule stops at that character,
        # so past the bound the rest of such a head shows, while within it the cut rule's head class takes
        # the whole head
        red, R = self.cf.redact_credential_tokens, self.cf.CREDENTIAL_REDACTED
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        letters = "".join(alphabet[b % 52] for b in uuid.uuid4().bytes + uuid.uuid4().bytes + uuid.uuid4().bytes)[:34]
        with_digits = uuid.uuid4().hex[:17] + uuid.uuid4().hex.upper()[:17]
        self.assertTrue(letters.isalpha() and any(c.isdigit() for c in with_digits))
        for prefix in ("hf_", "rpa_"):
            for body in (letters, with_digits):
                tok = prefix + body
                self.assertEqual(len(tok), len(prefix) + 34)
                long = prefix + (uuid.uuid4().hex + uuid.uuid4().hex.upper()) * 5     # past the bound: no real token is
                for text, want in (("token %s here" % tok, "token %s here" % R), ("'%s...%s'" % (tok[:12], tok[-13:]), "'%s'" % R),
                                   ("%s...%s" % (long[:135], long[-118:]), R), ("'%s[88 chars]%s'" % (long[:135], long[-5:]), "'%s'" % R)):
                    self.assertEqual(red(text), want, text[:12])
        self.assertEqual(red("at hf_hub_download_to_cache_dir()"), "at hf_hub_download_to_cache_dir()")
        body = uuid.uuid4().hex * 10
        fake = "hf_%s_%s" % (body[:40], body[41:])                  # an underscore after 40 letters and digits
        tail = body[-40:]
        self.assertEqual(red("'%s...%s'" % (fake[:123], tail)), "'%s'" % R, "120 of head: the cut rule's")
        self.assertEqual(red("'%s...%s'" % (fake[:124], tail)), "'%s_%s...%s'" % (R, fake[44:124], R), "121: the rest of the head shows")
        self.assertEqual(red("%s...%s" % (fake[:124], tail)), "%s_%s...%s" % (R, fake[44:124], tail), "and bare, the tail too")

    def test_a_cut_identifier_or_date_is_redacted_when_it_has_a_digit_or_an_interior_capital(self):
        # the fragment rule cannot tell a camelCase or PascalCase name from a base64 tail without a digit
        # (one 8-character fragment in 25 has that shape), nor a cut date from a hex tail, so both are
        # redacted against a cut: a readability cost the module docstring names, pinned so it is a measured
        # one. A Capitalised word and a single-case identifier stay, with or without dots
        red, R = self.cf.redact_credential_tokens, self.cf.CREDENTIAL_REDACTED
        for text in ("'SessionStart...'", "'HookEndToEnd...'", "'getUserById...'", "'python38...'", "'2026-09-06...'"):
            self.assertEqual(red(text), "'%s...'" % R, text)
        self.assertEqual(red("assert 'HookEndToEnd...rTheFirstTime' == 'HookEndToEnd...TheSecondTime'"),
                         "assert '%s...%s' == '%s...%s'" % (R, R, R, R), "a diff of two hook names loses both")
        self.assertEqual(red("'2026-09-06T1...6+00:00'"), "'%s...6+00:00'" % R, "the head is a fragment; the tail is under the floor")
        for text in ("'Connecting...'", "'Abcdefgh...'", "'test_a_long_...ithout_digits'", "'snake_case_id...'", "'deadbeef...'",
                     "'ABCDEFGHIJKL...'", "'2.1.261...'", "'python3.12.3...'"):
            self.assertEqual(red(text), text, text)

    def test_a_diff_line_pytest_truncated_mid_token_is_a_fragment_position(self):
        # pytest truncates an explanation over 8 lines or 640 characters and appends `...` to its last
        # line; a diff line so cut ends in `...` instead of the token's end the diff rule requires, and its
        # marker and sign are no fragment position. A piece of a compared JWT showed that way. The marker
        # and sign stay; the same floor and letter rules as any fragment apply; a `...` that does not end
        # the line is not pytest's cut
        red, R = self.cf.redact_credential_tokens, self.cf.CREDENTIAL_REDACTED
        a = uuid.uuid4().hex + uuid.uuid4().hex
        for pre in ("E         + ", "E         - ", "E       -  "):
            self.assertEqual(red("%s%s..." % (pre, a[:60])), "%s%s..." % (pre, R), pre)
            self.assertEqual(red("%s%s..." % (pre, a[:8])), "%s%s..." % (pre, R), "8 characters is the floor")
        self.assertEqual(red("E         + %s.%s..." % (a[:30], a[30:50])), "E         + %s..." % R, "the dotted rest rides along")
        self.assertEqual(red("E         + %s...\nE         \n" % a[:60]), "E         + %s...\nE         \n" % R)
        for text in ("E         + abcdefg...", "E         + Connecting...", "E         + test_a_long_...", "E         + %s... more" % a[:30],
                     "+ %s..." % a[:60]):
            self.assertEqual(red(text), text, text[:20])

    def test_a_qualifying_token_takes_its_dotted_rest(self):
        # a dotted token in a value position was matched to its first dot; the `.<more>` segments ride along
        # once the first run qualifies. A dot with no token character after it (a sentence's, an ellipsis)
        # is not taken, and a run that does not qualify on its own is not helped by its dots
        red, R = self.cf.redact_credential_tokens, self.cf.CREDENTIAL_REDACTED
        tok, sig = uuid.uuid4().hex, uuid.uuid4().hex[:20]
        for text, want in (("KEY=%s.%s" % (tok, sig), "KEY=" + R), ("E         - %s.%s" % (tok, sig), "E         - " + R),
                           ("%s.%s" % (tok, sig), R), ("KEY=%s. Next" % tok, "KEY=%s. Next" % R), ("KEY=%s..." % tok, "KEY=%s..." % R),
                           ("['%s.x.y', 'b']" % tok, "['%s', 'b']" % R)):
            self.assertEqual(red(text), want, text[:12])
        # the costs the docstring names: a digit-bearing file name in a value position loses its extension,
        # a uuid-named file alone on a line is redacted
        self.assertEqual(red("file=test_kernel_webpush_2026.py"), "file=" + R)
        self.assertEqual(red("%s.jsonl" % uuid.uuid4()), R)
        for text in ("version=2.1.261.3", "module: kernel.sdk_backend.thing", "n=%s.%s" % (uuid.uuid4().hex[:23], sig)):
            self.assertEqual(red(text), text, text)

    def test_a_jwt_is_redacted_whole_wherever_it_sits(self):
        # a JWT has no provider prefix; its shape is the format: `eyJ` (a base64url JSON object) and dotted
        # segments. Before the rule a JWT in a value position lost only its header, a public constant, and
        # kept its payload and signature; alone on a line or on a diff line nothing of it was matched
        red, R = self.cf.redact_credential_tokens, self.cf.CREDENTIAL_REDACTED
        hdr, pay, sig = _jwt_parts()
        jwt = "%s.%s.%s" % (hdr, pay, sig)
        for text, want in (("token=%s" % jwt, "token=" + R), ("Authorization: Bearer %s" % jwt, "Authorization: Bearer " + R),
                           ("{'token': '%s'}" % jwt, "{'token': '%s'}" % R), ("E       assert '%s' == 'x'" % jwt, "E       assert '%s' == 'x'" % R),
                           ("E         - %s" % jwt, "E         - " + R), (jwt, R), (jwt + "\n", R + "\n"),
                           ("Authorization: WebPush %s" % jwt, "Authorization: WebPush " + R),     # a scheme no value position knows
                           ("token=%s. Next" % jwt, "token=%s. Next" % R)):                        # a sentence's dot is not a segment
            self.assertEqual(red(text), want, text[:24])
        # the header the kernel's push code mints: a JWT after `t=`, a public key after `k=`
        self.assertEqual(red("Authorization: vapid t=%s, k=%s" % (jwt, _b64url(hashlib.sha512(uuid.uuid4().bytes).digest()))),
                         "Authorization: vapid t=%s, k=%s" % (R, R))
        # two segments (unsecured), five (JWE), a 20-character header ({"alg":"ES256"}), the shortest ({"alg":"none"})
        es = _b64url(json.dumps({"alg": "ES256"}, separators=(",", ":")).encode())
        none_hdr = _b64url(json.dumps({"alg": "none"}, separators=(",", ":")).encode())
        self.assertEqual((len(es), len(none_hdr)), (20, 19))
        for tok in ("%s.%s" % (hdr, pay), ".".join([hdr] + [_b64url(hashlib.sha256(uuid.uuid4().bytes).digest()[:n]) for n in (32, 12, 30, 16)]),
                    "%s.%s.%s" % (es, pay, sig), "%s.%s." % (none_hdr, pay)):
            self.assertEqual(red("t=%s" % tok), "t=" + R + ("." if tok.endswith(".") else ""), tok[:8])
        # a header past JWT_HEADER_MAX falls to the generic rule and its dotted rest: whole in a value
        # position, alone on a line and on a diff line
        self.assertEqual(self.cf._credpat.JWT_HEADER_MAX, 256)
        long_hdr = _b64url(json.dumps({"alg": "RS256", "kid": uuid.uuid4().hex, "x5c": [_b64url(uuid.uuid4().bytes * 14)]},
                                      separators=(",", ":")).encode())
        self.assertGreater(len(long_hdr), 256)
        lj = "%s.%s.%s" % (long_hdr, pay, sig)
        for text, want in (("token=%s" % lj, "token=" + R), (lj, R), ("E         - %s" % lj, "E         - " + R)):
            self.assertEqual(red(text), want, text[:12])
        # what stays: too little after the prefix to be a header, the prefix alone, a header with no dot after it
        for text in ("x eyJab.cd y", "'eyJ'", "a %s b" % hdr):
            self.assertEqual(red(text), text, text)

    def test_an_ellipsized_jwt_is_redacted_with_its_dotted_head_and_tail(self):
        # pytest's cuts of a JWT: the `==` operands (12 and 13 characters), saferepr's 240 (a head of 117
        # holding the header, a dot and part of the payload; a tail of 118 that may begin at a dot), the
        # short summary's cut with no tail; unittest's `[N chars]` with the prefix alone before it, its
        # 5 + 41 head, and a fragment between two cuts. No 8-character piece of any segment survives
        red, R = self.cf.redact_credential_tokens, self.cf.CREDENTIAL_REDACTED
        hdr, pay, sig = _jwt_parts(claims=6)
        jwt = "%s.%s.%s" % (hdr, pay, sig)
        self.assertGreater(len(jwt), 240)
        for text, want in (("assert '%s...%s' == '%s...%s'" % (jwt[:12], jwt[-13:], jwt[:12], jwt[-13:]), "assert '%s' == '%s'" % (R, R)),
                           ("j          = '%s...%s'" % (jwt[:117], jwt[-118:]), "j          = '%s'" % R),
                           ("E        +  where '%s...%s' = f()" % (jwt[:117], jwt[-118:]), "E        +  where '%s' = f()" % R),
                           ("j = '%s...%s'" % (jwt[:117], jwt[jwt.rindex("."):]), "j = '%s'" % R),
                           ("FAILED t.py::t - AssertionError: assert '%s..." % jwt[:60], "FAILED t.py::t - AssertionError: assert '%s" % R),
                           ("Lists differ: ['eyJ[35 chars]%s'] != ['eyJ[35 chars]%s']" % (jwt[38:90], jwt[38:80]),
                            "Lists differ: ['%s'] != ['%s']" % (R, R)),
                           ("['%s[101 chars]%s']" % (jwt[:54], jwt[-3:]), "['%s']" % R),
                           ("'[13 chars]%s[20 chars]%s'" % (jwt[40:75], jwt[-12:]), "'[13 chars]%s[20 chars]%s'" % (R, R))):
            out = red(text)
            self.assertEqual(out, want, text[:30])
            for seg in (hdr, pay, sig):
                for i in range(0, len(seg) - 8 + 1):
                    self.assertFalse(seg[i:i + 8] in out, "a piece of a segment reached the output")
        self.assertEqual(red("'eyJ...'"), "'eyJ...'", "the prefix alone around a cut shows nothing")

    def test_a_jwt_cut_inside_its_header_is_taken_up_to_the_header_bound(self):
        # the cut rule's header is bounded at JWT_HEADER_MAX, the whole-token rule's bound, so a JWT cut
        # anywhere inside any header an installation meets is one marker, bare or quoted, on a diff line
        # and in a value position (bounded at CUT_HEAD_MAX until 2026-09-06, a cut 121 or more characters
        # past `eyJ` inside a longer header was taken by no rule in bare text, head and tail shown). A
        # whole header of any width within the bound with the cut in the payload is the JWT rule's match,
        # as before. The bound is on the head, not the header: a cut within the first JWT_HEADER_MAX
        # characters of a longer header is taken too. What is not: a head with more than JWT_HEADER_MAX
        # characters between `eyJ` and the first dot or the cut — a cut deeper than that inside such a
        # header, or a payload cut after a whole header past the bound. In a value position the generic
        # rule takes the head and the tail shows; quoted, the fragment rule takes both; in bare text the
        # header shows, whole with the cut and tail when the cut is inside it, and up to its dot when the
        # cut is in the payload, whose own `eyJ` (a JSON payload begins with one too) starts the cut
        # rule's match. The limit the docstring states, pinned as a measured cost (no enumerated tool
        # leaves a head of that width)
        red, R = self.cf.redact_credential_tokens, self.cf.CREDENTIAL_REDACTED
        M = self.cf._credpat.JWT_HEADER_MAX
        _hdr, pay, sig = _jwt_parts(claims=6)

        def check(tok, where):
            for text, want in (("x %s y" % tok, "x %s y" % R), ("%s\n" % tok, "%s\n" % R), ("log: %s" % tok, "log: %s" % R),
                               ("'%s'" % tok, "'%s'" % R), ("E         - %s" % tok, "E         - %s" % R)):
                out = red(text)
                self.assertEqual(out, want, (where, text[:12]))
                for piece in (tok[:tok.index("...")], tok[tok.index("...") + 3:]):
                    for i in range(0, len(piece) - 8 + 1):
                        self.assertFalse(piece[i:i + 8] in out, (where, "a piece of the token reached the output"))

        for width in (124, 200, M):                      # 124 = `eyJ` + 121, the first width past the old bound
            hdr = _jwt_header_of(width)
            jwt = "%s.%s.%s" % (hdr, pay, sig)
            for cut in sorted({100, 124, 150, width - 1, width}):
                if cut <= width:                          # inside the header, up to and including its last character
                    check("%s...%s" % (jwt[:cut], jwt[-40:]), (width, cut))
            check("%s...%s" % (jwt[:width + 1 + 150], jwt[-40:]), (width, "payload"))
        wide = "%s.%s.%s" % (_jwt_header_of(M + 4), pay, sig)
        for cut in (150, M + 3):                          # inside a header past the bound, within the head bound
            check("%s...%s" % (wide[:cut], wide[-40:]), ("wide header", cut))
        hdr = wide[:M + 4]
        tok = "%s...%s" % (hdr, wide[-40:])                 # the whole header before the cut: a head past the bound
        self.assertEqual(red("x %s y" % tok), "x %s y" % tok, "bare: nothing takes it")
        self.assertEqual(red("log: %s" % tok), "log: %s...%s" % (R, wide[-40:]), "a value position: the head; the tail shows")
        self.assertEqual(red("'%s'" % tok), "'%s...%s'" % (R, R), "quoted: the fragment rule, twice")
        self.assertTrue(pay.startswith("eyJ"), "a JSON payload begins with `eyJ` as the header does")
        tok = "%s...%s" % (wide[:M + 4 + 1 + 150], wide[-40:])   # the same header whole, a payload cut deep
        self.assertEqual(red("x %s y" % tok), "x %s.%s y" % (hdr, R), "bare: the header shows; the payload's `eyJ` starts the cut rule's match")
        self.assertEqual(red("log: %s" % tok), "log: %s...%s" % (R, wide[-40:]))
        self.assertEqual(red("'%s'" % tok), "'%s...%s'" % (R, R))

    def test_the_two_nets_are_applied_in_order_and_the_conftest_loads_the_pattern_file(self):
        v = probe_value("env")
        tok = patterned_probe()
        text = "env %s and token %s" % (v, tok)
        red = self.cf.redact_report_text(text, {v})
        self.assertEqual(red, "env %s and token %s" % (self.cf.ENV_VALUE_REDACTED, self.cf.CREDENTIAL_REDACTED))
        self.assertEqual(self.cf.CREDENTIAL_REDACTED, "[REDACTED-CREDENTIAL]")
        self.assertEqual(os.path.realpath(self.cf._credpat.__file__), PATTERNS, "the conftest loads this file")
        self.assertIs(self.cf.redact_credential_tokens("x"), "x")


class ScrubCost(_WithConftest):
    """The scrub is linear in its input. A rule tried at every occurrence of its prefix inside a long run
    it never consumes must do bounded work per occurrence: the cut-key rule's unbounded head made the
    scrub quadratic (80 seconds for a 200 KB line of repeated `hf_`, 0.8 for 20 KB), and the JWT rule's
    header would have been the same on repeated `eyJ`. The budget is generous for CI; each line here
    took 0.16 seconds or less on the development box after the fix, minutes before it."""

    BUDGET_SECONDS = 5.0

    def test_a_200_kb_adversarial_line_is_scrubbed_within_the_budget(self):
        n = 200 * 1024

        def rep(unit):
            return unit * (n // len(unit) + 1)
        hexrun = rep("a1b2c3d4e5f6")
        lines = {
            "repeated hf_": rep("hf_"), "repeated rpa_": rep("rpa_"), "repeated hf_-": rep("hf_-"),
            "hf_1 off a value position": " " + rep("hf_1"), "repeated sk-ant-": rep("sk-ant-"), "repeated AIza": rep("AIza"),
            "repeated eyJ": rep("eyJ"), "eyJ1 off a value position": " " + rep("eyJ1"), "dotted eyJa.": rep("eyJa."),
            "one case": rep("a") + " x", "mixed case": rep("aB") + " x", "digits": rep("1") + " x",
            "underscores": rep("_"), "dashes": rep("-"),
            "hex after a quote": "'" + hexrun, "hex after a cut": "..." + hexrun, "hex on a diff line": "E         - " + hexrun + " x",
            "hex on a cut diff line": "E         - " + hexrun + "...",
            "dotted segments": rep(".a"), "dotted after =": "=" + hexrun[:24] + rep(".a") + " x",
            "repeated cuts": rep("..."), "repeated [N chars]": rep("[1 chars]"),
            # a format match and then a cut, or a `..` or `[x chars]` that is not one, repeated; one huge key cut once
            "sk-ant- + 121 + ...": rep("sk-ant-" + "a" * 121 + "..."), "hf_ + 121 + [1 chars]": rep("hf_" + "a" * 121 + "[1 chars]"),
            "sk-ant- + 20 + ..": rep("sk-ant-" + "a" * 20 + ".."), "sk-ant- + 20 + [x chars]": rep("sk-ant-" + "a" * 20 + "[x chars]"),
            "eyJ + 300 + ...": rep("eyJ" + "a" * 300 + ".b" + "..."), "one huge cut key": "sk-ant-" + "a" * (n // 2) + "..." + "b" * (n // 2),
        }
        for name, line in lines.items():
            t0 = time.perf_counter()
            self.cf.redact_credential_tokens(line)
            dt = time.perf_counter() - t0
            self.assertLess(dt, self.BUDGET_SECONDS, "%s: %.1f s for %d characters" % (name, dt, len(line)))


class ReportShapes(_WithConftest):
    """_redact_report on report objects of each outcome: the values it knows are gone from every text."""

    def _seen(self, v):
        self.cf._ENV_VALUES_SEEN.add(v)

    def test_a_failures_longrepr_and_sections_are_redacted(self):
        v = probe_value("fail")
        self._seen(v)
        rep = SimpleNamespace(failed=True, longrepr="AssertionError: got " + v,
                              sections=[("Captured stdout call", "printed " + v + "\n")])
        self.cf._redact_report(rep)
        self.assertEqual(rep.longrepr, "AssertionError: got " + self.cf.ENV_VALUE_REDACTED)
        self.assertEqual(rep.sections, [("Captured stdout call", "printed " + self.cf.ENV_VALUE_REDACTED + "\n")])

    def test_a_passed_tests_sections_are_redacted_too(self):
        v = probe_value("pass")
        self._seen(v)
        rep = SimpleNamespace(failed=False, longrepr=None, sections=[("Captured stderr call", v)])
        self.cf._redact_report(rep)
        self.assertEqual(rep.sections, [("Captured stderr call", self.cf.ENV_VALUE_REDACTED)], "-rA shows these")
        self.assertIsNone(rep.longrepr)

    def test_a_skips_reason_tuple_keeps_its_shape(self):
        v = probe_value("skip")
        self._seen(v)
        rep = SimpleNamespace(failed=False, longrepr=("tests/test_x.py", 12, "Skipped: no auth for " + v), sections=[])
        self.cf._redact_report(rep)
        self.assertEqual(rep.longrepr, ("tests/test_x.py", 12, "Skipped: no auth for " + self.cf.ENV_VALUE_REDACTED))
        rep = SimpleNamespace(failed=False, longrepr=("tests/test_x.py", 12, "Skipped: fine"), sections=[])
        self.cf._redact_report(rep)
        self.assertEqual(rep.longrepr, ("tests/test_x.py", 12, "Skipped: fine"), "unchanged when nothing matched")

    def test_an_unchanged_longrepr_object_is_left_as_pytests_own(self):
        obj = object()
        rep = SimpleNamespace(failed=True, longrepr=obj, sections=[])
        self.cf._redact_report(rep)
        self.assertIs(rep.longrepr, obj, "no match: pytest's rich rendering is kept")
        tok = patterned_probe()
        rep = SimpleNamespace(failed=True, longrepr="the child printed " + tok, sections=[])
        self.cf._redact_report(rep)
        self.assertEqual(rep.longrepr, "the child printed " + self.cf.CREDENTIAL_REDACTED, "the pattern net runs here too")

    def test_a_changed_failures_longrepr_keeps_its_crash_location(self):
        # the short test summary ends in reprcrash.message, junitxml's message attribute reads it, and
        # xdist serializes a longrepr with a traceback and a crash structurally; a plain str has
        # neither, so a scrubbed failure's summary line showed the traceback's first line instead
        # (`def test_x():`, `self = <Case testMethod=...>`) and lost the message under -n
        import pytest
        tok = patterned_probe()
        try:
            raise AssertionError("the message carries " + tok)
        except AssertionError:
            lr = pytest.ExceptionInfo.from_current().getrepr(style="long")
        self.assertTrue(tok in str(lr) and tok in lr.reprcrash.message, "the shape under test")
        rep = SimpleNamespace(failed=True, longrepr=lr, sections=[])
        self.cf._redact_report(rep)
        self.assertIsNot(rep.longrepr, lr)
        self.assertFalse(isinstance(rep.longrepr, str), "a longrepr, not plain text")
        text = str(rep.longrepr)
        self.assertFalse(tok in text)
        self.assertEqual(text, self.cf.redact_report_text(str(lr)), "rendered as the scrubbed text, as is")
        crash = rep.longrepr.reprcrash
        self.assertEqual((crash.path, crash.lineno), (lr.reprcrash.path, lr.reprcrash.lineno))
        self.assertEqual(crash.message, "AssertionError: the message carries " + self.cf.CREDENTIAL_REDACTED)
        # xdist's round trip, the one a worker's report takes to the controller
        report = pytest.TestReport("tests/test_x.py::test_x", ("tests/test_x.py", 3, "test_x"), {}, "failed",
                                   rep.longrepr, "call")
        back = pytest.TestReport._from_json(report._to_json())
        self.assertEqual(back.longrepr.reprcrash.message, crash.message, "the message reaches the controller")
        self.assertEqual(str(back.longrepr), text)
        self.assertFalse(tok in str(back.longrepr))
        # the message of a failed comparison carries pytest's diff without the `E` marker the pattern
        # net's diff-line rule is keyed on; under CI the short summary prints every line of it
        x, y = uuid.uuid4().hex * 2, uuid.uuid4().hex * 2
        try:
            assert x == y
        except AssertionError:
            lr = pytest.ExceptionInfo.from_current().getrepr(style="long")
        self.assertTrue(any(line.lstrip().startswith("- ") for line in lr.reprcrash.message.split("\n")),
                        "the shape under test: a diff line in the message, unmarked")
        rep = SimpleNamespace(failed=True, longrepr=lr, sections=[])
        self.cf._redact_report(rep)
        for v in (x, y):
            for i in range(0, len(v) - 8 + 1):
                self.assertFalse(v[i:i + 8] in rep.longrepr.reprcrash.message, "a piece reached the crash message")
                self.assertFalse(v[i:i + 8] in str(rep.longrepr))
        self.assertFalse(any(line.startswith("E") for line in rep.longrepr.reprcrash.message.split("\n")),
                         "unwrapped: the marker is not left in")
        self.assertTrue(rep.longrepr.reprcrash.message.lstrip().startswith(("assert '", "AssertionError: assert '")))
        self.assertGreaterEqual(rep.longrepr.reprcrash.message.count(self.cf.CREDENTIAL_REDACTED), 4,
                                "both operands and both diff lines")
        # a longrepr with no crash location (a collection error's) is the plain text, as before
        class _CollectErrorRepr:
            def __str__(self):
                return "the child printed " + tok
        rep = SimpleNamespace(failed=True, longrepr=_CollectErrorRepr(), sections=[])
        self.cf._redact_report(rep)
        self.assertEqual(rep.longrepr, "the child printed " + self.cf.CREDENTIAL_REDACTED)

    def test_both_hooks_are_declared(self):
        self.assertTrue(callable(getattr(self.cf, "pytest_runtest_makereport", None)))
        self.assertTrue(callable(getattr(self.cf, "pytest_collectreport", None)))


class HookEndToEnd(unittest.TestCase):
    def _run(self, d, *args, env=None):
        """A child pytest over the files in `d`. Its environment is this process's without CI and
        BUILD_NUMBER: with either set (pytest's `running_on_ci`) pytest neither truncates a long
        assertion explanation nor trims the short summary's message to the terminal width, and the
        tests here pin the truncated rendering wherever the suite runs. `env` adds variables on top
        (a probe value; CI itself, for the untruncated rendering)."""
        child = dict(os.environ)
        for name in ("CI", "BUILD_NUMBER"):
            child.pop(name, None)
        child.update(env or {})
        # The copied conftest mints its own private temp root under TMPDIR and removes it at run end;
        # pointed at `d`, that root and the state dir inside it go with the scratch dir even when the
        # child is killed before its unconfigure runs (the timeout below).
        child["TMPDIR"] = d
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", d] + list(args),
                           cwd=d, env=child, capture_output=True, text=True, timeout=180)
        return r.returncode, r.stdout + r.stderr

    def test_a_failing_test_that_renders_an_environment_value_prints_the_marker(self):
        d = tempfile.mkdtemp()
        try:
            _copy_hook(d)
            with open(os.path.join(d, "test_probe_leak.py"), "w") as fh:
                fh.write("import os\n\n"
                         "def test_leak():\n"
                         "    v = os.environ['ROMP_TEST_REDACTION_PROBE']\n"
                         "    print('stdout carries ' + v)\n"
                         "    assert v == 'something else', 'the message carries ' + v\n")
            v = probe_value("probe")
            rc, out = self._run(d, "test_probe_leak.py", env={"ROMP_TEST_REDACTION_PROBE": v})
            self.assertNotEqual(rc, 0, "the probe test fails by design")
            self.assertTrue("1 failed" in out, "the run reports the failure")
            self.assertFalse(v in out, "the probe value reached no line of the report")
            self.assertGreaterEqual(out.count("[REDACTED-ENV-VALUE]"), 2, "the message and the captured stdout both show the marker")
            self.assertTrue("FAILED test_probe_leak.py::test_leak - AssertionError: the message carries" in out,
                            "the short test summary still ends in the assertion message, not the traceback's first line")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_a_patch_dict_value_a_split_header_and_a_patterned_token_all_print_markers(self):
        # three leaks the first hook missed, one run: a value set inside mock.patch.dict and gone
        # before the assertion (never in the environment at a sample); a header-shaped value that
        # assertDictEqual's pprint splits so the token half stands alone; a pattern-shaped token
        # that never touched the environment at all (read from a file)
        d = tempfile.mkdtemp()
        try:
            _copy_hook(d)
            probes = {"pd": probe_value("patchdict"), "hdr_tok": probe_value("header"), "pat": patterned_probe()}
            with open(os.path.join(d, "probes.json"), "w") as fh:
                json.dump(probes, fh)
            with open(os.path.join(d, "test_probe_three.py"), "w") as fh:
                fh.write("import json, os, unittest\n"
                         "from unittest import mock\n"
                         "P = json.load(open(os.path.join(os.path.dirname(__file__), 'probes.json')))\n\n"
                         "def test_patch_dict():\n"
                         "    with mock.patch.dict(os.environ, {'ROMP_TEST_PROBE_PD': P['pd']}):\n"
                         "        pass\n"
                         "    assert 'ROMP_TEST_PROBE_PD' not in os.environ\n"
                         "    assert P['pd'] == 'something else', 'the message carries ' + P['pd']\n\n"
                         "class Header(unittest.TestCase):\n"
                         "    def test_header(self):\n"
                         "        os.environ['ROMP_TEST_PROBE_HDR'] = 'Authorization: Bearer ' + P['hdr_tok']\n"
                         "        self.assertDictEqual({'Authorization': 'Bearer ' + P['hdr_tok']},\n"
                         "                             {'Authorization': 'Bearer other'})\n\n"
                         "def test_pattern():\n"
                         "    assert P['pat'] == 'something else', 'the message carries ' + P['pat']\n")
            rc, out = self._run(d, "test_probe_three.py")
            self.assertNotEqual(rc, 0)
            self.assertTrue("3 failed" in out, out[-600:])
            for name, v in probes.items():
                self.assertFalse(v in out, "%s reached the report" % name)
            self.assertGreaterEqual(out.count("[REDACTED-ENV-VALUE]"), 2, "the patch.dict message and the header chunk")
            self.assertGreaterEqual(out.count("[REDACTED-CREDENTIAL]"), 1, "the patterned token, with no provenance")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_a_failing_comparison_of_two_tokens_prints_the_marker_on_every_rendering(self):
        # a plain `assert a == b` on two tokens of unknown format, under --showlocals: pytest renders the
        # pair on its assert line (abbreviated at -q), one per diff line, and once more per local. The
        # unittest form renders `'<a>' != '<b>'` and the same diff lines. No line shows either token.
        d = tempfile.mkdtemp()
        try:
            _copy_hook(d)
            probes = {"a": uuid.uuid4().hex, "b": uuid.uuid4().hex}
            with open(os.path.join(d, "probes.json"), "w") as fh:
                json.dump(probes, fh)
            with open(os.path.join(d, "test_probe_compare.py"), "w") as fh:
                fh.write("import json, os, unittest\n"
                         "P = json.load(open(os.path.join(os.path.dirname(__file__), 'probes.json')))\n\n"
                         "def test_plain():\n"
                         "    a = P['a']\n"
                         "    b = P['b']\n"
                         "    assert a == b\n\n"
                         "class Cmp(unittest.TestCase):\n"
                         "    def test_unittest(self):\n"
                         "        self.assertEqual(P['a'], P['b'])\n")
            rc, out = self._run(d, "--showlocals", "test_probe_compare.py")
            self.assertNotEqual(rc, 0)
            self.assertTrue("2 failed" in out, out[-600:])
            for name, v in probes.items():
                self.assertFalse(v in out, "%s reached the report" % name)
            # the plain assert: two diff lines and two locals; the unittest one: its message and two diff lines
            self.assertGreaterEqual(out.count("[REDACTED-CREDENTIAL]"), 8, out[-1200:])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_the_where_and_in_and_container_renderings_of_two_tokens_print_the_marker(self):
        # the renderings the comparison test above does not reach: `where '<a>' = f()` (the operands are
        # not both str, so there is no diff), `and   '<b>' = g()`, the haystack of `assert '<a>' in '<b>'`,
        # unittest's `'<a>' not found in '<b>'`, and its `Lists differ:` / `Tuples differ:` blocks (the
        # container line, the quoted per-element lines, the diff spread over lines). 32-character tokens:
        # pytest renders each of these in full at default verbosity, so no line depends on the ellipsis rule
        d = tempfile.mkdtemp()
        try:
            _copy_hook(d)
            probes = {"a": uuid.uuid4().hex, "b": uuid.uuid4().hex}
            with open(os.path.join(d, "probes.json"), "w") as fh:
                json.dump(probes, fh)
            with open(os.path.join(d, "test_probe_forms.py"), "w") as fh:
                fh.write("import json, os, unittest\n"
                         "P = json.load(open(os.path.join(os.path.dirname(__file__), 'probes.json')))\n\n"
                         "def f():\n    return P['a']\n\n"
                         "def g():\n    return P['b']\n\n"
                         "def h():\n    return 3\n\n"
                         "def test_where():\n    assert f() == 3\n\n"
                         "def test_and():\n    assert h() == g()\n\n"
                         "def test_in():\n    assert f() in g()\n\n"
                         "class Cmp(unittest.TestCase):\n"
                         "    def test_not_found(self):\n        self.assertIn(P['a'], P['b'])\n"
                         "    def test_lists(self):\n        self.assertEqual([P['a'], P['b']], [P['b'], P['a']])\n"
                         "    def test_tuple(self):\n        self.assertEqual((P['a'],), (P['b'],))\n")
            rc, out = self._run(d, "test_probe_forms.py")
            self.assertNotEqual(rc, 0)
            self.assertTrue("6 failed" in out, out[-600:])
            for name, v in probes.items():
                self.assertFalse(v in out, "%s reached the report" % name)
                for i in range(0, len(v) - 8 + 1):
                    self.assertFalse(v[i:i + 8] in out, "a fragment of %s reached the report" % name)
            # where + its assert line (2), and + its (2), in + where + and (4), not found (2), the lists block
            # (the container line 4, two element lines, four diff lines), the tuples block (2 + 2 + 2)
            self.assertGreaterEqual(out.count("[REDACTED-CREDENTIAL]"), 26, out[-2000:])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_an_ellipsized_comparison_prints_the_marker_on_every_fragment(self):
        # at default verbosity pytest ellipsizes the operands of a failed `==`: two keys of a public format
        # render as the prefix, 5 characters, `...` and 13 of the tail; two unknown-format tokens as 12- and
        # 13-character fragments; a list or a tuple of them as 11-character ones. unittest shortens a long
        # list's repr with `[N chars]` and spreads its diff over lines. No 8-character piece of any value
        # survives on any line
        d = tempfile.mkdtemp()
        try:
            _copy_hook(d)
            probes = {"k1": patterned_probe(), "k2": patterned_probe(),
                      "a": uuid.uuid4().hex + uuid.uuid4().hex, "b": uuid.uuid4().hex + uuid.uuid4().hex}
            with open(os.path.join(d, "probes.json"), "w") as fh:
                json.dump(probes, fh)
            with open(os.path.join(d, "test_probe_ellipsis.py"), "w") as fh:
                fh.write("import json, os, unittest\n"
                         "P = json.load(open(os.path.join(os.path.dirname(__file__), 'probes.json')))\n\n"
                         "def test_keys():\n    assert P['k1'] == P['k2']\n\n"
                         "def test_tokens():\n    assert P['a'] == P['b']\n\n"
                         "def test_list():\n    assert [P['a']] == [P['b']]\n\n"
                         "def test_tuple():\n    assert (P['k1'],) == (P['k2'],)\n\n"
                         "class Cmp(unittest.TestCase):\n"
                         "    def test_three(self):\n"
                         "        self.assertEqual([P['a'], P['b'], P['a']], [P['b'], P['a'], P['b']])\n"
                         "    def test_keys(self):\n        self.assertEqual([P['k1'], P['k2']], [P['k2'], P['k1']])\n")
            rc, out = self._run(d, "test_probe_ellipsis.py")
            self.assertNotEqual(rc, 0)
            self.assertTrue("6 failed" in out, out[-600:])
            for name, v in probes.items():
                for i in range(0, len(v) - 8 + 1):
                    self.assertFalse(v[i:i + 8] in out, "a piece of %s reached the report" % name)
            # the keys' assert line (2) and diff (2); the tokens' four fragments and diff (6); the list's (6);
            # the tuple's (4); the three-element block (2 heads, 2 elements, 6 diff lines); the keys' block (8)
            self.assertGreaterEqual(out.count("[REDACTED-CREDENTIAL]"), 30, out[-2500:])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_a_failing_comparison_of_two_jwts_prints_the_marker_on_every_rendering(self):
        # two fabricated JWTs, long enough for every cut: pytest's `==` operands and diff lines (which skip
        # the identical header, and which its 640-character truncation cuts mid-token with `...` appended),
        # the 240 cut of --showlocals, a list through unittest's `[N chars]`, and a bare print; and two long
        # unknown-format tokens, whose diff's second line that truncation always cuts. No 8-character piece
        # of any segment of any token survives on any line. The child runs twice, because pytest switches
        # the truncation off when CI or BUILD_NUMBER is set (`running_on_ci`; GitHub Actions sets CI) and
        # then also prints each failure's whole message in the short summary instead of one trimmed line:
        # once without them (the cut renderings) and once with CI set (the whole diff lines, and the
        # summary's repeat of every message)
        d = tempfile.mkdtemp()
        try:
            _copy_hook(d)
            j = {name: "%s.%s.%s" % _jwt_parts(claims=6) for name in ("a", "b")}
            j.update({name: uuid.uuid4().hex * 14 for name in ("x", "y")})              # 448 characters each
            with open(os.path.join(d, "probes.json"), "w") as fh:
                json.dump(j, fh)
            with open(os.path.join(d, "test_probe_jwt.py"), "w") as fh:
                fh.write("import json, os, unittest\n"
                         "P = json.load(open(os.path.join(os.path.dirname(__file__), 'probes.json')))\n\n"
                         "def test_plain():\n    a = P['a']\n    b = P['b']\n"
                         "    print('Authorization: Bearer ' + a)\n    assert a == b\n\n"
                         "def test_hex():\n    assert P['x'] == P['y']\n\n"
                         "class Cmp(unittest.TestCase):\n"
                         "    def test_lists(self):\n        self.assertEqual([P['a'], P['b']], [P['b'], P['a']])\n")

            def no_piece(out):
                for name, v in j.items():
                    for seg in v.split("."):
                        for i in range(0, len(seg) - 8 + 1):
                            self.assertFalse(seg[i:i + 8] in out, "a piece of %s reached the report" % name)

            rc, out = self._run(d, "--showlocals", "test_probe_jwt.py")
            self.assertNotEqual(rc, 0)
            self.assertTrue("3 failed" in out, out[-600:])
            no_piece(out)
            self.assertTrue("Full output truncated" in out, "the JWT diff is long enough for pytest's truncation")
            # the JWT test: the print, the assert line (2), two diff lines, two locals; the hex test: the assert
            # line (4: each operand is ellipsized into two fragments), two diff lines; the unittest one: the
            # Lists differ line (2) and two element lines (its diff is over maxDiff and not shown)
            self.assertGreaterEqual(out.count("[REDACTED-CREDENTIAL]"), 17, out[-2500:])
            # the untruncated rendering: the same lines, whole, and the short summary's repeat of each failure's
            # message (the captured print is a section and the locals are the traceback's, so neither is in
            # it): the JWT test's assert line (2) and diff lines (2), the hex test's (4 + 2), the unittest
            # one's (2 + 2)
            rc, out = self._run(d, "--showlocals", "test_probe_jwt.py", env={"CI": "1"})
            self.assertNotEqual(rc, 0)
            self.assertTrue("3 failed" in out, out[-600:])
            no_piece(out)
            self.assertFalse("Full output truncated" in out, "with CI set pytest shows the whole diff")
            self.assertGreaterEqual(out.count("[REDACTED-CREDENTIAL]"), 17 + 14, out[-2500:])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_a_passed_tests_output_under_rA_and_a_collection_error_print_the_marker(self):
        d = tempfile.mkdtemp()
        try:
            _copy_hook(d)
            with open(os.path.join(d, "test_probe_pass.py"), "w") as fh:
                fh.write("import os\n\n"
                         "def test_pass():\n"
                         "    print('a passing test prints ' + os.environ['ROMP_TEST_REDACTION_PROBE'])\n")
            with open(os.path.join(d, "test_probe_broken.py"), "w") as fh:
                fh.write("import os\n"
                         "raise RuntimeError('collection carries ' + os.environ['ROMP_TEST_REDACTION_PROBE'])\n")
            v = probe_value("outcomes")
            rc, out = self._run(d, "-rA", "--continue-on-collection-errors", "test_probe_pass.py", "test_probe_broken.py",
                                env={"ROMP_TEST_REDACTION_PROBE": v})
            self.assertNotEqual(rc, 0, "the collection error fails the run")
            self.assertTrue("1 passed" in out and "1 error" in out, out[-600:])
            self.assertFalse(v in out, "neither the passed test's captured stdout nor the collection error shows the value")
            self.assertGreaterEqual(out.count("[REDACTED-ENV-VALUE]"), 2)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
