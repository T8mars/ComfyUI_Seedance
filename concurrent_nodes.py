"""Optional submit/collect nodes for concurrent image and video generation."""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import copy
import inspect
import json
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Tuple

import torch

from . import nodes as _nodes
from .core.client import SeedanceAPIError
from .core.media import make_error_image, make_error_video
from .core.runtime import check_cancelled, concurrent_worker_context


IMAGE_FUTURE_TYPE = "SEEDANCE_IMAGE_FUTURE"
VIDEO_FUTURE_TYPE = "SEEDANCE_VIDEO_FUTURE"
IMAGE_SLOT_COUNT = 30
VIDEO_SLOT_COUNT = 10

IMAGE_ENV_NAME = "SEEDANCE_IMAGE_CONCURRENCY"
VIDEO_ENV_NAME = "SEEDANCE_VIDEO_CONCURRENCY"

PURE_IMAGE_NODE_KEYS = (
    "Seedream_V5_Pro_Image",
    "Zhenzhen_Image_G2",
    "Qwen_Image_3_0",
    "Zhenzhen_Image_GK_V15",
    "Zhenzhen_Image_NB",
)

PURE_VIDEO_NODE_KEYS = (
    "Seedance_TextToVideo",
    "Seedance_ImageToVideo",
    "Seedance_MultimodalVideo",
    "Seedance_2_5_Video",
    "Zhenzhen_Video_G_Omni_Flash",
    "Zhenzhen_Video_GK_V15",
    "Zhenzhen_Video_V31",
    "HappyHorse_1_1_Video",
    "Wan_2_7_Spicy_I2V",
    "Kling_Video",
    "Kling_Edit_Video",
    "Hailuo_2_3_Video",
    "Hailuo_H3_Video",
    "Flux_3_Video",
    "Minimax_H3_OW_Video",
    "Minimax_H3_OW_Fast_Video",
    "Vidu_Q3_Video",
    "Vidu_Q3_ShortPlay",
    "Zhenzhen_Upscaler_Video",
)

MIDJOURNEY_IMAGE_OPERATIONS = tuple(
    operation
    for operation, spec in _nodes.MIDJOURNEY_ACTION_SPECS.items()
    if spec.get("result_family") == "image"
)

_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9]{12,}")
_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
_TASK_PATTERN = re.compile(
    r"\b(?:task[_-]?[A-Za-z0-9_-]{6,}|[0-9a-f]{24,})\b",
    re.IGNORECASE,
)


def _worker_count(env_name: str, default: int, maximum: int) -> int:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return default
    try:
        return max(1, min(maximum, int(raw)))
    except ValueError:
        print(
            f"[Seedance Concurrent] Invalid {env_name}={raw!r}; "
            f"using default {default}."
        )
        return default


class _BoundedExecutor:
    def __init__(self, max_workers: int, thread_name_prefix: str):
        self.max_workers = max_workers
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self._admission = threading.BoundedSemaphore(max_workers * 2)
        self._shutdown = False
        self._lock = threading.Lock()

    def submit(self, function, *args, **kwargs) -> concurrent.futures.Future:
        self._admission.acquire()
        with self._lock:
            if self._shutdown:
                self._admission.release()
                raise RuntimeError("Concurrent executor is shutting down.")
            try:
                future = self._executor.submit(function, *args, **kwargs)
            except Exception:
                self._admission.release()
                raise
        future.add_done_callback(lambda _future: self._admission.release())
        return future

    def shutdown(self, wait: bool = False) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
        self._executor.shutdown(wait=wait, cancel_futures=True)


_pool_lock = threading.Lock()
_image_pool: Optional[_BoundedExecutor] = None
_video_pool: Optional[_BoundedExecutor] = None


def _pool_for(kind: str) -> _BoundedExecutor:
    global _image_pool, _video_pool
    with _pool_lock:
        if kind == "image":
            if _image_pool is None:
                workers = _worker_count(
                    IMAGE_ENV_NAME, IMAGE_SLOT_COUNT, IMAGE_SLOT_COUNT
                )
                _image_pool = _BoundedExecutor(workers, "seedance-image")
                print(
                    f"[Seedance Concurrent] Image pool started with "
                    f"{workers} workers."
                )
            return _image_pool
        if kind == "video":
            if _video_pool is None:
                workers = _worker_count(
                    VIDEO_ENV_NAME, VIDEO_SLOT_COUNT, VIDEO_SLOT_COUNT
                )
                _video_pool = _BoundedExecutor(workers, "seedance-video")
                print(
                    f"[Seedance Concurrent] Video pool started with "
                    f"{workers} workers."
                )
            return _video_pool
    raise ValueError(f"Unsupported concurrent media kind: {kind}")


def shutdown_concurrent_pools(wait: bool = False) -> None:
    global _image_pool, _video_pool
    with _pool_lock:
        image_pool, video_pool = _image_pool, _video_pool
        _image_pool = None
        _video_pool = None
    if image_pool is not None:
        image_pool.shutdown(wait=wait)
    if video_pool is not None:
        video_pool.shutdown(wait=wait)


atexit.register(shutdown_concurrent_pools)


@dataclass
class ConcurrentProgressState:
    value: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, value: float, total: float) -> None:
        denominator = max(1.0, float(total))
        normalized = max(0.0, min(1.0, float(value) / denominator))
        with self._lock:
            self.value = max(self.value, normalized)

    def complete(self) -> None:
        with self._lock:
            self.value = 1.0

    def snapshot(self) -> float:
        with self._lock:
            return self.value


@dataclass
class ConcurrentTaskHandle:
    future: concurrent.futures.Future
    kind: str
    original_node_key: str
    primary_output_index: int
    return_names: Tuple[str, ...]
    cancel_event: threading.Event
    skip_error: bool = False
    progress_state: ConcurrentProgressState = field(
        default_factory=ConcurrentProgressState
    )

    def cancel(self) -> bool:
        self.cancel_event.set()
        return self.future.cancel()


def _invoke_original(
    target_class,
    kwargs: Dict[str, Any],
    cancel_event: threading.Event,
    progress_state: ConcurrentProgressState,
):
    try:
        with concurrent_worker_context(cancel_event, progress_state.update):
            check_cancelled()
            node = target_class()
            function = getattr(node, target_class.FUNCTION)
            result = function(**kwargs)
            if inspect.isawaitable(result):
                result = asyncio.run(result)
            check_cancelled()
            return result
    finally:
        progress_state.complete()


def _submit_original(
    target_class,
    original_node_key: str,
    kind: str,
    primary_output_index: int,
    kwargs: Dict[str, Any],
) -> ConcurrentTaskHandle:
    cancel_event = threading.Event()
    progress_state = ConcurrentProgressState()
    future = _pool_for(kind).submit(
        _invoke_original,
        target_class,
        dict(kwargs),
        cancel_event,
        progress_state,
    )
    return ConcurrentTaskHandle(
        future=future,
        kind=kind,
        original_node_key=original_node_key,
        primary_output_index=primary_output_index,
        return_names=tuple(getattr(target_class, "RETURN_NAMES", ())),
        cancel_event=cancel_event,
        skip_error=bool(kwargs.get("skip_error", False)),
        progress_state=progress_state,
    )


def _failed_original(
    target_class,
    original_node_key: str,
    kind: str,
    primary_output_index: int,
    error: BaseException,
) -> ConcurrentTaskHandle:
    future = concurrent.futures.Future()
    future.set_exception(error)
    progress_state = ConcurrentProgressState()
    progress_state.complete()
    return ConcurrentTaskHandle(
        future=future,
        kind=kind,
        original_node_key=original_node_key,
        primary_output_index=primary_output_index,
        return_names=tuple(getattr(target_class, "RETURN_NAMES", ())),
        cancel_event=threading.Event(),
        skip_error=True,
        progress_state=progress_state,
    )


def _safe_class_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]", "_", value)


def _copy_input_types(target_class) -> Dict[str, Any]:
    return copy.deepcopy(target_class.INPUT_TYPES())


def _preflight_original_inputs(target_class, kwargs: Dict[str, Any]) -> None:
    validator = getattr(target_class, "VALIDATE_INPUTS", None)
    if validator is None:
        return

    signature = inspect.signature(validator)
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    validation_kwargs = dict(kwargs) if accepts_kwargs else {
        name: kwargs[name]
        for name in signature.parameters
        if name in kwargs
    }
    if "strict" in signature.parameters or accepts_kwargs:
        validation_kwargs["strict"] = True

    validation = validator(**validation_kwargs)
    if validation is not True:
        raise SeedanceAPIError(str(validation))


def _make_submit_class(
    original_node_key: str,
    target_class,
    kind: str,
    primary_output_index: int = 0,
    input_types_factory=None,
):
    future_type = IMAGE_FUTURE_TYPE if kind == "image" else VIDEO_FUTURE_TYPE
    original_category = str(getattr(target_class, "CATEGORY", "Seedance"))

    @classmethod
    def input_types(cls):
        if input_types_factory is not None:
            return input_types_factory()
        return _copy_input_types(target_class)

    @classmethod
    def validate_wrapper_inputs(cls):
        # Let ComfyUI perform ordinary per-field type/range checks. Model-aware
        # checks run synchronously in submit() so one error is not duplicated
        # across every input by ComfyUI 0.30 custom validation reporting.
        return True

    def submit(self, **kwargs):
        try:
            _preflight_original_inputs(target_class, kwargs)
        except Exception as error:
            if not bool(kwargs.get("skip_error", False)):
                raise
            return (_failed_original(
                target_class,
                original_node_key,
                kind,
                primary_output_index,
                error,
            ),)
        handle = _submit_original(
            target_class,
            original_node_key,
            kind,
            primary_output_index,
            kwargs,
        )
        return (handle,)

    class_name = f"SeedanceConcurrentSubmit_{_safe_class_name(original_node_key)}"
    attrs = {
        "__module__": __name__,
        "INPUT_TYPES": input_types,
        "VALIDATE_INPUTS": validate_wrapper_inputs,
        "RETURN_TYPES": (future_type,),
        "RETURN_NAMES": ("future",),
        "FUNCTION": "submit",
        "CATEGORY": f"{original_category}/并发提交",
        "OUTPUT_NODE": False,
        "ORIGINAL_NODE_KEY": original_node_key,
        "ORIGINAL_NODE_CLASS": target_class,
        "CONCURRENT_KIND": kind,
        "PRIMARY_OUTPUT_INDEX": primary_output_index,
        "submit": submit,
    }
    return type(class_name, (target_class,), attrs)


def _midjourney_input_types(kind: str) -> Dict[str, Any]:
    inputs = _copy_input_types(_nodes.MidjourneyMultiAction)
    if kind == "image":
        operations = MIDJOURNEY_IMAGE_OPERATIONS
    else:
        operations = ("midjourney-video",)
    choices = [
        _nodes.MIDJOURNEY_OPERATION_LABELS[operation]
        for operation in operations
    ] + list(operations)
    _, options = inputs["required"]["operation"]
    options = dict(options)
    options["default"] = _nodes.MIDJOURNEY_OPERATION_LABELS[operations[0]]
    inputs["required"]["operation"] = (choices, options)
    return inputs


def _unwrap_outputs(result: Any) -> Tuple[Any, ...]:
    if isinstance(result, dict) and "result" in result:
        result = result["result"]
    if isinstance(result, tuple):
        return result
    if isinstance(result, list):
        return tuple(result)
    return (result,)


def _redacted_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    text = _SECRET_PATTERN.sub("[redacted-key]", text)
    text = _URL_PATTERN.sub("[redacted-url]", text)
    text = _TASK_PATTERN.sub("[redacted-task]", text)
    return text if len(text) <= 400 else text[:400] + "..."


def _check_comfy_interruption() -> None:
    try:
        import comfy.model_management

        comfy.model_management.throw_exception_if_processing_interrupted()
    except ImportError:
        return


def _cancel_handles(handles: Iterable[ConcurrentTaskHandle]) -> None:
    for handle in handles:
        handle.cancel()


class _ConcurrentAwaitBase:
    KIND = ""
    SLOT_COUNT = 0
    FUTURE_TYPE = ""
    MEDIA_TYPE = ""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "future_1": (cls.FUTURE_TYPE,),
                "failure_mode": (
                    ["raise", "placeholder"],
                    {"default": "raise"},
                ),
            },
            "optional": {
                f"future_{index}": (cls.FUTURE_TYPE,)
                for index in range(2, cls.SLOT_COUNT + 1)
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    FUNCTION = "wait_all"
    CATEGORY = "Seedance/并发接收"
    OUTPUT_NODE = True

    def _placeholder(self, message: str):
        if self.KIND == "image":
            return make_error_image(message)
        return make_error_video(message)

    def _validate_handle(self, slot: int, handle: Any) -> ConcurrentTaskHandle:
        if not isinstance(handle, ConcurrentTaskHandle):
            raise TypeError(
                f"Concurrent slot {slot} expected ConcurrentTaskHandle, "
                f"got {type(handle).__name__}."
            )
        if handle.kind != self.KIND:
            raise TypeError(
                f"Concurrent slot {slot} expected {self.KIND}, got {handle.kind}."
            )
        return handle

    def _extract_media(self, handle: ConcurrentTaskHandle, result: Any) -> Any:
        outputs = _unwrap_outputs(result)
        index = handle.primary_output_index
        if index >= len(outputs):
            raise RuntimeError(
                f"{handle.original_node_key} returned {len(outputs)} outputs; "
                f"primary index {index} is unavailable."
            )
        media = outputs[index]
        if self.KIND == "image" and not torch.is_tensor(media):
            raise TypeError(
                f"{handle.original_node_key} returned "
                f"{type(media).__name__} instead of IMAGE."
            )
        if self.KIND == "video" and media is None:
            raise TypeError(
                f"{handle.original_node_key} returned an empty VIDEO."
            )
        return media

    def _metadata_summary(
        self,
        handle: ConcurrentTaskHandle,
        result: Any,
    ) -> Tuple[str, ...]:
        outputs = _unwrap_outputs(result)
        available = []
        for index, value in enumerate(outputs):
            if index == handle.primary_output_index:
                continue
            name = (
                handle.return_names[index]
                if index < len(handle.return_names)
                else f"output_{index + 1}"
            )
            if value is None:
                continue
            if isinstance(value, str) and value in ("", "[]"):
                continue
            available.append(name)
        return tuple(available)

    def wait_all(self, failure_mode: str = "raise", **kwargs):
        if failure_mode not in {"raise", "placeholder"}:
            raise ValueError(f"Unsupported failure_mode: {failure_mode}")

        handles: Dict[int, ConcurrentTaskHandle] = {}
        for slot in range(1, self.SLOT_COUNT + 1):
            value = kwargs.get(f"future_{slot}")
            if value is not None:
                handles[slot] = self._validate_handle(slot, value)
        if not handles:
            raise ValueError("At least one concurrent Future is required.")

        failure_placeholder = None
        outputs = [None] * self.SLOT_COUNT
        statuses: Dict[int, Dict[str, Any]] = {
            slot: {
                "slot": slot,
                "source": handle.original_node_key,
                "state": "waiting",
            }
            for slot, handle in handles.items()
        }
        pending = {
            handle.future: (slot, handle)
            for slot, handle in handles.items()
        }

        progress_total = 1000
        pbar = _nodes._make_progress_bar(progress_total)
        last_progress_value = -1
        completed = 0
        try:
            while pending:
                _check_comfy_interruption()
                if pbar is not None:
                    progress_value = int(
                        sum(
                            handle.progress_state.snapshot()
                            for handle in handles.values()
                        )
                        / len(handles)
                        * progress_total
                    )
                    if progress_value != last_progress_value:
                        pbar.update_absolute(progress_value, progress_total)
                        last_progress_value = progress_value
                done, _ = concurrent.futures.wait(
                    pending,
                    timeout=0.2,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                if not done:
                    continue
                for future in done:
                    slot, handle = pending.pop(future)
                    try:
                        result = future.result()
                        outputs[slot - 1] = self._extract_media(handle, result)
                        statuses[slot]["state"] = "completed"
                        metadata = self._metadata_summary(handle, result)
                        if metadata:
                            statuses[slot]["available_outputs"] = list(metadata)
                    except BaseException as exc:
                        statuses[slot]["state"] = "failed"
                        statuses[slot]["error"] = _redacted_error(exc)
                        skip_failed_slot = bool(handle.skip_error)
                        if failure_mode == "raise" and not skip_failed_slot:
                            _cancel_handles(item[1] for item in pending.values())
                            raise RuntimeError(
                                f"Concurrent {self.KIND} slot {slot} failed: "
                                f"{_redacted_error(exc)}"
                            ) from exc
                        if skip_failed_slot:
                            statuses[slot]["skipped"] = True
                        if failure_placeholder is None:
                            failure_placeholder = self._placeholder(
                                f"Concurrent {self.KIND} task failed."
                            )
                        outputs[slot - 1] = failure_placeholder
                    completed += 1
                    handle.progress_state.complete()
            if pbar is not None and last_progress_value != progress_total:
                pbar.update_absolute(progress_total, progress_total)
        except BaseException:
            _cancel_handles(handles.values())
            raise

        if len(handles) < self.SLOT_COUNT:
            missing_placeholder = self._placeholder(
                f"Concurrent {self.KIND} slot is not connected."
            )
            for index, output in enumerate(outputs):
                if output is None:
                    outputs[index] = missing_placeholder

        summary = {
            "kind": self.KIND,
            "connected": len(handles),
            "completed": sum(
                item["state"] == "completed" for item in statuses.values()
            ),
            "failed": sum(
                item["state"] == "failed" for item in statuses.values()
            ),
            "slots": [statuses[slot] for slot in sorted(statuses)],
        }
        return tuple(outputs) + (json.dumps(summary, ensure_ascii=False),)


class SeedanceConcurrentImageAwait(_ConcurrentAwaitBase):
    KIND = "image"
    SLOT_COUNT = IMAGE_SLOT_COUNT
    FUTURE_TYPE = IMAGE_FUTURE_TYPE
    MEDIA_TYPE = "IMAGE"
    RETURN_TYPES = tuple(["IMAGE"] * IMAGE_SLOT_COUNT + ["STRING"])
    RETURN_NAMES = tuple(
        [f"image_{index}" for index in range(1, IMAGE_SLOT_COUNT + 1)]
        + ["status_json"]
    )


class SeedanceConcurrentVideoAwait(_ConcurrentAwaitBase):
    KIND = "video"
    SLOT_COUNT = VIDEO_SLOT_COUNT
    FUTURE_TYPE = VIDEO_FUTURE_TYPE
    MEDIA_TYPE = "VIDEO"
    RETURN_TYPES = tuple(["VIDEO"] * VIDEO_SLOT_COUNT + ["STRING"])
    RETURN_NAMES = tuple(
        [f"video_{index}" for index in range(1, VIDEO_SLOT_COUNT + 1)]
        + ["status_json"]
    )


CONCURRENT_NODE_CLASS_MAPPINGS = {
    "SeedanceConcurrent_Image_Await": SeedanceConcurrentImageAwait,
    "SeedanceConcurrent_Video_Await": SeedanceConcurrentVideoAwait,
}

CONCURRENT_NODE_DISPLAY_NAME_MAPPINGS = {
    "SeedanceConcurrent_Image_Await": "并发接收图片（30 路）",
    "SeedanceConcurrent_Video_Await": "并发接收视频（10 路）",
}


def _register_pure_wrappers() -> None:
    for kind, keys in (
        ("image", PURE_IMAGE_NODE_KEYS),
        ("video", PURE_VIDEO_NODE_KEYS),
    ):
        expected_type = kind.upper()
        for original_key in keys:
            target_class = _nodes.NODE_CLASS_MAPPINGS[original_key]
            first_type = str(getattr(target_class, "RETURN_TYPES", (None,))[0])
            if first_type.upper() != expected_type:
                raise RuntimeError(
                    f"Concurrent registration mismatch for {original_key}: "
                    f"expected {expected_type}, got {first_type}."
                )
            wrapper_key = f"SeedanceConcurrent_{original_key}_Submit"
            wrapper_class = _make_submit_class(
                original_key,
                target_class,
                kind,
            )
            display_name = _nodes.NODE_DISPLAY_NAME_MAPPINGS.get(
                original_key, original_key
            )
            CONCURRENT_NODE_CLASS_MAPPINGS[wrapper_key] = wrapper_class
            CONCURRENT_NODE_DISPLAY_NAME_MAPPINGS[wrapper_key] = (
                f"并发提交｜{display_name}"
            )


def _register_midjourney_wrappers() -> None:
    target_class = _nodes.MidjourneyMultiAction
    image_key = "SeedanceConcurrent_Midjourney_Image_Submit"
    video_key = "SeedanceConcurrent_Midjourney_Video_Submit"
    CONCURRENT_NODE_CLASS_MAPPINGS[image_key] = _make_submit_class(
        "Midjourney_Multi_Action",
        target_class,
        "image",
        primary_output_index=0,
        input_types_factory=lambda: _midjourney_input_types("image"),
    )
    CONCURRENT_NODE_CLASS_MAPPINGS[video_key] = _make_submit_class(
        "Midjourney_Multi_Action",
        target_class,
        "video",
        primary_output_index=5,
        input_types_factory=lambda: _midjourney_input_types("video"),
    )
    CONCURRENT_NODE_DISPLAY_NAME_MAPPINGS[image_key] = (
        "并发提交｜Midjourney 图片"
    )
    CONCURRENT_NODE_DISPLAY_NAME_MAPPINGS[video_key] = (
        "并发提交｜Midjourney 视频"
    )


_register_pure_wrappers()
_register_midjourney_wrappers()


__all__ = [
    "CONCURRENT_NODE_CLASS_MAPPINGS",
    "CONCURRENT_NODE_DISPLAY_NAME_MAPPINGS",
    "ConcurrentTaskHandle",
    "IMAGE_FUTURE_TYPE",
    "VIDEO_FUTURE_TYPE",
    "IMAGE_SLOT_COUNT",
    "VIDEO_SLOT_COUNT",
    "shutdown_concurrent_pools",
]
