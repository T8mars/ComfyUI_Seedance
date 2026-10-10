import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT.parent))

from ComfyUI_Seedance import concurrent_nodes, nodes
from ComfyUI_Seedance.core import client


CONFIG = {
    "base_url": "https://api.seedance.nz",
    "api_key": "sk-test",
    "poll_interval": 0,
    "max_poll_time": 30,
}
SOURCE_URL = "https://cdn.test/source.mp4"
RESULT_URL = "https://cdn.test/result.mp4"
MP4_BYTES = b"\x00\x00\x00\x20ftypisom"


class TopazContractTests(unittest.TestCase):
    def test_inputs_match_documented_defaults_and_seed_contract(self):
        inputs = nodes.TopazVideoUpscale.INPUT_TYPES()
        self.assertEqual(list(inputs["required"]), ["video_url", "resolution", "model"])
        self.assertEqual(list(inputs["optional"]), ["input_video", "api_config", "skip_error", "seed"])
        self.assertEqual(inputs["required"]["resolution"][0], ["720p", "1080p", "2K", "4K"])
        self.assertEqual(inputs["required"]["resolution"][1]["default"], "1080p")
        self.assertEqual(inputs["required"]["model"][0], ["Ultra", "Max", "High", "Medium", "Low"])
        self.assertEqual(inputs["required"]["model"][1]["default"], "Max")
        self.assertFalse(inputs["optional"]["skip_error"][1]["default"])
        self.assertTrue(inputs["optional"]["seed"][1]["control_after_generate"])
        self.assertTrue(nodes.TopazVideoUpscale.SEEDANCE_CACHE_ONLY_SEED)
        self.assertEqual(nodes.TopazVideoUpscale.RETURN_TYPES, ("VIDEO", "STRING", "STRING", "STRING"))

    def test_payload_is_exact_and_keeps_case_sensitive_values(self):
        node = nodes.TopazVideoUpscale()
        for resolution in nodes.TOPAZ_VIDEO_RESOLUTIONS:
            for quality in nodes.TOPAZ_VIDEO_QUALITIES:
                with self.subTest(resolution=resolution, quality=quality):
                    self.assertEqual(
                        node.build_payload(
                            {"resolution": resolution, "model": quality, "seed": 123,
                             "prompt": "unused", "seconds": "unused"},
                            {"video_url": SOURCE_URL},
                        ),
                        {"model": "Topaz-Upscale-LowPirce", "metadata": {
                            "video_url": [SOURCE_URL], "resolution": resolution, "quality": quality,
                        }},
                    )
        self.assertEqual(node.build_payload({}, {"video_url": SOURCE_URL})["metadata"], {
            "video_url": [SOURCE_URL], "resolution": "1080p", "quality": "Max",
        })

    def test_invalid_controls_and_urls_fail_before_upload_or_submission(self):
        cases = [
            {"resolution": "2k"}, {"resolution": "8K"},
            {"model": "max"}, {"model": "other"},
            {"video_url": "file:///source.mp4"},
            {"video_url": "https://"}, {"video_url": "https://[invalid"},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), patch.object(nodes, "upload_media") as upload, \
                    patch.object(nodes, "submit_legacy_video_task") as submit:
                with self.assertRaises(client.SeedanceAPIError):
                    nodes.TopazVideoUpscale().execute(api_config=CONFIG, input_video=object(), **kwargs)
                upload.assert_not_called()
                submit.assert_not_called()

    def test_exactly_one_source_is_required(self):
        node = nodes.TopazVideoUpscale()
        for kwargs in ({}, {"video_url": SOURCE_URL, "input_video": object()}):
            with self.subTest(kwargs=kwargs), patch.object(nodes, "upload_media") as upload:
                with self.assertRaises(client.SeedanceAPIError):
                    node.collect_media(kwargs, CONFIG, lambda _value: None)
                upload.assert_not_called()

    def test_url_source_does_not_upload(self):
        progress = []
        with patch.object(nodes, "upload_media") as upload:
            result = nodes.TopazVideoUpscale().collect_media(
                {"video_url": "  " + SOURCE_URL + "  "}, CONFIG, progress.append,
            )
        self.assertEqual(result, {"video_url": SOURCE_URL})
        self.assertEqual(progress, [1.0])
        upload.assert_not_called()

    def test_local_mp4_is_uploaded_once(self):
        with patch.object(nodes, "video_to_bytes", return_value=(MP4_BYTES, "mp4")), \
                patch.object(nodes, "upload_media", return_value=SOURCE_URL) as upload:
            result = nodes.TopazVideoUpscale().collect_media(
                {"input_video": object()}, CONFIG, lambda _value: None,
            )
        upload.assert_called_once_with(
            MP4_BYTES, "topaz_input.mp4", "video/mp4", CONFIG,
            logger_prefix="Topaz-Upscale-LowPirce",
        )
        self.assertEqual(result, {"video_url": SOURCE_URL})

    def test_invalid_local_media_fails_before_upload(self):
        for data, extension in ((MP4_BYTES, "mov"), (b"not mp4", "mp4"),
                                (MP4_BYTES + bytes(50 * 1024 * 1024), "mp4")):
            with self.subTest(extension=extension, size=len(data)), \
                    patch.object(nodes, "video_to_bytes", return_value=(data, extension)), \
                    patch.object(nodes, "upload_media") as upload:
                with self.assertRaises(client.SeedanceAPIError):
                    nodes.TopazVideoUpscale().collect_media(
                        {"input_video": object()}, CONFIG, lambda _value: None,
                    )
                upload.assert_not_called()

    def test_build_payload_rejects_empty_or_invalid_source(self):
        for media in ({}, {"video_url": ""}, {"video_url": "file:///source.mp4"}):
            with self.subTest(media=media), self.assertRaises(client.SeedanceAPIError):
                nodes.TopazVideoUpscale().build_payload({}, media)

    def test_execute_uses_legacy_helpers_and_shared_downloader(self):
        final = {"data": {"status": "SUCCESS", "result_url": RESULT_URL}}
        video = {"file_path": "result.mp4"}
        progress = []
        node = nodes.TopazVideoUpscale()
        with patch.object(nodes, "get_config", return_value=CONFIG), \
                patch.object(nodes, "submit_legacy_video_task", return_value="task-test") as submit, \
                patch.object(nodes, "poll_legacy_video_task", return_value=final) as poll, \
                patch.object(nodes, "download_video", return_value=video) as download, \
                patch.object(node, "_update_progress", side_effect=lambda _bar, value: progress.append(value)):
            result = node.execute(video_url=SOURCE_URL, resolution="2K", model="High", seed=123)
        submit.assert_called_once_with(
            {"model": "Topaz-Upscale-LowPirce", "metadata": {
                "video_url": [SOURCE_URL], "resolution": "2K", "quality": "High",
            }}, CONFIG, logger_prefix="Topaz-Upscale-LowPirce",
        )
        self.assertEqual(poll.call_args.args, ("task-test", CONFIG))
        download.assert_called_once_with(RESULT_URL, logger_prefix="Topaz-Upscale-LowPirce")
        self.assertIs(result["result"][0], video)
        self.assertEqual(result["result"][1:3], (RESULT_URL, "task-test"))
        self.assertEqual(json.loads(result["result"][3]), final)
        self.assertEqual(progress[-1], 100)

    def test_documented_result_envelopes_are_supported(self):
        for response in (
            {"data": {"result_url": RESULT_URL}},
            {"data": {"data": {"content": {"video_urls": [RESULT_URL]}}}},
            {"video_url": RESULT_URL},
            {"metadata": {"video_urls": [RESULT_URL]}},
        ):
            with self.subTest(response=response):
                self.assertEqual(client.extract_legacy_video_url(response), RESULT_URL)

    def test_skip_error_preserves_output_contract(self):
        node = nodes.TopazVideoUpscale()
        with patch.object(node, "_execute_inner", side_effect=RuntimeError("forced failure")), \
                patch.object(nodes, "make_error_video", return_value="placeholder"):
            with self.assertRaisesRegex(RuntimeError, "forced failure"):
                node.execute()
            result = node.execute(skip_error=True)
        self.assertEqual(result["result"][:3], ("placeholder", "", ""))
        self.assertIn("error", json.loads(result["result"][3]))


class TopazRegistrationAndWorkflowTests(unittest.TestCase):
    def tearDown(self):
        concurrent_nodes.shutdown_concurrent_pools(wait=True)

    def test_concurrent_wrapper_has_independent_class_and_identical_inputs(self):
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Topaz_Video_Upscale"], nodes.TopazVideoUpscale)
        wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
            "SeedanceConcurrent_Topaz_Video_Upscale_Submit"
        ]
        self.assertEqual(wrapper.CONCURRENT_KIND, "video")
        self.assertIs(wrapper.ORIGINAL_NODE_CLASS, nodes.TopazVideoUpscale)
        self.assertEqual(wrapper.INPUT_TYPES(), nodes.TopazVideoUpscale.INPUT_TYPES())
        self.assertFalse(hasattr(wrapper, "VALIDATE_INPUTS"))
        self.assertFalse(hasattr(wrapper, "IS_CHANGED"))

    def test_concurrent_preflight_failure_does_not_cancel_successful_sibling(self):
        wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
            "SeedanceConcurrent_Topaz_Video_Upscale_Submit"
        ]
        with patch.object(nodes.TopazVideoUpscale, "_execute_inner", return_value={
            "result": ("valid-video", "", "", "{}"),
        }), patch.object(concurrent_nodes, "make_error_video", return_value="placeholder"):
            success = wrapper().submit(video_url=SOURCE_URL, resolution="720p", model="Low")[0]
            failed = wrapper().submit(
                video_url=SOURCE_URL, resolution="8K", model="Low", skip_error=True,
            )[0]
            result = concurrent_nodes.SeedanceConcurrentVideoAwait().wait_all(
                future_1=success, future_2=failed, failure_mode="raise",
            )
        self.assertEqual(result[:2], ("valid-video", "placeholder"))
        self.assertFalse(success.cancel_event.is_set())
        self.assertEqual(json.loads(result[-1])["failed"], 1)

    def test_both_examples_have_correct_sockets_widgets_and_no_credentials(self):
        for local in (True, False):
            filename = "Topaz视频高清修复本地素材.json" if local else "Topaz视频高清修复网址素材.json"
            source = (PLUGIN_ROOT / "examples" / filename).read_text(encoding="utf-8")
            workflow = json.loads(source)
            by_id = {node["id"]: node for node in workflow["nodes"]}
            config = next(node for node in by_id.values() if node["type"] == "Seedance_Config")
            generator = next(node for node in by_id.values() if node["type"] == "Topaz_Video_Upscale")
            self.assertEqual(config["widgets_values"], ["https://api.seedance.nz", ""])
            self.assertEqual(generator["widgets_values"], [
                "" if local else "https://example.com/source.mp4", "1080p", "Max", False, 0, "fixed",
            ])
            self.assertEqual([item["name"] for item in generator["inputs"]], ["input_video", "api_config"])
            for link_id, origin, origin_slot, target, target_slot, kind in workflow["links"]:
                self.assertEqual(by_id[origin]["outputs"][origin_slot]["type"], kind)
                self.assertEqual(by_id[target]["inputs"][target_slot]["type"], kind)
                self.assertEqual(by_id[target]["inputs"][target_slot]["link"], link_id)
            self.assertEqual(any(node["type"] == "LoadVideo" for node in by_id.values()), local)
            self.assertTrue(any(node["type"] == "SaveVideo" for node in by_id.values()))
            self.assertNotRegex(source, r"sk-[A-Za-z0-9]{12,}|task[_-][A-Za-z0-9_-]{6,}")


if __name__ == "__main__":
    unittest.main()
