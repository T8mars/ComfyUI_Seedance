import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import concurrent_nodes, nodes
from ComfyUI_Seedance.core.client import SeedanceAPIError

IMAGE = torch.zeros((1, 16, 16, 3))
CONFIG = {"base_url": "https://api.seedance.nz", "api_key": "sk-test"}


class MossImageTests(unittest.TestCase):
    def args(self, **changes):
        return {"prompt": "A red ceramic teapot", "ratio": "9:16", **changes}

    def tearDown(self):
        concurrent_nodes.shutdown_concurrent_pools(wait=True)

    def test_independent_registration_default_ratio_and_existing_nodes_unchanged(self):
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Moss_Image"], nodes.MossImage)
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["MAI_Image_2_6"], nodes.MAIImage26)
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Zhenzhen_Image_NB_Lowprice"], nodes.ZhenzhenImageNBLowprice)
        inputs = nodes.MossImage.INPUT_TYPES()
        self.assertEqual(list(inputs["required"]), ["prompt", "ratio"])
        self.assertEqual(inputs["required"]["ratio"], (nodes.MOSS_IMAGE_RATIOS, {"default": "9:16"}))
        self.assertEqual(list(inputs["optional"]), ["image1", "api_config", "skip_error", "seed"])
        self.assertFalse(inputs["optional"]["skip_error"][1]["default"])
        self.assertTrue(inputs["optional"]["seed"][1]["control_after_generate"])
        self.assertEqual(nodes.MossImage.RETURN_TYPES, ("IMAGE", "STRING", "STRING", "STRING"))

    def test_payload_only_sends_documented_fields(self):
        kwargs = self.args(prompt="  A teapot  ", model="not-used", n=5, seed=123, resolution="4k",
                           width=1000, height=1000, size="1:1", output_format="jpeg", metadata={"seed": 7})
        expected = {"model": "moss-image", "prompt": "A teapot", "metadata": {"ratio": "9:16"}}
        node = nodes.MossImage()
        self.assertEqual(node.build_payload(kwargs, []), expected)
        refs = ["https://reference.test/teapot.png"]
        self.assertEqual(node.build_payload(kwargs, refs), {**expected, "images": refs})
        self.assertEqual(node.build_payload({"prompt": "x"}, []), {"model": "moss-image", "prompt": "x", "metadata": {"ratio": "9:16"}})

    def test_all_eight_documented_ratios_and_invalid_values(self):
        self.assertEqual(nodes.MOSS_IMAGE_RATIOS, ["1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"])
        for ratio in nodes.MOSS_IMAGE_RATIOS:
            self.assertEqual(nodes.MossImage().build_payload(self.args(ratio=ratio), [])["metadata"], {"ratio": ratio})
        for ratio in ("auto", "adaptive", "4:1", "custom", "", "9:21"):
            self.assertIsNot(nodes.MossImage.VALIDATE_INPUTS(**self.args(ratio=ratio)), True)

    def test_prompt_validation_defers_links_and_does_not_invent_character_limits(self):
        self.assertIs(nodes.MossImage.VALIDATE_INPUTS(prompt=None), True)
        self.assertIs(nodes.MossImage.VALIDATE_INPUTS(prompt="", strict=False), True)
        for prompt in ("x", "汉字", "x" * 30000):
            self.assertIs(nodes.MossImage.VALIDATE_INPUTS(prompt=prompt, strict=True), True)
        for prompt in (None, "", " \n\t "):
            self.assertIsNot(nodes.MossImage.VALIDATE_INPUTS(prompt=prompt, strict=True), True)

    def test_reference_limit_rejects_multiple_urls_instead_of_truncating(self):
        with self.assertRaisesRegex(SeedanceAPIError, "at most one"):
            nodes.MossImage().build_payload(self.args(), ["ref1", "ref2"])

    def test_invalid_tensor_is_rejected_before_any_network_or_upload(self):
        invalid = [IMAGE.repeat(2, 1, 1, 1), torch.zeros((16, 16, 3)), torch.zeros((1, 0, 16, 3)),
                   torch.zeros((1, 16, 16, 1)), torch.full((1, 2, 2, 3), float("nan")), "not-an-image"]
        with patch.object(nodes, "get_config") as config, patch.object(nodes, "upload_media") as upload, \
             patch.object(nodes, "submit_image_task") as submit:
            for reference in invalid:
                with self.subTest(reference_type=type(reference).__name__), self.assertRaises(SeedanceAPIError):
                    nodes.MossImage().execute(**self.args(image1=reference))
            with self.assertRaises(SeedanceAPIError):
                nodes.MossImage().execute(**self.args(prompt=""))
        config.assert_not_called()
        upload.assert_not_called()
        submit.assert_not_called()
        self.assertIs(nodes.MossImage.VALIDATE_INPUTS(**self.args(image1=torch.zeros((1, 2, 2, 4))), strict=True), True)

    def test_text_execution_never_uploads_and_downloads_result(self):
        with patch.object(nodes, "get_config", return_value=CONFIG), \
             patch.object(nodes, "upload_media") as upload, \
             patch.object(nodes, "submit_image_task", return_value="test-task") as submit, \
             patch.object(nodes, "poll_image_task", return_value={"data": {"status": "SUCCESS", "result_url": "https://result.test/moss.png"}}) as poll, \
             patch.object(nodes, "download_image", return_value=IMAGE) as download:
            result = nodes.MossImage().execute(prompt="A teapot", seed=42)
        upload.assert_not_called()
        self.assertEqual(submit.call_args.args[0], {"model": "moss-image", "prompt": "A teapot", "metadata": {"ratio": "9:16"}})
        poll.assert_called_once()
        download.assert_called_once_with("https://result.test/moss.png", logger_prefix="Moss_Image")
        self.assertEqual(result["result"][1:3], ("https://result.test/moss.png", "test-task"))
        self.assertIs(result["result"][0], IMAGE)

    def test_reference_execution_uploads_real_png_and_reports_progress(self):
        pbar = Mock()
        final = {"data": {"data": {"content": {"image_url": "https://result.test/edit.png"}}}}

        def poll_task(*args, **kwargs):
            kwargs["on_progress"](40)
            return final

        with patch.object(nodes, "get_config", return_value=CONFIG), \
             patch.object(nodes, "_make_progress_bar", return_value=pbar), \
             patch.object(nodes, "upload_media", return_value="https://reference.test/moss.png") as upload, \
             patch.object(nodes, "submit_image_task", return_value="test-task") as submit, \
             patch.object(nodes, "poll_image_task", side_effect=poll_task), \
             patch.object(nodes, "download_image", return_value=IMAGE):
            result = nodes.MossImage().execute(**self.args(image1=IMAGE), seed=999)
        self.assertTrue(upload.call_args.args[0].startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(upload.call_args.args[1:3], ("moss_reference.png", "image/png"))
        self.assertEqual(submit.call_args.args[0]["images"], ["https://reference.test/moss.png"])
        pbar.update_absolute.assert_any_call(50, 100)
        pbar.update_absolute.assert_called_with(100, 100)
        self.assertIs(result["result"][0], IMAGE)

    def test_documented_array_result_fallback_and_primary_url_precedence(self):
        for result_url, expected in ((None, "https://result.test/list.png"), ("https://result.test/primary.png", "https://result.test/primary.png")):
            final = {"data": {"result_url": result_url, "data": {"content": {"image_urls": ["https://result.test/list.png"]}}}}
            with patch.object(nodes, "get_config", return_value=CONFIG), \
                 patch.object(nodes, "submit_image_task", return_value="test-task"), \
                 patch.object(nodes, "poll_image_task", return_value=final), \
                 patch.object(nodes, "download_image", return_value=IMAGE) as download:
                result = nodes.MossImage().execute(**self.args())
            self.assertEqual(result["result"][1], expected)
            download.assert_called_once_with(expected, logger_prefix="Moss_Image")

    def test_standard_seed_is_cache_only_and_skip_error_keeps_output_types(self):
        self.assertTrue(nodes.MossImage.SEEDANCE_CACHE_ONLY_SEED)
        self.assertFalse(hasattr(nodes.MossImage, "IS_CHANGED"))
        with patch.object(nodes.MossImage, "_execute_inner", return_value={"result": (IMAGE, "", "", "{}")}) as execute:
            nodes.MossImage().execute(**self.args(seed=7))
        self.assertNotIn("seed", execute.call_args.kwargs)
        result = nodes.MossImage().execute(**self.args(prompt=""), skip_error=True)
        self.assertEqual(result["result"][0].shape, (1, 512, 512, 3))
        self.assertEqual(result["result"][1:3], ("", ""))
        with self.assertRaises(SeedanceAPIError):
            nodes.MossImage().execute(**self.args(prompt=""))

    def test_concurrent_wrapper_contract_and_failed_slot_does_not_cancel_others(self):
        wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS["SeedanceConcurrent_Moss_Image_Submit"]
        self.assertEqual(wrapper.INPUT_TYPES(), nodes.MossImage.INPUT_TYPES())
        self.assertFalse(hasattr(wrapper, "VALIDATE_INPUTS"))
        self.assertFalse(hasattr(wrapper, "IS_CHANGED"))
        with patch.object(nodes.MossImage, "_execute_inner", return_value={"result": (IMAGE, "", "", "{}")}):
            good = wrapper().submit(**self.args())[0]
            bad = wrapper().submit(**self.args(prompt=""), skip_error=True)[0]
            result = concurrent_nodes.SeedanceConcurrentImageAwait().wait_all(future_1=good, future_2=bad)
        self.assertIs(result[0], IMAGE)
        self.assertEqual(result[1].shape, (1, 512, 512, 3))
        self.assertFalse(good.cancel_event.is_set())
        self.assertEqual(json.loads(result[-1])["failed"], 1)

    def test_two_workflows_keep_blank_keys_widgets_and_links_aligned(self):
        paths = list((ROOT / "examples").glob("moss-image*.json"))
        self.assertEqual(len(paths), 2)
        for path in paths:
            workflow = json.loads(path.read_text(encoding="utf-8"))
            by_id = {node["id"]: node for node in workflow["nodes"]}
            config = next(node for node in by_id.values() if node["type"] == "Seedance_Config")
            generator = next(node for node in by_id.values() if node["type"] == "Moss_Image")
            self.assertEqual(config["widgets_values"][1], "")
            self.assertEqual(generator["widgets_values"][1:], ["9:16", False, 0, "fixed"])
            self.assertEqual([item["name"] for item in generator["inputs"]], ["image1", "api_config"])
            for link_id, origin, origin_slot, target, target_slot, kind in workflow["links"]:
                self.assertEqual(by_id[origin]["outputs"][origin_slot]["type"], kind)
                self.assertIn(link_id, by_id[origin]["outputs"][origin_slot]["links"])
                self.assertEqual(by_id[target]["inputs"][target_slot]["type"], kind)
                self.assertEqual(by_id[target]["inputs"][target_slot]["link"], link_id)
            has_reference = "图像编辑" in path.name
            self.assertEqual(sum(node["type"] == "LoadImage" for node in by_id.values()), int(has_reference))
            self.assertTrue(any(node["type"] == "SaveImage" for node in by_id.values()))


if __name__ == "__main__":
    unittest.main()
