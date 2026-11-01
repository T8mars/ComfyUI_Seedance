"""Create safe HY, Muse and four-model FLUX examples."""

from generate_kling_v4_workflows import Workflow


def save_image(workflow, source, suffix):
    node = workflow.add("SaveImage", (1050, 80), (310, 240),
        [{"name": "images", "type": "IMAGE", "link": None}], [],
        [f"seedance/{suffix}"], "保存图片")
    workflow.connect(source, 0, node, "images")


def main():
    prompt = "An original small blue toy robot with a yellow chest badge in a bright mint studio, clear geometric shapes."
    for mode in ("text", "reference", "custom"):
        workflow = Workflow()
        values = {"prompt": prompt, "size": "1:1", "seed": 42}
        if mode == "reference":
            values.update(prompt="Combine both references in one clean mint studio. Keep the subjects and their colors.", size="auto")
        if mode == "custom":
            values.update(size="custom", width=1280, height=720)
        node = workflow.generate("HY_Image_3_5_Preview", values, title="HY 3.5 Preview 文生图/多图参考")
        if mode == "reference":
            for i in (1, 2):
                source = workflow.load("IMAGE", 30 + (i - 1) * 510, "选择参考图", "example.png" if i == 1 else "example_reference.png")
                workflow.connect(source, 0, node, f"image{i}")
        save_image(workflow, node, f"hy35_{mode}")
        workflow.write("HY35Preview" + {"text": "文生图", "reference": "多图编辑", "custom": "自定义尺寸"}[mode] + ".json")
    for video in (False, True):
        for reference in (False, True):
            workflow = Workflow()
            values = {"prompt": "Gently animate the blue toy robot waving once in a mint studio, soft mechanical sounds."
                      if video else prompt, "size": "16:9" if video else "1:1"}
            node = workflow.generate("Muse_Video" if video else "Muse_Image", values,
                                     title="Muse 约10秒720p带音频视频" if video else "Muse 图像生成/合成")
            if reference:
                for i in (1, 2):
                    workflow.connect(workflow.load("IMAGE", 30 + (i - 1) * 510, "选择构图参考图",
                        "example.png" if i == 1 else "example_reference.png"), 0, node, f"image{i}")
            if video:
                workflow.save_video(node, "muse_reference" if reference else "muse_text")
                workflow.nodes[-1]["widgets_values"][0] = "seedance/muse_video"
            else:
                save_image(workflow, node, "muse_reference" if reference else "muse_text")
            workflow.write(("MuseVideo" if video else "MuseImage") + ("多图参考" if reference else "文本生成") + ".json")
    for model in ("flux-3-image-t2i", "flux-3-image-i2i", "flux-3-image-klein-t2i", "flux-3-image-klein-i2i"):
        workflow = Workflow()
        edit = model.endswith("-i2i")
        values = {"model": model, "prompt": "Keep the robot and its colors, change the studio wall to coral red." if edit else prompt,
                  "resolution": "768sq", "aspect_ratio": "1:1", "seed": 42}
        node = workflow.generate("Flux_3_Image_Variants", values, title=model + (" 图像编辑" if edit else " 文生图"))
        if edit:
            workflow.connect(workflow.load("IMAGE", 30, "选择编辑参考图"), 0, node, "image1")
        save_image(workflow, node, model)
        workflow.write(model + ("图像编辑" if edit else "文生图") + ".json")


if __name__ == "__main__":
    main()
