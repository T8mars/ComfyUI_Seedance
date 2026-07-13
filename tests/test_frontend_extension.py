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
            "HappyHorse_1_1_Video",
            "Doubao_Seed_Audio",
        }
        self.assertTrue(expected.issubset(node_names))

    def test_existing_example_workflows_keep_registered_node_types(self):
        mappings = ComfyUI_Seedance.NODE_CLASS_MAPPINGS
        for workflow_path in sorted((PLUGIN_ROOT / "examples").glob("*.json")):
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            for node in workflow.get("nodes", []):
                node_type = str(node.get("type", ""))
                if node_type.startswith(
                    ("Seedance_", "Seedream_", "HappyHorse_", "Doubao_")
                ):
                    with self.subTest(workflow=workflow_path.name, node=node_type):
                        self.assertIn(node_type, mappings)

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
