"""Magi 2 request validation and ordered local reference preparation."""

import math
import mimetypes

from .client import SeedanceAPIError
from .h3_comfy import slots
from .kling_v4 import probe_video
from .media import video_to_bytes
from .nov21_models import audio_bytes, boolean, choice, image_bytes, text


MODELS = ["magi-2", "magi-2-global"]
MODES = ["auto", "text", "frame", "reference"]
RATIOS = ["api_default", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]
CAPS = {"image": 10, "video": 5, "audio": 5}


def request(kwargs, strict=False):
    model = choice(kwargs, "model", MODELS)
    mode = choice(kwargs, "generation_type", MODES)
    ratio = choice(kwargs, "ratio", RATIOS)
    prompt = text(kwargs, "prompt", maximum=15000, required=strict).strip()
    seconds = kwargs.get("seconds", 5)
    if type(seconds) is not int or not 4 <= seconds <= 30:
        raise SeedanceAPIError("Magi 2 duration must be 4-30 whole seconds")
    metadata = {"resolution": "1080p", "generate_audio": boolean(
        {"generate_audio": kwargs.get("generate_audio", True)}, "generate_audio")}
    if ratio != "api_default":
        metadata["ratio"] = ratio
    if "seed" in kwargs:
        seed = kwargs["seed"]
        if type(seed) is not int or not 0 <= seed <= 2147483647:
            raise SeedanceAPIError("Magi 2 seed must be between 0 and 2147483647")
        metadata["seed"] = seed
    media = {family: slots(kwargs, family, cap) for family, cap in CAPS.items()}
    images = media["image"]
    has_av = bool(media["audio"] or media["video"])
    if mode != "auto":
        metadata["generation_type"] = mode
    else:
        mode = "reference" if has_av or len(images) >= 3 else "frame" if images else "text"
    # Actual connected data is available only during execution, not graph validation.
    if strict:
        if mode == "text" and (images or has_av):
            raise SeedanceAPIError("Text mode does not accept references")
        if mode == "frame" and (has_av or [i for i, _ in images] not in ([1], [1, 2])):
            raise SeedanceAPIError("Frame mode needs image1 as the start frame, optionally image2 as the end frame, and no video/audio")
        if mode == "reference" and not (images or has_av):
            raise SeedanceAPIError("Reference mode needs at least one image, video or audio")
    return {"model": model, "prompt": prompt, "seconds": str(seconds), "metadata": metadata}, media


def check_duration(family, durations):
    if any(not math.isfinite(value) or not 2 <= value <= 30 for value in durations):
        raise SeedanceAPIError(f"Each Magi 2 reference {family} must be 2-30 seconds")
    if sum(durations) > 30:
        raise SeedanceAPIError(f"Total Magi 2 reference {family} duration must not exceed 30 seconds")


def prepare(kwargs):
    body, references = request(kwargs, strict=True)
    media = [("images", f"magi_image{index}.png", "image/png", image_bytes(image, f"image{index}"))
             for index, image in references["image"]]
    videos = []
    for index, video in references["video"]:
        try:
            data, extension = video_to_bytes(video)
            duration = probe_video(data, extension)["duration"]
        except Exception as exc:
            raise SeedanceAPIError(f"Could not read duration of Magi 2 reference video{index}") from exc
        filename = f"magi_video{index}.{extension}"
        videos.append((duration, ("video_url", filename, mimetypes.guess_type(filename)[0] or "video/mp4", data)))
    check_duration("video", [duration for duration, _ in videos])
    media.extend(entry for _, entry in videos)
    durations = []
    for index, audio in references["audio"]:
        data = audio_bytes(audio)
        durations.append(audio["waveform"].shape[-1] / audio["sample_rate"])
        media.append(("audio_urls", f"magi_audio{index}.wav", "audio/wav", data))
    check_duration("audio", durations)
    return body, media
