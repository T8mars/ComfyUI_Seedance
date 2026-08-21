"""Generate safe workflows for all documented Flow Music actions."""

import json
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EXAMPLES = ROOT / "examples"
OPERATIONS = (
    ("flowmusic-generation", "音乐生成"),
    ("flowmusic-lyrics", "歌词生成"),
    ("flowmusic-upload-audio", "上传音频"),
    ("flowmusic-extend", "音乐续写"),
    ("flowmusic-replace", "片段替换"),
    ("flowmusic-cover", "整曲改编"),
    ("flowmusic-stems", "人声伴奏分离"),
    ("flowmusic-download-audio", "下载音频"),
    ("flowmusic-video-clip", "音乐视频"),
)
FLOW_OUTPUTS = (
    ("audio1", "AUDIO"),
    ("audio2", "AUDIO"),
    ("video", "VIDEO"),
    ("text", "STRING"),
    ("clip_id", "STRING"),
    ("primary_url", "STRING"),
    ("result_urls", "STRING"),
    ("primary_path", "STRING"),
    ("result_paths", "STRING"),
    ("task_id", "STRING"),
    ("response", "STRING"),
)
AUDIO_RESULTS = {
    "flowmusic-generation",
    "flowmusic-extend",
    "flowmusic-replace",
    "flowmusic-cover",
    "flowmusic-download-audio",
}
DIRECT_OPERATIONS = {
    "flowmusic-generation",
    "flowmusic-lyrics",
    "flowmusic-upload-audio",
}


def node(node_id, node_type, pos, size, inputs, outputs, widgets, title=""):
    data = {
        "id": node_id,
        "type": node_type,
        "pos": list(pos),
        "size": list(size),
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": inputs,
        "outputs": outputs,
        "properties": {"Node name for S&R": node_type},
        "widgets_values": widgets,
    }
    if node_type in {"Seedance_Config", "Flow_Music"}:
        data["properties"]["aux_id"] = "T8mars/ComfyUI_Seedance"
    if title:
        data["title"] = title
    return data


def config_node(node_id):
    return node(
        node_id,
        "Seedance_Config",
        (40, 720),
        (300, 82),
        [],
        [{"name": "api_config", "type": "SEEDANCE_CONFIG", "links": None}],
        ["https://api.seedance.nz", ""],
    )


def load_audio_node(node_id):
    return node(
        node_id,
        "LoadAudio",
        (40, 80),
        (280, 136),
        [],
        [{"name": "AUDIO", "type": "AUDIO", "links": None}],
        ["example.wav", None, ""],
        "选择一个本地音频",
    )


def flow_widgets(operation):
    return [
        operation,
        "lyria-3.5" if operation == "flowmusic-replace" else "default",
        "warm cinematic piano with soft strings",
        "",
        "a hopeful song about finding light after rain",
        "",
        120,
        30,
        "",
        0.0,
        15,
        "continue naturally with soft strings",
        0.0,
        5.0,
        0.5,
        "mp3",
        "modern",
        0,
        "",
        False,
        "fixed",
    ]


def flow_node(node_id, operation, pos, title):
    return node(
        node_id,
        "Flow_Music",
        pos,
        (500, 560),
        [
            {"name": "audio", "shape": 7, "type": "AUDIO", "link": None},
            {"name": "api_config", "shape": 7, "type": "SEEDANCE_CONFIG", "link": None},
        ],
        [
            {"name": name, "type": type_name, "links": None}
            for name, type_name in FLOW_OUTPUTS
        ],
        flow_widgets(operation),
        title,
    )


def save_audio_node(node_id, operation):
    return node(
        node_id,
        "SaveAudio",
        (1500, 180),
        (270, 112),
        [{"name": "audio", "type": "AUDIO", "link": None}],
        [{"name": "audio", "type": "AUDIO", "links": None}],
        [f"audio/{operation}"],
    )


def save_video_node(node_id, operation):
    return node(
        node_id,
        "SaveVideo",
        (1500, 180),
        (270, 180),
        [{"name": "video", "type": "VIDEO", "link": None}],
        [{"name": "video", "type": "VIDEO", "links": None}],
        [f"video/{operation}", "auto", "auto"],
    )


class Builder:
    def __init__(self, operation):
        self.operation = operation
        self.nodes = []
        self.links = []
        self.next_node_id = 1
        self.next_link_id = 1

    def add(self, item):
        self.nodes.append(item)
        self.next_node_id = max(self.next_node_id, item["id"] + 1)
        return item

    def new_id(self):
        value = self.next_node_id
        self.next_node_id += 1
        return value

    def connect(self, source, output_name, target, input_name, type_name):
        output_index = next(
            index for index, slot in enumerate(source["outputs"])
            if slot["name"] == output_name
        )
        input_index = next(
            (
                index for index, slot in enumerate(target["inputs"])
                if slot["name"] == input_name
            ),
            None,
        )
        if input_index is None:
            target["inputs"].append({
                "name": input_name,
                "type": type_name,
                "widget": {"name": input_name},
                "link": None,
            })
            input_index = len(target["inputs"]) - 1
        link_id = self.next_link_id
        self.next_link_id += 1
        source["outputs"][output_index]["links"] = (
            source["outputs"][output_index]["links"] or []
        ) + [link_id]
        target["inputs"][input_index]["link"] = link_id
        self.links.append([
            link_id,
            source["id"],
            output_index,
            target["id"],
            input_index,
            type_name,
        ])

    def finish(self):
        for order, item in enumerate(self.nodes):
            item["order"] = order
        return {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"ComfyUI_Seedance/{self.operation}")),
            "revision": 0,
            "last_node_id": max(item["id"] for item in self.nodes),
            "last_link_id": self.next_link_id - 1,
            "nodes": self.nodes,
            "links": self.links,
            "groups": [],
            "config": {},
            "extra": {
                "frontendVersion": "1.45.20",
                "ds": {"scale": 0.85, "offset": [80, 40]},
            },
            "version": 0.4,
        }


def add_config(builder, *targets):
    config = builder.add(config_node(builder.new_id()))
    for target in targets:
        builder.connect(config, "api_config", target, "api_config", "SEEDANCE_CONFIG")


def build_workflow(operation):
    builder = Builder(operation)
    source = None
    load_audio = None
    if operation == "flowmusic-upload-audio" or operation not in DIRECT_OPERATIONS:
        load_audio = builder.add(load_audio_node(builder.new_id()))
        source = builder.add(
            flow_node(builder.new_id(), "flowmusic-upload-audio", (380, 80), "导入源音频")
        )
        builder.connect(load_audio, "AUDIO", source, "audio", "AUDIO")

    target = source if operation == "flowmusic-upload-audio" else builder.add(
        flow_node(
            builder.new_id(),
            operation,
            (920 if source else 380, 80),
            f"Flow Music - {operation}",
        )
    )
    targets = [target] if source is None or target is source else [source, target]
    add_config(builder, *targets)
    if source is not None and target is not source:
        builder.connect(source, "clip_id", target, "clip_id", "STRING")

    if operation in AUDIO_RESULTS:
        sink = builder.add(save_audio_node(builder.new_id(), operation))
        builder.connect(target, "audio1", sink, "audio", "AUDIO")
    elif operation == "flowmusic-video-clip":
        sink = builder.add(save_video_node(builder.new_id(), operation))
        builder.connect(target, "video", sink, "video", "VIDEO")
    return builder.finish()


def main():
    EXAMPLES.mkdir(parents=True, exist_ok=True)
    for operation, label in OPERATIONS:
        path = EXAMPLES / f"{operation}{label}.json"
        path.write_text(
            json.dumps(build_workflow(operation), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
