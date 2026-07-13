"""
ComfyUI nodes for Seedance, HappyHorse, Wan, Seedream, Dola Seedream,
and Doubao Seed Audio APIs (api.seedance.nz).

Seedance video nodes expose the 18 Seedance 2.0 model variants by task type.
HappyHorse and Wan use dedicated video nodes, Seedream and Dola Seedream share
one image node with a model-family selector, and Doubao Seed Audio uses its
own audio node.

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
            "standard/fast/mini = quality tiers (mini is cheapest); 'global-' models "
            "run on overseas infrastructure. | standard/fast/mini 为档位（mini 最便宜），"
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
    def VALIDATE_INPUTS(cls, model=None, resolution=None, prompt=None, **kwargs):
        if model and resolution:
            result = _validate_common(model, resolution, prompt)
            if result is not True:
                return result
        if prompt is not None and not str(prompt).strip():
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
    def VALIDATE_INPUTS(cls, model=None, prompt=None, seconds=None, resolution=None, **kwargs):
        if model not in (None, *HAPPYHORSE_MODELS):
            return f"unsupported HappyHorse model: {model}"
        if resolution is not None and resolution not in HAPPYHORSE_RESOLUTIONS:
            return "HappyHorse resolution must be 720p or 1080p | HappyHorse 分辨率只能是 720p 或 1080p"
        if seconds is not None and str(seconds) not in HAPPYHORSE_SECONDS:
            return "HappyHorse seconds must be 3-15 and cannot be -1 | HappyHorse 时长必须是 3-15 秒，不能用 -1"
        if prompt is not None and len(str(prompt)) > PROMPT_MAX_LENGTH:
            return f"prompt exceeds {PROMPT_MAX_LENGTH} characters ({len(str(prompt))})"
        if model == HAPPYHORSE_T2V_MODEL and not str(prompt or "").strip():
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
    def VALIDATE_INPUTS(cls, model=None, resolution=None, prompt=None, **kwargs):
        if model and resolution:
            result = _validate_common(model, resolution, prompt)
            if result is not True:
                return result
        if prompt is not None and not str(prompt).strip():
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
        **kwargs,
    ):
        prompt_text = str(prompt or "").strip()
        if not SEEDREAM_PROMPT_MIN_LENGTH <= len(prompt_text) <= SEEDREAM_PROMPT_MAX_LENGTH:
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
        **kwargs,
    ):
        prompt_text = str(prompt or "").strip()
        if not DOUBAO_PROMPT_MIN_LENGTH <= len(prompt_text) <= DOUBAO_PROMPT_MAX_LENGTH:
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
    "HappyHorse_1_1_Video": HappyHorseVideo,
    "Wan_2_7_Spicy_I2V": Wan27SpicyImageToVideo,
    "Doubao_Seed_Audio": DoubaoSeedAudio,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Seedance_Config": "Seedance API Config",
    "Seedance_TextToVideo": "Seedance 文生视频 (Text to Video)",
    "Seedance_ImageToVideo": "Seedance 图生视频 (Image to Video)",
    "Seedance_MultimodalVideo": "Seedance 多模态视频 (Multimodal Video)",
    "Seedream_V5_Pro_Image": "Seedream / Dola Seedream 图像生成/编辑",
    "HappyHorse_1_1_Video": "HappyHorse 1.1 视频生成",
    "Wan_2_7_Spicy_I2V": "Wan 2.7 Spicy 图生视频",
    "Doubao_Seed_Audio": "Doubao Seed Audio 1.0 音频生成",
}
