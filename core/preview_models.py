"""Request contracts and reference limits for HY Preview and Muse."""

from .client import SeedanceAPIError
from .media import image_to_png_bytes


HY_MODEL = "zhenzhen-image-hy-v3.5-preview"
MUSE_IMAGE_MODEL = "zhenzhen-image-muse"
MUSE_VIDEO_MODEL = "zhenzhen-video-muse"
HY_SIZES = ["auto", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "custom"]
HY_RESOLUTIONS = ["1K", "2K", "4K"]
MUSE_SIZES = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"]
MUSE_REFERENCE_BYTES = 11 * 1024 * 1024


def references(kwargs, maximum):
    result = []
    for name, value in kwargs.items():
        if not name.startswith("image") or not name[5:].isdigit() or value is None:
            continue
        index = int(name[5:])
        if not 1 <= index <= maximum:
            raise SeedanceAPIError(f"At most {maximum} reference images are supported")
        result.append((index, value))
    return sorted(result)


def encode_references(kwargs, maximum, per_file=50 * 1024 * 1024, total=None):
    encoded = []
    for index, image in references(kwargs, maximum):
        shape = getattr(image, "shape", ())
        if len(shape) != 4 or shape[0] != 1 or shape[-1] not in (3, 4) or min(shape[1:3]) < 1:
            raise SeedanceAPIError("Each reference socket requires exactly one IMAGE, not a batch")
        data = image_to_png_bytes(image)
        if len(data) > per_file:
            raise SeedanceAPIError(f"Reference image {index} exceeds the file size limit")
        encoded.append((index, data))
    if total is not None and sum(len(data) for _, data in encoded) > total:
        raise SeedanceAPIError("Muse reference images must total at most 11 MiB")
    return encoded


def validate(kind, kwargs, strict=False):
    prompt = kwargs.get("prompt")
    if prompt is not None and not isinstance(prompt, str):
        return "prompt must be text"
    if strict and not (prompt or "").strip():
        return "A non-empty prompt is required | 必须填写提示词"
    try:
        references(kwargs, 5 if kind == "hy" else 9)
    except SeedanceAPIError as exc:
        return str(exc)
    size = kwargs.get("size", "auto")
    if size not in (HY_SIZES if kind == "hy" else MUSE_SIZES):
        return "Unsupported size | 不支持的画幅"
    if kind != "hy":
        return True
    resolution = kwargs.get("resolution", "1K")
    if not isinstance(resolution, str) or resolution.upper() not in HY_RESOLUTIONS:
        return "HY resolution must be 1K, 2K or 4K"
    if size == "custom":
        # Missing queue-time values may be unresolved widget connections.
        default = 1024 if strict else None
        width, height = kwargs.get("width", default), kwargs.get("height", default)
        if any(value is not None and (not isinstance(value, int) or isinstance(value, bool) or not 256 <= value <= 8192)
               for value in (width, height)):
            return "HY width and height must be integers from 256 to 8192"
        if width is not None and height is not None and width * height > 8294400:
            return "HY custom dimensions must not exceed 8,294,400 pixels"
    if "negative_prompt" in kwargs and not isinstance(kwargs["negative_prompt"], str):
        return "negative_prompt must be text"
    seed = kwargs.get("seed", 0)
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        return "HY seed must be a nonnegative integer"
    return True


def payload(kind, kwargs, images):
    valid = validate(kind, kwargs, strict=True)
    if valid is not True:
        raise SeedanceAPIError(valid)
    maximum = 5 if kind == "hy" else 9
    if len(images) > maximum:
        raise SeedanceAPIError(f"At most {maximum} reference images are supported")
    model = {"hy": HY_MODEL, "muse_image": MUSE_IMAGE_MODEL, "muse_video": MUSE_VIDEO_MODEL}[kind]
    result = {"model": model, "prompt": kwargs["prompt"].strip(), "n": 1}
    if kind == "hy":
        result["resolution"] = kwargs.get("resolution", "1K").upper()
        result["seed"] = kwargs.get("seed", 0)
        if kwargs.get("size", "auto") == "custom":
            result.update(width=kwargs.get("width", 1024), height=kwargs.get("height", 1024))
        else:
            result["size"] = kwargs.get("size", "auto")
        if kwargs.get("negative_prompt", "").strip():
            result["negative_prompt"] = kwargs["negative_prompt"].strip()
    else:
        result["size"] = kwargs.get("size", "auto")
        if kind == "muse_video":
            result.update(duration=10, resolution="720p", audio=True)
    if images:
        result["images"] = list(images)
    return result
