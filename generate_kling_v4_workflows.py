"""Create credential-free Kling 4 examples, including connected reusable IDs."""

import sys
from pathlib import Path

from generate_latest_model_workflows import _node, _workflow

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ComfyUI_Seedance import nodes as plugin_nodes


class Workflow:
    def __init__(self):
        self.nodes = []
        self.links = []
        self.config = self.add("Seedance_Config", (40, 350), (300, 90), [], [("api_config", "SEEDANCE_CONFIG")],
                               ["https://api.seedance.nz", ""], "API 配置：填写自己的密钥")

    def add(self, kind, pos, size, inputs, outputs, widgets, title):
        node = _node(len(self.nodes) + 1, kind, pos, size, len(self.nodes), inputs,
                     [{"name": name, "type": type_, "links": None} for name, type_ in outputs], widgets, title)
        node["properties"]["cnr_id" if kind.startswith(("Load", "Save", "Preview")) else "aux_id"] = (
            "comfy-core" if kind.startswith(("Load", "Save", "Preview")) else "T8mars/ComfyUI_Seedance")
        self.nodes.append(node)
        return node

    def connect(self, source, output_index, target, input_name):
        index = next(i for i, item in enumerate(target["inputs"]) if item["name"] == input_name)
        link_id = len(self.links) + 1
        target["inputs"][index]["link"] = link_id
        output = source["outputs"][output_index]
        output["links"] = (output["links"] or []) + [link_id]
        self.links.append([link_id, source["id"], output_index, target["id"], index, output["type"]])

    def generate(self, kind, values, pos=(440, 60), title=""):
        cls = plugin_nodes.NODE_CLASS_MAPPINGS[kind]
        schema = cls.INPUT_TYPES()
        inputs, widgets = [], []
        for group in ("required", "optional"):
            for name, spec in schema[group].items():
                if isinstance(spec[0], str) and spec[0] not in {"STRING", "INT", "FLOAT", "BOOLEAN"}:
                    inputs.append({"name": name, "type": spec[0], "shape": 7, "link": None})
                else:
                    widgets.append(values.get(name, spec[1].get("default", "")))
                    if name == "seed":
                        widgets.append("fixed")
        node = self.add(kind, pos, (510, 640), inputs, list(zip(cls.RETURN_NAMES, cls.RETURN_TYPES)), widgets, title)
        self.connect(self.config, 0, node, "api_config")
        return node

    def load(self, kind, y=30, title="", filename=None):
        type_ = {"IMAGE": "LoadImage", "VIDEO": "LoadVideo", "AUDIO": "LoadAudio"}[kind]
        widgets = {"IMAGE": ["example.png", "image"], "VIDEO": ["example.mp4", "image"],
                   "AUDIO": ["example.wav", None, None]}[kind]
        if filename:
            widgets[0] = filename
        outputs = [(kind, kind)] + ([("MASK", "MASK")] if kind == "IMAGE" else [])
        return self.add(type_, (40, y), (300, 270), [], outputs, widgets, title)

    def save_video(self, source, suffix="video", pos=(1050, 80)):
        node = self.add("SaveVideo", pos, (310, 240), [{"name": "video", "type": "VIDEO", "link": None}],
                        [("video", "VIDEO")], [f"seedance/kling4_{suffix}", "auto", "auto"], "保存视频")
        self.connect(source, 0, node, "video")

    def save_voice(self, source):
        node = self.add("PreviewAudio", (1050, 100), (310, 180),
                        [{"name": "audio", "type": "AUDIO", "link": None}], [], [], "试听创建的音色")
        self.connect(source, 1, node, "audio")

    def connect_widget(self, source, slot, target, name):
        target["inputs"].append({"name": name, "type": "STRING", "link": None, "widget": {"name": name}})
        self.connect(source, slot, target, name)

    def write(self, name):
        _workflow(name, self.nodes, self.links)


def main():
    common = {"prompt": "A small original blue toy robot waves once in a mint studio. Locked camera, gentle motion."}
    w = Workflow()
    node = w.generate("Kling_V4_T2V", common, title="Kling 4 文生视频")
    w.save_video(node, "t2v")
    w.write("kling-v4-t2v文生视频.json")
    for end in (False, True):
        w = Workflow()
        node = w.generate("Kling_V4_I2V", common, title="Kling 4 首尾帧" if end else "Kling 4 首帧图生视频")
        w.connect(w.load("IMAGE", 30, "选择首帧图"), 0, node, "image1")
        if end:
            w.connect(w.load("IMAGE", 520, "选择尾帧图", "example_last.png"), 0, node, "image2")
        w.save_video(node, "start_end" if end else "i2v")
        w.write("kling-v4-i2v" + ("首尾帧.json" if end else "首帧.json"))
    for mode in ("image", "local_video", "url_video"):
        w = Workflow()
        values = {"element_name": "Blue Robot", "prompt": "A small blue toy robot with a square head, dark face and yellow chest badge.",
                  "reference_type": "image_refer" if mode == "image" else "video_refer"}
        if mode == "url_video":
            values["video_url"] = "https://example.com/element-1080p.mp4"
        node = w.generate("Kling_V4_Custom_Element", values, title="主体创建：先执行并保存 element_id")
        if mode == "image":
            for i in (1, 2):
                w.connect(w.load("IMAGE", 30 if i == 1 else 520, "正面图" if i == 1 else "另一角度参考图，不要重复正面图",
                                 "example.png" if i == 1 else "example_reference.png"), 0, node, f"image{i}")
        elif mode == "local_video":
            w.connect(w.load("VIDEO", 30, "选择3-8秒1080p主体视频", "element_1080p.mp4"), 0, node, "input_video")
        w.write("kling-v4-custom-element" + {"image": "图片主体.json", "local_video": "本地视频主体.json", "url_video": "网址视频主体.json"}[mode])
    for mode in ("local_audio", "url_audio", "video_id"):
        w = Workflow()
        values = {"voice_name": "Studio Voice", "source_mode": "video_id" if mode == "video_id" else "audio"}
        if mode == "url_audio":
            values["audio_url"] = "https://example.com/voice.wav"
        node = w.generate("Kling_V4_Custom_Voice", values,
                          title="填写自己的上游 videoId，不是任务ID" if mode == "video_id" else "音色创建：保存 voice_id")
        if mode == "local_audio":
            w.connect(w.load("AUDIO", 30, "选择自己有权使用的清晰语音"), 0, node, "audio")
        w.save_voice(node)
        w.write("kling-v4-custom-voice" + {"local_audio": "本地音频.json", "url_audio": "网址音频.json", "video_id": "视频ID来源.json"}[mode])
    w = Workflow()
    node = w.generate("Kling_V4_Omni", {"prompt": "Keep the subject in @1 consistent and animate a gentle wave, matching the reference video's style."}, title="Kling 4 Omni 图片和视频参考")
    w.connect(w.load("IMAGE", 30, "选择参考图"), 0, node, "image1")
    w.connect(w.load("VIDEO", 520, "选择参考视频，总时长最多30秒"), 0, node, "video1")
    w.save_video(node, "omni")
    w.write("kling-v4-omni图片视频参考.json")
    w = Workflow()
    front = w.load("IMAGE", 30, "主体正面图")
    side = w.load("IMAGE", 730, "同一主体的不同角度", "example_reference.png")
    audio = w.load("AUDIO", 1080, "自己有权使用的语音样本")
    element = w.generate("Kling_V4_Custom_Element", {"element_name": "Blue Robot", "prompt": "A small blue toy robot with a square head, dark face and yellow chest badge."},
                         pos=(440, 30), title="创建图片主体")
    voice = w.generate("Kling_V4_Custom_Voice", {"voice_name": "Studio Voice"}, pos=(440, 810), title="创建音色")
    omni = w.generate("Kling_V4_Omni", {"prompt": "@element_1 is the subject in @1. Keep its design consistent. It waves once and says hello in the supplied voice."},
                      pos=(1110, 30), title="主体ID + 音色ID 自动连线到 Omni")
    w.connect(front, 0, element, "image1")
    w.connect(side, 0, element, "image2")
    w.connect(audio, 0, voice, "audio")
    w.connect(front, 0, omni, "image1")
    w.connect_widget(element, 0, omni, "image_element_ids")
    w.connect_widget(voice, 0, omni, "voice_ids")
    w.save_video(omni, "connected_ids", pos=(1740, 80))
    w.write("kling-v4-omni主体音色连线.json")


if __name__ == "__main__":
    main()
