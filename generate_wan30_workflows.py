"""Generate safe Wan 3.0 I2V and R2V example workflows."""

from __future__ import annotations

from pathlib import Path

from generate_latest_model_workflows import _node, _workflow


CONFIG_SLOT = 20


def _config(target_id: int, link_id: int):
    node = _node(
        1,
        "Seedance_Config",
        (40, 760),
        (300, 82),
        0,
        [],
        [{"name": "api_config", "type": "SEEDANCE_CONFIG", "links": [link_id]}],
        ["https://api.seedance.nz", ""],
    )
    return node, [link_id, 1, 0, target_id, CONFIG_SLOT, "SEEDANCE_CONFIG"]


def _media_inputs(image_links=None, video_links=None, audio_links=None, config_link=0):
    image_links = image_links or {}
    video_links = video_links or {}
    audio_links = audio_links or {}
    inputs = [
        {
            "name": f"image{index}",
            "shape": 7,
            "type": "IMAGE",
            "link": image_links.get(index),
        }
        for index in range(1, 11)
    ]
    inputs.extend({
        "name": f"video{index}",
        "shape": 7,
        "type": "VIDEO",
        "link": video_links.get(index),
    } for index in range(1, 6))
    inputs.extend({
        "name": f"audio{index}",
        "shape": 7,
        "type": "AUDIO",
        "link": audio_links.get(index),
    } for index in range(1, 6))
    inputs.append({
        "name": "api_config",
        "shape": 7,
        "type": "SEEDANCE_CONFIG",
        "link": config_link,
    })
    return inputs


def _video_outputs(link_id: int):
    return [
        {"name": "video", "type": "VIDEO", "links": [link_id]},
        {"name": "video_url", "type": "STRING", "links": None},
        {"name": "task_id", "type": "STRING", "links": None},
        {"name": "response", "type": "STRING", "links": None},
    ]


def _load_image(node_id: int, link_id: int, pos, filename: str, title: str, order: int):
    return _node(
        node_id,
        "LoadImage",
        pos,
        (270, 310),
        order,
        [],
        [
            {"name": "IMAGE", "type": "IMAGE", "links": [link_id]},
            {"name": "MASK", "type": "MASK", "links": None},
        ],
        [filename, "image"],
        title,
    )


def _save_video(node_id: int, source_id: int, link_id: int, filename: str, order: int):
    return _node(
        node_id,
        "SaveVideo",
        (1060, 280),
        (300, 190),
        order,
        [{"name": "video", "type": "VIDEO", "link": link_id}],
        [{"name": "video", "type": "VIDEO", "links": None}],
        [f"video/{Path(filename).stem}", "auto", "auto"],
    )


def _i2v_workflow(model: str, filename: str, global_model: bool):
    generator_id = 4
    config_link = 3
    output_link = 4
    config, config_edge = _config(generator_id, config_link)
    nodes = [
        config,
        _load_image(2, 1, (40, 40), "选择首帧.png", "选择首帧", 1),
        _load_image(3, 2, (350, 40), "选择尾帧.png", "选择可选尾帧", 2),
        _node(
            generator_id,
            "Wan_3_0_Video",
            (680, 100),
            (430, 570),
            3,
            _media_inputs(image_links={1: 1, 2: 2}, config_link=config_link),
            _video_outputs(output_link),
            [
                model,
                "主体从首帧自然运动到尾帧，动作连续，镜头平稳推进，光影保持一致",
                "2",
                "480P",
                "adaptive",
                True,
                global_model,
                "",
                "",
                1,
                "fixed",
                False,
            ],
            f"{model} 首尾帧图生视频",
        ),
        _save_video(5, generator_id, output_link, filename, 4),
    ]
    links = [
        [1, 2, 0, generator_id, 0, "IMAGE"],
        [2, 3, 0, generator_id, 1, "IMAGE"],
        config_edge,
        [output_link, generator_id, 0, 5, 0, "VIDEO"],
    ]
    _workflow(filename, nodes, links)


def _r2v_workflow(model: str, filename: str, global_model: bool):
    generator_id = 5
    config_link = 4
    output_link = 5
    config, config_edge = _config(generator_id, config_link)
    nodes = [
        config,
        _load_image(2, 1, (40, 40), "选择参考图.png", "选择参考图", 1),
        _node(
            3,
            "LoadVideo",
            (40, 390),
            (300, 120),
            2,
            [],
            [{"name": "VIDEO", "type": "VIDEO", "links": [2]}],
            ["选择参考视频.mp4"],
            "选择参考视频",
        ),
        _node(
            4,
            "LoadAudio",
            (40, 550),
            (300, 120),
            3,
            [],
            [{"name": "AUDIO", "type": "AUDIO", "links": [3]}],
            ["选择参考音频.wav", None, ""],
            "选择参考音频",
        ),
        _node(
            generator_id,
            "Wan_3_0_Video",
            (430, 100),
            (520, 770),
            4,
            _media_inputs(
                image_links={1: 1},
                video_links={1: 2},
                audio_links={1: 3},
                config_link=config_link,
            ),
            _video_outputs(output_link),
            [
                model,
                "Image 1 中的主体进入 Video 1 的场景，动作节奏跟随 Audio 1，保持人物特征和镜头连续性",
                "2",
                "480P",
                "adaptive",
                True,
                global_model,
                "",
                "",
                1,
                "fixed",
                False,
            ],
            f"{model} 多模态参考生视频",
        ),
        _save_video(6, generator_id, output_link, filename, 5),
    ]
    links = [
        [1, 2, 0, generator_id, 0, "IMAGE"],
        [2, 3, 0, generator_id, 10, "VIDEO"],
        [3, 4, 0, generator_id, 15, "AUDIO"],
        config_edge,
        [output_link, generator_id, 0, 6, 0, "VIDEO"],
    ]
    _workflow(filename, nodes, links)


def main():
    _i2v_workflow("wan-3.0-i2v", "wan-3.0-i2v首尾帧图生视频.json", False)
    _r2v_workflow("wan-3.0-r2v", "wan-3.0-r2v多模态参考生视频.json", False)
    _i2v_workflow(
        "wan-3.0-global-i2v",
        "wan-3.0-global-i2v海外首尾帧图生视频.json",
        True,
    )
    _r2v_workflow(
        "wan-3.0-global-r2v",
        "wan-3.0-global-r2v海外多模态参考生视频.json",
        True,
    )


if __name__ == "__main__":
    main()
