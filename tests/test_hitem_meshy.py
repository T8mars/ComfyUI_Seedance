import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

import requests
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import nodes, concurrent_nodes
from ComfyUI_Seedance.core import client, geometry, hitem_meshy as contracts, preview_models

CONFIG = {"base_url": "https://api.seedance.nz", "api_key": "sk-test"}
URL = "https://example.com/model.glb"
CLASSES = (nodes.Hitem3DV2, nodes.Hitem3DPortrait21, nodes.Meshy6Global)
KEYS = ("Hitem3D_V2", "Hitem3D_Portrait_V2_1", "Meshy_6_Global")


class HitemMeshyTests(unittest.TestCase):
    def test_independent_nodes_native_types_and_cache_seeds(self):
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Hunyuan3D_V3_1"], nodes.Hunyuan3DV31)
        for key, cls in zip(KEYS, CLASSES):
            self.assertIs(nodes.NODE_CLASS_MAPPINGS[key], cls)
            self.assertEqual(cls.RETURN_TYPES, ("FILE_3D",) + ("STRING",) * 4)
            self.assertEqual(cls.RETURN_NAMES, ("model_3d", "model_url", "local_path", "task_id", "response"))
            schema = cls.INPUT_TYPES()
            self.assertFalse(schema["optional"]["skip_error"][1]["default"])
            self.assertTrue(schema["optional"]["seed"][1]["control_after_generate"])
            self.assertTrue(cls.SEEDANCE_CACHE_ONLY_SEED)
            self.assertFalse(hasattr(cls, "IS_CHANGED"))
            self.assertNotIn(f"SeedanceConcurrent_{key}_Submit", concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS)

    def test_only_five_currently_documented_available_models(self):
        self.assertEqual(len(contracts.HITEM_MODELS), 2)
        self.assertEqual(len(contracts.PORTRAIT_MODELS), 2)
        self.assertEqual(contracts.MESHY_MODELS, ["meshy-6-global-image-to-3d"])
        self.assertIsNot(contracts.validate("meshy", {"model": "meshy-6-global-text-to-3d"}), True)

    def test_hitem_payload_exact_fields_and_no_hunyuan_options(self):
        for family in ("hitem", "portrait"):
            for model in contracts.models(family):
                images = [URL] * (2 if "multi-image" in model else 1)
                kwargs = {"model": model, "request_type": "mesh", "face": 100000,
                          "resolution": "1536pro" if family == "portrait" else "1536",
                          "prompt": "ignore stale input", "face_count": 10000, "seed": 42, "enable_pbr": True}
                self.assertEqual(contracts.payload(family, kwargs, images), {
                    "model": model, "images": images, "request_type": "mesh", "face": 100000,
                    "resolution": kwargs["resolution"],
                })

    def test_meshy_optional_defaults_are_omitted_not_guessed(self):
        self.assertEqual(contracts.payload("meshy", {"seed": 42}, [URL]),
                         {"model": contracts.MESHY_MODELS[0], "images": [URL]})

    def test_meshy_explicit_fields_and_false_are_preserved(self):
        kwargs = {"topology": "quad", "target_polycount": 100, "symmetry_mode": "off",
                  "should_remesh": "false", "enable_pbr": "false", "ta_pose": "true", "should_texture": "false",
                  "face": 100000, "resolution": "1536", "request_type": "both", "prompt": "unused", "seed": 42}
        self.assertEqual(contracts.payload("meshy", kwargs, [URL]), {
            "model": contracts.MESHY_MODELS[0], "images": [URL], "topology": "quad", "target_polycount": 100,
            "symmetry_mode": "off", "should_remesh": False, "enable_pbr": False, "ta_pose": True, "should_texture": False})

    def test_hitem_enums_ranges_and_types(self):
        for face in (100000, 1000001, 2000000):
            self.assertIs(contracts.validate("hitem", {"face": face}), True)
        for kwargs in ({"face": 99999}, {"face": 2000001}, {"face": True}, {"face": 100000.0},
                       {"request_type": "texture"}, {"resolution": "768"}, {"model": "unknown"}):
            self.assertIsNot(contracts.validate("hitem", kwargs), True)
        self.assertIsNot(contracts.validate("portrait", {"resolution": "1536"}), True)
        self.assertIs(contracts.validate("portrait", {"resolution": "1536pro"}), True)

    def test_meshy_enum_numeric_and_boolean_boundaries(self):
        for count in (0, 100, 300000):
            self.assertIs(contracts.validate("meshy", {"target_polycount": count}), True)
        for kwargs in ({"topology": "mesh"}, {"symmetry_mode": "false"}, {"target_polycount": 99},
                       {"target_polycount": 300001}, {"target_polycount": True}, {"target_polycount": 100.0},
                       {"should_texture": False}, {"should_texture": "disabled"}):
            self.assertIsNot(contracts.validate("meshy", kwargs), True)

    def test_single_requires_exactly_first_image(self):
        for family in ("hitem", "portrait", "meshy"):
            self.assertIs(contracts.validate(family, {}, strict=False), True)
            self.assertIs(contracts.validate(family, {"image1": object()}, strict=True), True)
            for kwargs in ({}, {"image2": object()}, {"image1": object(), "image2": object()}, {"image5": object()}):
                self.assertIsNot(contracts.validate(family, kwargs, strict=True), True)

    def test_multiview_front_back_left_right_and_no_gaps(self):
        self.assertEqual(contracts.VIEWS, ["front", "back", "left", "right"])
        for family in ("hitem", "portrait"):
            model = contracts.models(family)[1]
            for count in (2, 3, 4):
                kwargs = {"model": model, **{f"image{i}": object() for i in range(1, count + 1)}}
                self.assertIs(contracts.validate(family, kwargs, strict=True), True)
            for kwargs in ({}, {"image1": object()}, {"image1": object(), "image3": object()},
                           {"image2": object(), "image3": object()}, {"image5": object()}):
                self.assertIsNot(contracts.validate(family, {"model": model, **kwargs}, strict=True), True)

    def test_invalid_options_and_batches_stop_before_any_upload(self):
        image = torch.zeros(1, 4, 4, 3)
        for cls in CLASSES:
            for kwargs in ({}, {"image1": torch.zeros(2, 4, 4, 3)},
                           {"image1": image, "image2": image}, {"image1": image, "model": "unknown"}):
                with self.subTest(cls=cls, keys=list(kwargs)), patch.object(nodes, "upload_media") as upload:
                    with self.assertRaises(client.SeedanceAPIError):
                        cls().execute(api_config=CONFIG, **kwargs)
                    upload.assert_not_called()

    def test_all_views_encode_before_first_upload(self):
        image = torch.zeros(1, 4, 4, 3)
        with patch.object(preview_models, "image_to_png_bytes", side_effect=[b"valid", ValueError("bad view")]), \
                patch.object(nodes, "upload_media") as upload:
            with self.assertRaisesRegex(ValueError, "bad view"):
                nodes.Hitem3DV2().execute(model=contracts.HITEM_MODELS[1], image1=image, image2=image, api_config=CONFIG)
            upload.assert_not_called()

    def test_execute_submits_polls_downloads_and_returns_native_file(self):
        image = torch.zeros(1, 4, 4, 3)
        final = {"data": {"status": "SUCCESS", "result_url": URL}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.glb"
            path.write_bytes(geometry.minimal_glb_bytes())
            for cls in CLASSES:
                with patch.object(nodes, "upload_media", return_value=URL), \
                        patch.object(nodes, "submit_3d_task", return_value="source") as submit, \
                        patch.object(nodes, "poll_3d_task", return_value=final), \
                        patch.object(nodes, "download_file", return_value=str(path)) as download:
                    result = cls().execute(image1=image, api_config=CONFIG, seed=42)["result"]
                self.assertEqual(len(result), 5)
                self.assertEqual(result[0].format, "glb")
                self.assertEqual(result[0].get_bytes()[:4], b"glTF")
                self.assertEqual(result[1:4], (URL, str(path), "source"))
                self.assertNotIn("seed", submit.call_args.args[0])
                download.assert_called_once()

    def test_multiview_upload_uses_fixed_view_names(self):
        image = torch.zeros(1, 4, 4, 3)
        with patch.object(nodes, "upload_media", return_value=URL) as upload, \
                patch.object(nodes, "submit_3d_task", side_effect=RuntimeError("stop before API")):
            with self.assertRaisesRegex(RuntimeError, "stop before API"):
                nodes.Hitem3DV2().execute(model=contracts.HITEM_MODELS[1], api_config=CONFIG,
                    image1=image, image2=image, image3=image, image4=image)
        self.assertEqual([call.args[1] for call in upload.call_args_list], ["front.png", "back.png", "left.png", "right.png"])

    def test_skip_error_keeps_native_placeholder_and_empty_identifiers(self):
        for cls in CLASSES:
            with patch.object(cls, "_execute_inner", side_effect=RuntimeError("offline failure")):
                with self.assertRaises(RuntimeError):
                    cls().execute()
                result = cls().execute(skip_error=True)["result"]
                self.assertEqual(len(result), 5)
                self.assertEqual(result[0].format, "glb")
                self.assertEqual(result[0].get_bytes()[:4], b"glTF")
                self.assertEqual(result[1:4], ("", "", ""))

    def test_glb_and_obj_are_recognized_by_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unknown.bin"
            path.write_bytes(geometry.minimal_glb_bytes())
            self.assertEqual(contracts.prepare_model(str(path)), (str(path), "glb"))
            obj = Path(directory) / "object.obj"
            obj.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
            self.assertEqual(contracts.prepare_model(str(obj)), (str(obj), "obj"))
            file_3d = geometry.file3d_from_path(str(obj), file_format="obj")
            self.assertEqual(file_3d.format, "obj")
            self.assertIn(b"v 0 0 0", file_3d.get_bytes())

    def test_html_fake_glb_truncation_and_invalid_json_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.glb"
            valid = geometry.minimal_glb_bytes()
            bad_json = struct.pack("<4sII", b"glTF", 2, 24) + struct.pack("<II", 4, 0x4E4F534A) + b"oops"
            bad_asset = json.dumps({"asset": []}).encode("utf-8")
            bad_asset += b" " * ((4 - len(bad_asset) % 4) % 4)
            bad_asset = struct.pack("<4sII", b"glTF", 2, 20 + len(bad_asset)) + struct.pack("<II", len(bad_asset), 0x4E4F534A) + bad_asset
            for data in (b"<html>oops</html>", valid[:-4], valid[:12], bad_json, bad_asset):
                path.write_bytes(data)
                with self.assertRaises(client.SeedanceAPIError):
                    contracts.prepare_model(str(path))

    def test_zip_uses_owned_filename_and_rejects_missing_or_bad_glb(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("../../outside.glb", geometry.minimal_glb_bytes())
            result, format_ = contracts.prepare_model(str(path))
            self.assertEqual(Path(result).parent, path.parent)
            self.assertEqual(Path(result).name, "result_model.glb")
            self.assertEqual(format_, "glb")
            Path(result).unlink()
            for filename, data in (("model.obj", b"obj"), ("bad.glb", b"not a glb")):
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr(filename, data)
                with self.assertRaises(client.SeedanceAPIError):
                    contracts.prepare_model(str(path))
                self.assertFalse(path.with_name("result_model.glb.part").exists())
                self.assertFalse(path.with_name("result_model.glb").exists())

    def test_ambiguous_creation_timeout_is_never_replayed(self):
        session = Mock(post=Mock(side_effect=requests.exceptions.ReadTimeout("response lost")))
        with patch.object(client, "_session", return_value=session):
            with self.assertRaisesRegex(RuntimeError, "not retried"):
                client.submit_3d_task({"model": contracts.HITEM_MODELS[0], "images": [URL]}, CONFIG)
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(session.post.call_args.args[0], "https://api.seedance.nz/v1/3d/generations")

    def test_ui_dynamic_views_without_removing_connected_sockets(self):
        executable = shutil.which("node")
        if not executable:
            self.skipTest("Node.js unavailable")
        result = subprocess.run([executable, str(ROOT / "tests" / "hitem_meshy_ui.mjs")], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_five_workflows_blank_keys_stable_views_and_native_preview_save(self):
        files = [file for file in (ROOT / "examples").glob("*.json") if file.name.startswith(("hitem3d-", "meshy-6-"))]
        self.assertEqual(len(files), 5)
        for file in files:
            source = file.read_text(encoding="utf-8")
            workflow = json.loads(source)
            by_id = {node["id"]: node for node in workflow["nodes"]}
            config = by_id[1]
            self.assertEqual(config["widgets_values"][1], "")
            generator = next(node for node in workflow["nodes"] if node["type"] in KEYS)
            self.assertEqual(generator["widgets_values"][-3:], [False, 0, "fixed"])
            self.assertEqual([item["name"] for item in generator["inputs"]],
                ["image1", "api_config"] if generator["type"] == KEYS[2] else ["image1", "image2", "image3", "image4", "api_config"])
            self.assertIn("Preview3D", {node["type"] for node in workflow["nodes"]})
            self.assertIn("SaveGLB", {node["type"] for node in workflow["nodes"]})
            for edge, origin, slot, target, target_slot, kind in workflow["links"]:
                self.assertIn(edge, by_id[origin]["outputs"][slot]["links"])
                self.assertEqual(by_id[target]["inputs"][target_slot]["link"], edge)
                self.assertEqual(by_id[target]["inputs"][target_slot]["type"], kind)
            self.assertNotRegex(source, r"sk-[A-Za-z0-9]{12,}|task_[A-Za-z0-9]{12,}|X-Amz-Signature")


if __name__ == "__main__":
    unittest.main()
