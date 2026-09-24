"""A FAKE `claude_agent_sdk` for the hermetic served labs, so a real SdkBackend/SdkSession runs a real
turn end to end WITHOUT a real Claude CLI or the real Agent SDK (which is not installed in the test
environment). It is put on the kernel subprocess's PYTHONPATH by the lab; the kernel's lazy
`from claude_agent_sdk import ...` then resolves to this package, `sdk_importable()`/`_ensure_sdk_on_path`
see it, and the real feeder + receiver run against `ClaudeSDKClient` below.

The client scripts turns IN-PROCESS (no subprocess, ignoring cli_path/transport), the way the FakeClient
in tests/test_sdk_backend.py does, and additionally WRITES the CLI's transcript records to disk (Claude's
projects layout) so the kernel's real landing/parse machinery lands each send and renders each reply,
exactly as the send-bubble lab appends records, never a hand-injected browser frame.

The one behaviour the labs turn on: a `/clear` turn emits an `init` SystemMessage carrying a FRESH
session_id (a new episode), which the real kernel reads as the /clear boundary (SdkSession._on_message:
lastSid flips, the clearing bracket ends). Like CLI 2.1.280, the /clear then writes the fresh episode's
record GROUP within milliseconds of the init: an isMeta session caveat, the /clear command-name wrapper
(the record that LANDS the slash send), and a local-command-stdout record, so the /clear renders as a
landed command row rather than a stuck chip. A plain message emits an init carrying the RESUMED id (no
flip) and writes a user record + an assistant reply under the current episode's file. SYNTHETIC only:
invented reply text, placeholder uuids, hostname TESTHOST.

Environment knobs (read by the client, set by the lab):
  ROMP_FAKE_SDK_REPLY   the assistant reply text for a plain message (default a synthetic line)
  ROMP_FAKE_SDK_GATE    a file path the /clear turn waits to exist before it runs (the lab creates it to release the in-flight clear)
"""
import asyncio
import json
import os
import re
import time
import uuid as _uuid
from datetime import datetime, timezone


# ── message + option types the kernel duck-types (attribute names match the real SDK / the test doubles
#    in tests/test_sdk_backend.py) ───────────────────────────────────────────────────────────────────
class TextBlock:
    def __init__(self, text):
        self.text = text


class ToolUseBlock:
    def __init__(self, id, name, input):
        self.id, self.name, self.input = id, name, input


class ToolResultBlock:
    def __init__(self, tool_use_id, content="", is_error=False):
        self.tool_use_id, self.content, self.is_error = tool_use_id, content, is_error


class SystemMessage:
    def __init__(self, subtype, data=None):
        self.subtype = subtype
        self.data = data or {}


class AssistantMessage:
    def __init__(self, content, model="claude-fable-5-1", uuid=None, stop_reason="end_turn",
                 parent_tool_use_id=None):
        self.content = content
        self.model = model
        self.uuid = uuid or ("a-" + _uuid.uuid4().hex[:8])
        self.stop_reason = stop_reason
        self.parent_tool_use_id = parent_tool_use_id


class UserMessage:
    def __init__(self, content, uuid=None, tool_use_result=None):
        self.content = content
        self.uuid = uuid or ("u-" + _uuid.uuid4().hex[:8])
        self.tool_use_result = tool_use_result


class ResultMessage:
    def __init__(self, subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                 num_turns=1, session_id=None, total_cost_usd=0.0, usage=None, **kw):
        self.subtype = subtype
        self.duration_ms = duration_ms
        self.duration_api_ms = duration_api_ms
        self.is_error = is_error
        self.num_turns = num_turns
        self.session_id = session_id
        self.total_cost_usd = total_cost_usd
        self.usage = usage or {}
        self.uuid = "r-" + _uuid.uuid4().hex[:8]
        for k, v in kw.items():
            setattr(self, k, v)


class ClaudeAgentOptions:
    def __init__(self, **kw):
        self.can_use_tool = None
        self.resume = None
        self.session_id = None
        self.cwd = None
        self.env = None
        for k, v in kw.items():
            setattr(self, k, v)


class HookMatcher:
    def __init__(self, matcher=None, hooks=None, timeout=None):
        self.matcher, self.hooks, self.timeout = matcher, hooks, timeout


class PermissionResultAllow:
    def __init__(self, updated_input=None, **kw):
        self.updated_input = updated_input


class PermissionResultDeny:
    def __init__(self, message="", **kw):
        self.message = message


class PermissionUpdate:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class MessageOrigin:
    pass


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _proj_dir(cwd):
    # FAIL LOUD, never touch the real store: with CLAUDE_CONFIG_DIR UNSET the transcripts would be written
    # under the developer's real ~/.claude. The one user (the served lab) always sets it via kernel_env, so
    # this is a safety net, not a normal path: refuse rather than write outside the hermetic root.
    root = os.environ.get("CLAUDE_CONFIG_DIR")
    if not root:
        raise RuntimeError("fake claude_agent_sdk: CLAUDE_CONFIG_DIR is unset; refusing to write transcripts "
                           "under the real ~/.claude store (set CLAUDE_CONFIG_DIR to a hermetic root)")
    return os.path.join(root, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(os.path.expanduser(cwd or "~"))))


def _transcript(cwd, fsid):
    return os.path.join(_proj_dir(cwd), fsid + ".jsonl")


def _append(path, record):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def _is_clear(text):
    t = (text or "").strip()
    return t == "/clear" or t.startswith("/clear ")


def _turn_text(turn):
    try:
        content = turn["message"]["content"]
        if isinstance(content, str):
            return content
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    except Exception:
        return ""


class _Query:
    async def _send_control_request(self, req):
        # get_usage / other control requests: a benign empty snapshot (the labs assert nothing off it)
        return {}


class ClaudeSDKClient:
    """The real split: query(iterable) WRITES turns, receive_messages() yields output independently, so
    the backend's concurrent feeder+receiver both run. Turns are scripted in-process; no subprocess."""

    def __init__(self, options=None, transport=None):
        self.options = options
        self._turnq = asyncio.Queue()
        self._query = _Query()
        # the episode the CLI is writing to right now (the resumed id, then a fresh id after a /clear)
        self._fsid = (getattr(options, "session_id", None) or getattr(options, "resume", None) or "fsid")
        self._cwd = getattr(options, "cwd", None)
        self._init_sent = False
        self._parent = None   # parentUuid chain within the current episode

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def query(self, prompt, session_id="default"):
        async for turn in prompt:
            await self._turnq.put(turn)

    async def interrupt(self):
        pass

    async def set_model(self, model=None):
        pass

    async def set_permission_mode(self, mode):
        pass

    async def get_context_usage(self):
        return {"percentage": 2, "model": "claude-fable-5-1"}

    async def get_server_info(self):
        return {"commands": []}

    async def receive_messages(self):
        # A /clear is held IN FLIGHT on an EVENT, not a timer: if ROMP_FAKE_SDK_GATE names a path, the /clear turn
        # waits until that file exists (the served lab creates it AFTER capturing the in-flight snapshot), so the
        # test controls exactly when the clear runs; the lab then POLLS the client's recorded frames for the
        # settled state. Bounded (~15s): a lab that forgets to create the gate RAISES below rather than running
        # the /clear late or hanging.
        gate = os.environ.get("ROMP_FAKE_SDK_GATE") or ""
        while True:
            turn = await self._turnq.get()
            text = _turn_text(turn)
            clear = _is_clear(text)
            if clear and gate:
                for _ in range(300):   # loop-ok: bounded (~15s) wait for the test to create the gate file
                    if os.path.exists(gate):
                        break
                    await asyncio.sleep(0.05)
                else:
                    raise RuntimeError(
                        "fake claude_agent_sdk: ROMP_FAKE_SDK_GATE file %r never appeared after ~15s; "
                        "the served lab must create it to release the in-flight /clear" % gate)
            if clear:
                # a /clear mints a FRESH episode: the init carries a NEW session_id → the kernel flips
                # lastSid and ends the clearing bracket. CLI 2.1.280 then writes a fresh-episode record GROUP
                # within milliseconds of the init (the earlier fixture wrote NOTHING here, so the /clear never
                # landed and rode on as a stuck chip): an isMeta session caveat (harness noise the kernel
                # skips), the /clear COMMAND-NAME wrapper (the record that LANDS a slash send, matched under
                # kernel/session_backend.py command_text_key, so the /clear renders as a LANDED command row),
                # and a local-command-stdout record (its output).
                self._fsid = "fsid-" + _uuid.uuid4().hex[:12]
                self._parent = None
                yield SystemMessage("init", {"model": "claude-fable-5-1", "permissionMode": "acceptEdits",
                                             "session_id": self._fsid})
                now = int(time.time())
                path = _transcript(self._cwd, self._fsid)
                cav = "u-" + _uuid.uuid4().hex[:10]
                _append(path, {"type": "user", "timestamp": _iso(now), "uuid": cav, "parentUuid": None,
                               "isMeta": True, "sessionId": self._fsid,
                               "message": {"role": "user", "content":
                                           "Caveat: The messages below were generated by the user while running "
                                           "local commands. DO NOT respond to these messages or otherwise consider "
                                           "them in your response unless the user explicitly asks you to."}})
                cmd = "u-" + _uuid.uuid4().hex[:10]
                _append(path, {"type": "user", "timestamp": _iso(now), "uuid": cmd, "parentUuid": cav,
                               "sessionId": self._fsid,
                               "message": {"role": "user", "content":
                                           "<command-name>/clear</command-name>\n<command-message>clear"
                                           "</command-message>\n<command-args></command-args>"}})
                out = "u-" + _uuid.uuid4().hex[:10]
                _append(path, {"type": "user", "timestamp": _iso(now), "uuid": out, "parentUuid": cmd,
                               "sessionId": self._fsid,
                               "message": {"role": "user", "content": "<local-command-stdout></local-command-stdout>"}})
                self._parent = out
                yield ResultMessage(subtype="success", is_error=False, num_turns=1, session_id=self._fsid,
                                    total_cost_usd=0.0)
                continue
            if not self._init_sent:
                # the first plain turn of a connection carries the init with the RESUMED id (no flip)
                self._init_sent = True
                yield SystemMessage("init", {"model": "claude-fable-5-1", "permissionMode": "acceptEdits",
                                             "session_id": self._fsid})
            # write the CLI's transcript records for this turn, so the kernel lands the send and renders
            # the reply through its REAL parse/landing path (not an injected frame)
            now = int(time.time())
            path = _transcript(self._cwd, self._fsid)
            u_uuid = "u-" + _uuid.uuid4().hex[:10]
            _append(path, {"type": "user", "timestamp": _iso(now), "uuid": u_uuid, "parentUuid": self._parent,
                           "promptSource": "sdk", "sessionId": self._fsid,
                           "message": {"role": "user", "content": text}})
            reply = os.environ.get("ROMP_FAKE_SDK_REPLY") or "Rebuilt the search index; 3 shards refreshed."
            a_uuid = "a-" + _uuid.uuid4().hex[:10]
            _append(path, {"type": "assistant", "timestamp": _iso(now + 1), "uuid": a_uuid, "parentUuid": u_uuid,
                           "sessionId": self._fsid,
                           "message": {"role": "assistant", "model": "claude-fable-5-1", "stop_reason": "end_turn",
                                       "content": [{"type": "text", "text": reply}]}})
            self._parent = a_uuid
            yield AssistantMessage(content=[TextBlock(reply)], model="claude-fable-5-1", uuid=a_uuid)
            yield ResultMessage(subtype="success", is_error=False, num_turns=1, session_id=self._fsid,
                                total_cost_usd=0.0)
