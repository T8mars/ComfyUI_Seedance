"""Offline Anima API, registration and workflow regression tests."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

import ComfyUI_Seedance as plugin
from ComfyUI_Seedance import nodes
from ComfyUI_Seedance.core.client import SeedanceAPIError


KEY = "Anima_V1_T2I"
MODEL = "Anima-v1-t2i"
PROMPT = "A red bicycle in front of a blue bakery."
RATIOS = ["1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"]


class AnimaV1Tests(unittest.TestCase):
    def test_schema_only_exposes_documented_controls_and_cache_seed(self):
        cls = nodes.AnimaV1T2I
        schema = cls.INPUT_TYPES()
        self.assertEqual(set(schema["required"]), {"prompt", "ratio"})
        self.assertEqual(set(schema["optional"]), {"api_config", "skip_error", "seed"})
        self.assertEqual(schema["required"]["ratio"], (RATIOS, {"default": "1:1"}))
        self.assertIs(schema["optional"]["skip_error"][1]["default"], False)
        self.assertTrue(cls.SEEDANCE_CACHE_ONLY_SEED)
        self.assertEqual(cls.RETURN_TYPES, ("IMAGE", "STRING", "STRING", "STRING"))
        wrapper = plugin.NODE_CLASS_MAPPINGS[f"SeedanceConcurrent_{KEY}_Submit"]
        self.assertEqual(wrapper.INPUT_TYPES(), schema)
        self.assertFalse(hasattr(wrapper, "VALIDATE_INPUTS"))

    def test_payload_matches_contract_and_cache_seed_never_leaves_node(self):
        tensor = torch.zeros(1, 8, 12, 3)
        url = "https://example.test/anima.png"
        response = {"data": {"status": "SUCCESS", "result_url": url}}
        with patch.object(nodes, "get_config", return_value={}), \
                patch.object(nodes, "submit_image_task", return_value="mock-id") as submit, \
                patch.object(nodes, "poll_image_task", return_value=response) as poll, \
                patch.object(nodes, "download_image", return_value=tensor) as download, \
                patch.object(nodes, "upload_media") as upload:
            output = nodes.AnimaV1T2I().execute(prompt=f" {PROMPT} ", ratio="3:2", seed=19)
        self.assertEqual(submit.call_args.args[0], {"model": MODEL, "prompt": PROMPT, "metadata": {"ratio": "3:2"}})
        self.assertEqual(poll.call_args.args[0], "mock-id")
        self.assertEqual(download.call_args.args[0], url)
        upload.assert_not_called()
        self.assertIs(output["result"][0], tensor)
        self.assertEqual(output["result"][1:3], (url, "mock-id"))
        self.assertEqual(json.loads(output["result"][3]), response)

    def test_validation_prevents_requests_with_missing_prompt_ratio_or_reference(self):
        for ratio in RATIOS:
            self.assertIs(nodes.AnimaV1T2I.VALIDATE_INPUTS(prompt=PROMPT, ratio=ratio, strict=True), True)
        with patch.object(nodes, "submit_image_task") as submit, patch.object(nodes, "upload_media") as upload:
            for changes in ({"prompt": " "}, {"ratio": "auto"}, {"image1": object()}):
                with self.subTest(changes=changes), self.assertRaises(SeedanceAPIError):
                    nodes.AnimaV1T2I().execute(**{"prompt": PROMPT, **changes})
            submit.assert_not_called()
            upload.assert_not_called()

    def test_example_keeps_key_blank_and_connects_save_image(self):
        name = "Anima-v1-t2i\u6587\u751f\u56fe.json"
        graph = json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))
        config, generation, save = graph["nodes"]
        self.assertEqual((config["type"], generation["type"], save["type"]), ("Seedance_Config", KEY, "SaveImage"))
        self.assertEqual(config["widgets_values"][1], "")
        self.assertEqual(generation["widgets_values"][1:], ["1:1", False, 0, "fixed"])
        self.assertEqual(graph["links"], [[1, 1, 0, 2, 0, "SEEDANCE_CONFIG"], [2, 2, 0, 3, 0, "IMAGE"]])
