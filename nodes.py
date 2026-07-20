"""
ComfyUI nodes for Seedance, HappyHorse, Wan, Kling, Hailuo, Vidu,
Zhenzhen Upscaler, Seedream, Dola Seedream, Zhenzhen Image G-2,
and Doubao Seed Audio APIs
(api.seedance.nz).

Seedance video nodes expose the 18 Seedance 2.0 model variants by task type.
HappyHorse, Wan, Kling, Hailuo, Vidu, and Zhenzhen Upscaler use dedicated video
nodes, Seedream and Dola Seedream share one image node with a model-family
selector, Zhenzhen Image G-2 uses its own image node, and Doubao Seed Audio
uses its own audio node.

Execution flow per node: upload media -> build payload -> submit -> poll ->
download result, with a ComfyUI progress bar driven by the API's progress
field and skip_error support for batch workflows.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from .core.config import get_config, DEFAULT_BASE_URL
from .core.client import (
    SeedanceAPIError,
    download_audio,
    download_image,
    download_video,
    extract_audio_url,
    extract_image_url,
    extract_video_url,
    poll_audio_task,
    poll_image_task,
    poll_task,
    submit_audio_task,
    submit_image_task,
    submit_task,
    upload_media,
)
from .core.media import (
    audio_to_wav_bytes,
    image_to_png_bytes,
    make_silent_audio,
    make_error_video,
    video_to_bytes,
)

try:
    import comfy.utils
    COMFYUI_AVAILABLE = True
except ImportError:
    COMFYUI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Model catalog
# ---------------------------------------------------------------------------

_TIERS = ("standard", "fast", "mini")


def _models_for(task_type: str) -> List[str]:
    cn = [f"seedance-2.0-{tier}-{task_type}" for tier in _TIERS]
    global_ = [f"seedance-2.0-global-{tier}-{task_type}" for tier in _TIERS]
    return cn + global_


T2V_MODELS = _models_for("t2v")
I2V_MODELS = _models_for("i2v")
MULTI_MODELS = _models_for("multi")

RESOLUTIONS = ["480p", "720p", "1080p", "2k", "4k", "native1080p", "native4k"]
STANDARD_ONLY_RESOLUTIONS = {"native1080p", "native4k"}
SECONDS = ["-1"] + [str(s) for s in range(4, 16)]
RATIOS = ["adaptive", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"]

PROMPT_MAX_LENGTH = 20480

MAX_MULTI_IMAGES = 9
MAX_MULTI_VIDEOS = 3
MAX_MULTI_AUDIOS = 3

SEEDREAM_T2I_MODEL = "seedream-v5-pro-t2i"
SEEDREAM_I2I_MODEL = "seedream-v5-pro-i2i"
DOLA_SEEDREAM_T2I_MODEL = "dola-seedream-5.0-pro-t2i"
DOLA_SEEDREAM_I2I_MODEL = "dola-seedream-5.0-pro-i2i"
SEEDREAM_FAMILY_DOMESTIC = "seedream-v5-pro (domestic)"
SEEDREAM_FAMILY_DOLA = "dola-seedream-5.0-pro (overseas)"
SEEDREAM_MODEL_FAMILIES = [SEEDREAM_FAMILY_DOMESTIC, SEEDREAM_FAMILY_DOLA]
SEEDREAM_MODEL_PAIRS = {
    SEEDREAM_FAMILY_DOMESTIC: (SEEDREAM_T2I_MODEL, SEEDREAM_I2I_MODEL),
    SEEDREAM_FAMILY_DOLA: (DOLA_SEEDREAM_T2I_MODEL, DOLA_SEEDREAM_I2I_MODEL),
}
SEEDREAM_RESOLUTIONS = ["1k", "2k", "custom"]
SEEDREAM_OUTPUT_FORMATS = ["png", "jpeg"]
SEEDREAM_PROMPT_MIN_LENGTH = 5
SEEDREAM_PROMPT_MAX_LENGTH = 2000
MAX_SEEDREAM_IMAGES = 10
ZHENZHEN_IMAGE_G2_T2I_MODEL = "zhenzhen-image-g2-t2i"
ZHENZHEN_IMAGE_G2_I2I_MODEL = "zhenzhen-image-g2-i2i"
ZHENZHEN_IMAGE_G2_MODELS = [ZHENZHEN_IMAGE_G2_T2I_MODEL, ZHENZHEN_IMAGE_G2_I2I_MODEL]
ZHENZHEN_IMAGE_G2_RESOLUTIONS = ["1k"]
ZHENZHEN_IMAGE_G2_PROMPT_MAX_LENGTH = 20000
MAX_ZHENZHEN_IMAGE_G2_IMAGES = 10

HAPPYHORSE_T2V_MODEL = "happyhorse-1.1-t2v"
HAPPYHORSE_I2V_MODEL = "happyhorse-1.1-i2v"
HAPPYHORSE_R2V_MODEL = "happyhorse-1.1-r2v"
HAPPYHORSE_MODELS = [HAPPYHORSE_T2V_MODEL, HAPPYHORSE_I2V_MODEL, HAPPYHORSE_R2V_MODEL]
HAPPYHORSE_RESOLUTIONS = ["720p", "1080p"]
HAPPYHORSE_SECONDS = [str(s) for s in range(3, 16)]
MAX_HAPPYHORSE_R2V_IMAGES = 9

WAN27_SPICY_I2V_MODEL = "wan-2.7-spicy-i2v"
WAN27_SPICY_RESOLUTIONS = ["720p", "1080p"]
WAN27_SPICY_SECONDS = [str(s) for s in range(2, 16)]

KLING_T2V_MODELS = [
    "kling-v3.0-std-t2v",
    "kling-v3.0-pro-t2v",
    "kling-v3-turbo-std-t2v",
    "kling-v3-turbo-pro-t2v",
    "kling-v3-4k-t2v",
    "kling-o3-std-t2v",
    "kling-o3-pro-t2v",
    "kling-o3-4k-t2v",
]
KLING_I2V_MODELS = [
    "kling-v3.0-std-i2v",
    "kling-v3.0-pro-i2v",
    "kling-v3-turbo-std-i2v",
    "kling-v3-turbo-pro-i2v",
    "kling-v3-4k-i2v",
    "kling-o3-std-i2v",
    "kling-o3-pro-i2v",
    "kling-o3-4k-i2v",
]
KLING_R2V_MODELS = [
    "kling-o3-std-r2v",
    "kling-o3-pro-r2v",
    "kling-o3-4k-r2v",
]
KLING_VIDEO_MODELS = KLING_T2V_MODELS + KLING_I2V_MODELS + KLING_R2V_MODELS
KLING_EDIT_MODELS = [
    "kling-o3-std-edit",
    "kling-o3-pro-edit",
]
KLING_SECONDS = ["5", "10"]
MAX_KLING_REFERENCE_IMAGES = 4

HAILUO23_T2V_MODELS = [
    "hailuo-2.3-t2v-standard",
    "hailuo-2.3-t2v-pro",
]
HAILUO23_I2V_MODELS = [
    "hailuo-2.3-i2v-standard",
    "hailuo-2.3-i2v-pro",
    "hailuo-2.3-fast-i2v",
    "hailuo-2.3-fast-pro-i2v",
]
HAILUO23_MODELS = HAILUO23_T2V_MODELS + HAILUO23_I2V_MODELS
HAILUO23_SECONDS = ["6", "10"]
HAILUO23_RESOLUTIONS = ["768p", "1080p"]
HAILUO23_PROMPT_MAX_LENGTH = 2000
HAILUO23_MIN_IMAGE_SHORT_EDGE = 301
HAILUO23_MIN_ASPECT_RATIO = 2 / 5
HAILUO23_MAX_ASPECT_RATIO = 5 / 2

VIDU_T2V_MODELS = [
    "vidu-q3-pro-t2v",
    "vidu-q3-turbo-t2v",
    "vidu-q3-pro-fast-t2v",
]
VIDU_I2V_MODELS = [
    "vidu-q3-pro-i2v",
    "vidu-q3-turbo-i2v",
    "vidu-q3-pro-fast-i2v",
]
VIDU_START_END_MODELS = [
    "vidu-q3-pro-start-end",
    "vidu-q3-turbo-start-end",
    "vidu-q3-pro-fast-start-end",
]
VIDU_R2V_MODELS = [
    "vidu-q3-r2v",
    "vidu-q3-mix-r2v",
    "vidu-q3-ad-r2v",
    "vidu-q3-drama-r2v",
]
VIDU_VIDEO_MODELS = VIDU_T2V_MODELS + VIDU_I2V_MODELS + VIDU_START_END_MODELS + VIDU_R2V_MODELS
VIDU_SHORT_PLAY_MODELS = [
    "vidu-q3-drama-short-play",
    "vidu-q3-ad-short-play",
]
VIDU_SECONDS = [str(s) for s in range(4, 16)]
VIDU_RESOLUTIONS = ["default", "720p", "1080p"]
MAX_VIDU_REFERENCE_IMAGES = 9
VIDU_SHORT_PLAY_DURATIONS = [str(s) for s in range(8, 13)]
VIDU_SHORT_PLAY_ASPECT_RATIOS = ["9:16", "16:9"]
VIDU_SHORT_PLAY_ASSET_TYPES = ["character", "scene", "prop"]
MAX_VIDU_SHORT_PLAY_ASSETS = 14

ZHENZHEN_UPSCALER_MODEL = "zhenzhen-upscaler"
ZHENZHEN_UPSCALER_RESOLUTIONS = ["720p", "1080p", "2k", "4k"]

DOUBAO_SEED_AUDIO_MODEL = "doubao-seed-audio-1.0"
DOUBAO_AUDIO_FORMATS = ["wav", "mp3", "pcm", "ogg_opus"]
DOUBAO_SAMPLE_RATES = ["8000", "16000", "24000", "32000", "44100"]
DOUBAO_PROMPT_MIN_LENGTH = 5
DOUBAO_PROMPT_MAX_LENGTH = 2048
MAX_DOUBAO_REFERENCE_AUDIOS = 3


def _is_standard_tier(model: str) -> bool:
    return "-standard-" in model


def _validate_common(model: str, resolution: str, prompt: Optional[str]):
    """Shared widget-level validation. Returns error string or True."""
    if resolution in STANDARD_ONLY_RESOLUTIONS and not _is_standard_tier(model):
        return (
            f"resolution '{resolution}' is only supported by Standard tier models; "
            f"'{model}' is not Standard. Use 480p/720p/1080p/2k/4k instead. | "
            f"native1080p/native4k 仅 Standard 档模型支持，请换用其他分辨率或 Standard 模型。"
        )
    if prompt is not None and len(prompt) > PROMPT_MAX_LENGTH:
        return f"prompt exceeds {PROMPT_MAX_LENGTH} characters ({len(prompt)})"
    return True


# ---------------------------------------------------------------------------
# Shared widget definitions
# ---------------------------------------------------------------------------

def _model_input(models: List[str]) -> tuple:
    return (models, {
        "default": models[0],
        "tooltip": (
            "standard/fast/mini = quality tiers; 'global-' models "
            "run on overseas infrastructure. | standard/fast/mini 为档位，"
            "带 global- 的为海外版通道。"
        ),
    })


def _prompt_input(required: bool) -> tuple:
    tooltip = (
        "Text prompt, up to 20480 chars. In multimodal mode you can reference "
        "materials as @Image 1 / @Video 1 / @Audio 1. | 文本提示词，多模态可用 "
        "@Image 1、@Video 1 指代第几个素材。"
    )
    return ("STRING", {"multiline": True, "default": "", "tooltip": tooltip})


def _common_widgets() -> Dict[str, tuple]:
    return {
        "seconds": (SECONDS, {
            "default": "5",
            "tooltip": "Video duration in seconds; -1 lets the model decide. | 视频时长（秒），-1 表示模型智能选择。",
        }),
        "resolution": (RESOLUTIONS, {
            "default": "720p",
            "tooltip": (
                "1080p/2k/4k are upscaled output tiers; native1080p/native4k "
                "are Standard-tier only. | 1080p/2k/4k 为超分输出档，native 档"
                "仅 Standard 模型支持。"
            ),
        }),
        "ratio": (RATIOS, {
            "default": "adaptive",
            "tooltip": "Aspect ratio; adaptive follows the input material. | 画面比例，adaptive 为自适应。",
        }),
    }


def _optional_widgets() -> Dict[str, tuple]:
    return {
        "generate_audio": ("BOOLEAN", {
            "default": True,
            "tooltip": "Generate voice-over / sound effects. | 是否生成配音与音效。",
        }),
        "seed": ("INT", {
            "default": -1, "min": -1, "max": 2147483647, "step": 1,
            "tooltip": "-1 = random seed. | -1 表示随机种子。",
        }),
        "api_config": ("SEEDANCE_CONFIG", {
            "tooltip": "Connect a 'Seedance API Config' node; falls back to SEEDANCE_API_KEY env var.",
        }),
        "skip_error": ("BOOLEAN", {
            "default": False,
            "tooltip": (
                "On failure return a placeholder error video instead of stopping the "
                "workflow. | 失败时输出占位错误视频而不中断工作流。"
            ),
        }),
    }


# ---------------------------------------------------------------------------
# Config node
# ---------------------------------------------------------------------------

class SeedanceConfig:
    """Outputs API connection config for Seedance generation nodes."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "base_url": ("STRING", {"default": DEFAULT_BASE_URL}),
                "api_key": ("STRING", {
                    "default": "",
                    "tooltip": f"Create at {DEFAULT_BASE_URL}/console -> API tokens. | 在控制台「API 令牌」页面创建。",
                }),
            },
        }

    RETURN_TYPES = ("SEEDANCE_CONFIG",)
    RETURN_NAMES = ("api_config",)
    CATEGORY = "Seedance"
    FUNCTION = "build"

    def build(self, base_url: str, api_key: str):
        return ([{"base_url": base_url.strip(), "api_key": api_key.strip()}],)


# ---------------------------------------------------------------------------
# Generation node base
# ---------------------------------------------------------------------------

class SeedanceVideoNodeBase:
    """Shared execute flow: upload -> submit -> poll -> download."""

    CATEGORY = "Seedance"
    FUNCTION = "execute"
    OUTPUT_NODE = True
    RETURN_TYPES = ("VIDEO", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("video", "video_url", "task_id", "response")

    # progress bar segments (0-100)
    PROGRESS_UPLOAD_END = 15
    PROGRESS_SUBMIT_END = 20
    PROGRESS_POLL_END = 95

    @property
    def _log_prefix(self) -> str:
        return f"Seedance_{self.__class__.__name__}"

    # ---- subclass hooks ----

    def collect_media(self, kwargs: Dict, config: Dict, progress_cb) -> Dict[str, Any]:
        """Upload node media inputs, return payload fragments (images/content)."""
        return {}

    def build_payload(self, kwargs: Dict, media: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    # ---- shared helpers ----

    def _base_payload(self, kwargs: Dict) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {
            "resolution": kwargs["resolution"],
            "ratio": kwargs["ratio"],
            "generate_audio": bool(kwargs.get("generate_audio", True)),
        }
        seed = kwargs.get("seed", -1)
        if seed is not None and int(seed) >= 0:
            metadata["seed"] = int(seed)
        return {
            "model": kwargs["model"],
            "seconds": str(kwargs["seconds"]),
            "metadata": metadata,
        }

    def _update_progress(self, pbar, value: float):
        if pbar is not None:
            try:
                pbar.update_absolute(int(value), 100)
            except Exception:
                pass

    def _make_error_result(self, error_msg: str) -> Dict:
        video = make_error_video(error_msg)
        response_str = json.dumps({"error": error_msg}, ensure_ascii=False, indent=2)
        return {
            "ui": {"text": ["", response_str]},
            "result": (video, "", "", response_str),
        }

    # ---- main flow ----

    def execute(self, **kwargs):
        skip_error = bool(kwargs.pop("skip_error", False))
        try:
            return self._execute_inner(**kwargs)
        except Exception as e:
            if skip_error:
                err_msg = f"{self._log_prefix}: {e}"
                print(f"[{self._log_prefix}] skip_error=True, returning placeholder: {e}")
                return self._make_error_result(err_msg)
            raise

    def _execute_inner(self, **kwargs):
        config = get_config(kwargs.get("api_config"))
        pbar = comfy.utils.ProgressBar(100) if COMFYUI_AVAILABLE else None
        self._update_progress(pbar, 0)

        # Stage 1: upload reference media
        try:
            media = self.collect_media(
                kwargs, config,
                lambda frac: self._update_progress(pbar, frac * self.PROGRESS_UPLOAD_END),
            )
        except SeedanceAPIError:
            raise
        except Exception as e:
            raise RuntimeError(f"[{self._log_prefix}] Media upload failed: {e}") from e
        self._update_progress(pbar, self.PROGRESS_UPLOAD_END)

        # Stage 2: build payload and submit
        payload = self.build_payload(kwargs, media)
        task_id = submit_task(payload, config, logger_prefix=self._log_prefix)
        self._update_progress(pbar, self.PROGRESS_SUBMIT_END)

        # Stage 3: poll until terminal status, mapping API progress 0-100
        # into the poll segment of the progress bar
        poll_span = self.PROGRESS_POLL_END - self.PROGRESS_SUBMIT_END

        def on_progress(p: int):
            self._update_progress(pbar, self.PROGRESS_SUBMIT_END + p / 100.0 * poll_span)

        final_response = poll_task(
            task_id, config, on_progress=on_progress, logger_prefix=self._log_prefix
        )
        self._update_progress(pbar, self.PROGRESS_POLL_END)

        # Stage 4: download result video
        video_url = extract_video_url(final_response)
        video = download_video(video_url, logger_prefix=self._log_prefix)
        self._update_progress(pbar, 100)

        response_str = json.dumps(final_response, ensure_ascii=False, indent=2)
        return {
            "ui": {"text": [video_url, response_str]},
            "result": (video, video_url, task_id, response_str),
        }


# ---------------------------------------------------------------------------
# Text to Video
# ---------------------------------------------------------------------------

class SeedanceTextToVideo(SeedanceVideoNodeBase):
    """Text-to-video across all 6 -t2v models."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": _model_input(T2V_MODELS),
                "prompt": _prompt_input(required=True),
                **_common_widgets(),
            },
            "optional": _optional_widgets(),
        }

    @classmethod
    def VALIDATE_INPUTS(cls, model=None, resolution=None, prompt=None, strict=False, **kwargs):
        if model and resolution:
            result = _validate_common(model, resolution, prompt)
            if result is not True:
                return result
        if strict and not str(prompt or "").strip():
            return "prompt is required for text-to-video | 文生视频必须填写提示词"
        return True

    def build_payload(self, kwargs, media):
        prompt = str(kwargs.get("prompt") or "").strip()
        if not prompt:
            raise SeedanceAPIError("prompt is required for text-to-video | 文生视频必须填写提示词")
        payload = self._base_payload(kwargs)
        payload["prompt"] = prompt
        return payload


# ---------------------------------------------------------------------------
# Image to Video
# ---------------------------------------------------------------------------

class SeedanceImageToVideo(SeedanceVideoNodeBase):
    """Image-to-video: first frame (required) + last frame (optional)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "first_image": ("IMAGE", {
                    "tooltip": "First frame reference image (required). | 首帧参考图（必填）。",
                }),
                "model": _model_input(I2V_MODELS),
                "prompt": _prompt_input(required=False),
                **_common_widgets(),
            },
            "optional": {
                "last_image": ("IMAGE", {
                    "tooltip": "Optional last frame reference image. | 尾帧参考图（可选）。",
                }),
                **_optional_widgets(),
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, model=None, resolution=None, prompt=None, **kwargs):
        if model and resolution:
            result = _validate_common(model, resolution, prompt)
            if result is not True:
                return result
        return True

    def collect_media(self, kwargs, config, progress_cb):
        first_image = kwargs.get("first_image")
        if first_image is None:
            raise SeedanceAPIError("first_image is required | 图生视频必须连接首帧图")

        jobs = [("first_frame.png", first_image)]
        last_image = kwargs.get("last_image")
        if last_image is not None:
            jobs.append(("last_frame.png", last_image))

        urls = []
        for i, (filename, tensor) in enumerate(jobs):
            url = upload_media(
                image_to_png_bytes(tensor), filename, "image/png",
                config, logger_prefix=self._log_prefix,
            )
            urls.append(url)
            progress_cb((i + 1) / len(jobs))
        return {"images": urls}

    def build_payload(self, kwargs, media):
        payload = self._base_payload(kwargs)
        payload["images"] = media["images"]
        prompt = str(kwargs.get("prompt") or "").strip()
        if prompt:
            payload["prompt"] = prompt
        return payload


# ---------------------------------------------------------------------------
# HappyHorse 1.1 video
# ---------------------------------------------------------------------------

class HappyHorseVideo(SeedanceVideoNodeBase):
    """HappyHorse 1.1 t2v/i2v/r2v via /v1/videos."""

    @classmethod
    def INPUT_TYPES(cls):
        optional: Dict[str, tuple] = {
            "first_image": ("IMAGE", {
                "tooltip": (
                    "Required for happyhorse-1.1-i2v, and image 1 / 图1 for "
                    "happyhorse-1.1-r2v. | i2v 必填；r2v 中作为图1。"
                ),
            })
        }
        for i in range(2, MAX_HAPPYHORSE_R2V_IMAGES + 1):
            optional[f"reference_image{i}"] = ("IMAGE", {
                "tooltip": (
                    f"Optional r2v reference image {i}; prompt can mention 图{i}. "
                    f"Gaps are compacted to connected order. | r2v 可选参考图 {i}，"
                    f"提示词可写图{i}；跳号会按连接顺序压缩。"
                ),
            })
        optional["api_config"] = ("SEEDANCE_CONFIG", {
            "tooltip": "Connect Seedance API Config; otherwise SEEDANCE_API_KEY is used.",
        })
        optional["skip_error"] = ("BOOLEAN", {
            "default": False,
            "tooltip": "On failure return a placeholder error video instead of stopping the workflow. | 失败时输出占位错误视频。",
        })

        return {
            "required": {
                "model": (HAPPYHORSE_MODELS, {
                    "default": HAPPYHORSE_T2V_MODEL,
                    "tooltip": (
                        "HappyHorse 1.1 task type. t2v uses prompt only; i2v uses first_image; "
                        "r2v uses 1-9 reference images. | t2v 只用提示词；i2v 使用首帧图；"
                        "r2v 使用 1-9 张参考图。"
                    ),
                }),
                "prompt": _prompt_input(required=False),
                "seconds": (HAPPYHORSE_SECONDS, {
                    "default": "4",
                    "tooltip": "HappyHorse supports 3-15 seconds and does not support -1. | 支持 3-15 秒，不支持 -1。",
                }),
                "resolution": (HAPPYHORSE_RESOLUTIONS, {
                    "default": "720p",
                    "tooltip": "HappyHorse supports 720p or 1080p. | HappyHorse 支持 720p 或 1080p。",
                }),
                "ratio": (RATIOS, {
                    "default": "adaptive",
                    "tooltip": "Aspect ratio forwarded as metadata.ratio for upstream aspectRatio mapping. | 画幅会通过 metadata.ratio 映射给上游 aspectRatio。",
                }),
            },
            "optional": optional,
        }

    @classmethod
    def VALIDATE_INPUTS(cls, model=None, prompt=None, seconds=None, resolution=None, strict=False, **kwargs):
        if model not in (None, *HAPPYHORSE_MODELS):
            return f"unsupported HappyHorse model: {model}"
        if resolution is not None and resolution not in HAPPYHORSE_RESOLUTIONS:
            return "HappyHorse resolution must be 720p or 1080p | HappyHorse 分辨率只能是 720p 或 1080p"
        if seconds is not None and str(seconds) not in HAPPYHORSE_SECONDS:
            return "HappyHorse seconds must be 3-15 and cannot be -1 | HappyHorse 时长必须是 3-15 秒，不能用 -1"
        if prompt is not None and len(str(prompt)) > PROMPT_MAX_LENGTH:
            return f"prompt exceeds {PROMPT_MAX_LENGTH} characters ({len(str(prompt))})"
        if strict and model == HAPPYHORSE_T2V_MODEL and not str(prompt or "").strip():
            return "prompt is required for HappyHorse text-to-video | HappyHorse 文生视频必须填写提示词"
        return True

    @property
    def _log_prefix(self) -> str:
        return "HappyHorse_1_1_video"

    def _gather_r2v_images(self, kwargs: Dict[str, Any]) -> List[Tuple[int, Any]]:
        slots = []
        first_image = kwargs.get("first_image")
        if first_image is not None:
            slots.append((1, first_image))
        for i in range(2, MAX_HAPPYHORSE_R2V_IMAGES + 1):
            value = kwargs.get(f"reference_image{i}")
            if value is not None:
                slots.append((i, value))

        connected = [i for i, _ in slots]
        if connected and connected != list(range(1, len(connected) + 1)):
            print(
                f"[{self._log_prefix}] WARNING: r2v image slots {connected} have gaps; "
                f"they will be compacted to imageUrls order 1..{len(connected)}."
            )
        return slots

    def collect_media(self, kwargs, config, progress_cb):
        model = kwargs.get("model")
        if model == HAPPYHORSE_T2V_MODEL:
            return {}

        if model == HAPPYHORSE_I2V_MODEL:
            image_slots = [(1, kwargs.get("first_image"))] if kwargs.get("first_image") is not None else []
            required_message = (
                "first_image is required for happyhorse-1.1-i2v | "
                "happyhorse-1.1-i2v 必须连接首帧图"
            )
        else:
            image_slots = self._gather_r2v_images(kwargs)
            required_message = (
                "at least one reference image is required for happyhorse-1.1-r2v | "
                "happyhorse-1.1-r2v 至少需要 1 张参考图"
            )

        if not image_slots:
            raise SeedanceAPIError(
                required_message
            )

        urls = []
        for done, (slot, image) in enumerate(image_slots, start=1):
            url = upload_media(
                image_to_png_bytes(image),
                f"happyhorse_reference_{slot}.png",
                "image/png",
                config,
                logger_prefix=self._log_prefix,
            )
            urls.append(url)
            progress_cb(done / len(image_slots))
        return {"images": urls}

    def build_payload(self, kwargs, media):
        model = kwargs["model"]
        prompt = str(kwargs.get("prompt") or "").strip()
        payload: Dict[str, Any] = {
            "model": model,
            "seconds": str(kwargs["seconds"]),
            "metadata": {
                "resolution": kwargs["resolution"],
                "ratio": kwargs["ratio"],
            },
        }

        if model == HAPPYHORSE_T2V_MODEL:
            if not prompt:
                raise SeedanceAPIError(
                    "prompt is required for happyhorse-1.1-t2v | HappyHorse 文生视频必须填写提示词"
                )
            payload["prompt"] = prompt
            return payload

        images = media.get("images") or []
        if not images:
            raise SeedanceAPIError(
                "reference image is required for HappyHorse image/reference-to-video | "
                "HappyHorse 图生视频/参考图生视频必须连接参考图"
            )
        payload["images"] = images[:1] if model == HAPPYHORSE_I2V_MODEL else images[:MAX_HAPPYHORSE_R2V_IMAGES]
        if prompt:
            payload["prompt"] = prompt
        return payload


# ---------------------------------------------------------------------------
# Wan 2.7 Spicy image-to-video
# ---------------------------------------------------------------------------

class Wan27SpicyImageToVideo(SeedanceVideoNodeBase):
    """Wan 2.7 Spicy i2v via /v1/videos."""

    @classmethod
    def INPUT_TYPES(cls):
        optional = {
            "api_config": ("SEEDANCE_CONFIG", {
                "tooltip": "Connect Seedance API Config; otherwise SEEDANCE_API_KEY is used.",
            }),
            "skip_error": ("BOOLEAN", {
                "default": False,
                "tooltip": "On failure return a placeholder error video instead of stopping the workflow. | 失败时输出占位错误视频。",
            }),
        }

        return {
            "required": {
                "first_image": ("IMAGE", {
                    "tooltip": "Required first frame image; sent as images[0]. | 必填首帧图，作为 images[0] 提交。",
                }),
                "prompt": _prompt_input(required=False),
                "seconds": (WAN27_SPICY_SECONDS, {
                    "default": "2",
                    "tooltip": "Wan 2.7 Spicy supports 2-15 seconds. | Wan 2.7 Spicy 支持 2-15 秒。",
                }),
                "resolution": (WAN27_SPICY_RESOLUTIONS, {
                    "default": "720p",
                    "tooltip": "Wan 2.7 Spicy supports 720p or 1080p. | Wan 2.7 Spicy 支持 720p 或 1080p。",
                }),
                "negative_prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Optional negative prompt forwarded to metadata. | 可选反向提示词，透传到 metadata。",
                }),
                "audio_url": ("STRING", {
                    "default": "",
                    "tooltip": "Optional public audio URL forwarded to metadata.audio_url. | 可选公网音频 URL，透传到 metadata.audio_url。",
                }),
                "prompt_extend": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Optional prompt expansion flag forwarded to metadata.prompt_extend. | 可选提示词扩展开关，透传到 metadata.prompt_extend。",
                }),
                "seed": ("INT", {
                    "default": -1,
                    "min": -1,
                    "max": 2147483647,
                    "step": 1,
                    "tooltip": "-1 = random seed; non-negative values are forwarded to metadata.seed. | -1 表示随机种子，非负整数透传到 metadata.seed。",
                }),
            },
            "optional": optional,
        }

    @classmethod
    def VALIDATE_INPUTS(
        cls,
        prompt=None,
        seconds=None,
        resolution=None,
        negative_prompt=None,
        audio_url=None,
        seed=None,
        **kwargs,
    ):
        if seconds is not None and str(seconds) not in WAN27_SPICY_SECONDS:
            return "Wan 2.7 Spicy seconds must be 2-15 | Wan 2.7 Spicy 时长必须是 2-15 秒"
        if resolution is not None and resolution not in WAN27_SPICY_RESOLUTIONS:
            return "Wan 2.7 Spicy resolution must be 720p or 1080p | Wan 2.7 Spicy 分辨率只能是 720p 或 1080p"
        if prompt is not None and len(str(prompt)) > PROMPT_MAX_LENGTH:
            return f"prompt exceeds {PROMPT_MAX_LENGTH} characters ({len(str(prompt))})"
        if negative_prompt is not None and len(str(negative_prompt)) > PROMPT_MAX_LENGTH:
            return f"negative_prompt exceeds {PROMPT_MAX_LENGTH} characters ({len(str(negative_prompt))})"
        audio_url_text = str(audio_url or "").strip()
        if audio_url_text and not audio_url_text.startswith(("http://", "https://")):
            return "audio_url must be an http(s) URL | audio_url 必须是 http(s) URL"
        if seed is not None:
            try:
                seed_value = int(seed)
            except (TypeError, ValueError):
                return "seed must be an integer | seed 必须是整数"
            if not -1 <= seed_value <= 2147483647:
                return "seed must be -1 to 2147483647 | seed 必须在 -1 到 2147483647 之间"
        return True

    @property
    def _log_prefix(self) -> str:
        return "Wan_2_7_spicy_i2v"

    def collect_media(self, kwargs, config, progress_cb):
        first_image = kwargs.get("first_image")
        if first_image is None:
            raise SeedanceAPIError("first_image is required for wan-2.7-spicy-i2v | Wan 2.7 Spicy 必须连接首帧图")

        url = upload_media(
            image_to_png_bytes(first_image),
            "wan27_spicy_first_frame.png",
            "image/png",
            config,
            logger_prefix=self._log_prefix,
        )
        progress_cb(1.0)
        return {"images": [url]}

    def build_payload(self, kwargs, media):
        images = media.get("images") or []
        if not images:
            raise SeedanceAPIError("first_image is required for wan-2.7-spicy-i2v | Wan 2.7 Spicy 必须连接首帧图")

        metadata: Dict[str, Any] = {"resolution": kwargs["resolution"]}
        negative_prompt = str(kwargs.get("negative_prompt") or "").strip()
        if negative_prompt:
            metadata["negative_prompt"] = negative_prompt

        audio_url = str(kwargs.get("audio_url") or "").strip()
        if audio_url:
            metadata["audio_url"] = audio_url

        if bool(kwargs.get("prompt_extend", False)):
            metadata["prompt_extend"] = True

        seed = kwargs.get("seed", -1)
        if seed is not None and int(seed) >= 0:
            metadata["seed"] = int(seed)

        payload: Dict[str, Any] = {
            "model": WAN27_SPICY_I2V_MODEL,
            "seconds": str(kwargs["seconds"]),
            "metadata": metadata,
            "images": images[:1],
        }

        prompt = str(kwargs.get("prompt") or "").strip()
        if prompt:
            payload["prompt"] = prompt
        return payload


# ---------------------------------------------------------------------------
# Kling video
# ---------------------------------------------------------------------------

class KlingVideo(SeedanceVideoNodeBase):
    """Kling t2v/i2v/r2v via /v1/videos."""

    @classmethod
    def INPUT_TYPES(cls):
        optional: Dict[str, tuple] = {}
        for i in range(1, MAX_KLING_REFERENCE_IMAGES + 1):
            optional[f"image{i}"] = ("IMAGE", {
                "tooltip": (
                    f"Optional Kling image {i}. i2v uses image1 and optionally image2 "
                    f"as an end frame; r2v uses connected images in compacted order. | "
                    f"可选 Kling 图片 {i}；图生视频使用 image1，可选 image2 作为尾帧；"
                    "r2v 按已连接图片顺序提交。"
                ),
            })
        optional["api_config"] = ("SEEDANCE_CONFIG", {
            "tooltip": "Connect Seedance API Config; otherwise SEEDANCE_API_KEY is used.",
        })
        optional["skip_error"] = ("BOOLEAN", {
            "default": False,
            "tooltip": "On failure return a placeholder error video instead of stopping the workflow. | 失败时输出占位错误视频。",
        })

        return {
            "required": {
                "model": (KLING_VIDEO_MODELS, {
                    "default": KLING_T2V_MODELS[0],
                    "tooltip": (
                        "Kling task type. t2v uses prompt; i2v uses image1 and optional image2; "
                        "o3-r2v uses up to 4 images. | Kling 任务类型：文生、图生/首尾帧、O3 参考生视频。"
                    ),
                }),
                "prompt": _prompt_input(required=False),
                "seconds": (KLING_SECONDS, {
                    "default": "5",
                    "tooltip": "Kling supports 5 or 10 seconds. | Kling 支持 5 或 10 秒。",
                }),
                "ratio": (RATIOS, {
                    "default": "16:9",
                    "tooltip": "Aspect ratio forwarded as metadata.ratio when not adaptive. | 非 adaptive 时透传为 metadata.ratio。",
                }),
                "negative_prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Optional negative prompt forwarded to metadata. | 可选反向提示词，透传到 metadata。",
                }),
            },
            "optional": optional,
        }

    @classmethod
    def VALIDATE_INPUTS(
        cls,
        model=None,
        prompt=None,
        seconds=None,
        ratio=None,
        negative_prompt=None,
        strict=False,
        **kwargs,
    ):
        if model not in (None, *KLING_VIDEO_MODELS):
            return f"unsupported Kling model: {model}"
        if seconds is not None and str(seconds) not in KLING_SECONDS:
            return "Kling seconds must be 5 or 10 | Kling 时长必须是 5 或 10 秒"
        if ratio is not None and ratio not in RATIOS:
            return f"unsupported ratio: {ratio}"
        if prompt is not None and len(str(prompt)) > PROMPT_MAX_LENGTH:
            return f"prompt exceeds {PROMPT_MAX_LENGTH} characters ({len(str(prompt))})"
        if negative_prompt is not None and len(str(negative_prompt)) > PROMPT_MAX_LENGTH:
            return f"negative_prompt exceeds {PROMPT_MAX_LENGTH} characters ({len(str(negative_prompt))})"
        if strict and model in (*KLING_T2V_MODELS, *KLING_R2V_MODELS) and not str(prompt or "").strip():
            return "prompt is required for Kling text/reference-to-video | Kling 文生视频/参考生视频必须填写提示词"
        return True

    @property
    def _log_prefix(self) -> str:
        return "Kling_video"

    def _connected_images(self, kwargs: Dict[str, Any]) -> List[Tuple[int, Any]]:
        slots = [
            (i, kwargs.get(f"image{i}"))
            for i in range(1, MAX_KLING_REFERENCE_IMAGES + 1)
            if kwargs.get(f"image{i}") is not None
        ]
        connected = [i for i, _ in slots]
        if connected and connected != list(range(1, len(connected) + 1)):
            print(
                f"[{self._log_prefix}] WARNING: Kling image slots {connected} have gaps; "
                f"they will be compacted to imageUrls order 1..{len(connected)}."
            )
        return slots

    def _required_image_slots(self, kwargs: Dict[str, Any]) -> Tuple[List[Tuple[int, Any]], str]:
        model = kwargs.get("model")
        connected = self._connected_images(kwargs)
        by_slot = {slot: image for slot, image in connected}
        if model in KLING_T2V_MODELS:
            return [], ""
        if model in KLING_I2V_MODELS:
            slots = [(slot, by_slot[slot]) for slot in (1, 2) if slot in by_slot]
            return slots, "image1 is required for Kling image-to-video | Kling 图生视频必须连接 image1"
        if model in KLING_R2V_MODELS:
            return connected[:MAX_KLING_REFERENCE_IMAGES], (
                "at least one image is required for Kling reference-to-video | Kling 参考生视频至少需要 1 张图"
            )
        return [], f"unsupported Kling model: {model}"

    def collect_media(self, kwargs, config, progress_cb):
        image_slots, required_message = self._required_image_slots(kwargs)
        model = kwargs.get("model")
        if model in KLING_T2V_MODELS:
            progress_cb(1.0)
            return {}
        if not image_slots:
            raise SeedanceAPIError(required_message)

        urls = []
        for done, (slot, image) in enumerate(image_slots, start=1):
            url = upload_media(
                image_to_png_bytes(image),
                f"kling_reference_{slot}.png",
                "image/png",
                config,
                logger_prefix=self._log_prefix,
            )
            urls.append(url)
            progress_cb(done / len(image_slots))
        return {"images": urls}

    def build_payload(self, kwargs, media):
        model = kwargs["model"]
        prompt = str(kwargs.get("prompt") or "").strip()
        validation = self.VALIDATE_INPUTS(
            model=model,
            prompt=prompt,
            seconds=kwargs.get("seconds"),
            ratio=kwargs.get("ratio"),
            negative_prompt=kwargs.get("negative_prompt"),
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        metadata: Dict[str, Any] = {}
        ratio = str(kwargs.get("ratio") or "").strip()
        if ratio and ratio != "adaptive":
            metadata["ratio"] = ratio
        negative_prompt = str(kwargs.get("negative_prompt") or "").strip()
        if negative_prompt:
            metadata["negative_prompt"] = negative_prompt

        payload: Dict[str, Any] = {
            "model": model,
            "seconds": str(kwargs["seconds"]),
            "metadata": metadata,
        }
        if prompt:
            payload["prompt"] = prompt

        images = media.get("images") or []
        if model in KLING_I2V_MODELS:
            if not images:
                raise SeedanceAPIError("image1 is required for Kling image-to-video | Kling 图生视频必须连接 image1")
            payload["images"] = images[:2]
        elif model in KLING_R2V_MODELS:
            if not images:
                raise SeedanceAPIError("at least one image is required for Kling reference-to-video | Kling 参考生视频至少需要 1 张图")
            payload["images"] = images[:MAX_KLING_REFERENCE_IMAGES]
        return payload


class KlingEditVideo(SeedanceVideoNodeBase):
    """Kling O3 video edit via /v1/videos and metadata.content video_url."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": (KLING_EDIT_MODELS, {
                    "default": KLING_EDIT_MODELS[0],
                    "tooltip": "Kling O3 edit model. | Kling O3 视频编辑模型。",
                }),
                "video_url": ("STRING", {
                    "default": "",
                    "tooltip": "Optional public MP4 URL. Leave empty when connecting input_video. | 可选公网 MP4 直链；连接 input_video 时可留空。",
                }),
                "prompt": _prompt_input(required=True),
                "seconds": (KLING_SECONDS, {
                    "default": "5",
                    "tooltip": "Kling edit supports 5 or 10 seconds. | Kling 编辑支持 5 或 10 秒。",
                }),
            },
            "optional": {
                "input_video": ("VIDEO", {
                    "tooltip": "Optional local ComfyUI video to upload for Kling edit. | 可选本地 ComfyUI 视频，节点会先上传再编辑。",
                }),
                "api_config": ("SEEDANCE_CONFIG", {
                    "tooltip": "Connect Seedance API Config; otherwise SEEDANCE_API_KEY is used.",
                }),
                "skip_error": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "On failure return a placeholder error video instead of stopping the workflow. | 失败时输出占位错误视频。",
                }),
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, model=None, video_url=None, prompt=None, seconds=None, strict=False, **kwargs):
        if model not in (None, *KLING_EDIT_MODELS):
            return f"unsupported Kling edit model: {model}"
        if seconds is not None and str(seconds) not in KLING_SECONDS:
            return "Kling edit seconds must be 5 or 10 | Kling 编辑时长必须是 5 或 10 秒"
        url_text = str(video_url or "").strip()
        if url_text and not url_text.startswith(("http://", "https://")):
            return "video_url must be an http(s) URL | video_url 必须是 http(s) URL"
        prompt_text = str(prompt or "").strip()
        if strict and not prompt_text:
            return "prompt is required for Kling edit | Kling 编辑必须填写提示词"
        if len(prompt_text) > PROMPT_MAX_LENGTH:
            return f"prompt exceeds {PROMPT_MAX_LENGTH} characters ({len(prompt_text)})"
        return True

    @property
    def _log_prefix(self) -> str:
        return "Kling_edit"

    def collect_media(self, kwargs, config, progress_cb):
        video_url = str(kwargs.get("video_url") or "").strip()
        if video_url:
            progress_cb(1.0)
            return {"video_url": video_url}

        input_video = kwargs.get("input_video")
        if input_video is None:
            raise SeedanceAPIError(
                "connect input_video or provide video_url for Kling edit | Kling 编辑需要连接 input_video 或填写 video_url"
            )

        video_bytes, ext = video_to_bytes(input_video)
        video_mime = {
            "mp4": "video/mp4",
            "mov": "video/quicktime",
            "avi": "video/x-msvideo",
            "mkv": "video/x-matroska",
        }.get(ext, "video/mp4")
        url = upload_media(
            video_bytes,
            f"kling_edit_input.{ext}",
            video_mime,
            config,
            logger_prefix=self._log_prefix,
        )
        progress_cb(1.0)
        return {"video_url": url}

    def build_payload(self, kwargs, media):
        video_url = str(media.get("video_url") or "").strip()
        if not video_url:
            raise SeedanceAPIError("video_url is required for Kling edit | Kling 编辑必须提供视频直链")

        prompt = str(kwargs.get("prompt") or "").strip()
        validation = self.VALIDATE_INPUTS(
            model=kwargs.get("model"),
            video_url=video_url,
            prompt=prompt,
            seconds=kwargs.get("seconds"),
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        return {
            "model": kwargs["model"],
            "prompt": prompt,
            "seconds": str(kwargs["seconds"]),
            "metadata": {
                "content": [
                    {
                        "type": "video_url",
                        "video_url": {"url": video_url},
                    }
                ],
            },
        }


# ---------------------------------------------------------------------------
# Hailuo 2.3 video
# ---------------------------------------------------------------------------

class Hailuo23Video(SeedanceVideoNodeBase):
    """Hailuo 2.3 t2v/i2v/fast-i2v via /v1/videos."""

    @classmethod
    def INPUT_TYPES(cls):
        optional = {
            "first_image": ("IMAGE", {
                "tooltip": (
                    "Required for Hailuo i2v / fast-i2v models; sent as images[0]. "
                    "Short edge must be greater than 300px and aspect ratio must be "
                    "between 2:5 and 5:2. | Hailuo 图生视频 / fast 图生视频必填，"
                    "作为 images[0] 提交；短边需大于 300px，宽高比需在 2:5 到 5:2 之间。"
                ),
            }),
            "api_config": ("SEEDANCE_CONFIG", {
                "tooltip": "Connect Seedance API Config; otherwise SEEDANCE_API_KEY is used.",
            }),
            "skip_error": ("BOOLEAN", {
                "default": False,
                "tooltip": "On failure return a placeholder error video instead of stopping the workflow. | 失败时输出占位错误视频。",
            }),
        }

        return {
            "required": {
                "model": (HAILUO23_MODELS, {
                    "default": HAILUO23_T2V_MODELS[0],
                    "tooltip": (
                        "Hailuo 2.3 task type. t2v uses prompt only; i2v / fast-i2v "
                        "uses first_image. | Hailuo 2.3 任务类型：文生视频只用提示词，"
                        "图生视频 / fast 图生视频使用首帧图。"
                    ),
                }),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Text prompt, up to 2000 characters for Hailuo 2.3. | Hailuo 2.3 提示词最多 2000 字符。",
                }),
                "seconds": (HAILUO23_SECONDS, {
                    "default": "6",
                    "tooltip": "Hailuo 2.3 supports 6 or 10 seconds; 1080p is limited to 6 seconds. | 支持 6 或 10 秒；1080p 仅支持 6 秒。",
                }),
                "resolution": (HAILUO23_RESOLUTIONS, {
                    "default": "768p",
                    "tooltip": "Hailuo 2.3 supports 768p or 1080p; 1080p is limited to 6 seconds. | 支持 768p 或 1080p；1080p 仅支持 6 秒。",
                }),
                "ratio": (RATIOS, {
                    "default": "16:9",
                    "tooltip": "Used for Hailuo text-to-video only; image-to-video follows the input image. | 仅文生视频使用；图生视频跟随输入图片比例。",
                }),
            },
            "optional": optional,
        }

    @classmethod
    def VALIDATE_INPUTS(
        cls,
        model=None,
        prompt=None,
        seconds=None,
        resolution=None,
        ratio=None,
        strict=False,
        **kwargs,
    ):
        if model not in (None, *HAILUO23_MODELS):
            return f"unsupported Hailuo 2.3 model: {model}"
        if seconds is not None and str(seconds) not in HAILUO23_SECONDS:
            return "Hailuo 2.3 seconds must be 6 or 10 | Hailuo 2.3 时长必须是 6 或 10 秒"
        if resolution is not None and resolution not in HAILUO23_RESOLUTIONS:
            return "Hailuo 2.3 resolution must be 768p or 1080p | Hailuo 2.3 分辨率只能是 768p 或 1080p"
        if str(seconds or "") == "10" and resolution == "1080p":
            return "Hailuo 2.3 1080p only supports 6 seconds | Hailuo 2.3 的 1080p 仅支持 6 秒"
        if ratio is not None and ratio not in RATIOS:
            return f"unsupported ratio: {ratio}"
        prompt_text = str(prompt or "")
        if len(prompt_text) > HAILUO23_PROMPT_MAX_LENGTH:
            return f"prompt exceeds {HAILUO23_PROMPT_MAX_LENGTH} characters ({len(prompt_text)})"
        if strict and model in HAILUO23_T2V_MODELS and not prompt_text.strip():
            return "prompt is required for Hailuo text-to-video | Hailuo 文生视频必须填写提示词"
        return True

    @property
    def _log_prefix(self) -> str:
        return "Hailuo_2_3_video"

    def _validate_first_image_shape(self, image: Any):
        shape = getattr(image, "shape", None)
        if not shape or len(shape) < 3:
            return

        if len(shape) >= 4:
            height = int(shape[1])
            width = int(shape[2])
        else:
            height = int(shape[0])
            width = int(shape[1])

        short_edge = min(width, height)
        if short_edge < HAILUO23_MIN_IMAGE_SHORT_EDGE:
            raise SeedanceAPIError(
                "Hailuo first_image short edge must be greater than 300px | "
                "Hailuo 首帧图短边必须大于 300px"
            )

        ratio = width / height if height else 0
        if not HAILUO23_MIN_ASPECT_RATIO <= ratio <= HAILUO23_MAX_ASPECT_RATIO:
            raise SeedanceAPIError(
                "Hailuo first_image aspect ratio must be between 2:5 and 5:2 | "
                "Hailuo 首帧图宽高比必须在 2:5 到 5:2 之间"
            )

    def collect_media(self, kwargs, config, progress_cb):
        model = kwargs.get("model")
        if model in HAILUO23_T2V_MODELS:
            progress_cb(1.0)
            return {}

        first_image = kwargs.get("first_image")
        if first_image is None:
            raise SeedanceAPIError(
                "first_image is required for Hailuo image-to-video | Hailuo 图生视频必须连接首帧图"
            )

        self._validate_first_image_shape(first_image)
        url = upload_media(
            image_to_png_bytes(first_image),
            "hailuo23_first_frame.png",
            "image/png",
            config,
            logger_prefix=self._log_prefix,
        )
        progress_cb(1.0)
        return {"images": [url]}

    def build_payload(self, kwargs, media):
        model = kwargs["model"]
        prompt = str(kwargs.get("prompt") or "").strip()
        validation = self.VALIDATE_INPUTS(
            model=model,
            prompt=prompt,
            seconds=kwargs.get("seconds"),
            resolution=kwargs.get("resolution"),
            ratio=kwargs.get("ratio"),
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        metadata: Dict[str, Any] = {"resolution": kwargs["resolution"]}
        payload: Dict[str, Any] = {
            "model": model,
            "seconds": str(kwargs["seconds"]),
            "metadata": metadata,
        }

        if model in HAILUO23_T2V_MODELS:
            ratio = str(kwargs.get("ratio") or "").strip()
            if ratio and ratio != "adaptive":
                metadata["ratio"] = ratio
            payload["prompt"] = prompt
            return payload

        images = media.get("images") or []
        if not images:
            raise SeedanceAPIError(
                "first_image is required for Hailuo image-to-video | Hailuo 图生视频必须连接首帧图"
            )
        payload["images"] = images[:1]
        if prompt:
            payload["prompt"] = prompt
        return payload


# ---------------------------------------------------------------------------
# Vidu Q3 video
# ---------------------------------------------------------------------------

class ViduQ3Video(SeedanceVideoNodeBase):
    """Vidu Q3 t2v/i2v/start-end/r2v via /v1/videos."""

    @classmethod
    def INPUT_TYPES(cls):
        optional: Dict[str, tuple] = {}
        for i in range(1, MAX_VIDU_REFERENCE_IMAGES + 1):
            optional[f"image{i}"] = ("IMAGE", {
                "tooltip": (
                    f"Optional Vidu image {i}. i2v uses image1; start-end uses image1+image2; "
                    f"r2v uses connected images in compacted order. | 可选 Vidu 图片 {i}；"
                    "i2v 用 image1；首尾帧用 image1+image2；r2v 按已连接图片顺序提交。"
                ),
            })
        optional["api_config"] = ("SEEDANCE_CONFIG", {
            "tooltip": "Connect Seedance API Config; otherwise SEEDANCE_API_KEY is used.",
        })
        optional["skip_error"] = ("BOOLEAN", {
            "default": False,
            "tooltip": "On failure return a placeholder error video instead of stopping the workflow. | 失败时输出占位错误视频。",
        })

        return {
            "required": {
                "model": (VIDU_VIDEO_MODELS, {
                    "default": "vidu-q3-turbo-t2v",
                    "tooltip": (
                        "Vidu Q3 task type. t2v uses prompt; i2v uses image1; "
                        "start-end uses image1+image2; r2v uses up to 9 images. | "
                        "Vidu Q3 任务类型：文生、图生、首尾帧、参考生视频。"
                    ),
                }),
                "prompt": _prompt_input(required=False),
                "seconds": (VIDU_SECONDS, {
                    "default": "4",
                    "tooltip": "Video duration in seconds, submitted as a string. | 视频时长，按字符串提交。",
                }),
                "ratio": (RATIOS, {
                    "default": "16:9",
                    "tooltip": "Aspect ratio forwarded as metadata.ratio for Vidu aspectRatio mapping. | 画幅会通过 metadata.ratio 映射给 Vidu aspectRatio。",
                }),
                "resolution": (VIDU_RESOLUTIONS, {
                    "default": "default",
                    "tooltip": "Optional metadata.resolution; default leaves the API default. | 可选 metadata.resolution；default 使用 API 默认值。",
                }),
                "seed": ("INT", {
                    "default": -1,
                    "min": -1,
                    "max": 2147483647,
                    "step": 1,
                    "tooltip": "-1 = random seed; non-negative values are forwarded to metadata.seed. | -1 表示随机种子，非负整数透传到 metadata.seed。",
                }),
            },
            "optional": optional,
        }

    @classmethod
    def VALIDATE_INPUTS(
        cls,
        model=None,
        prompt=None,
        seconds=None,
        ratio=None,
        resolution=None,
        seed=None,
        strict=False,
        **kwargs,
    ):
        if model not in (None, *VIDU_VIDEO_MODELS):
            return f"unsupported Vidu Q3 model: {model}"
        if seconds is not None and str(seconds) not in VIDU_SECONDS:
            return "Vidu Q3 seconds must be 4-15 | Vidu Q3 时长必须是 4-15 秒"
        if ratio is not None and ratio not in RATIOS:
            return f"unsupported ratio: {ratio}"
        if resolution is not None and resolution not in VIDU_RESOLUTIONS:
            return "Vidu Q3 resolution must be default, 720p, or 1080p | Vidu Q3 分辨率只能是 default、720p 或 1080p"
        if prompt is not None and len(str(prompt)) > PROMPT_MAX_LENGTH:
            return f"prompt exceeds {PROMPT_MAX_LENGTH} characters ({len(str(prompt))})"
        if strict and model in VIDU_T2V_MODELS and not str(prompt or "").strip():
            return "prompt is required for Vidu text-to-video | Vidu 文生视频必须填写提示词"
        if seed is not None:
            try:
                seed_value = int(seed)
            except (TypeError, ValueError):
                return "seed must be an integer | seed 必须是整数"
            if not -1 <= seed_value <= 2147483647:
                return "seed must be -1 to 2147483647 | seed 必须在 -1 到 2147483647 之间"
        return True

    @property
    def _log_prefix(self) -> str:
        return "Vidu_Q3_video"

    def _connected_images(self, kwargs: Dict[str, Any]) -> List[Tuple[int, Any]]:
        slots = [
            (i, kwargs.get(f"image{i}"))
            for i in range(1, MAX_VIDU_REFERENCE_IMAGES + 1)
            if kwargs.get(f"image{i}") is not None
        ]
        connected = [i for i, _ in slots]
        if connected and connected != list(range(1, len(connected) + 1)):
            print(
                f"[{self._log_prefix}] WARNING: Vidu image slots {connected} have gaps; "
                f"they will be compacted to imageUrls order 1..{len(connected)}."
            )
        return slots

    def _required_image_slots(self, kwargs: Dict[str, Any]) -> Tuple[List[Tuple[int, Any]], str]:
        model = kwargs.get("model")
        connected = self._connected_images(kwargs)
        by_slot = {slot: image for slot, image in connected}

        if model in VIDU_T2V_MODELS:
            return [], ""
        if model in VIDU_I2V_MODELS:
            return ([(1, by_slot[1])] if 1 in by_slot else []), (
                "image1 is required for Vidu image-to-video | Vidu 图生视频必须连接 image1"
            )
        if model in VIDU_START_END_MODELS:
            slots = [(slot, by_slot[slot]) for slot in (1, 2) if slot in by_slot]
            return slots, "image1 and image2 are required for Vidu start-end | Vidu 首尾帧必须连接 image1 和 image2"
        if model in VIDU_R2V_MODELS:
            return connected[:MAX_VIDU_REFERENCE_IMAGES], (
                "at least one image is required for Vidu reference-to-video | Vidu 参考生视频至少需要 1 张图"
            )
        return [], f"unsupported Vidu Q3 model: {model}"

    def collect_media(self, kwargs, config, progress_cb):
        image_slots, required_message = self._required_image_slots(kwargs)
        model = kwargs.get("model")
        if model in VIDU_T2V_MODELS:
            progress_cb(1.0)
            return {}
        if model in VIDU_START_END_MODELS and len(image_slots) != 2:
            raise SeedanceAPIError(required_message)
        if model not in VIDU_T2V_MODELS and not image_slots:
            raise SeedanceAPIError(required_message)

        urls = []
        for done, (slot, image) in enumerate(image_slots, start=1):
            url = upload_media(
                image_to_png_bytes(image),
                f"vidu_q3_reference_{slot}.png",
                "image/png",
                config,
                logger_prefix=self._log_prefix,
            )
            urls.append(url)
            progress_cb(done / len(image_slots))
        return {"images": urls}

    def build_payload(self, kwargs, media):
        model = kwargs["model"]
        prompt = str(kwargs.get("prompt") or "").strip()
        validation = self.VALIDATE_INPUTS(
            model=model,
            prompt=prompt,
            seconds=kwargs.get("seconds"),
            ratio=kwargs.get("ratio"),
            resolution=kwargs.get("resolution"),
            seed=kwargs.get("seed"),
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        metadata: Dict[str, Any] = {}
        ratio = str(kwargs.get("ratio") or "").strip()
        if ratio and ratio != "adaptive":
            metadata["ratio"] = ratio
        resolution = str(kwargs.get("resolution") or "").strip()
        if resolution and resolution != "default":
            metadata["resolution"] = resolution
        seed = kwargs.get("seed", -1)
        if seed is not None and int(seed) >= 0:
            metadata["seed"] = int(seed)

        payload: Dict[str, Any] = {
            "model": model,
            "seconds": str(kwargs["seconds"]),
            "metadata": metadata,
        }
        if prompt:
            payload["prompt"] = prompt

        images = media.get("images") or []
        if model in VIDU_I2V_MODELS:
            if not images:
                raise SeedanceAPIError("image1 is required for Vidu image-to-video | Vidu 图生视频必须连接 image1")
            payload["images"] = images[:1]
        elif model in VIDU_START_END_MODELS:
            if len(images) < 2:
                raise SeedanceAPIError("image1 and image2 are required for Vidu start-end | Vidu 首尾帧必须连接 image1 和 image2")
            payload["images"] = images[:2]
        elif model in VIDU_R2V_MODELS:
            if not images:
                raise SeedanceAPIError("at least one image is required for Vidu reference-to-video | Vidu 参考生视频至少需要 1 张图")
            payload["images"] = images[:MAX_VIDU_REFERENCE_IMAGES]
        return payload


class ViduQ3ShortPlay(SeedanceVideoNodeBase):
    """Vidu Q3 short-play generation via /v1/videos."""

    @classmethod
    def INPUT_TYPES(cls):
        optional: Dict[str, tuple] = {}
        for i in range(1, MAX_VIDU_SHORT_PLAY_ASSETS + 1):
            optional[f"asset_image{i}"] = ("IMAGE", {
                "tooltip": (
                    f"Optional short-play reference asset {i}. At least asset_image1 is required. | "
                    f"短剧参考资产图 {i}，至少需要 asset_image1。"
                ),
            })
        optional["api_config"] = ("SEEDANCE_CONFIG", {
            "tooltip": "Connect Seedance API Config; otherwise SEEDANCE_API_KEY is used.",
        })
        optional["skip_error"] = ("BOOLEAN", {
            "default": False,
            "tooltip": "On failure return a placeholder error video instead of stopping the workflow. | 失败时输出占位错误视频。",
        })

        return {
            "required": {
                "model": (VIDU_SHORT_PLAY_MODELS, {
                    "default": "vidu-q3-drama-short-play",
                    "tooltip": "Vidu Q3 short-play model. | Vidu Q3 短剧成片模型。",
                }),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Short-play script content; forwarded as prompt/scriptContent. | 短剧脚本内容，会作为 prompt/scriptContent 提交。",
                }),
                "script_name": ("STRING", {
                    "default": "Vidu short play",
                    "tooltip": "Forwarded as metadata.script_name for Vidu scriptName. | 透传为 metadata.script_name，对应 Vidu scriptName。",
                }),
                "resolution": (["1080p"], {
                    "default": "1080p",
                    "tooltip": "Required by Vidu Q3 short-play. | Vidu Q3 短剧成片要求 1080p。",
                }),
                "duration": (VIDU_SHORT_PLAY_DURATIONS, {
                    "default": "8",
                    "tooltip": "Short-play duration in seconds, 8-12. | 短剧成片时长，8-12 秒。",
                }),
                "aspect_ratio": (VIDU_SHORT_PLAY_ASPECT_RATIOS, {
                    "default": "9:16",
                    "tooltip": "Short-play aspect ratio. | 短剧成片画幅。",
                }),
                "style": ("STRING", {
                    "default": "realistic",
                    "tooltip": "Video style, up to 30 characters. | 视频风格，最多 30 字符。",
                }),
                "asset_type": (VIDU_SHORT_PLAY_ASSET_TYPES, {
                    "default": "character",
                    "tooltip": "Type used for all connected reference assets. | 所有连接参考资产使用的类型。",
                }),
                "asset_name_prefix": ("STRING", {
                    "default": "Asset",
                    "tooltip": "Asset names are built as '<prefix> 1', '<prefix> 2'. | 资产名称会生成为“前缀 1、前缀 2”。",
                }),
                "asset_description": ("STRING", {
                    "default": "Reference asset",
                    "tooltip": "Description used for all connected assets. | 所有连接资产使用的描述。",
                }),
            },
            "optional": optional,
        }

    @classmethod
    def VALIDATE_INPUTS(
        cls,
        model=None,
        prompt=None,
        script_name=None,
        resolution=None,
        duration=None,
        aspect_ratio=None,
        style=None,
        asset_type=None,
        asset_name_prefix=None,
        asset_description=None,
        strict=False,
        **kwargs,
    ):
        if model not in (None, *VIDU_SHORT_PLAY_MODELS):
            return f"unsupported Vidu short-play model: {model}"
        prompt_text = str(prompt or "").strip()
        if strict and not prompt_text:
            return "prompt/script content is required for Vidu short-play | Vidu 短剧成片必须填写脚本内容"
        if len(prompt_text) > PROMPT_MAX_LENGTH:
            return f"prompt exceeds {PROMPT_MAX_LENGTH} characters ({len(prompt_text)})"
        script_name_text = str(script_name or "").strip()
        if strict and not script_name_text:
            return "script_name is required for Vidu short-play | Vidu 短剧成片必须填写 script_name"
        if len(script_name_text) > 20:
            return "script_name must be 20 characters or fewer | script_name 不能超过 20 字符"
        if resolution is not None and resolution != "1080p":
            return "Vidu short-play resolution must be 1080p | Vidu 短剧成片分辨率必须是 1080p"
        if duration is not None and str(duration) not in VIDU_SHORT_PLAY_DURATIONS:
            return "Vidu short-play duration must be 8-12 | Vidu 短剧成片时长必须是 8-12 秒"
        if aspect_ratio is not None and aspect_ratio not in VIDU_SHORT_PLAY_ASPECT_RATIOS:
            return "Vidu short-play aspect_ratio must be 9:16 or 16:9 | Vidu 短剧成片画幅必须是 9:16 或 16:9"
        if style is not None and len(str(style)) > 30:
            return "style must be 30 characters or fewer | style 不能超过 30 字符"
        if asset_type is not None and asset_type not in VIDU_SHORT_PLAY_ASSET_TYPES:
            return f"unsupported asset_type: {asset_type}"
        if asset_name_prefix is not None and not str(asset_name_prefix).strip():
            return "asset_name_prefix is required | asset_name_prefix 必须填写"
        if asset_description is not None and not str(asset_description).strip():
            return "asset_description is required | asset_description 必须填写"
        return True

    @property
    def _log_prefix(self) -> str:
        return "Vidu_Q3_short_play"

    def _connected_asset_images(self, kwargs: Dict[str, Any]) -> List[Tuple[int, Any]]:
        slots = [
            (i, kwargs.get(f"asset_image{i}"))
            for i in range(1, MAX_VIDU_SHORT_PLAY_ASSETS + 1)
            if kwargs.get(f"asset_image{i}") is not None
        ]
        connected = [i for i, _ in slots]
        if connected and connected != list(range(1, len(connected) + 1)):
            print(
                f"[{self._log_prefix}] WARNING: short-play asset slots {connected} have gaps; "
                f"they will be compacted to assets order 1..{len(connected)}."
            )
        return slots

    def collect_media(self, kwargs, config, progress_cb):
        asset_slots = self._connected_asset_images(kwargs)
        if not asset_slots:
            raise SeedanceAPIError(
                "asset_image1 is required for Vidu short-play | Vidu 短剧成片至少需要 asset_image1"
            )

        urls = []
        for done, (slot, image) in enumerate(asset_slots, start=1):
            url = upload_media(
                image_to_png_bytes(image),
                f"vidu_short_play_asset_{slot}.png",
                "image/png",
                config,
                logger_prefix=self._log_prefix,
            )
            urls.append(url)
            progress_cb(done / len(asset_slots))
        return {"asset_urls": urls}

    def build_payload(self, kwargs, media):
        prompt = str(kwargs.get("prompt") or "").strip()
        script_name = str(kwargs.get("script_name") or "").strip()
        validation = self.VALIDATE_INPUTS(
            model=kwargs.get("model"),
            prompt=prompt,
            script_name=script_name,
            resolution=kwargs.get("resolution"),
            duration=kwargs.get("duration"),
            aspect_ratio=kwargs.get("aspect_ratio"),
            style=kwargs.get("style"),
            asset_type=kwargs.get("asset_type"),
            asset_name_prefix=kwargs.get("asset_name_prefix"),
            asset_description=kwargs.get("asset_description"),
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)
        asset_urls = media.get("asset_urls") or []
        if not asset_urls:
            raise SeedanceAPIError(
                "at least one uploaded asset is required for Vidu short-play | Vidu 短剧成片至少需要 1 个参考资产"
            )

        asset_type = kwargs.get("asset_type") or "character"
        asset_prefix = str(kwargs.get("asset_name_prefix") or "Asset").strip()
        asset_description = str(kwargs.get("asset_description") or "Reference asset").strip()
        assets = [
            {
                "id": str(i),
                "type": asset_type,
                "name": f"{asset_prefix} {i}",
                "image_uri": url,
                "description": asset_description,
            }
            for i, url in enumerate(asset_urls[:MAX_VIDU_SHORT_PLAY_ASSETS], start=1)
        ]
        return {
            "model": kwargs["model"],
            "prompt": prompt,
            "metadata": {
                "script_name": script_name,
                "resolution": kwargs.get("resolution", "1080p"),
                "duration": int(kwargs.get("duration", "8")),
                "aspect_ratio": kwargs.get("aspect_ratio", "9:16"),
                "style": str(kwargs.get("style") or "realistic").strip(),
                "assets": assets,
            },
        }


# ---------------------------------------------------------------------------
# Zhenzhen Upscaler video super-resolution
# ---------------------------------------------------------------------------

class ZhenzhenUpscalerVideo(SeedanceVideoNodeBase):
    """Video super-resolution via zhenzhen-upscaler and /v1/videos."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_url": ("STRING", {
                    "default": "",
                    "tooltip": (
                        "Optional public MP4 URL. Leave empty when connecting input_video. | "
                        "可选公网 MP4 直链；连接 input_video 时可留空。"
                    ),
                }),
                "resolution": (ZHENZHEN_UPSCALER_RESOLUTIONS, {
                    "default": "1080p",
                    "tooltip": "Target resolution: 720p, 1080p, 2k, or 4k. | 目标分辨率：720p、1080p、2k 或 4k。",
                }),
            },
            "optional": {
                "input_video": ("VIDEO", {
                    "tooltip": "Optional local ComfyUI video to upload for upscaling. | 可选本地 ComfyUI 视频，节点会先上传再超分。",
                }),
                "api_config": ("SEEDANCE_CONFIG", {
                    "tooltip": "Connect Seedance API Config; otherwise SEEDANCE_API_KEY is used.",
                }),
                "skip_error": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "On failure return a placeholder error video instead of stopping the workflow. | 失败时输出占位错误视频。",
                }),
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, video_url=None, resolution=None, **kwargs):
        if resolution is not None and resolution not in ZHENZHEN_UPSCALER_RESOLUTIONS:
            return (
                "Zhenzhen Upscaler resolution must be 720p, 1080p, 2k, or 4k | "
                "Zhenzhen Upscaler 分辨率只能是 720p、1080p、2k 或 4k"
            )
        url_text = str(video_url or "").strip()
        if url_text and not url_text.startswith(("http://", "https://")):
            return "video_url must be an http(s) URL | video_url 必须是 http(s) URL"
        return True

    @property
    def _log_prefix(self) -> str:
        return "Zhenzhen_upscaler"

    def collect_media(self, kwargs, config, progress_cb):
        video_url = str(kwargs.get("video_url") or "").strip()
        if video_url:
            progress_cb(1.0)
            return {"video_url": video_url}

        input_video = kwargs.get("input_video")
        if input_video is None:
            raise SeedanceAPIError(
                "connect input_video or provide video_url for zhenzhen-upscaler | "
                "zhenzhen-upscaler 需要连接 input_video 或填写 video_url"
            )

        video_bytes, ext = video_to_bytes(input_video)
        video_mime = {
            "mp4": "video/mp4",
            "mov": "video/quicktime",
            "avi": "video/x-msvideo",
            "mkv": "video/x-matroska",
        }.get(ext, "video/mp4")
        url = upload_media(
            video_bytes,
            f"zhenzhen_upscaler_input.{ext}",
            video_mime,
            config,
            logger_prefix=self._log_prefix,
        )
        progress_cb(1.0)
        return {"video_url": url}

    def build_payload(self, kwargs, media):
        video_url = str(media.get("video_url") or "").strip()
        if not video_url:
            raise SeedanceAPIError(
                "video_url is required for zhenzhen-upscaler | zhenzhen-upscaler 必须提供视频直链"
            )

        return {
            "model": ZHENZHEN_UPSCALER_MODEL,
            "prompt": "upscale",
            "metadata": {
                "resolution": kwargs["resolution"],
                "content": [
                    {
                        "type": "video_url",
                        "video_url": {"url": video_url},
                    }
                ],
            },
        }


# ---------------------------------------------------------------------------
# Multimodal Video
# ---------------------------------------------------------------------------

class SeedanceMultimodalVideo(SeedanceVideoNodeBase):
    """Multimodal video: up to 9 images + 3 videos + 3 audios as references.

    Slot order defines the @Image N / @Video N / @Audio N numbering used in
    the prompt. Gaps are compacted (image1 + image3 become @Image 1/@Image 2)
    with a console warning.
    """

    @classmethod
    def INPUT_TYPES(cls):
        optional: Dict[str, tuple] = {}
        for i in range(1, MAX_MULTI_IMAGES + 1):
            optional[f"image{i}"] = ("IMAGE", {
                "tooltip": f"Reference image, addressed as @Image {i} in the prompt. | 提示词中用 @Image {i} 指代。",
            })
        for i in range(1, MAX_MULTI_VIDEOS + 1):
            optional[f"video{i}"] = ("VIDEO", {
                "tooltip": (
                    f"Reference video (MP4 <=50MB), addressed as @Video {i}. | "
                    f"参考视频，提示词中用 @Video {i} 指代。"
                ),
            })
        for i in range(1, MAX_MULTI_AUDIOS + 1):
            optional[f"audio{i}"] = ("AUDIO", {
                "tooltip": f"Reference audio (<=50MB), addressed as @Audio {i}. | 参考音频，提示词中用 @Audio {i} 指代。",
            })
        optional.update(_optional_widgets())

        return {
            "required": {
                "model": _model_input(MULTI_MODELS),
                "prompt": _prompt_input(required=True),
                **_common_widgets(),
            },
            "optional": optional,
        }

    @classmethod
    def VALIDATE_INPUTS(cls, model=None, resolution=None, prompt=None, strict=False, **kwargs):
        if model and resolution:
            result = _validate_common(model, resolution, prompt)
            if result is not True:
                return result
        if strict and not str(prompt or "").strip():
            return "prompt is required for multimodal video | 多模态视频必须填写提示词"
        return True

    def _gather_slots(self, kwargs: Dict, base_name: str, count: int) -> List[Tuple[int, Any]]:
        slots = [
            (i, kwargs.get(f"{base_name}{i}"))
            for i in range(1, count + 1)
            if kwargs.get(f"{base_name}{i}") is not None
        ]
        connected = [i for i, _ in slots]
        if connected and connected != list(range(1, len(connected) + 1)):
            print(
                f"[{self._log_prefix}] WARNING: {base_name} slots {connected} have gaps; "
                f"they will be renumbered consecutively as @{base_name.capitalize()} 1..{len(connected)} in the prompt."
            )
        return slots

    def collect_media(self, kwargs, config, progress_cb):
        image_slots = self._gather_slots(kwargs, "image", MAX_MULTI_IMAGES)
        video_slots = self._gather_slots(kwargs, "video", MAX_MULTI_VIDEOS)
        audio_slots = self._gather_slots(kwargs, "audio", MAX_MULTI_AUDIOS)

        if not (image_slots or video_slots or audio_slots):
            raise SeedanceAPIError(
                "multimodal video requires at least one reference image, video, or audio | "
                "多模态视频至少需要连接 1 个参考图片/视频/音频素材"
            )

        _VIDEO_MIME = {"mp4": "video/mp4", "avi": "video/x-msvideo", "mov": "video/quicktime", "mkv": "video/x-matroska"}

        total = len(image_slots) + len(video_slots) + len(audio_slots)
        done = 0
        content: List[Dict[str, Any]] = []

        for i, tensor in image_slots:
            url = upload_media(
                image_to_png_bytes(tensor), f"image_{i}.png", "image/png",
                config, logger_prefix=self._log_prefix,
            )
            content.append({"type": "image_url", "image_url": {"url": url}})
            done += 1
            progress_cb(done / total)

        for i, value in video_slots:
            video_bytes, ext = video_to_bytes(value)
            url = upload_media(
                video_bytes, f"video_{i}.{ext}", _VIDEO_MIME.get(ext, "video/mp4"),
                config, logger_prefix=self._log_prefix,
            )
            content.append({"type": "video_url", "video_url": {"url": url}})
            done += 1
            progress_cb(done / total)

        for i, value in audio_slots:
            url = upload_media(
                audio_to_wav_bytes(value), f"audio_{i}.wav", "audio/wav",
                config, logger_prefix=self._log_prefix,
            )
            content.append({"type": "audio_url", "audio_url": {"url": url}})
            done += 1
            progress_cb(done / total)

        return {"content": content}

    def build_payload(self, kwargs, media):
        prompt = str(kwargs.get("prompt") or "").strip()
        if not prompt:
            raise SeedanceAPIError("prompt is required for multimodal video | 多模态视频必须填写提示词")
        payload = self._base_payload(kwargs)
        payload["prompt"] = prompt
        payload["metadata"]["content"] = media["content"]
        return payload


# ---------------------------------------------------------------------------
# Seedream image generation and editing
# ---------------------------------------------------------------------------

class SeedreamV5ProImage:
    """Text-to-image without references, image editing with 1-10 references."""

    CATEGORY = "Seedance"
    FUNCTION = "execute"
    OUTPUT_NODE = True
    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("image", "image_url", "task_id", "response")

    @classmethod
    def INPUT_TYPES(cls):
        optional: Dict[str, tuple] = {
            f"image{i}": ("IMAGE", {
                "tooltip": f"Optional editing reference image {i} of {MAX_SEEDREAM_IMAGES}. | 可选编辑参考图 {i}。",
            })
            for i in range(1, MAX_SEEDREAM_IMAGES + 1)
        }
        optional["api_config"] = ("SEEDANCE_CONFIG", {
            "tooltip": "Connect Seedance API Config; otherwise SEEDANCE_API_KEY is used.",
        })

        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Prompt, 5-2000 characters. | 提示词，长度 5-2000 字符。",
                }),
                "resolution": (SEEDREAM_RESOLUTIONS, {
                    "default": "2k",
                    "tooltip": "1k/2k use the API preset; custom uses width and height. | 1k/2k 使用预设，custom 使用宽高。",
                }),
                "width": ("INT", {
                    "default": 1024,
                    "min": 240,
                    "max": 8192,
                    "step": 8,
                    "tooltip": "Used only when resolution is custom. | 仅 custom 分辨率时生效。",
                }),
                "height": ("INT", {
                    "default": 1024,
                    "min": 240,
                    "max": 8192,
                    "step": 8,
                    "tooltip": "Used only when resolution is custom. | 仅 custom 分辨率时生效。",
                }),
                "output_format": (SEEDREAM_OUTPUT_FORMATS, {
                    "default": "png",
                    "tooltip": "Result file format. | 输出图片格式。",
                }),
                "model_family": (SEEDREAM_MODEL_FAMILIES, {
                    "default": SEEDREAM_FAMILY_DOMESTIC,
                    "tooltip": (
                        "Domestic uses seedream-v5-pro-t2i/i2i; overseas uses "
                        "dola-seedream-5.0-pro-t2i/i2i. | 国内使用 seedream-v5-pro；"
                        "海外使用 dola-seedream-5.0-pro。"
                    ),
                }),
            },
            "optional": optional,
        }

    @classmethod
    def VALIDATE_INPUTS(
        cls,
        prompt=None,
        resolution=None,
        width=None,
        height=None,
        output_format=None,
        model_family=None,
        strict=False,
        **kwargs,
    ):
        prompt_text = str(prompt or "").strip()
        if (strict or prompt_text) and not SEEDREAM_PROMPT_MIN_LENGTH <= len(prompt_text) <= SEEDREAM_PROMPT_MAX_LENGTH:
            return (
                f"prompt must contain {SEEDREAM_PROMPT_MIN_LENGTH}-{SEEDREAM_PROMPT_MAX_LENGTH} "
                f"characters (got {len(prompt_text)}) | 提示词长度必须为 "
                f"{SEEDREAM_PROMPT_MIN_LENGTH}-{SEEDREAM_PROMPT_MAX_LENGTH} 字符"
            )
        if resolution not in SEEDREAM_RESOLUTIONS:
            return f"unsupported resolution: {resolution}"
        if output_format not in SEEDREAM_OUTPUT_FORMATS:
            return f"unsupported output_format: {output_format}"
        if model_family is not None and model_family not in SEEDREAM_MODEL_FAMILIES:
            return f"unsupported model_family: {model_family}"
        if resolution == "custom":
            if width is None or not 240 <= int(width) <= 8192:
                return "custom width must be between 240 and 8192"
            if height is None or not 240 <= int(height) <= 8192:
                return "custom height must be between 240 and 8192"
        return True

    @property
    def _log_prefix(self) -> str:
        return "Seedream_v5_pro_image"

    def _update_progress(self, pbar, value: float):
        if pbar is not None:
            try:
                pbar.update_absolute(int(value), 100)
            except Exception:
                pass

    def _build_payload(
        self,
        prompt: str,
        resolution: str,
        width: int,
        height: int,
        output_format: str,
        images: List[str],
        model_family: str = SEEDREAM_FAMILY_DOMESTIC,
    ):
        model_pair = SEEDREAM_MODEL_PAIRS.get(model_family or SEEDREAM_FAMILY_DOMESTIC)
        if not model_pair:
            raise SeedanceAPIError(f"unsupported model_family: {model_family}")

        metadata: Dict[str, Any] = {"output_format": output_format}
        if resolution == "custom":
            metadata.update({"width": int(width), "height": int(height)})
        else:
            metadata["resolution"] = resolution

        payload: Dict[str, Any] = {
            "model": model_pair[1] if images else model_pair[0],
            "prompt": prompt,
            "metadata": metadata,
        }
        if images:
            payload["images"] = images
        return payload

    def execute(
        self,
        prompt: str,
        resolution: str,
        width: int,
        height: int,
        output_format: str,
        model_family: str = SEEDREAM_FAMILY_DOMESTIC,
        api_config=None,
        **kwargs,
    ):
        prompt_text = str(prompt or "").strip()
        validation = self.VALIDATE_INPUTS(
            prompt=prompt_text,
            resolution=resolution,
            width=width,
            height=height,
            output_format=output_format,
            model_family=model_family,
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        config = get_config(api_config)
        pbar = comfy.utils.ProgressBar(100) if COMFYUI_AVAILABLE else None
        self._update_progress(pbar, 0)

        references = [
            (i, kwargs.get(f"image{i}"))
            for i in range(1, MAX_SEEDREAM_IMAGES + 1)
            if kwargs.get(f"image{i}") is not None
        ]
        image_urls: List[str] = []
        for done, (slot, tensor) in enumerate(references, start=1):
            image_url = upload_media(
                image_to_png_bytes(tensor),
                f"seedream_reference_{slot}.png",
                "image/png",
                config,
                logger_prefix=self._log_prefix,
            )
            image_urls.append(image_url)
            self._update_progress(pbar, done / len(references) * 15)
        self._update_progress(pbar, 15)

        payload = self._build_payload(
            prompt_text, resolution, width, height, output_format, image_urls, model_family
        )
        task_id = submit_image_task(payload, config, logger_prefix=self._log_prefix)
        self._update_progress(pbar, 20)

        def on_progress(progress: int):
            self._update_progress(pbar, 20 + progress / 100.0 * 75)

        final_response = poll_image_task(
            task_id,
            config,
            on_progress=on_progress,
            logger_prefix=self._log_prefix,
        )
        self._update_progress(pbar, 95)

        image_url = extract_image_url(final_response)
        image = download_image(image_url, logger_prefix=self._log_prefix)
        self._update_progress(pbar, 100)

        response_str = json.dumps(final_response, ensure_ascii=False, indent=2)
        return {
            "ui": {"text": [image_url, response_str]},
            "result": (image, image_url, task_id, response_str),
        }


# ---------------------------------------------------------------------------
# Zhenzhen Image G-2 image generation and editing
# ---------------------------------------------------------------------------

class ZhenzhenImageG2:
    """Zhenzhen Image G-2 text-to-image and image-to-image."""

    CATEGORY = "Seedance"
    FUNCTION = "execute"
    OUTPUT_NODE = True
    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("image", "image_url", "task_id", "response")

    @classmethod
    def INPUT_TYPES(cls):
        optional: Dict[str, tuple] = {
            f"image{i}": ("IMAGE", {
                "tooltip": (
                    f"Optional editing reference image {i} of {MAX_ZHENZHEN_IMAGE_G2_IMAGES}; "
                    "used only by zhenzhen-image-g2-i2i. | 可选编辑参考图，仅 i2i 模型使用。"
                ),
            })
            for i in range(1, MAX_ZHENZHEN_IMAGE_G2_IMAGES + 1)
        }
        optional["api_config"] = ("SEEDANCE_CONFIG", {
            "tooltip": "Connect Seedance API Config; otherwise SEEDANCE_API_KEY is used.",
        })

        return {
            "required": {
                "model": (ZHENZHEN_IMAGE_G2_MODELS, {
                    "default": ZHENZHEN_IMAGE_G2_T2I_MODEL,
                    "tooltip": (
                        "Zhenzhen Image G-2 task type. t2i uses prompt only; "
                        "i2i requires one or more reference images. | G-2 文生图只用提示词；"
                        "图生图需要连接参考图。"
                    ),
                }),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Prompt, up to 20000 characters. | 提示词，最多 20000 字符。",
                }),
                "resolution": (ZHENZHEN_IMAGE_G2_RESOLUTIONS, {
                    "default": "1k",
                    "tooltip": "Zhenzhen Image G-2 currently supports 1k only. | G-2 当前仅支持 1k。",
                }),
                "ratio": (RATIOS, {
                    "default": "adaptive",
                    "tooltip": "Optional aspect ratio forwarded as metadata.ratio. | 可选画幅比例，透传为 metadata.ratio。",
                }),
            },
            "optional": optional,
        }

    @classmethod
    def VALIDATE_INPUTS(
        cls,
        model=None,
        prompt=None,
        resolution=None,
        ratio=None,
        strict=False,
        **kwargs,
    ):
        if model not in (None, *ZHENZHEN_IMAGE_G2_MODELS):
            return f"unsupported Zhenzhen Image G-2 model: {model}"
        prompt_text = str(prompt or "").strip()
        if strict and not prompt_text:
            return "prompt is required for Zhenzhen Image G-2 | Zhenzhen Image G-2 必须填写提示词"
        if prompt_text and len(prompt_text) > ZHENZHEN_IMAGE_G2_PROMPT_MAX_LENGTH:
            return (
                f"prompt exceeds {ZHENZHEN_IMAGE_G2_PROMPT_MAX_LENGTH} characters "
                f"({len(prompt_text)}) | 提示词不能超过 {ZHENZHEN_IMAGE_G2_PROMPT_MAX_LENGTH} 字符"
            )
        if resolution is not None and resolution not in ZHENZHEN_IMAGE_G2_RESOLUTIONS:
            return "Zhenzhen Image G-2 resolution must be 1k | Zhenzhen Image G-2 分辨率只能是 1k"
        if ratio is not None and ratio not in RATIOS:
            return f"unsupported ratio: {ratio}"
        return True

    @property
    def _log_prefix(self) -> str:
        return "Zhenzhen_image_g2"

    def _update_progress(self, pbar, value: float):
        if pbar is not None:
            try:
                pbar.update_absolute(int(value), 100)
            except Exception:
                pass

    def _connected_images(self, kwargs: Dict[str, Any]) -> List[Tuple[int, Any]]:
        slots = [
            (i, kwargs.get(f"image{i}"))
            for i in range(1, MAX_ZHENZHEN_IMAGE_G2_IMAGES + 1)
            if kwargs.get(f"image{i}") is not None
        ]
        connected = [i for i, _ in slots]
        if connected and connected != list(range(1, len(connected) + 1)):
            print(
                f"[{self._log_prefix}] WARNING: G-2 image slots {connected} have gaps; "
                f"they will be compacted to images order 1..{len(connected)}."
            )
        return slots

    def _build_payload(
        self,
        model: str,
        prompt: str,
        resolution: str,
        ratio: str,
        images: List[str],
    ) -> Dict[str, Any]:
        if model == ZHENZHEN_IMAGE_G2_I2I_MODEL and not images:
            raise SeedanceAPIError(
                "at least one image is required for zhenzhen-image-g2-i2i | "
                "zhenzhen-image-g2-i2i 至少需要 1 张参考图"
            )

        metadata: Dict[str, Any] = {"resolution": resolution}
        ratio_text = str(ratio or "").strip()
        if ratio_text and ratio_text != "adaptive":
            metadata["ratio"] = ratio_text

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "metadata": metadata,
        }
        if model == ZHENZHEN_IMAGE_G2_I2I_MODEL:
            payload["images"] = images[:MAX_ZHENZHEN_IMAGE_G2_IMAGES]
        return payload

    def execute(
        self,
        model: str,
        prompt: str,
        resolution: str,
        ratio: str,
        api_config=None,
        **kwargs,
    ):
        prompt_text = str(prompt or "").strip()
        validation = self.VALIDATE_INPUTS(
            model=model,
            prompt=prompt_text,
            resolution=resolution,
            ratio=ratio,
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        config = get_config(api_config)
        pbar = comfy.utils.ProgressBar(100) if COMFYUI_AVAILABLE else None
        self._update_progress(pbar, 0)

        image_urls: List[str] = []
        if model == ZHENZHEN_IMAGE_G2_I2I_MODEL:
            references = self._connected_images(kwargs)
            if not references:
                raise SeedanceAPIError(
                    "at least one image is required for zhenzhen-image-g2-i2i | "
                    "zhenzhen-image-g2-i2i 至少需要 1 张参考图"
                )
            for done, (slot, tensor) in enumerate(references, start=1):
                image_url = upload_media(
                    image_to_png_bytes(tensor),
                    f"zhenzhen_image_g2_reference_{slot}.png",
                    "image/png",
                    config,
                    logger_prefix=self._log_prefix,
                )
                image_urls.append(image_url)
                self._update_progress(pbar, done / len(references) * 15)
        self._update_progress(pbar, 15)

        payload = self._build_payload(model, prompt_text, resolution, ratio, image_urls)
        task_id = submit_image_task(payload, config, logger_prefix=self._log_prefix)
        self._update_progress(pbar, 20)

        def on_progress(progress: int):
            self._update_progress(pbar, 20 + progress / 100.0 * 75)

        final_response = poll_image_task(
            task_id,
            config,
            on_progress=on_progress,
            logger_prefix=self._log_prefix,
        )
        self._update_progress(pbar, 95)

        image_url = extract_image_url(final_response)
        image = download_image(image_url, logger_prefix=self._log_prefix)
        self._update_progress(pbar, 100)

        response_str = json.dumps(final_response, ensure_ascii=False, indent=2)
        return {
            "ui": {"text": [image_url, response_str]},
            "result": (image, image_url, task_id, response_str),
        }


# ---------------------------------------------------------------------------
# Doubao Seed Audio generation
# ---------------------------------------------------------------------------

class DoubaoSeedAudio:
    """Asynchronous doubao-seed-audio-1.0 generation via /v1/audio/generations."""

    CATEGORY = "Seedance"
    FUNCTION = "execute"
    OUTPUT_NODE = True
    RETURN_TYPES = ("AUDIO", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("audio", "audio_url", "audio_path", "task_id", "response")

    @classmethod
    def INPUT_TYPES(cls):
        optional: Dict[str, tuple] = {
            "reference_image": ("IMAGE", {
                "tooltip": "Optional reference image. Cannot be used with speaker or reference audio. | 可选参考图，不能与音色 ID 或参考音频同时使用。",
            })
        }
        for i in range(1, MAX_DOUBAO_REFERENCE_AUDIOS + 1):
            optional[f"reference_audio{i}"] = ("AUDIO", {
                "tooltip": f"Optional reference audio {i} of 3. Cannot be used with speaker or reference image. | 可选参考音频 {i}/3，不能与音色 ID 或参考图同时使用。",
            })
        optional["api_config"] = ("SEEDANCE_CONFIG", {
            "tooltip": "Connect Seedance API Config; otherwise SEEDANCE_API_KEY is used.",
        })
        optional["skip_error"] = ("BOOLEAN", {
            "default": False,
            "tooltip": "On failure return 1 second of silence instead of stopping the workflow. | 失败时输出 1 秒静音。",
        })

        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Audio prompt, 5-2048 characters. | 音频提示词，5-2048 字符。",
                }),
                "speaker": ("STRING", {
                    "default": "",
                    "tooltip": "Optional speaker/voice id. Mutually exclusive with reference image/audio. | 可选音色 ID，不能与参考图/参考音频同时使用。",
                }),
                "output_format": (DOUBAO_AUDIO_FORMATS, {
                    "default": "wav",
                    "tooltip": "Audio file format. wav is easiest for ComfyUI decoding. | 输出格式，wav 最容易被 ComfyUI 解码。",
                }),
                "sample_rate": (DOUBAO_SAMPLE_RATES, {
                    "default": "24000",
                    "tooltip": "Output sample rate. | 输出采样率。",
                }),
                "speech_rate": ("INT", {
                    "default": 0, "min": -50, "max": 100, "step": 1,
                    "tooltip": "Speech rate adjustment, -50 to 100. | 语速，-50 到 100。",
                }),
                "loudness_rate": ("INT", {
                    "default": 0, "min": -50, "max": 100, "step": 1,
                    "tooltip": "Loudness adjustment, -50 to 100. | 音量，-50 到 100。",
                }),
                "pitch_rate": ("INT", {
                    "default": 0, "min": -12, "max": 12, "step": 1,
                    "tooltip": "Pitch adjustment, -12 to 12. | 音高，-12 到 12。",
                }),
            },
            "optional": optional,
        }

    @classmethod
    def VALIDATE_INPUTS(
        cls,
        prompt=None,
        output_format=None,
        sample_rate=None,
        speech_rate=None,
        loudness_rate=None,
        pitch_rate=None,
        strict=False,
        **kwargs,
    ):
        prompt_text = str(prompt or "").strip()
        if (strict or prompt_text) and not DOUBAO_PROMPT_MIN_LENGTH <= len(prompt_text) <= DOUBAO_PROMPT_MAX_LENGTH:
            return (
                f"prompt must contain {DOUBAO_PROMPT_MIN_LENGTH}-{DOUBAO_PROMPT_MAX_LENGTH} "
                f"characters (got {len(prompt_text)}) | 提示词长度必须为 "
                f"{DOUBAO_PROMPT_MIN_LENGTH}-{DOUBAO_PROMPT_MAX_LENGTH} 字符"
            )
        if output_format not in DOUBAO_AUDIO_FORMATS:
            return f"unsupported output_format: {output_format}"
        if str(sample_rate) not in DOUBAO_SAMPLE_RATES:
            return f"unsupported sample_rate: {sample_rate}"
        for name, value, low, high in (
            ("speech_rate", speech_rate, -50, 100),
            ("loudness_rate", loudness_rate, -50, 100),
            ("pitch_rate", pitch_rate, -12, 12),
        ):
            if value is None:
                continue
            value_int = int(value)
            if not low <= value_int <= high:
                return f"{name} must be between {low} and {high}"
        return True

    @property
    def _log_prefix(self) -> str:
        return "Doubao_seed_audio"

    def _update_progress(self, pbar, value: float):
        if pbar is not None:
            try:
                pbar.update_absolute(int(value), 100)
            except Exception:
                pass

    def _connected_reference_audios(self, kwargs: Dict[str, Any]) -> List[Tuple[int, Any]]:
        return [
            (i, kwargs.get(f"reference_audio{i}"))
            for i in range(1, MAX_DOUBAO_REFERENCE_AUDIOS + 1)
            if kwargs.get(f"reference_audio{i}") is not None
        ]

    def _validate_reference_modes(self, speaker: str, reference_image: Any, reference_audios: List[Tuple[int, Any]]):
        modes = [
            bool(str(speaker or "").strip()),
            reference_image is not None,
            bool(reference_audios),
        ]
        if sum(1 for enabled in modes if enabled) > 1:
            raise SeedanceAPIError(
                "Doubao Seed Audio accepts only one of speaker, reference_image, or reference_audio. | "
                "Doubao Seed Audio 的 speaker、参考图、参考音频三类只能选择一种。"
            )

    def _build_payload(
        self,
        prompt: str,
        speaker: str,
        output_format: str,
        sample_rate: str,
        speech_rate: int,
        loudness_rate: int,
        pitch_rate: int,
        image_urls: List[str],
        audio_urls: List[str],
    ) -> Dict[str, Any]:
        self._validate_reference_modes(speaker, image_urls[0] if image_urls else None, [(i, url) for i, url in enumerate(audio_urls, 1)])
        metadata: Dict[str, Any] = {
            "format": output_format,
            "sample_rate": str(sample_rate),
            "speech_rate": int(speech_rate),
            "loudness_rate": int(loudness_rate),
            "pitch_rate": int(pitch_rate),
        }

        speaker_text = str(speaker or "").strip()
        if speaker_text:
            metadata["speaker"] = speaker_text
        if audio_urls:
            metadata["audio_urls"] = audio_urls[:MAX_DOUBAO_REFERENCE_AUDIOS]

        payload: Dict[str, Any] = {
            "model": DOUBAO_SEED_AUDIO_MODEL,
            "prompt": prompt,
            "metadata": metadata,
        }
        if image_urls:
            payload["images"] = image_urls[:1]
        return payload

    def _upload_references(self, kwargs, config, progress_cb):
        reference_image = kwargs.get("reference_image")
        reference_audios = self._connected_reference_audios(kwargs)
        speaker = str(kwargs.get("speaker") or "").strip()
        self._validate_reference_modes(speaker, reference_image, reference_audios)

        image_urls: List[str] = []
        audio_urls: List[str] = []
        total = (1 if reference_image is not None else 0) + len(reference_audios)
        if total == 0:
            progress_cb(1.0)
            return image_urls, audio_urls

        done = 0
        if reference_image is not None:
            image_url = upload_media(
                image_to_png_bytes(reference_image),
                "doubao_seed_audio_reference.png",
                "image/png",
                config,
                logger_prefix=self._log_prefix,
            )
            image_urls.append(image_url)
            done += 1
            progress_cb(done / total)

        for i, audio in reference_audios:
            audio_url = upload_media(
                audio_to_wav_bytes(audio),
                f"doubao_seed_audio_reference_{i}.wav",
                "audio/wav",
                config,
                logger_prefix=self._log_prefix,
            )
            audio_urls.append(audio_url)
            done += 1
            progress_cb(done / total)

        return image_urls, audio_urls

    def _make_error_result(self, error_msg: str, sample_rate: str = "24000") -> Dict:
        response_str = json.dumps({"error": error_msg}, ensure_ascii=False, indent=2)
        audio = make_silent_audio(int(sample_rate or 24000), 1.0)
        return {
            "ui": {"text": ["", "", response_str]},
            "result": (audio, "", "", "", response_str),
        }

    def execute(
        self,
        prompt: str,
        speaker: str,
        output_format: str,
        sample_rate: str,
        speech_rate: int,
        loudness_rate: int,
        pitch_rate: int,
        api_config=None,
        skip_error: bool = False,
        **kwargs,
    ):
        try:
            return self._execute_inner(
                prompt=prompt,
                speaker=speaker,
                output_format=output_format,
                sample_rate=sample_rate,
                speech_rate=speech_rate,
                loudness_rate=loudness_rate,
                pitch_rate=pitch_rate,
                api_config=api_config,
                **kwargs,
            )
        except Exception as e:
            if skip_error:
                err_msg = f"{self._log_prefix}: {e}"
                print(f"[{self._log_prefix}] skip_error=True, returning silence: {e}")
                return self._make_error_result(err_msg, sample_rate)
            raise

    def _execute_inner(
        self,
        prompt: str,
        speaker: str,
        output_format: str,
        sample_rate: str,
        speech_rate: int,
        loudness_rate: int,
        pitch_rate: int,
        api_config=None,
        **kwargs,
    ):
        prompt_text = str(prompt or "").strip()
        validation = self.VALIDATE_INPUTS(
            prompt=prompt_text,
            output_format=output_format,
            sample_rate=sample_rate,
            speech_rate=speech_rate,
            loudness_rate=loudness_rate,
            pitch_rate=pitch_rate,
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        config = get_config(api_config)
        pbar = comfy.utils.ProgressBar(100) if COMFYUI_AVAILABLE else None
        self._update_progress(pbar, 0)

        image_urls, audio_urls = self._upload_references(
            {**kwargs, "speaker": speaker},
            config,
            lambda frac: self._update_progress(pbar, frac * 15),
        )
        self._update_progress(pbar, 15)

        payload = self._build_payload(
            prompt_text,
            speaker,
            output_format,
            sample_rate,
            speech_rate,
            loudness_rate,
            pitch_rate,
            image_urls,
            audio_urls,
        )
        task_id = submit_audio_task(payload, config, logger_prefix=self._log_prefix)
        self._update_progress(pbar, 20)

        def on_progress(progress: int):
            self._update_progress(pbar, 20 + progress / 100.0 * 75)

        final_response = poll_audio_task(
            task_id,
            config,
            on_progress=on_progress,
            logger_prefix=self._log_prefix,
        )
        self._update_progress(pbar, 95)

        audio_url = extract_audio_url(final_response)
        audio, audio_path = download_audio(
            audio_url,
            output_format=output_format,
            sample_rate=int(sample_rate),
            logger_prefix=self._log_prefix,
        )
        self._update_progress(pbar, 100)

        response_str = json.dumps(final_response, ensure_ascii=False, indent=2)
        return {
            "ui": {"text": [audio_url, audio_path, response_str]},
            "result": (audio, audio_url, audio_path, task_id, response_str),
        }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

NODE_CLASS_MAPPINGS = {
    "Seedance_Config": SeedanceConfig,
    "Seedance_TextToVideo": SeedanceTextToVideo,
    "Seedance_ImageToVideo": SeedanceImageToVideo,
    "Seedance_MultimodalVideo": SeedanceMultimodalVideo,
    "Seedream_V5_Pro_Image": SeedreamV5ProImage,
    "Zhenzhen_Image_G2": ZhenzhenImageG2,
    "HappyHorse_1_1_Video": HappyHorseVideo,
    "Wan_2_7_Spicy_I2V": Wan27SpicyImageToVideo,
    "Kling_Video": KlingVideo,
    "Kling_Edit_Video": KlingEditVideo,
    "Hailuo_2_3_Video": Hailuo23Video,
    "Vidu_Q3_Video": ViduQ3Video,
    "Vidu_Q3_ShortPlay": ViduQ3ShortPlay,
    "Zhenzhen_Upscaler_Video": ZhenzhenUpscalerVideo,
    "Doubao_Seed_Audio": DoubaoSeedAudio,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Seedance_Config": "Seedance API Config",
    "Seedance_TextToVideo": "Seedance 文生视频 (Text to Video)",
    "Seedance_ImageToVideo": "Seedance 图生视频 (Image to Video)",
    "Seedance_MultimodalVideo": "Seedance 多模态视频 (Multimodal Video)",
    "Seedream_V5_Pro_Image": "Seedream / Dola Seedream 图像生成/编辑",
    "Zhenzhen_Image_G2": "Zhenzhen Image G-2 图像生成/编辑",
    "HappyHorse_1_1_Video": "HappyHorse 1.1 视频生成",
    "Wan_2_7_Spicy_I2V": "Wan 2.7 Spicy 图生视频",
    "Kling_Video": "Kling 视频生成",
    "Kling_Edit_Video": "Kling O3 视频编辑",
    "Hailuo_2_3_Video": "Hailuo 2.3 视频生成",
    "Vidu_Q3_Video": "Vidu Q3 视频生成",
    "Vidu_Q3_ShortPlay": "Vidu Q3 短剧成片",
    "Zhenzhen_Upscaler_Video": "Zhenzhen Upscaler 视频超分",
    "Doubao_Seed_Audio": "Doubao Seed Audio 1.0 音频生成",
}
