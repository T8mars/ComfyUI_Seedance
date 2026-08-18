import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


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


class _Response:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data
        self.text = json.dumps(data)

    def json(self):
        return self._data


class FlashVSRContractTests(unittest.TestCase):
    def test_inputs_match_single_source_contract(self):
        inputs = nodes.FlashVSRVideoUpscale.INPUT_TYPES()
        self.assertEqual(nodes.FLASHVSR_VIDEO_UPSCALE_MODEL, "FlashVSR_video_upscale")
        self.assertEqual(list(inputs["required"]), ["video_url"])
        self.assertEqual(
            list(inputs["optional"]),
            ["input_video", "api_config", "skip_error", "seed"],
        )
        self.assertEqual(inputs["optional"]["seed"][1]["default"], 0)
        self.assertTrue(
            inputs["optional"]["seed"][1]["control_after_generate"]
        )

    def test_payload_uses_exact_legacy_metadata_video_url(self):
        payload = nodes.FlashVSRVideoUpscale().build_payload(
            {},
            {"video_url": "https://cdn.test/source.mp4"},
        )
        self.assertEqual(payload, {
            "model": "FlashVSR_video_upscale",
            "metadata": {"video_url": "https://cdn.test/source.mp4"},
        })

    def test_local_video_is_uploaded_once(self):
        progress = []
        with (
            patch.object(nodes, "video_to_bytes", return_value=(b"video", "mp4")),
            patch.object(
                nodes,
                "upload_media",
                return_value="https://cdn.test/uploaded.mp4",
            ) as upload,
        ):
            media = nodes.FlashVSRVideoUpscale().collect_media(
                {"video_url": "", "input_video": {"file_path": "source.mp4"}},
                CONFIG,
                progress.append,
            )
        upload.assert_called_once_with(
            b"video",
            "flashvsr_input.mp4",
            "video/mp4",
            CONFIG,
            logger_prefix="FlashVSR_video_upscale",
        )
        self.assertEqual(media, {"video_url": "https://cdn.test/uploaded.mp4"})
        self.assertEqual(progress, [1.0])

    def test_exactly_one_source_is_required(self):
        node = nodes.FlashVSRVideoUpscale()
        with self.assertRaisesRegex(client.SeedanceAPIError, "exactly one source"):
            node.collect_media(
                {
                    "video_url": "https://cdn.test/source.mp4",
                    "input_video": object(),
                },
                CONFIG,
                lambda _value: None,
            )
        with self.assertRaisesRegex(client.SeedanceAPIError, "connect input_video"):
            node.collect_media(
                {"video_url": "", "input_video": None},
                CONFIG,
                lambda _value: None,
            )

    def test_execute_uses_legacy_endpoint_helpers_and_shared_downloader(self):
        final = {
            "code": "success",
            "data": {
                "status": "SUCCESS",
                "result_url": "https://cdn.test/result.mp4",
            },
        }
        video = {"file_path": "result.mp4"}
        node = nodes.FlashVSRVideoUpscale()
        with (
            patch.object(nodes, "get_config", return_value=CONFIG),
            patch.object(
                node,
                "collect_media",
                return_value={"video_url": "https://cdn.test/source.mp4"},
            ),
            patch.object(
                nodes,
                "submit_legacy_video_task",
                return_value="task-test",
            ) as submit,
            patch.object(nodes, "poll_legacy_video_task", return_value=final),
            patch.object(nodes, "download_video", return_value=video) as download,
        ):
            result = node.execute(video_url="https://cdn.test/source.mp4")

        self.assertEqual(submit.call_args.args[0], {
            "model": "FlashVSR_video_upscale",
            "metadata": {"video_url": "https://cdn.test/source.mp4"},
        })
        download.assert_called_once_with(
            "https://cdn.test/result.mp4",
            logger_prefix="FlashVSR_video_upscale",
        )
        self.assertEqual(result["result"][:3], (
            video,
            "https://cdn.test/result.mp4",
            "task-test",
        ))


class FlashVSRLegacyClientTests(unittest.TestCase):
    def test_submit_and_poll_use_compatibility_endpoint(self):
        session = Mock()
        session.post.return_value = _Response(200, {"data": {"id": "task-test"}})
        session.get.side_effect = [
            _Response(200, {"data": {"status": "IN_PROGRESS", "progress": "40%"}}),
            _Response(200, {
                "data": {
                    "status": "SUCCESS",
                    "result_url": "https://cdn.test/result.mp4",
                }
            }),
        ]
        with (
            patch.object(client, "_session", return_value=session),
            patch.object(client, "cooperative_sleep"),
        ):
            task_id = client.submit_legacy_video_task(
                {
                    "model": "FlashVSR_video_upscale",
                    "metadata": {"video_url": "https://cdn.test/source.mp4"},
                },
                CONFIG,
            )
            final = client.poll_legacy_video_task(task_id, CONFIG)

        self.assertEqual(task_id, "task-test")
        self.assertEqual(
            session.post.call_args.args[0],
            "https://api.seedance.nz/v1/video/generations",
        )
        self.assertEqual(
            session.get.call_args.args[0],
            "https://api.seedance.nz/v1/video/generations/task-test",
        )
        self.assertEqual(
            client.extract_legacy_video_url(final),
            "https://cdn.test/result.mp4",
        )

    def test_url_extractor_supports_nested_content(self):
        final = {
            "data": {
                "status": "SUCCESS",
                "data": {"content": {"video_url": "https://cdn.test/video.mp4"}},
            }
        }
        self.assertEqual(
            client.extract_legacy_video_url(final),
            "https://cdn.test/video.mp4",
        )


class FlashVSRRegistrationAndWorkflowTests(unittest.TestCase):
    def test_serial_and_concurrent_nodes_are_registered(self):
        self.assertIs(
            nodes.NODE_CLASS_MAPPINGS["FashVSR_Video_Upscale"],
            nodes.FlashVSRVideoUpscale,
        )
        wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
            "SeedanceConcurrent_FashVSR_Video_Upscale_Submit"
        ]
        self.assertEqual(wrapper.CONCURRENT_KIND, "video")
        self.assertIs(wrapper.ORIGINAL_NODE_CLASS, nodes.FlashVSRVideoUpscale)

    def test_safe_example_workflow(self):
        path = PLUGIN_ROOT / "examples" / "FlashVSR-480P视频超分.json"
        workflow = json.loads(path.read_text(encoding="utf-8"))
        node = next(
            item for item in workflow["nodes"]
            if item.get("type") == "FashVSR_Video_Upscale"
        )
        config = next(
            item for item in workflow["nodes"]
            if item.get("type") == "Seedance_Config"
        )
        self.assertEqual(config["widgets_values"], ["https://api.seedance.nz", ""])
        self.assertEqual(node["widgets_values"], ["", False, 0, "fixed"])
        incoming_types = {
            link[5]
            for link in workflow["links"]
            if link[3] == node["id"]
        }
        self.assertEqual(incoming_types, {"VIDEO", "SEEDANCE_CONFIG"})
        serialized = json.dumps(workflow, ensure_ascii=False)
        self.assertNotRegex(serialized, r"sk-[A-Za-z0-9]{12,}")
        self.assertNotRegex(serialized, r"task[_-][A-Za-z0-9_-]{6,}")


if __name__ == "__main__":
    unittest.main()
