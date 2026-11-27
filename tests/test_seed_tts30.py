"""Seed-TTS 3.0 contract and blank-key example regression."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import nodes
from ComfyUI_Seedance.core import seed_tts30
from ComfyUI_Seedance.core.client import SeedanceAPIError


PROMPT = "Welcome to the morning report."


class SeedTTS30Tests(unittest.TestCase):
    def test_catalog_and_case_insensitive_voice_override(self):
        self.assertEqual(len(set(seed_tts30.VOICES)), 502)
        self.assertEqual(seed_tts30.VOICES[0], "sarah")
        by_short = seed_tts30.payload({"prompt": PROMPT, "voice": "SaRaH"}, True)
        self.assertEqual(by_short, {"model": "bytedance-seed/seed-tts-3-0", "prompt": PROMPT,
                                    "metadata": {"voice": "sarah", "format": "wav", "speed": 1.0}})
        body = seed_tts30.payload({"prompt": PROMPT, "voice": "sarah", "voice_id": "MULTI_MALE_RYAN_V3_URANUS_BIGTTS",
                                   "instructions": " Warm and clear. ", "speed": 1.25}, True)
        self.assertEqual(body["metadata"], {"voice": "multi_male_ryan_v3_uranus_bigtts",
                                             "instructions": "Warm and clear.", "format": "wav", "speed": 1.25})

    def test_documented_boundaries_checked_before_api(self):
        for speed in (0.5, 2.0):
            self.assertTrue(seed_tts30.payload({"prompt": "a" * 5000, "instructions": "b" * 1000, "speed": speed}, True))
        with patch.object(nodes, "submit_audio_task") as submit:
            for invalid in ({"prompt": ""}, {"prompt": "a" * 5001}, {"instructions": "a" * 1001},
                            {"speed": 0.49}, {"speed": 2.01}, {"speed": True}, {"speed": float("nan")},
                            {"voice": "not-a-voice"}, {"voice_id": "multi_male_sarah_v3_uranus_bigtts"}):
                with self.subTest(invalid=next(iter(invalid))), self.assertRaises(SeedanceAPIError):
                    nodes.SeedTTS30().execute(**{"prompt": PROMPT, **invalid})
            submit.assert_not_called()

    def test_node_preserves_download_contract_and_strips_comfy_seed(self):
        self.assertTrue(nodes.SeedTTS30.SEEDANCE_CACHE_ONLY_SEED)
        url = "https://example.test/sample.wav"
        audio = {"waveform": torch.ones(1, 1, 32), "sample_rate": 24000}
        done = {"data": {"status": "SUCCESS", "result_url": url}}
        with patch.object(nodes, "get_config", return_value={}), \
                patch.object(nodes, "submit_audio_task", return_value="offline") as submit, \
                patch.object(nodes, "poll_audio_task", return_value=done), \
                patch.object(nodes, "download_audio", return_value=(audio, "sample.wav")) as download:
            result = nodes.SeedTTS30().execute(prompt=PROMPT, seed=25)["result"]
        self.assertEqual(submit.call_args.args[0], seed_tts30.payload({"prompt": PROMPT}, True))
        download.assert_called_once_with(url, output_format="wav", sample_rate=24000, logger_prefix="Seed_TTS_3_0")
        self.assertIs(result[0], audio)
        self.assertEqual(result[1:4], (url, "sample.wav", "offline"))
        self.assertEqual(json.loads(result[4]), done)

    def test_skip_error_is_opt_in_and_produces_silence(self):
        with patch.object(nodes, "get_config", return_value={}), \
                patch.object(nodes, "submit_audio_task", side_effect=SeedanceAPIError("offline failure")):
            self.assertFalse(nodes.SeedTTS30.INPUT_TYPES()["optional"]["skip_error"][1]["default"])
            with self.assertRaises(SeedanceAPIError):
                nodes.SeedTTS30().execute(prompt=PROMPT)
            result = nodes.SeedTTS30().execute(prompt=PROMPT, skip_error=True)["result"]
        self.assertEqual(result[0]["sample_rate"], 24000)
        self.assertEqual(result[0]["waveform"].count_nonzero().item(), 0)
        self.assertEqual(result[1:4], ("", "", ""))

    def test_blank_key_example_connects_config_and_audio_preview(self):
        example = json.loads((ROOT / "examples" / "seed-tts-3-0.json").read_text(encoding="utf-8"))
        config, generate, preview = example["nodes"]
        self.assertEqual((config["type"], generate["type"], preview["type"]), ("Seedance_Config", "Seed_TTS_3_0", "PreviewAudio"))
        self.assertEqual(config["widgets_values"][1], "")
        self.assertEqual(generate["widgets_values"][-2:], [0, "fixed"])
        self.assertEqual(example["links"], [[1, 1, 0, 2, 0, "SEEDANCE_CONFIG"], [2, 2, 0, 3, 0, "AUDIO"]])
