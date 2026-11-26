"""Regression tests for three-image digital humans and five-image GK editing."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
import ComfyUI_Seedance as plugin
from ComfyUI_Seedance import nodes
from ComfyUI_Seedance.core.client import SeedanceAPIError


CONFIG = {"base_url": "https://example.test", "api_key": "sk-test"}
IMAGE = torch.zeros((1, 8, 8, 3))
AUDIO = {"waveform": torch.zeros(1, 1, 8000), "sample_rate": 8000}
DRIVING = "https://example.test/voice.wav"
IMAGE_URLS = [f"https://example.test/reference-{i}.png" for i in range(1, 6)]
DIGITAL = "Minimax_H3_ComfyUI_Digital_Human"
GK = "Zhenzhen_Image_GK_V15"


class MultiReferenceTests(unittest.TestCase):
    def test_old_socket_prefixes_and_submit_schemas(self):
        for key, prefix, appended in (
            (GK, ["image1", "api_config"], [f"image{i}" for i in range(2, 6)]),
            (DIGITAL + "_Token", ["image1", "audio1", "api_config"], ["image2", "image3"]),
            (DIGITAL, ["image1", "image2", "image3", "audio1", "api_config"], []),
        ):
            node = plugin.NODE_CLASS_MAPPINGS[key]
            wrapper = plugin.NODE_CLASS_MAPPINGS[f"SeedanceConcurrent_{key}_Submit"]
            optional = node.INPUT_TYPES()["optional"]
            self.assertEqual([name for name, spec in optional.items() if spec[0] in ("IMAGE", "AUDIO", "SEEDANCE_CONFIG")], prefix + appended)
            self.assertEqual(wrapper.INPUT_TYPES(), node.INPUT_TYPES())
            self.assertNotIn("VALIDATE_INPUTS", dir(wrapper))
        self.assertEqual(nodes.MinimaxH3ComfyUICharSwap.INPUT_TYPES()["optional"]["image9"][0], "IMAGE")
        self.assertEqual(nodes.MinimaxH3CharSwapToken.INPUT_TYPES()["optional"]["image5"][0], "IMAGE")

    def test_digital_human_submits_three_images_in_order_and_one_driving_audio(self):
        prompt = "Speak as the same person shown in <Picture 1>, <Picture 2>, and <Picture 3>."
        common = dict(prompt=prompt, image3=IMAGE, image1=IMAGE, audio1=AUDIO, image2=IMAGE, seed=47, api_config=CONFIG)
        for cls, args, expected in (
            (nodes.MinimaxH3ComfyUIDigitalHuman, dict(duration_mode="frames", frames=124, prompt_extend=False),
             {"resolution": "608p", "ratio": "auto", "frames": 124, "seed": 47, "prompt_extend": False}),
            (nodes.MinimaxH3DigitalHumanToken, dict(seconds="3"), {"ratio": "16:9"}),
        ):
            with self.subTest(node=cls.__name__), \
                    patch.object(nodes, "upload_media", side_effect=[*IMAGE_URLS[:3], DRIVING]) as upload, \
                    patch.object(nodes, "submit_legacy_video_task", return_value="fixture") as submit, \
                    patch.object(nodes, "poll_legacy_video_task", return_value={"data": {"result_url": "https://example.test/movie.mp4"}}), \
                    patch.object(nodes, "download_video", return_value="mock-video"):
                self.assertEqual(cls().execute(**common, **args)["result"][0], "mock-video")
                self.assertEqual([call.args[1] for call in upload.call_args_list], ["image1.png", "image2.png", "image3.png", "audio1.wav"])
                payload = submit.call_args.args[0]
                self.assertEqual(payload["images"], IMAGE_URLS[:3])
                self.assertEqual(payload["metadata"], {**expected, "audio_urls": [DRIVING]})
                self.assertEqual(payload.get("seconds"), args.get("seconds"))
                self.assertEqual(payload["model"], "minimax-h3-comfyui-digital-human" + ("-token" if cls is nodes.MinimaxH3DigitalHumanToken else ""))

    def test_invalid_digital_human_references_and_durations_fail_before_upload(self):
        for cls in (nodes.MinimaxH3ComfyUIDigitalHuman, nodes.MinimaxH3DigitalHumanToken):
            base = dict(prompt="<Picture 1> speaks.", image1=IMAGE, audio1=AUDIO, api_config=CONFIG)
            for change in (dict(image4=IMAGE), dict(image1=None), dict(audio1=None), dict(audio2=AUDIO),
                           dict(video1=object()), dict(prompt="<Picture 2> speaks.")):
                with self.subTest(node=cls.__name__, field=next(iter(change))), \
                        patch.object(nodes, "upload_media") as upload, self.assertRaises(SeedanceAPIError):
                    try:
                        cls().execute(**{**base, **change})
                    finally:
                        upload.assert_not_called()
        with patch.object(nodes, "upload_media") as upload, self.assertRaisesRegex(SeedanceAPIError, "cover"):
            try:
                nodes.MinimaxH3ComfyUIDigitalHuman().execute(**base, duration_mode="frames", frames=22)
            finally:
                upload.assert_not_called()

    def test_gk_five_images_order_and_text_mode_compatibility(self):
        node = nodes.ZhenzhenImageGKV15()
        images = {f"image{i}": IMAGE for i in range(5, 0, -1)}
        base = dict(prompt="Combine the reference objects.", size="1:1", n=1, api_config=CONFIG)
        with patch.object(nodes, "upload_media", side_effect=IMAGE_URLS) as upload, \
                patch.object(nodes, "submit_image_task", return_value="fixture") as submit, \
                patch.object(nodes, "poll_image_task", return_value={"data": {"result_url": "https://example.test/result.png"}}), \
                patch.object(nodes, "download_image", return_value=IMAGE):
            node.execute(model=nodes.ZHENZHEN_IMAGE_GK_V15_EDIT_MODEL, **base, **images)
            self.assertEqual([call.args[1] for call in upload.call_args_list],
                             [f"zhenzhen_image_gk_v15_reference_{i}.png" for i in range(1, 6)])
            self.assertEqual(submit.call_args.args[0]["images"], IMAGE_URLS)
            upload.reset_mock()
            node.execute(model=nodes.ZHENZHEN_IMAGE_GK_V15_MODEL, **base, **images)
            upload.assert_not_called()
            self.assertNotIn("images", submit.call_args.args[0])
        with patch.object(nodes, "upload_media") as upload:
            for references in (dict(image6=IMAGE), dict(image1=IMAGE, image5=torch.zeros(2, 8, 8, 3))):
                with self.assertRaises(SeedanceAPIError):
                    node.execute(model=nodes.ZHENZHEN_IMAGE_GK_V15_EDIT_MODEL, **base, **references)
            upload.assert_not_called()

    def test_examples_connect_every_image_and_keep_api_key_blank(self):
        for name, key, count, saver in (
            ("minimax-h3-comfyui-digital-human-3refs", DIGITAL, 3, "SaveVideo"),
            ("minimax-h3-comfyui-digital-human-token-3refs", DIGITAL + "_Token", 3, "SaveVideo"),
            ("zhenzhen-image-gk-v15-edit-5refs", GK, 5, "SaveImage"),
        ):
            graph = json.loads((ROOT / "examples" / (name + ".json")).read_text(encoding="utf-8"))
            table = {node["type"]: node for node in graph["nodes"]}
            self.assertEqual(table["Seedance_Config"]["widgets_values"][1], "")
            self.assertIn(saver, table)
            target = table[key]
            self.assertEqual([item["name"] for item in target["inputs"] if item["type"] == "IMAGE" and item["link"] is not None],
                             [f"image{i}" for i in range(1, count + 1)])
            self.assertEqual(sum(i["type"] == "AUDIO" and i["link"] is not None for i in target["inputs"]), saver == "SaveVideo")
            by_id = {node["id"]: node for node in graph["nodes"]}
            for link, src, src_slot, dst, dst_slot, _ in graph["links"]:
                self.assertIn(link, by_id[src]["outputs"][src_slot]["links"])
                self.assertEqual(by_id[dst]["inputs"][dst_slot]["link"], link)
