"""Generate Midjourney example workflows without runtime or secret data."""

import json
import sys
import uuid
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parent
EXAMPLES_DIR = PLUGIN_ROOT / "examples"
sys.path.insert(0, str(PLUGIN_ROOT.parent))

from ComfyUI_Seedance.nodes import MidjourneyMultiAction


MANDATORY = [
    ("midjourney-imagine", "文生图"),
    ("midjourney-blend", "多图融合"),
    ("midjourney-describe", "图生文"),
    ("midjourney-edits", "图片编辑"),
    ("midjourney-upscale", "放大"),
    ("midjourney-variation", "生成变体"),
    ("midjourney-high-variation", "大幅变体"),
    ("midjourney-low-variation", "微调变体"),
    ("midjourney-reroll", "重新生成"),
    ("midjourney-zoom", "缩放扩展"),
    ("midjourney-pan", "平移扩展"),
    ("midjourney-inpaint", "局部重绘入口"),
    ("midjourney-modal", "局部重绘完成"),
    ("midjourney-video", "图生视频"),
    ("midjourney-remix-strong", "强重塑"),
    ("midjourney-remix-subtle", "弱重塑"),
]

SUPPLEMENTAL = [
    ("midjourney-imagine", "参考图", "imagine-reference"),
    ("midjourney-video", "任务复用", "video-task"),
    ("midjourney-video", "首尾帧", "video-start-end"),
]

MIDJOURNEY_OUTPUTS = [
    ("image1", "IMAGE"),
    ("image2", "IMAGE"),
    ("image3", "IMAGE"),
    ("image4", "IMAGE"),
    ("grid_image", "IMAGE"),
    ("video1", "VIDEO"),
    ("video2", "VIDEO"),
    ("video3", "VIDEO"),
    ("video4", "VIDEO"),
    ("text", "STRING"),
    ("primary_url", "STRING"),
    ("result_urls", "STRING"),
    ("primary_path", "STRING"),
    ("result_paths", "STRING"),
    ("task_id", "STRING"),
    ("buttons_json", "STRING"),
    ("response", "STRING"),
]

INPUT_TYPES = MidjourneyMultiAction.INPUT_TYPES()
REQUIRED_WIDGETS = list(INPUT_TYPES["required"])


def default_widget_value(name):
    type_spec, options = INPUT_TYPES["required"][name]
    options = options or {}
    if "default" in options:
        return options["default"]
    if isinstance(type_spec, list) and type_spec:
        return type_spec[0]
    if type_spec == "STRING":
        return ""
    if type_spec == "BOOLEAN":
        return False
    if type_spec in {"INT", "FLOAT"}:
        return 0
    return ""


def widget_values(operation, overrides=None):
    values = {
        name: default_widget_value(name)
        for name in REQUIRED_WIDGETS
    }
    values.update({
        "operation": operation,
        "prompt": "a small red paper boat on a quiet lake, soft natural light",
        "speed": "relax",
        "index": -1,
        "modal_mode": "region",
        "batch_size": 1,
    })
    values.update(overrides or {})
    return [values[name] for name in REQUIRED_WIDGETS] + [False]


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
        "outputs": [
            {"name": "api_config", "type": "SEEDANCE_CONFIG", "links": None}
        ],
        "properties": {
            "aux_id": "T8mars/ComfyUI_Seedance",
            "Node name for S&R": "Seedance_Config",
        },
        "widgets_values": ["https://api.seedance.nz", ""],
    }


def load_image_node(node_id, x, y, title):
    return {
        "id": node_id,
        "type": "LoadImage",
        "title": title,
        "pos": [x, y],
        "size": [270, 314],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [],
        "outputs": [
            {"name": "IMAGE", "type": "IMAGE", "links": None},
            {"name": "MASK", "type": "MASK", "links": None},
        ],
        "properties": {
            "cnr_id": "comfy-core",
            "Node name for S&R": "LoadImage",
        },
        "widgets_values": ["", "image"],
    }


def primitive_text_node(node_id, x, y, text):
    return {
        "id": node_id,
        "type": "PrimitiveStringMultiline",
        "title": "编辑提示词",
        "pos": [x, y],
        "size": [310, 170],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [],
        "outputs": [{"name": "STRING", "type": "STRING", "links": None}],
        "properties": {
            "cnr_id": "comfy-core",
            "Node name for S&R": "PrimitiveStringMultiline",
        },
        "widgets_values": [text],
    }


def midjourney_node(node_id, operation, x, y, title=None, overrides=None):
    inputs = [
        {"name": f"image{i}", "shape": 7, "type": "IMAGE", "link": None}
        for i in range(1, 5)
    ]
    inputs.extend([
        {"name": "end_image", "shape": 7, "type": "IMAGE", "link": None},
        {"name": "mask", "shape": 7, "type": "MASK", "link": None},
        {
            "name": "api_config",
            "shape": 7,
            "type": "SEEDANCE_CONFIG",
            "link": None,
        },
    ])
    return {
        "id": node_id,
        "type": "Midjourney_Multi_Action",
        "title": title or operation,
        "pos": [x, y],
        "size": [500, 620],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": inputs,
        "outputs": [
            {"name": name, "type": type_name, "links": None}
            for name, type_name in MIDJOURNEY_OUTPUTS
        ],
        "properties": {
            "aux_id": "T8mars/ComfyUI_Seedance",
            "Node name for S&R": "Midjourney_Multi_Action",
        },
        "widgets_values": widget_values(operation, overrides),
    }


def save_image_node(node_id, x, y, prefix):
    return {
        "id": node_id,
        "type": "SaveImage",
        "pos": [x, y],
        "size": [270, 270],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [{"name": "images", "type": "IMAGE", "link": None}],
        "outputs": [
            {"name": "images", "type": "IMAGE", "links": None}
        ],
        "properties": {
            "cnr_id": "comfy-core",
            "Node name for S&R": "SaveImage",
        },
        "widgets_values": [f"midjourney/{prefix}"],
    }


def save_video_node(node_id, x, y, prefix):
    return {
        "id": node_id,
        "type": "SaveVideo",
        "pos": [x, y],
        "size": [270, 180],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [{"name": "video", "type": "VIDEO", "link": None}],
        "outputs": [
            {"name": "video", "type": "VIDEO", "links": None}
        ],
        "properties": {
            "cnr_id": "comfy-core",
            "Node name for S&R": "SaveVideo",
        },
        "widgets_values": [f"midjourney/{prefix}", "auto", "auto"],
    }


def preview_node(node_id, x, y, title):
    return {
        "id": node_id,
        "type": "PreviewAny",
        "title": title,
        "pos": [x, y],
        "size": [320, 180],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [{"name": "source", "type": "*", "link": None}],
        "outputs": [{"name": "STRING", "type": "STRING", "links": None}],
        "properties": {
            "cnr_id": "comfy-core",
            "Node name for S&R": "PreviewAny",
        },
        "widgets_values": [],
    }


class WorkflowBuilder:
    def __init__(self, name):
        self.name = name
        self.nodes = []
        self.links = []
        self.next_node_id = 1
        self.next_link_id = 1

    def node_id(self):
        value = self.next_node_id
        self.next_node_id += 1
        return value

    def add(self, node):
        self.nodes.append(node)
        return node

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
        )
        source["outputs"][output_index]["links"].append(link_id)
        target["inputs"][input_index]["link"] = link_id
        self.links.append([
            link_id,
            source["id"],
            output_index,
            target["id"],
            input_index,
            type_name,
        ])

    def document(self):
        for order, node in enumerate(self.nodes):
            node["order"] = order
        return {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"seedance:{self.name}")),
            "revision": 0,
            "last_node_id": max(node["id"] for node in self.nodes),
            "last_link_id": self.next_link_id - 1,
            "nodes": self.nodes,
            "links": self.links,
            "groups": [],
            "config": {},
            "extra": {
                "ds": {"scale": 0.8, "offset": [100, 80]},
                "frontendVersion": "1.24.4",
            },
            "version": 0.4,
        }


def add_config(builder):
    return builder.add(config_node(builder.node_id(), 20, 760))


def add_midjourney(builder, config, operation, x, y, title=None, overrides=None):
    node = builder.add(
        midjourney_node(
            builder.node_id(), operation, x, y, title=title, overrides=overrides
        )
    )
    builder.connect(config, "api_config", node, "api_config", "SEEDANCE_CONFIG")
    return node


def add_imagine_source(builder, config, x=380, y=80, version="8.2"):
    return add_midjourney(
        builder,
        config,
        "midjourney-imagine",
        x,
        y,
        title="生成源四宫格",
        overrides={
            "prompt": "a small red paper boat on a quiet lake, soft natural light",
            "version": version,
        },
    )


def add_upscale_source(builder, config, imagine, x=940, y=80):
    upscale = add_midjourney(
        builder,
        config,
        "midjourney-upscale",
        x,
        y,
        title="放大第 1 张",
        overrides={"index": 1},
    )
    builder.connect(imagine, "task_id", upscale, "task_id", "STRING")
    return upscale


def add_final_output(builder, node, operation, x=1500, y=160):
    save = builder.add(
        save_image_node(builder.node_id(), x, y, operation)
    )
    builder.connect(node, "image1", save, "images", "IMAGE")


def build_direct(operation, label):
    builder = WorkflowBuilder(f"{operation}-{label}")
    config = add_config(builder)
    target = None

    if operation == "midjourney-imagine":
        target = add_midjourney(builder, config, operation, 400, 100)
        for index in range(1, 5):
            save = builder.add(
                save_image_node(
                    builder.node_id(),
                    980 + (index - 1) % 2 * 300,
                    40 + (index - 1) // 2 * 320,
                    f"{operation}-{index}",
                )
            )
            builder.connect(target, f"image{index}", save, "images", "IMAGE")
    elif operation == "midjourney-blend":
        image1 = builder.add(load_image_node(builder.node_id(), 20, 20, "选择图片 1"))
        image2 = builder.add(load_image_node(builder.node_id(), 20, 380, "选择图片 2"))
        target = add_midjourney(builder, config, operation, 400, 100)
        builder.connect(image1, "IMAGE", target, "image1", "IMAGE")
        builder.connect(image2, "IMAGE", target, "image2", "IMAGE")
        add_final_output(builder, target, operation, 980, 150)
    elif operation == "midjourney-describe":
        image = builder.add(load_image_node(builder.node_id(), 20, 80, "选择待描述图片"))
        target = add_midjourney(builder, config, operation, 400, 100)
        preview = builder.add(
            preview_node(builder.node_id(), 980, 180, "图片描述结果")
        )
        builder.connect(image, "IMAGE", target, "image1", "IMAGE")
        builder.connect(target, "text", preview, "source", "STRING")
    elif operation == "midjourney-edits":
        image = builder.add(load_image_node(builder.node_id(), 20, 20, "选择待编辑图片"))
        prompt = builder.add(
            primitive_text_node(
                builder.node_id(),
                20,
                390,
                "turn the paper boat blue while keeping the lake unchanged",
            )
        )
        target = add_midjourney(
            builder,
            config,
            operation,
            400,
            100,
            overrides={"prompt": ""},
        )
        builder.connect(image, "IMAGE", target, "image1", "IMAGE")
        builder.connect(prompt, "STRING", target, "prompt", "STRING")
        add_final_output(builder, target, operation, 980, 150)
    elif operation == "midjourney-video":
        image = builder.add(load_image_node(builder.node_id(), 20, 80, "选择视频首帧"))
        target = add_midjourney(
            builder,
            config,
            operation,
            400,
            100,
            overrides={
                "prompt": "gentle ripples move around the paper boat",
                "index": -1,
                "batch_size": 1,
            },
        )
        save = builder.add(
            save_video_node(builder.node_id(), 980, 180, operation)
        )
        builder.connect(image, "IMAGE", target, "image1", "IMAGE")
        builder.connect(target, "video1", save, "video", "VIDEO")
    return builder.document()


def build_task_action(operation, label):
    builder = WorkflowBuilder(f"{operation}-{label}")
    config = add_config(builder)
    version = "8.1" if operation.startswith("midjourney-remix-") else "8.2"
    if operation == "midjourney-pan":
        version = "6.1"
    imagine = add_imagine_source(builder, config, version=version)

    parent = imagine
    if operation in {
        "midjourney-high-variation",
        "midjourney-low-variation",
        "midjourney-zoom",
        "midjourney-pan",
        "midjourney-inpaint",
    }:
        parent = add_upscale_source(builder, config, imagine)

    overrides = {"index": 1}
    if operation in {"midjourney-reroll", "midjourney-zoom", "midjourney-inpaint"}:
        overrides["index"] = -1
    if operation == "midjourney-pan":
        overrides.update({"index": -1, "direction": "right"})
    target = add_midjourney(
        builder,
        config,
        operation,
        1500 if parent is not imagine else 940,
        80,
        overrides=overrides,
    )
    builder.connect(parent, "task_id", target, "task_id", "STRING")

    if operation == "midjourney-inpaint":
        preview = builder.add(
            preview_node(builder.node_id(), 2080, 180, "MODAL 任务 ID")
        )
        builder.connect(target, "task_id", preview, "source", "STRING")
    else:
        add_final_output(
            builder,
            target,
            operation,
            2080 if parent is not imagine else 1500,
            150,
        )
    return builder.document()


def build_modal(label):
    operation = "midjourney-modal"
    builder = WorkflowBuilder(f"{operation}-{label}")
    config = add_config(builder)
    mask_source = builder.add(
        load_image_node(builder.node_id(), 20, 80, "选择局部重绘遮罩图片")
    )
    imagine = add_imagine_source(builder, config, version="6.1")
    upscale = add_upscale_source(builder, config, imagine)
    inpaint = add_midjourney(
        builder,
        config,
        "midjourney-inpaint",
        1500,
        80,
        overrides={"index": -1},
    )
    builder.connect(upscale, "task_id", inpaint, "task_id", "STRING")
    modal = add_midjourney(
        builder,
        config,
        operation,
        2060,
        80,
        overrides={
            "prompt": "replace the selected region with a small blue sail",
            "modal_mode": "region",
        },
    )
    builder.connect(inpaint, "task_id", modal, "task_id", "STRING")
    builder.connect(mask_source, "MASK", modal, "mask", "MASK")
    add_final_output(builder, modal, operation, 2640, 150)
    return builder.document()


def build_supplemental(kind, label):
    builder = WorkflowBuilder(f"midjourney-{kind}-{label}")
    config = add_config(builder)
    if kind == "imagine-reference":
        image = builder.add(load_image_node(builder.node_id(), 20, 80, "选择参考图片"))
        node = add_midjourney(
            builder,
            config,
            "midjourney-imagine",
            400,
            100,
            overrides={"prompt": "a cinematic paper boat scene using the reference"},
        )
        builder.connect(image, "IMAGE", node, "image1", "IMAGE")
        add_final_output(builder, node, "midjourney-imagine参考图", 980, 150)
    elif kind == "video-task":
        imagine = add_imagine_source(builder, config)
        node = add_midjourney(
            builder,
            config,
            "midjourney-video",
            940,
            80,
            overrides={
                "prompt": "gentle camera push toward the paper boat",
                "index": 0,
                "animate_mode": "auto",
                "batch_size": 1,
            },
        )
        builder.connect(imagine, "task_id", node, "task_id", "STRING")
        save = builder.add(
            save_video_node(builder.node_id(), 1500, 180, "midjourney-video任务复用")
        )
        builder.connect(node, "video1", save, "video", "VIDEO")
    elif kind == "video-start-end":
        start = builder.add(load_image_node(builder.node_id(), 20, 20, "选择首帧"))
        end = builder.add(load_image_node(builder.node_id(), 20, 380, "选择结束帧"))
        node = add_midjourney(
            builder,
            config,
            "midjourney-video",
            400,
            100,
            overrides={
                "prompt": "smooth transition between the two frames",
                "index": -1,
                "video_type": "vid_1.1_i2v_start_end_480",
                "batch_size": 1,
            },
        )
        builder.connect(start, "IMAGE", node, "image1", "IMAGE")
        builder.connect(end, "IMAGE", node, "end_image", "IMAGE")
        save = builder.add(
            save_video_node(builder.node_id(), 980, 180, "midjourney-video首尾帧")
        )
        builder.connect(node, "video1", save, "video", "VIDEO")
    return builder.document()


def write_workflows():
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    direct = {
        "midjourney-imagine",
        "midjourney-blend",
        "midjourney-describe",
        "midjourney-edits",
        "midjourney-video",
    }
    for operation, label in MANDATORY:
        if operation == "midjourney-modal":
            document = build_modal(label)
        elif operation in direct:
            document = build_direct(operation, label)
        else:
            document = build_task_action(operation, label)
        path = EXAMPLES_DIR / f"{operation}{label}.json"
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(path)

    for operation, label, kind in SUPPLEMENTAL:
        document = build_supplemental(kind, label)
        path = EXAMPLES_DIR / f"{operation}{label}.json"
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


if __name__ == "__main__":
    paths = write_workflows()
    print(f"Generated {len(paths)} Midjourney workflows")
