#!/usr/bin/env python3
"""The notification bells (the user 2026-07-28; on by default + phone push 2026-08-09). A card ENTERING
needs_input (blocked on you) or completed notifies EVERY session by default; the session bell is a mute
(session-flags "notifyOff") and the per-card bell (notify-cards.json) speaks over that mute. Every
notification goes to the OS notifier AND to a configured ntfy topic, which is what reaches a phone.
Detection diffs each fresh feed build against the previous one — the exact event the columns move on —
and the first build after a kernel start is a silent baseline (existing state is status, not news).
Synthetic ids/names only."""
import io
import json
import os
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin")
SourceFileLoader("romp_event_model", os.path.join(BIN, "romp-event-model")).load_module()
SourceFileLoader("romp_judge", os.path.join(BIN, "romp-judge")).load_module()
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
km = SourceFileLoader("romp_kernel_nb", os.path.join(BIN, "romp-kernel")).load_module()
jd = km.jd


def _card(iid, sid, col, text="Fix the login flow", **kw):
    d = {"itemId": iid, "sid": sid, "name": "web", "column": col, "text": text}
    d.update(kw)
    return d


def _feed(*cards):
    return {"type": "feed", "asks": [dict(c) for c in cards]}


class NotifyCardStore(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.saved = jd.STATE
        jd.STATE = Path(self.td.name)
        km._notify_cards_cache.clear()

    def tearDown(self):
        jd.STATE = self.saved
        self.td.cleanup()

    def test_default_is_empty(self):
        self.assertEqual(km._notify_cards(), {})

    def test_set_get_then_unset_drops_the_entry(self):
        km._set_notify_card("TESTSID:g1", True)
        self.assertEqual(km._notify_cards(), {"TESTSID:g1": True})
        km._set_notify_card("TESTSID:g1", False)
        self.assertEqual(km._notify_cards(), {}, "disarming removes the key, not stores False")

    def test_cache_invalidates_on_write(self):
        self.assertEqual(km._notify_cards(), {})            # primes the (empty) read path
        km._set_notify_card("TESTSID:g1", True)
        self.assertTrue(km._notify_cards().get("TESTSID:g1"), "the (mtime_ns,size) cache key sees the write")

    def test_prune_drops_only_ids_that_left_the_feed(self):
        km._set_notify_card("TESTSID:g1", True)
        km._set_notify_card("TESTSID:g2", True)
        km._prune_notify_cards({"TESTSID:g2"})
        self.assertEqual(km._notify_cards(), {"TESTSID:g2": True})
        # nothing gone → no write (the file's mtime is the feed-cache sig; a no-op must not churn it)
        p = jd.STATE / "notify-cards.json"
        before = p.stat().st_mtime_ns
        km._prune_notify_cards({"TESTSID:g2"})
        self.assertEqual(p.stat().st_mtime_ns, before)


class SessionBellDefault(unittest.TestCase):
    """The bell is ON by default and what persists is the MUTE (the user 2026-08-09)."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.saved = jd.STATE
        jd.STATE = Path(self.td.name)
        km._flags_cache.clear()
        km._notify_cards_cache.clear()

    def tearDown(self):
        jd.STATE = self.saved
        self.td.cleanup()

    def test_a_session_nobody_ever_touched_is_on(self):
        self.assertTrue(km._notify_on("TESTSID"), "no arming step — an unheard block is the failure mode")

    def test_the_off_flag_mutes_and_clearing_it_restores(self):
        km._set_session_flag("TESTSID", "notifyOff", True)
        self.assertFalse(km._notify_on("TESTSID"))
        km._set_session_flag("TESTSID", "notifyOff", False)
        self.assertTrue(km._notify_on("TESTSID"))

    def test_muting_one_session_leaves_its_peers_alone(self):
        km._set_session_flag("TESTSID", "notifyOff", True)
        self.assertTrue(km._notify_on("TESTSID2"))

    def test_an_armed_card_speaks_over_its_sessions_mute(self):
        km._set_session_flag("TESTSID", "notifyOff", True)
        self.assertTrue(km._notify_muted("TESTSID", "TESTSID:g1"))
        km._set_notify_card("TESTSID:g1", True)
        self.assertFalse(km._notify_muted("TESTSID", "TESTSID:g1"),
                         "the per-card bell is what it's FOR once the session default is on")


class FeedNotifications(unittest.TestCase):
    """The diff detector: [(title, body, priority, sid)] per card newly in needs_input/completed."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.saved = jd.STATE
        jd.STATE = Path(self.td.name)
        km._notify_cards_cache.clear()
        km._flags_cache.clear()
        km._NOTIFY_PREV[0] = None
        km._NOTIFY_BLOCKED_SIDS.clear()

    def tearDown(self):
        jd.STATE = self.saved
        self.td.cleanup()

    def test_the_first_build_is_a_silent_baseline(self):
        out = km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "needs_input")))
        self.assertEqual(out, [], "existing state on start is status, not news (freshNeedsYou policy)")

    def test_a_card_entering_needs_input_notifies_with_nothing_armed(self):
        km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "working")))
        out = km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "needs_input")))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], "romp: web")
        self.assertTrue(out[0][1].startswith("Needs you: "), out[0][1])
        self.assertIn("Fix the login flow", out[0][1])
        self.assertEqual(out[0][2], "high", "blocked-on-you must break through a phone's quiet hours")
        self.assertEqual(out[0][3], "TESTSID", "the sid rides along for the click-through URL")

    def test_a_muted_session_is_silent(self):
        km._set_session_flag("TESTSID", "notifyOff", True)
        km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "working")))
        out = km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "needs_input")))
        self.assertEqual(out, [], "the bell is now a mute — turning it off is how you silence a session")

    def test_a_muted_sessions_armed_card_still_notifies(self):
        km._set_session_flag("TESTSID", "notifyOff", True)
        km._set_notify_card("TESTSID:g1", True)
        km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "working")))
        out = km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "needs_input")))
        self.assertEqual(len(out), 1, "one card you DO want to hear about, inside a session you don't")

    def test_a_completed_card_notifies_at_ordinary_priority(self):
        km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "working")))
        out = km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "completed")))
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0][1].startswith("Completed: "), out[0][1])
        self.assertEqual(out[0][2], "default", "finished work is news, not an interrupt")

    def test_an_on_you_api_error_says_what_to_DO_not_what_the_work_was(self):
        # tooLong/spendLimit/modelLimit already floor the card to needs_input (build_feed api_block), so
        # it arrives here as an ordinary column entry — only the wording differs.
        km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "working")))
        out = km._feed_notifications(_feed(_card(
            "TESTSID:g1", "TESTSID", "needs_input",
            blocked={"state": "apiError", "tooLong": True,
                     "what": "this session's prompt is too long — compact it to continue"})))
        self.assertEqual(len(out), 1)
        self.assertIn("compact it to continue", out[0][1])
        self.assertNotIn("Fix the login flow", out[0][1], "the goal title isn't the thing you must go do")
        self.assertEqual(out[0][2], "high")

    def test_holding_a_column_does_not_refire(self):
        km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "working")))
        km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "needs_input")))
        out = km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "needs_input")))
        self.assertEqual(out, [], "still blocked is not news — only the ENTRY event notifies")

    def test_reblocking_after_an_answer_notifies_again(self):
        km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "working")))
        km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "needs_input")))
        km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "working")))     # answered
        out = km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "needs_input")))
        self.assertEqual(len(out), 1, "a NEW block after the answer is a new event")

    def test_a_card_appearing_already_blocked_notifies(self):
        km._feed_notifications(_feed())                     # baseline consumed on an empty feed
        out = km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "needs_input")))
        self.assertEqual(len(out), 1, "work can SURFACE blocked — appearing there is entering there")

    def test_a_provisional_placeholder_never_notifies(self):
        km._feed_notifications(_feed())
        out = km._feed_notifications(
            _feed(_card("TESTSID:g1", "TESTSID", "needs_input", provisional=True)))
        self.assertEqual(out, [], "placeholder churn is not a stable card")

    def test_an_armed_card_leaving_the_feed_is_pruned(self):
        km._set_notify_card("TESTSID:g1", True)
        km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "working")))
        km._feed_notifications(_feed())                     # cleared/archived → id never comes back
        self.assertEqual(km._notify_cards(), {}, "the store tracks the live feed, not history")

    def test_the_blocked_sid_set_tracks_the_latest_build(self):
        km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "needs_input")))
        self.assertEqual(km._NOTIFY_BLOCKED_SIDS, {"TESTSID"})
        km._feed_notifications(_feed(_card("TESTSID:g1", "TESTSID", "working")))
        self.assertEqual(km._NOTIFY_BLOCKED_SIDS, set(), "the api-error fallback dedups against this")


class ApiErrorNotifications(unittest.TestCase):
    """The no-card fallback: a session stopped on an ON-YOU api error before any goal was filed."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.saved_state, self.saved_alive, self.saved_err = jd.STATE, km._alive_sessions, km._api_error
        jd.STATE = Path(self.td.name)
        km._flags_cache.clear()
        km._notify_cards_cache.clear()
        km._API_ERR_PREV[0] = None
        km._NOTIFY_BLOCKED_SIDS.clear()
        self.errs = {}
        km._alive_sessions = lambda now, tmux: [{"sid": s, "name": "web", "path": "/tmp/%s.jsonl" % s}
                                                for s in self.errs]
        km._api_error = lambda path: self.errs.get(Path(path).stem)

    def tearDown(self):
        jd.STATE = self.saved_state
        km._alive_sessions, km._api_error = self.saved_alive, self.saved_err
        self.td.cleanup()

    def _err(self, **kw):
        d = {"uuid": "11111111-2222-3333-4444-555555555555", "text": "Prompt is too long",
             "tooLong": False, "spendLimit": False, "modelLimit": False}
        d.update(kw)
        return d

    def test_the_first_pass_is_a_silent_baseline(self):
        self.errs["TESTSID"] = self._err(tooLong=True)
        self.assertEqual(km._api_error_notifications(0, {"TESTSID": {}}), [])

    def test_a_new_on_you_error_notifies(self):
        km._api_error_notifications(0, {})                  # baseline
        self.errs["TESTSID"] = self._err(tooLong=True)
        out = km._api_error_notifications(0, {"TESTSID": {}})
        self.assertEqual(len(out), 1)
        self.assertIn("compact it to continue", out[0][1])
        self.assertEqual(out[0][2], "high")

    def test_a_transient_error_never_notifies(self):
        km._api_error_notifications(0, {})
        self.errs["TESTSID"] = self._err(text="500 server_error")   # no on-you flag → auto-retry recovers it
        self.assertEqual(km._api_error_notifications(0, {"TESTSID": {}}), [],
                         "buzzing for something that fixes itself is a false interrupt")

    def test_the_same_standing_error_does_not_refire(self):
        km._api_error_notifications(0, {})
        self.errs["TESTSID"] = self._err(spendLimit=True)
        self.assertEqual(len(km._api_error_notifications(0, {"TESTSID": {}})), 1)
        self.assertEqual(km._api_error_notifications(0, {"TESTSID": {}}), [], "still stopped is not news")

    def test_a_fresh_attempt_is_a_fresh_event(self):
        km._api_error_notifications(0, {})
        self.errs["TESTSID"] = self._err(modelLimit=True, uuid="aaaa1111-2222-3333-4444-555555555555")
        km._api_error_notifications(0, {"TESTSID": {}})
        self.errs["TESTSID"] = self._err(modelLimit=True, uuid="bbbb1111-2222-3333-4444-555555555555")
        self.assertEqual(len(km._api_error_notifications(0, {"TESTSID": {}})), 1,
                         "a new failed attempt writes a new record — a new episode to hear about")

    def test_a_card_already_carrying_the_block_wins(self):
        km._api_error_notifications(0, {})
        self.errs["TESTSID"] = self._err(tooLong=True)
        km._NOTIFY_BLOCKED_SIDS.add("TESTSID")              # build_feed floored it to needs_input
        self.assertEqual(km._api_error_notifications(0, {"TESTSID": {}}), [],
                         "one stop, one notification — the card path already reported it")

    def test_a_muted_session_is_silent_here_too(self):
        km._api_error_notifications(0, {})
        km._set_session_flag("TESTSID", "notifyOff", True)
        self.errs["TESTSID"] = self._err(tooLong=True)
        self.assertEqual(km._api_error_notifications(0, {"TESTSID": {}}), [])


class NtfyConfig(unittest.TestCase):
    """The phone transport's config: file, env override, and the unconfigured no-op."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.saved_path = km._NTFY_CONFIG
        km._NTFY_CONFIG = Path(self.td.name) / "ntfy.json"
        km._ntfy_cache.clear()
        km._ntfy_complained[0] = 0
        self.saved_env = {k: os.environ.pop(k, None)
                          for k in ("ROMP_NTFY_URL", "ROMP_NTFY_TOPIC", "ROMP_NTFY_TOKEN", "ROMP_NTFY_CLICK")}

    def tearDown(self):
        km._NTFY_CONFIG = self.saved_path
        km._ntfy_cache.clear()
        for k, v in self.saved_env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        self.td.cleanup()

    def _write(self, d):
        km._NTFY_CONFIG.write_text(json.dumps(d))
        km._ntfy_cache.clear()

    def test_no_config_at_all_is_off(self):
        self.assertIsNone(km._ntfy_conf(), "nobody who hasn't set this up should publish anywhere")

    def test_a_config_without_a_topic_is_off(self):
        self._write({"url": "https://ntfy.example"})
        self.assertIsNone(km._ntfy_conf(), "a topic is the whole address — a url alone reaches nothing")

    def test_a_topic_defaults_the_rest(self):
        self._write({"topic": "TESTTOPIC"})
        c = km._ntfy_conf()
        self.assertEqual(c["topic"], "TESTTOPIC")
        self.assertEqual(c["url"], "https://ntfy.sh")
        self.assertEqual((c["token"], c["click"]), ("", ""))

    def test_a_trailing_slash_on_the_url_is_dropped(self):
        self._write({"topic": "TESTTOPIC", "url": "https://ntfy.example/"})
        self.assertEqual(km._ntfy_conf()["url"], "https://ntfy.example")

    def test_the_env_overrides_the_file(self):
        self._write({"topic": "TESTTOPIC", "url": "https://ntfy.example"})
        os.environ["ROMP_NTFY_TOPIC"] = "ENVTOPIC"
        self.assertEqual(km._ntfy_conf()["topic"], "ENVTOPIC")

    def test_the_env_alone_configures_it(self):
        os.environ["ROMP_NTFY_TOPIC"] = "ENVTOPIC"
        self.assertEqual(km._ntfy_conf()["topic"], "ENVTOPIC", "no file needed — a service unit can set it")

    def test_unreadable_json_is_off_but_LOUD(self):
        km._NTFY_CONFIG.write_text("{not json")
        km._ntfy_cache.clear()
        saved, sys.stderr = sys.stderr, io.StringIO()
        try:
            self.assertIsNone(km._ntfy_conf())
            said = sys.stderr.getvalue()
        finally:
            sys.stderr = saved
        self.assertIn("ntfy", said, "a typo'd config that silently stops your phone is unnoticeable otherwise")

    def test_publishing_with_nothing_configured_is_a_no_op(self):
        self.assertFalse(km._ntfy_publish("romp: web", "Needs you: something"),
                         "returns False rather than spawning a thread to nowhere")


class NtfyRequest(unittest.TestCase):
    """The request shape — the part that has to be right for a phone to ever ring."""

    CONF = {"url": "https://ntfy.example", "topic": "TESTTOPIC", "token": "", "click": ""}

    def test_the_topic_is_the_path_and_the_body_is_utf8(self):
        url, headers, data = km._ntfy_request(self.CONF, "romp: web", "Needs you: café")
        self.assertEqual(url, "https://ntfy.example/TESTTOPIC")
        self.assertEqual(data, "Needs you: café".encode("utf-8"))
        self.assertEqual(headers["Title"], "romp: web")

    def test_a_token_rides_as_a_bearer(self):
        _u, headers, _d = km._ntfy_request({**self.CONF, "token": "TESTTOKEN"}, "t", "b")
        self.assertEqual(headers["Authorization"], "Bearer TESTTOKEN")

    def test_no_token_sends_no_auth_header(self):
        _u, headers, _d = km._ntfy_request(self.CONF, "t", "b")
        self.assertNotIn("Authorization", headers)

    def test_priority_and_tags_ride_as_headers(self):
        _u, headers, _d = km._ntfy_request(self.CONF, "t", "b", priority="high", tags="warning")
        self.assertEqual((headers["Priority"], headers["Tags"]), ("high", "warning"))

    def test_the_click_url_comes_from_the_call_then_the_config(self):
        _u, h1, _d = km._ntfy_request({**self.CONF, "click": "https://dash.example/"}, "t", "b")
        self.assertEqual(h1["Click"], "https://dash.example/")
        _u, h2, _d = km._ntfy_request({**self.CONF, "click": "https://dash.example/"}, "t", "b",
                                      click="https://dash.example/?sid=TESTSID")
        self.assertEqual(h2["Click"], "https://dash.example/?sid=TESTSID")

    def test_a_title_that_would_break_the_socket_is_sanitized(self):
        # HTTP header values are latin-1 and single-line; a session name is neither by construction, and
        # an unencodable one raises inside http.client and LOSES the notification.
        _u, headers, _d = km._ntfy_request(self.CONF, "romp: 🚀 web\nsecond line", "b")
        headers["Title"].encode("latin-1")               # must not raise
        self.assertNotIn("\n", headers["Title"])
        self.assertIn("web", headers["Title"])

    def test_a_topic_with_url_characters_is_escaped_into_the_path(self):
        url, _h, _d = km._ntfy_request({**self.CONF, "topic": "a b/c"}, "t", "b")
        self.assertEqual(url, "https://ntfy.example/a%20b%2Fc")


class NotifyDispatch(unittest.TestCase):
    """_notify is the one choke point: every trigger reaches BOTH transports."""

    def setUp(self):
        self.saved_sys, self.saved_pub, self.saved_conf = km._system_notify, km._ntfy_publish, km._ntfy_conf
        self.os_calls, self.pub_calls = [], []
        km._system_notify = lambda t, b: self.os_calls.append((t, b))
        km._ntfy_publish = lambda t, b, **kw: self.pub_calls.append((t, b, kw))
        km._ntfy_conf = lambda: {"url": "https://ntfy.example", "topic": "TESTTOPIC", "token": "",
                                 "click": "https://dash.example/?sid={sid}"}

    def tearDown(self):
        km._system_notify, km._ntfy_publish, km._ntfy_conf = self.saved_sys, self.saved_pub, self.saved_conf

    def test_both_transports_fire(self):
        km._notify("romp: web", "Needs you: something", priority="high", tags="warning", sid="TESTSID")
        self.assertEqual(len(self.os_calls), 1)
        self.assertEqual(len(self.pub_calls), 1)
        self.assertEqual(self.pub_calls[0][2]["priority"], "high")

    def test_the_sid_placeholder_is_substituted_into_the_click_url(self):
        km._notify("romp: web", "b", sid="TESTSID")
        self.assertEqual(self.pub_calls[0][2]["click"], "https://dash.example/?sid=TESTSID")

    def test_an_unconfigured_click_stays_empty(self):
        km._ntfy_conf = lambda: None
        km._notify("romp: web", "b", sid="TESTSID")
        self.assertEqual(self.pub_calls[0][2]["click"], "")


class SystemNotify(unittest.TestCase):
    def test_darwin_shells_out_to_osascript_with_escaped_strings(self):
        calls = []
        saved_popen, saved_platform = km.subprocess.Popen, sys.platform
        km.subprocess.Popen = lambda cmd, **kw: calls.append(cmd)
        sys.platform = "darwin"
        try:
            km._system_notify('romp: web', 'Needs you: fix the "login" flow')
        finally:
            km.subprocess.Popen = saved_popen
            sys.platform = saved_platform
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "osascript")
        self.assertEqual(calls[0][1], "-e")
        self.assertIn('with title "romp: web"', calls[0][2])
        self.assertIn('\\"login\\"', calls[0][2], "quotes are escaped into the AppleScript string")

    def test_a_missing_binary_never_raises(self):
        saved = km.subprocess.Popen

        def boom(cmd, **kw):
            raise OSError("no such binary")
        km.subprocess.Popen = boom
        try:
            km._system_notify("t", "b")                    # must not raise — best-effort by contract
        finally:
            km.subprocess.Popen = saved


class NotifyWiring(unittest.TestCase):
    """Source pins: the flag reaches every payload + the detectors ride the right events."""

    @classmethod
    def setUpClass(cls):
        cls.src = Path(os.path.join(BIN, "romp-kernel")).resolve().read_text()

    def test_the_session_bell_rides_both_session_payloads(self):
        # the timeline lane row AND the chat session payload both echo it (lane bell + tab menu)
        self.assertEqual(self.src.count('"notify": _notify_on(sid)'), 2)

    def test_the_wire_stays_positive_while_the_store_holds_the_mute(self):
        # clients render "bell on/off"; the inversion lives in the ONE place that writes the flag
        self.assertIn('_flag, _val = "notifyOff", not _val', self.src)
        self.assertIn('return not _session_flag(sid, "notifyOff")', self.src)

    def test_every_ask_carries_its_card_arming(self):
        self.assertIn('_a["notify"] = True if _ncards.get(_a["itemId"]) else None', self.src)

    def test_the_ws_handler_persists_the_card_toggle(self):
        self.assertIn('msg.get("type") == "cardNotify"', self.src)
        self.assertIn('_set_notify_card(str(msg["itemId"]), bool(msg.get("value")))', self.src)

    def test_the_store_mtime_busts_the_feed_cache(self):
        self.assertIn('(jd.STATE / "notify-cards.json", "__ncards__")', self.src,
                      "arming a card must reach the next build, not wait out the sig")

    def test_fresh_feed_builds_drive_the_notifier(self):
        # the detector runs where the fresh build lands — the one choke point every push shares
        self.assertIn("for _t, _b, _p, _s in _feed_notifications(feed):", self.src)
        self.assertIn("_notify(_t, _b, priority=_p", self.src)

    def test_the_bells_ring_with_no_browser_open(self):
        # build_feed only runs inside a push, so without this the last pane closing silences everything —
        # exactly when a phone notification is the point
        self.assertIn("_headless_notify_tick(int(time.time()), _tmux_sessions())", self.src)
        self.assertIn("for _t, _b, _p, _s in _api_error_notifications(int(time.time()), _tmux_sessions()):",
                      self.src)

    def test_the_headless_build_is_event_keyed_not_clock_keyed(self):
        # _fleet_view_sig carries a 5s time bucket, so keying on it would rebuild the feed forever on an
        # idle machine; the substantive signal is _producer_sig + the judge generation
        self.assertIn("sig = (json.dumps(_producer_sig(True), sort_keys=True, default=str), _judge_gen[0])",
                      self.src)

    def test_the_topic_never_lands_in_the_repo(self):
        # it's a bearer secret: whoever has it can read every notification and post to the topic
        self.assertIn('_NTFY_CONFIG = Path(os.path.expanduser("~/.config/romp/ntfy.json"))', self.src)


if __name__ == "__main__":
    unittest.main()
