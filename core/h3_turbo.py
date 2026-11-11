"""Documented MiniMax H3 ComfyUI/Image and Qwen 2.1 Turbo contracts."""

import io

import numpy as np
from PIL import Image
import torch

from .client import SeedanceAPIError
from .media import audio_to_wav_bytes
from .preview_models import references


RATIOS = ["1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"]
PROFILES = {
    "video": {"model": "minimax-h3-comfyui-max", "images": 9,
              "resolutions": ["480p", "608p", "768p", "896p", "1088p", "1280p", "1440p"],
              "default": "480p", "ratios": ["16:9", "9:16"]},
    "minimax_image": {"model": "minimax-h3-image", "images": 16,
                      "resolutions": ["1k", "2k", "4k"], "default": "2k", "ratios": RATIOS + ["1:3", "3:1"]},
    "qwen": {"model": "qwen-image-2.1-turbo", "images": 4,
             "resolutions": ["1k", "2k", "720p"], "default": "1k", "ratios": RATIOS},
}
MIB = 1024 * 1024


def validate(kind, kwargs, strict=False):
    spec = PROFILES[kind]
    prompt = kwargs.get("prompt")
    if prompt is not None and not isinstance(prompt, str):
        raise SeedanceAPIError("prompt must be text")
    if strict and not (prompt or "").strip():
        raise SeedanceAPIError("A non-empty prompt is required | 必须填写提示词")
    if kind == "qwen" and isinstance(prompt, str) and len(prompt.encode("utf-8")) > 8192:
        raise SeedanceAPIError("Qwen Turbo prompt must not exceed 8192 UTF-8 bytes")
    images = references(kwargs, spec["images"])
    for name, allowed in (("resolution", spec["resolutions"]), ("ratio", spec["ratios"])):
        if kwargs.get(name) is not None and kwargs[name] not in allowed:
            raise SeedanceAPIError("Unsupported " + name)
    if kind == "qwen" and strict and kwargs.get("resolution") == "720p" and not images:
        raise SeedanceAPIError("720p requires a reference image | 720p 仅支持图像编辑")
    if kind == "video":
        if kwargs.get("seconds") is not None and kwargs["seconds"] not in [str(i) for i in range(3, 16)]:
            raise SeedanceAPIError("seconds must be an integer string from 3 to 15")
        for name, value in kwargs.items():
            if name.startswith("audio") and name[5:].isdigit() and value is not None and not 1 <= int(name[5:]) <= 3:
                raise SeedanceAPIError("At most three audio references are supported")
    else:
        seed = kwargs.get("seed", -1)
        if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool) or not -1 <= seed <= 2147483647):
            raise SeedanceAPIError("seed must be -1 (omit) or 0..2147483647")
        if kind == "minimax_image" and kwargs.get("output_format", "jpeg") not in ("jpeg", "png", "webp"):
            raise SeedanceAPIError("output_format must be jpeg, png or webp")
    return True


def encode_media(kind, kwargs):
    validate(kind, kwargs, strict=True)
    encoded = []
    for index, image in references(kwargs, PROFILES[kind]["images"]):
        shape = getattr(image, "shape", ())
        if len(shape) != 4 or shape[0] != 1 or shape[-1] not in (3, 4) or min(shape[1:3]) < 1:
            raise SeedanceAPIError("Each image reference must be one RGB/RGBA IMAGE, not a batch")
        pixels = image.detach().cpu().numpy()[0]
        if not np.isfinite(pixels).all():
            raise SeedanceAPIError("Image contains non-finite pixels")
        buffer = io.BytesIO()
        Image.fromarray(np.clip(pixels * 255, 0, 255).astype(np.uint8)).save(buffer, format="PNG")
        data = buffer.getvalue()
        if kind == "video" and len(data) > 10 * MIB:
            raise SeedanceAPIError("Each video reference image must not exceed 10 MiB")
        encoded.append((f"image{index}", data, "image/png"))
    if kind == "video":
        if sum(len(data) for _, data, _ in encoded) > 50 * MIB:
            raise SeedanceAPIError("Video reference images must total at most 50 MiB")
        audio_bytes = 0
        for index in range(1, 4):
            audio = kwargs.get(f"audio{index}")
            if audio is None:
                continue
            wave = audio.get("waveform") if isinstance(audio, dict) else None
            rate = audio.get("sample_rate") if isinstance(audio, dict) else None
            if not isinstance(wave, torch.Tensor) or wave.ndim != 3 or wave.shape[0] != 1 or not 1 <= wave.shape[1] <= 2 or wave.shape[2] < 1:
                raise SeedanceAPIError("Each audio reference requires one mono/stereo AUDIO")
            if not isinstance(rate, int) or isinstance(rate, bool) or rate < 1 or not torch.isfinite(wave).all():
                raise SeedanceAPIError("Invalid audio sample rate or waveform")
            data = audio_to_wav_bytes(audio)
            audio_bytes += len(data)
            if audio_bytes > 10 * MIB:
                raise SeedanceAPIError("Audio references must total at most 10 MiB")
            encoded.append((f"audio{index}", data, "audio/wav"))
    return encoded


def payload(kind, kwargs, image_urls, audio_urls=()):
    validate(kind, kwargs, strict=True)
    spec = PROFILES[kind]
    metadata = {"resolution": kwargs.get("resolution", spec["default"]),
                "ratio": kwargs.get("ratio", spec["ratios"][0])}
    body = {"model": spec["model"], "prompt": kwargs["prompt"].strip(), "metadata": metadata}
    if image_urls:
        body["images"] = list(image_urls)
    if kind == "video":
        body["seconds"] = kwargs.get("seconds", "5")
        if audio_urls:
            metadata["audio_urls"] = list(audio_urls)
    else:
        if kwargs.get("seed", -1) >= 0:
            metadata["seed"] = kwargs["seed"]
        if kind == "minimax_image":
            metadata["output_format"] = kwargs.get("output_format", "jpeg")
    return body
