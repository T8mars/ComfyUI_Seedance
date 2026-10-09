"""Generate credential-free FLUX 3 Image and Vidu Q4 examples."""

from generate_latest_model_workflows import _config, _node, _workflow
from generate_qwen21_animate_workflows import _core, _generator, _save, _source


def flux_workflow(edit=False):
    filename = "flux-3-image图像编辑.json" if edit else "flux-3-image文生图.json"
    generator_id = 3 if edit else 2
    config_link = 2 if edit else 1
    output_link = config_link + 1
    config, config_edge = _config(config_link, generator_id, 10)
    nodes, links = [config], [config_edge]
    if edit:
        nodes.append(_source(2, "IMAGE", 1, 40))
        links.append([1, 2, 0, generator_id, 0, "IMAGE"])
    inputs = [
        {"name": f"image{i}", "shape": 7, "type": "IMAGE",
         "link": 1 if edit and i == 1 else None} for i in range(1, 11)
    ] + [{"name": "api_config", "shape": 7, "type": "SEEDANCE_CONFIG", "link": config_link}]
    nodes.append(_generator(
        generator_id, "Flux_3_Image", "IMAGE", inputs, output_link,
        ["保留红色茶壶，将背景改为浅绿色" if edit else "白色桌面上的红色陶瓷茶壶，干净的产品摄影",
         "1k", "1:1", True, 2, False, 0, "fixed"],
        "FLUX 3 Image 图像编辑" if edit else "FLUX 3 Image 文生图",
    ))
    save = _save(generator_id + 1, "IMAGE", output_link, "保存生成图片")
    save["widgets_values"] = [f"seedance/flux_3_{'edit' if edit else 'text'}"]
    nodes.append(save)
    links.append([output_link, generator_id, 0, save["id"], 0, "IMAGE"])
    _workflow(filename, nodes, links)


def vidu_workflow(model):
    reference = model.endswith("-r2v")
    generator_id = 4 if reference else 3
    config_link = 3 if reference else 2
    output_link = config_link + 1
    config, config_edge = _config(config_link, generator_id, 18)
    nodes = [config, _source(2, "IMAGE", 1, 40)]
    links = [config_edge, [1, 2, 0, generator_id, 0, "IMAGE"]]
    if reference:
        nodes.append(_core(_node(
            3, "LoadAudio", (40, 430), (300, 130), 2, [],
            [{"name": "AUDIO", "type": "AUDIO", "links": [2]}],
            ["example.mp3", None, ""], "选择参考音频（可选）",
        )))
        links.append([2, 3, 0, generator_id, 15, "AUDIO"])
    inputs = [
        {"name": f"image{i}", "shape": 7, "type": "IMAGE", "link": 1 if i == 1 else None}
        for i in range(1, 16)
    ] + [
        {"name": f"audio{i}", "shape": 7, "type": "AUDIO",
         "link": 2 if reference and i == 1 else None} for i in range(1, 4)
    ] + [{"name": "api_config", "shape": 7, "type": "SEEDANCE_CONFIG", "link": config_link}]
    nodes.append(_generator(
        generator_id, "Vidu_Q4_Preview_Video", "VIDEO", inputs, output_link,
        [model, "红色茶壶在桌面上缓缓旋转，镜头保持稳定", "5", "720p", "16:9",
         True, True, False, "", "", "", False, 0, "fixed"],
        "Vidu Q4 Preview 参考生视频" if reference else "Vidu Q4 Preview 图生视频",
    ))
    save = _save(generator_id + 1, "VIDEO", output_link, "保存生成视频")
    save["widgets_values"][0] = f"seedance/{model}"
    nodes.append(save)
    links.append([output_link, generator_id, 0, save["id"], 0, "VIDEO"])
    _workflow(f"{model}{'参考生视频' if reference else '图生视频'}.json", nodes, links)


if __name__ == "__main__":
    flux_workflow(False)
    flux_workflow(True)
    for model in (
        "vidu-q4-preview-i2v", "vidu-q4-preview-r2v",
        "vidu-q4-preview-global-i2v", "vidu-q4-preview-global-r2v",
    ):
        vidu_workflow(model)
