"""Generate credential-free Seedream V5 Flash example workflows."""

from pathlib import Path

from generate_latest_model_workflows import _config, _node, _workflow


PLUGIN = "T8mars/ComfyUI_Seedance"


def _plugin(node):
    node["properties"]["aux_id"] = PLUGIN
    return node


def _core(node):
    node["properties"]["cnr_id"] = "comfy-core"
    return node


def _load_image(node_id, link_id):
    return _core(_node(
        node_id,
        "LoadImage",
        (40, 70),
        (300, 310),
        1,
        [],
        [
            {"name": "IMAGE", "type": "IMAGE", "links": [link_id]},
            {"name": "MASK", "type": "MASK", "links": None},
        ],
        ["example.png", "image"],
        "选择参考图片",
    ))


def _save_image(node_id, link_id, filename, order):
    return _core(_node(
        node_id,
        "SaveImage",
        (1060, 120),
        (300, 270),
        order,
        [{"name": "images", "type": "IMAGE", "link": link_id}],
        [{"name": "images", "type": "IMAGE", "links": None}],
        [Path(filename).stem],
        "保存结果",
    ))


def image_workflow(prefix, family, edit):
    mode = "图像编辑" if edit else "文生图"
    filename = f"{prefix}{mode}.json"
    generator_id = 3 if edit else 2
    config_link_id = 2 if edit else 1
    output_link_id = config_link_id + 1
    config, config_link = _config(config_link_id, generator_id, 10)
    nodes = [_plugin(config)]
    links = [config_link]
    if edit:
        nodes.append(_load_image(2, 1))
        links.append([1, 2, 0, generator_id, 0, "IMAGE"])

    inputs = [
        {
            "name": f"image{index}",
            "shape": 7,
            "type": "IMAGE",
            "link": 1 if edit and index == 1 else None,
        }
        for index in range(1, 11)
    ]
    inputs.append({
        "name": "api_config",
        "shape": 7,
        "type": "SEEDANCE_CONFIG",
        "link": config_link_id,
    })
    prompt = (
        "保留人物主体与构图，将背景改为雨后街景，暖色电影灯光"
        if edit
        else "雨后街角的咖啡店，暖色灯光，电影质感，细节清晰"
    )
    generator = _plugin(_node(
        generator_id,
        "Seedream_V5_Pro_Image",
        (410, 70),
        (540, 560),
        2 if edit else 1,
        inputs,
        [
            {"name": "image", "type": "IMAGE", "links": [output_link_id]},
            {"name": "image_url", "type": "STRING", "links": None},
            {"name": "task_id", "type": "STRING", "links": None},
            {"name": "response", "type": "STRING", "links": None},
        ],
        [prompt, "1k", 1024, 1024, "png", family, False, 0, "fixed"],
        f"{prefix} {mode}",
    ))
    nodes.append(generator)
    save_id = generator_id + 1
    nodes.append(_save_image(save_id, output_link_id, filename, 3 if edit else 2))
    links.append([output_link_id, generator_id, 0, save_id, 0, "IMAGE"])
    _workflow(filename, nodes, links)


def layer_workflow(prefix, model):
    filename = f"{prefix}图层拆分.json"
    config, config_link = _config(2, 3, 1)
    config = _plugin(config)
    source = _load_image(2, 1)
    layer = _plugin(_node(
        3,
        "Seedream_V5_Pro_Layer_Decomposition",
        (410, 70),
        (510, 400),
        2,
        [
            {"name": "image", "type": "IMAGE", "link": 1},
            {"name": "api_config", "shape": 7, "type": "SEEDANCE_CONFIG", "link": 2},
        ],
        [
            {"name": "images", "type": "IMAGE", "links": [3]},
            {"name": "masks", "type": "MASK", "links": [4]},
            {"name": "image_urls", "type": "STRING", "links": None},
            {"name": "image_count", "type": "INT", "links": None},
            {"name": "task_id", "type": "STRING", "links": None},
            {"name": "response", "type": "STRING", "links": None},
        ],
        ["", "auto", "png", False, 0, "fixed", model],
        f"{prefix} 图层拆分",
    ))
    join = _core(_node(
        4,
        "JoinImageWithAlpha",
        (990, 120),
        (280, 100),
        3,
        [
            {"name": "image", "type": "IMAGE", "link": 3},
            {"name": "alpha", "type": "MASK", "link": 4},
        ],
        [{"name": "image", "type": "IMAGE", "links": [5]}],
        [],
    ))
    save = _save_image(5, 5, filename, 4)
    _workflow(
        filename,
        [config, source, layer, join, save],
        [
            [1, 2, 0, 3, 0, "IMAGE"],
            config_link,
            [3, 3, 0, 4, 0, "IMAGE"],
            [4, 3, 1, 4, 1, "MASK"],
            [5, 4, 0, 5, 0, "IMAGE"],
        ],
    )


if __name__ == "__main__":
    families = [
        ("seedream-v5-flash", "seedream-v5-flash (domestic)"),
        ("dola-seedream-5.0-flash", "dola-seedream-5.0-flash (overseas)"),
    ]
    for prefix, family in families:
        image_workflow(prefix, family, False)
        image_workflow(prefix, family, True)
        layer_workflow(prefix, f"{prefix}-layer-decomposition")
