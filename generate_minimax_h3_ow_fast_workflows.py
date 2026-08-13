"""Generate safe example workflows for the latest MiniMax H3 OW Fast models."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EXAMPLES = ROOT / "examples"
BASE_PATH = EXAMPLES / "minimax-h3-ow-fast-i2v图生视频.json"

AUDIO_MODELS = (
    (
        "minimax-h3-ow-fl2va-audio-drive-fast",
        "MiniMax H3 OW FL2VA 音频驱动 Fast",
        "minimax-h3-ow-fl2va-audio-drive-fast音频驱动视频.json",
        "Animate the reference image with expressive motion driven by the connected audio",
    ),
    (
        "minimax-h3-ow-ref2va-audio-drive-fast",
        "MiniMax H3 OW REF2VA 音频驱动 Fast",
        "minimax-h3-ow-ref2va-audio-drive-fast参考音频驱动视频.json",
        "Keep the reference subject consistent and drive the performance with the connected audio",
    ),
)


def _node(workflow: dict, node_id: int) -> dict:
    return next(item for item in workflow["nodes"] if item["id"] == node_id)


def _set_common(generator: dict, model: str, title: str, prompt: str) -> None:
    generator["title"] = title
    generator["inputs"].append({
        "name": "audio", "shape": 7, "type": "AUDIO", "link": None,
    })
    generator["widgets_values"] = [
        model, prompt, "5", "480p", "16:9", False, 0, "fixed",
    ]


def _audio_loader() -> dict:
    return {
        "id": 5,
        "type": "LoadAudio",
        "pos": [20, 470],
        "size": [300, 100],
        "flags": {},
        "order": 2,
        "mode": 0,
        "inputs": [],
        "outputs": [{"name": "AUDIO", "type": "AUDIO", "links": [4]}],
        "properties": {
            "cnr_id": "comfy-core",
            "Node name for S&R": "LoadAudio",
        },
        "widgets_values": ["example.wav", None, None],
    }


def build_audio_workflow(model: str, title: str, filename: str, prompt: str) -> None:
    workflow = json.loads(BASE_PATH.read_text(encoding="utf-8"))
    workflow["id"] = f"{model}-workflow"
    workflow["last_node_id"] = 5
    workflow["last_link_id"] = 4
    generator = _node(workflow, 3)
    _set_common(generator, model, title, prompt)
    generator["inputs"][-1]["link"] = 4
    generator["size"] = [500, 480]
    _node(workflow, 4)["widgets_values"][0] = f"video/{model}"
    _node(workflow, 3)["order"] = 3
    _node(workflow, 4)["order"] = 4
    workflow["nodes"].insert(2, _audio_loader())
    workflow["links"].append([4, 5, 0, 3, 10, "AUDIO"])
    (EXAMPLES / filename).write_text(
        json.dumps(workflow, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_t2v_workflow() -> None:
    workflow = json.loads(BASE_PATH.read_text(encoding="utf-8"))
    model = "minimax-h3-ow-t2v-fast"
    workflow["id"] = f"{model}-workflow"
    workflow["nodes"] = [item for item in workflow["nodes"] if item["id"] != 2]
    workflow["links"] = [item for item in workflow["links"] if item[0] != 2]
    generator = _node(workflow, 3)
    for input_item in generator["inputs"]:
        if input_item["name"] == "image1":
            input_item["link"] = None
    _set_common(
        generator,
        model,
        "MiniMax H3 OW 文生视频 Fast",
        "A paper kite floats through warm sunset light with smooth cinematic camera movement",
    )
    generator["size"] = [500, 420]
    generator["order"] = 1
    _node(workflow, 4)["order"] = 2
    _node(workflow, 4)["widgets_values"][0] = f"video/{model}"
    (EXAMPLES / "minimax-h3-ow-t2v-fast文生视频.json").write_text(
        json.dumps(workflow, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    for spec in AUDIO_MODELS:
        build_audio_workflow(*spec)
    build_t2v_workflow()


if __name__ == "__main__":
    main()
