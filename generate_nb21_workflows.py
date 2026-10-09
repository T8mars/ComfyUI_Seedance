"""Generate credential-free Nano Banana 2.1 workflows."""

from generate_latest_model_workflows import _config, _workflow
from generate_qwen21_animate_workflows import _generator, _save, _source


def nb21_workflow(edit=False):
    generator_id = 3 if edit else 2
    config_link = 2 if edit else 1
    output_link = config_link + 1
    config, config_edge = _config(config_link, generator_id, 14)
    nodes, links = [config], [config_edge]
    if edit:
        nodes.append(_source(2, "IMAGE", 1, 40))
        links.append([1, 2, 0, generator_id, 0, "IMAGE"])
    inputs = [
        {"name": f"image{i}", "shape": 7, "type": "IMAGE",
         "link": 1 if edit and i == 1 else None} for i in range(1, 15)
    ] + [{"name": "api_config", "shape": 7, "type": "SEEDANCE_CONFIG", "link": config_link}]
    nodes.append(_generator(
        generator_id, "Zhenzhen_Image_NB_2_1", "IMAGE", inputs, output_link,
        ["将茶壶改为蓝色，保留原有形状与桌面背景" if edit else "白色桌面上的红色陶瓷茶壶，柔和的摄影棚光线",
         "1k", "auto" if edit else "1:1", False, 0, "fixed"],
        "Nano Banana 2.1 图像编辑" if edit else "Nano Banana 2.1 文生图",
    ))
    save = _save(generator_id + 1, "IMAGE", output_link, "保存生成图片")
    save["widgets_values"] = [f"seedance/nb21_{'edit' if edit else 'text'}"]
    nodes.append(save)
    links.append([output_link, generator_id, 0, save["id"], 0, "IMAGE"])
    _workflow(f"zhenzhen-image-nb-2.1{'图像编辑' if edit else '文生图'}.json", nodes, links)


if __name__ == "__main__":
    nb21_workflow(False)
    nb21_workflow(True)
