import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import nodes, concurrent_nodes
from ComfyUI_Seedance.core import client, kling_v4

CONFIG = {"base_url": "https://api.seedance.nz", "api_key": "sk-test"}
URL = "https://cdn.example.com/result.mp4"
CLASSES = (nodes.Kling4TextToVideo, nodes.Kling4ImageToVideo, nodes.Kling4Omni,
           nodes.Kling4CustomElement, nodes.Kling4CustomVoice)


def auxiliary(**values):
    return {"data": {"status": "SUCCESS", "result_text": json.dumps({"results": [
        {"name": name, "text": value, "outputType": "text", "url": None, "zindex": None}
        for name, value in values.items()
    ]})}}


class Kling4Tests(unittest.TestCase):
    def tearDown(self):
        concurrent_nodes.shutdown_concurrent_pools(wait=True)

    def test_frontend_dynamic_modes_and_concurrent_inputs(self):
        executable = shutil.which("node")
        if not executable:
            self.skipTest("Node.js unavailable")
        result = subprocess.run([executable, str(ROOT / "tests" / "kling_v4_ui.mjs")],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_five_independent_nodes_and_cache_controls(self):
        keys = ["Kling_V4_T2V", "Kling_V4_I2V", "Kling_V4_Omni", "Kling_V4_Custom_Element", "Kling_V4_Custom_Voice"]
        for key, cls in zip(keys, CLASSES):
            self.assertIs(nodes.NODE_CLASS_MAPPINGS[key], cls)
            self.assertFalse(cls.INPUT_TYPES()["optional"]["skip_error"][1]["default"])
            self.assertTrue(cls.INPUT_TYPES()["optional"]["seed"][1]["control_after_generate"])
            self.assertTrue(cls.SEEDANCE_CACHE_ONLY_SEED)
            self.assertFalse(hasattr(cls, "IS_CHANGED"))
            if key.endswith(("Element", "Voice")):
                self.assertNotIn(f"SeedanceConcurrent_{key}_Submit", concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS)
            else:
                wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[f"SeedanceConcurrent_{key}_Submit"]
                self.assertEqual(wrapper.INPUT_TYPES(), cls.INPUT_TYPES())
                self.assertFalse(hasattr(wrapper, "VALIDATE_INPUTS"))
                self.assertFalse(issubclass(wrapper, cls))

    def test_prompt_weighted_limits_not_generic_seedance_limit(self):
        for prompt in ("a" * 26000, "中" * 11000, "a" * 13000 + "中" * 5500):
            kling_v4.prompt_valid(prompt, required=True)
        for prompt in ("a" * 26001, "中" * 11001, "a" * 13000 + "中" * 5501):
            with self.assertRaises(client.SeedanceAPIError):
                kling_v4.prompt_valid(prompt)
        with self.assertRaises(client.SeedanceAPIError):
            kling_v4.prompt_valid(" ", required=True)
        kling_v4.validate_video("i2v", {"image1": object()}, strict=True)

    def test_video_payloads_match_the_documented_protocol(self):
        for kind, cls in zip(("t2v", "i2v", "omni"), CLASSES):
            media = {} if kind == "t2v" else {"images": ["https://example.com/front.png"]}
            kwargs = {"prompt": "Keep the subject consistent", "seconds": 3, "resolution": "720p", "ratio": "16:9",
                      "seed": 123, "generate_audio": False, "multi_shot": True, "negative_prompt": "unused"}
            payload = cls().build_payload(kwargs, media)
            expected = {"model": f"kling-v4-{kind}", "prompt": kwargs["prompt"], "seconds": "3",
                        "metadata": {"resolution": "720p"}}
            if kind != "i2v":
                expected["metadata"]["ratio"] = "16:9"
            if kind != "t2v":
                expected["images"] = media["images"]
            self.assertEqual(payload, expected)
        for control, value in (("enabled", True), ("disabled", False)):
            payload = kling_v4.video_payload("t2v", {"prompt": "test", "watermark": control}, {})
            self.assertIs(payload["metadata"]["watermark"], value)

    def test_video_invalid_options_fail_before_submission(self):
        for kwargs in ({"seconds": 2}, {"seconds": 31}, {"seconds": True}, {"seconds": 3.5},
                       {"seconds": "3"}, {"resolution": "4k"}, {"watermark": "off"}, {"ratio": "4:3"}):
            with self.subTest(kwargs=kwargs), patch.object(nodes, "submit_legacy_video_task") as submit:
                with self.assertRaises(client.SeedanceAPIError):
                    nodes.Kling4TextToVideo().execute(api_config=CONFIG, prompt="Test", **kwargs)
                submit.assert_not_called()

    def test_i2v_requires_first_frame_and_never_sends_ratio(self):
        self.assertIs(nodes.Kling4ImageToVideo.VALIDATE_INPUTS(), True)
        self.assertIsNot(nodes.Kling4ImageToVideo.VALIDATE_INPUTS(strict=True, image2=object()), True)
        payload = nodes.Kling4ImageToVideo().build_payload(
            {"prompt": "", "ratio": "invalid stale value"}, {"images": [URL, URL + "?last=1"]})
        self.assertNotIn("prompt", payload)
        self.assertNotIn("ratio", payload["metadata"])
        self.assertEqual(len(payload["images"]), 2)

    def test_omni_keeps_id_and_media_order(self):
        kwargs = {"prompt": "@element_1 follows @1", "image_element_ids": '["image-a", "image-b"]',
                  "video_element_ids": "video-a", "voice_ids": "voice-a\nvoice-b", "ratio": "adaptive"}
        media = {"images": [URL + "?image=1"], "videos": [URL + "?video=1", URL + "?video=2"]}
        payload = nodes.Kling4Omni().build_payload(kwargs, media)
        self.assertEqual(payload["images"], media["images"])
        self.assertEqual(payload["metadata"]["video_url"], media["videos"])
        self.assertEqual(payload["metadata"]["elementIds"], ["image-a", "image-b", "video-a"])
        self.assertEqual(payload["metadata"]["voiceIds"], ["voice-a", "voice-b"])

    def test_omni_cross_material_limits_fail_at_preflight(self):
        cases = [
            {"image_element_ids": json.dumps([str(i) for i in range(8)])},
            {"video_element_ids": "a\nb\nc\nd"}, {"voice_ids": "a\nb\nc\nd"},
            {"video_urls": "\n".join([URL] * 6)},
            {"image_element_ids": "a", "video_element_ids": "a"},
            {**{f"image{i}": object() for i in range(1, 11)}, "video_urls": "\n".join([URL] * 5), "image_element_ids": "a"},
            {"video_urls": "\n".join([URL] * 3), "video_element_ids": "a\nb\nc"},
            {"video_urls": "file:///test.mp4"},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=list(kwargs)), self.assertRaises(client.SeedanceAPIError):
                kling_v4.validate_video("omni", kwargs)
        kling_v4.validate_video("omni", {**{f"image{i}": object() for i in range(1, 11)},
                                        "video_urls": "\n".join([URL] * 5)})

    def test_image_sockets_reject_batches_and_enforce_element_dimensions(self):
        for shape in ((2, 512, 512, 3), (512, 512, 3), (1, 299, 512, 3), (1, 300, 900, 3)):
            with self.subTest(shape=shape), self.assertRaises(client.SeedanceAPIError):
                kling_v4.image_bytes(SimpleNamespace(shape=shape), lambda _: b"png", element=True)
        kling_v4.image_bytes(SimpleNamespace(shape=(1, 300, 750, 3)), lambda _: b"png", element=True)
        with self.assertRaises(client.SeedanceAPIError):
            kling_v4.image_bytes(SimpleNamespace(shape=(1, 300, 300, 3)), lambda _: b"0" * (10 * 1024 * 1024 + 1), element=True)

    def test_element_image_and_video_payloads_drop_inactive_fields(self):
        common = {"element_name": "Robot", "prompt": "A blue robot", "element_voice_id": "voice-demo",
                  "tag_list": '["o_101", "o_108"]'}
        image = nodes.Kling4CustomElement().build_payload(
            {**common, "reference_type": "image_refer", "video_url": "unused"}, {"images": [URL, URL + "?side=1"]})
        self.assertEqual(image["metadata"], {"elementName": "Robot", "referenceType": "image_refer",
                         "elementVoiceId": "voice-demo", "tagList": ["o_101", "o_108"]})
        self.assertNotIn("video_url", image["metadata"])
        video = nodes.Kling4CustomElement().build_payload(
            {**common, "reference_type": "video_refer"}, {"videos": [URL], "images": [URL]})
        self.assertNotIn("images", video)
        self.assertEqual(video["metadata"]["video_url"], [URL])

    def test_element_constraints_and_connected_queue_inputs(self):
        self.assertIs(nodes.Kling4CustomElement.VALIDATE_INPUTS(reference_type="image_refer"), True)
        for kwargs in ({"element_name": "a" * 21}, {"prompt": "a" * 101}, {"tag_list": "o_109"},
                       {"reference_type": "other"}):
            with self.assertRaises(client.SeedanceAPIError):
                kling_v4.validate_element(kwargs)
        with self.assertRaises(client.SeedanceAPIError):
            kling_v4.validate_element({"element_name": "R", "prompt": "Robot", "image1": object()}, strict=True)
        with patch.object(nodes, "upload_media") as upload:
            image = torch.zeros((1, 300, 300, 3))
            with self.assertRaises(client.SeedanceAPIError):
                nodes.Kling4CustomElement().collect_media({"element_name": "R", "prompt": "Robot",
                    "image1": image, "image2": image}, CONFIG, lambda _: None)
            upload.assert_not_called()

    def test_local_video_constraints_use_real_probe_and_upload_limit(self):
        for info in ({"width": 1280, "height": 720, "duration": 3},
                     {"width": 1920, "height": 1080, "duration": 2.99},
                     {"width": 1920, "height": 1080, "duration": 8.01}):
            with patch.object(kling_v4, "probe_video", return_value=info), self.assertRaises(client.SeedanceAPIError):
                kling_v4.validate_local_video(b"video", "mp4", element=True)
        with patch.object(kling_v4, "probe_video", return_value={"width": 1080, "height": 1920, "duration": 3}):
            self.assertEqual(kling_v4.validate_local_video(b"video", "mov", element=True)["duration"], 3)
        large = type("Large", (), {"__len__": lambda self: 51 * 1024 * 1024})()
        with patch.object(kling_v4, "probe_video") as probe, self.assertRaises(client.SeedanceAPIError):
            kling_v4.validate_local_video(large, "mp4")
        probe.assert_not_called()

    def test_voice_modes_are_mutually_exclusive_without_a_prompt(self):
        voice = nodes.Kling4CustomVoice()
        self.assertEqual(voice.build_payload({"voice_name": "Voice", "video_id": "stale"}, {"audio_url": URL}),
                         {"model": "kling-v4-custom-voice", "metadata": {"voiceName": "Voice", "audio_url": URL}})
        self.assertEqual(voice.build_payload({"voice_name": "Voice", "source_mode": "video_id", "video_id": "provider-video", "audio_url": URL}, {}),
                         {"model": "kling-v4-custom-voice", "metadata": {"voiceName": "Voice", "videoId": "provider-video"}})
        for kwargs in ({"voice_name": ""}, {"voice_name": "V", "audio_url": URL, "audio": object()},
                       {"voice_name": "V", "source_mode": "video_id", "video_id": ""}):
            with self.assertRaises(client.SeedanceAPIError):
                kling_v4.validate_voice(kwargs, strict=True)

    def test_named_result_parser_matches_observed_text_rows(self):
        for key in ("element_id", "voice_id", "trial_url"):
            self.assertEqual(kling_v4.named_results(auxiliary(**{key: "value"})), {key: "value"})
        self.assertEqual(kling_v4.named_results({"result_text": json.dumps({"results": [
            {"name": "element_id", "url": "", "text": "element-demo"},
        ]})}), {"element_id": "element-demo"})
        for data in ({}, {"result_text": "not-json"}, {"result_text": '{"results":{}}'}):
            with self.assertRaises(client.SeedanceAPIError):
                kling_v4.named_results(data)

    def test_serial_video_execution_uses_legacy_helpers_and_shared_download(self):
        for cls in CLASSES[:3]:
            instance = cls()
            with patch.object(instance, "collect_media", return_value={"images": [URL]}), \
                    patch.object(nodes, "get_config", return_value=CONFIG), \
                    patch.object(nodes, "submit_legacy_video_task", return_value="demo") as submit, \
                    patch.object(nodes, "poll_legacy_video_task", return_value={"data": {"result_url": URL}}), \
                    patch.object(nodes, "download_video", return_value="video") as download:
                result = instance.execute(prompt="Test", seed=123)["result"]
            self.assertEqual(result[:3], ("video", URL, "demo"))
            self.assertNotIn("seed", submit.call_args.args[0])
            self.assertTrue(download.called)

    def test_auxiliary_execution_extracts_ids_and_downloads_real_trial_audio(self):
        for cls, kwargs, final in (
            (nodes.Kling4CustomElement, {"element_name": "R", "prompt": "Robot"}, auxiliary(element_id="element-demo")),
            (nodes.Kling4CustomVoice, {"voice_name": "V"}, auxiliary(voice_id="voice-demo", trial_url="https://example.com/trial.wav")),
        ):
            instance = cls()
            audio = nodes.make_silent_audio()
            with patch.object(instance, "collect_media", return_value={"images": [URL, URL], "audio_url": URL}), \
                    patch.object(nodes, "get_config", return_value=CONFIG), \
                    patch.object(nodes, "submit_legacy_video_task", return_value="demo"), \
                    patch.object(nodes, "poll_legacy_video_task", return_value=final), \
                    patch.object(nodes, "download_audio", return_value=(audio, "trial.wav")) as download:
                result = instance.execute(**kwargs)["result"]
            self.assertEqual(len(result), 5)
            if cls is nodes.Kling4CustomVoice:
                self.assertIs(result[1], audio)
                self.assertTrue(download.called)
                self.assertEqual(result[0], "voice-demo")
            else:
                self.assertEqual(result[0], "element-demo")
                download.assert_not_called()

    def test_skip_errors_preserve_every_output_contract(self):
        for cls in CLASSES:
            instance = cls()
            with patch.object(instance, "_execute_inner", side_effect=RuntimeError("forced failure")), \
                    patch.object(nodes, "make_error_video", return_value="placeholder"):
                with self.assertRaises(RuntimeError):
                    instance.execute()
                result = instance.execute(skip_error=True)["result"]
            self.assertEqual(len(result), len(cls.RETURN_TYPES))
            self.assertIn("error", json.loads(result[-1]))
            self.assertEqual(result[0], "" if cls in CLASSES[3:] else "placeholder")

    def test_concurrent_preflight_failure_does_not_cancel_other_slots(self):
        wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS["SeedanceConcurrent_Kling_V4_T2V_Submit"]
        with patch.object(nodes.Kling4TextToVideo, "_execute_inner", return_value={"result": ("video", "", "", "{}")}), \
                patch.object(concurrent_nodes, "make_error_video", return_value="placeholder"):
            good = wrapper().submit(prompt="Test")[0]
            bad = wrapper().submit(prompt="Test", seconds=2, skip_error=True)[0]
            result = concurrent_nodes.SeedanceConcurrentVideoAwait().wait_all(future_1=good, future_2=bad)
        self.assertEqual(result[:2], ("video", "placeholder"))
        self.assertFalse(good.cancel_event.is_set())

    def test_post_timeout_never_replays_creation(self):
        session = Mock(post=Mock(side_effect=requests.exceptions.ReadTimeout("response lost")))
        with patch.object(client, "_session", return_value=session), self.assertRaisesRegex(RuntimeError, "not retried"):
            client.submit_legacy_video_task({"model": "kling-v4-t2v"}, CONFIG)
        self.assertEqual(session.post.call_count, 1)

    def test_all_workflow_links_widgets_and_credentials(self):
        paths = list((ROOT / "examples").glob("kling-v4-*.json"))
        self.assertEqual(len(paths), 11)
        for path in paths:
            source = path.read_text(encoding="utf-8")
            workflow = json.loads(source)
            by_id = {node["id"]: node for node in workflow["nodes"]}
            config = next(node for node in by_id.values() if node["type"] == "Seedance_Config")
            self.assertEqual(config["widgets_values"][1], "")
            for link_id, origin, slot, target, target_slot, kind in workflow["links"]:
                self.assertIn(link_id, by_id[origin]["outputs"][slot]["links"])
                self.assertEqual(by_id[target]["inputs"][target_slot]["link"], link_id)
                self.assertEqual(by_id[target]["inputs"][target_slot]["type"], kind)
            self.assertNotRegex(source, r"sk-[A-Za-z0-9]{12,}|task_[A-Za-z0-9]{12,}|X-Amz-Signature")
            for node in by_id.values():
                if node["type"].startswith("Kling_V4_"):
                    schema = nodes.NODE_CLASS_MAPPINGS[node["type"]].INPUT_TYPES()
                    expected = sum(1 for group in schema.values() for spec in group.values()
                                   if isinstance(spec[0], list) or spec[0] in {"STRING", "INT", "BOOLEAN", "FLOAT"}) + 1
                    self.assertEqual(len(node["widgets_values"]), expected)


if __name__ == "__main__":
    unittest.main()
