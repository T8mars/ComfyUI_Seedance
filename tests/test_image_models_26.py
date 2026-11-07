import concurrent.futures
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image
import requests
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import nodes, concurrent_nodes as parallel
from ComfyUI_Seedance.core import image_models_26 as contracts, image_artifacts, client


def image_bytes(animated=False):
    stream = io.BytesIO()
    frame = Image.new("RGB", (32, 32), "red")
    if animated:
        frame.save(stream, format="GIF", save_all=True, append_images=[Image.new("RGB", (32, 32), "blue")],
                   duration=[100, 250], loop=0)
    else:
        frame.save(stream, format="PNG")
    return stream.getvalue()


class Image26Tests(unittest.TestCase):
    def test_independent_nodes_and_concurrent_schemas(self):
        for key in ("Zhenzhen_Image_G26", "Z_Image_T2I", "Krea_V3_Image"):
            cls = nodes.NODE_CLASS_MAPPINGS[key]
            wrapper = parallel.CONCURRENT_NODE_CLASS_MAPPINGS["SeedanceConcurrent_" + key + "_Submit"]
            self.assertEqual(cls.INPUT_TYPES(), wrapper.INPUT_TYPES())
            self.assertFalse(hasattr(wrapper, "VALIDATE_INPUTS"))
            schema = cls.INPUT_TYPES()
            seed = schema["required"].get("seed", schema["optional"].get("seed"))
            self.assertTrue(seed[1]["control_after_generate"])
            self.assertFalse(schema["optional"]["skip_error"][1]["default"])

    def test_lowprice_gif_omits_unsupported_controls(self):
        kwargs = {"prompt": "A bouncing ball", "mode": "gif", "resolution": "4k", "n": 4,
                  "output_format": "gif", "frame_count": 16, "seed": 42}
        payload = contracts.g26_payload(kwargs, ["https://example.com/ref.png"] * 2)
        self.assertEqual(set(payload), {"model", "prompt", "size", "resolution", "n", "images"})
        self.assertEqual(payload["resolution"], "1k")
        self.assertEqual(payload["n"], 1)
        self.assertIn("animated looping GIF", payload["prompt"])

    def test_lowprice_ten_ordered_references_in_image_and_gif_modes(self):
        images = [f"https://example.com/ref{i}.png" for i in range(1, 11)]
        refs = {f"image{i}": object() for i in reversed(range(1, 11))}
        for mode in ("image", "gif"):
            with self.subTest(mode=mode):
                kwargs = dict(refs, prompt="Combine the references", mode=mode)
                self.assertIs(contracts.validate_g26(kwargs, strict=True), True)
                self.assertEqual(contracts.g26_payload(kwargs, images)["images"], images)
                self.assertEqual(contracts.g26_payload({"prompt": "Edit", "mode": mode}, images)["images"], images)
                self.assertIsNot(contracts.validate_g26(dict(kwargs, image11=object())), True)
                with self.assertRaises(client.SeedanceAPIError):
                    contracts.g26_payload({"prompt": "Edit", "mode": mode}, images + [images[0]])

    def test_official_gif_exact_fields_and_stale_fields_omitted(self):
        for model in contracts.G26_MODELS[1:]:
            payload = contracts.g26_payload({"model": model, "prompt": "ball", "mode": "gif", "frame_count": 4,
                "mask_url": "stale", "markup_url": "stale", "n": 4, "resolution": "4k", "output_compression": 50,
                "complexity": "high", "seed": 42}, [])
            self.assertEqual(set(payload), {"model", "prompt", "n", "quality", "output_format", "size", "frame_count", "frame_duration_ms"})
            self.assertEqual((payload["output_format"], payload["size"], payload["n"]), ("gif", "512x512", 1))

    def test_official_gif_text_only_and_lowprice_reference_boundaries(self):
        for model in contracts.G26_MODELS[1:]:
            self.assertIsNot(contracts.validate_g26({"model": model, "mode": "gif", "image1": object()}), True)
        self.assertIs(contracts.validate_g26({"mode": "gif", "image1": object(), "image2": object()}), True)
        self.assertIs(contracts.validate_g26({"image10": object()}), True)
        self.assertIsNot(contracts.validate_g26({"image11": object()}), True)

    def test_lowprice_excess_references_fail_before_serial_or_concurrent_submission(self):
        wrapper = parallel.CONCURRENT_NODE_CLASS_MAPPINGS["SeedanceConcurrent_Zhenzhen_Image_G26_Submit"]
        with patch.object(nodes, "upload_media") as upload, patch.object(nodes, "submit_image_task") as submit, \
             patch.object(parallel, "_submit_original") as worker:
            for mode in ("image", "gif"):
                kwargs = {"prompt": "Edit", "mode": mode, "image11": torch.zeros(1, 16, 16, 3)}
                for execute in (nodes.ZhenzhenImageG26().execute, wrapper().submit):
                    with self.subTest(mode=mode, execute=execute), self.assertRaises(client.SeedanceAPIError):
                        execute(**kwargs)
            upload.assert_not_called()
            submit.assert_not_called()
            worker.assert_not_called()

    def test_lowprice_ten_local_references_upload_in_order_serial_and_concurrent(self):
        wrapper = parallel.CONCURRENT_NODE_CLASS_MAPPINGS["SeedanceConcurrent_Zhenzhen_Image_G26_Submit"]
        for concurrent in (False, True):
            with self.subTest(concurrent=concurrent):
                refs = {f"image{i}": torch.full((1, 16, 16, 3), i / 10) for i in reversed(range(1, 11))}
                urls = [f"https://example.com/ref{i}.png" for i in range(1, 11)]
                try:
                    with patch.object(nodes, "get_config", return_value={}), \
                         patch.object(nodes, "upload_media", side_effect=urls) as upload, \
                         patch.object(nodes, "submit_image_task", return_value="fixture") as submit, \
                         patch.object(nodes, "poll_image_task", return_value={}), \
                         patch.object(nodes, "extract_image_urls", return_value=["https://example.com/result.png"]), \
                         patch.object(image_artifacts, "download_original", return_value=(torch.zeros(1, 16, 16, 3),
                             "result.png", {"filename": "result.png", "type": "output", "subfolder": ""}, [0], "png")):
                        kwargs = dict(refs, prompt="Combine the references", seed=42)
                        result = wrapper().submit(**kwargs)[0].future.result(timeout=10) if concurrent else nodes.ZhenzhenImageG26().execute(**kwargs)
                    self.assertEqual(len(result["result"]), 8)
                    self.assertEqual(submit.call_args.args[0]["images"], urls)
                    self.assertNotIn("seed", submit.call_args.args[0])
                    self.assertEqual(upload.call_count, 10)
                    for index, call in enumerate(upload.call_args_list, 1):
                        self.assertEqual(call.args[1], f"reference_{index}.png")
                        with Image.open(io.BytesIO(call.args[0])) as image:
                            self.assertLessEqual(abs(image.getpixel((0, 0))[0] - index * 255 / 10), 1)
                finally:
                    if concurrent:
                        parallel.shutdown_concurrent_pools(wait=True)

    def test_lowprice_last_reference_is_validated_before_any_upload(self):
        refs = {f"image{i}": torch.zeros(1, 16, 16, 3) for i in range(1, 11)}
        refs["image10"] = torch.zeros(2, 16, 16, 3)
        with patch.object(nodes, "upload_media") as upload, patch.object(nodes, "submit_image_task") as submit:
            with self.assertRaises(client.SeedanceAPIError):
                nodes.ZhenzhenImageG26().execute(prompt="Edit", **refs)
            upload.assert_not_called()
            submit.assert_not_called()

    def test_gif_contact_sheet_boundaries_and_transposition(self):
        common = {"model": contracts.G26_MODELS[1], "mode": "gif", "frame_size": "custom"}
        for count in range(2, 17):
            self.assertIs(contracts.validate_g26(dict(common, frame_count=count, frame_width=512, frame_height=512)), True)
        self.assertIs(contracts.validate_g26(dict(common, frame_count=2, frame_width=512, frame_height=1536)), True)
        self.assertIsNot(contracts.validate_g26(dict(common, frame_count=16, frame_width=1024, frame_height=1024)), True)
        self.assertIsNot(contracts.validate_g26(dict(common, frame_width=513)), True)

    def test_gif_frame_and_duration_boundaries(self):
        for field, invalid in (("frame_count", [1, 17, True, 4.0]), ("frame_duration_ms", [0, 19, 25, True])):
            for value in invalid:
                self.assertIsNot(contracts.validate_g26({"model": contracts.G26_MODELS[1], "mode": "gif", field: value}), True)

    def test_official_static_payload(self):
        kwargs = {"model": contracts.G26_MODELS[2], "prompt": "test", "size": "custom", "width": 1536, "height": 1024,
                  "n": 4, "quality": "high", "complexity": "medium", "output_format": "webp", "output_compression": 75,
                  "mask_url": "https://example.com/mask.png"}
        payload = contracts.g26_payload(kwargs, ["https://example.com/ref.png"] * 16)
        self.assertEqual(payload["size"], "1536x1024")
        self.assertEqual(payload["output_compression"], 75)
        self.assertNotIn("resolution", payload)
        self.assertEqual(len(payload["images"]), 16)
        self.assertNotIn("frame_count", payload)

    def test_static_mask_and_size_validation(self):
        common = {"model": contracts.G26_MODELS[1], "prompt": "test"}
        for extra in ({"mask_url": "file:///tmp/mask.png"}, {"mask_url": "https://example.com/m", "markup_url": "https://example.com/a"},
                      {"size": "custom", "width": 512, "height": 512}, {"size": "custom", "width": True}, {"n": 5}, {"image17": object()}):
            self.assertIsNot(contracts.validate_g26(dict(common, **extra)), True)
        self.assertIsNot(contracts.validate_g26(dict(common, mask_url="https://example.com/m"), strict=True), True)

    def test_linked_dimensions_not_guessed_at_queue_time(self):
        self.assertIs(contracts.validate_basic("krea", {"size": "custom", "width": 4096}), True)
        self.assertIs(contracts.validate_g26({"model": contracts.G26_MODELS[1], "size": "custom", "width": 3840}), True)
        for kind in ("krea", "z_image"):
            self.assertIs(contracts.validate_basic(kind, {}), True)
            self.assertIsNot(contracts.validate_basic(kind, {}, strict=True), True)

    def test_krea_exact_contract_and_pixel_limit(self):
        payload = contracts.basic_payload("krea", {"model": "krea-v3-i2i", "prompt": "edit", "size": "custom", "width": 256,
            "height": 512, "model_variant": "jam", "reasoning_level": "medium", "output_format": "jpeg", "seed": 42,
            "negative_prompt": " blur "}, ["https://example.com/ref.png"] * 8)
        self.assertEqual(payload["metadata"], {"model_variant": "jam", "reasoning_level": "medium"})
        self.assertEqual(payload["size"], "256*512")
        self.assertNotIn("n", payload)
        self.assertEqual(payload["seed"], 42)
        self.assertEqual(payload["negative_prompt"], "blur")
        for extra in ({"size": "custom", "width": 4096, "height": 4096}, {"width": None, "size": "custom"},
                      {"seed": 2147483648}, {"model_variant": "bad"}, {"output_format": "webp"}, {"image9": object()}):
            self.assertIsNot(contracts.validate_basic("krea", dict(prompt="test", **extra), strict=True), True)

    def test_krea_mode_requires_correct_references(self):
        self.assertIsNot(contracts.validate_basic("krea", {"model": "krea-v3-i2i", "prompt": "edit"}, strict=True), True)
        self.assertIsNot(contracts.validate_basic("krea", {"image1": object()}), True)
        self.assertIs(contracts.validate_basic("krea", {"model": "krea-v3-i2i", "prompt": "edit", "image8": object()}, strict=True), True)

    def test_z_exact_contract_and_random_seed_omission(self):
        payload = contracts.basic_payload("z_image", {"prompt": "test", "ratio": "16:9", "seed": -1, "n": 2}, [])
        self.assertEqual(payload, {"model": "z-image-t2i", "prompt": "test", "metadata": {"ratio": "16:9"}})
        self.assertEqual(contracts.basic_payload("z_image", {"prompt": "test", "seed": 42}, [])["metadata"]["seed"], 42)
        self.assertIsNot(contracts.validate_basic("z_image", {"image1": object()}), True)

    def test_raw_gif_all_frames_and_timing(self):
        data = image_bytes(True)
        image, extension, durations = image_artifacts.decode_original(data, True)
        self.assertEqual(tuple(image.shape), (2, 32, 32, 3))
        self.assertEqual((extension, durations), ("gif", [100, 250]))
        self.assertFalse(torch.equal(image[0], image[1]))

    def test_gif_mode_rejects_static_results(self):
        with self.assertRaises(client.SeedanceAPIError):
            image_artifacts.decode_original(image_bytes(), True)

    def test_original_file_atomic_and_native_preview_path(self):
        data = image_bytes(True)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"SEEDANCE_OUTPUT_DIR": directory}), \
             patch.object(client, "_download_image_bytes", return_value=data):
            image, path, entry, durations, extension = image_artifacts.download_original("https://example.com/result", "nested/test", True)
            self.assertEqual(Path(path).read_bytes(), data)
            self.assertEqual(entry, {"filename": Path(path).name, "subfolder": "nested", "type": "output"})
            self.assertEqual(len(list(Path(directory).rglob("*.part"))), 0)
            self.assertEqual((image.shape[0], extension, durations), (2, "gif", [100, 250]))

    def test_output_prefix_cannot_escape_root(self):
        for value in (".", "..", "../evil", "C:/evil", "/evil", "", "nested/../../evil"):
            with self.assertRaises(client.SeedanceAPIError):
                image_artifacts.output_target(value)

    def test_invalid_input_fails_before_upload_or_submit(self):
        with patch.object(nodes, "upload_media") as upload, patch.object(nodes, "submit_image_task") as submit:
            for cls, kwargs in ((nodes.ZhenzhenImageG26, {"prompt": "test", "filename_prefix": "../evil"}),
                                (nodes.KreaV3Image, {"prompt": "test", "model": "krea-v3-i2i"}),
                                (nodes.ZImageT2I, {"prompt": ""})):
                with self.assertRaises(client.SeedanceAPIError):
                    cls().execute(**kwargs)
            upload.assert_not_called()
            submit.assert_not_called()

    def test_g26_skip_error_preserves_arity(self):
        result = nodes.ZhenzhenImageG26().execute(prompt="", skip_error=True)
        self.assertEqual(len(result["result"]), 8)
        self.assertEqual(result["result"][1:3], ("", ""))
        self.assertEqual(result["result"][4:], ("", "[]", "[]", "[]"))

    def test_concurrent_animated_preview_preserves_slot_order(self):
        def handle(name):
            future = concurrent.futures.Future()
            future.set_result({"ui": {"images": [{"filename": name + ".gif", "subfolder": "", "type": "output"}], "animated": (True,)},
                "result": (torch.zeros(2, 16, 16, 3), "", "", "")})
            return parallel.ConcurrentTaskHandle(future, "image", "Zhenzhen_Image_G26", 0,
                ("image", "image_url", "task_id", "response"), threading.Event())
        result = parallel.SeedanceConcurrentImageAwait().wait_all(future_2=handle("two"), future_1=handle("one"))
        self.assertEqual(len(result["result"]), 31)
        self.assertEqual([item["filename"] for item in result["ui"]["images"]], ["one.gif", "two.gif"])
        self.assertEqual(json.loads(result["result"][-1])["completed"], 2)

    def test_gif_downloading_uses_existing_network_recovery(self):
        data = image_bytes(True)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"SEEDANCE_OUTPUT_DIR": directory}), \
             patch.object(client, "_download_image_bytes", side_effect=[requests.exceptions.SSLError("TLS"), data]) as download, \
             patch.object(client, "_tencent_cos_result_url_fallback", return_value="https://example.com/recovered.gif"):
            image, path, entry, timing, extension = image_artifacts.download_original("https://example.com/source.gif", require_gif=True)
            self.assertEqual(download.call_count, 2)
            self.assertEqual(Path(path).read_bytes(), data)
            self.assertEqual((image.shape[0], extension), (2, "gif"))

    def test_gif_concurrency_one_skipped_error_keeps_other_nine_previews(self):
        def execute(**kwargs):
            if kwargs["prompt"] == "fail":
                raise RuntimeError("fixture failure")
            return {"ui": {"images": [{"filename": "test.gif", "subfolder": "", "type": "output"}], "animated": (True,)},
                "result": (torch.zeros(2, 16, 16, 3), "", "", "", "", "[]", "[]", "[]")}
        wrapper = parallel.CONCURRENT_NODE_CLASS_MAPPINGS["SeedanceConcurrent_Zhenzhen_Image_G26_Submit"]
        try:
            with patch.object(nodes.ZhenzhenImageG26, "_execute_inner", side_effect=execute):
                handles = [wrapper().submit(prompt="fail" if i == 3 else "pass", skip_error=True)[0] for i in range(10)]
                result = parallel.SeedanceConcurrentImageAwait().wait_all(**{f"future_{i + 1}": handle for i, handle in enumerate(handles)})
            summary = json.loads(result["result"][-1])
            self.assertEqual((summary["completed"], summary["failed"]), (9, 1))
            self.assertTrue(summary["slots"][3]["skipped"])
            self.assertEqual(len(result["ui"]["images"]), 9)
            self.assertEqual(len(result["result"]), 31)
        finally:
            parallel.shutdown_concurrent_pools(wait=True)

    def test_g26_multiple_static_results_keep_all_files_and_frames(self):
        with patch.object(nodes, "get_config", return_value={}), patch.object(nodes, "submit_image_task", return_value="fixture"), \
             patch.object(nodes, "poll_image_task", return_value={}), \
             patch.object(nodes, "extract_image_urls", return_value=["https://example.com/a", "https://example.com/b"]), \
             patch.object(image_artifacts, "download_original", side_effect=[
                 (torch.zeros(1, 32, 32, 3), "a.png", {"filename": "a.png", "type": "output", "subfolder": ""}, [0], "png"),
                 (torch.ones(1, 32, 32, 3), "b.png", {"filename": "b.png", "type": "output", "subfolder": ""}, [0], "png")]):
            result = nodes.ZhenzhenImageG26().execute(prompt="test", model=contracts.G26_MODELS[1], n=2)
        self.assertEqual(tuple(result["result"][0].shape), (2, 32, 32, 3))
        self.assertEqual(json.loads(result["result"][6]), ["a.png", "b.png"])
        self.assertEqual(len(result["ui"]["images"]), 2)
        self.assertNotIn("animated", result["ui"])


if __name__ == "__main__":
    unittest.main()
