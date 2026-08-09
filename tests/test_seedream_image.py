import os
import io
import importlib.util
import builtins
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import torch
from PIL import Image


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT.parent))

try:
    from ComfyUI_Seedance import nodes
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
    from ComfyUI_Seedance import nodes
    from ComfyUI_Seedance.core import client


class FakeResponse:
    def __init__(self, status_code=200, data=None, content=b"", text=None):
        self.status_code = status_code
        self._data = data or {}
        self.content = content
        self.text = text if text is not None else ("{}" if data is not None else "")

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class StreamingResponse(FakeResponse):
    def __init__(self, chunks, **kwargs):
        super().__init__(**kwargs)
        self.chunks = list(chunks)
        self.closed = False

    def iter_content(self, chunk_size):
        yield from self.chunks

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


CONFIG = {
    "base_url": "https://example.test",
    "api_key": "test-key",
    "timeout": 60,
    "poll_interval": 0,
    "max_poll_time": 60,
}


class ImageClientTests(unittest.TestCase):
    def test_session_does_not_require_truststore(self):
        real_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "truststore":
                raise AssertionError("truststore should not be imported")
            return real_import(name, *args, **kwargs)

        with (
            patch.object(client, "_session_local", threading.local()),
            patch.object(builtins, "__import__", side_effect=guarded_import),
        ):
            session = client._session()

        self.assertIsNotNone(session)

    def test_http_sessions_are_isolated_per_worker_thread(self):
        session_local = threading.local()
        created = [MagicMock(), MagicMock()]
        child_sessions = []

        def create_child_session():
            child_sessions.append(client._session())
            child_sessions.append(client._session())

        with (
            patch.object(client, "_session_local", session_local),
            patch.object(client.requests, "Session", side_effect=created),
            patch.object(
                client, "_windows_cert_store_context", return_value=(None, 0)
            ),
            patch.dict(
                os.environ,
                {
                    "SEEDANCE_CA_BUNDLE": "",
                    "SEEDANCE_SSL_VERIFY": "",
                },
            ),
        ):
            main_session = client._session()
            self.assertIs(client._session(), main_session)
            worker = threading.Thread(target=create_child_session)
            worker.start()
            worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(child_sessions), 2)
        self.assertIs(child_sessions[0], child_sessions[1])
        self.assertIsNot(child_sessions[0], main_session)

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

    def test_download_image_retries_after_total_stream_timeout(self):
        buffer = io.BytesIO()
        Image.new("RGB", (3, 2), (255, 128, 0)).save(buffer, format="PNG")
        timed_out = StreamingResponse([b"partial"])
        succeeded = StreamingResponse([buffer.getvalue()])
        session = FakeSession(get_responses=[timed_out, succeeded])

        with (
            patch.object(client, "_session", return_value=session),
            patch.object(client, "cooperative_sleep", return_value=None),
            patch.object(client.time, "monotonic", side_effect=[0, 46, 46, 47]),
        ):
            tensor = client.download_image(
                "https://cdn.test/result.png",
                timeout=45,
                max_retries=2,
            )

        self.assertEqual(tuple(tensor.shape), (1, 2, 3, 3))
        self.assertEqual(len(session.get_calls), 2)
        self.assertTrue(timed_out.closed)
        self.assertTrue(succeeded.closed)
        for _url, kwargs in session.get_calls:
            self.assertTrue(kwargs["stream"])
            self.assertEqual(kwargs["timeout"], (15.0, 15.0))


class AudioClientTests(unittest.TestCase):
    def test_audio_submit_uses_audio_endpoint(self):
        session = FakeSession(
            post_response=FakeResponse(data={"id": "audio-task", "task_id": "audio-task"})
        )
        with patch.object(client, "_session", return_value=session):
            task_id = client.submit_audio_task(
                {"model": nodes.DOUBAO_SEED_AUDIO_MODEL, "prompt": "valid audio prompt"},
                CONFIG,
            )

        self.assertEqual(task_id, "audio-task")
        self.assertEqual(
            session.post_calls[0][0],
            "https://example.test/v1/audio/generations",
        )

    def test_audio_poll_reads_documented_nested_status_and_url(self):
        response = {
            "code": "success",
            "data": {
                "task_id": "audio-task",
                "status": "SUCCESS",
                "progress": "100%",
                "result_url": "https://cdn.test/result.wav",
            },
        }
        session = FakeSession(get_responses=[FakeResponse(data=response)])
        progress = []
        with patch.object(client, "_session", return_value=session), patch.object(
            client.time, "sleep", return_value=None
        ):
            result = client.poll_audio_task(
                "audio-task", CONFIG, on_progress=progress.append
            )

        self.assertEqual(result, response)
        self.assertEqual(progress, [100])
        self.assertEqual(client.extract_audio_url(result), "https://cdn.test/result.wav")
        self.assertEqual(
            session.get_calls[0][0],
            "https://example.test/v1/audio/generations/audio-task",
        )

    def test_extract_audio_url_supports_documented_content_fallback(self):
        response = {
            "data": {
                "status": "SUCCESS",
                "data": {"content": {"audio_url": "https://cdn.test/fallback.mp3"}},
            }
        }
        self.assertEqual(
            client.extract_audio_url(response), "https://cdn.test/fallback.mp3"
        )

    def test_transcription_uses_multipart_endpoint(self):
        session = FakeSession(post_response=FakeResponse(data={"text": "hello world"}))
        with patch.object(client, "_session", return_value=session):
            text, response = client.transcribe_audio(
                b"RIFF....WAVE",
                "input.wav",
                "audio/wav",
                nodes.WHISPER_TRANSCRIPTION_MODEL,
                "json",
                CONFIG,
            )

        self.assertEqual(text, "hello world")
        self.assertIn("hello world", response)
        url, kwargs = session.post_calls[0]
        self.assertEqual(url, "https://example.test/v1/audio/transcriptions")
        self.assertEqual(kwargs["data"]["model"], "whisper-1")
        self.assertEqual(kwargs["data"]["response_format"], "json")
        self.assertEqual(kwargs["files"]["file"], ("input.wav", b"RIFF....WAVE", "audio/wav"))
        self.assertNotIn("Content-Type", kwargs["headers"])


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

    def test_dola_payload_uses_overseas_text_to_image_model(self):
        node = nodes.SeedreamV5ProImage()
        payload = node._build_payload(
            "valid overseas prompt",
            "1k",
            1024,
            1024,
            "jpeg",
            [],
            nodes.SEEDREAM_FAMILY_DOLA,
        )

        self.assertEqual(payload["model"], "dola-seedream-5.0-pro-t2i")
        self.assertNotIn("images", payload)
        self.assertEqual(payload["metadata"], {"resolution": "1k", "output_format": "jpeg"})

    def test_dola_payload_uses_overseas_image_to_image_model(self):
        node = nodes.SeedreamV5ProImage()
        payload = node._build_payload(
            "edit this image overseas",
            "1k",
            1024,
            1024,
            "png",
            ["https://cdn.test/reference.png"],
            nodes.SEEDREAM_FAMILY_DOLA,
        )

        self.assertEqual(payload["model"], "dola-seedream-5.0-pro-i2i")
        self.assertEqual(payload["images"], ["https://cdn.test/reference.png"])
        self.assertEqual(payload["metadata"], {"resolution": "1k", "output_format": "png"})

    def test_rejects_unknown_seedream_model_family(self):
        self.assertIsNot(
            nodes.SeedreamV5ProImage.VALIDATE_INPUTS(
                prompt="valid",
                resolution="1k",
                width=1024,
                height=1024,
                output_format="png",
                model_family="unknown-family",
            ),
            True,
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
        self.assertIs(
            nodes.SeedreamV5ProImage.VALIDATE_INPUTS(
                prompt="",
                resolution="1k",
                width=1024,
                height=1024,
                output_format="png",
            ),
            True,
        )
        self.assertIsNot(
            nodes.SeedreamV5ProImage.VALIDATE_INPUTS(
                prompt="",
                resolution="1k",
                width=1024,
                height=1024,
                output_format="png",
                strict=True,
            ),
            True,
        )
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

    def test_seedream_execute_still_rejects_empty_runtime_prompt(self):
        node = nodes.SeedreamV5ProImage()
        with self.assertRaises(client.SeedanceAPIError):
            node.execute(
                prompt="",
                resolution="1k",
                width=1024,
                height=1024,
                output_format="png",
            )

    def test_zhenzhen_image_g2_text_to_image_payload(self):
        node = nodes.ZhenzhenImageG2()
        payload = node._build_payload(
            nodes.ZHENZHEN_IMAGE_G2_T2I_MODEL,
            "clean product photo on a white background",
            "1k",
            "adaptive",
            ["https://cdn.test/ignored.png"],
            size="1:1",
            n=1,
        )

        self.assertEqual(payload["model"], "zhenzhen-image-g2-t2i")
        self.assertEqual(payload["prompt"], "clean product photo on a white background")
        self.assertEqual(payload["metadata"], {"resolution": "1k"})
        self.assertNotIn("images", payload)

    def test_zhenzhen_image_g2_image_to_image_payload(self):
        node = nodes.ZhenzhenImageG2()
        payload = node._build_payload(
            nodes.ZHENZHEN_IMAGE_G2_I2I_MODEL,
            "turn this into a glossy blue app icon",
            "1k",
            "1:1",
            ["https://cdn.test/reference.png"],
            size="1:1",
            n=1,
        )

        self.assertEqual(payload["model"], "zhenzhen-image-g2-i2i")
        self.assertEqual(payload["images"], ["https://cdn.test/reference.png"])
        self.assertEqual(payload["metadata"], {"resolution": "1k", "ratio": "1:1"})

    def test_zhenzhen_image_g_lowprice_text_payload(self):
        node = nodes.ZhenzhenImageG2()
        payload = node._build_payload(
            nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL,
            "clean product photo on a white background",
            "4k",
            "adaptive",
            [],
            size="2048x1024",
            n=10,
        )

        self.assertEqual(payload["model"], "zhenzhen-image-g-v2-lowprice")
        self.assertEqual(payload["metadata"], {"resolution": "4k"})
        self.assertEqual(payload["size"], "2048x1024")
        self.assertEqual(payload["n"], 10)
        self.assertNotIn("ratio", payload["metadata"])
        self.assertNotIn("images", payload)

    def test_zhenzhen_image_g_lowprice_forwards_optional_images(self):
        node = nodes.ZhenzhenImageG2()
        references = [f"https://cdn.test/reference-{index}.png" for index in range(1, 17)]
        payload = node._build_payload(
            nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL,
            "edit the reference into a product icon",
            "2k",
            "1:1",
            references,
            size="16:9",
            n=3,
        )

        self.assertEqual(payload["model"], "zhenzhen-image-g-v2-lowprice")
        self.assertEqual(payload["images"], references)
        self.assertEqual(payload["metadata"], {"resolution": "2k"})
        self.assertEqual(payload["size"], "16:9")
        self.assertEqual(payload["n"], 3)

    def test_zhenzhen_image_g_lowprice_custom_size_supports_ratio_and_wxh(self):
        node = nodes.ZhenzhenImageG2()
        for custom_size, expected in (
            ("5:4", "5:4"),
            ("2048X1024", "2048x1024"),
        ):
            with self.subTest(custom_size=custom_size):
                payload = node._build_payload(
                    nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL,
                    "clean product photo",
                    "2k",
                    "adaptive",
                    [],
                    size="custom",
                    custom_size=custom_size,
                    n=1,
                )
                self.assertEqual(payload["size"], expected)
                self.assertNotIn("custom_size", payload)

    def test_zhenzhen_image_g2_image_to_image_requires_reference(self):
        node = nodes.ZhenzhenImageG2()
        with self.assertRaises(client.SeedanceAPIError):
            node._build_payload(
                nodes.ZHENZHEN_IMAGE_G2_I2I_MODEL,
                "valid prompt",
                "1k",
                "adaptive",
                [],
                size="1:1",
                n=1,
            )

    def test_zhenzhen_image_g_default_and_input_limits_match_documented_models(self):
        inputs = nodes.ZhenzhenImageG2.INPUT_TYPES()
        self.assertEqual(
            inputs["required"]["model"][1]["default"],
            nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL,
        )
        self.assertEqual(
            inputs["required"]["model"][0][0],
            nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL,
        )
        self.assertEqual(
            inputs["required"]["resolution"][0],
            nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_RESOLUTIONS,
        )
        self.assertEqual(
            inputs["required"]["size"][0],
            nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_SIZES,
        )
        self.assertEqual(inputs["required"]["size"][1]["default"], "1:1")
        self.assertIn("custom_size", inputs["required"])
        self.assertEqual(
            [name for name in inputs["optional"] if name.startswith("image")],
            [f"image{index}" for index in range(1, 17)],
        )

    def test_zhenzhen_image_g2_validation_matches_documented_limits(self):
        self.assertIs(
            nodes.ZhenzhenImageG2.VALIDATE_INPUTS(
                model=nodes.ZHENZHEN_IMAGE_G2_T2I_MODEL,
                prompt="",
                resolution="1k",
                ratio="adaptive",
            ),
            True,
        )
        self.assertIsNot(
            nodes.ZhenzhenImageG2.VALIDATE_INPUTS(
                model=nodes.ZHENZHEN_IMAGE_G2_T2I_MODEL,
                prompt="",
                resolution="1k",
                ratio="adaptive",
                strict=True,
            ),
            True,
        )
        self.assertIsNot(
            nodes.ZhenzhenImageG2.VALIDATE_INPUTS(
                model=nodes.ZHENZHEN_IMAGE_G2_T2I_MODEL,
                prompt="x" * (nodes.ZHENZHEN_IMAGE_G2_PROMPT_MAX_LENGTH + 1),
                resolution="1k",
                ratio="adaptive",
            ),
            True,
        )
        self.assertIsNot(
            nodes.ZhenzhenImageG2.VALIDATE_INPUTS(
                model=nodes.ZHENZHEN_IMAGE_G2_T2I_MODEL,
                prompt="valid prompt",
                resolution="2k",
                ratio="adaptive",
            ),
            True,
        )
        self.assertIsNot(
            nodes.ZhenzhenImageG2.VALIDATE_INPUTS(
                model=nodes.ZHENZHEN_IMAGE_G2_T2I_MODEL,
                prompt="valid prompt",
                resolution="1k",
                ratio="bad-ratio",
            ),
            True,
        )
        for resolution in nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_RESOLUTIONS:
            with self.subTest(resolution=resolution):
                self.assertIs(
                    nodes.ZhenzhenImageG2.VALIDATE_INPUTS(
                        model=nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL,
                        prompt="valid prompt",
                        resolution=resolution,
                        ratio="stale-hidden-value",
                        size="16:9",
                        n=10,
                    ),
                    True,
                )
        for invalid_prompt in (
            "四个字符",
            "x" * (nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_PROMPT_MAX_LENGTH + 1),
        ):
            with self.subTest(invalid_prompt_length=len(invalid_prompt)):
                self.assertIs(
                    nodes.ZhenzhenImageG2.VALIDATE_INPUTS(
                        model=nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL,
                        prompt=invalid_prompt,
                        resolution="1k",
                        size="1:1",
                        n=1,
                    ),
                    True,
                )
                self.assertIsNot(
                    nodes.ZhenzhenImageG2.VALIDATE_INPUTS(
                        model=nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL,
                        prompt=invalid_prompt,
                        resolution="1k",
                        size="1:1",
                        n=1,
                        strict=True,
                    ),
                    True,
                )
        self.assertIs(
            nodes.ZhenzhenImageG2.VALIDATE_INPUTS(
                model=nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL,
                prompt="五个字符了",
                resolution="1k",
                size="1:1",
                n=1,
            ),
            True,
        )
        for invalid_size in ("", "square", "0:1", "1024x0"):
            with self.subTest(invalid_size=invalid_size):
                self.assertIsNot(
                    nodes.ZhenzhenImageG2.VALIDATE_INPUTS(
                        model=nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL,
                        prompt="valid prompt",
                        resolution="2k",
                        size=invalid_size,
                        n=1,
                    ),
                    True,
                )
        self.assertIs(
            nodes.ZhenzhenImageG2.VALIDATE_INPUTS(
                model=nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL,
                prompt="valid prompt",
                resolution="2k",
                size="custom",
                custom_size="5:4",
                n=1,
                strict=True,
            ),
            True,
        )
        self.assertIsNot(
            nodes.ZhenzhenImageG2.VALIDATE_INPUTS(
                model=nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL,
                prompt="valid prompt",
                resolution="2k",
                size="custom",
                custom_size="",
                n=1,
                strict=True,
            ),
            True,
        )
        self.assertIsNot(
            nodes.ZhenzhenImageG2.VALIDATE_INPUTS(
                model=nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL,
                prompt="valid prompt",
                resolution="8k",
                size="1:1",
                n=1,
            ),
            True,
        )
        self.assertIsNot(
            nodes.ZhenzhenImageG2.VALIDATE_INPUTS(
                model=nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL,
                prompt="valid prompt",
                resolution="1k",
                size="1:1",
                n=11,
            ),
            True,
        )

    def test_zhenzhen_image_g2_execute_uploads_reference_and_returns_image_outputs(self):
        node = nodes.ZhenzhenImageG2()
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
                model=nodes.ZHENZHEN_IMAGE_G2_I2I_MODEL,
                prompt="turn this into a glossy blue app icon",
                resolution="1k",
                ratio="1:1",
                size="1:1",
                n=1,
                image1=torch.zeros((1, 8, 8, 3), dtype=torch.float32),
            )

        upload.assert_called_once()
        submitted_payload = submit.call_args.args[0]
        self.assertEqual(submitted_payload["model"], "zhenzhen-image-g2-i2i")
        self.assertEqual(submitted_payload["images"], ["https://cdn.test/reference.png"])
        self.assertEqual(submitted_payload["metadata"], {"resolution": "1k", "ratio": "1:1"})
        self.assertIs(output["result"][0], result_tensor)
        self.assertEqual(output["result"][1:3], ("https://cdn.test/result.png", "image-task"))

    def test_zhenzhen_image_gk_v15_text_payload(self):
        node = nodes.ZhenzhenImageGKV15()
        payload = node._build_payload(
            nodes.ZHENZHEN_IMAGE_GK_V15_MODEL,
            "clean product photo on a white background",
            "16:9",
            2,
            [],
        )

        self.assertEqual(payload["model"], "zhenzhen-image-gk-v15")
        self.assertEqual(payload["prompt"], "clean product photo on a white background")
        self.assertEqual(payload["size"], "16:9")
        self.assertEqual(payload["n"], 2)
        self.assertNotIn("images", payload)
        self.assertNotIn("metadata", payload)

    def test_zhenzhen_image_gk_v15_edit_payload_uses_first_image(self):
        node = nodes.ZhenzhenImageGKV15()
        payload = node._build_payload(
            nodes.ZHENZHEN_IMAGE_GK_V15_EDIT_MODEL,
            "change the background",
            "1:1",
            1,
            ["https://cdn.test/a.png", "https://cdn.test/b.png"],
        )

        self.assertEqual(payload["model"], "zhenzhen-image-gk-v15-edit")
        self.assertEqual(payload["images"], ["https://cdn.test/a.png"])
        self.assertEqual(payload["size"], "1:1")
        self.assertEqual(payload["n"], 1)

    def test_zhenzhen_image_gk_v15_edit_requires_reference(self):
        node = nodes.ZhenzhenImageGKV15()
        with self.assertRaises(client.SeedanceAPIError):
            node._build_payload(
                nodes.ZHENZHEN_IMAGE_GK_V15_EDIT_MODEL,
                "change the background",
                "1:1",
                1,
                [],
            )

    def test_zhenzhen_image_gk_v15_validation_matches_documented_limits(self):
        self.assertIs(
            nodes.ZhenzhenImageGKV15.VALIDATE_INPUTS(
                model=nodes.ZHENZHEN_IMAGE_GK_V15_MODEL,
                prompt="",
                size="1:1",
                n=1,
            ),
            True,
        )
        self.assertIsNot(
            nodes.ZhenzhenImageGKV15.VALIDATE_INPUTS(
                model=nodes.ZHENZHEN_IMAGE_GK_V15_MODEL,
                prompt="",
                size="1:1",
                n=1,
                strict=True,
            ),
            True,
        )
        self.assertIsNot(
            nodes.ZhenzhenImageGKV15.VALIDATE_INPUTS(
                model=nodes.ZHENZHEN_IMAGE_GK_V15_MODEL,
                prompt="valid prompt",
                size="4:5",
                n=1,
            ),
            True,
        )
        self.assertIsNot(
            nodes.ZhenzhenImageGKV15.VALIDATE_INPUTS(
                model=nodes.ZHENZHEN_IMAGE_GK_V15_MODEL,
                prompt="valid prompt",
                size="1:1",
                n=11,
            ),
            True,
        )
        self.assertIsNot(
            nodes.ZhenzhenImageGKV15.VALIDATE_INPUTS(
                model=nodes.ZHENZHEN_IMAGE_GK_V15_EDIT_MODEL,
                prompt="valid prompt",
                size="1:1",
                n=1,
                image1=None,
                strict=True,
            ),
            True,
        )

    def test_zhenzhen_image_gk_v15_execute_uploads_reference_and_returns_image_outputs(self):
        node = nodes.ZhenzhenImageGKV15()
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
                model=nodes.ZHENZHEN_IMAGE_GK_V15_EDIT_MODEL,
                prompt="change the background",
                size="1:1",
                n=1,
                image1=torch.zeros((1, 8, 8, 3), dtype=torch.float32),
            )

        upload.assert_called_once()
        submitted_payload = submit.call_args.args[0]
        self.assertEqual(submitted_payload["model"], "zhenzhen-image-gk-v15-edit")
        self.assertEqual(submitted_payload["images"], ["https://cdn.test/reference.png"])
        self.assertEqual(submitted_payload["size"], "1:1")
        self.assertEqual(submitted_payload["n"], 1)
        self.assertIs(output["result"][0], result_tensor)
        self.assertEqual(output["result"][1:3], ("https://cdn.test/result.png", "image-task"))

    def test_zhenzhen_video_payload_uses_prompt_and_metadata(self):
        node = nodes.ZhenzhenVideoGOmniFlash()
        payload = node.build_payload(
            {
                "model": nodes.ZHENZHEN_VIDEO_G_OMNI_FLASH_MODEL,
                "prompt": "a calm product reveal shot",
                "seconds": "4",
                "resolution": "720p",
                "ratio": "16:9",
                "negative_prompt": "",
                "seed": -1,
            },
            {},
        )

        self.assertEqual(payload["model"], "zhenzhen-video-g-omni-flash")
        self.assertEqual(payload["prompt"], "a calm product reveal shot")
        self.assertEqual(payload["seconds"], "4")
        self.assertEqual(payload["metadata"], {"resolution": "720p", "ratio": "16:9"})
        self.assertNotIn("images", payload)

    def test_zhenzhen_video_payload_forwards_optional_images_and_seed(self):
        node = nodes.ZhenzhenVideoGKV15()
        payload = node.build_payload(
            {
                "model": nodes.ZHENZHEN_VIDEO_GK_V15_MODEL,
                "prompt": "animate the reference with gentle camera movement",
                "seconds": "6",
                "resolution": "1080p",
                "ratio": "adaptive",
                "negative_prompt": "blur",
                "seed": 42,
            },
            {"images": ["https://cdn.test/start.png", "https://cdn.test/end.png"]},
        )

        self.assertEqual(payload["model"], "zhenzhen-video-gk-v15")
        self.assertEqual(payload["images"], ["https://cdn.test/start.png", "https://cdn.test/end.png"])
        self.assertEqual(
            payload["metadata"],
            {"resolution": "1080p", "negative_prompt": "blur", "seed": 42},
        )

    def test_zhenzhen_video_v31_payload_selects_model(self):
        node = nodes.ZhenzhenVideoV31()
        payload = node.build_payload(
            {
                "model": nodes.ZHENZHEN_VIDEO_V31_QUALITY_MODEL,
                "prompt": "a cinematic city sunrise",
                "seconds": "8",
                "resolution": "720p",
                "ratio": "9:16",
                "negative_prompt": "",
                "seed": -1,
            },
            {},
        )

        self.assertEqual(payload["model"], "zhenzhen-video-v31-quality")
        self.assertEqual(payload["metadata"], {"resolution": "720p", "ratio": "9:16"})

    def test_zhenzhen_video_validation_allows_linked_empty_widget_preflight(self):
        self.assertIs(
            nodes.ZhenzhenVideoV31.VALIDATE_INPUTS(
                model=nodes.ZHENZHEN_VIDEO_V31_FAST_MODEL,
                prompt="",
                seconds="8",
                resolution="720p",
                ratio="16:9",
                negative_prompt="",
                seed=-1,
            ),
            True,
        )
        self.assertIsNot(
            nodes.ZhenzhenVideoV31.VALIDATE_INPUTS(
                model=nodes.ZHENZHEN_VIDEO_V31_FAST_MODEL,
                prompt="",
                seconds="8",
                resolution="720p",
                ratio="16:9",
                negative_prompt="",
                seed=-1,
                strict=True,
            ),
            True,
        )
        self.assertIsNot(
            nodes.ZhenzhenVideoV31.VALIDATE_INPUTS(
                model=nodes.ZHENZHEN_VIDEO_V31_FAST_MODEL,
                prompt="valid prompt",
                seconds="3",
                resolution="720p",
                ratio="16:9",
                negative_prompt="",
                seed=-1,
            ),
            True,
        )


    def test_zhenzhen_image_nb_catalog_matches_documented_models(self):
        self.assertEqual(
            nodes.ZHENZHEN_IMAGE_NB_MODELS,
            [
                "zhenzhen-image-nb-flash",
                "zhenzhen-image-nb-2",
                "zhenzhen-image-nb-2-lite",
                "zhenzhen-image-nb-pro",
            ],
        )

    def test_zhenzhen_image_nb_payloads_follow_model_contracts(self):
        node = nodes.ZhenzhenImageNB()
        cases = (
            (nodes.ZHENZHEN_IMAGE_NB_FLASH_MODEL, "1k", "auto", 1),
            (nodes.ZHENZHEN_IMAGE_NB_2_MODEL, "0.5k", "1:8", 1),
            (nodes.ZHENZHEN_IMAGE_NB_2_LITE_MODEL, "1k", "8:1", 4),
            (nodes.ZHENZHEN_IMAGE_NB_PRO_MODEL, "4k", "21:9", 1),
        )
        for model, resolution, size, n in cases:
            with self.subTest(model=model):
                payload = node._build_payload(
                    model,
                    "a clean editorial product image",
                    resolution,
                    size,
                    n,
                    ["https://cdn.test/a.png", "https://cdn.test/b.png"],
                )
                self.assertEqual(payload["model"], model)
                self.assertEqual(payload["prompt"], "a clean editorial product image")
                self.assertEqual(payload["metadata"], {"resolution": resolution})
                self.assertEqual(payload["size"], size)
                self.assertEqual(payload["n"], n)
                self.assertEqual(
                    payload["images"],
                    ["https://cdn.test/a.png", "https://cdn.test/b.png"],
                )

    def test_zhenzhen_image_nb_text_payload_omits_images(self):
        payload = nodes.ZhenzhenImageNB()._build_payload(
            nodes.ZHENZHEN_IMAGE_NB_PRO_MODEL,
            "a clean editorial product image",
            "1k",
            "1:1",
            1,
            [],
        )
        self.assertNotIn("images", payload)

    def test_zhenzhen_image_nb_validation_is_model_specific(self):
        validate = nodes.ZhenzhenImageNB.VALIDATE_INPUTS
        self.assertIs(
            validate(
                model=nodes.ZHENZHEN_IMAGE_NB_FLASH_MODEL,
                prompt="valid",
                resolution="1k",
                size="auto",
                n=1,
                strict=True,
            ),
            True,
        )
        self.assertIsNot(
            validate(
                model=nodes.ZHENZHEN_IMAGE_NB_FLASH_MODEL,
                prompt="x" * 1001,
                resolution="1k",
                size="1:1",
                n=1,
                strict=True,
            ),
            True,
        )
        self.assertIsNot(
            validate(
                model=nodes.ZHENZHEN_IMAGE_NB_FLASH_MODEL,
                prompt="valid",
                resolution="2k",
                size="1:1",
                n=1,
            ),
            True,
        )
        self.assertIs(
            validate(
                model=nodes.ZHENZHEN_IMAGE_NB_2_LITE_MODEL,
                prompt="valid",
                resolution="1k",
                size="1:8",
                n=4,
            ),
            True,
        )
        self.assertIsNot(
            validate(
                model=nodes.ZHENZHEN_IMAGE_NB_PRO_MODEL,
                prompt="valid",
                resolution="1k",
                size="auto",
                n=1,
            ),
            True,
        )
        self.assertIsNot(
            validate(
                model=nodes.ZHENZHEN_IMAGE_NB_PRO_MODEL,
                prompt="valid",
                resolution="1k",
                size="1:1",
                n=2,
            ),
            True,
        )

    def test_zhenzhen_image_nb_execute_uploads_references_and_returns_image(self):
        node = nodes.ZhenzhenImageNB()
        result_tensor = torch.zeros((1, 4, 4, 3), dtype=torch.float32)
        final_response = {
            "data": {
                "status": "SUCCESS",
                "result_url": "https://cdn.test/result.png",
            }
        }

        with patch.object(nodes, "get_config", return_value=CONFIG), patch.object(
            nodes, "upload_media", side_effect=[
                "https://cdn.test/a.png",
                "https://cdn.test/b.png",
            ]
        ) as upload, patch.object(
            nodes, "submit_image_task", return_value="image-task"
        ) as submit, patch.object(
            nodes, "poll_image_task", return_value=final_response
        ), patch.object(
            nodes, "download_image", return_value=result_tensor
        ):
            output = node.execute(
                model=nodes.ZHENZHEN_IMAGE_NB_2_LITE_MODEL,
                prompt="edit the product into a studio scene",
                resolution="1k",
                size="16:9",
                n=1,
                image1=torch.zeros((1, 8, 8, 3), dtype=torch.float32),
                image3=torch.zeros((1, 8, 8, 3), dtype=torch.float32),
            )

        self.assertEqual(upload.call_count, 2)
        self.assertEqual(
            submit.call_args.args[0]["images"],
            ["https://cdn.test/a.png", "https://cdn.test/b.png"],
        )
        self.assertIs(output["result"][0], result_tensor)
        self.assertEqual(output["result"][1:3], ("https://cdn.test/result.png", "image-task"))

    def test_zhenzhen_video_v31_contract_uses_fixed_duration_and_model_limits(self):
        input_types = nodes.ZhenzhenVideoV31.INPUT_TYPES()
        self.assertEqual(input_types["required"]["seconds"][0], ["8"])
        self.assertEqual(
            input_types["required"]["resolution"][0],
            ["720p", "1080p", "4k"],
        )
        self.assertEqual(input_types["required"]["ratio"][0], ["16:9", "9:16"])
        self.assertIn("image3", input_types["optional"])

        node = nodes.ZhenzhenVideoV31()
        lite_payload = node.build_payload(
            {
                "model": nodes.ZHENZHEN_VIDEO_V31_LITE_MODEL,
                "prompt": "a cinematic city sunrise",
                "seconds": "8",
                "resolution": "720p",
                "ratio": "16:9",
                "negative_prompt": "",
                "seed": -1,
            },
            {},
        )
        self.assertEqual(lite_payload["model"], "zhenzhen-video-v31-lite")
        self.assertEqual(lite_payload["seconds"], "8")
        self.assertNotIn("images", lite_payload)

        fast_payload = node.build_payload(
            {
                "model": nodes.ZHENZHEN_VIDEO_V31_FAST_MODEL,
                "prompt": "a product reference sequence",
                "seconds": "8",
                "resolution": "4k",
                "ratio": "9:16",
                "negative_prompt": "",
                "seed": -1,
            },
            {"images": ["a", "b", "c"]},
        )
        self.assertEqual(fast_payload["images"], ["a", "b", "c"])

    def test_zhenzhen_video_v31_rejects_invalid_image_modes(self):
        node = nodes.ZhenzhenVideoV31()
        common = {
            "prompt": "valid prompt",
            "seconds": "8",
            "resolution": "720p",
            "ratio": "16:9",
            "negative_prompt": "",
            "seed": -1,
        }
        with self.assertRaises(client.SeedanceAPIError):
            node.build_payload(
                {"model": nodes.ZHENZHEN_VIDEO_V31_LITE_MODEL, **common},
                {"images": ["a"]},
            )
        with self.assertRaises(client.SeedanceAPIError):
            node.build_payload(
                {"model": nodes.ZHENZHEN_VIDEO_V31_QUALITY_MODEL, **common},
                {"images": ["a", "b", "c"]},
            )

class NewModelNodeTests(unittest.TestCase):
    def test_kling_text_to_video_payload(self):
        node = nodes.KlingVideo()
        payload = node.build_payload(
            {
                "model": "kling-v3.0-std-t2v",
                "prompt": "a compact product reveal shot",
                "seconds": "5",
                "ratio": "16:9",
                "negative_prompt": "",
            },
            {},
        )

        self.assertEqual(payload["model"], "kling-v3.0-std-t2v")
        self.assertEqual(payload["prompt"], "a compact product reveal shot")
        self.assertEqual(payload["seconds"], "5")
        self.assertEqual(payload["metadata"], {"ratio": "16:9"})
        self.assertNotIn("images", payload)

    def test_kling_image_to_video_payload_uses_first_and_optional_end_image(self):
        node = nodes.KlingVideo()
        payload = node.build_payload(
            {
                "model": "kling-v3.0-pro-i2v",
                "prompt": "move from start to end frame",
                "seconds": "5",
                "ratio": "adaptive",
                "negative_prompt": "blur",
            },
            {
                "images": [
                    "https://cdn.test/start.png",
                    "https://cdn.test/end.png",
                    "https://cdn.test/ignored.png",
                ]
            },
        )

        self.assertEqual(payload["images"], ["https://cdn.test/start.png", "https://cdn.test/end.png"])
        self.assertEqual(payload["metadata"], {"negative_prompt": "blur"})

    def test_kling_reference_to_video_payload_keeps_connected_images(self):
        node = nodes.KlingVideo()
        payload = node.build_payload(
            {
                "model": "kling-o3-4k-r2v",
                "prompt": "Use image1 as product and image2 as background",
                "seconds": "5",
                "ratio": "16:9",
                "negative_prompt": "",
            },
            {"images": ["https://cdn.test/a.png", "https://cdn.test/b.png"]},
        )

        self.assertEqual(payload["images"], ["https://cdn.test/a.png", "https://cdn.test/b.png"])
        self.assertEqual(payload["metadata"], {"ratio": "16:9"})

    def test_kling_uploads_required_image_for_i2v(self):
        node = nodes.KlingVideo()
        progress = []
        with patch.object(
            nodes, "image_to_png_bytes", return_value=b"image"
        ), patch.object(
            nodes, "upload_media", return_value="https://cdn.test/first.png"
        ) as upload:
            media = node.collect_media(
                {
                    "model": "kling-v3.0-std-i2v",
                    "image1": torch.zeros((1, 512, 512, 3), dtype=torch.float32),
                },
                CONFIG,
                progress.append,
            )

        upload.assert_called_once()
        self.assertEqual(media, {"images": ["https://cdn.test/first.png"]})
        self.assertEqual(progress, [1.0])

    def test_kling_validation_matches_documented_modes(self):
        self.assertIs(
            nodes.KlingVideo.VALIDATE_INPUTS(
                model="kling-v3.0-std-t2v",
                prompt="valid prompt",
                seconds="5",
                ratio="16:9",
                negative_prompt="",
            ),
            True,
        )
        self.assertIs(
            nodes.KlingVideo.VALIDATE_INPUTS(
                model="kling-v3.0-std-t2v",
                prompt="",
                seconds="5",
                ratio="16:9",
                negative_prompt="",
            ),
            True,
        )
        self.assertIsNot(
            nodes.KlingVideo.VALIDATE_INPUTS(
                model="kling-v3.0-std-t2v",
                prompt="",
                seconds="5",
                ratio="16:9",
                negative_prompt="",
                strict=True,
            ),
            True,
        )
        self.assertIsNot(
            nodes.KlingVideo.VALIDATE_INPUTS(
                model="kling-v3.0-std-t2v",
                prompt="valid prompt",
                seconds="6",
                ratio="16:9",
                negative_prompt="",
            ),
            True,
        )

    def test_kling_build_payload_still_rejects_empty_runtime_prompt(self):
        node = nodes.KlingVideo()
        with self.assertRaises(client.SeedanceAPIError):
            node.build_payload(
                {
                    "model": "kling-v3.0-std-t2v",
                    "prompt": "",
                    "seconds": "5",
                    "ratio": "16:9",
                    "negative_prompt": "",
                },
                {},
            )

    def test_kling_edit_payload_uses_content_video_url(self):
        node = nodes.KlingEditVideo()
        payload = node.build_payload(
            {
                "model": "kling-o3-std-edit",
                "prompt": "turn the product red",
                "seconds": "5",
            },
            {"video_url": "https://cdn.test/source.mp4"},
        )

        self.assertEqual(payload["model"], "kling-o3-std-edit")
        self.assertEqual(payload["prompt"], "turn the product red")
        self.assertEqual(payload["seconds"], "5")
        self.assertEqual(
            payload["metadata"],
            {
                "content": [
                    {
                        "type": "video_url",
                        "video_url": {"url": "https://cdn.test/source.mp4"},
                    }
                ]
            },
        )

    def test_hailuo_23_text_to_video_payload(self):
        node = nodes.Hailuo23Video()
        payload = node.build_payload(
            {
                "model": "hailuo-2.3-t2v-standard",
                "prompt": "a compact product reveal shot",
                "seconds": "6",
                "resolution": "768p",
                "ratio": "16:9",
            },
            {},
        )

        self.assertEqual(payload["model"], "hailuo-2.3-t2v-standard")
        self.assertEqual(payload["prompt"], "a compact product reveal shot")
        self.assertEqual(payload["seconds"], "6")
        self.assertEqual(payload["metadata"], {"resolution": "768p", "ratio": "16:9"})
        self.assertNotIn("images", payload)

    def test_hailuo_23_image_to_video_payload_uses_first_image_only(self):
        node = nodes.Hailuo23Video()
        payload = node.build_payload(
            {
                "model": "hailuo-2.3-fast-pro-i2v",
                "prompt": "gentle product motion",
                "seconds": "6",
                "resolution": "768p",
                "ratio": "9:16",
            },
            {
                "images": [
                    "https://cdn.test/first.png",
                    "https://cdn.test/ignored.png",
                ]
            },
        )

        self.assertEqual(payload["model"], "hailuo-2.3-fast-pro-i2v")
        self.assertEqual(payload["prompt"], "gentle product motion")
        self.assertEqual(payload["images"], ["https://cdn.test/first.png"])
        self.assertEqual(payload["metadata"], {"resolution": "768p"})

    def test_hailuo_23_uploads_valid_first_image(self):
        node = nodes.Hailuo23Video()
        progress = []
        with patch.object(
            nodes, "image_to_png_bytes", return_value=b"image"
        ), patch.object(
            nodes, "upload_media", return_value="https://cdn.test/first.png"
        ) as upload:
            media = node.collect_media(
                {
                    "model": "hailuo-2.3-i2v-standard",
                    "first_image": torch.zeros((1, 512, 512, 3), dtype=torch.float32),
                },
                CONFIG,
                progress.append,
            )

        upload.assert_called_once()
        self.assertEqual(media, {"images": ["https://cdn.test/first.png"]})
        self.assertEqual(progress, [1.0])

    def test_hailuo_23_rejects_too_small_first_image(self):
        node = nodes.Hailuo23Video()
        with self.assertRaises(nodes.SeedanceAPIError):
            node.collect_media(
                {
                    "model": "hailuo-2.3-i2v-standard",
                    "first_image": torch.zeros((1, 300, 512, 3), dtype=torch.float32),
                },
                CONFIG,
                lambda _progress: None,
            )

    def test_hailuo_23_validation_matches_documented_limits(self):
        self.assertIs(
            nodes.Hailuo23Video.VALIDATE_INPUTS(
                model="hailuo-2.3-t2v-standard",
                prompt="valid prompt",
                seconds="6",
                resolution="768p",
                ratio="16:9",
            ),
            True,
        )
        self.assertIs(
            nodes.Hailuo23Video.VALIDATE_INPUTS(
                model="hailuo-2.3-t2v-standard",
                prompt="",
                seconds="6",
                resolution="768p",
                ratio="16:9",
            ),
            True,
        )
        self.assertIsNot(
            nodes.Hailuo23Video.VALIDATE_INPUTS(
                model="hailuo-2.3-t2v-standard",
                prompt="",
                seconds="6",
                resolution="768p",
                ratio="16:9",
                strict=True,
            ),
            True,
        )
        self.assertIsNot(
            nodes.Hailuo23Video.VALIDATE_INPUTS(
                model="hailuo-2.3-t2v-standard",
                prompt="valid prompt",
                seconds="4",
                resolution="768p",
                ratio="16:9",
            ),
            True,
        )
        self.assertIsNot(
            nodes.Hailuo23Video.VALIDATE_INPUTS(
                model="hailuo-2.3-t2v-standard",
                prompt="valid prompt",
                seconds="10",
                resolution="1080p",
                ratio="16:9",
            ),
            True,
        )

    def test_hailuo_23_build_payload_still_rejects_empty_runtime_prompt(self):
        node = nodes.Hailuo23Video()
        with self.assertRaises(client.SeedanceAPIError):
            node.build_payload(
                {
                    "model": "hailuo-2.3-t2v-standard",
                    "prompt": "",
                    "seconds": "6",
                    "resolution": "768p",
                    "ratio": "16:9",
                },
                {},
            )

    def test_hailuo_h3_text_to_video_payload_matches_documented_fields(self):
        node = nodes.HailuoH3Video()
        payload = node.build_payload(
            {
                "model": "hailuo-h3-t2v",
                "prompt": "a paper airplane gliding through a bright studio",
                "seconds": "5",
                "resolution": "768P",
                "ratio": "adaptive",
            },
            {},
        )

        self.assertEqual(
            payload,
            {
                "model": "hailuo-h3-t2v",
                "prompt": "a paper airplane gliding through a bright studio",
                "seconds": "5",
                "metadata": {"resolution": "768P", "ratio": "adaptive"},
            },
        )

    def test_hailuo_h3_image_to_video_payload_supports_last_frame(self):
        node = nodes.HailuoH3Video()
        payload = node.build_payload(
            {
                "model": "hailuo-h3-i2v",
                "prompt": "smooth camera motion",
                "seconds": "5",
                "resolution": "768P",
                "ratio": "9:16",
            },
            {
                "images": [
                    "https://cdn.test/first.png",
                    "https://cdn.test/last.png",
                ],
            },
        )

        self.assertEqual(payload["images"], [
            "https://cdn.test/first.png",
            "https://cdn.test/last.png",
        ])
        self.assertEqual(payload["metadata"], {"resolution": "768P"})
        self.assertEqual(payload["prompt"], "smooth camera motion")

    def test_hailuo_h3_multi_payload_maps_each_media_type(self):
        node = nodes.HailuoH3Video()
        payload = node.build_payload(
            {
                "model": "hailuo-h3-multi",
                "prompt": "Use @Image 1 in @Video 1 with the rhythm of @Audio 1",
                "seconds": "5",
                "resolution": "768P",
                "ratio": "16:9",
            },
            {
                "images": ["https://cdn.test/reference.png"],
                "video_urls": ["https://cdn.test/reference.mp4"],
                "audio_urls": ["https://cdn.test/reference.wav"],
            },
        )

        self.assertEqual(payload["images"], ["https://cdn.test/reference.png"])
        self.assertEqual(
            payload["metadata"],
            {
                "resolution": "768P",
                "ratio": "16:9",
                "video_url": ["https://cdn.test/reference.mp4"],
                "audio_url": ["https://cdn.test/reference.wav"],
            },
        )

    def test_hailuo_h3_multi_uploads_image_video_and_audio(self):
        node = nodes.HailuoH3Video()
        progress = []
        with (
            patch.object(nodes, "image_to_png_bytes", return_value=b"image"),
            patch.object(nodes, "video_to_bytes", return_value=(b"video", "mp4")),
            patch.object(nodes, "audio_to_wav_bytes", return_value=b"audio"),
            patch.object(
                nodes,
                "upload_media",
                side_effect=[
                    "https://cdn.test/reference.png",
                    "https://cdn.test/reference.mp4",
                    "https://cdn.test/reference.wav",
                ],
            ) as upload,
        ):
            media = node.collect_media(
                {
                    "model": "hailuo-h3-multi",
                    "image1": object(),
                    "video1": object(),
                    "audio1": object(),
                },
                CONFIG,
                progress.append,
            )

        self.assertEqual(upload.call_count, 3)
        self.assertEqual(
            media,
            {
                "images": ["https://cdn.test/reference.png"],
                "video_urls": ["https://cdn.test/reference.mp4"],
                "audio_urls": ["https://cdn.test/reference.wav"],
            },
        )
        self.assertEqual(progress, [1 / 3, 2 / 3, 1.0])

    def test_hailuo_h3_input_and_validation_match_documented_limits(self):
        inputs = nodes.HailuoH3Video.INPUT_TYPES()
        self.assertEqual(inputs["required"]["model"][0], nodes.HAILUO_H3_MODELS)
        self.assertEqual(inputs["required"]["seconds"][0], [
            str(value) for value in range(5, 16)
        ])
        self.assertEqual(inputs["required"]["resolution"][0], ["768P", "2K"])
        self.assertEqual(
            [name for name in inputs["optional"] if name.startswith("image")],
            [f"image{index}" for index in range(1, 10)],
        )
        self.assertEqual(
            [name for name in inputs["optional"] if name.startswith("video")],
            [f"video{index}" for index in range(1, 4)],
        )
        self.assertEqual(
            [name for name in inputs["optional"] if name.startswith("audio")],
            [f"audio{index}" for index in range(1, 4)],
        )
        self.assertIs(
            nodes.HailuoH3Video.VALIDATE_INPUTS(
                model="hailuo-h3-global-t2v",
                prompt="valid prompt",
                seconds="15",
                resolution="768P",
                ratio="21:9",
                strict=True,
            ),
            True,
        )
        self.assertIsNot(
            nodes.HailuoH3Video.VALIDATE_INPUTS(
                model="hailuo-h3-t2v",
                prompt="valid prompt",
                seconds="4",
                resolution="2K",
                ratio="16:9",
            ),
            True,
        )

    def test_hailuo_h3_global_models_reuse_each_documented_task_contract(self):
        node = nodes.HailuoH3Video()
        t2v = node.build_payload(
            {
                "model": "hailuo-h3-global-t2v",
                "prompt": "a paper airplane gliding through a bright studio",
                "seconds": "5",
                "resolution": "768P",
                "ratio": "16:9",
            },
            {},
        )
        i2v = node.build_payload(
            {
                "model": "hailuo-h3-global-i2v",
                "prompt": "smooth camera motion",
                "seconds": "5",
                "resolution": "768P",
                "ratio": "9:16",
            },
            {"images": ["https://cdn.test/first.png"]},
        )
        multi = node.build_payload(
            {
                "model": "hailuo-h3-global-multi",
                "prompt": "Use @Image 1 as the main subject",
                "seconds": "5",
                "resolution": "768P",
                "ratio": "adaptive",
            },
            {"images": ["https://cdn.test/reference.png"]},
        )

        self.assertEqual(t2v["metadata"], {"resolution": "768P", "ratio": "16:9"})
        self.assertEqual(i2v["images"], ["https://cdn.test/first.png"])
        self.assertEqual(i2v["metadata"], {"resolution": "768P"})
        self.assertEqual(multi["metadata"], {"resolution": "768P", "ratio": "adaptive"})
        self.assertIsNot(
            nodes.HailuoH3Video.VALIDATE_INPUTS(
                model="hailuo-h3-t2v",
                prompt="valid prompt",
                seconds="5",
                resolution="1080p",
                ratio="16:9",
            ),
            True,
        )
        self.assertIsNot(
            nodes.HailuoH3Video.VALIDATE_INPUTS(
                model="hailuo-h3-multi",
                prompt="",
                seconds="5",
                resolution="2K",
                ratio="adaptive",
                strict=True,
            ),
            True,
        )

    def test_hailuo_h3_runtime_requires_model_specific_media(self):
        node = nodes.HailuoH3Video()
        with self.assertRaises(client.SeedanceAPIError):
            node.collect_media(
                {"model": "hailuo-h3-i2v"},
                CONFIG,
                lambda _progress: None,
            )
        with self.assertRaises(client.SeedanceAPIError):
            node.collect_media(
                {"model": "hailuo-h3-i2v", "image2": object()},
                CONFIG,
                lambda _progress: None,
            )
        with self.assertRaises(client.SeedanceAPIError):
            node.collect_media(
                {"model": "hailuo-h3-multi"},
                CONFIG,
                lambda _progress: None,
            )

    def test_vidu_q3_text_to_video_payload(self):
        node = nodes.ViduQ3Video()
        payload = node.build_payload(
            {
                "model": "vidu-q3-turbo-t2v",
                "prompt": "a compact product reveal shot",
                "seconds": "4",
                "ratio": "16:9",
                "resolution": "default",
                "seed": -1,
            },
            {},
        )

        self.assertEqual(payload["model"], "vidu-q3-turbo-t2v")
        self.assertEqual(payload["prompt"], "a compact product reveal shot")
        self.assertEqual(payload["seconds"], "4")
        self.assertEqual(payload["metadata"], {"ratio": "16:9"})
        self.assertNotIn("images", payload)

    def test_vidu_q3_start_end_payload_uses_two_images(self):
        node = nodes.ViduQ3Video()
        payload = node.build_payload(
            {
                "model": "vidu-q3-pro-fast-start-end",
                "prompt": "",
                "seconds": "4",
                "ratio": "9:16",
                "resolution": "720p",
                "seed": 7,
            },
            {
                "images": [
                    "https://cdn.test/start.png",
                    "https://cdn.test/end.png",
                    "https://cdn.test/ignored.png",
                ]
            },
        )

        self.assertEqual(payload["images"], ["https://cdn.test/start.png", "https://cdn.test/end.png"])
        self.assertEqual(
            payload["metadata"],
            {"ratio": "9:16", "resolution": "720p", "seed": 7},
        )
        self.assertNotIn("prompt", payload)

    def test_vidu_q3_reference_to_video_keeps_connected_images(self):
        node = nodes.ViduQ3Video()
        payload = node.build_payload(
            {
                "model": "vidu-q3-r2v",
                "prompt": "Use image1 as the main subject and image2 as the scene",
                "seconds": "5",
                "ratio": "adaptive",
                "resolution": "default",
                "seed": -1,
            },
            {"images": ["https://cdn.test/a.png", "https://cdn.test/b.png"]},
        )

        self.assertEqual(payload["images"], ["https://cdn.test/a.png", "https://cdn.test/b.png"])
        self.assertEqual(payload["prompt"], "Use image1 as the main subject and image2 as the scene")
        self.assertEqual(payload["metadata"], {})

    def test_vidu_q3_uploads_required_images_for_start_end(self):
        node = nodes.ViduQ3Video()
        progress = []
        with patch.object(
            nodes, "image_to_png_bytes", side_effect=[b"start", b"end"]
        ), patch.object(
            nodes,
            "upload_media",
            side_effect=["https://cdn.test/start.png", "https://cdn.test/end.png"],
        ) as upload:
            media = node.collect_media(
                {
                    "model": "vidu-q3-turbo-start-end",
                    "image1": torch.zeros((1, 4, 4, 3), dtype=torch.float32),
                    "image2": torch.zeros((1, 4, 4, 3), dtype=torch.float32),
                },
                CONFIG,
                progress.append,
            )

        self.assertEqual(media, {"images": ["https://cdn.test/start.png", "https://cdn.test/end.png"]})
        self.assertEqual(upload.call_count, 2)
        self.assertEqual(progress, [0.5, 1.0])

    def test_vidu_q3_validation_matches_documented_modes(self):
        self.assertIs(
            nodes.ViduQ3Video.VALIDATE_INPUTS(
                model="vidu-q3-turbo-t2v",
                prompt="valid prompt",
                seconds="4",
                ratio="16:9",
                resolution="default",
                seed=-1,
            ),
            True,
        )
        self.assertIs(
            nodes.ViduQ3Video.VALIDATE_INPUTS(
                model="vidu-q3-turbo-t2v",
                prompt="",
                seconds="4",
                ratio="16:9",
                resolution="default",
                seed=-1,
            ),
            True,
        )
        self.assertIsNot(
            nodes.ViduQ3Video.VALIDATE_INPUTS(
                model="vidu-q3-turbo-t2v",
                prompt="",
                seconds="4",
                ratio="16:9",
                resolution="default",
                seed=-1,
                strict=True,
            ),
            True,
        )
        self.assertIsNot(
            nodes.ViduQ3Video.VALIDATE_INPUTS(
                model="vidu-q3-turbo-t2v",
                prompt="valid prompt",
                seconds="-1",
                ratio="16:9",
                resolution="default",
                seed=-1,
            ),
            True,
        )
        self.assertIsNot(
            nodes.ViduQ3Video.VALIDATE_INPUTS(
                model="vidu-q3-turbo-t2v",
                prompt="valid prompt",
                seconds="4",
                ratio="16:9",
                resolution="4k",
                seed=-1,
            ),
            True,
        )

    def test_vidu_q3_build_payload_still_rejects_empty_runtime_prompt(self):
        node = nodes.ViduQ3Video()
        with self.assertRaises(client.SeedanceAPIError):
            node.build_payload(
                {
                    "model": "vidu-q3-turbo-t2v",
                    "prompt": "",
                    "seconds": "4",
                    "ratio": "16:9",
                    "resolution": "default",
                    "seed": -1,
                },
                {},
            )

    def test_vidu_q3_short_play_payload_uses_script_name_metadata(self):
        node = nodes.ViduQ3ShortPlay()
        payload = node.build_payload(
            {
                "model": "vidu-q3-drama-short-play",
                "prompt": "Scene one: a founder enters a quiet studio and introduces the product.",
                "script_name": "Studio intro",
                "resolution": "1080p",
                "duration": "8",
                "aspect_ratio": "9:16",
                "style": "realistic",
                "asset_type": "character",
                "asset_name_prefix": "Hero",
                "asset_description": "Founder in a clean studio",
            },
            {"asset_urls": ["https://cdn.test/founder.png"]},
        )

        self.assertEqual(payload["model"], "vidu-q3-drama-short-play")
        self.assertEqual(
            payload["prompt"],
            "Scene one: a founder enters a quiet studio and introduces the product.",
        )
        self.assertEqual(payload["metadata"]["script_name"], "Studio intro")
        self.assertEqual(payload["metadata"]["resolution"], "1080p")
        self.assertEqual(payload["metadata"]["duration"], 8)
        self.assertEqual(payload["metadata"]["aspect_ratio"], "9:16")
        self.assertEqual(payload["metadata"]["style"], "realistic")
        self.assertEqual(
            payload["metadata"]["assets"],
            [
                {
                    "id": "1",
                    "type": "character",
                    "name": "Hero 1",
                    "image_uri": "https://cdn.test/founder.png",
                    "description": "Founder in a clean studio",
                }
            ],
        )
        self.assertNotIn("seconds", payload)
        self.assertNotIn("images", payload)

    def test_vidu_q3_short_play_uploads_reference_assets(self):
        node = nodes.ViduQ3ShortPlay()
        progress = []
        with patch.object(
            nodes, "image_to_png_bytes", return_value=b"asset"
        ), patch.object(
            nodes, "upload_media", return_value="https://cdn.test/asset.png"
        ) as upload:
            media = node.collect_media(
                {
                    "asset_image1": torch.zeros((1, 4, 4, 3), dtype=torch.float32),
                },
                CONFIG,
                progress.append,
            )

        upload.assert_called_once()
        self.assertEqual(media, {"asset_urls": ["https://cdn.test/asset.png"]})
        self.assertEqual(progress, [1.0])

    def test_vidu_q3_short_play_validation_requires_script(self):
        common = {
            "model": "vidu-q3-drama-short-play",
            "resolution": "1080p",
            "duration": "8",
            "aspect_ratio": "9:16",
            "style": "realistic",
            "asset_type": "character",
            "asset_name_prefix": "Asset",
            "asset_description": "Reference asset",
        }
        self.assertIs(
            nodes.ViduQ3ShortPlay.VALIDATE_INPUTS(
                prompt="",
                script_name="Studio intro",
                **common,
            ),
            True,
        )
        self.assertIsNot(
            nodes.ViduQ3ShortPlay.VALIDATE_INPUTS(
                prompt="",
                script_name="Studio intro",
                strict=True,
                **common,
            ),
            True,
        )
        self.assertIs(
            nodes.ViduQ3ShortPlay.VALIDATE_INPUTS(
                prompt="valid script",
                script_name="",
                **common,
            ),
            True,
        )
        self.assertIsNot(
            nodes.ViduQ3ShortPlay.VALIDATE_INPUTS(
                prompt="valid script",
                script_name="",
                strict=True,
                **common,
            ),
            True,
        )
        self.assertIsNot(
            nodes.ViduQ3ShortPlay.VALIDATE_INPUTS(
                model="vidu-q3-drama-short-play",
                prompt="valid script",
                script_name="Studio intro",
                resolution="720p",
                duration="8",
                aspect_ratio="9:16",
                style="realistic",
                asset_type="character",
                asset_name_prefix="Asset",
                asset_description="Reference asset",
            ),
            True,
        )
        self.assertIsNot(
            nodes.ViduQ3ShortPlay.VALIDATE_INPUTS(
                model="vidu-q3-drama-short-play",
                prompt="valid script",
                script_name="Studio intro",
                resolution="1080p",
                duration="6",
                aspect_ratio="9:16",
                style="realistic",
                asset_type="character",
                asset_name_prefix="Asset",
                asset_description="Reference asset",
            ),
            True,
        )
        self.assertIsNot(
            nodes.ViduQ3ShortPlay.VALIDATE_INPUTS(
                model="vidu-q3-drama-short-play",
                prompt="valid script",
                script_name="Studio intro",
                resolution="1080p",
                duration="8",
                aspect_ratio="1:1",
                style="realistic",
                asset_type="character",
                asset_name_prefix="Asset",
                asset_description="Reference asset",
            ),
            True,
        )

    def test_vidu_q3_short_play_build_payload_still_rejects_empty_runtime_script(self):
        node = nodes.ViduQ3ShortPlay()
        with self.assertRaises(client.SeedanceAPIError):
            node.build_payload(
                {
                    "model": "vidu-q3-drama-short-play",
                    "prompt": "",
                    "script_name": "Studio intro",
                    "resolution": "1080p",
                    "duration": "8",
                    "aspect_ratio": "9:16",
                    "style": "realistic",
                    "asset_type": "character",
                    "asset_name_prefix": "Asset",
                    "asset_description": "Reference asset",
                },
                {"asset_urls": ["https://cdn.test/founder.png"]},
            )

    def test_zhenzhen_upscaler_payload_uses_single_video_content(self):
        node = nodes.ZhenzhenUpscalerVideo()
        payload = node.build_payload(
            {"resolution": "720p"},
            {"video_url": "https://cdn.test/source.mp4"},
        )

        self.assertEqual(payload["model"], "zhenzhen-upscaler")
        self.assertEqual(payload["prompt"], "upscale")
        self.assertNotIn("seconds", payload)
        self.assertNotIn("images", payload)
        self.assertEqual(
            payload["metadata"],
            {
                "resolution": "720p",
                "content": [
                    {
                        "type": "video_url",
                        "video_url": {"url": "https://cdn.test/source.mp4"},
                    }
                ],
            },
        )

    def test_zhenzhen_upscaler_validation_accepts_connected_video_runtime_check(self):
        self.assertIs(
            nodes.ZhenzhenUpscalerVideo.VALIDATE_INPUTS(
                video_url="https://cdn.test/source.mp4",
                resolution="1080p",
            ),
            True,
        )
        self.assertIsNot(
            nodes.ZhenzhenUpscalerVideo.VALIDATE_INPUTS(
                video_url="ftp://cdn.test/source.mp4",
                resolution="1080p",
            ),
            True,
        )
        self.assertIsNot(
            nodes.ZhenzhenUpscalerVideo.VALIDATE_INPUTS(
                video_url="",
                resolution="8k",
                input_video="dummy",
            ),
            True,
        )
        self.assertIs(
            nodes.ZhenzhenUpscalerVideo.VALIDATE_INPUTS(
                video_url="",
                resolution="720p",
                input_video=None,
            ),
            True,
        )

    def test_zhenzhen_upscaler_uploads_connected_video(self):
        node = nodes.ZhenzhenUpscalerVideo()
        progress = []
        with patch.object(
            nodes, "video_to_bytes", return_value=(b"fake-mp4", "mp4")
        ) as to_bytes, patch.object(
            nodes, "upload_media", return_value="https://cdn.test/uploaded.mp4"
        ) as upload:
            media = node.collect_media(
                {"video_url": "", "input_video": {"file_path": "source.mp4"}},
                CONFIG,
                progress.append,
            )

        to_bytes.assert_called_once()
        upload.assert_called_once_with(
            b"fake-mp4",
            "zhenzhen_upscaler_input.mp4",
            "video/mp4",
            CONFIG,
            logger_prefix="Zhenzhen_upscaler",
        )
        self.assertEqual(media, {"video_url": "https://cdn.test/uploaded.mp4"})
        self.assertEqual(progress, [1.0])

    def test_wan27_spicy_i2v_payload_minimal(self):
        node = nodes.Wan27SpicyImageToVideo()
        payload = node.build_payload(
            {
                "prompt": "gentle camera movement",
                "seconds": "2",
                "resolution": "720p",
                "negative_prompt": "",
                "audio_url": "",
                "prompt_extend": False,
                "seed": -1,
            },
            {"images": ["https://cdn.test/start.png", "https://cdn.test/ignored.png"]},
        )

        self.assertEqual(payload["model"], "wan-2.7-spicy-i2v")
        self.assertEqual(payload["seconds"], "2")
        self.assertEqual(payload["images"], ["https://cdn.test/start.png"])
        self.assertEqual(payload["prompt"], "gentle camera movement")
        self.assertEqual(payload["metadata"], {"resolution": "720p"})

    def test_wan27_spicy_i2v_payload_forwards_optional_metadata(self):
        node = nodes.Wan27SpicyImageToVideo()
        payload = node.build_payload(
            {
                "prompt": "",
                "seconds": "15",
                "resolution": "1080p",
                "negative_prompt": "blur, low quality",
                "audio_url": "https://cdn.test/driving.wav",
                "prompt_extend": True,
                "seed": 42,
            },
            {"images": ["https://cdn.test/start.png"]},
        )

        self.assertEqual(payload["model"], "wan-2.7-spicy-i2v")
        self.assertNotIn("prompt", payload)
        self.assertEqual(
            payload["metadata"],
            {
                "resolution": "1080p",
                "negative_prompt": "blur, low quality",
                "audio_url": "https://cdn.test/driving.wav",
                "prompt_extend": True,
                "seed": 42,
            },
        )

    def test_wan27_spicy_i2v_validation_matches_documented_limits(self):
        self.assertIs(
            nodes.Wan27SpicyImageToVideo.VALIDATE_INPUTS(
                prompt="",
                seconds="2",
                resolution="720p",
                audio_url="",
                seed=-1,
            ),
            True,
        )
        self.assertIsNot(
            nodes.Wan27SpicyImageToVideo.VALIDATE_INPUTS(
                prompt="",
                seconds="-1",
                resolution="720p",
                audio_url="",
                seed=-1,
            ),
            True,
        )
        self.assertIsNot(
            nodes.Wan27SpicyImageToVideo.VALIDATE_INPUTS(
                prompt="",
                seconds="2",
                resolution="480p",
                audio_url="",
                seed=-1,
            ),
            True,
        )
        self.assertIsNot(
            nodes.Wan27SpicyImageToVideo.VALIDATE_INPUTS(
                prompt="",
                seconds="2",
                resolution="720p",
                audio_url="not-a-url",
                seed=-1,
            ),
            True,
        )
        self.assertIsNot(
            nodes.Wan27SpicyImageToVideo.VALIDATE_INPUTS(
                prompt="",
                seconds="2",
                resolution="720p",
                audio_url="",
                seed=2147483648,
            ),
            True,
        )

    def test_happyhorse_text_to_video_payload(self):
        node = nodes.HappyHorseVideo()
        payload = node.build_payload(
            {
                "model": nodes.HAPPYHORSE_T2V_MODEL,
                "prompt": "a short cinematic horse ride",
                "seconds": "4",
                "resolution": "720p",
                "ratio": "16:9",
            },
            {},
        )

        self.assertEqual(payload["model"], "happyhorse-1.1-t2v")
        self.assertEqual(payload["seconds"], "4")
        self.assertEqual(payload["prompt"], "a short cinematic horse ride")
        self.assertEqual(payload["metadata"], {"resolution": "720p", "ratio": "16:9"})
        self.assertNotIn("images", payload)

    def test_happyhorse_image_to_video_payload_uses_first_image_only(self):
        node = nodes.HappyHorseVideo()
        payload = node.build_payload(
            {
                "model": nodes.HAPPYHORSE_I2V_MODEL,
                "prompt": "",
                "seconds": "5",
                "resolution": "1080p",
                "ratio": "adaptive",
            },
            {"images": ["https://cdn.test/start.png", "https://cdn.test/ignored.png"]},
        )

        self.assertEqual(payload["model"], "happyhorse-1.1-i2v")
        self.assertEqual(payload["images"], ["https://cdn.test/start.png"])
        self.assertNotIn("prompt", payload)

    def test_happyhorse_reference_to_video_payload_keeps_reference_images(self):
        node = nodes.HappyHorseVideo()
        payload = node.build_payload(
            {
                "model": nodes.HAPPYHORSE_R2V_MODEL,
                "prompt": "Use 图1 as the character and 图2 as the scene",
                "seconds": "6",
                "resolution": "720p",
                "ratio": "9:16",
            },
            {
                "images": [
                    "https://cdn.test/character.png",
                    "https://cdn.test/scene.png",
                    "https://cdn.test/style.png",
                ]
            },
        )

        self.assertEqual(payload["model"], "happyhorse-1.1-r2v")
        self.assertEqual(
            payload["images"],
            [
                "https://cdn.test/character.png",
                "https://cdn.test/scene.png",
                "https://cdn.test/style.png",
            ],
        )
        self.assertEqual(payload["prompt"], "Use 图1 as the character and 图2 as the scene")

    def test_happyhorse_reference_to_video_requires_reference_image(self):
        node = nodes.HappyHorseVideo()
        with self.assertRaises(client.SeedanceAPIError):
            node.build_payload(
                {
                    "model": nodes.HAPPYHORSE_R2V_MODEL,
                    "prompt": "",
                    "seconds": "6",
                    "resolution": "720p",
                    "ratio": "adaptive",
                },
                {},
            )

    def test_happyhorse_validation_rejects_seedance_only_settings(self):
        self.assertIsNot(
            nodes.HappyHorseVideo.VALIDATE_INPUTS(
                model=nodes.HAPPYHORSE_T2V_MODEL,
                prompt="valid prompt",
                seconds="-1",
                resolution="720p",
            ),
            True,
        )
        self.assertIsNot(
            nodes.HappyHorseVideo.VALIDATE_INPUTS(
                model=nodes.HAPPYHORSE_T2V_MODEL,
                prompt="valid prompt",
                seconds="4",
                resolution="2k",
            ),
            True,
        )
        self.assertIs(
            nodes.HappyHorseVideo.VALIDATE_INPUTS(
                model=nodes.HAPPYHORSE_T2V_MODEL,
                prompt="",
                seconds="4",
                resolution="720p",
            ),
            True,
        )
        self.assertIsNot(
            nodes.HappyHorseVideo.VALIDATE_INPUTS(
                model=nodes.HAPPYHORSE_T2V_MODEL,
                prompt="",
                seconds="4",
                resolution="720p",
                strict=True,
            ),
            True,
        )
        self.assertIs(
            nodes.HappyHorseVideo.VALIDATE_INPUTS(
                model=nodes.HAPPYHORSE_R2V_MODEL,
                prompt="",
                seconds="6",
                resolution="720p",
            ),
            True,
        )

    def test_core_video_prompt_validation_allows_linked_empty_widget_preflight(self):
        self.assertIs(
            nodes.SeedanceTextToVideo.VALIDATE_INPUTS(
                model="seedance-2.0-mini-t2v",
                prompt="",
                resolution="720p",
            ),
            True,
        )
        self.assertIsNot(
            nodes.SeedanceTextToVideo.VALIDATE_INPUTS(
                model="seedance-2.0-mini-t2v",
                prompt="",
                resolution="720p",
                strict=True,
            ),
            True,
        )
        self.assertIs(
            nodes.SeedanceMultimodalVideo.VALIDATE_INPUTS(
                model="seedance-2.0-mini-multi",
                prompt="",
                resolution="720p",
            ),
            True,
        )
        self.assertIsNot(
            nodes.SeedanceMultimodalVideo.VALIDATE_INPUTS(
                model="seedance-2.0-mini-multi",
                prompt="",
                resolution="720p",
                strict=True,
            ),
            True,
        )

    def test_doubao_audio_payload_with_speaker(self):
        node = nodes.DoubaoSeedAudio()
        payload = node._build_payload(
            prompt="gentle rain falling outside",
            speaker="zh_male_shaonianzixin_uranus_bigtts",
            output_format="wav",
            sample_rate="24000",
            speech_rate=0,
            loudness_rate=0,
            pitch_rate=0,
            image_urls=[],
            audio_urls=[],
        )

        self.assertEqual(payload["model"], "doubao-seed-audio-1.0")
        self.assertEqual(payload["prompt"], "gentle rain falling outside")
        self.assertEqual(
            payload["metadata"]["speaker"],
            "zh_male_shaonianzixin_uranus_bigtts",
        )
        self.assertEqual(payload["metadata"]["format"], "wav")
        self.assertNotIn("images", payload)

    def test_doubao_audio_payload_with_reference_audios(self):
        node = nodes.DoubaoSeedAudio()
        payload = node._build_payload(
            prompt="match the voice and read calmly",
            speaker="",
            output_format="mp3",
            sample_rate="32000",
            speech_rate=10,
            loudness_rate=-5,
            pitch_rate=2,
            image_urls=[],
            audio_urls=["https://cdn.test/a.wav", "https://cdn.test/b.wav"],
        )

        self.assertEqual(
            payload["metadata"]["audio_urls"],
            ["https://cdn.test/a.wav", "https://cdn.test/b.wav"],
        )
        self.assertNotIn("speaker", payload["metadata"])
        self.assertEqual(payload["metadata"]["sample_rate"], "32000")

    def test_doubao_audio_rejects_mixed_reference_modes(self):
        node = nodes.DoubaoSeedAudio()
        with self.assertRaises(client.SeedanceAPIError):
            node._build_payload(
                prompt="valid audio prompt",
                speaker="speaker-id",
                output_format="wav",
                sample_rate="24000",
                speech_rate=0,
                loudness_rate=0,
                pitch_rate=0,
                image_urls=[],
                audio_urls=["https://cdn.test/a.wav"],
            )

    def test_doubao_audio_prompt_validation_allows_linked_empty_widget_preflight(self):
        self.assertIs(
            nodes.DoubaoSeedAudio.VALIDATE_INPUTS(
                prompt="",
                output_format="wav",
                sample_rate="24000",
                speech_rate=0,
                loudness_rate=0,
                pitch_rate=0,
            ),
            True,
        )
        self.assertIsNot(
            nodes.DoubaoSeedAudio.VALIDATE_INPUTS(
                prompt="",
                output_format="wav",
                sample_rate="24000",
                speech_rate=0,
                loudness_rate=0,
                pitch_rate=0,
                strict=True,
            ),
            True,
        )

    def test_whisper_transcription_execute_converts_audio_and_returns_text(self):
        node = nodes.WhisperTranscription()
        audio = {"waveform": torch.zeros((1, 1, 1600)), "sample_rate": 16000}

        with patch.object(nodes, "get_config", return_value=CONFIG), patch.object(
            nodes, "audio_to_wav_bytes", return_value=b"wav-bytes"
        ) as convert, patch.object(
            nodes, "transcribe_audio", return_value=("hello seedance", '{"text":"hello seedance"}')
        ) as transcribe:
            result = node.execute(
                audio,
                nodes.WHISPER_TRANSCRIPTION_MODEL,
                "json",
            )

        convert.assert_called_once_with(audio)
        args, kwargs = transcribe.call_args
        self.assertEqual(args[:5], (
            b"wav-bytes",
            "whisper_input.wav",
            "audio/wav",
            nodes.WHISPER_TRANSCRIPTION_MODEL,
            "json",
        ))
        self.assertEqual(result["result"], ("hello seedance", '{"text":"hello seedance"}'))

    def test_whisper_transcription_validation(self):
        self.assertIs(
            nodes.WhisperTranscription.VALIDATE_INPUTS(
                audio=None,
                model=nodes.WHISPER_TRANSCRIPTION_MODEL,
                response_format="json",
            ),
            True,
        )
        self.assertIsNot(
            nodes.WhisperTranscription.VALIDATE_INPUTS(
                audio=None,
                model=nodes.WHISPER_TRANSCRIPTION_MODEL,
                response_format="json",
                strict=True,
            ),
            True,
        )
        self.assertIsNot(
            nodes.WhisperTranscription.VALIDATE_INPUTS(
                audio={},
                model=nodes.WHISPER_TRANSCRIPTION_MODEL,
                response_format="bad",
                strict=True,
            ),
            True,
        )


if __name__ == "__main__":
    unittest.main()
