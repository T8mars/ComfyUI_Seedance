import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT.parent))

from ComfyUI_Seedance import nodes


class GenerationSeedControlTests(unittest.TestCase):
    def test_every_generation_node_has_standard_seed_control(self):
        generation_count = 0
        for key, node_class in nodes.NODE_CLASS_MAPPINGS.items():
            inputs = node_class.INPUT_TYPES()
            if "skip_error" not in inputs.get("optional", {}):
                continue
            generation_count += 1
            with self.subTest(node=key):
                required_seed = inputs.get("required", {}).get("seed")
                optional_seed = inputs.get("optional", {}).get("seed")
                self.assertNotEqual(required_seed is None, optional_seed is None)
                seed = required_seed or optional_seed
                self.assertEqual(seed[0], "INT")
                self.assertIs(seed[1].get("control_after_generate"), True)
                self.assertIn("Fixed", seed[1].get("tooltip", ""))
                explicit_cache_only = bool(
                    getattr(node_class, "SEEDANCE_EXPLICIT_CACHE_ONLY_SEED", False)
                )
                self.assertIs(
                    node_class.SEEDANCE_CACHE_ONLY_SEED,
                    explicit_cache_only
                    or (required_seed is None and list(inputs["optional"])[-1] == "seed"),
                )
        self.assertEqual(generation_count, 38)

    def test_config_node_does_not_gain_seed_or_cache_policy(self):
        inputs = nodes.SeedanceConfig.INPUT_TYPES()
        self.assertNotIn("seed", inputs.get("required", {}))
        self.assertNotIn("seed", inputs.get("optional", {}))
        self.assertFalse(hasattr(nodes.SeedanceConfig, "SEEDANCE_CACHE_ONLY_SEED"))

    def test_cache_only_seed_is_removed_before_node_execution(self):
        node = nodes.HailuoH3Video()
        with patch.object(node, "_execute_inner", return_value={"ok": True}) as execute:
            self.assertEqual(node.execute(seed=1234), {"ok": True})
        execute.assert_called_once_with()

    def test_native_seed_still_reaches_supported_payload_path(self):
        node = nodes.SeedanceTextToVideo()
        with patch.object(node, "_execute_inner", return_value={"ok": True}) as execute:
            self.assertEqual(node.execute(seed=1234), {"ok": True})
        execute.assert_called_once_with(seed=1234)

    def test_layer_model_is_appended_after_legacy_cache_seed(self):
        node_class = nodes.SeedreamV5ProLayerDecomposition
        inputs = node_class.INPUT_TYPES()
        self.assertEqual(
            list(inputs["optional"]),
            ["api_config", "skip_error", "seed", "model"],
        )
        self.assertTrue(node_class.SEEDANCE_CACHE_ONLY_SEED)

        node = node_class()
        with patch.object(node, "_execute_inner", return_value={"ok": True}) as execute:
            self.assertEqual(
                node.execute(
                    seed=1234,
                    model="dola-seedream-5.0-pro-layer-decomposition",
                ),
                {"ok": True},
            )
        execute.assert_called_once_with(
            model="dola-seedream-5.0-pro-layer-decomposition"
        )

    def test_installer_preserves_native_seed_position_and_strips_cache_seed(self):
        class NativeSeedProbe:
            FUNCTION = "execute"

            @classmethod
            def INPUT_TYPES(cls):
                return {
                    "required": {
                        "prompt": ("STRING", {}),
                        "seed": ("INT", {"default": -1, "min": -1, "max": 99}),
                        "after": ("BOOLEAN", {"default": False}),
                    },
                    "optional": {"skip_error": ("BOOLEAN", {"default": False})},
                }

            def execute(self, **kwargs):
                return kwargs

        class CacheSeedProbe:
            FUNCTION = "execute"

            @classmethod
            def INPUT_TYPES(cls):
                return {
                    "required": {"prompt": ("STRING", {})},
                    "optional": {"skip_error": ("BOOLEAN", {"default": False})},
                }

            def execute(self, **kwargs):
                return kwargs

        nodes._install_generation_seed_control(NativeSeedProbe)
        nodes._install_generation_seed_control(CacheSeedProbe)

        native = NativeSeedProbe.INPUT_TYPES()
        self.assertEqual(list(native["required"]), ["prompt", "seed", "after"])
        self.assertEqual(native["required"]["seed"][1]["default"], -1)
        self.assertEqual(NativeSeedProbe().execute(seed=7), {"seed": 7})

        cache = CacheSeedProbe.INPUT_TYPES()
        self.assertEqual(list(cache["optional"]), ["skip_error", "seed"])
        self.assertEqual(cache["optional"]["seed"][1]["default"], 0)
        self.assertEqual(CacheSeedProbe().execute(seed=7, prompt="x"), {"prompt": "x"})


if __name__ == "__main__":
    unittest.main()
