import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import torch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from ComfyUI_Seedance import concurrent_nodes, nodes
from ComfyUI_Seedance.core.client import SeedanceAPIError, extract_legacy_video_url


CONFIG = {"base_url": "https://api.seedance.nz", "api_key": "sk-test"}
IMAGE = torch.zeros((1, 16, 16, 3), dtype=torch.float32)


class QwenGlobal21Tests(unittest.TestCase):
    def test_inputs_and_registration(self):
        inputs = nodes.QwenImageGlobal21.INPUT_TYPES()
        self.assertEqual(list(inputs["optional"])[:10], [f"image{i}" for i in range(1, 11)])
        self.assertEqual(inputs["required"]["resolution"][1]["default"], "2k")
        self.assertEqual(inputs["required"]["ratio"][1]["default"], "3:4")
        self.assertEqual(inputs["required"]["seed"][1]["max"], 9007199254740991)
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Qwen_Image_Global_2_1"], nodes.QwenImageGlobal21)
        self.assertEqual(
            concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
                "SeedanceConcurrent_Qwen_Image_Global_2_1_Submit"
            ].CONCURRENT_KIND, "image",
        )

    def test_exact_payload_and_seed_zero(self):
        build = nodes.QwenImageGlobal21.build_payload
        self.assertEqual(build("  sample ", "2k", "3:4", -1, []), {
            "model": "qwen-image-global-2.1", "prompt": "sample",
            "metadata": {"ratio": "3:4", "resolution": "2k"},
        })
        self.assertEqual(build("edit", "4k", "1:1", 0, ["https://cdn.test/a.png"]), {
            "model": "qwen-image-global-2.1", "prompt": "edit",
            "images": ["https://cdn.test/a.png"],
            "metadata": {"ratio": "1:1", "resolution": "4k", "seed": 0},
        })

    def test_invalid_prompt_and_batch_fail_before_upload(self):
        with patch.object(nodes, "upload_media") as upload:
            with self.assertRaisesRegex(SeedanceAPIError, "prompt is required"):
                nodes.QwenImageGlobal21().execute(prompt=" ", resolution="1k", ratio="3:4", seed=-1)
            with self.assertRaisesRegex(SeedanceAPIError, "not a batch"):
                nodes.QwenImageGlobal21().execute(
                    prompt="edit", resolution="1k", ratio="3:4", seed=-1,
                    image1=torch.zeros((2, 16, 16, 3)),
                )
        upload.assert_not_called()

    def test_node_uploads_ordered_images_and_downloads_list_only_result(self):
        final = {"data": {"status": "SUCCESS", "data": {"content": {
            "image_urls": ["https://cdn.test/result.png"]}}}}
        with (
            patch.object(nodes, "get_config", return_value=CONFIG),
            patch.object(nodes, "upload_media", side_effect=["https://cdn.test/1.png", "https://cdn.test/2.png"]) as upload,
            patch.object(nodes, "submit_image_task", return_value="test-task") as submit,
            patch.object(nodes, "poll_image_task", return_value=final),
            patch.object(nodes, "download_image", return_value=IMAGE) as download,
        ):
            result = nodes.QwenImageGlobal21().execute(
                prompt="edit", resolution="1k", ratio="16:9", seed=0,
                image1=IMAGE, image3=IMAGE,
            )
        self.assertEqual(upload.call_count, 2)
        self.assertEqual(submit.call_args.args[0], {
            "model": "qwen-image-global-2.1", "prompt": "edit",
            "images": ["https://cdn.test/1.png", "https://cdn.test/2.png"],
            "metadata": {"ratio": "16:9", "resolution": "1k", "seed": 0},
        })
        download.assert_called_once_with("https://cdn.test/result.png", logger_prefix="qwen-image-global-2.1")
        self.assertIs(result["result"][0], IMAGE)


class AnimateMotionTransferTests(unittest.TestCase):
    def base(self, **overrides):
        values = {name: options[1]["default"] for name, options in
                  nodes.AnimateMotionTransfer.INPUT_TYPES()["required"].items()}
        values.update({"image_url": "https://cdn.test/character.png",
                       "video_url": "https://cdn.test/motion.mp4"})
        values.update(overrides)
        return values

    def test_registration_and_cache_only_seed(self):
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Animate_Motion_Transfer"], nodes.AnimateMotionTransfer)
        self.assertEqual(
            concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
                "SeedanceConcurrent_Animate_Motion_Transfer_Submit"
            ].CONCURRENT_KIND, "video",
        )
        inputs = nodes.AnimateMotionTransfer.INPUT_TYPES()
        self.assertEqual(list(inputs["optional"]), ["input_image", "input_video", "api_config", "skip_error", "seed"])
        self.assertTrue(nodes.AnimateMotionTransfer.SEEDANCE_CACHE_ONLY_SEED)

    def test_exact_minimal_payload_has_single_image_and_video_array(self):
        node = nodes.AnimateMotionTransfer()
        payload = node.build_payload(self.base(), {
            "image_url": "https://cdn.test/character.png",
            "video_url": "https://cdn.test/motion.mp4",
        })
        self.assertEqual(payload, {
            "model": "animate-motion-transfer",
            "images": ["https://cdn.test/character.png"],
            "metadata": {
                "video_url": ["https://cdn.test/motion.mp4"],
                "resolution": "720p", "ratio": "adaptive",
                "frame_rate": 30, "pose_method": "vitpose",
            },
        })
        self.assertNotIn("prompt", payload)
        self.assertNotIn("seed", payload["metadata"])

    def test_custom_controls_and_preflight(self):
        node = nodes.AnimateMotionTransfer()
        kwargs = self.base(
            resolution="1080p", ratio="custom", custom_ratio="4:5", frame_rate=24,
            max_frames=240, skip_frames=3, pose_method="sdpose", camera_motion=True,
            normal_mode=False, pose_strength=1.2,
        )
        self.assertIs(node.VALIDATE_INPUTS(**kwargs, strict=True), True)
        metadata = node.build_payload(kwargs, {
            "image_url": kwargs["image_url"], "video_url": kwargs["video_url"],
        })["metadata"]
        self.assertEqual(metadata["ratio"], "4:5")
        self.assertEqual(metadata["max_frames"], 240)
        self.assertEqual(metadata["normal_mode"], False)
        self.assertEqual(metadata["pose_strength"], 1.2)
        self.assertIn("max_frames", node.VALIDATE_INPUTS(**(kwargs | {"max_frames": 241}), strict=True))
        self.assertIn("custom_ratio", node.VALIDATE_INPUTS(**(kwargs | {"custom_ratio": "abc"}), strict=True))
        with patch.object(nodes, "upload_media") as upload:
            with self.assertRaisesRegex(SeedanceAPIError, "exactly one character"):
                node.execute(**(self.base(image_url="") | {"seed": 0}))
            with self.assertRaisesRegex(SeedanceAPIError, "exactly one motion"):
                node.execute(**(self.base() | {"input_video": object()}))
        upload.assert_not_called()

    def test_local_upload_poll_and_video_urls_fallback(self):
        kwargs = self.base(image_url="", video_url="")
        final = {"data": {"status": "SUCCESS", "data": {"content": {
            "video_urls": ["https://cdn.test/result.mp4"]}}}}
        with (
            patch.object(nodes, "get_config", return_value=CONFIG),
            patch.object(nodes, "video_to_bytes", return_value=(b"video", "mp4")),
            patch.object(nodes, "upload_media", side_effect=["https://cdn.test/image.png", "https://cdn.test/video.mp4"]) as upload,
            patch.object(nodes, "submit_legacy_video_task", return_value="test-task") as submit,
            patch.object(nodes, "poll_legacy_video_task", return_value=final),
            patch.object(nodes, "download_video", return_value={"file_path": "test.mp4"}) as download,
        ):
            result = nodes.AnimateMotionTransfer().execute(
                **kwargs, input_image=IMAGE, input_video=object(), seed=5,
            )
        self.assertEqual(upload.call_count, 2)
        self.assertEqual(submit.call_args.args[0]["images"], ["https://cdn.test/image.png"])
        self.assertEqual(submit.call_args.args[0]["metadata"]["video_url"], ["https://cdn.test/video.mp4"])
        download.assert_called_once_with("https://cdn.test/result.mp4", logger_prefix="animate-motion-transfer")
        self.assertEqual(result["result"][1], "https://cdn.test/result.mp4")
        self.assertEqual(extract_legacy_video_url(final), "https://cdn.test/result.mp4")

    def test_url_sources_skip_upload_and_use_primary_result_url(self):
        final = {"data": {
            "status": "SUCCESS",
            "result_url": "https://cdn.test/result.mp4",
            "data": {"content": {"video_urls": ["https://cdn.test/other.mp4"]}},
        }}
        with (
            patch.object(nodes, "get_config", return_value=CONFIG),
            patch.object(nodes, "upload_media") as upload,
            patch.object(nodes, "submit_legacy_video_task", return_value="test-task") as submit,
            patch.object(nodes, "poll_legacy_video_task", return_value=final),
            patch.object(nodes, "download_video", return_value="local.mp4") as download,
        ):
            result = nodes.AnimateMotionTransfer().execute(**self.base())
        upload.assert_not_called()
        self.assertEqual(submit.call_args.args[0]["images"], ["https://cdn.test/character.png"])
        self.assertEqual(submit.call_args.args[0]["metadata"]["video_url"], ["https://cdn.test/motion.mp4"])
        download.assert_called_once_with("https://cdn.test/result.mp4", logger_prefix="animate-motion-transfer")
        self.assertEqual(result["result"][0], "local.mp4")


class ExampleWorkflowTests(unittest.TestCase):
    def test_safe_and_connected_examples(self):
        expected = {
            "qwen-image-global-2.1文生图.json": ("Qwen_Image_Global_2_1", None),
            "qwen-image-global-2.1图像编辑.json": ("Qwen_Image_Global_2_1", "image1"),
            "animate-motion-transfer本地素材.json": ("Animate_Motion_Transfer", "input_video"),
            "animate-motion-transfer网址素材.json": ("Animate_Motion_Transfer", None),
        }
        for filename, (node_type, connected) in expected.items():
            with self.subTest(filename=filename):
                workflow = json.loads((ROOT / "examples" / filename).read_text(encoding="utf-8"))
                generator = next(node for node in workflow["nodes"] if node["type"] == node_type)
                config = next(node for node in workflow["nodes"] if node["type"] == "Seedance_Config")
                self.assertEqual(config["widgets_values"][1], "")
                if connected:
                    self.assertIsNotNone(next(item for item in generator["inputs"] if item["name"] == connected)["link"])
                self.assertNotIn("sk-", json.dumps(workflow))


if __name__ == "__main__":
    unittest.main()
