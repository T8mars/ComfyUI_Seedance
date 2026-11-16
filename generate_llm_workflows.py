"""Blank-key Seedance-only text, vision, streaming and conversation examples."""

from generate_kling_v4_workflows import Workflow


def preview(workflow, source, pos):
    node = workflow.add("PreviewAny", pos, (430, 330), [{"name": "source", "type": "*", "link": None}],
                        [("STRING", "STRING")], [], "预览回答")
    workflow.connect(source, 0, node, "source")


def main():
    for mode in ("text", "vision", "stream", "history"):
        w = Workflow()
        prompt = "Write a concise cinematic video prompt for a quiet lakeside sunrise." if mode != "vision" else "Describe the subject, colors and composition of the image in Chinese."
        first = w.generate("Seedance_LLM_API", {"prompt": prompt, "stream": mode == "stream"}, title="Seedance LLM: " + mode)
        first["size"] = [560, 720]
        if mode == "vision":
            w.config["pos"] = [40, 650]
            w.connect(w.load("IMAGE", 40, "选择需要识别的图片"), 0, first, "image1")
        if mode == "history":
            second = w.generate("Seedance_LLM_API", {"prompt": "Keep the same scene and rewrite the preceding answer as a single English sentence."},
                                pos=(1120, 60), title="继续上一轮对话")
            second["size"] = [560, 720]
            w.connect_widget(first, 2, second, "history")
            preview(w, first, (440, 950))
            preview(w, second, (1120, 950))
        else:
            preview(w, first, (1100, 80))
        w.write("SeedanceLLM" + {"text": "文本对话", "vision": "图片理解", "stream": "流式返回", "history": "多轮历史连线"}[mode] + ".json")


if __name__ == "__main__":
    main()
