import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import sys
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
import ComfyUI_Seedance as plugin
from ComfyUI_Seedance import concurrent_nodes, nodes
from ComfyUI_Seedance.core import client, image_nov19 as image, llm, qwen_audio31 as tts


CONFIG = {"base_url": "https://example.test", "api_key": "sk-test"}
REF = torch.zeros(1, 320, 320, 3)
AUDIO = {"waveform": torch.zeros(1, 1, 800), "sample_rate": 8000}


class ImageContract(unittest.TestCase):
    def test_kling_independent_count_and_group_are_mutually_exclusive(self):
        body = image.payload("kling", {"prompt": " teapot ", "n": 9, "resolution": "4K"})
        self.assertEqual(body, {"model": "kling-v4-image", "prompt": "teapot", "nsfw_check": False,
            "size": "auto", "resolution": "4k", "n": 9, "sequential_image_generation": "disabled"})
        grouped = image.payload("kling", {"prompt": "Views", "n": 9, "max_images": 4, "sequential_image_generation": "auto"})
        self.assertNotIn("n", grouped)
        self.assertEqual(grouped["sequential_image_generation_options"], {"max_images": 4})
        for values in ({"n": 10}, {"sequential_image_generation": "auto", "max_images": 1},
                       {"size": "2048x2048"}, {"resolution": "1k"}, {"nsfw_check": "false"}):
            with self.subTest(values=values), self.assertRaises(client.SeedanceAPIError):
                image.payload("kling", {"prompt": "Tea", **values})

    def test_kling_mixed_prompt_budget_and_missing_reference(self):
        image.payload("kling", {"prompt": "a" * 25000 + "\u8336" * 10500})
        for prompt in ("a" * 25000 + "\u8336" * 10501, "@Image2 only"):
            with self.assertRaises(client.SeedanceAPIError):
                image.payload("kling", {"prompt": prompt}, ["https://example.test/1.png"])

    def test_kling_validates_full_set_before_first_upload(self):
        image.encode_references("kling", {f"image{i}": REF for i in range(1, 11)})
        for bad in (torch.zeros(1, 299, 320, 3), torch.zeros(1, 300, 751, 3), torch.zeros(2, 320, 320, 3)):
            with patch.object(nodes, "upload_media") as upload, self.assertRaises(client.SeedanceAPIError):
                nodes.Kling4Image().execute(prompt="Tea", image1=REF, image2=bad, api_config=CONFIG)
            upload.assert_not_called()
        with self.assertRaises(client.SeedanceAPIError):
            image.encode_references("kling", {"image11": REF})

    def test_kling_preserves_all_images_in_url_order_and_list_outputs(self):
        urls = ["https://example.test/a.png", "https://example.test/b.png"]
        final = {"data": {"result_url": urls[0], "data": {"content": {"image_urls": urls}}}}
        tensors = [REF, torch.ones(1, 300, 400, 3)]
        with patch.object(nodes, "submit_image_task", return_value="mock"), patch.object(nodes, "poll_image_task", return_value=final), \
                patch.object(nodes, "download_image", side_effect=tensors) as download:
            images, actual_urls, task, _ = nodes.Kling4Image().execute(
                prompt="Group", sequential_image_generation="auto", api_config=CONFIG)["result"]
        self.assertEqual(images, tensors)
        self.assertEqual(actual_urls, urls)
        self.assertEqual(task, "mock")
        self.assertEqual([call.args[0] for call in download.call_args_list], urls)
        self.assertEqual(nodes.Kling4Image.OUTPUT_IS_LIST, (True, True, False, False))
        self.assertNotIn("Kling_V4_Image", concurrent_nodes.PURE_IMAGE_NODE_KEYS)

    def test_kling_skip_error_keeps_list_shape(self):
        result = nodes.Kling4Image().execute(prompt="", skip_error=True)["result"]
        self.assertEqual(len(result[0]), 1)
        self.assertEqual(result[1], [""])

    def test_mai_uses_pixel_area_and_flooring_or_ratio(self):
        values = {"model": image.MAI_MODELS[1], "prompt": "Tea", "size": "custom_pixels",
                  "width": 2047, "height": 2017, "background": "opaque", "nsfw_check": True}
        body = image.payload("mai", values)
        self.assertEqual((body["width"], body["height"]), (2016, 2016))
        self.assertEqual((body["n"], body["background"], body["nsfw_check"]), (1, "opaque", True))
        self.assertNotIn("resolution", body)
        self.assertEqual(image.payload("mai", {"prompt": "Tea", "size": "custom_ratio", "custom_ratio": "1:4"})["size"], "1:4")
        for change in ({"width": 3000}, {"height": 767}, {"size": "auto"}, {"background": "transparent"},
                       {"size": "custom_ratio", "custom_ratio": "41:10"}, {"size": "1:1", "resolution": "4k"}):
            with self.subTest(change=change), self.assertRaises(client.SeedanceAPIError):
                image.payload("mai", {**values, **change})

    def test_mai_reference_edit_omits_sizing_and_legacy_fields(self):
        body = image.payload("mai", {"prompt": "Tea", "size": "custom_pixels", "width": 1,
            "web_grounding": True, "auto_aspect_ratio": True, "output_format": "jpeg"},
            [f"https://example.test/{i}.png" for i in range(5)])
        self.assertEqual(set(body), {"model", "prompt", "n", "background", "nsfw_check", "images"})
        wrapper = plugin.NODE_CLASS_MAPPINGS["SeedanceConcurrent_MAI_Image_2_7_Submit"]
        self.assertFalse(hasattr(wrapper, "VALIDATE_INPUTS"))
        self.assertEqual(wrapper.INPUT_TYPES(), nodes.MAIImage27.INPUT_TYPES())


class TTSContract(unittest.TestCase):
    def test_documented_voice_profiles_and_no_unrelated_model_changes(self):
        self.assertEqual([len(tts.VOICES[model]) for model in (tts.FLASH, tts.PLUS)], [69, 4])
        for model, voice in tts.VOICES.items():
            self.assertEqual(len(set(voice)), len(voice))
            self.assertEqual(tts.payload({"model": model, "prompt": "hello"})["metadata"]["voice"], voice[0])
        self.assertNotIn(tts.NEXT, tts.VOICES)
        self.assertNotIn(tts.FLASH, nodes.QWEN3_TTS_MODELS)

    def test_system_payload_seed_and_supported_fields(self):
        body = tts.payload({"prompt": " Hello ", "seed": 0, "channels": "1", "language_hint": "en",
                            "instruction": "Calm", "enable_cbr": True})
        self.assertEqual(body["prompt"], " Hello ")
        self.assertEqual(body["seed"], 0)
        self.assertEqual(body["metadata"]["sample_rate"], "22050")
        self.assertEqual(body["metadata"]["instruction"], "Calm")
        self.assertNotIn("enable_cbr", body["metadata"])
        self.assertNotIn("channels", body["metadata"])
        for change in ({"seed": 65536}, {"language_hint": "fr"}, {"voice": tts.VOICES[tts.PLUS][0]},
                       {"output_format": "opus", "sample_rate": "44100"}, {"enable_ssml": True}, {"audio1": AUDIO}):
            with self.subTest(change=change), self.assertRaises(client.SeedanceAPIError):
                tts.payload({"prompt": "Hello", **change})
        ssml = tts.payload({"model": tts.PLUS, "prompt": "<speak>Salut</speak>", "language_hint": "fr", "enable_ssml": True})
        self.assertTrue(ssml["metadata"]["enable_ssml"])
        self.assertNotIn("seed", ssml)

    def test_next_reference_order_defaults_and_mode_specific_fields(self):
        url = "https://example.test/public.wav"
        body = tts.payload({"model": tts.NEXT, "prompt": "@voice1 and @voice2 now speak",
            "audio1": AUDIO, "audio_urls": url, "pitch": 1.6, "voice": "stale", "seed": 2147483647},
            ["https://example.test/uploaded.wav"])
        self.assertEqual(body["metadata"]["audio_urls"], ["https://example.test/uploaded.wav", url])
        self.assertEqual((body["metadata"]["format"], body["metadata"]["sample_rate"], body["metadata"]["channels"]),
                         ("wav", "48000", "2"))
        self.assertNotIn("voice", body["metadata"])
        self.assertNotIn("pitch", body["metadata"])
        self.assertTrue(tts.payload({"model": tts.NEXT, "prompt": "Hello", "output_format": "mp3",
                                     "enable_cbr": True})["metadata"]["enable_cbr"])
        for change in ({"audio_urls": "\n".join([url] * 4)}, {"prompt": "@voice2"}, {"sample_rate": "22050"},
                       {"output_format": "opus"}, {"audio_urls": "https://user:password@example.test/b.wav"}):
            with self.subTest(change=change), self.assertRaises(client.SeedanceAPIError):
                tts.payload({"model": tts.NEXT, "prompt": "Hello", **change})

    def test_invalid_later_audio_is_rejected_before_any_upload(self):
        with patch.object(nodes, "upload_media") as upload, self.assertRaises(client.SeedanceAPIError):
            nodes.QwenAudio31TTS().execute(model=tts.NEXT, prompt="Hello", audio1=AUDIO,
                audio2={"waveform": torch.zeros(1, 1, 240001), "sample_rate": 8000}, api_config=CONFIG)
        upload.assert_not_called()

    def test_next_pcm_metadata_and_stereo_pcm_decode(self):
        with patch.object(nodes, "submit_audio_task", return_value="mock"), patch.object(nodes, "poll_audio_task", return_value={}), \
                patch.object(nodes, "extract_audio_url", return_value="https://example.test/a.pcm"), \
                patch.object(nodes, "download_audio", return_value=(AUDIO, "a.pcm")) as download:
            nodes.QwenAudio31TTS().execute(model=tts.NEXT, prompt="Hello", output_format="pcm", api_config=CONFIG)
        self.assertEqual(download.call_args.kwargs["pcm_channels"], 2)
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "a.pcm"
            file.write_bytes(b"\x00\x40\x00\xc0" * 4)
            out = client._load_pcm_audio(file, 48000, 2)
        self.assertEqual(out["waveform"].shape, (1, 2, 4))
        self.assertTrue(torch.allclose(out["waveform"][0, :, 0], torch.tensor([.5, -.5])))


class WorkflowsAndLLM(unittest.TestCase):
    def test_g62_catalog_and_native_payload(self):
        schema = nodes.SeedanceLLMAPI.INPUT_TYPES()["required"]["model"]
        self.assertEqual(schema[1]["default"], "qwen/qwen3.8-flash-next")
        for model in ("zhenzhen/g6.2-astra", "zhenzhen/g6.2-sol"):
            self.assertIn(model, schema[0])
            self.assertEqual(llm.payload({"model": model, "prompt": "Hello"})["model"], model)

    def test_13_new_examples_are_linked_and_have_blank_keys(self):
        starts = ("kling-v4-image-", "mai-image-2-7-", "qwen-audio-3.1-tts-", "zhenzhen-g6.2-")
        examples = [path for path in (ROOT / "examples").glob("*.json") if path.name.startswith(starts)]
        self.assertEqual(len(examples), 13)
        for path in examples:
            raw = path.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"sk-[A-Za-z0-9_-]{20,}", raw))
            graph = json.loads(raw)
            by_id = {node["id"]: node for node in graph["nodes"]}
            self.assertEqual(next(n for n in by_id.values() if n["type"] == "Seedance_Config")["widgets_values"][1], "")
            for id_, src, out, dst, slot, kind in graph["links"]:
                output, target = by_id[src]["outputs"][out], by_id[dst]["inputs"][slot]
                self.assertIn(id_, output["links"])
                self.assertEqual(id_, target["link"])
                self.assertEqual(kind, output["type"])
                self.assertIn(target["type"], (kind, "*"))
