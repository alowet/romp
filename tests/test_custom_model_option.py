#!/usr/bin/env python3
"""The CLI's custom-model option is offered per SESSION, and only there (the user 2026-08-13).

Claude Code can expose ONE model beyond the Claude ladder via ANTHROPIC_CUSTOM_MODEL_OPTION (+ _NAME),
which is how a gateway-routed model reaches its own picker. Sessions could already RUN on it — nothing
in the kernel's setModel or the SDK backend validates a model value — but romp never OFFERED it, because
MODEL_CHOICES is a literal, so no surface ever asked for it.

Two things this pins. First, the option is read from the SETTINGS FILE, not os.environ: that env lives in
~/.claude/settings.json, which Claude Code applies to itself, so a session the SDK spawns has it while the
kernel — started by the login service — does not. Second, it reaches the SESSION pickers only: the
judge-tier dropdowns read the same /models payload, and _set_judge_model validates against _MODEL_VALUES,
so listing it there would offer a control that silently refuses the pick.

SYNTHETIC only: invented model ids, temp dirs.
"""
import json
import os
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
os.environ["ROMP_KERNEL_NO_OPEN"] = "1"
os.environ.setdefault("ROMP_SERVE_TOKEN", "testtok")
km = SourceFileLoader("romp_kernel_custommodel", os.path.join(BIN, "romp-kernel")).load_module()

ENV_VALUE = "ANTHROPIC_CUSTOM_MODEL_OPTION"
ENV_NAME = "ANTHROPIC_CUSTOM_MODEL_OPTION_NAME"
# A synthetic routed model — deliberately not a real vendor id, so nothing here reads as a live config.
ROUTED, ROUTED_NAME = "vendor-x-1", "Vendor X 1"


class CustomModelOption(unittest.TestCase):
    def setUp(self):
        # PIN the environment. The suite may well be run from a shell that Claude Code started, which
        # applies settings.json's env to its own children — so these vars can be inherited for real, and
        # an unpinned test would pass or fail depending on whose machine ran it (CONTRIBUTING asks any
        # test touching machine state to pin it rather than inherit it).
        self._saved_env = {k: os.environ.pop(k, None) for k in (ENV_VALUE, ENV_NAME)}
        self._saved_settings = km._CLAUDE_SETTINGS
        self.td = tempfile.TemporaryDirectory()
        km._CLAUDE_SETTINGS = Path(self.td.name) / "settings.json"

    def tearDown(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        km._CLAUDE_SETTINGS = self._saved_settings
        self.td.cleanup()

    def write_settings(self, env, local=False):
        p = km._CLAUDE_SETTINGS.with_name("settings.local.json" if local else "settings.json")
        p.write_text(json.dumps({"env": env}))

    # ---- where the option is read from ----
    def test_nothing_defined_means_no_extra_model(self):
        self.assertIsNone(km._custom_model_choice())
        self.assertEqual(km._session_model_choices(), km.MODEL_CHOICES)

    def test_it_is_read_from_the_settings_file_the_kernel_does_not_inherit(self):
        self.write_settings({ENV_VALUE: ROUTED, ENV_NAME: ROUTED_NAME})
        self.assertEqual(km._custom_model_choice(), {"value": ROUTED, "label": ROUTED_NAME},
                         "the kernel has no such env of its own — the settings file is the source")

    def test_a_real_env_var_wins_over_the_file(self):
        self.write_settings({ENV_VALUE: "from-file", ENV_NAME: "From File"})
        os.environ[ENV_VALUE], os.environ[ENV_NAME] = ROUTED, ROUTED_NAME
        self.assertEqual(km._custom_model_choice()["value"], ROUTED,
                         "a kernel actually started with the var set should honour what a session would see")

    def test_local_settings_override_user_settings(self):
        self.write_settings({ENV_VALUE: "user-model", ENV_NAME: "User"})
        self.write_settings({ENV_VALUE: ROUTED, ENV_NAME: ROUTED_NAME}, local=True)
        self.assertEqual(km._custom_model_choice()["value"], ROUTED, "local overrides user, as the CLI merges them")

    def test_the_label_falls_back_to_the_id(self):
        self.write_settings({ENV_VALUE: ROUTED})
        self.assertEqual(km._custom_model_choice(), {"value": ROUTED, "label": ROUTED},
                         "no _NAME → show the id rather than a blank menu entry")

    def test_unreadable_settings_are_simply_no_option(self):
        km._CLAUDE_SETTINGS.write_text("{not json")
        self.assertIsNone(km._custom_model_choice(), "a malformed settings file must not take the kernel down")

    def test_a_value_shadowing_a_ladder_alias_is_dropped(self):
        self.write_settings({ENV_VALUE: "opus", ENV_NAME: "My Opus"})
        self.assertIsNone(km._custom_model_choice(), "never list the same value twice in one picker")

    # ---- who gets to see it ----
    def test_the_session_list_is_the_ladder_plus_the_extra(self):
        self.write_settings({ENV_VALUE: ROUTED, ENV_NAME: ROUTED_NAME})
        vals = [m["value"] for m in km._session_model_choices()]
        self.assertEqual(vals, [m["value"] for m in km.MODEL_CHOICES] + [ROUTED],
                         "appended, so the ladder's own order is untouched")

    def test_the_claude_ladder_itself_never_changes(self):
        self.write_settings({ENV_VALUE: ROUTED, ENV_NAME: ROUTED_NAME})
        km._session_model_choices()
        self.assertEqual([m["value"] for m in km.MODEL_CHOICES], ["fable", "opus", "sonnet", "haiku"],
                         "MODEL_CHOICES is the capability vocabulary — building the session list must not mutate it")

    def test_the_judges_stay_on_claude(self):
        self.write_settings({ENV_VALUE: ROUTED, ENV_NAME: ROUTED_NAME})
        self.assertNotIn(ROUTED, km._MODEL_VALUES,
                         "the judge/index tiers validate against this set and run across every session")

    def test_the_lane_colour_ramp_is_unshifted(self):
        # ranks derive from MODEL_CHOICES' ORDER; a fifth entry in that list would re-space every
        # existing model's colour, which is why the extra lives on a separate list
        self.write_settings({ENV_VALUE: ROUTED, ENV_NAME: ROUTED_NAME})
        self.assertEqual(dict(km._MODEL_RANK)["fable"], 1.0)
        self.assertEqual(dict(km._MODEL_RANK)["haiku"], 0.0)
        self.assertEqual(len(km._MODEL_RANK), 4)
        self.assertIsNone(km._model_color(ROUTED, ["#000000", "#ffffff"]),
                          "an off-ladder model takes the existing no-match path, it does not borrow a rank")

    # ---- the restore policy must not mistake it for a Claude model ----
    def test_the_safeguards_restore_leaves_an_off_ladder_model_alone(self):
        self.assertEqual(km._model_family_alias(ROUTED), "",
                         "a routed model belongs to no Claude family — the fallback restore must skip it")


if __name__ == "__main__":
    unittest.main()
