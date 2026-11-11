"""Blank-key independent MiniMax H3 and Qwen Turbo workflows."""

from generate_kling_v4_workflows import Workflow


def main():
    for model, key in (("minimax-h3-image", "Minimax_H3_Image"), ("qwen-image-2.1-turbo", "Qwen_Image_2_1_Turbo")):
        for edit in (False, True):
            w = Workflow()
            node = w.generate(key, {"prompt": "Change the ceramic cup to blue, preserve its shape and composition." if edit else
                "A red ceramic cup beside a green leaf, clean studio product photography, no text.",
                "resolution": "720p" if edit and key == "Qwen_Image_2_1_Turbo" else "1k"}, title=model)
            if edit:
                w.config["pos"] = [40, 650]
                w.connect(w.load("IMAGE", 30, "选择编辑参考图"), 0, node, "image1")
            save = w.add("SaveImage", (1070, 80), (310, 250), [{"name": "images", "type": "IMAGE", "link": None}], [],
                         ["seedance/" + model + ("_edit" if edit else "_text")], "保存图片")
            w.connect(node, 0, save, "images")
            w.write(model + ("图像编辑.json" if edit else "文生图.json"))
    for mode in ("text", "image", "audio", "mixed"):
        w = Workflow()
        node = w.generate("Minimax_H3_ComfyUI_Max", {"seconds": "3", "prompt": "A blue ceramic teapot rotates gently on a white table, locked camera, soft studio light."}, title="MiniMax H3 ComfyUI Max")
        if mode in ("image", "mixed"):
            w.config["pos"] = [40, 1100 if mode == "mixed" else 650]
            w.connect(w.load("IMAGE", 30, "选择参考图"), 0, node, "image1")
        if mode in ("audio", "mixed"):
            w.config["pos"] = [40, 1100 if mode == "mixed" else 650]
            w.connect(w.load("AUDIO", 650 if mode == "mixed" else 30, "选择参考音频"), 0, node, "audio1")
        w.save_video(node, "h3_comfyui_max_" + mode)
        w.write("minimax-h3-comfyui-max" + {"text": "文生视频", "image": "图片参考", "audio": "音频参考", "mixed": "图片音频参考"}[mode] + ".json")


if __name__ == "__main__":
    main()
