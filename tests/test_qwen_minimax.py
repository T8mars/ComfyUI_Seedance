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
AUDIO = {
    "waveform": torch.zeros((1, 1, 16000), dtype=torch.float32),
    "sample_rate": 16000,
}


class QwenImage30Tests(unittest.TestCase):
    def test_exact_documented_model_catalog(self):
        self.assertEqual(nodes.QWEN_IMAGE_30_MODELS, [
            "qwen-image-3.0-t2i",
            "qwen-image-3.0-i2i",
            "qwen-image-3.0-pro-t2i",
            "qwen-image-3.0-pro-i2i",
            "qwen-image-3.0-global-t2i",
            "qwen-image-3.0-global-i2i",
            "qwen-image-3.0-global-pro-t2i",
            "qwen-image-3.0-global-pro-i2i",
        ])
        inputs = nodes.QwenImage30.INPUT_TYPES()
        self.assertEqual(inputs["required"]["model"][0], nodes.QWEN_IMAGE_30_MODELS)
        self.assertEqual(
            list(inputs["optional"]),
            ["image1", "image2", "image3", "api_config", "skip_error"],
        )

    def test_strict_validation_requires_prompt_and_i2i_reference(self):
        self.assertIn(
            "prompt is required",
            nodes.QwenImage30.VALIDATE_INPUTS(
                model=nodes.QWEN_IMAGE_30_T2I_MODEL,
                prompt="",
                strict=True,
            ),
        )
        self.assertIn(
            "requires 1 to 3 images",
            nodes.QwenImage30.VALIDATE_INPUTS(
                model=nodes.QWEN_IMAGE_30_I2I_MODEL,
                prompt="valid prompt",
                sizing_mode="auto",
                resolution="1k",
                ratio="1:1",
                n=1,
                seed=-1,
                strict=True,
            ),
        )
        self.assertIs(
            nodes.QwenImage30.VALIDATE_INPUTS(
                model=nodes.QWEN_IMAGE_30_I2I_MODEL,
                prompt="valid prompt",
                sizing_mode="auto",
                resolution="1k",
                ratio="1:1",
                n=1,
                seed=-1,
                image1=IMAGE,
                strict=True,
            ),
            True,
        )

    def test_payload_modes_are_mutually_exclusive(self):
        node = nodes.QwenImage30()
        common = {
            "model": nodes.QWEN_IMAGE_30_T2I_MODEL,
            "prompt": "a clear studio product photograph",
            "negative_prompt": "blur",
            "prompt_extend": True,
            "resolution": "2k",
            "ratio": "16:9",
            "custom_size": "1024x1536",
            "n": 2,
            "seed": 9,
            "images": [],
        }

        auto = node._build_payload(sizing_mode="auto", **common)
        self.assertNotIn("size", auto)
        self.assertEqual(auto["metadata"], {"seed": 9})

        ratio = node._build_payload(sizing_mode="ratio", **common)
        self.assertNotIn("size", ratio)
        self.assertEqual(ratio["metadata"], {
            "seed": 9,
            "ratio": "16:9",
            "resolution": "2k",
        })

        custom = node._build_payload(sizing_mode="custom_size", **common)
        self.assertEqual(custom["size"], "1024*1536")
        self.assertEqual(custom["metadata"], {"seed": 9})

    def test_i2i_payload_forwards_one_to_three_images(self):
        payload = nodes.QwenImage30()._build_payload(
            nodes.QWEN_IMAGE_30_GLOBAL_PRO_I2I_MODEL,
            "edit this reference image",
            "",
            False,
            "auto",
            "1k",
            "1:1",
            "1024*1024",
            1,
            -1,
            ["https://media.test/1.png", "https://media.test/2.png"],
        )
        self.assertEqual(payload["images"], [
            "https://media.test/1.png",
            "https://media.test/2.png",
        ])
        self.assertNotIn("metadata", payload)
        self.assertNotIn("size", payload)

    def test_execute_uses_image_endpoint_and_uploads_only_for_i2i(self):
        final = {"data": {"status": "SUCCESS", "result_url": "https://result.test/image.png"}}
        with (
            patch.object(nodes, "get_config", return_value=CONFIG),
            patch.object(nodes, "upload_media", return_value="https://media.test/reference.png") as upload,
            patch.object(nodes, "submit_image_task", return_value="task-test") as submit,
            patch.object(nodes, "poll_image_task", return_value=final),
            patch.object(nodes, "extract_image_url", return_value="https://result.test/image.png"),
            patch.object(nodes, "download_image", return_value=IMAGE),
        ):
            result = nodes.QwenImage30().execute(
                model=nodes.QWEN_IMAGE_30_I2I_MODEL,
                prompt="edit the reference into a clean portrait",
                negative_prompt="",
                prompt_extend=True,
                sizing_mode="ratio",
                resolution="1k",
                ratio="1:1",
                custom_size="1024*1024",
                n=1,
                seed=-1,
                image1=IMAGE,
            )
        upload.assert_called_once()
        payload = submit.call_args.args[0]
        self.assertEqual(payload["images"], ["https://media.test/reference.png"])
        self.assertEqual(payload["metadata"], {"ratio": "1:1", "resolution": "1k"})
        self.assertTrue(torch.equal(result["result"][0], IMAGE))


class MinimaxH3OWTests(unittest.TestCase):
    def test_exact_documented_model_catalog_and_controls(self):
        self.assertEqual(nodes.MINIMAX_H3_OW_MODELS, [
            "minimax-h3-ow-t2v",
            "minimax-h3-ow-r2v",
            "minimax-h3-ow-i2v",
        ])
        inputs = nodes.MinimaxH3OWVideo.INPUT_TYPES()
        self.assertEqual(inputs["required"]["seconds"][0], ["5", "10", "15"])
        self.assertEqual(inputs["required"]["resolution"][0], ["480p", "720p"])
        self.assertEqual(inputs["required"]["ratio"][0], [
            "1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9",
        ])

    def test_strict_validation_is_model_aware(self):
        self.assertIn(
            "prompt is required",
            nodes.MinimaxH3OWVideo.VALIDATE_INPUTS(
                model=nodes.MINIMAX_H3_OW_T2V_MODEL,
                prompt="",
                seconds="5",
                resolution="480p",
                ratio="16:9",
                strict=True,
            ),
        )
        self.assertIn(
            "image1 is required",
            nodes.MinimaxH3OWVideo.VALIDATE_INPUTS(
                model=nodes.MINIMAX_H3_OW_R2V_MODEL,
                prompt="use the reference person",
                seconds="5",
                resolution="480p",
                ratio="16:9",
                strict=True,
            ),
        )
        self.assertIs(
            nodes.MinimaxH3OWVideo.VALIDATE_INPUTS(
                model=nodes.MINIMAX_H3_OW_I2V_MODEL,
                prompt="",
                seconds="5",
                resolution="480p",
                ratio="16:9",
                image1=IMAGE,
                strict=True,
            ),
            True,
        )

    def test_payload_contract_for_all_three_modes(self):
        node = nodes.MinimaxH3OWVideo()
        common = {
            "prompt": "slow cinematic camera movement",
            "seconds": "5",
            "resolution": "480p",
            "ratio": "16:9",
        }
        t2v = node.build_payload(
            {"model": nodes.MINIMAX_H3_OW_T2V_MODEL, **common},
            {},
        )
        self.assertNotIn("images", t2v)
        self.assertEqual(t2v["metadata"], {"resolution": "480p", "ratio": "16:9"})

        for model in (nodes.MINIMAX_H3_OW_I2V_MODEL, nodes.MINIMAX_H3_OW_R2V_MODEL):
            with self.subTest(model=model):
                payload = node.build_payload(
                    {"model": model, "image1": IMAGE, **common},
                    {"images": ["https://media.test/reference.png"]},
                )
                self.assertEqual(payload["images"], ["https://media.test/reference.png"])

    def test_execute_uses_video_flow(self):
        final = {"data": {"status": "SUCCESS", "video_url": "https://result.test/video.mp4"}}
        video = {"filename": "video.mp4"}
        with (
            patch.object(nodes, "get_config", return_value=CONFIG),
            patch.object(nodes, "upload_media", return_value="https://media.test/reference.png") as upload,
            patch.object(nodes, "submit_task", return_value="task-test") as submit,
            patch.object(nodes, "poll_task", return_value=final),
            patch.object(nodes, "extract_video_url", return_value="https://result.test/video.mp4"),
            patch.object(nodes, "download_video", return_value=video),
        ):
            result = nodes.MinimaxH3OWVideo().execute(
                model=nodes.MINIMAX_H3_OW_R2V_MODEL,
                prompt="use the reference person in a cinematic scene",
                seconds="5",
                resolution="480p",
                ratio="16:9",
                image1=IMAGE,
            )
        upload.assert_called_once()
        self.assertEqual(submit.call_args.args[0]["model"], nodes.MINIMAX_H3_OW_R2V_MODEL)
        self.assertIs(result["result"][0], video)


class MinimaxH3OWFastTests(unittest.TestCase):
    def test_exact_documented_model_catalog_and_controls(self):
        self.assertEqual(nodes.MINIMAX_H3_OW_FAST_MODELS, [
            "minimax-h3-ow-i2v-fast",
            "minimax-h3-ow-r2v-fast",
            "minimax-h3-ow-fl2va-audio-drive-fast",
            "minimax-h3-ow-ref2va-audio-drive-fast",
            "minimax-h3-ow-t2v-fast",
        ])
        inputs = nodes.MinimaxH3OWFastVideo.INPUT_TYPES()
        self.assertEqual(inputs["required"]["seconds"][0], ["5", "10", "15"])
        self.assertEqual(inputs["required"]["resolution"][0], ["480p", "720p"])
        self.assertEqual(inputs["required"]["ratio"][0], [
            "1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9",
        ])
        self.assertEqual(
            [name for name in inputs["optional"] if name.startswith("image")],
            [f"image{index}" for index in range(1, 10)],
        )
        self.assertEqual(list(inputs["optional"])[-4:], [
            "api_config", "audio", "skip_error", "seed",
        ])

    def test_strict_validation_enforces_fast_image_contracts(self):
        self.assertIn(
            "at least one image",
            nodes.MinimaxH3OWFastVideo.VALIDATE_INPUTS(
                model=nodes.MINIMAX_H3_OW_FAST_R2V_MODEL,
                prompt="use the reference subject",
                seconds="5",
                resolution="480p",
                ratio="16:9",
                strict=True,
            ),
        )
        self.assertIn(
            "exactly image1",
            nodes.MinimaxH3OWFastVideo.VALIDATE_INPUTS(
                model=nodes.MINIMAX_H3_OW_FAST_I2V_MODEL,
                prompt="",
                seconds="5",
                resolution="480p",
                ratio="16:9",
                image1=IMAGE,
                image2=IMAGE,
                strict=True,
            ),
        )
        self.assertIn(
            "prompt is required",
            nodes.MinimaxH3OWFastVideo.VALIDATE_INPUTS(
                model=nodes.MINIMAX_H3_OW_FAST_R2V_MODEL,
                prompt="",
                seconds="5",
                resolution="480p",
                ratio="16:9",
                image1=IMAGE,
                strict=True,
            ),
        )
        self.assertIs(
            nodes.MinimaxH3OWFastVideo.VALIDATE_INPUTS(
                model=nodes.MINIMAX_H3_OW_FAST_R2V_MODEL,
                prompt="use all references",
                seconds="5",
                resolution="720p",
                ratio="21:9",
                image1=IMAGE,
                image9=IMAGE,
                strict=True,
            ),
            True,
        )

    def test_payload_preserves_one_i2v_or_up_to_nine_r2v_images(self):
        node = nodes.MinimaxH3OWFastVideo()
        common = {
            "prompt": "subtle natural motion",
            "seconds": "5",
            "resolution": "480p",
            "ratio": "16:9",
        }
        i2v = node.build_payload(
            {
                "model": nodes.MINIMAX_H3_OW_FAST_I2V_MODEL,
                "image1": IMAGE,
                **common,
            },
            {"images": ["https://media.test/first.png"]},
        )
        self.assertEqual(i2v["images"], ["https://media.test/first.png"])

        r2v_kwargs = {
            "model": nodes.MINIMAX_H3_OW_FAST_R2V_MODEL,
            **common,
            **{f"image{index}": IMAGE for index in range(1, 10)},
        }
        r2v_urls = [f"https://media.test/reference-{index}.png" for index in range(1, 10)]
        r2v = node.build_payload(r2v_kwargs, {"images": r2v_urls})
        self.assertEqual(r2v["images"], r2v_urls)
        self.assertEqual(r2v["metadata"], {"resolution": "480p", "ratio": "16:9"})

    def test_t2v_fast_requires_prompt_and_omits_media(self):
        node = nodes.MinimaxH3OWFastVideo()
        self.assertIn(
            "prompt is required",
            node.VALIDATE_INPUTS(
                model=nodes.MINIMAX_H3_OW_FAST_T2V_MODEL,
                prompt="",
                seconds="5",
                resolution="480p",
                ratio="16:9",
                strict=True,
            ),
        )
        payload = node.build_payload({
            "model": nodes.MINIMAX_H3_OW_FAST_T2V_MODEL,
            "prompt": "A paper kite floating through warm sunlight",
            "seconds": "5",
            "resolution": "480p",
            "ratio": "16:9",
        }, {})
        self.assertNotIn("images", payload)
        self.assertNotIn("audio_urls", payload["metadata"])

    def test_audio_drive_requires_exactly_one_image_and_one_audio(self):
        for model in nodes.MINIMAX_H3_OW_FAST_AUDIO_MODELS:
            with self.subTest(model=model):
                self.assertIn(
                    "audio is required",
                    nodes.MinimaxH3OWFastVideo.VALIDATE_INPUTS(
                        model=model,
                        prompt="subtle performance",
                        seconds="5",
                        resolution="480p",
                        ratio="16:9",
                        image1=IMAGE,
                        strict=True,
                    ),
                )
                self.assertIn(
                    "exactly image1",
                    nodes.MinimaxH3OWFastVideo.VALIDATE_INPUTS(
                        model=model,
                        prompt="subtle performance",
                        seconds="5",
                        resolution="480p",
                        ratio="16:9",
                        image1=IMAGE,
                        image2=IMAGE,
                        audio=AUDIO,
                        strict=True,
                    ),
                )
                payload = nodes.MinimaxH3OWFastVideo().build_payload({
                    "model": model,
                    "prompt": "subtle performance",
                    "seconds": "5",
                    "resolution": "480p",
                    "ratio": "16:9",
                    "image1": IMAGE,
                    "audio": AUDIO,
                }, {
                    "images": ["https://media.test/reference.png"],
                    "audio_urls": ["https://media.test/drive.wav"],
                })
                self.assertEqual(payload["images"], ["https://media.test/reference.png"])
                self.assertEqual(
                    payload["metadata"],
                    {
                        "resolution": "480p",
                        "ratio": "16:9",
                        "audio_urls": ["https://media.test/drive.wav"],
                    },
                )

    def test_collect_media_uploads_audio_drive_image_then_wav(self):
        node = nodes.MinimaxH3OWFastVideo()
        progress = []
        with (
            patch.object(nodes, "image_to_png_bytes", return_value=b"image"),
            patch.object(nodes, "audio_to_wav_bytes", return_value=b"audio"),
            patch.object(
                nodes,
                "upload_media",
                side_effect=[
                    "https://media.test/reference.png",
                    "https://media.test/drive.wav",
                ],
            ) as upload,
        ):
            media = node.collect_media({
                "model": nodes.MINIMAX_H3_OW_FAST_FL2VA_AUDIO_MODEL,
                "image1": IMAGE,
                "audio": AUDIO,
            }, CONFIG, progress.append)

        self.assertEqual(upload.call_count, 2)
        self.assertEqual(media, {
            "images": ["https://media.test/reference.png"],
            "audio_urls": ["https://media.test/drive.wav"],
        })
        self.assertEqual(progress, [0.5, 1.0])

    def test_collect_media_uploads_every_connected_r2v_image_in_slot_order(self):
        node = nodes.MinimaxH3OWFastVideo()
        progress = []
        with (
            patch.object(nodes, "image_to_png_bytes", return_value=b"image"),
            patch.object(
                nodes,
                "upload_media",
                side_effect=["https://media.test/1.png", "https://media.test/3.png"],
            ) as upload,
        ):
            media = node.collect_media(
                {
                    "model": nodes.MINIMAX_H3_OW_FAST_R2V_MODEL,
                    "image1": IMAGE,
                    "image3": IMAGE,
                },
                CONFIG,
                progress.append,
            )

        self.assertEqual(upload.call_count, 2)
        self.assertEqual(media["images"], [
            "https://media.test/1.png",
            "https://media.test/3.png",
        ])
        self.assertEqual(progress, [0.5, 1.0])


class QwenMinimaxRegistrationAndWorkflowTests(unittest.TestCase):
    def test_original_and_concurrent_nodes_are_registered(self):
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Qwen_Image_3_0"], nodes.QwenImage30)
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Minimax_H3_OW_Video"], nodes.MinimaxH3OWVideo)
        self.assertIs(
            nodes.NODE_CLASS_MAPPINGS["Minimax_H3_OW_Fast_Video"],
            nodes.MinimaxH3OWFastVideo,
        )
        for key, kind in (
            ("Qwen_Image_3_0", "image"),
            ("Minimax_H3_OW_Video", "video"),
            ("Minimax_H3_OW_Fast_Video", "video"),
        ):
            wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
                f"SeedanceConcurrent_{key}_Submit"
            ]
            self.assertEqual(wrapper.CONCURRENT_KIND, kind)
            self.assertIs(wrapper.ORIGINAL_NODE_CLASS, nodes.NODE_CLASS_MAPPINGS[key])

    def test_every_model_has_a_safe_example_workflow(self):
        workflow_models = {}
        for path in (PLUGIN_ROOT / "examples").glob("*.json"):
            workflow = json.loads(path.read_text(encoding="utf-8"))
            for node in workflow.get("nodes", []):
                if node.get("type") == "Qwen_Image_3_0":
                    workflow_models[node["widgets_values"][0]] = (path, workflow, node)
                elif node.get("type") in (
                    "Minimax_H3_OW_Video",
                    "Minimax_H3_OW_Fast_Video",
                ):
                    workflow_models[node["widgets_values"][0]] = (path, workflow, node)

        expected = set(
            nodes.QWEN_IMAGE_30_MODELS
            + nodes.MINIMAX_H3_OW_MODELS
            + nodes.MINIMAX_H3_OW_FAST_MODELS
        )
        self.assertEqual(set(workflow_models), expected)
        for model, (path, workflow, node) in workflow_models.items():
            with self.subTest(model=model, workflow=path.name):
                config_node = next(item for item in workflow["nodes"] if item["type"] == "Seedance_Config")
                self.assertEqual(config_node["widgets_values"][1], "")
                if model in nodes.MINIMAX_H3_OW_FAST_MODELS:
                    expected_inputs = [
                        f"image{index}" for index in range(1, 10)
                    ] + ["api_config"]
                    if model in (
                        *nodes.MINIMAX_H3_OW_FAST_AUDIO_MODELS,
                        nodes.MINIMAX_H3_OW_FAST_T2V_MODEL,
                    ):
                        expected_inputs.append("audio")
                    self.assertEqual(
                        [item["name"] for item in node["inputs"]],
                        expected_inputs,
                    )
                    config_link = next(
                        link for link in workflow["links"]
                        if link[3] == node["id"] and link[5] == "SEEDANCE_CONFIG"
                    )
                    self.assertEqual(config_link[4], 9)
                incoming_images = [
                    link for link in workflow.get("links", [])
                    if link[3] == node["id"] and link[5] == "IMAGE"
                ]
                if model in nodes.QWEN_IMAGE_30_I2I_MODELS or model in (
                    nodes.MINIMAX_H3_OW_I2V_MODEL,
                    nodes.MINIMAX_H3_OW_R2V_MODEL,
                    nodes.MINIMAX_H3_OW_FAST_I2V_MODEL,
                    nodes.MINIMAX_H3_OW_FAST_R2V_MODEL,
                    *nodes.MINIMAX_H3_OW_FAST_AUDIO_MODELS,
                ):
                    self.assertEqual(len(incoming_images), 1)
                else:
                    self.assertEqual(incoming_images, [])
                incoming_audio = [
                    link for link in workflow.get("links", [])
                    if link[3] == node["id"] and link[5] == "AUDIO"
                ]
                if model in nodes.MINIMAX_H3_OW_FAST_AUDIO_MODELS:
                    self.assertEqual(len(incoming_audio), 1)
                    self.assertEqual(incoming_audio[0][4], 10)
                else:
                    self.assertEqual(incoming_audio, [])


if __name__ == "__main__":
    unittest.main()
