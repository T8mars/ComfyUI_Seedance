"""Write blank-key examples for the Nov 21 image, speech, video and 3D models."""

from generate_kling_v4_workflows import Workflow
from generate_llm_workflows import preview
from generate_nov19_workflows import save
from ComfyUI_Seedance.core import nov21_models as spec


def reference(w, dst, kind, slot, y, title, filename=None):
    source = w.load(kind, y, title, filename)
    w.connect(source, 0, dst, slot)
    w.config["pos"][1] = max(w.config["pos"][1], y + 340)


def video_example(w, node, filename):
    w.save_video(node)
    w.nodes[-1]["widgets_values"][0] = "seedance/" + filename
    w.write(filename + ".json")


def main():
    for mode in ("ecommerce", "webpage", "webpage-roles"):
        w = Workflow()
        commerce = mode == "ecommerce"
        prompt = "Create a short product detail page for the teapot in @Image1 with a clear hero and material details."
        if not commerce:
            prompt = "Design a pottery studio landing page with a hero, two featured products and workshop details."
        if mode == "webpage-roles":
            prompt += " Use @Image1 for the visual style and @Image2 as the featured object."
        node = w.generate("Kling_V4_Long_Image", {"prompt": prompt,
            "skill": "ecommerce" if commerce else "webpage", "length": "short"}, title="Kling 4 Long Image / " + mode)
        if commerce:
            reference(w, node, "IMAGE", "image1", 30, "Select your product photo")
        elif mode == "webpage-roles":
            reference(w, node, "IMAGE", "style_image", 30, "Select a visual style image")
            reference(w, node, "IMAGE", "subject_image", 420, "Select the featured object image", "example_subject.png")
        save(w, node, "kling-v4-long-image-" + mode, "IMAGE")
    for model, voice in zip(spec.GEMINI_TTS, ("Kore", "Puck")):
        w = Workflow()
        node = w.generate("Gemini_2_5_TTS", {"model": model, "voice": voice, "prompt": "Hello. Welcome to the studio.",
            "instructions": "Speak clearly in a warm, relaxed tone."}, title=model)
        save(w, node, model.replace("/", "-"), "AUDIO")
    for suffix in ("gm-4-hydrogen", "gm-4-carbon", "gm-4-neon", "hy-4-flash"):
        w = Workflow()
        vision = suffix in ("gm-4-neon", "hy-4-flash")
        node = w.generate("Seedance_LLM_API", {"model": "zhenzhen/" + suffix, "max_tokens": 256,
            "prompt": "Describe the main object in this image in one sentence." if vision else "Summarize a pottery workshop in one sentence.",
            "stream": suffix == "gm-4-neon"}, title="zhenzhen/" + suffix)
        if vision:
            reference(w, node, "IMAGE", "image1", 30, "Select an image to describe")
        preview(w, node, (1050, 80))
        w.write("zhenzhen-" + suffix + ("-vision" if vision else "-text") + ".json")
    for suffix, key, audio, video in (
        ("max-10020-token", "Max_10020_Token", True, False),
        ("max-10021-token", "Max_10021_Token", False, False),
        ("max-10021-token-video", "Max_10021_Token", False, True),
        ("charswap-token", "CharSwap_Token", False, True),
        ("digital-human-token", "Digital_Human_Token", True, False),
    ):
        w = Workflow()
        values = {"prompt": "<Picture 1> looks toward the camera with gentle movement.", "seconds": "5"}
        if "10020" in suffix:
            values["prompt"] = "<Picture 1> listens to <Audio 1> and waves gently."
        if "charswap" in suffix:
            values.update(prompt="Replace the person in the source clip with <Picture 1>, preserving motion.",
                          duration_mode="frames", frames=124)
        node = w.generate("Minimax_H3_ComfyUI_" + key, values, title="MiniMax H3 / " + suffix)
        reference(w, node, "IMAGE", "image1", 30, "Select a character reference")
        if audio:
            reference(w, node, "AUDIO", "audio1", 415, "Select a short audio track")
        if video:
            reference(w, node, "VIDEO", "video1", 415, "Select an MP4 source")
        video_example(w, node, "minimax-h3-comfyui-" + suffix)
    for model in spec.HEYGEN:
        for audio in (False, True):
            w = Workflow()
            node = w.generate("HeyGen_Avatar_6", {"model": model, "prompt": "" if audio else "Hello. Welcome to the studio.",
                "avatar": "Abigail Office Front" if audio else "Abigail Sofa Front"}, title=model)
            if audio:
                reference(w, node, "AUDIO", "audio", 30, "Select the speech audio to lip sync")
            video_example(w, node, model + ("-audio" if audio else "-text"))
    for mode in ("text", "image", "multiview"):
        w = Workflow()
        values = {"prompt": "A round ceramic teapot with one curved handle."} if mode == "text" else {
            "generate_type": "geometry", "face_count": 3000}
        node = w.generate("Miora_3D", values, title="Miora 3D / " + mode)
        if mode != "text":
            reference(w, node, "IMAGE", "image1", 30, "Select the front view")
        if mode == "multiview":
            reference(w, node, "IMAGE", "image2", 420, "Select the left view", "example_left.png")
            reference(w, node, "IMAGE", "image3", 810, "Select the right view", "example_right.png")
        preview_node = w.add("Preview3D", (1050, 60), (430, 460),
            [{"name": "model_file", "type": "FILE_3D", "link": None}], [], [], "Preview the locally saved 3D model")
        w.connect(node, 0, preview_node, "model_file")
        w.write("miora-3d-" + mode + ".json")


if __name__ == "__main__":
    main()
