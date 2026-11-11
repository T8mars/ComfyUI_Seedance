import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PIL import Image
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import nodes, concurrent_nodes
from ComfyUI_Seedance.core import h3_turbo as api
from ComfyUI_Seedance.core.client import SeedanceAPIError

IMAGE = torch.zeros(1, 8, 8, 4)
AUDIO = {"waveform": torch.zeros(1, 1, 800), "sample_rate": 8000}
CLASSES = {"video": nodes.MinimaxH3ComfyUIMax, "minimax_image": nodes.MinimaxH3Image, "qwen": nodes.QwenImage21Turbo}
KEYS = {"video": "Minimax_H3_ComfyUI_Max", "minimax_image": "Minimax_H3_Image", "qwen": "Qwen_Image_2_1_Turbo"}
CONFIG = {"api_key": "sk-test", "base_url": "https://example.com"}


class H3TurboTests(unittest.TestCase):
    def tearDown(self):
        concurrent_nodes.shutdown_concurrent_pools(wait=True)

    def test_three_independent_registered_nodes_and_concurrent_wrappers(self):
        for kind, cls in CLASSES.items():
            self.assertIs(nodes.NODE_CLASS_MAPPINGS[KEYS[kind]], cls)
            self.assertEqual(cls.INPUT_TYPES()["required"]["resolution"][1]["default"], api.PROFILES[kind]["default"])
            wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS["SeedanceConcurrent_"+KEYS[kind]+"_Submit"]
            self.assertFalse(hasattr(wrapper, "VALIDATE_INPUTS"))
            self.assertEqual(wrapper.CONCURRENT_KIND, "video" if kind == "video" else "image")
            self.assertEqual(len(cls.RETURN_TYPES), 4)
            schema = cls.INPUT_TYPES()
            self.assertFalse(schema["optional"]["skip_error"][1]["default"])
            seed = schema["optional"].get("seed") or schema["required"]["seed"]
            self.assertTrue(seed[1]["control_after_generate"])
            self.assertEqual(cls.SEEDANCE_CACHE_ONLY_SEED, kind == "video")

    def test_defaults_exact_payload_no_unsupported_fields(self):
        video = api.payload("video", {"prompt": "  animate  ", "seed": 123, "generate_audio": True}, [])
        self.assertEqual(video, {"model": "minimax-h3-comfyui-max", "prompt": "animate", "seconds": "5", "metadata": {"resolution": "480p", "ratio": "16:9"}})
        for kind in ("qwen", "minimax_image"):
            result = api.payload(kind, {"prompt": "draw", "seed": -1, "n": 7, "unknown": True}, [])
            self.assertEqual(set(result), {"model", "prompt", "metadata"})
            self.assertNotIn("seed", result["metadata"])
            self.assertNotIn("n", result)
            self.assertEqual("output_format" in result["metadata"], kind == "minimax_image")

    def test_video_all_resolutions_seconds_and_only_two_ratios(self):
        for resolution in api.PROFILES["video"]["resolutions"]:
            for seconds in ("3", "15"):
                self.assertTrue(api.validate("video", {"resolution": resolution, "seconds": seconds, "ratio": "9:16"}))
        for kwargs in ({"resolution": "1080p"}, {"ratio": "1:1"}, {"seconds": "2"}, {"seconds": "16"}, {"seconds": 3}, {"seconds": "3.5"}):
            with self.assertRaises(SeedanceAPIError):
                api.validate("video", kwargs)

    def test_prompt_connections_deferred_and_types(self):
        for kind, cls in CLASSES.items():
            self.assertIs(cls.VALIDATE_INPUTS(), True)
            self.assertIsNot(cls.VALIDATE_INPUTS(prompt=12), True)
            with self.assertRaisesRegex(SeedanceAPIError, "prompt"):
                api.validate(kind, {"prompt": "  "}, strict=True)

    def test_qwen_utf8_limit_not_character_count(self):
        self.assertTrue(api.validate("qwen", {"prompt": "中"*2730+"ab"}, strict=True))
        for text in ("a"*8193, "中"*2731, "😀"*2049):
            with self.assertRaisesRegex(SeedanceAPIError, "8192 UTF-8"):
                api.validate("qwen", {"prompt": text}, strict=True)
        self.assertTrue(api.validate("minimax_image", {"prompt": "a"*9000}, strict=True))

    def test_qwen_720p_edit_only_and_no_guessed_output_format(self):
        self.assertTrue(api.validate("qwen", {"resolution": "720p"}))
        with self.assertRaisesRegex(SeedanceAPIError, "720p"):
            api.payload("qwen", {"prompt": "draw", "resolution": "720p"}, [])
        result = api.payload("qwen", {"prompt": "edit", "resolution": "720p", "image1": IMAGE, "output_format": "png"}, ["https://example.com/a.png"])
        self.assertEqual(result["metadata"], {"resolution": "720p", "ratio": "1:1"})

    def test_seed_zero_maximum_and_random_omission(self):
        for kind in ("qwen", "minimax_image"):
            for seed in (0, 2147483647):
                self.assertEqual(api.payload(kind, {"prompt": "draw", "seed": seed}, [])["metadata"]["seed"], seed)
            for seed in (-2, 2147483648, True, 1.5, "1"):
                with self.assertRaisesRegex(SeedanceAPIError, "seed"):
                    api.validate(kind, {"seed": seed})

    def test_reference_caps_16_4_9_and_ordered_sparse_slots(self):
        for kind, spec in api.PROFILES.items():
            values = {f"image{i}": IMAGE for i in range(1, spec["images"]+1)}
            self.assertTrue(api.validate(kind, values))
            with self.assertRaisesRegex(SeedanceAPIError, "reference images"):
                api.validate(kind, {**values, f"image{spec['images']+1}": IMAGE})
        data = api.encode_media("minimax_image", {"prompt": "edit", "image16": IMAGE, "image2": IMAGE})
        self.assertEqual([item[0] for item in data], ["image2", "image16"])
        with Image.open(io.BytesIO(data[0][1])) as image:
            self.assertEqual(image.mode, "RGBA")

    def test_all_images_are_validated_before_any_upload(self):
        for bad in (torch.zeros(2, 8, 8, 3), torch.zeros(1, 8, 8, 1), torch.full((1, 8, 8, 3), float("nan"))):
            with patch.object(nodes, "upload_media") as upload:
                with self.assertRaises(SeedanceAPIError):
                    nodes.MinimaxH3Image().execute(prompt="edit", image1=IMAGE, image16=bad)
                upload.assert_not_called()

    def test_video_per_image_and_total_image_limits_before_upload(self):
        for unit, count, message in ((1, 1, "10 MiB"), (10, 9, "50 MiB")):
            with patch.object(api, "MIB", unit), patch.object(nodes, "upload_media") as upload:
                with self.assertRaisesRegex(SeedanceAPIError, message):
                    nodes.MinimaxH3ComfyUIMax().execute(prompt="animate", **{f"image{i}": IMAGE for i in range(1,count+1)})
                upload.assert_not_called()

    def test_three_audio_inputs_order_and_payload_location(self):
        with patch.object(api, "audio_to_wav_bytes", return_value=b"wav"):
            encoded = api.encode_media("video", {"prompt": "animate", "audio3": AUDIO, "audio1": AUDIO})
        self.assertEqual([item[0] for item in encoded], ["audio1", "audio3"])
        result = api.payload("video", {"prompt": "animate", "seconds": "3", "seed": 7}, [], ["https://example.com/1.wav", "https://example.com/3.wav"])
        self.assertEqual(result["metadata"]["audio_urls"], ["https://example.com/1.wav", "https://example.com/3.wav"])
        self.assertNotIn("seed", result["metadata"])
        with self.assertRaises(SeedanceAPIError):
            api.validate("video", {"audio4": AUDIO})

    def test_audio_total_and_bad_audio_fail_before_image_upload(self):
        bad_values = ({"waveform": torch.zeros(2,1,8), "sample_rate": 8000}, {"waveform": torch.ones(1,1,8)*float("nan"), "sample_rate": 8000})
        for bad in bad_values:
            with patch.object(nodes, "upload_media") as upload:
                with self.assertRaises(SeedanceAPIError):
                    nodes.MinimaxH3ComfyUIMax().execute(prompt="animate", image1=IMAGE, audio1=bad)
                upload.assert_not_called()
        with patch.object(api, "MIB", 1), patch.object(api, "audio_to_wav_bytes", return_value=b"x"*6):
            with self.assertRaisesRegex(SeedanceAPIError, "10 MiB"):
                api.encode_media("video", {"prompt": "animate", "audio1": AUDIO, "audio2": AUDIO})

    def test_every_node_uses_correct_submit_poll_download_and_input_order(self):
        for kind, cls in CLASSES.items():
            video = kind == "video"
            final = {"data": {"status": "SUCCESS", "result_url": "https://example.com/result"}}
            with patch.object(nodes, "get_config", return_value=CONFIG), patch.object(nodes, "upload_media", side_effect=lambda data, name, *a, **kw: "https://example.com/"+name) as upload, patch.object(nodes, "submit_legacy_video_task" if video else "submit_image_task", return_value="example-task") as submit, patch.object(nodes, "poll_legacy_video_task" if video else "poll_image_task", return_value=final) as poll, patch.object(nodes, "download_video" if video else "download_image", return_value=IMAGE) as download, patch.object(api, "audio_to_wav_bytes", return_value=b"wav"):
                result = cls().execute(prompt="animate", image3=IMAGE, image1=IMAGE, seed=0, **({"audio1": AUDIO} if video else {}))["result"]
            self.assertIs(result[0], IMAGE)
            self.assertEqual(result[2], "example-task")
            self.assertEqual(submit.call_args.args[0]["images"], ["https://example.com/image1.png", "https://example.com/image3.png"])
            self.assertEqual("seed" in submit.call_args.args[0]["metadata"], not video)
            self.assertEqual(upload.call_count, 3 if video else 2)
            poll.assert_called_once()
            download.assert_called_once()

    def test_skip_error_defaults_raise_and_enabled_returns_typed_placeholder(self):
        for cls in CLASSES.values():
            with patch.object(cls, "_execute_inner", side_effect=RuntimeError("example failure")):
                with self.assertRaises(RuntimeError):
                    cls().execute()
                self.assertEqual(len(cls().execute(skip_error=True)["result"]), 4)

    def test_concurrent_strict_validation_before_future_and_skipped_sibling(self):
        wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS["SeedanceConcurrent_Qwen_Image_2_1_Turbo_Submit"]
        with patch.object(concurrent_nodes, "_submit_original") as submit:
            with self.assertRaises(SeedanceAPIError):
                wrapper().submit(prompt="draw", resolution="720p")
            submit.assert_not_called()
        with patch.object(nodes.QwenImage21Turbo, "_execute_inner", side_effect=lambda **kw: (_ for _ in ()).throw(RuntimeError("example")) if kw["prompt"] == "fail" else {"result": (IMAGE, "url", "example", "{}") } ):
            failed = wrapper().submit(prompt="fail", skip_error=True)[0]
            good = wrapper().submit(prompt="good")[0]
            self.assertIsNotNone(failed.future.result(timeout=10))
            self.assertIsNotNone(good.future.result(timeout=10))

    def test_eight_workflows_have_blank_keys_and_native_save_nodes(self):
        examples = [p for p in (ROOT/"examples").glob("*.json") if p.name.startswith(("minimax-h3-comfyui-max", "minimax-h3-image", "qwen-image-2.1-turbo"))]
        self.assertEqual(len(examples), 8)
        for path in examples:
            graph = json.loads(path.read_text(encoding="utf-8"))
            config = next(n for n in graph["nodes"] if n["type"] == "Seedance_Config")
            self.assertEqual(config["widgets_values"][1], "")
            self.assertTrue(any(n["type"] == ("SaveVideo" if "comfyui-max" in path.name else "SaveImage") for n in graph["nodes"]))
