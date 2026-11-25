"""Write blank-key Magi 2 and LLM example workflows."""

from generate_kling_v4_workflows import Workflow
from generate_llm_workflows import preview
from ComfyUI_Seedance.core.magi2 import MODELS


def main():
    modes = {
        "text": ("t2v", "文生", "A small blue cube slowly rotates on a plain white desk."),
        "frame": ("i2v", "首尾帧", "Move smoothly from the start frame to the end frame, preserving the subject and texture."),
        "reference": ("r2v", "混合参考", "Animate the subject from the image with motion from the reference clip and rhythm from the audio."),
    }
    for model in MODELS:
        for mode, (suffix, label, prompt) in modes.items():
            w = Workflow()
            node = w.generate("Magi_2_Video", {"model": model, "generation_type": mode, "prompt": prompt, "seconds": 4},
                              title=f"{model} · {label}")
            if mode != "text":
                w.connect(w.load("IMAGE", 30, "选择首帧图" if mode == "frame" else "选择参考图"), 0, node, "image1")
                w.config["pos"][1] = 730
            if mode == "frame":
                w.connect(w.load("IMAGE", 355, "选择尾帧图", "example_last.png"), 0, node, "image2")
            if mode == "reference":
                w.connect(w.load("VIDEO", 355, "选择 2–30 秒参考视频"), 0, node, "video1")
                w.connect(w.load("AUDIO", 680, "选择 2–30 秒参考音频"), 0, node, "audio1")
                w.config["pos"][1] = 1040
            w.save_video(node)
            name = model + "-" + suffix
            w.nodes[-1]["widgets_values"][0] = "seedance/" + name
            w.write(name + ".json")

    for model, vision in (("moonshotai/kimi-k3.1-pro", False), ("zhenzhen/gk-4.7", True)):
        w = Workflow()
        node = w.generate("Seedance_LLM_API", {"model": model, "stream": vision, "max_tokens": 1024,
            "prompt": "Describe this image in two sentences." if vision else "Write a short prompt for a quiet mountain sunrise."},
            title=model)
        if vision:
            w.connect(w.load("IMAGE", 30, "选择需要识别的图片"), 0, node, "image1")
        preview(w, node, (1050, 80))
        w.write(model.replace("/", "-") + ("-vision.json" if vision else "-text.json"))


if __name__ == "__main__":
    main()
