"""Generate the two credential-free Ideogram 4.6 examples."""

from generate_image26_workflows import save_image
from generate_kling_v4_workflows import Workflow


def main():
    w = Workflow()
    node = w.generate("Ideogram_V4_6", {
        "prompt": "A single teal bicycle sticker, centered, no text or shadows.",
        "background": "transparent", "quality": "low",
    }, title="Ideogram 4.6 文生图 · 透明背景")
    rgba = w.add("JoinImageWithAlpha", (1010, 60), (295, 150),
                 [{"name": "image", "type": "IMAGE", "link": None},
                  {"name": "alpha", "type": "MASK", "link": None}],
                 [("IMAGE", "IMAGE")], [], "恢复透明度")
    rgba["properties"].pop("aux_id", None)
    rgba["properties"]["cnr_id"] = "comfy-core"
    w.connect(node, 0, rgba, "image")
    w.connect(node, 4, rgba, "alpha")
    save_image(w, rgba, "seedance/ideogram-v4.6")
    w.nodes[-1]["pos"] = [1370, 60]
    w.write("ideogram-v4.6.json")

    w = Workflow()
    node = w.generate("Ideogram_V4_6_Edit", {
        "prompt": "Replace the background with a clean ivory studio, keeping the main subject unchanged.",
        "quality": "low",
    }, title="Ideogram 4.6 图像编辑 · image1 为原图")
    w.connect(w.load("IMAGE", 30, "选择待编辑原图"), 0, node, "image1")
    save_image(w, node, "seedance/ideogram-v4.6-edit")
    w.write("ideogram-v4.6-edit.json")


if __name__ == "__main__":
    main()
