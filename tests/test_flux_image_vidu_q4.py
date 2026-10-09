import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import concurrent_nodes, nodes
from ComfyUI_Seedance.core import client, media

CONFIG = {"base_url": "https://api.seedance.nz", "api_key": "sk-test"}
IMAGE = torch.zeros((1, 16, 16, 3))
AUDIO = {"waveform": torch.zeros((1, 1, 24000)), "sample_rate": 24000}


class Flux3ImageTests(unittest.TestCase):
    def arguments(self, **changes):
        return {"prompt": "A red teapot", "resolution": "768sq", "aspect_ratio": "1:1",
                "grounding": True, "safety_tolerance": 2, **changes}

    def test_documented_payload_and_cache_seed(self):
        payload = nodes.Flux3Image().build_payload(self.arguments(seed=42), ["https://cdn.test/ref.png"])
        self.assertEqual(payload, {
            "model": "flux-3-image", "prompt": "A red teapot", "resolution": "768sq",
            "aspect_ratio": "1:1", "grounding": True, "safety_tolerance": 2, "n": 1,
            "images": ["https://cdn.test/ref.png"],
        })
        self.assertNotIn("images", nodes.Flux3Image().build_payload(self.arguments(), []))
        self.assertTrue(nodes.Flux3Image.SEEDANCE_CACHE_ONLY_SEED)
        self.assertIn("Flux_3_Image", concurrent_nodes.PURE_IMAGE_NODE_KEYS)

    def test_preflight_limits_and_linked_prompt(self):
        self.assertIs(nodes.Flux3Image.VALIDATE_INPUTS(**self.arguments(prompt=None)), True)
        for changes in ({"prompt": ""}, {"resolution": "720p"}, {"aspect_ratio": "custom"},
                        {"safety_tolerance": 5}, {"safety_tolerance": 1.5}):
            with self.subTest(changes=changes):
                self.assertIsNot(nodes.Flux3Image.VALIDATE_INPUTS(**self.arguments(**changes), strict=True), True)
        with self.assertRaises(client.SeedanceAPIError):
            nodes.Flux3Image().build_payload(self.arguments(), ["ref"] * 11)

    def test_execute_uploads_ordered_references_and_downloads(self):
        final = {"data": {"status": "SUCCESS", "result_url": "https://cdn.test/result.png"}}
        with patch.object(nodes, "get_config", return_value=CONFIG), \
             patch.object(nodes, "upload_media", side_effect=["ref1", "ref10"]) as upload, \
             patch.object(nodes, "submit_image_task", return_value="test-task") as submit, \
             patch.object(nodes, "poll_image_task", return_value=final), \
             patch.object(nodes, "download_image", return_value=IMAGE) as download:
            result = nodes.Flux3Image().execute(**self.arguments(), image1=IMAGE, image10=IMAGE, seed=42)
        self.assertEqual(upload.call_count, 2)
        self.assertEqual(submit.call_args.args[0]["images"], ["ref1", "ref10"])
        self.assertNotIn("seed", submit.call_args.args[0])
        download.assert_called_once_with("https://cdn.test/result.png", logger_prefix="flux-3-image")
        self.assertIs(result["result"][0], IMAGE)

    def test_batch_input_is_rejected_before_upload(self):
        with patch.object(nodes, "upload_media") as upload:
            with self.assertRaisesRegex(client.SeedanceAPIError, "one image"):
                nodes.Flux3Image().execute(**self.arguments(), image1=IMAGE.repeat(2, 1, 1, 1))
        upload.assert_not_called()


class ViduQ4Tests(unittest.TestCase):
    def arguments(self, model="vidu-q4-preview-r2v", **changes):
        return {"model": model, "prompt": "The teapot rotates slowly", "seconds": "3",
                "resolution": "540p", "ratio": "16:9", "generate_audio": True,
                "is_rec": True, "watermark": False, **changes}

    def test_all_four_models_and_mode_specific_payloads(self):
        node = nodes.ViduQ4PreviewVideo()
        for model in nodes.VIDU_Q4_MODELS:
            with self.subTest(model=model):
                ref = model.endswith("-r2v")
                payload = node.build_payload(self.arguments(model, seed=42, prompt="prompt" if ref else ""),
                                             {"images": ["image"], "audio_urls": ["audio"]})
                self.assertEqual(payload["model"], model)
                self.assertEqual(payload["seconds"], "3")
                self.assertEqual("ratio" in payload["metadata"], ref)
                self.assertEqual("audio_urls" in payload["metadata"], ref)
                self.assertEqual("prompt" in payload, ref)
                self.assertNotIn("seed", payload["metadata"])
        self.assertTrue(nodes.ViduQ4PreviewVideo.SEEDANCE_CACHE_ONLY_SEED)
        self.assertIn("Vidu_Q4_Preview_Video", concurrent_nodes.PURE_VIDEO_NODE_KEYS)

    def test_reference_limit_order_and_mp3_upload(self):
        arguments = self.arguments(**{f"image{i}": IMAGE for i in range(1, 16)},
                                   audio1=AUDIO, audio_url2="https://cdn.test/reference.mp3", audio3=AUDIO)
        with patch.object(nodes, "audio_to_mp3_bytes", return_value=b"mp3") as encode, \
             patch.object(nodes, "upload_media", side_effect=[f"image{i}" for i in range(1, 16)] + ["audio1", "audio3"]) as upload:
            result = nodes.ViduQ4PreviewVideo().collect_media(arguments, CONFIG, lambda _: None)
        self.assertEqual(result["images"], [f"image{i}" for i in range(1, 16)])
        self.assertEqual(result["audio_urls"], ["audio1", "https://cdn.test/reference.mp3", "audio3"])
        self.assertEqual(encode.call_count, 2)
        self.assertEqual(upload.call_args_list[-1].args[1:3], ("vidu_q4_audio_3.mp3", "audio/mpeg"))

    def test_preflight_rejects_bad_media_before_upload(self):
        cases = [
            self.arguments("vidu-q4-preview-i2v"),
            self.arguments("vidu-q4-preview-i2v", image1=IMAGE, image2=IMAGE),
            self.arguments(image1=IMAGE, audio1=AUDIO, audio_url1="https://cdn.test/ref.mp3"),
            self.arguments(image1=IMAGE, audio_url1="ftp://cdn.test/audio.mp3"),
            self.arguments(image1=IMAGE.repeat(2, 1, 1, 1)),
            self.arguments(image1=IMAGE, audio1={"waveform": torch.zeros((2, 1, 24))}),
            self.arguments(prompt="", image1=IMAGE),
            self.arguments(seconds="2", image1=IMAGE),
            self.arguments(resolution="480p", image1=IMAGE),
        ]
        with patch.object(nodes, "upload_media") as upload:
            for arguments in cases:
                with self.subTest(arguments={key: value for key, value in arguments.items() if key not in ("image1", "image2", "audio1")}):
                    with self.assertRaises(client.SeedanceAPIError):
                        nodes.ViduQ4PreviewVideo().collect_media(arguments, CONFIG, lambda _: None)
        upload.assert_not_called()

    def test_i2v_ignores_inapplicable_audio_and_ratio(self):
        args = self.arguments("vidu-q4-preview-i2v", image1=IMAGE, audio1=AUDIO,
                              audio_url1="invalid", ratio="invalid", prompt="")
        with patch.object(nodes, "upload_media", return_value="image"), \
             patch.object(nodes, "audio_to_mp3_bytes") as encode:
            uploaded = nodes.ViduQ4PreviewVideo().collect_media(args, CONFIG, lambda _: None)
        encode.assert_not_called()
        self.assertEqual(uploaded["audio_urls"], [])
        payload = nodes.ViduQ4PreviewVideo().build_payload(args, uploaded)
        self.assertNotIn("ratio", payload["metadata"])

    def test_execute_uses_legacy_submit_poll_and_download(self):
        final = {"data": {"status": "SUCCESS", "result_url": "https://cdn.test/result.mp4"}}
        with patch.object(nodes, "get_config", return_value=CONFIG), \
             patch.object(nodes, "upload_media", return_value="image"), \
             patch.object(nodes, "submit_legacy_video_task", return_value="test-task") as submit, \
             patch.object(nodes, "poll_legacy_video_task", return_value=final) as poll, \
             patch.object(nodes, "download_video", return_value={"file_path": "result.mp4"}):
            result = nodes.ViduQ4PreviewVideo().execute(**self.arguments(image1=IMAGE), seed=17)
        self.assertEqual(submit.call_args.args[0]["model"], "vidu-q4-preview-r2v")
        self.assertEqual(poll.call_args.args[0], "test-task")
        self.assertEqual(result["result"][1], "https://cdn.test/result.mp4")

    def test_skip_error_preserves_output_contract(self):
        with patch.object(nodes.ViduQ4PreviewVideo, "_execute_inner", side_effect=RuntimeError("test")), \
             patch.object(nodes, "make_error_video", return_value={"file_path": "placeholder.mp4"}):
            result = nodes.ViduQ4PreviewVideo().execute(skip_error=True, seed=3)
        self.assertEqual(len(result["result"]), 4)
        self.assertEqual(result["result"][1:3], ("", ""))


class MP3EncodingTests(unittest.TestCase):
    def test_codec_and_failure_behavior(self):
        with patch.object(client, "_find_ffmpeg", return_value="ffmpeg"), \
             patch.object(media, "audio_to_wav_bytes", return_value=b"wav"), \
             patch.object(media.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=b"mp3")) as run:
            self.assertEqual(media.audio_to_mp3_bytes(AUDIO), b"mp3")
        self.assertIn("libmp3lame", run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs["input"], b"wav")
        with patch.object(client, "_find_ffmpeg", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "FFmpeg"):
                media.audio_to_mp3_bytes(AUDIO)
        for completed in (SimpleNamespace(returncode=1, stdout=b""),
                          SimpleNamespace(returncode=0, stdout=b"")):
            with patch.object(client, "_find_ffmpeg", return_value="ffmpeg"), \
                 patch.object(media, "audio_to_wav_bytes", return_value=b"wav"), \
                 patch.object(media.subprocess, "run", return_value=completed):
                with self.assertRaisesRegex(RuntimeError, "encoding failed"):
                    media.audio_to_mp3_bytes(AUDIO)


class WorkflowTests(unittest.TestCase):
    def test_all_six_examples_preserve_input_slots_and_cache_controls(self):
        files = list((ROOT / "examples").glob("flux-3-image*.json"))
        files += list((ROOT / "examples").glob("vidu-q4-preview*.json"))
        self.assertEqual(len(files), 6)
        for path in files:
            with self.subTest(path=path.name):
                workflow = json.loads(path.read_text(encoding="utf-8"))
                generator = next(node for node in workflow["nodes"] if node["type"] in
                                 ("Flux_3_Image", "Vidu_Q4_Preview_Video"))
                config = next(node for node in workflow["nodes"] if node["type"] == "Seedance_Config")
                self.assertEqual(config["widgets_values"][1], "")
                self.assertEqual(generator["widgets_values"][-3:], [False, 0, "fixed"])
                spec = nodes.NODE_CLASS_MAPPINGS[generator["type"]].INPUT_TYPES()["optional"]
                sockets = [name for name, item in spec.items() if item[0] in ("IMAGE", "AUDIO", "SEEDANCE_CONFIG")]
                self.assertEqual([item["name"] for item in generator["inputs"]], sockets)
                for link in workflow["links"]:
                    if link[3] == generator["id"]:
                        input_slot = generator["inputs"][link[4]]
                        self.assertEqual(input_slot["type"], link[5])
                        self.assertEqual(input_slot["link"], link[0])
                if generator["type"] == "Vidu_Q4_Preview_Video":
                    self.assertIn(generator["widgets_values"][0], nodes.VIDU_Q4_MODELS)
                    reference = generator["widgets_values"][0].endswith("-r2v")
                    self.assertEqual(generator["inputs"][15]["link"] is not None, reference)
                self.assertTrue(any(node["type"] in ("SaveImage", "SaveVideo") for node in workflow["nodes"]))


if __name__ == "__main__":
    unittest.main()
