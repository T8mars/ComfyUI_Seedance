import json
import os
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import torch
from PIL import Image


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT.parent))

from ComfyUI_Seedance import nodes
from ComfyUI_Seedance.core import client, media


EXPECTED_OPERATIONS = [
    "midjourney-imagine",
    "midjourney-blend",
    "midjourney-describe",
    "midjourney-edits",
    "midjourney-upscale",
    "midjourney-variation",
    "midjourney-high-variation",
    "midjourney-low-variation",
    "midjourney-reroll",
    "midjourney-zoom",
    "midjourney-pan",
    "midjourney-inpaint",
    "midjourney-modal",
    "midjourney-video",
    "midjourney-remix-strong",
    "midjourney-remix-subtle",
]


def base_kwargs():
    return {
        "prompt": "a small red paper boat on a quiet lake",
        "speed": "relax",
        "size": "1:1",
        "custom_size": "",
        "dimensions": "SQUARE",
        "quality": "1",
        "style": "",
        "version": "8.2",
        "seed": -1,
        "negative_prompt": "",
        "stylize": -1,
        "chaos": -1,
        "weird": -1,
        "tile": False,
        "niji": False,
        "iw": -1.0,
        "cw": -1,
        "sw": -1,
        "cref": "",
        "sref": "",
        "dref": "",
        "dw": -1.0,
        "repeat": 0,
        "raw": False,
        "draft": False,
        "hd": False,
        "stop": 0,
        "extra": "",
        "task_id": "source-grid",
        "index": 1,
        "custom_id": "",
        "direction": "right",
        "zoom_ratio": 2.0,
        "modal_mode": "region",
        "video_type": "vid_1.1_i2v_480",
        "animate_mode": "manual",
        "motion": "high",
        "batch_size": 1,
        "metadata_json": "",
    }


def materials(images=None, end_url="", mask_url=""):
    return {
        "image_urls": list(images or []),
        "end_url": end_url,
        "mask_url": mask_url,
    }


def valid_payload_case(operation):
    values = base_kwargs()
    refs = materials()
    if operation == "midjourney-imagine":
        values["task_id"] = ""
    elif operation == "midjourney-blend":
        refs = materials(["https://example.test/a.png", "https://example.test/b.png"])
    elif operation == "midjourney-describe":
        refs = materials(["https://example.test/a.png"])
    elif operation == "midjourney-edits":
        refs = materials(["https://example.test/a.png"])
    elif operation == "midjourney-modal":
        refs = materials(mask_url="https://example.test/mask.png")
    elif operation == "midjourney-video":
        values["task_id"] = ""
        values["index"] = -1
        refs = materials(["https://example.test/start.png"])
    return values, refs


class MidjourneyActionSpecTests(unittest.TestCase):
    def test_catalog_contains_exactly_sixteen_documented_operations(self):
        self.assertEqual(nodes.MIDJOURNEY_OPERATIONS, EXPECTED_OPERATIONS)
        self.assertEqual(len(nodes.MIDJOURNEY_ACTION_SPECS), 16)

    def test_paths_are_explicit(self):
        for operation in EXPECTED_OPERATIONS:
            with self.subTest(operation=operation):
                self.assertEqual(
                    nodes.MIDJOURNEY_ACTION_SPECS[operation]["action"],
                    operation.removeprefix("midjourney-"),
                )

    def test_friendly_operation_labels_preserve_canonical_action_ids(self):
        self.assertEqual(
            set(nodes.MIDJOURNEY_OPERATION_LABELS),
            set(EXPECTED_OPERATIONS),
        )
        self.assertEqual(
            len(set(nodes.MIDJOURNEY_OPERATION_LABELS.values())),
            len(EXPECTED_OPERATIONS),
        )
        for operation, label in nodes.MIDJOURNEY_OPERATION_LABELS.items():
            with self.subTest(operation=operation):
                self.assertTrue(label.startswith(f"{operation}｜"))
                self.assertEqual(
                    nodes._normalize_midjourney_operation(label),
                    operation,
                )

    def test_input_defaults_are_ready_to_use_and_size_has_custom_mode(self):
        inputs = nodes.MidjourneyMultiAction.INPUT_TYPES()
        required = inputs["required"]
        self.assertEqual(required["speed"][1]["default"], "relax")
        self.assertEqual(required["size"][1]["default"], "1:1")
        self.assertIn("custom", required["size"][0])
        self.assertIn("custom_size", required)
        self.assertEqual(required["dimensions"][1]["default"], "SQUARE")
        self.assertEqual(required["quality"][1]["default"], "1")
        self.assertEqual(required["version"][1]["default"], "8.2")
        self.assertEqual(required["direction"][1]["default"], "right")

    def test_required_fields_are_whitelisted(self):
        for operation, spec in nodes.MIDJOURNEY_ACTION_SPECS.items():
            with self.subTest(operation=operation):
                allowed = set(spec["allowed_fields"])
                self.assertTrue(set(spec["required_fields"]).issubset(allowed))
                for group in spec["required_one_of"]:
                    self.assertTrue(set(group).issubset(allowed))

    def test_linked_prompt_preflight_does_not_reject_empty_widget(self):
        result = nodes.MidjourneyMultiAction.VALIDATE_INPUTS(
            operation="midjourney-imagine",
            prompt="",
            speed="relax",
            version="8.2",
            dimensions="SQUARE",
            quality="1",
            direction="right",
            modal_mode="region",
            video_type="vid_1.1_i2v_480",
            animate_mode="manual",
            motion="high",
            batch_size=1,
            index=-1,
            size="1:1",
            custom_size="",
        )
        self.assertIs(result, True)

    def test_registered_node_has_expected_fixed_outputs(self):
        cls = nodes.NODE_CLASS_MAPPINGS["Midjourney_Multi_Action"]
        self.assertIs(cls, nodes.MidjourneyMultiAction)
        self.assertEqual(len(cls.RETURN_TYPES), 17)
        self.assertEqual(cls.RETURN_NAMES[0:5], (
            "image1", "image2", "image3", "image4", "grid_image"
        ))

    def test_nineteen_example_workflows_cover_all_operations(self):
        paths = sorted((PLUGIN_ROOT / "examples").glob("midjourney-*.json"))
        self.assertEqual(len(paths), 19)
        selected = set()
        for path in paths:
            workflow = json.loads(path.read_text(encoding="utf-8"))
            operations = {
                node["widgets_values"][0]
                for node in workflow["nodes"]
                if node["type"] == "Midjourney_Multi_Action"
            }
            with self.subTest(workflow=path.name):
                self.assertTrue(operations)
            selected.update(operations)
        self.assertEqual(selected, set(EXPECTED_OPERATIONS))

    def test_example_workflows_use_ready_to_run_widget_defaults(self):
        required_names = list(
            nodes.MidjourneyMultiAction.INPUT_TYPES()["required"]
        )
        indexes = {
            name: required_names.index(name)
            for name in ("speed", "size", "quality", "version", "direction")
        }
        for path in sorted((PLUGIN_ROOT / "examples").glob("midjourney-*.json")):
            workflow = json.loads(path.read_text(encoding="utf-8"))
            for node in workflow["nodes"]:
                if node["type"] != "Midjourney_Multi_Action":
                    continue
                values = node["widgets_values"]
                with self.subTest(workflow=path.name, node=node["id"]):
                    self.assertEqual(values[indexes["speed"]], "relax")
                    self.assertEqual(values[indexes["size"]], "1:1")
                    self.assertEqual(values[indexes["quality"]], "1")
                    self.assertNotEqual(values[indexes["version"]], "unset")
                    self.assertEqual(values[indexes["direction"]], "right")
                    self.assertEqual(len(values), len(required_names) + 1)

    def test_task_workflows_connect_upstream_task_ids(self):
        task_actions = {
            "midjourney-upscale",
            "midjourney-variation",
            "midjourney-high-variation",
            "midjourney-low-variation",
            "midjourney-reroll",
            "midjourney-zoom",
            "midjourney-pan",
            "midjourney-inpaint",
            "midjourney-modal",
            "midjourney-remix-strong",
            "midjourney-remix-subtle",
        }
        for path in sorted((PLUGIN_ROOT / "examples").glob("midjourney-*.json")):
            workflow = json.loads(path.read_text(encoding="utf-8"))
            for node in workflow["nodes"]:
                if node["type"] != "Midjourney_Multi_Action":
                    continue
                operation = node["widgets_values"][0]
                if operation not in task_actions:
                    continue
                task_input = next(
                    item for item in node["inputs"] if item["name"] == "task_id"
                )
                with self.subTest(workflow=path.name, operation=operation):
                    self.assertIsNotNone(task_input["link"])

    def test_modal_and_start_end_workflows_wire_special_inputs(self):
        modal_path = (
            PLUGIN_ROOT / "examples" / "midjourney-modal局部重绘完成.json"
        )
        modal_workflow = json.loads(modal_path.read_text(encoding="utf-8"))
        modal_node = next(
            node
            for node in modal_workflow["nodes"]
            if node["type"] == "Midjourney_Multi_Action"
            and node["widgets_values"][0] == "midjourney-modal"
        )
        self.assertIsNotNone(
            next(item for item in modal_node["inputs"] if item["name"] == "mask")[
                "link"
            ]
        )

        video_path = (
            PLUGIN_ROOT / "examples" / "midjourney-video首尾帧.json"
        )
        video_workflow = json.loads(video_path.read_text(encoding="utf-8"))
        video_node = next(
            node
            for node in video_workflow["nodes"]
            if node["type"] == "Midjourney_Multi_Action"
        )
        self.assertIsNotNone(
            next(
                item for item in video_node["inputs"]
                if item["name"] == "end_image"
            )["link"]
        )

    def test_edits_workflow_uses_external_string_input(self):
        path = PLUGIN_ROOT / "examples" / "midjourney-edits图片编辑.json"
        workflow = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn(
            "PrimitiveStringMultiline",
            {node["type"] for node in workflow["nodes"]},
        )
        edit_node = next(
            node
            for node in workflow["nodes"]
            if node["type"] == "Midjourney_Multi_Action"
        )
        prompt_input = next(
            item for item in edit_node["inputs"] if item["name"] == "prompt"
        )
        self.assertIsNotNone(prompt_input["link"])


class MidjourneyPayloadTests(unittest.TestCase):
    def setUp(self):
        self.node = nodes.MidjourneyMultiAction()

    def test_every_action_builds_only_its_whitelisted_fields(self):
        for operation in EXPECTED_OPERATIONS:
            values, refs = valid_payload_case(operation)
            with self.subTest(operation=operation):
                payload = self.node._build_payload(operation, refs, **values)
                spec = nodes.MIDJOURNEY_ACTION_SPECS[operation]
                self.assertTrue(set(payload).issubset(spec["allowed_fields"]))
                self.assertNotIn("model", payload)

    def test_imagine_forwards_structured_fields_without_model(self):
        values = base_kwargs()
        values.update({
            "version": "7",
            "size": "16:9",
            "quality": "1",
            "seed": 7,
            "stylize": 250,
            "niji": True,
            "negative_prompt": "text",
            "metadata_json": '{"origin":"workflow"}',
            "task_id": "",
        })
        payload = self.node._build_payload(
            "midjourney-imagine",
            materials(["https://example.test/ref.png"]),
            **values,
        )
        self.assertEqual(payload["prompt"], values["prompt"])
        self.assertEqual(payload["image_urls"], ["https://example.test/ref.png"])
        self.assertEqual(payload["version"], "7")
        self.assertEqual(payload["size"], "16:9")
        self.assertEqual(payload["seed"], 7)
        self.assertEqual(payload["stylize"], 250)
        self.assertTrue(payload["niji"])
        self.assertEqual(payload["metadata"], {"origin": "workflow"})
        self.assertNotIn("model", payload)

    def test_custom_size_resolves_to_ratio_and_rejects_invalid_values(self):
        values = base_kwargs()
        values.update({
            "task_id": "",
            "size": "custom",
            "custom_size": "5:4",
        })
        payload = self.node._build_payload(
            "midjourney-imagine",
            materials(),
            **values,
        )
        self.assertEqual(payload["size"], "5:4")

        values["custom_size"] = "1280x1024"
        with self.assertRaisesRegex(client.SeedanceAPIError, "w:h"):
            self.node._build_payload(
                "midjourney-imagine",
                materials(),
                **values,
            )

    def test_friendly_operation_label_builds_the_same_payload(self):
        values = base_kwargs()
        values["task_id"] = ""
        operation = "midjourney-imagine"
        canonical = self.node._build_payload(
            operation,
            materials(),
            **values,
        )
        friendly = self.node._build_payload(
            nodes.MIDJOURNEY_OPERATION_LABELS[operation],
            materials(),
            **values,
        )
        self.assertEqual(friendly, canonical)

    def test_video_and_remix_do_not_send_undocumented_metadata(self):
        for operation in (
            "midjourney-video",
            "midjourney-remix-strong",
            "midjourney-remix-subtle",
        ):
            values, refs = valid_payload_case(operation)
            values["metadata_json"] = "stale-invalid-json-must-be-ignored"
            with self.subTest(operation=operation):
                payload = self.node._build_payload(operation, refs, **values)
                self.assertNotIn("metadata", payload)

    def test_version_gated_structured_flags_reject_invalid_combinations(self):
        cases = (
            ({"version": "5", "raw": True}, "raw"),
            ({"version": "6.1", "draft": True}, "draft"),
            ({"version": "7", "hd": True}, "hd"),
            ({"version": "8.1", "stop": 50}, "stop"),
            ({"version": "8.1", "niji": True}, "niji"),
        )
        for overrides, message in cases:
            values = base_kwargs()
            values.update({"task_id": "", **overrides})
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(client.SeedanceAPIError, message):
                    self.node._build_payload(
                        "midjourney-imagine", materials(), **values
                    )

    def test_version_gated_structured_flags_accept_documented_combinations(self):
        cases = (
            {"version": "5.1", "raw": True},
            {"version": "7", "draft": True},
            {"version": "8.1", "hd": True},
            {"version": "6.1", "stop": 50},
            {"version": "5", "niji": True, "stop": 50},
            {"version": "unset", "hd": True},
        )
        for overrides in cases:
            values = base_kwargs()
            values.update({"task_id": "", **overrides})
            with self.subTest(overrides=overrides):
                payload = self.node._build_payload(
                    "midjourney-imagine", materials(), **values
                )
                self.assertTrue(
                    any(field in payload for field in ("raw", "draft", "hd", "stop"))
                )

    def test_hidden_irrelevant_values_are_not_sent(self):
        values = base_kwargs()
        values.update({"style": "raw", "version": "8.1", "task_id": ""})
        payload = self.node._build_payload(
            "midjourney-describe",
            materials(["https://example.test/a.png"]),
            **values,
        )
        self.assertEqual(payload, {
            "image_urls": ["https://example.test/a.png"],
            "speed": "relax",
        })

    def test_imagine_runtime_requires_prompt(self):
        values = base_kwargs()
        values.update({"prompt": "", "task_id": ""})
        with self.assertRaisesRegex(client.SeedanceAPIError, "prompt"):
            self.node._build_payload(
                "midjourney-imagine", materials(), **values
            )

    def test_blend_requires_two_to_four_images_and_size_overrides_dimensions(self):
        values = base_kwargs()
        values.update({"size": "16:9", "dimensions": "PORTRAIT"})
        payload = self.node._build_payload(
            "midjourney-blend",
            materials(["https://example.test/a.png", "https://example.test/b.png"]),
            **values,
        )
        self.assertEqual(payload["size"], "16:9")
        self.assertNotIn("dimensions", payload)
        with self.assertRaisesRegex(client.SeedanceAPIError, "2-4"):
            self.node._build_payload(
                "midjourney-blend",
                materials(["https://example.test/a.png"]),
                **values,
            )

    def test_describe_requires_exactly_one_image(self):
        values = base_kwargs()
        for refs in ([], ["https://example.test/a.png", "https://example.test/b.png"]):
            with self.subTest(count=len(refs)):
                with self.assertRaisesRegex(client.SeedanceAPIError, "exactly one"):
                    self.node._build_payload(
                        "midjourney-describe", materials(refs), **values
                    )

    def test_custom_id_omits_auto_index_and_direction(self):
        values = base_kwargs()
        values["custom_id"] = "button-value"
        upscale = self.node._build_payload(
            "midjourney-upscale", materials(), **values
        )
        pan = self.node._build_payload(
            "midjourney-pan", materials(), **values
        )
        self.assertEqual(upscale["custom_id"], "button-value")
        self.assertNotIn("index", upscale)
        self.assertEqual(pan["custom_id"], "button-value")
        self.assertNotIn("index", pan)
        self.assertNotIn("direction", pan)

    def test_image_actions_use_one_based_index(self):
        for operation in (
            "midjourney-upscale",
            "midjourney-variation",
            "midjourney-high-variation",
            "midjourney-low-variation",
            "midjourney-remix-strong",
            "midjourney-remix-subtle",
        ):
            values = base_kwargs()
            values["index"] = 0
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(client.SeedanceAPIError, "1-4"):
                    self.node._build_payload(operation, materials(), **values)

    def test_modal_region_forwards_mask_and_outpaint_omits_it(self):
        values = base_kwargs()
        region = self.node._build_payload(
            "midjourney-modal",
            materials(mask_url="https://example.test/mask.png"),
            **values,
        )
        self.assertEqual(region["mask_url"], "https://example.test/mask.png")
        outpaint = self.node._build_payload(
            "midjourney-modal", materials(), **values
        )
        self.assertNotIn("mask_url", outpaint)

    def test_video_direct_task_auto_and_start_end_payloads(self):
        values = base_kwargs()
        values.update({"task_id": "", "index": -1})
        direct = self.node._build_payload(
            "midjourney-video",
            materials(["https://example.test/start.png"]),
            **values,
        )
        self.assertEqual(direct["image_urls"], ["https://example.test/start.png"])
        self.assertNotIn("task_id", direct)

        values.update({
            "task_id": "source-grid",
            "index": 0,
            "animate_mode": "auto",
        })
        task_auto = self.node._build_payload(
            "midjourney-video", materials(), **values
        )
        self.assertEqual(task_auto["task_id"], "source-grid")
        self.assertEqual(task_auto["index"], 0)
        self.assertEqual(task_auto["animate_mode"], "auto")

        values.update({"task_id": "", "index": -1, "animate_mode": "manual"})
        start_end = self.node._build_payload(
            "midjourney-video",
            materials(
                ["https://example.test/start.png"],
                end_url="https://example.test/end.png",
            ),
            **values,
        )
        self.assertEqual(
            start_end["video_type"], "vid_1.1_i2v_start_end_480"
        )

    def test_video_rejects_mixed_source_and_bad_auto_mode(self):
        values = base_kwargs()
        values.update({"task_id": "source-grid", "index": 0})
        with self.assertRaisesRegex(client.SeedanceAPIError, "exactly one source"):
            self.node._build_payload(
                "midjourney-video",
                materials(["https://example.test/start.png"]),
                **values,
            )
        values.update({"task_id": "", "animate_mode": "auto"})
        with self.assertRaisesRegex(client.SeedanceAPIError, "auto mode"):
            self.node._build_payload(
                "midjourney-video",
                materials(["https://example.test/start.png"]),
                **values,
            )

    def test_repeat_and_stop_ranges_are_runtime_checked(self):
        values = base_kwargs()
        values.update({"task_id": "", "repeat": 1})
        with self.assertRaisesRegex(client.SeedanceAPIError, "repeat"):
            self.node._build_payload(
                "midjourney-imagine", materials(), **values
            )
        values.update({"repeat": 0, "stop": 5})
        with self.assertRaisesRegex(client.SeedanceAPIError, "stop"):
            self.node._build_payload(
                "midjourney-imagine", materials(), **values
            )

    def test_invalid_metadata_json_is_rejected(self):
        values = base_kwargs()
        values.update({"task_id": "", "metadata_json": "[]"})
        with self.assertRaisesRegex(client.SeedanceAPIError, "JSON object"):
            self.node._build_payload(
                "midjourney-imagine", materials(), **values
            )


class MidjourneyMaterialTests(unittest.TestCase):
    def setUp(self):
        self.node = nodes.MidjourneyMultiAction()
        self.config = {"base_url": "https://api.example", "api_key": "unused"}

    def test_local_and_url_in_same_slot_conflict(self):
        with self.assertRaisesRegex(client.SeedanceAPIError, "cannot both"):
            self.node._collect_materials(
                "midjourney-describe",
                {
                    "image1": object(),
                    "image_url1": "https://example.test/a.png",
                },
                self.config,
                lambda _value: None,
            )

    def test_local_images_upload_in_slot_order(self):
        with (
            patch.object(nodes, "image_to_png_bytes", return_value=b"png"),
            patch.object(
                nodes,
                "upload_media",
                side_effect=[
                    "https://upload.test/one.png",
                    "https://upload.test/three.png",
                ],
            ) as upload,
        ):
            result = self.node._collect_materials(
                "midjourney-blend",
                {
                    "image1": object(),
                    "image3": object(),
                    "image_url2": "",
                    "image_url4": "",
                },
                self.config,
                lambda _value: None,
            )
        self.assertEqual(
            result["image_urls"],
            [
                "https://upload.test/one.png",
                "https://upload.test/three.png",
            ],
        )
        self.assertEqual(upload.call_count, 2)

    def test_region_mask_upload_uses_midjourney_alpha_encoder(self):
        with (
            patch.object(
                nodes, "mask_to_midjourney_png_bytes", return_value=b"mask"
            ) as encode,
            patch.object(
                nodes,
                "upload_media",
                return_value="https://upload.test/mask.png",
            ),
        ):
            result = self.node._collect_materials(
                "midjourney-modal",
                {"modal_mode": "region", "mask": object(), "mask_url": ""},
                self.config,
                lambda _value: None,
            )
        self.assertEqual(result["mask_url"], "https://upload.test/mask.png")
        encode.assert_called_once()

    def test_outpaint_ignores_stale_mask_inputs(self):
        result = self.node._collect_materials(
            "midjourney-modal",
            {
                "modal_mode": "outpaint",
                "mask": object(),
                "mask_url": "not-a-current-mask",
            },
            self.config,
            lambda _value: None,
        )
        self.assertEqual(result["mask_url"], "")


class MidjourneyMediaTests(unittest.TestCase):
    def test_mask_encoder_makes_selected_pixels_transparent(self):
        mask = torch.tensor([[[1.0, 0.0]]], dtype=torch.float32)
        encoded = media.mask_to_midjourney_png_bytes(mask)
        with Image.open(BytesIO(encoded)) as image:
            rgba = image.convert("RGBA")
            self.assertEqual(rgba.getpixel((0, 0)), (255, 255, 255, 0))
            self.assertEqual(rgba.getpixel((1, 0)), (255, 255, 255, 255))


class MidjourneyClientTests(unittest.TestCase):
    def test_submit_uses_explicit_midjourney_route_without_model(self):
        response = MagicMock()
        response.status_code = 200
        response.text = '{"data":[{"task_id":"source-result"}]}'
        response.json.return_value = {"data": [{"task_id": "source-result"}]}
        session = MagicMock()
        session.post.return_value = response
        with patch.object(client, "_session", return_value=session):
            task_id, _data = client.submit_midjourney_action(
                "imagine",
                {"prompt": "paper boat"},
                {"base_url": "https://api.example", "api_key": "unused"},
            )
        self.assertEqual(task_id, "source-result")
        self.assertTrue(
            session.post.call_args.args[0].endswith(
                "/v1/midjourney/generations/imagine"
            )
        )
        self.assertNotIn("model", session.post.call_args.kwargs["json"])

    def test_poll_falls_back_to_second_documented_route(self):
        missing = MagicMock()
        missing.status_code = 404
        completed_payload = {
            "data": {
                "status": "SUCCESS",
                "image_urls": ["https://example.test/a.png"],
            }
        }
        completed = MagicMock()
        completed.status_code = 200
        completed.json.return_value = completed_payload
        session = MagicMock()
        session.get.side_effect = [missing, completed]
        with (
            patch.object(client, "_session", return_value=session),
            patch.object(client.time, "sleep"),
        ):
            result = client.poll_midjourney_task(
                "source-result",
                {
                    "base_url": "https://api.example",
                    "api_key": "unused",
                    "poll_interval": 0,
                    "max_poll_time": 30,
                },
            )
        self.assertEqual(result, completed_payload)
        self.assertIn(
            "/v1/midjourney/tasks/source-result",
            session.get.call_args.args[0],
        )

    def test_poll_falls_back_to_third_route_and_extracts_result_images(self):
        missing_one = MagicMock()
        missing_one.status_code = 404
        missing_two = MagicMock()
        missing_two.status_code = 404
        completed_payload = {
            "result": {
                "task_id": "source-result",
                "status": "SUCCESS",
                "images": [{"url": "https://example.test/generated.png"}],
            }
        }
        completed = MagicMock()
        completed.status_code = 200
        completed.json.return_value = completed_payload
        session = MagicMock()
        session.get.side_effect = [missing_one, missing_two, completed]
        with (
            patch.object(client, "_session", return_value=session),
            patch.object(client.time, "sleep"),
        ):
            response = client.poll_midjourney_task(
                "source-result",
                {
                    "base_url": "https://api.example",
                    "api_key": "unused",
                    "poll_interval": 0,
                    "max_poll_time": 30,
                },
            )
        self.assertEqual(session.get.call_count, 3)
        self.assertIn("/v1/tasks/source-result", session.get.call_args.args[0])
        extracted = client.extract_midjourney_results(response)
        self.assertEqual(
            extracted["image_urls"], ["https://example.test/generated.png"]
        )

    def test_poll_raises_when_all_documented_routes_return_not_found(self):
        missing = MagicMock()
        missing.status_code = 404
        missing.text = "not found"
        session = MagicMock()
        session.get.return_value = missing
        with (
            patch.object(client, "_session", return_value=session),
            patch.object(client.time, "sleep"),
            self.assertRaisesRegex(
                client.SeedanceAPIError,
                "not found on any documented query route",
            ),
        ):
            client.poll_midjourney_task(
                "missing-result",
                {
                    "base_url": "https://api.example",
                    "api_key": "unused",
                    "poll_interval": 0,
                    "max_poll_time": 30,
                },
            )
        self.assertEqual(session.get.call_count, 3)

    def test_poll_returns_modal_only_when_requested(self):
        modal_payload = {"data": {"status": "MODAL", "task_id": "modal-source"}}
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = modal_payload
        session = MagicMock()
        session.get.return_value = response
        config = {
            "base_url": "https://api.example",
            "api_key": "unused",
            "poll_interval": 0,
            "max_poll_time": 30,
        }
        with (
            patch.object(client, "_session", return_value=session),
            patch.object(client.time, "sleep"),
        ):
            self.assertEqual(
                client.poll_midjourney_task(
                    "modal-source", config, stop_on_modal=True
                ),
                modal_payload,
            )
        with (
            patch.object(client, "_session", return_value=session),
            patch.object(client.time, "sleep"),
        ):
            with self.assertRaisesRegex(client.SeedanceAPIError, "modal"):
                client.poll_midjourney_task("modal-source", config)

    def test_poll_raises_on_failed_terminal_state(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "data": {"status": "FAILURE", "fail_reason": "upstream rejected"}
        }
        session = MagicMock()
        session.get.return_value = response
        with (
            patch.object(client, "_session", return_value=session),
            patch.object(client.time, "sleep"),
        ):
            with self.assertRaisesRegex(client.SeedanceAPIError, "upstream rejected"):
                client.poll_midjourney_task(
                    "source-result",
                    {
                        "base_url": "https://api.example",
                        "api_key": "unused",
                        "poll_interval": 0,
                        "max_poll_time": 30,
                    },
                )

    def test_poll_raises_immediately_on_cancel_terminal_state(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "data": {"status": "CANCEL", "fail_reason": "modal expired"}
        }
        session = MagicMock()
        session.get.return_value = response
        with (
            patch.object(client, "_session", return_value=session),
            patch.object(client.time, "sleep"),
            self.assertRaisesRegex(client.SeedanceAPIError, "modal expired"),
        ):
            client.poll_midjourney_task(
                "source-result",
                {
                    "base_url": "https://api.example",
                    "api_key": "unused",
                    "poll_interval": 0,
                    "max_poll_time": 30,
                },
            )
        self.assertEqual(session.get.call_count, 1)

    def test_result_extraction_ignores_echoed_request_and_metadata_urls(self):
        response = {
            "request": {
                "image_urls": ["https://example.test/input.png"],
                "prompt": "input prompt",
            },
            "metadata": {
                "images": [{"url": "https://example.test/tracking.png"}],
                "description": "tracking description",
            },
            "data": {
                "status": "SUCCESS",
                "result": {
                    "images": [{"url": "https://example.test/generated.png"}],
                    "description": "generated description",
                },
            },
        }
        result = client.extract_midjourney_results(response)
        self.assertEqual(
            result["image_urls"], ["https://example.test/generated.png"]
        )
        self.assertEqual(result["text"], "generated description")

        output_result = client.extract_midjourney_results({
            "output": {
                "task_id": "output-task",
                "status": "SUCCESS",
                "images": [{"url": "https://example.test/output.png"}],
            }
        })
        self.assertEqual(output_result["task_id"], "output-task")
        self.assertEqual(
            output_result["image_urls"], ["https://example.test/output.png"]
        )

    def test_extract_results_preserves_images_grid_videos_buttons_and_text(self):
        response = {
            "data": {
                "id": "source-result",
                "status": "SUCCESS",
                "description": "four paper boat prompts",
                "image_urls": [
                    "https://example.test/1.png",
                    "https://example.test/2.png",
                ],
                "grid_image_url": "https://example.test/grid.png",
                "video_urls": ["https://example.test/a.mp4"],
                "buttons": [{"customId": "button-value", "label": "U1"}],
            }
        }
        result = client.extract_midjourney_results(response)
        self.assertEqual(result["task_id"], "source-result")
        self.assertEqual(result["image_urls"], [
            "https://example.test/1.png",
            "https://example.test/2.png",
        ])
        self.assertEqual(result["grid_image_url"], "https://example.test/grid.png")
        self.assertEqual(result["video_urls"], ["https://example.test/a.mp4"])
        self.assertEqual(result["buttons"][0]["label"], "U1")
        self.assertEqual(result["text"], "four paper boat prompts")

        observed_describe = {
            "id": "source-result",
            "status": "SUCCESS",
            "description": "four observed prompts",
            "result": {"description": "nested result text"},
        }
        self.assertIs(
            client._unwrap_midjourney_task_data(observed_describe),
            observed_describe,
        )
        observed_result = client.extract_midjourney_results(observed_describe)
        self.assertEqual(observed_result["status"], "SUCCESS")
        self.assertEqual(
            observed_result["text"], "four observed prompts"
        )

    def test_download_image_with_path_decodes_and_saves_once(self):
        buffer = BytesIO()
        Image.new("RGB", (3, 2), (10, 20, 30)).save(buffer, format="PNG")
        response = MagicMock()
        response.content = buffer.getvalue()
        response.iter_content.return_value = [buffer.getvalue()]
        response.headers = {"Content-Type": "image/png"}
        response.raise_for_status.return_value = None
        session = MagicMock()
        session.get.return_value = response
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch.object(client, "_session", return_value=session),
                patch.dict(os.environ, {"SEEDANCE_OUTPUT_DIR": tmpdir}),
            ):
                tensor, path = client.download_image_with_path(
                    "https://example.test/a.png"
                )
            self.assertEqual(tuple(tensor.shape), (1, 2, 3, 3))
            self.assertTrue(Path(path).is_file())
            self.assertEqual(session.get.call_count, 1)
            self.assertTrue(session.get.call_args.kwargs["stream"])


class MidjourneyExecutionTests(unittest.TestCase):
    def setUp(self):
        self.node = nodes.MidjourneyMultiAction()

    def test_describe_immediate_text_does_not_poll(self):
        submit_response = {
            "data": {
                "task_id": "source-result",
                "description": "a tiny red paper boat",
            }
        }
        with (
            patch.object(nodes, "get_config", return_value={"api_key": "unused"}),
            patch.object(
                nodes,
                "submit_midjourney_action",
                return_value=("source-result", submit_response),
            ),
            patch.object(nodes, "poll_midjourney_task") as poll,
        ):
            result = self.node._execute_inner(
                operation="midjourney-describe",
                image_url1="https://example.test/a.png",
            )
        poll.assert_not_called()
        self.assertEqual(result["result"][9], "a tiny red paper boat")
        self.assertEqual(result["result"][14], "source-result")

    def test_async_image_action_downloads_four_slots_and_grid(self):
        final = {
            "data": {
                "status": "SUCCESS",
                "image_urls": [
                    "https://example.test/1.png",
                    "https://example.test/2.png",
                ],
                "grid_image_url": "https://example.test/grid.png",
                "buttons": [{"customId": "button-value", "label": "U1"}],
            }
        }
        images = [object(), object(), object()]
        with (
            patch.object(nodes, "get_config", return_value={"api_key": "unused"}),
            patch.object(
                nodes,
                "submit_midjourney_action",
                return_value=("source-result", {"data": {"status": "SUBMITTED"}}),
            ),
            patch.object(nodes, "poll_midjourney_task", return_value=final),
            patch.object(
                nodes,
                "download_image_with_path",
                side_effect=[
                    (images[0], "one.png"),
                    (images[1], "two.png"),
                    (images[2], "grid.png"),
                ],
            ),
        ):
            result = self.node._execute_inner(
                operation="midjourney-imagine",
                prompt="paper boat",
            )
        self.assertIs(result["result"][0], images[0])
        self.assertIs(result["result"][1], images[1])
        self.assertIsNone(result["result"][2])
        self.assertIs(result["result"][4], images[2])
        self.assertEqual(
            json.loads(result["result"][11]),
            [
                "https://example.test/1.png",
                "https://example.test/2.png",
                "https://example.test/grid.png",
            ],
        )
        self.assertEqual(json.loads(result["result"][15])[0]["label"], "U1")

    def test_inpaint_returns_modal_task_without_media(self):
        final = {"data": {"status": "MODAL", "task_id": "modal-source"}}
        with (
            patch.object(nodes, "get_config", return_value={"api_key": "unused"}),
            patch.object(
                nodes,
                "submit_midjourney_action",
                return_value=("modal-source", {"data": {"status": "SUBMITTED"}}),
            ),
            patch.object(
                nodes, "poll_midjourney_task", return_value=final
            ) as poll,
        ):
            result = self.node._execute_inner(
                operation="midjourney-inpaint",
                task_id="source-upscaled",
                index=-1,
            )
        self.assertEqual(result["result"][14], "modal-source")
        self.assertTrue(poll.call_args.kwargs["stop_on_modal"])
        self.assertEqual(json.loads(result["result"][11]), [])

    def test_video_downloads_all_returned_batch_results(self):
        final = {
            "data": {
                "status": "SUCCESS",
                "video_urls": [
                    "https://example.test/1.mp4",
                    "https://example.test/2.mp4",
                ],
            }
        }
        videos = [object(), object()]
        with (
            patch.object(nodes, "get_config", return_value={"api_key": "unused"}),
            patch.object(
                nodes,
                "submit_midjourney_action",
                return_value=("source-result", {"data": {"status": "SUBMITTED"}}),
            ),
            patch.object(nodes, "poll_midjourney_task", return_value=final),
            patch.object(
                nodes,
                "download_video_with_path",
                side_effect=[(videos[0], "one.mp4"), (videos[1], "two.mp4")],
            ),
        ):
            result = self.node._execute_inner(
                operation="midjourney-video",
                prompt="gentle ripples",
                image_url1="https://example.test/start.png",
                video_type="vid_1.1_i2v_480",
                animate_mode="manual",
                motion="high",
                batch_size=2,
                index=-1,
            )
        self.assertIs(result["result"][5], videos[0])
        self.assertIs(result["result"][6], videos[1])
        self.assertEqual(json.loads(result["result"][13]), ["one.mp4", "two.mp4"])

    def test_skip_error_returns_seventeen_outputs(self):
        with patch.object(
            self.node, "_execute_inner", side_effect=RuntimeError("boom")
        ):
            result = self.node.execute(
                operation="midjourney-imagine",
                prompt="paper boat",
                skip_error=True,
            )
        self.assertEqual(len(result["result"]), 17)
        self.assertIn("boom", result["result"][16])
        self.assertIsInstance(result["result"][0], torch.Tensor)
        self.assertEqual(tuple(result["result"][0].shape), (1, 512, 512, 3))
        self.assertIsNotNone(result["result"][5])


if __name__ == "__main__":
    unittest.main()
