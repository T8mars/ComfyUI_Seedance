"""Create image/GIF examples with original animation saving and fixed cache seeds."""

from generate_kling_v4_workflows import Workflow


def save_image(workflow, source, prefix):
    target = workflow.add("SaveImage", (1050, 60), (330, 300),
        [{"name": "images", "type": "IMAGE", "link": None}], [], [prefix], "保存图片")
    workflow.connect(source, 0, target, "images")


def save_gif(workflow, source, prefix, slot=0, original=False, pos=(1050, 60), fps=10.0):
    target = workflow.add("Seedance_Save_GIF", pos, (430, 420), [
        {"name": "images", "type": "IMAGE", "shape": 7, "link": None},
        {"name": "source_path", "type": "STRING", "shape": 7, "link": None},
        {"name": "durations_json", "type": "STRING", "shape": 7, "link": None},
    ], [("gif_path", "STRING"), ("durations_json", "STRING")],
        [prefix, "auto" if original else "frames", fps, 0], "保存原始 GIF" if original else "将帧保存为 GIF")
    workflow.connect(source, slot, target, "images")
    if original:
        workflow.connect(source, 4, target, "source_path")
        workflow.connect(source, 7, target, "durations_json")
    return target


def main():
    for suffix in ("lowprice", "flare", "sunburst"):
        model = "zhenzhen-image-g-v2.6-" + suffix
        for mode in ("text", "edit", "gif"):
            workflow = Workflow()
            gif = mode == "gif"
            node = workflow.generate("Zhenzhen_Image_G26", {
                "model": model, "mode": "gif" if gif else "image", "quality": "low",
                "prompt": ("A red ball bounces up and down on a white floor. Create a seamless animated looping GIF, fixed camera, no text." if gif else
                           "Preserve the subject and change the background to a clean mint studio." if mode == "edit" else
                           "A small original blue toy robot on a clean mint tabletop, soft studio lighting."),
                "filename_prefix": "seedance/" + model + "_" + mode,
            }, title=model + (" GIF 动画：原文件自动保存与预览" if gif else " 图像编辑" if mode == "edit" else " 文生图"))
            if mode == "edit":
                workflow.connect(workflow.load("IMAGE", 30, "选择参考图"), 0, node, "image1")
            if gif:
                save_gif(workflow, node, "seedance/saved_" + model, original=True)
            workflow.write(model + {"text": "文生图.json", "edit": "图像编辑.json", "gif": "GIF动画.json"}[mode])
    workflow = Workflow()
    node = workflow.generate("Z_Image_T2I", {
        "prompt": "A small original blue toy robot on a mint tabletop, studio photo.", "seed": 42,
    }, title="Z-image 文生图")
    save_image(workflow, node, "seedance/z_image")
    workflow.write("z-image-t2i文生图.json")
    for mode in ("t2i", "i2i"):
        workflow = Workflow()
        model = "krea-v3-" + mode
        node = workflow.generate("Krea_V3_Image", {
            "model": model, "prompt": "A small original blue toy robot on a mint tabletop, soft studio photo.", "seed": 42,
        }, title=model)
        if mode == "i2i":
            workflow.connect(workflow.load("IMAGE", 30, "选择参考图"), 0, node, "image1")
        save_image(workflow, node, "seedance/" + model)
        workflow.write(model + ("图像编辑.json" if mode == "i2i" else "文生图.json"))
    workflow = Workflow()
    collector = workflow.add("SeedanceConcurrent_Image_Await", (1070, 60), (510, 1180),
        [{"name": f"future_{i}", "type": "SEEDANCE_IMAGE_FUTURE", "shape": 7, "link": None} for i in range(1, 31)],
        [(f"image_{i}", "IMAGE") for i in range(1, 31)] + [("status_json", "STRING")], ["raise"], "三模型 GIF 并发接收与预览")
    for i, suffix in enumerate(("lowprice", "flare", "sunburst"), 1):
        node = workflow.generate("Zhenzhen_Image_G26", {
            "model": "zhenzhen-image-g-v2.6-" + suffix, "mode": "gif", "quality": "low",
            "prompt": "A red ball bounces on a white floor. Create a seamless animated looping GIF, fixed camera.",
            "filename_prefix": "seedance/g26_concurrent_" + suffix,
        }, pos=(440, 60 + (i - 1) * 900), title=suffix + " GIF 并发提交")
        node["type"] = "SeedanceConcurrent_Zhenzhen_Image_G26_Submit"
        node["properties"]["Node name for S&R"] = node["type"]
        node["outputs"] = [{"name": "future", "type": "SEEDANCE_IMAGE_FUTURE", "links": None}]
        workflow.connect(node, 0, collector, f"future_{i}")
        save_gif(workflow, collector, "seedance/concurrent_saved_" + suffix, slot=i - 1,
                 pos=(1720, 60 + (i - 1) * 600), fps=10.0 if suffix == "lowprice" else 5.0)
    workflow.write("G26GIF三模型并发.json")

    workflow = Workflow()
    workflow.nodes.remove(workflow.config)
    first = workflow.load("IMAGE", 40, "选择第一帧", "example_first.png")
    second = workflow.load("IMAGE", 420, "选择第二帧", "example_second.png")
    batch = workflow.add("ImageBatch", (440, 80), (300, 150), [
        {"name": "image1", "type": "IMAGE", "link": None}, {"name": "image2", "type": "IMAGE", "link": None},
    ], [("IMAGE", "IMAGE")], [], "合并动画帧")
    batch["properties"].pop("aux_id", None)
    batch["properties"]["cnr_id"] = "comfy-core"
    workflow.connect(first, 0, batch, "image1")
    workflow.connect(second, 0, batch, "image2")
    save_gif(workflow, batch, "seedance/local_frames", pos=(850, 80), fps=2.0)
    workflow.write("保存GIF_本地图像帧.json")


if __name__ == "__main__":
    main()
