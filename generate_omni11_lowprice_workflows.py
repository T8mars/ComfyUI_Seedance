"""Generate safe Omni 1.1 Flash Lowprice workflows from the shared contract."""

from __future__ import annotations

import json
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EXAMPLES = ROOT / "examples"
SOURCE_PREFIX = "zhenzhen-video-g-omni-flash-lowprice"
TARGET_PREFIX = "zhenzhen-video-g-omni-1.1-flash-lowprice"
SOURCE_NODE = "Zhenzhen_Video_G_Omni_Flash_Lowprice"
TARGET_NODE = "Zhenzhen_Video_G_Omni_1_1_Flash_Lowprice"
WORKFLOW_SUFFIXES = (
    "文生视频.json",
    "首帧生视频.json",
    "三图参考生视频.json",
    "参考视频生成.json",
)


def _replace_strings(value):
    if isinstance(value, str):
        return (
            value.replace(SOURCE_NODE, TARGET_NODE)
            .replace("Omni Flash Lowprice", "Omni 1.1 Flash Lowprice")
        )
    if isinstance(value, list):
        return [_replace_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: _replace_strings(item) for key, item in value.items()}
    return value


def main():
    for suffix in WORKFLOW_SUFFIXES:
        source_path = EXAMPLES / f"{SOURCE_PREFIX}{suffix}"
        target_name = f"{TARGET_PREFIX}{suffix}"
        workflow = _replace_strings(
            json.loads(source_path.read_text(encoding="utf-8"))
        )
        workflow["id"] = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"ComfyUI_Seedance/{target_name}")
        )
        (EXAMPLES / target_name).write_text(
            json.dumps(workflow, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
