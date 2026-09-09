import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import torch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT.parent))

from ComfyUI_Seedance import concurrent_nodes, nodes
from ComfyUI_Seedance.core.client import SeedanceAPIError


CONFIG = {
    "base_url": "https://api.seedance.nz",
    "api_key": "sk-test",
    "poll_interval": 0,
    "max_poll_time": 30,
}


class ZhenzhenImageG25LowpriceTests(unittest.TestCase):
    def test_inputs_and_limits_match_documentation(self):
        inputs = nodes.ZhenzhenImageG25Lowprice.INPUT_TYPES()
        self.assertEqual(
            list(inputs["required"]),
            ["prompt", "resolution", "size", "nsfw_check"],
        )
        self.assertEqual(nodes.MAX_ZHENZHEN_IMAGE_G25_LOWPRICE_IMAGES, 15)
        self.assertEqual(inputs["required"]["size"][1]["default"], "16:9")
        self.assertEqual(inputs["required"]["resolution"][1]["default"], "1k")
        self.assertEqual(
            list(inputs["optional"]),
            [
                *(f"image{index}" for index in range(1, 16)),
                "api_config",
                "skip_error",
                "seed",
            ],
        )

    def test_payload_contains_only_documented_lowprice_fields(self):
        payload = nodes.ZhenzhenImageG25Lowprice._build_payload(
            "a quiet garden at sunrise",
            "2k",
            "3:2",
            True,
            ["https://cdn.test/reference.png"],
        )
        self.assertEqual(
            payload,
            {
                "model": "zhenzhen-image-g-v2.5-lowprice",
                "prompt": "a quiet garden at sunrise",
                "n": 1,
                "size": "3:2",
                "resolution": "2k",
                "nsfw_check": True,
                "images": ["https://cdn.test/reference.png"],
            },
        )
        for unsupported in (
            "quality",
            "output_format",
            "output_compression",
            "background",
            "moderation",
            "metadata",
        ):
            self.assertNotIn(unsupported, payload)

    def test_prompt_and_reference_limits_are_enforced(self):
        self.assertIsNot(
            nodes.ZhenzhenImageG25Lowprice.VALIDATE_INPUTS(
                prompt="x" * 5001,
                resolution="1k",
                size="1:1",
                strict=True,
            ),
            True,
        )
        with self.assertRaisesRegex(SeedanceAPIError, "at most 15"):
            nodes.ZhenzhenImageG25Lowprice._build_payload(
                "valid prompt",
                "1k",
                "1:1",
                False,
                [f"https://cdn.test/{index}.png" for index in range(16)],
            )


class ZhenzhenImageG25OfficialTests(unittest.TestCase):
    def _payload(self, **overrides):
        values = {
            "model": nodes.ZHENZHEN_IMAGE_G25_FLARE_MODEL,
            "prompt": "a polished product photograph",
            "size": "auto",
            "custom_size": "1024x1024",
            "resolution": "1k",
            "quality": "low",
            "n": 1,
            "output_format": "png",
            "output_compression": 90,
            "background": "auto",
            "moderation": "low",
            "images": [],
        }
        values.update(overrides)
        return nodes.ZhenzhenImageG25Official._build_payload(**values)

    def test_inputs_expose_both_models_and_sixteen_references(self):
        inputs = nodes.ZhenzhenImageG25Official.INPUT_TYPES()
        self.assertEqual(
            inputs["required"]["model"][0],
            [
                "zhenzhen-image-g-v2.5-flare",
                "zhenzhen-image-g-v2.5-sunburst",
            ],
        )
        self.assertEqual(nodes.MAX_ZHENZHEN_IMAGE_G25_OFFICIAL_IMAGES, 16)
        self.assertEqual(inputs["required"]["n"][1]["max"], 4)
        self.assertIn("custom", inputs["required"]["size"][0])
        self.assertIn("preserve_reference", inputs["required"]["size"][0])
        self.assertEqual(
            list(inputs["optional"])[-3:],
            ["api_config", "skip_error", "seed"],
        )

    def test_standard_payload_forwards_documented_controls(self):
        self.assertEqual(
            self._payload(),
            {
                "model": "zhenzhen-image-g-v2.5-flare",
                "prompt": "a polished product photograph",
                "n": 1,
                "quality": "low",
                "output_format": "png",
                "background": "auto",
                "moderation": "low",
                "resolution": "1k",
                "size": "auto",
            },
        )

    def test_preserve_reference_omits_size_and_keeps_resolution(self):
        payload = self._payload(
            model=nodes.ZHENZHEN_IMAGE_G25_SUNBURST_MODEL,
            size="preserve_reference",
            images=["https://cdn.test/reference.png"],
        )
        self.assertNotIn("size", payload)
        self.assertEqual(payload["resolution"], "1k")
        self.assertEqual(payload["images"], ["https://cdn.test/reference.png"])

    def test_custom_pixels_omit_resolution_and_compression_is_format_specific(self):
        payload = self._payload(
            size="custom",
            custom_size="1536X864",
            resolution="4k",
            output_format="webp",
            output_compression=72,
            background="transparent",
        )
        self.assertEqual(payload["size"], "1536x864")
        self.assertNotIn("resolution", payload)
        self.assertEqual(payload["output_compression"], 72)
        self.assertNotIn("output_compression", self._payload(output_format="png"))

    def test_invalid_custom_pixels_and_jpeg_transparency_are_rejected(self):
        invalid_sizes = ("1023x1024", "4000x1024", "3200x800", "512x512")
        for value in invalid_sizes:
            with self.subTest(value=value):
                with self.assertRaises(SeedanceAPIError):
                    self._payload(size="custom", custom_size=value)
        with self.assertRaisesRegex(SeedanceAPIError, "transparent background"):
            self._payload(output_format="jpeg", background="transparent")

    def test_multiple_downloaded_results_return_one_image_batch(self):
        final = {
            "code": "success",
            "data": {
                "status": "SUCCESS",
                "data": {
                    "content": {
                        "image_urls": [
                            "https://cdn.test/one.png",
                            "https://cdn.test/two.png",
                        ],
                    },
                },
            },
        }
        output_one = torch.zeros((1, 16, 24, 3), dtype=torch.float32)
        output_two = torch.ones((1, 16, 24, 3), dtype=torch.float32)
        node = nodes.ZhenzhenImageG25Official()
        with (
            patch.object(nodes, "get_config", return_value=CONFIG),
            patch.object(nodes, "submit_image_task", return_value="task-test") as submit,
            patch.object(nodes, "poll_image_task", return_value=final),
            patch.object(
                nodes,
                "download_image",
                side_effect=[output_one, output_two],
            ) as download,
        ):
            result = node.execute(
                model=nodes.ZHENZHEN_IMAGE_G25_FLARE_MODEL,
                prompt="two complementary poster concepts",
                size="1:1",
                custom_size="1024x1024",
                resolution="1k",
                quality="low",
                n=2,
                output_format="png",
                output_compression=90,
                background="opaque",
                moderation="low",
            )

        self.assertEqual(submit.call_args.args[0]["n"], 2)
        self.assertEqual(download.call_count, 2)
        self.assertEqual(tuple(result["result"][0].shape), (2, 16, 24, 3))

    def test_edit_uploads_connected_images_in_slot_order(self):
        source = torch.zeros((1, 16, 16, 3), dtype=torch.float32)
        output = torch.ones((1, 16, 16, 3), dtype=torch.float32)
        final = {
            "code": "success",
            "data": {
                "status": "SUCCESS",
                "result_url": "https://cdn.test/result.png",
            },
        }
        node = nodes.ZhenzhenImageG25Official()
        with (
            patch.object(nodes, "get_config", return_value=CONFIG),
            patch.object(
                nodes,
                "upload_media",
                side_effect=[
                    "https://cdn.test/reference-1.png",
                    "https://cdn.test/reference-3.png",
                ],
            ) as upload,
            patch.object(nodes, "submit_image_task", return_value="task-test") as submit,
            patch.object(nodes, "poll_image_task", return_value=final),
            patch.object(nodes, "download_image", return_value=output),
        ):
            result = node.execute(
                model=nodes.ZHENZHEN_IMAGE_G25_SUNBURST_MODEL,
                prompt="keep the subject and replace the background",
                size="preserve_reference",
                custom_size="1024x1024",
                resolution="1k",
                quality="low",
                n=1,
                output_format="png",
                output_compression=90,
                background="auto",
                moderation="low",
                image1=source,
                image3=source,
            )

        self.assertEqual(upload.call_count, 2)
        self.assertEqual(
            submit.call_args.args[0]["images"],
            [
                "https://cdn.test/reference-1.png",
                "https://cdn.test/reference-3.png",
            ],
        )
        self.assertIs(result["result"][0], output)


class ZhenzhenImageG25RegistrationTests(unittest.TestCase):
    def test_serial_and_concurrent_nodes_are_registered(self):
        expected = {
            "Zhenzhen_Image_G25_Lowprice": nodes.ZhenzhenImageG25Lowprice,
            "Zhenzhen_Image_G25_Official": nodes.ZhenzhenImageG25Official,
        }
        for key, node_class in expected.items():
            with self.subTest(node=key):
                self.assertIs(nodes.NODE_CLASS_MAPPINGS[key], node_class)
                wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
                    f"SeedanceConcurrent_{key}_Submit"
                ]
                self.assertEqual(wrapper.CONCURRENT_KIND, "image")
                self.assertEqual(wrapper.ORIGINAL_NODE_KEY, key)

    def test_six_safe_workflows_cover_generation_and_editing(self):
        expected = {
            "zhenzhen-image-g-v2.5-lowprice文生图.json": (
                "Zhenzhen_Image_G25_Lowprice",
                "zhenzhen-image-g-v2.5-lowprice",
                False,
            ),
            "zhenzhen-image-g-v2.5-lowprice图像编辑.json": (
                "Zhenzhen_Image_G25_Lowprice",
                "zhenzhen-image-g-v2.5-lowprice",
                True,
            ),
            "zhenzhen-image-g-v2.5-flare文生图.json": (
                "Zhenzhen_Image_G25_Official",
                "zhenzhen-image-g-v2.5-flare",
                False,
            ),
            "zhenzhen-image-g-v2.5-flare图像编辑.json": (
                "Zhenzhen_Image_G25_Official",
                "zhenzhen-image-g-v2.5-flare",
                True,
            ),
            "zhenzhen-image-g-v2.5-sunburst文生图.json": (
                "Zhenzhen_Image_G25_Official",
                "zhenzhen-image-g-v2.5-sunburst",
                False,
            ),
            "zhenzhen-image-g-v2.5-sunburst图像编辑.json": (
                "Zhenzhen_Image_G25_Official",
                "zhenzhen-image-g-v2.5-sunburst",
                True,
            ),
        }
        for filename, (node_type, model, is_edit) in expected.items():
            with self.subTest(workflow=filename):
                source = (PLUGIN_ROOT / "examples" / filename).read_text(
                    encoding="utf-8"
                )
                workflow = json.loads(source)
                config = next(
                    item for item in workflow["nodes"]
                    if item["type"] == "Seedance_Config"
                )
                node = next(
                    item for item in workflow["nodes"]
                    if item["type"] == node_type
                )
                self.assertEqual(config["widgets_values"], ["https://api.seedance.nz", ""])
                if node_type.endswith("Official"):
                    self.assertEqual(node["widgets_values"][0], model)
                self.assertNotRegex(source, r"sk-[A-Za-z0-9]{12,}")
                self.assertNotRegex(source, r"task[_-][A-Za-z0-9_-]{6,}")
                image_links = [
                    link for link in workflow["links"]
                    if link[3] == node["id"] and link[5] == "IMAGE"
                ]
                self.assertEqual(len(image_links), 1 if is_edit else 0)


if __name__ == "__main__":
    unittest.main()
