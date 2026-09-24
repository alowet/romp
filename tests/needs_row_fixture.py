"""One Needs-you ask carrying a DISTINCT non-None value for every card field but `blocked`, for two tests: the row projection
(tests/test_chat_notices.py asserts each row value equals the ask's, the tree through the kernel's projection) and the chat
signature's differential (tests/test_chat_build_sig_inputs.py reads WHICH fields are structured from the row this ask builds,
never from a hand-written list). A contributor's post-merge note on PR 2124: seven single-edit mutants of the row builder (a
field set to None, a field read from the wrong key, every unfixtured field set to None) passed a fixture that populated five
fields. `blocked` stays None because a live-block object never rides a plain row: the credential floor builds the fix row, which
carries no card field, and every other live block is a hard stop, which takes no row. Booleans alternate, so a swap between two
of them shows where the values differ. Synthetic values throughout (a placeholder sid, invented text)."""

PEER_API = "22222222-2222-3333-4444-000000000902"
PEER_TESTS = "33333333-2222-3333-4444-000000000903"
PEER_WEB = "44444444-2222-3333-4444-000000000904"


def populated_ask(sid, category="needs_input"):
    gid = sid + ":g6"
    return {
        "itemId": gid, "sid": sid, "text": "which port do the fixtures own?", "live": True, "t": 108, "board": "feed", "category": category,
        # the sections
        "summary": "the suite targets Postgres and the fixtures load into one database",
        "blockSummary": "Postgres or SQLite: the fixtures differ and the port is not yet chosen",
        "briefParts": [{"id": gid + "a", "since": 11}, {"id": gid + ":open"}],
        "summaryParts": [{"id": gid + "b", "since": 12}],
        "distillState": "blocked",
        "summaryStale": True,
        "relayNote": "the api session still holds the question",
        "background": "the suite has two databases and the fixtures load into one",
        "stalled": {"why": "no turn in 2h", "since": 13, "note": "the fixtures wait on a port"},
        "tree": [{"id": gid, "kind": "ask", "text": "which port do the fixtures own?", "status": "open", "children": [gid + "a"], "trgb": [1, 2, 3], "last": 5, "whoWorking": "web"},
                 {"id": gid + "a", "kind": "ask", "text": "pick a port", "status": "done", "children": [], "parked": {"n": 1}, "log": ["a line the row never carries"]}],
        "awaiting": {"why": "a job on the cluster", "kind": "task", "since": 14, "tasks": ["the migration"]},
        # the name row's state badges
        "recheck": True, "rejudging": False, "nudgeFailed": True,
        "nudged": {"count": 2, "times": [21, 22]},
        "interrupting": False, "interrupted": True,
        "waitingOn": {"name": "api", "kind": "delegate", "since": 15},
        "origin": {"peer": "api", "peerSid": PEER_API, "live": True},
        "handoffTo": {"peer": "tests", "peerSid": PEER_TESTS},
        # the warning chip's evidence, the line's landings, the swirl's inputs
        "warns": [{"kind": "brief-failed", "t": 16, "msg": "the brief could not be written", "detail": "the model returned nothing"}],
        "failLog": [{"t": 17, "line": "brief", "model": "opus", "note": "529"}],
        "summaryAnchorUuid": "u-anchor-6", "summaryAnchorQuote": "the fixtures load into one database",
        "summaryAnchorsPara": [{"u": "u-para-1"}, None],
        "doneConfirming": False,
        "blocked": None,
        "column": category,
        "judging": True,
        "working": {"since": 18, "toolUses": 3},
        "sessState": "idle",
        "delegTracked": [{"sid": PEER_WEB, "name": "web"}],
    }
