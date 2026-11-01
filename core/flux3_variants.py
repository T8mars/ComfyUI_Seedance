"""Pure validation and payload helpers for the four FLUX 3 Image variants."""

from collections.abc import Mapping

from .client import SeedanceAPIError


__all__ = ["MODELS", "RESOLUTIONS", "RATIOS", "validate", "payload"]

MODELS = [
    "flux-3-image-t2i",
    "flux-3-image-i2i",
    "flux-3-image-klein-t2i",
    "flux-3-image-klein-i2i",
]
RESOLUTIONS = ["768sq", "1k", "1.5k", "2k", "4k"]
RATIOS = [
    "auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3",
    "5:4", "4:5", "2:1", "1:2", "21:9", "9:21", "5:7", "7:5",
]


def _integer(value, minimum, maximum):
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


def _validate(kwargs, strict, require_image_connection):
    if not isinstance(kwargs, Mapping):
        return "FLUX 3 Image arguments must be a mapping"
    model = kwargs.get("model", MODELS[0])
    if model not in MODELS:
        return "Unsupported FLUX 3 Image model"
    prompt = kwargs.get("prompt")
    if prompt is not None and not isinstance(prompt, str):
        return "FLUX 3 Image prompt must be text"
    if strict and (prompt is None or not prompt.strip()):
        return "FLUX 3 Image requires a prompt"
    if kwargs.get("resolution", "1k") not in RESOLUTIONS:
        return "Unsupported FLUX 3 Image resolution"
    if kwargs.get("aspect_ratio", "auto") not in RATIOS:
        return "Unsupported FLUX 3 Image aspect_ratio"
    if not _integer(kwargs.get("safety_tolerance", 2), 0, 4):
        return "safety_tolerance must be an integer from 0 to 4"

    if "-klein-" in model:
        if not _integer(kwargs.get("seed", 0), 0, 2147483647):
            return "seed must be an integer from 0 to 2147483647"
        if not _integer(kwargs.get("steps", 0), 0, 16):
            return "steps must be 0 (API default) or an integer from 1 to 16"
        if kwargs.get("output_format", "api_default") not in ("api_default", "jpeg", "png"):
            return "output_format must be api_default, jpeg or png"
    elif not isinstance(kwargs.get("grounding", True), bool):
        return "grounding must be a boolean"

    connected = any(kwargs.get(f"image{index}") is not None for index in range(1, 11))
    if model.endswith("-t2i") and connected:
        return "FLUX 3 Image T2I does not accept connected images"
    if strict and require_image_connection and model.endswith("-i2i") and not connected:
        return "FLUX 3 Image I2I requires at least one connected image1..image10"
    return True


def validate(kwargs, strict=False):
    """Return True or an error string; defer unresolved required inputs unless strict."""
    return _validate(kwargs, strict, require_image_connection=True)


def payload(kwargs, images):
    """Build a request from uploaded images, without requiring original I2I sockets."""
    validation = _validate(kwargs, strict=True, require_image_connection=False)
    if validation is not True:
        raise SeedanceAPIError(validation)
    if not isinstance(images, (list, tuple)):
        raise SeedanceAPIError("images must be an array of uploaded image strings")
    model = kwargs.get("model", MODELS[0])
    if model.endswith("-t2i") and len(images):
        raise SeedanceAPIError("FLUX 3 Image T2I does not accept uploaded images")
    if model.endswith("-i2i") and not 1 <= len(images) <= 10:
        raise SeedanceAPIError("FLUX 3 Image I2I requires 1 to 10 uploaded images")
    if any(not isinstance(image, str) or not image.strip() for image in images):
        raise SeedanceAPIError("images must contain non-empty uploaded image strings")

    result = {
        "model": model,
        "prompt": kwargs["prompt"].strip(),
        "resolution": kwargs.get("resolution", "1k"),
        "aspect_ratio": kwargs.get("aspect_ratio", "auto"),
        "safety_tolerance": kwargs.get("safety_tolerance", 2),
    }
    if "-klein-" in model:
        result["seed"] = kwargs.get("seed", 0)
        steps = kwargs.get("steps", 0)
        if steps:
            result["metadata"] = {"steps": steps}
        output_format = kwargs.get("output_format", "api_default")
        if output_format != "api_default":
            result["output_format"] = output_format
    else:
        result["grounding"] = kwargs.get("grounding", True)
    if model.endswith("-i2i"):
        result["images"] = list(images)
    return result
