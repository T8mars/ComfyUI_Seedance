"""Blank-key Seedream 5.5 and Seedance draft-to-video examples."""

from generate_kling_v4_workflows import Workflow
from ComfyUI_Seedance import nodes
from ComfyUI_Seedance.core import seedream55


def save_image(workflow, source, prefix, alpha=False):
    if alpha:
        joined = workflow.add("JoinImageWithAlpha", (1040, 80), (270, 100), [
            {"name": "image", "type": "IMAGE", "link": None}, {"name": "alpha", "type": "MASK", "link": None}],
            [("image", "IMAGE")], [], "保留各图层透明通道")
        workflow.connect(source, 0, joined, "image")
        workflow.connect(source, 1, joined, "alpha")
        source = joined
    save = workflow.add("SaveImage", (1390 if alpha else 1080, 80), (310, 250), [{"name": "images", "type": "IMAGE", "link": None}],
                        [], ["seedance/" + prefix], "保存所有图层" if alpha else "保存图片")
    workflow.connect(source, 0, save, "images")


def save_video(workflow, node, prefix, pos=(1080, 80)):
    save = workflow.add("SaveVideo", pos, (310, 250), [{"name": "video", "type": "VIDEO", "link": None}], [],
                        ["seedance/"+prefix, "auto", "auto"], "保存视频")
    workflow.connect(node, 0, save, "video")


def main():
    for model in seedream55.IMAGE_MODELS:
        workflow = Workflow()
        edit = model.endswith("-i2i")
        node = workflow.generate("Seedream_5_5_Image", {"model": model, "resolution": "1k", "prompt":
            "Keep the subject and composition, change the background to a bright photographic studio." if edit else
            "A red ceramic cup beside a green leaf, clean studio product photography, no text."}, title=model)
        if edit:
            workflow.connect(workflow.load("IMAGE", 40, "选择编辑参考图"), 0, node, "image1")
        save_image(workflow, node, model)
        workflow.write(model + ("图像编辑.json" if edit else "文生图.json"))
    for model in seedream55.LAYER_MODELS:
        workflow = Workflow()
        node = workflow.generate("Seedream_5_5_Layer_Decomposition", {"model": model, "max_images": 30}, title=model)
        workflow.connect(workflow.load("IMAGE", 40, "选择待分层图片"), 0, node, "image")
        save_image(workflow, node, model, alpha=True)
        workflow.write(model + "图像分层.json")
    workflow = Workflow()
    node = workflow.generate("Seedream_5_5_Image", {"background": "transparent", "prompt": "A single green leaf with fine veins, isolated on a transparent background, no text."}, title="Seedream 5.5 透明PNG")
    save_image(workflow, node, "seedream55_transparent")
    workflow.write("Seedream55透明PNG.json")
    for index, model in enumerate(nodes.Seedance25DraftToVideo.MODELS):
        workflow = Workflow()
        node = workflow.generate("Seedance_2_5_Draft_To_Video", {"model": model}, title="填写同账号、同区域已完成样片task_id")
        save_video(workflow, node, model)
        workflow.write(model + "样片转高清.json")
        workflow = Workflow()
        draft = workflow.generate("Seedance_2_5_Video", {"model": nodes.SEEDANCE25_T2V_MODELS[index], "draft": True,
            "prompt": "A blue ball rolls slowly across a clean white tabletop, locked camera.", "seconds": "4", "resolution": "480p"}, title="480p 样片")
        enhance = workflow.generate("Seedance_2_5_Draft_To_Video", {"model": model}, pos=(1070, 60), title="native1080p 成片")
        workflow.connect_widget(draft, 2, enhance, "draft_task_id")
        save_video(workflow, draft, model+"_draft", pos=(440, 900))
        save_video(workflow, enhance, model+"_enhanced", pos=(1680, 80))
        workflow.write(model + "样片成片连线.json")


if __name__ == "__main__":
    main()
