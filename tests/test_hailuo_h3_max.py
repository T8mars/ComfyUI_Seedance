import json
import unittest
from pathlib import Path
from unittest.mock import patch

from ComfyUI_Seedance import concurrent_nodes, nodes


CONFIG = {"base_url": "https://example.test", "api_key": "sk-test"}
PLUGIN_ROOT = Path(__file__).resolve().parents[1]


class HailuoH3MaxTests(unittest.TestCase):
    def test_documented_models_and_controls(self):
        self.assertEqual(nodes.HAILUO_H3_MAX_MODELS, [
            "hailuo-h3-max-t2v",
            "hailuo-h3-max-i2v",
        ])
        self.assertEqual(
            nodes.HAILUO_H3_MAX_SECONDS,
            [str(value) for value in range(5, 16)],
        )
        self.assertEqual(nodes.HAILUO_H3_MAX_RESOLUTIONS, ["480P", "768P"])
        self.assertEqual(
            nodes.HAILUO_H3_MAX_RATIOS,
            ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
        )

        inputs = nodes.HailuoH3MaxVideo.INPUT_TYPES()
        self.assertEqual(inputs["required"]["model"][0], nodes.HAILUO_H3_MAX_MODELS)
        self.assertEqual(inputs["optional"]["image1"][0], "IMAGE")
        self.assertEqual(inputs["optional"]["image2"][0], "IMAGE")
        self.assertFalse(inputs["optional"]["skip_error"][1]["default"])
        self.assertTrue(inputs["optional"]["seed"][1]["control_after_generate"])
        self.assertTrue(nodes.HailuoH3MaxVideo.SEEDANCE_CACHE_ONLY_SEED)

    def test_t2v_payload_matches_documented_contract(self):
        payload = nodes.HailuoH3MaxVideo().build_payload(
            {
                "model": nodes.HAILUO_H3_MAX_T2V_MODEL,
                "prompt": "A paper airplane glides through a sunlit studio",
                "seconds": "5",
                "resolution": "480P",
                "ratio": "16:9",
            },
            {},
        )

        self.assertEqual(payload, {
            "model": "hailuo-h3-max-t2v",
            "prompt": "A paper airplane glides through a sunlit studio",
            "seconds": "5",
            "metadata": {"resolution": "480P", "ratio": "16:9"},
        })

    def test_i2v_payload_uses_one_or_two_frames_without_ratio(self):
        payload = nodes.HailuoH3MaxVideo().build_payload(
            {
                "model": nodes.HAILUO_H3_MAX_I2V_MODEL,
                "prompt": "The camera moves forward while the subject turns naturally",
                "seconds": "15",
                "resolution": "768P",
                "ratio": "9:16",
            },
            {
                "images": [
                    "https://cdn.test/first.png",
                    "https://cdn.test/last.png",
                ],
            },
        )

        self.assertEqual(payload["images"], [
            "https://cdn.test/first.png",
            "https://cdn.test/last.png",
        ])
        self.assertEqual(payload["metadata"], {"resolution": "768P"})
        self.assertNotIn("ratio", payload["metadata"])

    def test_validation_enforces_model_specific_enums_and_prompt(self):
        self.assertIs(
            nodes.HailuoH3MaxVideo.VALIDATE_INPUTS(
                model=nodes.HAILUO_H3_MAX_T2V_MODEL,
                prompt="valid",
                seconds="5",
                resolution="480P",
                ratio="21:9",
                strict=True,
            ),
            True,
        )
        invalid_cases = (
            {"prompt": "", "seconds": "5", "resolution": "480P", "ratio": "16:9"},
            {"prompt": "valid", "seconds": "4", "resolution": "480P", "ratio": "16:9"},
            {"prompt": "valid", "seconds": "5", "resolution": "2K", "ratio": "16:9"},
            {"prompt": "valid", "seconds": "5", "resolution": "480P", "ratio": "adaptive"},
        )
        for values in invalid_cases:
            with self.subTest(values=values):
                self.assertIsNot(
                    nodes.HailuoH3MaxVideo.VALIDATE_INPUTS(
                        model=nodes.HAILUO_H3_MAX_T2V_MODEL,
                        strict=True,
                        **values,
                    ),
                    True,
                )
        self.assertIsNot(
            nodes.HailuoH3MaxVideo.VALIDATE_INPUTS(
                model=nodes.HAILUO_H3_MAX_T2V_MODEL,
                prompt="x" * (nodes.PROMPT_MAX_LENGTH + 1),
                seconds="5",
                resolution="480P",
                ratio="16:9",
            ),
            True,
        )

    @patch.object(nodes, "image_to_png_bytes", return_value=b"png")
    @patch.object(nodes, "upload_media")
    def test_i2v_uploads_first_and_optional_last_frame(
        self,
        upload_media,
        image_to_png_bytes,
    ):
        upload_media.side_effect = [
            "https://cdn.test/first.png",
            "https://cdn.test/last.png",
        ]
        progress = []
        media = nodes.HailuoH3MaxVideo().collect_media(
            {
                "model": nodes.HAILUO_H3_MAX_I2V_MODEL,
                "prompt": "Smooth motion between the first and last frame",
                "seconds": "5",
                "resolution": "480P",
                "ratio": "16:9",
                "image1": object(),
                "image2": object(),
            },
            CONFIG,
            progress.append,
        )

        self.assertEqual(media["images"], [
            "https://cdn.test/first.png",
            "https://cdn.test/last.png",
        ])
        self.assertEqual(progress, [0.5, 1.0])
        self.assertEqual(image_to_png_bytes.call_count, 2)
        self.assertEqual(upload_media.call_count, 2)

    @patch.object(nodes, "upload_media")
    def test_i2v_requires_first_frame_before_upload(self, upload_media):
        with self.assertRaisesRegex(nodes.SeedanceAPIError, "image1 is required"):
            nodes.HailuoH3MaxVideo().collect_media(
                {
                    "model": nodes.HAILUO_H3_MAX_I2V_MODEL,
                    "prompt": "Smooth motion",
                    "seconds": "5",
                    "resolution": "480P",
                    "ratio": "16:9",
                    "image2": object(),
                },
                CONFIG,
                lambda _value: None,
            )
        upload_media.assert_not_called()

    def test_registration_concurrency_and_frontend_switching(self):
        self.assertIs(
            nodes.NODE_CLASS_MAPPINGS["Hailuo_H3_Max_Video"],
            nodes.HailuoH3MaxVideo,
        )
        self.assertIn("Hailuo_H3_Max_Video", concurrent_nodes.PURE_VIDEO_NODE_KEYS)
        wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
            "SeedanceConcurrent_Hailuo_H3_Max_Video_Submit"
        ]
        self.assertIs(wrapper.ORIGINAL_NODE_CLASS, nodes.HailuoH3MaxVideo)

        frontend = (
            PLUGIN_ROOT / "web" / "js" / "hailuo_h3_model_ui.js"
        ).read_text(encoding="utf-8")
        self.assertIn('const HAILUO_H3_MAX_NODE_NAME = "Hailuo_H3_Max_Video"', frontend)
        self.assertIn("!model.endsWith(\"-i2v\")", frontend)
        self.assertIn('name === "image1" || name === "image2"', frontend)

    def test_workflows_cover_both_models_without_secrets(self):
        expected = {
            "hailuo-h3-max-t2v": "海螺hailuo-h3-max文生视频.json",
            "hailuo-h3-max-i2v": "海螺hailuo-h3-max图生视频首尾帧.json",
        }
        found = {}
        for path in (PLUGIN_ROOT / "examples").glob("*hailuo-h3-max*.json"):
            workflow = json.loads(path.read_text(encoding="utf-8"))
            node = next(
                item for item in workflow["nodes"]
                if item["type"] == "Hailuo_H3_Max_Video"
            )
            found[node["widgets_values"][0]] = path.name
            config = next(
                item for item in workflow["nodes"]
                if item["type"] == "Seedance_Config"
            )
            self.assertEqual(config["widgets_values"][1], "")
            self.assertEqual(
                [item["name"] for item in node["inputs"]],
                ["image1", "image2", "api_config"],
            )

            inbound = [link for link in workflow["links"] if link[3] == node["id"]]
            self.assertTrue(
                any(link[4] == 2 and link[5] == "SEEDANCE_CONFIG" for link in inbound)
            )
            image_links = [link for link in inbound if link[5] == "IMAGE"]
            if node["widgets_values"][0].endswith("-t2v"):
                self.assertEqual(image_links, [])
            else:
                self.assertEqual(
                    {(link[4], link[5]) for link in image_links},
                    {(0, "IMAGE"), (1, "IMAGE")},
                )

        self.assertEqual(found, expected)


if __name__ == "__main__":
    unittest.main()
