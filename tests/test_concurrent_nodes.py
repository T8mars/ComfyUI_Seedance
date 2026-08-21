import concurrent.futures
import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import torch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT.parent))

import ComfyUI_Seedance as plugin
from ComfyUI_Seedance import concurrent_nodes
from ComfyUI_Seedance import nodes
from ComfyUI_Seedance.core import config
from ComfyUI_Seedance.core import runtime


class _SmallImageAwait(concurrent_nodes._ConcurrentAwaitBase):
    KIND = "image"
    SLOT_COUNT = 2
    FUTURE_TYPE = concurrent_nodes.IMAGE_FUTURE_TYPE
    MEDIA_TYPE = "IMAGE"
    RETURN_TYPES = ("IMAGE", "IMAGE", "STRING")
    RETURN_NAMES = ("image_1", "image_2", "status_json")

    def _placeholder(self, message):
        return torch.full((1, 1, 1, 3), -1.0)


def _handle(future, kind="image", source="Fake", index=0, names=()):
    return concurrent_nodes.ConcurrentTaskHandle(
        future=future,
        kind=kind,
        original_node_key=source,
        primary_output_index=index,
        return_names=tuple(names),
        cancel_event=threading.Event(),
    )


class ConcurrentNodeTests(unittest.TestCase):
    def tearDown(self):
        concurrent_nodes.shutdown_concurrent_pools(wait=True)

    def test_package_keeps_base_mapping_unchanged_and_adds_concurrent_nodes(self):
        self.assertEqual(len(nodes.NODE_CLASS_MAPPINGS), 39)
        self.assertEqual(len(concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS), 32)
        self.assertEqual(len(plugin.NODE_CLASS_MAPPINGS), 71)
        for key, value in nodes.NODE_CLASS_MAPPINGS.items():
            self.assertIs(plugin.NODE_CLASS_MAPPINGS[key], value)

    def test_config_rejects_prompt_text_in_api_key_before_http(self):
        with self.assertRaisesRegex(RuntimeError, "中文提示词"):
            nodes.SeedanceConfig().build(
                "https://api.seedance.nz",
                "女人在跳舞",
            )

    def test_config_rejects_wrong_prefix_from_settings(self):
        with self.assertRaisesRegex(RuntimeError, "sk-"):
            config.get_config([{
                "base_url": "https://api.seedance.nz",
                "api_key": "not-a-seedance-key",
            }])

    def test_config_accepts_trimmed_ascii_key(self):
        result = nodes.SeedanceConfig().build(
            "https://api.seedance.nz",
            "  sk-test  ",
        )
        self.assertEqual(result[0][0]["api_key"], "sk-test")

    def test_fixed_collector_contract_does_not_depend_on_worker_environment(self):
        with patch.dict(
            os.environ,
            {
                concurrent_nodes.IMAGE_ENV_NAME: "2",
                concurrent_nodes.VIDEO_ENV_NAME: "3",
            },
        ):
            self.assertEqual(
                concurrent_nodes._worker_count(
                    concurrent_nodes.IMAGE_ENV_NAME,
                    concurrent_nodes.IMAGE_SLOT_COUNT,
                    concurrent_nodes.IMAGE_SLOT_COUNT,
                ),
                2,
            )
            self.assertEqual(
                concurrent_nodes._worker_count(
                    concurrent_nodes.VIDEO_ENV_NAME,
                    concurrent_nodes.VIDEO_SLOT_COUNT,
                    concurrent_nodes.VIDEO_SLOT_COUNT,
                ),
                3,
            )
        image_inputs = concurrent_nodes.SeedanceConcurrentImageAwait.INPUT_TYPES()
        video_inputs = concurrent_nodes.SeedanceConcurrentVideoAwait.INPUT_TYPES()
        self.assertIn("future_30", image_inputs["optional"])
        self.assertIn("future_10", video_inputs["optional"])
        self.assertEqual(
            len(concurrent_nodes.SeedanceConcurrentImageAwait.RETURN_TYPES), 31
        )
        self.assertEqual(
            len(concurrent_nodes.SeedanceConcurrentVideoAwait.RETURN_TYPES), 11
        )

    def test_generated_wrappers_preserve_inputs_without_queue_validator_inheritance(self):
        for original_key in (
            *concurrent_nodes.PURE_IMAGE_NODE_KEYS,
            *concurrent_nodes.PURE_VIDEO_NODE_KEYS,
        ):
            wrapper_key = f"SeedanceConcurrent_{original_key}_Submit"
            wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[wrapper_key]
            original = nodes.NODE_CLASS_MAPPINGS[original_key]
            self.assertFalse(issubclass(wrapper, original))
            self.assertIs(wrapper.ORIGINAL_NODE_CLASS, original)
            self.assertEqual(wrapper.ORIGINAL_NODE_KEY, original_key)
            self.assertEqual(wrapper.INPUT_TYPES(), original.INPUT_TYPES())
            self.assertFalse(hasattr(wrapper, "VALIDATE_INPUTS"))
            self.assertFalse(wrapper.OUTPUT_NODE)
            self.assertEqual(wrapper.RETURN_NAMES, ("future",))
            self.assertFalse(hasattr(wrapper, "IS_CHANGED"))
            seed = (
                wrapper.INPUT_TYPES().get("required", {}).get("seed")
                or wrapper.INPUT_TYPES().get("optional", {}).get("seed")
            )
            self.assertIs(seed[1].get("control_after_generate"), True)

    def test_await_nodes_remain_live_while_submit_nodes_are_cacheable(self):
        self.assertTrue(hasattr(concurrent_nodes.SeedanceConcurrentImageAwait, "IS_CHANGED"))
        self.assertTrue(hasattr(concurrent_nodes.SeedanceConcurrentVideoAwait, "IS_CHANGED"))
        self.assertTrue(
            concurrent_nodes.SeedanceConcurrentImageAwait.IS_CHANGED()
            != concurrent_nodes.SeedanceConcurrentImageAwait.IS_CHANGED()
        )
        self.assertTrue(
            concurrent_nodes.SeedanceConcurrentVideoAwait.IS_CHANGED()
            != concurrent_nodes.SeedanceConcurrentVideoAwait.IS_CHANGED()
        )

    def test_lowprice_concurrent_wrapper_rejects_short_prompt(self):
        wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
            "SeedanceConcurrent_Zhenzhen_Image_G2_Submit"
        ]
        with patch.object(concurrent_nodes, "_submit_original") as submit:
            with self.assertRaisesRegex(
                concurrent_nodes.SeedanceAPIError,
                "5 to 5000",
            ):
                wrapper().submit(
                    model=nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL,
                    prompt="女人唱歌",
                    resolution="1k",
                    ratio="adaptive",
                    size="1:1",
                    custom_size="",
                    n=1,
                )
        submit.assert_not_called()

        handle = object()
        with patch.object(
            concurrent_nodes,
            "_submit_original",
            return_value=handle,
        ) as submit:
            result = wrapper().submit(
                model=nodes.ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL,
                prompt="女人正在舞台上唱歌",
                resolution="1k",
                ratio="adaptive",
                size="1:1",
                custom_size="",
                n=1,
            )
        self.assertIs(result[0], handle)
        submit.assert_called_once()

    def test_midjourney_image_and_video_wrappers_have_separate_contracts(self):
        image_wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
            "SeedanceConcurrent_Midjourney_Image_Submit"
        ]
        video_wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
            "SeedanceConcurrent_Midjourney_Video_Submit"
        ]
        image_choices = image_wrapper.INPUT_TYPES()["required"]["operation"][0]
        video_choices = video_wrapper.INPUT_TYPES()["required"]["operation"][0]

        self.assertEqual(image_wrapper.CONCURRENT_KIND, "image")
        self.assertEqual(image_wrapper.PRIMARY_OUTPUT_INDEX, 0)
        self.assertNotIn("midjourney-video", image_choices)
        self.assertNotIn("midjourney-describe", image_choices)
        self.assertNotIn("midjourney-inpaint", image_choices)
        self.assertEqual(video_wrapper.CONCURRENT_KIND, "video")
        self.assertEqual(video_wrapper.PRIMARY_OUTPUT_INDEX, 5)
        self.assertEqual(
            video_choices,
            [
                nodes.MIDJOURNEY_OPERATION_LABELS["midjourney-video"],
                "midjourney-video",
            ],
        )

    def test_image_30_and_video_10_execute_at_the_same_time(self):
        image_active = 0
        video_active = 0
        image_peak = 0
        video_peak = 0
        lock = threading.Lock()
        all_started = threading.Event()
        release = threading.Event()

        def mark_started(kind):
            nonlocal image_active, video_active, image_peak, video_peak
            with lock:
                if kind == "image":
                    image_active += 1
                    image_peak = max(image_peak, image_active)
                else:
                    video_active += 1
                    video_peak = max(video_peak, video_active)
                if image_active == 30 and video_active == 10:
                    all_started.set()

        def mark_finished(kind):
            nonlocal image_active, video_active
            with lock:
                if kind == "image":
                    image_active -= 1
                else:
                    video_active -= 1

        class FakeImageNode:
            FUNCTION = "execute"
            RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING")
            RETURN_NAMES = ("image", "image_url", "task_id", "response")

            def execute(self, index):
                mark_started("image")
                if not release.wait(10):
                    raise TimeoutError("image stress release timed out")
                mark_finished("image")
                tensor = torch.full((1, 1, 1, 3), float(index))
                return {"result": (tensor, "", "", "{}")}

        class FakeVideoNode:
            FUNCTION = "execute"
            RETURN_TYPES = ("VIDEO", "STRING", "STRING", "STRING")
            RETURN_NAMES = ("video", "video_url", "task_id", "response")

            def execute(self, index):
                mark_started("video")
                if not release.wait(10):
                    raise TimeoutError("video stress release timed out")
                mark_finished("video")
                return {"result": (f"video-{index}", "", "", "{}")}

        image_handles = [
            concurrent_nodes._submit_original(
                FakeImageNode, "FakeImage", "image", 0, {"index": index}
            )
            for index in range(1, 31)
        ]
        video_handles = [
            concurrent_nodes._submit_original(
                FakeVideoNode, "FakeVideo", "video", 0, {"index": index}
            )
            for index in range(1, 11)
        ]

        self.assertTrue(all_started.wait(10), "30 image + 10 video workers did not overlap")
        self.assertEqual(image_peak, 30)
        self.assertEqual(video_peak, 10)
        release.set()

        image_kwargs = {
            f"future_{index}": handle
            for index, handle in enumerate(image_handles, 1)
        }
        video_kwargs = {
            f"future_{index}": handle
            for index, handle in enumerate(video_handles, 1)
        }
        image_result = concurrent_nodes.SeedanceConcurrentImageAwait().wait_all(
            failure_mode="raise", **image_kwargs
        )
        video_result = concurrent_nodes.SeedanceConcurrentVideoAwait().wait_all(
            failure_mode="raise", **video_kwargs
        )

        for index in range(30):
            self.assertEqual(float(image_result[index][0, 0, 0, 0]), index + 1)
        self.assertEqual(video_result[:10], tuple(f"video-{i}" for i in range(1, 11)))
        self.assertEqual(json.loads(image_result[-1])["completed"], 30)
        self.assertEqual(json.loads(video_result[-1])["completed"], 10)

    def test_results_keep_slot_order_when_futures_finish_out_of_order(self):
        futures = [concurrent.futures.Future() for _ in range(2)]
        futures[1].set_result((torch.full((1, 1, 1, 3), 2.0),))
        futures[0].set_result((torch.full((1, 1, 1, 3), 1.0),))
        result = _SmallImageAwait().wait_all(
            failure_mode="raise",
            future_1=_handle(futures[0]),
            future_2=_handle(futures[1]),
        )
        self.assertEqual(float(result[0][0, 0, 0, 0]), 1.0)
        self.assertEqual(float(result[1][0, 0, 0, 0]), 2.0)

    def test_failure_mode_placeholder_keeps_other_slots(self):
        success = concurrent.futures.Future()
        failed = concurrent.futures.Future()
        success.set_result((torch.ones((1, 1, 1, 3)),))
        failed.set_exception(RuntimeError("request failed at https://example.test/task_abc123"))

        result = _SmallImageAwait().wait_all(
            failure_mode="placeholder",
            future_1=_handle(success),
            future_2=_handle(failed),
        )
        summary = json.loads(result[-1])
        self.assertTrue(torch.equal(result[0], torch.ones((1, 1, 1, 3))))
        self.assertEqual(float(result[1][0, 0, 0, 0]), -1.0)
        self.assertEqual(summary["completed"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertNotIn("https://", result[-1])
        self.assertNotIn("task_abc123", result[-1])

    def test_failure_mode_raise_propagates_slot_and_cancels_pending(self):
        failed = concurrent.futures.Future()
        pending = concurrent.futures.Future()
        failed.set_exception(ValueError("bad input"))
        pending_handle = _handle(pending)
        with self.assertRaisesRegex(RuntimeError, "slot 1 failed"):
            _SmallImageAwait().wait_all(
                failure_mode="raise",
                future_1=_handle(failed),
                future_2=pending_handle,
            )
        self.assertTrue(pending_handle.cancel_event.is_set())
        self.assertTrue(pending.cancelled())

    def test_cooperative_sleep_stops_after_cancel(self):
        cancel_event = threading.Event()
        stopped = threading.Event()

        def worker():
            try:
                with runtime.concurrent_worker_context(cancel_event):
                    runtime.cooperative_sleep(10)
            except runtime.ConcurrentTaskCancelled:
                stopped.set()

        thread = threading.Thread(target=worker)
        thread.start()
        time.sleep(0.05)
        cancel_event.set()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(stopped.is_set())

    def test_progress_is_suppressed_only_inside_concurrent_worker(self):
        self.assertFalse(runtime.progress_is_suppressed())
        with runtime.concurrent_worker_context(threading.Event()):
            self.assertTrue(runtime.progress_is_suppressed())
        self.assertFalse(runtime.progress_is_suppressed())

    def test_concurrent_worker_progress_is_captured_without_child_ui_events(self):
        state = concurrent_nodes.ConcurrentProgressState()
        with runtime.concurrent_worker_context(
            threading.Event(),
            state.update,
        ):
            progress = nodes._make_progress_bar(100)
            progress.update_absolute(95, 100)

        self.assertAlmostEqual(state.snapshot(), 0.95)
        self.assertIsNone(runtime.current_progress_callback())

    def test_await_node_aggregates_progress_from_pending_workers(self):
        first = concurrent.futures.Future()
        second = concurrent.futures.Future()
        first_handle = _handle(first)
        second_handle = _handle(second)
        first_handle.progress_state.update(20, 100)
        second_handle.progress_state.update(80, 100)
        pbar = MagicMock()

        def complete():
            first.set_result((torch.ones((1, 1, 1, 3)),))
            second.set_result((torch.ones((1, 1, 1, 3)),))

        timer = threading.Timer(0.05, complete)
        timer.start()
        try:
            with patch.object(nodes, "_make_progress_bar", return_value=pbar):
                _SmallImageAwait().wait_all(
                    future_1=first_handle,
                    future_2=second_handle,
                )
        finally:
            timer.cancel()

        updates = [call.args[0] for call in pbar.update_absolute.call_args_list]
        self.assertIn(500, updates)
        self.assertEqual(updates[-1], 1000)

    def test_concurrent_example_workflows_are_complete_and_safe(self):
        cases = {
            "并发图片2路最小验证.json": ("image", 2),
            "并发视频2路最小验证.json": ("video", 2),
            "并发图片30路示例.json": ("image", 30),
            "并发视频10路示例.json": ("video", 10),
        }
        for filename, (kind, expected_count) in cases.items():
            with self.subTest(filename=filename):
                path = PACKAGE_ROOT / "examples" / filename
                text = path.read_text(encoding="utf-8")
                workflow = json.loads(text)
                config = next(
                    node for node in workflow["nodes"]
                    if node["type"] == "Seedance_Config"
                )
                submit_nodes = [
                    node for node in workflow["nodes"]
                    if node["type"].startswith("SeedanceConcurrent_")
                    and node["type"].endswith("_Submit")
                ]
                await_type = (
                    "SeedanceConcurrent_Image_Await"
                    if kind == "image"
                    else "SeedanceConcurrent_Video_Await"
                )
                await_node = next(
                    node for node in workflow["nodes"]
                    if node["type"] == await_type
                )
                connected = [
                    item for item in await_node["inputs"]
                    if item.get("link") is not None
                ]

                self.assertEqual(config["widgets_values"][1], "")
                self.assertEqual(len(submit_nodes), expected_count)
                self.assertEqual(len(connected), expected_count)
                self.assertEqual(await_node["widgets_values"], ["raise"])
                self.assertNotRegex(text, r"sk-[A-Za-z0-9]{12,}")
                self.assertNotIn("X-Amz-Signature", text)
                self.assertNotIn("X-Tos-Signature", text)


if __name__ == "__main__":
    unittest.main()
