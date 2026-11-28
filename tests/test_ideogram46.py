"""Tests for Ideogram routing, mask/ref limits, and shipped examples."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import NODE_CLASS_MAPPINGS, nodes
from ComfyUI_Seedance.core import ideogram46
from ComfyUI_Seedance.core.client import SeedanceAPIError


PROMPT = "Paint a blue circle."
MASK = "https://example.test/mask.png"


class IdeogramTests(unittest.TestCase):
    def test_each_registered_schema_has_its_own_controls(self):
        for wrapper in (False, True):
            for key in ("Ideogram_V4_6", "Ideogram_V4_6_Edit"):
                with self.subTest(key=key, wrapper=wrapper):
                    actual_key = f"SeedanceConcurrent_{key}_Submit" if wrapper else key
                    cls = NODE_CLASS_MAPPINGS[actual_key]
                    schema = cls.INPUT_TYPES()
                    edit = key.endswith("_Edit")
                    self.assertEqual("image1" in schema["required"], edit)
                    self.assertEqual("image5" in schema["optional"], edit)
                    self.assertNotIn("image6", schema["optional"])
                    self.assertEqual("mask_url" in schema["required"], edit)
                    self.assertEqual("background" in schema["required"], not edit)
                    self.assertTrue(schema["optional"]["seed"][1]["control_after_generate"])

    def test_text_defaults_and_limits(self):
        self.assertEqual(ideogram46.plan({"prompt": f" {PROMPT} ", "seed": 17}), {
            "model": "ideogram-v4.6", "prompt": PROMPT, "resolution": "1k", "quality": "medium",
            "aspect_ratio": "1:1", "background": "opaque", "enable_prompt_expansion": False,
        })
        self.assertEqual(ideogram46.plan({"prompt": "x" * 10000, "resolution": "2k",
                                          "quality": "very_low"})["resolution"], "2k")
        for fields in ({"prompt": " "}, {"prompt": "x" * 10001}, {"aspect_ratio": "21:9"},
                       {"quality": "very_low", "resolution": "4k"}, {"enable_prompt_expansion": "false"},
                       {"image1": object()}):
            with self.subTest(fields=tuple(fields)), self.assertRaises(SeedanceAPIError):
                ideogram46.plan({"prompt": PROMPT, **fields})

    def test_edit_ratios_and_mask_limits(self):
        kwargs = {"prompt": PROMPT, "image1": object()}
        self.assertNotIn("aspect_ratio", ideogram46.plan(kwargs, edit=True))
        self.assertEqual(ideogram46.plan({**kwargs, "aspect_ratio": "3:4"}, edit=True)["aspect_ratio"], "3:4")
        self.assertNotIn("aspect_ratio", ideogram46.plan({**kwargs, "aspect_ratio": "3:4",
                                                         "edit_precision": "high"}, edit=True))
        masked = {**kwargs, **{f"image{i}": object() for i in range(2, 5)},
                  "mask_url": MASK, "aspect_ratio": "3:4"}
        result = ideogram46.plan(masked, edit=True)
        self.assertEqual(result["mask_url"], MASK)
        self.assertNotIn("aspect_ratio", result)
        for fields in ({**masked, "image5": object()}, {"image6": object()}, {"image1": None, "image2": object()},
                       {"mask_url": "file:///tmp/mask.png"}):
            with self.subTest(fields=tuple(fields)), self.assertRaises(SeedanceAPIError):
                ideogram46.plan({**kwargs, **fields}, edit=True)

    def test_five_edit_inputs_uploaded_in_order_and_bad_batch_preflight(self):
        source = torch.ones(1, 8, 8, 3)
        mask = torch.zeros(1, 8, 8)
        kwargs = {f"image{i}": source for i in (4, 5, 2, 1, 3)}
        final = {"data": {"status": "SUCCESS", "result_url": "https://example.test/out.png"}}
        urls = [f"https://example.test/ref{i}.png" for i in range(1, 6)]
        with patch.object(nodes, "get_config", return_value={}), \
             patch.object(nodes, "upload_media", side_effect=urls) as upload, \
             patch.object(nodes, "submit_image_task", return_value="mock") as submit, \
             patch.object(nodes, "poll_image_task", return_value=final), \
             patch.object(nodes, "download_image_with_mask", return_value=(source, mask)):
            result = nodes.Ideogram46Edit().execute(prompt=PROMPT, **kwargs)["result"]
            self.assertIs(result[4], mask)
            self.assertEqual(submit.call_args.args[0]["images"], urls)
            self.assertEqual([v.args[1] for v in upload.call_args_list],
                             [f"ideogram_reference_{i}.png" for i in range(1, 6)])
            upload.reset_mock()
            submit.reset_mock()
            with self.assertRaises(SeedanceAPIError):
                nodes.Ideogram46Edit().execute(prompt=PROMPT, image1=source.repeat(2, 1, 1, 1))
            with self.assertRaises(SeedanceAPIError):
                nodes.Ideogram46Edit().execute(prompt=PROMPT, mask_url=MASK, **kwargs)
            upload.assert_not_called()
            submit.assert_not_called()

    def test_skip_error_retains_all_output_slots(self):
        result = nodes.Ideogram46().execute(prompt="", skip_error=True)["result"]
        self.assertEqual(len(result), len(nodes.Ideogram46.RETURN_TYPES))
        self.assertEqual(result[4].shape, result[0].shape[:3])
        self.assertTrue(json.loads(result[3])["error"])

    def test_examples_are_blank_and_wire_mask_or_base_image(self):
        for edit in (False, True):
            name = "ideogram-v4.6" + ("-edit" if edit else "")
            doc = json.loads((ROOT / "examples" / (name + ".json")).read_text(encoding="utf-8"))
            config, model = doc["nodes"][:2]
            self.assertEqual(config["widgets_values"], ["https://api.seedance.nz", ""])
            self.assertEqual(model["type"], "Ideogram_V4_6" + ("_Edit" if edit else ""))
            rest = {n["type"]: n for n in doc["nodes"][2:]}
            wires = [link[1:] for link in doc["links"]]
            if edit:
                self.assertIn([rest["LoadImage"]["id"], 0, 2, 0, "IMAGE"], wires)
            else:
                self.assertIn("transparent", model["widgets_values"])
                self.assertIn([2, 4, rest["JoinImageWithAlpha"]["id"], 1, "MASK"], wires)
                self.assertIn([rest["JoinImageWithAlpha"]["id"], 0, rest["SaveImage"]["id"], 0, "IMAGE"], wires)
