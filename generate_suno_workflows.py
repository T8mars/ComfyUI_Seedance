"""Generate the 31 documented Suno example workflows.

The files deliberately contain no API key, source task id, result URL, or
runtime response. Task-based actions are wired to preceding Suno node outputs.
"""

import json
import uuid
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parent
EXAMPLES_DIR = PLUGIN_ROOT / "examples"

OPERATIONS = [
    ("suno-generation", "音乐生成"),
    ("suno-lyrics", "歌词生成"),
    ("suno-upload", "本地音频导入"),
    ("suno-extend", "续写"),
    ("suno-cover-song", "翻唱换风格"),
    ("suno-inspo", "参考音频生成"),
    ("suno-mashup", "双曲混合"),
    ("suno-upsample-tags", "风格标签扩写"),
    ("suno-sounds", "音效生成"),
    ("suno-create-voice", "创建音色"),
    ("suno-stems", "单分轨"),
    ("suno-stems-all", "全分轨"),
    ("suno-wav", "导出WAV"),
    ("suno-generate-mp4", "生成MV"),
    ("suno-concat", "拼接完整歌曲"),
    ("suno-crop", "裁剪"),
    ("suno-fade-in", "淡入"),
    ("suno-fade-out", "淡出"),
    ("suno-remove-section", "删除片段"),
    ("suno-replace-music", "替换片段"),
    ("suno-adjust-speed", "变速"),
    ("suno-remaster", "母带处理"),
    ("suno-midi", "生成MIDI"),
    ("suno-bpm", "分析BPM"),
    ("suno-aligned-lyrics", "对齐歌词"),
    ("suno-persona", "创建Persona"),
    ("suno-vox", "提取人声片段"),
    ("suno-sample", "采样生成"),
    ("suno-add-vocals", "添加人声"),
    ("suno-add-instrumental", "添加伴奏"),
    ("suno-add-stem", "添加Stem"),
]

TEXT_ONLY = {
    "suno-lyrics",
    "suno-upload",
    "suno-upsample-tags",
    "suno-create-voice",
    "suno-bpm",
    "suno-aligned-lyrics",
    "suno-persona",
}
FILE_ONLY = {"suno-midi"}
VIDEO_ONLY = {"suno-generate-mp4"}
LOCAL_AUDIO_ACTIONS = {"suno-upload", "suno-inspo", "suno-create-voice"}
UPLOAD_SOURCE_ACTIONS = {
    "suno-add-vocals",
    "suno-add-instrumental",
    "suno-add-stem",
}
DIRECT_ACTIONS = {
    "suno-generation",
    "suno-lyrics",
    "suno-upload",
    "suno-inspo",
    "suno-upsample-tags",
    "suno-sounds",
    "suno-create-voice",
}

SUNO_OUTPUTS = [
    ("audio1", "AUDIO"),
    ("audio2", "AUDIO"),
    ("video", "VIDEO"),
    ("text", "STRING"),
    ("primary_url", "STRING"),
    ("result_urls", "STRING"),
    ("primary_path", "STRING"),
    ("result_paths", "STRING"),
    ("task_id", "STRING"),
    ("response", "STRING"),
]


def config_node(node_id, x, y):
    return {
        "id": node_id,
        "type": "Seedance_Config",
        "pos": [x, y],
        "size": [300, 82],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [],
        "outputs": [{"name": "api_config", "type": "SEEDANCE_CONFIG", "links": None}],
        "properties": {
            "aux_id": "T8mars/ComfyUI_Seedance",
            "Node name for S&R": "Seedance_Config",
        },
        "widgets_values": ["https://api.seedance.nz", ""],
    }


def load_audio_node(node_id, x, y):
    return {
        "id": node_id,
        "type": "LoadAudio",
        "title": "选择一个短音频素材",
        "pos": [x, y],
        "size": [270, 136],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [],
        "outputs": [{"name": "AUDIO", "type": "AUDIO", "links": None}],
        "properties": {
            "cnr_id": "comfy-core",
            "ver": "0.27.0",
            "Node name for S&R": "LoadAudio",
        },
        "widgets_values": ["example.wav", None, ""],
    }


def suno_widgets(operation):
    prompt = "short cinematic instrumental with piano and soft percussion"
    if operation == "suno-lyrics":
        prompt = "a hopeful journey through a rainy city at night"
    elif operation == "suno-sounds":
        prompt = "a short wooden door creak in a quiet room"
    return [
        operation,
        prompt,
        "v5.5",
        False,
        operation == "suno-generation",
        "",
        "",
        "unspecified",
        "cinematic, emotional, piano",
        "Studio Persona",
        "",
        "",
        1,
        30.0,
        0.0,
        4.0,
        2.0,
        1.1,
        "",
        "",
        "",
        "",
        False,
    ]


def suno_node(node_id, operation, x, y, title=None):
    inputs = [
        {"name": f"audio{i}", "shape": 7, "type": "AUDIO", "link": None}
        for i in range(1, 5)
    ]
    inputs.append(
        {
            "name": "api_config",
            "shape": 7,
            "type": "SEEDANCE_CONFIG",
            "link": None,
        }
    )
    return {
        "id": node_id,
        "type": "Suno_Music",
        "title": title or f"Suno - {operation}",
        "pos": [x, y],
        "size": [470, 520],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": inputs,
        "outputs": [
            {"name": name, "type": type_name, "links": None}
            for name, type_name in SUNO_OUTPUTS
        ],
        "properties": {
            "aux_id": "T8mars/ComfyUI_Seedance",
            "Node name for S&R": "Suno_Music",
        },
        "widgets_values": suno_widgets(operation),
    }


def save_audio_node(node_id, operation, x, y):
    return {
        "id": node_id,
        "type": "SaveAudio",
        "pos": [x, y],
        "size": [270, 112],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [{"name": "audio", "type": "AUDIO", "link": None}],
        "outputs": [{"name": "audio", "type": "AUDIO", "links": None}],
        "properties": {
            "cnr_id": "comfy-core",
            "ver": "0.27.0",
            "Node name for S&R": "SaveAudio",
        },
        "widgets_values": [f"audio/{operation}"],
    }


def save_video_node(node_id, operation, x, y):
    return {
        "id": node_id,
        "type": "SaveVideo",
        "pos": [x, y],
        "size": [270, 180],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [{"name": "video", "type": "VIDEO", "link": None}],
        "outputs": [{"name": "video", "type": "VIDEO", "links": None}],
        "properties": {
            "cnr_id": "comfy-core",
            "ver": "0.27.0",
            "Node name for S&R": "SaveVideo",
        },
        "widgets_values": [f"video/{operation}", "auto", "auto"],
    }


class WorkflowBuilder:
    def __init__(self, operation):
        self.operation = operation
        self.nodes = []
        self.links = []
        self.next_node_id = 1
        self.next_link_id = 1

    def add(self, node):
        self.nodes.append(node)
        self.next_node_id = max(self.next_node_id, node["id"] + 1)
        return node

    def node_id(self):
        node_id = self.next_node_id
        self.next_node_id += 1
        return node_id

    def connect(self, source, output_name, target, input_name, type_name):
        output_index = next(
            index
            for index, output in enumerate(source["outputs"])
            if output["name"] == output_name
        )
        input_index = next(
            (
                index
                for index, input_slot in enumerate(target["inputs"])
                if input_slot["name"] == input_name
            ),
            None,
        )
        if input_index is None:
            target["inputs"].append(
                {
                    "name": input_name,
                    "type": type_name,
                    "widget": {"name": input_name},
                    "link": None,
                }
            )
            input_index = len(target["inputs"]) - 1

        link_id = self.next_link_id
        self.next_link_id += 1
        source_links = source["outputs"][output_index]["links"]
        if source_links is None:
            source_links = []
            source["outputs"][output_index]["links"] = source_links
        source_links.append(link_id)
        target["inputs"][input_index]["link"] = link_id
        self.links.append(
            [
                link_id,
                source["id"],
                output_index,
                target["id"],
                input_index,
                type_name,
            ]
        )

    def finish(self):
        for order, node in enumerate(self.nodes):
            node["order"] = order
        return {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"ComfyUI_Seedance/{self.operation}")),
            "revision": 0,
            "last_node_id": max(node["id"] for node in self.nodes),
            "last_link_id": self.next_link_id - 1,
            "nodes": self.nodes,
            "links": self.links,
            "groups": [],
            "config": {},
            "extra": {
                "frontendVersion": "1.45.20",
                "ds": {"scale": 0.9, "offset": [80, 40]},
            },
            "version": 0.4,
        }


def add_config(builder, *suno_nodes):
    config = builder.add(config_node(builder.node_id(), 40, 720))
    for node in suno_nodes:
        builder.connect(config, "api_config", node, "api_config", "SEEDANCE_CONFIG")
    return config


def add_result_sink(builder, operation, final_node, x):
    if operation in TEXT_ONLY or operation in FILE_ONLY:
        return
    if operation in VIDEO_ONLY:
        sink = builder.add(save_video_node(builder.node_id(), operation, x, 180))
        builder.connect(final_node, "video", sink, "video", "VIDEO")
        return
    sink = builder.add(save_audio_node(builder.node_id(), operation, x, 180))
    builder.connect(final_node, "audio1", sink, "audio", "AUDIO")


def build_workflow(operation):
    builder = WorkflowBuilder(operation)

    if operation in DIRECT_ACTIONS:
        load_audio = None
        if operation in LOCAL_AUDIO_ACTIONS:
            load_audio = builder.add(load_audio_node(builder.node_id(), 40, 120))
        target = builder.add(
            suno_node(builder.node_id(), operation, 400, 100, f"Suno {operation}")
        )
        add_config(builder, target)
        if load_audio:
            builder.connect(load_audio, "AUDIO", target, "audio1", "AUDIO")
        add_result_sink(builder, operation, target, 940)
        return builder.finish()

    if operation == "suno-mashup":
        source_a = builder.add(
            suno_node(builder.node_id(), "suno-generation", 40, 80, "生成源音乐 A")
        )
        source_b = builder.add(
            suno_node(builder.node_id(), "suno-generation", 40, 600, "生成源音乐 B")
        )
        target = builder.add(
            suno_node(builder.node_id(), operation, 600, 280, "Suno 双曲混合")
        )
        add_config(builder, source_a, source_b, target)
        builder.connect(source_a, "task_id", target, "task_id", "STRING")
        builder.connect(source_b, "task_id", target, "task_id_2", "STRING")
        add_result_sink(builder, operation, target, 1140)
        return builder.finish()

    if operation == "suno-concat":
        source = builder.add(
            suno_node(builder.node_id(), "suno-generation", 40, 80, "生成源音乐")
        )
        extend = builder.add(
            suno_node(builder.node_id(), "suno-extend", 560, 80, "续写源音乐")
        )
        target = builder.add(
            suno_node(builder.node_id(), operation, 1080, 80, "拼接完整歌曲")
        )
        add_config(builder, source, extend, target)
        builder.connect(source, "task_id", extend, "task_id", "STRING")
        builder.connect(extend, "task_id", target, "task_id", "STRING")
        add_result_sink(builder, operation, target, 1620)
        return builder.finish()

    if operation in UPLOAD_SOURCE_ACTIONS:
        load_audio = builder.add(load_audio_node(builder.node_id(), 40, 100))
        source = builder.add(
            suno_node(builder.node_id(), "suno-upload", 380, 80, "导入源音频")
        )
        target = builder.add(
            suno_node(builder.node_id(), operation, 900, 80, f"Suno {operation}")
        )
        add_config(builder, source, target)
        builder.connect(load_audio, "AUDIO", source, "audio1", "AUDIO")
        builder.connect(source, "task_id", target, "task_id", "STRING")
        add_result_sink(builder, operation, target, 1440)
        return builder.finish()

    source = builder.add(
        suno_node(builder.node_id(), "suno-generation", 40, 100, "生成源音乐")
    )
    target = builder.add(
        suno_node(builder.node_id(), operation, 580, 100, f"Suno {operation}")
    )
    add_config(builder, source, target)
    builder.connect(source, "task_id", target, "task_id", "STRING")
    add_result_sink(builder, operation, target, 1120)
    return builder.finish()


def main():
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    for operation, label in OPERATIONS:
        path = EXAMPLES_DIR / f"{operation}{label}.json"
        workflow = build_workflow(operation)
        path.write_text(
            json.dumps(workflow, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
