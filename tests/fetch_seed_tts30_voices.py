"""Regenerate the Seed-TTS 3.0 voice catalog from the provider's LLMS table."""

import json
from pathlib import Path
import re

import requests

DOCS = "https://api.seedance.nz/docs/llms.txt"
OUT = Path(__file__).resolve().parents[1] / "core" / "data" / "seed_tts30_voices.json"


def voice_table(source):
    table = source.rsplit("## Seed-TTS 3.0 ", 1)[1].split("\n## ", 1)[0]
    rows = table.split("| --- | --- | --- |")[-1]
    by_name = {}
    for line in rows.splitlines():
        cells = line.strip().strip("|").split("|")
        if not line.startswith("|") or len(cells) != 3:
            continue
        for gender, text in zip(("female", "male"), cells[1:]):
            for short in re.findall(r"`([a-z0-9_]+)`", text):
                if short in by_name:
                    raise ValueError(f"Duplicate short voice name: {short}")
                by_name[short] = f"multi_{gender}_{short}_v3_uranus_bigtts"
    if len(by_name) != 502 or by_name.get("sarah") != "multi_female_sarah_v3_uranus_bigtts":
        raise ValueError("The official voice table changed; review before replacing the catalog")
    return by_name


if __name__ == "__main__":
    fetched = requests.get(DOCS, timeout=25)
    fetched.raise_for_status()
    data = voice_table(fetched.content.decode("utf-8"))
    OUT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Confirmed {len(data)} unique voices with official full IDs")
