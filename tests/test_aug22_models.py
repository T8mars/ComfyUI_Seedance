import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT.parent))

from ComfyUI_Seedance import concurrent_nodes, nodes
from ComfyUI_Seedance.core import client, geometry


class OmniFlashLowpriceTests(unittest.TestCase):
    def test_mode_payloads_match_the_documented_contract(self):
        node = nodes.ZhenzhenVideoGOmniFlashLowprice()
        common = {
            "mode": "text",
            "prompt": "a paper airplane glides across a quiet studio",
            "seconds": "4",
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "nsfw_check": False,
        }
        text_payload = node.build_payload(common, {})
        self.assertEqual(text_payload, {
            "model": nodes.ZHENZHEN_VIDEO_G_OMNI_FLASH_LOWPRICE_MODEL,
            "prompt": common["prompt"],
            "seconds": "4",
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "nsfw_check": False,
        })

        frame = node.build_payload({**common, "mode": "frame"}, {"images": ["front"]})
        self.assertEqual(frame["generation_type"], "frame")
        self.assertEqual(frame["images"], ["front"])

        reference = node.build_payload(
            {**common, "mode": "reference_images"},
            {"images": ["one", "two", "three"]},
        )
        self.assertEqual(reference["generation_type"], "reference")
        self.assertEqual(reference["images"], ["one", "two", "three"])

        video = node.build_payload(
            {**common, "mode": "reference_video"},
            {"video_url": "https://example.invalid/reference.mp4"},
        )
        self.assertNotIn("seconds", video)
        self.assertEqual(video["metadata"], {
            "video_url": "https://example.invalid/reference.mp4",
        })

    def test_strict_mode_validation_rejects_ambiguous_media(self):
        base = {
            "prompt": "a valid prompt",
            "seconds": "6",
            "resolution": "720p",
            "aspect_ratio": "16:9",
        }
        self.assertIs(
            nodes.ZhenzhenVideoGOmniFlashLowprice.VALIDATE_INPUTS(
                **base, mode="frame", image1=object(), strict=True
            ),
            True,
        )
        self.assertIn(
            "image1",
            nodes.ZhenzhenVideoGOmniFlashLowprice.VALIDATE_INPUTS(
                **base, mode="frame", image2=object(), strict=True
            ),
        )
        self.assertIn(
            "exactly one",
            nodes.ZhenzhenVideoGOmniFlashLowprice.VALIDATE_INPUTS(
                **base,
                mode="reference_video",
                input_video=object(),
                video_url="https://example.invalid/reference.mp4",
                strict=True,
            ),
        )


class Hunyuan3DTests(unittest.TestCase):
    def test_models_and_documented_limits(self):
        self.assertEqual(len(nodes.HUNYUAN3D_MODELS), 2)
        self.assertIn(
            "face_count",
            nodes.Hunyuan3DV31.VALIDATE_INPUTS(
                model=nodes.HUNYUAN3D_TEXT_MODEL,
                prompt="teapot",
                face_count=9999,
                generate_type="Normal",
                strict=True,
            ),
        )
        self.assertIn(
            "prompt is required",
            nodes.Hunyuan3DV31.VALIDATE_INPUTS(
                model=nodes.HUNYUAN3D_IMAGE_MODEL,
                prompt="",
                face_count=10000,
                generate_type="Geometry",
                image1=object(),
                strict=True,
            ),
        )
        self.assertIs(
            nodes.Hunyuan3DV31.VALIDATE_INPUTS(
                model=nodes.HUNYUAN3D_IMAGE_MODEL,
                prompt="a black cat bust",
                face_count=10000,
                generate_type="Geometry",
                image1=object(),
                strict=True,
            ),
            True,
        )
        self.assertIn(
            "contiguously",
            nodes.Hunyuan3DV31.VALIDATE_INPUTS(
                model=nodes.HUNYUAN3D_IMAGE_MODEL,
                prompt="a black cat bust",
                face_count=10000,
                generate_type="Normal",
                image2=object(),
                strict=True,
            ),
        )

    def test_text_node_executes_to_file3d(self):
        node = nodes.Hunyuan3DV31()
        final = {"data": {"status": "SUCCESS", "result_url": "https://example.invalid/a.glb"}}
        marker = object()
        with (
            patch.object(nodes, "get_config", return_value={"base_url": "x", "api_key": "sk-test"}),
            patch.object(nodes, "submit_3d_task", return_value="task-test") as submit,
            patch.object(nodes, "poll_3d_task", return_value=final),
            patch.object(nodes, "download_glb", return_value="C:/temp/a.glb"),
            patch.object(nodes, "file3d_from_path", return_value=marker),
        ):
            result = node._execute_inner(
                model=nodes.HUNYUAN3D_TEXT_MODEL,
                prompt="a ceramic teapot",
                face_count=10000,
                enable_pbr=False,
                generate_type="Normal",
            )
        payload = submit.call_args.args[0]
        self.assertEqual(payload["model"], nodes.HUNYUAN3D_TEXT_MODEL)
        self.assertEqual(payload["face_count"], 10000)
        self.assertNotIn("images", payload)
        self.assertIs(result["result"][0], marker)
        self.assertEqual(result["result"][2], "C:/temp/a.glb")

    def test_glb_validation_and_fallback_file_contract(self):
        data = geometry.minimal_glb_bytes("test")
        self.assertEqual(data[:4], b"glTF")
        self.assertEqual(struct.unpack("<I", data[8:12])[0], len(data))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.glb"
            path.write_bytes(data)
            model = geometry.file3d_from_path(str(path))
            self.assertEqual(model.format, "glb")
            self.assertEqual(model.get_bytes()[:4], b"glTF")


class GKV2ToolTests(unittest.TestCase):
    def test_segment_extracts_structured_result(self):
        node = nodes.ZhenzhenImageGKV2Segment()
        final = {
            "data": {
                "status": "SUCCESS",
                "content": {
                    "result": {"image_id": "image-test", "objects": [{"label": "bag"}]},
                },
            },
        }
        with (
            patch.object(nodes, "get_config", return_value={"base_url": "x", "api_key": "sk-test"}),
            patch.object(nodes, "submit_image_task", return_value="task-test") as submit,
            patch.object(nodes, "poll_image_task", return_value=final),
        ):
            output = node.execute("source-test", True)
        self.assertEqual(submit.call_args.args[0], {
            "model": nodes.ZHENZHEN_IMAGE_GK_V2_SEGMENT_MODEL,
            "operation": "segment",
            "source_task_id": "source-test",
            "include_mask_rle": True,
        })
        self.assertEqual(output["result"][0], "image-test")
        self.assertEqual(json.loads(output["result"][1]), [{"label": "bag"}])

    def test_region_selection_types_and_payload(self):
        node = nodes.ZhenzhenImageGKV2RegionEdit()
        self.assertEqual(node._parse_selection("object_indices", "[0, 2]"), [0, 2])
        self.assertEqual(node._parse_selection("boxes", "[[1, 2, 3, 4]]"), [[1, 2, 3, 4]])
        self.assertEqual(node._parse_selection("selection_regions", '[{"x": 1}]'), [{"x": 1}])
        with self.assertRaisesRegex(nodes.SeedanceAPIError, "non-negative"):
            node._parse_selection("object_indices", '["0"]')

        final = {"data": {"status": "SUCCESS", "result_url": "https://example.invalid/edit.png"}}
        image_marker = object()
        with (
            patch.object(nodes, "get_config", return_value={"base_url": "x", "api_key": "sk-test"}),
            patch.object(nodes, "submit_image_task", return_value="task-test") as submit,
            patch.object(nodes, "poll_image_task", return_value=final),
            patch.object(nodes, "download_image", return_value=image_marker),
        ):
            output = node._execute_inner(
                image_id="image-test",
                prompt="replace the selected object",
                selection_mode="object_indices",
                selection_json="[0]",
            )
        payload = submit.call_args.args[0]
        self.assertEqual(payload["object_indices"], [0])
        self.assertNotIn("boxes", payload)
        self.assertIs(output["result"][0], image_marker)

    def test_client_extractors_cover_documented_nested_shapes(self):
        segment = {"data": {"content": {"result": {"image_id": "x", "objects": []}}}}
        self.assertEqual(client.extract_image_operation_result(segment)["image_id"], "x")
        nested_3d = {"data": {"data": {"content": {"file_url": "https://example.invalid/model.glb"}}}}
        self.assertEqual(client.extract_3d_url(nested_3d), "https://example.invalid/model.glb")
        observed_3d = {
            "data": {
                "result_url": "https://example.invalid/package.zip",
                "data": {
                    "content": {
                        "file_url": "https://example.invalid/package.zip",
                        "file_urls": [
                            "https://example.invalid/package.zip",
                            "https://example.invalid/model.glb",
                        ],
                    },
                },
            },
        }
        self.assertEqual(client.extract_3d_url(observed_3d), "https://example.invalid/model.glb")


class RegistrationAndFrontendTests(unittest.TestCase):
    def test_new_nodes_and_concurrent_wrappers_are_registered(self):
        expected = {
            "Zhenzhen_Video_G_Omni_Flash_Lowprice",
            "Hunyuan3D_V3_1",
            "Zhenzhen_Image_GK_V2_Segment",
            "Zhenzhen_Image_GK_V2_Region_Edit",
        }
        self.assertTrue(expected.issubset(nodes.NODE_CLASS_MAPPINGS))
        self.assertIn(
            "SeedanceConcurrent_Zhenzhen_Video_G_Omni_Flash_Lowprice_Submit",
            concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS,
        )
        self.assertIn(
            "SeedanceConcurrent_Zhenzhen_Image_GK_V2_Region_Edit_Submit",
            concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS,
        )

    def test_frontend_uses_shared_dynamic_helpers(self):
        omni = (PLUGIN_ROOT / "web" / "js" / "omni_hunyuan_ui.js").read_text(encoding="utf-8")
        region = (PLUGIN_ROOT / "web" / "js" / "gk_v2_tools_ui.js").read_text(encoding="utf-8")
        self.assertIn('from "./dynamic_widget_ui.js"', omni)
        self.assertIn("setSeedanceInputVisible", omni)
        self.assertIn("setSeedanceWidgetVisible", omni)
        self.assertIn("originalSeedanceNodeName(nodeData.name)", omni)
        self.assertIn('from "./dynamic_widget_ui.js"', region)
        self.assertIn("MODE_DEFAULTS", region)

    def test_all_new_workflows_are_safe_and_complete(self):
        filenames = {
            "zhenzhen-video-g-omni-flash-lowprice文生视频.json",
            "zhenzhen-video-g-omni-flash-lowprice首帧生视频.json",
            "zhenzhen-video-g-omni-flash-lowprice三图参考生视频.json",
            "zhenzhen-video-g-omni-flash-lowprice参考视频生成.json",
            "hunyuan3d-v3.1-text-to-3d文生3D.json",
            "hunyuan3d-v3.1-image-to-3d图生3D.json",
            "zhenzhen-image-gk-v2-segment智能分割.json",
            "zhenzhen-image-gk-v2-region-edit分割区域编辑.json",
        }
        for filename in filenames:
            with self.subTest(workflow=filename):
                source = (PLUGIN_ROOT / "examples" / filename).read_text(encoding="utf-8")
                workflow = json.loads(source)
                self.assertNotIn("sk-", source)
                config = next(item for item in workflow["nodes"] if item["type"] == "Seedance_Config")
                self.assertEqual(config["widgets_values"][1], "")
                link_ids = {link[0] for link in workflow["links"]}
                nodes_by_id = {item["id"]: item for item in workflow["nodes"]}
                for item in workflow["nodes"]:
                    for item_output in item.get("outputs", []):
                        for link_id in item_output.get("links") or []:
                            self.assertIn(link_id, link_ids)
                for link_id, origin_id, origin_slot, target_id, target_slot, _ in workflow["links"]:
                    self.assertIn(
                        link_id,
                        nodes_by_id[origin_id]["outputs"][origin_slot].get("links") or [],
                    )
                    self.assertEqual(
                        nodes_by_id[target_id]["inputs"][target_slot].get("link"),
                        link_id,
                    )

        for filename in (
            "hunyuan3d-v3.1-text-to-3d文生3D.json",
            "hunyuan3d-v3.1-image-to-3d图生3D.json",
        ):
            workflow = json.loads((PLUGIN_ROOT / "examples" / filename).read_text(encoding="utf-8"))
            types = {item["type"] for item in workflow["nodes"]}
            self.assertIn("Preview3D", types)
            self.assertIn("SaveGLB", types)

        region_workflow = json.loads(
            (PLUGIN_ROOT / "examples" / "zhenzhen-image-gk-v2-region-edit分割区域编辑.json").read_text(encoding="utf-8")
        )
        region_types = {item["type"] for item in region_workflow["nodes"]}
        self.assertTrue({
            "Zhenzhen_Image_GK_V2",
            "Zhenzhen_Image_GK_V2_Segment",
            "Zhenzhen_Image_GK_V2_Region_Edit",
            "SaveImage",
        }.issubset(region_types))


if __name__ == "__main__":
    unittest.main()
