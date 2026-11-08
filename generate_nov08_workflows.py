"""Generate blank-key examples and append only new legacy widget defaults."""

import json
from pathlib import Path

from generate_kling_v4_workflows import Workflow
from generate_image26_workflows import save_image


ROOT = Path(__file__).resolve().parent


def main():
    for path in (ROOT / "examples").glob("*.json"):
        workflow = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for node in workflow.get("nodes", []):
            kind = node["type"].removeprefix("SeedanceConcurrent_").removesuffix("_Submit")
            if kind not in ("Zhenzhen_Image_G26", "Kling_V4_Omni"):
                continue
            from ComfyUI_Seedance import nodes
            schema = nodes.NODE_CLASS_MAPPINGS[kind].INPUT_TYPES()
            count = sum(1 for group in schema.values() for spec in group.values()
                        if isinstance(spec[0], list) or spec[0] in {"STRING", "INT", "FLOAT", "BOOLEAN"}) + 1
            values = node.get("widgets_values", [])
            if len(values) == count - 1:
                values.append("api_default" if kind == "Zhenzhen_Image_G26" else "kling-v4-omni")
                changed = True
        if changed:
            path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prompt = "A small original blue toy robot raises one arm in a mint studio. Locked camera, gentle motion."
    for model, kind in (("zhenzhen-video-kling-v4-flash", "Kling_V4_Omni"),
                        ("zhenzhen-video-g-omni-1.2-flash-lowprice", "Zhenzhen_Video_G_Omni_1_2_Flash_Lowprice")):
        for mode in ("text", "images", "video", "url"):
            workflow = Workflow()
            values = {"model": model, "prompt": prompt, "seconds": 3,
                      "resolution": "720p" if kind == "Kling_V4_Omni" else "360p"}
            if mode == "url":
                values["video_urls"] = "https://example.com/reference.mp4"
            node = workflow.generate(kind, values, title=model)
            if mode == "images":
                for i in (1, 2):
                    workflow.connect(workflow.load("IMAGE", 30 + (i-1)*420, f"选择参考图{i}", f"reference_{i}.png"), 0, node, f"image{i}")
            if mode == "video":
                workflow.connect(workflow.load("VIDEO", 30, "选择参考视频"), 0, node, "video1")
            workflow.save_video(node, model + "_" + mode)
            workflow.write(model + {"text": "文生视频.json", "images": "多图参考.json", "video": "本地视频参考.json", "url": "网址视频参考.json"}[mode])
    for resolution, version in (("2k", "flare"), ("4k", "sunburst")):
        workflow = Workflow()
        node = workflow.generate("Zhenzhen_Image_G26", {"model": "zhenzhen-image-g-v2.6-lowprice",
            "prompt": "A white ceramic cup on a mint tabletop, clean product photography.", "resolution": resolution,
            "quality": "low", "version": version, "output_format": "png"}, title="G 2.6 LowPrice " + resolution)
        save_image(workflow, node, "seedance/g26_lowprice_" + resolution)
        workflow.write("zhenzhen-image-g-v2.6-lowprice" + resolution.upper() + "文生图.json")


if __name__ == "__main__":
    main()
