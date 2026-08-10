import os
import io
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT.parent))

from ComfyUI_Seedance.core import client


MP4_BYTES = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isommp41"


def wav_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8000)
        wav_file.writeframes(b"\x00\x00" * 80)
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, chunks=None, error=None, headers=None):
        self.chunks = list(chunks or [])
        self.error = error
        self.headers = dict(headers or {})
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        self.chunk_size = chunk_size
        for chunk in self.chunks:
            yield chunk
        if self.error:
            raise self.error

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class VideoDownloadTests(unittest.TestCase):
    def test_all_generated_media_defaults_allow_60_second_reads(self):
        self.assertEqual(client._IMAGE_DOWNLOAD_TIMEOUT, 60)
        self.assertEqual(client._IMAGE_DOWNLOAD_READ_TIMEOUT, 60)
        self.assertEqual(client._VIDEO_DOWNLOAD_READ_TIMEOUT, 60)
        self.assertEqual(client._AUDIO_DOWNLOAD_READ_TIMEOUT, 60)
        self.assertEqual(client._FILE_DOWNLOAD_READ_TIMEOUT, 60)
        self.assertGreaterEqual(client._VIDEO_DOWNLOAD_TIMEOUT, 60)
        self.assertGreaterEqual(client._AUDIO_DOWNLOAD_TIMEOUT, 60)
        self.assertGreaterEqual(client._FILE_DOWNLOAD_TIMEOUT, 60)

    def test_streams_to_atomic_output_and_closes_response(self):
        response = FakeResponse([b"video", b"-bytes"])
        session = FakeSession([response])
        with tempfile.TemporaryDirectory() as directory, patch.object(
            client, "_session", return_value=session
        ):
            path = os.path.join(directory, "result.mp4")
            client._download_video_to_path("https://cdn.test/video.mp4", path, 45)

            self.assertEqual(Path(path).read_bytes(), b"video-bytes")
            self.assertFalse(os.path.exists(f"{path}.part"))

        self.assertTrue(response.closed)
        self.assertEqual(session.calls[0][1]["timeout"], (8.0, 45.0))
        self.assertTrue(session.calls[0][1]["allow_redirects"])
        self.assertIn("video/", session.calls[0][1]["headers"]["Accept"])

    def test_failed_partial_download_is_removed_before_retry(self):
        failed = FakeResponse(
            [b"partial"],
            requests.exceptions.ReadTimeout("slow result host"),
        )
        success = FakeResponse([MP4_BYTES])
        session = FakeSession([failed, success])
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(client, "_session", return_value=session),
                patch.object(
                    client,
                    "_download_result_to_path_with_curl",
                    side_effect=client._ResultDownloadTransportError("unavailable"),
                ),
                patch.object(client, "cooperative_sleep"),
                patch.dict(os.environ, {"SEEDANCE_OUTPUT_DIR": directory}),
            ):
                video, path = client.download_video_with_path(
                    "https://cdn.test/video.mp4",
                    timeout=45,
                    max_retries=2,
                )

                self.assertEqual(video, path)
                self.assertEqual(Path(path).read_bytes(), MP4_BYTES)
                self.assertEqual(list(Path(directory).glob("*.part")), [])

        self.assertTrue(failed.closed)
        self.assertTrue(success.closed)

    def test_empty_download_never_leaves_zero_byte_output(self):
        responses = [FakeResponse([]), FakeResponse([])]
        session = FakeSession(responses)
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(client, "_session", return_value=session),
                patch.object(
                    client,
                    "_download_result_to_path_with_curl",
                    side_effect=client._ResultDownloadTransportError("unavailable"),
                ),
                patch.object(client, "cooperative_sleep"),
                patch.dict(os.environ, {"SEEDANCE_OUTPUT_DIR": directory}),
            ):
                with self.assertRaises(RuntimeError):
                    client.download_video_with_path(
                        "https://cdn.test/video.mp4",
                        timeout=45,
                        max_retries=2,
                    )

                self.assertEqual(list(Path(directory).iterdir()), [])

        self.assertTrue(all(response.closed for response in responses))

    def test_video_connection_error_immediately_uses_system_downloader(self):
        def write_video(**kwargs):
            Path(kwargs["path"]).write_bytes(MP4_BYTES)

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(
                    client,
                    "_download_result_to_path_requests",
                    side_effect=requests.exceptions.ConnectionError("offline"),
                ),
                patch.object(
                    client,
                    "_download_result_to_path_with_curl",
                    side_effect=write_video,
                ) as curl_download,
                patch.object(client, "_reset_thread_session") as reset_session,
                patch.object(client, "cooperative_sleep") as sleep,
                patch.dict(os.environ, {"SEEDANCE_OUTPUT_DIR": directory}),
            ):
                video, path = client.download_video_with_path(
                    "https://cdn.test/video.mp4"
                )

            self.assertEqual(video, path)
            self.assertEqual(Path(path).read_bytes(), MP4_BYTES)
            curl_download.assert_called_once()
            reset_session.assert_called_once_with()
            sleep.assert_not_called()

    def test_invalid_video_body_immediately_uses_system_downloader(self):
        response = FakeResponse([b"<html>not a video</html>"])
        session = FakeSession([response])

        def write_video(**kwargs):
            Path(kwargs["path"]).write_bytes(MP4_BYTES)

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(client, "_session", return_value=session),
                patch.object(
                    client,
                    "_download_result_to_path_with_curl",
                    side_effect=write_video,
                ) as curl_download,
                patch.object(client, "cooperative_sleep") as sleep,
                patch.dict(os.environ, {"SEEDANCE_OUTPUT_DIR": directory}),
            ):
                _video, path = client.download_video_with_path(
                    "https://cdn.test/video.mp4"
                )

            self.assertEqual(Path(path).read_bytes(), MP4_BYTES)
            curl_download.assert_called_once()
            sleep.assert_not_called()

    def test_content_length_mismatch_removes_partial_media(self):
        response = FakeResponse(
            [b"short"],
            headers={"Content-Length": "100", "Content-Type": "video/mp4"},
        )
        session = FakeSession([response])

        with tempfile.TemporaryDirectory() as directory, patch.object(
            client, "_session", return_value=session
        ):
            path = os.path.join(directory, "result.mp4")
            with self.assertRaises(client._ResultDownloadTransportError):
                client._download_result_to_path_requests(
                    url="https://cdn.test/video.mp4",
                    path=path,
                    timeout=45,
                    connect_timeout=8,
                    read_timeout=45,
                    headers=client._VIDEO_DOWNLOAD_HEADERS,
                )

            self.assertFalse(os.path.exists(path))
            self.assertFalse(os.path.exists(f"{path}.part"))
            self.assertTrue(response.closed)

    def test_system_file_download_keeps_result_url_out_of_arguments(self):
        result_url = "https://cdn.test/video.mp4?opaque=private-marker"

        def run_curl(command, **kwargs):
            output_index = command.index("--output") + 1
            Path(command[output_index]).write_bytes(MP4_BYTES)
            return MagicMock(returncode=0, stdout=b"", stderr=b"")

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "result.mp4")
            with (
                patch.object(client, "_find_curl_binary", return_value="curl.exe"),
                patch.object(client.subprocess, "run", side_effect=run_curl) as run,
            ):
                client._download_result_to_path_with_curl(
                    result_url,
                    path,
                    45,
                    8,
                    client._VIDEO_DOWNLOAD_HEADERS,
                )

            self.assertEqual(Path(path).read_bytes(), MP4_BYTES)
            command = run.call_args.args[0]
            self.assertNotIn(result_url, " ".join(command))
            self.assertIn(result_url.encode("utf-8"), run.call_args.kwargs["input"])
            self.assertEqual(list(Path(directory).glob("*.part")), [])

    def test_audio_connection_error_uses_system_download_and_decodes(self):
        audio_bytes = wav_bytes()

        def write_audio(**kwargs):
            Path(kwargs["path"]).write_bytes(audio_bytes)

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(
                    client,
                    "_download_result_to_path_requests",
                    side_effect=requests.exceptions.ConnectionError("offline"),
                ),
                patch.object(
                    client,
                    "_download_result_to_path_with_curl",
                    side_effect=write_audio,
                ) as curl_download,
                patch.object(client, "_reset_thread_session") as reset_session,
                patch.object(client, "cooperative_sleep") as sleep,
                patch.dict(os.environ, {"SEEDANCE_OUTPUT_DIR": directory}),
            ):
                audio, path = client.download_audio(
                    "https://cdn.test/audio.wav",
                    output_format="wav",
                    sample_rate=8000,
                )

            self.assertEqual(audio["sample_rate"], 8000)
            self.assertEqual(tuple(audio["waveform"].shape), (1, 1, 80))
            self.assertEqual(Path(path).read_bytes(), audio_bytes)
            curl_download.assert_called_once()
            reset_session.assert_called_once_with()
            sleep.assert_not_called()

    def test_generic_file_connection_error_uses_system_download(self):
        def write_file(**kwargs):
            Path(kwargs["path"]).write_bytes(b"generic-result")

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(
                    client,
                    "_download_result_to_path_requests",
                    side_effect=requests.exceptions.ConnectionError("offline"),
                ),
                patch.object(
                    client,
                    "_download_result_to_path_with_curl",
                    side_effect=write_file,
                ),
                patch.object(client, "_reset_thread_session"),
                patch.object(client, "cooperative_sleep") as sleep,
                patch.dict(os.environ, {"SEEDANCE_OUTPUT_DIR": directory}),
            ):
                path = client.download_file(
                    "https://cdn.test/result.bin",
                    default_extension="bin",
                )

            self.assertEqual(Path(path).read_bytes(), b"generic-result")
            sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
