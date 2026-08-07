"""
ComfyUI nodes for Seedance, HappyHorse, Wan, Kling, Hailuo, MiniMax, Vidu,
Zhenzhen Upscaler, Seedream, Dola Seedream, Qwen, Zhenzhen Image G/NB,
Zhenzhen Video G/GK/V3.1, Doubao Seed Audio, and Whisper transcription APIs
(api.seedance.nz).

Seedance video nodes expose the 18 Seedance 2.0 variants by task type and a
dedicated six-model Seedance 2.5 Standard node.
HappyHorse, Wan, Kling, Hailuo, MiniMax, Vidu, and Zhenzhen Upscaler use dedicated video
nodes, Seedream and Dola Seedream share one image node with a model-family
selector, Qwen and Zhenzhen Image G/NB use dedicated image nodes, Zhenzhen Video models
use dedicated video nodes, Doubao Seed Audio uses its own audio node, and
Whisper transcription uses a synchronous audio node.

Execution flow per node: upload media -> build payload -> submit -> poll ->
download result, with a ComfyUI progress bar driven by the API's progress
field and skip_error support for batch workflows.
"""

import json
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .core.config import get_config, validate_api_key, DEFAULT_BASE_URL
from .core.client import (
    SeedanceAPIError,
    download_audio,
    download_file,
    download_image,
    download_image_with_path,
    download_video,
    download_video_with_path,
    extract_audio_url,
    extract_image_url,
    extract_midjourney_results,
    extract_music_results,
    extract_video_url,
    poll_audio_task,
    poll_image_task,
    poll_midjourney_task,
    poll_music_task,
    poll_task,
    submit_audio_task,
    submit_image_task,
    submit_midjourney_action,
    submit_music_action,
    submit_task,
    transcribe_audio,
    upload_media,
)
from .core.media import (
    audio_to_wav_bytes,
    image_to_png_bytes,
    mask_to_midjourney_png_bytes,
    make_silent_audio,
    make_error_image,
    make_error_video,
    video_to_bytes,
)
from .core.runtime import current_progress_callback, progress_is_suppressed

try:
    import comfy.utils
    COMFYUI_AVAILABLE = True
except ImportError:
    COMFYUI_AVAILABLE = False


class _ConcurrentProgressBar:
    def __init__(self, total: int, callback):
        self.total = max(1, int(total))
        self.callback = callback

    def update_absolute(self, value, total=None, preview=None):
        effective_total = max(1, int(total or self.total))
        self.callback(float(value), float(effective_total))


def _make_progress_bar(total: int):
    progress_callback = current_progress_callback()
    if progress_callback is not None:
        return _ConcurrentProgressBar(total, progress_callback)
    if not COMFYUI_AVAILABLE or progress_is_suppressed():
        return None
    return comfy.utils.ProgressBar(total)


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

SEEDANCE25_T2V_MODELS = [
    "seedance-2.5-standard-t2v",
    "seedance-2.5-global-standard-t2v",
]
SEEDANCE25_I2V_MODELS = [
    "seedance-2.5-standard-i2v",
    "seedance-2.5-global-standard-i2v",
]
SEEDANCE25_MULTI_MODELS = [
    "seedance-2.5-standard-multi",
    "seedance-2.5-global-standard-multi",
]
SEEDANCE25_MODELS = [
    SEEDANCE25_T2V_MODELS[0],
    SEEDANCE25_I2V_MODELS[0],
    SEEDANCE25_MULTI_MODELS[0],
    SEEDANCE25_T2V_MODELS[1],
    SEEDANCE25_I2V_MODELS[1],
    SEEDANCE25_MULTI_MODELS[1],
]
SEEDANCE25_SECONDS = ["-1"] + [str(value) for value in range(4, 31)]
SEEDANCE25_RESOLUTIONS = ["480p", "720p", "1080p", "2k", "4k"]
MAX_SEEDANCE25_MULTI_IMAGES = 30
MAX_SEEDANCE25_MULTI_VIDEOS = 10
MAX_SEEDANCE25_MULTI_AUDIOS = 10

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
ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL = "zhenzhen-image-g-v2-lowprice"
ZHENZHEN_IMAGE_G2_MODELS = [
    ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL,
    ZHENZHEN_IMAGE_G2_T2I_MODEL,
    ZHENZHEN_IMAGE_G2_I2I_MODEL,
]
ZHENZHEN_IMAGE_G2_RESOLUTIONS = ["1k"]
ZHENZHEN_IMAGE_G_V2_LOWPRICE_RESOLUTIONS = ["1k", "2k", "4k"]
ZHENZHEN_IMAGE_G_V2_LOWPRICE_SIZES = [
    "1:1",
    "2:3",
    "3:2",
    "3:4",
    "4:3",
    "4:5",
    "5:4",
    "9:16",
    "16:9",
    "21:9",
    "custom",
]
ZHENZHEN_IMAGE_G2_PROMPT_MAX_LENGTH = 20000
ZHENZHEN_IMAGE_G_V2_LOWPRICE_PROMPT_MIN_LENGTH = 5
ZHENZHEN_IMAGE_G_V2_LOWPRICE_PROMPT_MAX_LENGTH = 5000
MAX_ZHENZHEN_IMAGE_G2_IMAGES = 10
MAX_ZHENZHEN_IMAGE_G_V2_LOWPRICE_IMAGES = 16
QWEN_IMAGE_30_T2I_MODEL = "qwen-image-3.0-t2i"
QWEN_IMAGE_30_I2I_MODEL = "qwen-image-3.0-i2i"
QWEN_IMAGE_30_PRO_T2I_MODEL = "qwen-image-3.0-pro-t2i"
QWEN_IMAGE_30_PRO_I2I_MODEL = "qwen-image-3.0-pro-i2i"
QWEN_IMAGE_30_GLOBAL_T2I_MODEL = "qwen-image-3.0-global-t2i"
QWEN_IMAGE_30_GLOBAL_I2I_MODEL = "qwen-image-3.0-global-i2i"
QWEN_IMAGE_30_GLOBAL_PRO_T2I_MODEL = "qwen-image-3.0-global-pro-t2i"
QWEN_IMAGE_30_GLOBAL_PRO_I2I_MODEL = "qwen-image-3.0-global-pro-i2i"
QWEN_IMAGE_30_T2I_MODELS = [
    QWEN_IMAGE_30_T2I_MODEL,
    QWEN_IMAGE_30_PRO_T2I_MODEL,
    QWEN_IMAGE_30_GLOBAL_T2I_MODEL,
    QWEN_IMAGE_30_GLOBAL_PRO_T2I_MODEL,
]
QWEN_IMAGE_30_I2I_MODELS = [
    QWEN_IMAGE_30_I2I_MODEL,
    QWEN_IMAGE_30_PRO_I2I_MODEL,
    QWEN_IMAGE_30_GLOBAL_I2I_MODEL,
    QWEN_IMAGE_30_GLOBAL_PRO_I2I_MODEL,
]
QWEN_IMAGE_30_MODELS = [
    QWEN_IMAGE_30_T2I_MODEL,
    QWEN_IMAGE_30_I2I_MODEL,
    QWEN_IMAGE_30_PRO_T2I_MODEL,
    QWEN_IMAGE_30_PRO_I2I_MODEL,
    QWEN_IMAGE_30_GLOBAL_T2I_MODEL,
    QWEN_IMAGE_30_GLOBAL_I2I_MODEL,
    QWEN_IMAGE_30_GLOBAL_PRO_T2I_MODEL,
    QWEN_IMAGE_30_GLOBAL_PRO_I2I_MODEL,
]
QWEN_IMAGE_30_SIZING_MODES = ["auto", "ratio", "custom_size"]
QWEN_IMAGE_30_RESOLUTIONS = ["1k", "2k"]
QWEN_IMAGE_30_RATIOS = [
    "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9",
]
QWEN_IMAGE_30_PROMPT_MIN_LENGTH = 5
QWEN_IMAGE_30_PROMPT_MAX_LENGTH = 2000
MAX_QWEN_IMAGE_30_IMAGES = 3
ZHENZHEN_IMAGE_GK_V15_MODEL = "zhenzhen-image-gk-v15"
ZHENZHEN_IMAGE_GK_V15_EDIT_MODEL = "zhenzhen-image-gk-v15-edit"
ZHENZHEN_IMAGE_GK_V15_MODELS = [
    ZHENZHEN_IMAGE_GK_V15_MODEL,
    ZHENZHEN_IMAGE_GK_V15_EDIT_MODEL,
]
ZHENZHEN_IMAGE_GK_V15_SIZES = ["1:1", "16:9", "9:16", "3:2", "2:3"]
ZHENZHEN_IMAGE_GK_V15_PROMPT_MAX_LENGTH = 20000
ZHENZHEN_IMAGE_NB_FLASH_MODEL = "zhenzhen-image-nb-flash"
ZHENZHEN_IMAGE_NB_2_MODEL = "zhenzhen-image-nb-2"
ZHENZHEN_IMAGE_NB_2_LITE_MODEL = "zhenzhen-image-nb-2-lite"
ZHENZHEN_IMAGE_NB_PRO_MODEL = "zhenzhen-image-nb-pro"
ZHENZHEN_IMAGE_NB_MODELS = [
    ZHENZHEN_IMAGE_NB_FLASH_MODEL,
    ZHENZHEN_IMAGE_NB_2_MODEL,
    ZHENZHEN_IMAGE_NB_2_LITE_MODEL,
    ZHENZHEN_IMAGE_NB_PRO_MODEL,
]
ZHENZHEN_IMAGE_NB_STANDARD_SIZES = [
    "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9",
]
ZHENZHEN_IMAGE_NB_EXTREME_SIZES = [
    "1:1", "1:4", "1:8", "2:3", "3:2", "3:4", "4:1",
    "4:3", "4:5", "5:4", "8:1", "9:16", "16:9", "21:9",
]
ZHENZHEN_IMAGE_NB_SIZES = ["auto", *ZHENZHEN_IMAGE_NB_EXTREME_SIZES]
ZHENZHEN_IMAGE_NB_RESOLUTIONS = ["0.5k", "1k", "2k", "4k"]
ZHENZHEN_IMAGE_NB_MODEL_RESOLUTIONS = {
    ZHENZHEN_IMAGE_NB_FLASH_MODEL: ("1k",),
    ZHENZHEN_IMAGE_NB_2_MODEL: ("0.5k", "1k", "2k", "4k"),
    ZHENZHEN_IMAGE_NB_2_LITE_MODEL: ("1k",),
    ZHENZHEN_IMAGE_NB_PRO_MODEL: ("1k", "2k", "4k"),
}
ZHENZHEN_IMAGE_NB_MODEL_SIZES = {
    ZHENZHEN_IMAGE_NB_FLASH_MODEL: ("auto", *ZHENZHEN_IMAGE_NB_STANDARD_SIZES),
    ZHENZHEN_IMAGE_NB_2_MODEL: tuple(ZHENZHEN_IMAGE_NB_EXTREME_SIZES),
    ZHENZHEN_IMAGE_NB_2_LITE_MODEL: tuple(ZHENZHEN_IMAGE_NB_EXTREME_SIZES),
    ZHENZHEN_IMAGE_NB_PRO_MODEL: tuple(ZHENZHEN_IMAGE_NB_STANDARD_SIZES),
}
ZHENZHEN_IMAGE_NB_MODEL_N_RANGE = {
    ZHENZHEN_IMAGE_NB_FLASH_MODEL: (1, 1),
    ZHENZHEN_IMAGE_NB_2_MODEL: (1, 1),
    ZHENZHEN_IMAGE_NB_2_LITE_MODEL: (1, 4),
    ZHENZHEN_IMAGE_NB_PRO_MODEL: (1, 1),
}
MAX_ZHENZHEN_IMAGE_NB_IMAGES = 14
ZHENZHEN_IMAGE_NB_FLASH_PROMPT_MAX_LENGTH = 1000

ZHENZHEN_VIDEO_G_OMNI_FLASH_MODEL = "zhenzhen-video-g-omni-flash"
ZHENZHEN_VIDEO_GK_V15_MODEL = "zhenzhen-video-gk-v15"
ZHENZHEN_VIDEO_V31_FAST_MODEL = "zhenzhen-video-v31-fast"
ZHENZHEN_VIDEO_V31_QUALITY_MODEL = "zhenzhen-video-v31-quality"
ZHENZHEN_VIDEO_V31_LITE_MODEL = "zhenzhen-video-v31-lite"
ZHENZHEN_VIDEO_V31_MODELS = [
    ZHENZHEN_VIDEO_V31_FAST_MODEL,
    ZHENZHEN_VIDEO_V31_QUALITY_MODEL,
    ZHENZHEN_VIDEO_V31_LITE_MODEL,
]
ZHENZHEN_VIDEO_RESOLUTIONS = ["720p", "1080p"]
ZHENZHEN_VIDEO_SECONDS = [str(s) for s in range(4, 16)]
ZHENZHEN_VIDEO_GK_SECONDS = [str(s) for s in range(6, 31)]
MAX_ZHENZHEN_VIDEO_IMAGES = 2
ZHENZHEN_VIDEO_V31_RESOLUTIONS = ["720p", "1080p", "4k"]
ZHENZHEN_VIDEO_V31_RATIOS = ["16:9", "9:16"]
ZHENZHEN_VIDEO_V31_SECONDS = ["8"]
MAX_ZHENZHEN_VIDEO_V31_IMAGES = 3

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

HAILUO_H3_T2V_MODEL = "hailuo-h3-t2v"
HAILUO_H3_I2V_MODEL = "hailuo-h3-i2v"
HAILUO_H3_MULTI_MODEL = "hailuo-h3-multi"
HAILUO_H3_MODELS = [
    HAILUO_H3_T2V_MODEL,
    HAILUO_H3_I2V_MODEL,
    HAILUO_H3_MULTI_MODEL,
]
HAILUO_H3_SECONDS = [str(s) for s in range(5, 16)]
HAILUO_H3_RESOLUTIONS = ["2K"]
MAX_HAILUO_H3_IMAGES = 9
MAX_HAILUO_H3_VIDEOS = 3
MAX_HAILUO_H3_AUDIOS = 3

MINIMAX_H3_OW_T2V_MODEL = "minimax-h3-ow-t2v"
MINIMAX_H3_OW_R2V_MODEL = "minimax-h3-ow-r2v"
MINIMAX_H3_OW_I2V_MODEL = "minimax-h3-ow-i2v"
MINIMAX_H3_OW_MODELS = [
    MINIMAX_H3_OW_T2V_MODEL,
    MINIMAX_H3_OW_R2V_MODEL,
    MINIMAX_H3_OW_I2V_MODEL,
]
MINIMAX_H3_OW_SECONDS = ["5", "10", "15"]
MINIMAX_H3_OW_RESOLUTIONS = ["480p", "720p"]
MINIMAX_H3_OW_RATIOS = [
    "1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9",
]

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
WHISPER_TRANSCRIPTION_MODEL = "whisper-1"
WHISPER_RESPONSE_FORMATS = ["json", "verbose_json", "srt", "text", "vtt"]

SUNO_VERSIONS = ["v3.5", "v4", "v4.5", "v4.5+", "v4.5-all", "v5", "v5.5"]
SUNO_INSPO_VERSIONS = ["v4", "v4.5", "v4.5+", "v4.5-all", "v5", "v5.5"]
SUNO_REPLACE_VERSIONS = ["v4", "v4.5+", "v5", "v5.5"]
SUNO_REMASTER_VERSIONS = ["v4.5+", "v5", "v5.5"]
SUNO_V5_VERSIONS = ["v5", "v5.5"]
MAX_SUNO_REFERENCE_AUDIOS = 4
SUNO_UPLOAD_MIN_SECONDS = 6.0

SUNO_ACTION_SPECS: Dict[str, Dict[str, Any]] = {
    "suno-generation": {
        "action": "",
        "sync": False,
        "reference_type": "none",
        "required_fields": ("version", "prompt"),
        "allowed_fields": (
            "version",
            "prompt",
            "custom",
            "instrumental",
            "title",
            "style",
            "vocal_gender",
        ),
        "allowed_versions": tuple(SUNO_VERSIONS),
        "default_version": None,
        "result_family": "audio",
    },
    "suno-lyrics": {
        "action": "lyrics",
        "sync": False,
        "reference_type": "none",
        "required_fields": ("prompt",),
        "allowed_fields": ("prompt",),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "text",
    },
    "suno-upload": {
        "action": "upload",
        "sync": False,
        "reference_type": "url",
        "required_fields": ("audioFilePath",),
        "allowed_fields": ("audioFilePath",),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "audio",
    },
    "suno-extend": {
        "action": "extend",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id", "continue_at"),
        "allowed_fields": ("task_id", "audio_index", "continue_at", "version"),
        "allowed_versions": tuple(SUNO_VERSIONS),
        "default_version": "v5.5",
        "result_family": "audio",
    },
    "suno-cover-song": {
        "action": "cover-song",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id", "prompt"),
        "allowed_fields": ("task_id", "audio_index", "prompt", "version"),
        "allowed_versions": tuple(SUNO_VERSIONS),
        "default_version": "v5.5",
        "result_family": "audio",
    },
    "suno-inspo": {
        "action": "inspo",
        "sync": False,
        "reference_type": "url",
        "required_fields": ("audio_urls",),
        "allowed_fields": ("audio_urls", "version"),
        "allowed_versions": tuple(SUNO_INSPO_VERSIONS),
        "default_version": "v5.5",
        "result_family": "audio",
    },
    "suno-mashup": {
        "action": "mashup",
        "sync": False,
        "reference_type": "mashup",
        "required_fields": ("task_ids", "prompt"),
        "allowed_fields": ("task_ids", "prompt", "version"),
        "allowed_versions": tuple(SUNO_VERSIONS),
        "default_version": "v5.5",
        "result_family": "audio",
    },
    "suno-upsample-tags": {
        "action": "upsample-tags",
        "sync": True,
        "reference_type": "none",
        "required_fields": ("tags",),
        "allowed_fields": ("tags",),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "text",
    },
    "suno-sounds": {
        "action": "sounds",
        "sync": False,
        "reference_type": "none",
        "required_fields": ("prompt",),
        "allowed_fields": ("prompt", "version"),
        "allowed_versions": tuple(SUNO_V5_VERSIONS),
        "default_version": "v5.5",
        "result_family": "audio",
    },
    "suno-create-voice": {
        "action": "create-voice",
        "sync": False,
        "reference_type": "url",
        "required_fields": ("audio_url",),
        "allowed_fields": ("audio_url",),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "text",
    },
    "suno-stems": {
        "action": "stems",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id",),
        "allowed_fields": ("task_id", "audio_index"),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "audio",
    },
    "suno-stems-all": {
        "action": "stems-all",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id",),
        "allowed_fields": ("task_id", "audio_index"),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "audio",
    },
    "suno-wav": {
        "action": "wav",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id",),
        "allowed_fields": ("task_id", "audio_index"),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "audio",
    },
    "suno-generate-mp4": {
        "action": "generate-mp4",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id",),
        "allowed_fields": ("task_id", "audio_index"),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "video",
    },
    "suno-concat": {
        "action": "concat",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id",),
        "allowed_fields": ("task_id", "audio_index"),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "audio",
    },
    "suno-crop": {
        "action": "crop",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id", "start_s", "end_s"),
        "allowed_fields": ("task_id", "audio_index", "start_s", "end_s"),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "audio",
    },
    "suno-fade-in": {
        "action": "fade-in",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id", "duration_s"),
        "allowed_fields": ("task_id", "audio_index", "duration_s"),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "audio",
    },
    "suno-fade-out": {
        "action": "fade-out",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id", "duration_s"),
        "allowed_fields": ("task_id", "audio_index", "duration_s"),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "audio",
    },
    "suno-remove-section": {
        "action": "remove-section",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id", "start_s", "end_s"),
        "allowed_fields": ("task_id", "audio_index", "start_s", "end_s"),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "audio",
    },
    "suno-replace-music": {
        "action": "replace-music",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id", "start_s", "end_s"),
        "allowed_fields": (
            "task_id",
            "audio_index",
            "start_s",
            "end_s",
            "version",
        ),
        "allowed_versions": tuple(SUNO_REPLACE_VERSIONS),
        "default_version": "v5.5",
        "result_family": "audio",
    },
    "suno-adjust-speed": {
        "action": "adjust-speed",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id", "speed"),
        "allowed_fields": ("task_id", "audio_index", "speed"),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "audio",
    },
    "suno-remaster": {
        "action": "remaster",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id",),
        "allowed_fields": ("task_id", "audio_index", "version"),
        "allowed_versions": tuple(SUNO_REMASTER_VERSIONS),
        "default_version": "v5.5",
        "result_family": "audio",
    },
    "suno-midi": {
        "action": "midi",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id",),
        "allowed_fields": ("task_id", "audio_index"),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "file",
    },
    "suno-bpm": {
        "action": "bpm",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id",),
        "allowed_fields": ("task_id", "audio_index"),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "text",
    },
    "suno-aligned-lyrics": {
        "action": "aligned-lyrics",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id",),
        "allowed_fields": ("task_id", "audio_index"),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "text",
    },
    "suno-persona": {
        "action": "persona",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id", "name"),
        "allowed_fields": ("task_id", "audio_index", "name"),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "text",
    },
    "suno-vox": {
        "action": "vox",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id",),
        "allowed_fields": ("task_id", "audio_index"),
        "allowed_versions": (),
        "default_version": None,
        "result_family": "audio",
    },
    "suno-sample": {
        "action": "sample",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id", "start_s", "end_s", "prompt"),
        "allowed_fields": (
            "task_id",
            "audio_index",
            "prompt",
            "start_s",
            "end_s",
            "version",
        ),
        "allowed_versions": tuple(SUNO_VERSIONS),
        "default_version": "v5.5",
        "result_family": "audio",
    },
    "suno-add-vocals": {
        "action": "add-vocals",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id", "prompt"),
        "allowed_fields": ("task_id", "audio_index", "prompt", "version"),
        "allowed_versions": tuple(SUNO_V5_VERSIONS),
        "default_version": "v5.5",
        "result_family": "audio",
    },
    "suno-add-instrumental": {
        "action": "add-instrumental",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id", "prompt"),
        "allowed_fields": ("task_id", "audio_index", "prompt", "version"),
        "allowed_versions": tuple(SUNO_V5_VERSIONS),
        "default_version": "v5.5",
        "result_family": "audio",
    },
    "suno-add-stem": {
        "action": "add-stem",
        "sync": False,
        "reference_type": "task_audio",
        "required_fields": ("task_id", "prompt"),
        "allowed_fields": ("task_id", "audio_index", "prompt", "version"),
        "allowed_versions": ("v5.5",),
        "default_version": "v5.5",
        "result_family": "audio",
    },
}
SUNO_OPERATIONS = list(SUNO_ACTION_SPECS)

MIDJOURNEY_SPEEDS = ["relax", "fast", "turbo", "unset"]
MIDJOURNEY_VERSIONS = [
    "8.2",
    "8.1",
    "7",
    "6.1",
    "6",
    "5",
    "5.1",
    "5.2",
    "unset",
]
MIDJOURNEY_DIMENSIONS = ["SQUARE", "PORTRAIT", "LANDSCAPE", "unset"]
MIDJOURNEY_QUALITIES = ["1", "0.25", "0.5", "2", "unset"]
MIDJOURNEY_DIRECTIONS = ["right", "left", "up", "down", "unset"]
MIDJOURNEY_SIZES = [
    "1:1",
    "16:9",
    "9:16",
    "4:3",
    "3:4",
    "3:2",
    "2:3",
    "21:9",
    "custom",
]
MIDJOURNEY_MODAL_MODES = ["region", "outpaint"]
MIDJOURNEY_VIDEO_TYPES = [
    "vid_1.1_i2v_480",
    "vid_1.1_i2v_720",
    "vid_1.1_i2v_start_end_480",
    "vid_1.1_i2v_start_end_720",
]
MIDJOURNEY_ANIMATE_MODES = ["manual", "auto"]
MIDJOURNEY_MOTIONS = ["low", "high"]
MIDJOURNEY_BATCH_SIZES = [1, 2, 4]
MAX_MIDJOURNEY_IMAGES = 4

MIDJOURNEY_STRUCTURED_FIELDS = (
    "size",
    "quality",
    "style",
    "version",
    "seed",
    "negative_prompt",
    "stylize",
    "chaos",
    "weird",
    "tile",
    "niji",
    "iw",
    "cw",
    "sw",
    "cref",
    "sref",
    "dref",
    "dw",
    "repeat",
    "raw",
    "draft",
    "hd",
    "stop",
    "extra",
)

MIDJOURNEY_ACTION_SPECS: Dict[str, Dict[str, Any]] = {
    "midjourney-imagine": {
        "action": "imagine",
        "execution_mode": "async",
        "required_fields": ("prompt",),
        "required_one_of": (),
        "allowed_fields": (
            "prompt",
            "image_urls",
            "speed",
            "metadata",
            *MIDJOURNEY_STRUCTURED_FIELDS,
        ),
        "result_family": "image",
    },
    "midjourney-blend": {
        "action": "blend",
        "execution_mode": "async",
        "required_fields": ("image_urls",),
        "required_one_of": (),
        "allowed_fields": (
            "image_urls",
            "dimensions",
            "size",
            "speed",
            "metadata",
        ),
        "result_family": "image",
    },
    "midjourney-describe": {
        "action": "describe",
        "execution_mode": "sync_or_async",
        "required_fields": ("image_urls",),
        "required_one_of": (),
        "allowed_fields": ("image_urls", "speed", "metadata"),
        "result_family": "text",
    },
    "midjourney-edits": {
        "action": "edits",
        "execution_mode": "async",
        "required_fields": ("prompt", "image_urls"),
        "required_one_of": (),
        "allowed_fields": (
            "prompt",
            "image_urls",
            "speed",
            "metadata",
            *MIDJOURNEY_STRUCTURED_FIELDS,
        ),
        "result_family": "image",
    },
    "midjourney-upscale": {
        "action": "upscale",
        "execution_mode": "async",
        "required_fields": ("task_id",),
        "required_one_of": (("index", "custom_id"),),
        "allowed_fields": (
            "task_id",
            "index",
            "custom_id",
            "speed",
            "metadata",
        ),
        "result_family": "image",
    },
    "midjourney-variation": {
        "action": "variation",
        "execution_mode": "async",
        "required_fields": ("task_id",),
        "required_one_of": (("index", "custom_id"),),
        "allowed_fields": (
            "task_id",
            "index",
            "custom_id",
            "speed",
            "metadata",
        ),
        "result_family": "image",
    },
    "midjourney-high-variation": {
        "action": "high-variation",
        "execution_mode": "async",
        "required_fields": ("task_id",),
        "required_one_of": (("index", "custom_id"),),
        "allowed_fields": (
            "task_id",
            "index",
            "custom_id",
            "speed",
            "metadata",
        ),
        "result_family": "image",
    },
    "midjourney-low-variation": {
        "action": "low-variation",
        "execution_mode": "async",
        "required_fields": ("task_id",),
        "required_one_of": (("index", "custom_id"),),
        "allowed_fields": (
            "task_id",
            "index",
            "custom_id",
            "speed",
            "metadata",
        ),
        "result_family": "image",
    },
    "midjourney-reroll": {
        "action": "reroll",
        "execution_mode": "async",
        "required_fields": ("task_id",),
        "required_one_of": (),
        "allowed_fields": ("task_id", "custom_id", "speed", "metadata"),
        "result_family": "image",
    },
    "midjourney-zoom": {
        "action": "zoom",
        "execution_mode": "async",
        "required_fields": ("task_id",),
        "required_one_of": (),
        "allowed_fields": (
            "task_id",
            "index",
            "custom_id",
            "zoom_ratio",
            "speed",
            "metadata",
        ),
        "result_family": "image",
    },
    "midjourney-pan": {
        "action": "pan",
        "execution_mode": "async",
        "required_fields": ("task_id",),
        "required_one_of": (("direction", "custom_id"),),
        "allowed_fields": (
            "task_id",
            "index",
            "direction",
            "custom_id",
            "speed",
            "metadata",
        ),
        "result_family": "image",
    },
    "midjourney-inpaint": {
        "action": "inpaint",
        "execution_mode": "modal_stage",
        "required_fields": ("task_id",),
        "required_one_of": (),
        "allowed_fields": (
            "task_id",
            "index",
            "custom_id",
            "speed",
            "metadata",
        ),
        "result_family": "modal",
    },
    "midjourney-modal": {
        "action": "modal",
        "execution_mode": "async",
        "required_fields": ("task_id",),
        "required_one_of": (),
        "allowed_fields": (
            "task_id",
            "prompt",
            "mask_url",
            "speed",
            "metadata",
        ),
        "result_family": "image",
    },
    "midjourney-video": {
        "action": "video",
        "execution_mode": "async",
        "required_fields": (),
        "required_one_of": (("image_urls", "task_id"),),
        "allowed_fields": (
            "prompt",
            "image_urls",
            "task_id",
            "index",
            "video_type",
            "animate_mode",
            "motion",
            "batch_size",
            "end_url",
        ),
        "result_family": "video",
    },
    "midjourney-remix-strong": {
        "action": "remix-strong",
        "execution_mode": "async",
        "required_fields": ("task_id", "index"),
        "required_one_of": (),
        "allowed_fields": (
            "task_id",
            "index",
            "prompt",
            "speed",
        ),
        "result_family": "image",
    },
    "midjourney-remix-subtle": {
        "action": "remix-subtle",
        "execution_mode": "async",
        "required_fields": ("task_id", "index"),
        "required_one_of": (),
        "allowed_fields": (
            "task_id",
            "index",
            "prompt",
            "speed",
        ),
        "result_family": "image",
    },
}
MIDJOURNEY_OPERATIONS = list(MIDJOURNEY_ACTION_SPECS)
MIDJOURNEY_OPERATION_LABELS = {
    "midjourney-imagine": "midjourney-imagine｜文生图 / 参考图生成",
    "midjourney-blend": "midjourney-blend｜2-4 张图片融合",
    "midjourney-describe": "midjourney-describe｜图片反推提示词",
    "midjourney-edits": "midjourney-edits｜图片编辑",
    "midjourney-upscale": "midjourney-upscale｜指定图片放大",
    "midjourney-variation": "midjourney-variation｜生成图片变体",
    "midjourney-high-variation": "midjourney-high-variation｜大幅变体",
    "midjourney-low-variation": "midjourney-low-variation｜轻微变体",
    "midjourney-reroll": "midjourney-reroll｜重新生成整组",
    "midjourney-zoom": "midjourney-zoom｜缩放扩图",
    "midjourney-pan": "midjourney-pan｜平移扩图",
    "midjourney-inpaint": "midjourney-inpaint｜进入局部重绘",
    "midjourney-modal": "midjourney-modal｜提交局部重绘",
    "midjourney-video": "midjourney-video｜图生视频 / 首尾帧",
    "midjourney-remix-strong": "midjourney-remix-strong｜强重塑",
    "midjourney-remix-subtle": "midjourney-remix-subtle｜弱重塑",
}
MIDJOURNEY_OPERATION_CHOICES = [
    *MIDJOURNEY_OPERATION_LABELS.values(),
    *MIDJOURNEY_OPERATIONS,
]
MIDJOURNEY_OPERATION_BY_LABEL = {
    label: operation
    for operation, label in MIDJOURNEY_OPERATION_LABELS.items()
}


def _normalize_midjourney_operation(value: Any) -> str:
    operation = str(value or "").strip()
    return MIDJOURNEY_OPERATION_BY_LABEL.get(operation, operation)


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
        return ([{
            "base_url": base_url.strip(),
            "api_key": validate_api_key(api_key),
        }],)


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
        pbar = _make_progress_bar(100)
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
# Seedance 2.5 Standard video
# ---------------------------------------------------------------------------

class Seedance25Video(SeedanceVideoNodeBase):
    """Seedance 2.5 Standard t2v/i2v/multi across domestic and global routes."""

    @classmethod
    def INPUT_TYPES(cls):
        optional: Dict[str, tuple] = {}
        for index in range(1, MAX_SEEDANCE25_MULTI_IMAGES + 1):
            optional[f"image{index}"] = ("IMAGE", {
                "tooltip": (
                    f"Image {index}. I2V uses image1 as the first frame and image2 "
                    "as the optional last frame; Multi accepts up to 30 images. | "
                    f"图片 {index}；I2V 使用 image1 首帧和可选 image2 尾帧，"
                    "Multi 最多支持 30 张图片。"
                ),
            })
        for index in range(1, MAX_SEEDANCE25_MULTI_VIDEOS + 1):
            optional[f"video{index}"] = ("VIDEO", {
                "tooltip": (
                    f"Multi reference video {index}, up to 10 videos. Each clip must "
                    "be 2-30 seconds and combined reference media must not exceed 30 "
                    f"seconds. | Multi 参考视频 {index}，最多 10 个；单段需为 2-30 秒，"
                    "参考音视频总时长不能超过 30 秒。"
                ),
            })
        for index in range(1, MAX_SEEDANCE25_MULTI_AUDIOS + 1):
            optional[f"audio{index}"] = ("AUDIO", {
                "tooltip": (
                    f"Multi reference audio {index}, up to 10 audios. Each clip must "
                    "be 2-30 seconds and combined reference media must not exceed 30 "
                    f"seconds. | Multi 参考音频 {index}，最多 10 段；单段需为 2-30 秒，"
                    "参考音视频总时长不能超过 30 秒。"
                ),
            })
        optional.update(_optional_widgets())

        return {
            "required": {
                "model": (SEEDANCE25_MODELS, {
                    "default": SEEDANCE25_T2V_MODELS[0],
                    "tooltip": (
                        "Seedance 2.5 Standard domestic/global model and task type. | "
                        "Seedance 2.5 Standard 国内/海外线路及文生、图生或多模态模式。"
                    ),
                }),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": (
                        "Required for T2V and Multi; optional for I2V. Multi can use "
                        "@Image 1, @Video 1, and @Audio 1. | T2V 与 Multi 必填，"
                        "I2V 可选；Multi 可用 @Image 1、@Video 1、@Audio 1 指代素材。"
                    ),
                }),
                "seconds": (SEEDANCE25_SECONDS, {
                    "default": "4",
                    "tooltip": (
                        "4 to 30 seconds; -1 lets the model choose the duration. | "
                        "支持 4 到 30 秒；-1 表示由模型智能选择时长。"
                    ),
                }),
                "resolution": (SEEDANCE25_RESOLUTIONS, {
                    "default": "480p",
                    "tooltip": (
                        "Seedance 2.5 Standard output resolution; native presets are "
                        "not supported. | Seedance 2.5 Standard 输出分辨率，不支持 native 档。"
                    ),
                }),
                "ratio": (RATIOS, {
                    "default": "adaptive",
                    "tooltip": "Output aspect ratio. | 输出画面比例。",
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
        if model not in (None, *SEEDANCE25_MODELS):
            return f"unsupported Seedance 2.5 model: {model}"
        if seconds is not None and str(seconds) not in SEEDANCE25_SECONDS:
            return "Seedance 2.5 seconds must be -1 or 4 to 30 | Seedance 2.5 时长必须为 -1 或 4 到 30 秒"
        if resolution is not None and resolution not in SEEDANCE25_RESOLUTIONS:
            return f"unsupported Seedance 2.5 resolution: {resolution}"
        if ratio is not None and ratio not in RATIOS:
            return f"unsupported ratio: {ratio}"
        prompt_text = str(prompt or "")
        if len(prompt_text) > PROMPT_MAX_LENGTH:
            return f"prompt exceeds {PROMPT_MAX_LENGTH} characters ({len(prompt_text)})"
        if (
            strict
            and model in (*SEEDANCE25_T2V_MODELS, *SEEDANCE25_MULTI_MODELS)
            and not prompt_text.strip()
        ):
            return "prompt is required for Seedance 2.5 T2V and Multi | Seedance 2.5 文生与多模态必须填写提示词"
        return True

    @property
    def _log_prefix(self) -> str:
        return "Seedance_2_5_video"

    def _gather_slots(
        self,
        kwargs: Dict[str, Any],
        base_name: str,
        count: int,
    ) -> List[Tuple[int, Any]]:
        slots = [
            (index, kwargs.get(f"{base_name}{index}"))
            for index in range(1, count + 1)
            if kwargs.get(f"{base_name}{index}") is not None
        ]
        connected = [index for index, _value in slots]
        if connected and connected != list(range(1, len(connected) + 1)):
            print(
                f"[{self._log_prefix}] WARNING: {base_name} slots {connected} have gaps; "
                f"they will be compacted to {base_name} order 1..{len(connected)}."
            )
        return slots

    def collect_media(self, kwargs, config, progress_cb):
        model = kwargs.get("model")
        if model not in SEEDANCE25_MODELS:
            raise SeedanceAPIError(f"unsupported Seedance 2.5 model: {model}")
        if model in SEEDANCE25_T2V_MODELS:
            progress_cb(1.0)
            return {}

        image_limit = (
            2 if model in SEEDANCE25_I2V_MODELS
            else MAX_SEEDANCE25_MULTI_IMAGES
        )
        image_slots = self._gather_slots(kwargs, "image", image_limit)
        video_slots = (
            self._gather_slots(kwargs, "video", MAX_SEEDANCE25_MULTI_VIDEOS)
            if model in SEEDANCE25_MULTI_MODELS
            else []
        )
        audio_slots = (
            self._gather_slots(kwargs, "audio", MAX_SEEDANCE25_MULTI_AUDIOS)
            if model in SEEDANCE25_MULTI_MODELS
            else []
        )

        if model in SEEDANCE25_I2V_MODELS and kwargs.get("image1") is None:
            raise SeedanceAPIError(
                "image1 is required for Seedance 2.5 I2V | "
                "Seedance 2.5 图生视频必须连接 image1 首帧"
            )
        if model in SEEDANCE25_MULTI_MODELS and not (
            image_slots or video_slots or audio_slots
        ):
            raise SeedanceAPIError(
                "Seedance 2.5 Multi requires at least one image, video, or audio | "
                "Seedance 2.5 Multi 至少需要 1 个图片、视频或音频素材"
            )

        video_mime = {
            "mp4": "video/mp4",
            "avi": "video/x-msvideo",
            "mov": "video/quicktime",
            "mkv": "video/x-matroska",
        }
        total = len(image_slots) + len(video_slots) + len(audio_slots)
        completed = 0
        image_urls: List[str] = []
        content: List[Dict[str, Any]] = []

        for slot, image in image_slots:
            url = upload_media(
                image_to_png_bytes(image),
                f"seedance25_image_{slot}.png",
                "image/png",
                config,
                logger_prefix=self._log_prefix,
            )
            image_urls.append(url)
            if model in SEEDANCE25_MULTI_MODELS:
                content.append({"type": "image_url", "image_url": {"url": url}})
            completed += 1
            progress_cb(completed / total)

        for slot, video in video_slots:
            video_bytes, extension = video_to_bytes(video)
            url = upload_media(
                video_bytes,
                f"seedance25_video_{slot}.{extension}",
                video_mime.get(extension, "video/mp4"),
                config,
                logger_prefix=self._log_prefix,
            )
            content.append({"type": "video_url", "video_url": {"url": url}})
            completed += 1
            progress_cb(completed / total)

        for slot, audio in audio_slots:
            url = upload_media(
                audio_to_wav_bytes(audio),
                f"seedance25_audio_{slot}.wav",
                "audio/wav",
                config,
                logger_prefix=self._log_prefix,
            )
            content.append({"type": "audio_url", "audio_url": {"url": url}})
            completed += 1
            progress_cb(completed / total)

        if model in SEEDANCE25_I2V_MODELS:
            return {"images": image_urls}
        return {"content": content}

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

        metadata: Dict[str, Any] = {
            "resolution": kwargs["resolution"],
            "ratio": str(kwargs.get("ratio") or "adaptive"),
            "generate_audio": bool(kwargs.get("generate_audio", True)),
        }
        seed = kwargs.get("seed", -1)
        if seed is not None and int(seed) >= 0:
            metadata["seed"] = int(seed)

        payload: Dict[str, Any] = {"model": model, "metadata": metadata}
        seconds = str(kwargs["seconds"])
        if seconds == "-1":
            metadata["duration"] = -1
        else:
            payload["seconds"] = seconds

        if model in SEEDANCE25_T2V_MODELS:
            payload["prompt"] = prompt
            return payload

        if model in SEEDANCE25_I2V_MODELS:
            images = media.get("images") or []
            if not images:
                raise SeedanceAPIError(
                    "image1 is required for Seedance 2.5 I2V | "
                    "Seedance 2.5 图生视频必须连接 image1 首帧"
                )
            payload["images"] = images[:2]
            if prompt:
                payload["prompt"] = prompt
            return payload

        content = media.get("content") or []
        if not content:
            raise SeedanceAPIError(
                "Seedance 2.5 Multi requires at least one image, video, or audio | "
                "Seedance 2.5 Multi 至少需要 1 个图片、视频或音频素材"
            )
        payload["prompt"] = prompt
        metadata["content"] = content
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
# Zhenzhen video generation
# ---------------------------------------------------------------------------

class ZhenzhenVideoGenerationBase(SeedanceVideoNodeBase):
    """Shared Zhenzhen video text/image-to-video payload shape."""

    MODELS: List[str] = []
    DEFAULT_MODEL = ""
    LOG_PREFIX = "Zhenzhen_video"
    SECONDS = ZHENZHEN_VIDEO_SECONDS
    DEFAULT_SECONDS = "4"
    SUPPORTED_RESOLUTIONS = ZHENZHEN_VIDEO_RESOLUTIONS
    SUPPORTED_RATIOS = RATIOS
    DEFAULT_RATIO = "16:9"
    MAX_IMAGES = MAX_ZHENZHEN_VIDEO_IMAGES

    @classmethod
    def INPUT_TYPES(cls):
        optional: Dict[str, tuple] = {}
        for i in range(1, cls.MAX_IMAGES + 1):
            optional[f"image{i}"] = ("IMAGE", {
                "tooltip": (
                    f"Optional reference image {i}; connected images are submitted as images[]. | "
                    f"可选参考图 {i}，连接后通过 images[] 提交。"
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
                "model": (cls.MODELS, {
                    "default": cls.DEFAULT_MODEL,
                    "tooltip": "Zhenzhen video model. | Zhenzhen 视频模型。",
                }),
                "prompt": _prompt_input(required=True),
                "seconds": (cls.SECONDS, {
                    "default": cls.DEFAULT_SECONDS,
                    "tooltip": "Video duration in seconds, submitted as a string. | 视频时长，按字符串提交。",
                }),
                "resolution": (cls.SUPPORTED_RESOLUTIONS, {
                    "default": cls.SUPPORTED_RESOLUTIONS[0],
                    "tooltip": "Target resolution. | 目标分辨率。",
                }),
                "ratio": (cls.SUPPORTED_RATIOS, {
                    "default": cls.DEFAULT_RATIO,
                    "tooltip": "Optional aspect ratio forwarded as metadata.ratio. | 可选画幅比例，透传为 metadata.ratio。",
                }),
                "negative_prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Optional negative prompt forwarded to metadata. | 可选反向提示词，透传到 metadata。",
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
        resolution=None,
        ratio=None,
        negative_prompt=None,
        seed=None,
        strict=False,
        **kwargs,
    ):
        if model not in (None, *cls.MODELS):
            return f"unsupported Zhenzhen video model: {model}"
        if seconds is not None and str(seconds) not in cls.SECONDS:
            return (
                f"Zhenzhen video seconds must be one of {', '.join(cls.SECONDS)} | "
                "Zhenzhen 视频时长不在当前模型支持范围内"
            )
        if resolution is not None and resolution not in cls.SUPPORTED_RESOLUTIONS:
            return (
                f"Zhenzhen video resolution must be one of {', '.join(cls.SUPPORTED_RESOLUTIONS)} | "
                "Zhenzhen 视频分辨率不在当前模型支持范围内"
            )
        if ratio is not None and ratio not in cls.SUPPORTED_RATIOS:
            return f"unsupported ratio: {ratio}"
        if prompt is not None and len(str(prompt)) > PROMPT_MAX_LENGTH:
            return f"prompt exceeds {PROMPT_MAX_LENGTH} characters ({len(str(prompt))})"
        if strict and not str(prompt or "").strip():
            return "prompt is required for Zhenzhen video | Zhenzhen 视频必须填写提示词"
        if negative_prompt is not None and len(str(negative_prompt)) > PROMPT_MAX_LENGTH:
            return f"negative_prompt exceeds {PROMPT_MAX_LENGTH} characters ({len(str(negative_prompt))})"
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
        return self.LOG_PREFIX

    def _connected_images(self, kwargs: Dict[str, Any]) -> List[Tuple[int, Any]]:
        slots = [
            (i, kwargs.get(f"image{i}"))
            for i in range(1, self.MAX_IMAGES + 1)
            if kwargs.get(f"image{i}") is not None
        ]
        connected = [i for i, _ in slots]
        if connected and connected != list(range(1, len(connected) + 1)):
            print(
                f"[{self._log_prefix}] WARNING: image slots {connected} have gaps; "
                f"they will be compacted to images order 1..{len(connected)}."
            )
        return slots

    def collect_media(self, kwargs, config, progress_cb):
        image_slots = self._connected_images(kwargs)
        if not image_slots:
            progress_cb(1.0)
            return {}

        urls = []
        for done, (slot, image) in enumerate(image_slots, start=1):
            url = upload_media(
                image_to_png_bytes(image),
                f"{self._log_prefix.lower()}_reference_{slot}.png",
                "image/png",
                config,
                logger_prefix=self._log_prefix,
            )
            urls.append(url)
            progress_cb(done / len(image_slots))
        return {"images": urls}

    def build_payload(self, kwargs, media):
        prompt = str(kwargs.get("prompt") or "").strip()
        validation = self.VALIDATE_INPUTS(
            model=kwargs.get("model"),
            prompt=prompt,
            seconds=kwargs.get("seconds"),
            resolution=kwargs.get("resolution"),
            ratio=kwargs.get("ratio"),
            negative_prompt=kwargs.get("negative_prompt"),
            seed=kwargs.get("seed"),
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        metadata: Dict[str, Any] = {"resolution": kwargs["resolution"]}
        ratio = str(kwargs.get("ratio") or "").strip()
        if ratio and ratio != "adaptive":
            metadata["ratio"] = ratio
        negative_prompt = str(kwargs.get("negative_prompt") or "").strip()
        if negative_prompt:
            metadata["negative_prompt"] = negative_prompt
        seed = kwargs.get("seed", -1)
        if seed is not None and int(seed) >= 0:
            metadata["seed"] = int(seed)

        payload: Dict[str, Any] = {
            "model": kwargs["model"],
            "prompt": prompt,
            "seconds": str(kwargs["seconds"]),
            "metadata": metadata,
        }
        images = media.get("images") or []
        if images:
            payload["images"] = images[:self.MAX_IMAGES]
        return payload


class ZhenzhenVideoGOmniFlash(ZhenzhenVideoGenerationBase):
    """zhenzhen-video-g-omni-flash via /v1/videos."""

    MODELS = [ZHENZHEN_VIDEO_G_OMNI_FLASH_MODEL]
    DEFAULT_MODEL = ZHENZHEN_VIDEO_G_OMNI_FLASH_MODEL
    LOG_PREFIX = "Zhenzhen_video_g_omni_flash"


class ZhenzhenVideoGKV15(ZhenzhenVideoGenerationBase):
    """zhenzhen-video-gk-v15 via /v1/videos."""

    MODELS = [ZHENZHEN_VIDEO_GK_V15_MODEL]
    DEFAULT_MODEL = ZHENZHEN_VIDEO_GK_V15_MODEL
    LOG_PREFIX = "Zhenzhen_video_gk_v15"
    SECONDS = ZHENZHEN_VIDEO_GK_SECONDS
    DEFAULT_SECONDS = "6"


class ZhenzhenVideoV31(ZhenzhenVideoGenerationBase):
    """Zhenzhen Video V3.1 fast/quality/lite via /v1/videos."""

    MODELS = ZHENZHEN_VIDEO_V31_MODELS
    DEFAULT_MODEL = ZHENZHEN_VIDEO_V31_FAST_MODEL
    LOG_PREFIX = "Zhenzhen_video_v31"
    SECONDS = ZHENZHEN_VIDEO_V31_SECONDS
    DEFAULT_SECONDS = "8"
    SUPPORTED_RESOLUTIONS = ZHENZHEN_VIDEO_V31_RESOLUTIONS
    SUPPORTED_RATIOS = ZHENZHEN_VIDEO_V31_RATIOS
    MAX_IMAGES = MAX_ZHENZHEN_VIDEO_V31_IMAGES

    def _validate_image_mode(self, model: str, images: List[Any]):
        if model == ZHENZHEN_VIDEO_V31_LITE_MODEL and images:
            raise SeedanceAPIError(
                "zhenzhen-video-v31-lite is text-to-video only and does not accept images | "
                "zhenzhen-video-v31-lite 仅支持文生视频，不能连接图片"
            )
        if model == ZHENZHEN_VIDEO_V31_QUALITY_MODEL and len(images) >= 3:
            raise SeedanceAPIError(
                "zhenzhen-video-v31-quality does not accept 3-image reference mode | "
                "zhenzhen-video-v31-quality 不支持三图 reference 模式"
            )

    def collect_media(self, kwargs, config, progress_cb):
        image_slots = self._connected_images(kwargs)
        self._validate_image_mode(kwargs.get("model"), [image for _, image in image_slots])
        return super().collect_media(kwargs, config, progress_cb)

    def build_payload(self, kwargs, media):
        images = list(media.get("images") or [])
        self._validate_image_mode(kwargs.get("model"), images)
        return super().build_payload(kwargs, media)


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
# Hailuo H3 video
# ---------------------------------------------------------------------------

class HailuoH3Video(SeedanceVideoNodeBase):
    """Hailuo H3 t2v/i2v/multi via /v1/videos."""

    @classmethod
    def INPUT_TYPES(cls):
        optional: Dict[str, tuple] = {}
        for i in range(1, MAX_HAILUO_H3_IMAGES + 1):
            optional[f"image{i}"] = ("IMAGE", {
                "tooltip": (
                    f"H3 image {i}. I2V uses image1 as the first frame and image2 as "
                    f"the optional last frame; Multi accepts up to 9 images. | H3 图片 {i}；"
                    "I2V 用 image1 作为首帧、image2 作为可选尾帧；Multi 最多支持 9 张图。"
                ),
            })
        for i in range(1, MAX_HAILUO_H3_VIDEOS + 1):
            optional[f"video{i}"] = ("VIDEO", {
                "tooltip": (
                    f"H3 Multi reference video {i}, up to 3 videos. | "
                    f"H3 Multi 参考视频 {i}，最多 3 个。"
                ),
            })
        for i in range(1, MAX_HAILUO_H3_AUDIOS + 1):
            optional[f"audio{i}"] = ("AUDIO", {
                "tooltip": (
                    f"H3 Multi reference audio {i}, up to 3 audios. | "
                    f"H3 Multi 参考音频 {i}，最多 3 个。"
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
                "model": (HAILUO_H3_MODELS, {
                    "default": HAILUO_H3_T2V_MODEL,
                    "tooltip": (
                        "Hailuo H3 task type: text-to-video, first/last-frame "
                        "image-to-video, or multimodal reference video. | Hailuo H3 "
                        "支持文生视频、首尾帧图生视频和多模态参考生视频。"
                    ),
                }),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": (
                        "Required for T2V and Multi; optional for I2V. Multi prompts can "
                        "reference @Image 1, @Video 1, and @Audio 1. | T2V 与 Multi 必填，"
                        "I2V 可选；Multi 可用 @Image 1、@Video 1、@Audio 1 指代素材。"
                    ),
                }),
                "seconds": (HAILUO_H3_SECONDS, {
                    "default": "5",
                    "tooltip": "Hailuo H3 supports 5 to 15 seconds. | Hailuo H3 支持 5 到 15 秒。",
                }),
                "resolution": (HAILUO_H3_RESOLUTIONS, {
                    "default": "2K",
                    "tooltip": "Hailuo H3 output resolution is fixed to 2K. | Hailuo H3 输出分辨率固定为 2K。",
                }),
                "ratio": (RATIOS, {
                    "default": "16:9",
                    "tooltip": (
                        "Used by H3 T2V and Multi, including adaptive; I2V follows the "
                        "input frame. | H3 T2V 与 Multi 使用，支持 adaptive；I2V 跟随输入帧。"
                    ),
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
        if model not in (None, *HAILUO_H3_MODELS):
            return f"unsupported Hailuo H3 model: {model}"
        if seconds is not None and str(seconds) not in HAILUO_H3_SECONDS:
            return "Hailuo H3 seconds must be 5 to 15 | Hailuo H3 时长必须为 5 到 15 秒"
        if resolution is not None and resolution not in HAILUO_H3_RESOLUTIONS:
            return "Hailuo H3 resolution must be 2K | Hailuo H3 分辨率必须为 2K"
        if ratio is not None and ratio not in RATIOS:
            return f"unsupported ratio: {ratio}"
        prompt_text = str(prompt or "")
        if len(prompt_text) > PROMPT_MAX_LENGTH:
            return f"prompt exceeds {PROMPT_MAX_LENGTH} characters ({len(prompt_text)})"
        if (
            strict
            and model in (HAILUO_H3_T2V_MODEL, HAILUO_H3_MULTI_MODEL)
            and not prompt_text.strip()
        ):
            return "prompt is required for Hailuo H3 T2V and Multi | Hailuo H3 文生与多模态必须填写提示词"
        return True

    @property
    def _log_prefix(self) -> str:
        return "Hailuo_H3_video"

    def _gather_slots(
        self,
        kwargs: Dict[str, Any],
        base_name: str,
        count: int,
    ) -> List[Tuple[int, Any]]:
        slots = [
            (i, kwargs.get(f"{base_name}{i}"))
            for i in range(1, count + 1)
            if kwargs.get(f"{base_name}{i}") is not None
        ]
        connected = [i for i, _ in slots]
        if connected and connected != list(range(1, len(connected) + 1)):
            print(
                f"[{self._log_prefix}] WARNING: {base_name} slots {connected} have gaps; "
                f"they will be compacted to {base_name} order 1..{len(connected)}."
            )
        return slots

    def collect_media(self, kwargs, config, progress_cb):
        model = kwargs.get("model")
        if model == HAILUO_H3_T2V_MODEL:
            progress_cb(1.0)
            return {}

        if model == HAILUO_H3_I2V_MODEL and kwargs.get("image1") is None:
            raise SeedanceAPIError(
                "image1 is required for Hailuo H3 I2V | Hailuo H3 图生视频必须连接 image1 首帧"
            )

        image_limit = 2 if model == HAILUO_H3_I2V_MODEL else MAX_HAILUO_H3_IMAGES
        image_slots = self._gather_slots(kwargs, "image", image_limit)
        video_slots = (
            self._gather_slots(kwargs, "video", MAX_HAILUO_H3_VIDEOS)
            if model == HAILUO_H3_MULTI_MODEL
            else []
        )
        audio_slots = (
            self._gather_slots(kwargs, "audio", MAX_HAILUO_H3_AUDIOS)
            if model == HAILUO_H3_MULTI_MODEL
            else []
        )

        if model == HAILUO_H3_MULTI_MODEL and not (
            image_slots or video_slots or audio_slots
        ):
            raise SeedanceAPIError(
                "Hailuo H3 Multi requires at least one image, video, or audio | "
                "Hailuo H3 Multi 至少需要 1 个图片、视频或音频素材"
            )

        video_mime = {
            "mp4": "video/mp4",
            "avi": "video/x-msvideo",
            "mov": "video/quicktime",
            "mkv": "video/x-matroska",
        }
        total = len(image_slots) + len(video_slots) + len(audio_slots)
        done = 0
        image_urls: List[str] = []
        video_urls: List[str] = []
        audio_urls: List[str] = []

        for slot, image in image_slots:
            image_urls.append(upload_media(
                image_to_png_bytes(image),
                f"hailuo_h3_image_{slot}.png",
                "image/png",
                config,
                logger_prefix=self._log_prefix,
            ))
            done += 1
            progress_cb(done / total)

        for slot, video in video_slots:
            video_bytes, ext = video_to_bytes(video)
            video_urls.append(upload_media(
                video_bytes,
                f"hailuo_h3_video_{slot}.{ext}",
                video_mime.get(ext, "video/mp4"),
                config,
                logger_prefix=self._log_prefix,
            ))
            done += 1
            progress_cb(done / total)

        for slot, audio in audio_slots:
            audio_urls.append(upload_media(
                audio_to_wav_bytes(audio),
                f"hailuo_h3_audio_{slot}.wav",
                "audio/wav",
                config,
                logger_prefix=self._log_prefix,
            ))
            done += 1
            progress_cb(done / total)

        return {
            "images": image_urls,
            "video_urls": video_urls,
            "audio_urls": audio_urls,
        }

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

        if model in (HAILUO_H3_T2V_MODEL, HAILUO_H3_MULTI_MODEL):
            metadata["ratio"] = str(kwargs.get("ratio") or "adaptive")
            payload["prompt"] = prompt

        images = media.get("images") or []
        if model == HAILUO_H3_I2V_MODEL:
            if not images:
                raise SeedanceAPIError(
                    "image1 is required for Hailuo H3 I2V | Hailuo H3 图生视频必须连接 image1 首帧"
                )
            payload["images"] = images[:2]
            if prompt:
                payload["prompt"] = prompt
            return payload

        if model == HAILUO_H3_MULTI_MODEL:
            video_urls = media.get("video_urls") or []
            audio_urls = media.get("audio_urls") or []
            if not (images or video_urls or audio_urls):
                raise SeedanceAPIError(
                    "Hailuo H3 Multi requires at least one image, video, or audio | "
                    "Hailuo H3 Multi 至少需要 1 个图片、视频或音频素材"
                )
            if images:
                payload["images"] = images[:MAX_HAILUO_H3_IMAGES]
            if video_urls:
                metadata["video_url"] = video_urls[:MAX_HAILUO_H3_VIDEOS]
            if audio_urls:
                metadata["audio_url"] = audio_urls[:MAX_HAILUO_H3_AUDIOS]
        return payload


# ---------------------------------------------------------------------------
# MiniMax H3 OW video
# ---------------------------------------------------------------------------

class MinimaxH3OWVideo(SeedanceVideoNodeBase):
    """MiniMax H3 OW t2v/i2v/r2v via /v1/videos."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": (MINIMAX_H3_OW_MODELS, {
                    "default": MINIMAX_H3_OW_T2V_MODEL,
                    "tooltip": (
                        "MiniMax H3 OW task type: text-to-video, image-to-video, "
                        "or reference-image-to-video. | MiniMax H3 OW 支持文生视频、"
                        "图生视频和参考图生视频。"
                    ),
                }),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": (
                        "Required for T2V and R2V; optional for I2V. | "
                        "T2V 与 R2V 必填，I2V 可选。"
                    ),
                }),
                "seconds": (MINIMAX_H3_OW_SECONDS, {
                    "default": "5",
                    "tooltip": "MiniMax H3 OW supports 5, 10, or 15 seconds. | 支持 5、10 或 15 秒。",
                }),
                "resolution": (MINIMAX_H3_OW_RESOLUTIONS, {
                    "default": "480p",
                    "tooltip": "MiniMax H3 OW supports 480p or 720p. | 支持 480p 或 720p。",
                }),
                "ratio": (MINIMAX_H3_OW_RATIOS, {
                    "default": "16:9",
                    "tooltip": "Documented MiniMax H3 OW output aspect ratio. | 文档支持的输出画幅。",
                }),
            },
            "optional": {
                "image1": ("IMAGE", {
                    "tooltip": (
                        "Required for I2V and R2V; ignored by T2V. | "
                        "I2V 与 R2V 必须连接，T2V 不使用。"
                    ),
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
    def VALIDATE_INPUTS(
        cls,
        model=None,
        prompt=None,
        seconds=None,
        resolution=None,
        ratio=None,
        image1=None,
        strict=False,
        **kwargs,
    ):
        if model not in (None, *MINIMAX_H3_OW_MODELS):
            return f"unsupported MiniMax H3 OW model: {model}"
        if seconds is not None and str(seconds) not in MINIMAX_H3_OW_SECONDS:
            return "MiniMax H3 OW seconds must be 5, 10, or 15 | 时长必须为 5、10 或 15 秒"
        if resolution is not None and resolution not in MINIMAX_H3_OW_RESOLUTIONS:
            return "MiniMax H3 OW resolution must be 480p or 720p | 分辨率必须为 480p 或 720p"
        if ratio is not None and ratio not in MINIMAX_H3_OW_RATIOS:
            return f"unsupported MiniMax H3 OW ratio: {ratio}"
        prompt_text = str(prompt or "").strip()
        if len(prompt_text) > PROMPT_MAX_LENGTH:
            return f"prompt exceeds {PROMPT_MAX_LENGTH} characters ({len(prompt_text)})"
        if (
            strict
            and model in (MINIMAX_H3_OW_T2V_MODEL, MINIMAX_H3_OW_R2V_MODEL)
            and not prompt_text
        ):
            return "prompt is required for MiniMax H3 OW T2V and R2V | 文生与参考生视频必须填写提示词"
        if strict and model in (MINIMAX_H3_OW_I2V_MODEL, MINIMAX_H3_OW_R2V_MODEL) and image1 is None:
            return "image1 is required for MiniMax H3 OW I2V and R2V | 图生与参考生视频必须连接 image1"
        return True

    @property
    def _log_prefix(self) -> str:
        return "Minimax_H3_OW_video"

    def collect_media(self, kwargs, config, progress_cb):
        model = kwargs.get("model")
        if model == MINIMAX_H3_OW_T2V_MODEL:
            progress_cb(1.0)
            return {}

        image = kwargs.get("image1")
        if image is None:
            raise SeedanceAPIError(
                "image1 is required for MiniMax H3 OW I2V and R2V | "
                "MiniMax H3 OW 图生与参考生视频必须连接 image1"
            )
        image_url = upload_media(
            image_to_png_bytes(image),
            "minimax_h3_ow_reference.png",
            "image/png",
            config,
            logger_prefix=self._log_prefix,
        )
        progress_cb(1.0)
        return {"images": [image_url]}

    def build_payload(self, kwargs, media):
        model = kwargs["model"]
        prompt = str(kwargs.get("prompt") or "").strip()
        validation = self.VALIDATE_INPUTS(
            model=model,
            prompt=prompt,
            seconds=kwargs.get("seconds"),
            resolution=kwargs.get("resolution"),
            ratio=kwargs.get("ratio"),
            image1=kwargs.get("image1"),
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        payload: Dict[str, Any] = {
            "model": model,
            "seconds": str(kwargs["seconds"]),
            "metadata": {
                "resolution": kwargs["resolution"],
                "ratio": kwargs["ratio"],
            },
        }
        if prompt:
            payload["prompt"] = prompt
        if model != MINIMAX_H3_OW_T2V_MODEL:
            images = media.get("images") or []
            if not images:
                raise SeedanceAPIError(
                    "image1 is required for MiniMax H3 OW I2V and R2V | "
                    "MiniMax H3 OW 图生与参考生视频必须连接 image1"
                )
            payload["images"] = images[:1]
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
        pbar = _make_progress_bar(100)
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
    """Zhenzhen Image G text-to-image and image-to-image."""

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
                    f"Optional reference image {i} of {MAX_ZHENZHEN_IMAGE_G_V2_LOWPRICE_IMAGES}; "
                    "G-2 i2i accepts image1..image10; lowprice accepts image1..image16. | "
                    "可选参考图；G-2 图像编辑支持前 10 张，lowprice 支持 16 张。"
                ),
            })
            for i in range(1, MAX_ZHENZHEN_IMAGE_G_V2_LOWPRICE_IMAGES + 1)
        }
        optional["api_config"] = ("SEEDANCE_CONFIG", {
            "tooltip": "Connect Seedance API Config; otherwise SEEDANCE_API_KEY is used.",
        })

        return {
            "required": {
                "model": (ZHENZHEN_IMAGE_G2_MODELS, {
                    "default": ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL,
                    "tooltip": (
                        "Zhenzhen Image G task type. g2-t2i uses prompt only; "
                        "g2-i2i requires images; lowprice can run with or without images. | "
                        "G-2 文生图只用提示词；G-2 图生图需要参考图；lowprice 可选参考图。"
                    ),
                }),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": (
                        "Lowprice prompt: 5 to 5000 characters; G-2 prompt: up to "
                        "20000 characters. | Lowprice 提示词 5 到 5000 字符；"
                        "G-2 提示词最多 20000 字符。"
                    ),
                }),
                "resolution": (ZHENZHEN_IMAGE_G_V2_LOWPRICE_RESOLUTIONS, {
                    "default": "1k",
                    "tooltip": (
                        "G-2 supports 1k only; lowprice supports 1k, 2k, and 4k. | "
                        "G-2 仅支持 1k；lowprice 支持 1k、2k、4k。"
                    ),
                }),
                "ratio": (RATIOS, {
                    "default": "adaptive",
                    "tooltip": (
                        "G-2 only: optional metadata.ratio. Hidden for lowprice. | "
                        "仅 G-2 使用 metadata.ratio；lowprice 模型会隐藏。"
                    ),
                }),
                "size": (ZHENZHEN_IMAGE_G_V2_LOWPRICE_SIZES, {
                    "default": "1:1",
                    "tooltip": (
                        "Lowprice only: common aspect ratios; choose custom for another ratio or WxH. | "
                        "仅 lowprice 使用：常用画幅比例；选择 custom 可填写其他比例或 WxH。"
                    ),
                }),
                "custom_size": ("STRING", {
                    "default": "",
                    "tooltip": (
                        "Lowprice custom size, for example 5:4 or 2048x1024. | "
                        "Lowprice 自定义尺寸，例如 5:4 或 2048x1024。"
                    ),
                }),
                "n": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 10,
                    "step": 1,
                    "tooltip": (
                        "Lowprice only: top-level image count, 1 to 10. | "
                        "仅 lowprice 使用：顶层图片数量，1 到 10。"
                    ),
                }),
            },
            "optional": optional,
        }

    @staticmethod
    def _normalize_lowprice_size(value: Any) -> str:
        return str(value or "").strip().replace("X", "x")

    @classmethod
    def _valid_lowprice_size(cls, value: Any) -> bool:
        size_text = cls._normalize_lowprice_size(value)
        separator = ":" if ":" in size_text else "x" if "x" in size_text else ""
        if not separator:
            return False
        parts = [part.strip() for part in size_text.split(separator)]
        return (
            len(parts) == 2
            and all(part.isdigit() and int(part) > 0 for part in parts)
        )

    @classmethod
    def _resolve_lowprice_size(
        cls,
        size: Any,
        custom_size: Any = "",
    ) -> str:
        selected = cls._normalize_lowprice_size(size)
        resolved = (
            cls._normalize_lowprice_size(custom_size)
            if selected == "custom"
            else selected
        )
        if not cls._valid_lowprice_size(resolved):
            raise SeedanceAPIError(
                "lowprice size must be a positive aspect ratio or WxH, "
                "for example 16:9 or 2048x1024 | "
                "lowprice size 必须是正数画幅比例或 WxH，例如 16:9 或 2048x1024"
            )
        return resolved

    @classmethod
    def VALIDATE_INPUTS(
        cls,
        model=None,
        prompt=None,
        resolution=None,
        ratio=None,
        size=None,
        custom_size=None,
        n=None,
        strict=False,
        **kwargs,
    ):
        if model not in (None, *ZHENZHEN_IMAGE_G2_MODELS):
            return f"unsupported Zhenzhen Image G model: {model}"
        prompt_text = str(prompt or "").strip()
        if strict and not prompt_text:
            return "prompt is required for Zhenzhen Image G | Zhenzhen Image G 必须填写提示词"
        if model == ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL and prompt_text and strict:
            prompt_length = len(prompt_text)
            if prompt_length < ZHENZHEN_IMAGE_G_V2_LOWPRICE_PROMPT_MIN_LENGTH:
                return (
                    "lowprice prompt must contain 5 to 5000 characters "
                    f"({prompt_length}) | lowprice 提示词必须包含 5 到 5000 个字符"
                )
            if prompt_length > ZHENZHEN_IMAGE_G_V2_LOWPRICE_PROMPT_MAX_LENGTH:
                return (
                    "lowprice prompt must contain 5 to 5000 characters "
                    f"({prompt_length}) | lowprice 提示词必须包含 5 到 5000 个字符"
                )
        elif prompt_text and len(prompt_text) > ZHENZHEN_IMAGE_G2_PROMPT_MAX_LENGTH:
            return (
                f"prompt exceeds {ZHENZHEN_IMAGE_G2_PROMPT_MAX_LENGTH} characters "
                f"({len(prompt_text)}) | 提示词不能超过 {ZHENZHEN_IMAGE_G2_PROMPT_MAX_LENGTH} 字符"
            )
        if model in (ZHENZHEN_IMAGE_G2_T2I_MODEL, ZHENZHEN_IMAGE_G2_I2I_MODEL):
            if resolution is not None and resolution not in ZHENZHEN_IMAGE_G2_RESOLUTIONS:
                return "Zhenzhen Image G-2 resolution must be 1k | Zhenzhen Image G-2 分辨率只能是 1k"
            if ratio is not None and ratio not in RATIOS:
                return f"unsupported G-2 ratio: {ratio}"
        elif model == ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL:
            if (
                resolution is not None
                and resolution not in ZHENZHEN_IMAGE_G_V2_LOWPRICE_RESOLUTIONS
            ):
                return f"unsupported lowprice resolution: {resolution}"
            should_validate_size = (
                size is not None
                and (
                    str(size).strip() != "custom"
                    or strict
                    or str(custom_size or "").strip()
                )
            )
            if should_validate_size:
                try:
                    cls._resolve_lowprice_size(size, custom_size)
                except SeedanceAPIError as error:
                    return str(error)
            if n is not None and not 1 <= int(n) <= 10:
                return "lowprice n must be between 1 and 10 | lowprice n 必须在 1 到 10 之间"
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
            for i in range(1, MAX_ZHENZHEN_IMAGE_G_V2_LOWPRICE_IMAGES + 1)
            if kwargs.get(f"image{i}") is not None
        ]
        connected = [i for i, _ in slots]
        if connected and connected != list(range(1, len(connected) + 1)):
            print(
                f"[{self._log_prefix}] WARNING: Image G slots {connected} have gaps; "
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
        size: str = "1:1",
        custom_size: str = "",
        n: int = 1,
    ) -> Dict[str, Any]:
        validation = self.VALIDATE_INPUTS(
            model=model,
            prompt=prompt,
            resolution=resolution,
            ratio=ratio,
            size=size,
            custom_size=custom_size,
            n=n,
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        if model == ZHENZHEN_IMAGE_G2_I2I_MODEL:
            if not images:
                raise SeedanceAPIError(
                    "at least one image is required for zhenzhen-image-g2-i2i | "
                    "zhenzhen-image-g2-i2i 至少需要 1 张参考图"
                )
            if len(images) > MAX_ZHENZHEN_IMAGE_G2_IMAGES:
                raise SeedanceAPIError(
                    f"zhenzhen-image-g2-i2i supports at most {MAX_ZHENZHEN_IMAGE_G2_IMAGES} images"
                )

        if (
            model == ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL
            and len(images) > MAX_ZHENZHEN_IMAGE_G_V2_LOWPRICE_IMAGES
        ):
            raise SeedanceAPIError(
                f"zhenzhen-image-g-v2-lowprice supports at most "
                f"{MAX_ZHENZHEN_IMAGE_G_V2_LOWPRICE_IMAGES} images"
            )

        if model == ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL:
            payload: Dict[str, Any] = {
                "model": model,
                "prompt": prompt,
                "n": int(n),
                "size": self._resolve_lowprice_size(size, custom_size),
                "metadata": {"resolution": resolution},
            }
            if images:
                payload["images"] = images
            return payload

        metadata: Dict[str, Any] = {"resolution": resolution}
        ratio_text = str(ratio or "").strip()
        if ratio_text and ratio_text != "adaptive":
            metadata["ratio"] = ratio_text

        payload = {
            "model": model,
            "prompt": prompt,
            "metadata": metadata,
        }
        if model == ZHENZHEN_IMAGE_G2_I2I_MODEL:
            payload["images"] = images
        return payload

    def execute(
        self,
        model: str,
        prompt: str,
        resolution: str,
        ratio: str,
        size: str = "1:1",
        custom_size: str = "",
        n: int = 1,
        api_config=None,
        **kwargs,
    ):
        prompt_text = str(prompt or "").strip()
        validation = self.VALIDATE_INPUTS(
            model=model,
            prompt=prompt_text,
            resolution=resolution,
            ratio=ratio,
            size=size,
            custom_size=custom_size,
            n=n,
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        config = get_config(api_config)
        pbar = _make_progress_bar(100)
        self._update_progress(pbar, 0)

        image_urls: List[str] = []
        if model in (ZHENZHEN_IMAGE_G2_I2I_MODEL, ZHENZHEN_IMAGE_G_V2_LOWPRICE_MODEL):
            references = self._connected_images(kwargs)
            if model == ZHENZHEN_IMAGE_G2_I2I_MODEL:
                if not references:
                    raise SeedanceAPIError(
                        "at least one image is required for zhenzhen-image-g2-i2i | "
                        "zhenzhen-image-g2-i2i 至少需要 1 张参考图"
                    )
                if len(references) > MAX_ZHENZHEN_IMAGE_G2_IMAGES:
                    raise SeedanceAPIError(
                        f"zhenzhen-image-g2-i2i supports at most "
                        f"{MAX_ZHENZHEN_IMAGE_G2_IMAGES} images"
                    )
            for done, (slot, tensor) in enumerate(references, start=1):
                image_url = upload_media(
                    image_to_png_bytes(tensor),
                    f"zhenzhen_image_g_reference_{slot}.png",
                    "image/png",
                    config,
                    logger_prefix=self._log_prefix,
                )
                image_urls.append(image_url)
                self._update_progress(pbar, done / len(references) * 15)
        self._update_progress(pbar, 15)

        payload = self._build_payload(
            model,
            prompt_text,
            resolution,
            ratio,
            image_urls,
            size=size,
            custom_size=custom_size,
            n=n,
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
# Qwen Image 3.0 image generation and editing
# ---------------------------------------------------------------------------

class QwenImage30:
    """Qwen Image 3.0/3.0 Pro domestic and global generation/editing."""

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
                    f"Qwen I2I reference image {i} of {MAX_QWEN_IMAGE_30_IMAGES}; "
                    "ignored by T2I. | Qwen 图像编辑参考图；文生图不使用。"
                ),
            })
            for i in range(1, MAX_QWEN_IMAGE_30_IMAGES + 1)
        }
        optional["api_config"] = ("SEEDANCE_CONFIG", {
            "tooltip": "Connect Seedance API Config; otherwise SEEDANCE_API_KEY is used.",
        })
        return {
            "required": {
                "model": (QWEN_IMAGE_30_MODELS, {
                    "default": QWEN_IMAGE_30_T2I_MODEL,
                    "tooltip": (
                        "Qwen Image 3.0 or Pro, domestic or global, for T2I/I2I. | "
                        "Qwen Image 3.0 / Pro 国内或海外文生图、图像编辑。"
                    ),
                }),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Prompt, 5 to 2000 characters. | 提示词，5 到 2000 字符。",
                }),
                "negative_prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Optional negative prompt. | 可选负面提示词。",
                }),
                "prompt_extend": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Enable upstream prompt expansion. | 启用上游提示词扩写。",
                }),
                "sizing_mode": (QWEN_IMAGE_30_SIZING_MODES, {
                    "default": "auto",
                    "tooltip": (
                        "auto omits size; ratio sends metadata.ratio and resolution; "
                        "custom_size sends top-level size. | 自动模式省略尺寸；比例模式发送"
                        "画幅和分辨率；自定义模式发送顶层 size。"
                    ),
                }),
                "resolution": (QWEN_IMAGE_30_RESOLUTIONS, {
                    "default": "1k",
                    "tooltip": "Used only in ratio mode: 1k or 2k. | 仅比例模式使用：1k 或 2k。",
                }),
                "ratio": (QWEN_IMAGE_30_RATIOS, {
                    "default": "1:1",
                    "tooltip": "Used only in ratio mode. | 仅比例模式使用。",
                }),
                "custom_size": ("STRING", {
                    "default": "1024*1024",
                    "tooltip": (
                        "Used only in custom_size mode, for example 1024*1024. | "
                        "仅自定义模式使用，例如 1024*1024。"
                    ),
                }),
                "n": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 6,
                    "step": 1,
                    "tooltip": "Number of images requested, 1 to 6. | 请求图片数量，1 到 6。",
                }),
                "seed": ("INT", {
                    "default": -1,
                    "min": -1,
                    "max": 2147483647,
                    "step": 1,
                    "control_after_generate": True,
                    "tooltip": "-1 omits metadata.seed; non-negative values are forwarded. | -1 不发送 seed。",
                }),
            },
            "optional": optional,
        }

    @staticmethod
    def _normalize_custom_size(value: Any) -> str:
        return str(value or "").strip().replace("X", "*").replace("x", "*")

    @classmethod
    def _valid_custom_size(cls, value: Any) -> bool:
        parts = [part.strip() for part in cls._normalize_custom_size(value).split("*")]
        return len(parts) == 2 and all(part.isdigit() and int(part) > 0 for part in parts)

    @classmethod
    def VALIDATE_INPUTS(
        cls,
        model=None,
        prompt=None,
        sizing_mode=None,
        resolution=None,
        ratio=None,
        custom_size=None,
        n=None,
        seed=None,
        strict=False,
        **kwargs,
    ):
        if model not in (None, *QWEN_IMAGE_30_MODELS):
            return f"unsupported Qwen Image 3.0 model: {model}"
        prompt_text = str(prompt or "").strip()
        if strict and not prompt_text:
            return "prompt is required for Qwen Image 3.0 | Qwen Image 3.0 必须填写提示词"
        if prompt_text and not (
            QWEN_IMAGE_30_PROMPT_MIN_LENGTH
            <= len(prompt_text)
            <= QWEN_IMAGE_30_PROMPT_MAX_LENGTH
        ):
            return "Qwen Image 3.0 prompt must contain 5 to 2000 characters | 提示词必须包含 5 到 2000 个字符"
        if sizing_mode is not None and sizing_mode not in QWEN_IMAGE_30_SIZING_MODES:
            return f"unsupported Qwen Image 3.0 sizing_mode: {sizing_mode}"
        if resolution is not None and resolution not in QWEN_IMAGE_30_RESOLUTIONS:
            return "Qwen Image 3.0 resolution must be 1k or 2k | 分辨率必须为 1k 或 2k"
        if ratio is not None and ratio not in QWEN_IMAGE_30_RATIOS:
            return f"unsupported Qwen Image 3.0 ratio: {ratio}"
        if strict and sizing_mode == "custom_size" and not cls._valid_custom_size(custom_size):
            return "Qwen Image 3.0 custom_size must use positive WxH, for example 1024*1024 | 自定义尺寸必须为正数 WxH"
        if n is not None and not 1 <= int(n) <= 6:
            return "Qwen Image 3.0 n must be between 1 and 6 | n 必须在 1 到 6 之间"
        if seed is not None and int(seed) < -1:
            return "Qwen Image 3.0 seed must be -1 or non-negative | seed 必须为 -1 或非负数"
        connected = sum(
            kwargs.get(f"image{i}") is not None
            for i in range(1, MAX_QWEN_IMAGE_30_IMAGES + 1)
        )
        if strict and model in QWEN_IMAGE_30_I2I_MODELS and connected == 0:
            return "Qwen Image 3.0 I2I requires 1 to 3 images | Qwen 图像编辑需要 1 到 3 张参考图"
        return True

    @property
    def _log_prefix(self) -> str:
        return "Qwen_image_3_0"

    def _update_progress(self, pbar, value: float):
        if pbar is not None:
            try:
                pbar.update_absolute(int(value), 100)
            except Exception:
                pass

    def _connected_images(self, kwargs: Dict[str, Any]) -> List[Tuple[int, Any]]:
        return [
            (i, kwargs.get(f"image{i}"))
            for i in range(1, MAX_QWEN_IMAGE_30_IMAGES + 1)
            if kwargs.get(f"image{i}") is not None
        ]

    def _build_payload(
        self,
        model: str,
        prompt: str,
        negative_prompt: str,
        prompt_extend: bool,
        sizing_mode: str,
        resolution: str,
        ratio: str,
        custom_size: str,
        n: int,
        seed: int,
        images: List[str],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": int(n),
            "prompt_extend": bool(prompt_extend),
        }
        negative_text = str(negative_prompt or "").strip()
        if negative_text:
            payload["negative_prompt"] = negative_text

        metadata: Dict[str, Any] = {}
        if int(seed) >= 0:
            metadata["seed"] = int(seed)
        if sizing_mode == "ratio":
            metadata["ratio"] = ratio
            metadata["resolution"] = resolution
        elif sizing_mode == "custom_size":
            payload["size"] = self._normalize_custom_size(custom_size)
        if metadata:
            payload["metadata"] = metadata

        if model in QWEN_IMAGE_30_I2I_MODELS:
            if not 1 <= len(images) <= MAX_QWEN_IMAGE_30_IMAGES:
                raise SeedanceAPIError(
                    "Qwen Image 3.0 I2I requires 1 to 3 images | "
                    "Qwen 图像编辑需要 1 到 3 张参考图"
                )
            payload["images"] = images
        return payload

    def execute(
        self,
        model: str,
        prompt: str,
        negative_prompt: str,
        prompt_extend: bool,
        sizing_mode: str,
        resolution: str,
        ratio: str,
        custom_size: str,
        n: int,
        seed: int,
        api_config=None,
        **kwargs,
    ):
        prompt_text = str(prompt or "").strip()
        validation = self.VALIDATE_INPUTS(
            model=model,
            prompt=prompt_text,
            sizing_mode=sizing_mode,
            resolution=resolution,
            ratio=ratio,
            custom_size=custom_size,
            n=n,
            seed=seed,
            strict=True,
            **kwargs,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        config = get_config(api_config)
        pbar = _make_progress_bar(100)
        self._update_progress(pbar, 0)
        image_urls: List[str] = []
        if model in QWEN_IMAGE_30_I2I_MODELS:
            references = self._connected_images(kwargs)
            for done, (slot, tensor) in enumerate(references, start=1):
                image_urls.append(upload_media(
                    image_to_png_bytes(tensor),
                    f"qwen_image_3_reference_{slot}.png",
                    "image/png",
                    config,
                    logger_prefix=self._log_prefix,
                ))
                self._update_progress(pbar, done / len(references) * 15)
        self._update_progress(pbar, 15)

        payload = self._build_payload(
            model,
            prompt_text,
            negative_prompt,
            prompt_extend,
            sizing_mode,
            resolution,
            ratio,
            custom_size,
            n,
            seed,
            image_urls,
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
# Zhenzhen Image GK v1.5 image generation and editing
# ---------------------------------------------------------------------------

class ZhenzhenImageGKV15:
    """Zhenzhen Image GK v1.5 text-to-image and image editing."""

    CATEGORY = "Seedance"
    FUNCTION = "execute"
    OUTPUT_NODE = True
    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("image", "image_url", "task_id", "response")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": (ZHENZHEN_IMAGE_GK_V15_MODELS, {
                    "default": ZHENZHEN_IMAGE_GK_V15_MODEL,
                    "tooltip": (
                        "zhenzhen-image-gk-v15 for text-to-image; "
                        "zhenzhen-image-gk-v15-edit requires image1. | "
                        "文生图使用 gk-v15；图像编辑使用 gk-v15-edit 并连接 image1。"
                    ),
                }),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Prompt, up to 20000 characters. | 提示词，最多 20000 字符。",
                }),
                "size": (ZHENZHEN_IMAGE_GK_V15_SIZES, {
                    "default": "1:1",
                    "tooltip": "Top-level API size. | 顶层 size 参数。",
                }),
                "n": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 10,
                    "step": 1,
                    "tooltip": "Number of images requested from the API, 1 to 10. This node downloads the primary result returned by the gateway. | 请求图片数量 1 到 10，节点下载网关返回的主结果。",
                }),
            },
            "optional": {
                "image1": ("IMAGE", {
                    "tooltip": "Required for zhenzhen-image-gk-v15-edit; only the first image is submitted. | gk-v15-edit 必填，仅提交第一张图。",
                }),
                "api_config": ("SEEDANCE_CONFIG", {
                    "tooltip": "Connect Seedance API Config; otherwise SEEDANCE_API_KEY is used.",
                }),
            },
        }

    @classmethod
    def VALIDATE_INPUTS(
        cls,
        model=None,
        prompt=None,
        size=None,
        n=None,
        image1=None,
        strict=False,
        **kwargs,
    ):
        if model not in (None, *ZHENZHEN_IMAGE_GK_V15_MODELS):
            return f"unsupported Zhenzhen Image GK model: {model}"
        prompt_text = str(prompt or "").strip()
        if strict and not prompt_text:
            return "prompt is required for Zhenzhen Image GK | Zhenzhen Image GK 必须填写提示词"
        if prompt_text and len(prompt_text) > ZHENZHEN_IMAGE_GK_V15_PROMPT_MAX_LENGTH:
            return (
                f"prompt exceeds {ZHENZHEN_IMAGE_GK_V15_PROMPT_MAX_LENGTH} characters "
                f"({len(prompt_text)}) | 提示词不能超过 {ZHENZHEN_IMAGE_GK_V15_PROMPT_MAX_LENGTH} 字符"
            )
        if size is not None and size not in ZHENZHEN_IMAGE_GK_V15_SIZES:
            return f"unsupported size: {size}"
        if n is not None:
            n_int = int(n)
            if not 1 <= n_int <= 10:
                return "n must be between 1 and 10 | n 必须在 1 到 10 之间"
        if strict and model == ZHENZHEN_IMAGE_GK_V15_EDIT_MODEL and image1 is None:
            return "image1 is required for zhenzhen-image-gk-v15-edit | gk-v15-edit 必须连接 image1"
        return True

    @property
    def _log_prefix(self) -> str:
        return "Zhenzhen_image_gk_v15"

    def _update_progress(self, pbar, value: float):
        if pbar is not None:
            try:
                pbar.update_absolute(int(value), 100)
            except Exception:
                pass

    def _build_payload(
        self,
        model: str,
        prompt: str,
        size: str,
        n: int,
        images: List[str],
    ) -> Dict[str, Any]:
        validation = self.VALIDATE_INPUTS(
            model=model,
            prompt=prompt,
            size=size,
            n=n,
            image1=images[0] if images else None,
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": int(n),
            "size": size,
        }
        if model == ZHENZHEN_IMAGE_GK_V15_EDIT_MODEL:
            payload["images"] = images[:1]
        return payload

    def execute(
        self,
        model: str,
        prompt: str,
        size: str,
        n: int,
        image1=None,
        api_config=None,
    ):
        prompt_text = str(prompt or "").strip()
        validation = self.VALIDATE_INPUTS(
            model=model,
            prompt=prompt_text,
            size=size,
            n=n,
            image1=image1,
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        config = get_config(api_config)
        pbar = _make_progress_bar(100)
        self._update_progress(pbar, 0)

        image_urls: List[str] = []
        if model == ZHENZHEN_IMAGE_GK_V15_EDIT_MODEL:
            image_url = upload_media(
                image_to_png_bytes(image1),
                "zhenzhen_image_gk_v15_reference.png",
                "image/png",
                config,
                logger_prefix=self._log_prefix,
            )
            image_urls.append(image_url)
        self._update_progress(pbar, 15)

        payload = self._build_payload(model, prompt_text, size, n, image_urls)
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
# Zhenzhen Image Nano Banana generation and editing
# ---------------------------------------------------------------------------

class ZhenzhenImageNB:
    """Zhenzhen Nano Banana text-to-image and image editing."""

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
                    f"Optional reference image {i} of {MAX_ZHENZHEN_IMAGE_NB_IMAGES}; "
                    "connected images are uploaded and submitted in slot order. | "
                    f"可选参考图 {i}/{MAX_ZHENZHEN_IMAGE_NB_IMAGES}，按槽位顺序上传提交。"
                ),
            })
            for i in range(1, MAX_ZHENZHEN_IMAGE_NB_IMAGES + 1)
        }
        optional["api_config"] = ("SEEDANCE_CONFIG", {
            "tooltip": "Connect Seedance API Config; otherwise SEEDANCE_API_KEY is used.",
        })

        return {
            "required": {
                "model": (ZHENZHEN_IMAGE_NB_MODELS, {
                    "default": ZHENZHEN_IMAGE_NB_FLASH_MODEL,
                    "tooltip": (
                        "Nano Banana model. Every model supports text-to-image and optional "
                        "reference-image editing. | Nano Banana 模型，均支持文生图和可选参考图编辑。"
                    ),
                }),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": (
                        "Required prompt. zhenzhen-image-nb-flash supports up to 1000 characters. | "
                        "必填提示词；zhenzhen-image-nb-flash 最多 1000 字符。"
                    ),
                }),
                "resolution": (ZHENZHEN_IMAGE_NB_RESOLUTIONS, {
                    "default": "1k",
                    "tooltip": "Model-specific output resolution. | 按模型限制的输出分辨率。",
                }),
                "size": (ZHENZHEN_IMAGE_NB_SIZES, {
                    "default": "1:1",
                    "tooltip": "Model-specific aspect ratio. | 按模型限制的画幅比例。",
                }),
                "n": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 4,
                    "step": 1,
                    "tooltip": (
                        "Requested image count. Only nb-2-lite supports 1 to 4; other models require 1. "
                        "The node downloads the primary gateway result. | 请求图片数量；仅 nb-2-lite "
                        "支持 1 到 4，其他模型固定为 1。节点下载网关返回的主结果。"
                    ),
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
        size=None,
        n=None,
        strict=False,
        **kwargs,
    ):
        if model not in (None, *ZHENZHEN_IMAGE_NB_MODELS):
            return f"unsupported Zhenzhen Image NB model: {model}"

        prompt_text = str(prompt or "").strip()
        if strict and not prompt_text:
            return "prompt is required for Zhenzhen Image NB | Zhenzhen Image NB 必须填写提示词"
        if (
            model == ZHENZHEN_IMAGE_NB_FLASH_MODEL
            and len(prompt_text) > ZHENZHEN_IMAGE_NB_FLASH_PROMPT_MAX_LENGTH
        ):
            return (
                f"zhenzhen-image-nb-flash prompt exceeds "
                f"{ZHENZHEN_IMAGE_NB_FLASH_PROMPT_MAX_LENGTH} characters "
                f"({len(prompt_text)}) | nb-flash 提示词不能超过 "
                f"{ZHENZHEN_IMAGE_NB_FLASH_PROMPT_MAX_LENGTH} 字符"
            )

        if model in ZHENZHEN_IMAGE_NB_MODEL_RESOLUTIONS:
            allowed_resolutions = ZHENZHEN_IMAGE_NB_MODEL_RESOLUTIONS[model]
            if resolution is not None and resolution not in allowed_resolutions:
                return (
                    f"{model} resolution must be one of {', '.join(allowed_resolutions)} | "
                    "当前模型不支持所选分辨率"
                )

        if model in ZHENZHEN_IMAGE_NB_MODEL_SIZES:
            allowed_sizes = ZHENZHEN_IMAGE_NB_MODEL_SIZES[model]
            if size is not None and size not in allowed_sizes:
                return (
                    f"{model} size must be one of {', '.join(allowed_sizes)} | "
                    "当前模型不支持所选画幅比例"
                )

        if n is not None and model in ZHENZHEN_IMAGE_NB_MODEL_N_RANGE:
            try:
                n_value = int(n)
            except (TypeError, ValueError):
                return "n must be an integer | n 必须是整数"
            minimum, maximum = ZHENZHEN_IMAGE_NB_MODEL_N_RANGE[model]
            if not minimum <= n_value <= maximum:
                return (
                    f"{model} n must be between {minimum} and {maximum} | "
                    "当前模型不支持所选图片数量"
                )
        return True

    @property
    def _log_prefix(self) -> str:
        return "Zhenzhen_image_nb"

    def _update_progress(self, pbar, value: float):
        if pbar is not None:
            try:
                pbar.update_absolute(int(value), 100)
            except Exception:
                pass

    def _connected_images(self, kwargs: Dict[str, Any]) -> List[Tuple[int, Any]]:
        slots = [
            (i, kwargs.get(f"image{i}"))
            for i in range(1, MAX_ZHENZHEN_IMAGE_NB_IMAGES + 1)
            if kwargs.get(f"image{i}") is not None
        ]
        connected = [i for i, _ in slots]
        if connected and connected != list(range(1, len(connected) + 1)):
            print(
                f"[{self._log_prefix}] WARNING: NB image slots {connected} have gaps; "
                f"they will be compacted to images order 1..{len(connected)}."
            )
        return slots

    def _build_payload(
        self,
        model: str,
        prompt: str,
        resolution: str,
        size: str,
        n: int,
        images: List[str],
    ) -> Dict[str, Any]:
        validation = self.VALIDATE_INPUTS(
            model=model,
            prompt=prompt,
            resolution=resolution,
            size=size,
            n=n,
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": int(n),
            "size": size,
            "metadata": {"resolution": resolution},
        }
        if images:
            payload["images"] = images[:MAX_ZHENZHEN_IMAGE_NB_IMAGES]
        return payload

    def execute(
        self,
        model: str,
        prompt: str,
        resolution: str,
        size: str,
        n: int,
        api_config=None,
        **kwargs,
    ):
        prompt_text = str(prompt or "").strip()
        validation = self.VALIDATE_INPUTS(
            model=model,
            prompt=prompt_text,
            resolution=resolution,
            size=size,
            n=n,
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        config = get_config(api_config)
        pbar = _make_progress_bar(100)
        self._update_progress(pbar, 0)

        references = self._connected_images(kwargs)
        image_urls: List[str] = []
        for done, (slot, tensor) in enumerate(references, start=1):
            image_url = upload_media(
                image_to_png_bytes(tensor),
                f"zhenzhen_image_nb_reference_{slot}.png",
                "image/png",
                config,
                logger_prefix=self._log_prefix,
            )
            image_urls.append(image_url)
            self._update_progress(pbar, done / len(references) * 15)
        self._update_progress(pbar, 15)

        payload = self._build_payload(model, prompt_text, resolution, size, n, image_urls)
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
        pbar = _make_progress_bar(100)
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
# Whisper transcription
# ---------------------------------------------------------------------------

class WhisperTranscription:
    """Synchronous whisper-1 speech transcription via /v1/audio/transcriptions."""

    CATEGORY = "Seedance"
    FUNCTION = "execute"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("text", "response")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO", {
                    "tooltip": "Input audio to transcribe; converted to wav before upload. | 需要转写的音频，会先转换为 wav 再上传。",
                }),
                "model": ([WHISPER_TRANSCRIPTION_MODEL], {
                    "default": WHISPER_TRANSCRIPTION_MODEL,
                    "tooltip": "Whisper transcription model. | Whisper 语音转写模型。",
                }),
                "response_format": (WHISPER_RESPONSE_FORMATS, {
                    "default": "json",
                    "tooltip": "API response format: json, verbose_json, srt, text, or vtt. | API 返回格式。",
                }),
            },
            "optional": {
                "api_config": ("SEEDANCE_CONFIG", {
                    "tooltip": "Connect Seedance API Config; otherwise SEEDANCE_API_KEY is used.",
                }),
                "skip_error": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "On failure return an empty transcript and JSON error instead of stopping the workflow. | 失败时返回空文本和错误 JSON。",
                }),
            },
        }

    @classmethod
    def VALIDATE_INPUTS(
        cls,
        audio=None,
        model=None,
        response_format=None,
        strict=False,
        **kwargs,
    ):
        if model not in (None, WHISPER_TRANSCRIPTION_MODEL):
            return f"unsupported Whisper model: {model}"
        if response_format not in (None, *WHISPER_RESPONSE_FORMATS):
            return f"unsupported response_format: {response_format}"
        if strict and audio is None:
            return "audio is required for Whisper transcription | Whisper 转写必须连接音频"
        return True

    @property
    def _log_prefix(self) -> str:
        return "Whisper_transcription"

    def _update_progress(self, pbar, value: float):
        if pbar is not None:
            try:
                pbar.update_absolute(int(value), 100)
            except Exception:
                pass

    def _make_error_result(self, error_msg: str) -> Dict:
        response_str = json.dumps({"error": error_msg}, ensure_ascii=False, indent=2)
        return {
            "ui": {"text": ["", response_str]},
            "result": ("", response_str),
        }

    def execute(
        self,
        audio,
        model: str,
        response_format: str,
        api_config=None,
        skip_error: bool = False,
    ):
        try:
            return self._execute_inner(
                audio=audio,
                model=model,
                response_format=response_format,
                api_config=api_config,
            )
        except Exception as e:
            if skip_error:
                err_msg = f"{self._log_prefix}: {e}"
                print(f"[{self._log_prefix}] skip_error=True, returning empty transcript: {e}")
                return self._make_error_result(err_msg)
            raise

    def _execute_inner(
        self,
        audio,
        model: str,
        response_format: str,
        api_config=None,
    ):
        validation = self.VALIDATE_INPUTS(
            audio=audio,
            model=model,
            response_format=response_format,
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        config = get_config(api_config)
        pbar = _make_progress_bar(100)
        self._update_progress(pbar, 0)

        wav_bytes = audio_to_wav_bytes(audio)
        self._update_progress(pbar, 20)

        text, response_str = transcribe_audio(
            wav_bytes,
            "whisper_input.wav",
            "audio/wav",
            model,
            response_format,
            config,
            logger_prefix=self._log_prefix,
        )
        self._update_progress(pbar, 100)

        return {
            "ui": {"text": [text, response_str]},
            "result": (text, response_str),
        }


# ---------------------------------------------------------------------------
# Suno music generation and processing
# ---------------------------------------------------------------------------

class SunoMusic:
    """All documented Suno music actions through the dedicated /v1/music API."""

    CATEGORY = "Seedance"
    FUNCTION = "execute"
    OUTPUT_NODE = True
    RETURN_TYPES = (
        "AUDIO",
        "AUDIO",
        "VIDEO",
        "STRING",
        "STRING",
        "STRING",
        "STRING",
        "STRING",
        "STRING",
        "STRING",
    )
    RETURN_NAMES = (
        "audio1",
        "audio2",
        "video",
        "text",
        "primary_url",
        "result_urls",
        "primary_path",
        "result_paths",
        "task_id",
        "response",
    )

    @classmethod
    def INPUT_TYPES(cls):
        optional: Dict[str, tuple] = {}
        for i in range(1, MAX_SUNO_REFERENCE_AUDIOS + 1):
            optional[f"audio{i}"] = (
                "AUDIO",
                {
                    "tooltip": (
                        f"Local audio reference {i}; used by upload, create-voice, "
                        f"or inspo. Upload sources require at least 6 seconds. | "
                        f"本地音频素材 {i}；导入源音频至少需要 6 秒。"
                    )
                },
            )
            optional[f"audio_url{i}"] = (
                "STRING",
                {
                    "default": "",
                    "tooltip": (
                        f"Public audio URL {i}; do not fill together with audio{i}. | "
                        f"公网音频 URL {i}，不能与同槽本地音频同时使用。"
                    ),
                },
            )
        optional["api_config"] = (
            "SEEDANCE_CONFIG",
            {
                "tooltip": (
                    "Connect Seedance API Config; otherwise SEEDANCE_API_KEY is used."
                )
            },
        )
        optional["skip_error"] = (
            "BOOLEAN",
            {
                "default": False,
                "tooltip": (
                    "Return placeholders and an error response instead of stopping. | "
                    "失败时返回占位结果和错误信息，不中断批处理。"
                ),
            },
        )

        return {
            "required": {
                "operation": (
                    SUNO_OPERATIONS,
                    {
                        "default": "suno-generation",
                        "tooltip": "Select one documented Suno action. | 选择 Suno 操作。",
                    },
                ),
                "prompt": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": (
                            "Prompt, lyrics, or edit instruction for the selected action. | "
                            "当前操作使用的提示词、歌词或编辑说明。"
                        ),
                    },
                ),
                "version": (
                    SUNO_VERSIONS,
                    {
                        "default": "v5.5",
                        "tooltip": (
                            "Sent only when the selected action supports this version. | "
                            "仅在当前操作支持时发送。"
                        ),
                    },
                ),
                "custom": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": "Generation custom-lyrics mode. | 自定义歌词模式。",
                    },
                ),
                "instrumental": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": "Generation without vocals. | 生成纯伴奏。",
                    },
                ),
                "title": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Optional generation title. | 可选曲名。",
                    },
                ),
                "style": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Optional generation style. | 可选音乐风格。",
                    },
                ),
                "vocal_gender": (
                    ["unspecified", "Male", "Female"],
                    {
                        "default": "unspecified",
                        "tooltip": "Optional generation vocal preference. | 可选人声偏好。",
                    },
                ),
                "tags": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": "Style tags for upsample-tags. | 需要扩写的风格标签。",
                    },
                ),
                "name": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Persona name. | Persona 名称。",
                    },
                ),
                "task_id": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": (
                            "Source Suno task id; connect a previous Suno node. | "
                            "源任务 ID，可连接前一个 Suno 节点。"
                        ),
                    },
                ),
                "task_id_2": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Second source task id for mashup. | 混合作品的第二个任务 ID。",
                    },
                ),
                "audio_index": (
                    "INT",
                    {
                        "default": 1,
                        "min": 1,
                        "max": 2147483647,
                        "step": 1,
                        "tooltip": "1-based source track index. | 从 1 开始的音轨序号。",
                    },
                ),
                "continue_at": (
                    "FLOAT",
                    {
                        "default": 30.0,
                        "step": 0.1,
                        "tooltip": "Extend from this second. | 从该秒数开始续写。",
                    },
                ),
                "start_s": (
                    "FLOAT",
                    {
                        "default": 0.0,
                        "step": 0.1,
                        "tooltip": "Start second for range actions. | 时间范围起点。",
                    },
                ),
                "end_s": (
                    "FLOAT",
                    {
                        "default": 30.0,
                        "step": 0.1,
                        "tooltip": "End second for range actions. | 时间范围终点。",
                    },
                ),
                "duration_s": (
                    "FLOAT",
                    {
                        "default": 5.0,
                        "step": 0.1,
                        "tooltip": "Fade duration in seconds. | 淡入或淡出时长。",
                    },
                ),
                "speed": (
                    "FLOAT",
                    {
                        "default": 1.0,
                        "step": 0.05,
                        "tooltip": "Speed multiplier for adjust-speed. | 速度倍率。",
                    },
                ),
            },
            "optional": optional,
        }

    @classmethod
    def VALIDATE_INPUTS(
        cls,
        operation=None,
        version=None,
        audio_index=None,
        strict=False,
        **kwargs,
    ):
        if operation not in SUNO_ACTION_SPECS:
            return f"unsupported Suno operation: {operation}"

        spec = SUNO_ACTION_SPECS[operation]
        allowed_versions = spec["allowed_versions"]
        if allowed_versions and version not in allowed_versions:
            return (
                f"{operation} does not support version '{version}'; "
                f"allowed: {', '.join(allowed_versions)}"
            )
        if audio_index is not None and int(audio_index) < 1:
            return "audio_index must be at least 1"
        return True

    @property
    def _log_prefix(self) -> str:
        return "Suno_Music"

    def _update_progress(self, pbar, value: float):
        if pbar is not None:
            try:
                pbar.update_absolute(int(value), 100)
            except Exception:
                pass

    @staticmethod
    def _text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _audio_duration_seconds(audio: Any) -> Optional[float]:
        if not isinstance(audio, dict):
            return None
        waveform = audio.get("waveform")
        sample_rate = int(audio.get("sample_rate") or 0)
        shape = getattr(waveform, "shape", None)
        if not shape or sample_rate <= 0:
            return None
        try:
            return float(shape[-1]) / float(sample_rate)
        except (TypeError, ValueError, IndexError):
            return None

    def _collect_audio_inputs(
        self,
        operation: str,
        kwargs: Dict[str, Any],
        config: Dict[str, Any],
        progress_cb,
    ) -> List[str]:
        if operation not in {"suno-upload", "suno-create-voice", "suno-inspo"}:
            return []

        slots: List[Tuple[int, Any, str]] = []
        for i in range(1, MAX_SUNO_REFERENCE_AUDIOS + 1):
            audio = kwargs.get(f"audio{i}")
            url = self._text(kwargs.get(f"audio_url{i}"))
            if audio is not None and url:
                raise SeedanceAPIError(
                    f"audio{i} and audio_url{i} cannot both be used | "
                    f"第 {i} 槽不能同时连接本地音频和填写 URL"
                )
            if url and not url.startswith(("http://", "https://")):
                raise SeedanceAPIError(
                    f"audio_url{i} must be an http(s) URL | "
                    f"audio_url{i} 必须是 http(s) URL"
                )
            if audio is not None or url:
                slots.append((i, audio, url))

        if operation in {"suno-upload", "suno-create-voice"}:
            if any(i != 1 for i, _audio, _url in slots):
                raise SeedanceAPIError(
                    f"{operation} only accepts audio slot 1 | "
                    f"{operation} 只接受第 1 个音频槽"
                )
            if len(slots) != 1:
                raise SeedanceAPIError(
                    f"{operation} requires exactly one local audio or URL | "
                    f"{operation} 必须提供一个本地音频或 URL"
                )
        elif not 1 <= len(slots) <= MAX_SUNO_REFERENCE_AUDIOS:
            raise SeedanceAPIError(
                "suno-inspo requires 1-4 local audios or URLs | "
                "suno-inspo 必须提供 1-4 个本地音频或 URL"
            )

        resolved: List[str] = []
        total_uploads = sum(1 for _i, audio, _url in slots if audio is not None)
        uploaded = 0
        for i, audio, url in slots:
            if audio is not None:
                duration = self._audio_duration_seconds(audio)
                if (
                    operation == "suno-upload"
                    and duration is not None
                    and duration < SUNO_UPLOAD_MIN_SECONDS
                ):
                    raise SeedanceAPIError(
                        "suno-upload local audio must be at least 6 seconds | "
                        "suno-upload 本地音频至少需要 6 秒"
                    )
                url = upload_media(
                    audio_to_wav_bytes(audio),
                    f"suno_reference_{i}.wav",
                    "audio/wav",
                    config,
                    logger_prefix=self._log_prefix,
                )
                uploaded += 1
                progress_cb(uploaded / max(total_uploads, 1))
            resolved.append(url)
        if total_uploads == 0:
            progress_cb(1.0)
        return resolved

    def _build_payload(
        self,
        operation: str,
        audio_urls: List[str],
        **kwargs,
    ) -> Dict[str, Any]:
        if operation not in SUNO_ACTION_SPECS:
            raise SeedanceAPIError(f"unsupported Suno operation: {operation}")
        spec = SUNO_ACTION_SPECS[operation]
        allowed_fields = set(spec["allowed_fields"])
        payload: Dict[str, Any] = {"model": "suno"}

        version = self._text(kwargs.get("version"))
        allowed_versions = spec["allowed_versions"]
        if allowed_versions:
            if version not in allowed_versions:
                raise SeedanceAPIError(
                    f"{operation} does not support version '{version}'; "
                    f"allowed: {', '.join(allowed_versions)}"
                )
            payload["version"] = version

        if "prompt" in allowed_fields:
            prompt = self._text(kwargs.get("prompt"))
            if prompt:
                payload["prompt"] = prompt
        if "tags" in allowed_fields:
            tags = self._text(kwargs.get("tags"))
            if tags:
                payload["tags"] = tags
        if "name" in allowed_fields:
            name = self._text(kwargs.get("name"))
            if name:
                payload["name"] = name

        if operation == "suno-generation":
            payload["custom"] = bool(kwargs.get("custom", False))
            payload["instrumental"] = bool(kwargs.get("instrumental", False))
            for field in ("title", "style"):
                value = self._text(kwargs.get(field))
                if value:
                    payload[field] = value
            vocal_gender = self._text(kwargs.get("vocal_gender"))
            if vocal_gender in {"Male", "Female"}:
                payload["vocal_gender"] = vocal_gender

        if spec["reference_type"] == "task_audio":
            task_id = self._text(kwargs.get("task_id"))
            if task_id:
                payload["task_id"] = task_id
            payload["audio_index"] = int(kwargs.get("audio_index") or 1)

        if spec["reference_type"] == "mashup":
            task_ids = [
                self._text(kwargs.get("task_id")),
                self._text(kwargs.get("task_id_2")),
            ]
            if all(task_ids):
                payload["task_ids"] = task_ids

        if operation == "suno-upload" and audio_urls:
            payload["audioFilePath"] = audio_urls[0]
        elif operation == "suno-create-voice" and audio_urls:
            payload["audio_url"] = audio_urls[0]
        elif operation == "suno-inspo" and audio_urls:
            payload["audio_urls"] = audio_urls

        numeric_fields = {
            "continue_at": float,
            "start_s": float,
            "end_s": float,
            "duration_s": float,
            "speed": float,
        }
        for field, converter in numeric_fields.items():
            if field in allowed_fields:
                raw_value = kwargs.get(field)
                if raw_value is not None and raw_value != "":
                    payload[field] = converter(raw_value)

        missing = [
            field
            for field in spec["required_fields"]
            if field not in payload
            or payload[field] is None
            or payload[field] == ""
            or payload[field] == []
        ]
        if missing:
            raise SeedanceAPIError(
                f"{operation} requires: {', '.join(missing)} | "
                f"{operation} 缺少必填参数：{', '.join(missing)}"
            )

        if "task_ids" in payload and len(payload["task_ids"]) != 2:
            raise SeedanceAPIError("suno-mashup requires exactly two task IDs")
        if "audio_urls" in payload and not 1 <= len(payload["audio_urls"]) <= 4:
            raise SeedanceAPIError("suno-inspo requires 1-4 audio URLs")
        if "audio_index" in payload and payload["audio_index"] < 1:
            raise SeedanceAPIError("audio_index must be at least 1")
        if "start_s" in payload and "end_s" in payload:
            if payload["end_s"] <= payload["start_s"]:
                raise SeedanceAPIError("end_s must be greater than start_s")

        return {
            key: value
            for key, value in payload.items()
            if key == "model" or key in allowed_fields
        }

    def _make_error_result(self, error_msg: str) -> Dict[str, Any]:
        response_str = json.dumps({"error": error_msg}, ensure_ascii=False, indent=2)
        silence = make_silent_audio(44100, 1.0)
        error_video = make_error_video(error_msg)
        return {
            "ui": {"text": ["", "", "", response_str]},
            "result": (
                silence,
                silence,
                error_video,
                "",
                "",
                "[]",
                "",
                "[]",
                "",
                response_str,
            ),
        }

    def execute(
        self,
        operation: str,
        prompt: str,
        version: str,
        custom: bool,
        instrumental: bool,
        title: str,
        style: str,
        vocal_gender: str,
        tags: str,
        name: str,
        task_id: str,
        task_id_2: str,
        audio_index: int,
        continue_at: float,
        start_s: float,
        end_s: float,
        duration_s: float,
        speed: float,
        api_config=None,
        skip_error: bool = False,
        **kwargs,
    ):
        all_kwargs = {
            **kwargs,
            "prompt": prompt,
            "version": version,
            "custom": custom,
            "instrumental": instrumental,
            "title": title,
            "style": style,
            "vocal_gender": vocal_gender,
            "tags": tags,
            "name": name,
            "task_id": task_id,
            "task_id_2": task_id_2,
            "audio_index": audio_index,
            "continue_at": continue_at,
            "start_s": start_s,
            "end_s": end_s,
            "duration_s": duration_s,
            "speed": speed,
        }
        try:
            return self._execute_inner(
                operation=operation,
                api_config=api_config,
                **all_kwargs,
            )
        except Exception as e:
            if skip_error:
                error_msg = f"{self._log_prefix}: {e}"
                print(f"[{self._log_prefix}] skip_error=True: {e}")
                return self._make_error_result(error_msg)
            raise

    def _execute_inner(
        self,
        operation: str,
        api_config=None,
        **kwargs,
    ):
        validation = self.VALIDATE_INPUTS(
            operation=operation,
            version=kwargs.get("version"),
            audio_index=kwargs.get("audio_index"),
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        spec = SUNO_ACTION_SPECS[operation]
        config = get_config(api_config)
        pbar = _make_progress_bar(100)
        self._update_progress(pbar, 0)

        audio_urls = self._collect_audio_inputs(
            operation,
            kwargs,
            config,
            lambda fraction: self._update_progress(pbar, fraction * 15),
        )
        self._update_progress(pbar, 15)

        payload = self._build_payload(operation, audio_urls, **kwargs)
        submitted_task_id, submit_response = submit_music_action(
            spec["action"],
            payload,
            config,
            logger_prefix=self._log_prefix,
        )
        self._update_progress(pbar, 20)

        final_response = submit_response
        if submitted_task_id:
            final_response = poll_music_task(
                submitted_task_id,
                config,
                on_progress=lambda progress: self._update_progress(
                    pbar, 20 + progress / 100.0 * 65
                ),
                logger_prefix=self._log_prefix,
            )
        elif not spec["sync"]:
            raise SeedanceAPIError(
                f"{operation} returned no task id in its asynchronous submit response"
            )
        self._update_progress(pbar, 85)

        extracted = extract_music_results(final_response)
        result_task_id = submitted_task_id or extracted["task_id"]
        audio_objects: List[Any] = []
        video = None
        result_paths: List[str] = []
        artifacts = extracted.get("artifacts") or []
        artifact_count = max(1, len(artifacts))

        download_warnings: List[Dict[str, Any]] = []
        successful_downloads = 0

        for index, artifact in enumerate(artifacts, 1):
            url = str(artifact.get("url") or "")
            kind = str(artifact.get("kind") or "file")
            path = ""
            try:
                if kind == "audio":
                    fallback_format = (
                        "wav"
                        if urlparse(url).path.lower().endswith(".wav")
                        else "mp3"
                    )
                    audio, path = download_audio(
                        url,
                        output_format=fallback_format,
                        sample_rate=44100,
                        logger_prefix=self._log_prefix,
                    )
                    audio_objects.append(audio)
                elif kind == "video" and video is None:
                    video, path = download_video_with_path(
                        url, logger_prefix=self._log_prefix
                    )
                else:
                    prefix = {
                        "video": "suno_video",
                        "image": "suno_image",
                        "file": "suno_file",
                    }.get(kind, "suno_file")
                    default_extension = {
                        "video": "mp4",
                        "image": "jpg",
                        "file": "bin",
                    }.get(kind, "bin")
                    path = download_file(
                        url,
                        filename_prefix=prefix,
                        default_extension=default_extension,
                        logger_prefix=self._log_prefix,
                    )
                successful_downloads += 1
            except Exception as error:
                warning = {
                    "artifact_index": index,
                    "kind": kind,
                    "error": type(error).__name__,
                }
                download_warnings.append(warning)
                print(
                    f"[{self._log_prefix}] result artifact "
                    f"{index}/{artifact_count} ({kind}) download failed: "
                    f"{warning['error']}"
                )
            result_paths.append(path)
            self._update_progress(
                pbar,
                85 + min(10, index / artifact_count * 10),
            )

        if artifacts and successful_downloads == 0:
            raise SeedanceAPIError(
                "All music result artifacts failed to download | "
                "音乐结果文件全部下载失败"
            )

        all_urls = [artifact["url"] for artifact in artifacts]
        primary_url = all_urls[0] if all_urls else ""
        primary_path = result_paths[0] if result_paths else ""
        text = extracted["text"]
        if not text and spec["result_family"] == "text":
            text = json.dumps(extracted["result"], ensure_ascii=False, indent=2)
        response_payload = final_response
        if download_warnings:
            response_payload = dict(final_response)
            response_payload["_seedance_local"] = {
                "download_warnings": download_warnings
            }
        response_str = json.dumps(response_payload, ensure_ascii=False, indent=2)
        urls_str = json.dumps(all_urls, ensure_ascii=False)
        paths_str = json.dumps(result_paths, ensure_ascii=False)
        self._update_progress(pbar, 100)

        return {
            "ui": {
                "text": [
                    text,
                    primary_url,
                    primary_path,
                    result_task_id,
                    response_str,
                ]
            },
            "result": (
                audio_objects[0] if audio_objects else None,
                audio_objects[1] if len(audio_objects) > 1 else None,
                video,
                text,
                primary_url,
                urls_str,
                primary_path,
                paths_str,
                result_task_id,
                response_str,
            ),
        }


# ---------------------------------------------------------------------------
# Midjourney image and video actions
# ---------------------------------------------------------------------------

class MidjourneyMultiAction:
    """All documented Midjourney actions through /v1/midjourney."""

    CATEGORY = "Seedance"
    FUNCTION = "execute"
    OUTPUT_NODE = True
    RETURN_TYPES = (
        "IMAGE",
        "IMAGE",
        "IMAGE",
        "IMAGE",
        "IMAGE",
        "VIDEO",
        "VIDEO",
        "VIDEO",
        "VIDEO",
        "STRING",
        "STRING",
        "STRING",
        "STRING",
        "STRING",
        "STRING",
        "STRING",
        "STRING",
    )
    RETURN_NAMES = (
        "image1",
        "image2",
        "image3",
        "image4",
        "grid_image",
        "video1",
        "video2",
        "video3",
        "video4",
        "text",
        "primary_url",
        "result_urls",
        "primary_path",
        "result_paths",
        "task_id",
        "buttons_json",
        "response",
    )

    @classmethod
    def INPUT_TYPES(cls):
        optional: Dict[str, tuple] = {}
        for i in range(1, MAX_MIDJOURNEY_IMAGES + 1):
            optional[f"image{i}"] = (
                "IMAGE",
                {
                    "tooltip": (
                        f"Local image {i}; do not fill image_url{i} together. | "
                        f"本地图片 {i}，不能与同槽 URL 同时使用。"
                    )
                },
            )
        optional["end_image"] = (
            "IMAGE",
            {
                "tooltip": (
                    "Optional local video end frame. | 可选视频结束帧。"
                )
            },
        )
        optional["mask"] = (
            "MASK",
            {
                "tooltip": (
                    "ComfyUI mask for modal region repaint. White is repainted. | "
                    "Modal 局部重绘遮罩，ComfyUI 白色区域会被重绘。"
                )
            },
        )
        optional["api_config"] = (
            "SEEDANCE_CONFIG",
            {
                "tooltip": (
                    "Connect Seedance API Config; otherwise SEEDANCE_API_KEY is used."
                )
            },
        )
        optional["skip_error"] = (
            "BOOLEAN",
            {
                "default": False,
                "tooltip": (
                    "Return placeholders and an error response instead of stopping. | "
                    "失败时返回占位结果和错误信息。"
                ),
            },
        )
        required: Dict[str, tuple] = {
            "operation": (
                MIDJOURNEY_OPERATION_CHOICES,
                {
                    "default": MIDJOURNEY_OPERATION_LABELS["midjourney-imagine"],
                    "tooltip": (
                        "Select a documented Midjourney action; the suffix explains its use. | "
                        "选择 Midjourney 操作，后缀标明用途。"
                    ),
                },
            ),
            "prompt": (
                "STRING",
                {
                    "multiline": True,
                    "default": "",
                    "tooltip": (
                        "Prompt or edit instruction. External STRING inputs are supported. | "
                        "提示词或编辑指令，支持外部 STRING 节点。"
                    ),
                },
            ),
            "speed": (
                MIDJOURNEY_SPEEDS,
                {
                    "default": "relax",
                    "tooltip": "Action speed; relax is the documented default. | 速度模式，默认 relax。",
                },
            ),
            "size": (
                MIDJOURNEY_SIZES,
                {
                    "default": "1:1",
                    "tooltip": (
                        "Common aspect ratios; choose custom to enter another w:h ratio. | "
                        "常用画面比例，选择 custom 可手填其他 w:h 比例。"
                    ),
                },
            ),
            "custom_size": (
                "STRING",
                {
                    "default": "",
                    "tooltip": (
                        "Used only when size is custom; enter a positive w:h ratio. | "
                        "仅 size 选择 custom 时使用，请填写正整数比例 w:h。"
                    ),
                },
            ),
            "dimensions": (
                MIDJOURNEY_DIMENSIONS,
                {
                    "default": "SQUARE",
                    "tooltip": "Blend preset ratio; size takes priority. | Blend 预设比例。",
                },
            ),
            "quality": (
                MIDJOURNEY_QUALITIES,
                {
                    "default": "1",
                    "tooltip": "Imagine/Edits quality; default 1. | Imagine/Edits 质量，默认 1。",
                },
            ),
            "style": (
                "STRING",
                {"default": "", "tooltip": "Optional style, for example raw. | 可选风格。"},
            ),
            "version": (
                MIDJOURNEY_VERSIONS,
                {
                    "default": "8.2",
                    "tooltip": "Midjourney version; default 8.2. | Midjourney 版本，默认 8.2。",
                },
            ),
            "seed": (
                "INT",
                {"default": -1, "min": -1, "max": 4294967295, "step": 1},
            ),
            "negative_prompt": (
                "STRING",
                {"multiline": True, "default": "", "tooltip": "Optional --no content. | 可选负面提示词。"},
            ),
            "stylize": (
                "INT",
                {"default": -1, "min": -1, "max": 1000, "step": 1},
            ),
            "chaos": (
                "INT",
                {"default": -1, "min": -1, "max": 100, "step": 1},
            ),
            "weird": (
                "INT",
                {"default": -1, "min": -1, "max": 3000, "step": 1},
            ),
            "tile": ("BOOLEAN", {"default": False}),
            "niji": ("BOOLEAN", {"default": False}),
            "iw": (
                "FLOAT",
                {"default": -1.0, "min": -1.0, "max": 3.0, "step": 0.1},
            ),
            "cw": (
                "INT",
                {"default": -1, "min": -1, "max": 100, "step": 1},
            ),
            "sw": (
                "INT",
                {"default": -1, "min": -1, "max": 1000, "step": 1},
            ),
            "cref": ("STRING", {"default": "", "tooltip": "Character reference URL. | 角色参考图 URL。"}),
            "sref": ("STRING", {"default": "", "tooltip": "Style reference URL. | 风格参考图 URL。"}),
            "dref": ("STRING", {"default": "", "tooltip": "Depth reference URL. | 深度参考图 URL。"}),
            "dw": (
                "FLOAT",
                {"default": -1.0, "min": -1.0, "max": 100.0, "step": 0.1},
            ),
            "repeat": (
                "INT",
                {"default": 0, "min": 0, "max": 40, "step": 1},
            ),
            "raw": ("BOOLEAN", {"default": False}),
            "draft": ("BOOLEAN", {"default": False}),
            "hd": ("BOOLEAN", {"default": False}),
            "stop": (
                "INT",
                {"default": 0, "min": 0, "max": 100, "step": 1},
            ),
            "extra": (
                "STRING",
                {"default": "", "tooltip": "Optional native MJ flags. | 可选原生 MJ 参数。"},
            ),
            "task_id": (
                "STRING",
                {
                    "default": "",
                    "tooltip": (
                        "Source Midjourney task id; connect a previous node. | "
                        "源 Midjourney 任务 ID，可连接上游节点。"
                    ),
                },
            ),
            "index": (
                "INT",
                {
                    "default": -1,
                    "min": -1,
                    "max": 4,
                    "step": 1,
                    "tooltip": (
                        "Use 1-4 for image actions; Video task mode uses 0-3. | "
                        "图像操作用 1-4，Video 任务模式用 0-3。"
                    ),
                },
            ),
            "custom_id": (
                "STRING",
                {"default": "", "tooltip": "Optional button customId. | 可选按钮 customId。"},
            ),
            "direction": (
                MIDJOURNEY_DIRECTIONS,
                {"default": "right", "tooltip": "Pan direction. | Pan 平移方向。"},
            ),
            "zoom_ratio": (
                "FLOAT",
                {"default": 2.0, "min": 1.0, "max": 2.0, "step": 0.1},
            ),
            "modal_mode": (
                MIDJOURNEY_MODAL_MODES,
                {
                    "default": "region",
                    "tooltip": "Region uses a mask; outpaint sends no mask. | region 使用遮罩，outpaint 不发送遮罩。",
                },
            ),
            "video_type": (
                MIDJOURNEY_VIDEO_TYPES,
                {"default": "vid_1.1_i2v_480"},
            ),
            "animate_mode": (
                MIDJOURNEY_ANIMATE_MODES,
                {"default": "manual"},
            ),
            "motion": (
                MIDJOURNEY_MOTIONS,
                {"default": "high"},
            ),
            "batch_size": (
                MIDJOURNEY_BATCH_SIZES,
                {"default": 1},
            ),
            "metadata_json": (
                "STRING",
                {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Optional JSON object stored with the task. | 可选任务 metadata JSON。",
                },
            ),
        }
        for i in range(1, MAX_MIDJOURNEY_IMAGES + 1):
            required[f"image_url{i}"] = (
                "STRING",
                {
                    "default": "",
                    "tooltip": (
                        f"Public image URL or image data URL {i}. | "
                        f"公网图片或 data URL {i}。"
                    ),
                },
            )
        required["end_url"] = (
            "STRING",
            {"default": "", "tooltip": "Optional public video end-frame URL. | 可选结束帧 URL。"},
        )
        required["mask_url"] = (
            "STRING",
            {"default": "", "tooltip": "Optional modal mask URL or data URL. | 可选 Modal 遮罩 URL。"},
        )
        return {"required": required, "optional": optional}

    @classmethod
    def VALIDATE_INPUTS(
        cls,
        operation=None,
        speed=None,
        version=None,
        dimensions=None,
        quality=None,
        direction=None,
        modal_mode=None,
        video_type=None,
        animate_mode=None,
        motion=None,
        batch_size=None,
        index=None,
        size=None,
        custom_size=None,
        strict=False,
        **kwargs,
    ):
        operation = _normalize_midjourney_operation(operation)
        if operation not in MIDJOURNEY_ACTION_SPECS:
            return f"unsupported Midjourney operation: {operation}"
        enum_values = {
            "speed": (speed, MIDJOURNEY_SPEEDS),
            "version": (version, MIDJOURNEY_VERSIONS),
            "dimensions": (dimensions, MIDJOURNEY_DIMENSIONS),
            "quality": (quality, MIDJOURNEY_QUALITIES),
            "direction": (direction, MIDJOURNEY_DIRECTIONS),
            "modal_mode": (modal_mode, MIDJOURNEY_MODAL_MODES),
            "video_type": (video_type, MIDJOURNEY_VIDEO_TYPES),
            "animate_mode": (animate_mode, MIDJOURNEY_ANIMATE_MODES),
            "motion": (motion, MIDJOURNEY_MOTIONS),
        }
        for field, (value, allowed) in enum_values.items():
            if value is not None and value not in allowed:
                return f"unsupported {field}: {value}"
        if batch_size is not None and int(batch_size) not in MIDJOURNEY_BATCH_SIZES:
            return "batch_size must be 1, 2, or 4"
        if index is not None and not -1 <= int(index) <= 4:
            return "index must be between -1 and 4"
        supports_size = (
            "size" in MIDJOURNEY_ACTION_SPECS[operation]["allowed_fields"]
        )
        should_validate_size = (
            size is not None
            and (
                str(size).strip() != "custom"
                or strict
                or str(custom_size or "").strip()
            )
        )
        if supports_size and should_validate_size:
            try:
                cls._resolve_size(size, custom_size)
            except SeedanceAPIError as error:
                return str(error)
        return True

    @property
    def _log_prefix(self) -> str:
        return "Midjourney_Multi_Action"

    @staticmethod
    def _text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _is_aspect_ratio(value: str) -> bool:
        parts = value.split(":")
        return (
            len(parts) == 2
            and all(part.isdigit() for part in parts)
            and all(int(part) > 0 for part in parts)
        )

    @classmethod
    def _resolve_size(cls, size: Any, custom_size: Any = "") -> str:
        selected = cls._text(size)
        if selected in {"", "unset"}:
            return "1:1"
        resolved = cls._text(custom_size) if selected == "custom" else selected
        if not cls._is_aspect_ratio(resolved):
            raise SeedanceAPIError(
                "size must be a positive w:h ratio, for example 16:9 | "
                "画面比例必须为正整数 w:h 格式，例如 16:9"
            )
        return resolved

    def _update_progress(self, pbar, value: float):
        if pbar is not None:
            try:
                pbar.update_absolute(int(value), 100)
            except Exception:
                pass

    @staticmethod
    def _media_reference(value: Any, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if not text.startswith(("http://", "https://", "data:image/")):
            raise SeedanceAPIError(
                f"{field} must be an http(s) URL or image data URL | "
                f"{field} 必须是 http(s) URL 或图片 data URL"
            )
        return text

    def _collect_materials(
        self,
        operation: str,
        kwargs: Dict[str, Any],
        config: Dict[str, Any],
        progress_cb,
    ) -> Dict[str, Any]:
        direct_image_actions = {
            "midjourney-imagine",
            "midjourney-blend",
            "midjourney-describe",
            "midjourney-edits",
            "midjourney-video",
        }
        local_jobs = 0
        if operation in direct_image_actions:
            local_jobs += sum(
                1
                for i in range(1, MAX_MIDJOURNEY_IMAGES + 1)
                if kwargs.get(f"image{i}") is not None
            )
        if operation == "midjourney-video" and kwargs.get("end_image") is not None:
            local_jobs += 1
        if (
            operation == "midjourney-modal"
            and self._text(kwargs.get("modal_mode")) == "region"
            and kwargs.get("mask") is not None
        ):
            local_jobs += 1

        uploaded = 0
        image_urls: List[str] = []
        if operation in direct_image_actions:
            for i in range(1, MAX_MIDJOURNEY_IMAGES + 1):
                image = kwargs.get(f"image{i}")
                image_url = self._media_reference(
                    kwargs.get(f"image_url{i}"), f"image_url{i}"
                )
                if image is not None and image_url:
                    raise SeedanceAPIError(
                        f"image{i} and image_url{i} cannot both be used | "
                        f"第 {i} 槽不能同时连接本地图片和填写 URL"
                    )
                if image is not None:
                    image_url = upload_media(
                        image_to_png_bytes(image),
                        f"midjourney_image_{i}.png",
                        "image/png",
                        config,
                        logger_prefix=self._log_prefix,
                    )
                    uploaded += 1
                    progress_cb(uploaded / max(local_jobs, 1))
                if image_url:
                    image_urls.append(image_url)

        end_url = ""
        if operation == "midjourney-video":
            end_image = kwargs.get("end_image")
            end_url = self._media_reference(kwargs.get("end_url"), "end_url")
            if end_image is not None and end_url:
                raise SeedanceAPIError(
                    "end_image and end_url cannot both be used | "
                    "结束帧不能同时连接本地图片和填写 URL"
                )
            if end_image is not None:
                end_url = upload_media(
                    image_to_png_bytes(end_image),
                    "midjourney_end_frame.png",
                    "image/png",
                    config,
                    logger_prefix=self._log_prefix,
                )
                uploaded += 1
                progress_cb(uploaded / max(local_jobs, 1))

        mask_url = ""
        if operation == "midjourney-modal":
            modal_mode = self._text(kwargs.get("modal_mode")) or "region"
            mask = kwargs.get("mask")
            if modal_mode == "outpaint":
                mask = None
                supplied_mask_url = ""
            else:
                supplied_mask_url = self._media_reference(
                    kwargs.get("mask_url"), "mask_url"
                )
            if modal_mode != "outpaint" and mask is not None and supplied_mask_url:
                raise SeedanceAPIError(
                    "mask and mask_url cannot both be used | "
                    "遮罩不能同时连接本地 MASK 和填写 URL"
                )
            if mask is not None:
                supplied_mask_url = upload_media(
                    mask_to_midjourney_png_bytes(mask),
                    "midjourney_mask.png",
                    "image/png",
                    config,
                    logger_prefix=self._log_prefix,
                )
                uploaded += 1
                progress_cb(uploaded / max(local_jobs, 1))
            mask_url = supplied_mask_url
            if modal_mode == "region" and not mask_url:
                raise SeedanceAPIError(
                    "midjourney-modal region mode requires a mask | "
                    "midjourney-modal 局部重绘模式必须提供遮罩"
                )

        if local_jobs == 0:
            progress_cb(1.0)
        return {
            "image_urls": image_urls,
            "end_url": end_url,
            "mask_url": mask_url,
        }

    def _metadata(self, raw_value: Any) -> Optional[Dict[str, Any]]:
        text = self._text(raw_value)
        if not text:
            return None
        try:
            value = json.loads(text)
        except (TypeError, ValueError) as error:
            raise SeedanceAPIError(
                f"metadata_json must be valid JSON: {error}"
            ) from error
        if not isinstance(value, dict):
            raise SeedanceAPIError("metadata_json must contain a JSON object")
        return value

    @staticmethod
    def _validate_structured_compatibility(payload: Dict[str, Any]):
        """Validate documented version gates for structured Imagine flags."""
        version = str(payload.get("version") or "").strip()
        niji = bool(payload.get("niji"))

        if niji and version and version not in {"5", "6", "7"}:
            raise SeedanceAPIError(
                "niji requires version 5, 6, or 7 when version is supplied | "
                "启用 niji 时，version 只能为 5、6 或 7"
            )
        if payload.get("raw") and version == "5":
            raise SeedanceAPIError(
                "raw requires version 5.1 or newer | raw 需要 version 5.1 或更高"
            )
        if (
            payload.get("draft")
            and version
            and version not in {"7", "8.1", "8.2"}
        ):
            raise SeedanceAPIError(
                "draft requires version 7 or newer | draft 需要 version 7 或更高"
            )
        if payload.get("hd") and version and version not in {"8.1", "8.2"}:
            raise SeedanceAPIError(
                "hd supports only version 8.1 or 8.2 | "
                "hd 仅支持 version 8.1 或 8.2"
            )
        if "stop" in payload and version:
            supported = {"5", "6"} if niji else {
                "5", "5.1", "5.2", "6", "6.1"
            }
            if version not in supported:
                family = "Niji" if niji else "Midjourney"
                raise SeedanceAPIError(
                    f"stop is not supported by {family} version {version} | "
                    f"{family} version {version} 不支持 stop"
                )

    def _build_payload(
        self,
        operation: str,
        materials: Dict[str, Any],
        **kwargs,
    ) -> Dict[str, Any]:
        operation = _normalize_midjourney_operation(operation)
        if operation not in MIDJOURNEY_ACTION_SPECS:
            raise SeedanceAPIError(
                f"unsupported Midjourney operation: {operation}"
            )
        spec = MIDJOURNEY_ACTION_SPECS[operation]
        allowed = set(spec["allowed_fields"])
        payload: Dict[str, Any] = {}

        prompt = self._text(kwargs.get("prompt"))
        if "prompt" in allowed and prompt:
            payload["prompt"] = prompt
        image_urls = list(materials.get("image_urls") or [])
        if "image_urls" in allowed and image_urls:
            payload["image_urls"] = image_urls

        task_id = self._text(kwargs.get("task_id"))
        if "task_id" in allowed and task_id:
            payload["task_id"] = task_id

        custom_id = self._text(kwargs.get("custom_id"))
        if "custom_id" in allowed and custom_id:
            payload["custom_id"] = custom_id

        raw_index = kwargs.get("index")
        index = int(raw_index) if raw_index is not None else -1
        if "index" in allowed and index >= 0 and not custom_id:
            payload["index"] = index

        speed = self._text(kwargs.get("speed"))
        if "speed" in allowed and speed and speed != "unset":
            payload["speed"] = speed

        if "size" in allowed:
            payload["size"] = self._resolve_size(
                kwargs.get("size"),
                kwargs.get("custom_size"),
            )
        size = self._text(payload.get("size"))
        dimensions = self._text(kwargs.get("dimensions"))
        if "dimensions" in allowed and dimensions and dimensions != "unset" and not size:
            payload["dimensions"] = dimensions

        if "direction" in allowed and not custom_id:
            direction = self._text(kwargs.get("direction"))
            if direction and direction != "unset":
                payload["direction"] = direction
        if "zoom_ratio" in allowed and not custom_id:
            zoom_ratio = float(kwargs.get("zoom_ratio") or 2.0)
            if not 1.0 <= zoom_ratio <= 2.0:
                raise SeedanceAPIError("zoom_ratio must be between 1.0 and 2.0")
            payload["zoom_ratio"] = zoom_ratio

        if "mask_url" in allowed and materials.get("mask_url"):
            payload["mask_url"] = materials["mask_url"]
        if "end_url" in allowed and materials.get("end_url"):
            payload["end_url"] = materials["end_url"]

        if operation == "midjourney-video":
            payload["video_type"] = self._text(kwargs.get("video_type"))
            payload["animate_mode"] = self._text(kwargs.get("animate_mode"))
            payload["motion"] = self._text(kwargs.get("motion"))
            payload["batch_size"] = int(kwargs.get("batch_size") or 1)

        enum_fields = ("quality", "version")
        for field in enum_fields:
            if field in allowed:
                value = self._text(kwargs.get(field))
                if value and value != "unset":
                    payload[field] = value
        for field in (
            "style",
            "negative_prompt",
            "cref",
            "sref",
            "dref",
            "extra",
        ):
            if field not in allowed:
                continue
            value = self._text(kwargs.get(field))
            if value:
                if field in {"cref", "sref", "dref"}:
                    value = self._media_reference(value, field)
                payload[field] = value

        sentinel_ints = {
            "seed": -1,
            "stylize": -1,
            "chaos": -1,
            "weird": -1,
            "cw": -1,
            "sw": -1,
            "repeat": 0,
            "stop": 0,
        }
        for field, sentinel in sentinel_ints.items():
            if field in allowed:
                value = int(kwargs.get(field) if kwargs.get(field) is not None else sentinel)
                if value > sentinel:
                    payload[field] = value
        if payload.get("repeat") == 1:
            raise SeedanceAPIError("repeat must be 0 (unset) or 2-40")
        if "stop" in payload and payload["stop"] < 10:
            raise SeedanceAPIError("stop must be 0 (unset) or 10-100")

        for field in ("iw", "dw"):
            if field in allowed:
                value = float(kwargs.get(field) if kwargs.get(field) is not None else -1.0)
                if value >= 0:
                    payload[field] = value
        for field in ("tile", "niji", "raw", "draft", "hd"):
            if field in allowed and bool(kwargs.get(field, False)):
                payload[field] = True

        self._validate_structured_compatibility(payload)

        if "metadata" in allowed:
            metadata = self._metadata(kwargs.get("metadata_json"))
            if metadata is not None:
                payload["metadata"] = metadata

        if operation == "midjourney-blend" and not 2 <= len(image_urls) <= 4:
            raise SeedanceAPIError(
                "midjourney-blend requires 2-4 images | "
                "midjourney-blend 必须提供 2-4 张图片"
            )
        if operation == "midjourney-describe" and len(image_urls) != 1:
            raise SeedanceAPIError(
                "midjourney-describe requires exactly one image | "
                "midjourney-describe 必须提供一张图片"
            )

        missing = [
            field
            for field in spec["required_fields"]
            if field not in payload
            or payload[field] is None
            or payload[field] == ""
            or payload[field] == []
        ]
        if missing:
            raise SeedanceAPIError(
                f"{operation} requires: {', '.join(missing)} | "
                f"{operation} 缺少必填参数：{', '.join(missing)}"
            )
        for field_group in spec["required_one_of"]:
            if not any(
                field in payload and payload[field] not in ("", None, [])
                for field in field_group
            ):
                fields = " or ".join(field_group)
                raise SeedanceAPIError(
                    f"{operation} requires {fields} | "
                    f"{operation} 必须提供 {fields}"
                )

        if operation == "midjourney-imagine" and len(image_urls) > 4:
            raise SeedanceAPIError("midjourney-imagine accepts at most 4 images")
        if operation == "midjourney-edits" and not 1 <= len(image_urls) <= 4:
            raise SeedanceAPIError(
                "midjourney-edits requires 1-4 images | "
                "midjourney-edits 必须提供 1-4 张图片"
            )

        one_based_actions = {
            "midjourney-upscale",
            "midjourney-variation",
            "midjourney-high-variation",
            "midjourney-low-variation",
            "midjourney-remix-strong",
            "midjourney-remix-subtle",
        }
        if (
            operation in one_based_actions
            and "custom_id" not in payload
            and not 1 <= int(payload.get("index", -1)) <= 4
        ):
            raise SeedanceAPIError(
                f"{operation} index must be 1-4 | {operation} 的 index 必须为 1-4"
            )
        if (
            operation in {"midjourney-zoom", "midjourney-pan", "midjourney-inpaint"}
            and "index" in payload
            and not 1 <= int(payload["index"]) <= 4
        ):
            raise SeedanceAPIError(
                f"{operation} index must be 1-4 when supplied"
            )

        if operation == "midjourney-video":
            has_images = bool(payload.get("image_urls"))
            has_task = bool(payload.get("task_id"))
            if has_images == has_task:
                raise SeedanceAPIError(
                    "midjourney-video requires exactly one source: image or task_id | "
                    "midjourney-video 必须且只能选择首帧图片或任务 ID"
                )
            if has_images and len(payload["image_urls"]) != 1:
                raise SeedanceAPIError(
                    "midjourney-video accepts exactly one start image"
                )
            if has_images and not prompt:
                raise SeedanceAPIError(
                    "midjourney-video direct image mode requires prompt"
                )
            if payload["animate_mode"] == "auto":
                if not has_task or "index" not in payload:
                    raise SeedanceAPIError(
                        "midjourney-video auto mode requires task_id and index 0-3"
                    )
            if has_images and "index" in payload:
                raise SeedanceAPIError(
                    "midjourney-video index is only valid with task_id"
                )
            if has_task and "index" in payload and not 0 <= payload["index"] <= 3:
                raise SeedanceAPIError(
                    "midjourney-video task index must be 0-3"
                )
            if payload["batch_size"] not in MIDJOURNEY_BATCH_SIZES:
                raise SeedanceAPIError(
                    "midjourney-video batch_size must be 1, 2, or 4"
                )
            has_end = bool(payload.get("end_url"))
            is_start_end = "_start_end_" in payload["video_type"]
            if has_end and not is_start_end:
                resolution = "720" if "720" in payload["video_type"] else "480"
                payload["video_type"] = f"vid_1.1_i2v_start_end_{resolution}"
            elif is_start_end and not has_end:
                raise SeedanceAPIError(
                    "start/end video_type requires end_image or end_url"
                )

        return {
            key: value
            for key, value in payload.items()
            if key in allowed
        }

    @staticmethod
    def _response_status(response: Dict[str, Any]) -> str:
        if not isinstance(response, dict):
            return ""
        data = response.get("data")
        if isinstance(data, list):
            data = next((item for item in data if isinstance(item, dict)), {})
        if isinstance(data, dict):
            return str(data.get("status") or "").strip().upper()
        return str(response.get("status") or "").strip().upper()

    def _make_error_result(self, error_msg: str) -> Dict[str, Any]:
        response_str = json.dumps({"error": error_msg}, ensure_ascii=False, indent=2)
        error_image = make_error_image(error_msg)
        error_video = make_error_video(error_msg)
        return {
            "ui": {"text": ["", "", "", "", response_str]},
            "result": (
                error_image,
                None,
                None,
                None,
                None,
                error_video,
                None,
                None,
                None,
                "",
                "",
                "[]",
                "",
                "[]",
                "",
                "[]",
                response_str,
            ),
        }

    def execute(
        self,
        operation: str,
        prompt: str = "",
        api_config=None,
        skip_error: bool = False,
        **kwargs,
    ):
        all_kwargs = {**kwargs, "prompt": prompt}
        try:
            return self._execute_inner(
                operation=operation,
                api_config=api_config,
                **all_kwargs,
            )
        except Exception as error:
            if skip_error:
                error_msg = f"{self._log_prefix}: {error}"
                print(f"[{self._log_prefix}] skip_error=True: {type(error).__name__}")
                return self._make_error_result(error_msg)
            raise

    def _execute_inner(
        self,
        operation: str,
        api_config=None,
        **kwargs,
    ):
        operation = _normalize_midjourney_operation(operation)
        validation = self.VALIDATE_INPUTS(
            operation=operation,
            speed=kwargs.get("speed"),
            version=kwargs.get("version"),
            dimensions=kwargs.get("dimensions"),
            quality=kwargs.get("quality"),
            direction=kwargs.get("direction"),
            modal_mode=kwargs.get("modal_mode"),
            video_type=kwargs.get("video_type"),
            animate_mode=kwargs.get("animate_mode"),
            motion=kwargs.get("motion"),
            batch_size=kwargs.get("batch_size"),
            index=kwargs.get("index"),
            size=kwargs.get("size"),
            custom_size=kwargs.get("custom_size"),
            strict=True,
        )
        if validation is not True:
            raise SeedanceAPIError(validation)

        spec = MIDJOURNEY_ACTION_SPECS[operation]
        config = get_config(api_config)
        pbar = _make_progress_bar(100)
        self._update_progress(pbar, 0)

        materials = self._collect_materials(
            operation,
            kwargs,
            config,
            lambda fraction: self._update_progress(pbar, fraction * 15),
        )
        payload = self._build_payload(operation, materials, **kwargs)
        self._update_progress(pbar, 15)

        submitted_task_id, submit_response = submit_midjourney_action(
            spec["action"],
            payload,
            config,
            logger_prefix=self._log_prefix,
        )
        self._update_progress(pbar, 20)

        final_response = submit_response
        submit_extracted = extract_midjourney_results(submit_response)
        submit_status = self._response_status(submit_response)
        submit_is_complete = submit_status in {
            "SUCCESS",
            "SUCCEEDED",
            "COMPLETED",
            "COMPLETE",
        }
        submit_is_modal = submit_status == "MODAL"
        submit_has_sync_result = (
            spec["execution_mode"] == "sync_or_async"
            and bool(self._text(submit_extracted.get("text")))
        )
        if (
            submitted_task_id
            and not submit_is_complete
            and not submit_is_modal
            and not submit_has_sync_result
        ):
            final_response = poll_midjourney_task(
                submitted_task_id,
                config,
                on_progress=lambda progress: self._update_progress(
                    pbar, 20 + progress / 100.0 * 60
                ),
                logger_prefix=self._log_prefix,
                stop_on_modal=spec["execution_mode"] == "modal_stage",
            )
        elif (
            not submitted_task_id
            and spec["execution_mode"] not in {"sync_or_async"}
        ):
            raise SeedanceAPIError(
                f"{operation} returned no task id"
            )
        self._update_progress(pbar, 82)

        extracted = extract_midjourney_results(final_response)
        result_task_id = submitted_task_id or extracted["task_id"]
        if spec["execution_mode"] == "modal_stage":
            final_status = self._response_status(final_response)
            if final_status != "MODAL":
                raise SeedanceAPIError(
                    "midjourney-inpaint did not reach MODAL state"
                )

        image_objects: List[Any] = []
        image_paths: List[str] = []
        video_objects: List[Any] = []
        video_paths: List[str] = []
        download_warnings: List[Dict[str, Any]] = []
        successful_downloads = 0

        image_urls = list(extracted.get("image_urls") or [])
        grid_url = self._text(extracted.get("grid_image_url"))
        video_urls = list(extracted.get("video_urls") or [])
        artifact_count = max(
            1,
            len(image_urls) + (1 if grid_url else 0) + len(video_urls),
        )
        artifact_index = 0

        for url in image_urls:
            artifact_index += 1
            path = ""
            image = None
            try:
                image, path = download_image_with_path(
                    url, logger_prefix=self._log_prefix
                )
                successful_downloads += 1
            except Exception as error:
                download_warnings.append(
                    {
                        "artifact_index": artifact_index,
                        "kind": "image",
                        "error": type(error).__name__,
                    }
                )
            image_objects.append(image)
            image_paths.append(path)
            self._update_progress(
                pbar, 82 + artifact_index / artifact_count * 15
            )

        grid_image = None
        grid_path = ""
        if grid_url:
            artifact_index += 1
            try:
                grid_image, grid_path = download_image_with_path(
                    grid_url, logger_prefix=self._log_prefix
                )
                successful_downloads += 1
            except Exception as error:
                download_warnings.append(
                    {
                        "artifact_index": artifact_index,
                        "kind": "grid_image",
                        "error": type(error).__name__,
                    }
                )
            self._update_progress(
                pbar, 82 + artifact_index / artifact_count * 15
            )

        for url in video_urls:
            artifact_index += 1
            path = ""
            video = None
            try:
                video, path = download_video_with_path(
                    url, logger_prefix=self._log_prefix
                )
                successful_downloads += 1
            except Exception as error:
                download_warnings.append(
                    {
                        "artifact_index": artifact_index,
                        "kind": "video",
                        "error": type(error).__name__,
                    }
                )
            video_objects.append(video)
            video_paths.append(path)
            self._update_progress(
                pbar, 82 + artifact_index / artifact_count * 15
            )

        has_artifacts = bool(image_urls or grid_url or video_urls)
        if has_artifacts and successful_downloads == 0:
            raise SeedanceAPIError(
                "All Midjourney result artifacts failed to download | "
                "Midjourney 结果文件全部下载失败"
            )
        if (
            not has_artifacts
            and spec["result_family"] in {"image", "video"}
        ):
            raise SeedanceAPIError(
                f"{operation} completed without downloadable media"
            )

        text = self._text(extracted.get("text"))
        if spec["result_family"] == "text" and not text:
            raise SeedanceAPIError(
                f"{operation} completed without text output"
            )

        all_urls = [
            *image_urls,
            *([grid_url] if grid_url else []),
            *video_urls,
        ]
        result_paths = [
            *image_paths,
            *([grid_path] if grid_url else []),
            *video_paths,
        ]
        primary_url = all_urls[0] if all_urls else ""
        primary_path = result_paths[0] if result_paths else ""
        response_payload = final_response
        if download_warnings:
            response_payload = dict(final_response)
            response_payload["_seedance_local"] = {
                "download_warnings": download_warnings
            }
        response_str = json.dumps(
            response_payload, ensure_ascii=False, indent=2
        )
        buttons_str = json.dumps(
            extracted.get("buttons") or [], ensure_ascii=False
        )
        urls_str = json.dumps(all_urls, ensure_ascii=False)
        paths_str = json.dumps(result_paths, ensure_ascii=False)
        self._update_progress(pbar, 100)

        padded_images = (image_objects + [None] * 4)[:4]
        padded_videos = (video_objects + [None] * 4)[:4]
        return {
            "ui": {
                "text": [
                    text,
                    primary_url,
                    primary_path,
                    result_task_id,
                    response_str,
                ]
            },
            "result": (
                *padded_images,
                grid_image,
                *padded_videos,
                text,
                primary_url,
                urls_str,
                primary_path,
                paths_str,
                result_task_id,
                buttons_str,
                response_str,
            ),
        }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

NODE_CLASS_MAPPINGS = {
    "Seedance_Config": SeedanceConfig,
    "Seedance_TextToVideo": SeedanceTextToVideo,
    "Seedance_ImageToVideo": SeedanceImageToVideo,
    "Seedance_MultimodalVideo": SeedanceMultimodalVideo,
    "Seedance_2_5_Video": Seedance25Video,
    "Seedream_V5_Pro_Image": SeedreamV5ProImage,
    "Zhenzhen_Image_G2": ZhenzhenImageG2,
    "Qwen_Image_3_0": QwenImage30,
    "Zhenzhen_Image_GK_V15": ZhenzhenImageGKV15,
    "Zhenzhen_Image_NB": ZhenzhenImageNB,
    "Zhenzhen_Video_G_Omni_Flash": ZhenzhenVideoGOmniFlash,
    "Zhenzhen_Video_GK_V15": ZhenzhenVideoGKV15,
    "Zhenzhen_Video_V31": ZhenzhenVideoV31,
    "HappyHorse_1_1_Video": HappyHorseVideo,
    "Wan_2_7_Spicy_I2V": Wan27SpicyImageToVideo,
    "Kling_Video": KlingVideo,
    "Kling_Edit_Video": KlingEditVideo,
    "Hailuo_2_3_Video": Hailuo23Video,
    "Hailuo_H3_Video": HailuoH3Video,
    "Minimax_H3_OW_Video": MinimaxH3OWVideo,
    "Vidu_Q3_Video": ViduQ3Video,
    "Vidu_Q3_ShortPlay": ViduQ3ShortPlay,
    "Zhenzhen_Upscaler_Video": ZhenzhenUpscalerVideo,
    "Doubao_Seed_Audio": DoubaoSeedAudio,
    "Whisper_Transcription": WhisperTranscription,
    "Suno_Music": SunoMusic,
    "Midjourney_Multi_Action": MidjourneyMultiAction,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Seedance_Config": "Seedance API Config",
    "Seedance_TextToVideo": "Seedance 文生视频 (Text to Video)",
    "Seedance_ImageToVideo": "Seedance 图生视频 (Image to Video)",
    "Seedance_MultimodalVideo": "Seedance 多模态视频 (Multimodal Video)",
    "Seedance_2_5_Video": "Seedance 2.5 Standard 视频生成（6 合 1）",
    "Seedream_V5_Pro_Image": "Seedream / Dola Seedream 图像生成/编辑",
    "Zhenzhen_Image_G2": "Zhenzhen Image G 图像生成/编辑",
    "Qwen_Image_3_0": "Qwen Image 3.0 / Pro 图像生成/编辑（8 合 1）",
    "Zhenzhen_Image_GK_V15": "Zhenzhen Image GK v1.5 图像生成/编辑",
    "Zhenzhen_Image_NB": "Zhenzhen Image Nano Banana 生成/编辑",
    "Zhenzhen_Video_G_Omni_Flash": "Zhenzhen Video G Omni Flash",
    "Zhenzhen_Video_GK_V15": "Zhenzhen Video GK v1.5",
    "Zhenzhen_Video_V31": "Zhenzhen Video V3.1",
    "HappyHorse_1_1_Video": "HappyHorse 1.1 视频生成",
    "Wan_2_7_Spicy_I2V": "Wan 2.7 Spicy 图生视频",
    "Kling_Video": "Kling 视频生成",
    "Kling_Edit_Video": "Kling O3 视频编辑",
    "Hailuo_2_3_Video": "Hailuo 2.3 视频生成",
    "Hailuo_H3_Video": "Hailuo H3 视频生成",
    "Minimax_H3_OW_Video": "MiniMax H3 OW 视频生成（3 合 1）",
    "Vidu_Q3_Video": "Vidu Q3 视频生成",
    "Vidu_Q3_ShortPlay": "Vidu Q3 短剧成片",
    "Zhenzhen_Upscaler_Video": "Zhenzhen Upscaler 视频超分",
    "Doubao_Seed_Audio": "Doubao Seed Audio 1.0 音频生成",
    "Whisper_Transcription": "Whisper 1 语音转写",
    "Suno_Music": "Suno 音乐生成与处理（31 合 1）",
    "Midjourney_Multi_Action": "Midjourney 图像与视频（16 合 1）",
}
