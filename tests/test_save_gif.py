import concurrent.futures
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import nodes, concurrent_nodes
from ComfyUI_Seedance.core import gif_export, client, image_artifacts


def original_bytes(loop=3):
    output = io.BytesIO()
    frames = [Image.new("RGB", (48, 32), color) for color in ("red", "green", "blue")]
    frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:], duration=[70, 130, 270], loop=loop, disposal=2)
    return output.getvalue()


def image_frames():
    frames = torch.zeros(3, 32, 48, 3)
    for index in range(3):
        frames[index, ..., index] = 1
    return frames


class SaveGIFTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, {"SEEDANCE_OUTPUT_DIR": self.directory.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.modules = patch.dict(sys.modules, {"folder_paths": None})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def original(self, data=None):
        path = Path(self.directory.name) / "original.gif"
        path.write_bytes(original_bytes() if data is None else data)
        return path

    def test_independent_output_utility_not_api_generation(self):
        cls = nodes.NODE_CLASS_MAPPINGS["Seedance_Save_GIF"]
        self.assertIs(cls, nodes.SeedanceSaveGIF)
        self.assertTrue(cls.OUTPUT_NODE)
        self.assertEqual(cls.RETURN_TYPES, ("STRING", "STRING"))
        schema = cls.INPUT_TYPES()
        self.assertEqual(list(schema["required"]), ["filename_prefix", "source_mode", "fps", "loop"])
        self.assertEqual(list(schema["optional"]), ["images", "source_path", "durations_json"])
        self.assertTrue(schema["optional"]["source_path"][1]["forceInput"])
        self.assertNotIn("api_config", schema["optional"])
        self.assertNotIn("skip_error", schema["optional"])
        self.assertNotIn("SeedanceConcurrent_Seedance_Save_GIF_Submit", concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS)

    def test_original_preserves_bytes_frames_timing_and_loop(self):
        source = self.original()
        result = nodes.SeedanceSaveGIF().save(source_path=str(source), images="ignored", fps=50, loop=0)
        path, timing = result["result"]
        self.assertEqual(Path(path).read_bytes(), source.read_bytes())
        self.assertEqual(json.loads(timing), [70, 130, 270])
        with Image.open(path) as gif:
            self.assertEqual((gif.n_frames, gif.info["loop"]), (3, 3))
        self.assertEqual(result["ui"]["animated"], (True,))
        self.assertEqual(result["ui"]["images"][0]["subfolder"], "seedance")

    def test_auto_prefers_original_and_ignores_encoding_settings(self):
        source = self.original()
        path, _, _, _ = gif_export.save_gif(source_path=str(source), images=None, fps=float("nan"), loop=-1, durations_json="bad")
        self.assertEqual(Path(path).read_bytes(), source.read_bytes())

    def test_frames_default_fps_order_and_loop(self):
        path, entry, count, timings = gif_export.save_gif(images=image_frames(), fps=5, loop=2)
        self.assertEqual((count, timings), (3, [200, 200, 200]))
        with Image.open(path) as gif:
            self.assertEqual(gif.info["loop"], 2)
            for index in range(3):
                gif.seek(index)
                color = np.asarray(gif.convert("RGB"))[0, 0]
                self.assertEqual(int(color[index]), 255)
        self.assertTrue(entry["filename"].endswith(".gif"))

    def test_frame_mode_ignores_stale_original_path(self):
        path, _, count, _ = gif_export.save_gif(images=image_frames(), source_mode="frames", source_path="missing.gif")
        self.assertTrue(Path(path).is_file())
        self.assertEqual(count, 3)

    def test_flat_and_g26_nested_durations_override_fps(self):
        for timing in ("[70,130,270]", "[[70,130,270]]", "[[70],[130,270]]"):
            path, _, _, actual = gif_export.save_gif(images=image_frames(), durations_json=timing, fps=1)
            self.assertEqual(actual, [70, 130, 270])
            self.assertEqual(gif_export.inspect_gif(path)[1], actual)

    def test_gif_centisecond_quantization(self):
        self.assertEqual(gif_export.frame_durations("[123]", 1, 10), [120])
        self.assertEqual(gif_export.frame_durations("", 1, 7), [140])

    def test_invalid_duration_values(self):
        for timing in ("bad", "{}", "[]", "[1]", "[true]", "[10.0]", "[655351]", "[[10],20]", "[10,20]", 10):
            with self.subTest(timing=timing), self.assertRaises(client.SeedanceAPIError):
                gif_export.frame_durations(timing, 1, 10)

    def test_invalid_fps(self):
        for fps in (0, -.1, .01, 101, True, float("inf"), float("nan"), "10"):
            with self.subTest(fps=fps), self.assertRaises(client.SeedanceAPIError):
                gif_export.save_gif(images=image_frames(), fps=fps)

    def test_invalid_loop(self):
        for loop in (-1, 65536, True, 1.0, "0"):
            with self.subTest(loop=loop), self.assertRaises(client.SeedanceAPIError):
                gif_export.save_gif(images=image_frames(), loop=loop)

    def test_original_mode_requires_existing_local_gif(self):
        for value in ("", "missing.gif", "https://example.com/source.gif"):
            with self.subTest(value=value), self.assertRaises(client.SeedanceAPIError):
                gif_export.save_gif(source_mode="original", source_path=value, images=image_frames())

    def test_invalid_mode_and_source_path_type(self):
        for kwargs in ({"source_mode": "bad"}, {"source_path": True}):
            with self.assertRaises(client.SeedanceAPIError):
                gif_export.save_gif(images=image_frames(), **kwargs)

    def test_renamed_png_and_corrupt_gif_rejected_without_partial_files(self):
        output = io.BytesIO()
        Image.new("RGB", (8, 8)).save(output, format="PNG")
        for data in (output.getvalue(), b"GIF89a broken"):
            source = self.original(data)
            with self.assertRaises(Exception):
                gif_export.save_gif(source_path=str(source))
            self.assertEqual(list(Path(self.directory.name).rglob("*.part")), [])
            self.assertEqual(list((Path(self.directory.name) / "seedance").glob("*.gif")), [])

    def test_invalid_tensor_shapes(self):
        for image in (None, "images", torch.zeros(8, 8, 3), torch.zeros(0, 8, 8, 3), torch.zeros(1, 8, 8, 2), torch.zeros(1, 0, 8, 3)):
            with self.assertRaises(client.SeedanceAPIError):
                gif_export.save_gif(images=image)

    def test_nonfinite_pixels_fail_before_publishing(self):
        image = image_frames()
        image[0, 0, 0, 0] = float("nan")
        with self.assertRaises(client.SeedanceAPIError):
            gif_export.save_gif(images=image)
        self.assertEqual(list(Path(self.directory.name).rglob("*.gif")), [])

    def test_prefix_is_confined_to_output_directory(self):
        for prefix in ("..", "../escape", ".", "/absolute", "C:/escape", ""):
            with self.assertRaises(client.SeedanceAPIError):
                gif_export.save_gif(images=image_frames(), filename_prefix=prefix)

    def test_duplicate_inputs_do_not_overwrite_previous_files(self):
        first = gif_export.save_gif(images=image_frames())[0]
        before = Path(first).read_bytes()
        second = gif_export.save_gif(images=image_frames())[0]
        self.assertNotEqual(first, second)
        self.assertEqual(Path(first).read_bytes(), before)

    def test_parallel_copies_use_unique_atomic_destinations(self):
        source = self.original()
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            paths = list(pool.map(lambda _: gif_export.save_gif(source_path=str(source))[0], range(10)))
        self.assertEqual(len(set(paths)), 10)
        self.assertTrue(all(Path(path).read_bytes() == source.read_bytes() for path in paths))
        self.assertEqual(list(Path(self.directory.name).rglob("*.part")), [])

    @unittest.skipUnless(os.name == "nt", "Windows path namespace regression")
    def test_windows_extended_namespace_normalizes_drive_and_unc(self):
        for raw, expected in ((r"\\?\C:\output\nested", r"C:\output\nested"),
                              (r"\\?\UNC\server\share\nested", r"\\server\share\nested")):
            with patch.object(Path, "resolve", return_value=Path(raw)):
                self.assertEqual(image_artifacts._canonical_path(Path("ignored")), Path(expected))

    def test_failed_atomic_publish_removes_partial(self):
        with patch.object(gif_export.os, "replace", side_effect=OSError("failed publish")), self.assertRaises(OSError):
            gif_export.save_gif(images=image_frames())
        self.assertEqual(list(Path(self.directory.name).rglob("*.part")), [])
        self.assertEqual(list(Path(self.directory.name).rglob("*.gif")), [])

    def test_single_frame_is_a_valid_static_gif(self):
        path, _, count, _ = gif_export.save_gif(images=image_frames()[:1])
        self.assertEqual(count, 1)
        with Image.open(path) as image:
            self.assertEqual(image.format, "GIF")

    def test_rgba_frames_supported(self):
        rgba = torch.cat([image_frames(), torch.ones(3, 32, 48, 1)], dim=-1)
        self.assertEqual(gif_export.save_gif(images=rgba)[2], 3)

    def test_serial_gif_examples_connect_original_and_frames(self):
        for suffix in ("lowprice", "flare", "sunburst"):
            path = ROOT / "examples" / ("zhenzhen-image-g-v2.6-" + suffix + "GIF动画.json")
            workflow = json.loads(path.read_text(encoding="utf-8"))
            saver = next(node for node in workflow["nodes"] if node["type"] == "Seedance_Save_GIF")
            self.assertTrue(all(item["link"] is not None for item in saver["inputs"]))
            self.assertNotIn("SaveImage", {node["type"] for node in workflow["nodes"]})


if __name__ == "__main__":
    unittest.main()
