"""Save original image bytes and decode complete animations for ComfyUI."""

import io
import os
from pathlib import Path
import uuid

import numpy as np
from PIL import Image, ImageSequence
import torch

from .client import SeedanceAPIError, _ResultDownloadLimitError, _download_and_decode_image


def output_target(prefix):
    try:
        import folder_paths
        root = Path(folder_paths.get_output_directory()).resolve()
    except ImportError:
        root = Path(os.getenv("SEEDANCE_OUTPUT_DIR", "output")).resolve()
    if not isinstance(prefix, str) or not prefix.strip():
        raise SeedanceAPIError("filename_prefix must not be empty")
    relative = Path(prefix.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts or ":" in prefix:
        raise SeedanceAPIError("filename_prefix must stay inside the ComfyUI output directory")
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SeedanceAPIError("filename_prefix escapes the output directory") from exc
    if target == root or not target.name:
        raise SeedanceAPIError("filename_prefix requires a file name")
    return root, target


def decode_original(data, require_gif=False):
    with Image.open(io.BytesIO(data)) as source:
        actual_format = (source.format or "").upper()
        count = getattr(source, "n_frames", 1)
        if require_gif and (actual_format != "GIF" or count < 2):
            raise SeedanceAPIError("GIF mode requires an actual animated GIF result; upstream returned a static image")
        extension = {"GIF": "gif", "PNG": "png", "JPEG": "jpg", "WEBP": "webp"}.get(actual_format)
        if extension is None:
            raise SeedanceAPIError("Unsupported image result format")
        # Bound local decoded memory independently of the API's canvas limits.
        if source.width * source.height * count > 64 * 1024 * 1024:
            raise _ResultDownloadLimitError("Animation exceeds the local decoded-pixel safety limit")
        frames, durations = [], []
        for frame in ImageSequence.Iterator(source):
            frames.append(torch.from_numpy(np.array(frame.convert("RGB"), dtype=np.float32) / 255.0))
            durations.append(int(frame.info.get("duration", 0)))
        return torch.stack(frames), extension, durations


def download_original(url, prefix="seedance/g26", require_gif=False, logger_prefix="Image G 2.6"):
    root, target = output_target(prefix)

    def decode(data):
        image, extension, durations = decode_original(data, require_gif)
        return data, image, extension, durations

    data, image, extension, durations = _download_and_decode_image(
        url, decode, 60, 3, logger_prefix, "Original image")
    target.parent.mkdir(parents=True, exist_ok=True)
    destination = target.with_name(f"{target.name}_{uuid.uuid4().hex}.{extension}")
    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        with partial.open("xb") as stream:
            stream.write(data)
        os.replace(str(partial), str(destination))
    finally:
        partial.unlink(missing_ok=True)
    entry = {"filename": destination.name, "subfolder": destination.parent.relative_to(root).as_posix(), "type": "output"}
    if entry["subfolder"] == ".":
        entry["subfolder"] = ""
    return image, str(destination), entry, durations, extension
