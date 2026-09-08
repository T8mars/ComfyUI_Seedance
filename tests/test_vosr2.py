import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import torch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT.parent))

from ComfyUI_Seedance import concurrent_nodes, nodes
from ComfyUI_Seedance.core import client


CONFIG = {
    "base_url": "https://api.seedance.nz",
    "api_key": "sk-test",
    "poll_interval": 0,
    "max_poll_time": 30,
}


class VOSR2ImageContractTests(unittest.TestCase):
    def test_inputs_match_exactly_one_image_contract(self):
        inputs = nodes.VOSR2ImageUpscale.INPUT_TYPES()
        self.assertEqual(nodes.VOSR2_IMAGE_UPSCALE_MODEL, "vosr2-image-upscale")
        self.assertEqual(list(inputs["required"]), ["input_image"])
        self.assertEqual(
            list(inputs["optional"]),
            ["api_config", "skip_error", "seed"],
        )
        self.assertTrue(inputs["optional"]["seed"][1]["control_after_generate"])

    def test_payload_contains_only_documented_fields(self):
        self.assertEqual(
            nodes.VOSR2ImageUpscale.build_payload("https://cdn.test/source.png"),
            {
                "model": "vosr2-image-upscale",
                "images": ["https://cdn.test/source.png"],
            },
        )

    def test_image_node_runs_upload_submit_poll_download_chain(self):
        source = torch.zeros((1, 24, 32, 3), dtype=torch.float32)
        output = torch.ones((1, 48, 64, 3), dtype=torch.float32)
        final = {
            "code": "success",
            "data": {
                "status": "SUCCESS",
                "result_url": "https://cdn.test/result.png",
            },
        }
        node = nodes.VOSR2ImageUpscale()
        with (
            patch.object(nodes, "get_config", return_value=CONFIG),
            patch.object(
                nodes,
                "upload_media",
                return_value="https://cdn.test/source.png",
            ) as upload,
            patch.object(
                nodes, "submit_image_task", return_value="task-test"
            ) as submit,
            patch.object(nodes, "poll_image_task", return_value=final),
            patch.object(nodes, "download_image", return_value=output) as download,
        ):
            result = node.execute(input_image=source)

        upload.assert_called_once()
        self.assertEqual(
            upload.call_args.args[1:3], ("vosr2_image_input.png", "image/png")
        )
        submit.assert_called_once_with(
            {
                "model": "vosr2-image-upscale",
                "images": ["https://cdn.test/source.png"],
            },
            CONFIG,
            logger_prefix="vosr2-image-upscale",
        )
        download.assert_called_once_with(
            "https://cdn.test/result.png",
            logger_prefix="vosr2-image-upscale",
        )
        self.assertIs(result["result"][0], output)

    def test_image_batch_is_rejected_before_upload(self):
        source = torch.zeros((2, 24, 32, 3), dtype=torch.float32)
        with patch.object(nodes, "upload_media") as upload:
            with self.assertRaisesRegex(client.SeedanceAPIError, "exactly one"):
                nodes.VOSR2ImageUpscale().execute(
                    input_image=source,
                    api_config=CONFIG,
                )
        upload.assert_not_called()


class VOSR2VideoContractTests(unittest.TestCase):
    def test_inputs_match_single_source_contract(self):
        inputs = nodes.VOSR2VideoUpscale.INPUT_TYPES()
        self.assertEqual(nodes.VOSR2_VIDEO_UPSCALE_MODEL, "vosr2-video-upscale")
        self.assertEqual(list(inputs["required"]), ["video_url"])
        self.assertEqual(
            list(inputs["optional"]),
            ["input_video", "api_config", "skip_error", "seed"],
        )

    def test_payload_uses_exact_compatibility_contract(self):
        self.assertEqual(
            nodes.VOSR2VideoUpscale().build_payload(
                {}, {"video_url": "https://cdn.test/source.mp4"}
            ),
            {
                "model": "vosr2-video-upscale",
                "metadata": {"video_url": "https://cdn.test/source.mp4"},
            },
        )

    def test_local_video_is_uploaded_once(self):
        with (
            patch.object(nodes, "video_to_bytes", return_value=(b"video", "mp4")),
            patch.object(
                nodes,
                "upload_media",
                return_value="https://cdn.test/source.mp4",
            ) as upload,
        ):
            media = nodes.VOSR2VideoUpscale().collect_media(
                {"video_url": "", "input_video": {"file_path": "source.mp4"}},
                CONFIG,
                lambda _value: None,
            )
        upload.assert_called_once_with(
            b"video",
            "vosr2_video_input.mp4",
            "video/mp4",
            CONFIG,
            logger_prefix="vosr2-video-upscale",
        )
        self.assertEqual(media, {"video_url": "https://cdn.test/source.mp4"})

    def test_exactly_one_video_source_is_required(self):
        node = nodes.VOSR2VideoUpscale()
        with self.assertRaisesRegex(client.SeedanceAPIError, "exactly one source"):
            node.collect_media(
                {
                    "video_url": "https://cdn.test/source.mp4",
                    "input_video": object(),
                },
                CONFIG,
                lambda _value: None,
            )
        with self.assertRaisesRegex(client.SeedanceAPIError, "connect input_video"):
            node.collect_media(
                {"video_url": "", "input_video": None},
                CONFIG,
                lambda _value: None,
            )

    def test_video_node_uses_compatibility_helpers_and_downloader(self):
        final = {
            "code": "success",
            "data": {
                "status": "SUCCESS",
                "result_url": "https://cdn.test/result.mp4",
            },
        }
        output = {"file_path": "result.mp4"}
        node = nodes.VOSR2VideoUpscale()
        with (
            patch.object(nodes, "get_config", return_value=CONFIG),
            patch.object(
                node,
                "collect_media",
                return_value={"video_url": "https://cdn.test/source.mp4"},
            ),
            patch.object(
                nodes, "submit_legacy_video_task", return_value="task-test"
            ) as submit,
            patch.object(nodes, "poll_legacy_video_task", return_value=final),
            patch.object(nodes, "download_video", return_value=output) as download,
        ):
            result = node.execute(video_url="https://cdn.test/source.mp4")

        submit.assert_called_once_with(
            {
                "model": "vosr2-video-upscale",
                "metadata": {"video_url": "https://cdn.test/source.mp4"},
            },
            CONFIG,
            logger_prefix="vosr2-video-upscale",
        )
        download.assert_called_once_with(
            "https://cdn.test/result.mp4",
            logger_prefix="vosr2-video-upscale",
        )
        self.assertIs(result["result"][0], output)


class VOSR2RegistrationAndWorkflowTests(unittest.TestCase):
    def test_serial_and_concurrent_nodes_are_registered(self):
        self.assertIs(
            nodes.NODE_CLASS_MAPPINGS["VOSR2_Image_Upscale"],
            nodes.VOSR2ImageUpscale,
        )
        self.assertIs(
            nodes.NODE_CLASS_MAPPINGS["VOSR2_Video_Upscale"],
            nodes.VOSR2VideoUpscale,
        )
        image_wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
            "SeedanceConcurrent_VOSR2_Image_Upscale_Submit"
        ]
        video_wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
            "SeedanceConcurrent_VOSR2_Video_Upscale_Submit"
        ]
        self.assertEqual(image_wrapper.CONCURRENT_KIND, "image")
        self.assertEqual(video_wrapper.CONCURRENT_KIND, "video")

    def test_safe_example_workflows(self):
        expected = {
            "VOSR2-4K图片超分.json": "VOSR2_Image_Upscale",
            "VOSR2-2K视频超分.json": "VOSR2_Video_Upscale",
        }
        for filename, node_type in expected.items():
            with self.subTest(workflow=filename):
                source = (PLUGIN_ROOT / "examples" / filename).read_text(
                    encoding="utf-8"
                )
                workflow = json.loads(source)
                config = next(
                    item
                    for item in workflow["nodes"]
                    if item["type"] == "Seedance_Config"
                )
                node = next(
                    item for item in workflow["nodes"] if item["type"] == node_type
                )
                self.assertEqual(
                    config["widgets_values"], ["https://api.seedance.nz", ""]
                )
                self.assertNotRegex(source, r"sk-[A-Za-z0-9]{12,}")
                self.assertNotRegex(source, r"task[_-][A-Za-z0-9_-]{6,}")
                self.assertTrue(
                    any(
                        link[3] == node["id"] and link[5] in {"IMAGE", "VIDEO"}
                        for link in workflow["links"]
                    )
                )


if __name__ == "__main__":
    unittest.main()
