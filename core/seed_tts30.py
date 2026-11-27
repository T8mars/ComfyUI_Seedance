"""Seed-TTS 3.0 request schema and official voice IDs."""

import json
from pathlib import Path

from .client import SeedanceAPIError
from .nov21_models import text


MODEL = "bytedance-seed/seed-tts-3-0"
DEFAULT_VOICE = "sarah"
SAMPLE_RATE = 24000
_VOICE_MAP = json.loads((Path(__file__).parent / "data" / "seed_tts30_voices.json").read_text(encoding="utf-8"))
VOICES = [DEFAULT_VOICE, *(name for name in _VOICE_MAP if name != DEFAULT_VOICE)]
_FULL_IDS = frozenset(_VOICE_MAP.values())


def payload(kwargs, strict=False):
    prompt = text(kwargs, "prompt", maximum=5000, required=strict)
    instructions = text(kwargs, "instructions", maximum=1000).strip()
    override = text(kwargs, "voice_id").strip()
    voice = (override or text(kwargs, "voice", default=DEFAULT_VOICE)).strip().lower()
    if voice not in _VOICE_MAP and voice not in _FULL_IDS:
        raise SeedanceAPIError("Choose a Seed-TTS 3.0 voice or enter a documented voice ID")
    speed = kwargs.get("speed", 1.0)
    if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not 0.5 <= speed <= 2:
        raise SeedanceAPIError("Seed-TTS 3.0 speed must be between 0.5 and 2")
    metadata = {"voice": voice, "speed": float(speed), "format": "wav"}
    if instructions:
        metadata["instructions"] = instructions
    return {"model": MODEL, "prompt": prompt, "metadata": metadata}
