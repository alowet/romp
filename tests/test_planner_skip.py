#!/usr/bin/env python3
"""The planner skips a session whose inputs have not moved since a pass that had nothing to do (2026-09-09).

Measured on the maintainer's box: the planner worker pool was 37% of the process's samples, re-deriving every
session's segmentation, plan units and placement normalization on every pass. The gate keys each session on
every input the pass reads, taken before the store read: the parse cache's key bound to the session object,
the store with its journal and archive, the episode log, the session's task-store files, the reg file and the
transcript path; it records only when the pass placed nothing, collected no unit and left the store's key
unchanged. Pins: unchanged inputs skip after a pass that had nothing to do; a moved store, a fresh parse, a
task-store change alone and a reg change alone each un-skip that session; a write landing during the pass is
seen next pass; three sessions with one moved leave placements and nodes byte-identical to the ungated passes
(two fresh worlds); a parse the cache does not hold is never skipped; a rebound root forgets; the counters.

Synthetic sids and text; a temp state root, a temp Claude config root for the task store; the planner's model
calls are stubs, deterministic, so two worlds agree byte for byte."""
import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
os.environ.pop("ROMP_STATE_DIR", None)  # a live kernel's export outranks the XDG floor
jd = SourceFileLoader("romp_judge_planner_skip", os.path.join(BIN, "romp-judge")).load_module()

A = "11111111-2222-3333-4444-555555555501"
B = "11111111-2222-3333-4444-555555555502"
C = "11111111-2222-3333-4444-555555555503"
NOW = 1781100000
T0 = NOW - 3600


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def uline(t, text, uuid, parent=None):
    return {"type": "user", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent,
            "message": {"role": "user", "content": text}, "promptSource": "typed"}


def aline(t, text, uuid, parent):
    return {"type": "assistant", "timestamp": iso(t), "uuid": uuid, "parentUuid": parent,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}}


class _World(unittest.TestCase):
    SIDS = (A, B, C)
    PROMPTS = {A: "wire up the reconnect banner", B: "retire the request cap", C: "fix the mobile tab width"}

    def setUp(self):
        self.saved = (jd.STATE, jd.NAMES, jd.PROJECTS, jd.plan_llm, jd.opener_llm, jd.group_llm, jd._judge_run,
                      os.environ.get("CLAUDE_CONFIG_DIR"))
        jd.opener_llm = lambda text, menu, sibling_num=None, **kw: '{"ops":[{"why":"a new ask","do":"mint","text":"Ship: %s"}]}' % text.split("\n")[0][:40]
        jd.plan_llm = lambda *a, **kw: '{"ops":[{"why":"a new ask","do":"mint","text":"Ship: %s"}]}' % str(a[0] if a else "").split("\n")[0][:40]
        jd.group_llm = lambda menu, **kw: '{"ops":[]}'
        jd._judge_run = lambda *a, **kw: "{}"
        self._make_world()

    def tearDown(self):
        self._drop_world()
        (jd.STATE, jd.NAMES, jd.PROJECTS, jd.plan_llm, jd.opener_llm, jd.group_llm, jd._judge_run, cfg) = self.saved
        jd._rebind_state(jd.STATE)
        if cfg is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = cfg

    def _make_world(self):
        self.td = tempfile.TemporaryDirectory()
        td = Path(self.td.name)
        jd._rebind_state(td / "state")
        self.cfg = td / "claude"
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.cfg)
        cdir = td / "launchdir"; cdir.mkdir()
        proj = self.cfg / "projects"
        self.proj_dir = proj / re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(str(cdir)))
        self.proj_dir.mkdir(parents=True)
        names = td / "names"; names.mkdir()
        for i, sid in enumerate(self.SIDS):
            (names / sid).write_text("worker%d\t%s\t#abcdef\n" % (i, str(cdir)))
        jd.NAMES, jd.PROJECTS = names, proj
        jd.GOALDIR.mkdir(parents=True, exist_ok=True)
        self.recs = {sid: [] for sid in self.SIDS}
        self._reset()
        for sid in self.SIDS:
            self.prompt(sid, T0 + 10 * self.SIDS.index(sid))

    def _drop_world(self):
        self._reset()
        self.td.cleanup()

    @staticmethod
    def _reset():
        jd._PARSE_CACHE.clear(); jd._CHAIN_MEMO.clear(); jd._episode_memo.clear(); jd._shared_clear()
        jd._PLANNER_SEEN.clear()
        for k in jd._PLANNER_STATS:
            jd._PLANNER_STATS[k] = 0
        jd._discover_cache["fp"] = None
        jd._discover_cache["result"] = None

    def prompt(self, sid, t, text=None):
        """A human prompt and its reply land in `sid`'s transcript: one plan unit's worth."""
        n = len(self.recs[sid]) // 2 + 1
        parent = self.recs[sid][-1]["uuid"] if self.recs[sid] else None
        text = text or self.PROMPTS[sid]
        self.recs[sid] += [uline(t, text, "u%d" % n, parent), aline(t + 30, "Done: %s." % text, "a%d" % n, "u%d" % n)]
        p = self.proj_dir / (sid + ".jsonl")
        p.write_text("\n".join(json.dumps(r) for r in self.recs[sid]) + "\n")
        os.utime(p, (t + 60, t + 60))                       # a distinct mtime per write: the parse key moves
        jd._discover_cache["fp"] = None
        jd._discover_cache["result"] = None

    def run_pass(self, now=NOW):
        """One planner pass; returns the gate counters' deltas (planned, skipped, recorded)."""
        before = jd.planner_skip_stats()
        jd._discover_cache["fp"] = None
        jd._discover_cache["result"] = None
        jd.run_plan(now=now)
        after = jd.planner_skip_stats()
        return tuple(after[k] - before[k] for k in ("planned", "skipped", "recorded"))

    def stores(self):
        return {sid: json.loads((jd.GOALDIR / (sid + ".json")).read_text()) for sid in self.SIDS}

    def settle(self):
        """Plan until every session has nothing to do and is recorded; then a pass skips all three."""
        for _ in range(4):
            p, s, r = self.run_pass()
            if p == 0:
                break
        self.assertEqual(self.run_pass(), (0, 3, 0), "settled: all three skipped")


class PlannerSkip(_World):
    def test_unchanged_inputs_skip_after_a_pass_that_had_nothing_to_do(self):
        p, s, r = self.run_pass()
        self.assertEqual((p, s), (3, 0), "first pass: every session planned")
        stores = self.stores()
        self.assertTrue(all(st["nodes"] for st in stores.values()), "each prompt minted its top")
        self.assertTrue(all(len(st["placements"]) >= 1 for st in stores.values()))
        # a pass that has nothing left to do records; the next one skips
        for _ in range(3):
            p, s, r = self.run_pass()
            if r == 3:
                break
        self.assertEqual(r, 3, "every session recorded after a pass with nothing to do")
        self.assertEqual(self.run_pass(), (0, 3, 0))
        self.assertEqual(self.stores(), stores, "a skipped pass writes nothing")

    def test_a_moved_store_un_skips_that_session_only(self):
        self.settle()
        p = jd.GOALDIR / (A + ".json")
        d = json.loads(p.read_text()); d["seq"] = d.get("seq", 0) + 1
        p.write_text(json.dumps(d))
        planned, skipped, recorded = self.run_pass()
        self.assertEqual((planned, skipped), (1, 2), "A's store moved: A planned, B and C skipped")

    def test_a_fresh_parse_un_skips_and_the_new_prompt_is_placed(self):
        self.settle()
        self.prompt(B, T0 + 500, "and add the retry hint")
        planned, skipped, recorded = self.run_pass()
        self.assertEqual((planned, skipped), (1, 2), "B's transcript grew: B alone planned")
        st = self.stores()[B]
        self.assertEqual(len([n for n in st["nodes"].values() if n.get("parentId") is None]), 2, "the second ask minted")

    def test_a_task_store_change_alone_un_skips(self):
        self.settle()
        d = self.cfg / "tasks" / C
        d.mkdir(parents=True)
        (d / "1.json").write_text(json.dumps({"id": "1", "subject": "check the width on iOS", "status": "pending"}))
        self.assertEqual(self.run_pass()[0:2], (1, 2), "C's task store appeared: C alone planned")
        self.settle()
        (d / "1.json").write_text(json.dumps({"id": "1", "subject": "check the width on iOS", "status": "completed"}))
        os.utime(d / "1.json", (NOW + 5, NOW + 5))
        self.assertEqual(self.run_pass()[0:2], (1, 2), "a task's status moved: C alone planned")

    def test_a_reg_change_alone_un_skips(self):
        self.settle()
        jd.SDKDIR.mkdir(parents=True, exist_ok=True)
        (jd.SDKDIR / (A + ".json")).write_text(json.dumps({"sid": A, "name": "worker0", "cwd": "/tmp", "auth": "login"}))
        self.assertEqual(self.run_pass()[0:2], (1, 2), "A's reg appeared: A alone planned")

    def test_a_write_landing_during_the_pass_is_seen_next_pass(self):
        # INTERLEAVED WRITE: the key is taken before the store read; a journal row lands while the pass reads
        # A's store, so the key A records predates the file, and the next pass plans A again.
        self.settle()
        self.prompt(A, T0 + 600, "and the dark theme")            # A has work again: this pass plans it
        real = jd.load_goals
        landed = []

        def read_then_write(fsid):
            store = real(fsid)
            if fsid == A and not landed:
                landed.append(True)
                jd._overrides_dir().mkdir(parents=True, exist_ok=True)
                with (jd._overrides_dir() / (A + ".jsonl")).open("a") as f:
                    f.write(json.dumps({"op": "resolve", "id": A + ":gX", "t": NOW}) + "\n")
            return store
        jd.load_goals = read_then_write
        try:
            self.run_pass()                                    # plans A (units) with the write landing mid-pass
            counts = self.run_pass()                           # nothing to do now; A's recording pass
        finally:
            jd.load_goals = real
        self.assertTrue(landed)
        self.assertEqual(counts[0:2], (1, 2), "A planned again: the key it would have recorded predates the write")
        for _ in range(3):                                     # the replayed row may move the store once more
            counts = self.run_pass()
            if counts[0] == 0:
                break
        self.assertEqual(counts, (0, 3, 0), "A recorded with the post-write key, then skipped")

    def test_three_sessions_one_moved_leave_placements_and_nodes_identical_to_the_ungated_passes(self):
        def scenario(gated):
            self.settle()
            self.prompt(B, T0 + 500, "and add the retry hint")  # B moves
            if not gated:
                jd._PLANNER_SEEN.clear()
            counts = self.run_pass(now=NOW + 100)
            if not gated:
                jd._PLANNER_SEEN.clear()
            self.run_pass(now=NOW + 200)
            shape = {sid: json.dumps({"nodes": st["nodes"], "placements": st["placements"], "status": st["status"]},
                                     sort_keys=True) for sid, st in self.stores().items()}
            return counts, shape
        gated_counts, gated = scenario(True)
        self._drop_world(); self._make_world()
        ungated_counts, ungated = scenario(False)
        self.assertEqual(gated_counts[0:2], (1, 2), "gated: B planned, A and C skipped")
        self.assertEqual(ungated_counts[0:2], (3, 0), "ungated: all planned")
        self.assertEqual(gated, ungated, "byte-identical nodes, placements and status either way")

    def test_a_parse_the_cache_does_not_hold_is_never_skipped(self):
        real = jd.parsed_session
        jd.parsed_session = lambda fsid, paths, now: dict(real(fsid, paths, now))
        try:
            for _ in range(3):
                self.run_pass()
            self.assertEqual(self.run_pass(), (3, 0, 0), "unkeyed: planned every pass, never recorded")
        finally:
            jd.parsed_session = real

    def test_a_rebound_root_forgets_the_table(self):
        self.settle()
        self.assertTrue(jd._PLANNER_SEEN)
        other = tempfile.TemporaryDirectory()
        try:
            jd._rebind_state(Path(other.name))
            self.assertEqual(jd._PLANNER_SEEN, {})
        finally:
            jd._rebind_state(Path(self.td.name) / "state")
            other.cleanup()

    def test_the_counters(self):
        self.assertEqual(set(jd.planner_skip_stats()), {"skipped", "planned", "recorded"})
        s = jd.planner_skip_stats(); s["skipped"] = 99
        self.assertNotEqual(jd.planner_skip_stats()["skipped"], 99)


if __name__ == "__main__":
    unittest.main()
