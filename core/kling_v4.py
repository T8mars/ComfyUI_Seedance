"""Documented Kling 4 request validation and media/result adapters."""

from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlparse

from .client import SeedanceAPIError, _find_ffmpeg


RATIOS = ["21:9", "16:9", "1:1", "9:16"]
RESOLUTIONS = ["720p", "1080p"]
WATERMARKS = ["api_default", "disabled", "enabled"]
TAGS = [f"o_{value}" for value in range(101, 109)]


def string_list(value, name):
    if not isinstance(value, str):
        raise SeedanceAPIError(f"{name} must be text | {name} 必须为文本")
    value = value.strip()
    if not value:
        return []
    try:
        result = json.loads(value) if value.startswith("[") else value.splitlines()
    except ValueError as exc:
        raise SeedanceAPIError(f"{name}: invalid JSON string array") from exc
    if not isinstance(result, list) or any(not isinstance(item, str) or not item.strip() for item in result):
        raise SeedanceAPIError(f"{name} requires a JSON string array or one item per line")
    return [item.strip() for item in result]


def http_url(value):
    try:
        parsed = urlparse(value)
        return (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and not any(char.isspace() for char in value))
    except ValueError:
        return False


def prompt_valid(prompt, required=False):
    if not isinstance(prompt, str):
        raise SeedanceAPIError("Kling 4 prompt must be text")
    if required and not prompt.strip():
        raise SeedanceAPIError("Kling 4 prompt is required | 必须填写提示词")
    english = sum(ord(char) < 128 for char in prompt)
    other = len(prompt) - english
    if english * 11000 + other * 26000 > 26000 * 11000:
        raise SeedanceAPIError("Kling 4 prompt exceeds the documented mixed-language length limit")


def validate_video(kind, kwargs, strict=False):
    prompt_valid(kwargs.get("prompt", ""), required=strict and kind != "i2v")
    seconds = kwargs.get("seconds", 3)
    if isinstance(seconds, bool) or not isinstance(seconds, int) or not 3 <= seconds <= 30:
        raise SeedanceAPIError("Kling 4 duration must be an integer from 3 to 30 seconds")
    if kwargs.get("resolution", "720p") not in RESOLUTIONS:
        raise SeedanceAPIError("Kling 4 resolution must be 720p or 1080p")
    if kind != "i2v" and kwargs.get("ratio", "16:9") not in RATIOS + (["adaptive"] if kind == "omni" else []):
        raise SeedanceAPIError("Unsupported Kling 4 ratio")
    if kwargs.get("watermark", "api_default") not in WATERMARKS:
        raise SeedanceAPIError("Unsupported Kling 4 watermark control")
    if kind == "i2v" and strict and kwargs.get("image1") is None:
        raise SeedanceAPIError("Kling 4 I2V requires image1 as the first frame")
    if kind != "omni":
        return
    images = sum(kwargs.get(f"image{i}") is not None for i in range(1, 11))
    videos = sum(kwargs.get(f"video{i}") is not None for i in range(1, 6))
    urls = string_list(kwargs.get("video_urls", ""), "video_urls")
    if any(not http_url(url) for url in urls):
        raise SeedanceAPIError("video_urls must contain public HTTP(S) video links")
    videos += len(urls)
    image_ids = string_list(kwargs.get("image_element_ids", ""), "image_element_ids")
    video_ids = string_list(kwargs.get("video_element_ids", ""), "video_element_ids")
    voices = string_list(kwargs.get("voice_ids", ""), "voice_ids")
    if len(image_ids + video_ids) > 7 or len(video_ids) > 3 or len(voices) > 3:
        raise SeedanceAPIError("Kling 4 Omni supports at most 7 elements, 3 video elements and 3 voices")
    if len(set(image_ids + video_ids)) != len(image_ids + video_ids):
        raise SeedanceAPIError("Element IDs must not be repeated across image/video element lists")
    if videos > 5 or images + videos + len(image_ids + video_ids) > 15 or videos + len(video_ids) > 5:
        raise SeedanceAPIError("Kling 4 Omni: images/videos/elements <=15; videos/video elements <=5")


def video_payload(kind, kwargs, media):
    # Runtime media validation takes place before upload; payload checks also cover direct calls.
    validate_video(kind, kwargs)
    prompt_valid(kwargs.get("prompt", ""), required=kind != "i2v")
    images = list(media.get("images", []))
    videos = list(media.get("videos", []))
    if kind == "i2v" and not 1 <= len(images) <= 2:
        raise SeedanceAPIError("Kling 4 I2V requires one first frame and optional last frame")
    if kind == "omni" and (len(images) > 10 or len(videos) > 5):
        raise SeedanceAPIError("Kling 4 Omni supports at most 10 images and 5 videos")
    metadata = {"resolution": kwargs.get("resolution", "720p")}
    if kind != "i2v":
        metadata["ratio"] = kwargs.get("ratio", "16:9")
    watermark = kwargs.get("watermark", "api_default")
    if watermark != "api_default":
        metadata["watermark"] = watermark == "enabled"
    if kind == "omni":
        image_ids = string_list(kwargs.get("image_element_ids", ""), "image_element_ids")
        video_ids = string_list(kwargs.get("video_element_ids", ""), "video_element_ids")
        if len(images) + len(videos) + len(image_ids + video_ids) > 15 or len(videos) + len(video_ids) > 5:
            raise SeedanceAPIError("Kling 4 Omni combined material limit exceeded")
        if videos:
            metadata["video_url"] = videos
        if image_ids or video_ids:
            metadata["elementIds"] = image_ids + video_ids
        voices = string_list(kwargs.get("voice_ids", ""), "voice_ids")
        if voices:
            metadata["voiceIds"] = voices
    payload = {"model": f"kling-v4-{kind}", "seconds": str(kwargs.get("seconds", 3)), "metadata": metadata}
    if kwargs.get("prompt", "").strip():
        payload["prompt"] = kwargs["prompt"].strip()
    if images and kind != "t2v":
        payload["images"] = images
    return payload


def image_bytes(image, encode, element=False):
    shape = getattr(image, "shape", ())
    if len(shape) != 4 or shape[0] != 1:
        raise SeedanceAPIError("Each Kling 4 IMAGE socket requires exactly one image, not an image batch")
    data = encode(image)
    limit = 10 if element else 30
    if len(data) > limit * 1024 * 1024:
        raise SeedanceAPIError(f"Kling 4 image exceeds {limit} MB")
    if element:
        height, width = int(shape[1]), int(shape[2])
        if min(height, width) < 300 or not 0.4 <= width / height <= 2.5:
            raise SeedanceAPIError("Element images need a shortest edge >=300px and ratio between 1:2.5 and 2.5:1")
    return data


def probe_video(data, extension):
    try:
        import av
    except ImportError:
        av = None
    if av is not None:
        with av.open(BytesIO(data)) as container:
            stream = next(iter(container.streams.video), None)
            if stream is None:
                raise SeedanceAPIError("Kling 4 requires a decodable video stream")
            duration = (float(stream.duration * stream.time_base) if stream.duration is not None
                        else float(container.duration or 0) / 1000000)
            return {"width": stream.width, "height": stream.height, "duration": duration}
    executable = Path(_find_ffmpeg()).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if not executable.is_file():
        raise SeedanceAPIError("Video validation requires PyAV or ffprobe beside FFmpeg")
    with tempfile.TemporaryDirectory(prefix="seedance_kling4_probe_") as folder:
        path = Path(folder) / ("input." + extension)
        path.write_bytes(data)
        result = subprocess.run([str(executable), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                                capture_output=True, timeout=60, check=True)
        info = json.loads(result.stdout)
        stream = next((stream for stream in info.get("streams", []) if stream.get("codec_type") == "video"), None)
        if stream is None:
            raise SeedanceAPIError("Kling 4 requires a decodable video stream")
        return {"width": stream["width"], "height": stream["height"],
                "duration": float(stream.get("duration") or info.get("format", {}).get("duration") or 0)}


def validate_local_video(data, extension, element=False):
    if element and extension not in {"mp4", "mov"}:
        raise SeedanceAPIError("Video elements require MP4 or MOV")
    if len(data) > 50 * 1024 * 1024:
        raise SeedanceAPIError("Local upload is limited to 50 MB; use a public video URL for larger sources")
    info = probe_video(data, extension)
    if info["duration"] <= 0:
        raise SeedanceAPIError("Could not determine the video duration")
    if element and (not 3 <= info["duration"] <= 8 or (info["width"], info["height"]) not in {(1920, 1080), (1080, 1920)}):
        raise SeedanceAPIError("Video elements require 3-8 seconds, 1080p, 16:9 or 9:16")
    return info


def validate_element(kwargs, strict=False):
    name = kwargs.get("element_name", "")
    prompt = kwargs.get("prompt", "")
    if not isinstance(name, str) or not isinstance(prompt, str):
        raise SeedanceAPIError("Element name and description must be text")
    if len(name.strip()) > 20 or len(prompt.strip()) > 100:
        raise SeedanceAPIError("Element name is 1-20 characters; description is 1-100 characters")
    if strict and (not name.strip() or not prompt.strip()):
        raise SeedanceAPIError("Element name and description are required")
    mode = kwargs.get("reference_type", "image_refer")
    if mode not in {"image_refer", "video_refer"}:
        raise SeedanceAPIError("Unsupported element reference type")
    if not isinstance(kwargs.get("element_voice_id", ""), str):
        raise SeedanceAPIError("element_voice_id must be text")
    tags = string_list(kwargs.get("tag_list", ""), "tag_list")
    if any(tag not in TAGS for tag in tags):
        raise SeedanceAPIError("Element tags must be o_101 through o_108")
    if strict and mode == "image_refer":
        if kwargs.get("image1") is None or not any(kwargs.get(f"image{i}") is not None for i in (2, 3, 4)):
            raise SeedanceAPIError("Image elements require image1 (front) and 1-3 different reference images")
    if mode == "video_refer":
        url = kwargs.get("video_url", "")
        if not isinstance(url, str):
            raise SeedanceAPIError("video_url must be text")
        url = url.strip()
        if url and not http_url(url):
            raise SeedanceAPIError("Element video_url must be a public HTTP(S) video link")
        local = kwargs.get("input_video") is not None
        if local and url or (strict and not local and not url):
            raise SeedanceAPIError("Choose exactly one element video source: input_video or video_url")


def element_payload(kwargs, media):
    validate_element(kwargs)
    if not kwargs.get("element_name", "").strip() or not kwargs.get("prompt", "").strip():
        raise SeedanceAPIError("Element name and description are required")
    mode = kwargs.get("reference_type", "image_refer")
    metadata = {"elementName": kwargs["element_name"].strip(), "referenceType": mode}
    payload = {"model": "kling-v4-custom-element", "prompt": kwargs["prompt"].strip(), "metadata": metadata}
    if mode == "image_refer":
        images = list(media.get("images", []))
        if not 2 <= len(images) <= 4:
            raise SeedanceAPIError("Image elements require 2-4 ordered images")
        payload["images"] = images
    else:
        videos = list(media.get("videos", []))
        if len(videos) != 1:
            raise SeedanceAPIError("Video elements require exactly one video")
        metadata["video_url"] = videos
    if kwargs.get("element_voice_id", "").strip():
        metadata["elementVoiceId"] = kwargs["element_voice_id"].strip()
    tags = string_list(kwargs.get("tag_list", ""), "tag_list")
    if tags:
        metadata["tagList"] = tags
    return payload


def named_results(final):
    current = final
    for _ in range(5):
        if not isinstance(current, dict):
            break
        text = current.get("result_text")
        if isinstance(text, str) and text.strip():
            try:
                parsed = json.loads(text)
            except ValueError as exc:
                raise SeedanceAPIError("Kling 4 auxiliary result_text must contain JSON") from exc
            results = parsed.get("results") if isinstance(parsed, dict) else None
            if not isinstance(results, list):
                raise SeedanceAPIError("Kling 4 auxiliary response is missing its results array")
            values = {}
            for item in results:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    for field in ("text", "value", "url"):
                        if isinstance(item.get(field), str) and item[field].strip():
                            values[item["name"]] = item[field].strip()
                            break
            return values
        current = current.get("data")
    raise SeedanceAPIError("Kling 4 auxiliary response is missing result_text")


def validate_voice(kwargs, strict=False):
    name = kwargs.get("voice_name", "")
    if not isinstance(name, str) or (strict and not name.strip()):
        raise SeedanceAPIError("voice_name is required | 必须填写音色名称")
    mode = kwargs.get("source_mode", "audio")
    if mode not in {"audio", "video_id"}:
        raise SeedanceAPIError("Unsupported voice source mode")
    if mode == "video_id":
        if not isinstance(kwargs.get("video_id", ""), str):
            raise SeedanceAPIError("video_id must be text")
        if strict and not kwargs.get("video_id", "").strip():
            raise SeedanceAPIError("video_id is required for the video-ID voice source")
        return
    url = kwargs.get("audio_url", "")
    if not isinstance(url, str):
        raise SeedanceAPIError("audio_url must be text")
    url = url.strip()
    local = kwargs.get("audio") is not None
    if url and not http_url(url):
        raise SeedanceAPIError("audio_url must be a public HTTP(S) audio link")
    if local and url or (strict and not local and not url):
        raise SeedanceAPIError("Choose exactly one voice sample: local AUDIO or audio_url")
