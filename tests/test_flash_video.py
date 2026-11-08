import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import nodes, concurrent_nodes as parallel
from ComfyUI_Seedance.core import client, flash_video


class FlashVideoTests(unittest.TestCase):
    def tearDown(self):
        parallel.shutdown_concurrent_pools(wait=True)

    def test_profiles_and_exact_payloads(self):
        for model in flash_video.PROFILES:
            kwargs = {"prompt": "Robot waves", "seconds": 3, "seed": 42, "watermark": "enabled",
                      "generation_type": "reference", "nsfw_check": True}
            expected = {"model": model, "prompt": "Robot waves", "seconds": "3", "resolution": "720p", "aspect_ratio": "16:9"}
            self.assertEqual(flash_video.payload(model, kwargs, {}), expected)
            self.assertEqual(flash_video.payload(model, kwargs, {"images": ["https://example.com/a.png"]}),
                             dict(expected, images=["https://example.com/a.png"]))
            self.assertEqual(flash_video.payload(model, kwargs, {"videos": ["https://example.com/a.mp4"]}),
                             dict(expected, metadata={"video_url": ["https://example.com/a.mp4"]}))

    def test_integer_durations_and_distinct_tiers(self):
        for model, maximum in ((flash_video.KLING_MODEL, 20), (flash_video.OMNI_MODEL, 15)):
            for seconds in (3, maximum):
                flash_video.validate(model, {"seconds": seconds})
            for seconds in (2, maximum + 1, True, 3.5, "3"):
                with self.assertRaises(client.SeedanceAPIError):
                    flash_video.validate(model, {"seconds": seconds})
        for resolution in ("360p", "1080p", "4k"):
            flash_video.validate(flash_video.OMNI_MODEL, {"resolution": resolution})
            with self.assertRaises(client.SeedanceAPIError):
                flash_video.validate(flash_video.KLING_MODEL, {"resolution": resolution})
        for ratio in ("1:1", "21:9"):
            flash_video.validate(flash_video.KLING_MODEL, {"ratio": ratio})
            with self.assertRaises(client.SeedanceAPIError):
                flash_video.validate(flash_video.OMNI_MODEL, {"aspect_ratio": ratio})

    def test_reference_limits_and_exclusive_media(self):
        images = {f"image{i}": object() for i in range(1, 11)}
        for model in flash_video.PROFILES:
            flash_video.validate(model, images)
            with self.assertRaises(client.SeedanceAPIError):
                flash_video.validate(model, dict(images, image11=object()))
            maximum = flash_video.PROFILES[model]["videos"]
            urls = "\n".join(f"https://example.com/{i}.mp4" for i in range(maximum))
            flash_video.validate(model, {"video_urls": urls})
            for kwargs in (dict(images, video1=object()), {"video_urls": urls, "video1": object()},
                           {"video_urls": "file:///bad.mp4"}, {"video_urls": "[bad"}, {"video_urls": "{}"}):
                with self.assertRaises(client.SeedanceAPIError):
                    flash_video.validate(model, kwargs)

    def test_kling_legacy_default_and_appended_selector(self):
        schema = nodes.Kling4Omni.INPUT_TYPES()
        self.assertEqual(list(schema["optional"])[-4:], ["api_config", "skip_error", "seed", "model"])
        self.assertEqual(schema["optional"]["model"][1]["default"], "kling-v4-omni")
        self.assertIs(nodes.Kling4Omni.VALIDATE_INPUTS(strict=True, prompt="Robot waves"), True)
        payload = nodes.Kling4Omni().build_payload({"prompt": "Robot waves"}, {})
        self.assertEqual(payload["model"], "kling-v4-omni")
        self.assertIn("metadata", payload)
        for model in ("bad", flash_video.OMNI_MODEL):
            self.assertIsNot(nodes.Kling4Omni.VALIDATE_INPUTS(model=model), True)

    def test_g26_version_after_legacy_seed(self):
        schema = nodes.ZhenzhenImageG26.INPUT_TYPES()
        self.assertEqual(list(schema["optional"])[-4:], ["api_config", "skip_error", "seed", "version"])
        self.assertEqual(len([key for key in schema["optional"] if key.startswith("image")]), 16)
        self.assertEqual(len(nodes.ZhenzhenImageG26.RETURN_TYPES), 8)

    def test_flash_rejects_unsupported_ids_and_prompt_types(self):
        for kwargs in ({"prompt": 123}, {"image_element_ids": "element-test"}, {"voice_ids": "voice-test"},
                       {"video_element_ids": "video-test"}, {"prompt": " "}):
            with self.assertRaises(client.SeedanceAPIError):
                flash_video.validate(flash_video.KLING_MODEL, kwargs, strict=True)
        flash_video.validate(flash_video.KLING_MODEL, {}, strict=False)

    def test_preflight_stops_before_upload_or_future(self):
        for key in ("Kling_V4_Omni", "Zhenzhen_Video_G_Omni_1_2_Flash_Lowprice"):
            cls = nodes.NODE_CLASS_MAPPINGS[key]
            wrapper = parallel.CONCURRENT_NODE_CLASS_MAPPINGS[f"SeedanceConcurrent_{key}_Submit"]
            kwargs = {"prompt": "Robot waves", "image1": object(), "video1": object()}
            if key == "Kling_V4_Omni":
                kwargs["model"] = flash_video.KLING_MODEL
            self.assertEqual(cls.INPUT_TYPES(), wrapper.INPUT_TYPES())
            self.assertFalse(hasattr(wrapper, "VALIDATE_INPUTS"))
            with patch.object(nodes, "upload_media") as upload, patch.object(parallel, "_submit_original") as worker:
                with self.assertRaises(client.SeedanceAPIError):
                    wrapper().submit(**kwargs)
                upload.assert_not_called()
                worker.assert_not_called()

    def test_last_reference_encoded_before_any_upload(self):
        kwargs = {"prompt": "Robot waves", "image1": torch.zeros(1, 16, 16, 3), "image10": torch.zeros(2, 16, 16, 3)}
        with patch.object(nodes, "upload_media") as upload:
            with self.assertRaises(client.SeedanceAPIError):
                nodes.ZhenzhenVideoGOmni12FlashLowprice().collect_media(kwargs, {}, lambda value: None)
            upload.assert_not_called()

    def test_flash_and_legacy_use_their_own_endpoints(self):
        for flash in (False, True):
            with patch.object(nodes, "get_config", return_value={}), \
                 patch.object(nodes.Kling4Omni, "collect_media", return_value={}), \
                 patch.object(nodes, "submit_task", return_value="fixture") as current, \
                 patch.object(nodes, "poll_task", return_value={}), \
                 patch.object(nodes, "extract_video_url", return_value="https://example.com/out.mp4"), \
                 patch.object(nodes, "submit_legacy_video_task", return_value="fixture") as legacy, \
                 patch.object(nodes, "poll_legacy_video_task", return_value={}), \
                 patch.object(nodes, "extract_legacy_video_url", return_value="https://example.com/out.mp4"), \
                 patch.object(nodes, "download_video", return_value="video"):
                result = nodes.Kling4Omni().execute(prompt="Robot waves", seed=42,
                    model=flash_video.KLING_MODEL if flash else "kling-v4-omni")
            self.assertEqual(len(result["result"]), 4)
            self.assertEqual((current.call_count, legacy.call_count), (1, 0) if flash else (0, 1))
            self.assertNotIn("seed", (current if flash else legacy).call_args.args[0])

    def test_local_and_url_video_order_without_legacy_duration_cap(self):
        kwargs = {"prompt": "Robot waves", "model": flash_video.KLING_MODEL, "video2": "two", "video1": "one",
                  "video_urls": "https://example.com/last.mp4"}
        with patch.object(nodes, "video_to_bytes", side_effect=[(b"one", "mp4"), (b"two", "mp4")]), \
             patch.object(nodes.kling_v4, "validate_local_video", return_value={"duration": 20}), \
             patch.object(nodes, "upload_media", side_effect=["https://example.com/one.mp4", "https://example.com/two.mp4"]):
            media = nodes.Kling4Omni().collect_media(kwargs, {}, lambda value: None)
        self.assertEqual(media["videos"], ["https://example.com/one.mp4", "https://example.com/two.mp4", "https://example.com/last.mp4"])

    def test_examples_are_connected_and_key_free(self):
        paths = [path for prefix in (flash_video.KLING_MODEL, flash_video.OMNI_MODEL)
                 for path in (ROOT / "examples").glob(prefix + "*.json")]
        self.assertEqual(len(paths), 8)
        for path in paths:
            source = path.read_text(encoding="utf-8")
            workflow = json.loads(source)
            config = next(node for node in workflow["nodes"] if node["type"] == "Seedance_Config")
            self.assertEqual(config["widgets_values"][1], "")
            by_id = {node["id"]: node for node in workflow["nodes"]}
            for link, origin, slot, target, target_slot, kind in workflow["links"]:
                self.assertIn(link, by_id[origin]["outputs"][slot]["links"])
                self.assertEqual(by_id[target]["inputs"][target_slot]["link"], link)
            self.assertNotRegex(source, r"sk-[A-Za-z0-9]{12,}|X-Amz-Signature")


if __name__ == "__main__":
    unittest.main()
