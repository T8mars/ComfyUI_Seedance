"""Generate credential-free Topaz video restoration examples."""

from generate_latest_model_workflows import _config, _workflow
from generate_qwen21_animate_workflows import _generator, _save, _source


def topaz_workflow(local=True):
    filename = "Topaz视频高清修复本地素材.json" if local else "Topaz视频高清修复网址素材.json"
    generator_id = 3 if local else 2
    config_link = 2 if local else 1
    output_link = config_link + 1
    config, config_edge = _config(config_link, generator_id, 1)
    config["pos"] = [40, 430] if local else [40, 300]
    nodes, links = [config], [config_edge]
    if local:
        source = _source(2, "VIDEO", 1, 40)
        source["title"] = "选择需要高清修复的 MP4"
        nodes.append(source)
        links.append([1, 2, 0, generator_id, 0, "VIDEO"])
    inputs = [
        {"name": "input_video", "shape": 7, "type": "VIDEO", "link": 1 if local else None},
        {"name": "api_config", "shape": 7, "type": "SEEDANCE_CONFIG", "link": config_link},
    ]
    generator = _generator(
        generator_id, "Topaz_Video_Upscale", "VIDEO", inputs, output_link,
        ["" if local else "https://example.com/source.mp4", "1080p", "Max", False, 0, "fixed"],
        "Topaz 视频高清修复",
    )
    generator["size"] = [450, 260]
    nodes.append(generator)
    save = _save(generator_id + 1, "VIDEO", output_link, "保存高清修复视频")
    save["widgets_values"][0] = "seedance/topaz_upscale"
    nodes.append(save)
    links.append([output_link, generator_id, 0, save["id"], 0, "VIDEO"])
    _workflow(filename, nodes, links)


if __name__ == "__main__":
    topaz_workflow(True)
    topaz_workflow(False)
