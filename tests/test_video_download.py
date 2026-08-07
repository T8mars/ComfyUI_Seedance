import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT.parent))

from ComfyUI_Seedance.core import client


class FakeResponse:
    def __init__(self, chunks=None, error=None):
        self.chunks = list(chunks or [])
        self.error = error
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
        self.assertEqual(session.calls[0][1]["timeout"], (15.0, 45.0))

    def test_failed_partial_download_is_removed_before_retry(self):
        failed = FakeResponse(
            [b"partial"],
            requests.exceptions.ReadTimeout("slow result host"),
        )
        success = FakeResponse([b"complete-video"])
        session = FakeSession([failed, success])
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(client, "_session", return_value=session),
                patch.object(client, "cooperative_sleep"),
                patch.dict(os.environ, {"SEEDANCE_OUTPUT_DIR": directory}),
            ):
                video, path = client.download_video_with_path(
                    "https://cdn.test/video.mp4",
                    timeout=45,
                    max_retries=2,
                )

                self.assertEqual(video, path)
                self.assertEqual(Path(path).read_bytes(), b"complete-video")
                self.assertEqual(list(Path(directory).glob("*.part")), [])

        self.assertTrue(failed.closed)
        self.assertTrue(success.closed)

    def test_empty_download_never_leaves_zero_byte_output(self):
        responses = [FakeResponse([]), FakeResponse([])]
        session = FakeSession(responses)
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(client, "_session", return_value=session),
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


if __name__ == "__main__":
    unittest.main()
