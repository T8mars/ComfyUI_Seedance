"""Seedance gateway contract for Ideogram 4.6's two image models."""

from .client import SeedanceAPIError
from .nov21_models import boolean, choice, public_url, text
from .preview_models import references


TEXT_MODEL = "ideogram-v4.6"
EDIT_MODEL = "ideogram-v4.6-edit"
RATIOS = ["1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16"]
RESOLUTIONS = ["1k", "2k", "4k"]
QUALITIES = ["medium", "very_low", "low", "high"]
BACKGROUNDS = ["opaque", "transparent"]
PRECISIONS = ["regular", "high"]
MAX_IMAGES = 5
MASK_MAX_IMAGES = 4
SOURCE_RATIO = "original"


def plan(kwargs, edit=False):
    prompt = text(kwargs, "prompt", maximum=10000, required=True).strip()
    quality = choice(kwargs, "quality", QUALITIES)
    resolution = choice(kwargs, "resolution", RESOLUTIONS)
    if resolution == "4k" and quality == "very_low":
        raise SeedanceAPIError("very_low supports only 1k and 2k | very_low 仅支持 1k 和 2k")
    body = {"model": EDIT_MODEL if edit else TEXT_MODEL, "prompt": prompt,
            "resolution": resolution, "quality": quality}
    if not edit:
        if references(kwargs, MAX_IMAGES):
            raise SeedanceAPIError("Ideogram 4.6 text-to-image does not accept references")
        body.update(aspect_ratio=choice(kwargs, "aspect_ratio", RATIOS),
                    background=choice(kwargs, "background", BACKGROUNDS),
                    enable_prompt_expansion=boolean(kwargs, "enable_prompt_expansion"))
        return body

    mask_url = text(kwargs, "mask_url").strip()
    if mask_url and not public_url(mask_url):
        raise SeedanceAPIError("mask_url requires a public HTTP(S) URL | 蒙版需要公开 HTTP(S) 地址")
    refs = references(kwargs, MAX_IMAGES)
    if not refs or refs[0][0] != 1:
        raise SeedanceAPIError("Connect the base image to image1 | 请将待编辑原图连接到 image1")
    if mask_url and len(refs) > MASK_MAX_IMAGES:
        raise SeedanceAPIError("A mask allows at most 4 images total | 使用蒙版时最多 4 张（原图 + 3 张参考图）")
    precision = choice(kwargs, "edit_precision", PRECISIONS)
    ratio = choice(kwargs, "aspect_ratio", [SOURCE_RATIO, *RATIOS])
    if mask_url:
        body["mask_url"] = mask_url
    if ratio != SOURCE_RATIO and precision != "high" and not mask_url:
        body["aspect_ratio"] = ratio
    body["edit_precision"] = precision
    return body
