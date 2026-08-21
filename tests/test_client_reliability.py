import json
import os
import sys
import tempfile
import threading
import unittest
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT.parent))

from ComfyUI_Seedance.core import client


CONFIG = {
    "base_url": "https://example.test",
    "api_key": "test-key",
    "timeout": 60,
}


class FakeResponse:
    def __init__(self, status_code=200, data=None, headers=None, chunks=None):
        self.status_code = status_code
        self.data = data if data is not None else {}
        self.text = json.dumps(self.data)
        self.headers = dict(headers or {})
        self.chunks = list(chunks or [])
        self.closed = False

    @property
    def content(self):
        return b"".join(self.chunks)

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size):
        del chunk_size
        yield from self.chunks

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.post_calls = []
        self.get_calls = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def submit_cases():
    payload = {"model": "test-model", "prompt": "test"}
    return {
        "video": lambda: client.submit_task(payload, CONFIG),
        "context_ir": lambda: client.submit_context_ir_task(payload, CONFIG),
        "image": lambda: client.submit_image_task(payload, CONFIG),
        "audio": lambda: client.submit_audio_task(payload, CONFIG),
        "transcription": lambda: client.transcribe_audio(
            b"audio",
            "sample.wav",
            "audio/wav",
            "whisper-1",
            "json",
            CONFIG,
        ),
        "music": lambda: client.submit_music_action("extend", payload, CONFIG),
        "midjourney": lambda: client.submit_midjourney_action(
            "imagine", payload, CONFIG
        ),
    }


class TaskCreationRetryTests(unittest.TestCase):
    def test_video_submit_log_redacts_urls_and_runtime_identifiers(self):
        payload = {
            "model": "test-model",
            "prompt": "preserve the scene",
            "images": [
                "https://cdn.example.test/input.png?private-marker=image",
            ],
            "metadata": {
                "video_url": "https://cdn.example.test/input.mp4?private-marker=video",
                "extend_from_task_id": "task_runtime_secret",
                "content": [
                    {
                        "type": "audio_url",
                        "audio_url": {
                            "url": "https://cdn.example.test/input.mp3?private-marker=audio",
                        },
                    },
                ],
            },
        }
        session = FakeSession([FakeResponse(200, {"id": "task-result"})])
        with (
            patch.object(client, "_session", return_value=session),
            patch("builtins.print") as print_mock,
        ):
            self.assertEqual(client.submit_task(payload, CONFIG), "task-result")

        logged = "\n".join(
            str(call.args[0]) for call in print_mock.call_args_list if call.args
        )
        self.assertIn("test-model", logged)
        self.assertIn("preserve the scene", logged)
        self.assertIn("<redacted-url>", logged)
        self.assertIn("<redacted-id>", logged)
        self.assertNotIn("cdn.example.test", logged)
        self.assertNotIn("private-marker", logged)
        self.assertNotIn("task_runtime_secret", logged)
        self.assertEqual(session.post_calls[0][1]["json"], payload)

    def test_all_submit_families_do_not_replay_ambiguous_read_timeout(self):
        for name, submit in submit_cases().items():
            with self.subTest(name=name):
                session = FakeSession(
                    [requests.exceptions.ReadTimeout("response lost")]
                )
                with (
                    patch.object(client, "_session", return_value=session),
                    patch.object(client, "cooperative_sleep") as sleep,
                ):
                    with self.assertRaisesRegex(RuntimeError, "not retried"):
                        submit()
                self.assertEqual(len(session.post_calls), 1)
                sleep.assert_not_called()

    def test_all_submit_families_do_not_replay_http_502(self):
        for name, submit in submit_cases().items():
            with self.subTest(name=name):
                response = FakeResponse(
                    502, {"message": "temporary upstream response"}
                )
                session = FakeSession([response])
                with (
                    patch.object(client, "_session", return_value=session),
                    patch.object(client, "cooperative_sleep") as sleep,
                ):
                    with self.assertRaisesRegex(RuntimeError, "not retried"):
                        submit()
                self.assertEqual(len(session.post_calls), 1)
                self.assertTrue(response.closed)
                sleep.assert_not_called()

    def test_connect_timeout_retries_and_returns_task(self):
        session = FakeSession(
            [
                requests.exceptions.ConnectTimeout("connect timeout"),
                FakeResponse(200, {"id": "task-test"}),
            ]
        )
        with (
            patch.object(client, "_session", return_value=session),
            patch.object(client, "_reset_thread_session") as reset,
            patch.object(client, "cooperative_sleep") as sleep,
        ):
            task_id = client.submit_task(
                {"model": "test-model", "prompt": "test"}, CONFIG
            )

        self.assertEqual(task_id, "task-test")
        self.assertEqual(len(session.post_calls), 2)
        reset.assert_called_once_with()
        sleep.assert_called_once_with(3.0)

    def test_connection_error_is_retried_only_for_known_pre_send_cause(self):
        class NewConnectionError(OSError):
            pass

        safe_error = requests.exceptions.ConnectionError(
            NewConnectionError("connection refused")
        )
        self.assertTrue(client._is_safe_submit_retry_error(safe_error))
        self.assertFalse(
            client._is_safe_submit_retry_error(
                requests.exceptions.ConnectionError("connection reset")
            )
        )

    def test_http_429_honors_retry_after_and_retries(self):
        limited = FakeResponse(
            429,
            {"message": "rate limited"},
            headers={"Retry-After": "7"},
        )
        session = FakeSession(
            [limited, FakeResponse(200, {"task_id": "image-task"})]
        )
        with (
            patch.object(client, "_session", return_value=session),
            patch.object(client, "cooperative_sleep") as sleep,
        ):
            task_id = client.submit_image_task(
                {"model": "test-model", "prompt": "test"}, CONFIG
            )

        self.assertEqual(task_id, "image-task")
        self.assertEqual(len(session.post_calls), 2)
        self.assertTrue(limited.closed)
        sleep.assert_called_once_with(7.0)


class ResultDownloadLimitTests(unittest.TestCase):
    def test_default_limits_are_media_specific(self):
        self.assertEqual(client._IMAGE_DOWNLOAD_MAX_BYTES, 64 * 1024 * 1024)
        self.assertEqual(client._AUDIO_DOWNLOAD_MAX_BYTES, 512 * 1024 * 1024)
        self.assertEqual(client._FILE_DOWNLOAD_MAX_BYTES, 1024 * 1024 * 1024)
        self.assertEqual(client._VIDEO_DOWNLOAD_MAX_BYTES, 8192 * 1024 * 1024)

    def test_limit_environment_uses_positive_mib_and_rejects_invalid_values(self):
        with patch.dict(os.environ, {"SEEDANCE_TEST_MAX_MIB": "12"}):
            self.assertEqual(
                client._download_limit_bytes("SEEDANCE_TEST_MAX_MIB", 3),
                12 * 1024 * 1024,
            )
        with patch.dict(os.environ, {"SEEDANCE_TEST_MAX_MIB": "0"}):
            self.assertEqual(
                client._download_limit_bytes("SEEDANCE_TEST_MAX_MIB", 3),
                3 * 1024 * 1024,
            )

    def test_image_declared_limit_stops_without_fallback(self):
        response = FakeResponse(
            headers={"content-length": "5"}, chunks=[b"abcde"]
        )
        session = FakeSession([response])
        with (
            patch.object(client, "_session", return_value=session),
            patch.object(client, "_IMAGE_DOWNLOAD_MAX_BYTES", 4),
            patch.object(client, "_download_image_bytes_with_curl") as curl,
            patch.object(client, "cooperative_sleep") as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "LimitError"):
                client._download_and_decode_image(
                    "https://cdn.test/image.png",
                    lambda content: content,
                    60,
                    3,
                    "Test",
                    "Image",
                )

        self.assertEqual(len(session.get_calls), 1)
        self.assertTrue(response.closed)
        curl.assert_not_called()
        sleep.assert_not_called()

    def test_streamed_file_limit_removes_partial_output(self):
        response = FakeResponse(chunks=[b"abc", b"def"])
        session = FakeSession([response])
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "result.bin")
            with self.assertRaises(client._ResultDownloadLimitError):
                client._download_result_to_path_requests(
                    url="https://cdn.test/result.bin",
                    path=path,
                    timeout=60,
                    connect_timeout=8,
                    read_timeout=60,
                    headers=client._FILE_DOWNLOAD_HEADERS,
                    max_bytes=4,
                    session=session,
                )
            self.assertFalse(os.path.exists(path))
            self.assertFalse(os.path.exists(f"{path}.part"))
        self.assertTrue(response.closed)

    def test_curl_limit_is_in_config_and_removes_partial_output(self):
        def run_curl(command, **kwargs):
            output_index = command.index("--output") + 1
            Path(command[output_index]).write_bytes(b"abcde")
            return MagicMock(returncode=0, stdout=b"", stderr=b"")

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "result.bin")
            with (
                patch.object(client, "_find_curl_binary", return_value="curl.exe"),
                patch.object(client.subprocess, "run", side_effect=run_curl) as run,
            ):
                with self.assertRaises(client._ResultDownloadLimitError):
                    client._download_result_to_path_with_curl(
                        "https://cdn.test/result.bin",
                        path,
                        60,
                        8,
                        client._FILE_DOWNLOAD_HEADERS,
                        max_bytes=4,
                    )

            self.assertFalse(os.path.exists(path))
            self.assertFalse(os.path.exists(f"{path}.part"))
            self.assertIn(b"max-filesize = 4", run.call_args.kwargs["input"])


class TLSMigrationTests(unittest.TestCase):
    def setUp(self):
        client._insecure_tls_warning_emitted = False
        client._session_local = threading.local()

    def test_insecure_tls_escape_hatch_warns_once_and_remains_compatible(self):
        sessions = [MagicMock(), MagicMock()]
        with (
            patch.object(client.requests, "Session", side_effect=sessions),
            patch.object(client, "_windows_cert_store_context", return_value=(None, 0)),
            patch.dict(
                os.environ,
                {"SEEDANCE_CA_BUNDLE": "", "SEEDANCE_SSL_VERIFY": "0"},
            ),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always")
            first = client._create_session()
            second = client._create_session()

        self.assertFalse(first.verify)
        self.assertFalse(second.verify)
        insecure_warnings = [
            warning
            for warning in caught
            if "SEEDANCE_SSL_VERIFY=0" in str(warning.message)
        ]
        self.assertEqual(len(insecure_warnings), 1)

    def test_custom_ca_takes_precedence_over_insecure_legacy_flag(self):
        session = MagicMock()
        with (
            patch.object(client.requests, "Session", return_value=session),
            patch.dict(
                os.environ,
                {
                    "SEEDANCE_CA_BUNDLE": "C:/certs/custom.pem",
                    "SEEDANCE_SSL_VERIFY": "0",
                },
            ),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always")
            created = client._create_session()

        self.assertEqual(created.verify, "C:/certs/custom.pem")
        self.assertEqual(caught, [])


if __name__ == "__main__":
    unittest.main()
