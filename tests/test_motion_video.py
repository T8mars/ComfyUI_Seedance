import json
from pathlib import Path
import sys
import shutil
import subprocess
import unittest
import requests
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import nodes, concurrent_nodes
from ComfyUI_Seedance.core import client

CONFIG = {"base_url": "https://api.seedance.nz", "api_key": "sk-test",
          "poll_interval": 0, "max_poll_time": 30}
VIDEO_URL = "https://cdn.example.com/final.mp4"


def response(data, status=200):
    return Mock(status_code=status, text=json.dumps(data), json=Mock(return_value=data))


class MotionVideoTests(unittest.TestCase):
    def tearDown(self):
        concurrent_nodes.shutdown_concurrent_pools(wait=True)

    def test_dynamic_widgets_in_serial_and_concurrent_nodes(self):
        executable = shutil.which("node")
        if not executable:
            self.skipTest("Node.js unavailable")
        result = subprocess.run([executable, str(ROOT / "tests" / "motion_video_ui.mjs")],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_registration_seeds_and_outputs(self):
        cls = nodes.NODE_CLASS_MAPPINGS["Zhenzhen_Motion_Video"]
        self.assertIs(cls, nodes.ZhenzhenMotionVideo)
        self.assertEqual(cls.RETURN_TYPES, ("VIDEO",) + ("STRING",) * 9)
        self.assertEqual(cls.RETURN_NAMES[:4], ("video", "video_url", "task_id", "response"))
        self.assertEqual(cls.INPUT_TYPES()["optional"]["seed"][1]["default"], 0)
        self.assertTrue(cls.SEEDANCE_CACHE_ONLY_SEED)
        self.assertFalse(hasattr(cls, "IS_CHANGED"))
        self.assertEqual(cls.INPUT_TYPES()["required"]["duration"][0], [15, 30, 45, 60])
        self.assertFalse(any(spec[0] in ("IMAGE", "AUDIO", "VIDEO")
                             for spec in cls.INPUT_TYPES()["optional"].values()))

    def test_both_models_use_exact_top_level_protocol(self):
        for model in nodes.MOTION_VIDEO_MODELS:
            with self.subTest(model=model):
                result = nodes.ZhenzhenMotionVideo().build_payload({
                    "model": model, "prompt": "  Motion typography  ", "duration": 15,
                    "ratio": "9:16", "resolution": "1080p", "template_id": "cyber-glitch",
                    "title": "MOTION", "subtitle": "Create", "keywords": '["One", "Two"]',
                    "signature": "Studio", "language": "en", "music": "auto",
                    "assets": "https://cdn.example.com/one.png\nhttps://cdn.example.com/two.jpg",
                    "seed": 123, "skip_error": True, "seconds": "4", "metadata": {"other": True},
                })
                self.assertEqual(result, {
                    "model": model, "prompt": "Motion typography", "duration": 15,
                    "ratio": "9:16", "resolution": "1080p", "motion": {
                        "template_id": "cyber-glitch", "title": "MOTION", "subtitle": "Create",
                        "keywords": ["One", "Two"], "signature": "Studio", "language": "en",
                        "music": "auto", "assets": ["https://cdn.example.com/one.png", "https://cdn.example.com/two.jpg"],
                    },
                })

    def test_api_default_and_blank_fields_are_omitted(self):
        payload = nodes.ZhenzhenMotionVideo().build_payload({
            "prompt": "Motion", "music": "api_default", "language": "",
            "revise_from": "stale", "revision_instruction": "stale",
        })
        self.assertEqual(payload, {"model": nodes.MOTION_VIDEO_MODELS[0], "prompt": "Motion",
                                   "duration": 15, "ratio": "16:9", "resolution": "720p"})

    def test_revision_requires_both_fields_only_at_runtime(self):
        cls = nodes.ZhenzhenMotionVideo
        self.assertIs(cls.VALIDATE_INPUTS(operation="revise"), True)
        for kwargs in ({"prompt": ""}, {"prompt": "Motion", "operation": "revise"},
                       {"prompt": "Motion", "operation": "revise", "revise_from": "source"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(client.SeedanceAPIError):
                cls().build_payload(kwargs)
        payload = cls().build_payload({"prompt": "Motion", "operation": "revise",
                                      "revise_from": " source ", "revision_instruction": " Change scene 3 "})
        self.assertEqual(payload["motion"]["revise_from"], "source")
        self.assertEqual(payload["motion"]["revision_instruction"], "Change scene 3")

    def test_api_default_literal_in_text_is_not_dropped(self):
        payload = nodes.ZhenzhenMotionVideo().build_payload({"prompt": "Motion", "title": "api_default"})
        self.assertEqual(payload["motion"]["title"], "api_default")

    def test_invalid_values_stop_before_submission(self):
        invalid = [
            {"model": "other"}, {"operation": "edit"}, {"duration": 4}, {"duration": True},
            {"duration": 15.0}, {"ratio": "2:3"}, {"resolution": "4k"}, {"template_id": "not-documented"},
            {"music": "off"}, {"title": 123}, {"keywords": '["one", 2]'},
            {"keywords": "[broken"}, {"assets": "file:///image.png"},
            {"assets": "data:image/png;base64,AA"}, {"assets": "https://"},
            {"assets": "https://[invalid"}, {"assets": "https://example.com/a b.png"},
            {"assets": "https://user:password@example.com/image.png"},
            {"assets": json.dumps(["https://example.com/image.png"] * 5)},
        ]
        for value in invalid:
            with self.subTest(value=value), patch.object(nodes, "submit_legacy_video_task") as submit:
                with self.assertRaises(client.SeedanceAPIError):
                    nodes.ZhenzhenMotionVideo().execute(prompt="Motion", api_config=CONFIG, **value)
                submit.assert_not_called()

    def test_four_assets_preserve_order(self):
        assets = [f"https://example.com/{i}.png" for i in range(4)]
        payload = nodes.ZhenzhenMotionVideo().build_payload({"prompt": "Motion", "assets": json.dumps(assets)})
        self.assertEqual(payload["motion"]["assets"], assets)

    def test_motion_submission_does_not_replay_an_ambiguous_timeout(self):
        payload = nodes.ZhenzhenMotionVideo().build_payload({"prompt": "Motion"})
        session = Mock(post=Mock(side_effect=requests.exceptions.ReadTimeout("response lost")))
        with patch.object(client, "_session", return_value=session), patch.object(client, "cooperative_sleep"):
            with self.assertRaisesRegex(RuntimeError, "not retried"):
                client.submit_legacy_video_task(payload, CONFIG)
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(session.post.call_args.args[0], "https://api.seedance.nz/v1/video/generations")

    def test_poll_all_documented_states_and_compatibility_state(self):
        statuses = ["queued", "storyboarding", "coding", "checking", "media_generating",
                    "preview_ready", "rendering", "IN_PROGRESS", "succeeded"]
        samples = [response({"status": status, "progress": i * 10,
                             "content": {"video_url": VIDEO_URL}}) for i, status in enumerate(statuses)]
        session = Mock(get=Mock(side_effect=samples))
        with patch.object(client, "_session", return_value=session), \
                patch.object(client, "cooperative_sleep"), patch.object(client, "_log") as log:
            result = client.poll_motion_video_task("source", CONFIG)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(session.get.call_count, len(statuses))
        self.assertFalse(any("Unknown" in str(call) for call in log.call_args_list))
        self.assertEqual(session.get.call_args.args[0], "https://api.seedance.nz/v1/video/generations/source")

    def test_failed_poll_ends_without_downloading_preview(self):
        session = Mock(get=Mock(return_value=response({"data": {"status": "failed", "fail_reason": "Render failed"}})))
        with patch.object(client, "_session", return_value=session), patch.object(client, "cooperative_sleep"):
            with self.assertRaisesRegex(client.SeedanceAPIError, "Render failed"):
                client.poll_motion_video_task("source", CONFIG)

    def test_content_extraction_never_uses_a_preview_as_final(self):
        content = {"video_url": VIDEO_URL}
        for final in ({"content": content}, {"data": {"content": content}},
                      {"data": {"data": {"content": content}}}):
            self.assertEqual(nodes.ZhenzhenMotionVideo._content(final), content)
        for final in ({"content": {"preview_url": VIDEO_URL}},
                      {"video_url": VIDEO_URL}, {"content": {"video_url": "file:///result.mp4"}}):
            with self.assertRaises(client.SeedanceAPIError):
                nodes.ZhenzhenMotionVideo._content(final)

    def test_observed_compatibility_envelope_retains_sibling_artifacts(self):
        final = {"data": {"status": "SUCCESS", "data": {
            "content": {"video_url": VIDEO_URL}, "cover_url": "https://example.com/cover.png",
            "preview_url": "https://example.com/preview.mp4", "storyboard": {"scenes": [1]},
            "fallback_scenes": [],
        }}}
        content = nodes.ZhenzhenMotionVideo._content(final)
        self.assertEqual(content["cover_url"], "https://example.com/cover.png")
        self.assertEqual(content["storyboard"], {"scenes": [1]})
        self.assertEqual(content["fallback_scenes"], [])

    def test_execute_downloads_and_preserves_optional_results(self):
        final = {"status": "succeeded", "content": {"video_url": VIDEO_URL,
                 "cover_url": "https://example.com/cover.png", "storyboard": [{"scene": 1}], "fallback_scenes": [2]}}
        with patch.object(nodes, "get_config", return_value=CONFIG), \
                patch.object(nodes, "submit_legacy_video_task", return_value="source") as submit, \
                patch.object(nodes, "poll_motion_video_task", return_value=final), \
                patch.object(nodes, "download_video", return_value="video") as download, \
                patch("builtins.print") as logged:
            result = nodes.ZhenzhenMotionVideo().execute(prompt="Motion", seed=123)["result"]
        self.assertEqual(result[:3], ("video", VIDEO_URL, "source"))
        self.assertEqual(len(result), 10)
        self.assertEqual(json.loads(result[8]), [{"scene": 1}])
        self.assertEqual(json.loads(result[9]), [2])
        self.assertNotIn("seed", submit.call_args.args[0])
        self.assertTrue(any("fallback scenes" in str(call) for call in logged.call_args_list))
        download.assert_called_once_with(VIDEO_URL, logger_prefix="Seedance_ZhenzhenMotionVideo")

    def test_skip_error_retains_ten_outputs(self):
        with patch.object(nodes.ZhenzhenMotionVideo, "_execute_inner", side_effect=RuntimeError("render failed")), \
                patch.object(nodes, "make_error_video", return_value="placeholder"):
            with self.assertRaises(RuntimeError):
                nodes.ZhenzhenMotionVideo().execute()
            result = nodes.ZhenzhenMotionVideo().execute(skip_error=True)["result"]
        self.assertEqual(len(result), 10)
        self.assertEqual(result[:3], ("placeholder", "", ""))
        self.assertEqual(result[4:], ("",) * 6)

    def test_concurrent_preflight_and_failure_isolation(self):
        cls = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS["SeedanceConcurrent_Zhenzhen_Motion_Video_Submit"]
        self.assertEqual(cls.INPUT_TYPES(), nodes.ZhenzhenMotionVideo.INPUT_TYPES())
        self.assertFalse(issubclass(cls, nodes.ZhenzhenMotionVideo))
        self.assertFalse(hasattr(cls, "VALIDATE_INPUTS"))
        self.assertFalse(hasattr(cls, "IS_CHANGED"))
        with patch.object(nodes.ZhenzhenMotionVideo, "_execute_inner", return_value={"result": ("video",) + ("",) * 9}), \
                patch.object(concurrent_nodes, "make_error_video", return_value="placeholder"):
            good = cls().submit(prompt="Motion")[0]
            bad = cls().submit(prompt="Motion", duration=4, skip_error=True)[0]
            result = concurrent_nodes.SeedanceConcurrentVideoAwait().wait_all(future_1=good, future_2=bad)
        self.assertEqual(result[:2], ("video", "placeholder"))
        self.assertEqual(json.loads(result[-1])["failed"], 1)
        self.assertFalse(good.cancel_event.is_set())

    def test_four_workflows_have_blank_keys_valid_links_and_revision_connection(self):
        for pro in (False, True):
            for revision in (False, True):
                filename = "MotionVideo" + ("Pro" if pro else "Standard") + ("成片修订.json" if revision else "动效生成.json")
                source = (ROOT / "examples" / filename).read_text(encoding="utf-8")
                workflow = json.loads(source)
                by_id = {node["id"]: node for node in workflow["nodes"]}
                self.assertEqual(by_id[1]["widgets_values"][1], "")
                self.assertEqual(by_id[2]["widgets_values"][0], nodes.MOTION_VIDEO_MODELS[int(pro)])
                for link_id, origin, origin_slot, target, target_slot, kind in workflow["links"]:
                    self.assertIn(link_id, by_id[origin]["outputs"][origin_slot]["links"])
                    self.assertEqual(by_id[target]["inputs"][target_slot]["link"], link_id)
                    self.assertEqual(by_id[target]["inputs"][target_slot]["type"], kind)
                if revision:
                    self.assertEqual(by_id[4]["inputs"][1]["name"], "revise_from")
                    self.assertIn([4, 2, 2, 4, 1, "STRING"], workflow["links"])
                self.assertNotRegex(source, r"sk-[A-Za-z0-9]{12,}|task[_-][A-Za-z0-9_-]{6,}|X-Amz-Signature")


if __name__ == "__main__":
    unittest.main()
