"""Regenerate the factual voice catalog from the public Seedance playground."""

import ast
import hashlib
import json
from pathlib import Path
import re

import requests


SOURCE = "https://api.seedance.nz/static/js/async/42695.dd0817052a.js"
OFFICIAL = "https://docs.volcengine.com/docs/doubao-voice/tone-list-3?lang=zh"


def main():
    response = requests.get(SOURCE, timeout=60)
    response.raise_for_status()
    match = re.search(r"JSON\.parse\(('(?:\\.|[^'\\])*')\)", response.text)
    if not match:
        raise RuntimeError("Published catalog layout changed; do not guess voice IDs")
    voices = json.loads(ast.literal_eval(match[1]))
    if not isinstance(voices, list) or len(voices) < 470:
        raise RuntimeError("Unexpected voice catalog size")
    if len({voice["id"] for voice in voices}) != len(voices):
        raise RuntimeError("Duplicate voice IDs")
    if any("uranus" not in voice["id"] or not voice.get("name") for voice in voices):
        raise RuntimeError("Catalog contains a non-2.0 or unnamed voice")
    result = {"official_source": OFFICIAL, "published_catalog": SOURCE,
              "source_sha256": hashlib.sha256(response.content).hexdigest(), "voices": voices}
    target = Path(__file__).resolve().parents[1] / "core" / "data" / "doubao_tts_voices.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(f"Verified and extracted {len(voices)} unique 2.0 voices")


if __name__ == "__main__":
    main()
