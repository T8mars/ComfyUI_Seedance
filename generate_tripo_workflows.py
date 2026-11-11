"""One blank-key example per Tripo model, plus reusable-ID and texture variants."""

from generate_kling_v4_workflows import Workflow
from ComfyUI_Seedance.core import tripo


KEYS = {family: "Tripo_" + family.title() for family in tripo.MODELS}


def preview(workflow, node):
    target = workflow.add("Preview3D", (1080, 80), (480, 460), [{"name": "model_file", "type": "FILE_3D", "link": None}], [], [], "预览模型")
    workflow.connect(node, 0, target, "model_file")


def image(workflow, node, index, field=None):
    source = workflow.load("IMAGE", 50 + (index-1)*390, "选择" + ["正面", "左面", "背面", "右面"][index-1] + "图",
                           "tripo_" + tripo.VIEWS[index-1] + ".png")
    workflow.connect(source, 0, node, field or f"image{index}")


def main():
    for family, models in tripo.MODELS.items():
        for model in models:
            workflow = Workflow()
            values = {"model": model}
            if family == "generate" and "text-to-3d" in model:
                values["prompt"] = "A simple low-poly toy robot with a square head, two arms and two legs."
            if family in ("convert", "texture", "retopology", "mesh"):
                values["model_url"] = "https://example.com/model.glb"
            if model.endswith("retopology-v1"):
                values["face_limit"] = 10000
            if family == "texture":
                values.update(texture_prompt_mode="text", texture_prompt_text="Clean glossy blue ceramic with subtle surface detail.")
            if model.endswith("mesh-complete"):
                # A real Tripo ID is intentionally not stored in the example.
                values["tripo_segment_task_id"] = ""
            node = workflow.generate(KEYS[family], values, title=model)
            if model.endswith("mesh-complete"):
                segmentation = workflow.generate("Tripo_Mesh", {"model": "tripo-mesh-segment-v1", "model_url": "https://example.com/model.glb"},
                                                 pos=(440, 60), title="先分割：填写模型直链")
                node["pos"] = [1050, 60]
                workflow.connect_widget(segmentation, 4, node, "tripo_segment_task_id")
            if family == "generate" and "text-to-3d" not in model:
                for index in range(1, 3 if "multiview" in model else 2):
                    image(workflow, node, index)
            if family == "splat" or model.endswith("smartsegment"):
                image(workflow, node, 1)
            if family not in ("convert", "splat"):
                preview(workflow, node)
                if model.endswith("mesh-complete"):
                    workflow.nodes[-1]["pos"] = [1660, 60]
            workflow.write(model + "示例.json")
    # More than one reference input pattern is needed for retexturing and smart segmentation.
    for mode in ("image", "images"):
        workflow = Workflow()
        node = workflow.generate("Tripo_Texture", {"model_url": "https://example.com/model.glb", "texture_prompt_mode": mode},
                                 title="Tripo 重新贴图：" + ("单图" if mode == "image" else "四视图"))
        for index in range(1, 2 if mode == "image" else 5):
            image(workflow, node, index)
        preview(workflow, node)
        workflow.write("Tripo贴图" + ("单图" if mode == "image" else "四视图") + ".json")
    workflow = Workflow()
    node = workflow.generate("Tripo_Mesh", {"model": "tripo-mesh-smartsegment", "seg_type": "model", "model_url": "https://example.com/model.glb"}, title="Tripo GLB 智能分割")
    preview(workflow, node)
    workflow.write("Tripo智能分割模型输入.json")
    workflow = Workflow()
    generation = workflow.generate("Tripo_Generate", {"model": "tripo-p-p1-text-to-3d", "face_limit": 1000,
        "texture": "false", "pbr": "false", "prompt": "A simple low-poly toy robot with a square head, two arms and two legs."},
        pos=(440, 60), title="1 生成模型")
    segmentation = workflow.generate("Tripo_Mesh", {"model": "tripo-mesh-segment-v1"}, pos=(1050, 60), title="2 网格分割")
    completion = workflow.generate("Tripo_Mesh", {"model": "tripo-mesh-complete", "completion_mode": "quick_cap"},
                                   pos=(1660, 60), title="3 部件补全")
    workflow.connect_widget(generation, 1, segmentation, "model_url")
    workflow.connect_widget(segmentation, 4, completion, "tripo_segment_task_id")
    preview(workflow, completion)
    workflow.nodes[-1]["pos"] = [2270, 60]
    workflow.write("Tripo生成分割补全连线.json")


if __name__ == "__main__":
    main()
