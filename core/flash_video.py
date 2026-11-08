"""Zhenzhen Kling 4 Flash and Omni 1.2 documented request contracts."""

from .client import SeedanceAPIError
from .kling_v4 import http_url, string_list
from .preview_models import references


KLING_MODEL = "zhenzhen-video-kling-v4-flash"
OMNI_MODEL = "zhenzhen-video-g-omni-1.2-flash-lowprice"
PROFILES = {
    KLING_MODEL: {"seconds": 20, "videos": 5, "resolutions": ["720p"], "ratios": ["16:9", "9:16", "1:1", "21:9"]},
    OMNI_MODEL: {"seconds": 15, "videos": 1, "resolutions": ["360p", "720p", "1080p", "4k"], "ratios": ["16:9", "9:16"]},
}


def video_references(model, kwargs):
    maximum = PROFILES[model]["videos"]
    local = []
    for name, value in kwargs.items():
        if name.startswith("video") and name[5:].isdigit() and value is not None:
            index = int(name[5:])
            if not 1 <= index <= maximum:
                raise SeedanceAPIError(f"This model supports at most {maximum} reference videos")
            local.append((index, value))
    urls = string_list(kwargs.get("video_urls", ""), "video_urls")
    if any(not http_url(url) for url in urls):
        raise SeedanceAPIError("Reference videos require public HTTP(S) URLs")
    if len(local) + len(urls) > maximum:
        raise SeedanceAPIError(f"This model supports at most {maximum} reference videos")
    return sorted(local), urls


def validate(model, kwargs, strict=False):
    if model not in PROFILES:
        raise SeedanceAPIError("Unsupported Flash video model")
    profile = PROFILES[model]
    prompt = kwargs.get("prompt")
    if prompt is not None and not isinstance(prompt, str):
        raise SeedanceAPIError("prompt must be text")
    if strict and not (prompt or "").strip():
        raise SeedanceAPIError("A non-empty prompt is required")
    seconds = kwargs.get("seconds", 3)
    if isinstance(seconds, bool) or not isinstance(seconds, int) or not 3 <= seconds <= profile["seconds"]:
        raise SeedanceAPIError(f"Duration must be an integer from 3 to {profile['seconds']} seconds")
    if kwargs.get("resolution", "720p") not in profile["resolutions"]:
        raise SeedanceAPIError("Unsupported Flash video resolution")
    ratio = kwargs.get("aspect_ratio", kwargs.get("ratio", "16:9"))
    if ratio not in profile["ratios"]:
        raise SeedanceAPIError("Unsupported Flash video aspect ratio")
    images = references(kwargs, 10)
    local, urls = video_references(model, kwargs)
    if images and (local or urls):
        raise SeedanceAPIError("Choose image references OR video references, not both")
    for field in ("image_element_ids", "video_element_ids", "voice_ids"):
        value = kwargs.get(field, "")
        if value is None and not strict:
            continue
        if not isinstance(value, str):
            raise SeedanceAPIError(f"{field} must be text")
        if value.strip():
            raise SeedanceAPIError("Kling Flash does not accept element or voice IDs; disconnect them or select Kling 4 Omni")


def payload(model, kwargs, media):
    validate(model, kwargs, strict=True)
    images, videos = list(media.get("images", [])), list(media.get("videos", []))
    if len(images) > 10 or len(videos) > PROFILES[model]["videos"] or (images and videos):
        raise SeedanceAPIError("Unsupported Flash video reference combination")
    # The live /v1/videos parser requires strings despite numeric documentation examples.
    result = {"model": model, "prompt": kwargs["prompt"].strip(), "seconds": str(kwargs.get("seconds", 3)),
              "resolution": kwargs.get("resolution", "720p"),
              "aspect_ratio": kwargs.get("aspect_ratio", kwargs.get("ratio", "16:9"))}
    if images:
        result["images"] = images
    if videos:
        result["metadata"] = {"video_url": videos}
    return result
