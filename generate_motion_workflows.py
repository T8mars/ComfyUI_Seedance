"""Generate Motion Video creation and connected revision examples for both models."""

from generate_latest_model_workflows import _config, _node, _workflow
from generate_qwen21_animate_workflows import _save


def _motion(node_id, model, operation, config_link, video_link, task_link=None):
    inputs = [{"name": "api_config", "shape": 7, "type": "SEEDANCE_CONFIG", "link": config_link}]
    if operation == "revise":
        inputs.append({"name": "revise_from", "type": "STRING", "link": task_link,
                       "widget": {"name": "revise_from"}})
    outputs = [
        {"name": "video", "type": "VIDEO", "links": [video_link]},
        {"name": "video_url", "type": "STRING", "links": None},
        {"name": "task_id", "type": "STRING", "links": [task_link] if task_link and operation == "generate" else None},
    ] + [{"name": name, "type": "STRING", "links": None} for name in (
        "response", "cover_url", "preview_url", "html_preview_url", "subtitle_url",
        "storyboard", "fallback_scenes",
    )]
    widgets = [
        model, operation,
        "Create a simple 15-second Canvas 2D motion graphic. Three short scenes show emerald circles and coral squares moving smoothly on black. Use only the short title T8 in the last scene, centered with generous margins. No other text, no counters. Use layer='2d' for every scene.",
        15, "16:9", "720p", "swiss-minimal", "T8", "",
        "", "", "en", "auto", "", "",
        "Revise only the main content scene displaying the title T8, not end-card: replace T8 with OK. Keep short centered text, generous margins, 2d layers and all other scenes unchanged." if operation == "revise" else "",
        False, 0, "fixed",
    ]
    node = _node(node_id, "Zhenzhen_Motion_Video", (400 if node_id == 2 else 1370, 60),
                 (510, 1030), node_id - 1, inputs, outputs, widgets,
                 ("Pro" if model.endswith("-pro") else "Standard") + (" 动效视频修订" if operation == "revise" else " 动效视频生成"))
    return node


def motion_workflow(pro=False, revision=False):
    model = "zhenzhen/motion-video" + ("-pro" if pro else "")
    filename = "MotionVideo" + ("Pro" if pro else "Standard") + ("成片修订.json" if revision else "动效生成.json")
    config, edge = _config(1, 2, 0)
    nodes = [config, _motion(2, model, "generate", 1, 2, 4 if revision else None)]
    save = _save(3, "VIDEO", 2, "保存原始成片")
    save["widgets_values"][0] = "seedance/motion_video_original"
    nodes.append(save)
    links = [edge, [2, 2, 0, 3, 0, "VIDEO"]]
    if revision:
        config["outputs"][0]["links"].append(3)
        nodes.append(_motion(4, model, "revise", 3, 5, 4))
        revised_save = _save(5, "VIDEO", 5, "保存修订成片")
        revised_save["pos"] = [1980, 120]
        revised_save["widgets_values"][0] = "seedance/motion_video_revised"
        nodes.append(revised_save)
        links.extend(([3, 1, 0, 4, 0, "SEEDANCE_CONFIG"], [4, 2, 2, 4, 1, "STRING"], [5, 4, 0, 5, 0, "VIDEO"]))
    _workflow(filename, nodes, links)


if __name__ == "__main__":
    for pro in (False, True):
        for revision in (False, True):
            motion_workflow(pro, revision)
