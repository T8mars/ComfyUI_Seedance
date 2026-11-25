"""Offline tests for the new model contracts and workflow wiring."""

import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
import ComfyUI_Seedance as plugin
from ComfyUI_Seedance import nodes
from ComfyUI_Seedance.core import client, h3_token, llm, nov21_models as spec
from ComfyUI_Seedance.core.geometry import minimal_glb_bytes


CONFIG = {"base_url": "https://example.test", "api_key": "sk-test"}
IMAGE = torch.zeros(1, 16, 16, 3)
AUDIO = {"waveform": torch.zeros(1, 1, 8000), "sample_rate": 8000}
URL = "https://example.test/reference.png"


class ImageTests(unittest.TestCase):
    def test_long_image_contract_switches_array_shape(self):
        body, slots = spec.long_image({"prompt": "Use @Image1.", "image1": IMAGE, "length": "short"}, True)
        self.assertEqual(body, {"model": spec.LONG_IMAGE, "prompt": "Use @Image1.", "skill": "ecommerce",
                                "resolution": "1k", "nsfw_check": False, "length": "short"})
        self.assertEqual([name for name, _ in slots], ["image1"])
        body, slots = spec.long_image({"prompt": "Use @Image2.", "skill": "webpage",
                                      "subject_image": IMAGE, "style_image": IMAGE, "length": "long"}, True)
        self.assertNotIn("length", body)
        self.assertEqual([name for name, _ in slots], ["style", "subject"])
        for values in ({"prompt": "No product"}, {"prompt": "@Image2", "image1": IMAGE},
                       {"prompt": "Web", "skill": "webpage", "image1": IMAGE},
                       {"prompt": "Product", "image1": IMAGE, "style_image": IMAGE},
                       {"prompt": "a" * 83000 + "\u8336" * 35501, "image1": IMAGE},
                       {"prompt": "Product", "image4": IMAGE}):
            with self.subTest(values=[*values]), self.assertRaises(client.SeedanceAPIError):
                spec.long_image(values, True)

    def test_long_image_posts_only_documented_role_fields(self):
        final = {"data": {"result_url": "https://example.test/long.png"}}
        with patch.object(nodes, "upload_media", side_effect=["https://example.test/style.png", URL]), \
                patch.object(nodes, "submit_image_task", return_value="test") as submit, \
                patch.object(nodes, "poll_image_task", return_value=final), \
                patch.object(nodes, "download_image", return_value=IMAGE):
            self.assertIs(nodes.Kling4LongImage().execute(skill="webpage", prompt="A site", style_image=IMAGE,
                subject_image=IMAGE, seed=123, api_config=CONFIG)["result"][0], IMAGE)
        body = submit.call_args.args[0]
        self.assertEqual(body["image_with_roles"], [{"url": "https://example.test/style.png", "role": "style"}, {"url": URL, "role": "subject"}])
        self.assertNotIn("seed", body)
        self.assertNotIn("images", body)

    def test_all_input_images_encode_before_first_upload(self):
        broken = torch.zeros(2, 8, 8, 3)
        with patch.object(nodes, "upload_media") as upload:
            for cls, kwargs in ((nodes.Kling4LongImage, {"prompt": "Test", "image1": IMAGE, "image2": broken}),
                                (nodes.Miora3D, {"image1": IMAGE, "image2": broken})):
                with self.assertRaises(client.SeedanceAPIError):
                    cls().execute(api_config=CONFIG, **kwargs)
            upload.assert_not_called()


class AudioAndVideoTests(unittest.TestCase):
    def test_gemini_catalog_and_text_boundaries(self):
        self.assertEqual(len(set(spec.GEMINI_VOICES)), 30)
        for model in spec.GEMINI_TTS:
            body = spec.gemini_tts({"model": model, "voice": "kOrE", "prompt": "hello", "instructions": "Speak slowly."}, True)
            self.assertEqual(body, {"model": model, "prompt": "hello",
                                    "metadata": {"voice": "Kore", "instructions": "Speak slowly.", "format": "wav"}})
        for args in ({"voice": "bad"}, {"prompt": "A" * 5001}, {"instructions": "A" * 1001}, {"prompt": ""}):
            with self.assertRaises(client.SeedanceAPIError):
                spec.gemini_tts({"prompt": "hello", **args}, True)
        self.assertTrue(nodes.Gemini25TTS.SEEDANCE_CACHE_ONLY_SEED)

    def test_heygen_text_and_audio_fields_never_mix(self):
        body = spec.heygen({"prompt": "Hi there.", "seed": 42, "seconds": "10"}, True)
        self.assertEqual(set(body), {"model", "prompt", "metadata"})
        self.assertEqual(body["metadata"]["voice"], "Warm Pro Narrator")
        self.assertEqual(body["metadata"]["avatar"], "Abigail Sofa Front")
        for kwargs in ({"audio": AUDIO}, {"audio_url": "https://example.test/speech.m4a"}):
            body = spec.heygen({"prompt": "x" * 6000, "voice": "", **kwargs}, True)
            self.assertNotIn("prompt", body)
            self.assertNotIn("voice", body["metadata"])
        for values in ({"audio_url": "http://example.test/a.mp3"}, {"audio": AUDIO, "audio_url": "https://example.test/a.wav"},
                       {"ratio": "21:9"}, {"motion_prompt": "A" * 1201}):
            with self.assertRaises(client.SeedanceAPIError):
                spec.heygen({"prompt": "hello", **values}, True)

    def test_wf_and_jy_require_images_and_have_distinct_media_caps(self):
        kwargs = {"image1": IMAGE, "prompt": "<Picture 1> turns.", "ratio": "2:3"}
        for kind in ("wf", "jy"):
            body, inputs = h3_token.plan(kind, kwargs, True)
            self.assertEqual(body["metadata"], {"ratio": "2:3"})
            self.assertEqual(body["seconds"], "5")
            self.assertEqual(len(inputs["images"]), 1)
            for change in ({"image1": None}, {"image7": IMAGE}, {"audio4": AUDIO}, {"seconds": "3"}):
                with self.assertRaises(client.SeedanceAPIError):
                    h3_token.plan(kind, {**kwargs, **change}, True)
        with self.assertRaises(client.SeedanceAPIError):
            h3_token.plan("wf", {**kwargs, "video1": object()}, True)
        self.assertEqual(h3_token.plan("jy", {**kwargs, "video_urls": "https://example.test/v.mp4"}, True)[0]["metadata"]["video_url"],
                         ["https://example.test/v.mp4"])

    def test_character_frame_and_second_modes_are_exclusive(self):
        values = {"image1": IMAGE, "prompt": "<Picture 1>", "video_urls": "https://example.test/v.mp4"}
        body, _ = h3_token.plan("charswap", {**values, "duration_mode": "frames", "frames": 22, "seconds": "5"}, True)
        self.assertEqual(body["metadata"]["frames"], 22)
        self.assertNotIn("seconds", body)
        body, _ = h3_token.plan("charswap", {**values, "frames": 362, "seconds": "15", "seed": 6}, True)
        self.assertNotIn("frames", body["metadata"])
        self.assertNotIn("seed", body["metadata"])
        for invalid in ({"ratio": "1:1"}, {"video_urls": ""}, {"audio1": AUDIO}, {"duration_mode": "frames", "frames": 23}, {"image6": IMAGE}):
            with self.assertRaises(client.SeedanceAPIError):
                h3_token.plan("charswap", {**values, **invalid}, True)

    def test_digital_human_duration_covers_driving_audio(self):
        values = {"image1": IMAGE, "audio1": AUDIO, "seconds": "3", "prompt": "<Picture 1> speaks."}
        body, inputs = h3_token.plan("digital", values, True)
        self.assertEqual(body["seconds"], "3")
        self.assertEqual(len(h3_token.encode("digital", body, inputs)), 2)
        for changes in ({"audio1": None}, {"image2": IMAGE}, {"audio2": AUDIO}, {"video1": object()}):
            with self.assertRaises(client.SeedanceAPIError):
                h3_token.plan("digital", {**values, **changes}, True)
        with patch.object(nodes, "upload_media") as upload, self.assertRaisesRegex(client.SeedanceAPIError, "cover"):
            nodes.MinimaxH3DigitalHumanToken().execute(**{**values, "audio1": {
                "waveform": torch.zeros(1, 1, 24001), "sample_rate": 8000}}, api_config=CONFIG)
        upload.assert_not_called()

    def test_h3_packet_references_and_native_wrappers(self):
        classes = ("Minimax_H3_ComfyUI_Max_10020_Token", "Minimax_H3_ComfyUI_Max_10021_Token",
                   "Minimax_H3_ComfyUI_CharSwap_Token", "Minimax_H3_ComfyUI_Digital_Human_Token", "HeyGen_Avatar_6",
                   "Kling_V4_Long_Image")
        for key in classes:
            wrapper = plugin.NODE_CLASS_MAPPINGS[f"SeedanceConcurrent_{key}_Submit"]
            self.assertFalse(hasattr(wrapper, "VALIDATE_INPUTS"))
            self.assertTrue(nodes.NODE_CLASS_MAPPINGS[key].SEEDANCE_CACHE_ONLY_SEED)
        final = {"data": {"result_url": "https://example.test/video.mp4"}}
        with patch.object(nodes, "upload_media", side_effect=[URL, "https://example.test/voice.wav"]), \
                patch.object(nodes, "submit_legacy_video_task", return_value="test") as submit, \
                patch.object(nodes, "poll_legacy_video_task", return_value=final), \
                patch.object(nodes, "extract_legacy_video_url", return_value=final["data"]["result_url"]), \
                patch.object(nodes, "download_video", return_value="video"):
            result = nodes.MinimaxH3DigitalHumanToken().execute(prompt="<Picture 1> speaks.",
                image1=IMAGE, audio1=AUDIO, seed=123, api_config=CONFIG)["result"]
        self.assertEqual(result[0], "video")
        self.assertEqual(submit.call_args.args[0]["metadata"], {"ratio": "16:9", "audio_urls": ["https://example.test/voice.wav"]})
        self.assertEqual(submit.call_args.args[0]["images"], [URL])


class MioraAndExamplesTests(unittest.TestCase):
    def test_miora_input_order_and_mode_payload(self):
        self.assertEqual(spec.MIORA_VIEWS, ["front", "left", "right", "back", "top", "bottom", "front-left", "front-right"])
        body, slots = spec.miora({"image1": IMAGE, "image2": IMAGE, "prompt": "unused",
                                  "generate_type": "geometry", "enable_pbr": True, "face_count": 3000}, True)
        self.assertEqual(body, {"model": "miora-3d", "generate_type": "geometry", "face_count": 3000})
        self.assertEqual([i for i, _ in slots], [1, 2])
        self.assertEqual(spec.miora({"prompt": "A tea cup", "enable_pbr": True}, True)[0]["enable_pbr"], True)
        for args in ({"image2": IMAGE}, {"image1": IMAGE, "image3": IMAGE}, {"image9": IMAGE},
                     {"prompt": ""}, {"prompt": "A cup", "face_count": 2999}):
            with self.assertRaises(client.SeedanceAPIError):
                spec.miora(args, True)

    def test_miora_saves_all_files_and_returns_validated_model(self):
        urls = ["https://example.test/m.glb", "https://example.test/texture.png"]
        final = {"data": {"result_url": urls[0], "data": {"content": {"file_urls": urls}}}}
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "mesh.glb"
            model_path.write_bytes(minimal_glb_bytes())
            with patch.object(nodes, "submit_3d_task", return_value="test"), patch.object(nodes, "poll_3d_task", return_value=final), \
                    patch.object(nodes, "download_file", side_effect=[str(model_path), str(Path(directory) / "texture.png")]) as dl:
                result = nodes.Miora3D().execute(prompt="A vase", api_config=CONFIG)["result"]
            self.assertEqual([c.args[0] for c in dl.call_args_list], urls)
            self.assertEqual(result[0].format, "glb")
            self.assertEqual([item["url"] for item in json.loads(result[5])], urls)

    def test_3d_terminal_fail_reason_survives_transport(self):
        response = Mock(status_code=200)
        response.json.return_value = {"data": {"status": "FAILURE", "fail_reason": "Service unavailable"}}
        with patch.object(client, "_session", return_value=Mock(get=Mock(return_value=response))), \
                patch.object(client, "cooperative_sleep"), self.assertRaisesRegex(client.SeedanceAPIError, "Service unavailable"):
            client.poll_3d_task("test", CONFIG)

    def test_llm_catalog_additions_keep_existing_default(self):
        entries = ["zhenzhen/gm-4-" + name for name in ("hydrogen", "carbon", "neon")] + ["zhenzhen/hy-4-flash"]
        self.assertEqual(llm.MODELS[23:27], entries)
        self.assertEqual(nodes.SeedanceLLMAPI.INPUT_TYPES()["required"]["model"][1]["default"], "qwen/qwen3.8-flash-next")
        for model in entries:
            body = llm.payload({"model": model, "prompt": "Describe this image", "image1": IMAGE, "stream": True})
            self.assertEqual(body["model"], model)
            self.assertEqual(body["messages"][-1]["content"][1]["type"], "image_url")

    def test_blank_key_workflows_and_links(self):
        prefixes = ("kling-v4-long-image-", "heygen-avatar-6-", "miora-3d-", "zhenzhen-gm-2.5-",
                    "zhenzhen-gm-4-hydrogen-", "zhenzhen-gm-4-carbon-", "zhenzhen-gm-4-neon-", "zhenzhen-hy-4-")
        paths = [p for p in (ROOT / "examples").glob("*.json")
                 if p.name.startswith(prefixes) or p.name.startswith("minimax-h3-comfyui-") and "-token" in p.name]
        self.assertEqual(len(paths), 21)
        for path in paths:
            raw = path.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"sk-[A-Za-z0-9_-]{20,}|task_[A-Za-z0-9]{14,}", raw))
            graph = json.loads(raw)
            by_id = {n["id"]: n for n in graph["nodes"]}
            self.assertEqual(next(n for n in by_id.values() if n["type"] == "Seedance_Config")["widgets_values"][1], "")
            for link_id, origin, slot, target, target_slot, kind in graph["links"]:
                self.assertIn(link_id, by_id[origin]["outputs"][slot]["links"])
                self.assertEqual(by_id[target]["inputs"][target_slot]["link"], link_id)
                self.assertIn(by_id[target]["inputs"][target_slot]["type"], (kind, "*"))
