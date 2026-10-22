"""Generate credential-free NB Lowprice and Doubao training/synthesis examples."""

import sys
from pathlib import Path

from generate_latest_model_workflows import PLUGIN, _config, _node, _workflow
from generate_qwen21_animate_workflows import _generator, _save, _source

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import nodes as plugin_nodes


def nb_workflow(model, count):
    generator_id, config_link, output_link = count + 2, count + 1, count + 2
    config, edge = _config(config_link, generator_id, 14)
    config["pos"] = [40, 40 + count * 370] if count else [40, 250]
    graph, links = [config], [edge]
    for index in range(1, count + 1):
        source = _source(index + 1, "IMAGE", index, 40 + (index - 1) * 370)
        source["title"] = f"选择参考图 {index}"
        graph.append(source)
        links.append([index, index + 1, 0, generator_id, index - 1, "IMAGE"])
    inputs = [{"name": f"image{i}", "type": "IMAGE", "shape": 7, "link": i if i <= count else None}
              for i in range(1, 15)] + [{"name": "api_config", "type": "SEEDANCE_CONFIG", "shape": 7, "link": config_link}]
    prompt = ["白色桌面上的蓝色陶瓷茶壶，柔和的摄影棚光线", "把茶壶改为绿色，保留形状和构图",
              "保留图1的主体，参考图2的配色和光线，制作统一的产品摄影"][count]
    mode = ["文生图", "图像编辑", "多图合成"][count]
    graph.append(_generator(generator_id, "Zhenzhen_Image_NB_Lowprice", "IMAGE", inputs, output_link,
                            [model, prompt, "1k", "auto" if count else "1:1", False, 0, "fixed"], f"NB Lowprice {mode}"))
    save = _save(generator_id + 1, "IMAGE", output_link, "保存生成图片")
    save["widgets_values"] = [f"seedance/{model}_{count}"]
    graph.append(save)
    links.append([output_link, generator_id, 0, save["id"], 0, "IMAGE"])
    _workflow(f"{model}{mode}.json", graph, links)


def voice_widgets(model):
    inputs = plugin_nodes.DoubaoVoiceCloneICL.INPUT_TYPES()
    result = [spec[1]["default"] for spec in inputs["required"].values()]
    result[0] = model
    result[1] = "你好，这是音色训练后的试听。" if model == "doubao-voice-clone" else "你好，这是使用训练音色合成的语音。"
    return result + [False, 0, "fixed"]


def voice_node(node_id, model, config_link, audio_link=None, speaker_link=None, x=400):
    inputs = [
        {"name": "reference_audio", "type": "AUDIO", "shape": 7, "link": audio_link},
        {"name": "api_config", "type": "SEEDANCE_CONFIG", "shape": 7, "link": config_link},
    ]
    if speaker_link:
        inputs.append({"name": "speaker", "type": "STRING", "link": speaker_link, "widget": {"name": "speaker"}})
    node = _node(node_id, "Doubao_Voice_Clone_ICL", (x, 80), (480, 580), node_id,
                 inputs, [{"name": name, "type": kind, "links": None}
                          for name, kind in zip(plugin_nodes.DoubaoVoiceCloneICL.RETURN_NAMES,
                                                plugin_nodes.DoubaoVoiceCloneICL.RETURN_TYPES)],
                 voice_widgets(model))
    node["properties"]["aux_id"] = PLUGIN
    return node


def audio_save(node_id, source_id, link_id, x):
    return _node(node_id, "SaveAudio", (x, 80), (290, 160), node_id,
                 [{"name": "audio", "type": "AUDIO", "link": link_id}], [],
                 [f"audio/doubao_{source_id}"])


def voice_workflow(mode):
    clone = mode != "synthesis"
    chain = mode == "chain"
    config, edge = _config(1, 3 if clone else 2, 1)
    config["pos"] = [40, 300]
    graph, links = [config], [edge]
    if clone:
        graph.append(_node(2, "LoadAudio", (40, 60), (300, 160), 1, [],
                           [{"name": "AUDIO", "type": "AUDIO", "links": [2]}], ["example.wav", None, ""], "选择参考人声"))
        links.append([2, 2, 0, 3, 0, "AUDIO"])
    source_id = 3 if clone else 2
    generator = voice_node(source_id, "doubao-voice-clone" if clone else "doubao-seed-icl-2.0", 1, 2 if clone else None)
    generator["outputs"][0]["links"] = [3]
    graph.extend([generator, audio_save(4, source_id, 3, 950)])
    links.append([3, source_id, 0, 4, 0, "AUDIO"])
    if chain:
        config["outputs"][0]["links"].append(4)
        generator["outputs"][3]["links"] = [5]
        synthesis = voice_node(5, "doubao-seed-icl-2.0", 4, speaker_link=5, x=1330)
        synthesis["outputs"][0]["links"] = [6]
        graph.extend([synthesis, audio_save(6, 5, 6, 1890)])
        links.extend([[4, 1, 0, 5, 1, "SEEDANCE_CONFIG"], [5, 3, 3, 5, 2, "STRING"], [6, 5, 0, 6, 0, "AUDIO"]])
    filename = {"clone": "doubao-voice-clone音色训练.json", "synthesis": "doubao-seed-icl-2.0语音合成.json",
                "chain": "doubao音色训练到ICL语音合成.json"}[mode]
    _workflow(filename, graph, links)


if __name__ == "__main__":
    for model in plugin_nodes.ZHENZHEN_IMAGE_NB_LOWPRICE_MODELS:
        for count in (0, 1, 2):
            nb_workflow(model, count)
    for mode in ("clone", "synthesis", "chain"):
        voice_workflow(mode)
