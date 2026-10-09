import json
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


class NB21Tests(unittest.TestCase):
    def arguments(self, **changes):
        return {"prompt": "A red ceramic teapot", "resolution": "1k", "size": "1:1", **changes}

    def test_independent_node_preserves_legacy_nb_and_standard_controls(self):
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Zhenzhen_Image_NB_2_1"], nodes.ZhenzhenImageNB21)
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Zhenzhen_Image_NB"], nodes.ZhenzhenImageNB)
        self.assertNotIn(nodes.ZHENZHEN_IMAGE_NB_21_MODEL, nodes.ZHENZHEN_IMAGE_NB_MODELS)
        inputs = nodes.ZhenzhenImageNB21.INPUT_TYPES()
        self.assertEqual(inputs["required"]["resolution"][0], ["1k", "2k", "4k"])
        self.assertEqual(inputs["required"]["size"][0],
                         ["auto", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"])
        self.assertNotIn("n", inputs["required"])
        self.assertNotIn("output_format", inputs["required"])
        self.assertIs(inputs["optional"]["skip_error"][1]["default"], False)
        self.assertIs(inputs["optional"]["seed"][1]["control_after_generate"], True)
        self.assertTrue(nodes.ZhenzhenImageNB21.SEEDANCE_CACHE_ONLY_SEED)
        wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
            "SeedanceConcurrent_Zhenzhen_Image_NB_2_1_Submit"]
        self.assertEqual(wrapper.INPUT_TYPES(), inputs)
        self.assertFalse(hasattr(wrapper, "VALIDATE_INPUTS"))

    def test_payload_whitelist_for_text_and_edit(self):
        node = nodes.ZhenzhenImageNB21()
        kwargs = self.arguments(prompt="  A red ceramic teapot  ", seed=123,
                                output_format="png", metadata={"output_format": "jpeg"}, n=4)
        expected = {"model": "zhenzhen-image-nb-2.1", "prompt": "A red ceramic teapot",
                    "n": 1, "size": "1:1", "metadata": {"resolution": "1k"}}
        self.assertEqual(node.build_payload(kwargs, []), expected)
        expected["images"] = ["https://cdn.test/reference.png"]
        self.assertEqual(node.build_payload(kwargs, expected["images"]), expected)

    def test_prompt_bounds_and_linked_text_preflight(self):
        self.assertIs(nodes.ZhenzhenImageNB21.VALIDATE_INPUTS(prompt=None), True)
        for length in (5, 5000):
            self.assertIs(nodes.ZhenzhenImageNB21.VALIDATE_INPUTS(prompt="x" * length, strict=True), True)
        for length in (0, 4, 5001):
            self.assertIsNot(nodes.ZhenzhenImageNB21.VALIDATE_INPUTS(prompt="x" * length, strict=True), True)
        for changes in ({"resolution": "0.5k"}, {"size": "1:8"}, {"size": "custom"}):
            self.assertIsNot(nodes.ZhenzhenImageNB21.VALIDATE_INPUTS(**self.arguments(**changes)), True)

    def test_reference_limit_is_not_silently_truncated(self):
        node = nodes.ZhenzhenImageNB21()
        references = [f"https://cdn.test/ref{i}.png" for i in range(14)]
        self.assertEqual(node.build_payload(self.arguments(), references)["images"], references)
        with self.assertRaisesRegex(SeedanceAPIError, "14"):
            node.build_payload(self.arguments(), references + ["https://cdn.test/extra.png"])

    def test_execute_uploads_ordered_images_and_downloads_decoded_result(self):
        final = {"data": {"status": "SUCCESS", "result_url": "https://cdn.test/result.png"}}
        with patch.object(nodes, "get_config", return_value=CONFIG), \
             patch.object(nodes, "upload_media", side_effect=["ref1", "ref14"]) as upload, \
             patch.object(nodes, "submit_image_task", return_value="test-task") as submit, \
             patch.object(nodes, "poll_image_task", return_value=final) as poll, \
             patch.object(nodes, "download_image", return_value=IMAGE) as download:
            result = nodes.ZhenzhenImageNB21().execute(
                **self.arguments(size="auto"), image1=IMAGE, image14=IMAGE, seed=123)
        self.assertEqual(upload.call_count, 2)
        self.assertEqual([call.args[1] for call in upload.call_args_list],
                         ["nb21_reference_1.png", "nb21_reference_14.png"])
        self.assertEqual(submit.call_args.args[0]["images"], ["ref1", "ref14"])
        self.assertEqual(submit.call_args.args[0]["metadata"], {"resolution": "1k"})
        self.assertNotIn("seed", submit.call_args.args[0])
        poll.assert_called_once()
        download.assert_called_once_with("https://cdn.test/result.png", logger_prefix="zhenzhen-image-nb-2.1")
        self.assertIs(result["result"][0], IMAGE)
        self.assertEqual(len(result["result"]), 4)

    def test_invalid_prompt_or_batch_is_rejected_before_upload(self):
        with patch.object(nodes, "upload_media") as upload, \
             patch.object(nodes, "submit_image_task") as submit:
            for arguments in (self.arguments(prompt="bad", image1=IMAGE),
                              self.arguments(image1=IMAGE, image14=IMAGE.repeat(2, 1, 1, 1))):
                with self.assertRaises(SeedanceAPIError):
                    nodes.ZhenzhenImageNB21().execute(**arguments)
        upload.assert_not_called()
        submit.assert_not_called()

    def test_skip_error_keeps_valid_image_and_four_outputs(self):
        result = nodes.ZhenzhenImageNB21().execute(**self.arguments(prompt="bad"), skip_error=True)
        self.assertEqual(len(result["result"]), 4)
        self.assertEqual(result["result"][0].shape, (1, 512, 512, 3))
        self.assertEqual(result["result"][1:3], ("", ""))

    def test_two_examples_keep_credentials_empty_and_link_slots_aligned(self):
        paths = list((ROOT / "examples").glob("zhenzhen-image-nb-2.1*.json"))
        self.assertEqual(len(paths), 2)
        for path in paths:
            with self.subTest(path=path.name):
                workflow = json.loads(path.read_text(encoding="utf-8"))
                generator = next(item for item in workflow["nodes"] if item["type"] == "Zhenzhen_Image_NB_2_1")
                config = next(item for item in workflow["nodes"] if item["type"] == "Seedance_Config")
                self.assertEqual(config["widgets_values"][1], "")
                self.assertEqual(generator["widgets_values"][-3:], [False, 0, "fixed"])
                self.assertEqual([item["name"] for item in generator["inputs"]],
                                 [f"image{i}" for i in range(1, 15)] + ["api_config"])
                for link in workflow["links"]:
                    if link[3] == generator["id"]:
                        slot = generator["inputs"][link[4]]
                        self.assertEqual(slot["type"], link[5])
                        self.assertEqual(slot["link"], link[0])
                self.assertTrue(any(item["type"] == "SaveImage" for item in workflow["nodes"]))


if __name__ == "__main__":
    unittest.main()
