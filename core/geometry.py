"""ComfyUI-compatible GLB helpers with a lightweight test fallback."""

from __future__ import annotations

import json
import shutil
import struct
from io import BytesIO
from pathlib import Path
from typing import IO, Union


try:
    from comfy_api.latest import Types as _ComfyTypes
except ImportError:
    _ComfyTypes = None


class _FallbackFile3D:
    """Minimal File3D implementation used outside a full ComfyUI runtime."""

    def __init__(self, source: Union[str, IO[bytes]], file_format: str = ""):
        self._source = source
        self._format = file_format.lstrip(".").lower() or self._infer_format()

    def _infer_format(self) -> str:
        if isinstance(self._source, str):
            return Path(self._source).suffix.lstrip(".").lower()
        return ""

    @property
    def format(self) -> str:
        return self._format

    @property
    def is_disk_backed(self) -> bool:
        return isinstance(self._source, str)

    def get_source(self):
        if hasattr(self._source, "seek"):
            self._source.seek(0)
        return self._source

    def get_bytes(self) -> bytes:
        if isinstance(self._source, str):
            return Path(self._source).read_bytes()
        self._source.seek(0)
        return self._source.read()

    def save_to(self, path: str) -> str:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(self._source, str):
            source = Path(self._source)
            if source.resolve() != destination.resolve():
                shutil.copy2(source, destination)
        else:
            self._source.seek(0)
            destination.write_bytes(self._source.read())
        return str(destination)


File3D = _ComfyTypes.File3D if _ComfyTypes is not None else _FallbackFile3D


def file3d_from_path(path: str):
    return File3D(str(path), file_format="glb")


def minimal_glb_bytes(label: str = "Seedance placeholder") -> bytes:
    document = {
        "asset": {"version": "2.0", "generator": "ComfyUI_Seedance"},
        "scene": 0,
        "scenes": [{"nodes": []}],
        "nodes": [],
        "extras": {"message": str(label or "Seedance placeholder")[:240]},
    }
    json_chunk = json.dumps(
        document, ensure_ascii=True, separators=(",", ":")
    ).encode("utf-8")
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    total_length = 12 + 8 + len(json_chunk)
    return (
        struct.pack("<4sII", b"glTF", 2, total_length)
        + struct.pack("<II", len(json_chunk), 0x4E4F534A)
        + json_chunk
    )


def placeholder_file3d(message: str = "Seedance 3D generation failed"):
    return File3D(BytesIO(minimal_glb_bytes(message)), file_format="glb")


__all__ = [
    "File3D",
    "file3d_from_path",
    "minimal_glb_bytes",
    "placeholder_file3d",
]
