"""Credential-free examples for Flash, H3 ComfyUI, Fable and voice-library TTS."""

from generate_kling_v4_workflows import Workflow
from generate_llm_workflows import preview


def save_video(workflow, source, suffix):
    workflow.save_video(source, suffix)
    workflow.nodes[-1]["widgets_values"][0] = "seedance/" + suffix


def main():
    for region in ("", "global-"):
        for mode in ("t2v", "i2v", "multi"):
            model = f"seedance-2.5-{region}flash-{mode}"
            for end in ([False, True] if mode == "i2v" else [False]):
                workflow = Workflow()
                node = workflow.generate("Seedance_2_5_Video", {"model": model, "seconds": "4", "resolution": "480p", "ratio": "adaptive",
                    "prompt": "A small blue puppet waves gently in a bright studio. Keep its appearance consistent."}, title=model)
                if mode in ("i2v", "multi"):
                    workflow.connect(workflow.load("IMAGE", 30, "Select first frame / reference image"), 0, node, "image1")
                if end:
                    workflow.connect(workflow.load("IMAGE", 430, "Select last frame", "example_last.png"), 0, node, "image2")
                if mode == "multi":
                    workflow.connect(workflow.load("VIDEO", 430, "Select 2-30s reference video"), 0, node, "video1")
                    workflow.connect(workflow.load("AUDIO", 830, "Select 2-30s reference audio"), 0, node, "audio1")
                workflow.config["pos"] = [40, 1230 if mode == "multi" else 830 if end else 430]
                suffix = model + ("-first-last" if end else "-mixed" if mode == "multi" else "")
                save_video(workflow, node, suffix)
                workflow.write(suffix + ".json")
    models = [
        ("minimax-h3-comfyui-charswap", "Minimax_H3_ComfyUI_CharSwap", ["seconds", "frames"]),
        ("minimax-h3-comfyui-wuxi", "Minimax_H3_ComfyUI_Wuxi", ["text", "mixed", "url-video"]),
        ("minimax-h3-comfyui-max-10020", "Minimax_H3_ComfyUI_Max_10020", ["text", "mixed"]),
        ("minimax-h3-comfyui-max-10021", "Minimax_H3_ComfyUI_Max_10021", ["text", "mixed"]),
    ]
    for model, key, modes in models:
        for mode in modes:
            workflow = Workflow()
            values = {"prompt": "A blue puppet waves once on a bright studio stage, locked camera.", "resolution": "480p", "seconds": "3" if "1002" in model else "5", "ratio": "auto" if "charswap" in model else "16:9"}
            if mode == "frames":
                values.update(duration_mode="frames", frames=124)
            if mode == "url-video":
                values["video_urls"] = "https://example.com/your-reference.mp4"
            if mode != "text":
                values["prompt"] = "<Picture 1> is the main character. Preserve its identity and animate a gentle wave, with a bright studio background."
            node = workflow.generate(key, values, title=model + " / " + mode)
            if mode != "text":
                workflow.connect(workflow.load("IMAGE", 30, "Select character / reference image"), 0, node, "image1")
            if "charswap" in model or key.endswith("Wuxi") and mode == "mixed":
                workflow.connect(workflow.load("VIDEO", 430, "Select source / motion video"), 0, node, "video1")
            if mode == "mixed":
                workflow.connect(workflow.load("AUDIO", 830, "Select reference audio"), 0, node, "audio1")
            workflow.config["pos"] = [40, 1230 if mode == "mixed" else 830 if "charswap" in model else 430]
            save_video(workflow, node, model + "-" + mode)
            workflow.write(model + "-" + mode + ".json")
    for vision in (False, True):
        workflow = Workflow()
        node = workflow.generate("Seedance_LLM_API", {"model": "zhenzhen-fb-5.2", "prompt": "Describe this image briefly." if vision else "Write a concise video prompt about a calm studio scene.", "max_tokens": 512}, title="Fable 5.2")
        if vision:
            workflow.connect(workflow.load("IMAGE", 30, "Select image to describe"), 0, node, "image1")
            workflow.config["pos"] = [40, 430]
        preview(workflow, node, (1050, 80))
        workflow.write("zhenzhen-fb-5.2-" + ("vision" if vision else "text") + ".json")
    for speaker, suffix in (("zh_female_vv_uranus_bigtts", "vivi"), ("zh_male_lubanqihao_uranus_bigtts", "lubanqihao")):
        workflow = Workflow()
        node = workflow.generate("Doubao_Seed_TTS_2_0", {"speaker": speaker, "prompt": "\u4f60\u597d\uff0c\u4eca\u5929\u7684\u6d4b\u8bd5\u5df2\u7ecf\u5b8c\u6210\u3002", "context_texts": "\u8bf7\u7528\u81ea\u7136\u4eb2\u5207\u7684\u8bed\u6c14\u8bf4\u3002"}, title="Doubao TTS 2.0 / Voice Library")
        save = workflow.add("SaveAudio", (1050, 80), (310, 220), [{"name": "audio", "type": "AUDIO", "link": None}], [], ["seedance/doubao_tts_" + suffix], "Save audio")
        workflow.connect(node, 0, save, "audio")
        workflow.write("doubao-seed-tts-2.0-" + suffix + ".json")


if __name__ == "__main__":
    main()
