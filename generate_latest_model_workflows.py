"""Generate safe example workflows for the latest image and audio nodes."""

from __future__ import annotations

import json
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EXAMPLES = ROOT / "examples"
PLUGIN = "T8mars/ComfyUI_Seedance"


def _node(node_id, node_type, pos, size, order, inputs, outputs, widgets, title=None):
    node = {
        "id": node_id,
        "type": node_type,
        "pos": list(pos),
        "size": list(size),
        "flags": {},
        "order": order,
        "mode": 0,
        "inputs": inputs,
        "outputs": outputs,
        "properties": {"Node name for S&R": node_type},
        "widgets_values": widgets,
    }
    if node_type.startswith((
        "Seedance_", "Zhenzhen_", "Wan_", "Qwen3_", "Minimax_", "Mureka_",
    )):
        node["properties"]["aux_id"] = PLUGIN
    if title:
        node["title"] = title
    return node


def _config(link_id, target_id, target_slot):
    node = _node(
        1, "Seedance_Config", (40, 300), (300, 82), 0, [],
        [{"name": "api_config", "type": "SEEDANCE_CONFIG", "links": [link_id]}],
        ["https://api.seedance.nz", ""],
    )
    link = [link_id, 1, 0, target_id, target_slot, "SEEDANCE_CONFIG"]
    return node, link


def _workflow(filename, nodes, links):
    workflow = {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"ComfyUI_Seedance/{filename}")),
        "revision": 0,
        "last_node_id": max(node["id"] for node in nodes),
        "last_link_id": max((link[0] for link in links), default=0),
        "nodes": nodes,
        "links": links,
        "groups": [],
        "config": {},
        "extra": {
            "frontendVersion": "1.45.20",
            "ds": {"scale": 1, "offset": [80, 40]},
        },
        "version": 0.4,
    }
    (EXAMPLES / filename).write_text(
        json.dumps(workflow, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _image_workflow(filename, node_type, title, widgets, input_count=0, connect_image=False):
    generator_id = 3 if connect_image else 2
    save_id = generator_id + 1
    config_link_id = 2 if connect_image else 1
    image_link_id = 1 if connect_image else None
    output_link_id = config_link_id + 1
    config, config_link = _config(config_link_id, generator_id, input_count)
    nodes = [config]
    links = []
    if connect_image:
        nodes.append(_node(
            2, "LoadImage", (40, 60), (300, 310), 1, [],
            [
                {"name": "IMAGE", "type": "IMAGE", "links": [image_link_id]},
                {"name": "MASK", "type": "MASK", "links": None},
            ],
            ["example.png", "image"],
            "选择参考图片",
        ))
        links.append([image_link_id, 2, 0, generator_id, 0, "IMAGE"])
    generator_inputs = [
        {"name": f"image{index}", "shape": 7, "type": "IMAGE", "link": image_link_id if index == 1 and connect_image else None}
        for index in range(1, input_count + 1)
    ]
    generator_inputs.append({
        "name": "api_config", "shape": 7, "type": "SEEDANCE_CONFIG", "link": config_link_id,
    })
    nodes.append(_node(
        generator_id, node_type, (400, 80), (450, 380), 2 if connect_image else 1,
        generator_inputs,
        [
            {"name": "image", "type": "IMAGE", "links": [output_link_id]},
            {"name": "image_url", "type": "STRING", "links": None},
            {"name": "task_id", "type": "STRING", "links": None},
            {"name": "response", "type": "STRING", "links": None},
        ],
        widgets,
        title,
    ))
    nodes.append(_node(
        save_id, "SaveImage", (930, 120), (270, 270), 3 if connect_image else 2,
        [{"name": "images", "type": "IMAGE", "link": output_link_id}],
        [{"name": "images", "type": "IMAGE", "links": None}],
        [Path(filename).stem],
    ))
    links.extend([config_link, [output_link_id, generator_id, 0, save_id, 0, "IMAGE"]])
    _workflow(filename, nodes, links)


def _audio_workflow(filename, node_type, title, widgets, clone=False, list_output=False):
    generator_id = 3 if clone else 2
    save_id = generator_id + 1
    config_slot = 1 if clone else 0
    config_link_id = 2 if clone else 1
    audio_link_id = 1 if clone else None
    output_link_id = config_link_id + 1
    config, config_link = _config(config_link_id, generator_id, config_slot)
    nodes = [config]
    links = []
    if clone:
        nodes.append(_node(
            2, "LoadAudio", (40, 60), (300, 120), 1, [],
            [{"name": "AUDIO", "type": "AUDIO", "links": [audio_link_id]}],
            ["example.wav", None, ""],
            "选择10秒以上参考音频",
        ))
        links.append([audio_link_id, 2, 0, generator_id, 0, "AUDIO"])
    generator_inputs = []
    if clone:
        generator_inputs.append({
            "name": "reference_audio", "shape": 7, "type": "AUDIO", "link": audio_link_id,
        })
    generator_inputs.append({
        "name": "api_config", "shape": 7, "type": "SEEDANCE_CONFIG", "link": config_link_id,
    })
    output_names = (
        ["audios", "audio_urls", "audio_paths", "task_id", "response"]
        if list_output
        else (["audio", "audio_url", "audio_path", "result_text", "task_id", "response"]
              if node_type == "Minimax_Audio"
              else ["audio", "audio_url", "audio_path", "task_id", "response"])
    )
    output_types = ["AUDIO"] + ["STRING"] * (len(output_names) - 1)
    outputs = [
        {"name": name, "type": output_type, "links": [output_link_id] if index == 0 else None}
        for index, (name, output_type) in enumerate(zip(output_names, output_types))
    ]
    nodes.append(_node(
        generator_id, node_type, (400, 80), (470, 500), 2 if clone else 1,
        generator_inputs, outputs, widgets, title,
    ))
    nodes.append(_node(
        save_id, "SaveAudio", (950, 140), (270, 112), 3 if clone else 2,
        [{"name": "audio", "type": "AUDIO", "link": output_link_id}],
        [{"name": "audio", "type": "AUDIO", "links": None}],
        [f"audio/{Path(filename).stem}"],
    ))
    links.extend([config_link, [output_link_id, generator_id, 0, save_id, 0, "AUDIO"]])
    _workflow(filename, nodes, links)


def _minimax_widgets(model):
    is_music = model == "minimax-music-2.6"
    is_clone = model == "minimax-voice-clone"
    prompt = (
        "soft ambient piano, peaceful, cinematic background"
        if is_music else (
            "This is a short preview of the cloned voice."
            if is_clone else "你好，这是 MiniMax 语音合成测试。"
        )
    )
    return [
        model, prompt, "", is_music, False, "Wise_Woman", 1.0, 1.0, 0,
        "auto", "mp3", "32000", "128000", "1", "SeedanceVoice01",
        "minimax-speech-2.8-hd", False, False, False, 0, "fixed",
    ]


def main():
    _image_workflow(
        "zhenzhen-image-gk-v2文生图.json",
        "Zhenzhen_Image_GK_V2",
        "Zhenzhen Image GK v2 文生图",
        ["a clean cinematic portrait, natural light, fine details", "1:1", 1, False, 0, "fixed"],
    )
    _image_workflow(
        "zhenzhen-image-gk-v2-edit图像编辑.json",
        "Zhenzhen_Image_GK_V2_Edit",
        "Zhenzhen Image GK v2 多图编辑",
        [
            "keep the main subject, use the reference palette and create a polished poster",
            "auto",
            "1k",
            1,
            False,
            False,
            0,
            "fixed",
        ],
        input_count=3,
        connect_image=True,
    )
    _image_workflow(
        "wan-2.7-global-t2i文生图.json",
        "Wan_2_7_Global_Image",
        "Wan 2.7 海外文生图",
        ["wan-2.7-global-t2i", "a minimalist product photo, soft studio light", 1024, 1024, True, False, 0, "fixed"],
        input_count=9,
    )
    for model, label in (
        ("wan-2.7-global-i2i", "Wan 2.7 海外图像编辑"),
        ("wan-2.7-global-i2i-pro", "Wan 2.7 海外 Pro 图像编辑"),
    ):
        _image_workflow(
            f"{model}图像编辑.json",
            "Wan_2_7_Global_Image",
            label,
            [model, "keep the subject, change the background to a clean studio", 1024, 1024, True, False, 0, "fixed"],
            input_count=9,
            connect_image=True,
        )

    _audio_workflow(
        "qwen3-tts-flash语音合成.json", "Qwen3_TTS", "Qwen3 TTS Flash 语音合成",
        ["qwen3-tts-flash", "你好，这是 Qwen3 TTS 语音合成测试。", "Cherry", "Chinese", "", True, False, 0, "fixed"],
    )
    _audio_workflow(
        "qwen3-tts-instruct-flash指令语音.json", "Qwen3_TTS", "Qwen3 TTS Instruct Flash 指令语音",
        ["qwen3-tts-instruct-flash", "你好，这是带表达控制的语音合成。", "Cherry", "Chinese", "语气自然、亲切，语速稍慢。", True, False, 0, "fixed"],
    )
    for model, suffix in (
        ("minimax-music-2.6", "音乐生成"),
        ("minimax-speech-2.8-hd", "高清语音"),
        ("minimax-speech-2.8-turbo", "快速语音"),
        ("minimax-voice-clone", "声音克隆"),
    ):
        _audio_workflow(
            f"{model}{suffix}.json",
            "Minimax_Audio",
            f"{model} {suffix}",
            _minimax_widgets(model),
            clone=model == "minimax-voice-clone",
        )
    for model in ("mureka-v8-bgm", "mureka-v9-bgm"):
        _audio_workflow(
            f"{model}背景音乐.json",
            "Mureka_BGM",
            f"{model} 背景音乐",
            [model, "warm acoustic background music, calm and uplifting", "", 1, False, 0, "fixed"],
            list_output=True,
        )


if __name__ == "__main__":
    main()
