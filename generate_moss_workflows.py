"""Generate credential-free Moss text and single-reference editing workflows."""

from generate_latest_model_workflows import _config, _workflow
from generate_qwen21_animate_workflows import _generator, _save, _source


def moss_workflow(edit=False):
    generator_id = 3 if edit else 2
    config_link = 2 if edit else 1
    output_link = config_link + 1
    config, config_edge = _config(config_link, generator_id, 1)
    config["pos"] = [40, 440] if edit else [40, 250]
    graph, links = [config], [config_edge]
    if edit:
        graph.append(_source(2, "IMAGE", 1, 60))
        links.append([1, 2, 0, generator_id, 0, "IMAGE"])
    inputs = [
        {"name": "image1", "type": "IMAGE", "shape": 7, "link": 1 if edit else None},
        {"name": "api_config", "type": "SEEDANCE_CONFIG", "shape": 7, "link": config_link},
    ]
    mode = "图像编辑" if edit else "文生图"
    generator = _generator(
        generator_id, "Moss_Image", "IMAGE", inputs, output_link,
        ["将茶壶改为蓝色，保留原有形状、桌面和构图" if edit else
         "木桌上的红色陶瓷茶壶，柔和自然光，干净的产品摄影", "9:16", False, 0, "fixed"],
        f"Moss Image {mode}",
    )
    generator["size"] = [480, 330]
    graph.append(generator)
    save = _save(generator_id + 1, "IMAGE", output_link, "保存生成图片")
    save["widgets_values"] = [f"seedance/moss_{'edit' if edit else 'text'}"]
    graph.append(save)
    links.append([output_link, generator_id, 0, save["id"], 0, "IMAGE"])
    _workflow(f"moss-image{mode}.json", graph, links)


if __name__ == "__main__":
    moss_workflow(False)
    moss_workflow(True)
