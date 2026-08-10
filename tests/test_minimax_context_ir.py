import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import torch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT.parent))

from ComfyUI_Seedance import concurrent_nodes, nodes
from ComfyUI_Seedance.core import client


CONFIG = {
    "base_url": "https://api.seedance.nz",
    "api_key": "sk-test",
    "poll_interval": 0,
    "max_poll_time": 30,
}
IMAGE = torch.zeros((1, 8, 8, 3), dtype=torch.float32)


class _Response:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data
        self.text = json.dumps(data)

    def json(self):
        return self._data


class MinimaxH3ContextIRContractTests(unittest.TestCase):
    def test_exact_documented_catalog_and_controls(self):
        self.assertEqual(nodes.MINMAX_H3_CONTEXT_IR_MODELS, [
            "minmax-h3-context-ir-text",
            "minmax-h3-context-ir-image",
            "minmax-h3-context-ir-multimodal",
        ])
        inputs = nodes.MinimaxH3ContextIR.INPUT_TYPES()
        self.assertEqual(inputs["required"]["seconds"][0], [
            str(value) for value in range(4, 16)
        ])
        self.assertEqual(inputs["required"]["ratio"][0], [
            "api_default", "adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16",
        ])
        self.assertEqual(
            [name for name in inputs["optional"] if name.startswith("image")],
            [f"image{index}" for index in range(1, 10)],
        )
        self.assertEqual(
            [name for name in inputs["optional"] if name.startswith("video")],
            ["video1", "video2", "video3"],
        )
        self.assertEqual(
            [name for name in inputs["optional"] if name.startswith("audio")],
            ["audio1", "audio2", "audio3"],
        )
        self.assertEqual(list(inputs["optional"])[-3:], ["api_config", "skip_error", "seed"])

    def test_strict_validation_is_model_aware(self):
        self.assertIn(
            "prompt is required",
            nodes.MinimaxH3ContextIR.VALIDATE_INPUTS(
                model=nodes.MINMAX_H3_CONTEXT_IR_TEXT_MODEL,
                prompt="",
                seconds="4",
                ratio="16:9",
                strict=True,
            ),
        )
        self.assertIn(
            "fixed documented ratio",
            nodes.MinimaxH3ContextIR.VALIDATE_INPUTS(
                model=nodes.MINMAX_H3_CONTEXT_IR_TEXT_MODEL,
                prompt="camera follows the subject",
                seconds="4",
                ratio="adaptive",
                strict=True,
            ),
        )
        self.assertIn(
            "image1 is required",
            nodes.MinimaxH3ContextIR.VALIDATE_INPUTS(
                model=nodes.MINMAX_H3_CONTEXT_IR_IMAGE_MODEL,
                prompt="animate the first frame",
                seconds="4",
                ratio="16:9",
                strict=True,
            ),
        )
        self.assertIn(
            "at least one",
            nodes.MinimaxH3ContextIR.VALIDATE_INPUTS(
                model=nodes.MINMAX_H3_CONTEXT_IR_MULTIMODAL_MODEL,
                prompt="combine all references",
                seconds="4",
                ratio="api_default",
                strict=True,
            ),
        )
        self.assertIs(
            nodes.MinimaxH3ContextIR.VALIDATE_INPUTS(
                model=nodes.MINMAX_H3_CONTEXT_IR_MULTIMODAL_MODEL,
                prompt="combine all references",
                seconds="15",
                ratio="adaptive",
                image1=IMAGE,
                video1=object(),
                audio1=object(),
                strict=True,
            ),
            True,
        )

    def test_payload_contract_for_all_three_modes(self):
        node = nodes.MinimaxH3ContextIR()
        common = {
            "prompt": "smooth cinematic camera movement",
            "seconds": "4",
            "ratio": "16:9",
        }
        text_payload = node.build_payload(
            {"model": nodes.MINMAX_H3_CONTEXT_IR_TEXT_MODEL, **common},
            {},
        )
        self.assertEqual(text_payload, {
            "model": "minmax-h3-context-ir-text",
            "prompt": common["prompt"],
            "seconds": "4",
            "metadata": {"ratio": "16:9"},
        })

        image_payload = node.build_payload(
            {
                "model": nodes.MINMAX_H3_CONTEXT_IR_IMAGE_MODEL,
                "image1": IMAGE,
                "image2": IMAGE,
                **common,
            },
            {"images": ["https://media.test/first.png", "https://media.test/last.png"]},
        )
        self.assertEqual(image_payload["images"], [
            "https://media.test/first.png", "https://media.test/last.png",
        ])
        self.assertNotIn("metadata", image_payload)

        multi_payload = node.build_payload(
            {
                "model": nodes.MINMAX_H3_CONTEXT_IR_MULTIMODAL_MODEL,
                "image1": IMAGE,
                "video1": object(),
                "audio1": object(),
                **common,
            },
            {
                "images": ["https://media.test/image.png"],
                "video_urls": ["https://media.test/video.mp4"],
                "audio_urls": ["https://media.test/audio.wav"],
            },
        )
        self.assertEqual(multi_payload["images"], ["https://media.test/image.png"])
        self.assertEqual(multi_payload["metadata"], {
            "ratio": "16:9",
            "video_urls": ["https://media.test/video.mp4"],
            "audio_url": ["https://media.test/audio.wav"],
        })

    def test_multimodal_collects_all_media_families_in_slot_order(self):
        node = nodes.MinimaxH3ContextIR()
        progress = []
        with (
            patch.object(nodes, "image_to_png_bytes", return_value=b"image"),
            patch.object(nodes, "video_to_bytes", return_value=(b"video", "mp4")),
            patch.object(nodes, "audio_to_wav_bytes", return_value=b"audio"),
            patch.object(
                nodes,
                "upload_media",
                side_effect=[
                    "https://media.test/image.png",
                    "https://media.test/video.mp4",
                    "https://media.test/audio.wav",
                ],
            ) as upload,
        ):
            media = node.collect_media(
                {
                    "model": nodes.MINMAX_H3_CONTEXT_IR_MULTIMODAL_MODEL,
                    "image1": IMAGE,
                    "video1": object(),
                    "audio1": object(),
                },
                CONFIG,
                progress.append,
            )

        self.assertEqual(upload.call_count, 3)
        self.assertEqual(media, {
            "images": ["https://media.test/image.png"],
            "video_urls": ["https://media.test/video.mp4"],
            "audio_urls": ["https://media.test/audio.wav"],
        })
        self.assertEqual(progress, [1 / 3, 2 / 3, 1.0])

    def test_execute_returns_documented_result_text(self):
        final = {
            "code": "success",
            "data": {"status": "SUCCESS", "result_text": "Enhanced prompt"},
        }
        node = nodes.MinimaxH3ContextIR()
        with (
            patch.object(nodes, "get_config", return_value=CONFIG),
            patch.object(node, "collect_media", return_value={}),
            patch.object(nodes, "submit_context_ir_task", return_value="task-test") as submit,
            patch.object(nodes, "poll_context_ir_task", return_value=final),
        ):
            result = node.execute(
                model=nodes.MINMAX_H3_CONTEXT_IR_TEXT_MODEL,
                prompt="A quiet garden at sunrise",
                seconds="4",
                ratio="16:9",
            )

        self.assertEqual(submit.call_args.args[0]["metadata"], {"ratio": "16:9"})
        self.assertEqual(result["result"][0], "Enhanced prompt")
        self.assertEqual(result["result"][1], "task-test")

    def test_skip_error_preserves_three_string_outputs(self):
        node = nodes.MinimaxH3ContextIR()
        with patch.object(node, "_execute_inner", side_effect=RuntimeError("forced failure")):
            result = node.execute(skip_error=True)
        self.assertEqual(result["result"][:2], ("", ""))
        self.assertIn("forced failure", json.loads(result["result"][2])["error"])


class ContextIRClientTests(unittest.TestCase):
    def test_submit_uses_legacy_endpoint_and_accepts_root_id(self):
        session = Mock()
        session.post.return_value = _Response(200, {"id": "task-test"})
        with patch.object(client, "_session", return_value=session):
            task_id = client.submit_context_ir_task(
                {"model": "minmax-h3-context-ir-text"},
                CONFIG,
            )
        self.assertEqual(task_id, "task-test")
        self.assertEqual(
            session.post.call_args.args[0],
            "https://api.seedance.nz/v1/video/generations",
        )

    def test_poll_reads_data_status_and_result_text(self):
        session = Mock()
        session.get.side_effect = [
            _Response(200, {"data": {"status": "IN_PROGRESS", "progress": "50%"}}),
            _Response(200, {
                "code": "success",
                "data": {"status": "SUCCESS", "result_text": "Enhanced prompt"},
            }),
        ]
        with (
            patch.object(client, "_session", return_value=session),
            patch.object(client, "cooperative_sleep"),
        ):
            response = client.poll_context_ir_task("task-test", CONFIG)
        self.assertEqual(client.extract_context_ir_text(response), "Enhanced prompt")
        self.assertEqual(session.get.call_count, 2)


class ContextIRRegistrationAndWorkflowTests(unittest.TestCase):
    def test_node_is_registered_without_media_concurrent_wrapper(self):
        self.assertIs(
            nodes.NODE_CLASS_MAPPINGS["Minimax_H3_Context_IR"],
            nodes.MinimaxH3ContextIR,
        )
        self.assertNotIn("Minimax_H3_Context_IR", concurrent_nodes.PURE_IMAGE_NODE_KEYS)
        self.assertNotIn("Minimax_H3_Context_IR", concurrent_nodes.PURE_VIDEO_NODE_KEYS)
        self.assertNotIn(
            "SeedanceConcurrent_Minimax_H3_Context_IR_Submit",
            concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS,
        )

    def test_frontend_uses_shared_dynamic_visibility_helpers(self):
        source = (PLUGIN_ROOT / "web" / "js" / "qwen_minimax_model_ui.js").read_text(
            encoding="utf-8"
        )
        for fragment in (
            'const CONTEXT_IR_NODE_NAME = "Minimax_H3_Context_IR"',
            'const CONTEXT_IR_DEFAULT_MODEL = "minmax-h3-context-ir-text"',
            "function refreshContextIRNode(node)",
            'model.endsWith("-image")',
            'model.endsWith("-multimodal")',
            'setWidgetVisible(widgetByName(node, "ratio"), !model.endsWith("-image"))',
            "setInputVisible(node, input, contextIRInputAllowed(model, input.name))",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)

    def test_three_safe_workflows_cover_all_models(self):
        workflows = {}
        for path in (PLUGIN_ROOT / "examples").glob("minmax-h3-context-ir-*.json"):
            workflow = json.loads(path.read_text(encoding="utf-8"))
            node = next(
                item for item in workflow["nodes"]
                if item.get("type") == "Minimax_H3_Context_IR"
            )
            workflows[node["widgets_values"][0]] = (path, workflow, node)

        self.assertEqual(set(workflows), set(nodes.MINMAX_H3_CONTEXT_IR_MODELS))
        for model, (path, workflow, context_node) in workflows.items():
            with self.subTest(model=model, workflow=path.name):
                config = next(
                    item for item in workflow["nodes"]
                    if item["type"] == "Seedance_Config"
                )
                self.assertEqual(config["widgets_values"], ["https://api.seedance.nz", ""])
                self.assertNotIn("sk-", json.dumps(workflow))
                config_links = [
                    link for link in workflow["links"]
                    if link[3] == context_node["id"] and link[5] == "SEEDANCE_CONFIG"
                ]
                self.assertEqual(len(config_links), 1)
                text_links = [
                    link for link in workflow["links"]
                    if link[1] == context_node["id"] and link[2] == 0 and link[5] == "STRING"
                ]
                self.assertEqual(len(text_links), 1)

        multi_node = workflows[nodes.MINMAX_H3_CONTEXT_IR_MULTIMODAL_MODEL][2]
        multi_workflow = workflows[nodes.MINMAX_H3_CONTEXT_IR_MULTIMODAL_MODEL][1]
        incoming_types = {
            link[5]
            for link in multi_workflow["links"]
            if link[3] == multi_node["id"]
        }
        self.assertTrue({"IMAGE", "VIDEO", "AUDIO"}.issubset(incoming_types))


if __name__ == "__main__":
    unittest.main()
