import json
import unittest
from pathlib import Path
from unittest.mock import patch

from ComfyUI_Seedance import concurrent_nodes, nodes


CONFIG = {"base_url": "https://example.test", "api_key": "sk-test"}
PLUGIN_ROOT = Path(__file__).resolve().parents[1]


class Wan30VideoTests(unittest.TestCase):
    def test_documented_models_and_controls(self):
        self.assertEqual(nodes.WAN30_MODELS, [
            "wan-3.0-i2v",
            "wan-3.0-r2v",
            "wan-3.0-global-i2v",
            "wan-3.0-global-r2v",
        ])
        self.assertEqual(nodes.WAN30_SECONDS[0], "auto")
        self.assertEqual(nodes.WAN30_SECONDS[1:], [str(value) for value in range(2, 31)])
        self.assertEqual(nodes.WAN30_RESOLUTIONS, ["480P", "720P", "1080P"])
        self.assertEqual(
            nodes.WAN30_RATIOS,
            ["adaptive", "16:9", "4:3", "1:1", "3:4", "9:16"],
        )

        inputs = nodes.Wan30Video.INPUT_TYPES()
        self.assertEqual(inputs["required"]["model"][0], nodes.WAN30_MODELS)
        self.assertIs(inputs["required"]["seed"][1]["control_after_generate"], True)
        self.assertFalse(inputs["optional"]["skip_error"][1]["default"])
        for index in range(1, 11):
            self.assertIn(f"image{index}", inputs["optional"])
        for index in range(1, 6):
            self.assertIn(f"video{index}", inputs["optional"])
            self.assertIn(f"audio{index}", inputs["optional"])

    def test_i2v_payload_uses_first_and_optional_last_frame(self):
        payload = nodes.Wan30Video().build_payload(
            {
                "model": nodes.WAN30_I2V_MODEL,
                "prompt": "slow cinematic push in",
                "seconds": "2",
                "resolution": "480P",
                "ratio": "adaptive",
                "generate_audio": False,
                "enable_thinking": False,
                "file_url": "",
                "link_url": "",
                "seed": 7,
            },
            {"images": ["https://cdn.test/first.png", "https://cdn.test/last.png"]},
        )
        self.assertEqual(payload, {
            "model": "wan-3.0-i2v",
            "prompt": "slow cinematic push in",
            "seconds": "2",
            "images": ["https://cdn.test/first.png", "https://cdn.test/last.png"],
            "metadata": {
                "resolution": "480P",
                "ratio": "adaptive",
                "generate_audio": False,
                "seed": 7,
            },
        })

    def test_global_i2v_forwards_enable_thinking(self):
        payload = nodes.Wan30Video().build_payload(
            {
                "model": nodes.WAN30_GLOBAL_I2V_MODEL,
                "prompt": "",
                "seconds": "auto",
                "resolution": "720P",
                "ratio": "16:9",
                "generate_audio": True,
                "enable_thinking": True,
                "file_url": "",
                "link_url": "",
                "seed": 0,
            },
            {"images": ["https://cdn.test/first.png"]},
        )
        self.assertTrue(payload["metadata"]["enable_thinking"])
        self.assertNotIn("prompt", payload)

    def test_r2v_payload_forwards_all_documented_material_groups(self):
        payload = nodes.Wan30Video().build_payload(
            {
                "model": nodes.WAN30_R2V_MODEL,
                "prompt": "Image 1 enters Video 1 while Audio 1 guides the rhythm",
                "seconds": "30",
                "resolution": "1080P",
                "ratio": "9:16",
                "generate_audio": True,
                "enable_thinking": False,
                "file_url": "https://files.test/reference.pdf",
                "link_url": "",
                "seed": 2147483647,
            },
            {
                "images": [f"https://cdn.test/image-{value}.png" for value in range(1, 12)],
                "video_urls": [f"https://cdn.test/video-{value}.mp4" for value in range(1, 7)],
                "audio_urls": [f"https://cdn.test/audio-{value}.wav" for value in range(1, 7)],
            },
        )
        self.assertEqual(len(payload["images"]), 10)
        self.assertEqual(len(payload["metadata"]["video_url"]), 5)
        self.assertEqual(len(payload["metadata"]["audio_url"]), 5)
        self.assertEqual(payload["metadata"]["file_url"], "https://files.test/reference.pdf")
        self.assertNotIn("enable_thinking", payload["metadata"])

    def test_global_r2v_auto_enables_thinking_for_link(self):
        payload = nodes.Wan30Video().build_payload(
            {
                "model": nodes.WAN30_GLOBAL_R2V_MODEL,
                "prompt": "Use the referenced webpage as context",
                "seconds": "2",
                "resolution": "480P",
                "ratio": "adaptive",
                "generate_audio": False,
                "enable_thinking": False,
                "file_url": "",
                "link_url": "https://example.test/reference",
                "seed": 1,
            },
            {},
        )
        self.assertEqual(
            payload["metadata"]["link_url"],
            "https://example.test/reference",
        )
        self.assertTrue(payload["metadata"]["enable_thinking"])

    def test_validation_matches_model_specific_contracts(self):
        valid_i2v = nodes.Wan30Video.VALIDATE_INPUTS(
            model=nodes.WAN30_I2V_MODEL,
            prompt="",
            seconds="2",
            resolution="480P",
            ratio="adaptive",
            file_url="",
            link_url="",
            seed=0,
            strict=True,
            image1=object(),
        )
        self.assertIs(valid_i2v, True)
        self.assertIsNot(
            nodes.Wan30Video.VALIDATE_INPUTS(
                model=nodes.WAN30_I2V_MODEL,
                prompt="",
                seconds="2",
                resolution="480P",
                ratio="adaptive",
                seed=0,
                strict=True,
            ),
            True,
        )
        self.assertIsNot(
            nodes.Wan30Video.VALIDATE_INPUTS(
                model=nodes.WAN30_R2V_MODEL,
                prompt="",
                seconds="2",
                resolution="480P",
                ratio="adaptive",
                seed=0,
                strict=True,
            ),
            True,
        )
        self.assertIsNot(
            nodes.Wan30Video.VALIDATE_INPUTS(
                model=nodes.WAN30_R2V_MODEL,
                prompt="reference",
                seconds="2",
                resolution="480P",
                ratio="adaptive",
                file_url="https://files.test/reference.pdf",
                link_url="https://example.test/reference",
                seed=0,
                strict=True,
            ),
            True,
        )

    @patch.object(nodes, "audio_to_wav_bytes", return_value=b"wav")
    @patch.object(nodes, "video_to_bytes", return_value=(b"mp4", "mp4"))
    @patch.object(nodes, "image_to_png_bytes", return_value=b"png")
    @patch.object(nodes, "upload_media")
    def test_r2v_collects_images_videos_and_audios(
        self,
        upload_media,
        image_to_png_bytes,
        video_to_bytes,
        audio_to_wav_bytes,
    ):
        upload_media.side_effect = [
            "https://cdn.test/image.png",
            "https://cdn.test/video.mp4",
            "https://cdn.test/audio.wav",
        ]
        progress = []
        media = nodes.Wan30Video().collect_media(
            {
                "model": nodes.WAN30_R2V_MODEL,
                "prompt": "Use Image 1, Video 1, and Audio 1",
                "image1": object(),
                "video1": object(),
                "audio1": object(),
            },
            CONFIG,
            progress.append,
        )
        self.assertEqual(media, {
            "images": ["https://cdn.test/image.png"],
            "video_urls": ["https://cdn.test/video.mp4"],
            "audio_urls": ["https://cdn.test/audio.wav"],
        })
        self.assertEqual(progress, [1 / 3, 2 / 3, 1.0])
        image_to_png_bytes.assert_called_once()
        video_to_bytes.assert_called_once()
        audio_to_wav_bytes.assert_called_once()

    @patch.object(nodes, "upload_media")
    def test_collect_media_rejects_invalid_r2v_before_upload(self, upload_media):
        with self.assertRaisesRegex(nodes.SeedanceAPIError, "prompt is required"):
            nodes.Wan30Video().collect_media(
                {
                    "model": nodes.WAN30_R2V_MODEL,
                    "prompt": "",
                    "seconds": "2",
                    "resolution": "480P",
                    "ratio": "adaptive",
                    "file_url": "",
                    "link_url": "",
                    "seed": 0,
                    "image1": object(),
                },
                CONFIG,
                lambda _value: None,
            )
        upload_media.assert_not_called()

    def test_registration_and_concurrent_wrapper(self):
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Wan_3_0_Video"], nodes.Wan30Video)
        self.assertIn("Wan_3_0_Video", concurrent_nodes.PURE_VIDEO_NODE_KEYS)
        wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
            "SeedanceConcurrent_Wan_3_0_Video_Submit"
        ]
        self.assertIs(wrapper.ORIGINAL_NODE_CLASS, nodes.Wan30Video)

    def test_four_safe_workflows_cover_models_and_material_modes(self):
        expected_slots = (
            [f"image{index}" for index in range(1, 11)]
            + [f"video{index}" for index in range(1, 6)]
            + [f"audio{index}" for index in range(1, 6)]
            + ["api_config"]
        )
        workflows = {}
        for path in sorted((PLUGIN_ROOT / "examples").glob("wan-3.0*.json")):
            workflow = json.loads(path.read_text(encoding="utf-8"))
            node = next(
                item for item in workflow["nodes"] if item["type"] == "Wan_3_0_Video"
            )
            workflows[node["widgets_values"][0]] = (path, workflow, node)

        self.assertEqual(set(workflows), set(nodes.WAN30_MODELS))
        for model, (path, workflow, node) in workflows.items():
            with self.subTest(model=model, workflow=path.name):
                self.assertEqual(
                    [item["name"] for item in node["inputs"]],
                    expected_slots,
                )
                config = next(
                    item for item in workflow["nodes"] if item["type"] == "Seedance_Config"
                )
                self.assertEqual(config["widgets_values"][1], "")

                links = [
                    link
                    for link in workflow["links"]
                    if link[3] == node["id"]
                ]
                self.assertTrue(
                    any(link[4] == 20 and link[5] == "SEEDANCE_CONFIG" for link in links)
                )
                media_slots = {
                    (link[4], link[5])
                    for link in links
                    if link[5] in {"IMAGE", "VIDEO", "AUDIO"}
                }
                if model.endswith("-i2v"):
                    self.assertEqual(media_slots, {(0, "IMAGE"), (1, "IMAGE")})
                else:
                    self.assertEqual(
                        media_slots,
                        {(0, "IMAGE"), (10, "VIDEO"), (15, "AUDIO")},
                    )


if __name__ == "__main__":
    unittest.main()
