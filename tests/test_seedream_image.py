import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ComfyUI_Seedance import nodes
from ComfyUI_Seedance.core import client


class FakeResponse:
    def __init__(self, status_code=200, data=None, content=b""):
        self.status_code = status_code
        self._data = data or {}
        self.content = content
        self.text = "{}" if data is not None else ""

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


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


CONFIG = {
    "base_url": "https://example.test",
    "api_key": "test-key",
    "timeout": 60,
    "poll_interval": 0,
    "max_poll_time": 60,
}


class ImageClientTests(unittest.TestCase):
    def test_image_submit_uses_image_endpoint(self):
        session = FakeSession(
            post_response=FakeResponse(data={"id": "image-task", "task_id": "image-task"})
        )
        with patch.object(client, "_session", return_value=session):
            task_id = client.submit_image_task(
                {"model": nodes.SEEDREAM_T2I_MODEL, "prompt": "valid prompt"},
                CONFIG,
            )

        self.assertEqual(task_id, "image-task")
        self.assertEqual(
            session.post_calls[0][0],
            "https://example.test/v1/image/generations",
        )

    def test_existing_video_submit_still_uses_video_endpoint(self):
        session = FakeSession(post_response=FakeResponse(data={"id": "video-task"}))
        with patch.object(client, "_session", return_value=session):
            task_id = client.submit_task(
                {"model": "seedance-2.0-mini-t2v", "prompt": "test"},
                CONFIG,
            )

        self.assertEqual(task_id, "video-task")
        self.assertEqual(session.post_calls[0][0], "https://example.test/v1/videos")

    def test_image_poll_reads_documented_nested_status_and_url(self):
        response = {
            "code": "success",
            "data": {
                "task_id": "image-task",
                "status": "SUCCESS",
                "progress": "100%",
                "result_url": "https://cdn.test/result.png",
            },
        }
        session = FakeSession(get_responses=[FakeResponse(data=response)])
        progress = []
        with patch.object(client, "_session", return_value=session), patch.object(
            client.time, "sleep", return_value=None
        ):
            result = client.poll_image_task(
                "image-task", CONFIG, on_progress=progress.append
            )

        self.assertEqual(result, response)
        self.assertEqual(progress, [100])
        self.assertEqual(client.extract_image_url(result), "https://cdn.test/result.png")
        self.assertEqual(
            session.get_calls[0][0],
            "https://example.test/v1/image/generations/image-task",
        )

    def test_extract_image_url_supports_documented_content_fallback(self):
        response = {
            "data": {
                "status": "SUCCESS",
                "data": {"content": {"image_url": "https://cdn.test/fallback.jpg"}},
            }
        }
        self.assertEqual(
            client.extract_image_url(response), "https://cdn.test/fallback.jpg"
        )

    def test_download_image_returns_comfyui_tensor(self):
        buffer = io.BytesIO()
        Image.new("RGB", (3, 2), (255, 128, 0)).save(buffer, format="PNG")
        session = FakeSession(get_responses=[FakeResponse(content=buffer.getvalue())])

        with patch.object(client, "_session", return_value=session):
            tensor = client.download_image("https://cdn.test/result.png")

        self.assertEqual(tuple(tensor.shape), (1, 2, 3, 3))
        self.assertEqual(tensor.dtype, torch.float32)
        self.assertAlmostEqual(float(tensor[0, 0, 0, 0]), 1.0)


class ImageNodeTests(unittest.TestCase):
    def test_payload_omits_images_for_text_to_image(self):
        node = nodes.SeedreamV5ProImage()
        payload = node._build_payload("valid prompt", "2k", 1024, 1024, "png", [])

        self.assertEqual(payload["model"], "seedream-v5-pro-t2i")
        self.assertNotIn("images", payload)
        self.assertEqual(payload["metadata"], {"resolution": "2k", "output_format": "png"})

    def test_payload_includes_references_for_image_editing(self):
        node = nodes.SeedreamV5ProImage()
        payload = node._build_payload(
            "edit this image",
            "custom",
            1280,
            720,
            "jpeg",
            ["https://cdn.test/reference.png"],
        )

        self.assertEqual(payload["images"], ["https://cdn.test/reference.png"])
        self.assertEqual(payload["model"], "seedream-v5-pro-i2i")
        self.assertEqual(
            payload["metadata"],
            {"width": 1280, "height": 720, "output_format": "jpeg"},
        )

    def test_execute_uploads_reference_and_returns_image_outputs(self):
        node = nodes.SeedreamV5ProImage()
        result_tensor = torch.zeros((1, 4, 4, 3), dtype=torch.float32)
        final_response = {
            "data": {
                "status": "SUCCESS",
                "result_url": "https://cdn.test/result.png",
            }
        }

        with patch.object(nodes, "get_config", return_value=CONFIG), patch.object(
            nodes, "upload_media", return_value="https://cdn.test/reference.png"
        ) as upload, patch.object(
            nodes, "submit_image_task", return_value="image-task"
        ) as submit, patch.object(
            nodes, "poll_image_task", return_value=final_response
        ), patch.object(
            nodes, "download_image", return_value=result_tensor
        ):
            output = node.execute(
                prompt="edit this image",
                resolution="1k",
                width=1024,
                height=1024,
                output_format="png",
                image1=torch.zeros((1, 8, 8, 3), dtype=torch.float32),
            )

        upload.assert_called_once()
        submitted_payload = submit.call_args.args[0]
        self.assertEqual(
            submitted_payload["images"], ["https://cdn.test/reference.png"]
        )
        self.assertIs(output["result"][0], result_tensor)
        self.assertEqual(output["result"][1:3], ("https://cdn.test/result.png", "image-task"))

    def test_prompt_validation_matches_documented_range(self):
        self.assertIsNot(
            nodes.SeedreamV5ProImage.VALIDATE_INPUTS(
                prompt="four",
                resolution="1k",
                width=1024,
                height=1024,
                output_format="png",
            ),
            True,
        )
        self.assertIs(
            nodes.SeedreamV5ProImage.VALIDATE_INPUTS(
                prompt="valid",
                resolution="1k",
                width=1024,
                height=1024,
                output_format="png",
            ),
            True,
        )


if __name__ == "__main__":
    unittest.main()
