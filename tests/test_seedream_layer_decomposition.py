import io
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from PIL import Image


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT.parent))

try:
    from ComfyUI_Seedance import nodes
    from ComfyUI_Seedance.core import client
except ModuleNotFoundError:
    spec = importlib.util.spec_from_file_location(
        "ComfyUI_Seedance",
        PACKAGE_ROOT / "__init__.py",
        submodule_search_locations=[str(PACKAGE_ROOT)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules["ComfyUI_Seedance"] = package
    spec.loader.exec_module(package)
    from ComfyUI_Seedance import nodes
    from ComfyUI_Seedance.core import client


CONFIG = {
    "base_url": "https://example.test",
    "api_key": "test-key",
    "timeout": 60,
    "poll_interval": 0,
    "max_poll_time": 60,
}


class ByteResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None

    def close(self):
        return None


class ByteSession:
    def __init__(self, content):
        self.content = content

    def get(self, *args, **kwargs):
        return ByteResponse(self.content)


class SeedreamLayerDecompositionTests(unittest.TestCase):
    def test_node_contract_uses_comfyui_lists_for_different_sized_layers(self):
        self.assertEqual(
            nodes.SeedreamV5ProLayerDecomposition.RETURN_TYPES,
            ("IMAGE", "MASK", "STRING", "INT", "STRING", "STRING"),
        )
        self.assertEqual(
            nodes.SeedreamV5ProLayerDecomposition.OUTPUT_IS_LIST,
            (True, True, False, False, False, False),
        )
        self.assertIs(
            nodes.NODE_CLASS_MAPPINGS["Seedream_V5_Pro_Layer_Decomposition"],
            nodes.SeedreamV5ProLayerDecomposition,
        )
        model_spec = nodes.SeedreamV5ProLayerDecomposition.INPUT_TYPES()["optional"]["model"]
        self.assertEqual(
            model_spec[0],
            [
                "seedream-v5-pro-layer-decomposition",
                "dola-seedream-5.0-pro-layer-decomposition",
            ],
        )
        self.assertEqual(model_spec[1]["default"], "seedream-v5-pro-layer-decomposition")

    def test_payload_matches_documented_layer_contract(self):
        node = nodes.SeedreamV5ProLayerDecomposition()
        payload = node._build_payload(
            "https://cdn.test/source.png",
            "",
            "auto",
            "png",
        )

        self.assertEqual(
            payload,
            {
                "model": "seedream-v5-pro-layer-decomposition",
                "images": ["https://cdn.test/source.png"],
                "metadata": {"resolution": "auto", "output_format": "png"},
            },
        )
        prompted = node._build_payload(
            "https://cdn.test/source.png",
            "separate foreground text",
            "1.5k",
            "jpeg",
        )
        self.assertEqual(prompted["prompt"], "separate foreground text")
        dola = node._build_payload(
            "https://cdn.test/source.png",
            "",
            "auto",
            "png",
            "dola-seedream-5.0-pro-layer-decomposition",
        )
        self.assertEqual(dola["model"], "dola-seedream-5.0-pro-layer-decomposition")

    def test_validation_accepts_optional_prompt_and_documented_resolutions(self):
        for resolution in ("auto", "1k", "1.5k", "2k"):
            with self.subTest(resolution=resolution):
                self.assertIs(
                    nodes.SeedreamV5ProLayerDecomposition.VALIDATE_INPUTS(
                        image=torch.zeros((1, 4, 4, 3)),
                        prompt="",
                        resolution=resolution,
                        output_format="png",
                        strict=True,
                    ),
                    True,
                )
        self.assertIsNot(
            nodes.SeedreamV5ProLayerDecomposition.VALIDATE_INPUTS(
                image=None,
                prompt="",
                resolution="auto",
                output_format="png",
                strict=True,
            ),
            True,
        )
        self.assertIsNot(
            nodes.SeedreamV5ProLayerDecomposition.VALIDATE_INPUTS(
                image=torch.zeros((1, 4, 4, 3)),
                prompt="x" * 2001,
                resolution="auto",
                output_format="png",
                strict=True,
            ),
            True,
        )
        self.assertIsNot(
            nodes.SeedreamV5ProLayerDecomposition.VALIDATE_INPUTS(
                image=torch.zeros((2, 4, 4, 3)),
                prompt="",
                resolution="auto",
                output_format="png",
                strict=True,
            ),
            True,
        )
        self.assertIsNot(
            nodes.SeedreamV5ProLayerDecomposition.VALIDATE_INPUTS(
                image=torch.zeros((1, 4, 4, 3)),
                prompt="",
                resolution="auto",
                output_format="png",
                model="not-a-layer-model",
                strict=True,
            ),
            True,
        )

    def test_extract_image_urls_preserves_documented_array_order(self):
        response = {
            "data": {
                "status": "SUCCESS",
                "result_url": "https://cdn.test/summary.png",
                "data": {
                    "content": {
                        "image_url": "https://cdn.test/base.png",
                        "image_urls": [
                            "https://cdn.test/base.png",
                            "https://cdn.test/layer-1.png",
                            "https://cdn.test/layer-1.png",
                            "https://cdn.test/layer-2.png",
                        ],
                    }
                },
            }
        }

        self.assertEqual(
            client.extract_image_urls(response),
            [
                "https://cdn.test/base.png",
                "https://cdn.test/layer-1.png",
                "https://cdn.test/layer-1.png",
                "https://cdn.test/layer-2.png",
            ],
        )

    def test_download_image_with_mask_preserves_transparency_as_mask(self):
        source = Image.new("RGBA", (3, 2), (255, 0, 0, 255))
        source.putpixel((1, 0), (0, 255, 0, 0))
        buffer = io.BytesIO()
        source.save(buffer, format="PNG")

        with patch.object(
            client,
            "_session",
            return_value=ByteSession(buffer.getvalue()),
        ):
            image, mask = client.download_image_with_mask(
                "https://cdn.test/layer.png"
            )

        self.assertEqual(tuple(image.shape), (1, 2, 3, 3))
        self.assertEqual(tuple(mask.shape), (1, 2, 3))
        self.assertEqual(float(mask[0, 0, 0]), 0.0)
        self.assertEqual(float(mask[0, 0, 1]), 1.0)

    def test_execute_downloads_every_returned_image_in_order(self):
        node = nodes.SeedreamV5ProLayerDecomposition()
        urls = [
            "https://cdn.test/base.png",
            "https://cdn.test/layer-1.png",
            "https://cdn.test/layer-2.png",
        ]
        final_response = {
            "data": {
                "status": "SUCCESS",
                "data": {"content": {"image_urls": urls}},
            }
        }

        def make_result(url, **kwargs):
            index = urls.index(url)
            image = torch.full((1, index + 2, index + 3, 3), float(index))
            mask = torch.full((1, index + 2, index + 3), float(index) / 2)
            return image, mask

        with patch.object(nodes, "get_config", return_value=CONFIG), patch.object(
            nodes, "upload_media", return_value="https://cdn.test/source.png"
        ) as upload, patch.object(
            nodes, "submit_image_task", return_value="image-task"
        ) as submit, patch.object(
            nodes, "poll_image_task", return_value=final_response
        ), patch.object(
            nodes, "download_image_with_mask", side_effect=make_result
        ) as download:
            output = node.execute(
                image=torch.zeros((1, 8, 8, 3)),
                prompt="",
                resolution="auto",
                output_format="png",
            )

        upload.assert_called_once()
        self.assertEqual(submit.call_args.args[0]["images"], ["https://cdn.test/source.png"])
        self.assertNotIn("prompt", submit.call_args.args[0])
        self.assertEqual([call.args[0] for call in download.call_args_list], urls)
        images, masks, urls_json, count, task_id, response = output["result"]
        self.assertEqual(len(images), 3)
        self.assertEqual(len(masks), 3)
        self.assertEqual([tuple(item.shape) for item in images], [
            (1, 2, 3, 3),
            (1, 3, 4, 3),
            (1, 4, 5, 3),
        ])
        self.assertEqual(json.loads(urls_json), urls)
        self.assertEqual(count, 3)
        self.assertEqual(task_id, "image-task")
        self.assertEqual(json.loads(response), final_response)

    def test_execute_rejects_source_larger_than_documented_limit_before_upload(self):
        node = nodes.SeedreamV5ProLayerDecomposition()
        with patch.object(nodes, "get_config", return_value=CONFIG), patch.object(
            nodes, "image_to_png_bytes", return_value=b"oversized"
        ), patch.object(
            nodes, "MAX_SEEDREAM_LAYER_SOURCE_BYTES", 4
        ), patch.object(
            nodes, "upload_media"
        ) as upload:
            with self.assertRaisesRegex(client.SeedanceAPIError, "30 MB"):
                node.execute(
                    image=torch.zeros((1, 8, 8, 3)),
                    prompt="",
                    resolution="auto",
                    output_format="png",
                )

        upload.assert_not_called()

    def test_skip_error_returns_valid_list_outputs(self):
        node = nodes.SeedreamV5ProLayerDecomposition()
        with patch.object(
            node,
            "_execute_inner",
            side_effect=RuntimeError("forced layer failure"),
        ):
            output = node.execute(skip_error=True)

        images, masks, urls_json, count, task_id, response = output["result"]
        self.assertEqual(len(images), 1)
        self.assertEqual(tuple(images[0].shape), (1, 512, 512, 3))
        self.assertEqual(len(masks), 1)
        self.assertEqual(tuple(masks[0].shape), (1, 512, 512))
        self.assertEqual(urls_json, "[]")
        self.assertEqual(count, 0)
        self.assertEqual(task_id, "")
        self.assertIn("forced layer failure", json.loads(response)["error"])

    def test_example_workflows_are_safe_and_save_all_list_items(self):
        cases = {
            "seedream-v5-pro图层拆分.json": "seedream-v5-pro-layer-decomposition",
            "dola-seedream-5.0-pro图层拆分.json": "dola-seedream-5.0-pro-layer-decomposition",
        }
        for filename, expected_model in cases.items():
            with self.subTest(filename=filename):
                path = PACKAGE_ROOT / "examples" / filename
                source = path.read_text(encoding="utf-8")
                workflow = json.loads(source)
                node_types = {node["type"] for node in workflow["nodes"]}
                self.assertIn("Seedream_V5_Pro_Layer_Decomposition", node_types)
                self.assertIn("LoadImage", node_types)
                self.assertIn("SaveImage", node_types)
                self.assertNotRegex(source, r"sk-[A-Za-z0-9]{12,}")
                config_node = next(
                    node for node in workflow["nodes"] if node["type"] == "Seedance_Config"
                )
                self.assertEqual(config_node["widgets_values"][1], "")
                layer_node = next(
                    node
                    for node in workflow["nodes"]
                    if node["type"] == "Seedream_V5_Pro_Layer_Decomposition"
                )
                self.assertEqual(layer_node["widgets_values"][6], expected_model)
                join_link = next(
                    link
                    for link in workflow["links"]
                    if link[1] == layer_node["id"] and link[2] == 0
                )
                join_node = next(
                    node for node in workflow["nodes"] if node["id"] == join_link[3]
                )
                self.assertEqual(join_node["type"], "JoinImageWithAlpha")
                save_link = next(
                    link
                    for link in workflow["links"]
                    if link[1] == join_node["id"] and link[2] == 0
                )
                save_node = next(
                    node for node in workflow["nodes"] if node["id"] == save_link[3]
                )
                self.assertEqual(save_node["type"], "SaveImage")


if __name__ == "__main__":
    unittest.main()
