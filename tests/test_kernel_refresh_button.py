"""The ↻ kernel-restart button is decoupled from Debug mode (the user 2026-06-24).

It used to be hidden unless Debug mode was on (an `applyDebug()` helper in the gear JS toggled its
`style.display` off `s.debug`). The user wanted it ALWAYS visible, so that gating is gone — Debug now
only governs the timeline's judging band. Source-level pin against the kernel's embedded gear chrome.
"""
import os
import unittest
from romp_load import load_source
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
# Hermetic state BEFORE the loads — they resolve their state root at import time, and only
# pytest runs conftest's floor (a bare unittest or script run otherwise writes REAL state).
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
km = load_source("romp_kernel", os.path.join(BIN, "romp-kernel"))


class RefreshButtonDecoupledTest(unittest.TestCase):
    def test_refresh_button_is_always_present(self):
        # the ↻ moved to the shell's far-left rail (the user 2026-06-25) so it persists regardless of which
        # panes are open — always present, still POSTs /restart then polls /healthz and reloads.
        html = km._landing()
        self.assertIn("id=rail-refresh", html)
        self.assertIn("fetch('/restart',{method:'POST'})", html)
        self.assertNotIn("id=rrefresh", _gear_src())   # gone from the feed gear
        # …and it draws a REAL browser-style reload icon (the user 2026-07-27: the ↻ TEXT glyph stopped
        # its arc short at 11 o'clock and never read as refresh, and its size rode the fallback font).
        # One shared svg — a near-full clockwise arc with the arrowhead at 1 o'clock — used by the rail
        # AND the mobile bar, sized 18px like its icon neighbors.
        self.assertIn("aria-label=Refresh>" + km._REFRESH_SVG, html)
        self.assertIn("A 5.2 5.2 0 1 1", km._REFRESH_SVG)   # the 270-degree arc (large-arc, clockwise)
        self.assertNotIn(">↻<", html)                        # the text glyph is gone from every surface

    def test_refresh_button_is_not_gated_on_debug(self):
        # the old applyDebug() helper (which hid #rrefresh unless s.debug) is gone entirely …
        self.assertNotIn("applyDebug", _gear_src())
        # … and nothing else hides the refresh button by toggling its display off the debug flag
        self.assertNotRegex(_gear_src(), r"rf\.style\.display\s*=")
        self.assertNotRegex(_gear_src(), r"rrefresh[^\n]*display:none")

    def test_judge_toggles_do_not_touch_the_refresh_button(self):
        # the judge-set toggles (which replaced the single Debug toggle) save the pref + emit, but never
        # re-run any refresh-button visibility logic — the ↻ is always visible
        self.assertIn("s.showIndexJudges = jix.checked", _gear_src())
        self.assertIn("s.showTriageJudges = jtr.checked", _gear_src())
        self.assertNotRegex(_gear_src(), r"checked;[^\n]*applyDebug")


class RestartReloadRaceTest(unittest.TestCase):
    """The restart flow acts on the NEW kernel's answer, never a bare 200 (the user 2026-07-27), and since
    2026-09-16 it reloads nothing by itself.

    The old poll reloaded on the first /healthz 200 — but the OLD kernel keeps answering for a beat
    after the /restart ack (the manager SIGTERMs it asynchronously), so the reload routinely landed on
    a dying server and the browser sat on its connection-error page until a manual refresh. Now the
    page embeds the boot id it was served under, /healthz stamps every answer with X-Romp-Boot, and
    the poll acts only when the id FLIPS — an exact process-identity event, not a timing guess.
    While it waits, the romp boot splash is rebuilt over the page (the loading rule), with a reload
    backstop so the splash can never trap the user. What the flip DOES is the reload core's call (the
    user 2026-09-16, the design block above kernel.py _RELOAD_CORE_JS): the splash drops and the new
    kernel's /version is read; an unchanged build reloads nothing (the panes redial, the board updates
    in place), a changed build is OFFERED as one line with Reload and Not now, never taken. The ↻ is a
    request for a restart, not for a reload. tests/test_dashboard_auto_reload.py runs the button's
    function with the core over both answers; these pins hold its source."""

    def test_reload_waits_for_the_boot_id_to_flip(self):
        import json
        html = km._landing()
        # the page knows its own kernel's boot id, and the poll compares against it
        self.assertIn("b!==" + json.dumps(km._BOOT_ID), html)
        self.assertIn("r.headers.get('X-Romp-Boot')", html)
        # both splice placeholders were resolved
        self.assertNotIn("__ROMP_BOOT__", html)
        self.assertNotIn("__ROMP_LOADER__", html)
        # the racy first-200 reload is gone
        self.assertNotIn("if(r&&r.ok)location.reload()", html)

    def test_the_flip_hands_the_decision_to_the_reload_core_and_never_reloads_by_itself(self):
        import json
        html = km._landing()
        a = html.index("window.__rompRestart=function(){")
        fn = html[a:html.index("var rf=document.getElementById('rail-refresh');", a)]
        self.assertIn("if(b&&b!==%s){boot.classList.add('gone');if(window.__rompReload)window.__rompReload.checkBoot();else location.reload();}" % json.dumps(km._BOOT_ID), fn,
                      "the flip drops the splash and asks the core to read /version; only a page without the core reloads as before")
        self.assertNotIn("if(b&&b!==%s)location.reload()" % json.dumps(km._BOOT_ID), fn, "the flip's own reload is gone (2026-09-14)")
        self.assertEqual(fn.count("location.reload()"), 3, "the no-core fallback and the two-minute backstop's two arms: nothing else reloads here")
        # the ruling's words stand beside the code
        self.assertIn("A changed build: the core OFFERS the reload", fn)
        # and the gear's own ↻ handler, dead since the control moved to the rail, is gone with its first-200 reload
        self.assertNotIn("rrefresh", _gear_src())

    def test_wait_wears_the_boot_splash(self):
        import json
        html = km._landing()
        # the splash element is rebuilt (the boot JS removed it from the DOM after startup) from the
        # SAME server-rendered loader markup the boot splash uses — one source, no drifting copy
        self.assertIn("boot.id='romp-boot'", html)
        self.assertIn("boot.innerHTML=" + json.dumps(km._loader_inner()), html)

    def test_healthz_and_restart_carry_the_boot_id(self):
        # source-level pins (the HTTP-level check lives in test_kernel.py's ServeSecurity): /healthz
        # stamps X-Romp-Boot, and the /restart ack reports which kernel acked
        import inspect
        src = inspect.getsource(km.Handler)
        self.assertIn('"X-Romp-Boot": _BOOT_ID', src)
        self.assertIn('"restarting": True, "boot": _BOOT_ID', src)


if __name__ == "__main__":
    unittest.main()


# The gear moved from kernel-inline strings into the shared feed bundle
# (2026-07-13): ui/webview/gear.js is the single source both hosts render, so
# the gear pins read THAT file (and feed.css for its styling).
def _gear_src():
    import pathlib
    return (pathlib.Path(__file__).resolve().parent.parent / "ui" / "webview" / "gear.js").read_text()


def _gear_css_src():
    import pathlib
    return (pathlib.Path(__file__).resolve().parent.parent / "ui" / "webview" / "gear.css").read_text()
