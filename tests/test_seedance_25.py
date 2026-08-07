import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import torch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT.parent))

from ComfyUI_Seedance import concurrent_nodes, nodes
from ComfyUI_Seedance.core.client import SeedanceAPIError


CONFIG = {"base_url": "https://example.test", "api_key": "sk-test"}
IMAGE = torch.zeros((1, 8, 8, 3), dtype=torch.float32)


class Seedance25ContractTests(unittest.TestCase):
    def test_exact_documented_model_catalog_and_inputs(self):
        self.assertEqual(nodes.SEEDANCE25_MODELS, [
            "seedance-2.5-standard-t2v",
            "seedance-2.5-standard-i2v",
            "seedance-2.5-standard-multi",
            "seedance-2.5-global-standard-t2v",
            "seedance-2.5-global-standard-i2v",
            "seedance-2.5-global-standard-multi",
        ])
        inputs = nodes.Seedance25Video.INPUT_TYPES()
        self.assertEqual(inputs["required"]["model"][0], nodes.SEEDANCE25_MODELS)
        self.assertEqual(inputs["required"]["seconds"][0], [
            "-1", *[str(value) for value in range(4, 31)],
        ])
        self.assertEqual(
            inputs["required"]["resolution"][0],
            ["480p", "720p", "1080p", "2k", "4k"],
        )
        optional_names = list(inputs["optional"])
        self.assertEqual(
            [name for name in optional_names if name.startswith("image")],
            [f"image{index}" for index in range(1, 10)],
        )
        self.assertEqual(
            [name for name in optional_names if name.startswith("video")],
            [f"video{index}" for index in range(1, 4)],
        )
        self.assertEqual(
            [name for name in optional_names if name.startswith("audio")],
            [f"audio{index}" for index in range(1, 4)],
        )

    def test_validation_enforces_model_specific_contract(self):
        common = {
            "seconds": "4",
            "resolution": "480p",
            "ratio": "adaptive",
            "strict": True,
        }
        self.assertIs(
            nodes.Seedance25Video.VALIDATE_INPUTS(
                model=nodes.SEEDANCE25_T2V_MODELS[0],
                prompt="a paper boat crossing a quiet pond",
                **common,
            ),
            True,
        )
        self.assertIn(
            "prompt is required",
            nodes.Seedance25Video.VALIDATE_INPUTS(
                model=nodes.SEEDANCE25_MULTI_MODELS[0],
                prompt="",
                **common,
            ),
        )
        self.assertIs(
            nodes.Seedance25Video.VALIDATE_INPUTS(
                model=nodes.SEEDANCE25_I2V_MODELS[0],
                prompt="",
                **common,
            ),
            True,
        )
        self.assertIsNot(
            nodes.Seedance25Video.VALIDATE_INPUTS(
                model=nodes.SEEDANCE25_T2V_MODELS[0],
                prompt="valid prompt",
                seconds="31",
                resolution="480p",
                ratio="adaptive",
            ),
            True,
        )
        self.assertIsNot(
            nodes.Seedance25Video.VALIDATE_INPUTS(
                model=nodes.SEEDANCE25_T2V_MODELS[0],
                prompt="valid prompt",
                seconds="4",
                resolution="native1080p",
                ratio="adaptive",
            ),
            True,
        )

    def test_t2v_payload_uses_seconds_and_documented_metadata(self):
        payload = nodes.Seedance25Video().build_payload(
            {
                "model": nodes.SEEDANCE25_T2V_MODELS[0],
                "prompt": "a paper boat crossing a quiet pond",
                "seconds": "4",
                "resolution": "480p",
                "ratio": "16:9",
                "generate_audio": True,
                "seed": 7,
            },
            {},
        )
        self.assertEqual(payload, {
            "model": nodes.SEEDANCE25_T2V_MODELS[0],
            "prompt": "a paper boat crossing a quiet pond",
            "seconds": "4",
            "metadata": {
                "resolution": "480p",
                "ratio": "16:9",
                "generate_audio": True,
                "seed": 7,
            },
        })

    def test_smart_duration_uses_metadata_duration_not_seconds(self):
        payload = nodes.Seedance25Video().build_payload(
            {
                "model": nodes.SEEDANCE25_T2V_MODELS[1],
                "prompt": "a quiet studio product reveal",
                "seconds": "-1",
                "resolution": "720p",
                "ratio": "adaptive",
                "generate_audio": False,
                "seed": -1,
            },
            {},
        )
        self.assertNotIn("seconds", payload)
        self.assertEqual(payload["metadata"]["duration"], -1)
        self.assertNotIn("seed", payload["metadata"])

    def test_i2v_payload_uses_top_level_first_and_last_frame_images(self):
        payload = nodes.Seedance25Video().build_payload(
            {
                "model": nodes.SEEDANCE25_I2V_MODELS[0],
                "prompt": "",
                "seconds": "4",
                "resolution": "480p",
                "ratio": "adaptive",
                "generate_audio": True,
                "seed": -1,
            },
            {"images": ["https://cdn.test/first.png", "https://cdn.test/last.png"]},
        )
        self.assertEqual(
            payload["images"],
            ["https://cdn.test/first.png", "https://cdn.test/last.png"],
        )
        self.assertNotIn("prompt", payload)
        self.assertNotIn("content", payload["metadata"])

    def test_multi_payload_uses_only_metadata_content(self):
        content = [
            {"type": "image_url", "image_url": {"url": "https://cdn.test/image.png"}},
            {"type": "video_url", "video_url": {"url": "https://cdn.test/video.mp4"}},
            {"type": "audio_url", "audio_url": {"url": "https://cdn.test/audio.wav"}},
        ]
        payload = nodes.Seedance25Video().build_payload(
            {
                "model": nodes.SEEDANCE25_MULTI_MODELS[1],
                "prompt": "让 @Image 1 进入 @Video 1，并跟随 @Audio 1 的节奏",
                "seconds": "4",
                "resolution": "480p",
                "ratio": "16:9",
                "generate_audio": True,
                "seed": -1,
            },
            {"content": content},
        )
        self.assertEqual(payload["metadata"]["content"], content)
        self.assertNotIn("images", payload)

    def test_collect_media_maps_image_video_and_audio_to_content(self):
        progress = []
        with (
            patch.object(nodes, "image_to_png_bytes", return_value=b"image"),
            patch.object(nodes, "video_to_bytes", return_value=(b"video", "mp4")),
            patch.object(nodes, "audio_to_wav_bytes", return_value=b"audio"),
            patch.object(
                nodes,
                "upload_media",
                side_effect=[
                    "https://cdn.test/image.png",
                    "https://cdn.test/video.mp4",
                    "https://cdn.test/audio.wav",
                ],
            ) as upload,
        ):
            media = nodes.Seedance25Video().collect_media(
                {
                    "model": nodes.SEEDANCE25_MULTI_MODELS[0],
                    "image1": IMAGE,
                    "video1": "reference.mp4",
                    "audio1": {"waveform": torch.zeros((1, 1, 8)), "sample_rate": 8},
                },
                CONFIG,
                progress.append,
            )

        self.assertEqual(upload.call_count, 3)
        self.assertEqual(media["content"], [
            {"type": "image_url", "image_url": {"url": "https://cdn.test/image.png"}},
            {"type": "video_url", "video_url": {"url": "https://cdn.test/video.mp4"}},
            {"type": "audio_url", "audio_url": {"url": "https://cdn.test/audio.wav"}},
        ])
        self.assertEqual(progress, [1 / 3, 2 / 3, 1.0])

    def test_runtime_requires_i2v_and_multi_materials(self):
        node = nodes.Seedance25Video()
        with self.assertRaises(SeedanceAPIError):
            node.collect_media(
                {"model": nodes.SEEDANCE25_I2V_MODELS[0]},
                CONFIG,
                lambda _value: None,
            )
        with self.assertRaises(SeedanceAPIError):
            node.collect_media(
                {"model": nodes.SEEDANCE25_MULTI_MODELS[0]},
                CONFIG,
                lambda _value: None,
            )


class Seedance25RegistrationAndWorkflowTests(unittest.TestCase):
    def test_original_and_concurrent_nodes_are_registered(self):
        self.assertIs(
            nodes.NODE_CLASS_MAPPINGS["Seedance_2_5_Video"],
            nodes.Seedance25Video,
        )
        wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
            "SeedanceConcurrent_Seedance_2_5_Video_Submit"
        ]
        self.assertEqual(wrapper.CONCURRENT_KIND, "video")
        self.assertIs(wrapper.ORIGINAL_NODE_CLASS, nodes.Seedance25Video)

    def test_every_model_has_a_safe_example_workflow(self):
        workflow_models = {}
        for path in (PLUGIN_ROOT / "examples").glob("*.json"):
            workflow = json.loads(path.read_text(encoding="utf-8"))
            for node in workflow.get("nodes", []):
                if node.get("type") == "Seedance_2_5_Video":
                    workflow_models[node["widgets_values"][0]] = (path, workflow, node)

        self.assertEqual(set(workflow_models), set(nodes.SEEDANCE25_MODELS))
        for model, (path, workflow, node) in workflow_models.items():
            with self.subTest(model=model, workflow=path.name):
                config = next(
                    item for item in workflow["nodes"]
                    if item["type"] == "Seedance_Config"
                )
                self.assertEqual(config["widgets_values"][1], "")
                serialized = json.dumps(workflow, ensure_ascii=False)
                self.assertNotRegex(serialized, r"sk-[A-Za-z0-9]{12,}")
                self.assertNotRegex(serialized, r"task[_-][A-Za-z0-9_-]{6,}")
                incoming_types = [
                    link[5] for link in workflow.get("links", [])
                    if link[3] == node["id"]
                ]
                if model in nodes.SEEDANCE25_I2V_MODELS:
                    self.assertIn("IMAGE", incoming_types)
                elif model in nodes.SEEDANCE25_MULTI_MODELS:
                    self.assertTrue({"IMAGE", "VIDEO", "AUDIO"}.issubset(incoming_types))
                else:
                    self.assertNotIn("IMAGE", incoming_types)
                    self.assertNotIn("VIDEO", incoming_types)
                    self.assertNotIn("AUDIO", incoming_types)


if __name__ == "__main__":
    unittest.main()
