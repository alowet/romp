"""Credential-shaped tokens, by pattern: the second net of tests/conftest.py's report redaction.

tests/conftest.py's report redaction removes every value seen in the process environment. That net
cannot see a token that never touched the environment (read from a file, printed by a child process,
typed into a fixture). This is the second net, independent of provenance: the key formats an
installation may meet, each as the prefix its provider fixed plus a long tail, one format fixed by
its shape rather than a prefix (a JWT), and one generic rule for a token of unknown format.

The generic rule fires on a token of 24 characters or more that has a digit (a hex, base64 or random
token of that length has one with near certainty, while a long identifier does not, so
`testMethod=test_a_long_descriptive_name` in a failure header stays readable), and on one of 40 or
more that mixes upper and lower case with no digit. It applies where a value sits (after `=`, after
`:` or `: `, after `Bearer `, inside the quotes of a dict repr, as an element of a list, tuple or set
repr: after `[`, `(`, `{` or `, `), to a line that is one such token and nothing else, which is what
an apiKeyHelper's stdout is, and to pytest's own renderings of a failed comparison, which are value
positions too though nothing marks them as one: the `- <token>` and `+ <token>` lines of its diff
under the `E` marker (a container's elements spread over such lines included), the quoted operands
of `assert '<a>' == '<b>'` (and unittest's `'<a>' != '<b>'`), the haystack of `assert '<a>' in '<b>'`
(unittest's `'<a>' not found in '<b>'`), the `+  where '<a>' = f()` and `+  and   '<b>' = g()` lines
that explain an assert's operands, unittest's `Lists differ:` line and the quoted element lines under
it, and a `--showlocals` line `name = '<token>'`. A match takes the dotted rest of its token with it
(`.` and more token characters, any number of times), so a dotted token whose first run qualifies is
taken whole (`<32 hex>.<signature>`, a JWT whose header is longer than the JWT rule's bound) rather
than up to its first dot; a dot with nothing of a token after it (a sentence's, an ellipsis) is never
taken. Two shapes it leaves alone: the segment after a pytest node id's `::` (a test's name, not a
value), and a 40-hex git sha named as a commit (`commit: <sha>`, `{'commit': '<sha>'}`) or sitting
in a path or after an `@`. It still matches a synthetic uuid in a value position and a test method
name with a digit in it, so a failing dict comparison may show the marker where a test's placeholder
sid was, and a digit-bearing file name in a value position loses its extension to the dotted rest
(`file=<name>.py`, a uuid-named file alone on a line). That is the cost of catching a token of
unknown format; the failure is still readable.

A JWT (RFC 7519) has no provider prefix but a fixed shape: base64url segments joined by dots, the
first the JOSE header, a JSON object, whose encoding therefore begins `eyJ` (`{"` in base64). The
rule takes `eyJ`, the rest of a header segment of 10 to JWT_HEADER_MAX characters (the shortest
header, `{"alg":"none"}`, encodes to 19), and one to four more segments: a signed token has three,
an unsecured one two, an encrypted one (JWE) five. Wherever it sits: the value positions, a bare
line, pytest's diff line, and after a scheme the value positions do not know (`Authorization: vapid
t=<jwt>, k=<key>` and `WebPush <jwt>`, the header the kernel's push code mints). The header bound
is what keeps the rule linear (below); a header beyond it is longer than any JOSE header an
installation meets, and a token carrying one is still taken whole in a value position, on a bare
line and on a diff line by the generic rule and its dotted rest.

A value pytest has already cut is a piece of a value. At its default verbosity pytest ellipsizes the
operands of a failed `==`: the repr keeps its head and its tail, 11 to 13 characters each, joined by
`...` (`'sk-ant-api03...2c3d4a1b2c3d4'`, `['0123456789a...456789abcdef']`); its saferepr of a local
under `--showlocals`, of a traceback's arguments and of the operands on a `+  where` line keeps 118
characters of the repr on each side of the `...` (117 of a quoted string, at its default maximum of
240); the short test summary cuts a message at the terminal's width with `...` appended; and a long
explanation (over 8 lines or 640 characters) is truncated with `...` appended to its last line, so a
diff line can end mid-token in `...`, its marker and sign before a piece of the value. unittest
shortens a long container repr with `[N chars]` in place of the middle and keeps up to 41 characters
beside it after a common prefix it leaves whole when that is 22 or fewer, so 63 at most. A known
prefix against either ellipsis is a truncated key, whatever follows, when 1 to CUT_HEAD_MAX (120)
token characters sit between the prefix and the cut: every cut a tool makes at default verbosity
leaves a head within that bound. A wider head (pytest's saferepr at `-v` keeps 1198) is a run the
format rule takes on its own (20 characters or more, 30 for `AIza`), and every format rule takes a cut
against its run and the run after the cut in the same match, so a cut key is one marker whatever the
width of its head and wherever it sits, quoted or bare (a line a test or a child process prints itself
ends the tail with a newline or a space, not the quote the fragment rule below needs; until the format
rules took the tail, such a line showed it). The bound is there so a prefix inside a long run that
never reaches a cut costs a bounded scan (an unbounded head made the scrub quadratic: 80 seconds on
a 200 KB line of repeated `hf_`, which is what the tests/test_env_value_redaction.py timing case
guards). What a format rule cannot take whole is a body of characters its key does not have. A
Hugging Face token is `hf_` and 34 letters (gitleaks' rule is `hf_(?i:[a-z]{34})`, and every token that
rule is tested against is letters only); the `hf_` rule here takes letters and digits, wider than that
on purpose: narrowing it to letters would exclude nothing more (what ends a match in an identifier is
the `_` it carries, not a digit), and a token that did carry a digit would show. RunPod publishes the
`rpa_` prefix and nothing of the body (checked 2026-09-06; gitleaks has no rule for it), and the
`rpa_` rule is the same class. A body with `_` or `-` in it, whole or cut, is therefore taken up to
that character under either prefix. Past the bound the rest of such a head shows in bare text, and in
a quoted repr too once 20 letters and digits precede the `_` or `-` (with fewer the format rule
fails, the whole head is a fragment between the quote and the cut, and the fragment rule takes it);
within the bound the cut rule's head class takes it. That shape is no Hugging Face token; a real
RunPod key carrying `_` or `-` would be the reason to widen the `rpa_` class, and the whole key in
bare text, not the cut one, is what widening would fix first. The class stays narrow so an
`hf_`-prefixed identifier of 20 characters or more (`hf_hub_download_to_cache_dir`) is not redacted.
A cut JWT is the same with dotted segments in its head and tail
(`'eyJ<header>.eyJ<payload>...<payload>.<signature>'`, and unittest's `['eyJ[35 chars]<rest>']`,
whose head is the prefix alone). Its header is bounded at JWT_HEADER_MAX, as the whole token's is,
wherever the cut falls: a cut inside a header of up to that many characters past `eyJ` is the cut
rule's match, and a cut past the header (a payload cut deep, after a header of any width within the
bound) is the JWT rule's, which takes the cut and its dotted tail the same way. What neither takes is
a cut token with more than JWT_HEADER_MAX characters between `eyJ` and the first dot or the cut,
whichever comes first — a header past the bound with the cut anywhere after its first JWT_HEADER_MAX
characters (a cut inside such a header within them is the cut rule's match: the bound is on the head,
not the header): in a quoted repr the fragment rule takes its head and its tail as two matches, in a
value position the generic rule takes the head and the tail shows, and in bare text the header shows
— whole, with the cut and the tail, when the cut is inside it; up to its dot when the cut is in the
payload, where the payload's own `eyJ` (a JSON payload begins with one too) is the cut rule's match
with the cut and the tail. No enumerated tool leaves a head of that width (pytest's widest default
cut leaves 118 characters; its `-v` cut of 1198 lands past any real header), so such a line is a
hand-made one. A run of 8 or more token characters against an ellipsis, with a
quote or another ellipsis on its far side, or with a diff line's marker and sign before it and the
ellipsis ending the line, is a fragment of an unknown-format value when it has a digit, or when it
has a lower-case letter and an upper-case one anywhere after its first character (a base64 tail can
lack a digit); its dotted rest rides along. So a Capitalised word (`'Connecting...'`) and a
single-case identifier (`'test_a_long_...'`, `'deadbeef...'`, `'ABCDEFGHIJKL...'`) stay, and a
camelCase or PascalCase name (`'SessionStart...'`, `'HookEndToEnd...'`), a cut ISO date or timestamp
(`'2026-09-06...'`, the head of `'2026-09-06T1...6+00:00'`) and an identifier with a digit
(`'python38...'`) are redacted. That is a readability cost in a cut repr, taken on purpose: a
PascalCase name's letters are a shape a base64 tail without a digit takes for one 8-character
fragment in 25 (one in 200 at 13), and a digit-bearing run is the shape of a hex tail, so an
exclusion for either would pass fragments of a key.

Nothing here is a credential: the file holds prefixes and character classes only.
"""
import re

REDACTED = "[REDACTED-CREDENTIAL]"

# Where a value sits. Each alternative is one fixed-width lookbehind (the form Python's re accepts). A
# colon counts only when it is not the second of a `::` pair: that pair separates a pytest node id's
# segments, and what follows it is a test's name. The second and third rows are pytest's own rendering
# of a failed comparison, where the token is a compared value and nothing else marks it: the quoted
# operands of `assert '<a>' == '<b>'` (unittest's `'<a>' != '<b>'`), a --showlocals line `name = '<a>'`,
# the `+  where '<a>' = f()` and `+  and   '<b>' = g()` lines that explain the operands, and the
# haystack of `assert '<a>' in '<b>'` (unittest's `'<a>' not found in '<b>'`). The fourth row is an
# element of a list, tuple or set repr (`['<a>', '<b>']`, `('<a>',)`, `{'<a>'}`): the first after the
# opening bracket, the rest after `, `. unittest's `Lists differ:` line is one such repr per side.
_VALUE_POSITION = (r"(?:(?<=Bearer )|(?<==)|(?<==\")|(?<==')|(?<=: )|(?<=: \")|(?<=: ')|(?<=[^:]:)"
                   r"|(?<== \")|(?<== ')|(?<=== \")|(?<=== ')|(?<=!= \")|(?<=!= ')|(?<=assert \")|(?<=assert ')"
                   r"|(?<=where \")|(?<=where ')|(?<=and   \")|(?<=and   ')|(?<=in \")|(?<=in ')"
                   r"|(?<=[\[({]\")|(?<=[\[({]')|(?<=, \")|(?<=, '))")
_TOKEN_CHARS = r"[A-Za-z0-9_\-]"
# The dotted rest of a token: `.` and one or more token characters, any number of times. Appended to a
# rule, it takes `<payload>.<signature>` along with the run that qualified, and never a dot that no token
# character follows (an ellipsis, a sentence's end), so `...` is left for the cut rules.
_DOTTED = r"(?:\." + _TOKEN_CHARS + r"+)*"
# A token of unknown format: 24 or more characters with a digit, or 40 or more mixing upper and lower case,
# and the dotted rest of it
_GENERIC = (r"(?:(?=" + _TOKEN_CHARS + r"*\d)" + _TOKEN_CHARS + r"{24,}"
            r"|(?=" + _TOKEN_CHARS + r"*[a-z])(?=" + _TOKEN_CHARS + r"*[A-Z])" + _TOKEN_CHARS + r"{40,})" + _DOTTED)

# A bounded run of token characters that, once matched, is never shortened: the lookahead matches the
# run greedily into a named group and the backreference consumes it. A lookahead is atomic in Python's
# re, so when what follows the run fails the engine gives up on the alternative instead of retrying
# every shorter run, which halves the work of a rule tried at each occurrence of its prefix (5 to 10
# times faster on the adversarial lines the redaction tests time; CI's Python floor has no possessive
# quantifier). Token characters and what follows a head (`.`, `...`, `[N chars]`) are disjoint, so no
# shorter run could have matched anyway. Each use needs its own group name; scrub() reads none of them.
def _atomic_run(name, bounds):
    return r"(?=(?P<%s>%s%s))(?P=%s)" % (name, _TOKEN_CHARS, bounds, name)


# A JWT, by its shape: `eyJ` (a base64url JSON object's first three characters), the rest of the header
# segment, and one to four more dot-joined segments (JWS: three in all; unsecured: two; JWE: five). The
# header segment is bounded on both sides: 10 or more so `eyJab.cd` is not a token, JWT_HEADER_MAX at
# most so that an `eyJ` inside a long run with no dot after it costs a scan of at most that many
# characters. Without the bound the scrub is quadratic on such a run, for the reason CUT_HEAD_MAX
# explains. 256 is past every JOSE header an installation meets (a header carrying a kid, x5t and jku
# encodes to about 220); a longer one falls to the generic rule and its dotted rest.
JWT_HEADER_MAX = 256
_JWT = r"eyJ" + _atomic_run("jh", r"{10,%d}" % JWT_HEADER_MAX) + r"(?:\." + _TOKEN_CHARS + r"+){1,4}"

# pytest's diff of two compared values, one line per side: `E         - <a>` and `E         + <a>`, the
# token alone after the marker and the sign, or one element of a container repr that unittest's diff
# spreads over lines, quoted and closed by the repr's own punctuation (`E       -  '<a>']`,
# `E       +  '<a>',`). The prefix is captured (pfx) and kept, so the diff still reads as one; without
# the marker a `- <token>` line is a bullet in someone's captured output. unittest's `First differing
# element` lines render each element alone and quoted after the marker: `E       '<a>'`.
_DIFF_LINE = r"^(?P<pfx>E[ \t]+[-+][ \t]+['\"]?)" + _GENERIC + r"(?=['\"]?[\]),]*$)"
_QUOTED_LINE = r"^(?P<pfxq>E[ \t]+['\"])" + _GENERIC + r"(?=['\"]$)"

# A value pytest or unittest has already cut (the module docstring measures the widths). The two forms
# of the cut; a known prefix against one, whatever follows; a JWT against one, its head and tail dotted;
# and a fragment of an unknown-format value: a run of 8 or more token characters against an ellipsis, a
# quote or another ellipsis on its far side, with a digit, or with a lower-case letter and an upper-case
# one after its first, and the dotted rest of it.
#
# CUT_HEAD_MAX bounds the head between a prefix and the cut. The widest head a tool leaves is pytest's
# saferepr at its default 240: 118 characters of the repr, 117 of a quoted string; unittest's `[N chars]`
# leaves at most 63, pytest's `==` operands 13. The bound is what makes the scrub linear: a prefix rule
# is tried at every occurrence of its prefix, and inside a long run that never reaches a cut an unbounded
# head consumed the rest of the run and backtracked through it, once per occurrence. For `sk-ant-`,
# `sk-or-`, `sk-proj-` and `AIza` the format rule then took the run in one match, so the cost was paid
# once; for `hf_` and `rpa_` the format rule (`[A-Za-z0-9]{20,}`) fails on a run holding `_` or `-`, the
# run was never consumed, and every occurrence paid again: 80 seconds for a 200 KB line of repeated `hf_`.
# A head past the bound is the format rule's match, and _CUT_TAIL (below) gives that match the cut and the
# run after it, so a cut key of any head width is one match.
_ELLIPSIS = r"(?:\.\.\.|\[\d+ chars\])"
CUT_HEAD_MAX = 120
_CUT_HEAD_BOUNDS = r"{1,%d}" % CUT_HEAD_MAX
# A cut and the run after it, appended to each format rule and to the JWT rule: optional, so a whole key
# matches as before, and taken when the run a format rule matched ends at `...` or `[N chars]`
# (`sk-ant-<130>...<118>`, `hf_<130>[88 chars]<5>`). Without it a cut key whose head is past CUT_HEAD_MAX was
# two matches, the head by the format rule and the tail by _ELLIPSIZED, which needs a quote or another cut
# on the tail's far side: in a quoted repr the tail was redacted, but on a line a test or a child process
# printed itself (end of line, a space, a sentence's dot after the tail) it showed (2026-09-06). The run
# before it is greedy and its characters are disjoint from a cut's first, so the optional group is tried
# once where the run ends and never sends the engine back through the run: the scrub stays linear. A
# sentence's `...` right after a whole key is consumed with it, as _PREFIX_ELLIPSIZED already did for a
# head within the bound. The JWT's tail is dotted (`...<payload>.<signature>`), so its form takes the
# dotted rest too; a whole JWT's segment count (one to four after the header) is unchanged, because the
# dotted rest is inside the optional cut group.
_CUT_TAIL = r"(?:" + _ELLIPSIS + _TOKEN_CHARS + r"*)?"
_CUT_TAIL_DOTTED = r"(?:" + _ELLIPSIS + _TOKEN_CHARS + r"*" + _DOTTED + r")?"
_PREFIX_ELLIPSIZED = (r"(?:sk-ant-|sk-or-|sk-proj-|hf_|AIza|rpa_)" + _atomic_run("hk", _CUT_HEAD_BOUNDS)
                      + _ELLIPSIS + _TOKEN_CHARS + r"*")
# A JWT's head is `eyJ` and up to three dotted segments: the header, bounded at JWT_HEADER_MAX like the
# whole-token rule's, so a cut inside any header an installation meets is taken (atomic: it is the one
# scanned at every `eyJ` in a run; bounded at CUT_HEAD_MAX until 2026-09-06, which left a cut 121 or more
# characters into a longer header to no rule in bare text), then up to two more within CUT_HEAD_MAX (they
# run only after a dot, and a cut deeper in a later segment is _JWT's match with its cut tail); its tail
# is whatever dotted run follows the cut. Either may be empty (`['eyJ[35 chars]J9.eyJzdWIi']` has the
# prefix alone before the cut), but not both: `'eyJ...'` shows nothing beyond the prefix and stays, as
# `'hf_...'` does.
_JWT_ELLIPSIZED = (r"eyJ(?:" + _atomic_run("hj", r"{1,%d}" % JWT_HEADER_MAX) + r"(?:\." + _TOKEN_CHARS + _CUT_HEAD_BOUNDS + r"){0,2}"
                   + _ELLIPSIS + _TOKEN_CHARS + r"*" + _DOTTED
                   + r"|" + _ELLIPSIS + _TOKEN_CHARS + r"+" + _DOTTED + r")")
_FRAGMENT = (r"(?:(?=" + _TOKEN_CHARS + r"*\d)" + _TOKEN_CHARS + r"{8,}"
             r"|(?=" + _TOKEN_CHARS + r"*[a-z])(?=" + _TOKEN_CHARS + r"+[A-Z])" + _TOKEN_CHARS + r"{8,})" + _DOTTED)
_ELLIPSIZED = (r"(?:(?<=['\"])" + _FRAGMENT + r"(?=" + _ELLIPSIS + r")"
               r"|(?:(?<=\.\.\.)|(?<=chars\]))" + _FRAGMENT + r"(?=" + _ELLIPSIS + r"|['\"]))")
# The last line of an explanation pytest truncated (over 8 lines or 640 characters: `...` is appended to
# it, then `use '-vv' to show`). A diff line so cut ends in `...` instead of the token's end, which
# _DIFF_LINE requires, and nothing before the token marks a fragment position, so what is left of the
# value showed in the clear (a piece of a compared JWT, 2026-09-06). The marker and sign are kept (pfxc).
_DIFF_LINE_CUT = r"^(?P<pfxc>E[ \t]+[-+][ \t]+)" + _FRAGMENT + r"(?=\.\.\.$)"

TOKEN_RE = re.compile(
    _PREFIX_ELLIPSIZED +                            # a key of a known format that pytest or unittest cut
    r"|" + _JWT_ELLIPSIZED +                        # a JWT so cut
    r"|sk-ant-[A-Za-z0-9_\-]{20,}" + _CUT_TAIL +    # Anthropic API keys, each format whole or with a cut and its tail
    r"|sk-or-[A-Za-z0-9_\-]{20,}" + _CUT_TAIL +     # OpenRouter
    r"|sk-proj-[A-Za-z0-9_\-]{20,}" + _CUT_TAIL +   # OpenAI project keys
    r"|hf_[A-Za-z0-9]{20,}" + _CUT_TAIL +           # Hugging Face (a token is 34 letters; the class is wider, the docstring says why)
    r"|AIza[A-Za-z0-9_\-]{30,}" + _CUT_TAIL +       # Google API keys
    r"|rpa_[A-Za-z0-9]{20,}" + _CUT_TAIL +          # RunPod (the prefix is published, the body is not; the same class)
    r"|" + _JWT + _CUT_TAIL_DOTTED +                # a JWT (JWS, unsecured or JWE), by its shape, whole or cut with its dotted tail
    r"|" + _VALUE_POSITION + _GENERIC +             # a token of unknown format where a value sits...
    r"|^" + _GENERIC + r"$"                         # ...or alone on its line (an apiKeyHelper's stdout)...
    r"|" + _DIFF_LINE +                             # ...or one side of pytest's diff of two compared values...
    r"|" + _QUOTED_LINE +                           # ...or unittest's quoted rendering of one differing element...
    r"|" + _DIFF_LINE_CUT +                         # ...or a diff line pytest's truncation cut mid-token...
    r"|" + _ELLIPSIZED,                             # ...or a fragment of a value pytest or unittest cut
    re.MULTILINE,
)

# A git sha (40 lowercase hex) is no credential when the text says what it is: named as a commit
# (`commit=<sha>`, `commit: <sha>`, `{'commit': '<sha>'}`), or sitting in a path or after an `@`. Under
# today's value positions only the commit form can precede a match (a token after `/` or `@` is in no
# value position); the other two guard the rule should a position be added.
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")
_GIT_SHA_CONTEXT = re.compile(r"(?:commit\W{0,4}|/|@)$", re.IGNORECASE)


def _is_git_sha_in_context(text, m):
    tok = m.group(0)
    return bool(_GIT_SHA_RE.fullmatch(tok)) and bool(_GIT_SHA_CONTEXT.search(text[max(0, m.start() - 12):m.start()]))


def scrub(text):
    """`text` with every match replaced by REDACTED (a diff line keeps its marker and sign, a quoted
    element line its marker and quotes); anything that is not a str comes back as is."""
    if not isinstance(text, str):
        return text

    def one(m):
        if _is_git_sha_in_context(text, m):
            return m.group(0)
        return (m.group("pfx") or m.group("pfxq") or m.group("pfxc") or "") + REDACTED
    return TOKEN_RE.sub(one, text)
