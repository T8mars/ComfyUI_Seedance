import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import nodes, concurrent_nodes
from ComfyUI_Seedance.core import client, preview_models

CONFIG = {"base_url": "https://api.seedance.nz", "api_key": "sk-test"}
URL = "https://example.com/image.png"
KEYS = ("HY_Image_3_5_Preview", "Muse_Image", "Muse_Video", "Flux_3_Image_Variants")


class PreviewMuseTests(unittest.TestCase):
    def tearDown(self):
        concurrent_nodes.shutdown_concurrent_pools(wait=True)

    def test_frontend_switching_and_concurrent_aliases(self):
        executable = shutil.which("node")
        if not executable:
            self.skipTest("Node.js unavailable")
        result = subprocess.run([executable, str(ROOT / "tests" / "preview_muse_ui.mjs")],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_independent_registrations_and_seed_contracts(self):
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Flux_3_Image"], nodes.Flux3Image)
        for key in KEYS:
            cls = nodes.NODE_CLASS_MAPPINGS[key]
            wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[f"SeedanceConcurrent_{key}_Submit"]
            self.assertEqual(cls.INPUT_TYPES(), wrapper.INPUT_TYPES())
            self.assertFalse(issubclass(wrapper, cls))
            self.assertFalse(hasattr(wrapper, "VALIDATE_INPUTS"))
            self.assertFalse(hasattr(cls, "IS_CHANGED"))
            self.assertFalse(cls.INPUT_TYPES()["optional"]["skip_error"][1]["default"])
            spec = cls.INPUT_TYPES()["required"].get("seed") or cls.INPUT_TYPES()["optional"]["seed"]
            self.assertTrue(spec[1]["control_after_generate"])
            self.assertEqual(cls.RETURN_TYPES, (("VIDEO",) if key == "Muse_Video" else ("IMAGE",)) + ("STRING",) * 3)

    def test_hy_payload_presets_and_optional_fields(self):
        actual = preview_models.payload("hy", {"prompt": " Robot ", "resolution": "2k", "size": "16:9",
            "negative_prompt": " blur ", "seed": 42, "n": 10, "output_format": "webp"}, [URL])
        self.assertEqual(actual, {"model": preview_models.HY_MODEL, "prompt": "Robot", "n": 1,
            "size": "16:9", "resolution": "2K", "negative_prompt": "blur", "seed": 42, "images": [URL]})
        minimal = preview_models.payload("hy", {"prompt": "Robot"}, [])
        self.assertNotIn("images", minimal)
        self.assertNotIn("negative_prompt", minimal)
        self.assertEqual(minimal["seed"], 0)

    def test_hy_custom_dimensions_exact_boundaries(self):
        for width, height in ((256, 256), (8192, 256), (2000, 1104), (3840, 2160), (257, 259)):
            payload = preview_models.payload("hy", {"prompt": "Robot", "size": "custom",
                "width": width, "height": height}, [])
            self.assertEqual((payload["width"], payload["height"]), (width, height))
            self.assertNotIn("size", payload)
        for kwargs in ({"width": 255}, {"height": 8193}, {"width": True}, {"height": 256.0},
                       {"width": 8192, "height": 8192}):
            with self.subTest(kwargs=kwargs), self.assertRaises(client.SeedanceAPIError):
                preview_models.payload("hy", {"prompt": "Robot", "size": "custom", **kwargs}, [])
        # Inactive dimension controls never reach the request.
        payload = preview_models.payload("hy", {"prompt": "Robot", "width": 0, "height": 0}, [])
        self.assertNotIn("width", payload)

    def test_hy_rejects_invalid_active_values(self):
        for kwargs in ({"prompt": ""}, {"prompt": 123}, {"size": "8:1"}, {"resolution": "8K"},
                       {"seed": -1}, {"seed": True}, {"seed": 1.5}, {"negative_prompt": 123}):
            with self.subTest(kwargs=kwargs), self.assertRaises(client.SeedanceAPIError):
                preview_models.payload("hy", {"prompt": "Robot", **kwargs}, [])

    def test_hy_linked_dimensions_defer_total_pixels_until_resolved(self):
        cls = nodes.HunyuanImage35Preview
        for partial in ({"width": 8192}, {"height": 8192}):
            self.assertIs(cls.VALIDATE_INPUTS(size="custom", **partial), True)
        for width, height in ((256, 8192), (8192, 256)):
            self.assertIs(cls.VALIDATE_INPUTS(strict=True, prompt="Robot", size="custom",
                                             width=width, height=height), True)
        self.assertIsNot(cls.VALIDATE_INPUTS(strict=True, prompt="Robot", size="custom",
                                            width=8192, height=8192), True)

    def test_muse_exact_image_and_video_payloads(self):
        for kind in ("muse_image", "muse_video"):
            kwargs = {"prompt": " Robot ", "size": "auto", "seed": 42, "negative_prompt": "ignored",
                      "resolution": "4k", "seconds": 4, "generate_audio": False, "n": 9}
            payload = preview_models.payload(kind, kwargs, [URL, URL + "?second=1"])
            expected = {"model": preview_models.MUSE_IMAGE_MODEL if kind == "muse_image" else preview_models.MUSE_VIDEO_MODEL,
                        "prompt": "Robot", "n": 1, "size": "auto", "images": [URL, URL + "?second=1"]}
            if kind == "muse_video":
                expected.update(duration=10, resolution="720p", audio=True)
            self.assertEqual(payload, expected)
        for kind in ("muse_image", "muse_video"):
            for size in ("21:9", "1024x1024", "custom"):
                with self.assertRaises(client.SeedanceAPIError):
                    preview_models.payload(kind, {"prompt": "Robot", "size": size}, [])

    def test_linked_prompt_is_validated_at_execution_not_queue(self):
        for cls in (nodes.HunyuanImage35Preview, nodes.MuseImage, nodes.MuseVideo):
            self.assertIs(cls.VALIDATE_INPUTS(), True)
            self.assertIsNot(cls.VALIDATE_INPUTS(strict=True), True)
            self.assertIs(cls.VALIDATE_INPUTS(strict=True, prompt="A linked prompt"), True)

    def test_reference_order_and_batch_rejection_before_upload(self):
        image = torch.zeros((1, 8, 8, 3))
        refs = preview_models.encode_references({"image5": image, "image1": image}, 5)
        self.assertEqual([i for i, _ in refs], [1, 5])
        for cls in (nodes.HunyuanImage35Preview, nodes.MuseImage, nodes.MuseVideo):
            for kwargs in ({"image1": torch.zeros((2, 8, 8, 3))}, {"image99": image}, {"image1": torch.zeros((8, 8, 3))}):
                with self.subTest(cls=cls, kwargs=list(kwargs)), patch.object(nodes, "upload_media") as upload:
                    with self.assertRaises(client.SeedanceAPIError):
                        cls().execute(prompt="Robot", api_config=CONFIG, **kwargs)
                    upload.assert_not_called()

    def test_total_size_checked_before_any_upload(self):
        image = torch.zeros((1, 1, 1, 3))
        half = preview_models.MUSE_REFERENCE_BYTES // 2
        with patch.object(preview_models, "image_to_png_bytes", return_value=b"a" * half):
            self.assertEqual(len(preview_models.encode_references({"image1": image, "image2": image}, 9,
                total=preview_models.MUSE_REFERENCE_BYTES)), 2)
        for cls in (nodes.MuseImage, nodes.MuseVideo):
            with patch.object(preview_models, "image_to_png_bytes", return_value=b"a" * (half + 1)), \
                    patch.object(nodes, "upload_media") as upload:
                with self.assertRaisesRegex(client.SeedanceAPIError, "11 MiB"):
                    cls().execute(prompt="Robot", image1=image, image2=image, api_config=CONFIG)
                upload.assert_not_called()

    def test_image_nodes_submit_poll_and_download(self):
        image = torch.zeros((1, 8, 8, 3))
        for cls in (nodes.HunyuanImage35Preview, nodes.MuseImage):
            with patch.object(nodes, "upload_media", return_value=URL) as upload, \
                    patch.object(nodes, "submit_image_task", return_value="source") as submit, \
                    patch.object(nodes, "poll_image_task", return_value={"data": {"result_url": URL}}), \
                    patch.object(nodes, "download_image", return_value=image) as download:
                result = cls().execute(prompt="Robot", image1=image, api_config=CONFIG, seed=42)["result"]
            self.assertIs(result[0], image)
            self.assertEqual(result[1:3], (URL, "source"))
            upload.assert_called_once()
            download.assert_called_once()
            if cls is nodes.MuseImage:
                self.assertNotIn("seed", submit.call_args.args[0])
            else:
                self.assertEqual(submit.call_args.args[0]["seed"], 42)

    def test_video_legacy_route_download_and_fixed_fields(self):
        with patch.object(nodes, "submit_legacy_video_task", return_value="source") as submit, \
                patch.object(nodes, "poll_legacy_video_task", return_value={"data": {"result_url": URL}}), \
                patch.object(nodes, "download_video", return_value="video") as download:
            result = nodes.MuseVideo().execute(prompt="Robot", api_config=CONFIG, seed=42)["result"]
        self.assertEqual(result[:3], ("video", URL, "source"))
        self.assertEqual(submit.call_args.args[0], {"model": preview_models.MUSE_VIDEO_MODEL,
            "prompt": "Robot", "n": 1, "size": "auto", "duration": 10, "resolution": "720p", "audio": True})
        download.assert_called_once()

    def test_flux_adapter_native_seed_and_exact_request_whitelists(self):
        image = torch.zeros((1, 8, 8, 3))
        for model in nodes.flux3_variants.MODELS:
            kwargs = {"model": model, "prompt": "Robot", "seed": 42, "steps": 4, "output_format": "png"}
            if model.endswith("-i2i"):
                kwargs["image1"] = image
            with patch.object(nodes, "upload_media", return_value=URL), \
                    patch.object(nodes, "submit_image_task", return_value="source") as submit, \
                    patch.object(nodes, "poll_image_task", return_value={"data": {"result_url": URL}}), \
                    patch.object(nodes, "download_image", return_value=image):
                nodes.Flux3ImageVariants().execute(api_config=CONFIG, **kwargs)
            payload = submit.call_args.args[0]
            self.assertNotIn("n", payload)
            if "-klein-" in model:
                self.assertEqual(payload["seed"], 42)
                self.assertEqual(payload["metadata"], {"steps": 4})
                self.assertEqual(payload["output_format"], "png")
                self.assertNotIn("grounding", payload)
            else:
                self.assertNotIn("seed", payload)
                self.assertNotIn("metadata", payload)
                self.assertNotIn("output_format", payload)

    def test_flux_file_limit_is_checked_before_uploading_any_reference(self):
        image = torch.zeros((1, 1, 1, 3))
        with patch.object(preview_models, "image_to_png_bytes", side_effect=[b"png", b"a" * (10 * 1024 * 1024 + 1)]), \
                patch.object(nodes, "upload_media") as upload:
            with self.assertRaisesRegex(client.SeedanceAPIError, "size limit"):
                nodes.Flux3ImageVariants().execute(model="flux-3-image-i2i", prompt="Robot",
                    image1=image, image2=image, api_config=CONFIG)
            upload.assert_not_called()

    def test_skip_error_preserves_all_outputs(self):
        for key in KEYS:
            cls = nodes.NODE_CLASS_MAPPINGS[key]
            with patch.object(cls, "_execute_inner", side_effect=RuntimeError("offline failure")), \
                    patch.object(nodes, "make_error_video", return_value="video"), \
                    patch.object(nodes, "make_error_image", return_value="image"):
                with self.assertRaises(RuntimeError):
                    cls().execute()
                result = cls().execute(skip_error=True)["result"]
                self.assertEqual(len(result), 4)
                self.assertEqual(result[1:3], ("", ""))

    def test_concurrent_one_failure_does_not_cancel_sibling(self):
        wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS["SeedanceConcurrent_Muse_Image_Submit"]
        with patch.object(nodes.MuseImage, "_execute_inner", return_value={"result": (torch.zeros(1, 8, 8, 3), "", "", "")}), \
                patch.object(concurrent_nodes, "make_error_image", return_value=torch.ones(1, 8, 8, 3)):
            good = wrapper().submit(prompt="Robot")[0]
            bad = wrapper().submit(prompt="", skip_error=True)[0]
            result = concurrent_nodes.SeedanceConcurrentImageAwait().wait_all(future_1=good, future_2=bad)
        self.assertEqual(json.loads(result[-1])["failed"], 1)
        self.assertFalse(good.cancel_event.is_set())

    def test_all_eleven_workflows_have_valid_links_and_blank_credentials(self):
        files = [p for p in (ROOT / "examples").glob("*.json")
                 if p.name.startswith(("HY35Preview", "MuseImage", "MuseVideo", "flux-3-image-"))]
        self.assertEqual(len(files), 11)
        found = set()
        for file in files:
            source = file.read_text(encoding="utf-8")
            workflow = json.loads(source)
            by_id = {item["id"]: item for item in workflow["nodes"]}
            self.assertEqual(by_id[1]["widgets_values"][1], "")
            for item in workflow["nodes"]:
                if item["type"] in KEYS:
                    found.add(item["type"])
                    self.assertIn("fixed", item["widgets_values"])
            for edge, origin, origin_slot, target, target_slot, kind in workflow["links"]:
                self.assertIn(edge, by_id[origin]["outputs"][origin_slot]["links"])
                self.assertEqual(by_id[target]["inputs"][target_slot]["link"], edge)
                self.assertEqual(by_id[target]["inputs"][target_slot]["type"], kind)
            self.assertNotRegex(source, r"sk-[A-Za-z0-9]{12,}|task_[A-Za-z0-9]{12,}|X-Amz-Signature")
        self.assertEqual(found, set(KEYS))


if __name__ == "__main__":
    unittest.main()
