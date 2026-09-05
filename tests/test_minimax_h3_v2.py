import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT.parent))

try:
    from ComfyUI_Seedance import concurrent_nodes, nodes
    from ComfyUI_Seedance.core import client
except ModuleNotFoundError:
    spec = importlib.util.spec_from_file_location(
        "ComfyUI_Seedance",
        PACKAGE_ROOT / "__init__.py",
        submodule_search_locations=[str(PACKAGE_ROOT)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules["ComfyUI_Seedance"] = package
    spec.loader.exec_module(package)
    from ComfyUI_Seedance import concurrent_nodes, nodes
    from ComfyUI_Seedance.core import client


CONFIG = {
    "base_url": "https://example.test",
    "api_key": "test-key",
    "timeout": 60,
    "poll_interval": 0,
    "max_poll_time": 60,
}


class FakeResponse:
    def __init__(self, status_code=200, data=None, headers=None, text=None):
        self.status_code = status_code
        self._data = data if data is not None else {}
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(self._data)
        self.closed = False

    def json(self):
        return self._data

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, post_response=None, get_responses=None):
        self.post_response = post_response
        self.get_responses = list(get_responses or [])
        self.post_calls = []
        self.get_calls = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.post_response

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self.get_responses.pop(0)


def base_kwargs(**updates):
    values = {
        "model": nodes.MINIMAX_H3_V2_MODEL,
        "prompt": "A paper kite rises above a quiet shoreline.",
        "duration": 4,
        "resolution": "480P",
        "ratio": "16:9",
        "audio_mode": "api_default",
        "denoise_strength": 0.35,
        "add_drive_as_reference": "api_default",
        "video1_start_seconds": 0.0,
        "video2_start_seconds": 0.0,
        "video3_start_seconds": 0.0,
    }
    values.update(updates)
    return values


class MiniMaxH3V2NodeTests(unittest.TestCase):
    def test_registration_inputs_seed_skip_error_and_concurrent_wrapper(self):
        self.assertIs(
            nodes.NODE_CLASS_MAPPINGS["Minimax_H3_V2_Video"],
            nodes.MinimaxH3V2Video,
        )
        inputs = nodes.MinimaxH3V2Video.INPUT_TYPES()
        self.assertEqual(inputs["required"]["model"][0], ["MiniMax-H3"])
        self.assertEqual(inputs["required"]["duration"][1]["default"], 4)
        self.assertEqual(inputs["required"]["resolution"][0], ["480P", "768P"])
        self.assertIn("skip_error", inputs["optional"])
        self.assertIn("seed", inputs["optional"])
        self.assertTrue(nodes.MinimaxH3V2Video.SEEDANCE_CACHE_ONLY_SEED)
        self.assertEqual(
            len([name for name in inputs["optional"] if name.startswith("image")]),
            9,
        )
        self.assertEqual(
            len([name for name in inputs["optional"] if name.startswith("video")]),
            3,
        )
        self.assertEqual(
            len([name for name in inputs["optional"] if name.startswith("audio")]),
            3,
        )
        wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
            "SeedanceConcurrent_Minimax_H3_V2_Video_Submit"
        ]
        self.assertIs(wrapper.ORIGINAL_NODE_CLASS, nodes.MinimaxH3V2Video)
        self.assertEqual(wrapper.RETURN_TYPES, (concurrent_nodes.VIDEO_FUTURE_TYPE,))

    def test_text_payload_uses_exact_v2_contract_and_never_sends_seed(self):
        kwargs = base_kwargs(seed=123)
        payload = nodes.MinimaxH3V2Video().build_payload(kwargs, {})
        self.assertEqual(
            payload,
            {
                "model": "MiniMax-H3",
                "content": [
                    {
                        "type": "text",
                        "text": kwargs["prompt"],
                    }
                ],
                "resolution": "480P",
                "duration": 4,
                "ratio": "16:9",
            },
        )
        self.assertNotIn("seed", payload)

    def test_keyframes_references_drive_audio_and_audio_control(self):
        marker = object()
        kwargs = base_kwargs(
            duration=20,
            ratio="adaptive",
            audio_mode="remix_source",
            denoise_strength=0.42,
            add_drive_as_reference="true",
            first_frame=marker,
            last_frame=marker,
            image1=marker,
            video1=marker,
            video1_start_seconds=1.5,
            audio1=marker,
            drive_audio=marker,
        )
        media = {
            "first_frame": "https://cdn.test/first.png",
            "last_frame": "https://cdn.test/last.png",
            "reference_images": [(1, "https://cdn.test/ref.png")],
            "reference_videos": [(1, "https://cdn.test/ref.mp4")],
            "reference_audios": [(1, "https://cdn.test/ref.wav")],
            "drive_audio": "https://cdn.test/drive.wav",
        }
        payload = nodes.MinimaxH3V2Video().build_payload(kwargs, media)
        roles = [item.get("role") for item in payload["content"][1:]]
        self.assertEqual(
            roles,
            [
                "first_frame",
                "last_frame",
                "reference_image",
                "reference_video",
                "reference_audio",
                "drive_audio",
            ],
        )
        video_item = next(
            item for item in payload["content"] if item.get("role") == "reference_video"
        )
        self.assertEqual(video_item["start_time_seconds"], 1.5)
        self.assertEqual(
            payload["audio_control"],
            {
                "mode": "remix_source",
                "denoise_strength": 0.42,
                "add_drive_as_reference": True,
            },
        )

    def test_documented_conditional_validation(self):
        node = nodes.MinimaxH3V2Video
        self.assertIs(node.VALIDATE_INPUTS(strict=True, **base_kwargs()), True)
        self.assertIn(
            "drive_audio",
            node.VALIDATE_INPUTS(strict=True, **base_kwargs(duration=16)),
        )
        self.assertIs(
            node.VALIDATE_INPUTS(
                strict=True,
                **base_kwargs(duration=60, drive_audio=object()),
            ),
            True,
        )
        self.assertIn(
            "fixed ratio",
            node.VALIDATE_INPUTS(
                strict=True,
                **base_kwargs(ratio="api_default"),
            ),
        )
        self.assertIn(
            "first_frame",
            node.VALIDATE_INPUTS(
                strict=True,
                **base_kwargs(ratio="adaptive", image1=object()),
            ),
        )
        self.assertIs(
            node.VALIDATE_INPUTS(
                strict=True,
                **base_kwargs(ratio="auto", last_frame=object()),
            ),
            True,
        )
        self.assertIn(
            "requires drive_audio",
            node.VALIDATE_INPUTS(
                strict=True,
                **base_kwargs(audio_mode="lock_source"),
            ),
        )
        self.assertIn(
            "does not allow",
            node.VALIDATE_INPUTS(
                strict=True,
                **base_kwargs(
                    drive_audio=object(),
                    audio_mode="reference_only",
                    add_drive_as_reference="false",
                ),
            ),
        )

    def test_collect_media_uploads_each_role_and_keeps_video_slot_offset(self):
        marker = object()
        kwargs = base_kwargs(
            first_frame=marker,
            image2=marker,
            video3=marker,
            video3_start_seconds=2.0,
            audio1=marker,
            drive_audio=marker,
        )
        uploaded = iter(
            [
                "https://cdn.test/first.png",
                "https://cdn.test/ref.png",
                "https://cdn.test/ref.mp4",
                "https://cdn.test/ref.wav",
                "https://cdn.test/drive.wav",
            ]
        )
        with (
            patch.object(nodes, "image_to_png_bytes", return_value=b"png"),
            patch.object(nodes, "video_to_bytes", return_value=(b"mp4", "mp4")),
            patch.object(nodes, "audio_to_wav_bytes", return_value=b"wav"),
            patch.object(
                nodes,
                "upload_media",
                side_effect=lambda *args, **kwargs: next(uploaded),
            ) as upload,
        ):
            media = nodes.MinimaxH3V2Video().collect_media(
                kwargs,
                CONFIG,
                lambda _value: None,
            )

        self.assertEqual(upload.call_count, 5)
        self.assertEqual(media["reference_images"], [(2, "https://cdn.test/ref.png")])
        self.assertEqual(media["reference_videos"], [(3, "https://cdn.test/ref.mp4")])
        payload = nodes.MinimaxH3V2Video().build_payload(kwargs, media)
        video_item = next(
            item for item in payload["content"] if item.get("role") == "reference_video"
        )
        self.assertEqual(video_item["start_time_seconds"], 2.0)

    def test_execute_uses_v2_submit_poll_extract_and_shared_download(self):
        node = nodes.MinimaxH3V2Video()
        final = {
            "task": {
                "status": "succeeded",
                "content": {"url": "https://cdn.test/result.mp4"},
            },
        }
        with (
            patch.object(nodes, "get_config", return_value=CONFIG),
            patch.object(node, "collect_media", return_value={}),
            patch.object(node, "build_payload", return_value={"model": "MiniMax-H3"}),
            patch.object(
                nodes, "submit_minimax_h3_v2_task", return_value="task-test"
            ) as submit,
            patch.object(nodes, "poll_minimax_h3_v2_task", return_value=final) as poll,
            patch.object(
                nodes, "download_video", return_value="video-value"
            ) as download,
        ):
            result = node.execute(**base_kwargs(seed=7))

        self.assertEqual(
            result["result"][:3],
            (
                "video-value",
                "https://cdn.test/result.mp4",
                "task-test",
            ),
        )
        submit.assert_called_once()
        poll.assert_called_once()
        download.assert_called_once_with(
            "https://cdn.test/result.mp4",
            logger_prefix="Minimax_H3_V2_video",
        )


class MiniMaxH3V2ClientTests(unittest.TestCase):
    def test_submit_uses_v2_endpoint_and_exact_payload(self):
        session = FakeSession(post_response=FakeResponse(data={"task_id": "task-test"}))
        payload = {
            "model": "MiniMax-H3",
            "content": [{"type": "text", "text": "test"}],
            "resolution": "480P",
            "duration": 4,
            "ratio": "16:9",
        }
        with patch.object(client, "_session", return_value=session):
            task_id = client.submit_minimax_h3_v2_task(payload, CONFIG)

        self.assertEqual(task_id, "task-test")
        self.assertEqual(
            session.post_calls[0][0],
            "https://example.test/v2/video_generation",
        )
        self.assertEqual(session.post_calls[0][1]["json"], payload)

    def test_ambiguous_submit_recovers_header_without_replaying(self):
        session = FakeSession(
            post_response=FakeResponse(
                status_code=503,
                data={"error": {"message": "upstream timeout"}},
                headers={"X-Task-Id": "recovered-task"},
            )
        )
        with patch.object(client, "_session", return_value=session):
            task_id = client.submit_minimax_h3_v2_task(
                {"model": "MiniMax-H3", "content": [{"type": "text", "text": "x"}]},
                CONFIG,
            )

        self.assertEqual(task_id, "recovered-task")
        self.assertEqual(len(session.post_calls), 1)

    def test_poll_uses_v2_query_path_and_documented_statuses(self):
        queued = FakeResponse(data={"task": {"status": "queued"}})
        succeeded = FakeResponse(
            data={
                "task": {
                    "status": "succeeded",
                    "content": {"url": "https://cdn.test/result.mp4"},
                },
            }
        )
        session = FakeSession(get_responses=[queued, succeeded])
        progress = []
        with (
            patch.object(client, "_session", return_value=session),
            patch.object(client, "cooperative_sleep", return_value=None) as sleep,
        ):
            result = client.poll_minimax_h3_v2_task(
                "task-test",
                CONFIG,
                on_progress=progress.append,
            )

        self.assertEqual(result, succeeded._data)
        self.assertEqual(
            session.get_calls[0][0],
            "https://example.test/v2/query/video_generation/task-test",
        )
        self.assertEqual(progress, [10, 100])
        self.assertTrue(all(call.args[0] >= 5 for call in sleep.call_args_list))
        self.assertEqual(
            client.extract_minimax_h3_v2_video_url(result),
            "https://cdn.test/result.mp4",
        )

    def test_cancelled_task_raises_business_error(self):
        session = FakeSession(
            get_responses=[
                FakeResponse(
                    data={
                        "task": {
                            "status": "cancelled",
                            "error": {
                                "code": "cancelled",
                                "message": "cancelled upstream",
                            },
                        },
                    }
                )
            ]
        )
        with (
            patch.object(client, "_session", return_value=session),
            patch.object(client, "cooperative_sleep", return_value=None),
        ):
            with self.assertRaisesRegex(client.SeedanceAPIError, "cancelled upstream"):
                client.poll_minimax_h3_v2_task("task-test", CONFIG)


class MiniMaxH3V2WorkflowTests(unittest.TestCase):
    def test_four_safe_workflows_cover_text_keyframes_references_and_drive(self):
        expected = {
            "MiniMax-H3文生视频.json": set(),
            "MiniMax-H3首尾帧视频.json": {"first_frame", "last_frame"},
            "MiniMax-H3多模态参考视频.json": {"image1", "video1", "audio1"},
            "MiniMax-H3驱动音频视频.json": {"image1", "drive_audio"},
        }
        for filename, required_links in expected.items():
            with self.subTest(workflow=filename):
                path = PACKAGE_ROOT / "examples" / filename
                source = path.read_text(encoding="utf-8")
                workflow = json.loads(source)
                self.assertNotIn("sk-", source)
                node = next(
                    item
                    for item in workflow["nodes"]
                    if item["type"] == "Minimax_H3_V2_Video"
                )
                self.assertEqual(node["widgets_values"][0], "MiniMax-H3")
                config = next(
                    item
                    for item in workflow["nodes"]
                    if item["type"] == "Seedance_Config"
                )
                self.assertEqual(config["widgets_values"][1], "")
                linked_names = {
                    item["name"]
                    for item in node["inputs"]
                    if item.get("link") is not None
                }
                self.assertTrue(required_links.issubset(linked_names))
                self.assertIn("api_config", linked_names)

                self.assertTrue(
                    any(
                        item[1] == node["id"] and item[3] != node["id"]
                        for item in workflow["links"]
                    )
                )


if __name__ == "__main__":
    unittest.main()
