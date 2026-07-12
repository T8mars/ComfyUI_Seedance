"""
Media conversion helpers: ComfyUI IMAGE / VIDEO / AUDIO objects -> bytes for
upload, plus error placeholder generation for skip_error mode.
"""

import os
import tempfile
import time
import uuid
from io import BytesIO
from typing import Any, Optional, Tuple

import numpy as np
import torch


# ---------------------------------------------------------------------------
# IMAGE (tensor [B,H,W,C] float 0-1) -> PNG bytes
# ---------------------------------------------------------------------------

def image_to_png_bytes(image: torch.Tensor) -> bytes:
    from PIL import Image

    if image is None:
        raise ValueError("image is None")
    arr = image.cpu().numpy() if hasattr(image, "cpu") else np.asarray(image)
    if arr.ndim == 4:
        arr = arr[0]
    if arr.ndim != 3:
        raise ValueError(f"Unexpected image tensor shape: {arr.shape}")
    if arr.max() <= 1.0:
        arr = (arr * 255).astype(np.uint8)
    else:
        arr = arr.astype(np.uint8)
    if arr.shape[2] == 4:
        pil = Image.fromarray(arr, mode="RGBA").convert("RGB")
    else:
        pil = Image.fromarray(arr, mode="RGB")
    buf = BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# VIDEO (comfy_api VideoInput / dict / path) -> mp4 bytes
# ---------------------------------------------------------------------------

def video_to_bytes(value: Any) -> Tuple[bytes, str]:
    """Extract raw video bytes from a ComfyUI VIDEO object.

    Returns (bytes, extension). Supports VideoFromFile (get_stream_source),
    objects with .path / .file_path / save_to(), dicts and plain paths.
    """
    def _read(path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    def _ext(path: str) -> str:
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        return ext or "mp4"

    if isinstance(value, str) and os.path.isfile(value):
        return _read(value), _ext(value)

    if isinstance(value, dict):
        path = value.get("file_path") or value.get("path")
        if path and os.path.isfile(path):
            return _read(path), _ext(path)

    if hasattr(value, "get_stream_source"):
        source = value.get_stream_source()
        if isinstance(source, str) and os.path.isfile(source):
            return _read(source), _ext(source)
        if hasattr(source, "read"):
            data = source.read()
            if hasattr(source, "seek"):
                try:
                    source.seek(0)
                except Exception:
                    pass
            return data, "mp4"

    for attr in ("path", "file_path"):
        path = getattr(value, attr, None)
        if isinstance(path, str) and os.path.isfile(path):
            return _read(path), _ext(path)

    if hasattr(value, "save_to"):
        tmp_path = os.path.join(tempfile.gettempdir(), f"seedance_upload_{uuid.uuid4().hex[:8]}.mp4")
        try:
            value.save_to(tmp_path)
            return _read(tmp_path), "mp4"
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    raise ValueError(
        f"Cannot extract video data from {type(value).__name__}; "
        "connect the output of a Load Video node."
    )


# ---------------------------------------------------------------------------
# AUDIO (dict with waveform/sample_rate) -> WAV bytes
# ---------------------------------------------------------------------------

def audio_to_wav_bytes(audio: dict) -> bytes:
    if not isinstance(audio, dict) or "waveform" not in audio:
        raise ValueError("Expected ComfyUI AUDIO dict with 'waveform' key")

    waveform = audio["waveform"]
    sample_rate = int(audio.get("sample_rate", 44100))

    if waveform.dim() == 3:
        waveform = waveform[0]
    if waveform.dim() == 1:
        waveform = waveform.unsqueeze(0)

    buf = BytesIO()
    try:
        import torchaudio
        torchaudio.save(buf, waveform.cpu(), sample_rate, format="wav")
        return buf.getvalue()
    except Exception:
        pass

    # Fallback: hand-rolled 16-bit PCM WAV via scipy
    import scipy.io.wavfile as wavfile

    data = waveform.cpu().numpy()
    if data.shape[0] <= 8:  # [channels, samples] -> [samples, channels]
        data = data.T
    data = (data * 32767).clip(-32768, 32767).astype(np.int16)
    wavfile.write(buf, sample_rate, data)
    return buf.getvalue()


def make_silent_audio(sample_rate: int = 24000, duration_seconds: float = 1.0) -> dict:
    """Build a tiny silent ComfyUI AUDIO object for skip_error workflows."""
    samples = max(1, int(sample_rate * duration_seconds))
    waveform = torch.zeros((1, 1, samples), dtype=torch.float32)
    return {"waveform": waveform, "sample_rate": int(sample_rate)}


# ---------------------------------------------------------------------------
# Error placeholders (for skip_error=True)
# ---------------------------------------------------------------------------

def _make_error_frame(error_msg: str, size: int = 512):
    """Draw the error message onto a dark-red PIL image."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (size, size), (80, 10, 10))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except Exception:
        font = ImageFont.load_default()

    margin = 20
    max_width = size - 2 * margin
    lines = []
    for paragraph in str(error_msg).split("\n"):
        words = paragraph.split()
        cur = ""
        for w in words:
            test = f"{cur} {w}".strip()
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] > max_width and cur:
                lines.append(cur)
                cur = w
            else:
                cur = test
        if cur:
            lines.append(cur)
    y = margin
    for line in lines:
        draw.text((margin, y), line, fill=(255, 200, 200), font=font)
        y += 22
        if y > size - margin:
            break
    return img


def make_error_video(error_msg: str) -> Any:
    """Build a 2-second single-frame mp4 carrying the error text, so that
    downstream Save Video / Preview nodes keep working under skip_error."""
    frame = _make_error_frame(error_msg)

    tmp_dir = os.path.join(tempfile.gettempdir(), "seedance_error_videos")
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        import av

        video_path = os.path.join(tmp_dir, f"error_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp4")
        with av.open(video_path, "w") as container:
            stream = container.add_stream("h264", rate=2)
            stream.width = frame.width
            stream.height = frame.height
            stream.pix_fmt = "yuv420p"
            for _ in range(4):  # 2 seconds at 2 fps
                av_frame = av.VideoFrame.from_image(frame)
                for packet in stream.encode(av_frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)

        try:
            from comfy_api.input_impl import VideoFromFile
            return VideoFromFile(video_path)
        except ImportError:
            return video_path
    except Exception:
        # No encoder available: fall back to a PNG path dict.
        img_path = os.path.join(tmp_dir, f"error_{int(time.time())}_{uuid.uuid4().hex[:6]}.png")
        frame.save(img_path)
        return {"file_path": img_path, "format": "png"}
