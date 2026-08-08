import concurrent.futures
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import torch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT.parent))

from ComfyUI_Seedance import concurrent_nodes
from ComfyUI_Seedance import nodes


class _SkippableImageProbe(nodes.SeedanceImageNodeBase):
    FUNCTION = "execute"
    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("image", "image_url", "task_id", "response")
    CATEGORY = "Seedance/Test"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "index": ("INT", {"default": 0}),
                "fail": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "skip_error": ("BOOLEAN", {"default": False}),
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, fail=False, strict=False, **kwargs):
        return True

    @property
    def _log_prefix(self):
        return "Skip_error_probe"

    def _execute_inner(self, index, fail=False):
        if fail:
            raise RuntimeError("forced worker failure")
        image = torch.full((1, 1, 1, 3), float(index))
        return {"result": (image, "", "", "{}")}


def _finished_handle(index, *, failed=False, skip_error=False):
    future = concurrent.futures.Future()
    if failed:
        future.set_exception(RuntimeError("forced escaped failure"))
    else:
        image = torch.full((1, 1, 1, 3), float(index))
        future.set_result({"result": (image, "", "", "{}")})
    return concurrent_nodes.ConcurrentTaskHandle(
        future=future,
        kind="image",
        original_node_key="SkipErrorProbe",
        primary_output_index=0,
        return_names=("image", "image_url", "task_id", "response"),
        cancel_event=threading.Event(),
        skip_error=skip_error,
    )


class GenerationSkipErrorTests(unittest.TestCase):
    def tearDown(self):
        concurrent_nodes.shutdown_concurrent_pools(wait=True)

    def test_every_generation_node_exposes_optional_disabled_skip_error(self):
        config_inputs = nodes.SeedanceConfig.INPUT_TYPES()
        self.assertNotIn("skip_error", config_inputs.get("required", {}))
        self.assertNotIn("skip_error", config_inputs.get("optional", {}))

        for key, node_class in nodes.NODE_CLASS_MAPPINGS.items():
            if key == "Seedance_Config":
                continue
            with self.subTest(node=key):
                inputs = node_class.INPUT_TYPES()
                self.assertNotIn("skip_error", inputs.get("required", {}))
                skip_spec = inputs.get("optional", {}).get("skip_error")
                self.assertIsNotNone(skip_spec)
                self.assertIs(skip_spec[1].get("default"), False)

    def test_image_generation_nodes_keep_raise_default_and_return_typed_placeholder(self):
        for key in concurrent_nodes.PURE_IMAGE_NODE_KEYS:
            node = nodes.NODE_CLASS_MAPPINGS[key]()
            with self.subTest(node=key):
                with patch.object(
                    node,
                    "_execute_inner",
                    side_effect=RuntimeError("forced image failure"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "forced image failure"):
                        node.execute()

                with patch.object(
                    node,
                    "_execute_inner",
                    side_effect=RuntimeError("forced image failure"),
                ):
                    result = node.execute(skip_error=True)

                self.assertEqual(set(result), {"ui", "result"})
                self.assertEqual(len(result["result"]), 4)
                image, image_url, task_id, response = result["result"]
                self.assertTrue(torch.is_tensor(image))
                self.assertEqual(tuple(image.shape), (1, 512, 512, 3))
                self.assertEqual(image_url, "")
                self.assertEqual(task_id, "")
                self.assertIn("forced image failure", json.loads(response)["error"])

    def test_ten_way_submit_continues_when_one_node_skips_its_error(self):
        submit_class = concurrent_nodes._make_submit_class(
            "SkipErrorProbe",
            _SkippableImageProbe,
            "image",
        )
        handles = [
            submit_class().submit(
                index=index,
                fail=index == 4,
                skip_error=True,
            )[0]
            for index in range(10)
        ]
        kwargs = {
            f"future_{index + 1}": handle
            for index, handle in enumerate(handles)
        }

        result = concurrent_nodes.SeedanceConcurrentImageAwait().wait_all(
            failure_mode="raise",
            **kwargs,
        )
        summary = json.loads(result[-1])

        self.assertEqual(summary["connected"], 10)
        self.assertEqual(summary["completed"], 10)
        self.assertEqual(summary["failed"], 0)
        for index in range(10):
            if index == 4:
                self.assertEqual(tuple(result[index].shape), (1, 512, 512, 3))
            else:
                self.assertEqual(float(result[index][0, 0, 0, 0]), float(index))
        failed_response = json.loads(handles[4].future.result()["result"][3])
        self.assertIn("forced worker failure", failed_response["error"])

    def test_skip_enabled_preflight_failure_becomes_isolated_future(self):
        class PreflightProbe(_SkippableImageProbe):
            @classmethod
            def VALIDATE_INPUTS(cls, fail=False, strict=False, **kwargs):
                if strict and fail:
                    return "forced validation failure"
                return True

        submit_class = concurrent_nodes._make_submit_class(
            "PreflightProbe",
            PreflightProbe,
            "image",
        )
        handle = submit_class().submit(index=0, fail=True, skip_error=True)[0]
        self.assertTrue(handle.future.done())
        self.assertTrue(handle.skip_error)

        result = concurrent_nodes.SeedanceConcurrentImageAwait().wait_all(
            failure_mode="raise",
            future_1=handle,
        )
        summary = json.loads(result[-1])
        self.assertEqual(summary["failed"], 1)
        self.assertTrue(summary["slots"][0]["skipped"])
        self.assertEqual(tuple(result[0].shape), (1, 512, 512, 3))

    def test_escaped_concurrent_failure_only_replaces_skip_enabled_slot(self):
        handles = [
            _finished_handle(
                index,
                failed=index == 4,
                skip_error=index == 4,
            )
            for index in range(10)
        ]
        result = concurrent_nodes.SeedanceConcurrentImageAwait().wait_all(
            failure_mode="raise",
            **{
                f"future_{index + 1}": handle
                for index, handle in enumerate(handles)
            },
        )
        summary = json.loads(result[-1])

        self.assertEqual(summary["completed"], 9)
        self.assertEqual(summary["failed"], 1)
        self.assertTrue(summary["slots"][4]["skipped"])
        for index in range(10):
            if index != 4:
                self.assertEqual(float(result[index][0, 0, 0, 0]), float(index))


if __name__ == "__main__":
    unittest.main()
