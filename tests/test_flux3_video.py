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


CONFIG = {"base_url": "https://example.test", "api_key": "sk-test"}
IMAGE = torch.zeros((1, 8, 8, 3), dtype=torch.float32)


def common(model, **overrides):
    values = {
        "model": model,
        "prompt": "a silver paper airplane crossing a clean studio",
        "seconds": "5",
        "resolution": "hd",
        "ratio": "16:9",
        "draft": False,
        "audio_mode": "api_default",
        "safety_tolerance": "api_default",
        "video_url": "",
        "draft_cache": "",
    }
    values.update(overrides)
    return values


class Flux3VideoTests(unittest.TestCase):
    def test_exact_documented_model_catalog_and_inputs(self):
        self.assertEqual(nodes.FLUX3_VIDEO_MODELS, [
            "flux-3-video-t2v",
            "flux-3-video-i2v",
            "flux-3-video-v2v",
            "flux-3-video-draft-enhance",
            "flux-3-video-global-t2v",
            "flux-3-video-global-i2v",
            "flux-3-video-global-v2v",
            "flux-3-video-global-draft-enhance",
        ])
        inputs = nodes.Flux3Video.INPUT_TYPES()
        self.assertEqual(inputs["required"]["seconds"][0], [
            str(value) for value in range(5, 21)
        ])
        self.assertEqual(inputs["required"]["resolution"][0], ["hd", "fhd"])
        self.assertEqual(inputs["required"]["ratio"][0], [
            "auto", "21:9", "2:1", "16:9", "4:3", "1:1", "3:4", "9:16",
        ])
        self.assertEqual(list(inputs["optional"]), [
            *[f"image{index}" for index in range(1, 11)],
            "input_video",
            "video_url",
            "draft_cache",
            "api_config",
            "skip_error",
        ])

    def test_t2v_payload_forwards_only_selected_optional_controls(self):
        payload = nodes.Flux3Video().build_payload(
            common(
                "flux-3-video-t2v",
                draft=True,
                audio_mode="disabled",
                safety_tolerance="3",
            ),
            {},
        )
        self.assertEqual(payload, {
            "model": "flux-3-video-t2v",
            "prompt": "a silver paper airplane crossing a clean studio",
            "seconds": "5",
            "metadata": {
                "resolution": "hd",
                "ratio": "16:9",
                "draft": True,
                "generate_audio": False,
                "safety_tolerance": 3,
            },
        })

    def test_i2v_payload_accepts_ten_ordered_keyframes(self):
        urls = [f"https://cdn.test/keyframe-{index}.png" for index in range(1, 11)]
        payload = nodes.Flux3Video().build_payload(
            common("flux-3-video-global-i2v"),
            {"images": urls},
        )
        self.assertEqual(payload["images"], urls)
        self.assertNotIn("video_url", payload["metadata"])

    def test_v2v_payload_maps_one_video_url_into_metadata(self):
        payload = nodes.Flux3Video().build_payload(
            common("flux-3-video-v2v"),
            {"video_url": "https://cdn.test/source.mp4"},
        )
        self.assertEqual(
            payload["metadata"]["video_url"],
            "https://cdn.test/source.mp4",
        )
        self.assertNotIn("images", payload)

    def test_draft_enhance_uses_cache_without_prompt(self):
        payload = nodes.Flux3Video().build_payload(
            common(
                "flux-3-video-global-draft-enhance",
                prompt="",
                draft=True,
                draft_cache="cache-for-test",
            ),
            {},
        )
        self.assertEqual(payload, {
            "model": "flux-3-video-global-draft-enhance",
            "seconds": "5",
            "metadata": {
                "resolution": "hd",
                "ratio": "16:9",
                "draft_cache": "cache-for-test",
            },
        })

    def test_strict_validation_requires_mode_specific_inputs(self):
        self.assertIn(
            "prompt is required",
            nodes.Flux3Video.VALIDATE_INPUTS(
                **common("flux-3-video-t2v", prompt=""), strict=True
            ),
        )
        self.assertIn(
            "image1 is required",
            nodes.Flux3Video.VALIDATE_INPUTS(
                **common("flux-3-video-i2v"), strict=True
            ),
        )
        self.assertIn(
            "input_video or video_url",
            nodes.Flux3Video.VALIDATE_INPUTS(
                **common("flux-3-video-v2v"), strict=True
            ),
        )
        self.assertIn(
            "draft_cache is required",
            nodes.Flux3Video.VALIDATE_INPUTS(
                **common("flux-3-video-draft-enhance"), strict=True
            ),
        )

    def test_i2v_collects_all_connected_images_in_slot_order(self):
        progress = []
        kwargs = common("flux-3-video-i2v")
        kwargs.update({"image1": IMAGE, "image2": IMAGE, "image10": IMAGE})
        with (
            patch.object(nodes, "image_to_png_bytes", return_value=b"png"),
            patch.object(
                nodes,
                "upload_media",
                side_effect=[
                    "https://cdn.test/1.png",
                    "https://cdn.test/2.png",
                    "https://cdn.test/10.png",
                ],
            ) as upload,
        ):
            media = nodes.Flux3Video().collect_media(
                kwargs,
                CONFIG,
                progress.append,
            )
        self.assertEqual(upload.call_count, 3)
        self.assertEqual(media["images"], [
            "https://cdn.test/1.png",
            "https://cdn.test/2.png",
            "https://cdn.test/10.png",
        ])
        self.assertEqual(progress[-1], 1.0)

    def test_v2v_collects_local_video_or_uses_direct_url(self):
        with (
            patch.object(nodes, "video_to_bytes", return_value=(b"video", "mp4")),
            patch.object(nodes, "upload_media", return_value="https://cdn.test/source.mp4") as upload,
        ):
            local = nodes.Flux3Video().collect_media(
                common("flux-3-video-v2v", input_video=object()),
                CONFIG,
                lambda _progress: None,
            )
        direct = nodes.Flux3Video().collect_media(
            common("flux-3-video-global-v2v", video_url="https://cdn.test/direct.mp4"),
            CONFIG,
            lambda _progress: None,
        )
        self.assertEqual(upload.call_count, 1)
        self.assertEqual(local, {"video_url": "https://cdn.test/source.mp4"})
        self.assertEqual(direct, {"video_url": "https://cdn.test/direct.mp4"})

    def test_success_and_skip_error_results_preserve_five_output_contract(self):
        node = nodes.Flux3Video()
        success = node._make_success_result(
            object(),
            "https://cdn.test/result.mp4",
            "task-test",
            {"metadata": {"draft_cache": "cache-test"}},
        )
        error = node._make_error_result("test error")
        self.assertEqual(len(success["result"]), 5)
        self.assertEqual(success["result"][2], "cache-test")
        self.assertEqual(len(error["result"]), 5)

    def test_registration_and_concurrent_wrapper(self):
        self.assertIs(nodes.NODE_CLASS_MAPPINGS["Flux_3_Video"], nodes.Flux3Video)
        wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
            "SeedanceConcurrent_Flux_3_Video_Submit"
        ]
        self.assertIs(wrapper.ORIGINAL_NODE_CLASS, nodes.Flux3Video)
        self.assertEqual(wrapper.RETURN_TYPES, (concurrent_nodes.VIDEO_FUTURE_TYPE,))

    def test_every_flux_model_has_a_safe_example_workflow(self):
        found = {}
        for path in (PLUGIN_ROOT / "examples").glob("flux-3-video-*.json"):
            workflow = json.loads(path.read_text(encoding="utf-8"))
            for node in workflow.get("nodes", []):
                if node.get("type") == "Flux_3_Video":
                    model = node.get("widgets_values", [""])[0]
                    if model in nodes.FLUX3_VIDEO_MODELS:
                        found.setdefault(model, (path, workflow, node))
        self.assertEqual(set(found), set(nodes.FLUX3_VIDEO_MODELS))
        for model, (path, workflow, node) in found.items():
            with self.subTest(model=model, workflow=path.name):
                config = next(item for item in workflow["nodes"] if item["type"] == "Seedance_Config")
                self.assertEqual(config["widgets_values"][1], "")
                serialized = json.dumps(workflow, ensure_ascii=False)
                self.assertNotRegex(serialized, r"sk-[A-Za-z0-9]{12,}")
                incoming = [
                    link for link in workflow.get("links", [])
                    if link[3] == node["id"]
                ]
                if model.endswith("-i2v"):
                    self.assertIn("IMAGE", {link[5] for link in incoming})
                elif model.endswith("-v2v"):
                    self.assertIn("VIDEO", {link[5] for link in incoming})
                elif model.endswith("-draft-enhance"):
                    self.assertIn("STRING", {link[5] for link in incoming})


if __name__ == "__main__":
    unittest.main()
