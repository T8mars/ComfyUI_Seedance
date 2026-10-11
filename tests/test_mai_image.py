import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import concurrent_nodes, nodes
from ComfyUI_Seedance.core.client import SeedanceAPIError

IMAGE = torch.zeros((1, 16, 16, 3))
CONFIG = {"base_url": "https://api.seedance.nz", "api_key": "sk-test"}


class MAIImageTests(unittest.TestCase):
    def args(self, **changes):
        return {"model": "mai-image-2-6", "prompt": "A red ceramic teapot",
                "resolution": "1k", "size": "1:1", **changes}

    def tearDown(self):
        concurrent_nodes.shutdown_concurrent_pools(wait=True)

    def test_registration_and_cache_contract_preserve_existing_nodes(self):
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["MAI_Image_2_6"], nodes.MAIImage26)
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Zhenzhen_Image_NB_2_1"], nodes.ZhenzhenImageNB21)
        inputs = nodes.MAIImage26.INPUT_TYPES()
        self.assertEqual(inputs["required"]["model"][0], ["mai-image-2-6", "mai-image-2-6-flash"])
        self.assertEqual(inputs["required"]["resolution"][0], ["1k", "2k"])
        self.assertEqual(inputs["required"]["size"][1]["default"], "1:1")
        self.assertEqual(list(inputs["optional"]), [f"image{i}" for i in range(1, 6)]
                         + ["api_config", "skip_error", "seed"])
        self.assertTrue(inputs["optional"]["seed"][1]["control_after_generate"])
        self.assertFalse(inputs["optional"]["skip_error"][1]["default"])
        self.assertTrue(nodes.MAIImage26.SEEDANCE_CACHE_ONLY_SEED)
        self.assertFalse(hasattr(nodes.MAIImage26, "IS_CHANGED"))

    def test_text_payload_exact_whitelist_and_model_variants(self):
        for model in nodes.MAI_IMAGE_MODELS:
            with self.subTest(model=model):
                result = nodes.MAIImage26().build_payload(
                    self.args(model=model, seed=42, n=4, output_format="jpeg", quality="high", mask="unused"), [])
                self.assertEqual(result, {"model": model, "prompt": "A red ceramic teapot", "n": 1,
                    "web_grounding": False, "size": "1:1", "resolution": "1k", "auto_aspect_ratio": False})

    def test_ratio_presets_and_custom_bounds(self):
        for ratio in nodes.MAI_IMAGE_SIZES[:-2] + ["5:3", "100:25", "25:100"]:
            self.assertEqual(nodes.MAIImage26().build_payload(self.args(size="custom_ratio", custom_ratio=ratio), [])["size"], ratio)
        for ratio in ("0:1", "1:0", "5:1", "1:5", "1.5:1", "-1:2", "١:١", "16:9:1", "", "text"):
            with self.subTest(ratio=ratio), self.assertRaises(SeedanceAPIError):
                nodes.MAIImage26().build_payload(self.args(size="custom_ratio", custom_ratio=ratio), [])

    def test_pixels_round_down_and_override_unused_controls(self):
        payload = nodes.MAIImage26().build_payload(
            self.args(size="custom_pixels", width=1537, height=1025, resolution="unused"), [])
        self.assertEqual((payload["width"], payload["height"]), (1536, 1024))
        self.assertNotIn("resolution", payload)
        self.assertNotIn("size", payload)
        self.assertEqual(nodes.MAIImage26().build_payload(self.args(size="custom_pixels", width=768, height=3072), [])["height"], 3072)
        for width, height in ((767, 1024), (1024, 767), (1537, 1536), (3073, 768), (True, 768), (768.5, 768)):
            with self.subTest(width=width, height=height), self.assertRaises(SeedanceAPIError):
                nodes.MAIImage26().build_payload(self.args(size="custom_pixels", width=width, height=height), [])

    def test_auto_aspect_overrides_inactive_ratio_and_pixels(self):
        payload = nodes.MAIImage26().build_payload(
            self.args(size="custom_pixels", width=0, height=0, resolution="2K", auto_aspect_ratio=True), [])
        self.assertEqual((payload["size"], payload["resolution"], payload["auto_aspect_ratio"]), ("auto", "2k", True))
        self.assertNotIn("width", payload)
        self.assertNotIn("height", payload)

    def test_reference_payload_omits_all_sizing_and_forbidden_fields(self):
        refs = [f"https://cdn.test/ref{i}.png" for i in range(5)]
        for model in nodes.MAI_IMAGE_MODELS:
            payload = nodes.MAIImage26().build_payload(self.args(
                model=model, resolution="invalid", size="custom_pixels", width=0, height=0,
                auto_aspect_ratio=True, web_grounding=True, seed=99), refs)
            self.assertEqual(payload, {"model": model, "prompt": "A red ceramic teapot",
                                      "n": 1, "web_grounding": True, "images": refs})
        with self.assertRaises(SeedanceAPIError):
            nodes.MAIImage26().build_payload(self.args(), refs + ["https://cdn.test/extra.png"])

    def test_validation_defers_linked_prompt_and_does_not_invent_character_limits(self):
        self.assertIs(nodes.MAIImage26.VALIDATE_INPUTS(prompt=None), True)
        self.assertIs(nodes.MAIImage26.VALIDATE_INPUTS(prompt="x", strict=True), True)
        self.assertIs(nodes.MAIImage26.VALIDATE_INPUTS(prompt="x" * 40000, strict=True), True)
        for changes in ({"model": "mai-image-other"}, {"prompt": "  "}, {"resolution": "4k"}):
            self.assertIsNot(nodes.MAIImage26.VALIDATE_INPUTS(**self.args(**changes), strict=True), True)

    def test_execute_uploads_stable_slots_and_downloads_decoded_image(self):
        final = {"data": {"status": "SUCCESS", "result_url": "https://cdn.test/result.png"}}
        with patch.object(nodes, "get_config", return_value=CONFIG), \
             patch.object(nodes, "upload_media", side_effect=["ref1", "ref5"]) as upload, \
             patch.object(nodes, "submit_image_task", return_value="test-task") as submit, \
             patch.object(nodes, "poll_image_task", return_value=final) as poll, \
             patch.object(nodes, "download_image", return_value=IMAGE) as download:
            result = nodes.MAIImage26().execute(**self.args(image1=IMAGE, image5=IMAGE, seed=123))
        self.assertEqual([call.args[1] for call in upload.call_args_list], ["mai_reference_1.png", "mai_reference_5.png"])
        self.assertEqual(submit.call_args.args[0]["images"], ["ref1", "ref5"])
        self.assertEqual(set(submit.call_args.args[0]), {"model", "prompt", "n", "web_grounding", "images"})
        poll.assert_called_once()
        download.assert_called_once_with("https://cdn.test/result.png", logger_prefix="MAI_Image_2_6")
        self.assertIs(result["result"][0], IMAGE)
        self.assertEqual(len(result["result"]), 4)

    def test_text_path_never_uploads(self):
        with patch.object(nodes, "get_config", return_value=CONFIG), \
             patch.object(nodes, "upload_media") as upload, \
             patch.object(nodes, "submit_image_task", return_value="test-task"), \
             patch.object(nodes, "poll_image_task", return_value={"data": {"result_url": "url"}}), \
             patch.object(nodes, "download_image", return_value=IMAGE):
            nodes.MAIImage26().execute(**self.args())
        upload.assert_not_called()

    def test_invalid_runtime_inputs_fail_before_upload_or_submit(self):
        with patch.object(nodes, "upload_media") as upload, patch.object(nodes, "submit_image_task") as submit:
            for arguments in (self.args(prompt="", image1=IMAGE), self.args(size="custom_ratio", custom_ratio="8:1"),
                              self.args(image1=IMAGE, image5=IMAGE.repeat(2, 1, 1, 1))):
                with self.assertRaises(SeedanceAPIError):
                    nodes.MAIImage26().execute(**arguments)
        upload.assert_not_called()
        submit.assert_not_called()

    def test_skip_error_and_concurrent_failure_isolation(self):
        wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS["SeedanceConcurrent_MAI_Image_2_6_Submit"]
        self.assertEqual(wrapper.INPUT_TYPES(), nodes.MAIImage26.INPUT_TYPES())
        self.assertFalse(hasattr(wrapper, "VALIDATE_INPUTS"))
        self.assertFalse(hasattr(wrapper, "IS_CHANGED"))
        self.assertIs(nodes.MAIImage26().execute(**self.args(prompt=""), skip_error=True)["result"][0].ndim, 4)
        with patch.object(nodes.MAIImage26, "_execute_inner", return_value={"result": (IMAGE, "", "", "{}")}):
            valid = wrapper().submit(**self.args())[0]
            failed = wrapper().submit(**self.args(prompt=""), skip_error=True)[0]
            result = concurrent_nodes.SeedanceConcurrentImageAwait().wait_all(future_1=valid, future_2=failed)
        self.assertIs(result[0], IMAGE)
        self.assertEqual(result[1].shape, (1, 512, 512, 3))
        self.assertFalse(valid.cancel_event.is_set())
        self.assertEqual(json.loads(result[-1])["failed"], 1)

    def test_six_examples_have_all_model_modes_valid_links_and_blank_keys(self):
        paths = list((ROOT / "examples").glob("mai-image-2-6*.json"))
        self.assertEqual(len(paths), 6)
        combinations = set()
        for path in paths:
            workflow = json.loads(path.read_text(encoding="utf-8"))
            by_id = {node["id"]: node for node in workflow["nodes"]}
            generator = next(node for node in by_id.values() if node["type"] == "MAI_Image_2_6")
            config = next(node for node in by_id.values() if node["type"] == "Seedance_Config")
            count = sum(node["type"] == "LoadImage" for node in by_id.values())
            combinations.add((generator["widgets_values"][0], count))
            self.assertEqual(config["widgets_values"][1], "")
            self.assertEqual(generator["widgets_values"][-3:], [False, 0, "fixed"])
            self.assertEqual(len(generator["widgets_values"]), 12)
            self.assertEqual([item["name"] for item in generator["inputs"]], [f"image{i}" for i in range(1, 6)] + ["api_config"])
            for link_id, origin, origin_slot, target, target_slot, kind in workflow["links"]:
                self.assertEqual(by_id[origin]["outputs"][origin_slot]["type"], kind)
                self.assertEqual(by_id[target]["inputs"][target_slot]["type"], kind)
                self.assertEqual(by_id[target]["inputs"][target_slot]["link"], link_id)
        self.assertEqual(combinations, {(model, count) for model in nodes.MAI_IMAGE_MODELS for count in range(3)})

    def test_frontend_modes_use_shared_helper_and_both_node_aliases(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js unavailable")
        result = subprocess.run([node, str(ROOT / "tests" / "mai_image_ui.mjs")], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
