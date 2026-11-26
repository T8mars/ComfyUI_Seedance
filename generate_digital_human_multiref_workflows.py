"""Write three blank-key workflows without modifying the single-reference examples."""

from generate_kling_v4_workflows import Workflow
from generate_nov19_workflows import save
from generate_nov21_workflows import reference, video_example


def main():
    for token in (False, True):
        suffix = "-token" if token else ""
        w = Workflow()
        node = w.generate("Minimax_H3_ComfyUI_Digital_Human" + ("_Token" if token else ""), {
            "prompt": "Use <Picture 1>, <Picture 2> and <Picture 3> as views of the same presenter. Keep the face consistent and look toward the camera.",
            "seconds": "5",
        }, title="MiniMax H3 Digital Human" + (" / Token" if token else ""))
        for i, view in enumerate(("front", "three-quarter", "side"), 1):
            reference(w, node, "IMAGE", f"image{i}", 30 + (i - 1) * 330,
                      f"Select the {view} view of the same person", f"example_{i}.png")
        reference(w, node, "AUDIO", "audio1", 1020, "Select speech up to 5 seconds")
        video_example(w, node, f"minimax-h3-comfyui-digital-human{suffix}-3refs")

    w = Workflow()
    node = w.generate("Zhenzhen_Image_GK_V15", {"model": "zhenzhen-image-gk-v15-edit",
        "prompt": "Create a product photo of the object in image 1, using the other images as design, lighting and composition references."},
        title="Zhenzhen Image GK v1.5 Edit / 5 references")
    for i in range(1, 6):
        reference(w, node, "IMAGE", f"image{i}", 30 + (i - 1) * 330, f"Select reference {i}", f"example_{i}.png")
    save(w, node, "zhenzhen-image-gk-v15-edit-5refs", "IMAGE")


if __name__ == "__main__":
    main()
