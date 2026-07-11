"""
ComfyUI nodes for the Seedance video generation API (api.seedance.nz).

Node layout: 18 API models = 2 regions (cn / global-) x 3 tiers
(standard / fast / mini) x 3 task types (t2v / i2v / multi). The task type
decides the node's input signature, so we expose exactly 3 generation nodes
(one per task type) with a 6-entry model dropdown, plus one config node.

Execution flow per node: upload media -> build payload -> submit -> poll ->
download result, with a ComfyUI progress bar driven by the API's progress
field and skip_error support for batch workflows.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from .core.config import get_config, DEFAULT_BASE_URL
from .core.client import (
    SeedanceAPIError,
    download_image,
    download_video,
    extract_image_url,
    extract_video_url,
    poll_image_task,
    poll_task,
    submit_image_task,
    submit_task,
    upload_media,
)
from .core.media import (
    audio_to_wav_bytes,
    image_to_png_bytes,
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
SEEDREAM_RESOLUTIONS = ["1k", "2k", "custom"]
SEEDREAM_OUTPUT_FORMATS = ["png", "jpeg"]
SEEDREAM_PROMPT_MIN_LENGTH = 5
SEEDREAM_PROMPT_MAX_LENGTH = 2000
MAX_SEEDREAM_IMAGES = 10


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
                "1080p/2k/4k are upscaled from 720p with a per-second surcharge; "
                "native1080p/native4k are Standard-tier only. | 1080p/2k/4k 为超分档"
                "（按秒加收附加费），native 档仅 Standard 模型支持。"
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
                    f"Reference video (MP4 <=50MB), addressed as @Video {i}. Adding a video "
                    f"switches billing to the cheaper with-video-reference rate. | "
                    f"参考视频，提示词中用 @Video {i} 指代；带参考视频按低单价档计费。"
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

    def _build_payload(self, prompt: str, resolution: str, width: int, height: int, output_format: str, images: List[str]):
        metadata: Dict[str, Any] = {"output_format": output_format}
        if resolution == "custom":
            metadata.update({"width": int(width), "height": int(height)})
        else:
            metadata["resolution"] = resolution

        payload: Dict[str, Any] = {
            "model": SEEDREAM_I2I_MODEL if images else SEEDREAM_T2I_MODEL,
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
            prompt_text, resolution, width, height, output_format, image_urls
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
# Registration
# ---------------------------------------------------------------------------

NODE_CLASS_MAPPINGS = {
    "Seedance_Config": SeedanceConfig,
    "Seedance_TextToVideo": SeedanceTextToVideo,
    "Seedance_ImageToVideo": SeedanceImageToVideo,
    "Seedance_MultimodalVideo": SeedanceMultimodalVideo,
    "Seedream_V5_Pro_Image": SeedreamV5ProImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Seedance_Config": "Seedance API Config",
    "Seedance_TextToVideo": "Seedance 文生视频 (Text to Video)",
    "Seedance_ImageToVideo": "Seedance 图生视频 (Image to Video)",
    "Seedance_MultimodalVideo": "Seedance 多模态视频 (Multimodal Video)",
    "Seedream_V5_Pro_Image": "Seedream v5 Pro 图像生成/编辑",
}
