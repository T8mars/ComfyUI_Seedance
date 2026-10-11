"""Generate MAI 2.6/Flash text, single-edit and composition examples."""

from generate_latest_model_workflows import _config, _workflow
from generate_qwen21_animate_workflows import _generator, _save, _source


def mai_workflow(model, count):
    mode = ["文生图", "图像编辑", "多图合成"][count]
    generator_id = count + 2
    config_link = count + 1
    output_link = config_link + 1
    config, config_edge = _config(config_link, generator_id, 5)
    config["pos"] = [40, 40 + count * 370] if count else [40, 250]
    nodes, links = [config], [config_edge]
    for index in range(1, count + 1):
        source = _source(index + 1, "IMAGE", index, 40 + (index - 1) * 370)
        source["title"] = f"选择参考图 {index}"
        nodes.append(source)
        links.append([index, index + 1, 0, generator_id, index - 1, "IMAGE"])
    inputs = [
        {"name": f"image{i}", "shape": 7, "type": "IMAGE", "link": i if i <= count else None}
        for i in range(1, 6)
    ] + [{"name": "api_config", "shape": 7, "type": "SEEDANCE_CONFIG", "link": config_link}]
    prompt = ["白色桌面上的红色陶瓷茶壶，柔和日光，干净的产品摄影",
              "将茶壶改为蓝色，保留形状、桌面和背景",
              "使用图1的主体，结合图2的颜色和光线，创作统一的产品海报"][count]
    nodes.append(_generator(
        generator_id, "MAI_Image_2_6", "IMAGE", inputs, output_link,
        [model, prompt, "1k", "1:1", "16:9", 1536, 1024, False, False, False, 0, "fixed"],
        f"MAI 2.6 {'Flash ' if model.endswith('flash') else ''}{mode}",
    ))
    save = _save(generator_id + 1, "IMAGE", output_link, "保存生成图片")
    save["widgets_values"] = [f"seedance/{model}_{['text', 'edit', 'composition'][count]}"]
    nodes.append(save)
    links.append([output_link, generator_id, 0, save["id"], 0, "IMAGE"])
    _workflow(f"{model}{mode}.json", nodes, links)


if __name__ == "__main__":
    for model in ("mai-image-2-6", "mai-image-2-6-flash"):
        for count in range(3):
            mai_workflow(model, count)
