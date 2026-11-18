"""Write credential-free image, Qwen Audio 3.1 and GPT-6.2 examples."""

from generate_kling_v4_workflows import Workflow
from generate_llm_workflows import preview
from ComfyUI_Seedance.core import image_nov19, qwen_audio31


def save(workflow, source, file, media):
    node = workflow.add("SaveImage" if media == "IMAGE" else "SaveAudio", (1050, 80), (320, 240),
        [{"name": "images" if media == "IMAGE" else "audio", "type": media, "link": None}],
        [], ["seedance/" + file], "Save " + ("images" if media == "IMAGE" else "audio"))
    workflow.connect(source, 0, node, node["inputs"][0]["name"])
    workflow.write(file + ".json")


def main():
    for mode in ("text", "reference", "group"):
        w = Workflow()
        values = {"prompt": "An original blue ceramic teapot on a warm cream backdrop.", "size": "1:1"}
        if mode == "reference":
            values["prompt"] = "Keep the object in @Image1 and change the backdrop to pale yellow."
        if mode == "group":
            values.update(prompt="Two related views of an original blue teapot: straight on and from the side.",
                          sequential_image_generation="auto", max_images=2)
        node = w.generate("Kling_V4_Image", values, title="Kling 4 Image / " + mode)
        if mode == "reference":
            w.connect(w.load("IMAGE", 30, "Select a reference image (at least 300 px per side)"), 0, node, "image1")
        save(w, node, "kling-v4-image-" + mode, "IMAGE")
    for model in image_nov19.MAI_MODELS:
        for mode in ("text", "edit"):
            w = Workflow()
            values = {"model": model, "prompt": "An original blue teapot on a white table.", "background": "opaque"}
            if mode == "edit":
                values["prompt"] = "Keep the composition and change the main object to emerald green."
            elif model.endswith("flash"):
                values.update(size="custom_pixels", width=1536, height=1024)
            node = w.generate("MAI_Image_2_7", values, title=model + " / " + mode)
            if mode == "edit":
                w.connect(w.load("IMAGE", 30, "Select an image to edit"), 0, node, "image1")
            save(w, node, model + "-" + mode, "IMAGE")
    for model, suffix, props in (
        (qwen_audio31.FLASH, "", {"voice": qwen_audio31.VOICES[qwen_audio31.FLASH][0], "language_hint": "zh",
            "prompt": "\u4f60\u597d\uff0c\u6b22\u8fce\u6536\u542c\u4eca\u5929\u7684\u8282\u76ee\u3002"}),
        (qwen_audio31.PLUS, "", {"voice": qwen_audio31.VOICES[qwen_audio31.PLUS][0], "language_hint": "en",
            "prompt": "Thanks for listening. I hope you enjoy the show."}),
        (qwen_audio31.NEXT, "-text", {"prompt": "A short morning radio greeting with an upbeat, friendly delivery."}),
        (qwen_audio31.NEXT, "-reference", {"prompt": "A short electronic chime in the style of @voice1, with no speech."}),
    ):
        w = Workflow()
        node = w.generate("Qwen_Audio_3_1_TTS", {"model": model, **props}, title=model)
        if suffix == "-reference":
            w.connect(w.load("AUDIO", 25, "Select permitted reference audio (up to 30 s)"), 0, node, "audio1")
        save(w, node, model + suffix, "AUDIO")
    for variant, vision in (("astra", False), ("sol", True)):
        w = Workflow()
        model = "zhenzhen/g6.2-" + variant
        node = w.generate("Seedance_LLM_API", {"model": model, "stream": vision, "max_tokens": 256,
            "prompt": "Briefly describe this image." if vision else "Write one sentence about a bright, quiet studio."},
            title=model)
        if vision:
            w.connect(w.load("IMAGE", 30, "Select an image to describe"), 0, node, "image1")
        preview(w, node, (1050, 80))
        w.write("zhenzhen-g6.2-" + variant + ("-vision-stream" if vision else "-text") + ".json")


if __name__ == "__main__":
    main()
