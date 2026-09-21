"""Generate credential-free Qwen 2.1 and Animate example workflows."""

from generate_latest_model_workflows import _config, _node, _workflow


def _core(node):
    node["properties"]["cnr_id"] = "comfy-core"
    return node


def _source(node_id, kind, link_id, y):
    is_video = kind == "VIDEO"
    node = _node(
        node_id, "LoadVideo" if is_video else "LoadImage", (40, y),
        (300, 320), node_id - 1, [],
        [{"name": kind, "type": kind, "links": [link_id]}] +
        ([] if is_video else [{"name": "MASK", "type": "MASK", "links": None}]),
        ["example.mp4" if is_video else "example.png", "image"],
        "选择动作参考视频" if is_video else "选择参考图片",
    )
    return _core(node)


def _save(node_id, kind, link_id, title):
    is_video = kind == "VIDEO"
    return _core(_node(
        node_id, "SaveVideo" if is_video else "SaveImage", (1020, 120),
        (300, 240), node_id - 1,
        [{"name": "video" if is_video else "images", "type": kind, "link": link_id}],
        ([{"name": "video", "type": "VIDEO", "links": None}] if is_video else []),
        (["seedance/animate_motion", "auto", "auto"] if is_video else ["seedance/qwen_image_21"]),
        title,
    ))


def _generator(node_id, node_type, kind, inputs, link_id, widgets, title):
    outputs = [
        {"name": "video" if kind == "VIDEO" else "image", "type": kind, "links": [link_id]},
        {"name": "video_url" if kind == "VIDEO" else "image_url", "type": "STRING", "links": None},
        {"name": "task_id", "type": "STRING", "links": None},
        {"name": "response", "type": "STRING", "links": None},
    ]
    node = _node(node_id, node_type, (440, 80), (510, 650), node_id - 1,
                 inputs, outputs, widgets, title)
    node["properties"]["aux_id"] = "T8mars/ComfyUI_Seedance"
    return node


def qwen_workflow(edit=False):
    filename = "qwen-image-global-2.1图像编辑.json" if edit else "qwen-image-global-2.1文生图.json"
    generator_id = 3 if edit else 2
    config_link = 2 if edit else 1
    output_link = config_link + 1
    config, config_edge = _config(config_link, generator_id, 10)
    nodes = [config]
    links = [config_edge]
    if edit:
        nodes.append(_source(2, "IMAGE", 1, 60))
        links.append([1, 2, 0, generator_id, 0, "IMAGE"])
    inputs = [
        {"name": f"image{i}", "shape": 7, "type": "IMAGE",
         "link": 1 if edit and i == 1 else None}
        for i in range(1, 11)
    ]
    inputs.append({"name": "api_config", "shape": 7,
                   "type": "SEEDANCE_CONFIG", "link": config_link})
    nodes.append(_generator(
        generator_id, "Qwen_Image_Global_2_1", "IMAGE", inputs, output_link,
        ["保留主体并调整背景" if edit else "一只纸雕白鹤站在深绿色展台上", "2k", "3:4", -1,
         "randomize", False],
        "Qwen Image Global 2.1 图像编辑" if edit else "Qwen Image Global 2.1 文生图",
    ))
    save_id = generator_id + 1
    nodes.append(_save(save_id, "IMAGE", output_link, "保存生成图片"))
    links.append([output_link, generator_id, 0, save_id, 0, "IMAGE"])
    _workflow(filename, nodes, links)


def animate_workflow(local=True):
    filename = "animate-motion-transfer本地素材.json" if local else "animate-motion-transfer网址素材.json"
    generator_id = 4 if local else 2
    config_link = 3 if local else 1
    output_link = 4 if local else 2
    config, config_edge = _config(config_link, generator_id, 2)
    nodes = [config]
    links = [config_edge]
    if local:
        nodes.extend((_source(2, "IMAGE", 1, 40), _source(3, "VIDEO", 2, 410)))
        links.extend(([1, 2, 0, generator_id, 0, "IMAGE"],
                      [2, 3, 0, generator_id, 1, "VIDEO"]))
    inputs = [
        {"name": "input_image", "shape": 7, "type": "IMAGE", "link": 1 if local else None},
        {"name": "input_video", "shape": 7, "type": "VIDEO", "link": 2 if local else None},
        {"name": "api_config", "shape": 7, "type": "SEEDANCE_CONFIG", "link": config_link},
    ]
    widgets = [
        "" if local else "https://example.com/character.png",
        "" if local else "https://example.com/motion.mp4",
        "720p", "adaptive", "16:9", 30, 0, 0, "vitpose", True, False,
        1.0, False, 1.0, False, 0.8, 0.2, False, 0, "fixed",
    ]
    nodes.append(_generator(
        generator_id, "Animate_Motion_Transfer", "VIDEO", inputs,
        output_link, widgets, "Animate 动作迁移",
    ))
    save_id = generator_id + 1
    nodes.append(_save(save_id, "VIDEO", output_link, "保存动作迁移视频"))
    links.append([output_link, generator_id, 0, save_id, 0, "VIDEO"])
    _workflow(filename, nodes, links)


if __name__ == "__main__":
    qwen_workflow(False)
    qwen_workflow(True)
    animate_workflow(True)
    animate_workflow(False)
