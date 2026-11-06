"""Local GIF export with lossless original-file copying and frame encoding."""

import json
import math
import os
from pathlib import Path
import shutil
import uuid

import numpy as np
from PIL import Image
import torch

from .client import SeedanceAPIError
from .image_artifacts import output_target


MAX_DECODED_PIXELS = 64 * 1024 * 1024


def inspect_gif(path):
    with Image.open(path) as image:
        if image.format != "GIF":
            raise SeedanceAPIError("The original file must be a GIF, not a renamed static image")
        count = getattr(image, "n_frames", 1)
        if image.width * image.height * count > MAX_DECODED_PIXELS:
            raise SeedanceAPIError("GIF exceeds the local decoded-pixel safety limit")
        durations = []
        for index in range(count):
            image.seek(index)
            image.load()
            durations.append(int(image.info.get("duration", 0)))
        return count, durations


def frame_durations(value, count, fps):
    if not isinstance(fps, (int, float)) or isinstance(fps, bool) or not math.isfinite(fps) or not .1 <= fps <= 100:
        raise SeedanceAPIError("fps must be a finite number from 0.1 to 100")
    if value is None or value == "":
        return [max(10, round(100 / fps) * 10)] * count
    if not isinstance(value, str):
        raise SeedanceAPIError("durations_json must be a JSON string")
    try:
        values = json.loads(value)
    except ValueError as exc:
        raise SeedanceAPIError("durations_json must contain a JSON duration array") from exc
    if not isinstance(values, list):
        raise SeedanceAPIError("durations_json must contain a JSON duration array")
    if values and all(isinstance(item, list) for item in values):
        values = [duration for group in values for duration in group]
    if len(values) != count or any(not isinstance(item, int) or isinstance(item, bool) or not 10 <= item <= 655350 for item in values):
        raise SeedanceAPIError("durations_json needs one integer duration (10-655350 ms) per frame")
    return [max(10, round(item / 10) * 10) for item in values]


def save_gif(images=None, source_path="", durations_json="", filename_prefix="seedance/saved_gif",
             source_mode="auto", fps=10.0, loop=0):
    if source_mode not in ("auto", "original", "frames"):
        raise SeedanceAPIError("source_mode must be auto, original or frames")
    if source_path is not None and not isinstance(source_path, str):
        raise SeedanceAPIError("source_path must be a local GIF file path")
    source_path = (source_path or "").strip()
    original = source_mode == "original" or (source_mode == "auto" and bool(source_path))
    root, target = output_target(filename_prefix)
    source = None
    frames = []
    if original:
        if not source_path or source_path.lower().startswith(("http://", "https://")):
            raise SeedanceAPIError("Connect a local GIF path to source_path for original-file saving")
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise SeedanceAPIError("Original GIF file does not exist")
        if source.stat().st_size > 256 * 1024 * 1024:
            raise SeedanceAPIError("Original GIF exceeds the local 256 MiB file safety limit")
    else:
        if not torch.is_tensor(images) or images.ndim != 4 or images.shape[-1] not in (3, 4) or min(images.shape[:3]) < 1:
            raise SeedanceAPIError("Connect IMAGE frames with shape [frames, height, width, 3 or 4]")
        if math.prod(images.shape[:3]) > MAX_DECODED_PIXELS:
            raise SeedanceAPIError("Frames exceed the local decoded-pixel safety limit")
        if not isinstance(loop, int) or isinstance(loop, bool) or not 0 <= loop <= 65535:
            raise SeedanceAPIError("loop must be an integer from 0 to 65535; 0 loops forever")
        durations = frame_durations(durations_json, images.shape[0], fps)
        for tensor in images:
            if not torch.isfinite(tensor).all():
                raise SeedanceAPIError("IMAGE frames contain non-finite pixel values")
            pixels = tensor.detach().float().cpu().numpy()
            frames.append(Image.fromarray(np.rint(np.clip(pixels, 0, 1) * 255).astype(np.uint8)))
    target.parent.mkdir(parents=True, exist_ok=True)
    destination = target.with_name(f"{target.name}_{uuid.uuid4().hex}.gif")
    partial = destination.with_suffix(".gif.part")
    try:
        with partial.open("xb") as stream:
            if original:
                with source.open("rb") as reader:
                    shutil.copyfileobj(reader, stream)
            else:
                frames[0].save(stream, format="GIF", save_all=True, append_images=frames[1:],
                               duration=durations, loop=loop, disposal=2, optimize=False)
        # Verify exactly the bytes being published, including every GIF frame.
        count, actual_durations = inspect_gif(partial)
        os.replace(str(partial), str(destination))
    finally:
        partial.unlink(missing_ok=True)
    subfolder = destination.parent.relative_to(root).as_posix()
    entry = {"filename": destination.name, "subfolder": "" if subfolder == "." else subfolder, "type": "output"}
    return str(destination), entry, count, actual_durations
