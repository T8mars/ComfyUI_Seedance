"""Create one credential-free native 3D workflow per available model."""

from generate_kling_v4_workflows import Workflow


def main():
    families = (
        ("Hitem3D_V2", ["hitem3d-v2-image-to-3d", "hitem3d-v2-multi-image-to-3d"]),
        ("Hitem3D_Portrait_V2_1", ["hitem3d-portrait-v2.1-image-to-3d", "hitem3d-portrait-v2.1-multi-image-to-3d"]),
        ("Meshy_6_Global", ["meshy-6-global-image-to-3d", "meshy-6-global-text-to-3d"]),
    )
    for kind, models in families:
        for model in models:
            workflow = Workflow()
            multi = "multi-image" in model
            text = model.endswith("text-to-3d")
            values = {"model": model}
            if text:
                values["prompt"] = "A simple round ceramic teapot with a short spout, a single curved handle, and a fitted lid."
            node = workflow.generate(kind, values, pos=(430, 60), title=model)
            for i in range(1, 1 if text else 3 if multi else 2):
                source = workflow.load("IMAGE", 40 if i == 1 else 540,
                    "选择正面图" if i == 1 else "选择背面图，不要重复正面图",
                    "example_front.png" if i == 1 else "example_back.png")
                workflow.connect(source, 0, node, f"image{i}")
            preview = workflow.add("Preview3D", (1050, 60), (420, 400),
                [{"name": "model_file", "type": "FILE_3D", "link": None}], [], [], "预览 3D 模型")
            save = workflow.add("SaveGLB", (1050, 520), (360, 150),
                [{"name": "mesh", "type": "FILE_3D", "link": None}], [], ["3d/" + model], "保存 3D 模型")
            workflow.connect(node, 0, preview, "model_file")
            workflow.connect(node, 0, save, "mesh")
            workflow.write(model + ("文生3D.json" if text else "多图生3D.json" if multi else "图生3D.json"))


if __name__ == "__main__":
    main()
