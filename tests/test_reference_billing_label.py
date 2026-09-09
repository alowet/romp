#!/usr/bin/env python3
"""docs/reference.md's Billing-row paragraph quotes what ui/webview/render.ts renders.

The tab hover's `Billing` row and the tab menu's Billing sub-line each have four readings: the plain side,
a pick still applying, a pick this machine cannot bill, and a pick the CLI's own report contradicts. The
reference describes them by quoting the rendered text, and nothing else ties the two files together, so
these pins hold the doc to the code: the copy render.ts builds each reading from is asserted there, and
the doc is asserted to quote the readings assembled from that same copy. A wording change in render.ts
reddens here before the reference goes stale, and a retired reading cannot linger in the doc.

The render.ts pins are the rendered text, not the expressions around it: a rename, a reshuffle or an
extraction into a helper that leaves every rendered word as it was stays green here, since the doc is
not stale then. Where a fragment is a common word (`unavailable`) or the warning glyph, the template
quote beside it is included, so the pin names the row's own copy and not a comment or another control's.

Text only: labels, never key material.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _flat(text):
    """Collapse hard wraps so a quote that spans a line break in the doc still compares."""
    return re.sub(r"\s+", " ", text)


REFERENCE = _flat(_read("docs", "reference.md"))
RENDER = _read("ui", "webview", "render.ts")
CREDENTIALS = _read("kernel", "credentials.py")

# The hover row's readings, as render.ts assembles them: the side word first, then these fragments
# around an interpolated reason or side.
WARN = "⚠ "
PENDING = " (applying — not confirmed yet)"
UNAVAILABLE_HEAD = " picked, but "
FELL_TAIL = " — this session bills "
NO_FALL_TAIL = " — nothing to fall to, so the launch went out as picked"
CONTRADICTED_HEAD = " picked, but the CLI reports "
CONTRADICTED_TAIL = " — this session bills that"
# The side words the row starts each reading with, and the ones it names a fall or a report with.
HOVER_SIDES = ('"API key"', '"Login"', '"the API key"', '"the login"')
ACCOUNT_FORM = "Login (${"   # the login side with its account name: `Login (name@example.com)` in the doc
# The tab menu's shorter mirror of each reading.
MENU_PENDING = '"applying…"'
MENU_UNAVAILABLE = " unavailable"
MENU_FELL = ", billing "
MENU_CONTRADICTED = "⚠ CLI reports "
MENU_SIDES = ('"API key"', '"login"')
# The kernel's reason for a login pick on a machine with no login, which the hover row interpolates.
WHY_NO_LOGIN = "no Claude login signed in on this machine"


class _Pins(unittest.TestCase):
    def assertQuoted(self, needle, haystack, where, msg=""):
        # a bare assertIn would print the whole file on a miss; name the missing text and the file instead
        self.assertTrue(needle in haystack, "%s does not carry %r%s" % (where, needle, (": " + msg) if msg else ""))

    def assertNotQuoted(self, needle, haystack, where, msg=""):
        self.assertFalse(needle in haystack, "%s still carries %r%s" % (where, needle, (": " + msg) if msg else ""))


class RenderTsRendersThePinnedCopy(_Pins):
    SRC = "ui/webview/render.ts"

    def test_the_hover_row(self):
        self.assertQuoted('"%s"' % PENDING, RENDER, self.SRC)
        self.assertQuoted("`" + WARN, RENDER, self.SRC, "the warning glyph opens the warning readings")
        self.assertQuoted(UNAVAILABLE_HEAD, RENDER, self.SRC)
        self.assertQuoted(FELL_TAIL, RENDER, self.SRC)
        self.assertQuoted('"%s"' % NO_FALL_TAIL, RENDER, self.SRC)
        self.assertQuoted(CONTRADICTED_HEAD, RENDER, self.SRC)
        self.assertQuoted(CONTRADICTED_TAIL, RENDER, self.SRC)
        for side in HOVER_SIDES:
            self.assertQuoted(side, RENDER, self.SRC, "the key is 'API key', never any key material")
        self.assertQuoted(ACCOUNT_FORM, RENDER, self.SRC)

    def test_the_tab_menu_sub_line(self):
        self.assertQuoted(MENU_PENDING, RENDER, self.SRC)
        self.assertQuoted(MENU_UNAVAILABLE + "`", RENDER, self.SRC, "the word ends the sub-line's template piece")
        self.assertQuoted(MENU_FELL, RENDER, self.SRC)
        self.assertQuoted(MENU_CONTRADICTED, RENDER, self.SRC)
        for side in MENU_SIDES:
            self.assertQuoted(side, RENDER, self.SRC)

    def test_the_kernel_reason_the_unavailable_reading_interpolates(self):
        self.assertQuoted('WHY_NO_LOGIN = "%s"' % WHY_NO_LOGIN, CREDENTIALS, "kernel/credentials.py")


class TheReferenceQuotesEachReading(_Pins):
    DOC = "docs/reference.md"

    def test_the_plain_readings(self):
        self.assertQuoted("`API key` or `Login (name@example.com)`", REFERENCE, self.DOC)

    def test_the_applying_reading(self):
        self.assertQuoted("`Login%s`" % PENDING, REFERENCE, self.DOC)
        self.assertQuoted("`applying…`", REFERENCE, self.DOC, "the tab menu's sub-line while the switch applies")

    def test_the_unavailable_pick_reading(self):
        self.assertQuoted("`%sLogin%s%s%sthe API key`" % (WARN, UNAVAILABLE_HEAD, WHY_NO_LOGIN, FELL_TAIL),
                          REFERENCE, self.DOC)
        self.assertQuoted("`%slogin%s%sAPI key`" % (WARN, MENU_UNAVAILABLE, MENU_FELL), REFERENCE, self.DOC,
                          "the tab menu's sub-line")

    def test_the_contradicted_pick_reading(self):
        self.assertQuoted("`%sLogin%sthe API key%s`" % (WARN, CONTRADICTED_HEAD, CONTRADICTED_TAIL), REFERENCE, self.DOC)
        self.assertQuoted("`%sAPI key`" % MENU_CONTRADICTED, REFERENCE, self.DOC, "the tab menu's sub-line")

    def test_no_retired_reading_lingers(self):
        # the CLI's report is not a parenthetical after the side: the row leads with the warning
        # (render.ts's contradicted reading)
        self.assertNotQuoted("(CLI reports", REFERENCE, self.DOC)


if __name__ == "__main__":
    unittest.main()
