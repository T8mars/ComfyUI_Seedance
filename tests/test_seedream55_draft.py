import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import nodes, concurrent_nodes
from ComfyUI_Seedance.core import client, seedream55 as api
from ComfyUI_Seedance.core.client import SeedanceAPIError

CONFIG = {"base_url": "https://example.test", "api_key": "sk-test"}
URL = "https://example.com/image.png"
IMAGE = torch.zeros(1, 4, 4, 3)


class Seedream55Tests(unittest.TestCase):
    def tearDown(self):
        concurrent_nodes.shutdown_concurrent_pools(wait=True)

    def test_independent_catalogs_outputs_lists_and_cache_controls(self):
        self.assertEqual(len(api.IMAGE_MODELS), 4)
        self.assertEqual(len(api.LAYER_MODELS), 2)
        for key, cls in (("Seedream_5_5_Image", nodes.Seedream55Image), ("Seedream_5_5_Layer_Decomposition", nodes.Seedream55LayerDecomposition)):
            self.assertIs(nodes.NODE_CLASS_MAPPINGS[key], cls)
            schema = cls.INPUT_TYPES()
            self.assertFalse(schema["optional"]["skip_error"][1]["default"])
            self.assertTrue(schema["optional"]["seed"][1]["control_after_generate"])
            self.assertTrue(cls.SEEDANCE_CACHE_ONLY_SEED)
        self.assertEqual(nodes.Seedream55LayerDecomposition.OUTPUT_IS_LIST, (True, True, False, False, False, False, False, False))
        self.assertNotIn("SeedanceConcurrent_Seedream_5_5_Layer_Decomposition_Submit", concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS)

    def test_all_six_models_exact_request_whitelist(self):
        for model in api.IMAGE_MODELS + api.LAYER_MODELS:
            layer = model.endswith("layer-decomposition")
            kwargs = {"model": model, "prompt": "five characters", "resolution": "1k", "seed": 42,
                      "safety_identifier": "test-session", "unknown": "ignored", "width": 123, "height": 456}
            urls = []
            if layer:
                kwargs.update(image=IMAGE, max_images=2, text_recognition=True)
                urls = [URL]
            elif model.endswith("i2i"):
                kwargs["image1"] = IMAGE
                urls = [URL]
            payload = api.payload(kwargs, urls, layer)
            self.assertEqual(payload["model"], model)
            self.assertEqual(payload["metadata"]["resolution"], "1k")
            self.assertNotIn("width", payload["metadata"])
            self.assertNotIn("seed", payload["metadata"])
            self.assertNotIn("unknown", payload)
            self.assertFalse(payload["metadata"]["watermark"])
            self.assertEqual(payload["metadata"]["safety_identifier"], "test-session")
            if layer:
                self.assertEqual(payload["metadata"]["max_images"], 2)
                self.assertTrue(payload["metadata"]["text_recognition"])
                self.assertNotIn("background", payload["metadata"])

    def test_reference_bounds_t2i_and_i2i(self):
        base = {"model": api.IMAGE_MODELS[1], "prompt": "five chars"}
        for count in (1, 10):
            kwargs = {**base, **{f"image{i}": IMAGE for i in range(1, count+1)}}
            self.assertTrue(api.validate(kwargs, strict=True))
        for kwargs in (base, {**base, "image11": IMAGE}, {"prompt": "five chars", "image1": IMAGE}):
            with self.assertRaises(SeedanceAPIError):
                api.validate(kwargs, strict=True)

    def test_custom_canvas_limits_area_ratio_and_resolution_precedence(self):
        for width, height in ((960, 960), (11520, 720), (720, 11520), (2048, 1152)):
            payload = api.payload({"prompt": "five chars", "resolution": "custom", "width": width, "height": height}, [])
            self.assertEqual(payload["metadata"]["width"], width)
            self.assertNotIn("resolution", payload["metadata"])
        for width, height in ((959, 960), (11521, 720), (11520, 719), (3000, 3000), (True, 1024), (1024.0, 1024)):
            with self.subTest(width=width, height=height), self.assertRaises(SeedanceAPIError):
                api.validate({"prompt": "five chars", "resolution": "custom", "width": width, "height": height}, strict=True)

    def test_prompts_transparency_safety_and_boolean_types(self):
        for kwargs in ({"prompt": "four"}, {"prompt": "x"*5001}, {"prompt": 42}, {"prompt": "valid text", "background": "transparent", "output_format": "jpeg"},
                       {"prompt": "valid text", "watermark": "false"}, {"prompt": "valid text", "safety_identifier": "x"*65}):
            with self.assertRaises(SeedanceAPIError):
                api.validate(kwargs, strict=True)
        self.assertTrue(api.validate({"prompt": None, "resolution": "custom", "width": None, "height": None}, strict=False))
        self.assertTrue(api.validate({"prompt": "x"*5000, "background": "transparent", "output_format": "png"}, strict=True))
        self.assertTrue(api.validate({"image": IMAGE, "prompt": ""}, layer=True, strict=True))
        with self.assertRaises(SeedanceAPIError):
            api.validate({"image": IMAGE, "prompt": "x"*2001}, layer=True, strict=True)

    def test_layer_max_images_includes_base(self):
        for count in (2, 30, 100):
            self.assertTrue(api.validate({"image": IMAGE, "max_images": count}, layer=True, strict=True))
        for count in (1, 101, 2.0, True, "2"):
            with self.assertRaises(SeedanceAPIError):
                api.validate({"image": IMAGE, "max_images": count}, layer=True, strict=True)
        with self.assertRaises(SeedanceAPIError):
            api.validate({"image": IMAGE, "image1": IMAGE}, layer=True, strict=True)

    def test_reference_png_preserves_alpha_and_source_order(self):
        rgba = torch.ones(1, 3, 2, 4)
        rgba[0, 0, 0, 3] = 0
        encoded = api.encode_references({"image2": rgba, "image10": IMAGE})
        self.assertEqual([index for index, _ in encoded], [2, 10])
        with Image.open(io.BytesIO(encoded[0][1])) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((0, 0))[3], 0)

    def test_bad_references_batches_sizes_and_nan_fail_before_upload(self):
        for reference in (torch.zeros(2, 4, 4, 3), torch.zeros(1, 4, 4, 2), torch.full((1, 4, 4, 3), float("nan"))):
            with patch.object(nodes, "upload_media") as upload:
                with self.assertRaises(SeedanceAPIError):
                    nodes.Seedream55Image().execute(model=api.IMAGE_MODELS[1], prompt="five chars", image1=IMAGE, image2=reference, api_config=CONFIG)
                upload.assert_not_called()
        with patch.object(api, "SOURCE_BYTES", 4), patch.object(nodes, "upload_media") as upload:
            with self.assertRaises(SeedanceAPIError):
                nodes.Seedream55LayerDecomposition().execute(image=IMAGE, api_config=CONFIG)
            upload.assert_not_called()

    def test_original_download_rgba_mask_and_byte_preservation(self):
        source = Image.new("RGBA", (3, 2), (15, 30, 60, 255))
        source.putpixel((0, 0), (30, 60, 90, 0))
        buffer = io.BytesIO()
        source.save(buffer, format="PNG")
        data = buffer.getvalue()
        with tempfile.TemporaryDirectory() as directory, patch.dict("sys.modules", {"folder_paths": SimpleNamespace(get_output_directory=lambda: directory)}), \
                patch.object(api, "_download_and_decode_image", side_effect=lambda url, decode, *args: decode(data)):
            image, mask, path, entry = api.download_original(URL)
            self.assertEqual(image.shape[-1], 4)
            self.assertEqual(float(mask[0, 0, 0]), 1)
            self.assertEqual(float(mask[0, 0, 1]), 0)
            self.assertEqual(Path(path).read_bytes(), data)
            self.assertEqual(entry["type"], "output")
            self.assertFalse(list(Path(directory).rglob("*.part")))

    def test_layer_metadata_missing_is_not_invented(self):
        self.assertEqual(api.layer_metadata({"data": None}, [URL]), [])
        final = {"data": {"data": {"content": {"image_urls": [URL]}}}}
        self.assertEqual(api.layer_metadata(final, [URL]), [])
        final["data"]["data"]["content"]["layers"] = [{"url": URL, "name": "foreground", "boundingBox": [0, 0, 1, 1]}]
        self.assertEqual(api.layer_metadata(final, [URL])[0]["name"], "foreground")
        with self.assertRaises(SeedanceAPIError):
            api.layer_metadata(final, [URL, URL])

    def test_invalid_output_prefix_stops_before_upload_or_task_creation(self):
        for cls, kwargs in ((nodes.Seedream55Image, {"prompt": "five chars"}),
                            (nodes.Seedream55LayerDecomposition, {"image": IMAGE})):
            with patch.object(nodes, "upload_media") as upload, patch.object(nodes, "submit_image_task") as submit:
                with self.assertRaises(SeedanceAPIError):
                    cls().execute(filename_prefix="../outside", api_config=CONFIG, **kwargs)
                upload.assert_not_called()
                submit.assert_not_called()

    def test_all_100_layer_outputs_survive_without_resizing_or_truncation(self):
        urls = [f"https://example.com/layer{i}.png" for i in range(100)]
        final = {"data": {"data": {"content": {"image_urls": urls}}}}
        def download(url, prefix):
            index = urls.index(url)
            return torch.zeros(1, index+1, 2, 4), torch.zeros(1, index+1, 2), f"/output/layer{index}.png", {"filename": f"layer{index}.png"}
        with patch.object(nodes, "get_config", return_value=CONFIG), patch.object(nodes, "upload_media", return_value=URL), \
                patch.object(nodes, "submit_image_task", return_value="example-task"), patch.object(nodes, "poll_image_task", return_value=final), \
                patch.object(api, "download_original", side_effect=download) as downloads:
            result = nodes.Seedream55LayerDecomposition().execute(image=IMAGE, max_images=100)
        values = result["result"]
        self.assertEqual(len(values[0]), 100)
        self.assertEqual(len(values[1]), 100)
        self.assertEqual(values[3], 100)
        self.assertEqual(values[0][-1].shape[1], 100)
        self.assertEqual(len(json.loads(values[6])), 100)
        self.assertEqual(len(result["ui"]["images"]), 100)
        self.assertEqual([call.args[0] for call in downloads.call_args_list], urls)

    def test_new_nodes_skip_error_outputs_are_typed_and_cache_seed_is_removed(self):
        for cls in (nodes.Seedream55Image, nodes.Seedream55LayerDecomposition):
            with patch.object(cls, "_execute_inner", side_effect=RuntimeError("offline")) as inner:
                with self.assertRaises(RuntimeError):
                    cls().execute(seed=42)
                result = cls().execute(seed=42, skip_error=True)["result"]
                self.assertNotIn("seed", inner.call_args.kwargs)
            self.assertEqual(len(result), len(cls.RETURN_TYPES))
        for key in ("SeedanceConcurrent_Seedream_5_5_Image_Submit", "SeedanceConcurrent_Seedance_2_5_Draft_To_Video_Submit"):
            self.assertFalse(hasattr(concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[key], "VALIDATE_INPUTS"))

    def test_concurrent_collector_retains_rgba_primary(self):
        cls = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS["SeedanceConcurrent_Seedream_5_5_Image_Submit"]
        rgba = torch.ones(1, 3, 4, 4)
        rgba[..., 3] = 0
        with patch.object(nodes.Seedream55Image, "_execute_inner", return_value={"result": (rgba, URL, "example-task", "{}", rgba[..., 3], "/output/image.png")}):
            future = cls().submit(prompt="five chars", api_config=CONFIG)[0]
            output = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS["SeedanceConcurrent_Image_Await"]().wait_all(future_1=future)
        values = output["result"] if isinstance(output, dict) else output
        self.assertTrue(torch.equal(values[0], rgba))


class DraftTests(unittest.TestCase):
    def test_existing_seedance25_widget_prefix_and_draft_default(self):
        schema = nodes.Seedance25Video.INPUT_TYPES()
        self.assertFalse(schema["optional"]["draft"][1]["default"])
        self.assertEqual(list(schema["optional"])[-5:], ["generate_audio", "seed", "api_config", "skip_error", "draft"])
        self.assertEqual(nodes.Seedance25Video.RETURN_NAMES, ("video", "video_url", "task_id", "response"))
        base = {"model": nodes.SEEDANCE25_T2V_MODELS[0], "prompt": "A blue ball rolls slowly", "seconds": "4", "resolution": "native1080p", "ratio": "16:9"}
        normal = nodes.Seedance25Video().build_payload(base, {})
        self.assertNotIn("draft", normal["metadata"])
        self.assertEqual(normal["metadata"]["resolution"], "native1080p")
        draft = nodes.Seedance25Video().build_payload({**base, "draft": True}, {})
        self.assertTrue(draft["metadata"]["draft"])
        self.assertEqual(draft["metadata"]["resolution"], "480p")

    def test_all_six_draft_source_models_keep_original_media_contract(self):
        for model in nodes.SEEDANCE25_MODELS:
            base = {"model": model, "prompt": "A blue ball rolls slowly", "seconds": "4", "resolution": "4k", "ratio": "16:9", "draft": True}
            media = {"images": [URL]} if model.endswith("i2v") else {"content": [{"type": "image_url", "image_url": {"url": URL}}]} if model.endswith("multi") else {}
            result = nodes.Seedance25Video().build_payload(base, media)
            self.assertEqual(result["metadata"]["resolution"], "480p")
            self.assertTrue(result["metadata"]["draft"])

    def test_enhance_only_sends_documented_metadata_no_prompt_media_duration_or_seed(self):
        for model in nodes.Seedance25DraftToVideo.MODELS:
            payload = nodes.Seedance25DraftToVideo().build_payload({"model": model, "draft_task_id": " example-task ",
                "output_format": "mov", "return_last_frame": True, "prompt": "stale", "seconds": "30", "image1": IMAGE, "seed": 999, "resolution": "4k"})
            self.assertEqual(payload, {"model": model, "metadata": {"draft_task_id": "example-task", "output_format": "mov", "return_last_frame": True}})

    def test_id_validation_defers_connected_input_and_rejects_url(self):
        self.assertTrue(nodes.Seedance25DraftToVideo.VALIDATE_INPUTS(draft_task_id=None))
        for kwargs in ({}, {"draft_task_id": ""}, {"draft_task_id": "https://example.com/video.mp4"}, {"draft_task_id": 123},
                       {"draft_task_id": "example-task", "output_format": "avi"}, {"draft_task_id": "example-task", "return_last_frame": "true"}):
            with patch.object(nodes, "submit_task") as submit:
                with self.assertRaises(SeedanceAPIError):
                    nodes.Seedance25DraftToVideo().execute(api_config=CONFIG, **kwargs)
                submit.assert_not_called()

    def test_enhance_executes_shared_poll_and_mov_downloader(self):
        with patch.object(nodes, "submit_task", return_value="example-task") as submit, \
                patch.object(nodes, "poll_task", return_value={"status": "completed"}), \
                patch.object(nodes, "extract_video_url", return_value=URL), \
                patch.object(nodes, "download_video_with_path", return_value=("video", "file.mov")) as download:
            result = nodes.Seedance25DraftToVideo().execute(draft_task_id="example-draft", api_config=CONFIG, output_format="mov", seed=42)
        self.assertEqual(result["result"][:3], ("video", URL, "example-task"))
        self.assertEqual(download.call_args.kwargs["file_extension"], "mov")
        self.assertNotIn("seed", submit.call_args.args[0]["metadata"])

    def test_mov_download_suffix_is_opt_in_and_default_stays_mp4(self):
        def write_file(**kwargs):
            Path(kwargs["path"]).write_bytes(b"local test media")
        with tempfile.TemporaryDirectory() as directory, patch.dict("sys.modules", {"folder_paths": SimpleNamespace(get_output_directory=lambda: directory)}), \
                patch.dict("os.environ", {"SEEDANCE_OUTPUT_DIR": directory}), patch.object(client, "_download_to_path_with_recovery", side_effect=write_file):
            self.assertTrue(client.download_video_with_path(URL)[1].endswith(".mp4"))
            self.assertTrue(client.download_video_with_path(URL, file_extension="mov")[1].endswith(".mov"))

    def test_eleven_examples_blank_keys_connections_and_layer_alpha_saving(self):
        files = [path for path in (ROOT/"examples").glob("*.json") if "5.5" in path.name or path.name == "Seedream55透明PNG.json" or "draft-to-video" in path.name]
        self.assertEqual(len(files), 11)
        for path in files:
            graph = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(graph["nodes"][0]["widgets_values"][1], "")
            if "分层" in path.name:
                self.assertIn("JoinImageWithAlpha", [node["type"] for node in graph["nodes"]])
                self.assertIn("SaveImage", [node["type"] for node in graph["nodes"]])
            if "成片连线" in path.name:
                enhanced = next(node for node in graph["nodes"] if node["type"] == "Seedance_2_5_Draft_To_Video")
                linked = next(item for item in enhanced["inputs"] if item["name"] == "draft_task_id")
                link = next(item for item in graph["links"] if item[0] == linked["link"])
                self.assertEqual(link[2], 2)


if __name__ == "__main__":
    unittest.main()
