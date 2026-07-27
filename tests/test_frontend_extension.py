import json
import re
import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT.parent))

import ComfyUI_Seedance


class FrontendExtensionTests(unittest.TestCase):
    def test_package_exposes_web_directory(self):
        self.assertEqual(ComfyUI_Seedance.WEB_DIRECTORY, "./web")

    def test_api_key_button_policy_is_generic_and_safe(self):
        source = (
            PLUGIN_ROOT / "web" / "js" / "seedance_api_key_link.js"
        ).read_text(encoding="utf-8")

        required_fragments = (
            'const PLUGIN_MODULE = "custom_nodes.ComfyUI_Seedance"',
            'const API_KEY_BUTTON_LABEL = "获取平价版APIKEY"',
            'const API_KEY_SIGNUP_URL = "https://api.seedance.nz/sign-up?aff=5f4w"',
            'new Set(["Seedance_Config"])',
            "beforeRegisterNodeDef(nodeType, nodeData)",
            "originalOnNodeCreated?.apply(this, arguments)",
            'this.addWidget("button", API_KEY_BUTTON_LABEL',
            'window.open(API_KEY_SIGNUP_URL, "_blank", "noopener,noreferrer")',
            "button.serialize = false",
            "button.seedanceApiKeyLink = true",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)
        self.assertLess(
            source.index("originalOnNodeCreated?.apply(this, arguments)"),
            source.index('this.addWidget("button", API_KEY_BUTTON_LABEL'),
        )

    def test_current_node_registration_keys_remain_compatible(self):
        node_names = set(ComfyUI_Seedance.NODE_CLASS_MAPPINGS)
        expected = {
            "Seedance_Config",
            "Seedance_TextToVideo",
            "Seedance_ImageToVideo",
            "Seedance_MultimodalVideo",
            "Seedream_V5_Pro_Image",
            "Zhenzhen_Image_G2",
            "Zhenzhen_Image_GK_V15",
            "Zhenzhen_Image_NB",
            "Zhenzhen_Video_G_Omni_Flash",
            "Zhenzhen_Video_GK_V15",
            "Zhenzhen_Video_V31",
            "HappyHorse_1_1_Video",
            "Wan_2_7_Spicy_I2V",
            "Kling_Video",
            "Kling_Edit_Video",
            "Hailuo_2_3_Video",
            "Vidu_Q3_Video",
            "Vidu_Q3_ShortPlay",
            "Zhenzhen_Upscaler_Video",
            "Doubao_Seed_Audio",
            "Whisper_Transcription",
            "Suno_Music",
            "Midjourney_Multi_Action",
        }
        self.assertTrue(expected.issubset(node_names))

    def test_existing_example_workflows_keep_registered_node_types(self):
        mappings = ComfyUI_Seedance.NODE_CLASS_MAPPINGS
        for workflow_path in sorted((PLUGIN_ROOT / "examples").glob("*.json")):
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            for node in workflow.get("nodes", []):
                node_type = str(node.get("type", ""))
                if node_type.startswith(
                    ("Seedance_", "Seedream_", "HappyHorse_", "Wan_", "Kling_", "Hailuo_", "Vidu_", "Zhenzhen_", "Doubao_", "Whisper_", "Suno_", "Midjourney_")
                ):
                    with self.subTest(workflow=workflow_path.name, node=node_type):
                        self.assertIn(node_type, mappings)

    def test_suno_action_ui_covers_every_operation_and_preserves_links(self):
        source = (
            PLUGIN_ROOT / "web" / "js" / "suno_action_ui.js"
        ).read_text(encoding="utf-8")

        required_fragments = (
            'const SUNO_NODE_NAME = "Suno_Music"',
            "const ACTION_FIELDS = {",
            "if (nodeData.name !== SUNO_NODE_NAME)",
            "setWidgetVisible(widget, fields.has(widget.name))",
            "String(widget.type ?? \"\").startsWith(CONVERTED_WIDGET_PREFIX)",
            'Object.prototype.hasOwnProperty.call(widget, "origType")',
            "if (isConvertedInput)",
            "const connected = input.link != null",
            "input.hidden = !fields.has(input.name) && !connected",
            "originalOnConfigure?.apply(this, arguments)",
            "originalOnConnectionsChange?.apply(this, arguments)",
            "refreshSunoNode(this)",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)

        self.assertLess(
            source.index("if (isConvertedInput)"),
            source.index("if (!widget.seedanceSunoOriginal)"),
        )
        operation_keys = set(
            re.findall(r'^\s{4}"(suno-[a-z0-9-]+)": \[', source, re.MULTILINE)
        )
        from ComfyUI_Seedance.nodes import SUNO_OPERATIONS

        self.assertEqual(operation_keys, set(SUNO_OPERATIONS))

    def test_midjourney_action_ui_covers_every_operation_and_preserves_links(self):
        source = (
            PLUGIN_ROOT / "web" / "js" / "midjourney_action_ui.js"
        ).read_text(encoding="utf-8")

        required_fragments = (
            'const MIDJOURNEY_NODE_NAME = "Midjourney_Multi_Action"',
            "const ACTION_FIELDS = {",
            "if (nodeData.name !== MIDJOURNEY_NODE_NAME)",
            "setWidgetVisible(widget, fields.has(widget.name))",
            "String(widget?.type ?? \"\").startsWith(CONVERTED_WIDGET_PREFIX)",
            'Object.prototype.hasOwnProperty.call(widget ?? {}, "origType")',
            "const connected = input.link != null",
            "input.hidden = !fields.has(input.name) && !connected",
            'wrapRefreshWidget(this, "operation")',
            'wrapRefreshWidget(this, "modal_mode")',
            'wrapRefreshWidget(this, "size")',
            "normalizeFriendlyWidgets(this)",
            "migrateLegacyWidgetValues(arguments[0])",
            "values.splice(CUSTOM_SIZE_WIDGET_INDEX, 0, \"\")",
            'fields.delete("custom_size")',
            'widget.value = "custom"',
            "setComboValues(widget, SIZE_OPTIONS)",
            "originalOnConfigure?.apply(this, arguments)",
            "originalOnConnectionsChange?.apply(this, arguments)",
            "refreshMidjourneyNode(this)",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)

        operation_keys = set(
            re.findall(
                r'^\s{4}"(midjourney-[a-z0-9-]+)": \[',
                source,
                re.MULTILINE,
            )
        )
        from ComfyUI_Seedance.nodes import MIDJOURNEY_OPERATIONS

        self.assertEqual(operation_keys, set(MIDJOURNEY_OPERATIONS))
        label_pairs = dict(re.findall(
            r'^\s{4}"(midjourney-[a-z0-9-]+)": "([^"]+)",$',
            source,
            re.MULTILINE,
        ))
        from ComfyUI_Seedance.nodes import MIDJOURNEY_OPERATION_LABELS

        self.assertEqual(label_pairs, MIDJOURNEY_OPERATION_LABELS)

    def test_zhenzhen_model_ui_enforces_model_specific_controls(self):
        source = (
            PLUGIN_ROOT / "web" / "js" / "zhenzhen_model_ui.js"
        ).read_text(encoding="utf-8")
        required_fragments = (
            'const G2_NODE_NAME = "Zhenzhen_Image_G2"',
            'const NB_NODE_NAME = "Zhenzhen_Image_NB"',
            'const V31_NODE_NAME = "Zhenzhen_Video_V31"',
            'const LOWPRICE_MODEL = "zhenzhen-image-g-v2-lowprice"',
            'const CONVERTED_WIDGET_PREFIX = "converted-widget"',
            'String(widget.type ?? "").startsWith(CONVERTED_WIDGET_PREFIX)',
            'Object.prototype.hasOwnProperty.call(widget, "origType")',
            "function refreshG2Node(node)",
            'isLowprice ? ["1k", "2k", "4k"] : ["1k"]',
            'setWidgetVisible(widgetByName(node, "ratio"), !isLowprice)',
            'setWidgetVisible(widgetByName(node, "size"), isLowprice)',
            'widgetByName(node, "custom_size")',
            'String(widgetByName(node, "size")?.value) === "custom"',
            'setWidgetVisible(widgetByName(node, "n"), isLowprice)',
            "normalizeLowpriceSizeWidgets(node)",
            "migrateLegacyG2WidgetValues(arguments[0])",
            'wrapRefresh(this, refresh, "size")',
            'values.splice(G2_CUSTOM_SIZE_WIDGET_INDEX, 0, "")',
            'model === "zhenzhen-image-g2-i2i" && index <= 10',
            '"zhenzhen-image-nb-flash": {',
            '"zhenzhen-image-nb-2": {',
            '"zhenzhen-image-nb-2-lite": {',
            '"zhenzhen-image-nb-pro": {',
            'model !== "zhenzhen-video-v31-lite"',
            'model === "zhenzhen-video-v31-quality" && input.name === "image3"',
            "input.hidden = !allowed && input.link == null",
            "originalOnConfigure?.apply(this, arguments)",
            "originalOnConnectionsChange?.apply(this, arguments)",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)

    def test_zhenzhen_g2_and_lowprice_workflows_match_model_contracts(self):
        workflow_names = (
            "zhenzhen-image-g2文生图.json",
            "zhenzhen-image-g2图像编辑.json",
            "zhenzhen-image-g-v2-lowprice文生图.json",
            "zhenzhen-image-g-v2-lowprice图像编辑.json",
        )
        for workflow_name in workflow_names:
            workflow = json.loads(
                (PLUGIN_ROOT / "examples" / workflow_name).read_text(encoding="utf-8")
            )
            node = next(
                item for item in workflow["nodes"]
                if item["type"] == "Zhenzhen_Image_G2"
            )
            self.assertEqual(
                [item["name"] for item in node["inputs"]],
                [f"image{index}" for index in range(1, 17)] + ["api_config"],
            )
            config_link = next(
                link for link in workflow["links"]
                if link[3] == node["id"] and link[5] == "SEEDANCE_CONFIG"
            )
            self.assertEqual(config_link[4], 16)
            self.assertEqual(len(node["widgets_values"]), 7)
            model, _, resolution, ratio, size, custom_size, n = node["widgets_values"]
            self.assertEqual(size, "1:1" if "图像编辑" in workflow_name else "16:9")
            self.assertEqual(custom_size, "")
            self.assertEqual(n, 1)
            if model == "zhenzhen-image-g-v2-lowprice":
                self.assertEqual(resolution, "2k")
                self.assertEqual(ratio, "adaptive")
            else:
                self.assertEqual(resolution, "1k")

    def test_nano_banana_and_v31_lite_workflows_are_complete(self):
        expected_nb = {
            f"{model}{mode}.json"
            for model in (
                "zhenzhen-image-nb-flash",
                "zhenzhen-image-nb-2",
                "zhenzhen-image-nb-2-lite",
                "zhenzhen-image-nb-pro",
            )
            for mode in ("文生图", "图像编辑")
        }
        actual_nb = {
            path.name
            for path in (PLUGIN_ROOT / "examples").glob("zhenzhen-image-nb-*.json")
        }
        self.assertEqual(actual_nb, expected_nb)

        for workflow_name in sorted(expected_nb):
            workflow = json.loads(
                (PLUGIN_ROOT / "examples" / workflow_name).read_text(encoding="utf-8")
            )
            node = next(
                item for item in workflow["nodes"]
                if item["type"] == "Zhenzhen_Image_NB"
            )
            expected_model = workflow_name.removesuffix("文生图.json").removesuffix("图像编辑.json")
            self.assertEqual(node["widgets_values"][0], expected_model)
            self.assertEqual(
                [item["name"] for item in node["inputs"]],
                [f"image{index}" for index in range(1, 15)] + ["api_config"],
            )
            config_link = next(
                link for link in workflow["links"]
                if link[3] == node["id"] and link[5] == "SEEDANCE_CONFIG"
            )
            self.assertEqual(config_link[4], 14)
            image_links = [
                link for link in workflow["links"]
                if link[3] == node["id"] and link[5] == "IMAGE"
            ]
            self.assertEqual(len(image_links), 1 if "图像编辑" in workflow_name else 0)
            if image_links:
                self.assertEqual(image_links[0][4], 0)

        lite_path = PLUGIN_ROOT / "examples" / "zhenzhen-video-v31-lite文生视频.json"
        workflow = json.loads(lite_path.read_text(encoding="utf-8"))
        node = next(
            item for item in workflow["nodes"]
            if item["type"] == "Zhenzhen_Video_V31"
        )
        self.assertEqual(node["widgets_values"][:5], [
            "zhenzhen-video-v31-lite",
            "a paper airplane gliding through warm sunrise clouds, smooth cinematic camera movement",
            "8",
            "720p",
            "16:9",
        ])
        self.assertEqual(
            [item["name"] for item in node["inputs"]],
            ["image1", "image2", "image3", "api_config"],
        )

        for workflow_path in sorted(
            (PLUGIN_ROOT / "examples").glob("zhenzhen-video-v31-*.json")
        ):
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            node = next(
                item for item in workflow["nodes"]
                if item["type"] == "Zhenzhen_Video_V31"
            )
            self.assertEqual(node["widgets_values"][2], "8")
            self.assertEqual(
                [item["name"] for item in node["inputs"]],
                ["image1", "image2", "image3", "api_config"],
            )
            config_link = next(
                link for link in workflow["links"]
                if link[3] == node["id"] and link[5] == "SEEDANCE_CONFIG"
            )
            self.assertEqual(config_link[4], 3)

    def test_example_workflows_do_not_store_runtime_secrets_or_results(self):
        forbidden_patterns = {
            "api_key": re.compile(r"sk-[A-Za-z0-9_-]{16,}", re.IGNORECASE),
            "task_id": re.compile(r"task_[A-Za-z0-9]{16,}", re.IGNORECASE),
            "signed_url": re.compile(
                r"(?:q-signature|x-amz-signature|x-tos-signature)=",
                re.IGNORECASE,
            ),
        }
        for workflow_path in sorted((PLUGIN_ROOT / "examples").glob("*.json")):
            source = workflow_path.read_text(encoding="utf-8")
            workflow = json.loads(source)
            for name, pattern in forbidden_patterns.items():
                with self.subTest(workflow=workflow_path.name, pattern=name):
                    self.assertIsNone(pattern.search(source))
            for node in workflow.get("nodes", []):
                if node.get("type") != "easy showAnything":
                    continue
                for value in node.get("widgets_values", []):
                    with self.subTest(workflow=workflow_path.name, node=node.get("id")):
                        self.assertFalse(value)


if __name__ == "__main__":
    unittest.main()
